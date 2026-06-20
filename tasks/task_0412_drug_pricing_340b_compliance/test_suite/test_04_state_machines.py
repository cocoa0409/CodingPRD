"""State-machine transitions and cross-entity state dependencies: covered-entity
lifecycle, dispense reverse/reinstate/disclosure, audit-finding review loop, contract-
pharmacy lifecycle, termination cascade, and the recertify gate.

Design sources: Difficulty/non_linear_state_machine/*, Difficulty/cross_entity_state_dependency/*,
and Corner/state_machines/*.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_dispense_payload, create_audit_finding_payload, create_self_disclosure_payload,
    create_and_approve_covered_entity, create_covered_entity,
    create_drug_with_published_ceiling, create_prescriber, create_patient,
    setup_dispensable_scenario, record_dispense,
    create_open_hrsa_finding, create_under_review_hrsa_finding,
    setup_ce_with_contract_pharmacy,
)

CO = TEST_USERS["compliance_officer_headers"]
HRSA = TEST_USERS["hrsa_auditor_headers"]
PHARM = TEST_USERS["pharmacy_operator_headers"]


# ---------------------------------------------------------------------------
# Dispense parallel dimensions: classification fixed, status cycles
# ---------------------------------------------------------------------------
def test_reverse_keeps_classification_changes_status(api):
    """PRD §3.7: "A `PharmacyOperator` may reverse a dispense that is currently
    `DISPENSED`, moving it `DISPENSED → REVERSED`."

    Design: Difficulty/non_linear_state_machine/dispense_parallel_dimensions_reverse_reinstate_cycle
    """
    scenario = setup_dispensable_scenario(with_accumulator=True)
    disp = record_dispense(scenario, quantity_units=10)
    rev = validate_success(api.reverse_dispense(disp["id"], PHARM), 200)
    assert rev["dispense_status"] == "REVERSED"
    assert rev["classification_status"] == "CLASSIFIED_340B"


def test_reinstate_restores_dispensed_keeps_classification(api):
    """PRD §3.7: "A reversed dispense may be reinstated by a `PharmacyOperator`, moving it
    `REVERSED → DISPENSED`, but only while the owning covered entity's `registration_status`
    is `ACTIVE`".

    Design: Difficulty/non_linear_state_machine/dispense_parallel_dimensions_reverse_reinstate_cycle
    """
    scenario = setup_dispensable_scenario(with_accumulator=True)
    disp = record_dispense(scenario, quantity_units=10)
    validate_success(api.reverse_dispense(disp["id"], PHARM), 200)
    reins = validate_success(api.reinstate_dispense(disp["id"], PHARM), 200)
    assert reins["dispense_status"] == "DISPENSED"
    assert reins["classification_status"] == "CLASSIFIED_340B"
    acc = validate_success(api.get_accumulator(scenario["accumulator"]["id"], PHARM), 200)
    assert acc["accrued_units"] == 10  # net zero across reverse+reinstate


# ---------------------------------------------------------------------------
# Audit finding revision loop UNDER_REVIEW -> DISPUTED -> UNDER_REVIEW
# ---------------------------------------------------------------------------
def test_dispute_moves_under_review_to_disputed(api):
    """PRD §3.8: "From `UNDER_REVIEW`, a `ComplianceOfficer` may dispute the finding,
    moving it `UNDER_REVIEW → DISPUTED`".

    Design: Difficulty/non_linear_state_machine/audit_finding_under_review_disputed_revision_loop
    """
    scenario = setup_dispensable_scenario()
    disp = record_dispense(scenario, quantity_units=6)
    finding = create_under_review_hrsa_finding(scenario, disp, assessed_units=6)
    disputed = validate_success(api.dispute_audit_finding(finding["id"], CO), 200)
    assert disputed["finding_status"] == "DISPUTED"


def test_disputed_back_to_under_review_closes_loop(api):
    """PRD §3.8: "A disputed finding can be sent back to review by an auditor, moving it
    `DISPUTED → UNDER_REVIEW`; this revision loop `UNDER_REVIEW → DISPUTED → UNDER_REVIEW`
    has no fixed bound, and each dispute requires a prior review."

    Design: Difficulty/non_linear_state_machine/audit_finding_under_review_disputed_revision_loop
    """
    scenario = setup_dispensable_scenario()
    disp = record_dispense(scenario, quantity_units=6)
    finding = create_under_review_hrsa_finding(scenario, disp, assessed_units=6)
    validate_success(api.dispute_audit_finding(finding["id"], CO), 200)
    review2 = validate_success(api.start_review_audit_finding(finding["id"], HRSA), 200)
    assert review2["finding_status"] == "UNDER_REVIEW"


# ---------------------------------------------------------------------------
# Cross-entity state dependency: dispense requires CE ACTIVE
# ---------------------------------------------------------------------------
def test_dispense_against_pending_ce_rejected(api):
    """PRD §3.5: "The covered entity must be `ACTIVE`; a dispense against a non-active
    entity is rejected with `ERR_CE_NOT_ACTIVE` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/dispense_requires_covered_entity_active
    """
    ce = create_covered_entity(medicaid_billing_mode="CARVE_OUT")  # PENDING
    drug = create_drug_with_published_ceiling(amp=4000, ura=1500)
    presc = create_prescriber(ce["id"], relationship_type="EMPLOYED")
    pat = create_patient(ce["id"], medicaid_ffs_enrolled=False)
    resp = api.create_dispense(create_dispense_payload(
        ce["id"], pat["id"], presc["id"], drug["id"], quantity_units=5, quarter="2026Q2"), PHARM)
    validate_error(resp, ApiErrorId.ERR_CE_NOT_ACTIVE.value, expected_status=409)


def test_dispense_succeeds_once_ce_active(api):
    """PRD §3.1: "Approval, available only from `PENDING`, advances `registration_status`
    to `ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/dispense_requires_covered_entity_active
    """
    ce = create_covered_entity(medicaid_billing_mode="CARVE_OUT")  # PENDING
    drug = create_drug_with_published_ceiling(amp=4000, ura=1500)
    presc = create_prescriber(ce["id"], relationship_type="EMPLOYED")
    pat = create_patient(ce["id"], medicaid_ffs_enrolled=False)
    validate_success(api.approve_covered_entity(ce["id"], HRSA), 200)
    disp = validate_success(api.create_dispense(create_dispense_payload(
        ce["id"], pat["id"], presc["id"], drug["id"], quantity_units=5, quarter="2026Q2"), PHARM), 201)
    assert disp["classification_status"] == "CLASSIFIED_340B"


# ---------------------------------------------------------------------------
# Cross-entity state dependency: recertify gated on compliance_posture
# ---------------------------------------------------------------------------
def test_recertify_blocked_by_open_finding(api):
    """PRD §3.1: "From `RECERT_DUE`, the `ComplianceOfficer` completes recertification,
    returning it `RECERT_DUE → ACTIVE` and incrementing `recert_period_index` by one — but
    only when `compliance_posture` is `GOOD`; if any audit finding is still open or any
    repayment is still outstanding the posture is `FLAGGED` and the attempt is blocked."

    Design: Difficulty/cross_entity_state_dependency/recertify_blocked_by_open_audit_finding_posture
    """
    scenario = setup_dispensable_scenario()
    disp = record_dispense(scenario, quantity_units=6)
    create_open_hrsa_finding(scenario, disp, assessed_units=6)  # flips posture FLAGGED
    validate_success(api.flag_recert_covered_entity(scenario["ce"]["id"], HRSA), 200)
    resp = api.recertify_covered_entity(scenario["ce"]["id"], CO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_recertify_succeeds_after_finding_dismissed(api):
    """PRD §3.1: "From `RECERT_DUE`, the `ComplianceOfficer` completes recertification,
    returning it `RECERT_DUE → ACTIVE` and incrementing `recert_period_index` by one".

    Design: Difficulty/cross_entity_state_dependency/recertify_blocked_by_open_audit_finding_posture
    """
    scenario = setup_dispensable_scenario()
    disp = record_dispense(scenario, quantity_units=6)
    finding = create_open_hrsa_finding(scenario, disp, assessed_units=6)
    validate_success(api.flag_recert_covered_entity(scenario["ce"]["id"], HRSA), 200)
    validate_success(api.dismiss_audit_finding(finding["id"], HRSA), 200)
    ok = validate_success(api.recertify_covered_entity(scenario["ce"]["id"], CO), 200)
    assert ok["registration_status"] == "ACTIVE"
    assert ok["recert_period_index"] == 1


# ---------------------------------------------------------------------------
# Corner: invalid transitions and terminal lockdown
# ---------------------------------------------------------------------------
def test_approve_already_active_ce_invalid_state(api):
    """PRD §3.1: "Any transition attempted from a state that does not permit it is rejected
    with `ERR_INVALID_STATE` (HTTP 409); the recertify, approve, deny, flag, and terminate
    operations all share that guard."

    Design: Corner/state_machines/approve_already_active_ce_invalid_state
    """
    ce = create_and_approve_covered_entity()
    resp = api.approve_covered_entity(ce["id"], HRSA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_reverse_already_reversed_dispense_invalid_state(api):
    """PRD §3.7: "A `PharmacyOperator` may reverse a dispense that is currently
    `DISPENSED`, moving it `DISPENSED → REVERSED`."

    Design: Corner/state_machines/reverse_already_reversed_dispense_invalid_state
    """
    scenario = setup_dispensable_scenario(with_accumulator=True)
    disp = record_dispense(scenario, quantity_units=5)
    validate_success(api.reverse_dispense(disp["id"], PHARM), 200)
    resp = api.reverse_dispense(disp["id"], PHARM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_dispute_open_finding_invalid_state(api):
    """PRD §3.8: "From `UNDER_REVIEW`, a `ComplianceOfficer` may dispute the finding,
    moving it `UNDER_REVIEW → DISPUTED`".

    Design: Corner/state_machines/dispute_from_open_finding_invalid_state
    """
    scenario = setup_dispensable_scenario()
    disp = record_dispense(scenario, quantity_units=4)
    finding = create_open_hrsa_finding(scenario, disp, assessed_units=4)  # OPEN, no review
    resp = api.dispute_audit_finding(finding["id"], CO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_resolve_finding_without_repayment_rejected(api):
    """PRD §3.8: "An auditor resolves an `UNDER_REVIEW` finding, moving it
    `UNDER_REVIEW → RESOLVED`, but only when a repayment obligation with `source_kind` of
    `AUDIT_FINDING` referencing this finding already exists; resolving without one set up is
    rejected with `ERR_REPAYMENT_REQUIRED` (HTTP 409)."

    Design: Corner/state_machines/resolve_finding_without_repayment_rejected
    """
    scenario = setup_dispensable_scenario()
    disp = record_dispense(scenario, quantity_units=4)
    finding = create_under_review_hrsa_finding(scenario, disp, assessed_units=4)
    resp = api.resolve_audit_finding(finding["id"], HRSA)
    validate_error(resp, ApiErrorId.ERR_REPAYMENT_REQUIRED.value, expected_status=409)


def test_disclosed_dispense_cannot_be_reversed(api):
    """PRD §3.7: "`DISCLOSED` is terminal: a disclosed dispense can be neither reversed nor
    reinstated."

    Design: Corner/state_machines/terminal_disclosed_dispense_cannot_reverse
    """
    scenario = setup_dispensable_scenario()
    disp = record_dispense(scenario, quantity_units=4)
    validate_success(
        api.create_self_disclosure(
            scenario["ce"]["id"],
            create_self_disclosure_payload(disp["id"], finding_type="INELIGIBLE_PATIENT", assessed_units=4),
            CO), 201)
    resp = api.reverse_dispense(disp["id"], PHARM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_terminate_ce_cascades_contract_pharmacy(api):
    """PRD §3.1: "termination cascades to every contract-pharmacy arrangement of that
    entity whose `arrangement_status` is `ACTIVE`, driving each of those to `TERMINATED`."

    Design: Corner/state_machines/terminate_ce_cascades_contract_pharmacy_termination
    """
    ce, cp = setup_ce_with_contract_pharmacy(
        npi="3030303030", effective_start="2026-01-01", effective_end="2026-12-31")
    term = validate_success(api.terminate_covered_entity(ce["id"], HRSA), 200)
    assert term["registration_status"] == "TERMINATED"
    cp_after = validate_success(api.get_contract_pharmacy(cp["id"], CO), 200)
    assert cp_after["arrangement_status"] == "TERMINATED"


def test_reactivate_active_contract_pharmacy_invalid_state(api):
    """PRD §3.4: "reactivate a `SUSPENDED` one (`SUSPENDED → ACTIVE`, permitted only while
    the owning entity's `registration_status` is `ACTIVE`)".

    Design: Corner/state_machines/reactivate_contract_pharmacy_from_active_invalid_state
    """
    ce, cp = setup_ce_with_contract_pharmacy(
        npi="3131313131", effective_start="2026-01-01", effective_end="2026-12-31")
    resp = api.reactivate_contract_pharmacy(cp["id"], CO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

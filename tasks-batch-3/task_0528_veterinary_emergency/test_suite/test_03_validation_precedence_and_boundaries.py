"""Validation-precedence conflicts and numeric boundary precision.

Difficulty queue: priority_pair_validation_conflict, boundary_precision_check.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_finance_coordinator_headers,
    make_clinician_dvm_headers,
    make_owner_headers,
    register_and_triage,
    create_and_issue_estimate,
    setup_visit_with_active_auth,
    setup_visit_in_treatment,
    schedule_procedure,
    perform_procedure,
    admit_hospitalization,
    get_visit_state,
    api_client,
)


def test_approve_already_active_state_beats_fiscal(api):
    """PRD §2.6: "fifth, the target resource being in the required state for the
    requested transition (`ERR_INVALID_STATE`); ... tenth, fiscal ceiling checks"
    PRD §3.5: "Approving requires the Authorization to be `PENDING`
    (`ERR_INVALID_STATE`)"

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_fiscal_on_approve
    """
    finance = make_finance_coordinator_headers()
    owner = make_owner_headers("owner-8")
    _, visit, est, auth = setup_visit_with_active_auth(
        triage_level="YELLOW", unit_price_cents=300000,
        approved_ceiling_cents=386100, owner_user_id="owner-8")
    # Second approve on an already-ACTIVE authorization: state check must win.
    resp = api.approve_authorization(visit["id"], auth["id"], owner)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_approve_already_active_not_fiscal_error(api):
    """PRD §2.6: "Where a rule's own trigger condition is more specific than a
    general check above it, the specific rule is what applies to that operation,
    but the general-to-specific ordering above governs which error surfaces when
    more than one applies."
    PRD §3.5: "Approving requires the Authorization to be `PENDING`
    (`ERR_INVALID_STATE`)"

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_fiscal_on_approve
    """
    owner = make_owner_headers("owner-8b")
    _, visit, est, auth = setup_visit_with_active_auth(
        triage_level="YELLOW", unit_price_cents=300000,
        approved_ceiling_cents=386100, owner_user_id="owner-8b")
    resp = api.approve_authorization(visit["id"], auth["id"], owner)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_finalize_with_scheduled_procedure_charges_pending(api):
    """PRD §3.9: "A `FinanceCoordinator` finalizes the invoice, which requires it
    to be `OPEN` (`ERR_INVALID_STATE`) and requires that no `SCHEDULED` Procedure
    and no `ACTIVE` Hospitalization remain on the Visit — outstanding work of
    either kind blocks finalization with `ERR_CHARGES_PENDING`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_safety_beats_fiscal_on_finalize
    """
    finance = make_finance_coordinator_headers()
    _, visit, est, auth = setup_visit_in_treatment(
        triage_level="YELLOW", unit_price_cents=50000,
        approved_ceiling_cents=100000, owner_user_id="owner-9",
        chief_complaint="abscess")
    schedule_procedure(visit["id"], modality="SURGERY", resource_room="OR_1",
                       start_at="2026-05-01T09:00:00Z",
                       end_at="2026-05-01T10:00:00Z", price_cents=40000)
    resp = api.finalize_invoice(visit["id"], finance)
    validate_error(resp, ApiErrorId.ERR_CHARGES_PENDING, expected_status=409)


def test_finalize_charges_pending_surfaces_before_fiscal(api):
    """PRD §3.9: "outstanding work of either kind blocks finalization with
    `ERR_CHARGES_PENDING`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_safety_beats_fiscal_on_finalize
    """
    finance = make_finance_coordinator_headers()
    _, visit, est, auth = setup_visit_in_treatment(
        triage_level="YELLOW", unit_price_cents=50000,
        approved_ceiling_cents=100000, owner_user_id="owner-9b")
    schedule_procedure(visit["id"], modality="SURGERY", resource_room="OR_2",
                       start_at="2026-05-01T09:00:00Z",
                       end_at="2026-05-01T10:00:00Z", price_cents=40000)
    resp = api.finalize_invoice(visit["id"], finance)
    validate_error(resp, ApiErrorId.ERR_CHARGES_PENDING, expected_status=409)


def test_perform_at_ceiling_succeeds_over_ceiling_rejected(api):
    """PRD §3.8: "the Visit's current `charges_committed_cents` plus this
    procedure's `price_cents` must be less than or equal to the Visit's
    `authorized_ceiling_cents`. If performing would push committed charges past
    the ceiling, it is rejected with `ERR_CEILING_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/bpc_ceiling_exceeded_strict_greater
    """
    dvm = make_clinician_dvm_headers()
    _, visit, est, auth = setup_visit_in_treatment(
        triage_level="YELLOW", unit_price_cents=20000,
        approved_ceiling_cents=30000, owner_user_id="owner-10",
        chief_complaint="wound")
    # committed 20000
    p1 = schedule_procedure(visit["id"], modality="IMAGING_CT",
                            resource_room="CT_SUITE",
                            start_at="2026-05-01T09:00:00Z",
                            end_at="2026-05-01T09:30:00Z", price_cents=20000)
    perform_procedure(visit["id"], p1["id"])
    # 20000 + 10000 == 30000 (<= ceiling) succeeds
    p2 = schedule_procedure(visit["id"], modality="IMAGING_MRI",
                            resource_room="MRI_SUITE",
                            start_at="2026-05-01T10:00:00Z",
                            end_at="2026-05-01T10:30:00Z", price_cents=10000)
    perform_procedure(visit["id"], p2["id"])
    # 30000 + 1 == 30001 (> ceiling) rejected
    p3 = schedule_procedure(visit["id"], modality="SURGERY", resource_room="OR_1",
                            start_at="2026-05-01T11:00:00Z",
                            end_at="2026-05-01T11:30:00Z", price_cents=1)
    resp = api.perform_procedure(visit["id"], p3["id"], dvm)
    validate_error(resp, ApiErrorId.ERR_CEILING_EXCEEDED, expected_status=409)
    v = get_visit_state(visit["id"])
    assert v["charges_committed_cents"] == 30000, (
        f"committed must stay 30000 after rejected perform, got {v['charges_committed_cents']}")


def test_perform_committed_unchanged_after_rejection(api):
    """PRD §3.8: "If performing would push committed charges past the ceiling, it
    is rejected with `ERR_CEILING_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/bpc_ceiling_exceeded_strict_greater
    """
    dvm = make_clinician_dvm_headers()
    _, visit, est, auth = setup_visit_in_treatment(
        triage_level="YELLOW", unit_price_cents=20000,
        approved_ceiling_cents=30000, owner_user_id="owner-10b")
    p1 = schedule_procedure(visit["id"], modality="IMAGING_CT",
                            resource_room="CT_SUITE",
                            start_at="2026-05-01T09:00:00Z",
                            end_at="2026-05-01T09:30:00Z", price_cents=20000)
    perform_procedure(visit["id"], p1["id"])
    p2 = schedule_procedure(visit["id"], modality="IMAGING_MRI",
                            resource_room="MRI_SUITE",
                            start_at="2026-05-01T10:00:00Z",
                            end_at="2026-05-01T10:30:00Z", price_cents=10000)
    perform_procedure(visit["id"], p2["id"])
    p3 = schedule_procedure(visit["id"], modality="SURGERY", resource_room="OR_1",
                            start_at="2026-05-01T11:00:00Z",
                            end_at="2026-05-01T11:30:00Z", price_cents=1)
    resp = api.perform_procedure(visit["id"], p3["id"], dvm)
    validate_error(resp, ApiErrorId.ERR_CEILING_EXCEEDED, expected_status=409)
    assert get_visit_state(visit["id"])["charges_committed_cents"] == 30000


def test_icu_board_min_one_night_floor(api):
    """PRD §3.7: "The nights are the elapsed time from `admit_at` to `released_at`
    measured in hours, divided by 24 and rounded up to a whole number, but never
    fewer than one night — that is, the number of accrued nights is the larger of
    1 and the ceiling of the hour-span divided by 24."
    PRD §3.7: "an ICU night is 180,000 cents and a general ward night is 60,000
    cents."

    Design: Difficulty/boundary_precision_check/bpc_board_min_one_night_edge
    """
    dvm = make_clinician_dvm_headers()
    _, visit, est, auth, hosp = None, None, None, None, None
    from test_helpers import setup_visit_with_active_hospitalization
    _, visit, est, auth, hosp = setup_visit_with_active_hospitalization(
        triage_level="YELLOW", ward="ICU", cage_number=1,
        admit_at="2026-05-01T08:00:00Z",
        planned_discharge_at="2026-05-02T08:00:00Z",
        approved_ceiling_cents=300000, owner_user_id="owner-11")
    # 1-hour stay -> ceil(1/24)=1 but floored at 1 anyway.
    resp = api.release_hospitalization(visit["id"], hosp["id"],
                                       {"released_at": "2026-05-01T09:00:00Z"}, dvm)
    released = validate_success(resp)
    assert released["nights_accrued"] == 1, f"expected 1 night, got {released['nights_accrued']}"
    assert released["board_cents"] == 180000, f"expected 180000, got {released['board_cents']}"


def test_icu_board_one_hour_charges_full_night(api):
    """PRD §3.7: "the number of accrued nights is the larger of 1 and the ceiling
    of the hour-span divided by 24. The board charge is the accrued nights
    multiplied by the per-diem for the ward"

    Design: Difficulty/boundary_precision_check/bpc_board_min_one_night_edge
    """
    dvm = make_clinician_dvm_headers()
    from test_helpers import setup_visit_with_active_hospitalization
    _, visit, est, auth, hosp = setup_visit_with_active_hospitalization(
        triage_level="YELLOW", ward="ICU", cage_number=1,
        admit_at="2026-05-01T08:00:00Z",
        planned_discharge_at="2026-05-02T08:00:00Z",
        approved_ceiling_cents=300000, owner_user_id="owner-11b")
    resp = api.release_hospitalization(visit["id"], hosp["id"],
                                       {"released_at": "2026-05-01T09:00:00Z"}, dvm)
    released = validate_success(resp)
    assert released["nights_accrued"] == 1
    assert released["board_cents"] == 180000

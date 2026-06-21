"""Election and QDRO state-machine lifecycles: revision/amend cycles, cross-entity
gating, segregation of duties, and spousal/relative-value approval gates.

Translates non_linear_state_machine, cross_entity_state_dependency difficulty
instances (queue A) and the matching state_machine / validation corner instances
(queue B).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_plan_payload,
    create_participant,
    add_standard_comp_330k,
    setup_terminated_vested_participant_330k,
    draft_election,
    create_submitted_single_life_election,
    create_approved_single_life_election,
    create_submitted_js_election,
    create_submitted_lump_sum_election,
    record_spousal_consent,
    draft_qdro,
    create_submitted_percentage_qdro,
    create_qualified_percentage_qdro,
)

SPONSOR = TEST_USERS["plan_sponsor_headers"]
ACTUARY = TEST_USERS["plan_actuary_headers"]
ADMIN = TEST_USERS["benefits_admin_headers"]
ADM_A = TEST_USERS["benefits_admin_a_headers"]
ADM_B = TEST_USERS["benefits_admin_b_headers"]


# ---------------------------------------------------------------------------
# non_linear_state_machine / election_revision_cycle_approved_back_to_draft
# ---------------------------------------------------------------------------
def test_election_reopen_moves_approved_back_to_draft(api):
    """PRD §3.4: "An `APPROVED` election can be re-opened for revision by a
    `BenefitsAdministrator`, moving it from `APPROVED` back to `DRAFT` and clearing the
    computed benefit fields so the election can be revised and resubmitted; re-opening is
    allowed only while no `BenefitPayment` has yet been created for the election."

    Design: Difficulty/non_linear_state_machine/election_revision_cycle_approved_back_to_draft
    """
    plan, participant = setup_terminated_vested_participant_330k(fap_accrual_rate=0.015)
    election = create_approved_single_life_election(participant["id"])
    assert election["status"] == "APPROVED"
    reopened = validate_success(api.reopen_election(election["id"], ADM_B))
    assert reopened["status"] == "DRAFT"


def test_election_resubmit_after_reopen_returns_to_submitted(api):
    """PRD §3.4: "Submitting a `DRAFT` election is a `BenefitsAdministrator` action..."
    PRD §3.4: "When those gates pass, submission moves the election to `SUBMITTED`..."

    Design: Difficulty/non_linear_state_machine/election_revision_cycle_approved_back_to_draft
    """
    plan, participant = setup_terminated_vested_participant_330k(fap_accrual_rate=0.015)
    election = create_approved_single_life_election(participant["id"])
    validate_success(api.reopen_election(election["id"], ADM_B))
    resubmitted = validate_success(api.submit_election(election["id"], ADM_A))
    assert resubmitted["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# non_linear_state_machine / qdro_amend_cycle_rejected_back_to_draft
# ---------------------------------------------------------------------------
def test_qdro_amend_moves_rejected_back_to_draft(api):
    """PRD §3.5: "a `REJECTED` award may be re-opened for amendment, moving it from
    `REJECTED` back to `DRAFT` and clearing `alternate_payee_monthly_cents` so the order
    can be corrected and resubmitted."

    Design: Difficulty/non_linear_state_machine/qdro_amend_cycle_rejected_back_to_draft
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    participant = create_participant(plan["id"])
    qdro = create_submitted_percentage_qdro(participant["id"], 0.40)
    validate_success(api.reject_qdro(qdro["id"], ADMIN))
    amended = validate_success(api.amend_qdro(qdro["id"], ADMIN))
    assert amended["status"] == "DRAFT"


def test_qdro_resubmit_after_amend_returns_to_submitted(api):
    """PRD §3.5: "Submitting a `DRAFT` award for qualification review is a
    `BenefitsAdministrator` action; ... and it moves the award to `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/qdro_amend_cycle_rejected_back_to_draft
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    participant = create_participant(plan["id"])
    qdro = create_submitted_percentage_qdro(participant["id"], 0.40)
    validate_success(api.reject_qdro(qdro["id"], ADMIN))
    validate_success(api.amend_qdro(qdro["id"], ADMIN))
    resubmitted = validate_success(api.submit_qdro(qdro["id"], ADMIN))
    assert resubmitted["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / election_submit_requires_participant_terminated
# ---------------------------------------------------------------------------
def test_submit_active_participant_rejected_not_eligible(api):
    """PRD §3.4: "The participant's `employment_status` must be `TERMINATED`, or the
    submission is rejected with `ERR_PARTICIPANT_NOT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/election_submit_requires_participant_terminated
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    participant = create_participant(plan["id"], date_of_birth="1962-01-01", hire_date="2000-01-01")
    assert participant["employment_status"] == "ACTIVE"
    election = draft_election(participant["id"], "SINGLE_LIFE", "2024-06-01")
    resp = api.submit_election(election["id"], ADM_A)
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_ELIGIBLE.value)


def test_active_participant_stays_active_after_failed_submit(api):
    """PRD §3.2: "A new participant starts with `employment_status` of `ACTIVE`..."
    PRD §3.4: "The participant's `employment_status` must be `TERMINATED`, or the
    submission is rejected with `ERR_PARTICIPANT_NOT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/election_submit_requires_participant_terminated
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    participant = create_participant(plan["id"], date_of_birth="1962-01-01", hire_date="2000-01-01")
    election = draft_election(participant["id"], "SINGLE_LIFE", "2024-06-01")
    api.submit_election(election["id"], ADM_A)
    refetched = validate_success(api.get_participant(participant["id"], ADMIN))
    assert refetched["employment_status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / payment_activate_requires_participant_retired
# ---------------------------------------------------------------------------
def test_payment_activate_with_retired_participant_succeeds(api):
    """PRD §3.8: "Activation requires that the owning election be in `COMMENCED` state
    (otherwise `ERR_INVALID_STATE`) and that the participant's `employment_status` be
    `RETIRED` (otherwise `ERR_PARTICIPANT_NOT_ELIGIBLE`); on success it sets
    `current_monthly_cents` equal to `base_monthly_cents`."

    Design: Difficulty/cross_entity_state_dependency/payment_activate_requires_participant_retired
    """
    plan, participant = setup_terminated_vested_participant_330k(fap_accrual_rate=0.015)
    election = create_approved_single_life_election(participant["id"])
    validate_success(api.commence_election(election["id"], ADM_B))
    refetched = validate_success(api.get_participant(participant["id"], ADMIN))
    assert refetched["employment_status"] == "RETIRED"
    payments = get_success_data(api.list_payments(ADMIN, params={"participant_id": participant["id"]}))
    payment = payments[0]
    activated = validate_success(api.activate_payment(payment["id"], ADMIN))
    assert activated["status"] == "IN_PAY"
    assert activated["current_monthly_cents"] == 330000


def test_payment_current_equals_base_after_activation(api):
    """PRD §3.8: "on success it sets `current_monthly_cents` equal to
    `base_monthly_cents`."

    Design: Difficulty/cross_entity_state_dependency/payment_activate_requires_participant_retired
    """
    plan, participant = setup_terminated_vested_participant_330k(fap_accrual_rate=0.015)
    election = create_approved_single_life_election(participant["id"])
    validate_success(api.commence_election(election["id"], ADM_B))
    payments = get_success_data(api.list_payments(ADMIN, params={"participant_id": participant["id"]}))
    payment = payments[0]
    assert payment["base_monthly_cents"] == 330000
    activated = validate_success(api.activate_payment(payment["id"], ADMIN))
    assert activated["current_monthly_cents"] == activated["base_monthly_cents"]


# ---------------------------------------------------------------------------
# Corner: state_machines / approve_draft_election_invalid_state
# ---------------------------------------------------------------------------
def test_approve_draft_election_invalid_state(api):
    """PRD §2.10: "Only after these structural checks does the system evaluate
    state-machine legality (`ERR_INVALID_STATE`, HTTP 409)..."
    PRD §3.4: "A `SINGLE_LIFE` election is approved directly from `SUBMITTED`..."

    Design: Corner/state_machines/approve_draft_election_invalid_state
    """
    plan, participant = setup_terminated_vested_participant_330k(fap_accrual_rate=0.015)
    election = draft_election(participant["id"], "SINGLE_LIFE", "2024-06-01")
    resp = api.approve_election(election["id"], ADM_B)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / amend_qualified_qdro_invalid_state_terminal
# ---------------------------------------------------------------------------
def test_amend_qualified_qdro_invalid_state(api):
    """PRD §3.5: "on success it moves the award to the terminal `QUALIFIED` state and
    computes its `alternate_payee_monthly_cents`."
    PRD §3.5: "a `REJECTED` award may be re-opened for amendment, moving it from
    `REJECTED` back to `DRAFT`..."

    Design: Corner/state_machines/amend_qualified_qdro_invalid_state_terminal
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    participant = create_participant(plan["id"])
    qdro = create_qualified_percentage_qdro(participant["id"], 0.50)
    assert qdro["status"] == "QUALIFIED"
    resp = api.amend_qdro(qdro["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / election_reject_from_submitted
# ---------------------------------------------------------------------------
def test_election_reject_from_submitted(api):
    """PRD §3.4: "An election may also be rejected by a `BenefitsAdministrator` from
    either `SUBMITTED` or `SPOUSAL_CONSENT_PENDING`, moving it to the terminal
    `REJECTED` state."

    Design: Corner/state_machines/election_reject_from_submitted
    """
    plan, participant = setup_terminated_vested_participant_330k(fap_accrual_rate=0.015)
    election = create_submitted_single_life_election(participant["id"], ADM_A)
    rejected = validate_success(api.reject_election(election["id"], ADM_B))
    assert rejected["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# Corner: validations / segregation_of_duties_same_user_approve
# ---------------------------------------------------------------------------
def test_segregation_of_duties_same_user_approve_rejected(api):
    """PRD §3.4: "this path requires only that the approver's `X-User-ID` differ from the
    recorded `submitted_by_user_id`, or it is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/segregation_of_duties_same_user_approve
    """
    plan, participant = setup_terminated_vested_participant_330k(fap_accrual_rate=0.015)
    election = create_submitted_single_life_election(participant["id"], ADM_A)
    resp = api.approve_election(election["id"], ADM_A)  # same operator as submitter
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ---------------------------------------------------------------------------
# Corner: validations / js_approve_without_spousal_consent_required
# ---------------------------------------------------------------------------
def test_js_approve_without_spousal_consent_rejected(api):
    """PRD §3.4: "there must exist a `SpousalConsent` for the election with `waives_qjsa`
    equal to true, or the approval is rejected with `ERR_SPOUSAL_CONSENT_REQUIRED`."

    Design: Corner/validations/js_approve_without_spousal_consent_required
    """
    plan, participant = setup_terminated_vested_participant_330k(fap_accrual_rate=0.015)
    election = create_submitted_js_election(participant["id"], submitter_headers=ADM_A)
    assert election["status"] == "SPOUSAL_CONSENT_PENDING"
    resp = api.approve_election(election["id"], ADM_B)
    validate_error(resp, ApiErrorId.ERR_SPOUSAL_CONSENT_REQUIRED.value)


# ---------------------------------------------------------------------------
# Corner: validations / lump_sum_relative_value_failed_age_57
# ---------------------------------------------------------------------------
def test_lump_sum_relative_value_failed_age_57(api):
    """PRD §3.4: "then, for a `LUMP_SUM` form, the `relative_value_pct` must be at least
    the relative-value floor of 0.95, or the approval is rejected with
    `ERR_RELATIVE_VALUE_FAILED`."

    Design: Corner/validations/lump_sum_relative_value_failed_age_57
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    participant = create_participant(plan["id"], date_of_birth="1967-01-01", hire_date="2000-01-01")
    add_standard_comp_330k(participant["id"])
    get_success_data(api.terminate_participant(participant["id"], ADMIN, {"termination_date": "2024-01-01"}))
    election = create_submitted_lump_sum_election(participant["id"], submitter_headers=ADM_A)
    assert election["relative_value_pct"] == 0.864
    record_spousal_consent(election["id"], "1968-01-01", "NOTARY-9", waives_qjsa=True)
    resp = api.approve_election(election["id"], ADM_B)
    validate_error(resp, ApiErrorId.ERR_RELATIVE_VALUE_FAILED.value)


# ---------------------------------------------------------------------------
# Corner: validations / qdro_over_allocated_second_award
# ---------------------------------------------------------------------------
def test_qdro_over_allocated_second_award_rejected(api):
    """PRD §3.5: "for a `PERCENTAGE` split, that the cumulative `award_pct` of
    already-`QUALIFIED` percentage awards plus this award's `award_pct` not exceed 1.0
    (otherwise `ERR_QDRO_OVER_ALLOCATED`)."

    Design: Corner/validations/qdro_over_allocated_second_award
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    participant = create_participant(plan["id"])
    create_qualified_percentage_qdro(participant["id"], 0.60, "FORMER_SPOUSE")
    q2 = create_submitted_percentage_qdro(participant["id"], 0.50, "CHILD")
    resp = api.qualify_qdro(q2["id"], ADMIN)  # cumulative 1.10 > 1.0
    validate_error(resp, ApiErrorId.ERR_QDRO_OVER_ALLOCATED.value)


# ---------------------------------------------------------------------------
# Corner: validations / commence_with_pending_qdro_blocked
# ---------------------------------------------------------------------------
def test_commence_with_pending_qdro_blocked(api):
    """PRD §3.4: "Before it may proceed, every `QdroAward` for the participant must be in
    `QUALIFIED` or `REJECTED` state — none may still be `DRAFT` or `SUBMITTED` — or the
    request is rejected with `ERR_QDRO_PENDING`."

    Design: Corner/validations/commence_with_pending_qdro_blocked
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    participant = create_participant(plan["id"], date_of_birth="1962-01-01", hire_date="2000-01-01")
    get_success_data(api.create_compensation(
        {"participant_id": participant["id"], "plan_year": 2023, "gross_comp_cents": 12_000_000}, ADMIN))
    get_success_data(api.terminate_participant(participant["id"], ADMIN, {"termination_date": "2024-01-01"}))
    # A separate SUBMITTED QDRO still pending.
    create_submitted_percentage_qdro(participant["id"], 0.30)
    election = create_approved_single_life_election(participant["id"])
    resp = api.commence_election(election["id"], ADM_B)
    validate_error(resp, ApiErrorId.ERR_QDRO_PENDING.value)


# ---------------------------------------------------------------------------
# Corner: validations / qualify_qdro_after_commenced_too_late
# ---------------------------------------------------------------------------
def test_qualify_qdro_after_commenced_too_late(api):
    """PRD §3.5: "it requires that no `COMMENCED` election yet exist for the participant
    (otherwise `ERR_QDRO_TOO_LATE`)..."

    Design: Corner/validations/qualify_qdro_after_commenced_too_late
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    participant = create_participant(plan["id"], date_of_birth="1962-01-01", hire_date="2000-01-01")
    get_success_data(api.create_compensation(
        {"participant_id": participant["id"], "plan_year": 2023, "gross_comp_cents": 12_000_000}, ADMIN))
    get_success_data(api.terminate_participant(participant["id"], ADMIN, {"termination_date": "2024-01-01"}))
    election = create_approved_single_life_election(participant["id"])
    validate_success(api.commence_election(election["id"], ADM_B))
    qdro = create_submitted_percentage_qdro(participant["id"], 0.30)
    resp = api.qualify_qdro(qdro["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_QDRO_TOO_LATE.value)


# ---------------------------------------------------------------------------
# Corner: validations / js_election_create_missing_survivor_pct_invalid_request
# ---------------------------------------------------------------------------
def test_js_election_missing_survivor_pct_invalid_request(api):
    """PRD §3.4: "For a joint-and-survivor form the payload additionally requires
    `js_survivor_pct` — the survivor continuation fraction, which must be 0.50, 0.75, or
    1.00 — and `spouse_date_of_birth`, the contingent annuitant's date of birth; both are
    ignored for the other forms."

    Design: Corner/validations/js_election_create_missing_survivor_pct_invalid_request
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    participant = create_participant(plan["id"])
    resp = api.create_election(
        {"participant_id": participant["id"], "payment_form": "JOINT_AND_SURVIVOR",
         "annuity_start_date": "2024-06-01"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Corner: validations / percentage_qdro_submit_missing_award_pct_invalid_request
# ---------------------------------------------------------------------------
def test_percentage_qdro_submit_missing_award_pct_invalid_request(api):
    """PRD §3.5: "it requires that a `PERCENTAGE` award carry an `award_pct` in the
    interval greater than 0 and at most 1, and that a `SHARED_INTEREST` award carry an
    `award_fixed_monthly_cents` greater than 0 — a violation of either yields
    `ERR_INVALID_REQUEST` — and it moves the award to `SUBMITTED`."

    Design: Corner/validations/percentage_qdro_submit_missing_award_pct_invalid_request
    """
    plan = get_success_data(api.create_plan(create_plan_payload(fap_accrual_rate=0.015), SPONSOR))
    participant = create_participant(plan["id"])
    qdro = draft_qdro(participant["id"], "CHILD", "PERCENTAGE")  # no award_pct
    resp = api.submit_qdro(qdro["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

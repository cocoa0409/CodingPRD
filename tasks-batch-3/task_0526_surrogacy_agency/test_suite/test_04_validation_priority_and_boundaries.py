"""Validation-priority conflicts (state beats fiscal; state beats referential)
and numeric boundary-precision checks (budget cap at exact; carrier
prior_deliveries boundary at 1).

Covers difficulty queue rules priority_pair_validation_conflict and
boundary_precision_check.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    TEST_USERS,
    ApiErrorId,
    make_intended_parent_actor_headers,
    create_active_journey,
    create_funded_journey,
    create_approved_disbursement,
    add_comp_schedule_line,
    add_and_achieve_milestone,
)
from test_helpers import factories as f

CM = TEST_USERS["case_manager_headers"]
FO = TEST_USERS["finance_officer_headers"]


# ==========================================================================
# Priority-pair conflicts — state (priority 4) wins
# ==========================================================================
def test_approve_already_approved_disbursement_state_beats_fiscal(api):
    """PRD §3.8: "Approval requires the disbursement to be `REQUESTED`". PRD
    §3.10: "State validity is then checked: a resource not in a valid state for
    the requested transition fails with `ERR_INVALID_STATE`. After these come the
    business rules — ... escrow sufficiency (`ERR_INSUFFICIENT_ESCROW`)."

    Design: Difficulty/priority_pair_validation_conflict/milestone_gate_beats_insufficient_escrow_safety_vs_fiscal
    """
    # Deposit exactly the schedule amount so, after approval reserves it,
    # available is 0 — a re-approve would breach fiscal if state didn't win first.
    ctx = create_approved_disbursement(deposit_cents=1_000_000, schedule_amount_cents=1_000_000,
                                       approver_user_id="cm-state-fiscal")
    jr_id = ctx["journey"]["id"]
    resp = api.approve_disbursement(jr_id, ctx["disbursement"]["id"],
                                    TEST_USERS["case_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_file_parentage_twice_state_beats_referential(api):
    """PRD §3.6: "A `CaseManager` files the pre-birth order, moving it from
    `NOT_FILED` to `FILED`." PRD §3.10: "State validity is then checked: a
    resource not in a valid state for the requested transition fails with
    `ERR_INVALID_STATE`. After these come the business rules — ... parentage
    jurisdiction (`ERR_PARENTAGE_JURISDICTION_BLOCKED`)".

    Design: Difficulty/priority_pair_validation_conflict/parentage_jurisdiction_beats_missing_state_referential_vs_state
    """
    ctx = create_active_journey(ip_state_code="CA")
    jr_id = ctx["journey"]["id"]
    validate_success(api.file_parentage(jr_id, CM))  # NOT_FILED -> FILED
    resp = api.file_parentage(jr_id, CM)  # already FILED
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ==========================================================================
# Boundary precision — budget cap
# ==========================================================================
def test_escrow_deposit_at_budget_cap_exact_passes(api):
    """PRD §3.5: "the account's `deposited_cents` plus the new `amount_cents`
    must not exceed the linked intended parent's `budget_cents`. A deposit that
    would push cumulative `deposited_cents` above `budget_cents` is rejected with
    `ERR_BUDGET_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/escrow_deposit_at_budget_cap_exact_passes
    """
    ctx = create_active_journey()  # IP budget defaults to 6_000_000
    escrow = ctx["escrow"]
    ip_headers = make_intended_parent_actor_headers(ctx["ip"]["id"])
    data = validate_success(api.deposit_escrow(
        escrow["id"], f.deposit_payload(6_000_000, escrow["version"]), ip_headers))
    assert data["deposited_cents"] == 6_000_000
    assert data["available_cents"] == 6_000_000


def test_escrow_deposit_one_cent_over_budget_cap_rejected(api):
    """PRD §3.5: "A deposit that would push cumulative `deposited_cents` above
    `budget_cents` is rejected with `ERR_BUDGET_EXCEEDED`."

    Design: Corner/validations/deposit_over_budget_cap_exceeded
    """
    ctx = create_active_journey()
    escrow = ctx["escrow"]
    ip_headers = make_intended_parent_actor_headers(ctx["ip"]["id"])
    resp = api.deposit_escrow(escrow["id"], f.deposit_payload(6_000_001, escrow["version"]), ip_headers)
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED.value)
    refreshed = validate_success(api.get_escrow_account(escrow["id"], FO))
    assert refreshed["deposited_cents"] == 0


# ==========================================================================
# Boundary precision — carrier prior_deliveries
# ==========================================================================
def test_carrier_submit_prior_deliveries_exactly_one_passes(api):
    """PRD §3.1: "Submitting a carrier advances `DRAFT` to `SUBMITTED`, but only
    if `prior_deliveries` is at least 1 ...; a carrier whose `prior_deliveries`
    is below 1 is rejected with `ERR_CARRIER_INELIGIBLE`, and a count of exactly
    1 passes."

    Design: Difficulty/boundary_precision_check/carrier_prior_deliveries_exactly_one_passes_zero_fails
    """
    car = get_success_data(api.create_carrier(f.create_carrier_payload(prior_deliveries=1), CM))
    data = validate_success(api.submit_carrier(car["id"], CM))
    assert data["intake_status"] == "SUBMITTED"


def test_carrier_submit_prior_deliveries_zero_rejected(api):
    """PRD §3.1: "a carrier whose `prior_deliveries` is below 1 is rejected with
    `ERR_CARRIER_INELIGIBLE`, and a count of exactly 1 passes."

    Design: Difficulty/boundary_precision_check/carrier_prior_deliveries_exactly_one_passes_zero_fails
    """
    car = get_success_data(api.create_carrier(f.create_carrier_payload(prior_deliveries=0), CM))
    resp = api.submit_carrier(car["id"], CM)
    validate_error(resp, ApiErrorId.ERR_CARRIER_INELIGIBLE.value)
    refreshed = validate_success(api.get_carrier(car["id"], CM))
    assert refreshed["intake_status"] == "DRAFT"

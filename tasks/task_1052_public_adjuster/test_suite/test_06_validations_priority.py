"""Validation ordering, cross-entity state dependencies, and supplement flows."""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    create_supplement_payload, create_claim_payload, create_payment_payload,
    make_public_adjuster_headers,
)
from test_helpers.fixtures import (
    setup_active_contract, setup_filed_claim, setup_settled_claim_with_draft_supplement,
    new_adjuster, new_license, new_client, new_policy, new_contract,
    new_draft_claim, sign_contract, claim_version, set_clock,
)

FIRM = TEST_USERS["firm_principal_headers"]
CARRIER = TEST_USERS["carrier_headers"]


# ---------------- priority pair: state beats fiscal on supplement create (difficulty)
def test_supplement_create_on_unsettled_claim_state_beats_over_limit(api):
    """PRD §2.10: "(4) the target resource being in a state from which the requested
    transition is legal, which includes the requirement that a claim be settled before a
    supplement may be created against it (`ERR_INVALID_STATE`)".
    PRD §3.6: "The target claim must already be `SETTLED` or `PAID`; a create against a claim
    that has not settled is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/supplement_create_claim_not_settled_state_beats_over_limit_fiscal
    """
    ctx = setup_filed_claim(api)  # claim is FILED, not settled
    ver = claim_version(api, ctx["clm"])
    resp = api.create_supplement(
        create_supplement_payload(ctx["clm"], ver, amount_cents=200_000_000, reason="HIDDEN_DAMAGE"),
        make_public_adjuster_headers(ctx["adj"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_supplement_create_on_unsettled_claim_within_limit_still_invalid_state(api):
    """PRD §3.6: "The target claim must already be `SETTLED` or `PAID`; a create against a
    claim that has not settled is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/supplement_create_claim_not_settled_state_beats_over_limit_fiscal
    """
    ctx = setup_filed_claim(api)
    ver = claim_version(api, ctx["clm"])
    resp = api.create_supplement(
        create_supplement_payload(ctx["clm"], ver, amount_cents=1_000_000, reason="HIDDEN_DAMAGE"),
        make_public_adjuster_headers(ctx["adj"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# ---------- priority pair: license compliance beats loss-period on file (difficulty)
def test_claim_file_license_compliance_beats_loss_outside_policy(api):
    """PRD §3.3: "the retained adjuster must hold a currently-valid license in the claim's
    `loss_state_code` at the current clock instant (else `ERR_LICENSE_NOT_VALID`); and the
    `date_of_loss` must fall on or after the policy's `effective_date` and on or before its
    `expiry_date` (else `ERR_LOSS_OUTSIDE_POLICY_PERIOD`)."

    Design: Difficulty/priority_pair_validation_conflict/claim_file_license_compliance_beats_loss_outside_policy_temporal
    """
    ctx = setup_active_contract(api)  # TX license, contract loss_state TX (activation ok)
    clm = new_draft_claim(api, ctx["pol"], ctx["con"], ctx["adj"],
                          loss_state_code="CA", date_of_loss="2025-06-15T00:00:00Z")
    resp = api.file_claim(clm, make_public_adjuster_headers(ctx["adj"]))
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_VALID.value, expected_status=409)


def test_claim_file_missing_license_in_loss_state_rejected(api):
    """PRD §3.3: "the retained adjuster must hold a currently-valid license in the claim's
    `loss_state_code` at the current clock instant (else `ERR_LICENSE_NOT_VALID`)".

    Design: Difficulty/priority_pair_validation_conflict/claim_file_license_compliance_beats_loss_outside_policy_temporal
    """
    ctx = setup_active_contract(api)  # only a TX license exists
    clm = new_draft_claim(api, ctx["pol"], ctx["con"], ctx["adj"],
                          loss_state_code="CA", date_of_loss="2026-06-15T00:00:00Z")
    resp = api.file_claim(clm, make_public_adjuster_headers(ctx["adj"]))
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_VALID.value, expected_status=409)


# ----------------- cross-entity: claim file blocked by non-active policy (difficulty)
def test_claim_file_blocked_when_policy_lapsed(api):
    """PRD §3.3: "the referenced policy must be `ACTIVE` (else `ERR_POLICY_NOT_ACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/claim_file_blocked_when_policy_lapsed
    """
    ctx = setup_active_contract(api)
    clm = new_draft_claim(api, ctx["pol"], ctx["con"], ctx["adj"])
    validate_success(api.lapse_policy(ctx["pol"], FIRM))
    resp = api.file_claim(clm, make_public_adjuster_headers(ctx["adj"]))
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE.value, expected_status=409)


def test_claim_file_blocked_when_policy_cancelled(api):
    """PRD §3.3: "the referenced policy must be `ACTIVE` (else `ERR_POLICY_NOT_ACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/claim_file_blocked_when_policy_lapsed
    """
    ctx = setup_active_contract(api)
    clm = new_draft_claim(api, ctx["pol"], ctx["con"], ctx["adj"])
    validate_success(api.cancel_policy(ctx["pol"], FIRM))
    resp = api.file_claim(clm, make_public_adjuster_headers(ctx["adj"]))
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE.value, expected_status=409)


# --------------------------- supplement submit window boundary (difficulty)
def test_supplement_submit_exactly_at_window_boundary_accepted(api):
    """PRD §3.6: "the number of days between the claim's settlement instant and the current
    clock instant must be at most `SUPPLEMENT_WINDOW_DAYS`, which equals 365 days, otherwise
    the submission is rejected with `ERR_SUPPLEMENT_WINDOW_CLOSED`."

    Design: Difficulty/boundary_precision_check/supplement_submit_exactly_at_window_boundary_accepted
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    ctx = setup_settled_claim_with_draft_supplement(api, offer_cents=8_000_000, amount_cents=1_000_000)
    set_clock(api, "2027-07-01T00:00:00Z")  # exactly 365 days after settlement
    data = validate_success(api.submit_supplement(ctx["sup"], make_public_adjuster_headers(ctx["adj"])))
    assert data["status"] == "SUBMITTED"


def test_supplement_submit_within_window_accepted(api):
    """PRD §3.6: "Submitting a supplement to the carrier moves it from `DRAFT` to
    `SUBMITTED` and stamps `submitted_at` with the current clock instant, but only within the
    supplement window".

    Design: Difficulty/boundary_precision_check/supplement_submit_exactly_at_window_boundary_accepted
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    ctx = setup_settled_claim_with_draft_supplement(api, offer_cents=8_000_000, amount_cents=1_000_000)
    set_clock(api, "2026-08-01T00:00:00Z")  # 31 days after settlement, well within window
    data = validate_success(api.submit_supplement(ctx["sup"], make_public_adjuster_headers(ctx["adj"])))
    assert data["status"] == "SUBMITTED"


def test_supplement_submit_past_window_rejected(api):
    """PRD §3.6: "the number of days between the claim's settlement instant and the current
    clock instant must be at most `SUPPLEMENT_WINDOW_DAYS`, which equals 365 days, otherwise
    the submission is rejected with `ERR_SUPPLEMENT_WINDOW_CLOSED`."

    Design: Corner/validations/supplement_submit_past_window_rejected
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    ctx = setup_settled_claim_with_draft_supplement(api, offer_cents=8_000_000, amount_cents=1_000_000)
    set_clock(api, "2027-07-02T00:00:00Z")  # 366 days after settlement
    resp = api.submit_supplement(ctx["sup"], make_public_adjuster_headers(ctx["adj"]))
    validate_error(resp, ApiErrorId.ERR_SUPPLEMENT_WINDOW_CLOSED.value)


# ------------------------------------------ isolated file-time validations (corner)
def test_claim_file_from_settled_is_invalid_transition(api):
    """PRD §2.10: "(4) the target resource being in a state from which the requested
    transition is legal, which includes the requirement that a claim be settled before a
    supplement may be created against it (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/claim_file_from_settled_is_invalid_transition
    """
    from test_helpers.fixtures import setup_settled_claim
    ctx = setup_settled_claim(api, offer_cents=8_000_000)
    resp = api.file_claim(ctx["clm"], make_public_adjuster_headers(ctx["adj"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_claim_file_loss_outside_policy_period_rejected(api):
    """PRD §3.3: "and the `date_of_loss` must fall on or after the policy's `effective_date`
    and on or before its `expiry_date` (else `ERR_LOSS_OUTSIDE_POLICY_PERIOD`)."

    Design: Corner/validations/claim_file_loss_outside_policy_period_rejected
    """
    ctx = setup_active_contract(api)
    clm = new_draft_claim(api, ctx["pol"], ctx["con"], ctx["adj"],
                          loss_state_code="TX", date_of_loss="2025-06-15T00:00:00Z")
    resp = api.file_claim(clm, make_public_adjuster_headers(ctx["adj"]))
    validate_error(resp, ApiErrorId.ERR_LOSS_OUTSIDE_POLICY_PERIOD.value)


def test_claim_file_contract_not_active_rejected(api):
    """PRD §3.3: "the referenced contract must be `ACTIVE` (else `ERR_CONTRACT_NOT_ACTIVE`)".

    Design: Corner/validations/claim_file_contract_not_active_rejected
    """
    adj = new_adjuster(api)
    new_license(api, adj)
    cli = new_client(api)
    pol = new_policy(api, cli)
    con = new_contract(api, cli, adj)
    sign_contract(api, con, cli)  # SIGNED but never activated
    clm = new_draft_claim(api, pol, con, adj)
    resp = api.file_claim(clm, make_public_adjuster_headers(adj))
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)


def test_payment_clear_on_unsettled_claim_rejected(api):
    """PRD §3.7: "Clearing a payment, performed by the carrier, requires that the claim be
    `SETTLED` or `PAID`; a clear against any other claim state is rejected with
    `ERR_CLAIM_NOT_SETTLED`."

    Design: Corner/state_machines/payment_clear_on_unsettled_claim_rejected
    """
    ctx = setup_filed_claim(api)  # FILED, not settled
    pay = get_success_data(api.create_payment(create_payment_payload(ctx["clm"], 8_000_000), CARRIER))["id"]
    resp = api.clear_payment(pay, CARRIER)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_SETTLED.value)


# ------------------------------------------------ supplement decide (corner)
def test_supplement_decide_over_limit_rejected(api):
    """PRD §3.6: "On an approve decision, the additional amount must fit within the policy's
    current headroom: if `amount_cents` exceeds the policy's `remaining_limit_cents`, the
    decision is rejected with `ERR_POLICY_LIMIT_EXCEEDED`".

    Design: Corner/validations/supplement_decide_over_limit_rejected
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    ctx = setup_settled_claim_with_draft_supplement(api, offer_cents=8_000_000, amount_cents=100_000_000)
    validate_success(api.submit_supplement(ctx["sup"], make_public_adjuster_headers(ctx["adj"])))
    resp = api.decide_supplement(ctx["sup"], {"decision": "APPROVE"}, FIRM)
    validate_error(resp, ApiErrorId.ERR_POLICY_LIMIT_EXCEEDED.value)


def test_supplement_decide_approve_commits_limit(api):
    """PRD §3.6: "otherwise the supplement moves to the terminal `APPROVED`, the policy's
    `committed_cents` increases by `amount_cents` with `remaining_limit_cents` recomputed,
    and the claim's `settlement_amount_cents` increases by the same amount."

    Design: Corner/validations/supplement_decide_approve_commits_limit
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    ctx = setup_settled_claim_with_draft_supplement(api, offer_cents=8_000_000, amount_cents=1_000_000)
    validate_success(api.submit_supplement(ctx["sup"], make_public_adjuster_headers(ctx["adj"])))
    data = validate_success(api.decide_supplement(ctx["sup"], {"decision": "APPROVE"}, FIRM))
    assert data["status"] == "APPROVED"
    pol = get_success_data(api.get_policy(ctx["pol"], FIRM))
    assert pol["committed_cents"] == 9_000_000
    assert pol["remaining_limit_cents"] == 91_000_000

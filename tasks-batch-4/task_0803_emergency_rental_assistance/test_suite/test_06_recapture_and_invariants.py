"""Recapture cascade and conserved-quantity invariants.

Translates queue-A transitive_cascade (recapture depth-3) and compensating_invariant
instances, plus the queue-B recover-precondition corner instance.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_caseworker_headers,
    build_approved_application, create_cleared_disbursement, create_disbursement,
    open_substantiated_recapture, recapture_case_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
CW = TEST_USERS["caseworker_headers"]
FRAUD = TEST_USERS["fraud_headers"]


def _disbursed_and_substantiated(api, *, reason, approver, issuer, ref):
    """Approved app -> cleared disbursement (1000000/5mo) -> substantiated recapture case."""
    ctx = build_approved_application(api, approver_id=approver)
    aid, av = ctx["aid"], ctx["version"]
    did = create_cleared_disbursement(api, aid, amount_cents=1000000, months_covered=5,
                                      coverage_kind="COMBINED", version=av,
                                      issuer_id=issuer, payment_reference=ref)
    rcid = open_substantiated_recapture(api, aid, did, reason=reason)
    ctx["did"], ctx["rcid"] = did, rcid
    return ctx


# =====================================================================
# Rule 4 — transitive_cascade (recapture depth-3 reversal)
# =====================================================================

def test_recover_recaptures_disbursement_and_closes_application(api):
    """PRD §3.9: "As its cascade, the targeted disbursement moves from `CLEARED` to
    `RECAPTURED`, which in turn releases its reservation (the program's
    `funding_pool_remaining_cents` is increased by `amount_cents`, returning the program
    to `OPEN` if it was `EXHAUSTED`), releases its months (the tenant's `months_used` is
    decreased by `months_covered`), reverses the application's ledger (the application's
    `total_disbursed_cents` is decreased by `amount_cents`), and moves the application's
    `status` to `CLOSED`."

    Design: Difficulty/transitive_cascade/recapture_recover_depth3_reversal
    """
    ctx = _disbursed_and_substantiated(api, reason="INCOME_MISREPRESENTATION",
                                       approver="cw-approver-7", issuer="cw-issuer-7", ref="ACH-7")
    get_success_data(api.recover_recapture(ctx["rcid"], FRAUD))
    disb = get_success_data(api.get_disbursement(ctx["did"], ADMIN))
    app = get_success_data(api.get_application(ctx["aid"], CW))
    assert disb["status"] == "RECAPTURED"
    assert app["status"] == "CLOSED"


def test_recover_reverses_application_disbursed_total(api):
    """PRD §3.9: "reverses the application's ledger (the application's
    `total_disbursed_cents` is decreased by `amount_cents`), and moves the application's
    `status` to `CLOSED`."

    Design: Difficulty/transitive_cascade/recapture_recover_depth3_reversal
    """
    ctx = _disbursed_and_substantiated(api, reason="INCOME_MISREPRESENTATION",
                                       approver="cw-approver-7b", issuer="cw-issuer-7b", ref="ACH-7b")
    get_success_data(api.recover_recapture(ctx["rcid"], FRAUD))
    app = get_success_data(api.get_application(ctx["aid"], CW))
    assert app["total_disbursed_cents"] == 0


# =====================================================================
# Rule 9 — compensating_invariant (funding dollars conserved)
# =====================================================================

def test_funding_pool_restored_to_total_after_recapture(api):
    """PRD §2.7: "`funding_pool_remaining_cents` is the total minus the sum of
    `amount_cents` across every disbursement of that program currently in a reserving
    state — that is, in `PENDING`, `SENT`, or `CLEARED` status."

    Design: Difficulty/compensating_invariant/funding_pool_conserved_across_disburse_and_recapture
    """
    ctx = _disbursed_and_substantiated(api, reason="VACATED_UNIT",
                                       approver="cw-approver-17", issuer="cw-issuer-17", ref="ACH-17")
    get_success_data(api.recover_recapture(ctx["rcid"], FRAUD))
    program = get_success_data(api.get_program(ctx["pid"], ADMIN))
    assert program["funding_pool_remaining_cents"] == 100000000


def test_funding_pool_total_unchanged_by_recapture(api):
    """PRD §2.7: "Its `funding_pool_total_cents` is the total allocation, and
    `funding_pool_remaining_cents` is the total minus the sum of `amount_cents` across
    every disbursement of that program currently in a reserving state — that is, in
    `PENDING`, `SENT`, or `CLEARED` status."

    Design: Difficulty/compensating_invariant/funding_pool_conserved_across_disburse_and_recapture
    """
    ctx = _disbursed_and_substantiated(api, reason="VACATED_UNIT",
                                       approver="cw-approver-17b", issuer="cw-issuer-17b", ref="ACH-17b")
    get_success_data(api.recover_recapture(ctx["rcid"], FRAUD))
    program = get_success_data(api.get_program(ctx["pid"], ADMIN))
    assert program["funding_pool_total_cents"] == 100000000


# =====================================================================
# Rule 9 — compensating_invariant (months conserved)
# =====================================================================

def test_tenant_months_used_restored_to_zero_after_recapture(api):
    """PRD §2.8: "Each tenant carries `months_used`, a conserved counter equal to the sum
    of `months_covered` across every disbursement whose application belongs to that
    tenant and whose status is `PENDING`, `SENT`, or `CLEARED`. Like funds, months are
    reserved when a disbursement is created and released when it moves to `FAILED` or
    `RECAPTURED`."

    Design: Difficulty/compensating_invariant/months_cap_conserved_across_disburse_and_recapture
    """
    ctx = _disbursed_and_substantiated(api, reason="DUPLICATE_BENEFIT",
                                       approver="cw-approver-18", issuer="cw-issuer-18", ref="ACH-18")
    get_success_data(api.recover_recapture(ctx["rcid"], FRAUD))
    tenant = get_success_data(api.get_tenant(ctx["tid"], ADMIN))
    assert tenant["months_used"] == 0


def test_recaptured_disbursement_retains_its_months_covered_field(api):
    """PRD §2.8: "Each tenant carries `months_used`, a conserved counter equal to the sum
    of `months_covered` across every disbursement whose application belongs to that
    tenant and whose status is `PENDING`, `SENT`, or `CLEARED`."

    Design: Difficulty/compensating_invariant/months_cap_conserved_across_disburse_and_recapture
    """
    ctx = _disbursed_and_substantiated(api, reason="DUPLICATE_BENEFIT",
                                       approver="cw-approver-18b", issuer="cw-issuer-18b", ref="ACH-18b")
    get_success_data(api.recover_recapture(ctx["rcid"], FRAUD))
    disb = get_success_data(api.get_disbursement(ctx["did"], ADMIN))
    assert disb["months_covered"] == 5


# =====================================================================
# Queue B — recover precondition (targeted disbursement must still be CLEARED)
# =====================================================================

def test_recover_before_disbursement_cleared_rejected(api):
    """PRD §3.9: "From `SUBSTANTIATED`, the investigator recovers funds, which requires
    the targeted disbursement to still be `CLEARED` and triggers a depth-three cascade."
    PRD §2.6: "then whether the target is in a state from which the requested transition
    is defined (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/state_machines/recover_before_disbursement_cleared_returns_invalid_state
    """
    ctx = build_approved_application(api, approver_id="cw-approver-rb")
    aid, av = ctx["aid"], ctx["version"]
    did = create_disbursement(api, aid, amount_cents=1000000, months_covered=5,
                              coverage_kind="COMBINED", version=av, issuer_id="cw-issuer-rb")["id"]
    # Send but do NOT clear — disbursement stays SENT.
    get_success_data(api.send_disbursement(did, {"payment_reference": "ACH-RB"},
                                           make_caseworker_headers("cw-issuer-rb")))
    rcid = open_substantiated_recapture(api, aid, did, reason="OTHER")

    resp = api.recover_recapture(rcid, FRAUD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

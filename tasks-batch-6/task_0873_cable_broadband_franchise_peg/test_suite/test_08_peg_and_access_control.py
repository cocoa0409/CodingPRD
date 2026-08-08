"""PEG credit conservation, a payment precedence conflict, and access control."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_peg_contribution,
    TEST_USERS, make_operator_headers, anonymous_headers,
    create_franchise_payload,
)
from test_helpers import (
    create_active_franchise, create_accepted_report, create_paid_report,
    record_peg, get_franchise, make_authority_headers,
)

AUTHORITY = TEST_USERS["authority_headers"]


# ---- Difficulty: peg_record_then_void_conserves_peg_credit ----
def test_record_then_void_conserves_peg_credit(api):
    """PRD 3.1: "Recording a contribution and then voiding it leaves
    `peg_credit_cents` unchanged from its pre-record value."
    PRD 3.7: "voiding is defined only from `RECORDED`, moves the contribution to
    `VOIDED` (terminal), records the reason, and recomputes `peg_credit_cents` so
    the voided contribution leaves the credited set."

    Design: Difficulty/compensating_invariant/peg_record_then_void_conserves_peg_credit
    """
    fr = create_active_franchise(api)
    peg = record_peg(api, fr["id"], amount_cents=250000, contribution_type="CAPITAL_GRANT")
    assert get_franchise(api, fr["id"])["peg_credit_cents"] == 250000

    validate_success(api.void_peg_contribution(peg["id"], {"voided_reason": "duplicate deposit"}, AUTHORITY), 200)
    assert get_franchise(api, fr["id"])["peg_credit_cents"] == 0


def test_void_sets_contribution_voided(api):
    """PRD 3.7: "An authority may void a recorded contribution by supplying a
    `voided_reason`; voiding is defined only from `RECORDED`, moves the
    contribution to `VOIDED` (terminal), records the reason".

    Design: Difficulty/compensating_invariant/peg_record_then_void_conserves_peg_credit
    """
    fr = create_active_franchise(api)
    peg = record_peg(api, fr["id"], amount_cents=250000, contribution_type="CAPITAL_GRANT")
    data = validate_success(api.void_peg_contribution(peg["id"], {"voided_reason": "duplicate deposit"}, AUTHORITY), 200)
    assert data["status"] == "VOIDED"


# ---- Difficulty: pay_paid_report_state_beats_fiscal ----
def test_pay_paid_report_wrong_amount_state_wins(api):
    """PRD 2.8: "State — the target is in a state from which the requested
    transition is defined, else `ERR_INVALID_STATE` (409)." (State priority
    precedes the payment-amount check.)
    PRD 3.4: "payment is defined only from `ACCEPTED`."

    Design: Difficulty/priority_pair_validation_conflict/pay_paid_report_state_beats_fiscal
    """
    fr = create_active_franchise(api)
    rr = create_paid_report(api, fr["id"])  # now PAID
    op = make_operator_headers(fr["id"])
    # Re-pay a PAID report with a wrong amount: both state (PAID) and fiscal
    # (outstanding is 0) fail; state wins.
    resp = api.pay_revenue_report(rr["id"], {"amount_cents": 1}, op)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_pay_paid_report_leaves_report_paid(api):
    """PRD 3.4: "A successful payment adds `amount_cents` to `amount_paid_cents`
    and advances the report to `PAID`; payment is defined only from `ACCEPTED`."

    Design: Difficulty/priority_pair_validation_conflict/pay_paid_report_state_beats_fiscal
    """
    fr = create_active_franchise(api)
    rr = create_paid_report(api, fr["id"])
    op = make_operator_headers(fr["id"])
    api.pay_revenue_report(rr["id"], {"amount_cents": 1}, op)
    after = validate_success(api.get_revenue_report(rr["id"], AUTHORITY), 200)
    assert after["status"] == "PAID"
    assert after["amount_paid_cents"] == 9169


# ---- Corner: peg_contribution_default_type_applied ----
def test_peg_default_type_capital_grant(api):
    """PRD 3.7: "optionally a `contribution_type` of `CAPITAL_GRANT` (the
    default) or `INET`. The contribution is created at `status` `RECORDED`".

    Design: Corner/entities/peg_contribution_default_type_applied
    """
    fr = create_active_franchise(api)
    op = make_operator_headers(fr["id"])
    data = validate_success(api.create_peg_contribution({"franchise_id": fr["id"], "amount_cents": 100000}, op), 201)
    assert_peg_contribution(data)
    assert data["contribution_type"] == "CAPITAL_GRANT"
    assert data["status"] == "RECORDED"


# ---- Corner (rbac): operator_cannot_create_franchise_unauthorized ----
def test_operator_cannot_create_franchise_unauthorized(api):
    """PRD 2.1: "If the header is present and valid but the role is not permitted
    to invoke the requested operation (per the authorization matrix in Section
    4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/operator_cannot_create_franchise_unauthorized
    """
    resp = api.create_franchise(create_franchise_payload(), make_operator_headers("someone"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


# ---- Corner (rbac): unauthenticated_request_missing_role_header ----
def test_unauthenticated_missing_role_header(api):
    """PRD 2.1: "If `X-User-Role` is missing or is not one of the three known
    roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unauthenticated_request_missing_role_header
    """
    fr = create_active_franchise(api)
    resp = api.get_franchise(fr["id"], anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


# ---- Corner (rbac): operator_cannot_pay_other_franchises_report_not_owner ----
def test_operator_cannot_pay_other_franchise_report_not_owner(api):
    """PRD 2.1: "An Operator write against a resource whose `franchise_id` does
    not equal the caller's `X-User-ID` is rejected with `ERR_NOT_FRANCHISE_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/operator_cannot_pay_other_franchises_report_not_owner
    """
    fr_a = create_active_franchise(api, operator_name="CableCo A", territory_name="Ward A")
    fr_b = create_active_franchise(api, operator_name="CableCo B", territory_name="Ward B",
                                   homes_in_territory=8000, road_miles=40)
    rr = create_accepted_report(api, fr_a["id"])
    # Operator B (X-User-ID = fr_b) pays a report owned by franchise A.
    resp = api.pay_revenue_report(rr["id"], {"amount_cents": 9169}, make_operator_headers(fr_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FRANCHISE_OWNER.value, 403)

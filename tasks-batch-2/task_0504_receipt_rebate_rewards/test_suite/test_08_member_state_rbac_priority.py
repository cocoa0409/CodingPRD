"""Member parallel state dimensions, RBAC enforcement, and validation-priority
ordering pairs.

Translates difficulty `non_linear_state_machine` (member parallel dimensions) and
`priority_pair_validation_conflict`, plus corner `rbac` instances.
"""
from test_helpers import (
    validate_success, validate_error, api_client, TEST_USERS, make_member_headers,
    build_user_headers, ApiErrorId,
    create_merchant, create_offer, create_member, create_verified_member,
    member_version,
)

_PA = TEST_USERS["platform_admin_headers"]
_RA = TEST_USERS["review_agent_headers"]
_FA = TEST_USERS["finance_admin_headers"]


def test_member_parallel_account_and_verification_dimensions(api):
    """PRD §3.2: "A member carries two **independent** status dimensions that evolve
    on the same record. The verification dimension moves `UNVERIFIED` to `VERIFIED`
    when a `FinanceAdmin` verifies the member. The account dimension moves `ACTIVE`
    to `SUSPENDED` when a `FinanceAdmin` suspends the member".

    Design: Difficulty/non_linear_state_machine/member_parallel_account_and_verification_dimensions
    """
    member = create_member("mf@x.com")
    validate_success(api.verify_member(member["id"], _FA))
    suspended = validate_success(api.suspend_member(member["id"], _FA))
    assert suspended["account_status"] == "SUSPENDED"
    assert suspended["verification_status"] == "VERIFIED", \
        "verification dimension must persist independently of the account dimension"


def test_member_reinstate_restores_account_dimension_only(api):
    """PRD §3.2: "The account dimension moves `ACTIVE` to `SUSPENDED` when a
    `FinanceAdmin` suspends the member, and back from `SUSPENDED` to `ACTIVE` when a
    `FinanceAdmin` reinstates them."

    The two dimensions remain independent across a third transition: reinstating a
    verified-then-suspended member restores account_status to ACTIVE while
    verification_status stays VERIFIED.

    Design: Difficulty/non_linear_state_machine/member_parallel_account_and_verification_dimensions
    """
    member = create_member("mfreinst@x.com")
    validate_success(api.verify_member(member["id"], _FA))
    validate_success(api.suspend_member(member["id"], _FA))
    reinstated = validate_success(api.reinstate_member(member["id"], _FA))
    assert reinstated["account_status"] == "ACTIVE"
    assert reinstated["verification_status"] == "VERIFIED", \
        "verification dimension must be unaffected by account-dimension transitions"


def test_forbidden_beats_below_minimum_on_cashout(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.11: "Authentication comes first ... Authorization is next: a recognized
    but unpermitted role yields `ERR_FORBIDDEN`."

    A ReviewAgent (forbidden on POST /cashouts) sends a below-minimum request; the
    authorization check pre-empts the fiscal-minimum check.

    Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_below_minimum_on_cashout
    """
    member = create_verified_member("mi@x.com")
    ver = member_version(member["id"])
    resp = api.create_cashout(
        {"member_id": member["id"], "method": "PAYPAL",
         "requested_amount_cents": 100, "expected_member_version": ver}, _RA)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_forbidden_beats_below_minimum_for_finance_admin(api):
    """PRD §3.6: "they request a cash-out, an operation reserved to the `Member`
    role acting on their own wallet."
    PRD §2.11: "Authorization is next: a recognized but unpermitted role yields
    `ERR_FORBIDDEN`."

    A FinanceAdmin (not permitted on POST /cashouts) issuing a below-minimum
    request is stopped at authorization, ahead of the fiscal-minimum check.

    Design: Difficulty/priority_pair_validation_conflict/forbidden_beats_below_minimum_on_cashout
    """
    member = create_verified_member("mifa@x.com")
    ver = member_version(member["id"])
    resp = api.create_cashout(
        {"member_id": member["id"], "method": "PAYPAL",
         "requested_amount_cents": 100, "expected_member_version": ver}, _FA)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_invalid_state_beats_min_spend_on_receipt_approve(api):
    """PRD §2.11: "Only after these structural checks pass does the system evaluate
    state validity (yielding `ERR_INVALID_STATE`, HTTP 409, when the target resource
    is not in a state from which the requested transition is legal), then the
    optimistic-concurrency check ... and finally the domain-specific business
    rules".

    Approving a still-SUBMITTED receipt whose purchase is below min_spend: the
    state check pre-empts the min-spend business rule.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_min_spend_on_receipt_approve
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200, maturity_hold_days=30)
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=300, min_spend_cents=2000)
    member = create_member("mj@x.com")
    hdr = make_member_headers(member["id"])
    scan = validate_success(api.create_receipt_scan({
        "member_id": member["id"], "merchant_id": merchant["id"], "offer_id": offer["id"],
        "purchase_total_cents": 1000, "purchased_at": "2026-01-01T06:00:00Z"}, hdr), 201)
    # Review not started: receipt is SUBMITTED, approve is illegal from there.
    resp = api.approve_receipt_scan(scan["id"], {"review_note": "x"}, _RA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_invalid_state_beats_min_spend_from_rejected(api):
    """PRD §2.11: "shape precedes state, and state precedes business policy."
    PRD §3.4: "The reviewer may instead approve the receipt, moving `IN_REVIEW` to
    `APPROVED`".

    Approve is legal only from IN_REVIEW; a receipt sitting in REJECTED with a
    below-min purchase yields the state error, not the min-spend business error.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_min_spend_on_receipt_approve
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200, maturity_hold_days=30)
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=300, min_spend_cents=2000)
    member = create_member("mjrej@x.com")
    hdr = make_member_headers(member["id"])
    scan = validate_success(api.create_receipt_scan({
        "member_id": member["id"], "merchant_id": merchant["id"], "offer_id": offer["id"],
        "purchase_total_cents": 1000, "purchased_at": "2026-01-01T06:00:00Z"}, hdr), 201)
    validate_success(api.start_review_receipt_scan(scan["id"], _RA))
    validate_success(api.reject_receipt_scan(scan["id"], {"review_note": "no"}, _RA))  # -> REJECTED
    resp = api.approve_receipt_scan(scan["id"], {"review_note": "x"}, _RA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_member_cannot_approve_receipt(api):
    """PRD §2.1: "A `ReviewAgent` reviews uploaded receipts - starting review,
    approving, and rejecting."
    PRD §2.1: "If the role is recognized but is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/member_cannot_approve_receipt
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200)
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=300, min_spend_cents=0)
    member = create_member("rb@x.com")
    hdr = make_member_headers(member["id"])
    scan = validate_success(api.create_receipt_scan({
        "member_id": member["id"], "merchant_id": merchant["id"], "offer_id": offer["id"],
        "purchase_total_cents": 8000, "purchased_at": "2026-01-01T06:00:00Z"}, hdr), 201)
    validate_success(api.start_review_receipt_scan(scan["id"], _RA))
    resp = api.approve_receipt_scan(scan["id"], {"review_note": "x"}, hdr)  # Member calls approve
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_review_agent_cannot_create_offer(api):
    """PRD §2.1: "A `PlatformAdmin` configures merchants and offers".
    PRD §2.1: "If the role is recognized but is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/review_agent_cannot_create_offer
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200)
    resp = api.create_offer(
        {"merchant_id": merchant["id"], "offer_type": "LINKED",
         "starts_at": "2026-01-01T00:00:00Z", "expires_at": "2027-01-01T00:00:00Z"}, _RA)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or does not name one of these four
    roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    bad_headers = build_user_headers("nobody-1", "Nobody")
    resp = api.create_merchant(
        {"name": "M", "online_rate_bps": 500, "instore_rate_bps": 200}, bad_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

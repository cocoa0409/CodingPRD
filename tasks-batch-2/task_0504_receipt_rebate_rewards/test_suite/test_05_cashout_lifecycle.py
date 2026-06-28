"""Cash-out lifecycle: thresholds, OCC, processing/settlement, retry cycle,
terminal lockdown, suspended/unverified guards, and the wallet gross-vs-net
dual-variant.

Translates difficulty `dual_variant_calc` (wallet), `boundary_precision_check`
(min/empty), `cross_entity_state_dependency` (process needs verified), and corner
`state_machines` / `validations` / `cross_cutting` instances.
"""
from test_helpers import (
    validate_success, validate_error, api_client, TEST_USERS, make_member_headers,
    ApiErrorId,
    create_merchant, create_member, create_verified_member,
    create_online_click_and_claim, create_cashout_reserving, set_clock,
    member_version, get_member,
    setup_member_with_two_available_claims, setup_member_with_available_online_claim,
    setup_processing_cashout,
)

_PA = TEST_USERS["platform_admin_headers"]
_FA = TEST_USERS["finance_admin_headers"]


def test_wallet_gross_available_vs_net_cashoutable_diverge(api):
    """PRD §2.6: "`available_balance_cents` is the sum of `amount_cents` over claims
    in `AVAILABLE` only (it deliberately excludes reserved claims) ...
    `net_cashoutable_cents` equals `available_balance_cents` ... so a reserved claim
    shrinks the drawable amount even while the gross available figure is
    unchanged".
    PRD §3.5: "When a cash-out reserves a claim, the claim moves `AVAILABLE` to
    `RESERVED` ... the member's reserved balance rises and `net_cashoutable_cents`
    falls correspondingly."

    Design: Difficulty/dual_variant_calc/wallet_gross_available_vs_net_cashoutable_diverge
    """
    member_id, _, c1, c2 = setup_member_with_two_available_claims(
        per_claim_purchase=10000, online_rate_bps=1000, email="mb2@x.com")
    create_cashout_reserving(member_id, 1000, method="PAYPAL")  # reserves one 1000 claim
    member_now = get_member(member_id)
    assert member_now["available_balance_cents"] == 1000, \
        f"available (unreserved) must be 1000, got {member_now['available_balance_cents']}"
    assert member_now["reserved_balance_cents"] == 1000, \
        f"reserved must be 1000, got {member_now['reserved_balance_cents']}"
    assert member_now["net_cashoutable_cents"] == 1000, \
        f"net cashoutable must be 1000, got {member_now['net_cashoutable_cents']}"


def test_gross_available_conserved_while_net_shrinks_on_reservation(api):
    """PRD §2.6: "There also exists a gross available view - the sum of
    `amount_cents` over claims in either `AVAILABLE` or `RESERVED` - which is the
    gross figure including amounts already reserved by an open cash-out".
    PRD §2.6: "`net_cashoutable_cents` equals `available_balance_cents` ... so a
    reserved claim shrinks the drawable amount even while the gross available figure
    is unchanged".

    The gross view (available + reserved) stays at the pre-reservation total of 2000
    while net_cashoutable drops to the unreserved 1000.

    Design: Difficulty/dual_variant_calc/wallet_gross_available_vs_net_cashoutable_diverge
    """
    member_id, _, c1, c2 = setup_member_with_two_available_claims(
        per_claim_purchase=10000, online_rate_bps=1000, email="mbgross@x.com")
    create_cashout_reserving(member_id, 1000, method="PAYPAL")
    member_now = get_member(member_id)
    gross = member_now["available_balance_cents"] + member_now["reserved_balance_cents"]
    assert gross == 2000, f"gross (available+reserved) must stay 2000, got {gross}"
    assert member_now["net_cashoutable_cents"] == 1000, \
        f"net cashoutable must shrink to 1000, got {member_now['net_cashoutable_cents']}"


def test_cashout_minimum_inclusive_boundary_paypal(api):
    """PRD §3.6: "The requested amount must be at least the per-method minimum -
    500 cents ($5.00) for `PAYPAL` ... a request exactly at the minimum is allowed,
    and one below it is rejected with `ERR_BELOW_CASHOUT_MINIMUM` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/cashout_minimum_inclusive_boundary_paypal
    """
    # 10000 @ 500bps = 500 AVAILABLE; request exactly the 500 PayPal minimum.
    member_id, _, _ = setup_member_with_available_online_claim(
        10000, online_rate_bps=500, email="mk@x.com")
    cashout = create_cashout_reserving(member_id, 500, method="PAYPAL")
    assert cashout["status"] == "REQUESTED"
    assert cashout["requested_amount_cents"] == 500
    # 500 < 5000 -> 2% -> fee = floor(500*200/10000) = 10.
    assert cashout["fee_cents"] == 10, f"fee must be 10, got {cashout['fee_cents']}"


def test_cashout_below_paypal_minimum_rejected(api):
    """PRD §3.6: "The requested amount must be at least the per-method minimum -
    500 cents ($5.00) for `PAYPAL` ... a request exactly at the minimum is allowed,
    and one below it is rejected with `ERR_BELOW_CASHOUT_MINIMUM` (HTTP 422)."

    Boundary X-1: 499 cents (one below the 500 PayPal minimum) is rejected.

    Design: Difficulty/boundary_precision_check/cashout_minimum_inclusive_boundary_paypal
    """
    # 10000 @ 1000bps = 1000 AVAILABLE so balance is not the blocker.
    member_id, _, _ = setup_member_with_available_online_claim(
        10000, online_rate_bps=1000, email="mk499@x.com")
    hdr = make_member_headers(member_id)
    ver = member_version(member_id)
    resp = api.create_cashout(
        {"member_id": member_id, "method": "PAYPAL",
         "requested_amount_cents": 499, "expected_member_version": ver}, hdr)
    validate_error(resp, ApiErrorId.ERR_BELOW_CASHOUT_MINIMUM)


def test_empty_available_set_cashout_insufficient_balance(api):
    """PRD §3.6: "The requested amount must also be no greater than the member's
    `net_cashoutable_cents`; an amount exceeding it is rejected with
    `ERR_INSUFFICIENT_BALANCE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/empty_available_set_cashout_has_no_reservable_claims
    """
    member = create_verified_member("ml@x.com")
    hdr = make_member_headers(member["id"])
    ver = member_version(member["id"])
    resp = api.create_cashout(
        {"member_id": member["id"], "method": "PAYPAL",
         "requested_amount_cents": 500, "expected_member_version": ver}, hdr)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE)


def test_pending_only_balance_is_not_cashoutable(api):
    """PRD §3.6: "The requested amount must also be no greater than the member's
    `net_cashoutable_cents`; an amount exceeding it is rejected with
    `ERR_INSUFFICIENT_BALANCE` (HTTP 422)."
    PRD §2.6: "`net_cashoutable_cents` equals `available_balance_cents`".

    A member whose only claim is still PENDING (unmatured) has net_cashoutable 0,
    so any cash-out hits the empty drawable set - the same outcome as having no
    claims at all.

    Design: Difficulty/boundary_precision_check/empty_available_set_cashout_has_no_reservable_claims
    """
    merchant = create_merchant(online_rate_bps=1000, instore_rate_bps=200, maturity_hold_days=30)
    member = create_verified_member("mlpend@x.com")
    create_online_click_and_claim(member["id"], merchant["id"], 10000)  # PENDING, not matured
    hdr = make_member_headers(member["id"])
    ver = member_version(member["id"])
    resp = api.create_cashout(
        {"member_id": member["id"], "method": "PAYPAL",
         "requested_amount_cents": 500, "expected_member_version": ver}, hdr)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE)


def test_gift_card_minimum_boundary_rejects_below(api):
    """PRD §3.6: "1,000 cents ($10.00) for `GIFT_CARD`; a request exactly at the
    minimum is allowed, and one below it is rejected with
    `ERR_BELOW_CASHOUT_MINIMUM` (HTTP 422)."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_giftcard_minimum_boundary
    """
    # 10000 @ 5000bps = 5000 AVAILABLE so balance is not the blocker.
    member_id, _, _ = setup_member_with_available_online_claim(
        10000, online_rate_bps=5000, email="gc@x.com")
    hdr = make_member_headers(member_id)
    ver = member_version(member_id)
    resp = api.create_cashout(
        {"member_id": member_id, "method": "GIFT_CARD",
         "requested_amount_cents": 999, "expected_member_version": ver}, hdr)
    validate_error(resp, ApiErrorId.ERR_BELOW_CASHOUT_MINIMUM)


def test_cashout_insufficient_balance_above_net(api):
    """PRD §3.6: "The requested amount must also be no greater than the member's
    `net_cashoutable_cents`; an amount exceeding it is rejected with
    `ERR_INSUFFICIENT_BALANCE` (HTTP 422)."

    Design: Corner/validations/cashout_insufficient_balance_above_net
    """
    member_id, _, _ = setup_member_with_available_online_claim(
        10000, online_rate_bps=1000, email="ib@x.com")  # 1000 AVAILABLE
    hdr = make_member_headers(member_id)
    ver = member_version(member_id)
    resp = api.create_cashout(
        {"member_id": member_id, "method": "PAYPAL",
         "requested_amount_cents": 2000, "expected_member_version": ver}, hdr)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE)


def test_suspended_member_cannot_create_cashout(api):
    """PRD §3.6: "The member must not be suspended: if `account_status` is
    `SUSPENDED`, creation is rejected with `ERR_MEMBER_SUSPENDED`."

    Design: Corner/validations/suspended_member_cannot_create_cashout
    """
    member_id, _, _ = setup_member_with_available_online_claim(
        10000, online_rate_bps=1000, email="su@x.com")  # 1000 AVAILABLE, VERIFIED
    validate_success(api.suspend_member(member_id, _FA))
    hdr = make_member_headers(member_id)
    ver = member_version(member_id)
    resp = api.create_cashout(
        {"member_id": member_id, "method": "PAYPAL",
         "requested_amount_cents": 1000, "expected_member_version": ver}, hdr)
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED)


def test_process_cashout_requires_member_verified(api):
    """PRD §3.6: "Processing moves a cash-out `REQUESTED` to `PROCESSING`, and
    requires that the member's `account_status` be `ACTIVE` (else
    `ERR_MEMBER_SUSPENDED`) and `verification_status` be `VERIFIED` (else
    `ERR_MEMBER_NOT_VERIFIED`, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cashout_process_requires_member_verified
    """
    # UNVERIFIED member with a 1000 AVAILABLE claim and a REQUESTED cash-out.
    member_id, _, _ = setup_member_with_available_online_claim(
        10000, online_rate_bps=1000, verified=False, email="mm@x.com")
    cashout = create_cashout_reserving(member_id, 1000, method="PAYPAL")
    resp = api.process_cashout(cashout["id"], _FA)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_VERIFIED)


def test_process_cashout_succeeds_when_member_active_and_verified(api):
    """PRD §3.6: "Processing moves a cash-out `REQUESTED` to `PROCESSING`, and
    requires that the member's `account_status` be `ACTIVE` (else
    `ERR_MEMBER_SUSPENDED`) and `verification_status` be `VERIFIED` (else
    `ERR_MEMBER_NOT_VERIFIED`, HTTP 409)."

    Complementary positive path: a verified, active member's REQUESTED cash-out
    processes to PROCESSING.

    Design: Difficulty/cross_entity_state_dependency/cashout_process_requires_member_verified
    """
    member_id, _, _ = setup_member_with_available_online_claim(
        10000, online_rate_bps=1000, verified=True, email="mmok@x.com")
    cashout = create_cashout_reserving(member_id, 1000, method="PAYPAL")
    processed = validate_success(api.process_cashout(cashout["id"], _FA))
    assert processed["status"] == "PROCESSING"


def test_occ_correct_member_version_succeeds(api):
    """PRD §2.8: "A request to create a cash-out must carry `expected_member_version`,
    the `version` of the owning `Member` that the client last observed."
    PRD §3.6: "On creation it reserves the member's `AVAILABLE` claims ... and the
    member's `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_member_version_succeeds
    """
    member_id, _, _ = setup_member_with_available_online_claim(
        10000, online_rate_bps=1000, email="oc@x.com")
    hdr = make_member_headers(member_id)
    ver = member_version(member_id)
    resp = api.create_cashout(
        {"member_id": member_id, "method": "PAYPAL",
         "requested_amount_cents": 1000, "expected_member_version": ver}, hdr)
    cashout = validate_success(resp, expected_status=201)
    assert cashout["status"] == "REQUESTED"


def test_occ_stale_member_version_rejected(api):
    """PRD §2.8: "If another writer has advanced the member's `version` since the
    client last read it ... then `expected_member_version` will no longer match the
    member's current `version`, and the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_member_version_rejected
    """
    merchant = create_merchant(online_rate_bps=1000, instore_rate_bps=200, maturity_hold_days=30)
    member = create_member("sv2@x.com")
    create_online_click_and_claim(member["id"], merchant["id"], 10000)
    set_clock("2026-02-15T00:00:00Z")
    stale_ver = member_version(member["id"])      # captured BEFORE verify bumps version
    validate_success(api.verify_member(member["id"], _FA))
    hdr = make_member_headers(member["id"])
    resp = api.create_cashout(
        {"member_id": member["id"], "method": "PAYPAL",
         "requested_amount_cents": 1000, "expected_member_version": stale_ver}, hdr)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_settle_paid_cascades_claims_to_paid(api):
    """PRD §3.6: "When `outcome` is `PAID`, the cash-out becomes `PAID` (its terminal
    state), a `CASHOUT_DEBIT` ledger entry is emitted ... every claim whose
    `cashout_id` equals this cash-out moves `RESERVED` to `PAID`, the member's
    reserved balance falls, and `lifetime_paid_cents` rises."

    Design: Corner/state_machines/cashout_paid_cascades_claims_to_paid
    """
    member_id, claim_id, cashout_id = setup_processing_cashout(
        purchase_amount_cents=10000, online_rate_bps=1000,
        requested_amount_cents=1000, email="se@x.com")
    settled = validate_success(api.settle_cashout(cashout_id, {"outcome": "PAID"}, _FA))
    assert settled["status"] == "PAID"
    claim = validate_success(api.get_reward_claim(claim_id, _FA))
    assert claim["status"] == "PAID"
    member_now = get_member(member_id)
    assert member_now["lifetime_paid_cents"] == 1000
    assert member_now["reserved_balance_cents"] == 0


def test_paid_cashout_cannot_be_processed_again(api):
    """PRD §2.11: "`ERR_INVALID_STATE`, HTTP 409, when the target resource is not in
    a state from which the requested transition is legal".
    PRD §3.6: "When `outcome` is `PAID`, the cash-out becomes `PAID` (its terminal
    state)".

    Design: Corner/state_machines/terminal_paid_cashout_cannot_be_processed
    """
    _, _, cashout_id = setup_processing_cashout(
        purchase_amount_cents=10000, online_rate_bps=1000,
        requested_amount_cents=1000, email="st@x.com")
    validate_success(api.settle_cashout(cashout_id, {"outcome": "PAID"}, _FA))
    resp = api.process_cashout(cashout_id, _FA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_failed_cashout_retry_re_reserves_claim(api):
    """PRD §3.6: "A `FAILED` cash-out is not terminal: a `FinanceAdmin` may retry it,
    transitioning `FAILED` to `REQUESTED`, provided the member's
    `net_cashoutable_cents` is at least the cash-out's `requested_amount_cents` at
    retry time ... retry re-reserves available claims up to `requested_amount_cents`,
    oldest `created_at` first, moving each `AVAILABLE` to `RESERVED`".

    Design: Corner/state_machines/failed_cashout_retry_cycle_re_reserves
    """
    member_id, claim_id, cashout_id = setup_processing_cashout(
        purchase_amount_cents=10000, online_rate_bps=1000,
        requested_amount_cents=1000, email="sc@x.com")
    validate_success(api.settle_cashout(cashout_id, {"outcome": "FAILED"}, _FA))
    retried = validate_success(api.retry_cashout(cashout_id, _FA))
    assert retried["status"] == "REQUESTED"
    claim = validate_success(api.get_reward_claim(claim_id, _FA))
    assert claim["status"] == "RESERVED"
    member_now = get_member(member_id)
    assert member_now["reserved_balance_cents"] == 1000

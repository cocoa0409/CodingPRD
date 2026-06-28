"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty DB) before each test.
Setup calls use get_success_data() so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_member_headers

_PA = TEST_USERS["platform_admin_headers"]
_RA = TEST_USERS["review_agent_headers"]
_FA = TEST_USERS["finance_admin_headers"]

# A clock instant well past a 30-day maturity hold for claims created at the
# 2026-01-01 startup default (PRD §2.10), but before any default offer expiry.
MATURITY_CLOCK_ISO = "2026-02-15T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1/2: primitive builders
# ---------------------------------------------------------------------------
def create_merchant(online_rate_bps=500, instore_rate_bps=200, **overrides):
    payload = {"name": "M", "online_rate_bps": online_rate_bps,
               "instore_rate_bps": instore_rate_bps}
    payload.update(overrides)
    return get_success_data(api_client.create_merchant(payload, _PA))


def create_offer(merchant_id, offer_type, starts_at="2026-01-01T00:00:00Z",
                 expires_at="2027-01-01T00:00:00Z", **overrides):
    payload = {"merchant_id": merchant_id, "offer_type": offer_type,
               "starts_at": starts_at, "expires_at": expires_at}
    payload.update(overrides)
    return get_success_data(api_client.create_offer(payload, _PA))


def create_member(email, **overrides):
    payload = {"email": email}
    payload.update(overrides)
    return get_success_data(api_client.create_member(payload, _PA))


def create_verified_member(email, **overrides):
    member = create_member(email, **overrides)
    get_success_data(api_client.verify_member(member["id"], _FA))
    # Re-read so the returned record reflects VERIFIED + bumped version.
    return get_success_data(api_client.get_member(member["id"], make_member_headers(member["id"])))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, _FA))


def get_member(member_id):
    return get_success_data(api_client.get_member(member_id, make_member_headers(member_id)))


def member_version(member_id):
    return get_member(member_id)["version"]


# ---------------------------------------------------------------------------
# Tier 1: claim builders (online + in-store)
# ---------------------------------------------------------------------------
def create_online_click_and_claim(member_id, merchant_id, purchase_amount_cents,
                                  offer_id=None):
    """Record a click then file an ONLINE reward claim. Returns (click, claim)."""
    hdr = make_member_headers(member_id)
    click_payload = {"member_id": member_id, "merchant_id": merchant_id}
    if offer_id is not None:
        click_payload["offer_id"] = offer_id
    click = get_success_data(api_client.create_clickthrough(click_payload, hdr))
    claim_payload = {
        "member_id": member_id, "merchant_id": merchant_id,
        "click_through_id": click["id"], "purchase_amount_cents": purchase_amount_cents,
    }
    if offer_id is not None:
        claim_payload["offer_id"] = offer_id
    claim = get_success_data(api_client.create_reward_claim(claim_payload, hdr))
    return click, claim


def create_in_store_approved_claim(member_id, merchant_id, offer_id,
                                   purchase_total_cents, purchased_at="2026-01-01T06:00:00Z"):
    """Upload receipt -> start-review -> approve. Returns (receipt_scan, claim)."""
    hdr = make_member_headers(member_id)
    scan = get_success_data(api_client.create_receipt_scan({
        "member_id": member_id, "merchant_id": merchant_id, "offer_id": offer_id,
        "purchase_total_cents": purchase_total_cents, "purchased_at": purchased_at,
    }, hdr))
    get_success_data(api_client.start_review_receipt_scan(scan["id"], _RA))
    scan = get_success_data(api_client.approve_receipt_scan(scan["id"], {"review_note": "ok"}, _RA))
    claim = get_success_data(api_client.get_reward_claim(scan["reward_claim_id"], _FA))
    return scan, claim


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------
def setup_member_with_available_online_claim(purchase_amount_cents, online_rate_bps=1000,
                                             verified=True, email="m@x.com",
                                             maturity_hold_days=30):
    """Create a merchant + member + a single ONLINE claim, then advance the clock
    so the claim matures to AVAILABLE. Returns (member_id, merchant_id, claim_id).

    With online_rate_bps and purchase_amount_cents chosen by the caller, the
    matured AVAILABLE balance is floor(purchase * rate / 10000).
    """
    merchant = create_merchant(online_rate_bps=online_rate_bps,
                               maturity_hold_days=maturity_hold_days)
    if verified:
        member = create_verified_member(email)
    else:
        member = create_member(email)
    _, claim = create_online_click_and_claim(member["id"], merchant["id"], purchase_amount_cents)
    set_clock(MATURITY_CLOCK_ISO)
    return member["id"], merchant["id"], claim["id"]


def setup_member_with_two_available_claims(per_claim_purchase=10000, online_rate_bps=1000,
                                           verified=True, email="m2@x.com"):
    """Member + two matured AVAILABLE ONLINE claims of floor(purchase*rate/10000) each.
    Returns (member_id, merchant_id, claim1_id, claim2_id)."""
    merchant = create_merchant(online_rate_bps=online_rate_bps, maturity_hold_days=30)
    if verified:
        member = create_verified_member(email)
    else:
        member = create_member(email)
    _, claim1 = create_online_click_and_claim(member["id"], merchant["id"], per_claim_purchase)
    _, claim2 = create_online_click_and_claim(member["id"], merchant["id"], per_claim_purchase)
    set_clock(MATURITY_CLOCK_ISO)
    return member["id"], merchant["id"], claim1["id"], claim2["id"]


def create_cashout_reserving(member_id, requested_amount_cents, method="PAYPAL"):
    """Create a cash-out against the member at its current version (reserving
    AVAILABLE claims). Returns the cash-out record."""
    hdr = make_member_headers(member_id)
    ver = member_version(member_id)
    return get_success_data(api_client.create_cashout({
        "member_id": member_id, "method": method,
        "requested_amount_cents": requested_amount_cents,
        "expected_member_version": ver,
    }, hdr))


def setup_processing_cashout(purchase_amount_cents=10000, online_rate_bps=1000,
                             requested_amount_cents=1000, email="proc@x.com"):
    """Verified member with one AVAILABLE claim, a cash-out created (reserving it)
    and moved to PROCESSING. Returns (member_id, claim_id, cashout_id)."""
    member_id, _, claim_id = setup_member_with_available_online_claim(
        purchase_amount_cents, online_rate_bps=online_rate_bps, email=email)
    cashout = create_cashout_reserving(member_id, requested_amount_cents)
    get_success_data(api_client.process_cashout(cashout["id"], _FA))
    return member_id, claim_id, cashout_id_of(cashout)


def cashout_id_of(cashout):
    return cashout["id"]


# ---------------------------------------------------------------------------
# Tier 1: receipt scan builders for review-lifecycle tests
# ---------------------------------------------------------------------------
def setup_receipt_in_review(rebate_cents=300, min_spend_cents=0, instore_rate_bps=200,
                            purchase_total_cents=8000, double_dip_allowed=True,
                            offer_expires_at="2027-01-01T00:00:00Z",
                            purchased_at="2026-01-01T06:00:00Z", email="ir@x.com"):
    """Member + RECEIPT_REBATE offer + receipt scan moved to IN_REVIEW.
    Returns (member_id, merchant_id, offer_id, scan_id)."""
    merchant = create_merchant(instore_rate_bps=instore_rate_bps,
                               double_dip_allowed=double_dip_allowed)
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=rebate_cents,
                         min_spend_cents=min_spend_cents, expires_at=offer_expires_at)
    member = create_member(email)
    scan = get_success_data(api_client.create_receipt_scan({
        "member_id": member["id"], "merchant_id": merchant["id"], "offer_id": offer["id"],
        "purchase_total_cents": purchase_total_cents, "purchased_at": purchased_at,
    }, make_member_headers(member["id"])))
    get_success_data(api_client.start_review_receipt_scan(scan["id"], _RA))
    return member["id"], merchant["id"], offer["id"], scan["id"]


def setup_receipt_submitted(rebate_cents=300, min_spend_cents=0, purchase_total_cents=8000,
                            email="sub@x.com"):
    """Member + RECEIPT_REBATE offer + a SUBMITTED receipt (review not started).
    Returns (member_id, merchant_id, offer_id, scan_id)."""
    merchant = create_merchant()
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=rebate_cents,
                         min_spend_cents=min_spend_cents)
    member = create_member(email)
    scan = get_success_data(api_client.create_receipt_scan({
        "member_id": member["id"], "merchant_id": merchant["id"], "offer_id": offer["id"],
        "purchase_total_cents": purchase_total_cents, "purchased_at": "2026-01-01T06:00:00Z",
    }, make_member_headers(member["id"])))
    return member["id"], merchant["id"], offer["id"], scan["id"]


# ---------------------------------------------------------------------------
# Referral builders
# ---------------------------------------------------------------------------
def create_referral(referrer_member_id, referee_email, **overrides):
    payload = {"referrer_member_id": referrer_member_id, "referee_email": referee_email}
    payload.update(overrides)
    return get_success_data(api_client.create_referral(payload, make_member_headers(referrer_member_id)))


def setup_qualified_referral(referee_qualifying_cents=1000, bonus_cents=500,
                             referrer_email="refr@x.com", referee_email="refe@x.com"):
    """Referrer + referral; referee signs up and earns >= qualifying cents so the
    referral reaches QUALIFIED. Returns (referrer_id, referee_id, referral_id)."""
    merchant = create_merchant(online_rate_bps=5000, maturity_hold_days=0)
    referrer = create_member(referrer_email)
    referral = create_referral(referrer["id"], referee_email,
                               referee_qualifying_cents=referee_qualifying_cents,
                               bonus_cents=bonus_cents)
    referee = create_member(referee_email, referred_by_member_id=referrer["id"])
    # Referee earns: 10000 @ 5000bps = 5000 AVAILABLE >= 1000 qualifying.
    create_online_click_and_claim(referee["id"], merchant["id"], 10000)
    set_clock("2026-01-02T00:00:00Z")  # maturity_hold_days=0 matures immediately on advance
    return referrer["id"], referee["id"], referral["id"]

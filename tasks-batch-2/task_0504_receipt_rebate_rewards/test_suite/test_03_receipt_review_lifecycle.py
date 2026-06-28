"""Receipt-scan review lifecycle: reject/resubmit cycle, approve cascade, and the
cross-entity offer-active and double-dip approval guards.

Translates difficulty `non_linear_state_machine` (receipt cycle),
`transitive_cascade` (approve spawns claim + ledger), `cross_entity_state_dependency`
(start-review needs active offer), `resource_temporal_overlap` (double-dip buffer),
and corner `state_machines` (terminal re-approve) instances.
"""
from test_helpers import (
    validate_success, validate_error, api_client, TEST_USERS, make_member_headers,
    ApiErrorId,
    create_merchant, create_offer, create_member,
    create_online_click_and_claim, set_clock, get_member,
    setup_receipt_in_review,
)

_PA = TEST_USERS["platform_admin_headers"]
_RA = TEST_USERS["review_agent_headers"]
_FA = TEST_USERS["finance_admin_headers"]


def test_receipt_reject_then_resubmit_then_approve(api):
    """PRD §3.4: "a rejected receipt is not terminal - it may be re-reviewed,
    transitioning `REJECTED` back to `IN_REVIEW`".
    PRD §3.4: "The reviewer may instead approve the receipt, moving `IN_REVIEW` to
    `APPROVED`, the one terminal state of the receipt machine."
    PRD §3.4: "step one creates a new reward claim for this member, merchant, and
    offer with `IN_STORE` attribution".

    Design: Difficulty/non_linear_state_machine/receipt_scan_reject_then_resubmit_cycle
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200, maturity_hold_days=30)
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=300, min_spend_cents=0)
    member = create_member("me@x.com")
    hdr = make_member_headers(member["id"])
    scan = validate_success(api.create_receipt_scan({
        "member_id": member["id"], "merchant_id": merchant["id"], "offer_id": offer["id"],
        "purchase_total_cents": 8000, "purchased_at": "2026-01-01T06:00:00Z"}, hdr), 201)
    validate_success(api.start_review_receipt_scan(scan["id"], _RA))
    validate_success(api.reject_receipt_scan(scan["id"], {"review_note": "blurry"}, _RA))
    validate_success(api.start_review_receipt_scan(scan["id"], _RA))  # resubmit REJECTED->IN_REVIEW
    approved = validate_success(api.approve_receipt_scan(scan["id"], {"review_note": "clear now"}, _RA))
    assert approved["status"] == "APPROVED"
    claim = validate_success(api.get_reward_claim(approved["reward_claim_id"], _FA))
    assert claim["attribution"] == "IN_STORE"


def test_rejected_receipt_can_be_resubmitted_to_in_review(api):
    """PRD §3.4: "a rejected receipt is not terminal - it may be re-reviewed,
    transitioning `REJECTED` back to `IN_REVIEW` (subject to the same offer-active
    precondition as the first start-review)."

    The back-edge itself (REJECTED -> IN_REVIEW) is observable as a status change,
    distinct from the eventual approve.

    Design: Difficulty/non_linear_state_machine/receipt_scan_reject_then_resubmit_cycle
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200, maturity_hold_days=30)
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=300, min_spend_cents=0)
    member = create_member("me2@x.com")
    hdr = make_member_headers(member["id"])
    scan = validate_success(api.create_receipt_scan({
        "member_id": member["id"], "merchant_id": merchant["id"], "offer_id": offer["id"],
        "purchase_total_cents": 8000, "purchased_at": "2026-01-01T06:00:00Z"}, hdr), 201)
    validate_success(api.start_review_receipt_scan(scan["id"], _RA))
    rejected = validate_success(api.reject_receipt_scan(scan["id"], {"review_note": "blurry"}, _RA))
    assert rejected["status"] == "REJECTED"
    resubmitted = validate_success(api.start_review_receipt_scan(scan["id"], _RA))
    assert resubmitted["status"] == "IN_REVIEW", \
        "a REJECTED receipt must transition back to IN_REVIEW on resubmit"


def test_receipt_approve_spawns_pending_claim_and_ledger(api):
    """PRD §3.4: "step one creates a new reward claim for this member, merchant, and
    offer with `IN_STORE` attribution, beginning in `PENDING`, whose `amount_cents`
    is computed by the in-store variant below; step two emits a `CLAIM_PENDING`
    ledger entry for that new claim."
    PRD §2.6: "`pending_balance_cents` is the sum of `amount_cents` over the
    member's claims in `PENDING`".

    Design: Difficulty/transitive_cascade/receipt_approve_spawns_claim_and_pending_ledger_entry
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200, maturity_hold_days=30)
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=300, min_spend_cents=2000)
    member = create_member("mh@x.com")
    hdr = make_member_headers(member["id"])
    scan = validate_success(api.create_receipt_scan({
        "member_id": member["id"], "merchant_id": merchant["id"], "offer_id": offer["id"],
        "purchase_total_cents": 8000, "purchased_at": "2026-01-01T06:00:00Z"}, hdr), 201)
    validate_success(api.start_review_receipt_scan(scan["id"], _RA))
    approved = validate_success(api.approve_receipt_scan(scan["id"], {"review_note": "ok"}, _RA))
    claim = validate_success(api.get_reward_claim(approved["reward_claim_id"], _FA))
    assert claim["status"] == "PENDING"
    # In-store: floor(8000*200/10000)=160 + rebate 300 = 460 (<= 8000).
    assert claim["amount_cents"] == 460, f"in-store reward must be 460, got {claim['amount_cents']}"
    member_now = get_member(member["id"])
    assert member_now["pending_balance_cents"] == 460, \
        f"pending balance must be 460, got {member_now['pending_balance_cents']}"
    entries = validate_success(
        api.list_member_ledger_entries(member["id"], hdr, params={"entry_type": "CLAIM_PENDING"}))
    if isinstance(entries, dict):
        entries = [entries]
    assert any(e["entry_type"] == "CLAIM_PENDING" for e in entries), \
        "a CLAIM_PENDING ledger entry must be emitted on claim creation"


def test_receipt_approve_sets_reward_claim_id_on_scan(api):
    """PRD §3.4: "The receipt's `reward_claim_id` is then set to the new claim's
    `id`."
    PRD §3.4: "step one creates a new reward claim for this member, merchant, and
    offer with `IN_STORE` attribution, beginning in `PENDING`".

    The cascade's link-back side effect (scan.reward_claim_id pointing at the new
    PENDING claim) is distinct from the ledger-entry side effect.

    Design: Difficulty/transitive_cascade/receipt_approve_spawns_claim_and_pending_ledger_entry
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200, maturity_hold_days=30)
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=300, min_spend_cents=2000)
    member = create_member("mh2@x.com")
    hdr = make_member_headers(member["id"])
    scan = validate_success(api.create_receipt_scan({
        "member_id": member["id"], "merchant_id": merchant["id"], "offer_id": offer["id"],
        "purchase_total_cents": 8000, "purchased_at": "2026-01-01T06:00:00Z"}, hdr), 201)
    validate_success(api.start_review_receipt_scan(scan["id"], _RA))
    approved = validate_success(api.approve_receipt_scan(scan["id"], {"review_note": "ok"}, _RA))
    assert approved["reward_claim_id"], "approve must set the scan's reward_claim_id"
    claim = validate_success(api.get_reward_claim(approved["reward_claim_id"], _FA))
    assert claim["status"] == "PENDING"
    assert claim["attribution"] == "IN_STORE"


def test_start_review_blocked_when_offer_expired(api):
    """PRD §3.4: "Moving a receipt from `SUBMITTED` to `IN_REVIEW` (starting review)
    requires that the referenced offer be `ACTIVE` and that the current clock fall
    within the offer's `starts_at` and `expires_at` window, inclusive; if not, the
    transition is rejected with `ERR_OFFER_INACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/receipt_review_start_requires_offer_active
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200, maturity_hold_days=30)
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=300, min_spend_cents=0,
                         expires_at="2026-03-01T00:00:00Z")
    member = create_member("mn@x.com")
    hdr = make_member_headers(member["id"])
    scan = validate_success(api.create_receipt_scan({
        "member_id": member["id"], "merchant_id": merchant["id"], "offer_id": offer["id"],
        "purchase_total_cents": 8000, "purchased_at": "2026-02-01T06:00:00Z"}, hdr), 201)
    set_clock("2026-04-01T00:00:00Z")  # past offer expiry -> EXPIRED
    resp = api.start_review_receipt_scan(scan["id"], _RA)
    validate_error(resp, ApiErrorId.ERR_OFFER_INACTIVE)


def test_approve_blocked_when_offer_expired(api):
    """PRD §3.4: "(The start-review transition itself is also subject to the
    offer-active rule above, so `ERR_OFFER_INACTIVE` can surface both at
    start-review and at approve.)"

    The same Offer-status dependency gates approve, not just start-review: a receipt
    moved to IN_REVIEW while the offer was active is blocked at approve once the
    clock has crossed the offer's expiry.

    Design: Difficulty/cross_entity_state_dependency/receipt_review_start_requires_offer_active
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200, maturity_hold_days=30)
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=300, min_spend_cents=0,
                         expires_at="2026-03-01T00:00:00Z")
    member = create_member("mn2@x.com")
    hdr = make_member_headers(member["id"])
    scan = validate_success(api.create_receipt_scan({
        "member_id": member["id"], "merchant_id": merchant["id"], "offer_id": offer["id"],
        "purchase_total_cents": 8000, "purchased_at": "2026-02-01T06:00:00Z"}, hdr), 201)
    validate_success(api.start_review_receipt_scan(scan["id"], _RA))  # while offer ACTIVE
    set_clock("2026-04-01T00:00:00Z")  # offer now EXPIRED
    resp = api.approve_receipt_scan(scan["id"], {"review_note": "x"}, _RA)
    validate_error(resp, ApiErrorId.ERR_OFFER_INACTIVE)


def test_double_dip_blocks_in_store_approve_within_buffer(api):
    """PRD §3.4: "then, if the merchant's `double_dip_allowed` is false, there must
    be no existing non-clawed-back reward claim with `ONLINE` attribution for the
    same member and merchant whose underlying click's `clicked_at` is within 24
    hours of the receipt's `purchased_at`, else `ERR_DOUBLE_DIP_BLOCKED` (HTTP
    409)."

    Design: Difficulty/resource_temporal_overlap/double_dip_window_24h_buffer_blocks_complementary_reward
    """
    merchant = create_merchant(online_rate_bps=1000, instore_rate_bps=200,
                               double_dip_allowed=False, attribution_window_hours=168,
                               maturity_hold_days=30)
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=300, min_spend_cents=0)
    member = create_member("mp@x.com")
    hdr = make_member_headers(member["id"])
    set_clock("2026-01-02T00:00:00Z")
    create_online_click_and_claim(member["id"], merchant["id"], 10000)  # ONLINE reward at clock
    scan = validate_success(api.create_receipt_scan({
        "member_id": member["id"], "merchant_id": merchant["id"], "offer_id": offer["id"],
        "purchase_total_cents": 8000, "purchased_at": "2026-01-02T06:00:00Z"}, hdr), 201)
    validate_success(api.start_review_receipt_scan(scan["id"], _RA))
    resp = api.approve_receipt_scan(scan["id"], {"review_note": "dup"}, _RA)
    validate_error(resp, ApiErrorId.ERR_DOUBLE_DIP_BLOCKED)


def test_double_dip_allowed_permits_complementary_reward(api):
    """PRD §3.1: "when false, a single qualifying purchase may earn either a
    click-attributed reward or a receipt-rebate reward but not both, and when true
    the two may stack."
    PRD §3.4: "then, if the merchant's `double_dip_allowed` is false, there must be
    no existing non-clawed-back reward claim with `ONLINE` attribution".

    The double-dip guard is conditioned on `double_dip_allowed == false`; with it
    true, an in-store approve succeeds despite an ONLINE reward in the buffer.

    Design: Difficulty/resource_temporal_overlap/double_dip_window_24h_buffer_blocks_complementary_reward
    """
    merchant = create_merchant(online_rate_bps=1000, instore_rate_bps=200,
                               double_dip_allowed=True, attribution_window_hours=168,
                               maturity_hold_days=30)
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=300, min_spend_cents=0)
    member = create_member("mp2@x.com")
    hdr = make_member_headers(member["id"])
    set_clock("2026-01-02T00:00:00Z")
    create_online_click_and_claim(member["id"], merchant["id"], 10000)
    scan = validate_success(api.create_receipt_scan({
        "member_id": member["id"], "merchant_id": merchant["id"], "offer_id": offer["id"],
        "purchase_total_cents": 8000, "purchased_at": "2026-01-02T06:00:00Z"}, hdr), 201)
    validate_success(api.start_review_receipt_scan(scan["id"], _RA))
    approved = validate_success(api.approve_receipt_scan(scan["id"], {"review_note": "ok"}, _RA))
    assert approved["status"] == "APPROVED", \
        "with double_dip_allowed true the complementary in-store reward must be allowed"


def test_approve_already_approved_receipt_invalid_state(api):
    """PRD §3.4: "The reviewer may instead approve the receipt, moving `IN_REVIEW`
    to `APPROVED`, the one terminal state of the receipt machine."
    PRD §2.11: "`ERR_INVALID_STATE`, HTTP 409, when the target resource is not in a
    state from which the requested transition is legal".

    Design: Corner/state_machines/cancel_unknown_transition_approve_already_approved_receipt
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200)
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=300, min_spend_cents=0)
    member = create_member("sa@x.com")
    hdr = make_member_headers(member["id"])
    scan = validate_success(api.create_receipt_scan({
        "member_id": member["id"], "merchant_id": merchant["id"], "offer_id": offer["id"],
        "purchase_total_cents": 8000, "purchased_at": "2026-01-01T06:00:00Z"}, hdr), 201)
    validate_success(api.start_review_receipt_scan(scan["id"], _RA))
    validate_success(api.approve_receipt_scan(scan["id"], {"review_note": "ok"}, _RA))
    resp = api.approve_receipt_scan(scan["id"], {"review_note": "again"}, _RA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

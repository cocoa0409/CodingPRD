"""Multi-entity cascades: completing a session that exhausts a prepaid package fulfills the
engagement and auto-creates a lookbook; paying a referee's first invoice qualifies a referral
and credits the referrer's wallet; cancelling an engagement cascades to its sessions.
"""
from test_helpers import (
    validate_success, validate_paginated,
    setup_confirmed_session, setup_signed_up_referral_with_issued_invoice,
    create_stylist, register_client, create_active_engagement, schedule_session,
    complete_session_payload, make_client_headers, make_stylist_headers, make_admin_headers,
)


# ─────────────── transitive_cascade / complete_session_fulfills_package_then_autocreates_lookbook ───────────────
def test_complete_exhausting_package_fulfills_engagement(api):
    """PRD §3.4: "if after that consumption hours_available_blocks has reached 0 and no sibling
    session under the engagement remains SCHEDULED or CONFIRMED, the engagement transitions
    automatically from ACTIVE to FULFILLED."

    Design: Difficulty/transitive_cascade/complete_session_fulfills_package_then_autocreates_lookbook
    """
    ctx = setup_confirmed_session(api, mode="PACKAGE", block_rate_cents=3000,
                                  package_blocks=6, package_price_cents=18000)
    validate_success(api.complete_session(
        ctx["session"]["id"], complete_session_payload(90),
        make_stylist_headers(ctx["stylist"]["id"])), 200)
    eng = validate_success(api.get_engagement(ctx["engagement"]["id"], make_admin_headers()), 200)
    assert eng["status"] == "FULFILLED"
    assert eng["hours_consumed_blocks"] == 6
    assert eng["hours_available_blocks"] == 0


def test_fulfillment_autocreates_draft_lookbook(api):
    """PRD §3.4: "That fulfillment in turn auto-creates one lookbook in DRAFT titled 'Final
    Lookbook' under the engagement, ready for outfit delivery."

    Design: Difficulty/transitive_cascade/complete_session_fulfills_package_then_autocreates_lookbook
    """
    ctx = setup_confirmed_session(api, mode="PACKAGE", block_rate_cents=3000,
                                  package_blocks=6, package_price_cents=18000)
    validate_success(api.complete_session(
        ctx["session"]["id"], complete_session_payload(90),
        make_stylist_headers(ctx["stylist"]["id"])), 200)
    lookbooks, meta = validate_paginated(
        api.list_lookbooks(ctx["engagement"]["id"], make_admin_headers()))
    assert meta["total_count"] == 1, f"exactly one auto-created lookbook, got {meta['total_count']}"
    assert lookbooks[0]["status"] == "DRAFT"


# ─────────────── transitive_cascade / pay_first_invoice_credits_referral_then_referrer_wallet ───────────────
def test_pay_first_invoice_credits_referral(api):
    """PRD §3.9: "When a referral is SIGNED_UP, the paying invoice's engagement belongs to the
    referee client, and the referee had no prior paid invoice, the referral transitions
    automatically from SIGNED_UP to the terminal CREDITED state. At that point
    qualifying_invoice_id is set to that invoice, and realized_credit_cents is computed as the
    lesser of the cap of 10000 cents and ten percent of the qualifying invoice's total_cents
    rounded half up."

    Design: Difficulty/transitive_cascade/pay_first_invoice_credits_referral_then_referrer_wallet
    """
    ctx = setup_signed_up_referral_with_issued_invoice(api, clock_iso="2026-03-20T00:00:00Z")
    validate_success(api.pay_invoice(ctx["invoice"]["id"],
                                     make_client_headers(ctx["referee"]["id"])), 200)
    refl = validate_success(api.get_referral(ctx["referral"]["id"], make_admin_headers()), 200)
    assert refl["status"] == "CREDITED"
    assert refl["realized_credit_cents"] == 1980, f"min(10000, round(0.10*19800))=1980, got {refl['realized_credit_cents']}"
    assert refl["qualifying_invoice_id"] == ctx["invoice"]["id"]


def test_referral_credit_lands_in_referrer_wallet(api):
    """PRD §3.9: "That realized credit is then added to the referrer's wallet_credit_cents."

    Design: Difficulty/transitive_cascade/pay_first_invoice_credits_referral_then_referrer_wallet
    """
    ctx = setup_signed_up_referral_with_issued_invoice(api, clock_iso="2026-03-20T00:00:00Z")
    validate_success(api.pay_invoice(ctx["invoice"]["id"],
                                     make_client_headers(ctx["referee"]["id"])), 200)
    referrer = validate_success(api.get_client(ctx["referrer"]["id"], make_admin_headers()), 200)
    assert referrer["wallet_credit_cents"] == 1980, (
        f"referrer wallet should receive 1980, got {referrer['wallet_credit_cents']}")


# ─────────────── Corner: engagement_cancel_cascade_visible_immediately ───────────────
def test_engagement_cancel_cascades_to_session_and_releases_blocks(api):
    """PRD §3.2: "Cancellation cascades: every session under the engagement that is still
    SCHEDULED or CONFIRMED is set to CANCELLED, and for a PACKAGE engagement each such session's
    reserved blocks are released back to availability (its estimated_blocks are subtracted from
    hours_reserved_blocks and added to hours_available_blocks)."

    Design: Corner/consistency_model/engagement_cancel_cascade_visible_immediately
    """
    sty = create_stylist(api)
    cl = register_client(api)
    eng = create_active_engagement(api, cl["id"], sty["id"], mode="PACKAGE", block_rate_cents=3000,
                                   package_blocks=8, package_price_cents=24000)
    sess = schedule_session(api, eng["id"], cl["id"], eng["version"],
                            scheduled_start="2026-04-27T10:00:00Z",
                            scheduled_end="2026-04-27T11:30:00Z")
    eng_after = validate_success(api.cancel_engagement(eng["id"], make_client_headers(cl["id"])), 200)
    assert eng_after["status"] == "CANCELLED"
    assert eng_after["hours_reserved_blocks"] == 0
    assert eng_after["hours_available_blocks"] == 8
    sess_after = validate_success(api.get_session(sess["id"], make_admin_headers()), 200)
    assert sess_after["status"] == "CANCELLED"

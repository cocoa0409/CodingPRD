"""Compensating-invariant ledgers: cancelling a session restores the PACKAGE block pool, and
returning a purchased item reverses both the engagement's retail spend and the stylist's
earned commission back to their pre-purchase totals.
"""
from test_helpers import (
    validate_success, assert_package_hours_conserved,
    setup_shopping_session_with_item,
    create_stylist, register_client, create_active_engagement, schedule_session,
    make_client_headers, make_stylist_headers, make_admin_headers,
)


# ─────────────── compensating_invariant / package_hours_conserved_on_session_cancel ───────────────
def test_cancel_session_releases_reserved_blocks(api):
    """PRD §3.4: "For a PACKAGE engagement, cancellation releases the session's estimated_blocks —
    subtracting them from hours_reserved_blocks and adding them to hours_available_blocks — so the
    conservation invariant of §2.7 is restored."

    Design: Difficulty/compensating_invariant/package_hours_conserved_on_session_cancel
    """
    sty = create_stylist(api)
    cl = register_client(api)
    eng = create_active_engagement(api, cl["id"], sty["id"], mode="PACKAGE", block_rate_cents=3000,
                                   package_blocks=20, package_price_cents=60000)
    sess = schedule_session(api, eng["id"], cl["id"], eng["version"],
                            scheduled_start="2026-04-14T10:00:00Z",
                            scheduled_end="2026-04-14T11:30:00Z")
    sess_after = validate_success(api.cancel_session(sess["id"], make_client_headers(cl["id"])), 200)
    assert sess_after["status"] == "CANCELLED"
    eng_after = validate_success(api.get_engagement(eng["id"], make_admin_headers()), 200)
    assert eng_after["hours_reserved_blocks"] == 0
    assert eng_after["hours_available_blocks"] == 20
    assert eng_after["hours_consumed_blocks"] == 0


def test_package_pool_conserved_through_reserve_and_release(api):
    """PRD §2.7: "the conservation invariant holds after every mutation: package_blocks always
    equals the sum of available, reserved, and consumed blocks."

    Design: Difficulty/compensating_invariant/package_hours_conserved_on_session_cancel
    """
    sty = create_stylist(api)
    cl = register_client(api)
    eng = create_active_engagement(api, cl["id"], sty["id"], mode="PACKAGE", block_rate_cents=3000,
                                   package_blocks=20, package_price_cents=60000)
    sess = schedule_session(api, eng["id"], cl["id"], eng["version"],
                            scheduled_start="2026-04-14T10:00:00Z",
                            scheduled_end="2026-04-14T11:30:00Z")
    reserved = validate_success(api.get_engagement(eng["id"], make_admin_headers()), 200)
    assert reserved["hours_available_blocks"] == 14  # 20 - 6 reserved
    assert_package_hours_conserved(reserved)
    validate_success(api.cancel_session(sess["id"], make_client_headers(cl["id"])), 200)
    released = validate_success(api.get_engagement(eng["id"], make_admin_headers()), 200)
    assert released["hours_available_blocks"] == 20
    assert_package_hours_conserved(released)


# ─────────────── compensating_invariant / retail_spend_and_commission_conserved_on_return ───────────────
def test_return_item_reverses_engagement_retail_spend(api):
    """PRD §3.5: "A return reverses both ledgers: the engagement's retail_spend_cents is reduced
    by the item's marked_up_price_cents and the stylist's earned_commission_cents is reduced by
    the item's commission_cents, returning both conserved totals to their pre-purchase values."

    Design: Difficulty/compensating_invariant/retail_spend_and_commission_conserved_on_return
    """
    ctx = setup_shopping_session_with_item(api, commission_pct=0.40, retail_cost_cents=8000)
    before = validate_success(api.get_engagement(ctx["engagement"]["id"], make_admin_headers()), 200)
    assert before["retail_spend_cents"] == 9600, "purchase advanced retail_spend to 9600"
    item_after = validate_success(api.return_item(ctx["item"]["id"],
                                                  make_stylist_headers(ctx["stylist"]["id"])), 200)
    assert item_after["status"] == "RETURNED"
    after = validate_success(api.get_engagement(ctx["engagement"]["id"], make_admin_headers()), 200)
    assert after["retail_spend_cents"] == 0, f"return should reverse retail spend, got {after['retail_spend_cents']}"


def test_return_item_reverses_stylist_commission(api):
    """PRD §3.5: "the stylist's earned_commission_cents is reduced by the item's commission_cents,
    returning both conserved totals to their pre-purchase values."

    Design: Difficulty/compensating_invariant/retail_spend_and_commission_conserved_on_return
    """
    ctx = setup_shopping_session_with_item(api, commission_pct=0.40, retail_cost_cents=8000)
    before = validate_success(api.get_stylist(ctx["stylist"]["id"], make_admin_headers()), 200)
    assert before["earned_commission_cents"] == 640, "purchase advanced commission to 640"
    validate_success(api.return_item(ctx["item"]["id"], make_stylist_headers(ctx["stylist"]["id"])), 200)
    after = validate_success(api.get_stylist(ctx["stylist"]["id"], make_admin_headers()), 200)
    assert after["earned_commission_cents"] == 0, (
        f"return should reverse commission to 0, got {after['earned_commission_cents']}")

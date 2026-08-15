"""Repair-shop referrals: verdict gating, selector ranking and tie-break,
decline/successor chain, identity checks, and the completion fee."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, build_user_headers,
    create_product, create_branch, create_customer, create_branch_stock,
    create_shipped_line, create_shop, create_referral,
    file_claim, begin_analysis, render_verdict,
    setup_stocked_scenario, setup_verdicted_claim, setup_misapplication_referral,
    get_referral, make_service_shop_headers,
    ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["system_admin_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


def _setup_two_claims_two_shops():
    """Shipped line qty 2; claim1 CONFIRMED_DEFECT (APPROVED), claim2
    MISAPPLICATION (DENIED); shops S1 rate 8000 and S2 rate 7500, region R1."""
    ctx = setup_stocked_scenario(list_price_cents=7000, on_hand_qty=10)
    order, line, _ = create_shipped_line(
        ctx["customer"]["id"], ctx["branch"]["id"], ctx["product"]["id"],
        ctx["stock"]["id"], qty=2)
    claim1 = file_claim(ctx["product"]["id"], "wa-3", order_line_id=line["id"],
                        failure_mode="FATIGUE", operating_hours=100, qty=1)
    claim2 = file_claim(ctx["product"]["id"], "wa-3", order_line_id=line["id"],
                        failure_mode="MISALIGNMENT", operating_hours=300, qty=1)
    begin_analysis(claim1["id"], "qe-3")
    claim1 = render_verdict(claim1["id"], "CONFIRMED_DEFECT", "qe-3")
    begin_analysis(claim2["id"], "qe-3")
    claim2 = render_verdict(claim2["id"], "MISAPPLICATION", "qe-3")
    s1 = create_shop(name="Hub City Repair", region="R1", labor_rate_cents=8000)
    s2 = create_shop(name="Precision Rework", region="R1", labor_rate_cents=7500)
    ctx.update({"order": order, "line": line, "claim1": claim1,
                "claim2": claim2, "s1": s1, "s2": s2})
    return ctx


def test_referral_on_approved_claim_rejected(api):
    """PRD §3.10: "A `WarrantyAnalyst` creates a referral naming
    `warranty_claim_id` and the required service `region`; the claim's verdict
    must be `MISAPPLICATION` (`ERR_REFERRAL_VERDICT_NOT_MISAPPLICATION`, 409)."

    Design: Difficulty/cross_entity_state_dependency/referral_requires_misapplication_verdict
    """
    ctx = _setup_two_claims_two_shops()
    res = api.create_service_referral(
        {"warranty_claim_id": ctx["claim1"]["id"], "region": "R1"},
        build_user_headers("wa-3", "WarrantyAnalyst"))
    validate_error(res, ApiErrorId.ERR_REFERRAL_VERDICT_NOT_MISAPPLICATION,
                   expected_status=409)


def test_referral_selector_picks_lowest_labor_rate(api):
    """PRD §3.10: "Candidates rank by `labor_rate_cents` ascending, ties broken
    by the shop's `created_at` ascending; the shop's `id` is never used for
    ranking or tie-break." and "The referral is born `OPEN` with
    `service_shop_id` set to the selector's choice".

    Design: Difficulty/cross_entity_state_dependency/referral_requires_misapplication_verdict
    """
    ctx = _setup_two_claims_two_shops()
    referral = validate_success(api.create_service_referral(
        {"warranty_claim_id": ctx["claim2"]["id"], "region": "R1"},
        build_user_headers("wa-3", "WarrantyAnalyst")), 201)
    assert referral["status"] == "OPEN"
    assert referral["service_shop_id"] == ctx["s2"]["id"], (
        f"cheapest eligible shop (7500 < 8000) must win; got "
        f"{referral['service_shop_id']}")


def test_referral_decline_creates_successor_excluding_decliner(api):
    """PRD §3.10: "Declining requires `OPEN` and the same identity check; the
    referral moves to `DECLINED`, the shop's id is appended to the claim's
    referral chain `declined_shop_ids`, and the system immediately creates a
    successor referral in `OPEN` for the same claim, re-running the selector
    with all decliners excluded".

    Design: Corner/state_machines/referral_decline_creates_successor_excluding_decliner
    """
    ctx = setup_stocked_scenario(list_price_cents=7000, on_hand_qty=5)
    order, line, _ = create_shipped_line(
        ctx["customer"]["id"], ctx["branch"]["id"], ctx["product"]["id"],
        ctx["stock"]["id"], qty=1)
    claim = file_claim(ctx["product"]["id"], "wa-6", order_line_id=line["id"],
                       failure_mode="MISALIGNMENT", operating_hours=300, qty=1)
    begin_analysis(claim["id"], "qe-6")
    render_verdict(claim["id"], "MISAPPLICATION", "qe-6")
    s1 = create_shop(name="Alpha Repair", region="R9", labor_rate_cents=8000)
    s2 = create_shop(name="Beta Repair", region="R9", labor_rate_cents=7500)
    ref1 = create_referral(claim["id"], "R9", analyst_user_id="wa-6")
    assert ref1["service_shop_id"] == s2["id"], "cheapest shop selected first"

    declined = validate_success(api.decline_referral(
        ref1["id"], make_service_shop_headers(s2["id"])), 200)
    assert declined["status"] == "DECLINED"

    open_list, _meta = validate_paginated(
        api.list_service_referrals(
            TEST_USERS["warranty_analyst_headers"],
            params={"warranty_claim_id": claim["id"], "status": "OPEN"}))
    assert len(open_list) == 1, f"exactly one successor OPEN; got {len(open_list)}"
    ref2 = open_list[0]
    assert ref2["service_shop_id"] == s1["id"], (
        "decliner excluded from re-selection; next-ranked shop wins")
    assert s2["id"] in ref2["declined_shop_ids"]


def test_referral_fee_percentage_and_cap(api):
    """PRD §3.10: "the referral fee is 10 percent of `quoted_amount_cents`,
    rounded half-up, capped at 25000 cents — that is, the fee is the lesser of
    the rounded percentage and the cap".

    Design: Corner/calculations/referral_fee_percentage_and_cap
    """
    ctx = setup_stocked_scenario(list_price_cents=7000, on_hand_qty=5)
    order, line, _ = create_shipped_line(
        ctx["customer"]["id"], ctx["branch"]["id"], ctx["product"]["id"],
        ctx["stock"]["id"], qty=2)
    claims = []
    for hours in (100, 200):
        claim = file_claim(ctx["product"]["id"], "wa-8",
                           order_line_id=line["id"],
                           failure_mode="MISALIGNMENT",
                           operating_hours=hours, qty=1)
        begin_analysis(claim["id"], "qe-8")
        claims.append(render_verdict(claim["id"], "MISAPPLICATION", "qe-8"))
    shop = create_shop(name="Gamma Repair", region="R7", labor_rate_cents=9000)
    ref1 = create_referral(claims[0]["id"], "R7", analyst_user_id="wa-8")
    ref2 = create_referral(claims[1]["id"], "R7", analyst_user_id="wa-8")

    shop_headers = make_service_shop_headers(shop["id"])
    validate_success(api.accept_referral(
        ref1["id"], {"quoted_amount_cents": 100000}, shop_headers), 200)
    completed1 = validate_success(api.complete_referral(ref1["id"], shop_headers), 200)
    assert completed1["status"] == "COMPLETED"
    assert completed1["referral_fee_cents"] == 10000, (
        f"10% of 100000 = 10000; got {completed1['referral_fee_cents']}")

    validate_success(api.accept_referral(
        ref2["id"], {"quoted_amount_cents": 300000}, shop_headers), 200)
    completed2 = validate_success(api.complete_referral(ref2["id"], shop_headers), 200)
    assert completed2["referral_fee_cents"] == 25000, (
        f"cap binds: 10% of 300000 = 30000 > 25000; got {completed2['referral_fee_cents']}")


def test_referral_selector_tie_breaks_by_created_at(api):
    """PRD §3.10: "Candidates rank by `labor_rate_cents` ascending, ties broken
    by the shop's `created_at` ascending; the shop's `id` is never used for
    ranking or tie-break."

    Design: Corner/calculations/referral_selector_tie_breaks_by_created_at
    """
    ctx = setup_stocked_scenario(list_price_cents=7000, on_hand_qty=5)
    order, line, _ = create_shipped_line(
        ctx["customer"]["id"], ctx["branch"]["id"], ctx["product"]["id"],
        ctx["stock"]["id"], qty=1)
    claim = file_claim(ctx["product"]["id"], "wa-t", order_line_id=line["id"],
                       failure_mode="MISALIGNMENT", operating_hours=10, qty=1)
    begin_analysis(claim["id"], "qe-t")
    render_verdict(claim["id"], "MISAPPLICATION", "qe-t")
    t1 = create_shop(name="Tie One Repair", region="R5", labor_rate_cents=8000)
    t2 = create_shop(name="Tie Two Repair", region="R5", labor_rate_cents=8000)
    referral = create_referral(claim["id"], "R5", analyst_user_id="wa-t")
    assert referral["service_shop_id"] == t1["id"], (
        f"rate tie 8000 == 8000 broken by earlier created_at; got "
        f"{referral['service_shop_id']}")


def test_no_eligible_shop_when_region_unmatched(api):
    """PRD §3.10: "Eligibility requires the shop be `ACTIVE`, the claim's
    product family appear in the shop's `capabilities`, the shop's `region`
    equal the referral's `region`, and the shop's id not appear among the
    `declined_shop_ids` of this claim's referral chain" and "If no eligible
    shop exists at creation, the request fails with `ERR_NO_ELIGIBLE_SHOP`
    (409)."

    Design: Corner/errors/no_eligible_shop_when_region_unmatched
    """
    ctx = setup_stocked_scenario(list_price_cents=7000, on_hand_qty=5)
    order, line, _ = create_shipped_line(
        ctx["customer"]["id"], ctx["branch"]["id"], ctx["product"]["id"],
        ctx["stock"]["id"], qty=1)
    claim = file_claim(ctx["product"]["id"], "wa-r", order_line_id=line["id"],
                       failure_mode="MISALIGNMENT", operating_hours=10, qty=1)
    begin_analysis(claim["id"], "qe-r")
    render_verdict(claim["id"], "MISAPPLICATION", "qe-r")
    create_shop(name="Faraway Repair", region="R8", labor_rate_cents=9000)
    res = api.create_service_referral(
        {"warranty_claim_id": claim["id"], "region": "R7"},
        build_user_headers("wa-r", "WarrantyAnalyst"))
    validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_SHOP, expected_status=409)


def test_referral_accept_by_wrong_shop_rejected(api):
    """PRD §3.10: "The chosen shop responds under its own identity —
    `X-User-ID` must equal the referral's `service_shop_id`
    (`ERR_REFERRAL_SHOP_MISMATCH`, 403)."

    Design: Corner/errors/referral_accept_by_wrong_shop_rejected
    """
    ctx = setup_stocked_scenario(list_price_cents=7000, on_hand_qty=5)
    order, line, _ = create_shipped_line(
        ctx["customer"]["id"], ctx["branch"]["id"], ctx["product"]["id"],
        ctx["stock"]["id"], qty=1)
    claim = file_claim(ctx["product"]["id"], "wa-m", order_line_id=line["id"],
                       failure_mode="MISALIGNMENT", operating_hours=10, qty=1)
    begin_analysis(claim["id"], "qe-m")
    render_verdict(claim["id"], "MISAPPLICATION", "qe-m")
    s1 = create_shop(name="Delta Repair", region="R6", labor_rate_cents=8000)
    s2 = create_shop(name="Epsilon Repair", region="R6", labor_rate_cents=7500)
    referral = create_referral(claim["id"], "R6", analyst_user_id="wa-m")
    assert referral["service_shop_id"] == s2["id"], "selector picks the cheaper shop"
    res = api.accept_referral(referral["id"], {"quoted_amount_cents": 50000},
                              make_service_shop_headers(s1["id"]))
    validate_error(res, ApiErrorId.ERR_REFERRAL_SHOP_MISMATCH, expected_status=403)
    assert get_referral(referral["id"])["status"] == "OPEN"

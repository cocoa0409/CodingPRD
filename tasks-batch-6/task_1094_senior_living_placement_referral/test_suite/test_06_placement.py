"""Placement reservation, the four-level move-in cascade, the parallel
residency/billing axes and placement-creation guards.
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated, get_success_data,
    create_advisor, create_community, create_inventory, create_family, create_inquiry,
    assign_advisor, create_approved_assessment, set_clock,
    make_advisor_headers, make_community_manager_headers,
    create_match_payload, create_tour_payload, create_placement_payload,
    build_scenario,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _selected_match(api, ahdr, inquiry_id, community_id, *, tour_day):
    m = get_success_data(api.create_match(create_match_payload(inquiry_id, community_id), ahdr))
    api.shortlist_match(m["id"], ahdr)
    t = get_success_data(api.create_tour(create_tour_payload(
        m["id"], scheduled_start=f"2026-06-{tour_day}T15:00:00Z",
        scheduled_end=f"2026-06-{tour_day}T16:00:00Z", mode="IN_PERSON"), ahdr))
    api.complete_tour(t["id"], {"outcome_rating": 4}, ahdr)
    api.select_match(m["id"], ahdr)
    return m, t


# ---------------------------------------------------------------------------
# Difficulty: estimated vs final referral fee diverge (>=2 tests).
# ---------------------------------------------------------------------------

def test_referral_fee_estimated_and_final_diverge_on_identical_inputs(api):
    """PRD §3.11: "The **estimated variant** runs at placement creation and is
    stored in `estimated_fee_cents`. It uses the match's `quoted_monthly_rate_cents`
    as the rate, the match's `care_level` as the level, and a ratio of exactly 1.0".
    PRD §3.11: "Because of proration, an identical rate and care level still yield a
    different final fee from the estimate whenever the move-in day of month is not
    the 1st."

    Design: Difficulty/dual_variant_calc/referral_fee_estimated_vs_final_diverges_on_identical_rate_and_care_level
    """
    sc = build_scenario(api, "moved_in")
    p = sc["placement"]
    assert p["estimated_fee_cents"] == 492500
    assert p["final_fee_cents"] == 180583
    assert p["final_fee_cents"] != p["estimated_fee_cents"]


def test_move_in_drafts_invoice_seeded_with_final_fee(api):
    """PRD §3.10: "and creates a `DRAFT` referral invoice whose `final_fee_cents` is
    seeded from the placement, moving the placement's billing axis `NOT_INVOICED →
    INVOICE_DRAFTED`."

    Design: Difficulty/dual_variant_calc/referral_fee_estimated_vs_final_diverges_on_identical_rate_and_care_level
    """
    sc = build_scenario(api, "moved_in")
    p = validate_success(api.get_placement(sc["placement"]["id"], ADMIN))
    assert p["residency_status"] == "MOVED_IN"
    assert p["billing_status"] == "INVOICE_DRAFTED"
    rows, _ = validate_paginated(api.list_invoices(sc["billing"], params={"placement_id": p["id"]}))
    assert len(rows) == 1
    assert rows[0]["status"] == "DRAFT"
    assert rows[0]["final_fee_cents"] == 180583


# ---------------------------------------------------------------------------
# Difficulty: residency and billing axes advance independently (>=2 tests).
# ---------------------------------------------------------------------------

def test_residency_confirmation_leaves_paid_billing_untouched(api):
    """PRD §3.10: "Confirmation leaves the billing axis untouched, so it may fire
    while billing is `NOT_INVOICED`, `INVOICE_DRAFTED`, `INVOICED` or `PAID`."

    Design: Difficulty/non_linear_state_machine/placement_residency_and_billing_axes_advance_independently
    """
    sc = build_scenario(api, "paid")
    set_clock(api, "2026-07-04T09:00:00Z")
    p = validate_success(api.confirm_residency(sc["placement"]["id"], sc["advisor_headers"]))
    assert p["residency_status"] == "RESIDENT_CONFIRMED"
    assert p["billing_status"] == "PAID"


def test_paid_invoice_state_survives_residency_confirmation(api):
    """PRD §2.9: "Whenever an operation mutates a resource, that resource's
    `updated_at` is refreshed".
    PRD §3.12: "Payment ... moves the invoice `ACCEPTED → PAID`, and moves the
    placement's billing axis `INVOICED → PAID`."

    Design: Difficulty/non_linear_state_machine/placement_residency_and_billing_axes_advance_independently
    """
    sc = build_scenario(api, "paid")
    set_clock(api, "2026-07-04T09:00:00Z")
    validate_success(api.confirm_residency(sc["placement"]["id"], sc["advisor_headers"]))
    inv = validate_success(api.get_invoice(sc["invoice"]["id"], ADMIN))
    assert inv["status"] == "PAID"
    assert inv["paid_amount_cents"] == 180583
    assert inv["net_recognized_fee_cents"] == 180583
    community = validate_success(api.get_community(sc["community"]["id"], ADMIN))
    assert community["fee_balance_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty: depth-4 move-in cascade to sibling tour cancellation (>=2 tests).
# ---------------------------------------------------------------------------

def _depth4_setup(api):
    """Q1 TOURING: M1 SELECTED with placement P1 PENDING, M2 SHORTLISTED with a
    still-SCHEDULED tour T2. Advisor holds one ACTIVE assignment. Clock at move-in."""
    set_clock(api, "2026-06-01T00:00:00Z")
    ann = create_advisor(api, full_name="Ann Reyes")
    c1 = create_community(api, name="Cedar Grove")
    c2 = create_community(api, name="Willow Bend", contract_tier="STANDARD",
                          referral_fee_pct=0.80, quality_rating=3.5)
    inv1 = create_inventory(api, c1["id"], monthly_rate_cents=500000)
    create_inventory(api, c2["id"], total_units=4, monthly_rate_cents=480000)
    family = create_family(api)
    inquiry = create_inquiry(api, family["id"])
    assign_advisor(api, inquiry["id"], ann["id"])
    create_approved_assessment(api, inquiry["id"], ann["id"])
    ahdr = make_advisor_headers(ann["id"])
    m1 = get_success_data(api.create_match(create_match_payload(inquiry["id"], c1["id"]), ahdr))
    m2 = get_success_data(api.create_match(create_match_payload(inquiry["id"], c2["id"]), ahdr))
    api.shortlist_match(m1["id"], ahdr)
    api.shortlist_match(m2["id"], ahdr)
    t1 = get_success_data(api.create_tour(create_tour_payload(
        m1["id"], scheduled_start="2026-06-05T15:00:00Z",
        scheduled_end="2026-06-05T16:00:00Z", mode="IN_PERSON"), ahdr))
    api.complete_tour(t1["id"], {"outcome_rating": 4}, ahdr)
    t2 = get_success_data(api.create_tour(create_tour_payload(
        m2["id"], scheduled_start="2026-06-08T15:00:00Z",
        scheduled_end="2026-06-08T16:00:00Z", mode="IN_PERSON"), ahdr))
    api.select_match(m1["id"], ahdr)
    inv1_full = validate_success(api.get_inventory(inv1["id"], ADMIN))
    p1 = get_success_data(api.create_placement(
        create_placement_payload(m1["id"], inv1["id"], inv1_full["version"]), ahdr))
    set_clock(api, "2026-06-20T12:00:00Z")
    return {"ann": ann, "c1": c1, "inv1": inv1, "inquiry": inquiry, "m1": m1, "m2": m2,
            "t1": t1, "t2": t2, "p1": p1, "cm": make_community_manager_headers(c1["id"])}


def test_move_in_cascades_depth4_to_sibling_tour_cancellation(api):
    """PRD §3.10: "**Level 3**, caused by that placement, moves every match of the
    inquiry still in `PROPOSED`, `SHORTLISTED`, `TOUR_SCHEDULED` or `TOURED` to
    `WITHDRAWN` ... **Level 4**, caused by the level-3 withdrawals, moves every
    still-`SCHEDULED` tour on those withdrawn matches to `CANCELLED` with
    `cancel_reason_code` `MATCH_WITHDRAWN`, releasing each such community tour slot."

    Design: Difficulty/transitive_cascade/move_in_confirmation_depth4_chain_to_sibling_tour_cancellation
    """
    ctx = _depth4_setup(api)
    validate_success(api.confirm_move_in(
        ctx["p1"]["id"], {"actual_move_in_date": "2026-06-20", "actual_care_level": "ASSISTED_LIVING"}, ctx["cm"]))
    assert validate_success(api.get_placement(ctx["p1"]["id"], ADMIN))["residency_status"] == "MOVED_IN"
    assert validate_success(api.get_inquiry(ctx["inquiry"]["id"], ADMIN))["status"] == "PLACED"
    assert validate_success(api.get_match(ctx["m2"]["id"], ADMIN))["status"] == "WITHDRAWN"
    assert validate_success(api.get_match(ctx["m1"]["id"], ADMIN))["status"] == "SELECTED"
    t2 = validate_success(api.get_tour(ctx["t2"]["id"], ADMIN))
    assert t2["status"] == "CANCELLED" and t2["cancel_reason_code"] == "MATCH_WITHDRAWN"
    assert validate_success(api.get_tour(ctx["t1"]["id"], ADMIN))["status"] == "COMPLETED"


def test_move_in_releases_caseload_and_moves_inventory_counts(api):
    """PRD §3.10: "moves the inquiry's `ACTIVE` caseload assignment to `RELEASED`
    with `release_reason` `PLACED` and `released_at` from the clock, decrementing the
    owning advisor's `active_caseload_count` by 1 and recomputing both its load
    indices."
    PRD §3.10: "moves the pool's counts (decrement `reserved_units` by 1, increment
    `occupied_units` by 1, recompute `available_units`, bump `version`)".

    Design: Difficulty/transitive_cascade/move_in_confirmation_depth4_chain_to_sibling_tour_cancellation
    """
    ctx = _depth4_setup(api)
    validate_success(api.confirm_move_in(
        ctx["p1"]["id"], {"actual_move_in_date": "2026-06-20", "actual_care_level": "ASSISTED_LIVING"}, ctx["cm"]))
    advisor = validate_success(api.get_advisor(ctx["ann"]["id"], ADMIN))
    assert advisor["active_caseload_count"] == 0
    assert advisor["headcount_load_index"] == 0.0
    rows, _ = validate_paginated(api.list_caseload_assignments(ADMIN, params={"inquiry_id": ctx["inquiry"]["id"]}))
    assert len(rows) == 1
    assert rows[0]["status"] == "RELEASED" and rows[0]["release_reason"] == "PLACED"
    inv = validate_success(api.get_inventory(ctx["inv1"]["id"], ADMIN))
    assert inv["reserved_units"] == 0 and inv["occupied_units"] == 1 and inv["available_units"] == 4


# ---------------------------------------------------------------------------
# Difficulty: placement rejected when available_units is exactly zero (>=2 tests).
# ---------------------------------------------------------------------------

def _second_selected_same_single_unit_community(api):
    """Cedar Grove has a single-unit pool held by P1 (Q1). Q2 has a SELECTED match
    M2 at the same community."""
    sc = build_scenario(api, "pending", inventory_overrides={"total_units": 1})
    ann_id = sc["advisor"]["id"]
    ahdr = sc["advisor_headers"]
    fam2 = create_family(api)
    q2 = create_inquiry(api, fam2["id"], origin="PHONE", target_move_in_date="2026-06-25")
    assign_advisor(api, q2["id"], ann_id)
    create_approved_assessment(api, q2["id"], ann_id, gross_monthly_income_cents=300000,
                               va_eligible=False, marital_status="WIDOWED")
    m2, _ = _selected_match(api, ahdr, q2["id"], sc["community"]["id"], tour_day="06")
    return sc, q2, m2


def test_placement_rejected_when_available_units_exactly_zero(api):
    """PRD §3.10: "and the chosen pool must have `available_units` of at least 1,
    else `ERR_NO_UNITS_AVAILABLE`."

    Design: Difficulty/boundary_precision_check/placement_rejected_when_inventory_available_units_is_exactly_zero
    """
    sc, q2, m2 = _second_selected_same_single_unit_community(api)
    inv = validate_success(api.get_inventory(sc["inventory"]["id"], ADMIN))
    assert inv["available_units"] == 0
    resp = api.create_placement(
        create_placement_payload(m2["id"], sc["inventory"]["id"], inv["version"],
                                 agreed_move_in_date="2026-06-25"), sc["advisor_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_UNITS_AVAILABLE)


def test_zero_units_placement_leaves_pool_and_match_intact(api):
    """PRD §3.1: "`available_units` is `total_units` minus `reserved_units` minus
    `occupied_units`, never allowed to go below 0."

    Design: Difficulty/boundary_precision_check/placement_rejected_when_inventory_available_units_is_exactly_zero
    """
    sc, q2, m2 = _second_selected_same_single_unit_community(api)
    inv = validate_success(api.get_inventory(sc["inventory"]["id"], ADMIN))
    resp = api.create_placement(
        create_placement_payload(m2["id"], sc["inventory"]["id"], inv["version"],
                                 agreed_move_in_date="2026-06-25"), sc["advisor_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_UNITS_AVAILABLE)
    inv2 = validate_success(api.get_inventory(sc["inventory"]["id"], ADMIN))
    assert inv2["total_units"] == 1 and inv2["reserved_units"] == 1 and inv2["available_units"] == 0
    assert validate_success(api.get_match(m2["id"], ADMIN))["status"] == "SELECTED"
    rows, _ = validate_paginated(api.list_placements(ADMIN, params={"inquiry_id": q2["id"]}))
    assert rows == []


# ---------------------------------------------------------------------------
# Corner: placement guards and compensation.
# ---------------------------------------------------------------------------

def test_placement_cancel_restores_inventory_conservation(api):
    """PRD §3.10: "Cancellation moves the placement `PENDING_MOVE_IN → CANCELLED`,
    releases the held unit (decrement `reserved_units` by 1, recompute
    `available_units`, bump the pool's `version`), and — deliberately — leaves the
    underlying match in `SELECTED` so a replacement placement can be created."

    Design: Corner/state_machines/placement_cancel_restores_inventory_unit_conservation
    """
    sc = build_scenario(api, "pending")
    validate_success(api.cancel_placement(sc["placement"]["id"], {"reason_code": "FAMILY_CHANGED_MIND"}, sc["advisor_headers"]))
    p = validate_success(api.get_placement(sc["placement"]["id"], ADMIN))
    assert p["residency_status"] == "CANCELLED"
    assert p["billing_status"] == "NOT_INVOICED"
    inv = validate_success(api.get_inventory(sc["inventory"]["id"], ADMIN))
    assert inv["reserved_units"] == 0 and inv["occupied_units"] == 0
    assert inv["available_units"] == 5 and inv["total_units"] == 5
    assert validate_success(api.get_match(sc["match"]["id"], ADMIN))["status"] == "SELECTED"
    rows, _ = validate_paginated(api.list_invoices(sc["billing"], params={"placement_id": sc["placement"]["id"]}))
    assert rows == []


def test_second_placement_on_same_inquiry_rejected(api):
    """PRD §3.10: "the inquiry must not already have a placement whose residency is
    anything other than `CANCELLED` or `MOVED_OUT`, else `ERR_PLACEMENT_EXISTS`".

    Design: Corner/validations/second_placement_on_the_same_inquiry_returns_placement_exists
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    ann = create_advisor(api, full_name="Ann Reyes")
    c1 = create_community(api, name="Cedar Grove")
    c2 = create_community(api, name="Willow Bend", contract_tier="STANDARD",
                          referral_fee_pct=0.80, quality_rating=3.5)
    inv1 = create_inventory(api, c1["id"], monthly_rate_cents=500000)
    inv2 = create_inventory(api, c2["id"], total_units=4, monthly_rate_cents=480000)
    family = create_family(api)
    inquiry = create_inquiry(api, family["id"])
    assign_advisor(api, inquiry["id"], ann["id"])
    create_approved_assessment(api, inquiry["id"], ann["id"])
    ahdr = make_advisor_headers(ann["id"])
    m1, _ = _selected_match(api, ahdr, inquiry["id"], c1["id"], tour_day="05")
    m2, _ = _selected_match(api, ahdr, inquiry["id"], c2["id"], tour_day="06")
    inv1_full = validate_success(api.get_inventory(inv1["id"], ADMIN))
    p1 = get_success_data(api.create_placement(
        create_placement_payload(m1["id"], inv1["id"], inv1_full["version"]), ahdr))
    inv2_full = validate_success(api.get_inventory(inv2["id"], ADMIN))
    resp = api.create_placement(
        create_placement_payload(m2["id"], inv2["id"], inv2_full["version"],
                                 agreed_move_in_date="2026-06-25",
                                 contracted_monthly_rate_cents=480000), ahdr)
    validate_error(resp, ApiErrorId.ERR_PLACEMENT_EXISTS)
    rows, _ = validate_paginated(api.list_placements(ADMIN, params={"inquiry_id": inquiry["id"]}))
    assert len(rows) == 1 and rows[0]["id"] == p1["id"]
    inv2_after = validate_success(api.get_inventory(inv2["id"], ADMIN))
    assert inv2_after["reserved_units"] == 0 and inv2_after["available_units"] == 4
    assert validate_success(api.get_match(m2["id"], ADMIN))["status"] == "SELECTED"


def test_placement_create_with_stale_inventory_version_rejected(api):
    """PRD §2.8: "Reserving a unit — the placement-creation endpoint — requires an
    `expected_inventory_version` field carrying the client's last observed `version`
    of the target `CommunityInventory`. If that value does not equal the inventory's
    current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/placement_create_with_stale_inventory_version_returns_stale_version
    """
    sc = build_scenario(api, "selected")
    stale_version = sc["inventory_version"]
    validate_success(api.update_inventory(sc["inventory"]["id"], {"total_units": 6}, sc["cm_headers"]))
    resp = api.create_placement(
        create_placement_payload(sc["match"]["id"], sc["inventory"]["id"], stale_version),
        sc["advisor_headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    inv = validate_success(api.get_inventory(sc["inventory"]["id"], ADMIN))
    assert inv["reserved_units"] == 0 and inv["available_units"] == 6
    assert inv["version"] == stale_version + 1
    rows, _ = validate_paginated(api.list_placements(ADMIN, params={"match_id": sc["match"]["id"]}))
    assert rows == []


def test_confirm_residency_before_move_in_returns_invalid_state(api):
    """PRD §3.10: "Residency confirmation moves the placement `MOVED_IN →
    RESIDENT_CONFIRMED` and is allowed only once the logical clock's current UTC
    calendar date is at least the `actual_move_in_date` plus 14 days".

    Design: Corner/validations/confirming_residency_before_move_in_returns_placement_invalid_state
    """
    sc = build_scenario(api, "pending")
    resp = api.confirm_residency(sc["placement"]["id"], sc["advisor_headers"])
    err = validate_error(resp, ApiErrorId.ERR_PLACEMENT_INVALID_STATE)
    assert err["error_id"] != ApiErrorId.ERR_RESIDENCY_CONFIRM_TOO_EARLY.value
    p = validate_success(api.get_placement(sc["placement"]["id"], ADMIN))
    assert p["residency_status"] == "PENDING_MOVE_IN"
    assert p["estimated_fee_cents"] == 492500
    assert p["final_fee_cents"] is None


def test_residency_confirmation_thirteen_days_after_move_in_too_early(api):
    """PRD §3.10: "an earlier attempt is rejected with
    `ERR_RESIDENCY_CONFIRM_TOO_EARLY`."

    Design: Corner/validations/residency_confirmation_thirteen_days_after_move_in_returns_too_early
    """
    sc = build_scenario(api, "moved_in")
    set_clock(api, "2026-07-03T09:00:00Z")  # exactly 13 days after 2026-06-20
    resp = api.confirm_residency(sc["placement"]["id"], sc["advisor_headers"])
    validate_error(resp, ApiErrorId.ERR_RESIDENCY_CONFIRM_TOO_EARLY)
    assert validate_success(api.get_placement(sc["placement"]["id"], ADMIN))["residency_status"] == "MOVED_IN"

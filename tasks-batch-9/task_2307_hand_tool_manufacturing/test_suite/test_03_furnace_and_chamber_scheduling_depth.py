"""Exclusive furnace occupancy with its ramp buffer, additive chamber coupon
capacity, and the pinned order of the campaign safety checks."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_lot,
    api_client,
    assert_specimen_ledger,
    complete_campaign,
    create_chamber,
    create_furnace,
    create_lot,
    create_sku,
    furnace_campaign_payload,
    read_campaign,
    read_lot,
    schedule_campaign,
    schedule_test_run,
    setup_lot_with_completed_campaign,
    make_test_run_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]

FIRST_WINDOW = ("2026-08-02T06:00:00Z", "2026-08-02T10:00:00Z")
FIRST_BUFFERED_END = "2026-08-02T10:45:00Z"
ONE_MINUTE_EARLY_WINDOW = ("2026-08-02T10:44:00Z", "2026-08-02T12:00:00Z")
EXACTLY_AT_BUFFER_WINDOW = ("2026-08-02T10:45:00Z", "2026-08-02T12:00:00Z")
SECOND_BUFFERED_END = "2026-08-02T12:45:00Z"

CHAMBER_RUN_ONE = ("2026-08-04T00:00:00Z", "2026-08-06T00:00:00Z")
CHAMBER_RUN_TWO = ("2026-08-05T00:00:00Z", "2026-08-07T00:00:00Z")
CHAMBER_OVERLAP_WINDOW = ("2026-08-05T12:00:00Z", "2026-08-08T00:00:00Z")
CHAMBER_ABUTTING_WINDOW = ("2026-08-08T00:00:00Z", "2026-08-10T00:00:00Z")

CRV_WRENCH = {
    "sku_code": "WR-17-CRV",
    "tool_family": "WRENCH",
    "channel": "BRANDED",
    "nominal_size_mm": 17,
    "alloy_grade": "CR_V",
    "list_price_cents": 2900,
    "warranty_tier": "LIFETIME",
}
S2_PLIER = {
    "sku_code": "PL-10-S2",
    "tool_family": "PLIER",
    "channel": "PRIVATE_LABEL",
    "nominal_size_mm": 10,
    "alloy_grade": "S2",
    "list_price_cents": 1800,
    "warranty_tier": "LIMITED_5Y",
}
ALLOY_CLASH_WINDOW = ("2026-08-02T10:20:00Z", "2026-08-02T12:00:00Z")


# ---------------------------------------------------------------------------
# The 45 minute ramp-and-cool-down buffer
# ---------------------------------------------------------------------------


def _furnace_with_one_campaign():
    sku = create_sku()
    furnace = create_furnace()
    lot = create_lot(sku["id"])
    campaign = schedule_campaign(
        lot["id"],
        furnace["id"],
        window_start=FIRST_WINDOW[0],
        window_end=FIRST_WINDOW[1],
        charge_kg=800,
    )
    return {"sku": sku, "furnace": furnace, "lot": lot, "campaign": campaign}


def test_a_campaign_carries_a_buffered_end_forty_five_minutes_past_its_window():
    """A campaign running to 10:00 keeps the furnace until 10:45.

    PRD §3.2: "A furnace has exclusive occupancy — capacity one — and each
    campaign's interval is extended by a trailing ramp-and-cool-down buffer of 45
    minutes, recorded on the row as `buffered_end`, which is simply `window_end`
    plus those 45 minutes and is the instant the furnace becomes bookable again."

    Design: Difficulty/resource_temporal_overlap/furnace_campaign_ramp_buffer_exclusive_window
    """
    ctx = _furnace_with_one_campaign()

    assert ctx["campaign"]["window_end"].startswith("2026-08-02T10:00")
    assert ctx["campaign"]["buffered_end"].startswith("2026-08-02T10:45")
    assert ctx["campaign"]["status"] == "SCHEDULED"


def test_a_campaign_starting_one_minute_inside_the_buffer_is_refused():
    """10:44 falls strictly before the 10:45 buffered end, so the furnace is
    still occupied.

    PRD §3.2: "A collision exists when the requested `window_start` falls
    strictly before an existing campaign's buffered end **and** that existing
    campaign's `window_start` falls strictly before the requested `window_end`
    plus 45 minutes; both comparisons are strict, so a campaign starting exactly
    at a prior campaign's `buffered_end` is accepted while one starting a single
    minute earlier is refused."

    Design: Difficulty/resource_temporal_overlap/furnace_campaign_ramp_buffer_exclusive_window
    """
    ctx = _furnace_with_one_campaign()

    validate_error(
        api_client.create_furnace_campaign(
            furnace_campaign_payload(
                ctx["lot"]["id"],
                ctx["furnace"]["id"],
                window_start=ONE_MINUTE_EARLY_WINDOW[0],
                window_end=ONE_MINUTE_EARLY_WINDOW[1],
                charge_kg=700,
            ),
            PP,
        ),
        ApiErrorId.ERR_FURNACE_WINDOW_CONFLICT,
        409,
    )

    _, meta = validate_paginated(
        api_client.list_furnace_campaigns(PP, params={"furnace_id": ctx["furnace"]["id"]})
    )
    assert meta["total_count"] == 1


def test_a_campaign_starting_exactly_at_the_buffered_end_is_accepted():
    """10:45 is the instant the furnace becomes bookable again, and the new
    campaign carries its own buffer forward to 12:45.

    PRD §3.2: "A collision exists when the requested `window_start` falls
    strictly before an existing campaign's buffered end **and** that existing
    campaign's `window_start` falls strictly before the requested `window_end`
    plus 45 minutes; both comparisons are strict, so a campaign starting exactly
    at a prior campaign's `buffered_end` is accepted while one starting a single
    minute earlier is refused."

    Design: Difficulty/resource_temporal_overlap/furnace_campaign_ramp_buffer_exclusive_window
    """
    ctx = _furnace_with_one_campaign()
    validate_error(
        api_client.create_furnace_campaign(
            furnace_campaign_payload(
                ctx["lot"]["id"],
                ctx["furnace"]["id"],
                window_start=ONE_MINUTE_EARLY_WINDOW[0],
                window_end=ONE_MINUTE_EARLY_WINDOW[1],
                charge_kg=700,
            ),
            PP,
        ),
        ApiErrorId.ERR_FURNACE_WINDOW_CONFLICT,
    )

    second = validate_success(
        api_client.create_furnace_campaign(
            furnace_campaign_payload(
                ctx["lot"]["id"],
                ctx["furnace"]["id"],
                window_start=EXACTLY_AT_BUFFER_WINDOW[0],
                window_end=EXACTLY_AT_BUFFER_WINDOW[1],
                charge_kg=700,
            ),
            PP,
        ),
        201,
    )

    assert second["status"] == "SCHEDULED"
    assert second["soak_minutes"] is None
    assert second["buffered_end"].startswith("2026-08-02T12:45")

    _, meta = validate_paginated(
        api_client.list_furnace_campaigns(PP, params={"furnace_id": ctx["furnace"]["id"]})
    )
    assert meta["total_count"] == 2


def test_a_completed_campaign_still_blocks_its_buffered_window():
    """Recording the soak does not free the basket, so the same one-minute-early
    booking is refused after completion exactly as before it.

    PRD §3.2: "Note that completion does **not** free the furnace: a `COMPLETED`
    campaign still occupies its buffered window and still blocks overlapping
    bookings, because the basket and fixtures remain in place until the lot moves
    on."

    Design: Difficulty/resource_temporal_overlap/furnace_campaign_ramp_buffer_exclusive_window
    """
    ctx = _furnace_with_one_campaign()
    completed = complete_campaign(ctx["campaign"]["id"], soak_minutes=120)
    assert completed["status"] == "COMPLETED"
    assert completed["buffered_end"].startswith("2026-08-02T10:45")

    validate_error(
        api_client.create_furnace_campaign(
            furnace_campaign_payload(
                ctx["lot"]["id"],
                ctx["furnace"]["id"],
                window_start=ONE_MINUTE_EARLY_WINDOW[0],
                window_end=ONE_MINUTE_EARLY_WINDOW[1],
                charge_kg=700,
            ),
            PP,
        ),
        ApiErrorId.ERR_FURNACE_WINDOW_CONFLICT,
        409,
    )


# ---------------------------------------------------------------------------
# Additive chamber coupon capacity
# ---------------------------------------------------------------------------


def _chamber_with_two_overlapping_runs():
    """A PLATED lot with 40 specimens and a 24 coupon cabinet already holding a
    ten-coupon and an eight-coupon exposure whose windows overlap."""
    ctx = setup_lot_with_completed_campaign(lot_overrides={"specimen_pool_total": 40})
    lot_id = ctx["lot"]["id"]
    for stage in ("HEAT_TREATED", "MACHINED", "PLATED"):
        advance_lot(lot_id, stage)
    chamber = create_chamber(coupon_capacity=24)
    ctx["chamber"] = chamber
    ctx["run_one"] = schedule_test_run(
        lot_id, "SALT_SPRAY", 10, CHAMBER_RUN_ONE, chamber_id=chamber["id"]
    )
    ctx["run_two"] = schedule_test_run(
        lot_id, "SALT_SPRAY", 8, CHAMBER_RUN_TWO, chamber_id=chamber["id"]
    )
    ctx["lot"] = read_lot(lot_id)
    return ctx


def _salt_spray_attempt(lot_id, chamber_id, specimen_count, window):
    return api_client.create_test_run(
        make_test_run_payload(
            lot_id,
            test_type="SALT_SPRAY",
            specimen_count=specimen_count,
            window_start=window[0],
            window_end=window[1],
            chamber_id=chamber_id,
        ),
        QE,
    )


def test_many_corrosion_runs_share_one_cabinet_while_the_coupons_fit():
    """Ten coupons and eight coupons coexist in a 24 coupon cabinet across
    overlapping windows.

    PRD §3.3: "Unlike a furnace, a chamber is **additive**: many runs may share
    it as long as the coupons inside it never exceed `coupon_capacity` at any
    instant, and there is no buffer of any kind."

    Design: Difficulty/resource_temporal_overlap/salt_spray_chamber_aggregate_coupon_capacity_overlap
    """
    ctx = _chamber_with_two_overlapping_runs()

    assert ctx["run_one"]["status"] == "SCHEDULED"
    assert ctx["run_two"]["status"] == "SCHEDULED"
    assert ctx["chamber"]["coupon_capacity"] == 24
    assert ctx["lot"]["specimens_committed"] == 18
    assert_specimen_ledger(ctx["lot"])


def test_a_peak_coupon_load_above_capacity_is_refused():
    """Seven more coupons on top of the eighteen already exposed would peak at 25
    inside a 24 coupon cabinet.

    PRD §3.3: "If the greatest of those loads is strictly greater than
    `coupon_capacity`, the request is refused with
    `ERR_CHAMBER_CAPACITY_EXCEEDED`; a peak load exactly equal to
    `coupon_capacity` is accepted."

    Design: Difficulty/resource_temporal_overlap/salt_spray_chamber_aggregate_coupon_capacity_overlap
    """
    ctx = _chamber_with_two_overlapping_runs()

    validate_error(
        _salt_spray_attempt(
            ctx["lot"]["id"], ctx["chamber"]["id"], 7, CHAMBER_OVERLAP_WINDOW
        ),
        ApiErrorId.ERR_CHAMBER_CAPACITY_EXCEEDED,
        409,
    )

    lot = read_lot(ctx["lot"]["id"])
    assert lot["specimens_committed"] == 18
    assert_specimen_ledger(lot)


def test_a_peak_coupon_load_exactly_at_capacity_is_accepted():
    """Six more coupons peak at exactly 24 in the same window the seven-coupon
    request was refused for.

    PRD §3.3: "Occupancy is probed at the requested `window_start` and at every
    occupying run's start instant that is later than the requested
    `window_start`; at each probe instant the load is the requested
    `specimen_count` plus the `specimen_count` of every occupying run whose own
    interval covers that instant, treating each interval as including its start
    and excluding its end."

    Design: Difficulty/resource_temporal_overlap/salt_spray_chamber_aggregate_coupon_capacity_overlap
    """
    ctx = _chamber_with_two_overlapping_runs()
    validate_error(
        _salt_spray_attempt(
            ctx["lot"]["id"], ctx["chamber"]["id"], 7, CHAMBER_OVERLAP_WINDOW
        ),
        ApiErrorId.ERR_CHAMBER_CAPACITY_EXCEEDED,
    )

    accepted = validate_success(
        _salt_spray_attempt(
            ctx["lot"]["id"], ctx["chamber"]["id"], 6, CHAMBER_OVERLAP_WINDOW
        ),
        201,
    )

    assert accepted["specimen_count"] == 6
    assert accepted["status"] == "SCHEDULED"


def test_a_corrosion_run_beginning_when_another_ends_never_conflicts():
    """An exposure starting at 08-08T00:00 abuts the run that ends there, so the
    cabinet is free for it and the ledger closes on 28 committed coupons.

    PRD §3.3: "a run beginning exactly when another ends never conflicts, and
    `VOID` runs never occupy anything."

    Design: Difficulty/resource_temporal_overlap/salt_spray_chamber_aggregate_coupon_capacity_overlap
    """
    ctx = _chamber_with_two_overlapping_runs()
    lot_id = ctx["lot"]["id"]
    chamber_id = ctx["chamber"]["id"]
    validate_success(_salt_spray_attempt(lot_id, chamber_id, 6, CHAMBER_OVERLAP_WINDOW), 201)

    abutting = validate_success(
        _salt_spray_attempt(lot_id, chamber_id, 4, CHAMBER_ABUTTING_WINDOW), 201
    )

    assert abutting["status"] == "SCHEDULED"

    lot = read_lot(lot_id)
    assert lot["specimens_committed"] == 28
    assert lot["specimens_available"] == 12
    assert_specimen_ledger(lot)

    _, meta = validate_paginated(
        api_client.list_test_runs(QE, params={"chamber_id": chamber_id})
    )
    assert meta["total_count"] == 4


# ---------------------------------------------------------------------------
# Alloy qualification outranks the window rule
# ---------------------------------------------------------------------------


def _cr_v_only_furnace_with_two_lots():
    """A furnace qualified for CR_V alone, already carrying a campaign, plus a
    second lot of S2 metal waiting for a slot that also collides."""
    crv_sku = create_sku(**CRV_WRENCH)
    s2_sku = create_sku(**S2_PLIER)
    furnace = create_furnace(
        furnace_code="FCE-CRV", max_charge_kg=900, alloy_grades_supported=["CR_V"]
    )
    crv_lot = create_lot(crv_sku["id"], lot_code="LOT-CRV-1", unit_count=400,
                         specimen_pool_total=20)
    s2_lot = create_lot(s2_sku["id"], lot_code="LOT-S2-1", unit_count=300,
                        specimen_pool_total=20)
    campaign = schedule_campaign(
        crv_lot["id"],
        furnace["id"],
        window_start=FIRST_WINDOW[0],
        window_end=FIRST_WINDOW[1],
        charge_kg=800,
    )
    return {
        "crv_sku": crv_sku,
        "s2_sku": s2_sku,
        "furnace": furnace,
        "crv_lot": crv_lot,
        "s2_lot": s2_lot,
        "campaign": campaign,
    }


def test_an_unsupported_alloy_is_reported_ahead_of_the_colliding_window():
    """The requested slot at 10:20 also collides with the 10:45 buffered end, but
    the qualification check is settled first.

    PRD §3.2: "**Qualification comes first**: the furnace must list the alloy
    grade of the lot's SKU among its `alloy_grades_supported`, and if it does
    not, the answer is `ERR_ALLOY_NOT_SUPPORTED` even when the requested window
    also collides and the basket is also overweight."

    Design: Difficulty/priority_pair_validation_conflict/campaign_alloy_safety_beats_window_temporal
    """
    ctx = _cr_v_only_furnace_with_two_lots()

    body = validate_error(
        api_client.create_furnace_campaign(
            furnace_campaign_payload(
                ctx["s2_lot"]["id"],
                ctx["furnace"]["id"],
                window_start=ALLOY_CLASH_WINDOW[0],
                window_end=ALLOY_CLASH_WINDOW[1],
                charge_kg=800,
            ),
            PP,
        ),
        ApiErrorId.ERR_ALLOY_NOT_SUPPORTED,
        422,
    )
    assert body["error_id"] != ApiErrorId.ERR_FURNACE_WINDOW_CONFLICT


def test_the_refused_campaign_persists_nothing_and_leaves_the_first_buffer_intact():
    """No row is written for the S2 lot, the CR_V campaign keeps its 10:45
    buffered end, and the S2 plier's own acceptance bar is untouched at 36.4 Nm.

    PRD §3.1: "Step three adds a size-tier term, computed as a per-millimetre
    adder multiplied by `nominal_size_mm`, where the adder is zero for a size of
    10 millimetres or less, 1.5 for a size greater than 10 and up to and
    including 19, and 3.0 for a size greater than 19."

    Design: Difficulty/priority_pair_validation_conflict/campaign_alloy_safety_beats_window_temporal
    """
    ctx = _cr_v_only_furnace_with_two_lots()
    validate_error(
        api_client.create_furnace_campaign(
            furnace_campaign_payload(
                ctx["s2_lot"]["id"],
                ctx["furnace"]["id"],
                window_start=ALLOY_CLASH_WINDOW[0],
                window_end=ALLOY_CLASH_WINDOW[1],
                charge_kg=800,
            ),
            PP,
        ),
        ApiErrorId.ERR_ALLOY_NOT_SUPPORTED,
    )

    _, meta = validate_paginated(
        api_client.list_furnace_campaigns(PP, params={"lot_id": ctx["s2_lot"]["id"]})
    )
    assert meta["total_count"] == 0

    assert read_campaign(ctx["campaign"]["id"])["buffered_end"].startswith(
        "2026-08-02T10:45"
    )
    assert ctx["s2_sku"]["proof_torque_required_nm"] == pytest.approx(36.4, abs=0.01)

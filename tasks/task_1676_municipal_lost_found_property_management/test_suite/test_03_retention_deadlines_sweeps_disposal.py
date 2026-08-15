"""Retention deadline arithmetic, the expiry sweep, and disposal (PRD §3.2, §3.7)."""
from test_helpers import (
    ApiErrorId,
    advance_clock_and_sweep,
    assert_instant_equals,
    create_item,
    get_item,
    run_retention_sweep,
    set_clock,
    setup_program_policy_location,
    setup_stored_item,
    validate_error,
    validate_success,
    make_property_custodian_headers,
)


def test_retention_deadline_transit_hour_precise(api, program_admin_headers):
    """PRD §3.2: "For a `TRANSIT` program the arithmetic is hour-precise: the
    deadline is `found_at` plus `retention_days` times 24 hours, preserving the
    time of day."

    Design: Difficulty/dual_variant_calc/retention_deadline_transit_vs_facility
    """
    ctx = setup_program_policy_location(program_type="TRANSIT", value_tier="MID",
                                        retention_days=30)
    item = create_item(ctx.program["id"], ctx.location["id"],
                       declared_value_cents=50000, description="black laptop",
                       found_at="2026-08-01T10:30:00Z")
    assert item["value_tier"] == "MID"
    # found 2026-08-01T10:30:00Z + 30 * 24h = 2026-08-31T10:30:00Z.
    assert_instant_equals(item["retention_deadline"], "2026-08-31T10:30:00Z")


def test_retention_deadline_facility_calendar_day(api, program_admin_headers):
    """PRD §3.2: "For a `FACILITY` program the arithmetic is calendar-based: the
    item is held for the remainder of the calendar day on which it was found
    plus `retention_days` full calendar days, and the deadline falls at
    00:00:00 UTC on the following morning".

    Design: Difficulty/dual_variant_calc/retention_deadline_transit_vs_facility
    """
    ctx = setup_program_policy_location(program_type="FACILITY", value_tier="MID",
                                        retention_days=30)
    item = create_item(ctx.program["id"], ctx.location["id"],
                       declared_value_cents=50000, description="black laptop",
                       found_at="2026-08-01T10:30:00Z", found_location="City Hall lobby")
    assert item["value_tier"] == "MID"
    # Held for the rest of 2026-08-01 plus 30 full calendar days; expiry at the
    # midnight boundary after 2026-08-31 -> 2026-09-01T00:00:00Z.
    assert_instant_equals(item["retention_deadline"], "2026-09-01T00:00:00Z")


def test_sweep_at_exact_deadline_transitions_item(api, program_admin_headers):
    """PRD §3.7: "a `ProgramAdmin` runs the retention sweep through the ops
    endpoint, which examines every item in `STORED` or `LISTED` whose
    `retention_deadline` has been reached by the current logical clock" and
    "where the method is `AUCTION` the item becomes `AUCTION_ELIGIBLE`".

    Design: Difficulty/boundary_precision_check/retention_deadline_exact_equality_sweep
    """
    ctx = setup_stored_item(declared_value_cents=5000, retention_days=10,
                            found_at="2026-08-01T09:00:00Z")
    # TRANSIT deadline: 2026-08-01T09:00:00Z + 10 * 24h = 2026-08-11T09:00:00Z.
    sweep = advance_clock_and_sweep("2026-08-11T09:00:00Z")
    assert sweep["transitioned_count"] == 1, (
        "the item whose deadline equals the clock exactly has been reached")
    assert ctx.item["id"] in sweep["transitioned_item_ids"]
    assert get_item(ctx.item["id"])["status"] == "AUCTION_ELIGIBLE"


def test_sweep_one_second_before_deadline_leaves_item(api, program_admin_headers):
    """PRD §3.7: "Items whose deadlines have not passed, and items in any other
    status, are untouched."

    Design: Difficulty/boundary_precision_check/retention_deadline_exact_equality_sweep
    """
    ctx = setup_stored_item(declared_value_cents=5000, retention_days=10,
                            found_at="2026-08-01T09:00:01Z")
    # Item deadline 2026-08-11T09:00:01Z is one second past the pinned clock.
    sweep = advance_clock_and_sweep("2026-08-11T09:00:00Z")
    assert sweep["transitioned_count"] == 0, (
        "a deadline one second in the future has not been reached")
    assert get_item(ctx.item["id"])["status"] == "STORED"


def test_sweep_respects_default_logical_clock(api, program_admin_headers):
    """PRD §2.5: "At startup, before any explicit adjustment, the logical clock
    reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock
    time thereafter."

    Design: Corner/cross_cutting_layers/scheduled_sweep_respects_default_clock
    """
    ctx = setup_stored_item(declared_value_cents=5000, retention_days=10,
                            found_at="2026-08-01T09:00:00Z")
    # Clock never set: still the startup default 2026-08-01T00:00:00Z, well
    # before the item's 2026-08-11T09:00:00Z deadline.
    sweep = run_retention_sweep()
    assert sweep["transitioned_count"] == 0, (
        "default clock is before the deadline, so nothing is swept")
    assert get_item(ctx.item["id"])["status"] == "STORED"


def test_dispose_method_mismatch_rejected(api, property_custodian_headers):
    """PRD §3.7: "The supplied method must equal the item's
    `pending_disposal_method` — a mismatch is rejected with
    `ERR_DISPOSAL_METHOD_MISMATCH` (HTTP 422), which prevents, for example,
    donating an item that was slated for destruction."

    Design: Corner/errors/err_disposal_method_mismatch_rejected
    """
    ctx = setup_stored_item(declared_value_cents=5000, retention_days=10,
                            disposal_method="DESTRUCTION")
    advance_clock_and_sweep("2026-08-11T09:00:00Z")
    pending = get_item(ctx.item["id"])
    assert pending["status"] == "DISPOSAL_PENDING"
    assert pending["pending_disposal_method"] == "DESTRUCTION"

    res = api.dispose_item(ctx.item["id"], "DONATION", property_custodian_headers)
    validate_error(res, ApiErrorId.ERR_DISPOSAL_METHOD_MISMATCH, expected_status=422)
    assert get_item(ctx.item["id"])["status"] == "DISPOSAL_PENDING", (
        "a mismatched disposal attempt leaves the item DISPOSAL_PENDING")

"""Hours-of-Service clock derivation and violation detection (PRD §3.4, §3.5, §3.9).

Covers difficulty rules dual_variant_calc, combinatorial_formula, boundary_precision_check
and corner-design calculations-section instances.
"""
from test_helpers import fixtures, constants
from test_helpers.test_users import make_driver_headers
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    factories,
)


# =====================================================================
# Difficulty / dual_variant_calc
# =====================================================================
def test_adverse_approval_dismisses_driving_11h_violation_under_extended_limit(api):
    """PRD §3.9: "On approval the claim moves PENDING → APPROVED and the clocks and
    violation scan are rerun for that driver-day under the extended-limit variant: only
    for intervals whose home-terminal day is the claimed day, the driving limit is raised
    from 660 to 780 minutes (13 hours) and the window limit is raised from 840 to 960
    minutes (16 hours)."
    PRD §3.9: "Any OPEN or ACKNOWLEDGED DRIVING_11H or WINDOW_14H violation on that day
    whose overage disappears under the extended limits is auto-transitioned to DISMISSED
    with its resolution_note set to "auto-dismissed: adverse conditions"."

    Design: Difficulty/dual_variant_calc/hos_clocks_standard_vs_adverse_driving_on_driver
    """
    setup = fixtures.setup_driving_11h_violation(
        clock="2026-06-01T20:00:00Z",
        driver_overrides={"home_terminal_tz_offset_minutes": 0, "cycle_rule": "SEVENTY_HOUR_8_DAY", "pc_authorized": False},
    )
    d_id = setup["driver_id"]
    violation = setup["violation"]
    assert violation["violation_type"] == "DRIVING_11H"
    assert violation["status"] == "OPEN"
    assert violation["overage_minutes"] == 1, f"standard limit 660: 661-660 = 1, got {violation['overage_minutes']}"

    claim = fixtures.file_adverse_claim(d_id, "2026-06-01", reason="WEATHER", narrative="Snow on I-80 reduced speed.")
    approved = fixtures.approve_adverse_claim(claim["id"], claim["version"])
    assert approved["status"] == "APPROVED"

    after = fixtures.get_violation(violation["id"])
    assert after["status"] == "DISMISSED", f"expected DISMISSED under 780-min limit, got {after['status']}"
    assert after["resolution_note"] == constants.NOTE_AUTO_DISMISSED_ADVERSE


def test_standard_variant_opens_driving_11h_at_661(api):
    """PRD §3.5: "a driving clock of exactly 660 minutes is fine and 661 violates."
    PRD §3.5: "A DRIVING_11H violation arises when the driving clock exceeds 660 minutes
    (11 hours)."

    Design: Difficulty/dual_variant_calc/hos_clocks_standard_vs_adverse_driving_on_driver
    """
    setup = fixtures.setup_driving_11h_violation()
    violation = setup["violation"]
    assert violation["violation_type"] == "DRIVING_11H"
    assert violation["status"] == "OPEN"
    assert violation["overage_minutes"] == 1


# =====================================================================
# Difficulty / dual_variant_calc — overage on violation vs cycle on driver
# =====================================================================
def test_driving_11h_overage_distinct_from_cycle_on_duty_minutes(api):
    """PRD §3.5: "an overage_minutes equal to the clock value after the triggering interval
    minus the applicable limit; a row is only opened when that overage is at least 1 minute."
    PRD §3.4: "A driver's cycle_on_duty_minutes is the sum of DRIVING-with-NONE, YARD_MOVE,
    and ON_DUTY_NOT_DRIVING minutes over the rolling cycle window".

    Design: Difficulty/dual_variant_calc/violation_overage_threshold_on_violation_vs_driver_cycle
    """
    setup = fixtures.setup_bound_driver()
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T06:00:00Z")  # 30 min on-duty
    stream.append("DRIVING", "2026-06-01T06:30:00Z")              # 661 min driving
    stream.append("OFF_DUTY", "2026-06-01T17:31:00Z")

    violation = fixtures.find_one_violation(d_id, violation_type="DRIVING_11H")
    assert violation["overage_minutes"] == 1

    driver = fixtures.get_driver(d_id)
    assert driver["cycle_on_duty_minutes"] == 691, (
        f"30 on-duty + 661 driving = 691, got {driver['cycle_on_duty_minutes']}"
    )


def test_cycle_on_duty_minutes_sums_on_duty_and_driving(api):
    """PRD §3.4: "A driver's cycle_on_duty_minutes is the sum of DRIVING-with-NONE,
    YARD_MOVE, and ON_DUTY_NOT_DRIVING minutes over the rolling cycle window".

    Design: Difficulty/dual_variant_calc/violation_overage_threshold_on_violation_vs_driver_cycle
    """
    setup = fixtures.setup_bound_driver()
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T06:00:00Z")
    stream.append("DRIVING", "2026-06-01T06:30:00Z")
    stream.append("OFF_DUTY", "2026-06-01T17:31:00Z")
    driver = fixtures.get_driver(d_id)
    assert driver["cycle_on_duty_minutes"] == 691


# =====================================================================
# Difficulty / combinatorial_formula — nonlinear classification
# =====================================================================
def test_nonlinear_classification_pc_and_yard_move_excluded_from_driving(api):
    """PRD §3.4: "A DRIVING interval with category NONE advances the driving clock, the
    14-hour window clock, and the cycle. An ON_DUTY_NOT_DRIVING interval with category NONE
    advances the window clock and the cycle but not the driving clock. A DRIVING interval
    annotated YARD_MOVE advances the window clock and the cycle but not the driving clock.
    An interval annotated PERSONAL_CONVEYANCE is excluded from the driving clock, the window
    clock, and the cycle alike."

    Design: Difficulty/combinatorial_formula/hos_clocks_three_input_nonlinear_classification
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z",
                                        driver_overrides={"pc_authorized": True})
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T06:00:00Z")  # 30 min window+cycle
    stream.append("DRIVING", "2026-06-01T06:30:00Z")              # 90 min driving+window+cycle
    stream.append("DRIVING", "2026-06-01T08:00:00Z",
                  special_driving_category="PERSONAL_CONVEYANCE", annotation="Drove to lodging.")  # 90 min excluded
    stream.append("DRIVING", "2026-06-01T09:30:00Z",
                  special_driving_category="YARD_MOVE", annotation="Yard repositioning.")  # 30 min window+cycle
    stream.append("OFF_DUTY", "2026-06-01T10:00:00Z")

    driver = fixtures.get_driver(d_id)
    # cycle = 30 (on-duty) + 90 (driving) + 30 (yard) = 150; PC excluded.
    assert driver["cycle_on_duty_minutes"] == 150, (
        f"on-duty 30 + driving 90 + yard 30 (PC 90 excluded) = 150, got {driver['cycle_on_duty_minutes']}"
    )


def test_nonlinear_classification_no_violation_under_limits(api):
    """PRD §3.5: "a driving clock of exactly 660 minutes is fine and 661 violates."
    PRD §3.5: "A WINDOW_14H violation arises when the window clock exceeds 840 minutes
    (14 hours)."

    Design: Difficulty/combinatorial_formula/hos_clocks_three_input_nonlinear_classification
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z",
                                        driver_overrides={"pc_authorized": True})
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T06:00:00Z")
    stream.append("DRIVING", "2026-06-01T06:30:00Z")
    stream.append("DRIVING", "2026-06-01T08:00:00Z",
                  special_driving_category="PERSONAL_CONVEYANCE", annotation="Drove to lodging.")
    stream.append("DRIVING", "2026-06-01T09:30:00Z",
                  special_driving_category="YARD_MOVE", annotation="Yard repositioning.")
    stream.append("OFF_DUTY", "2026-06-01T10:00:00Z")

    rows = fixtures.list_violations(driver_id=d_id)
    assert len(rows) == 0, f"driving 120 <= 660 and window 240 <= 840 -> no violations, got {rows}"


# =====================================================================
# Difficulty / combinatorial_formula — sum-of-floored rounding
# =====================================================================
def test_duration_minutes_floored_per_interval(api):
    """PRD §2.8: "The duration an event occupies is the whole number of minutes from that
    event's event_time to the next surviving event's event_time for the same driver".
    PRD §2.8: "Each interval's contribution is truncated downward to a whole minute first,
    and the truncated per-interval values are then summed — the totals are a sum of floored
    intervals, never a floor applied to a sum of fractional intervals."

    Design: Difficulty/combinatorial_formula/sum_of_floored_minute_rounding_order_pinned
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    e1 = stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T06:00:00Z")  # [06:00:00, 06:30:30) = 1830s
    e2 = stream.append("DRIVING", "2026-06-01T06:30:30Z")              # [06:30:30, 07:01:00) = 1830s
    stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T07:01:00Z")

    assert fixtures.get_event(e1["id"])["duration_minutes"] == 30, "1830s floors to 30 minutes"
    assert fixtures.get_event(e2["id"])["duration_minutes"] == 30, "1830s floors to 30 minutes"


def test_cycle_total_is_sum_of_floored_not_floor_of_sum(api):
    """PRD §2.8: "the totals are a sum of floored intervals, never a floor applied to a sum
    of fractional intervals."
    PRD §3.4: "All four clocks are kept in integer minutes, each interval truncated to whole
    minutes before summing."

    Design: Difficulty/combinatorial_formula/sum_of_floored_minute_rounding_order_pinned
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T06:00:00Z")  # 1830s -> 30
    stream.append("DRIVING", "2026-06-01T06:30:30Z")              # 1830s -> 30
    stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T07:01:00Z")
    driver = fixtures.get_driver(d_id)
    assert driver["cycle_on_duty_minutes"] == 60, (
        f"sum-of-floored 30+30 = 60 (not floor-of-sum 3660s = 61), got {driver['cycle_on_duty_minutes']}"
    )


# =====================================================================
# Difficulty / boundary_precision_check
# =====================================================================
def test_driving_clock_exactly_660_is_compliant(api):
    """PRD §3.5: "a driving clock of exactly 660 minutes is fine and 661 violates."

    Design: Difficulty/boundary_precision_check/driving_clock_exactly_660_is_compliant
    """
    setup = fixtures.setup_bound_driver()
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    drive = stream.append("DRIVING", "2026-06-01T06:30:00Z")
    stream.append("OFF_DUTY", "2026-06-01T17:30:00Z")  # exactly 660 minutes

    assert fixtures.get_event(drive["id"])["duration_minutes"] == 660
    rows = fixtures.list_violations(driver_id=d_id, violation_type="DRIVING_11H")
    assert len(rows) == 0, f"660 == limit is compliant under strict >, got {rows}"


def test_driving_clock_661_violates_just_past_boundary(api):
    """PRD §3.5: "a driving clock of exactly 660 minutes is fine and 661 violates."
    PRD §3.5: "A DRIVING_11H violation arises when the driving clock exceeds 660 minutes
    (11 hours)."

    Design: Difficulty/boundary_precision_check/driving_clock_exactly_660_is_compliant
    """
    setup = fixtures.setup_bound_driver()
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    drive = stream.append("DRIVING", "2026-06-01T06:30:00Z")
    stream.append("OFF_DUTY", "2026-06-01T17:31:00Z")  # 661 minutes -> just past boundary

    assert fixtures.get_event(drive["id"])["duration_minutes"] == 661
    violation = fixtures.find_one_violation(d_id, violation_type="DRIVING_11H")
    assert violation["overage_minutes"] == 1


def test_empty_pc_segment_list_for_driver_with_no_pc(api):
    """PRD §3.7: "Segments may be listed and filtered by driver_id or by event_id."
    PRD §2.3: "the meta object on a list response carries the four pagination fields limit,
    offset, total_count, and has_more, where total_count is the size of the full filtered set
    and has_more indicates whether records remain beyond the returned page."

    Design: Difficulty/boundary_precision_check/empty_pc_segment_list_for_driver_with_no_pc
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    stream.append("DRIVING", "2026-06-01T06:30:00Z")

    resp = api.list_pc_segments(fixtures.ADMIN, params={"driver_id": d_id})
    data, meta = validate_paginated(resp)
    assert len(data) == 0
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_empty_pc_segment_list_unfiltered_when_no_pc_used(api):
    """PRD §3.7: "Segments may be listed and filtered by driver_id or by event_id."
    PRD §3.7: "Once the event following a PERSONAL_CONVEYANCE-annotated driving-or-off-duty
    event arrives and closes the PC interval — fixing that event's duration_minutes — the
    system creates exactly one Personal Conveyance segment for the prior PC event."

    Design: Difficulty/boundary_precision_check/empty_pc_segment_list_for_driver_with_no_pc
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T12:00:00Z")
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T06:00:00Z")
    stream.append("DRIVING", "2026-06-01T06:30:00Z")

    # No PC events at all -> no segments anywhere for this driver.
    data, meta = validate_paginated(api.list_pc_segments(fixtures.ADMIN, params={"driver_id": d_id}))
    assert meta["total_count"] == 0
    assert data == []


# =====================================================================
# Corner / calculations
# =====================================================================
def test_window_14h_exactly_840_is_compliant(api):
    """PRD §3.5: "A WINDOW_14H violation arises when the window clock exceeds 840 minutes
    (14 hours)."
    PRD §3.5: "Equality with a limit is compliant: the test is a strict exceedance".

    Design: Corner/calculations/window_14h_exactly_840_is_compliant
    """
    setup = fixtures.setup_bound_driver()
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    stream.append("DRIVING", "2026-06-01T05:00:00Z")              # 300 driving
    stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T10:00:00Z")
    stream.append("OFF_DUTY", "2026-06-01T19:00:00Z")            # window elapsed 840

    rows = fixtures.list_violations(driver_id=d_id, violation_type="WINDOW_14H")
    assert len(rows) == 0, f"840 == limit is compliant, got {rows}"


def test_window_14h_violation_at_841(api):
    """PRD §3.5: "A WINDOW_14H violation arises when the window clock exceeds 840 minutes
    (14 hours)."
    PRD §3.5: "an overage_minutes equal to the clock value after the triggering interval
    minus the applicable limit".

    Design: Corner/calculations/window_14h_violation_at_841
    """
    setup = fixtures.setup_bound_driver()
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    stream.append("DRIVING", "2026-06-01T05:00:00Z")
    stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T10:00:00Z")
    stream.append("OFF_DUTY", "2026-06-01T19:01:00Z")  # window elapsed 841

    violation = fixtures.find_one_violation(d_id, violation_type="WINDOW_14H")
    assert violation["overage_minutes"] == 1
    assert violation["status"] == "OPEN"


def test_break_30min_violation_at_481_driving(api):
    """PRD §3.5: "A BREAK_30MIN violation arises when the break clock exceeds 480 minutes
    (8 hours of driving) without a qualifying non-driving interval of at least 30 minutes
    having been taken."

    Design: Corner/calculations/break_30min_violation_at_481_driving
    """
    setup = fixtures.setup_bound_driver(clock="2026-06-01T18:00:00Z")
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    stream.append("DRIVING", "2026-06-01T06:00:00Z")
    stream.append("OFF_DUTY", "2026-06-01T14:01:00Z")  # 481 consecutive driving minutes

    violation = fixtures.find_one_violation(d_id, violation_type="BREAK_30MIN")
    assert violation["overage_minutes"] == 1
    assert violation["status"] == "OPEN"


def test_cycle_70h_violation_at_4201(api):
    """PRD §3.5: "A CYCLE_70H violation arises when cycle_on_duty_minutes exceeds 4200
    minutes (70 hours) for a SEVENTY_HOUR_8_DAY driver".
    PRD §3.4: "all events whose home-terminal calendar day falls within the last 8 days for
    a SEVENTY_HOUR_8_DAY driver ... counting inclusively up to and including the home-terminal
    day of the latest event."

    Design: Corner/calculations/cycle_70h_violation_at_4201
    """
    setup = fixtures.setup_bound_driver(driver_overrides={"cycle_rule": "SEVENTY_HOUR_8_DAY"})
    d_id = setup["driver_id"]
    stream = fixtures.make_stream(setup)
    # Five days, each 840 on-duty (00:00->14:00) + 600 off-duty reset (14:00->24:00).
    for day in ("2026-05-28", "2026-05-29", "2026-05-30", "2026-05-31", "2026-06-01"):
        stream.append("ON_DUTY_NOT_DRIVING", f"{day}T00:00:00Z")
        stream.append("OFF_DUTY", f"{day}T14:00:00Z")
    at_limit = fixtures.get_driver(d_id)
    assert at_limit["cycle_on_duty_minutes"] == 4200, (
        f"5 x 840 = 4200 (== limit, compliant), got {at_limit['cycle_on_duty_minutes']}"
    )
    assert len(fixtures.list_violations(driver_id=d_id, violation_type="CYCLE_70H")) == 0

    # One more minute pushes cycle to 4201.
    stream.append("ON_DUTY_NOT_DRIVING", "2026-06-01T15:00:00Z")
    stream.append("OFF_DUTY", "2026-06-01T15:01:00Z")
    violation = fixtures.find_one_violation(d_id, violation_type="CYCLE_70H")
    assert violation["overage_minutes"] == 1

"""Run-of-show timeline overlap geometry and day-of staffing shift buffers /
labor-cost rounding.

Covers queue A resource_temporal_overlap (timeline half-open zones, staff buffered
shifts) plus queue B interval / labor-cost corners.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    PLANNER,
    create_event,
    create_timeline_block,
    create_staff_member,
    create_staff_assignment,
)


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap: timeline half-open zone geometry
# ---------------------------------------------------------------------------
def test_overlapping_zone_block_rejected(api):
    """PRD §3.6: "Under the half-open convention, a proposed block conflicts with an
    existing block in that zone when the proposed block's start is earlier than the
    existing block's end and the existing block's start is earlier than the proposed
    block's end; such a conflict is rejected with `ERR_TIMELINE_OVERLAP`."

    [660,780) overlaps the existing [600,720) in the same zone.

    Design: Difficulty/resource_temporal_overlap/timeline_zone_halfopen_overlap
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=4_000_000)
    create_timeline_block(event["id"], 600, 720, zone="RECEPTION_HALL", block_type="RECEPTION",
                          label="Dinner service")
    validate_error(
        api.create_timeline_block(
            {
                "event_id": event["id"], "label": "Toasts", "zone": "RECEPTION_HALL",
                "block_type": "RECEPTION", "start_offset_min": 660, "end_offset_min": 780,
            },
            PLANNER,
        ),
        ApiErrorId.ERR_TIMELINE_OVERLAP.value,
    )


def test_adjacent_zone_block_allowed(api):
    """PRD §3.6: "Blocks that merely touch at an endpoint — where the proposed block's
    end equals an existing block's start, or an existing block's end equals the proposed
    block's start — do not overlap and are allowed."

    [720,780) starts exactly where [600,720) ends, so it is not a conflict.

    Design: Difficulty/resource_temporal_overlap/timeline_zone_halfopen_overlap
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=4_000_000)
    create_timeline_block(event["id"], 600, 720, zone="RECEPTION_HALL", block_type="RECEPTION",
                          label="Dinner service")
    data = validate_success(
        api.create_timeline_block(
            {
                "event_id": event["id"], "label": "Teardown", "zone": "RECEPTION_HALL",
                "block_type": "TEARDOWN", "start_offset_min": 720, "end_offset_min": 780,
            },
            PLANNER,
        ),
        201,
    )
    assert data["start_offset_min"] == 720 and data["end_offset_min"] == 780


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap: staff shift 30-minute buffer
# ---------------------------------------------------------------------------
def test_staff_shift_within_buffer_rejected(api):
    """PRD §3.7: "A proposed shift conflicts with another shift of the same staff member
    unless the two are separated by a gap of at least 30 minutes — that is, unless the
    earlier shift's end plus 30 minutes is less than or equal to the later shift's start.
    A gap of exactly 30 minutes is permitted; any smaller gap, or an actual overlap, is a
    conflict rejected with `ERR_STAFF_DOUBLE_BOOKED`."

    A [740,800] shift leaves only a 20-minute gap after [600,720] and is rejected.

    Design: Difficulty/resource_temporal_overlap/staff_shift_buffer_overlap
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=4_000_000)
    staff = create_staff_member(event["id"], hourly_rate_cents=5_000, role_title="SERVER")
    create_staff_assignment(event["id"], staff["id"], 600, 720)
    validate_error(
        api.create_staff_assignment(
            {
                "event_id": event["id"], "staff_member_id": staff["id"],
                "shift_start_offset_min": 740, "shift_end_offset_min": 800,
            },
            PLANNER,
        ),
        ApiErrorId.ERR_STAFF_DOUBLE_BOOKED.value,
    )


def test_staff_shift_exact_buffer_allowed(api):
    """PRD §3.7: "A proposed shift conflicts with another shift of the same staff member
    unless the two are separated by a gap of at least 30 minutes — that is, unless the
    earlier shift's end plus 30 minutes is less than or equal to the later shift's start.
    A gap of exactly 30 minutes is permitted; any smaller gap, or an actual overlap, is a
    conflict rejected with `ERR_STAFF_DOUBLE_BOOKED`."

    A [750,810] shift leaves exactly a 30-minute gap and is allowed; its labor cost is
    5000 * 60 / 60 = 5000.

    Design: Difficulty/resource_temporal_overlap/staff_shift_buffer_overlap
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=4_000_000)
    staff = create_staff_member(event["id"], hourly_rate_cents=5_000, role_title="SERVER")
    create_staff_assignment(event["id"], staff["id"], 600, 720)
    data = validate_success(
        api.create_staff_assignment(
            {
                "event_id": event["id"], "staff_member_id": staff["id"],
                "shift_start_offset_min": 750, "shift_end_offset_min": 810,
            },
            PLANNER,
        ),
        201,
    )
    assert data["labor_cost_cents"] == 5_000


# ---------------------------------------------------------------------------
# Queue B — timeline interval + staff labor-cost corners
# ---------------------------------------------------------------------------
def test_timeline_invalid_interval_rejected(api):
    """PRD §3.6: "A block's interval is treated as half-open — it includes its start
    minute and excludes its end minute — and must be well-formed: `end_offset_min` must
    be strictly greater than `start_offset_min`, otherwise the block is rejected with
    `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/timeline_invalid_interval_returns_422
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=3_000_000)
    validate_error(
        api.create_timeline_block(
            {
                "event_id": event["id"], "label": "Bad", "zone": "CEREMONY_SPACE",
                "block_type": "CEREMONY", "start_offset_min": 700, "end_offset_min": 700,
            },
            PLANNER,
        ),
        ApiErrorId.ERR_INVALID_INTERVAL.value,
    )


def test_staff_labor_cost_fractional_rounding(api):
    """PRD §3.7: "On creation the assignment's `labor_cost_cents` is computed: the shift
    length in minutes is `shift_end_offset_min` minus `shift_start_offset_min`, and the
    labor cost is the staff member's `hourly_rate_cents` multiplied by that number of
    minutes, divided by 60, rounded half up to whole cents."

    round_half_up(3333 * 50 / 60) = round_half_up(2777.5) = 2778.

    Design: Corner/calculations/staff_labor_cost_fractional_rounding
    """
    event = create_event(package_type="PARTIAL", total_budget_cents=3_000_000)
    staff = create_staff_member(event["id"], hourly_rate_cents=3_333, role_title="BARTENDER")
    data = validate_success(
        api.create_staff_assignment(
            {
                "event_id": event["id"], "staff_member_id": staff["id"],
                "shift_start_offset_min": 600, "shift_end_offset_min": 650,
            },
            PLANNER,
        ),
        201,
    )
    assert data["labor_cost_cents"] == 2_778

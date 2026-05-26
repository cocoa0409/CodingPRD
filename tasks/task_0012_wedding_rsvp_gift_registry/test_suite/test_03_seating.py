"""Seating: manual SeatingAssignments, table-full / already-seated rejections,
auto-seat dry-run vs commit, kids-spill rule, empty-attendee plan."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_guest_payload,
    create_meal_option_payload,
    create_table_payload,
    create_seating_assignment_payload,
    make_couple_headers,
    set_clock,
    bootstrap_wedding_in_rsvp_open,
)


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / dual_variant_calc / seating_chart_dry_run_vs_commit
# ─────────────────────────────────────────────────────────────────────────────

def test_seating_chart_dry_run_vs_commit(api):
    """PRD §3.3: "The dry-run variant — a read-style call — returns the plan
    and the unseatable list without persisting anything and without touching
    `seating_dirty`."
    PRD §3.3: "the committing variant — a write-style call — requires the
    wedding's `status` to be either `RSVP_CLOSED` or `SEATED` ... it
    atomically deletes every existing `SeatingAssignment` for the wedding
    and recreates rows from the freshly computed plan; on commit, the
    wedding's `version` advances by 1 and `seating_dirty` is left set to
    true so the couple still has to explicitly finalize."
    PRD §3.3: "The attendee list is the concatenation of all `Guest` rows of
    this wedding whose `rsvp_status` is `ATTENDING` ... sorted by
    `created_at` ascending as the primary key and `full_name` ascending as
    the disciplined tie-break".

    Design: Difficulty/dual_variant_calc/seating_chart_dry_run_vs_commit
    """
    set_clock("2027-01-10T00:00:00Z")
    wedding, _meal_unused = bootstrap_wedding_in_rsvp_open(
        couple_user_id="couple_w2",
        clock_iso="2027-01-10T00:00:00Z",
        title="W2 Wedding",
        ceremony_at="2027-06-15T18:00:00Z",
        rsvp_deadline_at="2027-05-30T23:59:59Z",
    )
    headers = make_couple_headers("couple_w2")
    # Override: the design uses "VEG" rather than ADULT — recreate.
    meal_veg = validate_success(api.create_meal_option(
        wedding["id"],
        create_meal_option_payload(code="VEG2", label="Vegetarian", max_servings=100),
        headers,
    ), expected_status=201)
    t1 = validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=1, capacity=1),
        headers,
    ), expected_status=201)
    t2 = validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=2, capacity=2),
        headers,
    ), expected_status=201)
    g_anna = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="Anna", email="anna@example.com"),
        headers,
    ), expected_status=201)
    g_ben = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="Ben", email="ben@example.com"),
        headers,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        g_anna["id"], {"attending": True, "meal_option_id": meal_veg["id"]},
        headers,
    ), expected_status=200)
    validate_success(api.guest_rsvp(
        g_ben["id"], {"attending": True, "meal_option_id": meal_veg["id"]},
        headers,
    ), expected_status=200)
    closed = validate_success(api.close_rsvp(wedding["id"], headers), expected_status=200)

    # Dry-run: no mutation. PRD §3.3: "returns the plan and the unseatable list
    # without persisting anything and without touching `seating_dirty`."
    validate_success(api.auto_seat_dry_run(wedding["id"], headers), expected_status=200)
    after_dry = validate_success(api.get_wedding(wedding["id"], headers), expected_status=200)
    assert after_dry["seating_dirty"] == closed["seating_dirty"], (
        "dry-run must not mutate seating_dirty"
    )
    assert after_dry["version"] == closed["version"], "dry-run must not bump version"

    # Commit: persists rows, advances version, sets seating_dirty=true.
    validate_success(api.auto_seat_commit(wedding["id"], headers), expected_status=200)
    after_commit = validate_success(api.get_wedding(wedding["id"], headers), expected_status=200)
    assert after_commit["seating_dirty"] is True
    assert after_commit["version"] == closed["version"] + 1

    rows_data = validate_success(
        api.list_seating_assignments(headers, params={"wedding_id": wedding["id"]}),
        expected_status=200,
    )
    if isinstance(rows_data, dict):
        rows_data = rows_data.get("items") or rows_data.get("data") or []
    assert len(rows_data) == 2
    by_assignee = {row["assignee_id"]: row for row in rows_data}
    # Anna sorts before Ben (full_name ASC tie-break given identical or near
    # created_at), and table_number 1 has capacity 1 — Anna fills it; Ben goes
    # to table 2.
    assert by_assignee[g_anna["id"]]["table_id"] == t1["id"]
    assert by_assignee[g_ben["id"]]["table_id"] == t2["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / combinatorial_formula / seating_chart_three_input_nonlinear_kids_spill
# ─────────────────────────────────────────────────────────────────────────────

def test_seating_chart_three_input_nonlinear_kids_spill(api):
    """PRD §3.3: "if the table has `kids_only=false`, the attendee's
    `is_child` must be false unless that attendee's `is_child` is true and
    every `kids_only=true` table in this wedding is already full, in which
    case the child is permitted to overflow into the non-kids-only table."

    Design: Difficulty/combinatorial_formula/seating_chart_three_input_nonlinear_kids_spill
    """
    set_clock("2027-03-01T00:00:00Z")
    wedding, _meal_unused = bootstrap_wedding_in_rsvp_open(
        couple_user_id="couple_w4",
        clock_iso="2027-03-01T00:00:00Z",
        title="W4 Wedding",
        ceremony_at="2027-08-01T18:00:00Z",
        rsvp_deadline_at="2027-07-15T23:59:59Z",
    )
    headers = make_couple_headers("couple_w4")
    meal_kids = validate_success(api.create_meal_option(
        wedding["id"],
        create_meal_option_payload(code="KIDS", label="Kids pasta", max_servings=50, is_kids=True),
        headers,
    ), expected_status=201)
    t1 = validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=1, capacity=1, kids_only=True),
        headers,
    ), expected_status=201)
    t2 = validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=2, capacity=4, kids_only=False),
        headers,
    ), expected_status=201)
    ck1 = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="AAA", email="aaa@example.com", is_child=True),
        headers,
    ), expected_status=201)
    ck2 = validate_success(api.create_guest(
        wedding["id"],
        create_guest_payload(full_name="BBB", email="bbb@example.com", is_child=True),
        headers,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        ck1["id"], {"attending": True, "meal_option_id": meal_kids["id"]}, headers,
    ), expected_status=200)
    validate_success(api.guest_rsvp(
        ck2["id"], {"attending": True, "meal_option_id": meal_kids["id"]}, headers,
    ), expected_status=200)
    validate_success(api.close_rsvp(wedding["id"], headers), expected_status=200)

    validate_success(api.auto_seat_commit(wedding["id"], headers), expected_status=200)
    rows = validate_success(
        api.list_seating_assignments(headers, params={"wedding_id": wedding["id"]}),
        expected_status=200,
    )
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("data") or []
    assert len(rows) == 2
    by_assignee = {row["assignee_id"]: row for row in rows}
    assert by_assignee[ck1["id"]]["table_id"] == t1["id"], "CK1 fills the only kids_only table"
    assert by_assignee[ck2["id"]]["table_id"] == t2["id"], "CK2 spills into adult table"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / boundary_precision_check / empty_attendee_seating_chart_empty_set
# ─────────────────────────────────────────────────────────────────────────────

def test_empty_attendee_seating_chart_empty_set(api):
    """PRD §3.3: "The output is an object with two arrays: `plan`, whose
    elements carry `assignee_type`, `assignee_id`, `table_id`, and
    `table_number`; and `unseatable`, whose elements carry `assignee_type`,
    `assignee_id`, and a reason."
    PRD §3.3: "The algorithm walks the attendee list in order and, for each
    attendee, scans the table list in order to find the first table where
    three conditions all hold".

    Design: Difficulty/boundary_precision_check/empty_attendee_seating_chart_empty_set
    """
    set_clock("2027-11-01T00:00:00Z")
    wedding, _meal_unused = bootstrap_wedding_in_rsvp_open(
        couple_user_id="couple_w12",
        clock_iso="2027-11-01T00:00:00Z",
        title="W12 Wedding",
        ceremony_at="2028-04-01T18:00:00Z",
        rsvp_deadline_at="2028-03-15T23:59:59Z",
    )
    headers = make_couple_headers("couple_w12")
    validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=1, capacity=4),
        headers,
    ), expected_status=201)
    validate_success(api.close_rsvp(wedding["id"], headers), expected_status=200)

    result = validate_success(api.auto_seat_commit(wedding["id"], headers), expected_status=200)
    assert result["plan"] == [], f"plan must be empty, got {result['plan']!r}"
    assert result["unseatable"] == [], f"unseatable must be empty, got {result['unseatable']!r}"

    rows = validate_success(
        api.list_seating_assignments(headers, params={"wedding_id": wedding["id"]}),
        expected_status=200,
    )
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("data") or []
    assert rows == []


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / resource_temporal_overlap / table_aggregate_capacity_overflow
# ─────────────────────────────────────────────────────────────────────────────

def test_table_aggregate_capacity_overflow(api):
    """PRD §3.3: "Second, the table-capacity ceiling: an assignment that
    would push the count of existing assignments on the target `Table` above
    its `capacity` is rejected with `ERR_TABLE_FULL` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/table_aggregate_capacity_overflow
    """
    set_clock("2028-02-01T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(
        couple_user_id="couple_w15",
        clock_iso="2028-02-01T00:00:00Z",
        title="W15 Wedding",
        ceremony_at="2028-07-01T18:00:00Z",
        rsvp_deadline_at="2028-06-15T23:59:59Z",
    )
    headers = make_couple_headers("couple_w15")
    table = validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=1, capacity=1),
        headers,
    ), expected_status=201)
    g_in = validate_success(api.create_guest(
        wedding["id"], create_guest_payload(full_name="GIn", email="gin@example.com"),
        headers,
    ), expected_status=201)
    g_out = validate_success(api.create_guest(
        wedding["id"], create_guest_payload(full_name="GOut", email="gout@example.com"),
        headers,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        g_in["id"], {"attending": True, "meal_option_id": meal["id"]}, headers,
    ), expected_status=200)
    validate_success(api.guest_rsvp(
        g_out["id"], {"attending": True, "meal_option_id": meal["id"]}, headers,
    ), expected_status=200)
    validate_success(api.close_rsvp(wedding["id"], headers), expected_status=200)
    validate_success(api.create_seating_assignment(
        create_seating_assignment_payload(
            wedding["id"], table["id"], "GUEST", g_in["id"],
        ),
        headers,
    ), expected_status=201)

    res = api.create_seating_assignment(
        create_seating_assignment_payload(
            wedding["id"], table["id"], "GUEST", g_out["id"],
        ),
        headers,
    )
    validate_error(res, ApiErrorId.ERR_TABLE_FULL, expected_status=422)

    rows = validate_success(
        api.list_seating_assignments(headers, params={"wedding_id": wedding["id"]}),
        expected_status=200,
    )
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("data") or []
    assert len(rows) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty / resource_temporal_overlap / assignee_point_uniqueness_collision
# ─────────────────────────────────────────────────────────────────────────────

def test_assignee_point_uniqueness_collision(api):
    """PRD §3.3: "Third, the per-attendee uniqueness check: the triple of
    `wedding_id`, `assignee_type`, and `assignee_id` is enforced as unique
    across `SeatingAssignment` rows — an attempt to seat a guest already
    seated is rejected with `ERR_ALREADY_SEATED` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/assignee_point_uniqueness_collision
    """
    set_clock("2028-03-01T00:00:00Z")
    wedding, meal = bootstrap_wedding_in_rsvp_open(
        couple_user_id="couple_w16",
        clock_iso="2028-03-01T00:00:00Z",
        title="W16 Wedding",
        ceremony_at="2028-08-01T18:00:00Z",
        rsvp_deadline_at="2028-07-15T23:59:59Z",
    )
    headers = make_couple_headers("couple_w16")
    t_a = validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=1, capacity=4),
        headers,
    ), expected_status=201)
    t_b = validate_success(api.create_table(
        wedding["id"], create_table_payload(table_number=2, capacity=4),
        headers,
    ), expected_status=201)
    g_dup = validate_success(api.create_guest(
        wedding["id"], create_guest_payload(full_name="Dup", email="dup@example.com"),
        headers,
    ), expected_status=201)
    validate_success(api.guest_rsvp(
        g_dup["id"], {"attending": True, "meal_option_id": meal["id"]}, headers,
    ), expected_status=200)
    validate_success(api.close_rsvp(wedding["id"], headers), expected_status=200)
    validate_success(api.create_seating_assignment(
        create_seating_assignment_payload(
            wedding["id"], t_a["id"], "GUEST", g_dup["id"],
        ),
        headers,
    ), expected_status=201)

    res = api.create_seating_assignment(
        create_seating_assignment_payload(
            wedding["id"], t_b["id"], "GUEST", g_dup["id"],
        ),
        headers,
    )
    validate_error(res, ApiErrorId.ERR_ALREADY_SEATED, expected_status=422)

    rows = validate_success(
        api.list_seating_assignments(headers, params={"wedding_id": wedding["id"]}),
        expected_status=200,
    )
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("data") or []
    assert len(rows) == 1, "The original t_a assignment must remain; t_b never received one."

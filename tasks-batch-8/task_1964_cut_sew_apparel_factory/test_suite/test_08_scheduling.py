"""Line assignments and temporal scheduling rules (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_draft_tech_pack,
    create_line_assignment,
    create_line_assignment_payload,
    create_operator,
    create_production_order,
    create_sewing_line,
    create_style,
    add_operation_spec,
    validate_error,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
SUPER = TEST_USERS["line_supervisor_headers"]
ANY = TEST_USERS["any_headers"]


def _line_scheduling_context(line_stations=2, style_code="ST-OV1"):
    """Style + DRAFT pack + op + order + line + no assignments yet."""
    style = create_style(style_code=style_code)
    pack = create_draft_tech_pack(style["id"], MERCH)
    op = add_operation_spec(pack["id"], MERCH)
    order = create_production_order(
        style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 10}],
    )
    line = create_sewing_line(PLANNER, station_count=line_stations)
    return style, pack, op, order, line


class TestLineStationAggregateCapacity:
    def test_line_station_aggregate_capacity_overlap(self):
        """PRD §3.6: "on the same line and `shift_date`, the number of
        assignments whose intervals cover any common point must never exceed
        the line's `station_count`, with pure adjacency — one assignment
        ending exactly when another starts — not counting as overlap; a
        breach is `ERR_LINE_STATION_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/line_station_aggregate_capacity_overlap
        """
        _style, _pack, op, order, line = _line_scheduling_context(line_stations=2)
        o1 = create_operator(SUPER, employee_no="E1", full_name="A1")
        o2 = create_operator(SUPER, employee_no="E2", full_name="A2")
        o3 = create_operator(SUPER, employee_no="E3", full_name="A3")
        a1 = create_line_assignment(
            line["id"], order["id"], op["id"], o1["id"], SUPER,
            shift_date="2026-08-03", start_minute=480, end_minute=580,
        )
        a2 = create_line_assignment(
            line["id"], order["id"], op["id"], o2["id"], SUPER,
            shift_date="2026-08-03", start_minute=500, end_minute=600,
        )
        # Third overlapping assignment: concurrency would reach 3 > 2.
        resp = api_client.create_line_assignment(
            create_line_assignment_payload(
                sewing_line_id=line["id"], production_order_id=order["id"],
                operation_spec_id=op["id"], operator_id=o3["id"],
                shift_date="2026-08-03", start_minute=520, end_minute=620,
            ),
            SUPER,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_STATION_CAPACITY_EXCEEDED)
        _ = (a1, a2)

    def test_pure_adjacency_does_not_count_as_overlap(self):
        """PRD §3.6: "with pure adjacency — one assignment ending exactly when
        another starts — not counting as overlap".

        Design: Difficulty/resource_temporal_overlap/line_station_aggregate_capacity_overlap
        """
        _style, _pack, op, order, line = _line_scheduling_context(line_stations=2)
        o1 = create_operator(SUPER, employee_no="E1", full_name="A1")
        o2 = create_operator(SUPER, employee_no="E2", full_name="A2")
        o3 = create_operator(SUPER, employee_no="E3", full_name="A3")
        create_line_assignment(
            line["id"], order["id"], op["id"], o1["id"], SUPER,
            shift_date="2026-08-03", start_minute=480, end_minute=580,
        )
        create_line_assignment(
            line["id"], order["id"], op["id"], o2["id"], SUPER,
            shift_date="2026-08-03", start_minute=500, end_minute=600,
        )
        # Adjacent to a2's end (600): half-open intervals never overlap there.
        a4 = create_line_assignment(
            line["id"], order["id"], op["id"], o3["id"], SUPER,
            shift_date="2026-08-03", start_minute=600, end_minute=700,
        )
        assert a4["id"]


class TestOperatorBufferedChangeover:
    def test_operator_buffered_changeover_overlap_adjacency_rejected(self):
        """PRD §3.6: "for the same operator and `shift_date`, a new assignment
        must start at least fifteen minutes after every existing assignment's
        end or end at least fifteen minutes before every existing assignment's
        start — pure adjacency is rejected because the fifteen-minute
        changeover buffer is mandatory — and a violation is
        `ERR_OPERATOR_SCHEDULE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/operator_buffered_changeover_overlap
        """
        _style, _pack, op, order, line = _line_scheduling_context(
            line_stations=5, style_code="ST-OV2",
        )
        o9 = create_operator(SUPER, employee_no="E9", full_name="A9")
        create_line_assignment(
            line["id"], order["id"], op["id"], o9["id"], SUPER,
            shift_date="2026-08-03", start_minute=480, end_minute=580,
        )
        # Adjacent: 580 == existing end. Buffer makes adjacency a violation.
        resp = api_client.create_line_assignment(
            create_line_assignment_payload(
                sewing_line_id=line["id"], production_order_id=order["id"],
                operation_spec_id=op["id"], operator_id=o9["id"],
                shift_date="2026-08-03", start_minute=580, end_minute=600,
            ),
            SUPER,
        )
        validate_error(resp, ApiErrorId.ERR_OPERATOR_SCHEDULE_OVERLAP)

    def test_operator_buffered_changeover_exact_buffer_accepted(self):
        """PRD §3.6: "a new assignment must start at least fifteen minutes
        after every existing assignment's end".

        Design: Difficulty/resource_temporal_overlap/operator_buffered_changeover_overlap
        """
        _style, _pack, op, order, line = _line_scheduling_context(
            line_stations=5, style_code="ST-OV2",
        )
        o9 = create_operator(SUPER, employee_no="E9", full_name="A9")
        create_line_assignment(
            line["id"], order["id"], op["id"], o9["id"], SUPER,
            shift_date="2026-08-03", start_minute=480, end_minute=580,
        )
        # 595 == 580 + 15: exactly the buffer — accepted.
        a3 = create_line_assignment(
            line["id"], order["id"], op["id"], o9["id"], SUPER,
            shift_date="2026-08-03", start_minute=595, end_minute=700,
            assigned_pieces=5,
        )
        assert a3["id"]

    def test_different_shift_date_does_not_interact(self):
        """PRD §3.6: "for the same operator and `shift_date`, a new assignment
        must start at least fifteen minutes after every existing assignment's
        end".

        Design: Difficulty/resource_temporal_overlap/operator_buffered_changeover_overlap
        """
        _style, _pack, op, order, line = _line_scheduling_context(
            line_stations=5, style_code="ST-OV2",
        )
        o9 = create_operator(SUPER, employee_no="E9", full_name="A9")
        create_line_assignment(
            line["id"], order["id"], op["id"], o9["id"], SUPER,
            shift_date="2026-08-03", start_minute=480, end_minute=580,
        )
        a_next_day = create_line_assignment(
            line["id"], order["id"], op["id"], o9["id"], SUPER,
            shift_date="2026-08-04", start_minute=480, end_minute=580,
        )
        assert a_next_day["id"]


class TestTimeWindow:
    def test_invalid_time_window_rejected(self):
        """PRD §3.6: "The window itself must satisfy start at or after minute
        0, end at or before minute 1440, and start strictly before end, or the
        request is `ERR_INVALID_TIME_WINDOW` (HTTP 400)."

        Design: Corner/validations/invalid_time_window_rejected
        """
        _style, _pack, op, order, line = _line_scheduling_context(style_code="ST-V10")
        opr = create_operator(SUPER, employee_no="E1", full_name="Ann")
        resp = api_client.create_line_assignment(
            create_line_assignment_payload(
                sewing_line_id=line["id"], production_order_id=order["id"],
                operation_spec_id=op["id"], operator_id=opr["id"],
                shift_date="2026-08-03", start_minute=600, end_minute=500,
            ),
            SUPER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW)

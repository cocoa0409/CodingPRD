"""Computed reads (grading, line balance, efficiency), envelope, RBAC (PRD §2.2, §2.3, §3.1, §3.6, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_available_fabric_roll,
    create_draft_tech_pack,
    create_marker_payload,
    create_production_order,
    create_style,
    get_success_data,
    plan_order,
    setup_released_bundle_with_operator,
    setup_style_with_approved_pack,
    validate_error,
    validate_paginated,
    validate_success,
    create_sewing_line,
    log_piece_work,
    verify_entry,
)

MERCH = TEST_USERS["merchandiser_headers"]
MATS = TEST_USERS["materials_planner_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
CUTMGR = TEST_USERS["cutting_manager_headers"]
SUPER = TEST_USERS["line_supervisor_headers"]
PM = TEST_USERS["plant_manager_headers"]
ANY = TEST_USERS["any_headers"]


class TestSizeGrading:
    def test_size_grading_eighth_inch_rounding(self):
        """PRD §3.1: "the raw value at a size is the base value plus the step
        count times the increment. Each resulting point-size cell is then
        rounded to the nearest one-eighth of an inch, rounding half up on the
        scaled eighth-count; rounding is applied per cell after the
        multiplication, and the cumulative raw value is never rounded
        mid-chain."

        Design: Corner/calculations/size_grading_eighth_inch_rounding
        """
        style = create_style(
            style_code="ST-C1", size_run=["XS", "S", "M", "L", "XL"],
        )
        pack = create_draft_tech_pack(
            style["id"], MERCH,
            base_measurements=[{"point": "chest", "base_value_in": 20.0}],
            grade_rules=[{"point": "chest", "per_step_increment_in": 0.4}],
        )
        data = validate_success(
            api_client.get_graded_measurements(pack["id"], ANY), 200
        )
        # Cell value key name is not fixed by the contract text; find the
        # chest value per size regardless of the serializer's key choice.
        def chest_at(size):
            for c in data["cells"]:
                if c.get("point") == "chest" and c.get("size") == size:
                    for k in ("value_in", "value", "graded_in", "measurement_in"):
                        if k in c:
                            return c[k]
                    # single numeric field besides size/point
                    numeric = [v for k, v in c.items()
                               if k not in ("point", "size") and isinstance(v, (int, float))]
                    assert numeric, f"no numeric value on cell {c}"
                    return numeric[0]
            raise AssertionError(f"no chest cell at size {size}")

        # 20.0 - 2*0.4 = 19.2 -> 153.6 eighths -> round_half_up 154 -> 19.25
        assert chest_at("XS") == pytest.approx(19.25, abs=1e-9)
        # 20.0 - 0.4 = 19.6 -> 156.8 -> 157 -> 19.625
        assert chest_at("S") == pytest.approx(19.625, abs=1e-9)
        assert chest_at("M") == pytest.approx(20.0, abs=1e-9)
        # 20.4 -> 163.2 -> 163 -> 20.375
        assert chest_at("L") == pytest.approx(20.375, abs=1e-9)
        assert chest_at("XL") == pytest.approx(20.75, abs=1e-9)
        assert data["size_run"] == ["XS", "S", "M", "L", "XL"]


class TestLineBalance:
    def test_line_balance_greedy_packing_efficiency(self):
        """PRD §3.6: "the takt time is that total divided by the line's
        `station_count`, rounded up to a whole second" and "a single operation
        longer than takt occupies a station of its own at its full length" and
        "`balance_efficiency_pct`, which is the total standard seconds as a
        percentage of the product of `stations_used` and
        `max_station_load_seconds`, rounded half up to one decimal place".

        Design: Corner/calculations/line_balance_greedy_packing_efficiency
        """
        style, pack, _ops = setup_style_with_approved_pack(
            style_overrides={"style_code": "ST-C2"},
            ops=[
                {"sequence_no": 1, "name": "join", "machine_type": "OVERLOCK",
                 "sam_seconds": 54, "piece_rate_cents": 12},
                {"sequence_no": 2, "name": "topstitch", "machine_type": "SINGLE_NEEDLE",
                 "sam_seconds": 66, "piece_rate_cents": 12},
            ],
        )
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 10}],
        )
        plan_order(order["id"], pack["id"], PLANNER)
        line = create_sewing_line(PLANNER, station_count=2)
        data = validate_success(
            api_client.get_line_balance(
                line["id"], ANY, params={"production_order_id": order["id"]},
            ),
            200,
        )
        assert data["total_sam_seconds"] == 120
        assert data["takt_seconds"] == 60  # ceil(120 / 2)
        # op1 (54) fits station 1; 54+66 > 60 closes it; op2 (66 > takt 60)
        # occupies its own station at full length.
        assert data["stations_used"] == 2
        assert data["max_station_load_seconds"] == 66
        # 120 / (2 * 66) = 90.9
        assert data["balance_efficiency_pct"] == pytest.approx(90.9, abs=1e-9)


class TestOperatorEfficiency:
    def test_operator_efficiency_read_at_top_tier_boundary(self):
        """PRD §3.7: "the sum of `earned_minutes` across the operator's
        entries in `VERIFIED` or `PAID` status, divided by the sum of assigned
        minutes across all of the operator's `LineAssignment` records,
        expressed as a percentage rounded half up to one decimal" and "ten
        percent at an efficiency of at least 100 ... with the boundary
        comparisons inclusive of the tier threshold."

        Design: Corner/calculations/operator_efficiency_read_at_top_tier_boundary
        """
        ctx = setup_released_bundle_with_operator(
            order_qty=100,
            ops=[{"sequence_no": 1, "name": "join", "machine_type": "MANUAL",
                  "sam_seconds": 60, "piece_rate_cents": 10}],
            work_date="2026-08-03", assign_start=480, assign_end=580,
            assigned_pieces=100,
        )
        entry = log_piece_work(
            ctx["bundle"]["id"], ctx["ops"][0]["id"], ctx["operator"]["id"],
            work_date="2026-08-03", qty=100,
        )
        verify_entry(entry["id"], SUPER)
        data = validate_success(
            api_client.get_operator_efficiency(ctx["operator"]["id"], ANY), 200
        )
        # earned = 100 * 60 / 60 = 100.0 ; attended = 100 -> 100.0
        assert data["earned_minutes"] == pytest.approx(100.0, abs=1e-9)
        assert data["attended_minutes"] == 100
        assert data["efficiency_pct"] == pytest.approx(100.0, abs=1e-9)


class TestEnvelopeAndPagination:
    def test_pagination_limit_offset_has_more(self):
        """PRD §2.3: "Paginated list responses include four fields in the
        `meta` object of the envelope: `limit`, `offset`, `total_count`, and
        `has_more`, where `has_more` reports whether further items exist
        beyond the returned window."

        Design: Corner/endpoints/pagination_limit_offset_has_more
        """
        style = create_style(style_code="ST-N1")
        for v in (1, 2, 3):
            create_draft_tech_pack(style["id"], MERCH, version_no=v)
        page1, meta1 = validate_paginated(
            api_client.list_tech_packs(
                ANY, params={"style_id": style["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        page2, meta2 = validate_paginated(
            api_client.list_tech_packs(
                ANY, params={"style_id": style["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False

    def test_success_and_error_envelope_shape(self):
        """PRD §2.2: "The `response_type` is either \"object\" for a single
        resource or \"array\" for a list of resources." and "The `error_id` is
        a unique, machine-readable string that identifies the specific error.
        The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/endpoints/success_and_error_envelope_shape
        """
        style = create_style(style_code="ST-N4")
        resp = api_client.get_style(style["id"], ANY)
        body = resp.json()
        assert "api_request_id" in body["meta"]
        assert body["response_type"] == "object"
        assert body["data"]["id"] == style["id"]
        resp_err = api_client.get_style(NON_EXISTENT_UUID, ANY)
        err_body = resp_err.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == ApiErrorId.ERR_NOT_FOUND.value
        assert isinstance(err_body["data"]["message"], str)
        assert err_body["data"]["message"].strip()

    def test_filtered_list_bundles_by_marker(self):
        """PRD §3.6: "bundles by `marker_id` or `production_order_id`".

        Design: Corner/endpoints/filtered_list_bundles_by_marker
        """
        style, pack, _ops = setup_style_with_approved_pack(
            style_overrides={"style_code": "ST-N2"},
        )
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 2}],
        )
        plan_order(order["id"], pack["id"], PLANNER)
        roll = create_available_fabric_roll(MATS, received_yards=82.6)
        marker_ids = []
        for _ in range(2):
            marker = get_success_data(api_client.create_marker(
                create_marker_payload(
                    production_order_id=order["id"], fabric_roll_id=roll["id"],
                    planned_pieces=1,
                ),
                CUTMGR,
            ))
            roll_now = get_success_data(api_client.get_fabric_roll(roll["id"], ANY))
            get_success_data(api_client.approve_marker(
                marker["id"],
                {"expected_fabric_roll_version": roll_now["version"]},
                CUTMGR,
            ))
            marker_ids.append(marker["id"])
        get_success_data(api_client.start_cutting(order["id"], PLANNER))
        for mid in marker_ids:
            get_success_data(api_client.cut_marker(
                mid, {"size_quantities": [{"size": "M", "qty": 1}]}, CUTMGR,
            ))
        b1, _ = validate_paginated(
            api_client.list_bundles(ANY, params={"marker_id": marker_ids[0]})
        )
        b2, _ = validate_paginated(
            api_client.list_bundles(ANY, params={"marker_id": marker_ids[1]})
        )
        assert len(b1) == 1 and b1[0]["marker_id"] == marker_ids[0]
        assert len(b2) == 1 and b2[0]["marker_id"] == marker_ids[1]
        assert b1[0]["id"] != b2[0]["id"]


class TestRbac:
    def test_merchandiser_cannot_create_marker(self):
        """PRD §4: `POST /markers` is authorized for CuttingManager. PRD §2.1:
        "A request whose authenticated role is not in the endpoint's
        authorized role list is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/merchandiser_cannot_create_marker
        """
        style = create_style(style_code="ST-B1")
        order = create_production_order(
            style["id"], PLANNER, size_quantities=[{"size": "M", "qty": 10}],
        )
        roll = create_available_fabric_roll(MATS)
        resp = api_client.create_marker(
            create_marker_payload(
                production_order_id=order["id"], fabric_roll_id=roll["id"],
                planned_pieces=10,
            ),
            MERCH,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_sewing_operator_cannot_review_entry(self):
        """PRD §4: `POST /piece-work-entries/{id}/review` is authorized for
        LineSupervisor. PRD §2.1: "A request whose authenticated role is not
        in the endpoint's authorized role list is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/sewing_operator_cannot_review_entry
        """
        ctx = setup_released_bundle_with_operator(order_qty=4)
        entry = log_piece_work(
            ctx["bundle"]["id"], ctx["ops"][0]["id"], ctx["operator"]["id"], qty=1,
        )
        from test_helpers import make_sewing_operator_headers
        resp = api_client.review_piece_work_entry(
            entry["id"], {"decision": "VERIFY"},
            make_sewing_operator_headers(ctx["operator"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        entry_after = get_success_data(
            api_client.get_piece_work_entry(entry["id"], ANY)
        )
        assert entry_after["status"] == "LOGGED"

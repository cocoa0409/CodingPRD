"""Order line shape discipline, catalog-active gates, and line list filters."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_box_line_payload,
    create_dealer_payload,
    create_door_line_payload,
    create_door_style_payload,
    create_finish_spec_payload,
    get_success_data,
    make_dealer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["plant_admin_headers"]


def _draft_order(api, price_level="L3"):
    dealer = get_success_data(api.create_dealer(create_dealer_payload(price_level=price_level), ADMIN))
    order = get_success_data(api.create_order(make_dealer_headers(dealer["id"])))
    return dealer, order


class TestLineShapeDiscipline:
    def test_box_line_with_door_style_rejected(self, api, plant_admin_headers):
        """PRD §3.2: "Shape discipline is enforced by line type: a `DOOR` line must
        carry a `door_style_id` and its `depth_in` must equal exactly 1, while a
        `BOX` line must not carry a `door_style_id` and must not carry a
        `required_sheen_lot_no`; violations are rejected with `ERR_WRONG_LINE_TYPE`
        (HTTP 422)."

        Design: Corner/validations/box_line_with_door_style_rejected
        """
        dealer, order = _draft_order(api)
        style = get_success_data(api.create_door_style(create_door_style_payload(style_code="DS-SHK"), ADMIN))
        finish = get_success_data(api.create_finish_spec(create_finish_spec_payload(), ADMIN))
        payload = create_box_line_payload(finish["id"])
        payload["door_style_id"] = style["id"]
        resp = api.create_order_line(order["id"], payload, make_dealer_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.ERR_WRONG_LINE_TYPE)

    def test_door_line_bad_depth_rejected(self, api, plant_admin_headers):
        """PRD §3.2: "Shape discipline is enforced by line type: a `DOOR` line must
        carry a `door_style_id` and its `depth_in` must equal exactly 1, while a
        `BOX` line must not carry a `door_style_id` and must not carry a
        `required_sheen_lot_no`; violations are rejected with `ERR_WRONG_LINE_TYPE`
        (HTTP 422)."

        Design: Corner/validations/door_line_bad_depth_rejected
        """
        dealer, order = _draft_order(api)
        style = get_success_data(api.create_door_style(create_door_style_payload(style_code="DS-SHK"), ADMIN))
        finish = get_success_data(api.create_finish_spec(create_finish_spec_payload(), ADMIN))
        payload = create_door_line_payload(style["id"], finish["id"], depth_in=5)
        resp = api.create_order_line(order["id"], payload, make_dealer_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.ERR_WRONG_LINE_TYPE)

    def test_finish_inactive_rejected(self, api, plant_admin_headers):
        """PRD §3.2: "Both the referenced door style and the referenced finish must
        be active — an inactive style yields `ERR_DOOR_STYLE_INACTIVE` and an
        inactive finish yields `ERR_FINISH_INACTIVE` (both HTTP 422)."

        Design: Corner/validations/finish_inactive_rejected
        """
        dealer, order = _draft_order(api)
        finish = get_success_data(
            api.create_finish_spec(
                create_finish_spec_payload(finish_code="FS-OFF", color_name="Legacy", active=False),
                ADMIN,
            )
        )
        resp = api.create_order_line(
            order["id"], create_box_line_payload(finish["id"]), make_dealer_headers(dealer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FINISH_INACTIVE)


class TestReferentialBeatsConstraint:
    def _setup_inactive_style(self, api):
        dealer, order = _draft_order(api)
        style = get_success_data(
            api.create_door_style(
                create_door_style_payload(
                    style_code="DS-OFF", name="Discontinued", construction="SLAB", active=False
                ),
                ADMIN,
            )
        )
        finish = get_success_data(api.create_finish_spec(create_finish_spec_payload(), ADMIN))
        return dealer, order, style, finish

    def test_inactive_style_error_wins_over_shape_error(self, api):
        """PRD §2.7: "When a single request violates several rules, the platform
        evaluates checks in a fixed priority order and surfaces only the first
        failure."
        PRD §2.7: "8. Catalog and configuration resources being active
        (`ERR_DOOR_STYLE_INACTIVE`, `ERR_FINISH_INACTIVE`,
        `ERR_ASSEMBLY_LINE_INACTIVE`, `ERR_STATION_INACTIVE`)."
        PRD §2.7: "9. Shape and type constraints (`ERR_WRONG_LINE_TYPE`,
        `ERR_COMPONENT_KIND_MISMATCH`, `ERR_CLAIM_LINE_NOT_ELIGIBLE`)."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_line_create
        """
        dealer, order, style, finish = self._setup_inactive_style(api)
        # Both rule 8 (inactive style) and rule 9 (DOOR depth_in != 1) are
        # violated; the earlier rule must surface.
        payload = create_door_line_payload(style["id"], finish["id"], depth_in=5, unit_list_price_cents=15000)
        resp = api.create_order_line(order["id"], payload, make_dealer_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.ERR_DOOR_STYLE_INACTIVE)

    def test_double_fault_creates_no_line(self, api, plant_admin_headers):
        """PRD §2.7: "When a single request violates several rules, the platform
        evaluates checks in a fixed priority order and surfaces only the first
        failure."
        PRD §3.2: "The order-line list view supports filtering by `order_id`,
        `door_style_id`, `finish_id`, and `finish_batch_id`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_line_create
        """
        dealer, order, style, finish = self._setup_inactive_style(api)
        payload = create_door_line_payload(style["id"], finish["id"], depth_in=5, unit_list_price_cents=15000)
        resp = api.create_order_line(order["id"], payload, make_dealer_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.ERR_DOOR_STYLE_INACTIVE)
        rows, meta = validate_paginated(
            api.list_order_lines(plant_admin_headers, params={"order_id": order["id"]})
        )
        assert len(rows) == 0 and meta["total_count"] == 0, (
            "a rejected line creation must leave no OrderLine behind"
        )


class TestOrderCube:
    def test_order_cube_per_line_rounding(self, api, plant_admin_headers):
        """PRD §3.2: "Line creation also recomputes the order's shipping cube: per
        non-cancelled line, the width times height times depth times quantity in
        cubic inches is divided by 1728 (the cubic inches in one cubic foot) and
        rounded half up to two decimal places, and the order's `cube_ft` is the
        sum of those per-line cubes, again rounded half up to two decimal places."

        Design: Corner/calculations/order_cube_per_line_rounding
        """
        dealer, order = _draft_order(api)
        style = get_success_data(api.create_door_style(create_door_style_payload(style_code="DS-SHK"), ADMIN))
        finish = get_success_data(
            api.create_finish_spec(
                create_finish_spec_payload(finish_code="FS-SAT-10", sheen="SATIN", upcharge_pct=0.10),
                ADMIN,
            )
        )
        get_success_data(
            api.create_order_line(
                order["id"],
                create_door_line_payload(style["id"], finish["id"], qty=4, unit_list_price_cents=30000),
                make_dealer_headers(dealer["id"]),
            )
        )
        reread = validate_success(api.get_order(order["id"], plant_admin_headers))
        # 15 x 30 x 1 x 4 = 1,800 in3 / 1728 = 1.04166... -> 1.04 ft3 at 2dp.
        assert reread["cube_ft"] == pytest.approx(1.04), (
            f"per-line cube must round half up to 2dp before summing; got {reread['cube_ft']}"
        )


class TestOrderLineFilters:
    def test_order_lines_filtered_by_finish_id(self, api, plant_admin_headers):
        """PRD §3.2: "The order-line list view supports filtering by `order_id`,
        `door_style_id`, `finish_id`, and `finish_batch_id`."

        Design: Corner/endpoints/order_lines_filtered_by_finish_id
        """
        dealer, order = _draft_order(api)
        finish_a = get_success_data(
            api.create_finish_spec(create_finish_spec_payload(finish_code="FS-A", color_name="A"), ADMIN)
        )
        finish_b = get_success_data(
            api.create_finish_spec(
                create_finish_spec_payload(finish_code="FS-B", color_name="B", sheen="SATIN"), ADMIN
            )
        )
        for finish in (finish_a, finish_a, finish_b):
            get_success_data(
                api.create_order_line(
                    order["id"], create_box_line_payload(finish["id"]), make_dealer_headers(dealer["id"])
                )
            )
        rows, meta = validate_paginated(
            api.list_order_lines(plant_admin_headers, params={"finish_id": finish_a["id"]})
        )
        assert len(rows) == 2, f"expected exactly the 2 lines on finish A, got {len(rows)}"
        assert all(row["finish_id"] == finish_a["id"] for row in rows)

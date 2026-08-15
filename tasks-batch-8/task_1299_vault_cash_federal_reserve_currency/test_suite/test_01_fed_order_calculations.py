"""Fed order calculations: face totals, per-line fee rounding, OCC on line adds."""
from test_helpers import (
    ApiErrorId,
    create_fed_order_payload,
    create_staffed_site,
    get_success_data,
    validate_error,
    validate_paginated,
)


class TestPerLineFeeRounding:
    def test_two_equal_lines_round_per_line_then_sum(self, api):
        """PRD §3.2: "The Fed's service fee is charged per line at one
        one-hundred-sixtieth of the line's value (0.625%), with each line's
        `fee_cents` rounded half-up to integer cents individually and only then
        summed into `fee_total_cents`."
        PRD §3.2: "This pinned order matters: two lines of 10,000 cents each yield
        per-line fees of 63 and 63 for a total of 126 cents, whereas summing first
        and rounding once would incorrectly give 125."

        Design: Difficulty/combinatorial_formula/fed_fee_per_line_rounding_then_sum
        """
        ctx = create_staffed_site(staff_roles=("coordinator",))
        coord = ctx["staff"]["coordinator"]["headers"]
        site_id = ctx["site"]["id"]

        order = get_success_data(
            api.create_fed_order(
                create_fed_order_payload(
                    site_id=site_id, direction="DEPOSIT", business_date="2026-08-03"
                ),
                coord,
            )
        )
        line1 = get_success_data(
            api.add_denomination_line(
                order["id"],
                {
                    "denomination_cents": 100,
                    "strap_count": 1,
                    "expected_fed_order_version": order["version"],
                },
                coord,
            )
        )
        assert line1["line_cents"] == 10000, f"line 1 line_cents: {line1['line_cents']}"
        assert line1["fee_cents"] == 63, (
            f"round_half_up(10000/160) = round_half_up(62.5) must be 63, got {line1['fee_cents']}"
        )
        mid = get_success_data(api.get_fed_order(order["id"], coord))
        get_success_data(
            api.add_denomination_line(
                order["id"],
                {
                    "denomination_cents": 100,
                    "strap_count": 1,
                    "expected_fed_order_version": mid["version"],
                },
                coord,
            )
        )
        final = get_success_data(api.get_fed_order(order["id"], coord))
        assert final["face_total_cents"] == 20000
        assert final["fee_total_cents"] == 126, (
            f"per-line rounding then sum must give 126 (not the sum-then-round 125), "
            f"got {final['fee_total_cents']}"
        )
        assert final["grand_total_cents"] == 20126

    def test_single_line_fee_is_rounded_half_up_individually(self, api):
        """PRD §3.2: "This pinned order matters: two lines of 10,000 cents each yield
        per-line fees of 63 and 63 for a total of 126 cents, whereas summing first
        and rounding once would incorrectly give 125."
        PRD §3.2: "The order's `grand_total_cents` is the face total plus the fee
        total."

        Design: Difficulty/combinatorial_formula/fed_fee_per_line_rounding_then_sum
        """
        ctx = create_staffed_site(staff_roles=("coordinator",))
        coord = ctx["staff"]["coordinator"]["headers"]
        site_id = ctx["site"]["id"]

        order = get_success_data(
            api.create_fed_order(
                create_fed_order_payload(
                    site_id=site_id, direction="DEPOSIT", business_date="2026-08-03"
                ),
                coord,
            )
        )
        line = get_success_data(
            api.add_denomination_line(
                order["id"],
                {
                    "denomination_cents": 100,
                    "strap_count": 1,
                    "expected_fed_order_version": order["version"],
                },
                coord,
            )
        )
        # A single 10,000-cent line is exactly the half-way point (62.5): the
        # half-up rule is observable on one line alone.
        assert line["fee_cents"] == 63, (
            f"single-line fee must be round_half_up(62.5) = 63, got {line['fee_cents']}"
        )
        fetched = get_success_data(api.get_fed_order(order["id"], coord))
        assert fetched["fee_total_cents"] == 63
        assert fetched["grand_total_cents"] == 10000 + 63


class TestDenominationLineComputedFields:
    def test_line_cents_and_fee_cents_are_server_computed(self, api):
        """PRD §3.2: "Every line's face value `line_cents` is computed exactly as its
        denomination times 100 notes per strap times its strap count, and the order's
        `face_total_cents` is the plain integer sum of all line values — zero lines
        means a face total of zero."
        PRD §3.2: "The Fed's service fee is charged per line at one
        one-hundred-sixtieth of the line's value (0.625%), with each line's
        `fee_cents` rounded half-up to integer cents individually and only then
        summed into `fee_total_cents`."

        Design: Corner/entities/denomination_line_computed_fields
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 10000000},
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        site_id = ctx["site"]["id"]

        order = get_success_data(
            api.create_fed_order(
                create_fed_order_payload(
                    site_id=site_id, direction="DEPOSIT", business_date="2026-08-03"
                ),
                coord,
            )
        )
        line = get_success_data(
            api.add_denomination_line(
                order["id"],
                {
                    "denomination_cents": 5000,
                    "strap_count": 5,
                    "expected_fed_order_version": order["version"],
                },
                coord,
            )
        )
        assert line["line_cents"] == 2500000, (
            f"5000 * 100 * 5 must be 2,500,000, got {line['line_cents']}"
        )
        assert line["fee_cents"] == 15625, (
            f"round_half_up(2,500,000 / 160) must be 15,625, got {line['fee_cents']}"
        )
        fetched = get_success_data(api.get_fed_order(order["id"], coord))
        assert fetched["face_total_cents"] == 2500000
        assert fetched["fee_total_cents"] == 15625
        assert fetched["grand_total_cents"] == 2515625


class TestLineAddOptimisticConcurrency:
    def test_stale_line_add_rejected_after_first_add(self, api):
        """PRD §2.7: "Adding a denomination line to a draft Fed order requires
        `expected_fed_order_version` matching the order's current `version`. A
        line-add carrying an older value is rejected with
        `ERR_STALE_FED_ORDER_VERSION` (HTTP 412) so that draft edits serialize."

        Design: Corner/cross_cutting_layers/occ_line_add_stale_rejected
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 10000000},
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        site_id = ctx["site"]["id"]

        order = get_success_data(
            api.create_fed_order(
                create_fed_order_payload(
                    site_id=site_id, direction="DEPOSIT", business_date="2026-08-03"
                ),
                coord,
            )
        )
        stale_version = order["version"]
        get_success_data(
            api.add_denomination_line(
                order["id"],
                {
                    "denomination_cents": 100,
                    "strap_count": 10,
                    "expected_fed_order_version": stale_version,
                },
                coord,
            )
        )
        replay = api.add_denomination_line(
            order["id"],
            {
                "denomination_cents": 100,
                "strap_count": 10,
                "expected_fed_order_version": stale_version,
            },
            coord,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_FED_ORDER_VERSION)

        fetched = get_success_data(api.get_fed_order(order["id"], coord))
        assert fetched["version"] == 2, (
            f"order version must have advanced to 2 after the first add, got {fetched['version']}"
        )
        assert fetched["face_total_cents"] == 100000

        lines, meta = validate_paginated(api.list_denomination_lines(order["id"], coord))
        assert meta["total_count"] == 1, (
            f"exactly one line must exist after the stale add was rejected, got {meta['total_count']}"
        )

    def test_line_add_with_fresh_version_succeeds_after_stale_rejection(self, api):
        """PRD §2.7: "Adding a denomination line to a draft Fed order requires
        `expected_fed_order_version` matching the order's current `version`. A
        line-add carrying an older value is rejected with
        `ERR_STALE_FED_ORDER_VERSION` (HTTP 412) so that draft edits serialize."

        Design: Corner/cross_cutting_layers/occ_line_add_stale_rejected
        """
        ctx = create_staffed_site(
            staff_roles=("coordinator",),
            site_overrides={"opening_fit_cents": 10000000},
        )
        coord = ctx["staff"]["coordinator"]["headers"]
        site_id = ctx["site"]["id"]

        order = get_success_data(
            api.create_fed_order(
                create_fed_order_payload(
                    site_id=site_id, direction="DEPOSIT", business_date="2026-08-03"
                ),
                coord,
            )
        )
        first = get_success_data(
            api.add_denomination_line(
                order["id"],
                {
                    "denomination_cents": 100,
                    "strap_count": 10,
                    "expected_fed_order_version": order["version"],
                },
                coord,
            )
        )
        assert first["line_cents"] == 100000
        stale = api.add_denomination_line(
            order["id"],
            {
                "denomination_cents": 100,
                "strap_count": 10,
                "expected_fed_order_version": order["version"],
            },
            coord,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_FED_ORDER_VERSION)
        current = get_success_data(api.get_fed_order(order["id"], coord))
        second = get_success_data(
            api.add_denomination_line(
                order["id"],
                {
                    "denomination_cents": 100,
                    "strap_count": 10,
                    "expected_fed_order_version": current["version"],
                },
                coord,
            )
        )
        assert second["line_cents"] == 100000
        final = get_success_data(api.get_fed_order(order["id"], coord))
        assert final["face_total_cents"] == 200000

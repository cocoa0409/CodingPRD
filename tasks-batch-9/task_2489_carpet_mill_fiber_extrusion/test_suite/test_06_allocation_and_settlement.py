"""Order fulfilment: the roll-good selector, the manual-allocation validation ladder,
the flammability gate, per-line charge rounding and cut-order settlement.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_cut_allocation,
    assert_cut_order,
    assert_net_invoice,
    assert_remnant_posture,
    assert_roll_good,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

_PLANNER = TEST_USERS["mill_planner_headers"]
_QA = TEST_USERS["qa_lab_technician_headers"]

# The computed money-and-yardage face of a cut order, as recomputed by allocation.
_SETTLED_FIELDS = (
    "status",
    "allocated_yards",
    "gross_cents",
    "freight_cents",
    "remnant_credit_cents",
    "net_invoice_cents",
)


# ---------------------------------------------------------------------------
# Scenario builders. Every test starts from an empty database, so each one
# rebuilds the whole chain it needs.
# ---------------------------------------------------------------------------


def _manual_line(api, cut_order_id, roll_good_id, yards, expected_version):
    """Raw manual-allocation call, so the failing cases can inspect the error."""
    return api.create_manual_allocation(
        cut_order_id,
        factories.manual_allocation_payload(roll_good_id, yards, expected_version),
        _PLANNER,
    )


def _two_half_cent_lines(api):
    """A 20.0-yard order filled by two manual lines of 12.5 and 7.5 yards.

    At 4275 cents a yard each line's raw charge lands on an exact half cent.
    """
    ctx = fixtures.setup_submitted_cut_order(
        order_overrides={"requested_yards": 20.0, "shade_tolerance": "ANY"}
    )
    order_id = ctx["cut_order"]["id"]
    roll = ctx["roll_good"]
    first = validate_success(
        _manual_line(api, order_id, roll["id"], 12.5, roll["version"]), 201
    )
    refreshed = fixtures.refresh_roll_good(roll["id"])
    second = validate_success(
        _manual_line(api, order_id, roll["id"], 7.5, refreshed["version"]), 201
    )
    ctx["line_one"] = first
    ctx["line_two"] = second
    ctx["cut_order"] = fixtures.refresh_cut_order(order_id)
    return ctx


def _remnant_and_whole_roll_order(api):
    """A 24.0-yard order filled from a 40.0-yard roll plus a 2.0-yard remnant."""
    ctx = fixtures.setup_cut_order_with_remnant(
        initial_yards=100.0, requested_yards=98.0
    )
    remnant = ctx["remnant"]
    assert remnant is not None, "cutting 98.0 of 100.0 yards must mint a remnant child"
    second_roll = fixtures.add_roll_good_to_run(
        ctx, roll_number="RG-02", initial_yards=40.0
    )
    order = fixtures.create_cut_order(
        ctx["account"]["id"],
        ctx["style"]["id"],
        order_code="CO-02",
        requested_yards=24.0,
        shade_tolerance="ANY",
    )
    line_one = validate_success(
        _manual_line(
            api, order["id"], second_roll["id"], 22.0, second_roll["version"]
        ),
        201,
    )
    fresh_remnant = fixtures.refresh_roll_good(remnant["id"])
    line_two = validate_success(
        _manual_line(
            api, order["id"], remnant["id"], 2.0, fresh_remnant["version"]
        ),
        201,
    )
    ctx["second_roll"] = second_roll
    ctx["line_one"] = line_one
    ctx["line_two"] = line_two
    ctx["second_order"] = fixtures.refresh_cut_order(order["id"])
    return ctx


def _uncertified_style_with_held_roll():
    """An ACTIVE style holding no certificate at all, over a roll on quality hold."""
    ctx = fixtures.setup_backed_solution_dyed_run()
    roll = fixtures.doff_roll_good(ctx["run"]["id"], initial_yards=200.0)
    ctx["product_test"] = fixtures.record_product_test(
        ctx["style"]["id"],
        roll["id"],
        test_type="FLAMMABILITY_PILL",
        result_value=18.0,
    )
    ctx["roll_good"] = fixtures.qa_disposition_roll_good(roll["id"], "HOLD")
    ctx["account"] = fixtures.create_account()
    ctx["cut_order"] = fixtures.create_cut_order(
        ctx["account"]["id"], ctx["style"]["id"], requested_yards=50.0
    )
    return ctx


def _certificate_expiring_at_september():
    """A certified style plus two identical 50.0-yard orders; the certificate dies
    at 2026-09-01T00:00:00Z."""
    ctx = fixtures.setup_backed_solution_dyed_run()
    roll = fixtures.doff_roll_good(ctx["run"]["id"], initial_yards=200.0)
    test = fixtures.record_product_test(
        ctx["style"]["id"],
        roll["id"],
        test_type="FLAMMABILITY_PILL",
        result_value=18.0,
    )
    ctx["product_test"] = test
    ctx["certification"] = fixtures.issue_certification(
        ctx["style"]["id"],
        [test["id"]],
        cert_type="DOC_FF_1_70",
        expires_at_utc="2026-09-01T00:00:00Z",
    )
    ctx["roll_good"] = fixtures.release_roll_good(roll["id"])
    ctx["account"] = fixtures.create_account()
    ctx["order_one"] = fixtures.create_cut_order(
        ctx["account"]["id"],
        ctx["style"]["id"],
        order_code="CO-01",
        requested_yards=50.0,
        shade_tolerance="ANY",
    )
    ctx["order_two"] = fixtures.create_cut_order(
        ctx["account"]["id"],
        ctx["style"]["id"],
        order_code="CO-02",
        requested_yards=50.0,
        shade_tolerance="ANY",
    )
    return ctx


def _sixty_and_hundred_yard_rolls():
    """Two eligible non-remnant rolls of 60.0 and 100.0 yards, plus a 130.0-yard order."""
    ctx = fixtures.setup_available_solution_dyed_roll(
        roll_overrides={"roll_number": "RG-A", "initial_yards": 60.0}
    )
    ctx["roll_b"] = fixtures.add_roll_good_to_run(
        ctx, roll_number="RG-B", initial_yards=100.0
    )
    ctx["account"] = fixtures.create_account()
    ctx["cut_order"] = fixtures.create_cut_order(
        ctx["account"]["id"],
        ctx["style"]["id"],
        requested_yards=130.0,
        shade_tolerance="ANY",
    )
    return ctx


# ---------------------------------------------------------------------------
# Per-line rounding before the gross sum
# ---------------------------------------------------------------------------


class TestPerLineChargeRounding:
    def test_each_manual_line_is_rounded_before_the_gross_is_summed(self, api):
        """Two half-cent lines round up individually to 53438 and 32063, summing to 85501.

        PRD: "Only after every line has been rounded individually is the order's
        `gross_cents` formed, as the exact integer sum of `line_cents` over the
        order's lines in status `RESERVED`, `CUT` or `SHIPPED`"

        Design: Difficulty/combinatorial_formula/line_charges_per_line_rounding_before_sum
        """
        ctx = _two_half_cent_lines(api)
        first, second = ctx["line_one"], ctx["line_two"]
        assert_cut_allocation(first)
        assert_cut_allocation(second)

        assert first["yards"] == pytest.approx(12.5, abs=0.01)
        assert second["yards"] == pytest.approx(7.5, abs=0.01)
        assert first["line_cents"] == 53438, (
            f"12.5 yards at 4275 cents is 53437.5, which rounds half-up to 53438, "
            f"got {first['line_cents']}"
        )
        assert second["line_cents"] == 32063, (
            f"7.5 yards at 4275 cents is 32062.5, which rounds half-up to 32063, "
            f"got {second['line_cents']}"
        )

        order = ctx["cut_order"]
        assert order["gross_cents"] == 85501, (
            f"gross_cents must be the integer sum 53438 + 32063 = 85501, got "
            f"{order['gross_cents']}"
        )
        assert order["gross_cents"] != 85500, (
            "gross_cents of 85500 means the unrounded line values were summed and "
            "then rounded, which the per-line rule forbids"
        )

    def test_settlement_follows_the_per_line_gross_and_leaves_the_roll_available(
        self, api
    ):
        """The 85501-cent gross pays 4500 freight, no remnant credit, netting 90001.

        PRD: "Rounding the sum of the unrounded line values instead of summing the
        rounded line values is incorrect and will differ by whole cents"

        Design: Difficulty/combinatorial_formula/line_charges_per_line_rounding_before_sum
        """
        ctx = _two_half_cent_lines(api)
        order = ctx["cut_order"]
        assert_cut_order(order)

        assert order["freight_cents"] == 4500, (
            f"a gross of 85501 cents sits in the middle freight tier at 4500, got "
            f"{order['freight_cents']}"
        )
        assert order["remnant_credit_cents"] == 0, (
            f"neither line came off a remnant, so the credit is 0, got "
            f"{order['remnant_credit_cents']}"
        )
        assert order["net_invoice_cents"] == 90001, (
            f"net must be 85501 + 4500 - 0 = 90001, got {order['net_invoice_cents']}"
        )
        assert_net_invoice(order)

        assert order["status"] == "ALLOCATED", (
            f"20.0 of 20.0 yards are committed, so the order is ALLOCATED, got "
            f"{order['status']}"
        )
        assert order["allocated_yards"] == pytest.approx(20.0, abs=0.01)
        assert order["reserved_credit_cents"] == 85500, (
            f"the credit hold follows requested_yards: 20.0 * 4275 = 85500, got "
            f"{order['reserved_credit_cents']}"
        )

        roll = fixtures.refresh_roll_good(ctx["roll_good"]["id"])
        assert_roll_good(roll)
        assert roll["available_yards"] == pytest.approx(180.0, abs=0.01), (
            f"200.0 less 20.0 committed yards leaves 180.0, got "
            f"{roll['available_yards']}"
        )
        assert roll["inventory_status"] == "AVAILABLE", (
            f"the roll still carries yardage, so it stays AVAILABLE, got "
            f"{roll['inventory_status']}"
        )


# ---------------------------------------------------------------------------
# Settlement: freight keyed on gross, remnant credit, net invoice
# ---------------------------------------------------------------------------


class TestSettlementKeyedOnGross:
    def test_remnant_line_takes_the_discount_and_earns_the_order_credit(self, api):
        """A 2.0-yard remnant line charges 7268 and lifts the credit to 3040 cents.

        PRD: "by 0.85, reflecting a fifteen percent discount for remnant yardage"

        Design: Difficulty/combinatorial_formula/settlement_freight_tier_keyed_on_gross_not_net
        """
        ctx = _remnant_and_whole_roll_order(api)
        remnant = fixtures.refresh_roll_good(ctx["remnant"]["id"])
        assert_remnant_posture(remnant)
        assert remnant["is_remnant"] is True
        assert remnant["initial_yards"] == pytest.approx(2.0, abs=0.01), (
            f"the residual of 100.0 - 98.0 yards becomes the child's initial_yards, "
            f"got {remnant['initial_yards']}"
        )
        assert remnant["parent_roll_id"] == ctx["parent_roll"]["id"]

        parent = fixtures.refresh_roll_good(ctx["parent_roll"]["id"])
        assert parent["inventory_status"] == "DEPLETED", (
            f"a sub-threshold residual split off drives the parent to DEPLETED, got "
            f"{parent['inventory_status']}"
        )

        line_one, line_two = ctx["line_one"], ctx["line_two"]
        assert line_one["from_remnant"] is False
        assert line_one["line_cents"] == 94050, (
            f"22.0 yards at 4275 cents with a SOLUTION factor of 1.00 is 94050, got "
            f"{line_one['line_cents']}"
        )
        assert line_two["from_remnant"] is True
        assert line_two["line_cents"] == 7268, (
            f"2.0 * 4275 * 1.00 * 0.85 is 7267.5, rounding half-up to 7268, got "
            f"{line_two['line_cents']}"
        )

        order = ctx["second_order"]
        assert order["gross_cents"] == 101318, (
            f"gross must be 94050 + 7268 = 101318, got {order['gross_cents']}"
        )
        assert order["remnant_credit_cents"] == 3040, (
            f"101318 * 0.03 is 3039.54, rounding half-up to 3040, got "
            f"{order['remnant_credit_cents']}"
        )

    def test_freight_tier_reads_gross_even_when_the_net_falls_below_the_threshold(
        self, api
    ):
        """Gross 101318 ships freight-free although the net settles at 98278.

        PRD: "freight is 0 when `gross_cents` is at least 100000 cents, 4500 cents
        when `gross_cents` is at least 50000 cents, and 8900 cents otherwise"

        Design: Difficulty/combinatorial_formula/settlement_freight_tier_keyed_on_gross_not_net
        """
        ctx = _remnant_and_whole_roll_order(api)
        order = ctx["second_order"]
        assert_cut_order(order)

        assert order["gross_cents"] == 101318
        assert order["freight_cents"] == 0, (
            f"a gross of 101318 clears the 100000-cent freight-free tier, got "
            f"{order['freight_cents']}"
        )
        assert order["net_invoice_cents"] == 98278, (
            f"net must be 101318 + 0 - 3040 = 98278, got "
            f"{order['net_invoice_cents']}"
        )
        assert_net_invoice(order)
        assert order["net_invoice_cents"] < 100000 and order["freight_cents"] == 0, (
            "the net of 98278 is below the freight-free threshold, so freight of 0 "
            "proves the tier was keyed on gross_cents rather than on the net"
        )
        assert order["net_invoice_cents"] != 102778, (
            "102778 is the figure a net-keyed freight tier would produce"
        )

        assert order["status"] == "ALLOCATED", (
            f"24.0 of 24.0 yards are committed, got {order['status']}"
        )
        assert order["allocated_yards"] == pytest.approx(24.0, abs=0.01)

    def test_freight_tier_boundaries_are_inclusive_at_100000_and_50000_cents(self, api):
        """Gross 100000 ships free, gross 50000 pays 4500 and gross 49500 pays 8900.

        PRD: "Both tier comparisons are inclusive, so a `gross_cents` of exactly
        100000 ships freight-free and one of exactly 50000 pays 4500"

        Design: Corner/calculations/settlement_freight_tiers_are_inclusive_at_100000_and_50000_cents
        """
        ctx = fixtures.setup_available_solution_dyed_roll(
            roll_overrides={"initial_yards": 100.0},
            style_overrides={
                "style_code": "ST-SD-05",
                "list_price_cents_per_yard": 5000,
            },
        )
        account = fixtures.create_account()
        expectations = [
            ("CO-01", 20.0, 100000, 0, 100000),
            ("CO-02", 10.0, 50000, 4500, 54500),
            ("CO-03", 9.9, 49500, 8900, 58400),
        ]
        for order_code, yards, gross, freight, net in expectations:
            order = fixtures.create_cut_order(
                account["id"],
                ctx["style"]["id"],
                order_code=order_code,
                requested_yards=yards,
                shade_tolerance="ANY",
            )
            allocated = validate_success(
                api.allocate_cut_order(order["id"], _PLANNER), 200
            )
            assert allocated["status"] == "ALLOCATED", (
                f"{order_code} for {yards} yards is fully covered, got "
                f"{allocated['status']}"
            )
            assert allocated["gross_cents"] == gross, (
                f"{order_code}: {yards} yards at 5000 cents is {gross}, got "
                f"{allocated['gross_cents']}"
            )
            assert allocated["freight_cents"] == freight, (
                f"{order_code}: a gross of {gross} cents pays {freight} freight, got "
                f"{allocated['freight_cents']}"
            )
            assert allocated["remnant_credit_cents"] == 0, (
                f"{order_code} drew from a non-remnant roll, so the credit is 0, got "
                f"{allocated['remnant_credit_cents']}"
            )
            assert allocated["net_invoice_cents"] == net, (
                f"{order_code}: net must be {gross} + {freight} - 0 = {net}, got "
                f"{allocated['net_invoice_cents']}"
            )
            assert_net_invoice(allocated)

        roll = fixtures.refresh_roll_good(ctx["roll_good"]["id"])
        assert roll["available_yards"] == pytest.approx(60.1, abs=0.01), (
            f"100.0 less 20.0, 10.0 and 9.9 yards leaves 60.1, got "
            f"{roll['available_yards']}"
        )
        assert roll["inventory_status"] == "AVAILABLE", (
            f"the roll still carries yardage, got {roll['inventory_status']}"
        )


# ---------------------------------------------------------------------------
# The flammability gate against the empty-candidate-set refusal
# ---------------------------------------------------------------------------


class TestFlammabilityGateBeatsCandidateSet:
    def test_missing_certificate_refuses_allocation_before_the_candidate_set_is_weighed(
        self, api
    ):
        """With no certificate and no eligible roll, allocate reports the certificate.

        PRD: "The ordered style holds a `Certification` whose `cert_type` is
        `DOC_FF_1_70`, whose `status` is `ACTIVE` and whose `expires_at_utc` is
        strictly later than the logical clock"
        PRD: "Evaluation stops at the first failing rung."

        Design: Difficulty/priority_pair_validation_conflict/flammability_cert_safety_beats_no_eligible_rolls_referential_on_allocate
        """
        ctx = _uncertified_style_with_held_roll()
        roll = fixtures.refresh_roll_good(ctx["roll_good"]["id"])
        assert roll["qa_status"] == "HELD", (
            f"the roll was put on quality hold, got {roll['qa_status']}"
        )
        assert roll["inventory_status"] == "IN_PROCESS", (
            f"a held roll never becomes AVAILABLE, got {roll['inventory_status']}"
        )

        order_id = ctx["cut_order"]["id"]
        error = validate_error(
            api.allocate_cut_order(order_id, _PLANNER),
            "ERR_FLAMMABILITY_CERT_REQUIRED",
        )
        assert error["error_id"] != "ERR_NO_ELIGIBLE_ROLL_GOODS", (
            "the certificate gate is evaluated before the candidate-set check, so "
            "the empty candidate set must not decide the error"
        )

        order = fixtures.refresh_cut_order(order_id)
        assert order["status"] == "SUBMITTED", (
            f"a refused allocation leaves the order untouched, got {order['status']}"
        )
        assert order["allocated_yards"] == pytest.approx(0.0, abs=0.01)
        assert fixtures.list_allocations_for_order(order_id) == [], (
            "a refused allocation creates no lines"
        )

    def test_issuing_the_certificate_exposes_the_empty_candidate_set(self, api):
        """Once certified, the same allocate is refused for having no eligible roll.

        PRD: "If the candidate set is empty, nothing is created and the request is
        refused with `ERR_NO_ELIGIBLE_ROLL_GOODS`"
        PRD: "Rolls whose `inventory_status` is `IN_PROCESS`, `COMMITTED`,
        `DEPLETED` or `SCRAPPED`, and rolls whose `qa_status` is anything other than
        `PASSED`, are never candidates."

        Design: Difficulty/priority_pair_validation_conflict/flammability_cert_safety_beats_no_eligible_rolls_referential_on_allocate
        """
        ctx = _uncertified_style_with_held_roll()
        order_id = ctx["cut_order"]["id"]
        validate_error(
            api.allocate_cut_order(order_id, _PLANNER),
            "ERR_FLAMMABILITY_CERT_REQUIRED",
        )

        certification = fixtures.issue_certification(
            ctx["style"]["id"],
            [ctx["product_test"]["id"]],
            cert_type="DOC_FF_1_70",
        )
        assert certification["status"] == "ACTIVE", (
            f"a freshly issued certificate is ACTIVE, got {certification['status']}"
        )
        assert certification["cert_type"] == "DOC_FF_1_70"

        validate_error(
            api.allocate_cut_order(order_id, _PLANNER),
            "ERR_NO_ELIGIBLE_ROLL_GOODS",
        )

        order = fixtures.refresh_cut_order(order_id)
        assert order["status"] == "SUBMITTED", (
            f"an empty candidate set leaves the order SUBMITTED, got {order['status']}"
        )
        assert fixtures.list_allocations_for_order(order_id) == [], (
            "nothing is created when the candidate set is empty"
        )


# ---------------------------------------------------------------------------
# The manual-allocation validation ladder
# ---------------------------------------------------------------------------


class TestManualAllocationLadder:
    def test_unknown_roll_reports_not_found_rather_than_a_stale_version(self, api):
        """A body roll_good_id that resolves to nothing yields 404, not the 412.

        PRD: "Body reference existence.** Every foreign key carried in the request
        body resolves to an existing row"
        PRD: "The applicable 404 from the same catalogue is returned."

        Design: Difficulty/priority_pair_validation_conflict/body_fk_existence_beats_occ_then_occ_beats_yardage_on_manual_allocation
        """
        ctx = fixtures.setup_submitted_cut_order(
            order_overrides={"requested_yards": 50.0, "shade_tolerance": "ANY"}
        )
        order_id = ctx["cut_order"]["id"]
        roll = ctx["roll_good"]

        response = _manual_line(
            api, order_id, NON_EXISTENT_UUID, 9999.0, roll["version"] - 1
        )
        error = validate_error(response, "ERR_ROLL_GOOD_NOT_FOUND")
        assert response.status_code == 404, (
            f"an absent body reference is a 404, got {response.status_code}"
        )
        assert error["error_id"] != "ERR_STALE_ROLL_GOOD_VERSION", (
            "existence is checked before the stale-version rung, so the deliberately "
            "stale version must not decide the error"
        )

        assert fixtures.list_allocations_for_order(order_id) == [], (
            "a refused manual line creates nothing"
        )
        after = fixtures.refresh_roll_good(roll["id"])
        assert after["version"] == roll["version"], (
            f"the named roll was never touched: version was {roll['version']}, now "
            f"{after['version']}"
        )

    def test_stale_version_reports_412_rather_than_insufficient_yardage(self, api):
        """A stale expected_roll_good_version wins over an impossible 9999.0 yards.

        PRD: "The supplied `expected_dye_lot_version` or
        `expected_roll_good_version` equals the parent's current `version`"
        PRD: "A mismatch with the roll's current `version` is rejected with
        `ERR_STALE_ROLL_GOOD_VERSION` and HTTP status 412."

        Design: Difficulty/priority_pair_validation_conflict/body_fk_existence_beats_occ_then_occ_beats_yardage_on_manual_allocation
        """
        ctx = fixtures.setup_submitted_cut_order(
            order_overrides={"requested_yards": 50.0, "shade_tolerance": "ANY"}
        )
        order_id = ctx["cut_order"]["id"]
        roll = ctx["roll_good"]

        stale = _manual_line(api, order_id, roll["id"], 9999.0, roll["version"] - 1)
        stale_error = validate_error(stale, "ERR_STALE_ROLL_GOOD_VERSION")
        assert stale.status_code == 412, (
            f"a stale roll version is a 412, got {stale.status_code}"
        )
        assert stale_error["error_id"] != "ERR_ROLL_YARDAGE_INSUFFICIENT", (
            "the stale-version rung is evaluated before manual line feasibility, so "
            "the over-sized yardage must not decide the error"
        )

        oversized = _manual_line(api, order_id, roll["id"], 9999.0, roll["version"])
        validate_error(oversized, "ERR_ROLL_YARDAGE_INSUFFICIENT")
        assert oversized.status_code == 422, (
            f"an over-sized manual line is a 422, got {oversized.status_code}"
        )

        assert fixtures.list_allocations_for_order(order_id) == [], (
            "none of the refused attempts created a line"
        )
        after = fixtures.refresh_roll_good(roll["id"])
        assert after["available_yards"] == pytest.approx(200.0, abs=0.01), (
            f"no yardage was committed, got {after['available_yards']}"
        )
        assert after["inventory_status"] == "AVAILABLE"
        assert after["version"] == roll["version"], (
            f"a refused manual line does not move the roll's version: was "
            f"{roll['version']}, now {after['version']}"
        )
        order = fixtures.refresh_cut_order(order_id)
        assert order["status"] == "SUBMITTED"
        assert order["allocated_yards"] == pytest.approx(0.0, abs=0.01)

    def test_pending_roll_is_invisible_to_the_selector_and_refused_by_name(self, api):
        """A PENDING roll empties the candidate set and is not manually allocatable.

        PRD: "The named roll must be `PASSED` on quality and `AVAILABLE` on
        inventory, failing which the refusal is `ERR_ROLL_NOT_ALLOCATABLE`"

        Design: Corner/validations/allocation_gates_reject_an_unpassed_roll_before_they_weigh_its_yardage
        """
        ctx = fixtures.setup_backed_solution_dyed_run()
        roll = fixtures.doff_roll_good(ctx["run"]["id"], initial_yards=100.0)
        fixtures.issue_flammability_certification(ctx["style"]["id"], roll["id"])
        account = fixtures.create_account()
        order = fixtures.create_cut_order(
            account["id"],
            ctx["style"]["id"],
            requested_yards=200.0,
            shade_tolerance="ANY",
        )
        order_id = order["id"]

        validate_error(
            api.allocate_cut_order(order_id, _PLANNER), "ERR_NO_ELIGIBLE_ROLL_GOODS"
        )
        assert fixtures.refresh_cut_order(order_id)["status"] == "SUBMITTED", (
            "an empty candidate set leaves the order SUBMITTED"
        )

        validate_error(
            _manual_line(api, order_id, roll["id"], 100.0, roll["version"]),
            "ERR_ROLL_NOT_ALLOCATABLE",
        )

        released = fixtures.qa_disposition_roll_good(roll["id"], "RELEASE")
        assert released["qa_status"] == "PASSED", (
            f"release sets qa_status to PASSED, got {released['qa_status']}"
        )
        assert released["inventory_status"] == "AVAILABLE", (
            f"release moves inventory_status to AVAILABLE, got "
            f"{released['inventory_status']}"
        )

        validate_error(
            _manual_line(api, order_id, roll["id"], 150.0, released["version"]),
            "ERR_ROLL_YARDAGE_INSUFFICIENT",
        )

        line = validate_success(
            _manual_line(api, order_id, roll["id"], 100.0, released["version"]), 201
        )
        assert_cut_allocation(line)
        assert line["status"] == "RESERVED", (
            f"a new manual line begins at RESERVED, got {line['status']}"
        )
        assert line["yards"] == pytest.approx(100.0, abs=0.01)
        assert line["line_cents"] == 427500, (
            f"100.0 yards at 4275 cents with a SOLUTION factor of 1.00 is 427500, "
            f"got {line['line_cents']}"
        )

        order = fixtures.refresh_cut_order(order_id)
        assert order["allocated_yards"] == pytest.approx(100.0, abs=0.01), (
            f"one 100.0-yard line is committed, got {order['allocated_yards']}"
        )
        roll_after = fixtures.refresh_roll_good(roll["id"])
        assert roll_after["available_yards"] == pytest.approx(0.0, abs=0.01)
        assert roll_after["inventory_status"] == "COMMITTED", (
            f"a roll driven to exactly zero available yards flips to COMMITTED, got "
            f"{roll_after['inventory_status']}"
        )


# ---------------------------------------------------------------------------
# The certificate gate crossed with the logical clock
# ---------------------------------------------------------------------------


class TestAllocationGatedOnCertificateAndClock:
    def test_lapsing_the_certificate_refuses_an_otherwise_identical_allocation(
        self, api
    ):
        """The clock reaching expires_at_utc lapses the certificate and suspends the style.

        PRD: "Advancing the logical clock to or past a certificate's
        `expires_at_utc` sets `status` to `LAPSED`, terminal, and the clock response
        lists every certificate so lapsed in `lapsed_certification_ids`."
        PRD: "when the affected style is left with no effective `DOC_FF_1_70`
        certificate, the style transitions `ACTIVE` to `SUSPENDED` and its
        `SCHEDULED` runs are held"

        Design: Difficulty/cross_entity_state_dependency/allocation_gated_on_certification_status_and_logical_clock
        """
        ctx = _certificate_expiring_at_september()
        first = validate_success(
            api.allocate_cut_order(ctx["order_one"]["id"], _PLANNER), 200
        )
        assert first["status"] == "ALLOCATED", (
            f"the effective certificate admits the allocation, got {first['status']}"
        )
        roll = fixtures.refresh_roll_good(ctx["roll_good"]["id"])
        assert roll["available_yards"] == pytest.approx(150.0, abs=0.01), (
            f"200.0 less 50.0 yards leaves 150.0, got {roll['available_yards']}"
        )

        clock = fixtures.set_clock("2026-09-01T00:00:00Z")
        assert ctx["certification"]["id"] in clock["lapsed_certification_ids"], (
            "the clock response must report the certificate it lapsed"
        )
        assert ctx["style"]["id"] in clock["suspended_style_ids"], (
            "the clock response must report the style left without an effective "
            "flammability certificate"
        )
        assert (
            fixtures.refresh_certification(ctx["certification"]["id"])["status"]
            == "LAPSED"
        ), "a certificate whose expiry the clock reached is LAPSED"
        assert fixtures.refresh_style(ctx["style"]["id"])["status"] == "SUSPENDED", (
            "losing the last effective DOC_FF_1_70 certificate suspends the style"
        )

        error = validate_error(
            api.allocate_cut_order(ctx["order_two"]["id"], _PLANNER),
            "ERR_FLAMMABILITY_CERT_REQUIRED",
        )
        assert error["error_id"] != "ERR_STYLE_NOT_ORDERABLE", (
            "the certificate gate is evaluated before style orderability, so the "
            "SUSPENDED style must not decide the error"
        )

        second_order = fixtures.refresh_cut_order(ctx["order_two"]["id"])
        assert second_order["status"] == "SUBMITTED", (
            f"the refused order is untouched, got {second_order['status']}"
        )
        assert (
            fixtures.refresh_cut_order(ctx["order_one"]["id"])["status"] == "ALLOCATED"
        ), "the earlier allocation is not unwound by the lapse"
        roll = fixtures.refresh_roll_good(ctx["roll_good"]["id"])
        assert roll["available_yards"] == pytest.approx(150.0, abs=0.01), (
            f"the refused allocation committed nothing, got {roll['available_yards']}"
        )

    def test_a_fresh_certificate_reopens_allocation_on_the_same_inventory(self, api):
        """Re-certifying the suspended style lets the identical order allocate.

        PRD: "when the style was in `SUSPENDED` and the new certificate is an
        effective `DOC_FF_1_70`, the style transitions `SUSPENDED` to `ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/allocation_gated_on_certification_status_and_logical_clock
        """
        ctx = _certificate_expiring_at_september()
        validate_success(
            api.allocate_cut_order(ctx["order_one"]["id"], _PLANNER), 200
        )
        fixtures.set_clock("2026-09-01T00:00:00Z")
        validate_error(
            api.allocate_cut_order(ctx["order_two"]["id"], _PLANNER),
            "ERR_FLAMMABILITY_CERT_REQUIRED",
        )

        replacement = fixtures.issue_certification(
            ctx["style"]["id"],
            [ctx["product_test"]["id"]],
            cert_type="DOC_FF_1_70",
            expires_at_utc="2027-08-01T00:00:00Z",
        )
        assert replacement["status"] == "ACTIVE", (
            f"the replacement certificate is ACTIVE, got {replacement['status']}"
        )
        assert fixtures.refresh_style(ctx["style"]["id"])["status"] == "ACTIVE", (
            "an effective replacement DOC_FF_1_70 lifts the style out of SUSPENDED"
        )

        third = validate_success(
            api.allocate_cut_order(ctx["order_two"]["id"], _PLANNER), 200
        )
        assert third["status"] == "ALLOCATED", (
            f"the re-certified style admits the allocation, got {third['status']}"
        )
        roll = fixtures.refresh_roll_good(ctx["roll_good"]["id"])
        assert roll["available_yards"] == pytest.approx(100.0, abs=0.01), (
            f"200.0 less two 50.0-yard commitments leaves 100.0, got "
            f"{roll['available_yards']}"
        )


# ---------------------------------------------------------------------------
# The selector's ranking waterfall
# ---------------------------------------------------------------------------


class TestSelectorWaterfall:
    def test_smallest_roll_is_exhausted_before_the_larger_roll_is_touched(self, api):
        """A 130.0-yard order empties the 60.0-yard roll then spills 70.0 onto the 100.0.

        PRD: "Rank first by `is_remnant` descending, so remnant rolls come before
        non-remnant rolls; then by `available_yards` ascending; then by `created_at`
        ascending as the final tie-break."
        PRD: "take from the current roll the lesser of the remaining need and that
        roll's `available_yards`, round it half-up to 1 decimal place, and create one
        line in `RESERVED` for that many `yards` against that roll"

        Design: Corner/calculations/roll_good_selector_takes_the_smallest_roll_first_then_spills
        """
        ctx = _sixty_and_hundred_yard_rolls()
        order_id = ctx["cut_order"]["id"]
        allocated = validate_success(api.allocate_cut_order(order_id, _PLANNER), 200)
        assert allocated["status"] == "ALLOCATED", (
            f"160.0 eligible yards cover the 130.0-yard order, got "
            f"{allocated['status']}"
        )
        assert allocated["allocated_yards"] == pytest.approx(130.0, abs=0.01)

        lines, meta = validate_paginated(
            api.list_cut_allocations(
                _PLANNER, params={"cut_order_id": order_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 2, (
            f"the waterfall spans exactly two rolls, got {meta['total_count']}"
        )

        first, second = lines[0], lines[1]
        assert first["roll_good_id"] == ctx["roll_good"]["id"], (
            "the smallest roll must be drawn first, so the earliest-created line "
            "belongs to the 60.0-yard roll"
        )
        assert first["yards"] == pytest.approx(60.0, abs=0.01), (
            f"the 60.0-yard roll is taken to exhaustion, got {first['yards']}"
        )
        assert first["shade_band"] == "SOLUTION"
        assert first["from_remnant"] is False
        assert first["line_cents"] == 256500, (
            f"60.0 yards at 4275 cents is 256500, got {first['line_cents']}"
        )

        assert second["roll_good_id"] == ctx["roll_b"]["id"], (
            "the larger roll is only touched once the smaller one is exhausted"
        )
        assert second["yards"] == pytest.approx(70.0, abs=0.01), (
            f"the residual need of 130.0 - 60.0 spills onto the larger roll, got "
            f"{second['yards']}"
        )
        assert second["line_cents"] == 299250, (
            f"70.0 yards at 4275 cents is 299250, got {second['line_cents']}"
        )

        small = fixtures.refresh_roll_good(ctx["roll_good"]["id"])
        assert small["available_yards"] == pytest.approx(0.0, abs=0.01)
        assert small["inventory_status"] == "COMMITTED", (
            f"a roll drawn to exactly zero flips AVAILABLE to COMMITTED, got "
            f"{small['inventory_status']}"
        )
        large = fixtures.refresh_roll_good(ctx["roll_b"]["id"])
        assert large["available_yards"] == pytest.approx(30.0, abs=0.01), (
            f"taking the larger roll first would have left 30.0 on the small roll "
            f"instead; got {large['available_yards']} on the large roll"
        )
        assert large["inventory_status"] == "AVAILABLE"

        assert allocated["gross_cents"] == 555750, (
            f"gross must be 256500 + 299250 = 555750, got {allocated['gross_cents']}"
        )
        assert allocated["freight_cents"] == 0
        assert allocated["remnant_credit_cents"] == 0
        assert allocated["net_invoice_cents"] == 555750
        assert_net_invoice(allocated)


# ---------------------------------------------------------------------------
# Custom coverage versus running-line backorder
# ---------------------------------------------------------------------------


class TestCustomCoverageVersusBackorder:
    def test_custom_order_is_refused_while_the_running_line_order_backorders(self, api):
        """40.0 eligible yards refuse a CUSTOM 100.0 but partially fill a RUNNING_LINE 100.0.

        PRD: "If the need is still positive and the order's `order_type` is
        `CUSTOM`, nothing at all is created and the request is refused with
        `ERR_INSUFFICIENT_YARDAGE`"
        PRD: "If the need is still positive and the `order_type` is
        `RUNNING_LINE`, the partial lines are kept and the order transitions to
        `BACKORDERED`."

        Design: Corner/validations/custom_orders_demand_full_coverage_while_running_line_backorders
        """
        ctx = fixtures.setup_available_solution_dyed_roll(
            roll_overrides={"initial_yards": 40.0}
        )
        account = fixtures.create_account()
        custom = fixtures.create_cut_order(
            account["id"],
            ctx["style"]["id"],
            order_code="CO-CUSTOM",
            order_type="CUSTOM",
            requested_yards=100.0,
            shade_tolerance="ANY",
        )
        running_line = fixtures.create_cut_order(
            account["id"],
            ctx["style"]["id"],
            order_code="CO-LINE",
            order_type="RUNNING_LINE",
            requested_yards=100.0,
            shade_tolerance="ANY",
        )

        validate_error(
            api.allocate_cut_order(custom["id"], _PLANNER), "ERR_INSUFFICIENT_YARDAGE"
        )
        refused = fixtures.refresh_cut_order(custom["id"])
        assert refused["status"] == "SUBMITTED", (
            f"a custom order is never partially allocated and never backordered, got "
            f"{refused['status']}"
        )
        assert refused["allocated_yards"] == pytest.approx(0.0, abs=0.01)
        assert fixtures.list_allocations_for_order(custom["id"]) == [], (
            "nothing at all is created for the refused custom order"
        )

        partial = validate_success(
            api.allocate_cut_order(running_line["id"], _PLANNER), 200
        )
        assert partial["status"] == "BACKORDERED", (
            f"a short RUNNING_LINE order keeps its partial lines and backorders, got "
            f"{partial['status']}"
        )
        assert partial["allocated_yards"] == pytest.approx(40.0, abs=0.01)

        lines, meta = validate_paginated(
            api.list_cut_allocations(
                _PLANNER,
                params={
                    "cut_order_id": running_line["id"],
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1, (
            f"the single eligible roll yields one line, got {meta['total_count']}"
        )
        assert lines[0]["yards"] == pytest.approx(40.0, abs=0.01)
        assert lines[0]["line_cents"] == 171000, (
            f"40.0 yards at 4275 cents is 171000, got {lines[0]['line_cents']}"
        )

        roll = fixtures.refresh_roll_good(ctx["roll_good"]["id"])
        assert roll["available_yards"] == pytest.approx(0.0, abs=0.01)
        assert roll["inventory_status"] == "COMMITTED", (
            f"the roll was drawn to exactly zero, got {roll['inventory_status']}"
        )

        style = fixtures.refresh_style(ctx["style"]["id"])
        assert style["open_backorder_yards"] == pytest.approx(160.0, abs=0.01), (
            f"the SUBMITTED custom order contributes 100.0 and the BACKORDERED "
            f"running-line order 60.0, got {style['open_backorder_yards']}"
        )
        assert style["replenishment_flag"] == "NONE", (
            f"160.0 backordered yards stay below the 250-yard alarm, got "
            f"{style['replenishment_flag']}"
        )


# ---------------------------------------------------------------------------
# Immediate visibility of every allocation side effect
# ---------------------------------------------------------------------------


class TestAllocationSideEffectsAreImmediate:
    def test_allocate_response_and_the_next_reads_agree_without_settling(self, api):
        """The allocate response already carries the settled order; roll and account agree.

        PRD: "there is no deferred or eventual settlement anywhere in this system"
        PRD: "is recomputed as part of the same request that changed that data,
        never on read and never on a schedule"

        Design: Corner/consistency_model/allocation_side_effects_are_all_visible_in_the_same_response
        """
        ctx = fixtures.setup_submitted_cut_order(
            order_overrides={"requested_yards": 60.0, "shade_tolerance": "ANY"}
        )
        order_id = ctx["cut_order"]["id"]

        allocated = validate_success(api.allocate_cut_order(order_id, _PLANNER), 200)
        assert_cut_order(allocated)
        assert allocated["status"] == "ALLOCATED", (
            f"the action endpoint itself must return the recomputed order, got "
            f"{allocated['status']}"
        )
        assert allocated["allocated_yards"] == pytest.approx(60.0, abs=0.01)
        assert allocated["gross_cents"] == 256500, (
            f"60.0 yards at 4275 cents is 256500, got {allocated['gross_cents']}"
        )
        assert allocated["freight_cents"] == 0, (
            f"a gross of 256500 clears the freight-free tier, got "
            f"{allocated['freight_cents']}"
        )
        assert allocated["remnant_credit_cents"] == 0
        assert allocated["net_invoice_cents"] == 256500
        assert_net_invoice(allocated)

        lines, meta = validate_paginated(
            api.list_cut_allocations(
                _PLANNER, params={"cut_order_id": order_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 1, (
            f"one roll covers the order, got {meta['total_count']}"
        )
        line = lines[0]
        assert line["status"] == "RESERVED"
        assert line["yards"] == pytest.approx(60.0, abs=0.01)
        assert line["line_cents"] == 256500
        assert line["shade_band"] == "SOLUTION"
        assert line["from_remnant"] is False

        roll = validate_success(api.get_roll_good(ctx["roll_good"]["id"], _QA), 200)
        assert roll["available_yards"] == pytest.approx(140.0, abs=0.01), (
            f"the very next read must already show 200.0 - 60.0 = 140.0, got "
            f"{roll['available_yards']}"
        )
        assert roll["inventory_status"] == "AVAILABLE", (
            f"the roll did not reach zero yards, so it stays AVAILABLE rather than "
            f"COMMITTED, got {roll['inventory_status']}"
        )
        assert roll["qa_status"] == "PASSED"

        account = validate_success(
            api.get_account(ctx["account"]["id"], _PLANNER), 200
        )
        assert account["credit_used_cents"] == 256500, (
            f"the account ledger already counts the order's 60.0 * 4275 = 256500 "
            f"credit hold, got {account['credit_used_cents']}"
        )
        assert account["status"] == "ACTIVE"

        reread = validate_success(api.get_cut_order(order_id, _PLANNER), 200)
        for field in _SETTLED_FIELDS:
            assert reread[field] == allocated[field], (
                f"{field} must not settle late: the allocate response said "
                f"{allocated[field]!r}, the re-read says {reread[field]!r}"
            )

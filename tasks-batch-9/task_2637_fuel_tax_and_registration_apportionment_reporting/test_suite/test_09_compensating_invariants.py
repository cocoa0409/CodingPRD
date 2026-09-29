"""Quantities that must survive being taken apart and put back together.

Two running totals are maintained incrementally and each has an inverse
operation. In both cases the value after the inverse must be the value before
the forward step, to the last decimal place, and the audit trail of the undone
step must remain readable.
"""
import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_CHANGE_REQUEST_NOT_PENDING,
    ERR_INVALID_PURCHASE_STATE,
)
from test_helpers.assertions import (
    assert_apportion_percent,
    assert_application_totals,
    assert_carrier_compliance,
    assert_change_request,
    assert_error_envelope,
    assert_gallons,
    assert_money,
    assert_return_settlement,
    assert_vehicle_dimensions,
    by_code,
    codes_of,
)
from test_helpers.factories import fuel_purchase_payload, leg
from test_helpers.fixtures import (
    accept_trip,
    add_schedule_lines,
    application_version,
    capture_trip,
    carrier_version,
    create_carrier,
    create_vehicle,
    decide_fleet_change,
    disallowed_purchase,
    invoice_application,
    open_application,
    open_return,
    prepare_return,
    read_application,
    read_carrier,
    read_fleet_change,
    read_purchase,
    read_vehicle,
    record_purchase,
    request_fleet_change,
    reverse_fleet_change,
    schedule_lines,
    seed_reference_data,
    submit_application,
)
from test_helpers.test_users import (
    ANALYST_1_HEADERS,
    OFFICER_1_HEADERS,
    OFFICER_2_HEADERS,
    PREPARER_1_HEADERS,
)


@pytest.fixture
def three_purchases_one_of_them_untaxed(client):
    """One carrier's fuel history for Q2-2026, recorded in three steps.

    Two receipted, tax-paid purchases lift the running gallons total to 255.000;
    a third is bulk fuel with no receipt, so it stays `RECORDED` and lifts
    nothing. The snapshots taken after each step are returned so the running
    total can be read as a sequence rather than only at its end.
    """
    seed_reference_data(client)
    carrier = create_carrier(
        client,
        legal_name="Reversible Gallons Fuel Co",
        usdot_number="USDOT-2637160",
        base_jurisdiction_code="IL",
        bond_ceiling_amount=5000.00,
    )
    vehicle = create_vehicle(
        client,
        carrier["id"],
        unit_number="U-1601",
        vin="1FUJA6CK21LA01601",
        factory_price_amount=144000.00,
        registration_year=2026,
    )
    haul = capture_trip(
        client,
        carrier["id"],
        vehicle["id"],
        "2026-04-05T05:00:00Z",
        "2026-04-06T05:00:00Z",
        500000.0,
        501400.0,
        [leg("IL", 1000.0), leg("IN", 400.0)],
    )
    accept_trip(client, haul["id"], headers=OFFICER_1_HEADERS)

    first = record_purchase(
        client,
        carrier["id"],
        vehicle["id"],
        "IL",
        "2026-04-11",
        175.000,
        receipt_reference="RCPT-IL-D1-0411",
    )
    after_first = read_carrier(client, carrier["id"])
    second = record_purchase(
        client,
        carrier["id"],
        vehicle["id"],
        "IN",
        "2026-05-06",
        80.000,
        receipt_reference="RCPT-IN-D1-0506",
    )
    after_second = read_carrier(client, carrier["id"])
    # Bulk fuel drawn from the carrier's own tank: no receipt is carried at all,
    # and the flag says the pump tax was never paid.
    bulk_payload = fuel_purchase_payload(
        carrier["id"],
        vehicle["id"],
        jurisdiction_code="KY",
        purchase_date="2026-06-03",
        gallons=40.000,
        tax_paid_flag=False,
    )
    bulk_payload.pop("receipt_reference")
    third = validate_success(
        client.create_fuel_purchase(bulk_payload, ANALYST_1_HEADERS), expected_status=201
    )
    after_third = read_carrier(client, carrier["id"])
    return {
        "carrier_id": carrier["id"],
        "vehicle_id": vehicle["id"],
        "first_id": first["id"],
        "second_id": second["id"],
        "third_id": third["id"],
        "first": first,
        "second": second,
        "third": third,
        "after_first": after_first,
        "after_second": after_second,
        "after_third": after_third,
    }


class TestTaxPaidGallonsYtdIsRestoredExactlyByADisallow:
    """The carrier's running gallons total is walked up by two purchases and
    walked back down by their disallowance, landing on its earlier value."""

    def test_only_the_receipted_taxed_purchases_lift_the_running_total(
        self, client, three_purchases_one_of_them_untaxed
    ):
        """"A purchase moves `RECORDED → ACCEPTED` at creation time when **both**
        conditions hold: `receipt_reference` is present, and `tax_paid_flag` is
        true. Only `ACCEPTED` purchases ever feed tax-paid gallons." So "the
        carrier's running `tax_paid_gallons_ytd` becomes its prior value plus the
        purchase's `gallons`, rounded to 3 decimal places" twice, and "A purchase
        that stays `RECORDED` leaves both untouched."

        Design: Difficulty/compensating_invariant/carrier_tax_paid_gallons_ytd_restored_exactly_by_purchase_disallow
        """
        ctx = three_purchases_one_of_them_untaxed
        assert ctx["first"]["purchase_status"] == "ACCEPTED", ctx["first"]
        assert ctx["second"]["purchase_status"] == "ACCEPTED", ctx["second"]
        assert ctx["third"]["purchase_status"] == "RECORDED", ctx["third"]

        assert_carrier_compliance(ctx["after_first"], tax_paid_gallons_ytd=175.000)
        assert_carrier_compliance(ctx["after_second"], tax_paid_gallons_ytd=255.000)
        assert_carrier_compliance(ctx["after_third"], tax_paid_gallons_ytd=255.000)
        assert (
            ctx["after_third"]["version"] == ctx["after_second"]["version"]
        ), (ctx["after_second"]["version"], ctx["after_third"]["version"])

    def test_disallowing_the_accepted_purchase_restores_the_earlier_total_exactly(
        self, client, three_purchases_one_of_them_untaxed
    ):
        """"Disallowing an `ACCEPTED` purchase stamps `disallow_reason_code` and
        reduces the carrier's `tax_paid_gallons_ytd` to its prior value minus the
        purchase's `gallons`, rounded to 3 decimal places — restoring, when that
        purchase was the only change, exactly the value the field held before the
        purchase existed." 255.000 less 80.000 is the 175.000 that stood before
        the Indiana receipt was recorded, and "Both paths increment the carrier's
        `version` by 1."

        Design: Difficulty/compensating_invariant/carrier_tax_paid_gallons_ytd_restored_exactly_by_purchase_disallow
        """
        ctx = three_purchases_one_of_them_untaxed
        version_before = carrier_version(client, ctx["carrier_id"])

        disallowed = disallowed_purchase(client, ctx["second_id"], "MISSING_RECEIPT")
        assert disallowed["purchase_status"] == "DISALLOWED", disallowed
        assert disallowed["disallow_reason_code"] == "MISSING_RECEIPT", disallowed

        carrier = read_carrier(client, ctx["carrier_id"])
        assert_carrier_compliance(carrier, tax_paid_gallons_ytd=175.000)
        assert_gallons(
            carrier["tax_paid_gallons_ytd"],
            ctx["after_first"]["tax_paid_gallons_ytd"],
            "restored tax_paid_gallons_ytd",
        )
        assert carrier["version"] == version_before + 1, carrier["version"]

        untouched = read_purchase(client, ctx["first_id"])
        assert untouched["purchase_status"] == "ACCEPTED", untouched
        assert untouched["disallow_reason_code"] is None, untouched

    def test_disallowing_the_purchase_that_never_counted_moves_no_gallons(
        self, client, three_purchases_one_of_them_untaxed
    ):
        """"Disallowing a `RECORDED` purchase stamps `disallow_reason_code` and
        leaves `tax_paid_gallons_ytd` untouched, because a `RECORDED` purchase's
        gallons were never counted in the first place. Both paths increment the
        carrier's `version` by 1." The forty bulk gallons therefore leave the
        total at the value the previous disallowance restored it to.

        Design: Difficulty/compensating_invariant/carrier_tax_paid_gallons_ytd_restored_exactly_by_purchase_disallow
        """
        ctx = three_purchases_one_of_them_untaxed
        disallowed_purchase(client, ctx["second_id"], "MISSING_RECEIPT")
        version_before = carrier_version(client, ctx["carrier_id"])

        disallowed = disallowed_purchase(client, ctx["third_id"], "BULK_UNTAXED")
        assert disallowed["purchase_status"] == "DISALLOWED", disallowed
        assert disallowed["disallow_reason_code"] == "BULK_UNTAXED", disallowed

        carrier = read_carrier(client, ctx["carrier_id"])
        assert_carrier_compliance(carrier, tax_paid_gallons_ytd=175.000)
        assert carrier["version"] == version_before + 1, carrier["version"]

    def test_the_terminal_status_refuses_a_second_disallowance(
        self, client, three_purchases_one_of_them_untaxed
    ):
        """"Disallowance is reachable from `ACCEPTED` and from `RECORDED` alike
        and lands on the terminal `DISALLOWED`; a purchase that is already
        `DISALLOWED` cannot be disallowed again, and the attempt is refused with
        `ERR_INVALID_PURCHASE_STATE`." Were the second attempt to succeed it
        would subtract the same eighty gallons twice, so the refusal is what keeps
        the total conserved.

        Design: Difficulty/compensating_invariant/carrier_tax_paid_gallons_ytd_restored_exactly_by_purchase_disallow
        """
        ctx = three_purchases_one_of_them_untaxed
        disallowed_purchase(client, ctx["second_id"], "MISSING_RECEIPT")
        version_before = carrier_version(client, ctx["carrier_id"])

        response = client.disallow_fuel_purchase(
            ctx["second_id"], ANALYST_1_HEADERS, disallow_reason_code="DUPLICATE"
        )
        validate_error(response, ERR_INVALID_PURCHASE_STATE)
        assert_error_envelope(response, ERR_INVALID_PURCHASE_STATE)

        carrier = read_carrier(client, ctx["carrier_id"])
        assert_carrier_compliance(carrier, tax_paid_gallons_ytd=175.000)
        assert carrier["version"] == version_before, carrier["version"]

        unchanged = read_purchase(client, ctx["second_id"])
        assert unchanged["disallow_reason_code"] == "MISSING_RECEIPT", unchanged

    def test_the_quarter_settles_on_the_restored_total_and_nothing_else(
        self, client, three_purchases_one_of_them_untaxed
    ):
        """"`tax_paid_gallons` on the line is the sum of `gallons` over the
        carrier's purchases whose `jurisdiction_code` is that jurisdiction, whose
        `purchase_status` is `ACCEPTED`, and whose `purchase_date` falls inside
        the quarter window ... `RECORDED` and `DISALLOWED` purchases contribute
        zero." With both later purchases disallowed, "The return's
        `total_tax_paid_gallons` is the sum of the per-jurisdiction figures" is the
        surviving 175.000, and 1400.0 fleet miles over it is a `fleet_mpg` of
        8.00.

        Design: Difficulty/compensating_invariant/carrier_tax_paid_gallons_ytd_restored_exactly_by_purchase_disallow
        """
        ctx = three_purchases_one_of_them_untaxed
        disallowed_purchase(client, ctx["second_id"], "MISSING_RECEIPT")
        disallowed_purchase(client, ctx["third_id"], "BULK_UNTAXED")

        opened = open_return(client, ctx["carrier_id"], 2026, 2, headers=PREPARER_1_HEADERS)
        prepared = prepare_return(
            client, opened["id"], ctx["carrier_id"], headers=PREPARER_1_HEADERS
        )
        assert_return_settlement(
            prepared,
            return_status="PREPARED",
            settlement_basis="PREPARER_BASIS",
            total_fleet_miles=1400.0,
            total_tax_paid_gallons=175.000,
            fleet_mpg=8.00,
        )


@pytest.fixture
def invoiced_application_with_a_pending_addition(client):
    """A 2026 registration priced for two units, with a third unit enrolled after
    the percentages were frozen and a mid-year addition awaiting a decision.

    The actual-basis schedule reported IL 60000.0 / IN 25000.0 / KY 15000.0, so
    the frozen mix is 0.600000 / 0.250000 / 0.150000 and the per-vehicle full-year
    fee is 2308.50 against the W80 chart. The supplement is effective 2026-07-15.
    """
    seed_reference_data(client)
    carrier = create_carrier(
        client,
        legal_name="Exact Restore Registration Inc",
        usdot_number="USDOT-2637170",
        base_jurisdiction_code="IL",
        bond_ceiling_amount=9000.00,
    )
    plated = [
        create_vehicle(
            client,
            carrier["id"],
            unit_number=unit_number,
            vin=vin,
            factory_price_amount=162000.00,
            registration_year=2026,
        )
        for unit_number, vin in (
            ("U-1701", "1FUJA6CK21LA01701"),
            ("U-1702", "1FUJA6CK21LA01702"),
        )
    ]
    application = open_application(
        client,
        carrier["id"],
        registration_year=2026,
        distance_basis="ACTUAL_DISTANCE_BASIS",
        headers=PREPARER_1_HEADERS,
    )
    add_schedule_lines(
        client,
        application["id"],
        [("IL", 60000.0), ("IN", 25000.0), ("KY", 15000.0)],
        headers=PREPARER_1_HEADERS,
    )
    submit_application(client, application["id"], headers=PREPARER_1_HEADERS)
    invoiced = invoice_application(client, application["id"], headers=OFFICER_1_HEADERS)

    late_arrival = create_vehicle(
        client,
        carrier["id"],
        unit_number="U-1703",
        vin="1FUJA6CK21LA01703",
        factory_price_amount=162000.00,
        registration_year=2026,
    )
    change = request_fleet_change(
        client,
        application["id"],
        late_arrival["id"],
        "ADDITION",
        "2026-07-15",
        headers=PREPARER_1_HEADERS,
    )
    return {
        "carrier_id": carrier["id"],
        "application_id": application["id"],
        "invoiced": invoiced,
        "plated_ids": [vehicle["id"] for vehicle in plated],
        "late_arrival_id": late_arrival["id"],
        "change_id": change["id"],
        "change": change,
    }


class TestApportionedFeeIsRestoredExactlyByAReversal:
    """The application's fee total is recomputed from the whole approved set, so
    undoing the only approval must land back on the invoiced figure."""

    def test_the_invoiced_baseline_prices_exactly_the_two_frozen_units(
        self, client, invoiced_application_with_a_pending_addition
    ):
        """"Each line's `jurisdiction_fee_amount` is its `apportion_percent`
        multiplied by the `annual_fee_amount` of the `WeightGroupFee` cell for that
        line's `jurisdiction_code` paired with the application's
        `weight_group_code`, multiplied again by the application's
        `apportioned_vehicle_count`, rounded to 2 decimal places. The application's
        `base_fee_total` is the sum of those already-rounded per-line fees, and at
        invoicing time — before any supplement exists — `total_apportioned_fee`
        equals `base_fee_total`." The unit enrolled afterwards was not caught by
        the invoicing cascade, so it is still waiting.

        Design: Difficulty/compensating_invariant/application_total_apportioned_fee_restored_exactly_by_approve_reverse
        """
        ctx = invoiced_application_with_a_pending_addition
        assert_application_totals(
            ctx["invoiced"],
            application_status="INVOICED",
            apportioned_vehicle_count=2,
            fleet_total_distance_miles=100000.0,
            base_fee_total=4617.00,
            total_apportioned_fee=4617.00,
        )
        lines = schedule_lines(client, ctx["application_id"], line_status="ACTIVE")
        assert codes_of(lines) == ["IL", "IN", "KY"], codes_of(lines)
        for code, percent, fee in (
            ("IL", 0.600000, 3348.00),
            ("IN", 0.250000, 846.00),
            ("KY", 0.150000, 423.00),
        ):
            line = by_code(lines, code)
            assert_apportion_percent(line["apportion_percent"], percent, f"{code} percent")
            assert_money(line["jurisdiction_fee_amount"], fee, f"{code} fee")

        assert_vehicle_dimensions(
            read_vehicle(client, ctx["late_arrival_id"]),
            vehicle_status="PENDING",
            activated_on_date=None,
        )
        assert_change_request(
            ctx["change"],
            change_status="REQUESTED",
            prorate_months=0,
            fee_delta=0.00,
            decided_by_user_id=None,
            reversal_reason_code=None,
        )

    def test_approval_charges_six_prorated_months_over_the_invoiced_total(
        self, client, invoiced_application_with_a_pending_addition
    ):
        """"For an `ADDITION`, the month of entry is charged, so `prorate_months`
        is thirteen minus the month number ... and `fee_delta` is the per-vehicle
        full-year fee multiplied by `prorate_months`, divided by twelve, rounded to
        2 decimal places." July is month seven, so six months of the 2308.50
        per-vehicle fee is 1154.25, and "The application's `total_apportioned_fee`
        becomes its `base_fee_total` plus the sum of `fee_delta` over all of that
        application's supplements whose `change_status` is `APPROVED`, rounded to
        2 decimal places — a conserved quantity recomputed from the whole approved
        set rather than nudged incrementally."

        Design: Difficulty/compensating_invariant/application_total_apportioned_fee_restored_exactly_by_approve_reverse
        """
        ctx = invoiced_application_with_a_pending_addition
        approved = decide_fleet_change(
            client, ctx["change_id"], "APPROVE", headers=OFFICER_2_HEADERS
        )
        assert_change_request(
            approved,
            change_status="APPROVED",
            prorate_months=6,
            fee_delta=1154.25,
            decided_by_user_id="officer-2",
        )
        assert_application_totals(
            read_application(client, ctx["application_id"]),
            application_status="INVOICED",
            apportioned_vehicle_count=3,
            base_fee_total=4617.00,
            total_apportioned_fee=5771.25,
        )
        assert_vehicle_dimensions(
            read_vehicle(client, ctx["late_arrival_id"]),
            vehicle_status="ACTIVE",
            activated_on_date="2026-07-15",
        )

    def test_reversal_returns_the_total_and_the_count_to_their_earlier_values(
        self, client, invoiced_application_with_a_pending_addition
    ):
        """"The row's `fee_delta` is **retained** as an audit trail but stops
        counting as approved and is never re-added, so the application's
        `total_apportioned_fee` is recomputed as `base_fee_total` plus the sum of
        `fee_delta` over the remaining `APPROVED` supplements, rounded to 2 decimal
        places, returning to exactly the value it held before this approval;
        `apportioned_vehicle_count` is likewise restored to its pre-approval
        value; and the application's `version` increments by 1." And "a reversed
        `ADDITION` moves its unit `ACTIVE → PENDING` and clears
        `activated_on_date` back to null, and a reversed `DELETION` moves its unit
        `DELETED → ACTIVE`."

        Design: Difficulty/compensating_invariant/application_total_apportioned_fee_restored_exactly_by_approve_reverse
        """
        ctx = invoiced_application_with_a_pending_addition
        decide_fleet_change(client, ctx["change_id"], "APPROVE", headers=OFFICER_2_HEADERS)
        assert_application_totals(
            read_application(client, ctx["application_id"]), total_apportioned_fee=5771.25
        )

        reverse_fleet_change(
            client, ctx["change_id"], "VEHICLE_NOT_DELIVERED", headers=OFFICER_2_HEADERS
        )
        restored = read_application(client, ctx["application_id"])
        assert_application_totals(
            restored,
            application_status="INVOICED",
            apportioned_vehicle_count=2,
            total_apportioned_fee=4617.00,
        )
        assert_money(
            restored["total_apportioned_fee"],
            ctx["invoiced"]["total_apportioned_fee"],
            "total_apportioned_fee after the reversal",
        )
        assert_vehicle_dimensions(
            read_vehicle(client, ctx["late_arrival_id"]),
            vehicle_status="PENDING",
            activated_on_date=None,
        )

    def test_the_reversed_supplement_keeps_its_delta_as_an_audit_trail(
        self, client, invoiced_application_with_a_pending_addition
    ):
        """"The row's `fee_delta` is **retained** as an audit trail but stops
        counting as approved and is never re-added, so the application's
        `total_apportioned_fee` is recomputed as `base_fee_total` plus the sum of
        `fee_delta` over the remaining `APPROVED` supplements, rounded to 2 decimal
        places, returning to exactly the value it held before this approval;
        `apportioned_vehicle_count` is likewise restored to its pre-approval
        value; and the application's `version` increments by 1." The
        pricing survives on the
        reversed row even though the application no longer carries it, and since
        "The application's `version` increments by 1" on the approval and again on
        the reversal, the round trip is two visible writes rather than a silent
        rewrite. "Note that the frozen `apportion_percent` values and
        `base_fee_total` are untouched — only `total_apportioned_fee` and the
        vehicle count move."

        Design: Difficulty/compensating_invariant/application_total_apportioned_fee_restored_exactly_by_approve_reverse
        """
        ctx = invoiced_application_with_a_pending_addition
        version_before = application_version(client, ctx["application_id"])

        decide_fleet_change(client, ctx["change_id"], "APPROVE", headers=OFFICER_2_HEADERS)
        reverse_fleet_change(
            client, ctx["change_id"], "CLERICAL_ERROR", headers=OFFICER_2_HEADERS
        )

        reversed_row = read_fleet_change(client, ctx["change_id"])
        assert_change_request(
            reversed_row,
            change_status="REVERSED",
            prorate_months=6,
            fee_delta=1154.25,
            reversal_reason_code="CLERICAL_ERROR",
            decided_by_user_id="officer-2",
        )
        application = read_application(client, ctx["application_id"])
        assert application["version"] == version_before + 2, application["version"]
        assert_application_totals(
            application, base_fee_total=4617.00, total_apportioned_fee=4617.00
        )
        lines = schedule_lines(client, ctx["application_id"], line_status="ACTIVE")
        for code, percent, fee in (
            ("IL", 0.600000, 3348.00),
            ("IN", 0.250000, 846.00),
            ("KY", 0.150000, 423.00),
        ):
            line = by_code(lines, code)
            assert_apportion_percent(line["apportion_percent"], percent, f"{code} percent")
            assert_money(line["jurisdiction_fee_amount"], fee, f"{code} fee")

    def test_a_second_reversal_is_refused_so_the_total_cannot_drift(
        self, client, invoiced_application_with_a_pending_addition
    ):
        """"Reversal requires `change_status` to be `APPROVED`, and a reversal
        aimed at a request in any other status is refused with
        `ERR_CHANGE_REQUEST_NOT_PENDING`." The terminal `REVERSED` status is what
        stops a second undo from being applied to a total that has already been
        restored.

        Design: Difficulty/compensating_invariant/application_total_apportioned_fee_restored_exactly_by_approve_reverse
        """
        ctx = invoiced_application_with_a_pending_addition
        decide_fleet_change(client, ctx["change_id"], "APPROVE", headers=OFFICER_2_HEADERS)
        reverse_fleet_change(
            client, ctx["change_id"], "CLERICAL_ERROR", headers=OFFICER_2_HEADERS
        )
        version_before = application_version(client, ctx["application_id"])

        response = client.reverse_fleet_change_request(
            ctx["change_id"], OFFICER_2_HEADERS, reversal_reason_code="JURISDICTION_REJECTION"
        )
        validate_error(response, ERR_CHANGE_REQUEST_NOT_PENDING)

        application = read_application(client, ctx["application_id"])
        assert_application_totals(
            application, apportioned_vehicle_count=2, total_apportioned_fee=4617.00
        )
        assert application["version"] == version_before, application["version"]
        assert_change_request(
            read_fleet_change(client, ctx["change_id"]),
            change_status="REVERSED",
            reversal_reason_code="CLERICAL_ERROR",
        )

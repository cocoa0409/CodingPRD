"""Concurrency tokens on shared baselines, and the immediacy of a cascade.

Two of these tests drive the only two version-bearing writes in the system --
filing a supplement against an application, and preparing a return against a
carrier -- and drive them in the one situation where the state machine has no
objection at all, so that the refusal can only be about the token. The third
checks that a cascade's results are already in the triggering response, with no
second read required to see them.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_STALE_APPLICATION_VERSION,
    ERR_STALE_CARRIER_VERSION,
)
from test_helpers.assertions import (
    assert_apportion_percent,
    assert_application_totals,
    assert_change_request,
    assert_jurisdiction_line,
    assert_money,
    assert_return_settlement,
    assert_vehicle_dimensions,
)
from test_helpers.constants import JURISDICTION_IL, JURISDICTION_IN
from test_helpers.factories import fleet_change_request_payload, leg
from test_helpers.fixtures import (
    accept_trip,
    add_schedule_lines,
    application_version,
    capture_trip,
    carrier_version,
    create_carrier,
    create_vehicle,
    invoice_application,
    invoiced_application,
    open_application,
    open_return,
    read_application,
    read_carrier,
    read_return,
    read_vehicle,
    record_purchase,
    request_fleet_change,
    seed_jurisdictions,
    seed_reference_data_il_in_only,
    set_clock,
    submit_application,
)
from test_helpers.test_users import OFFICER_1_HEADERS, PREPARER_1_HEADERS


def _prairie(client):
    """The Illinois licensee behind every scenario in this file."""
    return create_carrier(
        client,
        legal_name="Prairie Freight LLC",
        usdot_number="USDOT-2637001",
        base_jurisdiction_code="IL",
    )


def _unit(client, carrier_id, unit_number, vin, price):
    return create_vehicle(
        client,
        carrier_id,
        unit_number=unit_number,
        vin=vin,
        factory_price_amount=price,
        registration_year=2026,
    )


class TestTwoSupplementsFiledBackToBackCollideOnTheApplicationVersion:
    def test_the_second_create_replaying_the_first_snapshot_is_refused(self, client):
        """"A `POST /apportionment/fleet-change-requests` request must carry
        `expected_registration_application_version` holding the client's last
        observed `version` of the target `RegistrationApplication`."

        Nothing about this pair of supplements is illegitimate: "Nothing in the
        state machine blocks a second supplement — a carrier may legitimately
        file any number of mid-year supplements against one invoiced
        application, and the second create would succeed on its own terms." The
        collision is purely a concurrency one, because "Filing a supplement
        itself increments the parent application's `version` by 1, which is why
        two supplements filed back to back require the second requester to
        re-read the application." So the client that read the application once
        and then filed twice against that single reading is refused the second
        time -- "It is refused solely because the application's fee basis,
        `total_apportioned_fee` and `apportioned_vehicle_count`, has advanced
        past the snapshot the requester priced its supplement against."

        The refusal is also barren: after it, exactly one supplement exists for
        the application. Re-reading the version -- one higher than the snapshot,
        and no more than that, since only the first create moved it -- and
        replaying the identical body succeeds, and the two supplements then sit
        side by side awaiting a decision. Neither has priced anything yet, since
        "A newly filed supplement opens with `change_status` `REQUESTED`,
        `fee_delta` at 0.00, `prorate_months` at 0, `decided_by_user_id` and
        `reversal_reason_code` null, and `requested_by_user_id` stamped from the
        caller's `X-User-ID`" -- so the invoiced fee basis of 2350.80 for one
        apportioned unit is exactly where invoicing left it.

        Design: Corner/cross_cutting_complexity_layers/a_fleet_change_create_with_a_stale_application_version_is_rejected
        """
        seed_reference_data_il_in_only(client)
        carrier = _prairie(client)
        _unit(client, carrier["id"], "U-101", "1FUJA6CK21L101101", 145000.00)
        application = invoiced_application(
            client, carrier["id"], [("IL", 60000.0), ("IN", 40000.0)]
        )
        assert_application_totals(
            application,
            application_status="INVOICED",
            apportioned_vehicle_count=1,
            fleet_total_distance_miles=100000.0,
            base_fee_total=2350.80,
            total_apportioned_fee=2350.80,
        )

        second_unit = _unit(
            client, carrier["id"], "U-102", "1FUJA6CK21L101102", 152000.00
        )
        third_unit = _unit(
            client, carrier["id"], "U-103", "1FUJA6CK21L101103", 149000.00
        )
        assert_vehicle_dimensions(second_unit, vehicle_status="PENDING")
        assert_vehicle_dimensions(third_unit, vehicle_status="PENDING")

        snapshot = application_version(client, application["id"])
        first_supplement = request_fleet_change(
            client,
            application["id"],
            second_unit["id"],
            "ADDITION",
            "2026-07-15",
            expected_version=snapshot,
        )
        assert_change_request(
            first_supplement,
            change_status="REQUESTED",
            prorate_months=0,
            fee_delta=0.00,
            decided_by_user_id=None,
        )

        validate_error(
            client.create_fleet_change_request(
                fleet_change_request_payload(
                    application["id"],
                    third_unit["id"],
                    "ADDITION",
                    "2026-08-15",
                    snapshot,
                ),
                PREPARER_1_HEADERS,
            ),
            ERR_STALE_APPLICATION_VERSION,
            412,
        )
        filed, filed_meta = validate_paginated(
            client.list_fleet_change_requests(
                PREPARER_1_HEADERS,
                params={"registration_application_id": application["id"]},
            )
        )
        assert filed_meta["total_count"] == 1
        assert filed[0]["id"] == first_supplement["id"]

        fresh = application_version(client, application["id"])
        assert fresh == snapshot + 1
        second_supplement = request_fleet_change(
            client,
            application["id"],
            third_unit["id"],
            "ADDITION",
            "2026-08-15",
            expected_version=fresh,
        )
        assert second_supplement["vehicle_id"] == third_unit["id"]
        assert_change_request(
            second_supplement,
            change_status="REQUESTED",
            prorate_months=0,
            fee_delta=0.00,
            decided_by_user_id=None,
        )

        pending, pending_meta = validate_paginated(
            client.list_fleet_change_requests(
                PREPARER_1_HEADERS,
                params={
                    "registration_application_id": application["id"],
                    "change_status": "REQUESTED",
                },
            )
        )
        assert pending_meta["total_count"] == 2
        assert {row["id"] for row in pending} == {
            first_supplement["id"],
            second_supplement["id"],
        }
        for row in pending:
            assert_change_request(row, prorate_months=0, fee_delta=0.00)

        assert_application_totals(
            read_application(client, application["id"]),
            application_status="INVOICED",
            apportioned_vehicle_count=1,
            base_fee_total=2350.80,
            total_apportioned_fee=2350.80,
        )


class TestASecondPrepareCollidesOnTheCarrierVersion:
    def test_replaying_the_first_token_is_refused_and_voids_nothing(self, client):
        """"A `POST /apportionment/fuel-tax-returns/{id}/prepare` request must
        carry `expected_carrier_version` holding the client's last observed
        `version` of the return's `Carrier`."

        Recomputing a settlement is not an abuse of the endpoint -- "Re-preparation
        is an ordinary product operation here — a `PREPARED` return may be
        recomputed and legitimately supersede its prior jurisdiction line set, so
        the state machine permits it and a second sequential prepare would
        otherwise succeed." What defeats the replay is the first prepare's own
        side effect on the carrier: "the carrier's `latest_prepared_fleet_mpg` is
        set to the newly computed `fleet_mpg`, and the carrier's `version`
        increments by 1 — which is precisely why a second prepare needs a freshly
        read `expected_carrier_version`." The token the preparer held was spent by
        the very call that computed the figures, so "It is refused because the
        carrier record backing the settlement — `ifta_license_status`,
        `latest_prepared_fleet_mpg`, `unsubstantiated_mileage_ratio`,
        `audit_flag` — has advanced past the version the preparer observed."

        The quarter is arranged so the settlement has substance on both sides of
        the line: 400 fleet miles against 40.000 gallons is a fleet MPG of
        exactly 10.00, Illinois shows 300 miles and bought all forty gallons so
        it is owed a refund of 6.27, and Indiana shows 100 miles and bought
        nothing so it is owed 3.30 of base tax plus a 5.50 surcharge, since "The
        surcharge is assessed on full taxable gallons and is **never** offset by
        `tax_paid_gallons`, because surcharge fuel tax is not collected at the
        pump — the carrier owes it in full on every gallon it burned in that
        jurisdiction regardless of where it bought fuel." That is 2.53 net across
        the quarter.

        The point of interest after the refusal is what did not happen to that
        line set. Preparation voids and replaces, so a prepare that got as far as
        touching the lines would be visible as voided rows, since "Voided rows
        remain readable through the corresponding line-listing endpoint, which is
        the only channel through which cascade results are observable." The
        refused call leaves two lines in total and both still `ACTIVE`. Only the
        genuine re-prepare against the fresh token produces the void-and-replace,
        after which four rows exist -- two voided, two active -- and the totals
        are unchanged, because nothing about the underlying evidence moved.

        Design: Corner/cross_cutting_complexity_layers/a_second_sequential_prepare_with_a_stale_carrier_version_is_rejected
        """
        set_clock(client)
        seed_jurisdictions(client, [JURISDICTION_IL, JURISDICTION_IN])
        carrier = _prairie(client)
        vehicle = _unit(client, carrier["id"], "U-101", "1FUJA6CK21L101101", 145000.00)

        trip = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            "2026-04-05T06:00:00Z",
            "2026-04-05T18:00:00Z",
            1000.0,
            1400.0,
            [leg("IL", 300.0), leg("IN", 100.0)],
        )
        accept_trip(client, trip["id"])
        record_purchase(
            client,
            carrier["id"],
            vehicle["id"],
            "IL",
            "2026-05-02",
            40.000,
            receipt_reference="RCPT-IL-4471",
        )
        opened = open_return(client, carrier["id"], filing_year=2026, filing_quarter=2)

        snapshot = carrier_version(client, carrier["id"])
        first = validate_success(
            client.prepare_fuel_tax_return(
                opened["id"], PREPARER_1_HEADERS, expected_carrier_version=snapshot
            )
        )
        assert_return_settlement(
            first,
            return_status="PREPARED",
            settlement_basis="PREPARER_BASIS",
            total_fleet_miles=400.0,
            total_tax_paid_gallons=40.000,
            fleet_mpg=10.00,
            reconstructed_mileage_ratio=0.0000,
            total_net_tax_due=2.53,
            reconstruction_penalty_amount=0.00,
            total_amount_due=2.53,
        )
        assert_money(
            read_carrier(client, carrier["id"])["latest_prepared_fleet_mpg"],
            10.00,
            "latest_prepared_fleet_mpg",
        )

        validate_error(
            client.prepare_fuel_tax_return(
                opened["id"], PREPARER_1_HEADERS, expected_carrier_version=snapshot
            ),
            ERR_STALE_CARRIER_VERSION,
            412,
        )
        fresh = carrier_version(client, carrier["id"])
        assert fresh == snapshot + 1

        assert_return_settlement(
            read_return(client, opened["id"]),
            return_status="PREPARED",
            settlement_basis="PREPARER_BASIS",
            fleet_mpg=10.00,
            total_net_tax_due=2.53,
            total_amount_due=2.53,
        )
        surviving, surviving_meta = validate_paginated(
            client.list_return_jurisdiction_lines(
                opened["id"], PREPARER_1_HEADERS, params={"line_status": "ACTIVE"}
            )
        )
        assert surviving_meta["total_count"] == 2
        everything, everything_meta = validate_paginated(
            client.list_return_jurisdiction_lines(opened["id"], PREPARER_1_HEADERS)
        )
        assert everything_meta["total_count"] == 2
        assert {row["line_status"] for row in everything} == {"ACTIVE"}

        by_jurisdiction = {row["jurisdiction_code"]: row for row in surviving}
        assert_jurisdiction_line(
            by_jurisdiction["IL"],
            taxable_miles=300.0,
            taxable_gallons=30.000,
            tax_paid_gallons=40.000,
            net_taxable_gallons=-10.000,
            base_tax_amount=-6.27,
            surcharge_amount=0.00,
            net_tax_amount=-6.27,
        )
        assert_jurisdiction_line(
            by_jurisdiction["IN"],
            taxable_miles=100.0,
            taxable_gallons=10.000,
            tax_paid_gallons=0.000,
            net_taxable_gallons=10.000,
            base_tax_amount=3.30,
            surcharge_amount=5.50,
            net_tax_amount=8.80,
        )

        replayed = validate_success(
            client.prepare_fuel_tax_return(
                opened["id"], PREPARER_1_HEADERS, expected_carrier_version=fresh
            )
        )
        assert_return_settlement(
            replayed,
            return_status="PREPARED",
            settlement_basis="PREPARER_BASIS",
            total_fleet_miles=400.0,
            fleet_mpg=10.00,
            total_net_tax_due=2.53,
            total_amount_due=2.53,
        )
        after, after_meta = validate_paginated(
            client.list_return_jurisdiction_lines(opened["id"], PREPARER_1_HEADERS)
        )
        assert after_meta["total_count"] == 4
        statuses = [row["line_status"] for row in after]
        assert statuses.count("ACTIVE") == 2
        assert statuses.count("VOIDED") == 2


class TestAnInvoiceCascadeIsSettledBeforeItsResponseIsWritten:
    def test_the_invoice_body_already_carries_the_whole_cascade(self, client):
        """"Cascades in this system run transitively and are immediate: every hop
        completes inside the request that triggered the first hop, and the
        response reflects the settled end state."

        Invoicing is the widest cascade on the registration side: it prices every
        schedule line, totals the application, and reaches out across the fleet
        -- "And a cascade runs across the fleet: every power unit of the carrier
        for the application's `registration_year` whose `vehicle_status` is
        `PENDING` transitions `PENDING → ACTIVE`, with `activated_on_date`
        stamped from the logical-clock date." Everything asserted here is read
        out of the INVOICE response itself, not out of a follow-up request: two
        apportioned units, a hundred thousand fleet miles, and a base fee of
        4701.60.

        That fee is the count-multiplied one: "Each line's
        `jurisdiction_fee_amount` is its `apportion_percent` multiplied by the
        `annual_fee_amount` of the `WeightGroupFee` cell for that line's
        `jurisdiction_code` paired with the application's `weight_group_code`,
        multiplied again by the application's `apportioned_vehicle_count`,
        rounded to 2 decimal places." Sixty per cent of Illinois' 2790.00 across
        two units is 3348.00 and forty per cent of Indiana's 1692.00 across two
        units is 1353.60, and those two already-rounded figures are what
        "`base_fee_total` is the sum of those already-rounded per-line fees, and
        at invoicing time — before any supplement exists — `total_apportioned_fee`
        equals `base_fee_total`" adds up to.

        The per-line figures need their own channel, since "The schedule read is
        the only channel through which computed percentages and per-jurisdiction
        fees become observable, and it accepts a `line_status` filter so that
        voided rounds remain inspectable." -- but they too are final the instant
        the invoice returns. A re-read of the application afterwards is
        byte-identical to the invoice response, down to the version: no hop was
        left running behind the reply.

        Design: Corner/consistency_model/cascade_results_are_visible_in_the_triggering_response_without_a_re_read
        """
        seed_reference_data_il_in_only(client)
        carrier = _prairie(client)
        first_unit = _unit(
            client, carrier["id"], "U-101", "1FUJA6CK21L101101", 145000.00
        )
        second_unit = _unit(
            client, carrier["id"], "U-102", "1FUJA6CK21L101102", 152000.00
        )

        application = open_application(client, carrier["id"], registration_year=2026)
        created_lines = add_schedule_lines(
            client, application["id"], [("IL", 60000.0), ("IN", 40000.0)]
        )
        assert [line["apportion_percent"] for line in created_lines] == [0.0, 0.0]
        submit_application(client, application["id"])

        invoiced = invoice_application(client, application["id"])
        assert_application_totals(
            invoiced,
            application_status="INVOICED",
            apportioned_vehicle_count=2,
            fleet_total_distance_miles=100000.0,
            base_fee_total=4701.60,
            total_apportioned_fee=4701.60,
        )
        assert invoiced["apportion_frozen_at"] is not None

        activated, activated_meta = validate_paginated(
            client.list_vehicles(
                OFFICER_1_HEADERS,
                params={"carrier_id": carrier["id"], "vehicle_status": "ACTIVE"},
            )
        )
        assert activated_meta["total_count"] == 2
        assert {row["id"] for row in activated} == {
            first_unit["id"],
            second_unit["id"],
        }
        for row in activated:
            assert_vehicle_dimensions(
                row, vehicle_status="ACTIVE", activated_on_date="2026-08-01"
            )
        assert_vehicle_dimensions(
            read_vehicle(client, first_unit["id"]),
            vehicle_status="ACTIVE",
            activated_on_date="2026-08-01",
        )

        priced, priced_meta = validate_paginated(
            client.list_distance_schedule_lines(
                application["id"], PREPARER_1_HEADERS, params={"line_status": "ACTIVE"}
            )
        )
        assert priced_meta["total_count"] == 2
        by_jurisdiction = {row["jurisdiction_code"]: row for row in priced}
        assert_apportion_percent(by_jurisdiction["IL"]["apportion_percent"], 0.600000)
        assert_money(
            by_jurisdiction["IL"]["jurisdiction_fee_amount"],
            3348.00,
            "IL jurisdiction_fee_amount",
        )
        assert_apportion_percent(by_jurisdiction["IN"]["apportion_percent"], 0.400000)
        assert_money(
            by_jurisdiction["IN"]["jurisdiction_fee_amount"],
            1353.60,
            "IN jurisdiction_fee_amount",
        )

        assert read_application(client, application["id"]) == invoiced

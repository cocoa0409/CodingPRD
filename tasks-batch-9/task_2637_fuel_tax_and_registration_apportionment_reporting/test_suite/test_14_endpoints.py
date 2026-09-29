"""The surfaces themselves: what each one accepts, and what it makes visible.

Several of these endpoints are the *only* window onto a computation -- a voided
line set, a freshly minted credential, a frozen percentage. Each test below
drives one such surface and reads the result back through the channel the
specification nominates, rather than through the parent's summary fields.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_CREDENTIAL_NOT_ISSUED,
    ERR_JURISDICTION_NOT_DECLARED,
    ERR_REGISTRATION_APPLICATION_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_apportion_percent,
    assert_application_totals,
    assert_credential_state,
    assert_jurisdiction_line,
    assert_miles,
    assert_money,
    assert_return_settlement,
    assert_version_is,
    by_code,
    codes_of,
)
from test_helpers.factories import leg
from test_helpers.fixtures import (
    accept_trip,
    capture_trip,
    carrier_version,
    create_carrier,
    create_driver,
    create_vehicle,
    credentials_for_vehicle,
    distribute_credential,
    invoiced_application,
    issue_credentials,
    open_application,
    open_return,
    prepare_return,
    read_credential,
    read_return,
    read_vehicle,
    record_purchase,
    seed_reference_data_il_in_only,
    set_clock,
)
from test_helpers.test_users import OFFICER_1_HEADERS, PREPARER_1_HEADERS


def _prairie(client):
    """The Illinois licensee every scenario in this file registers."""
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


class TestIssuanceMintsTheWholePaperSetAtOnce:
    def test_three_credential_types_per_active_unit_with_defaulted_validity(
        self, client
    ):
        """"For every power unit of the carrier for that `registration_year`
        whose `vehicle_status` is `ACTIVE`, exactly three `Credential` rows are
        created — one of `credential_type` `DECAL_SET`, one of `CAB_CARD`, and
        one of `IFTA_LICENSE_COPY` — each carrying the `vehicle_id` of the unit
        it is printed for, the `registration_application_id` of the issuing
        application, and a `registration_year` copied from that application."

        Both ends of the window are defaulted here, and they default from
        different places: "`valid_from_date` is the supplied value or, when
        omitted, the logical-clock date at issuance, and `valid_to_date` is the
        supplied value or, when omitted, December 31 of the credential's
        `registration_year`." The clock is standing at 2026-09-20, so a
        from-date that reads 2026-01-01 or a to-date that reads a year out would
        both be wrong. Issuance also prices nothing further -- the fees were
        frozen at invoicing and are unchanged.

        Design: Corner/endpoints/issue_credentials_mints_all_three_credential_types_per_active_vehicle
        """
        seed_reference_data_il_in_only(client)
        carrier = _prairie(client)
        vehicle = _unit(client, carrier["id"], "U-101", "1FUJA6CK21L101101", 145000.00)
        application = invoiced_application(
            client, carrier["id"], [("IL", 60000.0), ("IN", 40000.0)]
        )
        assert_application_totals(
            application,
            application_status="INVOICED",
            apportioned_vehicle_count=1,
            base_fee_total=2350.80,
            total_apportioned_fee=2350.80,
        )
        version_before = application["version"]

        set_clock(client, "2026-09-20T00:00:00Z")
        issued = issue_credentials(client, application["id"])
        assert_application_totals(
            issued,
            application_status="ISSUED",
            base_fee_total=2350.80,
            total_apportioned_fee=2350.80,
        )
        assert_version_is(issued, version_before + 1)

        rows, meta = validate_paginated(
            client.list_credentials(
                OFFICER_1_HEADERS, params={"vehicle_id": vehicle["id"]}
            )
        )
        assert meta["total_count"] == 3
        assert {row["credential_type"] for row in rows} == {
            "DECAL_SET",
            "CAB_CARD",
            "IFTA_LICENSE_COPY",
        }
        for row in rows:
            assert_credential_state(
                row,
                credential_status="ISSUED",
                distributed_to_driver_id=None,
                distributed_at=None,
                voided_reason_code=None,
                valid_from_date="2026-09-20",
                valid_to_date="2026-12-31",
            )
            assert row["vehicle_id"] == vehicle["id"]
            assert row["registration_application_id"] == application["id"]
            assert row["registration_year"] == 2026

        plated = read_vehicle(client, vehicle["id"])
        assert plated["vehicle_status"] == "ACTIVE"
        assert plated["credential_status"] == "ISSUED"


class TestTheSettlementDetailLivesOnlyOnItsSubResource:
    def test_re_preparing_voids_the_old_lines_and_writes_a_fresh_active_set(
        self, client
    ):
        """"Every `ReturnJurisdictionLine` of the return whose `line_status` is
        `ACTIVE` becomes `VOIDED`, and the freshly computed set is inserted as
        `ACTIVE`; the voided set stays readable through the jurisdiction-line
        read, which accepts a `line_status` filter."

        The parent read carries totals and nothing per-jurisdiction, because
        "Voided rows remain readable through the corresponding line-listing
        endpoint, which is the only channel through which cascade results are
        observable." Re-preparing on unchanged evidence is idempotent in value
        and not in row count: four rows exist afterwards, two of them superseded
        but still carrying the amounts they were computed with. The second
        prepare also needs a freshly read token, because "the carrier's
        `latest_prepared_fleet_mpg` is set to the newly computed `fleet_mpg`, and
        the carrier's `version` increments by 1 — which is precisely why a second
        prepare needs a freshly read `expected_carrier_version`."

        Design: Corner/endpoints/jurisdiction_lines_are_observable_only_through_the_sub_resource_and_are_rewritten_on_re_prepare
        """
        seed_reference_data_il_in_only(client)
        carrier = _prairie(client)
        vehicle = _unit(client, carrier["id"], "U-101", "1FUJA6CK21L101101", 145000.00)
        trip = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            trip_start_utc="2026-04-05T06:00:00Z",
            trip_end_utc="2026-04-05T18:00:00Z",
            start_odometer=1000.0,
            end_odometer=1400.0,
            legs=[leg("IL", 300.0), leg("IN", 100.0)],
        )
        accept_trip(client, trip["id"])
        record_purchase(
            client,
            carrier["id"],
            vehicle["id"],
            jurisdiction_code="IL",
            purchase_date="2026-05-02",
            gallons=40.000,
        )
        quarter = open_return(client, carrier["id"], filing_year=2026, filing_quarter=2)
        prepare_return(client, quarter["id"], carrier["id"])

        # The freshly read token is the point: the first prepare moved the
        # carrier on, so the version captured before it would now be stale.
        second = validate_success(
            client.prepare_fuel_tax_return(
                quarter["id"],
                PREPARER_1_HEADERS,
                expected_carrier_version=carrier_version(client, carrier["id"]),
            )
        )
        assert_return_settlement(
            second,
            return_status="PREPARED",
            settlement_basis="PREPARER_BASIS",
            total_fleet_miles=400.0,
            total_tax_paid_gallons=40.000,
            fleet_mpg=10.00,
            total_net_tax_due=2.53,
            total_amount_due=2.53,
        )

        active, active_meta = validate_paginated(
            client.list_return_jurisdiction_lines(
                quarter["id"], OFFICER_1_HEADERS, params={"line_status": "ACTIVE"}
            )
        )
        assert active_meta["total_count"] == 2
        assert codes_of(active) == ["IL", "IN"]
        assert_jurisdiction_line(
            by_code(active, "IL"),
            taxable_miles=300.0,
            taxable_gallons=30.000,
            tax_paid_gallons=40.000,
            net_taxable_gallons=-10.000,
            net_tax_amount=-6.27,
        )
        assert_jurisdiction_line(
            by_code(active, "IN"),
            taxable_miles=100.0,
            taxable_gallons=10.000,
            tax_paid_gallons=0.000,
            net_taxable_gallons=10.000,
            base_tax_amount=3.30,
            surcharge_amount=5.50,
            net_tax_amount=8.80,
        )

        every_round, all_meta = validate_paginated(
            client.list_return_jurisdiction_lines(quarter["id"], OFFICER_1_HEADERS)
        )
        assert all_meta["total_count"] == 4
        voided = [row for row in every_round if row["line_status"] == "VOIDED"]
        assert len(voided) == 2
        assert sorted(row["jurisdiction_code"] for row in voided) == ["IL", "IN"]
        # The superseded round keeps the figures it was computed with.
        assert_money(
            by_code(voided, "IL")["net_tax_amount"], -6.27, "voided IL net_tax_amount"
        )
        assert_money(
            by_code(voided, "IN")["net_tax_amount"], 8.80, "voided IN net_tax_amount"
        )

        parent = read_return(client, quarter["id"])
        assert_return_settlement(
            parent, total_net_tax_due=2.53, total_amount_due=2.53, fleet_mpg=10.00
        )
        assert "jurisdiction_lines" not in parent


class TestTheScheduleLineLinksTwoThingsThatMustBothExist:
    def test_the_parent_is_resolved_before_the_jurisdiction_is_examined(self, client):
        """"A nested read such as a trip's mileage legs, a return's jurisdiction
        lines, a carrier's drivers, a carrier's audit selections, or an
        application's distance schedule first resolves the parent id and answers
        with that parent's not-found error if the parent is absent; only then
        does it apply the child filters."

        The same left-to-right discipline governs this write: "Path parameters
        are resolved strictly left to right before any body content is
        examined." So an unknown application id answers about the application
        even though the body's jurisdiction is perfectly good, and an undeclared
        jurisdiction on a real application answers about the jurisdiction. Only
        when both ends resolve is the link made -- and the link is made
        unpriced: "its `effective_distance_miles`, `apportion_percent` and
        `jurisdiction_fee_amount` all remain at zero until the application is
        invoiced."

        Design: Corner/endpoints/a_distance_schedule_line_links_an_application_to_a_declared_jurisdiction
        """
        seed_reference_data_il_in_only(client)
        carrier = _prairie(client)
        _unit(client, carrier["id"], "U-101", "1FUJA6CK21L101101", 145000.00)
        application = open_application(client, carrier["id"])

        no_such_parent = client.add_distance_schedule_line(
            NON_EXISTENT_UUID,
            {"jurisdiction_code": "IL", "reported_distance_miles": 60000.0},
            PREPARER_1_HEADERS,
        )
        validate_error(no_such_parent, ERR_REGISTRATION_APPLICATION_NOT_FOUND)

        no_such_jurisdiction = client.add_distance_schedule_line(
            application["id"],
            {"jurisdiction_code": "ZZ", "reported_distance_miles": 60000.0},
            PREPARER_1_HEADERS,
        )
        validate_error(no_such_jurisdiction, ERR_JURISDICTION_NOT_DECLARED)

        line = validate_success(
            client.add_distance_schedule_line(
                application["id"],
                {"jurisdiction_code": "IL", "reported_distance_miles": 60000.0},
                PREPARER_1_HEADERS,
            ),
            expected_status=201,
        )
        assert line["registration_application_id"] == application["id"]
        assert line["jurisdiction_code"] == "IL"
        assert line["line_status"] == "ACTIVE"
        assert_miles(line["reported_distance_miles"], 60000.0, "reported_distance_miles")
        assert_miles(line["effective_distance_miles"], 0.0, "effective_distance_miles")
        assert_apportion_percent(line["apportion_percent"], 0.000000)
        assert_money(line["jurisdiction_fee_amount"], 0.00, "jurisdiction_fee_amount")

        # Neither refusal left a row behind.
        rows, meta = validate_paginated(
            client.list_distance_schedule_lines(application["id"], OFFICER_1_HEADERS)
        )
        assert meta["total_count"] == 1
        assert codes_of(rows) == ["IL"]


class TestTheCredentialListNarrowsOnSeveralAxesAtOnce:
    def test_type_and_status_filters_intersect_rather_than_replace(self, client):
        """"Filters offered on a collection narrow the row set before ordering
        and windowing. They are always optional, and supplying two filters
        conjoins them."

        The credential list is the widest filter surface in the system --
        "`vehicle_id`, `registration_application_id`, `distributed_to_driver_id`,
        `credential_type`, `credential_status` and `registration_year` on
        credentials" -- so it is where a filter that replaces rather than
        conjoins would be least visible. Two units yield six credentials; the
        type filter alone yields two, the status filter alone yields all six, and
        the pair together still yields two, one per unit. "Both are reported back
        in `meta` alongside `total_count` — the number of rows matching the
        filters before the window is applied — and `has_more`, a boolean that is
        true exactly when rows remain beyond the returned window."

        Design: Corner/endpoints/the_credential_list_filters_by_type_and_status_together
        """
        seed_reference_data_il_in_only(client)
        carrier = _prairie(client)
        first = _unit(client, carrier["id"], "U-101", "1FUJA6CK21L101101", 145000.00)
        second = _unit(client, carrier["id"], "U-102", "1FUJA6CK21L101102", 152000.00)
        application = invoiced_application(
            client, carrier["id"], [("IL", 60000.0), ("IN", 40000.0)]
        )
        assert_application_totals(
            application,
            application_status="INVOICED",
            apportioned_vehicle_count=2,
            base_fee_total=4701.60,
        )
        issue_credentials(client, application["id"])

        _all_rows, all_meta = validate_paginated(
            client.list_credentials(
                OFFICER_1_HEADERS,
                params={"registration_application_id": application["id"]},
            )
        )
        assert all_meta["total_count"] == 6

        by_status, status_meta = validate_paginated(
            client.list_credentials(
                OFFICER_1_HEADERS,
                params={
                    "registration_application_id": application["id"],
                    "credential_status": "ISSUED",
                },
            )
        )
        assert status_meta["total_count"] == 6
        assert {row["credential_status"] for row in by_status} == {"ISSUED"}

        conjoined, conjoined_meta = validate_paginated(
            client.list_credentials(
                PREPARER_1_HEADERS,
                params={
                    "registration_application_id": application["id"],
                    "credential_type": "DECAL_SET",
                    "credential_status": "ISSUED",
                },
            )
        )
        assert conjoined_meta["total_count"] == 2
        assert {row["credential_type"] for row in conjoined} == {"DECAL_SET"}
        assert {row["vehicle_id"] for row in conjoined} == {first["id"], second["id"]}

        one_unit_one_type, single_meta = validate_paginated(
            client.list_credentials(
                OFFICER_1_HEADERS,
                params={"vehicle_id": first["id"], "credential_type": "CAB_CARD"},
            )
        )
        assert single_meta["total_count"] == 1
        assert one_unit_one_type[0]["vehicle_id"] == first["id"]

        # Nothing has been handed over yet, so the DISTRIBUTED slice is empty
        # rather than falling back to the whole table.
        empty, empty_meta = validate_paginated(
            client.list_credentials(
                OFFICER_1_HEADERS,
                params={
                    "registration_application_id": application["id"],
                    "credential_status": "DISTRIBUTED",
                },
            )
        )
        assert empty == []
        assert empty_meta["total_count"] == 0
        assert empty_meta["has_more"] is False

        assert read_vehicle(client, first["id"])["credential_status"] == "ISSUED"
        assert read_vehicle(client, second["id"])["credential_status"] == "ISSUED"


class TestAHandoverHappensExactlyOnce:
    def test_distributing_an_already_distributed_credential_is_rejected(self, client):
        """"The credential's `credential_status` must be `ISSUED`; a credential
        that is already `DISTRIBUTED`, or that has been `VOIDED` or `REPLACED`,
        cannot be handed over and the attempt is refused with
        `ERR_CREDENTIAL_NOT_ISSUED`."

        The second attempt names a different driver, so a lenient
        implementation would quietly re-stamp the handover trail onto whoever
        asked last. It must not: the first driver stays recorded. The unit's
        derived dimension is the other half of the claim -- "it moves `ISSUED →
        DISTRIBUTED` once every one of that unit's credentials in `ISSUED` or
        `DISTRIBUTED` has reached `DISTRIBUTED`, and it stays at `ISSUED` while
        any of them is still outstanding" -- so with one of three credentials
        handed out the vehicle still reads `ISSUED`.

        Design: Corner/endpoints/distribute_requires_a_credential_that_is_still_issued
        """
        seed_reference_data_il_in_only(client)
        carrier = _prairie(client)
        first_driver = create_driver(
            client, carrier["id"], full_name="Sam Okafor", cdl_number="IL-D-11001"
        )
        second_driver = create_driver(
            client, carrier["id"], full_name="Ana Petrov", cdl_number="IL-D-11002"
        )
        vehicle = _unit(client, carrier["id"], "U-101", "1FUJA6CK21L101101", 145000.00)
        application = invoiced_application(
            client, carrier["id"], [("IL", 60000.0), ("IN", 40000.0)]
        )
        issue_credentials(client, application["id"])
        decals = credentials_for_vehicle(client, vehicle["id"])["DECAL_SET"]

        handed_over = distribute_credential(client, decals["id"], first_driver["id"])
        assert_credential_state(
            handed_over,
            credential_status="DISTRIBUTED",
            credential_type="DECAL_SET",
            distributed_to_driver_id=first_driver["id"],
        )
        assert is_iso8601_timestamp(handed_over["distributed_at"])

        again = client.distribute_credential(
            decals["id"],
            OFFICER_1_HEADERS,
            distributed_to_driver_id=second_driver["id"],
        )
        validate_error(again, ERR_CREDENTIAL_NOT_ISSUED)

        assert_credential_state(
            read_credential(client, decals["id"]),
            credential_status="DISTRIBUTED",
            distributed_to_driver_id=first_driver["id"],
            distributed_at=handed_over["distributed_at"],
        )
        assert read_vehicle(client, vehicle["id"])["credential_status"] == "ISSUED"

        outstanding, meta = validate_paginated(
            client.list_credentials(
                OFFICER_1_HEADERS,
                params={"vehicle_id": vehicle["id"], "credential_status": "ISSUED"},
            )
        )
        assert meta["total_count"] == 2
        assert {row["credential_type"] for row in outstanding} == {
            "CAB_CARD",
            "IFTA_LICENSE_COPY",
        }

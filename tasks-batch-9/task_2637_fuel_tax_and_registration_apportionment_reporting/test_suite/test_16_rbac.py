"""Which desk may do what, and what a refused desk leaves behind.

The four roles are peers, not a ladder. Nothing here tests that a role can do
its own job -- the rest of the suite does that throughout. These tests drive the
crossings: a desk reaching for another desk's exclusive action, and every desk
reaching for the shared read surface.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ERR_FORBIDDEN_ROLE
from test_helpers.assertions import (
    assert_carrier_compliance,
    assert_jurisdiction_line,
    assert_return_settlement,
    assert_trip_state,
    assert_vehicle_dimensions,
)
from test_helpers.constants import JURISDICTION_IL
from test_helpers.factories import fuel_tax_return_payload, leg
from test_helpers.fixtures import (
    accept_trip,
    capture_trip,
    carrier_version,
    create_carrier,
    create_vehicle,
    open_return,
    read_carrier,
    read_return,
    read_trip,
    record_purchase,
    seed_jurisdictions,
    set_clock,
)
from test_helpers.test_users import (
    ANALYST_1_HEADERS,
    OFFICER_1_HEADERS,
    PREPARER_1_HEADERS,
    make_carrier_admin_headers,
)


def _illinois_only(client):
    """Clock plus the one declared jurisdiction every carrier below is based in."""
    set_clock(client)
    seed_jurisdictions(client, [JURISDICTION_IL])


def _prairie(client):
    return create_carrier(
        client,
        legal_name="Prairie Freight LLC",
        usdot_number="USDOT-2637001",
        base_jurisdiction_code="IL",
    )


def _unit(client, carrier_id, unit_number="U-101", vin="1FUJA6CK21L101101"):
    return create_vehicle(
        client,
        carrier_id,
        unit_number=unit_number,
        vin=vin,
        factory_price_amount=145000.00,
        registration_year=2026,
    )


class TestPreparationBelongsToOneDeskOnly:
    def test_an_analyst_is_refused_the_prepare_the_preparer_then_performs(self, client):
        """"If both headers are well-formed but the declared role is not among
        the roles authorised for the endpoint being called, the request is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Settlement is a preparer's job -- "A `TaxPreparer` computes the
        settlement, and may recompute it as new mileage or fuel evidence
        arrives." -- and the analyst who captured the mileage and recorded the
        fuel may not compute the tax from it. The denial lands at the role gate,
        which is above every substantive guard on the endpoint: the concurrency
        token the analyst supplied is never examined, so the carrier's `version`
        is exactly where the analyst read it and the same token still works for
        the preparer a moment later.

        The quarter itself is deliberately balanced -- 650.0 miles against
        100.000 tax-paid gallons is a fleet MPG of exactly 6.50, and Illinois
        bought precisely the gallons it burned, so the settlement lands at zero
        without any refund or liability to argue about. Reading the return is
        shared: the analyst who could not prepare it can still see it, because
        the identifiers of the three operator desks are opaque and "Because
        these three identifiers are opaque, no carrier-scope check applies to
        them; a `MileageAnalyst`, `TaxPreparer` or `ComplianceOfficer` may act
        across carriers."

        Design: Corner/rbac/a_mileage_analyst_cannot_prepare_a_return
        """
        _illinois_only(client)
        carrier = _prairie(client)
        vehicle = _unit(client, carrier["id"])

        trip = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            "2026-04-05T06:00:00Z",
            "2026-04-05T18:00:00Z",
            1000.0,
            1650.0,
            [leg("IL", 650.0)],
        )
        accept_trip(client, trip["id"])
        record_purchase(
            client,
            carrier["id"],
            vehicle["id"],
            "IL",
            "2026-05-02",
            100.000,
            receipt_reference="RCPT-IL-4471",
        )
        opened = open_return(client, carrier["id"], filing_year=2026, filing_quarter=2)
        version_read_by_the_analyst = carrier_version(client, carrier["id"])

        validate_error(
            client.prepare_fuel_tax_return(
                opened["id"],
                ANALYST_1_HEADERS,
                expected_carrier_version=version_read_by_the_analyst,
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        assert_return_settlement(
            read_return(client, opened["id"]), return_status="DRAFT", fleet_mpg=None
        )
        assert read_carrier(client, carrier["id"])["version"] == (
            version_read_by_the_analyst
        )

        prepared = validate_success(
            client.prepare_fuel_tax_return(
                opened["id"],
                PREPARER_1_HEADERS,
                expected_carrier_version=version_read_by_the_analyst,
            )
        )
        assert_return_settlement(
            prepared,
            return_status="PREPARED",
            settlement_basis="PREPARER_BASIS",
            total_fleet_miles=650.0,
            total_tax_paid_gallons=100.000,
            fleet_mpg=6.50,
            total_net_tax_due=0.00,
            reconstruction_penalty_amount=0.00,
            total_amount_due=0.00,
        )
        assert prepared["prepared_by_user_id"] == "preparer-1"

        lines, meta = validate_paginated(
            client.list_return_jurisdiction_lines(
                opened["id"], ANALYST_1_HEADERS, params={"line_status": "ACTIVE"}
            )
        )
        assert meta["total_count"] == 1
        assert_jurisdiction_line(
            lines[0],
            taxable_miles=650.0,
            taxable_gallons=100.000,
            tax_paid_gallons=100.000,
            net_taxable_gallons=0.000,
            base_tax_amount=0.00,
            surcharge_amount=0.00,
            net_tax_amount=0.00,
        )

        seen_by_the_analyst = validate_success(
            client.get_fuel_tax_return(opened["id"], ANALYST_1_HEADERS)
        )
        assert seen_by_the_analyst["id"] == opened["id"]
        assert seen_by_the_analyst["return_status"] == "PREPARED"


class TestTheDesksArePeersRatherThanALadder:
    def test_three_crossings_between_three_desks_are_all_refused(self, client):
        """"If both headers are well-formed but the declared role is not among
        the roles authorised for the endpoint being called, the request is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Three exclusive actions, three trespassers, one fixture. Trip review
        belongs to the officer: "Every trip that is to contribute miles to a
        settlement must pass an explicit review by a `ComplianceOfficer`, who
        supplies a `decision` of either `ACCEPT` or `REJECT` and may attach an
        optional `review_note`." -- so the preparer is refused it. Opening a
        quarter belongs to the preparer: "A `TaxPreparer` opens a quarterly
        return by naming the `carrier_id` of the licensee, the `filing_year` of
        the reporting quarter and the `filing_quarter`, which must be 1, 2, 3 or
        4." -- so the officer is refused it, even though the officer is the one
        who will later decide that very return. And rebuilding a gap belongs to
        the analyst: "Reconstruction is exclusive to the `MileageAnalyst` role
        and moves the trip `GAP_FLAGGED → RECONSTRUCTED`." -- so the officer is
        refused that too, which is the clearest evidence that the officer does
        not sit above the other desks and inherit their powers.

        Each denial is also inert. The captured trip is still awaiting its
        review, the flagged trip still carries the telematics basis it was born
        with, no return exists for the quarter at all, and the carrier's
        unsubstantiated share is still the three hundred flagged miles out of
        six hundred that the two captures established.

        Design: Corner/rbac/role_exclusive_actions_cannot_be_crossed_between_the_desks
        """
        _illinois_only(client)
        carrier = _prairie(client)
        vehicle = _unit(client, carrier["id"])

        captured = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            "2026-04-05T06:00:00Z",
            "2026-04-05T18:00:00Z",
            700.0,
            1000.0,
            [leg("IL", 300.0)],
        )
        assert_trip_state(captured, trip_status="CAPTURED")
        flagged = capture_trip(
            client,
            carrier["id"],
            vehicle["id"],
            "2026-05-10T06:00:00Z",
            "2026-05-10T18:00:00Z",
            1100.0,
            1400.0,
            [leg("IL", 300.0)],
        )
        assert_trip_state(
            flagged, trip_status="GAP_FLAGGED", gap_miles_from_previous=100.0
        )

        validate_error(
            client.review_trip_record(
                captured["id"], PREPARER_1_HEADERS, decision="ACCEPT"
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        assert_trip_state(read_trip(client, captured["id"]), trip_status="CAPTURED")

        validate_error(
            client.create_fuel_tax_return(
                fuel_tax_return_payload(
                    carrier["id"], filing_year=2026, filing_quarter=2
                ),
                OFFICER_1_HEADERS,
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        returns, returns_meta = validate_paginated(
            client.list_fuel_tax_returns(
                OFFICER_1_HEADERS, params={"carrier_id": carrier["id"]}
            )
        )
        assert returns_meta["total_count"] == 0
        assert returns == []

        validate_error(
            client.reconstruct_trip_record(
                flagged["id"],
                OFFICER_1_HEADERS,
                reconstructed_legs=[leg("IL", 400.0)],
                supporting_document_reference="FUEL-LOG-88",
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )
        assert_trip_state(
            read_trip(client, flagged["id"]),
            trip_status="GAP_FLAGGED",
            mileage_source="TELEMATICS",
            supporting_document_reference=None,
            reconstructed_by_user_id=None,
        )

        assert_carrier_compliance(
            read_carrier(client, carrier["id"]),
            unsubstantiated_mileage_ratio=0.5000,
            audit_flag=True,
        )


class TestTheReadSurfaceIsSharedByEveryDesk:
    def test_one_vehicle_reads_identically_for_all_four_roles(self, client):
        """"Concretely, a `CarrierAdmin` request is confined to its own fleet:
        the target vehicle's `carrier_id`, the parent application's `carrier_id`,
        or, for a credential handover, the `carrier_id` of the vehicle the
        credential was printed for, must all equal `X-User-ID`."

        That confinement is a write-side rule, and the specification enumerates
        exactly where it bites: "This scope check governs mid-year supplement
        filing, credential distribution, driver enrolment, vehicle enrolment,
        trip capture, and fuel purchase recording." Reading is not on that list,
        and the vehicle read is authorised for all four roles, so Lakeshore's
        administrator may read Prairie's unit even though it could not enrol one
        there. The other three desks are unconstrained in any case, since
        "Because these three identifiers are opaque, no carrier-scope check
        applies to them; a `MileageAnalyst`, `TaxPreparer` or
        `ComplianceOfficer` may act across carriers."

        Four reads of one row must also agree with each other exactly, down to
        the version -- a read is not a write, and the row must not have moved
        between the first caller and the last.

        Design: Corner/rbac/every_role_can_read_the_shared_get_surface
        """
        _illinois_only(client)
        prairie = _prairie(client)
        lakeshore = create_carrier(
            client,
            legal_name="Lakeshore Haulage Inc",
            usdot_number="USDOT-2637002",
            base_jurisdiction_code="IL",
        )
        vehicle = _unit(client, prairie["id"])

        readers = {
            "CarrierAdmin": make_carrier_admin_headers(lakeshore["id"]),
            "MileageAnalyst": ANALYST_1_HEADERS,
            "TaxPreparer": PREPARER_1_HEADERS,
            "ComplianceOfficer": OFFICER_1_HEADERS,
        }
        seen = {}
        for role, headers in readers.items():
            response = client.get_vehicle(vehicle["id"], headers)
            data = validate_success(response)
            assert data["id"] == vehicle["id"], f"{role} read the wrong row"
            assert data["carrier_id"] == prairie["id"]
            assert_vehicle_dimensions(
                data, vehicle_status="PENDING", credential_status="NONE"
            )
            assert response.json()["meta"]["api_request_id"].startswith("req_")
            seen[role] = data

        first = seen["CarrierAdmin"]
        for role, data in seen.items():
            assert data == first, f"the {role} read differs from the CarrierAdmin read"
        assert {data["version"] for data in seen.values()} == {first["version"]}

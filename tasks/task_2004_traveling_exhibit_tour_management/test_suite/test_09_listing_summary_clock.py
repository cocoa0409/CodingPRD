"""Listings, pagination envelope, financial summary, and the certificate clock
(PRD §2.2, §2.3, §2.4, §3.1, §3.9)."""
import pytest
from test_helpers import (
    validate_success,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    assert_tour,
    create_tour_payload,
    create_tour,
    create_and_open_booking,
    create_venue,
    book_stop,
    issue_certificate,
    plan_first_leg,
    setup_contracted_stop,
)

TM = TEST_USERS["tour_manager_headers"]
INS = TEST_USERS["insurer_headers"]
SHIP = TEST_USERS["shipper_headers"]


class TestListToursPagination:
    def test_pagination_envelope_and_total_count(self, api):
        """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100."

        Design: Corner/endpoints/list_tours_pagination_defaults
        """
        for i in range(3):
            get_success_data(
                api.create_tour(
                    create_tour_payload(title=f"T{i+1}", exhibit_code=f"T{i+1}-2026"),
                    TM,
                )
            )
        data, meta = validate_paginated(api.list_tours(TM))
        assert len(data) == 3
        assert meta["total_count"] == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["has_more"] is False

    def test_list_tours_entries_are_well_formed(self, api):
        """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/list_tours_pagination_defaults
        """
        for i in range(3):
            get_success_data(
                api.create_tour(
                    create_tour_payload(title=f"T{i+1}", exhibit_code=f"T{i+1}-2026"),
                    TM,
                )
            )
        data, meta = validate_paginated(api.list_tours(TM))
        assert len(data) == 3
        for entry in data:
            assert_tour(entry)


class TestListCratesByLocation:
    def test_filter_returns_only_in_transit_crates(self, api):
        """PRD §3.1: "A tour's crate collection lists with a `location_status`
        filter."
        PRD §3.6: "Dispatch physically commits the crates: every crate on the
        manifest moves from `AT_VENUE` (or `AT_ORIGIN`) to `IN_TRANSIT`, with
        each crate's `current_stop_id` pointed at the destination stop."

        Design: Corner/endpoints/list_crates_filtered_by_location_status
        """
        tour, crates, venue, stop, contract = setup_contracted_stop(
            crate_values=[100000, 100000], crate_count=2, declared_value_cents=200000
        )
        issue_certificate(tour["id"], stop["id"], tour["declared_value_cents"])
        # Only crate[0] goes on the manifest; crate[1] stays AT_ORIGIN.
        shipment = plan_first_leg(tour["id"], stop["id"], [crates[0]["id"]])
        validate_success(
            api.transition_shipment(tour["id"], shipment["id"], {"action": "DISPATCH"}, SHIP),
            200,
        )
        data, meta = validate_paginated(
            api.list_crates(tour["id"], TM, params={"location_status": "IN_TRANSIT"})
        )
        assert len(data) == 1
        assert data[0]["id"] == crates[0]["id"]
        assert data[0]["location_status"] == "IN_TRANSIT"

    def test_filter_at_origin_excludes_dispatched_crate(self, api):
        """PRD §3.1: "A tour's crate collection lists with a `location_status`
        filter."

        Design: Corner/endpoints/list_crates_filtered_by_location_status
        """
        tour, crates, venue, stop, contract = setup_contracted_stop(
            crate_values=[100000, 100000], crate_count=2, declared_value_cents=200000
        )
        issue_certificate(tour["id"], stop["id"], tour["declared_value_cents"])
        shipment = plan_first_leg(tour["id"], stop["id"], [crates[0]["id"]])
        validate_success(
            api.transition_shipment(tour["id"], shipment["id"], {"action": "DISPATCH"}, SHIP),
            200,
        )
        data, meta = validate_paginated(
            api.list_crates(tour["id"], TM, params={"location_status": "AT_ORIGIN"})
        )
        assert len(data) == 1
        assert data[0]["id"] == crates[1]["id"]


class TestFinancialSummary:
    def test_fresh_tour_zero_totals(self, api):
        """PRD §3.9: "Throughout the lifecycle, the tour's ledger reads back
        through its financial summary: `total_billed_cents` of final fees billed
        across all stops, `total_collected_cents` of payments applied to
        participation fees, `total_waived_cents` of sponsorship waivers granted
        at signature, and the derived `outstanding_cents` still to be
        collected."
        PRD §3.1: "A new tour is born in `DRAFT` with its three ledger totals —
        `total_billed_cents`, `total_collected_cents`, and `total_waived_cents`
        — all initialized to zero."

        Design: Corner/endpoints/financial_summary_computed_read
        """
        tour = create_tour(title="Zero", exhibit_code="ZERO-2026")
        summary = validate_success(api.get_financial_summary(tour["id"], TM), 200)
        assert summary["total_billed_cents"] == 0
        assert summary["total_collected_cents"] == 0
        assert summary["total_waived_cents"] == 0
        assert summary["outstanding_cents"] == 0


class TestCertificateClock:
    def _setup_future_cert(self, api):
        tour, _ = create_and_open_booking(
            title="Clock", exhibit_code="CLK2-2026", declared_value_cents=100000
        )
        venue = create_venue(name="Clock Hall")
        stop = book_stop(tour["id"], venue["id"], projected_attendance=100)
        cert = issue_certificate(
            tour["id"],
            stop["id"],
            100000,
            effective_from="2026-09-01T00:00:00Z",
            effective_to="2026-11-01T00:00:00Z",
        )
        return tour, cert

    def test_certificate_stays_issued_before_effective_from(self, api):
        """PRD §2.4: "Before any client call, the logical clock reads exactly
        2026-08-01T00:00:00Z — a fixed startup default."
        PRD §2.4: "a certificate in `ISSUED` becomes `ACTIVE` once the logical
        clock reaches its `effective_from`".

        Design: Corner/cross_cutting_layers/clock_default_and_certificate_activation
        """
        tour, cert = self._setup_future_cert(api)
        fetched = validate_success(api.get_certificate(tour["id"], cert["id"], INS), 200)
        assert fetched["status"] == "ISSUED"

    def test_certificate_activates_when_clock_advances(self, api):
        """PRD §2.4: "A `TourManager`-only test-driving capability advances it:
        the caller supplies a `to_iso8601` instant and receives back the
        resulting `current_utc`. Insurance certificates ride this clock: a
        certificate in `ISSUED` becomes `ACTIVE` once the logical clock reaches
        its `effective_from`, and a certificate in `ACTIVE` becomes `EXPIRED`
        once the logical clock reaches its `effective_to`."

        Design: Corner/cross_cutting_layers/clock_default_and_certificate_activation
        """
        tour, cert = self._setup_future_cert(api)
        before = validate_success(api.get_certificate(tour["id"], cert["id"], INS), 200)
        assert before["status"] == "ISSUED"
        validate_success(
            api.set_clock({"to_iso8601": "2026-09-02T00:00:00Z"}, TM), 200
        )
        after = validate_success(api.get_certificate(tour["id"], cert["id"], INS), 200)
        assert after["status"] == "ACTIVE"

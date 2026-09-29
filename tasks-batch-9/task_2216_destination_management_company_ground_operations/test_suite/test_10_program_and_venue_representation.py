"""What a freshly written programme or venue row actually reads back as."""

from test_helpers import (
    CLOCK_STARTUP_UTC,
    TEST_USERS,
    create_program,
    set_clock,
    validate_paginated,
    validate_success,
)

PD = TEST_USERS["program_director_headers"]
OC = TEST_USERS["operations_coordinator_headers"]

ARDEN = {
    "client_name": "Arden Logistics",
    "group_name": "Ops Summit",
    "arrival_date": "2026-09-10",
    "departure_date": "2026-09-14",
    "guaranteed_count": 100,
    "markup_pct": 0.18,
}
BELLWEATHER = {
    "client_name": "Bellweather Foods",
    "group_name": "Regional Sales Meet",
    "arrival_date": "2026-09-10",
    "departure_date": "2026-09-14",
    "guaranteed_count": 64,
    "markup_pct": 0.22,
}
ZEROED_FIELDS = (
    "element_count",
    "open_element_count",
    "actual_attendance_total",
    "estimated_client_total_cents",
    "final_client_total_cents",
    "supplier_open_payable_cents",
    "seated_guest_count",
    "staffing_gap_count",
)


class TestProgramCreation:
    def test_a_new_programme_starts_drafted_and_completely_zeroed(self, api):
        """PRD §3.1: "A newly created programme starts with `execution_status` of `DRAFT`
        and `settlement_status` of `NOT_STARTED`, with `invoice_issued_at` null and with
        every derived count and money field at zero: `element_count`, `open_element_count`,
        `actual_attendance_total`, `estimated_client_total_cents`, `final_subtotal_cents`,
        `disclosed_markup_cents`, `management_fee_cents`, `final_client_total_cents`,
        `supplier_gross_payable_cents`, `supplier_settled_cents`,
        `supplier_open_payable_cents`, `credit_note_cents`, `seated_guest_count`,
        `staffing_gap_count` and `unseated_guest_count`."

        Design: Corner/entities/create_program_returns_declared_defaults_and_zeroed_computed_fields
        """
        set_clock(CLOCK_STARTUP_UTC)

        response = api.create_program(ARDEN, PD)

        program = validate_success(response, 201)
        assert program["execution_status"] == "DRAFT"
        assert program["settlement_status"] == "NOT_STARTED"
        assert program["version"] == 1
        assert program["invoice_issued_at"] is None
        for field in ZEROED_FIELDS:
            assert program[field] == 0, field
        envelope = response.json()
        assert envelope["response_type"] == "object"
        assert envelope["meta"]["api_request_id"].startswith("req_")
        assert envelope["meta"]["api_request_timestamp"]

    def test_omitting_the_markup_falls_back_to_the_disclosed_default(self, api):
        """PRD §3.1: "An optional `markup_pct` sets the disclosed markup applied to
        supplier cost on every reconciliation line; when omitted it defaults to `0.18`, and
        whether supplied or defaulted it must be at least `0.05` and at most `0.35`, with
        anything outside that band refused as `ERR_MARKUP_PCT_OUT_OF_BAND`."

        Design: Corner/entities/omitted_markup_pct_applies_declared_default
        """
        response = api.create_program(
            {
                "client_name": "Default Markup Client",
                "group_name": "Default Group",
                "arrival_date": "2026-09-10",
                "departure_date": "2026-09-14",
                "guaranteed_count": 44,
            },
            PD,
        )

        program = validate_success(response, 201)
        assert program["markup_pct"] == 0.18

    def test_client_supplied_totals_and_counts_are_discarded(self, api):
        """PRD §3.1: "A newly created programme starts with `execution_status` of `DRAFT`
        and `settlement_status` of `NOT_STARTED`, with `invoice_issued_at` null and with
        every derived count and money field at zero: `element_count`, `open_element_count`,
        `actual_attendance_total`, `estimated_client_total_cents`, `final_subtotal_cents`,
        `disclosed_markup_cents`, `management_fee_cents`, `final_client_total_cents`,
        `supplier_gross_payable_cents`, `supplier_settled_cents`,
        `supplier_open_payable_cents`, `credit_note_cents`, `seated_guest_count`,
        `staffing_gap_count` and `unseated_guest_count`."

        Design: Corner/entities/program_computed_totals_reject_client_input_ignored
        """
        response = api.create_program(
            {
                "client_name": "Spoofing Client",
                "group_name": "Spoofing Group",
                "arrival_date": "2026-09-10",
                "departure_date": "2026-09-14",
                "guaranteed_count": 20,
                "markup_pct": 0.18,
                "element_count": 99,
                "final_client_total_cents": 500_000,
                "supplier_open_payable_cents": 777,
            },
            PD,
        )

        program = validate_success(response, 201)
        assert program["element_count"] == 0
        assert program["final_client_total_cents"] == 0
        assert program["supplier_open_payable_cents"] == 0

    def test_a_stored_programme_reads_back_exactly_as_filed(self, api):
        """PRD §2.2: "The `data` field contains the resource object or an array of resource
        objects."

        Design: Corner/entities/get_program_returns_stored_representation
        """
        created = create_program(**BELLWEATHER)

        program = validate_success(api.get_program(created["id"], OC))

        assert program["id"] == created["id"]
        assert program["guaranteed_count"] == 64
        assert program["markup_pct"] == 0.22
        assert program["arrival_date"] == "2026-09-10"
        assert program["departure_date"] == "2026-09-14"


class TestProgramListing:
    ROSTER = (
        ("2026-08-01T00:00:00Z", "Client One", "Group One", "2026-09-10", "2026-09-14", 10),
        ("2026-08-01T01:00:00Z", "Client Two", "Group Two", "2026-09-15", "2026-09-18", 20),
        (
            "2026-08-01T02:00:00Z",
            "Client Three",
            "Group Three",
            "2026-09-20",
            "2026-09-24",
            30,
        ),
    )

    def _three_programmes_filed_an_hour_apart(self):
        """The clock moves between creates so `created_at` orders the three unambiguously."""
        filed = []
        for clock, client, group, arrival, departure, guaranteed in self.ROSTER:
            set_clock(clock)
            filed.append(
                create_program(
                    client_name=client,
                    group_name=group,
                    arrival_date=arrival,
                    departure_date=departure,
                    guaranteed_count=guaranteed,
                )
            )
        return filed

    def test_two_pages_split_three_programmes_and_report_the_full_count(self, api):
        """PRD §2.3: "Unless a specific endpoint says otherwise, list results are sorted by
        `created_at` ascending. The `meta` object of every list response carries `limit`,
        `offset`, `total_count` and `has_more`."

        Design: Corner/entities/list_programs_paginated_with_total_count_and_has_more
        """
        self._three_programmes_filed_an_hour_apart()

        first_page = api.list_programs(PD, params={"limit": 2, "offset": 0})
        second_page = api.list_programs(PD, params={"limit": 2, "offset": 2})

        items, meta = validate_paginated(first_page)
        assert first_page.json()["response_type"] == "array"
        assert len(items) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert [row["client_name"] for row in items] == ["Client One", "Client Two"]

        tail, tail_meta = validate_paginated(second_page)
        assert len(tail) == 1
        assert tail_meta["total_count"] == 3
        assert tail_meta["has_more"] is False
        assert tail[0]["client_name"] == "Client Three"

    def test_the_execution_status_filter_matches_all_three_drafts(self, api):
        """PRD §2.3: "Programmes may be filtered by `execution_status` and
        `settlement_status`."

        Design: Corner/entities/list_programs_paginated_with_total_count_and_has_more
        """
        self._three_programmes_filed_an_hour_apart()

        items, meta = validate_paginated(
            api.list_programs(
                PD, params={"execution_status": "DRAFT", "limit": 10, "offset": 0}
            )
        )

        assert len(items) == 3
        assert meta["total_count"] == 3
        assert {row["execution_status"] for row in items} == {"DRAFT"}


class TestVenueSystemFields:
    SPOOFED = {
        "name": "Spoofed Venue",
        "capacity_seated": 100,
        "capacity_reception": 150,
        "turnover_buffer_minutes": 60,
        "requires_special_venue_permit": False,
        "status": "ACTIVE",
        "id": "11111111-1111-1111-1111-111111111111",
        "created_at": "2000-01-01T00:00:00Z",
        "version": 42,
    }

    def test_supplied_id_created_at_and_version_are_all_overwritten(self, api):
        """PRD §2.4: "Every persisted resource in this system — programmes, venues,
        suppliers, supplier contracts, program elements, permits, transport segments,
        manifest entries, staff members, staff assignments, reconciliation lines and
        settlement payments — carries the same four system-managed properties:"

        Design: Corner/entities/venue_system_fields_server_generated_extra_field_ignored
        """
        set_clock(CLOCK_STARTUP_UTC)

        response = api.create_venue(self.SPOOFED, PD)

        venue = validate_success(response, 201)
        assert venue["id"] != self.SPOOFED["id"]
        assert venue["version"] == 1
        # The row is stamped from the logical clock, not from the supplied literal.
        assert venue["created_at"].startswith("2026-08-01T00:00:00")
        stored = validate_success(api.get_venue(venue["id"], PD))
        assert stored["name"] == "Spoofed Venue"
        assert stored["version"] == 1

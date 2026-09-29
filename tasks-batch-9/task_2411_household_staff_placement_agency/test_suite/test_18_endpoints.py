"""The API surface itself: the clock, pagination, list filters and derived reads.

These tests exercise the collection endpoints and the two clock endpoints, where
the interesting behaviour is in the envelope and the query parameters rather than
in a state machine.
"""
from test_helpers import (
    BILLING,
    CASE_OPENER,
    PRINCIPAL,
    RECORDER,
    api_client,
    append_ledger_adjustment,
    confirm_start,
    create_household,
    create_onboarded_household,
    invoice_and_pay,
    invoice_milestone,
    invoice_milestone_payload,
    read_client,
    read_ledger,
    read_milestone,
    read_placement,
    register_candidate,
    set_clock,
    setup_active_placement,
    setup_investigating_case,
    setup_pending_offer,
    validate_error,
    validate_paginated,
    validate_success,
)

NO_HEADERS = {}


class TestTheLogicalClock:
    def test_01_one_advance_reports_both_sweep_counters(self):
        """A single advance crosses a due date and a guarantee expiry at once.

        PRD §2.6: "Advancing the clock runs an **ops sweep** with two jobs. First,
        every `FeeMilestone` whose `invoice_status` is `INVOICED` and whose
        `due_date` falls strictly before the new clock date moves to `OVERDUE`; a
        clock landing exactly on `due_date` leaves the milestone `INVOICED`.
        Second, every `Placement` whose `placement_status` is `ACTIVE` and whose
        `guarantee_expires_on` is on or before the new clock date moves to
        `GUARANTEE_EXPIRED`. Each affected row has its `version` incremented. The
        clock-set response reports what the sweep did: `current_utc` echoes the new
        instant, `milestones_marked_overdue` counts the milestones aged in this
        call, and `placements_guarantee_expired` counts the placements whose
        guarantee lapsed in this call."

        Design: Corner/endpoints/the_clock_sweep_reports_how_many_rows_it_aged
        """
        scenario = setup_active_placement()
        invoiced = invoice_milestone(scenario["milestones"][0])
        assert invoiced["due_date"] == "2026-09-15"

        swept = validate_success(
            api_client.set_clock("2026-11-30T00:00:00Z", PRINCIPAL)
        )
        assert swept["current_utc"] == "2026-11-30T00:00:00Z"
        assert swept["milestones_marked_overdue"] == 1
        assert swept["placements_guarantee_expired"] == 1

        aged = read_milestone(invoiced)
        assert aged["invoice_status"] == "OVERDUE"
        assert aged["due_date"] == "2026-09-15"

        placement = read_placement(scenario["placement"])
        assert placement["placement_status"] == "GUARANTEE_EXPIRED"
        assert placement["guarantee_expires_on"] == "2026-11-30"

        assert read_milestone(scenario["milestones"][1])["invoice_status"] == "PENDING"
        assert read_milestone(scenario["milestones"][2])["invoice_status"] == "PENDING"

    def test_02_the_clock_read_needs_no_authentication_headers(self):
        """The stored instant is echoed to a caller with no identity at all.

        PRD §2.1: "Every request other than the two logical-clock endpoints must
        carry two headers: `X-User-ID`, identifying the acting principal, and
        `X-User-Role`, declaring the capacity in which it is acting."

        PRD §2.6: "`GET /_clock` reads the stored instant back and returns it as
        `current_utc`."

        Design: Corner/endpoints/the_clock_read_with_missing_auth_headers_echoes_the_stored_time
        """
        set_clock("2026-08-20T08:30:00Z")

        read = validate_success(api_client.get_clock(NO_HEADERS))
        assert read["current_utc"] == "2026-08-20T08:30:00Z"


class TestPaginationAndFilters:
    def test_03_the_candidate_list_pages_at_the_default_limit(self):
        """Eleven rows exist and no limit is supplied, so the default must show.

        PRD §2.3: "Every list endpoint accepts two pagination parameters. `limit`
        defaults to 10 when omitted, has a minimum of 1 and a permitted maximum of
        100; `offset` defaults to 0 and has a minimum of 0."

        PRD §2.3: "Successful list responses carry `limit`, `offset`,
        `total_count` and `has_more` inside `meta`, where `total_count` is the
        number of rows matching the filters before pagination is applied and
        `has_more` is true when rows remain beyond the current page."

        Design: Corner/endpoints/the_candidate_list_pages_at_the_default_limit_of_ten
        """
        set_clock("2026-08-01T00:00:00Z")
        for index in range(1, 12):
            register_candidate(
                full_name=f"Candidate {index:02d}",
                contact_email=f"cand{index:02d}@mail.example",
                years_experience=3,
            )

        rows, meta = validate_paginated(api_client.list_candidates(RECORDER))
        assert len(rows) == 10
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 11
        assert meta["has_more"] is True

        tail, tail_meta = validate_paginated(
            api_client.list_candidates(RECORDER, {"offset": 10})
        )
        assert len(tail) == 1
        assert tail_meta["has_more"] is False

    def test_04_the_household_list_filters_on_the_lifecycle_state(self):
        """Two households in two states cannot both satisfy a fixed answer.

        PRD §2.3: "List filters are declared per collection and are all optional.
        Households may be filtered by `status`, `region_code` and
        `confidentiality_agreement_status`."

        Design: Corner/endpoints/the_household_list_filters_on_the_status_column
        """
        set_clock("2026-08-01T00:00:00Z")
        onboarded = create_onboarded_household()
        prospect = create_household(
            household_name="Beckford Row",
            primary_contact_email="ops@beckford.example",
            region_code="CA",
        )

        rows, meta = validate_paginated(
            api_client.list_clients(PRINCIPAL, {"status": "ONBOARDED"})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == onboarded["id"]

        rows, meta = validate_paginated(
            api_client.list_clients(PRINCIPAL, {"status": "PROSPECT"})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == prospect["id"]

        _, meta = validate_paginated(api_client.list_clients(PRINCIPAL))
        assert meta["total_count"] == 2

    def test_05_a_zero_page_size_is_out_of_range(self):
        """Zero is one below the declared minimum page size.

        PRD §2.3: "A `limit` value outside the accepted band of 1 through 200, or
        a negative `offset`, is refused with `ERR_INVALID_RANGE` (HTTP 400); a
        `limit` above the permitted maximum of 100 but still inside the accepted
        band is served with at most 100 rows."

        Design: Corner/endpoints/a_zero_limit_on_the_household_list_is_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        create_household()

        validate_error(
            api_client.list_clients(PRINCIPAL, {"limit": 0}),
            "ERR_INVALID_RANGE",
            400,
        )

        rows, _ = validate_paginated(api_client.list_clients(PRINCIPAL, {"limit": 1}))
        assert len(rows) == 1

    def test_06_an_unknown_filter_value_is_refused_rather_than_ignored(self):
        """An unknown state is a refusal, not an empty page.

        PRD §2.3: "Any filter value outside its declared enumeration is refused
        with `ERR_INVALID_ENUM` (HTTP 400)."

        Design: Corner/endpoints/an_unrecognised_status_filter_on_the_household_list_is_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        create_household()

        validate_error(
            api_client.list_clients(PRINCIPAL, {"status": "DORMANT"}),
            "ERR_INVALID_ENUM",
            400,
        )

    def test_07_the_enforcement_case_list_is_queryable_on_every_leg(self):
        """The case points at a household, a candidate and a placement at once.

        PRD §2.3: "Enforcement cases may be filtered by `respondent_client_id`,
        `candidate_id`, `source_placement_id` and `status`."

        Design: Corner/endpoints/the_enforcement_case_list_is_indexed_by_household_and_state
        """
        scenario = setup_investigating_case()
        client_id = scenario["client"]["id"]
        candidate_id = scenario["candidate"]["id"]

        rows, meta = validate_paginated(
            api_client.list_non_solicitation_cases(
                CASE_OPENER,
                {"respondent_client_id": client_id, "status": "INVESTIGATING"},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == scenario["case"]["id"]
        assert rows[0]["respondent_client_id"] == client_id
        assert rows[0]["candidate_id"] == candidate_id
        assert rows[0]["source_placement_id"] == scenario["placement"]["id"]

        _, meta = validate_paginated(
            api_client.list_non_solicitation_cases(
                CASE_OPENER,
                {"respondent_client_id": client_id, "status": "ALLEGED"},
            )
        )
        assert meta["total_count"] == 0

        _, meta = validate_paginated(
            api_client.list_non_solicitation_cases(
                CASE_OPENER, {"candidate_id": candidate_id}
            )
        )
        assert meta["total_count"] == 1

    def test_08_the_milestone_list_splits_on_the_invoice_status(self):
        """One row has moved on, so the two filtered reads must split 1 and 2.

        PRD §2.3: "A placement's milestone collection accepts `invoice_status` and
        `milestone_type`; its claim collection accepts `status` and
        `requested_remedy`; its payroll-handoff collection accepts `status`."

        Design: Corner/endpoints/the_milestone_list_filters_on_the_invoice_status
        """
        scenario = setup_active_placement()
        invoiced = invoice_milestone(scenario["milestones"][0])

        rows, meta = validate_paginated(
            api_client.list_fee_milestones(
                scenario["placement"]["id"], BILLING, {"invoice_status": "PENDING"}
            )
        )
        assert meta["total_count"] == 2
        assert [row["invoice_status"] for row in rows] == ["PENDING", "PENDING"]
        assert [row["sequence_no"] for row in rows] == [2, 3]
        assert [row["amount_cents"] for row in rows] == [600_000, 800_000]

        rows, meta = validate_paginated(
            api_client.list_fee_milestones(
                scenario["placement"]["id"], BILLING, {"invoice_status": "INVOICED"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == invoiced["id"]


class TestDerivedReads:
    def test_09_a_trial_cleared_row_cannot_be_invoiced_before_the_start(self):
        """The row itself is PENDING, so the objection comes from its parent.

        PRD §3.7: "The parent placement's `placement_status` must be
        `PENDING_ACCEPTANCE` or `ACTIVE` when the `milestone_type` is `ENGAGEMENT`
        — the engagement fee is billable as soon as the offer is out — and must be
        exactly `ACTIVE` when the `milestone_type` is `TRIAL_CLEARED` or
        `START_DATE`; a placement outside the admissible set is refused with
        `ERR_PLACEMENT_NOT_ACTIVE` (HTTP 409)."

        Design: Corner/endpoints/invoicing_before_the_placement_is_active_is_refused
        """
        scenario = setup_pending_offer()
        trial_cleared = scenario["milestones"][1]
        assert trial_cleared["milestone_type"] == "TRIAL_CLEARED"
        assert trial_cleared["invoice_status"] == "PENDING"

        validate_error(
            api_client.invoice_fee_milestone(
                trial_cleared["id"], invoice_milestone_payload(), BILLING
            ),
            "ERR_PLACEMENT_NOT_ACTIVE",
            409,
        )

        stored = read_milestone(trial_cleared)
        assert stored["invoice_status"] == "PENDING"
        assert stored["invoiced_on"] is None
        assert read_placement(scenario["placement"])["billing_status"] == "UNBILLED"

        _, meta = validate_paginated(
            api_client.list_ledger_entries(scenario["client"]["id"], BILLING)
        )
        assert meta["total_count"] == 0

        set_clock("2026-09-01T00:00:00Z")
        confirm_start(scenario["placement"])
        assert invoice_milestone(trial_cleared)["invoice_status"] == "INVOICED"

    def test_10_the_household_read_folds_its_whole_ledger(self):
        """Three rows of two signs fold to a single receivable figure.

        PRD §2.12: "A household's `outstanding_balance_cents` is the running fold
        of its ledger. Starting from zero, each row in ascending `sequence_no`
        order adds its `signed_amount_cents` to the running total, and the total
        after each row is what that row's `balance_after_cents` preserves; the
        household's `outstanding_balance_cents` is the total after the last row."

        Design: Corner/endpoints/the_household_read_recomputes_its_balance_from_the_ledger
        """
        scenario = setup_active_placement()
        invoice_and_pay(scenario["milestones"][0])
        append_ledger_adjustment(scenario["client"], 250_000)

        household = read_client(scenario["client"])
        assert household["outstanding_balance_cents"] == 250_000
        assert household["placement_count"] == 1

        entries = read_ledger(scenario["client"])
        assert [entry["entry_type"] for entry in entries] == [
            "FEE_INVOICED",
            "FEE_PAYMENT",
            "MANUAL_ADJUSTMENT",
        ]
        assert [entry["balance_after_cents"] for entry in entries] == [
            600_000,
            0,
            250_000,
        ]

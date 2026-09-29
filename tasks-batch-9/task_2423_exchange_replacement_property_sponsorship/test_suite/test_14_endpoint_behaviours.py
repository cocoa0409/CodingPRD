"""Computed reads, action endpoints and filtered list reads.

The investor report is recomputed on every call rather than stored; the
terminate action is observable through the capability it withdraws; an action
that is conditional on state refuses without touching anything downstream; and
every declared filter resolves against a fully funded trust in one pass.
"""

from test_helpers import (
    CANONICAL_CAPITAL_STACK,
    CANONICAL_LOAN_METRICS,
    COMPLIANCE,
    QI,
    SPONSOR,
    TENANT,
    TRUSTEE,
    api_client,
    list_ledger_entries,
    make_investor_headers,
    read_loan_facility,
    read_offering,
    read_subscription,
    read_trust,
    reprice_loan_payload,
    rent_posting_payload,
    set_clock,
    setup_operating_trust,
    setup_trust_funding,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_UUID = "00000000-0000-4000-8000-00000000dead"


class TestTrustInvestorReport:
    def test_every_reported_figure_is_derived_from_the_rows_beneath_it(self):
        """Two closed subscriptions, a 620-unit trust and a 2% reserve target.

        PRD: "The trust's own condition is available as a computed read that
        reports the `trust_id`, its `status` and `posture`, the `units_issued`
        and the `units_available` still unsold (the `total_units` minus
        `units_issued`), the `equity_raised_cents`, the
        `operating_balance_cents` and `reserve_balance_cents`, the
        `reserve_target_cents` (the property's `purchase_price_cents` multiplied
        by the trust's `reserve_target_pct`, rounded half up), the
        `reserve_variance_cents` (the `reserve_balance_cents` minus that target,
        which is negative when the reserve is short), the
        `distributions_paid_cents` (the sum of `final_amount_cents` over the
        trust's distributions in status `PAID`), and the
        `closed_investor_count` (the count of *distinct* `investor_id` values
        over the trust's `CLOSED` subscriptions, so one investor holding two
        closed subscriptions counts once)."

        Design: Corner/endpoints/trust_investor_report_computed_read_matches_rollup
        """
        deal = setup_operating_trust()

        report = validate_success(
            api_client.get_investor_report(
                deal["trust"]["id"], make_investor_headers(deal["investor_a"]["id"])
            )
        )

        assert report["trust_id"] == deal["trust"]["id"]
        assert report["status"] == "OPERATING"
        assert report["posture"] == "OPEN"
        assert report["units_issued"] == 600
        assert report["units_available"] == 20
        assert report["equity_raised_cents"] == 600_000_000
        assert report["operating_balance_cents"] == 1_098_901
        assert report["reserve_balance_cents"] == 30_000_000
        assert report["reserve_target_cents"] == 24_000_000
        assert report["reserve_variance_cents"] == 6_000_000
        assert report["distributions_paid_cents"] == 0
        assert report["closed_investor_count"] == 2


class TestMasterLeaseTerminateAction:
    def test_termination_preserves_the_history_and_withdraws_the_rent_capability(self):
        """The tenant who could remit yesterday cannot remit today.

        PRD: "Termination advances an executed lease `EXECUTED → TERMINATED`
        with an optional `reason`, and its effect is forward-looking only: rent
        stops accruing for periods that begin at or after the termination
        instant, while a lease already terminated still supplies the rent terms
        for a distribution period it covered."

        PRD: "The acting tenant's `X-User-ID` must equal the
        `master_tenant_user_id` of an `EXECUTED` lease on the target trust, or
        the request is refused with `ERR_FORBIDDEN_NOT_OWNER`; and some lease on
        the trust must be `EXECUTED`, or `ERR_MASTER_LEASE_NOT_EXECUTED`."

        PRD: "Ownership, on subscription rescission, consent recording, rent
        posting and capital-need funding: `ERR_FORBIDDEN_NOT_OWNER`."

        Design: Corner/endpoints/master_lease_terminate_action_stops_rent_postings
        """
        deal = setup_operating_trust()
        set_clock("2026-12-01T00:00:00Z")

        terminated = validate_success(
            api_client.terminate_master_lease(
                deal["lease"]["id"], TRUSTEE, {"reason": "master tenant restructuring"}
            )
        )

        assert terminated["status"] == "TERMINATED"
        assert terminated["executed_at"] == "2026-08-20T00:00:00.000Z"
        assert terminated["term_end_on"] == deal["lease"]["term_end_on"]

        refused = api_client.post_rent(
            deal["trust"]["id"],
            rent_posting_payload(rent_kind="BASE", amount_cents=22_500_000),
            TENANT,
        )
        validate_error(refused, "ERR_FORBIDDEN_NOT_OWNER", 403)

        assert read_trust(deal["trust"]["id"])["operating_balance_cents"] == 1_098_901
        assert list_ledger_entries(
            deal["trust"]["id"], entry_type="RENT_RECEIPT"
        ) == []


class TestExitConsentNeedsBothSidesOfTheJunction:
    def test_an_unknown_exit_event_is_a_not_found_even_with_a_valid_subscription(self):
        """The junction resolves its references before it records anything.

        PRD: "Payload references are resolved after the path, in the order the
        operation's input list declares them."

        Design: Corner/endpoints/exit_consent_for_unknown_exit_event_returns_not_found
        """
        deal = setup_operating_trust()

        response = api_client.create_exit_consent(
            {
                "exit_event_id": UNKNOWN_UUID,
                "subscription_id": deal["subscription_a"]["id"],
                "decision": "CONSENT",
            },
            make_investor_headers(deal["investor_a"]["id"]),
        )
        validate_error(response, "ERR_EXIT_EVENT_NOT_FOUND", 404)

        _, meta = validate_paginated(
            api_client.list_exit_consents(
                SPONSOR, params={"subscription_id": deal["subscription_a"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert read_subscription(deal["subscription_a"]["id"])["status"] == "CLOSED"


class TestRepriceIsConditionalOnTheFacilityBeingUndrawn:
    def test_a_funded_facility_refuses_the_reprice_and_no_cascade_fires(self):
        """The payload a committed facility accepts is refused once drawn.

        PRD: "A repricing request against a facility already in status `FUNDED`,
        or against a facility whose trust is in `OPERATING`, `WINDING_DOWN`,
        `TERMINATED` or `CONVERTED_LLC`, is refused with
        `ERR_REFINANCING_PROHIBITED` (422)."

        Design: Corner/endpoints/reprice_refused_once_the_facility_has_been_drawn
        """
        deal = setup_trust_funding()
        assert deal["loan"]["status"] == "FUNDED"

        response = api_client.reprice_loan_facility(
            deal["loan"]["id"], reprice_loan_payload(), TRUSTEE
        )
        validate_error(response, "ERR_REFINANCING_PROHIBITED", 422)

        facility = read_loan_facility(deal["loan"]["id"])
        assert facility["status"] == "FUNDED"
        assert facility["principal_cents"] == 720_000_000
        assert facility["rate_bps"] == 425
        assert facility["repriced_count"] == 0
        assert facility["ltv_pct"] == CANONICAL_LOAN_METRICS["ltv_pct"]

        offering = read_offering(deal["offering"]["id"])
        assert offering["status"] == "EFFECTIVE"
        assert offering["ppm_version"] == 1
        assert offering["target_equity_cents"] == (
            CANONICAL_CAPITAL_STACK["target_equity_cents"]
        )

        assert read_trust(deal["trust"]["id"])["operating_balance_cents"] == (
            720_000_000
        )


class TestFilteredListReadsWalkTheForeignKeyGraph:
    def test_every_declared_filter_reports_its_own_total_count(self):
        """Populated collections report their exact size; empty ones report zero.

        PRD: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope, where `total_count`
        is the number of rows matching the filters before pagination is applied
        and `has_more` indicates whether rows remain beyond the returned
        window."

        Design: Corner/endpoints/filtered_list_reads_walk_the_whole_foreign_key_graph
        """
        deal = setup_operating_trust()
        trust_id = deal["trust"]["id"]

        rows, meta = validate_paginated(
            api_client.list_properties(
                SPONSOR, params={"status": "ACQUIRED", "state_code": "TX"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == deal["property"]["id"]

        rows, meta = validate_paginated(
            api_client.list_trusts(
                TRUSTEE, params={"property_id": deal["property"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert rows[0]["id"] == trust_id

        rows, meta = validate_paginated(
            api_client.list_loan_facilities(
                TRUSTEE,
                params={"trust_id": trust_id, "recourse_type": "NON_RECOURSE"},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "FUNDED"
        assert rows[0]["principal_cents"] == 720_000_000

        rows, meta = validate_paginated(
            api_client.list_offerings(
                SPONSOR, params={"trust_id": trust_id, "status": "CLOSED"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == deal["offering"]["id"]

        _, meta = validate_paginated(
            api_client.list_investors(
                COMPLIANCE, params={"suitability_offering_id": deal["offering"]["id"]}
            )
        )
        assert meta["total_count"] == 2

        rows, meta = validate_paginated(
            api_client.list_exchange_files(
                QI, params={"investor_id": deal["investor_b"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "CLOSED_MATCHED"

        _, meta = validate_paginated(
            api_client.list_identifications(
                QI,
                params={"property_id": deal["property"]["id"], "status": "ACTIVE"},
            )
        )
        assert meta["total_count"] == 2

        rows, meta = validate_paginated(
            api_client.list_subscriptions(
                SPONSOR, params={"investor_id": deal["investor_a"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "CLOSED"
        assert rows[0]["closing_sequence_no"] == 1

        rows, meta = validate_paginated(
            api_client.list_master_leases(TRUSTEE, params={"trust_id": trust_id})
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "EXECUTED"

        rows, meta = validate_paginated(
            api_client.list_ledger_entries(
                TRUSTEE,
                params={"trust_id": trust_id, "entry_type": "EQUITY_CONTRIBUTION"},
            )
        )
        assert meta["total_count"] == 2
        for row in rows:
            assert row["amount_cents"] == 300_000_000
            assert row["bucket"] == "OPERATING"

        empty_reads = [
            api_client.list_distributions(TRUSTEE, params={"trust_id": trust_id}),
            api_client.list_capital_needs(TRUSTEE, params={"trust_id": trust_id}),
            api_client.list_tax_statements(SPONSOR, params={"trust_id": trust_id}),
            api_client.list_exit_events(SPONSOR, params={"trust_id": trust_id}),
        ]
        for response in empty_reads:
            rows, meta = validate_paginated(response)
            assert rows == []
            assert meta["total_count"] == 0
            assert meta["has_more"] is False
            assert meta["limit"] == 10
            assert meta["offset"] == 0

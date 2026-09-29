"""Two interval conventions that point in opposite directions.

Distribution periods are half-open, so a shared instant is not an overlap. Lease
terms are closed, so a shared single day is. Each convention is exercised at its
own touching boundary and one step inside it.
"""

from test_helpers import (
    CANONICAL_DISTRIBUTION,
    TRUSTEE,
    api_client,
    create_master_lease,
    create_master_lease_payload,
    declare_distribution,
    read_distribution,
    set_clock,
    setup_operating_with_rent_and_debt,
    setup_trust_forming,
    trust_version,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDistributionPeriodHalfOpenIntervals:
    def _two_adjacent_declared_periods(self) -> dict:
        deal = setup_operating_with_rent_and_debt()
        set_clock("2027-04-02T00:00:00Z")
        deal["d1"] = declare_distribution(
            deal["trust"]["id"],
            trust_version(deal["trust"]["id"]),
            period_start="2026-10-01T00:00:00Z",
            period_end="2027-01-01T00:00:00Z",
        )
        deal["d2"] = declare_distribution(
            deal["trust"]["id"],
            trust_version(deal["trust"]["id"]),
            period_start="2027-01-01T00:00:00Z",
            period_end="2027-04-01T00:00:00Z",
        )
        return deal

    def test_adjacent_periods_sharing_one_instant_are_both_accepted(self):
        """A touching endpoint is not an intersection.

        PRD: "The requested interval must not intersect the interval of any
        distribution on the same trust in status `DECLARED` or `PAID`, or the
        declaration is refused with `ERR_DISTRIBUTION_PERIOD_OVERLAP`; intervals
        that merely touch, the earlier `period_end` equalling the later
        `period_start`, do not intersect."

        Design: Difficulty/resource_temporal_overlap/distribution_period_half_open_adjacent_ok_overlap_rejected
        """
        deal = self._two_adjacent_declared_periods()

        assert deal["d1"]["status"] == "DECLARED"
        assert deal["d1"]["period_end"] == "2027-01-01T00:00:00.000Z"
        assert deal["d2"]["status"] == "DECLARED"
        assert deal["d2"]["period_start"] == "2027-01-01T00:00:00.000Z"
        assert deal["d1"]["provisional_amount_cents"] == (
            CANONICAL_DISTRIBUTION["provisional_amount_cents"]
        )

    def test_a_period_that_straddles_both_neighbours_is_refused(self):
        """A strict intersection with either neighbour is enough.

        PRD: "The requested interval must not intersect the interval of any
        distribution on the same trust in status `DECLARED` or `PAID`, or the
        declaration is refused with `ERR_DISTRIBUTION_PERIOD_OVERLAP`; intervals
        that merely touch, the earlier `period_end` equalling the later
        `period_start`, do not intersect."

        Design: Difficulty/resource_temporal_overlap/distribution_period_half_open_adjacent_ok_overlap_rejected
        """
        deal = self._two_adjacent_declared_periods()

        response = api_client.create_distribution(
            {
                "trust_id": deal["trust"]["id"],
                "kind": "OPERATING",
                "period_start": "2026-12-01T00:00:00Z",
                "period_end": "2027-02-01T00:00:00Z",
                "expected_trust_version": trust_version(deal["trust"]["id"]),
            },
            TRUSTEE,
        )
        validate_error(response, "ERR_DISTRIBUTION_PERIOD_OVERLAP", 409)

    def test_the_refused_declaration_leaves_only_the_two_accepted_periods(self):
        """The rejected interval never becomes a row.

        PRD: "The distribution is created in status `DECLARED` with `declared_at`
        stamped, `final_amount_cents` and `reconciliation_delta_cents` and
        `paid_at` all still empty, and the trust's `version` advances."

        Design: Difficulty/resource_temporal_overlap/distribution_period_half_open_adjacent_ok_overlap_rejected
        """
        deal = self._two_adjacent_declared_periods()

        api_client.create_distribution(
            {
                "trust_id": deal["trust"]["id"],
                "kind": "OPERATING",
                "period_start": "2026-12-01T00:00:00Z",
                "period_end": "2027-02-01T00:00:00Z",
                "expected_trust_version": trust_version(deal["trust"]["id"]),
            },
            TRUSTEE,
        )

        response = api_client.list_distributions(
            TRUSTEE, params={"trust_id": deal["trust"]["id"], "limit": 100}
        )
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {deal["d1"]["id"], deal["d2"]["id"]}
        assert read_distribution(deal["d1"]["id"])["final_amount_cents"] is None


class TestMasterLeaseClosedIntervals:
    def test_a_successor_sharing_the_incumbents_last_day_is_refused(self):
        """The overlap walk goes through the trust to the property.

        PRD: "Drafting is refused with `ERR_LEASE_TERM_OVERLAP` when the requested
        term intersects the term of any lease in status `DRAFT` or `EXECUTED` on
        any trust holding the same property, which is found by walking from each
        candidate lease's trust to that trust's property."

        Design: Difficulty/resource_temporal_overlap/master_lease_closed_interval_shared_endpoint_day_rejected
        """
        deal = setup_trust_forming()
        create_master_lease(deal["trust"]["id"])

        response = api_client.create_master_lease(
            create_master_lease_payload(
                deal["trust"]["id"],
                master_tenant_user_id="tenant-2",
                term_start_on="2033-08-31",
                term_end_on="2040-01-31",
                base_rent_annual_cents=95_000_000,
                supplemental_rent_annual_cents=1_600_000,
            ),
            TRUSTEE,
        )
        validate_error(response, "ERR_LEASE_TERM_OVERLAP", 409)

    def test_a_successor_starting_the_next_day_is_accepted(self):
        """One day clear of the incumbent's last day is enough.

        PRD: "Drafting is refused with `ERR_LEASE_TERM_OVERLAP` when the requested
        term intersects the term of any lease in status `DRAFT` or `EXECUTED` on
        any trust holding the same property, which is found by walking from each
        candidate lease's trust to that trust's property."

        Design: Difficulty/resource_temporal_overlap/master_lease_closed_interval_shared_endpoint_day_rejected
        """
        deal = setup_trust_forming()
        create_master_lease(deal["trust"]["id"])

        response = api_client.create_master_lease(
            create_master_lease_payload(
                deal["trust"]["id"],
                master_tenant_user_id="tenant-2",
                term_start_on="2033-09-01",
                term_end_on="2040-01-31",
                base_rent_annual_cents=95_000_000,
                supplemental_rent_annual_cents=1_600_000,
            ),
            TRUSTEE,
        )
        successor = validate_success(response, 201)

        assert successor["status"] == "DRAFT"

    def test_the_rejected_draft_leaves_the_incumbent_and_the_list_intact(self):
        """Only the accepted successor joins the trust's leases.

        PRD: "The lease is created in status `DRAFT`, and leases are listable and
        filterable by `trust_id`, `status` and `master_tenant_user_id`."

        Design: Difficulty/resource_temporal_overlap/master_lease_closed_interval_shared_endpoint_day_rejected
        """
        deal = setup_trust_forming()
        incumbent = create_master_lease(deal["trust"]["id"])

        api_client.create_master_lease(
            create_master_lease_payload(
                deal["trust"]["id"],
                master_tenant_user_id="tenant-2",
                term_start_on="2033-08-31",
                term_end_on="2040-01-31",
            ),
            TRUSTEE,
        )
        api_client.create_master_lease(
            create_master_lease_payload(
                deal["trust"]["id"],
                master_tenant_user_id="tenant-2",
                term_start_on="2033-09-01",
                term_end_on="2040-01-31",
            ),
            TRUSTEE,
        )

        response = api_client.list_master_leases(
            TRUSTEE, params={"trust_id": deal["trust"]["id"], "limit": 100}
        )
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 2
        assert incumbent["id"] in {row["id"] for row in rows}
        for row in rows:
            if row["id"] == incumbent["id"]:
                assert row["term_end_on"] == incumbent["term_end_on"]

"""Optimistic concurrency, the version counter, and a posture that moves mid-write.

Only two operations in this API carry a concurrency token, and each guards a
different row. Both are proved the same way: the stale attempt is refused and
persists nothing, then the identical request at the observed version succeeds.
The last case shows the same counter driving a derived gate — one cent of reserve
draw changes what the trust is allowed to do next.
"""

from test_helpers import (
    CANONICAL_DISTRIBUTION,
    CLOCK,
    SPONSOR,
    TRUSTEE,
    api_client,
    create_distribution_payload,
    create_capital_need,
    create_loan_facility,
    create_offering,
    create_property,
    create_subscription_payload,
    create_trust,
    list_ledger_entries,
    offering_version,
    read_offering,
    read_property,
    read_trust,
    set_clock,
    setup_funding_with_investor_a,
    setup_operating_with_rent_and_debt,
    setup_reserve_draw_to_floor,
    submit_ppm,
    declare_offering_effective,
    trust_version,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSubscriptionCreationGuardsTheOfferingVersion:
    def test_a_version_one_behind_is_refused_and_the_observed_version_succeeds(self):
        """The token is required, and it must match exactly.

        PRD: "Creating a subscription must carry `expected_offering_version`,
        holding the client's last observed `version` of the target offering. If
        that value does not equal the offering's current `version`, the create is
        rejected with `ERR_STALE_OFFERING_VERSION` (412)."

        PRD: "On success the offering's `units_committed` and
        `equity_committed_cents` are recomputed and its `version` advances by
        one."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_expected_offering_version_on_subscription_create_rejected
        """
        deal = setup_funding_with_investor_a()
        current = offering_version(deal["offering"]["id"])

        stale = api_client.create_subscription(
            create_subscription_payload(
                deal["offering"]["id"],
                deal["investor_a"]["id"],
                deal["exchange_file_a"]["id"],
                300,
                current - 1,
            ),
            SPONSOR,
        )
        validate_error(stale, "ERR_STALE_OFFERING_VERSION", 412)
        assert read_offering(deal["offering"]["id"])["units_committed"] == 0

        observed = read_offering(deal["offering"]["id"])["version"]
        accepted = validate_success(
            api_client.create_subscription(
                create_subscription_payload(
                    deal["offering"]["id"],
                    deal["investor_a"]["id"],
                    deal["exchange_file_a"]["id"],
                    300,
                    observed,
                ),
                SPONSOR,
            ),
            201,
        )
        assert accepted["status"] == "RESERVED"
        assert accepted["investment_amount_cents"] == 300_000_000

        offering = read_offering(deal["offering"]["id"])
        assert offering["units_committed"] == 300
        assert offering["equity_committed_cents"] == 300_000_000
        assert offering["version"] > observed


class TestDistributionDeclarationGuardsTheTrustVersion:
    def test_a_declaration_sized_against_moved_cash_is_refused(self):
        """Rent and debt service already advanced the counter this token names.

        PRD: "Declaring a distribution must carry `expected_trust_version`,
        holding the client's last observed `version` of the target trust. If that
        value does not equal the trust's current `version`, the declaration is
        rejected with `ERR_STALE_TRUST_VERSION` (412)."

        PRD: "The distribution is created in status `DECLARED` with `declared_at`
        stamped, `final_amount_cents` and `reconciliation_delta_cents` and
        `paid_at` all still empty, and the trust's `version` advances."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_expected_trust_version_on_distribution_create_rejected
        """
        deal = setup_operating_with_rent_and_debt()
        trust_id = deal["trust"]["id"]
        assert read_trust(trust_id)["operating_balance_cents"] == 16_323_901
        observed = trust_version(trust_id)

        stale = api_client.create_distribution(
            create_distribution_payload(trust_id, observed - 1), TRUSTEE
        )
        validate_error(stale, "ERR_STALE_TRUST_VERSION", 412)

        _, meta = validate_paginated(
            api_client.list_distributions(TRUSTEE, params={"trust_id": trust_id})
        )
        assert meta["total_count"] == 0

        declared = validate_success(
            api_client.create_distribution(
                create_distribution_payload(trust_id, observed), TRUSTEE
            ),
            201,
        )
        assert declared["status"] == "DECLARED"
        assert declared["provisional_amount_cents"] == (
            CANONICAL_DISTRIBUTION["provisional_amount_cents"]
        )
        assert declared["final_amount_cents"] is None
        assert declared["reconciliation_delta_cents"] is None

        assert trust_version(trust_id) > observed


class TestTheVersionCounterCountsMutationsAndNothingElse:
    def test_a_fresh_row_starts_at_one_and_a_read_never_advances_it(self):
        """Two rows, one write each, and a read wedged in between.

        PRD: "an integer that starts at 1 and increments by exactly 1 on every
        mutation of the row."

        PRD: "an ISO 8601 UTC timestamp, refreshed on every mutation of the row,
        including mutations the server performs on its own initiative when a
        cascade recomputes a derived field."

        PRD: "On success the trust copies the property's `acquired_at` into its
        own `property_acquired_at`, which becomes the start of the trust's
        depreciation holding period, and its `version` advances by one."

        Design: Corner/cross_cutting_complexity_layers/entity_version_increments_on_every_write
        """
        set_clock(CLOCK["START"])
        prop = create_property()
        dst = create_trust(prop["id"])
        assert prop["version"] == 1
        assert dst["version"] == 1
        for row in (prop, dst):
            assert row["id"]
            assert row["created_at"]
            assert row["updated_at"]

        offering = create_offering(dst["id"])
        loan = create_loan_facility(dst["id"])
        assert offering["version"] == 1
        assert loan["version"] == 1

        set_clock(CLOCK["PRE_ACQUISITION"])
        acquired = validate_success(api_client.acquire_property(prop["id"], SPONSOR))
        assert acquired["version"] == 2
        assert acquired["status"] == "ACQUIRED"
        assert acquired["acquired_at"] == "2026-08-20T00:00:00.000Z"

        # A pure read is not a mutation.
        assert read_property(prop["id"])["version"] == 2

        submit_ppm(offering["id"])
        declare_offering_effective(offering["id"], 1)
        assert read_trust(dst["id"])["version"] == 1

        opened = validate_success(api_client.open_trust_funding(dst["id"], TRUSTEE))
        assert opened["version"] == 2
        assert opened["status"] == "FUNDING"
        assert opened["property_acquired_at"] == "2026-08-20T00:00:00.000Z"


class TestTheReserveFloorIsAStrictlyLessThanBoundary:
    def test_one_further_cent_of_draw_restricts_the_trust(self):
        """Exactly at the floor is still open; one cent under is not.

        PRD: "Otherwise, if the trust's `status` is `OPERATING` and its
        `reserve_balance_cents` is strictly less than its `reserve_floor_cents`,
        the posture is `RESTRICTED`."

        PRD: "and the trust's `reserve_balance_cents` is recomputed and then its
        `posture`: a draw that leaves the reserve below `reserve_floor_cents`
        turns the trust `RESTRICTED` in the same request that drew it."

        PRD: "`RESTRICTED` is narrower: it blocks capital-need funding and both
        the declaration and the payment of a distribution whose `kind` is
        `OPERATING`, each rejected with `ERR_TRUST_RESTRICTED` (409), while
        leaving tax statements, consents and the exit workflow available."

        Design: Corner/cross_cutting_complexity_layers/reserve_draw_one_cent_below_the_floor_restricts_the_trust
        """
        deal = setup_reserve_draw_to_floor()
        trust_id = deal["trust"]["id"]
        at_floor = read_trust(trust_id)
        assert at_floor["reserve_balance_cents"] == 5_000_000
        assert at_floor["reserve_floor_cents"] == 5_000_000
        assert at_floor["posture"] == "OPEN"

        one_cent = create_capital_need(
            trust_id,
            need_type="NORMAL_REPAIR",
            amount_cents=1,
            needed_by="2026-12-31T00:00:00Z",
        )
        funded = validate_success(
            api_client.fund_capital_need(
                one_cent["id"], {"funding_source": "RESERVE"}, TRUSTEE
            )
        )
        assert funded["status"] == "FUNDED"

        restricted = read_trust(trust_id)
        assert restricted["reserve_balance_cents"] == 4_999_999
        assert restricted["posture"] == "RESTRICTED"
        assert restricted["status"] == "OPERATING"

        refused = api_client.create_distribution(
            create_distribution_payload(
                trust_id,
                trust_version(trust_id),
                period_start="2026-09-01T00:00:00Z",
                period_end="2026-10-01T00:00:00Z",
            ),
            TRUSTEE,
        )
        validate_error(refused, "ERR_TRUST_RESTRICTED", 409)

        _, meta = validate_paginated(
            api_client.list_distributions(TRUSTEE, params={"trust_id": trust_id})
        )
        assert meta["total_count"] == 0

        draws = list_ledger_entries(trust_id, entry_type="RESERVE_DRAW")
        assert len(draws) == 2
        assert sorted(entry["amount_cents"] for entry in draws) == [-25_000_000, -1]
        assert read_trust(trust_id)["status"] == "OPERATING"

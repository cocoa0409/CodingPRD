"""Operations gated by the status of an entity the payload never names.

Declaring a distribution reads the master lease; closing a subscription reads a
property identification sitting on a third entity. In both cases the request
body is identical either way and only the other row's status decides.
"""

from test_helpers import (
    CANONICAL_DISTRIBUTION,
    QI,
    SPONSOR,
    TRUSTEE,
    api_client,
    close_subscription,
    create_property,
    declare_distribution,
    file_identification,
    get_success_data,
    read_exchange_file,
    read_subscription,
    read_trust,
    revoke_identification,
    setup_operating_with_rent_and_debt,
    setup_reserved_subscription_a,
    trust_version,
    validate_error,
    validate_paginated,
)


class TestDistributionDeclarationRequiresAnExecutedLease:
    def test_declaration_is_refused_while_no_lease_on_the_trust_is_executed(self):
        """The refusal comes from the lease, not from the trust.

        PRD: "Execution is a precondition for two later capabilities: rent may
        only be remitted, and distributions may only be declared, while the trust
        has a lease in `EXECUTED` status — otherwise both are refused with
        `ERR_MASTER_LEASE_NOT_EXECUTED`."

        Design: Difficulty/cross_entity_state_dependency/distribution_declare_requires_master_lease_executed
        """
        deal = setup_operating_with_rent_and_debt()
        terminated = get_success_data(
            api_client.terminate_master_lease(deal["lease"]["id"], TRUSTEE)
        )
        assert terminated["status"] == "TERMINATED"

        response = api_client.create_distribution(
            {
                "trust_id": deal["trust"]["id"],
                "kind": "OPERATING",
                "period_start": CANONICAL_DISTRIBUTION["period_start"],
                "period_end": CANONICAL_DISTRIBUTION["period_end"],
                "expected_trust_version": trust_version(deal["trust"]["id"]),
            },
            TRUSTEE,
        )
        validate_error(response, "ERR_MASTER_LEASE_NOT_EXECUTED", 409)

        assert read_trust(deal["trust"]["id"])["status"] == "OPERATING"

    def test_the_rejected_declaration_writes_no_distribution_row(self):
        """The gate is checked before anything is created.

        PRD: "A master lease on the trust is `EXECUTED`, on distribution
        declaration and rent posting: `ERR_MASTER_LEASE_NOT_EXECUTED`."

        Design: Difficulty/cross_entity_state_dependency/distribution_declare_requires_master_lease_executed
        """
        deal = setup_operating_with_rent_and_debt()
        api_client.terminate_master_lease(deal["lease"]["id"], TRUSTEE)

        api_client.create_distribution(
            {
                "trust_id": deal["trust"]["id"],
                "kind": "OPERATING",
                "period_start": CANONICAL_DISTRIBUTION["period_start"],
                "period_end": CANONICAL_DISTRIBUTION["period_end"],
                "expected_trust_version": trust_version(deal["trust"]["id"]),
            },
            TRUSTEE,
        )

        response = api_client.list_distributions(
            TRUSTEE, params={"trust_id": deal["trust"]["id"]}
        )
        _, meta = validate_paginated(response)
        assert meta["total_count"] == 0

    def test_the_identical_request_succeeds_while_the_lease_is_executed(self):
        """Nothing about the payload changes — only the lease's status.

        PRD: "Termination advances an executed lease `EXECUTED → TERMINATED` with
        an optional `reason`, and its effect is forward-looking only: rent stops
        accruing for periods that begin at or after the termination instant, while
        a lease already terminated still supplies the rent terms for a
        distribution period it covered."

        Design: Difficulty/cross_entity_state_dependency/distribution_declare_requires_master_lease_executed
        """
        deal = setup_operating_with_rent_and_debt()
        assert deal["lease"]["status"] == "EXECUTED"

        distribution = declare_distribution(
            deal["trust"]["id"], trust_version(deal["trust"]["id"])
        )

        assert distribution["status"] == "DECLARED"
        assert distribution["provisional_amount_cents"] == (
            CANONICAL_DISTRIBUTION["provisional_amount_cents"]
        )


class TestSubscriptionCloseRequiresAnIdentificationForTheTrustProperty:
    def _reserved_with_two_identifications(self) -> dict:
        deal = setup_reserved_subscription_a(300)
        other_property = create_property(name="Alamo Flex Park")
        deal["other_property"] = other_property
        deal["identification_other"] = file_identification(
            deal["exchange_file_a"]["id"], other_property["id"]
        )
        return deal

    def test_revoking_the_trust_property_row_leaves_the_file_identified(self):
        """The file follows its identification set, not any single row.

        PRD: "Revoking the last `ACTIVE` row on a file walks it back
        `IDENTIFIED → OPEN`, which is the file's revision loop — identification can
        be unwound while the forty-five-day window is still open."

        Design: Difficulty/cross_entity_state_dependency/subscription_close_requires_active_identification_for_trust_property
        """
        deal = self._reserved_with_two_identifications()

        revoked = revoke_identification(
            deal["identification_a"]["id"],
            reason="sponsor re-papering the P1 identification",
        )

        assert revoked["status"] == "REVOKED"
        assert read_exchange_file(deal["exchange_file_a"]["id"])["status"] == (
            "IDENTIFIED"
        )

    def test_the_close_is_refused_once_the_trust_property_is_no_longer_identified(self):
        """A taxpayer may not buy into a property it never identified.

        PRD: "The exchange file has an active identification naming the trust's
        property, on subscription creation and closing:
        `ERR_IDENTIFICATION_MISSING_FOR_TRUST`."

        Design: Difficulty/cross_entity_state_dependency/subscription_close_requires_active_identification_for_trust_property
        """
        deal = self._reserved_with_two_identifications()
        revoke_identification(deal["identification_a"]["id"])

        response = api_client.close_subscription(deal["subscription_a"]["id"], SPONSOR)
        validate_error(response, "ERR_IDENTIFICATION_MISSING_FOR_TRUST", 422)

        assert read_subscription(deal["subscription_a"]["id"])["status"] == "RESERVED"
        assert read_trust(deal["trust"]["id"])["units_issued"] == 0

    def test_refiling_the_identification_lets_the_same_close_succeed(self):
        """The re-filed row takes the next ordinal on the file.

        PRD: "The server stamps `identified_at` from the logical clock and assigns
        a 1-based `sequence_no` within the file, ordinals being assigned in
        `identified_at` ascending order with `created_at` ascending as the
        tie-break."

        Design: Difficulty/cross_entity_state_dependency/subscription_close_requires_active_identification_for_trust_property
        """
        deal = self._reserved_with_two_identifications()
        revoke_identification(deal["identification_a"]["id"])

        refiled = get_success_data(
            api_client.create_identification(
                {
                    "exchange_file_id": deal["exchange_file_a"]["id"],
                    "property_id": deal["property"]["id"],
                    "fair_market_value_cents": 1_200_000_000,
                },
                QI,
            )
        )
        assert refiled["status"] == "ACTIVE"
        assert refiled["property_id"] == deal["property"]["id"]
        assert refiled["sequence_no"] == 3

        closed = close_subscription(deal["subscription_a"]["id"])
        assert closed["status"] == "CLOSED"
        assert closed["closing_sequence_no"] == 1
        trust = read_trust(deal["trust"]["id"])
        assert trust["units_issued"] == 300
        assert trust["equity_raised_cents"] == 300_000_000

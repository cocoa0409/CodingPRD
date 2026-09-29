"""Who may act, on which row, and which half of a workflow they already took.

Authority is checked in three distinct ways here: against the role list, against
the row the caller claims to own, and against the caller's own earlier
participation in the same workflow. All three sit above every state and fiscal
rule, so each refusal below arrives while the request would otherwise have been
perfectly reasonable.
"""

from test_helpers import (
    CANONICAL_OPERATING_TRUST,
    COMPLIANCE,
    QI,
    SPONSOR,
    TENANT,
    TRUSTEE,
    api_client,
    create_capital_need_payload,
    create_distribution_payload,
    create_exchange_file,
    create_investor,
    create_property_payload,
    create_loan_facility_payload,
    create_subscription_payload,
    file_identification,
    list_ledger_entries,
    make_investor_headers,
    make_sponsor_headers,
    offering_version,
    read_investor,
    read_offering,
    read_subscription,
    read_trust,
    setup_operating_trust,
    setup_reserved_subscription_a,
    setup_trust_funding,
    trust_version,
    validate_error,
    validate_paginated,
    validate_success,
)

class TestExclusiveWritesAreClosedToEveryOtherRole:
    def test_five_exclusive_operations_each_refuse_a_role_that_does_not_hold_them(self):
        """Every request is otherwise well formed; only the role is wrong.

        PRD: "A request whose role is recognised but is not among the roles
        authorised for the target operation is rejected with `ERR_UNAUTHORIZED`
        (403)."

        PRD: "When a request violates more than one rule, exactly one error comes
        back: the violation with the lowest priority number in the ladder below."

        PRD: "Segregation of duties, on declaring an offering effective and on
        closing a subscription: `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/exclusive_operation_denied_to_every_other_role
        """
        deal = setup_trust_funding()
        investor = create_investor()
        exchange_file = create_exchange_file(investor["id"])
        file_identification(exchange_file["id"], deal["property"]["id"])
        observed_trust_version = trust_version(deal["trust"]["id"])

        validate_error(
            api_client.create_property(
                create_property_payload(name="Alamo Flex Park"), TRUSTEE
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        # The offering is already EFFECTIVE and this sponsor submitted its
        # memorandum, so the role rung has to fire ahead of both of those.
        validate_error(
            api_client.declare_offering_effective(
                deal["offering"]["id"], {"acknowledged_ppm_version": 1}, SPONSOR
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        validate_error(
            api_client.create_subscription(
                create_subscription_payload(
                    deal["offering"]["id"],
                    investor["id"],
                    exchange_file["id"],
                    300,
                    offering_version(deal["offering"]["id"]),
                ),
                QI,
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        validate_error(
            api_client.create_distribution(
                create_distribution_payload(
                    deal["trust"]["id"], observed_trust_version
                ),
                make_investor_headers(investor["id"]),
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        validate_error(
            api_client.create_loan_facility(
                create_loan_facility_payload(
                    deal["trust"]["id"], lender_name="Tenant Capital"
                ),
                TENANT,
            ),
            "ERR_UNAUTHORIZED",
            403,
        )

        _, meta = validate_paginated(api_client.list_properties(SPONSOR))
        assert meta["total_count"] == 1
        _, meta = validate_paginated(
            api_client.list_loan_facilities(
                TRUSTEE, params={"trust_id": deal["trust"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        _, meta = validate_paginated(
            api_client.list_subscriptions(
                SPONSOR, params={"offering_id": deal["offering"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        _, meta = validate_paginated(
            api_client.list_distributions(
                TRUSTEE, params={"trust_id": deal["trust"]["id"]}
            )
        )
        assert meta["total_count"] == 0

        offering = read_offering(deal["offering"]["id"])
        assert offering["status"] == "EFFECTIVE"
        assert offering["ppm_version"] == 1


class TestOwnershipIsCheckedAgainstTheRowNotTheRole:
    def test_one_beneficial_owner_cannot_unwind_anothers_subscription(self):
        """A genuine investor identity is still the wrong investor identity.

        PRD: "An ownership violation — an `Investor` acting on a subscription,
        exchange file or consent that is not its own, or a `MasterTenant` acting
        on a trust for which it does not hold the executed master lease — is
        rejected with `ERR_FORBIDDEN_NOT_OWNER` (403)."

        PRD: "Ownership, on subscription rescission, consent recording, rent
        posting and capital-need funding: `ERR_FORBIDDEN_NOT_OWNER`."

        PRD: "The acting `Investor` must be the subscription's own `investor_id`,
        the subscription must be `CLOSED`, and the logical clock must be at or
        before the `rescission_deadline`, that boundary instant still being
        inside the window; arriving later is `ERR_RESCISSION_WINDOW_CLOSED`."

        Design: Corner/rbac/investor_cannot_rescind_another_investors_subscription
        """
        deal = setup_operating_trust()

        response = api_client.rescind_subscription(
            deal["subscription_a"]["id"],
            make_investor_headers(deal["investor_b"]["id"]),
        )
        # Subscription A's own window shut on 2026-09-20, yet ownership is
        # rung 3 and the window rule is rung 27, so this is not that error.
        validate_error(response, "ERR_FORBIDDEN_NOT_OWNER", 403)

        subscription = read_subscription(deal["subscription_a"]["id"])
        assert subscription["status"] == "CLOSED"
        assert subscription["investor_id"] == deal["investor_a"]["id"]

        trust = read_trust(deal["trust"]["id"])
        assert trust["units_issued"] == CANONICAL_OPERATING_TRUST["units_issued"]
        assert trust["equity_raised_cents"] == (
            CANONICAL_OPERATING_TRUST["equity_raised_cents"]
        )
        assert list_ledger_entries(deal["trust"]["id"], entry_type="REVERSAL") == []


class TestSegregationOfDutiesIsPerUserNotPerRole:
    def test_the_officer_who_approved_the_investor_may_not_take_the_money(self):
        """The same operation, the same role, two different acting user ids.

        PRD: "A segregation-of-duties violation, where the acting `X-User-ID` has
        already performed the conflicting half of the same workflow, is rejected
        with `ERR_SEGREGATION_OF_DUTIES` (403); the two conflicts are declaring
        effective an offering whose memorandum the same user submitted, and
        closing a subscription whose investor suitability the same user
        approved."

        PRD: "and the acting sponsor's `X-User-ID` to differ from the investor's
        `suitability_reviewed_by_user_id` — the officer who blessed the investor
        may not also be the person who takes the money, and a collision is
        `ERR_SEGREGATION_OF_DUTIES`."

        PRD: "The subscription's `closed_at` is stamped from the logical clock,
        its `closing_sequence_no` is assigned, and its `rescission_deadline` is
        set to `closed_at` plus the offering's `rescission_window_days` days."

        Design: Corner/rbac/suitability_reviewer_cannot_also_close_the_subscription
        """
        deal = setup_reserved_subscription_a()
        assert read_investor(deal["investor_a"]["id"])[
            "suitability_reviewed_by_user_id"
        ] == "compliance-1"

        conflicted = api_client.close_subscription(
            deal["subscription_a"]["id"], make_sponsor_headers("compliance-1")
        )
        validate_error(conflicted, "ERR_SEGREGATION_OF_DUTIES", 403)
        assert read_subscription(deal["subscription_a"]["id"])["status"] == "RESERVED"

        closed = validate_success(
            api_client.close_subscription(deal["subscription_a"]["id"], SPONSOR)
        )
        assert closed["status"] == "CLOSED"
        assert closed["closing_sequence_no"] == 1
        assert closed["closed_at"] == "2026-08-20T00:00:00.000Z"

        assert read_investor(deal["investor_a"]["id"])[
            "suitability_reviewed_by_user_id"
        ] == "compliance-1"

        trust = read_trust(deal["trust"]["id"])
        assert trust["units_issued"] == 300
        assert trust["equity_raised_cents"] == 300_000_000


class TestTheOneWriteTwoOperatingRolesShare:
    def test_the_trustee_and_the_master_tenant_both_record_a_need(self):
        """Identifying work is not spending money, so both sides may raise it.

        PRD: "Capital needs are recorded by either a `Trustee` or a
        `MasterTenant` against a `trust_id`, naming the `need_type` —
        `NORMAL_REPAIR`, `TENANT_IMPROVEMENT` or `STRUCTURAL_CAPEX` — the
        `amount_cents` of the work (at least 1) and the `needed_by` date the work
        must be funded by."

        PRD: "The need is created in status `IDENTIFIED` with `funding_source`
        and `funded_at` empty."

        Design: Corner/rbac/trustee_and_master_tenant_share_capital_need_creation
        """
        deal = setup_operating_trust()
        trust_id = deal["trust"]["id"]

        by_trustee = validate_success(
            api_client.create_capital_need(
                create_capital_need_payload(
                    trust_id,
                    need_type="NORMAL_REPAIR",
                    amount_cents=1_500_000,
                    needed_by="2027-02-28T00:00:00Z",
                ),
                TRUSTEE,
            ),
            201,
        )
        by_tenant = validate_success(
            api_client.create_capital_need(
                create_capital_need_payload(
                    trust_id,
                    need_type="TENANT_IMPROVEMENT",
                    amount_cents=2_500_000,
                    needed_by="2027-02-28T00:00:00Z",
                ),
                TENANT,
            ),
            201,
        )

        for need in (by_trustee, by_tenant):
            assert need["status"] == "IDENTIFIED"
            assert need["funding_source"] is None
            assert need["funded_at"] is None
        assert by_trustee["amount_cents"] == 1_500_000
        assert by_tenant["amount_cents"] == 2_500_000

        _, meta = validate_paginated(
            api_client.list_capital_needs(COMPLIANCE, params={"trust_id": trust_id})
        )
        assert meta["total_count"] == 2

        trust = read_trust(trust_id)
        assert trust["reserve_balance_cents"] == (
            CANONICAL_OPERATING_TRUST["reserve_balance_cents"]
        )
        assert trust["operating_balance_cents"] == (
            CANONICAL_OPERATING_TRUST["operating_balance_cents"]
        )

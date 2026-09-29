"""
Who may act, who may read, and who may not act twice in the same matter.

The office roles are peers: none inherits another's exclusive writes. Investors
see the production-level picture and nothing of each other. And the two control
pairs — submitter/certifier and issuer/settler — must be different people even
when the second person holds exactly the right role.
"""

from prd_bench_local_runner.testing import (
    build_user_headers,
    get_success_data,
    validate_error,
)

from test_helpers import (
    COMPTROLLER_HEADERS,
    COMPTROLLER_USER_ID,
    COUNSEL_HEADERS,
    GM_HEADERS,
    GM_USER_ID,
    PRODUCER_HEADERS,
    PRODUCER_USER_ID,
    ApiClient,
    ApiErrorId,
    Role,
    factories,
    fixtures,
    make_investor_headers,
)


class TestExclusiveOperations:
    """Each office write belongs to one role, and holding another is not enough."""

    def test_the_five_exclusive_writes_are_refused_to_the_wrong_office(
        self, api: ApiClient
    ):
        """Every probe is refused on the role alone, with the row in the right state.

        "A `Comptroller` is the production comptroller: they release escrowed
        capital, activate operating budgets, certify and dispute and void wraps,
        allocate licensing income to the ledger, declare and pay investor
        distributions, and settle the closing notice."

        "`SyndicationCounsel` runs the offering — opening the offering axis,
        drafting and making effective and withdrawing the offering instrument,
        registering investors and recording their accreditation, and processing
        subscriptions through return-for-cure, acceptance and rescission."

        "A `LeadProducer` approves the capitalization budget, advances the
        production's operating calendar, converts the royalty structure to a pool,
        terminates and reinstates participations, and makes the closing decision."

        Design: Corner/rbac/exclusive_operations_are_rejected_for_the_other_four_roles
        """
        world = fixtures.base_world(api)

        validate_error(
            api.open_offering(world.production_id, COMPTROLLER_HEADERS),
            ApiErrorId.FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.approve_budget(world.production_id, GM_HEADERS),
            ApiErrorId.FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.create_theatre(
                factories.theatre_payload(
                    name="Shubert Theatre",
                    seat_count=1400,
                    top_ticket_price_cents=21900,
                ),
                COUNSEL_HEADERS,
            ),
            ApiErrorId.FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.declare_investor_distribution(
                factories.distribution_payload(
                    world.production_id, 1_000, world.production_version()
                ),
                PRODUCER_HEADERS,
            ),
            ApiErrorId.FORBIDDEN_ROLE,
            403,
        )
        validate_error(
            api.convert_royalties_to_pool(world.production_id, COMPTROLLER_HEADERS),
            ApiErrorId.FORBIDDEN_ROLE,
            403,
        )

        production = world.production()
        assert production["offering_status"] == "DRAFT"
        assert production["royalty_basis"] == "FIXED_GROSS"
        assert production["budget_status"] == "DRAFT"
        assert production["version"] == 1


class TestSharedProductionRead:
    """The production file and the recoupment report are readable by all five."""

    def test_all_five_roles_read_the_row_but_break_even_stays_an_office_read(
        self, api: ApiClient
    ):
        """The investor sees the file and the report, and is refused the analysis.

        "Confidentiality runs the other way. Investors see the production-level
        picture — the production file with its rolled-up ledger, the recoupment
        report, offering documents, licensing income, distributions and closing
        notices are all readable by the `Investor` role — but the party-level
        detail of other investors is not."

        "Nor can an investor read a house record, a budget line, an operating
        budget, a royalty participant, a weekly wrap, a royalty allocation, a
        theatre engagement, or a break-even analysis; those are management
        artifacts."

        Design: Corner/rbac/every_role_including_investor_can_read_the_production_row
        """
        world = fixtures.base_world(api)
        investor = get_success_data(
            api.create_investor(
                factories.investor_payload(
                    legal_name="Amelia Hart", contact_email="amelia.hart@example.com"
                ),
                COUNSEL_HEADERS,
            ),
            201,
        )
        investor_headers = make_investor_headers(investor["id"])

        for headers in (
            GM_HEADERS,
            COMPTROLLER_HEADERS,
            COUNSEL_HEADERS,
            PRODUCER_HEADERS,
            investor_headers,
        ):
            row = get_success_data(
                api.get_production(world.production_id, headers), 200
            )
            assert row["id"] == world.production_id
            assert row["version"] == 1

        report = get_success_data(
            api.get_recoupment_report(world.production_id, investor_headers), 200
        )
        assert report["production_id"] == world.production_id

        validate_error(
            api.get_break_even_analysis(world.production_id, investor_headers),
            ApiErrorId.FORBIDDEN_ROLE,
            403,
        )


class TestInvestorConfidentiality:
    """Ownership is checked against the acting user, not against the role."""

    def test_one_investor_cannot_read_the_other_investors_records(
        self, api: ApiClient
    ):
        """The same three reads are refused to the stranger and served to the owner.

        "Attempting an operation for which the role is not authorized at all
        yields `ERR_FORBIDDEN_ROLE`; attempting an operation the role may perform,
        but on somebody else's record, yields `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/investor_cannot_read_another_investors_syndication_records
        """
        world = fixtures.capitalized_world(api)
        owner_headers = world.investor_headers or {}
        subscription_id = world.subscription_id or ""
        account = fixtures.sole_account(world)

        stranger_id = get_success_data(
            api.create_investor(
                factories.investor_payload(
                    legal_name="Rufus Blackwood",
                    contact_email="rufus.blackwood@example.com",
                ),
                COUNSEL_HEADERS,
            ),
            201,
        )["id"]
        stranger_headers = make_investor_headers(stranger_id)

        validate_error(
            api.get_subscription(subscription_id, stranger_headers),
            ApiErrorId.NOT_RESOURCE_OWNER,
            403,
        )
        owned_subscription = get_success_data(
            api.get_subscription(subscription_id, owner_headers), 200
        )
        assert owned_subscription["id"] == subscription_id
        assert owned_subscription["status"] == "ACCEPTED"
        assert owned_subscription["amount_cents"] == 120_000_000

        validate_error(
            api.get_investor_account(account["id"], stranger_headers),
            ApiErrorId.NOT_RESOURCE_OWNER,
            403,
        )
        owned_account = get_success_data(
            api.get_investor_account(account["id"], owner_headers), 200
        )
        assert owned_account["investor_id"] == world.investor_id
        assert owned_account["units_total"] == 1
        assert owned_account["ownership_pct"] == 1.0

        validate_error(
            api.get_investor(world.investor_id or "", stranger_headers),
            ApiErrorId.NOT_RESOURCE_OWNER,
            403,
        )


class TestSubscribingForAnotherParty:
    """On create, ownership is read out of the body rather than a stored row."""

    def test_acting_for_another_investor_is_refused_before_the_compliance_gate(
        self, api: ApiClient
    ):
        """The ownership refusal outranks the accreditation refusal on the same body.

        "The investor supplies the `offering_document_id` of the instrument being
        subscribed under, their own `investor_id` — which must equal the
        `X-User-ID` on the request — and a `units` count of at least 1."

        "**Resource ownership.** The `Investor` role owns the record it is acting
        on, else `ERR_NOT_RESOURCE_OWNER` (403)."

        Design: Corner/rbac/investor_cannot_subscribe_on_behalf_of_another_investor
        """
        world = fixtures.base_world(api)
        fixtures.open_offering(world)
        fixtures.with_effective_document(world)
        document_id = world.offering_document_id or ""

        accredited_id = fixtures.new_accredited_investor(world)
        unverified = get_success_data(
            api.create_investor(
                factories.investor_payload(
                    legal_name="Rufus Blackwood",
                    contact_email="rufus.blackwood@example.com",
                ),
                COUNSEL_HEADERS,
            ),
            201,
        )
        assert unverified["accreditation_status"] == "UNVERIFIED"

        # Acting for somebody else: refused on ownership, never on accreditation.
        validate_error(
            api.create_subscription(
                factories.subscription_payload(document_id, unverified["id"], units=1),
                make_investor_headers(accredited_id),
            ),
            ApiErrorId.NOT_RESOURCE_OWNER,
            403,
        )

        # Acting for itself, the same body now reaches the securities gate.
        validate_error(
            api.create_subscription(
                factories.subscription_payload(document_id, unverified["id"], units=1),
                make_investor_headers(unverified["id"]),
            ),
            ApiErrorId.INVESTOR_NOT_ACCREDITED,
            422,
        )

        created = get_success_data(
            api.create_subscription(
                factories.subscription_payload(document_id, accredited_id, units=1),
                make_investor_headers(accredited_id),
            ),
            201,
        )
        assert created["status"] == "SUBMITTED"
        assert created["investor_id"] == accredited_id
        assert created["amount_cents"] == 120_000_000


class TestWrapDutySegregation:
    """The wrap's submitter may not certify it, whatever role they hold."""

    def test_the_submitting_operator_cannot_certify_in_the_comptroller_role(
        self, api: ApiClient
    ):
        """The refusal fires no cascade, and a second operator certifies cleanly.

        "A weekly wrap must be certified by an operator whose `X-User-ID` differs
        from the `submitted_by_user_id` recorded when the wrap was submitted."

        Design: Corner/rbac/wrap_certifier_must_not_be_the_operator_who_submitted_it
        """
        world = fixtures.running_world(api)
        fixtures.with_submitted_standard_week(world)
        wrap_id = world.wrap_id or ""

        validate_error(
            api.certify_weekly_wrap(
                wrap_id, build_user_headers(GM_USER_ID, Role.COMPTROLLER)
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES,
            403,
        )

        untouched = get_success_data(
            api.get_weekly_wrap(wrap_id, COMPTROLLER_HEADERS), 200
        )
        assert untouched["status"] == "SUBMITTED"
        assert untouched["submitted_by_user_id"] == GM_USER_ID
        assert untouched["certified_by_user_id"] is None
        assert untouched["version"] == 2

        certified = fixtures.certify_wrap(world, wrap_id)
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_by_user_id"] == COMPTROLLER_USER_ID


class TestClosingDutySegregation:
    """The notice's issuer may not settle it, and settlement is the only way out."""

    def test_the_issuing_operator_cannot_settle_the_notice_it_posted(
        self, api: ApiClient
    ):
        """The refused settlement leaves the calendar axis short of its terminal state.

        "A closing notice must be settled by an operator whose `X-User-ID` differs
        from the `issued_by_user_id` recorded when the notice was posted."

        Design: Corner/rbac/closing_settler_must_not_be_the_operator_who_issued_the_notice
        """
        world = fixtures.running_world(api)
        fixtures.with_issued_closing_notice(world)
        notice_id = world.closing_notice_id or ""

        validate_error(
            api.settle_closing_notice(
                notice_id,
                factories.settle_payload(5_000_000),
                build_user_headers(PRODUCER_USER_ID, Role.COMPTROLLER),
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES,
            403,
        )

        mid = world.production()
        assert mid["operating_status"] == "CLOSING_NOTICE"
        assert mid["version"] == 8

        settled = get_success_data(fixtures.settle_closing_notice(world), 200)
        assert settled["status"] == "SETTLED"
        assert settled["issued_by_user_id"] == PRODUCER_USER_ID
        assert settled["settled_by_user_id"] == COMPTROLLER_USER_ID
        assert settled["closing_costs_cents"] == 5_000_000

        assert world.production()["operating_status"] == "CLOSED"

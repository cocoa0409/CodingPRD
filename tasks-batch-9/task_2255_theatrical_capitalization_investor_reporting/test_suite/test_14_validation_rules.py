"""
Each declared validation rule at the exact input where it starts and stops firing.

Where a rule is a threshold, both sides of it are exercised in the same test, so
a refusal is never mistaken for a rule that refuses everything. Where two rules
are violated at once, the reported code proves which one the documented order
puts first.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    COMPTROLLER_HEADERS,
    COUNSEL_HEADERS,
    GM_HEADERS,
    PRODUCER_HEADERS,
    UNKNOWN_UUID,
    ApiClient,
    ApiErrorId,
    assert_no_write,
    factories,
    fixtures,
)


class TestOfferingInstrumentAgreement:
    """The paper has to match the producing entity's legal form."""

    def test_an_lp_production_cannot_be_papered_on_an_llc_agreement(
        self, api: ApiClient
    ):
        """The mismatched instrument is refused and never persisted.

        "Its `doc_type` is either `LP_AGREEMENT` or `LLC_OPERATING_AGREEMENT`, and
        it must agree with the producing entity's legal form: an `LP` production
        requires `LP_AGREEMENT` and an `LLC` production requires
        `LLC_OPERATING_AGREEMENT`. A mismatch in either direction is rejected with
        `ERR_OFFERING_TYPE_MISMATCH` (HTTP 422)."

        Design: Corner/validations/offering_document_type_must_match_entity_form
        """
        world = fixtures.base_world(api)
        fixtures.open_offering(world)
        assert world.production()["offering_entity_type"] == "LP"

        validate_error(
            api.create_offering_document(
                factories.offering_document_payload(
                    world.production_id, doc_type="LLC_OPERATING_AGREEMENT"
                ),
                COUNSEL_HEADERS,
            ),
            ApiErrorId.OFFERING_TYPE_MISMATCH,
        )

        matching = get_success_data(
            api.create_offering_document(
                factories.offering_document_payload(
                    world.production_id, doc_type="LP_AGREEMENT"
                ),
                COUNSEL_HEADERS,
            ),
            201,
        )
        assert matching["doc_type"] == "LP_AGREEMENT"
        assert matching["status"] == "DRAFT"
        assert matching["version"] == 1

        _, meta = validate_paginated(
            api.list_offering_documents(
                COUNSEL_HEADERS, {"production_id": world.production_id}
            )
        )
        assert meta["total_count"] == 1

    def test_a_lapsed_window_blocks_the_instrument_from_going_effective(
        self, api: ApiClient
    ):
        """The document stays DRAFT rather than sweeping itself to EXPIRED.

        "And the current logical UTC date must fall inside the inclusive window
        from `effective_date` through `expiration_date`; a date before the window
        opens or after it closes yields `ERR_OFFERING_EXPIRED` (HTTP 422)."

        Design: Corner/validations/expired_offering_window_blocks_make_effective
        """
        world = fixtures.base_world(api)
        fixtures.open_offering(world)
        document = get_success_data(
            api.create_offering_document(
                factories.offering_document_payload(
                    world.production_id,
                    effective_date="2026-07-15",
                    expiration_date="2026-08-10",
                ),
                COUNSEL_HEADERS,
            ),
            201,
        )

        world.set_clock("2026-08-11")
        validate_error(
            api.make_offering_document_effective(document["id"], COUNSEL_HEADERS),
            ApiErrorId.OFFERING_EXPIRED,
        )

        after = get_success_data(
            api.get_offering_document(document["id"], COUNSEL_HEADERS), 200
        )
        # The lazy sweep to EXPIRED applies only to documents that reached EFFECTIVE.
        assert after["status"] == "DRAFT"
        assert after["version"] == 1


class TestSingleConversionConstraint:
    """The royalty basis is a one-way latch."""

    def test_a_second_conversion_is_refused_and_writes_nothing(self, api: ApiClient):
        """The basis and the recomputed share both stand exactly as they were.

        "Because it is one-way, a second conversion request against a production
        whose `royalty_basis` already reads `POOL` is rejected with
        `ERR_ROYALTY_BASIS_ALREADY_POOL` (HTTP 409)."

        Design: Corner/validations/royalty_basis_converts_only_once
        """
        world = fixtures.base_world(api)
        participant = get_success_data(
            api.create_royalty_participant(
                factories.participant_payload(world.production_id, pool_points=4),
                GM_HEADERS,
            ),
            201,
        )

        converted = get_success_data(
            api.convert_royalties_to_pool(world.production_id, PRODUCER_HEADERS), 200
        )
        assert converted["royalty_basis"] == "POOL"
        assert converted["total_pool_points"] == 4
        assert converted["version"] == 3

        validate_error(
            api.convert_royalties_to_pool(world.production_id, PRODUCER_HEADERS),
            ApiErrorId.ROYALTY_BASIS_ALREADY_POOL,
        )

        after = world.production()
        assert_no_write(converted, after)
        assert after["royalty_basis"] == "POOL"
        assert after["version"] == 3

        held = get_success_data(
            api.get_royalty_participant(participant["id"], GM_HEADERS), 200
        )
        assert held["pool_share_pct"] == 1.0
        assert held["status"] == "ACTIVE"


class TestClosingNoticeRules:
    """Uniqueness, the notice period, and the back-dating ban."""

    def test_a_second_notice_is_refused_while_one_is_still_issued(
        self, api: ApiClient
    ):
        """Its own dates are impeccable; the standing notice is what stops it.

        "The production may not already hold a notice in `ISSUED` status, else
        `ERR_CLOSING_NOTICE_ALREADY_ISSUED` (HTTP 409)."

        Design: Corner/validations/second_closing_notice_while_one_is_issued_rejected
        """
        world = fixtures.running_world(api)
        fixtures.with_issued_closing_notice(
            world, notice_date="2026-08-01", final_performance_date="2026-08-20"
        )
        before = world.production()
        assert before["operating_status"] == "CLOSING_NOTICE"
        assert before["version"] == 8

        validate_error(
            api.create_closing_notice(
                factories.closing_notice_payload(
                    world.production_id,
                    "2026-08-01",
                    "2026-08-25",
                    reason="SCHEDULED_END",
                ),
                PRODUCER_HEADERS,
            ),
            ApiErrorId.CLOSING_NOTICE_ALREADY_ISSUED,
        )

        rows, meta = validate_paginated(
            api.list_closing_notices(
                PRODUCER_HEADERS, {"production_id": world.production_id}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == world.closing_notice_id
        assert rows[0]["status"] == "ISSUED"
        assert_no_write(before, world.production())

    def test_thirteen_days_of_notice_and_a_same_day_close_are_both_too_short(
        self, api: ApiClient
    ):
        """The count is whole days against the production's configured minimum.

        "And the notice period must be long enough: the system computes
        `notice_days` as the whole days from `notice_date` to
        `final_performance_date`, and that count must be at least the production's
        `closing_notice_min_days`, else `ERR_INSUFFICIENT_CLOSING_NOTICE` (HTTP
        422)."

        Design: Corner/validations/closing_notice_shorter_than_minimum_rejected
        """
        world = fixtures.running_world(api)
        before = world.production()
        assert before["closing_notice_min_days"] == 14

        for final_performance_date in ("2026-08-14", "2026-08-01"):
            validate_error(
                api.create_closing_notice(
                    factories.closing_notice_payload(
                        world.production_id, "2026-08-01", final_performance_date
                    ),
                    PRODUCER_HEADERS,
                ),
                ApiErrorId.INSUFFICIENT_CLOSING_NOTICE,
            )

        after = world.production()
        assert_no_write(before, after)
        assert after["operating_status"] == "RUNNING"
        assert after["version"] == 7

    def test_exactly_the_minimum_notice_is_long_enough(self, api: ApiClient):
        """Fourteen days clears a fourteen-day minimum and the cascade runs.

        "Posting the notice cascades three hops. The production's
        `operating_status` moves to `CLOSING_NOTICE`, which is admissible from
        either `PREVIEWS` or `RUNNING` and from nowhere else."

        Design: Corner/validations/closing_notice_at_exactly_the_minimum_passes
        """
        world = fixtures.running_world(api)
        fixtures.with_reserve_line(world, 20_000_000)

        notice = get_success_data(
            api.create_closing_notice(
                factories.closing_notice_payload(
                    world.production_id,
                    "2026-08-01",
                    "2026-08-15",
                    reason="SCHEDULED_END",
                ),
                PRODUCER_HEADERS,
            ),
            201,
        )
        assert notice["notice_days"] == 14
        assert notice["status"] == "ISSUED"
        assert notice["reason"] == "SCHEDULED_END"
        # PRD 3.9 commits only `closing_costs_cents` to reading null before
        # settlement: "that field reads null on any notice not yet settled".
        assert notice["closing_costs_cents"] is None
        assert notice["settled_by_user_id"] is None

        production = world.production()
        assert production["operating_status"] == "CLOSING_NOTICE"
        assert production["budget_committed_cents"] == 20_000_000
        assert production["version"] == 9

        assert (
            get_success_data(
                api.get_budget_line(world.reserve_line_id or "", GM_HEADERS), 200
            )["commitment_status"]
            == "COMMITTED"
        )

    def test_a_notice_dated_yesterday_is_refused_and_one_dated_today_is_not(
        self, api: ApiClient
    ):
        """The comparison is against the logical clock, not the performance date.

        "The `notice_date` may not be earlier than the current logical UTC date —
        you cannot back-date a closing notice — else `ERR_NOTICE_DATE_IN_PAST`
        (HTTP 422)."

        Design: Corner/validations/closing_notice_dated_before_today_rejected
        """
        world = fixtures.running_world(api)
        world.set_clock("2026-08-05")

        validate_error(
            api.create_closing_notice(
                factories.closing_notice_payload(
                    world.production_id, "2026-08-04", "2026-08-25", reason="VENUE_LOSS"
                ),
                PRODUCER_HEADERS,
            ),
            ApiErrorId.NOTICE_DATE_IN_PAST,
        )

        today = get_success_data(
            api.create_closing_notice(
                factories.closing_notice_payload(
                    world.production_id, "2026-08-05", "2026-08-25", reason="VENUE_LOSS"
                ),
                PRODUCER_HEADERS,
            ),
            201,
        )
        assert today["notice_date"] == "2026-08-05"
        assert today["notice_days"] == 20
        assert today["status"] == "ISSUED"


class TestCapitalizationCeiling:
    """The budget ceiling is collective and inclusive of the target."""

    def test_one_cent_over_the_target_is_refused_and_landing_on_it_is_not(
        self, api: ApiClient
    ):
        """100,000,000 plus 20,000,001 breaches; plus 20,000,000 lands exactly.

        "The fiscal gate on the capitalization budget applies at line creation
        only: after the new line is taken into account, the production's
        `budget_total_cents` may not exceed its `capitalization_target_cents`. A
        line that would breach the target is rejected with
        `ERR_BUDGET_EXCEEDS_CAPITALIZATION` (HTTP 422)."

        Design: Corner/validations/budget_line_over_capitalization_target_rejected
        """
        world = fixtures.base_world(api)
        get_success_data(
            api.create_budget_line(
                factories.budget_line_payload(
                    world.production_id, 100_000_000, world.production_version()
                ),
                GM_HEADERS,
            ),
            201,
        )
        version_after_first_line = world.production_version()
        assert version_after_first_line == 2

        validate_error(
            api.create_budget_line(
                factories.reserve_line_payload(
                    world.production_id, 20_000_001, version_after_first_line
                ),
                GM_HEADERS,
            ),
            ApiErrorId.BUDGET_EXCEEDS_CAPITALIZATION,
        )

        # The refusal wrote nothing, so the same version token is still current.
        get_success_data(
            api.create_budget_line(
                factories.reserve_line_payload(
                    world.production_id, 20_000_000, version_after_first_line
                ),
                GM_HEADERS,
            ),
            201,
        )

        production = world.production()
        assert production["budget_total_cents"] == 120_000_000
        assert production["budget_committed_cents"] == 0
        assert production["version"] == 3


class TestDistributionFiscalGates:
    """The three distribution gates fire in their documented order."""

    def test_a_production_with_no_funded_accounts_reports_the_payee_gate(
        self, api: ApiClient
    ):
        """Zero accounts and zero cash report the structural error, not the amount one.

        "A distribution requires that the production have at least one capital
        account whose `units_total` is greater than zero. This is a structural
        check on the existence of a payee set, and it is evaluated **before** any
        cash ceiling: a production with no funded capital accounts reports
        `ERR_NO_INVESTOR_ACCOUNTS` (HTTP 422) and never the amount error."

        Design: Corner/validations/distribution_with_no_investor_accounts_rejected
        """
        world = fixtures.base_world(api)
        validate_error(
            fixtures.declare_distribution(world, 1), ApiErrorId.NO_INVESTOR_ACCOUNTS
        )

        _, meta = validate_paginated(
            api.list_investor_distributions(
                COMPTROLLER_HEADERS, {"production_id": world.production_id}
            )
        )
        assert meta["total_count"] == 0

        production = world.production()
        assert production["distributed_total_cents"] == 0
        assert production["distributable_cash_cents"] == 0
        assert production["version"] == 1

    def test_a_net_profit_declaration_needs_recoupment_however_much_cash_there_is(
        self, api: ApiClient
    ):
        """The same amount that fails as NET_PROFIT succeeds as RECOUPMENT_RETURN.

        "A distribution whose `distribution_type` is `NET_PROFIT` requires the
        production's `recoupment_status` to be `RECOUPED`; otherwise the
        declaration is rejected with `ERR_NOT_YET_RECOUPED` (HTTP 422)."

        Design: Corner/validations/net_profit_distribution_before_recoupment_rejected
        """
        world = fixtures.certified_week_world(api)
        assert world.production()["distributable_cash_cents"] == 28_250_000
        assert world.production()["recoupment_status"] == "UNRECOUPED"

        validate_error(
            fixtures.declare_distribution(
                world, 1_000_000, distribution_type="NET_PROFIT"
            ),
            ApiErrorId.NOT_YET_RECOUPED,
        )

        declared = get_success_data(
            fixtures.declare_distribution(
                world, 1_000_000, distribution_type="RECOUPMENT_RETURN"
            ),
            201,
        )
        assert declared["status"] == "DECLARED"
        assert declared["distribution_type"] == "RECOUPMENT_RETURN"
        assert [entry["amount_cents"] for entry in declared["allocation_breakdown"]] == [
            1_000_000
        ]

        production = world.production()
        assert production["distributed_total_cents"] == 1_000_000
        assert production["distributable_cash_cents"] == 27_250_000
        assert production["recoupment_status"] == "UNRECOUPED"
        assert production["version"] == 9

    def test_the_cash_ceiling_is_the_exact_distributable_figure(self, api: ApiClient):
        """28,250,001 is refused and 28,250,000 drains the ledger to nothing.

        "A declared distribution's `total_amount_cents` may not exceed the
        production's `distributable_cash_cents`; a breach is
        `ERR_DISTRIBUTION_EXCEEDS_DISTRIBUTABLE` (HTTP 422)."

        Design: Corner/validations/distribution_above_distributable_cash_rejected
        """
        world = fixtures.certified_week_world(api)
        assert world.production()["recouped_amount_cents"] == 28_250_000

        validate_error(
            fixtures.declare_distribution(world, 28_250_001),
            ApiErrorId.DISTRIBUTION_EXCEEDS_DISTRIBUTABLE,
        )

        declared = get_success_data(
            fixtures.declare_distribution(world, 28_250_000), 201
        )
        assert declared["total_amount_cents"] == 28_250_000
        assert [entry["amount_cents"] for entry in declared["allocation_breakdown"]] == [
            28_250_000
        ]

        production = world.production()
        assert production["distributed_total_cents"] == 28_250_000
        assert production["distributable_cash_cents"] == 0

        account = fixtures.sole_account(world)
        assert account["declared_distribution_cents"] == 28_250_000
        assert account["distributions_paid_cents"] == 0


class TestInvestorHeadcountCeiling:
    """The ceiling counts distinct accepted investors, not units or money."""

    def test_the_third_distinct_investor_is_refused_under_a_ceiling_of_two(
        self, api: ApiClient
    ):
        """Only 40,000,000 of a 120,000,000 offering is taken, and it still refuses.

        "First the headcount: counting this investor as new if and only if they
        hold no other accepted subscription under the same instrument, the
        instrument's distinct accepted-investor count after the acceptance may not
        exceed its `max_investors`, else `ERR_MAX_INVESTORS_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/max_investors_ceiling_rejects_third_distinct_investor
        """
        world = fixtures.base_world(api)
        fixtures.open_offering(world)
        fixtures.with_effective_document(
            world,
            offering_amount_cents=120_000_000,
            unit_price_cents=20_000_000,
            max_investors=2,
        )

        subscription_ids = []
        for index in range(3):
            investor_id = fixtures.new_accredited_investor(
                world,
                legal_name=f"Investor {index + 1}",
                contact_email=f"investor{index + 1}@example.com",
            )
            subscription_ids.append(
                fixtures.new_subscription(world, investor_id, units=1)
            )
        fixtures.accept_subscription(world, subscription_ids[0])
        fixtures.accept_subscription(world, subscription_ids[1])

        validate_error(
            api.accept_subscription(subscription_ids[2], COUNSEL_HEADERS),
            ApiErrorId.MAX_INVESTORS_EXCEEDED,
        )

        document = get_success_data(
            api.get_offering_document(world.offering_document_id or "", COUNSEL_HEADERS),
            200,
        )
        assert document["accepted_investor_count"] == 2
        assert document["accepted_units_total"] == 2
        assert document["accepted_amount_cents"] == 40_000_000
        assert document["submitted_units_total"] == 1

        assert (
            get_success_data(
                api.get_subscription(subscription_ids[2], COUNSEL_HEADERS), 200
            )["status"]
            == "SUBMITTED"
        )

        _, meta = validate_paginated(
            api.list_investor_accounts(
                COMPTROLLER_HEADERS, {"production_id": world.production_id}
            )
        )
        assert meta["total_count"] == 2

    def test_more_units_from_an_investor_already_accepted_do_not_count_again(
        self, api: ApiClient
    ):
        """Under a ceiling of one, the same investor may add units but nobody else may.

        "First the headcount: counting this investor as new if and only if they
        hold no other accepted subscription under the same instrument, the
        instrument's distinct accepted-investor count after the acceptance may not
        exceed its `max_investors`, else `ERR_MAX_INVESTORS_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/additional_units_from_an_accepted_investor_do_not_raise_the_investor_count
        """
        world = fixtures.base_world(api)
        fixtures.open_offering(world)
        fixtures.with_effective_document(
            world,
            offering_amount_cents=120_000_000,
            unit_price_cents=20_000_000,
            max_investors=1,
        )
        first_investor = fixtures.new_accredited_investor(world)
        second_investor = fixtures.new_accredited_investor(
            world, legal_name="Bertram Cole", contact_email="bertram.cole@example.com"
        )

        fixtures.accept_subscription(
            world, fixtures.new_subscription(world, first_investor, units=1)
        )
        more_units = fixtures.new_subscription(world, first_investor, units=1)
        newcomer = fixtures.new_subscription(world, second_investor, units=1)

        repeat = get_success_data(api.accept_subscription(more_units, COUNSEL_HEADERS), 200)
        assert repeat["status"] == "ACCEPTED"

        validate_error(
            api.accept_subscription(newcomer, COUNSEL_HEADERS),
            ApiErrorId.MAX_INVESTORS_EXCEEDED,
        )

        document = get_success_data(
            api.get_offering_document(world.offering_document_id or "", COUNSEL_HEADERS),
            200,
        )
        assert document["accepted_investor_count"] == 1
        assert document["accepted_units_total"] == 2
        assert document["accepted_amount_cents"] == 40_000_000

        account = fixtures.sole_account(world)
        assert account["units_total"] == 2
        assert account["contributed_cents"] == 40_000_000
        assert account["ownership_pct"] == 1.0

        production = world.production()
        assert production["capital_raised_cents"] == 40_000_000
        assert production["active_investor_count"] == 1


class TestCrossEntityGates:
    """A row's own state is fine; the related row's state is what refuses."""

    def test_a_week_cannot_be_wrapped_before_the_show_starts_performing(
        self, api: ApiClient
    ):
        """The identical body is refused in REHEARSAL and accepted in PREVIEWS.

        "The production's `operating_status` must be one of `PREVIEWS`, `RUNNING`,
        or `CLOSING_NOTICE`; a production still in `PRE_PRODUCTION` or
        `REHEARSAL`, or already `CLOSED`, is rejected with
        `ERR_PRODUCTION_NOT_PERFORMING` (HTTP 409)."

        Design: Corner/validations/wrap_creation_before_previews_rejected
        """
        world = fixtures.capitalized_world(api)
        fixtures.advance_operating_status(world, "REHEARSAL")
        world.set_clock("2026-09-07")

        validate_error(
            api.create_weekly_wrap(
                factories.standard_week_payload(world.production_id), GM_HEADERS
            ),
            ApiErrorId.PRODUCTION_NOT_PERFORMING,
        )

        previewing = fixtures.advance_operating_status(world, "PREVIEWS")
        assert previewing["operating_status"] == "PREVIEWS"
        assert previewing["version"] == 6

        wrap = get_success_data(
            api.create_weekly_wrap(
                factories.standard_week_payload(world.production_id), GM_HEADERS
            ),
            201,
        )
        assert wrap["status"] == "DRAFT"
        assert wrap["royalty_base_cents"] == 28_250_000

    def test_licensing_income_cannot_be_allocated_before_capitalization(
        self, api: ApiClient
    ):
        """Recording is always allowed; moving it into the ledger is not.

        "A `Comptroller` allocates it, which is what moves it into the cash
        ledger. Allocation is admissible only from `RECORDED` — a second attempt
        reports `ERR_INVALID_INCOME_STATE` (HTTP 409) — and only while the
        production's `offering_status` reads `CAPITALIZED`, else
        `ERR_PRODUCTION_NOT_CAPITALIZED` (HTTP 409)."

        Design: Corner/validations/subsidiary_rights_allocation_before_capitalization_rejected
        """
        world = fixtures.base_world(api)
        assert world.production()["offering_status"] == "DRAFT"
        income = fixtures.with_recorded_income(world, gross_income_cents=10_000_000)

        validate_error(
            api.allocate_subsidiary_rights_income(income["id"], COMPTROLLER_HEADERS),
            ApiErrorId.PRODUCTION_NOT_CAPITALIZED,
        )

        after = get_success_data(
            api.get_subsidiary_rights_income(income["id"], COMPTROLLER_HEADERS), 200
        )
        assert after["status"] == "RECORDED"
        assert after["investor_share_cents"] == 0
        assert after["version"] == 1

        rows, meta = validate_paginated(
            api.list_subsidiary_rights_income(
                COMPTROLLER_HEADERS,
                {"production_id": world.production_id, "status": "RECORDED"},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == income["id"]

        production = world.production()
        assert production["recouped_amount_cents"] == 0
        assert production["version"] == 1

    def test_break_even_needs_an_active_operating_budget_to_read(
        self, api: ApiClient
    ):
        """A drafted budget is not enough; activating one turns the read on.

        "It requires exactly one `ACTIVE` operating budget for the production and
        reports `ERR_ACTIVE_OPERATING_BUDGET_MISSING` (HTTP 409) when there is
        none."

        Design: Corner/validations/break_even_without_active_operating_budget_rejected
        """
        world = fixtures.base_world(api)
        validate_error(
            api.get_break_even_analysis(world.production_id, GM_HEADERS),
            ApiErrorId.ACTIVE_OPERATING_BUDGET_MISSING,
        )

        drafted = get_success_data(
            api.create_operating_budget(
                factories.operating_budget_payload(
                    world.production_id,
                    weekly_fixed_running_cost_cents=32_000_000,
                    variable_cost_pct=0.05,
                    performances_per_week=8,
                ),
                GM_HEADERS,
            ),
            201,
        )
        assert drafted["status"] == "DRAFT"
        validate_error(
            api.get_break_even_analysis(world.production_id, GM_HEADERS),
            ApiErrorId.ACTIVE_OPERATING_BUDGET_MISSING,
        )

        get_success_data(
            api.activate_operating_budget(drafted["id"], COMPTROLLER_HEADERS), 200
        )
        analysis = get_success_data(
            api.get_break_even_analysis(world.production_id, GM_HEADERS), 200
        )
        assert analysis["operating_budget_id"] == drafted["id"]
        assert analysis["royalty_min_guarantee_floor_cents"] == 0
        assert analysis["target_adjusted_gross_cents"] == 32_000_001
        # 33,684,211 clears only 32,000,000, so the solver stops one cent higher.
        assert analysis["break_even_gross_cents"] == 33_684_212
        assert analysis["capacity_gross_projection_cents"] == 191_040_000
        assert analysis["break_even_paid_capacity_pct"] == 0.1763
        assert analysis["weeks_to_recoup_at_last_certified_run_rate"] is None


class TestValidationPrecedence:
    """When two rules are broken at once, the earlier one reports."""

    def test_the_role_check_answers_before_the_path_lookup(self, api: ApiClient):
        """A wrong role learns nothing about whether the identifier exists.

        "2. **Authorization.** The declared role appears in the called endpoint's
        authorized list, else `ERR_FORBIDDEN_ROLE` (403)."

        "3. **Path existence.** Every path identifier resolves, left to right,
        else the matching 404 above."

        Design: Corner/validations/forbidden_role_precedes_path_id_not_found
        """
        world = fixtures.base_world(api)

        validate_error(
            api.capitalize(UNKNOWN_UUID, GM_HEADERS), ApiErrorId.FORBIDDEN_ROLE
        )
        validate_error(
            api.capitalize(UNKNOWN_UUID, COMPTROLLER_HEADERS),
            ApiErrorId.PRODUCTION_NOT_FOUND,
        )
        validate_error(
            api.capitalize(world.production_id, GM_HEADERS), ApiErrorId.FORBIDDEN_ROLE
        )

    def test_the_shape_check_answers_before_the_body_foreign_key(
        self, api: ApiClient
    ):
        """A malformed field masks the unresolvable reference in the same body.

        "4. **Request shape.** Required body fields present; enum fields hold a
        declared member; integer fields are integers inside their declared
        constraints; percentage fields carry no more than their declared decimals;
        date fields are well-formed ISO 8601 calendar dates; `end_date` is on or
        after `start_date` and `expiration_date` is on or after `effective_date`;
        `limit` is between 1 and 100 inclusive and `offset` is at least 0. Any
        violation is `ERR_INVALID_REQUEST` (400)."

        Design: Corner/validations/invalid_request_precedes_body_fk_not_found
        """
        fixtures.base_world(api)

        validate_error(
            api.create_weekly_wrap(
                factories.standard_week_payload(
                    UNKNOWN_UUID,
                    week_ending_date="2026-08-01",
                    performances="eight",
                ),
                GM_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST,
        )

        validate_error(
            api.create_weekly_wrap(
                factories.standard_week_payload(
                    UNKNOWN_UUID, week_ending_date="2026-08-01"
                ),
                GM_HEADERS,
            ),
            ApiErrorId.PRODUCTION_NOT_FOUND,
        )

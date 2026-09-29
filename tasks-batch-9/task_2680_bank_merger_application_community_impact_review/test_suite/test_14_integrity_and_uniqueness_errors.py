"""Integrity errors: intake guards, uniqueness scopes, the grace tail and notice completeness."""
from test_helpers import ApiErrorId, TEST_USERS, api_client, make_filer_headers
from test_helpers.factories import (
    line_item_payload,
    merger_application_payload,
    pro_forma_schedule_payload,
    public_comment_payload,
)
from test_helpers.fixtures import (
    accept_application,
    application_under_review,
    auto_comment_period,
    create_acquirer,
    create_application,
    create_branch,
    create_institution,
    create_market,
    create_regulatory_schedule,
    executed_standard_plan,
    file_comment,
    read_application,
    read_branch,
    read_institution,
    read_market,
    read_period,
    read_plan,
    register_conversion_plan,
    reset_clock_to_epoch,
    rosewood_market_world,
    run_competitive_analysis,
    set_clock,
    submit_application,
)
from test_helpers.test_users import make_commenter_headers
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]

THIN_CAPITAL_INSTITUTION = {
    "legal_name": "Coastal Savings Bank",
    "charter_type": "SAVINGS",
    "primary_regulator": "FDIC",
    "cet1_capital_usd": 40_000_000,
    "tier1_capital_usd": 41_000_000,
    "total_capital_usd": 45_000_000,
    "total_loans_usd": 300_000_000,
    "latest_cra_rating": "SATISFACTORY",
}


class TestIntakeGuards:
    """A filing needs two distinct parties, and a schedule needs capital denominators."""

    def test_01_a_self_merger_and_a_schedule_without_denominators_are_refused(self):
        """PRD §2.5: "The acquirer and the target are different institutions — `ERR_SELF_MERGER`."
        PRD §2.5: "Both institutions report the capital denominators a pro forma schedule needs —
        `ERR_CAPITAL_DATA_MISSING`."
        PRD §3.1: "A newly registered institution is `ACTIVE`, with `total_deposits_usd` of 0 and
        `branch_count` of 0; `status` is one of `ACTIVE` or `MERGED_OUT` and only the service sets
        it."

        Design: Corner/errors/intake_rejects_a_self_merger_and_a_schedule_built_on_missing_capital_data
        """
        reset_clock_to_epoch()
        acquirer = create_acquirer()
        thin = create_institution(payload=dict(THIN_CAPITAL_INSTITUTION))
        application = create_application(
            acquirer["id"], thin["id"], consideration_type="ALL_CASH",
            total_consideration_usd=90_000_000,
        )
        filer_headers = make_filer_headers(acquirer["id"])

        self_merger = api_client.create_merger_application(
            merger_application_payload(acquirer["id"], acquirer["id"], consideration_type="ALL_CASH",
                                       total_consideration_usd=1_000_000),
            filer_headers,
        )
        schedule = api_client.create_pro_forma_schedule(
            pro_forma_schedule_payload(
                application["id"], 1, goodwill_created_usd=10_000_000,
                core_deposit_intangible_usd=2_000_000, aoci_markdown_usd=3_000_000,
                deferred_tax_asset_usd=1_000_000, transaction_costs_usd=1_000_000,
                cash_consideration_usd=90_000_000),
            filer_headers,
        )

        validate_error(self_merger, ApiErrorId.ERR_SELF_MERGER.value, 422)
        validate_error(schedule, ApiErrorId.ERR_CAPITAL_DATA_MISSING.value, 422)
        assert read_institution(thin["id"])["risk_weighted_assets_usd"] == 0
        assert read_institution(thin["id"])["average_total_assets_usd"] == 0
        applications, meta = validate_paginated(api_client.list_merger_applications(
            ANALYST, params={"acquirer_id": acquirer["id"]}))
        assert meta["total_count"] == 1, "the self-merger attempt created no second filing"
        assert [record["id"] for record in applications] == [application["id"]]
        schedules, schedule_meta = validate_paginated(api_client.list_pro_forma_schedules(
            ANALYST, params={"application_id": application["id"]}))
        assert schedule_meta["total_count"] == 0
        assert schedules == []
        assert read_application(application["id"], acquirer["id"])["version"] == 1, (
            "the refused schedule write did not bump the parent version"
        )


class TestUniquenessScopes:
    """Three uniqueness constraints, each scoped to its own key."""

    def test_02_market_code_analysis_pair_and_conversion_plan_are_each_unique(self):
        """PRD §3.1: "Each carries a `market_code` — an MSA or rural county identifier between 2 and
        32 characters that must be unique across all deposit markets, a duplicate being refused with
        `ERR_DUPLICATE_MARKET_CODE` — a human-readable `market_name`, and a `market_type` of either
        `MSA` or `RURAL_COUNTY`."
        PRD §3.5: "At most one analysis may exist for a given application and market pair, a second
        attempt being refused with `ERR_DUPLICATE_ANALYSIS`."
        PRD §3.11: "The `Filer` registers at most one conversion plan per application — a second is
        refused with `ERR_DUPLICATE_CONVERSION_PLAN` — naming the `application_id`, the inclusive
        `conversion_start_date`, the inclusive `conversion_end_date` which must be at or after the
        start date, and an `affected_customer_count` strictly greater than 0 giving the number of
        target-bank customers who will receive conversion disclosures."

        Design: Corner/errors/uniqueness_errors_fire_on_market_code_analysis_and_conversion_plan
        """
        world = rosewood_market_world()
        application_id = world["application"]["id"]
        acquirer_id = world["acquirer"]["id"]
        create_regulatory_schedule(application_id, acquirer_id)
        submit_application(application_id, acquirer_id)
        accept_application(application_id)
        analysis = run_competitive_analysis(application_id, world["market"]["id"])
        conversion_plan = register_conversion_plan(
            application_id, acquirer_id, conversion_start_date="2026-12-01T00:00:00Z",
            conversion_end_date="2026-12-05T00:00:00Z", affected_customer_count=40_000)

        duplicate_market = api_client.create_deposit_market(
            {"market_code": "ROSEWOOD-MSA", "market_name": "Rosewood MSA duplicate",
             "market_type": "RURAL_COUNTY"}, ANALYST)
        duplicate_analysis = api_client.create_competitive_analysis(
            {"application_id": application_id, "market_id": world["market"]["id"]}, ANALYST)
        duplicate_conversion = api_client.create_conversion_plan(
            {"application_id": application_id, "conversion_start_date": "2027-01-10T00:00:00Z",
             "conversion_end_date": "2027-01-14T00:00:00Z", "affected_customer_count": 41_000},
            make_filer_headers(acquirer_id))

        validate_error(duplicate_market, ApiErrorId.ERR_DUPLICATE_MARKET_CODE.value, 409)
        validate_error(duplicate_analysis, ApiErrorId.ERR_DUPLICATE_ANALYSIS.value, 409)
        validate_error(duplicate_conversion, ApiErrorId.ERR_DUPLICATE_CONVERSION_PLAN.value, 409)
        markets, market_meta = validate_paginated(api_client.list_deposit_markets(ANALYST))
        assert market_meta["total_count"] == 1
        assert [record["market_code"] for record in markets] == ["ROSEWOOD-MSA"]
        analyses, analysis_meta = validate_paginated(api_client.list_competitive_analyses(
            ANALYST, params={"application_id": application_id}))
        assert analysis_meta["total_count"] == 1
        assert [record["id"] for record in analyses] == [analysis["id"]]
        plans, plan_meta = validate_paginated(api_client.list_conversion_plans(
            ANALYST, params={"application_id": application_id}))
        assert plan_meta["total_count"] == 1
        assert [record["id"] for record in plans] == [conversion_plan["id"]]

    def test_03_the_analysis_uniqueness_scope_is_the_application_and_market_pair(self):
        """PRD §3.5: "At most one analysis may exist for a given application and market pair, a
        second attempt being refused with `ERR_DUPLICATE_ANALYSIS`."
        PRD §3.5: "A `CaseAnalyst` names the `application_id` and the `market_id`, and the request is
        refused with `ERR_NO_MARKET_OVERLAP` unless both the acquirer and the target each hold at
        least one includable branch in that market."

        Design: Corner/errors/uniqueness_errors_fire_on_market_code_analysis_and_conversion_plan
        """
        world = rosewood_market_world()
        application_id = world["application"]["id"]
        first = run_competitive_analysis(application_id, world["market"]["id"])
        second_market = create_market(market_code="FERNWOOD-MSA", market_name="Fernwood MSA",
                                      market_type="MSA")
        create_branch(world["acquirer"]["id"], second_market["id"],
                      branch_name="Northbay Fernwood", deposits_usd=100_000_000)
        create_branch(world["target"]["id"], second_market["id"],
                      branch_name="Harbor Fernwood", deposits_usd=40_000_000)

        second = run_competitive_analysis(application_id, second_market["id"])

        assert second["market_id"] == second_market["id"]
        assert second["id"] != first["id"]
        analyses, meta = validate_paginated(api_client.list_competitive_analyses(
            ANALYST, params={"application_id": application_id}))
        assert meta["total_count"] == 2, (
            "the constraint is per application and market pair, not one analysis per application"
        )
        assert {record["id"] for record in analyses} == {first["id"], second["id"]}


class TestCommentGraceTail:
    """A three-day tail stores late comment as a record, then shuts entirely."""

    def test_04_a_comment_inside_the_grace_tail_is_untimely_and_after_it_is_refused(self):
        """PRD §3.7: "A comment received at or after `closes_at` but strictly before `closes_at` plus
        3 days is created with `status` `UNTIMELY` — it is stored as a matter of record but never
        counts toward any protest aggregate and never founds a hearing petition, and it is born in
        that state rather than transitioning into it."
        PRD §3.7: "A comment received at or after `closes_at` plus 3 days is refused outright with
        `ERR_COMMENT_WINDOW_CLOSED`."
        PRD §3.7: "The period's `comment_count` is the number of comments on it regardless of
        `status`."

        Design: Corner/errors/comment_grace_tail_marks_late_comments_untimely_then_shuts_the_window
        """
        world = application_under_review()
        period = world["period"]
        assert period["closes_at"].startswith("2026-08-31")
        set_clock("2026-09-02T23:59:59Z")

        late = file_comment(
            period["id"], commenter_user_id="commenter-3",
            commenter_name="Late But Inside Grace", commenter_type="INDIVIDUAL", stance="OPPOSE",
            body="Filed inside the three-day grace tail.", substantive=False)
        set_clock("2026-09-03T00:00:00Z")
        too_late = api_client.create_public_comment(
            public_comment_payload(
                period["id"], commenter_name="Too Late Entirely", commenter_type="INDIVIDUAL",
                stance="OPPOSE", body="Filed exactly at the end of the grace tail.",
                substantive=False),
            make_commenter_headers("commenter-4"))

        assert late["status"] == "UNTIMELY"
        assert late["received_at"].startswith("2026-09-02T23:59:59")
        validate_error(too_late, ApiErrorId.ERR_COMMENT_WINDOW_CLOSED.value, 422)
        refetched = read_period(period["id"])
        assert refetched["comment_count"] == 1, "the untimely record counts, the refused one does not"
        assert refetched["substantive_protest_count"] == 0
        assert refetched["status"] == "OPEN", (
            "the tail expiring does not close the window; only the close action does"
        )
        comments, meta = validate_paginated(api_client.list_public_comments(
            ANALYST, params={"period_id": period["id"]}))
        assert meta["total_count"] == 1
        assert [record["id"] for record in comments] == [late["id"]]


class TestClosureNoticeCompleteness:
    """A closure designation needs both notice dates and ninety days of lead time."""

    def test_05_a_closure_designation_needs_both_dates_and_ninety_days_of_lead(self):
        """PRD §3.6: "Both `notice_sent_at`, the date the customer branch-closing notice was mailed,
        and `planned_closure_date`, the date the office stops accepting deposits, must be present;
        omitting either yields `ERR_CLOSURE_NOTICE_REQUIRED`."
        PRD §3.6: "From them the service computes `notice_lead_days` as the number of whole UTC days
        from `notice_sent_at` to `planned_closure_date`, discarding any partial day, and that lead
        time must be at least 90 days; anything shorter yields
        `ERR_CLOSURE_NOTICE_LEAD_INSUFFICIENT`."
        PRD §2.8: "The consequence is deliberate and easy to get wrong: designating a branch for
        divestiture or for closure does **not** remove its deposits from the market's deposit base."

        Design: Corner/errors/closure_designation_needs_both_notice_fields_and_ninety_days_of_lead
        """
        world = rosewood_market_world()
        application_id = world["application"]["id"]
        acquirer_id = world["acquirer"]["id"]
        branch_id = world["branch_target"]["id"]
        create_regulatory_schedule(application_id, acquirer_id)
        submit_application(application_id, acquirer_id)
        accept_application(application_id)
        auto_comment_period(application_id)
        filer_headers = make_filer_headers(acquirer_id)

        short_lead = api_client.designate_branch(
            branch_id,
            {"application_id": application_id, "designation_type": "CLOSURE",
             "notice_sent_at": "2026-08-01T00:00:00Z",
             "planned_closure_date": "2026-10-15T00:00:00Z"},
            filer_headers)
        assert read_branch(branch_id)["status"] == "OPEN"
        missing_notice = api_client.designate_branch(
            branch_id,
            {"application_id": application_id, "designation_type": "CLOSURE",
             "planned_closure_date": "2027-01-01T00:00:00Z"},
            filer_headers)
        assert read_branch(branch_id)["status"] == "OPEN"
        accepted = validate_success(api_client.designate_branch(
            branch_id,
            {"application_id": application_id, "designation_type": "CLOSURE",
             "notice_sent_at": "2026-08-01T00:00:00Z",
             "planned_closure_date": "2026-11-15T00:00:00Z"},
            filer_headers))

        validate_error(short_lead, ApiErrorId.ERR_CLOSURE_NOTICE_LEAD_INSUFFICIENT.value, 422)
        validate_error(missing_notice, ApiErrorId.ERR_CLOSURE_NOTICE_REQUIRED.value, 422)
        assert accepted["status"] == "DESIGNATED_FOR_CLOSURE"
        assert accepted["notice_lead_days"] == 106, (
            "2026-08-01 to 2026-11-15 is 106 whole UTC days"
        )
        assert accepted["designation_application_id"] == application_id
        assert read_market(world["market"]["id"])["total_deposits_usd"] == 1_000_000_000, (
            "a designated office is still includable, so the deposit base does not move"
        )


class TestExecutedPlanIsFrozen:
    """An executed package accepts neither new dollars nor a second execution."""

    def test_06_neither_a_new_line_item_nor_a_second_execution_is_accepted(self):
        """PRD §3.9: "Adding a line item to a plan that has left `PROPOSED` is refused with
        `ERR_INVALID_PLAN_STATE`."
        PRD §3.9: "No further line items may be added afterwards, and the frozen
        `quarterly_target_total_usd` is the denominator of every fulfilment measurement that
        follows."
        PRD §3.9: "Only a `PROPOSED` plan is superseded this way; an `EXECUTED` plan blocks the
        creation of a replacement, and `EXECUTED` and `SUPERSEDED` are both terminal."

        Design: Corner/errors/adding_a_line_item_to_an_executed_plan_is_rejected
        """
        world = application_under_review()
        acquirer_id = world["acquirer"]["id"]
        executed = executed_standard_plan(world["application"]["id"], acquirer_id)
        plan_id = executed["plan"]["id"]
        filer_headers = make_filer_headers(acquirer_id)

        extra_item = api_client.create_line_item(
            line_item_payload(plan_id, "BRANCH_RETENTION", 8_000_000), filer_headers)
        second_execution = api_client.execute_benefits_plan(plan_id, filer_headers)

        validate_error(extra_item, ApiErrorId.ERR_INVALID_PLAN_STATE.value, 409)
        validate_error(second_execution, ApiErrorId.ERR_INVALID_PLAN_STATE.value, 409)
        refetched = read_plan(plan_id)
        assert refetched["status"] == "EXECUTED"
        assert refetched["total_committed_usd"] == 392_000_000
        assert refetched["annual_target_total_usd"] == 130_666_666, (
            "the rejected line item did not re-run the pro rata split"
        )
        line_items, meta = validate_paginated(api_client.list_line_items(
            ANALYST, params={"plan_id": plan_id}))
        assert meta["total_count"] == 4
        assert len(line_items) == 4

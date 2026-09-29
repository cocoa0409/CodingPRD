"""Closed reporting periods against half-open contract terms."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADMIN_REVIEW,
    ADMIN_REVIEW_ID,
    ApiErrorId,
    assert_cents,
    assert_instant,
    make_supplier_headers,
)
from test_helpers.constants import (
    CLOCK_NOV_01,
    CLOCK_OCT_01,
    CLOCK_OCT_02,
    OCT_PERIOD_END,
    OCT_PERIOD_START,
    SEP_PERIOD_END,
    SEP_PERIOD_START,
    SKU_LINER,
)
from test_helpers.factories import LINER_LINE, renewal_amendment_payload, usage_report_payload
from test_helpers.fixtures import (
    accept_report,
    open_report,
    read_amendment,
    read_analysis,
    read_contract,
    read_report,
    read_usage,
    record_confirmed_usage,
    set_clock,
    setup_active_contract,
    setup_authorised_member,
    submit_report,
)


def _period_world(api):
    """One September order under an accepted September report, one October order loose."""
    world = setup_active_contract(api, lines=(LINER_LINE,))
    member, analysis = setup_authorised_member(api, world)
    world["member"] = member
    world["analysis"] = analysis
    line_id = world["lines"][SKU_LINER]["id"]
    contract_id = world["contract"]["id"]
    world["september_usage"] = record_confirmed_usage(
        api, contract_id, member["id"], line_id, analysis["id"], quantity=1
    )
    world["september"] = open_report(
        api, world, period_start=SEP_PERIOD_START, period_end=SEP_PERIOD_END
    )
    set_clock(api, CLOCK_OCT_01)
    submit_report(api, world, world["september"]["id"])
    accept_report(api, world["september"]["id"])
    set_clock(api, CLOCK_OCT_02)
    world["october_usage"] = record_confirmed_usage(
        api, contract_id, member["id"], line_id, analysis["id"], quantity=1
    )
    return world


def _open_period(api, world, period_start, period_end):
    return api.create_usage_report(
        usage_report_payload(
            world["contract"]["id"], period_start=period_start, period_end=period_end
        ),
        make_supplier_headers(world["contract"]["supplier_id"]),
    )


def _october_report(api, world):
    report = open_report(api, world, period_start=OCT_PERIOD_START, period_end=OCT_PERIOD_END)
    set_clock(api, CLOCK_NOV_01)
    return submit_report(api, world, report["id"])


def _renewal_world(api):
    """An ACTIVE contract on its base term with one determined authority opinion."""
    world = setup_active_contract(api)
    member, analysis = setup_authorised_member(api, world)
    world["member"] = member
    world["analysis"] = analysis
    world["contract"] = read_contract(api, world["contract"]["id"])
    return world


def _propose_renewal(api, world, requested_term_end):
    return api.create_contract_amendment(
        renewal_amendment_payload(
            world["contract"]["id"], world["contract"]["version"], requested_term_end
        ),
        make_supplier_headers(world["contract"]["supplier_id"]),
    )


class TestClosedReportingPeriods:
    def test_01_a_period_touching_the_existing_end_instant_overlaps(self, api):
        """PRD §2.11: "Two periods that merely touch at a single instant therefore *do*
        overlap: a candidate period overlaps an existing one whenever the candidate's start
        is at or before the existing period's end and the existing period's start is at or
        before the candidate's end."

        Design: Difficulty/resource_temporal_overlap/report_periods_are_closed_intervals_so_a_touching_endpoint_is_an_overlap
        """
        world = _period_world(api)

        response = _open_period(api, world, SEP_PERIOD_END, OCT_PERIOD_END)

        validate_error(response, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP, 409)

    def test_02_a_period_touching_the_existing_start_instant_overlaps_too(self, api):
        """PRD §3.7: "The period must not overlap any other report on the same contract
        whose `status` is `DRAFT`, `SUBMITTED`, `ACCEPTED` or `RECONCILED`: overlap means the
        candidate's `period_start` is at or before the other's `period_end` and the other's
        `period_start` is at or before the candidate's `period_end`, so two periods that
        merely touch at a single instant *do* overlap and the later one is refused with
        `ERR_REPORT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/report_periods_are_closed_intervals_so_a_touching_endpoint_is_an_overlap
        """
        world = _period_world(api)

        response = _open_period(api, world, "2026-08-01T00:00:00Z", SEP_PERIOD_START)

        validate_error(response, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP, 409)

    def test_03_the_period_starting_one_second_later_is_disjoint_and_admitted(self, api):
        """PRD §3.7: "A new report starts in `status` `DRAFT` with `fee_status` `NOT_DUE`,
        every figure at 0, and `audited_fee_cents`, `fee_true_up_cents`, `variance_pct`,
        `accepted_at` and `fee_due_at` null."

        Design: Difficulty/resource_temporal_overlap/report_periods_are_closed_intervals_so_a_touching_endpoint_is_an_overlap
        """
        world = _period_world(api)

        report = validate_success(
            _open_period(api, world, OCT_PERIOD_START, OCT_PERIOD_END), 201
        )

        assert report["status"] == "DRAFT"
        assert report["fee_status"] == "NOT_DUE"
        assert_instant(report["period_start"], OCT_PERIOD_START, "period_start")
        assert_instant(report["period_end"], OCT_PERIOD_END, "period_end")
        assert report["swept_usage_count"] == 0
        assert report["accepted_at"] is None

    def test_04_the_accepted_period_sweeps_only_the_orders_inside_its_own_window(self, api):
        """PRD §3.7: "`swept_usage_count` is the count of the set,
        `reported_chargeable_cents` is the exact unrounded sum of the set's
        `chargeable_base_cents` values, and `reported_usage_cents` is the exact unrounded sum
        of the set's `total_cents` values — the figure printed on the member usage
        statement."

        Design: Difficulty/resource_temporal_overlap/report_periods_are_closed_intervals_so_a_touching_endpoint_is_an_overlap
        """
        world = _period_world(api)

        october = _october_report(api, world)

        assert october["status"] == "SUBMITTED"
        assert october["swept_usage_count"] == 1
        assert_cents(october["reported_chargeable_cents"], 9015, "reported_chargeable_cents")
        assert_cents(october["reported_usage_cents"], 9195, "reported_usage_cents")

    def test_05_the_bulk_fee_is_applied_to_the_one_order_the_period_holds(self, api):
        """PRD §3.7: "Submission also computes the *reported* variant of the administrative
        fee: `reported_fee_cents` is `reported_chargeable_cents` multiplied by the contract's
        `admin_fee_rate_bps` and divided by 10,000, rounded half up to a whole cent."

        Design: Difficulty/resource_temporal_overlap/report_periods_are_closed_intervals_so_a_touching_endpoint_is_an_overlap
        """
        world = _period_world(api)

        october = _october_report(api, world)

        assert_cents(october["reported_fee_cents"], 180, "reported_fee_cents")

    def test_06_each_order_stays_bound_to_the_period_that_contains_it(self, api):
        """PRD §3.7: "Every swept order has its `usage_report_id` stamped with this report's
        id."

        Design: Difficulty/resource_temporal_overlap/report_periods_are_closed_intervals_so_a_touching_endpoint_is_an_overlap
        """
        world = _period_world(api)

        october = _october_report(api, world)

        assert read_usage(api, world["october_usage"]["id"])["usage_report_id"] == october["id"]
        assert (
            read_usage(api, world["september_usage"]["id"])["usage_report_id"]
            == world["september"]["id"]
        )
        september = read_report(api, world["september"]["id"])
        assert september["swept_usage_count"] == 1
        assert september["status"] == "ACCEPTED"


class TestHalfOpenRenewalTerms:
    def test_07_a_requested_end_equal_to_the_exclusive_end_extends_nothing(self, api):
        """PRD §3.8: "For a `RENEWAL`, the requested end must genuinely extend the term:
        because a term is half-open, a `requested_term_end` equal to or earlier than the
        contract's `current_term_end` extends nothing and is
        `ERR_RENEWAL_TERM_NOT_EXTENDING`."

        Design: Difficulty/resource_temporal_overlap/renewal_terms_are_half_open_so_adjacency_is_legal_but_a_thirteenth_month_is_not
        """
        world = _renewal_world(api)
        assert_instant(world["contract"]["current_term_end"], "2027-09-01T00:00:00Z", "term end")

        response = _propose_renewal(api, world, "2027-09-01T00:00:00Z")

        validate_error(response, ApiErrorId.ERR_RENEWAL_TERM_NOT_EXTENDING, 422)

    def test_08_thirteen_months_out_is_one_month_too_far(self, api):
        """PRD §3.8: "The extension in whole months is computed by calendar arithmetic
        between `current_term_end` and `requested_term_end` — the year difference multiplied
        by twelve, plus the month difference, minus one further month when the requested
        end's day-of-month is earlier than the current end's day-of-month — and it must not
        exceed twelve months, a longer extension being `ERR_RENEWAL_TERM_TOO_LONG`."

        Design: Difficulty/resource_temporal_overlap/renewal_terms_are_half_open_so_adjacency_is_legal_but_a_thirteenth_month_is_not
        """
        world = _renewal_world(api)

        response = _propose_renewal(api, world, "2028-10-01T00:00:00Z")

        validate_error(response, ApiErrorId.ERR_RENEWAL_TERM_TOO_LONG, 422)

    def test_09_exactly_twelve_months_out_is_adjacent_and_admitted(self, api):
        """PRD §3.8: "The day-of-month correction is what makes a term running from the first
        of September 2026 to the first of September 2027 exactly twelve months."

        Design: Difficulty/resource_temporal_overlap/renewal_terms_are_half_open_so_adjacency_is_legal_but_a_thirteenth_month_is_not
        """
        world = _renewal_world(api)
        validate_error(
            _propose_renewal(api, world, "2028-10-01T00:00:00Z"),
            ApiErrorId.ERR_RENEWAL_TERM_TOO_LONG,
            422,
        )

        amendment = validate_success(_propose_renewal(api, world, "2028-09-01T00:00:00Z"), 201)

        assert amendment["status"] == "PROPOSED"
        assert amendment["amendment_type"] == "RENEWAL"
        assert_instant(
            amendment["requested_term_end"], "2028-09-01T00:00:00Z", "requested_term_end"
        )
        assert amendment["effective_from"] is None

    def test_10_approval_moves_the_exclusive_end_and_spends_one_renewal(self, api):
        """PRD §3.8: "The `RENEWAL` branch sets the contract's `current_term_end` to
        `requested_term_end` and increments `renewals_used` by 1; already-determined
        authority opinions keep their frozen `expires_on` and are not extended."

        Design: Difficulty/resource_temporal_overlap/renewal_terms_are_half_open_so_adjacency_is_legal_but_a_thirteenth_month_is_not
        """
        world = _renewal_world(api)
        amendment = validate_success(_propose_renewal(api, world, "2028-09-01T00:00:00Z"), 201)

        decided = validate_success(
            api.amendment_decision(
                amendment["id"],
                {
                    "action": "APPROVE",
                    "decision_note": "twelve month renewal within the total term cap",
                },
                ADMIN_REVIEW,
            )
        )

        assert decided["status"] == "APPROVED"
        assert decided["decided_by_user_id"] == ADMIN_REVIEW_ID
        assert_instant(decided["effective_from"], "2026-09-01T00:00:00Z", "effective_from")
        contract = read_contract(api, world["contract"]["id"])
        assert_instant(contract["current_term_end"], "2028-09-01T00:00:00Z", "current_term_end")
        assert_instant(contract["base_term_end"], "2027-09-01T00:00:00Z", "base_term_end")
        assert contract["renewals_used"] == 1
        assert contract["status"] == "ACTIVE"

    def test_11_the_determined_opinion_keeps_the_expiry_it_froze(self, api):
        """PRD §3.5: "`determined_at` is stamped with the current logical instant, and
        `expires_on` is frozen as the *earlier* of the contract's `current_term_end` and 365
        days after `determined_at`."

        Design: Difficulty/resource_temporal_overlap/renewal_terms_are_half_open_so_adjacency_is_legal_but_a_thirteenth_month_is_not
        """
        world = _renewal_world(api)
        amendment = validate_success(_propose_renewal(api, world, "2028-09-01T00:00:00Z"), 201)
        validate_success(
            api.amendment_decision(amendment["id"], {"action": "APPROVE"}, ADMIN_REVIEW)
        )

        analysis = read_analysis(api, world["analysis"]["id"])

        assert_instant(analysis["expires_on"], "2027-09-01T00:00:00Z", "expires_on")
        assert analysis["status"] == "DETERMINED"
        assert read_amendment(api, amendment["id"])["status"] == "APPROVED"

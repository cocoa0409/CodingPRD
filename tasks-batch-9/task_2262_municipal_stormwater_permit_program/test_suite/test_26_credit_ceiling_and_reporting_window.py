"""Two aggregate rules: half a fee is the most that can be credited, and a
reporting window has to sit inside a term the clock has not yet ended."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_fee_chain
from test_helpers.test_users import CLERK_HEADERS, MANAGER_HEADERS


def _review(application_id, decision="APPROVE", **overrides):
    """Send a review decision as the clerk without unwrapping the response."""
    return api_client.review_fee_credit_application(
        application_id, factories.credit_review_payload(decision, **overrides), CLERK_HEADERS
    )


class TestTheCreditCeilingIsAnAggregateOverApprovedRows:
    """One account, three applications, and a ceiling reached exactly once."""

    @pytest.fixture
    def credited_account(self, active_program):
        """A COMMERCIAL parcel of 9020 sqft with 0.3000 approved and 0.2500 pending."""
        account = fx.create_account(
            active_program["term_id"],
            parcel_id="P-1000",
            parcel_class="COMMERCIAL",
            impervious_area_sqft=9020.0,
            owner_name="Ada Owner",
        )
        first = fx.file_credit_application(
            account,
            requested_credit_pct=0.3000,
        )
        fx.review_credit_application(first["id"], "APPROVE")
        refreshed = fx.read_account(account["id"])
        second = fx.file_credit_application(
            refreshed,
            requested_credit_pct=0.2500,
        )
        return {"account": account, "first": first, "second": second}

    def test_01_only_approved_rows_are_in_the_running_total(self, credited_account):
        """The pending 0.2500 has not moved the account's own credit total.

        PRD: "Filing increments the account's `version` by one, and the requested
        percentage enters the `INTERIM` forward-looking pool at once without changing
        `total_credit_pct`." And: "In the `FINAL` reckoning — the one behind the account's
        own stored `total_credit_pct` and `current_net_fee_cents` — an application
        contributes its `approved_credit_pct` when its `status` is `APPROVED`, and nothing
        otherwise. `SUBMITTED`, `RETURNED`, `DENIED` and `REVOKED` rows contribute
        nothing."

        Design: Corner/validations/the_credit_ceiling_is_an_inclusive_aggregate_over_approved_rows_only
        """
        account = fx.read_account(credited_account["account"]["id"])

        assert account["total_credit_pct"] == pytest.approx(0.3000, abs=0.00005), (
            "only the approved 0.3000 counts, got "
            f"{account['total_credit_pct']}"
        )
        assert account["current_net_fee_cents"] == 20485, (
            "29264 less a credit of 8779 is 20485, got "
            f"{account['current_net_fee_cents']}"
        )

    def test_02_the_sum_of_approved_credit_may_not_pass_a_half(self, credited_account):
        """0.3000 already granted leaves no room for a further 0.2500.

        PRD: "`APPROVE` requires that the substantiating facility, when one is named, has
        `credit_eligible` true — a `MUNICIPAL` facility, one with no recorded agreement,
        or one overdue for maintenance inspection is refused with
        `ERR_FACILITY_NOT_CREDIT_ELIGIBLE` — and that the account's existing approved
        credit total plus this `approved_credit_pct` does not exceed 0.5000, otherwise
        `ERR_CREDIT_CEILING_EXCEEDED`."

        Design: Corner/validations/the_credit_ceiling_is_an_inclusive_aggregate_over_approved_rows_only
        """
        response = _review(credited_account["second"]["id"], "APPROVE")

        validate_error(response, ApiErrorId.ERR_CREDIT_CEILING_EXCEEDED.value, 422)

        application = fx.read_application(credited_account["second"]["id"])
        assert application["status"] == "SUBMITTED", (
            f"the refused review left it pending, got {application['status']}"
        )
        assert application["approved_credit_pct"] is None, (
            "and nothing was ever granted on it"
        )

        account = fx.read_account(credited_account["account"]["id"])
        assert account["total_credit_pct"] == pytest.approx(0.3000, abs=0.00005), (
            "the account's credit total is untouched by the refusal"
        )

    def test_03_the_reviewer_may_trim_the_request_down_to_the_ceiling(
        self, credited_account
    ):
        """An override of 0.2000 lands on exactly 0.5000, which is allowed.

        PRD: "The clerk supplies a `decision` of `APPROVE`, `RETURN` or `DENY`, may supply
        `approved_credit_pct` (which defaults to the application's `requested_credit_pct`
        when omitted), and may supply a `return_reason`." And: "and that the account's
        existing approved credit total plus this `approved_credit_pct` does not exceed
        0.5000, otherwise `ERR_CREDIT_CEILING_EXCEEDED`." And: "The credit in cents is
        `gross_billable_cents` multiplied by that capped percentage, rounded to whole
        cents, and the net fee is `gross_billable_cents` minus that credit."

        Design: Corner/validations/the_credit_ceiling_is_an_inclusive_aggregate_over_approved_rows_only
        """
        approved = validate_success(
            _review(credited_account["second"]["id"], "APPROVE", approved_credit_pct=0.2000)
        )

        assert approved["status"] == "APPROVED", "the trimmed request is granted"
        assert approved["approved_credit_pct"] == pytest.approx(0.2000, abs=0.00005), (
            "the reviewer's figure is stored, not the requested 0.2500, got "
            f"{approved['approved_credit_pct']}"
        )

        account = fx.read_account(credited_account["account"]["id"])
        assert_fee_chain(
            account,
            eru_units=3.01,
            gross_fee_cents=26129,
            class_surcharge_cents=3135,
            gross_billable_cents=29264,
            total_credit_pct=0.5000,
            current_net_fee_cents=14632,
        )

    def test_04_a_revoked_credit_gives_its_room_back(self, credited_account):
        """Once the first grant is revoked the ceiling has room again.

        PRD: "It removes the `approved_credit_pct` from the account's `total_credit_pct`,
        restores `current_net_fee_cents`, raises the term's
        `projected_annual_revenue_cents` and may restore `funding_adequacy_status` to
        `ADEQUATE`." And: "`SUBMITTED`, `RETURNED`, `DENIED` and `REVOKED` rows contribute
        nothing." And: "and that the account's existing approved credit total plus this
        `approved_credit_pct` does not exceed 0.5000, otherwise
        `ERR_CREDIT_CEILING_EXCEEDED`."

        Design: Corner/validations/the_credit_ceiling_is_an_inclusive_aggregate_over_approved_rows_only
        """
        account_id = credited_account["account"]["id"]
        validate_success(
            _review(credited_account["second"]["id"], "APPROVE", approved_credit_pct=0.2000)
        )

        validate_success(
            api_client.revoke_fee_credit_application(
                credited_account["first"]["id"],
                factories.credit_revoke_payload(reason="Rain garden removed"),
                CLERK_HEADERS,
            )
        )

        after_revocation = fx.read_account(account_id)
        assert after_revocation["total_credit_pct"] == pytest.approx(
            0.2000, abs=0.00005
        ), (
            "the revoked 0.3000 is out of the total, got "
            f"{after_revocation['total_credit_pct']}"
        )

        third = fx.file_credit_application(
            after_revocation,
            requested_credit_pct=0.3000,
        )
        granted = validate_success(_review(third["id"], "APPROVE"))
        assert granted["status"] == "APPROVED", (
            "0.2000 plus 0.3000 is exactly the ceiling and is allowed"
        )

        account = fx.read_account(account_id)
        assert account["total_credit_pct"] == pytest.approx(0.5000, abs=0.00005), (
            f"the total is back at the ceiling, got {account['total_credit_pct']}"
        )
        assert account["current_net_fee_cents"] == 14632, (
            f"half of 29264 is 14632, got {account['current_net_fee_cents']}"
        )


class TestTheReportingWindowMustSitInsideAnUnendedTerm:
    """Both edges of containment, an inverted window, and the term's own clock."""

    def _open_report(self, term_id, start, end):
        return api_client.create_annual_report(
            factories.annual_report_payload(term_id, start, end), MANAGER_HEADERS
        )

    def test_05_the_term_cannot_expire_before_its_end_date_arrives(
        self, active_program
    ):
        """The clock reads 2026-08-01 and the term runs to 2026-12-31.

        PRD: "The reverse transition, `ACTIVE → EXPIRED`, is available to the same manager
        once the logical clock has reached or passed `term_end_date`; before that instant
        it is refused with `ERR_TERM_END_NOT_REACHED`."

        Design: Corner/validations/a_reporting_window_must_lie_inside_the_term_and_the_term_must_have_ended
        """
        response = api_client.expire_permit_term(
            active_program["term_id"], MANAGER_HEADERS
        )

        validate_error(response, ApiErrorId.ERR_TERM_END_NOT_REACHED.value, 409)

        term = fx.read_term(active_program["term_id"])
        assert term["status"] == "ACTIVE", "the term is still running"
        assert term["expired_at"] is None, "and was never stamped as expired"

    def test_06_a_window_starting_a_day_early_escapes_the_term(self, active_program):
        """2025-12-31 lies outside a term that begins on 2026-01-01.

        PRD: "The window must lie wholly inside the term's `term_start_date` and
        `term_end_date`; a window that escapes the term is refused with
        `ERR_REPORT_WINDOW_OUTSIDE_TERM`."

        Design: Corner/validations/a_reporting_window_must_lie_inside_the_term_and_the_term_must_have_ended
        """
        response = self._open_report(
            active_program["term_id"], "2025-12-31", "2026-12-31"
        )

        validate_error(response, ApiErrorId.ERR_REPORT_WINDOW_OUTSIDE_TERM.value, 422)

    def test_07_a_window_ending_a_day_late_escapes_it_too(self, active_program):
        """2027-01-01 lies outside a term that ends on 2026-12-31.

        PRD: "The window must lie wholly inside the term's `term_start_date` and
        `term_end_date`; a window that escapes the term is refused with
        `ERR_REPORT_WINDOW_OUTSIDE_TERM`."

        Design: Corner/validations/a_reporting_window_must_lie_inside_the_term_and_the_term_must_have_ended
        """
        response = self._open_report(
            active_program["term_id"], "2026-01-01", "2027-01-01"
        )

        validate_error(response, ApiErrorId.ERR_REPORT_WINDOW_OUTSIDE_TERM.value, 422)

    def test_08_an_inverted_window_never_reaches_the_containment_test(
        self, active_program
    ):
        """Both dates are inside the term, and the order of them is not.

        PRD: "A `StormwaterProgramManager` opens one against a `permit_term_id` with the
        `reporting_period_start` and `reporting_period_end` of the period it covers, both
        ISO 8601 dates, the end on or after the start." And: "**Request shape.** Missing
        required body fields, wrong types, unknown enum members, out-of-range numbers,
        malformed ISO 8601 values and out-of-range pagination all yield `ERR_VALIDATION`
        (400)."

        Design: Corner/validations/a_reporting_window_must_lie_inside_the_term_and_the_term_must_have_ended
        """
        response = self._open_report(
            active_program["term_id"], "2026-07-01", "2026-06-30"
        )

        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    def test_09_a_window_equal_to_the_term_is_inside_it(self, active_program):
        """Containment is inclusive on both edges, so the whole term is a window.

        PRD: "The window must lie wholly inside the term's `term_start_date` and
        `term_end_date`; a window that escapes the term is refused with
        `ERR_REPORT_WINDOW_OUTSIDE_TERM`." And: "A new report has `status` `DRAFT`, every
        statistic at its zero value, `invalidation_count` at 0, and `compiled_at`,
        `compiled_by_user_id`, `certified_at`, `certified_by_user_id`,
        `certification_statement`, `submitted_at` and `invalidated_reason` all null."

        Design: Corner/validations/a_reporting_window_must_lie_inside_the_term_and_the_term_must_have_ended
        """
        report = validate_success(
            self._open_report(active_program["term_id"], "2026-01-01", "2026-12-31"), 201
        )

        assert report["status"] == "DRAFT", f"a fresh report is DRAFT, got {report['status']}"
        assert report["reporting_period_start"] == "2026-01-01", "the start is kept"
        assert report["reporting_period_end"] == "2026-12-31", "the end is kept"
        assert report["compliance_index"] == pytest.approx(0.00, abs=0.01), (
            f"nothing has been compiled yet, got {report['compliance_index']}"
        )
        assert report["invalidation_count"] == 0, "and it has never been invalidated"
        assert report["compiled_at"] is None, "with no compilation stamp"

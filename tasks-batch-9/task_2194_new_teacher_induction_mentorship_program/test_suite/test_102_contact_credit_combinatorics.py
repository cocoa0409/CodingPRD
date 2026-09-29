"""Formulas whose result no single input predicts: the three-way credited-minute
interaction and the pinned per-log rounding order of the stipend gross.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.api_errors import ERR_DAILY_CREDIT_CAP_REACHED
from test_helpers.assertions import assert_money_cents, assert_two_decimals
from test_helpers.fixtures import (
    build_program,
    read_match,
    read_mentor,
    read_novice,
    set_clock,
    submit_contact_log,
    verify_contact_log,
)
from test_helpers.test_users import ADMIN, PREPARER, make_site_lead_headers


class TestContactCreditThreeWayInteraction:
    """Minutes, contact-type weight and the residual same-day room interact."""

    @staticmethod
    def _three_logs_on_one_day(api: InductionApiClient) -> dict:
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-07T12:00:00Z")
        first = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-06T09:00:00Z",
            minutes=120,
            contact_type="ONE_ON_ONE",
            mentor_id=program["mentor_id"],
            description="Weekly one-on-one planning conference with the novice on unit pacing",
        )
        second = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-06T11:00:00Z",
            minutes=120,
            contact_type="MODEL_LESSON",
            mentor_id=program["mentor_id"],
            description="Model lesson delivered in the novice classroom for the whole period",
        )
        third = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-06T14:00:00Z",
            minutes=40,
            contact_type="DEBRIEF",
            mentor_id=program["mentor_id"],
            description="Short debrief after the model lesson block on questioning",
        )
        verify_contact_log(api, first["id"], lead)
        program["lead"] = lead
        program["log_ids"] = [first["id"], second["id"], third["id"]]
        return program

    def test_second_log_of_the_day_is_clipped_to_the_residual_room(
        self, api: InductionApiClient
    ):
        """A 120-minute model lesson weighs 150 minutes but credits only the 60 left.

        The PRD applies the ceiling after the weighting: "The remaining room for
        the day is three hours minus that already-credited sum, floored at zero.
        The log's `credited_minutes` is the smaller of the truncated weighted
        minutes and that remaining room."

        Design: Difficulty/combinatorial_formula/contact_credit_three_way_interaction
        """
        program = self._three_logs_on_one_day(api)
        _, second_id, _ = program["log_ids"]

        second = validate_success(
            api.review_contact_log(second_id, f.review_payload("VERIFY"), program["lead"])
        )

        assert second["verification_status"] == "VERIFIED"
        assert second["credited_minutes"] == 60, (
            "floor(120 * 1.25) = 150 weighted minutes must be clipped to the 60 "
            f"minutes left after the first log's 120, got {second['credited_minutes']}"
        )
        assert_money_cents(second["stipend_cents"], 4200, "stipend_cents")
        assert second["rate_tier_at_verification"] == "EXACT", (
            "the tier is pinned from the parent match's subject_match_tier"
        )
        assert_two_decimals(
            second["cert_multiplier_at_verification"], 1.00, "cert_multiplier_at_verification"
        )

        match = read_match(api, program["match_id"])
        assert match["verified_minutes_total"] == 180, (
            f"120 plus the clipped 60 is 180, got {match['verified_minutes_total']}"
        )
        assert_money_cents(match["accrued_stipend_cents"], 12600, "accrued_stipend_cents")
        assert read_novice(api, program["novice_id"])["verified_contact_minutes"] == 180

    def test_third_log_is_refused_once_the_day_is_exhausted(self, api: InductionApiClient):
        """With 180 minutes already credited, the next verification is refused outright.

        The PRD distinguishes an exhausted day from a zero credit: "If the
        already-credited total for that match and date has reached the full three
        hours, so that no room at all remains, the verification is refused
        outright with `ERR_DAILY_CREDIT_CAP_REACHED` rather than producing a
        zero-minute credit."

        Design: Difficulty/combinatorial_formula/contact_credit_three_way_interaction
        """
        program = self._three_logs_on_one_day(api)
        _, second_id, third_id = program["log_ids"]
        validate_success(
            api.review_contact_log(second_id, f.review_payload("VERIFY"), program["lead"])
        )

        response = api.review_contact_log(
            third_id, f.review_payload("VERIFY"), program["lead"]
        )
        validate_error(response, ERR_DAILY_CREDIT_CAP_REACHED, 422)

        third = validate_success(api.get_contact_log(third_id, ADMIN))
        assert third["verification_status"] == "SUBMITTED", (
            "a refused verification leaves the log where it was, got "
            f"{third['verification_status']}"
        )
        assert third["credited_minutes"] == 0, (
            "a refused verification credits nothing at all, got "
            f"{third['credited_minutes']}"
        )
        assert read_match(api, program["match_id"])["verified_minutes_total"] == 180


class TestStipendPerLogRoundingOrder:
    """Rounding per log and then summing is not the same as summing then rounding."""

    @staticmethod
    def _three_cross_tier_logs(api: InductionApiClient) -> dict:
        program = build_program(
            api,
            mentor_overrides={"subject_endorsements": ["SPED"]},
            novice_overrides={"subject_area": "SCIENCE"},
        )
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-04T12:00:00Z")
        program["log_ids"] = []
        for index in (1, 2, 3):
            log = submit_contact_log(
                api,
                program["match_id"],
                "2026-08-03T09:00:00Z",
                minutes=7,
                contact_type="ONE_ON_ONE",
                mentor_id=program["mentor_id"],
                description=f"Brief corridor check-in number {index} on classroom routines",
            )
            verify_contact_log(api, log["id"], lead)
            program["log_ids"].append(log["id"])
        set_clock(api, "2026-10-05T00:00:00Z")
        return program

    def test_gross_sums_already_rounded_per_log_amounts(self, api: InductionApiClient):
        """Three 7-minute CROSS logs round to 327 cents each and gross 981, not 980.

        The PRD pins the order: "The per-log amount is the log's credited minutes
        divided by 60, multiplied by that hourly rate, multiplied by that
        multiplier, and **rounded half up to whole cents at that point**."

        Design: Difficulty/combinatorial_formula/stipend_per_log_rounding_order
        """
        program = self._three_cross_tier_logs(api)
        for log_id in program["log_ids"]:
            log = validate_success(api.get_contact_log(log_id, ADMIN))
            assert log["credited_minutes"] == 7, (
                f"floor(7 * 1.00) is 7 credited minutes, got {log['credited_minutes']}"
            )
            assert_money_cents(log["stipend_cents"], 327, "stipend_cents")

        mentor_version = read_mentor(api, program["mentor_id"])["version"]
        disbursement = validate_success(
            api.create_disbursement(
                f.disbursement_payload(
                    program["mentor_id"],
                    mentor_version,
                    period_code="2026-Q3",
                    period_start="2026-07-01T00:00:00Z",
                    period_end="2026-09-30T23:59:59Z",
                ),
                PREPARER,
            ),
            201,
        )

        assert disbursement["eligible_log_count"] == 3, (
            f"all three VERIFIED logs fall in the period, got "
            f"{disbursement['eligible_log_count']}"
        )
        assert_money_cents(disbursement["gross_cents"], 981, "gross_cents")
        assert disbursement["gross_cents"] != 980, (
            "summing the unrounded per-log products and rounding once at the end "
            "would give 980, which is explicitly not the rule"
        )
        assert_money_cents(disbursement["net_cents"], 981, "net_cents")

    def test_cross_tier_pins_the_lowest_hourly_rate(self, api: InductionApiClient):
        """A SPED-endorsed mentor paired with a SCIENCE novice is CROSS at 2800 cents.

        The PRD fixes both the tier ladder and the rate table: "Failing both, the
        tier is `CROSS`." Activation "pins
        `pinned_stipend_rate_cents_per_hour` from the tier — 4200 cents per hour
        for `EXACT`, 3600 for `ADJACENT`, 2800 for `CROSS`".

        Design: Difficulty/combinatorial_formula/stipend_per_log_rounding_order
        """
        program = self._three_cross_tier_logs(api)
        match = read_match(api, program["match_id"])

        assert match["subject_match_tier"] == "CROSS", (
            "SPED is neither SCIENCE itself nor in SCIENCE's adjacency set of "
            f"MATH and CTE, got {match['subject_match_tier']}"
        )
        assert match["pinned_stipend_rate_cents_per_hour"] == 2800, (
            "a CROSS match pins 2800 cents per hour, got "
            f"{match['pinned_stipend_rate_cents_per_hour']}"
        )
        for log_id in program["log_ids"]:
            log = validate_success(api.get_contact_log(log_id, ADMIN))
            assert log["rate_tier_at_verification"] == "CROSS", (
                "the log pins the tier it was verified under"
            )

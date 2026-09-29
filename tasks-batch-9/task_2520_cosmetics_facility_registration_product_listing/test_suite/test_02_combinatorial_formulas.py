"""Multi-term formulas whose factors interact: the adverse-event points engine
across three events on two listings, and the readiness score whose five
weighted terms are each rounded before they are added.
"""

from test_helpers import assertions as A
from test_helpers import constants as K
from test_helpers import factories as F
from test_helpers import fixtures as X

CONSUMER_EVENT_RECEIVED_AT = "2026-08-05T10:00:00Z"
TIMELY_EVENT_RECEIVED_AT = "2026-08-30T09:00:00Z"
FILING_INSTANT = "2026-09-01T12:00:00Z"


def _facility_with_two_listings(api):
    """One establishment, one designee, a consumer listing and a trade-only one."""
    bundle = X.registered_facility_with_listing(api)
    professional = X.create_draft_listing(
        api, bundle["facility_id"], bundle["person_id"],
        product_name="Atelier Trade Eyeliner Fixative",
        category_code="03B",
        professional_use_only=True,
        professional_use_statement_present=True,
        label_contact_type=K.LABEL_CONTACT_DOMESTIC_PHONE,
        label_contact_value="+1-617-555-0142",
    )
    assert professional["professional_use_only"] is True
    return bundle, professional


def _three_events_filed_at_one_instant(api):
    """Two events twelve days late and one filed comfortably inside its window."""
    bundle, professional = _facility_with_two_listings(api)
    agent = bundle["agent"]

    X.set_clock(api, "2026-08-06T00:00:00Z")
    consumer_event = X.record_serious_event(
        api, bundle["listing_id"], agent, CONSUMER_EVENT_RECEIVED_AT
    )
    professional_event = X.record_serious_event(
        api, professional["id"], agent, CONSUMER_EVENT_RECEIVED_AT
    )

    X.set_clock(api, FILING_INSTANT)
    timely_event = X.record_serious_event(
        api, bundle["listing_id"], agent, TIMELY_EVENT_RECEIVED_AT
    )

    filed = {
        "consumer": X.file_report(api, consumer_event["id"], agent),
        "professional": X.file_report(api, professional_event["id"], agent),
        "timely": X.file_report(api, timely_event["id"], agent),
    }
    return bundle, professional, filed


class TestAdverseEventPointsAcrossThreeEvents:
    """Base severity, the capped lateness factor and the trade relief factor."""

    def test_two_reports_twelve_days_late_differ_only_by_the_relief_factor(self, api):
        """Both filings overran the same deadline by twelve days, so both take the capped
        lateness factor of 2.0 on the late base of 5; only the trade-only listing's event
        is halved, giving 10.00 against 5.00.

        PRD: "The lateness factor is one plus a tenth per day of lateness, capped at 2.0, so lateness stops accruing at ten days."
        PRD: "The relief factor is 0.5 when the event's listing is `professional_use_only` and 1.0 otherwise, halving the exposure for products sold only into the trade."

        Design: Difficulty/combinatorial_formula/facility_points_three_events_lateness_cap_and_professional_relief
        """
        _bundle, _professional, filed = _three_events_filed_at_one_instant(api)

        consumer = filed["consumer"]
        professional = filed["professional"]

        assert consumer["report_status"] == K.EVENT_STATUS_REPORTED_LATE
        assert professional["report_status"] == K.EVENT_STATUS_REPORTED_LATE
        assert consumer["lateness_days"] == 12
        assert professional["lateness_days"] == 12
        A.assert_two_decimal_value(consumer["event_points"], 10.00, "consumer event_points")
        A.assert_two_decimal_value(professional["event_points"], 5.00, "trade event_points")
        assert consumer["submitted_at"] == FILING_INSTANT

    def test_a_report_inside_its_window_contributes_the_timely_base_only(self, api):
        """The third event was received on 2026-08-30 and filed on 2026-09-01, well inside
        the fifteen-day window, so it carries zero lateness and the timely base of 2.

        PRD: "At or before the deadline the event takes `REPORT_DUE → REPORTED_TIMELY` with `lateness_days` 0."
        PRD: "The base is 2 for a timely report, 5 for a late one and 9 for a report that is overdue and still unfiled — the unfiled state is deliberately the most expensive of the three."

        Design: Difficulty/combinatorial_formula/facility_points_three_events_lateness_cap_and_professional_relief
        """
        _bundle, _professional, filed = _three_events_filed_at_one_instant(api)

        timely = filed["timely"]
        assert timely["report_status"] == K.EVENT_STATUS_REPORTED_TIMELY
        assert timely["lateness_days"] == 0
        A.assert_two_decimal_value(timely["event_points"], 2.00, "timely event_points")
        A.assert_deadline_at_end_of_day(timely["deadline_at"], "2026-09-14")

    def test_three_rounded_contributions_sum_to_seventeen_and_seat_the_posture(self, api):
        """10.00 plus 5.00 plus 2.00 is 17.00 on the establishment, which is at or above
        the restricted threshold and below the frozen one, and every open reporting
        obligation has been discharged.

        PRD: "**Each event's contribution is rounded to two decimals first, and the rounded contributions are then summed**; the sum is itself rounded to two decimals and finally clamped at the ceiling of 100.00."
        PRD: "The points component of the posture is `FROZEN` at 25.00 or more, `RESTRICTED` at 10.00 or more, and `OPEN` below that, with both comparisons inclusive at the boundary and made against the two-decimal stored value: 9.50 leaves the establishment `OPEN`, 10.00 exactly makes it `RESTRICTED`, 24.99 is still `RESTRICTED` and 25.00 is `FROZEN`."

        Design: Difficulty/combinatorial_formula/facility_points_three_events_lateness_cap_and_professional_relief
        """
        bundle, _professional, _filed = _three_events_filed_at_one_instant(api)

        facility = X.read_facility(api, bundle["facility_id"])
        A.assert_two_decimal_value(facility["serious_event_points"], 17.00, "serious_event_points")
        assert facility["compliance_posture"] == K.POSTURE_RESTRICTED
        assert facility["open_serious_event_count"] == 0

    def test_a_serious_event_is_retained_six_years_from_the_instant_it_arrived(self, api):
        """Retention is measured from received_at, so the two events received on different
        days carry different six-year horizons.

        PRD: "A `SERIOUS` intake takes the `RECORDED → REPORT_DUE` edge: `deadline_basis_at` becomes `received_at`, `deadline_at` is computed from it, `retention_until` becomes the calendar date of `received_at` plus six years, and both the listing's and the establishment's `open_serious_event_count` rise by 1."

        Design: Difficulty/combinatorial_formula/facility_points_three_events_lateness_cap_and_professional_relief
        """
        _bundle, _professional, filed = _three_events_filed_at_one_instant(api)

        assert filed["consumer"]["retention_until"] == "2032-08-05"
        assert filed["professional"]["retention_until"] == "2032-08-05"
        assert filed["timely"]["retention_until"] == "2032-08-30"


OBSERVATION_ISSUANCE_INSTANT = "2026-09-05T10:00:00Z"

#: One minor finding in premises, one in raw materials and three critical
#: recordkeeping findings: deductions of 0, 1, 0, 1 and 18.
MIXED_OBSERVATIONS = (
    [F.observation("PREMISES", K.SEVERITY_MINOR)]
    + [F.observation("RAW_MATERIALS", K.SEVERITY_MINOR)]
    + F.repeated_observations("RECORDKEEPING", K.SEVERITY_CRITICAL, 3)
)

EXPECTED_SUBSCORES = {
    "PERSONNEL": 100.00,
    "PREMISES": 96.67,
    "EQUIPMENT": 100.00,
    "RAW_MATERIALS": 96.67,
    "RECORDKEEPING": 40.00,
}


def _engagement_with_mixed_findings(api):
    """An engagement scored at 80.66 with its findings issued on 2026-09-05."""
    facility = X.create_registered_facility(api)
    engagement = X.schedule_inspection(api, facility["id"], "2026-09-01", "2026-09-05")
    X.set_clock(api, OBSERVATION_ISSUANCE_INSTANT)
    issued = X.issue_observations(api, facility["id"], engagement["id"], MIXED_OBSERVATIONS)
    return facility, issued


class TestReadinessScoreRoundingBoundary:
    """Five weighted terms, each rounded to two decimals before the sum."""

    def test_weighted_terms_are_rounded_before_they_are_summed(self, api):
        """Subscores of 100.00, 96.67, 100.00, 96.67 and 40.00 give terms of 15.00, 19.33,
        15.00, 19.33 and 12.00, which add to 80.66 — one cent below what summing the
        unrounded products would report.

        PRD: "Step three multiplies each subscore by that category's weight — `PERSONNEL` 0.15, `PREMISES` 0.20, `EQUIPMENT` 0.15, `RAW_MATERIALS` 0.20 and `RECORDKEEPING` 0.30, weights that sum to exactly 1.00, with recordkeeping deliberately the heaviest because documentation failures are the most predictive of the rest — **and rounds each of the five weighted terms to two decimals before any of them are added**."
        PRD: "Summing the unrounded weighted products and rounding once at the end is a different function and is wrong by a cent on real cases, which is exactly why the boundary is pinned."

        Design: Difficulty/combinatorial_formula/gmp_readiness_rounded_weighted_terms_then_summed
        """
        _facility, issued = _engagement_with_mixed_findings(api)

        A.assert_two_decimal_value(issued["readiness_score"], 80.66, "readiness_score")
        assert issued["readiness_score"] != 80.67
        assert issued["observation_count"] == 5

    def test_every_category_is_scored_including_the_ones_with_no_findings(self, api):
        """The two untouched categories score a full 100.00 and the recordkeeping category
        with eighteen deduction points scores 40.00, all five stored verbatim.

        PRD: "Step two turns each category's deductions into a subscore out of 100: cap the category's deduction points at 30, express the capped figure as a fraction of 30, and subtract that fraction of 100 from 100, rounding the result to two decimals."

        Design: Difficulty/combinatorial_formula/gmp_readiness_rounded_weighted_terms_then_summed
        """
        _facility, issued = _engagement_with_mixed_findings(api)

        A.assert_category_subscores(issued["category_subscores"], EXPECTED_SUBSCORES)

    def test_below_the_clean_close_threshold_the_engagement_asks_for_a_response(self, api):
        """80.66 is under 85.00, so the engagement stays open on the non-terminal marker
        with a response due fifteen days out, and the establishment records the score but
        no outcome.

        PRD: "Below 85.00 the engagement takes `SCHEDULED → OBSERVATIONS_ISSUED`: `response_due_at` is set to the logical clock plus fifteen days, pinned to 23:59:59.999Z of that day, `outcome_class` is set to the non-terminal marker `PENDING_RESPONSE` rather than to any final classification, the establishment's `gmp_readiness_score` is updated, and — this is the part that is easy to get wrong — the establishment's `last_inspection_outcome` is **left alone**, because no outcome has been reached yet."

        Design: Difficulty/combinatorial_formula/gmp_readiness_rounded_weighted_terms_then_summed
        """
        facility, issued = _engagement_with_mixed_findings(api)

        assert issued["status"] == K.INSPECTION_STATUS_OBSERVATIONS_ISSUED
        assert issued["outcome_class"] == K.OUTCOME_CLASS_PENDING_RESPONSE
        A.assert_deadline_at_end_of_day(issued["response_due_at"], "2026-09-20")

        stored = X.read_facility(api, facility["id"])
        A.assert_two_decimal_value(stored["gmp_readiness_score"], 80.66, "gmp_readiness_score")
        assert stored["last_inspection_outcome"] is None

    def test_the_response_decides_nothing_and_the_sweep_closes_the_engagement_vai(self, api):
        """Answering only records the narrative; it is the sweep that reads the stored
        80.66 against 70.00 and closes the engagement as a voluntary-action outcome
        without disturbing the establishment's posture.

        PRD: "A successful response takes `OBSERVATIONS_ISSUED → RESPONSE_SUBMITTED`, stores `response_submitted_at` at the logical clock and the narrative, and **decides nothing**."
        PRD: "For an engagement in `RESPONSE_SUBMITTED`, a `readiness_score` of 70.00 or more takes `RESPONSE_SUBMITTED → CLOSED_VAI`: `outcome_class` becomes `VAI`, the establishment's `last_inspection_outcome` becomes `VAI`, the `compliance_posture` is explicitly **not** disturbed, and one `INSPECTION_OUTCOME` ledger entry is appended."

        Design: Difficulty/combinatorial_formula/gmp_readiness_rounded_weighted_terms_then_summed
        """
        facility, issued = _engagement_with_mixed_findings(api)

        answered = X.respond_to_inspection(api, facility["id"], issued["id"])
        assert answered["status"] == K.INSPECTION_STATUS_RESPONSE_SUBMITTED
        assert answered["response_submitted_at"] == OBSERVATION_ISSUANCE_INSTANT
        assert answered["outcome_class"] == K.OUTCOME_CLASS_PENDING_RESPONSE

        X.set_clock(api, "2026-09-11T00:00:00Z")
        counters = X.run_sweep(api)
        A.assert_sweep_counters(counters, closed_vai_count=1)

        closed = X.read_inspection(api, facility["id"], issued["id"])
        assert closed["status"] == K.INSPECTION_STATUS_CLOSED_VAI
        assert closed["outcome_class"] == K.OUTCOME_CLASS_VAI
        A.assert_two_decimal_value(closed["readiness_score"], 80.66, "readiness_score")

        stored = X.read_facility(api, facility["id"])
        assert stored["last_inspection_outcome"] == K.OUTCOME_CLASS_VAI
        assert stored["compliance_posture"] == K.POSTURE_OPEN

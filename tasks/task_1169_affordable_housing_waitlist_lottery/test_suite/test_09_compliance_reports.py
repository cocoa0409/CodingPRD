"""Compliance reporting: aggregation window variants, counts and basis-point
rates, period overlap, quarter alignment, the submit gate, and the
return-resubmit correction cycle."""
from test_helpers import (
    ApiErrorId, assert_compliance_report, fixtures, get_success_data,
    validate_error, validate_success,
)

AUDITOR = fixtures.AUDITOR
OFFICER = fixtures.OFFICER

Q2_START = "2026-04-01T00:00:00Z"
Q2_END = "2026-06-30T00:00:00Z"


def _spring_campaign_with_two_applications(api):
    """Campaign window 2026-03-01..2026-06-25; application X created at
    2026-03-25T10:00:00Z, application Z at 2026-05-10T10:00:00Z."""
    prop = fixtures.new_property(api)
    campaign = fixtures.new_campaign(
        api, prop["id"], name="Spring 2026",
        application_open_at="2026-03-01T00:00:00Z",
        application_close_at="2026-06-25T00:00:00Z")
    fixtures.announce_campaign(api, campaign["id"])
    fixtures.set_clock("2026-03-25T10:00:00Z", api)
    fixtures.open_campaign(api, campaign["id"])
    applicant_x = fixtures.new_applicant(api, full_name="Xavier Young",
                                         email="x@x.com")
    fixtures.submit_application(api, campaign["id"], applicant_x["id"])
    fixtures.set_clock("2026-05-10T10:00:00Z", api)
    applicant_z = fixtures.new_applicant(api, full_name="Zoe Zimmer",
                                         email="z@x.com")
    fixtures.submit_application(api, campaign["id"], applicant_z["id"],
                                household_size=1,
                                self_reported_annual_income_cents=2_500_000)
    return campaign


def test_report_calendar_quarter_window_counts(api):
    """PRD §3.8: "Under `CALENDAR_QUARTER` the declared period must describe
    exactly one calendar quarter — `period_start` on the first day of a
    quarter at 00:00:00Z and `period_end` on the last day of that same
    quarter; a misaligned declaration is rejected with `ERR_INVALID_REQUEST`
    — and the effective aggregation window runs from the quarter's start
    inclusive to three months later exclusive, a half-open window."

    Design: Difficulty/dual_variant_calc/report_window_variants_diverge
    """
    campaign = _spring_campaign_with_two_applications(api)
    report = fixtures.new_report(api, campaign["id"], period_start=Q2_START,
                                 period_end=Q2_END,
                                 period_mode="CALENDAR_QUARTER")
    assert_compliance_report(report)
    # [2026-04-01, 2026-07-01) is end-exclusive: only the 2026-05-10
    # application falls inside; the 2026-03-25 one does not.
    assert report["applications_received_count"] == 1


def test_report_rolling_90_day_window_counts(api):
    """PRD §3.8: "Under `ROLLING_90_DAY` the effective window slides: it
    opens 90 days before `period_end` at 00:00:00Z and closes on `period_end`
    at 23:59:59.999Z, both ends inclusive. Because the two variants draw
    their boundaries differently, the same underlying events can yield
    different counts under different modes."

    Design: Difficulty/dual_variant_calc/report_window_variants_diverge
    """
    campaign = _spring_campaign_with_two_applications(api)
    report = fixtures.new_report(api, campaign["id"],
                                 period_start="2026-03-17T00:00:00Z",
                                 period_end="2026-06-15T00:00:00Z",
                                 period_mode="ROLLING_90_DAY")
    # [2026-03-17, 2026-06-15] inclusive holds both the 2026-03-25 and the
    # 2026-05-10 applications — the same events the quarter window counted
    # as one.
    assert report["applications_received_count"] == 2


def test_report_rates_and_counts_in_basis_points(api):
    """PRD §3.8: "Two rates derive from them, each in integer basis points
    rounded half-up: `preference_verification_rate_bp` multiplies verified
    claims by ten thousand and divides by decided claims, and
    `lease_up_rate_bp` multiplies accepted offers by ten thousand and divides
    by offers made; when a denominator is zero the corresponding rate is 0,
    never an error."

    Design: Corner/calculations/report_rates_and_counts_in_basis_points
    """
    world = fixtures.setup_leasing_pipeline(
        api, seed="SEED-RATES", num_units=2,
        applications=[
            {"full_name": "Pia P", "email": "p8@x.com",
             "claims": [("LOCAL_RESIDENT", "lease", "VERIFY"),
                        ("VETERAN", "dd214", "DENY")]},
            {"full_name": "Rex R", "email": "r8@x.com",
             "claims": [("ACCESSIBILITY", "mobility-cert", "VERIFY")]},
        ])
    campaign_id = world["campaign"]["id"]
    generation = fixtures.generate_offers(api, campaign_id)
    assert generation["generated_count"] == 2
    offer1, offer2 = fixtures.list_offers(api, campaign_id, status="PENDING")
    fixtures.accept_offer(api, offer1)
    fixtures.decline_offer(api, offer2)

    report = fixtures.new_report(api, campaign_id, period_start=Q2_START,
                                 period_end=Q2_END,
                                 period_mode="CALENDAR_QUARTER")
    assert report["applications_received_count"] == 2
    assert report["applications_verified_count"] == 2
    assert report["preference_claims_decided_count"] == 3
    assert report["preference_claims_verified_count"] == 2
    # round_half_up(2/3 x 10000) = round_half_up(6666.66...) = 6667
    assert report["preference_verification_rate_bp"] == 6667
    assert report["lottery_runs_executed_count"] == 1
    assert report["offers_made_count"] == 2
    assert report["offers_accepted_count"] == 1
    # round_half_up(1/2 x 10000) = 5000
    assert report["lease_up_rate_bp"] == 5000
    assert report["entries_removed_count"] == 0, (
        "a first decline is not a removal"
    )


def test_report_return_resubmit_cycle_recomputes_aggregates(api):
    """PRD §3.8: "A returned report may be resubmitted under the same
    submission preconditions, and resubmission recomputes every aggregate
    against the effective window at the resubmission instant, refreshes
    `submitted_by` and `submitted_at`, and clears the `return_reason`."

    Design: Corner/state_machines/report_return_resubmit_cycle_recomputes_aggregates
    """
    world = fixtures.setup_leasing_pipeline(api, seed="SEED-RC", num_units=0,
                                            certify=False)
    campaign_id = world["campaign"]["id"]
    entry = fixtures.get_entry_for_application(
        api, world["applications"][0]["id"])

    report = fixtures.new_report(api, campaign_id, period_start=Q2_START,
                                 period_end=Q2_END,
                                 period_mode="CALENDAR_QUARTER")
    assert report["entries_removed_count"] == 0
    fixtures.report_action(api, report["id"], "SUBMIT", OFFICER)
    fixtures.report_action(api, report["id"], "RETURN", AUDITOR,
                           return_reason="missing removal activity")

    # A removal lands inside the same quarter window before resubmission.
    validate_success(api.remove_waitlist_entry(
        entry["id"], {"removal_reason": "ADMIN_REMOVED"}, fixtures.DEVELOPER))
    resubmitted = fixtures.report_action(api, report["id"], "SUBMIT", OFFICER)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["entries_removed_count"] == 1, (
        "aggregates are recomputed at the resubmission instant"
    )
    assert resubmitted["return_reason"] is None


def test_report_period_shared_boundary_conflicts(api):
    """PRD §3.8: "Declared periods on the same campaign must not collide:
    treated as closed intervals, two periods overlap when each starts on or
    before the other ends, and any overlap with an existing report in
    `SUBMITTED` or `ACKNOWLEDGED` status is rejected with
    `ERR_REPORT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/report_periods_closed_interval_shared_boundary_conflicts
    """
    world = fixtures.setup_leasing_pipeline(api, seed="SEED-REP", num_units=0,
                                            certify=False)
    campaign_id = world["campaign"]["id"]
    report_a = fixtures.new_report(api, campaign_id, period_start=Q2_START,
                                   period_end=Q2_END,
                                   period_mode="CALENDAR_QUARTER")
    fixtures.report_action(api, report_a["id"], "SUBMIT", OFFICER)

    # Closed intervals: sharing the 2026-06-30 boundary date is an overlap.
    resp = api.create_compliance_report(
        fixtures.create_compliance_report_payload(
            campaign_id, period_start="2026-06-30T00:00:00Z",
            period_end="2026-08-01T00:00:00Z", period_mode="ROLLING_90_DAY"),
        OFFICER)
    validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)


def test_report_period_first_disjoint_day_accepted(api):
    """PRD §3.8: "treated as closed intervals, two periods overlap when each
    starts on or before the other ends, and any overlap with an existing
    report in `SUBMITTED` or `ACKNOWLEDGED` status is rejected with
    `ERR_REPORT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/report_periods_closed_interval_shared_boundary_conflicts
    """
    world = fixtures.setup_leasing_pipeline(api, seed="SEED-REP", num_units=0,
                                            certify=False)
    campaign_id = world["campaign"]["id"]
    report_a = fixtures.new_report(api, campaign_id, period_start=Q2_START,
                                   period_end=Q2_END,
                                   period_mode="CALENDAR_QUARTER")
    fixtures.report_action(api, report_a["id"], "SUBMIT", OFFICER)

    report_c = validate_success(api.create_compliance_report(
        fixtures.create_compliance_report_payload(
            campaign_id, period_start="2026-07-01T00:00:00Z",
            period_end="2026-08-01T00:00:00Z", period_mode="ROLLING_90_DAY"),
        OFFICER), expected_status=201)
    assert report_c["status"] == "DRAFT", (
        "2026-07-01 is the first day disjoint from the closed interval "
        "ending 2026-06-30"
    )


def test_quarter_misaligned_report_returns_invalid_request(api):
    """PRD §3.8: "Under `CALENDAR_QUARTER` the declared period must describe
    exactly one calendar quarter — `period_start` on the first day of a
    quarter at 00:00:00Z and `period_end` on the last day of that same
    quarter; a misaligned declaration is rejected with `ERR_INVALID_REQUEST`".

    Design: Corner/validations/quarter_misaligned_report_returns_invalid_request
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_campaign(api, prop["id"])
    resp = api.create_compliance_report(
        fixtures.create_compliance_report_payload(
            campaign["id"], period_start="2026-04-02T00:00:00Z",
            period_end=Q2_END, period_mode="CALENDAR_QUARTER"),
        OFFICER)
    # 2026-04-02 is not the first day of a calendar quarter.
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_report_submit_without_published_lottery_returns_incomplete_data(api):
    """PRD §3.8: "A `ComplianceOfficer` submits the report only when the
    campaign has at least one lottery run in `PUBLISHED` status and the
    campaign itself sits in `LOTTERY_COMPLETED`, `LEASING`,
    `PURGE_SCHEDULED`, or `PURGED`; failing either condition is rejected with
    `ERR_REPORT_INCOMPLETE_DATA`."

    Design: Corner/validations/report_submit_without_published_lottery_returns_incomplete_data
    """
    prop = fixtures.new_property(api)
    campaign = fixtures.new_campaign(api, prop["id"])
    report = fixtures.new_report(api, campaign["id"], period_start=Q2_START,
                                 period_end=Q2_END,
                                 period_mode="CALENDAR_QUARTER")
    resp = api.transition_compliance_report(report["id"],
                                            {"action": "SUBMIT"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_REPORT_INCOMPLETE_DATA)
    fetched = get_success_data(api.get_compliance_report(report["id"], OFFICER))
    assert fetched["status"] == "DRAFT"

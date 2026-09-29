"""Nested cap ceilings, per-category rounding, and the frozen audit sample size.

Every figure asserted here is a composite of several pinned arithmetic steps
whose order the PRD fixes, so each test drives one whole world through the
board's own sequence rather than checking a single subtraction.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    audit_action,
    create_accredited_provider,
    create_attorney,
    create_credit_record_payload,
    create_cycle,
    create_self_certified_course,
    credit_allocation_entry,
    dispose_complaint,
    file_code_verified_record,
    file_complaint,
    file_roster,
    make_attorney_headers,
    open_audit,
    read_audit,
    read_credit_record,
    read_cycle,
    read_provider,
    roster_entry,
    validate_error,
    validate_success,
)

BOARD = TEST_USERS["board_admin_headers"]


def _four_records_each_with_a_different_binding_ceiling():
    """One period holding four attendance-code claims: two on demand, one of
    self study, one webcast.

    The first on-demand claim fills the 720-minute on-demand allowance outright.
    The second therefore has no on-demand room left. The self-study claim still
    has its whole 360-minute self-study allowance, but the shared 900-minute
    non-live allowance has only 180 minutes left in it. The webcast claim is
    verified by attendance code, which makes it live, and live minutes face no
    ceiling at all.
    """
    provider = create_accredited_provider(
        name="Northgate CLE Group", provider_type="LAW_SCHOOL"
    )
    on_demand_one = create_self_certified_course(
        provider,
        title="Recorded Civil Procedure Marathon",
        delivery_format="ON_DEMAND",
        total_minutes=720,
        presented_at="2026-01-02T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[credit_allocation_entry("GENERAL", 720)],
    )
    on_demand_two = create_self_certified_course(
        provider,
        title="Recorded Evidence Refresher",
        delivery_format="ON_DEMAND",
        total_minutes=180,
        presented_at="2026-01-03T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[credit_allocation_entry("GENERAL", 180)],
    )
    self_study = create_self_certified_course(
        provider,
        title="Self-Paced Appellate Briefing",
        delivery_format="SELF_STUDY",
        total_minutes=240,
        presented_at="2026-01-04T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[credit_allocation_entry("GENERAL", 240)],
    )
    webcast = create_self_certified_course(
        provider,
        title="Live Webcast: Contract Drafting",
        delivery_format="LIVE_WEBCAST",
        total_minutes=600,
        presented_at="2026-03-15T08:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[credit_allocation_entry("GENERAL", 600)],
    )
    attorney = create_attorney(
        bar_number="BAR-2002",
        full_name="Marcus Idowu",
        admission_date="2012-09-15T00:00:00Z",
        compliance_group="GROUP_2",
        principal_office_jurisdiction="ST",
    )
    cycle = create_cycle(
        attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z"
    )
    record_on_demand_one = file_code_verified_record(
        attorney, on_demand_one, attended_minutes=720,
        completion_date="2026-02-01T00:00:00Z",
    )
    record_on_demand_two = file_code_verified_record(
        attorney, on_demand_two, attended_minutes=180,
        completion_date="2026-02-15T00:00:00Z",
    )
    record_self_study = file_code_verified_record(
        attorney, self_study, attended_minutes=240,
        completion_date="2026-03-01T00:00:00Z",
    )
    record_webcast = file_code_verified_record(
        attorney, webcast, attended_minutes=600,
        completion_date="2026-03-15T18:00:00Z",
    )
    return {
        "attorney": attorney,
        "cycle": cycle,
        "record_on_demand_one": record_on_demand_one,
        "record_on_demand_two": record_on_demand_two,
        "record_self_study": record_self_study,
        "record_webcast": record_webcast,
    }


def test_second_on_demand_claim_is_cut_to_zero_by_the_exhausted_format_allowance(api):
    """A record whose `effective_format` is `ON_DEMAND` has its room reduced to the smallest of its own credited minutes, the 720-minute on-demand allowance (12 credit hours per cycle) less on-demand minutes already used, and the same 900-minute non-live allowance less non-live minutes already used.
    The records in the variant's input set are processed in ascending order of `completion_date`, breaking ties by ascending `created_at`.
    Whatever room survives is floored at zero, and the result is that record's `countable_minutes`.

    Design: Difficulty/combinatorial_formula/nested_min_format_cap_room_across_three_simultaneous_ceilings
    """
    world = _four_records_each_with_a_different_binding_ceiling()

    first = read_credit_record(world["record_on_demand_one"]["id"])
    assert first["effective_format"] == "ON_DEMAND"
    assert first["countable_minutes"] == 720

    second = read_credit_record(world["record_on_demand_two"]["id"])
    assert second["effective_format"] == "ON_DEMAND"
    assert second["credited_minutes"] == 180
    assert second["countable_minutes"] == 0


def test_self_study_claim_is_cut_by_the_shared_ceiling_though_its_own_is_untouched(api):
    """A record whose `effective_format` is `SELF_STUDY` has its room reduced to the smallest of three quantities: its own credited minutes, the 360-minute self-study allowance (6 credit hours per cycle) less self-study minutes already used, and the 900-minute non-live allowance (15 credit hours per cycle) less non-live minutes already used.
    A `LIVE_WEBCAST` course yields `LIVE` only when attendance was verified by `ATTENDANCE_CODE` or by `ROSTER` — the two methods that prove someone was actually watching in real time — and otherwise yields `ON_DEMAND`.
    Live minutes are never capped.

    Design: Difficulty/combinatorial_formula/nested_min_format_cap_room_across_three_simultaneous_ceilings
    """
    world = _four_records_each_with_a_different_binding_ceiling()

    self_study = read_credit_record(world["record_self_study"]["id"])
    assert self_study["effective_format"] == "SELF_STUDY"
    assert self_study["credited_minutes"] == 240
    assert self_study["countable_minutes"] == 180

    webcast = read_credit_record(world["record_webcast"]["id"])
    assert webcast["effective_format"] == "LIVE"
    assert webcast["countable_minutes"] == 600


def test_cycle_totals_accumulate_only_the_minutes_that_survived_every_ceiling(api):
    """When every record in the input set has been processed, the overall countable total becomes `earned_countable_minutes`, the three specialty running totals become `earned_ethics_minutes`, `earned_technology_minutes` and `earned_bias_minutes`, and the running live total becomes `earned_live_minutes`.

    Design: Difficulty/combinatorial_formula/nested_min_format_cap_room_across_three_simultaneous_ceilings
    """
    world = _four_records_each_with_a_different_binding_ceiling()

    cycle = read_cycle(world["cycle"]["id"])
    assert cycle["earned_countable_minutes"] == 1500
    assert cycle["earned_live_minutes"] == 600


def test_summary_reports_the_allowance_consumption_behind_those_ceilings(api):
    """After the record is accounted for, the run adds its countable minutes to the overall countable total; adds them to the self-study and non-live allowances used when its `effective_format` is `SELF_STUDY`; adds them to the on-demand and non-live allowances used when its `effective_format` is `ON_DEMAND`; adds them to the running live total when its `effective_format` is `LIVE`; and adds them to the reciprocity allowance used when its `source` is `RECIPROCITY`.
    Four bucket fields report the **provisional** run's cap consumption: `self_study_used_minutes`, `on_demand_used_minutes`, `nonlive_used_minutes` and `reciprocity_used_minutes`.

    Design: Difficulty/combinatorial_formula/nested_min_format_cap_room_across_three_simultaneous_ceilings
    """
    world = _four_records_each_with_a_different_binding_ceiling()

    summary = validate_success(
        api.get_cycle_summary(world["cycle"]["id"], BOARD), expected_status=200
    )
    assert summary["on_demand_used_minutes"] == 720
    assert summary["self_study_used_minutes"] == 180
    assert summary["nonlive_used_minutes"] == 900
    assert summary["projected_final_deficiency_total_minutes"] == 300
    assert summary["projected_final_deficiency_ethics_minutes"] == 180


def _partly_attended_three_category_session():
    """A 300-minute live session split across three categories, and an attorney
    who sat through 200 of those minutes."""
    provider = create_accredited_provider(
        name="Harborview Bar Academy", provider_type="LAW_SCHOOL"
    )
    course = create_self_certified_course(
        provider,
        title="Ethics, Tech and Practice Day",
        delivery_format="LIVE_IN_PERSON",
        total_minutes=300,
        presented_at="2026-03-02T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[
            credit_allocation_entry("ETHICS", 90),
            credit_allocation_entry("TECHNOLOGY", 60),
            credit_allocation_entry("GENERAL", 150),
        ],
    )
    attorney = create_attorney(
        bar_number="BAR-3003",
        full_name="Priya Venkataraman",
        admission_date="2015-01-20T00:00:00Z",
        compliance_group="GROUP_1",
        principal_office_jurisdiction="ST",
    )
    cycle = create_cycle(
        attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z"
    )
    return {"course": course, "attorney": attorney, "cycle": cycle}


def test_each_category_is_floored_to_a_quarter_hour_before_anything_is_added(api):
    """Each raw entitlement is then rounded **down** to the nearest whole multiple of 15 minutes, and the four results are written to `credited_ethics_minutes`, `credited_technology_minutes`, `credited_bias_minutes` and `credited_general_minutes`.
    Only after all four have been individually rounded down are they added together to give `credited_minutes`.
    This order is pinned: rounding each category first and summing afterwards is the rule, and summing the exact prorated values and rounding once at the end is not — the two produce different totals, and only the first is correct here.

    Design: Difficulty/combinatorial_formula/per_category_rounding_before_summation_on_partial_attendance
    """
    world = _partly_attended_three_category_session()

    record = file_code_verified_record(
        world["attorney"], world["course"], attended_minutes=200,
        completion_date="2026-03-02T14:00:00Z",
    )

    assert record["credited_ethics_minutes"] == 60
    assert record["credited_technology_minutes"] == 30
    assert record["credited_general_minutes"] == 90
    assert record["credited_bias_minutes"] == 0
    assert record["credited_minutes"] == 180


def test_the_rounded_down_total_is_what_reaches_the_period(api):
    """Live minutes are never capped.
    Each run rewrites the cycle's `earned_countable_minutes`, `earned_ethics_minutes`, `earned_technology_minutes`, `earned_bias_minutes` and `earned_live_minutes`, and rewrites `countable_minutes` on every credit record of that cycle.
    A `LIVE_IN_PERSON` course always yields `LIVE`.

    Design: Difficulty/combinatorial_formula/per_category_rounding_before_summation_on_partial_attendance
    """
    world = _partly_attended_three_category_session()

    record = file_code_verified_record(
        world["attorney"], world["course"], attended_minutes=200,
        completion_date="2026-03-02T14:00:00Z",
    )
    assert record["status"] == "VERIFIED"
    assert record["effective_format"] == "LIVE"
    assert read_credit_record(record["id"])["countable_minutes"] == 180

    cycle = read_cycle(world["cycle"]["id"])
    assert cycle["earned_ethics_minutes"] == 60
    assert cycle["earned_technology_minutes"] == 30
    assert cycle["earned_countable_minutes"] == 180


def test_a_short_sitting_falls_below_the_floor_only_under_per_category_rounding(api):
    """Once the sum is known, a floor applies: a claim whose `credited_minutes` comes to less than 30 minutes is not worth recording, and the request is rejected with `ERR_BELOW_MINIMUM_CREDIT`.
    Only after all four have been individually rounded down are they added together to give `credited_minutes`.

    Design: Difficulty/combinatorial_formula/per_category_rounding_before_summation_on_partial_attendance
    """
    world = _partly_attended_three_category_session()
    attorney = world["attorney"]

    payload = create_credit_record_payload(
        attorney["id"],
        world["course"]["id"],
        verification_method="ATTENDANCE_CODE",
        attended_minutes=45,
        completion_date="2026-03-02T14:00:00Z",
        attendance_code=world["course"]["attendance_code"],
    )
    payload.pop("certificate_reference", None)

    response = api.create_credit_record(payload, make_attorney_headers(attorney["id"]))
    validate_error(response, "ERR_BELOW_MINIMUM_CREDIT")

    assert read_cycle(world["cycle"]["id"])["earned_countable_minutes"] == 0


def _sponsor_with_late_rosters_and_one_sampled_audit():
    """A sponsor whose two late rosters out of three put its score just under the
    middle sampling tier, with a complaint waiting under review and an audit
    already drawn once over a three-course window.
    """
    provider = create_accredited_provider(
        name="Cascade Legal Education", provider_type="BAR_ASSOCIATION"
    )
    pool = []
    for title, presented_at in (
        ("Sampled Course Alpha", "2026-06-05T09:00:00Z"),
        ("Sampled Course Bravo", "2026-06-12T09:00:00Z"),
        ("Sampled Course Charlie", "2026-06-25T09:00:00Z"),
    ):
        pool.append(
            create_self_certified_course(
                provider,
                title=title,
                delivery_format="SELF_STUDY",
                total_minutes=120,
                presented_at=presented_at,
                attendance_verification_method="AFFIRMATION_ONLY",
                credit_allocations=[credit_allocation_entry("GENERAL", 120)],
            )
        )
    roster_course = create_self_certified_course(
        provider,
        title="Roster Carrier Live Seminar",
        delivery_format="LIVE_IN_PERSON",
        total_minutes=120,
        presented_at="2026-05-10T09:00:00Z",
        attendance_verification_method="ROSTER",
        credit_allocations=[credit_allocation_entry("GENERAL", 120)],
    )
    late_one = file_roster(
        provider["id"], roster_course["id"], "2026-06-01T09:00:00Z",
        [roster_entry("BAR-UNKNOWN-1", 120)],
    )
    late_two = file_roster(
        provider["id"], roster_course["id"], "2026-06-15T09:00:00Z",
        [roster_entry("BAR-UNKNOWN-2", 120)],
    )
    on_time = file_roster(
        provider["id"], roster_course["id"], "2026-07-15T09:00:00Z",
        [roster_entry("BAR-UNKNOWN-3", 120)],
    )
    complaint = file_complaint(
        "PROVIDER",
        provider["id"],
        filer_user_id="board-intake-7",
        allegation="Course materials misstate the credit category.",
        allegation_category="MISREPRESENTED_CREDIT",
    )
    dispose_complaint(complaint["id"], "OPEN_REVIEW", "board-review-9")
    audit = open_audit(
        provider["id"], "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z", "RISK_BASED"
    )
    audit = audit_action(audit["id"], "DRAW_SAMPLE", audit["version"])
    return {
        "provider": provider,
        "pool": pool,
        "late_one": late_one,
        "late_two": late_two,
        "on_time": on_time,
        "complaint": complaint,
        "audit": audit,
    }


def test_roster_lateness_is_counted_in_whole_days_from_the_due_instant(api):
    """A roster arriving at or before `due_at` has `days_late` of 0 and a `status` of `ACCEPTED`.
    A roster arriving after `due_at` but at or before the hard close has `days_late` set to the number of days from `due_at` to now, rounded **up** so that any part of a day counts as a whole day, and a `status` of `ACCEPTED_LATE`; a late acceptance also raises the sponsor's `attendance_reports_late_count` by one, which feeds directly into its risk score.
    Every accepted roster, late or not, raises the sponsor's `attendance_reports_total_count` by one, and the sponsor's `risk_score` is recomputed afterwards.

    Design: Difficulty/combinatorial_formula/frozen_risk_at_open_resolves_the_sample_size_risk_score_circularity
    """
    world = _sponsor_with_late_rosters_and_one_sampled_audit()

    assert world["late_one"]["status"] == "ACCEPTED_LATE"
    assert world["late_one"]["days_late"] == 31
    assert world["on_time"]["status"] == "ACCEPTED"
    assert world["on_time"]["days_late"] == 0

    provider = read_provider(world["provider"]["id"])
    assert provider["attendance_reports_total_count"] == 3
    assert provider["attendance_reports_late_count"] == 2


def test_the_frozen_score_puts_the_engagement_in_the_lowest_sampling_tier(api):
    """It also captures `risk_score_at_open`: the provider's risk score computed at that moment and **frozen** onto the audit row, never refreshed afterwards even as the provider's live `risk_score` moves.
    That frozen number, and nothing else, decides how large a sample the engagement draws.
    The delinquency rate is `attendance_reports_late_count` divided by `attendance_reports_total_count`, where the denominator is treated as one whenever the stored count is zero, so a provider that has filed nothing has a delinquency rate of zero rather than an undefined one.
    `sample_size` is then the smaller of the target and the pool size — a pool smaller than the target simply yields a short sample and is not an error — and `sampled_course_ids` is the identifiers of the first `sample_size` entries of the sorted pool, in that order.

    Design: Difficulty/combinatorial_formula/frozen_risk_at_open_resolves_the_sample_size_risk_score_circularity
    """
    world = _sponsor_with_late_rosters_and_one_sampled_audit()

    audit = read_audit(world["audit"]["id"])
    assert audit["risk_score_at_open"] == pytest.approx(0.23, abs=0.001)
    assert audit["status"] == "SAMPLED"
    assert audit["sample_size"] == 2
    assert audit["sampled_course_ids"] == [
        world["pool"][0]["id"], world["pool"][1]["id"],
    ]


def test_substantiating_the_complaint_lifts_the_live_score_over_the_tier_line(api):
    """Against a provider, the provider's `substantiated_complaint_count` rises by one, its `risk_score` is recomputed, and the provider itself moves `ACCREDITED → PROBATIONARY`.
    The complaint rate is `substantiated_complaint_count` divided by three, capped at 1.0 — three substantiated complaints saturate the term.
    `risk_score` is then the delinquency rate weighted at 0.35, plus the complaint rate weighted at 0.30, plus the finding rate weighted at 0.25, plus the staleness rate weighted at 0.10, and the sum is rounded half-up to two decimal places.

    Design: Difficulty/combinatorial_formula/frozen_risk_at_open_resolves_the_sample_size_risk_score_circularity
    """
    world = _sponsor_with_late_rosters_and_one_sampled_audit()

    dispose_complaint(
        world["complaint"]["id"], "SUBSTANTIATE", "board-review-9",
        disposition_reason="Category misstatement confirmed in two courses.",
    )

    provider = read_provider(world["provider"]["id"])
    assert provider["substantiated_complaint_count"] == 1
    assert provider["accreditation_status"] == "PROBATIONARY"
    assert provider["risk_score"] == pytest.approx(0.33, abs=0.001)


def test_a_redraw_still_obeys_the_frozen_score_and_replaces_the_prior_sample(api):
    """`DRAW_SAMPLE` moves the audit `OPENED → SAMPLED`, and is also legitimately repeatable as a `SAMPLED → SAMPLED` redraw, which is exactly why the version guard exists.
    The target size comes from the frozen score in three tiers: ten courses when `risk_score_at_open` is 0.60 or above, five when it is 0.30 or above but below 0.60, and two otherwise.
    A redraw recomputes the whole list from scratch rather than appending to it, and the provider's `courses_sampled_lifetime` is adjusted by the difference between the new and prior `sample_size` — on a first draw that difference is simply the new sample size.

    Design: Difficulty/combinatorial_formula/frozen_risk_at_open_resolves_the_sample_size_risk_score_circularity
    """
    world = _sponsor_with_late_rosters_and_one_sampled_audit()
    dispose_complaint(
        world["complaint"]["id"], "SUBSTANTIATE", "board-review-9",
        disposition_reason="Category misstatement confirmed in two courses.",
    )

    redrawn = audit_action(
        world["audit"]["id"], "DRAW_SAMPLE", world["audit"]["version"]
    )

    assert redrawn["status"] == "SAMPLED"
    assert redrawn["sample_size"] == 2
    assert redrawn["risk_score_at_open"] == pytest.approx(0.23, abs=0.001)
    assert redrawn["sampled_course_ids"] == [
        world["pool"][0]["id"], world["pool"][1]["id"],
    ]
    assert read_provider(world["provider"]["id"])["courses_sampled_lifetime"] == 2

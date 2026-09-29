"""Endpoint contract compliance for the CLE accreditation and credit API.

Every test builds its own register from scratch through the endpoints the PRD
declares, because the database is empty and the logical clock reads
2026-08-01T00:00:00Z when each test begins.
"""
from datetime import datetime

from test_helpers import (
    api_client,
    factories as fac,
    fixtures as fx,
    get_success_data,
    make_attorney_headers,
    make_provider_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

BOARD = TEST_USERS["board_admin_headers"]
MISSING_ATTORNEY_ID = "00000000-0000-4000-8000-00000000dead"


# --- local helpers ---------------------------------------------------------

def _instant(value):
    """Parses an ISO 8601 UTC timestamp into a comparable datetime."""
    assert value and type(value) is str, f"expected a timestamp, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _same_instant(actual, expected, label):
    assert _instant(actual) == _instant(expected), (
        f"{label} must be {expected}, got {actual}"
    )


def _claim_payload(attorney_id, course_id, **overrides):
    """A credit claim body carrying a certificate reference only where the
    verification method is CERTIFICATE."""
    payload = fac.create_credit_record_payload(attorney_id, course_id, **overrides)
    if payload.get("verification_method") != "CERTIFICATE":
        payload.pop("certificate_reference", None)
    return payload


def _file_claim(attorney_id, course_id, **overrides):
    payload = _claim_payload(attorney_id, course_id, **overrides)
    return get_success_data(
        api_client.create_credit_record(payload, make_attorney_headers(attorney_id))
    )


def _setup_one_verified_and_one_pending_record():
    """An accredited sponsor, one webcast course proved by its minted code and
    one self-study course proved by affirmation, and an attorney whose period
    holds one VERIFIED record of 300 live minutes and one
    PENDING_VERIFICATION record of 600 self-study minutes."""
    provider = fx.create_accredited_provider(
        name="Summit Bar Education", provider_type="BAR_ASSOCIATION"
    )
    course_a = fx.create_self_certified_course(
        provider,
        title="Webcast Civil Procedure",
        delivery_format="LIVE_WEBCAST",
        total_minutes=300,
        presented_at="2026-02-01T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[fac.credit_allocation_entry("GENERAL", 300)],
    )
    course_b = fx.create_self_certified_course(
        provider,
        title="Self Study Ethics Compendium",
        delivery_format="SELF_STUDY",
        total_minutes=600,
        presented_at="2026-03-01T09:00:00Z",
        attendance_verification_method="AFFIRMATION_ONLY",
        credit_allocations=[
            fac.credit_allocation_entry("ETHICS", 180),
            fac.credit_allocation_entry("GENERAL", 420),
        ],
    )
    attorney = fx.create_attorney(
        full_name="Sofia Marchetti",
        admission_date="2003-01-01T00:00:00Z",
        compliance_group="GROUP_1",
    )
    cycle = fx.create_cycle(
        attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z"
    )
    record_a = _file_claim(
        attorney["id"], course_a["id"],
        verification_method="ATTENDANCE_CODE",
        attendance_code=course_a["attendance_code"],
        attended_minutes=300,
        completion_date="2026-02-01T13:00:00Z",
    )
    record_b = _file_claim(
        attorney["id"], course_b["id"],
        verification_method="AFFIRMATION",
        attended_minutes=600,
        completion_date="2026-04-01T00:00:00Z",
    )
    return attorney, cycle, record_a, record_b


# --- the computed cycle read ----------------------------------------------

def test_cycle_summary_returns_provisional_and_projected_final_side_by_side(api):
    """Because the provisional and final pictures can diverge sharply, the cycle summary read runs the algorithm *both* ways over the same stored data and returns the two results side by side without persisting anything.
    The **provisional** variant includes the cycle's records in `PENDING_VERIFICATION` and `VERIFIED`. The **final** variant includes only those in `VERIFIED`.
    Four bucket fields report the **provisional** run's cap consumption: `self_study_used_minutes`, `on_demand_used_minutes`, `nonlive_used_minutes` and `reciprocity_used_minutes`.
    Two counts close the payload: `records_counted` is the size of the provisional input set, and `records_excluded` is the number of the cycle's records in `REJECTED` or `VOIDED`.

    Design: Corner/endpoints/the_cycle_summary_read_returns_both_variants_side_by_side_without_mutating_anything
    """
    attorney, cycle, verified_record, pending_record = (
        _setup_one_verified_and_one_pending_record()
    )
    assert verified_record["status"] == "VERIFIED", verified_record["status"]
    assert pending_record["status"] == "PENDING_VERIFICATION", pending_record["status"]

    response = api.get_cycle_summary(cycle["id"], make_attorney_headers(attorney["id"]))
    summary = validate_success(response, expected_status=200)

    assert summary["cycle_id"] == cycle["id"]
    assert summary["credit_status"] == "OPEN", summary["credit_status"]
    assert summary["administrative_status"] == "GOOD_STANDING", (
        summary["administrative_status"]
    )
    assert summary["required_total_minutes"] == 1800
    assert summary["required_ethics_minutes"] == 180
    assert summary["required_technology_minutes"] == 60
    assert summary["required_bias_minutes"] == 120

    # The provisional run sees the live 300 and 360 of the 600 self-study
    # minutes, truncating the excess out of GENERAL before ETHICS.
    assert summary["provisional_total_minutes"] == 660
    assert summary["provisional_ethics_minutes"] == 180
    assert summary["provisional_technology_minutes"] == 0
    assert summary["provisional_bias_minutes"] == 0
    assert summary["provisional_live_minutes"] == 300
    assert summary["provisional_deficiency_total_minutes"] == 1140
    assert summary["provisional_deficiency_ethics_minutes"] == 0

    # The final run sees only the verified live session.
    assert summary["projected_final_total_minutes"] == 300
    assert summary["projected_final_ethics_minutes"] == 0
    assert summary["projected_final_technology_minutes"] == 0
    assert summary["projected_final_bias_minutes"] == 0
    assert summary["projected_final_live_minutes"] == 300
    assert summary["projected_final_deficiency_total_minutes"] == 1500
    assert summary["projected_final_deficiency_ethics_minutes"] == 180
    assert summary["projected_final_deficiency_technology_minutes"] == 60
    assert summary["projected_final_deficiency_bias_minutes"] == 120

    # The buckets report the provisional run only.
    assert summary["self_study_used_minutes"] == 360
    assert summary["on_demand_used_minutes"] == 0
    assert summary["nonlive_used_minutes"] == 360
    assert summary["reciprocity_used_minutes"] == 0

    assert summary["carryover_in_general_minutes"] == 0
    assert summary["carryover_in_ethics_minutes"] == 0
    assert summary["projected_carryover_out_general_minutes"] == 0
    assert summary["projected_carryover_out_ethics_minutes"] == 0
    assert summary["projected_late_fee_cents"] == 100000

    assert summary["records_counted"] == 2
    assert summary["records_excluded"] == 0


def test_cycle_summary_read_persists_nothing(api):
    """Because the provisional and final pictures can diverge sharply, the cycle summary read runs the algorithm *both* ways over the same stored data and returns the two results side by side without persisting anything.
    While a cycle's `credit_status` is `OPEN`, the provisional result is what gets persisted into the cycle's `earned_*` fields and into each record's `countable_minutes`.

    Design: Corner/endpoints/the_cycle_summary_read_returns_both_variants_side_by_side_without_mutating_anything
    """
    attorney, cycle, _verified_record, pending_record = (
        _setup_one_verified_and_one_pending_record()
    )
    cycle_before = fx.read_cycle(cycle["id"])
    record_before = fx.read_credit_record(pending_record["id"])
    assert record_before["credited_minutes"] == 600
    assert record_before["countable_minutes"] == 360

    first = validate_success(
        api.get_cycle_summary(cycle["id"], make_attorney_headers(attorney["id"])),
        expected_status=200,
    )
    second = validate_success(
        api.get_cycle_summary(cycle["id"], BOARD), expected_status=200
    )
    assert first == second, "two summary reads over the same data must agree"

    cycle_after = fx.read_cycle(cycle["id"])
    record_after = fx.read_credit_record(pending_record["id"])
    assert cycle_after == cycle_before, (
        "the summary read must leave the cycle exactly as it found it"
    )
    assert record_after == record_before, (
        "the summary read must leave the record exactly as it found it"
    )
    assert cycle_after["earned_countable_minutes"] == 660
    assert cycle_after["earned_live_minutes"] == 300
    assert record_after["countable_minutes"] == 360


# --- sponsor-filed session rosters ----------------------------------------

def _setup_roster_scenario():
    """A ROSTER-committed live course of an accredited sponsor, one attorney
    holding a period that covers the session and one holding none."""
    provider = fx.create_accredited_provider(
        name="Lakeside Trial Academy", provider_type="LAW_SCHOOL"
    )
    course = fx.create_self_certified_course(
        provider,
        title="Trial Advocacy Workshop",
        delivery_format="LIVE_IN_PERSON",
        total_minutes=120,
        presented_at="2026-07-15T09:00:00Z",
        attendance_verification_method="ROSTER",
        credit_allocations=[fac.credit_allocation_entry("GENERAL", 120)],
    )
    attending = fx.create_attorney(
        bar_number="E2-1001",
        full_name="Grace Odunlami",
        admission_date="2010-10-10T00:00:00Z",
        compliance_group="GROUP_1",
    )
    uncovered = fx.create_attorney(
        bar_number="E2-1002",
        full_name="Hugo Petersen",
        admission_date="2010-11-11T00:00:00Z",
        compliance_group="GROUP_1",
    )
    cycle = fx.create_cycle(
        attending["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z"
    )
    entries = [
        fac.roster_entry("E2-1001", 120),
        fac.roster_entry("E2-9999", 120),
        fac.roster_entry("E2-1002", 120),
        fac.roster_entry("E2-1001", 60),
    ]
    payload = fac.create_attendance_report_payload(
        course["id"], "2026-07-15T09:00:00Z", entries
    )
    response = api_client.create_attendance_report(
        payload, make_provider_admin_headers(provider["id"])
    )
    return provider, course, attending, uncovered, cycle, response


def test_roster_with_three_unusable_rows_is_accepted_and_tallies_the_skips(api):
    """Individual entries may fail without failing the request: an entry is skipped when its `bar_number` matches no attorney on the register, when that attorney has no compliance cycle whose half-open window covers the roster's `session_date`, or when that attorney already holds a `PENDING_VERIFICATION` or `VERIFIED` record for that course.
    `accepted_entry_count` counts the entries that produced a record and `rejected_entry_count` counts the rest, and the two always sum to `entry_count`.
    A roster arriving at or before `due_at` has `days_late` of 0 and a `status` of `ACCEPTED`.
    Each accepted entry cascades a credit record that is born `VERIFIED`, with `verification_method` set to `ROSTER` and `attendance_report_id` pointing at the roster, which raises the course's `verified_credit_record_count` and triggers a credit-application re-run for that record's owning cycle.

    Design: Corner/endpoints/a_partly_unusable_roster_is_accepted_whole_and_reports_its_skipped_rows
    """
    _provider, _course, attending, uncovered, _cycle, response = _setup_roster_scenario()

    roster = validate_success(response, expected_status=201)
    assert roster["entry_count"] == 4
    assert roster["accepted_entry_count"] == 1
    assert roster["rejected_entry_count"] == 3
    assert roster["days_late"] == 0
    assert roster["status"] == "ACCEPTED", roster["status"]

    cascaded = fx.list_credit_records(attendance_report_id=roster["id"])
    assert len(cascaded) == 1, (
        f"only the first usable row may produce a record, got {len(cascaded)}"
    )
    record = cascaded[0]
    assert record["attorney_id"] == attending["id"]
    assert record["status"] == "VERIFIED", record["status"]
    assert record["verification_method"] == "ROSTER", record["verification_method"]
    assert record["attendance_report_id"] == roster["id"]
    # The repeated row's 60-minute figure was never applied.
    assert record["credited_general_minutes"] == 120
    assert record["credited_minutes"] == 120

    assert fx.list_credit_records(attorney_id=uncovered["id"]) == [], (
        "an attorney with no covering period must gain no record from the roster"
    )


def test_accepted_roster_credits_the_covering_cycle_and_raises_sponsor_counters(api):
    """Each accepted entry cascades a credit record that is born `VERIFIED`, with `verification_method` set to `ROSTER` and `attendance_report_id` pointing at the roster, which raises the course's `verified_credit_record_count` and triggers a credit-application re-run for that record's owning cycle.
    Every accepted roster, late or not, raises the sponsor's `attendance_reports_total_count` by one, and the sponsor's `risk_score` is recomputed afterwards.
    A roster arriving after `due_at` but at or before the hard close has `days_late` set to the number of days from `due_at` to now, rounded **up** so that any part of a day counts as a whole day, and a `status` of `ACCEPTED_LATE`; a late acceptance also raises the sponsor's `attendance_reports_late_count` by one, which feeds directly into its risk score.

    Design: Corner/endpoints/a_partly_unusable_roster_is_accepted_whole_and_reports_its_skipped_rows
    """
    provider, course, _attending, _uncovered, cycle, response = _setup_roster_scenario()
    validate_success(response, expected_status=201)

    cycle_after = fx.read_cycle(cycle["id"])
    assert cycle_after["earned_countable_minutes"] == 120
    assert cycle_after["earned_live_minutes"] == 120

    provider_after = fx.read_provider(provider["id"])
    assert provider_after["attendance_reports_total_count"] == 1
    assert provider_after["attendance_reports_late_count"] == 0

    course_after = fx.read_course(course["id"])
    assert course_after["verified_credit_record_count"] == 1


# --- the clock action endpoint ---------------------------------------------

def test_clock_moves_and_each_grant_stamps_its_term_from_where_the_clock_stands(api):
    """A `BoardAdmin` may move the clock to an arbitrary instant by supplying `to_iso8601`; the move mutates no business row, and it never retroactively re-evaluates deadlines by itself — the reporting sweep is what observes the clock and acts on what it finds.
    Creation endpoints — those that bring a new row into existence — return HTTP 201; every other successful call, including every action endpoint that transitions an existing row and every read, returns HTTP 200.
    It stamps the same two-year term into `accreditation_term_start` and `accreditation_term_end`, leaves `self_certification_enabled` false, raises the same `PROVIDER_ANNUAL` assessment for `annual_fee_cents`, and re-scores the sponsor under `REVIEWED_WEIGHTING`.
    The grant stamps `accreditation_term_start` with the current logical instant and `accreditation_term_end` with that instant plus 24 months, flips `self_certification_enabled` to true, raises a `PROVIDER_ANNUAL` assessment against the sponsor for exactly its `annual_fee_cents`, and re-scores it under the self-certified weighting, writing `risk_score_variant` as `SELF_CERTIFIED_WEIGHTING`.
    An `annual_fee_cents` figure may be supplied and must be zero or greater; when it is omitted the board's standard annual accreditation fee of 120000 cents — twelve hundred dollars — is used.

    Design: Corner/endpoints/the_clock_action_endpoint_moves_time_in_both_directions_and_returns_no_body
    """
    first_move = api.set_clock("2026-09-01T00:00:00Z", BOARD)
    validate_success(first_move, expected_status=200)

    probationary = fx.create_provider(
        name="Probation Term Seminars", provider_type="COMMERCIAL"
    )
    probationary = fx.accreditation_action(
        probationary["id"], "GRANT_PROBATIONARY", probationary["version"],
        probation_reason="Probationary term for a new commercial sponsor.",
    )

    second_move = api.set_clock("2027-01-01T00:00:00Z", BOARD)
    validate_success(second_move, expected_status=200)

    fully = fx.create_provider(
        name="Forward Time Institute", provider_type="GOVERNMENT"
    )
    fully = fx.accreditation_action(fully["id"], "GRANT_FULL", fully["version"])

    _same_instant(
        probationary["accreditation_term_start"], "2026-09-01T00:00:00Z",
        "the probationary term start",
    )
    _same_instant(
        probationary["accreditation_term_end"], "2028-09-01T00:00:00Z",
        "the probationary term end",
    )
    assert probationary["self_certification_enabled"] is False
    assert probationary["risk_score_variant"] == "REVIEWED_WEIGHTING"

    _same_instant(
        fully["accreditation_term_start"], "2027-01-01T00:00:00Z",
        "the full term start",
    )
    _same_instant(
        fully["accreditation_term_end"], "2029-01-01T00:00:00Z",
        "the full term end",
    )
    assert fully["self_certification_enabled"] is True
    assert fully["risk_score_variant"] == "SELF_CERTIFIED_WEIGHTING"

    probation_fees = fx.list_fee_assessments(provider_id=probationary["id"])
    assert len(probation_fees) == 1, probation_fees
    assert probation_fees[0]["fee_type"] == "PROVIDER_ANNUAL"
    assert probation_fees[0]["status"] == "ASSESSED"
    assert probation_fees[0]["amount_cents"] == 120000
    _same_instant(
        probation_fees[0]["assessed_at"], "2026-09-01T00:00:00Z",
        "the probationary sponsor's annual assessment instant",
    )

    full_fees = fx.list_fee_assessments(provider_id=fully["id"])
    assert len(full_fees) == 1, full_fees
    assert full_fees[0]["fee_type"] == "PROVIDER_ANNUAL"
    assert full_fees[0]["status"] == "ASSESSED"
    assert full_fees[0]["amount_cents"] == 120000
    _same_instant(
        full_fees[0]["assessed_at"], "2027-01-01T00:00:00Z",
        "the fully accredited sponsor's annual assessment instant",
    )


# --- one course endpoint, three approval outcomes --------------------------

def _register_three_courses():
    """The same course endpoint exercised by a fully accredited sponsor, by a
    probationary sponsor and by an attorney with no sponsor at all."""
    full = fx.create_accredited_provider(
        name="Fully Accredited Bar CLE", provider_type="BAR_ASSOCIATION"
    )
    probationary = fx.create_probationary_provider(
        name="Probationary Sponsor LLC", provider_type="LAW_FIRM",
    )
    attorney = fx.create_attorney(
        bar_number="E4-1001",
        full_name="Lena Fitzgerald",
        admission_date="2012-12-12T00:00:00Z",
        compliance_group="GROUP_2",
    )
    self_certified = api_client.create_course(
        fac.create_course_payload(
            title="Self Certified Ethics Hour",
            delivery_format="LIVE_WEBCAST",
            total_minutes=60,
            presented_at="2026-09-01T09:00:00Z",
            attendance_verification_method="ATTENDANCE_CODE",
            credit_allocations=[fac.credit_allocation_entry("ETHICS", 60)],
            provider_id=full["id"],
        ),
        make_provider_admin_headers(full["id"]),
    )
    sponsored = api_client.create_course(
        fac.create_course_payload(
            title="Probationary Sponsor Seminar",
            delivery_format="LIVE_IN_PERSON",
            total_minutes=120,
            presented_at="2026-09-02T09:00:00Z",
            attendance_verification_method="ROSTER",
            credit_allocations=[fac.credit_allocation_entry("GENERAL", 120)],
            provider_id=probationary["id"],
        ),
        make_provider_admin_headers(probationary["id"]),
    )
    unsponsored_payload = fac.create_course_payload(
        title="Out of State Bar Retreat Session",
        delivery_format="ON_DEMAND",
        total_minutes=90,
        presented_at="2026-05-05T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[fac.credit_allocation_entry("GENERAL", 90)],
    )
    unsponsored_payload.pop("provider_id", None)
    unsponsored = api_client.create_course(
        unsponsored_payload, make_attorney_headers(attorney["id"])
    )
    return full, probationary, attorney, self_certified, sponsored, unsponsored


def test_course_registration_decides_the_pathway_from_the_sponsor(api):
    """It is `PROVIDER_ACCREDITED` when `provider_id` is supplied *and* that sponsor's `self_certification_enabled` is true at the moment of creation; in every other case — no sponsor at all, or a sponsor that is not fully accredited — it is `INDIVIDUAL_APPROVAL`.
    A course on the self-certification pathway is presumptively approved: it is created and immediately transitions `PENDING_APPROVAL → APPROVED` in the same request, its sponsor's `courses_self_certified_count` and `courses_total_count` each rise by one, and the sponsor's `risk_score` is recomputed because the denominator behind its findings rate has changed.
    Every other course is created in `PENDING_APPROVAL` and stays there until an application is decided; if it names a sponsor, only that sponsor's `courses_total_count` rises.
    Where and only where the sponsor commits to `ATTENDANCE_CODE`, the system mints a six-character `attendance_code` at creation; for the other three methods `attendance_code` is null.
    An `Attorney` registering a course must omit `provider_id` entirely, which is how an attorney seeks individual approval of instruction that has no sponsoring provider in this state.

    Design: Corner/endpoints/one_course_endpoint_produces_three_different_approval_outcomes
    """
    full, probationary, _attorney, self_certified, sponsored, unsponsored = (
        _register_three_courses()
    )

    course_self = validate_success(self_certified, expected_status=201)
    course_prob = validate_success(sponsored, expected_status=201)
    course_indiv = validate_success(unsponsored, expected_status=201)

    assert course_self["status"] == "APPROVED", course_self["status"]
    assert course_self["approval_pathway"] == "PROVIDER_ACCREDITED"
    assert len(course_self["attendance_code"]) == 6, course_self["attendance_code"]

    assert course_prob["status"] == "PENDING_APPROVAL", course_prob["status"]
    assert course_prob["approval_pathway"] == "INDIVIDUAL_APPROVAL"
    assert course_prob["attendance_code"] is None, course_prob["attendance_code"]

    assert course_indiv["status"] == "PENDING_APPROVAL", course_indiv["status"]
    assert course_indiv["approval_pathway"] == "INDIVIDUAL_APPROVAL"
    assert course_indiv["provider_id"] is None, course_indiv["provider_id"]
    assert course_indiv["attendance_code"] is None, course_indiv["attendance_code"]

    full_after = fx.read_provider(full["id"])
    assert full_after["courses_total_count"] == 1
    assert full_after["courses_self_certified_count"] == 1
    prob_after = fx.read_provider(probationary["id"])
    assert prob_after["courses_total_count"] == 1
    assert prob_after["courses_self_certified_count"] == 0


def test_course_approval_window_depends_on_the_delivery_format(api):
    """For `LIVE_IN_PERSON` and `LIVE_WEBCAST` it is `presented_at` plus the course's own `total_minutes` — a live session's approval covers the session and nothing more. For `ON_DEMAND` and `SELF_STUDY` it is `presented_at` plus 36 months, three years of shelf life for recorded material.

    Design: Corner/endpoints/one_course_endpoint_produces_three_different_approval_outcomes
    """
    _full, _prob, _attorney, self_certified, sponsored, unsponsored = (
        _register_three_courses()
    )
    course_self = validate_success(self_certified, expected_status=201)
    course_prob = validate_success(sponsored, expected_status=201)
    course_indiv = validate_success(unsponsored, expected_status=201)

    _same_instant(
        course_self["expires_at"], "2026-09-01T10:00:00Z",
        "a 60-minute webcast's approval window",
    )
    _same_instant(
        course_prob["expires_at"], "2026-09-02T11:00:00Z",
        "a 120-minute live session's approval window",
    )
    _same_instant(
        course_indiv["expires_at"], "2029-05-05T09:00:00Z",
        "an on-demand course's approval window",
    )


def test_course_list_filters_reach_each_pathway_and_each_sponsor(api):
    """The course list accepts `provider_id`, `status`, `delivery_format` and `approval_pathway` filters and is the reverse-reachability channel for a course's sponsoring provider.
    Filters combine conjunctively: supplying two filters returns only rows matching both.

    Design: Corner/endpoints/one_course_endpoint_produces_three_different_approval_outcomes
    """
    full, _prob, _attorney, self_certified, sponsored, unsponsored = (
        _register_three_courses()
    )
    course_self = validate_success(self_certified, expected_status=201)
    course_prob = validate_success(sponsored, expected_status=201)
    course_indiv = validate_success(unsponsored, expected_status=201)

    individual = fx.list_courses(approval_pathway="INDIVIDUAL_APPROVAL")
    assert {row["id"] for row in individual} == {course_prob["id"], course_indiv["id"]}

    approved = fx.list_courses(status="APPROVED")
    assert {row["id"] for row in approved} == {course_self["id"]}

    sponsored_by_full = fx.list_courses(provider_id=full["id"])
    assert {row["id"] for row in sponsored_by_full} == {course_self["id"]}

    both = fx.list_courses(
        provider_id=full["id"], approval_pathway="INDIVIDUAL_APPROVAL"
    )
    assert both == [], (
        "the fully accredited sponsor has no individually approved course, "
        f"got {both}"
    )


# --- out-of-state claims and their cascades --------------------------------

def _setup_two_claimants():
    """Two attorneys with the same period; the first files a New York claim
    and a California claim, the second files none."""
    claimant = fx.create_attorney(
        bar_number="E5-1001",
        full_name="Amara Nwosu",
        admission_date="2004-04-04T00:00:00Z",
        compliance_group="GROUP_1",
    )
    bystander = fx.create_attorney(
        bar_number="E5-1002",
        full_name="Bruno Salgado",
        admission_date="2004-05-05T00:00:00Z",
        compliance_group="GROUP_1",
    )
    claimant_cycle = fx.create_cycle(
        claimant["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z"
    )
    bystander_cycle = fx.create_cycle(
        bystander["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z"
    )
    first_claim = fx.file_reciprocity_claim(
        claimant["id"],
        basis="RECIPROCITY",
        origin_jurisdiction="NY",
        origin_course_title="New York Civil Practice Update",
        origin_credit_hours=2.0,
        origin_category="GENERAL",
        completion_date="2026-05-05T00:00:00Z",
    )
    second_claim = fx.file_reciprocity_claim(
        claimant["id"],
        basis="RECIPROCITY",
        origin_jurisdiction="CA",
        origin_course_title="California Legal Technology Forum",
        origin_credit_hours=1.5,
        origin_category="TECHNOLOGY",
        completion_date="2026-06-06T00:00:00Z",
    )
    return (claimant, bystander, claimant_cycle, bystander_cycle,
            first_claim, second_claim)


def test_approved_reciprocity_claim_converts_minutes_and_cascades_a_findable_record(api):
    """The origin minutes are `origin_credit_hours` multiplied by the origin jurisdiction's hour length, and `converted_minutes` is that product rounded **down** to a whole multiple of 15 minutes. Two New York credit hours therefore convert as follows: two hours at 50 minutes each is 100 minutes, and 100 minutes floored to a 15-minute multiple is 90 minutes.
    That record is created already `VERIFIED`, naming the claiming attorney and the covering cycle and carrying no `course_id`, with `source` set to `RECIPROCITY`, `reciprocity_claim_id` pointing back at the claim, `verification_method` recorded as `CERTIFICATE`, and `effective_format` of `LIVE`.
    Its credited minutes for the mapped category equal `converted_minutes`, and its `credited_minutes` equals `converted_minutes` as well, the other three category figures being zero.
    The credit-record list accepts `attorney_id`, `cycle_id`, `course_id`, `attendance_report_id`, `reciprocity_claim_id`, `affirmation_id` and `status`, covering all six of a record's references.

    Design: Corner/endpoints/an_attorneys_reciprocity_claims_and_their_cascaded_records_are_reachable_both_ways
    """
    (claimant, _bystander, claimant_cycle, bystander_cycle,
     first_claim, second_claim) = _setup_two_claimants()

    decided = validate_success(
        api.reciprocity_claim_determination(
            first_claim["id"], fac.determination_payload("APPROVE"), BOARD
        ),
        expected_status=200,
    )
    assert decided["status"] == "APPROVED", decided["status"]
    assert decided["converted_minutes"] == 90
    assert decided["converted_category"] == "GENERAL"

    cascaded = fx.list_credit_records(reciprocity_claim_id=first_claim["id"])
    assert len(cascaded) == 1, f"an approved claim cascades one record, got {cascaded}"
    record = cascaded[0]
    assert record["attorney_id"] == claimant["id"]
    assert record["cycle_id"] == claimant_cycle["id"]
    assert record["course_id"] is None, record["course_id"]
    assert record["status"] == "VERIFIED", record["status"]
    assert record["source"] == "RECIPROCITY", record["source"]
    assert record["verification_method"] == "CERTIFICATE"
    assert record["effective_format"] == "LIVE", record["effective_format"]
    assert record["credited_general_minutes"] == 90
    assert record["credited_minutes"] == 90
    assert record["credited_ethics_minutes"] == 0
    assert record["credited_technology_minutes"] == 0
    assert record["credited_bias_minutes"] == 0

    assert fx.list_credit_records(reciprocity_claim_id=second_claim["id"]) == [], (
        "a claim still in SUBMITTED has cascaded nothing"
    )

    assert fx.read_cycle(claimant_cycle["id"])["earned_countable_minutes"] == 90
    assert fx.read_cycle(claimant_cycle["id"])["earned_live_minutes"] == 90
    assert fx.read_cycle(bystander_cycle["id"])["earned_countable_minutes"] == 0


def test_attorney_reciprocity_claims_sub_collection_is_scoped_to_its_parent(api):
    """A nested collection also enforces containment: a sub-collection returns only rows belonging to the addressed parent, never a global list filtered client-side.
    Every nested sub-collection — a course's credit allocations, a course's attendance reports, a course's applications, an attorney's reciprocity claims, a cycle's affirmations — is ordered by `created_at` ascending.

    Design: Corner/endpoints/an_attorneys_reciprocity_claims_and_their_cascaded_records_are_reachable_both_ways
    """
    (claimant, bystander, _claimant_cycle, _bystander_cycle,
     first_claim, second_claim) = _setup_two_claimants()
    fx.determine_claim(first_claim["id"], "APPROVE")

    owned = validate_success(
        api.list_attorney_reciprocity_claims(
            claimant["id"], make_attorney_headers(claimant["id"])
        ),
        expected_status=200,
    )
    assert [row["id"] for row in owned] == [first_claim["id"], second_claim["id"]], (
        f"the claimant's own two claims, oldest first, got {owned}"
    )
    assert owned[0]["status"] == "APPROVED", owned[0]["status"]
    assert owned[1]["status"] == "SUBMITTED", owned[1]["status"]

    empty = validate_success(
        api.list_attorney_reciprocity_claims(bystander["id"], BOARD),
        expected_status=200,
    )
    assert empty == [], (
        f"an attorney who filed no claim must see an empty sub-collection, got {empty}"
    )


# --- declared status codes and envelope shapes ----------------------------

def _register_attorney_with_three_periods():
    """One attorney and three adjacent historical periods, created through the
    declared endpoints so every envelope can be inspected."""
    attorney_response = api_client.create_attorney(
        fac.create_attorney_payload(
            bar_number="E6-1001",
            full_name="Rafael Quintero",
            admission_date="2001-01-01T00:00:00Z",
            compliance_group="GROUP_3",
        ),
        BOARD,
    )
    attorney = validate_success(attorney_response, expected_status=201)
    windows = [
        ("2020-01-01T00:00:00Z", "2022-01-01T00:00:00Z"),
        ("2022-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
        ("2024-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    ]
    cycle_responses = [
        api_client.create_compliance_cycle(
            attorney["id"],
            fac.create_compliance_cycle_payload(period_start=start, period_end=end),
            BOARD,
        )
        for start, end in windows
    ]
    return attorney_response, attorney, cycle_responses


def test_creates_answer_201_and_actions_answer_200_in_the_standard_envelope(api):
    """Creation endpoints — those that bring a new row into existence — return HTTP 201; every other successful call, including every action endpoint that transitions an existing row and every read, returns HTTP 200.
    The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
    Every persisted resource carries a server-minted `id` that is a UUID string with no type prefix, and a `created_at` timestamp recorded at insertion. Most resources also carry an `updated_at` timestamp, refreshed on every mutation of that row, and an integer `version` that starts at 1 on creation and increases by exactly 1 on every mutation of that row — including mutations the row did not ask for, such as a counter bump driven by a cascade from another entity.
    Board staff may move an attorney between `ACTIVE`, `EXEMPT` and `INACTIVE` by supplying the target `status` and an optional `reason`; this is the only actor-driven writer of that field.
    A standing change leaves every one of that attorney's compliance cycles exactly as it found them: neither `credit_status` nor `administrative_status` moves, and the attorney's own `version` rises by one.

    Design: Corner/endpoints/every_declared_status_code_and_envelope_shape_matches_the_endpoint_table
    """
    attorney_response, attorney, cycle_responses = _register_attorney_with_three_periods()

    for response in [attorney_response] + cycle_responses:
        created = validate_success(response, expected_status=201)
        body = response.json()
        assert body["response_type"] == "object", body["response_type"]
        assert body["meta"]["api_request_id"].startswith("req_"), body["meta"]
        assert created["version"] == 1, created["version"]
        assert len(created["id"]) == 36, created["id"]
        assert ":" not in created["id"] and "_" not in created["id"], created["id"]
        assert created["created_at"] and created["updated_at"]

    read = api.get_attorney(attorney["id"], make_attorney_headers(attorney["id"]))
    read_data = validate_success(read, expected_status=200)
    assert read.json()["response_type"] == "object"
    assert read_data["id"] == attorney["id"]

    changed = api.attorney_status_change(
        attorney["id"],
        fac.status_change_payload("EXEMPT", reason="Full-time judicial appointment."),
        BOARD,
    )
    changed_data = validate_success(changed, expected_status=200)
    assert changed_data["status"] == "EXEMPT", changed_data["status"]
    assert changed_data["version"] == 2, changed_data["version"]


def test_list_pagination_meta_follows_the_declared_bounds(api):
    """`limit` controls page size: it defaults to 10, may not be smaller than 1, and may not be larger than 100. `offset` controls the starting position: it defaults to 0 and may not be negative. A supplied value outside those bounds is a malformed request rather than a silently clamped one, and is rejected with `ERR_INVALID_REQUEST`.
    For every list response, the `meta` object carries `limit`, `offset`, `total_count` and `has_more`. `total_count` is the number of rows matching the filters before pagination is applied, and `has_more` is true exactly when rows remain beyond the returned page.
    Four collections declare otherwise because their natural reading order is not their insertion order: the course list is returned newest first, ordered by `created_at` descending; the compliance-cycle list is ordered by `period_start` ascending and then `created_at` ascending; the credit-record list is ordered by `completion_date` ascending and then `created_at` ascending, which is exactly the order the credit-application algorithm consumes records in; and the provider-audit list is ordered by `audit_period_start` ascending and then `created_at` ascending.

    Design: Corner/endpoints/every_declared_status_code_and_envelope_shape_matches_the_endpoint_table
    """
    _attorney_response, attorney, cycle_responses = (
        _register_attorney_with_three_periods()
    )
    cycles = [validate_success(item, expected_status=201) for item in cycle_responses]

    first_page = api.list_compliance_cycles(
        BOARD, params={"attorney_id": attorney["id"], "limit": 2, "offset": 0}
    )
    rows, meta = validate_paginated(first_page)
    assert first_page.json()["response_type"] == "array"
    assert len(rows) == 2, rows
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert [row["id"] for row in rows] == [cycles[0]["id"], cycles[1]["id"]], (
        "the compliance-cycle list runs from the earliest period onward"
    )

    second_page = api.list_compliance_cycles(
        BOARD, params={"attorney_id": attorney["id"], "limit": 2, "offset": 2}
    )
    rows, meta = validate_paginated(second_page)
    assert [row["id"] for row in rows] == [cycles[2]["id"]], rows
    assert meta["total_count"] == 3
    assert meta["offset"] == 2
    assert meta["has_more"] is False

    defaults = api.list_compliance_cycles(BOARD, params={"attorney_id": attorney["id"]})
    rows, meta = validate_paginated(defaults)
    assert len(rows) == 3, rows
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False

    over_ceiling = api.list_compliance_cycles(
        BOARD, params={"attorney_id": attorney["id"], "limit": 101}
    )
    validate_error(over_ceiling, "ERR_INVALID_REQUEST", expected_status=422)


def test_a_missing_path_identifier_answers_the_error_envelope(api):
    """**Path resource existence**, validated left to right along the path template: a provider identifier that resolves to nothing yields `ERR_PROVIDER_NOT_FOUND`, a course `ERR_COURSE_NOT_FOUND`, a course application `ERR_APPLICATION_NOT_FOUND`, an attorney `ERR_ATTORNEY_NOT_FOUND`, a compliance cycle `ERR_CYCLE_NOT_FOUND`, a credit record `ERR_CREDIT_RECORD_NOT_FOUND`, a reciprocity claim `ERR_RECIPROCITY_CLAIM_NOT_FOUND`, an audit `ERR_AUDIT_NOT_FOUND`, a complaint `ERR_COMPLAINT_NOT_FOUND`, a fee assessment `ERR_FEE_ASSESSMENT_NOT_FOUND` — all HTTP 404.
    The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
    The `error_id` is a unique, machine-readable string that identifies the specific error.

    Design: Corner/endpoints/every_declared_status_code_and_envelope_shape_matches_the_endpoint_table
    """
    _register_attorney_with_three_periods()

    response = api.get_attorney(MISSING_ATTORNEY_ID, BOARD)
    error_data = validate_error(response, "ERR_ATTORNEY_NOT_FOUND", expected_status=404)
    body = response.json()
    assert body["response_type"] == "error", body["response_type"]
    assert set(error_data.keys()) == {"error_id", "message"}, (
        f"the error payload carries only error_id and message, got {sorted(error_data)}"
    )
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"an error meta carries only the two request fields, got {sorted(body['meta'])}"
    )

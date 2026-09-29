"""Appeals, audit engagements, comity closures and the batch run's cascades.

Every test builds its own state from an empty register: the database is wiped
and the server restarted before each one, and the logical clock reads
2026-08-01T00:00:00Z at the start of every test (PRD 2.4).
"""
import datetime

from test_helpers import (
    api_client,
    fixtures,
    make_provider_admin_headers,
    validate_error,
    validate_paginated,
)

CLOCK_START = "2026-08-01T00:00:00Z"

# Opaque operator identities. The reviewer and the panelist must differ so the
# segregation-of-duties rule of PRD 3.3 is satisfied, and the complainant must
# differ from the disposer for the same reason in PRD 3.9.
REVIEWER_R1 = "33333333-3333-4333-8333-333333333333"
PANELIST_P1 = "44444444-4444-4444-8444-444444444444"
COMPLAINANT_ID = "11111111-1111-4111-8111-111111111111"
DISPOSER_ID = "22222222-2222-4222-8222-222222222222"


def parse_instant(value):
    """Reads one of the API's UTC timestamps as a comparable instant."""
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_same_instant(actual, expected, label="timestamp"):
    """Compares two timestamps as instants, so fractional-second rendering is
    not mistaken for a different moment in time."""
    assert actual is not None, f"{label} must be stamped, got null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label} must be {expected}, got {actual}"
    )


def board_fee_page(**params):
    """Board-side read of the fee ledger, returning (rows, meta)."""
    return validate_paginated(
        api_client.list_fee_assessments(fixtures.BOARD, params=params)
    )


def board_credit_record_page(**params):
    """Board-side read of the credit-record collection, returning (rows, meta)."""
    return validate_paginated(
        api_client.list_credit_records(fixtures.BOARD, params=params)
    )


def build_denied_application(sponsor_name, title, category, denial_reason):
    """A probationary sponsor's course, filed for individual approval and then
    denied by reviewer R1. Returns (provider, course, application)."""
    provider = fixtures.create_probationary_provider(
        name=sponsor_name, provider_type="COMMERCIAL"
    )
    course = fixtures.create_self_certified_course(
        provider,
        title=title,
        delivery_format="LIVE_WEBCAST",
        total_minutes=120,
        presented_at="2026-06-06T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[{"category": category, "minutes": 120}],
    )
    application = fixtures.submit_application(
        course["id"], make_provider_admin_headers(provider["id"])
    )
    application = fixtures.review_action(
        application["id"], "DENY", REVIEWER_R1, denial_reason=denial_reason
    )
    return provider, course, application


def build_sponsor_under_substantiated_complaint():
    """An accredited sponsor with one course inside the 2025 first-half window,
    driven to probation by a substantiated complaint that has not yet seeded an
    audit. Returns (provider, course, complaint)."""
    provider = fixtures.create_accredited_provider(
        name="Ledger Bar Institute", provider_type="BAR_ASSOCIATION"
    )
    course = fixtures.create_self_certified_course(
        provider,
        title="Sign In Procedures Seminar",
        delivery_format="LIVE_WEBCAST",
        total_minutes=120,
        presented_at="2025-03-03T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[{"category": "GENERAL", "minutes": 120}],
    )
    complaint = fixtures.file_complaint(
        "PROVIDER",
        provider["id"],
        COMPLAINANT_ID,
        allegation="Attendance sheets were completed for absent registrants.",
        allegation_category="ATTENDANCE_FRAUD",
    )
    fixtures.dispose_complaint(complaint["id"], "OPEN_REVIEW", DISPOSER_ID)
    fixtures.dispose_complaint(
        complaint["id"],
        "SUBSTANTIATE",
        DISPOSER_ID,
        disposition_reason="Two registrants confirmed they never attended.",
    )
    return provider, course, complaint


def build_single_course_audit_at_findings_issued():
    """An accredited law school with one course in the audit window, walked to
    FINDINGS_ISSUED with one finding. Returns (provider, course, audit)."""
    provider = fixtures.create_accredited_provider(
        name="Northline Law School CLE", provider_type="LAW_SCHOOL"
    )
    course = fixtures.create_self_certified_course(
        provider,
        title="Fiduciary Duties Update",
        delivery_format="LIVE_WEBCAST",
        total_minutes=120,
        presented_at="2025-04-04T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[{"category": "GENERAL", "minutes": 120}],
    )
    audit = fixtures.open_audit(
        provider["id"],
        audit_period_start="2025-01-01T00:00:00Z",
        audit_period_end="2025-06-30T00:00:00Z",
        trigger_type="RISK_BASED",
    )
    sampled = fixtures.audit_action(audit["id"], "DRAW_SAMPLE", audit["version"])
    issued = fixtures.audit_action(
        audit["id"], "ISSUE_FINDINGS", sampled["version"], findings_count=1
    )
    return provider, course, issued


def build_two_course_audit_at_findings_issued():
    """An accredited government sponsor with two courses in the audit window,
    walked to FINDINGS_ISSUED with two findings. Returns (provider, first
    course, second course, audit)."""
    provider = fixtures.create_accredited_provider(
        name="State Judicial Education Office", provider_type="GOVERNMENT"
    )
    first = fixtures.create_self_certified_course(
        provider,
        title="Judicial Ethics March",
        delivery_format="LIVE_WEBCAST",
        total_minutes=120,
        presented_at="2026-03-03T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[{"category": "GENERAL", "minutes": 120}],
    )
    second = fixtures.create_self_certified_course(
        provider,
        title="Judicial Ethics April",
        delivery_format="LIVE_WEBCAST",
        total_minutes=120,
        presented_at="2026-04-04T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[{"category": "GENERAL", "minutes": 120}],
    )
    audit = fixtures.open_audit(
        provider["id"],
        audit_period_start="2026-01-01T00:00:00Z",
        audit_period_end="2026-06-30T00:00:00Z",
        trigger_type="RANDOM",
    )
    sampled = fixtures.audit_action(audit["id"], "DRAW_SAMPLE", audit["version"])
    issued = fixtures.audit_action(
        audit["id"], "ISSUE_FINDINGS", sampled["version"], findings_count=2
    )
    return provider, first, second, issued


def build_comity_claim_setup(sponsor_name, course_title, total_minutes,
                             allocations, jurisdiction, bar_number, full_name,
                             origin_title, completion_date):
    """An attorney whose principal office sits in a comity jurisdiction, with an
    open 2026-2028 period, one verified live-webcast record and one SUBMITTED
    comity claim. Returns (provider, course, attorney, cycle, record, claim)."""
    provider = fixtures.create_accredited_provider(
        name=sponsor_name, provider_type="BAR_ASSOCIATION"
    )
    course = fixtures.create_self_certified_course(
        provider,
        title=course_title,
        delivery_format="LIVE_WEBCAST",
        total_minutes=total_minutes,
        presented_at="2026-03-03T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=allocations,
    )
    attorney, cycle = fixtures.setup_attorney_with_cycle(
        period_start="2026-01-01T00:00:00Z",
        period_end="2028-01-01T00:00:00Z",
        attorney_overrides={
            "bar_number": bar_number,
            "full_name": full_name,
            "admission_date": "2004-01-01T00:00:00Z",
            "compliance_group": "GROUP_1",
            "principal_office_jurisdiction": jurisdiction,
        },
    )
    record = fixtures.file_code_verified_record(
        attorney, course,
        attended_minutes=total_minutes,
        completion_date=completion_date,
    )
    claim = fixtures.file_reciprocity_claim(
        attorney["id"],
        basis="COMITY",
        origin_jurisdiction=jurisdiction,
        origin_course_title=origin_title,
        origin_credit_hours=1.0,
        origin_category="GENERAL",
        completion_date="2026-04-04T00:00:00Z",
    )
    return provider, course, attorney, cycle, record, claim


def build_delinquent_attorney_with_pending_claim():
    """An attorney whose 2024-2026 period earned nothing and whose filing
    deadline has passed, plus one SUBMITTED reciprocity claim, taken through the
    first batch run. Returns (attorney, cycle, claim, sweep)."""
    attorney, cycle = fixtures.setup_attorney_with_cycle(
        period_start="2024-01-01T00:00:00Z",
        period_end="2026-01-01T00:00:00Z",
        attorney_overrides={
            "bar_number": "BAR-2040",
            "full_name": "Yusuf Adeyemi",
            "admission_date": "2004-01-01T00:00:00Z",
            "compliance_group": "GROUP_1",
            "principal_office_jurisdiction": "ST",
        },
    )
    claim = fixtures.file_reciprocity_claim(
        attorney["id"],
        basis="RECIPROCITY",
        origin_jurisdiction="CA",
        origin_course_title="California trial advocacy",
        origin_credit_hours=2.0,
        origin_category="GENERAL",
        completion_date="2025-05-05T00:00:00Z",
    )
    sweep = fixtures.run_sweep()
    return attorney, cycle, claim, sweep


def test_denial_cascades_the_reason_into_the_course_and_stamps_the_reviewer():
    """Denial moves the application to `DENIED` from either `SUBMITTED` or `INFO_REQUESTED`.
    The reason is recorded on the application, `denied_at` is stamped with the current logical instant, and the course cascades `PENDING_APPROVAL → DENIED` carrying the identical reason text into its own `denial_reason`.
    Whichever move is made, the acting `X-User-ID` is stamped into `reviewer_user_id`, which is precisely what disqualifies that operator from later deciding the appeal.
    The new application starts in `SUBMITTED` with `info_request_round`, `supplement_count` and `remand_count` all at zero and `reviewer_user_id`, `denial_reason`, `appeal_grounds`, `appeal_panelist_user_id`, `appeal_filed_at`, `denied_at` and `decided_at` all null.

    Design: Corner/state_machines/a_granted_appeal_flips_the_denied_course_back_to_approved_and_clears_its_denial_reason
    """
    reason = "Agenda shows no substantive technology content."
    provider, course, application = build_denied_application(
        "Second Chance CLE", "Legal Technology Bootcamp", "TECHNOLOGY", reason
    )

    assert application["status"] == "DENIED"
    assert application["denial_reason"] == reason
    assert application["reviewer_user_id"] == REVIEWER_R1
    assert_same_instant(application["denied_at"], CLOCK_START, "denied_at")
    assert application["appeal_filed_at"] is None
    assert application["appeal_panelist_user_id"] is None
    assert application["remand_count"] == 0

    denied_course = fixtures.read_course(course["id"])
    assert denied_course["status"] == "DENIED"
    assert denied_course["denial_reason"] == reason


def test_a_granted_appeal_flips_the_denied_course_back_to_approved_and_clears_the_reason():
    """An accepted appeal records the grounds and stamps `appeal_filed_at`.
    All three dispositions record the acting identifier in `appeal_panelist_user_id`.
    `GRANT` moves the application `APPEALED → APPEAL_GRANTED`, stamps `decided_at`, clears the application's `denial_reason` to null, and cascades the course `DENIED → APPROVED` while clearing the course's own `denial_reason` to null.
    `approval_pathway` is derived at creation and never revisited.
    Every other course is created in `PENDING_APPROVAL` and stays there until an application is decided; if it names a sponsor, only that sponsor's `courses_total_count` rises.

    Design: Corner/state_machines/a_granted_appeal_flips_the_denied_course_back_to_approved_and_clears_its_denial_reason
    """
    grounds = "The revised agenda documents 120 minutes of practice-management technology."
    provider, course, application = build_denied_application(
        "Second Chance CLE",
        "Legal Technology Bootcamp",
        "TECHNOLOGY",
        "Agenda shows no substantive technology content.",
    )

    appealed = fixtures.appellant_action(
        application["id"], "APPEAL",
        make_provider_admin_headers(provider["id"]),
        appeal_grounds=grounds,
    )
    assert appealed["status"] == "APPEALED"
    assert appealed["appeal_grounds"] == grounds
    assert_same_instant(appealed["appeal_filed_at"], CLOCK_START, "appeal_filed_at")

    granted = fixtures.grant_appeal(
        application["id"], PANELIST_P1,
        decision_reason="Revised agenda satisfies the technology definition.",
    )
    assert granted["status"] == "APPEAL_GRANTED"
    assert granted["appeal_panelist_user_id"] == PANELIST_P1
    assert_same_instant(granted["decided_at"], CLOCK_START, "decided_at")
    assert granted["denial_reason"] is None
    assert granted["remand_count"] == 0

    restored = fixtures.read_course(course["id"])
    assert restored["status"] == "APPROVED"
    assert restored["denial_reason"] is None
    assert restored["approval_pathway"] == "INDIVIDUAL_APPROVAL"

    sponsor = fixtures.read_provider(provider["id"])
    assert sponsor["courses_total_count"] == 1
    assert sponsor["courses_self_certified_count"] == 0


def test_an_appeal_after_the_window_closes_is_refused_while_one_inside_it_is_heard():
    """Appealing contests a denial and moves the application `DENIED → APPEALED`.
    It requires `appeal_grounds` text, and it must arrive strictly before 30 days have elapsed since `denied_at` as measured on the logical clock — at or after that instant the appeal is `ERR_APPEAL_WINDOW_EXPIRED`.
    An accepted appeal records the grounds and stamps `appeal_filed_at`.
    The reason is recorded on the application, `denied_at` is stamped with the current logical instant, and the course cascades `PENDING_APPROVAL → DENIED` carrying the identical reason text into its own `denial_reason`.

    Design: Corner/state_machines/an_appeal_at_exactly_thirty_days_is_refused_while_one_second_earlier_is_heard
    """
    grounds = "Credentials were attached to the original filing."
    denial_reason = "Faculty credentials were not documented."
    early_provider, early_course, early_app = build_denied_application(
        "Deadline CLE Works", "Wellness And Bias Awareness",
        "BIAS_ELIMINATION", denial_reason,
    )
    late_provider, late_course, late_app = build_denied_application(
        "Deadline CLE Annex", "Wellness And Bias Awareness Encore",
        "BIAS_ELIMINATION", denial_reason,
    )

    fixtures.set_clock("2026-08-30T23:59:59Z")
    heard = fixtures.appellant_action(
        early_app["id"], "APPEAL",
        make_provider_admin_headers(early_provider["id"]),
        appeal_grounds=grounds,
    )
    assert heard["status"] == "APPEALED"
    assert heard["appeal_grounds"] == grounds
    assert_same_instant(
        heard["appeal_filed_at"], "2026-08-30T23:59:59Z", "appeal_filed_at"
    )
    assert_same_instant(heard["denied_at"], CLOCK_START, "denied_at")

    fixtures.set_clock("2026-08-31T00:00:01Z")
    refused = api_client.application_appellant_action(
        late_app["id"],
        {"action": "APPEAL", "appeal_grounds": grounds},
        make_provider_admin_headers(late_provider["id"]),
    )
    validate_error(refused, "ERR_APPEAL_WINDOW_EXPIRED")

    unmoved = fixtures.read_application(late_app["id"])
    assert unmoved["status"] == "DENIED"
    assert unmoved["appeal_filed_at"] is None
    assert_same_instant(unmoved["denied_at"], CLOCK_START, "denied_at")
    assert fixtures.read_course(late_course["id"])["status"] == "DENIED"


def test_a_status_change_naming_admin_suspended_is_refused_while_the_other_moves_land():
    """Board staff may move an attorney between `ACTIVE`, `EXEMPT` and `INACTIVE` by supplying the target `status` and an optional `reason`; this is the only actor-driven writer of that field.
    `ADMIN_SUSPENDED` is deliberately unreachable this way — it is written only by the board's batch run and cleared only by reinstatement — so a standing change that names `ADMIN_SUSPENDED` as its target, or that addresses an attorney already sitting in `ADMIN_SUSPENDED`, is rejected with `ERR_INVALID_STATE_TRANSITION`.
    A new attorney is `ACTIVE` with `outstanding_fee_cents`, `open_deficiency_count` and `pending_recertification_count` all zero.
    Most resources also carry an `updated_at` timestamp, refreshed on every mutation of that row, and an integer `version` that starts at 1 on creation and increases by exactly 1 on every mutation of that row — including mutations the row did not ask for, such as a counter bump driven by a cascade from another entity.

    Design: Corner/state_machines/an_administrative_status_change_targeting_admin_suspended_is_refused
    """
    attorney = fixtures.create_attorney(
        bar_number="BAR-2020",
        full_name="Sofia Klein",
        admission_date="2015-01-01T00:00:00Z",
        compliance_group="GROUP_2",
        principal_office_jurisdiction="ST",
    )
    assert attorney["status"] == "ACTIVE"
    assert attorney["version"] == 1

    refused = api_client.attorney_status_change(
        attorney["id"],
        {
            "status": "ADMIN_SUSPENDED",
            "reason": "Attempted administrative suspension by hand.",
        },
        fixtures.BOARD,
    )
    validate_error(refused, "ERR_INVALID_STATE_TRANSITION")

    unmoved = fixtures.read_attorney(attorney["id"])
    assert unmoved["status"] == "ACTIVE"
    assert unmoved["version"] == 1
    assert unmoved["outstanding_fee_cents"] == 0
    assert unmoved["open_deficiency_count"] == 0

    exempt = fixtures.change_attorney_status(
        attorney["id"], "EXEMPT", reason="Full-time judicial appointment."
    )
    assert exempt["status"] == "EXEMPT"
    assert exempt["version"] == 2

    inactive = fixtures.change_attorney_status(
        attorney["id"], "INACTIVE", reason="Voluntary inactive election."
    )
    assert inactive["status"] == "INACTIVE"
    assert inactive["version"] == 3
    assert inactive["outstanding_fee_cents"] == 0
    assert inactive["open_deficiency_count"] == 0


def test_a_standing_change_leaves_the_attorneys_compliance_period_untouched():
    """A standing change leaves every one of that attorney's compliance cycles exactly as it found them: neither `credit_status` nor `administrative_status` moves, and the attorney's own `version` rises by one.
    `credit_status` tracks the credit picture and takes `OPEN`, `SATISFIED`, `DEFICIENT` or `CLOSED_COMITY`, starting at `OPEN`.
    `administrative_status` tracks the filing picture and takes `GOOD_STANDING`, `DELINQUENT`, `ADMIN_SUSPENDED` or `REINSTATED`, starting at `GOOD_STANDING`.

    Design: Corner/state_machines/an_administrative_status_change_targeting_admin_suspended_is_refused
    """
    attorney, cycle = fixtures.setup_attorney_with_cycle(
        attorney_overrides={
            "bar_number": "BAR-2021",
            "full_name": "Sofia Klein",
            "admission_date": "2015-01-01T00:00:00Z",
            "compliance_group": "GROUP_2",
            "principal_office_jurisdiction": "ST",
        },
    )
    before_attorney = fixtures.read_attorney(attorney["id"])
    before_cycle = fixtures.read_cycle(cycle["id"])
    assert before_cycle["credit_status"] == "OPEN"
    assert before_cycle["administrative_status"] == "GOOD_STANDING"

    changed = fixtures.change_attorney_status(
        attorney["id"], "EXEMPT", reason="Full-time judicial appointment."
    )
    assert changed["status"] == "EXEMPT"
    assert changed["version"] == before_attorney["version"] + 1

    after_cycle = fixtures.read_cycle(cycle["id"])
    assert after_cycle["credit_status"] == "OPEN"
    assert after_cycle["administrative_status"] == "GOOD_STANDING"
    assert after_cycle["version"] == before_cycle["version"]


def test_opening_an_audit_freezes_the_risk_score_computed_at_that_moment():
    """The grant stamps `accreditation_term_start` with the current logical instant and `accreditation_term_end` with that instant plus 24 months, flips `self_certification_enabled` to true, raises a `PROVIDER_ANNUAL` assessment against the sponsor for exactly its `annual_fee_cents`, and re-scores it under the self-certified weighting, writing `risk_score_variant` as `SELF_CERTIFIED_WEIGHTING`.
    Against a provider, the provider's `substantiated_complaint_count` rises by one, its `risk_score` is recomputed, and the provider itself moves `ACCREDITED → PROBATIONARY`.
    It also captures `risk_score_at_open`: the provider's risk score computed at that moment and **frozen** onto the audit row, never refreshed afterwards even as the provider's live `risk_score` moves.
    A new audit is created in `OPENED` with `sample_size` zero, `sampled_course_ids` empty, `findings_count` zero and `sanction_type` of `NONE`.
    Accepting the audit sets that complaint's `escalated` to true, so a single complaint can seed at most one audit.
    The delinquency rate is `attendance_reports_late_count` divided by `attendance_reports_total_count`, where the denominator is treated as one whenever the stored count is zero, so a provider that has filed nothing has a delinquency rate of zero rather than an undefined one.
    The complaint rate is `substantiated_complaint_count` divided by three, capped at 1.0 — three substantiated complaints saturate the term.
    The finding rate is `audit_findings_count` divided by a denominator that depends on the variant below, again capped at 1.0.
    The staleness rate measures how long it has been since anyone looked: the anchor is `last_audit_closed_at` when that field is set, and otherwise `accreditation_term_start`; if the anchor is still null the staleness rate is 1.0 outright, and otherwise it is the number of months between the anchor and the current logical instant divided by 24, capped at 1.0.
    `risk_score` is then the delinquency rate weighted at 0.35, plus the complaint rate weighted at 0.30, plus the finding rate weighted at 0.25, plus the staleness rate weighted at 0.10, and the sum is rounded half-up to two decimal places.

    Design: Corner/state_machines/the_cleared_audit_branch_stamps_last_audit_closed_at_and_raises_no_sanction_fee
    """
    provider, course, complaint = build_sponsor_under_substantiated_complaint()

    sponsor = fixtures.read_provider(provider["id"])
    assert sponsor["accreditation_status"] == "PROBATIONARY"
    assert sponsor["substantiated_complaint_count"] == 1
    assert sponsor["audit_findings_count"] == 0
    assert sponsor["attendance_reports_total_count"] == 0
    assert sponsor["attendance_reports_late_count"] == 0
    assert sponsor["last_audit_closed_at"] is None
    assert_same_instant(
        sponsor["accreditation_term_start"], CLOCK_START, "accreditation_term_start"
    )

    audit = fixtures.open_audit(
        provider["id"],
        audit_period_start="2025-01-01T00:00:00Z",
        audit_period_end="2025-06-30T00:00:00Z",
        trigger_type="COMPLAINT_ESCALATION",
        originating_complaint_id=complaint["id"],
    )
    assert audit["status"] == "OPENED"
    assert audit["sample_size"] == 0
    assert audit["sampled_course_ids"] == []
    assert audit["findings_count"] == 0
    assert audit["sanction_type"] == "NONE"
    # 0.35 * 0 + 0.30 * (1 / 3) + 0.25 * 0 + 0.10 * 0, rounded half-up to 0.10.
    assert float(audit["risk_score_at_open"]) == 0.10

    assert fixtures.read_complaint(complaint["id"])["escalated"] is True


def test_the_cleared_audit_branch_stamps_last_audit_closed_at_and_raises_no_sanction_fee():
    """`DRAW_SAMPLE` moves the audit `OPENED → SAMPLED`, and is also legitimately repeatable as a `SAMPLED → SAMPLED` redraw, which is exactly why the version guard exists.
    The eligible pool is the audited provider's courses whose `status` is `APPROVED`, `EXPIRED` or `SUSPENDED_PENDING_REVIEW` and whose `presented_at` falls inside the audit's closed window, both endpoints included.
    The target size comes from the frozen score in three tiers: ten courses when `risk_score_at_open` is 0.60 or above, five when it is 0.30 or above but below 0.60, and two otherwise.
    `sample_size` is then the smaller of the target and the pool size — a pool smaller than the target simply yields a short sample and is not an error — and `sampled_course_ids` is the identifiers of the first `sample_size` entries of the sorted pool, in that order.
    A redraw recomputes the whole list from scratch rather than appending to it, and the provider's `courses_sampled_lifetime` is adjusted by the difference between the new and prior `sample_size` — on a first draw that difference is simply the new sample size.
    `ISSUE_FINDINGS` moves `SAMPLED → FINDINGS_ISSUED` and records a `findings_count` that must be at least zero and no greater than the audit's `sample_size`; more findings than courses examined is `ERR_FINDINGS_EXCEED_SAMPLE`.
    The count is added to the provider's `audit_findings_count` and the risk score is recomputed.
    `CLOSE_CLEARED` requires `findings_count` of at most one, stamps `closed_at` with the current instant, sets `sanction_type` to `NONE`, writes that instant into the provider's `last_audit_closed_at` — which resets the staleness term of the score — and unlocks the sponsor's `PROBATIONARY → ACCREDITED` gate described in §3.1.
    Every charge the board raises is a `FeeAssessment` row, and there are exactly four kinds, recorded in `fee_type`: `LATE_COMPLIANCE` for a missed filing deadline, `REINSTATEMENT` for an administrative suspension, `AUDIT_SANCTION` for a sanctioned audit, and `PROVIDER_ANNUAL` for an accreditation grant or renewal.

    Design: Corner/state_machines/the_cleared_audit_branch_stamps_last_audit_closed_at_and_raises_no_sanction_fee
    """
    provider, course, complaint = build_sponsor_under_substantiated_complaint()
    audit = fixtures.open_audit(
        provider["id"],
        audit_period_start="2025-01-01T00:00:00Z",
        audit_period_end="2025-06-30T00:00:00Z",
        trigger_type="COMPLAINT_ESCALATION",
        originating_complaint_id=complaint["id"],
    )

    sampled = fixtures.audit_action(audit["id"], "DRAW_SAMPLE", audit["version"])
    assert sampled["status"] == "SAMPLED"
    assert sampled["sample_size"] == 1
    assert sampled["sampled_course_ids"] == [course["id"]]
    assert fixtures.read_provider(provider["id"])["courses_sampled_lifetime"] == 1

    issued = fixtures.audit_action(
        audit["id"], "ISSUE_FINDINGS", sampled["version"], findings_count=0
    )
    assert issued["status"] == "FINDINGS_ISSUED"
    assert issued["findings_count"] == 0
    assert fixtures.read_provider(provider["id"])["audit_findings_count"] == 0

    cleared = fixtures.audit_action(audit["id"], "CLOSE_CLEARED", issued["version"])
    assert cleared["status"] == "CLEARED"
    assert cleared["sanction_type"] == "NONE"
    assert_same_instant(cleared["closed_at"], CLOCK_START, "closed_at")

    sponsor = fixtures.read_provider(provider["id"])
    assert_same_instant(
        sponsor["last_audit_closed_at"], CLOCK_START, "last_audit_closed_at"
    )
    assert sponsor["accreditation_status"] == "PROBATIONARY"

    rows, meta = board_fee_page(provider_id=provider["id"])
    assert meta["total_count"] == 1
    assert [row["fee_type"] for row in rows] == ["PROVIDER_ANNUAL"]


def test_the_sanctioned_branch_bills_the_audit_sanction_fee_against_the_sponsor():
    """`ISSUE_FINDINGS` moves `SAMPLED → FINDINGS_ISSUED` and records a `findings_count` that must be at least zero and no greater than the audit's `sample_size`; more findings than courses examined is `ERR_FINDINGS_EXCEED_SAMPLE`.
    The count is added to the provider's `audit_findings_count` and the risk score is recomputed.
    `CLOSE_SANCTIONED` requires `findings_count` of at least one and a supplied `sanction_type` of `PROBATION` or `SUSPENSION`; it stamps `closed_at`, records the sanction, writes `last_audit_closed_at`, and assesses a `FeeAssessment` of `fee_type` `AUDIT_SANCTION` against the provider for 250000 cents.
    An assessment carries `amount_cents`, an `assessed_at` instant, a `status` of `ASSESSED`, `PAID`, `WAIVED` or `VOIDED` starting at `ASSESSED`, a `settled_at` instant recorded when it leaves `ASSESSED`, and a `waiver_reason` recorded only when it is waived.
    Attorney-side assessments carry `attorney_id` and, where a specific compliance period produced them, `cycle_id`; provider-side assessments carry `provider_id` instead and leave the attorney fields null.
    An assessment created by a batch run also records `assessed_by_sweep_id`, the identifier of the run that created it; assessments created by any other action leave that field null.

    Design: Corner/state_machines/the_sanctioned_probation_branch_bills_the_sanction_fee_and_reverts_the_provider
    """
    provider, course, audit = build_single_course_audit_at_findings_issued()
    assert audit["status"] == "FINDINGS_ISSUED"
    assert audit["sample_size"] == 1
    assert audit["sampled_course_ids"] == [course["id"]]
    assert audit["findings_count"] == 1
    assert fixtures.read_provider(provider["id"])["audit_findings_count"] == 1

    sanctioned = fixtures.audit_action(
        audit["id"], "CLOSE_SANCTIONED", audit["version"], sanction_type="PROBATION"
    )
    assert sanctioned["status"] == "SANCTIONED"
    assert sanctioned["sanction_type"] == "PROBATION"
    assert_same_instant(sanctioned["closed_at"], CLOCK_START, "closed_at")

    sponsor = fixtures.read_provider(provider["id"])
    assert_same_instant(
        sponsor["last_audit_closed_at"], CLOCK_START, "last_audit_closed_at"
    )

    rows, meta = board_fee_page(
        provider_id=provider["id"], fee_type="AUDIT_SANCTION"
    )
    assert meta["total_count"] == 1
    fee = rows[0]
    assert fee["fee_type"] == "AUDIT_SANCTION"
    assert fee["amount_cents"] == 250000
    assert fee["status"] == "ASSESSED"
    assert fee["provider_id"] == provider["id"]
    assert fee["attorney_id"] is None
    assert fee["cycle_id"] is None
    assert fee["settled_at"] is None
    assert fee["assessed_by_sweep_id"] is None
    assert_same_instant(fee["assessed_at"], CLOCK_START, "assessed_at")


def test_the_probation_sanction_reverts_the_sponsor_but_leaves_its_courses_approved():
    """`PROBATION` then moves the provider `ACCREDITED → PROBATIONARY`; `SUSPENSION` moves it to `SUSPENDED` from either `ACCREDITED` or `PROBATIONARY`, which suspends that sponsor's self-certified courses, which in turn rejects those courses' credit records still awaiting verification — the same chain §3.1 describes.
    Either way `self_certification_enabled` drops to false, `risk_score_variant` becomes `REVIEWED_WEIGHTING` with the score recomputed under it, and `probation_reason` records the audit or complaint that caused the reversion.
    Probation alone does **not** suspend the sponsor's courses — only `SUSPENDED` and `LAPSED` cascade into courses.
    The score is refreshed at each of these moments: when an audit is opened (into `risk_score_at_open`), on every provider accreditation action, on a `SUBSTANTIATE` disposition, on the `CLOSE_CLEARED` and `CLOSE_SANCTIONED` audit actions, and on every batch run.
    On an audit action that cascades a change to the provider's own `accreditation_status`, the recomputation happens **after** that cascade lands, so the variant chosen reflects the provider's post-cascade standing rather than its standing on arrival.
    Under `REVIEWED_WEIGHTING`, used for every other `accreditation_status` — `APPLIED`, `PROBATIONARY`, `SUSPENDED`, `LAPSED` or `DENIED` — the denominator is `courses_total_count` (again treated as one when zero), because every course such a sponsor offers passed board review.
    The delinquency rate is `attendance_reports_late_count` divided by `attendance_reports_total_count`, where the denominator is treated as one whenever the stored count is zero, so a provider that has filed nothing has a delinquency rate of zero rather than an undefined one.
    The complaint rate is `substantiated_complaint_count` divided by three, capped at 1.0 — three substantiated complaints saturate the term.
    The finding rate is `audit_findings_count` divided by a denominator that depends on the variant below, again capped at 1.0.
    The staleness rate measures how long it has been since anyone looked: the anchor is `last_audit_closed_at` when that field is set, and otherwise `accreditation_term_start`; if the anchor is still null the staleness rate is 1.0 outright, and otherwise it is the number of months between the anchor and the current logical instant divided by 24, capped at 1.0.
    `risk_score` is then the delinquency rate weighted at 0.35, plus the complaint rate weighted at 0.30, plus the finding rate weighted at 0.25, plus the staleness rate weighted at 0.10, and the sum is rounded half-up to two decimal places.

    Design: Corner/state_machines/the_sanctioned_probation_branch_bills_the_sanction_fee_and_reverts_the_provider
    """
    provider, course, audit = build_single_course_audit_at_findings_issued()
    fixtures.audit_action(
        audit["id"], "CLOSE_SANCTIONED", audit["version"], sanction_type="PROBATION"
    )

    sponsor = fixtures.read_provider(provider["id"])
    assert sponsor["accreditation_status"] == "PROBATIONARY"
    assert sponsor["self_certification_enabled"] is False
    assert sponsor["probation_reason"] is not None
    assert sponsor["risk_score_variant"] == "REVIEWED_WEIGHTING"
    assert sponsor["courses_total_count"] == 1
    assert sponsor["audit_findings_count"] == 1
    # 0.35 * 0 + 0.30 * 0 + 0.25 * (1 / 1) + 0.10 * 0 = 0.25.
    assert float(sponsor["risk_score"]) == 0.25

    assert fixtures.read_course(course["id"])["status"] == "APPROVED"


def test_the_sample_is_the_first_courses_of_the_pool_in_presented_at_order():
    """The eligible pool is the audited provider's courses whose `status` is `APPROVED`, `EXPIRED` or `SUSPENDED_PENDING_REVIEW` and whose `presented_at` falls inside the audit's closed window, both endpoints included.
    The pool is ordered by `presented_at` ascending and then `created_at` ascending — never by identifier, and never randomly, so the same engagement over the same data always draws the same courses.
    The target size comes from the frozen score in three tiers: ten courses when `risk_score_at_open` is 0.60 or above, five when it is 0.30 or above but below 0.60, and two otherwise.
    `sample_size` is then the smaller of the target and the pool size — a pool smaller than the target simply yields a short sample and is not an error — and `sampled_course_ids` is the identifiers of the first `sample_size` entries of the sorted pool, in that order.
    A redraw recomputes the whole list from scratch rather than appending to it, and the provider's `courses_sampled_lifetime` is adjusted by the difference between the new and prior `sample_size` — on a first draw that difference is simply the new sample size.

    Design: Corner/state_machines/close_cleared_with_two_findings_is_refused_because_the_clear_threshold_is_one
    """
    provider, march, april, audit = build_two_course_audit_at_findings_issued()

    assert audit["sample_size"] == 2
    assert audit["sampled_course_ids"] == [march["id"], april["id"]]
    assert audit["findings_count"] == 2
    assert fixtures.read_provider(provider["id"])["courses_sampled_lifetime"] == 2


def test_close_cleared_with_two_findings_is_refused_because_the_clear_threshold_is_one():
    """`CLOSE_CLEARED` requires `findings_count` of at most one, stamps `closed_at` with the current instant, sets `sanction_type` to `NONE`, writes that instant into the provider's `last_audit_closed_at` — which resets the staleness term of the score — and unlocks the sponsor's `PROBATIONARY → ACCREDITED` gate described in §3.1.
    `CLOSE_SANCTIONED` requires `findings_count` of at least one and a supplied `sanction_type` of `PROBATION` or `SUSPENSION`; it stamps `closed_at`, records the sanction, writes `last_audit_closed_at`, and assesses a `FeeAssessment` of `fee_type` `AUDIT_SANCTION` against the provider for 250000 cents.
    The addressed resource is in a state from which the requested trigger is declared, and every cross-entity state precondition of that transition holds — otherwise `ERR_INVALID_STATE_TRANSITION` (409).
    A new audit is created in `OPENED` with `sample_size` zero, `sampled_course_ids` empty, `findings_count` zero and `sanction_type` of `NONE`.
    The count is added to the provider's `audit_findings_count` and the risk score is recomputed.

    Design: Corner/state_machines/close_cleared_with_two_findings_is_refused_because_the_clear_threshold_is_one
    """
    provider, march, april, audit = build_two_course_audit_at_findings_issued()

    refused = api_client.provider_audit_action(
        audit["id"],
        {"action": "CLOSE_CLEARED", "expected_audit_version": audit["version"]},
        fixtures.BOARD,
    )
    validate_error(refused, "ERR_INVALID_STATE_TRANSITION")

    unmoved = fixtures.read_audit(audit["id"])
    assert unmoved["status"] == "FINDINGS_ISSUED"
    assert unmoved["sanction_type"] == "NONE"
    assert unmoved["findings_count"] == 2
    assert fixtures.read_provider(provider["id"])["last_audit_closed_at"] is None
    assert board_fee_page(
        provider_id=provider["id"], fee_type="AUDIT_SANCTION"
    )[1]["total_count"] == 0

    sanctioned = fixtures.audit_action(
        audit["id"], "CLOSE_SANCTIONED", unmoved["version"], sanction_type="PROBATION"
    )
    assert sanctioned["status"] == "SANCTIONED"
    assert sanctioned["sanction_type"] == "PROBATION"

    rows, meta = board_fee_page(
        provider_id=provider["id"], fee_type="AUDIT_SANCTION"
    )
    assert meta["total_count"] == 1
    assert rows[0]["amount_cents"] == 250000

    sponsor = fixtures.read_provider(provider["id"])
    assert sponsor["courses_sampled_lifetime"] == 2
    assert sponsor["audit_findings_count"] == 2


def test_a_verified_live_webcast_claim_persists_the_three_specialty_totals():
    """With `ATTENDANCE_CODE`, the supplied `attendance_code` must equal the course's minted code — an absent or mismatched code is `ERR_ATTENDANCE_CODE_INVALID` — and a matching code transitions the new record `PENDING_VERIFICATION → VERIFIED` in the same request, raising the course's `verified_credit_record_count` by one and re-running the owning cycle's credit application.
    A `LIVE_WEBCAST` course yields `LIVE` only when attendance was verified by `ATTENDANCE_CODE` or by `ROSTER` — the two methods that prove someone was actually watching in real time — and otherwise yields `ON_DEMAND`.
    First, the attended figure is clamped: it is the smaller of the claim's `attended_minutes` and the course's `total_minutes`, so a claim for more time than the course contains earns no bonus.
    Then, working through the four categories in the pinned order `ETHICS`, `TECHNOLOGY`, `BIAS_ELIMINATION`, `GENERAL`, each category's raw entitlement is that category's allocated minutes multiplied by the clamped attended figure and divided by the course's `total_minutes` — kept as an exact rational value, never rounded at this step, and taken as zero when the course has no allocation in that category.
    While a cycle's `credit_status` is `OPEN`, the provisional result is what gets persisted into the cycle's `earned_*` fields and into each record's `countable_minutes`.
    Live minutes are never capped.
    A record with no cap pressure therefore contributes each of its four credited category figures in full.
    When every record in the input set has been processed, the overall countable total becomes `earned_countable_minutes`, the three specialty running totals become `earned_ethics_minutes`, `earned_technology_minutes` and `earned_bias_minutes`, and the running live total becomes `earned_live_minutes`.

    Design: Corner/state_machines/comity_approval_closes_the_cycle_when_every_specialty_minimum_is_already_met
    """
    provider, course, attorney, cycle, record, claim = build_comity_claim_setup(
        "Interstate Bar Academy",
        "Specialty Trio Live",
        360,
        [
            {"category": "ETHICS", "minutes": 180},
            {"category": "TECHNOLOGY", "minutes": 60},
            {"category": "BIAS_ELIMINATION", "minutes": 120},
        ],
        "NY",
        "BAR-2030",
        "Adaeze Nwosu",
        "New York full compliance certificate",
        "2026-03-03T12:00:00Z",
    )

    assert record["status"] == "VERIFIED"
    assert record["effective_format"] == "LIVE"
    assert record["source"] == "IN_STATE"
    assert record["credited_ethics_minutes"] == 180
    assert record["credited_technology_minutes"] == 60
    assert record["credited_bias_minutes"] == 120
    assert record["credited_general_minutes"] == 0
    assert record["credited_minutes"] == 360
    assert record["countable_minutes"] == 360

    open_cycle = fixtures.read_cycle(cycle["id"])
    assert open_cycle["credit_status"] == "OPEN"
    assert open_cycle["earned_countable_minutes"] == 360
    assert open_cycle["earned_ethics_minutes"] == 180
    assert open_cycle["earned_technology_minutes"] == 60
    assert open_cycle["earned_bias_minutes"] == 120
    assert open_cycle["earned_live_minutes"] == 360


def test_a_comity_approval_grants_no_minutes_and_creates_no_credit_record():
    """Approval on the `COMITY` basis grants no minutes at all — `converted_minutes` stays 0 and `converted_category` stays at its `GENERAL` default, unused — and creates no credit record.
    A new claim is created in `SUBMITTED` with `converted_minutes` at zero, `converted_category` at `GENERAL` and `determination_reason` null, and the act of filing raises the attorney's own `version` by one.
    Board staff then determine the claim by naming an `action` of `APPROVE` or `DENY`, optionally with a `determination_reason`.

    Design: Corner/state_machines/comity_approval_closes_the_cycle_when_every_specialty_minimum_is_already_met
    """
    provider, course, attorney, cycle, record, claim = build_comity_claim_setup(
        "Interstate Bar Academy",
        "Specialty Trio Live",
        360,
        [
            {"category": "ETHICS", "minutes": 180},
            {"category": "TECHNOLOGY", "minutes": 60},
            {"category": "BIAS_ELIMINATION", "minutes": 120},
        ],
        "NY",
        "BAR-2030",
        "Adaeze Nwosu",
        "New York full compliance certificate",
        "2026-03-03T12:00:00Z",
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["converted_minutes"] == 0
    assert claim["converted_category"] == "GENERAL"
    assert claim["determination_reason"] is None

    determined = fixtures.determine_claim(claim["id"], "APPROVE")
    assert determined["status"] == "APPROVED"
    assert determined["converted_minutes"] == 0
    assert determined["converted_category"] == "GENERAL"

    rows, meta = board_credit_record_page(cycle_id=cycle["id"])
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [record["id"]]


def test_comity_closes_the_period_when_every_specialty_minimum_is_already_met():
    """Instead it must pass a three-part jurisdiction gate, every part of which reports `ERR_COMITY_NOT_AVAILABLE` on failure: the claim's `origin_jurisdiction` must be one of the two comity jurisdictions `NY` or `IL`; the attorney's `principal_office_jurisdiction` must equal that same jurisdiction; and that jurisdiction must not be the home code `ST`.
    Where the gate passes, the covering cycle records the claim in its `comity_claim_id` and then takes one of two divergent outcomes, decided by the cycle's specialty totals computed over `VERIFIED` records only.
    If `earned_ethics_minutes` has reached `required_ethics_minutes`, `earned_technology_minutes` has reached `required_technology_minutes`, and `earned_bias_minutes` has reached `required_bias_minutes`, the cycle moves `credit_status` from `OPEN` to `CLOSED_COMITY`: `certified_at` is stamped with the current logical instant, `earned_countable_minutes` is set to `required_total_minutes` because the general requirement is deemed met by comity, the three specialty earned figures keep their computed values, and both `carryover_out_general_minutes` and `carryover_out_ethics_minutes` are set to zero because a comity closure never carries anything forward.
    Comity waives the general hour requirement only; the ethics, technology and elimination-of-bias minimums survive it intact.
    Otherwise, `prorated` is true exactly when the attorney's `admission_date` falls inside the cycle's half-open window — that is, when it is at or after `period_start` and strictly before `period_end`.
    A full 24-month cycle therefore requires exactly 1800 minutes, and a shortened one requires a whole number of hours' worth of minutes and never a fraction of an hour.
    When the cycle is not prorated at all, or when the month count is 12 or more, they apply in full: `required_ethics_minutes` is 180 minutes (3 hours), `required_technology_minutes` is 60 minutes (1 hour) and `required_bias_minutes` is 120 minutes (2 hours).

    Design: Corner/state_machines/comity_approval_closes_the_cycle_when_every_specialty_minimum_is_already_met
    """
    provider, course, attorney, cycle, record, claim = build_comity_claim_setup(
        "Interstate Bar Academy",
        "Specialty Trio Live",
        360,
        [
            {"category": "ETHICS", "minutes": 180},
            {"category": "TECHNOLOGY", "minutes": 60},
            {"category": "BIAS_ELIMINATION", "minutes": 120},
        ],
        "NY",
        "BAR-2030",
        "Adaeze Nwosu",
        "New York full compliance certificate",
        "2026-03-03T12:00:00Z",
    )
    before = fixtures.read_cycle(cycle["id"])
    assert before["prorated"] is False
    assert before["required_total_minutes"] == 1800
    assert before["required_ethics_minutes"] == 180
    assert before["required_technology_minutes"] == 60
    assert before["required_bias_minutes"] == 120

    fixtures.determine_claim(claim["id"], "APPROVE")

    closed = fixtures.read_cycle(cycle["id"])
    assert closed["credit_status"] == "CLOSED_COMITY"
    assert closed["comity_claim_id"] == claim["id"]
    assert_same_instant(closed["certified_at"], CLOCK_START, "certified_at")
    assert closed["earned_countable_minutes"] == 1800
    assert closed["earned_ethics_minutes"] == 180
    assert closed["earned_technology_minutes"] == 60
    assert closed["earned_bias_minutes"] == 120
    assert closed["carryover_out_general_minutes"] == 0
    assert closed["carryover_out_ethics_minutes"] == 0

    assert fixtures.read_attorney(attorney["id"])["open_deficiency_count"] == 0


def test_comity_approval_with_a_missing_bias_minimum_pushes_the_period_to_deficient():
    """Approval on the `COMITY` basis grants no minutes at all — `converted_minutes` stays 0 and `converted_category` stays at its `GENERAL` default, unused — and creates no credit record.
    Instead it must pass a three-part jurisdiction gate, every part of which reports `ERR_COMITY_NOT_AVAILABLE` on failure: the claim's `origin_jurisdiction` must be one of the two comity jurisdictions `NY` or `IL`; the attorney's `principal_office_jurisdiction` must equal that same jurisdiction; and that jurisdiction must not be the home code `ST`.
    If `earned_ethics_minutes` has reached `required_ethics_minutes`, `earned_technology_minutes` has reached `required_technology_minutes`, and `earned_bias_minutes` has reached `required_bias_minutes`, the cycle moves `credit_status` from `OPEN` to `CLOSED_COMITY`: `certified_at` is stamped with the current logical instant, `earned_countable_minutes` is set to `required_total_minutes` because the general requirement is deemed met by comity, the three specialty earned figures keep their computed values, and both `carryover_out_general_minutes` and `carryover_out_ethics_minutes` are set to zero because a comity closure never carries anything forward.
    If even one of the three specialty totals is below its requirement, the cycle instead moves `credit_status` from `OPEN` to `DEFICIENT`, still recording `comity_claim_id` even though nothing was closed, and the attorney's `open_deficiency_count` rises by one.
    Comity waives the general hour requirement only; the ethics, technology and elimination-of-bias minimums survive it intact.
    When the cycle is not prorated at all, or when the month count is 12 or more, they apply in full: `required_ethics_minutes` is 180 minutes (3 hours), `required_technology_minutes` is 60 minutes (1 hour) and `required_bias_minutes` is 120 minutes (2 hours).

    Design: Corner/state_machines/comity_approval_with_a_missing_bias_minimum_pushes_the_cycle_to_deficient
    """
    provider, course, attorney, cycle, record, claim = build_comity_claim_setup(
        "Prairie Bar Institute",
        "Ethics And Tech Only",
        240,
        [
            {"category": "ETHICS", "minutes": 180},
            {"category": "TECHNOLOGY", "minutes": 60},
        ],
        "IL",
        "BAR-2031",
        "Marcus Feld",
        "Illinois full compliance certificate",
        "2026-03-03T12:00:00Z",
    )
    before = fixtures.read_cycle(cycle["id"])
    assert before["required_bias_minutes"] == 120
    assert before["earned_bias_minutes"] == 0

    determined = fixtures.determine_claim(claim["id"], "APPROVE")
    assert determined["status"] == "APPROVED"
    assert determined["converted_minutes"] == 0

    deficient = fixtures.read_cycle(cycle["id"])
    assert deficient["credit_status"] == "DEFICIENT"
    assert deficient["comity_claim_id"] == claim["id"]
    assert deficient["certified_at"] is None
    assert deficient["earned_countable_minutes"] == 240
    assert deficient["earned_ethics_minutes"] == 180
    assert deficient["earned_technology_minutes"] == 60
    assert deficient["earned_bias_minutes"] == 0

    assert fixtures.read_attorney(attorney["id"])["open_deficiency_count"] == 1
    assert board_credit_record_page(cycle_id=cycle["id"])[1]["total_count"] == 1


def test_the_first_batch_run_marks_the_missed_deadline_delinquent_and_caps_the_late_fee():
    """Finally, `filing_deadline` is `period_end` plus an offset drawn from the attorney's `compliance_group`: 31 days for `GROUP_1`, 61 days for `GROUP_2` and 91 days for `GROUP_3`.
    Otherwise, `prorated` is true exactly when the attorney's `admission_date` falls inside the cycle's half-open window — that is, when it is at or after `period_start` and strictly before `period_end`.
    A full 24-month cycle therefore requires exactly 1800 minutes, and a shortened one requires a whole number of hours' worth of minutes and never a fraction of an hour.
    When the cycle is not prorated at all, or when the month count is 12 or more, they apply in full: `required_ethics_minutes` is 180 minutes (3 hours), `required_technology_minutes` is 60 minutes (1 hour) and `required_bias_minutes` is 120 minutes (2 hours).
    Each run stamps `as_of` with the current logical instant and takes a `sweep_number` one higher than the previous run's, the first run being number 1.
    `cycles_examined` counts the cycles the run considered.
    The first: a cycle whose `administrative_status` is `GOOD_STANDING`, whose `credit_status` is `OPEN` or `DEFICIENT`, and whose `filing_deadline` is at or before the run's `as_of`, moves `administrative_status` from `GOOD_STANDING` to `DELINQUENT`.
    Its `delinquent_since` is set to the run's `as_of` — not to the deadline it missed — and a `FeeAssessment` is created with `fee_type` `LATE_COMPLIANCE`, the cycle's `attorney_id` and `cycle_id`, an `assessed_by_sweep_id` naming this run, `status` of `ASSESSED` and an `amount_cents` derived as described below.
    That assessment raises the attorney's `outstanding_fee_cents` by its `amount_cents`, and the run's `delinquencies_issued` and `late_fees_assessed_cents` tallies rise by one and by that amount respectively.
    Step two runs the credit application in its final variant — `VERIFIED` records only — substituting that effective figure for `carryover_in_general_minutes`.
    Step three totals the shortfall across all four requirements: the total deficiency plus the ethics, technology and elimination-of-bias deficiencies, added together as one number of minutes.
    Step four converts that to whole hours, rounding **up** — one minute short is one deficient hour.
    Step five picks a base amount from the rounded hour count: zero hours gives 15000 cents, one to five hours gives 25000, six to fifteen gives 40000, and sixteen or more gives 60000.
    Step six adds a surcharge of 2500 cents for each deficient hour, counting at most twenty hours.
    Step seven caps the total: `amount_cents` is the smaller of 100000 cents and the base plus surcharge.

    Design: Corner/state_machines/sweep_suspension_cascades_into_the_attorney_and_denies_the_submitted_claim
    """
    attorney, cycle, claim, sweep = build_delinquent_attorney_with_pending_claim()

    assert sweep["sweep_number"] == 1
    assert_same_instant(sweep["as_of"], CLOCK_START, "as_of")
    assert sweep["cycles_examined"] == 1
    assert sweep["delinquencies_issued"] == 1
    assert sweep["suspensions_issued"] == 0
    # 1800 + 180 + 60 + 120 = 2160 minutes short, 36 hours: 60000 + 2500 * 20
    # is 110000, capped at 100000.
    assert sweep["late_fees_assessed_cents"] == 100000

    delinquent = fixtures.read_cycle(cycle["id"])
    assert_same_instant(
        delinquent["filing_deadline"], "2026-02-01T00:00:00Z", "filing_deadline"
    )
    assert delinquent["required_total_minutes"] == 1800
    assert delinquent["earned_countable_minutes"] == 0
    assert delinquent["administrative_status"] == "DELINQUENT"
    assert delinquent["credit_status"] == "OPEN"
    assert_same_instant(
        delinquent["delinquent_since"], CLOCK_START, "delinquent_since"
    )

    rows, meta = board_fee_page(attorney_id=attorney["id"])
    assert meta["total_count"] == 1
    fee = rows[0]
    assert fee["fee_type"] == "LATE_COMPLIANCE"
    assert fee["amount_cents"] == 100000
    assert fee["status"] == "ASSESSED"
    assert fee["attorney_id"] == attorney["id"]
    assert fee["cycle_id"] == cycle["id"]
    assert fee["assessed_by_sweep_id"] == sweep["id"]
    assert_same_instant(fee["assessed_at"], CLOCK_START, "assessed_at")

    holder = fixtures.read_attorney(attorney["id"])
    assert holder["status"] == "ACTIVE"
    assert holder["outstanding_fee_cents"] == 100000


def test_the_second_batch_run_suspends_the_period_and_cascades_into_the_attorney_and_the_claim():
    """Each run stamps `as_of` with the current logical instant and takes a `sweep_number` one higher than the previous run's, the first run being number 1.
    The first: a cycle whose `administrative_status` is `GOOD_STANDING`, whose `credit_status` is `OPEN` or `DEFICIENT`, and whose `filing_deadline` is at or before the run's `as_of`, moves `administrative_status` from `GOOD_STANDING` to `DELINQUENT`.
    The second enforcement step: a cycle whose `administrative_status` is `DELINQUENT`, whose `credit_status` is `OPEN` or `DEFICIENT`, and whose `delinquent_since` is at least 60 days before the run's `as_of`, moves `administrative_status` from `DELINQUENT` to `ADMIN_SUSPENDED`.
    This cascades: the attorney's own `status` moves `ACTIVE → ADMIN_SUSPENDED`, which is the only way that value is ever written; every reciprocity or comity claim of that attorney still in `SUBMITTED` is denied with `determination_reason` of `ATTORNEY_ADMIN_SUSPENDED`, as §3.7 notes; and a second `FeeAssessment` is created with `fee_type` `REINSTATEMENT` for 50000 cents, naming the same `attorney_id`, `cycle_id` and `assessed_by_sweep_id`, which raises `outstanding_fee_cents` again.
    The run's `suspensions_issued` rises by one and its `late_fees_assessed_cents` rises by the reinstatement amount as well — that tally is the run's total money assessed, not its late-fee money alone.
    A third route into `DENIED` exists that no one requests: when a batch run drives an attorney into administrative suspension, every one of that attorney's claims still sitting in `SUBMITTED` is denied automatically, with `determination_reason` set to `ATTORNEY_ADMIN_SUSPENDED`.
    The two advance independently, and every combination is legitimate: a cycle can be `SATISFIED` and yet `DELINQUENT` (the credits were earned but the filing was late), or `OPEN` and `GOOD_STANDING`, or `DEFICIENT` and `ADMIN_SUSPENDED`.
    The invariant that binds the ledger is stated on the attorney: `outstanding_fee_cents` always equals the sum of `amount_cents` over that attorney's assessments whose `status` is still `ASSESSED`.

    Design: Corner/state_machines/sweep_suspension_cascades_into_the_attorney_and_denies_the_submitted_claim
    """
    attorney, cycle, claim, first_sweep = build_delinquent_attorney_with_pending_claim()
    late_fee = board_fee_page(
        attorney_id=attorney["id"], fee_type="LATE_COMPLIANCE"
    )[0][0]

    fixtures.set_clock("2026-09-30T00:00:00Z")
    second_sweep = fixtures.run_sweep()

    assert second_sweep["sweep_number"] == 2
    assert_same_instant(second_sweep["as_of"], "2026-09-30T00:00:00Z", "as_of")
    assert second_sweep["suspensions_issued"] == 1
    assert second_sweep["delinquencies_issued"] == 0
    assert second_sweep["late_fees_assessed_cents"] == 50000

    suspended = fixtures.read_cycle(cycle["id"])
    assert suspended["administrative_status"] == "ADMIN_SUSPENDED"
    assert suspended["credit_status"] == "OPEN"

    holder = fixtures.read_attorney(attorney["id"])
    assert holder["status"] == "ADMIN_SUSPENDED"
    assert holder["outstanding_fee_cents"] == late_fee["amount_cents"] + 50000

    claims = fixtures.list_reciprocity_claims(attorney["id"])
    denied = [row for row in claims if row["id"] == claim["id"]]
    assert len(denied) == 1, f"the filed claim must still be readable, got {claims}"
    assert denied[0]["status"] == "DENIED"
    assert denied[0]["determination_reason"] == "ATTORNEY_ADMIN_SUSPENDED"

    rows, meta = board_fee_page(attorney_id=attorney["id"])
    assert meta["total_count"] == 2
    by_type = {row["fee_type"]: row for row in rows}
    assert sorted(by_type) == ["LATE_COMPLIANCE", "REINSTATEMENT"]
    assert by_type["REINSTATEMENT"]["amount_cents"] == 50000
    assert by_type["REINSTATEMENT"]["cycle_id"] == cycle["id"]
    assert by_type["REINSTATEMENT"]["assessed_by_sweep_id"] == second_sweep["id"]
    assert by_type["LATE_COMPLIANCE"]["assessed_by_sweep_id"] == first_sweep["id"]
    assert [row["status"] for row in rows] == ["ASSESSED", "ASSESSED"]
    assert holder["outstanding_fee_cents"] == sum(
        row["amount_cents"] for row in rows
    )

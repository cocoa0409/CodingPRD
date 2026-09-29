"""Version guards, cascade sweeps and the immediacy of a credit filing's effects.

Every test builds its own register from scratch through the endpoints the PRD
declares, and moves the logical clock only where the rule under test needs it.
"""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    factories as f,
    fixtures as fx,
    make_attorney_headers,
    make_provider_admin_headers,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

BOARD = TEST_USERS["board_admin_headers"]

CLOCK_START = "2026-08-01T00:00:00Z"
TERM_END_FROM_START = "2028-08-01T00:00:00Z"

REVIEWER_ID = "33333333-3333-4333-8333-333333333333"


def _instant(value: str) -> datetime:
    """Reads a wire timestamp so two spellings of one instant compare equal."""
    assert value is not None, "expected a timestamp, found null"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _same_instant(actual: str, expected: str) -> bool:
    return _instant(actual) == _instant(expected)


def test_a_stale_provider_version_is_refused_and_the_current_one_renews_the_term(api, board_headers):
    """PRD 2.6: "`POST /cle/providers/{id}/accreditation-actions` requires `expected_provider_version`, carrying the client's last observed `version` of the target `Provider`. If it does not equal that provider's current `version`, the action is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD 2.5: "Most resources also carry an `updated_at` timestamp, refreshed on every mutation of that row, and an integer `version` that starts at 1 on creation and increases by exactly 1 on every mutation of that row — including mutations the row did not ask for, such as a counter bump driven by a cascade from another entity."
    PRD 3.1: "It re-stamps `accreditation_term_start` to the current instant and `accreditation_term_end` to that instant plus 24 months, so the new term wholly supersedes the prior one, and it raises a fresh `PROVIDER_ANNUAL` assessment for `annual_fee_cents`."

    Design: Corner/cross_cutting_complexity_layers/all_three_concurrency_rules_reject_a_stale_parent_version_and_accept_the_current_one
    """
    provider = fx.create_provider(
        name="Keystone Bar Association Education", provider_type="BAR_ASSOCIATION"
    )
    first_version = provider["version"]
    assert first_version == 1

    granted = fx.accreditation_action(provider["id"], "GRANT_FULL", first_version)
    second_version = granted["version"]
    assert second_version == 2

    annual_rows, _ = validate_paginated(
        api.list_fee_assessments(
            board_headers,
            params={"provider_id": provider["id"], "fee_type": "PROVIDER_ANNUAL"},
        )
    )
    assert len(annual_rows) == 1
    assert annual_rows[0]["amount_cents"] == 120000
    fx.settle_fee(annual_rows[0]["id"], "PAY", board_headers)

    validate_error(
        api.provider_accreditation_action(
            provider["id"],
            f.accreditation_action_payload("RENEW", first_version),
            board_headers,
        ),
        ApiErrorId.ERR_STALE_VERSION,
    )
    assert fx.read_provider(provider["id"])["version"] == second_version

    renewed = validate_success(
        api.provider_accreditation_action(
            provider["id"],
            f.accreditation_action_payload("RENEW", second_version),
            board_headers,
        ),
        expected_status=200,
    )
    assert renewed["accreditation_status"] == "ACCREDITED"
    assert renewed["version"] == 3
    assert _same_instant(renewed["accreditation_term_start"], CLOCK_START)
    assert _same_instant(renewed["accreditation_term_end"], TERM_END_FROM_START)

    after_rows, after_meta = validate_paginated(
        api.list_fee_assessments(
            board_headers,
            params={"provider_id": provider["id"], "fee_type": "PROVIDER_ANNUAL"},
        )
    )
    assert after_meta["total_count"] == 2
    settled = [row for row in after_rows if row["status"] == "PAID"]
    outstanding = [row for row in after_rows if row["status"] == "ASSESSED"]
    assert len(settled) == 1
    assert len(outstanding) == 1
    assert outstanding[0]["amount_cents"] == 120000


def test_a_stale_attorney_version_is_refused_and_the_current_one_files_the_claim(api, board_headers):
    """PRD 2.6: "`POST /cle/reciprocity-claims` requires `expected_attorney_version`, carrying the client's last observed `version` of the named `Attorney`. A mismatch with that attorney's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because the attorney row may meanwhile have absorbed an approved claim, a fee assessment or an administrative suspension, all of which change whether and how a new claim converts."
    PRD 3.4: "A standing change leaves every one of that attorney's compliance cycles exactly as it found them: neither `credit_status` nor `administrative_status` moves, and the attorney's own `version` rises by one."
    PRD 3.7: "A new claim is created in `SUBMITTED` with `converted_minutes` at zero, `converted_category` at `GENERAL` and `determination_reason` null, and the act of filing raises the attorney's own `version` by one."

    Design: Corner/cross_cutting_complexity_layers/all_three_concurrency_rules_reject_a_stale_parent_version_and_accept_the_current_one
    """
    attorney = fx.create_attorney(
        bar_number="CONC-1001",
        full_name="Rosalind Thackeray",
        admission_date="2003-04-04T00:00:00Z",
    )
    first_version = attorney["version"]
    assert first_version == 1

    fx.change_attorney_status(
        attorney["id"], "EXEMPT", reason="Deployed on active military service."
    )
    reactivated = fx.change_attorney_status(
        attorney["id"], "ACTIVE", reason="Returned to active practice."
    )
    third_version = reactivated["version"]
    assert third_version == first_version + 2

    validate_error(
        api.create_reciprocity_claim(
            f.create_reciprocity_claim_payload(attorney["id"], first_version),
            make_attorney_headers(attorney["id"]),
        ),
        ApiErrorId.ERR_STALE_VERSION,
    )
    _, empty_meta = validate_paginated(
        api.list_attorney_reciprocity_claims(attorney["id"], board_headers)
    )
    assert empty_meta["total_count"] == 0
    assert fx.read_attorney(attorney["id"])["version"] == third_version

    claim = validate_success(
        api.create_reciprocity_claim(
            f.create_reciprocity_claim_payload(attorney["id"], third_version),
            make_attorney_headers(attorney["id"]),
        ),
        expected_status=201,
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["converted_minutes"] == 0
    assert claim["converted_category"] == "GENERAL"
    assert claim["determination_reason"] is None

    _, filed_meta = validate_paginated(
        api.list_attorney_reciprocity_claims(attorney["id"], board_headers)
    )
    assert filed_meta["total_count"] == 1
    assert fx.read_attorney(attorney["id"])["version"] == third_version + 1


def test_a_stale_audit_version_is_refused_and_the_current_one_redraws_the_sample(api, board_headers):
    """PRD 2.6: "`POST /cle/provider-audits/{id}/audit-actions` requires `expected_audit_version`, carrying the client's last observed `version` of the target `ProviderAudit`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), which prevents a redraw or a findings filing computed against a sample the audit no longer holds."
    PRD 3.9: "`DRAW_SAMPLE` moves the audit `OPENED → SAMPLED`, and is also legitimately repeatable as a `SAMPLED → SAMPLED` redraw, which is exactly why the version guard exists."
    PRD 3.9: "`sample_size` is then the smaller of the target and the pool size — a pool smaller than the target simply yields a short sample and is not an error — and `sampled_course_ids` is the identifiers of the first `sample_size` entries of the sorted pool, in that order."
    PRD 3.9: "A redraw recomputes the whole list from scratch rather than appending to it, and the provider's `courses_sampled_lifetime` is adjusted by the difference between the new and prior `sample_size` — on a first draw that difference is simply the new sample size."

    Design: Corner/cross_cutting_complexity_layers/all_three_concurrency_rules_reject_a_stale_parent_version_and_accept_the_current_one
    """
    provider = fx.create_accredited_provider(
        name="Wexford Institute of Legal Study", provider_type="BAR_ASSOCIATION"
    )
    course = fx.create_self_certified_course(
        provider,
        title="Estate Administration On Demand",
        delivery_format="ON_DEMAND",
        total_minutes=300,
        presented_at="2026-03-01T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[f.credit_allocation_entry("GENERAL", 300)],
    )
    assert course["status"] == "APPROVED"

    audit = fx.open_audit(
        provider["id"],
        audit_period_start="2026-01-01T00:00:00Z",
        audit_period_end="2026-06-30T00:00:00Z",
        trigger_type="RISK_BASED",
    )
    first_version = audit["version"]
    assert first_version == 1
    assert audit["status"] == "OPENED"

    drawn = fx.audit_action(audit["id"], "DRAW_SAMPLE", first_version)
    second_version = drawn["version"]
    assert second_version == 2
    assert drawn["status"] == "SAMPLED"
    assert drawn["sample_size"] == 1
    assert drawn["sampled_course_ids"] == [course["id"]]

    validate_error(
        api.provider_audit_action(
            audit["id"],
            f.audit_action_payload("DRAW_SAMPLE", first_version),
            board_headers,
        ),
        ApiErrorId.ERR_STALE_VERSION,
    )
    assert fx.read_audit(audit["id"])["version"] == second_version

    redrawn = validate_success(
        api.provider_audit_action(
            audit["id"],
            f.audit_action_payload("DRAW_SAMPLE", second_version),
            board_headers,
        ),
        expected_status=200,
    )
    assert redrawn["status"] == "SAMPLED"
    assert redrawn["version"] == 3
    assert redrawn["sample_size"] == 1
    assert redrawn["sampled_course_ids"] == [course["id"]]
    assert fx.read_provider(provider["id"])["courses_sampled_lifetime"] == 1


def _sponsor_holding_both_kinds_of_approved_course():
    """A sponsor promoted from probation to full accreditation, holding one course
    approved through board review and one it certified for itself.
    Returns (provider, reviewed_course, self_certified_course)."""
    provider = fx.create_probationary_provider(
        name="Alderwood Professional Institute", provider_type="COMMERCIAL"
    )
    reviewed = fx.create_self_certified_course(
        provider,
        title="Guardianship Practice Recorded",
        delivery_format="ON_DEMAND",
        total_minutes=180,
        presented_at="2026-03-15T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[f.credit_allocation_entry("GENERAL", 180)],
    )
    _application, reviewed = fx.approve_course_by_review(
        reviewed, make_provider_admin_headers(provider["id"]), REVIEWER_ID
    )
    fx.take_audit_to_cleared(
        provider["id"],
        audit_period_start="2026-01-01T00:00:00Z",
        audit_period_end="2026-06-30T00:00:00Z",
        trigger_type="RANDOM",
        findings_count=0,
    )
    observed = fx.read_provider(provider["id"])
    provider = fx.accreditation_action(
        observed["id"], "GRANT_FULL", observed["version"]
    )
    assert provider["accreditation_status"] == "ACCREDITED"
    assert provider["self_certification_enabled"] is True

    self_certified = fx.create_self_certified_course(
        provider,
        title="Fiduciary Accounting Recorded",
        delivery_format="ON_DEMAND",
        total_minutes=300,
        presented_at="2026-07-15T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[f.credit_allocation_entry("GENERAL", 300)],
    )
    assert self_certified["status"] == "APPROVED"
    assert self_certified["approval_pathway"] == "PROVIDER_ACCREDITED"
    return fx.read_provider(provider["id"]), reviewed, self_certified


def test_suspending_a_sponsor_sweeps_out_only_its_self_certified_live_courses(api):
    """PRD 3.1: "Both branches set `self_certification_enabled` to false and both run the sponsor-suspension cascade: every course of that sponsor that is currently `APPROVED`, was approved through the self-certification pathway, and has not yet reached its `expires_at` moves `APPROVED → SUSPENDED_PENDING_REVIEW`."
    PRD 3.1: "The only difference between the branches is scoring: leaving `ACCREDITED` also switches `risk_score_variant` to `REVIEWED_WEIGHTING` and re-scores under it, whereas a sponsor leaving `PROBATIONARY` was already being scored that way."
    PRD 2.10: "Consistency in this system is immediate, not eventual: when one operation moves several rows, all of those moves land inside the same request, and the response reflects the finished state."
    PRD 2.5: "Most resources also carry an `updated_at` timestamp, refreshed on every mutation of that row, and an integer `version` that starts at 1 on creation and increases by exactly 1 on every mutation of that row — including mutations the row did not ask for, such as a counter bump driven by a cascade from another entity."

    Design: Corner/cross_cutting_complexity_layers/suspending_and_reinstating_a_provider_walks_the_course_cascade_out_and_back
    """
    provider, reviewed, self_certified = _sponsor_holding_both_kinds_of_approved_course()

    suspended = fx.accreditation_action(
        provider["id"], "SUSPEND", provider["version"],
        probation_reason="Two attendee complaints await review.",
    )
    assert suspended["accreditation_status"] == "SUSPENDED"
    assert suspended["self_certification_enabled"] is False
    assert suspended["risk_score_variant"] == "REVIEWED_WEIGHTING"
    assert suspended["version"] == provider["version"] + 1

    swept = fx.read_course(self_certified["id"])
    assert swept["status"] == "SUSPENDED_PENDING_REVIEW"

    untouched = fx.read_course(reviewed["id"])
    assert untouched["status"] == "APPROVED"
    assert untouched["approval_pathway"] == "INDIVIDUAL_APPROVAL"


def test_reinstating_the_sponsor_walks_the_courses_back_but_not_the_self_certification(api, board_headers):
    """PRD 3.1: "`REINSTATE` moves a `SUSPENDED` sponsor to `PROBATIONARY` — never directly back to `ACCREDITED` — and requires that the sponsor have no `AUDIT_SANCTION` assessment still in `ASSESSED`; an unpaid sanction fee makes it an `ERR_INVALID_STATE_TRANSITION`. Reinstatement runs the compensation cascade: every course of that sponsor in `SUSPENDED_PENDING_REVIEW` whose `expires_at` is still in the future returns to `APPROVED`."
    PRD 3.1: "Throughout all of this, `self_certification_enabled` is not an independent switch: it is true exactly when `accreditation_status` is `ACCREDITED`, and false in every other state."
    PRD 3.2: "Every other course is created in `PENDING_APPROVAL` and stays there until an application is decided; if it names a sponsor, only that sponsor's `courses_total_count` rises."

    Design: Corner/cross_cutting_complexity_layers/suspending_and_reinstating_a_provider_walks_the_course_cascade_out_and_back
    """
    provider, reviewed, self_certified = _sponsor_holding_both_kinds_of_approved_course()

    suspended = fx.accreditation_action(
        provider["id"], "SUSPEND", provider["version"],
        probation_reason="Two attendee complaints await review.",
    )
    assert fx.read_course(self_certified["id"])["status"] == "SUSPENDED_PENDING_REVIEW"

    annual_rows, annual_meta = validate_paginated(
        api.list_fee_assessments(
            board_headers,
            params={"provider_id": provider["id"], "fee_type": "PROVIDER_ANNUAL"},
        )
    )
    assert annual_meta["total_count"] == 1
    assert annual_rows[0]["status"] == "ASSESSED"

    reinstated = fx.accreditation_action(
        provider["id"], "REINSTATE", suspended["version"],
        probation_reason="The complaints were withdrawn.",
    )
    assert reinstated["accreditation_status"] == "PROBATIONARY"
    assert reinstated["self_certification_enabled"] is False
    assert reinstated["version"] == suspended["version"] + 1

    restored = fx.read_course(self_certified["id"])
    assert restored["status"] == "APPROVED"
    assert restored["approval_pathway"] == "PROVIDER_ACCREDITED"
    assert fx.read_course(reviewed["id"])["status"] == "APPROVED"

    after_reinstatement = fx.create_self_certified_course(
        reinstated,
        title="Probate Mediation Recorded",
        delivery_format="ON_DEMAND",
        total_minutes=180,
        presented_at="2026-07-20T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[f.credit_allocation_entry("GENERAL", 180)],
    )
    assert after_reinstatement["status"] == "PENDING_APPROVAL"
    assert after_reinstatement["approval_pathway"] == "INDIVIDUAL_APPROVAL"

    counted = fx.read_provider(provider["id"])
    assert counted["courses_total_count"] == 3
    assert counted["courses_self_certified_count"] == 1


def _accredited_sponsor_with_a_live_and_a_recorded_course():
    """A fully accredited sponsor whose term ends 24 months out, holding one live
    webcast that expires two hours after it starts and one recorded course that
    keeps its shelf life for three years.
    Returns (provider, live_course, recorded_course)."""
    provider = fx.create_accredited_provider(
        name="Statehouse Counsel Academy", provider_type="GOVERNMENT"
    )
    assert _same_instant(provider["accreditation_term_end"], TERM_END_FROM_START)

    live = fx.create_self_certified_course(
        provider,
        title="Webcast on Appellate Standards",
        delivery_format="LIVE_WEBCAST",
        total_minutes=120,
        presented_at="2026-09-10T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[f.credit_allocation_entry("GENERAL", 120)],
    )
    recorded = fx.create_self_certified_course(
        provider,
        title="Recorded Survey of Agency Practice",
        delivery_format="ON_DEMAND",
        total_minutes=300,
        presented_at="2026-09-01T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[f.credit_allocation_entry("GENERAL", 300)],
    )
    assert live["status"] == "APPROVED"
    assert recorded["status"] == "APPROVED"
    assert _same_instant(live["expires_at"], "2026-09-10T11:00:00Z")
    assert _same_instant(recorded["expires_at"], "2029-09-01T09:00:00Z")
    return provider, live, recorded


def test_two_runs_at_the_untouched_clock_age_nothing_and_number_themselves(api, board_headers):
    """PRD 3.9: "Nothing in this system ages by itself. Deadlines pass, approvals expire and accreditation terms run out only when the board executes its reporting run, which a board administrator triggers with no body at all and which returns a `ReportingSweep` record of what it did. Each run stamps `as_of` with the current logical instant and takes a `sweep_number` one higher than the previous run's, the first run being number 1."
    PRD 2.4: "Before the clock is ever set it reads exactly `2026-08-01T00:00:00Z`."

    Design: Corner/cross_cutting_complexity_layers/the_sweep_expires_courses_and_lapses_providers_only_when_the_clock_reaches_the_instant
    """
    provider, live, recorded = _accredited_sponsor_with_a_live_and_a_recorded_course()

    first = fx.run_sweep()
    assert first["sweep_number"] == 1
    assert _same_instant(first["as_of"], CLOCK_START)
    assert first["cycles_examined"] == 0
    assert first["delinquencies_issued"] == 0
    assert first["suspensions_issued"] == 0
    assert first["late_fees_assessed_cents"] == 0
    assert first["courses_expired"] == 0
    assert first["providers_lapsed"] == 0

    second = fx.run_sweep()
    assert second["sweep_number"] == 2
    assert _same_instant(second["as_of"], CLOCK_START)
    assert second["courses_expired"] == 0
    assert second["providers_lapsed"] == 0

    assert fx.read_course(live["id"])["status"] == "APPROVED"
    assert fx.read_course(recorded["id"])["status"] == "APPROVED"
    observed = fx.read_provider(provider["id"])
    assert observed["accreditation_status"] == "ACCREDITED"
    assert observed["self_certification_enabled"] is True


def test_the_run_expires_only_the_course_whose_instant_the_clock_has_reached(api, board_headers):
    """PRD 3.9: "Every course in `APPROVED` whose `expires_at` is at or before `as_of` moves to `EXPIRED`, and `courses_expired` counts them."
    PRD 3.2: "For `LIVE_IN_PERSON` and `LIVE_WEBCAST` it is `presented_at` plus the course's own `total_minutes` — a live session's approval covers the session and nothing more. For `ON_DEMAND` and `SELF_STUDY` it is `presented_at` plus 36 months, three years of shelf life for recorded material."

    Design: Corner/cross_cutting_complexity_layers/the_sweep_expires_courses_and_lapses_providers_only_when_the_clock_reaches_the_instant
    """
    provider, live, recorded = _accredited_sponsor_with_a_live_and_a_recorded_course()

    fx.set_clock("2026-09-10T11:00:00Z")
    run = fx.run_sweep()
    assert run["sweep_number"] == 1
    assert _same_instant(run["as_of"], "2026-09-10T11:00:00Z")
    assert run["courses_expired"] == 1
    assert run["providers_lapsed"] == 0

    assert fx.read_course(live["id"])["status"] == "EXPIRED"
    assert fx.read_course(recorded["id"])["status"] == "APPROVED"
    observed = fx.read_provider(provider["id"])
    assert observed["accreditation_status"] == "ACCREDITED"
    assert observed["self_certification_enabled"] is True


def test_the_run_lapses_the_sponsor_at_its_term_end_and_suspends_its_live_catalogue(api, board_headers):
    """PRD 3.9: "Every provider whose `accreditation_status` is `ACCREDITED` or `PROBATIONARY` and whose `accreditation_term_end` is at or before `as_of` moves to `LAPSED` — with the course-suspension cascade on the `ACCREDITED` branch only, exactly as §3.1 sets out — and `providers_lapsed` counts them."
    PRD 3.1: "When a run observes an `ACCREDITED` sponsor whose `accreditation_term_end` is at or before the run's evaluation instant, the sponsor moves `ACCREDITED → LAPSED`, `self_certification_enabled` drops to false, the sponsor-suspension course cascade runs exactly as it does for `SUSPEND` (self-certified `APPROVED` courses whose `expires_at` is still in the future move to `SUSPENDED_PENDING_REVIEW`), and the run's `providers_lapsed` tally rises by one."
    PRD 3.1: "`risk_score_variant` follows the same fact from the other side, reading `SELF_CERTIFIED_WEIGHTING` exactly when the sponsor is `ACCREDITED` and `REVIEWED_WEIGHTING` in every other state including `APPLIED` and `DENIED`."

    Design: Corner/cross_cutting_complexity_layers/the_sweep_expires_courses_and_lapses_providers_only_when_the_clock_reaches_the_instant
    """
    provider, live, recorded = _accredited_sponsor_with_a_live_and_a_recorded_course()

    fx.set_clock(TERM_END_FROM_START)
    run = fx.run_sweep()
    assert run["sweep_number"] == 1
    assert _same_instant(run["as_of"], TERM_END_FROM_START)
    assert run["providers_lapsed"] == 1
    assert run["courses_expired"] == 1

    lapsed = fx.read_provider(provider["id"])
    assert lapsed["accreditation_status"] == "LAPSED"
    assert lapsed["self_certification_enabled"] is False
    assert lapsed["risk_score_variant"] == "REVIEWED_WEIGHTING"

    assert fx.read_course(live["id"])["status"] == "EXPIRED"
    assert fx.read_course(recorded["id"])["status"] == "SUSPENDED_PENDING_REVIEW"


def test_a_second_run_at_the_same_instant_finds_nothing_left_to_age(api, board_headers):
    """PRD 3.9: "Every course in `APPROVED` whose `expires_at` is at or before `as_of` moves to `EXPIRED`, and `courses_expired` counts them. Every provider whose `accreditation_status` is `ACCREDITED` or `PROBATIONARY` and whose `accreditation_term_end` is at or before `as_of` moves to `LAPSED` — with the course-suspension cascade on the `ACCREDITED` branch only, exactly as §3.1 sets out — and `providers_lapsed` counts them."
    PRD 3.9: "It is the sole producer of delinquency notices, administrative suspensions, late fees, course expiry and provider lapse — no interactive request creates any of those five things."

    Design: Corner/cross_cutting_complexity_layers/the_sweep_expires_courses_and_lapses_providers_only_when_the_clock_reaches_the_instant
    """
    provider, live, recorded = _accredited_sponsor_with_a_live_and_a_recorded_course()

    fx.set_clock(TERM_END_FROM_START)
    fx.run_sweep()

    again = fx.run_sweep()
    assert again["sweep_number"] == 2
    assert _same_instant(again["as_of"], TERM_END_FROM_START)
    assert again["courses_expired"] == 0
    assert again["providers_lapsed"] == 0
    assert again["delinquencies_issued"] == 0
    assert again["suspensions_issued"] == 0
    assert again["late_fees_assessed_cents"] == 0

    still_lapsed = fx.read_provider(provider["id"])
    assert still_lapsed["accreditation_status"] == "LAPSED"
    assert still_lapsed["self_certification_enabled"] is False
    assert fx.read_course(live["id"])["status"] == "EXPIRED"
    assert fx.read_course(recorded["id"])["status"] == "SUSPENDED_PENDING_REVIEW"


def _attorney_cycle_and_a_code_verified_webcast():
    """An accredited sponsor's five-hour webcast whose attendance is proved by the
    minted code, plus one attorney with an open two-year period.
    Returns (provider, course, attorney, cycle)."""
    provider = fx.create_accredited_provider(
        name="Riverbend Bar Institute", provider_type="BAR_ASSOCIATION"
    )
    course = fx.create_self_certified_course(
        provider,
        title="Live Webcast on the Rules of Evidence",
        delivery_format="LIVE_WEBCAST",
        total_minutes=300,
        presented_at="2026-06-15T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[f.credit_allocation_entry("GENERAL", 300)],
    )
    assert course["status"] == "APPROVED"
    assert course["attendance_code"] is not None
    assert course["verified_credit_record_count"] == 0

    attorney = fx.create_attorney(
        admission_date="2001-05-14T00:00:00Z",
        compliance_group="GROUP_1",
        principal_office_jurisdiction="ST",
    )
    cycle = fx.create_cycle(
        attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z"
    )
    assert cycle["required_total_minutes"] == 1800
    return provider, course, attorney, cycle


def _claim_the_webcast_with_its_code(api, course, attorney):
    payload = f.create_credit_record_payload(
        attorney["id"],
        course["id"],
        verification_method="ATTENDANCE_CODE",
        attendance_code=course["attendance_code"],
        attended_minutes=300,
        completion_date="2026-06-15T12:00:00Z",
        certificate_reference=None,
    )
    return api.create_credit_record(payload, make_attorney_headers(attorney["id"]))


def test_the_code_verified_filing_leaves_record_cycle_and_course_all_agreeing(api):
    """PRD 2.10: "Consistency in this system is immediate, not eventual: when one operation moves several rows, all of those moves land inside the same request, and the response reflects the finished state."
    PRD 3.5: "With `ATTENDANCE_CODE`, the supplied `attendance_code` must equal the course's minted code — an absent or mismatched code is `ERR_ATTENDANCE_CODE_INVALID` — and a matching code transitions the new record `PENDING_VERIFICATION → VERIFIED` in the same request, raising the course's `verified_credit_record_count` by one and re-running the owning cycle's credit application."
    PRD 3.6: "Each run rewrites the cycle's `earned_countable_minutes`, `earned_ethics_minutes`, `earned_technology_minutes`, `earned_bias_minutes` and `earned_live_minutes`, and rewrites `countable_minutes` on every credit record of that cycle."
    PRD 3.5: "A `LIVE_WEBCAST` course yields `LIVE` only when attendance was verified by `ATTENDANCE_CODE` or by `ROSTER` — the two methods that prove someone was actually watching in real time — and otherwise yields `ON_DEMAND`."
    PRD 2.3: "the credit-record list is ordered by `completion_date` ascending and then `created_at` ascending, which is exactly the order the credit-application algorithm consumes records in"

    Design: Corner/consistency_model/a_credit_filings_cascade_is_visible_to_every_read_that_follows_it
    """
    provider, course, attorney, cycle = _attorney_cycle_and_a_code_verified_webcast()

    record = validate_success(
        _claim_the_webcast_with_its_code(api, course, attorney), expected_status=201
    )
    assert record["status"] == "VERIFIED"
    assert record["cycle_id"] == cycle["id"]
    assert record["credited_general_minutes"] == 300
    assert record["credited_ethics_minutes"] == 0
    assert record["credited_minutes"] == 300
    assert record["countable_minutes"] == 300
    assert record["effective_format"] == "LIVE"
    assert record["source"] == "IN_STATE"

    settled_cycle = fx.read_cycle(cycle["id"])
    assert settled_cycle["earned_countable_minutes"] == 300
    assert settled_cycle["earned_live_minutes"] == 300
    assert settled_cycle["earned_ethics_minutes"] == 0
    assert settled_cycle["earned_technology_minutes"] == 0
    assert settled_cycle["earned_bias_minutes"] == 0
    assert settled_cycle["credit_status"] == "OPEN"
    assert settled_cycle["administrative_status"] == "GOOD_STANDING"

    assert fx.read_course(course["id"])["verified_credit_record_count"] == 1

    rows, meta = validate_paginated(
        api.list_credit_records(BOARD, params={"cycle_id": cycle["id"]})
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert rows[0]["id"] == record["id"]
    assert rows[0]["countable_minutes"] == 300
    assert rows[0]["status"] == "VERIFIED"


def test_the_summary_read_after_the_filing_reports_the_same_three_hundred_minutes(api):
    """PRD 3.6: "Because the provisional and final pictures can diverge sharply, the cycle summary read runs the algorithm *both* ways over the same stored data and returns the two results side by side without persisting anything."
    PRD 3.6: "Two counts close the payload: `records_counted` is the size of the provisional input set, and `records_excluded` is the number of the cycle's records in `REJECTED` or `VOIDED`."
    PRD 3.6: "The four shortfalls are then: the total shortfall, being `required_total_minutes` less the effective total, floored at zero; the ethics shortfall, being `required_ethics_minutes` less the effective ethics figure, floored at zero; the technology shortfall, being `required_technology_minutes` less `earned_technology_minutes`, floored at zero; and the bias shortfall, being `required_bias_minutes` less `earned_bias_minutes`, floored at zero."
    PRD 3.9: "Step five picks a base amount from the rounded hour count: zero hours gives 15000 cents, one to five hours gives 25000, six to fifteen gives 40000, and sixteen or more gives 60000. Step six adds a surcharge of 2500 cents for each deficient hour, counting at most twenty hours. Step seven caps the total: `amount_cents` is the smaller of 100000 cents and the base plus surcharge."

    Design: Corner/consistency_model/a_credit_filings_cascade_is_visible_to_every_read_that_follows_it
    """
    provider, course, attorney, cycle = _attorney_cycle_and_a_code_verified_webcast()
    validate_success(
        _claim_the_webcast_with_its_code(api, course, attorney), expected_status=201
    )

    summary = validate_success(
        api.get_cycle_summary(cycle["id"], make_attorney_headers(attorney["id"]))
    )
    assert summary["cycle_id"] == cycle["id"]
    assert summary["credit_status"] == "OPEN"
    assert summary["administrative_status"] == "GOOD_STANDING"
    assert summary["required_total_minutes"] == 1800
    assert summary["required_ethics_minutes"] == 180
    assert summary["required_technology_minutes"] == 60
    assert summary["required_bias_minutes"] == 120

    assert summary["provisional_total_minutes"] == 300
    assert summary["provisional_live_minutes"] == 300
    assert summary["provisional_ethics_minutes"] == 0
    assert summary["provisional_technology_minutes"] == 0
    assert summary["provisional_bias_minutes"] == 0
    assert summary["provisional_deficiency_total_minutes"] == 1500
    assert summary["provisional_deficiency_ethics_minutes"] == 180

    assert summary["projected_final_total_minutes"] == 300
    assert summary["projected_final_live_minutes"] == 300
    assert summary["projected_final_ethics_minutes"] == 0
    assert summary["projected_final_technology_minutes"] == 0
    assert summary["projected_final_bias_minutes"] == 0
    assert summary["projected_final_deficiency_total_minutes"] == 1500
    assert summary["projected_final_deficiency_ethics_minutes"] == 180
    assert summary["projected_final_deficiency_technology_minutes"] == 60
    assert summary["projected_final_deficiency_bias_minutes"] == 120

    assert summary["self_study_used_minutes"] == 0
    assert summary["on_demand_used_minutes"] == 0
    assert summary["nonlive_used_minutes"] == 0
    assert summary["reciprocity_used_minutes"] == 0
    assert summary["carryover_in_general_minutes"] == 0
    assert summary["carryover_in_ethics_minutes"] == 0
    assert summary["records_counted"] == 1
    assert summary["records_excluded"] == 0
    assert summary["projected_late_fee_cents"] == 100000

    unchanged = fx.read_cycle(cycle["id"])
    assert unchanged["earned_countable_minutes"] == 300
    assert unchanged["earned_live_minutes"] == 300
    assert unchanged["credit_status"] == "OPEN"

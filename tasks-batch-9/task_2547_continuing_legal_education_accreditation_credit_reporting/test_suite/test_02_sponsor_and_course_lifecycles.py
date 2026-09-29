"""Sponsor standing, the course pathway it decides, and complaint dispositions.

Every test builds its own state from an empty register: the database is wiped
and the server restarted before each one, and the logical clock reads
2026-08-01T00:00:00Z at the start of every test (PRD 2.4).
"""
import datetime

from test_helpers import (
    api_client,
    fixtures,
    validate_error,
    validate_paginated,
)

CLOCK_START = "2026-08-01T00:00:00Z"
TERM_END_FROM_CLOCK_START = "2028-08-01T00:00:00Z"


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


def test_grant_probationary_stamps_the_two_year_term_and_bills_the_annual_fee():
    """`GRANT_PROBATIONARY` on an `APPLIED` sponsor moves it `APPLIED → PROBATIONARY` regardless of `provider_type`.
    It stamps the same two-year term into `accreditation_term_start` and `accreditation_term_end`, leaves `self_certification_enabled` false, raises the same `PROVIDER_ANNUAL` assessment for `annual_fee_cents`, and re-scores the sponsor under `REVIEWED_WEIGHTING`.
    The grant stamps `accreditation_term_start` with the current logical instant and `accreditation_term_end` with that instant plus 24 months, flips `self_certification_enabled` to true, raises a `PROVIDER_ANNUAL` assessment against the sponsor for exactly its `annual_fee_cents`, and re-scores it under the self-certified weighting, writing `risk_score_variant` as `SELF_CERTIFIED_WEIGHTING`.
    An `annual_fee_cents` figure may be supplied and must be zero or greater; when it is omitted the board's standard annual accreditation fee of 120000 cents — twelve hundred dollars — is used.
    Most resources also carry an `updated_at` timestamp, refreshed on every mutation of that row, and an integer `version` that starts at 1 on creation and increases by exactly 1 on every mutation of that row — including mutations the row did not ask for, such as a counter bump driven by a cascade from another entity.

    Design: Corner/state_machines/grant_probationary_starts_the_term_assesses_the_fee_and_forces_individual_approval
    """
    provider = fixtures.create_provider(
        name="Probationary Training Co",
        provider_type="COMMERCIAL",
        annual_fee_cents=80000,
    )
    assert provider["accreditation_status"] == "APPLIED"
    assert provider["version"] == 1

    granted = fixtures.accreditation_action(
        provider["id"], "GRANT_PROBATIONARY", provider["version"]
    )

    assert granted["accreditation_status"] == "PROBATIONARY"
    assert granted["version"] == 2
    assert_same_instant(
        granted["accreditation_term_start"], CLOCK_START, "accreditation_term_start"
    )
    assert_same_instant(
        granted["accreditation_term_end"],
        TERM_END_FROM_CLOCK_START,
        "accreditation_term_end",
    )
    assert granted["self_certification_enabled"] is False
    assert granted["risk_score_variant"] == "REVIEWED_WEIGHTING"

    fees, meta = board_fee_page(provider_id=provider["id"])
    assert meta["total_count"] == 1, (
        f"the probationary grant must raise exactly one assessment, got {fees}"
    )
    assert fees[0]["fee_type"] == "PROVIDER_ANNUAL"
    assert fees[0]["amount_cents"] == 80000
    assert fees[0]["status"] == "ASSESSED"


def test_a_probationary_sponsors_next_course_takes_the_individual_approval_pathway():
    """It stamps the same two-year term into `accreditation_term_start` and `accreditation_term_end`, leaves `self_certification_enabled` false, raises the same `PROVIDER_ANNUAL` assessment for `annual_fee_cents`, and re-scores the sponsor under `REVIEWED_WEIGHTING`.
    It is `PROVIDER_ACCREDITED` when `provider_id` is supplied *and* that sponsor's `self_certification_enabled` is true at the moment of creation; in every other case — no sponsor at all, or a sponsor that is not fully accredited — it is `INDIVIDUAL_APPROVAL`.
    Every other course is created in `PENDING_APPROVAL` and stays there until an application is decided; if it names a sponsor, only that sponsor's `courses_total_count` rises.

    Design: Corner/state_machines/grant_probationary_starts_the_term_assesses_the_fee_and_forces_individual_approval
    """
    provider = fixtures.create_provider(
        name="Probationary Training Co", provider_type="COMMERCIAL"
    )
    provider = fixtures.accreditation_action(
        provider["id"], "GRANT_PROBATIONARY", provider["version"]
    )
    assert provider["self_certification_enabled"] is False

    course = fixtures.create_self_certified_course(
        provider,
        title="Contract Drafting Intensive",
        delivery_format="LIVE_WEBCAST",
        total_minutes=120,
        presented_at="2026-09-09T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[{"category": "GENERAL", "minutes": 120}],
    )

    assert course["status"] == "PENDING_APPROVAL"
    assert course["approval_pathway"] == "INDIVIDUAL_APPROVAL"

    refreshed = fixtures.read_provider(provider["id"])
    assert refreshed["courses_total_count"] == 1
    assert refreshed["courses_self_certified_count"] == 0


def test_grant_full_on_a_commercial_applicant_is_refused_by_its_type_gate():
    """`GRANT_FULL` on an `APPLIED` sponsor moves it `APPLIED → ACCREDITED`, but only where the sponsor is presumptively trustworthy: its `provider_type` must be `BAR_ASSOCIATION`, `LAW_SCHOOL` or `GOVERNMENT`.
    A `COMMERCIAL` or `LAW_FIRM` sponsor cannot be granted full accreditation from `APPLIED` at all, and the attempt is an `ERR_INVALID_STATE_TRANSITION`.
    The addressed resource is in a state from which the requested trigger is declared, and every cross-entity state precondition of that transition holds — otherwise `ERR_INVALID_STATE_TRANSITION` (409).
    A new sponsor begins in `APPLIED` with `self_certification_enabled` false, a `risk_score` of 0.0, a `risk_score_variant` of `REVIEWED_WEIGHTING`, `accreditation_term_start` and `accreditation_term_end` both null, `probation_reason` null, and every counter at zero.
    `GRANT_PROBATIONARY` on an `APPLIED` sponsor moves it `APPLIED → PROBATIONARY` regardless of `provider_type`.

    Design: Corner/state_machines/grant_full_on_a_commercial_applicant_is_refused_by_its_type_precondition
    """
    commercial = fixtures.create_provider(
        name="Vendor CLE LLC", provider_type="COMMERCIAL"
    )
    government = fixtures.create_provider(
        name="State Judicial Institute", provider_type="GOVERNMENT"
    )

    refused = api_client.provider_accreditation_action(
        commercial["id"],
        {"action": "GRANT_FULL", "expected_provider_version": commercial["version"]},
        fixtures.BOARD,
    )
    validate_error(refused, "ERR_INVALID_STATE_TRANSITION")

    still_applied = fixtures.read_provider(commercial["id"])
    assert still_applied["accreditation_status"] == "APPLIED"
    assert still_applied["version"] == 1
    assert still_applied["accreditation_term_start"] is None
    _rows, meta = board_fee_page(provider_id=commercial["id"])
    assert meta["total_count"] == 0, "a refused grant must raise no assessment"

    accredited = fixtures.accreditation_action(
        government["id"], "GRANT_FULL", government["version"]
    )
    assert accredited["accreditation_status"] == "ACCREDITED"
    assert accredited["self_certification_enabled"] is True
    assert accredited["risk_score_variant"] == "SELF_CERTIFIED_WEIGHTING"

    probationary = fixtures.accreditation_action(
        commercial["id"], "GRANT_PROBATIONARY", commercial["version"]
    )
    assert probationary["accreditation_status"] == "PROBATIONARY"
    assert probationary["version"] == 2


def test_a_denied_sponsor_is_terminal_so_later_accreditation_actions_are_refused():
    """`DENY` on an `APPLIED` sponsor moves it `APPLIED → DENIED`, recording the supplied note in `probation_reason`.
    `DENIED` is the sponsor's only terminal state; no action leads out of it.
    The addressed resource is in a state from which the requested trigger is declared, and every cross-entity state precondition of that transition holds — otherwise `ERR_INVALID_STATE_TRANSITION` (409).
    `risk_score_variant` follows the same fact from the other side, reading `SELF_CERTIFIED_WEIGHTING` exactly when the sponsor is `ACCREDITED` and `REVIEWED_WEIGHTING` in every other state including `APPLIED` and `DENIED`.

    Design: Corner/state_machines/a_denied_provider_is_terminal_so_every_later_accreditation_action_is_refused
    """
    provider = fixtures.create_provider(
        name="Rejected Seminars Inc", provider_type="COMMERCIAL"
    )
    denied = fixtures.accreditation_action(
        provider["id"],
        "DENY",
        provider["version"],
        probation_reason="Curriculum did not meet minimum standards.",
    )
    assert denied["accreditation_status"] == "DENIED"
    assert denied["probation_reason"] == "Curriculum did not meet minimum standards."
    assert denied["version"] == 2
    assert denied["self_certification_enabled"] is False
    assert denied["risk_score_variant"] == "REVIEWED_WEIGHTING"

    for action in ("GRANT_PROBATIONARY", "RENEW"):
        refused = api_client.provider_accreditation_action(
            provider["id"],
            {"action": action, "expected_provider_version": denied["version"]},
            fixtures.BOARD,
        )
        validate_error(refused, "ERR_INVALID_STATE_TRANSITION")

    after = fixtures.read_provider(provider["id"])
    assert after["accreditation_status"] == "DENIED"
    assert after["version"] == 2, "a refused action must not mutate the sponsor row"
    _rows, meta = board_fee_page(provider_id=provider["id"])
    assert meta["total_count"] == 0


def test_substantiate_on_a_received_complaint_is_refused_before_open_review():
    """`SUBSTANTIATE` is available only from `UNDER_REVIEW` — substantiating a complaint nobody has opened for review is `ERR_INVALID_STATE_TRANSITION` — and likewise requires a `disposition_reason`.
    The complaint is created in `RECEIVED` with `escalated` false, and the filer is recorded in two fields — `complainant_role`, which takes the value `ATTORNEY` or `BOARD_ADMIN` (note that these are the recorded enumeration labels, not the header spellings of the roles), and `complainant_user_id`, which holds the acting `X-User-ID`.
    Against a provider, the provider's `substantiated_complaint_count` rises by one, its `risk_score` is recomputed, and the provider itself moves `ACCREDITED → PROBATIONARY`.

    Design: Corner/state_machines/substantiate_on_a_received_complaint_is_refused_before_open_review
    """
    provider = fixtures.create_provider(
        name="Beacon CLE Society", provider_type="BAR_ASSOCIATION"
    )
    provider = fixtures.accreditation_action(
        provider["id"], "GRANT_FULL", provider["version"]
    )
    complaint = fixtures.file_complaint(
        "PROVIDER",
        provider["id"],
        allegation="Sign-in sheets were pre-filled before the session began.",
        allegation_category="ATTENDANCE_FRAUD",
    )
    assert complaint["status"] == "RECEIVED"
    assert complaint["escalated"] is False
    assert complaint["complainant_role"] == "BOARD_ADMIN"

    refused = api_client.complaint_disposition(
        complaint["id"],
        {
            "action": "SUBSTANTIATE",
            "disposition_reason": "Investigator confirmed the pre-filled sheets.",
        },
        fixtures.BOARD,
    )
    validate_error(refused, "ERR_INVALID_STATE_TRANSITION")

    unchanged = fixtures.read_complaint(complaint["id"])
    assert unchanged["status"] == "RECEIVED"
    assert unchanged["version"] == complaint["version"]

    sponsor = fixtures.read_provider(provider["id"])
    assert sponsor["accreditation_status"] == "ACCREDITED"
    assert sponsor["substantiated_complaint_count"] == 0
    assert sponsor["self_certification_enabled"] is True


def test_open_review_then_substantiate_reverts_the_accredited_sponsor_to_probationary():
    """`OPEN_REVIEW` moves `RECEIVED → UNDER_REVIEW` and does nothing else.
    Against a provider, the provider's `substantiated_complaint_count` rises by one, its `risk_score` is recomputed, and the provider itself moves `ACCREDITED → PROBATIONARY`.
    Either way `self_certification_enabled` drops to false, `risk_score_variant` becomes `REVIEWED_WEIGHTING` with the score recomputed under it, and `probation_reason` records the audit or complaint that caused the reversion.

    Design: Corner/state_machines/substantiate_on_a_received_complaint_is_refused_before_open_review
    """
    provider = fixtures.create_provider(
        name="Beacon CLE Society", provider_type="BAR_ASSOCIATION"
    )
    provider = fixtures.accreditation_action(
        provider["id"], "GRANT_FULL", provider["version"]
    )
    complaint = fixtures.file_complaint(
        "PROVIDER",
        provider["id"],
        allegation="Sign-in sheets were pre-filled before the session began.",
        allegation_category="ATTENDANCE_FRAUD",
    )

    opened = fixtures.dispose_complaint(complaint["id"], "OPEN_REVIEW", "board-admin-1")
    assert opened["status"] == "UNDER_REVIEW"
    assert opened["escalated"] is False
    mid_sponsor = fixtures.read_provider(provider["id"])
    assert mid_sponsor["accreditation_status"] == "ACCREDITED"
    assert mid_sponsor["substantiated_complaint_count"] == 0

    substantiated = fixtures.dispose_complaint(
        complaint["id"],
        "SUBSTANTIATE",
        "board-admin-1",
        disposition_reason="Investigator confirmed the pre-filled sheets.",
    )
    assert substantiated["status"] == "SUBSTANTIATED"

    sponsor = fixtures.read_provider(provider["id"])
    assert sponsor["substantiated_complaint_count"] == 1
    assert sponsor["accreditation_status"] == "PROBATIONARY"
    assert sponsor["self_certification_enabled"] is False
    assert sponsor["risk_score_variant"] == "REVIEWED_WEIGHTING"
    assert sponsor["probation_reason"] is not None, (
        "probation_reason must record the complaint that caused the reversion"
    )


def test_a_second_open_review_on_the_same_complaint_is_refused():
    """`OPEN_REVIEW` moves `RECEIVED → UNDER_REVIEW` and does nothing else.
    The addressed resource is in a state from which the requested trigger is declared, and every cross-entity state precondition of that transition holds — otherwise `ERR_INVALID_STATE_TRANSITION` (409).
    `DISMISS` is available from either `RECEIVED` or `UNDER_REVIEW`, requires a `disposition_reason`, and has no side effects beyond recording it.

    Design: Corner/state_machines/a_second_open_review_on_the_same_complaint_is_refused
    """
    provider = fixtures.create_provider(
        name="Disputed Fees Institute", provider_type="COMMERCIAL"
    )
    complaint = fixtures.file_complaint(
        "PROVIDER",
        provider["id"],
        allegation="The registration fee charged did not match the published schedule.",
        allegation_category="FEE_DISPUTE",
    )
    opened = fixtures.dispose_complaint(complaint["id"], "OPEN_REVIEW", "board-admin-1")
    assert opened["status"] == "UNDER_REVIEW"

    replayed = api_client.complaint_disposition(
        complaint["id"], {"action": "OPEN_REVIEW"}, fixtures.BOARD
    )
    validate_error(replayed, "ERR_INVALID_STATE_TRANSITION")

    after = fixtures.read_complaint(complaint["id"])
    assert after["status"] == "UNDER_REVIEW"
    assert after["escalated"] is False
    assert after["version"] == opened["version"], (
        "a refused replay must not mutate the complaint row"
    )

    dismissed = fixtures.dispose_complaint(
        complaint["id"],
        "DISMISS",
        "board-admin-1",
        disposition_reason="The published schedule matched the charge.",
    )
    assert dismissed["status"] == "DISMISSED"


def build_sponsor_with_in_window_and_lapsed_shelf_courses():
    """An accredited sponsor holding one on-demand course whose three-year shelf
    life is still open and one self-study course whose shelf life has closed."""
    provider = fixtures.create_accredited_provider(
        name="Highpoint CLE Trust", provider_type="BAR_ASSOCIATION"
    )
    in_window = fixtures.create_self_certified_course(
        provider,
        title="On Demand Evidence Review",
        delivery_format="ON_DEMAND",
        total_minutes=300,
        presented_at="2026-05-05T00:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[{"category": "GENERAL", "minutes": 300}],
    )
    shelf_closed = fixtures.create_self_certified_course(
        provider,
        title="Archived Self Study Packet",
        delivery_format="SELF_STUDY",
        total_minutes=240,
        presented_at="2023-01-01T00:00:00Z",
        attendance_verification_method="AFFIRMATION_ONLY",
        credit_allocations=[{"category": "GENERAL", "minutes": 240}],
    )
    return provider, in_window, shelf_closed


def test_sponsor_suspension_suspends_only_the_course_still_inside_its_window():
    """Both branches set `self_certification_enabled` to false and both run the sponsor-suspension cascade: every course of that sponsor that is currently `APPROVED`, was approved through the self-certification pathway, and has not yet reached its `expires_at` moves `APPROVED → SUSPENDED_PENDING_REVIEW`.
    For `ON_DEMAND` and `SELF_STUDY` it is `presented_at` plus 36 months, three years of shelf life for recorded material.
    A course on the self-certification pathway is presumptively approved: it is created and immediately transitions `PENDING_APPROVAL → APPROVED` in the same request, its sponsor's `courses_self_certified_count` and `courses_total_count` each rise by one, and the sponsor's `risk_score` is recomputed because the denominator behind its findings rate has changed.
    `risk_score_variant` follows the same fact from the other side, reading `SELF_CERTIFIED_WEIGHTING` exactly when the sponsor is `ACCREDITED` and `REVIEWED_WEIGHTING` in every other state including `APPLIED` and `DENIED`.

    Design: Corner/state_machines/provider_suspension_cascades_only_into_self_certified_courses_still_inside_their_window
    """
    provider, in_window, shelf_closed = build_sponsor_with_in_window_and_lapsed_shelf_courses()
    assert in_window["status"] == "APPROVED"
    assert in_window["approval_pathway"] == "PROVIDER_ACCREDITED"
    assert_same_instant(in_window["expires_at"], "2029-05-05T00:00:00Z", "expires_at")
    assert shelf_closed["status"] == "APPROVED"
    assert_same_instant(shelf_closed["expires_at"], "2026-01-01T00:00:00Z", "expires_at")

    live = fixtures.read_provider(provider["id"])
    suspended = fixtures.accreditation_action(
        provider["id"], "SUSPEND", live["version"]
    )

    assert suspended["accreditation_status"] == "SUSPENDED"
    assert suspended["self_certification_enabled"] is False
    assert suspended["risk_score_variant"] == "REVIEWED_WEIGHTING"
    assert suspended["courses_total_count"] == 2
    assert suspended["courses_self_certified_count"] == 2

    assert fixtures.read_course(in_window["id"])["status"] == "SUSPENDED_PENDING_REVIEW"
    assert fixtures.read_course(shelf_closed["id"])["status"] == "APPROVED", (
        "a course whose expires_at has already been reached is outside the cascade"
    )


def test_sponsor_suspension_rejects_the_pending_claim_and_recomputes_the_period():
    """Sponsor suspension or lapse moves a self-certified `APPROVED` course whose `expires_at` is still in the future to `SUSPENDED_PENDING_REVIEW`, and that move itself rejects every credit record for that course still awaiting verification, stamping each with a `void_reason` of `SPONSOR_NOT_IN_GOOD_STANDING` and re-running the owning cycle's credit application.
    The **provisional** variant includes the cycle's records in `PENDING_VERIFICATION` and `VERIFIED`.
    Records in `REJECTED` or `VOIDED` participate in neither variant, ever.
    Every credit record of the cycle that was *not* in this variant's input set has its `countable_minutes` rewritten to zero, so the persisted per-record figures always reconcile against the cycle's earned totals for whichever variant last ran.

    Design: Corner/state_machines/provider_suspension_cascades_only_into_self_certified_courses_still_inside_their_window
    """
    provider, in_window, _shelf_closed = build_sponsor_with_in_window_and_lapsed_shelf_courses()
    attorney, cycle = fixtures.setup_attorney_with_cycle(
        period_start="2026-01-01T00:00:00Z",
        period_end="2028-01-01T00:00:00Z",
        attorney_overrides={
            "full_name": "Ines Duarte",
            "admission_date": "2006-03-01T00:00:00Z",
        },
    )
    record = fixtures.file_credit_record(
        attorney,
        in_window["id"],
        verification_method="CERTIFICATE",
        attended_minutes=300,
        completion_date="2026-06-06T00:00:00Z",
    )
    assert record["status"] == "PENDING_VERIFICATION"
    assert record["credited_minutes"] == 300
    assert fixtures.read_cycle(cycle["id"])["earned_countable_minutes"] == 300

    live = fixtures.read_provider(provider["id"])
    fixtures.accreditation_action(provider["id"], "SUSPEND", live["version"])

    rejected = fixtures.read_credit_record(record["id"])
    assert rejected["status"] == "REJECTED"
    assert rejected["void_reason"] == "SPONSOR_NOT_IN_GOOD_STANDING"
    assert rejected["countable_minutes"] == 0
    assert fixtures.read_cycle(cycle["id"])["earned_countable_minutes"] == 0


def build_suspended_sponsor_with_a_rejected_claim():
    """The state a suspension leaves behind: a suspended sponsor, its in-window
    on-demand course sitting in SUSPENDED_PENDING_REVIEW, and the credit record
    the cascade rejected. Returns (provider, course, attorney, cycle, record)."""
    provider = fixtures.create_accredited_provider(
        name="Highpoint CLE Trust", provider_type="BAR_ASSOCIATION"
    )
    course = fixtures.create_self_certified_course(
        provider,
        title="On Demand Evidence Review",
        delivery_format="ON_DEMAND",
        total_minutes=300,
        presented_at="2026-05-05T00:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[{"category": "GENERAL", "minutes": 300}],
    )
    attorney, cycle = fixtures.setup_attorney_with_cycle(
        period_start="2026-01-01T00:00:00Z",
        period_end="2028-01-01T00:00:00Z",
        attorney_overrides={
            "full_name": "Noel Bright",
            "admission_date": "2006-03-01T00:00:00Z",
        },
    )
    record = fixtures.file_credit_record(
        attorney,
        course["id"],
        verification_method="CERTIFICATE",
        attended_minutes=300,
        completion_date="2026-06-06T00:00:00Z",
    )
    live = fixtures.read_provider(provider["id"])
    suspended = fixtures.accreditation_action(provider["id"], "SUSPEND", live["version"])
    return suspended, course, attorney, cycle, record


def test_reinstatement_restores_the_course_but_never_the_rejected_credit_record():
    """`REINSTATE` moves a `SUSPENDED` sponsor to `PROBATIONARY` — never directly back to `ACCREDITED` — and requires that the sponsor have no `AUDIT_SANCTION` assessment still in `ASSESSED`; an unpaid sanction fee makes it an `ERR_INVALID_STATE_TRANSITION`.
    Reinstatement runs the compensation cascade: every course of that sponsor in `SUSPENDED_PENDING_REVIEW` whose `expires_at` is still in the future returns to `APPROVED`.
    Note carefully that no credit records are compensated by either the reinstatement or the renewal cascade — records rejected while the sponsor was out of standing stay rejected and must be re-filed.
    Throughout all of this, `self_certification_enabled` is not an independent switch: it is true exactly when `accreditation_status` is `ACCREDITED`, and false in every other state.

    Design: Corner/state_machines/provider_reinstatement_restores_the_course_but_never_the_rejected_credit_record
    """
    suspended, course, _attorney, _cycle, record = build_suspended_sponsor_with_a_rejected_claim()
    assert suspended["accreditation_status"] == "SUSPENDED"
    assert fixtures.read_course(course["id"])["status"] == "SUSPENDED_PENDING_REVIEW"
    assert fixtures.read_credit_record(record["id"])["status"] == "REJECTED"

    reinstated = fixtures.accreditation_action(
        suspended["id"], "REINSTATE", suspended["version"]
    )

    assert reinstated["accreditation_status"] == "PROBATIONARY"
    assert reinstated["self_certification_enabled"] is False
    assert fixtures.read_course(course["id"])["status"] == "APPROVED"

    still_rejected = fixtures.read_credit_record(record["id"])
    assert still_rejected["status"] == "REJECTED"
    assert still_rejected["void_reason"] == "SPONSOR_NOT_IN_GOOD_STANDING"
    assert still_rejected["countable_minutes"] == 0


def test_the_claim_may_be_refiled_after_reinstatement_because_the_rejection_is_terminal():
    """Note carefully that no credit records are compensated by either the reinstatement or the renewal cascade — records rejected while the sponsor was out of standing stay rejected and must be re-filed.
    Finally, an attorney may hold at most one live claim per course: a second claim for the same attorney and course while an earlier one is still `PENDING_VERIFICATION` or `VERIFIED` is `ERR_DUPLICATE_CREDIT_RECORD`.
    A record's `status` is therefore one of `PENDING_VERIFICATION`, `VERIFIED`, `REJECTED` or `VOIDED`, of which the last two are terminal, and `void_reason` carries the text recorded whenever a record is rejected or voided.
    The **provisional** variant includes the cycle's records in `PENDING_VERIFICATION` and `VERIFIED`.

    Design: Corner/state_machines/provider_reinstatement_restores_the_course_but_never_the_rejected_credit_record
    """
    suspended, course, attorney, cycle, first_record = build_suspended_sponsor_with_a_rejected_claim()
    fixtures.accreditation_action(suspended["id"], "REINSTATE", suspended["version"])
    assert fixtures.read_course(course["id"])["status"] == "APPROVED"

    refiled = fixtures.file_credit_record(
        attorney,
        course["id"],
        verification_method="CERTIFICATE",
        attended_minutes=300,
        completion_date="2026-06-06T00:00:00Z",
    )

    assert refiled["id"] != first_record["id"]
    assert refiled["status"] == "PENDING_VERIFICATION"
    assert refiled["credited_minutes"] == 300
    assert fixtures.read_credit_record(first_record["id"])["status"] == "REJECTED"
    assert fixtures.read_cycle(cycle["id"])["earned_countable_minutes"] == 300

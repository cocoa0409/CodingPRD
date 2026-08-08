"""Public complaints, reportable infections and the two risk-score variants."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_investigation,
    advance_notification,
    assert_complaint,
    assert_infection_report,
    assert_instant_equals,
    cite_violation,
    compliance_summary,
    create_active_artist,
    create_permitted_establishment,
    create_screening_infection_report,
    file_complaint,
    file_infection_report,
    read_artist,
    read_establishment,
    register_establishment,
    start_inspection_at,
    transition_complaint,
    validate_error,
    validate_paginated,
    validate_success,
)

HO = TEST_USERS["health_officer_headers"]
PUBLIC = TEST_USERS["public_user_headers"]

THREE_NONCRITICAL = (
    ("STER_004", "Autoclave log gap."),
    ("HAND_002", "Soap dispenser empty."),
    ("SIGN_001", "Permit not posted."),
)


def test_triage_books_a_complaint_visit_and_reopens_are_capped_at_two(api):
    """PRD §3.7: "The complaint opens in status `RECEIVED` with `received_at` stamped
    from the logical clock, `reopen_count` at zero, `triage_overdue` false, and
    `triage_due_at` computed as exactly 5 days after `received_at` — the department's
    self-imposed triage service level."
    PRD §3.7: "Triage also books the field response: an inspection is created for the
    same establishment with `inspection_type` `COMPLAINT`, status `SCHEDULED`,
    `source_complaint_id` pointing back at this complaint, `scheduled_start_at` set to
    24 hours after the current logical-clock instant and `scheduled_end_at` set 120
    minutes after that start."
    PRD §3.7: "`REOPEN` is admissible only from `UNSUBSTANTIATED`, drives
    `UNSUBSTANTIATED → INVESTIGATING`, increments `reopen_count` by one and recomputes
    `risk_score` and `operating_posture`; it is permitted only while `reopen_count` is
    strictly below 2, so a dismissed complaint can be revived at most twice before the
    file is closed for good, and a further attempt is rejected with
    `ERR_COMPLAINT_REOPEN_LIMIT` (HTTP 409)."

    Design: Corner/state_machines/complaint_triage_spawns_inspection_and_reopen_limit_is_enforced
    """
    establishment = register_establishment(
        name="Complaint Ink", street_address="14 Fourteenth St"
    )
    complaint = file_complaint(
        establishment["id"],
        complainant_contact="walker@example.com",
        category="INJURY",
        narrative="Piercing site became inflamed.",
    )
    assert_complaint(complaint)
    assert_instant_equals(
        complaint["triage_due_at"], "2026-05-06T00:00:00Z", "triage_due_at"
    )

    triaged = transition_complaint(complaint["id"], "TRIAGE")
    assert triaged["status"] == "TRIAGED"
    assert triaged["triage_overdue"] is False

    rows, meta = validate_paginated(
        api.list_inspections(HO, params={"source_complaint_id": complaint["id"]})
    )
    assert meta["total_count"] == 1
    spawned = rows[0]
    assert spawned["inspection_type"] == "COMPLAINT"
    assert_instant_equals(
        spawned["scheduled_start_at"], "2026-05-02T00:00:00Z", "scheduled_start_at"
    )
    assert_instant_equals(
        spawned["scheduled_end_at"], "2026-05-02T02:00:00Z", "scheduled_end_at"
    )

    transition_complaint(complaint["id"], "INVESTIGATE")
    transition_complaint(complaint["id"], "UNSUBSTANTIATE")
    transition_complaint(complaint["id"], "REOPEN")
    transition_complaint(complaint["id"], "UNSUBSTANTIATE")
    second_reopen = transition_complaint(complaint["id"], "REOPEN")
    assert second_reopen["reopen_count"] == 2
    transition_complaint(complaint["id"], "UNSUBSTANTIATE")

    third = api.transition_complaint(complaint["id"], {"action": "REOPEN"}, HO)
    validate_error(third, ApiErrorId.ERR_COMPLAINT_REOPEN_LIMIT.value)
    assert third.status_code == 409

    stored = validate_success(api.get_complaint(complaint["id"], HO))
    assert stored["status"] == "UNSUBSTANTIATED"
    assert stored["reopen_count"] == 2


def test_notification_waiver_and_investigation_reopen_limits(api):
    """PRD §3.7: "`MARK_NOT_REQUIRED` is also admissible only from `PENDING` and drives
    `PENDING → NOT_REQUIRED`, but only for a report whose `infection_type` is `OTHER`;
    every other clinical category is registry-reportable and cannot be waived, so the
    attempt is rejected with `ERR_NOTIFICATION_NOT_WAIVABLE` (HTTP 409)."
    PRD §3.7: "`REOPEN` is admissible only from `RULED_OUT`, drives `RULED_OUT →
    SCREENING`, increments `reopen_count` by one and recomputes `risk_score`; it is
    permitted only while `reopen_count` is strictly below 2, and a further attempt is
    rejected with `ERR_INFECTION_REOPEN_LIMIT` (HTTP 409)."

    Design: Corner/validations/infection_notification_waiver_and_reopen_limit_rejected
    """
    establishment = register_establishment(
        name="Report Limits Ink", street_address="39 Thirtyninth St",
        establishment_type="PIERCING",
    )
    report = file_infection_report(
        establishment["id"],
        reporter_contact="clinic@example.com",
        infection_type="MRSA",
        procedure_date="2026-04-10T00:00:00Z",
        symptom_onset_at="2026-04-18T00:00:00Z",
    )
    assert_infection_report(report)

    waiver = api.advance_infection_notification(
        report["id"], {"action": "MARK_NOT_REQUIRED"}, HO
    )
    validate_error(waiver, ApiErrorId.ERR_NOTIFICATION_NOT_WAIVABLE.value)
    assert waiver.status_code == 409

    advance_investigation(report["id"], "SCREEN")
    advance_investigation(report["id"], "RULE_OUT")
    advance_investigation(report["id"], "REOPEN")
    advance_investigation(report["id"], "RULE_OUT")
    second_reopen = advance_investigation(report["id"], "REOPEN")
    assert second_reopen["reopen_count"] == 2
    advance_investigation(report["id"], "RULE_OUT")

    third = api.advance_infection_investigation(report["id"], {"action": "REOPEN"}, HO)
    validate_error(third, ApiErrorId.ERR_INFECTION_REOPEN_LIMIT.value)
    assert third.status_code == 409

    stored = validate_success(api.get_infection_report(report["id"], HO))
    assert stored["investigation_status"] == "RULED_OUT"
    assert stored["notification_status"] == "PENDING"
    assert stored["reopen_count"] == 2


def test_audit_variant_counts_the_in_flight_complaint_that_provisional_ignores(api):
    """PRD §3.7: "complaints under triage or investigation and infection reports under
    screening are excluded entirely, so only `SUBSTANTIATED` complaints and `CONFIRMED`
    reports contribute."
    PRD §3.7: "variant adds an in-flight term to the same six: 5 points for each
    complaint of this establishment sitting in `TRIAGED` or `INVESTIGATING`, plus 10
    points for each infection report sitting in `investigation_status` `SCREENING`,
    both counted over the same closed 365-day window, with the total still capped at
    100."

    Design: Difficulty/dual_variant_calc/risk_score_provisional_excludes_in_flight_complaint_audit_includes
    """
    establishment = create_permitted_establishment(
        name="Ink Alley", street_address="12 Main St"
    )
    complaint = file_complaint(
        establishment["id"],
        complainant_contact="citizen@example.com",
        category="SANITATION",
        narrative="Floor was visibly dirty during my session.",
    )
    triaged = transition_complaint(complaint["id"], "TRIAGE")
    assert triaged["status"] == "TRIAGED"

    summary = compliance_summary(establishment["id"])
    assert summary["risk_score_provisional"] == 25
    assert summary["risk_score_audit"] == 30
    assert summary["risk_score_audit"] - summary["risk_score_provisional"] == 5, (
        "exactly the in-flight weight of the one TRIAGED complaint"
    )
    assert summary["operating_posture"] == "OPEN"


def test_only_the_provisional_risk_figure_is_persisted(api):
    """PRD §3.7: "The provisional variant is the one persisted to `risk_score`, the one
    that drives `operating_posture`, and the one tested against the suspension
    breakpoint of 80."
    PRD §3.7: "The audit variant is never persisted and never gates any transition; it
    exists only as a departmental early-warning read."

    Design: Difficulty/dual_variant_calc/risk_score_provisional_excludes_in_flight_complaint_audit_includes
    """
    establishment = create_permitted_establishment(
        name="Ink Alley Two", street_address="13 Main St"
    )
    complaint = file_complaint(
        establishment["id"],
        complainant_contact="citizen@example.com",
        category="SANITATION",
        narrative="Floor was visibly dirty during my session.",
    )
    transition_complaint(complaint["id"], "TRIAGE")

    summary = compliance_summary(establishment["id"])
    assert summary["risk_score_audit"] == 30

    stored = read_establishment(establishment["id"])
    assert stored["risk_score"] == 25, (
        f"Only the provisional figure is persisted, got {stored['risk_score']}"
    )
    assert stored["operating_posture"] == "OPEN"

    complaint_row = validate_success(api.get_complaint(complaint["id"], HO))
    assert complaint_row["status"] == "TRIAGED"


def test_notification_axis_advances_without_touching_the_investigation_axis(api):
    """PRD §3.7: "An infection report advances along two entirely independent axes, and
    this independence is a hard requirement: an action on one axis leaves the other
    axis untouched."
    PRD §3.7: "`NOTIFY` is admissible only from `PENDING`, drives `PENDING →
    CDC_NOTIFIED` and sets `notification_late` to true when the current logical-clock
    instant has reached `notification_due_at` or passed it, and to false otherwise."
    PRD §3.7: "The report opens with `investigation_status` `RECEIVED`,
    `notification_status` `PENDING`, `notification_late` false, `reopen_count` at zero,
    and `notification_due_at` computed as 24 hours after `created_at`."

    Design: Difficulty/non_linear_state_machine/infection_report_notification_axis_advances_without_investigation_axis
    """
    establishment = create_permitted_establishment(
        name="Parallel Parlor", street_address="18 Cedar Ct"
    )
    artist = create_active_artist(establishment["id"], "Wren Adle")
    report = file_infection_report(
        establishment["id"],
        artist["id"],
        reporter_contact="patient@example.com",
        infection_type="MRSA",
        procedure_date="2026-04-20T00:00:00Z",
        symptom_onset_at="2026-04-25T00:00:00Z",
    )
    assert_instant_equals(
        report["notification_due_at"], "2026-05-02T00:00:00Z", "notification_due_at"
    )

    notified = advance_notification(report["id"], "NOTIFY")
    assert notified["notification_status"] == "CDC_NOTIFIED"
    assert notified["investigation_status"] == "RECEIVED", (
        "The investigation axis must be untouched by a notification action"
    )
    assert notified["notification_late"] is False


def test_investigation_axis_advances_without_touching_the_notification_axis(api):
    """PRD §3.7: "An infection report advances along two entirely independent axes, and
    this independence is a hard requirement: an action on one axis leaves the other
    axis untouched."
    PRD §3.7: "`SCREEN` is admissible only from `RECEIVED` and drives `RECEIVED →
    SCREENING`."

    Design: Difficulty/non_linear_state_machine/infection_report_notification_axis_advances_without_investigation_axis
    """
    establishment = create_permitted_establishment(
        name="Parallel Parlor Two", street_address="19 Cedar Ct"
    )
    artist = create_active_artist(establishment["id"], "Wren Adle")
    report = file_infection_report(
        establishment["id"],
        artist["id"],
        reporter_contact="patient@example.com",
        infection_type="MRSA",
        procedure_date="2026-04-20T00:00:00Z",
        symptom_onset_at="2026-04-25T00:00:00Z",
    )
    advance_notification(report["id"], "NOTIFY")

    screened = advance_investigation(report["id"], "SCREEN")
    assert screened["investigation_status"] == "SCREENING"
    assert screened["notification_status"] == "CDC_NOTIFIED", (
        "The notification axis must be untouched by an investigation action"
    )

    assert read_artist(artist["id"])["permit_status"] == "ACTIVE"
    assert read_establishment(establishment["id"])["risk_score"] == 25


def _confirmation_scenario(name: str, address: str):
    establishment = create_permitted_establishment(name=name, street_address=address,
                                                   establishment_type="COMBINED")
    artist = create_active_artist(establishment["id"], "Iris Kwan")
    inspection = start_inspection_at(
        establishment["id"], "2026-05-05T00:00:00Z", "2026-05-05T02:00:00Z"
    )
    for code, text in THREE_NONCRITICAL:
        cite_violation(inspection["id"], code, "NONCRITICAL", text)
    report = create_screening_infection_report(
        establishment["id"],
        artist["id"],
        reporter_contact="patient2@example.com",
        infection_type="MYCOBACTERIAL",
        procedure_date="2026-04-22T00:00:00Z",
        symptom_onset_at="2026-04-30T00:00:00Z",
    )
    return establishment, artist, report


def test_confirming_an_infection_puts_the_named_artist_on_probation(api):
    """PRD §3.7: "**Hop one:** the report's `investigation_status` becomes `CONFIRMED`,
    which is terminal on that axis."
    PRD §3.7: "**Hop two:** because the report was confirmed, the practitioner named by
    `artist_id`, when one was named, moves `ACTIVE → PROBATION` and has
    `bbp_recert_required` set to true, with `confirmed_infection_count` recomputed on
    that artist."
    PRD §3.7: "Throughout all four hops the notification axis is untouched."

    Design: Difficulty/transitive_cascade/infection_confirmation_cascades_to_artist_probation_and_restricted_posture
    """
    _establishment, artist, report = _confirmation_scenario(
        "Rivet Body Arts", "8 Maple Row"
    )

    confirmed = advance_investigation(report["id"], "CONFIRM")
    assert confirmed["investigation_status"] == "CONFIRMED"
    assert confirmed["notification_status"] == "PENDING"

    stored_artist = read_artist(artist["id"])
    assert stored_artist["permit_status"] == "PROBATION"
    assert stored_artist["bbp_recert_required"] is True
    assert stored_artist["confirmed_infection_count"] == 1


def test_confirmed_infection_drives_the_premises_into_restricted_posture(api):
    """PRD §3.7: "**Hop three:** because that practitioner left `ACTIVE`, the
    establishment's `active_artist_count` is decremented and its `risk_score` is
    recomputed, now carrying the confirmed-infection weight."
    PRD §3.7: "**Hop four:** because the risk figure moved, `operating_posture` is
    recomputed, and the premises drops to `RESTRICTED` once the score reaches 60 or
    higher."
    PRD §3.7: "The infection term contributes 20 points for each infection report of
    this establishment whose `investigation_status` is `CONFIRMED` and whose
    `created_at` falls inside the window."

    Design: Difficulty/transitive_cascade/infection_confirmation_cascades_to_artist_probation_and_restricted_posture
    """
    establishment, _artist, report = _confirmation_scenario(
        "Rivet Body Arts Two", "9 Maple Row"
    )
    before = read_establishment(establishment["id"])
    assert before["risk_score"] == 40
    assert before["operating_posture"] == "OPEN"

    advance_investigation(report["id"], "CONFIRM")

    after = read_establishment(establishment["id"])
    assert after["active_artist_count"] == 0
    assert after["risk_score"] == 60, (
        f"40 plus the 20-point confirmed-infection weight, got {after['risk_score']}"
    )
    assert after["operating_posture"] == "RESTRICTED"
    assert after["open_critical_violation_count"] == 0

"""Amendment supersede cascades, production cancel/wrap gates, complaint clock."""
from datetime import datetime, timedelta, timezone

from test_helpers import (
    FO,
    LM,
    ApiErrorId,
    assert_complaint,
    create_complaint_payload,
    create_permit_application_payload,
    create_walkthrough_report_payload,
    get_success_data,
    make_owner_rep_headers,
    set_clock,
    setup_accepted_scout_package,
    setup_basic_scenario,
    setup_confirmed_monitor,
    setup_draft_agreement,
    setup_issued_permit,
    setup_planned_shoot_day,
    setup_production_with_executed_agreement,
    setup_ready_day,
    setup_under_review_permit,
    sweep,
    validate_error,
    validate_paginated,
    validate_success,
)


def _get_complaint(api, production_id, complaint_id):
    rows, _ = validate_paginated(api.list_complaints(production_id, LM))
    matches = [r for r in rows if r["id"] == complaint_id]
    assert matches, f"Complaint {complaint_id} not found"
    return matches[0]


def _parse_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Difficulty: depth-3 amendment supersede cascade
# ---------------------------------------------------------------------------

def test_amendment_supersede_cascades_to_day_and_monitor(api):
    """PRD §3.4: "When `amendment_of_id` is set and the referenced application is
    `ISSUED` or `CONDITIONALLY_APPROVED`, the supersede cascade fires: the
    referenced application moves to `SUPERSEDED`; for a superseded `ISSUED`
    application, its street closures still in `REQUESTED` or `APPROVED` are
    cancelled, and its shoot days in `PLANNED` or `READY` are cancelled — and each
    such shoot-day cancellation in turn releases that day's `ASSIGNED` or
    `CONFIRMED` monitor assignments to `RELEASED`."
    PRD §3.4: "On creation the application is born `DRAFT`"

    Design: Difficulty/transitive_cascade/amendment_supersede_depth3_permit_day_monitor_chain
    """
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    permit, _, _ = setup_issued_permit(
        scenario, clock="2026-08-03T09:00:00Z", with_notification=False,
    )
    day = setup_planned_shoot_day(scenario, permit)
    monitor = setup_confirmed_monitor(scenario, day, "FILM_OFFICER", "FO-1")
    assert monitor["status"] == "CONFIRMED"

    current_version = get_success_data(api.get_production(production_id, LM))["version"]
    payload = create_permit_application_payload(
        scenario["location"]["id"], current_version,
        shoot_start_date="2026-08-11", shoot_end_date="2026-08-12",
        closed_lanes=0, shoot_hours_per_day=8,
        amendment_of_id=permit["id"],
    )
    amendment = validate_success(api.create_permit_application(production_id, payload, LM), 201)
    assert amendment["status"] == "DRAFT"
    assert amendment["amendment_of_id"] == permit["id"]

    superseded = get_success_data(api.get_permit_application(production_id, permit["id"], LM))
    assert superseded["status"] == "SUPERSEDED", "Link 1: the referenced application supersedes"

    day_now = get_success_data(api.get_shoot_day(production_id, day["id"], LM))
    assert day_now["status"] == "CANCELLED", "Link 2: the supersede cancels the PLANNED day"

    rows, _ = validate_paginated(api.list_monitor_assignments(production_id, LM))
    by_id = {row["id"]: row for row in rows}
    assert by_id[monitor["id"]]["status"] == "RELEASED", (
        "Link 3: the day cancellation releases its CONFIRMED assignment"
    )


def test_amendment_of_conditionally_approved_supersedes_application_only(api):
    """PRD §3.4: "When `amendment_of_id` is set and the referenced application is
    `ISSUED` or `CONDITIONALLY_APPROVED`, the supersede cascade fires: the
    referenced application moves to `SUPERSEDED`"
    PRD §3.4: "From `CONDITIONALLY_APPROVED` the supersede moves only the
    application itself."
    PRD §3.4: "On creation the application is born `DRAFT`, its `jurisdiction_id`
    is copied from the location and pinned there for the life of the application,
    and the parent Production's `version` increments by one."

    Design: Difficulty/transitive_cascade/amendment_supersede_depth3_permit_day_monitor_chain
    """
    scenario = setup_production_with_executed_agreement()
    production_id = scenario["production"]["id"]
    permit = setup_under_review_permit(scenario, clock="2026-08-03T09:00:00Z")
    permit = get_success_data(
        api.decide_permit_application(production_id, permit["id"], "APPROVE_WITH_CONDITIONS", FO)
    )
    assert permit["status"] == "CONDITIONALLY_APPROVED"

    before = get_success_data(api.get_production(production_id, LM))["version"]
    payload = create_permit_application_payload(
        scenario["location"]["id"], before,
        shoot_start_date="2026-08-11", shoot_end_date="2026-08-12",
        closed_lanes=0, shoot_hours_per_day=8,
        amendment_of_id=permit["id"],
    )
    amendment = validate_success(api.create_permit_application(production_id, payload, LM), 201)
    assert amendment["status"] == "DRAFT"
    assert amendment["amendment_of_id"] == permit["id"]
    assert amendment["jurisdiction_id"] == permit["jurisdiction_id"], (
        "The amendment is pinned to the same jurisdiction"
    )

    superseded = get_success_data(api.get_permit_application(production_id, permit["id"], LM))
    assert superseded["status"] == "SUPERSEDED"
    after = get_success_data(api.get_production(production_id, LM))["version"]
    assert after == before + 1, "Permit create increments the Production version by one"


# ---------------------------------------------------------------------------
# Production cancel cascade
# ---------------------------------------------------------------------------

def test_production_cancel_cascades_to_open_agreements_and_applications(api):
    """PRD §3.9: "the manager may cancel the production, moving it to `CANCELLED`;
    the cancellation withdraws every application still in `DRAFT` or `SUBMITTED`
    to `WITHDRAWN` and collapses every agreement still in `PROPOSED` or
    `COUNTERED` to `COLLAPSED`."

    Design: Corner/state_machines/production_cancel_cascades_to_open_agreements_and_applications
    """
    scenario = setup_basic_scenario()
    production, location = scenario["production"], scenario["location"]
    production_id = production["id"]
    setup_accepted_scout_package(production, location)
    agreement = setup_draft_agreement(production, location)
    get_success_data(api.propose_owner_agreement(production_id, agreement["id"], 150_000, LM))
    permit = get_success_data(api.create_permit_application(
        production_id,
        create_permit_application_payload(location["id"], production["version"]),
        LM,
    ))
    assert permit["status"] == "DRAFT"

    cancelled = validate_success(api.cancel_production(production_id, LM))
    assert cancelled["status"] == "CANCELLED"

    agreement_now = get_success_data(api.get_owner_agreement(production_id, agreement["id"], LM))
    assert agreement_now["status"] == "COLLAPSED"
    permit_now = get_success_data(api.get_permit_application(production_id, permit["id"], LM))
    assert permit_now["status"] == "WITHDRAWN"


# ---------------------------------------------------------------------------
# Wrap gates (fixed order: applications, deposits, complaints)
# ---------------------------------------------------------------------------

def test_production_wrap_blocked_by_open_application(api):
    """PRD §3.9: "Wrapping is the `ACTIVE`-to-`WRAPPED` transition, and its three
    preconditions are evaluated in a fixed order: first, every permit application
    must have left `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, and
    `CONDITIONALLY_APPROVED` — a failure here is reported as
    `ERR_APPLICATIONS_OPEN`"
    PRD §3.9: "The ordering matters operationally: a wrap attempt against a
    production with both open applications and open deposits surfaces
    `ERR_APPLICATIONS_OPEN`, not `ERR_DEPOSITS_OPEN`."

    Design: Corner/state_machines/production_wrap_blocked_by_open_application
    """
    result = setup_ready_day()
    production_id = result["production"]["id"]
    production = get_success_data(api.get_production(production_id, LM))
    assert production["status"] == "ACTIVE", "Setup: READY day flips the production ACTIVE"

    # A second, still-DRAFT application is non-terminal; the FUNDED deposit would
    # fail the second gate too, but the applications gate is checked first.
    get_success_data(api.create_permit_application(
        production_id,
        create_permit_application_payload(
            result["location"]["id"], production["version"],
            shoot_start_date="2026-08-13", shoot_end_date="2026-08-14",
        ),
        LM,
    ))

    resp = api.wrap_production(production_id, LM)
    validate_error(resp, ApiErrorId.ERR_APPLICATIONS_OPEN)
    assert get_success_data(api.get_production(production_id, LM))["status"] == "ACTIVE"


def test_production_wrap_blocked_by_unclosed_deposit(api):
    """PRD §3.9: "second, every deposit account must be `CLOSED` — reported as
    `ERR_DEPOSITS_OPEN`"
    PRD §3.5: "For the purposes of the production wrap gate in §3.9, an
    application counts as resolved once it has left every one of `DRAFT`,
    `SUBMITTED`, `UNDER_REVIEW`, and `CONDITIONALLY_APPROVED` — `ISSUED`,
    `DENIED`, `SUPERSEDED`, `EXPIRED`, and `WITHDRAWN` all clear the gate."

    Design: Corner/state_machines/production_wrap_blocked_by_unclosed_deposit
    """
    result = setup_ready_day()
    production_id = result["production"]["id"]
    assert get_success_data(api.get_production(production_id, LM))["status"] == "ACTIVE"
    # The single permit is ISSUED (clears the applications gate); the deposit
    # stands FUNDED and is never settled; no complaints exist.
    account = get_success_data(
        api.get_deposit_account(production_id, result["deposit_account"]["id"], LM)
    )
    assert account["status"] == "FUNDED"

    resp = api.wrap_production(production_id, LM)
    validate_error(resp, ApiErrorId.ERR_DEPOSITS_OPEN)
    assert get_success_data(api.get_production(production_id, LM))["status"] == "ACTIVE"


def test_production_wrap_blocked_by_open_complaint(api):
    """PRD §3.9: "and last, no complaint may remain in `OPEN` or `ACKNOWLEDGED` —
    reported as `ERR_COMPLAINTS_OPEN`."

    Design: Corner/state_machines/production_wrap_blocked_by_open_complaint
    """
    result = setup_ready_day()
    production_id = result["production"]["id"]
    assert get_success_data(api.get_production(production_id, LM))["status"] == "ACTIVE"

    # Close the deposit account: POST walkthrough signed -> SETTLING -> settle.
    account = result["deposit_account"]
    post = get_success_data(api.create_walkthrough_report(
        production_id,
        create_walkthrough_report_payload(result["location"]["id"], "POST"),
        LM,
    ))
    get_success_data(api.sign_walkthrough_report(production_id, post["id"], LM))
    closed = validate_success(api.settle_deposit_account(production_id, account["id"], 0, FO))
    assert closed["status"] == "CLOSED"

    complaint = get_success_data(api.create_complaint(
        production_id,
        create_complaint_payload(result["shoot_day"]["id"], category="OTHER", severity="LOW"),
        make_owner_rep_headers(result["owner"]["id"]),
    ))
    assert complaint["status"] == "OPEN"

    resp = api.wrap_production(production_id, LM)
    validate_error(resp, ApiErrorId.ERR_COMPLAINTS_OPEN)
    assert get_success_data(api.get_production(production_id, LM))["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Complaint clock: 24h deadline, escalation, resolution note
# ---------------------------------------------------------------------------

def test_complaint_open_past_due_escalates_at_sweep(api):
    """PRD §3.9: "The server stamps `filed_at` from the logical clock and sets
    `response_due_at` exactly 24 hours later; the complaint opens as `OPEN`."
    PRD §3.9: "Escalation itself is automatic: when the operations sweep finds an
    `OPEN` complaint whose `response_due_at` has passed, it moves the complaint to
    `ESCALATED`"

    Design: Corner/state_machines/complaint_open_past_due_escalates_at_sweep
    """
    set_clock("2026-08-05T09:00:00Z")
    scenario = setup_basic_scenario(
        jurisdiction_overrides={"lead_time_business_days": 2},
    )
    production_id = scenario["production"]["id"]
    permit = get_success_data(api.create_permit_application(
        production_id,
        create_permit_application_payload(
            scenario["location"]["id"], scenario["production"]["version"],
        ),
        LM,
    ))
    day = setup_planned_shoot_day(scenario, permit)
    complaint = get_success_data(api.create_complaint(
        production_id,
        create_complaint_payload(day["id"], category="NOISE", severity="LOW"),
        make_owner_rep_headers(scenario["owner"]["id"]),
    ))
    assert_complaint(complaint)
    assert complaint["status"] == "OPEN"
    due_delta = _parse_ts(complaint["response_due_at"]) - _parse_ts(complaint["filed_at"])
    assert due_delta == timedelta(hours=24), (
        f"response_due_at must be filed_at + 24h, got {due_delta}"
    )

    # Just past the deadline, the sweep escalates the still-OPEN complaint.
    set_clock("2026-08-06T10:00:00Z")
    sweep()
    assert _get_complaint(api, production_id, complaint["id"])["status"] == "ESCALATED"


def test_complaint_resolve_with_empty_note_rejected(api):
    """PRD §3.9: "Resolution requires a non-empty `resolution_note` (an empty one
    fails with `ERR_INVALID_REQUEST`): the manager resolves from `ACKNOWLEDGED`"

    Design: Corner/state_machines/complaint_resolve_with_empty_note_rejected
    """
    set_clock("2026-08-05T09:00:00Z")
    scenario = setup_basic_scenario(
        jurisdiction_overrides={"lead_time_business_days": 2},
    )
    production_id = scenario["production"]["id"]
    permit = get_success_data(api.create_permit_application(
        production_id,
        create_permit_application_payload(
            scenario["location"]["id"], scenario["production"]["version"],
        ),
        LM,
    ))
    day = setup_planned_shoot_day(scenario, permit)
    complaint = get_success_data(api.create_complaint(
        production_id,
        create_complaint_payload(day["id"], category="PARKING", severity="MEDIUM"),
        make_owner_rep_headers(scenario["owner"]["id"]),
    ))
    acknowledged = get_success_data(api.acknowledge_complaint(production_id, complaint["id"], LM))
    assert acknowledged["status"] == "ACKNOWLEDGED"

    resp = api.resolve_complaint(production_id, complaint["id"], "", LM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert _get_complaint(api, production_id, complaint["id"])["status"] == "ACKNOWLEDGED"

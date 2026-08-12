"""Incident reports, patron discipline cascades, and certification gating
(PRD §3.5, §3.8)."""
from datetime import datetime, timedelta, timezone

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    assert_incident_report,
    create_incident_report_payload, create_lifeguard_payload,
    make_facility, make_season, make_pass_holder, make_lifeguard,
    make_season_pass, set_clock, get_facility,
    make_lifeguard_headers, setup_submitted_incident,
)

MANAGER = TEST_USERS["manager_headers"]
GATE = TEST_USERS["gate_headers"]


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def test_incident_confirm_major_triggers_ban_cascade(api):
    """PRD §3.8: "Confirmation moves the report to `CONFIRMED` and increments
    the involved holder's `strike_count` by 1. Two escalation paths then
    apply independently: if the report's `severity` is `MAJOR`, or if the
    holder's `strike_count` has reached at least 3, the holder's
    `banned_until` is set to 30 days from the current clock. Activating a ban
    also revokes every `ACTIVE` `SeasonPass` the holder owns (moving each to
    `REVOKED`)".

    Design: Difficulty/transitive_cascade/incident_confirm_depth2_ban_cascade
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=2)
    season = make_season(facility["id"])
    holder = make_pass_holder(
        full_name="Offender", date_of_birth="1990-01-01T00:00:00Z"
    )
    season_pass = make_season_pass(holder["id"], season["id"])
    lifeguard = make_lifeguard(full_name="Guard G", certification_id="RC-1")
    set_clock("2026-07-05T12:00:00Z")
    report = get_success_data(
        api.create_incident_report(
            create_incident_report_payload(
                facility["id"], lifeguard["id"], holder["id"],
                incident_type="RULE_VIOLATION",
                occurred_at="2026-07-05T11:30:00Z",
                severity="MAJOR", narrative="Assaulted staff",
            ),
            make_lifeguard_headers(lifeguard["id"]),
        )
    )
    get_success_data(
        api.submit_incident_report(
            report["id"], make_lifeguard_headers(lifeguard["id"])
        )
    )
    confirmed = validate_success(api.confirm_incident_report(report["id"], MANAGER))
    assert_incident_report(confirmed)
    assert confirmed["status"] == "CONFIRMED"
    holder_after = validate_success(api.get_pass_holder(holder["id"], MANAGER))
    assert holder_after["strike_count"] == 1
    assert holder_after["banned_until"] is not None
    expected_ban = _parse_iso("2026-07-05T12:00:00Z") + timedelta(days=30)
    assert _parse_iso(holder_after["banned_until"]) == expected_ban, (
        f"banned_until must be 30 days from the clock "
        f"({expected_ban.isoformat()}), got {holder_after['banned_until']}"
    )
    pass_after = validate_success(api.get_pass(season_pass["id"], MANAGER))
    assert pass_after["status"] == "REVOKED"


def test_incident_confirm_third_strike_triggers_ban(api):
    """PRD §3.8: "Confirmation moves the report to `CONFIRMED` and increments
    the involved holder's `strike_count` by 1. Two escalation paths then
    apply independently: if the report's `severity` is `MAJOR`, or if the
    holder's `strike_count` has reached at least 3, the holder's
    `banned_until` is set to 30 days from the current clock."

    Design: Difficulty/transitive_cascade/incident_confirm_depth2_ban_cascade
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=2)
    holder = make_pass_holder(
        full_name="Repeat", date_of_birth="1990-01-01T00:00:00Z"
    )
    lifeguard = make_lifeguard(full_name="Guard G", certification_id="RC-1")
    set_clock("2026-07-05T12:00:00Z")
    for i in range(3):
        report = get_success_data(
            api.create_incident_report(
                create_incident_report_payload(
                    facility["id"], lifeguard["id"], holder["id"],
                    incident_type="RULE_VIOLATION",
                    occurred_at="2026-07-05T11:30:00Z",
                    severity="MINOR", narrative=f"Infraction {i + 1}",
                ),
                make_lifeguard_headers(lifeguard["id"]),
            )
        )
        get_success_data(
            api.submit_incident_report(
                report["id"], make_lifeguard_headers(lifeguard["id"])
            )
        )
        confirmed = validate_success(
            api.confirm_incident_report(report["id"], MANAGER)
        )
        assert confirmed["status"] == "CONFIRMED"
    holder_after = validate_success(api.get_pass_holder(holder["id"], MANAGER))
    assert holder_after["strike_count"] == 3
    assert holder_after["banned_until"] is not None, (
        "Reaching strike_count 3 must activate a ban"
    )
    expected_ban = _parse_iso("2026-07-05T12:00:00Z") + timedelta(days=30)
    assert _parse_iso(holder_after["banned_until"]) == expected_ban


def test_incident_dismiss_terminal_no_further_transitions(api):
    """PRD §3.8: "A manager then either dismisses the report (moving it to
    `DISMISSED` with no further effect) or confirms it."
    PRD §2.10: "6. Target resource's current state permits the requested
    transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/incident_dismiss_terminal_no_further_transitions
    """
    facility, holder, lifeguard, report = setup_submitted_incident(
        severity="MINOR", clock="2026-06-15T12:00:00Z",
        incident_type="FIRST_AID",
    )
    dismissed = validate_success(api.dismiss_incident_report(report["id"], MANAGER))
    assert dismissed["status"] == "DISMISSED"
    resp = api.confirm_incident_report(report["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_incident_report(report["id"], MANAGER))
    assert after["status"] == "DISMISSED"


def test_lifeguard_submit_incident_with_expired_cert_returns_409(api):
    """PRD §3.8: "Submission is performed by the reporting lifeguard
    personally: `X-User-ID` must equal the report's `reporting_lifeguard_id`,
    and the guard's `cert_status` must be `ACTIVE` at submission time
    (otherwise `ERR_GUARD_NOT_CERTIFIED`)."
    PRD §3.5: "Certification status is derived: a guard whose
    `cert_expires_on` has passed moves from `ACTIVE` to `EXPIRED`".

    Design: Corner/validations/lifeguard_submit_incident_with_expired_cert_returns_409
    """
    facility = make_facility()
    holder = make_pass_holder()
    lifeguard = make_lifeguard(
        full_name="LG Old", certification_id="RC-OLD",
        cert_expires_on="2026-01-01T00:00:00Z",
        hired_on="2024-01-01T00:00:00Z",
    )
    set_clock("2026-06-15T10:00:00Z")
    report = get_success_data(
        api.create_incident_report(
            create_incident_report_payload(
                facility["id"], lifeguard["id"], holder["id"],
                incident_type="RESCUE",
                occurred_at="2026-06-15T09:00:00Z",
                severity="MINOR", narrative="x",
            ),
            make_lifeguard_headers(lifeguard["id"]),
        )
    )
    resp = api.submit_incident_report(
        report["id"], make_lifeguard_headers(lifeguard["id"])
    )
    validate_error(resp, ApiErrorId.ERR_GUARD_NOT_CERTIFIED)

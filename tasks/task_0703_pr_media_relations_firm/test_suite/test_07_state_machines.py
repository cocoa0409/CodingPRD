"""State-machine corners: invalid transitions, preconditions, side-effects, terminal lockdown."""
from datetime import datetime, timezone

from test_helpers import (
    validate_success,
    validate_error,
    is_iso8601_timestamp,
    ApiErrorId,
    create_client,
    create_campaign,
    create_outlet,
    create_journalist,
    create_spokesperson,
    create_media_list_current,
    create_pitch_in_state,
    create_coverage,
    create_interview,
    create_crisis_event,
    setup_campaign_with_media_list,
    setup_interview_scenario,
    create_scheduled_press_release,
    create_distribution,
    set_clock,
    TEST_USERS,
)

AM = TEST_USERS["account_manager_headers"]
MS = TEST_USERS["media_specialist_headers"]
SC = TEST_USERS["scheduling_coordinator_headers"]
PA = TEST_USERS["platform_admin_headers"]


def _parse_instant(s: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime for instant comparison.

    The PRD pins the fractional-digit serialization only for ``created_at`` and the
    request metadata timestamp (§2.2, §2.4); the clock-stamped side-effect timestamps
    (``released_at``/``delivered_at``/``sent_at``, §3.5) are specified only as being
    "stamped from the logical clock", so we compare the underlying instant rather than
    an exact string (both ``...:00Z`` and ``...:00.000Z`` denote the same instant).
    """
    raw = s[:-1] + "+00:00" if s.endswith("Z") else s
    return datetime.fromisoformat(raw).astimezone(timezone.utc)


def test_activate_completed_campaign_invalid_state(api):
    """PRD §3.3: "Activation moves a campaign from `DRAFT` to `ACTIVE`, and also from `PAUSED`
    back to `ACTIVE`."
    PRD §2.8: "(7) state validity — the target resource is in a state from which the
    requested transition is legal, else `ERR_INVALID_STATE`;"

    Design: Corner/state_machines/activate_campaign_from_completed_invalid_state
    """
    client = create_client()
    campaign = create_campaign(client["id"])
    validate_success(api.activate_campaign(campaign["id"], AM))
    validate_success(api.complete_campaign(campaign["id"], AM))
    resp = api.activate_campaign(campaign["id"], AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_archive_already_archived_campaign_invalid_state(api):
    """PRD §3.3: "Archiving moves a campaign from `COMPLETED` to `ARCHIVED`, and also directly
    from `DRAFT` to `ARCHIVED`; `ARCHIVED` is terminal."

    Design: Corner/state_machines/archive_then_archive_again_terminal_lockdown
    """
    client = create_client()
    campaign = create_campaign(client["id"])
    validate_success(api.archive_campaign(campaign["id"], AM))
    resp = api.archive_campaign(campaign["id"], AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_complete_campaign_with_open_sent_pitch_rejected(api):
    """PRD §3.3: "no pitch on the campaign may be in `SENT` or `RESPONDED` status (else
    `ERR_CAMPAIGN_HAS_OPEN_PITCHES`), and no interview on the campaign may be in `REQUESTED`
    or `CONFIRMED` status (else `ERR_CAMPAIGN_HAS_OPEN_INTERVIEWS`)."

    Design: Corner/state_machines/complete_campaign_with_open_sent_pitch_rejected
    """
    scn = setup_campaign_with_media_list()
    create_pitch_in_state(scn["campaign"]["id"], scn["media_list"]["id"], scn["journalist"]["id"], "SENT")
    resp = api.complete_campaign(scn["campaign"]["id"], AM)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_HAS_OPEN_PITCHES.value)


def test_complete_campaign_with_open_interview_rejected(api):
    """PRD §3.3: "no pitch on the campaign may be in `SENT` or `RESPONDED` status (else
    `ERR_CAMPAIGN_HAS_OPEN_PITCHES`), and no interview on the campaign may be in `REQUESTED`
    or `CONFIRMED` status (else `ERR_CAMPAIGN_HAS_OPEN_INTERVIEWS`)."

    Design: Corner/state_machines/complete_campaign_with_open_interview_rejected
    """
    scn = setup_interview_scenario()  # one REQUESTED interview, no open pitches
    resp = api.complete_campaign(scn["campaign"]["id"], AM)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_HAS_OPEN_INTERVIEWS.value)


def test_release_delivers_queued_distributions_with_clock_stamp(api):
    """PRD §3.5: "On release, the press release's `released_at` is stamped from the logical
    clock, and every distribution for that release still in `QUEUED` advances to `DELIVERED`
    with its `delivered_at` stamped from the same clock."

    Design: Corner/state_machines/press_release_release_delivers_queued_distributions
    """
    scn = setup_campaign_with_media_list()
    pr = create_scheduled_press_release(scn["campaign"]["id"], "2026-03-15T00:00:00Z", headline="Big News")
    dist = create_distribution(pr["id"], scn["journalist"]["id"])
    set_clock("2026-03-15T00:00:00Z")

    released = validate_success(api.release_press_release(pr["id"], MS))
    assert released["status"] == "RELEASED"
    assert is_iso8601_timestamp(released["released_at"])
    assert _parse_instant(released["released_at"]) == _parse_instant("2026-03-15T00:00:00Z")

    dist_after = validate_success(api.get_distribution(dist["id"], MS))
    assert dist_after["status"] == "DELIVERED"
    assert is_iso8601_timestamp(dist_after["delivered_at"])
    assert _parse_instant(dist_after["delivered_at"]) == _parse_instant("2026-03-15T00:00:00Z")


def test_withdraw_scheduled_press_release_bounces_distributions(api):
    """PRD §3.5: "Withdrawing from `SCHEDULED` advances every distribution for that release
    still in `QUEUED` to `BOUNCED`."

    Design: Corner/state_machines/withdraw_scheduled_press_release_bounces_queued_distributions
    """
    scn = setup_campaign_with_media_list()
    pr = create_scheduled_press_release(scn["campaign"]["id"], "2026-03-20T00:00:00Z", headline="Pulled")
    dist = create_distribution(pr["id"], scn["journalist"]["id"])

    withdrawn = validate_success(api.withdraw_press_release(pr["id"], MS))
    assert withdrawn["status"] == "WITHDRAWN"
    dist_after = validate_success(api.get_distribution(dist["id"], MS))
    assert dist_after["status"] == "BOUNCED"


def test_reschedule_requested_interview_updates_times_in_place(api):
    """PRD §3.6: "Rescheduling re-checks both overlap rules and updates `starts_at` and
    `ends_at` in place while leaving the `status` at `REQUESTED`; an interview may be
    rescheduled any number of times."

    Design: Corner/state_machines/interview_reschedule_cycle_updates_times_in_place
    """
    scn = setup_interview_scenario(
        starts_at="2026-04-25T10:00:00Z", ends_at="2026-04-25T11:00:00Z")
    resp = api.reschedule_interview(
        scn["interview"]["id"],
        {"starts_at": "2026-04-26T14:00:00Z", "ends_at": "2026-04-26T15:00:00Z"}, SC)
    data = validate_success(resp)
    assert data["status"] == "REQUESTED"
    assert data["starts_at"] == "2026-04-26T14:00:00Z"


def test_complete_interview_before_ends_at_rejected(api):
    """PRD §3.6: "Completing advances `CONFIRMED` to `COMPLETED` but only once the logical
    clock is at or after `ends_at`; an attempt before then is rejected with
    `ERR_INTERVIEW_NOT_ENDED`."

    Design: Corner/state_machines/interview_complete_before_ends_at_rejected
    """
    scn = setup_interview_scenario(
        starts_at="2026-04-30T10:00:00Z", ends_at="2026-04-30T11:00:00Z")
    validate_success(api.confirm_interview(scn["interview"]["id"], SC))
    # clock still at default 2026-03-01, before ends_at
    resp = api.complete_interview(scn["interview"]["id"], SC)
    validate_error(resp, ApiErrorId.ERR_INTERVIEW_NOT_ENDED.value)


def test_contain_crisis_before_response_published_rejected(api):
    """PRD §3.12: "Containing advances either `ASSESSING` or `ESCALATED` to `CONTAINED`, but
    only once the response dimension has reached `PUBLISHED`; a contain attempted before
    then is rejected with `ERR_RESPONSE_NOT_PUBLISHED`."

    Design: Corner/state_machines/crisis_contain_before_response_published_rejected
    """
    crisis = create_crisis_event(severity="HIGH")
    resp = api.contain_crisis(crisis["id"], AM)
    validate_error(resp, ApiErrorId.ERR_RESPONSE_NOT_PUBLISHED.value)


def test_escalate_low_severity_crisis_rejected(api):
    """PRD §3.12: "Escalating advances `ASSESSING` to `ESCALATED`, but only when the event's
    `severity` is `HIGH` or `CRITICAL`; an escalate on a `LOW` or `MEDIUM` crisis is
    rejected with `ERR_SEVERITY_TOO_LOW`."

    Design: Corner/state_machines/crisis_escalate_low_severity_rejected
    """
    crisis = create_crisis_event(severity="LOW", summary="Minor")
    resp = api.escalate_crisis(crisis["id"], AM)
    validate_error(resp, ApiErrorId.ERR_SEVERITY_TOO_LOW.value)


def test_approve_response_without_holding_statement_rejected(api):
    """PRD §3.12: "Approving the response advances `DRAFTING` to `APPROVED`, but only when the
    event has a non-null `holding_statement`; if no holding statement is present the approve
    is rejected with `ERR_NO_HOLDING_STATEMENT`."

    Design: Corner/state_machines/crisis_approve_response_without_holding_statement_rejected
    """
    crisis = create_crisis_event(severity="HIGH", summary="NoStmt")  # holding_statement omitted -> null
    resp = api.approve_response_crisis(crisis["id"], AM)
    validate_error(resp, ApiErrorId.ERR_NO_HOLDING_STATEMENT.value)


def test_verify_coverage_on_draft_campaign_invalid_state(api):
    """PRD §3.8: "Verification requires the owning campaign to be in `ACTIVE`, `PAUSED`, or
    `COMPLETED`; in any other state the verify is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/coverage_verify_requires_campaign_not_draft_invalid_state
    """
    # DRAFT campaign (never activated); media list + journalist created against it.
    client = create_client()
    campaign = create_campaign(client["id"])  # stays DRAFT
    outlet = create_outlet()
    journalist = create_journalist(outlet["id"])
    create_media_list_current(campaign["id"], [journalist["id"]], name="DC List")
    cov = create_coverage(campaign["id"], journalist["id"], sentiment="NEUTRAL", prominence="MENTION")
    resp = api.verify_coverage(cov["id"], MS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

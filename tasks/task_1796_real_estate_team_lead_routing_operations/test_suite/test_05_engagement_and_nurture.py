"""Engagement scoring, decay, temperature thresholds, and nurture automation."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_engagement_event,
    assert_instant_equals,
    claim_as,
    create_campaign,
    create_lead_source,
    create_team,
    ctx_claimed_lead_with_campaign,
    engagement_event_payload,
    enroll_as_leader,
    get_enrollment,
    get_lead,
    intake_lead,
    make_team_leader_headers,
    nurture_enrollment_payload,
    post_event,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["team_admin_headers"]


# ─── Engagement event points and decay (Corner) ──────────────────────────────


def test_engagement_event_points_computed_client_input_ignored(api):
    """PRD §3.5: "Each type earns fixed base `points`: `EMAIL_OPEN` earns 5, `LINK_CLICK` 10, `CALL_ANSWERED` 20, `FORM_SUBMIT` 25, `REPLIED` 30, and `SHOWING_ATTENDED` 40."
    PRD §2.8: "Third, body well-formedness — required fields present, no undeclared fields (a strict schema under which computed or system-maintained fields sent by the client are rejected), enum values valid, datetimes parseable, and integer ranges respected — all failing as `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/engagement_event_points_computed_client_input_ignored
    """
    team = create_team()
    source = create_lead_source(
        team["id"], name="Sphere", type="SPHERE", auto_route=False, monthly_budget_cents=1_000_000
    )
    lead = intake_lead(team["id"], source["id"], "+15125550100")

    injected = api.create_engagement_event(
        lead["id"],
        {"type": "FORM_SUBMIT", "occurred_at": "2026-08-01T00:30:00Z", "points": 9999},
        ADMIN,
    )
    validate_error(injected, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    event = validate_success(
        api.create_engagement_event(
            lead["id"], engagement_event_payload("FORM_SUBMIT", "2026-08-01T00:30:00Z"), ADMIN
        ),
        201,
    )
    assert_engagement_event(event)
    assert event["points"] == 25
    assert event["effective_points"] == 25


def test_temperature_threshold_warm_at_exactly_40(api):
    """PRD §3.5: "The `temperature` dimension is independent of lifecycle status: a lead is `HOT` when its `engagement_score` is at least 75, `WARM` when the score is at least 40 but below 75, and `COLD` below 40 — a score of exactly 40 is `WARM` and exactly 75 is `HOT`."

    Design: Corner/calculations/temperature_threshold_warm_at_exactly_40
    """
    team = create_team()
    source = create_lead_source(
        team["id"], name="Sphere", type="SPHERE", auto_route=False, monthly_budget_cents=1_000_000
    )
    warm = intake_lead(team["id"], source["id"], "+15125550110", contact_name="Warm", contact_email="w@x.com")
    cold = intake_lead(team["id"], source["id"], "+15125550111", contact_name="Cold", contact_email="c@x.com")

    post_event(warm["id"], "FORM_SUBMIT", "2026-08-01T00:30:00Z")
    post_event(warm["id"], "LINK_CLICK", "2026-08-01T00:31:00Z")
    post_event(warm["id"], "EMAIL_OPEN", "2026-08-01T00:32:00Z")
    post_event(cold["id"], "FORM_SUBMIT", "2026-08-01T00:30:00Z")
    post_event(cold["id"], "LINK_CLICK", "2026-08-01T00:31:00Z")

    warm_after = get_lead(warm["id"])
    assert warm_after["engagement_score"] == 40
    assert warm_after["temperature"] == "WARM", "40 >= 40 qualifies (inclusive)"
    cold_after = get_lead(cold["id"])
    assert cold_after["engagement_score"] == 35
    assert cold_after["temperature"] == "COLD"


def test_engagement_decay_step_halves_then_zeroes(api):
    """PRD §3.5: "An event's `effective_points` decay in steps against the logical clock: full points while the event is younger than 30 days old; half, floored to a whole point, once the event is at least 30 days but younger than 60 days old; and zero at 60 days or older."
    PRD §3.5: "A lead's `engagement_score` is the sum of `effective_points` over all of its events — no status filter applies — recomputed whenever an event is appended and whenever the score is read."

    Design: Corner/calculations/engagement_decay_step_halves_then_zeroes
    """
    team = create_team()
    source = create_lead_source(
        team["id"], name="Sphere", type="SPHERE", auto_route=False, monthly_budget_cents=1_000_000
    )
    lead = intake_lead(team["id"], source["id"], "+15125550112", contact_name="Decayer", contact_email="d@x.com")
    post_event(lead["id"], "SHOWING_ATTENDED", "2026-08-01T00:00:00Z")

    set_clock("2026-08-26T00:00:00Z")  # age 25 days
    at_25 = get_lead(lead["id"])
    assert at_25["engagement_score"] == 40
    assert at_25["temperature"] == "WARM"

    set_clock("2026-09-05T00:00:00Z")  # age 35 days
    at_35 = get_lead(lead["id"])
    assert at_35["engagement_score"] == 20, "floor(40/2)"
    assert at_35["temperature"] == "COLD"

    set_clock("2026-10-02T00:00:00Z")  # age 62 days
    at_62 = get_lead(lead["id"])
    assert at_62["engagement_score"] == 0


# ─── Temperature-shift cascade and step completion (Corner) ──────────────────


def test_enrollment_auto_exits_on_temperature_shift(api):
    """PRD §3.5: "Whenever a lead's temperature does change, every `ENROLLED` or `PAUSED` nurture enrollment whose campaign's `temperature_target` no longer equals the new temperature exits automatically with `exit_reason` `TEMPERATURE_SHIFT`."
    PRD §3.5: "Temperature changes never alter status, and status changes never alter temperature."

    Design: Corner/state_machines/enrollment_auto_exits_on_temperature_shift
    """
    ctx = ctx_claimed_lead_with_campaign()  # ACTIVE COLD campaign; lead CLAIMED, COLD
    enrollment = enroll_as_leader(ctx["campaign"]["id"], ctx["lead"]["id"], ctx["leader"]["id"])
    assert enrollment["status"] == "ENROLLED"

    post_event(ctx["lead"]["id"], "SHOWING_ATTENDED", "2026-08-01T00:30:00Z")
    post_event(ctx["lead"]["id"], "SHOWING_ATTENDED", "2026-08-01T01:00:00Z")

    lead_after = get_lead(ctx["lead"]["id"])
    assert lead_after["engagement_score"] == 80
    assert lead_after["temperature"] == "HOT"
    assert lead_after["status"] == "CLAIMED"

    enr_after = get_enrollment(enrollment["id"])
    assert enr_after["status"] == "EXITED"
    assert enr_after["exit_reason"] == "TEMPERATURE_SHIFT"


def test_enrollment_completes_after_final_step_via_clock(api):
    """PRD §3.5: "A new enrollment snapshots the lead's temperature into `entered_temperature`, starts at `current_step_index` zero, and schedules `next_send_at` at the enrollment instant plus the first step's `offset_days`."
    PRD §3.5: "During the sweep, any `ENROLLED` enrollment whose `next_send_at` has been reached advances `current_step_index` and re-schedules from the next step's offset; completing the final step transitions the enrollment to `COMPLETED`."

    Design: Corner/state_machines/enrollment_completes_after_final_step_via_clock
    """
    ctx = ctx_claimed_lead_with_campaign(campaign_steps=[{"offset_days": 1, "channel": "EMAIL"}])
    enrollment = enroll_as_leader(ctx["campaign"]["id"], ctx["lead"]["id"], ctx["leader"]["id"])
    assert_instant_equals(enrollment["next_send_at"], "2026-08-02T00:00:00Z")
    assert enrollment["current_step_index"] == 0

    sweep = set_clock("2026-08-02T00:00:00Z")  # exactly next_send_at — reached (inclusive)
    assert sweep["advanced_enrollment_count"] == 1
    assert get_enrollment(enrollment["id"])["status"] == "COMPLETED"


# ─── Enrollment validations (Corner) ─────────────────────────────────────────


def test_enrollment_temperature_mismatch_rejected(api):
    """PRD §3.5: "The lead must be `CLAIMED` or `WORKING` (any other status is `ERR_INVALID_STATE`), the campaign must be `ACTIVE` (enrolling against a `DRAFT` or `PAUSED` campaign is `ERR_CAMPAIGN_NOT_ACTIVE`), the lead's current temperature must equal the campaign's `temperature_target` (else `ERR_TEMPERATURE_MISMATCH`), and the lead must not already hold an `ENROLLED` or `PAUSED` enrollment (else `ERR_LEAD_ALREADY_ENROLLED`)."

    Design: Corner/validations/enrollment_temperature_mismatch_rejected
    """
    ctx = ctx_claimed_lead_with_campaign()  # ACTIVE COLD campaign
    post_event(ctx["lead"]["id"], "SHOWING_ATTENDED", "2026-08-01T00:30:00Z")  # 40 → WARM
    assert get_lead(ctx["lead"]["id"])["temperature"] == "WARM"

    res = api.create_nurture_enrollment(
        nurture_enrollment_payload(ctx["campaign"]["id"], ctx["lead"]["id"]),
        make_team_leader_headers(ctx["leader"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_TEMPERATURE_MISMATCH, expected_status=409)


def test_second_active_enrollment_rejected(api):
    """PRD §3.5: "The lead must be `CLAIMED` or `WORKING` (any other status is `ERR_INVALID_STATE`), the campaign must be `ACTIVE` (enrolling against a `DRAFT` or `PAUSED` campaign is `ERR_CAMPAIGN_NOT_ACTIVE`), the lead's current temperature must equal the campaign's `temperature_target` (else `ERR_TEMPERATURE_MISMATCH`), and the lead must not already hold an `ENROLLED` or `PAUSED` enrollment (else `ERR_LEAD_ALREADY_ENROLLED`)."

    Design: Corner/validations/second_active_enrollment_rejected
    """
    ctx = ctx_claimed_lead_with_campaign()  # campaign A: ACTIVE COLD
    camp_b = create_campaign(
        ctx["team"]["id"],
        name="Cold Drip B",
        temperature_target="COLD",
        steps=[{"offset_days": 2, "channel": "SMS"}],
    )
    enrollment = enroll_as_leader(ctx["campaign"]["id"], ctx["lead"]["id"], ctx["leader"]["id"])

    res = api.create_nurture_enrollment(
        nurture_enrollment_payload(camp_b["id"], ctx["lead"]["id"]),
        make_team_leader_headers(ctx["leader"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LEAD_ALREADY_ENROLLED, expected_status=409)
    assert get_enrollment(enrollment["id"])["status"] == "ENROLLED"


def test_double_exit_enrollment_returns_enrollment_not_active(api):
    """PRD §3.5: "A leader or admin may exit an `ENROLLED` or `PAUSED` enrollment manually, recording `exit_reason` `MANUAL`; attempting a manual exit on a `COMPLETED` or `EXITED` enrollment is `ERR_ENROLLMENT_NOT_ACTIVE`."

    Design: Corner/errors/double_exit_enrollment_returns_enrollment_not_active
    """
    ctx = ctx_claimed_lead_with_campaign()
    enrollment = enroll_as_leader(ctx["campaign"]["id"], ctx["lead"]["id"], ctx["leader"]["id"])
    exited = validate_success(
        api.exit_nurture_enrollment(
            enrollment["id"], make_team_leader_headers(ctx["leader"]["id"])
        ),
        200,
    )
    assert exited["status"] == "EXITED"
    assert exited["exit_reason"] == "MANUAL"

    res = api.exit_nurture_enrollment(
        enrollment["id"], make_team_leader_headers(ctx["leader"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE, expected_status=409)
    assert get_enrollment(enrollment["id"])["status"] == "EXITED"


# ─── Enrollment gated on campaign state (Difficulty) ─────────────────────────


def test_enrollment_blocked_when_campaign_paused(api):
    """PRD §3.5: "The lead must be `CLAIMED` or `WORKING` (any other status is `ERR_INVALID_STATE`), the campaign must be `ACTIVE` (enrolling against a `DRAFT` or `PAUSED` campaign is `ERR_CAMPAIGN_NOT_ACTIVE`), the lead's current temperature must equal the campaign's `temperature_target` (else `ERR_TEMPERATURE_MISMATCH`), and the lead must not already hold an `ENROLLED` or `PAUSED` enrollment (else `ERR_LEAD_ALREADY_ENROLLED`)."

    Design: Difficulty/cross_entity_state_dependency/enrollment_blocked_when_campaign_not_active
    """
    ctx = ctx_claimed_lead_with_campaign()  # campaign ACTIVE, lead CLAIMED COLD
    validate_success(api.pause_nurture_campaign(ctx["campaign"]["id"], ADMIN), 200)

    res = api.create_nurture_enrollment(
        nurture_enrollment_payload(ctx["campaign"]["id"], ctx["lead"]["id"]),
        make_team_leader_headers(ctx["leader"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE, expected_status=409)


def test_enrollment_blocked_when_campaign_draft(api):
    """PRD §3.5: "The lead must be `CLAIMED` or `WORKING` (any other status is `ERR_INVALID_STATE`), the campaign must be `ACTIVE` (enrolling against a `DRAFT` or `PAUSED` campaign is `ERR_CAMPAIGN_NOT_ACTIVE`), the lead's current temperature must equal the campaign's `temperature_target` (else `ERR_TEMPERATURE_MISMATCH`), and the lead must not already hold an `ENROLLED` or `PAUSED` enrollment (else `ERR_LEAD_ALREADY_ENROLLED`)."

    Design: Difficulty/cross_entity_state_dependency/enrollment_blocked_when_campaign_not_active
    """
    ctx = ctx_claimed_lead_with_campaign(campaign_activate=False)  # campaign stays DRAFT
    assert ctx["lead"]["temperature"] == "COLD", "Temperature matches the target; only the campaign state blocks"

    res = api.create_nurture_enrollment(
        nurture_enrollment_payload(ctx["campaign"]["id"], ctx["lead"]["id"]),
        make_team_leader_headers(ctx["leader"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE, expected_status=409)

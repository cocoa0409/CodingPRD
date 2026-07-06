"""Hearing calendar, notice, and agenda placement: notice period, calendar buffer,
optimistic concurrency, and the ACCEPTED->SCHEDULED gate ordering (PRD §2.8, §3.3, §3.4)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    agenda_item_payload, notice_payload, hearing_payload,
    assert_instant_equals,
    build_accepted, build_submitted, build_scheduled,
    create_hearing, place_agenda,
)
from test_helpers import api_client as api


# --- Notice period boundary (exactly the statutory minimum) ---------------

def test_notice_period_exactly_ten_days_accepted(clerk_headers):
    """PRD §3.4: "the notice period must be satisfied — the whole-day span from the notice's
    mailed_at to the hearing's scheduled_date must be at least the statutory minimum for the
    body, which is 10 days for a PLANNING_COMMISSION hearing and 15 days for a CITY_COUNCIL
    hearing, else ERR_NOTICE_PERIOD_NOT_MET."

    Design: Difficulty/boundary_precision_check/notice_period_exactly_min_days_passes
    """
    ctx = build_accepted(app_type="VARIANCE", with_notice=True)  # notice mailed 2026-06-01
    hearing = create_hearing(scheduled_date="2026-06-11T00:00:00Z")  # exactly 10 whole days
    resp = api.place_agenda_item(
        hearing["id"], agenda_item_payload(ctx["app"]["id"], hearing["version"]), clerk_headers)
    data = validate_success(resp, 201)
    assert data["status"] == "PLACED", f"agenda item must be PLACED, got {data['status']}"


def test_application_scheduled_after_exact_min_notice(clerk_headers):
    """PRD §3.4: "Placing an ACCEPTED application onto a hearing's agenda is the clerk action
    that drives the application from ACCEPTED to SCHEDULED."

    Design: Difficulty/boundary_precision_check/notice_period_exactly_min_days_passes
    """
    ctx = build_accepted(app_type="VARIANCE", with_notice=True)
    hearing = create_hearing(scheduled_date="2026-06-11T00:00:00Z")
    api.place_agenda_item(
        hearing["id"], agenda_item_payload(ctx["app"]["id"], hearing["version"]), clerk_headers)
    app = api.get_application(ctx["app"]["id"], clerk_headers).json()["data"]
    assert app["status"] == "SCHEDULED", f"application must be SCHEDULED, got {app['status']}"


def test_notice_period_nine_days_rejected(clerk_headers):
    """PRD §3.4: "the whole-day span from the notice's mailed_at to the hearing's
    scheduled_date must be at least the statutory minimum for the body, which is 10 days for
    a PLANNING_COMMISSION hearing ... else ERR_NOTICE_PERIOD_NOT_MET."

    Design: Corner/validations/notice_period_nine_days_returns_period_not_met
    """
    ctx = build_accepted(app_type="VARIANCE", with_notice=True)
    hearing = create_hearing(scheduled_date="2026-06-10T00:00:00Z")  # only 9 whole days
    resp = api.place_agenda_item(
        hearing["id"], agenda_item_payload(ctx["app"]["id"], hearing["version"]), clerk_headers)
    validate_error(resp, ApiErrorId.ERR_NOTICE_PERIOD_NOT_MET)


# --- Notice present precondition ------------------------------------------

def test_placement_without_notice_rejected(clerk_headers):
    """PRD §3.4: "a SENT notice must already exist for the application (ERR_NOTICE_MISSING)".

    Design: Corner/validations/place_without_notice_returns_notice_missing
    """
    ctx = build_accepted(app_type="VARIANCE", with_notice=False)
    hearing = create_hearing(scheduled_date="2026-07-11T00:00:00Z")  # notice period would pass
    resp = api.place_agenda_item(
        hearing["id"], agenda_item_payload(ctx["app"]["id"], hearing["version"]), clerk_headers)
    validate_error(resp, ApiErrorId.ERR_NOTICE_MISSING)


# --- Priority pair: state (not ACCEPTED) beats notice period --------------

def test_not_accepted_beats_notice_period(clerk_headers):
    """PRD §3.4: "The placement is subject, in the fixed order of §2.5, to these gates: the
    application must be in ACCEPTED (ERR_APPLICATION_NOT_ACCEPTED) and the hearing must be
    SCHEDULED (ERR_HEARING_NOT_OPEN) with a free slot (ERR_AGENDA_FULL); the supplied
    expected_hearing_version must match the hearing's version (ERR_STALE_HEARING_VERSION); a
    SENT notice must already exist for the application (ERR_NOTICE_MISSING); and the notice
    period must be satisfied ... else ERR_NOTICE_PERIOD_NOT_MET."

    Design: Difficulty/priority_pair_validation_conflict/agenda_state_beats_notice_period
    """
    ctx = build_submitted(app_type="VARIANCE")  # SUBMITTED, never made ACCEPTED
    from test_helpers import create_notice
    create_notice(ctx["app"]["id"])            # notice mailed 2026-06-01
    hearing = create_hearing(scheduled_date="2026-06-05T00:00:00Z")  # only 4 days (also violated)
    resp = api.place_agenda_item(
        hearing["id"], agenda_item_payload(ctx["app"]["id"], hearing["version"]), clerk_headers)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_ACCEPTED)


def test_placement_rejected_leaves_application_submitted(clerk_headers):
    """PRD §3.4: "Placing an ACCEPTED application onto a hearing's agenda is the clerk action
    that drives the application from ACCEPTED to SCHEDULED."

    Design: Difficulty/priority_pair_validation_conflict/agenda_state_beats_notice_period
    """
    ctx = build_submitted(app_type="VARIANCE")
    from test_helpers import create_notice
    create_notice(ctx["app"]["id"])
    hearing = create_hearing(scheduled_date="2026-06-05T00:00:00Z")
    api.place_agenda_item(
        hearing["id"], agenda_item_payload(ctx["app"]["id"], hearing["version"]), clerk_headers)
    app = api.get_application(ctx["app"]["id"], clerk_headers).json()["data"]
    assert app["status"] == "SUBMITTED", \
        f"a rejected placement must not transition the application, got {app['status']}"


# --- Cross-entity: hearing must be SCHEDULED (not CANCELLED) ---------------

def test_placement_on_cancelled_hearing_rejected(clerk_headers):
    """PRD §3.4: "the hearing must be SCHEDULED (ERR_HEARING_NOT_OPEN)".

    Design: Difficulty/cross_entity_state_dependency/agenda_placement_requires_hearing_scheduled
    """
    ctx = build_accepted(app_type="VARIANCE", with_notice=True)
    hearing = create_hearing()
    validate_success(api.cancel_hearing(hearing["id"], clerk_headers), 200)
    resp = api.place_agenda_item(
        hearing["id"], agenda_item_payload(ctx["app"]["id"], hearing["version"]), clerk_headers)
    validate_error(resp, ApiErrorId.ERR_HEARING_NOT_OPEN)


def test_application_stays_accepted_after_hearing_not_open(clerk_headers):
    """PRD §3.4: "Placing an ACCEPTED application onto a hearing's agenda is the clerk action
    that drives the application from ACCEPTED to SCHEDULED."

    Design: Difficulty/cross_entity_state_dependency/agenda_placement_requires_hearing_scheduled
    """
    ctx = build_accepted(app_type="VARIANCE", with_notice=True)
    hearing = create_hearing()
    validate_success(api.cancel_hearing(hearing["id"], clerk_headers), 200)
    api.place_agenda_item(
        hearing["id"], agenda_item_payload(ctx["app"]["id"], hearing["version"]), clerk_headers)
    app = api.get_application(ctx["app"]["id"], clerk_headers).json()["data"]
    assert app["status"] == "ACCEPTED", \
        f"a rejected placement must leave the application ACCEPTED, got {app['status']}"


# --- Hearing calendar buffer ----------------------------------------------

def test_second_hearing_within_buffer_rejected(clerk_headers):
    """PRD §3.4: "for the same body, its scheduled_date must be at least 14 whole days from
    the scheduled_date of every existing hearing of that body that is not CANCELLED; a closer
    date is rejected with ERR_HEARING_CALENDAR_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/hearing_calendar_buffer_same_body
    """
    create_hearing(scheduled_date="2026-06-11T00:00:00Z")
    resp = api.create_hearing(
        hearing_payload(body="PLANNING_COMMISSION", scheduled_date="2026-06-20T00:00:00Z"),
        clerk_headers)  # only 9 days from the first
    validate_error(resp, ApiErrorId.ERR_HEARING_CALENDAR_CONFLICT)


def test_hearing_beyond_buffer_allowed(clerk_headers):
    """PRD §3.4: "for the same body, its scheduled_date must be at least 14 whole days from
    the scheduled_date of every existing hearing of that body that is not CANCELLED; a closer
    date is rejected with ERR_HEARING_CALENDAR_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/hearing_calendar_buffer_same_body
    """
    create_hearing(scheduled_date="2026-06-11T00:00:00Z")
    resp = api.create_hearing(
        hearing_payload(body="PLANNING_COMMISSION", scheduled_date="2026-06-25T00:00:00Z"),
        clerk_headers)  # exactly 14 days from the first
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


# --- Optimistic concurrency on agenda placement ---------------------------

def test_stale_hearing_version_rejected(clerk_headers):
    """PRD §2.8: "If another writer has advanced the hearing's version since that read —
    because a competing placement already consumed a slot — the value no longer matches the
    hearing's current version, and the placement is rejected with ERR_STALE_HEARING_VERSION
    (HTTP 412) before capacity is re-read."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_hearing_version_returns_412
    """
    ctx1 = build_accepted(app_type="VARIANCE", with_notice=True)
    ctx2 = build_accepted(app_type="VARIANCE", with_notice=True)
    hearing = create_hearing()
    stale_version = hearing["version"]
    place_agenda(hearing["id"], ctx1["app"]["id"], stale_version)  # advances hearing.version
    resp = api.place_agenda_item(
        hearing["id"], agenda_item_payload(ctx2["app"]["id"], stale_version), clerk_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_HEARING_VERSION)


def test_placement_increments_hearing_version(clerk_headers):
    """PRD §3.4: "decrements the hearing's agenda_slots_remaining by one, and increments the
    hearing's version by one."

    Design: Corner/cross_cutting_complexity_layers/hearing_version_increments_on_agenda_placement
    """
    ctx = build_accepted(app_type="VARIANCE", with_notice=True)
    hearing = create_hearing()
    before = hearing["version"]
    place_agenda(hearing["id"], ctx["app"]["id"], before)
    after = api.get_hearing(hearing["id"], clerk_headers).json()["data"]["version"]
    assert after == before + 1, f"placement must increment version by exactly 1: {before} -> {after}"


# --- Notice recipient count and the logical-clock default -----------------

def test_notice_uses_expanded_radius_for_sensitive_parcel(clerk_headers):
    """PRD §3.3: "If the parcel's sensitive_area flag is set, the mailing reaches the expanded
    500-foot audience: recipient_count is set to the parcel's expanded_neighbor_count and
    used_expanded_radius is recorded as true."

    Design: Corner/entities/notice_recipient_count_expanded_radius_when_sensitive
    """
    ctx = build_submitted(app_type="VARIANCE", parcel_over={
        "sensitive_area": True, "neighbor_parcel_count": 12, "expanded_neighbor_count": 20})
    resp = api.create_notice(ctx["app"]["id"], notice_payload("MAILED"), clerk_headers)
    data = validate_success(resp, 201)
    assert data["recipient_count"] == 20, f"recipient_count must be the expanded count 20, got {data['recipient_count']}"
    assert data["used_expanded_radius"] is True


def test_clock_defaults_to_may_first(clerk_headers):
    """PRD §2.4: "At startup the clock reads 2026-05-01T00:00:00Z, and it never falls back to
    wall-clock time."
    PRD §3.3: "The server stamps mailed_at with the current clock reading — this is the instant
    the statutory notice period begins".

    Design: Corner/cross_cutting_complexity_layers/clock_default_is_may_first_2026
    """
    ctx = build_submitted(app_type="VARIANCE", clock=None)  # clock never moved from its default
    resp = api.create_notice(ctx["app"]["id"], notice_payload("MAILED"), clerk_headers)
    data = validate_success(resp, 201)
    assert_instant_equals(data["mailed_at"], "2026-05-01T00:00:00Z", "mailed_at (startup clock)")


# --- Findings requirement / agenda-not-empty ------------------------------

def test_approve_without_findings_rejected(commissioner_headers):
    """PRD §3.5: "An APPROVE decision requires at least one finding that supports approval; if
    none is supplied the decision is refused with ERR_FINDINGS_REQUIRED."

    Design: Corner/validations/decide_without_findings_returns_findings_required
    """
    ctx = build_scheduled(app_type="VARIANCE")
    resp = api.decide_agenda_item(
        ctx["item"]["id"], {"decision": "APPROVE", "findings": []}, commissioner_headers)
    validate_error(resp, ApiErrorId.ERR_FINDINGS_REQUIRED)


def test_cancel_hearing_with_placed_item_rejected(clerk_headers):
    """PRD §3.4: "A Clerk may cancel a hearing, moving it from SCHEDULED to CANCELLED, but
    only when it holds no PLACED agenda items; otherwise the cancellation is refused with
    ERR_AGENDA_NOT_EMPTY."

    Design: Corner/state_machines/cancel_hearing_with_placed_item_returns_agenda_not_empty
    """
    ctx = build_scheduled(app_type="VARIANCE")
    resp = api.cancel_hearing(ctx["hearing"]["id"], clerk_headers)
    validate_error(resp, ApiErrorId.ERR_AGENDA_NOT_EMPTY)

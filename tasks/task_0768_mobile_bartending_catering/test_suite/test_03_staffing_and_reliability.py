"""Assignment creation safety checks, labor cost, reliability scoring, and the
bartender travel-buffer overlap rule.

Design queues:
  A (Difficulty): dual_variant_calc/bartender_reliability_strict_vs_lenient_diverge,
                  priority_pair_validation_conflict/assignment_safety_beats_temporal,
                  resource_temporal_overlap/bartender_shift_buffer_overlap
  B (Corner): calculations & validations for assignments; empty-history baseline
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_draft_event, add_assignment, create_bartender,
    setup_reliability_no_show_and_cancel, make_bartender_with_one_no_show,
    TEST_USERS, make_bartender_headers, ApiErrorId,
    create_client_payload, create_package_payload, create_event_payload,
    make_client_headers, assert_bartender,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc / bartender_reliability_strict_vs_lenient_diverge
# ---------------------------------------------------------------------------
def test_strict_score_penalizes_no_show_and_bartender_cancel(api):
    """PRD §3.5: "the strict score (reliability_score_strict) is 100 multiplied
    by completed divided by total, then reduced by 15 for each no-show and by 5
    for each bartender cancel, rounded, and floored at 0."

    Design: Difficulty/dual_variant_calc/bartender_reliability_strict_vs_lenient_diverge
    """
    result = setup_reliability_no_show_and_cancel(api)
    assert result["bartender"]["reliability_score_strict"] == 0


def test_lenient_score_credits_half_cancel_and_diverges_from_strict(api):
    """PRD §3.5: "The lenient score (reliability_score_lenient) is 100
    multiplied by the quantity (completed plus half of cancels) divided by
    total, then reduced by 8 for each no-show, rounded, and floored at 0."

    Design: Difficulty/dual_variant_calc/bartender_reliability_strict_vs_lenient_diverge
    """
    b = setup_reliability_no_show_and_cancel(api)["bartender"]
    assert b["reliability_score_lenient"] == 17
    assert b["reliability_score_strict"] != b["reliability_score_lenient"]


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict / assignment_safety_beats_temporal
# ---------------------------------------------------------------------------
def test_expired_certification_rejected_before_service(api):
    """PRD §3.5: "The bartender's certification_expiry must fall strictly after
    the event's event_start; a certification that has lapsed by service time is
    rejected with ERR_BARTENDER_CERT_EXPIRED (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/assignment_safety_beats_temporal
    """
    bundle = create_draft_event(api)
    bartender = create_bartender(api, certification_expiry="2026-01-01T00:00:00Z")
    ev_id = bundle["event"]["id"]
    ver = bundle["event"]["version"]
    resp = api.create_assignment(ev_id, {
        "bartender_id": bartender["id"], "shift_start": "2026-06-01T17:00:00Z",
        "shift_end": "2026-06-01T23:30:00Z", "role_on_event": "BACK",
        "expected_event_version": ver,
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_BARTENDER_CERT_EXPIRED.value)


def test_certification_expiring_exactly_at_event_start_rejected(api):
    """PRD §3.5: "The bartender's certification_expiry must fall strictly after
    the event's event_start; a certification that has lapsed by service time is
    rejected with ERR_BARTENDER_CERT_EXPIRED (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/assignment_safety_beats_temporal
    """
    bundle = create_draft_event(api)  # event_start defaults to 2026-06-01T18:00:00Z
    bartender = create_bartender(api, certification_expiry="2026-06-01T18:00:00Z")
    ev_id = bundle["event"]["id"]
    ver = bundle["event"]["version"]
    resp = api.create_assignment(ev_id, {
        "bartender_id": bartender["id"], "shift_start": "2026-06-01T17:00:00Z",
        "shift_end": "2026-06-01T23:30:00Z", "role_on_event": "BACK",
        "expected_event_version": ver,
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_BARTENDER_CERT_EXPIRED.value)


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap / bartender_shift_buffer_overlap
# ---------------------------------------------------------------------------
def test_second_shift_within_travel_buffer_rejected(api):
    """PRD §2.9: "A bartender's shift is dilated by a travel buffer of 90
    minutes on each side before overlap is tested against that bartender's
    other non-terminal shifts; because of the buffer, even shifts that merely
    sit close together are treated as conflicting."

    Design: Difficulty/resource_temporal_overlap/bartender_shift_buffer_overlap
    """
    bartender = create_bartender(api)
    b_a = create_draft_event(api, title="A",
                             event_start="2026-06-01T18:00:00Z",
                             event_end="2026-06-01T23:00:00Z")
    b_b = create_draft_event(api, title="B",
                             event_start="2026-06-02T00:30:00Z",
                             event_end="2026-06-02T04:00:00Z")
    add_assignment(api, b_a["event"]["id"], bartender["id"], role_on_event="BACK",
                   shift_start="2026-06-01T17:00:00Z", shift_end="2026-06-01T23:30:00Z")
    # Second shift begins only 60 min after the first ends (< 90-min buffer).
    ver_b = b_b["event"]["version"]
    resp = api.create_assignment(b_b["event"]["id"], {
        "bartender_id": bartender["id"], "shift_start": "2026-06-02T00:30:00Z",
        "shift_end": "2026-06-02T04:00:00Z", "role_on_event": "BACK",
        "expected_event_version": ver_b,
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_BARTENDER_DOUBLE_BOOKED.value)


def test_second_shift_beyond_buffer_is_allowed(api):
    """PRD §2.9: "A bartender's shift is dilated by a travel buffer of 90
    minutes on each side before overlap is tested against that bartender's
    other non-terminal shifts; because of the buffer, even shifts that merely
    sit close together are treated as conflicting."

    Design: Difficulty/resource_temporal_overlap/bartender_shift_buffer_overlap
    """
    bartender = create_bartender(api)
    bundle = create_draft_event(api)
    ev_id = bundle["event"]["id"]
    add_assignment(api, ev_id, bartender["id"], role_on_event="BACK",
                   shift_start="2026-06-01T17:00:00Z", shift_end="2026-06-01T19:00:00Z")
    # A shift starting 22:30 leaves a 210-min gap; buffers (20:30 vs 21:00) do
    # not touch, so the second create is accepted.
    resp = api.create_assignment(ev_id, {
        "bartender_id": bartender["id"], "shift_start": "2026-06-01T22:30:00Z",
        "shift_end": "2026-06-01T23:30:00Z", "role_on_event": "BACK",
        "expected_event_version": get_success_data(api.get_event(ev_id, COORD))["version"],
    }, COORD)
    validate_success(resp, 201)


# ---------------------------------------------------------------------------
# Queue B — calculations / assignment_labor_cost
# ---------------------------------------------------------------------------
def test_labor_cost_regular_hours_no_overtime(api):
    """PRD §3.5: "The shift hours (shift_hours) are the duration from
    shift_start to shift_end in hours, rounded up to the nearest quarter hour."
    PRD §3.5: "The labor cost (labor_cost_cents) treats the first 8 shift hours
    as regular time and any hours beyond 8 as overtime: it is the regular hours
    multiplied by the bartender's hourly_rate_cents, plus the overtime hours
    multiplied by hourly_rate_cents and again by an overtime multiplier of 1.5,
    with the total rounded."

    Design: Corner/calculations/assignment_labor_cost_regular_hours
    """
    bundle = create_draft_event(api)
    bartender = create_bartender(api, hourly_rate_cents=4000)
    asg = add_assignment(api, bundle["event"]["id"], bartender["id"],
                         role_on_event="BACK",
                         shift_start="2026-06-01T18:00:00Z",
                         shift_end="2026-06-01T23:30:00Z")
    assert asg["shift_hours"] == 5.5
    assert asg["labor_cost_cents"] == 22000


def test_labor_cost_applies_overtime_beyond_eight_hours(api):
    """PRD §3.5: "The labor cost (labor_cost_cents) treats the first 8 shift
    hours as regular time and any hours beyond 8 as overtime: it is the regular
    hours multiplied by the bartender's hourly_rate_cents, plus the overtime
    hours multiplied by hourly_rate_cents and again by an overtime multiplier of
    1.5, with the total rounded."

    Design: Corner/calculations/assignment_labor_cost_overtime
    """
    bundle = create_draft_event(api)
    bartender = create_bartender(api, hourly_rate_cents=4000)
    asg = add_assignment(api, bundle["event"]["id"], bartender["id"],
                         role_on_event="LEAD",
                         shift_start="2026-06-01T13:00:00Z",
                         shift_end="2026-06-01T23:00:00Z")
    assert asg["shift_hours"] == 10
    assert asg["labor_cost_cents"] == 44000


# ---------------------------------------------------------------------------
# Queue B — validations for assignment creation
# ---------------------------------------------------------------------------
def test_assignment_jurisdiction_mismatch_rejected(api):
    """PRD §3.5: "The bartender's home_state_code must equal the event's
    venue_state_code, since the bartender must be licensed in the venue's ABC
    jurisdiction; a mismatch is rejected with ERR_JURISDICTION_MISMATCH (HTTP
    422)."

    Design: Corner/validations/assignment_jurisdiction_mismatch
    """
    bundle = create_draft_event(api, venue_state_code="CA")
    bartender = create_bartender(api, home_state_code="NY")
    ev_id = bundle["event"]["id"]
    resp = api.create_assignment(ev_id, {
        "bartender_id": bartender["id"], "shift_start": "2026-06-01T17:00:00Z",
        "shift_end": "2026-06-01T23:30:00Z", "role_on_event": "BACK",
        "expected_event_version": bundle["event"]["version"],
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_JURISDICTION_MISMATCH.value)


def test_inactive_bartender_cannot_be_assigned(api):
    """PRD §3.5: "The bartender's `availability_status` must be `AVAILABLE` or
    `ENGAGED` — an `INACTIVE` bartender cannot be assigned and yields
    `ERR_BARTENDER_UNAVAILABLE` (HTTP 409)."

    Design: Corner/validations/assignment_bartender_unavailable
    """
    bundle = create_draft_event(api)
    bartender = create_bartender(api)
    get_success_data(api.deactivate_bartender(bartender["id"], ADMIN))
    ev_id = bundle["event"]["id"]
    resp = api.create_assignment(ev_id, {
        "bartender_id": bartender["id"], "shift_start": "2026-06-01T17:00:00Z",
        "shift_end": "2026-06-01T23:30:00Z", "role_on_event": "BACK",
        "expected_event_version": bundle["event"]["version"],
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_BARTENDER_UNAVAILABLE.value)


def test_lead_assignment_requires_sufficient_strict_reliability(api):
    """PRD §3.5: "A LEAD assignment additionally requires that the bartender's
    reliability_score_strict be at least 70; a lower strict score is rejected
    with ERR_INSUFFICIENT_RELIABILITY (HTTP 422), while BACK assignments carry
    no reliability gate."

    Design: Corner/validations/assignment_lead_insufficient_reliability
    """
    low = make_bartender_with_one_no_show(api)
    bartender = low["bartender"]
    # A fresh event for the LEAD attempt (assignment checks run at create time).
    bundle = create_draft_event(api, title="B",
                                event_start="2026-06-05T18:00:00Z",
                                event_end="2026-06-05T23:00:00Z")
    ev_id = bundle["event"]["id"]
    resp = api.create_assignment(ev_id, {
        "bartender_id": bartender["id"], "shift_start": "2026-06-05T17:00:00Z",
        "shift_end": "2026-06-05T23:30:00Z", "role_on_event": "LEAD",
        "expected_event_version": bundle["event"]["version"],
    }, COORD)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_RELIABILITY.value)


# ---------------------------------------------------------------------------
# Queue B — entities / bartender_reliability_empty_history_baseline
# ---------------------------------------------------------------------------
def test_new_bartender_reliability_baseline_is_100(api):
    """PRD §3.1: "both reliability scores — reliability_score_strict and
    reliability_score_lenient — are initialized to 100 to reflect an empty
    history."

    Design: Corner/entities/bartender_reliability_empty_history_baseline
    """
    bartender = create_bartender(api)
    data = get_success_data(api.get_bartender(bartender["id"], COORD))
    assert_bartender(data)
    assert data["reliability_score_strict"] == 100
    assert data["reliability_score_lenient"] == 100
    assert data["availability_status"] == "AVAILABLE"

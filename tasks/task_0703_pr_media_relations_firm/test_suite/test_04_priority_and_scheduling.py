"""Validation-priority precedence pairs and interview interval-overlap semantics."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_client,
    create_campaign,
    setup_campaign_with_media_list,
    create_pitch_in_state,
    create_press_release,
    setup_interview_scenario,
    create_interview,
    create_spokesperson,
    create_outlet,
    create_journalist,
    TEST_USERS,
)

AM = TEST_USERS["account_manager_headers"]
MS = TEST_USERS["media_specialist_headers"]
SC = TEST_USERS["scheduling_coordinator_headers"]


# =========================================================================== #
# priority_pair_validation_conflict / state_vs_business_safety_release_invalid_state_wins
# =========================================================================== #

def test_release_draft_press_release_with_future_embargo_reports_invalid_state(api):
    """PRD §2.8: "(7) state validity — the target resource is in a state from which the
    requested transition is legal, else `ERR_INVALID_STATE`;"
    PRD §2.8: "(9) embargo safety;"
    PRD §3.5: "Releasing advances a press release from `SCHEDULED` to `RELEASED`."

    A release attempted on a DRAFT (not SCHEDULED) press release whose embargo is also still
    in the future fails the priority-7 state check before the priority-9 embargo check, so
    the lower-priority-number state error wins: ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_release_invalid_state_wins
    """
    client = create_client()
    campaign = create_campaign(client["id"])
    validate_success(api.activate_campaign(campaign["id"], AM))
    # DRAFT press release (never scheduled), embargo in the future vs default clock 2026-03-01.
    pr = create_press_release(campaign["id"], headline="PR1", embargo_until="2026-03-20T00:00:00Z")
    assert pr["status"] == "DRAFT"

    resp = api.release_press_release(pr["id"], MS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_release_scheduled_before_embargo_reports_embargo_not_lifted(api):
    """PRD §3.5: "the current logical clock must be at or after `embargo_until` (an attempt
    before the embargo lifts is rejected with `ERR_EMBARGO_NOT_LIFTED`), and at least one
    distribution must exist for the release (otherwise `ERR_NO_DISTRIBUTIONS`)."

    Once the release is correctly SCHEDULED (so the state check passes), the embargo safety
    check at priority 9 is what fires for a too-early release: ERR_EMBARGO_NOT_LIFTED. This
    contrasts with the DRAFT case where the state check pre-empts.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_release_invalid_state_wins
    """
    scn = setup_campaign_with_media_list()
    from test_helpers import create_scheduled_press_release, create_distribution
    pr = create_scheduled_press_release(scn["campaign"]["id"], "2026-03-20T00:00:00Z", headline="PR2")
    create_distribution(pr["id"], scn["journalist"]["id"])
    assert pr["status"] == "SCHEDULED"

    resp = api.release_press_release(pr["id"], MS)
    validate_error(resp, ApiErrorId.ERR_EMBARGO_NOT_LIFTED.value)


# =========================================================================== #
# priority_pair_validation_conflict / forbidden_vs_state_pitch_send_forbidden_wins
# =========================================================================== #

def test_send_already_sent_pitch_by_unauthorized_role_reports_forbidden(api):
    """PRD §2.8: "(2) authorization — the role is permitted for the operation, else
    `ERR_FORBIDDEN`;"
    PRD §2.8: "(7) state validity — the target resource is in a state from which the
    requested transition is legal, else `ERR_INVALID_STATE`;"

    A SchedulingCoordinator (not permitted to send pitches) calling send on an already-SENT
    pitch violates both authorization (priority 2) and the DRAFT->SENT state precondition
    (priority 7); the higher-priority auth error wins: ERR_FORBIDDEN.

    Design: Difficulty/priority_pair_validation_conflict/forbidden_vs_state_pitch_send_forbidden_wins
    """
    scn = setup_campaign_with_media_list()
    pitch = create_pitch_in_state(
        scn["campaign"]["id"], scn["media_list"]["id"], scn["journalist"]["id"], "SENT")

    resp = api.send_pitch(pitch["id"], SC)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_send_already_sent_pitch_by_authorized_role_reports_invalid_state(api):
    """PRD §3.4: "Sending a pitch advances it from `DRAFT` to `SENT`. Sending has three
    preconditions: the campaign must be `ACTIVE`, else `ERR_CAMPAIGN_NOT_ACTIVE`; the
    recipient journalist must be `ACTIVE`, else `ERR_JOURNALIST_BLOCKLISTED`; and the source
    media list must be `ACTIVE`, else `ERR_MEDIA_LIST_NOT_ACTIVE`."
    PRD §2.8: "(7) state validity — the target resource is in a state from which the
    requested transition is legal, else `ERR_INVALID_STATE`;"

    When the authorized MediaSpecialist re-sends an already-SENT pitch, the auth check
    passes and the priority-7 state check fires instead: ERR_INVALID_STATE — isolating that
    the role boundary is what pre-empted in the forbidden case.

    Design: Difficulty/priority_pair_validation_conflict/forbidden_vs_state_pitch_send_forbidden_wins
    """
    scn = setup_campaign_with_media_list()
    pitch = create_pitch_in_state(
        scn["campaign"]["id"], scn["media_list"]["id"], scn["journalist"]["id"], "SENT")

    resp = api.send_pitch(pitch["id"], MS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# =========================================================================== #
# resource_temporal_overlap / spokesperson_overlap_with_prep_buffer
# =========================================================================== #

def test_spokesperson_buffered_window_blocks_disjoint_interview(api):
    """PRD §3.6: "The proposed half-open interval running from `starts_at` up to but not
    including `ends_at` must not overlap any other non-terminal interview for the same
    spokesperson once that spokesperson's `prep_buffer_minutes` padding is applied to both
    ends — a violation is rejected with `ERR_SPOKESPERSON_DOUBLE_BOOKED`."

    First interview [10:00,11:00) with a 30-min buffer occupies [09:30,11:30); a second at
    [11:15,12:00) (15-min raw gap) still collides with the buffered window.

    Design: Difficulty/resource_temporal_overlap/spokesperson_overlap_with_prep_buffer
    """
    client = create_client()
    campaign = create_campaign(client["id"])
    validate_success(api.activate_campaign(campaign["id"], AM))
    outlet = create_outlet()
    j1 = create_journalist(outlet["id"], full_name="Buf J1")
    j2 = create_journalist(outlet["id"], full_name="Buf J2")
    spokesperson = create_spokesperson(client["id"], full_name="Buf Spoke", prep_buffer_minutes=30)

    create_interview(campaign["id"], spokesperson["id"], j1["id"],
                     "2026-04-10T10:00:00Z", "2026-04-10T11:00:00Z")

    from test_helpers import create_interview_payload
    resp = api.create_interview(
        create_interview_payload(campaign["id"], spokesperson["id"], j2["id"],
                                 "2026-04-10T11:15:00Z", "2026-04-10T12:00:00Z"), SC)
    validate_error(resp, ApiErrorId.ERR_SPOKESPERSON_DOUBLE_BOOKED.value)


def test_spokesperson_interview_outside_buffer_succeeds(api):
    """PRD §3.6: "The proposed half-open interval running from `starts_at` up to but not
    including `ends_at` must not overlap any other non-terminal interview for the same
    spokesperson once that spokesperson's `prep_buffer_minutes` padding is applied to both
    ends — a violation is rejected with `ERR_SPOKESPERSON_DOUBLE_BOOKED`."

    A second interview far outside the buffered window [09:30,11:30) — at [12:00,13:00),
    a 30-min clear gap from the 11:30 buffer end — does not collide and is created.

    Design: Difficulty/resource_temporal_overlap/spokesperson_overlap_with_prep_buffer
    """
    client = create_client()
    campaign = create_campaign(client["id"])
    validate_success(api.activate_campaign(campaign["id"], AM))
    outlet = create_outlet()
    j1 = create_journalist(outlet["id"], full_name="Buf2 J1")
    j2 = create_journalist(outlet["id"], full_name="Buf2 J2")
    spokesperson = create_spokesperson(client["id"], full_name="Buf2 Spoke", prep_buffer_minutes=30)

    create_interview(campaign["id"], spokesperson["id"], j1["id"],
                     "2026-04-10T10:00:00Z", "2026-04-10T11:00:00Z")
    second = create_interview(campaign["id"], spokesperson["id"], j2["id"],
                              "2026-04-10T12:00:00Z", "2026-04-10T13:00:00Z")
    assert second["status"] == "REQUESTED"


# =========================================================================== #
# resource_temporal_overlap / journalist_half_open_adjacency_no_buffer
# =========================================================================== #

def test_journalist_adjacent_intervals_no_buffer_succeed(api):
    """PRD §3.6: "Independently, the same half-open interval must not overlap any other
    non-terminal interview for the same journalist, evaluated without any buffer padding — a
    violation is rejected with `ERR_JOURNALIST_DOUBLE_BOOKED`."

    Two interviews for the same journalist exactly adjacent at [10:00,11:00) and
    [11:00,12:00): half-open, zero gap, no buffer -> no overlap, second is created.

    Design: Difficulty/resource_temporal_overlap/journalist_half_open_adjacency_no_buffer
    """
    client = create_client()
    campaign = create_campaign(client["id"])
    validate_success(api.activate_campaign(campaign["id"], AM))
    outlet = create_outlet()
    journalist = create_journalist(outlet["id"], full_name="Adj J")
    s1 = create_spokesperson(client["id"], full_name="Adj S1", prep_buffer_minutes=0)
    s2 = create_spokesperson(client["id"], full_name="Adj S2", prep_buffer_minutes=0)

    create_interview(campaign["id"], s1["id"], journalist["id"],
                     "2026-04-10T10:00:00Z", "2026-04-10T11:00:00Z")
    second = create_interview(campaign["id"], s2["id"], journalist["id"],
                              "2026-04-10T11:00:00Z", "2026-04-10T12:00:00Z")
    assert second["status"] == "REQUESTED", "adjacent half-open intervals must not collide"


def test_journalist_overlapping_intervals_no_buffer_rejected(api):
    """PRD §3.6: "Independently, the same half-open interval must not overlap any other
    non-terminal interview for the same journalist, evaluated without any buffer padding — a
    violation is rejected with `ERR_JOURNALIST_DOUBLE_BOOKED`."

    A second interview for the same journalist at [10:30,11:30) genuinely overlaps the first
    [10:00,11:00) and is rejected — confirming the no-buffer half-open rule still catches
    true overlaps.

    Design: Difficulty/resource_temporal_overlap/journalist_half_open_adjacency_no_buffer
    """
    client = create_client()
    campaign = create_campaign(client["id"])
    validate_success(api.activate_campaign(campaign["id"], AM))
    outlet = create_outlet()
    journalist = create_journalist(outlet["id"], full_name="Ovl J")
    s1 = create_spokesperson(client["id"], full_name="Ovl S1", prep_buffer_minutes=0)
    s2 = create_spokesperson(client["id"], full_name="Ovl S2", prep_buffer_minutes=0)

    create_interview(campaign["id"], s1["id"], journalist["id"],
                     "2026-04-10T10:00:00Z", "2026-04-10T11:00:00Z")
    from test_helpers import create_interview_payload
    resp = api.create_interview(
        create_interview_payload(campaign["id"], s2["id"], journalist["id"],
                                 "2026-04-10T10:30:00Z", "2026-04-10T11:30:00Z"), SC)
    validate_error(resp, ApiErrorId.ERR_JOURNALIST_DOUBLE_BOOKED.value)

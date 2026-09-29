"""State machine corners: every declared edge of the partner, request, revision, offer,
agreement, engagement, milestone, review, scope-change and valuation lifecycles — the valid
transitions and their side effects, the terminal states that refuse a second call, and the
cascades one transition drags along."""
from datetime import datetime, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    add_second_volunteer,
    api_client,
    counter_payload,
    create_cycle,
    create_partner,
    deliverable_scores_payload,
    drive_review_to_outcome,
    handoff_payload,
    make_partner_contact_headers,
    make_program_manager_headers,
    milestone_payload,
    post_valuation,
    project_request_payload,
    read_agreement,
    read_cycle,
    read_deliverables,
    read_engagement,
    read_milestone,
    read_offer,
    read_request,
    read_scope,
    read_time_logs,
    read_valuation_records,
    read_volunteer,
    read_window,
    scope_change_request_payload,
    scope_definition_payload,
    set_clock,
    setup_accepted_engagement,
    setup_drafted_agreement,
    setup_engagement,
    setup_executed_agreement,
    setup_handed_off_engagement,
    setup_held_milestone_engagement,
    setup_in_progress_engagement,
    setup_offer,
    setup_scoped_request,
    setup_scoping_request,
    setup_sent_agreement,
    setup_submitted_engagement,
    time_log_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# The logical clock reads this instant at startup and only ever moves forward.
CLOCK_T0 = "2026-08-01T00:00:00Z"

# Small, deliberately tight capacity so the utilization ratio is a clean fraction.
CYCLE_SLOTS = 4
WINDOW_HOURS = 200.00

# A one-deliverable revision carrying the whole 100.00 weight and all 40.00 estimated hours.
SINGLE_DELIVERABLE = [
    {
        "title": "Findings memo",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 40.00,
        "acceptance_criteria": "Board-ready memo with cited findings.",
    }
]

# One eligible SENIOR volunteer with a verified TAX_LAW claim at proficiency 4, a ROUTINE
# request and a window that more than covers the 40.00 required hours scores
# 0.55*0.93 + 0.20*1.00 + 0.25*0.7500 = 0.8990 with a SENIOR multiplier of 1.00.
EXPECTED_MATCH_SCORE = 0.8990


def _instant(value):
    """Parse an ISO 8601 UTC timestamp so instants compare regardless of how many
    fractional digits the serializer emitted."""
    assert value is not None, "expected a timestamp, got null"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _same_instant(actual, expected):
    return _instant(actual) == _instant(expected)


# ---------------------------------------------------------------------------
# PartnerOrg standing
# ---------------------------------------------------------------------------
def test_01_suspending_a_partner_abandons_its_request_and_releases_the_offer(api):
    """PRD §3.1: "The transition stamps `suspended_at` from the logical clock; every project
    request of that partner sitting in `DRAFT`, `SCOPING`, `SCOPED`, `MATCHING` or `RESCOPING`
    moves to `ABANDONED`; each abandoned request in turn moves its `OFFERED` match offers to
    `WITHDRAWN` with `withdraw_reason` set to `PARTNER_SUSPENDED`; each such withdrawal
    subtracts that offer's `reserved_hours` from the holding window's `hours_committed` and
    forces the cycle's `slots_reserved` to be recomputed; and every engagement of that partner
    whose `work_status` is `NOT_STARTED`, `IN_PROGRESS`, `SUBMITTED` or `ACCEPTED` moves to
    `TERMINATED` with `termination_reason` set to `PARTNER_SUSPENDED`."

    Design: Corner/state_machines/sm_partner_active_to_suspended_runs_full_abandon_cascade
    """
    world = setup_offer(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)

    partner = validate_success(
        api_client.patch_partner_org_status(
            world["partner"]["id"], {"to_status": "SUSPENDED"}, world["pm_headers"]
        )
    )

    assert partner["status"] == "SUSPENDED", (
        f"Expected status SUSPENDED, got {partner['status']}"
    )
    assert _same_instant(partner["suspended_at"], CLOCK_T0), (
        f"Expected suspended_at at the logical clock {CLOCK_T0}, got "
        f"{partner['suspended_at']}"
    )

    request = read_request(world)
    assert request["status"] == "ABANDONED", (
        f"Expected the MATCHING request to be ABANDONED by the suspension, got "
        f"{request['status']}"
    )

    offer = read_offer(world)
    assert offer["status"] == "WITHDRAWN", (
        f"Expected the OFFERED offer to be WITHDRAWN, got {offer['status']}"
    )
    assert offer["withdraw_reason"] == "PARTNER_SUSPENDED", (
        f"Expected withdraw_reason PARTNER_SUSPENDED, got {offer['withdraw_reason']}"
    )

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.005), (
        f"Expected the 40.00 reserved hours released, got hours_committed "
        f"{window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(WINDOW_HOURS, abs=0.005), (
        f"Expected hours_remaining back at {WINDOW_HOURS}, got {window['hours_remaining']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved recomputed to 0, got {cycle['slots_reserved']}"
    )
    assert cycle["slots_committed"] == 0, (
        f"Expected slots_committed 0, got {cycle['slots_committed']}"
    )
    assert cycle["slots_available"] == CYCLE_SLOTS, (
        f"Expected slots_available {CYCLE_SLOTS}, got {cycle['slots_available']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.0000, abs=0.00005), (
        f"Expected utilization_ratio 0.0000, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"Expected posture OPEN, got {cycle['posture']}"
    )


# ---------------------------------------------------------------------------
# ProjectRequest lifecycle
# ---------------------------------------------------------------------------
def test_02_handing_a_draft_request_to_scoping_advances_status_and_version(api):
    """PRD §3.3: "The partner hands the work to the scoping team by moving the request
    `DRAFT → SCOPING`."
    PRD §3.3: "Nothing cascades from this transition beyond the request's own `updated_at` and
    `version`."
    PRD §2.4: "Most resources additionally carry `updated_at`, in the same timestamp format,
    refreshed on every mutation that touches the row, and `version`, an integer that starts at 1
    on creation and increases by exactly 1 on every mutation of that row."

    Design: Corner/state_machines/sm_request_draft_to_scoping_on_submit_for_scoping
    """
    pm = make_program_manager_headers()
    cycle = create_cycle(pm, capacity_slot_total=CYCLE_SLOTS)
    partner = create_partner(pm)
    partner_headers = make_partner_contact_headers(partner["id"])
    created = validate_success(
        api_client.create_project_request(
            project_request_payload(partner["id"], cycle["id"]), partner_headers
        ),
        201,
    )
    assert created["version"] == 1, (
        f"Expected the freshly filed request at version 1, got {created['version']}"
    )

    request = validate_success(
        api_client.submit_for_scoping(created["id"], partner_headers)
    )

    assert request["status"] == "SCOPING", (
        f"Expected status SCOPING after submit-for-scoping, got {request['status']}"
    )
    assert request["version"] == 2, (
        f"Expected version 2 after exactly one mutation, got {request['version']}"
    )
    assert request["active_scope_revision_no"] == 0, (
        f"Expected active_scope_revision_no still 0, got "
        f"{request['active_scope_revision_no']}"
    )
    assert request["closed_at"] is None, (
        f"Expected closed_at still null, got {request['closed_at']}"
    )


def test_03_submitting_an_abandoned_request_for_scoping_is_refused(api):
    """PRD §2.12: "The project request's `status` is in the from-set of the requested transition
    — on `POST /project-requests/{id}/submit-for-scoping`, `POST
    /project-requests/{id}/scope-definitions`, `POST /project-requests/{id}/match`, `POST
    /project-requests/{id}/rescope` and `POST /project-requests/{id}/abandon` — otherwise
    `ERR_INVALID_REQUEST_STATE` (409)."
    PRD §3.3: "In every case the request moves to `ABANDONED` and `closed_at` is stamped from
    the logical clock."

    Design: Corner/state_machines/sm_request_terminal_abandoned_cannot_be_submitted_for_scoping
    """
    pm = make_program_manager_headers()
    cycle = create_cycle(pm, capacity_slot_total=CYCLE_SLOTS)
    partner = create_partner(pm)
    partner_headers = make_partner_contact_headers(partner["id"])
    request = validate_success(
        api_client.create_project_request(
            project_request_payload(partner["id"], cycle["id"]), partner_headers
        ),
        201,
    )
    abandoned = validate_success(
        api_client.abandon_project_request(
            request["id"], pm, {"reason": "Partner withdrew the ask before scoping."}
        )
    )
    assert abandoned["status"] == "ABANDONED", (
        f"Setup expected an ABANDONED request, got {abandoned['status']}"
    )

    validate_error(
        api_client.submit_for_scoping(request["id"], partner_headers),
        ApiErrorId.ERR_INVALID_REQUEST_STATE,
    )

    after = validate_success(api_client.get_project_request(request["id"], pm))
    assert after["status"] == "ABANDONED", (
        f"Expected the request to stay ABANDONED, got {after['status']}"
    )
    assert _same_instant(after["closed_at"], CLOCK_T0), (
        f"Expected closed_at to keep its original {CLOCK_T0} stamp, got {after['closed_at']}"
    )


def test_04_abandoning_a_scoping_request_withdraws_its_draft_revision(api):
    """PRD §3.3: "Abandonment from `SCOPING` or `SCOPED` additionally moves every scope revision
    of the request whose `status` is `DRAFT` or `APPROVED` to `WITHDRAWN`, and when the withdrawn
    revision was the approved one, `active_scope_revision_no` resets to 0."
    PRD §3.3: "In every case the request moves to `ABANDONED` and `closed_at` is stamped from
    the logical clock."

    Design: Corner/state_machines/sm_request_draft_to_abandoned_withdraws_open_draft_revision
    """
    world = setup_scoping_request(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)

    request = validate_success(
        api_client.abandon_project_request(
            world["request"]["id"],
            world["pm_headers"],
            {"reason": "Board deferred the engagement."},
        )
    )

    assert request["status"] == "ABANDONED", (
        f"Expected status ABANDONED, got {request['status']}"
    )
    assert _same_instant(request["closed_at"], CLOCK_T0), (
        f"Expected closed_at stamped from the clock {CLOCK_T0}, got {request['closed_at']}"
    )

    scope = read_scope(world)
    assert scope["status"] == "WITHDRAWN", (
        f"Expected the DRAFT revision to be WITHDRAWN, got {scope['status']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 0, (
        f"Expected no cycle capacity to move, got slots_reserved {cycle['slots_reserved']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"Expected posture OPEN, got {cycle['posture']}"
    )


def test_05_abandoning_a_scoped_request_withdraws_its_approved_revision(api):
    """PRD §3.3: "Abandonment from `SCOPING` or `SCOPED` additionally moves every scope revision
    of the request whose `status` is `DRAFT` or `APPROVED` to `WITHDRAWN`, and when the withdrawn
    revision was the approved one, `active_scope_revision_no` resets to 0."

    Design: Corner/state_machines/sm_scope_approved_revision_moves_to_withdrawn_when_request_abandoned_from_scoped
    """
    world = setup_scoped_request(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)
    assert world["scope"]["status"] == "APPROVED", (
        f"Setup expected an APPROVED revision, got {world['scope']['status']}"
    )

    request = validate_success(
        api_client.abandon_project_request(
            world["request"]["id"],
            world["pm_headers"],
            {"reason": "Funding for the audit fell through."},
        )
    )

    assert request["status"] == "ABANDONED", (
        f"Expected status ABANDONED, got {request['status']}"
    )
    assert request["active_scope_revision_no"] == 0, (
        f"Expected active_scope_revision_no reset to 0, got "
        f"{request['active_scope_revision_no']}"
    )

    scope = read_scope(world)
    assert scope["status"] == "WITHDRAWN", (
        f"Expected the APPROVED revision to move to WITHDRAWN rather than SUPERSEDED, got "
        f"{scope['status']}"
    )


def test_06_a_second_draft_revision_withdraws_the_first(api):
    """PRD §3.3: "Any sibling revision still sitting in `DRAFT` moves to `WITHDRAWN` at once,
    and the parent request's `version` advances by one."
    PRD §3.3: "The new row is created in `status` `DRAFT`; its `revision_no` is one greater than
    the highest `revision_no` among its siblings on the same request, so the first is 1; its
    `authored_by_user_id` records the drafting specialist's own `X-User-ID`, which is the value
    the segregation-of-duties barrier later reads; its `deliverable_count` and
    `deliverable_weight_total_pct` both start at 0."

    Design: Corner/state_machines/sm_scope_draft_revision_two_withdraws_revision_one
    """
    world = setup_scoping_request(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)
    first = world["scope"]
    current = read_request(world)

    second = validate_success(
        api_client.create_scope_definition(
            world["request"]["id"],
            scope_definition_payload(
                current["version"],
                estimated_hours=48.00,
                complexity_factor=1.25,
                confidentiality_tier="ELEVATED",
                ip_disposition="RETAINED_BY_VOLUNTEER",
                supersedes_scope_id=first["id"],
            ),
            world["spec_headers"],
        ),
        201,
    )

    assert second["revision_no"] == 2, (
        f"Expected revision_no 2 on the second revision, got {second['revision_no']}"
    )
    assert second["supersedes_scope_id"] == first["id"], (
        f"Expected supersedes_scope_id {first['id']}, got {second['supersedes_scope_id']}"
    )
    assert second["status"] == "DRAFT", (
        f"Expected the new revision in DRAFT, got {second['status']}"
    )

    retired = read_scope(world, first["id"])
    assert retired["status"] == "WITHDRAWN", (
        f"Expected revision 1 to be WITHDRAWN at once, got {retired['status']}"
    )

    request = read_request(world)
    assert request["status"] == "SCOPING", (
        f"Expected the request to stay SCOPING, got {request['status']}"
    )
    assert request["active_scope_revision_no"] == 0, (
        f"Expected active_scope_revision_no 0 while no revision is APPROVED, got "
        f"{request['active_scope_revision_no']}"
    )


def test_07_approving_a_revision_scopes_the_request_and_pins_the_active_revision(api):
    """PRD §3.3: "On success the revision moves `DRAFT → APPROVED` with `approved_at` stamped
    from the logical clock and `approved_by_user_id` recording the approving contact's
    identifier, any sibling revision that was already `APPROVED` moves to `SUPERSEDED`, the
    request moves `SCOPING → SCOPED`, and the request's `active_scope_revision_no` is recomputed
    to the `revision_no` of the newly approved revision."

    Design: Corner/state_machines/sm_request_scoping_to_scoped_on_scope_approve_sets_active_revision
    """
    world = setup_scoping_request(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)

    scope = validate_success(
        api_client.approve_scope_definition(
            world["scope"]["id"], world["partner_headers"]
        )
    )

    assert scope["status"] == "APPROVED", (
        f"Expected status APPROVED, got {scope['status']}"
    )
    assert _same_instant(scope["approved_at"], CLOCK_T0), (
        f"Expected approved_at stamped from the clock {CLOCK_T0}, got {scope['approved_at']}"
    )
    assert scope["approved_by_user_id"] == world["partner"]["id"], (
        f"Expected approved_by_user_id {world['partner']['id']}, got "
        f"{scope['approved_by_user_id']}"
    )
    assert scope["deliverable_count"] == 2, (
        f"Expected deliverable_count 2, got {scope['deliverable_count']}"
    )
    assert scope["deliverable_weight_total_pct"] == pytest.approx(100.00, abs=0.005), (
        f"Expected deliverable_weight_total_pct 100.00, got "
        f"{scope['deliverable_weight_total_pct']}"
    )

    request = read_request(world)
    assert request["status"] == "SCOPED", (
        f"Expected the request to move SCOPING → SCOPED, got {request['status']}"
    )
    assert request["active_scope_revision_no"] == 1, (
        f"Expected active_scope_revision_no 1, got {request['active_scope_revision_no']}"
    )


# ---------------------------------------------------------------------------
# Matching and the offer
# ---------------------------------------------------------------------------
def test_08_matching_creates_the_offer_and_reserves_hours_and_a_slot(api):
    """PRD §3.4: "A winning selection writes a match offer in `status` `OFFERED` against the
    request, recording the winning `volunteer_id`, the `scope_definition_id` of the `APPROVED`
    revision pinned at this instant, the `availability_window_id` of the chosen window, and a
    `round_no` equal to the request's `failed_match_rounds` plus one at offer time — so the first
    offer on a request is round 1."
    PRD §3.4: "Its `reserved_hours` is the required-hours figure computed above, its `offered_at`
    is the logical clock, and its `expires_at` is `offered_at` plus a time-to-live chosen by the
    request's `urgency`: five days for a `ROUTINE` request, three days for an `ELEVATED` one, and
    a single day for a `CRITICAL` one."
    PRD §3.4: "Two ledger movements accompany the offer: the chosen window's `hours_committed`
    rises by the offer's `reserved_hours`, and the cycle's `slots_reserved` rises by one, after
    which the posture calculation reruns and may carry the cycle from `OPEN` to `RESTRICTED` or
    on to `FROZEN`."

    Design: Corner/state_machines/sm_request_scoped_to_matching_reserves_hours_and_slot
    """
    world = setup_scoped_request(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)

    offer = validate_success(
        api_client.match_project_request(
            world["request"]["id"], world["spec_headers"]
        ),
        201,
    )
    world["offer"] = offer

    assert offer["status"] == "OFFERED", (
        f"Expected status OFFERED, got {offer['status']}"
    )
    assert offer["volunteer_id"] == world["volunteer"]["id"], (
        f"Expected the only eligible volunteer {world['volunteer']['id']}, got "
        f"{offer['volunteer_id']}"
    )
    assert offer["availability_window_id"] == world["window"]["id"], (
        f"Expected the offer held against window {world['window']['id']}, got "
        f"{offer['availability_window_id']}"
    )
    assert offer["scope_definition_id"] == world["scope"]["id"], (
        f"Expected the APPROVED revision {world['scope']['id']} pinned, got "
        f"{offer['scope_definition_id']}"
    )
    assert offer["round_no"] == 1, (
        f"Expected round_no 1 on the first offer, got {offer['round_no']}"
    )
    assert offer["match_score"] == pytest.approx(EXPECTED_MATCH_SCORE, abs=0.00005), (
        f"Expected match_score {EXPECTED_MATCH_SCORE}, got {offer['match_score']}"
    )
    assert offer["reserved_hours"] == pytest.approx(40.00, abs=0.005), (
        f"Expected reserved_hours 40.00 (40.00 estimated hours times complexity 1.00), got "
        f"{offer['reserved_hours']}"
    )
    assert _same_instant(offer["offered_at"], CLOCK_T0), (
        f"Expected offered_at at the clock {CLOCK_T0}, got {offer['offered_at']}"
    )
    assert _same_instant(offer["expires_at"], "2026-08-06T00:00:00Z"), (
        f"Expected expires_at five days after offered_at, got {offer['expires_at']}"
    )
    assert offer["responded_at"] is None, (
        f"Expected a null responded_at, got {offer['responded_at']}"
    )
    assert offer["decline_reason"] is None, (
        f"Expected a null decline_reason, got {offer['decline_reason']}"
    )
    assert offer["withdraw_reason"] is None, (
        f"Expected a null withdraw_reason, got {offer['withdraw_reason']}"
    )

    request = read_request(world)
    assert request["status"] == "MATCHING", (
        f"Expected the request to move SCOPED → MATCHING, got {request['status']}"
    )
    assert request["failed_match_rounds"] == 0, (
        f"Expected failed_match_rounds still 0, got {request['failed_match_rounds']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 1, (
        f"Expected slots_reserved 1, got {cycle['slots_reserved']}"
    )
    assert cycle["slots_committed"] == 0, (
        f"Expected slots_committed 0, got {cycle['slots_committed']}"
    )
    assert cycle["slots_available"] == CYCLE_SLOTS - 1, (
        f"Expected slots_available {CYCLE_SLOTS - 1}, got {cycle['slots_available']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.2500, abs=0.00005), (
        f"Expected utilization_ratio 0.2500, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"Expected posture OPEN below the 0.8000 floor, got {cycle['posture']}"
    )

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(40.00, abs=0.005), (
        f"Expected hours_committed 40.00 after the reservation, got "
        f"{window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(WINDOW_HOURS - 40.00, abs=0.005), (
        f"Expected hours_remaining {WINDOW_HOURS - 40.00}, got {window['hours_remaining']}"
    )


def test_09_accepting_an_offer_converts_the_reserved_slot_into_a_committed_slot(api):
    """PRD §3.5: "The offered volunteer accepts, and the offer moves `OFFERED → ACCEPTED` while
    the request moves `MATCHING → ENGAGED`."
    PRD §3.5: "**Step one:** the new engagement is written with `work_status` `NOT_STARTED` and
    `valuation_status` `UNVALUED`, its `match_offer_id` pointing at the accepted offer, its
    `project_request_id`, `volunteer_id`, `cycle_id` and `availability_window_id` copied from the
    offer and its request, its `scope_definition_id` pinned to the offer's revision and never
    re-pointed afterwards, and its `committed_hours` seeded from the offer's `reserved_hours`."
    PRD §3.5: "The remaining engagement fields start at their defaults: `approved_hours` 0.00,
    `scope_creep_pct` 0, `creep_escalation_level` `NONE`, `quality_gate` `PENDING`,
    `confidentiality_attested` false, `handoff_artifact_count` 0, `missed_checkin_count` 0, and
    null `handoff_at`, `terminated_at` and `termination_reason`."
    PRD §3.5: "**Step two:** because the request became `ENGAGED`, the cycle's `slots_reserved`
    falls by one while `slots_committed` rises by one, and the posture calculation reruns — which
    may set `posture` to `FROZEN`."

    Design: Corner/state_machines/sm_offer_accepted_converts_reserved_slot_into_committed_slot
    """
    world = setup_offer(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)

    engagement = validate_success(
        api_client.accept_match_offer(
            world["offer"]["id"], world["volunteer_headers"]
        ),
        201,
    )
    world["engagement"] = engagement

    assert engagement["work_status"] == "NOT_STARTED", (
        f"Expected work_status NOT_STARTED, got {engagement['work_status']}"
    )
    assert engagement["valuation_status"] == "UNVALUED", (
        f"Expected valuation_status UNVALUED, got {engagement['valuation_status']}"
    )
    assert engagement["match_offer_id"] == world["offer"]["id"], (
        f"Expected match_offer_id {world['offer']['id']}, got {engagement['match_offer_id']}"
    )
    assert engagement["scope_definition_id"] == world["scope"]["id"], (
        f"Expected the offer's revision {world['scope']['id']} pinned, got "
        f"{engagement['scope_definition_id']}"
    )
    assert engagement["committed_hours"] == pytest.approx(40.00, abs=0.005), (
        f"Expected committed_hours seeded from the offer's 40.00 reserved hours, got "
        f"{engagement['committed_hours']}"
    )
    assert engagement["approved_hours"] == pytest.approx(0.00, abs=0.005), (
        f"Expected approved_hours 0.00, got {engagement['approved_hours']}"
    )
    assert engagement["creep_escalation_level"] == "NONE", (
        f"Expected creep_escalation_level NONE, got {engagement['creep_escalation_level']}"
    )
    assert engagement["quality_gate"] == "PENDING", (
        f"Expected quality_gate PENDING, got {engagement['quality_gate']}"
    )
    assert engagement["confidentiality_attested"] is False, (
        f"Expected confidentiality_attested false, got "
        f"{engagement['confidentiality_attested']}"
    )
    assert engagement["handoff_artifact_count"] == 0, (
        f"Expected handoff_artifact_count 0, got {engagement['handoff_artifact_count']}"
    )
    assert engagement["missed_checkin_count"] == 0, (
        f"Expected missed_checkin_count 0, got {engagement['missed_checkin_count']}"
    )
    assert engagement["handoff_at"] is None, (
        f"Expected a null handoff_at, got {engagement['handoff_at']}"
    )
    assert engagement["terminated_at"] is None, (
        f"Expected a null terminated_at, got {engagement['terminated_at']}"
    )
    assert engagement["termination_reason"] is None, (
        f"Expected a null termination_reason, got {engagement['termination_reason']}"
    )

    offer = read_offer(world)
    assert offer["status"] == "ACCEPTED", (
        f"Expected the offer ACCEPTED, got {offer['status']}"
    )
    assert _same_instant(offer["responded_at"], CLOCK_T0), (
        f"Expected responded_at stamped from the clock, got {offer['responded_at']}"
    )

    request = read_request(world)
    assert request["status"] == "ENGAGED", (
        f"Expected the request to move MATCHING → ENGAGED, got {request['status']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved back to 0, got {cycle['slots_reserved']}"
    )
    assert cycle["slots_committed"] == 1, (
        f"Expected slots_committed 1, got {cycle['slots_committed']}"
    )
    assert cycle["slots_available"] == CYCLE_SLOTS - 1, (
        f"Expected slots_available {CYCLE_SLOTS - 1}, got {cycle['slots_available']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.2500, abs=0.00005), (
        f"Expected utilization_ratio 0.2500, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"Expected posture OPEN, got {cycle['posture']}"
    )

    volunteer = read_volunteer(world)
    assert volunteer["open_engagement_count"] == 1, (
        f"Expected open_engagement_count 1, got {volunteer['open_engagement_count']}"
    )


def test_10_a_first_decline_releases_the_reservation_and_returns_the_request_to_scoped(api):
    """PRD §3.5: "The offer moves `OFFERED → DECLINED` with `responded_at` and the reason
    stamped, the holding window's `hours_committed` drops by the offer's `reserved_hours`, the
    cycle's `slots_reserved` drops by one and the posture recomputes, and the request's
    `failed_match_rounds` rises by one before the request advances as described below."
    PRD §3.5: "If the request's `failed_match_rounds` plus one is still below 2, the request
    returns to `SCOPED` (`MATCHING → SCOPED`) and the specialist may run the selector again,
    which will now skip every volunteer already approached."

    Design: Corner/state_machines/sm_offer_declined_first_round_returns_request_to_scoped
    """
    world = setup_offer(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)

    offer = validate_success(
        api_client.decline_match_offer(
            world["offer"]["id"],
            {"decline_reason": "SCHEDULE_CONFLICT"},
            world["volunteer_headers"],
        )
    )

    assert offer["status"] == "DECLINED", (
        f"Expected status DECLINED, got {offer['status']}"
    )
    assert offer["decline_reason"] == "SCHEDULE_CONFLICT", (
        f"Expected decline_reason SCHEDULE_CONFLICT, got {offer['decline_reason']}"
    )
    assert _same_instant(offer["responded_at"], CLOCK_T0), (
        f"Expected responded_at stamped from the clock {CLOCK_T0}, got "
        f"{offer['responded_at']}"
    )

    request = read_request(world)
    assert request["status"] == "SCOPED", (
        f"Expected the request back in SCOPED on the first failed round, got "
        f"{request['status']}"
    )
    assert request["failed_match_rounds"] == 1, (
        f"Expected failed_match_rounds 1, got {request['failed_match_rounds']}"
    )
    assert request["rescope_count"] == 0, (
        f"Expected rescope_count still 0, got {request['rescope_count']}"
    )
    assert request["active_scope_revision_no"] == 1, (
        f"Expected the approved revision still pinned at 1, got "
        f"{request['active_scope_revision_no']}"
    )

    scope = read_scope(world)
    assert scope["status"] == "APPROVED", (
        f"Expected the revision to stay APPROVED for the next round, got {scope['status']}"
    )

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.005), (
        f"Expected the 40.00 held hours released, got hours_committed "
        f"{window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(WINDOW_HOURS, abs=0.005), (
        f"Expected hours_remaining {WINDOW_HOURS}, got {window['hours_remaining']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved back to 0, got {cycle['slots_reserved']}"
    )
    assert cycle["slots_available"] == CYCLE_SLOTS, (
        f"Expected slots_available {CYCLE_SLOTS}, got {cycle['slots_available']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"Expected posture OPEN, got {cycle['posture']}"
    )


def test_11_a_second_decline_pushes_the_request_into_rescoping_and_supersedes_the_scope(api):
    """PRD §3.5: "If `failed_match_rounds` plus one has reached 2 while `rescope_count` is still
    below 3, the request moves `MATCHING → RESCOPING`: the same offer-release effects run,
    `failed_match_rounds` is incremented and then reset to 0, `rescope_count` rises by one, the
    currently `APPROVED` revision moves to `SUPERSEDED`, and `active_scope_revision_no` resets
    to 0."

    Design: Corner/state_machines/sm_offer_second_decline_pushes_request_to_rescoping_and_supersedes_scope
    """
    world = setup_offer(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)
    second = add_second_volunteer(world)

    validate_success(
        api_client.decline_match_offer(
            world["offer"]["id"],
            {"decline_reason": "SCHEDULE_CONFLICT"},
            world["volunteer_headers"],
        )
    )
    round_two = validate_success(
        api_client.match_project_request(world["request"]["id"], world["spec_headers"]),
        201,
    )
    assert round_two["round_no"] == 2, (
        f"Setup expected the re-run selector to open round 2, got {round_two['round_no']}"
    )
    assert round_two["volunteer_id"] == second["volunteer"]["id"], (
        f"Setup expected the selector to skip the volunteer already approached, got "
        f"{round_two['volunteer_id']}"
    )

    offer = validate_success(
        api_client.decline_match_offer(
            round_two["id"],
            {"decline_reason": "OUTSIDE_EXPERTISE"},
            second["volunteer_headers"],
        )
    )

    assert offer["status"] == "DECLINED", (
        f"Expected status DECLINED, got {offer['status']}"
    )

    request = read_request(world)
    assert request["status"] == "RESCOPING", (
        f"Expected the request to move MATCHING → RESCOPING once the second round failed, got "
        f"{request['status']}"
    )
    assert request["failed_match_rounds"] == 0, (
        f"Expected failed_match_rounds reset to 0 by the rescoping branch, got "
        f"{request['failed_match_rounds']}"
    )
    assert request["rescope_count"] == 1, (
        f"Expected rescope_count 1, got {request['rescope_count']}"
    )
    assert request["active_scope_revision_no"] == 0, (
        f"Expected active_scope_revision_no reset to 0, got "
        f"{request['active_scope_revision_no']}"
    )
    assert request["closed_at"] is None, (
        f"Expected closed_at still null with rescoping left, got {request['closed_at']}"
    )

    scope = read_scope(world)
    assert scope["status"] == "SUPERSEDED", (
        f"Expected the APPROVED revision to move to SUPERSEDED, got {scope['status']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved back to 0, got {cycle['slots_reserved']}"
    )
    assert read_window(world, window_id=second["window"]["id"],
                       volunteer_id=second["volunteer"]["id"])["hours_committed"] == \
        pytest.approx(0.00, abs=0.005), "Expected the second window's held hours released"


def test_12_restarting_scoping_on_a_rescoping_request_reopens_the_drafting_stage(api):
    """PRD §3.5: "A `ScopingSpecialist` restarts scoping on a request sitting in `RESCOPING`,
    moving it `RESCOPING → SCOPING` so that a fresh revision can be drafted, approved and matched
    again — the full `SCOPING → SCOPED → MATCHING` sequence runs a second time on new terms."

    Design: Corner/state_machines/sm_request_rescoping_to_scoping_on_rescope_endpoint
    """
    world = setup_offer(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)
    second = add_second_volunteer(world)
    validate_success(
        api_client.decline_match_offer(
            world["offer"]["id"],
            {"decline_reason": "SCHEDULE_CONFLICT"},
            world["volunteer_headers"],
        )
    )
    round_two = validate_success(
        api_client.match_project_request(world["request"]["id"], world["spec_headers"]),
        201,
    )
    validate_success(
        api_client.decline_match_offer(
            round_two["id"],
            {"decline_reason": "OUTSIDE_EXPERTISE"},
            second["volunteer_headers"],
        )
    )
    staged = read_request(world)
    assert staged["status"] == "RESCOPING", (
        f"Setup expected a RESCOPING request, got {staged['status']}"
    )

    request = validate_success(
        api_client.rescope_project_request(world["request"]["id"], world["spec_headers"])
    )

    assert request["status"] == "SCOPING", (
        f"Expected the request to move RESCOPING → SCOPING, got {request['status']}"
    )
    assert request["rescope_count"] == 1, (
        f"Expected rescope_count to stay 1 — the restart does not consume another allowance, "
        f"got {request['rescope_count']}"
    )
    assert request["failed_match_rounds"] == 0, (
        f"Expected failed_match_rounds 0, got {request['failed_match_rounds']}"
    )
    assert request["active_scope_revision_no"] == 0, (
        f"Expected active_scope_revision_no 0 while a fresh revision is drafted, got "
        f"{request['active_scope_revision_no']}"
    )


def test_13_the_checkpoint_expires_a_stale_offer_without_touching_reliability(api):
    """PRD §3.1: "First it sweeps expiry: every match offer in the cycle still in `OFFERED` whose
    `expires_at` is at or before the logical clock moves to `EXPIRED`, releasing its reserved
    hours and its reserved slot and incrementing the owning request's `failed_match_rounds`, with
    each increment advancing that request to `SCOPED`, `RESCOPING` or `ABANDONED` exactly as §3.5
    prescribes."
    PRD §3.5: "`responded_at` is stamped from the clock, the window hours and the reserved slot
    are released, and `failed_match_rounds` rises by one. Expiry is the only terminal outcome
    that leaves the volunteer's reliability inputs entirely untouched — the program does not
    attribute an unanswered offer to the volunteer."
    PRD §3.2: "A volunteer with no terminal engagement at all reads 0.7500 in both fields."

    Design: Corner/state_machines/sm_offer_expiry_sweep_marks_offer_expired_without_touching_reliability
    """
    world = setup_offer(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)
    lapsed = "2026-08-06T00:00:00Z"
    set_clock(lapsed, world["pm_headers"])

    validate_success(
        api_client.recalculate_program_cycle(world["cycle"]["id"], world["pm_headers"])
    )

    offer = read_offer(world)
    assert offer["status"] == "EXPIRED", (
        f"Expected the offer EXPIRED once the clock reached expires_at, got {offer['status']}"
    )
    assert _same_instant(offer["responded_at"], lapsed), (
        f"Expected responded_at stamped from the checkpoint clock {lapsed}, got "
        f"{offer['responded_at']}"
    )
    assert offer["decline_reason"] is None, (
        f"Expected no decline_reason on an expiry, got {offer['decline_reason']}"
    )
    assert offer["withdraw_reason"] is None, (
        f"Expected no withdraw_reason on an expiry, got {offer['withdraw_reason']}"
    )

    request = read_request(world)
    assert request["status"] == "SCOPED", (
        f"Expected the request back in SCOPED, got {request['status']}"
    )
    assert request["failed_match_rounds"] == 1, (
        f"Expected failed_match_rounds 1, got {request['failed_match_rounds']}"
    )

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.005), (
        f"Expected the reserved hours released, got hours_committed "
        f"{window['hours_committed']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 0, (
        f"Expected the reserved slot released, got slots_reserved {cycle['slots_reserved']}"
    )

    volunteer = read_volunteer(world)
    assert volunteer["reliability_score"] == pytest.approx(0.7500, abs=0.00005), (
        f"Expected the unanswered offer to leave reliability_score at the 0.7500 baseline, got "
        f"{volunteer['reliability_score']}"
    )
    assert volunteer["reliability_score_lifetime"] == pytest.approx(0.7500, abs=0.00005), (
        f"Expected reliability_score_lifetime at the 0.7500 baseline, got "
        f"{volunteer['reliability_score_lifetime']}"
    )
    assert volunteer["terminal_engagement_count"] == 0, (
        f"Expected terminal_engagement_count 0, got {volunteer['terminal_engagement_count']}"
    )
    assert volunteer["status"] == "ACTIVE", (
        f"Expected the volunteer to stay ACTIVE, got {volunteer['status']}"
    )


def test_14_an_admin_withdrawal_releases_the_reservation_without_a_failed_round(api):
    """PRD §3.5: "The offer moves `OFFERED → WITHDRAWN` with `responded_at` and the reason
    stamped, and the same hour and slot releases run. The difference from a decline is
    conditional: `failed_match_rounds` rises only when `withdraw_reason` is something other than
    `ADMIN`."

    Design: Corner/state_machines/sm_offer_withdrawn_with_admin_reason_does_not_penalise_the_request
    """
    world = setup_offer(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)

    offer = validate_success(
        api_client.withdraw_match_offer(
            world["offer"]["id"], world["spec_headers"], {"withdraw_reason": "ADMIN"}
        )
    )

    assert offer["status"] == "WITHDRAWN", (
        f"Expected status WITHDRAWN, got {offer['status']}"
    )
    assert offer["withdraw_reason"] == "ADMIN", (
        f"Expected withdraw_reason ADMIN, got {offer['withdraw_reason']}"
    )
    assert _same_instant(offer["responded_at"], CLOCK_T0), (
        f"Expected responded_at stamped from the clock, got {offer['responded_at']}"
    )

    request = read_request(world)
    assert request["failed_match_rounds"] == 0, (
        f"Expected an ADMIN withdrawal to leave failed_match_rounds at 0, got "
        f"{request['failed_match_rounds']}"
    )
    assert request["status"] == "SCOPED", (
        f"Expected the request back in SCOPED, got {request['status']}"
    )

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.005), (
        f"Expected the held hours released, got hours_committed {window['hours_committed']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved back to 0, got {cycle['slots_reserved']}"
    )


def test_15_a_rescoped_withdrawal_charges_the_request_a_failed_round(api):
    """PRD §3.5: "The offer moves `OFFERED → WITHDRAWN` with `responded_at` and the reason
    stamped, and the same hour and slot releases run. The difference from a decline is
    conditional: `failed_match_rounds` rises only when `withdraw_reason` is something other than
    `ADMIN`."
    PRD §3.5: "If the request's `failed_match_rounds` plus one is still below 2, the request
    returns to `SCOPED` (`MATCHING → SCOPED`) and the specialist may run the selector again,
    which will now skip every volunteer already approached."

    Design: Corner/state_machines/sm_offer_withdrawn_with_rescoped_reason_increments_failed_rounds
    """
    world = setup_offer(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)

    offer = validate_success(
        api_client.withdraw_match_offer(
            world["offer"]["id"], world["spec_headers"], {"withdraw_reason": "RESCOPED"}
        )
    )

    assert offer["status"] == "WITHDRAWN", (
        f"Expected status WITHDRAWN, got {offer['status']}"
    )
    assert offer["withdraw_reason"] == "RESCOPED", (
        f"Expected withdraw_reason RESCOPED, got {offer['withdraw_reason']}"
    )

    request = read_request(world)
    assert request["failed_match_rounds"] == 1, (
        f"Expected a non-ADMIN withdrawal to raise failed_match_rounds to 1, got "
        f"{request['failed_match_rounds']}"
    )
    assert request["status"] == "SCOPED", (
        f"Expected the request back in SCOPED on the first failed round, got "
        f"{request['status']}"
    )
    assert request["rescope_count"] == 0, (
        f"Expected rescope_count still 0, got {request['rescope_count']}"
    )

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.005), (
        f"Expected the held hours released, got hours_committed {window['hours_committed']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved back to 0, got {cycle['slots_reserved']}"
    )


def test_16_an_accepted_offer_refuses_a_second_acceptance(api):
    """PRD §3.5: "Any of the three volunteer- or staff-driven responses aimed at an offer that is
    no longer in `OFFERED` is refused with `ERR_OFFER_NOT_OPEN`."

    Design: Corner/state_machines/sm_offer_cannot_be_accepted_twice_second_call_returns_offer_not_open
    """
    world = setup_engagement(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)
    assert read_offer(world)["status"] == "ACCEPTED", (
        "Setup expected an already ACCEPTED offer"
    )

    validate_error(
        api_client.accept_match_offer(
            world["offer"]["id"], world["volunteer_headers"]
        ),
        ApiErrorId.ERR_OFFER_NOT_OPEN,
    )

    engagements, meta = validate_paginated(
        api_client.list_engagements(world["pm_headers"])
    )
    assert len(engagements) == 1, (
        f"Expected the rejected retry to create no second engagement, got "
        f"{len(engagements)} engagements"
    )
    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 1, (
        f"Expected slots_committed to stay 1, got {cycle['slots_committed']}"
    )
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved to stay 0, got {cycle['slots_reserved']}"
    )


def test_17_a_declined_offer_refuses_a_second_decline(api):
    """PRD §3.5: "Any of the three volunteer- or staff-driven responses aimed at an offer that is
    no longer in `OFFERED` is refused with `ERR_OFFER_NOT_OPEN`."

    Design: Corner/state_machines/sm_declined_offer_cannot_be_declined_again
    """
    world = setup_offer(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)
    validate_success(
        api_client.decline_match_offer(
            world["offer"]["id"],
            {"decline_reason": "SCHEDULE_CONFLICT"},
            world["volunteer_headers"],
        )
    )

    validate_error(
        api_client.decline_match_offer(
            world["offer"]["id"],
            {"decline_reason": "OUTSIDE_EXPERTISE"},
            world["volunteer_headers"],
        ),
        ApiErrorId.ERR_OFFER_NOT_OPEN,
    )

    offer = read_offer(world)
    assert offer["decline_reason"] == "SCHEDULE_CONFLICT", (
        f"Expected the first reason to survive the rejected retry, got "
        f"{offer['decline_reason']}"
    )
    request = read_request(world)
    assert request["failed_match_rounds"] == 1, (
        f"Expected failed_match_rounds to stay 1 after the rejected second decline, got "
        f"{request['failed_match_rounds']}"
    )
    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.005), (
        f"Expected the hours released exactly once, got hours_committed "
        f"{window['hours_committed']}"
    )
    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved to stay 0, got {cycle['slots_reserved']}"
    )


# ---------------------------------------------------------------------------
# The terms document
# ---------------------------------------------------------------------------
def test_18_issuing_then_sending_the_terms_clears_both_signature_slots(api):
    """PRD §3.6: "The document is created with `status` `DRAFTED`, `counter_round` 0,
    `terms_revision_no` 1, a null `last_countered_by`, and null `volunteer_signed_at` and
    `partner_signed_at`."
    PRD §3.6: "The `ProgramManager` sends the current revision for signature, moving the
    agreement `DRAFTED → SENT`; sending requires the engagement to still be in `NOT_STARTED` and
    the pinned revision to still be `APPROVED`, and it clears both `volunteer_signed_at` and
    `partner_signed_at` to null."

    Design: Corner/state_machines/sm_agreement_initial_drafted_then_send_clears_signature_slots
    """
    world = setup_drafted_agreement(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)
    drafted = world["agreement"]
    assert drafted["status"] == "DRAFTED", (
        f"Expected the freshly issued document in DRAFTED, got {drafted['status']}"
    )
    assert drafted["counter_round"] == 0, (
        f"Expected counter_round 0, got {drafted['counter_round']}"
    )
    assert drafted["terms_revision_no"] == 1, (
        f"Expected terms_revision_no 1, got {drafted['terms_revision_no']}"
    )
    assert drafted["last_countered_by"] is None, (
        f"Expected a null last_countered_by, got {drafted['last_countered_by']}"
    )

    agreement = validate_success(
        api_client.send_agreement(drafted["id"], world["pm_headers"])
    )

    assert agreement["status"] == "SENT", (
        f"Expected the agreement to move DRAFTED → SENT, got {agreement['status']}"
    )
    assert agreement["volunteer_signed_at"] is None, (
        f"Expected volunteer_signed_at cleared to null, got "
        f"{agreement['volunteer_signed_at']}"
    )
    assert agreement["partner_signed_at"] is None, (
        f"Expected partner_signed_at cleared to null, got {agreement['partner_signed_at']}"
    )
    assert agreement["counter_round"] == 0, (
        f"Expected counter_round still 0, got {agreement['counter_round']}"
    )
    assert agreement["terms_revision_no"] == 1, (
        f"Expected terms_revision_no still 1, got {agreement['terms_revision_no']}"
    )

    engagement = read_engagement(world)
    assert engagement["work_status"] == "NOT_STARTED", (
        f"Expected the engagement still NOT_STARTED while terms circulate, got "
        f"{engagement['work_status']}"
    )


def test_19_the_first_signature_stamps_one_slot_and_leaves_the_agreement_sent(api):
    """PRD §3.6: "In practice the first call stamps one slot — `volunteer_signed_at` for the
    volunteer, `partner_signed_at` for the partner contact — and leaves the agreement in `SENT`;
    the countersign by the other party stamps the second slot and completes `SENT → EXECUTED`."

    Design: Corner/state_machines/sm_agreement_first_execute_stamps_one_slot_and_stays_sent
    """
    world = setup_sent_agreement(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)

    agreement = validate_success(
        api_client.execute_agreement(
            world["agreement"]["id"], world["volunteer_headers"]
        )
    )

    assert agreement["status"] == "SENT", (
        f"Expected the agreement to stay SENT after one signature, got {agreement['status']}"
    )
    assert _same_instant(agreement["volunteer_signed_at"], CLOCK_T0), (
        f"Expected volunteer_signed_at stamped from the clock {CLOCK_T0}, got "
        f"{agreement['volunteer_signed_at']}"
    )
    assert agreement["partner_signed_at"] is None, (
        f"Expected partner_signed_at still null, got {agreement['partner_signed_at']}"
    )

    engagement = read_engagement(world)
    assert engagement["work_status"] == "NOT_STARTED", (
        f"Expected the engagement still NOT_STARTED, got {engagement['work_status']}"
    )


def test_20_the_countersignature_completes_execution(api):
    """PRD §3.6: "In practice the first call stamps one slot — `volunteer_signed_at` for the
    volunteer, `partner_signed_at` for the partner contact — and leaves the agreement in `SENT`;
    the countersign by the other party stamps the second slot and completes `SENT → EXECUTED`."

    Design: Corner/state_machines/sm_agreement_countersign_completes_execution
    """
    world = setup_sent_agreement(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)
    validate_success(
        api_client.execute_agreement(
            world["agreement"]["id"], world["volunteer_headers"]
        )
    )

    agreement = validate_success(
        api_client.execute_agreement(
            world["agreement"]["id"], world["partner_headers"]
        )
    )

    assert agreement["status"] == "EXECUTED", (
        f"Expected the countersignature to complete SENT → EXECUTED, got "
        f"{agreement['status']}"
    )
    assert _same_instant(agreement["volunteer_signed_at"], CLOCK_T0), (
        f"Expected volunteer_signed_at kept, got {agreement['volunteer_signed_at']}"
    )
    assert _same_instant(agreement["partner_signed_at"], CLOCK_T0), (
        f"Expected partner_signed_at stamped, got {agreement['partner_signed_at']}"
    )

    engagement = read_engagement(world)
    assert engagement["work_status"] == "NOT_STARTED", (
        f"Expected the engagement to await its own start call, got "
        f"{engagement['work_status']}"
    )


def test_21_a_counter_then_a_re_send_returns_the_agreement_to_sent(api):
    """PRD §3.6: "A counter moves the agreement `SENT → COUNTERED`, raises `counter_round` by
    one, sets `terms_revision_no` to `counter_round` plus one, overwrites the three negotiated
    fields with the countered values, clears both signature timestamps to null so that nothing
    signed against the old revision survives, and records `last_countered_by` as `VOLUNTEER` or
    `PARTNER` according to who countered."
    PRD §3.6: "The manager then re-sends, moving the agreement `COUNTERED → SENT` — permitted
    while `counter_round` has not passed 3 — again clearing both signature slots, and the cycle
    `SENT → COUNTERED → SENT` may run up to three times in total."

    Design: Corner/state_machines/sm_agreement_counter_round_returns_agreement_to_sent
    """
    world = setup_sent_agreement(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)
    validate_success(
        api_client.execute_agreement(
            world["agreement"]["id"], world["volunteer_headers"]
        )
    )

    countered = validate_success(
        api_client.counter_agreement(
            world["agreement"]["id"],
            counter_payload(
                ip_disposition="LICENSE_PERPETUAL",
                confidentiality_tier="ELEVATED",
                indemnity_cap_usd=40000.00,
            ),
            world["volunteer_headers"],
        )
    )

    assert countered["status"] == "COUNTERED", (
        f"Expected the agreement to move SENT → COUNTERED, got {countered['status']}"
    )
    assert countered["counter_round"] == 1, (
        f"Expected counter_round 1, got {countered['counter_round']}"
    )
    assert countered["terms_revision_no"] == 2, (
        f"Expected terms_revision_no 2, got {countered['terms_revision_no']}"
    )
    assert countered["last_countered_by"] == "VOLUNTEER", (
        f"Expected last_countered_by VOLUNTEER, got {countered['last_countered_by']}"
    )
    assert countered["ip_disposition"] == "LICENSE_PERPETUAL", (
        f"Expected the countered ip_disposition LICENSE_PERPETUAL, got "
        f"{countered['ip_disposition']}"
    )
    assert countered["confidentiality_tier"] == "ELEVATED", (
        f"Expected the countered confidentiality_tier ELEVATED, got "
        f"{countered['confidentiality_tier']}"
    )
    assert countered["indemnity_cap_usd"] == pytest.approx(40000.00, abs=0.005), (
        f"Expected the countered indemnity_cap_usd 40000.00, got "
        f"{countered['indemnity_cap_usd']}"
    )
    assert countered["volunteer_signed_at"] is None, (
        f"Expected the signature against the old revision cleared, got "
        f"{countered['volunteer_signed_at']}"
    )
    assert countered["partner_signed_at"] is None, (
        f"Expected partner_signed_at null, got {countered['partner_signed_at']}"
    )

    resent = validate_success(
        api_client.send_agreement(world["agreement"]["id"], world["pm_headers"])
    )

    assert resent["status"] == "SENT", (
        f"Expected the re-send to move COUNTERED → SENT, got {resent['status']}"
    )
    assert resent["counter_round"] == 1, (
        f"Expected counter_round to stay 1 across the re-send, got {resent['counter_round']}"
    )
    assert resent["terms_revision_no"] == 2, (
        f"Expected terms_revision_no to stay 2, got {resent['terms_revision_no']}"
    )
    assert resent["last_countered_by"] == "VOLUNTEER", (
        f"Expected last_countered_by to stay VOLUNTEER, got {resent['last_countered_by']}"
    )
    assert resent["volunteer_signed_at"] is None, (
        f"Expected both signature slots cleared again, got "
        f"{resent['volunteer_signed_at']}"
    )
    assert resent["partner_signed_at"] is None, (
        f"Expected both signature slots cleared again, got {resent['partner_signed_at']}"
    )


def test_22_voiding_a_sent_agreement_terminates_the_engagement_it_governed(api):
    """PRD §3.6: "A direct void records `void_reason` `TERMS_REJECTED` and terminates the
    engagement it governed with `termination_reason` `AGREEMENT_VOIDED`; a void that arrives as a
    cascade from an engagement termination records `void_reason` `ENGAGEMENT_TERMINATED` instead
    and terminates nothing further, since the engagement is already gone."
    PRD §3.9: "The cycle's `slots_committed` falls by one and the posture recomputes. The holding
    window's `hours_committed` falls by the engagement's full current `committed_hours` — the
    grown figure, not the originally reserved one."

    Design: Corner/state_machines/sm_agreement_void_terminates_the_engagement
    """
    world = setup_sent_agreement(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)

    agreement = validate_success(
        api_client.void_agreement(world["agreement"]["id"], world["pm_headers"])
    )

    assert agreement["status"] == "VOIDED", (
        f"Expected the agreement VOIDED, got {agreement['status']}"
    )
    assert agreement["void_reason"] == "TERMS_REJECTED", (
        f"Expected void_reason TERMS_REJECTED on a direct void, got "
        f"{agreement['void_reason']}"
    )

    engagement = read_engagement(world)
    assert engagement["work_status"] == "TERMINATED", (
        f"Expected the governed engagement TERMINATED, got {engagement['work_status']}"
    )
    assert engagement["termination_reason"] == "AGREEMENT_VOIDED", (
        f"Expected termination_reason AGREEMENT_VOIDED, got "
        f"{engagement['termination_reason']}"
    )
    assert _same_instant(engagement["terminated_at"], CLOCK_T0), (
        f"Expected terminated_at stamped from the clock, got {engagement['terminated_at']}"
    )
    assert engagement["valuation_status"] == "UNVALUED", (
        f"Expected valuation_status untouched at UNVALUED, got "
        f"{engagement['valuation_status']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 0, (
        f"Expected slots_committed released to 0, got {cycle['slots_committed']}"
    )
    assert cycle["slots_available"] == CYCLE_SLOTS, (
        f"Expected slots_available {CYCLE_SLOTS}, got {cycle['slots_available']}"
    )

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.005), (
        f"Expected the engagement's 40.00 committed hours released, got "
        f"{window['hours_committed']}"
    )

    volunteer = read_volunteer(world)
    assert volunteer["terminal_engagement_count"] == 1, (
        f"Expected terminal_engagement_count 1, got "
        f"{volunteer['terminal_engagement_count']}"
    )
    assert volunteer["open_engagement_count"] == 0, (
        f"Expected open_engagement_count 0, got {volunteer['open_engagement_count']}"
    )
    assert volunteer["reliability_score"] == pytest.approx(0.6000, abs=0.00005), (
        f"Expected reliability_score 0.6000 from a single AGREEMENT_VOIDED termination, got "
        f"{volunteer['reliability_score']}"
    )
    assert volunteer["reliability_score_lifetime"] == pytest.approx(0.6000, abs=0.00005), (
        f"Expected reliability_score_lifetime 0.6000, got "
        f"{volunteer['reliability_score_lifetime']}"
    )


def test_23_terminating_before_work_starts_voids_the_drafted_agreement(api):
    """PRD §3.9: "Termination is the program's universal compensating action, and it runs
    identically from all four live states — `NOT_STARTED → TERMINATED`, `IN_PROGRESS →
    TERMINATED`, `SUBMITTED → TERMINATED` and `ACCEPTED → TERMINATED`."
    PRD §3.9: "The governing agreement, unless it had already reached `EXECUTED`, moves to
    `VOIDED` with `void_reason` `ENGAGEMENT_TERMINATED`."

    Design: Corner/state_machines/sm_engagement_terminate_before_start_voids_the_drafted_agreement
    """
    world = setup_drafted_agreement(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)

    engagement = validate_success(
        api_client.terminate_engagement(
            world["engagement"]["id"],
            world["pm_headers"],
            {"termination_reason": "ADMIN"},
        )
    )

    assert engagement["work_status"] == "TERMINATED", (
        f"Expected work_status TERMINATED from NOT_STARTED, got {engagement['work_status']}"
    )
    assert engagement["termination_reason"] == "ADMIN", (
        f"Expected termination_reason ADMIN, got {engagement['termination_reason']}"
    )
    assert _same_instant(engagement["terminated_at"], CLOCK_T0), (
        f"Expected terminated_at stamped from the clock, got {engagement['terminated_at']}"
    )

    agreement = read_agreement(world)
    assert agreement["status"] == "VOIDED", (
        f"Expected the never-executed agreement VOIDED, got {agreement['status']}"
    )
    assert agreement["void_reason"] == "ENGAGEMENT_TERMINATED", (
        f"Expected void_reason ENGAGEMENT_TERMINATED on the cascade, got "
        f"{agreement['void_reason']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 0, (
        f"Expected slots_committed released to 0, got {cycle['slots_committed']}"
    )

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.005), (
        f"Expected the committed hours released, got {window['hours_committed']}"
    )


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------
def test_24_starting_the_work_carries_the_request_into_delivery(api):
    """PRD §3.7: "Work begins when the engaged volunteer starts the engagement, moving its
    `work_status` `NOT_STARTED → IN_PROGRESS` and carrying the parent request `ENGAGED → IN_DELIVERY`."

    Design: Corner/state_machines/sm_engagement_start_moves_request_to_in_delivery
    """
    world = setup_executed_agreement(cycle_slots=CYCLE_SLOTS, window_hours=WINDOW_HOURS)

    engagement = validate_success(
        api_client.start_engagement(
            world["engagement"]["id"], world["volunteer_headers"]
        )
    )

    assert engagement["work_status"] == "IN_PROGRESS", (
        f"Expected work_status IN_PROGRESS, got {engagement['work_status']}"
    )
    assert engagement["valuation_status"] == "UNVALUED", (
        f"Expected the valuation dimension untouched at UNVALUED, got "
        f"{engagement['valuation_status']}"
    )
    assert engagement["approved_hours"] == pytest.approx(0.00, abs=0.005), (
        f"Expected approved_hours still 0.00, got {engagement['approved_hours']}"
    )

    request = read_request(world)
    assert request["status"] == "IN_DELIVERY", (
        f"Expected the request to move ENGAGED → IN_DELIVERY, got {request['status']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 1, (
        f"Expected the committed slot to stay held, got {cycle['slots_committed']}"
    )
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved 0, got {cycle['slots_reserved']}"
    )

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(40.00, abs=0.005), (
        f"Expected the 40.00 committed hours still held, got {window['hours_committed']}"
    )


def test_25_holding_a_check_in_approves_the_logs_dated_before_it(api):
    """PRD §3.7: "The hold moves the milestone `SCHEDULED → HELD` with `held_at` stamped, and
    then, in this order: every child time log of the engagement that is still unapproved and whose
    `work_date` is at or before the milestone's `due_at` flips `approved` to true with
    `approved_at` stamped and its `milestone_id` set to this milestone; the engagement's
    `approved_hours` is recomputed; the creep calculation reruns and may move
    `creep_escalation_level`; `variance_hours` is computed as the reported cumulative hours less
    the engagement's `approved_hours` *measured after those approvals*, which is why an early hold
    can show a negative variance; and `escalation_raised` is set to true when the recomputed
    `creep_escalation_level` is `ESCALATED` or `BREACH`."
    PRD §3.7: "The result drives `creep_escalation_level`: `NONE` below 0.1500, `WATCH` from
    0.1500 up to but not including 0.3000, `ESCALATED` from 0.3000 up to but not including
    0.5000, and `BREACH` at 0.5000 and above."

    Design: Corner/state_machines/sm_milestone_hold_approves_dated_logs_and_recomputes_creep
    """
    world = setup_in_progress_engagement(
        cycle_slots=CYCLE_SLOTS,
        window_hours=WINDOW_HOURS,
        deliverables=SINGLE_DELIVERABLE,
    )
    milestone = validate_success(
        api_client.create_milestone(
            world["engagement"]["id"],
            milestone_payload(due_at="2026-08-20T00:00:00Z"),
            world["pm_headers"],
        ),
        201,
    )
    world["milestone"] = milestone
    for _ in range(4):
        validate_success(
            api_client.create_time_log(
                world["engagement"]["id"],
                time_log_payload(
                    work_date="2026-08-12T00:00:00Z", hours=10.00, activity_class="DELIVERY"
                ),
                world["volunteer_headers"],
            ),
            201,
        )
    hold_clock = "2026-08-19T00:00:00Z"
    set_clock(hold_clock, world["pm_headers"])

    held = validate_success(
        api_client.hold_milestone(
            milestone["id"], {"reported_cumulative_hours": 40.00}, world["pm_headers"]
        )
    )

    assert held["checkin_status"] == "HELD", (
        f"Expected checkin_status HELD, got {held['checkin_status']}"
    )
    assert _same_instant(held["held_at"], hold_clock), (
        f"Expected held_at stamped from the clock {hold_clock}, got {held['held_at']}"
    )
    assert held["sequence_no"] == 1, (
        f"Expected sequence_no 1 on the first check-in, got {held['sequence_no']}"
    )
    assert held["reported_cumulative_hours"] == pytest.approx(40.00, abs=0.005), (
        f"Expected reported_cumulative_hours 40.00, got "
        f"{held['reported_cumulative_hours']}"
    )
    assert held["variance_hours"] == pytest.approx(0.00, abs=0.005), (
        f"Expected variance_hours 0.00 once the 40.00 logged hours were approved, got "
        f"{held['variance_hours']}"
    )
    assert held["escalation_raised"] is False, (
        f"Expected escalation_raised false at creep level NONE, got "
        f"{held['escalation_raised']}"
    )

    engagement = read_engagement(world)
    assert engagement["approved_hours"] == pytest.approx(40.00, abs=0.005), (
        f"Expected approved_hours 40.00, got {engagement['approved_hours']}"
    )
    assert engagement["scope_creep_pct"] == pytest.approx(0.0000, abs=0.00005), (
        f"Expected scope_creep_pct 0.0000 against the 40.00 baseline, got "
        f"{engagement['scope_creep_pct']}"
    )
    assert engagement["creep_escalation_level"] == "NONE", (
        f"Expected creep_escalation_level NONE, got {engagement['creep_escalation_level']}"
    )
    assert engagement["work_status"] == "IN_PROGRESS", (
        f"Expected the engagement still IN_PROGRESS, got {engagement['work_status']}"
    )

    attached, _ = validate_paginated(
        api_client.list_milestone_time_logs(milestone["id"], world["pm_headers"])
    )
    assert len(attached) == 4, (
        f"Expected all four dated logs attached to the check-in, got {len(attached)}"
    )
    for row in attached:
        assert row["approved"] is True, (
            f"Expected log {row['id']} approved, got {row['approved']}"
        )
        assert row["milestone_id"] == milestone["id"], (
            f"Expected log {row['id']} stamped with milestone_id {milestone['id']}, got "
            f"{row['milestone_id']}"
        )
        assert row["approved_at"] is not None, (
            f"Expected approved_at stamped on log {row['id']}"
        )


def test_26_the_checkpoint_marks_an_unheld_check_in_missed(api):
    """PRD §3.7: "During the cycle checkpoint, a milestone still `SCHEDULED` on an `IN_PROGRESS`
    engagement whose `due_at` plus twenty-four hours has fallen strictly behind the logical clock
    moves `SCHEDULED → MISSED`, raising the engagement's `missed_checkin_count` by one and
    rerunning both of the volunteer's reliability figures."
    PRD §3.7: "A second miss ends the engagement: once `missed_checkin_count` reaches 2, the
    engagement is terminated with `termination_reason` `ADMIN`."
    PRD §3.2: "A volunteer with no terminal engagement at all reads 0.7500 in both fields."
    PRD §3.1: "Finally it recomputes the capacity figures and `posture`, stamps
    `last_recalculated_at` from the clock, and advances `recalc_epoch` by exactly one — the epoch
    counter starts at 0 and exists so operators can tell one checkpoint's output from the next."

    Design: Corner/state_machines/sm_milestone_missed_via_cycle_recalculate_sweep
    """
    world = setup_in_progress_engagement(
        cycle_slots=CYCLE_SLOTS,
        window_hours=WINDOW_HOURS,
        deliverables=SINGLE_DELIVERABLE,
    )
    milestone = validate_success(
        api_client.create_milestone(
            world["engagement"]["id"],
            milestone_payload(due_at="2026-08-20T00:00:00Z"),
            world["pm_headers"],
        ),
        201,
    )
    world["milestone"] = milestone
    lapsed = "2026-08-21T00:00:01Z"
    set_clock(lapsed, world["pm_headers"])

    cycle = validate_success(
        api_client.recalculate_program_cycle(world["cycle"]["id"], world["pm_headers"])
    )

    assert cycle["recalc_epoch"] == 1, (
        f"Expected recalc_epoch advanced to 1, got {cycle['recalc_epoch']}"
    )
    assert _same_instant(cycle["last_recalculated_at"], lapsed), (
        f"Expected last_recalculated_at stamped from the clock {lapsed}, got "
        f"{cycle['last_recalculated_at']}"
    )
    assert cycle["slots_committed"] == 1, (
        f"Expected the engagement's slot still committed, got {cycle['slots_committed']}"
    )
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved 0, got {cycle['slots_reserved']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"Expected posture OPEN, got {cycle['posture']}"
    )

    missed = read_milestone(world)
    assert missed["checkin_status"] == "MISSED", (
        f"Expected checkin_status MISSED a day and a second past due_at, got "
        f"{missed['checkin_status']}"
    )

    engagement = read_engagement(world)
    assert engagement["missed_checkin_count"] == 1, (
        f"Expected missed_checkin_count 1, got {engagement['missed_checkin_count']}"
    )
    assert engagement["work_status"] == "IN_PROGRESS", (
        f"Expected the engagement to survive a single miss, got "
        f"{engagement['work_status']}"
    )

    volunteer = read_volunteer(world)
    assert volunteer["terminal_engagement_count"] == 0, (
        f"Expected terminal_engagement_count 0, got "
        f"{volunteer['terminal_engagement_count']}"
    )
    assert volunteer["reliability_score"] == pytest.approx(0.7500, abs=0.00005), (
        f"Expected reliability_score at the 0.7500 baseline with no terminal engagement, got "
        f"{volunteer['reliability_score']}"
    )
    assert volunteer["reliability_score_lifetime"] == pytest.approx(0.7500, abs=0.00005), (
        f"Expected reliability_score_lifetime 0.7500, got "
        f"{volunteer['reliability_score_lifetime']}"
    )


def test_27_termination_waives_the_open_check_in_and_spares_the_executed_agreement(api):
    """PRD §3.9: "Every child milestone still `SCHEDULED` moves to `WAIVED` with `waiver_reason`
    `ENGAGEMENT_TERMINATED`."
    PRD §3.9: "The governing agreement, unless it had already reached `EXECUTED`, moves to
    `VOIDED` with `void_reason` `ENGAGEMENT_TERMINATED`."
    PRD §3.2: "Each terminal engagement earns a point value before penalties: 1.00 when it was
    `HANDED_OFF` with a `quality_gate` of `PASSED`; 0.70 when it was `HANDED_OFF` with a
    `quality_gate` of `CONDITIONAL`; 0.00 when it was `TERMINATED` for `QUALITY_FAILURE`; 0.25
    when it was `TERMINATED` for `SCOPE_BREACH` or `ADMIN`; and 0.60 when it was `TERMINATED` for
    `AGREEMENT_VOIDED` or `PARTNER_SUSPENDED`."
    PRD §3.2: "One threshold consequence hangs off the decay-weighted figure alone: if
    `reliability_score` falls strictly below 0.4000 while the volunteer's `status` is `ACTIVE`,
    the volunteer moves to `PAUSED` with `pause_reason` `RELIABILITY_FLOOR`, dragging the
    offer-withdrawal cascade above with it."

    Design: Corner/state_machines/sm_milestone_waived_on_termination_leaves_executed_agreement_intact
    """
    world = setup_in_progress_engagement(
        cycle_slots=CYCLE_SLOTS,
        window_hours=WINDOW_HOURS,
        deliverables=SINGLE_DELIVERABLE,
    )
    milestone = validate_success(
        api_client.create_milestone(
            world["engagement"]["id"],
            milestone_payload(due_at="2026-08-20T00:00:00Z"),
            world["pm_headers"],
        ),
        201,
    )
    world["milestone"] = milestone

    engagement = validate_success(
        api_client.terminate_engagement(
            world["engagement"]["id"],
            world["pm_headers"],
            {"termination_reason": "ADMIN"},
        )
    )

    assert engagement["work_status"] == "TERMINATED", (
        f"Expected work_status TERMINATED, got {engagement['work_status']}"
    )
    assert engagement["termination_reason"] == "ADMIN", (
        f"Expected termination_reason ADMIN, got {engagement['termination_reason']}"
    )

    waived = read_milestone(world)
    assert waived["checkin_status"] == "WAIVED", (
        f"Expected the SCHEDULED check-in WAIVED, got {waived['checkin_status']}"
    )
    assert waived["waiver_reason"] == "ENGAGEMENT_TERMINATED", (
        f"Expected waiver_reason ENGAGEMENT_TERMINATED, got {waived['waiver_reason']}"
    )

    agreement = read_agreement(world)
    assert agreement["status"] == "EXECUTED", (
        f"Expected the already-EXECUTED agreement left untouched, got {agreement['status']}"
    )
    assert agreement["void_reason"] is None, (
        f"Expected a null void_reason on the executed agreement, got "
        f"{agreement['void_reason']}"
    )

    request = read_request(world)
    assert request["status"] == "IN_DELIVERY", (
        f"Expected an ADMIN termination to leave the request in IN_DELIVERY, got "
        f"{request['status']}"
    )

    volunteer = read_volunteer(world)
    assert volunteer["terminal_engagement_count"] == 1, (
        f"Expected terminal_engagement_count 1, got "
        f"{volunteer['terminal_engagement_count']}"
    )
    assert volunteer["reliability_score"] == pytest.approx(0.2500, abs=0.00005), (
        f"Expected reliability_score 0.2500 from a single ADMIN termination, got "
        f"{volunteer['reliability_score']}"
    )
    assert volunteer["status"] == "PAUSED", (
        f"Expected the volunteer PAUSED below the 0.4000 floor, got {volunteer['status']}"
    )
    assert volunteer["pause_reason"] == "RELIABILITY_FLOOR", (
        f"Expected pause_reason RELIABILITY_FLOOR, got {volunteer['pause_reason']}"
    )


def test_28_submission_approves_every_remaining_log_before_review(api):
    """PRD §3.7: "The engaged volunteer submits, moving the engagement `IN_PROGRESS → SUBMITTED`,
    and five conditions must hold: the caller is the engagement's volunteer, at least one child
    milestone has `checkin_status` `HELD`, no child scope change request sits in `PENDING` or
    `ESCALATED`, the engagement's `creep_escalation_level` is not `BREACH`, and every
    non-`WAIVED` deliverable on the pinned revision has its `hours_estimate` accounted for by at
    least one time log."
    PRD §3.7: "On success every remaining unapproved child log flips `approved` to true with
    `approved_at` stamped, and the engagement's `approved_hours` and creep figures are recomputed
    one final time before review."

    Design: Corner/state_machines/sm_engagement_submit_flips_remaining_logs_and_locks_review_gate
    """
    world = setup_held_milestone_engagement(
        cycle_slots=CYCLE_SLOTS,
        window_hours=WINDOW_HOURS,
        deliverables=SINGLE_DELIVERABLE,
    )
    late = validate_success(
        api_client.create_time_log(
            world["engagement"]["id"],
            time_log_payload(
                work_date="2026-08-13T00:00:00Z", hours=4.00, activity_class="ADMIN"
            ),
            world["volunteer_headers"],
        ),
        201,
    )
    assert late["approved"] is False, (
        f"Setup expected the extra log unapproved, got {late['approved']}"
    )

    engagement = validate_success(
        api_client.submit_engagement(
            world["engagement"]["id"], world["volunteer_headers"]
        )
    )

    assert engagement["work_status"] == "SUBMITTED", (
        f"Expected work_status SUBMITTED, got {engagement['work_status']}"
    )
    assert engagement["approved_hours"] == pytest.approx(44.00, abs=0.005), (
        f"Expected approved_hours 44.00 once the trailing ADMIN log was approved, got "
        f"{engagement['approved_hours']}"
    )
    assert engagement["committed_hours"] == pytest.approx(40.00, abs=0.005), (
        f"Expected committed_hours untouched at 40.00, got {engagement['committed_hours']}"
    )
    assert engagement["scope_creep_pct"] == pytest.approx(0.1000, abs=0.00005), (
        f"Expected scope_creep_pct 0.1000 for 44.00 hours against a 40.00 baseline, got "
        f"{engagement['scope_creep_pct']}"
    )
    assert engagement["creep_escalation_level"] == "NONE", (
        f"Expected creep_escalation_level NONE below 0.1500, got "
        f"{engagement['creep_escalation_level']}"
    )
    assert engagement["quality_gate"] == "PENDING", (
        f"Expected quality_gate still PENDING before review, got "
        f"{engagement['quality_gate']}"
    )

    logs = read_time_logs(world)
    assert len(logs) == 5, (
        f"Expected five child logs, got {len(logs)}"
    )
    for row in logs:
        assert row["approved"] is True, (
            f"Expected log {row['id']} approved by submission, got {row['approved']}"
        )
    trailing = [row for row in logs if row["id"] == late["id"]][0]
    assert trailing["milestone_id"] is None, (
        f"Expected the post-hold log to carry no milestone_id, got "
        f"{trailing['milestone_id']}"
    )

    request = read_request(world)
    assert request["status"] == "IN_DELIVERY", (
        f"Expected the request still IN_DELIVERY, got {request['status']}"
    )


def test_29_opening_a_review_round_needs_no_body_at_all(api):
    """PRD §3.8: "The new review is created in `status` `OPEN` with a `round_no` one greater than
    the highest among its siblings on that engagement, a `reviewer_user_id` recording the opening
    operator's `X-User-ID`, a `scored_deliverable_count` of 0, a null `weighted_score`, an
    `outcome` of `PENDING`, and null `rework_deadline_at` and `decided_at`."

    Design: Corner/state_machines/sm_quality_review_opens_in_open_state_with_round_one
    """
    world = setup_submitted_engagement(
        cycle_slots=CYCLE_SLOTS,
        window_hours=WINDOW_HOURS,
        deliverables=SINGLE_DELIVERABLE,
    )

    review = validate_success(
        api_client.create_quality_review(
            world["engagement"]["id"], world["reviewer_headers"]
        ),
        201,
    )

    assert review["status"] == "OPEN", (
        f"Expected status OPEN, got {review['status']}"
    )
    assert review["round_no"] == 1, (
        f"Expected round_no 1 on the first round, got {review['round_no']}"
    )
    assert review["reviewer_user_id"] == world["reviewer_user_id"], (
        f"Expected reviewer_user_id {world['reviewer_user_id']}, got "
        f"{review['reviewer_user_id']}"
    )
    assert review["weighted_score"] is None, (
        f"Expected a null weighted_score, got {review['weighted_score']}"
    )
    assert review["outcome"] == "PENDING", (
        f"Expected outcome PENDING, got {review['outcome']}"
    )
    assert review["scored_deliverable_count"] == 0, (
        f"Expected scored_deliverable_count 0, got {review['scored_deliverable_count']}"
    )
    assert review["decided_at"] is None, (
        f"Expected a null decided_at, got {review['decided_at']}"
    )
    assert review["rework_deadline_at"] is None, (
        f"Expected a null rework_deadline_at, got {review['rework_deadline_at']}"
    )

    engagement = read_engagement(world)
    assert engagement["work_status"] == "SUBMITTED", (
        f"Expected the engagement still SUBMITTED while the round is open, got "
        f"{engagement['work_status']}"
    )


def test_30_scoring_the_single_deliverable_at_five_produces_a_pass_round(api):
    """PRD §3.8: "For each deliverable in the pinned order, divide its `weight_pct` by that
    active total and round to six decimals, then multiply that normalised weight by the
    deliverable's `review_score` and by a scale factor of 20, rounding each deliverable's
    contribution to two decimals *before* summing."
    PRD §3.8: "The `outcome` follows from the score: `PASS` at 78.00 and above, `CONDITIONAL` from
    60.00 up to but not including 78.00, and `FAIL` below 60.00."
    PRD §3.8: "Scoring also recomputes `scored_deliverable_count`, the number of non-`WAIVED`
    deliverables on the pinned revision now carrying a non-null `review_score`, and moves the
    review `OPEN → SCORED`."

    Design: Corner/state_machines/sm_quality_review_score_produces_pass_and_holds_engagement_in_submitted
    """
    world = setup_submitted_engagement(
        cycle_slots=CYCLE_SLOTS,
        window_hours=WINDOW_HOURS,
        deliverables=SINGLE_DELIVERABLE,
    )
    deliverable = read_deliverables(world)[0]
    review = validate_success(
        api_client.create_quality_review(
            world["engagement"]["id"], world["reviewer_headers"]
        ),
        201,
    )

    scored = validate_success(
        api_client.score_quality_review(
            review["id"],
            deliverable_scores_payload({deliverable["id"]: 5}),
            world["reviewer_headers"],
        )
    )

    assert scored["status"] == "SCORED", (
        f"Expected the review to move OPEN → SCORED, got {scored['status']}"
    )
    assert scored["weighted_score"] == pytest.approx(100.00, abs=0.005), (
        f"Expected weighted_score 100.00 for a lone 100.00-weight deliverable scored 5, got "
        f"{scored['weighted_score']}"
    )
    assert scored["outcome"] == "PASS", (
        f"Expected outcome PASS at or above 78.00, got {scored['outcome']}"
    )
    assert scored["scored_deliverable_count"] == 1, (
        f"Expected scored_deliverable_count 1, got {scored['scored_deliverable_count']}"
    )
    assert scored["decided_at"] is None, (
        f"Expected decided_at still null before the decide call, got {scored['decided_at']}"
    )

    settled = read_deliverables(world)[0]
    assert settled["review_score"] == 5, (
        f"Expected the deliverable carrying review_score 5, got {settled['review_score']}"
    )
    assert settled["review_status"] == "PENDING", (
        f"Expected review_status still PENDING until the decision settles it, got "
        f"{settled['review_status']}"
    )

    engagement = read_engagement(world)
    assert engagement["work_status"] == "SUBMITTED", (
        f"Expected the engagement to wait in SUBMITTED for the decision, got "
        f"{engagement['work_status']}"
    )
    assert engagement["quality_gate"] == "PENDING", (
        f"Expected quality_gate still PENDING, got {engagement['quality_gate']}"
    )


def test_31_deciding_a_pass_round_accepts_the_engagement_and_its_deliverable(api):
    """PRD §3.8: "A decision on a `PASS` or `CONDITIONAL` outcome without rework moves the review
    `SCORED → DECIDED` with `decided_at` stamped, sets the engagement's `quality_gate` to `PASSED`
    when the outcome was `PASS` and to `CONDITIONAL` when it was `CONDITIONAL`, moves the
    engagement `SUBMITTED → ACCEPTED`, and settles each deliverable: every non-`WAIVED`
    deliverable whose `review_score` is 3 or higher moves to `review_status` `ACCEPTED`, and every
    remaining one moves to `REJECTED`."

    Design: Corner/state_machines/sm_quality_review_decide_pass_accepts_engagement_and_deliverables
    """
    world = setup_submitted_engagement(
        cycle_slots=CYCLE_SLOTS,
        window_hours=WINDOW_HOURS,
        deliverables=SINGLE_DELIVERABLE,
    )
    deliverable = read_deliverables(world)[0]
    review = drive_review_to_outcome(world, {deliverable["id"]: 5})
    assert review["outcome"] == "PASS", (
        f"Setup expected a PASS round, got {review['outcome']}"
    )

    decided = validate_success(
        api_client.decide_quality_review(review["id"], world["reviewer_headers"])
    )

    assert decided["status"] == "DECIDED", (
        f"Expected the review to move SCORED → DECIDED, got {decided['status']}"
    )
    assert decided["decided_at"] is not None, (
        "Expected decided_at stamped on the decision"
    )
    assert decided["rework_deadline_at"] is None, (
        f"Expected rework_deadline_at still null on a plain decision, got "
        f"{decided['rework_deadline_at']}"
    )

    engagement = read_engagement(world)
    assert engagement["work_status"] == "ACCEPTED", (
        f"Expected the engagement to move SUBMITTED → ACCEPTED, got "
        f"{engagement['work_status']}"
    )
    assert engagement["quality_gate"] == "PASSED", (
        f"Expected quality_gate PASSED, got {engagement['quality_gate']}"
    )
    assert engagement["handoff_at"] is None, (
        f"Expected handoff_at still null, got {engagement['handoff_at']}"
    )

    settled = read_deliverables(world)[0]
    assert settled["review_status"] == "ACCEPTED", (
        f"Expected the deliverable scored 5 to move to ACCEPTED, got "
        f"{settled['review_status']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 1, (
        f"Expected an ACCEPTED engagement to keep holding its slot, got "
        f"{cycle['slots_committed']}"
    )


def test_32_requesting_rework_reopens_the_work_and_wipes_the_scores(api):
    """PRD §3.8: "A decision carrying `request_rework` set to true moves the review `SCORED →
    REWORK_REQUESTED` instead, and is only available when the `outcome` is exactly `CONDITIONAL`
    and the review's `round_no` is still below 2 — on the second round a `CONDITIONAL` outcome can
    no longer ask for rework and must simply be decided."
    PRD §3.8: "The transition stamps `decided_at` and sets `rework_deadline_at` to that instant
    plus one week, the rework window being 168 hours. The engagement moves back `SUBMITTED →
    IN_PROGRESS`, and every non-`WAIVED` deliverable has its `review_score` reset to null and its
    `review_status` reset to `PENDING`, so the second round scores a clean set."

    Design: Corner/state_machines/sm_quality_review_conditional_rework_resets_scores_and_reopens_work
    """
    world = setup_submitted_engagement(
        cycle_slots=CYCLE_SLOTS,
        window_hours=WINDOW_HOURS,
        deliverables=SINGLE_DELIVERABLE,
    )
    deliverable = read_deliverables(world)[0]
    review = drive_review_to_outcome(world, {deliverable["id"]: 3})
    assert review["weighted_score"] == pytest.approx(60.00, abs=0.005), (
        f"Setup expected a weighted_score of exactly 60.00, got {review['weighted_score']}"
    )

    decided = validate_success(
        api_client.decide_quality_review(
            review["id"], world["reviewer_headers"], {"request_rework": True}
        )
    )

    assert decided["status"] == "REWORK_REQUESTED", (
        f"Expected the review to move SCORED → REWORK_REQUESTED, got {decided['status']}"
    )
    assert decided["outcome"] == "CONDITIONAL", (
        f"Expected outcome CONDITIONAL on the inclusive 60.00 floor, got "
        f"{decided['outcome']}"
    )
    assert decided["weighted_score"] == pytest.approx(60.00, abs=0.005), (
        f"Expected weighted_score 60.00, got {decided['weighted_score']}"
    )
    assert decided["decided_at"] is not None, (
        "Expected decided_at stamped on the rework decision"
    )
    assert _instant(decided["rework_deadline_at"]) - _instant(decided["decided_at"]) == \
        timedelta(hours=168), (
        f"Expected rework_deadline_at 168 hours after decided_at {decided['decided_at']}, got "
        f"{decided['rework_deadline_at']}"
    )

    engagement = read_engagement(world)
    assert engagement["work_status"] == "IN_PROGRESS", (
        f"Expected the engagement back in IN_PROGRESS, got {engagement['work_status']}"
    )
    assert engagement["quality_gate"] == "PENDING", (
        f"Expected quality_gate still PENDING while rework runs, got "
        f"{engagement['quality_gate']}"
    )

    reset = read_deliverables(world)[0]
    assert reset["review_score"] is None, (
        f"Expected the review_score wiped to null, got {reset['review_score']}"
    )
    assert reset["review_status"] == "PENDING", (
        f"Expected review_status reset to PENDING, got {reset['review_status']}"
    )


def test_33_a_second_round_opens_after_rework_while_round_one_stays_put(api):
    """PRD §3.8: "A second round is only openable after a first round that ended in
    `REWORK_REQUESTED`, and opening it leaves that prior row sitting in `REWORK_REQUESTED` — the
    closing of the loop `OPEN → SCORED → REWORK_REQUESTED → OPEN` is what the round counter
    records."
    PRD §3.8: "The new review is created in `status` `OPEN` with a `round_no` one greater than the
    highest among its siblings on that engagement, a `reviewer_user_id` recording the opening
    operator's `X-User-ID`, a `scored_deliverable_count` of 0, a null `weighted_score`, an
    `outcome` of `PENDING`, and null `rework_deadline_at` and `decided_at`."

    Design: Corner/state_machines/sm_quality_review_round_two_reopens_cycle_after_rework
    """
    world = setup_submitted_engagement(
        cycle_slots=CYCLE_SLOTS,
        window_hours=WINDOW_HOURS,
        deliverables=SINGLE_DELIVERABLE,
    )
    deliverable = read_deliverables(world)[0]
    round_one = drive_review_to_outcome(world, {deliverable["id"]: 3})
    validate_success(
        api_client.decide_quality_review(
            round_one["id"], world["reviewer_headers"], {"request_rework": True}
        )
    )
    validate_success(
        api_client.submit_engagement(
            world["engagement"]["id"], world["volunteer_headers"]
        )
    )

    round_two = validate_success(
        api_client.create_quality_review(
            world["engagement"]["id"], world["reviewer_headers"]
        ),
        201,
    )

    assert round_two["status"] == "OPEN", (
        f"Expected the second round OPEN, got {round_two['status']}"
    )
    assert round_two["round_no"] == 2, (
        f"Expected round_no 2, got {round_two['round_no']}"
    )
    assert round_two["reviewer_user_id"] == world["reviewer_user_id"], (
        f"Expected the round-one owner {world['reviewer_user_id']} to own round two, got "
        f"{round_two['reviewer_user_id']}"
    )
    assert round_two["weighted_score"] is None, (
        f"Expected a null weighted_score, got {round_two['weighted_score']}"
    )
    assert round_two["outcome"] == "PENDING", (
        f"Expected outcome PENDING, got {round_two['outcome']}"
    )

    rounds, _ = validate_paginated(
        api_client.list_quality_reviews(world["engagement"]["id"], world["pm_headers"])
    )
    assert len(rounds) == 2, (
        f"Expected two review rounds on the engagement, got {len(rounds)}"
    )
    by_round = {row["round_no"]: row for row in rounds}
    assert by_round[1]["status"] == "REWORK_REQUESTED", (
        f"Expected round one to stay REWORK_REQUESTED, got {by_round[1]['status']}"
    )
    assert by_round[2]["status"] == "OPEN", (
        f"Expected round two OPEN, got {by_round[2]['status']}"
    )

    engagement = read_engagement(world)
    assert engagement["work_status"] == "SUBMITTED", (
        f"Expected the resubmitted engagement in SUBMITTED, got "
        f"{engagement['work_status']}"
    )


def test_34_a_failed_review_terminates_restates_the_valuation_and_pauses_the_volunteer(api):
    """PRD §3.8: "**Step one:** the engagement's `quality_gate` becomes `FAILED` and its
    `work_status` moves `SUBMITTED → TERMINATED` with `termination_reason` `QUALITY_FAILURE`,
    releasing the cycle slot and the window hours exactly as any termination does."
    PRD §3.8: "**Step two:** because the engagement terminated while holding a posted valuation,
    its `valuation_status` moves from `FINAL` or `PROVISIONAL` to `RESTATED`, a compensating
    `INDEPENDENT_SECTOR` valuation record carrying `variant_label` `RESTATED` is posted, and the
    prior record's `superseded_at` is stamped."
    PRD §3.8: "**Step three:** because a restated record was posted, the volunteer's
    `lifetime_valued_usd` is recomputed from her non-superseded `INDEPENDENT_SECTOR` records and
    both reliability variants rerun."
    PRD §3.8: "**Step four:** because the decay-weighted `reliability_score` has now fallen
    strictly below 0.4000, the volunteer moves `ACTIVE → PAUSED` with `pause_reason`
    `RELIABILITY_FLOOR`, and every match offer she still holds in `OFFERED` moves to `WITHDRAWN`
    with `withdraw_reason` `VOLUNTEER_PAUSED`, releasing their reserved hours and their cycle
    slots in turn."

    Design: Corner/state_machines/sm_quality_review_fail_runs_cascade_b_restatement_and_pause
    """
    world = setup_held_milestone_engagement(
        cycle_slots=CYCLE_SLOTS,
        window_hours=WINDOW_HOURS,
        deliverables=SINGLE_DELIVERABLE,
    )
    provisional = validate_success(post_valuation(world, method="INDEPENDENT_SECTOR"), 201)
    assert provisional["total_amount_usd"] == pytest.approx(1558.59, abs=0.005), (
        f"Setup expected 40.00 approved hours valued at 1558.59, got "
        f"{provisional['total_amount_usd']}"
    )
    validate_success(
        api_client.submit_engagement(
            world["engagement"]["id"], world["volunteer_headers"]
        )
    )
    deliverable = read_deliverables(world)[0]
    review = drive_review_to_outcome(world, {deliverable["id"]: 2})
    assert review["outcome"] == "FAIL", (
        f"Setup expected a FAIL round at weighted_score 40.00, got {review['outcome']}"
    )

    decided = validate_success(
        api_client.decide_quality_review(review["id"], world["reviewer_headers"])
    )

    assert decided["status"] == "DECIDED", (
        f"Expected the review DECIDED, got {decided['status']}"
    )
    assert decided["weighted_score"] == pytest.approx(40.00, abs=0.005), (
        f"Expected weighted_score 40.00, got {decided['weighted_score']}"
    )

    engagement = read_engagement(world)
    assert engagement["work_status"] == "TERMINATED", (
        f"Expected work_status TERMINATED, got {engagement['work_status']}"
    )
    assert engagement["termination_reason"] == "QUALITY_FAILURE", (
        f"Expected termination_reason QUALITY_FAILURE, got "
        f"{engagement['termination_reason']}"
    )
    assert engagement["quality_gate"] == "FAILED", (
        f"Expected quality_gate FAILED, got {engagement['quality_gate']}"
    )
    assert engagement["valuation_status"] == "RESTATED", (
        f"Expected valuation_status RESTATED, got {engagement['valuation_status']}"
    )

    records = read_valuation_records(world)
    assert len(records) == 2, (
        f"Expected the original plus a compensating record, got {len(records)}"
    )
    original = [r for r in records if r["id"] == provisional["id"]][0]
    restated = [r for r in records if r["id"] != provisional["id"]][0]
    assert original["variant_label"] == "PROVISIONAL", (
        f"Expected the original labelled PROVISIONAL, got {original['variant_label']}"
    )
    assert original["superseded_at"] is not None, (
        "Expected the original record's superseded_at stamped"
    )
    assert restated["variant_label"] == "RESTATED", (
        f"Expected the compensating record labelled RESTATED, got "
        f"{restated['variant_label']}"
    )
    assert restated["method"] == "INDEPENDENT_SECTOR", (
        f"Expected the compensating record posted as INDEPENDENT_SECTOR, got "
        f"{restated['method']}"
    )
    assert restated["total_amount_usd"] == pytest.approx(1558.59, abs=0.005), (
        f"Expected the compensating record computed from the same approved hours at 1558.59, "
        f"got {restated['total_amount_usd']}"
    )
    assert restated["superseded_at"] is None, (
        f"Expected the newest record not superseded, got {restated['superseded_at']}"
    )

    volunteer = read_volunteer(world)
    assert volunteer["lifetime_valued_usd"] == pytest.approx(1558.59, abs=0.005), (
        f"Expected lifetime_valued_usd 1558.59 with the superseded row excluded, got "
        f"{volunteer['lifetime_valued_usd']}"
    )
    assert volunteer["terminal_engagement_count"] == 1, (
        f"Expected terminal_engagement_count 1, got "
        f"{volunteer['terminal_engagement_count']}"
    )
    assert volunteer["reliability_score"] == pytest.approx(0.0000, abs=0.00005), (
        f"Expected reliability_score 0.0000 for a QUALITY_FAILURE termination, got "
        f"{volunteer['reliability_score']}"
    )
    assert volunteer["reliability_score_lifetime"] == pytest.approx(0.0000, abs=0.00005), (
        f"Expected reliability_score_lifetime 0.0000, got "
        f"{volunteer['reliability_score_lifetime']}"
    )
    assert volunteer["status"] == "PAUSED", (
        f"Expected the volunteer PAUSED below the 0.4000 floor, got {volunteer['status']}"
    )
    assert volunteer["pause_reason"] == "RELIABILITY_FLOOR", (
        f"Expected pause_reason RELIABILITY_FLOOR, got {volunteer['pause_reason']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 0, (
        f"Expected the cycle slot released, got slots_committed {cycle['slots_committed']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.0000, abs=0.00005), (
        f"Expected utilization_ratio 0.0000, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"Expected posture OPEN, got {cycle['posture']}"
    )

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.005), (
        f"Expected the window hours released, got {window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(WINDOW_HOURS, abs=0.005), (
        f"Expected hours_remaining {WINDOW_HOURS}, got {window['hours_remaining']}"
    )


def test_35_handoff_closes_the_request_and_returns_the_capacity(api):
    """PRD §3.8: "On success `handoff_at` is stamped from the logical clock and the engagement
    moves `ACCEPTED → HANDED_OFF`; the parent request moves `IN_DELIVERY → CLOSED` with
    `closed_at` stamped; the cycle's `slots_committed` falls by one and the posture recomputes,
    which may release a `FROZEN` cycle back to `RESTRICTED` or `OPEN`; the holding window's
    `hours_committed` falls by the engagement's full current `committed_hours`, including any
    hours an approved scope change added; and the volunteer's `terminal_engagement_count` rises by
    one while both reliability variants rerun."
    PRD §3.2: "Each terminal engagement earns a point value before penalties: 1.00 when it was
    `HANDED_OFF` with a `quality_gate` of `PASSED`."

    Design: Corner/state_machines/sm_engagement_handoff_closes_request_and_releases_capacity
    """
    world = setup_accepted_engagement(
        cycle_slots=CYCLE_SLOTS,
        window_hours=WINDOW_HOURS,
        deliverables=SINGLE_DELIVERABLE,
    )

    engagement = validate_success(
        api_client.handoff_engagement(
            world["engagement"]["id"],
            handoff_payload(confidentiality_attested=True, handoff_artifact_count=3),
            world["pm_headers"],
        )
    )

    assert engagement["work_status"] == "HANDED_OFF", (
        f"Expected work_status HANDED_OFF, got {engagement['work_status']}"
    )
    assert engagement["handoff_at"] is not None, (
        "Expected handoff_at stamped from the logical clock"
    )
    assert engagement["quality_gate"] == "PASSED", (
        f"Expected quality_gate PASSED, got {engagement['quality_gate']}"
    )
    assert engagement["terminated_at"] is None, (
        f"Expected terminated_at still null on the happy ending, got "
        f"{engagement['terminated_at']}"
    )
    assert engagement["handoff_artifact_count"] == 3, (
        f"Expected handoff_artifact_count 3, got {engagement['handoff_artifact_count']}"
    )
    assert engagement["confidentiality_attested"] is True, (
        f"Expected confidentiality_attested true, got "
        f"{engagement['confidentiality_attested']}"
    )

    request = read_request(world)
    assert request["status"] == "CLOSED", (
        f"Expected the request to move IN_DELIVERY → CLOSED, got {request['status']}"
    )
    assert request["closed_at"] is not None, (
        "Expected closed_at stamped on the closed request"
    )

    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 0, (
        f"Expected slots_committed released to 0, got {cycle['slots_committed']}"
    )
    assert cycle["slots_reserved"] == 0, (
        f"Expected slots_reserved 0, got {cycle['slots_reserved']}"
    )
    assert cycle["slots_available"] == CYCLE_SLOTS, (
        f"Expected slots_available {CYCLE_SLOTS}, got {cycle['slots_available']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.0000, abs=0.00005), (
        f"Expected utilization_ratio 0.0000, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"Expected posture OPEN, got {cycle['posture']}"
    )

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.005), (
        f"Expected the full committed_hours released, got {window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(WINDOW_HOURS, abs=0.005), (
        f"Expected hours_remaining {WINDOW_HOURS}, got {window['hours_remaining']}"
    )

    volunteer = read_volunteer(world)
    assert volunteer["terminal_engagement_count"] == 1, (
        f"Expected terminal_engagement_count 1, got "
        f"{volunteer['terminal_engagement_count']}"
    )
    assert volunteer["open_engagement_count"] == 0, (
        f"Expected open_engagement_count 0, got {volunteer['open_engagement_count']}"
    )
    assert volunteer["reliability_score"] == pytest.approx(1.0000, abs=0.00005), (
        f"Expected reliability_score 1.0000 for a PASSED handoff, got "
        f"{volunteer['reliability_score']}"
    )
    assert volunteer["reliability_score_lifetime"] == pytest.approx(1.0000, abs=0.00005), (
        f"Expected reliability_score_lifetime 1.0000, got "
        f"{volunteer['reliability_score_lifetime']}"
    )
    assert volunteer["status"] == "ACTIVE", (
        f"Expected the volunteer to stay ACTIVE, got {volunteer['status']}"
    )


def test_36_a_handed_off_engagement_refuses_termination(api):
    """PRD §3.9: "Terminating from `ACCEPTED` additionally requires `handoff_at` to still be null,
    and terminating an engagement already in `HANDED_OFF` or `TERMINATED` is refused with
    `ERR_INVALID_WORK_STATE`."

    Design: Corner/state_machines/sm_handed_off_engagement_cannot_be_terminated
    """
    world = setup_handed_off_engagement(
        cycle_slots=CYCLE_SLOTS,
        window_hours=WINDOW_HOURS,
        deliverables=SINGLE_DELIVERABLE,
    )

    validate_error(
        api_client.terminate_engagement(
            world["engagement"]["id"],
            world["pm_headers"],
            {"termination_reason": "ADMIN"},
        ),
        ApiErrorId.ERR_INVALID_WORK_STATE,
        409,
    )

    engagement = read_engagement(world)
    assert engagement["work_status"] == "HANDED_OFF", (
        f"Expected the engagement to stay HANDED_OFF, got {engagement['work_status']}"
    )
    assert engagement["terminated_at"] is None, (
        f"Expected terminated_at still null, got {engagement['terminated_at']}"
    )
    assert engagement["termination_reason"] is None, (
        f"Expected termination_reason still null, got {engagement['termination_reason']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 0, (
        f"Expected the slot to stay released exactly once, got "
        f"{cycle['slots_committed']}"
    )

    volunteer = read_volunteer(world)
    assert volunteer["terminal_engagement_count"] == 1, (
        f"Expected terminal_engagement_count to stay 1, got "
        f"{volunteer['terminal_engagement_count']}"
    )


def test_37_a_market_rate_post_values_a_running_engagement_as_provisional(api):
    """PRD §3.9: "`UNVALUED → PROVISIONAL` requires the engagement's `work_status` to be
    `IN_PROGRESS` or `SUBMITTED` and at least one child time log to be `approved`."
    PRD §3.9: "Each post writes a record whose `sequence_no` is one greater than the highest among
    sibling records *of the same method*, whose `variant_label` is `PROVISIONAL` or `FINAL`
    according to the stage reached, and whose `posted_at` is the logical clock; it stamps
    `superseded_at` on the prior non-superseded record of the same method."
    PRD §3.9: "For each admitted log it multiplies the log's `hours` by the lesser of that log's
    `rate_basis_usd` and the seniority ceiling, then by a class factor of 1.00 for `DELIVERY` and
    0.50 for `ADMIN` ... and rounds that line to two decimals."
    PRD §3.9: "`hours_included` is the sum of `hours` over the admitted logs, rounded to two
    decimals, and `rate_applied_usd` is the lesser of the volunteer's
    `professional_rate_usd_per_hour` and the seniority ceiling."
    PRD §3.9: "a base from 2500.00 up to but not including 10000.00 takes 0.09 ... third,
    `admin_overhead_usd` is the greater of a 45.00-dollar floor and the base multiplied by that
    tier rate rounded to two decimals ... Fourth, `total_amount_usd` is the base plus the
    overhead, rounded to two decimals."
    PRD §2.10: "records of the `MARKET_RATE` method never enter this total"

    Design: Corner/state_machines/sm_valuation_unvalued_to_provisional_on_market_rate_post
    """
    world = setup_held_milestone_engagement(
        cycle_slots=CYCLE_SLOTS,
        window_hours=WINDOW_HOURS,
        deliverables=SINGLE_DELIVERABLE,
        volunteer_rate=200.00,
        volunteer_seniority="SENIOR",
    )

    record = validate_success(post_valuation(world, method="MARKET_RATE"), 201)

    assert record["method"] == "MARKET_RATE", (
        f"Expected method MARKET_RATE, got {record['method']}"
    )
    assert record["variant_label"] == "PROVISIONAL", (
        f"Expected variant_label PROVISIONAL for the UNVALUED → PROVISIONAL stage, got "
        f"{record['variant_label']}"
    )
    assert record["sequence_no"] == 1, (
        f"Expected sequence_no 1 for the first MARKET_RATE record, got "
        f"{record['sequence_no']}"
    )
    assert record["hours_included"] == pytest.approx(40.00, abs=0.005), (
        f"Expected hours_included 40.00 over the four approved DELIVERY logs, got "
        f"{record['hours_included']}"
    )
    assert record["rate_applied_usd"] == pytest.approx(200.00, abs=0.005), (
        f"Expected rate_applied_usd 200.00, the lesser of the 200.00 personal rate and the "
        f"320.00 SENIOR ceiling, got {record['rate_applied_usd']}"
    )
    assert record["base_amount_usd"] == pytest.approx(8000.00, abs=0.005), (
        f"Expected base_amount_usd 8000.00 from four lines of 10.00 x 200.00 x 1.00, got "
        f"{record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(720.00, abs=0.005), (
        f"Expected admin_overhead_usd 720.00 from the 0.09 tier on an 8000.00 base, got "
        f"{record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(8720.00, abs=0.005), (
        f"Expected total_amount_usd 8720.00, got {record['total_amount_usd']}"
    )
    assert record["superseded_at"] is None, (
        f"Expected superseded_at null with no prior record of this method, got "
        f"{record['superseded_at']}"
    )
    assert record["posted_at"] is not None, (
        "Expected posted_at stamped from the logical clock"
    )

    engagement = read_engagement(world)
    assert engagement["valuation_status"] == "PROVISIONAL", (
        f"Expected valuation_status PROVISIONAL, got {engagement['valuation_status']}"
    )
    assert engagement["work_status"] == "IN_PROGRESS", (
        f"Expected work_status untouched at IN_PROGRESS, got {engagement['work_status']}"
    )

    volunteer = read_volunteer(world)
    assert volunteer["lifetime_valued_usd"] == pytest.approx(0.00, abs=0.005), (
        f"Expected lifetime_valued_usd to stay 0.00 because MARKET_RATE records never enter "
        f"that total, got {volunteer['lifetime_valued_usd']}"
    )


def test_38_a_post_after_handoff_takes_final_and_supersedes_the_provisional_row(api):
    """PRD §3.9: "`PROVISIONAL → FINAL` requires the `work_status` to be `HANDED_OFF`."
    PRD §3.9: "Each post writes a record whose `sequence_no` is one greater than the highest among
    sibling records *of the same method*, whose `variant_label` is `PROVISIONAL` or `FINAL`
    according to the stage reached, and whose `posted_at` is the logical clock; it stamps
    `superseded_at` on the prior non-superseded record of the same method; it recomputes the
    volunteer's `lifetime_valued_usd` from her non-superseded `INDEPENDENT_SECTOR` records."
    PRD §3.9: "It admits every approved log regardless of class ... sets `rate_applied_usd` to the
    flat national rate of 34.79 dollars an hour, and sets `base_amount_usd` to those hours
    multiplied by that rate, rounded once at the end."
    PRD §2.10: "A volunteer's `lifetime_valued_usd` equals the sum of `total_amount_usd` over that
    volunteer's valuation records whose `method` is `INDEPENDENT_SECTOR` and whose `superseded_at`
    is still null, rounded to two decimals."

    Design: Corner/state_machines/sm_valuation_provisional_to_final_after_handoff_supersedes_prior_record
    """
    world = setup_held_milestone_engagement(
        cycle_slots=CYCLE_SLOTS,
        window_hours=WINDOW_HOURS,
        deliverables=SINGLE_DELIVERABLE,
    )
    provisional = validate_success(post_valuation(world, method="INDEPENDENT_SECTOR"), 201)
    assert provisional["variant_label"] == "PROVISIONAL", (
        f"Setup expected a PROVISIONAL first record, got {provisional['variant_label']}"
    )
    validate_success(
        api_client.submit_engagement(
            world["engagement"]["id"], world["volunteer_headers"]
        )
    )
    deliverable = read_deliverables(world)[0]
    review = drive_review_to_outcome(world, {deliverable["id"]: 5})
    validate_success(
        api_client.decide_quality_review(review["id"], world["reviewer_headers"])
    )
    validate_success(
        api_client.handoff_engagement(
            world["engagement"]["id"], handoff_payload(), world["pm_headers"]
        )
    )

    record = validate_success(post_valuation(world, method="INDEPENDENT_SECTOR"), 201)

    assert record["variant_label"] == "FINAL", (
        f"Expected variant_label FINAL once the engagement is HANDED_OFF, got "
        f"{record['variant_label']}"
    )
    assert record["sequence_no"] == 2, (
        f"Expected sequence_no 2, one greater than the sibling of the same method, got "
        f"{record['sequence_no']}"
    )
    assert record["hours_included"] == pytest.approx(40.00, abs=0.005), (
        f"Expected hours_included 40.00, got {record['hours_included']}"
    )
    assert record["rate_applied_usd"] == pytest.approx(34.79, abs=0.005), (
        f"Expected the flat 34.79 national rate, got {record['rate_applied_usd']}"
    )
    assert record["base_amount_usd"] == pytest.approx(1391.60, abs=0.005), (
        f"Expected base_amount_usd 1391.60 from 40.00 x 34.79, got "
        f"{record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(166.99, abs=0.005), (
        f"Expected admin_overhead_usd 166.99 from the 0.12 tier on a base below 2500.00, got "
        f"{record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(1558.59, abs=0.005), (
        f"Expected total_amount_usd 1558.59, got {record['total_amount_usd']}"
    )
    assert record["superseded_at"] is None, (
        f"Expected the newest record not superseded, got {record['superseded_at']}"
    )

    engagement = read_engagement(world)
    assert engagement["valuation_status"] == "FINAL", (
        f"Expected valuation_status FINAL, got {engagement['valuation_status']}"
    )
    assert engagement["work_status"] == "HANDED_OFF", (
        f"Expected work_status HANDED_OFF, got {engagement['work_status']}"
    )

    records = read_valuation_records(world)
    prior = [row for row in records if row["id"] == provisional["id"]]
    assert len(prior) == 1, (
        f"Expected the prior record still listed for audit, got {len(prior)} matches"
    )
    assert prior[0]["superseded_at"] is not None, (
        "Expected superseded_at stamped on the prior non-superseded record of the same method"
    )

    volunteer = read_volunteer(world)
    assert volunteer["lifetime_valued_usd"] == pytest.approx(1558.59, abs=0.005), (
        f"Expected lifetime_valued_usd 1558.59 — one record's worth, the superseded row "
        f"excluded — got {volunteer['lifetime_valued_usd']}"
    )


def test_39_an_auto_approvable_scope_change_is_born_approved_and_applies_its_hours(api):
    """PRD §3.7: "Before the row is persisted the program projects its effect: take the
    engagement's `approved_hours`, add the sum of `additional_hours` over sibling change requests
    whose `status` is `PENDING` or `ESCALATED` — excluding the incoming row — add the incoming
    row's own `additional_hours`, subtract the engagement's `committed_hours` baseline, divide by
    that baseline and round to four decimals. That figure is stored as `projected_creep_pct`, and
    the `decision_tier` is chosen from it by tests applied in exactly this order: a projection at
    or above 0.5000 is `RESCOPE_REQUIRED`; otherwise a projection strictly below 0.1500 that also
    carries an `additional_deliverable_count` of exactly zero is `AUTO_APPROVABLE`; everything else
    is `MANAGER_REVIEW`."
    PRD §3.7: "An `AUTO_APPROVABLE` change is applied at once, moving `PENDING → APPROVED` in the
    same operation: the engagement's `committed_hours` rises by `additional_hours` and the holding
    window's `hours_committed` rises by the same amount, after which the creep calculation reruns
    against the *new* baseline."
    PRD §3.7: "The `requested_by` field is derived from the caller's role rather than supplied,
    reading `VOLUNTEER` or `PARTNER`."
    PRD §3.7: "The result drives `creep_escalation_level`: `NONE` below 0.1500 ... the ratio may
    legitimately be negative when a generous scope change has raised the baseline above the hours
    actually burned."

    Design: Corner/state_machines/sm_scope_change_auto_approvable_applies_hours_at_creation
    """
    world = setup_in_progress_engagement(
        cycle_slots=CYCLE_SLOTS,
        window_hours=WINDOW_HOURS,
        deliverables=SINGLE_DELIVERABLE,
    )

    change = validate_success(
        api_client.create_scope_change_request(
            world["engagement"]["id"],
            scope_change_request_payload(
                additional_hours=4.00,
                additional_deliverable_count=0,
                justification="Extra reconciliation pass on the FY25 ledger.",
            ),
            world["volunteer_headers"],
        ),
        201,
    )

    assert change["status"] == "APPROVED", (
        f"Expected an AUTO_APPROVABLE change to be born APPROVED, got {change['status']}"
    )
    assert change["decision_tier"] == "AUTO_APPROVABLE", (
        f"Expected decision_tier AUTO_APPROVABLE for a projection below 0.1500 asking for no "
        f"extra deliverable, got {change['decision_tier']}"
    )
    assert change["projected_creep_pct"] == pytest.approx(-0.9000, abs=0.00005), (
        f"Expected projected_creep_pct -0.9000 from (0.00 + 4.00 - 40.00) / 40.00, got "
        f"{change['projected_creep_pct']}"
    )
    assert change["requested_by"] == "VOLUNTEER", (
        f"Expected requested_by VOLUNTEER derived from the caller's role, got "
        f"{change['requested_by']}"
    )
    assert change["additional_hours"] == pytest.approx(4.00, abs=0.005), (
        f"Expected additional_hours 4.00, got {change['additional_hours']}"
    )

    engagement = read_engagement(world)
    assert engagement["committed_hours"] == pytest.approx(44.00, abs=0.005), (
        f"Expected committed_hours to rise to 44.00 in the same call, got "
        f"{engagement['committed_hours']}"
    )
    assert engagement["approved_hours"] == pytest.approx(0.00, abs=0.005), (
        f"Expected approved_hours to stay 0.00 with no approved log, got "
        f"{engagement['approved_hours']}"
    )
    assert engagement["scope_creep_pct"] == pytest.approx(-1.0000, abs=0.00005), (
        f"Expected scope_creep_pct -1.0000 against the new 44.00 baseline, got "
        f"{engagement['scope_creep_pct']}"
    )
    assert engagement["creep_escalation_level"] == "NONE", (
        f"Expected creep_escalation_level NONE below 0.1500, got "
        f"{engagement['creep_escalation_level']}"
    )

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(44.00, abs=0.005), (
        f"Expected the window's hours_committed to rise by the same 4.00 to 44.00, got "
        f"{window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(WINDOW_HOURS - 44.00, abs=0.005), (
        f"Expected hours_remaining {WINDOW_HOURS - 44.00}, got {window['hours_remaining']}"
    )


def test_40_rejecting_a_pending_scope_change_returns_the_creep_to_zero(api):
    """PRD §3.7: "the `decision_tier` is chosen from it by tests applied in exactly this order: a
    projection at or above 0.5000 is `RESCOPE_REQUIRED`; otherwise a projection strictly below
    0.1500 that also carries an `additional_deliverable_count` of exactly zero is
    `AUTO_APPROVABLE`; everything else is `MANAGER_REVIEW`."
    PRD §3.7: "A `MANAGER_REVIEW` change is stored in `PENDING` with a null `decided_by_user_id`
    and a null `decided_at`, and its pending hours immediately raise the engagement's
    `scope_creep_pct` even though no work has been done against them."
    PRD §3.7: "Rejection stamps the same two audit fields, moves the row `PENDING → REJECTED`, and
    lets the creep figure fall back, since the rejected hours leave the numerator."
    PRD §3.7: "The result drives `creep_escalation_level`: `NONE` below 0.1500, `WATCH` from 0.1500
    up to but not including 0.3000."

    Design: Corner/state_machines/sm_scope_change_pending_to_rejected_removes_pending_creep
    """
    world = setup_held_milestone_engagement(
        cycle_slots=CYCLE_SLOTS,
        window_hours=WINDOW_HOURS,
        deliverables=SINGLE_DELIVERABLE,
    )
    pending = validate_success(
        api_client.create_scope_change_request(
            world["engagement"]["id"],
            scope_change_request_payload(
                additional_hours=8.00,
                additional_deliverable_count=0,
                justification="Partner asks for a board presentation walkthrough.",
            ),
            world["partner_headers"],
        ),
        201,
    )
    assert pending["decision_tier"] == "MANAGER_REVIEW", (
        f"Setup expected a MANAGER_REVIEW tier at a 0.2000 projection, got "
        f"{pending['decision_tier']}"
    )
    assert pending["projected_creep_pct"] == pytest.approx(0.2000, abs=0.00005), (
        f"Setup expected projected_creep_pct 0.2000 from (40.00 + 8.00 - 40.00) / 40.00, got "
        f"{pending['projected_creep_pct']}"
    )
    assert pending["status"] == "PENDING", (
        f"Setup expected the row stored in PENDING, got {pending['status']}"
    )
    assert pending["decided_by_user_id"] is None, (
        f"Setup expected a null decided_by_user_id while PENDING, got "
        f"{pending['decided_by_user_id']}"
    )
    assert pending["decided_at"] is None, (
        f"Setup expected a null decided_at while PENDING, got {pending['decided_at']}"
    )
    live = read_engagement(world)
    assert live["scope_creep_pct"] == pytest.approx(0.2000, abs=0.00005), (
        f"Setup expected the pending hours to lift live creep to 0.2000, got "
        f"{live['scope_creep_pct']}"
    )
    assert live["creep_escalation_level"] == "WATCH", (
        f"Setup expected creep_escalation_level WATCH at 0.2000, got "
        f"{live['creep_escalation_level']}"
    )

    decided = validate_success(
        api_client.decide_scope_change_request(
            pending["id"], {"decision": "REJECT"}, world["pm_headers"]
        )
    )

    assert decided["status"] == "REJECTED", (
        f"Expected the row to move PENDING → REJECTED, got {decided['status']}"
    )
    assert decided["decided_by_user_id"] == world["pm_user_id"], (
        f"Expected decided_by_user_id {world['pm_user_id']}, got "
        f"{decided['decided_by_user_id']}"
    )
    assert decided["decided_at"] is not None, (
        "Expected decided_at stamped by the rejection"
    )

    engagement = read_engagement(world)
    assert engagement["committed_hours"] == pytest.approx(40.00, abs=0.005), (
        f"Expected committed_hours untouched at 40.00 by a rejection, got "
        f"{engagement['committed_hours']}"
    )
    assert engagement["approved_hours"] == pytest.approx(40.00, abs=0.005), (
        f"Expected approved_hours 40.00, got {engagement['approved_hours']}"
    )
    assert engagement["scope_creep_pct"] == pytest.approx(0.0000, abs=0.00005), (
        f"Expected scope_creep_pct to fall back to 0.0000 once the rejected hours left the "
        f"numerator, got {engagement['scope_creep_pct']}"
    )
    assert engagement["creep_escalation_level"] == "NONE", (
        f"Expected creep_escalation_level NONE at 0.0000, got "
        f"{engagement['creep_escalation_level']}"
    )

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(40.00, abs=0.005), (
        f"Expected the window commitment untouched at 40.00, got {window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(WINDOW_HOURS - 40.00, abs=0.005), (
        f"Expected hours_remaining {WINDOW_HOURS - 40.00}, got {window['hours_remaining']}"
    )


def test_41_a_rescope_required_change_escalates_and_terminates_the_engagement(api):
    """PRD §3.7: "the `decision_tier` is chosen from it by tests applied in exactly this order: a
    projection at or above 0.5000 is `RESCOPE_REQUIRED`."
    PRD §3.7: "A `RESCOPE_REQUIRED` change moves `PENDING → ESCALATED` in the same operation and is
    not a request for hours at all but a declaration that the engagement has outgrown its scope:
    the engagement is terminated with `termination_reason` `SCOPE_BREACH`, running the full release
    chain, the parent request moves `IN_DELIVERY → RESCOPING`, and the request's `rescope_count`
    rises by one."
    PRD §3.9: "The cycle's `slots_committed` falls by one and the posture recomputes. The holding
    window's `hours_committed` falls by the engagement's full current `committed_hours` ... Every
    child milestone still `SCHEDULED` moves to `WAIVED` with `waiver_reason`
    `ENGAGEMENT_TERMINATED`."
    PRD §3.2: "0.25 when it was `TERMINATED` for `SCOPE_BREACH` or `ADMIN`"

    Design: Corner/state_machines/sm_scope_change_rescope_required_escalates_and_terminates_engagement
    """
    world = setup_held_milestone_engagement(
        cycle_slots=CYCLE_SLOTS,
        window_hours=WINDOW_HOURS,
        deliverables=SINGLE_DELIVERABLE,
    )

    change = validate_success(
        api_client.create_scope_change_request(
            world["engagement"]["id"],
            scope_change_request_payload(
                additional_hours=22.00,
                additional_deliverable_count=0,
                justification="Ledger reconstruction is far larger than scoped.",
            ),
            world["volunteer_headers"],
        ),
        201,
    )

    assert change["decision_tier"] == "RESCOPE_REQUIRED", (
        f"Expected decision_tier RESCOPE_REQUIRED at a projection of 0.5500, got "
        f"{change['decision_tier']}"
    )
    assert change["projected_creep_pct"] == pytest.approx(0.5500, abs=0.00005), (
        f"Expected projected_creep_pct 0.5500 from (40.00 + 22.00 - 40.00) / 40.00, got "
        f"{change['projected_creep_pct']}"
    )

    engagement = read_engagement(world)
    assert engagement["work_status"] == "TERMINATED", (
        f"Expected the engagement terminated by the escalation, got "
        f"{engagement['work_status']}"
    )
    assert engagement["termination_reason"] == "SCOPE_BREACH", (
        f"Expected termination_reason SCOPE_BREACH, got {engagement['termination_reason']}"
    )
    assert engagement["terminated_at"] is not None, (
        "Expected terminated_at stamped by the release chain"
    )

    request = read_request(world)
    assert request["status"] == "RESCOPING", (
        f"Expected the request to move IN_DELIVERY → RESCOPING, got {request['status']}"
    )
    assert request["rescope_count"] == 1, (
        f"Expected rescope_count to rise by one to 1, got {request['rescope_count']}"
    )

    milestone = read_milestone(world)
    assert milestone["checkin_status"] == "HELD", (
        f"Expected the already HELD check-in untouched — only SCHEDULED ones are waived — got "
        f"{milestone['checkin_status']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 0, (
        f"Expected the cycle slot released, got slots_committed {cycle['slots_committed']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"Expected posture OPEN once the slot came back, got {cycle['posture']}"
    )

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.005), (
        f"Expected the window's full 40.00 commitment released, got "
        f"{window['hours_committed']}"
    )

    volunteer = read_volunteer(world)
    assert volunteer["reliability_score"] == pytest.approx(0.2500, abs=0.00005), (
        f"Expected reliability_score 0.2500 for a SCOPE_BREACH termination, got "
        f"{volunteer['reliability_score']}"
    )
    assert volunteer["terminal_engagement_count"] == 1, (
        f"Expected terminal_engagement_count 1, got "
        f"{volunteer['terminal_engagement_count']}"
    )
    assert volunteer["status"] == "PAUSED", (
        f"Expected the volunteer PAUSED below the 0.4000 floor, got {volunteer['status']}"
    )
    assert volunteer["pause_reason"] == "RELIABILITY_FLOOR", (
        f"Expected pause_reason RELIABILITY_FLOOR, got {volunteer['pause_reason']}"
    )

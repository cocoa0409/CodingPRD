"""Review-decision constraints, Peer-to-Peer scheduling/overlap, the open-P2P
decision block, the SLA-pause cascade on completion, duplicate-active-auth, and
the priority-ordered validation conflicts.

Translates queue A (cross_entity_state_dependency, priority_pair_validation_conflict,
resource_temporal_overlap) and queue B (validations, state_machines P2P) instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    register_actors,
    set_clock,
    create_under_review_request,
    create_approved_request,
    schedule_p2p,
    render_decision,
    make_provider_headers,
    make_payer_headers,
)


# --------------------------------------------------------------------------
# cross-entity state dependency: open P2P blocks decision (queue A)
# Also owns corner stubs validations/open_p2p_blocks_decision_violation
# --------------------------------------------------------------------------

def test_decision_blocked_while_p2p_scheduled(api):
    """PRD §3.4: "An open Peer-to-Peer session blocks decision-making: no
    `ReviewDecision` may be rendered for a request while any of that request's
    sessions is still `SCHEDULED`. The session must first be completed or
    cancelled. An attempt to decide over a still-`SCHEDULED` session is rejected
    with `ERR_OPEN_P2P_BLOCKS_DECISION` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/decision_blocked_while_p2p_scheduled
    """
    actors = register_actors(provider_overrides={"specialty": "CARDIOLOGY"},
                             reviewer_overrides={"specialty": "CARDIOLOGY"})
    payer_h = make_payer_headers(actors["payer"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-D",
                           "requested_units": 1, "unit_cost_cents": 5000},
    )
    get_success_data(schedule_p2p(actors, ur["id"], "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z"))
    resp = api.create_review_decision(
        {"request_id": ur["id"], "reviewer_id": actors["reviewer"]["id"],
         "outcome": "APPROVE", "approved_units": 1, "rationale": "OK"},
        payer_h,
    )
    validate_error(resp, ApiErrorId.ERR_OPEN_P2P_BLOCKS_DECISION.value)


def test_open_p2p_blocks_decision_violation(api):
    """PRD §3.4: "An open Peer-to-Peer session blocks decision-making: no
    `ReviewDecision` may be rendered for a request while any of that request's
    sessions is still `SCHEDULED`. ... An attempt to decide over a
    still-`SCHEDULED` session is rejected with `ERR_OPEN_P2P_BLOCKS_DECISION`
    (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/decision_blocked_while_p2p_scheduled
    """
    actors = register_actors(provider_overrides={"specialty": "ONCOLOGY"})
    payer_h = make_payer_headers(actors["payer"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "DRUG", "procedure_code": "NDC-9",
                           "requested_units": 1, "unit_cost_cents": 5000},
    )
    get_success_data(schedule_p2p(actors, ur["id"], "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z"))
    resp = render_decision(actors, ur["id"], "DENY", rationale="no")
    validate_error(resp, ApiErrorId.ERR_OPEN_P2P_BLOCKS_DECISION.value)


# --------------------------------------------------------------------------
# P2P complete credits SLA pause — side effect (queue B)
# --------------------------------------------------------------------------

def test_p2p_complete_credits_sla_pause_cross_entity(api):
    """PRD §3.4: "Completion adds the slot's duration — the hours from
    `slot_start` to `slot_end` — to the linked request's `clock_paused_hours`,
    recomputes that request's `sla_due_at`". PRD §3.4: "The deadline `sla_due_at`
    is then `review_started_at` advanced by the sum of that base allowance and the
    accumulated `clock_paused_hours`".

    Design: Corner/state_machines/p2p_complete_credits_sla_pause_cross_entity
    """
    actors = register_actors(
        payer_overrides={"standard_sla_hours": 168, "expedited_sla_hours": 72},
        provider_overrides={"specialty": "CARDIOLOGY"},
        reviewer_overrides={"specialty": "CARDIOLOGY"},
    )
    payer_h = make_payer_headers(actors["payer"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-1",
                           "requested_units": 1, "unit_cost_cents": 5000},
    )
    p2p = get_success_data(schedule_p2p(actors, ur["id"], "2026-06-02T10:00:00Z", "2026-06-02T12:00:00Z"))
    completed = validate_success(api.complete_peer_to_peer_session(p2p["id"], payer_h))
    assert completed["status"] == "COMPLETED"
    req = get_success_data(api.get_authorization_request(ur["id"], payer_h))
    assert req["clock_paused_hours"] == 2, f"2h slot duration; got {req['clock_paused_hours']}"
    assert req["sla_due_at"] == "2026-06-08T02:00:00Z", (
        f"168h + 2h pause after 2026-06-01; got {req['sla_due_at']}"
    )


# --------------------------------------------------------------------------
# resource temporal overlap: P2P buffer gap conflict (queue A)
# Also owns corner stub errors/error_p2p_slot_conflict_triggerable
# --------------------------------------------------------------------------

def test_p2p_slot_buffer_gap_conflict_on_reviewer(api):
    """PRD §3.4: "A proposed slot, treated as the half-open interval from
    `slot_start` up to but not including `slot_end`, conflicts with any other
    non-`CANCELLED` slot of the same reviewer when the two intervals overlap, or
    when the gap between them is less than that reviewer's `p2p_buffer_minutes`.
    A conflicting slot is rejected with `ERR_P2P_SLOT_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/p2p_slot_buffer_gap_conflict_on_reviewer
    """
    actors = register_actors(provider_overrides={"specialty": "RADIOLOGY"},
                             reviewer_overrides={"specialty": "RADIOLOGY", "p2p_buffer_minutes": 30})
    payer_h = make_payer_headers(actors["payer"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-R",
                           "requested_units": 1, "unit_cost_cents": 5000},
    )
    get_success_data(schedule_p2p(actors, ur["id"], "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z"))
    # New slot starts 15 min after the prior ends; gap 15 < buffer 30 -> conflict.
    resp = schedule_p2p(actors, ur["id"], "2026-06-02T11:15:00Z", "2026-06-02T11:45:00Z")
    validate_error(resp, ApiErrorId.ERR_P2P_SLOT_CONFLICT.value)


def test_error_p2p_slot_conflict_triggerable(api):
    """PRD §3.4: "A proposed slot, treated as the half-open interval from
    `slot_start` up to but not including `slot_end`, conflicts with any other
    non-`CANCELLED` slot of the same reviewer when the two intervals overlap, or
    when the gap between them is less than that reviewer's `p2p_buffer_minutes`.
    A conflicting slot is rejected with `ERR_P2P_SLOT_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/p2p_slot_buffer_gap_conflict_on_reviewer
    """
    actors = register_actors(provider_overrides={"specialty": "RADIOLOGY"},
                             reviewer_overrides={"specialty": "RADIOLOGY", "p2p_buffer_minutes": 0})
    payer_h = make_payer_headers(actors["payer"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-R2",
                           "requested_units": 1, "unit_cost_cents": 5000},
    )
    get_success_data(schedule_p2p(actors, ur["id"], "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z"))
    # Overlapping interval, buffer 0 -> conflict from overlap.
    resp = schedule_p2p(actors, ur["id"], "2026-06-02T10:30:00Z", "2026-06-02T11:30:00Z")
    validate_error(resp, ApiErrorId.ERR_P2P_SLOT_CONFLICT.value)


# --------------------------------------------------------------------------
# resource temporal overlap: duplicate active authorization (queue A)
# --------------------------------------------------------------------------

def test_duplicate_active_authorization_coverage_overlap(api):
    """PRD §3.8: "The system permits exactly one concurrent active authorization
    per member and procedure code. ... An approval is rejected with
    `ERR_DUPLICATE_ACTIVE_AUTH` (HTTP 409) when this interval would overlap the
    coverage interval of any existing `APPROVED` request — one that is neither
    `EXPIRED` nor `SUPERSEDED` — for the same member and the same `procedure_code`."

    Design: Difficulty/resource_temporal_overlap/duplicate_active_authorization_coverage_overlap
    """
    actors = register_actors(provider_overrides={"specialty": "CARDIOLOGY"},
                             reviewer_overrides={"specialty": "CARDIOLOGY"})
    payer_h = make_payer_headers(actors["payer"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    # First approved request for member + CPT-DUP.
    create_approved_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-DUP",
                           "requested_units": 1, "unit_cost_cents": 5000},
        approved_units=1,
    )
    # Second request, same member + procedure, brought UNDER_REVIEW, then approve attempt.
    ur_b = create_under_review_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-DUP",
                           "requested_units": 1, "unit_cost_cents": 5000},
    )
    resp = render_decision(actors, ur_b["id"], "APPROVE", approved_units=1, rationale="Second")
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_AUTH.value)


def test_duplicate_active_auth_different_procedure_allowed(api):
    """PRD §3.8: "The system permits exactly one concurrent active authorization
    per member and procedure code. ... An approval is rejected with
    `ERR_DUPLICATE_ACTIVE_AUTH` (HTTP 409) when this interval would overlap the
    coverage interval of any existing `APPROVED` request — one that is neither
    `EXPIRED` nor `SUPERSEDED` — for the same member and the same `procedure_code`."

    Design: Difficulty/resource_temporal_overlap/duplicate_active_authorization_coverage_overlap
    """
    actors = register_actors(provider_overrides={"specialty": "CARDIOLOGY"},
                             reviewer_overrides={"specialty": "CARDIOLOGY"})
    payer_h = make_payer_headers(actors["payer"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    # First approved request for member + CPT-AAA.
    create_approved_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-AAA",
                           "requested_units": 1, "unit_cost_cents": 5000},
        approved_units=1,
    )
    # Second request, SAME member but DIFFERENT procedure -> no duplicate.
    ur_b = create_under_review_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-BBB",
                           "requested_units": 1, "unit_cost_cents": 5000},
    )
    resp = render_decision(actors, ur_b["id"], "APPROVE", approved_units=1, rationale="Different proc")
    data = validate_success(resp, expected_status=201)
    fetched = get_success_data(api.get_authorization_request(ur_b["id"], payer_h))
    assert fetched["status"] == "APPROVED", (
        f"different procedure_code is not a duplicate, got {fetched['status']}"
    )


# --------------------------------------------------------------------------
# priority-pair conflict: open P2P (P6) beats past-deadline (P9) (queue A)
# --------------------------------------------------------------------------

def test_open_p2p_safety_beats_past_deadline_temporal(api):
    """PRD §3.9: "After those structural checks come the business rules in order:
    the reviewer-payer match (`ERR_REVIEWER_PAYER_MISMATCH`), the
    open-Peer-to-Peer block on decisions (`ERR_OPEN_P2P_BLOCKS_DECISION`), the
    evidence requirement on submit (`ERR_NO_EVIDENCE`), the Peer-to-Peer
    slot-conflict check (`ERR_P2P_SLOT_CONFLICT`), the duplicate-active-authorization
    check (`ERR_DUPLICATE_ACTIVE_AUTH`), the deadline check (`ERR_PAST_DEADLINE`)".

    Design: Difficulty/priority_pair_validation_conflict/open_p2p_safety_beats_past_deadline_temporal
    """
    actors = register_actors(
        payer_overrides={"standard_sla_hours": 168, "expedited_sla_hours": 72},
        provider_overrides={"specialty": "CARDIOLOGY"},
        reviewer_overrides={"specialty": "CARDIOLOGY"},
    )
    payer_h = make_payer_headers(actors["payer"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-P",
                           "requested_units": 1, "unit_cost_cents": 5000},
    )
    get_success_data(schedule_p2p(actors, ur["id"], "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z"))
    # Advance past sla_due_at (2026-06-08) so BOTH P6 and P9 would fire; P6 wins.
    set_clock("2026-07-01T00:00:00Z", payer_h)
    resp = api.create_review_decision(
        {"request_id": ur["id"], "reviewer_id": actors["reviewer"]["id"],
         "outcome": "APPROVE", "approved_units": 1, "rationale": "OK"},
        payer_h,
    )
    validate_error(resp, ApiErrorId.ERR_OPEN_P2P_BLOCKS_DECISION.value)


def test_open_p2p_beats_past_deadline_on_deny(api):
    """PRD §3.9: "After those structural checks come the business rules in order:
    the reviewer-payer match (`ERR_REVIEWER_PAYER_MISMATCH`), the
    open-Peer-to-Peer block on decisions (`ERR_OPEN_P2P_BLOCKS_DECISION`), the
    evidence requirement on submit (`ERR_NO_EVIDENCE`), the Peer-to-Peer
    slot-conflict check (`ERR_P2P_SLOT_CONFLICT`), the duplicate-active-authorization
    check (`ERR_DUPLICATE_ACTIVE_AUTH`), the deadline check (`ERR_PAST_DEADLINE`)".

    Design: Difficulty/priority_pair_validation_conflict/open_p2p_safety_beats_past_deadline_temporal
    """
    actors = register_actors(
        payer_overrides={"standard_sla_hours": 168, "expedited_sla_hours": 72},
        provider_overrides={"specialty": "CARDIOLOGY"},
        reviewer_overrides={"specialty": "CARDIOLOGY"},
    )
    payer_h = make_payer_headers(actors["payer"]["id"])
    set_clock("2026-06-01T00:00:00Z", payer_h)
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-P2",
                           "requested_units": 1, "unit_cost_cents": 5000},
    )
    get_success_data(schedule_p2p(actors, ur["id"], "2026-06-02T10:00:00Z", "2026-06-02T11:00:00Z"))
    # Past sla_due_at AND open P2P: P6 still wins for a DENY decision too.
    set_clock("2026-07-01T00:00:00Z", payer_h)
    resp = render_decision(actors, ur["id"], "DENY", rationale="no")
    validate_error(resp, ApiErrorId.ERR_OPEN_P2P_BLOCKS_DECISION.value)


# --------------------------------------------------------------------------
# priority-pair conflict: reviewer mismatch (P5) beats invalid fields (P10)
# Also owns corner stub errors/error_reviewer_payer_mismatch_triggerable (queue A)
# --------------------------------------------------------------------------

def test_reviewer_mismatch_referential_beats_invalid_decision_fields(api):
    """PRD §3.3: "A reviewer whose `payer_id` does not match the request's
    `payer_id` is rejected with `ERR_REVIEWER_PAYER_MISMATCH` (HTTP 422) — a
    reviewer may act only on its own payer's requests." PRD §3.9: "After those
    structural checks come the business rules in order: the reviewer-payer match
    (`ERR_REVIEWER_PAYER_MISMATCH`), ... the decision-field validity check
    (`ERR_INVALID_DECISION_FIELDS`)".

    Design: Difficulty/priority_pair_validation_conflict/reviewer_mismatch_referential_beats_invalid_decision_fields
    """
    actors = register_actors(provider_overrides={"specialty": "CARDIOLOGY"}, with_reviewer=False)
    payer_a = actors["payer"]
    payer_h_a = make_payer_headers(payer_a["id"])
    # A reviewer belonging to a DIFFERENT payer B.
    payer_b = get_success_data(api.create_payer({"name": "Payer B"}, None))
    reviewer_b = get_success_data(
        api.create_reviewer({"payer_id": payer_b["id"], "name": "Rev B", "specialty": "CARDIOLOGY"}, None)
    )
    set_clock("2026-06-01T00:00:00Z", payer_h_a)
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-Q",
                           "requested_units": 2, "unit_cost_cents": 5000},
    )
    # PARTIAL with approved_units=0 is invalid (P10), reviewer is mismatched (P5). P5 wins.
    resp = api.create_review_decision(
        {"request_id": ur["id"], "reviewer_id": reviewer_b["id"],
         "outcome": "PARTIAL", "approved_units": 0, "rationale": "x"},
        payer_h_a,
    )
    validate_error(resp, ApiErrorId.ERR_REVIEWER_PAYER_MISMATCH.value)


def test_error_reviewer_payer_mismatch_triggerable(api):
    """PRD §3.3: "A reviewer whose `payer_id` does not match the request's
    `payer_id` is rejected with `ERR_REVIEWER_PAYER_MISMATCH` (HTTP 422) — a
    reviewer may act only on its own payer's requests."

    Design: Difficulty/priority_pair_validation_conflict/reviewer_mismatch_referential_beats_invalid_decision_fields
    """
    actors = register_actors(provider_overrides={"specialty": "CARDIOLOGY"}, with_reviewer=False)
    payer_h_a = make_payer_headers(actors["payer"]["id"])
    payer_b = get_success_data(api.create_payer({"name": "Payer B"}, None))
    reviewer_b = get_success_data(
        api.create_reviewer({"payer_id": payer_b["id"], "name": "Rev B", "specialty": "CARDIOLOGY"}, None)
    )
    set_clock("2026-06-01T00:00:00Z", payer_h_a)
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "SERVICE", "procedure_code": "CPT-Q2",
                           "requested_units": 2, "unit_cost_cents": 5000},
    )
    # Valid decision fields, but mismatched reviewer.
    resp = api.create_review_decision(
        {"request_id": ur["id"], "reviewer_id": reviewer_b["id"],
         "outcome": "APPROVE", "approved_units": 2, "rationale": "OK"},
        payer_h_a,
    )
    validate_error(resp, ApiErrorId.ERR_REVIEWER_PAYER_MISMATCH.value)


# --------------------------------------------------------------------------
# decision-field validity corner (queue B)
# --------------------------------------------------------------------------

def test_partial_units_equal_requested_rejected(api):
    """PRD §3.3: "If the decision-field combination is invalid — a `PARTIAL` whose
    units fall outside the range from 1 up to but not including `requested_units`
    ... — the request is rejected with `ERR_INVALID_DECISION_FIELDS` (HTTP 422)."

    Design: Corner/validations/partial_units_equal_requested_rejected
    """
    actors = register_actors()
    set_clock("2026-06-01T00:00:00Z", make_payer_headers(actors["payer"]["id"]))
    ur = create_under_review_request(
        actors,
        request_overrides={"request_type": "DRUG", "procedure_code": "NDC-1",
                           "requested_units": 4, "unit_cost_cents": 5000},
    )
    resp = render_decision(actors, ur["id"], "PARTIAL", approved_units=4, rationale="all")
    validate_error(resp, ApiErrorId.ERR_INVALID_DECISION_FIELDS.value)



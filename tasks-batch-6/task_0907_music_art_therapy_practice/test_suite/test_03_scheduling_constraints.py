"""Session scheduling: calendar overlap, room buffer, capacity, cross-entity
plan-active gate, referential-vs-fiscal precedence, material/contract budget.

Queue A: resource_temporal_overlap, boundary_precision_check,
cross_entity_state_dependency (plan-active), priority_pair (referential>fiscal).
Queue B: contract budget, insufficient material, duplicate enroll, end<=start.
"""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx


# ================================================== therapist overlap (queue A)
def test_therapist_tail_overlap_rejected(api):
    """PRD §3.5: "the requested half-open interval, from `start_utc` up to but not
    including `end_utc`, must not overlap any other non-cancelled session for the
    same therapist; two sessions that merely touch at a boundary (one ending exactly
    when the next begins) do not conflict, but any true overlap raises
    `ERR_THERAPIST_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/therapist_halfopen_overlap_rejected
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    room2 = fx.new_room(api, name="Room 2")
    fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"],
                        start_utc="2026-06-01T09:00:00Z", end_utc="2026-06-01T10:00:00Z")
    resp = api.create_session(
        {"therapist_id": ctx["ther_id"], "room_id": room2["id"], "plan_id": ctx["plan_id"],
         "goal_id": ctx["goal_id"], "modality": "INDIVIDUAL",
         "start_utc": "2026-06-01T09:30:00Z", "end_utc": "2026-06-01T10:30:00Z", "capacity": 1},
        ctx["ther_headers"])
    validate_error(resp, ApiErrorId.ERR_THERAPIST_UNAVAILABLE.value)


def test_therapist_head_overlap_rejected(api):
    """PRD §3.5: "the requested half-open interval, from `start_utc` up to but not
    including `end_utc`, must not overlap any other non-cancelled session for the
    same therapist; two sessions that merely touch at a boundary (one ending exactly
    when the next begins) do not conflict, but any true overlap raises
    `ERR_THERAPIST_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/therapist_halfopen_overlap_rejected
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    room2 = fx.new_room(api, name="Room 2")
    fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"],
                        start_utc="2026-06-01T09:00:00Z", end_utc="2026-06-01T10:00:00Z")
    resp = api.create_session(
        {"therapist_id": ctx["ther_id"], "room_id": room2["id"], "plan_id": ctx["plan_id"],
         "goal_id": ctx["goal_id"], "modality": "INDIVIDUAL",
         "start_utc": "2026-06-01T08:30:00Z", "end_utc": "2026-06-01T09:30:00Z", "capacity": 1},
        ctx["ther_headers"])
    validate_error(resp, ApiErrorId.ERR_THERAPIST_UNAVAILABLE.value)


# ================================================== room buffer (queue A)
def test_room_buffer_gap_after_rejected(api):
    """PRD §3.5: "the practice enforces a fifteen-minute turnaround buffer, so a new
    booking conflicts with any non-cancelled session in the same room whose interval,
    expanded by fifteen minutes both before its start and after its end, overlaps the
    new session's interval; a conflict raises `ERR_ROOM_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/room_turnaround_buffer_rejected
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"],
                        start_utc="2026-06-01T09:00:00Z", end_utc="2026-06-01T10:00:00Z")
    # New booking starts 10:05 — only 5 minutes after the first ends (< 15-min buffer).
    resp = api.create_session(
        {"therapist_id": ctx["ther_id"], "room_id": ctx["room_id"], "plan_id": ctx["plan_id"],
         "goal_id": ctx["goal_id"], "modality": "INDIVIDUAL",
         "start_utc": "2026-06-01T10:05:00Z", "end_utc": "2026-06-01T11:00:00Z", "capacity": 1},
        ctx["ther_headers"])
    validate_error(resp, ApiErrorId.ERR_ROOM_UNAVAILABLE.value)


def test_room_buffer_gap_before_rejected(api):
    """PRD §3.5: "the practice enforces a fifteen-minute turnaround buffer, so a new
    booking conflicts with any non-cancelled session in the same room whose interval,
    expanded by fifteen minutes both before its start and after its end, overlaps the
    new session's interval; a conflict raises `ERR_ROOM_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/room_turnaround_buffer_rejected
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"],
                        start_utc="2026-06-01T09:00:00Z", end_utc="2026-06-01T10:00:00Z")
    # New booking ends 08:50 — only 10 minutes before the first starts (< 15-min buffer).
    resp = api.create_session(
        {"therapist_id": ctx["ther_id"], "room_id": ctx["room_id"], "plan_id": ctx["plan_id"],
         "goal_id": ctx["goal_id"], "modality": "INDIVIDUAL",
         "start_utc": "2026-06-01T08:00:00Z", "end_utc": "2026-06-01T08:50:00Z", "capacity": 1},
        ctx["ther_headers"])
    validate_error(resp, ApiErrorId.ERR_ROOM_UNAVAILABLE.value)


# ================================================== adjacent interval (queue A)
def test_therapist_adjacent_session_allowed(api):
    """PRD §3.5: "two sessions that merely touch at a boundary (one ending exactly
    when the next begins) do not conflict, but any true overlap raises
    `ERR_THERAPIST_UNAVAILABLE`."

    Design: Difficulty/boundary_precision_check/therapist_adjacent_interval_allowed
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    room2 = fx.new_room(api, name="Room 2")
    fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"],
                        start_utc="2026-06-01T09:00:00Z", end_utc="2026-06-01T10:00:00Z")
    resp = api.create_session(
        {"therapist_id": ctx["ther_id"], "room_id": room2["id"], "plan_id": ctx["plan_id"],
         "goal_id": ctx["goal_id"], "modality": "INDIVIDUAL",
         "start_utc": "2026-06-01T10:00:00Z", "end_utc": "2026-06-01T11:00:00Z", "capacity": 1},
        ctx["ther_headers"])
    validate_success(resp, expected_status=201)


def test_therapist_adjacent_session_is_scheduled(api):
    """PRD §3.5: "two sessions that merely touch at a boundary (one ending exactly
    when the next begins) do not conflict, but any true overlap raises
    `ERR_THERAPIST_UNAVAILABLE`."
    PRD §3.5: "A new session opens with `scheduling_status` at `SCHEDULED` and
    `billing_status` at `UNBILLED`".

    Design: Difficulty/boundary_precision_check/therapist_adjacent_interval_allowed
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    room2 = fx.new_room(api, name="Room 2")
    fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"],
                        start_utc="2026-06-01T09:00:00Z", end_utc="2026-06-01T10:00:00Z")
    resp = api.create_session(
        {"therapist_id": ctx["ther_id"], "room_id": room2["id"], "plan_id": ctx["plan_id"],
         "goal_id": ctx["goal_id"], "modality": "INDIVIDUAL",
         "start_utc": "2026-06-01T10:00:00Z", "end_utc": "2026-06-01T11:00:00Z", "capacity": 1},
        ctx["ther_headers"])
    data = validate_success(resp, expected_status=201)
    assert data["scheduling_status"] == "SCHEDULED"


# ================================================== group capacity (queue A)
def test_group_enroll_below_capacity_succeeds(api):
    """PRD §3.6: "enrollment is refused once the non-cancelled enrollment count has
    reached the session's `capacity` (`ERR_SESSION_FULL`). An individual session,
    defaulting to a capacity of 1, therefore admits exactly one active enrollee,
    while a group session admits up to its stated capacity."

    Design: Difficulty/boundary_precision_check/group_capacity_at_limit_rejects
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY", room_capacity=8)
    c2 = fx.new_self_pay_client(api, full_name="c2")
    session = fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"],
                                  ctx["goal_id"], modality="GROUP", capacity=2)
    fx.enroll(api, session["id"], ctx["client_id"], ctx["ther_id"])  # count -> 1
    resp = api.enroll_client(session["id"], {"client_id": c2["id"]}, ctx["ther_headers"])
    validate_success(resp, expected_status=201)  # count 1 == capacity-1, allowed


def test_group_enroll_at_capacity_rejected(api):
    """PRD §3.6: "enrollment is refused once the non-cancelled enrollment count has
    reached the session's `capacity` (`ERR_SESSION_FULL`). An individual session,
    defaulting to a capacity of 1, therefore admits exactly one active enrollee,
    while a group session admits up to its stated capacity."

    Design: Difficulty/boundary_precision_check/group_capacity_at_limit_rejects
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY", room_capacity=8)
    c2 = fx.new_self_pay_client(api, full_name="c2")
    c3 = fx.new_self_pay_client(api, full_name="c3")
    session = fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"],
                                  ctx["goal_id"], modality="GROUP", capacity=2)
    fx.enroll(api, session["id"], ctx["client_id"], ctx["ther_id"])  # 1
    fx.enroll(api, session["id"], c2["id"], ctx["ther_id"])          # 2 == capacity
    resp = api.enroll_client(session["id"], {"client_id": c3["id"]}, ctx["ther_headers"])
    validate_error(resp, ApiErrorId.ERR_SESSION_FULL.value)


# ============================================ plan-active cross-entity gate (A)
def test_session_on_under_revision_plan_rejected(api):
    """PRD §3.5: "the referenced plan must be `ACTIVE`, or the request is rejected
    with `ERR_PLAN_NOT_ACTIVE`; a plan in `DRAFT`, `UNDER_REVISION`, `SUPERSEDED`, or
    `DISCHARGED` cannot host new sessions."

    Design: Difficulty/cross_entity_state_dependency/session_requires_plan_active
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    api.revise_plan(ctx["plan_id"], {"revision_note": "rework"}, TEST_USERS["clinical_headers"])
    resp = api.create_session(
        {"therapist_id": ctx["ther_id"], "room_id": ctx["room_id"], "plan_id": ctx["plan_id"],
         "goal_id": ctx["goal_id"], "modality": "INDIVIDUAL",
         "start_utc": "2026-06-01T09:00:00Z", "end_utc": "2026-06-01T10:00:00Z", "capacity": 1},
        ctx["ther_headers"])
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE.value)


def test_session_on_draft_plan_rejected(api):
    """PRD §3.5: "the referenced plan must be `ACTIVE`, or the request is rejected
    with `ERR_PLAN_NOT_ACTIVE`; a plan in `DRAFT`, `UNDER_REVISION`, `SUPERSEDED`, or
    `DISCHARGED` cannot host new sessions."

    Design: Difficulty/cross_entity_state_dependency/session_requires_plan_active
    """
    ther = fx.new_therapist(api)
    client = fx.new_self_pay_client(api)
    ref = fx.new_referral(api, client["id"])
    fx.assess(api, ref["id"], ther["id"])
    plan = fx.new_plan(api, client["id"], ref["id"], client["version"])  # DRAFT, not activated
    goal = fx.new_goal(api, plan["id"])
    room = fx.new_room(api)
    resp = api.create_session(
        {"therapist_id": ther["id"], "room_id": room["id"], "plan_id": plan["id"],
         "goal_id": goal["id"], "modality": "INDIVIDUAL",
         "start_utc": "2026-06-01T09:00:00Z", "end_utc": "2026-06-01T10:00:00Z", "capacity": 1},
        fx.make_therapist_headers(ther["id"]))
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE.value)


# ================================ referential precedence over fiscal (queue A)
def _build_referential_vs_fiscal(api):
    """Client A with an ACTIVE plan A; client B with a plan holding goal B; a
    contract whose budget (100) is smaller than its per-session rate (5000)."""
    ther = fx.new_therapist(api)
    ca = fx.new_insurance_client(api, full_name="Client A", insurance_visits_authorized=5)
    refa = fx.new_referral(api, ca["id"])
    fx.assess(api, refa["id"], ther["id"])
    plana = fx.new_plan(api, ca["id"], refa["id"], ca["version"])
    fx.activate_plan(api, plana["id"])
    cb = fx.new_insurance_client(api, full_name="Client B", insurance_visits_authorized=5)
    refb = fx.new_referral(api, cb["id"])
    fx.assess(api, refb["id"], ther["id"])
    planb = fx.new_plan(api, cb["id"], refb["id"], cb["version"])
    goalb = fx.new_goal(api, planb["id"], description="Goal B", target_sessions=4)
    room = fx.new_room(api)
    contract = fx.new_contract(api, party_name="Lincoln Elementary",
                               budget_cents=100, rate_cents_per_session=5000)
    return ther, plana, goalb, room, contract


def test_session_referential_error_beats_fiscal(api):
    """PRD §3.5: "the chosen `goal_id` must belong to the chosen `plan_id`, otherwise
    `ERR_GOAL_PLAN_MISMATCH`."
    PRD §2.7: "wherever two of them could both fire on the same request, the
    lower-numbered check wins."

    Design: Difficulty/priority_pair_validation_conflict/session_referential_beats_fiscal
    """
    ther, plana, goalb, room, contract = _build_referential_vs_fiscal(api)
    resp = api.create_session(
        {"therapist_id": ther["id"], "room_id": room["id"], "plan_id": plana["id"],
         "goal_id": goalb["id"], "modality": "INDIVIDUAL",
         "start_utc": "2026-06-01T09:00:00Z", "end_utc": "2026-06-01T10:00:00Z",
         "capacity": 1, "contract_id": contract["id"]},
        fx.make_therapist_headers(ther["id"]))
    err = validate_error(resp, ApiErrorId.ERR_GOAL_PLAN_MISMATCH.value)
    assert err["error_id"] != ApiErrorId.ERR_CONTRACT_BUDGET_EXCEEDED.value


def test_session_fiscal_error_surfaces_once_referential_fixed(api):
    """PRD §2.7: "wherever two of them could both fire on the same request, the
    lower-numbered check wins."
    PRD §3.5: "if that projected total would exceed `budget_cents` the request is
    rejected with `ERR_CONTRACT_BUDGET_EXCEEDED`, where the boundary is strict — a
    projection exactly equal to the budget is allowed."

    With the goal/plan mismatch removed, the same over-budget request now fails the
    lower-priority fiscal check instead — confirming the referential error had been
    pre-empting the fiscal one on the original request.

    Design: Difficulty/priority_pair_validation_conflict/session_referential_beats_fiscal
    """
    ther, plana, _goalb, room, contract = _build_referential_vs_fiscal(api)
    goala = fx.new_goal(api, plana["id"], description="Plan A goal", target_sessions=4)
    resp = api.create_session(
        {"therapist_id": ther["id"], "room_id": room["id"], "plan_id": plana["id"],
         "goal_id": goala["id"], "modality": "INDIVIDUAL",
         "start_utc": "2026-06-01T09:00:00Z", "end_utc": "2026-06-01T10:00:00Z",
         "capacity": 1, "contract_id": contract["id"]},
        fx.make_therapist_headers(ther["id"]))
    validate_error(resp, ApiErrorId.ERR_CONTRACT_BUDGET_EXCEEDED.value)


# ================================================== budget / material (queue B)
def test_contract_budget_boundary_and_exceeded(api):
    """PRD §3.5: "if that projected total would exceed `budget_cents` the request is
    rejected with `ERR_CONTRACT_BUDGET_EXCEEDED`, where the boundary is strict — a
    projection exactly equal to the budget is allowed."

    Design: Corner/calculations/contract_budget_boundary_and_exceeded
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    contract = fx.new_contract(api, party_name="Maple School",
                               budget_cents=5000, rate_cents_per_session=5000)
    first = fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"],
                                start_utc="2026-06-01T09:00:00Z", end_utc="2026-06-01T10:00:00Z",
                                contract_id=contract["id"])
    assert first["scheduling_status"] == "SCHEDULED"
    resp = api.create_session(
        {"therapist_id": ctx["ther_id"], "room_id": ctx["room_id"], "plan_id": ctx["plan_id"],
         "goal_id": ctx["goal_id"], "modality": "INDIVIDUAL",
         "start_utc": "2026-06-01T11:00:00Z", "end_utc": "2026-06-01T12:00:00Z",
         "capacity": 1, "contract_id": contract["id"]},
        ctx["ther_headers"])
    validate_error(resp, ApiErrorId.ERR_CONTRACT_BUDGET_EXCEEDED.value)


def test_insufficient_material_on_session_rejected(api):
    """PRD §3.5: "the requested `material_qty` must not exceed that item's
    `available_quantity`; if it would, the request is rejected with
    `ERR_INSUFFICIENT_MATERIAL`".

    Design: Corner/calculations/insufficient_material_on_session_rejected
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    mat = fx.new_material(api, name="Harp", on_hand_quantity=1, unit_charge_cents=400)
    resp = api.create_session(
        {"therapist_id": ctx["ther_id"], "room_id": ctx["room_id"], "plan_id": ctx["plan_id"],
         "goal_id": ctx["goal_id"], "modality": "INDIVIDUAL",
         "start_utc": "2026-06-01T09:00:00Z", "end_utc": "2026-06-01T10:00:00Z",
         "capacity": 1, "material_item_id": mat["id"], "material_qty": 2},
        ctx["ther_headers"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MATERIAL.value)


def test_duplicate_enrollment_rejected(api):
    """PRD §3.6: "a client who already holds a non-cancelled enrollment in the
    session cannot be enrolled again (`ERR_CLIENT_ALREADY_ENROLLED`)".

    Design: Corner/validations/duplicate_enrollment_rejected
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY", room_capacity=8)
    session = fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"],
                                  ctx["goal_id"], modality="GROUP", capacity=3)
    fx.enroll(api, session["id"], ctx["client_id"], ctx["ther_id"])
    resp = api.enroll_client(session["id"], {"client_id": ctx["client_id"]}, ctx["ther_headers"])
    validate_error(resp, ApiErrorId.ERR_CLIENT_ALREADY_ENROLLED.value)


def test_session_end_before_start_returns_422(api):
    """PRD §2.7: "Field validation — required fields present, types correct, enum
    members valid, numeric ranges satisfied, and `end_utc` strictly later than
    `start_utc` (`ERR_VALIDATION`, 422)."

    Design: Corner/validations/session_end_before_start_returns_422
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    resp = api.create_session(
        {"therapist_id": ctx["ther_id"], "room_id": ctx["room_id"], "plan_id": ctx["plan_id"],
         "goal_id": ctx["goal_id"], "modality": "INDIVIDUAL",
         "start_utc": "2026-06-01T10:00:00Z", "end_utc": "2026-06-01T09:00:00Z", "capacity": 1},
        ctx["ther_headers"])
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

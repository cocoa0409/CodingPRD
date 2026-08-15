"""Pre-lease delivery commitments: creation gating, the ACTIVE/AT_RISK
projection-driven cycle, uniqueness, and move-in resolution."""
from test_helpers import (
    TC,
    ApiErrorId,
    add_scope_item,
    complete,
    create_commitment,
    create_property,
    create_unit,
    finalize_turn,
    get_item,
    get_turn,
    get_unit,
    list_commitments,
    open_turn,
    pass_inspection,
    setup_in_progress_turn,
    setup_scoped_turn,
    validate_error,
    validate_success,
)


# --- creation gating (Difficulty: commitment_creation_requires_active_turn)

def test_commitment_while_turn_open_rejected(api):
    """PRD §3.8: "Pre-leasing requires an active turn on the unit whose
    projection has been established; without one the request is rejected with
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/commitment_creation_requires_active_turn
    """
    prop = create_property()
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])
    add_scope_item(turn["id"], "REPAIR", 5000)  # still OPEN: no projection yet

    resp = api.create_lease_commitment(
        {"unit_id": unit["id"], "applicant_name": "B Kay",
         "committed_delivery_date": "2026-08-10"}, TC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_commitment_on_projected_date_satisfies_inclusive_floor(api):
    """PRD §3.8: "a `committed_delivery_date` earlier than the active turn's
    current `projected_ready_date` is rejected with
    `ERR_DELIVERY_BEFORE_PROJECTED`. A valid commitment is born `ACTIVE`."
    (A date equal to the projection is not earlier, so it is accepted.)
    PRD §3.3: the projection advances the anchor by "two days for `REPAIR`".

    Design: Difficulty/cross_entity_state_dependency/commitment_creation_requires_active_turn
    """
    prop = create_property()
    unit = create_unit(prop["id"])
    turn = open_turn(unit["id"])
    add_scope_item(turn["id"], "REPAIR", 5000)
    finalize_turn(turn["id"])
    assert get_turn(turn["id"])["projected_ready_date"] == "2026-08-03"

    commitment = create_commitment(unit["id"], "2026-08-03", "B Kay")
    assert commitment["status"] == "ACTIVE"
    assert commitment["committed_delivery_date"] == "2026-08-03"


# --- risk cycle (Difficulty: lease_commitment_active_at_risk_cycle)

def _setup_commitment_then_add_six_items(api):
    """IN_PROGRESS turn (base REPAIR 100000, assignment accepted) with an
    ACTIVE commitment promising 2026-08-10; then six auto-approved 1000-cent
    items are added across the category ranks."""
    ctx = setup_in_progress_turn(100000)
    commitment = create_commitment(ctx["unit"]["id"], "2026-08-10", "A Lee")
    assert commitment["status"] == "ACTIVE"
    added = [
        add_scope_item(ctx["turn"]["id"], "REPAIR", 1000, "extra repair"),
        add_scope_item(ctx["turn"]["id"], "APPLIANCE", 1000, "fridge"),
        add_scope_item(ctx["turn"]["id"], "FIXTURE", 1000, "vanity"),
        add_scope_item(ctx["turn"]["id"], "PAINT", 1000, "touch-up"),
        add_scope_item(ctx["turn"]["id"], "CARPET", 1000, "recarpet"),
        add_scope_item(ctx["turn"]["id"], "OTHER", 1000, "misc"),
    ]
    return ctx, commitment, added


def test_projection_slipping_past_promise_flips_commitment_at_risk(api):
    """PRD §3.8: "Every recomputation of the active turn's
    `projected_ready_date` — whether driven by scope changes, assignment
    events, inspections, or a clock set — re-evaluates each open commitment on
    the unit: a projection now later than `committed_delivery_date` flips the
    commitment from `ACTIVE` to `AT_RISK`, and a later recomputation bringing
    the projection back to on or before the promised date flips it from
    `AT_RISK` back to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/lease_commitment_active_at_risk_cycle
    """
    ctx, commitment, _added = _setup_commitment_then_add_six_items(api)
    # anchor = max(clock 08-01, accepted window end 08-03); REPAIR+2,
    # APPLIANCE+1, FIXTURE+1, PAINT+2, CARPET +1 cure (PAINT not complete) +1,
    # OTHER+1 -> projected 2026-08-12 > promised 2026-08-10.
    assert get_turn(ctx["turn"]["id"])["projected_ready_date"] == "2026-08-12"
    current = [c for c in list_commitments(ctx["unit"]["id"])
               if c["id"] == commitment["id"]][0]
    assert current["status"] == "AT_RISK"


def test_voiding_discretionary_scope_flips_commitment_back_to_active(api):
    """PRD §3.8: "a later recomputation bringing the projection back to on or
    before the promised date flips it from `AT_RISK` back to `ACTIVE`."
    PRD §3.5: "Voiding a `PLANNED` item simply moves it to `VOIDED` and
    re-derives the turn's estimate and projection, with commitment risk
    re-evaluated."

    Design: Difficulty/non_linear_state_machine/lease_commitment_active_at_risk_cycle
    """
    ctx, commitment, added = _setup_commitment_then_add_six_items(api)
    assert [c for c in list_commitments(ctx["unit"]["id"])
            if c["id"] == commitment["id"]][0]["status"] == "AT_RISK"

    for item in added:
        validate_success(api.void_scope_item(item["id"], TC))

    current = [c for c in list_commitments(ctx["unit"]["id"])
               if c["id"] == commitment["id"]][0]
    assert current["status"] == "ACTIVE", (
        "projection falls back to 2026-08-03 <= promised 2026-08-10"
    )
    assert get_turn(ctx["turn"]["id"])["estimated_cost_cents"] == 100000
    for item in added:
        assert get_item(item["id"])["status"] == "VOIDED"


# --- delivery floor (Corner: delivery_before_projected_rejected)

def test_delivery_before_projected_rejected(api):
    """PRD §3.8: "the promise may not undercut the projection: a
    `committed_delivery_date` earlier than the active turn's current
    `projected_ready_date` is rejected with `ERR_DELIVERY_BEFORE_PROJECTED`."

    Design: Corner/validations/delivery_before_projected_rejected
    """
    ctx = setup_scoped_turn("REPAIR", 5000)
    assert get_turn(ctx["turn"]["id"])["projected_ready_date"] == "2026-08-03"

    resp = api.create_lease_commitment(
        {"unit_id": ctx["unit"]["id"], "applicant_name": "C Dee",
         "committed_delivery_date": "2026-08-02"}, TC)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_BEFORE_PROJECTED, 422)
    assert list_commitments(ctx["unit"]["id"]) == [], "nothing persisted"


# --- one open commitment per unit (Corner: second_active_commitment_rejected)

def test_second_open_commitment_rejected(api):
    """PRD §3.8: "The unit may hold at most one open commitment at a time — if
    another commitment in `ACTIVE` or `AT_RISK` already exists on the unit, the
    request is rejected with `ERR_COMMITMENT_EXISTS`."

    Design: Corner/validations/second_active_commitment_rejected
    """
    ctx = setup_scoped_turn("REPAIR", 5000)
    first = create_commitment(ctx["unit"]["id"], "2026-08-10", "A Lee")

    resp = api.create_lease_commitment(
        {"unit_id": ctx["unit"]["id"], "applicant_name": "B Kay",
         "committed_delivery_date": "2026-08-12"}, TC)
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_EXISTS, 422)
    current = [c for c in list_commitments(ctx["unit"]["id"])
               if c["id"] == first["id"]][0]
    assert current["status"] == "ACTIVE"


# --- move-in resolution (Corner: move_in_resolves_commitment_fulfilled / move_in_late_marks_commitment_breached)

def _setup_ready_turn_with_commitment(api, committed):
    """Turn taken to READY with a commitment created while IN_PROGRESS."""
    ctx = setup_in_progress_turn(5000)
    commitment = create_commitment(ctx["unit"]["id"], committed)
    complete(ctx["assignment"]["id"], ctx["vendor"]["id"], 4000)
    pass_inspection(ctx["turn"]["id"])
    assert get_turn(ctx["turn"]["id"])["status"] == "READY"
    assert get_unit(ctx["unit"]["id"])["status"] == "READY"
    return ctx, commitment


def test_move_in_on_time_fulfills_commitment(api):
    """PRD §3.8: "The unit moves from `READY` back to `OCCUPIED`, closing the
    unit lifecycle loop, and if the unit holds a commitment in `ACTIVE` or
    `AT_RISK`, that commitment resolves in the same step: a `move_in_date` on
    or before `committed_delivery_date` resolves it to `FULFILLED` — from
    either `ACTIVE` or `AT_RISK` — while a `move_in_date` after
    `committed_delivery_date` resolves it to `BREACHED`, again from either
    status."

    Design: Corner/state_machines/move_in_resolves_commitment_fulfilled
    """
    ctx, commitment = _setup_ready_turn_with_commitment(api, "2026-08-06")
    unit = validate_success(api.record_move_in(
        ctx["unit"]["id"], {"move_in_date": "2026-08-05"}, TC))
    assert unit["status"] == "OCCUPIED"
    current = [c for c in list_commitments(ctx["unit"]["id"])
               if c["id"] == commitment["id"]][0]
    assert current["status"] == "FULFILLED", "08-05 <= promised 08-06"


def test_move_in_after_promised_date_breaches_commitment(api):
    """PRD §3.8: "a `move_in_date` after `committed_delivery_date` resolves it
    to `BREACHED`, again from either status."

    Design: Corner/state_machines/move_in_late_marks_commitment_breached
    """
    ctx, commitment = _setup_ready_turn_with_commitment(api, "2026-08-04")
    unit = validate_success(api.record_move_in(
        ctx["unit"]["id"], {"move_in_date": "2026-08-09"}, TC))
    assert unit["status"] == "OCCUPIED"
    current = [c for c in list_commitments(ctx["unit"]["id"])
               if c["id"] == commitment["id"]][0]
    assert current["status"] == "BREACHED", "08-09 > promised 08-04"

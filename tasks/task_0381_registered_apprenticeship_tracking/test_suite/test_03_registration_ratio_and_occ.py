"""Registration: journeyman-ratio capacity, slot exhaustion, OCC stale-version,
slot conservation, cross-entity state dependencies, and the validation-priority
conflicts on register / attainment create.

Covers combinatorial_formula (ratio capacity), boundary_precision_check (slot
exhaustion), compensating_invariant (slot conservation), cross_entity_state_dependency,
priority_pair_validation_conflict, the OCC corners, and the consistency corner.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_sponsor,
    create_journeyworker,
    create_qualified_journeyworker,
    create_apprentice,
    create_draft_program,
    create_active_program,
    create_draft_agreement,
    create_active_agreement,
    register_agreement,
    current_program_version,
    setup_active_agreement,
    AGENCY,
)
from test_helpers.test_users import make_sponsor_headers


# ===========================================================================
# Difficulty: combinatorial_formula / journeyman_ratio_capacity_mode_a_nonlinear
# ===========================================================================
def test_ratio_capacity_combines_qualified_and_probationary_nonlinearly(api):
    """PRD §2.6: "The raw ratio capacity is the qualified count multiplied by the
    program's `journeyman_ratio`, plus the probationary count multiplied by the
    program's `journeyman_ratio` multiplied by a probationary weighting factor of
    one-half; this sum is then rounded down to a whole number."
    PRD §2.6: "The order is fixed: form that weighted sum and floor it to obtain
    the ratio capacity, then subtract the program's `active_agreement_count`,
    then take the larger of zero and that difference."

    With q=1, p=1, ratio=4, active=0: floor(1*4 + 1*4*0.5) = floor(6) = 6, not
    the naive q*ratio = 4.

    Design: Difficulty/combinatorial_formula/journeyman_ratio_capacity_mode_a_nonlinear
    """
    sponsor = create_sponsor()
    create_qualified_journeyworker(sponsor["id"])   # q = 1
    create_journeyworker(sponsor["id"])             # p = 1 (PROBATIONARY)
    program = create_active_program(sponsor["id"], journeyman_ratio=4)
    prog = get_success_data(api.get_program(program["id"], make_sponsor_headers(sponsor["id"])))
    assert prog["active_agreement_count"] == 0
    assert prog["available_apprentice_slots"] == 6, f"expected 6 slots, got {prog['available_apprentice_slots']}"


def test_ratio_capacity_qualified_only(api):
    """PRD §2.6: "first count the sponsor's journeyworkers in `QUALIFIED` status
    and, separately, the sponsor's journeyworkers in `PROBATIONARY` status. The
    raw ratio capacity is the qualified count multiplied by the program's
    `journeyman_ratio`, plus the probationary count multiplied by the program's
    `journeyman_ratio` multiplied by a probationary weighting factor of one-half;
    this sum is then rounded down to a whole number."

    With q=1, p=0, ratio=4: floor(1*4 + 0) = 4 slots.

    Design: Difficulty/combinatorial_formula/journeyman_ratio_capacity_mode_a_nonlinear
    """
    sponsor = create_sponsor()
    create_qualified_journeyworker(sponsor["id"])   # q = 1, no probationary
    program = create_active_program(sponsor["id"], journeyman_ratio=4)
    prog = get_success_data(api.get_program(program["id"], make_sponsor_headers(sponsor["id"])))
    assert prog["available_apprentice_slots"] == 4, f"expected 4 slots, got {prog['available_apprentice_slots']}"


# ===========================================================================
# Difficulty: boundary_precision_check / journeyman_ratio_slots_exhausted_to_zero_boundary
# ===========================================================================
def test_register_blocked_when_slots_exhausted_to_zero(api):
    """PRD §3.3: "and finally the program must have at least one free slot,
    meaning `available_apprentice_slots` is 1 or greater (otherwise
    `ERR_JOURNEYMAN_RATIO_EXCEEDED`)."

    Ratio 1 with one QUALIFIED journeyworker gives capacity 1; after AGR1 is
    registered available_apprentice_slots == 0, so registering AGR2 against the
    same journeyworker is rejected.

    Design: Difficulty/boundary_precision_check/journeyman_ratio_slots_exhausted_to_zero_boundary
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap1 = create_apprentice(sponsor["id"])
    ap2 = create_apprentice(sponsor["id"])
    program = create_active_program(sponsor["id"], journeyman_ratio=1)
    headers = make_sponsor_headers(sponsor["id"])

    agr1 = create_draft_agreement(sponsor["id"], program["id"], ap1["id"], jw["id"])
    register_agreement(sponsor["id"], agr1["id"], program["version"])
    prog = get_success_data(api.get_program(program["id"], headers))
    assert prog["available_apprentice_slots"] == 0, "slot must be exhausted to 0 after first register"

    agr2 = create_draft_agreement(sponsor["id"], program["id"], ap2["id"], jw["id"])
    res = api.register_agreement(
        agr2["id"], {"expected_program_version": prog["version"]}, headers
    )
    validate_error(res, ApiErrorId.ERR_JOURNEYMAN_RATIO_EXCEEDED.value)


def test_register_succeeds_when_a_slot_is_free(api):
    """PRD §3.3: "and finally the program must have at least one free slot,
    meaning `available_apprentice_slots` is 1 or greater (otherwise
    `ERR_JOURNEYMAN_RATIO_EXCEEDED`)."

    With ratio 1 and capacity 1, the FIRST register (one free slot) succeeds and
    moves the agreement to REGISTERED.

    Design: Difficulty/boundary_precision_check/journeyman_ratio_slots_exhausted_to_zero_boundary
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap = create_apprentice(sponsor["id"])
    program = create_active_program(sponsor["id"], journeyman_ratio=1)
    agr = create_draft_agreement(sponsor["id"], program["id"], ap["id"], jw["id"])
    res = api.register_agreement(
        agr["id"], {"expected_program_version": program["version"]},
        make_sponsor_headers(sponsor["id"]),
    )
    registered = validate_success(res)
    assert registered["status"] == "REGISTERED"


# ===========================================================================
# Difficulty: compensating_invariant / ratio_slot_conserved_register_then_cancel
# ===========================================================================
def test_slot_conserved_after_register_then_cancel(api):
    """PRD §3.3: "On success the agreement becomes `REGISTERED`, the program's
    `active_agreement_count` increases by one, the supervising journeyworker's
    `active_apprentice_count` increases by one, the program's
    `available_apprentice_slots` is recomputed from capacity, and the program's
    `version` increments by one."
    PRD §3.3: "On cancellation the `end_date` is set to the cancellation date,
    the program's `active_agreement_count` decreases by one, the supervising
    journeyworker's `active_apprentice_count` decreases by one, and the program's
    `available_apprentice_slots` is recomputed."

    Register (+1) then cancel (-1) returns both counters to 0 and slots to the
    full ratio-4 capacity.

    Design: Difficulty/compensating_invariant/ratio_slot_conserved_register_then_cancel
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap = create_apprentice(sponsor["id"])
    program = create_active_program(sponsor["id"], journeyman_ratio=4)
    headers = make_sponsor_headers(sponsor["id"])

    agr = create_draft_agreement(sponsor["id"], program["id"], ap["id"], jw["id"])
    register_agreement(sponsor["id"], agr["id"], program["version"])
    jw_after_reg = get_success_data(api.get_journeyworker(jw["id"], headers))
    assert jw_after_reg["active_apprentice_count"] == 1

    validate_success(api.cancel_agreement(agr["id"], headers))
    prog_after = get_success_data(api.get_program(program["id"], headers))
    jw_after = get_success_data(api.get_journeyworker(jw["id"], headers))
    assert prog_after["active_agreement_count"] == 0
    assert jw_after["active_apprentice_count"] == 0
    assert prog_after["available_apprentice_slots"] == 4


def test_journeyworker_count_increments_on_register(api):
    """PRD §3.3: "the supervising journeyworker's `active_apprentice_count`
    increases by one."

    Register bumps the supervising journeyworker's active_apprentice_count to 1.

    Design: Difficulty/compensating_invariant/ratio_slot_conserved_register_then_cancel
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap = create_apprentice(sponsor["id"])
    program = create_active_program(sponsor["id"], journeyman_ratio=4)
    headers = make_sponsor_headers(sponsor["id"])
    agr = create_draft_agreement(sponsor["id"], program["id"], ap["id"], jw["id"])
    register_agreement(sponsor["id"], agr["id"], program["version"])
    jw_after = get_success_data(api.get_journeyworker(jw["id"], headers))
    assert jw_after["active_apprentice_count"] == 1


# ===========================================================================
# Difficulty: cross_entity_state_dependency / register_requires_program_active
# ===========================================================================
def test_register_requires_program_active(api):
    """PRD §3.3: "The transition is guarded, in order, by these conditions: the
    agreement must be in `DRAFT` (otherwise `ERR_AGREEMENT_NOT_DRAFT`); the parent
    program must be `ACTIVE` (otherwise `ERR_PROGRAM_NOT_ACTIVE`); the supervising
    journeyworker must be `QUALIFIED` (otherwise `ERR_JOURNEYWORKER_NOT_QUALIFIED`)."

    Registering against a DRAFT (never-activated) program is rejected.

    Design: Difficulty/cross_entity_state_dependency/register_requires_program_active
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap = create_apprentice(sponsor["id"])
    program = create_draft_program(sponsor["id"])  # NOT activated
    agr = create_draft_agreement(sponsor["id"], program["id"], ap["id"], jw["id"])
    pv = current_program_version(sponsor["id"], program["id"])
    res = api.register_agreement(
        agr["id"], {"expected_program_version": pv}, make_sponsor_headers(sponsor["id"])
    )
    validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE.value)


def test_register_succeeds_once_program_is_active(api):
    """PRD §3.3: "the agreement must be in `DRAFT` (otherwise
    `ERR_AGREEMENT_NOT_DRAFT`); the parent program must be `ACTIVE` (otherwise
    `ERR_PROGRAM_NOT_ACTIVE`); the supervising journeyworker must be `QUALIFIED`
    (otherwise `ERR_JOURNEYWORKER_NOT_QUALIFIED`)."

    The same Agreement->Program dependency in the affirmative: once the program is
    ACTIVE, registering the DRAFT agreement succeeds (->REGISTERED). This pins the
    program-ACTIVE precondition as the gate distinguishing the two outcomes.

    Design: Difficulty/cross_entity_state_dependency/register_requires_program_active
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap = create_apprentice(sponsor["id"])
    program = create_active_program(sponsor["id"])  # ACTIVE this time
    agr = create_draft_agreement(sponsor["id"], program["id"], ap["id"], jw["id"])
    res = api.register_agreement(
        agr["id"], {"expected_program_version": program["version"]},
        make_sponsor_headers(sponsor["id"]),
    )
    registered = validate_success(res)
    assert registered["status"] == "REGISTERED"


# ===========================================================================
# Difficulty: cross_entity_state_dependency / attainment_approve_requires_agreement_active
# ===========================================================================
def test_attainment_approve_requires_agreement_active(api):
    """PRD §3.6: "Approval moves an attainment `SUBMITTED -> APPROVED`, requiring
    the attainment to be `SUBMITTED` (otherwise `ERR_ATTAINMENT_NOT_SUBMITTED`)
    and the parent agreement to be `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`)."

    With the parent agreement SUSPENDED, approving a SUBMITTED attainment is
    rejected with ERR_AGREEMENT_NOT_ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/attainment_approve_requires_agreement_active
    """
    from test_helpers import submit_attainment, COORD
    sc = setup_active_agreement(completion_type="HYBRID", milestones=[{}])
    headers = make_sponsor_headers(sc.sponsor_id)
    milestones = get_success_data(
        api.list_milestones(headers, params={"program_id": sc.program_id})
    )
    att = submit_attainment(sc.sponsor_id, sc.agreement_id, milestones[0]["id"])
    validate_success(api.suspend_agreement(sc.agreement_id, headers))
    res = api.approve_milestone_attainment(att["id"], COORD)
    validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)


def test_attainment_approve_succeeds_after_reinstate_to_active(api):
    """PRD §3.6: "Approval moves an attainment `SUBMITTED -> APPROVED`, requiring
    the attainment to be `SUBMITTED` (otherwise `ERR_ATTAINMENT_NOT_SUBMITTED`)
    and the parent agreement to be `ACTIVE` (otherwise `ERR_AGREEMENT_NOT_ACTIVE`)."
    PRD §3.3: "The sponsor reinstates a suspended agreement, moving `SUSPENDED ->
    ACTIVE` (the agreement must be `SUSPENDED`, otherwise `ERR_AGREEMENT_NOT_SUSPENDED`)."

    The same MilestoneAttainment->Agreement dependency in the affirmative: once the
    suspended agreement is reinstated to ACTIVE, the SUBMITTED attainment approves
    successfully. This pins agreement-ACTIVE as the gate.

    Design: Difficulty/cross_entity_state_dependency/attainment_approve_requires_agreement_active
    """
    from test_helpers import submit_attainment, COORD
    sc = setup_active_agreement(completion_type="HYBRID", milestones=[{}])
    headers = make_sponsor_headers(sc.sponsor_id)
    milestones = get_success_data(
        api.list_milestones(headers, params={"program_id": sc.program_id})
    )
    att = submit_attainment(sc.sponsor_id, sc.agreement_id, milestones[0]["id"])
    validate_success(api.suspend_agreement(sc.agreement_id, headers))
    validate_success(api.reinstate_agreement(sc.agreement_id, headers))
    approved = validate_success(api.approve_milestone_attainment(att["id"], COORD))
    assert approved["status"] == "APPROVED"


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / register_state_vs_ratio_constraint_state_wins
# ===========================================================================
def test_register_state_check_precedes_ratio_constraint(api):
    """PRD §2.10: "the target resource being in a legal state for the requested
    transition; and only then (7 and beyond) the operation-specific business
    rules described in §3, in the order those subsections set out."
    PRD §3.3: "the agreement must be in `DRAFT` (otherwise
    `ERR_AGREEMENT_NOT_DRAFT`); ... and finally the program must have at least one
    free slot, meaning `available_apprentice_slots` is 1 or greater (otherwise
    `ERR_JOURNEYMAN_RATIO_EXCEEDED`)."

    Ratio 1: AGR1 is registered (slot consumed). Re-registering AGR1 (already
    REGISTERED, so state violation) when slots are also exhausted returns the
    state error ERR_AGREEMENT_NOT_DRAFT, not ERR_JOURNEYMAN_RATIO_EXCEEDED.

    Design: Difficulty/priority_pair_validation_conflict/register_state_vs_ratio_constraint_state_wins
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap1 = create_apprentice(sponsor["id"])
    create_apprentice(sponsor["id"])
    program = create_active_program(sponsor["id"], journeyman_ratio=1)
    headers = make_sponsor_headers(sponsor["id"])

    agr1 = create_draft_agreement(sponsor["id"], program["id"], ap1["id"], jw["id"])
    after = register_agreement(sponsor["id"], agr1["id"], program["version"])
    # AGR1 is now REGISTERED and slots are exhausted to 0; re-register AGR1.
    pv = current_program_version(sponsor["id"], program["id"])
    res = api.register_agreement(agr1["id"], {"expected_program_version": pv}, headers)
    validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_DRAFT.value)


def test_register_cancelled_agreement_returns_state_error_over_ratio(api):
    """PRD §2.10: "(6) the target resource being in a legal state for the
    requested transition; and only then (7 and beyond) the operation-specific
    business rules described in §3, in the order those subsections set out."
    PRD §3.3: "the agreement must be in `DRAFT` (otherwise
    `ERR_AGREEMENT_NOT_DRAFT`); ... and finally the program must have at least one
    free slot, meaning `available_apprentice_slots` is 1 or greater (otherwise
    `ERR_JOURNEYMAN_RATIO_EXCEEDED`)."

    Ratio 1, slot consumed by AGR1. A second agreement that was registered then
    CANCELLED (now non-DRAFT) is re-registered while slots are exhausted: the
    earlier state check (ERR_AGREEMENT_NOT_DRAFT) pre-empts the slot rule.

    Design: Difficulty/priority_pair_validation_conflict/register_state_vs_ratio_constraint_state_wins
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap1 = create_apprentice(sponsor["id"])
    ap2 = create_apprentice(sponsor["id"])
    program = create_active_program(sponsor["id"], journeyman_ratio=1)
    headers = make_sponsor_headers(sponsor["id"])

    # AGR2 reaches a non-DRAFT terminal state (CANCELLED) and frees its slot...
    agr2 = create_draft_agreement(sponsor["id"], program["id"], ap2["id"], jw["id"])
    register_agreement(sponsor["id"], agr2["id"], current_program_version(sponsor["id"], program["id"]))
    validate_success(api.cancel_agreement(agr2["id"], headers))
    # ...then AGR1 consumes the only slot so capacity is exhausted again.
    agr1 = create_draft_agreement(sponsor["id"], program["id"], ap1["id"], jw["id"])
    register_agreement(sponsor["id"], agr1["id"], current_program_version(sponsor["id"], program["id"]))

    pv = current_program_version(sponsor["id"], program["id"])
    res = api.register_agreement(agr2["id"], {"expected_program_version": pv}, headers)
    validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_DRAFT.value)


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / attainment_referential_vs_temporal_referential_wins
# ===========================================================================
def test_attainment_referential_check_precedes_temporal(api):
    """PRD §3.6: "Two referential guards apply at submission: the referenced
    milestone must belong to the agreement's program - its `program_id` must match
    the agreement's `program_id`, otherwise `ERR_MILESTONE_PROGRAM_MISMATCH` - and
    the `attained_on` date must be on or after the agreement's `start_date`,
    otherwise `ERR_DATE_BEFORE_AGREEMENT_START`."
    PRD §2.10: "(4) existence of foreign-key resources named in the body ... and
    only then (7 and beyond) the operation-specific business rules described in
    §3, in the order those subsections set out."

    A milestone belonging to a DIFFERENT program AND an attained_on before
    start_date both fail; the referential mismatch (listed first in §3.6) wins.

    Design: Difficulty/priority_pair_validation_conflict/attainment_referential_vs_temporal_referential_wins
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap = create_apprentice(sponsor["id"])
    headers = make_sponsor_headers(sponsor["id"])

    prog_a = create_active_program(sponsor["id"])
    prog_b = create_active_program(sponsor["id"], occupation_code="49-9021.00",
                                   occupation_title="HVAC", milestones=[{"title": "B Milestone"}])
    milestones_b = get_success_data(
        api.list_milestones(headers, params={"program_id": prog_b["id"]})
    )
    mb_id = milestones_b[0]["id"]

    agr = create_draft_agreement(sponsor["id"], prog_a["id"], ap["id"], jw["id"], start_date="2026-03-01")
    register_agreement(sponsor["id"], agr["id"], prog_a["version"])
    validate_success(api.activate_agreement(agr["id"], headers))

    res = api.create_milestone_attainment(
        {"agreement_id": agr["id"], "milestone_id": mb_id, "attained_on": "2026-01-15"},
        headers,
    )
    validate_error(res, ApiErrorId.ERR_MILESTONE_PROGRAM_MISMATCH.value)


def test_attainment_wrong_program_milestone_with_valid_date_still_referential(api):
    """PRD §3.6: "the referenced milestone must belong to the agreement's program
    - its `program_id` must match the agreement's `program_id`, otherwise
    `ERR_MILESTONE_PROGRAM_MISMATCH`."

    The referential guard is independent of the temporal one: a milestone from a
    DIFFERENT program with an `attained_on` that is perfectly valid (on/after
    start_date) still yields ERR_MILESTONE_PROGRAM_MISMATCH. This pins the
    referential mismatch as the asserted outcome with the temporal check passing.

    Design: Difficulty/priority_pair_validation_conflict/attainment_referential_vs_temporal_referential_wins
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap = create_apprentice(sponsor["id"])
    headers = make_sponsor_headers(sponsor["id"])

    prog_a = create_active_program(sponsor["id"])
    prog_b = create_active_program(sponsor["id"], occupation_code="49-9021.00",
                                   occupation_title="HVAC", milestones=[{"title": "B Milestone"}])
    milestones_b = get_success_data(
        api.list_milestones(headers, params={"program_id": prog_b["id"]})
    )
    mb_id = milestones_b[0]["id"]

    agr = create_active_agreement(sponsor["id"], prog_a["id"], ap["id"], jw["id"], start_date="2026-01-01")
    # attained_on 2026-02-02 is on/after start_date -> temporal check passes.
    res = api.create_milestone_attainment(
        {"agreement_id": agr["id"], "milestone_id": mb_id, "attained_on": "2026-02-02"},
        headers,
    )
    validate_error(res, ApiErrorId.ERR_MILESTONE_PROGRAM_MISMATCH.value)


# ===========================================================================
# Corner: cross_cutting_complexity_layers / occ_stale_program_version_register_rejected
# ===========================================================================
def test_register_with_stale_program_version_rejected(api):
    """PRD §2.9: "The server compares `expected_program_version` to the program's
    current `version`. If another registration has advanced the program's
    `version` since the client read it - meaning the client's view of
    `available_apprentice_slots` is stale - the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    A first register bumps the program version; a second register carrying the
    pre-bump expected_program_version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_program_version_register_rejected
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap1 = create_apprentice(sponsor["id"])
    ap2 = create_apprentice(sponsor["id"])
    program = create_active_program(sponsor["id"], journeyman_ratio=4)
    headers = make_sponsor_headers(sponsor["id"])
    pv0 = program["version"]

    agr1 = create_draft_agreement(sponsor["id"], program["id"], ap1["id"], jw["id"])
    agr2 = create_draft_agreement(sponsor["id"], program["id"], ap2["id"], jw["id"])
    register_agreement(sponsor["id"], agr1["id"], pv0)  # bumps version

    res = api.register_agreement(agr2["id"], {"expected_program_version": pv0}, headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)


# ===========================================================================
# Corner: cross_cutting_complexity_layers / occ_correct_program_version_register_succeeds
# ===========================================================================
def test_register_with_fresh_program_version_succeeds(api):
    """PRD §2.9: "the registration action requires the client to supply
    `expected_program_version` as a non-optional field carrying the `version` of
    the parent `ApprenticeshipProgram` that the client last observed."
    PRD §3.3: "On success the agreement becomes `REGISTERED`, the program's
    `active_agreement_count` increases by one."

    After the first register, re-reading the program yields the bumped version;
    supplying that fresh version on the second register succeeds and
    active_agreement_count becomes 2.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_program_version_register_succeeds
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap1 = create_apprentice(sponsor["id"])
    ap2 = create_apprentice(sponsor["id"])
    program = create_active_program(sponsor["id"], journeyman_ratio=4)
    headers = make_sponsor_headers(sponsor["id"])

    agr1 = create_draft_agreement(sponsor["id"], program["id"], ap1["id"], jw["id"])
    agr2 = create_draft_agreement(sponsor["id"], program["id"], ap2["id"], jw["id"])
    register_agreement(sponsor["id"], agr1["id"], program["version"])

    fresh = current_program_version(sponsor["id"], program["id"])
    res = api.register_agreement(agr2["id"], {"expected_program_version": fresh}, headers)
    registered = validate_success(res)
    assert registered["status"] == "REGISTERED"
    prog = get_success_data(api.get_program(program["id"], headers))
    assert prog["active_agreement_count"] == 2


# ===========================================================================
# Corner: consistency_model / immediate_consistency_register_visible_in_response
# ===========================================================================
def test_register_side_effects_visible_immediately(api):
    """PRD §3.3: "On success the agreement becomes `REGISTERED`, the program's
    `active_agreement_count` increases by one ... the program's
    `available_apprentice_slots` is recomputed from capacity."
    PRD §2.6: "Capacity is recomputed whenever a program is activated, whenever an
    agreement is registered, completed, or cancelled, whenever a journeyworker is
    qualified or deactivated, and on every read of a program (so a `GET` of a
    program always reflects current capacity)."

    The register response shows status REGISTERED; an immediate GET of the program
    (ratio 4) shows active_agreement_count == 1 and available_apprentice_slots == 3.

    Design: Corner/consistency_model/immediate_consistency_register_visible_in_response
    """
    sponsor = create_sponsor()
    jw = create_qualified_journeyworker(sponsor["id"])
    ap = create_apprentice(sponsor["id"])
    program = create_active_program(sponsor["id"], journeyman_ratio=4)
    headers = make_sponsor_headers(sponsor["id"])
    agr = create_draft_agreement(sponsor["id"], program["id"], ap["id"], jw["id"])

    registered = validate_success(
        api.register_agreement(agr["id"], {"expected_program_version": program["version"]}, headers)
    )
    assert registered["status"] == "REGISTERED"
    prog = get_success_data(api.get_program(program["id"], headers))
    assert prog["active_agreement_count"] == 1
    assert prog["available_apprentice_slots"] == 3

"""Plot allocation, assignment state machine, pre-need gating, and OCC.

Covers difficulty non_linear_state_machine (assign/release revert),
cross_entity_state_dependency (PMC-gated assign), plus corner allocation,
error, and cross_cutting_complexity (OCC) instances.
"""
from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_cemetery_with_gravesite,
    create_cemetery,
    create_in_ground_section,
    create_gravesite,
    open_and_approve_case,
    open_case,
    assign_plot_auto,
    setup_preneed_eligible_case,
    setup_preneed_approved_case,
    create_pmc,
    approve_pmc,
    set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["eligibility_officer_headers"]
CLERK = TEST_USERS["scheduling_clerk_headers"]


# ===========================================================================
# non_linear_state_machine — assign/release revert loop
# ===========================================================================
def test_assign_then_release_revert_loop(api):
    """PRD §3.4: "A clerk may undo an assignment by releasing the plot, reverting
    the case from ASSIGNED back to ELIGIBLE."
    PRD §3.4: "Releasing moves the reserved unit from RESERVED back to AVAILABLE,
    clears its reserved_by_case_id, clears the case's assigned_unit_type,
    assigned_gravesite_id, and assigned_niche_id, and recomputes the parent
    section's inventory."

    Design: Difficulty/non_linear_state_machine/burial_case_assign_release_revert_loop
    """
    cem, sec, grv = setup_cemetery_with_gravesite(depth_capacity=1, honors_squad_capacity=1)
    case = open_and_approve_case(cem["id"])
    assign_plot_auto(cem["id"], case["id"])
    released = validate_success(api.release_plot(cem["id"], case["id"], CLERK))
    assert released["status"] == "ELIGIBLE"
    assert released["assigned_gravesite_id"] is None
    grv_read = validate_success(api.get_gravesite(cem["id"], sec["id"], grv["id"], CLERK))
    assert grv_read["status"] == "AVAILABLE"


def test_reassign_after_release_returns_to_assigned(api):
    """PRD §3.4: "Once a case is ELIGIBLE, a SchedulingClerk assigns it a burial
    unit, advancing it from ELIGIBLE to ASSIGNED."

    Design: Difficulty/non_linear_state_machine/burial_case_assign_release_revert_loop
    """
    cem, sec, grv = setup_cemetery_with_gravesite(depth_capacity=1, honors_squad_capacity=1)
    case = open_and_approve_case(cem["id"])
    assign_plot_auto(cem["id"], case["id"])
    validate_success(api.release_plot(cem["id"], case["id"], CLERK))
    reassigned = validate_success(api.assign_plot(cem["id"], case["id"], CLERK, payload={}))
    assert reassigned["status"] == "ASSIGNED"
    assert reassigned["assigned_gravesite_id"] == grv["id"]


# ===========================================================================
# cross_entity_state_dependency — assign-plot requires APPROVED PMC
# ===========================================================================
def test_assign_preneed_case_without_approved_pmc_rejected(api):
    """PRD §3.4: "For a PRE_NEED case, this is permitted only when a pre-need
    determination for the case exists in APPROVED status; if none does, the
    assignment is rejected with ERR_PMC_REQUIRED"

    Design: Difficulty/cross_entity_state_dependency/assign_plot_requires_approved_pmc_on_preneed_case
    """
    cem, sec, grv, case, pmc = setup_preneed_eligible_case(honors_squad_capacity=1)
    # PMC is still PENDING (not approved)
    resp = api.assign_plot(cem["id"], case["id"], CLERK, payload={})
    validate_error(resp, ApiErrorId.ERR_PMC_REQUIRED, expected_status=409)
    case_read = validate_success(api.get_burial_case(cem["id"], case["id"], CLERK))
    assert case_read["status"] == "ELIGIBLE"


def test_assign_preneed_case_with_approved_pmc_succeeds(api):
    """PRD §3.4: "For a PRE_NEED case, this is permitted only when a pre-need
    determination for the case exists in APPROVED status"
    PRD §3.4: "For a PRE_NEED case, the successful assignment also drives the linked
    pre-need determination from APPROVED to RESERVED."

    Design: Difficulty/cross_entity_state_dependency/assign_plot_requires_approved_pmc_on_preneed_case
    """
    set_clock("2026-05-01T00:00:00Z")
    cem, sec, grv, case, pmc = setup_preneed_approved_case(honors_squad_capacity=1)
    assigned = validate_success(api.assign_plot(cem["id"], case["id"], CLERK, payload={}))
    assert assigned["status"] == "ASSIGNED"


# ===========================================================================
# Corner: state_machines — invalid assign from SUBMITTED
# ===========================================================================
def test_assign_plot_from_submitted_invalid_state(api):
    """PRD §2.6: "the target resource's state is checked against the requested
    transition, yielding ERR_INVALID_STATE when the transition is not defined from
    the current state."
    PRD §3.4: "Once a case is ELIGIBLE, a SchedulingClerk assigns it a burial unit"

    Design: Corner/state_machines/assign_plot_from_submitted_case_invalid_state
    """
    cem, sec, grv = setup_cemetery_with_gravesite(depth_capacity=1, honors_squad_capacity=1)
    case = open_case(cem["id"])  # SUBMITTED, no eligibility run
    resp = api.assign_plot(cem["id"], case["id"], CLERK, payload={})
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    grv_read = validate_success(api.get_gravesite(cem["id"], sec["id"], grv["id"], ADMIN))
    assert grv_read["status"] == "AVAILABLE"


# ===========================================================================
# Corner: calculations — plot allocation deterministic order
# ===========================================================================
def test_auto_allocation_deterministic_grid_order(api):
    """PRD §3.4: "then by the section's code in ascending order; then by the unit's
    grid_ref or niche_ref in ascending lexicographic order; and finally, as the last
    deterministic tie-break, by created_at ascending — never by id. The first
    candidate in this ranking is selected."

    Design: Corner/calculations/plot_allocation_auto_select_deterministic_order
    """
    cem = create_cemetery(name="Alloc National", honors_squad_capacity=1)
    sec = create_in_ground_section(cem["id"], code="A")
    grv1 = create_gravesite(cem["id"], sec["id"], grid_ref="R1C1", gravesite_class="STANDARD", depth_capacity=1)
    grv2 = create_gravesite(cem["id"], sec["id"], grid_ref="R1C2", gravesite_class="STANDARD", depth_capacity=1)
    case = open_and_approve_case(cem["id"])
    assigned = validate_success(api.assign_plot(cem["id"], case["id"], CLERK, payload={}))
    assert assigned["assigned_gravesite_id"] == grv1["id"]
    g1 = validate_success(api.get_gravesite(cem["id"], sec["id"], grv1["id"], CLERK))
    g2 = validate_success(api.get_gravesite(cem["id"], sec["id"], grv2["id"], CLERK))
    assert g1["status"] == "RESERVED"
    assert g2["status"] == "AVAILABLE"


# ===========================================================================
# Corner: validations — empty candidate pool
# ===========================================================================
def test_auto_assign_empty_pool_no_available_unit(api):
    """PRD §3.4: "If the candidate set is empty, the assignment is rejected with
    ERR_NO_AVAILABLE_UNIT"

    Design: Corner/validations/assign_auto_select_empty_pool_no_available_unit
    """
    cem = create_cemetery(name="Empty National", honors_squad_capacity=1)
    sec = create_in_ground_section(cem["id"], code="A")
    create_gravesite(cem["id"], sec["id"], grid_ref="R1C1", gravesite_class="STANDARD", depth_capacity=1)
    case = open_and_approve_case(cem["id"], requested_class="OVERSIZE")
    resp = api.assign_plot(cem["id"], case["id"], CLERK, payload={})
    validate_error(resp, ApiErrorId.ERR_NO_AVAILABLE_UNIT, expected_status=409)


# ===========================================================================
# Corner: validations — body FK not found
# ===========================================================================
def test_dependent_case_bad_reserving_case_id_reference_not_found(api):
    """PRD §2.5: "When a create or action endpoint carries a body-level reference —
    such as burial_case_id, section_id, interment_schedule_id, reserving_case_id, or
    an explicit unit_id — and that reference does not resolve to an existing record,
    the request is rejected with ERR_REFERENCE_NOT_FOUND."

    Design: Corner/validations/body_fk_reserving_case_not_found
    """
    cem = create_cemetery(name="BadFK National", honors_squad_capacity=1)
    resp = api.create_burial_case(cem["id"], {
        "cemetery_id": cem["id"], "case_type": "AT_NEED", "applicant_role": "DEPENDENT",
        "requested_class": "STANDARD",
        "reserving_case_id": "00000000-0000-0000-0000-000000000000", "service_days": 0,
    }, OFFICER)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND, expected_status=404)


# ===========================================================================
# Corner: errors — PMC expired blocks assign, explicit unit outside cemetery
# ===========================================================================
def test_expired_pmc_blocks_assign_plot(api):
    """PRD §3.4: "if the approved certificate's reservation window has already
    elapsed — that is, the current time is at or past its expiry — it is rejected
    with ERR_PMC_EXPIRED"

    Design: Corner/errors/pmc_expired_blocks_assign_plot
    """
    set_clock("2026-05-01T00:00:00Z")
    cem, sec, grv, case, pmc = setup_preneed_approved_case(honors_squad_capacity=1)
    set_clock("2027-06-01T00:00:00Z")  # past expires_on (approval + 365 days)
    resp = api.assign_plot(cem["id"], case["id"], CLERK, payload={})
    validate_error(resp, ApiErrorId.ERR_PMC_EXPIRED, expected_status=409)
    grv_read = validate_success(api.get_gravesite(cem["id"], sec["id"], grv["id"], ADMIN))
    assert grv_read["status"] == "AVAILABLE"


def test_assign_explicit_unit_outside_cemetery_kind_mismatch(api):
    """PRD §3.4: "it must belong to the case's own cemetery — a unit outside it is
    rejected with ERR_UNIT_KIND_MISMATCH"

    Design: Corner/errors/assign_explicit_unit_outside_cemetery_kind_mismatch
    """
    cem1 = create_cemetery(name="CemOne", honors_squad_capacity=1)
    sec1 = create_in_ground_section(cem1["id"], code="A")
    g1 = create_gravesite(cem1["id"], sec1["id"], grid_ref="R1C1", gravesite_class="STANDARD", depth_capacity=1)
    cem2 = create_cemetery(name="CemTwo", honors_squad_capacity=1)
    case2 = open_and_approve_case(cem2["id"])
    resp = api.assign_plot(cem2["id"], case2["id"], CLERK, payload={
        "unit_id": g1["id"], "unit_type": "GRAVESITE", "expected_gravesite_version": g1["version"],
    })
    validate_error(resp, ApiErrorId.ERR_UNIT_KIND_MISMATCH, expected_status=422)


# ===========================================================================
# cross_cutting_complexity — OCC stale versions
# ===========================================================================
def test_occ_stale_gravesite_version_on_explicit_assign(api):
    """PRD §2.9: "If the gravesite's current version has advanced since — for
    instance because another case already reserved it, which moves the unit from
    AVAILABLE to RESERVED and increments its version — the assignment is rejected as
    stale with ERR_STALE_GRAVESITE_VERSION at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_gravesite_version_on_explicit_assign
    """
    cem = create_cemetery(name="Occ National", honors_squad_capacity=1)
    sec = create_in_ground_section(cem["id"], code="A")
    grv = create_gravesite(cem["id"], sec["id"], grid_ref="R1C1", gravesite_class="STANDARD", depth_capacity=2)
    g_v0 = grv["version"]
    case_a = open_and_approve_case(cem["id"])
    case_b = open_and_approve_case(cem["id"])
    # Case A reserves the gravesite -> its version advances.
    validate_success(api.assign_plot(cem["id"], case_a["id"], CLERK, payload={
        "unit_id": grv["id"], "unit_type": "GRAVESITE", "expected_gravesite_version": g_v0,
    }))
    # Case B carries the stale pre-assign version.
    resp = api.assign_plot(cem["id"], case_b["id"], CLERK, payload={
        "unit_id": grv["id"], "unit_type": "GRAVESITE", "expected_gravesite_version": g_v0,
    })
    validate_error(resp, ApiErrorId.ERR_STALE_GRAVESITE_VERSION, expected_status=412)


def test_occ_stale_pmc_version_on_approve(api):
    """PRD §2.9: "If the record's current version has advanced since — for instance
    because a denial has already been recorded against the pending certificate — the
    approval is rejected as stale with ERR_STALE_PMC_VERSION at HTTP 412, rather than
    overwriting the newer decision."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_pmc_version_on_approve
    """
    cem = create_cemetery(name="OccPmc National", honors_squad_capacity=1)
    case = open_and_approve_case(cem["id"], case_type="PRE_NEED")
    pmc = create_pmc(cem["id"], case["id"])
    pmc_v0 = pmc["version"]
    validate_success(api.deny_pmc(cem["id"], pmc["id"], OFFICER))  # version advances
    resp = api.approve_pmc(cem["id"], pmc["id"], pmc_v0, OFFICER)
    validate_error(resp, ApiErrorId.ERR_STALE_PMC_VERSION, expected_status=412)


# ===========================================================================
# Corner: state_machines — PMC deny from approved invalid state
# ===========================================================================
def test_preneed_deny_from_approved_invalid_state(api):
    """PRD §3.5: "The officer then either approves or denies the pending
    certificate; both are permitted only from PENDING."

    Design: Corner/state_machines/preneed_deny_from_approved_invalid_state
    """
    cem = create_cemetery(name="DenyBlock National", honors_squad_capacity=1)
    case = open_and_approve_case(cem["id"], case_type="PRE_NEED")
    pmc = create_pmc(cem["id"], case["id"])
    approve_pmc(cem["id"], pmc["id"], pmc["version"])
    resp = api.deny_pmc(cem["id"], pmc["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

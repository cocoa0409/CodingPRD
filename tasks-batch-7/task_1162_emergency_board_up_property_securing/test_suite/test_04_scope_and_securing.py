"""Scope measurement formulas, material invariants, OCC on the job version, and
the complete-securing gate family."""
from test_helpers import (
    accept_offer,
    add_scope_item,
    board_scope_payload,
    dispatch_job,
    fence_scope_payload,
    get_job,
    install_scope_item,
    intake_job,
    make_subcontractor_headers,
    setup_dispatched_job,
    setup_network,
    setup_on_site_job,
    validate_error,
    validate_success,
    void_scope_item,
)


def test_board_material_quantity_branching_high_wind_door(api, dispatcher_headers):
    """PRD §3.5: "For `BOARD`, the total opening area is `opening_count` times
    `width_in` times `height_in` square inches, divided by 144 to obtain square
    feet; that area is divided by 32 — the coverage of one 4x8 plywood sheet —
    and rounded up to a whole number of base sheets; one additional framing sheet
    is added for each of the `door_count` door openings; if the property's
    `wind_zone` is `HIGH`, the total is doubled; and whenever at least one opening
    exists, the result is never allowed to fall below one sheet."

    Design: Difficulty/combinatorial_formula/board_material_quantity_branching
    """
    net = setup_network(wind_zone="HIGH", num_subcontractors=1, covered_count=1)
    job = intake_job(net["property"]["id"], incident_type="STORM", priority="P3")
    item = add_scope_item(job["id"], kind="BOARD", opening_count=3,
                          width_in=72, height_in=36, door_count=1)
    # ceil(3*72*36/144 / 32) = ceil(54/32) = 2 base sheets; +1 door framing = 3;
    # HIGH wind zone doubles to 6. Omitting any branch yields a different integer.
    assert item["planned_qty"] == 6
    assert item["unit"] == "SHEETS"
    assert item["status"] == "PLANNED"


def test_board_material_quantity_low_wind_baseline(api, dispatcher_headers):
    """PRD §3.5: "For `BOARD`, the total opening area is `opening_count` times
    `width_in` times `height_in` square inches, divided by 144 to obtain square
    feet; that area is divided by 32 — the coverage of one 4x8 plywood sheet —
    and rounded up to a whole number of base sheets"
    PRD §3.1: "a `HIGH` wind zone doubles the plywood requirement of every
    boarded opening, as detailed in §3.5."

    Design: Difficulty/combinatorial_formula/board_material_quantity_branching
    """
    # Same dimensions with LOW wind and no doors: ceil(54/32) = 2 sheets — the
    # branch-free baseline that falsifies spurious doubling/framing.
    net = setup_network(wind_zone="LOW", num_subcontractors=1, covered_count=1)
    job = intake_job(net["property"]["id"], incident_type="STORM", priority="P3")
    item = add_scope_item(job["id"], kind="BOARD", opening_count=3,
                          width_in=72, height_in=36, door_count=0)
    assert item["planned_qty"] == 2
    assert item["unit"] == "SHEETS"


def test_tarp_overlap_factor_ceil(api, dispatcher_headers):
    """PRD §3.5: "For `TARP`, the damaged roof area `length_ft` times `width_ft`
    is multiplied by 1.25 to allow for overlap and anchoring, then rounded up to
    a whole square foot; tarp items are expressed in `SQFT`."

    Design: Corner/calculations/tarp_overlap_factor_ceil
    """
    net = setup_network(wind_zone="LOW", num_subcontractors=1, covered_count=1)
    job = intake_job(net["property"]["id"], incident_type="STORM", priority="P3")
    item = add_scope_item(job["id"], kind="TARP", length_ft=10, width_ft=15)
    assert item["planned_qty"] == 188, "ceil(150 x 1.25) = 188, not 187 (truncated) or 150"
    assert item["unit"] == "SQFT"


def test_scope_item_door_count_default_zero(api, dispatcher_headers):
    """PRD §3.5: "Each item declares a `kind` — `BOARD`, `TARP`, or `FENCE` — and
    carries the measurement fields appropriate to that kind, each of which must
    be present and positive: `opening_count`, `width_in`, and `height_in` for
    board-up work, with `door_count` optional and defaulting to 0"

    Design: Corner/entities/scope_item_door_count_default_zero
    """
    net = setup_network(wind_zone="LOW", num_subcontractors=1, covered_count=1)
    job = intake_job(net["property"]["id"], incident_type="STORM", priority="P3")

    current = get_job(job["id"])
    payload = {
        "kind": "BOARD", "opening_count": 4, "width_in": 48, "height_in": 36,
        "expected_job_version": current["version"],
    }  # door_count deliberately omitted
    item = validate_success(api.create_scope_item(job["id"], payload,
                                                  dispatcher_headers), 201)
    assert item["door_count"] == 0, "default 0 must be applied"
    assert item["planned_qty"] == 2, "ceil(48/32) = 2 with no door framing sheet"


def test_invalid_measurement_rejected(api, dispatcher_headers):
    """PRD §3.5: "Missing or non-positive measurements for the item's kind are
    rejected with `ERR_INVALID_MEASUREMENT` (HTTP 422)."

    Design: Corner/endpoints/invalid_measurement_rejected
    """
    net = setup_network(wind_zone="LOW", num_subcontractors=1, covered_count=1)
    job = intake_job(net["property"]["id"], incident_type="FIRE", priority="P3")

    current = get_job(job["id"])
    payload = board_scope_payload(opening_count=1, width_in=0, height_in=36)
    payload["expected_job_version"] = current["version"]
    res = api.create_scope_item(job["id"], payload, dispatcher_headers)
    validate_error(res, "ERR_INVALID_MEASUREMENT")
    assert get_job(job["id"])["total_planned_sheets"] == 0


def test_material_total_add_void_restores(api, dispatcher_headers):
    """PRD §3.5: "Every scope addition advances the parent job's `version` by one,
    and the job's `total_planned_sheets` — the running sum of `planned_qty` over
    its `BOARD` items in `PLANNED` or `INSTALLED` status — is kept current as
    items are added, installed, or voided."
    PRD §3.5: "voiding moves the item `PLANNED` → `VOIDED`, recomputes
    `total_planned_sheets` and the package's photo requirement when one exists,
    and advances the job's `version`."

    Design: Difficulty/compensating_invariant/material_total_add_void_restores
    """
    net = setup_network(wind_zone="LOW", num_subcontractors=1, covered_count=1)
    job = intake_job(net["property"]["id"], incident_type="STORM", priority="P3")
    assert job["total_planned_sheets"] == 0

    # 4 openings of 48x36in = 48 sqft -> ceil(48/32) = 2 sheets.
    item = add_scope_item(job["id"], kind="BOARD", opening_count=4,
                          width_in=48, height_in=36, door_count=0)
    assert get_job(job["id"])["total_planned_sheets"] == 2

    voided = void_scope_item(item["id"])
    assert voided["status"] == "VOIDED"
    assert get_job(job["id"])["total_planned_sheets"] == 0, (
        "the compensating void must restore the aggregate exactly")


def test_material_total_counts_installed_and_ignores_non_board(api, dispatcher_headers):
    """PRD §3.5: "the job's `total_planned_sheets` — the running sum of
    `planned_qty` over its `BOARD` items in `PLANNED` or `INSTALLED` status — is
    kept current as items are added, installed, or voided."

    Design: Difficulty/compensating_invariant/material_total_add_void_restores
    """
    ctx = setup_on_site_job(priority="P3")
    job_id = ctx["job"]["id"]
    assignee = ctx["assignee"]["id"]

    board = add_scope_item(job_id, kind="BOARD", opening_count=4,
                           width_in=48, height_in=36, door_count=0)
    assert get_job(job_id)["total_planned_sheets"] == 2

    # Installing the BOARD item keeps it in the aggregate (INSTALLED counts).
    install_scope_item(board["id"], assignee, opening_count=4,
                       width_in=48, height_in=36, door_count=0)
    assert get_job(job_id)["total_planned_sheets"] == 2

    # Non-BOARD kinds never contribute to the sheet aggregate.
    add_scope_item(job_id, kind="TARP", length_ft=10, width_ft=15)
    add_scope_item(job_id, kind="FENCE", linear_ft=40)
    assert get_job(job_id)["total_planned_sheets"] == 2

    # Voiding a second PLANNED BOARD item removes only its own contribution.
    board2 = add_scope_item(job_id, kind="BOARD", opening_count=1,
                            width_in=48, height_in=36, door_count=0)
    assert get_job(job_id)["total_planned_sheets"] == 3
    void_scope_item(board2["id"])
    assert get_job(job_id)["total_planned_sheets"] == 2


def test_immediate_consistency_computed_in_create_response(api, dispatcher_headers):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data field."
    PRD §3.5: "From these measurements the platform computes `planned_qty` and
    the `unit` it is expressed in."

    Design: Corner/consistency_model/immediate_consistency_computed_in_create_response
    """
    net = setup_network(wind_zone="LOW", num_subcontractors=1, covered_count=1)
    job = intake_job(net["property"]["id"], incident_type="FIRE", priority="P3")
    current = get_job(job["id"])
    payload = board_scope_payload(opening_count=4, width_in=48, height_in=36)
    payload["expected_job_version"] = current["version"]
    res = api.create_scope_item(job["id"], payload, dispatcher_headers)
    item = validate_success(res, 201)
    assert item["planned_qty"] == 2, "computed quantity visible in the create response"
    assert item["unit"] == "SHEETS"


def test_occ_stale_version_scope_add_rejected(api, dispatcher_headers):
    """PRD §2.9: "The request must carry `expected_job_version`, holding the
    `version` of the job as the client last observed it. Because every scope
    addition and every scope void legitimately advances the job's `version`, a
    client whose view predates another writer's scope change is working from a
    stale picture of the job's scope; if the supplied value does not equal the
    job's current `version`, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_scope_add_rejected
    """
    net = setup_network(wind_zone="LOW", num_subcontractors=1, covered_count=1)
    job = intake_job(net["property"]["id"], incident_type="FIRE", priority="P3")
    stale_version = job["version"]

    first = add_scope_item(job["id"], kind="BOARD", opening_count=1,
                           width_in=48, height_in=36, door_count=0)
    assert first["status"] == "PLANNED"

    payload = fence_scope_payload(linear_ft=20)
    payload["expected_job_version"] = stale_version
    res = api.create_scope_item(job["id"], payload, dispatcher_headers)
    validate_error(res, "ERR_STALE_VERSION")
    assert get_job(job["id"])["total_planned_sheets"] == 1, (
        "only the first add may persist")


def test_version_increments_on_each_mutation(api, dispatcher_headers):
    """PRD §2.4: "`version` — an integer that starts at 1 and increments by
    exactly one on every mutation, whether the mutation was client-requested or
    the by-product of an automatic cascade."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
    """
    ctx = setup_network(wind_zone="LOW", num_subcontractors=1, covered_count=1)
    job = intake_job(ctx["property"]["id"], incident_type="FIRE", priority="P3")
    assert job["version"] == 1

    item = add_scope_item(job["id"], kind="BOARD", opening_count=1,
                          width_in=48, height_in=36, door_count=0)
    assert get_job(job["id"])["version"] == 2, "scope add bumps the job version"

    void_scope_item(item["id"])
    assert get_job(job["id"])["version"] == 3, "void side effect bumps the job version"

    dispatch_job(job["id"])
    assert get_job(job["id"])["version"] == 4, "dispatch bumps the job version"


def test_empty_scope_set_rejection(api, dispatcher_headers):
    """PRD §3.5: "at least one scope item not in `VOIDED` status must exist
    (`ERR_SCOPE_EMPTY`)"

    Design: Difficulty/boundary_precision_check/empty_scope_set_rejection
    """
    ctx = setup_on_site_job(priority="P3", with_assessment=True)
    assignee = ctx["assignee"]
    assert get_job(ctx["job"]["id"])["safety_cleared"] is True

    res = api.complete_securing(ctx["job"]["id"], make_subcontractor_headers(assignee["id"]))
    validate_error(res, "ERR_SCOPE_EMPTY")
    job = get_job(ctx["job"]["id"])
    assert job["work_status"] == "ON_SITE", "no transition may fire on the empty scope"


def test_all_scope_voided_is_empty_rejection(api, dispatcher_headers):
    """PRD §3.5: "at least one scope item not in `VOIDED` status must exist
    (`ERR_SCOPE_EMPTY`); and every scope item not in `VOIDED` status must already
    be `INSTALLED` (`ERR_SCOPE_ITEMS_PENDING`)."

    Design: Difficulty/boundary_precision_check/empty_scope_set_rejection
    """
    ctx = setup_on_site_job(priority="P3", with_assessment=True)
    assignee = ctx["assignee"]
    item = add_scope_item(ctx["job"]["id"], kind="BOARD", opening_count=1,
                          width_in=48, height_in=36, door_count=0)
    void_scope_item(item["id"])

    res = api.complete_securing(ctx["job"]["id"], make_subcontractor_headers(assignee["id"]))
    validate_error(res, "ERR_SCOPE_EMPTY", )
    assert get_job(ctx["job"]["id"])["work_status"] == "ON_SITE", (
        "an all-VOIDED scope is the empty set for securing purposes")


def test_scope_items_pending_rejected(api, dispatcher_headers):
    """PRD §3.5: "every scope item not in `VOIDED` status must already be
    `INSTALLED` (`ERR_SCOPE_ITEMS_PENDING`)."

    Design: Corner/endpoints/scope_items_pending_rejected
    """
    ctx = setup_on_site_job(priority="P3", with_assessment=True)
    assignee = ctx["assignee"]
    add_scope_item(ctx["job"]["id"], kind="BOARD", opening_count=1,
                   width_in=48, height_in=36, door_count=0)  # left PLANNED

    res = api.complete_securing(ctx["job"]["id"], make_subcontractor_headers(assignee["id"]))
    validate_error(res, "ERR_SCOPE_ITEMS_PENDING")
    assert get_job(ctx["job"]["id"])["work_status"] == "ON_SITE"


def test_complete_securing_state_failure_beats_safety(api, dispatcher_headers):
    """PRD §2.7: "The platform evaluates every request against the following
    stages, in this exact sequence, and surfaces the first failure encountered"
    with stage 5 "State eligibility" preceding stage 6 "Safety and regulatory
    gates".
    PRD §2.7: "otherwise the entity must be in the action's expected from-state,
    failing with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/complete_securing_state_failure_beats_safety
    """
    # Job is DISPATCHED (complete-securing expects ON_SITE) AND no cleared
    # assessment exists: both the state gate and the safety gate fail.
    ctx = setup_dispatched_job(priority="P3", num_subcontractors=1, covered_count=1)
    sa = ctx["subs"][0]
    accept_offer(ctx["assignment"]["id"], sa["id"])

    res = api.complete_securing(ctx["job"]["id"], make_subcontractor_headers(sa["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    assert res.json()["data"]["error_id"] != "ERR_HAZARD_NOT_MITIGATED", (
        "the from-state violation must mask the safety gate")


def test_complete_securing_hazard_gate_in_isolation(api, dispatcher_headers):
    """PRD §3.5: "Four gates guard that declaration, in validation-precedence
    order: the caller must be the job's assignee subcontractor
    (`ERR_NOT_ASSIGNEE`); the job's `safety_cleared` flag must be true, meaning a
    cleared assessment is on file (`ERR_HAZARD_NOT_MITIGATED`)"

    Design: Difficulty/priority_pair_validation_conflict/complete_securing_state_failure_beats_safety
    """
    # Isolated safety failure: job correctly ON_SITE with installed scope, but no
    # assessment was ever submitted — the hazard gate alone must fire.
    ctx = setup_on_site_job(priority="P3", with_assessment=False)
    assignee = ctx["assignee"]
    item = add_scope_item(ctx["job"]["id"], kind="BOARD", opening_count=1,
                          width_in=48, height_in=36, door_count=0)
    install_scope_item(item["id"], assignee["id"], opening_count=1,
                       width_in=48, height_in=36, door_count=0)

    res = api.complete_securing(ctx["job"]["id"], make_subcontractor_headers(assignee["id"]))
    validate_error(res, "ERR_HAZARD_NOT_MITIGATED")
    assert get_job(ctx["job"]["id"])["work_status"] == "ON_SITE"

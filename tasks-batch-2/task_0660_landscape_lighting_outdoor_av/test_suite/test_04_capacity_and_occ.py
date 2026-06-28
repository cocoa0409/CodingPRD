"""Transformer load budget: the usable-capacity derate, the exact-equal vs
exceed boundary, optimistic concurrency on the transformer version, the
state-beats-fiscal precedence, cross-project and existence checks, and
decommission guarding.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    setup_project_with_transformer_and_zone,
    setup_zone_near_capacity,
    setup_installed_project,
    create_customer,
    create_project,
    create_fixture,
    api_client,
    GHOST_UUID,
    TEST_USERS,
)
import test_helpers.factories as F

DESIGNER = TEST_USERS["lighting_designer_headers"]
TECH = TEST_USERS["install_tech_headers"]
ADMIN = TEST_USERS["operations_admin_headers"]


# ---------------------------------------------------------------------------
# Computed usable capacity (corner: entities)
# ---------------------------------------------------------------------------
def test_transformer_usable_capacity_is_floored_derate(api):
    """PRD §2.5: "the system immediately derives its `usable_capacity_va` by
    taking eighty percent of the rated value and discarding any fractional VA —
    that is, multiplying `rated_capacity_va` by 0.80 and flooring the result to a
    whole number of VA."

    rated 150 -> floor(150*0.80) == 120; committed starts 0; status STAGED.

    Design: Corner/entities/transformer_usable_capacity_computed_floor
    """
    cust = create_customer()
    project = create_project(cust["id"])
    tx = validate_success(api.create_transformer(
        F.create_transformer_payload(project["id"], model_code="TX-150", rated_capacity_va=150), DESIGNER),
        expected_status=201)
    assert tx["usable_capacity_va"] == 120, tx["usable_capacity_va"]
    assert tx["committed_load_va"] == 0, tx["committed_load_va"]
    assert tx["status"] == "STAGED", tx["status"]


# ---------------------------------------------------------------------------
# Capacity boundary (difficulty: boundary_precision_check)
# ---------------------------------------------------------------------------
def test_committed_load_at_exact_usable_capacity_allowed(api):
    """PRD §2.5: "Any operation that would push a transformer's post-action
    `committed_load_va` strictly above its `usable_capacity_va` is rejected with
    `ERR_TRANSFORMER_CAPACITY_EXCEEDED`; the boundary case where the resulting
    committed load lands exactly equal to the usable capacity is permitted."

    Three 80W fixtures sum to exactly 240 == usable (300*0.80), which is allowed.

    Design: Difficulty/boundary_precision_check/transformer_capacity_at_exact_usable_boundary
    """
    ctx = setup_zone_near_capacity(
        [{"model_code": "F80", "category": "SPOT", "wattage_w": 80, "purchase_price_cents": 1000}] * 3,
        rated_capacity_va=300,
    )
    tx = validate_success(api.get_transformer(ctx["tx_id"], DESIGNER))
    assert tx["committed_load_va"] == 240, tx["committed_load_va"]


def test_committed_load_one_over_usable_capacity_rejected(api):
    """PRD §2.5: "Any operation that would push a transformer's post-action
    `committed_load_va` strictly above its `usable_capacity_va` is rejected with
    `ERR_TRANSFORMER_CAPACITY_EXCEEDED`".

    With the transformer at exactly 240, assigning a further 1W fixture would
    reach 241 > 240 and is rejected; committed load stays 240.

    Design: Difficulty/boundary_precision_check/transformer_capacity_at_exact_usable_boundary
    """
    ctx = setup_zone_near_capacity(
        [{"model_code": "F80", "category": "SPOT", "wattage_w": 80, "purchase_price_cents": 1000}] * 3,
        rated_capacity_va=300,
    )
    extra = create_fixture(ctx["project_id"], model_code="F1", category="PATH",
                           wattage_w=1, purchase_price_cents=1000)
    tx = validate_success(api.get_transformer(ctx["tx_id"], DESIGNER))
    validate_error(
        api.assign_zone(extra["id"], F.assign_zone_payload(ctx["zone_id"], tx["version"]), DESIGNER),
        ApiErrorId.ERR_TRANSFORMER_CAPACITY_EXCEEDED.value,
    )
    tx_after = validate_success(api.get_transformer(ctx["tx_id"], DESIGNER))
    assert tx_after["committed_load_va"] == 240, tx_after["committed_load_va"]


# ---------------------------------------------------------------------------
# State-beats-fiscal precedence (difficulty: priority_pair_validation_conflict)
# ---------------------------------------------------------------------------
def _installed_full_transformer():
    """An INSTALLED project whose 300VA transformer is at 240 (three INSTALLED 80W
    fixtures in one zone). Returns (ctx, installed_fixture_ids)."""
    ctx = setup_installed_project(
        rated_capacity_va=300,
        fixture_specs=[{"model_code": "F80", "category": "SPOT", "wattage_w": 80,
                        "purchase_price_cents": 1000}] * 3,
        quote_lines=[{"model_code": "F80", "quantity": 3, "unit_price_cents": 1000}],
    )
    return ctx, [fx["id"] for fx in ctx["fixtures"]]


def test_assign_installed_fixture_returns_invalid_state_not_capacity(api):
    """PRD §2.10: "The state-machine guard that the target is in a state from which
    the requested transition is defined (`ERR_INVALID_STATE`) is checked sixth, and
    the transformer OCC check (`ERR_STALE_TRANSFORMER_VERSION`) seventh."
    PRD §2.10: "The remaining business rules — wiring-before-fixtures,
    unzoned-fixture lock, visit-window overlap, scene-window buffer, capacity
    ceiling, warranty age, window validity, demo-time presence, and email
    uniqueness — are evaluated after these foundational checks, each guarding the
    specific operations named in §3."
    PRD §3.2: "The fixture must currently be `PLANNED`."

    An already-INSTALLED fixture fails the state precondition at priority 6 before
    the priority-12 capacity check, so the error is ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_assign_zone
    """
    ctx, fixture_ids = _installed_full_transformer()
    tx = validate_success(api.get_transformer(ctx["tx_id"], DESIGNER))
    validate_error(
        api.assign_zone(fixture_ids[2], F.assign_zone_payload(ctx["zone_id"], tx["version"]), DESIGNER),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_assign_installed_fixture_leaves_committed_load_unchanged(api):
    """PRD §3.2: "The fixture must currently be `PLANNED`." and PRD §2.5: "the
    boundary case where the resulting committed load lands exactly equal to the
    usable capacity is permitted."

    The rejected re-assignment of an INSTALLED fixture does not alter the
    transformer's committed_load_va, which stays at 240.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_assign_zone
    """
    ctx, fixture_ids = _installed_full_transformer()
    tx = validate_success(api.get_transformer(ctx["tx_id"], DESIGNER))
    validate_error(
        api.assign_zone(fixture_ids[2], F.assign_zone_payload(ctx["zone_id"], tx["version"]), DESIGNER),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    tx_after = validate_success(api.get_transformer(ctx["tx_id"], DESIGNER))
    assert tx_after["committed_load_va"] == 240, tx_after["committed_load_va"]


# ---------------------------------------------------------------------------
# Existence-beats-referential precedence (difficulty: priority_pair)
# ---------------------------------------------------------------------------
def test_zone_create_with_nonexistent_transformer_returns_not_found(api):
    """PRD §2.10: "Existence of every referenced identifier
    (`ERR_RESOURCE_NOT_FOUND`) is checked third."
    PRD §2.10: "Cross-project referential integrity
    (`ERR_CROSS_PROJECT_REFERENCE`) is checked fifth."
    PRD §2.9: "an identifier in a path or body that does not resolve to an
    existing resource yields `ERR_RESOURCE_NOT_FOUND`."

    A zone body naming a transformer id that does not exist fails existence
    (priority 3) before the referential check (priority 5).

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_referential_on_zone_create
    """
    cust = create_customer()
    project = create_project(cust["id"])
    validate_error(
        api.create_zone(project["id"], F.create_zone_payload(GHOST_UUID, label="Ghost"), DESIGNER),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
    )


def test_zone_create_with_nonexistent_transformer_creates_no_zone(api):
    """PRD §2.9: "an identifier in a path or body that does not resolve to an
    existing resource yields `ERR_RESOURCE_NOT_FOUND`." PRD §3.1: "Creating the
    first `Zone` on a project advances its `design_status` from `DRAFT` to
    `ZONED`".

    The rejected zone create leaves the project at DRAFT with no zone created.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_referential_on_zone_create
    """
    cust = create_customer()
    project = create_project(cust["id"])
    validate_error(
        api.create_zone(project["id"], F.create_zone_payload(GHOST_UUID, label="Ghost"), DESIGNER),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
    )
    zones, _meta = validate_paginated(api.list_project_zones(project["id"], DESIGNER))
    proj = validate_success(api.get_project(project["id"], DESIGNER))
    assert proj["design_status"] == "DRAFT", proj["design_status"]
    assert zones == [], zones


# ---------------------------------------------------------------------------
# OCC on transformer version (corner: cross_cutting_complexity_layers)
# ---------------------------------------------------------------------------
def test_assign_with_stale_transformer_version_rejected(api):
    """PRD §2.6: "If they do not match — because another assignment or an add-on
    activation has already drawn load the client never saw — the request is
    rejected with `ERR_STALE_TRANSFORMER_VERSION` and an HTTP 412 status".

    The first assign bumps the transformer version; a second assign still carrying
    the pre-bump version is stale.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_transformer_version_on_assign
    """
    ctx = setup_project_with_transformer_and_zone()
    fx1 = create_fixture(ctx["project_id"], model_code="A", wattage_w=10, purchase_price_cents=4000)
    fx2 = create_fixture(ctx["project_id"], model_code="B", wattage_w=10, purchase_price_cents=4000)
    v0 = ctx["tx_version"]
    validate_success(api.assign_zone(fx1["id"], F.assign_zone_payload(ctx["zone_id"], v0), DESIGNER))
    # Second assign reuses the now-stale v0.
    validate_error(
        api.assign_zone(fx2["id"], F.assign_zone_payload(ctx["zone_id"], v0), DESIGNER),
        ApiErrorId.ERR_STALE_TRANSFORMER_VERSION.value,
    )
    fx2_now = validate_success(api.get_fixture(fx2["id"], DESIGNER))
    assert fx2_now["zone_id"] is None, fx2_now["zone_id"]


def test_assign_with_current_version_succeeds_and_bumps_version(api):
    """PRD §2.6: "If they match, the assignment proceeds (subject to the capacity
    gate) and the transformer's `version` is incremented by one."
    PRD §3.2: "the fixture's `zone_id` is set, the zone's `zone_load_va` is
    recomputed upward by the fixture's wattage, the transformer's
    `committed_load_va` is recomputed, the project's `total_committed_load_va` is
    recomputed, and the target transformer's `version` is incremented by one."

    Assign with the current version sets zone_id, raises committed_load_va to the
    fixture's wattage, and increments the transformer version from 1 to 2.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_assign_succeeds_and_bumps_version
    """
    ctx = setup_project_with_transformer_and_zone()
    fx = create_fixture(ctx["project_id"], model_code="A", wattage_w=10, purchase_price_cents=4000)
    assigned = validate_success(
        api.assign_zone(fx["id"], F.assign_zone_payload(ctx["zone_id"], ctx["tx_version"]), DESIGNER))
    assert assigned["zone_id"] == ctx["zone_id"], assigned["zone_id"]
    tx = validate_success(api.get_transformer(ctx["tx_id"], DESIGNER))
    assert tx["committed_load_va"] == 10, tx["committed_load_va"]
    assert tx["version"] == 2, tx["version"]


# ---------------------------------------------------------------------------
# Cross-project zone reference (corner: validations)
# ---------------------------------------------------------------------------
def test_zone_referencing_other_project_transformer_rejected(api):
    """PRD §2.9: "A zone's `transformer_id` must point at a transformer belonging
    to the same project as the zone ... A reference that crosses a project boundary
    in any of these three ways is rejected with `ERR_CROSS_PROJECT_REFERENCE`."

    A transformer exists under project B; creating a zone under project A that
    names it crosses the boundary (existence passes, referential fails).

    Design: Corner/validations/cross_project_zone_transformer_reference
    """
    cust = create_customer()
    proj_a = create_project(cust["id"], property_address="A")
    proj_b = create_project(cust["id"], property_address="B")
    tx_b = validate_success(api.create_transformer(
        F.create_transformer_payload(proj_b["id"], rated_capacity_va=300), DESIGNER),
        expected_status=201)
    validate_error(
        api.create_zone(proj_a["id"], F.create_zone_payload(tx_b["id"], label="Z"), DESIGNER),
        ApiErrorId.ERR_CROSS_PROJECT_REFERENCE.value,
    )


# ---------------------------------------------------------------------------
# Decommission guard (corner: validations)
# ---------------------------------------------------------------------------
def test_decommission_transformer_with_live_fixture_rejected(api):
    """PRD §3.6: "An installer may also decommission a transformer that is
    `ENERGIZED`, moving it to `DECOMMISSIONED` (terminal) — but only when no zone
    fed by that transformer still has a fixture in `PLANNED` or `INSTALLED`
    status. A decommission attempted on a transformer that is not `ENERGIZED`, or
    while a zone it feeds still holds a planned or installed fixture, is rejected
    with `ERR_TRANSFORMER_NOT_ENERGIZED`."

    Design: Corner/validations/decommission_transformer_with_live_fixtures_rejected
    """
    ctx = setup_installed_project(
        fixture_specs=[{"model_code": "A", "category": "PATH", "wattage_w": 3,
                        "purchase_price_cents": 4000}],
        quote_lines=[{"model_code": "A", "quantity": 1, "unit_price_cents": 4000}],
    )
    tx = validate_success(api.get_transformer(ctx["tx_id"], DESIGNER))
    assert tx["status"] == "ENERGIZED", tx["status"]
    validate_error(
        api.decommission_transformer(ctx["tx_id"], TECH),
        ApiErrorId.ERR_TRANSFORMER_NOT_ENERGIZED.value,
    )
    tx_after = validate_success(api.get_transformer(ctx["tx_id"], DESIGNER))
    assert tx_after["status"] == "ENERGIZED", tx_after["status"]

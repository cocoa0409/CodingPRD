"""Cut programs, nesting yield, die tooling, lock gates, optimistic
concurrency on spec version, and the supersede cascade."""
import pytest

from test_helpers import (
    DESIGN,
    QUALITY,
    SALES,
    ApiErrorId,
    begin_validation,
    commission_tooling,
    confirm_order,
    create_approved_spec,
    create_customer,
    create_cut_program,
    create_locked_die_program,
    create_material,
    create_quoted_order,
    create_spec,
    create_submitted_spec,
    create_tooling,
    get_spec,
    get_tooling,
    nest_program,
    patch_material,
    submit_spec,
    validate_error,
    validate_success,
)


def test_nesting_yield_exact_values(api):
    """PRD §3.3: "The study consumes a quarter-inch kerf of material between
    adjacent parts. It tries both part orientations on the stock sheet and
    keeps the better result." PRD §3.3: "The `sheet_utilization_pct` is one
    hundred times `parts_per_sheet` times the part's footprint area —
    `part_length_in` times `part_width_in` — divided by the sheet's face
    area — `sheet_length_in` times `sheet_width_in` — rounded half-up to two
    decimal places." PRD §3.3: "The `offcut_sqft_per_sheet` is the sheet's
    face area minus the area converted to parts minus the kerf waste, divided
    by 144 to convert square inches to square feet, rounded half-up to two
    decimal places."

    Design: Corner/calculations/nesting_yield_exact_values
    """
    _customer, _material, spec = create_submitted_spec()
    program = create_cut_program(spec["id"], method="DIE_CUT")

    nested = nest_program(program["id"])
    assert nested["status"] == "NESTED"
    # 10x8 part on a 108x48 sheet, 0.25 in kerf: rotated orientation wins
    # with 13 cols x 4 rows = 52 parts (normal gives 10 x 5 = 50).
    assert nested["parts_per_sheet"] == 52
    assert nested["sheet_utilization_pct"] == pytest.approx(80.25, abs=1e-6)
    assert nested["offcut_sqft_per_sheet"] == pytest.approx(5.49, abs=1e-6)


def test_cnc_program_missing_machine_seconds_rejected(api):
    """PRD §3.3: "When `method` is `CNC_ROUTE`, the payload must also carry
    `machine_seconds_per_part`, the CNC cutting time per part; omitting it is
    rejected with `ERR_INVALID_REQUEST` (HTTP 400), while for `DIE_CUT` the
    field is ignored."

    Design: Corner/validations/cnc_program_missing_machine_seconds_rejected
    """
    _customer, _material, spec = create_submitted_spec()
    resp = api.create_cut_program(
        {
            "package_spec_id": spec["id"],
            "method": "CNC_ROUTE",
            "expected_package_spec_version": get_spec(spec["id"])["version"],
        },
        DESIGN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_tooling_on_cnc_program_rejected(api):
    """PRD §3.3: "Ordering a die against a `CNC_ROUTE` program is rejected
    with `ERR_METHOD_MISMATCH` (HTTP 422)."

    Design: Corner/validations/tooling_on_cnc_program_rejected
    """
    _customer, _material, spec = create_submitted_spec()
    program = create_cut_program(spec["id"], method="CNC_ROUTE",
                                 machine_seconds_per_part=40)

    resp = api.create_tooling(
        {
            "cut_program_id": program["id"],
            "die_cost_cents": 250000,
            "amortization_qty": 1000,
            "lead_time_days": 10,
        },
        DESIGN,
    )
    validate_error(resp, ApiErrorId.ERR_METHOD_MISMATCH)


def test_lock_die_program_without_tooling_rejected(api):
    """PRD §3.3: "Third, for a `DIE_CUT` program, a Tooling must exist for
    the program — none is rejected with `ERR_TOOLING_REQUIRED` (HTTP 422) —
    and it must be `IN_SERVICE`; a tooling that is merely `ORDERED`, or
    already `RETIRED`, yields `ERR_TOOLING_NOT_IN_SERVICE` (HTTP 409)."

    Design: Corner/validations/lock_die_program_without_tooling_rejected
    """
    _customer, _material, spec = create_submitted_spec()
    program = create_cut_program(spec["id"], method="DIE_CUT")
    nest_program(program["id"])

    resp = api.lock_cut_program(program["id"], DESIGN)
    validate_error(resp, ApiErrorId.ERR_TOOLING_REQUIRED)


def test_lock_with_zero_yield_rejected(api):
    """PRD §3.3: "Second, `parts_per_sheet` must be greater than zero, or the
    lock is rejected with `ERR_UTILIZATION_INFEASIBLE` (HTTP 422)." PRD §3.3:
    "A part that fits the sheet in neither orientation legitimately computes
    a `parts_per_sheet` of zero; the program may stand `NESTED` with that
    result, but it cannot be locked."

    Design: Corner/validations/lock_with_zero_yield_rejected
    """
    customer = create_customer()
    material = create_material(foam_family="EPE", density_pcf=2.5, ild_lb_25=400)
    # A 200x60 part cannot fit a 108x48 sheet in either orientation.
    spec = create_spec(customer["id"], material["id"], part_name="Oversize Tray",
                       part_length_in=200, part_width_in=60)
    submit_spec(spec["id"])
    program = create_cut_program(spec["id"], method="DIE_CUT")
    nested = nest_program(program["id"])
    assert nested["parts_per_sheet"] == 0
    tooling = create_tooling(program["id"])
    commission_tooling(tooling["id"])

    resp = api.lock_cut_program(program["id"], DESIGN)
    validate_error(resp, ApiErrorId.ERR_UTILIZATION_INFEASIBLE)


def test_tooling_retire_is_terminal(api):
    """PRD §3.3: "Commissioning moves it from `ORDERED` to `IN_SERVICE`;
    retirement moves it from `ORDERED` or `IN_SERVICE` to `RETIRED`." PRD
    §2.5: "The target resource must be in a valid from-state for the
    requested transition, and cross-entity state gates must hold — rejected
    as `ERR_INVALID_STATE`, `ERR_SPEC_NOT_APPROVED`, `ERR_PROGRAM_NOT_ACTIVE`,
    `ERR_TOOLING_NOT_IN_SERVICE`, or `ERR_PROGRAM_HAS_OPEN_RELEASES` (all HTTP
    409)."

    Design: Corner/state_machines/tooling_retire_is_terminal
    """
    _customer, _material, spec = create_submitted_spec()
    program = create_cut_program(spec["id"], method="DIE_CUT")
    tooling = create_tooling(program["id"])

    retired = validate_success(api.retire_tooling(tooling["id"], DESIGN))
    assert retired["status"] == "RETIRED"

    resp = api.commission_tooling(tooling["id"], DESIGN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_lock_blocked_while_tooling_only_ordered(api):
    """PRD §3.3: "Third, for a `DIE_CUT` program, a Tooling must exist for
    the program — none is rejected with `ERR_TOOLING_REQUIRED` (HTTP 422) —
    and it must be `IN_SERVICE`; a tooling that is merely `ORDERED`, or
    already `RETIRED`, yields `ERR_TOOLING_NOT_IN_SERVICE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/lock_requires_tooling_in_service
    """
    _customer, _material, spec = create_submitted_spec()
    program = create_cut_program(spec["id"], method="DIE_CUT")
    nest_program(program["id"])
    tooling = create_tooling(program["id"])  # stays ORDERED
    assert tooling["status"] == "ORDERED"

    resp = api.lock_cut_program(program["id"], DESIGN)
    validate_error(resp, ApiErrorId.ERR_TOOLING_NOT_IN_SERVICE)


def test_lock_succeeds_after_tooling_commissioned(api):
    """PRD §3.3: "Commissioning moves it from `ORDERED` to `IN_SERVICE`;
    retirement moves it from `ORDERED` or `IN_SERVICE` to `RETIRED`." PRD
    §3.3: "Locking marks the program as the specification's active
    manufacturing definition and increments the specification's `version` by
    1 — which is exactly why cut-program creation pins the spec version it
    observed."

    Design: Difficulty/cross_entity_state_dependency/lock_requires_tooling_in_service
    """
    _customer, _material, spec = create_submitted_spec()
    program = create_cut_program(spec["id"], method="DIE_CUT")
    nest_program(program["id"])
    tooling = create_tooling(program["id"])
    version_before = get_spec(spec["id"])["version"]

    tooling = commission_tooling(tooling["id"])
    assert tooling["status"] == "IN_SERVICE"

    locked = validate_success(api.lock_cut_program(program["id"], DESIGN))
    assert locked["status"] == "LOCKED"
    assert get_spec(spec["id"])["version"] == version_before + 1, (
        "locking advances the specification's version by 1"
    )


def test_lock_safety_margin_reported_when_ild_and_yield_both_fail(api):
    """PRD §2.5: "Every request is validated against the following pipeline,
    evaluated in this order; the first failing check rejects the request, so
    an earlier failure masks every later check." PRD §3.3: "First, the
    cushioning safety margin is re-checked at lock time: the material's
    current `ild_lb_25` must still be at least the specification's
    `required_ild_lb`, or the lock is rejected with `ERR_ILD_SAFETY_MARGIN`
    (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/lock_safety_margin_beats_utilization
    """
    customer = create_customer()
    material = create_material(foam_family="PU", density_pcf=2.0, ild_lb_25=240)
    # weight 20, drop exactly 48 -> HIGH band -> required_ild_lb 240.
    spec = create_spec(customer["id"], material["id"], part_name="Oversize Tray",
                       part_length_in=200, part_width_in=60,
                       product_weight_lb=20, required_drop_height_in=48)
    assert spec["required_ild_lb"] == 240
    submit_spec(spec["id"])
    # Lower the material's ILD after submission; lock re-reads it.
    patch_material(material["id"], ild_lb_25=100)

    program = create_cut_program(spec["id"], method="DIE_CUT")
    nested = nest_program(program["id"])
    assert nested["parts_per_sheet"] == 0, (
        "the 200x60 part cannot fit the 108x48 sheet in either orientation"
    )
    tooling = create_tooling(program["id"])
    commission_tooling(tooling["id"])

    resp = api.lock_cut_program(program["id"], DESIGN)
    err = validate_error(resp, ApiErrorId.ERR_ILD_SAFETY_MARGIN)
    assert err["error_id"] != ApiErrorId.ERR_UTILIZATION_INFEASIBLE, (
        "the cushioning safety check (earlier in the pipeline) masks the "
        "zero-yield feasibility failure"
    )


def test_lock_zero_yield_reported_once_safety_margin_passes(api):
    """PRD §3.3: "First, the cushioning safety margin is re-checked at lock
    time: the material's current `ild_lb_25` must still be at least the
    specification's `required_ild_lb`, or the lock is rejected with
    `ERR_ILD_SAFETY_MARGIN` (HTTP 422). Second, `parts_per_sheet` must be
    greater than zero, or the lock is rejected with
    `ERR_UTILIZATION_INFEASIBLE` (HTTP 422)." PRD §3.1: "A `PlantManager` may
    later update a material's `cost_per_board_ft_cents`, `ild_lb_25`,
    `density_pcf`, or `scrap_credit_per_lb_cents`."

    Design: Difficulty/priority_pair_validation_conflict/lock_safety_margin_beats_utilization
    """
    customer = create_customer()
    material = create_material(foam_family="PU", density_pcf=2.0, ild_lb_25=240)
    spec = create_spec(customer["id"], material["id"], part_name="Oversize Tray",
                       part_length_in=200, part_width_in=60,
                       product_weight_lb=20, required_drop_height_in=48)
    submit_spec(spec["id"])
    patch_material(material["id"], ild_lb_25=100)

    program = create_cut_program(spec["id"], method="DIE_CUT")
    nest_program(program["id"])
    tooling = create_tooling(program["id"])
    commission_tooling(tooling["id"])
    validate_error(
        api.lock_cut_program(program["id"], DESIGN),
        ApiErrorId.ERR_ILD_SAFETY_MARGIN,
    )

    # Restore the material's ILD so the safety gate passes; the zero-yield
    # feasibility gate is the one that must now report.
    patch_material(material["id"], ild_lb_25=240)
    resp = api.lock_cut_program(program["id"], DESIGN)
    validate_error(resp, ApiErrorId.ERR_UTILIZATION_INFEASIBLE)


def test_occ_stale_spec_version_rejected(api):
    """PRD §2.7: "The request must carry `expected_package_spec_version`,
    holding the `version` of the target PackageSpec that the client last
    observed. If the specification's current `version` no longer equals the
    supplied value — because the specification has been mutated since the
    client read it — the create is rejected with `ERR_STALE_SPEC_VERSION`
    (HTTP 412), preventing the client from building on a specification it has
    not observed."

    Design: Corner/complexity_layers/occ_stale_spec_version_rejected
    """
    _customer, _material, spec = create_submitted_spec()
    observed_version = get_spec(spec["id"])["version"]
    first = create_cut_program(spec["id"], method="CNC_ROUTE",
                               machine_seconds_per_part=40,
                               expected_version=observed_version)
    assert first["status"] == "DRAFT"

    # The first create advanced the spec's version, so the observed token is
    # now stale.
    resp = api.create_cut_program(
        {
            "package_spec_id": spec["id"],
            "method": "DIE_CUT",
            "expected_package_spec_version": observed_version,
        },
        DESIGN,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_SPEC_VERSION)

    fresh_version = get_spec(spec["id"])["version"]
    second = create_cut_program(spec["id"], method="DIE_CUT",
                                expected_version=fresh_version)
    assert second["status"] == "DRAFT"


def test_supersede_of_non_locked_program_rejected(api):
    """PRD §3.3: "The create also accepts an optional
    `supersedes_cut_program_id`; when present, the referenced `LOCKED`
    program is transitioned to `OBSOLETE` as part of the create, with the
    full obsolescence cascade of §3.5 — its `QUOTED` and `CONFIRMED`
    production orders are cancelled with their compensation." PRD §2.5: "The
    target resource must be in a valid from-state for the requested
    transition, and cross-entity state gates must hold — rejected as
    `ERR_INVALID_STATE`, `ERR_SPEC_NOT_APPROVED`, `ERR_PROGRAM_NOT_ACTIVE`,
    `ERR_TOOLING_NOT_IN_SERVICE`, or `ERR_PROGRAM_HAS_OPEN_RELEASES` (all HTTP
    409)."

    Design: Corner/endpoints/supersede_of_non_locked_program_rejected
    """
    _customer, _material, spec = create_submitted_spec()
    program = create_cut_program(spec["id"], method="CNC_ROUTE",
                                 machine_seconds_per_part=40)
    nest_program(program["id"])  # NESTED, never LOCKED

    resp = api.create_cut_program(
        {
            "package_spec_id": spec["id"],
            "method": "CNC_ROUTE",
            "machine_seconds_per_part": 40,
            "expected_package_spec_version": get_spec(spec["id"])["version"],
            "supersedes_cut_program_id": program["id"],
        },
        DESIGN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def _setup_confirmed_die_order_for_supersede():
    """Approved spec + LOCKED DIE program with IN_SERVICE tooling + one
    CONFIRMED order (which has charged the die 125000 cents)."""
    customer, material, spec = create_approved_spec()
    program, tooling = create_locked_die_program(spec["id"])
    order = create_quoted_order(spec["id"], program["id"], 500)
    confirm_order(order["id"])
    return customer, material, spec, program, tooling, order


def test_supersede_obsoletes_old_program_and_creates_draft(api):
    """PRD §3.3: "The create also accepts an optional
    `supersedes_cut_program_id`; when present, the referenced `LOCKED`
    program is transitioned to `OBSOLETE` as part of the create, with the
    full obsolescence cascade of §3.5 — its `QUOTED` and `CONFIRMED`
    production orders are cancelled with their compensation." PRD §3.3: "The
    new program starts in `DRAFT`, and its yield fields `parts_per_sheet`,
    `sheet_utilization_pct`, and `offcut_sqft_per_sheet` are null until
    nesting runs."

    Design: Difficulty/transitive_cascade/supersede_cascade_cancels_orders_and_deamortizes
    """
    _c, _m, spec, program, _tooling, _order = (
        _setup_confirmed_die_order_for_supersede()
    )

    successor = create_cut_program(
        spec["id"], method="DIE_CUT", supersedes_cut_program_id=program["id"],
    )
    assert successor["status"] == "DRAFT"
    assert successor["parts_per_sheet"] is None

    old = validate_success(api.get_cut_program(program["id"], DESIGN))
    assert old["status"] == "OBSOLETE", (
        "the referenced LOCKED program is obsoleted by the superseding create"
    )


def test_supersede_cancels_order_and_returns_die_amortization(api):
    """PRD §2.9: "Superseding or otherwise obsoleting a locked cut program
    cancels its open production orders (§3.3)." PRD §2.9: "Cancelling a
    confirmed die-cut production order returns its die amortization to the
    tooling — the tooling's `amortized_cents` is reduced by the order's
    `tooling_amort_cents` — and frees the order's machine window."

    Design: Difficulty/transitive_cascade/supersede_cascade_cancels_orders_and_deamortizes
    """
    _c, _m, spec, program, tooling, order = (
        _setup_confirmed_die_order_for_supersede()
    )
    assert get_tooling(tooling["id"])["amortized_cents"] == 125000, (
        "the confirmed order charged ceil(250000/1000)*500 = 125000 to the die"
    )

    create_cut_program(spec["id"], method="DIE_CUT",
                       supersedes_cut_program_id=program["id"])

    cancelled = validate_success(api.get_production_order(order["id"], SALES))
    assert cancelled["fab_status"] == "CANCELLED", (
        "the open order on the obsoleted program is cancelled by the cascade"
    )
    tooling_after = get_tooling(tooling["id"])
    assert tooling_after["amortized_cents"] == 0, (
        "the cancellation returns the 125000 charged cents to the die"
    )


def test_return_for_revision_cascade_obsoletes_programs_and_quotes(api):
    """PRD §3.2: "That single action increments `revision_no` by 1 and fires
    the full revision cascade: every cut program linked to the specification
    in `DRAFT`, `NESTED`, or `LOCKED` status becomes `OBSOLETE`; every
    production order referencing one of those obsoleted programs with
    `fab_status` of `QUOTED` or `CONFIRMED` becomes `CANCELLED`; and each
    confirmed order so cancelled compensates per §2.9 — its die amortization
    is returned to the tooling and its machine window is freed."

    Design: Corner/state_machines/return_for_revision_cascade_obsoletes_programs_and_quotes
    """
    customer = create_customer()
    material = create_material()
    spec = create_spec(customer["id"], material["id"])
    submit_spec(spec["id"])
    begin_validation(spec["id"])
    program = create_cut_program(spec["id"], method="CNC_ROUTE",
                                 machine_seconds_per_part=40)
    nest_program(program["id"])
    order = create_quoted_order(spec["id"], program["id"], 100)
    assert order["fab_status"] == "QUOTED"

    revised = validate_success(api.return_for_revision(spec["id"], QUALITY))
    assert revised["status"] == "DRAFT"
    assert revised["revision_no"] == 2

    obsolete = validate_success(api.get_cut_program(program["id"], DESIGN))
    assert obsolete["status"] == "OBSOLETE"
    cancelled = validate_success(api.get_production_order(order["id"], SALES))
    assert cancelled["fab_status"] == "CANCELLED"

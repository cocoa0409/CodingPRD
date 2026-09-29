"""Shape and invariant assertions for every entity this API returns.

Each ``assert_<entity>`` helper checks the properties the PRD says the
resource carries: the four universal system-managed properties, the caller
fields, and the enum domains of its status dimensions. The domain-invariant
helpers at the bottom encode conservation rules the PRD states in prose.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ApplicationClass,
    BatchQcStatus,
    BatchStage,
    CellId,
    ChamberId,
    CoatingRunStatus,
    Coolant,
    CustomerAccountStatus,
    CustomerTier,
    DepositionType,
    DossierStatus,
    EdgePrep,
    GeometryStatus,
    GradeStatus,
    GrindingRunStatus,
    JobStatus,
    LayerMaterial,
    OrderClass,
    OrderStatus,
    ProductReleaseStatus,
    ProductSupplyStatus,
    ToleranceClass,
    ToolType,
    TrialStatus,
    TrialVerdict,
    WheelStatus,
    WorkpieceGroup,
)


# ─── Generic building blocks ────────────────────────────────────────────────

def assert_common_fields(entity: dict) -> None:
    """Assert the four universal system-managed properties.

    No resource in this system omits ``updated_at`` or ``version``: ``id`` is a
    server-assigned UUID, ``created_at`` and ``updated_at`` are RFC 3339 UTC
    instants, and ``version`` is an integer that starts at 1.
    """
    assert "id" in entity, f"missing id: {entity}"
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']}"
    assert is_iso8601_timestamp(
        entity["created_at"]
    ), f"created_at is not RFC 3339 UTC: {entity['created_at']}"
    assert is_iso8601_timestamp(
        entity["updated_at"]
    ), f"updated_at is not RFC 3339 UTC: {entity['updated_at']}"
    assert isinstance(entity["version"], int), f"version is not an int: {entity['version']}"
    assert entity["version"] >= 1, f"version below 1: {entity['version']}"


def assert_enum_value(value, enum_cls, field_name: str) -> None:
    allowed = [member.value for member in enum_cls]
    assert value in allowed, f"{field_name} {value!r} is not one of {allowed}"


def assert_fields_present(entity: dict, field_names) -> None:
    missing = [name for name in field_names if name not in entity]
    assert not missing, f"missing fields {missing} in {sorted(entity)}"


# ─── Per-entity shape assertions ────────────────────────────────────────────

def assert_carbide_grade(grade: dict) -> None:
    assert_common_fields(grade)
    assert_fields_present(
        grade,
        [
            "grade_code",
            "target_workpiece_group",
            "co_binder_pct",
            "wc_grain_um",
            "hardness_hv",
            "trs_mpa",
            "status",
            "revision",
            "qualified_product_count",
            "authored_by_user_id",
        ],
    )
    assert_enum_value(grade["status"], GradeStatus, "status")
    assert_enum_value(
        grade["target_workpiece_group"], WorkpieceGroup, "target_workpiece_group"
    )
    assert grade["revision"] >= 1, f"revision below 1: {grade['revision']}"
    assert grade["qualified_product_count"] >= 0


def assert_powder_blend_batch(batch: dict) -> None:
    assert_common_fields(batch)
    assert_fields_present(
        batch,
        [
            "grade_id",
            "batch_code",
            "planned_mass_kg",
            "stage",
            "qc_status",
            "pinned_grade_revision",
            "pressed_units",
            "sintered_units",
            "scrap_units",
            "remaining_units",
        ],
    )
    assert_enum_value(batch["stage"], BatchStage, "stage")
    assert_enum_value(batch["qc_status"], BatchQcStatus, "qc_status")


def assert_insert_geometry(geometry: dict) -> None:
    assert_common_fields(geometry)
    assert_fields_present(
        geometry,
        [
            "geometry_code",
            "iso_designation",
            "application_class",
            "chipbreaker_code",
            "rake_angle_deg",
            "nose_radius_mm",
            "max_depth_of_cut_mm",
            "edge_prep",
            "status",
            "revision",
        ],
    )
    assert_enum_value(geometry["status"], GeometryStatus, "status")
    assert_enum_value(
        geometry["application_class"], ApplicationClass, "application_class"
    )
    assert_enum_value(geometry["edge_prep"], EdgePrep, "edge_prep")


def assert_coating_recipe(recipe: dict) -> None:
    assert_common_fields(recipe)
    assert_fields_present(
        recipe,
        [
            "recipe_code",
            "deposition_type",
            "layers",
            "total_thickness_um",
            "adhesion_class",
            "is_validated",
            "revision",
        ],
    )
    assert_enum_value(recipe["deposition_type"], DepositionType, "deposition_type")
    assert isinstance(recipe["is_validated"], bool)
    assert 1 <= len(recipe["layers"]) <= 5, f"layer count out of range: {recipe['layers']}"
    for layer in recipe["layers"]:
        assert_enum_value(layer["material"], LayerMaterial, "layers[].material")


def assert_coating_run(run: dict) -> None:
    assert_common_fields(run)
    assert_fields_present(
        run,
        [
            "recipe_id",
            "chamber_id",
            "window_start",
            "window_end",
            "loaded_area_cm2",
            "status",
            "pinned_recipe_revision",
        ],
    )
    assert_enum_value(run["status"], CoatingRunStatus, "status")
    assert_enum_value(run["chamber_id"], ChamberId, "chamber_id")
    assert is_iso8601_timestamp(run["window_start"])
    assert is_iso8601_timestamp(run["window_end"])


def assert_grinding_wheel(wheel: dict) -> None:
    assert_common_fields(wheel)
    assert_fields_present(
        wheel,
        [
            "wheel_code",
            "spec_code",
            "initial_life_units",
            "consumed_life_units",
            "remaining_life_units",
            "dress_count",
            "status",
        ],
    )
    assert_enum_value(wheel["status"], WheelStatus, "status")
    assert_wheel_life_conserved(wheel)


def assert_grinding_run(run: dict) -> None:
    assert_common_fields(run)
    assert_fields_present(
        run,
        [
            "wheel_id",
            "product_id",
            "cell_id",
            "window_start",
            "window_end",
            "planned_units",
            "produced_units",
            "scrap_units",
            "tolerance_class",
            "consumed_life_units",
            "status",
        ],
    )
    assert_enum_value(run["status"], GrindingRunStatus, "status")
    assert_enum_value(run["cell_id"], CellId, "cell_id")
    if run["tolerance_class"] is not None:
        assert_enum_value(run["tolerance_class"], ToleranceClass, "tolerance_class")


def assert_tool_product(product: dict) -> None:
    assert_common_fields(product)
    assert_fields_present(
        product,
        [
            "sku",
            "order_class",
            "grade_id",
            "geometry_id",
            "coating_recipe_id",
            "tool_type",
            "list_price_cents",
            "min_order_qty",
            "nominal_length_mm",
            "min_regrind_length_mm",
            "regrind_step_mm",
            "grind_units_per_tool",
            "release_status",
            "supply_status",
            "engineering_lead_time_days",
            "expedite_eligible",
            "qualified_workpiece_groups",
            "open_order_units",
        ],
    )
    assert_enum_value(product["release_status"], ProductReleaseStatus, "release_status")
    assert_enum_value(product["supply_status"], ProductSupplyStatus, "supply_status")
    assert_enum_value(product["order_class"], OrderClass, "order_class")
    assert_enum_value(product["tool_type"], ToolType, "tool_type")
    assert isinstance(product["expedite_eligible"], bool)
    assert isinstance(product["list_price_cents"], int), "prices are whole cents"
    for group in product["qualified_workpiece_groups"]:
        assert_enum_value(group, WorkpieceGroup, "qualified_workpiece_groups[]")


def assert_qualification_dossier(dossier: dict) -> None:
    assert_common_fields(dossier)
    assert_fields_present(
        dossier,
        [
            "product_id",
            "dossier_code",
            "required_trial_count",
            "status",
            "completed_trial_count",
            "passed_trial_count",
            "composite_score",
            "submitted_by_user_id",
            "decided_by_user_id",
        ],
    )
    assert_enum_value(dossier["status"], DossierStatus, "status")
    assert 2 <= dossier["required_trial_count"] <= 8


def assert_machining_trial(trial: dict) -> None:
    assert_common_fields(trial)
    assert_fields_present(
        trial,
        [
            "dossier_id",
            "batch_id",
            "trial_code",
            "workpiece_material_code",
            "workpiece_group",
            "units_consumed",
            "cutting_speed_vc",
            "feed_fz",
            "depth_ap",
            "coolant",
            "status",
            "operator_user_id",
        ],
    )
    assert_enum_value(trial["status"], TrialStatus, "status")
    assert_enum_value(trial["workpiece_group"], WorkpieceGroup, "workpiece_group")
    assert_enum_value(trial["coolant"], Coolant, "coolant")
    if trial.get("verdict") is not None:
        assert_enum_value(trial["verdict"], TrialVerdict, "verdict")


def assert_customer(customer: dict) -> None:
    assert_common_fields(customer)
    assert_fields_present(
        customer,
        [
            "customer_code",
            "name",
            "tier",
            "regrind_credit_cents",
            "reserved_credit_cents",
            "account_status",
        ],
    )
    assert_enum_value(customer["account_status"], CustomerAccountStatus, "account_status")
    assert_enum_value(customer["tier"], CustomerTier, "tier")
    assert isinstance(customer["regrind_credit_cents"], int), "credit is whole cents"
    assert isinstance(customer["reserved_credit_cents"], int), "credit is whole cents"


def assert_tool_order(order: dict) -> None:
    assert_common_fields(order)
    assert_fields_present(
        order,
        [
            "customer_id",
            "product_id",
            "order_code",
            "order_class",
            "quantity",
            "expedite_requested",
            "status",
            "requires_reconfirmation",
            "hold_reason",
        ],
    )
    assert_enum_value(order["status"], OrderStatus, "status")
    assert_enum_value(order["order_class"], OrderClass, "order_class")
    assert isinstance(order["requires_reconfirmation"], bool)
    if order.get("per_unit_net_cents") is not None:
        assert isinstance(order["per_unit_net_cents"], int), "prices are whole cents"
    if order.get("total_price_cents") is not None:
        assert isinstance(order["total_price_cents"], int), "prices are whole cents"


def assert_recondition_job(job: dict) -> None:
    assert_common_fields(job)
    assert_fields_present(
        job,
        [
            "customer_id",
            "product_id",
            "job_code",
            "units_received",
            "regrind_pass_no",
            "reserved_credit_cents",
            "status",
        ],
    )
    assert_enum_value(job["status"], JobStatus, "status")
    assert job["regrind_pass_no"] >= 1
    assert isinstance(job["reserved_credit_cents"], int), "credit is whole cents"


# ─── Domain invariants stated by the PRD ────────────────────────────────────

def assert_wheel_life_conserved(wheel: dict) -> None:
    """``remaining_life_units`` is ``initial_life_units`` minus ``consumed_life_units``."""
    assert (
        wheel["remaining_life_units"]
        == wheel["initial_life_units"] - wheel["consumed_life_units"]
    ), (
        "wheel life drifted: "
        f"initial {wheel['initial_life_units']}, consumed {wheel['consumed_life_units']}, "
        f"remaining {wheel['remaining_life_units']}"
    )


def assert_credit_conserved(customer: dict, opening_balance_cents: int) -> None:
    """Available plus reserved credit stays at the opening balance.

    Intake moves cents from ``regrind_credit_cents`` into
    ``reserved_credit_cents``, and scrapping releases them back, so the sum is
    unchanged by either move.
    """
    total = customer["regrind_credit_cents"] + customer["reserved_credit_cents"]
    assert total == opening_balance_cents, (
        f"credit not conserved: available {customer['regrind_credit_cents']} + "
        f"reserved {customer['reserved_credit_cents']} = {total}, "
        f"expected {opening_balance_cents}"
    )


def assert_batch_units_conserved(batch: dict) -> None:
    """Sintered plus scrapped units equal the pressed count exactly."""
    assert batch["sintered_units"] + batch["scrap_units"] == batch["pressed_units"], (
        f"batch units not conserved: sintered {batch['sintered_units']} + "
        f"scrap {batch['scrap_units']} != pressed {batch['pressed_units']}"
    )


def assert_total_is_per_unit_times_quantity(order: dict) -> None:
    """The total is the rounded per-unit price multiplied by the quantity."""
    assert (
        order["total_price_cents"] == order["per_unit_net_cents"] * order["quantity"]
    ), (
        f"total {order['total_price_cents']} is not "
        f"{order['per_unit_net_cents']} x {order['quantity']}"
    )


def assert_no_row_with_code(rows, code_field: str, code_value: str) -> None:
    """Assert no listed row carries the given business code."""
    matches = [row for row in rows if row.get(code_field) == code_value]
    assert not matches, f"unexpected row with {code_field} {code_value}: {matches}"

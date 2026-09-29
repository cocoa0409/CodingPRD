"""Validation corners: uniqueness scopes, the two chemistry gates, inclusive
verification edges and the top of the first-failure ladder."""

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers.api_client import BatteryApiClient
from test_helpers.assertions import assert_assembly_axes, assert_close
from test_helpers.factories import (
    formation_bay_payload,
    insulation_verification_payload,
    lead_design_payload,
    lithium_design_payload,
    plant_payload,
    production_lot_payload,
    torque_verification_payload,
)
from test_helpers.fixtures import World
from test_helpers.test_users import make_design_engineer_headers, make_headers

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_USER_ID = "00000000-0000-0000-0000-0000000000ff"


def test_site_codes_are_globally_unique_while_bay_codes_are_only_per_plant(
    api: BatteryApiClient, admin_headers
):
    """The same BAY-1 is a duplicate inside one plant and a fresh row in another.

    "The uniqueness scopes are: a plant's `site_code`, a design's `code`, a charger's
    `model_code`, an assembly's `serial_number`, a unit's `serial_number` and a unit's
    `core_manifest_number` are unique across the whole system; a bay's `bay_code`, a chamber's
    `chamber_code` and a lot's `lot_code` are unique only within their plant." Both refusals share
    one code: "`ERR_DUPLICATE_CODE` (HTTP 409) on `POST /plants`, `POST /cell-designs`, `POST
    /chargers`, `POST /formation-bays`".

    Design: Corner/validations/duplicate_code_is_rejected_globally_for_site_code_but_only_per_plant_for_bay_code
    """
    validate_success(api.set_clock(C.CLOCK_START, admin_headers), 200)
    plant_a = validate_success(api.create_plant(plant_payload(), admin_headers), 201)
    plant_b = validate_success(
        api.create_plant(
            plant_payload(
                name="Eastside Battery Works",
                site_code="PLTEAST",
                licensed_chemistries=[C.CHEMISTRY_LEAD_ACID],
                peak_tariff_cents_per_kwh=30.00,
                offpeak_tariff_cents_per_kwh=18.00,
                lead_initial_inventory_kg=5000.000,
            ),
            admin_headers,
        ),
        201,
    )
    validate_success(
        api.create_formation_bay(formation_bay_payload(plant_a["id"]), admin_headers), 201
    )

    validate_error(
        api.create_plant(
            plant_payload(name="Riverside Battery Works Annex"), admin_headers
        ),
        E.ERR_DUPLICATE_CODE,
    )
    validate_error(
        api.create_formation_bay(
            formation_bay_payload(
                plant_a["id"], rated_power_kw=30.00, cooldown_minutes=30
            ),
            admin_headers,
        ),
        E.ERR_DUPLICATE_CODE,
    )

    twin = validate_success(
        api.create_formation_bay(
            formation_bay_payload(
                plant_b["id"], rated_power_kw=30.00, cooldown_minutes=30
            ),
            admin_headers,
        ),
        201,
    )
    assert twin["bay_code"] == C.BAY_CODE
    assert twin["plant_id"] == plant_b["id"]

    rows, meta = validate_paginated(api.list_formation_bays(admin_headers))
    assert meta["total_count"] == 2, rows
    assert [row["bay_code"] for row in rows] == [C.BAY_CODE, C.BAY_CODE]
    assert len({row["plant_id"] for row in rows}) == 2, rows


def test_the_plate_coherence_gate_and_the_plant_licence_gate_are_distinct(make_world):
    """A lithium design can be intrinsically illegal, or legal but unusable at this site.

    "a `LEAD_ACID` design must use `FLAT_PASTED` or `TUBULAR` plates and declare a lead content
    strictly greater than 0.000, while a `LITHIUM_LFP` design must use `PRISMATIC_CELL` plates and
    declare a lead content of exactly 0.000; violations return `ERR_PLATE_TYPE_INCOMPATIBLE`". The
    licence gate lives on the lot instead: "The copied chemistry must appear in the plant's
    `licensed_chemistries`, otherwise `ERR_CHEMISTRY_NOT_LICENSED`."

    Design: Corner/validations/unlicensed_chemistry_and_mismatched_plate_type_are_rejected_with_distinct_errors
    """
    world = make_world(
        plant_overrides={"licensed_chemistries": [C.CHEMISTRY_LEAD_ACID]},
        with_design=False,
    )
    lfp_id = world.approved_lithium_design(
        "CD-LFP-300",
        cells_per_battery=8,
        cell_nominal_voltage_v=3.20,
        nominal_capacity_ah=300.0,
        rated_cycles=3000,
        pack_weight_kg=400.0,
        list_price_cents=900000,
    )

    validate_error(
        world.api.create_cell_design(
            lithium_design_payload("CD-LFP-BAD", plate_type=C.PLATE_TUBULAR), world.eng_a
        ),
        E.ERR_PLATE_TYPE_INCOMPATIBLE,
    )
    validate_error(
        world.api.create_cell_design(
            lithium_design_payload("CD-LFP-LEADY", lead_content_kg=0.500), world.eng_a
        ),
        E.ERR_PLATE_TYPE_INCOMPATIBLE,
    )

    validate_error(
        world.api.create_production_lot(
            production_lot_payload(world.plant_id, lfp_id, "LOT-LFP", 12), world.sup_a
        ),
        E.ERR_CHEMISTRY_NOT_LICENSED,
    )

    designs, meta = validate_paginated(world.api.list_cell_designs(world.eng_a))
    assert meta["total_count"] == 1, designs
    assert designs[0]["code"] == "CD-LFP-300"
    lots, lot_meta = validate_paginated(world.api.list_production_lots(world.sup_a))
    assert lots == [], lots
    assert lot_meta["total_count"] == 0


def test_readings_sitting_on_the_inclusive_verification_edges_pass(world: World):
    """22.0 Nm, 19.0 Nm and an insulation reading equal to the floor all pass.

    "`torque_status` becomes `PASS` when the reading falls inside the window from `torque_spec_nm`
    multiplied by 0.95 up to `torque_spec_nm` multiplied by 1.10, with **both ends inclusive** -- a
    reading exactly on either boundary passes". The other axis is a floor with the same inclusivity:
    "`insulation_status` becomes `PASS` when `measured_ir_megaohm` is greater than or equal to
    `ir_min_megaohm` -- equality passes". Certification is their join: "It is `CERTIFIED` only when
    both `torque_status` and `insulation_status` are `PASS` ... and it remains `PENDING` for as long
    as either axis is still `PENDING`."

    Design: Corner/validations/torque_and_insulation_readings_on_the_inclusive_window_edges_pass_and_certify
    """
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-T", 9)
    high = world.add_assembly(lot["id"], "ASM-T1")
    low = world.add_assembly(lot["id"], "ASM-T2")

    torqued = validate_success(
        world.api.record_verification(
            high["id"], torque_verification_payload(22.0, 12), world.qa_a
        ),
        200,
    )
    assert_assembly_axes(torqued, torque_status=C.AXIS_PASS)
    assert_close(torqued["measured_torque_nm"], 22.0, "measured_torque_nm", 2)
    assert torqued["insulation_status"] == C.AXIS_PENDING
    assert torqued["certification_status"] == C.CERT_PENDING

    certified = validate_success(
        world.api.record_verification(
            high["id"], insulation_verification_payload(1.00, 500), world.qa_a
        ),
        200,
    )
    assert_assembly_axes(
        certified,
        torque_status=C.AXIS_PASS,
        insulation_status=C.AXIS_PASS,
        certification_status=C.CERT_CERTIFIED,
        rework_count=0,
    )
    assert_close(certified["measured_ir_megaohm"], 1.00, "measured_ir_megaohm", 2)

    lower_edge = validate_success(
        world.api.record_verification(
            low["id"], torque_verification_payload(19.0, 12), world.qa_a
        ),
        200,
    )
    assert_assembly_axes(
        lower_edge,
        torque_status=C.AXIS_PASS,
        insulation_status=C.AXIS_PENDING,
        certification_status=C.CERT_PENDING,
        rework_count=0,
    )
    assert_close(lower_edge["measured_torque_nm"], 19.0, "measured_torque_nm", 2)


def test_the_role_gate_beats_the_payload_gate_which_beats_the_actor_lookup(make_world):
    """One request breaks three rules and only the lowest-numbered tier is reported.

    "When several checks would fail on the same request, exactly one error is returned: the one
    belonging to the **lowest-numbered tier** below that fails." Tier 2 is "The acting role appears
    in the addressed endpoint's authorised-role list; otherwise `ERR_ROLE_NOT_PERMITTED`", tier 3
    refuses a body whose "enum members recognised, numeric bounds honoured" conditions fail with
    `ERR_VALIDATION`, and only then does tier 4 apply: "For endpoints whose authorised roles include
    any entity-backed role, `X-User-ID` resolves to a `Worker`; otherwise
    `ERR_ACTING_WORKER_NOT_FOUND`." Authorship itself is unrestricted by job class, since
    "Approving a cell design requires the acting worker's `job_class` to be `ENGINEER`".

    Design: Corner/validations/role_gate_precedes_payload_gate_which_precedes_actor_lookup
    """
    world = make_world(with_design=False)
    malformed = lead_design_payload(
        "CD-BAD", chemistry="NICKEL_IRON", cells_per_battery=0
    )

    validate_error(
        world.api.create_cell_design(
            malformed, make_headers(C.ROLE_QUALITY_INSPECTOR, UNKNOWN_USER_ID)
        ),
        E.ERR_ROLE_NOT_PERMITTED,
    )

    stranger = make_headers(C.ROLE_DESIGN_ENGINEER, UNKNOWN_USER_ID)
    validate_error(world.api.create_cell_design(malformed, stranger), E.ERR_VALIDATION)
    validate_error(
        world.api.create_cell_design(lead_design_payload(), stranger),
        E.ERR_ACTING_WORKER_NOT_FOUND,
    )

    authored = validate_success(
        world.api.create_cell_design(
            lead_design_payload(), make_design_engineer_headers(world.sup_a_id)
        ),
        201,
    )
    assert authored["code"] == C.LEAD_DESIGN_CODE
    assert authored["approval_state"] == C.DESIGN_DRAFT

    rows, meta = validate_paginated(world.api.list_cell_designs(world.eng_a))
    assert meta["total_count"] == 1, rows
    assert rows[0]["id"] == authored["id"]

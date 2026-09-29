"""Dock-intake and component-inspection validation rules.

Every test in this module builds its own world from scratch through the
documented endpoints: the logical clock is pinned, a model specification and a
program account are created, a shipment is opened and counted, and only then is
the rule under examination provoked.
"""
from test_helpers import (
    INTAKE_CLERK,
    TECHNICIAN_1,
    ApiErrorId,
    api_client,
    accept_shipment_payload,
    assert_equipment_unit,
    count_shipment_payload,
    create_account,
    create_equipment_unit_payload,
    create_inspection_payload,
    create_intake_shipment_payload,
    disassemble_unit,
    get_success_data,
    identify_unit,
    inspect_component,
    read_account,
    read_shipment,
    read_unit,
    register_units,
    setup_accepted_shipment,
    setup_counted_shipment,
    shell_component_criteria,
    validate_error,
    validate_paginated,
    validate_success,
)


def _open_counted_shipment(account_id, declared_unit_count, counted_unit_count, **overrides):
    """Open a shipment for an existing account and record its dock count, so the
    shipment is left in a status registration is defined from."""
    payload = create_intake_shipment_payload(
        account_id, declared_unit_count=declared_unit_count, **overrides
    )
    shipment = get_success_data(api_client.create_intake_shipment(payload, INTAKE_CLERK))
    return get_success_data(
        api_client.count_intake_shipment(
            shipment["id"], count_shipment_payload(counted_unit_count), INTAKE_CLERK
        )
    )


def _two_component_model_overrides():
    """A model that requires two component codes, so recording only the SHELL
    inspection leaves the unit in DISASSEMBLED with its rollup still PENDING."""
    return {
        "required_component_codes": ["SHELL", "LINER"],
        "component_criteria": [
            shell_component_criteria(),
            shell_component_criteria(
                code="LINER",
                metric="pad_thickness_mm",
                metric_direction="LOWER_IS_WORSE",
                replace_threshold=2.0,
                fail_threshold=1.0,
                unit="mm",
            ),
        ],
    }


def _units_of_shipment(shipment_id):
    return validate_paginated(
        api_client.list_equipment_units(
            INTAKE_CLERK, params={"intake_shipment_id": shipment_id}
        )
    )


def test_registering_more_units_than_the_dock_count_is_rejected():
    """The physical dock tally caps how many units the plant may carry.

    The shipment was counted at one unit and SN-0001 already occupies that slot,
    so registering a second shell SN-0002 must come back as
    ERR_UNIT_COUNT_EXCEEDED, and the shipment must still carry exactly one
    registered unit afterwards.

    PRD: "A registration that would push `units_registered` above
    `counted_unit_count` is rejected with `ERR_UNIT_COUNT_EXCEEDED` (HTTP 409)"

    Design: Corner/validations/registering_more_units_than_were_counted_rejected
    """
    ctx = setup_counted_shipment(unit_count=1)
    shipment_id = ctx["shipment"]["id"]

    response = api_client.create_equipment_unit(
        create_equipment_unit_payload(shipment_id, serial_number="SN-0002"), INTAKE_CLERK
    )
    validate_error(response, ApiErrorId.ERR_UNIT_COUNT_EXCEEDED.value, 409)

    shipment = read_shipment(shipment_id)
    assert shipment["units_registered"] == 1
    assert shipment["counted_unit_count"] == 1
    assert shipment["status"] == "COUNTED"

    units, meta = _units_of_shipment(shipment_id)
    assert meta["total_count"] == 1
    assert [unit["serial_number"] for unit in units] == ["SN-0001"]


def test_accepting_before_every_counted_unit_is_registered_is_rejected():
    """Acceptance is refused while the shipment's inventory is still incomplete.

    Two units were counted on the dock but only SN-0001 has been registered, so
    the accept must come back as ERR_UNIT_REGISTRATION_INCOMPLETE and none of
    the acceptance side effects — the acceptance stamp, the turnaround dates,
    the provisional settlement figure or the account's open-shipment exposure —
    may be written.

    PRD: "Acceptance additionally demands that every counted unit has been
    registered: when `units_registered` does not equal `counted_unit_count` the
    request is rejected with `ERR_UNIT_REGISTRATION_INCOMPLETE` (HTTP 409)."

    Design: Corner/validations/accept_before_every_counted_unit_is_registered_rejected
    """
    ctx = setup_counted_shipment(unit_count=2, register=False)
    shipment_id = ctx["shipment"]["id"]
    register_units(shipment_id, 1)

    response = api_client.accept_intake_shipment(
        shipment_id, accept_shipment_payload("MATCHED"), INTAKE_CLERK
    )
    validate_error(response, ApiErrorId.ERR_UNIT_REGISTRATION_INCOMPLETE.value, 409)

    shipment = read_shipment(shipment_id)
    assert shipment["status"] == "COUNTED"
    assert shipment["units_registered"] == 1
    assert shipment["counted_unit_count"] == 2
    assert shipment["accepted_at"] is None
    assert shipment["raw_due_at"] is None
    assert shipment["committed_due_at"] is None
    assert shipment["provisional_total_cents"] is None
    assert shipment["discrepancy_resolution"] is None

    account = read_account(ctx["account"]["id"])
    assert account["open_shipment_count"] == 0


def test_duplicate_serial_under_the_same_account_is_rejected():
    """Serial uniqueness is scoped to the owning program, across its shipments.

    SN-0001 is already on the books under the program's first shipment, so
    registering the same serial against a second shipment of that same program
    must come back as ERR_SERIAL_DUPLICATE and the second shipment must be left
    with nothing registered against it.

    PRD: "Serial numbers must not collide: if another unit bearing the same
    `serial_number` already exists under the same program's account, the
    registration is rejected with `ERR_SERIAL_DUPLICATE` (HTTP 409)."

    Design: Corner/validations/duplicate_serial_under_the_same_account_rejected
    """
    ctx = setup_counted_shipment(unit_count=1)
    second_shipment = _open_counted_shipment(ctx["account"]["id"], 1, 1)

    response = api_client.create_equipment_unit(
        create_equipment_unit_payload(second_shipment["id"], serial_number="SN-0001"),
        INTAKE_CLERK,
    )
    validate_error(response, ApiErrorId.ERR_SERIAL_DUPLICATE.value, 409)

    reread = read_shipment(second_shipment["id"])
    assert reread["units_registered"] == 0
    assert reread["status"] == "COUNTED"

    units, meta = _units_of_shipment(second_shipment["id"])
    assert meta["total_count"] == 0
    assert units == []

    first_shipment = read_shipment(ctx["shipment"]["id"])
    assert first_shipment["units_registered"] == 1


def test_the_same_serial_under_a_different_account_is_accepted():
    """Two programs may legitimately stamp the same serial on their own shells.

    Northside High already carries SN-0001, but the collision rule is scoped to
    one program's account, so Eastview Prep's shipment may register its own
    SN-0001 and receive the created unit in RECEIVED status.

    PRD: "Serial numbers must not collide: if another unit bearing the same
    `serial_number` already exists under the same program's account, the
    registration is rejected with `ERR_SERIAL_DUPLICATE` (HTTP 409)."

    Design: Corner/validations/the_same_serial_under_a_different_account_is_accepted
    """
    ctx = setup_counted_shipment(unit_count=1)
    other_account = create_account(
        org_name="Eastview Prep", contact_email="ad@eastview.example"
    )
    other_shipment = _open_counted_shipment(other_account["id"], 1, 1)

    response = api_client.create_equipment_unit(
        create_equipment_unit_payload(other_shipment["id"], serial_number="SN-0001"),
        INTAKE_CLERK,
    )
    unit = validate_success(response, 201)
    assert_equipment_unit(unit)
    assert unit["serial_number"] == "SN-0001"
    assert unit["intake_shipment_id"] == other_shipment["id"]
    assert unit["recon_status"] == "RECEIVED"
    assert unit["custody_status"] == "AT_PLANT"
    assert unit["version"] == 1

    assert read_shipment(other_shipment["id"])["units_registered"] == 1
    assert read_shipment(ctx["shipment"]["id"])["units_registered"] == 1


def test_a_second_inspection_for_the_same_component_is_rejected():
    """A recorded measurement is evidence, not a draft, so it cannot be redone.

    The model requires both a SHELL and a LINER inspection, so after the single
    SHELL measurement at 1.50 mm the unit is still open for inspection in
    DISASSEMBLED status. Re-measuring SHELL at 5.00 mm must therefore come back
    as ERR_DUPLICATE_INSPECTION rather than overwrite the recorded PASS verdict,
    and the unit must still carry exactly one inspection.

    PRD: "At most one inspection may exist per component code per unit; a second
    attempt on a code the unit already carries is rejected with
    `ERR_DUPLICATE_INSPECTION` (HTTP 409)"

    Design: Corner/validations/a_second_inspection_for_the_same_component_rejected
    """
    ctx = setup_accepted_shipment(
        unit_count=1, model_overrides=_two_component_model_overrides()
    )
    unit_id = ctx["unit"]["id"]
    identify_unit(unit_id, ctx["model"]["id"])
    disassemble_unit(unit_id)
    first = inspect_component(unit_id, component_code="SHELL", measurement_value=1.50)
    assert first["verdict"] == "PASS"

    response = api_client.create_component_inspection(
        unit_id,
        create_inspection_payload(
            component_code="SHELL", measurement_value=5.00, note="second look"
        ),
        TECHNICIAN_1,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_INSPECTION.value, 409)

    rows, meta = validate_paginated(
        api_client.list_component_inspections(unit_id, TECHNICIAN_1)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["component_code"] == "SHELL"
    assert rows[0]["measurement_value"] == 1.50
    assert rows[0]["verdict"] == "PASS"

    unit = read_unit(unit_id)
    assert unit["recon_status"] == "DISASSEMBLED"
    assert unit["inspection_verdict_summary"] == "PENDING"
    assert unit["condemn_required"] is False

"""Version stamping and stale-read rejection on the two write operations that
consume a client-supplied `expected_equipment_unit_version`: issuing a
recertification label and creating a repair order.
"""
from test_helpers import (
    INSPECTOR_1,
    REPAIR_IMPACTS,
    TECHNICIAN_1,
    TECHNICIAN_1_USER_ID,
    ApiErrorId,
    assert_repair_order,
    create_bench,
    create_certification_label_payload,
    create_repair_order_payload,
    determine,
    disassemble_unit,
    identify_unit,
    inspect_component,
    read_shipment,
    read_unit,
    record_impacts,
    schedule_shell_test,
    setup_accepted_shipment,
    setup_tested_units,
    unit_version,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_label_issue_with_a_stale_unit_version_is_rejected(api):
    """A label issued on the version read before the signature is refused.

    The requirements state: "Issuing a recertification label requires
    `expected_equipment_unit_version` as a mandatory, non-optional field of the
    request body, carrying the `version` of the target `EquipmentUnit` as the
    inspector last observed it. If that value does not equal the unit's current
    `version`, the issue is rejected with `ERR_STALE_UNIT_VERSION` and HTTP 412."
    Signing the determination "advances the session `COMPLETED → DETERMINED`,
    advances its `version` by one" and advances the unit's version too, so the
    inspector's earlier reading is one behind. Every other precondition is
    satisfied at that point, so the expected error id is ERR_STALE_UNIT_VERSION
    and no label may be created.

    Design: Corner/complexity_layers/label_issue_with_a_stale_unit_version_is_rejected
    """
    ctx = setup_tested_units(unit_count=1)
    unit_id = ctx["unit"]["id"]

    stale_version = unit_version(unit_id, INSPECTOR_1)
    assert stale_version == 5

    determine(ctx["shell_test"]["id"], "PASS")
    signed_unit = read_unit(unit_id)
    assert signed_unit["version"] == 6
    assert signed_unit["recon_status"] == "TEST_PASSED"
    assert signed_unit["condemn_required"] is False

    response = api.create_certification_label(
        create_certification_label_payload(unit_id, stale_version), INSPECTOR_1
    )
    validate_error(response, ApiErrorId.ERR_STALE_UNIT_VERSION.value, 412)

    unit = read_unit(unit_id)
    assert unit["version"] == 6
    assert unit["recon_status"] == "TEST_PASSED"
    assert unit["certified_at"] is None
    assert unit["record_retention_until"] is None

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["units_in_process"] == 1
    assert shipment["units_certified"] == 0

    labels, meta = validate_paginated(
        api.list_unit_certification_labels(unit_id, INSPECTOR_1)
    )
    assert meta["total_count"] == 0
    assert labels == []


def test_repair_order_create_with_a_stale_unit_version_is_rejected(api):
    """A repair order opened on the pre-signature version is refused.

    The requirements state: "Creating a repair order likewise requires
    `expected_equipment_unit_version` as a mandatory field carrying the
    technician's last observed `version` of the unit. A mismatch against the
    unit's current `version` is rejected with `ERR_STALE_UNIT_VERSION` and HTTP
    412." A REPAIR determination "advances the unit `TESTED → REPAIR_PENDING`"
    and advances the unit's version by one, so the technician's reading taken
    before the signature is stale. The expected error id is
    ERR_STALE_UNIT_VERSION, and a rejected create must leave no order behind and
    must not bump the unit again.

    Design: Corner/complexity_layers/repair_order_create_with_a_stale_unit_version_is_rejected
    """
    ctx = setup_tested_units(unit_count=1, impacts=REPAIR_IMPACTS)
    unit_id = ctx["unit"]["id"]

    stale_version = unit_version(unit_id, TECHNICIAN_1)
    assert stale_version == 5

    determine(ctx["shell_test"]["id"], "REPAIR")
    signed_unit = read_unit(unit_id)
    assert signed_unit["version"] == 6
    assert signed_unit["recon_status"] == "REPAIR_PENDING"

    response = api.create_repair_order(
        create_repair_order_payload(unit_id, stale_version), TECHNICIAN_1
    )
    validate_error(response, ApiErrorId.ERR_STALE_UNIT_VERSION.value, 412)

    unit = read_unit(unit_id)
    assert unit["version"] == 6
    assert unit["recon_status"] == "REPAIR_PENDING"

    orders, meta = validate_paginated(
        api.list_repair_orders(TECHNICIAN_1, params={"equipment_unit_id": unit_id})
    )
    assert meta["total_count"] == 0
    assert orders == []


def test_the_correct_unit_version_is_accepted_and_advances_the_counter(api):
    """Each write moves the unit's version by exactly one and reads move it not at all.

    The requirements state: "Most resources additionally carry an `updated_at`
    timestamp in the same format and an integer `version` that starts at 1 when
    the resource is created and increases by exactly one on every mutation that
    changes the row." Identification "advances the unit `RECEIVED → IDENTIFIED`,
    advances its `version` by one"; teardown "advances the unit `IDENTIFIED →
    DISASSEMBLED` and advances its `version` by one"; "the unit's `version`
    advances by one on each recorded inspection"; recording impacts "advances both
    the session's and the unit's `version` by one"; all three determination
    branches "advance the unit's `version` by one"; and on a repair-order create
    "`opened_by_user_id` records the acting `X-User-ID`, and the unit's `version`
    advances by one." Submitting the version the technician just read therefore
    succeeds and leaves the unit one higher.

    Design: Corner/complexity_layers/the_correct_unit_version_is_accepted_and_advances_the_counter
    """
    ctx = setup_accepted_shipment(unit_count=1)
    unit_id = ctx["unit"]["id"]
    model_id = ctx["model"]["id"]

    assert read_unit(unit_id, TECHNICIAN_1)["version"] == 1

    identify_unit(unit_id, model_id)
    assert read_unit(unit_id, TECHNICIAN_1)["version"] == 2

    disassemble_unit(unit_id)
    assert read_unit(unit_id, TECHNICIAN_1)["version"] == 3

    inspect_component(unit_id)
    assert read_unit(unit_id, TECHNICIAN_1)["version"] == 4

    bench = create_bench()
    session = schedule_shell_test(unit_id, bench["id"])
    record_impacts(session["id"], REPAIR_IMPACTS)
    assert read_unit(unit_id, TECHNICIAN_1)["version"] == 5

    determine(session["id"], "REPAIR")
    observed_version = unit_version(unit_id, TECHNICIAN_1)
    assert observed_version == 6

    response = api.create_repair_order(
        create_repair_order_payload(unit_id, observed_version), TECHNICIAN_1
    )
    order = validate_success(response, 201)
    assert_repair_order(order)
    assert order["equipment_unit_id"] == unit_id
    assert order["status"] == "DRAFT"
    assert order["version"] == 1
    assert order["opened_by_user_id"] == TECHNICIAN_1_USER_ID
    assert order["part_lines"] == []
    assert order["reserved_parts_cents"] == 0
    assert order["installed_parts_cents"] == 0
    assert order["labor_cents"] == 0
    assert order["verification_failure_count"] == 0
    assert order["warranty_claim_ref"] is None
    assert order["installed_by_user_id"] is None
    assert order["verified_by_user_id"] is None
    assert order["cancel_reason"] is None

    assert read_unit(unit_id, TECHNICIAN_1)["version"] == 7

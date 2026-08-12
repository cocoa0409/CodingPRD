"""Catalog / entity creation and defaults (PRD §3.1, §3.2, §3.3)."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    ADMIN,
    ANY,
    ApiErrorId,
    TECH,
    assert_employee,
    assert_item,
    assert_manager_override,
    assert_serialized_unit,
    assert_slot,
    create_cost_center_payload,
    create_employee_payload,
    create_item_payload,
    create_job_role_payload,
    create_machine_payload,
    create_manager_override_payload,
    create_serialized_unit_payload,
    create_slot_payload,
    setup_cost_center,
    setup_item,
    setup_job_role,
    setup_machine,
    setup_manager,
    setup_employee,
    setup_slot_for_machine,
    make_manager_headers,
)


def test_employee_creation_applies_defaults(api):
    """PRD §3.2: "an optional `is_manager` flag defaulting to false — the gate
    that lets an Employee-backed identity act in the `Manager` role. New
    employees start `ACTIVE` with an empty `fit_tests` list."

    Design: Corner/entities/employee_creation_applies_defaults
    """
    cc = setup_cost_center(code="CC-EN1", name="Admin")
    role = setup_job_role(role_name="CLERK-EN")
    resp = api.create_employee(
        create_employee_payload(
            employee_code="E-EN1",
            full_name="Clerk One",
            job_role_id=role["id"],
            home_cost_center_id=cc["id"],
        ),
        ADMIN,
    )
    emp = validate_success(resp, 201)
    assert_employee(emp)
    assert emp["is_manager"] is False
    assert emp["status"] == "ACTIVE"
    assert emp["fit_tests"] == []
    assert emp["version"] == 1


def test_item_computed_flags_by_category(api):
    """PRD §3.1: "Two behavioral flags derive from `category` at creation, and
    any client-supplied value for them is ignored: `requires_fit_test` is true
    exactly when the item is a `RESPIRATOR`, and `serialized_tracking` is true
    exactly when the item is `FALL_PROTECTION`. Fall-protection items
    additionally require `inspection_interval_days`, a positive integer that
    drives the regulated inspection cycle of §3.3; for any other category the
    field stays null."

    Design: Corner/entities/item_computed_flags_by_category
    """
    general = validate_success(
        api.create_item(
            create_item_payload(sku="EN-GEN", name="Gloves", category="GENERAL",
                                base_list_price_cents=100),
            ADMIN,
        ),
        201,
    )
    respirator = validate_success(
        api.create_item(
            create_item_payload(sku="EN-RSP", name="Respirator", category="RESPIRATOR",
                                base_list_price_cents=100),
            ADMIN,
        ),
        201,
    )
    fall = validate_success(
        api.create_item(
            create_item_payload(sku="EN-FP", name="Harness", category="FALL_PROTECTION",
                                base_list_price_cents=100, inspection_interval_days=90),
            ADMIN,
        ),
        201,
    )
    assert_item(general)
    assert general["requires_fit_test"] is False
    assert general["serialized_tracking"] is False

    assert_item(respirator)
    assert respirator["requires_fit_test"] is True
    assert respirator["serialized_tracking"] is False

    assert_item(fall)
    assert fall["requires_fit_test"] is False
    assert fall["serialized_tracking"] is True

    bad_resp = api.create_item(
        create_item_payload(sku="EN-FPBAD", name="Harness NoInterval",
                            category="FALL_PROTECTION", base_list_price_cents=100),
        ADMIN,
    )
    validate_error(bad_resp, ApiErrorId.ERR_VALIDATION_FAILED)


def test_slot_code_unique_per_machine(api):
    """PRD §3.3: "The `slot_code` must be unique within its machine
    (`ERR_DUPLICATE_SLOT_CODE`)".

    Design: Corner/entities/slot_code_unique_per_machine
    """
    item = setup_item(sku="EN-SC", base_list_price_cents=100)
    m1 = setup_machine(location_code="LOC-EN-S1", site_name="P1", model="VM-1")
    m2 = setup_machine(location_code="LOC-EN-S2", site_name="P2", model="VM-1")

    slot1 = setup_slot_for_machine(m1, item_id=item["id"], capacity=10, par_level=2,
                                   slot_code="A1")
    assert_slot(slot1)

    m1_now = get_success_data(api.get_machine(m1["id"], ANY))
    dup_resp = api.create_slot(
        m1["id"],
        create_slot_payload(slot_code="A1", item_id=item["id"], capacity=10,
                            par_level=2,
                            expected_machine_version=m1_now["version"]),
        TECH,
    )
    validate_error(dup_resp, ApiErrorId.ERR_DUPLICATE_SLOT_CODE)

    slot2_resp = api.create_slot(
        m2["id"],
        create_slot_payload(slot_code="A1", item_id=item["id"], capacity=10,
                            par_level=2,
                            expected_machine_version=m2["version"]),
        TECH,
    )
    slot2 = validate_success(slot2_resp, 201)
    assert_slot(slot2)
    assert slot2["slot_code"] == "A1"

    list_resp = api.list_machine_slots(m2["id"], ANY)
    data, meta = get_success_data(list_resp), None
    assert len(data) == 1
    assert data[0]["slot_code"] == "A1"


def test_machine_not_found_returns_404(api):
    """PRD §2.7: "After path identifiers, the foreign keys in the request body
    (`machine_id`, `slot_id`, `item_id`, `job_role_id`, `home_cost_center_id`,
    `employee_id`, `serialized_unit_id`, `manager_override_id`) are resolved,
    and any miss produces the resource-specific 404".

    Design: Corner/entities/machine_not_found_returns_404
    """
    # Ensure at least one machine exists so the collection is initialized.
    setup_machine(location_code="LOC-EN-NF", site_name="P3", model="VM-1")

    resp = api.get_machine("11111111-2222-4333-8444-555555555555", ANY)
    validate_error(resp, ApiErrorId.ERR_MACHINE_NOT_FOUND)


def test_manager_override_remaining_qty_computed(api):
    """PRD §3.5: "New grants start `ACTIVE` with `consumed_qty` at zero and
    `remaining_qty` reading `approved_qty` minus `consumed_qty`."
    PRD §3.5: "The granting identity is captured as `granted_by_user_id` from
    the header, and segregation of duties forbids granting to oneself".

    Design: Corner/entities/manager_override_remaining_qty_computed
    """
    cc = setup_cost_center(code="CC-EN2", name="Ops")
    role = setup_job_role(role_name="TECH-EN")
    item = setup_item(sku="EN-MO", base_list_price_cents=100)
    emp, _ = setup_employee(role["id"], cc["id"], employee_code="E-EN2",
                            full_name="Tech One")
    mgr, mgr_headers = setup_manager(role["id"], cc["id"], employee_code="M-EN2",
                                     full_name="Mgr EN")

    resp = api.create_manager_override(
        create_manager_override_payload(
            employee_id=emp["id"],
            item_id=item["id"],
            approved_qty=5,
            valid_from="2026-05-01",
            valid_until="2026-05-31",
            reason_code="NEW_HIRE",
        ),
        mgr_headers,
    )
    ov = validate_success(resp, 201)
    assert_manager_override(ov)
    assert ov["consumed_qty"] == 0
    assert ov["remaining_qty"] == 5
    assert ov["granted_by_user_id"] == mgr["id"]
    assert ov["status"] == "ACTIVE"


def test_serialized_unit_registration_bumps_on_hand(api):
    """PRD §3.3: "An `EHSAdministrator` registers each unit with its `item_id`
    — which must belong to a `FALL_PROTECTION` item, otherwise
    `ERR_ITEM_NOT_SERIALIZED_CATEGORY` — a globally unique `serial_number`
    (`ERR_DUPLICATE_SERIAL_NUMBER` on collision), and the `slot_id` it
    physically sits in."
    PRD §3.3: "Registration requires the machine to be `COMMISSIONING` or
    `ACTIVE` (`ERR_MACHINE_NOT_ACTIVE`) and the item to be `ACTIVE`, starts
    the unit `IN_STOCK`, and raises the slot's `on_hand_qty` by one, which
    may not push it past `capacity` (`ERR_CAPACITY_EXCEEDED`)."

    Design: Corner/entities/serialized_unit_registration_bumps_on_hand
    """
    fp_item = setup_item(sku="EN-SU", name="Lanyard", category="FALL_PROTECTION",
                         base_list_price_cents=5000, inspection_interval_days=90)
    g_item = setup_item(sku="EN-SUG", name="Gloves", category="GENERAL",
                        base_list_price_cents=100)
    machine = setup_machine(location_code="LOC-EN-SU", site_name="P4", model="VM-1")
    fp_slot = setup_slot_for_machine(machine, item_id=fp_item["id"], capacity=4,
                                     par_level=0, slot_code="H1")
    g_slot = setup_slot_for_machine(machine, item_id=g_item["id"], capacity=10,
                                    par_level=0, slot_code="G1")

    unit_resp = api.create_serialized_unit(
        create_serialized_unit_payload(
            item_id=fp_item["id"], serial_number="SN-EN-001", slot_id=fp_slot["id"]
        ),
        ADMIN,
    )
    unit = validate_success(unit_resp, 201)
    assert_serialized_unit(unit)
    assert unit["status"] == "IN_STOCK"

    slot_now = get_success_data(api.get_slot(fp_slot["id"], ANY))
    assert slot_now["on_hand_qty"] == 1, "registration bumps on_hand_qty by 1"

    bad_resp = api.create_serialized_unit(
        create_serialized_unit_payload(
            item_id=g_item["id"], serial_number="SN-EN-002", slot_id=g_slot["id"]
        ),
        ADMIN,
    )
    validate_error(bad_resp, ApiErrorId.ERR_ITEM_NOT_SERIALIZED_CATEGORY)

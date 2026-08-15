"""Entity creation defaults, not-found family, FK integrity, append-only resources."""
import pytest

from test_helpers import (
    ApiErrorId,
    BOGUS_UUID,
    CLOCK_T0800,
    api_client,
    assert_instant_equal,
    create_bed_payload,
    create_clean_request_payload,
    create_maintenance_window_payload,
    create_outbreak_event_payload,
    create_placement_demand_payload,
    create_quality_audit_payload,
    create_staff_payload,
    create_supply_item_payload,
    create_unit_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_auditor_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
IP = TEST_USERS["ip_headers"]
ANY = TEST_USERS["any_headers"]


def test_not_found_family_covers_all_twelve_resources(api):
    """PRD §2.5: "the request is rejected with the 404 error corresponding to
    the first identifier that does not resolve: `ERR_UNIT_NOT_FOUND`,
    `ERR_BED_NOT_FOUND`, `ERR_CLEAN_REQUEST_NOT_FOUND`,
    `ERR_PLACEMENT_DEMAND_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`,
    `ERR_AUDIT_NOT_FOUND`, `ERR_SUPPLY_ITEM_NOT_FOUND`,
    `ERR_OUTBREAK_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`,
    `ERR_STANDARD_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, or
    `ERR_SNAPSHOT_NOT_FOUND`."

    Design: Corner/entities/not_found_family_covers_all_twelve_resources
    """
    set_clock(CLOCK_T0800)
    cases = [
        (api.get_unit(BOGUS_UUID, ANY), ApiErrorId.ERR_UNIT_NOT_FOUND),
        (api.get_bed(BOGUS_UUID, ANY), ApiErrorId.ERR_BED_NOT_FOUND),
        (
            api.get_clean_request(BOGUS_UUID, ANY),
            ApiErrorId.ERR_CLEAN_REQUEST_NOT_FOUND,
        ),
        (
            api.get_placement_demand(BOGUS_UUID, ANY),
            ApiErrorId.ERR_PLACEMENT_DEMAND_NOT_FOUND,
        ),
        (api.get_staff(BOGUS_UUID, ANY), ApiErrorId.ERR_STAFF_NOT_FOUND),
        (api.get_quality_audit(BOGUS_UUID, ANY), ApiErrorId.ERR_AUDIT_NOT_FOUND),
        (
            api.get_supply_item(BOGUS_UUID, ANY),
            ApiErrorId.ERR_SUPPLY_ITEM_NOT_FOUND,
        ),
        (
            api.get_outbreak_event(BOGUS_UUID, ANY),
            ApiErrorId.ERR_OUTBREAK_NOT_FOUND,
        ),
        (
            api.get_bed_ready_notification(BOGUS_UUID, ANY),
            ApiErrorId.ERR_NOTIFICATION_NOT_FOUND,
        ),
        (
            api.get_maintenance_window(BOGUS_UUID, ANY),
            ApiErrorId.ERR_WINDOW_NOT_FOUND,
        ),
        (
            api.get_turnaround_snapshot(BOGUS_UUID, ANY),
            ApiErrorId.ERR_SNAPSHOT_NOT_FOUND,
        ),
        (
            api.get_clean_standard("ROUTINE", ANY),
            ApiErrorId.ERR_STANDARD_NOT_FOUND,
        ),
    ]
    for resp, expected in cases:
        validate_error(resp, expected)


def test_create_with_unknown_body_fk_returns_parent_not_found(api):
    """PRD §2.5: "Identifiers carried in the request body — such as `staff_id`,
    `clean_request_id`, `bed_id`, `unit_id`, or item ids — are validated after
    the path identifiers."

    Design: Corner/entities/create_with_unknown_body_fk_returns_parent_not_found
    """
    set_clock(CLOCK_T0800)
    # ROUTINE standard must exist so only the bed FK fails for clean requests.
    get_success_data(
        api.create_clean_standard(
            {
                "clean_type": "ROUTINE",
                "base_minutes": 45,
                "outbreak_multiplier_bps": 15000,
                "atp_rlu_threshold": 250,
            },
            ADMIN,
        )
    )
    auditor = get_success_data(
        api.create_staff(
            create_staff_payload(
                employee_code="A1", display_name="Auditor One", capabilities=["AUDIT"]
            ),
            ADMIN,
        )
    )

    r = api.create_bed(
        create_bed_payload(unit_id=BOGUS_UUID, bed_code="B1", bed_kind="STANDARD"),
        ADMIN,
    )
    validate_error(r, ApiErrorId.ERR_UNIT_NOT_FOUND)

    r = api.create_clean_request(
        create_clean_request_payload(bed_id=BOGUS_UUID, clean_type="ROUTINE"),
        DISPATCHER,
    )
    validate_error(r, ApiErrorId.ERR_BED_NOT_FOUND)

    r = api.create_placement_demand(
        create_placement_demand_payload(unit_id=BOGUS_UUID), COORDINATOR
    )
    validate_error(r, ApiErrorId.ERR_UNIT_NOT_FOUND)

    r = api.create_maintenance_window(
        create_maintenance_window_payload(bed_id=BOGUS_UUID), ADMIN
    )
    validate_error(r, ApiErrorId.ERR_BED_NOT_FOUND)

    r = api.create_outbreak_event(
        create_outbreak_event_payload(unit_id=BOGUS_UUID, pathogen_class="MRSA"), IP
    )
    validate_error(r, ApiErrorId.ERR_UNIT_NOT_FOUND)

    r = api.create_quality_audit(
        create_quality_audit_payload(clean_request_id=BOGUS_UUID, rlu_reading=100),
        make_auditor_headers(auditor["id"]),
    )
    validate_error(r, ApiErrorId.ERR_CLEAN_REQUEST_NOT_FOUND)

    beds, beds_meta = validate_paginated(api.list_beds(ANY))
    assert beds == [], f"no beds may persist from rejected creates, got {beds}"
    reqs, _ = validate_paginated(api.list_clean_requests(ANY))
    assert reqs == [], f"no clean requests may persist from rejected creates, got {reqs}"


def test_unit_create_applies_defaults_and_system_fields(api):
    """PRD §3.1: "Each unit carries an `outbreak_posture`, which starts at
    `NORMAL` and reads `OUTBREAK` exactly while the unit has at least one
    outbreak event in `ACTIVE` status — it is recomputed whenever an outbreak
    is activated or lifted, never set directly. Each unit also carries an
    `ops_run_index`, a monotonic ops-run epoch that starts at 0 and increments
    by 1 on each ops-run executed for the unit."

    Design: Corner/entities/unit_create_applies_defaults_and_system_fields
    """
    set_clock(CLOCK_T0800)
    unit = validate_success(api.create_unit(create_unit_payload(), ADMIN), 201)
    assert unit["outbreak_posture"] == "NORMAL"
    assert unit["ops_run_index"] == 0
    assert unit["version"] == 1
    assert_instant_equal(unit["created_at"], CLOCK_T0800)
    assert is_valid_uuid(unit["id"])
    assert is_iso8601_timestamp(unit["updated_at"])

    fetched = validate_success(api.get_unit(unit["id"], ANY))
    assert fetched["outbreak_posture"] == "NORMAL"
    assert fetched["ops_run_index"] == 0
    assert_instant_equal(fetched["created_at"], CLOCK_T0800)
    assert fetched["updated_at"] == fetched["created_at"]


def test_staff_create_required_fields_and_enum_membership(api):
    """PRD §3.4: "The workforce is a registry of **staff members**, each created
    by an administrator with a facility-unique `employee_code`, a
    `display_name`, a non-empty `capabilities` list drawn from `CLEAN` and
    `AUDIT`, and an optional `certifications` list drawn from `ISO_CERT` and
    `TERMINAL_CERT` that defaults to empty. ... A new staff member is
    `OFF_SHIFT` with all counters zeroed."
    PRD §3.6: "`stat_eligible` holds when the technician has no verified cleans
    yet (`completed_clean_count` is zero) or when `productivity_score` has
    reached at least 80.00."

    Design: Corner/entities/staff_create_required_fields_and_enum_membership
    """
    set_clock(CLOCK_T0800)
    r_missing = api.create_staff(
        {"employee_code": "T1", "display_name": "Tech One"}, ADMIN
    )
    validate_error(r_missing, ApiErrorId.ERR_INVALID_REQUEST)

    r_enum = api.create_staff(
        {
            "employee_code": "T2",
            "display_name": "Tech Two",
            "capabilities": ["CLEAN", "SCRUB"],
        },
        ADMIN,
    )
    validate_error(r_enum, ApiErrorId.ERR_INVALID_REQUEST)

    staff = validate_success(
        api.create_staff(
            {
                "employee_code": "T3",
                "display_name": "Tech Three",
                "capabilities": ["CLEAN"],
            },
            ADMIN,
        ),
        201,
    )
    assert staff["certifications"] == []
    assert staff["shift_status"] == "OFF_SHIFT"
    assert staff["active_clean_count"] == 0
    assert staff["completed_clean_count"] == 0
    assert staff["qa_fail_count"] == 0
    assert staff["verified_credit_total"] == 0
    assert staff["shift_seconds_today"] == 0
    assert staff["stat_eligible"] is True

    listed, meta = validate_paginated(api.list_staff(ANY))
    assert len(listed) == 1
    assert meta["total_count"] == 1


def test_supply_item_create_enum_range_and_opening_ledger(api):
    """PRD §3.1: "**Supply items** are registered with an `item_code` — one of
    `DISINFECTANT`, `PPE_PACK`, `CLOTH`, or `SEALANT`, unique across the
    facility — a `display_name`, an opening `initial_on_hand`, and a
    `reorder_threshold` that must be zero or greater. Registration writes a
    `RESTOCK` ledger entry for the opening quantity, so on-hand stock is
    ledger-derived from the first moment (§2.9)."
    PRD §2.9: "an item's `stock_status` reads `LOW` whenever its
    `on_hand_quantity` has fallen to or below its `reorder_threshold`, and
    `STOCKED` otherwise."

    Design: Corner/entities/supply_item_create_enum_range_and_opening_ledger
    """
    set_clock(CLOCK_T0800)
    r_enum = api.create_supply_item(
        create_supply_item_payload(
            item_code="BLEACH", initial_on_hand=10, reorder_threshold=2
        ),
        ADMIN,
    )
    validate_error(r_enum, ApiErrorId.ERR_INVALID_REQUEST)

    r_range = api.create_supply_item(
        create_supply_item_payload(initial_on_hand=10, reorder_threshold=-1), ADMIN
    )
    validate_error(r_range, ApiErrorId.ERR_INVALID_REQUEST)

    item = validate_success(
        api.create_supply_item(
            create_supply_item_payload(initial_on_hand=50, reorder_threshold=10),
            ADMIN,
        ),
        201,
    )
    assert item["on_hand_quantity"] == 50
    assert item["reserved_quantity"] == 0
    assert item["stock_status"] == "STOCKED"

    entries, meta = validate_paginated(
        api.list_supply_ledger_entries(ANY, params={"supply_item_id": item["id"]})
    )
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entry_type"] == "RESTOCK"
    assert entry["quantity_delta"] == 50
    assert entry["clean_request_id"] is None

    items, items_meta = validate_paginated(api.list_supply_items(ANY))
    assert len(items) == 1
    assert items_meta["total_count"] == 1


def test_outbreak_create_defaults_declared_state(api):
    """PRD §3.8: "An `InfectionPreventionist` declares one with the affected
    `unit_id`, a `pathogen_class` of `C_DIFF`, `MRSA`, `NOROVIRUS`, or `OTHER`,
    and an optional free-text `declared_reason`; a new event is `DECLARED`."
    PRD §3.1: "Each unit carries an `outbreak_posture`, which starts at
    `NORMAL` and reads `OUTBREAK` exactly while the unit has at least one
    outbreak event in `ACTIVE` status."

    Design: Corner/entities/outbreak_create_defaults_declared_state
    """
    set_clock(CLOCK_T0800)
    unit = get_success_data(api.create_unit(create_unit_payload(), ADMIN))
    event = validate_success(
        api.create_outbreak_event(
            create_outbreak_event_payload(unit_id=unit["id"], pathogen_class="C_DIFF"),
            IP,
        ),
        201,
    )
    assert event["status"] == "DECLARED"
    assert event["declared_reason"] is None
    assert event["activated_at"] is None
    assert event["lifted_at"] is None
    assert event["version"] == 1

    fetched_unit = validate_success(api.get_unit(unit["id"], ANY))
    assert fetched_unit["outbreak_posture"] == "NORMAL"


def test_supply_ledger_entry_append_only_immutable(api):
    """PRD §2.5: "Two resources are append-only exceptions. A
    `SupplyLedgerEntry` and a `TurnaroundSnapshot` each carry only `id` and
    `created_at`; both `updated_at` and `version` are absent from them, neither
    has any update endpoint, and neither is ever modified after creation."

    Design: Corner/entities/supply_ledger_entry_append_only_immutable
    """
    set_clock(CLOCK_T0800)
    item = get_success_data(
        api.create_supply_item(
            create_supply_item_payload(
                item_code="PPE_PACK",
                display_name="PPE packs",
                initial_on_hand=25,
                reorder_threshold=8,
            ),
            ADMIN,
        )
    )
    entries, _ = validate_paginated(
        api.list_supply_ledger_entries(ANY, params={"supply_item_id": item["id"]})
    )
    assert len(entries) == 1
    entry_id = entries[0]["id"]

    entry = validate_success(api.get_supply_ledger_entry(entry_id, ANY))
    assert entry["entry_type"] == "RESTOCK"
    assert entry["quantity_delta"] == 25
    assert entry["clean_request_id"] is None
    assert "version" not in entry, "append-only ledger entry must not carry version"
    assert "updated_at" not in entry, "append-only ledger entry must not carry updated_at"
    assert_instant_equal(entry["created_at"], CLOCK_T0800)

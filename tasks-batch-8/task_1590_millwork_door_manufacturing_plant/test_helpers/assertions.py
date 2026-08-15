"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_project(data: dict):
    _assert_common(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("site_address"), str)
    assert isinstance(data.get("contract_code"), str) and data["contract_code"]
    assert data.get("status") in ("OPEN", "COMPLETED", "ARCHIVED")


def assert_hardware_template(data: dict):
    _assert_common(data)
    assert isinstance(data.get("template_code"), str) and data["template_code"]
    assert isinstance(data.get("manufacturer"), str)
    assert isinstance(data.get("fire_rated_compatible"), bool)


def assert_moulder_machine(data: dict):
    _assert_common(data)
    assert isinstance(data.get("machine_code"), str) and data["machine_code"]
    assert isinstance(data.get("supported_species"), list)
    assert isinstance(data.get("active"), bool)


def assert_spray_booth(data: dict):
    _assert_common(data)
    assert isinstance(data.get("booth_code"), str) and data["booth_code"]
    assert isinstance(data.get("capacity"), int) and data["capacity"] >= 1


def assert_fire_label_roll(data: dict):
    _assert_common(data)
    assert data.get("label_series") in ("UL_20MIN", "UL_45MIN", "UL_90MIN")
    assert isinstance(data.get("serial_capacity"), int) and data["serial_capacity"] >= 0
    for f in ("serials_issued", "serials_applied", "serials_spoiled", "serials_available"):
        assert isinstance(data.get(f), int) and data[f] >= 0, f"{f} must be a non-negative integer"
    assert data.get("status") in ("ACTIVE", "DEPLETED", "RETIRED")


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data.get("order_code"), str) and data["order_code"]
    assert data.get("species") in ("OAK", "MAPLE", "CHERRY", "WALNUT", "PAINT_GRADE")
    assert isinstance(data.get("profile_code"), str)
    assert data.get("finish_system") in ("CLEAR_COAT", "STAIN", "PAINT")
    assert data.get("sheen_target") in ("MATTE", "SATIN", "SEMI_GLOSS", "HIGH_GLOSS")
    assert data.get("hardware_prep_mode") in ("TEMPLATE_PREP", "INSTALLER_PREP")
    assert data.get("fire_rating_required") in ("NONE", "MIN_20", "MIN_45", "MIN_90")
    assert isinstance(data.get("config_locked"), bool)
    assert data.get("status") in (
        "DRAFT", "CONFIGURED", "SUBMITTED", "APPROVED", "IN_PRODUCTION",
        "FINISHING", "READY_TO_SHIP", "SHIPPED", "CLOSED", "CANCELLED",
    )


def assert_opening(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data.get("opening_no"), str) and data["opening_no"]
    assert data.get("width_in") is not None and data.get("height_in") is not None
    assert isinstance(data.get("leaf_count"), int) and data["leaf_count"] >= 1
    assert data.get("fire_rating") in ("NONE", "MIN_20", "MIN_45", "MIN_90")
    assert isinstance(data.get("required_on_site_date"), str)
    assert data.get("fab_status") in (
        "QUEUED", "MACHINED", "FINISHED", "LABELED", "STAGED", "REWORK", "CANCELLED",
    )
    assert data.get("ship_status") in (
        "UNSCHEDULED", "SCHEDULED", "SHIPPED", "DELIVERED", "PUNCH_LISTED", "ACCEPTED", "CANCELLED",
    )


def assert_shop_drawing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data.get("revision_no"), int) and data["revision_no"] >= 1
    for f in ("pinned_species", "pinned_profile_code", "pinned_sheen_target",
              "pinned_fire_rating_required", "pinned_hardware_prep_mode"):
        assert data.get(f) is not None, f"{f} must be pinned at creation"
    assert data.get("status") in (
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED", "VOID",
    )


def assert_machining_program(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("drawing_id", ""))
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data.get("program_code"), str) and data["program_code"]
    assert isinstance(data.get("estimated_minutes"), int)
    assert data.get("status") in ("CREATED", "SETUP_BOOKED", "PROVEN", "RELEASED", "VOIDED")


def assert_moulder_setup_slot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("machine_id", ""))
    assert isinstance(data.get("start_hour"), int)
    assert isinstance(data.get("end_hour"), int)
    assert data["end_hour"] > data["start_hour"]
    assert data.get("status") in ("BOOKED", "COMPLETED", "CANCELLED")


def assert_finishing_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("booth_id", ""))
    assert data.get("finish_family") in ("PAINT", "CLEAR_STAIN")
    assert isinstance(data.get("cure_start_hour"), int)
    assert isinstance(data.get("cure_end_hour"), int)
    assert data["cure_end_hour"] - data["cure_start_hour"] >= 4
    assert isinstance(data.get("sheen_target_gu"), int)
    assert data.get("status") in ("MIXED", "SPRAYED", "CURED", "PASSED", "FAILED")


def assert_label_allocation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("opening_id", ""))
    assert is_valid_uuid(data.get("roll_id", ""))
    assert isinstance(data.get("serial_count"), int) and data["serial_count"] >= 1
    assert isinstance(data.get("issued_by"), str) and data["issued_by"]
    assert data.get("status") in ("ISSUED", "APPLIED", "VERIFIED", "VOIDED")


def assert_delivery_trip(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data.get("trip_code"), str) and data["trip_code"]
    assert isinstance(data.get("truck_capacity_leaves"), int) and data["truck_capacity_leaves"] >= 1
    assert isinstance(data.get("departure_date"), str)
    assert isinstance(data.get("site_arrival_date"), str)
    assert data["site_arrival_date"] >= data["departure_date"]
    assert isinstance(data.get("leaves_committed"), int) and data["leaves_committed"] >= 0
    assert data.get("status") in ("PLANNED", "DEPARTED", "DELIVERED", "CLOSED", "CANCELLED")


def assert_punch_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("opening_id", ""))
    assert data.get("category") in (
        "FINISH_DEFECT", "HARDWARE_MISALIGNMENT", "TRANSIT_DAMAGE", "LABEL_MISSING",
    )
    assert data.get("severity") in ("MINOR", "MAJOR")
    assert isinstance(data.get("description"), str)
    assert isinstance(data.get("reported_by"), str) and data["reported_by"]
    assert data.get("status") in (
        "REPORTED", "TRIAGED", "REWORK_AUTHORIZED", "IN_REWORK",
        "RESOLVED", "VERIFIED", "REJECTED_INVALID",
    )


def assert_roll_serial_conservation(roll: dict):
    """PRD §2.9 conservation invariant: issued + applied + spoiled + available
    always equals serial_capacity; spoiled serials never return."""
    total = (
        roll["serials_issued"] + roll["serials_applied"]
        + roll["serials_spoiled"] + roll["serials_available"]
    )
    assert total == roll["serial_capacity"], (
        f"serial accounting broken: {roll['serials_issued']}+{roll['serials_applied']}"
        f"+{roll['serials_spoiled']}+{roll['serials_available']} != {roll['serial_capacity']}"
    )

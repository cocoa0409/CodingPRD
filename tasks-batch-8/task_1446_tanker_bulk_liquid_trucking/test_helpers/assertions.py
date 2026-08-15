"""Entity assertions and domain invariant checkers (PRD section 2.4)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """PRD 2.4: every resource carries id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["dedicated_program_enrolled"], bool)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["exposure_cents"], int)


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["compatibility_group"] in [
        "PETROLEUM", "SOLVENT", "ACID", "CAUSTIC", "VEG_OIL", "FOOD_GRADE", "LATEX",
    ]
    assert data["hazmat_class"] in ["NONE", "CLASS_3_FLAMMABLE", "CLASS_8_CORROSIVE", "CLASS_6_TOXIC"]
    assert data["packing_group"] in ["NONE", "I", "II", "III"]
    assert isinstance(data["density_lb_per_gal"], (int, float))
    assert isinstance(data["temp_coeff_per_degF"], (int, float))
    assert isinstance(data["placard_code"], str)


def assert_compatibility_rule(data: dict):
    _assert_common(data)
    assert isinstance(data["prior_group"], str)
    assert isinstance(data["next_group"], str)
    assert data["required_wash_level"] in ["NONE", "FLUSH", "DETERGENT_WASH", "CHEMICAL_KOSHER"]
    assert isinstance(data["forbidden"], bool)


def assert_trailer(data: dict):
    _assert_common(data)
    assert isinstance(data["unit_number"], str)
    assert isinstance(data["capacity_gallons"], int)
    assert data["status"] in ["AVAILABLE", "ASSIGNED"]
    for field in ("tare_weight_lb", "tare_steer_lb", "tare_drive_lb", "tare_trailer_lb",
                  "steer_axle_rating_lb", "drive_axle_rating_lb", "trailer_axle_rating_lb",
                  "gvwr_lb"):
        assert isinstance(data[field], int)


def assert_driver(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["cdl_number"], str)
    assert isinstance(data["tanker_endorsement"], bool)
    assert isinstance(data["hazmat_endorsement"], bool)
    assert isinstance(data["endorsement_expires_on"], str)
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_wash_bay(data: dict):
    _assert_common(data)
    assert isinstance(data["bay_code"], str)
    assert isinstance(data["supported_wash_levels"], list)
    assert isinstance(data["cleanup_buffer_minutes"], int)


def assert_wash_certificate(data: dict):
    _assert_common(data)
    assert isinstance(data["trailer_id"], str)
    assert isinstance(data["wash_bay_id"], str)
    assert data["wash_level"] in ["FLUSH", "DETERGENT_WASH", "CHEMICAL_KOSHER"]
    assert data["status"] in ["SCHEDULED", "CERTIFIED", "HELD", "CONSUMED", "VOIDED", "EXPIRED"]


def assert_loading_rack(data: dict):
    _assert_common(data)
    assert isinstance(data["rack_code"], str)
    assert isinstance(data["terminal_name"], str)
    assert isinstance(data["authorized_groups"], list)
    assert isinstance(data["open_hour"], int)
    assert isinstance(data["close_hour"], int)
    assert isinstance(data["meter_id"], str)


def assert_shipment(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["ordered_gallons"], int)
    assert isinstance(data["route_miles"], int)
    assert isinstance(data["rate_per_gal_cents"], int)
    assert data["status"] in [
        "DRAFT", "PLANNED", "LOADING", "LOADED", "IN_TRANSIT", "DELIVERING",
        "DELIVERED", "VARIANCE_REVIEW", "RECONCILED", "CANCELLED",
    ]


def assert_meter_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["shipment_id"], str)
    assert data["status"] in ["OPEN", "CLOSED", "VOIDED"]


def assert_delivery_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["shipment_id"], str)
    assert data["status"] in ["OPEN", "CLOSED_ACCEPTED", "CLOSED_VARIANCE"]


def assert_retain_sample(data: dict):
    _assert_common(data)
    assert isinstance(data["shipment_id"], str)
    assert data["status"] in ["RETAINED", "DISPOSED"]


def assert_spill_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["equipment_checklist"], list)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUSPENDED", "EXPIRED"]


def assert_spill_incident(data: dict):
    _assert_common(data)
    assert isinstance(data["shipment_id"], str)
    assert data["status"] in ["REPORTED", "UNDER_REVIEW", "CLOSED"]
    assert data["severity"] in ["MINOR", "MAJOR", "REPORTABLE"]


def assert_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["trailer_id"], str)
    assert isinstance(data["committed_loads_per_month"], int)
    assert data["status"] in ["PENDING", "ACTIVE", "SUSPENDED", "TERMINATED"]
    assert isinstance(data["flagged_shipment_count"], int)
    assert isinstance(data["shortfall_events"], int)
    assert isinstance(data["shortfall_fees_total_cents"], int)

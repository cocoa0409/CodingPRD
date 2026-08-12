"""Entity assertions and domain invariant checkers (PRD §2.5, §2.10, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity: str):
    """Primary resources share id/created_at/updated_at/version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be a positive integer"


def assert_member(data: dict):
    _assert_common_fields(data, "Member")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["payer_type"] in ("MEDICAID_WAIVER", "MEDICARE_ADVANTAGE")
    assert isinstance(data["payer_member_id"], str)
    assert isinstance(data["allergies"], list)
    assert isinstance(data["income_fpl_percent"], int)
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert data["status"] in ("INTAKE", "ACTIVE", "SUSPENDED", "DISENROLLED")
    assert isinstance(data["adherence_delivered_pct"], (int, float))
    assert isinstance(data["adherence_confirmed_pct"], (int, float))
    assert isinstance(data["oop_accumulator_cents"], int)


def assert_referral(data: dict):
    _assert_common_fields(data, "Referral")
    assert data["status"] in ("SUBMITTED", "TRIAGED", "ACCEPTED", "REJECTED",
                              "EXPIRED", "CONSUMED")
    assert isinstance(data["member_id"], str)
    assert isinstance(data["diagnosis_codes"], list)
    assert data["referred_diet_type"] in ("RENAL", "DIABETIC", "RENAL_DIABETIC", "CARDIAC")


def assert_prescription(data: dict):
    _assert_common_fields(data, "DietPrescription")
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED", "REVOKED")
    assert data["diet_type"] in ("RENAL", "DIABETIC", "RENAL_DIABETIC", "CARDIAC")
    for field in ("daily_sodium_mg_max", "daily_potassium_mg_max",
                  "daily_phosphorus_mg_max", "daily_carbs_g_max",
                  "daily_protein_g_min", "meals_per_week"):
        assert isinstance(data[field], int), f"DietPrescription.{field} must be int"
    assert isinstance(data["excluded_allergens"], list)
    assert "supersedes_id" in data


def assert_menu_item(data: dict):
    _assert_common_fields(data, "MenuItem")
    assert isinstance(data["name"], str) and data["name"]
    for field in ("sodium_mg", "potassium_mg", "phosphorus_mg", "carbs_g",
                  "protein_g", "base_cost_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, \
            f"MenuItem.{field} must be a non-negative int"
    assert isinstance(data["allergen_codes"], list)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_menu_cycle(data: dict):
    _assert_common_fields(data, "MenuCycle")
    assert data["status"] in ("PLANNED", "FROZEN", "FULFILLED", "CANCELLED")
    assert data["compliance_status"] in ("UNCHECKED", "PASSED")
    assert isinstance(data["meals_count"], int) and data["meals_count"] >= 0
    assert isinstance(data["member_id"], str)
    assert isinstance(data["prescription_id"], str)


def assert_menu_cycle_item(data: dict):
    """Append-only sub-record: id + created_at only, no updated_at/version
    (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "MenuCycleItem.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "MenuCycleItem.created_at must be an ISO 8601 timestamp"
    assert "updated_at" not in data, "MenuCycleItem must not expose updated_at"
    assert "version" not in data, "MenuCycleItem must not expose version"
    assert isinstance(data["menu_item_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1


def assert_route(data: dict):
    _assert_common_fields(data, "DeliveryRoute")
    assert data["status"] in ("PLANNED", "DISPATCHED", "COMPLETED", "CANCELLED")
    assert isinstance(data["driver_id"], str)
    assert isinstance(data["capacity_stops"], int) and data["capacity_stops"] >= 1


def assert_delivery(data: dict):
    _assert_common_fields(data, "Delivery")
    assert data["status"] in ("SCHEDULED", "OUT_FOR_DELIVERY", "DELIVERED",
                              "FAILED", "CANCELLED", "SPOILED")
    assert data["cold_chain_status"] in ("INTACT", "EXCURSION", "SPOILED")
    assert isinstance(data["cumulative_excursion_minutes"], int)
    assert data["cumulative_excursion_minutes"] >= 0
    assert isinstance(data["member_id"], str)
    assert isinstance(data["menu_cycle_id"], str)
    assert isinstance(data["route_id"], str)


def assert_cold_chain_reading(data: dict):
    """Append-only sub-record: id + created_at only, no updated_at/version
    (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "ColdChainReading.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "ColdChainReading.created_at must be an ISO 8601 timestamp"
    assert "updated_at" not in data, "ColdChainReading must not expose updated_at"
    assert "version" not in data, "ColdChainReading must not expose version"
    assert isinstance(data["delivery_id"], str)
    assert isinstance(data["recorded_at"], str)
    assert isinstance(data["temp_celsius"], (int, float))


def assert_reauthorization(data: dict):
    _assert_common_fields(data, "Reauthorization")
    assert data["status"] in ("PENDING", "APPROVED", "DENIED", "EXHAUSTED", "EXPIRED")
    for field in ("authorized_units", "used_units", "reserved_units",
                  "available_units", "max_amount_cents", "consumed_amount_cents"):
        assert isinstance(data[field], int), f"Reauthorization.{field} must be int"
    assert_authorization_units_conserved(data)


def assert_outcome_assessment(data: dict):
    _assert_common_fields(data, "OutcomeAssessment")
    assert isinstance(data["member_id"], str)
    assert isinstance(data["assessed_at"], str)
    assert isinstance(data["weight_kg"], (int, float))
    assert isinstance(data["hba1c_pct"], (int, float))


def assert_claim(data: dict):
    _assert_common_fields(data, "Claim")
    assert data["status"] in ("DRAFT", "SUBMITTED", "PAID", "PARTIALLY_PAID",
                              "DENIED", "VOIDED")
    assert data["payer_type_snapshot"] in ("MEDICAID_WAIVER", "MEDICARE_ADVANTAGE")
    for field in ("units_delivered", "provisional_gross_cents",
                  "member_cost_share_cents", "plan_liability_cents"):
        assert isinstance(data[field], int), f"Claim.{field} must be int"
    assert_claim_amount_invariants(data)


def assert_claim_amount_invariants(data: dict):
    """plan_liability_cents == provisional_gross_cents - member_cost_share_cents
    (PRD §3.7)."""
    assert data["plan_liability_cents"] == (
        data["provisional_gross_cents"] - data["member_cost_share_cents"]
    ), (f"plan_liability_cents {data['plan_liability_cents']} != "
        f"provisional_gross_cents {data['provisional_gross_cents']} - "
        f"member_cost_share_cents {data['member_cost_share_cents']}")


def assert_authorization_units_conserved(data: dict):
    """Conserved service units (PRD §2.10):
    authorized_units == used_units + reserved_units + available_units."""
    assert data["authorized_units"] == (
        data["used_units"] + data["reserved_units"] + data["available_units"]
    ), (f"unit conservation violated: {data['authorized_units']} != "
        f"{data['used_units']} + {data['reserved_units']} + {data['available_units']}")

"""Entity assertions, semantic timestamp comparison and conservation checkers."""
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --------------------------------------------------------------------------
# Timestamps are compared as parsed instants, never as rendered strings.
# --------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into an aware datetime."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual, expected, label="timestamp"):
    """Compare two ISO 8601 instants semantically, ignoring rendering style."""
    assert actual is not None, f"{label} must not be null"
    got = parse_instant(actual)
    want = parse_instant(expected) if isinstance(expected, str) else expected
    assert got == want, f"{label}: expected instant {want.isoformat()}, got {actual!r}"


def iso_plus_days(instant: str, days: int) -> str:
    """The instant advanced by whole 24-hour periods, rendered ISO 8601 UTC."""
    return (parse_instant(instant) + timedelta(days=days)).isoformat().replace("+00:00", "Z")


def round_half_up(value) -> int:
    """Round half up to a whole cent, away from zero at the half boundary."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_dp(value, places: int) -> float:
    quant = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Common-field assertions. Every entity carries id, created_at, updated_at and
# version (PRD 2.4).
# --------------------------------------------------------------------------
def assert_common_fields(data: dict, entity_label: str = "entity"):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer starting at 1"
    )


def assert_organization(data: dict):
    assert_common_fields(data, "Organization")
    assert data["org_type"] in ("SHELTER", "PARTNER_RESCUE")
    assert data["default_methodology"] in ("SAC", "ASILOMAR")
    assert data["freeze_status"] in ("UNFROZEN", "FROZEN")
    assert isinstance(data["records_freeze_active"], bool)
    assert isinstance(data["unrestricted_balance_cents"], int)
    assert isinstance(data["restricted_balance_cents"], int)
    assert isinstance(data["open_commitment_slots_total"], int)


def assert_person(data: dict):
    assert_common_fields(data, "Person")
    assert "@" in data["email"]
    assert data["housing_type"] in ("APARTMENT", "CONDO", "HOUSE", "FARM")
    assert isinstance(data["reclaim_history_count"], int)


def assert_animal(data: dict):
    assert_common_fields(data, "Animal")
    assert data["species"] in ("DOG", "CAT", "OTHER")
    assert data["size_class"] in ("SMALL", "MEDIUM", "LARGE")
    assert data["temperament"] in ("SOCIAL", "REACTIVE", "UNKNOWN")
    assert data["lifecycle_status"] in (
        "PRE_INTAKE", "IN_CUSTODY", "IN_TRANSIT", "STRANDED", "OUTCOME_CLOSED"
    )
    assert data["alteration_status"] in ("NOT_ALTERED", "ALTERED", "DEFERRED_DEPOSIT")
    assert isinstance(data["identifiable"], bool)
    assert isinstance(data["age_weeks"], int) and data["age_weeks"] >= 0
    assert isinstance(data["age_months"], int) and data["age_months"] >= 0
    assert isinstance(data["length_of_stay_days"], int) and data["length_of_stay_days"] >= 0
    assert data["weight_lb"] > 0


def assert_intake_record(data: dict):
    assert_common_fields(data, "IntakeRecord")
    assert data["intake_type"] in (
        "STRAY", "OWNER_SURRENDER", "CONFISCATE", "TRANSFER_IN", "RETURN"
    )
    assert data["status"] in ("OPEN", "CLOSED", "VOIDED")
    assert data["hold_status"] in ("HOLD_ACTIVE", "HOLD_EXPIRED")
    assert isinstance(data["hold_days"], int) and data["hold_days"] >= 0


def assert_hold_record(data: dict):
    assert_common_fields(data, "HoldRecord")
    assert data["hold_type"] in ("MEDICAL", "BEHAVIORAL", "LEGAL")
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_foster_home(data: dict):
    assert_common_fields(data, "FosterHome")
    assert data["capacity_status"] in ("OPEN", "FULL")
    assert data["consumed_dog_slots"] >= 0
    assert data["consumed_cat_slots"] >= 0
    assert data["consumed_headcount"] >= 0


def assert_foster_application(data: dict):
    assert_common_fields(data, "FosterApplication")
    assert data["application_status"] in (
        "SUBMITTED", "APPROVED", "DECLINED", "SUSPENDED", "WITHDRAWN"
    )
    assert data["home_check_status"] in ("NOT_SCHEDULED", "PASSED", "FAILED", "LAPSED")
    assert data["species_requested"] in ("DOG", "CAT", "OTHER")


def assert_foster_placement(data: dict):
    assert_common_fields(data, "FosterPlacement")
    assert data["status"] in (
        "PROPOSED", "ACTIVE", "ENDED", "CANCELLED", "TRANSFERRED", "CONVERTED_TO_ADOPTION"
    )
    assert data["count_basis"] in ("INDIVIDUAL", "NURSING_UNIT")
    assert isinstance(data["slot_consumption"], int)
    assert isinstance(data["headcount_consumption"], int)


def assert_medical_record(data: dict):
    assert_common_fields(data, "MedicalRecord")
    assert data["status"] in ("ORDERED", "COMPLETED")
    assert data["procedure_type"] in ("EXAM", "VACCINE_RABIES", "SPAY_NEUTER", "TREATMENT")
    assert data["expense_category"] in ("MEDICAL", "SPAY_NEUTER", "VACCINE")
    assert isinstance(data["funded_amount_cents"], int)
    assert isinstance(data["admin_overhead_cents"], int)


def assert_health_certificate(data: dict):
    assert_common_fields(data, "HealthCertificate")
    assert data["status"] in ("VALID", "EXPIRED")
    assert isinstance(data["window_days"], int)
    assert len(data["destination_state"]) == 2 and data["destination_state"].isupper()


def assert_transport_run(data: dict):
    assert_common_fields(data, "TransportRun")
    assert data["status"] in ("PLANNED", "IN_PROGRESS", "COMPLETED", "ABORTED", "CANCELLED")
    assert data["run_type"] in ("RESCUE_LEG", "RELAY")
    assert data["purpose"] in ("INTAKE_TRANSPORT", "TRANSFER_OUT")
    assert isinstance(data["slots_drawn"], int)


def assert_transport_leg(data: dict):
    assert_common_fields(data, "TransportLeg")
    assert data["status"] in ("SCHEDULED", "DEPARTED", "ARRIVED", "ABORTED", "INVALIDATED")
    assert data["species_policy"] in ("DOGS_ONLY", "CATS_ONLY", "MIXED_SEGREGATED", "ANY")
    assert isinstance(data["used_crate_units"], int)
    assert parse_instant(data["scheduled_arrive_at"]) > parse_instant(data["scheduled_depart_at"])


def assert_manifest_entry(data: dict):
    assert_common_fields(data, "ManifestEntry")
    assert data["status"] in ("ASSIGNED", "LOADED", "DELIVERED", "BUMPED", "STRANDED")
    assert isinstance(data["crate_units"], int) and data["crate_units"] >= 0
    assert isinstance(data["is_litter_anchor"], bool)


def assert_adoption_application(data: dict):
    assert_common_fields(data, "AdoptionApplication")
    assert data["status"] in (
        "SUBMITTED", "APPROVED", "DECLINED", "AUTO_DECLINED", "FINALIZED"
    )
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 1


def assert_adoption(data: dict):
    assert_common_fields(data, "Adoption")
    assert data["status"] in ("FINALIZED", "RETURNED")
    assert data["fee_status"] in (
        "UNPAID", "PARTIALLY_PAID", "PAID", "REFUNDED_PARTIAL", "REFUNDED_FULL"
    )
    assert data["waiver_kind"] in ("NONE", "SENIOR", "LONG_STAY")


def assert_outcome_record(data: dict):
    assert_common_fields(data, "OutcomeRecord")
    assert isinstance(data["is_live_release"], bool)


def assert_contribution(data: dict):
    assert_common_fields(data, "Contribution")
    assert data["status"] in ("RECEIVED", "PARTIALLY_APPLIED", "FULLY_APPLIED", "RELEASED")
    assert data["designated_program"] in (
        "NONE", "ADOPTION_FEE_ASSISTANCE", "TRANSPORT_FUND", "MEDICAL_FUND"
    )
    assert data["restriction_category"] in (
        "UNRESTRICTED", "MEDICAL", "SPAY_NEUTER", "VACCINE", "TRANSPORT"
    )


def assert_partner_commitment(data: dict):
    assert_common_fields(data, "PartnerCommitment")
    assert data["status"] in ("OPEN", "PARTIALLY_DRAWN", "EXHAUSTED", "EXPIRED")


# --------------------------------------------------------------------------
# Conservation identities (PRD 2.10).
# --------------------------------------------------------------------------
def assert_contribution_money_conserved(contribution: dict):
    """amount_cents == applied_cents + released_cents + available_cents."""
    total = (
        contribution["applied_cents"]
        + contribution["released_cents"]
        + contribution["available_cents"]
    )
    assert total == contribution["amount_cents"], (
        f"contribution money not conserved: {contribution['applied_cents']} + "
        f"{contribution['released_cents']} + {contribution['available_cents']} != "
        f"{contribution['amount_cents']}"
    )


def assert_partner_slots_conserved(commitment: dict):
    """slots_total == slots_drawn + slots_released + slots_open."""
    total = (
        commitment["slots_drawn"] + commitment["slots_released"] + commitment["slots_open"]
    )
    assert total == commitment["slots_total"], (
        f"partner slots not conserved: {total} != {commitment['slots_total']}"
    )


def assert_adoption_fee_components_conserved(adoption: dict):
    """base_fee_cents == sponsorship + waiver + adopter_charged."""
    total = (
        adoption["sponsorship_applied_cents"]
        + adoption["waiver_applied_cents"]
        + adoption["adopter_charged_cents"]
    )
    assert total == adoption["base_fee_cents"], (
        f"adoption fee components not conserved: {total} != {adoption['base_fee_cents']}"
    )


def assert_leg_crate_units_conserved(leg: dict, entries: list):
    """used_crate_units == sum of crate_units over ASSIGNED/LOADED/DELIVERED entries."""
    counted = sum(
        entry["crate_units"]
        for entry in entries
        if entry["status"] in ("ASSIGNED", "LOADED", "DELIVERED")
    )
    assert leg["used_crate_units"] == counted, (
        f"leg crate units not conserved: used_crate_units={leg['used_crate_units']} "
        f"but non-bumped entries sum to {counted}"
    )


def assert_foster_slots_conserved(home: dict, active_placements: list):
    """consumed_dog_slots + consumed_cat_slots == sum of ACTIVE slot_consumption."""
    counted = sum(p["slot_consumption"] for p in active_placements if p["status"] == "ACTIVE")
    assert home["consumed_dog_slots"] + home["consumed_cat_slots"] == counted, (
        f"foster slots not conserved: {home['consumed_dog_slots']} + "
        f"{home['consumed_cat_slots']} != {counted}"
    )

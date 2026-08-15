"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

SUPPLIER_STATUSES = (
    "PENDING_EVALUATION", "APPROVED", "REEVALUATION_DUE", "SUSPENDED", "REJECTED",
)
RISK_TIERS = ("LOW", "MODERATE", "HIGH")
EVALUATION_OUTCOMES = ("APPROVED", "CONDITIONAL", "REJECTED")
ENTRY_STATUSES = (
    "DRAFT", "PRIOR_NOTICE_FILED", "ENTRY_FILED", "RELEASED", "DETAINED", "REFUSED",
)
LOT_STATUSES = (
    "UNDER_INSPECTION", "ACCEPTED", "QUARANTINED", "REJECTED", "CONSUMED",
)
VERIFICATION_STATUSES = (
    "CONFIRMED", "MISMATCH", "RESOLVED_RELABELED", "RESOLVED_REJECTED",
)
BATCH_STATUSES = ("IN_PROCESS", "COMPLETED", "RECONCILED")
CA_STATUSES = ("OPEN", "INVESTIGATING", "RESOLVED", "ESCALATED")
LABEL_STATUSES = ("DRAFT", "APPROVED", "SUPERSEDED")
FINISHED_LOT_STATUSES = ("UNLABELED", "LABELED", "RELEASED", "RECALLED")
RECALL_STATUSES = ("INITIATED", "NOTIFIED")


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, \
        "append-only record must not carry updated_at"
    assert "version" not in data, \
        "append-only record must not carry version"


def assert_supplier(data: dict):
    _assert_common(data)
    assert data["fsvp_status"] in SUPPLIER_STATUSES
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["country_code"], str) and data["country_code"]
    assert isinstance(data["facility_registration_number"], str)
    assert isinstance(data["handles_histamine_susceptible_species"], bool)
    assert isinstance(data["open_corrective_action_count"], int)
    assert isinstance(data["total_species_mismatches"], int)
    assert isinstance(data["total_haccp_deviations"], int)


def assert_supplier_evaluation(data: dict):
    _assert_common(data)
    assert data["outcome"] in EVALUATION_OUTCOMES
    assert isinstance(data["supplier_id"], str)
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    for field in ("hazard_analysis_score", "record_review_score",
                  "performance_score", "overall_score"):
        assert isinstance(data[field], (int, float)), field
    assert isinstance(data["evaluated_by"], str)


def assert_import_entry(data: dict):
    _assert_common(data)
    assert data["status"] in ENTRY_STATUSES
    assert data["transport_mode"] in ("VESSEL", "AIR", "ROAD")
    assert isinstance(data["goods_value_cents"], int)
    assert isinstance(data["freight_cost_cents"], int)
    assert isinstance(data["entry_number"], str) and data["entry_number"]


def assert_receipt_lot(data: dict):
    _assert_common(data)
    assert data["status"] in LOT_STATUSES
    assert data["production_method"] in ("WILD", "FARMED")
    assert data["grade"] in ("A", "B", "C")
    assert data["freeze_protocol"] in ("NONE", "STANDARD", "BLAST", "COMBO")
    assert isinstance(data["quantity_accepted_kg"], (int, float))
    assert isinstance(data["consumed_kg"], (int, float))
    assert isinstance(data["remaining_kg"], (int, float))
    assert isinstance(data["mislabel_flag"], bool)
    assert isinstance(data["freeze_compliant"], bool)
    assert isinstance(data["cumulative_abuse_minutes"], int)
    assert isinstance(data["allocated_cost_cents"], int)


def assert_species_verification(data: dict):
    _assert_common(data)
    assert data["status"] in VERIFICATION_STATUSES
    assert data["test_method"] in ("DNA_BARCODING", "SENSORY")
    assert isinstance(data["is_match"], bool)
    assert isinstance(data["sample_size"], int)


def assert_processing_batch(data: dict):
    _assert_common(data)
    assert data["status"] in BATCH_STATUSES
    assert data["product_form"] in ("FILLET", "LOIN", "PORTION")
    assert isinstance(data["target_species"], str)
    assert isinstance(data["input_total_kg"], (int, float))


def assert_batch_input(data: dict):
    _assert_common(data)
    assert isinstance(data["processing_batch_id"], str)
    assert isinstance(data["receipt_lot_id"], str)
    assert isinstance(data["quantity_kg"], (int, float))
    assert isinstance(data["provisional_yield_kg"], (int, float))


def assert_temperature_log(data: dict):
    _assert_append_only(data)
    assert data["source"] in ("CONTINUOUS_MONITOR", "MANUAL_PROBE")
    assert is_iso8601_timestamp(data["interval_start"])
    assert is_iso8601_timestamp(data["interval_end"])


def assert_haccp_record(data: dict):
    _assert_append_only(data)
    assert data["hazard_type"] in ("HISTAMINE", "PARASITE")
    assert data["phase"] in ("SCREENING", "CONFIRMATORY")
    assert data["verdict"] in ("PASS", "DEVIATION")


def assert_corrective_action(data: dict):
    _assert_common(data)
    assert data["status"] in CA_STATUSES
    assert data["source_type"] in (
        "SPECIES_MISMATCH", "HISTAMINE_DEVIATION", "TEMPERATURE_ABUSE",
        "YIELD_VARIANCE", "MANUAL",
    )
    assert isinstance(data["opened_by"], str)


def assert_product_label(data: dict):
    _assert_common(data)
    assert data["status"] in LABEL_STATUSES
    assert isinstance(data["allergen_statement"], str)


def assert_finished_lot(data: dict):
    _assert_common(data)
    assert data["status"] in FINISHED_LOT_STATUSES
    assert isinstance(data["net_weight_kg"], (int, float))
    assert isinstance(data["label_stale"], bool)


def assert_recall(data: dict):
    _assert_common(data)
    assert data["status"] in RECALL_STATUSES
    assert isinstance(data["corrective_action_id"], str)
    assert isinstance(data["scope_lot_ids"], list)


def assert_lot_mass_balance(lot: dict):
    """Domain invariant: consumed_kg + remaining_kg == quantity_accepted_kg."""
    total = float(lot["consumed_kg"]) + float(lot["remaining_kg"])
    assert abs(total - float(lot["quantity_accepted_kg"])) < 1e-6, (
        f"Mass balance violated: consumed {lot['consumed_kg']} + "
        f"remaining {lot['remaining_kg']} != accepted "
        f"{lot['quantity_accepted_kg']}"
    )


def assert_allocation_conserves_total(lots: list, allocatable_total_cents: int):
    """Domain invariant: sum of allocated_cost_cents over ACCEPTED lots equals
    the entry's allocatable_total_cents."""
    total = sum(l["allocated_cost_cents"] for l in lots)
    assert total == allocatable_total_cents, (
        f"Allocation total {total} != allocatable_total_cents "
        f"{allocatable_total_cents}"
    )

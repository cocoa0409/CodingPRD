"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version on a full-quartet entity."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an int >= 1"


def assert_patient(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_device_model(data: dict):
    assert_common_fields(data)
    assert isinstance(data["model_code"], str) and len(data["model_code"]) > 0
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert isinstance(data["restock_fee_cents"], int) and data["restock_fee_cents"] >= 0
    assert data["min_severity"] in ("MILD", "MODERATE", "SEVERE", "PROFOUND")
    assert isinstance(data["warranty_months"], int) and data["warranty_months"] > 0
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_allowance_benefit(data: dict):
    assert_common_fields(data)
    assert isinstance(data["total_allowance_cents"], int) and data["total_allowance_cents"] > 0
    assert isinstance(data["per_device_cap_cents"], int) and data["per_device_cap_cents"] > 0
    assert 0 <= data["coinsurance_pct"] < 1
    assert isinstance(data["consumed_allowance_cents"], int) and data["consumed_allowance_cents"] >= 0
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "EXPIRED")


def assert_evaluation(data: dict):
    assert_common_fields(data)
    assert 0 <= data["pure_tone_avg_db"] <= 120
    assert data["status"] in ("DRAFT", "FINALIZED", "SUPERSEDED")


def assert_evaluation_finalized(data: dict):
    assert_evaluation(data)
    assert data["status"] == "FINALIZED"
    assert data["severity"] in ("NORMAL", "MILD", "MODERATE", "SEVERE", "PROFOUND")
    assert isinstance(data["candidate"], bool)
    assert isinstance(data["is_pediatric"], bool)
    assert data["candidate"] == (data["severity"] != "NORMAL"), \
        "candidate must be true iff severity is not NORMAL"


def assert_fitting_order(data: dict):
    assert_common_fields(data)
    assert data["ear_count"] in (1, 2)
    assert data["status"] in (
        "DRAFT", "TRIAL", "PURCHASED", "WARRANTY_ACTIVE", "RETURNED", "CANCELLED")


def assert_adjustment_session(data: dict):
    assert_common_fields(data)
    assert data["reason"] in ("COMFORT", "RECALL_REPROGRAM", "GAIN_TUNE")
    assert data["status"] in ("COMPLETED", "VOIDED")


def assert_warranty_claim(data: dict):
    assert_common_fields(data)
    assert data["claim_type"] in ("DEFECT", "LOSS", "DAMAGE")
    assert isinstance(data["assessed_value_cents"], int) and data["assessed_value_cents"] > 0
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED", "APPEALED", "REPLACED")


def assert_supply_subscription(data: dict):
    assert_common_fields(data)
    assert data["cadence_days"] in (30, 60, 90)
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["cycles_fulfilled"], int) and data["cycles_fulfilled"] >= 0
    assert isinstance(data["lifetime_billed_cents"], int) and data["lifetime_billed_cents"] >= 0
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")


def assert_supply_cycle(data: dict):
    assert_common_fields(data)
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert data["status"] in ("SCHEDULED", "SHIPPED", "SKIPPED")


def assert_recall_notice(data: dict):
    assert_common_fields(data)
    assert data["severity_level"] in ("ADVISORY", "MANDATORY")
    assert isinstance(data["affected_order_count"], int) and data["affected_order_count"] >= 0
    assert data["status"] in ("DRAFT", "ISSUED", "CLOSED")


def assert_ledger_entry(data: dict):
    """LedgerEntry is append-only: id + created_at only, NO updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["source_kind"] in (
        "ORDER_PURCHASE", "ORDER_RETURN", "ALLOWANCE_APPLIED",
        "WARRANTY_DEDUCTIBLE", "SUPPLY_BILLING")
    assert isinstance(data["amount_cents"], int)


# --- Domain conserved-quantity invariants (PRD Section 2.10) ---

def assert_warranty_split_conserved(claim: dict):
    """deductible_cents + clinic_cost_cents == assessed_value_cents."""
    assert claim["deductible_cents"] + claim["clinic_cost_cents"] == claim["assessed_value_cents"], (
        "warranty settlement must split assessed value exactly: "
        f"{claim['deductible_cents']} + {claim['clinic_cost_cents']} != {claim['assessed_value_cents']}"
    )


def assert_net_charge_equals_restock(order: dict, restock_fee_cents: int):
    """patient_due_cents - refund_cents == restock_fee_cents for an in-window purchased return."""
    net = order["patient_due_cents"] - order["refund_cents"]
    assert net == restock_fee_cents, (
        f"net patient charge {net} must equal restock fee {restock_fee_cents}"
    )

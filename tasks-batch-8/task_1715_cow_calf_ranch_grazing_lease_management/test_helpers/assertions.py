"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_aum(value, expected, label="AUM value"):
    """AUM figures are carried at 2 decimals, round half-up (PRD §2.6)."""
    assert value == pytest.approx(expected, abs=0.005), (
        f"{label}: expected {expected}, got {value}"
    )


def assert_money(value, expected, label="money value"):
    """Monetary cents are carried at 2 decimals, round half-up (PRD §2.6)."""
    assert value == pytest.approx(expected, abs=0.005), (
        f"{label}: expected {expected}, got {value}"
    )


def assert_pct1(value, expected, label="percentage"):
    """Percentages are rounded half-up to 1 decimal place (PRD §2.6)."""
    assert value == pytest.approx(expected, abs=0.05), (
        f"{label}: expected {expected}, got {value}"
    )


def assert_au4(value, expected, label="animal-unit factor"):
    """The animal-unit factor is rounded half-up to 4 decimals (PRD §2.6)."""
    assert value == pytest.approx(expected, abs=0.00005), (
        f"{label}: expected {expected}, got {value}"
    )


def assert_date_field(value, expected_yyyy_mm_dd, label="date field"):
    """Domain date fields are ISO calendar dates (YYYY-MM-DD)."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert value.startswith(expected_yyyy_mm_dd), (
        f"{label}: expected date {expected_yyyy_mm_dd}, got {value}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def assert_ranch(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["hq_state"], str) and len(data["hq_state"]) == 2
    assert isinstance(data["destock_grace_days"], int)
    assert data["drought_posture"] in ["NORMAL", "WATCH", "ALERT", "CRITICAL"]
    assert isinstance(data["assessment_seq"], int) and data["assessment_seq"] >= 0


def assert_pasture(data: dict):
    _assert_common(data)
    assert data["tenure"] in ["DEEDED", "LEASED"]
    assert data["forage_type"] in ["NATIVE_RANGE", "IMPROVED", "CROP_RESIDUE"]
    assert isinstance(data["base_capacity_aum"], int)
    assert isinstance(data["min_rest_days"], int)
    assert data["condition_status"] in ["GRAZEABLE", "RESTING", "CLOSED"]
    assert isinstance(data["closed_flag"], bool)
    for f in ("effective_capacity_aum", "committed_aum", "consumed_total_aum",
              "available_aum"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"


def assert_lease(data: dict):
    _assert_common(data)
    assert data["lease_status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED",
                                    "TERMINATED"]
    assert data["settlement_basis"] in ["ALLOTMENT", "ACTUAL_USE"]
    assert isinstance(data["aum_allotment"], int)


def assert_lease_statement(data: dict):
    _assert_common(data)
    assert data["statement_status"] in ["DRAFT", "ISSUED", "APPROVED", "PAID"]
    assert isinstance(data["period_year"], int)
    for f in ("actual_aum_used", "base_charge_cents", "overage_charge_cents",
              "total_due_cents"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    assert isinstance(data["recorded_by_user_id"], str)


def assert_herd_group(data: dict):
    _assert_common(data)
    assert data["animal_class"] in ["MATURE_COW", "REPLACEMENT_HEIFER", "GROWING"]
    assert isinstance(data["head_count"], int) and data["head_count"] >= 0
    assert isinstance(data["marked_open_head"], int) and data["marked_open_head"] >= 0
    assert data["group_status"] in ["ACTIVE", "DESTOCKING", "LIQUIDATED"]


def assert_breeding_season(data: dict):
    _assert_common(data)
    assert data["season_status"] in ["PLANNED", "BREEDING", "GESTATION",
                                     "PREG_CHECK", "CLOSED"]
    assert isinstance(data["exposed_head_count"], int)
    assert isinstance(data["required_bull_count"], int) and data["required_bull_count"] >= 1


def assert_bull(data: dict):
    _assert_common(data)
    assert data["bse_status"] in ["UNTESTED", "PASSED", "FAILED", "EXPIRED"]
    assert data["life_status"] in ["ACTIVE", "SOLD", "CULLED", "DEAD"]


def assert_bull_turnout(data: dict):
    _assert_common(data)
    assert data["turnout_status"] in ["SCHEDULED", "TURNED_IN", "REMOVED", "CANCELLED"]


def assert_preg_check(data: dict):
    _assert_common(data)
    assert data["check_status"] in ["DRAFT", "FINALIZED"]
    assert isinstance(data["exposed_head_count"], int)


def assert_calf_crop(data: dict):
    _assert_common(data)
    assert data["wean_status"] in ["UNWEANED", "WEANED"]
    assert data["precon_status"] in ["NONE", "ENROLLED", "CERTIFIED"]
    assert data["lifecycle_status"] in ["ACTIVE", "CLOSED"]
    for f in ("steer_head", "heifer_head", "retained_heifer_head",
              "death_loss_steer_head", "death_loss_heifer_head",
              "marketed_steer_head", "marketed_heifer_head",
              "reserved_steer_head", "reserved_heifer_head",
              "available_steer_head", "available_heifer_head"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative int"


def assert_sale_lot(data: dict):
    _assert_common(data)
    assert data["lot_status"] in ["DRAFT", "OFFERED", "CONTRACTED", "DELIVERED",
                                  "DISPUTED", "SETTLED", "CANCELLED"]
    assert data["lot_class"] in ["STEER", "HEIFER"]
    assert data["precon_claim"] in ["NONE", "ENROLLED", "CERTIFIED"]
    assert isinstance(data["relist_count"], int) and data["relist_count"] >= 0
    assert isinstance(data["sold_by_user_id"], str)


def assert_grazing_assignment(data: dict):
    _assert_common(data)
    assert data["assignment_status"] in ["ACTIVE", "COMPLETED", "SHORTENED",
                                         "CANCELLED"]
    assert isinstance(data["grazing_days"], int)
    assert isinstance(data["reserved_aum"], (int, float))
    assert isinstance(data["au_factor"], (int, float))


def assert_supplement_program(data: dict):
    _assert_common(data)
    assert data["program_type"] in ["MINERAL", "PROTEIN", "ENERGY"]
    assert data["program_status"] in ["ACTIVE", "COMPLETED", "CANCELLED"]
    assert isinstance(data["delivered_lbs_total"], (int, float))
    assert isinstance(data["cost_to_date_cents"], (int, float))
    assert isinstance(data["projected_consumption_lbs"], (int, float))


def assert_drought_assessment(data: dict):
    _assert_common(data)
    assert data["assessment_status"] in ["DRAFT", "FINALIZED"]
    assert data["resulting_posture"] in ["NORMAL", "WATCH", "ALERT", "CRITICAL"]
    for f in ("ranch_production_pct", "monthly_supply_aum", "monthly_demand_aum",
              "deficit_aum_per_30d"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"


def assert_destock_order(data: dict):
    _assert_common(data)
    assert data["order_status"] in ["OPEN", "COMPLIANT", "WAIVED", "EXPIRED"]
    assert isinstance(data["required_reduction_head"], int)
    assert isinstance(data["received_reduction_head"], int)


def assert_pasture_ledger_invariant(pasture: dict):
    """The forage ledger must always reconcile:
    available == effective - committed - consumed_total (PRD §2.9)."""
    assert_aum(
        pasture["available_aum"],
        pasture["effective_capacity_aum"]
        - pasture["committed_aum"]
        - pasture["consumed_total_aum"],
        "pasture available_aum ledger identity",
    )

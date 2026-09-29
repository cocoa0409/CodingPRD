"""Entity assertions and domain invariant checkers for the NPD stage-gate API."""
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    CATEGORY_FACTOR,
    READINESS_INDEX_CAP,
)
from .types import (
    BusinessCaseStatus,
    CommercialStatus,
    DeliverableStatus,
    DevStatus,
    FormulationStatus,
    GateReviewStatus,
    LabelApprovalStatus,
    PilotRunStatus,
    PresentationStatus,
    ShelfLifeStudyStatus,
)


def _assert_identity(data: dict):
    """Every stored resource is addressed by a server-minted UUID plus created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def _assert_audited(data: dict):
    """Entities other than a cast ballot also carry updated_at and version."""
    _assert_identity(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 on insert"


def assert_stage_gate(data: dict):
    _assert_audited(data)
    assert isinstance(data["gate_number"], int) and data["gate_number"] >= 2
    assert data["category"] in [c for c in CATEGORY_FACTOR]
    assert data["stage_from"] in ["SCREENED", "PILOT_QUALIFIED"]
    assert data["stage_to"] in ["PILOT_QUALIFIED", "LAUNCH_READY"]
    assert isinstance(data["required_deliverable_types"], list)
    assert len(data["required_deliverable_types"]) == len(
        set(data["required_deliverable_types"])
    ), "required_deliverable_types must contain no duplicates"
    assert data["quorum_size"] >= 1, "quorum_size is at least one ballot"
    assert isinstance(data["veto_functions"], list)


def assert_retailer(data: dict):
    _assert_audited(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["channel"] in ["GROCERY", "MASS", "CLUB", "CONVENIENCE", "ECOMMERCE"]
    assert 0.00 <= data["acv_contribution_pct"] <= 100.00
    assert isinstance(data["presentation_lead_days"], int)


def assert_shelf_reset_window(data: dict):
    _assert_audited(data)
    assert data["category"] in [c for c in CATEGORY_FACTOR]
    assert data["window_end"] > data["window_start"], "window_end is strictly after start"
    assert data["max_presentations"] >= 1
    assert data["booked_slot_count"] >= 0, "the slot counter never goes negative"
    assert data["booked_slot_count"] <= data["max_presentations"], (
        "booked_slot_count never exceeds the window's max_presentations"
    )


def assert_pilot_line(data: dict):
    _assert_audited(data)
    assert isinstance(data["plant_name"], str) and data["plant_name"]
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert 0 <= data["changeover_buffer_minutes"] <= 1440
    assert data["allergen_regime"] in ["NONE", "DAIRY", "NUT", "GLUTEN"]


def assert_project(data: dict):
    _assert_audited(data)
    assert 1 <= len(data["name"]) <= 120
    assert data["category"] in [c for c in CATEGORY_FACTOR]
    assert data["project_type"] in ["NEW_BRAND", "LINE_EXTENSION", "RENOVATION"]
    assert data["dev_status"] in [s.value for s in DevStatus]
    assert data["commercial_status"] in [s.value for s in CommercialStatus]
    assert data["screening_decision"] in ["PENDING", "PASSED", "REJECTED"]
    assert isinstance(data["next_gate_number"], int)
    assert isinstance(data["recycle_count"], int) and data["recycle_count"] >= 0
    assert isinstance(data["open_gate_conditions"], bool)
    assert_cost_precision(data["development_budget_committed_usd"])
    assert data["development_budget_committed_usd"] >= 0.00
    assert 0.00 <= data["launch_readiness_pct"] <= 100.00
    assert 0.00 <= data["authorized_acv_pct"] <= 100.00


def assert_concept_test(data: dict):
    _assert_audited(data)
    assert data["test_type"] in ["MONADIC", "SEQUENTIAL_MONADIC", "IN_HOME_USE"]
    assert data["sample_size"] >= 1
    assert 0.00 <= data["purchase_intent_top2_pct"] <= 100.00
    assert 0.00 <= data["uniqueness_pct"] <= 100.00
    assert_cost_precision(data["concept_score"])
    assert isinstance(data["is_authoritative"], bool)


def assert_business_case(data: dict):
    _assert_audited(data)
    assert data["case_type"] in ["PRELIMINARY", "FINAL"]
    assert data["status"] in [s.value for s in BusinessCaseStatus]
    assert data["variant_mode"] in ["BOTTOM_UP", "TOP_DOWN"]
    assert isinstance(data["annual_units"], int), "annual_units is a whole number"
    for money_field in (
        "gross_revenue_usd",
        "trade_spend_usd",
        "net_revenue_usd",
        "cogs_total_usd",
        "gross_margin_usd",
        "gross_margin_pct",
        "npv_usd",
        "trade_spend_rate_pct",
    ):
        assert_cost_precision(data[money_field])
    assert isinstance(data["payback_months"], int)


def assert_forecast_line(data: dict):
    _assert_audited(data)
    assert data["channel"] in ["GROCERY", "MASS", "CLUB", "CONVENIENCE", "ECOMMERCE"]
    assert isinstance(data["store_count"], int)
    assert 0 <= data["promo_weeks"] <= 52
    assert isinstance(data["line_units"], int), "line_units is a whole number"
    assert_cost_precision(data["line_revenue_usd"])


def assert_deliverable(data: dict):
    _assert_audited(data)
    assert data["status"] in [s.value for s in DeliverableStatus]
    assert data["deliverable_type"] in [
        "CONSUMER_CONCEPT_TEST",
        "PRELIM_BUSINESS_CASE",
        "FINAL_BUSINESS_CASE",
        "PILOT_SCALE_UP_REPORT",
        "SHELF_LIFE_REPORT",
        "REGULATORY_CLEARANCE",
        "MANUFACTURING_READINESS",
        "DISTRIBUTION_READINESS",
        "MARKETING_LAUNCH_PLAN",
        "SALES_SELL_IN_PLAN",
    ]
    assert data["owner_function"] in [
        "R_AND_D", "MARKETING", "FINANCE", "OPERATIONS", "QUALITY", "REGULATORY", "SALES",
    ]
    assert isinstance(data["submission_count"], int) and data["submission_count"] >= 0


def assert_gate_review(data: dict):
    _assert_audited(data)
    assert data["status"] in [s.value for s in GateReviewStatus]
    assert isinstance(data["vote_count"], int) and data["vote_count"] >= 0
    assert 0.00 <= data["deliverable_completeness_pct"] <= 100.00
    assert 0.00 <= data["readiness_index"] <= READINESS_INDEX_CAP
    assert_cost_precision(data["deliverable_completeness_pct"])
    assert_cost_precision(data["readiness_index"])


def assert_gate_vote(data: dict):
    """A ballot is immutable once cast: it carries only id and created_at."""
    _assert_identity(data)
    assert data["function"] in [
        "R_AND_D", "MARKETING", "FINANCE", "OPERATIONS", "QUALITY", "REGULATORY", "SALES",
    ]
    assert data["vote"] in ["APPROVE", "APPROVE_WITH_CONDITIONS", "REJECT"]
    assert isinstance(data["voter_user_id"], str) and data["voter_user_id"]
    assert "updated_at" not in data, "a cast ballot has no updated_at"
    assert "version" not in data, "a cast ballot has no version"


def assert_formulation(data: dict):
    _assert_audited(data)
    assert data["status"] in [s.value for s in FormulationStatus]
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["allergen_regime"] in ["NONE", "DAIRY", "NUT", "GLUTEN"]
    assert data["target_shelf_life_days"] >= 1
    assert_cost_precision(data["best_pilot_yield_pct"])


def assert_pilot_run(data: dict):
    _assert_audited(data)
    assert data["status"] in [s.value for s in PilotRunStatus]
    assert data["window_end"] > data["window_start"]
    assert data["planned_units"] >= 1
    assert_cost_precision(data["committed_cost_usd"])
    assert isinstance(data["effective_buffer_minutes"], int)


def assert_shelf_life_study(data: dict):
    _assert_audited(data)
    assert data["status"] in [s.value for s in ShelfLifeStudyStatus]
    assert data["duration_days"] >= 1
    assert isinstance(data["timepoints"], list)
    day_indexes = [tp["day_index"] for tp in data["timepoints"]]
    assert day_indexes == sorted(day_indexes), (
        "the timepoints list is kept sorted by day_index ascending"
    )
    if data.get("verdict") is not None:
        assert data["verdict"] in ["PASS", "FAIL"]


def assert_label_approval(data: dict):
    _assert_audited(data)
    assert data["status"] in [s.value for s in LabelApprovalStatus]
    assert isinstance(data["claims"], list) and 1 <= len(data["claims"]) <= 10
    assert isinstance(data["unsupported_claims"], list)


def assert_sell_in_presentation(data: dict):
    _assert_audited(data)
    assert data["status"] in [s.value for s in PresentationStatus]
    assert data["proposed_sku_count"] >= 1
    if data.get("accepted_sku_count") is not None:
        assert data["accepted_sku_count"] <= data["proposed_sku_count"], (
            "accepted_sku_count may not exceed proposed_sku_count"
        )


def assert_post_launch_period(data: dict):
    _assert_audited(data)
    assert isinstance(data["period_index"], int) and data["period_index"] >= 1
    assert data["attainment_basis"] in ["CUMULATIVE", "TRAILING"]
    assert data["decision"] in ["CONTINUE", "FIX", "DISCONTINUE"]
    for pct_field in (
        "attainment_cumulative_pct",
        "attainment_trailing_pct",
        "attainment_pct",
        "plan_units_per_period",
    ):
        assert_cost_precision(data[pct_field])


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------

def assert_committed_budget_equals_live_sum(project: dict, live_costs):
    """The ledger is the exact sum over live pilot runs and stability studies."""
    expected = round(sum(live_costs), 2)
    actual = project["development_budget_committed_usd"]
    assert abs(actual - expected) < 0.005, (
        f"development_budget_committed_usd should be exactly {expected}, got {actual}"
    )
    assert actual <= project["development_budget_cap_usd"] + 0.005, (
        "the committed total never exceeds the project's cap"
    )


def assert_attainment_decision(period: dict):
    """CONTINUE at or above 90.00, FIX from 70.00 up to 90.00, DISCONTINUE below 70.00."""
    pct = period["attainment_pct"]
    if pct >= 90.00:
        expected = "CONTINUE"
    elif pct >= 70.00:
        expected = "FIX"
    else:
        expected = "DISCONTINUE"
    assert period["decision"] == expected, (
        f"attainment_pct {pct} implies {expected}, got {period['decision']}"
    )

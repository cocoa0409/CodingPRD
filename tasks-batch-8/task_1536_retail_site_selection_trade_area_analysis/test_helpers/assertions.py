"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

Nullable computed fields (scores before evaluation, lock-time forecast fields,
LOI negotiation fields) are read via .get() so that both an explicit JSON null
and an omitted key satisfy "unset".
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _check_identity(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )


def _check_versioned(data: dict, label: str):
    _check_identity(data, label)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def assert_market(data: dict):
    _check_versioned(data, "Market")
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("market_status") in [
        "SCREENING", "QUALIFIED", "DISQUALIFIED", "SATURATED", "CLOSED",
    ]
    assert isinstance(data.get("open_store_count"), int)
    assert isinstance(data.get("committed_capex_cents"), int)
    for field in ("raw_score", "penetration_index", "final_score"):
        value = data.get(field)
        assert value is None or isinstance(value, (int, float)), (
            f"Market.{field} must be null or numeric"
        )
    for field in ("screening_tier",):
        assert data.get(field) in (None, "A", "B", "C")
    value = data.get("target_store_count")
    assert value is None or isinstance(value, int)


def assert_store(data: dict):
    _check_versioned(data, "ExistingStore")
    assert data.get("store_status") in ["OPERATING", "CLOSED"]
    assert isinstance(data.get("store_code"), str) and data["store_code"]
    assert isinstance(data.get("annual_sales_cents"), int)


def assert_site(data: dict):
    _check_versioned(data, "Site")
    assert data.get("site_status") in [
        "DRAFT", "SCREENED", "MODELED", "SCORED", "FORECAST_LOCKED",
        "IN_COMMITTEE", "APPROVED", "REJECTED", "LOI_ACTIVE",
        "LEASE_EXECUTED", "BUILD_OUT", "OPEN", "MEASURING",
        "UNDERPERFORMING", "WITHDRAWN", "CLOSED_OUT",
    ]
    assert isinstance(data.get("consecutive_miss_count"), int)


def assert_trade_area_model(data: dict):
    _check_versioned(data, "TradeAreaModel")
    assert data.get("model_status") in ["DRAFT", "LOCKED", "SUPERSEDED"]
    assert data.get("cannibalization_variant") in ["FLAT_BAND", "DISTANCE_DECAY"]
    value = data.get("cannibalized_sales_cents")
    assert value is None or isinstance(value, int)


def assert_competitor_listing(data: dict):
    _check_versioned(data, "CompetitorListing")
    assert data.get("listing_type") in ["COMPETITOR", "COTENANT"]
    assert isinstance(data.get("brand_name"), str) and data["brand_name"]


def assert_site_visit(data: dict):
    _check_versioned(data, "SiteVisit")
    assert data.get("visit_status") in ["SUBMITTED", "SUPERSEDED"]
    for field in (
        "visibility_score", "access_score", "parking_score", "cotenancy_score",
    ):
        assert isinstance(data.get(field), int), f"SiteVisit.{field} must be int"
    value = data.get("total_score")
    assert value is None or isinstance(value, (int, float))


def assert_sales_forecast(data: dict):
    _check_versioned(data, "SalesForecast")
    assert data.get("forecast_status") in [
        "DRAFT", "COMMITTEE_LOCKED", "ACTUALIZED", "SUPERSEDED",
    ]
    assert data.get("model_variant") in ["GRAVITY", "ANALOG"]
    value = data.get("gross_annual_sales_cents")
    assert value is None or isinstance(value, int)
    for field in ("cannibalized_sales_cents", "net_annual_sales_cents",
                  "occupancy_ratio_bp"):
        value = data.get(field)
        assert value is None or isinstance(value, int), (
            f"SalesForecast.{field} must be null or int"
        )
    assert data.get("occupancy_band") in (None, "GREEN", "YELLOW", "RED")


def assert_committee_member(data: dict):
    _check_versioned(data, "CommitteeMember")
    assert data.get("member_status") in ["ACTIVE", "INACTIVE"]
    assert isinstance(data.get("display_name"), str) and data["display_name"]
    assert isinstance(data.get("is_chair"), bool)


def assert_committee_review(data: dict):
    _check_versioned(data, "CommitteeReview")
    assert data.get("review_status") in [
        "OPEN", "DECIDED", "RATIFIED", "EXPIRED", "VOID",
    ]
    assert data.get("decided_outcome") in (None, "APPROVE", "REJECT")
    for field in ("eligible_member_count", "quorum_count", "approve_votes",
                  "reject_votes", "abstain_votes"):
        assert isinstance(data.get(field), int), (
            f"CommitteeReview.{field} must be int"
        )


def assert_vote(data: dict):
    """A vote carries only id + created_at plus its recorded fields; no
    updated_at and no version (PRD §2.4)."""
    _check_identity(data, "Vote")
    assert "updated_at" not in data, "Vote must not carry updated_at"
    assert "version" not in data, "Vote must not carry version"
    assert data.get("ballot") in ["APPROVE", "REJECT", "ABSTAIN"]
    assert is_valid_uuid(data.get("review_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))


def assert_loi(data: dict):
    _check_versioned(data, "LOI")
    assert data.get("loi_status") in [
        "DRAFT", "SENT", "COUNTERED", "ACCEPTED", "EXPIRED", "WITHDRAWN",
    ]
    assert isinstance(data.get("round_number"), int) and data["round_number"] >= 1
    for field in ("countered_rent_psf_cents", "agreed_rent_psf_cents",
                  "effective_annual_rent_cents"):
        value = data.get(field)
        assert value is None or isinstance(value, int), (
            f"LOI.{field} must be null or int"
        )


def assert_lease(data: dict):
    _check_versioned(data, "Lease")
    assert data.get("lease_status") in ["NEGOTIATING", "EXECUTED", "TERMINATED"]
    for field in ("effective_annual_rent_cents", "final_occupancy_ratio_bp"):
        value = data.get(field)
        assert value is None or isinstance(value, int), (
            f"Lease.{field} must be null or int"
        )


def assert_construction_crew(data: dict):
    _check_versioned(data, "ConstructionCrew")
    assert data.get("crew_status") in ["ACTIVE", "RETIRED"]
    assert isinstance(data.get("crew_code"), str) and data["crew_code"]


def assert_permit_milestone(data: dict):
    _check_versioned(data, "PermitMilestone")
    assert data.get("milestone_status") in ["PENDING", "COMPLETED"]
    assert data.get("milestone_type") in [
        "PERMIT_SUBMITTED", "PERMIT_APPROVED", "BUILD_START", "BUILD_COMPLETE",
    ]
    value = data.get("actual_date")
    assert value is None or isinstance(value, str)


def assert_performance_snapshot(data: dict):
    _check_versioned(data, "PerformanceSnapshot")
    assert data.get("snapshot_status") in ["RECORDED", "FINALIZED"]
    assert isinstance(data.get("period_index"), int) and data["period_index"] >= 1
    for field in ("expected_sales_cents", "variance_bp"):
        value = data.get(field)
        assert value is None or isinstance(value, int), (
            f"PerformanceSnapshot.{field} must be null or int"
        )


def assert_market_ledger_invariants(data: dict):
    """Ledger invariants that must hold on any market read (PRD §2.9)."""
    assert data["open_store_count"] >= 0, "open_store_count must be non-negative"
    assert data["committed_capex_cents"] >= 0, (
        "committed_capex_cents must be non-negative"
    )
    if data.get("market_status") == "SATURATED":
        target = data.get("target_store_count")
        if target is not None:
            assert data["open_store_count"] >= target, (
                "SATURATED market must be at or above target_store_count"
            )

"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AdvanceStatus,
    AssetStatus,
    ArtistStatus,
    BeatStatus,
    BudgetPosture,
    CampaignStatus,
    ContractStatus,
    DeliveryStatus,
    DistributionStatus,
    MilestoneStatus,
    PayoutStatus,
    ProjectStatus,
    StatementStatus,
    TrackStatus,
    RoyaltyRunStatus,
    TourExpenseStatus,
    TourSupportStatus,
)


def _assert_common(data, with_version=True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            "version must be a positive integer"
        )


def assert_label(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["advance_cap_cents"], int)
    assert isinstance(data["reserve_rate_bps"], int)
    assert isinstance(data["sign_threshold_score"], (int, float))
    assert isinstance(data["option_window_days"], int)
    assert isinstance(data["release_lead_days"], int)
    assert isinstance(data["beat_pre_release_days"], int)
    assert isinstance(data["beat_post_release_days"], int)
    assert isinstance(data["campaign_gap_days"], int)
    assert isinstance(data["genre_multipliers"], dict)
    assert isinstance(data["channel_deduction_bps"], dict)
    assert isinstance(data["tier_thresholds"], list)
    assert isinstance(data["tour_category_caps_bps"], dict)


def assert_artist(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("label_id", "")), "label_id must be a UUID"
    assert isinstance(data["stage_name"], str)
    assert data["status"] in {s.value for s in ArtistStatus}
    assert isinstance(data["scouting_score"], (int, float))
    assert 0 <= data["scouting_score"] <= 100
    assert "pre_hiatus_status" in data


def assert_deal_memo(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in DealMemoStatus}
    assert isinstance(data["advance_cents"], int) and data["advance_cents"] >= 0
    assert 1000 <= data["base_royalty_rate_bps"] <= 3000
    assert data["recoupment_scope"] in ("MASTER_ONLY", "CROSS_COLLATERALIZED")
    assert isinstance(data["promo_costs_recoupable"], bool)
    assert 0 <= data["options_total"] <= 3
    assert data["option_term_months"] in (12, 24)
    assert data["term_months"] in (12, 24, 36)
    assert isinstance(data["round_count"], int)


def assert_contract(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in ContractStatus}
    assert data["advance_status"] in {s.value for s in AdvanceStatus}
    assert isinstance(data["options_exercised"], int) and data["options_exercised"] >= 0
    assert isinstance(data["effective_base_rate_bps"], int)
    assert data["effective_base_rate_bps"] <= 3000


def assert_recoupment_account(data: dict):
    _assert_common(data)
    assert data["payout_status"] in {s.value for s in PayoutStatus}
    for bucket in (
        "recording_balance_cents",
        "advance_balance_cents",
        "tour_support_balance_cents",
        "promo_balance_cents",
    ):
        assert isinstance(data[bucket], int) and data[bucket] >= 0
    assert isinstance(data["total_unrecouped_cents"], int)
    assert data["total_unrecouped_cents"] == (
        data["recording_balance_cents"]
        + data["advance_balance_cents"]
        + data["tour_support_balance_cents"]
        + data["promo_balance_cents"]
    ), "total_unrecouped_cents must equal the sum of the four buckets"
    assert isinstance(data["total_recouped_cents"], int) and data["total_recouped_cents"] >= 0
    assert isinstance(data["writeoff_cents"], int) and data["writeoff_cents"] >= 0


def assert_recording_project(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in ProjectStatus}
    assert data["budget_posture"] in {s.value for s in BudgetPosture}
    assert isinstance(data["budget_cents"], int)
    assert isinstance(data["spent_cents"], int) and data["spent_cents"] >= 0
    assert isinstance(data["committed_cents"], int) and data["committed_cents"] >= 0


def assert_milestone(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in MilestoneStatus}
    assert isinstance(data["payment_cents"], int) and data["payment_cents"] > 0
    assert isinstance(data["sequence"], int)


def assert_track(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in TrackStatus}
    assert isinstance(data["isrc"], str) and data["isrc"]
    assert isinstance(data["duration_seconds"], int) and data["duration_seconds"] > 0
    assert isinstance(data["contains_sample"], bool)


def assert_release(data: dict):
    _assert_common(data)
    assert data["asset_status"] in {s.value for s in AssetStatus}
    assert data["distribution_status"] in {s.value for s in DistributionStatus}
    assert data["release_type"] in ("SINGLE", "ALBUM")
    assert isinstance(data["track_ids"], list)


def assert_distributor(data: dict):
    _assert_common(data)
    assert data["channel_type"] in ("DSP", "PHYSICAL", "RADIO")
    assert isinstance(data["is_active"], bool)


def assert_asset_delivery(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in DeliveryStatus}
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_marketing_beat(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in BeatStatus}
    assert data["beat_type"] in ("TEASER", "SINGLE_DROP", "VIDEO", "PRESS", "TOUR_ANNOUNCE")
    assert data["channel"] in ("PLAYLIST", "RADIO", "SOCIAL", "PRESS")


def assert_promo_campaign(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in CampaignStatus}
    assert data["channel"] in ("PLAYLIST", "RADIO")
    assert isinstance(data["spend_cap_cents"], int) and data["spend_cap_cents"] > 0
    assert isinstance(data["spend_cents"], int) and data["spend_cents"] >= 0


def assert_tour_support(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in TourSupportStatus}
    assert isinstance(data["requested_amount_cents"], int) and data["requested_amount_cents"] > 0
    assert isinstance(data["approved_expense_total_cents"], int)


def assert_tour_expense(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in TourExpenseStatus}
    assert data["category"] in ("TRAVEL", "LODGING", "PRODUCTION", "MISC")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_revenue_report(data: dict):
    # Append-only: id + created_at only; NO updated_at, NO version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only revenue report must not carry version"
    assert "updated_at" not in data, "append-only revenue report must not carry updated_at"
    assert data["channel"] in ("STREAMING", "DOWNLOAD", "PHYSICAL", "SYNC")
    assert isinstance(data["units"], int) and data["units"] > 0
    assert isinstance(data["gross_revenue_cents"], int) and data["gross_revenue_cents"] > 0


def assert_royalty_run(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in RoyaltyRunStatus}
    assert isinstance(data["period"], str)


def assert_royalty_statement(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in StatementStatus}
    for field in (
        "gross_revenue_cents",
        "net_revenue_cents",
        "royalty_earned_cents",
        "projected_recoupment_cents",
        "recoupment_applied_cents",
        "reserve_held_cents",
        "adjustment_cents",
        "net_payable_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"

"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AdvertiserStatus, AdvertiserType, AdvertiserCategory, AuditStatus,
    BillingStatus, CampaignStatus, ContentRating, CreditStatus, Daypart,
    MarketTier, PartialCreditMode, PlayLogOutcome, ReelStatus, ReportStatus,
    ScreenStatus, SlotStatus, TheaterStatus,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_theater(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["market_tier"] in [t.value for t in MarketTier]
    assert data["theater_status"] in [s.value for s in TheaterStatus]


def assert_screen(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("theater_id", "")), "theater_id must be a UUID"
    assert isinstance(data["auditorium_label"], str) and data["auditorium_label"]
    assert isinstance(data["seat_count"], int) and data["seat_count"] > 0
    assert data["screen_status"] in [s.value for s in ScreenStatus]


def assert_feature(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["content_rating"] in [r.value for r in ContentRating]
    assert isinstance(data["runtime_minutes"], int) and data["runtime_minutes"] > 0
    assert isinstance(data["release_date"], str) and len(data["release_date"]) == 10


def assert_showtime(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("screen_id", "")), "screen_id must be a UUID"
    assert is_valid_uuid(data.get("feature_id", "")), "feature_id must be a UUID"
    assert isinstance(data["starts_at"], str) and data["starts_at"]
    assert data["daypart"] in [d.value for d in Daypart]
    assert isinstance(data["forecast_attendance"], int) and data["forecast_attendance"] >= 0
    actual = data.get("actual_attendance")
    assert actual is None or (isinstance(actual, int) and actual >= 0)


def assert_advertiser(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["advertiser_type"] in [t.value for t in AdvertiserType]
    assert data["category"] in [c.value for c in AdvertiserCategory]
    assert data["advertiser_status"] in [s.value for s in AdvertiserStatus]


def assert_campaign(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("advertiser_id", "")), "advertiser_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["flight_start_date"], str)
    assert isinstance(data["flight_end_date"], str)
    assert isinstance(data["contracted_impressions"], int) and data["contracted_impressions"] > 0
    assert isinstance(data["cpm_cents"], int) and data["cpm_cents"] > 0
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] > 0
    assert data["partial_credit_mode"] in [m.value for m in PartialCreditMode]
    assert data["campaign_status"] in [s.value for s in CampaignStatus]
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert data.get("approved_by_user_id") is None or isinstance(data["approved_by_user_id"], str)
    assert isinstance(data["reserved_estimated_cents"], int) and data["reserved_estimated_cents"] >= 0
    assert isinstance(data["delivered_impressions"], int) and data["delivered_impressions"] >= 0


def assert_reel(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("showtime_id", "")), "showtime_id must be a UUID"
    assert data["reel_status"] in [s.value for s in ReelStatus]
    assert data["capacity_seconds"] == 1200
    assert data["national_pool_seconds"] == 720
    assert data["local_pool_seconds"] == 480
    assert isinstance(data["national_used_seconds"], int) and 0 <= data["national_used_seconds"] <= 720
    assert isinstance(data["local_used_seconds"], int) and 0 <= data["local_used_seconds"] <= 480


def assert_slot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("reel_id", "")), "reel_id must be a UUID"
    assert is_valid_uuid(data.get("campaign_id", "")), "campaign_id must be a UUID"
    assert isinstance(data["start_offset_seconds"], int) and data["start_offset_seconds"] >= 0
    assert isinstance(data["duration_seconds"], int) and data["duration_seconds"] > 0
    assert data["slot_status"] in [s.value for s in SlotStatus]
    assert isinstance(data["estimated_cost_cents"], int) and data["estimated_cost_cents"] >= 0
    pf = data.get("play_factor")
    assert pf is None or pf in (0.0, 0.5, 1.0), f"play_factor must be null/0.0/0.5/1.0, got {pf!r}"
    ai = data.get("attributed_impressions")
    assert ai is None or (isinstance(ai, int) and ai >= 0)


def assert_playlog(data: dict):
    """Append-only record: id + created_at only from the common set; no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "PlayLog must not carry updated_at"
    assert "version" not in data, "PlayLog must not carry version"
    assert is_valid_uuid(data.get("slot_id", "")), "slot_id must be a UUID"
    assert data["outcome"] in [o.value for o in PlayLogOutcome]
    assert isinstance(data["played_at"], str) and data["played_at"]
    assert isinstance(data["reported_by_user_id"], str) and data["reported_by_user_id"]
    assert isinstance(data["reported_by_theater_id"], str) and data["reported_by_theater_id"]


def assert_attendance_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("showtime_id", "")), "showtime_id must be a UUID"
    assert isinstance(data["reported_attendance"], int) and data["reported_attendance"] >= 0
    aa = data.get("audited_attendance")
    assert aa is None or (isinstance(aa, int) and aa >= 0)
    assert data["report_status"] in [s.value for s in ReportStatus]
    assert isinstance(data["reported_by_user_id"], str) and data["reported_by_user_id"]
    assert data.get("reviewed_by_user_id") is None or isinstance(data["reviewed_by_user_id"], str)
    assert data.get("audited_by_user_id") is None or isinstance(data["audited_by_user_id"], str)


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("campaign_id", "")), "campaign_id must be a UUID"
    assert isinstance(data["period_start_date"], str)
    assert isinstance(data["period_end_date"], str)
    assert data["billing_status"] in [s.value for s in BillingStatus]
    assert data["audit_status"] in [s.value for s in AuditStatus]
    assert isinstance(data["provisional_impressions"], int) and data["provisional_impressions"] >= 0
    assert isinstance(data["provisional_amount_cents"], int) and data["provisional_amount_cents"] >= 0
    ai = data.get("audited_impressions")
    assert ai is None or (isinstance(ai, int) and ai >= 0)
    aac = data.get("audited_amount_cents")
    assert aac is None or (isinstance(aac, int) and aac >= 0)
    assert isinstance(data["applied_credit_cents"], int) and data["applied_credit_cents"] >= 0
    fac = data.get("final_amount_cents")
    assert fac is None or (isinstance(fac, int) and fac >= 0)
    assert data.get("issued_by_user_id") is None or isinstance(data["issued_by_user_id"], str)
    assert data.get("certified_by_user_id") is None or isinstance(data["certified_by_user_id"], str)


def assert_make_good(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("invoice_id", "")), "invoice_id must be a UUID"
    assert isinstance(data["shortfall_impressions"], int) and data["shortfall_impressions"] >= 0
    assert isinstance(data["under_delivery_pct"], (int, float)) and data["under_delivery_pct"] >= 0
    assert isinstance(data["credit_cents"], int) and data["credit_cents"] >= 0
    assert data["credit_status"] in [s.value for s in CreditStatus]
    assert isinstance(data["proposed_by_user_id"], str) and data["proposed_by_user_id"]
    assert data.get("reviewed_by_user_id") is None or isinstance(data["reviewed_by_user_id"], str)
    assert data.get("applied_by_user_id") is None or isinstance(data["applied_by_user_id"], str)


def assert_invoice_money_invariant(invoice: dict):
    """final_amount_cents + applied_credit_cents == audited_amount_cents once certified."""
    if invoice.get("audit_status") == AuditStatus.CERTIFIED.value:
        total = invoice["final_amount_cents"] + invoice["applied_credit_cents"]
        assert total == invoice["audited_amount_cents"], (
            f"Money invariant violated: final {invoice['final_amount_cents']} + "
            f"applied {invoice['applied_credit_cents']} != audited {invoice['audited_amount_cents']}"
        )


def assert_reel_pool_invariant(reel: dict):
    """Pool usage never exceeds pool capacity, and pools sum to total capacity."""
    assert reel["national_pool_seconds"] + reel["local_pool_seconds"] == reel["capacity_seconds"]
    assert reel["national_used_seconds"] <= reel["national_pool_seconds"]
    assert reel["local_used_seconds"] <= reel["local_pool_seconds"]

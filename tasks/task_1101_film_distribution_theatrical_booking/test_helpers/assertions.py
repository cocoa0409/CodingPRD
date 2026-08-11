"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, what: str = "resource"):
    assert is_valid_uuid(str(data.get("id", ""))), f"{what}.id must be a valid UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), f"{what}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(str(data.get("updated_at", ""))), f"{what}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{what}.version must be an integer"


def assert_distributor(data: dict):
    _assert_common_fields(data, "Distributor")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["territory"], str) and len(data["territory"]) > 0
    assert isinstance(data["week_epoch"], int) and data["week_epoch"] >= 0
    assert data["lifecycle_posture"] in ("ACTIVE", "FROZEN")


def assert_film(data: dict):
    _assert_common_fields(data, "Film")
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["genre"] in ("NARRATIVE", "DOCUMENTARY", "ANIMATION", "GENRE_HORROR")
    assert isinstance(data["runtime_minutes"], int) and data["runtime_minutes"] > 0
    assert data["rating"] in ("G", "PG", "PG13", "R", "NC17")
    assert data["release_pattern"] in ("WIDE", "LIMITED", "PLATFORM")
    assert data["lifecycle_status"] in (
        "PRE_RELEASE", "IN_RELEASE", "HOLDOVER_PHASE",
        "ANCILLARY_PENDING", "ANCILLARY_RELEASED", "PULLED",
    )
    assert isinstance(data["screens_committed"], int) and data["screens_committed"] >= 0


def assert_theatre(data: dict):
    _assert_common_fields(data, "Theatre")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["circuit"], str)
    assert isinstance(data["market_code"], str)
    assert isinstance(data["house_allowance_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "DARK")


def assert_screen(data: dict):
    _assert_common_fields(data, "Screen")
    assert isinstance(data["auditorium_label"], str)
    assert isinstance(data["seat_count"], int) and data["seat_count"] > 0
    assert data["projection_format"] in ("DCP_2K", "DCP_4K", "FILM_35MM")
    assert data["status"] in ("AVAILABLE", "BOOKED", "MAINTENANCE")


def assert_market(data: dict):
    _assert_common_fields(data, "Market")
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["population_tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert isinstance(data["weekly_coop_budget_cents"], int)
    assert isinstance(data["coop_committed_cents"], int) and data["coop_committed_cents"] >= 0


def assert_booking_agreement(data: dict):
    _assert_common_fields(data, "BookingAgreement")
    assert is_valid_uuid(str(data.get("film_id", ""))), "film_id must be a UUID"
    assert is_valid_uuid(str(data.get("theatre_id", ""))), "theatre_id must be a UUID"
    assert is_valid_uuid(str(data.get("screen_id", ""))), "screen_id must be a UUID"
    assert data["deal_status"] in (
        "PROPOSED", "COUNTERED", "ACCEPTED", "IN_PLAY",
        "HELD_OVER", "DECLINED", "CANCELLED", "COMPLETED",
    )
    assert data["print_status"] in (
        "NOT_ORDERED", "DCP_QUEUED", "DCP_SHIPPED", "DCP_DELIVERED",
        "KDM_ISSUED", "KEY_LIVE", "PRINT_STRUCK", "PRINT_RETURNED",
    )
    assert isinstance(data["min_weeks_committed"], int) and data["min_weeks_committed"] >= 0
    assert isinstance(data["weeks_played"], int) and data["weeks_played"] >= 0
    assert isinstance(data["week_one_rental_pct"], (int, float))
    assert isinstance(data["floor_pct"], (int, float))


def assert_aggregate_deal(data: dict):
    _assert_common_fields(data, "AggregateDeal")
    assert data["deal_status"] in ("DRAFT", "ACTIVE", "CLOSED", "VOIDED")
    assert isinstance(data["aggregate_rental_pct"], (int, float))
    assert isinstance(data["min_screens"], int)
    assert isinstance(data["aggregate_house_allowance_cents"], int)


def assert_dcp_shipment(data: dict):
    _assert_common_fields(data, "DCPShipment")
    assert data["content_format"] in ("DCP_2K", "DCP_4K", "FILM_35MM")
    assert data["status"] in ("QUEUED", "IN_TRANSIT", "DELIVERED", "RETURNED", "LOST")


def assert_kdm_key(data: dict):
    _assert_common_fields(data, "KDMKey")
    assert data["status"] in ("ISSUED", "LIVE", "EXPIRED", "REVOKED", "EXTENDED")
    assert isinstance(data["screen_cert_fingerprint"], str)


def assert_box_office_report(data: dict):
    _assert_common_fields(data, "BoxOfficeReport")
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["admissions"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "LOCKED", "VOIDED")


def assert_settlement(data: dict):
    _assert_common_fields(data, "Settlement")
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["net_cents"], int)
    assert isinstance(data["distributor_share_cents"], int)
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in (
        "PROVISIONAL", "PENDING_FINAL", "FINALIZED",
        "DISPUTED", "SETTLED", "WRITTEN_OFF",
    )


def assert_holdover_decision(data: dict):
    _assert_common_fields(data, "HoldoverDecision")
    assert data["decision"] in ("HOLD", "RELEASE", "AUTO_HOLD", "AUTO_RELEASE")
    assert isinstance(data["prior_week_gross_cents"], int)


def assert_marketing_commitment(data: dict):
    _assert_common_fields(data, "MarketingCommitment")
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["spent_cents"], int)
    assert data["status"] in ("DRAFT", "COMMITTED", "ACCRUING", "SETTLED", "CANCELLED")


def assert_zone_clearance(data: dict):
    _assert_common_fields(data, "ZoneClearance")
    assert data["status"] in ("GRANTED", "CHALLENGED", "UPHELD", "OVERRULED", "EXPIRED")
    assert isinstance(data["clearance_radius_km"], (int, float))


def assert_ancillary_window(data: dict):
    _assert_common_fields(data, "AncillaryWindow")
    assert data["window_kind"] in ("HOME_VIDEO", "TVOD", "SVOD", "AIRLINE")
    assert data["status"] in ("SCHEDULED", "HANDED_OFF", "CANCELLED", "VIOLATED")


def assert_settlement_money_conservation(data: dict):
    """PRD §3.7: exhibitor_share_cents is the net minus the distributor share;
    final payout is the distributor share plus the marketing offset."""
    assert data["exhibitor_share_cents"] == data["net_cents"] - data["distributor_share_cents"], (
        f"exhibitor_share {data['exhibitor_share_cents']} != net {data['net_cents']} "
        f"- distributor_share {data['distributor_share_cents']}"
    )
    assert data["final_distributor_payout_cents"] == (
        data["distributor_share_cents"] + data["marketing_offset_cents"]
    ), "final_distributor_payout_cents must equal distributor_share + marketing_offset"

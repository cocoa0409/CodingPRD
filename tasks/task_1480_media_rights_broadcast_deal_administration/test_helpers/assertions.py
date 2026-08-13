"""Entity assertions and domain invariant checkers (PRD §2.5 common fields)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_rights_asset(data: dict):
    _assert_common(data)
    assert isinstance(data["asset_code"], str) and data["asset_code"]
    assert isinstance(data["competition_name"], str)
    assert isinstance(data["season_label"], str)
    assert isinstance(data["total_package_pool"], int)
    assert isinstance(data["guaranteed_rating_basis_points"], int)
    assert data["status"] in ["OPEN", "PACKAGES_LOCKED", "AWARD_CLOSED", "RETIRED"]
    assert isinstance(data["active_package_count"], int)


def assert_broadcaster(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["home_territory"], str)
    assert isinstance(data["platform_classes"], list)
    assert data["credit_rating"] in ["INVESTMENT_GRADE", "SPECULATIVE", "UNRATED"]
    assert data["status"] in ["REGISTERED", "ACCREDITED", "SUSPENDED", "BARRED"]


def assert_rights_package(data: dict):
    _assert_common(data)
    assert isinstance(data["package_code"], str) and data["package_code"]
    assert isinstance(data["territory_code"], str)
    assert data["platform_class"] in [
        "LINEAR_TV", "SVOD", "AVOD", "MOBILE", "RADIO", "SOCIAL_CLIP",
    ]
    assert data["exclusivity_class"] in ["EXCLUSIVE", "CO_EXCLUSIVE", "NON_EXCLUSIVE"]
    assert isinstance(data["minimum_bid_cents"], int)
    assert isinstance(data["games_committed"], int)
    assert data["status"] in [
        "DRAFT", "OPEN_FOR_BIDS", "UNDER_NEGOTIATION", "AWARDED", "WITHDRAWN",
    ]


def assert_bid(data: dict):
    _assert_common(data)
    assert isinstance(data["bidder_id"], str)
    assert isinstance(data["offered_fee_cents"], int)
    assert isinstance(data["fee_cap_cents"], int)
    assert isinstance(data["production_commitment_games"], int)
    assert data["exclusivity_request"] in ["MATCH_PACKAGE", "NARROWER", "BROADER"]
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "SHORTLISTED", "COUNTERED",
        "ACCEPTED", "REJECTED", "WITHDRAWN", "EXPIRED",
    ]
    assert isinstance(data["round_number"], int)


def assert_deal(data: dict):
    _assert_common(data)
    assert isinstance(data["package_id"], str)
    assert isinstance(data["winning_bid_id"], str)
    assert isinstance(data["broadcaster_id"], str)
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["payment_delinquency_count"], int)
    assert isinstance(data["cumulative_rating_basis_points"], int)
    assert isinstance(data["accrued_shortfall_liability_cents"], int)
    assert isinstance(data["accrued_make_good_credit_cents"], int)
    assert data["posture"] in ["CLEAN", "WARNING", "FROZEN"]
    assert data["status"] in [
        "DRAFT", "EXECUTED", "ACTIVE", "RENEWAL_OPEN", "RENEWED", "LAPSED",
        "TERMINATED_BREACH", "TERMINATED_CONVENIENCE",
    ]


def assert_payment_milestone(data: dict):
    _assert_common(data)
    assert isinstance(data["season_index"], int)
    assert isinstance(data["sequence_in_season"], int)
    assert isinstance(data["base_amount_cents"], int)
    assert isinstance(data["late_fee_cents"], int)
    assert data["status"] in [
        "SCHEDULED", "INVOICED", "PAID", "OVERDUE", "CURED", "DEFAULTED",
    ]


def assert_production_obligation(data: dict):
    _assert_common(data)
    assert isinstance(data["season_index"], int)
    assert isinstance(data["games_required"], int)
    assert isinstance(data["games_delivered"], int)
    assert isinstance(data["shortfall_games"], int)
    assert isinstance(data["make_good_credit_cents"], int)
    assert isinstance(data["credit_settled_cents"], int)
    assert data["status"] in [
        "TRACKING", "MET", "SHORTFALL_DECLARED", "REMEDIED", "CREDITED",
    ]


def assert_broadcast_event(data: dict):
    _assert_common(data)
    assert isinstance(data["obligation_id"], str)
    assert isinstance(data["event_code"], str) and data["event_code"]
    assert data["status"] in [
        "SCHEDULED", "DELIVERED", "CANCELLED_BY_LEAGUE",
        "CANCELLED_BY_BROADCASTER", "NO_SHOW",
    ]


def assert_audience_measurement(data: dict):
    _assert_common(data)
    assert isinstance(data["broadcast_event_id"], str)
    assert isinstance(data["rating_basis_points"], int)
    assert data["source"] in ["PANEL", "CENSUS", "HYBRID"]
    assert data["status"] in ["PROVISIONAL", "CONFIRMED", "DISPUTED", "EXCLUDED"]


def assert_sublicense_request(data: dict):
    _assert_common(data)
    assert isinstance(data["sublicensee_name"], str)
    assert isinstance(data["sublicensee_territory"], str)
    assert data["sublicensee_platform_class"] in [
        "LINEAR_TV", "SVOD", "AVOD", "MOBILE", "RADIO", "SOCIAL_CLIP",
    ]
    assert isinstance(data["proposed_fee_cents"], int)
    assert data["status"] in ["PENDING", "APPROVED", "REJECTED", "REVOKED"]


def assert_blackout_window(data: dict):
    _assert_common(data)
    assert isinstance(data["territory_code"], str)
    assert data["platform_class"] in [
        "LINEAR_TV", "SVOD", "AVOD", "MOBILE", "RADIO", "SOCIAL_CLIP",
    ]


def assert_renewal_offer(data: dict):
    _assert_common(data)
    assert data["offer_source"] in ["INCUMBENT_BROADCASTER", "THIRD_PARTY_BIDDER"]
    assert isinstance(data["offeror_broadcaster_id"], str)
    assert isinstance(data["offered_fee_cents"], int)
    assert data["status"] in [
        "OPEN", "MATCHED", "SUPERSEDED", "EXERCISED", "LAPSED", "WITHDRAWN",
    ]


def assert_rights_conflict(data: dict):
    """Append-only monitor row: id + created_at present; updated_at/version absent."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "append-only row must not carry updated_at"
    assert "version" not in data, "append-only row must not carry version"
    assert data["conflict_type"] in [
        "EXCLUSIVITY_OVERLAP", "BLACKOUT_VIOLATION",
        "TERRITORY_COLLISION", "PLATFORM_COLLISION",
    ]
    assert isinstance(data["left_entity_id"], str)
    assert isinstance(data["right_entity_id"], str)


def assert_deal_invariants(data: dict):
    """Domain invariants that must hold on any deal read."""
    assert data["payment_delinquency_count"] >= 0
    assert data["cumulative_rating_basis_points"] >= 0
    assert data["accrued_shortfall_liability_cents"] >= 0
    assert data["accrued_make_good_credit_cents"] >= 0

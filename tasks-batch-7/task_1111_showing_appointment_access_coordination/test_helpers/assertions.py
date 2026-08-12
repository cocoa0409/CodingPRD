"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, label: str, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"{label}: id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}: created_at must be ISO 8601, got {data.get('created_at')!r}"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}: updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{label}: version must be a positive int, got {data.get('version')!r}"
    else:
        assert "updated_at" not in data, f"{label}: append-only record must not carry updated_at"
        assert "version" not in data, f"{label}: append-only record must not carry version"


def assert_seller(data: dict):
    _assert_common(data, "Seller")
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("contact_email"), str) and data["contact_email"]
    assert isinstance(data.get("approval_timeout_minutes"), int)
    assert isinstance(data.get("auto_approve"), bool)


def assert_agent(data: dict):
    _assert_common(data, "Agent")
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("license_number"), str) and data["license_number"]
    assert data.get("verification_status") in ("UNVERIFIED", "VERIFIED")
    assert data.get("standing") in ("GOOD_STANDING", "RESTRICTED", "SUSPENDED")
    assert isinstance(data.get("active_strike_points"), int) and data["active_strike_points"] >= 0


def assert_listing(data: dict):
    _assert_common(data, "Listing")
    assert is_valid_uuid(data.get("seller_id", "")), "Listing: seller_id must be a UUID"
    assert isinstance(data.get("address"), str) and data["address"]
    assert data.get("occupancy_type") in ("VACANT", "OCCUPIED")
    assert data.get("status") in ("ACTIVE", "PAUSED", "WITHDRAWN")
    assert isinstance(data.get("buffer_minutes"), int)
    assert isinstance(data.get("max_showings_per_day"), int)
    assert isinstance(data.get("min_notice_minutes"), int)
    assert isinstance(data.get("confirmed_showing_count"), int) and data["confirmed_showing_count"] >= 0


def assert_verification_case(data: dict):
    _assert_common(data, "VerificationCase")
    assert data.get("status") in ("SUBMITTED", "APPROVED", "REJECTED")
    assert isinstance(data.get("resubmission_count"), int) and data["resubmission_count"] >= 0


def assert_blackout_window(data: dict):
    _assert_common(data, "BlackoutWindow")
    assert is_valid_uuid(data.get("listing_id", "")), "BlackoutWindow: listing_id must be a UUID"
    assert is_iso8601_timestamp(data.get("start_at", "")), "BlackoutWindow: start_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_at", "")), "BlackoutWindow: end_at must be ISO 8601"


def assert_showing_request(data: dict):
    _assert_common(data, "ShowingRequest")
    assert is_valid_uuid(data.get("listing_id", "")), "ShowingRequest: listing_id must be a UUID"
    assert is_valid_uuid(data.get("buyer_agent_id", "")), "ShowingRequest: buyer_agent_id must be a UUID"
    assert is_iso8601_timestamp(data.get("start_at", "")), "ShowingRequest: start_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_at", "")), "ShowingRequest: end_at must be ISO 8601"
    assert data.get("status") in (
        "PENDING_APPROVAL", "APPROVED", "CONFIRMED", "DECLINED",
        "COMPLETED", "NO_SHOW", "CANCELLED", "EXPIRED",
    )
    assert isinstance(data.get("reschedule_count"), int) and data["reschedule_count"] >= 0


def assert_access_credential(data: dict):
    _assert_common(data, "AccessCredential")
    assert data.get("credential_type") in ("LOCKBOX_CODE", "DOOR_CODE", "SMART_LOCK")
    assert data.get("status") in ("ISSUED", "USED", "EXPIRED", "REVOKED")
    code = data.get("access_code")
    assert isinstance(code, str) and len(code) == 6 and code.isdigit(), (
        f"AccessCredential: access_code must be a 6-digit numeric string, got {code!r}"
    )
    assert is_iso8601_timestamp(data.get("active_from", "")), "AccessCredential: active_from must be ISO 8601"
    assert is_iso8601_timestamp(data.get("expires_at", "")), "AccessCredential: expires_at must be ISO 8601"


def assert_feedback_request(data: dict):
    _assert_common(data, "FeedbackRequest")
    assert data.get("status") in ("SCHEDULED", "SENT", "SUBMITTED", "EXPIRED", "CANCELLED")


def assert_strike_record(data: dict):
    _assert_common(data, "StrikeRecord")
    assert data.get("strike_type") in ("NO_SHOW", "LATE_CANCEL")
    assert data.get("status") in ("ACTIVE", "FORGIVEN", "EXPIRED")
    assert data.get("weight") in (10, 25), f"StrikeRecord: weight must be 10 or 25, got {data.get('weight')!r}"


def assert_activity_event(data: dict):
    """Append-only: id + created_at only, no updated_at/version."""
    _assert_common(data, "ActivityEvent", with_version=False)
    assert data.get("event_type") in (
        "REQUEST_CREATED", "APPROVED", "DECLINED", "RESCHEDULED", "CONFIRMED",
        "CANCELLED", "EXPIRED", "COMPLETED", "NO_SHOW", "CREDENTIAL_ISSUED",
        "CREDENTIAL_REDEEMED", "CREDENTIAL_REVOKED", "CREDENTIAL_EXPIRED",
        "FEEDBACK_SENT", "FEEDBACK_SUBMITTED", "STRIKE_ISSUED",
        "LISTING_PAUSED", "LISTING_RESUMED", "LISTING_WITHDRAWN",
    )
    assert data.get("actor_role") in ("BuyerAgent", "Seller", "ListingAgent", "PlatformAdmin", "SYSTEM")


def assert_listing_confirmed_count_invariant(listing: dict, confirmed_requests: list):
    """Listing.confirmed_showing_count must equal the number of requests in CONFIRMED."""
    assert listing["confirmed_showing_count"] == len(
        [r for r in confirmed_requests if r.get("status") == "CONFIRMED"]
    ), "confirmed_showing_count must equal the number of CONFIRMED requests on the listing"


def assert_agent_strike_points_invariant(agent: dict, active_strikes: list):
    """Agent.active_strike_points must equal the sum of weights of ACTIVE strikes."""
    expected = sum(s["weight"] for s in active_strikes if s.get("status") == "ACTIVE")
    assert agent["active_strike_points"] == expected, (
        f"active_strike_points {agent['active_strike_points']} != sum of ACTIVE strike weights {expected}"
    )

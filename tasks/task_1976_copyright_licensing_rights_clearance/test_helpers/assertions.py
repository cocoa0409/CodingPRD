"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp with or without fractional digits,
    truncated to second precision (PRD §2.5: "All datetime comparisons in
    this system are made at second precision.")."""
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def same_instant(actual: str, expected: str) -> bool:
    """True when two ISO 8601 timestamps denote the same instant at second
    precision. Used for domain datetime fields whose fractional-digit wire
    format PRD does not pin (PRD §2.2/§2.4 pin three fractional digits only
    for `api_request_timestamp` and the `created_at`/`updated_at` audit
    fields); the PRD pins the instant VALUE (e.g. §2.5's default clock,
    §3.7's received_at + 10 days, §3.9's term_end - 30 days)."""
    return _parse_instant(actual) == _parse_instant(expected)


def assert_same_instant(actual: str, expected: str) -> None:
    assert same_instant(actual, expected), (
        f"expected instant {expected!r}, got {actual!r}"
    )


# ---------------------------------------------------------------------------
# Common-field validators
# ---------------------------------------------------------------------------


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"version must be int, got {data.get('version')!r}"


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    # Append-only ledger: PRD §2.4 — no updated_at, no version.
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_asset(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["work_kind"] in {
        "MUSICAL_COMPOSITION",
        "SOUND_RECORDING",
        "FILM_CLIP",
        "STILL_IMAGE",
        "LITERARY_EXCERPT",
    }
    assert isinstance(data["permitted_media"], list)
    assert data["orphan_status"] in {"NOT_ORPHAN", "DILIGENCE_PENDING", "ORPHAN_CERTIFIED"}
    assert data["posture"] in {"CLEAR", "ENCUMBERED", "SUSPENDED", "RETIRED"}


def assert_rights_holder(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["holder_kind"] in {"PUBLISHER", "LABEL", "ESTATE", "COLLECTIVE", "INDIVIDUAL"}
    assert isinstance(data["mfn_floor_cents"], int)


def assert_diligence_log(data: dict):
    _assert_append_only_fields(data)
    assert data["search_channel"] in {
        "COPYRIGHT_OFFICE",
        "PERFORMING_RIGHTS_ORG",
        "UNION_GUILD",
        "COMMERCIAL_DATABASE",
        "DIRECT_OUTREACH",
    }
    assert data["outcome"] in {"HOLDER_FOUND", "NO_RESULT", "CONFLICTING_CLAIM"}


def assert_clearance_request(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {
        "SUBMITTED",
        "HOLDER_REVIEW",
        "NEGOTIATING",
        "APPROVED",
        "DENIED",
        "WITHDRAWN",
        "FAIR_USE_ROUTE",
        "LICENSED",
        "EXPIRED",
    }
    assert data["media"] in {
        "BROADCAST_TV",
        "STREAMING",
        "THEATRICAL",
        "RADIO",
        "SOCIAL",
        "PRINT",
    }
    assert data["territory"] in {"NA", "EMEA", "LATAM", "APAC", "WORLD"}
    assert isinstance(data["requested_units"], int) and data["requested_units"] >= 1
    assert isinstance(data["negotiation_round"], int) and data["negotiation_round"] >= 0


def assert_negotiation_round(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1
    assert isinstance(data["offered_fee_cents"], int)
    assert data["offered_by_role"] in {"NEGOTIATOR", "RIGHTS_HOLDER_REP"}
    assert data["outcome"] in {"OPEN", "ACCEPTED", "REJECTED", "SUPERSEDED"}


def assert_license(data: dict):
    _assert_common_fields(data)
    assert data["lifecycle"] in {"ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED"}
    assert data["fee_status"] in {"UNPAID", "PARTIALLY_PAID", "PAID", "REFUNDED"}
    assert isinstance(data["unit_limit"], int) and data["unit_limit"] >= 1
    assert isinstance(data["fee_agreed_cents"], int)
    assert isinstance(data["units_reserved"], int) and data["units_reserved"] >= 0
    assert isinstance(data["units_consumed_net"], int)
    assert isinstance(data["units_consumed_gross"], int) and data["units_consumed_gross"] >= 0


def assert_usage_reservation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {"HELD", "CONSUMED", "RELEASED", "FORFEITED"}
    assert isinstance(data["units"], int) and data["units"] >= 1


def assert_usage_event(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert data["posting_kind"] in {"POSTED", "STRUCK"}


def assert_license_payment(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["amount_cents"], int)


def assert_fair_use_assessment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {"DRAFT", "CERTIFIED", "REJECTED", "SUPERSEDED"}
    assert isinstance(data["factor_scores"], dict)
    for k in ("purpose", "nature", "amount", "market"):
        assert 1 <= data["factor_scores"][k] <= 4
    assert isinstance(data["composite_score"], int)
    assert isinstance(data["certified"], bool)


def assert_takedown_notice(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {"PENDING", "COUNTERED", "UPHELD", "RETRACTED"}
    assert is_iso8601_timestamp(data["received_at"])
    assert is_iso8601_timestamp(data["counter_notice_due_at"])


def assert_renewal_alert(data: dict):
    _assert_common_fields(data)
    assert data["status"] in {"SCHEDULED", "FIRED", "CANCELLED"}
    assert is_iso8601_timestamp(data["fires_at"])

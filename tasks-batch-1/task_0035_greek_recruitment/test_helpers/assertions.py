"""Entity assertions and domain invariant checkers (PRD §2.4, §2.10)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# --- Common-field helpers (PRD §2.4) -----------------------------------------
def assert_common_fields_full(data: dict):
    """Entities with common_fields=true: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version must start at 1"


def assert_common_fields_append_only(data: dict):
    """Append-only rows (DuesLedgerEntry): id + created_at only — no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "created_at must be ISO 8601"


# --- Chapter (PRD §3.1) ------------------------------------------------------
def assert_chapter(data: dict):
    assert_common_fields_full(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 80
    assert data["greek_type"] in ("SORORITY", "FRATERNITY")
    assert isinstance(data["quota_total"], int) and data["quota_total"] >= 1
    assert (
        isinstance(data["dues_per_member_cents"], int)
        and data["dues_per_member_cents"] >= 0
    )
    assert isinstance(data["legacy_priority_slots"], int)
    assert 0 <= data["legacy_priority_slots"] <= data["quota_total"]
    assert data["risk_status"] in ("GOOD_STANDING", "PROBATION", "SUSPENDED")
    assert isinstance(data["risk_points"], int) and data["risk_points"] >= 0
    assert isinstance(data["pledged_count"], int) and data["pledged_count"] >= 0
    assert data["pledged_count"] <= data["quota_total"]
    assert (
        isinstance(data["legacy_pledged_count"], int)
        and data["legacy_pledged_count"] >= 0
    )
    assert data["legacy_pledged_count"] <= data["legacy_priority_slots"]


# --- PNM (PRD §3.1) ----------------------------------------------------------
def assert_pnm(data: dict):
    assert_common_fields_full(data)
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert isinstance(data["gpa"], (int, float))
    assert 0.0 <= float(data["gpa"]) <= 4.0
    assert data["status"] in (
        "REGISTERED",
        "ACTIVE",
        "MATCHED",
        "WITHDRAWN",
        "BID_ACCEPTED",
        "BID_DECLINED",
    )
    assert isinstance(data["is_legacy"], bool)
    # is_legacy iff legacy_chapter_id is non-null
    if data.get("legacy_chapter_id") is None:
        assert data["is_legacy"] is False
    else:
        assert data["is_legacy"] is True


# --- RecruitmentRound (PRD §3.1) ---------------------------------------------
def assert_round(data: dict):
    assert_common_fields_full(data)
    assert isinstance(data["cycle_label"], str) and 1 <= len(data["cycle_label"]) <= 40
    assert data["phase"] in ("PARTY", "MUTUAL_SELECTION", "BID_DAY", "CLOSED")


# --- Party (PRD §3.2) --------------------------------------------------------
def assert_party(data: dict):
    assert_common_fields_full(data)
    assert isinstance(data["duration_minutes"], int)
    assert 30 <= data["duration_minutes"] <= 240
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["confirmed_count"], int) and data["confirmed_count"] >= 0
    assert data["confirmed_count"] <= data["capacity"]
    assert data["status"] in ("SCHEDULED", "OPEN", "COMPLETED", "CANCELLED")


# --- PartyInvitation (PRD §3.3) ----------------------------------------------
def assert_party_invitation(data: dict):
    assert_common_fields_full(data)
    assert data["rsvp_status"] in (
        "INVITED",
        "ACCEPTED",
        "DECLINED",
        "ATTENDED",
        "NO_SHOW",
    )


# --- Preference (PRD §3.4) ---------------------------------------------------
def assert_preference(data: dict):
    assert_common_fields_full(data)
    assert data["side"] in ("PNM_TO_CHAPTER", "CHAPTER_TO_PNM")
    assert isinstance(data["rank"], int) and data["rank"] >= 1


# --- BidMatch (PRD §3.5) -----------------------------------------------------
def assert_bid_match(data: dict):
    assert_common_fields_full(data)
    assert data["status"] in ("PROPOSED", "ACCEPTED", "DECLINED")
    assert data["priority_kind"] in ("LEGACY", "STANDARD")
    assert (
        isinstance(data["dues_charged_cents"], int)
        and data["dues_charged_cents"] >= 0
    )


# --- DuesLedgerEntry (PRD §3.6) ----------------------------------------------
def assert_dues_ledger_entry(data: dict):
    assert_common_fields_append_only(data)
    assert data["entry_kind"] in ("CHARGE", "REFUND")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["running_balance_cents"], int)
    # Append-only: must NOT carry version / updated_at (PRD §2.4)
    assert "version" not in data, "DuesLedgerEntry must not carry version (PRD §2.4)"
    assert (
        "updated_at" not in data
    ), "DuesLedgerEntry must not carry updated_at (PRD §2.4)"


# --- RiskIncident (PRD §3.8) -------------------------------------------------
def assert_risk_incident(data: dict):
    assert_common_fields_full(data)
    assert isinstance(data["severity_points"], int)
    assert 1 <= data["severity_points"] <= 10
    assert data["status"] in ("ACTIVE", "EXPIRED", "DISMISSED")
    assert isinstance(data["reason"], str) and 1 <= len(data["reason"]) <= 200

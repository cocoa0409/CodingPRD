"""Entity assertions and domain invariant checkers."""

import datetime as _dt

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_audit_columns(data: dict, entity: str) -> None:
    """PRD 2.4 common columns: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def assert_club_member(data: dict) -> None:
    _assert_audit_columns(data, "ClubMember")
    assert isinstance(data["full_name"], str) and data["full_name"].strip()
    assert "@" in data["email"], "email must contain an at sign"
    assert data["measurer_license_id"] is None or isinstance(data["measurer_license_id"], str)
    assert data["judge_certification_level"] in [
        "NONE", "CLUB", "REGIONAL", "NATIONAL", "INTERNATIONAL",
    ]
    assert data["safety_course_expiry_utc"] is None or is_iso8601_timestamp(
        data["safety_course_expiry_utc"]
    )
    assert isinstance(data["assigned_duty_minutes"], int)
    assert data["assigned_duty_minutes"] >= 0, "duty ledger must never go negative"


def assert_boat(data: dict) -> None:
    _assert_audit_columns(data, "Boat")
    assert 3 <= len(data["sail_number"]) <= 12
    assert isinstance(data["boat_name"], str) and data["boat_name"].strip()
    assert is_valid_uuid(data["owner_member_id"])
    assert data["boat_type"] in ["MONOHULL", "MULTIHULL", "KEELBOAT_SPORT"]
    assert 0 < data["loa_meters"] <= 40


def assert_rating_certificate(data: dict) -> None:
    _assert_audit_columns(data, "RatingCertificate")
    assert is_valid_uuid(data["boat_id"])
    assert data["rule_code"] in ["TOD_PHRF", "TOT_ORC"]
    assert data["status"] in ["DRAFT", "ISSUED", "SUSPENDED", "SUPERSEDED"]
    assert is_valid_uuid(data["measured_by_member_id"])
    assert is_iso8601_timestamp(data["valid_from"])
    assert is_iso8601_timestamp(data["valid_until"])
    assert data["valid_until"] > data["valid_from"], (
        "valid_until must fall strictly after valid_from"
    )
    assert_decimal_places(data["raw_speed_index"], 4, "raw_speed_index")
    assert_decimal_places(data["band_key_spm"], 1, "band_key_spm")
    if data["rule_code"] == "TOD_PHRF":
        assert -30.0 <= data["rating_value"] <= 300.0
        assert_decimal_places(data["rating_value"], 1, "rating_value")
        assert data["band_key_spm"] == pytest.approx(data["rating_value"], abs=1e-9), (
            "under TOD_PHRF band_key_spm is set equal to rating_value"
        )
    else:
        assert 0.5000 <= data["rating_value"] <= 1.6000
        assert_decimal_places(data["rating_value"], 4, "rating_value")


def assert_regatta(data: dict) -> None:
    _assert_audit_columns(data, "Regatta")
    assert 1 <= len(data["name"]) <= 120
    assert data["status"] in ["DRAFT", "NOR_PUBLISHED", "SI_PUBLISHED", "RACING", "SCORED"]
    assert data["scoring_system"] in ["LOW_POINT", "BONUS_POINT"]
    assert data["discard_policy"] in ["NONE", "ONE_PER_FIVE", "ONE_PER_FOUR"]
    assert data["handicap_basis"] in ["PER_CERTIFICATE", "UNIFIED_TOD"]
    assert data["safety_category"] in ["CAT_4", "CAT_3", "CAT_2"]
    assert 1 <= data["planned_race_count"] <= 20
    assert 2 <= data["fleet_minimum"] <= 20
    assert 15 <= data["protest_time_limit_minutes"] <= 480
    assert 2 <= data["jury_quorum_required"] <= 7
    assert is_iso8601_timestamp(data["series_start_utc"])
    for counter in ("nor_revision", "si_revision", "confirmed_division_count", "final_race_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_race_document(data: dict) -> None:
    _assert_audit_columns(data, "RaceDocument")
    assert is_valid_uuid(data["regatta_id"])
    assert data["doc_type"] in ["NOR", "SI"]
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["status"] in ["PUBLISHED", "SUPERSEDED"]
    assert is_iso8601_timestamp(data["effective_utc"])


def assert_division(data: dict) -> None:
    _assert_audit_columns(data, "Division")
    assert is_valid_uuid(data["regatta_id"])
    assert 1 <= len(data["code"]) <= 8
    assert data["boat_type_filter"] in ["MONOHULL", "MULTIHULL", "KEELBOAT_SPORT", "ANY"]
    assert data["rating_band_high"] > data["rating_band_low"], (
        "the high edge must be strictly greater than the low edge"
    )
    assert 2 <= data["min_entries"] <= 20
    assert data["status"] in ["PROVISIONAL", "CONFIRMED", "MERGED"]
    assert data["accepted_entry_count"] <= data["assigned_entry_count"], (
        "accepted entries are a subset of assigned entries"
    )


def assert_entry(data: dict) -> None:
    _assert_audit_columns(data, "Entry")
    assert is_valid_uuid(data["regatta_id"])
    assert is_valid_uuid(data["boat_id"])
    assert is_valid_uuid(data["certificate_id"])
    assert is_valid_uuid(data["helm_member_id"])
    assert 1 <= data["declared_crew_count"] <= 20
    assert data["registration_status"] in [
        "SUBMITTED", "ACCEPTED", "RATING_INVALID", "WITHDRAWN",
    ]
    assert data["inspection_status"] in ["NOT_INSPECTED", "PASSED", "FAILED"]
    assert isinstance(data["crew_manifest"], list)
    assert data["registered_crew_count"] == len(data["crew_manifest"]), (
        "registered_crew_count is the length of crew_manifest"
    )
    assert_decimal_places(data["crew_weight_kg"], 1, "crew_weight_kg")
    assert isinstance(data["discarded_race_numbers"], list)
    helms = [c for c in data["crew_manifest"] if c["position"] == "HELM"]
    assert len(helms) <= 1, "a manifest holds at most one element with position HELM"


def assert_mark_boat(data: dict) -> None:
    _assert_audit_columns(data, "MarkBoat")
    assert is_valid_uuid(data["regatta_id"])
    assert isinstance(data["call_sign"], str) and data["call_sign"].strip()
    assert 1 <= data["crew_capacity"] <= 12
    assert 1 <= data["concurrent_assignment_limit"] <= 6
    assert 0 <= data["turnaround_buffer_minutes"] <= 120
    assert isinstance(data["committed_minutes"], int) and data["committed_minutes"] >= 0


def assert_duty_assignment(data: dict) -> None:
    _assert_audit_columns(data, "DutyAssignment")
    assert is_valid_uuid(data["regatta_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["position"] in [
        "PRO", "TIMEKEEPER", "SIGNALS", "MARK_BOAT_DRIVER", "SAFETY_BOAT",
    ]
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert data["window_end_utc"] > data["window_start_utc"], (
        "the end must fall strictly after the start"
    )
    assert isinstance(data["duty_minutes"], int), "duty minutes are whole integers"
    assert data["status"] in ["PROPOSED", "CONFIRMED", "RELEASED"]
    if data["position"] in ("MARK_BOAT_DRIVER", "SAFETY_BOAT"):
        assert data["mark_boat_id"] is not None
    else:
        assert data["mark_boat_id"] is None


def assert_race(data: dict) -> None:
    _assert_audit_columns(data, "Race")
    assert is_valid_uuid(data["regatta_id"])
    assert 1 <= data["race_number"] <= 20
    assert data["course_code"] in ["WINDWARD_LEEWARD", "TRIANGLE", "DISTANCE_COASTAL"]
    assert 0 < data["course_distance_nm"] <= 300
    assert is_iso8601_timestamp(data["scheduled_start_utc"])
    assert data["start_status"] in [
        "PENDING", "SEQUENCE_STARTED", "GENERAL_RECALLED", "STARTED", "ABANDONED",
    ]
    assert data["scoring_status"] in ["NOT_SCORED", "PROVISIONAL", "FINAL"]
    assert isinstance(data["general_recall_count"], int) and data["general_recall_count"] >= 0
    assert isinstance(data["black_flag_active"], bool)
    assert data["start_blocked_reason"] in (None, "DIVISION_UNDER_MINIMUM"), (
        "DIVISION_UNDER_MINIMUM is the only value start_blocked_reason ever takes"
    )
    assert isinstance(data["rescore_count"], int) and data["rescore_count"] >= 0
    assert_decimal_places(data["points_pool_total"], 1, "points_pool_total")


def assert_race_result(data: dict) -> None:
    _assert_audit_columns(data, "RaceResult")
    assert is_valid_uuid(data["race_id"])
    assert is_valid_uuid(data["entry_id"])
    assert data["finish_status"] in [
        "FINISHED", "DNF", "DNS", "RET", "DNC", "OCS", "DSQ", "RDG",
    ]
    assert data["penalty_percent"] in [0, 20, 30, 40]
    assert isinstance(data["voided"], bool)
    assert isinstance(data["discardable"], bool)
    if data["finish_status"] == "FINISHED":
        assert data["elapsed_seconds"] is not None
        assert 0 < data["elapsed_seconds"] <= 604800
    else:
        assert data["corrected_seconds"] is None, (
            "corrected_seconds is written only for a FINISHED result"
        )
    if data["corrected_seconds"] is not None:
        assert_decimal_places(data["corrected_seconds"], 1, "corrected_seconds")
    assert_decimal_places(data["points"], 1, "points")


def assert_recall_event(data: dict) -> None:
    """A recall signal record is append-only: it carries only `id` and
    `created_at`, and has neither `updated_at` nor `version` (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "RecallEvent.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "a RecallEvent has no updated_at"
    assert "version" not in data, "a RecallEvent has no version"
    assert is_valid_uuid(data["race_id"])
    assert data["recall_type"] in ["INDIVIDUAL", "GENERAL"]
    if data["recall_type"] == "GENERAL":
        assert data["entry_id"] is None, "entry_id must be null for GENERAL"
    else:
        assert is_valid_uuid(data["entry_id"]), "entry_id is required for INDIVIDUAL"
    assert is_iso8601_timestamp(data["signal_utc"])
    assert is_valid_uuid(data["recorded_by_member_id"])
    assert isinstance(data["black_flag_applied"], bool)


def assert_jury_panel(data: dict) -> None:
    _assert_audit_columns(data, "JuryPanel")
    assert is_valid_uuid(data["regatta_id"])
    assert is_valid_uuid(data["chair_member_id"])
    assert data["status"] in ["FORMING", "SEATED"]
    assert isinstance(data["seats"], list) and len(data["seats"]) >= 1
    non_recused = [s for s in data["seats"] if not s["recused"]]
    assert data["seated_member_count"] == len(non_recused), (
        "seated_member_count is the number of seats whose recused flag is false"
    )
    assert data["seats"][0]["seat_role"] == "CHAIR"
    for seat in data["seats"]:
        assert seat["seat_role"] in ["CHAIR", "MEMBER"]
        assert isinstance(seat["recused"], bool)
        assert is_iso8601_timestamp(seat["seated_utc"])


def assert_protest(data: dict) -> None:
    _assert_audit_columns(data, "Protest")
    assert is_valid_uuid(data["regatta_id"])
    assert is_valid_uuid(data["race_id"])
    assert is_valid_uuid(data["protestor_entry_id"])
    assert is_valid_uuid(data["protestee_entry_id"])
    assert data["protestor_entry_id"] != data["protestee_entry_id"], (
        "the two parties must be different entries"
    )
    assert is_iso8601_timestamp(data["incident_utc"])
    assert is_iso8601_timestamp(data["filed_utc"])
    assert data["status"] in [
        "FILED", "HEARING_SCHEDULED", "HEARD", "DECIDED", "REOPENED", "INVALID",
    ]
    assert data["decision"] in [
        "NONE", "PENALTY_DSQ", "PENALTY_SCORING_20", "DISMISSED", "REDRESS_GRANTED",
    ]
    assert isinstance(data["evidence_log"], list)
    assert data["evidence_count"] == len(data["evidence_log"]), (
        "evidence_count is the length of evidence_log"
    )
    assert data["reopen_count"] in (0, 1), (
        "reopening is available once and only once per protest"
    )


def assert_series_standing(data: dict) -> None:
    assert is_valid_uuid(data["entry_id"])
    assert isinstance(data["races_counted"], int) and data["races_counted"] >= 0
    assert isinstance(data["discarded_race_numbers"], list)
    assert_decimal_places(data["gross_points"], 1, "gross_points")
    assert_decimal_places(data["net_points"], 1, "net_points")
    assert data["net_points"] <= data["gross_points"] + 1e-9, (
        "net points are gross points minus the discarded points"
    )
    assert data["rank"] is None or (isinstance(data["rank"], int) and data["rank"] >= 1)


def assert_staffing_readout(data: dict) -> None:
    assert is_valid_uuid(data["race_id"])
    assert isinstance(data["staffing_ready"], bool)
    assert isinstance(data["staffed_position_codes"], list)
    assert isinstance(data["missing_position_codes"], list)
    assert data["staffed_position_codes"] == sorted(data["staffed_position_codes"]), (
        "staffed_position_codes holds the sorted, distinct positions on station"
    )
    assert len(set(data["staffed_position_codes"])) == len(data["staffed_position_codes"])
    assert is_iso8601_timestamp(data["coverage_window_start_utc"])
    assert is_iso8601_timestamp(data["coverage_window_end_utc"])
    assert data["staffing_ready"] is (len(data["missing_position_codes"]) == 0)


def assert_same_instant(actual, expected, label: str = "instant") -> None:
    """Assert two ISO 8601 UTC strings name the same instant.

    PRD 2.4 fixes "ISO 8601 UTC format with three fractional digits" for
    `created_at` and `updated_at` only, and PRD 2.2 for `api_request_timestamp`.
    It fixes no rendering for the instants the server stamps from the logical
    clock (`results_closed_utc`, `filed_utc`, `recorded_utc`, `seated_utc`) or
    computes (`coverage_window_start_utc`, `coverage_window_end_utc`), and it
    writes clock values itself without fractional digits — "the clock reads
    exactly `2026-08-01T00:00:00Z`". Those fields are therefore compared as
    instants, so that a server rendering `...:00Z` and one rendering
    `...:00.000Z` are both accepted, while the instant itself stays exact.
    """
    assert is_iso8601_timestamp(actual), f"{label} must be ISO 8601 UTC, got {actual!r}"
    assert is_iso8601_timestamp(expected), f"expected {label} must be ISO 8601 UTC"
    parsed_actual = _dt.datetime.strptime(_normalise_instant(actual), _INSTANT_FMT)
    parsed_expected = _dt.datetime.strptime(_normalise_instant(expected), _INSTANT_FMT)
    assert parsed_actual == parsed_expected, (
        f"{label} must be the instant {expected!r}, got {actual!r}"
    )


_INSTANT_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def _normalise_instant(value: str) -> str:
    body = value[:-1] if value.endswith(("Z", "z")) else value
    return body if "." in body else body + ".000"


# ── Precision and identity helpers ─────────────────────────────────────────
def assert_decimal_places(value, places: int, label: str = "value") -> None:
    """PRD 2.5 fixes the rounding point of every published figure."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round(float(value), places) == pytest.approx(float(value), abs=1e-9), (
        f"{label} must be rounded to {places} decimal place(s), got {value!r}"
    )


def assert_duty_minutes_identity(member_totals, assignment_rows) -> None:
    """PRD 2.12: summed over every club member, `assigned_duty_minutes` equals
    the summed `duty_minutes` of every duty assignment whose `status` is
    `PROPOSED` or `CONFIRMED`."""
    ledger = sum(member_totals)
    booked = sum(
        row["duty_minutes"] for row in assignment_rows
        if row["status"] in ("PROPOSED", "CONFIRMED")
    )
    assert ledger == booked, (
        f"duty-minutes identity broken: ledgers total {ledger}, "
        f"non-released assignments total {booked}"
    )


def assert_series_points_identity(accepted_entries, races) -> None:
    """PRD 2.12: summed over the regatta's `ACCEPTED` entries,
    `series_points_gross` equals the summed `points_pool_total` of the regatta's
    races whose `scoring_status` is `FINAL` and whose `start_status` is not
    `ABANDONED`. Both sides are compared exactly, at 1 decimal place."""
    entry_side = round(sum(e["series_points_gross"] for e in accepted_entries), 1)
    race_side = round(
        sum(
            r["points_pool_total"] for r in races
            if r["scoring_status"] == "FINAL" and r["start_status"] != "ABANDONED"
        ),
        1,
    )
    assert entry_side == pytest.approx(race_side, abs=0.05), (
        f"series-points identity broken: entries total {entry_side}, "
        f"counted races total {race_side}"
    )

"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_iso_instant_equal(actual, expected):
    """Compare two ISO 8601 timestamps as instants, ignoring renderer details.

    PRD §2.4 pins the three-fractional-digit rendering only for `created_at` /
    `updated_at` (and §2.2 for `api_request_timestamp`). Every other datetime
    field — `validity_expires_at`, `closed_at`, `retention_expires_at`,
    `retention_expires_at_snapshot`, etc. — has its *instant* pinned by the
    workflow rules but not its string rendering, so these comparisons parse
    both sides and compare the instants.
    """
    from datetime import datetime, timezone

    def _parse(v):
        assert isinstance(v, str), f"expected an ISO 8601 string, got {v!r}"
        s = v[:-1] + "+00:00" if v.endswith("Z") else v
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    assert _parse(actual) == _parse(expected), (
        f"{actual!r} != {expected!r} (instant comparison)"
    )


def _assert_common_fields(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity_label}.version must be an int"


def _assert_append_only_fields(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    # Append-only audit records carry neither updated_at nor version (PRD §2.4).
    assert "updated_at" not in data, f"{entity_label} must not carry updated_at"
    assert "version" not in data, f"{entity_label} must not carry version"


def assert_vendor(data: dict):
    _assert_common_fields(data, "AssessmentVendor")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["security_clearance_tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert isinstance(data["content_copies_outstanding"], int)
    assert data["content_copies_outstanding"] >= 0, "content ledger never goes negative"


def assert_content_ledger_event(data: dict):
    _assert_append_only_fields(data, "ContentLedgerEvent")
    assert data["direction"] in ("DISTRIBUTE", "DESTROY")
    assert isinstance(data["copies"], int) and data["copies"] >= 1
    assert isinstance(data["note"], str) and len(data["note"]) >= 10


def assert_instrument(data: dict):
    _assert_common_fields(data, "AssessmentInstrument")
    assert is_valid_uuid(data.get("vendor_id", ""))
    assert data["instrument_type"] in (
        "COGNITIVE_ABILITY", "PERSONALITY", "SKILLS_SIMULATION", "JOB_KNOWLEDGE",
    )
    assert isinstance(data["max_score"], int) and data["max_score"] >= 1
    assert isinstance(data["pass_floor"], int)
    assert 0 <= data["pass_floor"] < data["max_score"]
    assert data["validation_status"] in (
        "DRAFT", "VALIDATION_REVIEW", "VALIDATED", "EXPIRED", "REVALIDATION", "RETIRED",
    )
    assert isinstance(data["vendor_suspended"], bool)
    assert isinstance(data["adverse_impact_monitor_enabled"], bool)


def assert_evidence(data: dict):
    _assert_common_fields(data, "ValidationEvidence")
    assert data["evidence_type"] in ("CRITERION", "CONTENT", "CONSTRUCT")
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_until", ""))


def assert_guide(data: dict):
    _assert_common_fields(data, "InterviewGuide")
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["status"] in ("DRAFT", "PILOT", "APPROVED", "RETIRED")
    assert isinstance(data["rubric_items"], list)
    for item in data["rubric_items"]:
        assert isinstance(item["competency_code"], str)
        assert 0 < item["weight"] <= 1
        assert isinstance(item["scale_max"], int) and 2 <= item["scale_max"] <= 10
    assert data["scoring_mode"] in ("RAW", "LENIENCY_ADJUSTED")
    assert isinstance(data["version_label"], int) and data["version_label"] >= 1
    assert isinstance(data["pinned_cycle_count"], int) and data["pinned_cycle_count"] >= 0


def assert_requisition(data: dict):
    _assert_common_fields(data, "Requisition")
    assert isinstance(data["openings_count"], int) and data["openings_count"] >= 1
    assert isinstance(data["filled_count"], int) and data["filled_count"] >= 0
    assert data["status"] in ("OPEN", "FILLED", "CLOSED")
    assert isinstance(data["retention_days"], int)


def assert_cycle(data: dict):
    _assert_common_fields(data, "AssessmentCycle")
    assert is_valid_uuid(data.get("requisition_id", ""))
    assert is_valid_uuid(data.get("instrument_id", ""))
    assert is_valid_uuid(data.get("guide_id", ""))
    assert data["posture"] in ("SETUP", "ACTIVE", "FROZEN", "SCORING", "DECIDED", "CLOSED")
    assert isinstance(data["max_sessions_per_day"], int)
    assert isinstance(data["active_candidate_count"], int)
    assert isinstance(data["decisions_finalized_count"], int)


def assert_candidate(data: dict):
    _assert_common_fields(data, "Candidate")
    assert isinstance(data["external_ref"], str) and len(data["external_ref"]) > 0
    assert data["group_code"] in (
        "GROUP_A", "GROUP_B", "GROUP_C", "GROUP_D", "UNDISCLOSED",
    )
    assert data["status"] in ("ACTIVE", "WITHDRAWN")


def assert_assessment(data: dict):
    _assert_common_fields(data, "CandidateAssessment")
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert is_valid_uuid(data.get("candidate_id", ""))
    assert data["admin_status"] in (
        "INVITED", "SCHEDULED", "ACCOMMODATION_HOLD", "IN_PROGRESS",
        "COMPLETED", "NO_SHOW", "CANCELLED", "PURGED",
    )
    assert data["feedback_status"] in ("NOT_SENT", "SENT", "NOT_APPLICABLE")
    assert isinstance(data["accommodation_extension_days"], int)


def assert_accommodation_request(data: dict):
    _assert_common_fields(data, "AccommodationRequest")
    assert data["request_type"] in (
        "EXTENDED_TIME", "ALTERNATE_FORMAT", "SCREEN_READER", "OTHER",
    )
    assert data["status"] in ("PENDING", "APPROVED", "DENIED", "WITHDRAWN")


def assert_interviewer(data: dict):
    _assert_common_fields(data, "Interviewer")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["committed_minutes_total"], int)
    assert data["committed_minutes_total"] >= 0, "committed minutes never go negative"


def assert_calibration(data: dict):
    _assert_common_fields(data, "CalibrationRecord")
    assert is_valid_uuid(data.get("interviewer_id", ""))
    assert is_valid_uuid(data.get("guide_id", ""))
    assert data["status"] in ("TRAINED", "CALIBRATED", "LAPSED")


def assert_session(data: dict):
    _assert_common_fields(data, "InterviewSession")
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert is_valid_uuid(data.get("candidate_id", ""))
    assert is_valid_uuid(data.get("interviewer_id", ""))
    assert is_valid_uuid(data.get("guide_id", ""))
    assert data["status"] in ("SCHEDULED", "COMPLETED", "SCORED", "CANCELLED")


def assert_scorecard(data: dict):
    _assert_common_fields(data, "Scorecard")
    assert is_valid_uuid(data.get("session_id", ""))
    assert is_valid_uuid(data.get("interviewer_id", ""))
    assert is_valid_uuid(data.get("candidate_id", ""))
    assert data["status"] in ("DRAFT", "SUBMITTED", "VOIDED")
    assert data["overall_recommendation"] in ("STRONG_YES", "YES", "NO", "STRONG_NO")
    assert isinstance(data["redacted"], bool)


def assert_decision(data: dict):
    _assert_common_fields(data, "HiringDecision")
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert is_valid_uuid(data.get("candidate_id", ""))
    assert data["decision"] in ("ADVANCE", "HOLD", "REJECT")
    assert data["status"] == "FINALIZED"
    assert isinstance(data["quorum_required_at_decision"], int)
    assert isinstance(data["quorum_submitted_at_decision"], int)


def assert_snapshot(data: dict):
    _assert_common_fields(data, "AdverseImpactSnapshot")
    assert data["snapshot_type"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["group_breakdowns"], list)
    for entry in data["group_breakdowns"]:
        assert entry["group_code"] in (
            "GROUP_A", "GROUP_B", "GROUP_C", "GROUP_D", "UNDISCLOSED",
        )
        assert entry.get("excluded_reason") in (
            None, "INSUFFICIENT_N", "NO_SELECTIONS", "UNDISCLOSED",
        )
    assert isinstance(data["flagged"], bool)


def assert_purge_event(data: dict):
    _assert_append_only_fields(data, "RetentionPurgeEvent")
    assert data["event_type"] == "ASSESSMENT_PURGED"
    assert is_valid_uuid(data.get("candidate_assessment_id", ""))


def get_group_breakdown(snapshot: dict, group_code: str) -> dict:
    """Locate one group's breakdown entry on an adverse-impact snapshot."""
    for entry in snapshot["group_breakdowns"]:
        if entry["group_code"] == group_code:
            return entry
    raise AssertionError(
        f"snapshot {snapshot.get('id')} lacks a breakdown entry for {group_code}; "
        f"has {[e['group_code'] for e in snapshot['group_breakdowns']]}"
    )

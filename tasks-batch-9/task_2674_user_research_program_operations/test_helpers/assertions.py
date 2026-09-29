"""Shape and invariant assertions for every resource type."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    POOL_CLOSED_UTILIZATION,
    POOL_RESTRICTED_UTILIZATION,
    SUPPRESSION_RATIO_THRESHOLD,
)
from .types import (
    ArtifactLifecycleState,
    ArtifactType,
    ConsentStatus,
    DecisionStatus,
    ExecutionStatus,
    FindingStatus,
    FollowUpStatus,
    GuideStatus,
    IncentiveState,
    ParticipantStatus,
    PoolStatus,
    PoolType,
    QuestionType,
    ReadoutStatus,
    RecommendedAction,
    RecruitmentStatus,
    RecruitmentStatusDimension,
    RequestStatus,
    ResearchMethod,
    Reversibility,
    Severity,
    StrengthVariant,
    ThemeStatus,
    WeightClass,
)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """Every resource carries a UUID id, both timestamps and a version."""
    assert is_valid_uuid(data.get("id")), f"id is not a UUID string: {data.get('id')!r}"
    assert "-" in str(data["id"]), f"id must be an unprefixed UUID, got {data['id']!r}"
    assert is_iso8601_timestamp(
        data.get("created_at")
    ), f"created_at is not an ISO 8601 timestamp: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at")
    ), f"updated_at is not an ISO 8601 timestamp: {data.get('updated_at')!r}"
    assert isinstance(
        data.get("version"), int
    ), f"version must be an integer, got {data.get('version')!r}"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def _assert_enum(data: Dict[str, Any], field: str, enum_cls: Any) -> None:
    value = data.get(field)
    allowed = [m.value for m in enum_cls]
    assert value in allowed, f"{field}={value!r} is outside {allowed}"


def _assert_int(data: Dict[str, Any], field: str, minimum: Optional[int] = None) -> None:
    value = data.get(field)
    assert isinstance(value, int) and not isinstance(
        value, bool
    ), f"{field} must be an integer, got {value!r}"
    if minimum is not None:
        assert value >= minimum, f"{field} must be >= {minimum}, got {value}"


def _assert_number(data: Dict[str, Any], field: str) -> None:
    value = data.get(field)
    assert isinstance(value, (int, float)) and not isinstance(
        value, bool
    ), f"{field} must be numeric, got {value!r}"


def _assert_nullable_timestamp(data: Dict[str, Any], field: str) -> None:
    value = data.get(field)
    if value is not None:
        assert is_iso8601_timestamp(
            value
        ), f"{field} is not an ISO 8601 timestamp: {value!r}"


# ---------------------------------------------------------------------------
# Roadmap decisions and research requests
# ---------------------------------------------------------------------------
def assert_roadmap_decision(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("title"), str) and data["title"], "title must be non-empty"
    assert is_iso8601_timestamp(data.get("decision_deadline")) or isinstance(
        data.get("decision_deadline"), str
    ), "decision_deadline must be an ISO 8601 instant"
    _assert_enum(data, "reversibility", Reversibility)
    _assert_int(data, "impacted_user_count", minimum=0)
    _assert_enum(data, "status", DecisionStatus)
    _assert_number(data, "evidence_confidence")
    _assert_nullable_timestamp(data, "locked_at")


def assert_research_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("roadmap_decision_id"), str)
    assert isinstance(data.get("requester_user_id"), str) and data["requester_user_id"]
    assert isinstance(data.get("question"), str) and data["question"]
    _assert_enum(data, "question_type", QuestionType)
    assert data.get("evidence_gap") in ("NONE", "PARTIAL", "FULL")
    _assert_enum(data, "status", RequestStatus)
    if data.get("priority_score") is not None:
        _assert_number(data, "priority_score")
    if data.get("recommended_method") is not None:
        _assert_enum(data, "recommended_method", ResearchMethod)
    if data.get("approved_method") is not None:
        _assert_enum(data, "approved_method", ResearchMethod)
    _assert_int(data, "revision_round", minimum=0)
    _assert_nullable_timestamp(data, "triaged_at")


# ---------------------------------------------------------------------------
# Pools and participants
# ---------------------------------------------------------------------------
def assert_participant_pool(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("name"), str) and data["name"]
    _assert_enum(data, "pool_type", PoolType)
    _assert_int(data, "contact_cap_per_window", minimum=1)
    _assert_int(data, "contact_window_days", minimum=1)
    _assert_int(data, "incentive_budget_cents", minimum=0)
    _assert_int(data, "incentive_reserved_cents", minimum=0)
    _assert_int(data, "incentive_paid_cents", minimum=0)
    _assert_int(data, "incentive_available_cents")
    if data.get("last_estimate_cents") is not None:
        _assert_int(data, "last_estimate_cents")
    assert isinstance(data.get("settled_study_ids"), list)
    _assert_enum(data, "status", PoolStatus)
    _assert_int(data, "participant_count", minimum=0)
    _assert_int(data, "suppressed_participant_count", minimum=0)
    assert_ledger_partition(data)


def assert_ledger_partition(pool: Dict[str, Any]) -> None:
    """available + reserved + paid == budget, at every observable instant."""
    total = (
        pool["incentive_available_cents"]
        + pool["incentive_reserved_cents"]
        + pool["incentive_paid_cents"]
    )
    assert total == pool["incentive_budget_cents"], (
        "incentive ledger partition broken: "
        f"available {pool['incentive_available_cents']} + reserved "
        f"{pool['incentive_reserved_cents']} + paid {pool['incentive_paid_cents']} "
        f"!= budget {pool['incentive_budget_cents']}"
    )


def assert_pool_posture_matches_ledger(pool: Dict[str, Any]) -> None:
    """The derived posture is a pure function of utilization and suppression."""
    budget = pool["incentive_budget_cents"]
    committed = pool["incentive_reserved_cents"] + pool["incentive_paid_cents"]
    utilization = (committed / budget) if budget else 0.0
    participants = pool["participant_count"]
    suppression_ratio = (
        pool["suppressed_participant_count"] / participants if participants else 0.0
    )
    if utilization >= POOL_CLOSED_UTILIZATION:
        expected = PoolStatus.CLOSED.value
    elif (
        utilization >= POOL_RESTRICTED_UTILIZATION
        or suppression_ratio > SUPPRESSION_RATIO_THRESHOLD
    ):
        expected = PoolStatus.RESTRICTED.value
    else:
        expected = PoolStatus.OPEN.value
    assert pool["status"] == expected, (
        f"Expected pool status {expected} at utilization {utilization} and "
        f"suppression ratio {suppression_ratio}, got {pool['status']}"
    )


def assert_participant(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("pool_id"), str)
    assert isinstance(data.get("external_ref"), str) and data["external_ref"]
    assert isinstance(data.get("segment"), str) and data["segment"]
    assert isinstance(data.get("locale"), str) and data["locale"]
    assert isinstance(data.get("pii_on_file"), bool)
    _assert_nullable_timestamp(data, "last_contacted_at")
    _assert_int(data, "contacts_in_window", minimum=0)
    _assert_int(data, "no_show_strikes", minimum=0)
    _assert_enum(data, "status", ParticipantStatus)


# ---------------------------------------------------------------------------
# Studies
# ---------------------------------------------------------------------------
def assert_study(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("research_request_id"), str)
    assert isinstance(data.get("participant_pool_id"), str)
    assert isinstance(data.get("lead_user_id"), str) and data["lead_user_id"]
    _assert_enum(data, "method", ResearchMethod)
    _assert_int(data, "target_participant_count", minimum=1)
    criteria = data.get("screening_criteria")
    assert isinstance(criteria, dict), "screening_criteria must be an object"
    assert set(criteria.keys()) == {
        "required_segment",
        "required_locale",
        "target_answers",
        "disqualifying_answers",
    }, f"screening_criteria carries exactly four keys, got {sorted(criteria.keys())}"
    _assert_int(data, "incentive_amount_cents", minimum=0)
    assert isinstance(data.get("fielding_start"), str)
    assert isinstance(data.get("fielding_end"), str)
    _assert_enum(data, "guide_status", GuideStatus)
    _assert_enum(data, "execution_status", ExecutionStatus)
    _assert_enum(data, "recruitment_status", RecruitmentStatusDimension)
    _assert_int(data, "invited_count", minimum=0)
    _assert_int(data, "screened_in_count", minimum=0)
    _assert_int(data, "completed_count", minimum=0)
    _assert_nullable_timestamp(data, "fielded_at")
    _assert_nullable_timestamp(data, "fielding_closed_at")


def assert_study_metrics(data: Dict[str, Any]) -> None:
    for field in (
        "cycle_time_days",
        "fielding_days",
        "recruitment_efficiency",
        "published_findings",
        "impact_score",
    ):
        assert field in data, f"metrics read must report {field}"
    if data["cycle_time_days"] is not None:
        _assert_int(data, "cycle_time_days", minimum=0)
    if data["fielding_days"] is not None:
        _assert_int(data, "fielding_days", minimum=0)
    _assert_number(data, "recruitment_efficiency")
    _assert_int(data, "published_findings", minimum=0)
    _assert_number(data, "impact_score")


# ---------------------------------------------------------------------------
# Recruitments
# ---------------------------------------------------------------------------
def assert_recruitment(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("study_id"), str)
    assert isinstance(data.get("participant_id"), str)
    _assert_enum(data, "status", RecruitmentStatus)
    _assert_enum(data, "incentive_state", IncentiveState)
    _assert_int(data, "reserved_cents", minimum=0)
    _assert_int(data, "paid_cents", minimum=0)
    if data.get("screen_score") is not None:
        _assert_number(data, "screen_score")
    _assert_nullable_timestamp(data, "scheduled_start")
    _assert_nullable_timestamp(data, "scheduled_end")
    _assert_int(data, "reschedule_count", minimum=0)


# ---------------------------------------------------------------------------
# Consent records and artifacts
# ---------------------------------------------------------------------------
def assert_consent_record(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("participant_id"), str)
    assert isinstance(data.get("study_id"), str)
    scopes = data.get("scopes")
    assert isinstance(scopes, list) and scopes, "scopes must be a non-empty array"
    assert len(set(scopes)) == len(scopes), f"scopes must be duplicate-free, got {scopes}"
    for scope in scopes:
        assert scope in (
            "RECORDING",
            "TRANSCRIPT",
            "PII_QUOTE",
        ), f"scope {scope!r} is outside the declared members"
    _assert_int(data, "retention_days", minimum=1)
    assert is_iso8601_timestamp(data.get("granted_at"))
    assert isinstance(data.get("retention_until"), str)
    _assert_enum(data, "status", ConsentStatus)
    _assert_nullable_timestamp(data, "revoked_at")


def assert_research_artifact(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("recruitment_id"), str)
    _assert_enum(data, "artifact_type", ArtifactType)
    assert isinstance(data.get("contains_pii"), bool)
    assert isinstance(data.get("retention_until"), str)
    _assert_enum(data, "lifecycle_state", ArtifactLifecycleState)
    _assert_nullable_timestamp(data, "purged_at")


def assert_retention_sweep(data: Dict[str, Any]) -> None:
    for field in (
        "expired_consent_count",
        "purged_artifact_count",
        "inadmissible_link_count",
        "retracted_finding_count",
        "overdue_follow_up_count",
        "unlocked_decision_count",
    ):
        _assert_int(data, field, minimum=0)


# ---------------------------------------------------------------------------
# Repository: themes, findings, evidence links
# ---------------------------------------------------------------------------
def assert_theme(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("label"), str) and data["label"]
    _assert_int(data, "depth", minimum=1)
    _assert_number(data, "own_evidence_weight")
    _assert_number(data, "evidence_weight")
    _assert_int(data, "reuse_count", minimum=0)
    _assert_enum(data, "status", ThemeStatus)


def assert_finding(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("study_id"), str)
    assert isinstance(data.get("theme_id"), str)
    assert isinstance(data.get("authored_by_user_id"), str) and data[
        "authored_by_user_id"
    ]
    assert isinstance(data.get("statement"), str) and data["statement"]
    _assert_enum(data, "severity", Severity)
    _assert_number(data, "evidence_strength")
    _assert_enum(data, "strength_variant", StrengthVariant)
    _assert_int(data, "admissible_link_count", minimum=0)
    _assert_int(data, "distinct_participant_count", minimum=0)
    _assert_enum(data, "status", FindingStatus)
    _assert_nullable_timestamp(data, "published_at")


def assert_evidence_link(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("finding_id"), str)
    assert isinstance(data.get("artifact_id"), str)
    assert isinstance(data.get("excerpt_ref"), str) and data["excerpt_ref"]
    _assert_enum(data, "weight_class", WeightClass)
    _assert_number(data, "contribution")
    assert isinstance(data.get("is_admissible"), bool)


# ---------------------------------------------------------------------------
# Readouts and follow-ups
# ---------------------------------------------------------------------------
def assert_readout(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("study_id"), str)
    assert isinstance(data.get("roadmap_decision_id"), str)
    assert isinstance(data.get("recommendation"), str) and data["recommendation"]
    _assert_enum(data, "recommended_action", RecommendedAction)
    cited = data.get("cited_finding_ids")
    assert isinstance(cited, list) and cited, "cited_finding_ids must be non-empty"
    assert len(set(cited)) == len(cited), "cited_finding_ids must be duplicate-free"
    _assert_enum(data, "status", ReadoutStatus)
    _assert_nullable_timestamp(data, "delivered_at")
    _assert_nullable_timestamp(data, "responded_at")


def assert_follow_up(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("readout_id"), str)
    assert isinstance(data.get("owner_user_id"), str) and data["owner_user_id"]
    assert isinstance(data.get("description"), str) and data["description"]
    assert isinstance(data.get("due_date"), str)
    _assert_enum(data, "status", FollowUpStatus)
    _assert_nullable_timestamp(data, "completed_at")


# ---------------------------------------------------------------------------
# Ordering helpers
# ---------------------------------------------------------------------------
def assert_ordered_desc_then_created_at(rows: List[Dict[str, Any]], field: str) -> None:
    for earlier, later in zip(rows, rows[1:]):
        if earlier[field] == later[field]:
            assert earlier["created_at"] <= later["created_at"], (
                f"rows tied on {field} must fall back to created_at ascending: "
                f"{earlier['created_at']} then {later['created_at']}"
            )
        else:
            assert earlier[field] > later[field], (
                f"rows must be ordered by {field} descending: "
                f"{earlier[field]} then {later[field]}"
            )


def assert_ordered_asc(rows: List[Dict[str, Any]], field: str = "created_at") -> None:
    values = [row[field] for row in rows]
    assert values == sorted(values), f"rows must be ordered by {field} ascending: {values}"

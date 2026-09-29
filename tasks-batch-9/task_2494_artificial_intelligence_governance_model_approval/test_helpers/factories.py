"""Payload factories for every write endpoint, plus timestamp arithmetic.

Each factory returns a valid, minimal-but-complete payload and accepts keyword
overrides, so a test that cares about one field states only that field.

The named payload sets near the bottom are the standard actors the whole suite
reuses: a first-party asset, several third-party assets, and use case intakes that
land deliberately in each risk band.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .constants import DEFAULT_CLOCK, REQUIRED_METRIC_NAME

# ─── Timestamp arithmetic (PRD §2.5) ───────────────────────────────────────
# Day arithmetic is exact calendar-day addition in UTC; hour arithmetic is exact;
# comparisons are exact to the second.

_FMT = "%Y-%m-%dT%H:%M:%SZ"


def parse_ts(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp as the API renders it.

    PRD §2.4 renders stamps with three fractional digits, so a value read back
    off a record may carry them while the literals this module composes do not.
    Both spellings denote the same instant and both must parse.
    """
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_ts(value: datetime) -> str:
    """Render a datetime the way the API renders timestamps."""
    return value.astimezone(timezone.utc).strftime(_FMT)


def plus_days(value: str, days: int) -> str:
    """Exact calendar-day addition in UTC."""
    return fmt_ts(parse_ts(value) + timedelta(days=days))


def plus_hours(value: str, hours: float) -> str:
    """Exact hour addition in UTC."""
    return fmt_ts(parse_ts(value) + timedelta(hours=hours))


def plus_seconds(value: str, seconds: int) -> str:
    """Exact second addition in UTC, for at-the-boundary probes."""
    return fmt_ts(parse_ts(value) + timedelta(seconds=seconds))


def clock_payload(current_utc: str) -> dict[str, Any]:
    return {"current_utc": current_utc}


# ─── Model assets (PRD §3.1) ───────────────────────────────────────────────


def model_asset_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": "Internal ML Platform",
        "model_name": "helios-mini",
        "model_version": "1.0.0",
        "hosting": "INTERNAL",
        "modality": "TEXT",
        "is_third_party": False,
    }
    payload.update(overrides)
    return payload


def vendor_assessment_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "vendor_name": "Nimbus AI",
        "training_data_provenance": "DOCUMENTED_LICENSED",
        "output_rights": "FULL_ASSIGNMENT",
        "retention_days": 20,
        "retention_opt_out": True,
        "subprocessors_disclosed": True,
    }
    payload.update(overrides)
    return payload


def assessment_decision_payload(
    decision: str, terms_variant: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {"decision": decision, "terms_variant": terms_variant}
    payload.update(overrides)
    return payload


def asset_revision_payload(**overrides: Any) -> dict[str, Any]:
    """A revision must carry at least one of the three revisable attributes."""
    payload: dict[str, Any] = {"model_version": "1.1.0"}
    payload.update(overrides)
    return payload


# ─── Use cases (PRD §3.2) ──────────────────────────────────────────────────


def use_case_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "Support ticket triage assistant",
        "business_unit": "Support",
        "description": "ranks inbound tickets and drafts a first reply for agent sign-off",
        "affects_individuals": True,
        "decision_autonomy": "HUMAN_IN_LOOP",
        "data_sensitivity": "CONFIDENTIAL",
        "individual_impact": "MATERIAL",
        "jurisdictions": [],
        "deployed_headcount_reach": 5000,
    }
    payload.update(overrides)
    return payload


def classify_payload(expected_use_case_version: int, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "expected_use_case_version": expected_use_case_version
    }
    payload.update(overrides)
    return payload


def use_case_revision_payload(**overrides: Any) -> dict[str, Any]:
    """A revision must carry at least one revisable intake field."""
    payload: dict[str, Any] = {"description": "revised scope after reviewer feedback"}
    payload.update(overrides)
    return payload


# ─── Review gates (PRD §3.3) ───────────────────────────────────────────────


def issue_conditions_payload(conditions: list[str], **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"conditions": conditions}
    payload.update(overrides)
    return payload


def conditions(count: int) -> list[str]:
    """A list of ``count`` distinct, non-empty remediation conditions."""
    return [f"remediation condition {index + 1}" for index in range(count)]


# ─── Model bindings (PRD §3.4) ─────────────────────────────────────────────


def model_binding_payload(
    model_asset_id: str, expected_use_case_version: int, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model_asset_id": model_asset_id,
        "expected_use_case_version": expected_use_case_version,
    }
    payload.update(overrides)
    return payload


# ─── Test evaluations (PRD §3.4) ───────────────────────────────────────────


def evaluation_schedule_payload(
    model_binding_id: str,
    eval_type: str,
    window_start_at: str,
    window_end_at: str,
    use_case_id: Optional[str] = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Body for scheduling a run. ``use_case_id`` is the tier source, so it is
    part of the declared input alongside the binding under test."""
    payload: dict[str, Any] = {
        "model_binding_id": model_binding_id,
        "eval_type": eval_type,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }
    if use_case_id is not None:
        payload["use_case_id"] = use_case_id
    payload.update(overrides)
    return payload


# Historical name kept for call sites that already import it. ``__test__ = False``
# stops pytest from collecting the factory itself as a test function when a test
# module imports it under this name.
test_evaluation_payload = evaluation_schedule_payload
test_evaluation_payload.__test__ = False  # type: ignore[attr-defined]


def evaluation_completion_payload(
    metric_value: float,
    sample_size: int,
    eval_type: Optional[str] = None,
    metric_name: Optional[str] = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Body for completing a run.

    The metric travels under the name the frozen profile designates, not under
    ``observed_metric_value`` — that is where the server *stores* it. Pass either
    the ``eval_type`` (whose metric name is then looked up) or ``metric_name``
    directly.
    """
    if metric_name is None:
        if eval_type is None:
            raise ValueError("pass eval_type or metric_name so the metric key is known")
        metric_name = REQUIRED_METRIC_NAME[eval_type]
    payload: dict[str, Any] = {
        metric_name: metric_value,
        "sample_size": sample_size,
    }
    payload.update(overrides)
    return payload


# ─── Oversight designs (PRD §3.5) ──────────────────────────────────────────


def oversight_design_payload(
    expected_use_case_version: int, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "review_mode": "PRE_DECISION_REVIEW",
        "sample_pct": 0,
        "escalation_sla_hours": 24,
        "reviewer_role": "BusinessReviewer",
        "override_capability": True,
        "expected_use_case_version": expected_use_case_version,
    }
    payload.update(overrides)
    return payload


def design_decision_payload(decision: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ─── Disclosure notices (PRD §3.6) ─────────────────────────────────────────


def disclosure_notice_payload(
    notice_type: str,
    jurisdiction: str,
    effective_from: str,
    effective_to: str,
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "notice_type": notice_type,
        "jurisdiction": jurisdiction,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "locale_count": 1,
    }
    payload.update(overrides)
    return payload


# ─── Approval (PRD §3.7) ───────────────────────────────────────────────────


def approval_payload(expected_use_case_version: int, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "expected_use_case_version": expected_use_case_version
    }
    payload.update(overrides)
    return payload


def revocation_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"revocation_reason": "GOVERNANCE_DECISION"}
    payload.update(overrides)
    return payload


def reassessment_payload(outcome: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


# ─── Monitoring incidents (PRD §3.8) ───────────────────────────────────────


def monitoring_incident_payload(
    use_case_id: str,
    severity: str,
    detected_at: Optional[str] = None,
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "use_case_id": use_case_id,
        "severity": severity,
        "category": "HARMFUL_OUTPUT",
        "summary": "model produced an unsafe recommendation in production",
        "detected_at": detected_at or DEFAULT_CLOCK,
    }
    payload.update(overrides)
    return payload


# ─── Shadow deployments (PRD §3.9) ─────────────────────────────────────────


def shadow_deployment_payload(
    model_asset_id: str,
    environment: str = "SANDBOX",
    discovered_at: Optional[str] = None,
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model_asset_id": model_asset_id,
        "environment": environment,
        "discovered_source": "NETWORK_SCAN",
        "discovered_at": discovered_at or DEFAULT_CLOCK,
    }
    payload.update(overrides)
    return payload


def grant_grace_payload(grace_days: int, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"grace_days": grace_days}
    payload.update(overrides)
    return payload


def shadow_link_payload(use_case_id: str, **overrides: Any) -> dict[str, Any]:
    """Body for attributing a discovery. The officer supplies ``use_case_id``;
    ``claimed_use_case_id`` is the field the record sets from it."""
    payload: dict[str, Any] = {"use_case_id": use_case_id}
    payload.update(overrides)
    return payload


# ─── Named asset payloads reused across the suite ──────────────────────────

FIRST_PARTY_ASSET = model_asset_payload()

THIRD_PARTY_ASSET_NIMBUS = model_asset_payload(
    provider="Nimbus AI",
    model_name="nimbus-chat",
    model_version="3.2.0",
    hosting="VENDOR_API",
    modality="TEXT",
    is_third_party=True,
)

THIRD_PARTY_ASSET_GRAYLINE = model_asset_payload(
    provider="Grayline Models",
    model_name="gl-omni",
    model_version="0.9.0",
    hosting="VENDOR_API",
    modality="MULTIMODAL",
    is_third_party=True,
)

THIRD_PARTY_ASSET_NORTHWIND = model_asset_payload(
    provider="Northwind AI",
    model_name="nw-adjudicate",
    model_version="3.2.0",
    hosting="VENDOR_API",
    modality="TEXT",
    is_third_party=True,
)

THIRD_PARTY_ASSET_CARTWRIGHT = model_asset_payload(
    provider="Cartwright Labs",
    model_name="cl-summarize",
    model_version="1.4.1",
    hosting="ON_PREM",
    modality="MULTIMODAL",
    is_third_party=True,
)


# ─── Named use case intakes, one per intended risk band ────────────────────

# Scores 10 → MINIMAL. Opens only the BUSINESS gate.
MINIMAL_USE_CASE = use_case_payload(
    title="Internal wiki search reranker",
    business_unit="IT",
    description="reranks internal wiki hits for staff searches",
    affects_individuals=False,
    decision_autonomy="ADVISORY",
    data_sensitivity="PUBLIC",
    individual_impact="LOW",
    jurisdictions=[],
    deployed_headcount_reach=500,
)

# Scores 49 → LIMITED. Opens PRIVACY and BUSINESS.
LIMITED_USE_CASE = use_case_payload()

# Scores 52 → LIMITED, with one high-scrutiny jurisdiction so a published EU
# notice becomes a precondition for clearing the PRIVACY gate.
LIMITED_EU_USE_CASE = use_case_payload(
    title="Applicant screening ranker",
    business_unit="HR",
    description="ranks external applicants for recruiter shortlisting",
    affects_individuals=True,
    decision_autonomy="HUMAN_IN_LOOP",
    data_sensitivity="CONFIDENTIAL",
    individual_impact="MATERIAL",
    jurisdictions=["EU"],
    deployed_headcount_reach=5000,
)

# Scores 74 → HIGH. Opens all four gates.
HIGH_USE_CASE = use_case_payload(
    title="Credit limit adjustment recommender",
    business_unit="Lending",
    description="recommends credit limit changes for review by a credit officer",
    affects_individuals=True,
    decision_autonomy="HUMAN_ON_LOOP",
    data_sensitivity="INTERNAL",
    individual_impact="CONSEQUENTIAL",
    jurisdictions=["EU", "UK"],
    deployed_headcount_reach=12000,
)

# Satisfies all four legs of the prohibited conjunction, so classification
# rejects it outright regardless of the additive score.
FORCED_PROHIBITED_USE_CASE = use_case_payload(
    title="Automated dismissal decision engine",
    business_unit="HR",
    description=(
        "issues final dismissal decisions from performance and health records "
        "with no human in the path"
    ),
    affects_individuals=True,
    decision_autonomy="FULLY_AUTOMATED",
    data_sensitivity="SPECIAL_CATEGORY",
    individual_impact="CONSEQUENTIAL",
    jurisdictions=[],
    deployed_headcount_reach=500,
)

# Scores 99 → PROHIBITED by band alone, without the forced conjunction, because
# the data sensitivity is CONFIDENTIAL rather than SPECIAL_CATEGORY.
PROHIBITED_BY_BAND_USE_CASE = use_case_payload(
    title="Benefits eligibility auto-denial",
    business_unit="Operations",
    description="denies benefits claims end to end from submitted evidence",
    affects_individuals=True,
    decision_autonomy="FULLY_AUTOMATED",
    data_sensitivity="CONFIDENTIAL",
    individual_impact="CONSEQUENTIAL",
    jurisdictions=["EU", "UK", "US_CO"],
    deployed_headcount_reach=100000,
)


# ─── Named vendor assessment payloads by intended grade ────────────────────

# 0 + 0 + 0 retention band + 0 + 0 = 0 points → grade A under DOCUMENTED_TERMS.
ASSESSMENT_GRADE_A = vendor_assessment_payload()

# 8 + 6 + 0 + 0 + 0 = 14 points → grade B.
ASSESSMENT_GRADE_B = vendor_assessment_payload(
    training_data_provenance="DOCUMENTED_MIXED",
    output_rights="LICENSE_WITH_RESTRICTIONS",
    retention_days=20,
    retention_opt_out=True,
    subprocessors_disclosed=True,
)

# 8 + 16 + 10 + 0 + 0 = 34 points → grade C at the top of the band.
ASSESSMENT_GRADE_C = vendor_assessment_payload(
    training_data_provenance="DOCUMENTED_MIXED",
    output_rights="VENDOR_RETAINS",
    retention_days=120,
    retention_opt_out=True,
    subprocessors_disclosed=True,
)

# 20 + 10 surcharge + 16 + 18 + 6 + 5 = 75 points → grade D.
ASSESSMENT_GRADE_D = vendor_assessment_payload(
    training_data_provenance="UNDISCLOSED",
    output_rights="VENDOR_RETAINS",
    retention_days=400,
    retention_opt_out=False,
    subprocessors_disclosed=False,
)

# Declares no retention period at all, which the conservative variant tolerates
# and the documented variant refuses.
ASSESSMENT_NULL_RETENTION = vendor_assessment_payload(retention_days=None)

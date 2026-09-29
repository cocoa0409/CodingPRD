"""Payload builders. Every builder returns a valid body and accepts overrides.

Each builder produces the minimum body the PRD declares as required for its
endpoint, filling optional fields only where a test would almost always want
them. Callers override any key by keyword; passing ``None`` explicitly keeps the
key with a null value, which is how a test exercises an explicit null.
"""

from typing import Any, Dict, List, Optional

_UNSET = object()


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, dropping any key whose override is the _UNSET sentinel."""
    merged = dict(base)
    for key, value in overrides.items():
        if value is _UNSET:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


# --------------------------------------------------------------------------
# Clinicians
# --------------------------------------------------------------------------


def build_clinician_payload(**overrides: Any) -> Dict[str, Any]:
    """A clinician registration body.

    Required: full_name, specialty, authorized_roles.
    """
    base: Dict[str, Any] = {
        "full_name": "Dana Okafor",
        "specialty": "INTERNAL_MEDICINE",
        "authorized_roles": ["PeerReviewer"],
    }
    return _merge(base, overrides)


# --------------------------------------------------------------------------
# Content requests
# --------------------------------------------------------------------------


def build_citation(
    citation: str = "Ann Intern Med 2025;182:114-121",
    peer_reviewed: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """One evidence citation object: citation + peer_reviewed are required."""
    base: Dict[str, Any] = {"citation": citation, "peer_reviewed": peer_reviewed}
    return _merge(base, overrides)


def build_citations(
    count: int = 2, peer_reviewed_count: Optional[int] = None
) -> List[Dict[str, Any]]:
    """`count` citations, the first `peer_reviewed_count` of them peer reviewed."""
    if peer_reviewed_count is None:
        peer_reviewed_count = count
    return [
        build_citation(citation=f"Reference {index + 1}", peer_reviewed=index < peer_reviewed_count)
        for index in range(count)
    ]


def build_content_request_payload(
    clinical_sponsor_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A content request intake body.

    Required: title, request_type, clinical_domain, urgency, evidence_grade,
    clinical_sponsor_id, evidence_citations (at least one entry).
    """
    base: Dict[str, Any] = {
        "title": "Sepsis fluid resuscitation order set",
        "request_type": "ORDER_SET",
        "clinical_domain": "CRITICAL_CARE",
        "urgency": "ROUTINE",
        "evidence_grade": "B",
        "clinical_sponsor_id": clinical_sponsor_id,
        "patient_safety_flag": False,
        "evidence_citations": build_citations(2, 1),
    }
    return _merge(base, overrides)


def build_triage_payload(decision: str = "ACCEPT", **overrides: Any) -> Dict[str, Any]:
    """A triage body: decision is required, triage_note optional."""
    base: Dict[str, Any] = {"decision": decision}
    return _merge(base, overrides)


def build_resubmit_payload(**overrides: Any) -> Dict[str, Any]:
    """A sponsor resubmission body: a fresh evidence_citations array."""
    base: Dict[str, Any] = {"evidence_citations": build_citations(2, 2)}
    return _merge(base, overrides)


# --------------------------------------------------------------------------
# Order sets and items
# --------------------------------------------------------------------------


def build_order_set_payload(
    built_by_clinician_id: str,
    pinned_vendor_release_id: str,
    expected_content_request_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """An order set build body.

    Required: name, specialty, pinned_vendor_release_id, built_by_clinician_id,
    expected_content_request_version.
    """
    base: Dict[str, Any] = {
        "name": "Adult sepsis bundle",
        "specialty": "CRITICAL_CARE",
        "pinned_vendor_release_id": pinned_vendor_release_id,
        "built_by_clinician_id": built_by_clinician_id,
        "expected_content_request_version": expected_content_request_version,
    }
    return _merge(base, overrides)


def build_order_set_item_payload(**overrides: Any) -> Dict[str, Any]:
    """An order set item body.

    Required: orderable_code, display_name, item_category.
    """
    base: Dict[str, Any] = {
        "orderable_code": "LACTATE",
        "display_name": "Lactate, serum",
        "item_category": "LAB",
    }
    return _merge(base, overrides)


def build_high_alert_item_payload(**overrides: Any) -> Dict[str, Any]:
    """An item line flagged as a high-alert medication."""
    base: Dict[str, Any] = {
        "orderable_code": "HEPARIN-DRIP",
        "display_name": "Heparin infusion",
        "item_category": "MEDICATION",
        "default_dose": "18 units/kg/hr",
        "high_alert_medication": True,
    }
    return _merge(base, overrides)


def build_pharmacy_signoff_payload(
    pharmacy_signoff_by_clinician_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A pharmacy sign-off body: the signing clinician reference is required."""
    base: Dict[str, Any] = {
        "pharmacy_signoff_by_clinician_id": pharmacy_signoff_by_clinician_id
    }
    return _merge(base, overrides)


def build_submit_for_peer_review_payload(**overrides: Any) -> Dict[str, Any]:
    """A peer-review submission body: submission_note is optional."""
    base: Dict[str, Any] = {}
    return _merge(base, overrides)


def build_publish_payload(go_live_at: str, **overrides: Any) -> Dict[str, Any]:
    """A publication body: the binding go_live_at instant is required."""
    base: Dict[str, Any] = {"go_live_at": go_live_at}
    return _merge(base, overrides)


# --------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------


def build_firing_criteria(**overrides: Any) -> Dict[str, Any]:
    """Firing criteria: a trigger_event string plus an expression string."""
    base: Dict[str, Any] = {
        "trigger_event": "MEDICATION_ORDER_ENTRY",
        "expression": "drug_pair(warfarin, fluconazole)",
    }
    return _merge(base, overrides)


def build_alert_payload(
    designed_by_clinician_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """An alert design body.

    Required: name, firing_criteria, designed_by_clinician_id, severity_tier.
    Alert design carries no version guard: only the order set build and the
    burden window opening accept one.
    """
    base: Dict[str, Any] = {
        "name": "Warfarin-fluconazole interaction",
        "firing_criteria": build_firing_criteria(),
        "designed_by_clinician_id": designed_by_clinician_id,
        "severity_tier": "TIER_2_INTERRUPTIVE",
        "override_reason_codes": ["CLINICALLY_APPROPRIATE", "MONITORING_IN_PLACE"],
    }
    return _merge(base, overrides)


def build_tier1_alert_payload(
    designed_by_clinician_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """A hard-stop alert carrying the narrative its tier requires."""
    return build_alert_payload(
        designed_by_clinician_id,
        **_merge(
            {
                "name": "Contraindicated combination hard stop",
                "severity_tier": "TIER_1_HARD_STOP",
                "hard_stop_justification": (
                    "Co-prescription is contraindicated and has caused a harm event."
                ),
            },
            overrides,
        ),
    )


def build_activation_payload(**overrides: Any) -> Dict[str, Any]:
    """An alert activation body: activation_note is optional."""
    base: Dict[str, Any] = {}
    return _merge(base, overrides)


def build_suspend_payload(**overrides: Any) -> Dict[str, Any]:
    """An alert suspension body: suspension_reason is stored."""
    base: Dict[str, Any] = {"suspension_reason": "Firing volume under investigation"}
    return _merge(base, overrides)


def build_resume_payload(**overrides: Any) -> Dict[str, Any]:
    """An alert resumption body: resume_note is optional."""
    base: Dict[str, Any] = {}
    return _merge(base, overrides)


def build_retire_payload(**overrides: Any) -> Dict[str, Any]:
    """An alert retirement body: retirement_rationale is supplied by the chair."""
    base: Dict[str, Any] = {
        "retirement_rationale": "Two consecutive windows meet the low-value gate."
    }
    return _merge(base, overrides)


# --------------------------------------------------------------------------
# Review assignments
# --------------------------------------------------------------------------


def build_review_assignment_payload(
    reviewer_id: str,
    review_kind: str = "PEER_REVIEW",
    order_set_id: Optional[str] = None,
    alert_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """A review assignment body.

    Required: reviewer_id, review_kind, and exactly one of order_set_id or
    alert_id.
    """
    base: Dict[str, Any] = {"reviewer_id": reviewer_id, "review_kind": review_kind}
    if order_set_id is not None:
        base["order_set_id"] = order_set_id
    if alert_id is not None:
        base["alert_id"] = alert_id
    return _merge(base, overrides)


def build_cast_payload(vote: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    """A vote body: vote is required; comment and evidence_concern optional."""
    base: Dict[str, Any] = {"vote": vote}
    return _merge(base, overrides)


def build_withdraw_payload(**overrides: Any) -> Dict[str, Any]:
    """A withdrawal body: withdrawal_reason is supplied by the chair."""
    base: Dict[str, Any] = {"withdrawal_reason": "Reviewer reassigned to another committee"}
    return _merge(base, overrides)


# --------------------------------------------------------------------------
# Burden windows and firings
# --------------------------------------------------------------------------


def build_burden_window_payload(
    window_start: str, window_end: str, expected_alert_version: int, **overrides: Any
) -> Dict[str, Any]:
    """A burden window body: bounds plus the mandatory alert-version guard."""
    base: Dict[str, Any] = {
        "window_start": window_start,
        "window_end": window_end,
        "expected_alert_version": expected_alert_version,
    }
    return _merge(base, overrides)


def build_close_window_payload(**overrides: Any) -> Dict[str, Any]:
    """A window close body: closure_reason is optional."""
    base: Dict[str, Any] = {}
    return _merge(base, overrides)


def build_reopen_window_payload(**overrides: Any) -> Dict[str, Any]:
    """A window reopen body: reopen_reason accompanies the request."""
    base: Dict[str, Any] = {"reopen_reason": "Firing feed backfilled after ingest gap"}
    return _merge(base, overrides)


def build_firing_ingest_payload(
    alert_id: str,
    fired_at_start: str,
    fire_count: int,
    override_count: int,
    distinct_clinician_count: int,
    interval_seconds: int = 60,
    **overrides: Any,
) -> Dict[str, Any]:
    """A deterministic firing ingest body."""
    base: Dict[str, Any] = {
        "alert_id": alert_id,
        "fired_at_start": fired_at_start,
        "interval_seconds": interval_seconds,
        "fire_count": fire_count,
        "override_count": override_count,
        "distinct_clinician_count": distinct_clinician_count,
        "override_reason_code": "CLINICALLY_APPROPRIATE",
    }
    return _merge(base, overrides)


# --------------------------------------------------------------------------
# Vendor releases and deltas
# --------------------------------------------------------------------------


def build_vendor_release_payload(**overrides: Any) -> Dict[str, Any]:
    """A vendor release body.

    Required: vendor_name, release_label, content_domain.
    """
    base: Dict[str, Any] = {
        "vendor_name": "FDB",
        "release_label": "2026.08",
        "content_domain": "DRUG_INTERACTION",
    }
    return _merge(base, overrides)


def build_vendor_rule_delta_payload(**overrides: Any) -> Dict[str, Any]:
    """A vendor rule delta body.

    Required: rule_code, change_type, description.
    """
    base: Dict[str, Any] = {
        "rule_code": "DI-0001",
        "change_type": "NEW_INTERACTION",
        "description": "New moderate interaction between two agents.",
        "new_severity": "MODERATE",
    }
    return _merge(base, overrides)


def build_impact_analysis_payload(**overrides: Any) -> Dict[str, Any]:
    """An impact analysis body: analysis_note is optional."""
    base: Dict[str, Any] = {}
    return _merge(base, overrides)


def build_disposition_payload(
    disposition: str = "ACCEPT", **overrides: Any
) -> Dict[str, Any]:
    """A delta disposition body: disposition is required."""
    base: Dict[str, Any] = {"disposition": disposition}
    return _merge(base, overrides)


def build_release_activation_payload(**overrides: Any) -> Dict[str, Any]:
    """A release activation body: activation_note is optional."""
    base: Dict[str, Any] = {}
    return _merge(base, overrides)


# --------------------------------------------------------------------------
# Downtime events
# --------------------------------------------------------------------------


def build_downtime_event_payload(
    window_start: str,
    window_end: str,
    scope: str = "SYSTEM_WIDE",
    mode: str = "READ_ONLY",
    **overrides: Any,
) -> Dict[str, Any]:
    """A downtime event body.

    Required: scope, mode, window_start, window_end.
    """
    base: Dict[str, Any] = {
        "scope": scope,
        "mode": mode,
        "window_start": window_start,
        "window_end": window_end,
    }
    return _merge(base, overrides)


def build_downtime_activation_payload(**overrides: Any) -> Dict[str, Any]:
    """A downtime activation body: activation_note is optional."""
    base: Dict[str, Any] = {}
    return _merge(base, overrides)


def build_downtime_close_payload(**overrides: Any) -> Dict[str, Any]:
    """A downtime close body: closure_note is optional."""
    base: Dict[str, Any] = {}
    return _merge(base, overrides)


# --------------------------------------------------------------------------
# Adherence measurement
# --------------------------------------------------------------------------


def build_unit_observation(
    unit_code: str = "MICU",
    eligible_orders: int = 100,
    adherent_orders: int = 80,
    unintended_events: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    """One unit observation row."""
    base: Dict[str, Any] = {
        "unit_code": unit_code,
        "eligible_orders": eligible_orders,
        "adherent_orders": adherent_orders,
        "unintended_events": unintended_events,
    }
    return _merge(base, overrides)


def build_adherence_measurement_payload(
    measurement_period_start: str,
    measurement_period_end: str,
    unit_observations: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """An adherence observation set body.

    Required: measurement_period_start, measurement_period_end, and a
    unit_observations array with at least one row.
    """
    base: Dict[str, Any] = {
        "measurement_period_start": measurement_period_start,
        "measurement_period_end": measurement_period_end,
        "unit_observations": (
            unit_observations if unit_observations is not None else [build_unit_observation()]
        ),
    }
    return _merge(base, overrides)


def build_finalize_measurement_payload(
    verdict: str = "SUSTAIN", **overrides: Any
) -> Dict[str, Any]:
    """A finalization body: verdict is required."""
    base: Dict[str, Any] = {"verdict": verdict}
    return _merge(base, overrides)


# --------------------------------------------------------------------------
# Annual review tasks and operational control
# --------------------------------------------------------------------------


def build_attestation_payload(**overrides: Any) -> Dict[str, Any]:
    """An attestation body: a non-empty evidence_citations array."""
    base: Dict[str, Any] = {"evidence_citations": build_citations(1, 1)}
    return _merge(base, overrides)


def build_expiration_sweep_payload(**overrides: Any) -> Dict[str, Any]:
    """An expiration sweep body: dry_run is optional."""
    base: Dict[str, Any] = {}
    return _merge(base, overrides)


def build_clock_payload(to_iso8601: str, **overrides: Any) -> Dict[str, Any]:
    """A logical clock body: the target instant is required."""
    base: Dict[str, Any] = {"to_iso8601": to_iso8601}
    return _merge(base, overrides)

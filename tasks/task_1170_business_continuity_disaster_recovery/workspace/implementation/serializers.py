"""Serializers: whitelist declared fields, refresh computed-on-read values.

Computed-on-read per PRD: Gap.overdue, RecoveryCapability.meets_bia /
validation_freshness, Attestation.readiness_score (while DRAFT),
Activation coverage_pct.
"""
from calc import (activation_coverage, attestation_readiness,
                  capability_freshness, capability_meets_bia, gap_is_overdue)
from core import fmt_dt


def _common(entity, fields):
    out = {f: entity.get(f) for f in fields}
    out["id"] = entity["id"]
    out["created_at"] = fmt_dt(entity["created_at"])
    out["updated_at"] = fmt_dt(entity["updated_at"])
    out["version"] = entity["version"]
    return out


def contact_view(c):
    return _common(c, ["full_name", "email", "role_title", "active_flag"])


def process_view(p):
    return _common(p, ["name", "business_unit", "owner_contact_id",
                       "criticality_tier", "status"])


def bia_view(b):
    out = _common(b, ["process_id", "cycle_label", "rto_target_hours",
                      "rpo_target_hours", "mtpd_hours", "peak_period_flag",
                      "peak_start_month", "peak_end_month",
                      "impact_regulatory", "impact_reputational",
                      "impact_operational", "criticality_score",
                      "score_variant", "decided_by_contact_id", "status"])
    fin = b.get("impact_financial_per_hour")
    out["impact_financial_per_hour"] = float(fin) if fin is not None else None
    return out


def plan_view(p):
    return _common(p, ["process_id", "title", "version_no", "strategy_type",
                       "rto_committed_hours", "rpo_committed_hours",
                       "target_bia_id", "approved_version_no",
                       "supersedes_plan_id", "last_adoption_check_cycle",
                       "status"])


def section_view(s):
    return _common(s, ["plan_id", "section_type", "content", "order_index",
                       "required_flag"])


def dependency_view(d):
    return {
        "id": d["id"],
        "from_process_id": d["from_process_id"],
        "to_process_id": d["to_process_id"],
        "dependency_type": d["dependency_type"],
        "criticality": d["criticality"],
        "notes": d.get("notes"),
        "created_at": fmt_dt(d["created_at"]),
    }


def third_party_view(t):
    return _common(t, ["name", "service_category", "criticality_rating",
                       "owner_contact_id", "status"])


def assessment_view(a):
    return _common(a, ["third_party_id", "process_id", "assessment_type",
                       "assessed_rto_hours", "assessed_rpo_hours",
                       "evidence_doc_ref", "continuity_score", "score_variant",
                       "meets_required_rto", "rto_required_hours",
                       "rpo_required_hours", "finalized_by_contact_id",
                       "status"])


def site_view(s):
    out = _common(s, ["name", "site_type", "region", "capacity_seats",
                      "status"])
    out["contracted_through"] = fmt_dt(s["contracted_through"])
    cost = s.get("monthly_cost")
    out["monthly_cost"] = float(cost) if cost is not None else None
    return out


def reservation_view(r):
    out = _common(r, ["site_id", "process_id", "purpose", "seats_reserved",
                      "created_by_contact_id", "status"])
    out["starts_at"] = fmt_dt(r["starts_at"])
    out["ends_at"] = fmt_dt(r["ends_at"])
    return out


def exercise_view(e):
    out = _common(e, ["process_id", "plan_id", "exercise_type",
                      "completion_outcome", "achieved_rto_hours",
                      "achieved_rpo_hours", "result",
                      "requires_capability_check", "validation_run_id",
                      "status"])
    out["scheduled_start"] = fmt_dt(e["scheduled_start"])
    out["scheduled_end"] = fmt_dt(e["scheduled_end"])
    return out


def finding_view(f):
    out = _common(f, ["exercise_id", "process_id", "severity", "description",
                      "root_cause", "verified_by_contact_id",
                      "rejected_reason", "status"])
    out["due_date"] = fmt_dt(f["due_date"])
    return out


def capability_view(c):
    # Derived truth on read (PRD §3.7); refresh stored labels silently.
    c["meets_bia"] = capability_meets_bia(c)
    c["validation_freshness"] = capability_freshness(c)
    return _common(c, ["process_id", "capability_type", "capability_ref_id",
                       "proven_rto_hours", "proven_rpo_hours", "meets_bia",
                       "last_validation_run_id", "validation_freshness",
                       "status"])


def run_view(r):
    return _common(r, ["capability_id", "exercise_id", "measured_rto_hours",
                       "measured_rpo_hours", "method", "evidence_ref",
                       "result", "gap_created_id", "status"])


def gap_view(g):
    g["overdue"] = gap_is_overdue(g)
    out = _common(g, ["process_id", "capability_id", "finding_id", "gap_type",
                      "severity", "description", "overdue",
                      "closed_by_contact_id", "status"])
    out["due_date"] = fmt_dt(g["due_date"])
    return out


def node_view(n):
    return _common(n, ["tree_label", "contact_name", "role_title",
                       "parent_node_id", "order_index", "channel",
                       "ack_deadline_minutes", "active_flag"])


def activation_view(a):
    out = _common(a, ["process_id", "plan_id", "declared_severity",
                      "activation_criterion", "criterion_justification",
                      "expected_notifications", "notified_count", "acked_count",
                      "escalation_level", "deactivated_by_contact_id",
                      "status"])
    out["acknowledged_at"] = fmt_dt(a.get("acknowledged_at"))
    out["coverage_pct"] = activation_coverage(a)
    return out


def notification_view(n):
    return {
        "id": n["id"],
        "activation_id": n["activation_id"],
        "comm_node_id": n["comm_node_id"],
        "channel": n["channel"],
        "status": n["status"],
        "sent_at": fmt_dt(n["sent_at"]),
        "acked_at": fmt_dt(n.get("acked_at")),
        "ack_token": n["ack_token"],
        "created_at": fmt_dt(n["created_at"]),
    }


def attestation_view(a):
    if a["status"] == "DRAFT":
        score, _ = attestation_readiness(a["process_id"])
        a["readiness_score"] = score
    out = _common(a, ["process_id", "attestation_type", "readiness_score",
                      "snapshot_payload", "signed_by_contact_id",
                      "signer_declaration", "revoked_reason", "status"])
    out["period_start"] = fmt_dt(a["period_start"])
    out["period_end"] = fmt_dt(a["period_end"])
    return out

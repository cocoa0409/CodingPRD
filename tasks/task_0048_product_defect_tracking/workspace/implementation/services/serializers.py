"""Entity serializers — produce JSON payloads with stable field ordering."""

from __future__ import annotations


def _strip(row: dict) -> dict:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def project_dto(p: dict) -> dict:
    return {
        "id": p["id"],
        "project_key": p["project_key"],
        "name": p["name"],
        "clock_minute": p["clock_minute"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def module_dto(m: dict) -> dict:
    return {
        "id": m["id"],
        "project_id": m["project_id"],
        "module_key": m["module_key"],
        "owner_team_member_id": m["owner_team_member_id"],
        "kloc": m["kloc"],
        "initial_defect_quota": m["initial_defect_quota"],
        "active_defect_count": m["active_defect_count"],
        "quota_remaining": m["quota_remaining"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def team_member_dto(t: dict) -> dict:
    return {
        "id": t["id"],
        "project_id": t["project_id"],
        "display_name": t["display_name"],
        "role": t["role"],
        "active_workload": t["active_workload"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def defect_dto(d: dict) -> dict:
    return {
        "id": d["id"],
        "project_id": d["project_id"],
        "module_id": d["module_id"],
        "reporter_id": d["reporter_id"],
        "assignee_id": d.get("assignee_id"),
        "title": d["title"],
        "defect_source": d["defect_source"],
        "severity": d["severity"],
        "effective_severity": d["effective_severity"],
        "business_impact": d["business_impact"],
        "reproduction_steps": d["reproduction_steps"],
        "environment": d["environment"],
        "priority_score": d["priority_score"],
        "status": d["status"],
        "sla_state": d["sla_state"],
        "reopen_count": d["reopen_count"],
        "total_paused_minutes": d["total_paused_minutes"],
        "report_clock_minute": d["report_clock_minute"],
        "first_fixed_at_minute": d.get("first_fixed_at_minute"),
        "response_due_minute": d["response_due_minute"],
        "resolution_due_minute": d["resolution_due_minute"],
        "escalation_level": d["escalation_level"],
        "canonical_defect_id": d.get("canonical_defect_id"),
        "fix_version": d.get("fix_version"),
        "final_resolution_minutes": d.get("final_resolution_minutes"),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def attachment_dto(a: dict) -> dict:
    return {
        "id": a["id"],
        "defect_id": a["defect_id"],
        "attachment_type": a["attachment_type"],
        "filename": a["filename"],
        "size_bytes": a["size_bytes"],
        "uploaded_by": a["uploaded_by"],
        "created_at": a["created_at"],
    }


def duplicate_link_dto(dl: dict) -> dict:
    return {
        "id": dl["id"],
        "duplicate_defect_id": dl["duplicate_defect_id"],
        "canonical_defect_id": dl["canonical_defect_id"],
        "linked_by": dl["linked_by"],
        "similarity_score": dl["similarity_score"],
        "created_at": dl["created_at"],
    }


def severity_override_dto(s: dict) -> dict:
    return {
        "id": s["id"],
        "defect_id": s["defect_id"],
        "requested_severity": s["requested_severity"],
        "justification": s["justification"],
        "requested_by": s["requested_by"],
        "approved_by": s.get("approved_by"),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def fix_record_dto(f: dict) -> dict:
    return {
        "id": f["id"],
        "defect_id": f["defect_id"],
        "fix_version": f["fix_version"],
        "developer_id": f["developer_id"],
        "fix_summary": f["fix_summary"],
        "commit_sha": f["commit_sha"],
        "created_at": f["created_at"],
    }


def verification_record_dto(v: dict) -> dict:
    return {
        "id": v["id"],
        "defect_id": v["defect_id"],
        "fix_record_id": v["fix_record_id"],
        "verifier_id": v["verifier_id"],
        "outcome": v["outcome"],
        "notes": v.get("notes"),
        "created_at": v["created_at"],
    }


def regression_run_dto(r: dict) -> dict:
    return {
        "id": r["id"],
        "defect_id": r["defect_id"],
        "module_id": r["module_id"],
        "test_suite_key": r["test_suite_key"],
        "started_at_minute": r["started_at_minute"],
        "ended_at_minute": r.get("ended_at_minute"),
        "result": r.get("result"),
        "impact_scope": r["impact_scope"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def sla_pause_dto(p: dict) -> dict:
    return {
        "id": p["id"],
        "defect_id": p["defect_id"],
        "started_at_minute": p["started_at_minute"],
        "ended_at_minute": p.get("ended_at_minute"),
        "reason": p["reason"],
        "paused_by": p["paused_by"],
        "created_at": p["created_at"],
    }


def audit_entry_dto(a: dict) -> dict:
    return {
        "id": a["id"],
        "defect_id": a.get("defect_id"),
        "event_type": a["event_type"],
        "actor_id": a["actor_id"],
        "from_value": a.get("from_value"),
        "to_value": a.get("to_value"),
        "at_minute": a["at_minute"],
        "external_payload": a.get("external_payload"),
        "created_at": a["created_at"],
    }

"""Resource serializers — return JSON-safe dicts for API responses."""

import db


COMMON_FAT = ("id", "created_at", "updated_at", "version")
COMMON_LEAN = ("id", "created_at")


def project_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "project_name": p["project_name"],
        "task_type": p["task_type"],
        "difficulty": p["difficulty"],
        "guideline_doc_url": p.get("guideline_doc_url", ""),
        "sample_preview_urls": list(p.get("sample_preview_urls", [])),
        "package_size": p["package_size"],
        "distribution_mode": p["distribution_mode"],
        "unit_price_cents": p["unit_price_cents"],
        "pass_rate_target": p["pass_rate_target"],
        "timeout_seconds": p["timeout_seconds"],
        "golden_sample_count": db.find_many("golden_samples", project_id=p["id"]).__len__(),
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def golden_sample_view(g: dict) -> dict:
    return {
        "id": g["id"],
        "project_id": g["project_id"],
        "payload_url": g["payload_url"],
        "expected_label": g["expected_label"],
        "created_at": g["created_at"],
    }


def task_package_view(pkg: dict) -> dict:
    return {
        "id": pkg["id"],
        "project_id": pkg["project_id"],
        "batch_no": pkg["batch_no"],
        "item_count": pkg["item_count"],
        "golden_inserted_count": pkg.get("golden_inserted_count", 0),
        "assigned_annotator_id": pkg.get("assigned_annotator_id"),
        "claimed_at": pkg.get("claimed_at"),
        "deadline_at": pkg.get("deadline_at"),
        "rework_round": pkg.get("rework_round", 0),
        "tier_required": pkg.get("tier_required"),
        "status": pkg["status"],
        "consistency_score": pkg.get("consistency_score"),
        "created_at": pkg["created_at"],
        "updated_at": pkg["updated_at"],
        "version": pkg["version"],
    }


def annotator_view(a: dict) -> dict:
    return {
        "id": a["id"],
        "display_name": a["display_name"],
        "domain_tags": list(a.get("domain_tags", [])),
        "entry_test_score": a["entry_test_score"],
        "tier": a["tier"],
        "lifetime_pass_rate": a.get("lifetime_pass_rate", 1.0),
        "rolling_pass_rate": a.get("rolling_pass_rate", 1.0),
        "golden_hit_rate": a.get("golden_hit_rate", 1.0),
        "status": a["status"],
        "last_evaluated_at": a.get("last_evaluated_at"),
        "submitted_count": a.get("submitted_count", 0),
        "approved_count": a.get("approved_count", 0),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def submission_view(s: dict) -> dict:
    return {
        "id": s["id"],
        "package_id": s["package_id"],
        "annotator_id": s["annotator_id"],
        "rework_round": s["rework_round"],
        "labels": s["labels"],
        "golden_correct": s["golden_correct"],
        "golden_total": s["golden_total"],
        "created_at": s["created_at"],
    }


def inspection_view(i: dict) -> dict:
    return {
        "id": i["id"],
        "package_id": i["package_id"],
        "submission_id": i["submission_id"],
        "inspector_id": i["inspector_id"],
        "sample_size": i["sample_size"],
        "defects_found": i.get("defects_found"),
        "pass_rate": i.get("pass_rate"),
        "outcome": i.get("outcome"),
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def appeal_view(ap: dict) -> dict:
    return {
        "id": ap["id"],
        "package_id": ap["package_id"],
        "inspection_id": ap["inspection_id"],
        "annotator_id": ap["annotator_id"],
        "reason": ap["reason"],
        "arbiter_id": ap.get("arbiter_id"),
        "decision": ap.get("decision"),
        "status": ap["status"],
        "created_at": ap["created_at"],
        "updated_at": ap["updated_at"],
        "version": ap["version"],
    }


def ledger_view(e: dict) -> dict:
    return {
        "id": e["id"],
        "annotator_id": e["annotator_id"],
        "package_id": e.get("package_id"),
        "payroll_period_id": e.get("payroll_period_id"),
        "kind": e["kind"],
        "gross_amount_cents": e["gross_amount_cents"],
        "settlement_state": e["settlement_state"],
        "created_at": e["created_at"],
    }


def payroll_period_view(pp: dict) -> dict:
    return {
        "id": pp["id"],
        "cycle_label": pp["cycle_label"],
        "opens_at": pp["opens_at"],
        "closes_at": pp["closes_at"],
        "tax_rate": pp["tax_rate"],
        "status": pp["status"],
        "created_at": pp["created_at"],
        "updated_at": pp["updated_at"],
        "version": pp["version"],
    }


def audit_log_view(a: dict) -> dict:
    return {
        "id": a["id"],
        "actor_id": a["actor_id"],
        "actor_role": a["actor_role"],
        "subject_kind": a["subject_kind"],
        "subject_id": a["subject_id"],
        "event_type": a["event_type"],
        "from_value": a.get("from_value"),
        "to_value": a.get("to_value"),
        "created_at": a["created_at"],
    }


def external_event_view(e: dict) -> dict:
    return {
        "id": e["id"],
        "target_system": e["target_system"],
        "event_type": e["event_type"],
        "payload_ref_id": e["payload_ref_id"],
        "dispatch_status": e["dispatch_status"],
        "created_at": e["created_at"],
    }

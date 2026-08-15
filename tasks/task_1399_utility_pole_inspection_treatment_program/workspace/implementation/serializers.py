from datetime import datetime
from decimal import Decimal

import db
from calc import iso

TASK_TERMINAL = ("ACCEPTED", "WAIVED", "ESCALATED")
REPLACEMENT_PENDING = ("QUEUED", "DEFERRED", "FUNDED")


def dump(rec, fields):
    out = {}
    for f in fields:
        v = rec.get(f)
        if isinstance(v, datetime):
            v = iso(v)
        elif isinstance(v, Decimal):
            v = float(v)
        out[f] = v
    return out


BUDGET_FIELDS = ["id", "fiscal_year", "total_cents", "committed_cents",
                 "spent_cents", "created_at", "updated_at", "version"]


def ser_budget(r):
    out = dump(r, BUDGET_FIELDS)
    # available_cents computed so total == available + committed + spent always holds
    out["available_cents"] = (r["total_cents"] - r["committed_cents"]
                              - r["spent_cents"])
    # place available right after spent for readability (order irrelevant to JSON)
    return {
        "id": out["id"], "fiscal_year": out["fiscal_year"],
        "total_cents": out["total_cents"],
        "committed_cents": out["committed_cents"],
        "spent_cents": out["spent_cents"],
        "available_cents": out["available_cents"],
        "created_at": out["created_at"], "updated_at": out["updated_at"],
        "version": out["version"],
    }


CYCLE_FIELDS = ["id", "year", "cycle_length_years", "sample_pct",
                "mandatory_zone_tags", "strength_variant_policy", "status",
                "opened_at", "reconciled_at", "sample_pool_size",
                "created_at", "updated_at", "version"]


def ser_cycle(r):
    out = dump(r, CYCLE_FIELDS)
    cycle_tasks = [t for t in db.tasks.values() if t["cycle_id"] == r["id"]]
    out["tasks_total"] = len(cycle_tasks)
    out["tasks_terminal"] = sum(1 for t in cycle_tasks
                                if t["status"] in TASK_TERMINAL)
    out["pending_replacement_count"] = sum(
        1 for o in db.replacements.values()
        if o["cycle_id"] == r["id"] and o["status"] in REPLACEMENT_PENDING)
    return {
        "id": out["id"], "year": out["year"],
        "cycle_length_years": out["cycle_length_years"],
        "sample_pct": out["sample_pct"],
        "mandatory_zone_tags": out["mandatory_zone_tags"],
        "strength_variant_policy": out["strength_variant_policy"],
        "status": out["status"], "opened_at": out["opened_at"],
        "reconciled_at": out["reconciled_at"],
        "sample_pool_size": out["sample_pool_size"],
        "tasks_total": out["tasks_total"],
        "tasks_terminal": out["tasks_terminal"],
        "pending_replacement_count": out["pending_replacement_count"],
        "created_at": out["created_at"], "updated_at": out["updated_at"],
        "version": out["version"],
    }


POLE_FIELDS = ["id", "pole_number", "species", "original_class", "install_date",
               "gis_lat", "gis_lon", "gis_tag", "height_ft", "joint_use",
               "attachment_count_declared", "status", "last_inspection_date",
               "last_treatment_date", "current_remaining_strength_pct",
               "current_classification", "open_treatment_count",
               "created_at", "updated_at", "version"]


def ser_pole(r):
    return dump(r, POLE_FIELDS)


TASK_FIELDS = ["id", "cycle_id", "pole_id", "due_window_start",
               "due_window_end", "status", "rework_count", "shell_thickness_in",
               "sound_wood_pct", "decay_pocket_depth_in", "moisture_pct",
               "hazard_flag", "photos", "submitted_by_user_id",
               "qa_reviewed_by_user_id", "rs_conservative_pct",
               "rs_statistical_pct", "effective_rs_pct", "classification",
               "created_at", "updated_at", "version"]


def ser_task(r):
    return dump(r, TASK_FIELDS)


TREATMENT_FIELDS = ["id", "pole_id", "product_code", "crew_id",
                    "work_start_date", "work_end_date", "cost_cents",
                    "is_warranty_retreat", "source_claim_id", "status",
                    "applied_at", "applied_by_crew_id", "warranty_years",
                    "warranty_end_date", "qa_fail_events",
                    "created_at", "updated_at", "version"]


def ser_treatment(r):
    return dump(r, TREATMENT_FIELDS)


CLAIM_FIELDS = ["id", "treatment_order_id", "claim_reason", "status",
                "filed_at", "filed_by_user_id", "adjudication_note",
                "created_at", "updated_at", "version"]


def ser_claim(r):
    return dump(r, CLAIM_FIELDS)


CREW_FIELDS = ["id", "crew_code", "region", "status", "qa_pass_count",
               "qa_fail_count", "current_cycle_billing_cents",
               "created_at", "updated_at", "version"]


def ser_crew(r):
    out = dump(r, CREW_FIELDS)
    out["quality_score_lifetime"] = float(r["quality_score_lifetime"])
    out["quality_score_rolling"] = float(r["quality_score_rolling"])
    out["qa_event_log"] = [
        {"decision": e["decision"], "decided_at": iso(e["decided_at"]),
         "order_id": e["order_id"]}
        for e in r["qa_event_log"]
    ]
    return {
        "id": out["id"], "crew_code": out["crew_code"], "region": out["region"],
        "status": out["status"], "qa_pass_count": out["qa_pass_count"],
        "qa_fail_count": out["qa_fail_count"],
        "quality_score_lifetime": out["quality_score_lifetime"],
        "quality_score_rolling": out["quality_score_rolling"],
        "qa_event_log": out["qa_event_log"],
        "current_cycle_billing_cents": out["current_cycle_billing_cents"],
        "created_at": out["created_at"], "updated_at": out["updated_at"],
        "version": out["version"],
    }


REPLACEMENT_FIELDS = ["id", "pole_id", "cycle_id", "budget_id",
                      "estimated_cost_cents", "actual_cost_cents",
                      "deferral_count", "escalated_cost_cents",
                      "priority_score", "status", "funded_at",
                      "created_at", "updated_at", "version"]


def ser_replacement(r):
    return dump(r, REPLACEMENT_FIELDS)


AUDIT_FIELDS = ["id", "pole_id", "inspection_task_id", "audit_status",
                "violation_status", "found_attachment_count",
                "unauthorized_count", "cure_deadline", "adjudicated_at",
                "cured_at", "created_at", "updated_at", "version"]


def ser_audit(r):
    return dump(r, AUDIT_FIELDS)


SNAPSHOT_FIELDS = ["id", "cycle_id", "budget_id", "snapshot_seq",
                   "queued_count", "queued_escalated_cost_cents",
                   "funded_count", "budget_available_cents",
                   "budget_committed_cents", "crew_billings", "created_at"]


def ser_snapshot(r):
    return dump(r, SNAPSHOT_FIELDS)

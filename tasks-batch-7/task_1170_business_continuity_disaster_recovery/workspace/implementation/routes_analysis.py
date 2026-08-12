"""BIAs, plans, plan sections (PRD §3.2, §3.3)."""
from flask import Blueprint

from calc import (REQUIRED_SECTION_TYPES, approved_bia, assessment_compute,
                  bia_score, latest_bia, pin_target_bia)
from core import (ALL_ROLES, DB, actor, apply_filters, as_bool, as_enum,
                  as_int, as_num, as_str, body, bump, fail, money2, not_found,
                  ok, opt_str, paginate, req, sorted_by_created, stamp_new,
                  validation)
from routes_registry import get_process_or_404
from serializers import bia_view, plan_view, section_view

bp = Blueprint("analysis", __name__)

IMPACTS = ["NONE", "LOW", "HIGH"]
STRATEGIES = ["ACTIVE_ACTIVE", "WARM_SITE", "COLD_SITE", "MANUAL_WORKAROUND"]
SECTION_TYPES = ["SCOPE", "RECOVERY_STRATEGY", "DEPENDENCY_MAP", "COMMS_PLAN",
                 "SITE_STRATEGY", "WORKFORCE_STRATEGY", "VALIDATION_STRATEGY",
                 "ATTESTATION_MAP"]


def get_bia_or_404(bia_id):
    b = DB.bias.get(bia_id)
    if b is None:
        not_found("ERR_BIA_NOT_FOUND", "BIA")
    return b


def get_plan_or_404(plan_id):
    p = DB.plans.get(plan_id)
    if p is None:
        not_found("ERR_PLAN_NOT_FOUND", "Plan")
    return p


def _process_allows_new_children(process):
    """No new BIA / Plan may be created for a SUSPENDED process (PRD §3.1);
    RETIRED is terminal."""
    if process["status"] in ("SUSPENDED", "RETIRED"):
        fail("ERR_PROCESS_NOT_ACTIVE", 409,
             "The referenced process is not ACTIVE")


def _bia_cycle_unique(process_id, cycle_label, exclude_id=None):
    for b in DB.bias.values():
        if (b["process_id"] == process_id and b["cycle_label"] == cycle_label
                and b["status"] != "SUPERSEDED" and b["id"] != exclude_id):
            fail("ERR_DUPLICATE", 409,
                 "A live BIA with this cycle_label already exists for the process")


def _validate_bia_fields(payload, current=None):
    """Merge payload over current; validate shape rules; return updates."""
    data = dict(current) if current else {}
    for key in ("cycle_label",):
        if key in payload and payload[key] is not None:
            data[key] = as_str(payload[key], key)
    for key in ("rto_target_hours", "rpo_target_hours", "mtpd_hours"):
        if key in payload and payload[key] is not None:
            data[key] = as_int(payload[key], key, minv=0)
    if "peak_period_flag" in payload and payload["peak_period_flag"] is not None:
        data["peak_period_flag"] = as_bool(payload["peak_period_flag"],
                                           "peak_period_flag")
    for key in ("peak_start_month", "peak_end_month"):
        if key in payload and payload[key] is not None:
            data[key] = as_int(payload[key], key, minv=1, maxv=12)
    if "impact_financial_per_hour" in payload \
            and payload["impact_financial_per_hour"] is not None:
        data["impact_financial_per_hour"] = money2(
            as_num(payload["impact_financial_per_hour"],
                   "impact_financial_per_hour", minv=0))
    for key in ("impact_regulatory", "impact_reputational", "impact_operational"):
        if key in payload and payload[key] is not None:
            data[key] = as_enum(payload[key], key, IMPACTS)
    if data.get("peak_period_flag"):
        if data.get("peak_start_month") is None or data.get("peak_end_month") is None:
            fail("ERR_INVALID_REQUEST", 400,
                 "peak_start_month and peak_end_month are required when "
                 "peak_period_flag is true")
    if (data.get("mtpd_hours") is not None and data.get("rto_target_hours") is not None
            and data["mtpd_hours"] < data["rto_target_hours"]):
        fail("ERR_MTPD_BELOW_RTO", 422,
             "mtpd_hours must be >= rto_target_hours")
    return data


# --------------------------------------------------------------------------
# BIAs
# --------------------------------------------------------------------------

@bp.post("/resilience/bias")
def create_bia():
    actor(["BIAAnalyst"])
    payload = body()
    process_id = req(payload, "process_id")
    process = DB.processes.get(process_id)
    if process is None:
        not_found("ERR_PROCESS_NOT_FOUND", "Process")
    for field in ("cycle_label", "peak_period_flag", "impact_regulatory",
                  "impact_reputational", "impact_operational"):
        req(payload, field)
    for field in ("rto_target_hours", "rpo_target_hours", "mtpd_hours",
                  "impact_financial_per_hour"):
        req(payload, field)
    data = _validate_bia_fields(payload)
    _process_allows_new_children(process)
    _bia_cycle_unique(process_id, data["cycle_label"])
    bia = {
        "process_id": process_id,
        "cycle_label": data["cycle_label"],
        "rto_target_hours": data["rto_target_hours"],
        "rpo_target_hours": data["rpo_target_hours"],
        "mtpd_hours": data["mtpd_hours"],
        "peak_period_flag": data["peak_period_flag"],
        "peak_start_month": data.get("peak_start_month"),
        "peak_end_month": data.get("peak_end_month"),
        "impact_financial_per_hour": data["impact_financial_per_hour"],
        "impact_regulatory": data["impact_regulatory"],
        "impact_reputational": data["impact_reputational"],
        "impact_operational": data["impact_operational"],
        "score_variant": "PROVISIONAL",
        "decided_by_contact_id": None,
        "status": "DRAFT",
    }
    bia["criticality_score"] = bia_score(bia, final=False)
    stamp_new(bia)
    DB.bias[bia["id"]] = bia
    return ok(bia_view(bia), status=201)


@bp.get("/resilience/bias")
def list_bias():
    actor(ALL_ROLES)
    items = apply_filters(list(DB.bias.values()), [
        ("process_id", "process_id"),
        ("status", "status"),
        ("cycle_label", "cycle_label"),
        ("decided_by_contact_id", "decided_by_contact_id"),
    ])
    page, meta = paginate(sorted_by_created(items))
    return ok([bia_view(b) for b in page], response_type="array", pagination=meta)


@bp.get("/resilience/bias/<biaId>")
def get_bia(biaId):
    actor(ALL_ROLES)
    return ok(bia_view(get_bia_or_404(biaId)))


@bp.put("/resilience/bias/<biaId>")
def update_bia(biaId):
    actor(["BIAAnalyst"])
    bia = get_bia_or_404(biaId)
    payload = body()
    data = _validate_bia_fields(payload, current=bia)
    if bia["status"] not in ("DRAFT", "REJECTED"):
        fail("ERR_INVALID_STATE", 409,
             "A BIA may be updated only while DRAFT or REJECTED")
    if data["cycle_label"] != bia["cycle_label"]:
        _bia_cycle_unique(bia["process_id"], data["cycle_label"],
                          exclude_id=bia["id"])
    for key in ("cycle_label", "rto_target_hours", "rpo_target_hours",
                "mtpd_hours", "peak_period_flag", "peak_start_month",
                "peak_end_month", "impact_financial_per_hour",
                "impact_regulatory", "impact_reputational", "impact_operational"):
        if key in data:
            bia[key] = data[key]
    # PROVISIONAL score recomputes on every update (PRD §3.2)
    if bia["score_variant"] == "PROVISIONAL":
        bia["criticality_score"] = bia_score(bia, final=False)
    bump(bia)
    return ok(bia_view(bia))


@bp.post("/resilience/bias/<biaId>/submit")
def submit_bia(biaId):
    actor(["BIAAnalyst"])
    bia = get_bia_or_404(biaId)
    if bia["status"] not in ("DRAFT", "REJECTED"):
        fail("ERR_INVALID_STATE", 409,
             "A BIA may be submitted only from DRAFT or REJECTED")
    process = DB.processes.get(bia["process_id"])
    if process is None or process["status"] != "ACTIVE":
        fail("ERR_PROCESS_NOT_ACTIVE", 409,
             "The referenced process must be ACTIVE")
    bia["status"] = "SUBMITTED"
    bump(bia)
    return ok(bia_view(bia))


@bp.post("/resilience/bias/<biaId>/decide")
def decide_bia(biaId):
    who = actor(["RiskCommittee"], sod_identity=True)
    bia = get_bia_or_404(biaId)
    payload = body()
    decision = as_enum(req(payload, "decision"), "decision",
                       ["APPROVE", "REJECT"])
    if bia["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", 409,
             "A BIA may be decided only while SUBMITTED")
    if bia.get("decided_by_contact_id") is not None \
            and bia["decided_by_contact_id"] == who["id"]:
        fail("ERR_SOD_VIOLATION", 403,
             "The deciding contact must differ from the current decider")
    bia["decided_by_contact_id"] = who["id"]
    if decision == "REJECT":
        bia["status"] = "REJECTED"
        bump(bia)
        return ok(bia_view(bia))

    # APPROVE: freeze FINAL score, then supersede + adoption + recalculation.
    bia["criticality_score"] = bia_score(bia, final=True)
    bia["score_variant"] = "FINAL"
    bia["status"] = "APPROVED"
    bump(bia)

    process_id = bia["process_id"]
    # Supersede hop: prior APPROVED BIA of the same process.
    for other in DB.bias.values():
        if (other["process_id"] == process_id and other["id"] != bia["id"]
                and other["status"] == "APPROVED"):
            other["status"] = "SUPERSEDED"
            bump(other)
    # Adoption refresh: re-pin DRAFT / IN_REVIEW plans targeting elsewhere.
    for plan in DB.plans.values():
        if (plan["process_id"] == process_id
                and plan["status"] in ("DRAFT", "IN_REVIEW")
                and plan.get("target_bia_id") != bia["id"]):
            plan["target_bia_id"] = bia["id"]
            plan["last_adoption_check_cycle"] = bia["cycle_label"]
            bump(plan)
    # Recalculation refresh: capabilities' meets_bia is computed on read;
    # DRAFT assessments recompute meets_required_rto against the new targets.
    for assessment in DB.assessments.values():
        if assessment["process_id"] == process_id \
                and assessment["status"] == "DRAFT":
            assessment["meets_required_rto"] = (
                assessment["assessed_rto_hours"] <= bia["rto_target_hours"])
    return ok(bia_view(bia))


# --------------------------------------------------------------------------
# Plans
# --------------------------------------------------------------------------

def _plan_version_unique(process_id, version_no, exclude_id=None):
    for p in DB.plans.values():
        if (p["process_id"] == process_id and p["version_no"] == version_no
                and p["status"] != "RETIRED" and p["id"] != exclude_id):
            fail("ERR_DUPLICATE", 409,
                 "A live plan with this version_no already exists for the process")


@bp.post("/resilience/plans")
def create_plan():
    actor(["PlanAuthor"])
    payload = body()
    process_id = req(payload, "process_id")
    process = DB.processes.get(process_id)
    if process is None:
        not_found("ERR_PROCESS_NOT_FOUND", "Process")
    title = as_str(req(payload, "title"), "title")
    version_no = as_int(req(payload, "version_no"), "version_no")
    strategy = as_enum(req(payload, "strategy_type"), "strategy_type",
                       STRATEGIES)
    rto = as_int(req(payload, "rto_committed_hours"), "rto_committed_hours",
                 minv=0)
    rpo = as_int(req(payload, "rpo_committed_hours"), "rpo_committed_hours",
                 minv=0)
    _process_allows_new_children(process)
    _plan_version_unique(process_id, version_no)
    plan = {
        "process_id": process_id,
        "title": title,
        "version_no": version_no,
        "strategy_type": strategy,
        "rto_committed_hours": rto,
        "rpo_committed_hours": rpo,
        "target_bia_id": pin_target_bia(process_id),
        "approved_version_no": None,
        "supersedes_plan_id": None,
        "last_adoption_check_cycle": None,
        "status": "DRAFT",
    }
    stamp_new(plan)
    DB.plans[plan["id"]] = plan
    return ok(plan_view(plan), status=201)


@bp.get("/resilience/plans")
def list_plans():
    actor(ALL_ROLES)
    items = apply_filters(list(DB.plans.values()), [
        ("process_id", "process_id"),
        ("status", "status"),
        ("target_bia_id", "target_bia_id"),
        ("supersedes_plan_id", "supersedes_plan_id"),
    ])
    page, meta = paginate(sorted_by_created(items))
    return ok([plan_view(p) for p in page], response_type="array", pagination=meta)


@bp.get("/resilience/plans/<planId>")
def get_plan(planId):
    actor(ALL_ROLES)
    return ok(plan_view(get_plan_or_404(planId)))


@bp.put("/resilience/plans/<planId>")
def update_plan(planId):
    actor(["PlanAuthor"])
    plan = get_plan_or_404(planId)
    payload = body()
    expected = req(payload, "expected_plan_version")
    expected = as_int(expected, "expected_plan_version")
    updates = {}
    if "title" in payload and payload["title"] is not None:
        updates["title"] = as_str(payload["title"], "title")
    if "strategy_type" in payload and payload["strategy_type"] is not None:
        updates["strategy_type"] = as_enum(payload["strategy_type"],
                                           "strategy_type", STRATEGIES)
    for key in ("rto_committed_hours", "rpo_committed_hours"):
        if key in payload and payload[key] is not None:
            updates[key] = as_int(payload[key], key, minv=0)
    if plan["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409,
             "A plan may be updated only while DRAFT")
    # OCC is the final gate (PRD §2.10 layer 15)
    if expected != plan["version"]:
        fail("ERR_STALE_VERSION", 412,
             "expected_plan_version does not match the plan's current version")
    for key, value in updates.items():
        plan[key] = value
    bump(plan)
    return ok(plan_view(plan))


@bp.post("/resilience/plans/<planId>/submit")
def submit_plan(planId):
    actor(["PlanAuthor"])
    plan = get_plan_or_404(planId)
    if plan["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409,
             "A plan may be submitted only from DRAFT")
    process = DB.processes.get(plan["process_id"])
    if process is None or process["status"] != "ACTIVE":
        fail("ERR_PROCESS_NOT_ACTIVE", 409,
             "The referenced process must be ACTIVE")
    present = {s["section_type"] for s in DB.sections.values()
               if s["plan_id"] == plan["id"]}
    if not REQUIRED_SECTION_TYPES.issubset(present):
        fail("ERR_REQUIRED_SECTION_MISSING", 422,
             "Plan lacks one of RECOVERY_STRATEGY / DEPENDENCY_MAP / COMMS_PLAN")
    plan["status"] = "IN_REVIEW"
    bump(plan)
    return ok(plan_view(plan))


@bp.post("/resilience/plans/<planId>/approve")
def approve_plan(planId):
    actor(["PlanApprover"])
    plan = get_plan_or_404(planId)
    if plan["status"] != "IN_REVIEW":
        fail("ERR_INVALID_STATE", 409,
             "A plan may be approved only from IN_REVIEW")
    target = DB.bias.get(plan["target_bia_id"]) if plan.get("target_bia_id") else None
    if target is None or target["status"] != "APPROVED":
        fail("ERR_PLAN_TARGETS_UNAPPROVED_BIA", 422,
             "target_bia_id must resolve to an APPROVED BIA")
    if plan["rto_committed_hours"] > target["rto_target_hours"]:
        fail("ERR_PLAN_EXCEEDS_BIA_RTO", 422,
             "Plan rto_committed_hours exceeds the target BIA rto_target_hours")
    if plan["rpo_committed_hours"] > target["rpo_target_hours"]:
        fail("ERR_PLAN_EXCEEDS_BIA_RPO", 422,
             "Plan rpo_committed_hours exceeds the target BIA rpo_target_hours")
    # Supersede cascade: retire the currently APPROVED sibling plan.
    prior = None
    for other in DB.plans.values():
        if (other["process_id"] == plan["process_id"]
                and other["id"] != plan["id"] and other["status"] == "APPROVED"):
            prior = other
            break
    if prior is not None:
        prior["status"] = "RETIRED"
        bump(prior)
        plan["supersedes_plan_id"] = prior["id"]
    plan["approved_version_no"] = plan["version_no"]
    plan["status"] = "APPROVED"
    bump(plan)
    return ok(plan_view(plan))


@bp.post("/resilience/plans/<planId>/reject")
def reject_plan(planId):
    actor(["PlanApprover"])
    plan = get_plan_or_404(planId)
    if plan["status"] != "IN_REVIEW":
        fail("ERR_INVALID_STATE", 409,
             "A plan may be rejected only from IN_REVIEW")
    plan["status"] = "DRAFT"
    bump(plan)
    return ok(plan_view(plan))


@bp.post("/resilience/plans/<planId>/retire")
def retire_plan(planId):
    actor(["PlanApprover"])
    plan = get_plan_or_404(planId)
    if plan["status"] not in ("DRAFT", "APPROVED"):
        fail("ERR_INVALID_STATE", 409,
             "A plan may be retired only from DRAFT or APPROVED")
    if plan["status"] == "APPROVED":
        if any(e["plan_id"] == plan["id"]
               and e["status"] in ("SCHEDULED", "IN_PROGRESS")
               for e in DB.exercises.values()):
            fail("ERR_PLAN_HAS_ACTIVE_EXERCISE", 409,
                 "Plan has a SCHEDULED or IN_PROGRESS exercise")
        if any(a["process_id"] == plan["process_id"]
               and a["status"] in ("ACTIVE", "ALL_NOTIFIED", "ACKNOWLEDGED")
               for a in DB.activations.values()):
            fail("ERR_PLAN_HAS_LIVE_ACTIVATION", 409,
                 "Plan's process has a live activation")
    plan["status"] = "RETIRED"
    bump(plan)
    return ok(plan_view(plan))


# --------------------------------------------------------------------------
# Plan sections
# --------------------------------------------------------------------------

def _section_unique(plan_id, order_index, exclude_id=None):
    for s in DB.sections.values():
        if (s["plan_id"] == plan_id and s["order_index"] == order_index
                and s["id"] != exclude_id):
            fail("ERR_DUPLICATE", 409,
                 "A section with this order_index already exists in the plan")


def _require_plan_draft(plan):
    if plan["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409,
             "Plan sections may be modified only while the plan is DRAFT")


@bp.get("/resilience/plans/<planId>/sections")
def list_sections(planId):
    actor(ALL_ROLES)
    get_plan_or_404(planId)
    items = [s for s in DB.sections.values() if s["plan_id"] == planId]
    page, meta = paginate(sorted_by_created(items))
    return ok([section_view(s) for s in page], response_type="array",
              pagination=meta)


@bp.post("/resilience/plans/<planId>/sections")
def create_section(planId):
    actor(["PlanAuthor"])
    plan = get_plan_or_404(planId)
    payload = body()
    section_type = as_enum(req(payload, "section_type"), "section_type",
                           SECTION_TYPES)
    content = as_str(req(payload, "content"), "content")
    order_index = as_int(req(payload, "order_index"), "order_index")
    _require_plan_draft(plan)
    _section_unique(planId, order_index)
    section = {
        "plan_id": planId,
        "section_type": section_type,
        "content": content,
        "order_index": order_index,
        "required_flag": section_type in REQUIRED_SECTION_TYPES,
    }
    stamp_new(section)
    DB.sections[section["id"]] = section
    return ok(section_view(section), status=201)


def _get_section_scoped(planId, sectionId):
    section = DB.sections.get(sectionId)
    if section is None or section["plan_id"] != planId:
        not_found("ERR_SECTION_NOT_FOUND", "Plan section")
    return section


@bp.get("/resilience/plans/<planId>/sections/<sectionId>")
def get_section(planId, sectionId):
    actor(ALL_ROLES)
    get_plan_or_404(planId)
    return ok(section_view(_get_section_scoped(planId, sectionId)))


@bp.put("/resilience/plans/<planId>/sections/<sectionId>")
def update_section(planId, sectionId):
    actor(["PlanAuthor"])
    plan = get_plan_or_404(planId)
    section = _get_section_scoped(planId, sectionId)
    payload = body()
    updates = {}
    if "content" in payload and payload["content"] is not None:
        updates["content"] = as_str(payload["content"], "content")
    if "order_index" in payload and payload["order_index"] is not None:
        updates["order_index"] = as_int(payload["order_index"], "order_index")
    _require_plan_draft(plan)
    if "order_index" in updates and updates["order_index"] != section["order_index"]:
        _section_unique(planId, updates["order_index"], exclude_id=section["id"])
    for key, value in updates.items():
        section[key] = value
    bump(section)
    return ok(section_view(section))


@bp.delete("/resilience/plans/<planId>/sections/<sectionId>")
def delete_section(planId, sectionId):
    actor(["PlanAuthor"])
    plan = get_plan_or_404(planId)
    section = _get_section_scoped(planId, sectionId)
    _require_plan_draft(plan)
    del DB.sections[sectionId]
    return "", 204

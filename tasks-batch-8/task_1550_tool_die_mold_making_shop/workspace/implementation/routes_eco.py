"""Engineering change and rework authorization endpoints (PRD §3.7)."""
from decimal import Decimal

from flask import Blueprint, request

from store import STORE
from helpers import (ApiError, endpoint, get_body, validate_payload, ok, created,
                     ok_list, paginate, filter_eq, sort_created, not_found,
                     stamp_new, bump)
from domain import (ser_eco, ser_ra, milestones_of_job, tool_by_job, ra_by_eco,
                    eco_impact_reprice, rhu, BILLING_PCT, REQUESTED_BY)

bp = Blueprint("eco", __name__)


def _approve_cascade(eco):
    """The four-hop re-baseline cascade of PRD §3.7 on customer APPROVED."""
    job = STORE.jobs[eco["build_job_id"]]
    # Hop 1 — exactly one rework authorization, snapshotting the total charge.
    ra = stamp_new({
        "engineering_change_id": eco["id"],
        "build_job_id": job["id"],
        "authorized_cost_cents": eco["total_charge_cents"],
        "consumed_cost_cents": None,
        "status": "AUTHORIZED",
    })
    STORE.ras[ra["id"]] = ra
    # Hop 2 — contract re-baseline, milestone reopen, replan.
    job["contract_value_cents"] += eco["total_charge_cents"]
    ms_list = milestones_of_job(job["id"])
    reopened_any = False
    for m in ms_list:
        if m["seq"] >= eco["affects_from_milestone_seq"] and m["status"] in ("EARNED", "INVOICED"):
            m["status"] = "REOPENED"
            m["completed_at"] = None
            reopened_any = True
            # Hop 3 — void the reopened milestone's open invoices.
            for inv in STORE.invoices.values():
                if (inv["build_milestone_id"] == m["id"]
                        and inv["status"] in ("ISSUED", "PARTIALLY_PAID")):
                    inv["status"] = "VOID"
                    inv["void_reason"] = "ECO_REWORK"
                    bump(inv)
            bump(m)
    replanned = [m for m in ms_list if m["status"] in ("PENDING", "REOPENED")]
    if replanned:
        new_contract = job["contract_value_cents"]
        computed = {m["id"]: rhu(Decimal(new_contract) * BILLING_PCT[m["seq"] - 1] / 100)
                    for m in replanned}
        # The highest-seq milestone in the replanned set absorbs the remainder so
        # all six planned amounts sum exactly to the new contract value.
        anchor = max(replanned, key=lambda m: m["seq"])
        locked_sum = sum(m["planned_amount_cents"] for m in ms_list
                         if m["status"] not in ("PENDING", "REOPENED"))
        others_sum = sum(v for k, v in computed.items() if k != anchor["id"])
        computed[anchor["id"]] = new_contract - locked_sum - others_sum
        for m in replanned:
            if m["planned_amount_cents"] != computed[m["id"]]:
                m["planned_amount_cents"] = computed[m["id"]]
            bump(m)
    # Hop 4 — job and tool regression when at least one milestone reopened.
    if reopened_any and job["status"] in ("TRYOUT_PHASE", "BUYOFF_PASSED", "READY_TO_SHIP"):
        job["status"] = "IN_BUILD"
        tool = tool_by_job(job["id"])
        if tool is not None and tool["physical_status"] in ("TRYOUT", "AWAITING_SHIPMENT"):
            tool["physical_status"] = "IN_BUILD"
            bump(tool)
    eco["status"] = "APPROVED"
    bump(eco)
    bump(job)  # the contract baseline changed (stored field)


@bp.route("/engineering-changes", methods=["POST"])
@endpoint(roles=["ToolingEngineer", "Customer"])
def create_eco(uid, role):
    data = validate_payload(get_body(), [
        ("build_job_id", "str", True),
        ("requested_by", "enum", True, {"values": REQUESTED_BY}),
        ("description", "str", True),
        ("affects_from_milestone_seq", "int", True, {"min": 1, "max": 6}),
        ("expected_build_job_version", "int", True),
    ])
    # Shape tier: requested_by must match the caller's role.
    if role == "ToolingEngineer" and data["requested_by"] != "SHOP":
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "ToolingEngineer callers file with requested_by=SHOP")
    if role == "Customer" and data["requested_by"] != "CUSTOMER":
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Customer callers file with requested_by=CUSTOMER")
    job = STORE.jobs.get(data["build_job_id"])
    if job is None:
        not_found("BUILD_JOB")
    # Tier 5: ownership for customer-initiated changes.
    if role == "Customer" and job["customer_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Customers may only file changes against their own jobs")
    # Tier 6: OCC against the job version.
    if data["expected_build_job_version"] != job["version"]:
        raise ApiError("ERR_STALE_BUILD_JOB_VERSION", 412,
                       "The build job version has advanced since it was observed")
    # Tier 7: job state gates.
    if job["status"] == "ON_HOLD":
        raise ApiError("ERR_JOB_ON_HOLD", 409,
                       "Engineering changes may not be filed while the job is ON_HOLD")
    if job["status"] not in ("IN_BUILD", "TRYOUT_PHASE", "BUYOFF_PASSED", "READY_TO_SHIP"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The job is not in a state that accepts engineering changes")
    eco = stamp_new({
        "build_job_id": job["id"],
        "requested_by": data["requested_by"],
        "description": data["description"],
        "affects_from_milestone_seq": data["affects_from_milestone_seq"],
        "rework_hours": None,
        "scrapped_material_cost_cents": None,
        "lead_extension_weeks": None,
        "labor_cost_cents": None,
        "material_cost_cents": None,
        "impact_cost_cents": None,
        "schedule_penalty_cents": None,
        "total_charge_cents": None,
        "status": "SUBMITTED",
    })
    STORE.ecos[eco["id"]] = eco
    bump(job)  # filing an engineering change increments the job's version
    return created(ser_eco(eco))


@bp.route("/engineering-changes", methods=["GET"])
@endpoint(roles=None)
def list_ecos(uid, role):
    items = sort_created(list(STORE.ecos.values()))
    items = filter_eq(items, "build_job_id", request.args.get("build_job_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, meta = paginate(items)
    return ok_list([ser_eco(e) for e in page], meta)


@bp.route("/engineering-changes/<ecoId>", methods=["GET"])
@endpoint(roles=None)
def get_eco(uid, role, ecoId):
    eco = STORE.ecos.get(ecoId)
    if eco is None:
        not_found("ENGINEERING_CHANGE")
    return ok(ser_eco(eco))


@bp.route("/engineering-changes/<ecoId>/assess", methods=["POST"])
@endpoint(roles=["ToolingEngineer"])
def assess_eco(uid, role, ecoId):
    data = validate_payload(get_body(), [
        ("rework_hours", "num", True, {"min": 0}),
        ("scrapped_material_cost_cents", "int", True, {"min": 0}),
        ("lead_extension_weeks", "int", True, {"min": 0}),
    ])
    eco = STORE.ecos.get(ecoId)
    if eco is None:
        not_found("ENGINEERING_CHANGE")
    if eco["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SUBMITTED change may be assessed")
    job = STORE.jobs[eco["build_job_id"]]
    priced = eco_impact_reprice(job, data["rework_hours"],
                                data["scrapped_material_cost_cents"],
                                data["lead_extension_weeks"])
    eco["rework_hours"] = data["rework_hours"]
    eco["scrapped_material_cost_cents"] = data["scrapped_material_cost_cents"]
    eco["lead_extension_weeks"] = data["lead_extension_weeks"]
    eco.update(priced)
    eco["status"] = "IMPACT_ASSESSED"
    bump(eco)
    return ok(ser_eco(eco))


@bp.route("/engineering-changes/<ecoId>/customer-decision", methods=["POST"])
@endpoint(roles=["Customer"])
def eco_customer_decision(uid, role, ecoId):
    data = validate_payload(get_body(), [
        ("decision", "enum", True, {"values": {"APPROVED", "REJECTED"}}),
    ])
    eco = STORE.ecos.get(ecoId)
    if eco is None:
        not_found("ENGINEERING_CHANGE")
    job = STORE.jobs[eco["build_job_id"]]
    if job["customer_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Only the job's owning customer may decide the change")
    if eco["status"] != "IMPACT_ASSESSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an IMPACT_ASSESSED change may be decided")
    if data["decision"] == "REJECTED":
        eco["status"] = "REJECTED"
        bump(eco)
        return ok(ser_eco(eco))
    _approve_cascade(eco)
    return ok(ser_eco(eco))


@bp.route("/engineering-changes/<ecoId>/verify", methods=["POST"])
@endpoint(roles=["ToolingEngineer"])
def verify_eco(uid, role, ecoId):
    validate_payload(get_body(), [])
    eco = STORE.ecos.get(ecoId)
    if eco is None:
        not_found("ENGINEERING_CHANGE")
    if eco["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an APPROVED change may be verified")
    ra = ra_by_eco(eco["id"])
    if ra is None or ra["status"] not in ("COMPLETED", "CANCELLED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Verification requires the linked authorization COMPLETED or CANCELLED")
    eco["status"] = "VERIFIED"
    bump(eco)
    return ok(ser_eco(eco))


# ---------------------------------------------------------------------------
# Rework authorizations
# ---------------------------------------------------------------------------

@bp.route("/rework-authorizations", methods=["GET"])
@endpoint(roles=None)
def list_ras(uid, role):
    items = sort_created(list(STORE.ras.values()))
    items = filter_eq(items, "build_job_id", request.args.get("build_job_id"))
    items = filter_eq(items, "engineering_change_id",
                      request.args.get("engineering_change_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, meta = paginate(items)
    return ok_list([ser_ra(r) for r in page], meta)


@bp.route("/rework-authorizations/<raId>", methods=["GET"])
@endpoint(roles=None)
def get_ra(uid, role, raId):
    ra = STORE.ras.get(raId)
    if ra is None:
        not_found("REWORK_AUTHORIZATION")
    return ok(ser_ra(ra))


@bp.route("/rework-authorizations/<raId>/start", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def start_ra(uid, role, raId):
    validate_payload(get_body(), [])
    ra = STORE.ras.get(raId)
    if ra is None:
        not_found("REWORK_AUTHORIZATION")
    if ra["status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an AUTHORIZED rework authorization may be started")
    ra["status"] = "IN_PROGRESS"
    bump(ra)
    return ok(ser_ra(ra))


@bp.route("/rework-authorizations/<raId>/complete", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def complete_ra(uid, role, raId):
    data = validate_payload(get_body(), [
        ("actual_cost_cents", "int", True, {"min": 0}),
    ])
    ra = STORE.ras.get(raId)
    if ra is None:
        not_found("REWORK_AUTHORIZATION")
    if ra["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an IN_PROGRESS rework authorization may be completed")
    if data["actual_cost_cents"] > ra["authorized_cost_cents"]:
        raise ApiError("ERR_REWORK_COST_OVERRUN", 422,
                       "Actual cost exceeds the authorized amount")
    ra["consumed_cost_cents"] = data["actual_cost_cents"]
    ra["status"] = "COMPLETED"
    bump(ra)
    return ok(ser_ra(ra))


@bp.route("/rework-authorizations/<raId>/cancel", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def cancel_ra(uid, role, raId):
    validate_payload(get_body(), [])
    ra = STORE.ras.get(raId)
    if ra is None:
        not_found("REWORK_AUTHORIZATION")
    if ra["status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an AUTHORIZED rework authorization may be cancelled")
    ra["status"] = "CANCELLED"
    bump(ra)
    return ok(ser_ra(ra))

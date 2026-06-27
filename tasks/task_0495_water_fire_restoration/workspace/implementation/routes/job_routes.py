from flask import Blueprint, request

from clock import clock, format_iso8601_ms, add_days
from db import db, stamp_create, touch
from errors import err
from middleware import auth
from response import object_response, list_response, success
from services import calc, domain
from services.query import get_or_404, get_ref_or_404, paginate
from validate import (
    get_body, req_str, req_enum, opt_int, pagination_params,
)

bp = Blueprint("jobs", __name__)

LOSS_TYPES = {"WATER", "FIRE", "SMOKE"}


# ----------------------------------------------------------------------------
# FNOL intake / CRUD
# ----------------------------------------------------------------------------
@bp.route("/restoration/jobs", methods=["POST"])
def create_job():
    auth(["Dispatcher", "PlatformAdmin"])
    body = get_body()
    # priority 4: claim_id body FK existence.
    claim_id = req_str(body, "claim_id")
    get_ref_or_404(db.claims, claim_id)

    property_address = req_str(body, "property_address")
    loss_type = req_enum(body, "loss_type", LOSS_TYPES)

    if loss_type == "WATER":
        # Both required for a WATER loss; enum/range enforced.
        water_category = opt_int(body, "water_category", default=None)
        water_class = opt_int(body, "water_class", default=None)
        if water_category is None or water_class is None:
            raise err("ERR_INVALID_REQUEST",
                      "water_category and water_class are required for a WATER loss.")
        if water_category not in (1, 2, 3):
            raise err("ERR_INVALID_REQUEST", "water_category must be 1, 2, or 3.")
        if water_class not in (1, 2, 3, 4):
            raise err("ERR_INVALID_REQUEST", "water_class must be 1, 2, 3, or 4.")
    else:
        water_category = None
        water_class = None

    antimicrobial_required = (water_category == 3) or (loss_type in ("FIRE", "SMOKE"))

    entity = {
        "claim_id": claim_id,
        "property_address": property_address,
        "loss_type": loss_type,
        "water_category": water_category,
        "water_class": water_class,
        "assigned_technician_id": None,
        "antimicrobial_required": antimicrobial_required,
        "monitoring_day": 0,
        "drying_status": "NOT_STARTED",
        "status": "FNOL",
        "completed_at": None,
        "warranty_expires_on": None,
    }
    stamp_create(entity)
    db.jobs[entity["id"]] = entity
    return object_response(entity, status=201)


@bp.route("/restoration/jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    auth(["Dispatcher", "PlatformAdmin", "Technician", "Adjuster"])
    return object_response(get_or_404(db.jobs, job_id))


@bp.route("/restoration/jobs", methods=["GET"])
def list_jobs():
    auth(["Dispatcher", "PlatformAdmin", "Technician", "Adjuster"])
    claim_id = request.args.get("claim_id")
    status = request.args.get("status")
    assigned_technician_id = request.args.get("assigned_technician_id")
    limit, offset = pagination_params()

    items = list(db.jobs.values())
    if claim_id is not None:
        items = [j for j in items if j["claim_id"] == claim_id]
    if status is not None:
        items = [j for j in items if j["status"] == status]
    if assigned_technician_id is not None:
        items = [j for j in items if j["assigned_technician_id"] == assigned_technician_id]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


# ----------------------------------------------------------------------------
# Dispatch & the certification gate (PRD §3.2)
# ----------------------------------------------------------------------------
def _cert_ok(job, technician):
    cert = technician["certification"]
    if job["loss_type"] in ("FIRE", "SMOKE") or job["antimicrobial_required"]:
        if cert not in ("AMRT", "ASD"):
            return False
    if job["loss_type"] == "WATER":
        if cert not in ("WRT", "ASD"):
            return False
    return True


@bp.route("/restoration/jobs/<job_id>/dispatch", methods=["POST"])
def dispatch_job(job_id):
    auth(["Dispatcher"])
    job = get_or_404(db.jobs, job_id)
    body = get_body()
    # priority 4: technician_id body FK existence.
    technician_id = req_str(body, "technician_id")
    technician = get_ref_or_404(db.technicians, technician_id)

    # priority 6: state validity — dispatch only from FNOL.
    if job["status"] != "FNOL":
        raise err("ERR_INVALID_STATE", "Job is not in FNOL status.")

    # priority 7: technician must be active.
    if not technician["active"]:
        raise err("ERR_TECHNICIAN_UNAVAILABLE", "Technician is not active.")

    # priority 8: certification must match the loss / antimicrobial profile.
    if not _cert_ok(job, technician):
        raise err("ERR_CERTIFICATION_MISMATCH",
                  "Technician certification does not match the loss profile.")

    job["assigned_technician_id"] = technician_id
    job["status"] = "DISPATCHED"
    touch(job)
    return object_response(job)


# ----------------------------------------------------------------------------
# Lifecycle transitions
# ----------------------------------------------------------------------------
@bp.route("/restoration/jobs/<job_id>/start-mitigation", methods=["POST"])
def start_mitigation(job_id):
    auth(["Technician"])
    job = get_or_404(db.jobs, job_id)
    if job["status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "Job is not in DISPATCHED status.")
    if not domain.non_decommissioned_chambers(job_id):
        raise err("ERR_NO_CHAMBERS", "At least one non-DECOMMISSIONED chamber is required.")
    job["status"] = "MITIGATION"
    touch(job)
    return object_response(job)


@bp.route("/restoration/jobs/<job_id>/begin-monitoring", methods=["POST"])
def begin_monitoring(job_id):
    auth(["Technician"])
    job = get_or_404(db.jobs, job_id)
    if job["status"] != "MITIGATION":
        raise err("ERR_INVALID_STATE", "Job is not in MITIGATION status.")

    # Every OPEN chamber must have ACTIVE placements meeting its required counts.
    for chamber in domain.open_chambers(job_id):
        actives = domain.active_placements_for_chamber(chamber["id"])
        am = sum(1 for p in actives if p["kind"] == "AIR_MOVER")
        dehu = sum(1 for p in actives if p["kind"] == "DEHUMIDIFIER")
        if am < chamber["air_movers_required"] or dehu < chamber["dehumidifiers_required"]:
            raise err("ERR_EQUIPMENT_UNDERSIZED",
                      "An OPEN chamber lacks its required air mover / dehumidifier counts.")

    job["status"] = "MONITORING"
    touch(job)
    return object_response(job)


@bp.route("/restoration/jobs/<job_id>/reopen-mitigation", methods=["POST"])
def reopen_mitigation(job_id):
    auth(["Technician"])
    job = get_or_404(db.jobs, job_id)
    if job["status"] != "MONITORING":
        raise err("ERR_INVALID_STATE", "Job is not in MONITORING status.")
    # At least one non-DECOMMISSIONED chamber must still be not-dry.
    if not any(not c["is_dry"] for c in domain.non_decommissioned_chambers(job_id)):
        raise err("ERR_NOTHING_TO_REOPEN", "Every non-DECOMMISSIONED chamber is already dry.")
    job["status"] = "MITIGATION"
    touch(job)
    return object_response(job)


@bp.route("/restoration/jobs/<job_id>/advance-day", methods=["POST"])
def advance_day(job_id):
    auth(["Technician"])
    job = get_or_404(db.jobs, job_id)
    if job["status"] != "MONITORING":
        raise err("ERR_INVALID_STATE", "Job is not in MONITORING status.")
    job["monitoring_day"] += 1
    touch(job)
    return object_response(job)


@bp.route("/restoration/jobs/<job_id>/complete", methods=["POST"])
def complete_job(job_id):
    auth(["Technician"])
    job = get_or_404(db.jobs, job_id)
    if job["status"] != "MONITORING":
        raise err("ERR_INVALID_STATE", "Job is not in MONITORING status.")

    # precondition 1: drying standard met (every non-DECOMMISSIONED chamber DRIED).
    if job["drying_status"] != "DRY_STANDARD_MET":
        raise err("ERR_DRY_STANDARD_NOT_MET",
                  "Not every non-DECOMMISSIONED chamber is DRIED.")

    # precondition 2: no ACTIVE placement still on the job.
    if domain.active_placements_for_job(job_id):
        raise err("ERR_EQUIPMENT_STILL_DEPLOYED", "An ACTIVE placement is still deployed.")

    # precondition 3: an APPROVED estimate must exist for the job.
    if not any(e["status"] == "APPROVED" for e in domain.job_estimates(job_id)):
        raise err("ERR_NO_APPROVED_ESTIMATE", "No APPROVED ScopeEstimate exists for the job.")

    now = clock.now()
    job["status"] = "COMPLETED"
    job["completed_at"] = format_iso8601_ms(now)
    job["warranty_expires_on"] = format_iso8601_ms(add_days(now, calc.WARRANTY_DAYS))
    touch(job)

    # finalizing side effect: every STORED contents item -> RETURNED.
    for item in domain.job_contents(job_id):
        if item["status"] == "STORED":
            item["status"] = "RETURNED"
            touch(item)

    return object_response(job)


@bp.route("/restoration/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    auth(["Dispatcher"])
    job = get_or_404(db.jobs, job_id)
    status = job["status"]

    if status in ("COMPLETED", "CANCELLED"):
        raise err("ERR_INVALID_STATE", "Job is in a terminal state and cannot be cancelled.")

    if status == "FNOL":
        # no cascade
        pass
    elif status == "DISPATCHED":
        # release the assigned technician
        job["assigned_technician_id"] = None
    elif status in ("MITIGATION", "MONITORING"):
        domain.cancel_cascade_full(job)

    job["status"] = "CANCELLED"
    touch(job)
    return object_response(job)


# ----------------------------------------------------------------------------
# Computed read endpoints (PRD §3.6, §3.7)
# ----------------------------------------------------------------------------
@bp.route("/restoration/jobs/<job_id>/billing", methods=["GET"])
def job_billing(job_id):
    auth(["Adjuster", "Dispatcher", "PlatformAdmin"])
    job = get_or_404(db.jobs, job_id)

    approved = next((e for e in domain.job_estimates(job_id)
                     if e["status"] == "APPROVED"), None)
    scope_lines_total_cents = approved["scope_lines_total_cents"] if approved else 0
    approved_total = approved["estimate_total_cents"] if approved else 0

    final_equipment_cents = 0
    for p in sorted(domain.job_placements(job_id),
                    key=lambda x: (x["created_at"], x["_seq"])):
        rate = calc.AM_DAY_RATE_CENTS if p["kind"] == "AIR_MOVER" else calc.DEHU_DAY_RATE_CENTS
        final_equipment_cents += rate * p["billable_days"]

    final_total_cents = scope_lines_total_cents + final_equipment_cents
    billing_variance_cents = final_total_cents - approved_total

    return success({
        "scope_lines_total_cents": scope_lines_total_cents,
        "final_equipment_cents": final_equipment_cents,
        "final_total_cents": final_total_cents,
        "billing_variance_cents": billing_variance_cents,
    }, status=200, response_type="object")


@bp.route("/restoration/jobs/<job_id>/drying-progress", methods=["GET"])
def drying_progress(job_id):
    auth(["Technician", "Dispatcher", "Adjuster", "PlatformAdmin"])
    job = get_or_404(db.jobs, job_id)
    mode = request.args.get("mode", "INSTANT")
    if mode not in ("INSTANT", "TRAILING"):
        raise err("ERR_INVALID_REQUEST", "mode must be INSTANT or TRAILING.")

    chambers = domain.job_chambers(job_id)

    def readings_asc(chamber_id):
        rs = domain.chamber_readings(chamber_id)
        return sorted(rs, key=lambda r: (r["created_at"], r["_seq"]))

    # job reference gpp: newest reading on the UNAFFECTED-REF chamber.
    reference_gpp = None
    ref_chamber = next((c for c in chambers if c["room_label"] == "UNAFFECTED-REF"), None)
    if ref_chamber is not None:
        rs = readings_asc(ref_chamber["id"])
        if rs:
            reference_gpp = rs[-1]["gpp"]

    def chamber_gpp(chamber_id):
        rs = readings_asc(chamber_id)
        if not rs:
            return None
        if mode == "TRAILING":
            newest_two = rs[-2:]
            mean = sum(r["gpp"] for r in newest_two) / len(newest_two)
            return calc.round_half_up_int(mean)
        return rs[-1]["gpp"]

    per_chamber = []
    for c in sorted(chambers, key=lambda x: (x["created_at"], x["_seq"])):
        if c["room_label"] == "UNAFFECTED-REF":
            continue
        rs = readings_asc(c["id"])
        progress = None
        if reference_gpp is not None and rs:
            initial_gpp = rs[0]["gpp"]
            initial_diff = initial_gpp - reference_gpp
            current_diff = chamber_gpp(c["id"]) - reference_gpp
            if initial_diff != 0:
                progress = float(calc.round_half_up(
                    (initial_diff - current_diff) / initial_diff * 100, 2))
        per_chamber.append({
            "chamber_id": c["id"],
            "room_label": c["room_label"],
            "progress_pct": progress,
        })

    return success({
        "per_chamber": per_chamber,
        "job_reference_gpp": reference_gpp,
    }, status=200, response_type="object")


@bp.route("/restoration/jobs/<job_id>/contents/value", methods=["POST"])
def contents_value(job_id):
    auth(["Adjuster", "Technician"])
    job = get_or_404(db.jobs, job_id)
    claim = db.claims.get(job["claim_id"])

    claim_limit_cents = 0
    if claim is not None:
        claim_limit_cents = max(0, claim["coverage_limit_cents"] - claim["deductible_cents"])

    # included items: PACKED_OUT or STORED, ordered created_at ASC.
    included = [c for c in domain.job_contents(job_id)
                if c["status"] in ("PACKED_OUT", "STORED")]
    included = sorted(included, key=lambda x: (x["created_at"], x["_seq"]))

    allocated_total = calc.waterfall_allocate(included, claim_limit_cents)
    for item in included:
        touch(item)

    items_out = [{
        "id": c["id"],
        "declared_value_cents": c["declared_value_cents"],
        "allocated_value_cents": c["allocated_value_cents"],
        "status": c["status"],
    } for c in included]

    return success({
        "allocated_total_cents": allocated_total,
        "claim_limit_cents": claim_limit_cents,
        "items": items_out,
    }, status=200, response_type="object")

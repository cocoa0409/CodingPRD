"""CleaningJob lifecycle and ServiceWindow calendar (PRD §3.3, §3.4, §3.8)."""

from datetime import timedelta

from flask import Blueprint

from core import (
    db, ApiError, auth, require_role, body_json, need, req_int, req_str, req_dt,
    as_int, as_bool, get_or_404, create_entity, touch, ser, ok, paginate,
    sorted_all, apply_filters, forbid, now,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_TANK_NOT_IN_SERVICE, ERR_CONTRACTOR_NOT_QUALIFIED,
    ERR_INCOMPATIBLE_CHANGEOVER, ERR_WINDOW_UNAVAILABLE, ERR_WINDOW_OVERLAP,
    ERR_WINDOW_BUFFER, ERR_WINDOW_NOT_ACTIVE, ERR_WINDOW_LINKED,
    ERR_WASTE_PROFILE_NOT_APPROVED, ERR_NO_DELIVERED_SHIPMENT,
    ERR_NO_VALID_ENTRY_PERMIT, ERR_PERMITS_NOT_CLOSED, ERR_JOB_HAS_ACTIVE_PERMIT,
    ERR_NO_REWORKABLE_FINDINGS, ERR_CRITICAL_FINDINGS_OPEN,
    ERR_FLUSH_VOLUME_INSUFFICIENT, ERR_MASS_BALANCE, ERR_NO_VALID_CERT,
)
import calc
from services import (
    contractor_score, recompute_shipped_solids, accepted_inspection,
    findings_of,
)

bp = Blueprint("jobs", __name__)


def _own_job(uid, job):
    """Entity-backed ownership: ContractorSupervisor's X-User-ID is the
    Contractor id referenced by the job."""
    if job["contractor_id"] != uid:
        forbid("acting ContractorSupervisor does not own this job")


# --------------------------------------------------------- cleaning jobs ---


@bp.post("/cleaning-jobs")
def create_job():
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    b = body_json()
    terminal_id = req_str(b, "terminal_id")
    tank_id = req_str(b, "tank_id")
    contractor_id = req_str(b, "contractor_id")
    from_product_id = req_str(b, "from_product_id")
    to_product_id = req_str(b, "to_product_id")
    sounding = req_int(b, "heel_volume_liters_sounding")
    base_fee = req_int(b, "base_service_fee_cents")
    lines_included = b.get("lines_included", False)
    if not isinstance(lines_included, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "lines_included must be a boolean")
    if sounding < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "heel_volume_liters_sounding must be >= 0")
    if base_fee < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "base_service_fee_cents must be >= 0")
    terminal = get_or_404(db.terminals, terminal_id, "terminal")
    tank = get_or_404(db.tanks, tank_id, "tank")
    get_or_404(db.contractors, contractor_id, "contractor")
    from_product = get_or_404(db.products, from_product_id, "product")
    get_or_404(db.products, to_product_id, "product")
    if terminal_id != tank["terminal_id"]:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "terminal_id does not own the named tank")
    if tank["status"] != "IN_SERVICE":
        raise ApiError(ERR_TANK_NOT_IN_SERVICE, 409,
                       "tank is not IN_SERVICE")
    changeover = calc.changeover_class(from_product,
                                       db.products[to_product_id])
    flush_volume = calc.flush_volume_liters(tank, from_product, changeover,
                                            lines_included)
    job = create_entity({
        "terminal_id": terminal_id,
        "tank_id": tank_id,
        "contractor_id": contractor_id,
        "from_product_id": from_product_id,
        "to_product_id": to_product_id,
        "lines_included": lines_included,
        "heel_volume_liters_sounding": sounding,
        "heel_volume_liters_metered": None,
        "residual_sludge_kg": 0,
        "base_service_fee_cents": base_fee,
        "changeover_class": changeover,
        "sludge_estimate_provisional_kg": calc.sludge_mass_kg(
            sounding, from_product, tank),
        "expected_solids_kg": None,
        "shipped_solids_kg": 0,
        "flush_volume_liters": flush_volume,
        "waste_cost_cents": 0,
        "invoice_total_cents": None,
        "window_id": None,
        "status": "DRAFT",
        "paused_from": None,
        "pause_reason": None,
    })
    db.cleaning_jobs[job["id"]] = job
    return ok(ser(job), 201)


@bp.get("/cleaning-jobs/<jobId>")
def get_job(jobId):
    auth()
    return ok(ser(get_or_404(db.cleaning_jobs, jobId, "cleaning job")), 200)


@bp.get("/cleaning-jobs")
def list_jobs():
    auth()
    items = apply_filters(sorted_all(db.cleaning_jobs), [
        ("terminal_id", "terminal_id"),
        ("tank_id", "tank_id"),
        ("contractor_id", "contractor_id"),
        ("from_product_id", "from_product_id"),
        ("to_product_id", "to_product_id"),
        ("window_id", "window_id"),
        ("status", "status"),
    ])
    page, pg = paginate(items)
    return ok([ser(e) for e in page], 200, pg)


@bp.patch("/cleaning-jobs/<jobId>")
def patch_job(jobId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    job = get_or_404(db.cleaning_jobs, jobId, "cleaning job")
    b = body_json()
    expected = req_int(b, "expected_job_version")
    if "base_service_fee_cents" in b and b["base_service_fee_cents"] is not None:
        fee = as_int(b["base_service_fee_cents"], "base_service_fee_cents")
        if fee < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "base_service_fee_cents must be >= 0")
    if "lines_included" in b and b["lines_included"] is not None:
        as_bool(b["lines_included"], "lines_included")
    if expected != job["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_job_version does not match the job version")
    if job["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a DRAFT job can be patched")
    if "base_service_fee_cents" in b and b["base_service_fee_cents"] is not None:
        job["base_service_fee_cents"] = as_int(b["base_service_fee_cents"],
                                               "base_service_fee_cents")
    if "lines_included" in b and b["lines_included"] is not None:
        new_lines = as_bool(b["lines_included"], "lines_included")
        if new_lines != job["lines_included"]:
            job["lines_included"] = new_lines
            tank = db.tanks[job["tank_id"]]
            from_product = db.products[job["from_product_id"]]
            job["flush_volume_liters"] = calc.flush_volume_liters(
                tank, from_product, job["changeover_class"], new_lines)
    touch(job)
    return ok(ser(job), 200)


@bp.post("/cleaning-jobs/<jobId>/schedule")
def schedule_job(jobId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    job = get_or_404(db.cleaning_jobs, jobId, "cleaning job")
    b = body_json()
    window_id = req_str(b, "window_id")
    window = get_or_404(db.service_windows, window_id, "service window")
    if job["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "job is not in DRAFT")
    # PRD §3.4 normative order: contractor standing -> changeover -> window.
    contractor = db.contractors[job["contractor_id"]]
    terminal = db.terminals[job["terminal_id"]]
    score = contractor_score(contractor["id"], terminal["score_variant"])
    if contractor["status"] != "QUALIFIED" or \
            score < calc.Decimal(str(terminal["safety_score_threshold"])):
        raise ApiError(ERR_CONTRACTOR_NOT_QUALIFIED, 409,
                       "contractor is not QUALIFIED or below the terminal threshold")
    if job["changeover_class"] == "FORBIDDEN":
        raise ApiError(ERR_INCOMPATIBLE_CHANGEOVER, 422,
                       "changeover class is FORBIDDEN")
    if (window["status"] != "PLANNED" or window["tank_id"] != job["tank_id"]
            or window["job_id"] is not None):
        raise ApiError(ERR_WINDOW_UNAVAILABLE, 409,
                       "window is not linkable to this job")
    job["status"] = "SCHEDULED"
    job["window_id"] = window["id"]
    touch(job)
    window["job_id"] = job["id"]
    touch(window)
    return ok(ser(job), 200)


@bp.post("/cleaning-jobs/<jobId>/take-out-of-service")
def take_out_of_service(jobId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    job = get_or_404(db.cleaning_jobs, jobId, "cleaning job")
    if job["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "job is not SCHEDULED")
    window = db.service_windows.get(job["window_id"])
    if window is None or window["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "linked window is not ACTIVE")
    tank = db.tanks[job["tank_id"]]
    if tank["status"] != "IN_SERVICE":
        raise ApiError(ERR_TANK_NOT_IN_SERVICE, 409, "tank is not IN_SERVICE")
    tank["status"] = "OUT_OF_SERVICE"
    touch(tank)
    job["status"] = "TANK_OOS"
    touch(job)
    return ok(ser(job), 200)


@bp.post("/cleaning-jobs/<jobId>/record-heel-removal")
def record_heel_removal(jobId):
    uid, role = auth()
    require_role(role, {"ContractorSupervisor"})
    job = get_or_404(db.cleaning_jobs, jobId, "cleaning job")
    _own_job(uid, job)
    b = body_json()
    metered = req_int(b, "metered_liters")
    if job["status"] != "TANK_OOS":
        raise ApiError(ERR_INVALID_STATE, 409, "job is not TANK_OOS")
    if metered < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "metered_liters must be >= 0")
    tank = db.tanks[job["tank_id"]]
    from_product = db.products[job["from_product_id"]]
    job["heel_volume_liters_metered"] = metered
    job["expected_solids_kg"] = calc.sludge_mass_kg(metered, from_product, tank)
    job["status"] = "HEEL_REMOVED"
    touch(job)
    return ok(ser(job), 200)


@bp.post("/cleaning-jobs/<jobId>/record-sludge-removal")
def record_sludge_removal(jobId):
    uid, role = auth()
    require_role(role, {"ContractorSupervisor"})
    job = get_or_404(db.cleaning_jobs, jobId, "cleaning job")
    _own_job(uid, job)
    b = body_json()
    residual = req_int(b, "residual_sludge_kg")
    if job["status"] not in ("HEEL_REMOVED", "REWORK_CLEANING"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "job is not in a state allowing sludge removal")
    # PRD §3.5 normative order: approved profile -> delivered shipment ->
    # residual non-negative.
    if not any(p["job_id"] == job["id"] and p["status"] == "APPROVED"
               for p in db.waste_profiles.values()):
        raise ApiError(ERR_WASTE_PROFILE_NOT_APPROVED, 409,
                       "no APPROVED waste profile exists for the job")
    if not any(s["job_id"] == job["id"]
               and s["status"] in ("DELIVERED", "RECONCILED")
               for s in db.waste_shipments.values()):
        raise ApiError(ERR_NO_DELIVERED_SHIPMENT, 409,
                       "no DELIVERED/RECONCILED shipment exists for the job")
    if residual < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "residual_sludge_kg must be >= 0")
    # One mutation, one version bump: residual recorded, status moved, and
    # shipped_solids_kg recomputed as part of the same transition.
    job["residual_sludge_kg"] = residual
    job["status"] = "SLUDGE_REMOVED"
    job["shipped_solids_kg"] = residual + sum(
        s["manifested_kg"] for s in db.waste_shipments.values()
        if s["job_id"] == job["id"] and s["status"] in ("DELIVERED", "RECONCILED"))
    touch(job)
    return ok(ser(job), 200)


@bp.post("/cleaning-jobs/<jobId>/request-gas-free")
def request_gas_free(jobId):
    uid, role = auth()
    require_role(role, {"ContractorSupervisor"})
    job = get_or_404(db.cleaning_jobs, jobId, "cleaning job")
    _own_job(uid, job)
    if job["status"] == "SLUDGE_REMOVED":
        job["status"] = "GAS_FREE_PENDING"
    elif job["status"] == "PAUSED":
        # Recovery edge: only when no VALID certificate exists for the job.
        if any(c["job_id"] == job["id"] and c["status"] == "VALID"
               for c in db.gas_free_certs.values()):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "a VALID certificate already exists for the job")
        job["paused_from"] = None
        job["pause_reason"] = None
        job["status"] = "GAS_FREE_PENDING"
    else:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "job cannot request gas-free from its current state")
    touch(job)
    return ok(ser(job), 200)


@bp.post("/cleaning-jobs/<jobId>/begin-entry")
def begin_entry(jobId):
    uid, role = auth()
    require_role(role, {"ContractorSupervisor"})
    job = get_or_404(db.cleaning_jobs, jobId, "cleaning job")
    _own_job(uid, job)
    if job["status"] != "GAS_FREE_CERTIFIED":
        raise ApiError(ERR_INVALID_STATE, 409, "job is not GAS_FREE_CERTIFIED")
    if not any(p["job_id"] == job["id"] and p["status"] == "ACTIVE"
               and p["atmosphere"] == "CLEAR"
               for p in db.entry_permits.values()):
        raise ApiError(ERR_NO_VALID_ENTRY_PERMIT, 409,
                       "no ACTIVE permit with CLEAR atmosphere exists")
    job["status"] = "ENTRY_IN_PROGRESS"
    touch(job)
    return ok(ser(job), 200)


@bp.post("/cleaning-jobs/<jobId>/complete-entry")
def complete_entry(jobId):
    uid, role = auth()
    require_role(role, {"ContractorSupervisor"})
    job = get_or_404(db.cleaning_jobs, jobId, "cleaning job")
    _own_job(uid, job)
    if job["status"] != "ENTRY_IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "job is not ENTRY_IN_PROGRESS")
    if any(p["job_id"] == job["id"] and p["status"] not in ("CLOSED", "VOIDED")
           for p in db.entry_permits.values()):
        raise ApiError(ERR_PERMITS_NOT_CLOSED, 409,
                       "all permits must be CLOSED or VOIDED")
    job["status"] = "ENTRY_COMPLETE"
    touch(job)
    return ok(ser(job), 200)


@bp.post("/cleaning-jobs/<jobId>/order-rework")
def order_rework(jobId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    job = get_or_404(db.cleaning_jobs, jobId, "cleaning job")
    if job["status"] != "INSPECTION_ACCEPTED":
        raise ApiError(ERR_INVALID_STATE, 409, "job is not INSPECTION_ACCEPTED")
    insp = accepted_inspection(job["id"])
    reworkable = False
    if insp is not None:
        reworkable = any(f["status"] in ("OPEN", "REPAIR_ORDERED")
                         for f in findings_of(insp["id"]))
    if not reworkable:
        raise ApiError(ERR_NO_REWORKABLE_FINDINGS, 409,
                       "no OPEN/REPAIR_ORDERED finding on the accepted inspection")
    for cert in db.gas_free_certs.values():
        if cert["job_id"] == job["id"] and cert["status"] == "VALID":
            cert["status"] = "SUPERSEDED"
            touch(cert)
    for p in db.entry_permits.values():
        if p["job_id"] == job["id"] \
                and p["status"] in ("REQUESTED", "ISSUED", "SUSPENDED"):
            p["status"] = "VOIDED"
            touch(p)
    job["status"] = "REWORK_CLEANING"
    touch(job)
    return ok(ser(job), 200)


@bp.post("/cleaning-jobs/<jobId>/begin-flush")
def begin_flush(jobId):
    uid, role = auth()
    require_role(role, {"ContractorSupervisor"})
    job = get_or_404(db.cleaning_jobs, jobId, "cleaning job")
    _own_job(uid, job)
    if job["status"] != "INSPECTION_ACCEPTED":
        raise ApiError(ERR_INVALID_STATE, 409, "job is not INSPECTION_ACCEPTED")
    insp = accepted_inspection(job["id"])
    if insp is not None and any(
            f["severity"] == "CRITICAL" and f["status"] in ("OPEN", "REPAIR_ORDERED")
            for f in findings_of(insp["id"])):
        raise ApiError(ERR_CRITICAL_FINDINGS_OPEN, 409,
                       "CRITICAL findings remain open on the accepted inspection")
    job["status"] = "FLUSH_IN_PROGRESS"
    touch(job)
    return ok(ser(job), 200)


@bp.post("/cleaning-jobs/<jobId>/verify-flush")
def verify_flush(jobId):
    uid, role = auth()
    require_role(role, {"EHSOfficer"})
    job = get_or_404(db.cleaning_jobs, jobId, "cleaning job")
    b = body_json()
    actual = req_int(b, "actual_flush_liters")
    if job["status"] != "FLUSH_IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "job is not FLUSH_IN_PROGRESS")
    # Inclusive boundary: exactly equal to the requirement verifies.
    if actual < (job["flush_volume_liters"] or 0):
        raise ApiError(ERR_FLUSH_VOLUME_INSUFFICIENT, 409,
                       "actual flush liters below the computed requirement")
    job["status"] = "FLUSH_VERIFIED"
    touch(job)
    return ok(ser(job), 200)


@bp.post("/cleaning-jobs/<jobId>/request-rts")
def request_rts(jobId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    job = get_or_404(db.cleaning_jobs, jobId, "cleaning job")
    if job["status"] != "FLUSH_VERIFIED":
        raise ApiError(ERR_INVALID_STATE, 409, "job is not FLUSH_VERIFIED")
    terminal = db.terminals[job["terminal_id"]]
    if not calc.mass_balance_passes(job, terminal):
        raise ApiError(ERR_MASS_BALANCE, 409,
                       "shipped solids are outside the terminal tolerance")
    job["invoice_total_cents"] = calc.invoice_total_cents(job)
    job["status"] = "RTS_PENDING"
    touch(job)
    return ok(ser(job), 200)


@bp.post("/cleaning-jobs/<jobId>/return-to-service")
def return_to_service(jobId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    job = get_or_404(db.cleaning_jobs, jobId, "cleaning job")
    if job["status"] != "RTS_PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "job is not RTS_PENDING")
    # PRD §3.8: critical-findings rule first, then mass balance, at call time.
    insp = accepted_inspection(job["id"])
    if insp is not None and any(
            f["severity"] == "CRITICAL" and f["status"] in ("OPEN", "REPAIR_ORDERED")
            for f in findings_of(insp["id"])):
        raise ApiError(ERR_CRITICAL_FINDINGS_OPEN, 409,
                       "CRITICAL findings remain open on the accepted inspection")
    terminal = db.terminals[job["terminal_id"]]
    if not calc.mass_balance_passes(job, terminal):
        raise ApiError(ERR_MASS_BALANCE, 409,
                       "shipped solids are outside the terminal tolerance")
    tank = db.tanks[job["tank_id"]]
    tank["status"] = "IN_SERVICE"
    tank["current_product_id"] = job["to_product_id"]
    touch(tank)
    window = db.service_windows.get(job["window_id"])
    if window is not None:
        window["status"] = "COMPLETED"
        touch(window)
    job["status"] = "RETURNED_TO_SERVICE"
    touch(job)
    return ok(ser(job), 200)


@bp.post("/cleaning-jobs/<jobId>/resume")
def resume_job(jobId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    job = get_or_404(db.cleaning_jobs, jobId, "cleaning job")
    if job["status"] != "PAUSED":
        raise ApiError(ERR_INVALID_STATE, 409, "job is not PAUSED")
    target = job["paused_from"]
    has_valid_cert = any(c["job_id"] == job["id"] and c["status"] == "VALID"
                         for c in db.gas_free_certs.values())
    if target in ("GAS_FREE_CERTIFIED", "ENTRY_COMPLETE"):
        if not has_valid_cert:
            raise ApiError(ERR_NO_VALID_CERT, 409,
                           "no VALID certificate exists for the job")
    elif target == "ENTRY_IN_PROGRESS":
        if not has_valid_cert:
            raise ApiError(ERR_NO_VALID_CERT, 409,
                           "no VALID certificate exists for the job")
        if not any(p["job_id"] == job["id"] and p["status"] == "ACTIVE"
                   and p["atmosphere"] == "CLEAR"
                   for p in db.entry_permits.values()):
            raise ApiError(ERR_NO_VALID_ENTRY_PERMIT, 409,
                           "no ACTIVE permit with CLEAR atmosphere exists")
    else:
        raise ApiError(ERR_INVALID_STATE, 409, "job has no resumable state")
    job["status"] = target
    job["paused_from"] = None
    job["pause_reason"] = None
    touch(job)
    return ok(ser(job), 200)


@bp.post("/cleaning-jobs/<jobId>/cancel")
def cancel_job(jobId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    job = get_or_404(db.cleaning_jobs, jobId, "cleaning job")
    allowed = ("DRAFT", "SCHEDULED", "TANK_OOS", "HEEL_REMOVED",
               "SLUDGE_REMOVED", "GAS_FREE_PENDING", "GAS_FREE_CERTIFIED",
               "PAUSED")
    if job["status"] not in allowed:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "job cannot be cancelled from its current state")
    if job["status"] in ("GAS_FREE_CERTIFIED", "PAUSED"):
        if any(p["job_id"] == job["id"] and p["status"] == "ACTIVE"
               for p in db.entry_permits.values()):
            raise ApiError(ERR_JOB_HAS_ACTIVE_PERMIT, 409,
                           "job holds an ACTIVE entry permit")
        for p in db.entry_permits.values():
            if p["job_id"] == job["id"] \
                    and p["status"] in ("REQUESTED", "ISSUED", "SUSPENDED"):
                p["status"] = "VOIDED"
                touch(p)
    window = db.service_windows.get(job["window_id"]) if job["window_id"] else None
    if job["status"] == "SCHEDULED":
        if window is not None:
            window["job_id"] = None  # window stays PLANNED
            touch(window)
    elif job["status"] != "DRAFT":
        tank = db.tanks[job["tank_id"]]
        tank["status"] = "IN_SERVICE"
        touch(tank)
        if window is not None:
            window["status"] = "CANCELLED"
            touch(window)
    job["status"] = "CANCELLED"
    touch(job)
    return ok(ser(job), 200)


# -------------------------------------------------------- service windows ---

_BUFFER = timedelta(hours=calc.BUFFER_HOURS)


@bp.post("/service-windows")
def create_window():
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    b = body_json()
    tank_id = req_str(b, "tank_id")
    planned_start = req_dt(b, "planned_start")
    planned_end = req_dt(b, "planned_end")
    expected = req_int(b, "expected_tank_version")
    if not planned_start < planned_end:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "planned_start must be strictly before planned_end")
    tank = get_or_404(db.tanks, tank_id, "tank")
    if expected != tank["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_tank_version does not match the tank version")
    existing = [w for w in db.service_windows.values()
                if w["tank_id"] == tank_id and w["status"] in ("PLANNED", "ACTIVE")]
    # Overlap is reported before buffer violation (PRD §2.8).
    for w in existing:
        if planned_start < w["planned_end"] and w["planned_start"] < planned_end:
            raise ApiError(ERR_WINDOW_OVERLAP, 409,
                           "window intersects an existing window on the tank")
    for w in existing:
        if (planned_start < w["planned_end"] + _BUFFER
                and planned_end > w["planned_end"]):
            raise ApiError(ERR_WINDOW_BUFFER, 409,
                           "window violates the 24h buffer after an existing window")
        if (w["planned_start"] < planned_end + _BUFFER
                and w["planned_end"] > planned_end):
            raise ApiError(ERR_WINDOW_BUFFER, 409,
                           "window violates the 24h buffer before an existing window")
    w = create_entity({
        "tank_id": tank_id,
        "job_id": None,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "status": "PLANNED",
    })
    db.service_windows[w["id"]] = w
    touch(tank)  # booking advances the tank version by one
    return ok(ser(w), 201)


@bp.get("/service-windows/<windowId>")
def get_window(windowId):
    auth()
    return ok(ser(get_or_404(db.service_windows, windowId, "service window")), 200)


@bp.get("/service-windows")
def list_windows():
    auth()
    items = apply_filters(sorted_all(db.service_windows), [
        ("tank_id", "tank_id"),
        ("job_id", "job_id"),
        ("status", "status"),
    ])
    page, pg = paginate(items)
    return ok([ser(e) for e in page], 200, pg)


@bp.post("/service-windows/<windowId>/activate")
def activate_window(windowId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    w = get_or_404(db.service_windows, windowId, "service window")
    if w["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409, "window is not PLANNED")
    now_dt = now()
    if not (w["planned_start"] <= now_dt < w["planned_end"]):
        raise ApiError(ERR_WINDOW_NOT_ACTIVE, 409,
                       "window is not within its planned interval")
    w["status"] = "ACTIVE"
    touch(w)
    return ok(ser(w), 200)


@bp.post("/service-windows/<windowId>/complete")
def complete_window(windowId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    w = get_or_404(db.service_windows, windowId, "service window")
    if w["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "window is not ACTIVE")
    w["status"] = "COMPLETED"
    touch(w)
    return ok(ser(w), 200)


@bp.post("/service-windows/<windowId>/cancel")
def cancel_window(windowId):
    uid, role = auth()
    require_role(role, {"TerminalOperator"})
    w = get_or_404(db.service_windows, windowId, "service window")
    if w["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409, "window is not PLANNED")
    if w["job_id"] is not None:
        job = db.cleaning_jobs.get(w["job_id"])
        if job is not None and job["status"] != "CANCELLED":
            raise ApiError(ERR_WINDOW_LINKED, 409,
                           "window is linked to a non-cancelled job")
    w["status"] = "CANCELLED"
    touch(w)
    return ok(ser(w), 200)

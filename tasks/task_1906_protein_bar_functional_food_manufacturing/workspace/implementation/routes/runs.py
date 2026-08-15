"""Production runs, retain samples, and lot releases."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import serialize
from db import STORES, base_record, touch, CLOCK, new_run_number
from errors import (
    not_found, invalid_request, invalid_state, terminal_locked, unprocessable,
    stale_version,
    ERR_REVISION_NOT_FOUND, ERR_AGREEMENT_NOT_FOUND, ERR_LINE_NOT_FOUND,
    ERR_RUN_NOT_FOUND, ERR_RELEASE_NOT_FOUND,
    ERR_ALLERGEN_SEGREGATION_VIOLATION, ERR_REVISION_NOT_APPROVED,
    ERR_FORMULA_ARCHIVED, ERR_AGREEMENT_NOT_ACTIVE, ERR_CUSTOMER_SUSPENDED,
    ERR_MOQ_SHORTFALL, ERR_SCHEDULE_IN_PAST,
    ERR_SLOT_OVERLAP, ERR_SLOT_CHANGEOVER_BUFFER_VIOLATION,
    ERR_COMPOSITE_CLAIM_UNSUBSTANTIATED, ERR_CHANGEOVER_NOT_VALIDATED,
    ERR_INGREDIENT_SHORTAGE, ERR_OUTPUT_EXCEEDS_CUT_PLAN,
    ERR_RETAIN_PERIOD_TOO_SHORT, ERR_SOD_VIOLATION,
    ERR_RETAIN_SAMPLE_REQUIRED, ERR_YIELD_VARIANCE_EXCEEDED,
    ERR_QC_NOT_PASSED,
)
from middleware import require_roles, rep_owns_customer, run_customer_id
from response import ok_object, list_response
from services import calc
from services import inventory as inv
from util import (
    D, get_body, require, opt, check_str, check_int, check_number, check_enum,
    parse_dt,
)

bp = Blueprint("runs", __name__)

RUN_READ = ("PlantAdmin", "FormulationScientist", "QualityManager",
            "ProductionPlanner", "LabTechnician", "BrandCustomerRep")
RUN_STATUS = ["PLANNED", "SCHEDULED", "PRE_RUN_VERIFIED", "IN_PRODUCTION",
              "COMPLETED", "CANCELLED"]
RETAIN_STATUS = ["STORED"]
QC_DISPOSITIONS = ["PASSED", "FAILED"]
DECISIONS = ["RELEASED", "HOLD_REWORK", "SCRAPPED"]


def _sorted(name):
    return sorted(STORES[name].values(), key=lambda r: r["_seq"])


def _get_run(rid):
    rec = STORES["runs"].get(rid)
    if rec is None:
        raise not_found(ERR_RUN_NOT_FOUND, f"Production run {rid} does not exist")
    return rec


def _get_release(rid):
    rec = STORES["releases"].get(rid)
    if rec is None:
        raise not_found(ERR_RELEASE_NOT_FOUND, f"Lot release {rid} does not exist")
    return rec


# ---------------- run creation ----------------

@bp.post("/mfg/production-runs")
def create_run():
    require_roles("ProductionPlanner")
    body = get_body(request)
    # Stage 5: body FK existence, in field order
    revision = agreement = line = None
    rid = body.get("revision_id")
    if isinstance(rid, str):
        revision = STORES["revisions"].get(rid)
        if revision is None:
            raise not_found(ERR_REVISION_NOT_FOUND,
                            f"Revision {rid} does not exist")
    aid = body.get("agreement_id")
    if isinstance(aid, str):
        agreement = STORES["agreements"].get(aid)
        if agreement is None:
            raise not_found(ERR_AGREEMENT_NOT_FOUND,
                            f"Agreement {aid} does not exist")
    lid = body.get("line_id")
    if isinstance(lid, str):
        line = STORES["lines"].get(lid)
        if line is None:
            raise not_found(ERR_LINE_NOT_FOUND, f"Line {lid} does not exist")
    # Stage 6: shape
    if revision is None:
        raise invalid_request("Missing required field 'revision_id'")
    if agreement is None:
        raise invalid_request("Missing required field 'agreement_id'")
    if line is None:
        raise invalid_request("Missing required field 'line_id'")
    planned_cases = check_int(require(body, "planned_cases"), "planned_cases")
    if planned_cases <= 0:
        raise invalid_request("Field 'planned_cases' must be > 0")
    expected_version = check_int(require(body, "expected_agreement_version"),
                                 "expected_agreement_version")
    # Business gates, in the PRD §3.6 order
    if "GLUTEN_FREE" in (revision.get("claim_tags") or []) \
            and "WHEAT" in (line.get("current_allergen_profile") or []):
        raise unprocessable(
            ERR_ALLERGEN_SEGREGATION_VIOLATION,
            "GLUTEN_FREE-claimed revision cannot run on a line with WHEAT residue")
    if revision["status"] != "APPROVED":
        raise unprocessable(ERR_REVISION_NOT_APPROVED,
                            "Run create requires an APPROVED revision")
    formula = STORES["formulas"].get(revision["formula_id"])
    if formula is None or formula["status"] != "ACTIVE":
        raise unprocessable(ERR_FORMULA_ARCHIVED,
                            "Revision's formula is ARCHIVED")
    if agreement["status"] != "ACTIVE":
        raise unprocessable(ERR_AGREEMENT_NOT_ACTIVE,
                            "Run create requires an ACTIVE agreement")
    customer = STORES["customers"].get(agreement["customer_id"])
    if customer is None or customer["status"] != "ACTIVE":
        raise unprocessable(ERR_CUSTOMER_SUSPENDED,
                            "Agreement's customer is SUSPENDED")
    if planned_cases < int(agreement["moq_cases_per_run"]):
        raise unprocessable(ERR_MOQ_SHORTFALL,
                            "planned_cases below the agreement MOQ")
    if expected_version != int(agreement["version"]):
        raise stale_version()
    # Commit: mint the run and reserve ingredients FIFO
    rec = base_record()
    allocations = []
    ready = True
    for line_entry in revision["ingredient_lines"]:
        needed = inv.run_line_required_qty(line_entry)
        allocs, covered = inv.reserve_fifo(line_entry["ingredient_id"], needed)
        allocations.extend(allocs)
        if not covered:
            ready = False
    rec.update({
        "revision_id": revision["id"],
        "agreement_id": agreement["id"],
        "line_id": line["id"],
        "planned_cases": planned_cases,
        "batch_code": "BATCH-" + str(new_run_number()).zfill(4),
        "reserved_lot_allocations": allocations,
        "ingredient_readiness": "READY" if ready else "BLOCKED",
        "provisional_sweetener_required_kg":
            calc.sweetener_provisional_total(revision),
        "final_sweetener_required_kg": None,
        "produced_cases": None,
        "scrapped_cases": None,
        "completed_utc_dt": None,
        "cancel_reason": None,
        "status": "PLANNED",
        "release_status": "NOT_READY",
    })
    STORES["runs"][rec["id"]] = rec
    touch(agreement)  # committed-volume ledger debited
    return ok_object(serialize.run(rec), 201)


# ---------------- run reads ----------------

@bp.get("/mfg/production-runs")
def list_runs():
    uid, role = require_roles(*RUN_READ)
    items = _sorted("runs")
    if role == "BrandCustomerRep":
        items = [r for r in items if run_customer_id(r) == uid]
    f = request.args.get("revision_id")
    if f is not None:
        items = [r for r in items if r["revision_id"] == f]
    f = request.args.get("agreement_id")
    if f is not None:
        items = [r for r in items if r["agreement_id"] == f]
    f = request.args.get("line_id")
    if f is not None:
        items = [r for r in items if r["line_id"] == f]
    st = request.args.get("status")
    if st is not None:
        check_enum(st, "status", RUN_STATUS)
        items = [r for r in items if r["status"] == st]
    return list_response([serialize.run(r) for r in items])


@bp.get("/mfg/production-runs/<rid>")
def get_run(rid):
    uid, role = require_roles(*RUN_READ)
    rec = _get_run(rid)
    rep_owns_customer(uid, role, run_customer_id(rec))
    return ok_object(serialize.run(rec))


def _run_action(rid):
    rec = _get_run(rid)
    if rec["status"] == "CANCELLED":
        raise terminal_locked("Run is CANCELLED (terminal)")
    return rec


# ---------------- scheduling ----------------

def _confirmed_slots(line_id):
    return [s for s in STORES["slots"].values()
            if s["line_id"] == line_id and s["status"] == "CONFIRMED"]


def _previous_run(line_id, start_dt):
    """Previous run on the line: latest slot end_utc <= start among CONFIRMED
    /COMPLETED slots; tie broken by earliest run created_at. None if none."""
    candidates = []
    for slot in STORES["slots"].values():
        if slot["line_id"] != line_id or slot["status"] not in ("CONFIRMED",
                                                                "COMPLETED"):
            continue
        if slot["end_utc_dt"] <= start_dt:
            candidates.append(slot)
    if not candidates:
        return None
    best_end = max(s["end_utc_dt"] for s in candidates)
    tied = [s for s in candidates if s["end_utc_dt"] == best_end]
    tied.sort(key=lambda s: STORES["runs"][s["run_id"]]["_seq"]
              if s["run_id"] in STORES["runs"] else s["_seq"])
    return STORES["runs"].get(tied[0]["run_id"])


@bp.post("/mfg/production-runs/<rid>/schedule")
def schedule_run(rid):
    require_roles("ProductionPlanner")
    run = _get_run(rid)
    body = get_body(request)
    # Stage 6 shape
    start_dt = parse_dt(require(body, "start_utc"), "start_utc")
    end_dt = parse_dt(require(body, "end_utc"), "end_utc")
    if not end_dt > start_dt:
        raise invalid_request("Field 'end_utc' must be later than 'start_utc'")
    expected_line_version = check_int(require(body, "expected_line_version"),
                                      "expected_line_version")
    # Stage 8/9: terminal lock, then state legality
    if run["status"] == "CANCELLED":
        raise terminal_locked("Run is CANCELLED (terminal)")
    if run["status"] != "PLANNED":
        raise invalid_state("Only a PLANNED run can be scheduled")
    line = STORES["lines"].get(run["line_id"])
    # Compute the changeover level for this run (drives slot buffer)
    prev_run = _previous_run(line["id"], start_dt)
    from_profile = []
    if prev_run is not None:
        prev_revision = STORES["revisions"].get(prev_run["revision_id"])
        if prev_revision is not None:
            from_profile = prev_revision.get("allergen_profile") or []
    revision = STORES["revisions"].get(run["revision_id"])
    to_profile = revision.get("allergen_profile") or []
    if line.get("last_wet_clean_utc_dt") is None:
        minutes_since_wet = None
    else:
        minutes_since_wet = (CLOCK.current
                             - line["last_wet_clean_utc_dt"]).total_seconds() / 60
    level = calc.changeover_level(from_profile, to_profile, minutes_since_wet)
    buffer_minutes = calc.BUFFER_MINUTES[level]
    # Business checks in order: past, overlap, buffer gap, OCC
    if start_dt < CLOCK.current:
        raise unprocessable(ERR_SCHEDULE_IN_PAST,
                            "Slot start_utc is earlier than the logical clock")
    confirmed = _confirmed_slots(line["id"])
    for slot in confirmed:
        if start_dt < slot["end_utc_dt"] and slot["start_utc_dt"] < end_dt:
            raise unprocessable(
                ERR_SLOT_OVERLAP,
                "Slot interval intersects a CONFIRMED slot on this line", 409)
    prev_slots = [s for s in confirmed if s["end_utc_dt"] <= start_dt]
    next_slots = [s for s in confirmed if s["start_utc_dt"] >= end_dt]
    if prev_slots:
        nearest_end = max(s["end_utc_dt"] for s in prev_slots)
        gap_min = (start_dt - nearest_end).total_seconds() / 60
        if gap_min < buffer_minutes:
            raise unprocessable(
                ERR_SLOT_CHANGEOVER_BUFFER_VIOLATION,
                "Gap to the preceding CONFIRMED slot is below the changeover buffer",
                409)
    if next_slots:
        nearest_start = min(s["start_utc_dt"] for s in next_slots)
        gap_min = (nearest_start - end_dt).total_seconds() / 60
        if gap_min < buffer_minutes:
            raise unprocessable(
                ERR_SLOT_CHANGEOVER_BUFFER_VIOLATION,
                "Gap to the following CONFIRMED slot is below the changeover buffer",
                409)
    if expected_line_version != int(line["version"]):
        raise stale_version()
    # Commit: slot + changeover + status
    slot = base_record()
    slot.update({
        "line_id": line["id"],
        "run_id": run["id"],
        "start_utc_dt": start_dt,
        "end_utc_dt": end_dt,
        "buffer_minutes": buffer_minutes,
        "status": "CONFIRMED",
    })
    STORES["slots"][slot["id"]] = slot
    event = base_record()
    event.update({
        "line_id": line["id"],
        "from_run_id": prev_run["id"] if prev_run is not None else None,
        "to_run_id": run["id"],
        "required_level": level,
        "swab_allergen_ppm": None,
        "swab_recorded_by": None,
        "validated_by": None,
        "status": "VALIDATED" if level == "NONE" else "PENDING",
    })
    STORES["changeovers"][event["id"]] = event
    run["status"] = "SCHEDULED"
    touch(line)
    touch(run)
    return ok_object(serialize.run(run))


# ---------------- pre-run verification ----------------

@bp.post("/mfg/production-runs/<rid>/verify-pre-run")
def verify_pre_run(rid):
    require_roles("QualityManager")
    run = _get_run(rid)
    if run["status"] == "CANCELLED":
        raise terminal_locked("Run is CANCELLED (terminal)")
    if run["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED run can be pre-run verified")
    revision = STORES["revisions"].get(run["revision_id"])
    formula = STORES["formulas"].get(revision["formula_id"])
    # Gate 1: COMPOSITE substantiation
    composite = calc.composite_protein_per_serving(revision, formula, run)
    if composite == "SHORTAGE":
        raise unprocessable(
            ERR_INGREDIENT_SHORTAGE,
            "A protein-contributing line has zero reserved kilograms")
    if not calc.nutrient_claims_satisfied(revision, composite):
        raise unprocessable(
            ERR_COMPOSITE_CLAIM_UNSUBSTANTIATED,
            "COMPOSITE-variant substantiation fails a NUTRIENT_CONTENT claim")
    # Gate 2: changeover validated
    event = inv.active_changeover_to_run(run["id"])
    if event is None or event["status"] != "VALIDATED":
        raise unprocessable(ERR_CHANGEOVER_NOT_VALIDATED,
                            "The run's changeover event is not VALIDATED")
    # Gate 3: readiness + sweetener top-up
    if run["ingredient_readiness"] != "READY":
        raise unprocessable(ERR_INGREDIENT_SHORTAGE,
                            "Run ingredient readiness is BLOCKED")
    sweetener_lines = [l for l in revision["ingredient_lines"]
                       if STORES["ingredients"][l["ingredient_id"]]["category"]
                       == "SWEETENER"]
    final_per_line = []
    for line_entry in sweetener_lines:
        value = calc.sweetener_final_line(line_entry, run)
        if value == "SHORTAGE":
            raise unprocessable(
                ERR_INGREDIENT_SHORTAGE,
                "A sweetener line has zero reserved kilograms")
        final_per_line.append((line_entry, value))
    # Simulate top-ups against a shared pending pool for atomicity
    pending = {}   # lot_id -> Decimal extra reservation
    topup_allocs = []
    for line_entry, final_kg in final_per_line:
        reserved = sum((D(a["qty_kg"]) for a in run["reserved_lot_allocations"]
                        if a["ingredient_id"] == line_entry["ingredient_id"]),
                       Decimal("0"))
        delta = final_kg - reserved
        if delta <= 0:
            continue
        remaining = delta
        for lot in inv.released_lots_fifo(line_entry["ingredient_id"]):
            if remaining <= 0:
                break
            avail = inv.lot_available(lot) - pending.get(lot["id"], Decimal("0"))
            if avail <= 0:
                continue
            take = min(avail, remaining)
            pending[lot["id"]] = pending.get(lot["id"], Decimal("0")) + take
            topup_allocs.append({"lot_id": lot["id"],
                                 "ingredient_id": line_entry["ingredient_id"],
                                 "qty_kg": take})
            remaining -= take
        if remaining > 0:
            raise unprocessable(
                ERR_INGREDIENT_SHORTAGE,
                "Insufficient RELEASED quantity for the sweetener top-up")
    # Commit
    for lot_id, extra in pending.items():
        lot = STORES["lots"][lot_id]
        lot["reserved_qty_kg"] = D(lot["reserved_qty_kg"]) + extra
        touch(lot)
    run["reserved_lot_allocations"].extend(topup_allocs)
    revision["composite_protein_g_per_serving"] = composite
    touch(revision)
    run["final_sweetener_required_kg"] = calc.round2(
        sum((v for _l, v in final_per_line), Decimal("0")))
    run["status"] = "PRE_RUN_VERIFIED"
    touch(run)
    return ok_object(serialize.run(run))


# ---------------- start / complete / cancel ----------------

@bp.post("/mfg/production-runs/<rid>/start")
def start_run(rid):
    require_roles("ProductionPlanner")
    run = _run_action(rid)
    if run["status"] != "PRE_RUN_VERIFIED":
        raise invalid_state("Only a PRE_RUN_VERIFIED run can start production")
    revision = STORES["revisions"].get(run["revision_id"])
    line = STORES["lines"].get(run["line_id"])
    inv.consume_run_reservations(run)
    if line is not None:
        line["current_allergen_profile"] = list(
            revision.get("allergen_profile") or [])
        touch(line)
    run["status"] = "IN_PRODUCTION"
    touch(run)
    return ok_object(serialize.run(run))


@bp.post("/mfg/production-runs/<rid>/complete")
def complete_run(rid):
    require_roles("ProductionPlanner")
    run = _get_run(rid)
    body = get_body(request)
    produced = check_int(require(body, "produced_cases"), "produced_cases")
    if produced < 0:
        raise invalid_request("Field 'produced_cases' must be >= 0")
    scrapped = check_int(require(body, "scrapped_cases"), "scrapped_cases")
    if scrapped < 0:
        raise invalid_request("Field 'scrapped_cases' must be >= 0")
    if run["status"] == "CANCELLED":
        raise terminal_locked("Run is CANCELLED (terminal)")
    if run["status"] != "IN_PRODUCTION":
        raise invalid_state("Only an IN_PRODUCTION run can be completed")
    revision = STORES["revisions"].get(run["revision_id"])
    formula = STORES["formulas"].get(revision["formula_id"])
    line = STORES["lines"].get(run["line_id"])
    expected = calc.cut_plan_cases(revision, line, formula)
    if produced > expected:
        raise unprocessable(
            ERR_OUTPUT_EXCEEDS_CUT_PLAN,
            "produced_cases exceeds the cut plan's expected_cases")
    run["produced_cases"] = produced
    run["scrapped_cases"] = scrapped
    run["release_status"] = "PENDING_QC"
    run["completed_utc_dt"] = CLOCK.current
    run["status"] = "COMPLETED"
    slot = inv.slot_for_run(run["id"])
    if slot is not None and slot["status"] == "CONFIRMED":
        slot["status"] = "COMPLETED"
        touch(slot)
    release = base_record()
    release.update({
        "run_id": run["id"],
        "expected_cases": expected,
        "yield_variance_pct": calc.yield_variance_pct(produced,
                                                      run["planned_cases"]),
        "qc_disposition": "PENDING",
        "qc_recorded_by": None,
        "decision": "PENDING",
        "decided_by": None,
        "retain_cases_stored": 0,
    })
    STORES["releases"][release["id"]] = release
    touch(run)
    return ok_object(serialize.run(run))


@bp.post("/mfg/production-runs/<rid>/cancel")
def cancel_run(rid):
    require_roles("ProductionPlanner")
    run = _run_action(rid)
    if run["status"] not in ("PLANNED", "SCHEDULED"):
        raise invalid_state("Only a PLANNED or SCHEDULED run can be cancelled")
    was_scheduled = run["status"] == "SCHEDULED"
    inv.release_run_reservations(run)
    if was_scheduled:
        slot = inv.slot_for_run(run["id"])
        if slot is not None and slot["status"] == "CONFIRMED":
            slot["status"] = "RELEASED"
            touch(slot)
        event = inv.active_changeover_to_run(run["id"])
        if event is not None:
            inv.system_cancel_changeover(event)
    run["status"] = "CANCELLED"
    run["cancel_reason"] = "OPERATOR_CANCEL"
    touch(run)
    return ok_object(serialize.run(run))


# ---------------- run-scoped reads ----------------

@bp.get("/mfg/production-runs/<rid>/slots")
def list_run_slots(rid):
    require_roles("PlantAdmin", "ProductionPlanner", "QualityManager")
    _get_run(rid)
    items = [s for s in _sorted("slots") if s["run_id"] == rid]
    return list_response([serialize.slot(s) for s in items])


@bp.get("/mfg/production-runs/<rid>/changeovers")
def list_run_changeovers(rid):
    require_roles("PlantAdmin", "ProductionPlanner", "QualityManager",
                  "LabTechnician")
    _get_run(rid)
    items = [c for c in _sorted("changeovers")
             if c.get("from_run_id") == rid or c.get("to_run_id") == rid]
    return list_response([serialize.changeover(c) for c in items])


@bp.get("/mfg/production-runs/<rid>/retain-samples")
def list_run_retains(rid):
    require_roles("PlantAdmin", "QualityManager", "LabTechnician")
    _get_run(rid)
    items = [s for s in _sorted("retains") if s["run_id"] == rid]
    st = request.args.get("status")
    if st is not None:
        check_enum(st, "status", RETAIN_STATUS)
        items = [s for s in items if s["status"] == st]
    return list_response([serialize.retain(s) for s in items])


@bp.get("/mfg/production-runs/<rid>/lot-release")
def get_run_release(rid):
    require_roles("PlantAdmin", "QualityManager", "LabTechnician")
    _get_run(rid)
    items = [r for r in _sorted("releases") if r["run_id"] == rid]
    return list_response([serialize.release(r) for r in items])


# ---------------- retain samples ----------------

@bp.post("/mfg/production-runs/<rid>/retain-samples")
def create_retain_sample(rid):
    require_roles("QualityManager")
    run = _get_run(rid)
    body = get_body(request)
    bin_id = check_str(require(body, "bin_id"), "bin_id")
    cases = check_int(require(body, "cases_count"), "cases_count")
    if cases <= 0:
        raise invalid_request("Field 'cases_count' must be > 0")
    retain_until = parse_dt(require(body, "retain_until_utc"), "retain_until_utc")
    status_raw = opt(body, "status", "STORED")
    check_str(status_raw, "status")
    status = check_enum(status_raw, "status", RETAIN_STATUS)
    if run["status"] == "CANCELLED":
        raise terminal_locked("Run is CANCELLED (terminal)")
    if run["status"] != "COMPLETED":
        raise invalid_state("Retain samples require a COMPLETED run")
    if run.get("produced_cases") is not None and cases > int(run["produced_cases"]):
        raise invalid_request("cases_count exceeds the run's produced_cases")
    if retain_until < run["completed_utc_dt"] + timedelta(days=30):
        raise unprocessable(
            ERR_RETAIN_PERIOD_TOO_SHORT,
            "retain_until_utc must be at least 30 days past completion")
    rec = base_record()
    rec.update({
        "run_id": run["id"],
        "bin_id": bin_id,
        "cases_count": cases,
        "retain_until_utc_dt": retain_until,
        "status": status,
    })
    STORES["retains"][rec["id"]] = rec
    # Recompute the lot release's stored retain figure
    release = next((r for r in STORES["releases"].values()
                    if r["run_id"] == run["id"]), None)
    if release is not None:
        release["retain_cases_stored"] = sum(
            int(s["cases_count"]) for s in STORES["retains"].values()
            if s["run_id"] == run["id"] and s["status"] == "STORED")
        touch(release)
    return ok_object(serialize.retain(rec), 201)


# ---------------- lot releases ----------------

@bp.get("/mfg/lot-releases/<rid>")
def get_release(rid):
    require_roles("PlantAdmin", "QualityManager", "LabTechnician")
    return ok_object(serialize.release(_get_release(rid)))


@bp.post("/mfg/lot-releases/<rid>/record-qc")
def record_qc(rid):
    uid, _role = require_roles("LabTechnician")
    rec = _get_release(rid)
    body = get_body(request)
    qc_raw = require(body, "qc_disposition")
    check_str(qc_raw, "qc_disposition")
    qc = check_enum(qc_raw, "qc_disposition", QC_DISPOSITIONS)
    if rec["decision"] in ("RELEASED", "SCRAPPED"):
        raise terminal_locked(f"Lot release decision is {rec['decision']} (terminal)")
    if rec["qc_disposition"] != "PENDING":
        raise invalid_state("QC disposition has already been recorded")
    rec["qc_disposition"] = qc
    rec["qc_recorded_by"] = uid
    touch(rec)
    return ok_object(serialize.release(rec))


@bp.post("/mfg/lot-releases/<rid>/decide")
def decide_release(rid):
    uid, _role = require_roles("QualityManager")
    rec = _get_release(rid)
    body = get_body(request)
    decision_raw = require(body, "decision")
    check_str(decision_raw, "decision")
    decision = check_enum(decision_raw, "decision", DECISIONS)
    if rec["decision"] in ("RELEASED", "SCRAPPED"):
        raise terminal_locked(f"Lot release decision is {rec['decision']} (terminal)")
    current = rec["decision"]
    if current == "HOLD_REWORK" and decision != "SCRAPPED":
        raise invalid_state("A HOLD_REWORK release may only transition to SCRAPPED")
    run = STORES["runs"].get(rec["run_id"])
    if current == "PENDING":
        # Segregation of duties guards every decision from PENDING
        if rec.get("qc_recorded_by") is not None and uid == rec["qc_recorded_by"]:
            raise unprocessable(
                ERR_SOD_VIOLATION,
                "Decider must differ from the QC recorder")
        if decision == "RELEASED":
            if int(rec["retain_cases_stored"]) < 1:
                raise unprocessable(
                    ERR_RETAIN_SAMPLE_REQUIRED,
                    "RELEASED requires at least one STORED retain sample")
            if abs(D(rec["yield_variance_pct"])) > calc.YIELD_TOLERANCE_PCT:
                raise unprocessable(
                    ERR_YIELD_VARIANCE_EXCEEDED,
                    "ABS(yield_variance_pct) exceeds 5.00")
            if rec["qc_disposition"] != "PASSED":
                raise unprocessable(ERR_QC_NOT_PASSED,
                                    "RELEASED requires qc_disposition == PASSED")
    rec["decision"] = decision
    rec["decided_by"] = uid
    if run is not None:
        run["release_status"] = decision
        touch(run)
    if decision == "RELEASED" and run is not None:
        agreement = STORES["agreements"].get(run["agreement_id"])
        if agreement is not None:
            touch(agreement)  # quarter rollup recomputed (derived at read)
    touch(rec)
    return ok_object(serialize.release(rec))

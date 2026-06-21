"""Visit endpoints, charge lines, and the visit lifecycle (PRD §3.4–§3.6)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g, request

import db
from db import parse_iso, stamp_create, touch
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_REFERENCE_NOT_FOUND,
    ERR_SLOT_OVERLAP,
    ERR_VACCINE_INTERVAL_VIOLATION,
)
from middleware import require
from response import ok_array, ok_object
from routes.common import lookup_or_404, paginate, parse_pagination, sort_by_created
from services import calc, derive
from validation import (
    get_body,
    optional_int,
    optional_str,
    require_datetime,
    require_enum,
    require_int,
    require_str,
)

bp = Blueprint("visits", __name__)

VISIT_TYPES = {"CONSULTATION", "PHYSICAL", "VACCINATION"}
VACCINE_MIN_INTERVAL_DAYS = 28


def _slots_overlap(a_start, a_end, b_start, b_end) -> bool:
    """Half-open overlap: [a_start, a_end) intersects [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


@bp.route("/visits", methods=["POST"])
def create_visit():
    require(["FrontDesk"])
    body = get_body()

    # Priority 4: body FK existence (patient_id, provider_id).
    patient_id_raw = body.get("patient_id")
    provider_id_raw = body.get("provider_id")
    if isinstance(patient_id_raw, str) and patient_id_raw not in db.patients:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 404, "patient_id does not resolve")
    if isinstance(provider_id_raw, str) and provider_id_raw not in db.providers:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 404, "provider_id does not resolve")

    # Priority 5: field presence / type / enum.
    patient_id = require_str(body, "patient_id")
    provider_id = require_str(body, "provider_id")
    visit_type = require_enum(body, "visit_type", VISIT_TYPES)
    scheduled_start = require_datetime(body, "scheduled_start")
    scheduled_end = require_datetime(body, "scheduled_end")
    vaccine_code = optional_str(body, "vaccine_code", default=None)

    if patient_id not in db.patients:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 404, "patient_id does not resolve")
    if provider_id not in db.providers:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 404, "provider_id does not resolve")

    if scheduled_end <= scheduled_start:
        raise APIError(ERR_INVALID_REQUEST, 422, "scheduled_end must be strictly after scheduled_start")
    if visit_type == "VACCINATION" and (vaccine_code is None or vaccine_code.strip() == ""):
        raise APIError(ERR_INVALID_REQUEST, 422, "vaccine_code required for VACCINATION visits")

    # Business priority 10: slot overlap against the same provider's calendar.
    for v in db.visits.values():
        if v["provider_id"] != provider_id:
            continue
        if v["status"] in ("CANCELLED", "NO_SHOW"):
            continue
        if _slots_overlap(scheduled_start, scheduled_end,
                          parse_iso(v["scheduled_start"]), parse_iso(v["scheduled_end"])):
            raise APIError(ERR_SLOT_OVERLAP, 409, "Visit slot overlaps an existing visit")

    rec = stamp_create({
        "patient_id": patient_id,
        "provider_id": provider_id,
        "visit_type": visit_type,
        "scheduled_start": body["scheduled_start"],
        "scheduled_end": body["scheduled_end"],
        "vaccine_code": vaccine_code if visit_type == "VACCINATION" else None,
        "status": "SCHEDULED",
        "billed_total_cents": 0,
    })
    db.visits[rec["id"]] = rec
    return ok_object(derive.serialize_visit(rec), 201)


@bp.route("/visits/<vid>", methods=["GET"])
def get_visit(vid):
    require(["FrontDesk", "Provider", "Biller", "Patient"])
    rec = lookup_or_404(db.visits, vid, "Visit")
    if g.user_role == "Patient" and g.user_id != rec["patient_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Patient may only read own visits")
    return ok_object(derive.serialize_visit(rec), 200)


@bp.route("/visits", methods=["GET"])
def list_visits():
    require(["FrontDesk", "Provider", "Biller"])
    limit, offset = parse_pagination()
    items = list(db.visits.values())
    patient_id = request.args.get("patient_id")
    provider_id = request.args.get("provider_id")
    status = request.args.get("status")
    if patient_id is not None:
        items = [v for v in items if v["patient_id"] == patient_id]
    if provider_id is not None:
        items = [v for v in items if v["provider_id"] == provider_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return ok_array([derive.serialize_visit(v) for v in window], limit, offset, total)


# ---------------------------------------------------------------------------
# Charge lines
# ---------------------------------------------------------------------------

@bp.route("/visits/<vid>/charge-lines", methods=["POST"])
def add_charge_line(vid):
    require(["Provider"])
    visit = lookup_or_404(db.visits, vid, "Visit")
    body = get_body()

    # Priority 4: cpt_code FK (natural key) existence.
    cpt_raw = body.get("cpt_code")
    cpt = None
    if isinstance(cpt_raw, str):
        cpt = next((c for c in db.cpt_codes.values() if c["code"] == cpt_raw), None)
        if cpt is None:
            raise APIError(ERR_REFERENCE_NOT_FOUND, 404, "cpt_code does not resolve")

    # Priority 5: field presence / type.
    cpt_code = require_str(body, "cpt_code")
    units = optional_int(body, "units", default=1, minimum=1)
    em_level = optional_int(body, "em_level", default=None, minimum=1, maximum=5)
    if cpt is None:
        cpt = next((c for c in db.cpt_codes.values() if c["code"] == cpt_code), None)
        if cpt is None:
            raise APIError(ERR_REFERENCE_NOT_FOUND, 404, "cpt_code does not resolve")

    # em_level required when the referenced code requires it.
    if cpt["requires_em_level"] and em_level is None:
        raise APIError(ERR_INVALID_REQUEST, 422, "em_level required for this CPT code")

    # Priority 6: visit must be IN_PROGRESS to receive charge lines (PRD §3.3).
    if visit["status"] != "IN_PROGRESS":
        raise APIError(ERR_INVALID_STATE, 409, "Visit must be IN_PROGRESS to add charge lines")

    amount_cents = calc.charge_line_amount(
        cpt["base_fee_cents"], cpt["requires_em_level"], em_level, units
    )
    rec = stamp_create({
        "visit_id": vid,
        "cpt_code": cpt_code,
        "units": units,
        "em_level": em_level,
        "amount_cents": amount_cents,
    })
    db.charge_lines[rec["id"]] = rec
    return ok_object(derive.serialize_charge_line(rec), 201)


@bp.route("/visits/<vid>/charge-lines", methods=["GET"])
def list_charge_lines(vid):
    require(["Provider", "Biller", "FrontDesk"])
    lookup_or_404(db.visits, vid, "Visit")
    limit, offset = parse_pagination()
    items = [cl for cl in db.charge_lines.values() if cl["visit_id"] == vid]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return ok_array([derive.serialize_charge_line(cl) for cl in window], limit, offset, total)


def _visit_line_amounts(vid):
    return [cl["amount_cents"] for cl in db.charge_lines.values() if cl["visit_id"] == vid]


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

@bp.route("/visits/<vid>/check-in", methods=["POST"])
def check_in(vid):
    require(["FrontDesk"])
    visit = lookup_or_404(db.visits, vid, "Visit")
    if visit["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "Visit is not SCHEDULED")

    provider = db.providers.get(visit["provider_id"])
    patient = db.patients.get(visit["patient_id"])
    if not provider or provider["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "Rendering provider is not ACTIVE")
    if not patient or patient["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "Patient is not ACTIVE")

    # Priority 9: vaccine interval (minimum spacing) on VACCINATION check-in.
    if visit["visit_type"] == "VACCINATION":
        this_start = parse_iso(visit["scheduled_start"])
        window_open = this_start - timedelta(days=VACCINE_MIN_INTERVAL_DAYS)
        for other in db.visits.values():
            if other["id"] == vid:
                continue
            if other["patient_id"] != visit["patient_id"]:
                continue
            if other["visit_type"] != "VACCINATION" or other["vaccine_code"] != visit["vaccine_code"]:
                continue
            if other["status"] not in ("CHECKED_IN", "IN_PROGRESS", "CODED", "FINALIZED"):
                continue
            other_start = parse_iso(other["scheduled_start"])
            # Prior dose whose scheduled_start falls within the 28 days immediately
            # before this start (window_open <= other_start < this_start).
            if window_open <= other_start < this_start:
                raise APIError(ERR_VACCINE_INTERVAL_VIOLATION, 409, "Vaccine interval violation")

    visit["status"] = "CHECKED_IN"
    touch(visit)
    return ok_object(derive.serialize_visit(visit), 200)


@bp.route("/visits/<vid>/start", methods=["POST"])
def start_visit(vid):
    require(["Provider"])
    visit = lookup_or_404(db.visits, vid, "Visit")
    if visit["status"] != "CHECKED_IN":
        raise APIError(ERR_INVALID_STATE, 409, "Visit is not CHECKED_IN")
    # Priority 7: acting provider must own the visit.
    if g.user_id != visit["provider_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Only the visit's provider may start it")
    visit["status"] = "IN_PROGRESS"
    touch(visit)
    return ok_object(derive.serialize_visit(visit), 200)


@bp.route("/visits/<vid>/code", methods=["POST"])
def code_visit(vid):
    require(["Provider"])
    visit = lookup_or_404(db.visits, vid, "Visit")
    if visit["status"] != "IN_PROGRESS":
        raise APIError(ERR_INVALID_STATE, 409, "Visit is not IN_PROGRESS")
    if g.user_id != visit["provider_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Only the visit's provider may code it")
    line_amounts = _visit_line_amounts(vid)
    if len(line_amounts) < 1:
        raise APIError(ERR_INVALID_STATE, 409, "Visit must have at least one charge line to code")

    visit["billed_total_cents"] = calc.visit_billed_total_provisional(line_amounts)
    visit["status"] = "CODED"
    touch(visit)
    return ok_object(derive.serialize_visit(visit), 200)


@bp.route("/visits/<vid>/reopen", methods=["POST"])
def reopen_visit(vid):
    require(["Provider"])
    visit = lookup_or_404(db.visits, vid, "Visit")
    if visit["status"] != "CODED":
        raise APIError(ERR_INVALID_STATE, 409, "Visit is not CODED")
    visit["billed_total_cents"] = 0
    visit["status"] = "IN_PROGRESS"
    touch(visit)
    return ok_object(derive.serialize_visit(visit), 200)


@bp.route("/visits/<vid>/finalize", methods=["POST"])
def finalize_visit(vid):
    require(["Biller"])
    visit = lookup_or_404(db.visits, vid, "Visit")
    if visit["status"] != "CODED":
        raise APIError(ERR_INVALID_STATE, 409, "Visit is not CODED")

    # CHAIN-1 link 1: final billed total; charge-line amounts locked (already set).
    line_amounts = _visit_line_amounts(vid)
    visit["billed_total_cents"] = calc.visit_billed_total_final(line_amounts)
    visit["status"] = "FINALIZED"
    touch(visit)

    patient = db.patients.get(visit["patient_id"])
    if patient is not None:
        # CHAIN-1 link 2: patient ledger recomputed (includes this visit now).
        derive.recompute_patient_ledger(patient)
        ledger_touched = True

        # CHAIN-1 link 2 (cont.): qualifying visit flips a matching GAP measure.
        flipped = False
        if visit["visit_type"] in ("PHYSICAL", "VACCINATION"):
            for m in db.hedis_measures.values():
                if m["patient_id"] != patient["id"]:
                    continue
                if m["status"] != "GAP":
                    continue
                if m["measurement_year"] != calc.CURRENT_MEASUREMENT_YEAR:
                    continue
                m["status"] = "NUMERATOR_COMPLIANT"
                touch(m)
                flipped = True

        # CHAIN-1 link 3: open_care_gaps recomputed downward after a flip.
        derive.recompute_patient_open_care_gaps(patient)
        # Patient mutated by ledger and/or gap recompute -> bump once.
        if ledger_touched or flipped:
            touch(patient)

    return ok_object(derive.serialize_visit(visit), 200)


@bp.route("/visits/<vid>/cancel", methods=["POST"])
def cancel_visit(vid):
    require(["FrontDesk"])
    visit = lookup_or_404(db.visits, vid, "Visit")
    if visit["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "Visit is not SCHEDULED")
    visit["status"] = "CANCELLED"
    touch(visit)
    return ok_object(derive.serialize_visit(visit), 200)


@bp.route("/visits/<vid>/no-show", methods=["POST"])
def no_show_visit(vid):
    require(["FrontDesk"])
    visit = lookup_or_404(db.visits, vid, "Visit")
    if visit["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "Visit is not SCHEDULED")
    # Permitted only once the clock has reached/passed scheduled_end.
    if db.clock.now() < parse_iso(visit["scheduled_end"]):
        raise APIError(ERR_INVALID_STATE, 409, "Cannot no-show before scheduled_end")
    visit["status"] = "NO_SHOW"
    touch(visit)
    return ok_object(derive.serialize_visit(visit), 200)

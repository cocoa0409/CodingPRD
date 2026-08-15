"""DockTicket, LandingLine, GradeAssessment: dockside purchase workflow."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from db import store, new_record, touch
from errors import (
    ApiError,
    ERR_TICKET_NOT_FOUND,
    ERR_LINE_NOT_FOUND,
    ERR_ASSESSMENT_NOT_FOUND,
    ERR_VESSEL_NOT_FOUND,
    ERR_CATCH_AREA_NOT_FOUND,
    ERR_SPECIES_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
    ERR_INVALID_REQUEST,
    ERR_INVALID_LANDING_WINDOW,
    ERR_VESSEL_LANDING_OVERLAP,
    ERR_TICKET_INVALID_STATE,
    ERR_ASSESSMENT_INVALID_STATE,
    ERR_ASSESSMENT_ALREADY_ACTIVE,
    ERR_INVALID_YIELD,
    ERR_REGRADE_LIMIT_EXCEEDED,
    ERR_IMPORT_DOCS_NOT_CLEARED,
    ERR_LOT_ON_HOLD,
    ERR_QUOTE_NOT_PUBLISHED,
    ERR_STALE_VERSION,
)
from middleware import auth, require
from response import ok, ok_list
from services.calc import (
    ZERO,
    q2,
    cents,
    settlement_quote,
    processed_weight,
)
from services.cascades import (
    ticket_lines,
    ticket_lots,
    recall_lot,
    recompute_line,
    recompute_provisional_total,
    recompute_final_total,
    post_release_epilogue,
)
from util import (
    body,
    req_str,
    req_int,
    req_enum,
    opt_enum,
    opt_str,
    req_num,
    req_instant,
    parse_instant,
    apply_filters,
)

bp = Blueprint("tickets", __name__)

GRADES = {"GRADE_A", "GRADE_B", "GRADE_C"}
PROCESSING_TYPES = {"WHOLE", "FILLETED"}
VOIDABLE_STATES = {"DRAFT", "LANDED", "GRADED", "SETTLED"}


def _get_ticket(rid):
    rec = store.tickets.get(rid)
    if rec is None:
        raise ApiError(ERR_TICKET_NOT_FOUND, 404, "DockTicket id does not exist")
    return rec


def _get_line(rid):
    rec = store.lines.get(rid)
    if rec is None:
        raise ApiError(ERR_LINE_NOT_FOUND, 404, "LandingLine id does not exist")
    return rec


def _get_assessment(rid):
    rec = store.assessments.get(rid)
    if rec is None:
        raise ApiError(ERR_ASSESSMENT_NOT_FOUND, 404, "GradeAssessment id does not exist")
    return rec


# ---------------------------------------------------------------------------
# DockTicket
# ---------------------------------------------------------------------------
@bp.post("/dock-tickets")
def create_ticket():
    uid, role = auth()
    require(role, {"DockBuyer", "VesselAgent"})
    b = body()
    # Ownership (priority 3) precedes shape/existence (priority 4).
    if role == "VesselAgent" and b.get("vessel_id") != uid:
        raise ApiError(
            ERR_OWNERSHIP_MISMATCH, 403,
            "VesselAgent may act only on tickets of its own vessel",
        )
    vessel_id = req_str(b, "vessel_id")
    catch_area_id = req_str(b, "catch_area_id")
    landing_start_at = req_instant(b, "landing_start_at")
    landing_end_at = req_instant(b, "landing_end_at")
    if vessel_id not in store.vessels:
        raise ApiError(ERR_VESSEL_NOT_FOUND, 404, "Vessel id does not exist")
    if catch_area_id not in store.catch_areas:
        raise ApiError(ERR_CATCH_AREA_NOT_FOUND, 404, "CatchArea id does not exist")
    start = parse_instant(landing_start_at)
    end = parse_instant(landing_end_at)
    # Temporal (priority 8): window validity, then half-open overlap.
    if not end > start:
        raise ApiError(
            ERR_INVALID_LANDING_WINDOW, 400,
            "landing_end_at must be strictly after landing_start_at",
        )
    for other in store.tickets.values():
        if other["vessel_id"] != vessel_id or other["status"] == "VOIDED":
            continue
        o_start = parse_instant(other["landing_start_at"])
        o_end = parse_instant(other["landing_end_at"])
        if start < o_end and o_start < end:
            raise ApiError(
                ERR_VESSEL_LANDING_OVERLAP, 409,
                "Landing window overlaps another non-VOID ticket of this vessel",
            )
    rec = new_record({
        "vessel_id": vessel_id,
        "catch_area_id": catch_area_id,
        "landing_start_at": landing_start_at,
        "landing_end_at": landing_end_at,
        "status": "DRAFT",
        "regrade_count": 0,
        "provisional_total_cents": 0,
        "final_total_cents": 0,
    })
    store.tickets[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/dock-tickets")
def list_tickets():
    auth()
    page, total, limit, offset = apply_filters(
        list(store.tickets.values()),
        ["vessel_id", "catch_area_id", "status"],
    )
    return ok_list(page, total, limit, offset)


@bp.get("/dock-tickets/<rid>")
def get_ticket(rid):
    auth()
    return ok(_get_ticket(rid))


@bp.post("/dock-tickets/<rid>/land")
def land_ticket(rid):
    uid, role = auth()
    require(role, {"DockBuyer", "VesselAgent"})
    ticket = _get_ticket(rid)
    if role == "VesselAgent" and ticket["vessel_id"] != uid:
        raise ApiError(
            ERR_OWNERSHIP_MISMATCH, 403,
            "VesselAgent may act only on tickets of its own vessel",
        )
    if ticket["status"] != "DRAFT":
        raise ApiError(ERR_TICKET_INVALID_STATE, 409, "Ticket is not in DRAFT")
    ticket["status"] = "LANDED"
    touch(ticket)
    return ok(ticket)


@bp.post("/dock-tickets/<rid>/settle")
def settle_ticket(rid):
    _, role = auth()
    require(role, {"OperationsManager"})
    ticket = _get_ticket(rid)
    if ticket["status"] != "GRADED":
        raise ApiError(ERR_TICKET_INVALID_STATE, 409, "Ticket is not in GRADED")
    # Import-document gate: for every imported-species line, the required
    # documents for (ticket, species) must all be CLEARED.
    for line in ticket_lines(ticket["id"]):
        if line["voided"]:
            continue
        species = store.species[line["species_id"]]
        if not species["is_import"]:
            continue
        required_types = ["HEALTH_CERT"]
        if species["requires_cites"]:
            required_types.append("CITES")
        for doc_type in required_types:
            cleared = any(
                d["dock_ticket_id"] == ticket["id"]
                and d["species_id"] == line["species_id"]
                and d["doc_type"] == doc_type
                and d["status"] == "CLEARED"
                for d in store.import_docs.values()
            )
            if not cleared:
                raise ApiError(
                    ERR_IMPORT_DOCS_NOT_CLEARED, 409,
                    "Required import documents are not all CLEARED",
                )
    # Hold gate: no derived lot may be ON_HOLD.
    if any(lot["hold_status"] == "ON_HOLD" for lot in ticket_lots(ticket["id"])):
        raise ApiError(
            ERR_LOT_ON_HOLD, 409,
            "A derived inventory lot is ON_HOLD",
        )
    ticket["status"] = "SETTLED"
    touch(ticket)
    vessel = store.vessels[ticket["vessel_id"]]
    vessel["payable_balance_cents"] += ticket["final_total_cents"]
    touch(vessel)
    return ok(ticket)


@bp.post("/dock-tickets/<rid>/pay")
def pay_ticket(rid):
    _, role = auth()
    require(role, {"OperationsManager"})
    ticket = _get_ticket(rid)
    if ticket["status"] != "SETTLED":
        raise ApiError(ERR_TICKET_INVALID_STATE, 409, "Ticket is not in SETTLED")
    ticket["status"] = "PAID"
    touch(ticket)
    vessel = store.vessels[ticket["vessel_id"]]
    vessel["payable_balance_cents"] -= ticket["final_total_cents"]
    touch(vessel)
    return ok(ticket)


def _recall_ticket_lots(ticket):
    affected = []
    for lot in ticket_lots(ticket["id"]):
        if lot["lifecycle_status"] == "ACTIVE":
            affected.extend(recall_lot(lot))
            touch(lot)
    return affected


@bp.post("/dock-tickets/<rid>/void")
def void_ticket(rid):
    _, role = auth()
    require(role, {"OperationsManager"})
    ticket = _get_ticket(rid)
    if ticket["status"] not in VOIDABLE_STATES:
        raise ApiError(
            ERR_TICKET_INVALID_STATE, 409,
            "Ticket cannot be voided from %s" % ticket["status"],
        )
    was_settled = ticket["status"] == "SETTLED"
    # Unwind everything the ticket created.
    for line in ticket_lines(ticket["id"]):
        if not line["voided"]:
            line["voided"] = True
            touch(line)
    recompute_provisional_total(ticket)
    affected = _recall_ticket_lots(ticket)
    post_release_epilogue(affected, fire_substitution=False)
    if was_settled:
        vessel = store.vessels[ticket["vessel_id"]]
        vessel["payable_balance_cents"] -= ticket["final_total_cents"]
        touch(vessel)
    ticket["status"] = "VOIDED"
    touch(ticket)
    return ok(ticket)


@bp.post("/dock-tickets/<rid>/request-regrade")
def request_regrade(rid):
    _, role = auth()
    require(role, {"DockBuyer", "OperationsManager"})
    ticket = _get_ticket(rid)
    if ticket["status"] != "GRADED":
        raise ApiError(ERR_TICKET_INVALID_STATE, 409, "Ticket is not in GRADED")
    if ticket["regrade_count"] >= 2:
        raise ApiError(
            ERR_REGRADE_LIMIT_EXCEEDED, 409,
            "regrade_count already at 2",
        )
    ticket["regrade_count"] += 1
    line_ids = {l["id"] for l in ticket_lines(ticket["id"])}
    for a in store.assessments.values():
        if a["landing_line_id"] in line_ids and a["status"] == "FINAL":
            a["status"] = "SUPERSEDED"
            touch(a)
    affected = _recall_ticket_lots(ticket)
    post_release_epilogue(affected, fire_substitution=False)
    recompute_final_total(ticket)
    ticket["status"] = "LANDED"
    touch(ticket)
    return ok(ticket)


# ---------------------------------------------------------------------------
# LandingLine
# ---------------------------------------------------------------------------
@bp.post("/landing-lines")
def create_line():
    _, role = auth()
    require(role, {"DockBuyer"})
    b = body()
    dock_ticket_id = req_str(b, "dock_ticket_id")
    species_id = req_str(b, "species_id")
    declared_grade = req_enum(b, "declared_grade", GRADES)
    landed_weight_kg = req_num(b, "landed_weight_kg")
    if landed_weight_kg <= ZERO:
        raise ApiError(ERR_INVALID_REQUEST, 400, "landed_weight_kg must be > 0")
    processing_type = opt_enum(b, "processing_type", PROCESSING_TYPES, "WHOLE")
    expected_dock_ticket_version = req_int(b, "expected_dock_ticket_version")
    # Body FK resolution in the declared order: species_id, then dock_ticket_id.
    if species_id not in store.species:
        raise ApiError(ERR_SPECIES_NOT_FOUND, 404, "Species id does not exist")
    ticket = store.tickets.get(dock_ticket_id)
    if ticket is None:
        raise ApiError(ERR_TICKET_NOT_FOUND, 404, "DockTicket id does not exist")
    # OCC (priority 5) precedes the state check (priority 6).
    if expected_dock_ticket_version != ticket["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_dock_ticket_version is stale")
    if ticket["status"] != "LANDED":
        raise ApiError(ERR_TICKET_INVALID_STATE, 409, "Ticket is not in LANDED")
    # Provisional settlement on the declared grade, dated on the landing day.
    landing_date = parse_instant(ticket["landing_start_at"]).date()
    quote = settlement_quote(species_id, declared_grade, landing_date)
    if quote is None:
        raise ApiError(
            ERR_QUOTE_NOT_PUBLISHED, 422,
            "No settlement quote resolvable for this species, grade, and landing date",
        )
    weight = q2(landed_weight_kg)
    provisional = cents(weight * quote["price_per_kg_cents"])
    rec = new_record({
        "dock_ticket_id": dock_ticket_id,
        "species_id": species_id,
        "declared_grade": declared_grade,
        "landed_weight_kg": weight,
        "processing_type": processing_type,
        "provisional_amount_cents": provisional,
        "processed_weight_kg": ZERO,
        "final_amount_cents": 0,
        "voided": False,
    })
    store.lines[rec["id"]] = rec
    recompute_provisional_total(ticket)
    touch(ticket)
    return ok(rec, 201)


@bp.get("/landing-lines")
def list_lines():
    auth()
    page, total, limit, offset = apply_filters(
        list(store.lines.values()),
        ["dock_ticket_id", "species_id"],
    )
    return ok_list(page, total, limit, offset)


@bp.get("/landing-lines/<rid>")
def get_line(rid):
    auth()
    return ok(_get_line(rid))


# ---------------------------------------------------------------------------
# GradeAssessment
# ---------------------------------------------------------------------------
@bp.post("/grade-assessments")
def create_assessment():
    uid, role = auth()
    require(role, {"GradingInspector"})
    b = body()
    landing_line_id = req_str(b, "landing_line_id")
    assessed_grade = req_enum(b, "assessed_grade", GRADES)
    yield_pct = req_num(b, "yield_pct")
    notes = opt_str(b, "notes", "")
    line = store.lines.get(landing_line_id)
    if line is None:
        raise ApiError(ERR_LINE_NOT_FOUND, 404, "LandingLine id does not exist")
    ticket = store.tickets[line["dock_ticket_id"]]
    if ticket["status"] != "LANDED":
        raise ApiError(ERR_TICKET_INVALID_STATE, 409, "Owning ticket is not in LANDED")
    active = any(
        a["landing_line_id"] == landing_line_id and a["status"] in ("DRAFT", "FINAL")
        for a in store.assessments.values()
    )
    if active:
        raise ApiError(
            ERR_ASSESSMENT_ALREADY_ACTIVE, 409,
            "A DRAFT or FINAL assessment already exists for this landing line",
        )
    if not (ZERO < yield_pct <= Decimal("1")):
        raise ApiError(ERR_INVALID_YIELD, 400, "yield_pct must satisfy 0 < yield_pct <= 1")
    rec = new_record({
        "landing_line_id": landing_line_id,
        "inspector_user_id": uid,
        "assessed_grade": assessed_grade,
        "yield_pct": yield_pct,
        "notes": notes,
        "status": "DRAFT",
    })
    store.assessments[rec["id"]] = rec
    return ok(rec, 201)


@bp.post("/grade-assessments/<rid>/finalize")
def finalize_assessment(rid):
    _, role = auth()
    require(role, {"GradingInspector"})
    assessment = _get_assessment(rid)
    if assessment["status"] != "DRAFT":
        raise ApiError(ERR_ASSESSMENT_INVALID_STATE, 409, "Assessment is not in DRAFT")
    line = store.lines[assessment["landing_line_id"]]
    ticket = store.tickets[line["dock_ticket_id"]]
    if ticket["status"] != "LANDED":
        raise ApiError(ERR_TICKET_INVALID_STATE, 409, "Owning ticket is not in LANDED")
    # Final settlement prices the assessed grade on the landing day.
    landing_date = parse_instant(ticket["landing_start_at"]).date()
    quote = settlement_quote(line["species_id"], assessment["assessed_grade"], landing_date)
    if quote is None:
        raise ApiError(
            ERR_QUOTE_NOT_PUBLISHED, 422,
            "No settlement quote resolvable for this species, assessed grade, and landing date",
        )
    species = store.species[line["species_id"]]
    processed = processed_weight(
        line["landed_weight_kg"],
        assessment["yield_pct"],
        assessment["assessed_grade"],
        line["processing_type"],
    )
    final_amount = cents(processed * quote["price_per_kg_cents"])
    assessment["status"] = "FINAL"
    touch(assessment)
    line["processed_weight_kg"] = processed
    line["final_amount_cents"] = final_amount
    touch(line)
    # Birth the inventory lot (FRESH; shelf-life clock starts at landing).
    landed_dt = parse_instant(ticket["landing_start_at"])
    unit_cost = cents(Decimal(final_amount) / processed) if processed > ZERO else 0
    lot = new_record({
        "landing_line_id": line["id"],
        "species_id": line["species_id"],
        "storage_type": "FRESH",
        "landed_at": ticket["landing_start_at"],
        "frozen_at": None,
        "expires_at": landed_dt + timedelta(hours=species["fresh_shelf_life_hours"]),
        "received_weight_kg": processed,
        "available_weight_kg": processed,
        "reserved_weight_kg": ZERO,
        "committed_weight_kg": ZERO,
        "shipped_weight_kg": ZERO,
        "condemned_weight_kg": ZERO,
        "spoiled_weight_kg": ZERO,
        "recalled_weight_kg": ZERO,
        "lifecycle_status": "ACTIVE",
        "hold_status": "CLEAR",
        "unit_cost_cents": unit_cost,
    })
    store.lots[lot["id"]] = lot
    recompute_final_total(ticket)
    # Auto-grade: every non-voided line of a ticket holding >= 1 line has a
    # FINAL assessment.
    lines = ticket_lines(ticket["id"])
    non_voided = [l for l in lines if not l["voided"]]
    if non_voided:
        all_final = all(
            any(
                a["landing_line_id"] == l["id"] and a["status"] == "FINAL"
                for a in store.assessments.values()
            )
            for l in non_voided
        )
        if all_final:
            ticket["status"] = "GRADED"
    touch(ticket)
    return ok(assessment)


@bp.get("/grade-assessments")
def list_assessments():
    auth()
    page, total, limit, offset = apply_filters(
        list(store.assessments.values()),
        ["landing_line_id", "status"],
    )
    return ok_list(page, total, limit, offset)


@bp.get("/grade-assessments/<rid>")
def get_assessment(rid):
    auth()
    return ok(_get_assessment(rid))

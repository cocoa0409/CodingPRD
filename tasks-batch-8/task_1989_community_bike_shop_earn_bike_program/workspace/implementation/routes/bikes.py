"""Bike pipeline: intake, triage, routing, refurbishment, safety inspection,
harvest, usage ledger, and scrap (PRD §3.1–§3.4, §3.13)."""

from flask import Blueprint, request

from db import db, _parse_iso
from errors import ApiError
from middleware import require_roles, get_body, validate_payload
from response import success
from services.core import (make_common, make_event, touch, paginate, sorted_by_created,
                           recompute_donor, recompute_bike_parts_cost, recompute_part_low_stock,
                           scrap_payout, SKILL_ORDER)

bp = Blueprint("bikes", __name__)

BIKE_TYPES = ["ROAD", "MTB", "HYBRID", "KIDS", "BMX", "CARGO"]
GRADES = ["A", "B", "C", "D"]
CHECKLIST_KEYS = ["brakes", "steering", "tires", "drivetrain", "reflectors"]
MATERIALS = ["STEEL", "ALUMINUM", "MIXED"]


def bike_view(b):
    return {
        "id": b["id"],
        "donor_id": b["donor_id"],
        "serial_number": b["serial_number"],
        "bike_type": b["bike_type"],
        "wheel_size_inches": b["wheel_size_inches"],
        "condition_grade": b["condition_grade"],
        "frame_damage": b["frame_damage"],
        "status": b["status"],
        "refurb_lead_volunteer_id": b["refurb_lead_volunteer_id"],
        "parts_cost_cents": b["parts_cost_cents"],
        "rework_count": b["rework_count"],
        "latest_inspection_result": b["latest_inspection_result"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def harvest_view(h):
    return {
        "id": h["id"],
        "bike_id": h["bike_id"],
        "part_id": h["part_id"],
        "quantity": h["quantity"],
        "harvested_by_user_id": h["harvested_by_user_id"],
        "note": h["note"],
        "created_at": h["created_at"],
    }


def usage_view(u):
    return {
        "id": u["id"],
        "bike_id": u["bike_id"],
        "part_id": u["part_id"],
        "quantity": u["quantity"],
        "unit_cost_cents": u["unit_cost_cents"],
        "logged_by_user_id": u["logged_by_user_id"],
        "status": u["status"],
        "void_reason": u["void_reason"],
        "created_at": u["created_at"],
    }


def inspection_view(i):
    return {
        "id": i["id"],
        "bike_id": i["bike_id"],
        "inspector_volunteer_id": i["inspector_volunteer_id"],
        "result": i["result"],
        "checklist": i["checklist"],
        "note": i["note"],
        "created_at": i["created_at"],
    }


def ticket_view(t):
    return {
        "id": t["id"],
        "bike_id": t["bike_id"],
        "material": t["material"],
        "weight_kg": t["weight_kg"],
        "recycler_name": t["recycler_name"],
        "payout_cents": t["payout_cents"],
        "status": t["status"],
        "picked_up_at": t["picked_up_at"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def _get_bike(bike_id):
    bike = db.bikes.get(bike_id)
    if bike is None:
        raise ApiError("ERR_NOT_FOUND", f"Bike {bike_id} does not exist")
    return bike


def _get_volunteer(volunteer_id):
    vol = db.volunteers.get(volunteer_id)
    if vol is None:
        raise ApiError("ERR_NOT_FOUND", f"Volunteer {volunteer_id} does not exist")
    return vol


def _get_part(part_id):
    part = db.parts.get(part_id)
    if part is None:
        raise ApiError("ERR_NOT_FOUND", f"Part {part_id} does not exist")
    return part


def _caller_volunteer(user_id):
    """Volunteer-role callers are entity-backed: X-User-ID must be a Volunteer id."""
    vol = db.volunteers.get(user_id)
    if vol is None:
        raise ApiError("ERR_NOT_FOUND", f"Volunteer {user_id} does not exist")
    return vol


# ---------------------------------------------------------------------------
# Bike intake & reads
# ---------------------------------------------------------------------------

@bp.post("/bikes")
def create_bike():
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {
        "donor_id": {"type": "string", "required": True},
        "serial_number": {"type": "string", "required": True},
        "bike_type": {"type": "string", "required": True, "enum": BIKE_TYPES},
        "wheel_size_inches": {"type": "number", "required": True},
    })
    donor = db.donors.get(body["donor_id"])
    if donor is None:
        raise ApiError("ERR_NOT_FOUND", f"Donor {body['donor_id']} does not exist")
    if any(b["serial_number"] == body["serial_number"] for b in db.bikes.values()):
        raise ApiError("ERR_SERIAL_NUMBER_CONFLICT", "serial_number already registered")
    bike = make_common()
    bike.update({
        "donor_id": body["donor_id"],
        "serial_number": body["serial_number"],
        "bike_type": body["bike_type"],
        "wheel_size_inches": body["wheel_size_inches"],
        "condition_grade": None,
        "frame_damage": None,
        "status": "RECEIVED",
        "refurb_lead_volunteer_id": None,
        "parts_cost_cents": 0,
        "rework_count": 0,
        "latest_inspection_result": None,
    })
    db.bikes[bike["id"]] = bike
    recompute_donor(donor)
    return success(bike_view(bike), status=201)


@bp.get("/bikes/<bike_id>")
def get_bike(bike_id):
    require_roles("ShopCoordinator", "ProgramDirector", "Volunteer", "Participant", "Member")
    return success(bike_view(_get_bike(bike_id)))


@bp.get("/bikes")
def list_bikes():
    require_roles("ShopCoordinator", "ProgramDirector", "Volunteer", "Participant", "Member")
    rows = list(db.bikes.values())
    for param in ("status", "condition_grade", "bike_type", "donor_id", "refurb_lead_volunteer_id"):
        value = request.args.get(param)
        if value is not None:
            rows = [b for b in rows if b[param] == value]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([bike_view(b) for b in page], pagination=pg)


# ---------------------------------------------------------------------------
# Triage & routing
# ---------------------------------------------------------------------------

@bp.post("/bikes/<bike_id>/triage")
def triage_bike(bike_id):
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {
        "condition_grade": {"type": "string", "required": True, "enum": GRADES},
        "frame_damage": {"type": "boolean", "required": True},
    })
    bike = _get_bike(bike_id)
    if bike["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "Only a RECEIVED bike can be triaged")
    bike["condition_grade"] = body["condition_grade"]
    bike["frame_damage"] = body["frame_damage"]
    bike["status"] = "TRIAGED"
    touch(bike)
    donor = db.donors.get(bike["donor_id"])
    if donor is not None:
        recompute_donor(donor)
    return success(bike_view(bike))


@bp.post("/bikes/<bike_id>/route")
def route_bike(bike_id):
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {
        "destination": {"type": "string", "required": True, "enum": ["REFURBISH", "HARVEST", "SCRAP"]},
        "refurb_lead_volunteer_id": {"type": "string"},
    })
    bike = _get_bike(bike_id)
    destination = body["destination"]

    if destination == "REFURBISH":
        if bike["status"] != "TRIAGED":
            raise ApiError("ERR_INVALID_STATE", "Only a TRIAGED bike can be routed to refurbishment")
        # Body FK existence precedes business checks.
        lead_id = body.get("refurb_lead_volunteer_id")
        lead = None
        if lead_id is not None:
            lead = _get_volunteer(lead_id)
        if bike["condition_grade"] not in ("A", "B", "C"):
            raise ApiError("ERR_GRADE_NOT_REFURBISHABLE", "Grade D bikes cannot be refurbished")
        if (lead is None
                or SKILL_ORDER.index(lead["skill_level"]) < SKILL_ORDER.index("APPRENTICE")
                or lead["engagement_status"] != "ACTIVE"):
            raise ApiError("ERR_LEAD_INELIGIBLE", "Refurb lead must be APPRENTICE+ and ACTIVE")
        bike["refurb_lead_volunteer_id"] = lead_id
        bike["status"] = "IN_REFURBISHMENT"
    elif destination == "HARVEST":
        if bike["status"] == "TRIAGED":
            if bike["condition_grade"] not in ("C", "D"):
                raise ApiError("ERR_GRADE_NOT_HARVESTABLE", "Grade A/B bikes cannot be harvested")
        elif bike["status"] == "IN_REFURBISHMENT":
            # Mid-refurb redirect: blocked once a passing inspection exists.
            if any(i["bike_id"] == bike["id"] and i["result"] == "PASS" for i in db.inspections.values()):
                raise ApiError("ERR_INVALID_STATE", "A bike with a passing inspection cannot be redirected")
            bike["refurb_lead_volunteer_id"] = None
        else:
            raise ApiError("ERR_INVALID_STATE", "Bike cannot be routed to harvest from its current state")
        bike["status"] = "HARVEST_QUEUE"
    else:  # SCRAP
        if bike["status"] != "TRIAGED":
            raise ApiError("ERR_INVALID_STATE", "Only a TRIAGED bike can be routed to scrap")
        if not (bike["condition_grade"] == "D" and bike["frame_damage"] is True):
            raise ApiError("ERR_SCRAP_CRITERIA_NOT_MET", "Scrap requires grade D with frame damage")
        bike["status"] = "SCRAP_PENDING"
    touch(bike)
    return success(bike_view(bike))


# ---------------------------------------------------------------------------
# Refurbishment & safety inspection
# ---------------------------------------------------------------------------

@bp.post("/bikes/<bike_id>/submit-safety")
def submit_safety(bike_id):
    user_id, _ = require_roles("Volunteer")
    bike = _get_bike(bike_id)
    vol = _caller_volunteer(user_id)
    if bike["status"] != "IN_REFURBISHMENT":
        raise ApiError("ERR_INVALID_STATE", "Only a bike IN_REFURBISHMENT can be submitted for safety review")
    if vol["engagement_status"] != "ACTIVE":
        raise ApiError("ERR_VOLUNTEER_SUSPENDED", "Suspended volunteers cannot submit bikes")
    if not any(u["bike_id"] == bike["id"] and u["status"] == "COMMITTED" for u in db.part_usages.values()):
        raise ApiError("ERR_NO_WORK_RECORDED", "At least one committed part usage is required")
    bike["status"] = "SAFETY_REVIEW"
    touch(bike)
    return success(bike_view(bike))


@bp.post("/bikes/<bike_id>/safety-inspections")
def create_inspection(bike_id):
    user_id, _ = require_roles("Volunteer")
    body = get_body()
    checklist = body.get("checklist")
    if not isinstance(checklist, dict):
        checklist_ok = False
    else:
        checklist_ok = all(isinstance(checklist.get(k), bool) for k in CHECKLIST_KEYS)
    validate_payload(body, {
        "result": {"type": "string", "required": True, "enum": ["PASS", "FAIL"]},
        "checklist": {"type": "object", "required": True},
        "note": {"type": "string"},
    })
    if not checklist_ok:
        raise ApiError("ERR_VALIDATION", "checklist must carry boolean brakes/steering/tires/drivetrain/reflectors")
    bike = _get_bike(bike_id)
    inspector = _caller_volunteer(user_id)
    if bike["status"] != "SAFETY_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only a bike in SAFETY_REVIEW can be inspected")
    # Safety / segregation-of-duties tier (PRD §2.7) runs before business
    # constraints such as inspector-skill and engagement eligibility.
    if bike["refurb_lead_volunteer_id"] is not None and inspector["id"] == bike["refurb_lead_volunteer_id"]:
        raise ApiError("ERR_INSPECTOR_IS_REFURB_LEAD", "The inspector must not be the refurb lead")
    if body["result"] == "PASS" and not all(checklist[k] for k in CHECKLIST_KEYS):
        raise ApiError("ERR_CHECKLIST_INCONSISTENT", "PASS requires every checklist item true")
    if SKILL_ORDER.index(inspector["skill_level"]) < SKILL_ORDER.index("JOURNEYMAN"):
        raise ApiError("ERR_INSPECTOR_SKILL_INSUFFICIENT", "Inspector must be JOURNEYMAN or LEAD_MECHANIC")
    if inspector["engagement_status"] != "ACTIVE":
        raise ApiError("ERR_VOLUNTEER_SUSPENDED", "Suspended volunteers cannot inspect")

    inspection = make_event()
    inspection.update({
        "bike_id": bike["id"],
        "inspector_volunteer_id": inspector["id"],
        "result": body["result"],
        "checklist": {k: checklist[k] for k in CHECKLIST_KEYS},
        "note": body.get("note"),
    })
    db.inspections[inspection["id"]] = inspection

    bike["latest_inspection_result"] = body["result"]
    if body["result"] == "PASS":
        bike["status"] = "READY_FOR_DISPOSITION"
    else:
        bike["status"] = "IN_REFURBISHMENT"
        bike["rework_count"] += 1
    touch(bike)
    inspector["inspections_conducted"] += 1
    touch(inspector)
    return success(inspection_view(inspection), status=201)


@bp.get("/safety-inspections/<inspection_id>")
def get_inspection(inspection_id):
    require_roles("ShopCoordinator", "ProgramDirector", "Volunteer")
    row = db.inspections.get(inspection_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", f"SafetyInspection {inspection_id} does not exist")
    return success(inspection_view(row))


@bp.get("/safety-inspections")
def list_inspections():
    require_roles("ShopCoordinator", "ProgramDirector", "Volunteer")
    rows = list(db.inspections.values())
    for param in ("bike_id", "inspector_volunteer_id", "result"):
        value = request.args.get(param)
        if value is not None:
            rows = [i for i in rows if i[param] == value]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([inspection_view(i) for i in page], pagination=pg)


# ---------------------------------------------------------------------------
# Harvest
# ---------------------------------------------------------------------------

@bp.post("/bikes/<bike_id>/harvest-logs")
def create_harvest(bike_id):
    user_id, _ = require_roles("Volunteer")
    body = get_body()
    validate_payload(body, {
        "part_id": {"type": "string", "required": True},
        "quantity": {"type": "integer", "required": True},
        "note": {"type": "string"},
    })
    bike = _get_bike(bike_id)
    part = _get_part(body["part_id"])
    vol = _caller_volunteer(user_id)
    if bike["status"] != "HARVEST_QUEUE":
        raise ApiError("ERR_INVALID_STATE", "Harvest logs require a bike in HARVEST_QUEUE")
    if vol["engagement_status"] != "ACTIVE":
        raise ApiError("ERR_VOLUNTEER_SUSPENDED", "Suspended volunteers cannot log harvests")
    if part["category"] == "HELMET":
        raise ApiError("ERR_NOT_HARVESTABLE_CATEGORY", "Helmets are purchased stock only")
    if body["quantity"] < 1:
        raise ApiError("ERR_QUANTITY_INVALID", "quantity must be at least 1")

    harvest = make_event()
    harvest.update({
        "bike_id": bike["id"],
        "part_id": part["id"],
        "quantity": body["quantity"],
        "harvested_by_user_id": user_id,
        "note": body.get("note"),
    })
    db.part_harvests[harvest["id"]] = harvest
    part["quantity_on_hand"] += body["quantity"]
    touch(part)
    recompute_part_low_stock(part)
    return success(harvest_view(harvest), status=201)


@bp.get("/harvest-logs/<harvest_id>")
def get_harvest(harvest_id):
    require_roles("ShopCoordinator", "ProgramDirector", "Volunteer")
    row = db.part_harvests.get(harvest_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", f"PartHarvest {harvest_id} does not exist")
    return success(harvest_view(row))


@bp.get("/harvest-logs")
def list_harvests():
    require_roles("ShopCoordinator", "ProgramDirector", "Volunteer")
    rows = list(db.part_harvests.values())
    for param in ("bike_id", "part_id"):
        value = request.args.get(param)
        if value is not None:
            rows = [h for h in rows if h[param] == value]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([harvest_view(h) for h in page], pagination=pg)


@bp.post("/bikes/<bike_id>/harvest-complete")
def harvest_complete(bike_id):
    require_roles("ShopCoordinator")
    bike = _get_bike(bike_id)
    if bike["status"] != "HARVEST_QUEUE":
        raise ApiError("ERR_INVALID_STATE", "Only a bike in HARVEST_QUEUE can complete harvest")
    if not any(h["bike_id"] == bike["id"] for h in db.part_harvests.values()):
        raise ApiError("ERR_NO_HARVEST_RECORDED", "At least one harvest log is required")
    bike["status"] = "HARVESTED"
    touch(bike)
    return success(bike_view(bike))


# ---------------------------------------------------------------------------
# Part usage ledger
# ---------------------------------------------------------------------------

@bp.post("/bikes/<bike_id>/usage-logs")
def create_usage(bike_id):
    user_id, _ = require_roles("Volunteer")
    body = get_body()
    validate_payload(body, {
        "part_id": {"type": "string", "required": True},
        "quantity": {"type": "integer", "required": True},
        "expected_part_version": {"type": "integer", "required": True},
    })
    bike = _get_bike(bike_id)
    part = _get_part(body["part_id"])
    vol = _caller_volunteer(user_id)
    # OCC runs first among the state checks.
    if body["expected_part_version"] != part["version"]:
        raise ApiError("ERR_STALE_VERSION", "Part version has advanced; re-read and resubmit")
    if bike["status"] != "IN_REFURBISHMENT":
        raise ApiError("ERR_INVALID_STATE", "Usage logs require a bike IN_REFURBISHMENT")
    if vol["engagement_status"] != "ACTIVE":
        raise ApiError("ERR_VOLUNTEER_SUSPENDED", "Suspended volunteers cannot log usage")
    if SKILL_ORDER.index(vol["skill_level"]) < SKILL_ORDER.index("APPRENTICE"):
        raise ApiError("ERR_USAGE_SKILL_INSUFFICIENT", "Usage logging requires APPRENTICE or above")
    if body["quantity"] < 1:
        raise ApiError("ERR_QUANTITY_INVALID", "quantity must be at least 1")
    if body["quantity"] > part["quantity_on_hand"]:
        raise ApiError("ERR_INSUFFICIENT_STOCK", "quantity exceeds Part.quantity_on_hand")

    usage = make_event()
    usage.update({
        "bike_id": bike["id"],
        "part_id": part["id"],
        "quantity": body["quantity"],
        "unit_cost_cents": part["unit_cost_cents"],  # frozen snapshot
        "logged_by_user_id": user_id,
        "status": "COMMITTED",
        "void_reason": None,
    })
    db.part_usages[usage["id"]] = usage
    part["quantity_on_hand"] -= body["quantity"]
    touch(part)
    recompute_part_low_stock(part)
    recompute_bike_parts_cost(bike)
    touch(bike)
    return success(usage_view(usage), status=201)


@bp.get("/usage-logs/<usage_id>")
def get_usage(usage_id):
    require_roles("ShopCoordinator", "ProgramDirector", "Volunteer")
    row = db.part_usages.get(usage_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", f"PartUsage {usage_id} does not exist")
    return success(usage_view(row))


@bp.get("/usage-logs")
def list_usages():
    require_roles("ShopCoordinator", "ProgramDirector", "Volunteer")
    rows = list(db.part_usages.values())
    for param in ("bike_id", "part_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [u for u in rows if u[param] == value]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([usage_view(u) for u in page], pagination=pg)


@bp.post("/usage-logs/<usage_id>/void")
def void_usage(usage_id):
    require_roles("ProgramDirector")
    body = get_body()
    validate_payload(body, {"reason": {"type": "string"}})
    usage = db.part_usages.get(usage_id)
    if usage is None:
        raise ApiError("ERR_NOT_FOUND", f"PartUsage {usage_id} does not exist")
    if usage["status"] != "COMMITTED":
        raise ApiError("ERR_USAGE_NOT_COMMITTED", "Only a COMMITTED usage can be voided")
    usage["status"] = "VOIDED"
    usage["void_reason"] = body.get("reason")
    part = db.parts.get(usage["part_id"])
    if part is not None:
        part["quantity_on_hand"] += usage["quantity"]
        touch(part)
        recompute_part_low_stock(part)
    bike = db.bikes.get(usage["bike_id"])
    if bike is not None:
        recompute_bike_parts_cost(bike)
        touch(bike)
    return success(usage_view(usage))


# ---------------------------------------------------------------------------
# Scrap
# ---------------------------------------------------------------------------

@bp.post("/bikes/<bike_id>/scrap-tickets")
def create_scrap_ticket(bike_id):
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {
        "material": {"type": "string", "required": True, "enum": MATERIALS},
        "weight_kg": {"type": "number", "required": True},
        "recycler_name": {"type": "string", "required": True},
    })
    bike = _get_bike(bike_id)
    if bike["status"] not in ("HARVESTED", "SCRAP_PENDING"):
        raise ApiError("ERR_INVALID_STATE", "Scrap tickets require a HARVESTED or SCRAP_PENDING bike")
    if any(t["bike_id"] == bike["id"] and t["status"] == "OPEN" for t in db.scrap_tickets.values()):
        raise ApiError("ERR_SCRAP_TICKET_OPEN", "Bike already has an OPEN scrap ticket")
    weight = body["weight_kg"]
    if not (weight > 0 and weight <= 100):
        raise ApiError("ERR_WEIGHT_INVALID", "weight_kg must be within (0, 100]")

    ticket = make_common()
    ticket.update({
        "bike_id": bike["id"],
        "material": body["material"],
        "weight_kg": weight,
        "recycler_name": body["recycler_name"],
        "payout_cents": scrap_payout(body["material"], weight),
        "status": "OPEN",
        "picked_up_at": None,
    })
    db.scrap_tickets[ticket["id"]] = ticket
    if bike["status"] == "HARVESTED":
        bike["status"] = "SCRAP_PENDING"
        touch(bike)
    return success(ticket_view(ticket), status=201)


@bp.get("/scrap-tickets/statement")
def scrap_statement():
    require_roles("ShopCoordinator", "ProgramDirector")
    from services.core import parse_month_param, month_of
    raw_month = request.args.get("month")
    if raw_month is None:
        year, month = db.now().year, db.now().month
    else:
        year, month = parse_month_param(raw_month)
    tickets = [
        t for t in db.scrap_tickets.values()
        if t["status"] == "PICKED_UP" and t["picked_up_at"] is not None
        and month_of(_parse_iso(t["picked_up_at"])) == (year, month)
    ]
    return success({
        "month": f"{year:04d}-{month:02d}",
        "ticket_count": len(tickets),
        "total_payout_cents": sum(t["payout_cents"] for t in tickets),
    })


@bp.get("/scrap-tickets/<ticket_id>")
def get_scrap_ticket(ticket_id):
    require_roles("ShopCoordinator", "ProgramDirector")
    ticket = db.scrap_tickets.get(ticket_id)
    if ticket is None:
        raise ApiError("ERR_NOT_FOUND", f"ScrapTicket {ticket_id} does not exist")
    return success(ticket_view(ticket))


@bp.get("/scrap-tickets")
def list_scrap_tickets():
    require_roles("ShopCoordinator", "ProgramDirector")
    from services.core import parse_month_param, month_of
    rows = list(db.scrap_tickets.values())
    for param in ("bike_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [t for t in rows if t[param] == value]
    raw_month = request.args.get("month")
    if raw_month is not None:
        year, month = parse_month_param(raw_month)
        rows = [
            t for t in rows
            if t["picked_up_at"] is not None
            and month_of(_parse_iso(t["picked_up_at"])) == (year, month)
        ]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([ticket_view(t) for t in page], pagination=pg)


@bp.post("/scrap-tickets/<ticket_id>/pick-up")
def pick_up_scrap_ticket(ticket_id):
    require_roles("ProgramDirector")
    ticket = db.scrap_tickets.get(ticket_id)
    if ticket is None:
        raise ApiError("ERR_NOT_FOUND", f"ScrapTicket {ticket_id} does not exist")
    if ticket["status"] != "OPEN":
        raise ApiError("ERR_TICKET_NOT_OPEN", "Only an OPEN ticket can be picked up")
    ticket["status"] = "PICKED_UP"
    ticket["picked_up_at"] = db.now_iso()
    touch(ticket)
    bike = db.bikes.get(ticket["bike_id"])
    if bike is not None and bike["status"] == "SCRAP_PENDING":
        bike["status"] = "SCRAPPED"
        touch(bike)
    return success(ticket_view(ticket))

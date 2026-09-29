"""Arbitration: the demand, the panel and the alternate strike, the case file,
witness coordination, the hearing, the award and remedy implementation."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from core import (
    ApiError, db, now, base_record, touch, ok, paginated, qp, order_by,
    authenticate, get_body, bad, add_days, floor_days, party_of, to_dec,
    req_string, opt_string, req_enum, opt_enum, req_int, opt_int, opt_number,
    req_dt, opt_dt, req_id, opt_id, opt_bool,
    ROLE_UNION_STEWARD, ROLE_ANALYST, ROLE_DIRECTOR, ROLE_ADMIN, READ_ROLES,
)
import derive
from derive import (
    GRIEVANCE_TERMINAL, PANEL_SOURCES, FILING_TYPES, WITNESS_TYPES, OFFER_PARTIES,
    AWARD_OUTCOMES, MAX_DAILY_RELEASE_HOURS, BRIEF_DAYS_AFTER_HEARING, PREP_RUNWAY_DAYS,
    RETAINER_DAYS, ENFORCEMENT_COUNSEL_CENTS,
    ser_demand, ser_strike, ser_assignment, ser_award,
)
import services

bp = Blueprint("arbitration", __name__)


# --------------------------------------------------------------------------
# Demanding arbitration (PRD 3.6)
# --------------------------------------------------------------------------
@bp.post("/grievances/<grievance_id>/arbitration-demands")
def demand_arbitration(grievance_id):
    user_id, role = authenticate([ROLE_UNION_STEWARD])
    grievance = services.find_grievance(grievance_id)
    services.require_filing_steward(grievance, user_id)
    body = get_body()

    panel_source = req_enum(body, "panel_source", PANEL_SOURCES)
    panel_size = req_int(body, "panel_size")
    expected_version = req_int(body, "expected_grievance_version")

    # ladder 8
    if expected_version != grievance["version"]:
        raise ApiError("ERR_STALE_GRIEVANCE_VERSION",
                       "expected_grievance_version does not match the grievance.")

    # ladder 9 — the two declared routes in
    instant = now()
    step3 = derive.step_at_number(grievance["id"], 3)
    deemed_denied_route = False
    if (grievance["status"] == "ANSWERED"
            and grievance["current_step"] == 3
            and step3 is not None
            and step3["status"] == "ANSWERED"):
        pass
    elif (grievance["status"] == "AWAITING_RESPONSE"
          and grievance["current_step"] == 3
          and step3 is not None
          and step3["status"] == "HELD"
          and step3["response_due_at"] is not None
          and instant > step3["response_due_at"]):
        deemed_denied_route = True
    else:
        raise ApiError("ERR_INVALID_GRIEVANCE_STATE",
                       "The grievance is not in a state from which arbitration may be demanded.")

    unit = db.bargaining_units[grievance["bargaining_unit_id"]]
    # ladder 10
    if derive.unit_status(unit) != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_EXPIRED", "The collective agreement has expired.")

    # ladder 16
    clause = db.contract_clauses[grievance["clause_id"]]
    if not clause["is_arbitrable"]:
        raise ApiError("ERR_CLAUSE_NOT_ARBITRABLE",
                       "The cited clause is not arbitrable.")

    # ladder 24
    if panel_size not in (3, 5, 7):
        raise ApiError("ERR_INVALID_PANEL_SIZE", "panel_size must be 3, 5 or 7.")

    # ladder 33 — the deadline anchors on the step-3 resolution instant, which
    # for the overdue route is its response_due_at.
    if deemed_denied_route:
        deadline = add_days(step3["response_due_at"], unit["arbitration_demand_days"])
    else:
        deadline = derive.arbitration_deadline_at(grievance)
    if deadline is not None and instant > deadline:
        raise ApiError("ERR_ARBITRATION_DEMAND_UNTIMELY",
                       "The arbitration demand window has closed.")

    if deemed_denied_route:
        step3["status"] = "DEEMED_DENIED"
        touch(step3)

    demand = base_record()
    demand.update({
        "grievance_id": grievance["id"],
        "selected_arbitrator_id": None,
        "demanded_at": instant,
        "demand_deadline_at": deadline,
        "panel_source": panel_source,
        "panel_size": panel_size,
        "panel_arbitrator_ids": [],
        "strike_turn": None,
        "strikes_taken": 0,
        "status": "DEMANDED",
        "prep_status": "PREP_NOT_STARTED",
        "exhibit_count": 0,
        "hearing_start_at": None,
        "hearing_end_at": None,
        "brief_due_at": None,
        "estimated_cost_cents": 0,
    })
    db.arbitration_demands[demand["id"]] = demand

    grievance["status"] = "ARBITRATION_DEMANDED"
    touch(grievance)
    if deemed_denied_route:
        grievance["timeliness_state"] = "EMPLOYER_DEFAULT"
    else:
        derive.refresh_timeliness(grievance)

    return ok(ser_demand(demand), 201)


@bp.get("/arbitration-demands/<demand_id>")
def read_demand(demand_id):
    authenticate(READ_ROLES)
    demand = services.find_demand(demand_id)
    return ok(ser_demand(demand))


@bp.get("/arbitration-demands")
def list_demands():
    authenticate(READ_ROLES)
    rows = list(db.arbitration_demands.values())
    for field in ("grievance_id", "selected_arbitrator_id", "status", "prep_status"):
        value = qp(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows = order_by(rows, "demanded_at", "created_at")
    return paginated(rows, ser_demand)


# --------------------------------------------------------------------------
# Panel issue and the alternate strike (PRD 3.6)
# --------------------------------------------------------------------------
@bp.post("/arbitration-demands/<demand_id>/request-panel")
def request_panel(demand_id):
    authenticate([ROLE_ADMIN])
    demand = services.find_demand(demand_id)

    if demand["status"] != "DEMANDED":
        raise ApiError("ERR_DEMAND_STATE_INVALID",
                       "A panel may only be issued on a demand standing at DEMANDED.")

    candidates = derive.panel_candidates(demand)
    if len(candidates) < demand["panel_size"]:
        raise ApiError("ERR_PANEL_POOL_INSUFFICIENT",
                       "Fewer eligible arbitrators exist than the requested panel size.")

    demand["panel_arbitrator_ids"] = [a["id"] for a in candidates[:demand["panel_size"]]]
    demand["status"] = "PANEL_ISSUED"
    demand["strike_turn"] = "UNION"
    demand["strikes_taken"] = 0
    touch(demand)
    return ok(ser_demand(demand))


@bp.get("/arbitration-demands/<demand_id>/panel-strikes")
def list_panel_strikes(demand_id):
    authenticate(READ_ROLES)
    demand = services.find_demand(demand_id)
    rows = derive.strikes_of(demand["id"])
    struck_by = qp("struck_by")
    if struck_by is not None:
        rows = [r for r in rows if r["struck_by"] == struck_by]
    rows = order_by(rows, "strike_order")
    return paginated(rows, ser_strike)


@bp.post("/arbitration-demands/<demand_id>/strikes")
def take_strike(demand_id):
    user_id, role = authenticate([ROLE_UNION_STEWARD, ROLE_DIRECTOR])
    demand = services.find_demand(demand_id)
    grievance = db.grievances[demand["grievance_id"]]
    if role == ROLE_UNION_STEWARD:
        services.require_filing_steward(grievance, user_id)

    body = get_body()
    arbitrator_id = req_id(body, "arbitrator_id")
    arbitrator = services.find_arbitrator(arbitrator_id)

    if demand["status"] not in ("PANEL_ISSUED", "STRIKING"):
        raise ApiError("ERR_DEMAND_STATE_INVALID",
                       "No strike may be taken from this demand state.")

    if party_of(role) != demand["strike_turn"]:
        raise ApiError("ERR_NOT_STRIKE_TURN", "It is not this party's turn to strike.")

    already_struck = {s["arbitrator_id"] for s in derive.strikes_of(demand["id"])}
    if arbitrator["id"] not in demand["panel_arbitrator_ids"] or \
            arbitrator["id"] in already_struck:
        raise ApiError("ERR_ARBITRATOR_NOT_ON_PANEL",
                       "The arbitrator is not an unstruck member of this panel.")

    strike = base_record(with_version=False)
    strike.update({
        "arbitration_demand_id": demand["id"],
        "arbitrator_id": arbitrator["id"],
        "struck_by": party_of(role),
        "strike_order": demand["strikes_taken"] + 1,
        "struck_by_user_id": user_id,
    })
    db.panel_strikes[strike["id"]] = strike

    remaining = demand["panel_size"] - demand["strikes_taken"] - 1
    demand["strikes_taken"] = demand["strikes_taken"] + 1

    if remaining > 1:
        demand["status"] = "STRIKING"
        demand["strike_turn"] = "EMPLOYER" if demand["strike_turn"] == "UNION" else "UNION"
        touch(demand)
    else:
        struck = {s["arbitrator_id"] for s in derive.strikes_of(demand["id"])}
        survivors = [a for a in demand["panel_arbitrator_ids"] if a not in struck]
        demand["status"] = "ARBITRATOR_SELECTED"
        demand["selected_arbitrator_id"] = survivors[0] if survivors else None
        demand["strike_turn"] = None
        touch(demand)

        selected = db.arbitrators.get(demand["selected_arbitrator_id"])
        if selected is not None:
            services.engage_arbitrator(selected)
            services.create_cost_entry(
                grievance["id"], "ARBITRATOR_FEE",
                selected["per_diem_cents"] * RETAINER_DAYS, "SPLIT", "SYSTEM")

    return ok(ser_strike(strike), 201)


# --------------------------------------------------------------------------
# Booking the hearing (PRD 3.8)
# --------------------------------------------------------------------------
@bp.post("/arbitration-demands/<demand_id>/schedule-hearing")
def schedule_hearing(demand_id):
    authenticate([ROLE_ADMIN])
    demand = services.find_demand(demand_id)
    body = get_body()

    hearing_start = req_dt(body, "hearing_start_at")
    hearing_end = req_dt(body, "hearing_end_at")

    if demand["status"] != "ARBITRATOR_SELECTED":
        raise ApiError("ERR_DEMAND_STATE_INVALID",
                       "A hearing may only be booked once an arbitrator is selected.")

    arbitrator = db.arbitrators[demand["selected_arbitrator_id"]]
    if derive.arbitrator_status(arbitrator) == "INACTIVE":
        raise ApiError("ERR_ARBITRATOR_INACTIVE", "The selected arbitrator is inactive.")

    if hearing_end <= hearing_start:
        raise ApiError("ERR_INVALID_HEARING_WINDOW",
                       "hearing_end_at must be strictly after hearing_start_at.")

    buffer = timedelta(hours=arbitrator["travel_buffer_hours"])
    for other in db.arbitration_demands.values():
        if other["id"] == demand["id"]:
            continue
        if other["selected_arbitrator_id"] != arbitrator["id"]:
            continue
        if other["status"] not in ("HEARING_SCHEDULED", "HEARD", "AWARDED"):
            continue
        if other["hearing_start_at"] is None or other["hearing_end_at"] is None:
            continue
        expanded_start = other["hearing_start_at"] - buffer
        expanded_end = other["hearing_end_at"] + buffer
        # closed intervals: touching endpoints are a conflict
        if expanded_start <= hearing_end and hearing_start <= expanded_end:
            raise ApiError("ERR_ARBITRATOR_UNAVAILABLE",
                           "The arbitrator has a buffered calendar conflict.")

    demand["hearing_start_at"] = hearing_start
    demand["hearing_end_at"] = hearing_end
    demand["brief_due_at"] = add_days(hearing_end, BRIEF_DAYS_AFTER_HEARING)
    demand["status"] = "HEARING_SCHEDULED"
    if demand["prep_status"] == "PREP_NOT_STARTED" and \
            (hearing_start - now()) < timedelta(days=PREP_RUNWAY_DAYS):
        demand["prep_status"] = "PREP_DEFICIENT"
    demand["estimated_cost_cents"] = derive.estimated_case_cost(demand, arbitrator)
    touch(demand)
    return ok(ser_demand(demand))


# --------------------------------------------------------------------------
# Case-file preparation (PRD 3.7)
# --------------------------------------------------------------------------
@bp.post("/arbitration-demands/<demand_id>/prep-filings")
def file_prep(demand_id):
    authenticate([ROLE_ANALYST])
    demand = services.find_demand(demand_id)
    body = get_body()

    filing_type = req_enum(body, "filing_type", FILING_TYPES)
    exhibit_count = None
    if filing_type == "EXHIBIT_LIST":
        exhibit_count = req_int(body, "exhibit_count", minimum=1)
    else:
        opt_int(body, "exhibit_count", None, minimum=1)

    if filing_type == "EXHIBIT_LIST":
        if demand["status"] not in ("ARBITRATOR_SELECTED", "HEARING_SCHEDULED", "HEARD"):
            raise ApiError("ERR_DEMAND_STATE_INVALID",
                           "An exhibit list may not be filed from this demand state.")
        if demand["prep_status"] not in ("PREP_NOT_STARTED", "PREP_DEFICIENT"):
            raise ApiError("ERR_DEMAND_STATE_INVALID",
                           "The case file has already moved past the exhibits stage.")
        demand["exhibit_count"] = exhibit_count
        demand["prep_status"] = "EXHIBITS_FILED"
    elif filing_type == "BRIEF":
        if demand["prep_status"] != "EXHIBITS_FILED":
            raise ApiError("ERR_DEMAND_STATE_INVALID",
                           "A brief may only be filed once exhibits are filed.")
        demand["prep_status"] = "BRIEFS_FILED"
    else:
        if demand["prep_status"] != "BRIEFS_FILED":
            raise ApiError("ERR_DEMAND_STATE_INVALID",
                           "A stipulation may only be filed once briefs are filed.")
        if not any(w["status"] == "CONFIRMED" for w in derive.assignments_of(demand["id"])):
            raise ApiError("ERR_DEMAND_STATE_INVALID",
                           "At least one witness must be CONFIRMED before a stipulation.")
        demand["prep_status"] = "PREP_READY"

    touch(demand)
    return ok(ser_demand(demand))


# --------------------------------------------------------------------------
# Witness coordination (PRD 3.7)
# --------------------------------------------------------------------------
@bp.post("/arbitration-demands/<demand_id>/witness-assignments")
def call_witness(demand_id):
    authenticate([ROLE_UNION_STEWARD, ROLE_ANALYST])
    demand = services.find_demand(demand_id)
    grievance = db.grievances[demand["grievance_id"]]
    body = get_body()

    employee_id = req_id(body, "employee_id")
    witness_type = req_enum(body, "witness_type", WITNESS_TYPES)
    called_by = req_enum(body, "called_by", OFFER_PARTIES)
    slot_start = req_dt(body, "slot_start_at")
    slot_end = req_dt(body, "slot_end_at")
    if slot_end <= slot_start:
        bad("slot_end_at", "must be strictly after slot_start_at")

    employee = services.find_employee(employee_id)

    if demand["status"] not in ("ARBITRATOR_SELECTED", "HEARING_SCHEDULED"):
        raise ApiError("ERR_DEMAND_STATE_INVALID",
                       "Witnesses may only be called once an arbitrator is selected.")

    # ladder 14 — the union's advocate does not also become the union's evidence
    if employee["id"] == grievance["filed_by_steward_employee_id"]:
        raise ApiError("ERR_ADVOCATE_WITNESS_CONFLICT",
                       "The filing steward may not be called as a witness.")

    # ladder 15
    if employee["employment_status"] == "TERMINATED":
        raise ApiError("ERR_WITNESS_NOT_EMPLOYED",
                       "A terminated employee may not be called as a witness.")

    # ladder 36 — half-open slots, no buffer
    for other in db.witness_assignments.values():
        if other["employee_id"] != employee["id"]:
            continue
        if other["status"] not in ("INVITED", "CONFIRMED", "TESTIFIED"):
            continue
        if other["slot_start_at"] < slot_end and slot_start < other["slot_end_at"]:
            raise ApiError("ERR_WITNESS_SLOT_CONFLICT",
                           "The testimony slot overlaps another slot of the same person.")

    release_hours, release_cost = derive.witness_release(slot_start, slot_end, employee)

    # ladder 37 — aggregate daily release capacity
    existing = derive.daily_release_hours(employee["id"], slot_start.date())
    if existing + release_hours > MAX_DAILY_RELEASE_HOURS:
        raise ApiError("ERR_WITNESS_RELEASE_CAP_EXCEEDED",
                       "The person's daily release capacity would be exceeded.")

    assignment = base_record()
    assignment.update({
        "arbitration_demand_id": demand["id"],
        "employee_id": employee["id"],
        "witness_type": witness_type,
        "called_by": called_by,
        "slot_start_at": slot_start,
        "slot_end_at": slot_end,
        "release_hours": release_hours,
        "release_cost_cents": release_cost,
        "status": "INVITED",
        "confirmed_by_user_id": None,
        "release_cost_entry_id": None,
    })
    db.witness_assignments[assignment["id"]] = assignment
    return ok(ser_assignment(assignment), 201)


@bp.get("/arbitration-demands/<demand_id>/witness-assignments")
def list_demand_witnesses(demand_id):
    authenticate(READ_ROLES)
    demand = services.find_demand(demand_id)
    rows = derive.assignments_of(demand["id"])
    for field in ("status", "called_by"):
        value = qp(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows = order_by(rows, "slot_start_at", "created_at")
    return paginated(rows, ser_assignment)


@bp.post("/witness-assignments/<assignment_id>/confirm")
def confirm_witness(assignment_id):
    user_id, role = authenticate([ROLE_DIRECTOR])
    assignment = services.find_assignment(assignment_id)
    demand = db.arbitration_demands[assignment["arbitration_demand_id"]]

    if assignment["status"] != "INVITED":
        raise ApiError("ERR_DEMAND_STATE_INVALID",
                       "Only an INVITED witness assignment may be confirmed.")
    if demand["status"] not in ("ARBITRATOR_SELECTED", "HEARING_SCHEDULED"):
        raise ApiError("ERR_DEMAND_STATE_INVALID",
                       "The demand is not in a state that permits witness confirmation.")

    entry = services.create_cost_entry(
        demand["grievance_id"], "RELEASE_TIME", assignment["release_cost_cents"],
        "UNION", "SYSTEM")

    assignment["status"] = "CONFIRMED"
    assignment["confirmed_by_user_id"] = user_id
    assignment["release_cost_entry_id"] = entry["id"]
    touch(assignment)
    return ok(ser_assignment(assignment))


# --------------------------------------------------------------------------
# The award (PRD 3.8)
# --------------------------------------------------------------------------
@bp.post("/arbitration-demands/<demand_id>/awards")
def record_award(demand_id):
    authenticate([ROLE_ADMIN])
    demand = services.find_demand(demand_id)
    body = get_body()
    instant = now()

    outcome = req_enum(body, "outcome", AWARD_OUTCOMES)
    sustained_fraction = opt_int(body, "sustained_fraction_bps", 10000, minimum=0, maximum=10000)
    if outcome == "SUSTAINED" and sustained_fraction != 10000:
        bad("sustained_fraction_bps", "must be exactly 10000 for a SUSTAINED outcome")
    if outcome == "DENIED" and sustained_fraction != 0:
        bad("sustained_fraction_bps", "must be exactly 0 for a DENIED outcome")
    if outcome == "SPLIT" and not (0 < sustained_fraction < 10000):
        bad("sustained_fraction_bps", "must be strictly between 0 and 10000 for a SPLIT outcome")
    back_pay_hours = opt_number(body, "back_pay_hours_ordered", Decimal(0), minimum=0)
    mitigation = opt_int(body, "mitigation_offset_cents", 0, minimum=0)
    interest_rate = opt_int(body, "interest_rate_bps", 0, minimum=0)
    interest_start = opt_dt(body, "interest_accrual_start")
    if interest_rate > 0 and interest_start is None:
        bad("interest_accrual_start", "is required when interest_rate_bps is greater than 0")
    if interest_start is not None and interest_start > instant:
        bad("interest_accrual_start", "must be at or before the award's issued_at")
    reinstatement_ordered = opt_bool(body, "reinstatement_ordered", False)
    remedy_deadline_days = opt_int(body, "remedy_deadline_days", 30, minimum=1)

    # ladder 9 — a second award is reported against the award, not the demand
    if derive.award_of(demand["id"]) is not None:
        raise ApiError("ERR_AWARD_STATE_INVALID", "An award already exists on this demand.")
    if demand["status"] != "HEARING_SCHEDULED":
        raise ApiError("ERR_DEMAND_STATE_INVALID",
                       "An award may only be recorded on a demand with a scheduled hearing.")

    # ladder 12
    if demand["hearing_end_at"] is None or instant < demand["hearing_end_at"]:
        raise ApiError("ERR_HEARING_NOT_CONCLUDED", "The hearing has not concluded.")

    # ladder 26
    if demand["prep_status"] not in ("BRIEFS_FILED", "PREP_READY"):
        raise ApiError("ERR_PREP_INCOMPLETE",
                       "The case file has not reached the briefs stage.")

    grievance = db.grievances[demand["grievance_id"]]
    grievant = db.employees[grievance["grievant_id"]]

    award = base_record()
    award.update({
        "arbitration_demand_id": demand["id"],
        "issued_at": instant,
        "outcome": outcome,
        "sustained_fraction_bps": sustained_fraction,
        "back_pay_hours_ordered": back_pay_hours,
        "mitigation_offset_cents": mitigation,
        "interest_rate_bps": interest_rate,
        "interest_accrual_start": interest_start,
        "reinstatement_ordered": reinstatement_ordered,
        "remedy_deadline_days": remedy_deadline_days,
        "implemented_cents": 0,
        "implementation_deadline_at": add_days(instant, remedy_deadline_days),
        "status": "ISSUED",
    })
    gross, net = derive.award_remedy(award, grievant, grievance)
    award["gross_remedy_cents"] = gross
    award["net_remedy_cents"] = net
    db.awards[award["id"]] = award

    # the demand walks HEARING_SCHEDULED -> HEARD -> AWARDED inside this request
    demand["status"] = "AWARDED"
    touch(demand)

    arbitrator = db.arbitrators.get(demand["selected_arbitrator_id"])
    if arbitrator is not None:
        services.release_arbitrator(arbitrator)

    for assignment in derive.assignments_of(demand["id"]):
        if assignment["status"] == "CONFIRMED":
            inside = (assignment["slot_start_at"] >= demand["hearing_start_at"]
                      and assignment["slot_end_at"] <= demand["hearing_end_at"])
            if inside:
                assignment["status"] = "TESTIFIED"
                touch(assignment)
            else:
                assignment["status"] = "NO_SHOW"
                touch(assignment)
                entry = db.cost_entries.get(assignment["release_cost_entry_id"])
                if entry is not None and entry["status"] == "POSTED":
                    services.void_cost_entry(entry, None, None)
        elif assignment["status"] == "INVITED":
            assignment["status"] = "EXCUSED"
            touch(assignment)

    if net > 0 or reinstatement_ordered:
        award["status"] = "IMPLEMENTATION_PENDING"
        grievance["status"] = "AWARDED"
        touch(grievance)
        derive.refresh_timeliness(grievance)
    else:
        award["status"] = "IMPLEMENTED"
        grievance["status"] = "AWARDED"
        derive.refresh_timeliness(grievance)
        grievance["status"] = "CLOSED"
        services.void_open_offers(grievance)
        touch(grievance)

    return ok(ser_award(award), 201)


@bp.get("/arbitration-demands/<demand_id>/awards")
def list_demand_awards(demand_id):
    authenticate(READ_ROLES)
    demand = services.find_demand(demand_id)
    rows = [a for a in db.awards.values() if a["arbitration_demand_id"] == demand["id"]]
    rows = order_by(rows, "created_at")
    return paginated(rows, ser_award)


@bp.get("/awards/<award_id>")
def read_award(award_id):
    authenticate(READ_ROLES)
    award = services.find_award(award_id)
    return ok(ser_award(award))


@bp.post("/awards/<award_id>/implement")
def implement_award(award_id):
    user_id, role = authenticate([ROLE_ANALYST])
    award = services.find_award(award_id)
    demand = db.arbitration_demands[award["arbitration_demand_id"]]
    grievance = db.grievances[demand["grievance_id"]]
    grievant = db.employees[grievance["grievant_id"]]
    body = get_body()

    paid_cents = req_int(body, "paid_cents", minimum=0)
    reinstatement_date = opt_dt(body, "reinstatement_effective_date")
    if reinstatement_date is not None and not award["reinstatement_ordered"]:
        bad("reinstatement_effective_date",
            "may only be supplied for an award that ordered reinstatement")

    if award["status"] == "IMPLEMENTED":
        raise ApiError("ERR_AWARD_STATE_INVALID", "The award is already implemented.")

    remaining = award["net_remedy_cents"] - award["implemented_cents"]
    if paid_cents > remaining:
        raise ApiError("ERR_OVERPAYMENT",
                       "The payment exceeds the award's remaining net remedy.")

    if reinstatement_date is not None:
        grievant["employment_status"] = "REINSTATED"
        touch(grievant)

    total = award["implemented_cents"] + paid_cents
    reinstatement_ok = (not award["reinstatement_ordered"]
                        or grievant["employment_status"] == "REINSTATED")

    if total == award["net_remedy_cents"] and reinstatement_ok:
        award["implemented_cents"] = award["net_remedy_cents"]
        award["status"] = "IMPLEMENTED"
        touch(award)
        services.close_grievance(grievance)
    elif now() > award["implementation_deadline_at"] and total < award["net_remedy_cents"]:
        award["implemented_cents"] = total
        award["status"] = "COMPLIANCE_DISPUTED"
        touch(award)
        services.create_cost_entry(
            grievance["id"], "COUNSEL", ENFORCEMENT_COUNSEL_CENTS, "EMPLOYER", "SYSTEM")
    else:
        award["implemented_cents"] = total
        award["status"] = "PARTIALLY_IMPLEMENTED"
        touch(award)

    return ok(ser_award(award))

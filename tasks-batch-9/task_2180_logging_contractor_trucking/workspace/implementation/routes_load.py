"""Load dispatch, the haul, the mill scale ticket, certification, rejection and
the rehaul selector."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import derive
from core import (
    D,
    GRADES,
    PERMIT_RANK,
    REJECT_REASONS,
    RESERVING_STATUSES,
    SEASON_MONTHS,
    SPECIES,
    body,
    clock,
    created,
    db,
    endpoint,
    fail,
    new_record,
    ok,
    ordered,
    paginated,
    parse_instant,
    req_datetime,
    req_enum,
    req_int,
    req_num,
    req_str,
    rhu,
    to_date,
    tons,
    touch,
)

bp = Blueprint("loads", __name__)

ALL_ROLES = (
    "PlatformAdmin",
    "OperationsManager",
    "MillScaler",
    "SafetyOfficer",
    "SettlementAccountant",
    "HaulContractor",
)


def seasonal_gate_open(access_class):
    months = SEASON_MONTHS[access_class]
    if months is None:
        return True
    return clock.now.month in months


def build_load(
    tract,
    contract,
    route,
    truck,
    declared_species,
    declared_grade,
    estimated_net_tons,
    depart_at,
    arrive_at,
    rehaul_of_load_id=None,
):
    """Create and store a Load, writing the provisional haul-pay figures."""
    provisional = calc.load_haul_pay(
        estimated_net_tons, route["distance_miles"], wait_minutes=0, regrade_applies=False
    )
    rec = new_record()
    rec.update(
        {
            "tract_id": tract["id"],
            "mill_contract_id": contract["id"],
            "haul_route_id": route["id"],
            "truck_id": truck["id"],
            "haul_contractor_id": truck["haul_contractor_id"],
            "rehaul_of_load_id": rehaul_of_load_id,
            "declared_species": declared_species,
            "declared_grade": declared_grade,
            "estimated_net_tons": tons(estimated_net_tons),
            "scheduled_depart_at": depart_at,
            "scheduled_arrive_at": arrive_at,
            "dispatch_status": "DISPATCHED",
            "settlement_status": "UNSETTLED",
            "rehaul_status": "NONE",
            "departed_at": None,
            "arrived_at": None,
            "rejected_on": None,
            "settlement_event_on": None,
            "wait_minutes": None,
            "rate_cents_per_ton_mile": provisional["rate_cents_per_ton_mile"],
            "provisional_haul_pay_cents": provisional["haul_pay_cents"],
            "line_haul_cents": None,
            "fuel_surcharge_cents": None,
            "demurrage_cents": None,
            "incentive_cents": None,
            "regrade_adjustment_cents": None,
            "final_haul_pay_cents": None,
        }
    )
    db.loads[rec["id"]] = rec
    derive.recompute_contract(contract)
    return rec


# ---------------------------------------------------------------------------
# Load dispatch
# ---------------------------------------------------------------------------
@bp.route("/loads", methods=["POST"])
@endpoint("OperationsManager")
def create_load(caller):
    payload = body()
    tract_id = req_str(payload, "tract_id")
    mill_contract_id = req_str(payload, "mill_contract_id")
    haul_route_id = req_str(payload, "haul_route_id")
    truck_id = req_str(payload, "truck_id")
    declared_species = req_enum(payload, "declared_species", SPECIES)
    declared_grade = req_enum(payload, "declared_grade", GRADES)
    estimated_net_tons = req_num(
        payload, "estimated_net_tons", minimum=0, exclusive_min=True, max_places=2
    )
    depart_at = req_datetime(payload, "scheduled_depart_at")
    arrive_at = req_datetime(payload, "scheduled_arrive_at")
    if arrive_at <= depart_at:
        fail("ERR_VALIDATION", "scheduled_arrive_at must be strictly after scheduled_depart_at")

    # Rung 4 -- body foreign keys resolve in declared input order.
    tract = db.tracts.get(tract_id)
    if tract is None:
        fail("ERR_TRACT_NOT_FOUND", "no tract %s" % tract_id)
    contract = db.mill_contracts.get(mill_contract_id)
    if contract is None:
        fail("ERR_MILL_CONTRACT_NOT_FOUND", "no mill contract %s" % mill_contract_id)
    route = db.haul_routes.get(haul_route_id)
    if route is None:
        fail("ERR_HAUL_ROUTE_NOT_FOUND", "no haul route %s" % haul_route_id)
    truck = db.trucks.get(truck_id)
    if truck is None:
        fail("ERR_TRUCK_NOT_FOUND", "no truck %s" % truck_id)

    contractor = db.haul_contractors.get(truck["haul_contractor_id"])

    # Rung 9 -- carrier compliance status, deliberately above the truck rung.
    if contractor is None or contractor["compliance_status"] == "SUSPENDED":
        fail("ERR_CONTRACTOR_NOT_COMPLIANT", "the load's carrier is SUSPENDED")

    # Rung 11 -- cross-entity state, in the order PRD 3.6 gives.
    if tract["status"] != "ACTIVE":
        fail("ERR_TRACT_NOT_ACTIVE", "the tract is not ACTIVE")
    if contract["status"] != "OPEN":
        fail("ERR_INVALID_MILL_CONTRACT_STATE", "the mill contract is not OPEN")
    mill = db.mills.get(contract["mill_id"])
    if mill is None or mill["receiving_status"] != "OPEN":
        fail("ERR_MILL_NOT_RECEIVING", "the mill yard is not receiving")
    if route["status"] not in ("OPEN", "POSTED_RESTRICTED"):
        fail("ERR_ROUTE_NOT_OPEN", "the haul route is CLOSED")
    if derive.truck_status(truck) == "OUT_OF_SERVICE":
        fail("ERR_TRUCK_OUT_OF_SERVICE", "the truck is OUT_OF_SERVICE")

    # Rung 12 -- safety and compliance thresholds.
    if derive.rolling_compliance_score(contractor["id"]) < calc.MIN_DISPATCH_SCORE:
        fail("ERR_COMPLIANCE_SCORE_TOO_LOW", "the carrier's rolling compliance score is below 70")

    # Rung 13 -- temporal windows.
    if not seasonal_gate_open(tract["access_class"]):
        fail("ERR_SEASONAL_ACCESS_CLOSED", "the tract's access class forbids this calendar month")
    for existing in ordered(derive.loads_of_truck(truck["id"])):
        if existing["dispatch_status"] not in RESERVING_STATUSES:
            continue
        existing_depart = parse_instant(existing["scheduled_depart_at"])
        existing_arrive = parse_instant(existing["scheduled_arrive_at"])
        if depart_at <= existing_arrive and arrive_at >= existing_depart:
            fail("ERR_TRUCK_WINDOW_CONFLICT", "the truck is already occupied over this interval")
    today = clock.date()
    if not (to_date(contract["period_start"]) <= today <= to_date(contract["period_end"])):
        fail("ERR_CONTRACT_PERIOD_CLOSED", "the clock date falls outside the contract period")

    # Rung 14 -- physical and referential constraints.
    if PERMIT_RANK[truck["permit_class"]] < PERMIT_RANK[route["permit_class_required"]]:
        fail("ERR_PERMIT_CLASS_INSUFFICIENT", "the truck's permit rank is below the route requirement")
    if route["tract_id"] != tract["id"] or route["mill_id"] != contract["mill_id"]:
        fail("ERR_ROUTE_TRACT_MILL_MISMATCH", "the route does not connect this tract to this mill")
    if declared_species != contract["species"] or declared_grade != contract["grade"]:
        fail("ERR_SPECIES_GRADE_MISMATCH", "declared species/grade do not match the contract")

    # Rung 15 -- fiscal limits.  Exact equality is admitted.
    if tons(estimated_net_tons) > derive.contract_available_tons(contract):
        fail("ERR_QUOTA_EXCEEDED", "estimated_net_tons exceeds the contract's available_tons")

    rec = build_load(
        tract,
        contract,
        route,
        truck,
        declared_species,
        declared_grade,
        estimated_net_tons,
        payload["scheduled_depart_at"],
        payload["scheduled_arrive_at"],
    )
    return created(derive.load_json(rec))


@bp.route("/loads/<id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_load(caller, id):
    rec = db.loads.get(id)
    if rec is None:
        fail("ERR_LOAD_NOT_FOUND", "no load %s" % id)
    return ok(derive.load_json(rec))


@bp.route("/loads", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_loads(caller):
    records = ordered(list(db.loads.values()))
    for key in (
        "tract_id",
        "mill_contract_id",
        "haul_route_id",
        "truck_id",
        "haul_contractor_id",
        "rehaul_of_load_id",
        "dispatch_status",
        "settlement_status",
    ):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    return paginated(records, derive.load_json)


@bp.route("/loads/<id>/depart", methods=["POST"])
@endpoint("HaulContractor")
def depart_load(caller, id):
    rec = db.loads.get(id)
    if rec is None:
        fail("ERR_LOAD_NOT_FOUND", "no load %s" % id)
    if caller.user_id != rec["haul_contractor_id"]:
        fail("ERR_CONTRACTOR_NOT_OWNER", "the load belongs to a different carrier")
    if rec["dispatch_status"] != "DISPATCHED":
        fail("ERR_INVALID_LOAD_STATE", "only a DISPATCHED load may depart")
    truck = db.trucks.get(rec["truck_id"])
    if truck is not None and derive.truck_status(truck) == "OUT_OF_SERVICE":
        fail("ERR_TRUCK_OUT_OF_SERVICE", "the truck is OUT_OF_SERVICE")
    rec["dispatch_status"] = "IN_TRANSIT"
    rec["departed_at"] = clock.iso()
    touch(rec)
    return ok(derive.load_json(rec))


@bp.route("/loads/<id>/arrive", methods=["POST"])
@endpoint("HaulContractor")
def arrive_load(caller, id):
    rec = db.loads.get(id)
    if rec is None:
        fail("ERR_LOAD_NOT_FOUND", "no load %s" % id)
    if caller.user_id != rec["haul_contractor_id"]:
        fail("ERR_CONTRACTOR_NOT_OWNER", "the load belongs to a different carrier")
    if rec["dispatch_status"] != "IN_TRANSIT":
        fail("ERR_INVALID_LOAD_STATE", "only an IN_TRANSIT load may arrive")
    rec["dispatch_status"] = "AT_MILL"
    rec["arrived_at"] = clock.iso()
    touch(rec)
    return ok(derive.load_json(rec))


@bp.route("/loads/<id>/cancel", methods=["POST"])
@endpoint("OperationsManager")
def cancel_load_endpoint(caller, id):
    payload = body()
    req_str(payload, "reason", 1, 500)
    rec = db.loads.get(id)
    if rec is None:
        fail("ERR_LOAD_NOT_FOUND", "no load %s" % id)
    if rec["dispatch_status"] not in ("DISPATCHED", "IN_TRANSIT"):
        fail("ERR_INVALID_LOAD_STATE", "only a DISPATCHED or IN_TRANSIT load may be cancelled")
    derive.cancel_load(rec)
    return ok(derive.load_json(rec))


# ---------------------------------------------------------------------------
# DeliveryTicket
# ---------------------------------------------------------------------------
def ticket_mill_id(load):
    contract = db.mill_contracts.get(load["mill_contract_id"])
    return contract["mill_id"] if contract else None


@bp.route("/loads/<id>/delivery-tickets", methods=["POST"])
@endpoint("MillScaler")
def create_delivery_ticket(caller, id):
    payload = body()
    gross_weight_lbs = req_int(payload, "gross_weight_lbs", minimum=0, maximum=200000)
    defect_pct = req_num(payload, "defect_deduction_pct", minimum=0, maximum="0.50")
    scaled_species = req_enum(payload, "scaled_species", SPECIES)
    scaled_grade = req_enum(payload, "scaled_grade", GRADES)
    load = db.loads.get(id)
    if load is None:
        fail("ERR_LOAD_NOT_FOUND", "no load %s" % id)
    mill_id = ticket_mill_id(load)
    if caller.user_id != mill_id:
        fail("ERR_SCALER_MILL_MISMATCH", "scaler may only scale loads bound for its own mill")
    if load["dispatch_status"] != "AT_MILL":
        fail("ERR_INVALID_LOAD_STATE", "only a load AT_MILL may be scaled")
    if derive.live_ticket_for_load(load["id"]) is not None:
        fail("ERR_INVALID_LOAD_STATE", "the load already carries a DRAFT or CERTIFIED ticket")

    route = db.haul_routes.get(load["haul_route_id"])
    truck = db.trucks.get(load["truck_id"])
    max_allowed = calc.effective_max_gross_weight(route, truck, clock.date())
    if gross_weight_lbs > max_allowed:
        fail("ERR_OVERWEIGHT_LOAD", "gross_weight_lbs exceeds max_allowed_gross_lbs")
    net_weight_lbs, defect_lbs, payable_lbs, net_tons = calc.ticket_net_tons(
        gross_weight_lbs, truck["tare_weight_lbs"], defect_pct
    )
    if net_tons <= 0:
        fail("ERR_ZERO_NET_TONS", "the computed net_tons is not greater than 0.00")

    rec = new_record()
    rec.update(
        {
            "load_id": load["id"],
            "mill_id": mill_id,
            "gross_weight_lbs": gross_weight_lbs,
            "tare_weight_lbs": truck["tare_weight_lbs"],
            "net_weight_lbs": net_weight_lbs,
            "defect_deduction_pct": defect_pct,
            "defect_deducted_lbs": defect_lbs,
            "payable_lbs": payable_lbs,
            "net_tons": net_tons,
            "max_allowed_gross_lbs": max_allowed,
            "scaled_species": scaled_species,
            "scaled_grade": scaled_grade,
            "ticket_status": "DRAFT",
            "certified_at": None,
            "certified_by_user_id": None,
            "reject_reason": None,
        }
    )
    db.delivery_tickets[rec["id"]] = rec
    return created(derive.delivery_ticket_json(rec))


@bp.route("/delivery-tickets/<id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_delivery_ticket(caller, id):
    rec = db.delivery_tickets.get(id)
    if rec is None:
        fail("ERR_DELIVERY_TICKET_NOT_FOUND", "no delivery ticket %s" % id)
    return ok(derive.delivery_ticket_json(rec))


@bp.route("/delivery-tickets", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_delivery_tickets(caller):
    records = ordered(list(db.delivery_tickets.values()))
    for key in ("load_id", "mill_id", "ticket_status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    return paginated(records, derive.delivery_ticket_json)


@bp.route("/delivery-tickets/<id>/certify", methods=["POST"])
@endpoint("MillScaler")
def certify_delivery_ticket(caller, id):
    ticket = db.delivery_tickets.get(id)
    if ticket is None:
        fail("ERR_DELIVERY_TICKET_NOT_FOUND", "no delivery ticket %s" % id)
    if caller.user_id != ticket["mill_id"]:
        fail("ERR_SCALER_MILL_MISMATCH", "scaler may only act on its own mill's tickets")
    if ticket["ticket_status"] != "DRAFT":
        fail("ERR_INVALID_TICKET_STATE", "only a DRAFT ticket may be certified")
    load = db.loads.get(ticket["load_id"])
    if load is None or load["dispatch_status"] != "AT_MILL":
        fail("ERR_INVALID_LOAD_STATE", "the ticket's load is not AT_MILL")
    contract = db.mill_contracts.get(load["mill_contract_id"])

    # Rung 15 -- the overrun gate.
    delivered_after = tons(derive.contract_delivered_tons(contract) + D(ticket["net_tons"]))
    ceiling = tons(D(contract["quota_tons"]) * (D(1) + D(contract["overrun_tolerance_pct"])))
    if delivered_after > ceiling:
        fail("ERR_OVERRUN_TOLERANCE_EXCEEDED", "certification would breach the overrun tolerance")

    # Hop 1
    certified_at = clock.iso()
    ticket["ticket_status"] = "CERTIFIED"
    ticket["certified_at"] = certified_at
    ticket["certified_by_user_id"] = caller.user_id
    touch(ticket)

    # Hop 2 -- final-variant haul pay on the load, plus the settlement axis.
    route = db.haul_routes.get(load["haul_route_id"])
    arrived_at = parse_instant(load["arrived_at"]) if load["arrived_at"] else None
    certified_dt = parse_instant(certified_at)
    if arrived_at is None:
        wait_minutes = 0
    else:
        wait_minutes = int((certified_dt - arrived_at).total_seconds() // 60)
        if wait_minutes < 0:
            wait_minutes = 0
    regrade_applies = ticket["scaled_grade"] != load["declared_grade"]
    final = calc.load_haul_pay(
        ticket["net_tons"], route["distance_miles"], wait_minutes, regrade_applies
    )
    load["dispatch_status"] = "DELIVERED"
    load["wait_minutes"] = wait_minutes
    load["rate_cents_per_ton_mile"] = final["rate_cents_per_ton_mile"]
    load["line_haul_cents"] = final["line_haul_cents"]
    load["fuel_surcharge_cents"] = final["fuel_surcharge_cents"]
    load["demurrage_cents"] = final["demurrage_cents"]
    load["incentive_cents"] = final["incentive_cents"]
    load["regrade_adjustment_cents"] = final["regrade_adjustment_cents"]
    load["final_haul_pay_cents"] = final["haul_pay_cents"]
    load["settlement_event_on"] = certified_dt.date().isoformat()
    load["settlement_status"] = "ACCRUED"
    touch(load)

    # Hops 3 and 4 -- quota moves from reserved to delivered; contract may fill.
    derive.recompute_contract(contract)
    tract = db.tracts.get(load["tract_id"])
    if tract is not None:
        touch(tract)
    return ok(derive.delivery_ticket_json(ticket))


@bp.route("/delivery-tickets/<id>/reject", methods=["POST"])
@endpoint("MillScaler")
def reject_delivery_ticket(caller, id):
    payload = body()
    reject_reason = req_enum(payload, "reject_reason", REJECT_REASONS)
    ticket = db.delivery_tickets.get(id)
    if ticket is None:
        fail("ERR_DELIVERY_TICKET_NOT_FOUND", "no delivery ticket %s" % id)
    if caller.user_id != ticket["mill_id"]:
        fail("ERR_SCALER_MILL_MISMATCH", "scaler may only act on its own mill's tickets")
    if ticket["ticket_status"] != "DRAFT":
        fail("ERR_INVALID_TICKET_STATE", "only a DRAFT ticket may be rejected")
    load = db.loads.get(ticket["load_id"])
    if load is None or load["dispatch_status"] != "AT_MILL":
        fail("ERR_INVALID_LOAD_STATE", "the ticket's load is not AT_MILL")

    # Hop 1
    ticket["ticket_status"] = "REJECTED"
    ticket["reject_reason"] = reject_reason
    touch(ticket)

    # Hop 2
    load["dispatch_status"] = "REJECTED"
    load["rejected_on"] = clock.date_str()
    touch(load)

    # Hop 3
    contract = db.mill_contracts.get(load["mill_contract_id"])
    derive.recompute_contract(contract)

    # Hop 4 -- the carrier's compliance score is derived, so nothing to write.

    # Hop 5 -- the rehaul selector.
    winner = select_rehaul_alternate(load, ticket)
    if winner is None:
        load["rehaul_status"] = "NO_ALTERNATE"
        load["settlement_event_on"] = load["rejected_on"]
        load["settlement_status"] = "ACCRUED"
        touch(load)
    else:
        win_contract, win_route = winner
        load["rehaul_status"] = "REHAULED"
        touch(load)
        tract = db.tracts.get(load["tract_id"])
        truck = db.trucks.get(load["truck_id"])
        depart_dt = clock.now
        arrive_dt = depart_dt + timedelta(
            minutes=calc.rehaul_travel_minutes(win_route["distance_miles"])
        )
        from core import iso_instant

        build_load(
            tract,
            win_contract,
            win_route,
            truck,
            ticket["scaled_species"],
            ticket["scaled_grade"],
            ticket["net_tons"],
            iso_instant(depart_dt),
            iso_instant(arrive_dt),
            rehaul_of_load_id=load["id"],
        )
    return ok(derive.delivery_ticket_json(ticket))


def select_rehaul_alternate(load, ticket):
    """calculations.rehaul_alternate_selection -- explicit filter, strict ranking."""
    truck = db.trucks.get(load["truck_id"])
    rejecting_mill_id = ticket["mill_id"]
    today = clock.date()
    net_tons = D(ticket["net_tons"])
    candidates = []
    for contract in ordered(list(db.mill_contracts.values())):
        if contract["status"] != "OPEN":
            continue
        if contract["species"] != ticket["scaled_species"]:
            continue
        if contract["grade"] != ticket["scaled_grade"]:
            continue
        if not (to_date(contract["period_start"]) <= today <= to_date(contract["period_end"])):
            continue
        if derive.contract_available_tons(contract) < net_tons:
            continue
        if contract["mill_id"] == rejecting_mill_id:
            continue
        mill = db.mills.get(contract["mill_id"])
        if mill is None or mill["receiving_status"] != "OPEN":
            continue
        for route in ordered(list(db.haul_routes.values())):
            if route["tract_id"] != load["tract_id"]:
                continue
            if route["mill_id"] != contract["mill_id"]:
                continue
            if route["status"] not in ("OPEN", "POSTED_RESTRICTED"):
                continue
            if PERMIT_RANK[truck["permit_class"]] < PERMIT_RANK[route["permit_class_required"]]:
                continue
            yield_cents = calc.rehaul_net_yield_cents(
                contract["base_rate_cents_per_ton"], net_tons, route["distance_miles"]
            )
            candidates.append((yield_cents, route["distance_miles"], contract, route))
    if not candidates:
        return None
    candidates.sort(
        key=lambda c: (-c[0], c[1], c[2]["created_at"], c[2]["_seq"])
    )
    best = candidates[0]
    return best[2], best[3]

"""PerDiemLedger, EquipmentShipment, ContingencyEvent, CredentialRequest routes."""
from flask import Blueprint, g

import calc
import util
from util import (
    ApiError,
    apply_filters,
    body,
    check_team_member_owns,
    finalize_trip,
    invalid,
    paginate,
    reconcile_trip_posture,
    req_date,
    req_dt,
    req_enum,
    req_int,
    req_str,
    opt_int,
    opt_str,
    require_role,
    resolve_credential,
    resolve_contract,
    resolve_event,
    resolve_ledger,
    resolve_leg,
    resolve_member,
    resolve_shipment,
    resolve_team,
    resolve_trip,
    team_member_read_guard,
)
from envelope import ok, ok_list
from state import STORE, bump, clock_now, fmt_ts, new_resource, public

bp = Blueprint("ops", __name__)


def trip_not_terminal(trip):
    if trip["posture"] in ("CLOSED", "CANCELLED"):
        raise ApiError("ERR_TRIP_ALREADY_TERMINAL", 409, "Trip already CLOSED or CANCELLED")


def per_diem_input_error(msg):
    return ApiError("ERR_INVALID_PER_DIEM_INPUT", 400, msg)


# ---------------------------------------------------------------------------
# Per-diem ledgers
# ---------------------------------------------------------------------------
@bp.route("/travel/teams/<teamId>/trips/<tripId>/members/<memberId>/per-diem", methods=["POST"])
def create_ledger(teamId, tripId, memberId):
    require_role("TravelFinanceLead")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    member = resolve_member(trip, memberId)
    data = body()
    service_date_raw, _sd = req_date(data, "service_date")
    day_kind_raw = data.get("day_kind")
    if not isinstance(day_kind_raw, str):
        raise invalid("Missing or invalid field: day_kind")
    meals = data.get("meals_provided_count", 0)
    if isinstance(meals, bool) or not isinstance(meals, int):
        raise invalid("Invalid field: meals_provided_count")
    trip_not_terminal(trip)
    # Referenced-target state (priority 15) before per-diem input (priority 17).
    if member["status"] != "IN":
        raise ApiError("ERR_MEMBER_NOT_IN", 409, "Referenced member status is not IN")
    if day_kind_raw not in calc.DAY_KINDS:
        raise per_diem_input_error("day_kind invalid")
    if meals < 0 or meals > calc.MAX_MEALS_PER_DAY:
        raise per_diem_input_error("meals_provided_count cannot exceed 3 per day")
    base, deduction, net = calc.per_diem_amounts(member["per_diem_tier"], day_kind_raw, meals)
    ledger = new_resource()
    ledger.update(
        {
            "member_id": member["id"],
            "service_date": service_date_raw,
            "day_kind": day_kind_raw,
            "meals_provided_count": meals,
            "base_amount_cents": base,
            "deduction_cents": deduction,
            "net_amount_cents": net,
            "status": "DRAFT",
            "paid_at": None,
            "_kind": "ledger",
        }
    )
    STORE["ledgers"][ledger["id"]] = ledger
    finalize_trip(trip)
    return ok(public(ledger), 201)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/members/<memberId>/per-diem", methods=["GET"])
def list_ledgers(teamId, tripId, memberId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    member = resolve_member(trip, memberId)
    if g.user_role == "TeamMember":
        check_team_member_owns(member["id"])
    items = calc.children("ledgers", member_id=member["id"])
    page, total, limit, offset = paginate(items)
    return ok_list([public(l) for l in page], total, limit, offset)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/members/<memberId>/per-diem/<ledgerId>", methods=["GET"])
def get_ledger(teamId, tripId, memberId, ledgerId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    member = resolve_member(trip, memberId)
    ledger = resolve_ledger(member, ledgerId)
    team_member_read_guard(ledger)
    return ok(public(ledger), 200)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/members/<memberId>/per-diem/<ledgerId>/approve",
    methods=["POST"],
)
def approve_ledger(teamId, tripId, memberId, ledgerId):
    require_role("TravelFinanceLead")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    member = resolve_member(trip, memberId)
    ledger = resolve_ledger(member, ledgerId)
    body()
    trip_not_terminal(trip)
    if ledger["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Ledger must be DRAFT to approve")
    if member["status"] != "IN":
        raise ApiError("ERR_MEMBER_NOT_IN", 409, "Referenced member status is not IN")
    ledger["status"] = "APPROVED"
    bump(ledger)
    finalize_trip(trip, enumerated=True)
    return ok(public(ledger), 200)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/members/<memberId>/per-diem/<ledgerId>/pay",
    methods=["POST"],
)
def pay_ledger(teamId, tripId, memberId, ledgerId):
    require_role("TravelFinanceLead")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    member = resolve_member(trip, memberId)
    ledger = resolve_ledger(member, ledgerId)
    body()
    trip_not_terminal(trip)
    if ledger["status"] != "APPROVED":
        raise ApiError("ERR_LEDGER_NOT_APPROVED", 409, "Ledger must be APPROVED to pay")
    if trip["posture"] not in ("LOCKED", "IN_FLIGHT", "RECOVERING", "DISRUPTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Trip posture does not permit payment")
    ledger["status"] = "PAID"
    ledger["paid_at"] = fmt_ts(clock_now())
    bump(ledger)
    calc.log_financial_event(trip, fmt_ts(clock_now()), ledger["net_amount_cents"])
    finalize_trip(trip, enumerated=True)
    return ok(public(ledger), 200)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/members/<memberId>/per-diem/<ledgerId>/dispute",
    methods=["POST"],
)
def dispute_ledger(teamId, tripId, memberId, ledgerId):
    require_role("TeamMember")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    member = resolve_member(trip, memberId)
    ledger = resolve_ledger(member, ledgerId)
    body()
    check_team_member_owns(member["id"])
    trip_not_terminal(trip)
    if ledger["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Ledger must be APPROVED to dispute")
    ledger["status"] = "DISPUTED"
    bump(ledger)
    finalize_trip(trip)
    return ok(public(ledger), 200)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/members/<memberId>/per-diem/<ledgerId>/resolve",
    methods=["POST"],
)
def resolve_ledger_action(teamId, tripId, memberId, ledgerId):
    require_role("TravelFinanceLead")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    member = resolve_member(trip, memberId)
    ledger = resolve_ledger(member, ledgerId)
    data = body()
    meals = data.get("meals_provided_count")
    if isinstance(meals, bool) or not isinstance(meals, int):
        raise invalid("Missing or invalid field: meals_provided_count")
    trip_not_terminal(trip)
    if ledger["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Ledger must be DISPUTED to resolve")
    if meals < 0 or meals > calc.MAX_MEALS_PER_DAY:
        raise per_diem_input_error("meals_provided_count cannot exceed 3 per day")
    base, deduction, net = calc.per_diem_amounts(member["per_diem_tier"], ledger["day_kind"], meals)
    ledger["meals_provided_count"] = meals
    ledger["base_amount_cents"] = base
    ledger["deduction_cents"] = deduction
    ledger["net_amount_cents"] = net
    ledger["status"] = "APPROVED"
    bump(ledger)
    finalize_trip(trip)
    return ok(public(ledger), 200)


# ---------------------------------------------------------------------------
# Equipment shipments
# ---------------------------------------------------------------------------
@bp.route("/travel/teams/<teamId>/trips/<tripId>/equipment", methods=["POST"])
def create_shipment(teamId, tripId):
    require_role("EquipmentManager")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    data = body()
    kind = req_enum(data, "shipment_kind", calc.SHIPMENT_KINDS)
    weight = req_int(data, "gross_weight_lb")
    pieces = req_int(data, "piece_count")
    value = req_int(data, "declared_value_cents")
    contract_id = opt_str(data, "assigned_contract_id", None)
    trip_not_terminal(trip)
    if contract_id is not None:
        resolve_contract(trip, contract_id)
    shipment = new_resource()
    shipment.update(
        {
            "trip_id": trip["id"],
            "shipment_kind": kind,
            "gross_weight_lb": weight,
            "piece_count": pieces,
            "declared_value_cents": value,
            "assigned_contract_id": contract_id,
            "status": "STAGED",
            "chargeback_cents": 0,
            "_kind": "shipment",
        }
    )
    STORE["shipments"][shipment["id"]] = shipment
    return ok(public(shipment), 201)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/equipment", methods=["GET"])
def list_shipments(teamId, tripId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    items = calc.trip_shipments(trip)
    items = apply_filters(items, ["assigned_contract_id"])
    page, total, limit, offset = paginate(items)
    return ok_list([public(s) for s in page], total, limit, offset)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/charter-contracts/<contractId>/equipment",
    methods=["GET"],
)
def list_shipments_by_contract(teamId, tripId, contractId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    contract = resolve_contract(trip, contractId)
    items = calc.children("shipments", assigned_contract_id=contract["id"])
    page, total, limit, offset = paginate(items)
    return ok_list([public(s) for s in page], total, limit, offset)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/equipment/<shipmentId>", methods=["GET"])
def get_shipment(teamId, tripId, shipmentId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    shipment = resolve_shipment(trip, shipmentId)
    return ok(public(shipment), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/equipment/<shipmentId>/load", methods=["POST"])
def load_shipment(teamId, tripId, shipmentId):
    require_role("EquipmentManager")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    shipment = resolve_shipment(trip, shipmentId)
    body()
    trip_not_terminal(trip)
    if shipment["status"] != "STAGED":
        raise ApiError("ERR_INVALID_STATE", 409, "Shipment must be STAGED to load")
    contract_id = shipment.get("assigned_contract_id")
    if contract_id is None:
        raise invalid("Shipment has no assigned_contract_id to load onto")
    contract = STORE["contracts"].get(contract_id)
    if contract is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", 404, "contractId does not exist within trip")
    # Cargo capacity (priority 12) precedes referenced-contract state (15).
    committed = calc.committed_weight_lb(contract)
    if committed > contract["cargo_capacity_lb"]:
        raise ApiError("ERR_CARGO_OVERWEIGHT", 409, "Shipment would exceed charter cargo capacity")
    if contract["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONTRACT_NOT_EXECUTABLE", 409, "Referenced charter contract must be ACTIVE"
        )
    shipment["status"] = "LOADED"
    shipment["chargeback_cents"] = calc.weight_chargeback_cents(
        committed, contract["cargo_capacity_lb"]
    )
    bump(shipment)
    finalize_trip(trip, enumerated=True)
    return ok(public(shipment), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/equipment/<shipmentId>/deliver", methods=["POST"])
def deliver_shipment(teamId, tripId, shipmentId):
    require_role("EquipmentManager")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    shipment = resolve_shipment(trip, shipmentId)
    body()
    trip_not_terminal(trip)
    if shipment["status"] != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_STATE", 409, "Shipment must be IN_TRANSIT to deliver")
    shipment["status"] = "DELIVERED"
    bump(shipment)
    finalize_trip(trip)
    return ok(public(shipment), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/equipment/<shipmentId>/mark-lost", methods=["POST"])
def lost_shipment(teamId, tripId, shipmentId):
    require_role("EquipmentManager")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    shipment = resolve_shipment(trip, shipmentId)
    body()
    trip_not_terminal(trip)
    if shipment["status"] not in ("STAGED", "LOADED", "IN_TRANSIT", "DELAYED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Shipment cannot be marked lost from current state")
    shipment["status"] = "LOST"
    shipment["chargeback_cents"] = shipment["declared_value_cents"]
    bump(shipment)
    calc.log_financial_event(trip, fmt_ts(clock_now()), shipment["chargeback_cents"])
    finalize_trip(trip)
    return ok(public(shipment), 200)


# ---------------------------------------------------------------------------
# Contingency events
# ---------------------------------------------------------------------------
@bp.route("/travel/teams/<teamId>/trips/<tripId>/contingencies", methods=["POST"])
def create_event(teamId, tripId):
    require_role("TravelManager")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    data = body()
    kind = req_enum(data, "kind", calc.EVENT_KINDS)
    detected_raw, detected = req_dt(data, "detected_at")
    leg_id = req_str(data, "affected_leg_id")
    severity = req_enum(data, "severity", calc.SEVERITIES)
    trip_not_terminal(trip)
    leg = resolve_leg(trip, leg_id)
    event = new_resource()
    event.update(
        {
            "trip_id": trip["id"],
            "kind": kind,
            "detected_at": detected_raw,
            "affected_leg_id": leg["id"],
            "severity": severity,
            "status": "OPEN",
            "resolution_action": None,
            "recovery_cost_cents": 0,
            "_kind": "event",
            "_detected": detected,
            "_resolved_at": None,
        }
    )
    STORE["events"][event["id"]] = event
    trip["disruption_seq"] += 1
    if trip["posture"] == "LOCKED":
        trip["posture"] = "DISRUPTED"
        if leg["status"] == "BOOKED":
            leg["status"] = "REBOOKING"
            bump(leg)
    elif trip["posture"] == "IN_FLIGHT":
        trip["posture"] = "DISRUPTED"
    finalize_trip(trip, enumerated=True)
    return ok(public(event), 201)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/contingencies", methods=["GET"])
def list_events(teamId, tripId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    items = calc.trip_events(trip)
    items = apply_filters(items, ["affected_leg_id"])
    page, total, limit, offset = paginate(items)
    return ok_list([public(e) for e in page], total, limit, offset)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/flight-legs/<legId>/contingencies", methods=["GET"]
)
def list_events_by_leg(teamId, tripId, legId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    leg = resolve_leg(trip, legId)
    items = calc.children("events", affected_leg_id=leg["id"])
    page, total, limit, offset = paginate(items)
    return ok_list([public(e) for e in page], total, limit, offset)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/contingencies/<eventId>", methods=["GET"])
def get_event(teamId, tripId, eventId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    event = resolve_event(trip, eventId)
    return ok(public(event), 200)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/contingencies/<eventId>/mitigate", methods=["POST"]
)
def mitigate_event(teamId, tripId, eventId):
    require_role("TravelManager")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    event = resolve_event(trip, eventId)
    data = body()
    action = req_enum(data, "resolution_action", calc.RESOLUTION_ACTIONS)
    trip_not_terminal(trip)
    if event["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Event must be OPEN to mitigate")
    event["resolution_action"] = action
    event["status"] = "MITIGATING"
    bump(event)
    return ok(public(event), 200)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/contingencies/<eventId>/resolve", methods=["POST"]
)
def resolve_event_action(teamId, tripId, eventId):
    require_role("TravelManager")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    event = resolve_event(trip, eventId)
    data = body()
    recovery = req_int(data, "recovery_cost_cents")
    trip_not_terminal(trip)
    if event["status"] != "MITIGATING":
        raise ApiError("ERR_INVALID_STATE", 409, "Event must be MITIGATING to resolve")
    leg = STORE["legs"].get(event["affected_leg_id"])
    if event["resolution_action"] == "REBOOK":
        if leg is None or leg["status"] != "BOOKED":
            raise ApiError(
                "ERR_LEG_NOT_BOOKED", 409, "REBOOK resolution requires affected leg BOOKED"
            )
    if event["resolution_action"] == "OVERNIGHT":
        if not any(
            b["posture"] in ("HOLDING", "NAME_LIST_DUE", "LOCKED", "ATTRITION_EXPOSED")
            for b in calc.trip_blocks(trip)
        ):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "OVERNIGHT resolution requires a hotel block covering the disruption night",
            )
    season = STORE["seasons"][trip["season_id"]]
    if trip["posture"] in ("LOCKED", "IN_FLIGHT", "DISRUPTED", "RECOVERING"):
        if calc.season_remaining(season) < recovery:
            raise ApiError("ERR_BUDGET_EXCEEDED", 402, "Recovery cost exceeds season budget")
    event["recovery_cost_cents"] = recovery
    event["status"] = "RESOLVED"
    event["_resolved_at"] = fmt_ts(clock_now())
    bump(event)
    calc.log_financial_event(trip, fmt_ts(clock_now()), recovery)
    finalize_trip(trip)
    reconcile_trip_posture(trip, season)
    return ok(public(event), 200)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/contingencies/<eventId>/close-noop", methods=["POST"]
)
def close_noop_event(teamId, tripId, eventId):
    require_role("TravelManager")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    event = resolve_event(trip, eventId)
    body()
    if event["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Event must be OPEN to close without action")
    leg = STORE["legs"].get(event["affected_leg_id"])
    if not (
        (leg is not None and leg["status"] == "CANCELLED") or trip["posture"] == "CANCELLED"
    ):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "close-noop requires the affected leg or the trip to be CANCELLED",
        )
    event["status"] = "CLOSED"
    bump(event)
    return ok(public(event), 200)


# ---------------------------------------------------------------------------
# Credential requests
# ---------------------------------------------------------------------------
@bp.route("/travel/teams/<teamId>/trips/<tripId>/credentials", methods=["POST"])
def create_credential(teamId, tripId):
    require_role("TeamMember")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    data = body()
    member_id = req_str(data, "member_id")
    venue_code = req_str(data, "venue_code")
    access_level = req_enum(data, "access_level", calc.ACCESS_LEVELS)
    trip_not_terminal(trip)
    member = resolve_member(trip, member_id)
    check_team_member_owns(member["id"])
    if member["status"] != "IN":
        raise ApiError("ERR_MEMBER_NOT_IN", 409, "Referenced member status is not IN")
    cred = new_resource()
    cred.update(
        {
            "trip_id": trip["id"],
            "member_id": member["id"],
            "venue_code": venue_code,
            "access_level": access_level,
            "submitted_by_user_id": g.user_id,
            "reviewed_by_user_id": None,
            "approved_by_user_id": None,
            "status": "SUBMITTED",
            "denial_reason": None,
            "_kind": "credential",
        }
    )
    STORE["credentials"][cred["id"]] = cred
    return ok(public(cred), 201)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/credentials", methods=["GET"])
def list_credentials(teamId, tripId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    items = calc.trip_credentials(trip)
    if g.user_role == "TeamMember":
        items = [c for c in items if c["member_id"] == g.user_id]
    items = apply_filters(items, ["member_id"])
    page, total, limit, offset = paginate(items)
    return ok_list([public(c) for c in page], total, limit, offset)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/members/<memberId>/credentials", methods=["GET"]
)
def list_credentials_by_member(teamId, tripId, memberId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    member = resolve_member(trip, memberId)
    if g.user_role == "TeamMember":
        check_team_member_owns(member["id"])
    items = calc.children("credentials", member_id=member["id"], trip_id=trip["id"])
    page, total, limit, offset = paginate(items)
    return ok_list([public(c) for c in page], total, limit, offset)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/credentials/<credId>", methods=["GET"])
def get_credential(teamId, tripId, credId):
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    cred = resolve_credential(trip, credId)
    team_member_read_guard(cred)
    return ok(public(cred), 200)


def _bump_confirmed_entries_for_venue(trip, member_id, venue_code):
    for leg in calc.trip_legs(trip):
        if leg["destination_code"] != venue_code:
            continue
        for entry in calc.leg_entries(leg):
            if entry["member_id"] == member_id and entry["status"] == "CONFIRMED":
                entry["status"] = "BUMPED"
                entry["bump_reason"] = "SECURITY_DENIAL"
                bump(entry)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/credentials/<credId>/security-review",
    methods=["POST"],
)
def security_review_credential(teamId, tripId, credId):
    require_role("SecurityOfficer")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    cred = resolve_credential(trip, credId)
    body()
    trip_not_terminal(trip)
    if cred["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Credential must be SUBMITTED for security review")
    # Segregation of duties (priority 9).
    if g.user_id == cred["submitted_by_user_id"]:
        raise ApiError(
            "ERR_SOD_VIOLATION", 403, "Reviewer may not be the request submitter"
        )
    cred["reviewed_by_user_id"] = g.user_id
    cred["status"] = "SECURITY_REVIEW"
    bump(cred)
    return ok(public(cred), 200)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/credentials/<credId>/approve", methods=["POST"]
)
def approve_credential(teamId, tripId, credId):
    require_role("VenueCredentialApprover")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    cred = resolve_credential(trip, credId)
    body()
    trip_not_terminal(trip)
    if cred["status"] != "SECURITY_REVIEW":
        raise ApiError(
            "ERR_CREDENTIAL_NOT_IN_REVIEW", 409, "Credential must be in SECURITY_REVIEW to approve"
        )
    if g.user_id in (cred["submitted_by_user_id"], cred["reviewed_by_user_id"]):
        raise ApiError(
            "ERR_SOD_VIOLATION",
            403,
            "Approver must differ from submitter and reviewer",
        )
    cred["approved_by_user_id"] = g.user_id
    cred["status"] = "APPROVED"
    bump(cred)
    return ok(public(cred), 200)


@bp.route("/travel/teams/<teamId>/trips/<tripId>/credentials/<credId>/deny", methods=["POST"])
def deny_credential(teamId, tripId, credId):
    require_role("VenueCredentialApprover")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    cred = resolve_credential(trip, credId)
    data = body()
    reason = req_str(data, "denial_reason")
    trip_not_terminal(trip)
    if cred["status"] != "SECURITY_REVIEW":
        raise ApiError(
            "ERR_CREDENTIAL_NOT_IN_REVIEW", 409, "Credential must be in SECURITY_REVIEW to deny"
        )
    cred["denial_reason"] = reason
    cred["status"] = "DENIED"
    bump(cred)
    _bump_confirmed_entries_for_venue(trip, cred["member_id"], cred["venue_code"])
    return ok(public(cred), 200)


@bp.route(
    "/travel/teams/<teamId>/trips/<tripId>/credentials/<credId>/revoke", methods=["POST"]
)
def revoke_credential(teamId, tripId, credId):
    require_role("SecurityOfficer")
    team = resolve_team(teamId)
    trip = resolve_trip(team, tripId)
    cred = resolve_credential(trip, credId)
    body()
    trip_not_terminal(trip)
    if cred["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Credential must be APPROVED to revoke")
    cred["status"] = "REVOKED"
    bump(cred)
    _bump_confirmed_entries_for_venue(trip, cred["member_id"], cred["venue_code"])
    return ok(public(cred), 200)

"""Service tickets: open/dispatch/record-response (breach cascade)/resolve/cancel."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, request

from auth import require_roles, check_ownership
from domain import (
    CREDIT_TTL_DAYS,
    SEVERITY_MULTIPLIER,
    SLA_BASE_HOURS,
    SLA_BREACH_SUSPEND_THRESHOLD,
    SLA_CREDIT_PCT,
    active_contract_of,
    latest_nonterminal_contract_of,
)
from envelope import ok_object, ok_list
from errors import (
    conflict,
    invalid_request,
    invalid_state,
    not_found,
    ERR_CONTRACT_SUSPENDED,
    ERR_FACILITY_MISMATCH,
    ERR_FACILITY_NOT_ACTIVE,
    ERR_NO_ACTIVE_CONTRACT,
)
import store
from store import new_resource, touch
from util import body_or_empty, parse_pagination, public, req_str, round_half_up, sort_and_page

bp = Blueprint("tickets", __name__)

ALL_ROLES = ["DealerAdmin", "EnergyEngineer", "ServiceTech", "ContractManager", "FacilityManager"]
SEVERITIES = ("EMERGENCY", "URGENT", "ROUTINE")


def _get_or_404(ticket_id):
    ticket = store.service_tickets.get(ticket_id)
    if ticket is None:
        raise not_found("ServiceTicket not found")
    return ticket


def _parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


@bp.route("/service-tickets", methods=["POST"])
def create_ticket():
    user_id, role = require_roles(["FacilityManager"])
    body = body_or_empty()
    facility_id = req_str(body, "facility_id")
    compressor_id = req_str(body, "compressor_id")
    severity = req_str(body, "severity")
    if severity not in SEVERITIES:
        raise invalid_request("severity must be EMERGENCY, URGENT, or ROUTINE")

    fac = store.facilities.get(facility_id)
    if fac is None:
        raise not_found("Facility not found")
    check_ownership(user_id, role, facility_id)

    # gates in order: facility ACTIVE -> contract gate -> compressor ownership
    if fac["status"] != "ACTIVE":
        raise conflict(ERR_FACILITY_NOT_ACTIVE, "Facility must be ACTIVE to open a ticket")

    contract = active_contract_of(facility_id)
    if contract is None:
        latest = latest_nonterminal_contract_of(facility_id)
        if latest is not None and latest["status"] == "SUSPENDED":
            raise conflict(ERR_CONTRACT_SUSPENDED, "Facility's latest non-terminal contract is SUSPENDED")
        raise conflict(ERR_NO_ACTIVE_CONTRACT, "Facility has no ACTIVE service contract")

    comp = store.compressors.get(compressor_id)
    if comp is None or comp["facility_id"] != facility_id:
        raise conflict(ERR_FACILITY_MISMATCH, "compressor_id must belong to the calling facility")

    reported_at = store.get_clock()
    base_hours = SLA_BASE_HOURS[contract["tier"]]
    deadline = reported_at + timedelta(hours=base_hours * SEVERITY_MULTIPLIER[severity])

    ticket = new_resource()
    ticket.update(
        {
            "facility_id": facility_id,
            "contract_id": contract["id"],
            "compressor_id": compressor_id,
            "severity": severity,
            "reported_at": store.fmt_clock(reported_at),
            "sla_tier_snapshot": contract["tier"],
            "sla_deadline": store.fmt_clock(deadline),
            "first_response_at": None,
            "sla_met": None,
            "status": "OPEN",
        }
    )
    store.service_tickets[ticket["id"]] = ticket
    return ok_object(public(ticket), 201)


@bp.route("/service-tickets", methods=["GET"])
def list_tickets():
    require_roles(ALL_ROLES)
    items = list(store.service_tickets.values())
    for param in ("facility_id", "contract_id", "compressor_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [t for t in items if t[param] == value]
    limit, offset = parse_pagination()
    page, total = sort_and_page(items, limit, offset)
    return ok_list([public(t) for t in page], limit, offset, total)


@bp.route("/service-tickets/<serviceTicketId>", methods=["GET"])
def get_ticket(serviceTicketId):
    user_id, role = require_roles(ALL_ROLES)
    ticket = _get_or_404(serviceTicketId)
    check_ownership(user_id, role, ticket["facility_id"])
    return ok_object(public(ticket), 200)


@bp.route("/service-tickets/<serviceTicketId>/dispatch", methods=["POST"])
def dispatch(serviceTicketId):
    require_roles(["ServiceTech"])
    ticket = _get_or_404(serviceTicketId)
    if ticket["status"] != "OPEN":
        raise invalid_state("ServiceTicket must be OPEN to dispatch")
    ticket["status"] = "DISPATCHED"
    touch(ticket)
    return ok_object(public(ticket), 200)


@bp.route("/service-tickets/<serviceTicketId>/record-response", methods=["POST"])
def record_response(serviceTicketId):
    require_roles(["ServiceTech"])
    ticket = _get_or_404(serviceTicketId)
    if ticket["status"] != "DISPATCHED":
        raise invalid_state("ServiceTicket must be DISPATCHED to record a response")

    now = store.get_clock()
    deadline = _parse_iso(ticket["sla_deadline"])
    ticket["first_response_at"] = store.fmt_clock(now)
    ticket["sla_met"] = now <= deadline  # inclusive: exactly at deadline is MET
    ticket["status"] = "ON_SITE"
    touch(ticket)

    if not ticket["sla_met"]:
        # Breach cascade: credit accrual + contract counters + auto-suspension
        contract = store.service_contracts.get(ticket["contract_id"])
        if contract is not None:
            amount = round_half_up(Decimal(contract["monthly_fee_cents"]) * SLA_CREDIT_PCT)
            credit = new_resource()
            accrued_at = store.get_clock()
            credit.update(
                {
                    "contract_id": contract["id"],
                    "ticket_id": ticket["id"],
                    "source": "SLA_BREACH",
                    "amount_cents": amount,
                    "accrued_at": store.fmt_clock(accrued_at),
                    "expires_at": store.fmt_clock(accrued_at + timedelta(days=CREDIT_TTL_DAYS)),
                    "status": "ACCRUED",
                }
            )
            store.service_credits[credit["id"]] = credit

            contract["credits_accrued_total_cents"] += amount
            contract["credits_outstanding_cents"] += amount
            contract["sla_breach_count"] += 1
            if contract["sla_breach_count"] >= SLA_BREACH_SUSPEND_THRESHOLD:
                contract["termination_penalty_waived"] = True
                if contract["status"] == "ACTIVE":
                    contract["status"] = "SUSPENDED"
            touch(contract)

    return ok_object(public(ticket), 200)


@bp.route("/service-tickets/<serviceTicketId>/resolve", methods=["POST"])
def resolve(serviceTicketId):
    require_roles(["ServiceTech"])
    ticket = _get_or_404(serviceTicketId)
    if ticket["status"] != "ON_SITE":
        raise invalid_state("ServiceTicket must be ON_SITE to resolve")
    ticket["status"] = "RESOLVED"
    touch(ticket)
    return ok_object(public(ticket), 200)


@bp.route("/service-tickets/<serviceTicketId>/cancel", methods=["POST"])
def cancel(serviceTicketId):
    user_id, role = require_roles(["FacilityManager"])
    ticket = _get_or_404(serviceTicketId)
    check_ownership(user_id, role, ticket["facility_id"])
    if ticket["status"] not in ("OPEN", "DISPATCHED"):
        raise invalid_state("ServiceTicket must be OPEN or DISPATCHED to cancel")
    ticket["status"] = "CANCELLED"
    touch(ticket)
    return ok_object(public(ticket), 200)

"""Routes: crew share contracts, expense records, trip settlements."""

from flask import Blueprint, request

from errors import ApiError
import store
from common import (
    auth,
    body,
    f_dt,
    f_enum,
    f_int,
    f_number,
    f_str,
    get_crew_contract,
    get_expense,
    get_settlement,
    get_trip,
    get_vessel,
    list_response,
    make_entity,
    not_owner,
    ok_object,
    pub,
    require_roles,
    touch,
)
import domain
from store import iso

bp = Blueprint("settlements", __name__)

OWNER = ["VesselOwner"]
CLERK = ["SettlementClerk"]
EXPENSE_RECORDERS = ["Captain", "VesselOwner"]
EXPENSE_CATEGORIES = ["FUEL", "BAIT", "ICE", "GROCERIES", "GEAR_REPAIR", "OTHER"]


# ---------------------------------------------------------------------------
# Crew share contracts
# ---------------------------------------------------------------------------

@bp.route("/vessels/<rid>/crew-contracts", methods=["POST"])
def create_crew_contract(rid):
    uid, role = auth()
    require_roles(role, OWNER)
    if uid != rid:
        not_owner("X-User-ID must equal the vessel id")
    vessel = get_vessel(rid)
    payload = body()
    crew_name = f_str(payload, "crew_name")
    share_points = f_number(payload, "share_points")
    if share_points <= 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "share_points must be > 0")
    joined_at = f_dt(payload, "joined_at")
    contract = make_entity(
        {
            "vessel_id": vessel["id"],
            "crew_name": crew_name,
            "share_points": share_points,
            "joined_at": iso(joined_at),
            "status": "ACTIVE",
        }
    )
    store.db.crew_contracts[contract["id"]] = contract
    return ok_object(pub(contract), 201)


@bp.route("/vessels/<rid>/crew-contracts", methods=["GET"])
def list_crew_contracts(rid):
    auth()
    get_vessel(rid)
    items = [c for c in store.db.crew_contracts.values() if c["vessel_id"] == rid]
    return list_response(items, [("status", request.args.get("status"))])


@bp.route("/crew-contracts/<rid>/deactivate", methods=["POST"])
def deactivate_crew_contract(rid):
    uid, role = auth()
    require_roles(role, OWNER)
    contract = get_crew_contract(rid)
    if uid != contract["vessel_id"]:
        not_owner("X-User-ID must equal the contract's vessel id")
    contract["status"] = "INACTIVE"
    touch(contract)
    return ok_object(pub(contract))


# ---------------------------------------------------------------------------
# Expense records
# ---------------------------------------------------------------------------

@bp.route("/fishing-trips/<rid>/expenses", methods=["POST"])
def create_expense(rid):
    uid, role = auth()
    require_roles(role, EXPENSE_RECORDERS)
    trip = get_trip(rid)
    if uid != trip["vessel_id"]:
        not_owner("X-User-ID must equal the trip's vessel id")
    payload = body()
    category = f_enum(payload, "category", EXPENSE_CATEGORIES)
    amount = f_int(payload, "amount_cents")
    if amount <= 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "amount_cents must be > 0")
    incurred_at = f_dt(payload, "incurred_at")
    expense = make_entity(
        {
            "trip_id": trip["id"],
            "category": category,
            "amount_cents": amount,
            "incurred_at": iso(incurred_at),
            "status": "PENDING",
        }
    )
    store.db.expenses[expense["id"]] = expense
    return ok_object(pub(expense), 201)


@bp.route("/fishing-trips/<rid>/expenses", methods=["GET"])
def list_expenses(rid):
    auth()
    get_trip(rid)
    items = [e for e in store.db.expenses.values() if e["trip_id"] == rid]
    return list_response(items, [("status", request.args.get("status"))])


def _expense_transition(rid, target):
    _, role = auth()
    require_roles(role, CLERK)
    expense = get_expense(rid)
    if expense["status"] != "PENDING":
        raise ApiError(409, "ERR_EXPENSE_NOT_PENDING", "expense is not PENDING")
    expense["status"] = target
    touch(expense)
    return ok_object(pub(expense))


@bp.route("/expenses/<rid>/verify", methods=["POST"])
def verify_expense(rid):
    return _expense_transition(rid, "VERIFIED")


@bp.route("/expenses/<rid>/reject", methods=["POST"])
def reject_expense(rid):
    return _expense_transition(rid, "REJECTED")


# ---------------------------------------------------------------------------
# Trip settlements
# ---------------------------------------------------------------------------

@bp.route("/fishing-trips/<rid>/settlement", methods=["POST"])
def create_settlement(rid):
    _, role = auth()
    require_roles(role, CLERK)
    trip = get_trip(rid)
    if trip["status"] != "LANDING_FINALIZED":
        raise ApiError(
            409,
            "ERR_TRIP_NOT_LANDING_FINALIZED",
            "settlement creation requires LANDING_FINALIZED",
        )
    payload = body()
    gross = f_int(payload, "gross_revenue_cents")
    if gross <= 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "gross_revenue_cents must be > 0")
    if any(s["trip_id"] == trip["id"] for s in store.db.settlements.values()):
        raise ApiError(
            409, "ERR_SETTLEMENT_EXISTS", "a settlement already exists for this trip"
        )
    provisional = domain.settlement_math(trip, gross, "provisional")
    settlement = make_entity(
        {
            "trip_id": trip["id"],
            "gross_revenue_cents": gross,
            "provisional_total_expenses_cents": provisional["total_expenses_cents"],
            "provisional_processing_fee_cents": provisional["processing_fee_cents"],
            "provisional_vessel_share_cents": provisional["vessel_share_cents"],
            "provisional_crew_pool_cents": provisional["crew_pool_cents"],
            "total_expenses_cents": None,
            "observer_fee_cents": None,
            "gear_loss_charge_cents": None,
            "processing_fee_cents": None,
            "net_cents": None,
            "vessel_share_cents": None,
            "crew_pool_cents": None,
            "crew_payouts": None,
            "status": "DRAFT",
        }
    )
    store.db.settlements[settlement["id"]] = settlement
    return ok_object(pub(settlement), 201)


@bp.route("/fishing-trips/<rid>/settlement", methods=["GET"])
def get_trip_settlement(rid):
    auth()
    get_trip(rid)
    items = [s for s in store.db.settlements.values() if s["trip_id"] == rid]
    return list_response(items)


@bp.route("/trip-settlements/<rid>", methods=["GET"])
def get_one_settlement(rid):
    auth()
    return ok_object(pub(get_settlement(rid)))


def _check_expenses_resolved(trip_id):
    if any(
        e["trip_id"] == trip_id and e["status"] not in ("VERIFIED", "REJECTED")
        for e in store.db.expenses.values()
    ):
        raise ApiError(
            409,
            "ERR_EXPENSES_UNRESOLVED",
            "every expense of the trip must be VERIFIED or REJECTED",
        )


def _run_final_calculation(settlement, check_active_crew):
    trip = get_trip(settlement["trip_id"])
    _check_expenses_resolved(trip["id"])
    if check_active_crew and not any(
        c["vessel_id"] == trip["vessel_id"] and c["status"] == "ACTIVE"
        for c in store.db.crew_contracts.values()
    ):
        raise ApiError(
            422, "ERR_NO_ACTIVE_CREW", "no ACTIVE crew share contract on the vessel"
        )
    final = domain.settlement_math(trip, settlement["gross_revenue_cents"], "final")
    if final["net_before_fee_cents"] < 0:
        raise ApiError(
            422, "ERR_SETTLEMENT_UNDERWATER", "net_before_fee is negative"
        )
    settlement["total_expenses_cents"] = final["total_expenses_cents"]
    settlement["observer_fee_cents"] = final["observer_fee_cents"]
    settlement["gear_loss_charge_cents"] = final["gear_loss_charge_cents"]
    settlement["processing_fee_cents"] = final["processing_fee_cents"]
    settlement["net_cents"] = final["net_cents"]
    settlement["vessel_share_cents"] = final["vessel_share_cents"]
    settlement["crew_pool_cents"] = final["crew_pool_cents"]
    settlement["crew_payouts"] = domain.crew_pool_split(
        trip["vessel_id"], final["crew_pool_cents"]
    )
    settlement["status"] = "CALCULATED"
    touch(settlement)


@bp.route("/trip-settlements/<rid>/calculate", methods=["POST"])
def calculate_settlement(rid):
    _, role = auth()
    require_roles(role, CLERK)
    settlement = get_settlement(rid)
    if settlement["status"] != "DRAFT":
        raise ApiError(409, "ERR_SETTLEMENT_NOT_DRAFT", "calculate requires DRAFT")
    _run_final_calculation(settlement, check_active_crew=True)
    return ok_object(pub(settlement))


@bp.route("/trip-settlements/<rid>/recalculate", methods=["POST"])
def recalculate_settlement(rid):
    _, role = auth()
    require_roles(role, CLERK)
    settlement = get_settlement(rid)
    payload = body()
    expected = f_int(payload, "expected_settlement_version")
    if expected != settlement["version"]:
        raise ApiError(412, "ERR_STALE_VERSION", "expected_settlement_version is stale")
    if settlement["status"] != "DISPUTED":
        raise ApiError(
            409, "ERR_SETTLEMENT_NOT_DISPUTED", "recalculate requires DISPUTED"
        )
    _run_final_calculation(settlement, check_active_crew=False)
    return ok_object(pub(settlement))


@bp.route("/trip-settlements/<rid>/approve", methods=["POST"])
def approve_settlement(rid):
    uid, role = auth()
    require_roles(role, OWNER)
    settlement = get_settlement(rid)
    trip = get_trip(settlement["trip_id"])
    if uid != trip["vessel_id"]:
        not_owner("X-User-ID must equal the trip's vessel id")
    if settlement["status"] != "CALCULATED":
        raise ApiError(
            409, "ERR_SETTLEMENT_NOT_CALCULATED", "approve requires CALCULATED"
        )
    settlement["status"] = "APPROVED"
    touch(settlement)
    return ok_object(pub(settlement))


@bp.route("/trip-settlements/<rid>/dispute", methods=["POST"])
def dispute_settlement(rid):
    uid, role = auth()
    require_roles(role, ["CrewMember"])
    settlement = get_settlement(rid)
    trip = get_trip(settlement["trip_id"])
    contract = store.db.crew_contracts.get(uid)
    if (
        contract is None
        or contract["vessel_id"] != trip["vessel_id"]
        or contract["status"] != "ACTIVE"
    ):
        not_owner("X-User-ID must be an ACTIVE crew share contract on the trip's vessel")
    if settlement["status"] != "CALCULATED":
        raise ApiError(
            409, "ERR_SETTLEMENT_NOT_CALCULATED", "dispute requires CALCULATED"
        )
    settlement["status"] = "DISPUTED"
    touch(settlement)
    return ok_object(pub(settlement))


@bp.route("/trip-settlements/<rid>/pay", methods=["POST"])
def pay_settlement(rid):
    _, role = auth()
    require_roles(role, CLERK)
    settlement = get_settlement(rid)
    if settlement["status"] != "APPROVED":
        raise ApiError(409, "ERR_SETTLEMENT_NOT_APPROVED", "pay requires APPROVED")
    settlement["status"] = "PAID"
    touch(settlement)
    trip = get_trip(settlement["trip_id"])
    if trip["status"] == "LANDING_FINALIZED":
        trip["status"] = "SETTLED"
        touch(trip)
    return ok_object(pub(settlement))

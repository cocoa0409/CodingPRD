"""Agreement lifecycle."""

from flask import Blueprint

import calc
import envelope
import serializers
import services
import store
import validate
from auth import ALL_ROLES, authenticate, require_owner
from errors import fail

bp = Blueprint("agreements", __name__)

PRODUCTS = ("SHORT_TERM_RENTAL", "FULL_SERVICE_LEASE")
AGREEMENT_STATUSES = ("DRAFT", "PENDING_INSURANCE", "PENDING_ALLOCATION", "RESERVED",
                      "ACTIVE", "PENDING_SETTLEMENT", "CLOSED", "CANCELLED")
CANCELLABLE = ("DRAFT", "PENDING_INSURANCE", "PENDING_ALLOCATION", "RESERVED")


def _agreement_owner_guard(caller, agreement):
    if caller.is_customer:
        require_owner(caller, agreement["customer_id"])
    elif caller.is_branch_manager:
        require_owner(caller, agreement["branch_id"])


# ---------------------------------------------------------------------------
# create / read / list
# ---------------------------------------------------------------------------
@bp.post("/fleet/agreements")
def create_agreement():
    caller = authenticate(["FleetAdmin", "Customer"])
    payload = validate.body()
    for field, getter in (("customer_id", services.get_customer),
                          ("branch_id", services.get_branch),
                          ("trailer_type_id", services.get_trailer_type)):
        if validate.present(payload, field) and isinstance(payload[field], str):
            getter(payload[field])

    customer_id = validate.req_string(payload, "customer_id")
    branch_id = validate.req_string(payload, "branch_id")
    product = validate.req_enum(payload, "product", PRODUCTS)
    type_id = validate.req_string(payload, "trailer_type_id")
    unit_count = validate.req_int(payload, "unit_count", minimum=1)
    start = validate.req_date(payload, "start_date")
    end = validate.req_date(payload, "end_date")
    term_months = validate.opt_int(payload, "term_months")
    if product == "SHORT_TERM_RENTAL" and term_months is not None:
        fail("ERR_INVALID_REQUEST", "term_months must be absent for SHORT_TERM_RENTAL")

    if end <= start:
        fail("ERR_INVALID_DATE_RANGE", "end_date must be strictly after start_date")
    if caller.is_customer:
        require_owner(caller, customer_id)

    rec = store.new_record()
    rec.update({
        "customer_id": customer_id,
        "branch_id": branch_id,
        "product": product,
        "trailer_type_id": type_id,
        "unit_count": unit_count,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "term_months": term_months,
        "status": "DRAFT",
        "rate_card_id": None,
        "insurance_certificate_id": None,
        "underwriting_risk_score": None,
        "quoted_total_cents": None,
        "final_total_cents": None,
        "purchase_option_status": "NOT_OFFERED",
        "purchase_option_price_cents": None,
        "cancel_reason": None,
    })
    store.agreements[rec["id"]] = rec
    return envelope.created(serializers.agreement(rec))


@bp.get("/fleet/agreements/<agreement_id>")
def read_agreement(agreement_id):
    authenticate(ALL_ROLES)
    return envelope.ok(serializers.agreement(services.get_agreement(agreement_id)))


@bp.get("/fleet/agreements")
def list_agreements():
    authenticate(ALL_ROLES)
    limit, offset = validate.pagination()
    customer_id = validate.query("customer_id")
    branch_id = validate.query("branch_id")
    type_id = validate.query("trailer_type_id")
    rate_card_id = validate.query("rate_card_id")
    certificate_id = validate.query("insurance_certificate_id")
    status = validate.query_enum("status", AGREEMENT_STATUSES)

    rows = []
    for a in store.agreements.values():
        if customer_id is not None and a["customer_id"] != customer_id:
            continue
        if branch_id is not None and a["branch_id"] != branch_id:
            continue
        if type_id is not None and a["trailer_type_id"] != type_id:
            continue
        if rate_card_id is not None and a.get("rate_card_id") != rate_card_id:
            continue
        if certificate_id is not None and a.get("insurance_certificate_id") != certificate_id:
            continue
        if status is not None and a["status"] != status:
            continue
        rows.append(a)
    rows = store.sorted_rows(rows)
    page = validate.paginate(rows, limit, offset)
    return envelope.listing([serializers.agreement(r) for r in page], limit, offset, len(rows))


# ---------------------------------------------------------------------------
# submit / verify insurance
# ---------------------------------------------------------------------------
@bp.post("/fleet/agreements/<agreement_id>/submit")
def submit_agreement(agreement_id):
    caller = authenticate(["FleetAdmin", "Customer"])
    agreement = services.get_agreement(agreement_id)
    validate.body()
    _agreement_owner_guard(caller, agreement)

    if agreement["status"] != "DRAFT":
        fail("ERR_AGREEMENT_NOT_DRAFT", "Agreement is not in DRAFT")
    if agreement["product"] == "FULL_SERVICE_LEASE":
        term = agreement.get("term_months")
        if term is None or term < 1:
            fail("ERR_INVALID_REQUEST", "term_months is required for a FULL_SERVICE_LEASE")

    customer = store.customers.get(agreement["customer_id"])
    result = calc.customer_risk_score(customer, "underwriting_snapshot")
    if result["risk_score"] > calc.RISK_SCORE_MAX:
        fail("ERR_RISK_SCORE_TOO_HIGH", "Underwriting risk score %s exceeds the tolerance"
             % result["risk_score"])

    agreement["underwriting_risk_score"] = result["risk_score"]
    agreement["status"] = "PENDING_INSURANCE"
    store.touch(agreement)
    return envelope.ok(serializers.agreement(agreement))


@bp.post("/fleet/agreements/<agreement_id>/verify-insurance")
def verify_insurance(agreement_id):
    caller = authenticate(["FleetAdmin", "BranchManager"])
    agreement = services.get_agreement(agreement_id)
    validate.body()
    _agreement_owner_guard(caller, agreement)

    if agreement["status"] != "PENDING_INSURANCE":
        fail("ERR_AGREEMENT_NOT_PENDING_INSURANCE", "Agreement is not awaiting insurance verification")

    start = store.parse_date(agreement["start_date"])
    end = store.parse_date(agreement["end_date"])
    qualifying = []
    for cert in store.certificates.values():
        if cert["customer_id"] != agreement["customer_id"]:
            continue
        if serializers.certificate_status(cert) != "ACTIVE":
            continue
        effective = store.parse_date(cert["effective_date"])
        expiry = store.parse_date(cert["expiry_date"])
        if effective is None or expiry is None:
            continue
        if effective <= start and expiry >= end:
            qualifying.append(cert)
    if not qualifying:
        fail("ERR_INSURANCE_INVALID", "No active certificate covers the agreement window")

    qualifying.sort(key=lambda c: (
        -store.parse_date(c["expiry_date"]).toordinal(), c["created_at"], c["_seq"]))
    chosen = qualifying[0]

    ttype = store.trailer_types.get(agreement["trailer_type_id"]) or {}
    if (chosen["physical_damage_limit_cents"] or 0) < (ttype.get("required_physical_damage_limit_cents") or 0):
        fail("ERR_INSURANCE_LIMIT_INSUFFICIENT", "Certificate physical damage limit is insufficient")

    agreement["insurance_certificate_id"] = chosen["id"]
    agreement["status"] = "PENDING_ALLOCATION"
    store.touch(agreement)
    return envelope.ok(serializers.agreement(agreement))


# ---------------------------------------------------------------------------
# allocation
# ---------------------------------------------------------------------------
def _create_unit(agreement, trailer):
    unit = store.new_record()
    unit.update({
        "agreement_id": agreement["id"],
        "trailer_id": trailer["id"],
        "return_branch_id": None,
        "status": "ALLOCATED",
        "planned_start_date": agreement["start_date"],
        "planned_end_date": agreement["end_date"],
        "checkout_date": None,
        "return_date": None,
        "checkout_hub_miles": None,
        "return_hub_miles": None,
        "peak_days": None,
        "excess_miles": None,
        "drop_charge_cents": None,
        "line_charge_cents": None,
    })
    store.agreement_units[unit["id"]] = unit
    return unit


@bp.post("/fleet/agreements/<agreement_id>/allocate")
def allocate(agreement_id):
    caller = authenticate(["FleetAdmin", "BranchManager"])
    agreement = services.get_agreement(agreement_id)
    payload = validate.body()
    expected_version = validate.req_int(payload, "expected_agreement_version")
    _agreement_owner_guard(caller, agreement)

    if expected_version != agreement["version"]:
        fail("ERR_STALE_VERSION", "expected_agreement_version does not match the agreement version")
    if agreement["status"] != "PENDING_ALLOCATION":
        fail("ERR_AGREEMENT_NOT_PENDING_ALLOCATION", "Agreement is not awaiting allocation")

    card = services.active_rate_card(agreement["branch_id"], agreement["trailer_type_id"],
                                     agreement["product"])
    if card is None:
        fail("ERR_RATE_CARD_NOT_FOUND", "No ACTIVE rate card for this branch, trailer type and product")

    branch = store.branches.get(agreement["branch_id"])
    need = agreement["unit_count"] - serializers.allocated_unit_count(agreement_id)
    pool = services.candidate_pool(agreement, branch)
    if len(pool) == 0:
        fail("ERR_NO_ELIGIBLE_TRAILER", "No eligible trailer for this agreement")
    if len(pool) < need:
        fail("ERR_INSUFFICIENT_AVAILABILITY", "Not enough eligible trailers for the remaining demand")

    for trailer in pool[:need]:
        _create_unit(agreement, trailer)
        trailer["availability_status"] = "ALLOCATED"
        store.touch(trailer)

    services.reserve_agreement(agreement, card)
    store.touch(agreement)
    return envelope.ok(serializers.agreement(agreement))


@bp.post("/fleet/agreements/<agreement_id>/units")
def attach_unit(agreement_id):
    caller = authenticate(["FleetAdmin", "BranchManager"])
    agreement = services.get_agreement(agreement_id)
    payload = validate.body()
    trailer = None
    if validate.present(payload, "trailer_id") and isinstance(payload["trailer_id"], str):
        trailer = services.get_trailer(payload["trailer_id"])
    validate.req_string(payload, "trailer_id")
    expected_version = validate.req_int(payload, "expected_agreement_version")
    _agreement_owner_guard(caller, agreement)

    if expected_version != agreement["version"]:
        fail("ERR_STALE_VERSION", "expected_agreement_version does not match the agreement version")
    if agreement["status"] != "PENDING_ALLOCATION":
        fail("ERR_AGREEMENT_NOT_PENDING_ALLOCATION", "Agreement is not awaiting allocation")

    start = store.parse_date(agreement["start_date"])
    end = store.parse_date(agreement["end_date"])

    if calc.trailer_service_status(trailer) != "SERVICEABLE":
        fail("ERR_TRAILER_OUT_OF_SERVICE", "Trailer is not serviceable")
    expires = store.parse_date(trailer.get("dot_expires_on"))
    if expires is None or not (expires > end):
        fail("ERR_DOT_INSPECTION_EXPIRED", "Trailer DOT inspection does not outlast the agreement")
    if services.trailer_window_conflict(trailer["id"], start, end):
        fail("ERR_TRAILER_WINDOW_CONFLICT", "Trailer is already booked over an overlapping window")
    if trailer["current_branch_id"] != agreement["branch_id"]:
        fail("ERR_TRAILER_BRANCH_MISMATCH", "Trailer does not stand at the agreement's branch")
    if trailer["availability_status"] not in ("AVAILABLE", "ALLOCATED"):
        fail("ERR_TRAILER_NOT_AVAILABLE", "Trailer is not available")
    allocated = serializers.allocated_unit_count(agreement_id)
    if allocated >= agreement["unit_count"]:
        fail("ERR_INSUFFICIENT_AVAILABILITY", "Agreement already holds its full unit count")

    card = None
    if allocated + 1 == agreement["unit_count"]:
        card = services.active_rate_card(agreement["branch_id"], agreement["trailer_type_id"],
                                         agreement["product"])
        if card is None:
            fail("ERR_RATE_CARD_NOT_FOUND",
                 "No ACTIVE rate card for this branch, trailer type and product")

    unit = _create_unit(agreement, trailer)
    if trailer["availability_status"] == "AVAILABLE":
        trailer["availability_status"] = "ALLOCATED"
        store.touch(trailer)
    if card is not None:
        services.reserve_agreement(agreement, card)
    store.touch(agreement)
    return envelope.created(serializers.agreement_unit(unit))


# ---------------------------------------------------------------------------
# activation / cancellation
# ---------------------------------------------------------------------------
@bp.post("/fleet/agreements/<agreement_id>/activate")
def activate(agreement_id):
    caller = authenticate(["FleetAdmin", "BranchManager"])
    agreement = services.get_agreement(agreement_id)
    payload = validate.body()
    checkout_date = validate.req_date(payload, "checkout_date")

    start = store.parse_date(agreement["start_date"])
    end = store.parse_date(agreement["end_date"])
    if not (start <= checkout_date < end):
        fail("ERR_INVALID_DATE_RANGE", "checkout_date must fall inside the agreement window")
    _agreement_owner_guard(caller, agreement)

    if agreement["status"] != "RESERVED":
        fail("ERR_AGREEMENT_NOT_RESERVED", "Agreement is not RESERVED")

    units = [u for u in services.units_of_agreement(agreement_id) if u["status"] == "ALLOCATED"]
    for unit in units:
        trailer = store.trailers.get(unit["trailer_id"])
        if trailer is None or trailer["availability_status"] != "ALLOCATED":
            fail("ERR_TRAILER_NOT_AVAILABLE", "A committed trailer is not standing allocated")

    customer = store.customers.get(agreement["customer_id"])
    if calc.outstanding_chargeback_cents(customer["id"]) > (customer["credit_limit_cents"] or 0):
        fail("ERR_CREDIT_LIMIT_EXCEEDED", "Customer outstanding chargeback balance exceeds its credit limit")

    on_rent = "ON_RENT" if agreement["product"] == "SHORT_TERM_RENTAL" else "ON_LEASE"
    for unit in units:
        trailer = store.trailers[unit["trailer_id"]]
        unit["status"] = "OUT"
        unit["checkout_date"] = checkout_date.isoformat()
        unit["checkout_hub_miles"] = trailer.get("hub_miles", 0)
        store.touch(unit)
        trailer["availability_status"] = on_rent
        store.touch(trailer)

    agreement["status"] = "ACTIVE"
    store.touch(agreement)
    return envelope.ok(serializers.agreement(agreement))


@bp.post("/fleet/agreements/<agreement_id>/cancel")
def cancel(agreement_id):
    caller = authenticate(["FleetAdmin", "BranchManager", "Customer"])
    agreement = services.get_agreement(agreement_id)
    payload = validate.body()
    reason = validate.req_string(payload, "reason")
    _agreement_owner_guard(caller, agreement)

    if agreement["status"] not in CANCELLABLE:
        fail("ERR_AGREEMENT_TERMINAL", "Agreement can no longer be cancelled")

    for unit in services.units_of_agreement(agreement_id):
        if unit["status"] != "ALLOCATED":
            continue
        unit["status"] = "RELEASED"
        store.touch(unit)
        trailer = store.trailers.get(unit["trailer_id"])
        if trailer is not None:
            services.release_trailer_if_idle(trailer)

    agreement["status"] = "CANCELLED"
    agreement["cancel_reason"] = reason
    store.touch(agreement)
    return envelope.ok(serializers.agreement(agreement))


# ---------------------------------------------------------------------------
# settlement and the lease-end purchase option
# ---------------------------------------------------------------------------
@bp.post("/fleet/agreements/<agreement_id>/settle")
def settle(agreement_id):
    authenticate(["FleetAdmin"])
    agreement = services.get_agreement(agreement_id)
    validate.body()

    if agreement["status"] != "PENDING_SETTLEMENT":
        fail("ERR_AGREEMENT_NOT_SETTLEABLE", "Agreement is not awaiting settlement")

    card = store.rate_cards.get(agreement.get("rate_card_id"))
    branch = store.branches.get(agreement["branch_id"])
    returned = [u for u in services.units_of_agreement(agreement_id) if u["status"] == "RETURNED"]

    final_total = 0
    for unit in returned:
        peak_days, excess_miles, drop, charge = calc.line_charge(unit, agreement, card, branch)
        unit["peak_days"] = peak_days
        unit["excess_miles"] = excess_miles
        unit["drop_charge_cents"] = drop
        unit["line_charge_cents"] = charge
        unit["status"] = "SETTLED"
        store.touch(unit)
        final_total += charge

    agreement["final_total_cents"] = final_total

    start = store.parse_date(agreement["start_date"])
    end = store.parse_date(agreement["end_date"])
    eligible = (agreement["product"] == "FULL_SERVICE_LEASE"
                and agreement["unit_count"] == 1
                and (end - start).days >= calc.MIN_PURCHASE_OPTION_TERM_DAYS)
    if eligible and agreement["purchase_option_status"] == "NOT_OFFERED":
        unit = returned[0] if returned else None
        if unit is not None:
            trailer = store.trailers.get(unit["trailer_id"])
            ttype = store.trailer_types.get(trailer["trailer_type_id"]) if trailer else None
            if trailer is not None and ttype is not None:
                agreement["purchase_option_status"] = "OFFERED"
                agreement["purchase_option_price_cents"] = calc.purchase_option_price(
                    final_total, trailer, ttype)

    agreement["status"] = "CLOSED"
    store.touch(agreement)
    return envelope.ok(serializers.agreement(agreement))


def _option_trailer(agreement):
    for unit in services.units_of_agreement(agreement["id"]):
        if unit["status"] in ("SETTLED", "RETURNED", "OUT", "ALLOCATED"):
            return store.trailers.get(unit["trailer_id"])
    return None


@bp.post("/fleet/agreements/<agreement_id>/exercise-purchase-option")
def exercise_purchase_option(agreement_id):
    caller = authenticate(["Customer"])
    agreement = services.get_agreement(agreement_id)
    validate.body()
    require_owner(caller, agreement["customer_id"])

    if agreement["purchase_option_status"] != "OFFERED":
        fail("ERR_PURCHASE_OPTION_NOT_OFFERED", "No purchase option is on offer")

    trailer = _option_trailer(agreement)
    if trailer is None or trailer["availability_status"] != "AVAILABLE":
        fail("ERR_TRAILER_NOT_AVAILABLE", "The leased trailer is not available for sale")

    trailer["availability_status"] = "SOLD"
    store.touch(trailer)
    agreement["purchase_option_status"] = "EXERCISED"
    store.touch(agreement)
    return envelope.ok(serializers.agreement(agreement))


@bp.post("/fleet/agreements/<agreement_id>/decline-purchase-option")
def decline_purchase_option(agreement_id):
    caller = authenticate(["Customer"])
    agreement = services.get_agreement(agreement_id)
    validate.body()
    require_owner(caller, agreement["customer_id"])

    if agreement["purchase_option_status"] != "OFFERED":
        fail("ERR_PURCHASE_OPTION_NOT_OFFERED", "No purchase option is on offer")

    agreement["purchase_option_status"] = "DECLINED"
    store.touch(agreement)
    return envelope.ok(serializers.agreement(agreement))

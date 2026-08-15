"""Child resources under a load: securement plans, permits, escort bookings,
crane appointments, delay events, scale tickets, fines, invoices."""
from flask import Blueprint, request

from store import store, new_entity, bump, new_id, now_iso, next_seq
from helpers import (
    api_error, ok, ok_list, require_roles, json_body, pub, paginate,
    pagination_params, v_str, v_int, v_enum, v_dt,
    ERR_NOT_FOUND, ERR_NOT_OWN, ERR_STALE, ERR_INVALID_REQUEST,
    ERR_LOAD_INVALID_STATE, ERR_INVALID_STATE, ERR_WLL, ERR_TARP,
    ERR_PERMIT_TYPE, ERR_DUPLICATE_PERMIT, ERR_ESCORT_OVERLAP,
    ERR_CRANE_OVERLAP, ERR_FINE_KIND, ERR_FINE_NOT_DISPUTABLE,
    ERR_INVOICE_EXISTS, ERR_INVOICE_NOT_ISSUED,
)
from logic import (
    STATES, PERMIT_TYPES, SECUREMENT_METHODS, ESCORT_POSITIONS, CRANE_SITES,
    DELAY_KINDS, FINE_KINDS, TRAILER_CATALOG, permit_fee_cents,
    latest_ticket_weight, standby_cents, whole_minutes, crane_windows_overlap,
    escort_line_cents, fuel_surcharge_cents, permit_type_required,
    permits_of, escorts_of, cranes_of, readiness_gate, scale_violation_cascade,
)

bp = Blueprint("children", __name__)


def load_or_404(load_id):
    load = store.loads.get(load_id)
    if load is None:
        api_error(ERR_NOT_FOUND, 404, "Load not found")
    return load


def check_shipper_owns_load(uid, role, load):
    if role == "Shipper" and load["customer_id"] != uid:
        api_error(ERR_NOT_OWN, 403, "Shipper does not own this resource")


def check_load_occ(data, load):
    """Priority 5 OCC: a present, integer expected_load_version that does not
    equal the load's current version is rejected with 412. A missing or
    non-integer value is left for body-sanity validation (priority 6)."""
    v = data.get("expected_load_version")
    if isinstance(v, int) and not isinstance(v, bool) and v != load["version"]:
        api_error(ERR_STALE, 412,
                  "expected_load_version does not match the load's current version")


# ---------------------------------------------------------------------------
# Securement plans
# ---------------------------------------------------------------------------

@bp.post("/heavy-haul/loads/<lid>/securement-plans")
def create_securement(lid):
    require_roles("Dispatcher")
    load = load_or_404(lid)
    data = json_body()
    method = v_enum(data, "method", SECUREMENT_METHODS)
    tiedown_count = v_int(data, "tiedown_count", min_value=2)
    wll = v_int(data, "wll_per_tiedown_lbs", min_value=1)
    if load["status"] not in ("PLANNED", "SURVEYED"):
        api_error(ERR_LOAD_INVALID_STATE, 409,
                  "Securement plans require a PLANNED or SURVEYED load")
    plan = new_entity()
    plan.update({
        "load_id": lid,
        "method": method,
        "tiedown_count": tiedown_count,
        "wll_per_tiedown_lbs": wll,
        "aggregate_wll_lbs": tiedown_count * wll,
        "status": "SUBMITTED",
    })
    store.securements[plan["id"]] = plan
    return ok(pub(plan), 201)


@bp.get("/heavy-haul/loads/<lid>/securement-plans")
def list_securement(lid):
    uid, role = require_roles("Shipper", "Dispatcher", "SafetyManager",
                              "BillingClerk", "PlatformAdmin")
    load = load_or_404(lid)
    check_shipper_owns_load(uid, role, load)
    limit, offset = pagination_params()
    records = [p for p in store.securements.values() if p["load_id"] == lid]
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/heavy-haul/securement-plans/<pid>/approve")
def approve_securement(pid):
    require_roles("SafetyManager")
    plan = store.securements.get(pid)
    if plan is None:
        api_error(ERR_NOT_FOUND, 404, "Securement plan not found")
    if plan["status"] != "SUBMITTED":
        api_error(ERR_INVALID_STATE, 409, "Plan must be SUBMITTED to approve")
    load = store.loads[plan["load_id"]]
    if plan["aggregate_wll_lbs"] < (load["gross_weight_lbs"] + 1) // 2:
        api_error(ERR_WLL, 422,
                  "Aggregate WLL must be at least half the gross weight")
    if load["cargo_requires_tarp"] and plan["method"] != "CHAINS_AND_TARPS":
        api_error(ERR_TARP, 422,
                  "Cargo requires tarping; method must be CHAINS_AND_TARPS")
    plan["status"] = "APPROVED"
    bump(plan)
    readiness_gate(load)
    return ok(pub(plan))


@bp.post("/heavy-haul/securement-plans/<pid>/reject")
def reject_securement(pid):
    require_roles("SafetyManager")
    plan = store.securements.get(pid)
    if plan is None:
        api_error(ERR_NOT_FOUND, 404, "Securement plan not found")
    if plan["status"] != "SUBMITTED":
        api_error(ERR_INVALID_STATE, 409, "Plan must be SUBMITTED to reject")
    plan["status"] = "REJECTED"
    bump(plan)
    return ok(pub(plan))


# ---------------------------------------------------------------------------
# Permits
# ---------------------------------------------------------------------------

@bp.post("/heavy-haul/loads/<lid>/permits")
def create_permit(lid):
    require_roles("PermitClerk")
    load = load_or_404(lid)
    data = json_body()
    check_load_occ(data, load)
    state_code = v_enum(data, "state_code", STATES)
    permit_type = v_enum(data, "permit_type", PERMIT_TYPES)
    v_int(data, "expected_load_version")
    if load["status"] not in ("SURVEYED", "CLEARED", "ON_HOLD"):
        api_error(ERR_LOAD_INVALID_STATE, 409,
                  "Permits require a SURVEYED, CLEARED, or ON_HOLD load")
    if not permit_type_required(load, permit_type):
        api_error(ERR_PERMIT_TYPE, 409,
                  "Permit type does not match the load's computed flags")
    if any(p["state_code"] == state_code and p["permit_type"] == permit_type
           and p["status"] in ("DRAFT", "FILED", "GRANTED")
           for p in permits_of(lid)):
        api_error(ERR_DUPLICATE_PERMIT, 409,
                  "A non-terminal permit already exists for this state and type")
    permit = new_entity()
    permit.update({
        "load_id": lid,
        "state_code": state_code,
        "permit_type": permit_type,
        "weight_basis_lbs": None,
        "fee_cents": None,
        "travel_window_start": None,
        "travel_window_end": None,
        "denial_reason": None,
        "status": "DRAFT",
        "_tws_dt": None,
        "_twe_dt": None,
    })
    store.permits[permit["id"]] = permit
    bump(load)
    return ok(pub(permit), 201)


@bp.get("/heavy-haul/loads/<lid>/permits")
def list_permits(lid):
    uid, role = require_roles("Shipper", "Dispatcher", "PermitClerk",
                              "StateAuthority", "SafetyManager", "BillingClerk",
                              "PlatformAdmin")
    load = load_or_404(lid)
    check_shipper_owns_load(uid, role, load)
    limit, offset = pagination_params()
    records = permits_of(lid)
    status = request.args.get("status")
    if status is not None:
        records = [p for p in records if p["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/heavy-haul/permits/<pid>/file")
def file_permit(pid):
    require_roles("PermitClerk")
    permit = store.permits.get(pid)
    if permit is None:
        api_error(ERR_NOT_FOUND, 404, "Permit not found")
    if permit["status"] not in ("DRAFT", "DENIED", "REVOKED"):
        api_error(ERR_INVALID_STATE, 409,
                  "Permit must be DRAFT, DENIED, or REVOKED to file")
    load = store.loads[permit["load_id"]]
    if load["status"] not in ("SURVEYED", "CLEARED", "ON_HOLD"):
        api_error(ERR_LOAD_INVALID_STATE, 409,
                  "Filing requires a SURVEYED, CLEARED, or ON_HOLD load")
    basis = latest_ticket_weight(load["id"])
    if basis is None:
        basis = load["gross_weight_lbs"]
    permit["weight_basis_lbs"] = basis
    permit["fee_cents"] = permit_fee_cents(permit["state_code"], permit["permit_type"],
                                           basis, load["width_in"])
    permit["status"] = "FILED"
    bump(permit)
    return ok(pub(permit))


@bp.post("/heavy-haul/permits/<pid>/grant")
def grant_permit(pid):
    require_roles("StateAuthority")
    permit = store.permits.get(pid)
    if permit is None:
        api_error(ERR_NOT_FOUND, 404, "Permit not found")
    data = json_body()
    raw_start, dt_start = v_dt(data, "travel_window_start")
    raw_end, dt_end = v_dt(data, "travel_window_end")
    if dt_end <= dt_start:
        api_error(ERR_INVALID_REQUEST, 400,
                  "travel_window_end must be after travel_window_start")
    if permit["status"] != "FILED":
        api_error(ERR_INVALID_STATE, 409, "Permit must be FILED to grant")
    permit["travel_window_start"] = raw_start
    permit["travel_window_end"] = raw_end
    permit["_tws_dt"] = dt_start
    permit["_twe_dt"] = dt_end
    permit["status"] = "GRANTED"
    bump(permit)
    readiness_gate(store.loads[permit["load_id"]])
    return ok(pub(permit))


@bp.post("/heavy-haul/permits/<pid>/deny")
def deny_permit(pid):
    require_roles("StateAuthority")
    permit = store.permits.get(pid)
    if permit is None:
        api_error(ERR_NOT_FOUND, 404, "Permit not found")
    data = json_body()
    reason = v_str(data, "denial_reason")
    if permit["status"] != "FILED":
        api_error(ERR_INVALID_STATE, 409, "Permit must be FILED to deny")
    permit["denial_reason"] = reason
    permit["status"] = "DENIED"
    bump(permit)
    return ok(pub(permit))


# ---------------------------------------------------------------------------
# Escort bookings
# ---------------------------------------------------------------------------

@bp.post("/heavy-haul/loads/<lid>/escort-bookings")
def create_escort(lid):
    require_roles("Dispatcher")
    load = load_or_404(lid)
    data = json_body()
    check_load_occ(data, load)
    provider = v_str(data, "provider_name")
    position = v_enum(data, "position", ESCORT_POSITIONS)
    raw_start, dt_start = v_dt(data, "scheduled_start")
    raw_end, dt_end = v_dt(data, "scheduled_end")
    if dt_end <= dt_start:
        api_error(ERR_INVALID_REQUEST, 400,
                  "scheduled_end must be after scheduled_start")
    rate = v_int(data, "rate_per_hour_cents", min_value=1)
    v_int(data, "expected_load_version")
    if load["status"] not in ("PLANNED", "SURVEYED", "CLEARED", "ON_HOLD"):
        api_error(ERR_LOAD_INVALID_STATE, 409,
                  "Escort booking requires a PLANNED, SURVEYED, CLEARED, or ON_HOLD load")
    # Half-open [start, end) overlap per provider, CONFIRMED bookings only.
    for b in store.escorts.values():
        if (b["provider_name"] == provider and b["status"] == "CONFIRMED"
                and dt_start < b["_end_dt"] and dt_end > b["_start_dt"]):
            api_error(ERR_ESCORT_OVERLAP, 409,
                      "Booking window overlaps a CONFIRMED booking for this provider")
    booking = new_entity()
    booking.update({
        "load_id": lid,
        "provider_name": provider,
        "position": position,
        "scheduled_start": raw_start,
        "scheduled_end": raw_end,
        "scheduled_minutes": whole_minutes(dt_start, dt_end),
        "rate_per_hour_cents": rate,
        "status": "CONFIRMED",
        "_start_dt": dt_start,
        "_end_dt": dt_end,
    })
    store.escorts[booking["id"]] = booking
    bump(load)
    readiness_gate(load)
    return ok(pub(booking), 201)


@bp.get("/heavy-haul/loads/<lid>/escort-bookings")
def list_escorts(lid):
    uid, role = require_roles("Shipper", "Dispatcher", "SafetyManager", "Driver",
                              "BillingClerk", "PlatformAdmin")
    load = load_or_404(lid)
    check_shipper_owns_load(uid, role, load)
    limit, offset = pagination_params()
    records = escorts_of(lid)
    status = request.args.get("status")
    if status is not None:
        records = [b for b in records if b["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/heavy-haul/escort-bookings/<bid>/cancel")
def cancel_escort(bid):
    require_roles("Dispatcher")
    booking = store.escorts.get(bid)
    if booking is None:
        api_error(ERR_NOT_FOUND, 404, "Escort booking not found")
    if booking["status"] != "CONFIRMED":
        api_error(ERR_INVALID_STATE, 409, "Booking must be CONFIRMED to cancel")
    booking["status"] = "CANCELLED"
    bump(booking)
    readiness_gate(store.loads[booking["load_id"]])
    return ok(pub(booking))


# ---------------------------------------------------------------------------
# Crane appointments
# ---------------------------------------------------------------------------

@bp.post("/heavy-haul/loads/<lid>/crane-appointments")
def create_crane(lid):
    require_roles("Dispatcher")
    load = load_or_404(lid)
    data = json_body()
    site = v_enum(data, "site", CRANE_SITES)
    crane_id = v_str(data, "crane_id")
    raw_start, dt_start = v_dt(data, "window_start")
    raw_end, dt_end = v_dt(data, "window_end")
    if dt_end <= dt_start:
        api_error(ERR_INVALID_REQUEST, 400,
                  "window_end must be after window_start")
    if load["status"] not in ("PLANNED", "SURVEYED", "CLEARED", "ON_HOLD"):
        api_error(ERR_LOAD_INVALID_STATE, 409,
                  "Crane appointments require a PLANNED, SURVEYED, CLEARED, or ON_HOLD load")
    for c in store.cranes.values():
        if (c["crane_id"] == crane_id and c["status"] == "SCHEDULED"
                and crane_windows_overlap(dt_start, dt_end, c["_ws_dt"], c["_we_dt"])):
            api_error(ERR_CRANE_OVERLAP, 409,
                      "Window overlaps another SCHEDULED appointment for this crane "
                      "(45-minute turnaround buffer)")
    appt = new_entity()
    appt.update({
        "load_id": lid,
        "site": site,
        "crane_id": crane_id,
        "window_start": raw_start,
        "window_end": raw_end,
        "status": "SCHEDULED",
        "_ws_dt": dt_start,
        "_we_dt": dt_end,
    })
    store.cranes[appt["id"]] = appt
    readiness_gate(load)
    return ok(pub(appt), 201)


@bp.get("/heavy-haul/loads/<lid>/crane-appointments")
def list_cranes(lid):
    uid, role = require_roles("Shipper", "Dispatcher", "SafetyManager", "Driver",
                              "PlatformAdmin")
    load = load_or_404(lid)
    check_shipper_owns_load(uid, role, load)
    limit, offset = pagination_params()
    records = cranes_of(lid)
    site = request.args.get("site")
    if site is not None:
        records = [c for c in records if c["site"] == site]
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Delay events
# ---------------------------------------------------------------------------

@bp.post("/heavy-haul/loads/<lid>/delay-events")
def create_delay(lid):
    require_roles("Driver")
    load = load_or_404(lid)
    data = json_body()
    kind = v_enum(data, "kind", DELAY_KINDS)
    raw_start, dt_start = v_dt(data, "started_at")
    raw_end, dt_end = v_dt(data, "ended_at")
    if dt_end <= dt_start:
        api_error(ERR_INVALID_REQUEST, 400, "ended_at must be after started_at")
    if load["status"] not in ("CLEARED", "ON_HOLD", "IN_TRANSIT"):
        api_error(ERR_LOAD_INVALID_STATE, 409,
                  "Delay events require a CLEARED, ON_HOLD, or IN_TRANSIT load")
    duration = whole_minutes(dt_start, dt_end)
    billable, amount = standby_cents(kind, duration)
    event = new_entity()
    event.update({
        "load_id": lid,
        "kind": kind,
        "started_at": raw_start,
        "ended_at": raw_end,
        "duration_minutes": duration,
        "billable_minutes": billable,
        "standby_amount_cents": amount,
    })
    store.delays[event["id"]] = event
    return ok(pub(event), 201)


@bp.get("/heavy-haul/loads/<lid>/delay-events")
def list_delays(lid):
    uid, role = require_roles("Shipper", "Dispatcher", "Driver", "BillingClerk",
                              "PlatformAdmin")
    load = load_or_404(lid)
    check_shipper_owns_load(uid, role, load)
    limit, offset = pagination_params()
    records = [d for d in store.delays.values() if d["load_id"] == lid]
    kind = request.args.get("kind")
    if kind is not None:
        records = [d for d in records if d["kind"] == kind]
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Scale tickets (immutable, append-only: id + created_at only)
# ---------------------------------------------------------------------------

@bp.post("/heavy-haul/loads/<lid>/scale-tickets")
def create_ticket(lid):
    require_roles("Driver")
    load = load_or_404(lid)
    data = json_body()
    measured = v_int(data, "measured_gross_lbs", min_value=1)
    raw_weighed, _dt_weighed = v_dt(data, "weighed_at")
    if load["status"] not in ("CLEARED", "IN_TRANSIT", "ON_HOLD"):
        api_error(ERR_LOAD_INVALID_STATE, 409,
                  "Scale tickets require a CLEARED, IN_TRANSIT, or ON_HOLD load")
    excess = max(0, measured - load["gross_weight_lbs"])
    is_violation = measured * 100 > load["gross_weight_lbs"] * 103
    ticket = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
        "load_id": lid,
        "measured_gross_lbs": measured,
        "weighed_at": raw_weighed,
        "excess_lbs": excess,
        "is_violation": is_violation,
    }
    store.tickets[ticket["id"]] = ticket
    if is_violation:
        scale_violation_cascade(load, ticket)
    return ok(pub(ticket), 201)


@bp.get("/heavy-haul/loads/<lid>/scale-tickets")
def list_tickets(lid):
    uid, role = require_roles("Shipper", "Dispatcher", "SafetyManager", "Driver",
                              "BillingClerk", "PlatformAdmin")
    load = load_or_404(lid)
    check_shipper_owns_load(uid, role, load)
    limit, offset = pagination_params()
    records = [t for t in store.tickets.values() if t["load_id"] == lid]
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Fines
# ---------------------------------------------------------------------------

@bp.post("/heavy-haul/loads/<lid>/fines")
def create_fine(lid):
    require_roles("Driver", "SafetyManager")
    load = load_or_404(lid)
    data = json_body()
    kind = v_enum(data, "kind", FINE_KINDS)
    amount = v_int(data, "amount_cents", min_value=1)
    description = v_str(data, "description")
    if load["status"] not in ("CLEARED", "ON_HOLD", "IN_TRANSIT", "DELIVERED"):
        api_error(ERR_LOAD_INVALID_STATE, 409,
                  "Fines require a CLEARED, ON_HOLD, IN_TRANSIT, or DELIVERED load")
    if kind == "OVERWEIGHT":
        api_error(ERR_FINE_KIND, 409,
                  "OVERWEIGHT fines are system-created via scale tickets only")
    fine = new_entity()
    fine.update({
        "load_id": lid,
        "kind": kind,
        "amount_cents": amount,
        "description": description,
        "liable_party": "CARRIER",
        "status": "PENDING",
    })
    store.fines[fine["id"]] = fine
    return ok(pub(fine), 201)


@bp.get("/heavy-haul/loads/<lid>/fines")
def list_fines(lid):
    uid, role = require_roles("Shipper", "Dispatcher", "SafetyManager", "Driver",
                              "BillingClerk", "PlatformAdmin")
    load = load_or_404(lid)
    check_shipper_owns_load(uid, role, load)
    limit, offset = pagination_params()
    records = [f for f in store.fines.values() if f["load_id"] == lid]
    status = request.args.get("status")
    if status is not None:
        records = [f for f in records if f["status"] == status]
    kind = request.args.get("kind")
    if kind is not None:
        records = [f for f in records if f["kind"] == kind]
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/heavy-haul/fines/<fid>/dispute")
def dispute_fine(fid):
    uid, role = require_roles("Shipper")
    fine = store.fines.get(fid)
    if fine is None:
        api_error(ERR_NOT_FOUND, 404, "Fine not found")
    load = store.loads[fine["load_id"]]
    check_shipper_owns_load(uid, role, load)
    if fine["status"] != "PENDING" or fine["liable_party"] != "CUSTOMER":
        api_error(ERR_FINE_NOT_DISPUTABLE, 409,
                  "Only a PENDING, customer-liable fine may be disputed")
    fine["status"] = "DISPUTED"
    bump(fine)
    return ok(pub(fine))


@bp.post("/heavy-haul/fines/<fid>/resolve")
def resolve_fine(fid):
    require_roles("SafetyManager")
    fine = store.fines.get(fid)
    if fine is None:
        api_error(ERR_NOT_FOUND, 404, "Fine not found")
    data = json_body()
    resolution = v_enum(data, "resolution", ("CUSTOMER_LIABLE", "CARRIER_LIABLE"))
    adjusted = v_int(data, "adjusted_amount_cents", required=False, min_value=1)
    if fine["status"] not in ("PENDING", "DISPUTED"):
        api_error(ERR_INVALID_STATE, 409,
                  "Fine must be PENDING or DISPUTED to resolve")
    if resolution == "CUSTOMER_LIABLE":
        fine["liable_party"] = "CUSTOMER"
        if adjusted is not None:
            fine["amount_cents"] = adjusted
        fine["status"] = "RESOLVED_CUSTOMER_LIABLE"
    else:
        fine["liable_party"] = "CARRIER"
        fine["status"] = "RESOLVED_CARRIER_LIABLE"
    bump(fine)
    return ok(pub(fine))


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@bp.post("/heavy-haul/loads/<lid>/invoices")
def create_invoice(lid):
    require_roles("BillingClerk")
    load = load_or_404(lid)
    if load["status"] != "DELIVERED":
        api_error(ERR_LOAD_INVALID_STATE, 409,
                  "Invoices require a DELIVERED load")
    if any(i["load_id"] == lid and i["status"] == "ISSUED"
           for i in store.invoices.values()):
        api_error(ERR_INVOICE_EXISTS, 409,
                  "Load already has an ISSUED invoice")
    # Final variant of the pinned invoice_total evaluation order.
    linehaul = load["route_miles"] * TRAILER_CATALOG[load["trailer_type"]]["cost_per_mile_cents"]
    permits = sum(p["fee_cents"] for p in permits_of(lid) if p["status"] == "GRANTED")
    escorts = sum(escort_line_cents(b) for b in escorts_of(lid)
                  if b["status"] == "COMPLETED")
    standby = sum(d["standby_amount_cents"] for d in store.delays.values()
                  if d["load_id"] == lid)
    swept = [f for f in store.fines.values()
             if f["load_id"] == lid and f["liable_party"] == "CUSTOMER"
             and f["status"] in ("PENDING", "RESOLVED_CUSTOMER_LIABLE")]
    fines = sum(f["amount_cents"] for f in swept)
    subtotal = linehaul + permits + escorts + standby + fines
    fuel = fuel_surcharge_cents(subtotal)
    invoice = new_entity()
    invoice.update({
        "load_id": lid,
        "linehaul_cents": linehaul,
        "permits_cents": permits,
        "escorts_cents": escorts,
        "standby_cents": standby,
        "fines_cents": fines,
        "subtotal_cents": subtotal,
        "fuel_surcharge_cents": fuel,
        "total_cents": subtotal + fuel,
        "status": "ISSUED",
        "_swept_fine_ids": [f["id"] for f in swept],
    })
    store.invoices[invoice["id"]] = invoice
    for f in swept:
        f["status"] = "APPLIED"
        bump(f)
    cust = store.customers[load["customer_id"]]
    cust["outstanding_balance_cents"] += invoice["total_cents"]
    if cust["outstanding_balance_cents"] > cust["credit_limit_cents"]:
        cust["status"] = "SUSPENDED"
    bump(cust)
    return ok(pub(invoice), 201)


@bp.get("/heavy-haul/loads/<lid>/invoices")
def list_invoices(lid):
    uid, role = require_roles("Shipper", "Dispatcher", "BillingClerk", "PlatformAdmin")
    load = load_or_404(lid)
    check_shipper_owns_load(uid, role, load)
    limit, offset = pagination_params()
    records = [i for i in store.invoices.values() if i["load_id"] == lid]
    page, total = paginate(records, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/heavy-haul/invoices/<iid>/pay")
def pay_invoice(iid):
    require_roles("BillingClerk")
    invoice = store.invoices.get(iid)
    if invoice is None:
        api_error(ERR_NOT_FOUND, 404, "Invoice not found")
    data = json_body()
    amount = v_int(data, "amount_cents")
    if amount != invoice["total_cents"]:
        api_error(ERR_INVALID_REQUEST, 400,
                  "amount_cents must equal the invoice total exactly")
    if invoice["status"] != "ISSUED":
        api_error(ERR_INVOICE_NOT_ISSUED, 409, "Invoice is not ISSUED")
    invoice["status"] = "PAID"
    bump(invoice)
    cust = store.customers[store.loads[invoice["load_id"]]["customer_id"]]
    cust["outstanding_balance_cents"] -= invoice["total_cents"]
    bump(cust)
    return ok(pub(invoice))


@bp.post("/heavy-haul/invoices/<iid>/void")
def void_invoice(iid):
    require_roles("BillingClerk")
    invoice = store.invoices.get(iid)
    if invoice is None:
        api_error(ERR_NOT_FOUND, 404, "Invoice not found")
    if invoice["status"] != "ISSUED":
        api_error(ERR_INVOICE_NOT_ISSUED, 409, "Invoice is not ISSUED")
    invoice["status"] = "VOID"
    bump(invoice)
    cust = store.customers[store.loads[invoice["load_id"]]["customer_id"]]
    cust["outstanding_balance_cents"] -= invoice["total_cents"]
    bump(cust)
    for f in store.fines.values():
        if f["id"] in invoice["_swept_fine_ids"] and f["status"] == "APPLIED":
            f["status"] = "PENDING"
            bump(f)
    return ok(pub(invoice))

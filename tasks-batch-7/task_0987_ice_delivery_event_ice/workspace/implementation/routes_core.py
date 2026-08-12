"""Routes: logical clock, depots (+ run-ops), customers, certifications,
price books, surge windows."""
import core
import domain
from core import (ALL_ROLES, agent_owns, as_enum, as_int, as_str,
                  authenticate, authorize, fail, get_body, need, ok, paginate,
                  parse_date_str, parse_dt_str, reject_unknown)
from server import app, fetch, new_record
from store import BOOKS, CERTS, CUSTOMERS, DEPOTS, SURGE_WINDOWS
from views import (book_view, cert_view, customer_view, depot_view,
                   window_view)


# ---------------------------------------------------------------------------
# POST /_clock/set_current_utc (PlatformAdmin)
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate_role = authenticate()
    authorize(authenticate_role[1], {"PlatformAdmin"})
    data = get_body()
    reject_unknown(data, {"to_iso8601"})
    dt = parse_dt_str(need(data, "to_iso8601"), "to_iso8601")
    core.set_clock(dt)
    return ok({"current_utc": core.fmt_instant(dt)})


# ---------------------------------------------------------------------------
# Depots
# ---------------------------------------------------------------------------
@app.route("/depots", methods=["POST"])
def create_depot():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    data = get_body()
    reject_unknown(data, {"name", "freezer_capacity_pallets"})
    name = as_str(need(data, "name"), "name")
    cap = as_int(need(data, "freezer_capacity_pallets"),
                 "freezer_capacity_pallets", minimum=1)
    d = new_record()
    d.update({"name": name, "freezer_capacity_pallets": cap, "ops_run_index": 0})
    DEPOTS[d["id"]] = d
    return ok(depot_view(d), 201)


@app.route("/depots/<depot_id>", methods=["GET"])
def get_depot(depot_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    return ok(depot_view(fetch(DEPOTS, depot_id, "Depot")))


@app.route("/depots/<depot_id>/run-ops", methods=["POST"])
def run_ops(depot_id):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    depot = fetch(DEPOTS, depot_id, "Depot")
    result = domain.run_ops_sweeps(depot)
    depot["ops_run_index"] += 1
    depot["version"] += 1
    depot["updated_at"] = core.stamp()
    data = {"ops_run_index": depot["ops_run_index"]}
    data.update(result)
    return ok(data)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@app.route("/customers", methods=["POST"])
def create_customer():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    data = get_body()
    reject_unknown(data, {"account_name", "kind", "tier", "credit_terms",
                          "credit_limit_cents"})
    name = as_str(need(data, "account_name"), "account_name")
    kind = as_enum(need(data, "kind"), "kind", {"BAR_RESTAURANT", "EVENT_ORGANIZER"})
    tier = as_enum(need(data, "tier"), "tier", {"STANDARD", "PRIORITY"})
    terms = as_enum(need(data, "credit_terms"), "credit_terms",
                    {"PREPAID", "NET_15", "NET_30"})
    limit = as_int(need(data, "credit_limit_cents"), "credit_limit_cents", minimum=0)
    c = new_record()
    c.update({"account_name": name, "kind": kind, "tier": tier,
              "credit_terms": terms, "credit_limit_cents": limit,
              "credit_balance_cents": 0})
    CUSTOMERS[c["id"]] = c
    return ok(customer_view(c), 201)


@app.route("/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    c = fetch(CUSTOMERS, customer_id, "Customer")
    agent_owns(uid, role, c["id"])
    return ok(customer_view(c))


# ---------------------------------------------------------------------------
# Handler certifications
# ---------------------------------------------------------------------------
@app.route("/customers/<customer_id>/certifications", methods=["POST"])
def create_cert(customer_id):
    uid, role = authenticate()
    authorize(role, {"SafetyOfficer"})
    data = get_body()
    reject_unknown(data, {"handler_name", "certificate_number",
                          "max_dry_ice_lbs", "expires_at"})
    handler = as_str(need(data, "handler_name"), "handler_name")
    number = as_str(need(data, "certificate_number"), "certificate_number")
    max_lbs = as_int(need(data, "max_dry_ice_lbs"), "max_dry_ice_lbs", minimum=1)
    expires = parse_dt_str(need(data, "expires_at"), "expires_at")
    fetch(CUSTOMERS, customer_id, "Customer")  # rung 4: path existence
    c = new_record()
    c.update({"customer_id": customer_id, "handler_name": handler,
              "certificate_number": number, "max_dry_ice_lbs": max_lbs,
              "expires_at": expires, "status": "ACTIVE"})
    CERTS[c["id"]] = c
    return ok(cert_view(c), 201)


@app.route("/customers/<customer_id>/certifications", methods=["GET"])
def list_certs(customer_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    c = fetch(CUSTOMERS, customer_id, "Customer")
    agent_owns(uid, role, c["id"])
    items = sorted((x for x in CERTS.values() if x["customer_id"] == customer_id),
                   key=lambda x: x["_seq"])
    return paginate(items, cert_view)


@app.route("/certifications/<cert_id>/suspend", methods=["POST"])
def suspend_cert(cert_id):
    uid, role = authenticate()
    authorize(role, {"SafetyOfficer"})
    c = fetch(CERTS, cert_id, "HandlerCertification")
    if c["status"] == "EXPIRED":
        fail("ERR_ALREADY_TERMINAL", 409, "Certification is EXPIRED")
    if c["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", 409, "Only an ACTIVE certification can be suspended")
    c["status"] = "SUSPENDED"
    c["version"] += 1
    c["updated_at"] = core.stamp()
    return ok(cert_view(c))


@app.route("/certifications/<cert_id>/reinstate", methods=["POST"])
def reinstate_cert(cert_id):
    uid, role = authenticate()
    authorize(role, {"SafetyOfficer"})
    c = fetch(CERTS, cert_id, "HandlerCertification")
    if c["status"] == "EXPIRED":
        fail("ERR_ALREADY_TERMINAL", 409, "Certification is EXPIRED")
    if c["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE", 409, "Only a SUSPENDED certification can be reinstated")
    if c["expires_at"] < core.now():
        fail("ERR_INVALID_STATE", 409, "Cannot reinstate an expired certification")
    c["status"] = "ACTIVE"
    c["version"] += 1
    c["updated_at"] = core.stamp()
    return ok(cert_view(c))


# ---------------------------------------------------------------------------
# Price books
# ---------------------------------------------------------------------------
def _parse_book_lines(data):
    lines = need(data, "lines")
    if not isinstance(lines, list):
        fail("ERR_INVALID_REQUEST", 400, "Field 'lines' must be an array")
    out = []
    for row in lines:
        if not isinstance(row, dict):
            fail("ERR_INVALID_REQUEST", 400, "Each price-book line must be an object")
        reject_unknown(row, {"product_form", "packaging", "tier_min_units",
                             "tier_max_units", "unit_price_cents"})
        pf = as_enum(need(row, "product_form"), "product_form", core.PRODUCT_FORMS)
        pk = as_enum(need(row, "packaging"), "packaging", core.PACKAGINGS)
        tmin = as_int(need(row, "tier_min_units"), "tier_min_units", minimum=0)
        tmax = row.get("tier_max_units")
        if tmax is not None:
            tmax = as_int(tmax, "tier_max_units", minimum=0)
            if tmax < tmin:
                fail("ERR_INVALID_REQUEST", 400,
                     "tier_max_units must be >= tier_min_units")
        price = as_int(need(row, "unit_price_cents"), "unit_price_cents", minimum=0)
        out.append({"product_form": pf, "packaging": pk, "tier_min_units": tmin,
                    "tier_max_units": tmax, "unit_price_cents": price})
    return out


def _parse_discount_tiers(data):
    tiers = need(data, "volume_discount_tiers")
    if not isinstance(tiers, list):
        fail("ERR_INVALID_REQUEST", 400, "Field 'volume_discount_tiers' must be an array")
    out = []
    for t in tiers:
        if not isinstance(t, dict):
            fail("ERR_INVALID_REQUEST", 400, "Each discount tier must be an object")
        reject_unknown(t, {"threshold_cents", "discount_bps"})
        th = as_int(need(t, "threshold_cents"), "threshold_cents", minimum=0)
        bps = as_int(need(t, "discount_bps"), "discount_bps", minimum=0)
        out.append({"threshold_cents": th, "discount_bps": bps})
    return out


@app.route("/price-books", methods=["POST"])
def create_book():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    data = get_body()
    reject_unknown(data, {"scope_label", "effective_from", "lines",
                          "pallet_deposit_cents", "delivery_fee_cents",
                          "free_delivery_threshold_cents",
                          "volume_discount_tiers", "surge_surcharge_bps"})
    label = as_str(need(data, "scope_label"), "scope_label")
    eff = parse_dt_str(need(data, "effective_from"), "effective_from")
    lines = _parse_book_lines(data)
    deposit = as_int(need(data, "pallet_deposit_cents"), "pallet_deposit_cents", minimum=0)
    fee = as_int(need(data, "delivery_fee_cents"), "delivery_fee_cents", minimum=0)
    threshold = as_int(need(data, "free_delivery_threshold_cents"),
                       "free_delivery_threshold_cents", minimum=0)
    tiers = _parse_discount_tiers(data)
    surge_bps = as_int(need(data, "surge_surcharge_bps"), "surge_surcharge_bps", minimum=0)
    b = new_record()
    b.update({"scope_label": label, "effective_from": eff, "lines": lines,
              "pallet_deposit_cents": deposit, "delivery_fee_cents": fee,
              "free_delivery_threshold_cents": threshold,
              "volume_discount_tiers": tiers, "surge_surcharge_bps": surge_bps,
              "status": "SCHEDULED"})
    # A book activates immediately iff effective_from <= clock (PRD §3.1).
    if eff <= core.now():
        for other in BOOKS.values():
            if other["status"] == "ACTIVE":
                other["status"] = "SUPERSEDED"
                other["version"] += 1
                other["updated_at"] = core.stamp()
        b["status"] = "ACTIVE"
    BOOKS[b["id"]] = b
    return ok(book_view(b), 201)


@app.route("/price-books", methods=["GET"])
def list_books():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    items = sorted(BOOKS.values(), key=lambda b: b["_seq"])
    status = core.request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return paginate(items, book_view)


# ---------------------------------------------------------------------------
# Surge windows
# ---------------------------------------------------------------------------
@app.route("/surge-windows", methods=["POST"])
def create_window():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    data = get_body()
    reject_unknown(data, {"depot_id", "start_date", "end_date",
                          "admission_policy", "daily_pallet_cap"})
    depot_id = as_str(need(data, "depot_id"), "depot_id")
    start = parse_date_str(need(data, "start_date"), "start_date")
    end = parse_date_str(need(data, "end_date"), "end_date")
    if start > end:
        fail("ERR_INVALID_REQUEST", 400, "start_date must be <= end_date")
    policy = as_enum(need(data, "admission_policy"), "admission_policy",
                     {"OPEN", "RATIONED", "CLOSED"})
    cap = data.get("daily_pallet_cap")
    if policy == "RATIONED":
        # required exactly when the policy is RATIONED (PRD §3.1)
        cap = as_int(need(data, "daily_pallet_cap"), "daily_pallet_cap", minimum=1)
    elif cap is not None:
        cap = as_int(cap, "daily_pallet_cap", minimum=1)
    fetch(DEPOTS, depot_id, "Depot")  # rung 5: body FK existence
    w = new_record()
    w.update({"depot_id": depot_id, "start_date": start, "end_date": end,
              "admission_policy": policy, "daily_pallet_cap": cap})
    SURGE_WINDOWS[w["id"]] = w
    return ok(window_view(w), 201)


@app.route("/depots/<depot_id>/surge-windows", methods=["GET"])
def list_windows(depot_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    fetch(DEPOTS, depot_id, "Depot")
    items = sorted((w for w in SURGE_WINDOWS.values() if w["depot_id"] == depot_id),
                   key=lambda w: w["_seq"])
    status = core.request.args.get("status")
    if status is not None:
        items = [w for w in items if domain.window_status(w) == status]
    return paginate(items, window_view)

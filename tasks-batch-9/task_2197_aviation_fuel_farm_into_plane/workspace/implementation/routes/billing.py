"""Stock reconciliation runs and airline invoicing."""
from flask import Blueprint, request

import calc
import services as svc
from authz import (auth, body, enum, opt_str, out_of_range, req_dt, req_int,
                   req_num, req_str, resolve, resolve_ref, rng)
from core import (ApiError, D, base_row, cents, created, db, f2, f4, fmt_dt,
                  listing, now, now_iso, ok, parse_dt, public, q2, q4, touch)

bp = Blueprint("billing", __name__)

MEASURABLE = ("IN_SERVICE", "ISOLATED")


# ------------------------------------------------------------ reconciliation
@bp.post("/fuel-farms/<fid>/reconciliation-runs")
def create_run(fid):
    auth("FarmOperator")
    farm = resolve(db.farms, fid, "Fuel farm not found")
    data = body()
    start = req_dt(data, "period_start_utc")
    end = req_dt(data, "period_end_utc")
    if end <= start:
        out_of_range("period_end_utc must be later than period_start_utc")

    run = base_row()
    run.update({
        "fuel_farm_id": farm["id"],
        "period_start_utc": fmt_dt(start),
        "period_end_utc": fmt_dt(end),
        "tank_measurements": [],
        "receipts_net_liters": 0.0,
        "uplifts_net_liters": 0.0,
        "throughput_liters": 0.0,
        "variance_liters": None,
        "variance_pct_throughput_basis": None,
        "variance_pct_opening_stock_basis": None,
        "adjustment_liters": None,
        "variance_override_reason": None,
        "posted_by_user_id": None,
        "status": "OPEN",
    })
    db.runs[run["id"]] = run
    return created(public(run))


@bp.get("/fuel-farms/<fid>/reconciliation-runs")
def list_runs(fid):
    auth("ConsortiumAdmin", "FarmOperator")
    farm = resolve(db.farms, fid, "Fuel farm not found")
    rows = [r for r in db.runs.values() if r["fuel_farm_id"] == farm["id"]]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows)


@bp.post("/reconciliation-runs/<rid>/measure")
def measure_run(rid):
    auth("FarmOperator")
    run = resolve(db.runs, rid, "Reconciliation run not found")
    farm = db.farms.get(run["fuel_farm_id"])
    data = body()

    raw = data.get("tank_measurements")
    if not isinstance(raw, list):
        raise ApiError("ERR_INVALID_PAYLOAD", "tank_measurements must be an array")
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            raise ApiError("ERR_INVALID_PAYLOAD", "tank_measurements entries must be objects")
        tank_id = req_str(item, "storage_tank_id")
        measured = req_num(item, "measured_volume_liters")
        temperature = req_num(item, "temperature_c")
        rng(measured, "measured_volume_liters", minimum=0)
        rng(temperature, "temperature_c", minimum=-20, maximum=60)
        entries.append((tank_id, measured, temperature))

    svc.terminal_guard("run", run["status"])
    if run["status"] != "OPEN":
        raise ApiError("ERR_INVALID_RUN_STATE",
                       "Run status %s cannot accept measurements" % run["status"])

    if now() < parse_dt(run["period_end_utc"]):
        raise ApiError("ERR_PERIOD_NOT_ELAPSED",
                       "The reconciliation period has not yet elapsed")

    expected_tanks = [t for t in calc.farm_tanks(farm["id"])
                      if t["service_status"] in MEASURABLE]
    expected_ids = set(t["id"] for t in expected_tanks)
    posted_ids = [e[0] for e in entries]
    if len(posted_ids) != len(set(posted_ids)) or set(posted_ids) != expected_ids:
        raise ApiError("ERR_MEASUREMENT_SET_INCOMPLETE",
                       "Exactly one measurement is required for each IN_SERVICE or "
                       "ISOLATED tank at the farm")

    by_id = dict((e[0], e) for e in entries)
    measurements = []
    total_variance = D(0)
    book_total = D(0)
    for tank in sorted(expected_tanks, key=lambda t: (t["created_at"], t["_seq"])):
        _tid, measured, temperature = by_id[tank["id"]]
        calc.recompute_tank(tank)
        vcf = calc.vcf_for(tank["density_kg_per_m3"], temperature)
        corrected = q2(D(measured) * vcf)
        book = D(tank["book_volume_liters"])
        variance = q2(corrected - book)
        total_variance += variance
        book_total += book
        measurements.append({
            "storage_tank_id": tank["id"],
            "measured_volume_liters": f2(measured),
            "temperature_c": float(D(temperature)),
            "volume_correction_factor": float(vcf),
            "corrected_volume_liters": f2(corrected),
            "book_volume_liters": f2(book),
            "variance_liters": f2(variance),
            "adjustment_liters": None,
        })
        tank["last_gauge_volume_liters"] = f2(measured)
        tank["last_gauge_at_utc"] = now_iso()
        touch(tank)

    start = parse_dt(run["period_start_utc"])
    end = parse_dt(run["period_end_utc"])
    receipts_net = D(0)
    for tank in calc.farm_tanks(farm["id"]):
        for r in calc.tank_receipts(tank["id"]):
            if r["status"] != "RELEASED" or not r.get("released_at_utc"):
                continue
            rel = parse_dt(r["released_at_utc"])
            if start <= rel < end:
                receipts_net += D(r["net_volume_liters"])
    uplifts_net = D(0)
    for tank in calc.farm_tanks(farm["id"]):
        for u in calc.tank_uplifts(tank["id"]):
            if u["status"] not in ("POSTED", "BILLED"):
                continue
            cr = parse_dt(u["created_at"])
            if start <= cr < end:
                uplifts_net += D(u["net_liters"])
    receipts_net = q2(receipts_net)
    uplifts_net = q2(uplifts_net)
    throughput = q2(receipts_net + uplifts_net)
    variance = q2(total_variance)
    opening = q2(book_total - receipts_net + uplifts_net)

    tp_denom = throughput if throughput > D("1.0") else D("1.0")
    op_denom = opening if opening > D("1.0") else D("1.0")
    pct_tp = q4(abs(variance) / tp_denom * D(100))
    pct_op = q4(abs(variance) / op_denom * D(100))

    run["tank_measurements"] = measurements
    run["receipts_net_liters"] = f2(receipts_net)
    run["uplifts_net_liters"] = f2(uplifts_net)
    run["throughput_liters"] = f2(throughput)
    run["variance_liters"] = f2(variance)
    run["variance_pct_throughput_basis"] = f4(pct_tp)
    run["variance_pct_opening_stock_basis"] = f4(pct_op)
    run["status"] = "MEASURED"
    touch(run)
    if pct_tp > D("0.50"):
        run["status"] = "VARIANCE_HOLD"
        touch(run)
    return ok(public(run))


@bp.post("/reconciliation-runs/<rid>/post")
def post_run(rid):
    uid, role = auth("ConsortiumAdmin")
    run = resolve(db.runs, rid, "Reconciliation run not found")
    farm = db.farms.get(run["fuel_farm_id"])
    data = body()
    override = data.get("variance_override_reason")
    if override is not None and not isinstance(override, str):
        raise ApiError("ERR_INVALID_PAYLOAD", "variance_override_reason must be a string")

    svc.terminal_guard("run", run["status"])
    if run["status"] not in ("MEASURED", "VARIANCE_HOLD"):
        raise ApiError("ERR_INVALID_RUN_STATE",
                       "Run status %s cannot be posted" % run["status"])
    for tank in calc.farm_tanks(farm["id"]):
        if tank["quality_status"] == "QUARANTINED":
            raise ApiError("ERR_INVALID_TANK_STATE",
                           "A storage tank at this farm is QUARANTINED")
    if run["status"] == "VARIANCE_HOLD" and not override:
        raise ApiError("ERR_VARIANCE_OVERRIDE_REQUIRED",
                       "A non-empty variance_override_reason is required to post a held run")

    for m in run["tank_measurements"]:
        m["adjustment_liters"] = m["variance_liters"]
    run["adjustment_liters"] = run["variance_liters"]
    if override:
        run["variance_override_reason"] = override
    run["posted_by_user_id"] = uid
    run["status"] = "POSTED"
    touch(run)
    for m in run["tank_measurements"]:
        tank = db.tanks.get(m["storage_tank_id"])
        if tank is not None:
            calc.recompute_tank(tank)
            touch(tank)
    svc.apply_posture_change(farm)
    touch(farm)
    return ok(public(run))


# ------------------------------------------------------------------ invoices
def swept(invoice):
    return calc.invoice_tickets(invoice["id"])


@bp.post("/invoices")
def create_invoice():
    auth("BillingClerk")
    data = body()
    account = resolve_ref(db.accounts, data.get("airline_account_id"),
                          "Airline account not found") \
        if isinstance(data.get("airline_account_id"), str) else None
    replaces = resolve_ref(db.invoices, data.get("replaces_invoice_id"),
                          "Replaced invoice not found") \
        if isinstance(data.get("replaces_invoice_id"), str) else None

    account_id = req_str(data, "airline_account_id")
    start = req_dt(data, "period_start_utc")
    end = req_dt(data, "period_end_utc")
    expected = req_int(data, "expected_airline_account_version")
    if end <= start:
        out_of_range("period_end_utc must be later than period_start_utc")

    if int(expected) != int(account["version"]):
        raise ApiError("ERR_STALE_ACCOUNT_VERSION",
                       "expected_airline_account_version %s does not match %s"
                       % (expected, account["version"]))

    tickets = []
    for u in calc.by_created(calc.account_uplifts(account_id)):
        if u["status"] != "POSTED" or u.get("invoice_id"):
            continue
        cr = parse_dt(u["created_at"])
        if start <= cr < end:
            tickets.append(u)
    if not tickets:
        raise ApiError("ERR_NOTHING_TO_SWEEP",
                       "No unbilled POSTED uplift tickets fall inside the period")

    invoice = base_row()
    invoice.update({
        "airline_account_id": account_id,
        "period_start_utc": fmt_dt(start),
        "period_end_utc": fmt_dt(end),
        "replaces_invoice_id": replaces["id"] if replaces else None,
        "swept_net_liters": 0.0,
        "fuel_component_cents": 0,
        "subtotal_cents": 0,
        "volume_rebate_cents": 0,
        "admin_fee_cents": 0,
        "total_cents": 0,
        "amount_paid_cents": 0,
        "dispute_round": 0,
        "issued_by_user_id": None,
        "dispute_resolved_by_user_id": None,
        "status": "DRAFT",
    })
    db.invoices[invoice["id"]] = invoice
    for u in tickets:
        u["invoice_id"] = invoice["id"]
    calc.recompute_invoice_totals(invoice, tickets)
    touch(account)
    return created(public(invoice))


@bp.get("/invoices")
def list_invoices():
    uid, role = auth("ConsortiumAdmin", "BillingClerk", "AirlineRep")
    rows = list(db.invoices.values())
    if role == "AirlineRep":
        rows = [i for i in rows if i["airline_account_id"] == uid]
    for field in ("airline_account_id", "replaces_invoice_id", "status"):
        val = request.args.get(field)
        if val:
            rows = [i for i in rows if i.get(field) == val]
    return listing(rows)


@bp.get("/invoices/<iid>")
def get_invoice(iid):
    uid, role = auth("ConsortiumAdmin", "BillingClerk", "AirlineRep")
    invoice = resolve(db.invoices, iid, "Invoice not found")
    if role == "AirlineRep" and uid != invoice["airline_account_id"]:
        raise ApiError("ERR_ACCOUNT_OWNERSHIP_REQUIRED",
                       "This airline representative may not read that invoice")
    return ok(public(invoice))


@bp.post("/invoices/<iid>/issue")
def issue_invoice(iid):
    uid, role = auth("BillingClerk")
    invoice = resolve(db.invoices, iid, "Invoice not found")
    body()
    account = db.accounts.get(invoice["airline_account_id"])

    svc.terminal_guard("invoice", invoice["status"])
    if invoice["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_INVOICE_STATE",
                       "Invoice status %s cannot be issued" % invoice["status"])
    tickets = swept(invoice)
    if int(invoice["subtotal_cents"]) <= 0 or not tickets:
        raise ApiError("ERR_NOTHING_TO_SWEEP", "The invoice has no swept tickets")
    for u in tickets:
        if u["status"] == "VOIDED":
            raise ApiError("ERR_INVALID_INVOICE_STATE",
                           "A swept uplift ticket has since been VOIDED")

    for u in tickets:
        u["status"] = "BILLED"
        touch(u)
    calc.recompute_invoice_totals(invoice, tickets)
    invoice["status"] = "ISSUED"
    invoice["issued_by_user_id"] = uid
    touch(invoice)
    if account is not None:
        calc.recompute_exposure(account)
        touch(account)
    return ok(public(invoice))


@bp.post("/invoices/<iid>/dispute")
def dispute_invoice(iid):
    uid, role = auth("AirlineRep")
    invoice = resolve(db.invoices, iid, "Invoice not found")
    if uid != invoice["airline_account_id"]:
        raise ApiError("ERR_ACCOUNT_OWNERSHIP_REQUIRED",
                       "This airline representative may not dispute that invoice")
    body()
    svc.terminal_guard("invoice", invoice["status"])
    if invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_INVOICE_STATE",
                       "Invoice status %s cannot be disputed" % invoice["status"])
    if int(invoice["amount_paid_cents"]) != 0:
        raise ApiError("ERR_INVALID_INVOICE_STATE",
                       "A partly paid invoice cannot be disputed")
    if int(invoice["dispute_round"]) > 1:
        raise ApiError("ERR_DISPUTE_LIMIT_REACHED",
                       "This invoice has already been disputed twice")
    invoice["status"] = "DISPUTED"
    touch(invoice)
    return ok(public(invoice))


@bp.post("/invoices/<iid>/resolve-dispute")
def resolve_dispute(iid):
    uid, role = auth("BillingClerk")
    invoice = resolve(db.invoices, iid, "Invoice not found")
    body()
    svc.terminal_guard("invoice", invoice["status"])
    if invoice["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_INVOICE_STATE",
                       "Invoice status %s has no open dispute" % invoice["status"])
    if uid == invoice.get("issued_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The clerk who issued the invoice may not resolve its dispute")
    invoice["status"] = "ISSUED"
    invoice["dispute_round"] = int(invoice["dispute_round"]) + 1
    invoice["dispute_resolved_by_user_id"] = uid
    touch(invoice)
    return ok(public(invoice))


@bp.post("/invoices/<iid>/void")
def void_invoice(iid):
    auth("BillingClerk")
    invoice = resolve(db.invoices, iid, "Invoice not found")
    body()
    account = db.accounts.get(invoice["airline_account_id"])
    svc.terminal_guard("invoice", invoice["status"])
    if invoice["status"] not in ("ISSUED", "DISPUTED"):
        raise ApiError("ERR_INVALID_INVOICE_STATE",
                       "Invoice status %s cannot be voided" % invoice["status"])
    if int(invoice["amount_paid_cents"]) != 0:
        raise ApiError("ERR_INVALID_INVOICE_STATE",
                       "A partly paid invoice cannot be voided")

    for u in swept(invoice):
        u["status"] = "POSTED"
        u["invoice_id"] = None
        touch(u)
    invoice["status"] = "VOIDED"
    touch(invoice)
    if account is not None:
        calc.recompute_exposure(account)
        touch(account)
    return ok(public(invoice))


@bp.post("/invoices/<iid>/payments")
def record_payment(iid):
    auth("BillingClerk")
    invoice = resolve(db.invoices, iid, "Invoice not found")
    data = body()
    amount = req_int(data, "amount_cents")
    account = db.accounts.get(invoice["airline_account_id"])

    svc.terminal_guard("invoice", invoice["status"])
    if invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_INVOICE_STATE",
                       "Invoice status %s cannot accept a payment" % invoice["status"])
    if int(amount) <= 0:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE", "amount_cents must be strictly positive")
    new_paid = int(invoice["amount_paid_cents"]) + int(amount)
    if new_paid > int(invoice["total_cents"]):
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE",
                       "The payment would exceed the invoice total")

    # A payment is a resource in its own right -- PRD lists "payments under an invoice" among
    # the collections addressed as children of a parent in the URL -- so per PRD §4
    # "Endpoints that create a new resource respond with HTTP 201 and return the created
    # resource in the `data` field", and per PRD §2.4 only the filter-change record is exempt
    # from carrying `updated_at` and `version`.
    payment = base_row()
    payment.update({
        "invoice_id": invoice["id"],
        "amount_cents": int(amount),
        "received_at_utc": now_iso(),
    })
    db.payments[payment["id"]] = payment
    invoice["amount_paid_cents"] = new_paid
    if new_paid == int(invoice["total_cents"]):
        invoice["status"] = "PAID"
    touch(invoice)
    if account is not None:
        calc.recompute_exposure(account)
        touch(account)
    return created(public(payment))

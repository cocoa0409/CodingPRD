"""Routes: work orders, teardown reports, quotes, inventory, stock reservations."""

from datetime import timedelta

from flask import Blueprint

from db import DB, CLOCK, make_entity, touch, serialize, sorted_entities, parse_iso8601
from middleware import (
    validate_body, require_auth, require_role, parse_pagination, get_filter, ALL_ROLES,
)
from errors import (
    err_invalid_request, err_invalid_state, err_already_terminal, err_not_found,
    err_stale_version, err_cylinder_retired, err_customer_suspended, err_promise,
    err_teardown_report_exists, err_seal_kit, err_active_quote_exists,
    err_teardown_stale, err_quote_not_approvable, err_quote_expired, err_no_stock,
    err_credit_limit, err_scrap_not_authorized, err_cleanliness,
    err_reservation_not_open, err_unit_not_in_pool, err_spec_mismatch,
    err_core_not_returned,
)
from helpers import (
    get_or_404, check_customer_owns, check_technician_assigned, WO_TERMINAL,
    QUOTE_TERMINAL, check_seal_kit_compatible, create_reservation_with_cut,
    check_stock_available, active_quote_for, sent_quote_for, draft_quote_for,
    teardown_report_for, reservations_for, exchange_unit_for,
)
from calc import (
    shop_config, tier_gate_ok, cleanliness_result, quote_pricing_provisional,
    quote_pricing_final, invoice_total_settlement, credit_exposure_ok,
)
from response import success_object, success_list

bp = Blueprint("workflow", __name__)

TIERS = ["STANDARD", "EXPEDITE", "EMERGENCY"]
MATERIALS = ["CHROME_ROD", "HONING_TUBE"]


# ---------------------------------------------------------------------------
# Work orders
# ---------------------------------------------------------------------------

@bp.post("/fluid-power/work-orders")
def create_work_order():
    body = validate_body([
        ("cylinder_id", ("string", True, False)),
        ("tier", ("enum", True, False, TIERS)),
        ("promised_hours", ("integer", True, False)),
        ("complaint", ("string", True, False)),
    ])
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor", "Customer"])
    cylinder = get_or_404(DB.cylinders, body["cylinder_id"])
    check_customer_owns(actor, cylinder["customer_id"])
    if cylinder["status"] != "ACTIVE":
        raise err_cylinder_retired()
    customer = get_or_404(DB.customers, cylinder["customer_id"])
    if customer["status"] == "SUSPENDED":
        raise err_customer_suspended()
    cfg = shop_config()
    if not tier_gate_ok(cfg, body["tier"], body["promised_hours"]):
        raise err_promise()
    wo = make_entity({
        "cylinder_id": cylinder["id"],
        "customer_id": cylinder["customer_id"],
        "tier": body["tier"],
        "promised_hours": body["promised_hours"],
        "complaint": body["complaint"],
        "status": "INTAKE",
        "assigned_technician_id": None,
        "actual_labor_hours": None,
        "latest_cleanliness_code4": None,
        "latest_cleanliness_code6": None,
        "latest_cleanliness_code14": None,
        "cleanliness_passed": False,
        "final_total_cents": None,
        "invoice_total_cents": None,
        "core_credit_applied_cents": 0,
    })
    DB.work_orders[wo["id"]] = wo
    return success_object(serialize(wo), status=201)


@bp.get("/fluid-power/work-orders/<wo_id>")
def get_work_order(wo_id):
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    return success_object(serialize(get_or_404(DB.work_orders, wo_id)))


@bp.get("/fluid-power/work-orders")
def list_work_orders():
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    cylinder_id = get_filter("cylinder_id")
    customer_id = get_filter("customer_id")
    status = get_filter("status")
    tech_id = get_filter("assigned_technician_id")
    items = sorted_entities(DB.work_orders)
    if cylinder_id is not None:
        items = [w for w in items if w["cylinder_id"] == cylinder_id]
    if customer_id is not None:
        items = [w for w in items if w["customer_id"] == customer_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    if tech_id is not None:
        items = [w for w in items if w["assigned_technician_id"] == tech_id]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(w) for w in page], limit, offset, total)


def _load_wo(wo_id):
    return get_or_404(DB.work_orders, wo_id)


def _wo_terminal_guard(wo):
    if wo["status"] in WO_TERMINAL:
        raise err_already_terminal("Work order is in terminal state %s" % wo["status"])


@bp.post("/fluid-power/work-orders/<wo_id>/start-teardown")
def start_teardown(wo_id):
    body = validate_body([("technician_id", ("string", True, False))])
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor"])
    wo = _load_wo(wo_id)
    tech = get_or_404(DB.technicians, body["technician_id"])
    _wo_terminal_guard(wo)
    if wo["status"] != "INTAKE":
        raise err_invalid_state("Work order is not INTAKE")
    if not tech["active"] or "CYLINDER_REPAIR" not in tech["skills"]:
        raise err_invalid_state("Technician is not active or lacks CYLINDER_REPAIR")
    wo["assigned_technician_id"] = tech["id"]
    wo["status"] = "TEARDOWN"
    touch(wo)
    return success_object(serialize(wo))


@bp.post("/fluid-power/work-orders/<wo_id>/cancel")
def cancel_work_order(wo_id):
    body = validate_body([("reason", ("string", False, True))])
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor", "Customer"])
    wo = _load_wo(wo_id)
    check_customer_owns(actor, wo["customer_id"])
    _wo_terminal_guard(wo)
    if wo["status"] not in ("INTAKE", "TEARDOWN", "QUOTE_DRAFT", "QUOTE_SENT", "REVISION_REQUESTED"):
        raise err_invalid_state("Work order cannot be cancelled from %s" % wo["status"])
    if wo["status"] == "QUOTE_DRAFT":
        quote = draft_quote_for(wo["id"])
        if quote is not None:
            quote["status"] = "SUPERSEDED"
            touch(quote)
    elif wo["status"] == "QUOTE_SENT":
        quote = sent_quote_for(wo["id"])
        if quote is not None:
            quote["status"] = "SUPERSEDED"
            touch(quote)
    wo["status"] = "CANCELLED"
    touch(wo)
    return success_object(serialize(wo))


@bp.post("/fluid-power/work-orders/<wo_id>/authorize-scrap")
def authorize_scrap(wo_id):
    actor = require_auth()
    require_role(actor, ["Customer"])
    wo = _load_wo(wo_id)
    check_customer_owns(actor, wo["customer_id"])
    _wo_terminal_guard(wo)
    if wo["status"] == "QUOTE_SENT":
        quote = sent_quote_for(wo["id"])
        if quote is not None:
            quote["status"] = "REJECTED_SCRAP"
            touch(quote)
    elif wo["status"] != "REVISION_REQUESTED":
        raise err_invalid_state("authorize-scrap requires QUOTE_SENT or REVISION_REQUESTED")
    wo["status"] = "SCRAP_AUTHORIZED"
    touch(wo)
    return success_object(serialize(wo))


@bp.post("/fluid-power/work-orders/<wo_id>/complete-scrap")
def complete_scrap(wo_id):
    body = validate_body([("disposal_method", ("string", True, False))])
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor"])
    wo = _load_wo(wo_id)
    _wo_terminal_guard(wo)
    if wo["status"] != "SCRAP_AUTHORIZED":
        raise err_scrap_not_authorized()
    wo["status"] = "SCRAPPED"
    touch(wo)
    cylinder = DB.cylinders.get(wo["cylinder_id"])
    if cylinder is not None:
        cylinder["status"] = "RETIRED"
        touch(cylinder)
    return success_object(serialize(wo))


@bp.post("/fluid-power/work-orders/<wo_id>/start-repair")
def start_repair(wo_id):
    actor = require_auth()
    require_role(actor, ["Technician"])
    wo = _load_wo(wo_id)
    check_technician_assigned(actor, wo["assigned_technician_id"])
    _wo_terminal_guard(wo)
    if wo["status"] != "APPROVED":
        raise err_invalid_state("Work order is not APPROVED")
    wo["status"] = "IN_REPAIR"
    touch(wo)
    return success_object(serialize(wo))


@bp.post("/fluid-power/work-orders/<wo_id>/complete-assembly")
def complete_assembly(wo_id):
    actor = require_auth()
    require_role(actor, ["Technician"])
    wo = _load_wo(wo_id)
    check_technician_assigned(actor, wo["assigned_technician_id"])
    _wo_terminal_guard(wo)
    if wo["status"] != "IN_REPAIR":
        raise err_invalid_state("Work order is not IN_REPAIR")
    # domain guard (priority 8) precedes the safety gate (priority 9)
    for reservation in reservations_for(wo["id"]):
        if reservation["status"] == "OPEN":
            raise err_reservation_not_open(
                "Every stock reservation of the work order must be CONSUMED")
    if not wo["cleanliness_passed"]:
        raise err_cleanliness()
    wo["status"] = "ASSEMBLED"
    touch(wo)
    return success_object(serialize(wo))


@bp.post("/fluid-power/work-orders/<wo_id>/cleanliness-checks")
def cleanliness_check(wo_id):
    body = validate_body([
        ("c4_count", ("integer", True, False)),
        ("c6_count", ("integer", True, False)),
        ("c14_count", ("integer", True, False)),
    ])
    if body["c4_count"] < 0 or body["c6_count"] < 0 or body["c14_count"] < 0:
        raise err_invalid_request("Particle counts must be non-negative")
    actor = require_auth()
    require_role(actor, ["Technician", "QualityInspector"])
    wo = _load_wo(wo_id)
    _wo_terminal_guard(wo)
    cfg = shop_config()
    code4, code6, code14, passed = cleanliness_result(
        cfg, body["c4_count"], body["c6_count"], body["c14_count"])
    wo["latest_cleanliness_code4"] = code4
    wo["latest_cleanliness_code6"] = code6
    wo["latest_cleanliness_code14"] = code14
    wo["cleanliness_passed"] = passed
    touch(wo)
    return success_object(serialize(wo))


@bp.post("/fluid-power/work-orders/<wo_id>/select-exchange")
def select_exchange(wo_id):
    body = validate_body([("exchange_unit_id", ("string", True, False))])
    actor = require_auth()
    require_role(actor, ["Customer"])
    wo = _load_wo(wo_id)
    check_customer_owns(actor, wo["customer_id"])
    unit = get_or_404(DB.exchange_units, body["exchange_unit_id"])
    _wo_terminal_guard(wo)
    # EXCHANGE_SELECTED is a valid from-state for re-selection after a release
    if wo["status"] not in ("QUOTE_SENT", "EXCHANGE_SELECTED"):
        raise err_invalid_state("select-exchange requires QUOTE_SENT")
    if unit["status"] != "IN_POOL":
        raise err_unit_not_in_pool()
    cylinder = get_or_404(DB.cylinders, wo["cylinder_id"])
    if not (unit["bore_mm"] == cylinder["bore_mm"]
            and unit["stroke_mm"] == cylinder["stroke_mm"]
            and unit["rod_diameter_mm"] == cylinder["rod_diameter_mm"]
            and unit["pressure_class"] == cylinder["pressure_class"]):
        raise err_spec_mismatch()
    if wo["status"] == "QUOTE_SENT":
        quote = sent_quote_for(wo["id"])
        if quote is not None:
            quote["status"] = "SUPERSEDED"
            touch(quote)
    unit["status"] = "RESERVED"
    unit["work_order_id"] = wo["id"]
    touch(unit)
    wo["status"] = "EXCHANGE_SELECTED"
    touch(wo)
    return success_object(serialize(wo))


@bp.post("/fluid-power/work-orders/<wo_id>/close")
def close_work_order(wo_id):
    body = validate_body([("actual_labor_hours", ("number", True, False))])
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor"])
    wo = _load_wo(wo_id)
    _wo_terminal_guard(wo)
    if wo["status"] not in ("CERTIFIED", "EXCHANGE_FULFILLED"):
        raise err_invalid_state("close requires CERTIFIED or EXCHANGE_FULFILLED")
    cfg = shop_config()
    customer = get_or_404(DB.customers, wo["customer_id"])
    wo["actual_labor_hours"] = body["actual_labor_hours"]
    if wo["status"] == "CERTIFIED":
        # PRD 3.8: "On the repair path the work order must be CERTIFIED, and
        # actual_labor_hours must be a positive number" — the positivity rule is
        # scoped to the repair path; the exchange-path close carries the field
        # but does not constrain it.
        if body["actual_labor_hours"] <= 0:
            raise err_invalid_request("actual_labor_hours must be a positive number")
        teardown = teardown_report_for(wo["id"])
        cylinder = get_or_404(DB.cylinders, wo["cylinder_id"])
        approved = [q for q in DB.quotes.values()
                    if q["work_order_id"] == wo["id"] and q["status"] == "APPROVED"]
        tier = approved[-1]["tier_snapshot"] if approved else wo["tier"]
        reservations = reservations_for(wo["id"])
        final_total = quote_pricing_final(
            cfg, tier, teardown, cylinder, DB.seal_kits, reservations,
            DB.inventory_items, body["actual_labor_hours"])
        invoice_total = invoice_total_settlement(cfg, customer, final_total)
        wo["final_total_cents"] = final_total
        wo["invoice_total_cents"] = invoice_total
    else:
        unit = exchange_unit_for(wo["id"])
        if unit is None or unit["status"] != "SETTLED":
            raise err_core_not_returned()
        invoice_total = unit["unit_price_cents"] - unit["final_credit_cents"]
        if unit["condition"] == "SCRAP":
            invoice_total += cfg["core_disposal_fee_cents"]
        wo["core_credit_applied_cents"] = unit["final_credit_cents"]
        wo["invoice_total_cents"] = invoice_total
    customer["ytd_spend_cents"] += wo["invoice_total_cents"]
    touch(customer)
    wo["status"] = "CLOSED"
    touch(wo)
    return success_object(serialize(wo))


# ---------------------------------------------------------------------------
# Teardown reports
# ---------------------------------------------------------------------------

def _validate_cut_length_pair(body, needed_field, length_field):
    """rod_cut_length_mm / tube_cut_length_mm is mandatory exactly when the
    matching *_needed flag is true."""
    needed = body.get(needed_field)
    length = body.get(length_field)
    if needed is True and length is None:
        raise err_invalid_request("%s is required when %s is true" % (length_field, needed_field))
    if needed is False and length is not None:
        raise err_invalid_request("%s must be omitted when %s is false" % (length_field, needed_field))


@bp.post("/fluid-power/teardown-reports")
def create_teardown_report():
    body = validate_body([
        ("work_order_id", ("string", True, False)),
        ("rod_needed", ("boolean", True, False)),
        ("rod_cut_length_mm", ("integer", False, True)),
        ("tube_needed", ("boolean", True, False)),
        ("tube_cut_length_mm", ("integer", False, True)),
        ("honing_passes", ("integer", False, False)),
        ("seal_kit_id", ("string", False, True)),
        ("estimated_labor_hours", ("number", True, False)),
        ("findings_notes", ("string", False, False)),
    ])
    _validate_cut_length_pair(body, "rod_needed", "rod_cut_length_mm")
    _validate_cut_length_pair(body, "tube_needed", "tube_cut_length_mm")
    actor = require_auth()
    require_role(actor, ["Technician"])
    wo = get_or_404(DB.work_orders, body["work_order_id"])
    _wo_terminal_guard(wo)
    if teardown_report_for(wo["id"]) is not None:
        raise err_teardown_report_exists()
    if wo["status"] != "TEARDOWN":
        raise err_invalid_state("Work order is not TEARDOWN")
    cylinder = get_or_404(DB.cylinders, wo["cylinder_id"])
    override_kit_id = body.get("seal_kit_id")
    if override_kit_id is not None:
        kit = get_or_404(DB.seal_kits, override_kit_id)
        check_seal_kit_compatible(kit, cylinder["bore_mm"],
                                  cylinder["pressure_class"], cylinder["fluid_type"])
    report = make_entity({
        "work_order_id": wo["id"],
        "rod_needed": body["rod_needed"],
        "rod_cut_length_mm": body.get("rod_cut_length_mm"),
        "tube_needed": body["tube_needed"],
        "tube_cut_length_mm": body.get("tube_cut_length_mm"),
        "honing_passes": body.get("honing_passes") if body.get("honing_passes") is not None else 0,
        "seal_kit_id": override_kit_id,
        "estimated_labor_hours": body["estimated_labor_hours"],
        "findings_notes": body.get("findings_notes") or "",
    })
    DB.teardown_reports[report["id"]] = report
    wo["status"] = "QUOTE_DRAFT"
    touch(wo)
    return success_object(serialize(report), status=201)


@bp.get("/fluid-power/teardown-reports/<report_id>")
def get_teardown_report(report_id):
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    return success_object(serialize(get_or_404(DB.teardown_reports, report_id)))


@bp.get("/fluid-power/teardown-reports")
def list_teardown_reports():
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    work_order_id = get_filter("work_order_id")
    seal_kit_id = get_filter("seal_kit_id")
    items = sorted_entities(DB.teardown_reports)
    if work_order_id is not None:
        items = [r for r in items if r["work_order_id"] == work_order_id]
    if seal_kit_id is not None:
        items = [r for r in items if r["seal_kit_id"] == seal_kit_id]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.patch("/fluid-power/teardown-reports/<report_id>")
def patch_teardown_report(report_id):
    body = validate_body([
        ("expected_teardown_report_version", ("integer", True, False)),
        ("rod_needed", ("boolean", False, False)),
        ("rod_cut_length_mm", ("integer", False, True)),
        ("tube_needed", ("boolean", False, False)),
        ("tube_cut_length_mm", ("integer", False, True)),
        ("honing_passes", ("integer", False, False)),
        ("seal_kit_id", ("string", False, True)),
        ("estimated_labor_hours", ("number", False, False)),
        ("findings_notes", ("string", False, False)),
    ])
    actor = require_auth()
    require_role(actor, ["Technician"])
    report = get_or_404(DB.teardown_reports, report_id)
    if body["expected_teardown_report_version"] != report["version"]:
        raise err_stale_version()
    wo = get_or_404(DB.work_orders, report["work_order_id"])
    # PRD 3.3: revision allowed only while QUOTE_DRAFT or REVISION_REQUESTED;
    # at any other stage -> ERR_INVALID_STATE
    if wo["status"] not in ("QUOTE_DRAFT", "REVISION_REQUESTED"):
        raise err_invalid_state("Findings may be revised only while QUOTE_DRAFT or REVISION_REQUESTED")
    merged = dict(report)
    for field in ("rod_needed", "rod_cut_length_mm", "tube_needed", "tube_cut_length_mm",
                  "honing_passes", "seal_kit_id", "estimated_labor_hours", "findings_notes"):
        if field in body:
            merged[field] = body[field]
    # keep cut lengths consistent with the resulting *_needed flags
    if merged["rod_needed"] and merged["rod_cut_length_mm"] is None:
        raise err_invalid_request("rod_cut_length_mm is required when rod_needed is true")
    if not merged["rod_needed"]:
        if "rod_cut_length_mm" in body and body["rod_cut_length_mm"] is not None and not merged["rod_needed"]:
            raise err_invalid_request("rod_cut_length_mm must be omitted when rod_needed is false")
        merged["rod_cut_length_mm"] = None
    if merged["tube_needed"] and merged["tube_cut_length_mm"] is None:
        raise err_invalid_request("tube_cut_length_mm is required when tube_needed is true")
    if not merged["tube_needed"]:
        if "tube_cut_length_mm" in body and body["tube_cut_length_mm"] is not None and not merged["tube_needed"]:
            raise err_invalid_request("tube_cut_length_mm must be omitted when tube_needed is false")
        merged["tube_cut_length_mm"] = None
    if merged.get("seal_kit_id") is not None and merged.get("seal_kit_id") != report.get("seal_kit_id"):
        kit = get_or_404(DB.seal_kits, merged["seal_kit_id"])
        cylinder = get_or_404(DB.cylinders, wo["cylinder_id"])
        check_seal_kit_compatible(kit, cylinder["bore_mm"],
                                  cylinder["pressure_class"], cylinder["fluid_type"])
    for field in ("rod_needed", "rod_cut_length_mm", "tube_needed", "tube_cut_length_mm",
                  "honing_passes", "seal_kit_id", "estimated_labor_hours", "findings_notes"):
        report[field] = merged[field]
    touch(report)
    return success_object(serialize(report))


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------

@bp.post("/fluid-power/quotes")
def create_quote():
    body = validate_body([("work_order_id", ("string", True, False))])
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor"])
    wo = get_or_404(DB.work_orders, body["work_order_id"])
    _wo_terminal_guard(wo)
    if wo["status"] not in ("QUOTE_DRAFT", "REVISION_REQUESTED"):
        raise err_invalid_state("Quote drafting requires QUOTE_DRAFT or REVISION_REQUESTED")
    if active_quote_for(wo["id"]) is not None:
        raise err_active_quote_exists()
    teardown = teardown_report_for(wo["id"])
    if teardown is None:
        raise err_invalid_state("No teardown report exists for the work order")
    cylinder = get_or_404(DB.cylinders, wo["cylinder_id"])
    cfg = shop_config()
    line_items, provisional_total = quote_pricing_provisional(
        cfg, wo["tier"], teardown, cylinder, DB.seal_kits)
    quote = make_entity({
        "work_order_id": wo["id"],
        "teardown_report_id": teardown["id"],
        "pinned_teardown_version": teardown["version"],
        "tier_snapshot": wo["tier"],
        "status": "DRAFT",
        "line_items": line_items,
        "provisional_total_cents": provisional_total,
        "sent_at": None,
    })
    DB.quotes[quote["id"]] = quote
    if wo["status"] == "REVISION_REQUESTED":
        # revision loop: the prior REVISION_REQUESTED quote is superseded and
        # the work order returns to QUOTE_DRAFT
        for prior in DB.quotes.values():
            if prior["work_order_id"] == wo["id"] and prior["status"] == "REVISION_REQUESTED":
                prior["status"] = "SUPERSEDED"
                touch(prior)
        wo["status"] = "QUOTE_DRAFT"
        touch(wo)
    return success_object(serialize(quote), status=201)


@bp.get("/fluid-power/quotes/<quote_id>")
def get_quote(quote_id):
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    return success_object(serialize(get_or_404(DB.quotes, quote_id)))


@bp.get("/fluid-power/quotes")
def list_quotes():
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    work_order_id = get_filter("work_order_id")
    teardown_report_id = get_filter("teardown_report_id")
    status = get_filter("status")
    items = sorted_entities(DB.quotes)
    if work_order_id is not None:
        items = [q for q in items if q["work_order_id"] == work_order_id]
    if teardown_report_id is not None:
        items = [q for q in items if q["teardown_report_id"] == teardown_report_id]
    if status is not None:
        items = [q for q in items if q["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(q) for q in page], limit, offset, total)


@bp.post("/fluid-power/quotes/<quote_id>/send")
def send_quote(quote_id):
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor"])
    quote = get_or_404(DB.quotes, quote_id)
    if quote["status"] in QUOTE_TERMINAL:
        raise err_already_terminal("Quote is in terminal state %s" % quote["status"])
    if quote["status"] != "DRAFT":
        raise err_invalid_state("Quote is not DRAFT")
    wo = get_or_404(DB.work_orders, quote["work_order_id"])
    if wo["status"] != "QUOTE_DRAFT":
        raise err_invalid_state("Work order is not QUOTE_DRAFT")
    teardown = get_or_404(DB.teardown_reports, quote["teardown_report_id"])
    if quote["pinned_teardown_version"] != teardown["version"]:
        raise err_teardown_stale()
    quote["status"] = "SENT"
    quote["sent_at"] = CLOCK.now_iso()
    touch(quote)
    wo["status"] = "QUOTE_SENT"
    touch(wo)
    return success_object(serialize(quote))


@bp.post("/fluid-power/quotes/<quote_id>/approve")
def approve_quote(quote_id):
    actor = require_auth()
    require_role(actor, ["Customer"])
    quote = get_or_404(DB.quotes, quote_id)
    wo = get_or_404(DB.work_orders, quote["work_order_id"])
    check_customer_owns(actor, wo["customer_id"])
    # PRD 3.4: approval aimed at a non-SENT quote -> ERR_QUOTE_NOT_APPROVABLE
    if quote["status"] != "SENT":
        raise err_quote_not_approvable()
    cfg = shop_config()
    # temporal (priority 10): lazy TTL expiry; the quote flips to EXPIRED even
    # though the call fails
    sent_at = parse_iso8601(quote["sent_at"])
    if CLOCK.now() > sent_at + timedelta(hours=cfg["quote_ttl_hours"]):
        quote["status"] = "EXPIRED"
        touch(quote)
        raise err_quote_expired()
    # structural (priority 11): stock must exist for the cascade before commit
    teardown = get_or_404(DB.teardown_reports, quote["teardown_report_id"])
    cylinder = get_or_404(DB.cylinders, wo["cylinder_id"])
    if teardown["rod_needed"]:
        if not check_stock_available("CHROME_ROD", cylinder["rod_diameter_mm"],
                                     teardown["rod_cut_length_mm"]):
            raise err_no_stock()
    if teardown["tube_needed"]:
        if not check_stock_available("HONING_TUBE", cylinder["bore_mm"],
                                     teardown["tube_cut_length_mm"]):
            raise err_no_stock()
    # fiscal (priority 13): credit exposure, inclusive boundary passes
    customer = get_or_404(DB.customers, wo["customer_id"])
    if not credit_exposure_ok(customer, quote):
        raise err_credit_limit()
    # commit: quote + work order advance, material cascade fires
    quote["status"] = "APPROVED"
    touch(quote)
    wo["status"] = "APPROVED"
    touch(wo)
    if teardown["rod_needed"]:
        create_reservation_with_cut(wo["id"], "CHROME_ROD", cylinder["rod_diameter_mm"],
                                    teardown["rod_cut_length_mm"])
    if teardown["tube_needed"]:
        create_reservation_with_cut(wo["id"], "HONING_TUBE", cylinder["bore_mm"],
                                    teardown["tube_cut_length_mm"])
    return success_object(serialize(quote))


@bp.post("/fluid-power/quotes/<quote_id>/request-revision")
def request_revision(quote_id):
    body = validate_body([("notes", ("string", False, True))])
    actor = require_auth()
    require_role(actor, ["Customer"])
    quote = get_or_404(DB.quotes, quote_id)
    wo = get_or_404(DB.work_orders, quote["work_order_id"])
    check_customer_owns(actor, wo["customer_id"])
    if quote["status"] in QUOTE_TERMINAL:
        raise err_already_terminal("Quote is in terminal state %s" % quote["status"])
    if quote["status"] != "SENT":
        raise err_invalid_state("Quote is not SENT")
    quote["status"] = "REVISION_REQUESTED"
    touch(quote)
    wo["status"] = "REVISION_REQUESTED"
    touch(wo)
    return success_object(serialize(quote))


# ---------------------------------------------------------------------------
# Inventory items
# ---------------------------------------------------------------------------

@bp.post("/fluid-power/inventory-items")
def create_inventory_item():
    body = validate_body([
        ("material", ("enum", True, False, MATERIALS)),
        ("diameter_mm", ("integer", True, False)),
        ("length_mm", ("integer", True, False)),
        ("cost_per_mm_cents", ("integer", True, False)),
    ])
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor"])
    item = make_entity({
        "material": body["material"],
        "diameter_mm": body["diameter_mm"],
        "length_mm": body["length_mm"],
        "cost_per_mm_cents": body["cost_per_mm_cents"],
        "status": "AVAILABLE",
        "origin": "RECEIVED",
    })
    DB.inventory_items[item["id"]] = item
    return success_object(serialize(item), status=201)


@bp.get("/fluid-power/inventory-items/<item_id>")
def get_inventory_item(item_id):
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    return success_object(serialize(get_or_404(DB.inventory_items, item_id)))


@bp.get("/fluid-power/inventory-items")
def list_inventory_items():
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    material = get_filter("material")
    status = get_filter("status")
    items = sorted_entities(DB.inventory_items)
    if material is not None:
        items = [i for i in items if i["material"] == material]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(i) for i in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Stock reservations
# ---------------------------------------------------------------------------

@bp.post("/fluid-power/stock-reservations")
def create_stock_reservation():
    body = validate_body([
        ("work_order_id", ("string", True, False)),
        ("material", ("enum", True, False, MATERIALS)),
        ("diameter_mm", ("integer", True, False)),
        ("cut_length_mm", ("integer", True, False)),
    ])
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor"])
    get_or_404(DB.work_orders, body["work_order_id"])
    reservation = create_reservation_with_cut(
        body["work_order_id"], body["material"], body["diameter_mm"], body["cut_length_mm"])
    return success_object(serialize(reservation), status=201)


@bp.get("/fluid-power/stock-reservations/<reservation_id>")
def get_stock_reservation(reservation_id):
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    return success_object(serialize(get_or_404(DB.stock_reservations, reservation_id)))


@bp.get("/fluid-power/stock-reservations")
def list_stock_reservations():
    actor = require_auth()
    require_role(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    work_order_id = get_filter("work_order_id")
    inventory_item_id = get_filter("inventory_item_id")
    status = get_filter("status")
    items = sorted_entities(DB.stock_reservations)
    if work_order_id is not None:
        items = [r for r in items if r["work_order_id"] == work_order_id]
    if inventory_item_id is not None:
        items = [r for r in items if r["inventory_item_id"] == inventory_item_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.post("/fluid-power/stock-reservations/<reservation_id>/consume")
def consume_reservation(reservation_id):
    actor = require_auth()
    require_role(actor, ["Technician"])
    reservation = get_or_404(DB.stock_reservations, reservation_id)
    wo = get_or_404(DB.work_orders, reservation["work_order_id"])
    check_technician_assigned(actor, wo["assigned_technician_id"])
    # PRD 3.5: a reservation in any state other than OPEN -> ERR_RESERVATION_NOT_OPEN
    if reservation["status"] != "OPEN":
        raise err_reservation_not_open()
    if wo["status"] != "IN_REPAIR":
        raise err_invalid_state("Linked work order is not IN_REPAIR")
    reservation["consumed_length_mm"] = reservation["cut_length_mm"]
    reservation["status"] = "CONSUMED"
    touch(reservation)
    return success_object(serialize(reservation))


@bp.post("/fluid-power/stock-reservations/<reservation_id>/release")
def release_reservation(reservation_id):
    actor = require_auth()
    require_role(actor, ["ShopAdmin", "ServiceAdvisor"])
    reservation = get_or_404(DB.stock_reservations, reservation_id)
    if reservation["status"] != "OPEN":
        raise err_reservation_not_open()
    cfg = shop_config()
    source_item = get_or_404(DB.inventory_items, reservation["inventory_item_id"])
    reservation["status"] = "RELEASED"
    if reservation["cut_length_mm"] >= cfg["min_remnant_mm"]:
        remnant = make_entity({
            "material": source_item["material"],
            "diameter_mm": source_item["diameter_mm"],
            "length_mm": reservation["cut_length_mm"],
            "cost_per_mm_cents": source_item["cost_per_mm_cents"],
            "status": "AVAILABLE",
            "origin": "REMNANT",
        })
        DB.inventory_items[remnant["id"]] = remnant
    else:
        reservation["scrap_length_mm"] += reservation["cut_length_mm"]
        reservation["scrap_charge_cents"] = (
            reservation["scrap_length_mm"] * source_item["cost_per_mm_cents"])
    touch(reservation)
    return success_object(serialize(reservation))

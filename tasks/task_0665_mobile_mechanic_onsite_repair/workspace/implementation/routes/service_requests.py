"""Service-request endpoints + nested quotes, dispatch, part-lines, findings, resolve, cancel."""
from flask import Blueprint, request

import db
import errors
import response
from middleware import authenticate, require_role, parse_pagination, paginate
from services import models, validate, calc, scheduling

bp = Blueprint("service_requests", __name__)


def _sorted(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def _get_sr(sid):
    sr = db.store.service_requests.get(sid)
    if sr is None:
        raise errors.not_found("Service request not found.")
    return sr


def _fleet_discount_for(sr):
    """Return the fleet labor_discount_pct if the request is fleet-billed, else None."""
    fid = sr.get("fleet_account_id")
    if fid is None:
        return None
    fleet = db.store.fleet_accounts.get(fid)
    if fleet is None:
        return None
    return fleet["labor_discount_pct"]


# ---- create / read / list ----
@bp.route("/service-requests", methods=["POST"])
def create_service_request():
    uid, role = authenticate()
    require_role(role, {"Customer"})
    body = validate.get_body()
    # body FK existence (priority 3): customer_id
    customer_id = body.get("customer_id")
    if not isinstance(customer_id, str) or db.store.customers.get(customer_id) is None:
        raise errors.not_found("customer_id does not resolve.")
    customer = db.store.customers[customer_id]
    # ownership (priority 4): the acting customer must be the customer_id
    if uid != customer_id:
        raise errors.not_owner("Customer may only file requests for itself.")
    # structural validation (priority 6)
    vin = validate.require_str(body, "vehicle_vin")
    if len(vin) != 17:
        raise errors.invalid_request("vehicle_vin must be exactly 17 characters.")
    symptom = validate.require_str(body, "symptom_text")
    severity = validate.optional_enum(body, "severity",
                                      {"ROUTINE", "URGENT", "EMERGENCY"}, "ROUTINE")
    rec = models.make_service_request(
        db.store, customer_id, vin, symptom, severity,
        zone_code=customer["home_zone_code"],
        fleet_account_id=customer.get("fleet_account_id"),
    )
    db.store.service_requests[rec["id"]] = rec
    return response.success(models.serialize(rec), 201)


@bp.route("/service-requests/<sid>", methods=["GET"])
def get_service_request(sid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Customer", "Mechanic", "Dispatcher"})
    sr = _get_sr(sid)
    if role == "Customer" and uid != sr["customer_id"]:
        raise errors.not_owner("Customer may only read its own service requests.")
    return response.success(models.serialize(sr), 200)


@bp.route("/service-requests", methods=["GET"])
def list_service_requests():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Dispatcher", "FleetManager"})
    limit, offset = parse_pagination()
    customer_filter = request.args.get("customer_id")
    fleet_filter = request.args.get("fleet_account_id")
    items = list(db.store.service_requests.values())
    if customer_filter is not None:
        items = [s for s in items if s["customer_id"] == customer_filter]
    if fleet_filter is not None:
        items = [s for s in items if s.get("fleet_account_id") == fleet_filter]
    items = _sorted(items)
    page, total = paginate(items, limit, offset)
    return response.success_list([models.serialize(s) for s in page], limit, offset, total)


# ---- quotes (send / list) ----
@bp.route("/service-requests/<sid>/quotes", methods=["POST"])
def send_quote(sid):
    _uid, role = authenticate()
    require_role(role, {"Mechanic"})
    sr = _get_sr(sid)
    # state precondition (priority 5): INTAKE for first send, or QUOTED with a prior
    # REVISION_REQUESTED quote for a replacement.
    status = sr["status"]
    prior_revision = None
    if status == "INTAKE":
        pass
    elif status == "QUOTED":
        # find a quote in REVISION_REQUESTED for this request
        for q in db.store.quotes.values():
            if q["service_request_id"] == sid and q["status"] == "REVISION_REQUESTED":
                prior_revision = q
                break
        if prior_revision is None:
            raise errors.invalid_state("No revision-requested quote to replace.")
    else:
        raise errors.invalid_state("Quote may only be sent from INTAKE or a revision loop.")

    # structural validation (priority 6)
    body = validate.get_body()
    diagnosis = validate.require_str(body, "diagnosis_text")
    labor_hours = validate.require_number(body, "estimated_labor_hours", exclusive_min=0)
    parts_cents = validate.require_int(body, "estimated_parts_cents", minimum=0)
    rate = validate.require_int(body, "labor_rate_cents_per_hour", exclusive_min=0)
    tow_fee = validate.optional_int(body, "tow_fee_cents", default=0, minimum=0)

    # for first send, customer must be ACTIVE (precondition)
    if status == "INTAKE":
        customer = db.store.customers.get(sr["customer_id"])
        if customer is None or customer["status"] != "ACTIVE":
            raise errors.invalid_state("Owning customer is not ACTIVE.")

    discount = _fleet_discount_for(sr)
    quoted_total = calc.quote_estimate_total(
        labor_hours, rate, parts_cents, tow_fee, discount)

    quote = models.make_quote(db.store, sid, diagnosis, labor_hours, parts_cents,
                              tow_fee, rate, quoted_total)
    db.store.quotes[quote["id"]] = quote

    if prior_revision is not None:
        prior_revision["status"] = "SUPERSEDED"
        models.touch(prior_revision, db.store)
    else:
        sr["status"] = "QUOTED"

    models.touch(sr, db.store)
    return response.success(models.serialize(quote), 201)


@bp.route("/service-requests/<sid>/quotes", methods=["GET"])
def list_quotes(sid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Customer", "Mechanic", "Dispatcher"})
    sr = _get_sr(sid)
    if role == "Customer" and uid != sr["customer_id"]:
        raise errors.not_owner("Customer may only read its own quotes.")
    limit, offset = parse_pagination()
    items = [q for q in db.store.quotes.values() if q["service_request_id"] == sid]
    items = _sorted(items)
    page, total = paginate(items, limit, offset)
    return response.success_list([models.serialize(q) for q in page], limit, offset, total)


# ---- dispatch ----
@bp.route("/service-requests/<sid>/dispatch", methods=["POST"])
def dispatch(sid):
    _uid, role = authenticate()
    require_role(role, {"Dispatcher"})
    sr = _get_sr(sid)
    body = validate.get_body()
    # body FK existence (priority 3): mechanic_id
    mechanic_id = body.get("mechanic_id")
    if not isinstance(mechanic_id, str) or db.store.mechanics.get(mechanic_id) is None:
        raise errors.not_found("mechanic_id does not resolve.")
    mechanic = db.store.mechanics[mechanic_id]

    # state precondition (priority 5): request APPROVED and mechanic AVAILABLE
    if sr["status"] != "APPROVED":
        raise errors.invalid_state("Service request is not APPROVED.")
    if mechanic["status"] != "AVAILABLE":
        raise errors.invalid_state("Mechanic is not AVAILABLE.")

    # structural validation (priority 6)
    routing_mode = validate.require_enum(body, "routing_mode", {"ON_SITE", "TOW_TO_SHOP"})
    if "scheduled_start_utc" not in body or "scheduled_end_utc" not in body:
        raise errors.invalid_request("scheduled_start_utc and scheduled_end_utc are required.")
    start = validate.parse_dt(body["scheduled_start_utc"])
    end = validate.parse_dt(body["scheduled_end_utc"])
    if not (end > start):
        raise errors.invalid_request("scheduled_end_utc must be strictly after scheduled_start_utc.")
    if "expected_service_request_version" not in body or body["expected_service_request_version"] is None:
        raise errors.invalid_request("expected_service_request_version is required.")
    expected = body["expected_service_request_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_service_request_version must be an integer.")

    # zone match (priority 7)
    if mechanic["zone_code"] != sr["zone_code"]:
        raise errors.zone_mismatch()
    # skill tier for tow (priority 8)
    if routing_mode == "TOW_TO_SHOP" and mechanic["skill_tier"] != "TIER3":
        raise errors.insufficient_skill()
    # on-site overlap (priority 9)
    if routing_mode == "ON_SITE" and scheduling.onsite_overlap(mechanic_id, start, end):
        raise errors.visit_overlap()
    # OCC (priority 14)
    if expected != sr["version"]:
        raise errors.stale_version()

    visit = models.make_job_visit(db.store, sid, mechanic_id,
                                  body["scheduled_start_utc"], body["scheduled_end_utc"],
                                  routing_mode)
    db.store.job_visits[visit["id"]] = visit

    sr["routing_mode"] = routing_mode
    sr["status"] = "DISPATCHED"
    models.touch(sr, db.store)
    return response.success(models.serialize(visit), 201)


# ---- part-lines ----
@bp.route("/service-requests/<sid>/part-lines", methods=["POST"])
def source_part(sid):
    _uid, role = authenticate()
    require_role(role, {"Mechanic"})
    sr = _get_sr(sid)
    body = validate.get_body()
    catalog_part_id = body.get("catalog_part_id")
    if not isinstance(catalog_part_id, str) or db.store.catalog_parts.get(catalog_part_id) is None:
        raise errors.not_found("catalog_part_id does not resolve.")
    part = db.store.catalog_parts[catalog_part_id]
    quantity = validate.require_int(body, "quantity", exclusive_min=0)

    unit_cost = part["wholesale_cost_cents"]
    unit_price, line_total = calc.part_line_pricing(unit_cost, quantity)
    pl = models.make_part_line(db.store, sid, catalog_part_id, quantity,
                               unit_cost, unit_price, line_total, is_addon=False)
    db.store.part_lines[pl["id"]] = pl
    return response.success(models.serialize(pl), 201)


@bp.route("/service-requests/<sid>/part-lines", methods=["GET"])
def list_part_lines_for_request(sid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Customer", "Mechanic", "Dispatcher"})
    sr = _get_sr(sid)
    if role == "Customer" and uid != sr["customer_id"]:
        raise errors.not_owner("Customer may only read its own part lines.")
    limit, offset = parse_pagination()
    items = [p for p in db.store.part_lines.values() if p["service_request_id"] == sid]
    items = _sorted(items)
    page, total = paginate(items, limit, offset)
    return response.success_list([models.serialize(p) for p in page], limit, offset, total)


# ---- inspection findings ----
@bp.route("/service-requests/<sid>/inspection-findings", methods=["POST"])
def record_finding(sid):
    _uid, role = authenticate()
    require_role(role, {"Mechanic"})
    sr = _get_sr(sid)
    body = validate.get_body()
    # body FK existence (priority 3): job_visit_id + optional recommended_part_id
    job_visit_id = body.get("job_visit_id")
    if not isinstance(job_visit_id, str) or db.store.job_visits.get(job_visit_id) is None:
        raise errors.not_found("job_visit_id does not resolve.")
    recommended_part_id = body.get("recommended_part_id")
    if recommended_part_id is not None:
        if not isinstance(recommended_part_id, str) or db.store.catalog_parts.get(recommended_part_id) is None:
            raise errors.not_found("recommended_part_id does not resolve.")

    # state precondition (priority 5): request IN_PROGRESS
    if sr["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Inspection findings may only be recorded while IN_PROGRESS.")

    # structural validation (priority 6)
    description = validate.require_str(body, "description")
    recommended_quantity = validate.optional_int(body, "recommended_quantity", default=0, minimum=0)
    add_on_labor_hours = validate.optional_number(body, "add_on_labor_hours", default=0, minimum=0)

    finding = models.make_inspection_finding(
        db.store, sid, job_visit_id, description, recommended_part_id,
        recommended_quantity, add_on_labor_hours)
    db.store.inspection_findings[finding["id"]] = finding

    # first PROPOSED finding drives IN_PROGRESS -> AWAITING_ADDON_APPROVAL
    sr["status"] = "AWAITING_ADDON_APPROVAL"
    models.touch(sr, db.store)
    return response.success(models.serialize(finding), 201)


@bp.route("/service-requests/<sid>/inspection-findings", methods=["GET"])
def list_findings_for_request(sid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Customer", "Mechanic", "Dispatcher"})
    sr = _get_sr(sid)
    if role == "Customer" and uid != sr["customer_id"]:
        raise errors.not_owner("Customer may only read its own findings.")
    limit, offset = parse_pagination()
    items = [f for f in db.store.inspection_findings.values()
             if f["service_request_id"] == sid]
    items = _sorted(items)
    page, total = paginate(items, limit, offset)
    return response.success_list([models.serialize(f) for f in page], limit, offset, total)


# ---- resolve add-ons ----
@bp.route("/service-requests/<sid>/resolve-addons", methods=["POST"])
def resolve_addons(sid):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    sr = _get_sr(sid)
    if uid != sr["customer_id"]:
        raise errors.not_owner("Customer may only resolve its own add-ons.")
    # state precondition (priority 5)
    if sr["status"] != "AWAITING_ADDON_APPROVAL":
        raise errors.invalid_state("Request is not awaiting add-on approval.")

    body = validate.get_body()
    decisions = body.get("decisions")
    if not isinstance(decisions, list):
        raise errors.invalid_request("decisions must be a list.")

    # parse decisions structurally
    parsed = []
    for d in decisions:
        if not isinstance(d, dict):
            raise errors.invalid_request("Each decision must be an object.")
        fid = d.get("finding_id")
        decision = d.get("decision")
        if not isinstance(fid, str) or decision not in {"APPROVED", "DECLINED"}:
            raise errors.invalid_request("Each decision needs finding_id and decision in {APPROVED,DECLINED}.")
        parsed.append((fid, decision))

    # exact-cover rule (priority 16): decisions must cover exactly the PROPOSED
    # findings for this request — none omitted, none referencing a non-PROPOSED
    # or unrelated finding.
    proposed = {f["id"] for f in db.store.inspection_findings.values()
                if f["service_request_id"] == sid and f["status"] == "PROPOSED"}
    decided_ids = [fid for fid, _ in parsed]
    decided_set = set(decided_ids)
    if len(decided_ids) != len(decided_set):
        raise errors.validation_pending("Duplicate finding in decisions list.")
    for fid, _ in parsed:
        finding = db.store.inspection_findings.get(fid)
        if finding is None or finding["service_request_id"] != sid or finding["status"] != "PROPOSED":
            raise errors.validation_pending("Decision references a non-proposed or unrelated finding.")
    if decided_set != proposed:
        raise errors.validation_pending("Decisions do not exactly cover proposed findings.")

    # find the visit to accumulate add-on labour onto (the visit referenced by findings)
    # apply decisions
    for fid, decision in parsed:
        finding = db.store.inspection_findings[fid]
        finding["status"] = decision
        models.touch(finding, db.store)
        if decision == "APPROVED":
            visit = db.store.job_visits.get(finding["job_visit_id"])
            if visit is not None:
                visit["_addon_labor_hours"] = visit.get("_addon_labor_hours", 0) + (finding["add_on_labor_hours"] or 0)
            # approved finding naming a recommended part spawns an add-on PartLine
            if finding.get("recommended_part_id"):
                part = db.store.catalog_parts[finding["recommended_part_id"]]
                qty = finding["recommended_quantity"]
                unit_cost = part["wholesale_cost_cents"]
                unit_price, line_total = calc.part_line_pricing(unit_cost, qty)
                pl = models.make_part_line(db.store, sid, finding["recommended_part_id"],
                                           qty, unit_cost, unit_price, line_total, is_addon=True)
                db.store.part_lines[pl["id"]] = pl

    # no PROPOSED remain -> back to IN_PROGRESS
    sr["status"] = "IN_PROGRESS"
    models.touch(sr, db.store)
    return response.success(models.serialize(sr), 200)


# ---- cancel ----
@bp.route("/service-requests/<sid>/cancel", methods=["POST"])
def cancel_request(sid):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    sr = _get_sr(sid)
    if uid != sr["customer_id"]:
        raise errors.not_owner("Customer may only cancel its own requests.")
    if sr["status"] not in {"INTAKE", "QUOTED", "APPROVED"}:
        raise errors.invalid_state("Request may only be cancelled pre-dispatch.")
    # supersede any SENT/REVISION_REQUESTED quote
    for q in db.store.quotes.values():
        if q["service_request_id"] == sid and q["status"] in {"SENT", "REVISION_REQUESTED"}:
            q["status"] = "SUPERSEDED"
            models.touch(q, db.store)
    sr["status"] = "CANCELLED"
    models.touch(sr, db.store)
    return response.success(models.serialize(sr), 200)


# ---- warranty claims (file / list) ----
@bp.route("/service-requests/<sid>/warranty-claims", methods=["POST"])
def file_warranty_claim(sid):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    sr = _get_sr(sid)
    if uid != sr["customer_id"]:
        raise errors.not_owner("Customer may only file claims on its own requests.")
    # state precondition (priority 5): request COMPLETED
    if sr["status"] != "COMPLETED":
        raise errors.invalid_state("Warranty claims may only be filed against COMPLETED requests.")
    body = validate.get_body()
    reason = validate.require_str(body, "reason_text")
    claim = models.make_warranty_claim(db.store, sid, reason, db.now_iso(db.store))
    db.store.warranty_claims[claim["id"]] = claim
    return response.success(models.serialize(claim), 201)


@bp.route("/service-requests/<sid>/warranty-claims", methods=["GET"])
def list_warranty_claims_for_request(sid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Customer", "Dispatcher"})
    sr = _get_sr(sid)
    if role == "Customer" and uid != sr["customer_id"]:
        raise errors.not_owner("Customer may only read its own claims.")
    limit, offset = parse_pagination()
    items = [w for w in db.store.warranty_claims.values()
             if w["service_request_id"] == sid]
    items = _sorted(items)
    page, total = paginate(items, limit, offset)
    return response.success_list([models.serialize(w) for w in page], limit, offset, total)


# ---- payments for a request ----
@bp.route("/service-requests/<sid>/payments", methods=["GET"])
def list_payments_for_request(sid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Customer", "FleetManager", "Dispatcher"})
    sr = _get_sr(sid)
    if role == "Customer" and uid != sr["customer_id"]:
        raise errors.not_owner("Customer may only read its own payments.")
    limit, offset = parse_pagination()
    items = [p for p in db.store.payments.values() if p["service_request_id"] == sid]
    items = _sorted(items)
    page, total = paginate(items, limit, offset)
    return response.success_list([models.serialize(p) for p in page], limit, offset, total)

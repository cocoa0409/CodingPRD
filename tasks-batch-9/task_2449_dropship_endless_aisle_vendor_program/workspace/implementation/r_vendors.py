"""Vendor onboarding, integration tests, serviceability rules and blackouts."""

from flask import Blueprint, request

import calc
import serialize
import validate as v
from auth import authenticate, require_vendor_scope
from db import db, new_row, now, touch
from errors import api_error
from response import created, listing, ok, paginate, pagination

bp = Blueprint("vendors", __name__)

MESSAGE_TYPES = ("CATALOG", "INVENTORY", "ORDER", "SHIP_CONFIRM")
SHIP_METHODS = ("GROUND", "TWO_DAY", "FREIGHT_LTL")
BLACKOUT_REASONS = ("HOLIDAY", "PEAK_FREEZE", "CAPACITY", "SYSTEM_CUTOVER")


def get_vendor(vendor_id):
    """Validation rank 3."""
    row = db.vendors.get(vendor_id)
    if row is None:
        api_error("ERR_VENDOR_NOT_FOUND", "vendor %s does not exist" % vendor_id)
    return row


# ------------------------------------------------------------ registration --


@bp.post("/dropship/vendors")
def create_vendor():
    authenticate(("PlatformAdmin", "VendorOpsAnalyst"))
    body = v.payload()

    vendor_code = v.req_str(body, "vendor_code", 1, 32, v.UPPER_CODE_RE)
    legal_name = v.req_str(body, "legal_name", 1, 200)
    cost_model = v.req_enum(body, "cost_model", ("COMMISSION", "WHOLESALE"))
    commission = v.opt_int(body, "commission_rate_bps", None, 0, 5000)
    wholesale = v.opt_int(body, "wholesale_discount_bps", None, 0, 5000)
    cadence = v.opt_int(body, "inventory_refresh_cadence_minutes", 1440, 1, 1440)
    buffer_units = v.opt_int(body, "safety_buffer_units", 0, 0, None)
    grace_units = v.opt_int(body, "oversell_grace_units", 0, 0, None)
    lead_days = v.opt_int(body, "default_lead_time_days", 0, 0, 60)
    ack_hours = v.opt_int(body, "ack_sla_hours", 24, 1, 168)
    grace_hours = v.opt_int(body, "ship_sla_grace_hours", 12, 0, 168)
    padding = v.opt_int(body, "promise_padding_days", calc.PROMISE_DEFAULT_PADDING_DAYS, 0, 5)

    # rank 14: cost-model field agreement
    if cost_model == "COMMISSION":
        if not v.has_value(body, "commission_rate_bps"):
            api_error("ERR_COST_MODEL_FIELD_MISMATCH",
                      "commission_rate_bps is required for a COMMISSION vendor")
        if v.has_value(body, "wholesale_discount_bps"):
            api_error("ERR_COST_MODEL_FIELD_MISMATCH",
                      "wholesale_discount_bps must be omitted for a COMMISSION vendor")
        wholesale = None
    else:
        if not v.has_value(body, "wholesale_discount_bps"):
            api_error("ERR_COST_MODEL_FIELD_MISMATCH",
                      "wholesale_discount_bps is required for a WHOLESALE vendor")
        if v.has_value(body, "commission_rate_bps"):
            api_error("ERR_COST_MODEL_FIELD_MISMATCH",
                      "commission_rate_bps must be omitted for a WHOLESALE vendor")
        commission = None

    # rank 15: uniqueness
    for existing in db.vendors.values():
        if existing["vendor_code"] == vendor_code:
            api_error("ERR_DUPLICATE_VENDOR_CODE",
                      "vendor_code %s already exists" % vendor_code)

    row = new_row()
    row.update({
        "vendor_code": vendor_code,
        "legal_name": legal_name,
        "cost_model": cost_model,
        "commission_rate_bps": commission,
        "wholesale_discount_bps": wholesale,
        "inventory_refresh_cadence_minutes": cadence,
        "safety_buffer_units": buffer_units,
        "oversell_grace_units": grace_units,
        "default_lead_time_days": lead_days,
        "ack_sla_hours": ack_hours,
        "ship_sla_grace_hours": grace_hours,
        "onboarding_status": "DRAFT",
        "integration_round": 0,
        "certified_by_user_id": None,
        "activated_by_user_id": None,
        "suspension_reason": None,
        "performance_tier": "UNRATED",
        "promise_padding_days": padding,
        "settlement_balance_cents": 0,
        "chargeback_balance_cents": 0,
    })
    db.vendors[row["id"]] = row
    return created(serialize.vendor(row))


@bp.get("/dropship/vendors/<vendor_id>")
def read_vendor(vendor_id):
    caller = authenticate(("PlatformAdmin", "VendorOpsAnalyst", "MerchandiseManager",
                           "VendorUser", "CareAgent"))
    row = get_vendor(vendor_id)
    require_vendor_scope(caller, vendor_id)
    return ok(serialize.vendor(row))


# -------------------------------------------------------------- lifecycle --


@bp.post("/dropship/vendors/<vendor_id>/begin-integration")
def begin_integration(vendor_id):
    authenticate(("VendorOpsAnalyst", "PlatformAdmin"))
    vendor = get_vendor(vendor_id)

    status = vendor["onboarding_status"]
    if status == "DRAFT":
        vendor["integration_round"] = 1
        vendor["certified_by_user_id"] = None
    elif status == "INTEGRATION_TESTING":
        failed = [
            t for t in db.integration_tests.values()
            if t["vendor_id"] == vendor_id
            and t["round_number"] == vendor["integration_round"]
            and t["status"] == "FAILED"
        ]
        if not failed:
            api_error("ERR_VENDOR_INVALID_STATE",
                      "a new integration round requires at least one FAILED run in the current round")
        vendor["integration_round"] = vendor["integration_round"] + 1
        vendor["certified_by_user_id"] = None
    else:
        api_error("ERR_VENDOR_INVALID_STATE",
                  "begin-integration is not allowed from %s" % status)

    vendor["onboarding_status"] = "INTEGRATION_TESTING"
    touch(vendor)
    return ok(serialize.vendor(vendor))


@bp.post("/dropship/vendors/<vendor_id>/certify")
def certify_vendor(vendor_id):
    caller = authenticate(("VendorOpsAnalyst", "PlatformAdmin"))
    vendor = get_vendor(vendor_id)

    if vendor["onboarding_status"] != "INTEGRATION_TESTING":
        api_error("ERR_VENDOR_INVALID_STATE",
                  "certify is not allowed from %s" % vendor["onboarding_status"])

    for message_type in MESSAGE_TYPES:
        passed = [
            t for t in db.integration_tests.values()
            if t["vendor_id"] == vendor_id
            and t["round_number"] == vendor["integration_round"]
            and t["status"] == "PASSED"
            and t["message_type"] == message_type
        ]
        if not passed:
            api_error("ERR_INTEGRATION_INCOMPLETE",
                      "no PASSED %s run in round %d" % (message_type, vendor["integration_round"]))

    vendor["onboarding_status"] = "CERTIFIED"
    vendor["certified_by_user_id"] = caller.user_id
    touch(vendor)
    return ok(serialize.vendor(vendor))


@bp.post("/dropship/vendors/<vendor_id>/activate")
def activate_vendor(vendor_id):
    caller = authenticate(("MerchandiseManager", "PlatformAdmin"))
    vendor = get_vendor(vendor_id)

    if vendor["onboarding_status"] != "CERTIFIED":
        api_error("ERR_VENDOR_INVALID_STATE",
                  "activate is not allowed from %s" % vendor["onboarding_status"])

    if vendor["certified_by_user_id"] is not None and caller.user_id == vendor["certified_by_user_id"]:
        api_error("ERR_SEGREGATION_OF_DUTIES",
                  "the activating user must differ from the certifying user")

    if not calc.has_active_coverage(vendor_id):
        api_error("ERR_NO_SERVICEABILITY_COVERAGE",
                  "vendor has no ACTIVE serviceability rule")

    vendor["onboarding_status"] = "ACTIVE"
    vendor["activated_by_user_id"] = caller.user_id
    vendor["suspension_reason"] = None
    touch(vendor)
    return ok(serialize.vendor(vendor))


@bp.post("/dropship/vendors/<vendor_id>/suspend")
def suspend_vendor(vendor_id):
    authenticate(("MerchandiseManager", "PlatformAdmin"))
    vendor = get_vendor(vendor_id)

    if vendor["onboarding_status"] != "ACTIVE":
        api_error("ERR_VENDOR_INVALID_STATE",
                  "suspend is not allowed from %s" % vendor["onboarding_status"])

    vendor["onboarding_status"] = "SUSPENDED"
    vendor["suspension_reason"] = "MANUAL_OPS"
    touch(vendor)
    calc.suspension_cascade(vendor)
    return ok(serialize.vendor(vendor))


@bp.post("/dropship/vendors/<vendor_id>/reinstate")
def reinstate_vendor(vendor_id):
    authenticate(("MerchandiseManager", "PlatformAdmin"))
    vendor = get_vendor(vendor_id)

    if vendor["onboarding_status"] != "SUSPENDED":
        api_error("ERR_VENDOR_INVALID_STATE",
                  "reinstate is not allowed from %s" % vendor["onboarding_status"])

    if vendor["suspension_reason"] == "SCORECARD_PROBATION":
        latest = calc.latest_published_scorecard(vendor_id)
        if latest is None or latest["tier"] == "PROBATION":
            api_error("ERR_VENDOR_INVALID_STATE",
                      "a probation suspension requires a newer non-PROBATION published scorecard")

    vendor["onboarding_status"] = "ACTIVE"
    vendor["suspension_reason"] = None
    touch(vendor)
    calc.reinstate_cascade(vendor)
    return ok(serialize.vendor(vendor))


# ------------------------------------------------------ integration tests --


@bp.post("/dropship/vendors/<vendor_id>/integration-tests")
def create_integration_test(vendor_id):
    caller = authenticate(("VendorOpsAnalyst", "PlatformAdmin"))
    vendor = get_vendor(vendor_id)
    body = v.payload()

    message_type = v.req_enum(body, "message_type", MESSAGE_TYPES)
    digest = v.req_str(body, "sample_payload_digest", 8, 64, v.HEX_RE)

    row = new_row()
    row.update({
        "vendor_id": vendor_id,
        "message_type": message_type,
        "round_number": vendor["integration_round"],
        "sample_payload_digest": digest,
        "reported_error_count": 0,
        "status": "PENDING",
        "created_by_user_id": caller.user_id,
        "evaluated_by_user_id": None,
        "defect_notes": None,
        "evaluated_at": None,
    })
    db.integration_tests[row["id"]] = row
    return created(serialize.integration_test(row))


@bp.get("/dropship/vendors/<vendor_id>/integration-tests")
def list_integration_tests(vendor_id):
    authenticate(("PlatformAdmin", "VendorOpsAnalyst", "VendorUser"))
    get_vendor(vendor_id)

    message_type = v.filter_enum(request.args, "message_type", MESSAGE_TYPES)
    status = v.filter_enum(request.args, "status", ("PENDING", "PASSED", "FAILED"))
    round_number = v.filter_int(request.args, "round_number", 0)
    limit, offset = pagination(request.args)

    rows = [t for t in db.integration_tests.values() if t["vendor_id"] == vendor_id]
    if message_type is not None:
        rows = [t for t in rows if t["message_type"] == message_type]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    if round_number is not None:
        rows = [t for t in rows if t["round_number"] == round_number]

    rows = sorted(rows, key=lambda t: (t["created_at"], t["_seq"]))
    page, total = paginate(rows, limit, offset)
    return listing([serialize.integration_test(t) for t in page], limit, offset, total)


@bp.post("/dropship/integration-tests/<test_id>/evaluate")
def evaluate_integration_test(test_id):
    caller = authenticate(("VendorOpsAnalyst", "PlatformAdmin"))

    run = db.integration_tests.get(test_id)
    if run is None:
        api_error("ERR_INTEGRATION_TEST_NOT_FOUND",
                  "integration test %s does not exist" % test_id)

    body = v.payload()
    outcome = v.req_enum(body, "outcome", ("PASS", "FAIL"))
    error_count = v.opt_int(body, "reported_error_count", None, 0, None)
    notes = v.opt_str(body, "defect_notes", None, 0, 500)
    if outcome == "FAIL" and (notes is None or notes.strip() == ""):
        api_error("ERR_INVALID_REQUEST", "defect_notes is required when outcome is FAIL")

    if run["status"] != "PENDING":
        api_error("ERR_INTEGRATION_TEST_INVALID_STATE",
                  "integration test is already %s" % run["status"])

    vendor = db.vendors.get(run["vendor_id"])
    if run["round_number"] != (vendor["integration_round"] if vendor else None):
        api_error("ERR_INTEGRATION_TEST_INVALID_STATE",
                  "integration test belongs to a closed round")

    if vendor is None or vendor["onboarding_status"] != "INTEGRATION_TESTING":
        api_error("ERR_VENDOR_INVALID_STATE",
                  "the owning vendor is not in INTEGRATION_TESTING")

    if run["created_by_user_id"] is not None and caller.user_id == run["created_by_user_id"]:
        api_error("ERR_SEGREGATION_OF_DUTIES",
                  "the evaluating user must differ from the recording user")

    run["status"] = "PASSED" if outcome == "PASS" else "FAILED"
    run["evaluated_by_user_id"] = caller.user_id
    run["evaluated_at"] = now()
    run["defect_notes"] = notes
    if error_count is not None:
        run["reported_error_count"] = error_count
    touch(run)
    return ok(serialize.integration_test(run))


# -------------------------------------------------- serviceability rules --


@bp.post("/dropship/vendors/<vendor_id>/serviceability-rules")
def create_rule(vendor_id):
    authenticate(("MerchandiseManager", "PlatformAdmin"))
    get_vendor(vendor_id)
    body = v.payload()

    row = new_row()
    row.update({
        "vendor_id": vendor_id,
        "zone_code": v.req_str(body, "zone_code", 1, 16, v.UPPER_CODE_RE),
        "ship_method": v.req_enum(body, "ship_method", SHIP_METHODS),
        "transit_days": v.req_int(body, "transit_days", 1, 30),
        "cutoff_hour_utc": v.req_int(body, "cutoff_hour_utc", 0, 23),
        "surcharge_cents": v.opt_int(body, "surcharge_cents", 0, 0, None),
        "status": "ACTIVE",
        "inactivated_by_suspension": False,
    })
    db.rules[row["id"]] = row
    return created(serialize.rule(row))


@bp.get("/dropship/vendors/<vendor_id>/serviceability-rules")
def list_rules(vendor_id):
    authenticate(("PlatformAdmin", "VendorOpsAnalyst", "MerchandiseManager", "VendorUser"))
    get_vendor(vendor_id)

    zone_code = v.filter_str(request.args, "zone_code")
    ship_method = v.filter_enum(request.args, "ship_method", SHIP_METHODS)
    status = v.filter_enum(request.args, "status", ("ACTIVE", "INACTIVE"))
    limit, offset = pagination(request.args)

    rows = [r for r in db.rules.values() if r["vendor_id"] == vendor_id]
    if zone_code is not None:
        rows = [r for r in rows if r["zone_code"] == zone_code]
    if ship_method is not None:
        rows = [r for r in rows if r["ship_method"] == ship_method]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return listing([serialize.rule(r) for r in page], limit, offset, total)


# --------------------------------------------------------------- blackouts --


@bp.post("/dropship/vendors/<vendor_id>/blackouts")
def create_blackout(vendor_id):
    authenticate(("PlatformAdmin", "VendorOpsAnalyst"))
    get_vendor(vendor_id)
    body = v.payload()

    start_date = v.req_date(body, "start_date")
    end_date = v.req_date(body, "end_date")
    reason = v.req_enum(body, "reason", BLACKOUT_REASONS)
    buffer_days = v.opt_int(body, "reopen_buffer_days", 1, 0, 14)

    # rank 13
    if end_date < start_date:
        api_error("ERR_INVALID_INTERVAL", "end_date must be on or after start_date")

    # rank 34
    for other in db.blackouts.values():
        if other["vendor_id"] != vendor_id or other["status"] != "ACTIVE":
            continue
        if start_date <= other["end_date"] and other["start_date"] <= end_date:
            api_error("ERR_BLACKOUT_WINDOW_CONFLICT",
                      "the window overlaps an existing ACTIVE blackout")
        if start_date > other["end_date"]:
            if (start_date - other["end_date"]).days <= other["reopen_buffer_days"]:
                api_error("ERR_BLACKOUT_WINDOW_CONFLICT",
                          "the window does not clear the earlier blackout's reopen buffer")
        else:
            if (other["start_date"] - end_date).days <= buffer_days:
                api_error("ERR_BLACKOUT_WINDOW_CONFLICT",
                          "the window does not clear the later blackout by its reopen buffer")

    row = new_row()
    row.update({
        "vendor_id": vendor_id,
        "start_date": start_date,
        "end_date": end_date,
        "reopen_buffer_days": buffer_days,
        "reason": reason,
        "status": "ACTIVE",
    })
    db.blackouts[row["id"]] = row
    return created(serialize.blackout(row))


@bp.get("/dropship/vendors/<vendor_id>/blackouts")
def list_blackouts(vendor_id):
    authenticate(("PlatformAdmin", "VendorOpsAnalyst", "MerchandiseManager", "VendorUser"))
    get_vendor(vendor_id)

    status = v.filter_enum(request.args, "status", ("ACTIVE", "CANCELLED"))
    limit, offset = pagination(request.args)

    rows = [b for b in db.blackouts.values() if b["vendor_id"] == vendor_id]
    if status is not None:
        rows = [b for b in rows if b["status"] == status]

    rows = sorted(rows, key=lambda b: (b["created_at"], b["_seq"]))
    page, total = paginate(rows, limit, offset)
    return listing([serialize.blackout(b) for b in page], limit, offset, total)


@bp.delete("/dropship/vendors/<vendor_id>/blackouts/<blackout_id>")
def cancel_blackout(vendor_id, blackout_id):
    authenticate(("PlatformAdmin", "VendorOpsAnalyst"))
    get_vendor(vendor_id)

    row = db.blackouts.get(blackout_id)
    if row is None or row["vendor_id"] != vendor_id:
        api_error("ERR_BLACKOUT_NOT_FOUND",
                  "blackout %s does not exist for this vendor" % blackout_id)

    if row["status"] != "CANCELLED":
        row["status"] = "CANCELLED"
        touch(row)
    return ok(serialize.blackout(row))

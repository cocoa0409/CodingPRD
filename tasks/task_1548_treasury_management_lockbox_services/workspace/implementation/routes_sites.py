"""Lockbox sites, availability schedules, transmission formats."""
import re
from zoneinfo import ZoneInfo

from appobj import api
from store import (
    banks, customers, agreements, sites, formats, schedules, batches, items,
    image_requests,
)
from util import (
    ApiError, ok, body, req_str, opt_str, req_int, req_enum, opt_bool,
    req_date_field, opt_date_field, new_entity, touch, pub, list_response,
    invalid,
)
from helpers import (
    auth, require_role, R_bank, R_customer, R_agreement, R_site, check_posture,
    bad_state,
)

IMPL = {"TreasuryImplementer"}
ACT = {"TreasuryActivator"}
CUTOFF_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
PATTERN_RE = re.compile(r"^\d{1,9}$")
TIERS = {"SAME_DAY", "ONE_DAY", "TWO_DAY"}
FORMAT_KINDS = {"BAI2", "EDI820", "CUSTOM_CSV"}


def _resolve_site(bankId, customerId, agreementId, siteId, uid=None, role=None):
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    a = R_agreement(c, agreementId)
    s = R_site(a, siteId)
    return bank, c, a, s


# ---------------------------------------------------------------------------
# Lockbox sites
# ---------------------------------------------------------------------------

@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites")
def create_site(bankId, customerId, agreementId):
    uid, role = auth()
    require_role(role, IMPL)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    a = R_agreement(c, agreementId)
    b = body()
    site_code = req_str(b, "site_code")
    addr = req_str(b, "postal_box_address")
    cutoff = req_str(b, "daily_cutoff_time_local")
    if not CUTOFF_RE.match(cutoff):
        invalid("daily_cutoff_time_local must be HH:MM 24h")
    tz = req_str(b, "timezone")
    try:
        ZoneInfo(tz)
    except Exception:
        invalid("timezone must be a valid IANA name")
    check_posture(bank)
    for other in sites.values():
        if other["bank_id"] == bank["id"] and other["site_code"] == site_code:
            raise ApiError("ERR_DUPLICATE_UNIQUE_FIELD", 409,
                           "site_code already in use within this bank")
    s = new_entity({
        "agreement_id": a["id"],
        "customer_id": c["id"],
        "bank_id": bank["id"],
        "site_code": site_code,
        "postal_box_address": addr,
        "daily_cutoff_time_local": cutoff,
        "timezone": tz,
        "status": "PROVISIONING",
        "_ss": set(),
    })
    sites[s["id"]] = s
    return ok(pub(s), "object", 201)


@api.get("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>")
def get_site(bankId, customerId, agreementId, siteId):
    uid, role = auth()
    bank, c, a, s = _resolve_site(bankId, customerId, agreementId, siteId, uid, role)
    return ok(pub(s))


@api.get("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites")
def list_sites(bankId, customerId, agreementId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    a = R_agreement(c, agreementId)
    rows = [s for s in sites.values() if s["agreement_id"] == a["id"]]
    return list_response(rows, ["status"])


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/go_live")
def go_live_site(bankId, customerId, agreementId, siteId):
    uid, role = auth()
    require_role(role, ACT)
    bank, c, a, s = _resolve_site(bankId, customerId, agreementId, siteId)
    check_posture(bank)
    if s["status"] not in ("PROVISIONING", "SUSPENDED"):
        bad_state("site is not PROVISIONING or SUSPENDED")
    if a["status"] != "ACTIVE":
        bad_state("parent agreement is not ACTIVE")
    if s["status"] == "PROVISIONING":
        if not any(x["site_id"] == s["id"] and x["status"] == "ACTIVE"
                   for x in schedules.values()):
            raise ApiError("ERR_SITE_LACKS_AVAILABILITY_SCHEDULE", 409,
                           "go_live requires at least one ACTIVE availability schedule")
        if not any(f["agreement_id"] == a["id"] and f["status"] == "ACTIVE"
                   for f in formats.values()):
            raise ApiError("ERR_SITE_LACKS_TRANSMISSION_FORMAT", 409,
                           "go_live requires at least one ACTIVE transmission format")
    else:  # SUSPENDED re-entry
        if c["status"] != "ACTIVE":
            raise ApiError("ERR_CUSTOMER_NOT_ACTIVE", 409,
                           "customer must be ACTIVE to return a site to LIVE")
    s["status"] = "LIVE"
    s["_ss"] = set()
    touch(s)
    for bt in batches.values():
        if bt["site_id"] == s["id"] and bt["_held"]:
            bt["_held"] = False
            touch(bt)
    return ok(pub(s))


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/suspend")
def suspend_site(bankId, customerId, agreementId, siteId):
    uid, role = auth()
    require_role(role, ACT)
    bank, c, a, s = _resolve_site(bankId, customerId, agreementId, siteId)
    check_posture(bank)
    if s["status"] != "LIVE":
        bad_state("site is not LIVE")
    s["status"] = "SUSPENDED"
    s["_ss"].add("manual")
    touch(s)
    return ok(pub(s))


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/decommission")
def decommission_site(bankId, customerId, agreementId, siteId):
    uid, role = auth()
    require_role(role, ACT)
    bank, c, a, s = _resolve_site(bankId, customerId, agreementId, siteId)
    check_posture(bank)
    if s["status"] not in ("LIVE", "SUSPENDED"):
        bad_state("site is not LIVE or SUSPENDED")
    for bt in batches.values():
        if (bt["site_id"] == s["id"] and bt["capture_status"]
                in ("RECEIVED", "CAPTURING", "BALANCED", "OUT_OF_BALANCE")):
            raise ApiError("ERR_SITE_HAS_OPEN_BATCHES", 409,
                           "site has batches in non-terminal capture status")
    if s["status"] == "LIVE":
        site_items = {i["id"] for i in items.values() if i["site_id"] == s["id"]}
        for r in image_requests.values():
            if r["item_id"] in site_items and r["status"] == "REQUESTED":
                bad_state("site has open image retrieval requests")
    s["status"] = "DECOMMISSIONED"
    touch(s)
    return ok(pub(s))


# ---------------------------------------------------------------------------
# Availability schedules
# ---------------------------------------------------------------------------

def _resolve_schedule(bankId, customerId, agreementId, siteId, scheduleId,
                      uid=None, role=None):
    bank, c, a, s = _resolve_site(bankId, customerId, agreementId, siteId, uid, role)
    sch = schedules.get(scheduleId)
    if not sch or sch["site_id"] != s["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "availability schedule not found")
    return bank, c, a, s, sch


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/availability_schedules")
def create_schedule(bankId, customerId, agreementId, siteId):
    uid, role = auth()
    require_role(role, IMPL)
    bank, c, a, s = _resolve_site(bankId, customerId, agreementId, siteId)
    b = body()
    pattern = req_str(b, "routing_number_pattern")
    if not PATTERN_RE.match(pattern):
        invalid("routing_number_pattern must be 1-9 digits")
    tier = req_enum(b, "tier", TIERS)
    eff_from = req_date_field(b, "effective_from")
    eff_to = opt_date_field(b, "effective_to")
    if eff_to is not None and eff_to < eff_from:
        invalid("effective_to precedes effective_from")
    priority = req_int(b, "priority")
    check_posture(bank)
    sch = new_entity({
        "site_id": s["id"],
        "bank_id": bank["id"],
        "routing_number_pattern": pattern,
        "tier": tier,
        "effective_from": eff_from,
        "effective_to": eff_to,
        "priority": priority,
        "status": "ACTIVE",
    })
    schedules[sch["id"]] = sch
    return ok(pub(sch), "object", 201)


@api.get("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/availability_schedules")
def list_schedules(bankId, customerId, agreementId, siteId):
    uid, role = auth()
    bank, c, a, s = _resolve_site(bankId, customerId, agreementId, siteId, uid, role)
    rows = [x for x in schedules.values() if x["site_id"] == s["id"]]
    return list_response(rows, ["status", "tier"])


@api.get("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/availability_schedules/<scheduleId>")
def get_schedule(bankId, customerId, agreementId, siteId, scheduleId):
    uid, role = auth()
    bank, c, a, s, sch = _resolve_schedule(bankId, customerId, agreementId,
                                           siteId, scheduleId, uid, role)
    return ok(pub(sch))


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/sites/<siteId>/availability_schedules/<scheduleId>/retire")
def retire_schedule(bankId, customerId, agreementId, siteId, scheduleId):
    uid, role = auth()
    require_role(role, IMPL)
    bank, c, a, s, sch = _resolve_schedule(bankId, customerId, agreementId,
                                           siteId, scheduleId)
    check_posture(bank)
    if sch["status"] != "ACTIVE":
        bad_state("schedule is not ACTIVE")
    sch["status"] = "RETIRED"
    touch(sch)
    return ok(pub(sch))


# ---------------------------------------------------------------------------
# Transmission formats
# ---------------------------------------------------------------------------

def _resolve_format(bankId, customerId, agreementId, formatId, uid=None, role=None):
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    a = R_agreement(c, agreementId)
    f = formats.get(formatId)
    if not f or f["agreement_id"] != a["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "transmission format not found")
    return bank, c, a, f


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/transmission_formats")
def create_format(bankId, customerId, agreementId):
    uid, role = auth()
    require_role(role, IMPL)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    a = R_agreement(c, agreementId)
    b = body()
    kind = req_enum(b, "format_kind", FORMAT_KINDS)
    label = req_str(b, "version_label")
    supersedes = opt_str(b, "supersedes_format_id")
    incl_inv = opt_bool(b, "include_invoice_detail", default=False)
    incl_img = opt_bool(b, "include_images", default=False)
    check_posture(bank)
    if supersedes is not None:
        tgt = formats.get(supersedes)
        if not tgt or tgt["bank_id"] != bank["id"] or tgt["customer_id"] != c["id"] \
                or tgt["agreement_id"] != a["id"]:
            raise ApiError("ERR_INVALID_REFERENCE", 409,
                           "supersedes_format_id does not resolve within scope")
    f = new_entity({
        "agreement_id": a["id"],
        "customer_id": c["id"],
        "bank_id": bank["id"],
        "format_kind": kind,
        "version_label": label,
        "supersedes_format_id": supersedes,
        "include_invoice_detail": incl_inv,
        "include_images": incl_img,
        "status": "DRAFT",
    })
    formats[f["id"]] = f
    return ok(pub(f), "object", 201)


@api.get("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/transmission_formats/<formatId>")
def get_format(bankId, customerId, agreementId, formatId):
    uid, role = auth()
    bank, c, a, f = _resolve_format(bankId, customerId, agreementId, formatId, uid, role)
    return ok(pub(f))


@api.get("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/transmission_formats")
def list_formats(bankId, customerId, agreementId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    a = R_agreement(c, agreementId)
    rows = [f for f in formats.values() if f["agreement_id"] == a["id"]]
    return list_response(rows, ["status", "format_kind"])


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/transmission_formats/<formatId>/activate")
def activate_format(bankId, customerId, agreementId, formatId):
    uid, role = auth()
    require_role(role, ACT)
    bank, c, a, f = _resolve_format(bankId, customerId, agreementId, formatId)
    check_posture(bank)
    if f["status"] != "DRAFT":
        bad_state("transmission format is not DRAFT")
    if a["status"] != "ACTIVE":
        bad_state("parent agreement is not ACTIVE")
    b = body()
    expected = req_int(b, "expected_agreement_version")
    if expected != a["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_agreement_version does not match current version")
    f["status"] = "ACTIVE"
    touch(f)
    if f["supersedes_format_id"]:
        tgt = formats.get(f["supersedes_format_id"])
        if tgt and tgt["status"] == "ACTIVE":
            tgt["status"] = "SUPERSEDED"
            touch(tgt)
    touch(a)  # activation mutates the parent agreement (OCC token)
    return ok(pub(f))


@api.post("/banks/<bankId>/customers/<customerId>/agreements/<agreementId>/transmission_formats/<formatId>/retire")
def retire_format(bankId, customerId, agreementId, formatId):
    uid, role = auth()
    require_role(role, ACT)
    bank, c, a, f = _resolve_format(bankId, customerId, agreementId, formatId)
    check_posture(bank)
    if f["status"] not in ("ACTIVE", "SUPERSEDED"):
        bad_state("transmission format is not ACTIVE or SUPERSEDED")
    if f["status"] == "ACTIVE":
        for bt in batches.values():
            if (bt["agreement_id"] == a["id"]
                    and bt["transmission_status"] == "PENDING"):
                bad_state("batches still hold a PENDING transmission for this format")
    f["status"] = "RETIRED"
    touch(f)
    return ok(pub(f))

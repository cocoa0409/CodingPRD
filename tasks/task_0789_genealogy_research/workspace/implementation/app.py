"""Genealogy & Family-History Research Service API.

Python + Flask, in-memory only. The store starts empty on every boot; no
seeding, no preload, no persistence. The test harness restarts this process
via start.sh before every test.
"""
import os
import json
import math
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import Flask, request, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory stores (keyed by id). Wiped on every process start.
# ---------------------------------------------------------------------------
clients = {}
researchers = {}
repositories = {}
projects = {}
record_searches = {}
citations = {}
persons = {}
dna_interpretations = {}
document_requests = {}
heirlooms = {}
deliverables = {}
milestones = {}
time_entries = {}
appointments = {}

SEQ = 0  # monotonic insertion counter for stable ordering / tie-breaks

# Logical clock (operator-controlled test-driving value).
DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
LOGICAL_CLOCK = DEFAULT_CLOCK

ROLES = {"Client", "Researcher", "ProjectManager"}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
OVERAGE_RATE_CENTS = 8000
WEIGHT = {"PRIMARY": 3, "SECONDARY": 2, "INDIRECT": 1}
CONFIDENCE_DIVISOR = 6
TIER_DISCOUNT = {"STANDARD": Decimal("0.00"), "PREMIUM": Decimal("0.10")}
RUSH_SURCHARGE_CENTS = 5000
PRICE_CAP_MULTIPLIER = Decimal("1.5")
AGENCY_FEE_PCT = Decimal("0.075")
MAX_OVERAGE_MULTIPLIER = Decimal("1.5")
RESEARCHER_BUFFER = timedelta(minutes=30)

TIER_VALUES = {"STANDARD", "PREMIUM"}
PACKAGE_TYPES = {"HOURLY", "BASIC_PACKAGE", "PREMIUM_PACKAGE"}
PRIORITY_VALUES = {"STANDARD", "RUSH"}
SOURCE_TYPES = {"VITAL_RECORD", "CENSUS", "CHURCH", "DNA", "OTHER"}
QUALITY_VALUES = {"PRIMARY", "SECONDARY", "INDIRECT"}
ACTIVITY_TYPES = {"RESEARCH", "WRITING", "TRANSLATION", "ADMIN", "TRAVEL"}
DELIVERABLE_TYPES = {"RESEARCH_REPORT", "FAMILY_TREE", "DNA_SUMMARY"}
HEIRLOOM_CATEGORIES = {"PHOTO", "DOCUMENT", "ARTIFACT", "TEXTILE", "OTHER"}
ARCHIVE_STATES = {"RECEIVED", "CATALOGUED", "DIGITIZED", "RETURNED"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Helpers: time, ids, response envelope
# ---------------------------------------------------------------------------
def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def rand_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": rand_req_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def _respond(payload, status):
    return app.response_class(json.dumps(payload), status=status, mimetype="application/json")


def ok_object(data, status=200):
    return _respond({"meta": _meta(), "response_type": "object", "data": data}, status)


def ok_list(items, limit, offset, total):
    has_more = (offset + limit) < total
    extra = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return _respond({"meta": _meta(extra), "response_type": "array", "data": items}, 200)


def err_response(error_id, status, message):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _respond(payload, status)


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def require(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            try:
                uid = request.headers.get("X-User-ID")
                role = request.headers.get("X-User-Role")
                if not uid or not role or role not in ROLES:
                    raise ApiError("ERR_UNAUTHENTICATED", 401)
                if role not in roles:
                    raise ApiError("ERR_UNAUTHORIZED", 403)
                g.user_id = uid
                g.role = role
                return fn(*a, **kw)
            except ApiError as e:
                return err_response(e.error_id, e.http_status, e.message)
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# Body / validation helpers
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "request body must be a JSON object")
    return data


def _present(body, field):
    return field in body and body[field] is not None


def vstr(body, field, required=True, default=None):
    if not _present(body, field):
        if required:
            raise ApiError("ERR_VALIDATION", 400, f"{field} is required")
        return default
    v = body[field]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be a string")
    return v


def venum(body, field, allowed, required=True, default=None):
    if not _present(body, field):
        if required:
            raise ApiError("ERR_VALIDATION", 400, f"{field} is required")
        return default
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, f"{field} is invalid")
    return v


def vint(body, field, required=True, default=None, minimum=None):
    if not _present(body, field):
        if required:
            raise ApiError("ERR_VALIDATION", 400, f"{field} is required")
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", 400, f"{field} out of range")
    return v


def vnum(body, field, required=True, default=None, minimum=None, gt=None):
    if not _present(body, field):
        if required:
            raise ApiError("ERR_VALIDATION", 400, f"{field} is required")
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be a number")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", 400, f"{field} out of range")
    if gt is not None and not (v > gt):
        raise ApiError("ERR_VALIDATION", 400, f"{field} out of range")
    return v


def vbool(body, field, required=False, default=None):
    if not _present(body, field):
        if required:
            raise ApiError("ERR_VALIDATION", 400, f"{field} is required")
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be a boolean")
    return v


def varr(body, field, default=None):
    if not _present(body, field):
        return list(default) if default is not None else []
    v = body[field]
    if not isinstance(v, list):
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be an array")
    return v


def resolve_fk(body, field, store, not_found_error, required=True):
    """Existence check for a present FK; missing required FK -> validation."""
    if not _present(body, field):
        if required:
            raise ApiError("ERR_VALIDATION", 400, f"{field} is required")
        return None
    v = body[field]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be a string")
    ent = store.get(v)
    if ent is None:
        raise ApiError(not_found_error, 404, f"{field} not found")
    return ent


def must(store, ent_id, not_found_error):
    ent = store.get(ent_id)
    if ent is None:
        raise ApiError(not_found_error, 404)
    return ent


# ---------------------------------------------------------------------------
# Entity / mutation helpers
# ---------------------------------------------------------------------------
def new_entity(fields):
    global SEQ
    SEQ += 1
    ts = now_iso()
    ent = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": SEQ,
    }
    ent.update(fields)
    return ent


def touch(ent):
    ent["version"] += 1
    ent["updated_at"] = now_iso()


def serialize(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Money / confidence primitives
# ---------------------------------------------------------------------------
def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def confidence(point_sum):
    val = Decimal(point_sum) / Decimal(CONFIDENCE_DIVISOR)
    if val > 1:
        val = Decimal(1)
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def dna_predicted(cm):
    if cm >= 3400:
        return "PARENT_CHILD"
    if cm >= 2000:
        return "FULL_SIBLING"
    if cm >= 1300:
        return "CLOSE_FAMILY"
    if cm >= 200:
        return "COUSIN"
    return "UNRELATED"


# ---------------------------------------------------------------------------
# Derived-field recomputation
# ---------------------------------------------------------------------------
def recompute_person(pe):
    pid = pe["id"]
    cits = [c for c in citations.values() if c["person_id"] == pid]
    non_disputed = [c for c in cits if c["verification_status"] != "DISPUTED"]
    verified = [c for c in cits if c["verification_status"] == "VERIFIED"]
    pe["citation_count"] = len(non_disputed)
    pe["verified_citation_count"] = len(verified)
    pe["provisional_confidence"] = confidence(sum(WEIGHT[c["quality"]] for c in non_disputed))
    pe["confidence_score"] = confidence(sum(WEIGHT[c["quality"]] for c in verified))


def recompute_project(p):
    pid = p["id"]
    budget = Decimal(str(p["budget_hours"]))

    consumed = 0
    for te in time_entries.values():
        if te["project_id"] == pid and te["status"] == "ACTIVE" and te["billable"]:
            consumed += te["hours"]
    p["consumed_hours"] = consumed

    vpc = sum(1 for pe in persons.values()
              if pe["project_id"] == pid and pe["verification_status"] == "VERIFIED")
    p["verified_person_count"] = vpc

    p["accepted_deliverable_count"] = sum(
        1 for d in deliverables.values()
        if d["project_id"] == pid and d["status"] == "ACCEPTED")

    p["ready_milestone_amount_cents"] = sum(
        m["amount_cents"] for m in milestones.values()
        if m["project_id"] == pid and m["status"] == "READY")

    p["research_status"] = ("RESEARCH_COMPLETE"
                            if vpc >= p["target_person_count"] else "IN_PROGRESS")

    # Estimated cost: non-cancelled searches' estimated_hours.
    est_hours = Decimal("0")
    for rs in record_searches.values():
        if rs["project_id"] == pid and rs["status"] in ("PENDING", "COMPLETED", "NO_RESULTS"):
            est_hours += Decimal(str(rs["estimated_hours"]))
    est_overage = est_hours - budget
    if est_overage < 0:
        est_overage = Decimal("0")
    p["estimated_cost_cents"] = (p["package_price_cents"]
                                 + int(math.ceil(est_overage)) * OVERAGE_RATE_CENTS)

    # Actual cost: ACTIVE billable logged hours.
    act_overage = Decimal(str(consumed)) - budget
    if act_overage < 0:
        act_overage = Decimal("0")
    p["actual_cost_cents"] = (p["package_price_cents"]
                              + int(math.ceil(act_overage)) * OVERAGE_RATE_CENTS)

    # Billable amount: per-milestone rounded line totals for INVOICED|PAID.
    ms = [m for m in milestones.values()
          if m["project_id"] == pid and m["status"] in ("INVOICED", "PAID")]
    ms.sort(key=lambda m: (m["sequence_no"], m["_seq"]))
    billable = 0
    for m in ms:
        fee = round_half_up_cents(Decimal(m["invoiced_amount_cents"]) * AGENCY_FEE_PCT)
        m["line_total_cents"] = m["invoiced_amount_cents"] + fee
        billable += m["line_total_cents"]
    p["billable_amount_cents"] = billable

    p["outstanding_balance_cents"] = (p["invoiced_total_cents"]
                                      - p["paid_total_cents"]
                                      - p["credited_total_cents"])


def ser_project(p):
    recompute_project(p)
    return serialize(p)


def ser_person(pe):
    recompute_person(pe)
    return serialize(pe)


def bump_project(p):
    """Cascade version/updated_at bump on a project touched by a child op."""
    recompute_project(p)
    touch(p)


# ---------------------------------------------------------------------------
# Pagination + generic listing
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 400, "limit out of range")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 400, "offset out of range")
    return limit, offset


def do_list(store, allowed_filters, recompute=None):
    limit, offset = parse_pagination()
    items = list(store.values())
    for f in allowed_filters:
        if f in request.args:
            val = request.args.get(f)
            items = [x for x in items if str(x.get(f)) == val]
    items.sort(key=lambda x: x["_seq"])
    total = len(items)
    window = items[offset:offset + limit]
    if recompute:
        for x in window:
            recompute(x)
    return ok_list([serialize(x) for x in window], limit, offset, total)


# ===========================================================================
# CLIENTS
# ===========================================================================
@app.post("/genealogy/clients")
@require("ProjectManager")
def create_client():
    try:
        body = get_body()
        name = vstr(body, "name")
        email = vstr(body, "email")
        tier = venum(body, "tier", TIER_VALUES, required=False, default="STANDARD")
        for c in clients.values():
            if c["email"] == email:
                raise ApiError("ERR_VALIDATION", 400, "email must be unique")
        ent = new_entity({"name": name, "email": email, "tier": tier, "status": "ACTIVE"})
        clients[ent["id"]] = ent
        return ok_object(serialize(ent), 201)
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/clients/<cid>")
@require("ProjectManager", "Client")
def get_client(cid):
    try:
        ent = must(clients, cid, "ERR_CLIENT_NOT_FOUND")
        return ok_object(serialize(ent))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


# ===========================================================================
# RESEARCHERS
# ===========================================================================
@app.post("/genealogy/researchers")
@require("ProjectManager")
def create_researcher():
    try:
        body = get_body()
        name = vstr(body, "name")
        email = vstr(body, "email")
        rate = vint(body, "hourly_rate_cents", minimum=0)
        specialties = varr(body, "specialties", default=[])
        for r in researchers.values():
            if r["email"] == email:
                raise ApiError("ERR_VALIDATION", 400, "email must be unique")
        ent = new_entity({
            "name": name, "email": email,
            "hourly_rate_cents": rate, "specialties": specialties,
        })
        researchers[ent["id"]] = ent
        return ok_object(serialize(ent), 201)
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/researchers/<rid>")
@require("ProjectManager", "Researcher")
def get_researcher(rid):
    try:
        ent = must(researchers, rid, "ERR_RESEARCHER_NOT_FOUND")
        return ok_object(serialize(ent))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


# ===========================================================================
# REPOSITORIES
# ===========================================================================
@app.post("/genealogy/repositories")
@require("ProjectManager")
def create_repository():
    try:
        body = get_body()
        name = vstr(body, "name")
        location = vstr(body, "location")
        cap = vint(body, "concurrent_capacity", required=False, default=2, minimum=1)
        ent = new_entity({"name": name, "location": location, "concurrent_capacity": cap})
        repositories[ent["id"]] = ent
        return ok_object(serialize(ent), 201)
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/repositories/<rid>")
@require("ProjectManager", "Researcher")
def get_repository(rid):
    try:
        ent = must(repositories, rid, "ERR_REPOSITORY_NOT_FOUND")
        return ok_object(serialize(ent))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


# ===========================================================================
# RESEARCH PROJECTS
# ===========================================================================
@app.post("/genealogy/projects")
@require("Client", "ProjectManager")
def create_project():
    try:
        body = get_body()
        resolve_fk(body, "client_id", clients, "ERR_CLIENT_NOT_FOUND")
        resolve_fk(body, "lead_researcher_id", researchers, "ERR_RESEARCHER_NOT_FOUND")
        client_id = body["client_id"]
        lead = body["lead_researcher_id"]
        title = vstr(body, "title")
        objective = vstr(body, "objective")
        scope_note = vstr(body, "scope_note", required=False, default="")
        package_type = venum(body, "package_type", PACKAGE_TYPES)
        package_price = vint(body, "package_price_cents", minimum=0)
        budget_hours = vnum(body, "budget_hours", gt=0)
        priority = venum(body, "priority", PRIORITY_VALUES, required=False, default="STANDARD")
        target = vint(body, "target_person_count", required=False, default=1, minimum=1)
        ent = new_entity({
            "client_id": client_id,
            "lead_researcher_id": lead,
            "title": title,
            "objective": objective,
            "scope_note": scope_note,
            "package_type": package_type,
            "package_price_cents": package_price,
            "budget_hours": budget_hours,
            "priority": priority,
            "target_person_count": target,
            "status": "DRAFT",
            "research_status": "IN_PROGRESS",
            "consumed_hours": 0,
            "verified_person_count": 0,
            "accepted_deliverable_count": 0,
            "ready_milestone_amount_cents": 0,
            "estimated_cost_cents": 0,
            "actual_cost_cents": 0,
            "invoiced_total_cents": 0,
            "credited_total_cents": 0,
            "paid_total_cents": 0,
            "outstanding_balance_cents": 0,
            "billable_amount_cents": 0,
        })
        projects[ent["id"]] = ent
        return ok_object(ser_project(ent), 201)
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/projects/<pid>")
@require("Client", "Researcher", "ProjectManager")
def get_project(pid):
    try:
        ent = must(projects, pid, "ERR_PROJECT_NOT_FOUND")
        return ok_object(ser_project(ent))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/projects")
@require("Client", "Researcher", "ProjectManager")
def list_projects():
    try:
        return do_list(projects, ["client_id", "lead_researcher_id", "status"],
                       recompute=recompute_project)
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/projects/<pid>/activate")
@require("ProjectManager")
def activate_project(pid):
    try:
        p = must(projects, pid, "ERR_PROJECT_NOT_FOUND")
        if p["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409)
        p["status"] = "ACTIVE"
        touch(p)
        return ok_object(ser_project(p))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/projects/<pid>/close")
@require("ProjectManager")
def close_project(pid):
    try:
        p = must(projects, pid, "ERR_PROJECT_NOT_FOUND")
        if p["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409)
        p["status"] = "CLOSED"
        touch(p)
        # Cascade: ORDERED DNA interpretations are cancelled when the project closes.
        for d in dna_interpretations.values():
            if d["project_id"] == pid and d["status"] == "ORDERED":
                d["status"] = "CANCELLED"
                touch(d)
        return ok_object(ser_project(p))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/projects/<pid>/reconfigure")
@require("ProjectManager")
def reconfigure_project(pid):
    try:
        p = must(projects, pid, "ERR_PROJECT_NOT_FOUND")
        body = get_body()
        expected = vint(body, "expected_project_version")
        package_type = venum(body, "package_type", PACKAGE_TYPES, required=False, default=None)
        budget_hours = vnum(body, "budget_hours", required=False, default=None, gt=0)
        package_price = vint(body, "package_price_cents", required=False, default=None, minimum=0)
        priority = venum(body, "priority", PRIORITY_VALUES, required=False, default=None)
        if p["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409)
        if expected != p["version"]:
            raise ApiError("ERR_STALE_PROJECT_VERSION", 412)
        if package_type is not None:
            p["package_type"] = package_type
        if budget_hours is not None:
            p["budget_hours"] = budget_hours
        if package_price is not None:
            p["package_price_cents"] = package_price
        if priority is not None:
            p["priority"] = priority
        touch(p)
        return ok_object(ser_project(p))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


# ===========================================================================
# RECORD SEARCHES
# ===========================================================================
@app.post("/genealogy/record-searches")
@require("Researcher", "ProjectManager")
def create_record_search():
    try:
        body = get_body()
        p = resolve_fk(body, "project_id", projects, "ERR_PROJECT_NOT_FOUND")
        repo_name = vstr(body, "repository_name")
        terms = vstr(body, "search_terms")
        est_hours = vnum(body, "estimated_hours", minimum=0)
        if p["status"] != "ACTIVE":
            raise ApiError("ERR_PROJECT_NOT_ACTIVE", 409)
        ent = new_entity({
            "project_id": p["id"],
            "performed_by_id": g.user_id,
            "repository_name": repo_name,
            "search_terms": terms,
            "estimated_hours": est_hours,
            "result_summary": "",
            "status": "PENDING",
        })
        record_searches[ent["id"]] = ent
        recompute_project(p)
        return ok_object(serialize(ent), 201)
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/record-searches/<rid>")
@require("Client", "Researcher", "ProjectManager")
def get_record_search(rid):
    try:
        ent = must(record_searches, rid, "ERR_RECORD_SEARCH_NOT_FOUND")
        return ok_object(serialize(ent))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/record-searches")
@require("Client", "Researcher", "ProjectManager")
def list_record_searches():
    try:
        return do_list(record_searches, ["project_id", "performed_by_id", "status"])
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/record-searches/<rid>/complete")
@require("Researcher")
def complete_record_search(rid):
    try:
        rs = must(record_searches, rid, "ERR_RECORD_SEARCH_NOT_FOUND")
        body = get_body()
        outcome = venum(body, "outcome", {"COMPLETED", "NO_RESULTS"})
        summary = vstr(body, "result_summary", required=False, default=None)
        if rs["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", 409)
        if outcome == "COMPLETED":
            rs["status"] = "COMPLETED"
            if summary is not None:
                rs["result_summary"] = summary
        else:
            rs["status"] = "NO_RESULTS"
        touch(rs)
        return ok_object(serialize(rs))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


# ===========================================================================
# SOURCE CITATIONS
# ===========================================================================
@app.post("/genealogy/citations")
@require("Researcher")
def create_citation():
    try:
        body = get_body()
        rs = resolve_fk(body, "record_search_id", record_searches, "ERR_RECORD_SEARCH_NOT_FOUND")
        pe = resolve_fk(body, "person_id", persons, "ERR_PERSON_NOT_FOUND")
        citation_text = vstr(body, "citation_text")
        source_type = venum(body, "source_type", SOURCE_TYPES)
        quality = venum(body, "quality", QUALITY_VALUES)
        if rs["project_id"] != pe["project_id"]:
            raise ApiError("ERR_CROSS_PROJECT_REFERENCE", 409)
        if rs["status"] != "COMPLETED":
            raise ApiError("ERR_SEARCH_NOT_COMPLETED", 409)
        ent = new_entity({
            "project_id": rs["project_id"],
            "record_search_id": rs["id"],
            "person_id": pe["id"],
            "citation_text": citation_text,
            "source_type": source_type,
            "quality": quality,
            "verification_status": "UNVERIFIED",
        })
        citations[ent["id"]] = ent
        recompute_person(pe)
        return ok_object(serialize(ent), 201)
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/citations/<cid>")
@require("Client", "Researcher", "ProjectManager")
def get_citation(cid):
    try:
        ent = must(citations, cid, "ERR_CITATION_NOT_FOUND")
        return ok_object(serialize(ent))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/citations")
@require("Client", "Researcher", "ProjectManager")
def list_citations():
    try:
        return do_list(citations,
                       ["project_id", "person_id", "record_search_id", "verification_status"])
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/citations/<cid>/verify")
@require("Researcher", "ProjectManager")
def verify_citation(cid):
    try:
        c = must(citations, cid, "ERR_CITATION_NOT_FOUND")
        if c["verification_status"] != "UNVERIFIED":
            raise ApiError("ERR_INVALID_STATE", 409)
        c["verification_status"] = "VERIFIED"
        touch(c)
        pe = persons.get(c["person_id"])
        if pe is not None:
            recompute_person(pe)
            if (pe["verification_status"] == "UNDER_REVIEW"
                    and pe["confidence_score"] >= 0.75
                    and pe["verified_citation_count"] >= 2):
                pe["verification_status"] = "VERIFIED"
                touch(pe)
                proj = projects.get(pe["project_id"])
                if proj is not None:
                    bump_project(proj)
        return ok_object(serialize(c))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/citations/<cid>/dispute")
@require("Researcher", "ProjectManager")
def dispute_citation(cid):
    try:
        c = must(citations, cid, "ERR_CITATION_NOT_FOUND")
        get_body()  # optional reason ignored
        if c["verification_status"] not in ("UNVERIFIED", "VERIFIED"):
            raise ApiError("ERR_INVALID_STATE", 409)
        c["verification_status"] = "DISPUTED"
        touch(c)
        pe = persons.get(c["person_id"])
        if pe is not None:
            recompute_person(pe)
            if (pe["verification_status"] == "VERIFIED"
                    and (pe["confidence_score"] < 0.75
                         or pe["verified_citation_count"] < 2)):
                pe["verification_status"] = "UNDER_REVIEW"
                touch(pe)
                proj = projects.get(pe["project_id"])
                if proj is not None:
                    bump_project(proj)
        return ok_object(serialize(c))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


# ===========================================================================
# PERSONS
# ===========================================================================
@app.post("/genealogy/persons")
@require("Researcher")
def create_person():
    try:
        body = get_body()
        p = resolve_fk(body, "project_id", projects, "ERR_PROJECT_NOT_FOUND")
        resolve_fk(body, "father_id", persons, "ERR_PERSON_NOT_FOUND", required=False)
        resolve_fk(body, "mother_id", persons, "ERR_PERSON_NOT_FOUND", required=False)
        full_name = vstr(body, "full_name")
        birth_year = vint(body, "birth_year", required=False, default=None)
        death_year = vint(body, "death_year", required=False, default=None)
        ent = new_entity({
            "project_id": p["id"],
            "father_id": body.get("father_id"),
            "mother_id": body.get("mother_id"),
            "full_name": full_name,
            "birth_year": birth_year,
            "death_year": death_year,
            "verification_status": "DRAFT",
            "citation_count": 0,
            "verified_citation_count": 0,
            "provisional_confidence": 0,
            "confidence_score": 0,
        })
        persons[ent["id"]] = ent
        return ok_object(ser_person(ent), 201)
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/persons/<pid>")
@require("Client", "Researcher", "ProjectManager")
def get_person(pid):
    try:
        ent = must(persons, pid, "ERR_PERSON_NOT_FOUND")
        return ok_object(ser_person(ent))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/persons")
@require("Client", "Researcher", "ProjectManager")
def list_persons():
    try:
        return do_list(persons,
                       ["project_id", "father_id", "mother_id", "verification_status"],
                       recompute=recompute_person)
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/persons/<pid>/submit-review")
@require("Researcher")
def submit_person_review(pid):
    try:
        pe = must(persons, pid, "ERR_PERSON_NOT_FOUND")
        if pe["verification_status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409)
        pe["verification_status"] = "UNDER_REVIEW"
        touch(pe)
        return ok_object(ser_person(pe))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/persons/<pid>/verify")
@require("Researcher", "ProjectManager")
def verify_person(pid):
    try:
        pe = must(persons, pid, "ERR_PERSON_NOT_FOUND")
        recompute_person(pe)
        if pe["verification_status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409)
        if pe["verified_citation_count"] < 2:
            raise ApiError("ERR_INSUFFICIENT_CITATIONS", 422)
        if pe["confidence_score"] < 0.75:
            raise ApiError("ERR_CONFIDENCE_BELOW_THRESHOLD", 422)
        pe["verification_status"] = "VERIFIED"
        touch(pe)
        proj = projects.get(pe["project_id"])
        if proj is not None:
            bump_project(proj)
        return ok_object(ser_person(pe))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


# ===========================================================================
# DNA INTERPRETATIONS
# ===========================================================================
@app.post("/genealogy/dna-interpretations")
@require("Researcher")
def create_dna():
    try:
        body = get_body()
        p = resolve_fk(body, "project_id", projects, "ERR_PROJECT_NOT_FOUND")
        subject = resolve_fk(body, "subject_person_id", persons, "ERR_PERSON_NOT_FOUND")
        resolve_fk(body, "match_person_id", persons, "ERR_PERSON_NOT_FOUND", required=False)
        provider = vstr(body, "test_provider")
        addon_fee = vint(body, "addon_fee_cents", required=False, default=15000, minimum=0)
        ent = new_entity({
            "project_id": p["id"],
            "subject_person_id": subject["id"],
            "match_person_id": body.get("match_person_id"),
            "test_provider": provider,
            "cm_shared": None,
            "predicted_relationship": None,
            "addon_fee_cents": addon_fee,
            "status": "ORDERED",
        })
        dna_interpretations[ent["id"]] = ent
        return ok_object(serialize(ent), 201)
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/dna-interpretations/<did>")
@require("Client", "Researcher", "ProjectManager")
def get_dna(did):
    try:
        ent = must(dna_interpretations, did, "ERR_DNA_NOT_FOUND")
        return ok_object(serialize(ent))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/dna-interpretations")
@require("Client", "Researcher", "ProjectManager")
def list_dna():
    try:
        return do_list(dna_interpretations,
                       ["project_id", "subject_person_id", "match_person_id"])
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/dna-interpretations/<did>/interpret")
@require("Researcher")
def interpret_dna(did):
    try:
        d = must(dna_interpretations, did, "ERR_DNA_NOT_FOUND")
        body = get_body()
        cm = vint(body, "cm_shared", minimum=0)
        if d["status"] != "ORDERED":
            raise ApiError("ERR_INVALID_STATE", 409)
        subject = persons.get(d["subject_person_id"])
        if subject is None or subject["verification_status"] != "VERIFIED":
            raise ApiError("ERR_SUBJECT_NOT_VERIFIED", 409)
        d["cm_shared"] = cm
        d["predicted_relationship"] = dna_predicted(cm)
        d["status"] = "INTERPRETED"
        touch(d)
        return ok_object(serialize(d))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


# ===========================================================================
# DOCUMENT REQUESTS
# ===========================================================================
@app.post("/genealogy/document-requests")
@require("Researcher")
def create_document_request():
    try:
        body = get_body()
        p = resolve_fk(body, "project_id", projects, "ERR_PROJECT_NOT_FOUND")
        repo = resolve_fk(body, "repository_id", repositories, "ERR_REPOSITORY_NOT_FOUND")
        doc_type = vstr(body, "document_type")
        source_lang = vstr(body, "source_language")
        needs_translation = vbool(body, "needs_translation", required=False, default=False)
        pages = vint(body, "pages", required=False, default=1, minimum=1)
        ent = new_entity({
            "project_id": p["id"],
            "repository_id": repo["id"],
            "document_type": doc_type,
            "source_language": source_lang,
            "pages": pages,
            "retrieval_status": "REQUESTED",
            "translation_status": "PENDING" if needs_translation else "NOT_NEEDED",
        })
        document_requests[ent["id"]] = ent
        return ok_object(serialize(ent), 201)
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/document-requests/<did>")
@require("Client", "Researcher", "ProjectManager")
def get_document_request(did):
    try:
        ent = must(document_requests, did, "ERR_DOCUMENT_REQUEST_NOT_FOUND")
        return ok_object(serialize(ent))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/document-requests")
@require("Client", "Researcher", "ProjectManager")
def list_document_requests():
    try:
        return do_list(document_requests, ["project_id", "repository_id"])
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/document-requests/<did>/update-retrieval")
@require("Researcher")
def update_retrieval(did):
    try:
        d = must(document_requests, did, "ERR_DOCUMENT_REQUEST_NOT_FOUND")
        body = get_body()
        outcome = venum(body, "outcome", {"RETRIEVED", "UNAVAILABLE"})
        if d["retrieval_status"] != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE", 409)
        d["retrieval_status"] = outcome
        touch(d)
        return ok_object(serialize(d))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/document-requests/<did>/update-translation")
@require("Researcher")
def update_translation(did):
    try:
        d = must(document_requests, did, "ERR_DOCUMENT_REQUEST_NOT_FOUND")
        body = get_body()
        venum(body, "outcome", {"TRANSLATED"})
        if d["translation_status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", 409)
        d["translation_status"] = "TRANSLATED"
        touch(d)
        return ok_object(serialize(d))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


# ===========================================================================
# HEIRLOOMS
# ===========================================================================
@app.post("/genealogy/heirlooms")
@require("Researcher", "ProjectManager")
def create_heirloom():
    try:
        body = get_body()
        p = resolve_fk(body, "project_id", projects, "ERR_PROJECT_NOT_FOUND")
        resolve_fk(body, "related_person_id", persons, "ERR_PERSON_NOT_FOUND", required=False)
        description = vstr(body, "description")
        category = venum(body, "category", HEIRLOOM_CATEGORIES)
        storage = vstr(body, "storage_location", required=False, default="")
        ent = new_entity({
            "project_id": p["id"],
            "related_person_id": body.get("related_person_id"),
            "description": description,
            "category": category,
            "storage_location": storage,
            "archive_status": "RECEIVED",
        })
        heirlooms[ent["id"]] = ent
        return ok_object(serialize(ent), 201)
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/heirlooms/<hid>")
@require("Client", "Researcher", "ProjectManager")
def get_heirloom(hid):
    try:
        ent = must(heirlooms, hid, "ERR_HEIRLOOM_NOT_FOUND")
        return ok_object(serialize(ent))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/heirlooms")
@require("Client", "Researcher", "ProjectManager")
def list_heirlooms():
    try:
        return do_list(heirlooms, ["project_id", "related_person_id"])
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/heirlooms/<hid>/advance")
@require("Researcher", "ProjectManager")
def advance_heirloom(hid):
    try:
        h = must(heirlooms, hid, "ERR_HEIRLOOM_NOT_FOUND")
        body = get_body()
        target = venum(body, "target_status", ARCHIVE_STATES)
        nxt = {"RECEIVED": "CATALOGUED", "CATALOGUED": "DIGITIZED", "DIGITIZED": "RETURNED"}
        if h["archive_status"] not in nxt or target != nxt[h["archive_status"]]:
            raise ApiError("ERR_INVALID_STATE", 409)
        h["archive_status"] = target
        touch(h)
        return ok_object(serialize(h))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


# ===========================================================================
# DELIVERABLES
# ===========================================================================
@app.post("/genealogy/deliverables")
@require("Researcher")
def create_deliverable():
    try:
        body = get_body()
        p = resolve_fk(body, "project_id", projects, "ERR_PROJECT_NOT_FOUND")
        resolve_fk(body, "milestone_id", milestones, "ERR_MILESTONE_NOT_FOUND", required=False)
        dtype = venum(body, "deliverable_type", DELIVERABLE_TYPES)
        page_count = vint(body, "page_count", required=False, default=1, minimum=1)
        ent = new_entity({
            "project_id": p["id"],
            "milestone_id": body.get("milestone_id"),
            "deliverable_type": dtype,
            "page_count": page_count,
            "status": "DRAFT",
        })
        deliverables[ent["id"]] = ent
        return ok_object(serialize(ent), 201)
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/deliverables/<did>")
@require("Client", "Researcher", "ProjectManager")
def get_deliverable(did):
    try:
        ent = must(deliverables, did, "ERR_DELIVERABLE_NOT_FOUND")
        return ok_object(serialize(ent))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/deliverables")
@require("Client", "Researcher", "ProjectManager")
def list_deliverables():
    try:
        return do_list(deliverables, ["project_id", "milestone_id"])
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/deliverables/<did>/submit")
@require("Researcher")
def submit_deliverable(did):
    try:
        d = must(deliverables, did, "ERR_DELIVERABLE_NOT_FOUND")
        if d["status"] not in ("DRAFT", "REVISION_REQUESTED"):
            raise ApiError("ERR_INVALID_STATE", 409)
        d["status"] = "SUBMITTED"
        touch(d)
        return ok_object(serialize(d))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


def _deliverable_owner_check(d):
    if g.role == "Client":
        proj = projects.get(d["project_id"])
        if proj is None or proj["client_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403)


@app.post("/genealogy/deliverables/<did>/accept")
@require("Client", "ProjectManager")
def accept_deliverable(did):
    try:
        d = must(deliverables, did, "ERR_DELIVERABLE_NOT_FOUND")
        _deliverable_owner_check(d)
        if d["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409)
        d["status"] = "ACCEPTED"
        touch(d)
        proj = projects.get(d["project_id"])
        if d.get("milestone_id"):
            m = milestones.get(d["milestone_id"])
            if m is not None and m["status"] == "PENDING":
                m["status"] = "READY"
                touch(m)
        if proj is not None:
            bump_project(proj)
        return ok_object(serialize(d))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/deliverables/<did>/request-revision")
@require("Client", "ProjectManager")
def request_revision(did):
    try:
        d = must(deliverables, did, "ERR_DELIVERABLE_NOT_FOUND")
        _deliverable_owner_check(d)
        get_body()  # optional notes ignored
        if d["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409)
        d["status"] = "REVISION_REQUESTED"
        touch(d)
        return ok_object(serialize(d))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


# ===========================================================================
# MILESTONES
# ===========================================================================
@app.post("/genealogy/milestones")
@require("ProjectManager")
def create_milestone():
    try:
        body = get_body()
        p = resolve_fk(body, "project_id", projects, "ERR_PROJECT_NOT_FOUND")
        resolve_fk(body, "deliverable_id", deliverables, "ERR_DELIVERABLE_NOT_FOUND", required=False)
        title = vstr(body, "title")
        amount = vint(body, "amount_cents", minimum=0)
        seq_no = vint(body, "sequence_no", minimum=1)
        ent = new_entity({
            "project_id": p["id"],
            "deliverable_id": body.get("deliverable_id"),
            "title": title,
            "amount_cents": amount,
            "sequence_no": seq_no,
            "invoiced_amount_cents": 0,
            "line_total_cents": 0,
            "status": "PENDING",
        })
        milestones[ent["id"]] = ent
        return ok_object(serialize(ent), 201)
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/milestones/<mid>")
@require("Client", "Researcher", "ProjectManager")
def get_milestone(mid):
    try:
        ent = must(milestones, mid, "ERR_MILESTONE_NOT_FOUND")
        return ok_object(serialize(ent))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/milestones")
@require("Client", "Researcher", "ProjectManager")
def list_milestones():
    try:
        return do_list(milestones, ["project_id", "deliverable_id"])
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/milestones/<mid>/invoice")
@require("ProjectManager")
def invoice_milestone(mid):
    try:
        m = must(milestones, mid, "ERR_MILESTONE_NOT_FOUND")
        if m["status"] != "READY":
            raise ApiError("ERR_INVALID_STATE", 409)
        proj = projects.get(m["project_id"])
        client = clients.get(proj["client_id"]) if proj else None
        base = m["amount_cents"]
        disc_pct = TIER_DISCOUNT.get(client["tier"] if client else "STANDARD", Decimal("0"))
        discounted = round_half_up_cents(Decimal(base) * (Decimal(1) - disc_pct))
        surcharge = RUSH_SURCHARGE_CENTS if (proj and proj["priority"] == "RUSH") else 0
        pre_cap = discounted + surcharge
        cap = round_half_up_cents(Decimal(base) * PRICE_CAP_MULTIPLIER)
        invoiced = min(pre_cap, cap)
        fee = round_half_up_cents(Decimal(invoiced) * AGENCY_FEE_PCT)
        m["invoiced_amount_cents"] = invoiced
        m["line_total_cents"] = invoiced + fee
        m["status"] = "INVOICED"
        touch(m)
        if proj is not None:
            proj["invoiced_total_cents"] += m["line_total_cents"]
            bump_project(proj)
        return ok_object(serialize(m))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/milestones/<mid>/record-payment")
@require("ProjectManager")
def record_payment(mid):
    try:
        m = must(milestones, mid, "ERR_MILESTONE_NOT_FOUND")
        if m["status"] != "INVOICED":
            raise ApiError("ERR_INVALID_STATE", 409)
        m["status"] = "PAID"
        touch(m)
        proj = projects.get(m["project_id"])
        if proj is not None:
            proj["paid_total_cents"] += m["line_total_cents"]
            bump_project(proj)
        return ok_object(serialize(m))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/milestones/<mid>/cancel")
@require("ProjectManager")
def cancel_milestone(mid):
    try:
        m = must(milestones, mid, "ERR_MILESTONE_NOT_FOUND")
        get_body()  # optional reason ignored
        if m["status"] not in ("READY", "INVOICED"):
            raise ApiError("ERR_INVALID_STATE", 409)
        proj = projects.get(m["project_id"])
        was_invoiced = m["status"] == "INVOICED"
        m["status"] = "CANCELLED"
        touch(m)
        if proj is not None:
            if was_invoiced:
                proj["credited_total_cents"] += m["line_total_cents"]
                bump_project(proj)
            else:
                recompute_project(proj)
        return ok_object(serialize(m))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


# ===========================================================================
# TIME ENTRIES
# ===========================================================================
@app.post("/genealogy/time-entries")
@require("Researcher")
def create_time_entry():
    try:
        body = get_body()
        p = resolve_fk(body, "project_id", projects, "ERR_PROJECT_NOT_FOUND")
        resolve_fk(body, "record_search_id", record_searches, "ERR_RECORD_SEARCH_NOT_FOUND",
                   required=False)
        hours = vnum(body, "hours", gt=0)
        activity = venum(body, "activity_type", ACTIVITY_TYPES)
        billable = vbool(body, "billable", required=False, default=True)
        if p["status"] != "ACTIVE":
            raise ApiError("ERR_PROJECT_NOT_ACTIVE", 409)
        if billable:
            recompute_project(p)
            new_total = Decimal(str(p["consumed_hours"])) + Decimal(str(hours))
            cap = Decimal(str(p["budget_hours"])) * MAX_OVERAGE_MULTIPLIER
            if new_total > cap:
                raise ApiError("ERR_HOURS_CAP_EXCEEDED", 409)
        ent = new_entity({
            "project_id": p["id"],
            "researcher_id": g.user_id,
            "record_search_id": body.get("record_search_id"),
            "hours": hours,
            "activity_type": activity,
            "billable": billable,
            "status": "ACTIVE",
        })
        time_entries[ent["id"]] = ent
        recompute_project(p)
        return ok_object(serialize(ent), 201)
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/time-entries/<tid>")
@require("Client", "Researcher", "ProjectManager")
def get_time_entry(tid):
    try:
        ent = must(time_entries, tid, "ERR_TIME_ENTRY_NOT_FOUND")
        return ok_object(serialize(ent))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/time-entries")
@require("Client", "Researcher", "ProjectManager")
def list_time_entries():
    try:
        return do_list(time_entries, ["project_id", "researcher_id", "record_search_id"])
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/time-entries/<tid>/void")
@require("Researcher", "ProjectManager")
def void_time_entry(tid):
    try:
        te = must(time_entries, tid, "ERR_TIME_ENTRY_NOT_FOUND")
        get_body()  # optional reason ignored
        if te["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409)
        te["status"] = "VOIDED"
        touch(te)
        proj = projects.get(te["project_id"])
        if proj is not None:
            recompute_project(proj)
        return ok_object(serialize(te))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


# ===========================================================================
# REPOSITORY APPOINTMENTS
# ===========================================================================
def parse_dt(value):
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", 400, "datetime must be a string")
    try:
        t = value
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        d = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "invalid datetime")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


@app.post("/genealogy/appointments")
@require("Researcher")
def create_appointment():
    try:
        body = get_body()
        repo = resolve_fk(body, "repository_id", repositories, "ERR_REPOSITORY_NOT_FOUND")
        p = resolve_fk(body, "project_id", projects, "ERR_PROJECT_NOT_FOUND")
        researcher = resolve_fk(body, "researcher_id", researchers, "ERR_RESEARCHER_NOT_FOUND")
        start_raw = vstr(body, "start_utc")
        end_raw = vstr(body, "end_utc")
        purpose = vstr(body, "purpose", required=False, default="")
        start_dt = parse_dt(start_raw)
        end_dt = parse_dt(end_raw)

        # 1) Researcher exclusive (buffered) interval.
        for ap in appointments.values():
            if ap["researcher_id"] == researcher["id"] and ap["status"] == "BOOKED":
                if (start_dt - RESEARCHER_BUFFER) < ap["_end_dt"] and \
                        ap["_start_dt"] < (end_dt + RESEARCHER_BUFFER):
                    raise ApiError("ERR_RESEARCHER_UNAVAILABLE", 409)

        # 2) Repository aggregate capacity over overlapping windows.
        overlapping = 0
        for ap in appointments.values():
            if ap["repository_id"] == repo["id"] and ap["status"] == "BOOKED":
                if start_dt < ap["_end_dt"] and ap["_start_dt"] < end_dt:
                    overlapping += 1
        if overlapping >= repo["concurrent_capacity"]:
            raise ApiError("ERR_REPOSITORY_AT_CAPACITY", 409)

        # 3) Interval well-formedness.
        if not (end_dt > start_dt):
            raise ApiError("ERR_INVALID_INTERVAL", 422)

        ent = new_entity({
            "repository_id": repo["id"],
            "project_id": p["id"],
            "researcher_id": researcher["id"],
            "start_utc": start_raw,
            "end_utc": end_raw,
            "purpose": purpose,
            "status": "BOOKED",
            "_start_dt": start_dt,
            "_end_dt": end_dt,
        })
        appointments[ent["id"]] = ent
        return ok_object(serialize(ent), 201)
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/appointments/<aid>")
@require("Client", "Researcher", "ProjectManager")
def get_appointment(aid):
    try:
        ent = must(appointments, aid, "ERR_APPOINTMENT_NOT_FOUND")
        return ok_object(serialize(ent))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.get("/genealogy/appointments")
@require("Client", "Researcher", "ProjectManager")
def list_appointments():
    try:
        return do_list(appointments, ["repository_id", "project_id", "researcher_id"])
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


@app.post("/genealogy/appointments/<aid>/cancel")
@require("Researcher", "ProjectManager")
def cancel_appointment(aid):
    try:
        ap = must(appointments, aid, "ERR_APPOINTMENT_NOT_FOUND")
        get_body()  # optional reason ignored
        if ap["status"] != "BOOKED":
            raise ApiError("ERR_INVALID_STATE", 409)
        ap["status"] = "CANCELLED"
        touch(ap)
        return ok_object(serialize(ap))
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


# ===========================================================================
# TEST-DRIVING CLOCK
# ===========================================================================
@app.post("/genealogy/_clock/set_current_utc")
@require("ProjectManager")
def set_clock():
    global LOGICAL_CLOCK
    try:
        body = get_body()
        to_iso = vstr(body, "to_iso8601")
        LOGICAL_CLOCK = parse_dt(to_iso)
        return ok_object({})
    except ApiError as e:
        return err_response(e.error_id, e.http_status, e.message)


# ===========================================================================
# Fallback error handlers
# ===========================================================================
@app.errorhandler(404)
def handle_404(_e):
    return err_response("ERR_VALIDATION", 400, "unknown route") if False else \
        _respond({"meta": _meta(), "response_type": "error",
                  "data": {"error_id": "ERR_NOT_FOUND", "message": "route not found"}}, 404)


@app.errorhandler(405)
def handle_405(_e):
    return _respond({"meta": _meta(), "response_type": "error",
                     "data": {"error_id": "ERR_METHOD_NOT_ALLOWED",
                              "message": "method not allowed"}}, 405)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)

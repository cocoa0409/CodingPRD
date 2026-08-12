"""Clock, contacts, processes (+ sub-collections), dependencies."""
from flask import Blueprint

from calc import blast_radius, gap_pressure, would_cycle
from core import (ALL_ROLES, DB, actor, apply_filters, as_bool, as_dt,
                  as_enum, as_str, body, bump, fail, new_id, next_seq,
                  not_found, ok, opt_str, paginate, req, sorted_by_created,
                  stamp_new, tick_dt, validation)
from serializers import (assessment_view, attestation_view, bia_view,
                         capability_view, contact_view, dependency_view,
                         plan_view, process_view)

bp = Blueprint("registry", __name__)

TIERS = ["TIER_1", "TIER_2", "TIER_3"]
DEP_TYPES = ["DATA", "STAFF", "FACILITY", "VENDOR", "SYSTEM"]
CRITICALITIES = ["HIGH", "MEDIUM", "LOW"]


def get_process_or_404(process_id):
    p = DB.processes.get(process_id)
    if p is None:
        not_found("ERR_PROCESS_NOT_FOUND", "Process")
    return p


def get_contact_or_404(contact_id):
    c = DB.contacts.get(contact_id)
    if c is None:
        not_found("ERR_CONTACT_NOT_FOUND", "Contact")
    return c


# --------------------------------------------------------------------------
# Program clock (PRD §2.4)
# --------------------------------------------------------------------------

@bp.post("/resilience/_clock/set_current_utc")
def set_clock():
    actor(["ResilienceAdmin"])
    payload = body()
    raw = req(payload, "to_iso8601")
    dt = as_dt(raw, "to_iso8601")
    DB.clock = dt
    DB.clock_raw = raw if isinstance(raw, str) else None
    # Time-derived fields (Gap.overdue, validation_freshness, readiness
    # recency) are computed on read against the logical clock — a clock set
    # is therefore a full recalculation event by construction.
    return ok({"current_utc": DB.clock_raw})


# --------------------------------------------------------------------------
# Contacts
# --------------------------------------------------------------------------

@bp.post("/resilience/contacts")
def create_contact():
    actor(["ResilienceAdmin"])
    payload = body()
    full_name = as_str(req(payload, "full_name"), "full_name")
    email = as_str(req(payload, "email"), "email")
    role_title = as_str(req(payload, "role_title"), "role_title")
    active_flag = True
    if "active_flag" in payload and payload["active_flag"] is not None:
        active_flag = as_bool(payload["active_flag"], "active_flag")
    for c in DB.contacts.values():
        if c["email"] == email:
            fail("ERR_DUPLICATE", 409, "A contact with this email already exists")
    c = {"full_name": full_name, "email": email, "role_title": role_title,
         "active_flag": active_flag}
    stamp_new(c)
    DB.contacts[c["id"]] = c
    return ok(contact_view(c), status=201)


@bp.get("/resilience/contacts")
def list_contacts():
    actor(ALL_ROLES)
    items = apply_filters(list(DB.contacts.values()), [("email", "email")])
    page, meta = paginate(sorted_by_created(items))
    return ok([contact_view(c) for c in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/contacts/<contactId>")
def get_contact(contactId):
    actor(ALL_ROLES)
    return ok(contact_view(get_contact_or_404(contactId)))


# --------------------------------------------------------------------------
# Processes
# --------------------------------------------------------------------------

@bp.post("/resilience/processes")
def create_process():
    actor(["ResilienceAdmin"])
    payload = body()
    name = as_str(req(payload, "name"), "name")
    business_unit = as_str(req(payload, "business_unit"), "business_unit")
    owner_contact_id = req(payload, "owner_contact_id")
    if owner_contact_id not in DB.contacts:
        not_found("ERR_CONTACT_NOT_FOUND", "Contact")
    tier = as_enum(req(payload, "criticality_tier"), "criticality_tier", TIERS)
    p = {"name": name, "business_unit": business_unit,
         "owner_contact_id": owner_contact_id, "criticality_tier": tier,
         "status": "DRAFT"}
    stamp_new(p)
    DB.processes[p["id"]] = p
    return ok(process_view(p), status=201)


@bp.get("/resilience/processes")
def list_processes():
    actor(ALL_ROLES)
    items = apply_filters(list(DB.processes.values()), [
        ("business_unit", "business_unit"),
        ("criticality_tier", "criticality_tier"),
        ("status", "status"),
        ("owner_contact_id", "owner_contact_id"),
    ])
    page, meta = paginate(sorted_by_created(items))
    return ok([process_view(p) for p in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/processes/<processId>")
def get_process(processId):
    actor(ALL_ROLES)
    return ok(process_view(get_process_or_404(processId)))


@bp.put("/resilience/processes/<processId>")
def update_process(processId):
    actor(["ResilienceAdmin"])
    p = get_process_or_404(processId)
    payload = body()
    if "owner_contact_id" in payload and payload["owner_contact_id"] is not None:
        if payload["owner_contact_id"] not in DB.contacts:
            not_found("ERR_CONTACT_NOT_FOUND", "Contact")
    if p["status"] == "RETIRED":
        fail("ERR_INVALID_STATE", 409, "A RETIRED process is locked")
    if "name" in payload and payload["name"] is not None:
        p["name"] = as_str(payload["name"], "name")
    if "business_unit" in payload and payload["business_unit"] is not None:
        p["business_unit"] = as_str(payload["business_unit"], "business_unit")
    if "owner_contact_id" in payload and payload["owner_contact_id"] is not None:
        p["owner_contact_id"] = payload["owner_contact_id"]
    if "criticality_tier" in payload and payload["criticality_tier"] is not None:
        p["criticality_tier"] = as_enum(payload["criticality_tier"],
                                        "criticality_tier", TIERS)
    bump(p)
    return ok(process_view(p))


def _process_transition(processId, from_states, to_state):
    actor(["ResilienceAdmin"])
    p = get_process_or_404(processId)
    if p["status"] not in from_states:
        fail("ERR_INVALID_STATE", 409,
             f"Process must be in {' or '.join(from_states)}")
    p["status"] = to_state
    bump(p)
    return p


@bp.post("/resilience/processes/<processId>/activate")
def activate_process(processId):
    return ok(process_view(_process_transition(processId, ["DRAFT"], "ACTIVE")))


@bp.post("/resilience/processes/<processId>/suspend")
def suspend_process(processId):
    return ok(process_view(_process_transition(processId, ["ACTIVE"], "SUSPENDED")))


@bp.post("/resilience/processes/<processId>/resume")
def resume_process(processId):
    return ok(process_view(_process_transition(processId, ["SUSPENDED"], "ACTIVE")))


@bp.post("/resilience/processes/<processId>/retire")
def retire_process(processId):
    actor(["ResilienceAdmin"])
    p = get_process_or_404(processId)
    if p["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", 409, "Process must be ACTIVE to retire")
    # Open-item guards (PRD §3.1)
    if any(pl["process_id"] == processId and pl["status"] == "APPROVED"
           for pl in DB.plans.values()):
        fail("ERR_PROCESS_HAS_OPEN_ITEMS", 409,
             "Process has an APPROVED plan")
    if any(b["process_id"] == processId and b["status"] == "SUBMITTED"
           for b in DB.bias.values()):
        fail("ERR_PROCESS_HAS_OPEN_ITEMS", 409,
             "Process has a SUBMITTED BIA")
    if any(e["process_id"] == processId
           and e["status"] in ("SCHEDULED", "IN_PROGRESS")
           for e in DB.exercises.values()):
        fail("ERR_PROCESS_HAS_OPEN_ITEMS", 409,
             "Process has a live exercise")
    if any(a["process_id"] == processId
           and a["status"] in ("ACTIVE", "ALL_NOTIFIED", "ACKNOWLEDGED")
           for a in DB.activations.values()):
        fail("ERR_PROCESS_HAS_OPEN_ITEMS", 409,
             "Process has a live activation")
    # Cascades: non-terminal plans -> RETIRED, DRAFT/REJECTED BIAs -> SUPERSEDED
    for pl in DB.plans.values():
        if pl["process_id"] == processId and pl["status"] in ("DRAFT", "IN_REVIEW"):
            pl["status"] = "RETIRED"
            bump(pl)
    for b in DB.bias.values():
        if b["process_id"] == processId and b["status"] in ("DRAFT", "REJECTED"):
            b["status"] = "SUPERSEDED"
            bump(b)
    p["status"] = "RETIRED"
    bump(p)
    return ok(process_view(p))


# ---- process sub-collections ------------------------------------------------

@bp.get("/resilience/processes/<processId>/bias")
def process_bias(processId):
    actor(ALL_ROLES)
    get_process_or_404(processId)
    items = [b for b in DB.bias.values() if b["process_id"] == processId]
    page, meta = paginate(sorted_by_created(items))
    return ok([bia_view(b) for b in page], response_type="array", pagination=meta)


@bp.get("/resilience/processes/<processId>/plans")
def process_plans(processId):
    actor(ALL_ROLES)
    get_process_or_404(processId)
    items = [p for p in DB.plans.values() if p["process_id"] == processId]
    page, meta = paginate(sorted_by_created(items))
    return ok([plan_view(p) for p in page], response_type="array", pagination=meta)


@bp.get("/resilience/processes/<processId>/recovery-capabilities")
def process_capabilities(processId):
    actor(ALL_ROLES)
    get_process_or_404(processId)
    items = [c for c in DB.capabilities.values() if c["process_id"] == processId]
    page, meta = paginate(sorted_by_created(items))
    return ok([capability_view(c) for c in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/processes/<processId>/attestations")
def process_attestations(processId):
    actor(ALL_ROLES)
    get_process_or_404(processId)
    items = [a for a in DB.attestations.values() if a["process_id"] == processId]
    page, meta = paginate(sorted_by_created(items))
    return ok([attestation_view(a) for a in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/processes/<processId>/blast-radius")
def process_blast_radius(processId):
    actor(ALL_ROLES)
    get_process_or_404(processId)
    ids = blast_radius(processId)
    return ok({"blast_radius": len(ids), "process_ids": ids})


@bp.get("/resilience/processes/<processId>/gap-pressure")
def process_gap_pressure(processId):
    actor(ALL_ROLES)
    get_process_or_404(processId)
    return ok(gap_pressure(processId))


# --------------------------------------------------------------------------
# Dependencies
# --------------------------------------------------------------------------

@bp.post("/resilience/dependencies")
def create_dependency():
    actor(["ResilienceAdmin"])
    payload = body()
    from_id = req(payload, "from_process_id")
    to_id = req(payload, "to_process_id")
    if from_id not in DB.processes:
        not_found("ERR_PROCESS_NOT_FOUND", "Process")
    if to_id not in DB.processes:
        not_found("ERR_PROCESS_NOT_FOUND", "Process")
    dep_type = as_enum(req(payload, "dependency_type"), "dependency_type",
                       DEP_TYPES)
    criticality = as_enum(req(payload, "criticality"), "criticality",
                          CRITICALITIES)
    notes = opt_str(payload, "notes")
    if from_id == to_id:
        fail("ERR_DEPENDENCY_SELF_LOOP", 422,
             "from_process_id must differ from to_process_id")
    if would_cycle(from_id, to_id):
        fail("ERR_DEPENDENCY_CYCLE", 422,
             "The edge would close a directed cycle")
    d = {"from_process_id": from_id, "to_process_id": to_id,
         "dependency_type": dep_type, "criticality": criticality,
         "notes": notes}
    d["id"] = new_id()
    d["created_at"] = tick_dt()
    d["_seq"] = next_seq()
    DB.dependencies[d["id"]] = d
    return ok(dependency_view(d), status=201)


@bp.get("/resilience/dependencies")
def list_dependencies():
    actor(ALL_ROLES)
    items = apply_filters(list(DB.dependencies.values()), [
        ("from_process_id", "from_process_id"),
        ("to_process_id", "to_process_id"),
        ("dependency_type", "dependency_type"),
    ])
    page, meta = paginate(sorted_by_created(items))
    return ok([dependency_view(d) for d in page], response_type="array",
              pagination=meta)


@bp.get("/resilience/dependencies/<dependencyId>")
def get_dependency(dependencyId):
    actor(ALL_ROLES)
    d = DB.dependencies.get(dependencyId)
    if d is None:
        not_found("ERR_DEPENDENCY_NOT_FOUND", "Dependency")
    return ok(dependency_view(d))


@bp.delete("/resilience/dependencies/<dependencyId>")
def delete_dependency(dependencyId):
    actor(["ResilienceAdmin"])
    d = DB.dependencies.get(dependencyId)
    if d is None:
        not_found("ERR_DEPENDENCY_NOT_FOUND", "Dependency")
    del DB.dependencies[dependencyId]
    return "", 204

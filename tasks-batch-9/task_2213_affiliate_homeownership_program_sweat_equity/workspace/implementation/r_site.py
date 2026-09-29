"""Build sites, lot readiness, the safety hold, and the cost ledger."""
from flask import Blueprint

import cascade
import derive
from common import (
    API, created, get_cost_entry, get_program, get_site, listing, match, okay,
)
from errors import fail
from payload import body, qbool, qenum, qid, vbool, venum, vint, vstring
from rbac import auth
from store import bump, db, stamp
from util import new_id

bp = Blueprint("sites", __name__)

READINESS_STATES = ("RAW_LAND", "TITLE_CLEAR", "ENV_CLEARED", "READY_TO_BUILD",
                    "UNDER_CONSTRUCTION", "SAFETY_HOLD", "COMPLETED")
SITE_READ_ROLES = ("ProgramAdmin", "FamilyServicesCoordinator", "MortgageOfficer",
                   "ConstructionManager")
COST_CATEGORIES = ("SITE_WORK", "MATERIALS", "LABOR", "PERMITS", "OTHER")


# --------------------------------------------------------------------------- #
# build sites
# --------------------------------------------------------------------------- #
@bp.post(API + "/build-sites")
def create_site():
    auth("ProgramAdmin")
    data = body()
    raw = data.get("program_id")
    program = get_program(raw) if isinstance(raw, str) and raw else None

    program_id = vstring(data, "program_id", 1, None, required=True)
    parcel = vstring(data, "parcel_number", 1, 40, required=True)
    street = vstring(data, "street_address", 1, 200, required=True)
    acquisition = vint(data, "acquisition_cost_cents", minimum=0, required=True)
    appraised = vint(data, "appraised_value_cents", minimum=1000000, required=True)
    if program is None:
        program = get_program(program_id)

    for existing in derive.sites_of_program(program):
        if existing["parcel_number"] == parcel:
            fail("ERR_VALIDATION", "parcel_number must be unique within the program.")

    row = {
        "program_id": program["id"],
        "assigned_household_id": None,
        "parcel_number": parcel,
        "street_address": street,
        "acquisition_cost_cents": acquisition,
        "appraised_value_cents": appraised,
        "title_cleared": False,
        "environmental_cleared": False,
        "utilities_cleared": False,
        "cash_cost_cents": acquisition,
        "total_development_cost_cents": acquisition,
        "readiness_status": "RAW_LAND",
        "safety_posture": "CLEAR",
        "pre_hold_readiness_status": None,
    }
    stamp(row)
    db.sites[row["id"]] = row
    return created(derive.public_site(row))


@bp.get(API + "/build-sites")
def list_sites():
    auth(*SITE_READ_ROLES)
    program_id = qid("program_id")
    household_id = qid("assigned_household_id")
    readiness = qenum("readiness_status", READINESS_STATES)
    posture = qenum("safety_posture", ("CLEAR", "HOLD"))
    rows = []
    for site in db.sites.values():
        derive.refresh_site(site)
        if not match(site, "program_id", program_id):
            continue
        if not match(site, "assigned_household_id", household_id):
            continue
        if not match(site, "readiness_status", readiness):
            continue
        if not match(site, "safety_posture", posture):
            continue
        rows.append(site)
    return listing(rows, derive.public_site)


@bp.get(API + "/build-sites/<sid>")
def read_site(sid):
    auth(*SITE_READ_ROLES)
    site = get_site(sid)
    return okay(derive.public_site(site))


@bp.post(API + "/build-sites/<sid>/readiness-advance")
def advance_readiness(sid):
    auth("ProgramAdmin", "ConstructionManager")
    site = get_site(sid)
    data = body()
    step = venum(data, "step",
                 ("TITLE", "ENVIRONMENTAL", "UTILITIES", "FINAL_INSPECTION"),
                 required=True)
    document = vstring(data, "document_reference", 1, None, default=None, nullable=True)

    origins = {
        "TITLE": ("RAW_LAND",),
        "ENVIRONMENTAL": ("TITLE_CLEAR",),
        "UTILITIES": ("ENV_CLEARED",),
        "FINAL_INSPECTION": ("UNDER_CONSTRUCTION",),
    }[step]
    cascade.state_gate(site, "readiness_status", origins, ("COMPLETED",))

    if not document:
        fail("ERR_DOCUMENTATION_INCOMPLETE")

    if step == "TITLE":
        if site.get("title_cleared"):
            fail("ERR_TRANSITION_NOT_ALLOWED", "Title is already cleared.")
        site["title_cleared"] = True
        site["readiness_status"] = "TITLE_CLEAR"
    elif step == "ENVIRONMENTAL":
        site["environmental_cleared"] = True
        site["readiness_status"] = "ENV_CLEARED"
    elif step == "UTILITIES":
        if not site.get("title_cleared") or not site.get("environmental_cleared"):
            fail("ERR_TRANSITION_NOT_ALLOWED",
                 "Title and environmental clearance must land first.")
        site["utilities_cleared"] = True
        site["readiness_status"] = "READY_TO_BUILD"
    else:
        for shift in derive.shifts_of_site(site):
            if shift["status"] in ("SCHEDULED", "OPEN", "LOCKED"):
                fail("ERR_TRANSITION_NOT_ALLOWED",
                     "A shift of this site is still open.")
        if site.get("assigned_household_id") is None:
            fail("ERR_TRANSITION_NOT_ALLOWED", "The site has no assigned household.")
        site["readiness_status"] = "COMPLETED"

    derive.refresh_site(site)
    bump(site)
    return okay(derive.public_site(site))


@bp.post(API + "/build-sites/<sid>/safety-posture")
def set_safety_posture(sid):
    auth("ConstructionManager")
    site = get_site(sid)
    data = body()
    posture = venum(data, "posture", ("HOLD", "CLEAR"), required=True)
    vstring(data, "incident_note", 1, None, default=None, nullable=True)

    if posture == "HOLD":
        cascade.state_gate(site, "readiness_status",
                           ("READY_TO_BUILD", "UNDER_CONSTRUCTION"), ("COMPLETED",))
        if site.get("safety_posture") != "CLEAR":
            fail("ERR_TRANSITION_NOT_ALLOWED", "The site is already on hold.")
        site["pre_hold_readiness_status"] = site["readiness_status"]
        site["readiness_status"] = "SAFETY_HOLD"
        site["safety_posture"] = "HOLD"
        derive.refresh_site(site)
        bump(site)
        cascade.safety_hold_cascade(site)
    else:
        cascade.state_gate(site, "readiness_status", ("SAFETY_HOLD",), ("COMPLETED",))
        restored = site.get("pre_hold_readiness_status") or "READY_TO_BUILD"
        site["readiness_status"] = restored
        site["pre_hold_readiness_status"] = None
        site["safety_posture"] = "CLEAR"
        derive.refresh_site(site)
        bump(site)
    return okay(derive.public_site(site))


# --------------------------------------------------------------------------- #
# cost entries
# --------------------------------------------------------------------------- #
def _touch_cost_bases(site, in_kind):
    derive.refresh_site(site)
    bump(site)
    program = derive.program_of_site(site)
    if program is not None and in_kind:
        derive.refresh_program(program)
        bump(program)


@bp.post(API + "/cost-entries")
def create_cost_entry():
    auth("ConstructionManager", "ProgramAdmin")
    data = body()
    raw = data.get("build_site_id")
    site = get_site(raw) if isinstance(raw, str) and raw else None

    site_id = vstring(data, "build_site_id", 1, None, required=True)
    category = venum(data, "category", COST_CATEGORIES, required=True)
    amount = vint(data, "amount_cents", minimum=0, default=0)
    is_in_kind = vbool(data, "is_in_kind", default=False)
    fmv = vint(data, "fair_market_value_cents", minimum=0, default=0)
    donor = vstring(data, "donor_name", 1, 120, default=None, nullable=True)
    award_code = vstring(data, "grant_award_code", 1, 40, default=None, nullable=True)
    if site is None:
        site = get_site(site_id)

    cascade.guard_not_frozen(derive.program_of_site(site))

    if is_in_kind:
        if amount != 0 or fmv <= 0 or not donor:
            fail("ERR_IN_KIND_AMOUNT_MISMATCH")
    else:
        if amount <= 0 or fmv != 0:
            fail("ERR_IN_KIND_AMOUNT_MISMATCH")

    row = {
        "id": new_id(),
        "created_at": db.now(),
        "build_site_id": site["id"],
        "category": category,
        "amount_cents": amount,
        "is_in_kind": bool(is_in_kind),
        "fair_market_value_cents": fmv,
        "donor_name": donor,
        "grant_award_code": award_code,
        "status": "RECORDED",
        "_seq": db.next_seq(),
    }
    db.cost_entries[row["id"]] = row
    _touch_cost_bases(site, bool(is_in_kind))
    return created(derive.public_cost_entry(row))


@bp.get(API + "/cost-entries")
def list_cost_entries():
    auth("ProgramAdmin", "ConstructionManager", "MortgageOfficer")
    site_id = qid("build_site_id")
    category = qenum("category", COST_CATEGORIES)
    in_kind = qbool("is_in_kind")
    status = qenum("status", ("RECORDED", "VOIDED"))
    rows = [r for r in db.cost_entries.values()
            if match(r, "build_site_id", site_id)
            and match(r, "category", category)
            and (in_kind is None or bool(r.get("is_in_kind")) == in_kind)
            and match(r, "status", status)]
    return listing(rows, derive.public_cost_entry)


@bp.get(API + "/cost-entries/<cid>")
def read_cost_entry(cid):
    auth("ProgramAdmin", "ConstructionManager", "MortgageOfficer")
    entry = get_cost_entry(cid)
    return okay(derive.public_cost_entry(entry))


@bp.post(API + "/cost-entries/<cid>/void")
def void_cost_entry(cid):
    auth("ConstructionManager", "ProgramAdmin")
    entry = get_cost_entry(cid)
    data = body()
    vstring(data, "void_reason", 1, None, default=None, nullable=True)

    site = db.sites.get(entry["build_site_id"])
    cascade.guard_not_frozen(derive.program_of_site(site) if site else None)
    cascade.state_gate(entry, "status", ("RECORDED",), ())

    entry["status"] = "VOIDED"
    if site is not None:
        _touch_cost_bases(site, bool(entry.get("is_in_kind")))
    return okay(derive.public_cost_entry(entry))

"""Sites, artworks (install/deaccession/conservation), loans, logical clock."""
from datetime import timedelta

from flask import Blueprint, request

import db
import serialize as S
from util import (
    ApiError, guard, body, ok, ok_list, new_record, touch,
    require_str, require_int, require_enum, parse_dt,
    paginate_params, sort_and_page,
)

bp = Blueprint("registry", __name__)

ALL_ROLES = {"ProgramAdmin", "Registrar", "Artist", "Panelist"}
LOAN_BUFFER = timedelta(days=30)


def get_artwork(aid):
    rec = db.artworks.get(aid)
    if rec is None:
        raise ApiError("ERR_ARTWORK_NOT_FOUND", "artwork not found")
    return rec


def get_site(sid):
    rec = db.sites.get(sid)
    if rec is None:
        raise ApiError("ERR_SITE_NOT_FOUND", "site not found")
    return rec


def get_loan(lid):
    rec = db.loans.get(lid)
    if rec is None:
        raise ApiError("ERR_LOAN_NOT_FOUND", "loan not found")
    return rec


# ---------------------------------------------------------------------------
# Site
# ---------------------------------------------------------------------------
@bp.post("/sites")
def create_site():
    guard({"Registrar"})
    data = body()
    name = require_str(data, "name")
    address = require_str(data, "address")
    capacity = 1
    if data.get("capacity") is not None:
        capacity = require_int(data, "capacity", minimum=1)
    rec = new_record({
        "name": name,
        "address": address,
        "capacity": capacity,
        "current_artwork_id": None,
        "status": "AVAILABLE",
    })
    db.sites[rec["id"]] = rec
    return ok(S.site(rec), 201)


@bp.get("/sites/<sid>")
def fetch_site(sid):
    guard(ALL_ROLES)
    return ok(S.site(get_site(sid)))


# ---------------------------------------------------------------------------
# Artwork
# ---------------------------------------------------------------------------
@bp.post("/artworks")
def create_artwork():
    guard({"Registrar"})
    data = body()
    title = require_str(data, "title")
    acquisition_type = require_str(data, "acquisition_type")
    if acquisition_type not in ("COMMISSION", "DONATION", "LOAN"):
        raise ApiError("ERR_VALIDATION", "invalid acquisition_type")
    if acquisition_type == "COMMISSION":
        raise ApiError("ERR_DONATION_TYPE_REQUIRED", "direct intake requires DONATION or LOAN")
    appraised = data.get("appraised_value_cents")
    if appraised is not None:
        appraised = require_int(data, "appraised_value_cents")
    site_id = data.get("site_id")
    if site_id is not None and not isinstance(site_id, str):
        raise ApiError("ERR_VALIDATION", "site_id must be a string")
    rec = new_record({
        "title": title,
        "acquisition_type": acquisition_type,
        "contract_id": None,
        "site_id": site_id,
        "appraised_value_cents": appraised,
        "install_date": None,
        "location_status": "FABRICATED",
        "condition_status": "GOOD",
        "deaccession_method": None,
        "deaccession_proceeds_cents": None,
    })
    db.artworks[rec["id"]] = rec
    return ok(S.artwork(rec), 201)


@bp.get("/artworks/<aid>")
def fetch_artwork(aid):
    guard(ALL_ROLES)
    return ok(S.artwork(get_artwork(aid)))


@bp.get("/artworks")
def list_artworks():
    guard(ALL_ROLES)
    contract_id = request.args.get("contract_id")
    site_id = request.args.get("site_id")
    acquisition_type = request.args.get("acquisition_type")
    location_status = request.args.get("location_status")
    recs = [
        a for a in db.artworks.values()
        if (contract_id is None or a["contract_id"] == contract_id)
        and (site_id is None or a["site_id"] == site_id)
        and (acquisition_type is None or a["acquisition_type"] == acquisition_type)
        and (location_status is None or a["location_status"] == location_status)
    ]
    limit, offset = paginate_params()
    page, total = sort_and_page(recs, limit, offset)
    return ok_list([S.artwork(a) for a in page], limit, offset, total)


@bp.post("/artworks/<aid>/install")
def install_artwork(aid):
    guard({"Registrar"})
    artwork = get_artwork(aid)
    data = body()
    site_id = require_str(data, "site_id")
    install_date = require_str(data, "install_date")
    new_install = parse_dt(install_date)
    site = get_site(site_id)
    if artwork["location_status"] != "FABRICATED":
        raise ApiError("ERR_INVALID_STATE", "artwork is not FABRICATED")
    # Site occupancy: half-open interval [install_date, +inf); collision if the new
    # install instant falls within an already-installed artwork's occupancy interval.
    for other in db.artworks.values():
        if other["site_id"] == site["id"] and other["location_status"] == "INSTALLED":
            if other["install_date"] is not None and new_install >= parse_dt(other["install_date"]):
                raise ApiError("ERR_SITE_INTERVAL_CONFLICT", "site is occupied over this interval")
    if site["status"] != "AVAILABLE":
        raise ApiError("ERR_SITE_INTERVAL_CONFLICT", "site is not available")
    artwork["location_status"] = "INSTALLED"
    artwork["site_id"] = site["id"]
    artwork["install_date"] = install_date
    touch(artwork)
    site["status"] = "OCCUPIED"
    site["current_artwork_id"] = artwork["id"]
    touch(site)
    return ok(S.artwork(artwork))


@bp.post("/artworks/<aid>/deaccession")
def deaccession_artwork(aid):
    guard({"ProgramAdmin", "Registrar"})
    artwork = get_artwork(aid)
    if artwork["location_status"] not in ("FABRICATED", "INSTALLED"):
        raise ApiError("ERR_INVALID_STATE", "artwork cannot be deaccessioned")
    for loan in db.loans.values():
        if loan["artwork_id"] == artwork["id"] and loan["status"] == "APPROVED":
            raise ApiError("ERR_DEACCESSION_BLOCKED_BY_LOAN", "an approved loan blocks deaccession")
    data = body()
    method = require_enum(data, "deaccession_method", {"SALE", "DONATION", "DESTRUCTION", "TRANSFER"})
    proceeds = data.get("deaccession_proceeds_cents")
    if proceeds is not None:
        proceeds = require_int(data, "deaccession_proceeds_cents")
    was_installed = artwork["location_status"] == "INSTALLED"
    site_id = artwork["site_id"]
    artwork["location_status"] = "DEACCESSIONED"
    artwork["deaccession_method"] = method
    artwork["deaccession_proceeds_cents"] = proceeds
    touch(artwork)
    if was_installed and site_id is not None:
        site = db.sites.get(site_id)
        if site is not None and site["current_artwork_id"] == artwork["id"]:
            site["status"] = "AVAILABLE"
            site["current_artwork_id"] = None
            touch(site)
    return ok(S.artwork(artwork))


@bp.post("/artworks/<aid>/conservation-records")
def add_conservation_record(aid):
    guard({"Registrar"})
    artwork = get_artwork(aid)
    if artwork["location_status"] == "DEACCESSIONED":
        raise ApiError("ERR_INVALID_STATE", "artwork is DEACCESSIONED")
    data = body()
    record_type = require_enum(data, "record_type", {"INSPECTION", "TREATMENT", "DAMAGE"})
    condition_after = require_enum(data, "condition_after", {"GOOD", "FAIR", "POOR", "NEEDS_TREATMENT"})
    notes = data.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise ApiError("ERR_VALIDATION", "notes must be a string")
    performed_at = data.get("performed_at")
    if performed_at is not None:
        parse_dt(performed_at)  # validate
    else:
        from util import now_iso
        performed_at = now_iso()
    rec = new_record({
        "artwork_id": artwork["id"],
        "record_type": record_type,
        "condition_after": condition_after,
        "notes": notes,
        "performed_at": performed_at,
    }, common=False)
    db.conservation_records[rec["id"]] = rec
    artwork["condition_status"] = condition_after
    touch(artwork)
    return ok(S.conservation_record(rec), 201)


@bp.get("/artworks/<aid>/conservation-records")
def list_conservation_records(aid):
    guard(ALL_ROLES)
    artwork = get_artwork(aid)
    recs = [r for r in db.conservation_records.values() if r["artwork_id"] == artwork["id"]]
    limit, offset = paginate_params()
    page, total = sort_and_page(recs, limit, offset)
    return ok_list([S.conservation_record(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Loan
# ---------------------------------------------------------------------------
@bp.post("/artworks/<aid>/loans")
def create_loan(aid):
    guard({"Registrar"})
    artwork = get_artwork(aid)
    data = body()
    borrower_name = require_str(data, "borrower_name")
    loan_start = require_str(data, "loan_start")
    loan_end = require_str(data, "loan_end")
    start_dt = parse_dt(loan_start)
    end_dt = parse_dt(loan_end)
    if not (end_dt > start_dt):
        raise ApiError("ERR_VALIDATION", "loan_end must be after loan_start")
    # Interval conflict vs non-returned loans (buffer 30 days, closed intervals)
    for other in db.loans.values():
        if other["artwork_id"] != artwork["id"] or other["status"] not in ("REQUESTED", "APPROVED"):
            continue
        o_start = parse_dt(other["loan_start"])
        o_end = parse_dt(other["loan_end"])
        separated = start_dt > o_end + LOAN_BUFFER or end_dt < o_start - LOAN_BUFFER
        if not separated:
            raise ApiError("ERR_LOAN_INTERVAL_CONFLICT", "loan interval conflicts with an existing loan")
    rec = new_record({
        "artwork_id": artwork["id"],
        "borrower_name": borrower_name,
        "loan_start": loan_start,
        "loan_end": loan_end,
        "status": "REQUESTED",
    })
    db.loans[rec["id"]] = rec
    return ok(S.loan(rec), 201)


@bp.get("/artworks/<aid>/loans")
def list_loans(aid):
    guard(ALL_ROLES)
    artwork = get_artwork(aid)
    recs = [l for l in db.loans.values() if l["artwork_id"] == artwork["id"]]
    limit, offset = paginate_params()
    page, total = sort_and_page(recs, limit, offset)
    return ok_list([S.loan(l) for l in page], limit, offset, total)


@bp.post("/loans/<lid>/approve")
def approve_loan(lid):
    guard({"Registrar"})
    loan = get_loan(lid)
    if loan["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "loan is not REQUESTED")
    artwork = db.artworks.get(loan["artwork_id"])
    if artwork is not None and artwork["location_status"] == "DEACCESSIONED":
        raise ApiError("ERR_INVALID_STATE", "artwork is DEACCESSIONED")
    loan["status"] = "APPROVED"
    touch(loan)
    return ok(S.loan(loan))


@bp.post("/loans/<lid>/return")
def return_loan(lid):
    guard({"Registrar"})
    loan = get_loan(lid)
    if loan["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "loan is not APPROVED")
    loan["status"] = "RETURNED"
    touch(loan)
    return ok(S.loan(loan))


# ---------------------------------------------------------------------------
# Logical clock (test-driving)
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    guard({"ProgramAdmin"})
    data = body()
    to_iso = require_str(data, "to_iso8601")
    db.set_clock(parse_dt(to_iso))
    return ok({})

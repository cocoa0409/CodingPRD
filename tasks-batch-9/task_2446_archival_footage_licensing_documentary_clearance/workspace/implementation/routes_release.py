"""Subject releases, life-rights grants and depiction agreements."""
from flask import Blueprint, request

from calc import RELEASE_REVISION_LIMIT
from core import (ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL, ROLE_PRODUCTION_ADMIN, body,
                  by_seq, created, db, fail, guard, invalid, iso_date, new_row, ok, ok_list,
                  opt_enum, opt_str, pagination, public, req_date, req_enum, req_str, touch)
from domain import (get_asset, get_production, get_release, has_depiction_conflict,
                    recompute_production, set_depiction_status)

bp = Blueprint("releases", __name__)

RELEASE_TYPES = ("SUBJECT_RELEASE", "LIFE_RIGHTS", "DEPICTION_AGREEMENT")
APPROVAL_RIGHTS = ("NONE", "ROUGH_CUT_APPROVAL", "FINAL_APPROVAL")
RELEASE_STATUSES = ("DRAFT", "SENT", "REVISION_REQUESTED", "SIGNED", "REFUSED",
                    "APPROVAL_GRANTED", "APPROVAL_WITHHELD")


@bp.post("/productions/<pid>/subject-releases")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR)
def create_release(pid):
    production = get_production(pid)
    data = body()

    # rung 6 — the optional body foreign key
    asset = None
    if "asset_id" in data and data["asset_id"] is not None:
        if not isinstance(data["asset_id"], str) or not data["asset_id"].strip():
            invalid("Field 'asset_id' must be a string.")
        asset = get_asset(data["asset_id"])

    # rung 7
    subject_key = req_str(data, "subject_person_key")
    release_type = req_enum(data, "release_type", RELEASE_TYPES)
    from_date = req_date(data, "depiction_from_date")
    to_date = req_date(data, "depiction_to_date")
    approval_rights = opt_enum(data, "approval_rights", APPROVAL_RIGHTS, "NONE")
    if to_date < from_date:
        invalid("depiction_to_date must not precede depiction_from_date.")

    # rung 11
    if production["status"] not in ("DEVELOPMENT", "CLEARANCE"):
        fail("ERR_PRODUCTION_NOT_IN_CLEARANCE",
             "A %s production accepts no new releases." % production["status"])

    # rung 17
    if asset is not None and asset["production_id"] != pid:
        fail("ERR_ASSET_PRODUCTION_MISMATCH",
             "The asset does not belong to the addressed production.")

    # rung 39
    if has_depiction_conflict(pid, subject_key, from_date, to_date):
        fail("ERR_DEPICTION_WINDOW_CONFLICT",
             "A live release for this subject already covers an overlapping window.")

    row = new_row()
    row.update({
        "production_id": pid,
        "asset_id": asset["id"] if asset is not None else None,
        "subject_person_key": subject_key,
        "release_type": release_type,
        "approval_rights": approval_rights,
        "depiction_from_date": iso_date(from_date),
        "depiction_to_date": iso_date(to_date),
        "revision_round_count": 0,
        "status": "DRAFT",
        "cut_reference": None,
    })
    db.subject_releases[row["id"]] = row

    changed = False
    if asset is not None:
        changed = set_depiction_status(asset, "PENDING")
    recompute_production(production)
    if changed:
        touch(production)
    return created(public(row))


@bp.get("/subject-releases/<rid>")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL)
def read_release(rid):
    return ok(public(get_release(rid)))


@bp.get("/subject-releases")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR, ROLE_LEGAL_COUNSEL)
def list_releases():
    limit, offset = pagination()
    rows = by_seq(list(db.subject_releases.values()))
    for key in ("production_id", "asset_id", "subject_person_key", "release_type", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    return ok_list([public(r) for r in rows], limit, offset)


@bp.post("/subject-releases/<rid>/state")
@guard(ROLE_PRODUCTION_ADMIN, ROLE_CLEARANCE_SUPERVISOR)
def release_state(rid):
    release = get_release(rid)
    data = body()
    to_status = req_enum(data, "to_status", RELEASE_STATUSES)
    cut_reference = opt_str(data, "cut_reference")

    production = get_production(release["production_id"])
    asset = db.assets.get(release["asset_id"]) if release["asset_id"] else None
    current = release["status"]
    allowed = {("DRAFT", "SENT"), ("SENT", "SIGNED"), ("SENT", "REVISION_REQUESTED"),
               ("REVISION_REQUESTED", "SENT"), ("SENT", "REFUSED"),
               ("SIGNED", "APPROVAL_GRANTED"), ("SIGNED", "APPROVAL_WITHHELD")}
    if (current, to_status) not in allowed:
        fail("ERR_INVALID_STATE_TRANSITION",
             "A release in %s cannot move to %s." % (current, to_status))

    # rung 30
    if to_status in ("APPROVAL_GRANTED", "APPROVAL_WITHHELD") \
            and release["approval_rights"] == "NONE":
        fail("ERR_NO_APPROVAL_RIGHTS",
             "A release granting no approval rights has no approval to give.")

    # rung 35
    if to_status == "REVISION_REQUESTED" \
            and release["revision_round_count"] >= RELEASE_REVISION_LIMIT:
        fail("ERR_RELEASE_REVISION_LIMIT",
             "At most %d revision rounds are permitted." % RELEASE_REVISION_LIMIT)

    release["status"] = to_status
    if to_status == "REVISION_REQUESTED":
        release["revision_round_count"] += 1
    if to_status in ("APPROVAL_GRANTED", "APPROVAL_WITHHELD"):
        release["cut_reference"] = cut_reference

    changed = False
    if asset is not None:
        if to_status == "SIGNED" and release["approval_rights"] == "NONE":
            changed = set_depiction_status(asset, "OBTAINED")
        elif to_status == "REFUSED":
            changed = set_depiction_status(asset, "BLOCKED")
        elif to_status == "APPROVAL_GRANTED":
            changed = set_depiction_status(asset, "OBTAINED")
        elif to_status == "APPROVAL_WITHHELD":
            changed = set_depiction_status(asset, "BLOCKED")

    touch(release)
    recompute_production(production)
    if changed:
        touch(production)
    return ok(public(release))

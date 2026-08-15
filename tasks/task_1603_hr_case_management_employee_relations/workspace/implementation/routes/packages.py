"""Litigation file packages: assembly, finalize, seal, release (PRD §3.8).

Package assembly actions are exempt from the §2.7 litigation-hold freeze.
"""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_STATE, ERR_STALE_VERSION
from middleware import authorize
from response import success_object
from services import calculations as calc
from services.core import (
    new_record, touch, require_path, list_response, serialize_package,
)
from util import CLOCK, fmt_dt
from validate import Payload

bp = Blueprint("packages", __name__)

READ_ROLES = {"LegalCounsel", "ERManager"}


@bp.post("/er/cases/<cid>/litigation-packages")
def create_package(cid):
    caller = authorize({"LegalCounsel"})
    case = require_path("cases", cid)

    # priority 6 — assembly may begin only on a CLOSED case under litigation
    # hold (cross-entity state dependency on the parent case)
    if case["status"] != "CLOSED":
        raise_error(ERR_INVALID_STATE,
                    "litigation packages may be assembled only for CLOSED "
                    "cases")
    if not case["litigation_hold"]:
        raise_error(ERR_INVALID_STATE,
                    "litigation packages require the case's litigation_hold "
                    "to be set")

    member_ids, _lines = calc.compute_manifest(cid)
    rec = new_record()
    rec.update({
        "case_id": cid,
        "assembled_by": caller.user_id,
        "status": "ASSEMBLING",
        "manifest_hash": None,
        "item_count": len(member_ids),
        "sealed_at": None,
        "package_version": 1,
        "_member_ids": member_ids,
    })
    db["litigation_packages"][rec["id"]] = rec
    return success_object(serialize_package(rec), status=201)


@bp.get("/er/cases/<cid>/litigation-packages")
def list_case_packages(cid):
    authorize(READ_ROLES)
    require_path("cases", cid)
    items = [p for p in db["litigation_packages"].values()
             if p["case_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response(items, serialize_package)


@bp.get("/er/litigation-packages/<pid>")
def get_package(pid):
    authorize(READ_ROLES)
    rec = require_path("litigation_packages", pid)
    return success_object(serialize_package(rec))


@bp.post("/er/litigation-packages/<pid>/finalize")
def finalize_package(pid):
    authorize({"LegalCounsel"})
    pkg = require_path("litigation_packages", pid)
    case = db["cases"][pkg["case_id"]]

    # priority 6
    if pkg["status"] != "ASSEMBLING":
        raise_error(ERR_INVALID_STATE,
                    f"cannot finalize a package in status {pkg['status']}")
    if case["status"] != "CLOSED" or not case["litigation_hold"]:
        raise_error(ERR_INVALID_STATE,
                    "finalization requires the parent case CLOSED under "
                    "litigation hold")

    member_ids, lines = calc.compute_manifest(pkg["case_id"])
    if len(member_ids) < 1:
        raise_error(ERR_INVALID_STATE,
                    "cannot finalize a package with an empty manifest")

    pkg["_member_ids"] = member_ids
    pkg["item_count"] = len(member_ids)
    pkg["manifest_hash"] = calc.manifest_hash(lines)
    pkg["status"] = "READY"
    touch(pkg)
    return success_object(serialize_package(pkg))


@bp.post("/er/litigation-packages/<pid>/seal")
def seal_package(pid):
    authorize({"LegalCounsel"})
    pkg = require_path("litigation_packages", pid)
    p = Payload(request.get_json(silent=True))
    expected_version = p.get_int("expected_case_version", required=True)
    case = db["cases"][pkg["case_id"]]

    # priority 6
    if pkg["status"] != "READY":
        raise_error(ERR_INVALID_STATE,
                    f"cannot seal a package in status {pkg['status']}")
    # priority 23 — OCC on the parent case: the seal pins the manifest to the
    # case-file state counsel actually reviewed
    if expected_version is not None and expected_version != case["version"]:
        raise_error(ERR_STALE_VERSION,
                    f"expected_case_version {expected_version} does not match "
                    f"current case version {case['version']}")
    # priority 24
    p.raise_if_errors()

    member_ids, lines = calc.compute_manifest(pkg["case_id"])
    pkg["_member_ids"] = member_ids
    pkg["item_count"] = len(member_ids)
    pkg["manifest_hash"] = calc.manifest_hash(lines)  # recomputed and frozen
    pkg["status"] = "SEALED"
    pkg["sealed_at"] = fmt_dt(CLOCK.now())
    touch(pkg)
    # the seal mutates the case's file state
    touch(case)
    return success_object(serialize_package(pkg))


@bp.post("/er/litigation-packages/<pid>/release")
def release_package(pid):
    authorize({"LegalCounsel"})
    pkg = require_path("litigation_packages", pid)
    p = Payload(request.get_json(silent=True))
    authority_ref = p.get_str("release_authority_reference", required=True)

    # priority 6
    if pkg["status"] != "SEALED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot release a package in status {pkg['status']}")
    # priority 24 — external authority reference of at least 8 characters
    if authority_ref is not None and len(authority_ref) < 8:
        p.errors.append(
            "release_authority_reference must be at least 8 characters")
    p.raise_if_errors()

    pkg["status"] = "RELEASED"
    touch(pkg)
    return success_object(serialize_package(pkg))

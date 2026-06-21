"""Post-summary correction / protest endpoints (PRD §3.10, §2.7)."""
from flask import Blueprint

from db import db
from errors import err
from helpers import (
    get_body, require_enum, require_int, stamp_create, bump_version,
    lookup, list_response,
)
from middleware import require_roles, check_importer_ownership
from response import object_response
from serializers import psc_view
from services import calc
from services.reconcile import (
    lines_for_entry, bond_add_liability, recompute_statement_totals,
)

bp = Blueprint("post_summary_corrections", __name__)


@bp.post("/post-summary-corrections")
@require_roles("LicensedBroker", "ImporterUser")
def create_psc():
    body = get_body()
    entry_id = body.get("entry_id")
    if not isinstance(entry_id, str) or entry_id == "":
        raise err("ERR_VALIDATION", "entry_id is required.")
    filing_kind = require_enum(body, "filing_kind", {"PSC", "PROTEST"})
    corrected_value_delta_cents = require_int(body, "corrected_value_delta_cents")
    expected_entry_version = require_int(body, "expected_entry_version")

    # existence (404).
    entry = lookup(db.entries, entry_id)

    # ownership (403) for ImporterUser.
    importer = db.importers.get(entry["importer_id"])
    if importer is not None:
        check_importer_ownership(importer)

    # state (priority 5): the referenced entry must be LIQUIDATED.
    if entry["status"] != "LIQUIDATED":
        raise err("ERR_INVALID_STATE", "Entry is not LIQUIDATED.")

    # OCC (priority 16): expected_entry_version must equal current version.
    if expected_entry_version != entry["version"]:
        raise err("ERR_STALE_ENTRY_VERSION", "expected_entry_version does not match the entry's version.")

    rec = {
        "entry_id": entry_id,
        "filing_kind": filing_kind,
        "corrected_value_delta_cents": corrected_value_delta_cents,
        "adjustment_cents": 0,
        "status": "SUBMITTED",
    }
    stamp_create(rec)
    db.post_summary_corrections[rec["id"]] = rec
    return object_response(psc_view(rec), status=201)


@bp.get("/post-summary-corrections/<id>")
@require_roles("AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer")
def get_psc(id):
    return object_response(psc_view(lookup(db.post_summary_corrections, id)))


@bp.get("/post-summary-corrections")
@require_roles("AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer")
def list_psc():
    return list_response(
        db.post_summary_corrections.values(), psc_view,
        filters=[("entry_id", "entry_id")],
    )


@bp.post("/post-summary-corrections/<id>/grant")
@require_roles("CBPOfficer")
def grant_psc(id):
    psc = lookup(db.post_summary_corrections, id)
    if psc["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Filing is not SUBMITTED.")
    entry = db.entries.get(psc["entry_id"])
    if entry is None:
        raise err("ERR_NOT_FOUND", "Entry not found.")
    if entry["status"] != "LIQUIDATED":
        raise err("ERR_INVALID_STATE", "Entry is not LIQUIDATED.")

    lines = lines_for_entry(entry["id"])
    adjustment = calc.compute_psc_adjustment(lines, psc["corrected_value_delta_cents"])
    psc["adjustment_cents"] = adjustment

    # entry.final_total += adjustment; total_duties_owed = new final.
    entry["final_total_cents"] = entry["final_total_cents"] + adjustment
    entry["total_duties_owed_cents"] = entry["final_total_cents"]

    # bond liability += adjustment (may flip ACTIVE <-> SATURATED).
    bond = db.bonds.get(entry["bond_id"])
    if bond is not None:
        bond_add_liability(bond, adjustment)

    # recompute statement total.
    statement = db.monthly_statements.get(entry["statement_id"]) if entry["statement_id"] else None
    if statement is not None:
        recompute_statement_totals(statement)

    psc["status"] = "GRANTED"
    bump_version(psc)
    return object_response(psc_view(psc))


@bp.post("/post-summary-corrections/<id>/deny")
@require_roles("CBPOfficer")
def deny_psc(id):
    psc = lookup(db.post_summary_corrections, id)
    if psc["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Filing is not SUBMITTED.")
    entry = db.entries.get(psc["entry_id"])
    if entry is None:
        raise err("ERR_NOT_FOUND", "Entry not found.")
    if entry["status"] != "LIQUIDATED":
        raise err("ERR_INVALID_STATE", "Entry is not LIQUIDATED.")

    psc["adjustment_cents"] = 0
    psc["status"] = "DENIED"
    bump_version(psc)
    return object_response(psc_view(psc))

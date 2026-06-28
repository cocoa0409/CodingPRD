"""Customs entry (7501) endpoints (PRD §3.3 - §3.5, §3.9)."""
from datetime import timedelta

from flask import Blueprint, g

from db import db
from errors import err
from helpers import (
    get_body, require_str, require_int, require_enum, optional_int,
    optional_enum, stamp_create, bump_version, lookup, lookup_optional,
    list_response, parse_iso8601, validate_hts, validate_country,
)
from middleware import require_roles, check_importer_ownership
from response import object_response
from serializers import entry_view, line_view
from services import calc
from services.reconcile import (
    lines_for_entry, bond_add_liability, schedule_entry_onto_statement,
    recompute_statement_totals,
)

bp = Blueprint("entries", __name__)

ENTRY_TYPES = {"CONSUMPTION_01", "WAREHOUSE_21", "FTZ_06"}


# ---------------------------------------------------------------------------
# Create / read entries
# ---------------------------------------------------------------------------
@bp.post("/entries")
@require_roles("LicensedBroker", "ImporterUser")
def create_entry():
    body = get_body()
    importer_id = body.get("importer_id")
    bond_id = body.get("bond_id")
    if not isinstance(importer_id, str) or importer_id == "":
        raise err("ERR_VALIDATION", "importer_id is required.")
    if not isinstance(bond_id, str) or bond_id == "":
        raise err("ERR_VALIDATION", "bond_id is required.")
    isf_filing_id = body.get("isf_filing_id")  # optional / nullable at draft
    entry_type = require_enum(body, "entry_type", ENTRY_TYPES)
    country_of_origin = require_str(body, "country_of_origin")
    entry_date = require_str(body, "entry_date")
    parse_iso8601(entry_date, "entry_date")  # validate datetime format

    # existence (404) left-to-right, then ownership (403).
    importer = lookup(db.importers, importer_id)
    lookup(db.bonds, bond_id)
    if isf_filing_id is not None:
        lookup(db.isf_filings, isf_filing_id)
    check_importer_ownership(importer)

    # format validation: country must be 2 uppercase letters.
    validate_country(country_of_origin)

    rec = {
        "importer_id": importer_id,
        "bond_id": bond_id,
        "isf_filing_id": isf_filing_id,
        "statement_id": None,
        "entry_type": entry_type,
        "country_of_origin": country_of_origin,
        "entry_date": entry_date,
        "provisional_total_cents": 0,
        "final_total_cents": None,
        "total_duties_owed_cents": 0,
        "filed_by_user_id": None,
        "reviewed_by_user_id": None,
        "status": "DRAFT",
    }
    stamp_create(rec)
    db.entries[rec["id"]] = rec
    return object_response(entry_view(rec), status=201)


@bp.get("/entries/<id>")
@require_roles("AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer")
def get_entry(id):
    return object_response(entry_view(lookup(db.entries, id)))


@bp.get("/entries")
@require_roles("AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer")
def list_entries():
    return list_response(
        db.entries.values(), entry_view,
        filters=[("importer_id", "importer_id"), ("bond_id", "bond_id"),
                 ("isf_filing_id", "isf_filing_id"), ("statement_id", "statement_id")],
    )


# ---------------------------------------------------------------------------
# Entry lines
# ---------------------------------------------------------------------------
@bp.post("/entries/<id>/lines")
@require_roles("LicensedBroker", "ImporterUser")
def add_line(id):
    entry = lookup(db.entries, id)
    # ownership scoped to the parent importer.
    importer = db.importers.get(entry["importer_id"])
    if importer is not None:
        check_importer_ownership(importer)
    # lines may only be added while the entry is DRAFT.
    if entry["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Lines may only be added to a DRAFT entry.")

    body = get_body()
    hts_code = require_str(body, "hts_code")
    customs_value_cents = require_int(body, "customs_value_cents")
    if customs_value_cents <= 0:
        raise err("ERR_VALIDATION", "customs_value_cents must be > 0.")
    assists_cents = optional_int(body, "assists_cents", 0)
    if assists_cents < 0:
        raise err("ERR_VALIDATION", "assists_cents must be >= 0.")
    quantity = require_int(body, "quantity")
    if quantity <= 0:
        raise err("ERR_VALIDATION", "quantity must be > 0.")
    preference_claim = optional_enum(body, "preference_claim", {"NONE", "USMCA"}, "NONE")
    pga_flag = optional_enum(body, "pga_flag", {"NONE", "FDA", "USDA"}, "NONE")

    # hts_code must be exactly 10 digits.
    validate_hts(hts_code)

    line = {
        "entry_id": entry["id"],
        "hts_code": hts_code,
        "customs_value_cents": customs_value_cents,
        "assists_cents": assists_cents,
        "quantity": quantity,
        "preference_claim": preference_claim,
        "pga_flag": pga_flag,
        "dutiable_value_cents": 0,
        "line_duty_cents": 0,
        "preference_verified": False,
    }
    # dutiable_value computed at line creation.
    line["dutiable_value_cents"] = calc.compute_line_dutiable_value(line)
    stamp_create(line)
    db.entry_lines[line["id"]] = line
    return object_response(line_view(line), status=201)


@bp.get("/entries/<id>/lines")
@require_roles("AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer")
def list_lines(id):
    # entry in path resolved before the line scope.
    lookup(db.entries, id)
    lines = [l for l in db.entry_lines.values() if l["entry_id"] == id]
    return list_response(lines, line_view)


# ---------------------------------------------------------------------------
# File the entry — provisional pricing + bond reconciliation (PRD §3.4)
# ---------------------------------------------------------------------------
@bp.post("/entries/<id>/file")
@require_roles("LicensedBroker")
def file_entry(id):
    entry = lookup(db.entries, id)

    # State first (priority 5).
    if entry["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Entry is not DRAFT.")

    lines = lines_for_entry(entry["id"])
    # >= 1 line.
    if len(lines) == 0:
        raise err("ERR_NO_LINES", "Entry must have at least one line to file.")

    bond = db.bonds.get(entry["bond_id"])
    if bond is None:
        raise err("ERR_NOT_FOUND", "Bond not found.")

    # priority 7: bond-importer mismatch (422) before fiscal checks.
    if bond["importer_id"] != entry["importer_id"]:
        raise err("ERR_BOND_IMPORTER_MISMATCH", "Bond does not belong to the entry's importer.")

    # ISF must be set and FILED (priority 9, 409).
    isf_id = entry["isf_filing_id"]
    if isf_id is None:
        raise err("ERR_ISF_NOT_FILED", "Entry has no ISF filing set.")
    isf = db.isf_filings.get(isf_id)
    if isf is None:
        raise err("ERR_NOT_FOUND", "ISF filing not found.")
    if isf["status"] != "FILED":
        raise err("ERR_ISF_NOT_FILED", "Referenced ISF is not in FILED status.")

    # For every PGA-flagged line a PGAReview must exist for (entry, that agency).
    flagged_agencies = {l["pga_flag"] for l in lines if l["pga_flag"] != "NONE"}
    existing_review_agencies = {
        r["agency"] for r in db.pga_reviews.values() if r["entry_id"] == entry["id"]
    }
    for agency in flagged_agencies:
        if agency not in existing_review_agencies:
            raise err("ERR_INVALID_STATE", "Missing PGA review for agency %s." % agency)

    # priority 11: entry_date must not precede vessel_eta - 24h (422).
    eta = parse_iso8601(isf["vessel_eta"], "vessel_eta")
    entry_dt = parse_iso8601(entry["entry_date"], "entry_date")
    manifest_cutoff = eta - timedelta(hours=calc.ISF_CUTOFF_HOURS)
    if entry_dt < manifest_cutoff:
        raise err("ERR_ENTRY_PRECEDES_MANIFEST", "entry_date precedes the manifest cutoff.")

    # Compute the provisional total (needed for the insufficiency test).
    for line in lines:
        line["dutiable_value_cents"] = calc.compute_line_dutiable_value(line)
        line["line_duty_cents"] = calc.compute_line_duty_provisional(line)
    provisional_total = calc.compute_entry_charges(lines, entry["entry_type"], "provisional")

    # PRD §2.8 pins: insufficiency BEFORE saturation.
    # priority 14: filing must not drive outstanding strictly above limit (422).
    projected = bond["outstanding_liability_cents"] + provisional_total
    if projected > bond["limit_cents"]:
        raise err("ERR_BOND_INSUFFICIENT", "Filing would exceed the bond limit.")

    # priority 15: a filing against an already-SATURATED bond (409).
    if bond["status"] == "SATURATED":
        raise err("ERR_BOND_SATURATED", "Bond is already SATURATED.")

    # Only an ACTIVE bond may secure a filing (PRD §3.1, §3.4).
    if bond["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Bond is not ACTIVE.")

    # Commit: persist line duties and entry totals.
    entry["provisional_total_cents"] = provisional_total
    entry["total_duties_owed_cents"] = provisional_total
    entry["filed_by_user_id"] = g.user_id
    entry["status"] = "FILED"
    bump_version(entry)

    # Cascade: bond liability += total; may auto-saturate.
    bond_add_liability(bond, provisional_total)

    return object_response(entry_view(entry))


# ---------------------------------------------------------------------------
# CBP review — RELEASE / HOLD (PRD §3.5)
# ---------------------------------------------------------------------------
@bp.post("/entries/<id>/review")
@require_roles("CBPOfficer")
def review_entry(id):
    entry = lookup(db.entries, id)
    body = get_body()
    action = require_enum(body, "action", {"RELEASE", "HOLD"})

    # State (priority 5): must be FILED or HOLD_EXAM.
    if entry["status"] not in ("FILED", "HOLD_EXAM"):
        raise err("ERR_INVALID_STATE", "Entry is not in a reviewable state.")

    # Segregation of duties (priority 6): officer != filer.
    if g.user_id == entry["filed_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Reviewer must not be the filer.")

    reviews = [r for r in db.pga_reviews.values() if r["entry_id"] == entry["id"]]

    if action == "RELEASE":
        return _release_entry(entry, reviews)
    return _hold_entry(entry, reviews)


def _release_entry(entry, reviews):
    # HOLD_EXAM release path requires status == HOLD_EXAM; FILED release path
    # requires status == FILED. Both already passed the {FILED, HOLD_EXAM} gate.
    # PGA: every review MAY_PROCEED; else ERR_PGA_NOT_CLEARED.
    if any(r["decision"] != "MAY_PROCEED" for r in reviews):
        raise err("ERR_PGA_NOT_CLEARED", "PGA reviews not all cleared.")

    isf = db.isf_filings.get(entry["isf_filing_id"]) if entry["isf_filing_id"] else None
    # On a direct FILED->RELEASED, the ISF must be in FILED status.
    if entry["status"] == "FILED":
        if isf is None or isf["status"] != "FILED":
            raise err("ERR_ISF_NOT_FILED", "Referenced ISF is not in FILED status.")

    was_hold_exam = entry["status"] == "HOLD_EXAM"

    entry["reviewed_by_user_id"] = g.user_id
    entry["status"] = "RELEASED"
    bump_version(entry)

    # Cascade: ISF FILED -> MATCHED.
    if isf is not None and isf["status"] == "FILED":
        isf["status"] = "MATCHED"

    # Cascade: free BOOKED exam slots when releasing out of HOLD_EXAM.
    if was_hold_exam:
        for slot in db.exam_slots.values():
            if slot["entry_id"] == entry["id"] and slot["status"] == "BOOKED":
                slot["status"] = "RELEASED_SLOT"

    # Cascade: schedule onto the open monthly statement.
    schedule_entry_onto_statement(entry)

    return object_response(entry_view(entry))


def _hold_entry(entry, reviews):
    # HOLD permitted only while FILED.
    if entry["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Hold is only permitted on a FILED entry.")
    # Condition: a PGA review in {HOLD, REFUSED} OR action explicitly HOLD.
    # Since the caller passed action=HOLD explicitly, the hold is permitted.
    entry["reviewed_by_user_id"] = g.user_id
    entry["status"] = "HOLD_EXAM"
    bump_version(entry)
    return object_response(entry_view(entry))


# ---------------------------------------------------------------------------
# Liquidate — final pricing + cross-aggregate reconciliation (PRD §3.9)
# ---------------------------------------------------------------------------
@bp.post("/entries/<id>/liquidate")
@require_roles("CBPOfficer")
def liquidate_entry(id):
    entry = lookup(db.entries, id)

    # State (priority 5): RELEASED.
    if entry["status"] != "RELEASED":
        raise err("ERR_INVALID_STATE", "Entry is not RELEASED.")
    # Segregation of duties (priority 6).
    if g.user_id == entry["filed_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Liquidator must not be the filer.")

    lines = lines_for_entry(entry["id"])

    # Recompute each line under the final rule; set preference_verified.
    for line in lines:
        duty, verified = calc.compute_line_duty_final(line, entry["country_of_origin"])
        line["line_duty_cents"] = duty
        line["preference_verified"] = verified

    final_total = calc.compute_entry_charges(lines, entry["entry_type"], "final")
    delta = final_total - entry["provisional_total_cents"]

    entry["final_total_cents"] = final_total
    entry["total_duties_owed_cents"] = final_total
    entry["status"] = "LIQUIDATED"
    bump_version(entry)

    # Cascade: bond liability += delta (may de-saturate).
    bond = db.bonds.get(entry["bond_id"])
    if bond is not None:
        bond_add_liability(bond, delta)

    # Cascade: recompute the statement total.
    statement = db.monthly_statements.get(entry["statement_id"]) if entry["statement_id"] else None
    if statement is not None:
        recompute_statement_totals(statement)

    return object_response(entry_view(entry))


# ---------------------------------------------------------------------------
# Cancel a DRAFT entry (PRD §3.4)
# ---------------------------------------------------------------------------
@bp.post("/entries/<id>/cancel")
@require_roles("LicensedBroker")
def cancel_entry(id):
    entry = lookup(db.entries, id)
    if entry["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Entry is not DRAFT.")
    entry["status"] = "CANCELLED"
    bump_version(entry)
    return object_response(entry_view(entry))

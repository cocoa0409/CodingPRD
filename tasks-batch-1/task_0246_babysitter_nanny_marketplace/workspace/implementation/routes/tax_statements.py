"""TaxStatement (W-2) endpoints (PRD §3.9).

A TaxStatement is an immutable frozen snapshot: only id + created_at (no
updated_at, no version — PRD §2.4).

At issuance it freezes:
  - cash_wages_cents: gross wages paid from this family to this caregiver in
    tax_year (sum of COMPLETED sessions' gross_pay_cents, minus reversed-payout
    gross for that group).
  - fica_withheld_cents: FICA employee-share withheld in tax_year for that
    pairing (sum of PAID payouts' fica_withheld for that group).
"""

from flask import Blueprint, request

import errors
from db import store
from errors import err
from middleware import authenticate, require_roles, get_json, parse_pagination, paginate
from response import ok
from services import validate as v
from services.common import base_record
from services.ledger import tax_year_of
from services.lookup import get_family, get_caregiver, get_tax_statement, sorted_by_created
from services.serialize import tax_statement_out

bp = Blueprint("tax_statements", __name__)


def _snapshot_cash_wages(family_id, caregiver_id, tax_year):
    """Gross wages paid family->caregiver in tax_year from COMPLETED sessions,
    decremented by the gross of any REVERSED payouts in that group."""
    total = 0
    for s in store.sessions.values():
        if s["status"] != "COMPLETED" or s["caregiver_id"] != caregiver_id:
            continue
        booking = store.bookings.get(s["booking_id"])
        if not booking or booking["family_id"] != family_id:
            continue
        if tax_year_of(s["window_start_iso"]) != tax_year:
            continue
        total += s["gross_pay_cents"]

    for p in store.payouts.values():
        if (p["status"] != "REVERSED" or p["caregiver_id"] != caregiver_id
                or p["family_id"] != family_id):
            continue
        for sid in p["session_ids"]:
            s = store.sessions.get(sid)
            if s and tax_year_of(s["window_start_iso"]) == tax_year:
                total += -s["gross_pay_cents"]
    return total


def _snapshot_fica(family_id, caregiver_id, tax_year):
    """FICA employee-share withheld in tax_year for this pairing from PAID
    payouts (only payouts whose included sessions fall in tax_year)."""
    total = 0
    for p in store.payouts.values():
        if (p["status"] != "PAID" or p["caregiver_id"] != caregiver_id
                or p["family_id"] != family_id):
            continue
        # Attribute the payout to the tax year of its swept sessions.
        years = set()
        for sid in p["session_ids"]:
            s = store.sessions.get(sid)
            if s:
                years.add(tax_year_of(s["window_start_iso"]))
        if tax_year in years:
            total += p["fica_withheld_cents"]
    return total


@bp.route("/marketplace/tax-statements", methods=["POST"])
def create_tax_statement():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin"})
    body = get_json()
    family_id = v.req_str(body, "family_id")
    caregiver_id = v.req_str(body, "caregiver_id")
    tax_year = v.req_int(body, "tax_year")

    get_family(family_id)
    get_caregiver(caregiver_id)

    cash_wages = _snapshot_cash_wages(family_id, caregiver_id, tax_year)
    fica = _snapshot_fica(family_id, caregiver_id, tax_year)

    rec = base_record(common_fields=False)
    rec.update({
        "family_id": family_id,
        "caregiver_id": caregiver_id,
        "tax_year": tax_year,
        "cash_wages_cents": cash_wages,
        "fica_withheld_cents": fica,
    })
    store.tax_statements[rec["id"]] = rec
    return ok(tax_statement_out(rec), status=201)


@bp.route("/marketplace/tax-statements/<tid>", methods=["GET"])
def get_one_tax_statement(tid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family", "Caregiver"})
    t = get_tax_statement(tid)
    if auth.is_family and auth.user_id != t["family_id"]:
        raise err(errors.ERR_FORBIDDEN, "Family may only read its own statements")
    if auth.is_caregiver and auth.user_id != t["caregiver_id"]:
        raise err(errors.ERR_FORBIDDEN, "Caregiver may only read its own statements")
    return ok(tax_statement_out(t), status=200)


@bp.route("/marketplace/tax-statements", methods=["GET"])
def list_tax_statements():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family", "Caregiver"})
    limit, offset = parse_pagination()
    family_id = request.args.get("family_id")
    caregiver_id = request.args.get("caregiver_id")
    tax_year = request.args.get("tax_year")

    items = list(store.tax_statements.values())
    if auth.is_family:
        items = [t for t in items if t["family_id"] == auth.user_id]
    if auth.is_caregiver:
        items = [t for t in items if t["caregiver_id"] == auth.user_id]
    if family_id is not None:
        items = [t for t in items if t["family_id"] == family_id]
    if caregiver_id is not None:
        items = [t for t in items if t["caregiver_id"] == caregiver_id]
    if tax_year is not None:
        try:
            ty = int(tax_year)
        except (ValueError, TypeError):
            raise err(errors.ERR_VALIDATION, "tax_year must be an integer")
        items = [t for t in items if t["tax_year"] == ty]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return ok([tax_statement_out(t) for t in page], status=200, pagination=meta)

"""Shared request helpers: body parsing, nested path resolution, filters."""

from flask import request

import db
import errors


def get_body() -> dict:
    """Return the JSON request body as a dict ({} when absent/invalid)."""
    try:
        data = request.get_json(silent=True)
    except Exception:
        data = None
    if isinstance(data, dict):
        return data
    return {}


def require_fields(body: dict, fields):
    """Presence check for required input fields.

    The error catalog has no generic 400 entry; a missing required field is
    surfaced as a 422 (ERR_REFERENTIAL_INTEGRITY) — the catalog's catch-all
    for malformed input payloads.
    """
    for f in fields:
        if body.get(f) is None:
            raise errors.ApiError(
                errors.ERR_REFERENTIAL_INTEGRITY,
                f"Missing required field: {f}",
                422,
            )


# ---------------------------------------------------------------------------
# Left-to-right path resolvers (PRD §2.6) — ERR_NOT_FOUND at the first
# identifier that does not resolve within its expected parent scope.
# ---------------------------------------------------------------------------

def resolve_department(dept_id):
    dept = db.legal_departments.get(dept_id)
    if dept is None:
        raise errors.not_found()
    return dept


def resolve_firm(dept_id, firm_id):
    dept = resolve_department(dept_id)
    firm = db.panel_firms.get(firm_id)
    if firm is None or firm.get("legal_department_id") != dept_id:
        raise errors.not_found()
    return dept, firm


def resolve_guideline_version(dept_id, gv_id):
    dept = resolve_department(dept_id)
    gv = db.guideline_versions.get(gv_id)
    if gv is None or gv.get("legal_department_id") != dept_id:
        raise errors.not_found()
    return dept, gv


def resolve_acknowledgment(dept_id, firm_id, ack_id):
    dept, firm = resolve_firm(dept_id, firm_id)
    ack = db.guideline_acknowledgments.get(ack_id)
    if ack is None or ack.get("panel_firm_id") != firm_id:
        raise errors.not_found()
    return dept, firm, ack


def resolve_matter(dept_id, matter_id):
    dept = resolve_department(dept_id)
    matter = db.matters.get(matter_id)
    if matter is None or matter.get("legal_department_id") != dept_id:
        raise errors.not_found()
    return dept, matter


def resolve_rate_card(dept_id, firm_id, card_id):
    dept, firm = resolve_firm(dept_id, firm_id)
    card = db.rate_cards.get(card_id)
    if card is None or card.get("panel_firm_id") != firm_id:
        raise errors.not_found()
    return dept, firm, card


def resolve_rate(dept_id, firm_id, card_id, rate_id):
    dept, firm, card = resolve_rate_card(dept_id, firm_id, card_id)
    rate = db.timekeeper_rates.get(rate_id)
    if rate is None or rate.get("rate_card_id") != card_id:
        raise errors.not_found()
    return dept, firm, card, rate


def resolve_timekeeper(dept_id, firm_id, tk_id):
    dept, firm = resolve_firm(dept_id, firm_id)
    tk = db.timekeepers.get(tk_id)
    if tk is None or tk.get("panel_firm_id") != firm_id:
        raise errors.not_found()
    return dept, firm, tk


def resolve_invoice(dept_id, matter_id, invoice_id):
    dept, matter = resolve_matter(dept_id, matter_id)
    inv = db.invoices.get(invoice_id)
    if inv is None or inv.get("matter_id") != matter_id:
        raise errors.not_found()
    return dept, matter, inv


def resolve_line_item(dept_id, matter_id, invoice_id, line_id):
    dept, matter, inv = resolve_invoice(dept_id, matter_id, invoice_id)
    line = db.invoice_line_items.get(line_id)
    if line is None or line.get("invoice_id") != invoice_id:
        raise errors.not_found()
    return dept, matter, inv, line


def resolve_appeal(dept_id, matter_id, invoice_id, line_id, appeal_id):
    dept, matter, inv, line = resolve_line_item(dept_id, matter_id, invoice_id, line_id)
    appeal = db.appeals.get(appeal_id)
    if appeal is None or appeal.get("invoice_line_item_id") != line_id:
        raise errors.not_found()
    return dept, matter, inv, line, appeal


def resolve_accrual(dept_id, matter_id, accrual_id):
    dept, matter = resolve_matter(dept_id, matter_id)
    acc = db.accruals.get(accrual_id)
    if acc is None or acc.get("matter_id") != matter_id:
        raise errors.not_found()
    return dept, matter, acc


def resolve_scorecard(dept_id, firm_id, snapshot_id):
    dept, firm = resolve_firm(dept_id, firm_id)
    snap = db.scorecard_snapshots.get(snapshot_id)
    if snap is None or snap.get("panel_firm_id") != firm_id:
        raise errors.not_found()
    return dept, firm, snap


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def str_or_none(v):
    if v is None:
        return None
    return str(v)


def apply_filters(records, args, filterable):
    """Apply equality filters from query args for the given field names."""
    out = []
    wanted = {}
    for f in filterable:
        v = args.get(f)
        if v is not None:
            wanted[f] = v
    for rec in records:
        ok = True
        for f, v in wanted.items():
            rv = rec.get(f)
            if rv is None or str(rv) != v:
                ok = False
                break
        if ok:
            out.append(rec)
    return out

"""Tax forms: list/get, finalize, correct (PRD §3.10; OCC §2.8)."""

from flask import Blueprint, g, request

import errors
from db import store, touch
from middleware import ALL_ROLES, body, opt_int, opt_str, paginate, require_roles
from response import ok, ok_list
from services import serialize_taxform, supersede_form

bp = Blueprint("taxforms", __name__)

DISTRIBUTION_CODES = {"CODE_1", "CODE_7", "CODE_G"}


def _get_form_or_404(form_id, ownership_mask=True):
    f = store.taxforms.get(form_id)
    if f is None:
        raise errors.err_tax_form_not_found()
    if ownership_mask and g.role == "Participant" and f["participant_id"] != g.user_id:
        # Ownership scoping masked as not-found (PRD §2.1).
        raise errors.err_account_not_found()
    return f


@bp.get("/v1/tax-forms")
@require_roles(*ALL_ROLES)
def list_tax_forms():
    rows = list(store.taxforms.values())
    if g.role == "Participant":
        rows = [f for f in rows if f["participant_id"] == g.user_id]
    for param in ("participant_id", "rollover_case_id", "loan_id", "supersedes_id", "form_type", "status"):
        v = request.args.get(param)
        if v is not None:
            rows = [f for f in rows if f.get(param) == v]
    tax_year = request.args.get("tax_year")
    if tax_year is not None:
        try:
            ty = int(tax_year)
        except ValueError:
            raise errors.err_validation("tax_year must be an integer")
        rows = [f for f in rows if f.get("tax_year") == ty]
    rows.sort(key=lambda f: f["_seq"])
    page, total, limit, offset = paginate(rows)
    return ok_list([serialize_taxform(f) for f in page], total, limit, offset)


@bp.get("/v1/tax-forms/<form_id>")
@require_roles(*ALL_ROLES)
def get_tax_form(form_id):
    return ok(serialize_taxform(_get_form_or_404(form_id)))


@bp.post("/v1/tax-forms/<form_id>/finalize")
@require_roles("TaxReportingOfficer")
def finalize_tax_form(form_id):
    form = _get_form_or_404(form_id, ownership_mask=False)
    if form["status"] != "DRAFT":
        raise errors.err_tax_form_invalid_state("Only a DRAFT form may be finalized")
    form["status"] = "ISSUED"  # amounts locked; draft recomputes stop applying
    touch(form)
    return ok(serialize_taxform(form))


@bp.post("/v1/tax-forms/<form_id>/correct")
@require_roles("TaxReportingOfficer")
def correct_tax_form(form_id):
    form = _get_form_or_404(form_id, ownership_mask=False)
    data = body()
    expected = data.get("expected_tax_form_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.err_validation("expected_tax_form_version is required")
    if form["status"] != "ISSUED":
        raise errors.err_tax_form_invalid_state("Only an ISSUED form may be corrected")
    if expected != form["version"]:
        raise errors.err_stale_version()
    overrides = {}
    taxable = opt_int(data, "taxable_amount_cents")
    if taxable is not None:
        if taxable < 0:
            raise errors.err_validation("taxable_amount_cents must be >= 0")
        overrides["taxable_amount_cents"] = taxable
    rollover_contrib = opt_int(data, "rollover_contribution_cents")
    if rollover_contrib is not None:
        if rollover_contrib < 0:
            raise errors.err_validation("rollover_contribution_cents must be >= 0")
        overrides["rollover_contribution_cents"] = rollover_contrib
    code = opt_str(data, "distribution_code")
    if code is not None:
        if code not in DISTRIBUTION_CODES:
            raise errors.err_validation("distribution_code must be one of CODE_1, CODE_7, CODE_G")
        overrides["distribution_code"] = code
    new_form = supersede_form(form, overrides)
    return ok(serialize_taxform(new_form), status=201)

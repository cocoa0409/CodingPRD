"""Annual 1099 roll-up."""
from flask import Blueprint

from core import (
    FORM_1099_THRESHOLD_CENTS,
    authenticate,
    db,
    fail,
    filter_eq,
    get_body,
    new_record,
    ok,
    ok_list,
    ordered,
    pagination,
    paginate,
    parse_iso,
    public,
    req_int,
    req_str,
)
from services import lookup

bp = Blueprint("tax_forms", __name__)


@bp.post("/api/tax-forms")
def create_form():
    authenticate({"PlatformAdmin"})
    body = get_body()
    developer_id = req_str(body, "developer_id")
    tax_year = req_int(body, "tax_year")
    dev = lookup("developers", developer_id)
    for existing in ordered(db.tax_forms):
        if existing["developer_id"] == dev["id"] and existing["tax_year"] == tax_year:
            fail("ERR_TAX_FORM_EXISTS", "A form already exists for this developer and year.")

    reportable = 0
    withheld = 0
    for line in ordered(db.payout_lines):
        if line["developer_id"] != dev["id"] or line["status"] != "PAID":
            continue
        batch = db.payout_batches.get(line["payout_batch_id"])
        if batch is None:
            continue
        start = parse_iso(batch["period_start"])
        if start is None or start.year != tax_year:
            continue
        reportable += line["payout_amount_cents"] + line["withholding_cents"]
        withheld += line["withholding_cents"]

    rec = new_record(
        developer_id=dev["id"],
        tax_year=tax_year,
        reportable_cents=reportable,
        withheld_cents=withheld,
        threshold_cents=FORM_1099_THRESHOLD_CENTS,
        status="ISSUABLE" if reportable >= FORM_1099_THRESHOLD_CENTS else "NOT_REQUIRED",
    )
    db.tax_forms[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/api/tax-forms")
def list_forms():
    authenticate({"PlatformAdmin", "FinanceOps", "Developer"})
    limit, offset = pagination()
    rows = ordered(db.tax_forms)
    for field in ("developer_id", "tax_year", "status"):
        rows = filter_eq(rows, field)
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/api/tax-forms/<tax_form_id>")
def read_form(tax_form_id):
    authenticate({"PlatformAdmin", "FinanceOps", "Developer"})
    rec = lookup("tax_forms", tax_form_id)
    return ok(public(rec))

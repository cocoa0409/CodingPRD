"""Approved-payables ingestion (PRD 3.3)."""

from flask import Blueprint

from db import base_row, db, parse_dt, public, put_dt, touch
from errors import ApiError
from middleware import BUYER_ADMIN, authenticate, get_program, scope_program
from response import ok
from services import calc
from services import guards as g
from services import recompute as rc
from validation import bad, body, req_int, req_list, req_str

bp = Blueprint("files", __name__)

ROW_REASONS = (
    "SUPPLIER_UNKNOWN",
    "DUPLICATE_INVOICE_NUMBER",
    "NON_POSITIVE_AMOUNT",
    "DUE_DATE_NOT_AFTER_APPROVAL",
    "EMPTY_LINES",
)


def _parse_row(raw, index):
    if not isinstance(raw, dict):
        bad(detail="rows[%d] must be an object." % index)
    invoice_number = req_str(raw, "invoice_number", 1, 40)
    approval_raw = req_str(raw, "approval_date", 1)
    approval_dt = parse_dt(approval_raw)
    if approval_dt is None:
        bad(detail="rows[%d].approval_date is not a valid instant." % index)
    net_due_raw = req_str(raw, "net_due_date", 1)
    net_due_dt = parse_dt(net_due_raw)
    if net_due_dt is None:
        bad(detail="rows[%d].net_due_date is not a valid instant." % index)
    supplier_id = req_str(raw, "supplier_id", 1)
    suppression_flag = raw.get("suppression_flag", False)
    if suppression_flag is None:
        suppression_flag = False
    if not isinstance(suppression_flag, bool):
        bad(detail="rows[%d].suppression_flag must be a boolean." % index)
    lines_raw = req_list(raw, "lines", 0)
    lines = []
    seen = set()
    for pos, line in enumerate(lines_raw):
        if not isinstance(line, dict):
            bad(detail="rows[%d].lines[%d] must be an object." % (index, pos))
        line_no = req_int(line, "line_no", 1)
        amount = req_int(line, "line_amount_cents")
        tax_rate = req_int(line, "tax_rate_bps", 0, 3000)
        if line_no in seen:
            bad(detail="rows[%d].lines carries a duplicate line_no." % index)
        seen.add(line_no)
        lines.append((line_no, amount, tax_rate))
    if lines and sorted(seen) != list(range(1, len(lines) + 1)):
        bad(detail="rows[%d].lines must be contiguous from 1 upward." % index)
    lines.sort(key=lambda item: item[0])
    return {
        "invoice_number": invoice_number,
        "approval_raw": approval_raw,
        "approval_dt": approval_dt,
        "net_due_raw": net_due_raw,
        "net_due_dt": net_due_dt,
        "supplier_id": supplier_id,
        "suppression_flag": suppression_flag,
        "lines": lines,
    }


def _row_reason(row, program_id, claimed):
    if row["supplier_id"] not in db.suppliers:
        return "SUPPLIER_UNKNOWN"
    key = (program_id, row["supplier_id"], row["invoice_number"])
    if key in claimed:
        return "DUPLICATE_INVOICE_NUMBER"
    for _, amount, _tax in row["lines"]:
        if amount <= 0:
            return "NON_POSITIVE_AMOUNT"
    if not row["net_due_dt"] > row["approval_dt"]:
        return "DUE_DATE_NOT_AFTER_APPROVAL"
    if not row["lines"]:
        return "EMPTY_LINES"
    return None


@bp.post("/payable-files")
def ingest_payable_file():
    ctx = authenticate((BUYER_ADMIN,))
    b = body()
    program_id = req_str(b, "program_id", 1)
    filename = req_str(b, "filename", 1, 200)
    declared_row_count = req_int(b, "declared_row_count", 1)
    declared_total_cents = req_int(b, "declared_total_cents", 1)
    rows_raw = req_list(b, "rows", 0)
    parsed = [_parse_row(raw, index) for index, raw in enumerate(rows_raw)]

    program = get_program(program_id)
    scope_program(ctx, program)
    g.require_program_open(program)

    claimed = set()
    for invoice in db.invoices.values():
        claimed.add((invoice["program_id"], invoice["supplier_id"], invoice["invoice_number"]))

    accepted = []
    rejection_reasons = []
    computed_total = 0
    suppressed = 0
    for index, row in enumerate(parsed):
        reason = _row_reason(row, program["id"], claimed)
        if reason is not None:
            rejection_reasons.append({"row_index": index, "reason": reason})
            continue
        face, priced = calc.price_lines(row["lines"])
        row["face"] = face
        row["priced"] = priced
        computed_total += face
        if row["suppression_flag"]:
            suppressed += 1
        claimed.add((program["id"], row["supplier_id"], row["invoice_number"]))
        accepted.append(row)

    rejection_reasons.sort(key=lambda item: item["row_index"])

    if declared_row_count != len(accepted) or declared_total_cents != computed_total:
        raise ApiError("ERR_FILE_TOTALS_MISMATCH")

    if not rejection_reasons:
        ingest_status = "ACCEPTED"
    elif not accepted:
        ingest_status = "REJECTED"
    else:
        ingest_status = "PARTIALLY_ACCEPTED"

    file_row = base_row(common=False)
    file_row.update(
        {
            "program_id": program["id"],
            "filename": filename,
            "declared_row_count": declared_row_count,
            "declared_total_cents": declared_total_cents,
            "computed_total_cents": computed_total,
            "accepted_row_count": len(accepted),
            "rejected_row_count": len(rejection_reasons),
            "rejection_reasons": rejection_reasons,
            "suppressed_row_count": suppressed,
            "ingest_status": ingest_status,
        }
    )
    db.files[file_row["id"]] = file_row

    for row in accepted:
        invoice = base_row()
        invoice.update(
            {
                "file_id": file_row["id"],
                "program_id": program["id"],
                "supplier_id": row["supplier_id"],
                "invoice_number": row["invoice_number"],
                "face_amount_cents": row["face"],
                "face_covered_cents": 0,
                "remaining_face_cents": row["face"],
                "status": "SUPPRESSED" if row["suppression_flag"] else "ELIGIBLE",
                "dispute_suppressed": bool(row["suppression_flag"]),
                "accepted_apr_bps": 0,
                "provisional_discount_cents": 0,
                "final_discount_cents": 0,
                "discount_true_up_cents": 0,
            }
        )
        put_dt(invoice, "approval_date", row["approval_dt"], row["approval_raw"])
        put_dt(invoice, "net_due_date", row["net_due_dt"], row["net_due_raw"])
        db.invoices[invoice["id"]] = invoice
        for line in row["priced"]:
            line_row = base_row(common=False)
            line_row.update(line)
            line_row["invoice_id"] = invoice["id"]
            db.invoice_lines[line_row["id"]] = line_row
        if row["suppression_flag"]:
            dispute = base_row()
            dispute.update(
                {
                    "invoice_id": invoice["id"],
                    "reason_code": "BUYER_FILE_SUPPRESSION",
                    "disputed_amount_cents": row["face"],
                    "status": "OPEN",
                    "resolution_note": None,
                }
            )
            db.disputes[dispute["id"]] = dispute

    if accepted:
        rc.recompute_program_adoption(program, force=True)
    return ok(public(file_row), 201)

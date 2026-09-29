"""Reference resolution (PRD section 2.8) and list-response helpers."""

from envelope import ok_list
from errors import fail
from store import db, sort_rows
from validation import paginate, pagination


def _resolve(table, row_id, error_id):
    if not isinstance(row_id, str):
        fail(error_id, "Referenced resource does not exist.")
    row = table.get(row_id)
    if row is None:
        fail(error_id, "Referenced resource does not exist.")
    return row


def program_or_404(row_id):
    return _resolve(db.programs, row_id, "ERR_PROGRAM_NOT_FOUND")


def venue_or_404(row_id):
    return _resolve(db.venues, row_id, "ERR_VENUE_NOT_FOUND")


def supplier_or_404(row_id):
    return _resolve(db.suppliers, row_id, "ERR_SUPPLIER_NOT_FOUND")


def contract_or_404(row_id):
    return _resolve(db.contracts, row_id, "ERR_CONTRACT_NOT_FOUND")


def element_or_404(row_id):
    return _resolve(db.elements, row_id, "ERR_ELEMENT_NOT_FOUND")


def permit_or_404(row_id):
    return _resolve(db.permits, row_id, "ERR_PERMIT_NOT_FOUND")


def segment_or_404(row_id):
    return _resolve(db.segments, row_id, "ERR_SEGMENT_NOT_FOUND")


def manifest_entry_or_404(row_id):
    return _resolve(db.manifest_entries, row_id, "ERR_MANIFEST_ENTRY_NOT_FOUND")


def staff_member_or_404(row_id):
    return _resolve(db.staff_members, row_id, "ERR_STAFF_MEMBER_NOT_FOUND")


def staff_assignment_or_404(row_id):
    return _resolve(db.staff_assignments, row_id, "ERR_STAFF_ASSIGNMENT_NOT_FOUND")


def recon_line_or_404(row_id):
    return _resolve(db.recon_lines, row_id, "ERR_RECONCILIATION_LINE_NOT_FOUND")


def settlement_or_404(row_id):
    return _resolve(db.settlements, row_id, "ERR_SETTLEMENT_PAYMENT_NOT_FOUND")


# --------------------------------------------------------------------------

def respond_list(rows, serializer):
    limit, offset = pagination()
    ordered = sort_rows(rows)
    total_count = len(ordered)
    page = paginate(ordered, limit, offset)
    return ok_list([serializer(row) for row in page], limit, offset, total_count)


def apply_filters(rows, spec):
    """spec: list of (query_param_name, row_field, allowed_values_or_None)."""
    from validation import query_filter

    for name, field, allowed in spec:
        value = query_filter(name, allowed)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return rows

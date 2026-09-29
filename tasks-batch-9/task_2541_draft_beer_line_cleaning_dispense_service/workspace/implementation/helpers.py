"""Shared route helpers: path resolution, body FK resolution, list plumbing."""
import store
from envelope import list_response
from errors import raise_error
from shape import paginate, parse_pagination

PATH_ERRORS = {
    "account_id": "ERR_ACCOUNT_NOT_FOUND",
    "contract_id": "ERR_CONTRACT_NOT_FOUND",
    "line_id": "ERR_LINE_NOT_FOUND",
    "technician_id": "ERR_TECHNICIAN_NOT_FOUND",
    "lot_id": "ERR_CHEMICAL_LOT_NOT_FOUND",
    "part_id": "ERR_PART_NOT_FOUND",
    "program_id": "ERR_PROGRAM_NOT_FOUND",
    "visit_id": "ERR_VISIT_NOT_FOUND",
    "cycle_id": "ERR_CYCLE_NOT_FOUND",
    "record_id": "ERR_BALANCE_RECORD_NOT_FOUND",
    "inspection_id": "ERR_INSPECTION_NOT_FOUND",
    "complaint_id": "ERR_COMPLAINT_NOT_FOUND",
    "loop_id": "ERR_GLYCOL_LOOP_NOT_FOUND",
    "reading_id": "ERR_READING_NOT_FOUND",
}

BODY_ERRORS = {
    "account_id": "ERR_ACCOUNT_NOT_FOUND",
    "line_id": "ERR_LINE_NOT_FOUND",
    "technician_id": "ERR_TECHNICIAN_NOT_FOUND",
    "chemical_lot_id": "ERR_CHEMICAL_LOT_NOT_FOUND",
    "part_sku_id": "ERR_PART_NOT_FOUND",
    "brewer_program_id": "ERR_PROGRAM_NOT_FOUND",
    "visit_id": "ERR_VISIT_NOT_FOUND",
    "glycol_loop_id": "ERR_GLYCOL_LOOP_NOT_FOUND",
}

COLLECTION_FOR = {
    "account_id": store.accounts,
    "contract_id": store.contracts,
    "line_id": store.lines,
    "technician_id": store.technicians,
    "lot_id": store.chemical_lots,
    "chemical_lot_id": store.chemical_lots,
    "part_id": store.parts,
    "part_sku_id": store.parts,
    "program_id": store.programs,
    "brewer_program_id": store.programs,
    "visit_id": store.visits,
    "cycle_id": store.cycles,
    "record_id": store.balance_records,
    "inspection_id": store.inspections,
    "complaint_id": store.complaints,
    "loop_id": store.glycol_loops,
    "glycol_loop_id": store.glycol_loops,
    "reading_id": store.cooler_readings,
}


def resolve_path(param, value):
    row = COLLECTION_FOR[param].get(value)
    if row is None:
        raise_error(PATH_ERRORS[param])
    return row


def resolve_body(field, value, optional=False):
    if value is None:
        if optional:
            return None
        raise_error(BODY_ERRORS[field])
    row = COLLECTION_FOR[field].get(value)
    if row is None:
        raise_error(BODY_ERRORS[field])
    return row


def listing(rows, serializer):
    limit, offset = parse_pagination()
    ordered = store.sort_created(rows)
    page, total = paginate(ordered, limit, offset)
    return list_response([serializer(row) for row in page], limit, offset, total)


def match(row, field, value):
    return value is None or row.get(field) == value

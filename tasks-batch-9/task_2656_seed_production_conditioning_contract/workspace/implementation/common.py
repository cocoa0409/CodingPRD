"""Shared lookup, serialization and list helpers."""

from errors import ApiError
from store import by_created_at, db


def public(rec):
    """Public projection: every key that is not an internal bookkeeping key."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def public_list(rows):
    return [public(r) for r in rows]


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def lookup(table, ident, error_id):
    if not isinstance(ident, str):
        raise ApiError(error_id)
    rec = table.get(ident)
    if rec is None:
        raise ApiError(error_id)
    return rec


def get_variety(ident):
    return lookup(db.varieties, ident, "ERR_VARIETY_NOT_FOUND")


def get_treatment_product(ident):
    return lookup(db.treatment_products, ident, "ERR_TREATMENT_PRODUCT_NOT_FOUND")


def get_grower(ident):
    return lookup(db.growers, ident, "ERR_GROWER_NOT_FOUND")


def get_field(ident):
    return lookup(db.production_fields, ident, "ERR_PRODUCTION_FIELD_NOT_FOUND")


def get_history_record(ident):
    return lookup(db.field_history_records, ident, "ERR_FIELD_HISTORY_RECORD_NOT_FOUND")


def get_contract(ident):
    return lookup(db.production_contracts, ident, "ERR_CONTRACT_NOT_FOUND")


def get_inspection(ident):
    return lookup(db.field_inspections, ident, "ERR_INSPECTION_NOT_FOUND")


def get_equipment(ident):
    return lookup(db.harvest_equipment, ident, "ERR_EQUIPMENT_NOT_FOUND")


def get_harvest_event(ident):
    return lookup(db.harvest_events, ident, "ERR_HARVEST_EVENT_NOT_FOUND")


def get_line(ident):
    return lookup(db.conditioning_lines, ident, "ERR_LINE_NOT_FOUND")


def get_lot(ident):
    return lookup(db.seed_lots, ident, "ERR_SEED_LOT_NOT_FOUND")


def get_run(ident):
    return lookup(db.conditioning_runs, ident, "ERR_RUN_NOT_FOUND")


def get_sample(ident):
    return lookup(db.lot_samples, ident, "ERR_SAMPLE_NOT_FOUND")


def get_tag(ident):
    return lookup(db.certification_tags, ident, "ERR_TAG_NOT_FOUND")


def get_settlement(ident):
    return lookup(db.settlements, ident, "ERR_SETTLEMENT_NOT_FOUND")


def rows_where(table, **filters):
    """created_at-ascending rows matching every non-None equality filter."""
    out = []
    for rec in table.values():
        keep = True
        for key, value in filters.items():
            if value is None:
                continue
            if rec.get(key) != value:
                keep = False
                break
        if keep:
            out.append(rec)
    return by_created_at(out)

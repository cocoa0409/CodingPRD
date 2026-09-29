"""Existence resolution helpers, ordered exactly as PRD section 2.7 requires."""

from db import db, ordered
from errors import ApiError


def _get(collection, ident, error_id):
    if ident is None:
        raise ApiError(error_id)
    record = collection.get(ident)
    if record is None:
        raise ApiError(error_id)
    return record


# Step 4 -- configuration existence.
def species_profile(ident):
    return _get(db.species_profiles, ident, "ERR_CONFIG_NOT_FOUND")


def drying_schedule(ident):
    return _get(db.drying_schedules, ident, "ERR_CONFIG_NOT_FOUND")


def kiln_chamber(ident):
    return _get(db.kiln_chambers, ident, "ERR_CONFIG_NOT_FOUND")


def product_line(ident):
    return _get(db.product_lines, ident, "ERR_CONFIG_NOT_FOUND")


def core_stock(ident):
    return _get(db.core_stocks, ident, "ERR_CONFIG_NOT_FOUND")


def prefinish_line(ident):
    return _get(db.prefinish_lines, ident, "ERR_CONFIG_NOT_FOUND")


# Steps 5 - 11 -- workflow existence.
def green_receipt(ident):
    return _get(db.green_receipts, ident, "ERR_RECEIPT_NOT_FOUND")


def kiln_charge(ident):
    return _get(db.kiln_charges, ident, "ERR_CHARGE_NOT_FOUND")


def flooring_lot(ident):
    return _get(db.flooring_lots, ident, "ERR_LOT_NOT_FOUND")


def grade_run(ident):
    return _get(db.grade_runs, ident, "ERR_GRADE_RUN_NOT_FOUND")


def grade_bundle(ident):
    return _get(db.grade_bundles, ident, "ERR_NOT_FOUND")


def prefinish_run(ident):
    return _get(db.prefinish_runs, ident, "ERR_PREFINISH_RUN_NOT_FOUND")


def byproduct_batch(ident):
    return _get(db.byproduct_batches, ident, "ERR_BATCH_NOT_FOUND")


def byproduct_sale(ident):
    return _get(db.byproduct_sales, ident, "ERR_NOT_FOUND")


def warranty_claim(ident):
    return _get(db.warranty_claims, ident, "ERR_CLAIM_NOT_FOUND")


def code_taken(collection, field, value):
    return any(record.get(field) == value for record in collection.values())


def filtered(collection, predicates):
    """Filters combine conjunctively and are applied before paging (PRD 2.3)."""
    rows = ordered(collection)
    for field, value in predicates:
        if value is None:
            continue
        rows = [row for row in rows if row.get(field) == value]
    return rows

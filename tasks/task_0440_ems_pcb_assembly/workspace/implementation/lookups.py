"""Lookup helpers that raise the correct existence errors.

Path-referenced resources -> ERR_NOT_FOUND (404).
Body FK references         -> ERR_FK_NOT_FOUND (404).
"""

import db
import errors


def get_path(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise errors.not_found("Resource named in the path does not exist.")
    return rec


def get_fk(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise errors.fk_not_found("A referenced resource does not exist.")
    return rec


def part_path(rid):
    return get_path(db.parts, rid)


def vendor_path(rid):
    return get_path(db.vendors, rid)


def avl_path(rid):
    return get_path(db.avl_entries, rid)


def lot_path(rid):
    return get_path(db.inventory_lots, rid)


def bom_path(rid):
    return get_path(db.boms, rid)


def bom_line_path(rid):
    return get_path(db.bom_lines, rid)


def work_order_path(rid):
    return get_path(db.work_orders, rid)


def kit_req_path(rid):
    return get_path(db.kit_requirements, rid)


def line_program_path(rid):
    return get_path(db.line_programs, rid)


def unit_path(rid):
    return get_path(db.units, rid)


def rework_path(rid):
    return get_path(db.rework_orders, rid)


def eco_path(rid):
    return get_path(db.ecos, rid)


def rma_path(rid):
    return get_path(db.rmas, rid)

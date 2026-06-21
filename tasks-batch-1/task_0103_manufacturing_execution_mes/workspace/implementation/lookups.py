"""Existence lookups: fetch a record by id or raise ERR_NOT_FOUND (PRD §2.6)."""
import db
import errors


def _get(coll, rid):
    if not isinstance(rid, str):
        raise errors.not_found()
    rec = coll.get(rid)
    if rec is None:
        raise errors.not_found()
    return rec


def product(rid):
    return _get(db.products, rid)


def bom_line(rid):
    return _get(db.bom_lines, rid)


def routing(rid):
    return _get(db.routings, rid)


def operation(rid):
    return _get(db.operations, rid)


def machine(rid):
    return _get(db.machines, rid)


def run_log(rid):
    return _get(db.machine_run_logs, rid)


def work_order(rid):
    return _get(db.work_orders, rid)


def component_demand(rid):
    return _get(db.component_demands, rid)


def work_order_operation(rid):
    return _get(db.work_order_operations, rid)


def lot(rid):
    return _get(db.lots, rid)


def lot_issue(rid):
    return _get(db.lot_issues, rid)


def genealogy_link(rid):
    return _get(db.genealogy_links, rid)


def scrap_disposition(rid):
    return _get(db.scrap_dispositions, rid)

"""Path / body resource resolution with the scaffold's exact not-found codes."""

import store
from errors import ApiError


def _get(coll, rid, error_id):
    rec = coll.get(rid) if isinstance(rid, str) else None
    if rec is None:
        raise ApiError(error_id)
    return rec


def study(rid):
    return _get(store.studies, rid, "ERR_STUDY_NOT_FOUND")


def analysis(rid):
    return _get(store.analyses, rid, "ERR_ANALYSIS_NOT_FOUND")


def coverage_item(rid):
    return _get(store.coverage_items, rid, "ERR_COVERAGE_ITEM_NOT_FOUND")


def calendar(rid):
    return _get(store.calendars, rid, "ERR_CALENDAR_NOT_FOUND")


def calendar_visit(rid):
    return _get(store.calendar_visits, rid, "ERR_CALENDAR_VISIT_NOT_FOUND")


def route(rid):
    return _get(store.routes, rid, "ERR_ROUTE_NOT_FOUND")


def subject(rid):
    return _get(store.subjects, rid, "ERR_SUBJECT_NOT_FOUND")


def subject_visit(rid):
    return _get(store.subject_visits, rid, "ERR_SUBJECT_VISIT_NOT_FOUND")


def charge(rid):
    return _get(store.charges, rid, "ERR_CHARGE_NOT_FOUND")


def invoice(rid):
    return _get(store.invoices, rid, "ERR_INVOICE_NOT_FOUND")


def finding(rid):
    return _get(store.findings, rid, "ERR_FINDING_NOT_FOUND")


def amendment(rid):
    return _get(store.amendments, rid, "ERR_AMENDMENT_NOT_FOUND")

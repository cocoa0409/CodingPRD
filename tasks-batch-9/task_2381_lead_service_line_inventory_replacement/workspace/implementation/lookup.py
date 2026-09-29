"""Path- and foreign-key resolution (ladder rungs 7 and 8).

Each entity owns its own not-found code, and callers resolve identifiers in the
declared left-to-right / input-list order.
"""

from core import db, fail


def _resolve(table, identifier, error_id):
    if not isinstance(identifier, str):
        fail(error_id, "No such row: %r." % (identifier,))
    row = table.get(identifier)
    if row is None:
        fail(error_id, "No such row: %s." % identifier)
    return row


def water_system(identifier):
    return _resolve(db.water_systems, identifier, "ERR_WATER_SYSTEM_NOT_FOUND")


def service_line(identifier):
    return _resolve(db.service_lines, identifier, "ERR_SERVICE_LINE_NOT_FOUND")


def evidence_item(identifier):
    return _resolve(db.evidence_items, identifier, "ERR_EVIDENCE_ITEM_NOT_FOUND")


def crew(identifier):
    return _resolve(db.crews, identifier, "ERR_CREW_NOT_FOUND")


def appointment(identifier):
    return _resolve(db.appointments, identifier, "ERR_APPOINTMENT_NOT_FOUND")


def batch(identifier):
    return _resolve(db.batches, identifier, "ERR_SAMPLING_BATCH_NOT_FOUND")


def publication(identifier):
    return _resolve(db.publications, identifier, "ERR_PUBLICATION_NOT_FOUND")


def notification(identifier):
    return _resolve(db.notifications, identifier, "ERR_NOTIFICATION_NOT_FOUND")


def order(identifier):
    return _resolve(db.orders, identifier, "ERR_REPLACEMENT_ORDER_NOT_FOUND")


def street_project(identifier):
    return _resolve(db.street_projects, identifier, "ERR_STREET_PROJECT_NOT_FOUND")


def funding_source(identifier):
    return _resolve(db.funding_sources, identifier, "ERR_FUNDING_SOURCE_NOT_FOUND")


def progress_report(identifier):
    return _resolve(db.progress_reports, identifier, "ERR_PROGRESS_REPORT_NOT_FOUND")

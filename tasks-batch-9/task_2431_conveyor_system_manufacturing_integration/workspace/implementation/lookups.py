"""Identifier resolution with the per-type not-found codes (PRD section 2.11)."""

from errors import ApiError
from store import store


def _get(collection, identifier, error_id, label):
    if not isinstance(identifier, str) or identifier == "":
        raise ApiError(error_id, "%s does not exist." % label)
    record = collection.get(identifier)
    if record is None:
        raise ApiError(error_id, "%s does not exist." % label)
    return record


def get_project(identifier):
    return _get(store.projects, identifier, "ERR_PROJECT_NOT_FOUND", "Project")


def get_segment(identifier):
    return _get(store.segments, identifier, "ERR_SEGMENT_NOT_FOUND", "Conveyor segment")


def get_flow_link(identifier):
    return _get(store.flow_links, identifier, "ERR_FLOW_LINK_NOT_FOUND", "Flow link")


def get_staging_bay(identifier):
    return _get(store.staging_bays, identifier, "ERR_STAGING_BAY_NOT_FOUND", "Staging bay")


def get_lot(identifier):
    return _get(store.fabrication_lots, identifier, "ERR_LOT_NOT_FOUND", "Fabrication lot")


def get_zone(identifier):
    return _get(store.site_zones, identifier, "ERR_ZONE_NOT_FOUND", "Site zone")


def get_window(identifier):
    return _get(store.cutover_windows, identifier, "ERR_WINDOW_NOT_FOUND", "Cutover window")


def get_change_order(identifier):
    return _get(store.change_orders, identifier, "ERR_CHANGE_ORDER_NOT_FOUND", "Change order")


def get_certificate(identifier):
    return _get(
        store.acceptance_certificates,
        identifier,
        "ERR_CERTIFICATE_NOT_FOUND",
        "Acceptance certificate",
    )


def get_dispute(identifier):
    return _get(
        store.performance_disputes, identifier, "ERR_DISPUTE_NOT_FOUND", "Performance dispute"
    )

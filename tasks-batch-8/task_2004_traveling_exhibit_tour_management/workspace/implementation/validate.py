"""Payload validation, path resolution, and pagination helpers.

Validation order per PRD §2.8: auth -> authorization -> left-to-right path
existence -> payload shape (ERR_INVALID_REQUEST, independent) -> OCC ->
transition state validity -> business rules.
"""

from flask import request

import db
from envelope import ok_list
from errors import fail


# --- body / field validation --------------------------------------------------

def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        fail("ERR_INVALID_REQUEST", "Missing or invalid required field: %s" % field)
    return v


def req_int(data, field, minimum=None):
    v = data.get(field)
    if not _is_int(v):
        fail("ERR_INVALID_REQUEST", "Missing or invalid required field: %s" % field)
    if minimum is not None and v < minimum:
        fail("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (field, minimum))
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", "Missing or invalid required field: %s" % field)
    return v


def req_dt(data, field):
    """Required datetime: returned as the raw string after parse validation,
    so the value echoes back exactly as supplied."""
    v = req_str(data, field)
    if db.parse_dt(v) is None:
        fail("ERR_INVALID_REQUEST", "Field %s is not a valid ISO 8601 timestamp" % field)
    return v


def opt_int(data, field, minimum=None):
    if field not in data or data[field] is None:
        return None
    v = data[field]
    if not _is_int(v):
        fail("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        fail("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (field, minimum))
    return v


def req_version(data, field):
    """OCC token: integer (numeric strings coerced)."""
    v = data.get(field)
    if _is_int(v):
        return v
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v.strip())
    fail("ERR_INVALID_REQUEST", "Missing or invalid required field: %s" % field)


# --- path resolution (left to right) ------------------------------------------

def get_tour(tour_id):
    tour = db.tours.get(tour_id)
    if tour is None:
        fail("ERR_NOT_FOUND", "Tour not found: %s" % tour_id)
    return tour


def get_venue(venue_id):
    venue = db.venues.get(venue_id)
    if venue is None:
        fail("ERR_NOT_FOUND", "Venue not found: %s" % venue_id)
    return venue


def get_stop(tour, stop_id):
    stop = db.stops.get(stop_id)
    if stop is None or stop["tour_id"] != tour["id"]:
        fail("ERR_NOT_FOUND", "TourStop not found: %s" % stop_id)
    return stop


def get_crate(tour, crate_id):
    crate = db.crates.get(crate_id)
    if crate is None or crate["tour_id"] != tour["id"]:
        fail("ERR_NOT_FOUND", "Crate not found: %s" % crate_id)
    return crate


def get_shipment(tour, shipment_id):
    sh = db.shipments.get(shipment_id)
    if sh is None or sh["tour_id"] != tour["id"]:
        fail("ERR_NOT_FOUND", "Shipment not found: %s" % shipment_id)
    return sh


def get_report(shipment, report_id):
    rep = db.reports.get(report_id)
    if rep is None or rep["shipment_id"] != shipment["id"]:
        fail("ERR_NOT_FOUND", "ConditionReport not found: %s" % report_id)
    return rep


def get_claim(shipment, claim_id):
    cl = db.claims.get(claim_id)
    if cl is None or cl["shipment_id"] != shipment["id"]:
        fail("ERR_NOT_FOUND", "DamageClaim not found: %s" % claim_id)
    return cl


def get_cert(tour, cert_id):
    cert = db.certs.get(cert_id)
    if cert is None or cert["tour_id"] != tour["id"]:
        fail("ERR_NOT_FOUND", "InsuranceCertificate not found: %s" % cert_id)
    return cert


# --- pagination (PRD §2.3: limit default 10 min 1 max 100, offset default 0) --

def paginate(items):
    """items must already be filtered and sorted by created_at ascending."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list(page, total, limit, offset)


def apply_filters(items, filters):
    """filters: list of (query_param_name, resource_field). Exact-match."""
    for param, field in filters:
        raw = request.args.get(param)
        if raw is None:
            continue
        items = [r for r in items if str(r.get(field)) == raw]
    return items


def sorted_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))

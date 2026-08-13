"""Shared route helpers: body parsing, pagination, existence, filters."""

from flask import request

import db
import errors


def body():
    """Parse the JSON request body. Empty body returns {}."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        errors.raise_err(errors.ERR_INVALID_REQUEST, "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_fields(data, *fields):
    for f in fields:
        if f not in data or data[f] is None:
            errors.raise_err(errors.ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_enum(data, field, allowed):
    val = data.get(field)
    if val not in allowed:
        errors.raise_err(
            errors.ERR_INVALID_REQUEST,
            f"Field {field} must be one of {sorted(allowed)}",
        )
    return val


def opt_enum(data, field, allowed):
    val = data.get(field)
    if val is None:
        return None
    if val not in allowed:
        errors.raise_err(
            errors.ERR_INVALID_REQUEST,
            f"Field {field} must be one of {sorted(allowed)}",
        )
    return val


def parse_pagination():
    """Parse limit/offset per envelope defaults (limit=10, min=1, max=100)."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        errors.raise_err(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        errors.raise_err(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items):
    """Apply pagination to an in-memory sorted list; returns (page, limit, offset, total)."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def parse_bool_param(name):
    val = request.args.get(name)
    if val is None:
        return None
    if val.lower() in ("true", "1"):
        return True
    if val.lower() in ("false", "0"):
        return False
    errors.raise_err(errors.ERR_INVALID_REQUEST, f"{name} must be a boolean")


def parse_dt_field(data, field):
    val = data.get(field)
    if val is None:
        return None
    try:
        return db.parse_dt(val)
    except (ValueError, TypeError):
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} must be ISO8601 datetime")


def require_dt_field(data, field):
    val = data.get(field)
    if val is None:
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
    try:
        return db.parse_dt(val)
    except (ValueError, TypeError):
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} must be ISO8601 datetime")


def require_number(data, field):
    val = data.get(field)
    if val is None:
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} must be a number")
    return val


def require_int(data, field):
    val = data.get(field)
    if val is None:
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
    if isinstance(val, bool) or not isinstance(val, int):
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    return val


def require_str(data, field):
    val = data.get(field)
    if val is None:
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
    if not isinstance(val, str):
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} must be a string")
    return val


# ---------------------------------------------------------------------------
# Existence checks (priority 3; ERR_NOT_FOUND)
# ---------------------------------------------------------------------------

def get_program_or_404(program_id):
    p = db.programs.get(program_id)
    if not p:
        errors.raise_err(errors.ERR_NOT_FOUND, "Program not found")
    return p


def get_site_or_404(site_id, program_id=None):
    s = db.sites.get(site_id)
    if not s or (program_id is not None and s["program_id"] != program_id):
        errors.raise_err(errors.ERR_NOT_FOUND, "Site not found")
    return s


def get_agreement_or_404(agreement_id, program_id=None):
    a = db.host_agreements.get(agreement_id)
    if not a or (program_id is not None and a["program_id"] != program_id):
        errors.raise_err(errors.ERR_NOT_FOUND, "SiteHostAgreement not found")
    return a


def get_material_or_404(material_id, program_id=None):
    m = db.materials.get(material_id)
    if not m or (program_id is not None and m["program_id"] != program_id):
        errors.raise_err(errors.ERR_NOT_FOUND, "MaterialCategory not found")
    return m


def get_participant_or_404(participant_id, program_id=None):
    p = db.participants.get(participant_id)
    if not p or (program_id is not None and p["program_id"] != program_id):
        errors.raise_err(errors.ERR_NOT_FOUND, "Participant not found")
    return p


def get_grant_or_404(grant_id, participant_id=None):
    g = db.grants.get(grant_id)
    if not g or (participant_id is not None and g["participant_id"] != participant_id):
        errors.raise_err(errors.ERR_NOT_FOUND, "AccessGrant not found")
    return g


def get_drop_or_404(drop_id, site_id=None):
    d = db.drops.get(drop_id)
    if not d or (site_id is not None and d["site_id"] != site_id):
        errors.raise_err(errors.ERR_NOT_FOUND, "DropEvent not found")
    return d


def get_report_or_404(report_id, site_id=None):
    r = db.contamination_reports.get(report_id)
    if not r or (site_id is not None and r["site_id"] != site_id):
        errors.raise_err(errors.ERR_NOT_FOUND, "ContaminationReport not found")
    return r


def get_route_or_404(route_id, program_id=None):
    r = db.routes.get(route_id)
    if not r or (program_id is not None and r["program_id"] != program_id):
        errors.raise_err(errors.ERR_NOT_FOUND, "CollectionRoute not found")
    return r


def get_partner_or_404(partner_id, program_id=None):
    p = db.partners.get(partner_id)
    if not p or (program_id is not None and p["program_id"] != program_id):
        errors.raise_err(errors.ERR_NOT_FOUND, "ProcessingPartner not found")
    return p


def get_stop_or_404(stop_id, route_id=None):
    s = db.stops.get(stop_id)
    if not s or (route_id is not None and s["route_id"] != route_id):
        errors.raise_err(errors.ERR_NOT_FOUND, "RouteStop not found")
    return s


def get_batch_or_404(batch_id, partner_id=None):
    b = db.batches.get(batch_id)
    if not b or (partner_id is not None and b["partner_id"] != partner_id):
        errors.raise_err(errors.ERR_NOT_FOUND, "ProcessingBatch not found")
    return b


def get_distribution_or_404(distribution_id, program_id=None):
    d = db.distributions.get(distribution_id)
    if not d or (program_id is not None and d["program_id"] != program_id):
        errors.raise_err(errors.ERR_NOT_FOUND, "CompostDistribution not found")
    return d


def get_allocation_or_404(allocation_id, distribution_id=None):
    a = db.allocations.get(allocation_id)
    if not a or (distribution_id is not None and a["distribution_id"] != distribution_id):
        errors.raise_err(errors.ERR_NOT_FOUND, "DistributionAllocation not found")
    return a


def get_complaint_or_404(complaint_id, site_id=None):
    c = db.complaints.get(complaint_id)
    if not c or (site_id is not None and c["site_id"] != site_id):
        errors.raise_err(errors.ERR_NOT_FOUND, "ComplaintTicket not found")
    return c


def get_diversion_report_or_404(report_id, program_id=None):
    r = db.diversion_reports.get(report_id)
    if not r or (program_id is not None and r["program_id"] != program_id):
        errors.raise_err(errors.ERR_NOT_FOUND, "DiversionReport not found")
    return r


def occ_check(entity, expected, field_name):
    """Priority-4 optimistic concurrency check. Skipped when expected is None."""
    if expected is None:
        return
    if isinstance(expected, bool) or not isinstance(expected, int):
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"{field_name} must be an integer")
    if expected != entity["version"]:
        errors.raise_err(errors.ERR_STALE_VERSION, f"Stale {field_name}")


def sort_created(items):
    return sorted(items, key=lambda e: e.get("created_at", ""))

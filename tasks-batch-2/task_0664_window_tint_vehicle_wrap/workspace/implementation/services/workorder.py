"""WorkOrder derivation and scheduling helpers."""
import db
from services import calculations
from services import quote as quote_svc

ACTIVE_INSTALL_STATES = {"SCHEDULED", "IN_PROGRESS", "CURING"}


def primary_service_type_and_package(quote_id):
    """Return (service_type, package) for the dominant INCLUDED line."""
    lines = quote_svc.included_lines(quote_id)
    if not lines:
        return None, None
    # Highest line_total_cents, tie-break earliest created_at.
    best = None
    for line in lines:
        if best is None:
            best = line
            continue
        if line["line_total_cents"] > best["line_total_cents"]:
            best = line
        elif line["line_total_cents"] == best["line_total_cents"]:
            if (line["created_at"], line["id"]) < (best["created_at"], best["id"]):
                best = line
    pkg = db.service_packages[best["service_package_id"]]
    return pkg["service_type"], pkg


def aggregate_duration(quote_id):
    """Sum of duration_minutes over the source quote's INCLUDED lines' packages."""
    total = 0
    for line in quote_svc.included_lines(quote_id):
        total += db.service_packages[line["service_package_id"]]["duration_minutes"]
    return total


def aggregate_cure_buffer(quote_id):
    """Max cure_buffer_minutes over the source quote's INCLUDED lines' packages."""
    values = [db.service_packages[line["service_package_id"]]["cure_buffer_minutes"]
              for line in quote_svc.included_lines(quote_id)]
    return max(values) if values else 0


def max_cure_hours(quote_id):
    """Max cure_hours over the source quote's INCLUDED lines' materials."""
    values = [db.film_materials[line["film_material_id"]]["cure_hours"]
              for line in quote_svc.included_lines(quote_id)]
    return max(values) if values else 0


def max_warranty_days(quote_id):
    """Max warranty_days over the source quote's INCLUDED lines' packages."""
    values = [db.service_packages[line["service_package_id"]]["warranty_days"]
              for line in quote_svc.included_lines(quote_id)]
    return max(values) if values else 0


def bay_intervals(bay_id, exclude_wo_id=None):
    """Return [(start, end)] half-open bay-occupancy intervals for active orders
    on this bay. Bay interval = [scheduled_start, scheduled_start + duration + buffer).
    """
    intervals = []
    for wo in db.work_orders.values():
        if wo["bay_id"] != bay_id:
            continue
        if exclude_wo_id is not None and wo["id"] == exclude_wo_id:
            continue
        if wo["install_status"] not in ACTIVE_INSTALL_STATES:
            continue
        start = db.parse_iso(wo["scheduled_start"])
        end = _add_minutes(start, wo["duration_minutes"] + wo["cure_buffer_minutes"])
        intervals.append((start, end))
    return intervals


def installer_intervals(installer_id, exclude_wo_id=None):
    """Return [(start, end)] half-open installer-occupancy intervals for active
    orders for this installer. Installer interval =
    [scheduled_start - REST_BUFFER, scheduled_start + duration).
    """
    intervals = []
    for wo in db.work_orders.values():
        if wo["installer_id"] != installer_id:
            continue
        if exclude_wo_id is not None and wo["id"] == exclude_wo_id:
            continue
        if wo["install_status"] not in ACTIVE_INSTALL_STATES:
            continue
        start = db.parse_iso(wo["scheduled_start"])
        a = _add_minutes(start, -calculations.INSTALLER_REST_BUFFER_MINUTES)
        b = _add_minutes(start, wo["duration_minutes"])
        intervals.append((a, b))
    return intervals


def overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval intersection; adjacency (touching endpoints) allowed."""
    return a_start < b_end and b_start < a_end


def _add_minutes(dt, minutes):
    from datetime import timedelta
    return dt + timedelta(minutes=minutes)

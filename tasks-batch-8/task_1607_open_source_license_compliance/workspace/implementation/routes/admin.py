"""Test-driving admin endpoints: clock, vulnerability feed, scan worker."""

from flask import Blueprint

from db import store, iso_fmt, parse_iso
from errors import err, ERR_SCAN_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import require_roles, get_json_body
from response import success_obj
from services import engine
from routes.vulnerabilities import _register_vulnerability, vuln_view
from routes.scans import scan_view

bp = Blueprint("admin", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PlatformAdmin")
    body = get_json_body()
    to_iso8601 = body.get("to_iso8601")
    if not to_iso8601:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 is required")
    try:
        dt = parse_iso(to_iso8601)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp")
    store.set_clock(dt)
    engine.time_sweep()
    return success_obj({"current_utc": iso_fmt(store.now())})


@bp.route("/_vulnerability-feed/simulate", methods=["POST"])
def simulate_feed():
    require_roles("PlatformAdmin")
    body = get_json_body()
    v = _register_vulnerability(body)
    return success_obj(vuln_view(v))


@bp.route("/_scan-worker/process-next", methods=["POST"])
def process_next():
    require_roles("PlatformAdmin")
    body = get_json_body()
    scan_id = body.get("scan_id")
    if not scan_id:
        raise err(ERR_INVALID_REQUEST, "scan_id is required")
    scan = store.scans.get(scan_id)
    if not scan:
        raise err(ERR_SCAN_NOT_FOUND, "DependencyScan not found")
    if scan["status"] != "QUEUED":
        raise err(ERR_INVALID_REQUEST, "Scan must be in QUEUED state to process")
    engine.process_scan(scan)
    return success_obj(scan_view(scan))

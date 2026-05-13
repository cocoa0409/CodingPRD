"""Package routes."""
from flask import Blueprint, request

from db import store, new_id, now_iso
from errors import raise_error, ERR_PACKAGE_NOT_FOUND
from middleware import require_roles
from response import success, parse_pagination, paginate
from services.packages import check_package_version_unique


bp = Blueprint("packages", __name__)


def serialize_package(p):
    return dict(p)


@bp.route("/packages", methods=["POST"])
@require_roles("PlatformAdmin")
def create_package_version():
    body = request.get_json(silent=True) or {}
    package_code = body.get("package_code")
    version_number = body.get("version_number")
    check_package_version_unique(package_code, version_number)

    pid = new_id()
    pv = {
        "id": pid,
        "created_at": now_iso(),
        "package_code": package_code,
        "version_number": int(version_number),
        "package_type": body.get("package_type"),
        "effective_from": body.get("effective_from"),
        "base_price_cents": int(body.get("base_price_cents", 0)),
        "currency": body.get("currency"),
        "billing_cycle": body.get("billing_cycle"),
        "pricing_model": body.get("pricing_model"),
        "included_quotas": body.get("included_quotas") or {},
        "tiered_brackets": body.get("tiered_brackets") or [],
        "overage_rates": body.get("overage_rates") or {},
        "addons": body.get("addons") or [],
    }
    store.package_versions[pid] = pv
    return success(serialize_package(pv), status=201)


@bp.route("/packages", methods=["GET"])
@require_roles("PlatformAdmin", "BillingOperator", "TenantAdmin")
def list_packages():
    limit, offset = parse_pagination(request.args)
    code = request.args.get("package_code")
    ptype = request.args.get("package_type")
    items = list(store.package_versions.values())
    if code:
        items = [p for p in items if p["package_code"] == code]
    if ptype:
        items = [p for p in items if p["package_type"] == ptype]
    items.sort(key=lambda p: p["created_at"])
    page, meta = paginate(items, limit, offset)
    return success([serialize_package(p) for p in page], status=200,
                   pagination=meta, response_type="array")


@bp.route("/packages/<pid>", methods=["GET"])
@require_roles("PlatformAdmin", "BillingOperator", "TenantAdmin")
def get_package(pid):
    pv = store.package_versions.get(pid)
    if pv is None:
        raise_error(ERR_PACKAGE_NOT_FOUND, f"PackageVersion {pid} not found")
    return success(serialize_package(pv), status=200)

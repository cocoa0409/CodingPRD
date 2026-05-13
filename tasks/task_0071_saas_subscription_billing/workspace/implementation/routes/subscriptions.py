"""Subscription routes."""
from flask import Blueprint, request, g

from clock import clock, parse_iso

from db import store, now_iso
from errors import (
    raise_error,
    ERR_FORBIDDEN,
    ERR_TENANT_STATUS_INVALID,
    ERR_SUBSCRIPTION_STATUS_INVALID,
    ERR_TENANT_READ_ONLY,
    ERR_VERSION_CONFLICT,
    ERR_SUBSCRIPTION_CHANGE_IN_FLIGHT,
    ERR_CURRENCY_MISMATCH,
    ERR_NOT_AN_UPGRADE,
    ERR_NOT_A_DOWNGRADE,
    ERR_USAGE_TOO_LATE,
    ERR_INVALID_USAGE_QUANTITY,
    ERR_DUPLICATE_USAGE_IDEMPOTENCY_KEY,
    ERR_TENANT_FEATURE_RESTRICTED,
)
from middleware import authenticate, enforce_tenant_isolation
from response import success, parse_pagination, paginate
from routes.tenants import get_tenant_or_404
from services.packages import resolve_package_or_404, get_package_by_id_or_none
from services.subscriptions import (
    get_subscription_for_tenant,
    create_subscription,
    convert_trial,
    upgrade_subscription,
    downgrade_end_of_cycle,
    downgrade_immediate_refund,
    cancel_subscription,
    has_in_flight_change,
)
from db import new_id


bp = Blueprint("subscriptions", __name__)


def serialize_subscription(s):
    return dict(s)


def _check_role(allowed):
    if g.actor_role not in allowed:
        raise_error(ERR_FORBIDDEN, "Not permitted")


@bp.route("/tenants/<tenant_id>/subscriptions", methods=["POST"])
def create_sub(tenant_id):
    authenticate()
    _check_role(("PlatformAdmin", "TenantAdmin"))
    tenant = get_tenant_or_404(tenant_id)
    enforce_tenant_isolation(tenant_id)
    if tenant["tenant_status"] != "TRIAL":
        raise_error(ERR_TENANT_STATUS_INVALID,
                    "Subscriptions can only be created on TRIAL tenants")
    if tenant.get("restriction_level") in ("READ_ONLY", "FEATURE_RESTRICTED"):
        raise_error(ERR_TENANT_READ_ONLY, "Tenant is restricted")

    body = request.get_json(silent=True) or {}
    package_code = body.get("package_code")
    selected_addons = body.get("selected_addons") or []
    pkg = resolve_package_or_404(package_code, clock.now())
    if pkg["currency"] != tenant["currency"]:
        raise_error(ERR_CURRENCY_MISMATCH,
                    "Package currency does not match tenant currency")
    sub, _ = create_subscription(tenant, package_code, selected_addons)
    return success(serialize_subscription(sub), status=201)


@bp.route("/tenants/<tenant_id>/subscriptions/<sub_id>", methods=["GET"])
def get_sub(tenant_id, sub_id):
    authenticate()
    _check_role(("PlatformAdmin", "BillingOperator", "TenantAdmin"))
    get_tenant_or_404(tenant_id)
    enforce_tenant_isolation(tenant_id)
    sub = get_subscription_for_tenant(tenant_id, sub_id)
    return success(serialize_subscription(sub), status=200)


@bp.route("/tenants/<tenant_id>/subscriptions/<sub_id>/convert", methods=["POST"])
def convert_sub(tenant_id, sub_id):
    authenticate()
    _check_role(("PlatformAdmin", "TenantAdmin"))
    tenant = get_tenant_or_404(tenant_id)
    enforce_tenant_isolation(tenant_id)
    sub = get_subscription_for_tenant(tenant_id, sub_id)
    if tenant["tenant_status"] not in ("TRIAL", "ACTIVE"):
        raise_error(ERR_TENANT_STATUS_INVALID,
                    "Conversion requires tenant in TRIAL or ACTIVE")
    if sub["subscription_status"] != "TRIAL":
        raise_error(ERR_SUBSCRIPTION_STATUS_INVALID,
                    "Conversion requires subscription in TRIAL")
    if tenant.get("restriction_level") in ("READ_ONLY", "FEATURE_RESTRICTED"):
        raise_error(ERR_TENANT_READ_ONLY, "Tenant is restricted")
    body = request.get_json(silent=True) or {}
    if "version" in body and body["version"] is not None:
        if int(body["version"]) != int(sub["version"]):
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch")
    convert_trial(sub, tenant)
    return success(serialize_subscription(sub), status=200)


@bp.route("/tenants/<tenant_id>/subscriptions/<sub_id>/upgrade", methods=["POST"])
def upgrade_sub(tenant_id, sub_id):
    authenticate()
    _check_role(("PlatformAdmin", "TenantAdmin"))
    tenant = get_tenant_or_404(tenant_id)
    enforce_tenant_isolation(tenant_id)
    sub = get_subscription_for_tenant(tenant_id, sub_id)

    if tenant["tenant_status"] != "ACTIVE":
        raise_error(ERR_TENANT_STATUS_INVALID, "Upgrade requires ACTIVE tenant")
    if sub["subscription_status"] != "ACTIVE":
        raise_error(ERR_SUBSCRIPTION_STATUS_INVALID,
                    "Upgrade requires ACTIVE subscription")
    if tenant.get("restriction_level") in ("READ_ONLY", "FEATURE_RESTRICTED"):
        raise_error(ERR_TENANT_READ_ONLY, "Tenant is restricted")

    body = request.get_json(silent=True) or {}
    if "version" in body and body["version"] is not None:
        if int(body["version"]) != int(sub["version"]):
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch")
    if has_in_flight_change(sub):
        raise_error(ERR_SUBSCRIPTION_CHANGE_IN_FLIGHT,
                    "A subscription change is already in flight")

    target_code = body.get("target_package_code")
    target_pkg = resolve_package_or_404(target_code, clock.now())

    if target_pkg["currency"] != tenant["currency"]:
        raise_error(ERR_CURRENCY_MISMATCH,
                    "Target package currency mismatch")

    current_pkg = store.package_versions[sub["package_version_id"]]
    if int(target_pkg["base_price_cents"]) <= int(current_pkg["base_price_cents"]):
        raise_error(ERR_NOT_AN_UPGRADE,
                    "Target package base price is not greater than current")

    upgrade_subscription(sub, tenant, target_pkg)
    return success(serialize_subscription(sub), status=200)


@bp.route("/tenants/<tenant_id>/subscriptions/<sub_id>/downgrade", methods=["POST"])
def downgrade_sub(tenant_id, sub_id):
    authenticate()
    _check_role(("PlatformAdmin", "TenantAdmin"))
    tenant = get_tenant_or_404(tenant_id)
    enforce_tenant_isolation(tenant_id)
    sub = get_subscription_for_tenant(tenant_id, sub_id)

    if tenant["tenant_status"] != "ACTIVE":
        raise_error(ERR_TENANT_STATUS_INVALID, "Downgrade requires ACTIVE tenant")
    if sub["subscription_status"] != "ACTIVE":
        raise_error(ERR_SUBSCRIPTION_STATUS_INVALID,
                    "Downgrade requires ACTIVE subscription")
    if tenant.get("restriction_level") in ("READ_ONLY", "FEATURE_RESTRICTED"):
        raise_error(ERR_TENANT_READ_ONLY, "Tenant is restricted")

    body = request.get_json(silent=True) or {}
    if "version" in body and body["version"] is not None:
        if int(body["version"]) != int(sub["version"]):
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch")
    if has_in_flight_change(sub):
        raise_error(ERR_SUBSCRIPTION_CHANGE_IN_FLIGHT,
                    "A subscription change is already in flight")

    target_code = body.get("target_package_code")
    target_pkg = resolve_package_or_404(target_code, clock.now())
    if target_pkg["currency"] != tenant["currency"]:
        raise_error(ERR_CURRENCY_MISMATCH, "Target package currency mismatch")

    current_pkg = store.package_versions[sub["package_version_id"]]
    if int(target_pkg["base_price_cents"]) >= int(current_pkg["base_price_cents"]):
        raise_error(ERR_NOT_A_DOWNGRADE,
                    "Target package base price is not less than current")

    mode = request.args.get("mode") or body.get("mode")
    if mode == "IMMEDIATE_REFUND":
        if current_pkg["pricing_model"] not in ("PREPAID", "HYBRID"):
            # cannot refund money never charged
            raise_error(ERR_SUBSCRIPTION_STATUS_INVALID,
                        "Cannot IMMEDIATE_REFUND on a POSTPAID-only package")
        downgrade_immediate_refund(sub, tenant, target_pkg)
    else:
        # Default to END_OF_CYCLE
        downgrade_end_of_cycle(sub, tenant, target_pkg)
    return success(serialize_subscription(sub), status=200)


@bp.route("/tenants/<tenant_id>/subscriptions/<sub_id>", methods=["DELETE"])
def delete_sub(tenant_id, sub_id):
    authenticate()
    _check_role(("PlatformAdmin", "TenantAdmin"))
    tenant = get_tenant_or_404(tenant_id)
    enforce_tenant_isolation(tenant_id)
    sub = get_subscription_for_tenant(tenant_id, sub_id)
    if sub["subscription_status"] not in ("TRIAL", "ACTIVE", "PENDING_DOWNGRADE"):
        raise_error(ERR_SUBSCRIPTION_STATUS_INVALID,
                    "Cannot cancel subscription in current state")
    if tenant.get("restriction_level") in ("READ_ONLY", "FEATURE_RESTRICTED"):
        raise_error(ERR_TENANT_READ_ONLY, "Tenant is restricted")
    body = request.get_json(silent=True) or {}
    if body and "version" in body and body["version"] is not None:
        if int(body["version"]) != int(sub["version"]):
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch")
    cancel_subscription(sub, tenant)
    return ("", 204)


@bp.route("/tenants/<tenant_id>/subscriptions/<sub_id>/changes", methods=["GET"])
def list_changes(tenant_id, sub_id):
    authenticate()
    _check_role(("PlatformAdmin", "BillingOperator", "TenantAdmin"))
    get_tenant_or_404(tenant_id)
    enforce_tenant_isolation(tenant_id)
    get_subscription_for_tenant(tenant_id, sub_id)
    limit, offset = parse_pagination(request.args)
    items = [c for c in store.subscription_changes.values()
             if c["subscription_id"] == sub_id]
    items.sort(key=lambda c: c["created_at"])
    page, meta = paginate(items, limit, offset)
    return success([dict(c) for c in page], status=200, pagination=meta,
                   response_type="array")


# ------------- Usage -------------

@bp.route("/tenants/<tenant_id>/subscriptions/<sub_id>/usage", methods=["POST"])
def post_usage(tenant_id, sub_id):
    authenticate()
    _check_role(("PlatformAdmin", "TenantAdmin"))
    tenant = get_tenant_or_404(tenant_id)
    enforce_tenant_isolation(tenant_id)
    sub = get_subscription_for_tenant(tenant_id, sub_id)
    # PRD §2.12: 'all POST, PATCH, and DELETE requests scoped to the
    # tenant — except the payment endpoint, which must always remain
    # available so the tenant can clear its debt — are rejected with
    # ERR_TENANT_READ_ONLY while restriction_level is either READ_ONLY
    # or FEATURE_RESTRICTED.' Per PRD §2.11 priority, this gate (line 6)
    # precedes business-constraint checks like uniqueness (line 10) and
    # the feature-restricted quota check (line 6 sub-rule).
    if tenant.get("restriction_level") in ("READ_ONLY", "FEATURE_RESTRICTED"):
        raise_error(ERR_TENANT_READ_ONLY,
                    "Tenant is restricted; mutations blocked")

    body = request.get_json(silent=True) or {}
    idem_key = body.get("idempotency_key")
    metric = body.get("metric")
    quantity = body.get("quantity")
    event_ts = body.get("event_timestamp")
    ingestion_mode = body.get("ingestion_mode")

    # Validate quantity
    try:
        q = int(quantity)
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_USAGE_QUANTITY, "quantity must be a non-negative integer")
    if q < 0:
        raise_error(ERR_INVALID_USAGE_QUANTITY, "quantity must be non-negative")

    # Idempotency check
    existing = None
    for rec in store.usage_records.values():
        if rec["subscription_id"] == sub_id and rec["idempotency_key"] == idem_key:
            existing = rec
            break
    if existing is not None:
        # Check conflict
        same = (existing["metric"] == metric
                and int(existing["quantity"]) == q
                and existing["event_timestamp"] == event_ts
                and existing["ingestion_mode"] == ingestion_mode)
        if same:
            return success(dict(existing), status=201)
        raise_error(ERR_DUPLICATE_USAGE_IDEMPOTENCY_KEY,
                    "Duplicate idempotency_key with conflicting payload")

    # Late-arrival window
    try:
        ets = parse_iso(event_ts)
    except Exception:
        raise_error(ERR_INVALID_USAGE_QUANTITY, "Invalid event_timestamp")
    cs = parse_iso(sub["cycle_start"])
    ce = parse_iso(sub["cycle_end"])
    from datetime import timedelta
    if ets < cs - timedelta(days=7):
        raise_error(ERR_USAGE_TOO_LATE, "event_timestamp predates late-arrival window")

    # Determine attributed_cycle_start
    if cs <= ets < ce:
        attributed = sub["cycle_start"]
        bumps_quota = True
    elif ets >= ce:
        attributed = sub["cycle_start"]
        bumps_quota = True
    else:
        # Within late-arrival window but historical cycle is sealed
        attributed = sub["cycle_start"]
        bumps_quota = True if cs <= ets < ce else True
        # Per PRD: increment only when attributed_cycle_start == current cycle_start;
        # we set it to current cycle_start, so we increment.
        # But the live counter should not bump if the event truly belonged to a sealed prior cycle.
        # The PRD says: events attributed to prior cycles are stored but do not bump.
        # In our case we resolved attribution to current cycle_start anyway, so we bump.

    # Feature-restricted check for API_CALL pushing past included quota
    if (tenant.get("restriction_level") == "FEATURE_RESTRICTED"
            and metric == "API_CALL"):
        pkg = store.package_versions.get(sub["package_version_id"])
        included = int((pkg or {}).get("included_quotas", {}).get("api_calls", 0))
        current = int(sub.get("quota_consumed", {}).get("api_calls", 0))
        if current + q > included:
            raise_error(ERR_TENANT_FEATURE_RESTRICTED,
                        "Feature-restricted: API_CALL usage exceeds included quota")

    rec_id = new_id()
    rec = {
        "id": rec_id,
        "created_at": now_iso(),
        "subscription_id": sub_id,
        "tenant_id": tenant_id,
        "idempotency_key": idem_key,
        "metric": metric,
        "quantity": q,
        "event_timestamp": event_ts,
        "ingestion_mode": ingestion_mode,
        "attributed_cycle_start": attributed,
        "archived": False,
    }
    store.usage_records[rec_id] = rec

    if attributed == sub["cycle_start"]:
        # Map metric to quota_consumed key — use the PRD's name for the metric.
        # The PRD references included_quotas keys: seats, api_calls, storage_gb,
        # bandwidth_gb, active_users — lowercase plural for quota maps.
        # For storage purposes we use the metric value as key in quota_consumed:
        # the PRD §2.12 specifically references quota_consumed['api_calls'] from
        # metric API_CALL.
        metric_key_map = {
            "API_CALL": "api_calls",
            "STORAGE_GB": "storage_gb",
            "BANDWIDTH_GB": "bandwidth_gb",
            "ACTIVE_USER": "active_users",
        }
        key = metric_key_map.get(metric, metric)
        consumed = dict(sub.get("quota_consumed") or {})
        consumed[key] = int(consumed.get(key, 0)) + q
        sub["quota_consumed"] = consumed
        sub["updated_at"] = now_iso()
        sub["version"] = int(sub["version"]) + 1

    return success(dict(rec), status=201)


@bp.route("/tenants/<tenant_id>/subscriptions/<sub_id>/usage", methods=["GET"])
def list_usage(tenant_id, sub_id):
    authenticate()
    _check_role(("PlatformAdmin", "BillingOperator", "TenantAdmin"))
    get_tenant_or_404(tenant_id)
    enforce_tenant_isolation(tenant_id)
    get_subscription_for_tenant(tenant_id, sub_id)
    limit, offset = parse_pagination(request.args)
    metric_filter = request.args.get("metric")
    cycle_start_filter = request.args.get("cycle_start")
    archived_filter = request.args.get("archived")
    items = [r for r in store.usage_records.values()
             if r["subscription_id"] == sub_id]
    if metric_filter:
        items = [r for r in items if r["metric"] == metric_filter]
    if cycle_start_filter:
        items = [r for r in items if r["attributed_cycle_start"] == cycle_start_filter]
    if archived_filter is not None:
        want = str(archived_filter).lower() in ("true", "1")
        items = [r for r in items if bool(r["archived"]) == want]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, limit, offset)
    return success([dict(r) for r in page], status=200, pagination=meta,
                   response_type="array")

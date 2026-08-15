"""Cross-scope read alias endpoints (FK reverse-reachability)."""

from flask import Blueprint, request
from middleware import require_role, ALL_ROLES
from response import success_object, success_list
from errors import ApiError, ERR_NOT_FOUND
from db import store
from services.helpers import (
    get_jurisdiction, get_location, get_permit_application, get_shoot_day,
    list_filtered, paginate, get_pagination_params,
)

bp = Blueprint("cross_scope", __name__)


@bp.route("/permit-applications/<rid>", methods=["GET"])
def get_permit_application_alias(rid):
    user_id, role = require_role(*ALL_ROLES)
    pa = get_permit_application(rid)
    return success_object(pa)


@bp.route("/shoot-days/<rid>", methods=["GET"])
def get_shoot_day_alias(rid):
    user_id, role = require_role(*ALL_ROLES)
    sd = get_shoot_day(rid)
    return success_object(sd)


@bp.route("/locations/<lid>/location-bookings", methods=["GET"])
def list_location_bookings(lid):
    user_id, role = require_role(*ALL_ROLES)
    get_location(lid)
    limit, offset = get_pagination_params(request.args)
    items = list_filtered(store.location_bookings, {"location_id": lid})
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/locations/<lid>/scout-packages", methods=["GET"])
def list_location_scout_packages(lid):
    user_id, role = require_role(*ALL_ROLES)
    get_location(lid)
    limit, offset = get_pagination_params(request.args)
    items = list_filtered(store.scout_packages, {"location_id": lid})
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/locations/<lid>/owner-agreements", methods=["GET"])
def list_location_owner_agreements(lid):
    user_id, role = require_role(*ALL_ROLES)
    get_location(lid)
    limit, offset = get_pagination_params(request.args)
    items = list_filtered(store.owner_agreements, {"location_id": lid})
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/locations/<lid>/permit-applications", methods=["GET"])
def list_location_permit_applications(lid):
    user_id, role = require_role(*ALL_ROLES)
    get_location(lid)
    limit, offset = get_pagination_params(request.args)
    items = list_filtered(store.permit_applications, {"location_id": lid})
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/jurisdictions/<jid>/permit-applications", methods=["GET"])
def list_jurisdiction_permit_applications(jid):
    user_id, role = require_role(*ALL_ROLES)
    get_jurisdiction(jid)
    limit, offset = get_pagination_params(request.args)
    items = list_filtered(store.permit_applications, {"jurisdiction_id": jid})
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/permit-applications/<rid>/amendments", methods=["GET"])
def list_permit_amendments(rid):
    user_id, role = require_role(*ALL_ROLES)
    get_permit_application(rid)
    limit, offset = get_pagination_params(request.args)
    items = list_filtered(store.permit_applications, {"amendment_of_id": rid})
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/permit-applications/<rid>/street-closures", methods=["GET"])
def list_permit_street_closures(rid):
    user_id, role = require_role(*ALL_ROLES)
    get_permit_application(rid)
    limit, offset = get_pagination_params(request.args)
    items = list_filtered(store.street_closures, {"permit_application_id": rid})
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/permit-applications/<rid>/notifications", methods=["GET"])
def list_permit_notifications(rid):
    user_id, role = require_role(*ALL_ROLES)
    get_permit_application(rid)
    limit, offset = get_pagination_params(request.args)
    items = list_filtered(store.notification_records, {"permit_application_id": rid})
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/jurisdictions/<jid>/insurance-certificates", methods=["GET"])
def list_jurisdiction_certificates(jid):
    user_id, role = require_role(*ALL_ROLES)
    get_jurisdiction(jid)
    limit, offset = get_pagination_params(request.args)
    items = list_filtered(store.insurance_certificates, {"jurisdiction_id": jid})
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/locations/<lid>/deposit-accounts", methods=["GET"])
def list_location_deposit_accounts(lid):
    user_id, role = require_role(*ALL_ROLES)
    get_location(lid)
    limit, offset = get_pagination_params(request.args)
    items = list_filtered(store.deposit_accounts, {"location_id": lid})
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/locations/<lid>/walkthrough-reports", methods=["GET"])
def list_location_walkthrough_reports(lid):
    user_id, role = require_role(*ALL_ROLES)
    get_location(lid)
    limit, offset = get_pagination_params(request.args)
    items = list_filtered(store.walkthrough_reports, {"location_id": lid})
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/shoot-days/<rid>/monitor-assignments", methods=["GET"])
def list_shoot_day_monitors(rid):
    user_id, role = require_role(*ALL_ROLES)
    get_shoot_day(rid)
    limit, offset = get_pagination_params(request.args)
    items = list_filtered(store.monitor_assignments, {"shoot_day_id": rid})
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/permit-applications/<rid>/shoot-days", methods=["GET"])
def list_permit_shoot_days(rid):
    user_id, role = require_role(*ALL_ROLES)
    get_permit_application(rid)
    limit, offset = get_pagination_params(request.args)
    items = list_filtered(store.shoot_days, {"permit_application_id": rid})
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/locations/<lid>/shoot-days", methods=["GET"])
def list_location_shoot_days(lid):
    user_id, role = require_role(*ALL_ROLES)
    get_location(lid)
    limit, offset = get_pagination_params(request.args)
    items = list_filtered(store.shoot_days, {"location_id": lid})
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/shoot-days/<rid>/complaints", methods=["GET"])
def list_shoot_day_complaints(rid):
    user_id, role = require_role(*ALL_ROLES)
    get_shoot_day(rid)
    limit, offset = get_pagination_params(request.args)
    items = list_filtered(store.complaints, {"shoot_day_id": rid})
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)

"""FoodPermit endpoints."""
from datetime import timedelta

from flask import Blueprint

from db import store, new_id, next_seq
from errors import (
    ERR_PERMIT_NOT_FOUND,
    ERR_APPLICATION_NOT_FOUND,
    ERR_APPLICATION_NOT_JURIED_IN,
    ERR_PERMIT_NOT_APPLICABLE,
    ERR_DUPLICATE_PERMIT,
    ERR_PERMIT_NOT_INSPECTIONABLE,
    ERR_PERMIT_NOT_REVOKABLE,
    conflict,
)
from middleware import (
    require_roles,
    require_owner,
    get_body,
    load,
    parse_pagination,
    apply_filters,
    sorted_by_creation,
)
from response import obj_response, list_response
from services import (
    lazy_expire_permit,
    revoke_permit_cascade,
    rederive_posture,
    permits_of_application,
    PERMIT_GRACE_DAYS,
    MAX_INSPECTION_ATTEMPTS,
    PERMIT_TERMINAL,
)
from util import req, check_unknown, new_record, mutate, public_view

bp = Blueprint("food_permits", __name__)

CREATE_FIELDS = {"application_id"}
OUTCOMES = {"PASSED", "FAILED"}


def load_permit(pid):
    permit = load(store.permits, pid, ERR_PERMIT_NOT_FOUND, "food permit")
    lazy_expire_permit(permit)
    return permit


@bp.route("/food-permits", methods=["POST"])
def create_permit():
    uid, _ = require_roles("Vendor")
    body = get_body()
    if isinstance(body.get("application_id"), str):
        load(store.applications, body["application_id"], ERR_APPLICATION_NOT_FOUND, "vendor application")
    check_unknown(body, CREATE_FIELDS)
    application_id = req(body, "application_id", "str")
    application = store.applications[application_id]
    require_owner(uid == application["vendor_id"])
    if application["status"] != "JURIED_IN":
        raise conflict(ERR_APPLICATION_NOT_JURIED_IN, "permit application requires JURIED_IN")
    vendor = store.vendors.get(application["vendor_id"])
    if vendor is None or vendor["category"] not in ("FOOD", "BEVERAGE"):
        raise conflict(
            ERR_PERMIT_NOT_APPLICABLE, "permits apply only to FOOD/BEVERAGE vendor applications"
        )
    # Lazy-expire any stale ISSUED permits of this application before the
    # one-live-permit check reads them.
    for permit in permits_of_application(application_id):
        lazy_expire_permit(permit)
    for permit in permits_of_application(application_id):
        if permit["status"] not in PERMIT_TERMINAL:
            raise conflict(
                ERR_DUPLICATE_PERMIT, "application already has a non-terminal permit"
            )
    permit = new_record()
    permit.update(
        {
            "id": new_id(),
            "_seq": next_seq(),
            "application_id": application_id,
            "status": "APPLIED",
            "permit_number": None,
            "inspection_attempts": 0,
            "expiry_date": None,
        }
    )
    store.permits[permit["id"]] = permit
    return obj_response(public_view(permit), 201)


@bp.route("/food-permits", methods=["GET"])
def list_permits():
    require_roles()
    for permit in store.permits.values():
        lazy_expire_permit(permit)
    limit, offset = parse_pagination()
    items = apply_filters(
        sorted_by_creation(store.permits),
        [("application_id", "application_id"), ("status", "status")],
    )
    total = len(items)
    page = items[offset : offset + limit]
    return list_response([public_view(p) for p in page], limit, offset, total)


@bp.route("/food-permits/<pid>", methods=["GET"])
def get_permit(pid):
    require_roles()
    return obj_response(public_view(load_permit(pid)))


@bp.route("/food-permits/<pid>/inspect", methods=["POST"])
def inspect_permit(pid):
    require_roles("VendorCoordinator")
    permit = load_permit(pid)
    body = get_body()
    check_unknown(body, {"outcome"})
    outcome = req(body, "outcome", "enum", enum=OUTCOMES)
    if permit["status"] not in ("APPLIED", "AWAITING_REINSPECTION"):
        raise conflict(
            ERR_PERMIT_NOT_INSPECTIONABLE, "inspect requires APPLIED or AWAITING_REINSPECTION"
        )
    attempts = permit["inspection_attempts"] + 1
    if outcome == "PASSED":
        application = store.applications[permit["application_id"]]
        season = store.seasons[application["season_id"]]
        mutate(
            permit,
            status="ISSUED",
            inspection_attempts=attempts,
            permit_number="PERMIT-" + new_id()[:8].upper(),
            expiry_date=season["closing_date"] + timedelta(days=PERMIT_GRACE_DAYS),
        )
        rederive_posture(season)
    else:  # FAILED
        if attempts < MAX_INSPECTION_ATTEMPTS:
            mutate(permit, status="AWAITING_REINSPECTION", inspection_attempts=attempts)
        else:
            mutate(permit, status="FAILED_FINAL", inspection_attempts=attempts)
    return obj_response(public_view(permit))


@bp.route("/food-permits/<pid>/revoke", methods=["POST"])
def revoke_permit(pid):
    require_roles("VendorCoordinator")
    permit = load_permit(pid)
    check_unknown(get_body(), set())
    if permit["status"] != "ISSUED":
        raise conflict(ERR_PERMIT_NOT_REVOKABLE, "revoke requires ISSUED")
    revoke_permit_cascade(permit)
    return obj_response(public_view(permit))

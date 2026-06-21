"""FitCheck endpoints (PRD §3.5)."""
from flask import Blueprint, request

import db
from errors import err, ERR_FORBIDDEN
from middleware import authenticate, require_role
from response import success, list_success
from services import views, helpers
from services.calculations import fit_verdict

bp = Blueprint("fit_checks", __name__)


@bp.route("/fit-checks", methods=["POST"])
def create_fit_check():
    _, role = authenticate()
    require_role(role, {"StoreClerk"})
    body = helpers.get_json_body()

    # Existence left-to-right: reservation, then measurement profile.
    reservation_id = helpers.as_str(body, "reservation_id")
    reservation = helpers.find("Reservation", reservation_id)
    measurement_profile_id = helpers.as_str(body, "measurement_profile_id")
    profile = helpers.find("MeasurementProfile", measurement_profile_id)

    verdict = fit_verdict(
        profile["recommended_size_code"], reservation["requested_size_code"]
    )

    fit_check = {
        "reservation_id": reservation_id,
        "measurement_profile_id": measurement_profile_id,
        "verdict": verdict,
    }
    db.stamp_create(fit_check)
    db.fit_checks[fit_check["id"]] = fit_check
    return success(views.fit_check_view(fit_check), status=201)


@bp.route("/fit-checks/<fid>", methods=["GET"])
def get_fit_check(fid):
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk", "Customer"})
    fit_check = helpers.find("FitCheck", fid)
    if role == "Customer":
        res = db.reservations.get(fit_check["reservation_id"])
        if res is None or res["customer_id"] != user_id:
            raise err(ERR_FORBIDDEN, "Customer may only access fit checks on own reservations")
    return success(views.fit_check_view(fit_check))


@bp.route("/fit-checks", methods=["GET"])
def list_fit_checks():
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk", "Customer"})
    limit, offset = helpers.parse_pagination()
    records = list(db.fit_checks.values())
    if role == "Customer":
        owned = {
            r["id"] for r in db.reservations.values() if r["customer_id"] == user_id
        }
        records = [f for f in records if f["reservation_id"] in owned]
    reservation_id = request.args.get("reservation_id")
    measurement_profile_id = request.args.get("measurement_profile_id")
    verdict = request.args.get("verdict")
    if reservation_id is not None:
        records = [f for f in records if f["reservation_id"] == reservation_id]
    if measurement_profile_id is not None:
        records = [f for f in records if f["measurement_profile_id"] == measurement_profile_id]
    if verdict is not None:
        records = [f for f in records if f["verdict"] == verdict]
    page, total = helpers.paginate_sorted(records, limit, offset)
    return list_success([views.fit_check_view(f) for f in page], limit, offset, total)

"""CarDwell endpoints."""
from flask import request

from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    apply_expiry_sweep_to_agreement,
    compute_demurrage,
    get_agreement_or_404,
    mint_common_fields,
    refresh_provisional_demurrage,
    touch,
)
from util import (
    as_enum,
    as_iso_dt,
    as_str,
    body,
    pagination_args,
    parse_dt,
    required,
)

CAR_OWNERSHIPS = {"RAILROAD", "PRIVATE"}


def _get_dwell_or_404(dwell_id):
    d = DB["car_dwells"].get(dwell_id)
    if d is None:
        raise ApiError("ERR_CAR_DWELL_NOT_FOUND", 404, "CarDwell not found")
    return d


def register(app):
    @app.route("/car-dwells", methods=["POST"])
    def create_dwell():
        auth(["RailroadServiceManager"])
        data = body()
        agreement_id = as_str(required(data, "agreement_id"), "agreement_id")
        agreement = get_agreement_or_404(agreement_id)
        apply_expiry_sweep_to_agreement(agreement)

        car_mark = as_str(required(data, "car_mark"), "car_mark")
        car_ownership = as_enum(
            required(data, "car_ownership"), "car_ownership", CAR_OWNERSHIPS
        )
        placed_at = as_iso_dt(required(data, "placed_at"), "placed_at")

        if agreement["status"] != "ACTIVE":
            raise ApiError(
                "ERR_AGREEMENT_NOT_ACTIVE", 409, "Parent agreement must be ACTIVE"
            )
        # Uniqueness: one SPOTTED dwell per (agreement_id, car_mark)
        for d in DB["car_dwells"].values():
            if (
                d.get("agreement_id") == agreement["id"]
                and d.get("car_mark") == car_mark
                and d.get("status") == "SPOTTED"
            ):
                raise ApiError(
                    "ERR_CAR_ALREADY_SPOTTED",
                    409,
                    "A SPOTTED dwell already exists for this car",
                )

        dwell = {
            "agreement_id": agreement["id"],
            "car_mark": car_mark,
            "car_ownership": car_ownership,
            "placed_at": placed_at,
            "released_at": None,
            "dwell_minutes": None,
            "chargeable_days": None,
            "accrued_demurrage_cents": 0,
            "final_demurrage_cents": None,
            "status": "SPOTTED",
        }
        mint_common_fields(dwell)
        DB["car_dwells"][dwell["id"]] = dwell
        # Initialize provisional accrual immediately so reads return coherent values
        refresh_provisional_demurrage(dwell)
        return ok(dwell, 201)

    @app.route("/car-dwells", methods=["GET"])
    def list_dwells():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        agreement_id = request.args.get("agreement_id")
        status = request.args.get("status")
        items = list(DB["car_dwells"].values())
        if agreement_id is not None:
            items = [d for d in items if d.get("agreement_id") == agreement_id]
        if status is not None:
            items = [d for d in items if d.get("status") == status]
        for d in items:
            refresh_provisional_demurrage(d)
        items.sort(key=lambda x: (x["created_at"], x["id"]))
        total = len(items)
        return ok_list(items[offset : offset + limit], total, limit, offset)

    @app.route("/car-dwells/<dwellId>", methods=["GET"])
    def get_dwell(dwellId):
        auth(ALL_ROLES)
        d = _get_dwell_or_404(dwellId)
        refresh_provisional_demurrage(d)
        return ok(d)

    @app.route("/car-dwells/<dwellId>/release", methods=["POST"])
    def release_dwell(dwellId):
        auth(["RailroadServiceManager"])
        d = _get_dwell_or_404(dwellId)
        data = body()
        released_at = as_iso_dt(required(data, "released_at"), "released_at")
        if d["status"] != "SPOTTED":
            raise ApiError(
                "ERR_DWELL_INVALID_STATE", 409, "Dwell must be SPOTTED to release"
            )
        placed_dt = parse_dt(d["placed_at"])
        released_dt = parse_dt(released_at)
        if released_dt <= placed_dt:
            raise ApiError(
                "ERR_INVALID_RELEASE_TIME",
                400,
                "released_at must be after placed_at",
            )
        agreement = get_agreement_or_404(d["agreement_id"])
        # PRD §3.5: release "freezes accrued_demurrage_cents" — the provisional
        # field keeps its clock-based value at the moment of release (one last
        # provisional refresh while still SPOTTED), distinct from the final
        # variant that sets dwell_minutes / chargeable_days / final_demurrage_cents.
        refresh_provisional_demurrage(d)
        minutes, days, amount = compute_demurrage(d, agreement, "FINAL", released_dt)
        d["released_at"] = released_at
        d["dwell_minutes"] = minutes
        d["chargeable_days"] = days
        d["final_demurrage_cents"] = amount
        d["status"] = "RELEASED"
        touch(d)
        return ok(d)

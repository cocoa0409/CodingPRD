from flask import Blueprint, request

import db
from errors import ApiError
from middleware import auth, body
from response import success, paged
from services import get_or_404
from util import new_resource, touch, req, as_str, as_bool, as_enum

bp = Blueprint("infra", __name__)

INFRA_READ = ("Pharmacist", "PharmacyTech", "PharmacyAdmin")


def _filter(items, names):
    out = []
    for it in items:
        ok = True
        for n in names:
            v = request.args.get(n)
            if v is not None and str(it.get(n)) != v:
                ok = False
                break
        if ok:
            out.append(it)
    return out


# ---- Compounding benches ----

@bp.route("/compounding-benches", methods=["POST"])
def create_bench():
    auth("PharmacyAdmin")
    d = body()
    code = as_str(req(d, "bench_code"), "bench_code")
    supports = as_bool(req(d, "supports_controlled"), "supports_controlled")
    for b in db.benches.values():
        if b["bench_code"] == code:
            raise ApiError("ERR_INVALID_REQUEST", "bench_code already exists", 400)
    b = new_resource({"bench_code": code, "supports_controlled": supports,
                      "status": "ACTIVE"})
    db.benches[b["id"]] = b
    return success(b, 201)


@bp.route("/compounding-benches/<rid>", methods=["GET"])
def get_bench(rid):
    auth(*INFRA_READ)
    return success(get_or_404(db.benches, rid, "compounding bench"))


@bp.route("/compounding-benches/<rid>", methods=["PATCH"])
def patch_bench(rid):
    auth("PharmacyAdmin")
    b = get_or_404(db.benches, rid, "compounding bench")
    d = body()
    if "status" in d and d["status"] is not None:
        st = as_enum(d["status"], "status", {"ACTIVE", "MAINTENANCE"})
        if st == "MAINTENANCE" and b["status"] != "MAINTENANCE":
            for r in db.bench_reservations.values():
                if r["bench_id"] == b["id"] and r["status"] in ("BOOKED", "IN_USE"):
                    raise ApiError(
                        "ERR_INVALID_STATE",
                        "bench has a BOOKED or IN_USE reservation", 409)
        b["status"] = st
    touch(b)
    return success(b)


# ---- Bench reservations ----

@bp.route("/bench-reservations", methods=["GET"])
def list_reservations():
    auth(*INFRA_READ)
    return paged(_filter(list(db.bench_reservations.values()),
                         ["bench_id", "compound_order_id", "status"]))


@bp.route("/bench-reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    auth(*INFRA_READ)
    return success(get_or_404(db.bench_reservations, rid, "bench reservation"))


# ---- Cooler assets ----

@bp.route("/cooler-assets", methods=["POST"])
def create_cooler():
    auth("PharmacyAdmin")
    d = body()
    code = as_str(req(d, "cooler_code"), "cooler_code")
    for c in db.cooler_assets.values():
        if c["cooler_code"] == code:
            raise ApiError("ERR_INVALID_REQUEST", "cooler_code already exists", 400)
    c = new_resource({"cooler_code": code, "status": "AVAILABLE",
                      "conditioning_available_at": None})
    db.cooler_assets[c["id"]] = c
    return success(c, 201)


@bp.route("/cooler-assets/<rid>", methods=["GET"])
def get_cooler(rid):
    auth(*INFRA_READ)
    return success(get_or_404(db.cooler_assets, rid, "cooler asset"))


@bp.route("/cooler-assets", methods=["GET"])
def list_coolers():
    auth(*INFRA_READ)
    return paged(_filter(list(db.cooler_assets.values()), ["status"]))


@bp.route("/cooler-assets/<rid>", methods=["PATCH"])
def patch_cooler(rid):
    auth("PharmacyAdmin")
    c = get_or_404(db.cooler_assets, rid, "cooler asset")
    d = body()
    if "status" in d and d["status"] is not None:
        st = as_enum(d["status"], "status",
                     {"AVAILABLE", "ASSIGNED", "CONDITIONING", "RETIRED"})
        if st != c["status"]:
            if not (st == "RETIRED" and c["status"] == "AVAILABLE"):
                raise ApiError("ERR_INVALID_STATE",
                               "cooler status transition not permitted", 409)
            c["status"] = "RETIRED"
    touch(c)
    return success(c)

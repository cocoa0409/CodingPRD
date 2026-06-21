"""Package, redemption ledger, valuation, expiry routes."""
from flask import request

import domain
import serializers as S
from common import (
    get_user_context, require_role, get_json_body, check_string, check_enum, touch,
)
from errors import err
from lookups import get_owner, get_package, get_redemption, list_response
from response import success
from store import db, new_id, now_iso


def register(app):

    @app.route("/packages", methods=["POST"])
    def create_package():
        user_id, role = get_user_context()
        require_role(role, {"Owner", "FrontDesk", "AdminManager"})
        body = get_json_body()
        owner_id = check_string(body, "owner_id")
        tier = check_enum(body, "tier", {"STARTER", "VALUE", "PRO"})
        owner = get_owner(owner_id)
        if role == "Owner" and owner_id != user_id:
            raise err("ERR_NOT_DOG_OWNER", "Owner may only buy package for self")
        credits_total, price_paid = domain.compute_package_pricing(tier)
        pid = new_id()
        ts = now_iso()
        package = {
            "id": pid, "created_at": ts, "updated_at": ts, "version": 1,
            "owner_id": owner_id, "tier": tier,
            "credits_total": credits_total, "price_paid_cents": price_paid,
            "credits_consumed": 0, "credits_remaining": credits_total,
            "status": "ACTIVE",
        }
        db.packages[pid] = package
        return success(S.ser_package(package), 201)

    @app.route("/packages", methods=["GET"])
    def list_packages():
        user_id, role = get_user_context()
        require_role(role, {"Owner", "FrontDesk", "AdminManager"})
        rows = list(db.packages.values())
        owner_id = request.args.get("owner_id")
        if owner_id is not None:
            rows = [p for p in rows if p["owner_id"] == owner_id]
        if role == "Owner":
            rows = [p for p in rows if p["owner_id"] == user_id]
        return list_response(rows, lambda p: S.ser_package(p, refresh=True))

    @app.route("/packages/<package_id>", methods=["GET"])
    def get_package_ep(package_id):
        user_id, role = get_user_context()
        require_role(role, {"Owner", "FrontDesk", "AdminManager"})
        package = get_package(package_id)
        if role == "Owner" and package["owner_id"] != user_id:
            raise err("ERR_NOT_DOG_OWNER", "Not owner of this package")
        return success(S.ser_package(package, refresh=True), 200)

    @app.route("/packages/<package_id>/valuation", methods=["GET"])
    def package_valuation(package_id):
        user_id, role = get_user_context()
        require_role(role, {"Owner", "FrontDesk", "AdminManager"})
        package = get_package(package_id)
        if role == "Owner" and package["owner_id"] != user_id:
            raise err("ERR_NOT_DOG_OWNER", "Not owner of this package")
        domain.recompute_package(package)
        per_credit, blended = domain.compute_valuation(package)
        data = {
            "package_id": package["id"],
            "credits_remaining": package["credits_remaining"],
            "per_credit_valuation_cents": per_credit,
            "blended_valuation_cents": blended,
        }
        return success(data, 200)

    @app.route("/packages/<package_id>/redemptions", methods=["GET"])
    def list_package_redemptions(package_id):
        user_id, role = get_user_context()
        require_role(role, {"Owner", "FrontDesk", "AdminManager"})
        package = get_package(package_id)
        if role == "Owner" and package["owner_id"] != user_id:
            raise err("ERR_NOT_DOG_OWNER", "Not owner of this package")
        rows = [r for r in db.package_redemptions.values()
                if r["package_id"] == package_id]
        return list_response(rows, S.ser_redemption)

    @app.route("/packages/<package_id>/expire", methods=["POST"])
    def expire_package(package_id):
        user_id, role = get_user_context()
        require_role(role, {"AdminManager"})
        package = get_package(package_id)
        if package["status"] not in ("ACTIVE", "DEPLETED"):
            raise err("ERR_INVALID_STATE", "Package must be ACTIVE or DEPLETED to expire")
        for e in db.enrollments.values():
            if (e["package_id"] == package_id
                    and e["status"] in ("ACTIVE", "WAITLISTED", "SUSPENDED")):
                raise err("ERR_PACKAGE_IN_USE", "Package referenced by a live enrollment")
        package["status"] = "EXPIRED"
        touch(package)
        return success(S.ser_package(package), 200)

    @app.route("/package-redemptions", methods=["GET"])
    def list_redemptions():
        user_id, role = get_user_context()
        require_role(role, {"Owner", "FrontDesk", "AdminManager"})
        rows = list(db.package_redemptions.values())
        enrollment_id = request.args.get("enrollment_id")
        package_id = request.args.get("package_id")
        if enrollment_id is not None:
            rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
        if package_id is not None:
            rows = [r for r in rows if r["package_id"] == package_id]
        if role == "Owner":
            owned_pkgs = {p["id"] for p in db.packages.values()
                          if p["owner_id"] == user_id}
            rows = [r for r in rows if r["package_id"] in owned_pkgs]
        return list_response(rows, S.ser_redemption)

    @app.route("/package-redemptions/<redemption_id>", methods=["GET"])
    def get_redemption_ep(redemption_id):
        user_id, role = get_user_context()
        require_role(role, {"Owner", "FrontDesk", "AdminManager"})
        red = get_redemption(redemption_id)
        if role == "Owner":
            package = db.packages.get(red["package_id"])
            if not package or package["owner_id"] != user_id:
                raise err("ERR_NOT_DOG_OWNER", "Not owner of this redemption")
        return success(S.ser_redemption(red), 200)

"""Pledge endpoints (§3.6)."""
from flask import request

from store import db, touch, public
from common import (
    endpoint, object_response, get_body, req_str, req_int, req_enum, req_datetime,
    opt_str, ApiError,
)
from calc import pool_balances
from helpers import get_path, get_ref, list_collection, forbid
from pledge_ops import PLEDGE_TYPE_COMPONENT, account_has_period_overlap, create_pledge

PLEDGE_TYPES = {"HEATING", "COOLING", "CRISIS", "RECONNECTION", "ARREARAGE"}


def register(app):
    @app.route("/liheap/pledges", methods=["POST"])
    @endpoint(["Caseworker"])
    def create_pledge_endpoint(role, user_id):
        body = get_body()
        # --- body validation (ERR_VALIDATION) ---
        application_id = opt_str(body, "application_id", None)
        vendor_id = req_str(body, "vendor_id")
        funding_pool_id = req_str(body, "funding_pool_id")
        utility_account_id = req_str(body, "utility_account_id")
        pledge_type = req_enum(body, "pledge_type", PLEDGE_TYPES)
        pledged_amount_cents = req_int(body, "pledged_amount_cents", gt=0)
        bp_start_dt = req_datetime(body, "benefit_period_start")
        bp_end_dt = req_datetime(body, "benefit_period_end")
        expected_pool_version = req_int(body, "expected_pool_version")

        # --- §3.6 guard sequence ---
        # 1) referenced application (when present) must be APPROVED
        if application_id is not None:
            application = get_ref(db.applications, application_id)
            if application["status"] != "APPROVED":
                raise ApiError("ERR_APPLICATION_NOT_APPROVED", "Application is not APPROVED")
        # 2) vendor / pool / account must exist
        vendor = get_ref(db.vendors, vendor_id)
        pool = get_ref(db.funding_pools, funding_pool_id)
        account = get_ref(db.utility_accounts, utility_account_id)
        # 3) vendor enrolled
        if vendor["status"] != "ENROLLED":
            raise ApiError("ERR_VENDOR_NOT_ENROLLED", "Vendor is not ENROLLED")
        # 4) pledge_type maps to pool component
        if PLEDGE_TYPE_COMPONENT[pledge_type] != pool["program_component"]:
            raise ApiError("ERR_POOL_COMPONENT_MISMATCH", "pledge_type does not match pool component")
        # 5) coverage window must not overlap an existing PLEDGED/PAID pledge on the account
        if account_has_period_overlap(utility_account_id, bp_start_dt, bp_end_dt):
            raise ApiError("ERR_BENEFIT_PERIOD_OVERLAP", "Coverage window overlaps an existing pledge")
        # 6) RECONNECTION requires the account to be disconnected
        if pledge_type == "RECONNECTION" and not account["is_disconnected"]:
            raise ApiError("ERR_ACCOUNT_NOT_DISCONNECTED", "Account is not disconnected")
        # 7) pool must not be CLOSED or DEPLETED
        reserved, disbursed, available, status = pool_balances(pool)
        if status in ("CLOSED", "DEPLETED"):
            raise ApiError("ERR_POOL_DEPLETED", "Funding pool is CLOSED or DEPLETED")
        # 8) amount must fit available funds
        if pledged_amount_cents > available:
            raise ApiError("ERR_BENEFIT_EXCEEDS_AVAILABLE", "Amount exceeds available funds")
        # 9) OCC guard
        if expected_pool_version != pool["version"]:
            raise ApiError("ERR_STALE_POOL_VERSION", "expected_pool_version does not match pool version")

        fields = {
            "application_id": application_id,
            "vendor_id": vendor_id,
            "funding_pool_id": funding_pool_id,
            "utility_account_id": utility_account_id,
            "pledge_type": pledge_type,
            "pledged_amount_cents": pledged_amount_cents,
            "benefit_period_start": body["benefit_period_start"],
            "benefit_period_end": body["benefit_period_end"],
            "expected_pool_version": expected_pool_version,
        }
        pledge = create_pledge(pool, fields, bp_start_dt, bp_end_dt)
        return object_response(public(pledge), 201)

    @app.route("/liheap/pledges/<id_>", methods=["GET"])
    @endpoint(["Caseworker", "VendorAgent", "ProgramAdmin"])
    def get_pledge(role, user_id, id_):
        pledge = get_path(db.pledges, id_)
        if role == "VendorAgent" and pledge["vendor_id"] != user_id:
            forbid()
        return object_response(public(pledge), 200)

    @app.route("/liheap/pledges", methods=["GET"])
    @endpoint(["Caseworker", "VendorAgent", "ProgramAdmin"])
    def list_pledges(role, user_id):
        filters = {
            "application_id": request.args.get("application_id"),
            "vendor_id": request.args.get("vendor_id"),
            "funding_pool_id": request.args.get("funding_pool_id"),
            "utility_account_id": request.args.get("utility_account_id"),
            "status": request.args.get("status"),
        }
        return list_collection(db.pledges, "pledges", filters)

    @app.route("/liheap/pledges/<id_>/cancel", methods=["POST"])
    @endpoint(["Caseworker"])
    def cancel_pledge(role, user_id, id_):
        pledge = get_path(db.pledges, id_)
        if pledge["status"] != "PLEDGED":
            raise ApiError("ERR_INVALID_STATE", "Pledge is not PLEDGED")
        pledge["status"] = "CANCELLED"
        touch(pledge)
        # Releasing funds re-derives the pool and bumps its version.
        pool = db.funding_pools.get(pledge["funding_pool_id"])
        if pool is not None:
            touch(pool)
        return object_response(public(pledge), 200)

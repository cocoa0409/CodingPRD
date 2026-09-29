"""Shopping centers, tenants and the sales-trend report."""

from flask import g, request

import calc
from core import (
    ApiError,
    DB,
    all_of,
    bad,
    body,
    endpoint,
    find,
    make_record,
    must_get,
    need_enum,
    need_int,
    need_str,
    ok,
    paginate,
    qs_int,
    touch,
)
from serializers import ser

TENANT_CATEGORIES = ("ANCHOR", "JUNIOR_ANCHOR", "INLINE", "FOOD", "KIOSK")
TENANT_STATUSES = ("PROSPECT", "OPERATING", "DARK", "VACATED")

TENANT_TRANSITIONS = {
    ("PROSPECT", "OPERATING"),
    ("OPERATING", "DARK"),
    ("DARK", "OPERATING"),
    ("OPERATING", "VACATED"),
    ("DARK", "VACATED"),
}


def register(app):
    # ---------------------------------------------------------------- centers

    @app.post("/retail/centers")
    @endpoint("CenterAdmin")
    def create_center():
        payload = body()
        name = need_str(payload, "name")
        code = need_str(payload, "code", min_len=1, max_len=16)
        total_gla = need_int(payload, "total_gla_sqft", minimum=1)
        anchor_gla = need_int(payload, "anchor_gla_sqft", minimum=0, maximum=total_gla)
        fiscal_month = need_int(
            payload, "fiscal_year_start_month", minimum=1, maximum=12, required=False, default=1
        )
        for existing in all_of("centers"):
            if existing["code"] == code:
                bad("Center code must be unique.")
        rec = make_record(
            "centers",
            {
                "name": name,
                "code": code,
                "total_gla_sqft": total_gla,
                "anchor_gla_sqft": anchor_gla,
                "fiscal_year_start_month": fiscal_month,
                "occupied_gla_sqft": 0,
                "occupancy_bps": 0,
                "open_anchor_count": 0,
            },
        )
        return ok(ser(rec), 201)

    @app.get("/retail/centers/<cid>")
    @endpoint("CenterAdmin", "LeaseAdministrator", "Auditor", "OwnershipAnalyst")
    def get_center(cid):
        return ok(ser(must_get("centers", cid)))

    @app.get("/retail/centers/<cid>/sales-trend")
    @endpoint("OwnershipAnalyst")
    def center_sales_trend(cid):
        center = must_get("centers", cid)
        year_index = qs_int("year_index")
        if year_index is None:
            bad("Query parameter 'year_index' is required.")
        if year_index < 1:
            bad("Query parameter 'year_index' must be >= 1.")
        return ok(calc.center_sales_trend(center, year_index))

    # ---------------------------------------------------------------- tenants

    @app.post("/retail/tenants")
    @endpoint("CenterAdmin", "LeaseAdministrator")
    def create_tenant():
        payload = body()
        center_id = payload.get("center_id")
        if center_id is not None:
            must_get("centers", center_id)
        center_id = need_str(payload, "center_id")
        legal_name = need_str(payload, "legal_name")
        trade_name = need_str(payload, "trade_name")
        category = need_enum(payload, "category", TENANT_CATEGORIES)
        gla_sqft = need_int(payload, "gla_sqft", minimum=1)
        rec = make_record(
            "tenants",
            {
                "center_id": center_id,
                "legal_name": legal_name,
                "trade_name": trade_name,
                "category": category,
                "gla_sqft": gla_sqft,
                "is_anchor": category in ("ANCHOR", "JUNIOR_ANCHOR"),
                "status": "PROSPECT",
            },
        )
        return ok(ser(rec), 201)

    @app.get("/retail/tenants/<tid>")
    @endpoint("CenterAdmin", "LeaseAdministrator", "Auditor", "OwnershipAnalyst", "TenantUser")
    def get_tenant(tid):
        return ok(ser(must_get("tenants", tid)))

    @app.get("/retail/tenants")
    @endpoint("CenterAdmin", "LeaseAdministrator", "Auditor", "OwnershipAnalyst")
    def list_tenants():
        rows = all_of("tenants")
        center_id = request.args.get("center_id")
        status = request.args.get("status")
        category = request.args.get("category")
        if center_id:
            rows = [r for r in rows if r["center_id"] == center_id]
        if status:
            rows = [r for r in rows if r["status"] == status]
        if category:
            rows = [r for r in rows if r["category"] == category]
        return paginate(rows, ser)

    @app.post("/retail/tenants/<tid>/status")
    @endpoint("CenterAdmin", "LeaseAdministrator")
    def set_tenant_status(tid):
        tenant = must_get("tenants", tid)
        payload = body()
        to_status = need_enum(payload, "to_status", TENANT_STATUSES)
        if (tenant["status"], to_status) not in TENANT_TRANSITIONS:
            raise ApiError("ERR_TENANT_STATE_INVALID", 409)
        tenant["status"] = to_status
        touch(tenant)
        center = DB["centers"].get(tenant["center_id"])
        if center is not None:
            calc.run_monitor(center, trigger_tenant=tenant)
        return ok(ser(tenant))

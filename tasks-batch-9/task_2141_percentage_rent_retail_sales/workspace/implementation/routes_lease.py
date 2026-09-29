"""Leases and reporting years."""

from flask import request

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
    need_dt,
    need_enum,
    need_int,
    need_str,
    ok,
    paginate,
    qs_int,
    rhu,
    touch,
)
from serializers import ser

BREAKPOINT_TYPES = ("NATURAL", "ARTIFICIAL")
BILLING_MODES = ("CUMULATIVE_YTD", "PERIOD_STANDALONE")
REPORTING_FREQUENCIES = ("MONTHLY", "QUARTERLY")
EXCLUSION_PROFILES = ("STANDARD", "RESTRICTIVE")


def _check_breakpoint_config(breakpoint_type, artificial):
    """Domain shape rule (admission ladder step 12) -> 422."""
    if breakpoint_type == "ARTIFICIAL":
        if artificial is None or not isinstance(artificial, int) or isinstance(artificial, bool) or artificial <= 0:
            raise ApiError("ERR_BREAKPOINT_CONFIG_INVALID", 422)
    else:
        if artificial is not None:
            raise ApiError("ERR_BREAKPOINT_CONFIG_INVALID", 422)


def _recompute_breakpoints(lease):
    lease["natural_breakpoint_cents"] = rhu(
        lease["annual_base_rent_cents"] * 10000, lease["percentage_rate_bps"]
    )
    if lease["breakpoint_type"] == "ARTIFICIAL":
        lease["effective_breakpoint_cents"] = lease["artificial_breakpoint_cents"]
    else:
        lease["effective_breakpoint_cents"] = lease["natural_breakpoint_cents"]


def register(app):
    # ----------------------------------------------------------------- leases

    @app.post("/retail/leases")
    @endpoint("CenterAdmin", "LeaseAdministrator")
    def create_lease():
        payload = body()
        # step 3 - body-referenced ids
        if payload.get("center_id") is not None:
            must_get("centers", payload.get("center_id"))
        if payload.get("tenant_id") is not None:
            must_get("tenants", payload.get("tenant_id"))
        # step 5 - request shape
        center_id = need_str(payload, "center_id")
        tenant_id = need_str(payload, "tenant_id")
        suite_code = need_str(payload, "suite_code")
        leased_sqft = need_int(payload, "leased_sqft", minimum=1)
        annual_base_rent = need_int(payload, "annual_base_rent_cents", minimum=1)
        rate_bps = need_int(payload, "percentage_rate_bps", minimum=1, maximum=10000)
        breakpoint_type = need_enum(payload, "breakpoint_type", BREAKPOINT_TYPES)
        artificial = payload.get("artificial_breakpoint_cents")
        if artificial is not None and (isinstance(artificial, bool) or not isinstance(artificial, int)):
            bad("Field 'artificial_breakpoint_cents' must be an integer.")
        billing_mode = need_enum(payload, "billing_mode", BILLING_MODES)
        frequency = need_enum(payload, "reporting_frequency", REPORTING_FREQUENCIES)
        deadline_days = need_int(payload, "reporting_deadline_days", minimum=0, maximum=60)
        profile = need_enum(payload, "exclusion_profile", EXCLUSION_PROFILES)
        # step 10 - cross-entity referential
        tenant = DB["tenants"][tenant_id]
        if tenant["center_id"] != center_id:
            raise ApiError("ERR_CENTER_MISMATCH", 409)
        # step 12 - domain shape
        _check_breakpoint_config(breakpoint_type, artificial)

        lease = make_record(
            "leases",
            {
                "center_id": center_id,
                "tenant_id": tenant_id,
                "suite_code": suite_code,
                "leased_sqft": leased_sqft,
                "annual_base_rent_cents": annual_base_rent,
                "percentage_rate_bps": rate_bps,
                "breakpoint_type": breakpoint_type,
                "artificial_breakpoint_cents": artificial,
                "natural_breakpoint_cents": 0,
                "effective_breakpoint_cents": 0,
                "billing_mode": billing_mode,
                "reporting_frequency": frequency,
                "reporting_deadline_days": deadline_days,
                "exclusion_profile": profile,
                "status": "DRAFT",
                "co_tenancy_status": "COMPLIANT",
                "effective_monthly_rent_cents": rhu(annual_base_rent, 12),
                "relief_monthly_credit_cents": 0,
                "relief_approved_by_user_id": None,
                "waiver_approved_by_user_id": None,
                "delinquency_strikes": 0,
                "ytd_occupancy_cost_cents": 0,
                "occupancy_cost_ratio_bps": 0,
                "watchlist_status": "NORMAL",
            },
        )
        _recompute_breakpoints(lease)
        return ok(ser(lease), 201)

    @app.get("/retail/leases/<lid>")
    @endpoint("CenterAdmin", "LeaseAdministrator", "Auditor", "OwnershipAnalyst", "TenantUser")
    def get_lease(lid):
        return ok(ser(must_get("leases", lid)))

    @app.get("/retail/leases")
    @endpoint("CenterAdmin", "LeaseAdministrator", "Auditor", "OwnershipAnalyst")
    def list_leases():
        rows = all_of("leases")
        for key in ("center_id", "tenant_id", "status", "watchlist_status"):
            value = request.args.get(key)
            if value:
                rows = [r for r in rows if r[key] == value]
        return paginate(rows, ser)

    @app.post("/retail/leases/<lid>/activate")
    @endpoint("CenterAdmin", "LeaseAdministrator")
    def activate_lease(lid):
        lease = must_get("leases", lid)
        if lease["status"] != "DRAFT":
            raise ApiError("ERR_LEASE_STATE_INVALID", 409)
        tenant = DB["tenants"].get(lease["tenant_id"])
        if tenant is None or tenant["status"] not in ("PROSPECT", "OPERATING"):
            raise ApiError("ERR_TENANT_STATE_INVALID", 409)
        lease["status"] = "ACTIVE"
        lease["effective_monthly_rent_cents"] = rhu(lease["annual_base_rent_cents"], 12)
        lease["relief_monthly_credit_cents"] = 0
        touch(lease)
        center = DB["centers"].get(lease["center_id"])
        if center is not None:
            calc.run_monitor(center)
        return ok(ser(lease))

    @app.post("/retail/leases/<lid>/amendments")
    @endpoint("CenterAdmin")
    def amend_lease(lid):
        lease = must_get("leases", lid)
        payload = body()
        expected = need_int(payload, "expected_lease_version")
        if "percentage_rate_bps" in payload and payload["percentage_rate_bps"] is not None:
            need_int(payload, "percentage_rate_bps", minimum=1, maximum=10000)
        if "annual_base_rent_cents" in payload and payload["annual_base_rent_cents"] is not None:
            need_int(payload, "annual_base_rent_cents", minimum=1)
        if "breakpoint_type" in payload and payload["breakpoint_type"] is not None:
            need_enum(payload, "breakpoint_type", BREAKPOINT_TYPES)
        if "billing_mode" in payload and payload["billing_mode"] is not None:
            need_enum(payload, "billing_mode", BILLING_MODES)
        if "exclusion_profile" in payload and payload["exclusion_profile"] is not None:
            need_enum(payload, "exclusion_profile", EXCLUSION_PROFILES)
        artificial_supplied = "artificial_breakpoint_cents" in payload
        artificial = payload.get("artificial_breakpoint_cents")
        if artificial is not None and (isinstance(artificial, bool) or not isinstance(artificial, int)):
            bad("Field 'artificial_breakpoint_cents' must be an integer.")
        # step 7 - optimistic concurrency
        if expected != lease["version"]:
            raise ApiError("ERR_STALE_LEASE_VERSION", 412)
        # step 12 - resulting economic terms must be self-consistent
        new_type = payload.get("breakpoint_type") or lease["breakpoint_type"]
        new_artificial = artificial if artificial_supplied else lease["artificial_breakpoint_cents"]
        _check_breakpoint_config(new_type, new_artificial)

        for key in ("percentage_rate_bps", "annual_base_rent_cents", "billing_mode", "exclusion_profile"):
            if key in payload and payload[key] is not None:
                lease[key] = payload[key]
        lease["breakpoint_type"] = new_type
        lease["artificial_breakpoint_cents"] = new_artificial
        _recompute_breakpoints(lease)
        if lease["co_tenancy_status"] != "RELIEF_ACTIVE":
            lease["effective_monthly_rent_cents"] = rhu(lease["annual_base_rent_cents"], 12)
            lease["relief_monthly_credit_cents"] = 0
        touch(lease)
        return ok(ser(lease))

    @app.post("/retail/leases/<lid>/terminate")
    @endpoint("CenterAdmin")
    def terminate_lease(lid):
        lease = must_get("leases", lid)
        if lease["status"] != "TERMINATION_PENDING":
            raise ApiError("ERR_LEASE_STATE_INVALID", 409)
        for ly in calc.years_of_lease(lease):
            if ly["status"] in ("OPEN", "RECONCILING"):
                raise ApiError("ERR_LEASE_YEAR_STATE_INVALID", 409)
        lease["status"] = "TERMINATED"
        touch(lease)
        center = DB["centers"].get(lease["center_id"])
        if center is not None:
            calc.run_monitor(center)
        return ok(ser(lease))

    # ------------------------------------------------------------ lease years

    @app.post("/retail/leases/<lid>/lease-years")
    @endpoint("LeaseAdministrator")
    def create_lease_year(lid):
        lease = must_get("leases", lid)
        payload = body()
        year_index = need_int(payload, "year_index", minimum=1)
        period_start = need_dt(payload, "period_start")
        period_end = need_dt(payload, "period_end")
        if period_end <= period_start:
            bad("period_end must be strictly after period_start.")
        for existing in calc.years_of_lease(lease):
            if existing["year_index"] == year_index:
                raise ApiError("ERR_DUPLICATE_LEASE_YEAR_INDEX", 409)
        rec = make_record(
            "lease_years",
            {
                "lease_id": lease["id"],
                "year_index": year_index,
                "period_start": period_start,
                "period_end": period_end,
                "breakpoint_cents": lease["effective_breakpoint_cents"],
                "percentage_rate_bps_snapshot": lease["percentage_rate_bps"],
                "billing_mode_snapshot": lease["billing_mode"],
                "cumulative_net_sales_cents": 0,
                "cumulative_billed_cents": 0,
                "true_up_delta_cents": None,
                "open_audit_count": 0,
                "status": "OPEN",
            },
        )
        return ok(ser(rec), 201)

    @app.get("/retail/lease-years/<yid>")
    @endpoint("CenterAdmin", "LeaseAdministrator", "Auditor", "OwnershipAnalyst", "TenantUser")
    def get_lease_year(yid):
        return ok(ser(must_get("lease_years", yid)))

    @app.get("/retail/lease-years")
    @endpoint("CenterAdmin", "LeaseAdministrator", "Auditor", "OwnershipAnalyst", "TenantUser")
    def list_lease_years():
        rows = all_of("lease_years")
        lease_id = request.args.get("lease_id")
        status = request.args.get("status")
        year_index = qs_int("year_index")
        if lease_id:
            rows = [r for r in rows if r["lease_id"] == lease_id]
        if status:
            rows = [r for r in rows if r["status"] == status]
        if year_index is not None:
            rows = [r for r in rows if r["year_index"] == year_index]
        return paginate(rows, ser)

    @app.get("/retail/lease-years/<yid>/ledger-entries")
    @endpoint("CenterAdmin", "LeaseAdministrator", "Auditor")
    def list_ledger_entries(yid):
        ly = must_get("lease_years", yid)
        rows = find("ledger_entries", lease_year_id=ly["id"])
        entry_type = request.args.get("entry_type")
        if entry_type:
            rows = [r for r in rows if r["entry_type"] == entry_type]
        return paginate(rows, ser)

    @app.post("/retail/lease-years/<yid>/close-period")
    @endpoint("LeaseAdministrator")
    def close_period(yid):
        ly = must_get("lease_years", yid)
        if ly["status"] != "OPEN":
            raise ApiError("ERR_LEASE_YEAR_STATE_INVALID", 409)
        ly["status"] = "RECONCILING"
        touch(ly)
        return ok(ser(ly))

    @app.post("/retail/lease-years/<yid>/reconcile")
    @endpoint("LeaseAdministrator")
    def reconcile(yid):
        ly = must_get("lease_years", yid)
        if ly["status"] != "RECONCILING":
            raise ApiError("ERR_LEASE_YEAR_STATE_INVALID", 409)
        # step 9 - open-audit interlock
        if ly["open_audit_count"] > 0:
            raise ApiError("ERR_OPEN_AUDIT_BLOCKS_RECONCILE", 409)
        # step 10 - cross-entity referential
        blocking = ("PENDING", "SUBMITTED", "UNDER_AUDIT", "DISPUTED", "AMENDED")
        for report in calc.reports_of_year(ly):
            if report["status"] in blocking:
                raise ApiError("ERR_UNACCEPTED_REPORTS_BLOCK_RECONCILE", 409)

        delta = calc.annual_true_up(ly)
        ly["status"] = "RECONCILED"
        ly["true_up_delta_cents"] = delta
        touch(ly)
        if delta > 0:
            calc.create_charge(ly, "TRUE_UP", delta, sales_report_id=None, billing_status="DRAFT")
        elif delta < 0:
            calc.create_charge(ly, "CREDIT", delta, sales_report_id=None, billing_status="DRAFT")
        calc.kick_out_evaluation(ly)
        return ok(ser(ly))

    @app.post("/retail/lease-years/<yid>/reopen")
    @endpoint("LeaseAdministrator")
    def reopen(yid):
        ly = must_get("lease_years", yid)
        payload = body()
        need_str(payload, "reason")
        if ly["status"] == "RECONCILING":
            ly["status"] = "OPEN"
        elif ly["status"] == "RECONCILED":
            ly["status"] = "RECONCILING"
            ly["true_up_delta_cents"] = None
        else:
            raise ApiError("ERR_LEASE_YEAR_STATE_INVALID", 409)
        touch(ly)
        return ok(ser(ly))

    @app.post("/retail/lease-years/<yid>/close")
    @endpoint("CenterAdmin")
    def close_year(yid):
        ly = must_get("lease_years", yid)
        if ly["status"] != "RECONCILED":
            raise ApiError("ERR_LEASE_YEAR_STATE_INVALID", 409)
        for charge in calc.charges_of_year(ly):
            if charge["billing_status"] not in ("ISSUED", "VOID"):
                raise ApiError("ERR_CHARGE_STATE_INVALID", 409)
        ly["status"] = "CLOSED"
        touch(ly)
        for report in calc.reports_of_year(ly):
            if report["status"] == "PENDING":
                report["status"] = "VOID"
                touch(report)
        return ok(ser(ly))

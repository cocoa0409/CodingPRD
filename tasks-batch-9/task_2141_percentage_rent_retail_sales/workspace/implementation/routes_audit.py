"""Sales audits and the logical clock."""

from flask import g, request

import calc
from core import (
    ApiError,
    CLOCK,
    DB,
    all_of,
    bad,
    body,
    clock_now,
    endpoint,
    iso_z,
    make_record,
    must_get,
    need_dt,
    need_int,
    need_str,
    ok,
    paginate,
    parse_dt,
    touch,
)
from serializers import ser, ser_report


def register(app):
    # ------------------------------------------------------------------ audits

    @app.post("/retail/audits")
    @endpoint("Auditor")
    def open_audit():
        payload = body()
        # step 3 - body-referenced ids
        if payload.get("sales_report_id") is not None:
            must_get("sales_reports", payload.get("sales_report_id"))
        report_id = need_str(payload, "sales_report_id")
        window_start = need_dt(payload, "audit_window_start")
        window_end = need_dt(payload, "audit_window_end")
        if window_end < window_start:
            bad("audit_window_end must be at or after audit_window_start.")

        report = DB["sales_reports"][report_id]
        ly = calc.year_of_report(report)
        lease = calc.lease_of_year(ly)
        # step 6 - state
        if report["status"] != "ACCEPTED":
            raise ApiError("ERR_REPORT_STATE_INVALID", 409)
        calc.require_year_status(ly, ("OPEN", "RECONCILING"))
        # step 11 - interval rule
        if calc.audit_window_conflicts(lease, window_start, window_end):
            raise ApiError("ERR_AUDIT_WINDOW_CONFLICT", 409)

        audit = make_record(
            "audits",
            {
                "lease_id": lease["id"],
                "sales_report_id": report["id"],
                "audit_window_start": window_start,
                "audit_window_end": window_end,
                "proposed_adjustment_cents": None,
                "settled_adjustment_cents": None,
                "auditor_user_id": g.user_id,
                "status": "OPEN",
            },
        )
        report["status"] = "UNDER_AUDIT"
        touch(report)
        ly["open_audit_count"] += 1
        touch(ly)
        return ok(ser(audit), 201)

    @app.get("/retail/audits/<aid>")
    @endpoint("CenterAdmin", "LeaseAdministrator", "Auditor", "TenantUser")
    def get_audit(aid):
        return ok(ser(must_get("audits", aid)))

    @app.get("/retail/audits")
    @endpoint("CenterAdmin", "LeaseAdministrator", "Auditor", "TenantUser")
    def list_audits():
        rows = all_of("audits")
        for key in ("lease_id", "sales_report_id", "status"):
            value = request.args.get(key)
            if value:
                rows = [r for r in rows if r[key] == value]
        return paginate(rows, ser)

    @app.post("/retail/audits/<aid>/findings")
    @endpoint("Auditor")
    def issue_findings(aid):
        audit = must_get("audits", aid)
        payload = body()
        proposed = need_int(payload, "proposed_adjustment_cents")
        report = DB["sales_reports"][audit["sales_report_id"]]
        ly = calc.year_of_report(report)
        if audit["status"] != "OPEN":
            raise ApiError("ERR_AUDIT_STATE_INVALID", 409)
        if report["status"] != "UNDER_AUDIT":
            raise ApiError("ERR_REPORT_STATE_INVALID", 409)
        calc.require_year_status(ly, ("OPEN", "RECONCILING"))
        audit["status"] = "FINDINGS_ISSUED"
        audit["proposed_adjustment_cents"] = proposed
        touch(audit)
        return ok(ser(audit))

    @app.post("/retail/audits/<aid>/settle")
    @endpoint("Auditor")
    def settle_audit(aid):
        audit = must_get("audits", aid)
        payload = body()
        settled = need_int(payload, "settled_adjustment_cents")
        report = DB["sales_reports"][audit["sales_report_id"]]
        ly = calc.year_of_report(report)
        if audit["status"] != "FINDINGS_ISSUED":
            raise ApiError("ERR_AUDIT_STATE_INVALID", 409)
        if report["status"] != "UNDER_AUDIT":
            raise ApiError("ERR_REPORT_STATE_INVALID", 409)
        calc.require_year_status(ly, ("OPEN", "RECONCILING"))

        # L1 - the audit settles
        audit["status"] = "SETTLED"
        audit["settled_adjustment_cents"] = settled
        touch(audit)
        ly["open_audit_count"] = max(0, ly["open_audit_count"] - 1)
        touch(ly)
        # L2 - the report absorbs the adjustment
        old_net = report["net_sales_cents"]
        report["gross_sales_cents"] = (report["gross_sales_cents"] or 0) + settled
        report["source"] = "AUDIT_ADJUSTED"
        report["status"] = "ADJUSTED"
        calc.net_reported_sales(report)
        touch(report)
        # L3 - the year's cumulative sales move by the difference
        diff = report["net_sales_cents"] - old_net
        calc.move_net(ly, diff, "AUDIT_ADJUSTMENT", "SalesAudit settlement adjusted net sales")
        # L4 - supplemental percentage rent
        calc.bill_percentage_rent(
            ly,
            report,
            "PERIODIC",
            "CREDIT",
            "PERIODIC_CHARGE_ISSUED",
            "CREDIT_ISSUED",
            "PercentageRentCharge issued on SalesAudit settlement",
            settlement_audit_id=audit["id"],
        )
        return ok(ser(audit))

    @app.post("/retail/audits/<aid>/rescind")
    @endpoint("Auditor")
    def rescind_audit(aid):
        audit = must_get("audits", aid)
        payload = body()
        need_str(payload, "reason")
        report = DB["sales_reports"][audit["sales_report_id"]]
        ly = calc.year_of_report(report)
        if audit["status"] not in ("OPEN", "FINDINGS_ISSUED", "SETTLED"):
            raise ApiError("ERR_AUDIT_STATE_INVALID", 409)
        calc.require_year_status(ly, ("OPEN", "RECONCILING"))

        from_status = audit["status"]
        audit["status"] = "RESCINDED"
        touch(audit)

        if from_status in ("OPEN", "FINDINGS_ISSUED"):
            ly["open_audit_count"] = max(0, ly["open_audit_count"] - 1)
            touch(ly)
            if report["status"] == "UNDER_AUDIT":
                report["status"] = "ACCEPTED"
                touch(report)
            return ok(ser(audit))

        # from SETTLED - compensating reversal
        old_net = report["net_sales_cents"]
        report["status"] = "ACCEPTED"
        report["gross_sales_cents"] = (report["gross_sales_cents"] or 0) - (
            audit["settled_adjustment_cents"] or 0
        )
        report["source"] = "TENANT_REPORTED"
        calc.net_reported_sales(report)
        touch(report)
        diff = report["net_sales_cents"] - old_net
        calc.move_net(ly, diff, "AUDIT_RESCINDED", "SalesAudit rescission reversed net sales")
        for charge in calc.charges_of_year(ly):
            if (
                charge.get("_settlement_audit_id") == audit["id"]
                and charge["billing_status"] == "ISSUED"
            ):
                charge["billing_status"] = "VOID"
                touch(charge)
                calc.move_billed(
                    ly,
                    -charge["amount_cents"],
                    "AUDIT_RESCINDED",
                    "PercentageRentCharge voided on SalesAudit rescission",
                )
        return ok(ser(audit))

    # ------------------------------------------------------------ logical clock

    @app.post("/_clock/set_current_utc")
    @endpoint("CenterAdmin")
    def set_clock():
        payload = body()
        raw = need_str(payload, "to_iso8601")
        parsed = parse_dt(raw)
        if parsed is None:
            bad("Field 'to_iso8601' must be an ISO 8601 timestamp.")
        CLOCK["now"] = parsed
        return ok({"current_utc": iso_z(parsed)})

    @app.get("/_clock")
    @endpoint("CenterAdmin", "LeaseAdministrator", "Auditor", "OwnershipAnalyst", "TenantUser")
    def get_clock():
        return ok({"current_utc": iso_z(clock_now())})

from errors import ApiError
from middleware import guard
from response import success_envelope
from utils import json_body, reject_unknown, req_int, opt_int, parse_dt
from db import store, make_record, touch, get_or_404, fmt_ts
from serializers import tax_year as ser


def register(app):
    @app.post("/tax1099/tax-years")
    @guard({"TaxAdmin"})
    def create_tax_year():
        b = json_body()
        reject_unknown(b, {"tax_year", "period_start", "period_end_exclusive",
                           "recipient_copy_deadline", "efiling_threshold_count",
                           "nec_reportable_threshold_cents", "misc_reportable_threshold_cents"})
        year = req_int(b, "tax_year")
        if "period_start" not in b:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field 'period_start'")
        if "period_end_exclusive" not in b:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field 'period_end_exclusive'")
        if "recipient_copy_deadline" not in b:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field 'recipient_copy_deadline'")
        start = parse_dt(b["period_start"], "period_start")
        end = parse_dt(b["period_end_exclusive"], "period_end_exclusive")
        deadline = parse_dt(b["recipient_copy_deadline"], "recipient_copy_deadline")
        efile = opt_int(b, "efiling_threshold_count", 10)
        nec = opt_int(b, "nec_reportable_threshold_cents", 60000)
        misc = opt_int(b, "misc_reportable_threshold_cents", 60000)
        if end <= start:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "period_end_exclusive must fall after period_start")
        if any(ty["tax_year"] == year for ty in store["tax_years"].values()):
            raise ApiError("ERR_INVALID_REQUEST", 400, "tax_year duplicates an existing row")
        # Half-open overlap: touching endpoints allowed.
        for ty in store["tax_years"].values():
            if start < ty["_end"] and ty["_start"] < end:
                raise ApiError("ERR_TAX_YEAR_OVERLAP", 409,
                               "New TaxYear period intersects an existing TaxYear")
        rec = make_record("tax_years", {
            "tax_year": year,
            "period_start": fmt_ts(start),
            "period_end_exclusive": fmt_ts(end),
            "recipient_copy_deadline": fmt_ts(deadline),
            "efiling_threshold_count": efile,
            "nec_reportable_threshold_cents": nec,
            "misc_reportable_threshold_cents": misc,
            "backup_withholding_rate_bps": 2400,
            "status": "OPEN",
            "_start": start,
            "_end": end,
            "_deadline": deadline,
        })
        return success_envelope(ser(rec), status=201)

    @app.post("/tax1099/tax-years/<taxYearId>/close")
    @guard({"TaxAdmin"})
    def close_tax_year(taxYearId):
        rec = get_or_404("tax_years", taxYearId)
        if rec["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "TaxYear must be OPEN to close")
        rec["status"] = "CLOSED"
        touch(rec)
        return success_envelope(ser(rec))

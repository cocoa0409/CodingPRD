from flask import request

from errors import ApiError
from middleware import guard
from response import success_envelope
from utils import json_body, reject_unknown, req_str, req_int, opt_bool, parse_dt, list_page
from db import store, make_record, touch, get_or_404, logical_now, fmt_ts
from serializers import state_rule as ser_rule, state_obligation as ser_ob
from services import find_tax_year_by_value


def register(app):
    @app.post("/tax1099/state-rules")
    @guard({"TaxAdmin"})
    def create_state_rule():
        b = json_body()
        reject_unknown(b, {"state_code", "participates_in_cfsf",
                           "direct_reporting_threshold_cents", "effective_from", "effective_to"})
        code = req_str(b, "state_code")
        if len(code) != 2 or not code.isalpha() or not code.isascii():
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "state_code must be a 2-letter code")
        cfsf = opt_bool(b, "participates_in_cfsf")
        if cfsf is None:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Missing required field 'participates_in_cfsf'")
        threshold = req_int(b, "direct_reporting_threshold_cents")
        if "effective_from" not in b:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field 'effective_from'")
        if "effective_to" not in b:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field 'effective_to'")
        eff_from = parse_dt(b["effective_from"], "effective_from")
        eff_to = parse_dt(b["effective_to"], "effective_to")
        if eff_to < eff_from:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "effective_to must not precede effective_from")
        # Closed-closed intervals: touching endpoints DO overlap.
        for r in store["state_rules"].values():
            if r["state_code"] == code and r["_from"] <= eff_to and eff_from <= r["_to"]:
                raise ApiError("ERR_STATE_RULE_OVERLAP", 409,
                               "Effective interval overlaps an existing rule for this state")
        rec = make_record("state_rules", {
            "state_code": code,
            "participates_in_cfsf": cfsf,
            "direct_reporting_threshold_cents": threshold,
            "effective_from": fmt_ts(eff_from),
            "effective_to": fmt_ts(eff_to),
            "_from": eff_from,
            "_to": eff_to,
        })
        return success_envelope(ser_rule(rec), status=201)

    @app.post("/tax1099/state-obligations/evaluate")
    @guard({"TaxSpecialist"})
    def evaluate_obligations():
        b = json_body()
        reject_unknown(b, {"tax_year"})
        year = req_int(b, "tax_year")
        if find_tax_year_by_value(year) is None:
            raise ApiError("ERR_NO_TAX_YEAR", 422, "No TaxYear row exists for tax_year")
        now = logical_now()
        evaluated = 0
        created_ids = []
        updated = 0
        for v in sorted(store["vendors"].values(), key=lambda r: r["_seq"]):
            if v["status"] != "ACTIVE":
                continue  # MERGED / DEACTIVATED vendors are skipped
            posted = [p for p in store["payments"].values()
                      if p["vendor_id"] == v["id"] and p["tax_year"] == year
                      and p["status"] == "POSTED"]
            if not posted:
                continue
            rule = None
            for r in store["state_rules"].values():
                if (r["state_code"] == v["address_state"]
                        and r["_from"] <= now <= r["_to"]):
                    if rule is None or r["_from"] > rule["_from"]:
                        rule = r
            if rule is None:
                continue  # no governing rule -> no obligation row
            evaluated += 1
            reportable = sum(p["amount_cents"] for p in posted if p["is_reportable"])
            if rule["participates_in_cfsf"]:
                channel = "CFSF_FORWARD"
            elif reportable >= rule["direct_reporting_threshold_cents"]:
                channel = "DIRECT_FILE"
            else:
                channel = "NOT_REQUIRED"
            status = "NOT_REQUIRED" if channel == "NOT_REQUIRED" else "PENDING"
            existing = None
            for ob in sorted(store["state_obligations"].values(), key=lambda r: r["_seq"]):
                if ob["vendor_id"] == v["id"] and ob["tax_year"] == year:
                    existing = ob
                    break
            if existing is None:
                rec = make_record("state_obligations", {
                    "vendor_id": v["id"],
                    "state_rule_id": rule["id"],
                    "tax_year": year,
                    "required_channel": channel,
                    "reportable_amount_cents": reportable,
                    "status": status,
                })
                created_ids.append(rec["id"])
            elif existing["status"] == "PENDING":
                existing["state_rule_id"] = rule["id"]
                existing["required_channel"] = channel
                existing["reportable_amount_cents"] = reportable
                existing["status"] = status
                touch(existing)
                updated += 1
            # terminal rows are left untouched
        return success_envelope({"evaluated_count": evaluated,
                                 "created_obligation_ids": created_ids,
                                 "updated_count": updated})

    @app.get("/tax1099/state-obligations/<obligationId>")
    @guard({"TaxSpecialist", "TaxAdmin"})
    def get_obligation(obligationId):
        return success_envelope(ser_ob(get_or_404("state_obligations", obligationId)))

    @app.get("/tax1099/state-obligations")
    @guard({"TaxSpecialist", "TaxAdmin"})
    def list_obligations():
        items = sorted(store["state_obligations"].values(), key=lambda r: r["_seq"])
        for f in ("vendor_id", "state_rule_id", "tax_year", "status"):
            v = request.args.get(f)
            if v is not None:
                items = [r for r in items if str(r.get(f)) == v]
        page, pagination = list_page(items)
        return success_envelope([ser_ob(r) for r in page], response_type="array",
                                pagination=pagination)

    @app.post("/tax1099/state-obligations/<obligationId>/mark-filed")
    @guard({"TaxSpecialist"})
    def mark_filed(obligationId):
        rec = get_or_404("state_obligations", obligationId)
        if rec["status"] != "PENDING" or rec["required_channel"] != "DIRECT_FILE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Only a PENDING DIRECT_FILE obligation can be marked filed")
        rec["status"] = "FILED_DIRECT"
        touch(rec)
        return success_envelope(ser_ob(rec))

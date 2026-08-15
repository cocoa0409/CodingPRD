"""Routes: TrimTicket, QualityCert, PartSerial, SurchargeIndex, Invoice."""
import re
from decimal import Decimal

from core import (
    ALL_ROLES, DB, TON_LBS, SCRAP_CREDIT_CAP, auth, body, success,
    list_response, apply_filters, view, new_record, touch, get_or_404,
    f_str, f_num, f_int, f_enum, clock_now, err, q2, q3, q0, D,
    recompute_order, reeval_coverage, trim_allocation, accepted_flash_total,
    order_runs,
)

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def register(app):

    # ---------------- TrimTicket ----------------
    @app.post("/forge-runs/<rid>/trim-tickets")
    def create_ticket(rid):
        auth(["ForgeOperator"])
        body()
        run = get_or_404("forge_runs", rid)
        if run["status"] != "FORGED":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"run in status {run['status']} cannot open a trim ticket")
        for t in DB["trim_tickets"].values():
            if t["forge_run_id"] == run["id"] and t["status"] in ("DRAFT", "FLAGGED"):
                raise err("ERR_TRIM_TICKET_ACTIVE_EXISTS", 409,
                          "run already has a trim ticket in DRAFT or FLAGGED")
        rec = new_record("trim_tickets")
        rec.update({
            "forge_run_id": run["id"],
            "gross_as_forged_lbs": None,
            "net_trimmed_lbs": None,
            "pierce_loss_lbs": None,
            "flash_scrap_lbs": None,
            "flash_yield_pct": None,
            "deviation_reason": None,
            "status": "DRAFT",
        })
        return success(view(rec), 201)

    @app.get("/forge-runs/<rid>/trim-tickets")
    def list_run_tickets(rid):
        auth(ALL_ROLES)
        get_or_404("forge_runs", rid)
        return list_response([t for t in DB["trim_tickets"].values() if t["forge_run_id"] == rid])

    @app.get("/trim-tickets/<rid>")
    def get_ticket(rid):
        auth(ALL_ROLES)
        return success(view(get_or_404("trim_tickets", rid)), 200)

    @app.post("/trim-tickets/<rid>/record")
    def record_ticket(rid):
        auth(["ForgeOperator"])
        d = body()
        gross = f_num(d, "gross_as_forged_lbs", min_inclusive=0)
        net = f_num(d, "net_trimmed_lbs", min_inclusive=0)
        pierce = f_num(d, "pierce_loss_lbs", min_inclusive=0)
        t = get_or_404("trim_tickets", rid)
        if t["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"trim ticket in status {t['status']} cannot be recorded")
        run = get_or_404("forge_runs", t["forge_run_id"])
        wo = get_or_404("work_orders", run["work_order_id"])
        alloy = get_or_404("alloy_specs", wo["alloy_spec_id"])
        # mass balance
        flash = gross - net - pierce
        if flash < 0:
            raise err("ERR_TRIM_MASS_IMBALANCE", 422, "flash_scrap_lbs would be negative")
        others = sum((o["gross_as_forged_lbs"] for o in DB["trim_tickets"].values()
                      if o["forge_run_id"] == run["id"] and o["id"] != t["id"]
                      and o["status"] != "VOIDED" and o["gross_as_forged_lbs"] is not None),
                     Decimal("0"))
        if gross > D(run["input_weight_lbs"]) - others:
            raise err("ERR_TRIM_MASS_IMBALANCE", 422,
                      "gross exceeds the run's unallocated input weight")
        t["gross_as_forged_lbs"] = gross
        t["net_trimmed_lbs"] = net
        t["pierce_loss_lbs"] = pierce
        t["flash_scrap_lbs"] = flash
        if gross > 0:
            ratio_pct = flash / gross * Decimal("100")
            t["flash_yield_pct"] = q2(ratio_pct)
            flagged = ratio_pct > D(alloy["flash_allowance_pct"])
        else:
            t["flash_yield_pct"] = q2(Decimal("0"))
            flagged = False
        t["status"] = "FLAGGED" if flagged else "ACCEPTED"
        touch("trim_tickets", t)
        if not flagged:
            trim_allocation(t)
        return success(view(t), 200)

    @app.post("/trim-tickets/<rid>/approve-deviation")
    def approve_deviation(rid):
        auth(["QualityEngineer"])
        d = body()
        reason = f_str(d, "deviation_reason")
        t = get_or_404("trim_tickets", rid)
        if t["status"] != "FLAGGED":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"trim ticket in status {t['status']} cannot be deviation-approved")
        t["deviation_reason"] = reason
        t["status"] = "ACCEPTED"
        touch("trim_tickets", t)
        trim_allocation(t)
        return success(view(t), 200)

    @app.post("/trim-tickets/<rid>/void")
    def void_ticket(rid):
        auth(["ForgeOperator"])
        body()
        t = get_or_404("trim_tickets", rid)
        if t["status"] not in ("DRAFT", "FLAGGED"):
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"trim ticket in status {t['status']} cannot be voided")
        t["status"] = "VOIDED"
        touch("trim_tickets", t)
        return success(view(t), 200)

    # ---------------- QualityCert ----------------
    @app.post("/work-orders/<rid>/quality-certs")
    def create_cert(rid):
        auth(["QualityEngineer"])
        d = body()
        heat_id = f_str(d, "mill_heat_id")
        sample_id = d.get("sample_part_serial_id")
        if sample_id is not None and (not isinstance(sample_id, str) or not sample_id):
            raise err("ERR_INVALID_REQUEST", 400, "sample_part_serial_id must be a string id")
        wo = get_or_404("work_orders", rid)
        get_or_404("mill_heats", heat_id)
        sample = get_or_404("part_serials", sample_id) if sample_id else None
        # referential usability
        used_heats = {p["mill_heat_id"] for p in DB["part_serials"].values()
                      if p["work_order_id"] == wo["id"]}
        if heat_id not in used_heats:
            raise err("ERR_HEAT_NOT_IN_ORDER", 409,
                      "the heat does not appear among the order's parts")
        if sample is not None:
            if sample["work_order_id"] != wo["id"] or sample["mill_heat_id"] != heat_id:
                raise err("ERR_SAMPLE_NOT_FROM_HEAT", 409,
                          "sample part must belong to this order and to the cert's heat")
        for c in DB["quality_certs"].values():
            if c["work_order_id"] == wo["id"] and c["mill_heat_id"] == heat_id:
                raise err("ERR_CERT_EXISTS", 409,
                          "a QualityCert already exists for this (work order, heat)")
        rec = new_record("quality_certs")
        rec.update({
            "work_order_id": wo["id"],
            "mill_heat_id": heat_id,
            "sample_part_serial_id": sample_id,
            "grain_flow_rating": None,
            "macro_etch_result": None,
            "submitter_id": None,
            "certifier_id": None,
            "status": "PENDING",
        })
        return success(view(rec), 201)

    @app.get("/quality-certs")
    def list_certs():
        auth(ALL_ROLES)
        return list_response(apply_filters(
            DB["quality_certs"].values(),
            ["work_order_id", "mill_heat_id", "sample_part_serial_id", "status"]))

    @app.get("/quality-certs/<rid>")
    def get_cert(rid):
        auth(ALL_ROLES)
        return success(view(get_or_404("quality_certs", rid)), 200)

    @app.post("/quality-certs/<rid>/submit")
    def submit_cert(rid):
        uid = auth(["QualityEngineer"])
        d = body()
        rating = f_int(d, "grain_flow_rating", min_inclusive=1, max_inclusive=8)
        etch = f_enum(d, "macro_etch_result", {"PASS", "FAIL"})
        cert = get_or_404("quality_certs", rid)
        if cert["status"] not in ("PENDING", "REJECTED"):
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"cert in status {cert['status']} cannot be submitted")
        cert["grain_flow_rating"] = rating
        cert["macro_etch_result"] = etch
        cert["submitter_id"] = uid
        cert["status"] = "SUBMITTED"
        touch("quality_certs", cert)
        return success(view(cert), 200)

    @app.post("/quality-certs/<rid>/certify")
    def certify_cert(rid):
        uid = auth(["QualityEngineer"])
        body()
        cert = get_or_404("quality_certs", rid)
        if cert["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"cert in status {cert['status']} cannot be certified")
        heat = get_or_404("mill_heats", cert["mill_heat_id"])
        alloy = get_or_404("alloy_specs", heat["alloy_spec_id"])
        if cert["grain_flow_rating"] < alloy["grain_flow_min_rating"] or (
                cert["macro_etch_result"] == "FAIL" and alloy["macro_etch_required"]):
            raise err("ERR_GRAIN_FLOW_BELOW_SPEC", 422,
                      "grain-flow/macro-etch readings do not meet the alloy spec")
        wo = get_or_404("work_orders", cert["work_order_id"])
        if uid == cert["submitter_id"]:
            raise err("ERR_CERT_SOD_VIOLATION", 403,
                      "certifier must differ from the submitter")
        for r in order_runs(wo["id"]):
            if r.get("operator_id") is not None and r["operator_id"] == uid:
                raise err("ERR_CERT_SOD_VIOLATION", 403,
                          "certifier must not be a forge-run operator of record on this order")
        cert["certifier_id"] = uid
        cert["status"] = "CERTIFIED"
        touch("quality_certs", cert)
        reeval_coverage(wo)
        return success(view(cert), 200)

    @app.post("/quality-certs/<rid>/reject")
    def reject_cert(rid):
        uid = auth(["QualityEngineer"])
        d = body()
        f_str(d, "reason")
        cert = get_or_404("quality_certs", rid)
        if cert["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"cert in status {cert['status']} cannot be rejected")
        if uid == cert["submitter_id"]:
            raise err("ERR_CERT_SOD_VIOLATION", 403,
                      "rejecter must differ from the submitter")
        cert["status"] = "REJECTED"
        touch("quality_certs", cert)
        return success(view(cert), 200)

    # ---------------- PartSerial ----------------
    @app.get("/part-serials")
    def list_parts():
        auth(ALL_ROLES)
        return list_response(apply_filters(
            DB["part_serials"].values(),
            ["work_order_id", "mill_heat_id", "forge_run_id", "forge_heat_id", "status"]))

    @app.get("/part-serials/<rid>")
    def get_part(rid):
        auth(ALL_ROLES)
        return success(view(get_or_404("part_serials", rid)), 200)

    @app.post("/part-serials/<rid>/inspect")
    def inspect_part(rid):
        auth(["QualityEngineer"])
        body()
        p = get_or_404("part_serials", rid)
        if p["status"] != "TRIMMED":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"part in status {p['status']} cannot be inspected")
        p["status"] = "INSPECTED"
        touch("part_serials", p)
        return success(view(p), 200)

    @app.post("/part-serials/<rid>/scrap")
    def scrap_part(rid):
        auth(["QualityEngineer"])
        d = body()
        f_str(d, "reason")
        p = get_or_404("part_serials", rid)
        if p["status"] not in ("FORGED", "TRIMMED", "INSPECTED"):
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"part in status {p['status']} cannot be scrapped")
        p["status"] = "SCRAPPED"
        touch("part_serials", p)
        wo = get_or_404("work_orders", p["work_order_id"])
        recompute_order(wo)
        return success(view(p), 200)

    # ---------------- SurchargeIndex ----------------
    @app.post("/surcharge-indices")
    def create_index():
        auth(["PlantManager"])
        d = body()
        alloy_id = f_str(d, "alloy_spec_id")
        month = f_str(d, "effective_month")
        rate = f_int(d, "surcharge_cents_per_ton", min_inclusive=0)
        energy = f_num(d, "energy_pct", min_inclusive=0)
        if not MONTH_RE.match(month):
            raise err("ERR_INVALID_REQUEST", 400, "effective_month must be in YYYY-MM form")
        get_or_404("alloy_specs", alloy_id)
        for x in DB["surcharge_indices"].values():
            if x["alloy_spec_id"] == alloy_id and x["effective_month"] == month:
                raise err("ERR_DUPLICATE_SURCHARGE_INDEX", 409,
                          "index already exists for (alloy_spec_id, effective_month)")
        rec = new_record("surcharge_indices")
        rec.update({
            "alloy_spec_id": alloy_id,
            "effective_month": month,
            "surcharge_cents_per_ton": rate,
            "energy_pct": energy,
        })
        return success(view(rec), 201)

    @app.get("/surcharge-indices")
    def list_indices():
        auth(ALL_ROLES)
        return list_response(apply_filters(
            DB["surcharge_indices"].values(), ["alloy_spec_id", "effective_month"]))

    @app.get("/surcharge-indices/<rid>")
    def get_index(rid):
        auth(ALL_ROLES)
        return success(view(get_or_404("surcharge_indices", rid)), 200)

    # ---------------- Invoice ----------------
    def _compute_invoice(inv, wo, variant):
        idx = get_or_404("surcharge_indices", inv["surcharge_index_id"])
        if variant == "provisional":
            weight = q2(Decimal(wo["ordered_qty"]) * D(wo["part_net_weight_lbs"]))
            inv["estimated_net_weight_lbs"] = weight
        else:
            weight = q2(sum((D(p["net_weight_lbs"]) for p in DB["part_serials"].values()
                             if p["work_order_id"] == wo["id"] and p["status"] == "SHIPPED"),
                            Decimal("0")))
            inv["actual_shipped_net_weight_lbs"] = weight
        inv["billable_weight_lbs"] = weight
        tons = q3(weight / TON_LBS)
        inv["billable_tons"] = tons
        if tons <= D(wo["price_tier1_limit_tons"]):
            rate = wo["price_tier1_cents_per_ton"]
        elif tons <= D(wo["price_tier2_limit_tons"]):
            rate = wo["price_tier2_cents_per_ton"]
        else:
            rate = wo["price_tier3_cents_per_ton"]
        inv["tier_rate_cents_per_ton"] = rate
        base = q0(tons * rate)
        alloy_s = q0(tons * D(idx["surcharge_cents_per_ton"]))
        energy = q0(Decimal(base + alloy_s) * D(idx["energy_pct"]))
        flash_total = accepted_flash_total(wo["id"])
        scrap = min(q0(flash_total * D(wo["scrap_recovery_rate_cents_per_lb"])),
                    q0(Decimal(base) * SCRAP_CREDIT_CAP))
        inv["base_amount_cents"] = base
        inv["alloy_surcharge_cents"] = alloy_s
        inv["energy_surcharge_cents"] = energy
        inv["scrap_credit_cents"] = scrap
        inv["total_cents"] = base + alloy_s + energy - scrap

    @app.post("/work-orders/<rid>/invoices")
    def create_invoice(rid):
        auth(["SalesPlanner"])
        d = body()
        expected = f_int(d, "expected_work_order_version")
        wo = get_or_404("work_orders", rid)
        if expected != wo["version"]:
            raise err("ERR_STALE_VERSION", 412,
                      "expected_work_order_version does not match the order's current version")
        for x in DB["invoices"].values():
            if x["work_order_id"] == wo["id"] and x["status"] != "VOID":
                raise err("ERR_INVOICE_EXISTS", 409,
                          "a non-VOID invoice already exists for the work order")
        month = clock_now().strftime("%Y-%m")
        idx = None
        for x in DB["surcharge_indices"].values():
            if x["alloy_spec_id"] == wo["alloy_spec_id"] and x["effective_month"] == month:
                idx = x
                break
        if idx is None:
            raise err("ERR_SURCHARGE_INDEX_MISSING", 422,
                      "no surcharge index for (order alloy, logical-clock month)")
        rec = new_record("invoices")
        rec.update({
            "work_order_id": wo["id"],
            "surcharge_index_id": idx["id"],
            "estimated_net_weight_lbs": None,
            "actual_shipped_net_weight_lbs": None,
            "billable_weight_lbs": None,
            "billable_tons": None,
            "tier_rate_cents_per_ton": None,
            "base_amount_cents": None,
            "alloy_surcharge_cents": None,
            "energy_surcharge_cents": None,
            "scrap_credit_cents": None,
            "total_cents": None,
            "status": "PROVISIONAL",
        })
        _compute_invoice(rec, wo, "provisional")
        touch("work_orders", wo)
        return success(view(rec), 201)

    @app.get("/invoices")
    def list_invoices():
        auth(ALL_ROLES)
        return list_response(apply_filters(
            DB["invoices"].values(), ["work_order_id", "surcharge_index_id", "status"]))

    @app.get("/invoices/<rid>")
    def get_invoice(rid):
        auth(ALL_ROLES)
        return success(view(get_or_404("invoices", rid)), 200)

    @app.post("/invoices/<rid>/finalize")
    def finalize_invoice(rid):
        auth(["SalesPlanner"])
        body()
        inv = get_or_404("invoices", rid)
        if inv["status"] != "PROVISIONAL":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"invoice in status {inv['status']} cannot be finalized")
        wo = get_or_404("work_orders", inv["work_order_id"])
        if wo["status"] != "CERTIFIED":
            raise err("ERR_ORDER_NOT_CERTIFIED", 409, "work order is not CERTIFIED")
        for p in DB["part_serials"].values():
            if p["work_order_id"] == wo["id"] and p["status"] in ("FORGED", "TRIMMED", "INSPECTED"):
                raise err("ERR_ORDER_NOT_FULLY_SHIPPED", 409,
                          "parts remain in FORGED, TRIMMED, or INSPECTED")
        _compute_invoice(inv, wo, "final")
        inv["status"] = "FINAL"
        touch("invoices", inv)
        return success(view(inv), 200)

    @app.post("/invoices/<rid>/void")
    def void_invoice(rid):
        auth(["SalesPlanner"])
        body()
        inv = get_or_404("invoices", rid)
        if inv["status"] != "PROVISIONAL":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"invoice in status {inv['status']} cannot be voided")
        inv["status"] = "VOID"
        touch("invoices", inv)
        return success(view(inv), 200)

    @app.post("/invoices/<rid>/mark-paid")
    def mark_paid(rid):
        auth(["SalesPlanner"])
        body()
        inv = get_or_404("invoices", rid)
        if inv["status"] != "FINAL":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"invoice in status {inv['status']} cannot be marked paid")
        inv["status"] = "PAID"
        touch("invoices", inv)
        wo = get_or_404("work_orders", inv["work_order_id"])
        if wo["status"] == "CERTIFIED":
            wo["status"] = "CLOSED"
            touch("work_orders", wo)
        return success(view(inv), 200)

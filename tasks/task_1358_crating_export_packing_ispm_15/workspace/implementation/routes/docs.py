"""Export documents: PackingList & CommercialInvoice (PRD §3.7)."""
from decimal import Decimal

from flask import Blueprint

from db import STORE, new_id, now_iso, touch
from errors import (ApiError, ERR_JOB_INVALID_STATE, ERR_DOC_INVALID_STATE,
                    ERR_DOC_CRATE_MISMATCH, ERR_DOC_QUANTITY_MISMATCH,
                    ERR_DOC_WEIGHT_MISMATCH, ERR_INVOICE_UNDERVALUED,
                    not_found, bad_request)
from middleware import (ALL_OPERATIONAL, require_roles, body, req_list,
                        paginate, enum_filter, str_filter)
from response import success
from services import calc
from services.state import get, ser_packing_list, ser_invoice, job_items

bp = Blueprint("docs", __name__)

DOC_STATUSES = {"DRAFT", "FINALIZED", "RELEASED", "AMENDING"}
DOC_JOB_STATES = {"DESIGN", "PACKING", "READY_TO_LOAD", "LOADED"}  # upsert window


def _get_job_or_404(jid):
    j = get("jobs", jid)
    if not j:
        raise not_found("PackingJob not found")
    return j


def _crate_belongs(job_id, crate_id):
    c = get("crates", crate_id)
    if not c or c["packing_job_id"] != job_id:
        raise not_found("crate_id %s does not resolve within this job" % crate_id)
    return c


def _validate_pl_lines(job_id, lines):
    out = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise bad_request("Each packing-list line must be an object")
        crate_id = ln.get("crate_id")
        if not isinstance(crate_id, str):
            raise bad_request("Each line requires a string 'crate_id'")
        desc = ln.get("description")
        if not isinstance(desc, str):
            raise bad_request("Each line requires a string 'description'")
        qty = ln.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
                or (isinstance(qty, float) and not qty.is_integer()) or int(qty) < 1:
            raise bad_request("Each line requires integer 'qty' >= 1")
        for wkey in ("net_weight_kg", "gross_weight_kg"):
            w = ln.get(wkey)
            if isinstance(w, bool) or not isinstance(w, (int, float)) or not w > 0:
                raise bad_request("Each line requires '%s' > 0" % wkey)
        out.append({"crate_id": crate_id, "description": desc, "qty": int(qty),
                    "net_weight_kg": ln["net_weight_kg"],
                    "gross_weight_kg": ln["gross_weight_kg"]})
    return out


def _validate_ci_lines(lines):
    out = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise bad_request("Each invoice line must be an object")
        crate_id = ln.get("crate_id")
        if not isinstance(crate_id, str):
            raise bad_request("Each line requires a string 'crate_id'")
        desc = ln.get("description")
        if not isinstance(desc, str):
            raise bad_request("Each line requires a string 'description'")
        qty = ln.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, (int, float)) \
                or (isinstance(qty, float) and not qty.is_integer()) or int(qty) < 1:
            raise bad_request("Each line requires integer 'qty' >= 1")
        price = ln.get("unit_price_cents")
        if isinstance(price, bool) or not isinstance(price, (int, float)) \
                or (isinstance(price, float) and not price.is_integer()) or int(price) < 0:
            raise bad_request("Each line requires integer 'unit_price_cents' >= 0")
        duty = ln.get("duty_rate_bp")
        if isinstance(duty, bool) or not isinstance(duty, (int, float)) \
                or (isinstance(duty, float) and not duty.is_integer()) \
                or not (0 <= int(duty) <= 10000):
            raise bad_request("Each line requires integer 'duty_rate_bp' in 0..10000")
        out.append({"crate_id": crate_id, "description": desc, "qty": int(qty),
                    "unit_price_cents": int(price), "duty_rate_bp": int(duty)})
    return out


def _job_docs(job_id):
    pl = next((p for p in STORE["packing_lists"].values()
               if p["packing_job_id"] == job_id), None)
    ci = next((v for v in STORE["invoices"].values()
               if v["packing_job_id"] == job_id), None)
    return pl, ci


@bp.post("/crating/packing-jobs/<jid>/packing-list")
def upsert_packing_list(jid):
    require_roles(["SalesRep"])
    d = body()
    lines = _validate_pl_lines(jid, req_list(d, "lines"))
    j = _get_job_or_404(jid)
    for ln in lines:
        _crate_belongs(jid, ln["crate_id"])
    if j["status"] not in DOC_JOB_STATES:
        raise ApiError(ERR_JOB_INVALID_STATE,
                       "Documents may be upserted only while DESIGN..LOADED", 409)
    pl, _ = _job_docs(jid)
    if pl is not None and pl["status"] not in ("DRAFT", "AMENDING"):
        raise ApiError(ERR_DOC_INVALID_STATE,
                       "PackingList may only be replaced while DRAFT or AMENDING", 409)
    total = float(sum(Decimal(str(ln["gross_weight_kg"])) for ln in lines)
                  .quantize(Decimal("0.01")))
    if pl is None:
        pl = {"id": new_id(), "packing_job_id": jid, "lines": lines,
              "total_gross_weight_kg": total, "status": "DRAFT",
              "created_at": now_iso(), "updated_at": now_iso(), "version": 1}
        STORE["packing_lists"][pl["id"]] = pl
    else:
        pl["lines"] = lines
        pl["total_gross_weight_kg"] = total
        touch(pl)
    return success(ser_packing_list(pl), status=201)


@bp.get("/crating/packing-lists/<pid>")
def get_packing_list(pid):
    require_roles(ALL_OPERATIONAL)
    pl = get("packing_lists", pid)
    if not pl:
        raise not_found("PackingList not found")
    return success(ser_packing_list(pl))


@bp.get("/crating/packing-lists")
def list_packing_lists():
    require_roles(ALL_OPERATIONAL)
    job_id = str_filter("packing_job_id")
    status = enum_filter("status", DOC_STATUSES)
    recs = [p for p in STORE["packing_lists"].values()
            if (job_id is None or p["packing_job_id"] == job_id)
            and (status is None or p["status"] == status)]
    recs.sort(key=lambda p: p["created_at"])
    page, meta = paginate(recs)
    return success([ser_packing_list(p) for p in page], pagination=meta)


@bp.post("/crating/packing-jobs/<jid>/commercial-invoice")
def upsert_invoice(jid):
    require_roles(["SalesRep"])
    d = body()
    lines = _validate_ci_lines(req_list(d, "lines"))
    j = _get_job_or_404(jid)
    for ln in lines:
        _crate_belongs(jid, ln["crate_id"])
    if j["status"] not in DOC_JOB_STATES:
        raise ApiError(ERR_JOB_INVALID_STATE,
                       "Documents may be upserted only while DESIGN..LOADED", 409)
    _, ci = _job_docs(jid)
    if ci is not None and ci["status"] not in ("DRAFT", "AMENDING"):
        raise ApiError(ERR_DOC_INVALID_STATE,
                       "CommercialInvoice may only be replaced while DRAFT or AMENDING", 409)
    total, duty = calc.invoice_totals(lines)
    if ci is None:
        ci = {"id": new_id(), "packing_job_id": jid, "lines": lines,
              "invoice_total_cents": total, "duty_total_cents": duty,
              "status": "DRAFT",
              "created_at": now_iso(), "updated_at": now_iso(), "version": 1}
        STORE["invoices"][ci["id"]] = ci
    else:
        ci["lines"] = lines
        ci["invoice_total_cents"] = total
        ci["duty_total_cents"] = duty
        touch(ci)
    return success(ser_invoice(ci), status=201)


@bp.get("/crating/commercial-invoices/<vid>")
def get_invoice(vid):
    require_roles(ALL_OPERATIONAL)
    ci = get("invoices", vid)
    if not ci:
        raise not_found("CommercialInvoice not found")
    return success(ser_invoice(ci))


@bp.get("/crating/commercial-invoices")
def list_invoices():
    require_roles(ALL_OPERATIONAL)
    job_id = str_filter("packing_job_id")
    status = enum_filter("status", DOC_STATUSES)
    recs = [v for v in STORE["invoices"].values()
            if (job_id is None or v["packing_job_id"] == job_id)
            and (status is None or v["status"] == status)]
    recs.sort(key=lambda v: v["created_at"])
    page, meta = paginate(recs)
    return success([ser_invoice(v) for v in page], pagination=meta)


@bp.post("/crating/packing-jobs/<jid>/finalize-docs")
def finalize_docs(jid):
    require_roles(["SalesRep"])
    j = _get_job_or_404(jid)
    pl, ci = _job_docs(jid)
    if pl is None or pl["status"] not in ("DRAFT", "AMENDING"):
        raise ApiError(ERR_DOC_INVALID_STATE,
                       "PackingList must exist and be DRAFT or AMENDING", 409)
    if ci is None or ci["status"] not in ("DRAFT", "AMENDING"):
        raise ApiError(ERR_DOC_INVALID_STATE,
                       "CommercialInvoice must exist and be DRAFT or AMENDING", 409)
    pl["status"] = "FINALIZED"
    touch(pl)
    ci["status"] = "FINALIZED"
    touch(ci)
    return success(ser_packing_list(pl))


@bp.post("/crating/packing-jobs/<jid>/release-docs")
def release_docs(jid):
    require_roles(["ComplianceOfficer"])
    j = _get_job_or_404(jid)
    pl, ci = _job_docs(jid)
    if pl is None or pl["status"] != "FINALIZED":
        raise ApiError(ERR_DOC_INVALID_STATE, "PackingList must be FINALIZED", 409)
    if ci is None or ci["status"] != "FINALIZED":
        raise ApiError(ERR_DOC_INVALID_STATE, "CommercialInvoice must be FINALIZED", 409)
    # consistency checks in pinned order (PRD §2.8 tier 10, §3.7)
    pl_by_crate = {ln["crate_id"]: ln for ln in pl["lines"]}
    ci_by_crate = {ln["crate_id"]: ln for ln in ci["lines"]}
    if set(pl_by_crate) != set(ci_by_crate):
        raise ApiError(ERR_DOC_CRATE_MISMATCH,
                       "PackingList and invoice reference different crates", 422)
    for cid, pl_ln in pl_by_crate.items():
        if pl_ln["qty"] != ci_by_crate[cid]["qty"]:
            raise ApiError(ERR_DOC_QUANTITY_MISMATCH,
                           "Per-crate quantities differ between documents", 422)
    crate_gross_sum = Decimal(0)
    for cid in pl_by_crate:
        c = get("crates", cid)
        if c:
            crate_gross_sum += Decimal(str(c["gross_weight_kg"]))
    if abs(Decimal(str(pl["total_gross_weight_kg"])) - crate_gross_sum) > Decimal("0.5"):
        raise ApiError(ERR_DOC_WEIGHT_MISMATCH,
                       "PackingList gross weight diverges from crate gross weights", 422)
    declared_sum = sum(it["declared_value_cents"] for it in job_items(jid))
    if Decimal(ci["invoice_total_cents"]) < Decimal("0.95") * Decimal(declared_sum):
        raise ApiError(ERR_INVOICE_UNDERVALUED,
                       "Invoice total below 95% of declared value sum", 422)
    pl["status"] = "RELEASED"
    touch(pl)
    ci["status"] = "RELEASED"
    touch(ci)
    return success(ser_packing_list(pl))


@bp.post("/crating/packing-jobs/<jid>/amend-docs")
def amend_docs(jid):
    require_roles(["SalesRep"])
    j = _get_job_or_404(jid)
    if j["status"] not in ("READY_TO_LOAD", "LOADED"):
        raise ApiError(ERR_JOB_INVALID_STATE,
                       "Documents may be amended only before shipment", 409)
    pl, ci = _job_docs(jid)
    if pl is None or pl["status"] != "RELEASED" or ci is None or ci["status"] != "RELEASED":
        raise ApiError(ERR_DOC_INVALID_STATE, "Both documents must be RELEASED", 409)
    pl["status"] = "AMENDING"
    touch(pl)
    ci["status"] = "AMENDING"
    touch(ci)
    return success(ser_packing_list(pl))

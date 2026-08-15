"""Flat single-resource GETs, flat filtered lists, and bank-scoped *_index lists."""
from appobj import api
from store import (
    banks, customers, agreements, sites, formats, schedules, batches, items,
    exceptions, image_requests, cycles, line_items, incidents, credits,
)
from util import ApiError, ok, pub, list_response
from helpers import auth, scope, R_bank, batch_pub

# (segment, store, filters, customer_scoped, serializer)
SPECS = {
    "customers": (customers, ["bank_id", "status"], "self", None),
    "agreements": (agreements, ["bank_id", "customer_id", "status"], "customer_id", None),
    "sites": (sites, ["bank_id", "agreement_id", "customer_id", "status"], "customer_id", None),
    "transmission_formats": (formats, ["bank_id", "agreement_id", "customer_id",
                                       "supersedes_format_id", "status", "format_kind"],
                             "customer_id", None),
    "batches": (batches, ["bank_id", "site_id", "agreement_id", "customer_id",
                          "capture_status", "transmission_status", "batch_status",
                          "business_date"], "customer_id", "batch"),
    "items": (items, ["bank_id", "batch_id", "site_id", "customer_id", "status",
                      "availability_tier"], "customer_id", None),
    "availability_schedules": (schedules, ["bank_id", "site_id", "status", "tier"],
                               None, None),
    "exception_items": (exceptions, ["bank_id", "customer_id", "batch_id", "item_id",
                                     "status", "reason_code"], "customer_id", None),
    "image_requests": (image_requests, ["bank_id", "customer_id", "item_id", "status",
                                        "request_reason"], "customer_id", None),
    "analysis_cycles": (cycles, ["bank_id", "customer_id", "agreement_id", "status"],
                        "customer_id", None),
    "analysis_line_items": (line_items, ["bank_id", "cycle_id", "line_kind"],
                            "via_cycle", None),
    "sla_incidents": (incidents, ["bank_id", "customer_id", "cycle_id",
                                  "reference_batch_id", "reference_request_id",
                                  "status", "incident_kind"], "customer_id", None),
    "error_credit_requests": (credits, ["bank_id", "customer_id", "cycle_id",
                                        "status", "reason_code"], "customer_id", None),
}


def _customer_of(seg, row):
    if seg == "customers":
        return row["id"]
    if SPECS[seg][2] == "via_cycle":
        cyc = cycles.get(row["cycle_id"])
        return cyc["customer_id"] if cyc else None
    return row.get("customer_id")


def _serialize(seg, row):
    if SPECS[seg][3] == "batch":
        return batch_pub(row)
    return pub(row)


def _get_flat(seg, rid):
    uid, role = auth()
    st = SPECS[seg][0]
    row = st.get(rid)
    if not row:
        raise ApiError("ERR_NOT_FOUND", 404, "resource not found")
    cust = _customer_of(seg, row)
    if cust is not None:
        scope(uid, role, cust)
    return ok(_serialize(seg, row))


def _list_flat(seg):
    uid, role = auth()
    st, filters, _, _ = SPECS[seg]
    rows = list(st.values())
    if role == "CustomerOperator":
        rows = [r for r in rows if _customer_of(seg, r) == uid]
    if "batch_status" in filters:
        from flask import request
        from helpers import compound_status
        bs = request.args.get("batch_status")
        if bs is not None:
            rows = [r for r in rows if compound_status(r) == bs]
        filters = [f for f in filters if f != "batch_status"]
    return list_response(rows, filters, serialize=lambda r: _serialize(seg, r))


def _list_index(seg, bankId):
    uid, role = auth()
    bank = R_bank(bankId)
    st, filters, _, _ = SPECS[seg]
    rows = [r for r in st.values() if r.get("bank_id") == bank["id"]]
    if role == "CustomerOperator":
        rows = [r for r in rows if _customer_of(seg, r) == uid]
    if "batch_status" in filters:
        from flask import request
        from helpers import compound_status
        bs = request.args.get("batch_status")
        if bs is not None:
            rows = [r for r in rows if compound_status(r) == bs]
        filters = [f for f in filters if f != "batch_status"]
    return list_response(rows, filters, serialize=lambda r: _serialize(seg, r))


def _mk(seg):
    def get_one(rid):
        return _get_flat(seg, rid)

    def list_all():
        return _list_flat(seg)

    def list_index(bankId):
        return _list_index(seg, bankId)

    get_one.__name__ = "flat_get_" + seg
    list_all.__name__ = "flat_list_" + seg
    list_index.__name__ = "index_list_" + seg
    api.add_url_rule("/banks/%s/<rid>" % seg, get_one.__name__, get_one, methods=["GET"])
    api.add_url_rule("/banks/%s" % seg, list_all.__name__, list_all, methods=["GET"])
    api.add_url_rule("/banks/<bankId>/%s_index" % seg, list_index.__name__,
                     list_index, methods=["GET"])


for _seg in SPECS:
    _mk(_seg)

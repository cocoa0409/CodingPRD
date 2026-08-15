"""Analysis cycles, line items, SLA incidents, error credit requests."""
from appobj import api
from store import (
    banks, customers, agreements, batches, image_requests, cycles, line_items,
    incidents, credits,
)
from util import (
    ApiError, ok, body, req_str, req_int, req_enum, new_entity, touch, pub,
    list_response, parse_date, invalid,
)
from helpers import (
    auth, require_role, R_bank, R_customer, R_cycle, R_lineitem, R_incident,
    R_credit, check_posture, bad_state, recompute_cycle_sla,
)

BS = {"BillingSpecialist"}
BA = {"BillingApprover"}
CO = {"CustomerOperator"}
INCIDENT_KINDS = {"LATE_TRANSMISSION", "LATE_IMAGE_FULFILLMENT",
                  "MISSED_CUTOFF_POSTING", "DATA_FORMAT_ERROR"}
CREDIT_REASONS = {"SLA_NOT_APPLIED", "BILLING_RATE_ERROR", "DUPLICATE_CHARGE",
                  "ECR_MISCALCULATION"}
BATCH_REF_KINDS = {"LATE_TRANSMISSION", "MISSED_CUTOFF_POSTING", "DATA_FORMAT_ERROR"}


# ---------------------------------------------------------------------------
# Analysis cycles
# ---------------------------------------------------------------------------

@api.get("/banks/<bankId>/customers/<customerId>/analysis_cycles/<cycleId>")
def get_cycle(bankId, customerId, cycleId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    cyc = R_cycle(c, cycleId)
    return ok(pub(cyc))


@api.get("/banks/<bankId>/customers/<customerId>/analysis_cycles")
def list_cycles(bankId, customerId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    rows = [x for x in cycles.values() if x["customer_id"] == c["id"]]
    return list_response(rows, ["status"])


@api.post("/banks/<bankId>/customers/<customerId>/analysis_cycles/<cycleId>/settle")
def settle_cycle(bankId, customerId, cycleId):
    uid, role = auth()
    require_role(role, BS)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    cyc = R_cycle(c, cycleId)
    b = body()
    expected = req_int(b, "expected_cycle_version")
    check_posture(bank)
    if cyc["status"] not in ("FINALIZED", "DISPUTED"):
        raise ApiError("ERR_CYCLE_NOT_FINALIZED", 409,
                       "cycle is not FINALIZED or DISPUTED")
    open_disputes = [r for r in credits.values()
                     if r["cycle_id"] == cyc["id"] and r["status"] == "SUBMITTED"]
    if open_disputes:
        raise ApiError("ERR_CYCLE_HAS_OPEN_DISPUTES", 409,
                       "cycle has unresolved error credit requests")
    if expected != cyc["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_cycle_version does not match current version")
    if cyc["status"] == "DISPUTED":
        approved = sum(r["approved_credit_cents"] or 0 for r in credits.values()
                       if r["cycle_id"] == cyc["id"]
                       and r["status"] in ("APPROVED", "PARTIALLY_APPROVED"))
        net = max(0, cyc["gross_service_charges_cents"] - cyc["earnings_credit_cents"])
        net = max(0, net - cyc["sla_credit_cents"])
        net = max(0, net - approved)
        cyc["net_amount_due_cents"] = net
    cyc["status"] = "SETTLED"
    cyc["_settled_by"] = uid
    touch(cyc)
    return ok(pub(cyc))


# ---------------------------------------------------------------------------
# Analysis line items
# ---------------------------------------------------------------------------

@api.get("/banks/<bankId>/customers/<customerId>/analysis_cycles/<cycleId>/line_items")
def list_line_items(bankId, customerId, cycleId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    cyc = R_cycle(c, cycleId)
    rows = [l for l in line_items.values() if l["cycle_id"] == cyc["id"]]
    return list_response(rows, ["line_kind"])


@api.get("/banks/<bankId>/customers/<customerId>/analysis_cycles/<cycleId>/line_items/<lineItemId>")
def get_line_item(bankId, customerId, cycleId, lineItemId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    cyc = R_cycle(c, cycleId)
    li = R_lineitem(cyc, lineItemId)
    return ok(pub(li))


# ---------------------------------------------------------------------------
# SLA incidents
# ---------------------------------------------------------------------------

@api.post("/banks/<bankId>/customers/<customerId>/sla_incidents")
def create_incident(bankId, customerId):
    uid, role = auth()
    require_role(role, CO | BS)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    b = body()
    kind = req_enum(b, "incident_kind", INCIDENT_KINDS)
    occurred = b.get("occurred_on_business_date")
    occurred = parse_date(occurred).isoformat()
    ref_batch = b.get("reference_batch_id")
    ref_request = b.get("reference_request_id")
    if kind in BATCH_REF_KINDS and not ref_batch:
        invalid("reference_batch_id is required for %s" % kind)
    if kind == "LATE_IMAGE_FULFILLMENT" and not ref_request:
        invalid("reference_request_id is required for LATE_IMAGE_FULFILLMENT")
    check_posture(bank)
    if ref_batch is not None:
        bt = batches.get(ref_batch)
        if not bt or bt["bank_id"] != bank["id"] or bt["customer_id"] != c["id"]:
            raise ApiError("ERR_INVALID_REFERENCE", 409,
                           "reference_batch_id does not resolve within scope")
    if ref_request is not None:
        rr = image_requests.get(ref_request)
        if not rr or rr["bank_id"] != bank["id"] or rr["customer_id"] != c["id"]:
            raise ApiError("ERR_INVALID_REFERENCE", 409,
                           "reference_request_id does not resolve within scope")
    inc = new_entity({
        "customer_id": c["id"],
        "bank_id": bank["id"],
        "cycle_id": None,
        "incident_kind": kind,
        "reference_batch_id": ref_batch,
        "reference_request_id": ref_request,
        "occurred_on_business_date": occurred,
        "breach_confirmed": False,
        "status": "REPORTED",
    })
    incidents[inc["id"]] = inc
    return ok(pub(inc), "object", 201)


@api.get("/banks/<bankId>/customers/<customerId>/sla_incidents/<incidentId>")
def get_incident(bankId, customerId, incidentId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    inc = R_incident(c, incidentId)
    return ok(pub(inc))


@api.get("/banks/<bankId>/customers/<customerId>/sla_incidents")
def list_incidents(bankId, customerId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    rows = [i for i in incidents.values() if i["customer_id"] == c["id"]]
    return list_response(rows, ["status", "incident_kind", "cycle_id"])


@api.post("/banks/<bankId>/customers/<customerId>/sla_incidents/<incidentId>/confirm")
def confirm_incident(bankId, customerId, incidentId):
    uid, role = auth()
    require_role(role, BS)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    inc = R_incident(c, incidentId)
    check_posture(bank)
    if inc["status"] != "REPORTED":
        raise ApiError("ERR_SLA_INCIDENT_ALREADY_REVIEWED", 409,
                       "incident is not in REPORTED status")
    inc["status"] = "CONFIRMED"
    inc["breach_confirmed"] = True
    touch(inc)
    if inc["cycle_id"]:
        cyc = cycles.get(inc["cycle_id"])
        if cyc and cyc["status"] in ("FINALIZED", "DISPUTED"):
            recompute_cycle_sla(bank, cyc)
    return ok(pub(inc))


@api.post("/banks/<bankId>/customers/<customerId>/sla_incidents/<incidentId>/reject")
def reject_incident(bankId, customerId, incidentId):
    uid, role = auth()
    require_role(role, BS)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    inc = R_incident(c, incidentId)
    check_posture(bank)
    if inc["status"] != "REPORTED":
        raise ApiError("ERR_SLA_INCIDENT_ALREADY_REVIEWED", 409,
                       "incident is not in REPORTED status")
    inc["status"] = "REJECTED"
    touch(inc)
    return ok(pub(inc))


# ---------------------------------------------------------------------------
# Error credit requests
# ---------------------------------------------------------------------------

@api.post("/banks/<bankId>/customers/<customerId>/error_credit_requests")
def create_credit(bankId, customerId):
    uid, role = auth()
    require_role(role, CO)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    b = body()
    cycle_id = req_str(b, "cycle_id")
    amount = req_int(b, "requested_credit_cents", minv=1)
    reason = req_enum(b, "reason_code", CREDIT_REASONS)
    check_posture(bank)
    cyc = cycles.get(cycle_id)
    if not cyc or cyc["bank_id"] != bank["id"] or cyc["customer_id"] != c["id"]:
        raise ApiError("ERR_INVALID_REFERENCE", 409,
                       "cycle_id does not resolve within scope")
    if cyc["status"] not in ("FINALIZED", "DISPUTED"):
        bad_state("error credits may only be filed against a FINALIZED cycle")
    r = new_entity({
        "customer_id": c["id"],
        "bank_id": bank["id"],
        "cycle_id": cyc["id"],
        "requested_credit_cents": amount,
        "reason_code": reason,
        "approved_credit_cents": None,
        "reviewed_by_user_id": None,
        "status": "SUBMITTED",
    })
    credits[r["id"]] = r
    if cyc["status"] == "FINALIZED":
        cyc["status"] = "DISPUTED"
        touch(cyc)
    return ok(pub(r), "object", 201)


@api.get("/banks/<bankId>/customers/<customerId>/error_credit_requests/<requestId>")
def get_credit(bankId, customerId, requestId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    r = R_credit(c, requestId)
    return ok(pub(r))


@api.get("/banks/<bankId>/customers/<customerId>/error_credit_requests")
def list_credits(bankId, customerId):
    uid, role = auth()
    bank = R_bank(bankId)
    c = R_customer(bank, customerId, uid, role)
    rows = [r for r in credits.values() if r["customer_id"] == c["id"]]
    return list_response(rows, ["status", "reason_code", "cycle_id"])


def _review_guard(bank, r, uid):
    if r["status"] != "SUBMITTED":
        bad_state("error credit request is not SUBMITTED")
    cyc = cycles.get(r["cycle_id"])
    if cyc and (cyc.get("_finalized_by") == uid or cyc.get("_settled_by") == uid):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409,
                       "approver must differ from the billing specialist who worked the cycle")


@api.post("/banks/<bankId>/customers/<customerId>/error_credit_requests/<requestId>/approve")
def approve_credit(bankId, customerId, requestId):
    uid, role = auth()
    require_role(role, BA)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    r = R_credit(c, requestId)
    check_posture(bank)
    _review_guard(bank, r, uid)
    r["status"] = "APPROVED"
    r["approved_credit_cents"] = r["requested_credit_cents"]
    r["reviewed_by_user_id"] = uid
    touch(r)
    return ok(pub(r))


@api.post("/banks/<bankId>/customers/<customerId>/error_credit_requests/<requestId>/approve_partial")
def approve_partial_credit(bankId, customerId, requestId):
    uid, role = auth()
    require_role(role, BA)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    r = R_credit(c, requestId)
    b = body()
    approved = req_int(b, "approved_credit_cents", minv=0)
    check_posture(bank)
    _review_guard(bank, r, uid)
    if approved >= r["requested_credit_cents"]:
        raise ApiError("ERR_CREDIT_EXCEEDS_REQUESTED", 409,
                       "approved_credit_cents must be strictly less than requested")
    r["status"] = "PARTIALLY_APPROVED"
    r["approved_credit_cents"] = approved
    r["reviewed_by_user_id"] = uid
    touch(r)
    return ok(pub(r))


@api.post("/banks/<bankId>/customers/<customerId>/error_credit_requests/<requestId>/deny")
def deny_credit(bankId, customerId, requestId):
    uid, role = auth()
    require_role(role, BA)
    bank = R_bank(bankId)
    c = R_customer(bank, customerId)
    r = R_credit(c, requestId)
    check_posture(bank)
    _review_guard(bank, r, uid)
    r["status"] = "DENIED"
    r["approved_credit_cents"] = 0
    r["reviewed_by_user_id"] = uid
    touch(r)
    return ok(pub(r))

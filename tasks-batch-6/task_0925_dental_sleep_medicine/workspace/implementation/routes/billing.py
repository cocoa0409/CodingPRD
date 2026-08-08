"""Claims, repair orders and payer audit holds."""

from flask import Blueprint, request

import calc
import domain
import validation as v
from access import (actor, body_refs, gate_device, gate_frozen, in_scope, new_row,
                    ordered, path_row, require_scope, touch)
from envelope import created, ok
from errors import fail
from serializers import dump
from store import DB, clock_date

bp = Blueprint("billing", __name__)


def _routing(patient, payer):
    if payer is None or patient is None:
        return
    if payer["id"] != patient["medical_payer_id"] or payer["payer_kind"] != "MEDICAL":
        fail("ERR_DENTAL_PAYER_ROUTING", "Oral appliance therapy is a medical benefit.")


# ------------------------------------------------------------------- claims

@bp.post("/claims")
def create_claim():
    uid, role = actor(["BillingSpecialist"])
    body = v.read_body()
    refs = body_refs(body, ["patient_id", "payer_id", "appliance_id",
                            "prior_auth_id", "written_order_id", "repair_order_id"])
    gate_frozen(refs["patient_id"])
    fields = [
        v.S("patient_id", required=True),
        v.S("payer_id", required=True),
        v.S("appliance_id", required=True),
        v.S("claim_type", required=True, enum=v.ENUM_CLAIM_TYPE),
        v.S("hcpcs_code", required=True, enum=v.ENUM_HCPCS),
        v.D("date_of_service", required=True),
        v.I("billed_cents", required=True),
        v.S("prior_auth_id"),
        v.S("written_order_id"),
        v.S("repair_order_id"),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    date_of_service = v.date_of(body, "date_of_service")
    v.at_least(body, "billed_cents", 0)
    appliance = refs["appliance_id"]
    if body["claim_type"] in ("INITIAL_DEVICE", "REPLACEMENT"):
        if appliance["delivered_on"] is None or date_of_service != appliance["delivered_on"]:
            fail("ERR_VALIDATION", "date_of_service must equal the appliance's delivered_on.")
    gate_device(appliance)
    _routing(refs["patient_id"], refs["payer_id"])
    row = new_row("claims", {
        "patient_id": body["patient_id"],
        "payer_id": body["payer_id"],
        "appliance_id": body["appliance_id"],
        "prior_auth_id": body.get("prior_auth_id"),
        "written_order_id": body.get("written_order_id"),
        "repair_order_id": body.get("repair_order_id"),
        "claim_type": body["claim_type"],
        "hcpcs_code": body["hcpcs_code"],
        "date_of_service": date_of_service,
        "billed_cents": body["billed_cents"],
        "allowed_cents": None,
        "deductible_applied_cents": None,
        "coinsurance_cents": None,
        "patient_responsibility_cents": None,
        "payer_paid_cents": None,
        "adjustment_cents": None,
        "denial_error_id": None,
        "appeal_attempts": 0,
        "status": "DRAFT",
    })
    return created(dump("claim", row))


@bp.get("/claims/<claim_id>")
def read_claim(claim_id):
    uid, role = actor(["BillingSpecialist", "PlatformAdmin", "Dentist"])
    row = path_row("claim_id", claim_id)
    require_scope(role, uid, row["patient_id"])
    return ok(dump("claim", row))


@bp.get("/claims")
def list_claims():
    uid, role = actor(["BillingSpecialist", "PlatformAdmin", "Dentist"])
    limit, offset = v.pagination()
    filters = {
        "patient_id": request.args.get("patient_id"),
        "payer_id": request.args.get("payer_id"),
        "appliance_id": request.args.get("appliance_id"),
        "prior_auth_id": request.args.get("prior_auth_id"),
        "written_order_id": request.args.get("written_order_id"),
        "repair_order_id": request.args.get("repair_order_id"),
        "status": request.args.get("status"),
    }
    return domain.paginate("claim", "claims", filters, limit, offset,
                           lambda r: in_scope(role, uid, r["patient_id"]))


@bp.post("/claims/<claim_id>/submit")
def submit_claim(claim_id):
    uid, role = actor(["BillingSpecialist"])
    claim = path_row("claim_id", claim_id)
    body = v.read_body()
    patient = DB["patients"].get(claim["patient_id"])
    appliance = DB["appliances"].get(claim["appliance_id"])
    payer = DB["payers"].get(claim["payer_id"])
    gate_frozen(patient)
    v.rung7(body, [])
    if claim["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT claim may be submitted.")
    gate_device(appliance)

    claim_type = claim["claim_type"]
    # Rung 24 — cross-provider loop closure.
    if claim_type == "CONTINUED_USE":
        referral = domain.referral_of_appliance(appliance)
        if referral is None or referral["loop_status"] != "CLOSED":
            fail("ERR_EFFICACY_LOOP_OPEN", "The efficacy loop is still open.")
    # Rung 25 — medical benefit routing.
    _routing(patient, payer)
    # Rungs 26, 27 and 28 — the standard written order.
    if claim_type in ("INITIAL_DEVICE", "REPLACEMENT"):
        domain.swo_ladder(claim["patient_id"], claim["hcpcs_code"], appliance["delivered_on"])
    # Rung 29 — prior authorisation, mutate then reject.
    if payer is not None and payer["prior_auth_required"]:
        auth = DB["prior_auths"].get(claim["prior_auth_id"]) if claim["prior_auth_id"] else None
        if auth is None or auth["status"] != "APPROVED":
            fail("ERR_PRIOR_AUTH_REQUIRED", "An APPROVED prior authorisation is required.")
        valid_until = auth["approval_valid_until"]
        if valid_until is None or clock_date() > valid_until:
            auth["status"] = "EXPIRED"
            touch(auth)
            fail("ERR_PRIOR_AUTH_REQUIRED", "The prior authorisation has expired.")
    # Rung 30 — proof of delivery.
    if claim_type in ("INITIAL_DEVICE", "REPLACEMENT", "CONTINUED_USE"):
        if appliance["pod_signed_on"] is None or appliance["pod_method"] is None:
            fail("ERR_POD_MISSING", "No proof of delivery is on file.")
    # Rung 31 — useful lifetime.
    if claim_type == "REPLACEMENT":
        predecessor = DB["appliances"].get(appliance.get("replaces_appliance_id"))
        end_date = predecessor["useful_lifetime_end_date"] if predecessor else None
        if end_date is None or claim["date_of_service"] <= end_date:
            fail("ERR_USEFUL_LIFETIME_NOT_ELAPSED", "The predecessor's useful lifetime has not elapsed.")
    # Rung 32 — repair billability.
    repair_order = DB["repair_orders"].get(claim["repair_order_id"]) if claim["repair_order_id"] else None
    if claim_type == "REPAIR":
        if repair_order is None or not repair_order["billable"]:
            fail("ERR_REPAIR_NOT_BILLABLE", "The linked repair order is not billable.")
    # Rung 33 — objective adherence and a live recall posture.
    if claim_type == "CONTINUED_USE":
        downloads = [d for d in DB["adherence_downloads"].values()
                     if d["appliance_id"] == appliance["id"]
                     and d["source"] == "OBJECTIVE_MICRORECORDER"]
        newest_objective = ordered(downloads)[-1] if downloads else None
        if newest_objective is None or not newest_objective["compliant"]:
            fail("ERR_ADHERENCE_NOT_MET", "No compliant objective adherence download is on file.")
        if appliance["recall_status"] == "LAPSED":
            fail("ERR_ADHERENCE_NOT_MET", "The patient recall has lapsed.")

    basis = calc.fee_basis(claim["hcpcs_code"], repair_order)
    allowed, adjustment = calc.claim_allowed(claim["billed_cents"], basis)
    claim["allowed_cents"] = allowed
    claim["adjustment_cents"] = adjustment
    claim["status"] = "SUBMITTED"
    touch(claim)
    return ok(dump("claim", claim))


@bp.post("/claims/<claim_id>/adjudicate")
def adjudicate_claim(claim_id):
    uid, role = actor(["PlatformAdmin"])
    claim = path_row("claim_id", claim_id)
    body = v.read_body()
    patient = DB["patients"].get(claim["patient_id"])
    payer = DB["payers"].get(claim["payer_id"])
    appliance = DB["appliances"].get(claim["appliance_id"])
    gate_frozen(patient)
    fields = [
        v.S("outcome", required=True, enum=v.ENUM_CLAIM_OUTCOME),
        v.S("denial_error_id"),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    if claim["status"] not in ("SUBMITTED", "APPEALED"):
        fail("ERR_INVALID_STATE", "Only a submitted or appealed claim may be adjudicated.")
    gate_device(appliance)

    if body["outcome"] == "PAID":
        deductible, coinsurance, responsibility, payer_paid = calc.patient_responsibility(
            claim["allowed_cents"] or 0,
            patient["deductible_remaining_cents"],
            payer["coinsurance_pct"] if payer else 0.20)
        claim["deductible_applied_cents"] = deductible
        claim["coinsurance_cents"] = coinsurance
        claim["patient_responsibility_cents"] = responsibility
        claim["payer_paid_cents"] = payer_paid
        claim["status"] = "PAID"
        touch(claim)
        if deductible:
            patient["deductible_remaining_cents"] = patient["deductible_remaining_cents"] - deductible
            touch(patient)
    else:
        claim["denial_error_id"] = body.get("denial_error_id")
        limit = payer["appeal_limit"] if payer else 0
        claim["status"] = "DENIED_FINAL" if claim["appeal_attempts"] >= limit else "DENIED"
        touch(claim)
    return ok(dump("claim", claim))


@bp.post("/claims/<claim_id>/appeal")
def appeal_claim(claim_id):
    uid, role = actor(["BillingSpecialist"])
    claim = path_row("claim_id", claim_id)
    body = v.read_body()
    gate_frozen(DB["patients"].get(claim["patient_id"]))
    fields = [v.S("narrative", required=True)]
    v.rung7(body, fields)
    v.rung8(body, fields)
    if claim["status"] not in ("DENIED", "DENIED_FINAL"):
        fail("ERR_INVALID_STATE", "Only a denied claim may be appealed.")
    payer = DB["payers"].get(claim["payer_id"])
    limit = payer["appeal_limit"] if payer else 0
    if claim["appeal_attempts"] >= limit:
        fail("ERR_APPEAL_LIMIT_REACHED", "The payer's appeal limit has been reached.")
    claim["appeal_attempts"] = claim["appeal_attempts"] + 1
    claim["status"] = "APPEALED"
    touch(claim)
    return ok(dump("claim", claim))


# ------------------------------------------------------------ repair orders

@bp.post("/repair-orders")
def create_repair_order():
    uid, role = actor(["Dentist"])
    body = v.read_body()
    refs = body_refs(body, ["appliance_id", "loaner_appliance_id"])
    appliance = refs["appliance_id"]
    if appliance is not None:
        gate_frozen(DB["patients"].get(appliance["patient_id"]))
        require_scope(role, uid, appliance["patient_id"])
    fields = [
        v.S("appliance_id", required=True),
        v.S("reason", required=True, enum=v.ENUM_REPAIR_REASON),
        v.D("reported_on", required=True),
        v.I("labor_minutes"),
        v.S("loaner_appliance_id"),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    reported_on = v.date_of(body, "reported_on")
    v.at_least(body, "labor_minutes", 0)
    if appliance["lifecycle_status"] in ("FABRICATED", "RETIRED", "REPLACED"):
        fail("ERR_INVALID_STATE", "The device is not in a repairable state.")
    gate_device(appliance)
    loaner_id = body.get("loaner_appliance_id")
    if loaner_id is not None:
        for other in DB["repair_orders"].values():
            if other.get("loaner_appliance_id") != loaner_id:
                continue
            returned = other.get("returned_on")
            if returned is None or reported_on < returned:
                fail("ERR_LOANER_UNAVAILABLE", "The loaner device is already occupied.")

    labor_minutes = v.get(body, "labor_minutes", 0)
    in_warranty, billable, labor_units, charge = calc.repair_billability(
        body["reason"], reported_on, appliance["warranty_end_date"], labor_minutes)
    if body["reason"] == "LOSS":
        billable = True
        charge = 0
    row = new_row("repair_orders", {
        "appliance_id": appliance["id"],
        "loaner_appliance_id": loaner_id,
        "reason": body["reason"],
        "reported_on": reported_on,
        "labor_minutes": labor_minutes,
        "returned_on": None,
        "in_warranty": in_warranty,
        "billable": billable,
        "labor_units": labor_units,
        "repair_charge_cents": charge,
        "resets_useful_lifetime": False,
        "status": "CLOSED_NOT_COVERED" if body["reason"] == "LOSS" else "IN_LAB",
    })
    if body["reason"] == "LOSS":
        domain.retire_appliance(appliance)
    return created(dump("repair_order", row))


@bp.get("/repair-orders/<repair_order_id>")
def read_repair_order(repair_order_id):
    uid, role = actor(["Dentist", "BillingSpecialist", "PlatformAdmin"])
    row = path_row("repair_order_id", repair_order_id)
    appliance = DB["appliances"].get(row["appliance_id"])
    if appliance is not None:
        require_scope(role, uid, appliance["patient_id"])
    return ok(dump("repair_order", row))


@bp.get("/repair-orders")
def list_repair_orders():
    uid, role = actor(["Dentist", "BillingSpecialist", "PlatformAdmin"])
    limit, offset = v.pagination()
    filters = {
        "appliance_id": request.args.get("appliance_id"),
        "loaner_appliance_id": request.args.get("loaner_appliance_id"),
        "status": request.args.get("status"),
    }

    def scope_pred(row):
        appliance = DB["appliances"].get(row["appliance_id"])
        return appliance is not None and in_scope(role, uid, appliance["patient_id"])

    return domain.paginate("repair_order", "repair_orders", filters, limit, offset, scope_pred)


@bp.post("/repair-orders/<repair_order_id>/complete")
def complete_repair_order(repair_order_id):
    uid, role = actor(["Dentist"])
    repair = path_row("repair_order_id", repair_order_id)
    body = v.read_body()
    appliance = DB["appliances"].get(repair["appliance_id"])
    if appliance is not None:
        gate_frozen(DB["patients"].get(appliance["patient_id"]))
        require_scope(role, uid, appliance["patient_id"])
    fields = [v.S("outcome", required=True, enum=v.ENUM_REPAIR_OUTCOME)]
    v.rung7(body, fields)
    v.rung8(body, fields)
    if repair["status"] != "IN_LAB":
        fail("ERR_INVALID_STATE", "Only a repair in the laboratory may be completed.")
    gate_device(appliance)
    repair["returned_on"] = clock_date()
    if body["outcome"] == "REPAIRED":
        repair["status"] = "CLOSED_REPAIRED"
    else:
        repair["status"] = "CLOSED_NOT_COVERED"
        repair["repair_charge_cents"] = 0
    touch(repair)
    return ok(dump("repair_order", repair))


# -------------------------------------------------------------- audit holds

@bp.post("/audit-holds")
def create_audit_hold():
    actor(["PlatformAdmin"])
    body = v.read_body()
    refs = body_refs(body, ["patient_id", "payer_id"])
    fields = [
        v.S("patient_id", required=True),
        v.S("payer_id", required=True),
        v.S("scope_note"),
    ]
    v.rung7(body, fields)
    v.rung8(body, fields)
    patient = refs["patient_id"]
    row = new_row("audit_holds", {
        "patient_id": patient["id"],
        "payer_id": body["payer_id"],
        "opened_on": clock_date(),
        "closed_on": None,
        "scope_note": body.get("scope_note"),
        "status": "OPEN",
    })
    domain.recompute_records_frozen(patient)
    return created(dump("audit_hold", row))


@bp.get("/audit-holds/<audit_hold_id>")
def read_audit_hold(audit_hold_id):
    actor(["PlatformAdmin", "BillingSpecialist"])
    row = path_row("audit_hold_id", audit_hold_id)
    return ok(dump("audit_hold", row))


@bp.get("/audit-holds")
def list_audit_holds():
    actor(["PlatformAdmin", "BillingSpecialist"])
    limit, offset = v.pagination()
    filters = {
        "patient_id": request.args.get("patient_id"),
        "payer_id": request.args.get("payer_id"),
        "status": request.args.get("status"),
    }
    return domain.paginate("audit_hold", "audit_holds", filters, limit, offset)


@bp.post("/audit-holds/<audit_hold_id>/close")
def close_audit_hold(audit_hold_id):
    actor(["PlatformAdmin"])
    hold = path_row("audit_hold_id", audit_hold_id)
    body = v.read_body()
    v.rung7(body, [])
    if hold["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Only an OPEN audit hold may be closed.")
    hold["status"] = "CLOSED"
    hold["closed_on"] = clock_date()
    touch(hold)
    patient = DB["patients"].get(hold["patient_id"])
    if patient is not None:
        domain.recompute_records_frozen(patient)
    return ok(dump("audit_hold", hold))

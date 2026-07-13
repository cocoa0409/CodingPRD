"""Derived computations, calculations, serializers, and safety cascades."""

from decimal import ROUND_HALF_UP, Decimal

import constants as C
from store import base_fields, db, touch

# Decimal versions of rate/factor constants (avoid binary-float artifacts) -----
_RISK_MULT_D = {"HIGH": Decimal("1.5"), "MEDIUM": Decimal("1.2"), "LOW": Decimal("1.0")}
_LATE_RATE_D = Decimal("0.10")
_LATE_CAP_D = Decimal("1.0")
_INDEX_RATE_D = Decimal("0.0725")
_UNSUB_FACTOR_D = Decimal("0.25")


def rhu(value):
    """Round half up to a whole integer. `value` must be a Decimal."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Derived-quantity queries
# ---------------------------------------------------------------------------

def device_citations(device_id):
    return [c for c in db.citations.values() if c["device_id"] == device_id]


def device_fees(device_id):
    return [f for f in db.fee_invoices.values() if f["device_id"] == device_id]


def device_certs(device_id):
    return [c for c in db.certificates.values() if c["device_id"] == device_id]


def device_deficiencies(device_id):
    return [d for d in db.deficiencies.values() if d["device_id"] == device_id]


def device_inspections(device_id):
    return [i for i in db.inspections.values() if i["device_id"] == device_id]


def effective_fee_status(fee):
    if fee["status"] == "PENDING" and db.current_period_index > fee["due_period"]:
        return "OVERDUE"
    return fee["status"]


def effective_cert_status(cert):
    if cert["status"] in ("ISSUED", "POSTED") and db.current_period_index > cert["expiry_period"]:
        return "EXPIRED"
    return cert["status"]


def outstanding_balance(device_id):
    citations_part = sum(
        c["surcharged_amount_cents"]
        for c in device_citations(device_id)
        if c["status"] in ("ISSUED", "CONTESTED")
    )
    fees_part = sum(
        f["amount_cents"]
        for f in device_fees(device_id)
        if effective_fee_status(f) in ("PENDING", "OVERDUE")
    )
    return citations_part + fees_part


def active_oos_count(device_id):
    return sum(
        1 for o in db.oos_orders.values()
        if o["device_id"] == device_id and o["status"] == "ACTIVE"
    )


def active_assignment_count(inspector_id):
    return sum(
        1 for i in db.inspections.values()
        if i.get("assigned_inspector_id") == inspector_id
        and i["status"] in ("ASSIGNED", "IN_PROGRESS")
    )


def current_certificate_id(device_id):
    for c in device_certs(device_id):
        if effective_cert_status(c) in ("ISSUED", "POSTED"):
            return c["id"]
    return None


def active_cert(device):
    """The device's certificate currently ISSUED or POSTED (stored), if any."""
    for c in device_certs(device["id"]):
        if c["status"] in ("ISSUED", "POSTED"):
            return c
    return None


def suspended_cert(device):
    for c in device_certs(device["id"]):
        if c["status"] == "SUSPENDED":
            return c
    return None


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def compute_citation_fine(device, severity):
    base = C.BASE_FINE_CENTS[severity]
    risk_adjusted = rhu(Decimal(base) * _RISK_MULT_D[device["risk_class"]])
    repeat_count = sum(
        1 for c in device_citations(device["id"])
        if c["status"] in ("ISSUED", "CONTESTED", "PAID")
    )
    capped = min(repeat_count, C.REPEAT_SURCHARGE_CAP_COUNT)
    repeat_surcharge = capped * C.REPEAT_SURCHARGE_CENTS
    fine = min(risk_adjusted + repeat_surcharge, C.FINE_CAP_CENTS)
    surcharged = rhu(Decimal(fine) * (Decimal(1) + _INDEX_RATE_D))
    return fine, surcharged


def compute_fee_final_amount(fee_type, category, due_period, paid_period):
    if fee_type == "REGISTRATION":
        base = C.REGISTRATION_FEE_CENTS
    else:
        base = C.BASE_RENEWAL_FEE_CENTS[category]
    months_overdue = max(0, paid_period - due_period)
    accrued = rhu(Decimal(base) * _LATE_RATE_D * Decimal(months_overdue))
    cap = rhu(Decimal(base) * _LATE_CAP_D)
    penalty = min(accrued, cap)
    return base + penalty


def compute_fee_provisional_amount(fee_type, category):
    if fee_type == "REGISTRATION":
        return C.REGISTRATION_FEE_CENTS
    return C.BASE_RENEWAL_FEE_CENTS[category]


def compute_accident_final_score(report, device, finding):
    weight = C.SEVERITY_WEIGHT[report["severity"]]
    if finding == "SUBSTANTIATED":
        risk_part = rhu(Decimal(weight) * _RISK_MULT_D[device["risk_class"]])
        crit = sum(
            1 for d in device_deficiencies(device["id"])
            if d["severity"] == "CRITICAL" and d["status"] in ("OPEN", "CITED")
        )
        return risk_part + C.OPEN_CRITICAL_DEFICIENCY_BONUS * crit
    return rhu(Decimal(weight) * _UNSUB_FACTOR_D)


# ---------------------------------------------------------------------------
# Citation issuance (shared by POST /citations and the FAIL cascade)
# ---------------------------------------------------------------------------

def issue_citation(deficiency, device):
    """Create an ISSUED citation against `deficiency`; move it to CITED.

    The device's outstanding balance is derived from citation status, so the
    ISSUED citation automatically enters the ledger with no explicit debit.
    Fine calculation counts prior citations before this one is added.
    """
    fine, surcharged = compute_citation_fine(device, deficiency["severity"])
    cit = base_fields()
    cit.update({
        "deficiency_id": deficiency["id"],
        "device_id": device["id"],
        "fine_amount_cents": fine,
        "surcharged_amount_cents": surcharged,
        "issued_period": db.current_period_index,
        "due_period": db.current_period_index + C.CITATION_DUE_GRACE_MONTHS,
        "contest_count": 0,
        "status": "ISSUED",
    })
    db.citations[cit["id"]] = cit
    deficiency["status"] = "CITED"
    touch(deficiency)
    return cit


# ---------------------------------------------------------------------------
# Out-of-service propagation (§2.8)
# ---------------------------------------------------------------------------

def create_oos_order(device, reason, start, end, citation_id=None):
    """Create an ACTIVE order and apply its activation propagation.

    Used both by the manual endpoint (after its overlap check) and by the
    internal safety cascades (which skip the overlap check).
    """
    order = base_fields()
    order.update({
        "device_id": device["id"],
        "citation_id": citation_id,
        "reason": reason,
        "effective_start_period": start,
        "effective_end_period": end,
        "lifted_period": None,
        "status": "ACTIVE",
    })
    db.oos_orders[order["id"]] = order
    _apply_oos_activation(device)
    return order


def _apply_oos_activation(device):
    if device["status"] in ("REGISTERED", "ACTIVE"):
        device["status"] = "OUT_OF_SERVICE"
        touch(device)
    cert = active_cert(device)
    if cert is not None:
        cert["_pre_suspension_status"] = cert["status"]
        cert["status"] = "SUSPENDED"
        touch(cert)


def lift_oos_order(order):
    order["status"] = "LIFTED"
    order["lifted_period"] = db.current_period_index
    touch(order)
    device = db.devices[order["device_id"]]
    if active_oos_count(device["id"]) == 0:
        if device["status"] == "OUT_OF_SERVICE":
            device["status"] = "ACTIVE"
            touch(device)
        cert = suspended_cert(device)
        if cert is not None:
            if cert.get("_pre_suspension_status") == "POSTED":
                cert["status"] = "POSTED"
            else:
                cert["status"] = "REVOKED"
            cert["_pre_suspension_status"] = None
            touch(cert)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_owner(o):
    d = _common(o)
    d.update({"name": o["name"], "contact_email": o["contact_email"]})
    return d


def serialize_inspector(i):
    d = _common(i)
    d.update({
        "name": i["name"],
        "license_number": i["license_number"],
        "license_expiry_period": i["license_expiry_period"],
        "certified_categories": list(i["certified_categories"]),
        "active_assignment_count": active_assignment_count(i["id"]),
    })
    return d


def serialize_device(dev):
    d = _common(dev)
    d.update({
        "owner_id": dev["owner_id"],
        "category": dev["category"],
        "location_description": dev["location_description"],
        "install_period": dev["install_period"],
        "risk_class": dev["risk_class"],
        "status": dev["status"],
        "next_inspection_due_period": dev["next_inspection_due_period"],
        "outstanding_balance_cents": outstanding_balance(dev["id"]),
        "accident_risk_score": dev["accident_risk_score"],
        "current_certificate_id": current_certificate_id(dev["id"]),
        "active_oos_count": active_oos_count(dev["id"]),
    })
    return d


def serialize_inspection(i):
    d = _common(i)
    d.update({
        "device_id": i["device_id"],
        "assigned_inspector_id": i["assigned_inspector_id"],
        "type": i["type"],
        "scheduled_start_period": i["scheduled_start_period"],
        "scheduled_end_period": i["scheduled_end_period"],
        "performed_period": i["performed_period"],
        "status": i["status"],
    })
    return d


def serialize_deficiency(d0):
    d = _common(d0)
    d.update({
        "inspection_id": d0["inspection_id"],
        "device_id": d0["device_id"],
        "code": d0["code"],
        "severity": d0["severity"],
        "description": d0["description"],
        "resolution_due_period": d0["resolution_due_period"],
        "status": d0["status"],
    })
    return d


def serialize_citation(c):
    d = _common(c)
    d.update({
        "deficiency_id": c["deficiency_id"],
        "device_id": c["device_id"],
        "fine_amount_cents": c["fine_amount_cents"],
        "surcharged_amount_cents": c["surcharged_amount_cents"],
        "issued_period": c["issued_period"],
        "due_period": c["due_period"],
        "contest_count": c["contest_count"],
        "status": c["status"],
    })
    return d


def serialize_certificate(c):
    d = _common(c)
    d.update({
        "device_id": c["device_id"],
        "source_inspection_id": c["source_inspection_id"],
        "certificate_number": c["certificate_number"],
        "issue_period": c["issue_period"],
        "expiry_period": c["expiry_period"],
        "posted_period": c["posted_period"],
        "status": effective_cert_status(c),
    })
    return d


def serialize_oos(o):
    d = _common(o)
    d.update({
        "device_id": o["device_id"],
        "citation_id": o["citation_id"],
        "reason": o["reason"],
        "effective_start_period": o["effective_start_period"],
        "effective_end_period": o["effective_end_period"],
        "lifted_period": o["lifted_period"],
        "status": o["status"],
    })
    return d


def serialize_fee(f):
    d = _common(f)
    d.update({
        "device_id": f["device_id"],
        "type": f["type"],
        "amount_cents": f["amount_cents"],
        "due_period": f["due_period"],
        "paid_period": f["paid_period"],
        "status": effective_fee_status(f),
    })
    return d


def serialize_accident(a):
    d = _common(a)
    d.update({
        "device_id": a["device_id"],
        "lead_investigator_id": a["lead_investigator_id"],
        "severity": a["severity"],
        "occurred_period": a["occurred_period"],
        "description": a["description"],
        "provisional_risk_score": a["provisional_risk_score"],
        "final_risk_score": a["final_risk_score"],
        "status": a["status"],
    })
    return d

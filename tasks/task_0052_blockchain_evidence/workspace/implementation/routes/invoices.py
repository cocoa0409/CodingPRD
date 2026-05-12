"""Invoice routes."""
from flask import Blueprint, g

import db
from clock import iso, now, parse_iso
from errors import err
from middleware import require_auth
from response import success
from services import audit
from services.lookup import get_batch, get_customer, get_evidence, get_invoice
from services.validation import get_body, require_enum, require_str


bp = Blueprint("invoices", __name__)

VALID_SCOPES = {"SINGLE_EVIDENCE", "SINGLE_BATCH", "BILLING_PERIOD"}


def _public(inv: dict) -> dict:
    return {
        "id": inv["id"],
        "customer_id": inv["customer_id"],
        "scope": inv["scope"],
        "scope_ref_id": inv.get("scope_ref_id"),
        "period_start": inv.get("period_start"),
        "period_end": inv.get("period_end"),
        "total_cents": inv["total_cents"],
        "status": inv["status"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


@bp.route("/invoices", methods=["POST"])
@require_auth(roles={"Customer", "PlatformAdmin"})
def issue_invoice():
    body = get_body()
    customer_id = require_str(body, "customer_id")
    scope = require_enum(body, "scope", VALID_SCOPES)
    scope_ref_id = body.get("scope_ref_id")
    period_start = body.get("period_start")
    period_end = body.get("period_end")

    # ownership when caller is Customer
    if g.user_role == "Customer" and g.user_id != customer_id:
        raise err("ERR_PERMISSION_DENIED",
                  "X-User-ID does not match body customer_id")

    get_customer(customer_id, body_ref=True)

    total = 0
    if scope == "SINGLE_EVIDENCE":
        if not isinstance(scope_ref_id, str):
            raise err("ERR_VALIDATION_FAILED",
                      "scope_ref_id required for SINGLE_EVIDENCE")
        ev = db.evidences.get(scope_ref_id)
        if ev is None:
            raise err("ERR_NOT_FOUND", f"Evidence {scope_ref_id} not found")
        if ev["customer_id"] != customer_id:
            raise err("ERR_PERMISSION_DENIED",
                      "Evidence does not belong to this customer")
        if ev["status"] != "CONFIRMED" or ev.get("per_evidence_fee_cents") is None:
            raise err("ERR_INVOICE_SCOPE_INVALID",
                      "Evidence must be CONFIRMED with a recorded fee")
        total = ev["per_evidence_fee_cents"]
    elif scope == "SINGLE_BATCH":
        if not isinstance(scope_ref_id, str):
            raise err("ERR_VALIDATION_FAILED",
                      "scope_ref_id required for SINGLE_BATCH")
        b = db.batches.get(scope_ref_id)
        if b is None:
            raise err("ERR_NOT_FOUND", f"Batch {scope_ref_id} not found")
        if b["customer_id"] != customer_id:
            raise err("ERR_PERMISSION_DENIED",
                      "Batch does not belong to this customer")
        if b["status"] != "CONFIRMED" or b.get("total_fee_cents") is None:
            raise err("ERR_INVOICE_SCOPE_INVALID",
                      "Batch must be CONFIRMED with a pinned total fee")
        total = b["total_fee_cents"]
    else:  # BILLING_PERIOD
        if not isinstance(period_start, str) or not isinstance(period_end, str):
            raise err("ERR_VALIDATION_FAILED",
                      "period_start and period_end required for BILLING_PERIOD")
        try:
            ps = parse_iso(period_start)
            pe = parse_iso(period_end)
        except ValueError as e:
            raise err("ERR_PERIOD_INVALID", f"Invalid period timestamps: {e}")
        if ps > pe:
            raise err("ERR_PERIOD_INVALID", "period_start must be <= period_end")
        if pe > now():
            raise err("ERR_PERIOD_INVALID", "period_end must be <= server current time")

        # Sum fees within [ps, pe] inclusive for this customer:
        # - CONFIRMED Evidence at confirmed_at  -> per_evidence_fee_cents
        # - CONFIRMED Batch at confirmed_at     -> total_fee_cents
        # - SEALED JudicialPackage at updated_at -> surcharge_cents
        for ev in db.evidences.values():
            if ev["customer_id"] != customer_id:
                continue
            if ev["status"] != "CONFIRMED" and ev["status"] != "EXPIRED":
                continue
            if ev.get("per_evidence_fee_cents") is None:
                continue
            # confirmed_at must be set
            if not ev.get("confirmed_at"):
                continue
            try:
                ca = parse_iso(ev["confirmed_at"])
            except ValueError:
                continue
            if ps <= ca <= pe:
                total += ev["per_evidence_fee_cents"]
        for b in db.batches.values():
            if b["customer_id"] != customer_id:
                continue
            if b["status"] != "CONFIRMED":
                continue
            if b.get("total_fee_cents") is None:
                continue
            ca_iso = b.get("_confirmed_at") or b.get("updated_at")
            if not ca_iso:
                continue
            try:
                ca = parse_iso(ca_iso)
            except ValueError:
                continue
            if ps <= ca <= pe:
                total += b["total_fee_cents"]
        for pkg in db.judicial_packages.values():
            if pkg["status"] not in ("SEALED", "DELIVERED"):
                continue
            # The fee was debited at the SEALED transition; for DELIVERED
            # packages the seal happened earlier — we accept the package's
            # updated_at when seal -> deliver is not the most recent change.
            # We use the dedicated sealed timestamp captured below.
            ev = db.evidences.get(pkg["evidence_id"])
            if ev is None or ev["customer_id"] != customer_id:
                continue
            sealed_at_iso = pkg.get("_sealed_at")
            if not sealed_at_iso:
                continue
            try:
                sa = parse_iso(sealed_at_iso)
            except ValueError:
                continue
            if ps <= sa <= pe and pkg.get("surcharge_cents") is not None:
                total += pkg["surcharge_cents"]

    inv = {
        "customer_id": customer_id,
        "scope": scope,
        "scope_ref_id": scope_ref_id if scope != "BILLING_PERIOD" else None,
        "period_start": period_start if scope == "BILLING_PERIOD" else None,
        "period_end": period_end if scope == "BILLING_PERIOD" else None,
        "total_cents": total,
        "status": "ISSUED",
    }
    db.stamp_create(inv, common_fields=True)
    db.invoices[inv["id"]] = inv

    audit.append(
        event_type="INVOICE_ISSUED",
        target_entity="Invoice",
        target_id=inv["id"],
        detail={"scope": scope, "total_cents": total},
    )
    return success(_public(inv), 201)


@bp.route("/invoices/<i_id>", methods=["GET"])
@require_auth(roles={"Customer", "PlatformAdmin"})
def read_invoice(i_id):
    inv = get_invoice(i_id)
    if g.user_role == "Customer" and g.user_id != inv["customer_id"]:
        raise err("ERR_PERMISSION_DENIED", "Cannot read this invoice")
    return success(_public(inv), 200)

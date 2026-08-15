"""Certificate grants, validity windows, suspension cascade (PRD 3.6)."""
from decimal import Decimal

from flask import Blueprint, request

import clock
import store
from auth import ALL_ROLES, authenticate, authorize
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CERT_WINDOW_CONFLICT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INVALID_WINDOW,
    raise_err,
)
from services import (
    BATCH_HOLDABLE_STATES,
    cancel_scheduled_runs_of_batch,
    certificate_out,
    CERT_TYPES,
)
from util import (
    body_json, bump, get_or_404, list_response, new_record, req_date,
    req_enum, req_num, success_object,
)

bp = Blueprint("certificates", __name__)


def _cert_or_404(cid):
    return get_or_404(store.certificates, cid, "CertificateGrant")


@bp.route("/tea-ops/certificates", methods=["POST"])
def create_certificate():
    _, role = authenticate()
    authorize(role, ["CertificationOfficer"])
    body = body_json()
    # Priority 3: body FK resolution.
    supplier_id = body.get("supplier_id")
    supplier = None
    if supplier_id is not None:
        supplier = get_or_404(store.suppliers, supplier_id, "Supplier")
    # Priority 13: field shape.
    if not isinstance(supplier_id, str) or not supplier_id:
        raise_err(ERR_INVALID_REQUEST, "supplier_id is required and must be a string")
    cert_type = req_enum(body, "cert_type", CERT_TYPES)
    total_volume_kg = req_num(body, "total_volume_kg")
    if total_volume_kg <= 0:
        raise_err(ERR_INVALID_REQUEST, "total_volume_kg must be strictly positive")
    valid_from = req_date(body, "valid_from")
    valid_until = req_date(body, "valid_until")
    # Priority 9: window validity, then closed-interval overlap per
    # (supplier_id, cert_type) against ACTIVE / SUSPENDED grants.
    if valid_from >= valid_until:
        raise_err(ERR_INVALID_WINDOW, "valid_from must be strictly before valid_until")
    for other in store.certificates.values():
        if (
            other["supplier_id"] == supplier["id"]
            and other["cert_type"] == cert_type
            and other["status"] in ("ACTIVE", "SUSPENDED")
            and valid_from <= other["valid_until"]
            and other["valid_from"] <= valid_until
        ):
            # Closed intervals: shared boundary dates count as overlap.
            raise_err(
                ERR_CERT_WINDOW_CONFLICT,
                "Validity interval overlaps an existing grant for this "
                "supplier and cert_type",
            )

    rec = new_record()
    rec.update({
        "supplier_id": supplier["id"],
        "cert_type": cert_type,
        "total_volume_kg": total_volume_kg,
        "consumed_volume_kg": Decimal("0"),
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "ACTIVE",
    })
    store.certificates[rec["id"]] = rec
    return success_object(certificate_out(rec), 201)


@bp.route("/tea-ops/certificates/<cid>", methods=["GET"])
def get_certificate(cid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success_object(certificate_out(_cert_or_404(cid)))


@bp.route("/tea-ops/certificates", methods=["GET"])
def list_certificates():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.certificates.values())
    supplier_id = request.args.get("supplier_id")
    cert_type = request.args.get("cert_type")
    status = request.args.get("status")
    if supplier_id is not None:
        records = [r for r in records if r["supplier_id"] == supplier_id]
    if cert_type is not None:
        records = [r for r in records if r["cert_type"] == cert_type]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records, certificate_out)


@bp.route("/tea-ops/certificates/<cid>/suspend", methods=["POST"])
def suspend_certificate(cid):
    _, role = authenticate()
    authorize(role, ["CertificationOfficer"])
    cert = _cert_or_404(cid)
    if cert["status"] == "EXPIRED":
        raise_err(ERR_ALREADY_TERMINAL, "CertificateGrant is EXPIRED")
    if cert["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "CertificateGrant is not ACTIVE")
    cert["status"] = "SUSPENDED"
    bump(cert)

    # Cascade (enters at link 2): batches whose recipe targets this cert_type,
    # holding an ACTIVE allocation from a lot of this supplier, in a holdable
    # state -> ON_HOLD; their SCHEDULED runs -> CANCELLED.
    for batch in sorted(store.batches.values(), key=lambda b: b["_seq"]):
        if batch["status"] not in BATCH_HOLDABLE_STATES:
            continue
        recipe = store.recipes.get(batch["recipe_id"])
        if recipe is None or recipe["certification_target"] != cert["cert_type"]:
            continue
        hit = False
        for a in store.allocations.values():
            if a["batch_id"] != batch["id"] or a["status"] != "ACTIVE":
                continue
            lot = store.leaf_lots.get(a["lot_id"])
            if lot is not None and lot["supplier_id"] == cert["supplier_id"]:
                hit = True
                break
        if not hit:
            continue
        batch["status"] = "ON_HOLD"
        bump(batch)
        cancel_scheduled_runs_of_batch(batch)
    return success_object(certificate_out(cert))


@bp.route("/tea-ops/certificates/<cid>/reinstate", methods=["POST"])
def reinstate_certificate(cid):
    _, role = authenticate()
    authorize(role, ["CertificationOfficer"])
    cert = _cert_or_404(cid)
    if cert["status"] == "EXPIRED":
        raise_err(ERR_ALREADY_TERMINAL, "CertificateGrant is EXPIRED")
    if cert["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "CertificateGrant is not SUSPENDED")
    if cert["valid_until"] < clock.today():
        # Unreachable once the clock sweep has run; defensive guard.
        raise_err(
            ERR_INVALID_STATE,
            "Certificate validity no longer covers the current date",
        )
    cert["status"] = "ACTIVE"
    bump(cert)
    # No automatic batch un-hold (PRD 2.8).
    return success_object(certificate_out(cert))

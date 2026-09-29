"""Certificate and chain-of-title endpoints (PRD 3.6)."""

from flask import Blueprint

import serializers
from core import db, new_record, now, respond_object, touch
from errors import fail
from listing import match, paged
from middleware import (ADMIN, ALL_ROLES, DEVELOPER, LANDOWNER, require_owner, require_roles,
                        require_suspension_clear)
from services.derive import (append_transfer, available_units, certificate_easement,
                             easement_compliance_ok, recompute_certificate_units,
                             recompute_easement_units, recompute_party_holdings)
from validators import body, field_int, field_str, filter_enum, filter_str

bp = Blueprint("certificates", __name__)

LIFECYCLE_STATUSES = ("ISSUED", "PARTIALLY_REDEEMED", "REDEEMED", "RETIRED")
MARKET_STATUSES = ("HELD", "UNDER_CONTRACT", "FROZEN")
TRANSFER_TYPES = ("ISSUANCE", "PRIVATE_SALE", "BANK_PURCHASE", "BANK_RESALE", "SPLIT_OUT",
                  "REDEMPTION", "RETIREMENT", "REVERSAL")
TRADEABLE_LIFECYCLE = ("ISSUED", "PARTIALLY_REDEEMED")


def get_certificate_or_404(certificate_id):
    cert = db.certificates.get(certificate_id)
    if cert is None:
        fail("ERR_CERTIFICATE_NOT_FOUND", "certificate %s does not exist" % certificate_id)
    return cert


def assert_transferable(cert):
    """Ladder rung 20. A FROZEN certificate deliberately falls through to rung 24."""
    if cert["lifecycle_status"] not in TRADEABLE_LIFECYCLE:
        fail("ERR_CERTIFICATE_NOT_TRANSFERABLE", "certificate is %s" % cert["lifecycle_status"])
    if cert["market_status"] == "UNDER_CONTRACT":
        fail("ERR_CERTIFICATE_NOT_TRANSFERABLE", "certificate is already UNDER_CONTRACT")


def mint_child_certificate(parent, holder_party_id, units):
    parent["split_count"] = int(parent["split_count"]) + 1
    child = new_record(
        {
            "conservation_easement_id": parent["conservation_easement_id"],
            "holder_party_id": holder_party_id,
            "parent_certificate_id": parent["id"],
            "origin_sending_area_id": parent["origin_sending_area_id"],
            "serial_number": "%s-S%d" % (parent["serial_number"], int(parent["split_count"])),
            "origin_neighborhood_code": parent["origin_neighborhood_code"],
            "generation": int(parent["generation"]) + 1,
            "split_count": 0,
            "units_face": int(units),
            "units_remaining": int(units),
            "units_split_out": 0,
            "units_encumbered": 0,
            "units_redeemed": 0,
            "units_retired": 0,
            "lifecycle_status": "ISSUED",
            "market_status": "HELD",
            "issued_at": now(),
        }
    )
    db.certificates[child["id"]] = child
    parent["units_split_out"] = int(parent["units_split_out"]) + int(units)
    recompute_certificate_units(parent)
    return child


@bp.get("/tdr/certificates/<certificate_id>")
def get_certificate(certificate_id):
    require_roles(*ALL_ROLES)
    return respond_object(serializers.certificate(get_certificate_or_404(certificate_id)))


@bp.get("/tdr/certificates")
def list_certificates():
    require_roles(*ALL_ROLES)
    rows = match(
        list(db.certificates.values()),
        holder_party_id=filter_str("holder_party_id"),
        conservation_easement_id=filter_str("conservation_easement_id"),
        parent_certificate_id=filter_str("parent_certificate_id"),
        origin_sending_area_id=filter_str("origin_sending_area_id"),
        lifecycle_status=filter_enum("lifecycle_status", LIFECYCLE_STATUSES),
        market_status=filter_enum("market_status", MARKET_STATUSES),
    )
    return paged(rows, serializers.certificate)


@bp.post("/tdr/certificates/<certificate_id>/split")
def split_certificate(certificate_id):
    user_id, role = require_roles(LANDOWNER, DEVELOPER, ADMIN)
    cert = get_certificate_or_404(certificate_id)
    data = body()
    units = field_int(data, "units", minimum=1)
    expected_version = field_int(data, "expected_certificate_version")

    require_owner(user_id, role, cert["holder_party_id"])
    require_suspension_clear(cert["holder_party_id"])
    assert_transferable(cert)

    if expected_version != cert["version"]:
        fail("ERR_STALE_PARENT_VERSION", "certificate version is %s" % cert["version"])

    easement = certificate_easement(cert)
    if not easement_compliance_ok(easement):
        fail("ERR_CERTIFICATE_FROZEN", "the source easement is %s" % easement["compliance_status"])
    if cert["market_status"] != "HELD":
        fail("ERR_CERTIFICATE_NOT_TRANSFERABLE", "certificate is %s" % cert["market_status"])

    if not units < available_units(cert):
        fail("ERR_SPLIT_EXCEEDS_AVAILABLE_UNITS", "the split must leave unencumbered units behind")

    child = mint_child_certificate(cert, cert["holder_party_id"], units)
    append_transfer(cert, "SPLIT_OUT", cert["holder_party_id"], cert["holder_party_id"], units)
    append_transfer(child, "ISSUANCE", None, child["holder_party_id"], units)
    touch(cert)
    recompute_party_holdings(db.parties.get(cert["holder_party_id"]))
    return respond_object(serializers.certificate(child), 201)


@bp.post("/tdr/certificates/<certificate_id>/retire")
def retire_certificate(certificate_id):
    user_id, role = require_roles(LANDOWNER, DEVELOPER, ADMIN)
    cert = get_certificate_or_404(certificate_id)
    data = body()
    units = field_int(data, "units", minimum=1)
    field_str(data, "reason", required=False)

    require_owner(user_id, role, cert["holder_party_id"])
    assert_transferable(cert)
    if cert["market_status"] != "HELD":
        fail("ERR_CERTIFICATE_NOT_TRANSFERABLE", "certificate is %s" % cert["market_status"])
    if units > available_units(cert):
        fail("ERR_INSUFFICIENT_CERTIFICATE_UNITS", "only %d units are unencumbered" % available_units(cert))

    cert["units_retired"] = int(cert["units_retired"]) + units
    recompute_certificate_units(cert)
    if int(cert["units_remaining"]) <= 0:
        # Retirement outranks redemption on a certificate that hits zero.
        cert["lifecycle_status"] = "RETIRED"
    append_transfer(cert, "RETIREMENT", cert["holder_party_id"], None, units)
    touch(cert)

    recompute_easement_units(certificate_easement(cert))
    recompute_party_holdings(db.parties.get(cert["holder_party_id"]))
    return respond_object(serializers.certificate(cert))


@bp.get("/tdr/certificate-transfers/<transfer_id>")
def get_transfer(transfer_id):
    require_roles(*ALL_ROLES)
    row = db.certificate_transfers.get(transfer_id)
    if row is None:
        fail("ERR_CERTIFICATE_TRANSFER_NOT_FOUND", "certificate transfer %s does not exist" % transfer_id)
    return respond_object(serializers.certificate_transfer(row))


@bp.get("/tdr/certificate-transfers")
def list_transfers():
    require_roles(*ALL_ROLES)
    rows = match(
        list(db.certificate_transfers.values()),
        certificate_id=filter_str("certificate_id"),
        from_party_id=filter_str("from_party_id"),
        to_party_id=filter_str("to_party_id"),
        market_transaction_id=filter_str("market_transaction_id"),
        transfer_type=filter_enum("transfer_type", TRANSFER_TYPES),
    )
    return paged(rows, serializers.certificate_transfer)

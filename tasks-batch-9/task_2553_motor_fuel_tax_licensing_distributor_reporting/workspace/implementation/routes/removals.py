"""Rack removals and the imposition point (PRD 3.3)."""

from flask import Blueprint

import db
import helpers
import middleware
import response
import shape
from errors import ApiError
from middleware import (AUDIT_MANAGER, FIELD_INSPECTOR, LICENSEE_AGENT,
                        LICENSING_OFFICER, RETURNS_EXAMINER, TAX_SUPERVISOR)
from services import calc, cascade, derive

bp = Blueprint("removals", __name__, url_prefix="/mft")


@bp.post("/rack-removals")
def report_removal():
    middleware.require(LICENSEE_AGENT, RETURNS_EXAMINER)
    body = shape.body()
    terminal_id = shape.req_id(body, "terminal_id")
    position_holder_id = shape.req_id(body, "position_holder_licensee_id")
    purchaser_id = shape.req_id(body, "purchaser_licensee_id")
    certificate_id = shape.opt_id(body, "exemption_certificate_id")
    product_code = shape.req_enum(body, "product_code", calc.PRODUCT_CODES)
    gross_gallons = shape.req_gallons(body, "gross_gallons", gt=calc.ZERO)
    net_gallons = shape.req_gallons(body, "net_gallons", gt=calc.ZERO)
    if net_gallons > gross_gallons:
        raise ApiError("ERR_INVALID_REQUEST",
                       "net_gallons must not exceed gross_gallons.")
    removal_date = shape.req_date(body, "removal_date")
    destination_state = shape.req_pattern(body, "destination_state",
                                          shape.STATE_RE)
    bol = shape.req_str(body, "bill_of_lading_number")

    # Body foreign keys, in the order the fields are declared.
    terminal = helpers.body_ref("terminal", terminal_id)
    position_holder = helpers.body_licensee(position_holder_id)
    purchaser = helpers.body_licensee(purchaser_id)
    certificate = (helpers.body_ref("certificate", certificate_id)
                   if certificate_id else None)

    # Five business checks, strictly in this order.
    if purchaser["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_PURCHASER_LICENSE_INVALID")
    if (position_holder["license_type"] != "SUPPLIER"
            or position_holder["status"] != "ACTIVE"):
        raise ApiError("ERR_POSITION_HOLDER_INVALID")
    if certificate is not None:
        if certificate["purchaser_licensee_id"] != purchaser_id:
            raise ApiError("ERR_CERTIFICATE_HOLDER_MISMATCH")
        if not cascade.cert_active_on_date(certificate, removal_date):
            raise ApiError("ERR_CERTIFICATE_NOT_VALID_ON_DATE")
        if product_code not in calc.CERT_PRODUCT_SET[certificate["exemption_type"]]:
            raise ApiError("ERR_EXEMPTION_PRODUCT_MISMATCH")

    for existing in db.rack_removals.values():
        if (existing["terminal_id"] == terminal_id
                and existing["bill_of_lading_number"] == bol):
            raise ApiError("ERR_DUPLICATE_BOL")

    # The one fiscal check, last of all.
    would_defer = (purchaser["license_type"] in ("SUPPLIER", "DISTRIBUTOR")
                   and destination_state == calc.HOME_STATE_CODE
                   and certificate is None)
    if would_defer and derive.bond_position(purchaser)["bond_deficiency_cents"] > 0:
        raise ApiError("ERR_PURCHASER_BOND_DEFICIENT")

    # Step one: the gallons basis, keyed on the POSITION HOLDER's election.
    if position_holder["gross_net_election"] == "GROSS":
        basis_used = "GROSS"
        basis_gallons = gross_gallons
    else:
        basis_used = "NET"
        basis_gallons = net_gallons

    # Step two: six branches, first match wins.
    export_valid = cascade.cert_validly_presented(
        certificate_id, "EXPORT", purchaser_id, removal_date, product_code)
    government_valid = cascade.cert_validly_presented(
        certificate_id, "GOVERNMENT", purchaser_id, removal_date, product_code)
    agriculture_valid = cascade.cert_validly_presented(
        certificate_id, "AGRICULTURE", purchaser_id, removal_date, product_code)
    out_of_state = destination_state != calc.HOME_STATE_CODE

    if product_code == "DYED_DIESEL":
        imposition_point = "NONE_EXEMPT"
    elif out_of_state and export_valid:
        imposition_point = "NONE_EXEMPT"
    elif out_of_state:
        imposition_point = "TERMINAL_RACK"
    elif government_valid or agriculture_valid:
        imposition_point = "NONE_EXEMPT"
    elif (purchaser["license_type"] in ("SUPPLIER", "DISTRIBUTOR")
          and purchaser["status"] == "ACTIVE"):
        imposition_point = "DEFERRED_TO_PURCHASER"
    else:
        imposition_point = "TERMINAL_RACK"

    # Step three: the money, with exactly one multiplication and one rounding.
    if imposition_point == "NONE_EXEMPT":
        taxable_gallons = calc.ZERO
        tax_imposed = False
        tax_amount_cents = 0
        deferred_tax_cents = 0
    elif imposition_point == "TERMINAL_RACK":
        taxable_gallons = basis_gallons
        tax_imposed = True
        tax_amount_cents = calc.rate_cents(basis_gallons, product_code)
        deferred_tax_cents = 0
    else:
        taxable_gallons = basis_gallons
        tax_imposed = False
        tax_amount_cents = 0
        deferred_tax_cents = calc.rate_cents(basis_gallons, product_code)

    row = db.base_row(versioned=False)
    row.update({
        "terminal_id": terminal["id"],
        "position_holder_licensee_id": position_holder_id,
        "purchaser_licensee_id": purchaser_id,
        "exemption_certificate_id": certificate_id,
        "product_code": product_code,
        "gross_gallons": gross_gallons,
        "net_gallons": net_gallons,
        "removal_date": removal_date,
        "destination_state": destination_state,
        "bill_of_lading_number": bol,
        "taxable_gallons": taxable_gallons,
        "imposition_point": imposition_point,
        "tax_imposed": tax_imposed,
        "tax_amount_cents": tax_amount_cents,
        "deferred_tax_cents": deferred_tax_cents,
        "basis_used": basis_used,
    })
    db.rack_removals[row["id"]] = row
    return response.object_response(derive.rack_removal_json(row), 201)


@bp.get("/rack-removals/<removal_id>")
def read_removal(removal_id):
    middleware.require(LICENSING_OFFICER, RETURNS_EXAMINER, TAX_SUPERVISOR,
                       AUDIT_MANAGER, FIELD_INSPECTOR, LICENSEE_AGENT)
    row = helpers.find("rack_removal", removal_id)
    return response.object_response(derive.rack_removal_json(row))


@bp.get("/rack-removals")
def list_removals():
    middleware.require(LICENSING_OFFICER, RETURNS_EXAMINER, TAX_SUPERVISOR,
                       AUDIT_MANAGER, LICENSEE_AGENT)
    rows = db.ordered(db.rack_removals)
    rows = helpers.filter_by(rows, {
        "terminal_id": "terminal_id",
        "position_holder_licensee_id": "position_holder_licensee_id",
        "purchaser_licensee_id": "purchaser_licensee_id",
        "exemption_certificate_id": "exemption_certificate_id",
        "imposition_point": "imposition_point",
    })
    rows = helpers.filter_removal_month(rows)
    return response.list_response(rows, derive.rack_removal_json)

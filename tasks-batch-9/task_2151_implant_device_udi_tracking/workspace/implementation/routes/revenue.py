"""Charge capture accuracy and consignment invoice reconciliation."""
from flask import Blueprint

import serialize
from auth import (
    CIRC_CLINICIAN,
    COMPLIANCE_OFFICER,
    INVENTORY_LEAD,
    REVENUE_ANALYST,
    VENDOR_REP,
    actor,
    endpoint,
)
from calc import (
    HIGH_COST_VARIANCE_THRESHOLD_CENTS,
    consignment_expected_total,
    implant_charge_amount,
    net_consignment_settlement,
)
from derive import (
    case_close_readiness,
    recompute_case_totals,
    set_billing,
    vendor_open_consignment_liability,
)
from envelope import array_response, object_response
from errors import ApiError
from graph import (
    case_of_record,
    catalog_of_unit,
    units_of_invoice,
    unit_of_record,
    vendor_of_unit,
)
from resolve import must
from store import base_record, db, ordered, touch
from validation import (
    apply_page,
    body,
    filter_enum,
    filter_value,
    opt_int,
    pagination,
    present,
    req_int,
    req_str,
    req_str_array,
)

bp = Blueprint("revenue", __name__)

CHARGE_STATES = ("DRAFT", "POSTED", "CORRECTION_REQUIRED", "FINALIZED", "VOIDED")
INVOICE_STATES = ("SUBMITTED", "MATCHED", "VARIANCE_HOLD", "DISPUTED", "APPROVED")
CHARGE_READERS = [INVENTORY_LEAD, CIRC_CLINICIAN, COMPLIANCE_OFFICER, REVENUE_ANALYST]
INVOICE_READERS = [INVENTORY_LEAD, COMPLIANCE_OFFICER, REVENUE_ANALYST, VENDOR_REP]


# ----------------------------------------------------------- charge capture
@bp.route("/udi/implant-records/<implant_record_id>/charges", methods=["POST"])
@endpoint([REVENUE_ANALYST])
def create_charge(implant_record_id):
    data = body()
    quantity = opt_int(data, "quantity", 1, 1)

    record = must("implant_record_id", implant_record_id)
    unit = unit_of_record(record)
    item = catalog_of_unit(unit)

    charge = base_record()
    charge.update(
        {
            "implant_record_id": record["id"],
            "charge_code": item["charge_code"] if item else None,
            "quantity": quantity,
            "status": "DRAFT",
            "provisional_charge_cents": implant_charge_amount(
                item["list_charge_cents"], quantity, item["category"]
            )
            if item
            else 0,
            "final_charge_cents": None,
            "variance_cents": None,
            "capture_variant": "PROVISIONAL",
        }
    )
    db.charges[charge["id"]] = charge
    return object_response(serialize.charge(charge), 201)


@bp.route("/udi/charge-captures/<charge_id>", methods=["GET"])
@endpoint(CHARGE_READERS)
def get_charge(charge_id):
    return object_response(serialize.charge(must("charge_id", charge_id)))


@bp.route("/udi/charge-captures", methods=["GET"])
@endpoint(CHARGE_READERS)
def list_charges():
    limit, offset = pagination()
    implant_record_id = filter_value("implant_record_id")
    status = filter_enum("status", CHARGE_STATES)
    rows = []
    for row in db.charges.values():
        if implant_record_id is not None and row["implant_record_id"] != implant_record_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, total = apply_page(ordered(rows), limit, offset)
    return array_response([serialize.charge(r) for r in page], limit, offset, total)


@bp.route("/udi/charge-captures/<charge_id>/post", methods=["POST"])
@endpoint([REVENUE_ANALYST])
def post_charge(charge_id):
    charge = must("charge_id", charge_id)
    if charge["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_LIFECYCLE_STATE", "Only a DRAFT line can be posted.")
    record = db.implant_records.get(charge["implant_record_id"])
    if record is None or record["status"] not in ("VERIFIED", "AMENDED"):
        raise ApiError("ERR_INVALID_RECORD_STATE", "The implant record is not verified.")

    charge["status"] = "POSTED"
    touch(charge)
    case = case_of_record(record)
    recompute_case_totals(case)
    case_close_readiness(case)
    return object_response(serialize.charge(charge))


@bp.route("/udi/charge-captures/<charge_id>/finalize", methods=["POST"])
@endpoint([REVENUE_ANALYST])
def finalize_charge(charge_id):
    charge = must("charge_id", charge_id)
    if charge["status"] != "POSTED":
        raise ApiError("ERR_INVALID_LIFECYCLE_STATE", "Only a POSTED line can be finalized.")

    record = db.implant_records.get(charge["implant_record_id"])
    unit = unit_of_record(record)
    item = catalog_of_unit(unit)

    final_cents = implant_charge_amount(
        unit["acquisition_cost_cents"], charge["quantity"], item["category"]
    )
    charge["final_charge_cents"] = final_cents
    charge["variance_cents"] = int(charge["provisional_charge_cents"]) - final_cents
    charge["capture_variant"] = "FINAL"
    if (
        item["category"] == "HIGH_COST_IMPLANT"
        and abs(charge["variance_cents"]) >= HIGH_COST_VARIANCE_THRESHOLD_CENTS
    ):
        charge["status"] = "CORRECTION_REQUIRED"
    else:
        charge["status"] = "FINALIZED"
    touch(charge)

    case = case_of_record(record)
    recompute_case_totals(case)
    case_close_readiness(case)
    return object_response(serialize.charge(charge))


@bp.route("/udi/charge-captures/<charge_id>/correct", methods=["POST"])
@endpoint([REVENUE_ANALYST])
def correct_charge(charge_id):
    data = body()
    acknowledged = req_int(data, "acknowledged_variance_cents")

    charge = must("charge_id", charge_id)
    if charge["status"] != "CORRECTION_REQUIRED":
        raise ApiError(
            "ERR_INVALID_LIFECYCLE_STATE", "Only a CORRECTION_REQUIRED line can be corrected."
        )
    if acknowledged != charge.get("variance_cents"):
        raise ApiError("ERR_VARIANCE_ACK_MISMATCH", "acknowledged_variance_cents does not match.")

    charge["status"] = "FINALIZED"
    touch(charge)
    case = case_of_record(db.implant_records.get(charge["implant_record_id"]))
    case_close_readiness(case)
    return object_response(serialize.charge(charge))


@bp.route("/udi/charge-captures/<charge_id>/void", methods=["POST"])
@endpoint([REVENUE_ANALYST])
def void_charge(charge_id):
    charge = must("charge_id", charge_id)
    if charge["status"] not in ("DRAFT", "POSTED", "CORRECTION_REQUIRED"):
        raise ApiError("ERR_INVALID_LIFECYCLE_STATE", "The line cannot be voided from here.")

    charge["status"] = "VOIDED"
    touch(charge)
    case = case_of_record(db.implant_records.get(charge["implant_record_id"]))
    recompute_case_totals(case)
    case_close_readiness(case)
    return object_response(serialize.charge(charge))


# ---------------------------------------------------------- vendor invoices
def _attach_units(invoice, units):
    for unit in units:
        unit["vendor_invoice_id"] = invoice["id"]
        set_billing(unit, "INVOICED")


@bp.route("/udi/vendor-invoices", methods=["POST"])
@endpoint([VENDOR_REP])
def create_invoice():
    data = body()
    vendor_id = req_str(data, "vendor_id")
    agreement_id = req_str(data, "consignment_agreement_id")
    invoice_number = req_str(data, "invoice_number")
    submitted_total_cents = req_int(data, "submitted_total_cents", 1)
    device_unit_ids = req_str_array(data, "device_unit_ids")
    expected_agreement_version = req_int(data, "expected_agreement_version")

    vendor = must("vendor_id", vendor_id)                            # step 5
    agreement = must("consignment_agreement_id", agreement_id)
    units = [must("device_unit_id", unit_id) for unit_id in device_unit_ids]

    if vendor["id"] != actor():                                      # step 6
        raise ApiError("ERR_UNAUTHORIZED", "A vendor may only bill for itself.")

    if expected_agreement_version != agreement["version"]:           # step 7
        raise ApiError(
            "ERR_STALE_AGREEMENT_VERSION", "expected_agreement_version does not match."
        )

    if agreement["status"] != "ACTIVE":                               # step 17
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", "The consignment agreement is not ACTIVE.")

    if vendor["standing"] != "ACTIVE":                                # step 18
        raise ApiError("ERR_VENDOR_ON_HOLD", "The vendor is on HOLD.")

    for existing in db.invoices.values():                             # step 19
        if existing["vendor_id"] == vendor["id"] and existing["invoice_number"] == invoice_number:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER", "invoice_number already exists.")

    for unit in units:                                                # step 20
        if unit.get("vendor_invoice_id") is not None:
            raise ApiError("ERR_UNIT_ALREADY_INVOICED", "A unit already carries an invoice.")

    for unit in units:                                                # step 27
        if unit["billing_state"] != "BILLABLE":
            raise ApiError("ERR_UNIT_NOT_BILLABLE", "A unit is not in billing_state BILLABLE.")

    invoice = base_record()
    invoice.update(
        {
            "vendor_id": vendor["id"],
            "consignment_agreement_id": agreement["id"],
            "invoice_number": invoice_number,
            "submitted_total_cents": submitted_total_cents,
            "device_unit_ids": list(device_unit_ids),
            "status": "SUBMITTED",
            "expected_total_cents": None,
            "variance_cents": None,
            "variance_bps": None,
            "reconciliation_variant": None,
            "credit_applied_cents": None,
            "net_payable_cents": None,
            "matched_by_user_id": None,
            "approved_by_user_id": None,
            "override_reason": None,
        }
    )
    db.invoices[invoice["id"]] = invoice
    _attach_units(invoice, units)
    touch(agreement)
    return object_response(serialize.invoice(invoice), 201)


@bp.route("/udi/vendor-invoices/<invoice_id>/match", methods=["POST"])
@endpoint([REVENUE_ANALYST])
def match_invoice(invoice_id):
    invoice = must("invoice_id", invoice_id)
    if invoice["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_INVOICE_STATE", "Only a SUBMITTED invoice can be matched.")

    agreement = db.agreements.get(invoice["consignment_agreement_id"])
    expected, variance, variance_bps, variant = consignment_expected_total(invoice, agreement)
    invoice["expected_total_cents"] = expected
    invoice["variance_cents"] = variance
    invoice["variance_bps"] = variance_bps
    invoice["reconciliation_variant"] = variant
    invoice["matched_by_user_id"] = actor()
    invoice["status"] = (
        "VARIANCE_HOLD" if variance_bps > agreement["invoice_tolerance_bps"] else "MATCHED"
    )
    touch(invoice)
    return object_response(serialize.invoice(invoice))


@bp.route("/udi/vendor-invoices/<invoice_id>/approve", methods=["POST"])
@endpoint([COMPLIANCE_OFFICER, REVENUE_ANALYST])
def approve_invoice(invoice_id):
    data = body()
    raw_reason = data.get("override_reason")
    override_reason = raw_reason if isinstance(raw_reason, str) and raw_reason.strip() else None

    invoice = must("invoice_id", invoice_id)
    if invoice["status"] not in ("MATCHED", "VARIANCE_HOLD"):        # step 8
        raise ApiError("ERR_INVALID_INVOICE_STATE", "The invoice cannot be approved from here.")

    if actor() == invoice.get("matched_by_user_id"):                 # step 9
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "The matching user may not approve.")

    agreement = db.agreements.get(invoice["consignment_agreement_id"])
    if agreement is None or agreement["status"] != "ACTIVE":         # step 17
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", "The consignment agreement is not ACTIVE.")

    if invoice["status"] == "VARIANCE_HOLD" and override_reason is None:   # step 28
        raise ApiError(
            "ERR_INVOICE_TOLERANCE_EXCEEDED", "A held invoice needs a non-empty override_reason."
        )

    credit_applied, net_payable = net_consignment_settlement(invoice)
    invoice["credit_applied_cents"] = credit_applied
    invoice["net_payable_cents"] = net_payable
    invoice["approved_by_user_id"] = actor()
    if override_reason is not None:
        invoice["override_reason"] = override_reason
    invoice["status"] = "APPROVED"
    touch(invoice)

    for unit in units_of_invoice(invoice["id"]):
        if unit["billing_state"] == "INVOICED":
            set_billing(unit, "RECONCILED")
    vendor_open_consignment_liability(db.vendors.get(invoice["vendor_id"]))
    return object_response(serialize.invoice(invoice))


@bp.route("/udi/vendor-invoices/<invoice_id>/dispute", methods=["POST"])
@endpoint([REVENUE_ANALYST])
def dispute_invoice(invoice_id):
    invoice = must("invoice_id", invoice_id)
    if invoice["status"] != "VARIANCE_HOLD":
        raise ApiError("ERR_INVALID_INVOICE_STATE", "Only a VARIANCE_HOLD invoice is disputable.")

    invoice["status"] = "DISPUTED"
    touch(invoice)
    for unit in units_of_invoice(invoice["id"]):
        unit["vendor_invoice_id"] = None
        if unit["billing_state"] == "INVOICED":
            set_billing(unit, "BILLABLE")
        else:
            touch(unit)
    vendor_open_consignment_liability(db.vendors.get(invoice["vendor_id"]))
    return object_response(serialize.invoice(invoice))


@bp.route("/udi/vendor-invoices/<invoice_id>/resubmit", methods=["POST"])
@endpoint([VENDOR_REP])
def resubmit_invoice(invoice_id):
    data = body()
    submitted_total_cents = req_int(data, "submitted_total_cents", 1)
    device_unit_ids = req_str_array(data, "device_unit_ids")

    invoice = must("invoice_id", invoice_id)                         # step 4
    units = [must("device_unit_id", unit_id) for unit_id in device_unit_ids]

    if invoice["vendor_id"] != actor():                              # step 6
        raise ApiError("ERR_UNAUTHORIZED", "A vendor may only bill for itself.")

    if invoice["status"] != "DISPUTED":                              # step 8
        raise ApiError("ERR_INVALID_INVOICE_STATE", "Only a DISPUTED invoice can be resubmitted.")

    vendor = db.vendors.get(invoice["vendor_id"])
    if vendor is None or vendor["standing"] != "ACTIVE":             # step 18
        raise ApiError("ERR_VENDOR_ON_HOLD", "The vendor is on HOLD.")

    for unit in units:                                               # step 20
        if unit.get("vendor_invoice_id") is not None:
            raise ApiError("ERR_UNIT_ALREADY_INVOICED", "A unit already carries an invoice.")

    for unit in units:                                               # step 27
        if unit["billing_state"] != "BILLABLE":
            raise ApiError("ERR_UNIT_NOT_BILLABLE", "A unit is not in billing_state BILLABLE.")

    invoice["submitted_total_cents"] = submitted_total_cents
    invoice["device_unit_ids"] = list(device_unit_ids)
    invoice["status"] = "SUBMITTED"
    invoice["expected_total_cents"] = None
    invoice["variance_cents"] = None
    invoice["variance_bps"] = None
    invoice["reconciliation_variant"] = None
    invoice["matched_by_user_id"] = None
    touch(invoice)
    _attach_units(invoice, units)
    return object_response(serialize.invoice(invoice))


@bp.route("/udi/vendor-invoices/<invoice_id>", methods=["GET"])
@endpoint(INVOICE_READERS)
def get_invoice(invoice_id):
    return object_response(serialize.invoice(must("invoice_id", invoice_id)))


@bp.route("/udi/vendor-invoices", methods=["GET"])
@endpoint(INVOICE_READERS)
def list_invoices():
    limit, offset = pagination()
    vendor_id = filter_value("vendor_id")
    agreement_id = filter_value("consignment_agreement_id")
    status = filter_enum("status", INVOICE_STATES)
    rows = []
    for row in db.invoices.values():
        if vendor_id is not None and row["vendor_id"] != vendor_id:
            continue
        if agreement_id is not None and row["consignment_agreement_id"] != agreement_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, total = apply_page(ordered(rows), limit, offset)
    return array_response([serialize.invoice(r) for r in page], limit, offset, total)

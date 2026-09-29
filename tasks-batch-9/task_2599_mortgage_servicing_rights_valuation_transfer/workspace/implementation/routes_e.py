"""Servicing transfers: the three parallel dimensions, borrower notices, completion."""
from flask import Blueprint

import calcs
import cascades
import serial
from core import (DB, READ_NOTICE, READ_XFER, R_BUYER, R_COMPLIANCE, R_TXN, authenticate,
                  body_of, f_date, f_enum, f_id, f_str, fail, filter_eq, lookup, new_row,
                  no_body, now_date, now_iso, ok, paginate, require_owner, rows,
                  sort_created, touch)

bp = Blueprint("group_e", __name__)

NOTICE_TYPES = ("TRANSFEROR_15DAY", "TRANSFEREE_15DAY", "COMBINED")
DATA_ORDER = {"NOT_STARTED": 0, "MAPPED": 1, "ESCROW_MAPPED": 2, "RECONCILED": 3}


def transfer_chain(transfer):
    agreement = DB["agreements"][transfer["purchase_agreement_id"]]
    package = DB["bid_packages"][agreement["bid_package_id"]]
    portfolio = DB["portfolios"][package["portfolio_id"]]
    return agreement, package, portfolio


def require_in_progress(transfer):
    if transfer["status"] != "IN_PROGRESS":
        fail("ERR_TRANSFER_INVALID_STATE", "the servicing transfer is not IN_PROGRESS")


# ---------------------------------------------------------------- reads
@bp.get("/msr/servicing-transfers/<xf_id>")
def get_transfer(xf_id):
    authenticate(READ_XFER)
    row = lookup("transfers", xf_id, "ERR_SERVICING_TRANSFER_NOT_FOUND")
    return ok(serial.ser_transfer(row))


@bp.get("/msr/servicing-transfers")
def list_transfers():
    authenticate(READ_XFER)
    items = sort_created(rows("transfers"))
    items = filter_eq(items, "purchase_agreement_id")
    items = filter_eq(items, "status")
    items = filter_eq(items, "notice_status")
    items = filter_eq(items, "data_status")
    items = filter_eq(items, "pipeline_status")
    items = filter_eq(items, "readiness")
    return paginate(items, serial.ser_transfer)


# ---------------------------------------------------------------- data dimension
@bp.post("/msr/servicing-transfers/<xf_id>/map-data")
def map_data(xf_id):
    user_id, _ = authenticate(R_BUYER)
    body = body_of("mapping_scheme")
    scheme = f_enum(body, "mapping_scheme", ("MSP_TO_MSP", "MSP_TO_LSAMS", "CUSTOM"))

    transfer = lookup("transfers", xf_id, "ERR_SERVICING_TRANSFER_NOT_FOUND")
    agreement, _, _ = transfer_chain(transfer)
    require_owner(user_id, agreement["buyer_id"])
    require_in_progress(transfer)
    if transfer["data_status"] != "NOT_STARTED":
        fail("ERR_TRANSFER_INVALID_STATE", "data mapping has already been filed")

    transfer["mapping_scheme"] = scheme
    transfer["data_status"] = "MAPPED"
    calcs.derive_readiness(transfer)
    touch(transfer)
    return ok(serial.ser_transfer(transfer))


@bp.post("/msr/servicing-transfers/<xf_id>/map-escrow")
def map_escrow(xf_id):
    user_id, _ = authenticate(R_BUYER)
    no_body()
    transfer = lookup("transfers", xf_id, "ERR_SERVICING_TRANSFER_NOT_FOUND")
    agreement, package, _ = transfer_chain(transfer)
    require_owner(user_id, agreement["buyer_id"])
    require_in_progress(transfer)
    if transfer["data_status"] != "MAPPED":
        fail("ERR_TRANSFER_INVALID_STATE", "the custodial sweep requires data_status MAPPED")

    escrow_total = 0
    suspense_total = 0
    for line in calcs.included_lines(package["id"]):
        loan = DB["loans"][line["loan_id"]]
        loan["escrow_balance_at_mapping_cents"] = loan["escrow_balance_cents"]
        loan["suspense_balance_at_mapping_cents"] = loan["suspense_balance_cents"]
        escrow_total += loan["escrow_balance_cents"]
        suspense_total += loan["suspense_balance_cents"]
        loan["escrow_balance_cents"] = 0
        loan["suspense_balance_cents"] = 0
        touch(loan)

    transfer["escrow_transferred_cents"] = escrow_total
    transfer["suspense_transferred_cents"] = suspense_total
    transfer["data_status"] = "ESCROW_MAPPED"
    calcs.derive_readiness(transfer)
    touch(transfer)
    return ok(serial.ser_transfer(transfer))


@bp.post("/msr/servicing-transfers/<xf_id>/rollback-escrow-mapping")
def rollback_escrow(xf_id):
    user_id, _ = authenticate(R_BUYER)
    body = body_of("reason")
    f_str(body, "reason", max_len=None)

    transfer = lookup("transfers", xf_id, "ERR_SERVICING_TRANSFER_NOT_FOUND")
    agreement, package, _ = transfer_chain(transfer)
    require_owner(user_id, agreement["buyer_id"])
    require_in_progress(transfer)
    if transfer["data_status"] != "ESCROW_MAPPED":
        fail("ERR_TRANSFER_INVALID_STATE",
             "only an ESCROW_MAPPED transfer can roll its sweep back")

    for line in calcs.included_lines(package["id"]):
        loan = DB["loans"][line["loan_id"]]
        if loan["escrow_balance_at_mapping_cents"] is not None:
            loan["escrow_balance_cents"] = loan["escrow_balance_at_mapping_cents"]
        if loan["suspense_balance_at_mapping_cents"] is not None:
            loan["suspense_balance_cents"] = loan["suspense_balance_at_mapping_cents"]
        touch(loan)

    transfer["escrow_transferred_cents"] = 0
    transfer["suspense_transferred_cents"] = 0
    transfer["data_status"] = "MAPPED"
    calcs.derive_readiness(transfer)
    touch(transfer)
    return ok(serial.ser_transfer(transfer))


@bp.post("/msr/servicing-transfers/<xf_id>/reconcile")
def reconcile(xf_id):
    user_id, _ = authenticate(R_BUYER)
    no_body()
    transfer = lookup("transfers", xf_id, "ERR_SERVICING_TRANSFER_NOT_FOUND")
    agreement, _, portfolio = transfer_chain(transfer)
    require_owner(user_id, agreement["buyer_id"])
    require_in_progress(transfer)
    if transfer["data_status"] == "RECONCILED":
        fail("ERR_TRANSFER_INVALID_STATE", "this transfer is already reconciled")
    if DATA_ORDER[transfer["data_status"]] < DATA_ORDER["ESCROW_MAPPED"]:
        fail("ERR_ESCROW_NOT_MAPPED", "reconciliation requires the custodial sweep first")

    frozen = portfolio.get("frozen_custodial_cents")
    if frozen is None:
        frozen = calcs.custodial_funds_total(portfolio["id"])
    swept = transfer["escrow_transferred_cents"] + transfer["suspense_transferred_cents"]
    if swept != frozen:
        fail("ERR_ESCROW_NOT_MAPPED",
             "swept custodial funds do not account for the pool as frozen at tape lock")

    transfer["reconciled_at"] = now_iso()
    transfer["data_status"] = "RECONCILED"
    calcs.derive_readiness(transfer)
    touch(transfer)
    return ok(serial.ser_transfer(transfer))


# ---------------------------------------------------------------- pipeline dimension
@bp.post("/msr/servicing-transfers/<xf_id>/transfer-pipeline")
def transfer_pipeline(xf_id):
    user_id, _ = authenticate(R_BUYER)
    no_body()
    transfer = lookup("transfers", xf_id, "ERR_SERVICING_TRANSFER_NOT_FOUND")
    agreement, package, _ = transfer_chain(transfer)
    require_owner(user_id, agreement["buyer_id"])
    require_in_progress(transfer)
    if transfer["pipeline_status"] != "NOT_STARTED":
        fail("ERR_TRANSFER_INVALID_STATE", "the loss-mit pipeline has already transferred")

    count = 0
    for line in calcs.included_lines(package["id"]):
        loan = DB["loans"][line["loan_id"]]
        if loan["loss_mit_status"] != "NONE":
            count += 1
    transfer["loss_mit_pipeline_count"] = count
    transfer["pipeline_status"] = "PIPELINE_TRANSFERRED"
    calcs.derive_readiness(transfer)
    touch(transfer)
    return ok(serial.ser_transfer(transfer))


# ---------------------------------------------------------------- notice dimension
@bp.post("/msr/servicing-transfers/<xf_id>/notices")
def send_notice(xf_id):
    user_id, role = authenticate(("SellerServicer", "BuyerServicer"))
    body = body_of("notice_type", "loan_id", "effective_date")
    notice_type = f_enum(body, "notice_type", NOTICE_TYPES)
    loan_id = f_id(body, "loan_id")
    effective_date = f_date(body, "effective_date")

    transfer = lookup("transfers", xf_id, "ERR_SERVICING_TRANSFER_NOT_FOUND")
    loan = lookup("loans", loan_id, "ERR_LOAN_NOT_FOUND")
    agreement, package, portfolio = transfer_chain(transfer)
    if role == "SellerServicer":
        require_owner(user_id, portfolio["seller_id"])
    else:
        require_owner(user_id, agreement["buyer_id"])
    require_in_progress(transfer)

    expected_role = ("SellerServicer" if notice_type in ("TRANSFEROR_15DAY", "COMBINED")
                     else "BuyerServicer")
    if role != expected_role:
        fail("ERR_NOTICE_SENDER_ROLE_MISMATCH",
             "this notice type must be sent by the %s" % expected_role)
    if effective_date != agreement["transfer_date"]:
        fail("ERR_NOTICE_EFFECTIVE_DATE_MISMATCH",
             "effective_date must equal the agreement transfer_date")
    on_tape = any(line["loan_id"] == loan_id
                  for line in calcs.included_lines(package["id"]))
    if not on_tape:
        fail("ERR_LOAN_NOT_ON_TAPE", "the named loan is not on the awarded tape")

    lead_days, compliance = calcs.notice_window(notice_type, effective_date, now_date())
    row = new_row("notices", versioned=False)
    row.update({"servicing_transfer_id": xf_id, "loan_id": loan_id,
                "notice_type": notice_type, "effective_date": effective_date,
                "sent_at": now_iso(), "lead_days": lead_days,
                "compliance_status": compliance, "sent_by_role": role})

    transfer["notice_count"] += 1
    if compliance == "LATE":
        transfer["late_notice_count"] += 1
    if transfer["notice_status"] == "NOT_STARTED":
        transfer["notice_status"] = "NOTICES_IN_PROGRESS"
    calcs.derive_readiness(transfer)
    touch(transfer)
    return ok(serial.ser_notice(row), 201)


@bp.get("/msr/servicing-transfers/<xf_id>/notices")
def list_transfer_notices(xf_id):
    authenticate(READ_NOTICE)
    lookup("transfers", xf_id, "ERR_SERVICING_TRANSFER_NOT_FOUND")
    items = calcs.transfer_notices(xf_id)
    items = filter_eq(items, "notice_type")
    items = filter_eq(items, "compliance_status")
    items = filter_eq(items, "loan_id")
    return paginate(items, serial.ser_notice)


@bp.post("/msr/servicing-transfers/<xf_id>/attest-notices")
def attest_notices(xf_id):
    user_id, _ = authenticate(R_COMPLIANCE)
    no_body()
    transfer = lookup("transfers", xf_id, "ERR_SERVICING_TRANSFER_NOT_FOUND")
    _, package, _ = transfer_chain(transfer)
    require_in_progress(transfer)
    if transfer["notice_status"] != "NOTICES_IN_PROGRESS":
        fail("ERR_TRANSFER_INVALID_STATE",
             "attestation requires notice_status NOTICES_IN_PROGRESS")

    notices = calcs.transfer_notices(xf_id)
    covered = {n["loan_id"] for n in notices
               if n["notice_type"] in ("TRANSFEROR_15DAY", "COMBINED")}
    for line in calcs.included_lines(package["id"]):
        if line["loan_id"] not in covered:
            fail("ERR_NOTICE_COMPLIANCE_INCOMPLETE",
                 "at least one included tape loan has no transferor notice")
    if transfer["late_notice_count"] != 0:
        fail("ERR_NOTICE_LATE", "one or more notices breached the statutory window")

    transfer["notice_status"] = "NOTICES_ATTESTED"
    transfer["notice_attested_at"] = now_iso()
    transfer["notice_attested_by_user_id"] = user_id
    calcs.derive_readiness(transfer)
    touch(transfer)
    return ok(serial.ser_transfer(transfer))


# ---------------------------------------------------------------- completion
@bp.post("/msr/servicing-transfers/<xf_id>/complete")
def complete_transfer(xf_id):
    authenticate(R_TXN)
    no_body()
    transfer = lookup("transfers", xf_id, "ERR_SERVICING_TRANSFER_NOT_FOUND")
    agreement, package, portfolio = transfer_chain(transfer)
    require_in_progress(transfer)
    calcs.derive_readiness(transfer)
    if transfer["readiness"] != "READY":
        fail("ERR_TRANSFER_NOT_READY", "all three transfer dimensions must be complete")
    if agreement["transfer_date"] is not None and now_date() < agreement["transfer_date"]:
        fail("ERR_TRANSFER_NOT_READY",
             "a transfer cannot complete before its own effective date")

    cascades.completion_cascade(transfer, agreement, package, portfolio)
    return ok(serial.ser_transfer(transfer))

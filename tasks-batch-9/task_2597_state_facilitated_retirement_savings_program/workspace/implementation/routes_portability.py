"""Portability transfers: request, settle, return."""
from flask import Blueprint

import calc
import serializers
from auth import (get_account, get_participant, get_transfer, own_participant,
                  require)
from errors import fail
from response import created, paginate, query_filter, single
from store import db
from util import add_days, fmt_date, parse_date
from validate import parse_body

bp = Blueprint("portability", __name__)

DESTINATION_TYPES = ("EXTERNAL_IRA", "PROGRAM_ACCOUNT")
TRANSFER_KINDS = ("DIRECT_ROLLOVER", "TRUSTEE_TO_TRUSTEE", "INDIRECT_60_DAY")
TRANSFER_STATUSES = ("REQUESTED", "SETTLED", "RETURNED", "FAILED_TAXABLE")
TRANSFER_READ_ROLES = ["ProgramAdministrator", "ComplianceOfficer", "Recordkeeper", "Participant"]


@bp.route("/portability-transfers", methods=["POST"])
def request_transfer():
    principal = require(["Participant", "ProgramAdministrator"])
    parsed = parse_body({
        "participant_id": {"type": "str", "required": True},
        "source_account_id": {"type": "str", "required": True},
        "destination_type": {"type": "str", "required": True, "enum": DESTINATION_TYPES},
        "transfer_kind": {"type": "str", "required": True, "enum": TRANSFER_KINDS},
        "amount_cents": {"type": "int", "required": True, "min": 1},
        "destination_account_id": {"type": "str", "nullable": True},
        "external_institution_name": {"type": "str", "nullable": True},
    })
    if parsed["destination_type"] == "PROGRAM_ACCOUNT":
        if not parsed["destination_account_id"]:
            fail("ERR_INVALID_REQUEST",
                 "destination_account_id is required for a PROGRAM_ACCOUNT destination")
        if parsed["external_institution_name"]:
            fail("ERR_INVALID_REQUEST",
                 "external_institution_name must be null for a PROGRAM_ACCOUNT destination")
    else:
        if not parsed["external_institution_name"]:
            fail("ERR_INVALID_REQUEST",
                 "external_institution_name is required for an EXTERNAL_IRA destination")
        if parsed["destination_account_id"]:
            fail("ERR_INVALID_REQUEST",
                 "destination_account_id must be null for an EXTERNAL_IRA destination")
    participant = get_participant(parsed["participant_id"])
    own_participant(principal, participant["id"])
    source = get_account(parsed["source_account_id"])
    destination = None
    if parsed["destination_account_id"]:
        destination = get_account(parsed["destination_account_id"])

    if source["account_status"] == "CLOSED":
        fail("ERR_ACCOUNT_CLOSED", "the source account is closed")
    if calc.account_posture(source) != "UNRESTRICTED":
        fail("ERR_ACCOUNT_RESTRICTED", "the source account is not free of holds")
    if source["participant_id"] != participant["id"]:
        fail("ERR_ACCOUNT_OWNER_MISMATCH", "the source account belongs to someone else")
    if destination is not None:
        if destination["id"] == source["id"] or \
                destination["participant_id"] != participant["id"] or \
                destination["account_status"] != "OPEN":
            fail("ERR_ACCOUNT_OWNER_MISMATCH",
                 "the destination account is not an open account of this saver")
    today = db.today()
    if parsed["transfer_kind"] == "INDIRECT_60_DAY" and \
            calc.rollover_frequency_blocked(participant["id"], today):
        fail("ERR_ROLLOVER_FREQUENCY_LIMIT",
             "only one indirect rollover is permitted per rolling 365 days")
    amount = int(parsed["amount_cents"])
    if amount > int(source["balance_cents"]):
        fail("ERR_INSUFFICIENT_ACCOUNT_BALANCE",
             "the source account holds only %d cents" % int(source["balance_cents"]))

    money = calc.transfer_money(amount, parsed["transfer_kind"],
                                source["balance_cents"], source["contribution_basis_cents"])
    settle_by = None
    if parsed["transfer_kind"] == "INDIRECT_60_DAY":
        settle_by = fmt_date(add_days(today, calc.INDIRECT_SETTLE_DAYS))
    row = {
        "participant_id": participant["id"],
        "source_account_id": source["id"],
        "destination_type": parsed["destination_type"],
        "destination_account_id": parsed["destination_account_id"],
        "external_institution_name": parsed["external_institution_name"],
        "transfer_kind": parsed["transfer_kind"],
        "amount_cents": amount,
        "in_transit_cents": amount,
        "status": "REQUESTED",
        "requested_on": fmt_date(today),
        "settle_by_date": settle_by,
        "settled_on": None,
        "settlement_reference": None,
        "return_reason": None,
        "is_taxable_distribution": False,
    }
    row.update(money)
    transfer = db.insert("portability_transfers", row)
    source["balance_cents"] = int(source["balance_cents"]) - amount
    source["contribution_basis_cents"] = (int(source["contribution_basis_cents"])
                                          - money["basis_portion_cents"])
    calc.refresh_account(source, bump=True)
    return created(serializers.transfer(transfer))


@bp.route("/portability-transfers/<transfer_id>", methods=["GET"])
def read_transfer(transfer_id):
    principal = require(TRANSFER_READ_ROLES)
    transfer = get_transfer(transfer_id)
    own_participant(principal, transfer["participant_id"])
    return single(serializers.transfer(transfer))


@bp.route("/portability-transfers", methods=["GET"])
def list_transfers():
    principal = require(TRANSFER_READ_ROLES)
    participant_id = query_filter("participant_id")
    source_account_id = query_filter("source_account_id")
    destination_account_id = query_filter("destination_account_id")
    kind = query_filter("transfer_kind", TRANSFER_KINDS)
    status = query_filter("status", TRANSFER_STATUSES)
    rows = db.ordered("portability_transfers")
    if principal.is_participant:
        rows = [t for t in rows if t["participant_id"] == principal.user_id]
    if participant_id is not None:
        rows = [t for t in rows if t["participant_id"] == participant_id]
    if source_account_id is not None:
        rows = [t for t in rows if t["source_account_id"] == source_account_id]
    if destination_account_id is not None:
        rows = [t for t in rows if t["destination_account_id"] == destination_account_id]
    if kind is not None:
        rows = [t for t in rows if t["transfer_kind"] == kind]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    return paginate(rows, serializers.transfer)


@bp.route("/portability-transfers/<transfer_id>/settle", methods=["POST"])
def settle_transfer(transfer_id):
    require(["Recordkeeper"])
    transfer = get_transfer(transfer_id)
    parsed = parse_body({
        "settled_on": {"type": "date", "required": True},
        "settlement_reference": {"type": "str", "required": True},
    })
    if transfer["status"] != "REQUESTED":
        fail("ERR_TRANSFER_STATE_INVALID", "this transfer has already been resolved")
    settled_on = parse_date(parsed["settled_on"])
    if transfer["transfer_kind"] == "INDIRECT_60_DAY" and transfer["settle_by_date"]:
        if settled_on > parse_date(transfer["settle_by_date"]):
            fail("ERR_ROLLOVER_WINDOW_EXPIRED",
                 "the sixty-day rollover window closed on %s" % transfer["settle_by_date"])
    transfer["status"] = "SETTLED"
    transfer["in_transit_cents"] = 0
    transfer["settled_on"] = parsed["settled_on"]
    transfer["settlement_reference"] = parsed["settlement_reference"]
    if transfer["transfer_kind"] == "INDIRECT_60_DAY":
        transfer["is_taxable_distribution"] = True
    db.touch(transfer)
    if transfer["destination_type"] == "PROGRAM_ACCOUNT":
        destination = db.participant_accounts.get(transfer["destination_account_id"])
        if destination is not None:
            destination["balance_cents"] = (int(destination["balance_cents"])
                                            + int(transfer["net_cents"]))
            destination["contribution_basis_cents"] = (
                int(destination["contribution_basis_cents"])
                + int(transfer["basis_portion_cents"]))
            destination["rolled_over_from_account_id"] = transfer["source_account_id"]
            calc.refresh_account(destination, bump=True)
    source = db.participant_accounts.get(transfer["source_account_id"])
    if source is not None:
        calc.refresh_account(source, bump=True)
    return single(serializers.transfer(transfer))


@bp.route("/portability-transfers/<transfer_id>/return", methods=["POST"])
def return_transfer(transfer_id):
    require(["Recordkeeper"])
    transfer = get_transfer(transfer_id)
    parsed = parse_body({"return_reason": {"type": "str", "required": True}})
    if transfer["status"] != "REQUESTED":
        fail("ERR_TRANSFER_STATE_INVALID", "this transfer has already been resolved")
    transfer["status"] = "RETURNED"
    transfer["in_transit_cents"] = 0
    transfer["return_reason"] = parsed["return_reason"]
    db.touch(transfer)
    source = db.participant_accounts.get(transfer["source_account_id"])
    if source is not None:
        # Full compensation: the gross amount and its basis portion come back and
        # the fee is reversed, so program cash lands exactly where it started.
        source["balance_cents"] = int(source["balance_cents"]) + int(transfer["amount_cents"])
        source["contribution_basis_cents"] = (int(source["contribution_basis_cents"])
                                              + int(transfer["basis_portion_cents"]))
        calc.refresh_account(source, bump=True)
    return single(serializers.transfer(transfer))

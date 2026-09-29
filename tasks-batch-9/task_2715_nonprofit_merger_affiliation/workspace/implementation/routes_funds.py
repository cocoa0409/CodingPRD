"""Restricted gifts: donor consent, judicial modification and transfer — PRD 3.6."""

from flask import Blueprint

import calc
import enums
import services
from auth import authenticate
from clock import CLOCK
from db import ORGANIZATIONS, create_row, touch
from errors import fail
from response import ok_row
from validate import (CODE_PATTERN, body_object, opt_bool, opt_int, opt_str,
                      req_enum, req_id, req_int, req_str)

bp = Blueprint("funds", __name__)

TRANSFER_DEAL_STATES = ("STRUCTURE_SELECTED", "BOARD_APPROVAL", "REGULATORY_REVIEW",
                        "INTEGRATION")


@bp.post("/restricted-funds")
def register_fund():
    authenticate(["PlatformAdmin", "CharitableTrustCounsel"])
    body = body_object()
    org_id = req_id(body, "org_id")
    fund_name = req_str(body, "fund_name", min_len=1, max_len=160)
    fund_type = req_enum(body, "fund_type", enums.FUND_TYPES)
    principal_cents = req_int(body, "principal_cents", minimum=1)
    appreciation = opt_int(body, "accumulated_appreciation_cents", minimum=0, default=0)
    hdv = req_int(body, "historic_dollar_value_cents", minimum=0)
    purpose_code = req_str(body, "restriction_purpose_code", pattern=CODE_PATTERN)
    restriction_conflict = opt_bool(body, "restriction_conflict", default=False)
    reachable = opt_bool(body, "donor_of_record_reachable", default=True)

    org = services.find_org(org_id)

    # Ladder rule 31.
    if hdv > principal_cents + appreciation:
        fail("ERR_HDV_EXCEEDS_FUND_VALUE",
             "historic_dollar_value_cents may not exceed the fund's value.")

    row = create_row("RestrictedFund", {
        "org_id": org["id"],
        "fund_name": fund_name,
        "fund_type": fund_type,
        "principal_cents": principal_cents,
        "accumulated_appreciation_cents": appreciation,
        "historic_dollar_value_cents": hdv,
        "restriction_purpose_code": purpose_code,
        "restriction_conflict": restriction_conflict,
        "donor_of_record_reachable": reachable,
        "transfer_status": "HELD",
        "consent_method": None,
        "consent_decision": None,
        "consent_signed_at": None,
        "petition_basis": None,
        "petition_filed_at": None,
        "court_docket_no": None,
        "court_decision": None,
        "modified_purpose_code": None,
        "transfer_basis": None,
        "transferable_amount_cents": 0,
        "transferred_amount_cents": 0,
        "retained_amount_cents": 0,
        "transferred_to_org_id": None,
        "transfer_restructuring_id": None,
        "unwind_count": 0,
    })

    # The holder's corpus is recomputed immediately (PRD 3.1 three-part sum).
    services.refresh_corpus(org)
    services.recompute_postures_for_orgs([org["id"]])
    return ok_row(row, 201)


@bp.post("/restricted-funds/<fund_id>/seek-consent")
def seek_consent(fund_id):
    authenticate(["CharitableTrustCounsel"])
    body = body_object()
    consent_method = req_enum(body, "consent_method", enums.CONSENT_METHODS)

    fund = services.find_fund(fund_id)
    # Ladder rule 18: a HELD fund with a reachable donor of record.
    if fund["transfer_status"] != "HELD":
        fail("ERR_INVALID_FUND_STATE",
             "Donor consent may only be solicited on a HELD fund.")
    if not fund["donor_of_record_reachable"]:
        fail("ERR_INVALID_FUND_STATE",
             "The donor of record is unreachable; a judicial petition is required.")

    fund["transfer_status"] = "CONSENT_SOUGHT"
    fund["consent_method"] = consent_method
    touch(fund)
    services.recompute_postures_for_orgs([fund["org_id"]])
    return ok_row(fund)


@bp.post("/restricted-funds/<fund_id>/record-consent")
def record_consent(fund_id):
    authenticate(["CharitableTrustCounsel"])
    body = body_object()
    decision = req_enum(body, "decision", enums.CONSENT_DECISIONS)

    fund = services.find_fund(fund_id)
    # Ladder rule 18.
    if fund["transfer_status"] != "CONSENT_SOUGHT":
        fail("ERR_INVALID_FUND_STATE",
             "A donor answer may only be recorded against a CONSENT_SOUGHT fund.")

    # Stamped from the logical clock either way; a client value is ignored.
    fund["consent_signed_at"] = CLOCK.now_iso()
    fund["consent_decision"] = decision
    if decision == "GRANTED":
        fund["transfer_status"] = "CONSENT_GRANTED"
        fund["transferable_amount_cents"] = calc.transferable_amount(fund, "DONOR_CONSENT")
    else:
        fund["transfer_status"] = "CONSENT_DENIED"
    touch(fund)
    services.recompute_postures_for_orgs([fund["org_id"]])
    return ok_row(fund)


@bp.post("/restricted-funds/<fund_id>/file-petition")
def file_petition(fund_id):
    authenticate(["CharitableTrustCounsel"])
    body = body_object()
    petition_basis = req_enum(body, "petition_basis", enums.PETITION_BASES)
    docket = req_str(body, "court_docket_no", min_len=1)

    fund = services.find_fund(fund_id)
    # Ladder rule 18: the judicial branch opens from CONSENT_DENIED, or from HELD.
    if fund["transfer_status"] not in ("CONSENT_DENIED", "HELD"):
        fail("ERR_INVALID_FUND_STATE",
             "A petition may only be filed from CONSENT_DENIED or HELD.")
    # Ladder rule 30: a reachable donor must be asked before a court is.
    if fund["transfer_status"] == "HELD":
        if fund["donor_of_record_reachable"] or petition_basis != "DONOR_UNREACHABLE":
            fail("ERR_DONOR_CONSENT_REQUIRED",
                 "Filing straight from HELD requires an unreachable donor of record "
                 "pleaded on the DONOR_UNREACHABLE basis.")

    fund["transfer_status"] = "PETITION_FILED"
    fund["petition_basis"] = petition_basis
    fund["court_docket_no"] = docket
    fund["petition_filed_at"] = CLOCK.now_iso()
    touch(fund)
    services.recompute_postures_for_orgs([fund["org_id"]])
    return ok_row(fund)


@bp.post("/restricted-funds/<fund_id>/record-court-decision")
def record_court_decision(fund_id):
    authenticate(["CharitableTrustCounsel"])
    body = body_object()
    decision = req_enum(body, "decision", enums.COURT_DECISIONS)
    modified_purpose_code = opt_str(body, "modified_purpose_code", pattern=CODE_PATTERN)

    fund = services.find_fund(fund_id)
    # Ladder rule 18.
    if fund["transfer_status"] != "PETITION_FILED":
        fail("ERR_INVALID_FUND_STATE",
             "A court answer may only be recorded against a PETITION_FILED fund.")

    fund["court_decision"] = decision
    if decision == "DENIED":
        fund["transfer_status"] = "RETAINED"
        fund["transferable_amount_cents"] = 0
        fund["retained_amount_cents"] = calc.fund_value(fund)
    else:
        fund["transfer_status"] = "MODIFIED"
        if modified_purpose_code is not None:
            fund["modified_purpose_code"] = modified_purpose_code
        fund["transferable_amount_cents"] = calc.transferable_amount(
            fund, "JUDICIAL_MODIFICATION")
    touch(fund)
    services.refresh_corpus_for_ids([fund["org_id"]])
    services.recompute_postures_for_orgs([fund["org_id"]])
    return ok_row(fund)


@bp.post("/restricted-funds/<fund_id>/transfer")
def transfer_fund(fund_id):
    authenticate(["CharitableTrustCounsel"])
    body = body_object()
    restructuring_id = req_id(body, "restructuring_id")
    transfer_basis = req_enum(body, "transfer_basis", enums.TRANSFER_BASES)

    # Ladder rule 5 resolves the deal before rule 9 resolves the fund.
    deal = services.find_deal(restructuring_id)
    fund = services.find_fund(fund_id)

    # Ladder rule 16.
    if deal["status"] not in TRANSFER_DEAL_STATES:
        fail("ERR_INVALID_DEAL_STATE",
             "A restricted fund cannot be transferred while the deal is %s."
             % deal["status"])
    # Ladder rule 18: only the exhausted rows.
    if fund["transfer_status"] in ("TRANSFERRED", "RETAINED"):
        fail("ERR_INVALID_FUND_STATE",
             "This fund is %s and can no longer be transferred."
             % fund["transfer_status"])
    # Ladder rule 26.
    init, tgt = services.parties(deal)
    if fund["org_id"] == init:
        recipient_id = tgt
    elif fund["org_id"] == tgt:
        recipient_id = init
    else:
        fail("ERR_FUND_NOT_DEAL_PARTY_ASSET",
             "This fund is not held by either party of the deal.")
    # Ladder rule 29.
    if fund["restriction_conflict"] and transfer_basis == "DONOR_CONSENT":
        fail("ERR_JUDICIAL_ORDER_REQUIRED",
             "A conflicting restriction can only be released by a judicial "
             "modification.")
    # Ladder rule 30: the declared basis must match the branch actually travelled.
    ok_basis = ((transfer_basis == "DONOR_CONSENT"
                 and fund["transfer_status"] == "CONSENT_GRANTED")
                or (transfer_basis == "JUDICIAL_MODIFICATION"
                    and fund["transfer_status"] == "MODIFIED"))
    if not ok_basis:
        fail("ERR_DONOR_CONSENT_REQUIRED",
             "This fund holds neither the donor consent nor the judicial order the "
             "declared basis requires.")

    # CASCADE HOP 1: the fund moves.
    moved = fund["transferable_amount_cents"]
    fund["transfer_status"] = "TRANSFERRED"
    fund["transfer_basis"] = transfer_basis
    fund["transfer_restructuring_id"] = deal["id"]
    fund["transferred_to_org_id"] = recipient_id
    fund["transferred_amount_cents"] = moved
    fund["retained_amount_cents"] = calc.fund_value(fund) - moved
    touch(fund)

    # CASCADE HOP 2: both parties' corpus figures are recomputed, pair total conserved.
    services.refresh_corpus_for_ids([fund["org_id"], recipient_id], force=True)

    # CASCADE HOP 3: the deal's count and posture are recomputed.
    services.recompute_deal_restricted(deal)
    touch(deal)

    # CASCADE HOP 4: held program-continuity tasks are released.
    if deal["restricted_asset_posture"] == "CLEARED":
        services.release_held_continuity_tasks(deal)

    services.recompute_postures_for_orgs([fund["org_id"], recipient_id])
    return ok_row(fund)


@bp.post("/restricted-funds/<fund_id>/unwind")
def unwind(fund_id):
    authenticate(["CharitableTrustCounsel"])
    body = body_object()
    req_str(body, "unwind_reason", min_len=1)

    fund = services.find_fund(fund_id)
    deal = None
    if isinstance(fund["transfer_restructuring_id"], str):
        deal = services.find_deal(fund["transfer_restructuring_id"])
        # Ladder rule 16.
        if deal["status"] == "CONSUMMATED":
            fail("ERR_INVALID_DEAL_STATE",
                 "A transfer under a consummated deal can no longer be unwound.")
    # Ladder rule 18.
    if fund["transfer_status"] != "TRANSFERRED":
        fail("ERR_INVALID_FUND_STATE", "Only a TRANSFERRED fund can be unwound.")

    services.unwind_fund(fund, deal)
    if deal is not None:
        touch(deal)
    return ok_row(fund)

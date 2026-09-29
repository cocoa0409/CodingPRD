"""Investors, broker-dealers and selling agreements — PRD §3.2 and §3.3."""

from flask import Blueprint

import calc
import domain
import validate as V
from auth import require_roles, role, user_id
from errors import fail
from response import object_response
from routes.helpers import listing, new, resolve, single
from store import DB, all_rows, new_row, touch

bp = Blueprint("investors", __name__)

SUITABILITY_STATES = ("INCOMPLETE", "DOCUMENTED", "FLAGGED")
ACCOUNT_STATES = ("ACTIVE", "CLOSED_NO_POSITION")
SUPERVISION_STATES = ("IN_GOOD_STANDING", "HEIGHTENED_SUPERVISION", "BARRED")
AGREEMENT_STATES = ("PENDING", "ACTIVE", "SUSPENDED", "TERMINATED")
SEVERITIES = ("MINOR", "MAJOR")


# --------------------------------------------------------------------------
# Investor
# --------------------------------------------------------------------------

@bp.post("/investors")
def create_investor():
    require_roles("SponsorOperator", "TransferAgent", "BrokerDealerRep")
    body = V.json_body()
    legal_name = V.string(body, "legal_name", min_len=1, max_len=120)
    email = V.string(body, "email", min_len=1)
    state_code = V.string(body, "state_code", min_len=2, max_len=2)
    if not state_code.isalpha() or not state_code.isupper():
        fail("ERR_INVALID_REQUEST",
             "Field 'state_code' must be exactly two uppercase letters.")
    net_worth = V.integer(body, "net_worth_cents", minimum=0)
    annual_income = V.integer(body, "annual_income_cents", minimum=0)

    for other in all_rows("investors"):
        if other["email"] == email:
            fail("ERR_DUPLICATE_INVESTOR_EMAIL")

    row = new_row("investors", {
        "legal_name": legal_name,
        "email": email,
        "state_code": state_code,
        "net_worth_cents": net_worth,
        "annual_income_cents": annual_income,
        "suitability_status": "INCOMPLETE",
        "suitability_documentation_reference": None,
        "concentration_limit_cents": calc.concentration_limit_cents(
            state_code, net_worth, annual_income),
        "cumulative_invested_cents": 0,
        "total_shares_e4": 0,
        "cumulative_distributions_received_cents": 0,
        "cumulative_early_repurchase_deduction_cents": 0,
        "account_status": "ACTIVE",
    })
    return new(row)


@bp.get("/investors")
def list_investors():
    require_roles("SponsorOperator", "ComplianceOfficer", "TransferAgent",
                  "BrokerDealerRep")
    limit, offset = V.pagination()
    suitability = V.query_enum("suitability_status", SUITABILITY_STATES)
    account = V.query_enum("account_status", ACCOUNT_STATES)
    state_code = V.query_string("state_code")
    rows = [i for i in all_rows("investors")
            if (suitability is None or i["suitability_status"] == suitability)
            and (account is None or i["account_status"] == account)
            and (state_code is None or i["state_code"] == state_code)]
    return listing(rows, limit, offset)


@bp.get("/investors/<investor_id>")
def get_investor(investor_id):
    require_roles("SponsorOperator", "ComplianceOfficer", "TransferAgent",
                  "BrokerDealerRep", "InvestorUser")
    return single(resolve("investors", investor_id))


@bp.post("/investors/<investor_id>/suitability-documentation")
def record_suitability(investor_id):
    require_roles("BrokerDealerRep", "ComplianceOfficer")
    body = V.json_body()
    reference = V.string(body, "documentation_reference", min_len=1)
    investor = resolve("investors", investor_id)

    # PRD §3.2 — only a ComplianceOfficer may clear a FLAGGED account.
    if investor["suitability_status"] == "FLAGGED" and role() != "ComplianceOfficer":
        fail("ERR_ROLE_NOT_PERMITTED",
             "Only a ComplianceOfficer may clear a FLAGGED investor.")

    investor["suitability_status"] = "DOCUMENTED"
    investor["suitability_documentation_reference"] = reference
    touch(investor)
    domain.sync_derived()
    return single(investor)


@bp.get("/investors/<investor_id>/statement")
def investor_statement(investor_id):
    require_roles("TransferAgent", "SponsorOperator", "InvestorUser")
    investor = resolve("investors", investor_id)
    if role() == "InvestorUser" and user_id() != investor["id"]:
        fail("ERR_NOT_RESOURCE_OWNER")

    open_lots = domain.open_lots_of(investor["id"])
    estimated = 0
    for lot in open_lots:
        price = domain.transaction_price_of_class_id(lot["share_class_id"])
        estimated += calc.lot_value_cents(price, lot["remaining_shares_e4"])

    return object_response({
        "investor_id": investor["id"],
        "total_shares_e4": investor["total_shares_e4"],
        "open_lot_count": len(open_lots),
        "cumulative_invested_cents": investor["cumulative_invested_cents"],
        "cumulative_distributions_received_cents":
            investor["cumulative_distributions_received_cents"],
        "cumulative_early_repurchase_deduction_cents":
            investor["cumulative_early_repurchase_deduction_cents"],
        "estimated_value_cents": estimated,
    })


# --------------------------------------------------------------------------
# BrokerDealer
# --------------------------------------------------------------------------

@bp.post("/broker-dealers")
def create_broker_dealer():
    require_roles("ComplianceOfficer")
    body = V.json_body()
    firm_name = V.string(body, "firm_name", min_len=1)
    crd_number = V.string(body, "crd_number", min_len=1)

    for other in all_rows("broker_dealers"):
        if other["crd_number"] == crd_number:
            fail("ERR_DUPLICATE_CRD_NUMBER")

    row = new_row("broker_dealers", {
        "firm_name": firm_name,
        "crd_number": crd_number,
        "supervision_status": "IN_GOOD_STANDING",
        "suspended_agreement_count": 0,
    })
    return new(row)


@bp.get("/broker-dealers")
def list_broker_dealers():
    require_roles("ComplianceOfficer", "SponsorOperator", "TransferAgent",
                  "BrokerDealerRep")
    limit, offset = V.pagination()
    supervision = V.query_enum("supervision_status", SUPERVISION_STATES)
    crd_number = V.query_string("crd_number")
    rows = [b for b in all_rows("broker_dealers")
            if (supervision is None or b["supervision_status"] == supervision)
            and (crd_number is None or b["crd_number"] == crd_number)]
    return listing(rows, limit, offset)


@bp.get("/broker-dealers/<broker_dealer_id>")
def get_broker_dealer(broker_dealer_id):
    require_roles("ComplianceOfficer", "SponsorOperator", "TransferAgent",
                  "BrokerDealerRep")
    return single(resolve("broker_dealers", broker_dealer_id))


@bp.post("/broker-dealers/<broker_dealer_id>/supervision-status")
def drive_supervision(broker_dealer_id):
    require_roles("ComplianceOfficer")
    body = V.json_body()
    to_status = V.enum(body, "to_status", SUPERVISION_STATES)
    V.string(body, "reason", required=False, default=None, min_len=0)
    firm = resolve("broker_dealers", broker_dealer_id)
    current = firm["supervision_status"]

    if current == "IN_GOOD_STANDING" and to_status == "HEIGHTENED_SUPERVISION":
        firm["supervision_status"] = "HEIGHTENED_SUPERVISION"
        touch(firm)
    elif current == "HEIGHTENED_SUPERVISION" and to_status == "IN_GOOD_STANDING":
        if firm["suspended_agreement_count"] != 0:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A firm with a suspended agreement may not return to good standing.")
        firm["supervision_status"] = "IN_GOOD_STANDING"
        touch(firm)
    elif current == "HEIGHTENED_SUPERVISION" and to_status == "BARRED":
        firm["supervision_status"] = "BARRED"
        touch(firm)
        for agreement in domain.agreements_of_firm(firm["id"]):
            if agreement["status"] in ("PENDING", "ACTIVE", "SUSPENDED"):
                agreement["status"] = "TERMINATED"
                touch(agreement)
                domain.reject_pending_subscriptions(agreement, "BROKER_DEALER_BARRED")
    else:
        fail("ERR_INVALID_STATE_TRANSITION")

    domain.sync_derived()
    return single(firm)


# --------------------------------------------------------------------------
# SellingAgreement
# --------------------------------------------------------------------------

@bp.post("/selling-agreements")
def create_selling_agreement():
    require_roles("ComplianceOfficer")
    body = V.json_body()
    offering_id = V.fk(body, "offering_id")
    broker_dealer_id = V.fk(body, "broker_dealer_id")
    max_commission = V.integer(body, "max_commission_bps", minimum=0, maximum=1300)
    documentation_required = V.boolean(body, "suitability_documentation_required",
                                       required=False, default=True)

    offering = resolve("offerings", offering_id)
    firm = resolve("broker_dealers", broker_dealer_id)

    row = new_row("selling_agreements", {
        "offering_id": offering["id"],
        "broker_dealer_id": firm["id"],
        "max_commission_bps": max_commission,
        "suitability_documentation_required": documentation_required,
        "status": "PENDING",
        "open_minor_finding_count": 0,
        "open_major_finding_count": 0,
    })
    return new(row)


@bp.get("/selling-agreements")
def list_selling_agreements():
    require_roles("ComplianceOfficer", "SponsorOperator", "TransferAgent",
                  "BrokerDealerRep")
    limit, offset = V.pagination()
    offering_id = V.query_string("offering_id")
    broker_dealer_id = V.query_string("broker_dealer_id")
    status = V.query_enum("status", AGREEMENT_STATES)
    rows = [a for a in all_rows("selling_agreements")
            if (offering_id is None or a["offering_id"] == offering_id)
            and (broker_dealer_id is None or a["broker_dealer_id"] == broker_dealer_id)
            and (status is None or a["status"] == status)]
    return listing(rows, limit, offset)


@bp.get("/selling-agreements/<selling_agreement_id>")
def get_selling_agreement(selling_agreement_id):
    require_roles("ComplianceOfficer", "SponsorOperator", "TransferAgent",
                  "BrokerDealerRep")
    return single(resolve("selling_agreements", selling_agreement_id))


@bp.post("/selling-agreements/<selling_agreement_id>/status")
def drive_agreement(selling_agreement_id):
    require_roles("ComplianceOfficer")
    body = V.json_body()
    to_status = V.enum(body, "to_status", AGREEMENT_STATES)
    V.string(body, "reason", required=False, default=None, min_len=0)
    agreement = resolve("selling_agreements", selling_agreement_id)
    current = agreement["status"]
    firm = DB["broker_dealers"].get(agreement["broker_dealer_id"])
    offering = DB["offerings"].get(agreement["offering_id"])

    if to_status == "ACTIVE" and current == "PENDING":
        # Dependencies in the global fixed order: offering registration first,
        # then the broker-dealer (PRD §2.9 level 8).
        if offering is None or offering["registration_status"] != "EFFECTIVE":
            fail("ERR_OFFERING_NOT_EFFECTIVE")
        if firm is not None and firm["supervision_status"] == "BARRED":
            fail("ERR_BROKER_DEALER_BARRED")
        agreement["status"] = "ACTIVE"
        touch(agreement)
    elif to_status == "SUSPENDED" and current == "ACTIVE":
        agreement["status"] = "SUSPENDED"
        touch(agreement)
        domain.escalate_firm_on_suspension(firm)
    elif to_status == "TERMINATED" and current in ("PENDING", "ACTIVE", "SUSPENDED"):
        agreement["status"] = "TERMINATED"
        touch(agreement)
        if current == "ACTIVE":
            domain.reject_pending_subscriptions(agreement, "AGREEMENT_TERMINATED")
    else:
        fail("ERR_INVALID_STATE_TRANSITION")

    domain.sync_derived()
    return single(agreement)


@bp.post("/selling-agreements/<selling_agreement_id>/supervision-findings")
def supervision_findings(selling_agreement_id):
    require_roles("ComplianceOfficer")
    body = V.json_body()
    action = V.enum(body, "action", ("RECORD", "RESOLVE"))
    severity = V.enum(body, "severity", SEVERITIES)
    V.string(body, "finding_reference", required=False, default=None, min_len=0)
    agreement = resolve("selling_agreements", selling_agreement_id)
    firm = DB["broker_dealers"].get(agreement["broker_dealer_id"])

    field = ("open_minor_finding_count" if severity == "MINOR"
             else "open_major_finding_count")
    if action == "RECORD":
        agreement[field] += 1
    else:
        agreement[field] = max(0, agreement[field] - 1)
    touch(agreement)

    minor = agreement["open_minor_finding_count"]
    major = agreement["open_major_finding_count"]
    if agreement["status"] == "ACTIVE":
        if minor >= calc.AUTO_SUSPEND_MINOR_THRESHOLD or \
                major >= calc.AUTO_SUSPEND_MAJOR_THRESHOLD:
            agreement["status"] = "SUSPENDED"
            domain.escalate_firm_on_suspension(firm)
    elif agreement["status"] == "SUSPENDED":
        clear = minor < calc.AUTO_SUSPEND_MINOR_THRESHOLD and major == 0
        if clear and (firm is None or firm["supervision_status"] != "BARRED"):
            agreement["status"] = "ACTIVE"

    domain.sync_derived()
    return single(agreement)

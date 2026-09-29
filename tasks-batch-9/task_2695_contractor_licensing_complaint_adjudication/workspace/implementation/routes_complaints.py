"""Complaint intake, jurisdiction screening, mediation and withdrawal."""

from flask import Blueprint, g

import calc
from core import (
    add_days,
    add_months,
    clock_date,
    created,
    db,
    err,
    fmt_date,
    get_body,
    new_row,
    ok,
    qfilter,
    render_list,
    require_auth,
    setf,
    touch,
    v_date,
    v_enum,
    v_id,
    v_money,
    v_str,
)
import domain
from domain import D, find, must, rows

bp = Blueprint("complaints", __name__)

OPEN_STATES = ("RECEIVED", "MEDIATION", "INVESTIGATION")


@bp.route("/licensing/complaints", methods=["POST"])
def create_complaint():
    require_auth(["Consumer", "LicensingAnalyst"])
    body = get_body()
    consumer_id = v_id(body, "consumer_id")
    alleged_loss_cents = v_money(body, "alleged_loss_cents")
    contract_date = v_date(body, "contract_date")
    description = v_str(body, "description")
    license_id = v_id(body, "license_id", required=False)
    subject_business_name = v_str(body, "subject_business_name", required=False)
    work_completed_on = v_date(body, "work_completed_on", required=False)
    if license_id is None and subject_business_name is None:
        err("ERR_INVALID_REQUEST",
            "subject_business_name is required when license_id is omitted")

    consumer = must("consumers", consumer_id)
    if license_id is not None:
        must("licenses", license_id)

    row = new_row()
    row.update({
        "consumer_id": consumer["id"],
        "license_id": license_id,
        "subject_business_name": subject_business_name,
        "alleged_loss_cents": alleged_loss_cents,
        "contract_date": fmt_date(contract_date),
        "work_completed_on": (fmt_date(work_completed_on)
                              if work_completed_on is not None else None),
        "description": description,
        "status": "RECEIVED",
        "mediation_round_count": 0,
        "mediation_deadline": None,
        "settlement_amount_cents": 0,
        "jurisdiction_basis": None,
        "dismissal_reason": None,
        "remand_reason": None,
    })
    db.complaints[row["id"]] = row
    return created(domain.ser_complaint(row))


@bp.route("/licensing/complaints/<rid>", methods=["GET"])
def get_complaint(rid):
    require_auth(["BoardAdmin", "LicensingAnalyst", "Investigator", "HearingOfficer",
                  "FundAdjudicator", "Consumer", "Licensee"])
    return ok(domain.ser_complaint(must("complaints", rid)))


@bp.route("/licensing/complaints", methods=["GET"])
def list_complaints():
    require_auth(["BoardAdmin", "LicensingAnalyst", "Investigator", "HearingOfficer",
                  "FundAdjudicator", "Consumer"])
    items = rows("complaints")
    for field in ("consumer_id", "license_id", "status", "jurisdiction_basis"):
        items = qfilter(items, field)
    return render_list(items, domain.ser_complaint)


@bp.route("/licensing/complaints/<rid>/screen", methods=["POST"])
def screen_complaint(rid):
    require_auth(["LicensingAnalyst"])
    body = get_body()
    jurisdiction_finding = v_enum(body, "jurisdiction_finding", ["ACCEPTED", "REJECTED"])
    rejection_reason = v_str(body, "rejection_reason", required=False)
    if jurisdiction_finding == "REJECTED" and rejection_reason is None:
        err("ERR_INVALID_REQUEST",
            "rejection_reason is required for a REJECTED jurisdiction_finding")

    complaint = must("complaints", rid)
    if complaint["status"] != "RECEIVED":
        err("ERR_COMPLAINT_STATE_INVALID", "only a RECEIVED complaint may be screened")

    if jurisdiction_finding == "REJECTED":
        setf(complaint, "status", "DISMISSED_NO_JURISDICTION")
        setf(complaint, "dismissal_reason", rejection_reason)
        touch(complaint)
        return ok(domain.ser_complaint(complaint))

    today = clock_date()
    reference = D(complaint.get("work_completed_on") or complaint["contract_date"])
    if today > add_months(reference, calc.STATUTE_OF_LIMITATIONS_MONTHS):
        err("ERR_STATUTE_OF_LIMITATIONS_EXPIRED",
            "the four-year limitation period has run")

    lic = find("licenses", complaint["license_id"]) if complaint["license_id"] else None
    if lic is not None and D(complaint["contract_date"]) < D(lic["issued_on"]):
        err("ERR_CONTRACT_PREDATES_LICENSE",
            "the contract predates the licence's issuance")

    if complaint["alleged_loss_cents"] < calc.MIN_JURISDICTIONAL_LOSS_CENTS:
        err("ERR_LOSS_BELOW_JURISDICTIONAL_MINIMUM",
            "the pleaded loss is below the jurisdictional minimum")

    mediation = False
    if lic is not None and lic["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED"):
        classification = find("trade_classifications", lic["classification_id"])
        if classification is not None and classification["mediation_required"]:
            mediation = True

    if mediation:
        setf(complaint, "status", "MEDIATION")
        setf(complaint, "jurisdiction_basis", "LICENSED_SUBJECT")
        setf(complaint, "mediation_round_count", 1)
        setf(complaint, "mediation_deadline",
             fmt_date(add_days(today, calc.MEDIATION_WINDOW_DAYS)))
    else:
        setf(complaint, "status", "INVESTIGATION")
        setf(complaint, "jurisdiction_basis",
             "LICENSED_SUBJECT" if lic is not None else "UNLICENSED_PRACTICE")
    touch(complaint)
    return ok(domain.ser_complaint(complaint))


@bp.route("/licensing/complaints/<rid>/mediation-outcome", methods=["POST"])
def mediation_outcome(rid):
    require_auth(["LicensingAnalyst"])
    body = get_body()
    outcome = v_enum(body, "outcome", ["SETTLED", "FAILED"])
    settlement_amount_cents = v_money(body, "settlement_amount_cents", required=False)
    if outcome == "SETTLED" and (settlement_amount_cents is None
                                 or settlement_amount_cents < 1):
        err("ERR_INVALID_REQUEST",
            "a SETTLED outcome requires settlement_amount_cents of at least one cent")

    complaint = must("complaints", rid)
    if complaint["status"] != "MEDIATION":
        err("ERR_COMPLAINT_STATE_INVALID",
            "only a complaint in MEDIATION may record a mediation outcome")

    if outcome == "SETTLED":
        setf(complaint, "settlement_amount_cents", settlement_amount_cents)
        setf(complaint, "status", "CLOSED_RESOLVED")
    else:
        if settlement_amount_cents is not None:
            setf(complaint, "settlement_amount_cents", settlement_amount_cents)
        setf(complaint, "status", "INVESTIGATION")
        setf(complaint, "mediation_deadline", None)
    touch(complaint)
    return ok(domain.ser_complaint(complaint))


@bp.route("/licensing/complaints/<rid>/remand-to-mediation", methods=["POST"])
def remand_complaint(rid):
    require_auth(["Investigator"])
    body = get_body()
    remand_reason = v_str(body, "remand_reason")

    complaint = must("complaints", rid)
    if complaint["status"] != "INVESTIGATION":
        err("ERR_COMPLAINT_STATE_INVALID",
            "only a complaint in INVESTIGATION may be remanded to mediation")

    if complaint["mediation_round_count"] >= calc.MAX_MEDIATION_ROUNDS:
        err("ERR_MEDIATION_ROUNDS_EXHAUSTED", "both mediation rounds have been spent")
    investigation_ids = set(i["id"] for i in rows("investigations")
                            if i.get("complaint_id") == complaint["id"])
    for citation in rows("citations"):
        if citation["investigation_id"] in investigation_ids:
            err("ERR_MEDIATION_ROUNDS_EXHAUSTED",
                "a citation has already issued on this complaint")

    today = clock_date()
    setf(complaint, "mediation_round_count", complaint["mediation_round_count"] + 1)
    setf(complaint, "mediation_deadline",
         fmt_date(add_days(today, calc.MEDIATION_WINDOW_DAYS)))
    setf(complaint, "remand_reason", remand_reason)
    setf(complaint, "status", "MEDIATION")
    touch(complaint)
    return ok(domain.ser_complaint(complaint))


@bp.route("/licensing/complaints/<rid>/withdraw", methods=["POST"])
def withdraw_complaint(rid):
    require_auth(["Consumer"])
    complaint = must("complaints", rid)
    if g.user_id != complaint["consumer_id"]:
        err("ERR_NOT_RESOURCE_OWNER", "this complaint belongs to another consumer")
    if complaint["status"] not in OPEN_STATES:
        err("ERR_COMPLAINT_STATE_INVALID", "this complaint is already closed")
    if complaint["status"] == "MEDIATION":
        setf(complaint, "mediation_deadline", None)
    setf(complaint, "status", "WITHDRAWN")
    touch(complaint)
    return ok(domain.ser_complaint(complaint))

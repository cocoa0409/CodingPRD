"""Enforcement: investigations and citations."""

from flask import Blueprint, g

import calc
from core import (
    add_days,
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

bp = Blueprint("enforcement", __name__)

SEVERITIES = ["MINOR", "SERIOUS", "EGREGIOUS"]
RECIDIVISM_STATES = ("FINAL", "AFFIRMED", "MODIFIED", "SATISFIED")


def prior_final_citation_count(license_id, exclude_id=None):
    if license_id is None:
        return 0
    count = 0
    for c in domain.license_citations(license_id):
        if exclude_id is not None and c["id"] == exclude_id:
            continue
        if c["status"] in RECIDIVISM_STATES:
            count += 1
    return count


def citation_licensee(citation):
    lic = find("licenses", citation.get("license_id")) if citation.get("license_id") else None
    if lic is None:
        return None
    return find("licensees", lic["licensee_id"])


def citation_owner_check(citation):
    if g.role != "Licensee":
        return
    lic = find("licenses", citation.get("license_id")) if citation.get("license_id") else None
    if lic is None or lic["licensee_id"] != g.user_id:
        err("ERR_NOT_RESOURCE_OWNER", "this citation does not belong to the acting licensee")


def close_complaint_on_citation_final(citation):
    investigation = find("investigations", citation["investigation_id"])
    if investigation is None or not investigation.get("complaint_id"):
        return
    complaint = find("complaints", investigation["complaint_id"])
    if complaint is not None and complaint["status"] == "CITATION_ISSUED":
        setf(complaint, "status", "CLOSED_SANCTIONED")
        touch(complaint)


# ------------------------------------------------------------ investigations --
@bp.route("/licensing/investigations", methods=["POST"])
def create_investigation():
    require_auth(["Investigator"])
    body = get_body()
    origin = v_enum(body, "origin", ["COMPLAINT", "STING"])
    complaint_id = v_id(body, "complaint_id", required=False)
    subject_license_id = v_id(body, "subject_license_id", required=False)
    subject_business_name = v_str(body, "subject_business_name", required=False)

    complaint = None
    if complaint_id is not None:
        complaint = must("complaints", complaint_id)
    if subject_license_id is not None:
        must("licenses", subject_license_id)

    if origin == "COMPLAINT" and complaint is not None:
        if complaint["status"] != "INVESTIGATION":
            err("ERR_COMPLAINT_STATE_INVALID",
                "the parent complaint must sit in INVESTIGATION")

    if origin == "COMPLAINT" and complaint_id is None:
        err("ERR_INVESTIGATION_ORIGIN_MISMATCH",
            "a complaint-driven case must name its complaint_id")
    if origin == "STING" and complaint_id is not None:
        err("ERR_INVESTIGATION_ORIGIN_MISMATCH",
            "a sting case must not name a complaint_id")
    if subject_license_id is None and subject_business_name is None:
        err("ERR_INVESTIGATION_ORIGIN_MISMATCH",
            "subject_business_name is required when subject_license_id is omitted")

    row = new_row()
    row.update({
        "complaint_id": complaint_id,
        "subject_license_id": subject_license_id,
        "subject_business_name": subject_business_name,
        "origin": origin,
        "assigned_investigator_user_id": g.user_id,
        "status": "OPEN",
        "finding": None,
        "finding_severity": None,
        "evidence_summary": None,
        "opened_on": fmt_date(clock_date()),
        "closed_on": None,
    })
    db.investigations[row["id"]] = row
    return created(domain.ser_investigation(row))


@bp.route("/licensing/investigations/<rid>", methods=["GET"])
def get_investigation(rid):
    require_auth(["BoardAdmin", "LicensingAnalyst", "Investigator", "HearingOfficer",
                  "FundAdjudicator"])
    return ok(domain.ser_investigation(must("investigations", rid)))


@bp.route("/licensing/investigations", methods=["GET"])
def list_investigations():
    require_auth(["BoardAdmin", "LicensingAnalyst", "Investigator", "HearingOfficer"])
    items = rows("investigations")
    for field in ("complaint_id", "subject_license_id", "origin", "status"):
        items = qfilter(items, field)
    return render_list(items, domain.ser_investigation)


@bp.route("/licensing/investigations/<rid>/close", methods=["POST"])
def close_investigation(rid):
    require_auth(["Investigator"])
    body = get_body()
    finding = v_enum(body, "finding", ["SUBSTANTIATED", "UNSUBSTANTIATED"])
    evidence_summary = v_str(body, "evidence_summary")
    finding_severity = v_enum(body, "finding_severity", SEVERITIES, required=False)
    if finding == "SUBSTANTIATED" and finding_severity is None:
        err("ERR_INVALID_REQUEST",
            "finding_severity is required for a SUBSTANTIATED finding")

    investigation = must("investigations", rid)
    if investigation["status"] != "OPEN":
        err("ERR_INVESTIGATION_STATE_INVALID", "only an OPEN case may be closed")
    if g.user_id != investigation["assigned_investigator_user_id"]:
        err("ERR_NOT_ASSIGNED_INVESTIGATOR",
            "only the assigned investigator may close this case")

    complaint = None
    if investigation["origin"] == "COMPLAINT" and investigation.get("complaint_id"):
        complaint = find("complaints", investigation["complaint_id"])

    if finding == "SUBSTANTIATED":
        if complaint is not None and complaint["status"] != "INVESTIGATION":
            err("ERR_COMPLAINT_STATE_INVALID",
                "the linked complaint must still sit in INVESTIGATION")
        setf(investigation, "finding_severity", finding_severity)
    setf(investigation, "finding", finding)
    setf(investigation, "evidence_summary", evidence_summary)
    setf(investigation, "closed_on", fmt_date(clock_date()))
    setf(investigation, "status", finding)
    touch(investigation)

    if finding == "UNSUBSTANTIATED" and complaint is not None:
        if complaint["status"] == "INVESTIGATION":
            setf(complaint, "status", "CLOSED_UNFOUNDED")
            touch(complaint)

    return ok(domain.ser_investigation(investigation))


# ------------------------------------------------------------------ citations --
@bp.route("/licensing/citations", methods=["POST"])
def create_citation():
    require_auth(["Investigator"])
    body = get_body()
    investigation_id = v_id(body, "investigation_id")
    classification_id = v_id(body, "classification_id")
    violation_code = v_str(body, "violation_code")
    correction_due_date = v_date(body, "correction_due_date")

    investigation = must("investigations", investigation_id)
    classification = must("trade_classifications", classification_id)

    if investigation["status"] != "SUBSTANTIATED" or not investigation.get("finding_severity"):
        err("ERR_INVESTIGATION_NOT_SUBSTANTIATED",
            "a citation may only issue on a SUBSTANTIATED case")
    if g.user_id != investigation["assigned_investigator_user_id"]:
        err("ERR_NOT_ASSIGNED_INVESTIGATOR",
            "only the assigned investigator may issue this citation")

    license_id = investigation.get("subject_license_id")
    lic = find("licenses", license_id) if license_id else None
    if lic is not None and classification["id"] != lic["classification_id"]:
        err("ERR_CLASSIFICATION_MISMATCH",
            "the citation classification must match the licence's own classification")

    today = clock_date()
    severity = investigation["finding_severity"]
    subject_type = "LICENSED" if lic is not None else "UNLICENSED"
    priors = prior_final_citation_count(license_id)
    penalty = calc.citation_civil_penalty(severity, subject_type,
                                          classification["hazard_tier"], priors,
                                          mitigation=False)

    row = new_row()
    row.update({
        "investigation_id": investigation["id"],
        "license_id": license_id,
        "classification_id": classification["id"],
        "subject_type": subject_type,
        "violation_code": violation_code,
        "severity": severity,
        "civil_penalty_cents": penalty,
        "penalty_variant": "INITIAL_ASSESSMENT",
        "penalty_paid_cents": 0,
        "prior_final_citation_count": priors,
        "correction_due_date": fmt_date(correction_due_date),
        "correction_completed_on": None,
        "issued_on": fmt_date(today),
        "appeal_deadline": fmt_date(add_days(today, calc.APPEAL_WINDOW_DAYS)),
        "appeal_grounds": None,
        "status": "ISSUED",
    })
    db.citations[row["id"]] = row

    if investigation.get("complaint_id"):
        complaint = find("complaints", investigation["complaint_id"])
        if complaint is not None and complaint["status"] == "INVESTIGATION":
            setf(complaint, "status", "CITATION_ISSUED")
            touch(complaint)

    return created(domain.ser_citation(row))


@bp.route("/licensing/citations/<rid>", methods=["GET"])
def get_citation(rid):
    require_auth(["BoardAdmin", "LicensingAnalyst", "Investigator", "HearingOfficer",
                  "FundAdjudicator", "Licensee", "Consumer"])
    return ok(domain.ser_citation(must("citations", rid)))


@bp.route("/licensing/citations", methods=["GET"])
def list_citations():
    require_auth(["BoardAdmin", "LicensingAnalyst", "Investigator", "HearingOfficer",
                  "FundAdjudicator", "Licensee"])
    items = rows("citations")
    for field in ("investigation_id", "license_id", "classification_id", "status"):
        items = qfilter(items, field)
    return render_list(items, domain.ser_citation)


@bp.route("/licensing/citations/<rid>/appeal", methods=["POST"])
def appeal_citation(rid):
    require_auth(["Licensee"])
    body = get_body()
    appeal_grounds = v_str(body, "appeal_grounds")

    citation = must("citations", rid)
    citation_owner_check(citation)
    if citation["status"] != "ISSUED":
        err("ERR_CITATION_STATE_INVALID", "only an ISSUED citation may be appealed")
    if clock_date() > D(citation["appeal_deadline"]):
        err("ERR_APPEAL_WINDOW_CLOSED", "the fifteen-day appeal window has closed")

    setf(citation, "appeal_grounds", appeal_grounds)
    setf(citation, "status", "APPEAL_REQUESTED")
    touch(citation)
    return ok(domain.ser_citation(citation))


@bp.route("/licensing/citations/<rid>/finalize", methods=["POST"])
def finalize_citation(rid):
    require_auth(["LicensingAnalyst"])
    citation = must("citations", rid)
    if citation["status"] != "ISSUED":
        err("ERR_CITATION_STATE_INVALID", "only an ISSUED citation may be defaulted final")
    if clock_date() <= D(citation["appeal_deadline"]):
        err("ERR_APPEAL_WINDOW_OPEN", "the appeal window has not yet closed")

    setf(citation, "status", "FINAL")
    touch(citation)

    close_complaint_on_citation_final(citation)

    licensee = citation_licensee(citation)
    if licensee is not None:
        touch(licensee)
    lic = find("licenses", citation.get("license_id")) if citation.get("license_id") else None
    if lic is not None:
        domain.recompute_posture(lic)
    return ok(domain.ser_citation(citation))


@bp.route("/licensing/citations/<rid>/comply", methods=["POST"])
def comply_citation(rid):
    require_auth(["Licensee"])
    body = get_body()
    penalty_payment_cents = v_money(body, "penalty_payment_cents")
    corrected_on = v_date(body, "corrected_on")

    citation = must("citations", rid)
    citation_owner_check(citation)
    if citation["status"] not in ("FINAL", "AFFIRMED", "MODIFIED"):
        err("ERR_CITATION_STATE_INVALID",
            "only a FINAL, AFFIRMED or MODIFIED citation may be discharged")

    due = citation["civil_penalty_cents"] - citation["penalty_paid_cents"]
    if penalty_payment_cents != due:
        err("ERR_PAYMENT_AMOUNT_MISMATCH",
            "the payment must equal the outstanding penalty exactly")

    setf(citation, "penalty_paid_cents", citation["civil_penalty_cents"])
    setf(citation, "correction_completed_on", fmt_date(corrected_on))
    setf(citation, "status", "SATISFIED")
    touch(citation)

    licensee = citation_licensee(citation)
    if licensee is not None:
        touch(licensee)
    lic = find("licenses", citation.get("license_id")) if citation.get("license_id") else None
    if lic is not None:
        domain.recompute_posture(lic)
    return ok(domain.ser_citation(citation))

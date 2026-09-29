"""Licence applications: filing, submission, cure, decision, withdrawal."""

from flask import Blueprint, g, request

import calc
from core import (
    add_months,
    clock_date,
    created,
    db,
    err,
    fmt_date,
    get_body,
    new_row,
    now_ts,
    ok,
    qfilter,
    render_list,
    require_auth,
    setf,
    touch,
    v_enum,
    v_id,
    v_money,
    v_str,
)
import domain
from domain import D, find, must, rows

bp = Blueprint("applications", __name__)

APPLICATION_TYPES = ["ORIGINAL", "ADDITIONAL_CLASSIFICATION", "REINSTATEMENT"]
CREDENTIALS = ["NONE", "APPRENTICESHIP", "TWO_YEAR_DEGREE", "FOUR_YEAR_DEGREE"]
NON_TERMINAL = ("DRAFT", "SUBMITTED", "DEFICIENT")


# ---------------------------------------------------------------- helpers ---
def exam_requirement_met(qi_id, classification):
    today = clock_date()
    law_ok = False
    trade_ok = False
    for e in rows("exam_results"):
        if e["qualifying_individual_id"] != qi_id or not e["passed"]:
            continue
        if D(e["expires_on"]) < today:
            continue
        if e["exam_type"] == "LAW_AND_BUSINESS":
            law_ok = True
        elif e["exam_type"] == "TRADE" and e.get("trade_code") == classification["code"]:
            trade_ok = True
    return law_ok and trade_ok


def check_predecessor(application_type, predecessor_license_id, licensee_id,
                      classification_id):
    if application_type == "REINSTATEMENT":
        if predecessor_license_id is None:
            err("ERR_PREDECESSOR_LICENSE_INVALID",
                "predecessor_license_id is required for a REINSTATEMENT application")
        pred = find("licenses", predecessor_license_id)
        if pred is None:
            err("ERR_LICENSE_NOT_FOUND", "predecessor licence not found")
        if (pred["licensee_id"] != licensee_id
                or pred["classification_id"] != classification_id
                or pred["status"] not in ("REVOKED", "EXPIRED")):
            err("ERR_PREDECESSOR_LICENSE_INVALID",
                "predecessor licence does not qualify for reinstatement")
    else:
        if predecessor_license_id is not None:
            err("ERR_PREDECESSOR_LICENSE_INVALID",
                "predecessor_license_id must be omitted for this application_type")


def active_designations_covering(qi_id, on_date):
    count = 0
    for a in rows("qualifier_assignments"):
        if a["qualifying_individual_id"] != qi_id or a["status"] != "ACTIVE":
            continue
        if D(a["effective_from"]) > on_date:
            continue
        eff_to = a.get("effective_to")
        if eff_to is not None and D(eff_to) < on_date:
            continue
        count += 1
    return count


def run_eligibility(app):
    """Examination, experience and financial-responsibility gates."""
    classification = find("trade_classifications", app["classification_id"])
    qi = find("qualifying_individuals", app["qualifying_individual_id"])
    if not exam_requirement_met(app["qualifying_individual_id"], classification):
        err("ERR_EXAM_REQUIREMENT_UNMET",
            "the offered qualifier lacks a current passed LAW_AND_BUSINESS and TRADE examination")
    credited = calc.credited_experience_months(
        qi["verified_experience_months"], app["education_credential"],
        classification["min_experience_months"])
    if credited < classification["min_experience_months"]:
        err("ERR_EXPERIENCE_INSUFFICIENT",
            "credited experience of %d months is below the required %d"
            % (credited, classification["min_experience_months"]))
    if app["declared_net_worth_cents"] < classification["min_net_worth_cents"]:
        err("ERR_NET_WORTH_INSUFFICIENT", "declared net worth is below the minimum")
    return credited


def owner_check(licensee_id):
    if g.role == "Licensee" and g.user_id != licensee_id:
        err("ERR_NOT_RESOURCE_OWNER", "the acting licensee does not own this resource")


# ------------------------------------------------------------------ create --
@bp.route("/licensing/license-applications", methods=["POST"])
def create_application():
    require_auth(["Licensee", "LicensingAnalyst"])
    body = get_body()
    licensee_id = v_id(body, "licensee_id")
    classification_id = v_id(body, "classification_id")
    qualifying_individual_id = v_id(body, "qualifying_individual_id")
    application_type = v_enum(body, "application_type", APPLICATION_TYPES)
    declared_net_worth_cents = v_money(body, "declared_net_worth_cents")
    education_credential = v_enum(body, "education_credential", CREDENTIALS,
                                  required=False, default="NONE")
    predecessor_license_id = v_id(body, "predecessor_license_id", required=False)

    must("licensees", licensee_id)
    must("trade_classifications", classification_id)
    must("qualifying_individuals", qualifying_individual_id)
    if predecessor_license_id is not None:
        must("licenses", predecessor_license_id)

    check_predecessor(application_type, predecessor_license_id, licensee_id,
                      classification_id)

    for a in rows("license_applications"):
        if (a["licensee_id"] == licensee_id
                and a["classification_id"] == classification_id
                and a["status"] in NON_TERMINAL):
            err("ERR_DUPLICATE_APPLICATION",
                "a non-terminal application for this classification already exists")

    row = new_row()
    row.update({
        "licensee_id": licensee_id,
        "classification_id": classification_id,
        "qualifying_individual_id": qualifying_individual_id,
        "predecessor_license_id": predecessor_license_id,
        "application_type": application_type,
        "education_credential": education_credential,
        "declared_net_worth_cents": declared_net_worth_cents,
        "credited_experience_months": None,
        "status": "DRAFT",
        "deficiency_round_count": 0,
        "deficiency_reason": None,
        "denial_reason": None,
        "submitted_at": None,
    })
    db.license_applications[row["id"]] = row
    return created(domain.ser_application(row))


@bp.route("/licensing/license-applications/<rid>", methods=["GET"])
def get_application(rid):
    require_auth(["BoardAdmin", "LicensingAnalyst", "Licensee"])
    return ok(domain.ser_application(must("license_applications", rid)))


@bp.route("/licensing/license-applications", methods=["GET"])
def list_applications():
    require_auth(["BoardAdmin", "LicensingAnalyst", "Licensee"])
    items = rows("license_applications")
    for field in ("licensee_id", "classification_id", "qualifying_individual_id",
                  "predecessor_license_id", "status"):
        items = qfilter(items, field)
    return render_list(items, domain.ser_application)


# ------------------------------------------------------------------ submit --
@bp.route("/licensing/license-applications/<rid>/submit", methods=["POST"])
def submit_application(rid):
    require_auth(["Licensee"])
    app = must("license_applications", rid)
    owner_check(app["licensee_id"])
    if app["status"] != "DRAFT":
        err("ERR_APPLICATION_STATE_INVALID", "only a DRAFT application may be submitted")

    classification = find("trade_classifications", app["classification_id"])
    qi = find("qualifying_individuals", app["qualifying_individual_id"])
    if not exam_requirement_met(app["qualifying_individual_id"], classification):
        err("ERR_EXAM_REQUIREMENT_UNMET",
            "the offered qualifier lacks a current passed LAW_AND_BUSINESS and TRADE examination")
    check_predecessor(app["application_type"], app.get("predecessor_license_id"),
                      app["licensee_id"], app["classification_id"])
    credited = calc.credited_experience_months(
        qi["verified_experience_months"], app["education_credential"],
        classification["min_experience_months"])
    if credited < classification["min_experience_months"]:
        err("ERR_EXPERIENCE_INSUFFICIENT",
            "credited experience is below the statutory minimum")
    if app["declared_net_worth_cents"] < classification["min_net_worth_cents"]:
        err("ERR_NET_WORTH_INSUFFICIENT", "declared net worth is below the minimum")

    setf(app, "credited_experience_months", credited)
    setf(app, "status", "SUBMITTED")
    setf(app, "submitted_at", now_ts())
    setf(app, "deficiency_reason", None)
    touch(app)
    return ok(domain.ser_application(app))


# -------------------------------------------------------------------- cure --
@bp.route("/licensing/license-applications/<rid>/cure", methods=["POST"])
def cure_application(rid):
    require_auth(["Licensee"])
    body = get_body()
    declared_net_worth_cents = v_money(body, "declared_net_worth_cents", required=False)
    education_credential = v_enum(body, "education_credential", CREDENTIALS,
                                  required=False)
    qualifying_individual_id = v_id(body, "qualifying_individual_id", required=False)

    app = must("license_applications", rid)
    if qualifying_individual_id is not None:
        must("qualifying_individuals", qualifying_individual_id)
    owner_check(app["licensee_id"])
    if app["status"] != "DEFICIENT":
        err("ERR_APPLICATION_STATE_INVALID", "only a DEFICIENT application may be cured")

    if declared_net_worth_cents is not None:
        setf(app, "declared_net_worth_cents", declared_net_worth_cents)
    if education_credential is not None:
        setf(app, "education_credential", education_credential)
    if qualifying_individual_id is not None:
        setf(app, "qualifying_individual_id", qualifying_individual_id)

    credited = run_eligibility(app)

    setf(app, "credited_experience_months", credited)
    setf(app, "status", "SUBMITTED")
    setf(app, "submitted_at", now_ts())
    touch(app)
    return ok(domain.ser_application(app))


# ---------------------------------------------------------------- decision --
@bp.route("/licensing/license-applications/<rid>/decision", methods=["POST"])
def decide_application(rid):
    require_auth(["LicensingAnalyst"])
    body = get_body()
    outcome = v_enum(body, "outcome", ["APPROVED", "DEFICIENT", "DENIED"])
    deficiency_reason = v_str(body, "deficiency_reason", required=False)
    denial_reason = v_str(body, "denial_reason", required=False)

    app = must("license_applications", rid)
    if app["status"] != "SUBMITTED":
        err("ERR_APPLICATION_STATE_INVALID",
            "only a SUBMITTED application may be decided")

    if outcome == "DEFICIENT":
        if app["deficiency_round_count"] >= calc.MAX_DEFICIENCY_ROUNDS - 1:
            setf(app, "deficiency_round_count", calc.MAX_DEFICIENCY_ROUNDS)
            setf(app, "deficiency_reason", deficiency_reason)
            setf(app, "denial_reason", "EXCESSIVE_DEFICIENCY_ROUNDS")
            setf(app, "status", "DENIED")
        else:
            setf(app, "deficiency_round_count", app["deficiency_round_count"] + 1)
            setf(app, "deficiency_reason", deficiency_reason)
            setf(app, "status", "DEFICIENT")
        touch(app)
        return ok(domain.ser_application(app))

    if outcome == "DENIED":
        setf(app, "denial_reason", denial_reason)
        setf(app, "status", "DENIED")
        touch(app)
        return ok(domain.ser_application(app))

    # ---- APPROVED: re-verify examinations and qualifier capacity -----------
    classification = find("trade_classifications", app["classification_id"])
    if not exam_requirement_met(app["qualifying_individual_id"], classification):
        err("ERR_EXAM_REQUIREMENT_UNMET",
            "the offered qualifier's examinations are no longer current")
    today = clock_date()
    if active_designations_covering(app["qualifying_individual_id"], today) >= \
            calc.MAX_CONCURRENT_QUALIFICATIONS:
        err("ERR_QUALIFIER_CAPACITY_EXCEEDED",
            "the offered qualifier already holds the maximum concurrent designations")

    setf(app, "status", "APPROVED")
    touch(app)

    # 1. mint the licence
    lic = new_row()
    lic.update({
        "licensee_id": app["licensee_id"],
        "classification_id": app["classification_id"],
        "application_id": app["id"],
        "qualifying_individual_id": None,
        "predecessor_license_id": app.get("predecessor_license_id"),
        "license_number": db.next_license_number(),
        "status": "ACTIVE",
        "compliance_posture": "COMPLIANT",
        "issued_on": fmt_date(today),
        "expires_on": fmt_date(add_months(today, calc.LICENSE_TERM_MONTHS)),
        "suspension_reason": None,
        "suspension_until": None,
        "ce_hours_completed": 0,
        "last_renewed_on": None,
        "renewal_count": 0,
        "last_renewal_fee_cents": None,
    })
    db.licenses[lic["id"]] = lic

    # 2. designate the qualifier of record
    assignment = new_row()
    assignment.update({
        "license_id": lic["id"],
        "qualifying_individual_id": app["qualifying_individual_id"],
        "relationship_type": "RESPONSIBLE_MANAGING_EMPLOYEE",
        "ownership_pct": 0,
        "effective_from": lic["issued_on"],
        "effective_to": None,
        "status": "ACTIVE",
        "withdrawn_on": None,
    })
    db.qualifier_assignments[assignment["id"]] = assignment
    lic["qualifying_individual_id"] = app["qualifying_individual_id"]

    # 3. the designee's active-qualification count rises
    touch(find("qualifying_individuals", app["qualifying_individual_id"]))

    # 4. posture recomputation — no verified bond yet
    lic["compliance_posture"] = domain.compute_posture(lic)

    return ok(domain.ser_application(app))


# ---------------------------------------------------------------- withdraw --
@bp.route("/licensing/license-applications/<rid>/withdraw", methods=["POST"])
def withdraw_application(rid):
    require_auth(["Licensee"])
    app = must("license_applications", rid)
    owner_check(app["licensee_id"])
    if app["status"] not in NON_TERMINAL:
        err("ERR_APPLICATION_STATE_INVALID",
            "only an undecided application may be withdrawn")
    setf(app, "status", "WITHDRAWN")
    touch(app)
    return ok(domain.ser_application(app))

from flask import Blueprint, request

from db import store
import errors
import middleware
import response
from services import validate
from services import calc
from services.entities import (
    touch, get_license, get_business, get_activity_category,
    create_fee_assessment, parse_iso8601, add_months, recompute_audited_risk,
)
from services.serialize import public, public_list

bp = Blueprint("licenses", __name__)


# ---------------------------------------------------------------------------
def _license_expires_dt(lic):
    return parse_iso8601(lic["expires_on"])


def _compute_days_overdue(lic):
    delta = store.clock_now - _license_expires_dt(lic)
    return delta.days  # timedelta.days floors toward -inf; for overdue (>=0) it is whole days


def _unsettled_assessments(license_id, kinds=None):
    out = []
    for fa in store.fee_assessments.values():
        if fa.get("license_id") != license_id:
            continue
        if fa.get("settled"):
            continue
        if kinds is not None and fa.get("kind") not in kinds:
            continue
        out.append(fa)
    return out


def _business_has_other_bad_license(business_id, exclude_license_id):
    for l in store.licenses.values():
        if l["id"] == exclude_license_id:
            continue
        if l.get("business_id") == business_id and l.get("status") in ("DELINQUENT", "REVOKED"):
            return True
    return False


# ---------------------------------------------------------------------------
@bp.route("/licenses/<lid>", methods=["GET"])
def get_one(lid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant", "LicensingOfficer", "InspectionOfficer"])
    rec = get_license(lid)
    return response.object_response(public(rec), 200)


@bp.route("/licenses", methods=["GET"])
def list_all():
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant", "LicensingOfficer", "InspectionOfficer"])
    limit, offset = middleware.parse_pagination()
    business_id = request.args.get("business_id")
    activity_category_id = request.args.get("activity_category_id")
    application_id = request.args.get("application_id")
    items = list(store.licenses.values())
    if business_id is not None:
        items = [l for l in items if l.get("business_id") == business_id]
    if activity_category_id is not None:
        items = [l for l in items if l.get("activity_category_id") == activity_category_id]
    if application_id is not None:
        items = [l for l in items if l.get("application_id") == application_id]
    items.sort(key=lambda r: r["created_at"])
    page, total = middleware.paginate(items, limit, offset)
    return response.array_response(public_list(page), limit, offset, total, 200)


# ---------------------------------------------------------------------------
@bp.route("/licenses/<lid>/assess-delinquency", methods=["POST"])
def assess_delinquency(lid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer"])
    lic = get_license(lid)

    # state legality (409): defined from ACTIVE; also requires clock_now > expires_on
    if lic["status"] != "ACTIVE":
        raise errors.invalid_state("License must be ACTIVE to assess delinquency")
    if not (store.clock_now > _license_expires_dt(lic)):
        raise errors.invalid_state("License is not past expiry")

    cat = get_activity_category(lic["activity_category_id"])
    risk_tier = cat["risk_tier"]
    days = _compute_days_overdue(lic)
    penalty = calc.delinquency_penalty(risk_tier, days)
    renewal_fee = float(calc.RENEWAL_FEE[risk_tier])

    lic["status"] = "DELINQUENT"
    touch(lic)

    # always open a RENEWAL_FEE assessment; open DELINQUENCY_PENALTY only if penalty > 0
    create_fee_assessment("RENEWAL_FEE", renewal_fee, license_id=lic["id"], settled=False)
    if penalty > 0:
        create_fee_assessment("DELINQUENCY_PENALTY", penalty, license_id=lic["id"], settled=False)

    business = get_business(lic["business_id"])
    business["standing"] = "DELINQUENT"
    recompute_audited_risk(business)
    touch(business)

    return response.object_response(public(lic), 200)


@bp.route("/licenses/<lid>/renew", methods=["POST"])
def renew(lid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant"])
    lic = get_license(lid)

    # state legality (409): renew defined from ACTIVE or DELINQUENT
    if lic["status"] not in ("ACTIVE", "DELINQUENT"):
        raise errors.invalid_state("License must be ACTIVE or DELINQUENT to renew")

    cat = get_activity_category(lic["activity_category_id"])

    # renewal window: clock_now >= expires_on - RENEWAL_WINDOW_DAYS
    from datetime import timedelta
    window_open = _license_expires_dt(lic) - timedelta(days=calc.RENEWAL_WINDOW_DAYS)
    if store.clock_now < window_open:
        raise errors.ApiError(errors.ERR_RENEWAL_WINDOW_CLOSED, 409,
                              "Renewal window not open")

    was_delinquent = lic["status"] == "DELINQUENT"
    risk_tier = cat["risk_tier"]

    # advance expiry by term_months anchored to current expires_on
    new_expires = add_months(_license_expires_dt(lic), cat["term_months"])
    from db import now_iso
    lic["expires_on"] = now_iso(new_expires)
    lic["renewal_count"] = lic.get("renewal_count", 0) + 1
    lic["status"] = "ACTIVE"
    touch(lic)

    if was_delinquent:
        # settle outstanding RENEWAL_FEE and DELINQUENCY_PENALTY assessments
        for fa in _unsettled_assessments(lic["id"], kinds=("RENEWAL_FEE", "DELINQUENCY_PENALTY")):
            fa["settled"] = True
            touch(fa)
        # restore standing if no other DELINQUENT/REVOKED license
        business = get_business(lic["business_id"])
        if not _business_has_other_bad_license(business["id"], lic["id"]):
            business["standing"] = "GOOD"
            recompute_audited_risk(business)
            touch(business)
    else:
        # in-cycle renewal: create and immediately settle a RENEWAL_FEE
        renewal_fee = float(calc.RENEWAL_FEE[risk_tier])
        create_fee_assessment("RENEWAL_FEE", renewal_fee, license_id=lic["id"], settled=True)

    return response.object_response(public(lic), 200)


@bp.route("/licenses/<lid>/revoke", methods=["POST"])
def revoke(lid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer"])
    lic = get_license(lid)

    # state legality (409): revoke defined from DELINQUENT
    if lic["status"] != "DELINQUENT":
        raise errors.invalid_state("License must be DELINQUENT to revoke")

    days = _compute_days_overdue(lic)
    if not (days > calc.REVOCATION_THRESHOLD_DAYS):
        raise errors.ApiError(errors.ERR_REVOCATION_THRESHOLD_NOT_REACHED, 409,
                              "Revocation threshold not reached")

    lic["status"] = "REVOKED"
    touch(lic)

    # cascade 1: VOID all ACTIVE/SUSPENDED endorsements of this license
    for end in store.endorsements.values():
        if end.get("license_id") == lic["id"] and end.get("status") in ("ACTIVE", "SUSPENDED"):
            end["status"] = "VOIDED"
            touch(end)

    # cascade 2: CANCEL any REQUESTED/APPROVED transfer; cancel sets transfer_fee = 0
    for tr in store.transfers.values():
        if tr.get("license_id") == lic["id"] and tr.get("status") in ("REQUESTED", "APPROVED"):
            tr["status"] = "CANCELLED"
            tr["transfer_fee"] = 0
            touch(tr)

    # cascade 3: business REVOKED + prior_revocation_flag, recompute audited risk
    business = get_business(lic["business_id"])
    business["standing"] = "REVOKED"
    business["prior_revocation_flag"] = True
    recompute_audited_risk(business)
    touch(business)

    return response.object_response(public(lic), 200)


@bp.route("/licenses/<lid>/surrender", methods=["POST"])
def surrender(lid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant"])
    lic = get_license(lid)

    # state legality (409): surrender defined from ACTIVE
    if lic["status"] != "ACTIVE":
        raise errors.invalid_state("License must be ACTIVE to surrender")

    # fiscal gate: no outstanding unsettled FeeAssessment
    if _unsettled_assessments(lic["id"]):
        raise errors.ApiError(errors.ERR_OUTSTANDING_FEES, 409,
                              "License has outstanding unsettled fees")

    lic["status"] = "SURRENDERED"
    touch(lic)

    # VOID all ACTIVE endorsements
    for end in store.endorsements.values():
        if end.get("license_id") == lic["id"] and end.get("status") == "ACTIVE":
            end["status"] = "VOIDED"
            touch(end)

    return response.object_response(public(lic), 200)


# ---------------------------------------------------------------------------
@bp.route("/licenses/<lid>/endorsements", methods=["GET"])
def list_endorsements(lid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant", "LicensingOfficer", "InspectionOfficer"])
    get_license(lid)
    limit, offset = middleware.parse_pagination()
    items = [e for e in store.endorsements.values() if e.get("license_id") == lid]
    items.sort(key=lambda r: r["created_at"])
    page, total = middleware.paginate(items, limit, offset)
    return response.array_response(public_list(page), limit, offset, total, 200)


@bp.route("/licenses/<lid>/transfers", methods=["GET"])
def list_transfers(lid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant", "LicensingOfficer"])
    get_license(lid)
    limit, offset = middleware.parse_pagination()
    items = [t for t in store.transfers.values() if t.get("license_id") == lid]
    items.sort(key=lambda r: r["created_at"])
    page, total = middleware.paginate(items, limit, offset)
    return response.array_response(public_list(page), limit, offset, total, 200)


@bp.route("/licenses/<lid>/fee-assessments", methods=["GET"])
def list_fee_assessments(lid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer", "Applicant"])
    get_license(lid)
    limit, offset = middleware.parse_pagination()
    items = [f for f in store.fee_assessments.values() if f.get("license_id") == lid]
    items.sort(key=lambda r: r["created_at"])
    page, total = middleware.paginate(items, limit, offset)
    return response.array_response(public_list(page), limit, offset, total, 200)

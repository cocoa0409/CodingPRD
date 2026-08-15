"""Royalty reports and distributions."""
from flask import Blueprint

from store import db, create_record, touch
from util import (ApiError, require, get_body, check_schema, v_dt, v_int,
                  v_int_min, v_str, ok_object, ok_list, paginate)
from serializers import ser_report, ser_distribution
from services import (compute_acceptance, compute_distribution_figures,
                      apply_cost_offsets, reverse_cost_offsets,
                      recompute_license_rollups, recompute_disclosure_costs,
                      distribution_pay_cascade)

bp = Blueprint("royalties", __name__)


def _get_license_or_404(license_id):
    lic = db.licenses.get(license_id)
    if lic is None:
        raise ApiError("ERR_LICENSE_NOT_FOUND", 404, "LicenseAgreement id does not exist")
    return lic


def _get_report_or_404(report_id):
    rep = db.reports.get(report_id)
    if rep is None:
        raise ApiError("ERR_ROYALTY_REPORT_NOT_FOUND", 404, "RoyaltyReport id does not exist")
    return rep


def _get_distribution_or_404(distribution_id):
    dist = db.distributions.get(distribution_id)
    if dist is None:
        raise ApiError("ERR_DISTRIBUTION_NOT_FOUND", 404, "RoyaltyDistribution id does not exist")
    return dist


def _half_open_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# Royalty reports
# ---------------------------------------------------------------------------

@bp.route("/tlo/licenses/<licenseId>/royalty-reports", methods=["POST"])
def create_report(licenseId):
    require("LicensingManager")
    lic = _get_license_or_404(licenseId)
    data = check_schema(get_body(), {
        "period_start": (True, v_dt),
        "period_end": (True, v_dt),
        "reported_sales_cents": (True, v_int_min(0)),
    })
    if data["period_end"] <= data["period_start"]:
        raise ApiError("ERR_INVALID_REQUEST", 400, "period_end must be after period_start")
    for r in db.reports.values():
        if (r["license_id"] == lic["id"] and r["status"] != "VOIDED"
                and _half_open_overlap(data["period_start"], data["period_end"],
                                       r["period_start"], r["period_end"])):
            raise ApiError("ERR_REPORT_PERIOD_OVERLAP", 409,
                           "Report period overlaps an existing non-VOIDED report period on the license")
    rep = create_record(db.reports, {
        "license_id": lic["id"],
        "period_start": data["period_start"],
        "period_end": data["period_end"],
        "reported_sales_cents": data["reported_sales_cents"],
        "earned_royalty_cents": None,
        "true_up_cents": None,
        "accepted_royalty_cents": None,
        "status": "SUBMITTED",
    })
    return ok_object(ser_report(rep), status=201)


@bp.route("/tlo/licenses/<licenseId>/royalty-reports", methods=["GET"])
def list_reports(licenseId):
    require()
    lic = _get_license_or_404(licenseId)
    records = [r for r in db.reports.values() if r["license_id"] == lic["id"]]
    page, limit, offset, total = paginate(records)
    return ok_list([ser_report(r) for r in page], limit, offset, total)


@bp.route("/tlo/royalty-reports/<reportId>", methods=["GET"])
def get_report(reportId):
    require()
    return ok_object(ser_report(_get_report_or_404(reportId)))


@bp.route("/tlo/royalty-reports/<reportId>/accept", methods=["POST"])
def accept_report(reportId):
    require("FinanceOfficer")
    rep = _get_report_or_404(reportId)
    check_schema(get_body(), {})
    if rep["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_NOT_ACCEPTABLE", 409, "Accept requires report status SUBMITTED")
    lic = db.licenses[rep["license_id"]]
    earned, true_up, accepted = compute_acceptance(lic, rep)
    rep["earned_royalty_cents"] = earned
    rep["true_up_cents"] = true_up
    rep["accepted_royalty_cents"] = accepted
    rep["status"] = "ACCEPTED"
    touch(rep)
    recompute_license_rollups(lic)
    return ok_object(ser_report(rep))


# ---------------------------------------------------------------------------
# Royalty distributions
# ---------------------------------------------------------------------------

def _report_distribution(report_id):
    for d in db.distributions.values():
        if d["royalty_report_id"] == report_id:
            return d
    return None


@bp.route("/tlo/royalty-reports/<reportId>/distribution", methods=["POST"])
def create_distribution(reportId):
    uid, _ = require("FinanceOfficer")
    rep = _get_report_or_404(reportId)
    check_schema(get_body(), {})
    if rep["status"] != "ACCEPTED" or _report_distribution(rep["id"]) is not None:
        raise ApiError("ERR_REPORT_NOT_ACCEPTABLE", 409,
                       "Distribution requires an ACCEPTED report with no existing distribution")
    lic = db.licenses[rep["license_id"]]
    disc = db.disclosures[lic["disclosure_id"]]
    figures = compute_distribution_figures(rep, lic, disc)
    dist = create_record(db.distributions, {
        "royalty_report_id": rep["id"],
        "gross_cents": figures["gross_cents"],
        "cost_offset_cents": figures["cost_offset_cents"],
        "net_cents": figures["net_cents"],
        "admin_fee_cents": figures["admin_fee_cents"],
        "inventor_pool_cents": figures["inventor_pool_cents"],
        "department_pool_cents": figures["department_pool_cents"],
        "university_pool_cents": figures["university_pool_cents"],
        "inventor_shares": figures["inventor_shares"],
        "department_shares": figures["department_shares"],
        "cost_applications": [],
        "prepared_by_user_id": uid,
        "status": "CALCULATED",
    })
    return ok_object(ser_distribution(dist), status=201)


@bp.route("/tlo/royalty-reports/<reportId>/distribution", methods=["GET"])
def get_report_distribution(reportId):
    require()
    rep = _get_report_or_404(reportId)
    dist = _report_distribution(rep["id"])
    records = [dist] if dist is not None else []
    page, limit, offset, total = paginate(records)
    return ok_list([ser_distribution(d) for d in page], limit, offset, total)


@bp.route("/tlo/distributions/<distributionId>", methods=["GET"])
def get_distribution(distributionId):
    require()
    return ok_object(ser_distribution(_get_distribution_or_404(distributionId)))


@bp.route("/tlo/distributions/<distributionId>/recalculate", methods=["POST"])
def recalculate_distribution(distributionId):
    require("FinanceOfficer")
    dist = _get_distribution_or_404(distributionId)
    check_schema(get_body(), {})
    if dist["status"] != "CALCULATED":
        raise ApiError("ERR_DISTRIBUTION_NOT_APPROVABLE", 409,
                       "Recalculate requires distribution status CALCULATED")
    rep = db.reports[dist["royalty_report_id"]]
    lic = db.licenses[rep["license_id"]]
    disc = db.disclosures[lic["disclosure_id"]]
    figures = compute_distribution_figures(rep, lic, disc)
    for key in ("gross_cents", "cost_offset_cents", "net_cents", "admin_fee_cents",
                "inventor_pool_cents", "department_pool_cents", "university_pool_cents",
                "inventor_shares", "department_shares"):
        dist[key] = figures[key]
    touch(dist)
    return ok_object(ser_distribution(dist))


@bp.route("/tlo/distributions/<distributionId>/approve", methods=["POST"])
def approve_distribution(distributionId):
    uid, _ = require("FinanceDirector")
    dist = _get_distribution_or_404(distributionId)
    data = check_schema(get_body(), {
        "expected_distribution_version": (True, v_int),
    })
    if dist["status"] != "CALCULATED":
        raise ApiError("ERR_DISTRIBUTION_NOT_APPROVABLE", 409,
                       "Approve requires distribution status CALCULATED")
    if uid == dist["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409,
                       "Approver must differ from the distribution's preparer")
    if data["expected_distribution_version"] != dist["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_distribution_version does not match the distribution's current version")
    apply_cost_offsets(dist)
    dist["status"] = "APPROVED"
    touch(dist)
    return ok_object(ser_distribution(dist))


@bp.route("/tlo/distributions/<distributionId>/pay", methods=["POST"])
def pay_distribution(distributionId):
    require("FinanceDirector")
    dist = _get_distribution_or_404(distributionId)
    check_schema(get_body(), {})
    if dist["status"] != "APPROVED":
        raise ApiError("ERR_DISTRIBUTION_NOT_PAYABLE", 409,
                       "Pay requires distribution status APPROVED")
    dist["status"] = "PAID"
    touch(dist)
    distribution_pay_cascade(dist)
    return ok_object(ser_distribution(dist))


@bp.route("/tlo/distributions/<distributionId>/cancel", methods=["POST"])
def cancel_distribution(distributionId):
    require("FinanceDirector")
    dist = _get_distribution_or_404(distributionId)
    check_schema(get_body(), {"cancel_reason": (False, v_str)})
    if dist["status"] not in ("CALCULATED", "APPROVED"):
        raise ApiError("ERR_DISTRIBUTION_NOT_CANCELLABLE", 409,
                       "Cancel requires distribution status CALCULATED or APPROVED")
    if dist["status"] == "APPROVED":
        reverse_cost_offsets(dist)
    dist["status"] = "CANCELLED"
    touch(dist)
    return ok_object(ser_distribution(dist))

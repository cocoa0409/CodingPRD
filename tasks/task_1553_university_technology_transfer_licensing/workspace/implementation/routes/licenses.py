"""License agreements and milestones."""
from datetime import timedelta

from flask import Blueprint

from store import db, create_record, touch, now
from util import (ApiError, require, get_body, check_schema, v_nonempty_str,
                  v_str, v_enum, v_dt, v_int, v_int_range, v_int_min,
                  ok_object, ok_list, paginate)
from serializers import ser_license, ser_milestone
from services import (coi_coverage_active, license_termination_cascade,
                      CURE_PERIOD_DAYS)

bp = Blueprint("licenses", __name__)

EXCLUSIVE_MIN_UPFRONT_CENTS = 500000


def _get_disclosure_or_404(disclosure_id):
    disc = db.disclosures.get(disclosure_id)
    if disc is None:
        raise ApiError("ERR_DISCLOSURE_NOT_FOUND", 404, "Disclosure id does not exist")
    return disc


def _get_license_or_404(license_id):
    lic = db.licenses.get(license_id)
    if lic is None:
        raise ApiError("ERR_LICENSE_NOT_FOUND", 404, "LicenseAgreement id does not exist")
    return lic


def _get_milestone_or_404(milestone_id):
    ms = db.milestones.get(milestone_id)
    if ms is None:
        raise ApiError("ERR_MILESTONE_NOT_FOUND", 404, "LicenseMilestone id does not exist")
    return ms


def _closed_intervals_intersect(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


# ---------------------------------------------------------------------------
# Licenses
# ---------------------------------------------------------------------------

@bp.route("/tlo/disclosures/<disclosureId>/licenses", methods=["POST"])
def create_license(disclosureId):
    require("LicensingManager")
    disc = _get_disclosure_or_404(disclosureId)
    data = check_schema(get_body(), {
        "licensee_name": (True, v_nonempty_str),
        "exclusivity": (True, v_enum("EXCLUSIVE", "NON_EXCLUSIVE")),
        "effective_date": (True, v_dt),
        "expiration_date": (True, v_dt),
        "royalty_rate_bp": (True, v_int_range(100, 2000)),
        "minimum_annual_royalty_cents": (True, v_int_min(0)),
        "upfront_fee_cents": (True, v_int_min(0)),
        "startup_id": (False, v_nonempty_str),
    })
    if data["expiration_date"] <= data["effective_date"]:
        raise ApiError("ERR_INVALID_REQUEST", 400, "expiration_date must be after effective_date")
    if disc["status"] != "PATENT_PURSUED":
        raise ApiError("ERR_DISCLOSURE_INVALID_STATE", 409,
                       "License creation requires disclosure status PATENT_PURSUED")
    startup_id = data.get("startup_id")
    if startup_id is not None and startup_id not in db.startups:
        raise ApiError("ERR_STARTUP_NOT_FOUND", 404, "Startup id does not exist")
    lic = create_record(db.licenses, {
        "disclosure_id": disc["id"],
        "startup_id": startup_id,
        "licensee_name": data["licensee_name"],
        "exclusivity": data["exclusivity"],
        "effective_date": data["effective_date"],
        "expiration_date": data["expiration_date"],
        "royalty_rate_bp": data["royalty_rate_bp"],
        "minimum_annual_royalty_cents": data["minimum_annual_royalty_cents"],
        "upfront_fee_cents": data["upfront_fee_cents"],
        "status": "IN_NEGOTIATION",
        "default_notice_date": None,
        "cure_deadline": None,
        "cumulative_sales_cents": 0,
        "cumulative_royalty_cents": 0,
    })
    return ok_object(ser_license(lic), status=201)


@bp.route("/tlo/disclosures/<disclosureId>/licenses", methods=["GET"])
def list_licenses(disclosureId):
    require()
    disc = _get_disclosure_or_404(disclosureId)
    records = [l for l in db.licenses.values() if l["disclosure_id"] == disc["id"]]
    page, limit, offset, total = paginate(records)
    return ok_list([ser_license(l) for l in page], limit, offset, total)


@bp.route("/tlo/licenses/<licenseId>", methods=["GET"])
def get_license(licenseId):
    require()
    return ok_object(ser_license(_get_license_or_404(licenseId)))


@bp.route("/tlo/licenses/<licenseId>/counter", methods=["POST"])
def counter_license(licenseId):
    require("LicensingManager")
    lic = _get_license_or_404(licenseId)
    data = check_schema(get_body(), {
        "royalty_rate_bp": (False, v_int_range(100, 2000)),
        "minimum_annual_royalty_cents": (False, v_int_min(0)),
        "upfront_fee_cents": (False, v_int_min(0)),
        "expiration_date": (False, v_dt),
    })
    if "expiration_date" in data and data["expiration_date"] <= lic["effective_date"]:
        raise ApiError("ERR_INVALID_REQUEST", 400, "expiration_date must be after effective_date")
    if lic["status"] not in ("IN_NEGOTIATION", "COUNTERED"):
        raise ApiError("ERR_LICENSE_NOT_NEGOTIABLE", 409,
                       "Counter requires status IN_NEGOTIATION or COUNTERED")
    for field in ("royalty_rate_bp", "minimum_annual_royalty_cents", "upfront_fee_cents", "expiration_date"):
        if field in data:
            lic[field] = data[field]
    lic["status"] = "COUNTERED" if lic["status"] == "IN_NEGOTIATION" else "IN_NEGOTIATION"
    touch(lic)
    return ok_object(ser_license(lic))


@bp.route("/tlo/licenses/<licenseId>/execute", methods=["POST"])
def execute_license(licenseId):
    require("LicensingManager")
    lic = _get_license_or_404(licenseId)
    data = check_schema(get_body(), {
        "expected_license_version": (True, v_int),
    })
    if lic["status"] not in ("IN_NEGOTIATION", "COUNTERED"):
        raise ApiError("ERR_LICENSE_NOT_EXECUTABLE", 409,
                       "Execute requires status IN_NEGOTIATION or COUNTERED")
    if data["expected_license_version"] != lic["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_license_version does not match the license's current version")
    if lic["startup_id"] is not None and not coi_coverage_active(lic["startup_id"]):
        raise ApiError("ERR_COI_COVERAGE_REQUIRED", 409,
                       "No APPROVED COI plan for the linked startup covers the current clock")
    if lic["exclusivity"] == "EXCLUSIVE":
        for other in db.licenses.values():
            if (other["id"] != lic["id"]
                    and other["disclosure_id"] == lic["disclosure_id"]
                    and other["exclusivity"] == "EXCLUSIVE"
                    and other["status"] in ("EXECUTED", "ACTIVE", "DEFAULT_NOTICE")
                    and _closed_intervals_intersect(lic["effective_date"], lic["expiration_date"],
                                                    other["effective_date"], other["expiration_date"])):
                raise ApiError("ERR_EXCLUSIVE_OVERLAP", 409,
                               "Exclusive window intersects another EXECUTED/ACTIVE/DEFAULT_NOTICE "
                               "exclusive license on the disclosure")
        if lic["upfront_fee_cents"] < EXCLUSIVE_MIN_UPFRONT_CENTS:
            raise ApiError("ERR_UPFRONT_BELOW_FLOOR", 402,
                           "EXCLUSIVE execute requires upfront_fee_cents >= 500000")
    lic["status"] = "EXECUTED"
    touch(lic)
    return ok_object(ser_license(lic))


@bp.route("/tlo/licenses/<licenseId>/declare-default", methods=["POST"])
def declare_default(licenseId):
    require("LicensingManager")
    lic = _get_license_or_404(licenseId)
    check_schema(get_body(), {"reason": (True, v_str)})
    if lic["status"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_ACTIVE", 409, "Declare-default requires license status ACTIVE")
    clock = now()
    overdue = any(
        m["license_id"] == lic["id"] and m["status"] == "PENDING" and m["due_date"] < clock
        for m in db.milestones.values()
    )
    if not overdue:
        raise ApiError("ERR_NO_DEFAULT_GROUNDS", 409,
                       "Declare-default requires at least one overdue PENDING milestone")
    lic["status"] = "DEFAULT_NOTICE"
    lic["default_notice_date"] = clock
    lic["cure_deadline"] = clock + timedelta(days=CURE_PERIOD_DAYS)
    touch(lic)
    return ok_object(ser_license(lic))


@bp.route("/tlo/licenses/<licenseId>/cure", methods=["POST"])
def cure_license(licenseId):
    require("LicensingManager")
    lic = _get_license_or_404(licenseId)
    check_schema(get_body(), {})
    if lic["status"] != "DEFAULT_NOTICE":
        raise ApiError("ERR_LICENSE_NOT_IN_DEFAULT", 409, "Cure requires license status DEFAULT_NOTICE")
    if now() > lic["cure_deadline"]:
        raise ApiError("ERR_CURE_PERIOD_EXPIRED", 409, "Cure attempted after cure_deadline")
    lic["status"] = "ACTIVE"
    lic["default_notice_date"] = None
    lic["cure_deadline"] = None
    touch(lic)
    return ok_object(ser_license(lic))


@bp.route("/tlo/licenses/<licenseId>/terminate", methods=["POST"])
def terminate_license(licenseId):
    require("LicensingManager")
    lic = _get_license_or_404(licenseId)
    check_schema(get_body(), {"termination_reason": (False, v_str)})
    if lic["status"] != "DEFAULT_NOTICE":
        raise ApiError("ERR_LICENSE_NOT_TERMINABLE", 409,
                       "Terminate requires license status DEFAULT_NOTICE")
    if now() <= lic["cure_deadline"]:
        raise ApiError("ERR_CURE_PERIOD_ACTIVE", 409, "Terminate attempted on or before cure_deadline")
    lic["status"] = "TERMINATED"
    touch(lic)
    license_termination_cascade(lic)
    return ok_object(ser_license(lic))


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------

@bp.route("/tlo/licenses/<licenseId>/milestones", methods=["POST"])
def create_milestone(licenseId):
    require("LicensingManager")
    lic = _get_license_or_404(licenseId)
    data = check_schema(get_body(), {
        "description": (True, v_nonempty_str),
        "due_date": (True, v_dt),
        "amount_cents": (True, v_int_min(0)),
    })
    ms = create_record(db.milestones, {
        "license_id": lic["id"],
        "description": data["description"],
        "due_date": data["due_date"],
        "amount_cents": data["amount_cents"],
        "waiver_reason": None,
        "status": "PENDING",
    })
    return ok_object(ser_milestone(ms), status=201)


@bp.route("/tlo/licenses/<licenseId>/milestones", methods=["GET"])
def list_milestones(licenseId):
    require()
    lic = _get_license_or_404(licenseId)
    records = [m for m in db.milestones.values() if m["license_id"] == lic["id"]]
    page, limit, offset, total = paginate(records)
    return ok_list([ser_milestone(m) for m in page], limit, offset, total)


@bp.route("/tlo/milestones/<milestoneId>", methods=["GET"])
def get_milestone(milestoneId):
    require()
    return ok_object(ser_milestone(_get_milestone_or_404(milestoneId)))


def _get_nested_milestone(licenseId, milestoneId):
    lic = _get_license_or_404(licenseId)
    ms = db.milestones.get(milestoneId)
    if ms is None or ms["license_id"] != lic["id"]:
        raise ApiError("ERR_MILESTONE_NOT_FOUND", 404,
                       "LicenseMilestone id does not exist within the license")
    return lic, ms


@bp.route("/tlo/licenses/<licenseId>/milestones/<milestoneId>/achieve", methods=["POST"])
def achieve_milestone(licenseId, milestoneId):
    require("LicensingManager")
    lic, ms = _get_nested_milestone(licenseId, milestoneId)
    check_schema(get_body(), {})
    if ms["status"] != "PENDING":
        raise ApiError("ERR_MILESTONE_NOT_PENDING", 409, "Achieve requires milestone status PENDING")
    if lic["status"] not in ("EXECUTED", "ACTIVE"):
        raise ApiError("ERR_LICENSE_NOT_ACTIVE", 409,
                       "Achieve requires license status EXECUTED or ACTIVE")
    if now() > ms["due_date"]:
        raise ApiError("ERR_MILESTONE_OVERDUE", 409, "Achieve requires current clock on or before due_date")
    ms["status"] = "ACHIEVED"
    touch(ms)
    return ok_object(ser_milestone(ms))


@bp.route("/tlo/licenses/<licenseId>/milestones/<milestoneId>/waive", methods=["POST"])
def waive_milestone(licenseId, milestoneId):
    require("LicensingManager")
    lic, ms = _get_nested_milestone(licenseId, milestoneId)
    data = check_schema(get_body(), {"waiver_reason": (True, v_str)})
    if ms["status"] != "PENDING":
        raise ApiError("ERR_MILESTONE_NOT_PENDING", 409, "Waive requires milestone status PENDING")
    if lic["status"] not in ("ACTIVE", "DEFAULT_NOTICE"):
        raise ApiError("ERR_LICENSE_NOT_ACTIVE", 409,
                       "Waive requires license status ACTIVE or DEFAULT_NOTICE")
    ms["status"] = "WAIVED"
    ms["waiver_reason"] = data["waiver_reason"]
    touch(ms)
    return ok_object(ser_milestone(ms))

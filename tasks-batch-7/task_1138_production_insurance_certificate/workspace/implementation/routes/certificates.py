"""Certificate endpoints: draft, list, get, issue (OCC-guarded), void."""

from flask import request

from db import db
from errors import err
from middleware import require_roles
from response import success_list, success_object
from routes import bp
from services.posture import touch_production_once
from util import (
    add_days,
    body,
    get_child,
    get_production,
    make_entity,
    now,
    opt_string,
    paginate,
    req_dt,
    req_enum,
    req_string,
    serialize,
    touch,
)

CERTIFICATE_TYPES = ("LOCATION", "VENDOR", "EQUIPMENT_RENTAL", "PERMIT")
CERT_COVERAGE_LINES = ("GENERAL_LIABILITY", "EQUIPMENT", "ERRORS_OMISSIONS")
CERT_ROLES = {"BrokerAgent", "ProductionManager", "PlatformOperator"}
POST_PRODUCTION_EXTENSION_DAYS = 30


def get_certificate(prod_id, cert_id):
    return get_child(db.certificates, cert_id, "production_id", prod_id, "Certificate")


def _check_additional_insured(cert_type, data_or_rec):
    if cert_type in ("LOCATION", "PERMIT"):
        name = data_or_rec.get("additional_insured_name")
        if not isinstance(name, str) or name == "":
            raise err("ERR_ADDITIONAL_INSURED_REQUIRED",
                      "additional_insured_name is required for %s certificates" % cert_type)


def _parse_coverage_lines(data):
    lines = data.get("coverage_lines")
    if not isinstance(lines, list):
        raise err("ERR_INVALID_REQUEST",
                  "Field 'coverage_lines' is required and must be an array")
    for line in lines:
        if not isinstance(line, str) or line not in CERT_COVERAGE_LINES:
            raise err("ERR_INVALID_ENUM",
                      "coverage_lines entries must be in %s" % list(CERT_COVERAGE_LINES))
    return list(lines)


@bp.route("/productions/<id>/certificates", methods=["POST"])
def create_certificate(id):
    require_roles({"BrokerAgent"})
    with db.lock:
        get_production(id)
        data = body()
        cert_type = data.get("certificate_type")
        if not isinstance(cert_type, str) or not cert_type:
            raise err("ERR_INVALID_REQUEST", "Field 'certificate_type' is required")
        holder_name = req_string(data, "holder_name")
        holder_address = req_string(data, "holder_address")
        _check_additional_insured(cert_type, data)
        if cert_type not in CERTIFICATE_TYPES:
            raise err("ERR_INVALID_ENUM",
                      "certificate_type must be one of %s" % list(CERTIFICATE_TYPES))
        additional_insured_name = opt_string(data, "additional_insured_name")
        coverage_lines = _parse_coverage_lines(data)
        location_start = req_dt(data, "location_start")
        location_end = req_dt(data, "location_end")
        if location_end <= location_start:
            raise err("ERR_TEMPORAL_RANGE_INVALID",
                      "location_end must be after location_start")

        rec = make_entity({
            "production_id": id,
            "certificate_type": cert_type,
            "holder_name": holder_name,
            "holder_address": holder_address,
            "additional_insured_name": additional_insured_name,
            "coverage_lines": coverage_lines,
            "location_start": location_start,
            "location_end": location_end,
            "certificate_number": None,
            "status": "DRAFT",
        })
        db.certificates[rec["id"]] = rec
        return success_object(serialize(rec), status=201)


@bp.route("/productions/<id>/certificates", methods=["GET"])
def list_certificates(id):
    require_roles(CERT_ROLES)
    get_production(id)
    ctype = request.args.get("certificate_type")
    status = request.args.get("status")
    records = [c for c in db.certificates.values() if c["production_id"] == id]
    if ctype is not None:
        records = [r for r in records if r["certificate_type"] == ctype]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, page = paginate(records)
    return success_list(items, page)


@bp.route("/productions/<id>/certificates/<childId>", methods=["GET"])
def get_certificate_by_id(id, childId):
    require_roles(CERT_ROLES)
    get_production(id)
    rec = get_certificate(id, childId)
    return success_object(serialize(rec))


@bp.route("/productions/<id>/certificates/<childId>/issue", methods=["POST"])
def issue_certificate(id, childId):
    require_roles({"BrokerAgent"})
    with db.lock:
        prod = get_production(id)
        cert = get_certificate(id, childId)
        if cert["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE",
                      "Certificate must be DRAFT to issue (current: %s)" % cert["status"])

        data = body()
        expected = data.get("expected_production_version")
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err("ERR_INVALID_REQUEST",
                      "Field 'expected_production_version' is required and must be an integer")
        if expected != prod["version"]:
            raise err("ERR_STALE_VERSION",
                      "expected_production_version %s does not match current version %s"
                      % (expected, prod["version"]))

        if prod["status"] != "ACTIVE":
            raise err("ERR_PRODUCTION_NOT_ACTIVE",
                      "Production must be ACTIVE to issue certificates (current: %s)"
                      % prod["status"])

        if prod["coverage_posture"] not in ("BOUND_FULL", "BOUND_PARTIAL"):
            raise err("ERR_POSTURE_BLOCKS_ISSUANCE",
                      "coverage_posture %s blocks certificate issuance"
                      % prod["coverage_posture"])

        # Every listed line must have a bound policy on this production.
        for line in cert["coverage_lines"]:
            bound = [
                p for p in db.policies.values()
                if p["production_id"] == id and p["coverage_line"] == line
                and p["status"] in ("BOUND", "ENDORSED_PENDING", "ACTIVE")
            ]
            if not bound:
                raise err("ERR_COVERAGE_LINE_NOT_BOUND",
                          "Coverage line %s has no bound policy on this production" % line)

        _check_additional_insured(cert["certificate_type"], cert)

        # Window containment: outer production envelope (end-inclusive at
        # pp_end + 30 days) plus each bound policy window (end-exclusive).
        start = cert["location_start"]
        end = cert["location_end"]
        outer_start = prod["principal_photography_start"]
        outer_end = add_days(prod["principal_photography_end"], POST_PRODUCTION_EXTENSION_DAYS)
        if start < outer_start or end > outer_end:
            raise err("ERR_CERT_WINDOW_OUTSIDE_POLICY",
                      "Certificate window is outside the production coverage envelope")
        for line in cert["coverage_lines"]:
            bound = [
                p for p in db.policies.values()
                if p["production_id"] == id and p["coverage_line"] == line
                and p["status"] in ("BOUND", "ENDORSED_PENDING", "ACTIVE")
            ]
            win_start = max(p["effective_date"] for p in bound)
            win_end = min(p["expiry_date"] for p in bound)
            if start < win_start or end >= win_end:
                raise err("ERR_CERT_WINDOW_OUTSIDE_POLICY",
                          "Certificate window is outside the %s policy window" % line)

        if now() > end:
            raise err("ERR_WINDOW_ELAPSED",
                      "Certificate coverage window has already elapsed")

        seq = db.next_cert_seq(id)
        cert["certificate_number"] = "CERT-%s-%d" % (prod["production_code"], seq)
        cert["status"] = "ISSUED"
        touch(cert)
        touch_production_once(prod)  # issuance explicitly advances the production version
        return success_object(serialize(cert))


@bp.route("/productions/<id>/certificates/<childId>/void", methods=["POST"])
def void_certificate(id, childId):
    require_roles({"BrokerAgent"})
    with db.lock:
        get_production(id)
        cert = get_certificate(id, childId)
        if cert["status"] == "DRAFT":
            pass
        elif cert["status"] == "ISSUED":
            if not now() < cert["location_start"]:
                raise err("ERR_INVALID_STATE",
                          "Issued certificate cannot be voided after its window has started")
        else:
            raise err("ERR_INVALID_STATE",
                      "Certificate in %s cannot be voided" % cert["status"])
        cert["status"] = "VOIDED"
        touch(cert)
        return success_object(serialize(cert))

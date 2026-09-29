"""Component part certificates and the reliance decision (PRD 3.4)."""

from flask import Blueprint

import auth
import db
import paging
import refs
import response
import validation
from errors import ApiError
from routes.products import guard_not_archived
from services import calc, engine, gates

bp = Blueprint("partcerts", __name__)

RELIANCE_STATES = {"SUBMITTED", "RELIED_UPON", "REJECTED", "RELIANCE_VOID"}
RELIANCE_DECISIONS = {"RELY", "REJECT"}
CERT_READ_ROLES = (
    "ComplianceAdministrator",
    "TestCoordinator",
    "CertificationOfficer",
    "SupplierUser",
)


@bp.post("/component-parts/<part_id>/certificates")
def submit_certificate(part_id):
    auth.require_roles("SupplierUser")

    # Priority 4 needs the path entity; when it resolves, ownership is decided
    # before request shape, and when it does not, shape is decided first.
    early_part = db.get("component_parts", part_id)
    if early_part is not None:
        auth.require_part_owner(early_part)

    body = validation.json_body()
    laboratory_id = validation.id_field(body, "laboratory_id")
    rule_id = validation.id_field(body, "rule_id")
    measured_value = validation.number_field(body, "measured_value", minimum=0)
    coverage_from = validation.datetime_field(body, "coverage_from")
    coverage_through = validation.datetime_field(body, "coverage_through")

    part = refs.part(part_id)
    laboratory = refs.laboratory(laboratory_id)
    rule = refs.rule(rule_id)
    product = refs.product(part["product_id"])
    guard_not_archived(product)

    gates.require_not_barred(laboratory)
    gates.require_method_accreditation(laboratory, rule)
    if not coverage_through > coverage_from:
        raise ApiError("ERR_WINDOW_INVALID")
    if calc.coverage_collides(part["id"], rule["id"], coverage_from, coverage_through):
        raise ApiError("ERR_COMPONENT_COVERAGE_OVERLAP")

    row = db.insert(
        "component_part_certificates",
        {
            "component_part_id": part["id"],
            "supplier_id": part["supplier_id"],
            "laboratory_id": laboratory["id"],
            "rule_id": rule["id"],
            "measured_value": measured_value,
            "coverage_from": coverage_from,
            "coverage_through": coverage_through,
            "reliance_state": "SUBMITTED",
            "reliance_documentation_ref": None,
            "reliance_recorded_by_user_id": None,
        },
    )
    supplier = db.get("suppliers", part["supplier_id"])
    if supplier is not None:
        supplier["certificates_issued_count"] += 1
        engine.bump("suppliers", supplier)
    return response.object_response(
        db.serialize("component_part_certificates", row), 201
    )


@bp.get("/component-part-certificates/<part_certificate_id>")
def get_certificate(part_certificate_id):
    auth.require_roles(*CERT_READ_ROLES)
    row = refs.part_certificate(part_certificate_id)
    return response.object_response(db.serialize("component_part_certificates", row))


@bp.get("/component-part-certificates")
def list_certificates():
    auth.require_roles(*CERT_READ_ROLES)
    component_part_id = validation.query_string("component_part_id")
    supplier_id = validation.query_string("supplier_id")
    laboratory_id = validation.query_string("laboratory_id")
    rule_id = validation.query_string("rule_id")
    reliance_state = validation.query_enum("reliance_state", RELIANCE_STATES)
    return paging.build(
        "component_part_certificates",
        [
            paging.eq_filter("component_part_id", component_part_id),
            paging.eq_filter("supplier_id", supplier_id),
            paging.eq_filter("laboratory_id", laboratory_id),
            paging.eq_filter("rule_id", rule_id),
            paging.eq_filter("reliance_state", reliance_state),
        ],
    )


@bp.post("/component-part-certificates/<part_certificate_id>/reliance-documentation")
def record_reliance(part_certificate_id):
    auth.require_roles("CertificationOfficer")
    body = validation.json_body()
    decision = validation.enum_field(body, "reliance_decision", RELIANCE_DECISIONS)
    documentation_ref = validation.string_field(
        body, "reliance_documentation_ref", min_len=1, max_len=200
    )
    cert = refs.part_certificate(part_certificate_id)
    part = refs.part(cert["component_part_id"])
    product = refs.product(part["product_id"])
    guard_not_archived(product)

    if cert["reliance_state"] != "SUBMITTED":
        raise ApiError("ERR_PART_CERTIFICATE_STATE_INVALID")

    supplier = db.get("suppliers", cert["supplier_id"])
    rule = db.get("applicable_rules", cert["rule_id"])

    if decision == "RELY":
        if supplier is None or supplier["reliance_agreement_state"] != "ON_FILE":
            raise ApiError("ERR_RELIANCE_AGREEMENT_MISSING")
        if cert["rule_id"] not in product["required_rule_ids"]:
            raise ApiError("ERR_RULE_NOT_APPLICABLE_TO_PRODUCT")
        if rule is None or not rule["component_reliance_allowed"]:
            raise ApiError("ERR_COMPONENT_RELIANCE_NOT_ALLOWED")
        if product["evidence_path"] != "COMPONENT_RELIANCE":
            raise ApiError("ERR_EVIDENCE_PATH_MISMATCH")

    cert["reliance_documentation_ref"] = documentation_ref
    cert["reliance_recorded_by_user_id"] = auth.current_user_id()

    if decision == "RELY":
        cert["reliance_state"] = "RELIED_UPON"
        engine.bump("component_part_certificates", cert)
        engine.maybe_promote_part(part, product)
        engine.recompute_product_derived(product)
        if (
            product["risk_weighted_gap_score"] == 0
            and product["certification_state"] == "EVIDENCE_RELIANCE"
        ):
            product["certification_state"] = "EVIDENCE_COMPLETE"
            product["compliance_posture"] = "CLEARED"
        engine.bump("products", product)
    else:
        cert["reliance_state"] = "REJECTED"
        engine.bump("component_part_certificates", cert)
        if supplier is not None:
            supplier["certificates_issued_count"] -= 1
            engine.bump("suppliers", supplier)
    return response.object_response(db.serialize("component_part_certificates", cert))

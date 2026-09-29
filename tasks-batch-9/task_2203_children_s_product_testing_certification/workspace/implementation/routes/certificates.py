"""Children's product certificates: content, issuance, accompaniment (PRD 3.7)."""

from flask import Blueprint

import auth
import clock
import db
import paging
import refs
import response
import validation
from errors import ApiError
from routes.products import guard_not_archived
from services import calc, engine

bp = Blueprint("certificates", __name__)

ISSUANCE_STATUSES = {"DRAFT", "ISSUED", "SUPERSEDED", "WITHDRAWN", "VOIDED"}
ACCOMPANIMENT_STATUSES = {"NOT_FURNISHED", "FURNISHED", "RECALLED_FROM_SHIPMENTS"}
CERT_READ_ROLES = (
    "ComplianceAdministrator",
    "TestCoordinator",
    "CertificationOfficer",
    "DistributionManager",
)


def evidence_orders(product, cited_rule_ids):
    out = []
    for order in db.all_rows("test_orders"):
        if order["product_id"] != product["id"]:
            continue
        if order["order_state"] != "REPORTED_PASS":
            continue
        if order["rule_id"] not in cited_rule_ids:
            continue
        out.append(order)
    return out


def evidence_row_count(product, cited_rule_ids):
    count = len(evidence_orders(product, cited_rule_ids))
    part_ids = {p["id"] for p in db.find("component_parts", product_id=product["id"])}
    for cert in db.all_rows("component_part_certificates"):
        if cert["component_part_id"] not in part_ids:
            continue
        if cert["reliance_state"] != "RELIED_UPON":
            continue
        if cert["rule_id"] not in cited_rule_ids:
            continue
        count += 1
    return count


@bp.post("/products/<product_id>/certificates")
def draft_certificate(product_id):
    auth.require_roles("CertificationOfficer")
    body = validation.json_body()
    expected_product_version = validation.int_field(
        body, "expected_product_version", minimum=1
    )
    certifier_legal_name = validation.string_field(
        body, "certifier_legal_name", min_len=1, max_len=160
    )
    certifier_contact_email = validation.string_field(
        body, "certifier_contact_email", min_len=5, max_len=160
    )
    if "@" not in certifier_contact_email:
        raise ApiError(
            "ERR_INVALID_REQUEST", "certifier_contact_email: must contain an at-sign"
        )
    manufacture_place = validation.string_field(
        body, "manufacture_place", min_len=1, max_len=120
    )
    manufacture_date_month = validation.string_field(
        body, "manufacture_date_month", min_len=7, max_len=7,
        pattern=validation.RE_MONTH,
    )
    testing_place = validation.string_field(
        body, "testing_place", min_len=1, max_len=120
    )

    product = refs.product(product_id)
    guard_not_archived(product)
    if product["certification_state"] != "EVIDENCE_COMPLETE":
        raise ApiError("ERR_PRODUCT_STATE_INVALID")
    if expected_product_version != product["version"]:
        raise ApiError("ERR_STALE_PRODUCT_VERSION")

    predecessor = None
    for candidate in db.find("certificates", product_id=product["id"]):
        if candidate["issuance_status"] == "ISSUED":
            predecessor = candidate
            break
    cited_rule_ids = list(product["required_rule_ids"])
    draft = {
        "product_id": product["id"],
        "supersedes_certificate_id": predecessor["id"] if predecessor else None,
        "issuance_status": "DRAFT",
        "accompaniment_status": "NOT_FURNISHED",
        "certifier_legal_name": certifier_legal_name,
        "certifier_contact_email": certifier_contact_email,
        "manufacture_place": manufacture_place,
        "manufacture_date_month": manufacture_date_month,
        "testing_place": testing_place,
        "cited_rule_ids": cited_rule_ids,
        "cited_evidence_count": evidence_row_count(product, cited_rule_ids),
        "content_completeness_pct": 0,
        "issued_by_user_id": None,
        "issued_at": None,
        "expected_product_version_seen": expected_product_version,
    }
    draft["content_completeness_pct"] = calc.content_completeness_pct(draft, product)
    row = db.insert("certificates", draft)
    engine.bump("products", product)
    return response.object_response(db.serialize("certificates", row), 201)


@bp.get("/certificates/<certificate_id>")
def get_certificate(certificate_id):
    auth.require_roles(*CERT_READ_ROLES)
    row = refs.certificate(certificate_id)
    return response.object_response(db.serialize("certificates", row))


@bp.get("/certificates")
def list_certificates():
    auth.require_roles(*CERT_READ_ROLES)
    product_id = validation.query_string("product_id")
    supersedes_certificate_id = validation.query_string("supersedes_certificate_id")
    issuance_status = validation.query_enum("issuance_status", ISSUANCE_STATUSES)
    accompaniment_status = validation.query_enum(
        "accompaniment_status", ACCOMPANIMENT_STATUSES
    )
    return paging.build(
        "certificates",
        [
            paging.eq_filter("product_id", product_id),
            paging.eq_filter("supersedes_certificate_id", supersedes_certificate_id),
            paging.eq_filter("issuance_status", issuance_status),
            paging.eq_filter("accompaniment_status", accompaniment_status),
        ],
    )


@bp.post("/certificates/<certificate_id>/issue")
def issue_certificate(certificate_id):
    auth.require_roles("CertificationOfficer")
    cert = refs.certificate(certificate_id)
    product = refs.product(cert["product_id"])
    guard_not_archived(product)
    if product["certification_state"] != "EVIDENCE_COMPLETE":
        raise ApiError("ERR_PRODUCT_STATE_INVALID")
    if cert["issuance_status"] != "DRAFT":
        raise ApiError("ERR_CERTIFICATE_STATE_INVALID")

    cert["content_completeness_pct"] = calc.content_completeness_pct(cert, product)
    if cert["content_completeness_pct"] != 100:
        raise ApiError("ERR_CERTIFICATE_CONTENT_INCOMPLETE")
    if product["compliance_posture"] != "CLEARED":
        raise ApiError("ERR_PRODUCT_POSTURE_NOT_CLEARED")
    actor = auth.current_user_id()
    for order in evidence_orders(product, cert["cited_rule_ids"]):
        if order["ordered_by_user_id"] == actor:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    cert["issuance_status"] = "ISSUED"
    cert["issued_by_user_id"] = actor
    cert["issued_at"] = clock.now()
    engine.bump("certificates", cert)

    if cert["supersedes_certificate_id"] is not None:
        predecessor = db.get("certificates", cert["supersedes_certificate_id"])
        if predecessor is not None and predecessor["issuance_status"] == "ISSUED":
            predecessor["issuance_status"] = "SUPERSEDED"
            if predecessor["accompaniment_status"] == "FURNISHED":
                predecessor["accompaniment_status"] = "RECALLED_FROM_SHIPMENTS"
            engine.bump("certificates", predecessor)

    product["certification_state"] = "CERTIFIED"
    product["compliance_posture"] = "CLEARED"
    engine.bump("products", product)
    return response.object_response(db.serialize("certificates", cert))


@bp.post("/certificates/<certificate_id>/void")
def void_certificate(certificate_id):
    auth.require_roles("CertificationOfficer")
    cert = refs.certificate(certificate_id)
    product = refs.product(cert["product_id"])
    guard_not_archived(product)
    if cert["issuance_status"] != "DRAFT":
        raise ApiError("ERR_CERTIFICATE_STATE_INVALID")
    cert["issuance_status"] = "VOIDED"
    engine.bump("certificates", cert)
    return response.object_response(db.serialize("certificates", cert))


@bp.post("/certificates/<certificate_id>/furnish")
def furnish_certificate(certificate_id):
    auth.require_roles("DistributionManager")
    cert = refs.certificate(certificate_id)
    product = refs.product(cert["product_id"])
    guard_not_archived(product)
    if cert["issuance_status"] != "ISSUED":
        raise ApiError("ERR_CERTIFICATE_STATE_INVALID")
    if cert["accompaniment_status"] != "NOT_FURNISHED":
        raise ApiError("ERR_CERTIFICATE_STATE_INVALID")
    cert["accompaniment_status"] = "FURNISHED"
    engine.bump("certificates", cert)
    return response.object_response(db.serialize("certificates", cert))


@bp.post("/certificates/<certificate_id>/recall-accompaniment")
def recall_accompaniment(certificate_id):
    auth.require_roles("DistributionManager")
    cert = refs.certificate(certificate_id)
    product = refs.product(cert["product_id"])
    guard_not_archived(product)
    if cert["accompaniment_status"] != "FURNISHED":
        raise ApiError("ERR_CERTIFICATE_STATE_INVALID")
    cert["accompaniment_status"] = "RECALLED_FROM_SHIPMENTS"
    engine.bump("certificates", cert)
    return response.object_response(db.serialize("certificates", cert))

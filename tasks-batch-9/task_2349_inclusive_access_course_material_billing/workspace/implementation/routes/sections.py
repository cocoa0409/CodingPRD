"""CourseSection endpoints: creation, flagging, reads and batch charge posting."""

from flask import Blueprint

from auth import (ROLE_BURSAR, ROLE_COMPLIANCE, ROLE_FACULTY, ROLE_PROGRAM_ADMIN,
                  ROLE_REGISTRAR, authenticate)
from domain import (adoption_json, adoptions_of_section, agreement_of_adoption,
                    approved_adoptions, census_basis, charge_json,
                    charge_net, charge_publisher_share, charges_of_section,
                    current_approved_adoption, enrollment_json,
                    enrollments_of_section, freeze_billing_basis, get_section,
                    get_term, gross_price, post_charge, recompute_section,
                    section_json, section_participation_rate,
                    section_provisioned_count, section_revoked_count,
                    tier_basis, title_of_adoption, uncharged_enrollments)
from errors import fail
from response import apply_filters, array_response, object_response, paginate
from store import base_record, db, in_order, touch
from validate import f_int, f_str, get_body

bp = Blueprint("sections", __name__)

SECTION_READ_ROLES = (ROLE_PROGRAM_ADMIN, ROLE_FACULTY, ROLE_REGISTRAR, ROLE_BURSAR,
                      ROLE_COMPLIANCE)

POST_CHARGES_EVENT = "POST /sections/{section_id}/post-charges"


@bp.post("/sections")
def create_section():
    authenticate(ROLE_REGISTRAR, ROLE_PROGRAM_ADMIN)
    body = get_body(("term_id", "subject_code", "catalog_number", "section_number",
                     "instructor_user_id", "max_concurrent_titles"))
    term_id = f_str(body, "term_id")
    subject_code = f_str(body, "subject_code")
    catalog_number = f_str(body, "catalog_number")
    section_number = f_str(body, "section_number")
    instructor_user_id = f_str(body, "instructor_user_id")
    max_concurrent_titles = f_int(body, "max_concurrent_titles", required=False,
                                  default=2, minimum=1)

    term = get_term(term_id)
    for existing in db.sections.values():
        if (existing["term_id"] == term["id"]
                and existing["subject_code"] == subject_code
                and existing["catalog_number"] == catalog_number
                and existing["section_number"] == section_number):
            fail("ERR_DUPLICATE_RESOURCE_KEY")

    section = base_record()
    section.update({
        "term_id": term["id"],
        "subject_code": subject_code,
        "catalog_number": catalog_number,
        "section_number": section_number,
        "instructor_user_id": instructor_user_id,
        "max_concurrent_titles": max_concurrent_titles,
        "inclusive_access_flag": False,
        "ia_status": "NOT_FLAGGED",
        "billing_basis_enrollment_count": None,
        "first_posted_at": None,
    })
    db.sections[section["id"]] = section
    return object_response(section_json(section), 201)


@bp.get("/sections/<section_id>")
def read_section(section_id):
    authenticate(*SECTION_READ_ROLES)
    return object_response(section_json(get_section(section_id)))


@bp.get("/sections")
def list_sections():
    authenticate(*SECTION_READ_ROLES)
    items = apply_filters(in_order(db.sections.values()), [
        ("term_id", "term_id"),
        ("ia_status", "ia_status"),
        ("instructor_user_id", "instructor_user_id"),
    ])
    return paginate(items, section_json)


@bp.post("/sections/<section_id>/flag-inclusive-access")
def flag_section(section_id):
    authenticate(ROLE_PROGRAM_ADMIN)
    get_body(())
    section = get_section(section_id)
    term = get_term(section["term_id"])

    if section["ia_status"] != "NOT_FLAGGED":
        fail("ERR_INVALID_STATE")
    if term["status"] != "OPEN":
        fail("ERR_TERM_NOT_OPEN")

    approved = approved_adoptions(section["id"])
    if not approved:
        fail("ERR_ADOPTION_NOT_APPROVED")
    for adoption in approved:
        if agreement_of_adoption(adoption)["status"] != "ACTIVE":
            fail("ERR_AGREEMENT_NOT_ACTIVE")
    for adoption in approved:
        if title_of_adoption(adoption)["status"] != "ACTIVE":
            fail("ERR_TITLE_WITHDRAWN")

    section["inclusive_access_flag"] = True
    section["ia_status"] = "FLAGGED"
    touch(section)
    touch(term)
    return object_response(section_json(section))


@bp.get("/sections/<section_id>/adoptions")
def list_section_adoptions(section_id):
    authenticate(*SECTION_READ_ROLES)
    section = get_section(section_id)
    items = apply_filters(adoptions_of_section(section["id"]), [("status", "status")])
    return paginate(items, adoption_json)


@bp.get("/sections/<section_id>/enrollments")
def list_section_enrollments(section_id):
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_FACULTY, ROLE_REGISTRAR, ROLE_BURSAR)
    section = get_section(section_id)
    items = apply_filters(enrollments_of_section(section["id"]), [
        ("status", "status"),
        ("registration_type", "registration_type"),
    ])
    return paginate(items, enrollment_json)


@bp.get("/sections/<section_id>/billing-summary")
def billing_summary(section_id):
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_BURSAR, ROLE_COMPLIANCE)
    section = get_section(section_id)
    term = get_term(section["term_id"])
    adoption = current_approved_adoption(section["id"])

    posting_basis = tier_basis(section)
    census_count = census_basis(section, term)

    gross_posting = None
    gross_census = None
    if adoption is not None:
        gross_posting = gross_price(adoption, posting_basis, strict=False)
        gross_census = gross_price(adoption, census_count, strict=False)

    charges = charges_of_section(section["id"])
    data = {
        "section_id": section["id"],
        "ia_status": section["ia_status"],
        "billing_basis_enrollment_count": section["billing_basis_enrollment_count"],
        "tier_basis_posting_count": posting_basis,
        "tier_basis_census_count": census_count,
        "gross_per_student_posting_cents": gross_posting,
        "gross_per_student_census_cents": gross_census,
        "charge_count": len(charges),
        "posted_charge_count": sum(1 for c in charges if c["billing_status"] == "POSTED"),
        "refunded_charge_count": sum(1 for c in charges
                                     if c["billing_status"] == "REFUNDED"),
        "total_net_billed_cents": sum(charge_net(c) for c in charges),
        "total_publisher_share_cents": sum(charge_publisher_share(c) for c in charges),
        "provisioned_access_count": section_provisioned_count(section["id"]),
        "revoked_access_count": section_revoked_count(section["id"]),
        "participation_rate": float(section_participation_rate(section["id"])),
    }
    return object_response(data)


@bp.post("/sections/<section_id>/post-charges")
def post_charges(section_id):
    authenticate(ROLE_BURSAR, ROLE_PROGRAM_ADMIN)
    get_body(())
    section = get_section(section_id)
    term = get_term(section["term_id"])

    if term["status"] != "OPEN":
        fail("ERR_TERM_BILLING_LOCKED")
    if section["ia_status"] not in ("FLAGGED", "BILLED"):
        fail("ERR_SECTION_NOT_FLAGGED")

    adoption = current_approved_adoption(section["id"])
    if adoption is None:
        fail("ERR_ADOPTION_NOT_APPROVED")
    if agreement_of_adoption(adoption)["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE")

    pending = uncharged_enrollments(section, adoption)
    if not pending:
        fail("ERR_NO_BILLABLE_CHARGES")

    basis = tier_basis(section)
    # Resolve the band once, before any row is written, so a missing band cannot
    # leave the batch half posted.
    gross_price(adoption, basis)

    created = []
    for enrollment in pending:
        created.append(post_charge(section, term, enrollment, adoption, basis,
                                   POST_CHARGES_EVENT))
    freeze_billing_basis(section, term, basis)
    recompute_section(section)
    return array_response([charge_json(c) for c in created], status=201)

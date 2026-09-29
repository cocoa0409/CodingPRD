"""DesignRevision endpoints (PRD 3.2)."""

from flask import Blueprint, g

import calc
import lookup
import response
import serialize
import store
import validate
from auth import authorize
from errors import fail
from routes._common import paged
from store import db, mark_dirty, now

bp = Blueprint("design_revisions", __name__)

READERS = (
    "DesignEngineer",
    "DesignApprover",
    "TestLabTechnician",
    "ProductionSupervisor",
    "ComplianceOfficer",
    "SafetyDirector",
)


@bp.post("/design-revisions")
@authorize("DesignEngineer")
def create_design_revision():
    data = validate.body()

    # step 4 — foreign keys in declared input order
    product = None
    if validate.present(data, "product_id"):
        product = lookup.product(data["product_id"])
    supersedes = None
    if validate.present(data, "supersedes_revision_id"):
        supersedes = lookup.design_revision(data["supersedes_revision_id"])

    # step 6 — shape
    validate.req_id(data, "product_id")
    revision_label = validate.req_str(data, "revision_label")
    joint_type = validate.req_enum(data, "joint_type", calc.JOINT_TYPES)
    structural_margin_pct = validate.req_number(data, "structural_margin_pct", minimum=0)
    rail_section_modulus_in3 = validate.req_number(
        data, "rail_section_modulus_in3", minimum=0, exclusive_min=True
    )
    expected_product_version = validate.req_int(data, "expected_product_version")

    # step 10 — optimistic concurrency on the parent product
    if expected_product_version != product["version"]:
        fail(
            "ERR_STALE_PRODUCT_VERSION",
            "expected_product_version %s does not match current version %s"
            % (expected_product_version, product["version"]),
        )

    # step 35 — supersede target must sit on the same product
    if supersedes is not None and supersedes["product_id"] != product["id"]:
        fail("ERR_SUPERSEDE_TARGET_MISMATCH", "superseded revision belongs to another product")

    # step 57 — revision_label unique per product
    for existing in lookup.revisions_of_product(product["id"]):
        if existing["revision_label"] == revision_label:
            fail("ERR_DUPLICATE_KEY", "revision_label already exists on this product")

    revision = store.base_record()
    revision.update(
        {
            "product_id": product["id"],
            "revision_label": revision_label,
            "joint_type": joint_type,
            "structural_margin_pct": structural_margin_pct,
            "rail_section_modulus_in3": rail_section_modulus_in3,
            "supersedes_revision_id": supersedes["id"] if supersedes is not None else None,
            "status": "DRAFT",
            "review_round": 1,
            "submitted_by_user_id": None,
            "reviewed_by_user_id": None,
            "reviewer_notes": None,
            "superseded_at": None,
        }
    )
    db.design_revisions[revision["id"]] = revision
    store.register_new(revision)
    mark_dirty(product)
    return response.created(revision, serialize.design_revision)


@bp.get("/design-revisions/<revision_id>")
@authorize(*READERS)
def get_design_revision(revision_id):
    revision = lookup.design_revision(revision_id)
    return response.obj(revision, serialize.design_revision)


@bp.get("/design-revisions")
@authorize(*READERS)
def list_design_revisions():
    spec = {
        "product_id": "product_id",
        "supersedes_revision_id": "supersedes_revision_id",
        "status": "status",
        "joint_type": "joint_type",
    }
    return paged(lookup.rows(db.design_revisions), spec, serialize.design_revision)


@bp.post("/design-revisions/<revision_id>/submit")
@authorize("DesignEngineer")
def submit_design_revision(revision_id):
    revision = lookup.design_revision(revision_id)

    if revision["status"] != "DRAFT":
        fail("ERR_REVISION_STATE_INVALID", "status must be DRAFT to submit")
    if revision["structural_margin_pct"] < calc.MIN_STRUCTURAL_MARGIN_PCT:
        fail(
            "ERR_DESIGN_MARGIN_INSUFFICIENT",
            "structural_margin_pct must be at least %s" % calc.MIN_STRUCTURAL_MARGIN_PCT,
        )

    revision["status"] = "UNDER_REVIEW"
    revision["submitted_by_user_id"] = g.user_id
    mark_dirty(revision)
    return response.obj(revision, serialize.design_revision)


@bp.post("/design-revisions/<revision_id>/review")
@authorize("DesignApprover")
def review_design_revision(revision_id):
    revision = lookup.design_revision(revision_id)
    data = validate.body()
    decision = validate.req_enum(data, "decision", calc.REVIEW_DECISIONS)
    reviewer_notes = validate.opt_str(data, "reviewer_notes")

    if revision["status"] != "UNDER_REVIEW":
        fail("ERR_REVISION_STATE_INVALID", "status must be UNDER_REVIEW to review")
    if revision["submitted_by_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", "a submitter may not review their own revision")
    if decision == "APPROVE" and revision["rail_section_modulus_in3"] < calc.MIN_SECTION_MODULUS_IN3:
        fail(
            "ERR_DESIGN_MARGIN_INSUFFICIENT",
            "rail_section_modulus_in3 must be at least %s" % calc.MIN_SECTION_MODULUS_IN3,
        )

    revision["reviewed_by_user_id"] = g.user_id
    revision["reviewer_notes"] = reviewer_notes
    if decision == "APPROVE":
        revision["status"] = "APPROVED"
        target_id = revision["supersedes_revision_id"]
        if target_id:
            target = db.design_revisions.get(target_id)
            if target is not None and target["status"] == "APPROVED":
                target["status"] = "SUPERSEDED"
                target["superseded_at"] = now()
                mark_dirty(target)
    else:
        revision["status"] = "CHANGES_REQUESTED"
    mark_dirty(revision)
    return response.obj(revision, serialize.design_revision)


@bp.post("/design-revisions/<revision_id>/revise")
@authorize("DesignEngineer")
def revise_design_revision(revision_id):
    revision = lookup.design_revision(revision_id)
    data = validate.body()
    structural_margin_pct = validate.opt_number(data, "structural_margin_pct", minimum=0)
    rail_section_modulus_in3 = validate.opt_number(
        data, "rail_section_modulus_in3", minimum=0, exclusive_min=True
    )
    joint_type = validate.opt_enum(data, "joint_type", calc.JOINT_TYPES)

    if revision["status"] != "CHANGES_REQUESTED":
        fail("ERR_REVISION_STATE_INVALID", "status must be CHANGES_REQUESTED to revise")

    if structural_margin_pct is not None:
        revision["structural_margin_pct"] = structural_margin_pct
    if rail_section_modulus_in3 is not None:
        revision["rail_section_modulus_in3"] = rail_section_modulus_in3
    if joint_type is not None:
        revision["joint_type"] = joint_type
    revision["status"] = "DRAFT"
    revision["review_round"] = revision["review_round"] + 1
    revision["submitted_by_user_id"] = None
    mark_dirty(revision)
    return response.obj(revision, serialize.design_revision)

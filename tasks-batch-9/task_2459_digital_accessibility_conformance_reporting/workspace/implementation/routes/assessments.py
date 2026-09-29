"""Per-criterion assessments: authoring, superseding, attestation (PRD 3.5)."""
from datetime import timedelta

from flask import Blueprint, g

from db import clock_now, db, new_row, now_iso, sort_key, touch
from calc import EVIDENCE_MAX_AGE_DAYS
from derive import recompute_product
from errors import ApiError, bad_request
from middleware import ALL_ROLES, endpoint
from response import list_response, obj_response
from serialize import assessment_out
from validate import (
    ATTESTATION_STATES,
    SUPPORT_LEVELS,
    body,
    fk_component,
    fk_criterion,
    fk_run,
    pagination,
    paginate,
    path_assessment,
    q_enum,
    q_str,
    v_enum,
    v_int,
    v_str,
)

bp = Blueprint("assessments", __name__)


@bp.post("/criterion-assessments")
@endpoint(["AccessibilityTester"])
def create_assessment():
    data = body()
    component = fk_component(data.get("component_id"))     # step 5
    criterion = fk_criterion(data.get("criterion_id"))     # step 5
    evidence_run = None
    if data.get("evidence_run_id") is not None:
        evidence_run = fk_run(data.get("evidence_run_id"))

    v_str(data, "component_id", required=True, min_len=1)
    v_str(data, "criterion_id", required=True, min_len=1)
    support_level = v_enum(data, "support_level", SUPPORT_LEVELS, required=True)
    remarks = data.get("remarks")
    if remarks is not None:
        if not isinstance(remarks, str):
            raise bad_request("'remarks' must be a string")
        if len(remarks) > 2000:
            raise bad_request("'remarks' must be at most 2000 characters")
        if support_level == "SUPPORTS" and len(remarks) < 10:
            raise bad_request("'remarks' must be at least 10 characters")
    if data.get("evidence_run_id") is not None:
        v_str(data, "evidence_run_id", required=True, min_len=1)
    expected = v_int(data, "expected_component_version", required=True, min_value=0)

    # step 7: optimistic concurrency on the parent component
    if expected != component["version"]:
        raise ApiError("ERR_STALE_COMPONENT_VERSION",
                       "Component %s is at version %d, not %d"
                       % (component["id"], component["version"], expected))

    # step 21: remarks are mandatory for anything other than SUPPORTS
    if support_level != "SUPPORTS" and (remarks is None or len(remarks) < 10):
        raise ApiError("ERR_REMARKS_REQUIRED",
                       "Support level %s requires remarks of at least 10 characters"
                       % support_level)

    # step 33: the criterion must belong to the product's selected standard
    product = db.products[component["product_id"]]
    if criterion["standard_id"] != product["standard_id"]:
        raise ApiError("ERR_CRITERION_STANDARD_MISMATCH",
                       "Criterion %s does not belong to standard %s"
                       % (criterion["id"], product["standard_id"]))

    row = new_row({
        "component_id": component["id"],
        "criterion_id": criterion["id"],
        "support_level": support_level,
        "remarks": remarks,
        "evidence_run_id": evidence_run["id"] if evidence_run else None,
        "attestation_state": "DRAFT",
        "authored_by_user_id": g.user_id,
        "attested_by_user_id": None,
        "attested_at": None,
        "attestation_note": None,
        "superseded_by_assessment_id": None,
    })

    # supersede the history of this (component, criterion) pair
    for existing in list(db.assessments.values()):
        if (existing["component_id"] == component["id"]
                and existing["criterion_id"] == criterion["id"]
                and existing["attestation_state"] in
                ("DRAFT", "ATTESTED", "NEEDS_REVALIDATION")):
            existing["attestation_state"] = "SUPERSEDED"
            existing["superseded_by_assessment_id"] = row["id"]
            touch(existing)

    db.assessments[row["id"]] = row

    touch(component)
    recompute_product(product)
    touch(product)
    return obj_response(assessment_out(row), 201)


@bp.get("/criterion-assessments/<assessment_id>")
@endpoint(ALL_ROLES)
def get_assessment(assessment_id):
    return obj_response(assessment_out(path_assessment(assessment_id)))


@bp.get("/criterion-assessments")
@endpoint(ALL_ROLES)
def list_assessments():
    component_id = q_str("component_id")
    criterion_id = q_str("criterion_id")
    evidence_run_id = q_str("evidence_run_id")
    superseded_by = q_str("superseded_by_assessment_id")
    state = q_enum("attestation_state", ATTESTATION_STATES)
    limit, offset = pagination()
    rows = list(db.assessments.values())
    if component_id is not None:
        rows = [r for r in rows if r["component_id"] == component_id]
    if criterion_id is not None:
        rows = [r for r in rows if r["criterion_id"] == criterion_id]
    if evidence_run_id is not None:
        rows = [r for r in rows if r["evidence_run_id"] == evidence_run_id]
    if superseded_by is not None:
        rows = [r for r in rows if r["superseded_by_assessment_id"] == superseded_by]
    if state is not None:
        rows = [r for r in rows if r["attestation_state"] == state]
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return list_response([assessment_out(r) for r in page], limit, offset, total)


@bp.post("/criterion-assessments/<assessment_id>/attest")
@endpoint(["ConformanceReviewer"])
def attest_assessment(assessment_id):
    assessment = path_assessment(assessment_id)
    data = body()
    note = v_str(data, "attestation_note", required=True, min_len=1, max_len=2000)

    component = db.components[assessment["component_id"]]
    product = db.products[component["product_id"]]

    # step 9: from-state
    if assessment["attestation_state"] != "DRAFT":
        raise ApiError("ERR_ASSESSMENT_NOT_DRAFT",
                       "Criterion assessment %s is %s"
                       % (assessment["id"], assessment["attestation_state"]))
    # step 15: posture gate (before segregation of duties)
    if product["publication_posture"] == "FROZEN":
        raise ApiError("ERR_PRODUCT_POSTURE_FROZEN",
                       "Product %s is FROZEN" % product["id"])
    # step 16: segregation of duties
    if g.user_id == assessment["authored_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "User %s may not both author and sign off on criterion "
                       "assessment %s" % (g.user_id, assessment["id"]))
    # step 19: the component's testing dimension must be COMPLETE
    if component["assessment_state"] != "COMPLETE":
        raise ApiError("ERR_COMPONENT_ASSESSMENT_INCOMPLETE",
                       "Component %s is %s"
                       % (component["id"], component["assessment_state"]))
    # step 23: evidence freshness (exactly 90 days is still accepted)
    deadline = assessment["_created_dt"] + timedelta(days=EVIDENCE_MAX_AGE_DAYS)
    if clock_now() > deadline:
        raise ApiError("ERR_ASSESSMENT_EVIDENCE_EXPIRED",
                       "Criterion assessment %s is older than %d days"
                       % (assessment["id"], EVIDENCE_MAX_AGE_DAYS))

    assessment["attestation_state"] = "ATTESTED"
    assessment["attested_at"] = now_iso()
    assessment["attested_by_user_id"] = g.user_id
    assessment["attestation_note"] = note
    touch(assessment)

    recompute_product(product)
    touch(product)
    return obj_response(assessment_out(assessment))

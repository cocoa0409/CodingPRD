"""Evidence packages: assembly, seal cascade, examiner submission (PRD §3.8)."""

from flask import Blueprint, request

from db import new_id, now_clock, stamp_new, store, touch
from errors import (ApiError, ERR_NO_ARTIFACTS, ERR_PACKAGE_ALREADY_EXISTS,
                    ERR_PACKAGE_SEALED, ERR_PLAN_NOT_COMPLETED, not_found,
                    not_resource_owner)
from middleware import auth_context, get_body, get_or_404, req_str, require_roles
from response import paginate, success_object
from serializers import created_sorted, package_to_api
from services.audit import append_audit
from services.cascades import reevaluate_change_closure

bp = Blueprint("evidence_packages", __name__)


@bp.post("/compliance/evidence-packages")
def create_package():
    user_id, role = auth_context()
    require_roles(role, ("BusinessOwner",))
    body = get_body()
    plan_id = req_str(body, "implementation_plan_id")

    plan = get_or_404(store.plans, plan_id, "implementation plan")
    # Ownership enforced through the plan.
    if plan["business_owner_id"] != user_id:
        raise not_resource_owner()
    # Priority 4: plan must be COMPLETED.
    if plan["execution_status"] != "COMPLETED":
        raise ApiError(ERR_PLAN_NOT_COMPLETED, 409,
                       "Evidence package creation attempted for a plan not in "
                       "COMPLETED")
    # Priority 7: at most one package per plan.
    if any(p["implementation_plan_id"] == plan["id"]
           for p in store.packages.values()):
        raise ApiError(ERR_PACKAGE_ALREADY_EXISTS, 409,
                       "An evidence package already exists for the "
                       "implementation plan")

    package = stamp_new({
        "id": new_id(),
        "implementation_plan_id": plan["id"],
        "artifacts": [],
        "status": "ASSEMBLING",
        "sealed_at": None,
        "examiner_reference": None,
    })
    store.packages[package["id"]] = package
    append_audit(user_id, role, "POST /compliance/evidence-packages",
                 "EvidencePackage", package["id"])
    return success_object(package_to_api(package), status=201)


@bp.get("/compliance/evidence-packages")
def list_packages():
    auth_context()
    items = created_sorted(store.packages.values())
    for param in ("implementation_plan_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [p for p in items if p[param] == value]
    return paginate(items, package_to_api)


@bp.get("/compliance/evidence-packages/<package_id>")
def get_package(package_id):
    auth_context()
    package = get_or_404(store.packages, package_id, "evidence package")
    return success_object(package_to_api(package))


def _owned_package(package_id, user_id):
    package = get_or_404(store.packages, package_id, "evidence package")
    plan = store.plans.get(package["implementation_plan_id"])
    if plan is None or plan["business_owner_id"] != user_id:
        raise not_resource_owner()
    return package


@bp.post("/compliance/evidence-packages/<package_id>/artifacts")
def attach_artifact(package_id):
    user_id, role = auth_context()
    require_roles(role, ("BusinessOwner",))
    body = get_body()
    artifact_type = req_str(body, "artifact_type")
    uri = req_str(body, "uri")

    package = _owned_package(package_id, user_id)
    if package["status"] != "ASSEMBLING":
        raise ApiError(ERR_PACKAGE_SEALED, 409,
                       "Artifact attach attempted on a package no longer "
                       "ASSEMBLING")
    package["artifacts"].append({
        "artifact_id": new_id(),
        "artifact_type": artifact_type,
        "uri": uri,
        "attached_at": now_clock(),
    })
    touch(package)
    append_audit(user_id, role,
                 "POST /compliance/evidence-packages/{id}/artifacts",
                 "EvidencePackage", package["id"])
    return success_object(package_to_api(package), status=201)


@bp.delete("/compliance/evidence-packages/<package_id>/artifacts/<artifact_id>")
def remove_artifact(package_id, artifact_id):
    user_id, role = auth_context()
    require_roles(role, ("BusinessOwner",))
    # Path ids validated left-to-right: package first, then the artifact.
    package = _owned_package(package_id, user_id)
    index = next((i for i, a in enumerate(package["artifacts"])
                  if a["artifact_id"] == artifact_id), None)
    if index is None:
        raise not_found("artifact")
    if package["status"] != "ASSEMBLING":
        raise ApiError(ERR_PACKAGE_SEALED, 409,
                       "Artifact removal attempted on a package no longer "
                       "ASSEMBLING")
    package["artifacts"].pop(index)
    touch(package)
    append_audit(user_id, role,
                 "DELETE /compliance/evidence-packages/{id}/artifacts/{artifactId}",
                 "EvidencePackage", package["id"])
    return success_object(package_to_api(package))


@bp.post("/compliance/evidence-packages/<package_id>/seal")
def seal_package(package_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceManager",))
    package = get_or_404(store.packages, package_id, "evidence package")
    if package["status"] != "ASSEMBLING":
        raise ApiError(ERR_PACKAGE_SEALED, 409,
                       "Seal attempted on a package no longer ASSEMBLING")
    if len(package["artifacts"]) < 1:
        raise ApiError(ERR_NO_ARTIFACTS, 422,
                       "Seal attempted with artifact_count == 0")

    package["status"] = "SEALED"
    package["sealed_at"] = now_clock()
    touch(package)

    # Cascade link 1: the plan behind the package COMPLETED -> VERIFIED.
    plan = store.plans.get(package["implementation_plan_id"])
    if plan is not None and plan["execution_status"] == "COMPLETED":
        plan["execution_status"] = "VERIFIED"
        plan["verification_evidence_id"] = package["id"]
        touch(plan)
        # Cascade link 2: bubble-up closure check on the regulatory change.
        reevaluate_change_closure(plan["regulatory_change_id"])

    append_audit(user_id, role, "POST /compliance/evidence-packages/{id}/seal",
                 "EvidencePackage", package["id"])
    return success_object(package_to_api(package))


@bp.post("/compliance/evidence-packages/<package_id>/submit-to-examiner")
def submit_to_examiner(package_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceManager",))
    body = get_body()
    examiner_reference = req_str(body, "examiner_reference")
    package = get_or_404(store.packages, package_id, "evidence package")
    if package["status"] != "SEALED":
        raise invalid_state_submit()
    package["status"] = "SUBMITTED_TO_EXAMINER"
    package["examiner_reference"] = examiner_reference
    touch(package)
    append_audit(user_id, role,
                 "POST /compliance/evidence-packages/{id}/submit-to-examiner",
                 "EvidencePackage", package["id"])
    return success_object(package_to_api(package))


def invalid_state_submit():
    from errors import invalid_state
    return invalid_state("submit-to-examiner requires status SEALED")

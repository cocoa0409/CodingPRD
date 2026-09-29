"""Plans of services and service commitments (PRD §3.5)."""

from flask import Blueprint

import validate as v
from auth import ANY_ROLE, check_municipality_scope, prelude
from db import base_record, db, touch
from errors import ApiError
from response import object_response, paginate
from services import calc, domain

bp = Blueprint("plans", __name__)

SERVICE_TYPES = ("POLICE", "FIRE", "WATER", "SEWER")


def _plan_for_write(plan_id, roles):
    user_id, role = prelude(roles)
    soft_plan = domain.soft("plans", plan_id)
    check_municipality_scope(
        role, user_id, domain.municipality_id_of_case(domain.case_of_plan(soft_plan))
    )
    plan = domain.path_record("plans", plan_id)
    return plan, user_id, role


def _commitment_for_write(commitment_id, roles):
    user_id, role = prelude(roles)
    soft_commitment = domain.soft("commitments", commitment_id)
    check_municipality_scope(
        role,
        user_id,
        domain.municipality_id_of_case(domain.case_of_commitment(soft_commitment)),
    )
    commitment = domain.path_record("commitments", commitment_id)
    return commitment, user_id, role


# ---------------------------------------------------------------------------
# Plans of services
# ---------------------------------------------------------------------------

@bp.post("/plans-of-services")
def create_plan():
    user_id, role = prelude(("MunicipalPlanner",))
    body = v.get_body()

    soft_case = domain.soft("cases", body.get("annexation_case_id"))
    check_municipality_scope(role, user_id, domain.municipality_id_of_case(soft_case))

    case_id = v.id_field(body, "annexation_case_id")
    case = domain.body_ref("cases", case_id)
    domain.assert_case_not_terminal(case)

    record = base_record()
    record.update(
        {
            "annexation_case_id": case["id"],
            "adoption_status": "DRAFT",
            "service_readiness": "PENDING",
            "adopted_at": None,
            "committed_cost_cents": 0,
            "covered_service_types": [],
        }
    )
    db.plans[record["id"]] = record
    return object_response(record, 201)


@bp.get("/plans-of-services/<plan_id>")
def read_plan(plan_id):
    prelude(ANY_ROLE)
    return object_response(domain.path_record("plans", plan_id))


@bp.get("/plans-of-services")
def list_plans():
    prelude(ANY_ROLE)
    return paginate(domain.rows("plans"), ("annexation_case_id", "adoption_status"))


@bp.post("/plans-of-services/<plan_id>/adopt")
def adopt_plan(plan_id):
    plan, _user_id, _role = _plan_for_write(plan_id, ("CityClerk",))
    case = domain.case_of_plan(plan)
    domain.assert_case_not_terminal(case)
    statute = domain.statute_of_case(case)

    if case is None or case["status"] not in (
        "TERRITORY_CERTIFIED",
        "PETITION_CIRCULATING",
        "SUFFICIENCY_REVIEW",
        "HEARING_NOTICED",
        "HEARING_HELD",
    ):
        raise ApiError(
            "ERR_CASE_STATE_INVALID",
            "The case is not in a state where a plan of services may be adopted.",
        )

    if plan["adoption_status"] != "DRAFT":
        raise ApiError("ERR_PLAN_ALREADY_ADOPTED", "The plan is no longer a DRAFT.")
    for other in domain.rows("plans"):
        if (
            other["id"] != plan["id"]
            and other["annexation_case_id"] == plan["annexation_case_id"]
            and other["adoption_status"] == "ADOPTED"
        ):
            raise ApiError(
                "ERR_PLAN_ALREADY_ADOPTED", "The case already has an ADOPTED plan of services."
            )

    covered = plan["covered_service_types"]
    for required in statute["required_service_types"]:
        if required not in covered:
            raise ApiError(
                "ERR_SERVICE_TYPE_NOT_COVERED",
                "The plan does not cover the statutorily required service %s." % required,
            )

    for commitment in domain.plan_commitments(plan):
        if commitment["commitment_status"] not in ("ACTIVE", "FULFILLED"):
            continue
        ceiling = domain.timeline_ceiling(statute, commitment["service_type"])
        if int(commitment["timeline_days"]) > ceiling:
            raise ApiError(
                "ERR_PLAN_SERVICE_TIMELINE_EXCEEDS_STATUTE",
                "A committed %s window exceeds the statutory maximum of %d days."
                % (commitment["service_type"], ceiling),
            )

    plan["adoption_status"] = "ADOPTED"
    plan["adopted_at"] = db.now()
    touch(plan)
    return object_response(plan)


# ---------------------------------------------------------------------------
# Service commitments
# ---------------------------------------------------------------------------

@bp.post("/service-commitments")
def create_commitment():
    user_id, role = prelude(("MunicipalPlanner",))
    body = v.get_body()

    soft_plan = domain.soft("plans", body.get("plan_of_services_id"))
    check_municipality_scope(
        role, user_id, domain.municipality_id_of_case(domain.case_of_plan(soft_plan))
    )

    plan_id = v.id_field(body, "plan_of_services_id")
    plan = domain.body_ref("plans", plan_id)
    provider_id = v.id_field(body, "service_provider_id")
    provider = domain.body_ref("service_providers", provider_id)

    service_type = v.enum_field(body, "service_type", SERVICE_TYPES)
    window_start = v.date_field(body, "window_start_date")
    window_end = v.date_field(body, "window_end_date")
    cost_cents = v.int_field(body, "cost_cents", minimum=0)
    expected_plan_version = v.int_field(body, "expected_plan_of_services_version", minimum=0)
    committed_account_count = v.int_field(
        body, "committed_account_count", required=False, default=0, minimum=0
    )
    if window_end < window_start:
        v.bad("window_end_date may not precede window_start_date.")

    if expected_plan_version != int(plan["version"]):
        raise ApiError(
            "ERR_STALE_PLAN_VERSION",
            "expected_plan_of_services_version does not match the plan's current version.",
        )

    case = domain.case_of_plan(plan)
    domain.assert_case_not_terminal(case)

    if service_type not in provider["service_types"]:
        raise ApiError(
            "ERR_PROVIDER_SERVICE_TYPE_MISMATCH",
            "The provider does not deliver %s service." % service_type,
        )
    if case is None or provider["municipality_id"] != case["municipality_id"]:
        raise ApiError(
            "ERR_PARCEL_CASE_MISMATCH",
            "The service provider belongs to another municipality.",
        )

    # A new commitment supersedes the plan's existing DRAFT commitment of the same service_type.
    for other in domain.plan_commitments(plan):
        if other["service_type"] == service_type and other["commitment_status"] == "DRAFT":
            other["commitment_status"] = "VOIDED"
            touch(other)

    record = base_record()
    record.update(
        {
            "plan_of_services_id": plan["id"],
            "service_provider_id": provider["id"],
            "service_type": service_type,
            "window_start_date": window_start,
            "window_end_date": window_end,
            "timeline_days": calc.timeline_days(window_start, window_end),
            "committed_account_count": committed_account_count,
            "activated_account_count": 0,
            "cost_cents": cost_cents,
            "commitment_status": "DRAFT",
        }
    )
    db.commitments[record["id"]] = record

    touch(plan)
    return object_response(record, 201)


@bp.get("/service-commitments/<commitment_id>")
def read_commitment(commitment_id):
    prelude(ANY_ROLE)
    return object_response(domain.path_record("commitments", commitment_id))


@bp.get("/service-commitments")
def list_commitments():
    prelude(ANY_ROLE)
    return paginate(
        domain.rows("commitments"),
        ("plan_of_services_id", "service_provider_id", "commitment_status", "service_type"),
    )


@bp.post("/service-commitments/<commitment_id>/activate")
def activate_commitment(commitment_id):
    commitment, _user_id, _role = _commitment_for_write(commitment_id, ("MunicipalPlanner",))
    plan = domain.soft("plans", commitment["plan_of_services_id"])
    case = domain.case_of_commitment(commitment)
    domain.assert_case_not_terminal(case)
    statute = domain.statute_of_case(case)

    if commitment["commitment_status"] != "DRAFT":
        raise ApiError("ERR_COMMITMENT_STATE_INVALID", "Only a DRAFT commitment may be activated.")

    ceiling = domain.timeline_ceiling(statute, commitment["service_type"])
    if int(commitment["timeline_days"]) > ceiling:
        raise ApiError(
            "ERR_PLAN_SERVICE_TIMELINE_EXCEEDS_STATUTE",
            "The commitment window exceeds the statutory maximum of %d days." % ceiling,
        )

    provider = domain.soft("service_providers", commitment["service_provider_id"])
    if provider is None or commitment["service_type"] not in provider["service_types"]:
        raise ApiError(
            "ERR_PROVIDER_SERVICE_TYPE_MISMATCH",
            "The provider does not deliver %s service." % commitment["service_type"],
        )

    peers = [
        (c["window_start_date"], c["window_end_date"])
        for c in domain.rows("commitments")
        if c["id"] != commitment["id"]
        and c["service_provider_id"] == provider["id"]
        and c["commitment_status"] in ("ACTIVE", "FULFILLED")
    ]
    if not calc.capacity_admissible(
        commitment["window_start_date"],
        commitment["window_end_date"],
        peers,
        provider["concurrent_project_capacity"],
    ):
        raise ApiError(
            "ERR_PROVIDER_CAPACITY_EXCEEDED",
            "The provider's concurrent project capacity is exhausted inside this window.",
        )

    commitment["commitment_status"] = "ACTIVE"
    if int(commitment["committed_account_count"]) == 0:
        commitment["commitment_status"] = "FULFILLED"
    touch(commitment)

    domain.recompute_provider_encumbrance(provider)
    touch(provider)
    if plan is not None:
        domain.recompute_plan(plan, statute)
        touch(plan)
    return object_response(commitment)


@bp.post("/service-commitments/<commitment_id>/void")
def void_commitment(commitment_id):
    commitment, _user_id, _role = _commitment_for_write(commitment_id, ("MunicipalPlanner",))
    plan = domain.soft("plans", commitment["plan_of_services_id"])
    case = domain.case_of_commitment(commitment)
    domain.assert_case_not_terminal(case)
    statute = domain.statute_of_case(case)

    if case is not None and case["status"] == "EFFECTIVE":
        raise ApiError(
            "ERR_CASE_STATE_INVALID",
            "A commitment may not be voided once the case is EFFECTIVE.",
        )
    if commitment["commitment_status"] == "VOIDED":
        raise ApiError("ERR_COMMITMENT_STATE_INVALID", "The commitment is already voided.")

    released = commitment["commitment_status"] in ("ACTIVE", "FULFILLED")
    commitment["commitment_status"] = "VOIDED"
    touch(commitment)

    if released:
        provider = domain.soft("service_providers", commitment["service_provider_id"])
        if provider is not None:
            domain.recompute_provider_encumbrance(provider)
            touch(provider)
    if plan is not None:
        domain.recompute_plan(plan, statute)
        touch(plan)
    return object_response(commitment)

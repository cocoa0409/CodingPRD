"""Access control: header presence, role exclusivity, entity-backed customer
ownership, and the auth-before-existence gate ordering."""

import test_helpers as fx
from test_helpers import (
    NON_EXISTENT_UUID,
    PM,
    ApiErrorId,
    create_decision_payload,
    create_record_payload,
    make_assessor_headers,
    make_customer_headers,
    make_engineer_headers,
    validate_error,
    validate_success,
)

ASSESSOR_1 = "assessor-1"


def test_auth_precedes_existence_ordering(api):
    """PRD §2.8: "Every request passes through a fixed cascade of validation gates, evaluated in the order below. When several gates would fail, the earliest failing gate's error is the one reported, so higher-priority failures are never masked by lower-priority ones."
    PRD §2.8: "`X-User-ID` and `X-User-Role` are present and the role is one of the nine declared names; otherwise `ERR_MISSING_HEADERS` (HTTP 401). Applies to every endpoint."
    PRD §2.8: "Path identifiers exist, validated left to right, and body-referenced identifiers (`part_id`, `window_id`, `offer_id`) exist; otherwise `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/auth_precedes_existence_ordering
    """
    no_auth = api.get_machine(NON_EXISTENT_UUID, headers={})
    validate_error(no_auth, ApiErrorId.ERR_MISSING_HEADERS.value)

    with_auth = api.get_machine(NON_EXISTENT_UUID, PM)
    validate_error(with_auth, ApiErrorId.ERR_NOT_FOUND.value)


def test_rbac_customer_cannot_record_decision(api):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    The routing summary in PRD §4 lists ProjectManager as the only authorized role for POST /api/projects/{id}/decision.

    Design: Corner/rbac/rbac_customer_cannot_record_decision
    """
    ctx = fx.setup_project_scoped()

    res = api.record_decision(
        ctx.project["id"],
        create_decision_payload(decision="MECHANICAL_REBUILD", assigned_engineer_id="eng-1"),
        make_customer_headers(ctx.customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)

    project = fx.get_project(ctx.project["id"])
    assert project["work_status"] == "SCOPED"


def test_rbac_assessor_cannot_accept_assessment(api):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    The routing summary in PRD §4 lists ProjectManager as the only authorized role for POST /api/assessments/{id}/accept.

    Design: Corner/rbac/rbac_assessor_cannot_accept_assessment
    """
    customer = fx.create_customer()
    machine = fx.create_machine(customer["id"])
    assessment = fx.create_assessment(machine["id"], assessor_id=ASSESSOR_1)
    fx.submit_assessment(assessment["id"], assessor_id=ASSESSOR_1)

    res = api.accept_assessment(assessment["id"], make_assessor_headers(ASSESSOR_1))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)

    after = validate_success(api.get_assessment(assessment["id"], PM), 200)
    assert after["status"] == "SUBMITTED"


def test_rbac_customer_cannot_approve_foreign_project(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer record; ownership checks on any resource that references a customer compare the resource's customer foreign key — `customer_id` on a machine, downtime window, or trade-in offer, and the denormalized `customer_id` carried on a rebuild project — to `X-User-ID`."
    PRD §3.3: "Approval is then the customer's act: the caller's `X-User-ID` must equal the project's `customer_id`, the quote must still be unstale (again `ERR_QUOTE_STALE`), and — as the final fiscal gate of the validation cascade — `quote_price_cents` must not exceed the customer's `credit_limit_cents`, failing which the approval is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/rbac/rbac_customer_cannot_approve_foreign_project
    """
    ctx = fx.setup_project_decided(customer_overrides={"name": "Customer One"})
    other_customer = fx.create_customer(name="Customer Two")
    fx.compute_quote(ctx.project["id"])
    fx.send_quote(ctx.project["id"])

    res = api.approve_quote(ctx.project["id"], make_customer_headers(other_customer["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)

    project = fx.get_project(ctx.project["id"])
    assert project["commercial_status"] == "QUOTE_SENT"


def test_rbac_rebuild_engineer_cannot_record_test(api):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    The routing summary in PRD §4 lists QualityInspector as the only authorized role for POST /api/acceptance-tests/{id}/record.

    Design: Corner/rbac/rbac_rebuild_engineer_cannot_record_test
    """
    ctx = fx.setup_scheduled_test()

    res = api.record_acceptance_test(
        ctx.test["id"],
        create_record_payload(samples=[8, -8, 8, -8, 0], repeatability_microns=5.0),
        make_engineer_headers("eng-1"),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)

    test_after = validate_success(api.get_acceptance_test(ctx.test["id"], PM), 200)
    assert test_after["status"] == "SCHEDULED"

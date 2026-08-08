"""Authentication, role scoping, ownership, and the precedence between them and
path resolution."""

import test_helpers as fx
from test_helpers import (
    ADMIN,
    ECOLOGIST,
    LAB,
    MANAGER,
    NO_AUTH_HEADERS,
    RESIDENT,
    ApiErrorId,
    validate_error,
)

UNKNOWN_AREA_ID = "00000000-0000-4000-8000-000000000000"


def test_request_without_auth_headers_is_unauthenticated(api):
    """PRD §2.1: "Every endpoint in this API — without exception, including the
    logical-clock endpoint and every read — requires authentication."
    PRD §2.1: "If either header is absent, or is present but empty, or if
    `X-User-Role` does not spell one of the seven roles below exactly, the request
    is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). No endpoint has an anonymous
    mode."

    Design: Corner/rbac/corner_missing_auth_headers_returns_unauthenticated
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()

    response = api.get_service_area(area["id"], NO_AUTH_HEADERS)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_role_scoping_bites_at_both_endpoint_and_action_level(api):
    """PRD §2.1: "When the acting role is not among the roles listed for the
    endpoint in §4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "An `AbatementManager` may not send the submit action on a plan, a
    `VectorEcologist` may not send the approve action, a `FieldTech` may not send
    the commit action, and only a `SensitiveSiteOperator` may send the acknowledge
    action on a notice — each such mismatch is `ERR_UNAUTHORIZED`, even though the
    role does appear in the endpoint's role list."

    Design: Corner/rbac/corner_role_scoped_writes_reject_wrong_roles
    """
    bundle = fx.setup_plan_scenario(
        treatment_type="AERIAL", approve=False, routes=[{"planned_acres": 10.0}]
    )
    fx.plan_action(bundle["plan"]["id"], "SUBMIT", ECOLOGIST)
    request = fx.file_request(
        bundle["area"]["id"], description="Water in tyres", x_m=10, y_m=10
    )

    product_attempt = api.create_pesticide_product(
        {"name": "Sneaky Product", "epa_reg_no": "EPA-999", "active_ingredient": "BTI",
         "application_method": "LARVICIDE", "label_rate_ml_per_acre": 1.0,
         "reentry_interval_hours": 0, "cost_cents_per_liter": 1, "received_total_ml": 1.0},
        LAB,
    )
    validate_error(product_attempt, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    triage_attempt = api.transition_service_request(
        request["id"], {"action": "TRIAGE", "priority": "URGENT"}, RESIDENT
    )
    validate_error(triage_attempt, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    approve_attempt = api.transition_treatment_plan(
        bundle["plan"]["id"], {"action": "APPROVE"}, ECOLOGIST
    )
    validate_error(approve_attempt, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    assert fx.read_request(request["id"])["handling_status"] == "RECEIVED"
    plan = fx.read_plan(bundle["plan"]["id"])
    assert plan["status"] == "SUBMITTED"
    assert plan["approver_user_ids"] == []


def test_entity_backed_roles_may_act_only_on_their_own_resources(api):
    """PRD §2.1: "Ownership checks on any resource that references an `Applicator`
    compare the resource's foreign-key field to `X-User-ID`: a trap collection's
    `recorded_by_applicator_id` when submitting it, a treatment route's
    `applicator_id` when executing it, and a service request's
    `assigned_applicator_id` when inspecting or resolving it. A mismatch is
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §2.1: "When `X-User-Role` is `SensitiveSiteOperator`, `X-User-ID` is the
    `id` of the acting `SensitiveSite`. Acknowledging a spray notice compares the
    notice's `sensitive_site_id` to `X-User-ID`, and a mismatch is likewise
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/corner_entity_backed_ownership_checks_reject_foreign_actors
    """
    bundle = fx.setup_plan_scenario(
        applicator_overrides={"license_category": "LARVICIDE_ONLY"},
        product_overrides={"received_total_ml": 1000.0},
        sensitive_sites=[
            {"site_type": "APIARY", "x_m": 960, "y_m": 1280},
            {"site_type": "ORGANIC_FARM", "operator_name": "Green Row Farm",
             "contact_email": "farm@example.com", "x_m": 5000, "y_m": 5000},
        ],
        routes=[{"center_x_m": 0, "center_y_m": 0}],
    )
    apiary, farm = bundle["sites"]
    other_tech = fx.create_applicator(
        full_name="Ravi Shah", license_no="L-1002", license_category="LARVICIDE_ONLY"
    )
    trap_site = fx.create_trap_site(bundle["area"]["id"])
    collection = fx.log_collection(
        trap_site["id"], bundle["applicator"]["id"],
        collection_date="2026-05-28", trap_nights=1, female_count=10,
    )
    notice = fx.issue_notification(bundle["plan"]["id"], apiary["id"])
    fx.notification_action(notice["id"], "SEND")

    foreign_submit = api.transition_trap_collection(
        collection["id"], {"action": "SUBMIT"}, fx.make_field_tech_headers(other_tech["id"])
    )
    validate_error(foreign_submit, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    foreign_ack = api.transition_notification(
        notice["id"], {"action": "ACKNOWLEDGE"}, fx.make_site_operator_headers(farm["id"])
    )
    validate_error(foreign_ack, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    assert fx.read_collection(collection["id"])["status"] == "LOGGED"
    refreshed_notice = fx.read_notification(notice["id"])
    assert refreshed_notice["status"] == "SENT"
    assert refreshed_notice["acknowledged_at"] is None


def test_each_collection_answers_with_its_own_not_found_code(api):
    """PRD §2.5: "When a path names a service area that does not exist, the answer
    is `ERR_SERVICE_AREA_NOT_FOUND`; the analogous codes for the remaining path
    positions are `ERR_TRAP_SITE_NOT_FOUND`, `ERR_TRAP_COLLECTION_NOT_FOUND`,
    `ERR_LAB_POOL_NOT_FOUND`, `ERR_RISK_ASSESSMENT_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_APPLICATOR_NOT_FOUND`,
    `ERR_TREATMENT_PLAN_NOT_FOUND`, `ERR_TREATMENT_ROUTE_NOT_FOUND`,
    `ERR_NOTIFICATION_NOT_FOUND`, and `ERR_SERVICE_REQUEST_NOT_FOUND`. All ten are
    HTTP 404."

    Design: Corner/errors/corner_every_path_not_found_error_is_entity_specific
    """
    fx.set_clock(fx.CLOCK_BASE)

    probes = [
        (api.get_trap_collection("00000000-0000-4000-8000-000000000001", MANAGER),
         ApiErrorId.ERR_TRAP_COLLECTION_NOT_FOUND.value),
        (api.get_lab_pool("00000000-0000-4000-8000-000000000002", LAB),
         ApiErrorId.ERR_LAB_POOL_NOT_FOUND.value),
        (api.get_risk_assessment("00000000-0000-4000-8000-000000000003", ECOLOGIST),
         ApiErrorId.ERR_RISK_ASSESSMENT_NOT_FOUND.value),
        (api.get_pesticide_product("00000000-0000-4000-8000-000000000004", ADMIN),
         ApiErrorId.ERR_PRODUCT_NOT_FOUND.value),
        (api.get_applicator("00000000-0000-4000-8000-000000000005", ADMIN),
         ApiErrorId.ERR_APPLICATOR_NOT_FOUND.value),
        (api.get_treatment_plan("00000000-0000-4000-8000-000000000006", MANAGER),
         ApiErrorId.ERR_TREATMENT_PLAN_NOT_FOUND.value),
        (api.get_treatment_route("00000000-0000-4000-8000-000000000007", MANAGER),
         ApiErrorId.ERR_TREATMENT_ROUTE_NOT_FOUND.value),
        (api.get_notification("00000000-0000-4000-8000-000000000008", ADMIN),
         ApiErrorId.ERR_NOTIFICATION_NOT_FOUND.value),
        (api.get_service_request("00000000-0000-4000-8000-000000000009", RESIDENT),
         ApiErrorId.ERR_SERVICE_REQUEST_NOT_FOUND.value),
    ]

    for response, expected in probes:
        error = validate_error(response, expected, 404)
        assert response.json()["response_type"] == "error"
        assert isinstance(error["message"], str) and error["message"].strip()


def test_wrong_role_outranks_an_unresolvable_service_area(api):
    """PRD §2.11: "**Authorization** — the acting role is listed for the endpoint
    and, on a transition-driving endpoint, is the declared actor of the requested
    action; otherwise `ERR_UNAUTHORIZED`."
    PRD §2.11: "**Path existence** — every identifier in the path resolves, left to
    right, with the code matching the first unresolved segment."
    PRD §2.11: "Checks are evaluated in the following order, and the first failure
    short-circuits the request:"

    Design: Difficulty/priority_pair_validation_conflict/unauthorized_role_outranks_missing_service_area
    """
    fx.set_clock(fx.CLOCK_BASE)
    tech = fx.create_applicator()

    response = api.create_trap_site(
        UNKNOWN_AREA_ID,
        {"site_code": "T-999", "trap_type": "CDC_LIGHT", "habitat": "URBAN",
         "x_m": 0, "y_m": 0},
        fx.make_field_tech_headers(tech["id"]),
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert response.status_code == 403


def test_the_same_path_reports_not_found_once_the_role_is_authorised(api):
    """PRD §2.5: "When a path names a service area that does not exist, the answer
    is `ERR_SERVICE_AREA_NOT_FOUND`"
    PRD §3.1: "**Trap sites** are the fixed surveillance hardware of the area, also
    registered by a `DistrictAdmin` under the area path."

    Design: Difficulty/priority_pair_validation_conflict/unauthorized_role_outranks_missing_service_area
    """
    fx.set_clock(fx.CLOCK_BASE)

    response = api.create_trap_site(
        UNKNOWN_AREA_ID,
        {"site_code": "T-999", "trap_type": "CDC_LIGHT", "habitat": "URBAN",
         "x_m": 0, "y_m": 0},
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_SERVICE_AREA_NOT_FOUND.value, 404)
    assert response.status_code == 404

"""Corner section: rbac (PRD §2.1, §2.9, §3.5).

Role authorization (participant cannot run-purchase), participant ownership on
enrollment actions, and missing-auth-header rejection. The segregation-of-duties
and OCC stale-version checks live in test_26 alongside the cross-cutting layers.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    create_plan_payload,
    create_offering_payload,
    create_participant_payload,
    create_enrollment_payload,
    create_purchase_period_payload,
    create_contribution_payload,
    run_purchase_payload,
    make_participant_headers,
    make_officer_headers,
)


def test_participant_cannot_run_purchase(api, admin_headers):
    """PRD §2.1: "When the headers are present but the role named in X-User-Role is not
    authorized for the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)."

    run-purchase is a PlanAdministrator-only operation (PRD §4 endpoint table); a
    Participant calling it is denied with ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/participant_cannot_run_purchase
    """
    plan = get_success_data(api.create_plan(create_plan_payload(), admin_headers))
    participant = get_success_data(
        api.create_participant(create_participant_payload(), admin_headers)
    )
    offering = get_success_data(
        api.create_offering_period(create_offering_payload(plan["id"]), admin_headers)
    )
    enrollment = get_success_data(
        api.create_enrollment(
            create_enrollment_payload(
                participant["id"], offering["id"], contribution_rate_pct=10
            ),
            make_participant_headers(participant["id"]),
        )
    )
    get_success_data(api.close_enrollment(offering["id"], admin_headers))
    batch = get_success_data(
        api.create_purchase_period(
            offering["id"], create_purchase_period_payload(), admin_headers
        )
    )
    opened = get_success_data(api.open_purchase_period(batch["id"], admin_headers))
    certified = get_success_data(
        api.certify_purchase_period(batch["id"], make_officer_headers("officer1"))
    )
    resp = api.run_purchase(
        batch["id"], run_purchase_payload(certified["version"]),
        make_participant_headers(participant["id"]),
    )
    validate_error(resp, "ERR_FORBIDDEN_ROLE")


def test_participant_cannot_act_on_others_enrollment(api, admin_headers):
    """PRD §2.1: "For participant-owned actions — the enrollment lifecycle operations
    and disposition recording — the acting participant's X-User-ID must equal the
    participant_id of the affected resource ... A participant acting on a resource they
    do not own is rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Participant B suspending participant A's enrollment => ERR_NOT_RESOURCE_OWNER.

    Design: Corner/rbac/participant_cannot_act_on_others_enrollment
    """
    plan = get_success_data(api.create_plan(create_plan_payload(), admin_headers))
    pa = get_success_data(
        api.create_participant(create_participant_payload(), admin_headers)
    )
    pb = get_success_data(
        api.create_participant(create_participant_payload(), admin_headers)
    )
    offering = get_success_data(
        api.create_offering_period(create_offering_payload(plan["id"]), admin_headers)
    )
    enrollment = get_success_data(
        api.create_enrollment(
            create_enrollment_payload(pa["id"], offering["id"], contribution_rate_pct=10),
            make_participant_headers(pa["id"]),
        )
    )
    resp = api.suspend_enrollment(enrollment["id"], make_participant_headers(pb["id"]))
    validate_error(resp, "ERR_NOT_RESOURCE_OWNER")


def test_missing_auth_headers_unauthenticated(api, admin_headers):
    """PRD §2.1: "Every request other than participant self-registration must carry two
    headers identifying the caller: X-User-ID and X-User-Role. If either header is
    missing or carries an unrecognized value, the request is rejected with
    ERR_UNAUTHENTICATED (HTTP 401)."

    A GET on an existing plan with no auth headers => ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    plan = get_success_data(api.create_plan(create_plan_payload(), admin_headers))
    resp = api.get_plan(plan["id"], headers={})
    validate_error(resp, "ERR_UNAUTHENTICATED")

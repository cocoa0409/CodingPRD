"""Role-based access control: exclusive-operation enforcement and entity-backed ownership."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_config, create_approved_helper, create_booked_job, assign_helper,
    create_job_payload, create_assignment_payload,
    make_helper_headers, make_customer_headers, ADMIN, api_client,
)

WINDOW_START = "2026-03-11T09:00:00Z"
WINDOW_END = "2026-03-11T11:00:00Z"


def test_helper_cannot_create_job(api):
    """PRD §2.1: "When an authenticated caller attempts an operation their role is not
    permitted to perform, or acts on a resource they do not own, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    POST /jobs is Customer-exclusive; a Helper caller is forbidden.

    Design: Corner/rbac/helper_cannot_create_job
    """
    rate_card, policy, _customer = create_config(api)
    helper = create_approved_helper(api, email="hh@x.com")
    resp = api.create_job(
        create_job_payload(rate_card["id"], policy["id"], crew_size=1, estimated_hours=2.0,
                           window_start=WINDOW_START, window_end=WINDOW_END),
        make_helper_headers(helper["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_customer_cannot_create_assignment(api):
    """PRD §2.1: "When an authenticated caller attempts an operation their role is not
    permitted to perform ... the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    POST /assignments is Dispatcher-exclusive; a Customer caller is forbidden.

    Design: Corner/rbac/customer_cannot_create_assignment
    """
    rate_card, policy, customer = create_config(api)
    helper = create_approved_helper(api, email="hh@x.com")
    booked, _q = create_booked_job(
        api, rate_card["id"], policy["id"], customer["id"],
        crew_size=1, estimated_hours=2.0, window_start=WINDOW_START, window_end=WINDOW_END,
    )
    resp = api.create_assignment(
        create_assignment_payload(booked["id"], helper["id"]),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_helper_cannot_check_in_others_assignment(api):
    """PRD §2.1: "Ownership checks on an `Assignment` compare the assignment's `helper_id` to
    `X-User-ID`; a helper may only check in or check out of an assignment they own." PRD §3.5:
    "both actions require that the acting helper's `X-User-ID` equal the assignment's
    `helper_id`."

    Design: Corner/rbac/helper_cannot_checkin_others_assignment
    """
    rate_card, policy, customer = create_config(api)
    helper_a = create_approved_helper(api, email="ha@x.com")
    helper_b = create_approved_helper(api, email="hb@x.com")
    booked, _q = create_booked_job(
        api, rate_card["id"], policy["id"], customer["id"],
        crew_size=1, estimated_hours=2.0, window_start=WINDOW_START, window_end=WINDOW_END,
    )
    assignment = assign_helper(api, booked["id"], helper_a["id"])
    resp = api.check_in(assignment["id"], make_helper_headers(helper_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    after = validate_success(api.get_assignment(assignment["id"], ADMIN))
    assert after["status"] == "ASSIGNED"

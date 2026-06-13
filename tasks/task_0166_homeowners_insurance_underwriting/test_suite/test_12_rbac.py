"""Role-based access denials and segregation of duties.
Queue B — section rbac.
"""
import pytest

from test_helpers import (
    validate_error,
    TEST_USERS,
    make_underwriter_headers,
    make_inspector_headers,
    ApiErrorId,
    factories as f,
    fixtures as fx,
)

AGENT = TEST_USERS["agent_headers"]
UW = TEST_USERS["underwriter_headers"]


def test_agent_cannot_bind_segregation_of_duties(api):
    """PRD §3.6: "The acting underwriter must be the one assigned ... this is the
    segregation of duties point, since the producer is an agent and the binder must
    be the assigned underwriter."
    PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/agent_cannot_bind_segregation_of_duties
    """
    uw = fx.create_underwriter()
    prop, ra = fx.setup_estimated_property(prop_overrides={"street_address": "35 Segr St"})
    app = fx.create_application(prop["id"], 300000)
    app = fx.submit_application(app["id"])
    app = fx.take_review(app["id"], uw["id"])
    # Agent attempts the bind — bind is exclusive to Underwriter.
    resp = api.bind_application(
        app["id"],
        f.bind_application_payload(1751000000, 1782536000, app["version"]),
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_inspector_cannot_create_risk_assessment(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §3.2: "A property's exposure is captured by a risk assessment, authored by an
    underwriter."

    Design: Corner/rbac/inspector_cannot_create_risk_assessment
    """
    inspector = fx.create_inspector()
    prop = fx.create_property(street_address="36 Role St")
    resp = api.create_risk_assessment(
        f.create_risk_assessment_payload(prop["id"]),
        make_inspector_headers(inspector["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_non_assigned_underwriter_cannot_decline(api):
    """PRD §3.6: "declining is permitted only while the application is `UNDER_REVIEW`
    (otherwise `ERR_APPLICATION_NOT_UNDER_REVIEW`) and only by the assigned underwriter
    (otherwise `ERR_NOT_ASSIGNED_UNDERWRITER`)."

    Design: Corner/rbac/non_assigned_underwriter_cannot_decline
    """
    uw1 = fx.create_underwriter(full_name="UW One")
    uw2 = fx.create_underwriter(full_name="UW Two")
    prop, ra = fx.setup_estimated_property(prop_overrides={"street_address": "37 Assign St"})
    app = fx.create_application(prop["id"], 300000)
    app = fx.submit_application(app["id"])
    app = fx.take_review(app["id"], uw1["id"])
    resp = api.decline_application(
        app["id"], f.decline_application_payload("INSPECTION_FAILED"),
        make_underwriter_headers(uw2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_UNDERWRITER.value)

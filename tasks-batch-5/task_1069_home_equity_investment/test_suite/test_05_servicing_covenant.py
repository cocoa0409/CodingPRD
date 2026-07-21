"""Maintenance-covenant inspections and their effect on the agreement."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_homeowner_headers,
    fixtures,
)

ANALYST = TEST_USERS["analyst_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def test_failed_inspection_sets_covenant_breach(api):
    """PRD §3.6: "A failed inspection is a covenant event: if the agreement's
    covenant_status is COMPLIANT or CURED, it moves to BREACH_NOTICED."

    Design: Corner/cross_cutting/inspection_fail_sets_covenant_breach_noticed
    """
    ctx = fixtures.setup_active_agreement(api)
    inspector = fixtures.create_inspector(api)
    inspection = fixtures.schedule_inspection(api, ctx["agreement"]["id"], inspector["id"])
    completed = fixtures.complete_inspection(api, inspection["id"], inspector["id"], "FAILED", 42)
    assert completed["status"] == "FAILED"
    agreement = validate_success(api.get_agreement(ctx["agreement"]["id"], ANALYST))
    assert agreement["covenant_status"] == "BREACH_NOTICED"


def test_initiate_exit_with_open_breach_rejected(api):
    """PRD §3.5: "This is blocked while a maintenance-covenant breach is open —
    if the agreement's covenant_status is BREACH_NOTICED, the request is
    rejected with ERR_COVENANT_BREACH_OPEN".

    Design: Corner/cross_cutting/initiate_exit_with_open_breach_returns_error
    """
    ctx = fixtures.setup_active_agreement(api)
    inspector = fixtures.create_inspector(api)
    inspection = fixtures.schedule_inspection(api, ctx["agreement"]["id"], inspector["id"])
    fixtures.complete_inspection(api, inspection["id"], inspector["id"], "FAILED", 42)
    validate_error(
        api.initiate_exit(ctx["agreement"]["id"], make_homeowner_headers(ctx["homeowner"]["id"])),
        "ERR_COVENANT_BREACH_OPEN", 409,
    )


def test_default_without_open_breach_rejected(api):
    """PRD §3.5: "a default is only permitted when a covenant breach is actually
    open, that is, when covenant_status is BREACH_NOTICED, else it is rejected
    with ERR_NO_OPEN_BREACH."

    Design: Corner/cross_cutting/default_without_open_breach_returns_error
    """
    ctx = fixtures.setup_active_agreement(api)
    validate_error(api.default_agreement(ctx["agreement"]["id"], COMPLIANCE), "ERR_NO_OPEN_BREACH", 409)

"""Invalid transitions, terminal lockdown, and reschedule side effects.
Queue B — section state_machines.
"""
import pytest

from test_helpers import (
    validate_success,
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


def test_submit_already_submitted_returns_not_draft(api):
    """PRD §3.4: "The application must be in `DRAFT`, otherwise
    `ERR_APPLICATION_NOT_DRAFT`."

    Design: Corner/state_machines/submit_from_already_submitted_returns_not_draft
    """
    prop, ra, app = fx.setup_submitted_application()
    resp = api.submit_application(app["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_DRAFT.value)


def test_cancel_from_cancelled_returns_not_cancellable(api):
    """PRD §3.7: "Cancellation is permitted while the policy is `ACTIVE`,
    `REINSTATED`, or `LAPSED`, otherwise `ERR_POLICY_NOT_CANCELLABLE`, and it moves
    the policy to the terminal `CANCELLED` state."

    Design: Corner/state_machines/cancel_from_cancelled_returns_not_cancellable
    """
    ctx = fx.setup_active_policy(binding_amount=997.50)
    policy, uw = ctx["policy"], ctx["underwriter"]
    first = validate_success(api.cancel_policy(policy["id"], make_underwriter_headers(uw["id"])))
    assert first["status"] == "CANCELLED"
    resp = api.cancel_policy(policy["id"], make_underwriter_headers(uw["id"]))
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_CANCELLABLE.value)


def test_reschedule_from_scheduled_returns_not_failed(api):
    """PRD §3.3: "The inspector reschedules it, supplying a fresh `window_start` and
    `window_end`; this is allowed only from `FAILED`, otherwise
    `ERR_INSPECTION_NOT_FAILED`, and the new window is re-checked against the same
    inspector buffer-conflict rule."

    Design: Corner/state_machines/reschedule_from_scheduled_returns_not_failed
    """
    inspector = fx.create_inspector()
    prop = fx.create_property(street_address="22 Resch St")
    insp = fx.schedule_inspection(prop["id"], inspector["id"], 1751400000, 1751403600)
    resp = api.reschedule_inspection(
        insp["id"], f.reschedule_inspection_payload(1751500000, 1751503600),
        make_inspector_headers(inspector["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_FAILED.value)


def test_failed_inspection_reschedule_resets_flags(api):
    """PRD §3.3: "Rescheduling returns the inspection to `SCHEDULED`, resets all four
    condition flags to false, and resets `passed_count` to 0, so the re-inspection
    starts clean."

    Design: Corner/state_machines/failed_inspection_reschedule_resets_flags
    """
    inspector = fx.create_inspector()
    prop = fx.create_property(street_address="23 Reset St")
    insp = fx.schedule_inspection(prop["id"], inspector["id"], 1751600000, 1751603600)
    failed = fx.complete_inspection(insp["id"], inspector["id"],
                                    roof_ok=True, electrical_ok=True,
                                    plumbing_ok=False, hvac_ok=False)
    assert failed["status"] == "FAILED" and failed["passed_count"] == 2
    rescheduled = validate_success(
        api.reschedule_inspection(
            insp["id"], f.reschedule_inspection_payload(1751700000, 1751703600),
            make_inspector_headers(inspector["id"]),
        )
    )
    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["passed_count"] == 0
    assert rescheduled["window_start"] == 1751700000
    assert rescheduled["roof_ok"] is False and rescheduled["hvac_ok"] is False


def test_take_review_from_draft_returns_not_submitted(api):
    """PRD §3.6: "An underwriter takes a submitted application under review, which is
    permitted only from `SUBMITTED`, otherwise `ERR_APPLICATION_NOT_SUBMITTED`."

    Design: Corner/state_machines/take_review_from_draft_returns_not_submitted
    """
    uw = fx.create_underwriter()
    prop = fx.create_property(street_address="24 Draft St")
    app = fx.create_application(prop["id"], 300000)
    resp = api.take_review_application(app["id"], make_underwriter_headers(uw["id"]))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_SUBMITTED.value)

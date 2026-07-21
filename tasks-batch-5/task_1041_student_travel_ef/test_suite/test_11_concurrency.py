"""Optimistic concurrency on payment-plan creation (queue-B cross-cutting layer)."""
from test_helpers import (
    validate_success, validate_error, OPERATOR,
    ApiErrorId,
    setup_open_departure, enroll, make_plan,
    create_payment_plan_payload,
)


def test_payment_plan_create_with_stale_enrollment_version_returns_412(api):
    """PRD §2.10: "Because creating a new plan supersedes the enrollment's prior active plan
    and advances the enrollment's version, a client whose expected_enrollment_version no
    longer matches the enrollment's current version has not seen that supersede; the request
    is therefore rejected with ERR_STALE_VERSION (HTTP 412) rather than silently creating a
    second competing plan."

    Design: Corner/cross_cutting_complexity_layers/payment_plan_create_stale_enrollment_version_returns_412
    """
    ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z")
    enr = enroll(api, ctx["departure"]["id"], traveler_name="OCC O")
    original_version = enr["version"]
    make_plan(api, enr["id"], original_version, installment_count=2)  # bumps enrollment.version
    # Reuse the now-stale original version.
    resp = api.create_payment_plan(
        create_payment_plan_payload(enr["id"], original_version, installment_count=3), OPERATOR
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


def test_payment_plan_create_with_current_version_supersedes_prior_plan(api):
    """PRD §3.4: "When a new active plan is created for an enrollment that already has one,
    the prior active plan transitions ACTIVE → SUPERSEDED and its accumulated
    amount_paid_cents is carried forward onto the new plan through mirrored payment rows;
    creating a plan advances the enrollment's version by 1".

    Design: Corner/cross_cutting_complexity_layers/payment_plan_create_correct_version_supersedes_prior_plan
    """
    ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z")
    enr = enroll(api, ctx["departure"]["id"], traveler_name="Sup S")
    plan1 = make_plan(api, enr["id"], enr["version"], installment_count=2)
    refreshed = validate_success(api.get_enrollment(enr["id"], OPERATOR))
    plan2 = validate_success(
        api.create_payment_plan(
            create_payment_plan_payload(enr["id"], refreshed["version"], installment_count=3), OPERATOR
        ),
        expected_status=201,
    )
    assert plan2["status"] == "ACTIVE"
    superseded = validate_success(api.get_payment_plan(plan1["id"], OPERATOR))
    assert superseded["status"] == "SUPERSEDED"

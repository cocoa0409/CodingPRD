"""Corner section: validations (PRD §3.3, §3.8).

Rate-exceeds rejection, valid-enrollment success, terminated-participant bar,
duplicate-enrollment aggregate, and insufficient-shares disposition.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_enrollment_payload,
    create_disposition_payload,
    create_offering_payload,
    create_plan_payload,
    create_participant_payload,
    setup_open_offering,
    setup_settled_purchase,
    make_participant_headers,
)


def test_rate_exceeds_plan_max_rejected(api, admin_headers):
    """PRD §3.3: "then it rejects a contribution_rate_pct that is not greater than 0 or
    that exceeds the plan's max_contribution_rate_pct with ERR_RATE_EXCEEDS_LIMIT
    (HTTP 422)".

    Enrolling at 16% under a plan with max 15% => ERR_RATE_EXCEEDS_LIMIT.

    Design: Corner/validations/rate_exceeds_plan_max_rejected
    """
    plan = get_success_data(
        api.create_plan(create_plan_payload(max_contribution_rate_pct=15), admin_headers)
    )
    participant = get_success_data(
        api.create_participant(create_participant_payload(), admin_headers)
    )
    offering = get_success_data(
        api.create_offering_period(create_offering_payload(plan["id"]), admin_headers)
    )
    resp = api.create_enrollment(
        create_enrollment_payload(
            participant["id"], offering["id"], contribution_rate_pct=16
        ),
        make_participant_headers(participant["id"]),
    )
    validate_error(resp, "ERR_RATE_EXCEEDS_LIMIT")


def test_valid_enrollment_succeeds(api, admin_headers):
    """PRD §3.3: "A new enrollment opens in ENROLLED status with an
    accumulated_contribution_cents of 0 and a refunded_contribution_cents of 0."

    An ACTIVE non-owner at a valid rate 10% => 201, status ENROLLED.

    Design: Corner/validations/valid_enrollment_succeeds
    """
    plan = get_success_data(
        api.create_plan(create_plan_payload(max_contribution_rate_pct=15), admin_headers)
    )
    participant = get_success_data(
        api.create_participant(create_participant_payload(), admin_headers)
    )
    offering = get_success_data(
        api.create_offering_period(create_offering_payload(plan["id"]), admin_headers)
    )
    enr = validate_success(
        api.create_enrollment(
            create_enrollment_payload(
                participant["id"], offering["id"], contribution_rate_pct=10
            ),
            make_participant_headers(participant["id"]),
        ),
        expected_status=201,
    )
    assert enr["status"] == "ENROLLED", enr


def test_terminated_participant_cannot_enroll(api, admin_headers):
    """PRD §3.3: "then it rejects an employee whose status is not ACTIVE with
    ERR_PARTICIPANT_NOT_ACTIVE (HTTP 422)".
    PRD §3.1: "an administrator may later mark a participant TERMINATED".

    Design: Corner/validations/terminated_participant_cannot_enroll
    """
    plan = get_success_data(api.create_plan(create_plan_payload(), admin_headers))
    participant = get_success_data(
        api.create_participant(create_participant_payload(), admin_headers)
    )
    get_success_data(api.terminate_participant(participant["id"], admin_headers))
    offering = get_success_data(
        api.create_offering_period(create_offering_payload(plan["id"]), admin_headers)
    )
    resp = api.create_enrollment(
        create_enrollment_payload(
            participant["id"], offering["id"], contribution_rate_pct=10
        ),
        make_participant_headers(participant["id"]),
    )
    validate_error(resp, "ERR_PARTICIPANT_NOT_ACTIVE")


def test_duplicate_enrollment_aggregate_rejected(api, admin_headers):
    """PRD §3.3: "finally it rejects an attempt to hold more than one non-terminal
    enrollment in the same offering — that is, when the participant already has an
    enrollment in ENROLLED or SUSPENDED status against that offering — with
    ERR_DUPLICATE_ENROLLMENT (HTTP 409)".

    Design: Corner/validations/duplicate_enrollment_aggregate_rejected
    """
    plan = get_success_data(api.create_plan(create_plan_payload(), admin_headers))
    participant = get_success_data(
        api.create_participant(create_participant_payload(), admin_headers)
    )
    offering = get_success_data(
        api.create_offering_period(create_offering_payload(plan["id"]), admin_headers)
    )
    ph = make_participant_headers(participant["id"])
    get_success_data(
        api.create_enrollment(
            create_enrollment_payload(
                participant["id"], offering["id"], contribution_rate_pct=10
            ),
            ph,
        )
    )
    resp = api.create_enrollment(
        create_enrollment_payload(
            participant["id"], offering["id"], contribution_rate_pct=5
        ),
        ph,
    )
    validate_error(resp, "ERR_DUPLICATE_ENROLLMENT")


def test_disposition_insufficient_shares_rejected(api):
    """PRD §3.8: "The shares_sold must be greater than 0 and at most the lot's
    shares_remaining, or the request is rejected with ERR_INSUFFICIENT_SHARES
    (HTTP 422)."

    Selling more than the lot holds (shares_remaining + 1) => ERR_INSUFFICIENT_SHARES.

    Design: Corner/validations/disposition_insufficient_shares_rejected
    """
    ctx = setup_settled_purchase(
        plan_overrides={"discount_pct": 15, "lookback_enabled": True},
        offering_overrides={
            "grant_date": "2022-01-01T00:00:00.000Z", "grant_date_fmv_cents": 1000,
        },
        batch_overrides={
            "purchase_date": "2022-06-30T00:00:00.000Z", "purchase_date_fmv_cents": 1200,
        },
        rate_pct=10,
    )
    lot = ctx["share_lot"]
    ph = make_participant_headers(ctx["participant"]["id"])
    resp = api.create_disposition(
        create_disposition_payload(
            lot["id"], ctx["participant"]["id"],
            sale_date="2024-06-30T00:00:00.000Z",
            shares_sold=lot["shares_remaining"] + 1,
            sale_price_per_share_cents=1500,
        ),
        ph,
    )
    validate_error(resp, "ERR_INSUFFICIENT_SHARES")

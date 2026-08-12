"""Hardship creation gates: enum schema, plan safe-harbor list, vested-balance
cap (PRD §2.8 priorities 4, 11, 12)."""
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_hardship_request_payload,
    create_plan_payload,
    enroll_participant,
    make_participant_headers,
    setup_plan_and_participant,
)

ADMIN = TEST_USERS["admin_headers"]


def test_hardship_unknown_reason_enum_rejected(api):
    """PRD §2.8 priority 4: "an unknown member of `reason_category`,
    `document_type`, `decision`, or any other enum field fails here ... the error
    is `ERR_INVALID_REQUEST`."

    Design: Corner/entities/hardship_unknown_reason_enum_rejected
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=20_000_000)
    res = api.create_hardship_request(
        participant["id"],
        {"reason_category": "VACATION", "amount_cents": 100_000},
        make_participant_headers(participant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_plan_disallowed_safe_harbor_reason_rejected(api):
    """PRD §2.8 priority 11: "the hardship `reason_category` is among the plan's
    `allowed_hardship_reasons` (otherwise `ERR_UNSAFE_HARBOR_REASON`)"."

    Design: Corner/entities/plan_disallowed_safe_harbor_reason_rejected
    """
    plan = api.create_plan(
        create_plan_payload(allowed_hardship_reasons=["MEDICAL", "FUNERAL"]),
        ADMIN,
    ).json()["data"]
    participant = enroll_participant(plan["id"], vested_balance_cents=20_000_000)
    res = api.create_hardship_request(
        participant["id"],
        create_hardship_request_payload(
            reason_category="TUITION", amount_cents=100_000, amount_semantics="GROSS"
        ),
        make_participant_headers(participant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_UNSAFE_HARBOR_REASON, expected_status=422)


def test_hardship_amount_above_vested_balance_rejected(api):
    """PRD §2.8 priority 12: "a hardship `amount_cents` must not exceed the
    participant's `vested_balance_cents` at creation (otherwise
    `ERR_INSUFFICIENT_VESTED_BALANCE`)"."

    Design: Corner/validations/hardship_amount_above_vested_balance_rejected
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=20_000_000)
    res = api.create_hardship_request(
        participant["id"],
        create_hardship_request_payload(
            reason_category="MEDICAL",
            amount_cents=25_000_000,
            amount_semantics="GROSS",
        ),
        make_participant_headers(participant["id"]),
    )
    validate_error(
        res, ApiErrorId.ERR_INSUFFICIENT_VESTED_BALANCE, expected_status=422
    )

"""Collections intake, write-off workflow, and segregation-of-duties claims
(PRD §3.10, §3.7, §2.1)."""
from test_helpers import (
    ApiErrorId,
    account_version,
    create_payment_plan_payload,
    make_bursar_manager_headers,
    make_payment,
    read_account,
    setup_account_with_enrollment,
    setup_collections_account,
    validate_error,
    validate_success,
)


def test_collections_entry_and_zero_balance_errors(api, bursar_staff_headers):
    """PRD §3.10: "The account must be `PAST_DUE` — any other state is rejected
    with `ERR_COLLECTIONS_STATE_INVALID` (HTTP 409)" and "Out-of-order requests
    or approvals — for instance a `REQUEST` against an account not in
    `COLLECTIONS`, or an `APPROVE` with no pending request — are rejected with
    `ERR_COLLECTIONS_STATE_INVALID`."
    PRD §3.7: "plan creation against a zero or credit balance is rejected with
    `ERR_NO_BALANCE_DUE` (HTTP 422)".

    Design: Corner/errors/collections_entry_and_zero_balance_errors
    """
    # Account A: assessed 1cr, still OPEN at the default clock (charges due
    # 2026-09-07 are not yet past due at 2026-08-01).
    ctx_a = setup_account_with_enrollment(credit_hours=1, external_ref="S-OAC")
    res = api.send_to_collections(ctx_a["account_id"], bursar_staff_headers)
    validate_error(res, ApiErrorId.ERR_COLLECTIONS_STATE_INVALID,
                   expected_status=409)
    res = api.write_off(ctx_a["account_id"], {"action": "REQUEST"},
                        bursar_staff_headers)
    validate_error(res, ApiErrorId.ERR_COLLECTIONS_STATE_INVALID,
                   expected_status=409)

    # Account B: fully paid; balance 0 cannot seed a payment plan.
    ctx_b = setup_account_with_enrollment(
        credit_hours=1, external_ref="S-POF",
        term_overrides={"code": "FALL-26B"},
    )
    make_payment(ctx_b["account_id"], 50000)
    version_b = account_version(ctx_b["account_id"])
    res = api.create_payment_plan(
        create_payment_plan_payload(
            account_id=ctx_b["account_id"], installment_count=2,
            first_due_date="2026-09-01", expected_account_version=version_b,
        ),
        bursar_staff_headers,
    )
    validate_error(res, ApiErrorId.ERR_NO_BALANCE_DUE, expected_status=422)


def test_writeoff_segregation_of_duties_enforced(api, bursar_staff_headers):
    """PRD §3.10: "A `REQUEST` action, available to bursar staff and managers
    alike, moves the account's `writeoff_status` from its initial `NONE` to
    `PENDING` and records the caller's `X-User-ID` as the account's
    `writeoff_requester_id`" and "Approval is `BursarManager`-only and is
    forbidden to the requester: an approving `X-User-ID` equal to the stored
    `writeoff_requester_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403). On approval the system posts a `WRITE_OFF` ledger entry equal
    to the account's full `balance_cents`, driving the balance to zero and
    raising `writeoffs_total_cents`; the account moves to terminal
    `WRITTEN_OFF`, its `writeoff_status` becomes `APPROVED`".

    Design: Corner/validations/writeoff_segregation_of_duties_enforced
    """
    ctx = setup_collections_account(credit_hours=9, external_ref="S-WO")
    acc = ctx["account_id"]
    mgr1 = make_bursar_manager_headers("mgr-1")
    mgr2 = make_bursar_manager_headers("mgr-2")

    requested = validate_success(
        api.write_off(acc, {"action": "REQUEST", "reason": "Uncollectible"},
                      mgr1),
        200,
    )
    assert requested["writeoff_status"] == "PENDING"

    # The requesting manager cannot approve their own request.
    res = api.write_off(acc, {"action": "APPROVE"}, mgr1)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                   expected_status=403)

    # A different manager approves: WRITE_OFF entry zeroes the account.
    approved = validate_success(
        api.write_off(acc, {"action": "APPROVE"}, mgr2), 200
    )
    assert approved["status"] == "WRITTEN_OFF"
    assert approved["writeoff_status"] == "APPROVED"
    # Balance at approval was 330000 + 16500 collections fee = 346500.
    assert approved["balance_cents"] == 0
    assert approved["writeoffs_total_cents"] == 346500
    account = read_account(acc)
    assert account["balance_cents"] == 0
    assert account["status"] == "WRITTEN_OFF"

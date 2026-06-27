"""Calculations (settlement amount, SOL dual-anchor, cadence input filtering) and
validation rejections (arrangement linkage, invalid offer, missing user context).

All tests translate corner-design (queue B) instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    set_clock,
    setup_working_account,
    propose_arrangement,
    post_payment,
    log_phone_attempt,
    refresh_account,
    create_communication_attempt_payload,
    create_arrangement_payload,
    TEST_USERS,
)

COLLECTOR = TEST_USERS["collector_headers"]


# ===========================================================================
# calculations / settlement_amount_computed_at_accept
# ===========================================================================
def test_settlement_amount_computed_at_accept():
    """PRD §3.6: "When a settlement is accepted, its `settlement_amount_cents` is
    computed as the account's `balance_cents` multiplied by `offer_pct_bps`, divided
    by 10,000, rounded half up to whole cents."

    Design: Corner/calculations/settlement_amount_computed_at_accept
    """
    # balance 100000, charge_off recent (age<180 -> age_floor 7000),
    # balance<$10000 -> balance_floor 6000; floor max=7000; offer 7000 == floor allowed.
    ctx = setup_working_account(
        clock="2026-01-01T00:00:00Z",
        account_overrides={
            "original_principal_cents": 100000,
            "charge_off_date": "2025-12-01T00:00:00Z",
        },
    )
    arr = propose_arrangement(ctx["account"]["id"], "SETTLEMENT", offer_pct_bps=7000)
    accepted = validate_success(api_client.accept_arrangement(arr["id"], COLLECTOR), 200)
    assert accepted["status"] == "ACCEPTED"
    # round_half_up(100000 * 7000 / 10000) = 70000
    assert accepted["settlement_amount_cents"] == 70000


# ===========================================================================
# calculations / sol_dual_anchor_last_payment_not_barred
# ===========================================================================
def test_sol_dual_anchor_last_payment_not_barred():
    """PRD §3.2: "The anchor instant is chosen by `sol_anchor_basis`: under
    `CHARGE_OFF` the anchor is the immutable `charge_off_date`; under `LAST_PAYMENT`
    the anchor is the account's `last_payment_date`, or the `charge_off_date` if no
    payment has ever posted. The expiry instant is the anchor plus `sol_years` whole
    years."

    Design: Corner/calculations/sol_dual_anchor_last_payment_not_barred
    """
    # charge_off 2020-01-01, sol_years 4, LAST_PAYMENT basis. Post a 5000 payment at
    # clock 2025-06-01 -> last_payment_date 2025-06-01 -> expiry 2029-06-01.
    # Advance clock to 2026-01-01: not barred under LAST_PAYMENT.
    ctx = setup_working_account(
        clock="2025-06-01T00:00:00Z",
        account_overrides={
            "original_principal_cents": 100000,
            "charge_off_date": "2020-01-01T00:00:00Z",
            "sol_years": 4,
            "sol_anchor_basis": "LAST_PAYMENT",
        },
    )
    get_success_data(post_payment(ctx["account"]["id"], 5000))
    set_clock("2026-01-01T00:00:00Z")
    acct = refresh_account(ctx)
    assert acct["last_payment_date"].startswith("2025-06-01T00:00:00")
    assert acct["time_barred"] is False


# ===========================================================================
# calculations / letter_attempt_does_not_count_toward_cadence
# ===========================================================================
def test_letter_attempt_does_not_count_toward_cadence():
    """PRD §3.5: "Each attempt carries a computed `counts_toward_cadence` flag, which
    is true for a `PHONE` attempt with outcome `LOGGED` or `CONVERSATION` and false
    for any `LETTER` or `EMAIL` attempt and for any `CANCELLED` attempt."

    Design: Corner/calculations/letter_attempt_does_not_count_toward_cadence
    """
    ctx = setup_working_account(clock="2026-03-01T15:00:00Z",
                                account_overrides={"original_principal_cents": 100000})
    res = api_client.create_communication_attempt(
        create_communication_attempt_payload(
            ctx["account"]["id"], "LETTER", "2026-03-01T15:00:00Z", "LOGGED"
        ),
        COLLECTOR,
    )
    attempt = validate_success(res, 201)
    assert attempt["counts_toward_cadence"] is False
    acct = refresh_account(ctx)
    assert acct["attempts_in_window_count"] == 0


# ===========================================================================
# validations / payment_arrangement_id_not_accepted_rejected
# ===========================================================================
def test_payment_arrangement_id_not_accepted_rejected():
    """PRD §3.7: "When supplied, the `arrangement_id` must reference an `ACCEPTED`
    arrangement on the same account; a payment whose arrangement reference is to a
    non-accepted arrangement, or to an arrangement on a different account, is rejected
    with `ERR_ARRANGEMENT_NOT_ACCEPTED`."

    Design: Corner/validations/payment_arrangement_id_not_accepted_rejected
    """
    ctx = setup_working_account(clock="2026-01-01T00:00:00Z",
                                account_overrides={"original_principal_cents": 100000})
    arr = propose_arrangement(ctx["account"]["id"], "PLAN")  # still PROPOSED
    res = api_client.create_payment(
        {"account_id": ctx["account"]["id"], "amount_cents": 1000, "arrangement_id": arr["id"]},
        COLLECTOR,
    )
    validate_error(res, ApiErrorId.ERR_ARRANGEMENT_NOT_ACCEPTED.value)


# ===========================================================================
# validations / invalid_offer_pct_bps_rejected
# ===========================================================================
def test_invalid_offer_pct_bps_rejected():
    """PRD §2.10: "a settlement offer expressed in basis points must lie between 1 and
    10,000 inclusive ... a body that fails any of these yields `ERR_INVALID_REQUEST`."

    Design: Corner/validations/invalid_offer_pct_bps_rejected
    """
    ctx = setup_working_account(clock="2026-01-01T00:00:00Z",
                                account_overrides={"original_principal_cents": 100000})
    res = api_client.create_arrangement(
        create_arrangement_payload(ctx["account"]["id"], "SETTLEMENT", offer_pct_bps=0),
        COLLECTOR,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# validations / missing_user_context_header_rejected
# ===========================================================================
def test_unknown_role_rejected_missing_user_context():
    """PRD §2.1: "If either header is missing or malformed, or if `X-User-Role` names
    a value that is not one of these five roles, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/missing_user_context_header_rejected
    """
    from test_helpers import build_user_headers
    bad_headers = build_user_headers("someone", "NotARole")
    res = api_client.list_accounts(bad_headers)
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

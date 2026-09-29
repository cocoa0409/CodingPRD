"""
Priority conflicts inside one request: the §2.8 admission order decides which of two
simultaneously violated rules is reported.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACCOUNT_POSTURE_LOCKED,
    ERR_BELOW_MIN_TRANSFER,
    ERR_INSUFFICIENT_POINTS,
    ERR_OFFER_OUT_OF_PARITY,
)
from test_helpers.assertions import assert_account_aggregates, assert_page
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS, APPROVER_HEADERS
from test_helpers.types import (
    OFFER_OPEN,
    PARITY_OUT,
    POSTURE_CLEAR,
    POSTURE_LOCKED,
    SIGNAL_DEVICE_CHANGE,
    SIGNAL_NEW_PAYEE,
)


def _locked_account_with_a_high_minimum_agreement(api):
    """A locked account and an agreement whose `min_transfer_points` is 5,000."""
    account, cardholder = fx.funded_account(api, 20000)
    agreement = fx.active_agreement(
        api,
        ADMIN_HEADERS,
        APPROVER_HEADERS,
        partner_name="Skyward Miles",
        partner_program_code="SKYW",
        min_transfer_points=5000,
        transfer_increment_points=1000,
    )
    case = fx.open_case(
        api,
        account["id"],
        ANALYST_HEADERS,
        signals=[SIGNAL_DEVICE_CHANGE, SIGNAL_NEW_PAYEE],
        device_fingerprint_changed=True,
    )
    fx.review_case(api, case["id"], ANALYST_HEADERS)
    fx.confirm_case(api, case["id"], APPROVER_HEADERS)
    locked = fx.read_account(api, account["id"])
    assert locked["fraud_posture"] == POSTURE_LOCKED
    return locked, cardholder, agreement


def test_posture_lock_outranks_the_below_minimum_transfer_amount_check(api):
    """
    "a mid-flight posture lock must surface as `ERR_ACCOUNT_POSTURE_LOCKED` rather
    than being masked by a later insufficient-points check, and a stale version must
    surface before any state check."

    Design: Difficulty/priority_pair_validation_conflict/priority_posture_locked_outranks_below_min_transfer
    """
    locked, cardholder, agreement = _locked_account_with_a_high_minimum_agreement(api)

    response = api.create_transfer(
        f.transfer_payload(
            account_id=locked["id"],
            partner_agreement_id=agreement["id"],
            points_out=1000,
            expected_account_version=locked["version"],
        ),
        cardholder,
    )
    error = validate_error(response, ERR_ACCOUNT_POSTURE_LOCKED, 409)
    assert error["error_id"] != ERR_BELOW_MIN_TRANSFER


def test_the_refused_transfer_creates_no_row_and_moves_no_points(api):
    """
    "The account must be `ACTIVE` and not `LOCKED`, the agreement must be `ACTIVE`,
    and the burn must be within available points."

    Design: Difficulty/priority_pair_validation_conflict/priority_posture_locked_outranks_below_min_transfer
    """
    locked, cardholder, agreement = _locked_account_with_a_high_minimum_agreement(api)

    api.create_transfer(
        f.transfer_payload(
            account_id=locked["id"],
            partner_agreement_id=agreement["id"],
            points_out=1000,
            expected_account_version=locked["version"],
        ),
        cardholder,
    )

    assert_page(
        api.list_transfers(ADMIN_HEADERS, {"account_id": locked["id"]}),
        total_count=0,
        length=0,
    )
    assert_account_aggregates(
        fx.read_account(api, locked["id"]),
        points_balance=20000,
        points_pending_redemption=0,
        fraud_posture=POSTURE_LOCKED,
    )


def _out_of_parity_offer_and_a_pointless_cardholder(api):
    """A 4000 bps markup with zero tolerance, and an account holding no points."""
    account, cardholder = fx.funded_account(api, 0)
    _, offer, _ = fx.agency_with_offer(
        api,
        ADMIN_HEADERS,
        agency={"contracted_markup_bps": 4000, "parity_tolerance_bps": 0},
        net_rate_cents=40000,
        agency_public_price_cents=50000,
        agency_public_seats=3,
        portal_seats=2,
        tax_cents=0,
    )
    return account, cardholder, offer


def test_the_parity_verdict_is_computed_from_the_offers_own_figures(api):
    """
    "The price ceiling is the offer's `agency_public_price_cents` multiplied by one
    plus the agency's `parity_tolerance_bps` divided by 10,000, rounded half up to
    whole cents; the price limb passes when `portal_price_cents` is less than or equal
    to that ceiling."

    Design: Difficulty/priority_pair_validation_conflict/priority_out_of_parity_outranks_insufficient_points
    """
    _, _, offer = _out_of_parity_offer_and_a_pointless_cardholder(api)

    assert offer["portal_price_cents"] == 56000
    assert offer["parity_status"] == PARITY_OUT
    assert offer["status"] == OFFER_OPEN
    assert offer["seats_committed"] == 0


def test_out_of_parity_outranks_the_insufficient_points_check(api):
    """
    "**Business safety.** The addressed offer is in parity
    (`ERR_OFFER_OUT_OF_PARITY`, 409) ... **Fiscal.** Insufficient available points
    (`ERR_INSUFFICIENT_POINTS`, 402)"

    Design: Difficulty/priority_pair_validation_conflict/priority_out_of_parity_outranks_insufficient_points
    """
    account, cardholder, offer = _out_of_parity_offer_and_a_pointless_cardholder(api)

    response = api.book_offer(
        offer["id"],
        f.book_payload(
            account_id=account["id"], expected_offer_version=offer["version"]
        ),
        cardholder,
    )
    error = validate_error(response, ERR_OFFER_OUT_OF_PARITY, 409)
    assert error["error_id"] != ERR_INSUFFICIENT_POINTS

    assert_page(
        api.list_orders(ADMIN_HEADERS, {"account_id": account["id"]}),
        total_count=0,
        length=0,
    )
    untouched = fx.read_offer(api, offer["id"])
    assert untouched["status"] == OFFER_OPEN
    assert untouched["seats_committed"] == 0


def test_the_masked_minimum_check_answers_on_its_own_once_the_posture_is_clear(api):
    """
    "`points_out` must be strictly positive, must be at least the agreement's
    `min_transfer_points` — otherwise `ERR_BELOW_MIN_TRANSFER` (HTTP 422) ..."

    Design: Difficulty/priority_pair_validation_conflict/priority_posture_locked_outranks_below_min_transfer
    """
    account, cardholder = fx.funded_account(
        api,
        20000,
        cardholder_name="Ravi Lund",
        email="ravi@example.com",
        enrolled_at="2025-02-01T00:00:00.000Z",
    )
    agreement = fx.active_agreement(
        api,
        ADMIN_HEADERS,
        APPROVER_HEADERS,
        partner_name="Skyward Miles",
        partner_program_code="SKYW",
        min_transfer_points=5000,
        transfer_increment_points=1000,
    )
    clear = fx.read_account(api, account["id"])
    assert clear["fraud_posture"] == POSTURE_CLEAR

    response = api.create_transfer(
        f.transfer_payload(
            account_id=clear["id"],
            partner_agreement_id=agreement["id"],
            points_out=1000,
            expected_account_version=clear["version"],
        ),
        cardholder,
    )
    error = validate_error(response, ERR_BELOW_MIN_TRANSFER, 422)
    assert error["error_id"] != ERR_ACCOUNT_POSTURE_LOCKED

    assert_page(
        api.list_transfers(ADMIN_HEADERS, {"account_id": clear["id"]}),
        total_count=0,
        length=0,
    )
    assert_account_aggregates(
        fx.read_account(api, clear["id"]),
        points_balance=20000,
        points_pending_redemption=0,
        fraud_posture=POSTURE_CLEAR,
    )

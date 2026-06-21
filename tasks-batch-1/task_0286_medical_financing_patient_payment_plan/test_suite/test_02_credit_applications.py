"""Credit-application submission, the underwriting decision, and account minting.

Queue A (Difficulty) — dual_variant_calc / credit_decision_provisional_vs_final_haircut.
Queue B (Corner)     — entities (computed/system fields, ssn uniqueness),
                       calculations (zero-line auto-decline), state_machines.
"""
import re
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    is_valid_uuid,
    create_credit_application_payload,
    TEST_USERS,
    set_clock,
    setup_defaulted_account,
)

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ───────────────────────── Queue A: dual_variant_calc ─────────────────────────
def test_credit_decision_provisional_income_band_only(api):
    """PRD §3.2: "The system first computes an income-band ceiling by multiplying
    `stated_annual_income_cents` by the income multiplier of 0.20 and taking the floor
    of the product. It then takes the smallest of three numbers — the requested limit,
    that income-band ceiling, and the absolute cap of 2,500,000 cents — as the
    provisional limit."
    PRD §3.2: "The provisional variant never inspects the applicant's history and never
    applies a haircut."

    For income 6,000,000 and request 1,500,000 the provisional line is the income band
    1,200,000 (no haircut), identical to the figure the haircut test starts from.

    Design: Difficulty/dual_variant_calc/credit_decision_provisional_vs_final_haircut
    """
    set_clock("2026-01-01T00:00:00Z")
    res = api.create_credit_application(
        create_credit_application_payload(
            applicant_full_name="Provisional Only", applicant_ssn_last4="2901",
            stated_annual_income_cents=6_000_000, requested_limit_cents=1_500_000),
        ANON)
    app = validate_success(res, 201)
    assert app["provisional_limit_cents"] == 1_200_000


def test_credit_decision_final_haircut_below_provisional(api):
    """PRD §3.2: "The system counts the applicant's prior defaults as the number of
    `PatientAccount` records whose `account_holder_name` equals this application's
    `applicant_full_name` and whose status is `DEFAULTED`. The haircut is the base figure
    multiplied by 0.25 per prior default".
    PRD §3.2: "Because of the haircut, an applicant with prior defaults receives a final
    line strictly smaller than the provisional estimate computed from the same income and
    request."

    Holder "Dee Fault" has one prior DEFAULTED account; for income 6,000,000 / request
    1,500,000 the base 1,200,000 is cut by 0.25 → approved 900,000 < provisional 1,200,000.

    Design: Difficulty/dual_variant_calc/credit_decision_provisional_vs_final_haircut
    """
    # One prior DEFAULTED account for holder "Dee Fault".
    setup_defaulted_account(applicant_full_name="Dee Fault")

    res = api.create_credit_application(
        create_credit_application_payload(
            applicant_full_name="Dee Fault", applicant_ssn_last4="2902",
            stated_annual_income_cents=6_000_000, requested_limit_cents=1_500_000),
        ANON)
    new_app = validate_success(res, 201)
    assert new_app["provisional_limit_cents"] == 1_200_000

    approved = validate_success(api.approve_credit_application(new_app["id"], ADMIN), 200)
    assert approved["approved_limit_cents"] == 900_000
    assert approved["approved_limit_cents"] < new_app["provisional_limit_cents"]


# ───────────────────────── Queue B: corner instances ─────────────────────────
def test_credit_application_provisional_computed_input_ignored(api):
    """PRD §3.2: "A submitted application starts in `SUBMITTED` status and immediately
    receives a pre-qualification estimate stored in `provisional_limit_cents`."
    PRD §3.2: "It then takes the smallest of three numbers — the requested limit, that
    income-band ceiling, and the absolute cap of 2,500,000 cents — as the provisional
    limit."

    Design: Corner/entities/credit_application_provisional_computed_input_ignored
    """
    res = api.create_credit_application(
        create_credit_application_payload(
            applicant_full_name="Comp Pat", applicant_ssn_last4="2201",
            stated_annual_income_cents=6_000_000, requested_limit_cents=1_500_000),
        ANON)
    app = validate_success(res, 201)
    assert app["provisional_limit_cents"] == 1_200_000
    assert app["status"] == "SUBMITTED"
    assert app["approved_limit_cents"] is None


def test_account_id_is_uuid_without_type_prefix(api):
    """PRD §2.4: "carries a server-minted `id` formatted as a UUID with no type prefix".
    PRD §3.2: "the system mints a `PatientAccount`: it is created `ACTIVE`, with
    `credit_limit_cents` copied from `approved_limit_cents`, `available_credit_cents`
    equal to that same limit, `current_balance_cents` of zero, and `delinquency_strikes`
    of zero."

    Design: Corner/entities/account_id_is_uuid_without_type_prefix
    """
    app = validate_success(api.create_credit_application(
        create_credit_application_payload(
            applicant_full_name="Uuid Pat", applicant_ssn_last4="2202",
            stated_annual_income_cents=6_000_000, requested_limit_cents=500_000),
        ANON), 201)
    approved = validate_success(api.approve_credit_application(app["id"], ADMIN), 200)
    account_id = approved["patient_account_id"]
    assert re.match(r"^[0-9a-f-]{36}$", account_id), "account id must be a bare UUID"
    assert is_valid_uuid(account_id)
    account = validate_success(api.get_account(account_id, ADMIN), 200)
    assert account["version"] == 1
    assert account["current_balance_cents"] == 0


def test_duplicate_ssn_last4_among_non_declined_returns_duplicate(api):
    """PRD §3.2: "The `applicant_ssn_last4` must be unique among applications that are
    not `DECLINED`; a collision is rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/entities/duplicate_ssn_last4_among_non_declined_returns_duplicate
    """
    api.create_credit_application(
        create_credit_application_payload(
            applicant_full_name="Ssn A", applicant_ssn_last4="2203",
            stated_annual_income_cents=6_000_000, requested_limit_cents=500_000),
        ANON)
    res = api.create_credit_application(
        create_credit_application_payload(
            applicant_full_name="Ssn B", applicant_ssn_last4="2203",
            stated_annual_income_cents=6_000_000, requested_limit_cents=500_000),
        ANON)
    validate_error(res, "ERR_DUPLICATE_RESOURCE", expected_status=409)


def test_zero_line_application_approve_auto_declines(api):
    """PRD §3.2: "if that result falls below the minimum viable line of 50,000 cents, the
    approved figure is set to zero."
    PRD §3.2: "When the final variant instead yields a zero line, approve resolves not by
    minting an account but by auto-declining: `approved_limit_cents` is set to zero and
    the application moves to `DECLINED`."

    Income 200,000 → income band floor(200,000*0.20)=40,000 < 50,000 → provisional 0 and
    final 0, so approve auto-declines with no account minted.

    Design: Corner/calculations/zero_line_application_approve_auto_declines
    """
    app = validate_success(api.create_credit_application(
        create_credit_application_payload(
            applicant_full_name="Zero Pat", applicant_ssn_last4="4405",
            stated_annual_income_cents=200_000, requested_limit_cents=100_000),
        ANON), 201)
    assert app["provisional_limit_cents"] == 0
    declined = validate_success(api.approve_credit_application(app["id"], ADMIN), 200)
    assert declined["status"] == "DECLINED"
    assert declined["approved_limit_cents"] == 0
    assert declined["patient_account_id"] is None

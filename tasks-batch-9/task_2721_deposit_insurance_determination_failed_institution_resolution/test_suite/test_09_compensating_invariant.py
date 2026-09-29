"""Reversals that must leave the ledger exactly where they found it.

Superseding a certified determination unwinds the insurance side — certificate,
holds and notice — and a voided dividend round unwinds the cash side.  Both are
checked against the signed conservation deltas, which read zero before and after,
so no half-reversal can hide behind a compensating error.
"""
from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_account_dimensions,
    assert_certificate,
    assert_fields_equal,
    assert_instant,
)

SUPERSESSION_REASON = "Trust beneficiary documentation arrived after certification"


def _nadia_certified_estate(client):
    """Nadia's estate certified, held and certificated, with no dividend yet paid."""
    return X.certified_pooled_estate(
        client,
        cert_number="34582",
        legal_name="Spokane Compensation Bank",
        depositor_name="Nadia Farouk",
    )


def test_superseding_a_certified_determination_unwinds_certificate_holds_and_notice(client):
    """Opening a fresh determination for an already-certified depositor supersedes the
    old one, cancels its certificate without deleting it, releases both holds and
    resets the notice to pending.

    PRD: "**Second**, because that determination is now superseded, the receivership certificate it issued moves `ISSUED` → `CANCELLED` ... **Third**, because the certificate was cancelled, every deposit account whose `held_amount_cents` was allocated by the superseded determination moves `hold_status` `HELD` → `RELEASED` with `held_amount_cents` reset to zero. **Fourth**, because those holds are gone, the depositor's `notice_status` resets to `PENDING` and `notice_template_code`, `notice_sent_at` and `acknowledged_at` all reset to unset."

    Design: Difficulty/compensating_invariant/supersede_determination_restores_insurance_conservation_identity
    """
    estate = _nadia_certified_estate(client)
    depositor_id = estate["depositor"]["id"]

    reopened = X.open_determination(
        client, depositor_id, revision_reason=SUPERSESSION_REASON
    )
    assert_fields_equal(
        reopened,
        {"status": "DRAFT", "revision_round": 1, "insured_amount_cents": 0},
    )

    superseded = X.get_determination(client, estate["determination"]["id"])
    assert superseded["status"] == "SUPERSEDED"

    depositor = X.get_depositor(client, depositor_id)
    assert_fields_equal(
        depositor,
        {
            "certified_insured_cents": 0,
            "certified_uninsured_cents": 0,
            "notice_status": "PENDING",
            "notice_template_code": None,
            "notice_sent_at": None,
            "acknowledged_at": None,
        },
    )

    # The certificate is cancelled, never removed, and keeps its face amount.
    assert_certificate(
        X.get_certificate(client, estate["certificate"]["id"]),
        "CANCELLED",
        C.CERT_FACE_LARGE_CENTS,
        cumulative_dividends_cents=0,
    )

    # Holds are released; the insurance dimension is not rewound.
    for account_id in (estate["account_a"]["id"], estate["account_b"]["id"]):
        assert_account_dimensions(
            X.get_account(client, account_id),
            "DETERMINED",
            "RELEASED",
            "PENDING",
            held_amount_cents=0,
        )


def test_the_insurance_identity_reads_zero_before_and_after_a_supersession(client):
    """Every aggregate returns exactly to its pre-certification value and the deposit
    base is untouched, so the conservation delta is zero on both sides of the reversal.

    PRD: "because the institution's aggregates are recomputed from scratch rather than adjusted, `total_deposit_balance_cents` is conserved and `aggregate_insured_cents` and `aggregate_certificate_face_cents` both return exactly to their pre-certification values, leaving the conservation deltas of §2.8 at zero"

    Design: Difficulty/compensating_invariant/supersede_determination_restores_insurance_conservation_identity
    """
    estate = _nadia_certified_estate(client)
    institution_id = estate["institution"]["id"]

    before = X.insurance_summary(client, institution_id)
    assert_fields_equal(
        before,
        {
            "conservation_delta_cents": 0,
            "aggregate_insured_cents": C.POOLED_INSURED_CENTS,
            "aggregate_certificate_face_cents": C.CERT_FACE_LARGE_CENTS,
            "uninsured_claim_count": 1,
            "held_amount_total_cents": C.POOLED_UNINSURED_CENTS,
            "total_deposit_balance_cents": C.POOLED_ATTRIBUTED_CENTS,
        },
    )

    X.open_determination(
        client, estate["depositor"]["id"], revision_reason=SUPERSESSION_REASON
    )

    after = X.insurance_summary(client, institution_id)
    assert_fields_equal(
        after,
        {
            "conservation_delta_cents": 0,
            "aggregate_insured_cents": 0,
            "aggregate_certificate_face_cents": 0,
            "uninsured_claim_count": 0,
            "held_amount_total_cents": 0,
            "total_deposit_balance_cents": C.POOLED_ATTRIBUTED_CENTS,
        },
    )


# ---------------------------------------------------------------------------
# The other conserved quantity: receivership cash
# ---------------------------------------------------------------------------
SETTLED_PAYOUT_CENTS = 1999800
CASH_AFTER_SETTLEMENT_CENTS = 2000200
CASH_AFTER_VOID_CENTS = 4000000
GROSS_PROCEEDS_CENTS = 5000000
DISPOSITION_EXPENSE_CENTS = 1000000
BOTH_FACES_CENTS = C.CERT_FACE_LARGE_CENTS + C.CERT_FACE_SMALL_CENTS


def _umpqua_settled_round(client):
    """Two certificated claimants and one settled general-unsecured round."""
    return X.estate_with_settled_general_unsecured_round(
        client,
        cert_number="34583",
        legal_name="Umpqua Estate Bank",
        charter_state="OR",
    )


def test_voiding_a_round_returns_the_cash_and_reopens_both_certificates(client):
    """Voiding the settled round subtracts each certificate's last payment, resets its
    dividend history to zero, returns both to `ISSUED`, restores the estate's cash and
    still keeps the voided round's distributed total for audit.

    PRD: "The round itself moves `status` `SETTLED` → the terminal `VOIDED`, stamps `voided_at` from the logical clock, and **keeps** its `total_distributed_cents` for audit rather than zeroing it. On the institution, `receivership_cash_cents` is recomputed and returns to its pre-settlement value"

    Design: Difficulty/compensating_invariant/void_dividend_round_restores_receivership_cash_conservation
    """
    estate = _umpqua_settled_round(client)

    voided = X.void_dividend(client, estate["round"]["id"])
    assert_fields_equal(
        voided,
        {
            "status": "VOIDED",
            "distribution_round": 1,
            "total_distributed_cents": SETTLED_PAYOUT_CENTS,
            "certificate_count": 2,
        },
    )
    assert_instant(voided["voided_at"], C.SETUP_CLOCK)

    institution = X.get_institution(client, estate["institution"]["id"])
    assert_fields_equal(
        institution,
        {
            "receivership_cash_cents": CASH_AFTER_VOID_CENTS,
            "gross_disposition_proceeds_cents": GROSS_PROCEEDS_CENTS,
            "disposition_expense_total_cents": DISPOSITION_EXPENSE_CENTS,
        },
    )

    for certificate_key, face in (
        ("alice_certificate", C.CERT_FACE_LARGE_CENTS),
        ("bob_certificate", C.CERT_FACE_SMALL_CENTS),
    ):
        assert_certificate(
            X.get_certificate(client, estate[certificate_key]["id"]),
            "ISSUED",
            face,
            cumulative_dividends_cents=0,
            last_dividend_amount_cents=0,
            last_dividend_round=0,
        )


def test_the_cash_identity_reads_zero_before_and_after_a_void(client):
    """The cash delta is zero once the round has settled and zero again once it is
    voided, with the paid total moving back into the estate and the proceeds side
    untouched, while the insurance aggregates never move at all.

    PRD: "Its delta, `cash_conservation_delta_cents`, is computed by taking `gross_disposition_proceeds_cents` minus `disposition_expense_total_cents`, then subtracting the sum of three quantities: `receivership_cash_cents`, the total of `cumulative_dividends_cents` over the institution's certificates that are not cancelled, and the total of `total_distributed_cents` over the institution's settled rounds whose `priority_class` is `INSURED_SUBROGATION`. This delta must be zero as well."

    Design: Difficulty/compensating_invariant/void_dividend_round_restores_receivership_cash_conservation
    """
    estate = _umpqua_settled_round(client)
    institution_id = estate["institution"]["id"]

    before = X.insurance_summary(client, institution_id)
    assert_fields_equal(
        before,
        {
            "cash_conservation_delta_cents": 0,
            "receivership_cash_cents": CASH_AFTER_SETTLEMENT_CENTS,
            "dividends_paid_cents": SETTLED_PAYOUT_CENTS,
            "gross_disposition_proceeds_cents": GROSS_PROCEEDS_CENTS,
            "disposition_expense_total_cents": DISPOSITION_EXPENSE_CENTS,
        },
    )

    X.void_dividend(client, estate["round"]["id"])

    after = X.insurance_summary(client, institution_id)
    assert_fields_equal(
        after,
        {
            "cash_conservation_delta_cents": 0,
            "receivership_cash_cents": CASH_AFTER_VOID_CENTS,
            "dividends_paid_cents": 0,
            "gross_disposition_proceeds_cents": GROSS_PROCEEDS_CENTS,
            "disposition_expense_total_cents": DISPOSITION_EXPENSE_CENTS,
            # A cash reversal touches nothing on the insurance side.
            "conservation_delta_cents": 0,
            "aggregate_certificate_face_cents": BOTH_FACES_CENTS,
        },
    )

"""Both figures the API computes two ways: the trust shortage and the case score."""

import pytest

from prd_bench_local_runner.testing import validate_success
from test_helpers import fixtures
from test_helpers.assertions import (
    assert_book_position,
    assert_posture,
    expected_bank_basis_shortage,
    expected_book_figures,
    expected_priority_score,
)

AS_OF_DATE = "2026-07-31"
CLEARED_THROUGH_DATE = "2026-07-20"
FIELDWORK_START = "2026-08-03T09:00:00Z"
FIELDWORK_END = "2026-08-07T17:00:00Z"
AUDITOR = "aud-1"

DIVERGING_LEDGER = [
    {
        "entry_type": "OBLIGATION_OPENED",
        "amount_cents": 500000,
        "effective_date": "2026-07-10",
        "cleared_date": None,
        "transaction_reference": "OBL-4400",
    },
    {
        "entry_type": "DEPOSIT",
        "amount_cents": 500000,
        "effective_date": "2026-07-10",
        "cleared_date": None,
        "transaction_reference": "DEP-4401",
    },
    {
        "entry_type": "DISBURSEMENT",
        "amount_cents": 200000,
        "effective_date": "2026-07-15",
        "cleared_date": "2026-07-16",
        "transaction_reference": "DIS-4402",
    },
]


def _firm_with_diverging_ledger(client):
    """A live escrow account holding one booked-but-uncleared buyer deposit."""
    firm = fixtures.bootstrap_active_brokerage(
        client, name="Harbor Realty Group", broker_name="Dana Broker"
    )
    account = firm["account"]
    for row in DIVERGING_LEDGER:
        fixtures.append_ledger_entry(
            client,
            account["id"],
            row["entry_type"],
            row["amount_cents"],
            row["effective_date"],
            row["transaction_reference"],
            cleared_date=row["cleared_date"],
        )
    return firm


class TestTrustShortageBasisDivergence:
    """The same ledger reconciled on the book basis and on the bank basis."""

    def test_bank_basis_shortage_exceeds_book_basis_by_the_uncleared_deposit(self, client):
        """One ledger, two bases, two shortages five hundred thousand cents apart.

        The PRD says "the same ledger yields a larger shortage on the `BANK`
        basis than on the `BOOK` basis whenever a deposit has been booked but
        not yet cleared, because the book view already lets that deposit offset
        the obligation while the bank view does not."

        Design: Difficulty/dual_variant_calc/trust_shortage_book_basis_vs_bank_basis_diverge_on_one_ledger
        """
        firm = _firm_with_diverging_ledger(client)
        account_id = firm["account"]["id"]

        book_audit = fixtures.schedule_audit(
            client, account_id, AUDITOR, "BOOK", AS_OF_DATE, FIELDWORK_START, FIELDWORK_END
        )
        bank_audit = fixtures.schedule_audit(
            client, account_id, AUDITOR, "BANK", AS_OF_DATE, FIELDWORK_START, FIELDWORK_END
        )
        fixtures.move_clock(client, "2026-08-05T00:00:00Z")

        book = validate_success(
            client.open_fieldwork(book_audit["id"], {}, fixtures.make_auditor_headers(AUDITOR))
        )
        bank = validate_success(
            client.open_fieldwork(
                bank_audit["id"],
                {"bank_statement_balance_cents": 300000, "cleared_through_date": CLEARED_THROUGH_DATE},
                fixtures.make_auditor_headers(AUDITOR),
            )
        )

        expected_book = expected_book_figures(DIVERGING_LEDGER, AS_OF_DATE)[2]
        expected_bank = expected_bank_basis_shortage(
            DIVERGING_LEDGER, AS_OF_DATE, CLEARED_THROUGH_DATE
        )
        assert expected_book == 200000
        assert expected_bank == 700000
        assert book["computed_shortage_cents"] == expected_book
        assert bank["computed_shortage_cents"] == expected_bank
        assert bank["computed_shortage_cents"] - book["computed_shortage_cents"] == 500000
        assert book["status"] == "FIELDWORK"
        assert bank["status"] == "FIELDWORK"

    def test_account_always_carries_the_book_basis_triple_not_the_bank_one(self, client):
        """The stored triple is the unfiltered book view, whatever an audit says.

        The PRD says "The account's stored triple is the **book-basis** view of
        the ledger with no date filter at all, equivalent to reconciling as of
        the sentinel cut-off date `9999-12-31`."

        Design: Difficulty/dual_variant_calc/trust_shortage_book_basis_vs_bank_basis_diverge_on_one_ledger
        """
        firm = _firm_with_diverging_ledger(client)
        account_id = firm["account"]["id"]

        bank_audit = fixtures.schedule_audit(
            client, account_id, AUDITOR, "BANK", AS_OF_DATE, FIELDWORK_START, FIELDWORK_END
        )
        fixtures.move_clock(client, "2026-08-05T00:00:00Z")
        bank = validate_success(
            client.open_fieldwork(
                bank_audit["id"],
                {"bank_statement_balance_cents": 300000, "cleared_through_date": CLEARED_THROUGH_DATE},
                fixtures.make_auditor_headers(AUDITOR),
            )
        )
        assert bank["computed_shortage_cents"] == 700000

        obligation, available, shortage = expected_book_figures(DIVERGING_LEDGER)
        account = fixtures.read_trust_account(client, account_id)
        assert_book_position(account, obligation, available)
        assert account["book_obligation_cents"] == 500000
        assert account["book_available_cents"] == 300000
        assert account["shortage_cents"] == shortage == 200000

    def test_obligations_are_gathered_identically_on_both_bases(self, client):
        """Only the cash side is basis-sensitive; the obligation side is not.

        The PRD says "Obligations are gathered identically on both bases: take
        every `OBLIGATION_OPENED` and `OBLIGATION_RELEASED` entry of the account
        whose `effective_date` falls on or before `as_of_date`, sum the opened
        amounts and subtract the released amounts."

        Design: Difficulty/dual_variant_calc/trust_shortage_book_basis_vs_bank_basis_diverge_on_one_ledger
        """
        firm = _firm_with_diverging_ledger(client)
        account_id = firm["account"]["id"]

        book_audit = fixtures.schedule_audit(
            client, account_id, AUDITOR, "BOOK", AS_OF_DATE, FIELDWORK_START, FIELDWORK_END
        )
        bank_audit = fixtures.schedule_audit(
            client, account_id, AUDITOR, "BANK", AS_OF_DATE, FIELDWORK_START, FIELDWORK_END
        )
        fixtures.move_clock(client, "2026-08-05T00:00:00Z")
        book = validate_success(
            client.open_fieldwork(book_audit["id"], {}, fixtures.make_auditor_headers(AUDITOR))
        )
        bank = validate_success(
            client.open_fieldwork(
                bank_audit["id"],
                {"bank_statement_balance_cents": 300000, "cleared_through_date": CLEARED_THROUGH_DATE},
                fixtures.make_auditor_headers(AUDITOR),
            )
        )

        # The obligation of 500000 is common to both, so each shortage is that
        # obligation less the cash its own basis was willing to see.
        assert 500000 - book["computed_shortage_cents"] == 300000
        assert 500000 - bank["computed_shortage_cents"] == -200000


def _firm_on_watch_with_salesperson(client):
    """A firm graded WATCH by a small shortage, with one active salesperson."""
    firm = fixtures.bootstrap_active_brokerage(
        client, name="Harbor Realty Group", broker_name="Dana Broker"
    )
    salesperson = fixtures.affiliate_new_salesperson(
        client, firm["brokerage"]["id"], firm["broker"]["id"], "Sam Sales"
    )
    fixtures.append_ledger_entry(
        client, firm["account"]["id"], "OBLIGATION_OPENED", 50000, "2026-07-20", "OBL-9001"
    )
    brokerage = fixtures.read_brokerage(client, firm["brokerage"]["id"])
    assert_posture(brokerage, "WATCH")
    assert brokerage["open_shortage_cents"] == 50000
    return {"brokerage": brokerage, "broker": firm["broker"], "salesperson": salesperson}


class TestComplaintPriorityScoreVariants:
    """Intake scores on two terms; investigation scores on four."""

    def test_intake_score_omits_the_posture_bump(self, client):
        """At intake the score is the allegation base plus the harm term only.

        The PRD says "While the complaint is still `SUBMITTED`, the **intake
        variant** applies: the score is the base plus the harm term, capped at
        100 points in total, with the prior and posture terms omitted entirely
        because the commission has not yet verified the respondent's history."

        Design: Difficulty/dual_variant_calc/complaint_priority_intake_variant_omits_posture_bump_investigation_variant_applies_it
        """
        world = _firm_on_watch_with_salesperson(client)
        complaint = fixtures.file_complaint(
            client, world["salesperson"]["id"], "MISREPRESENTATION", 350000, "Ruth Payne"
        )

        expected = expected_priority_score("MISREPRESENTATION", 350000)
        assert expected == 43
        assert complaint["priority_score"] == expected
        assert complaint["status"] == "SUBMITTED"
        # The respondent's firm is on WATCH, yet no bump has been applied.
        assert complaint["respondent_brokerage_id"] == world["brokerage"]["id"]

    def test_investigation_score_adds_prior_discipline_and_the_watch_bump(self, client):
        """Screening into investigation switches the score onto all four terms.

        The PRD says "Once the complaint's `status` is anything other than
        `SUBMITTED`, the **investigation variant** applies: base plus harm plus
        prior plus posture bump, again capped at 100 in total."

        Design: Difficulty/dual_variant_calc/complaint_priority_intake_variant_omits_posture_bump_investigation_variant_applies_it
        """
        world = _firm_on_watch_with_salesperson(client)
        complaint = fixtures.file_complaint(
            client, world["salesperson"]["id"], "MISREPRESENTATION", 350000, "Ruth Payne"
        )
        assert complaint["priority_score"] == 43

        investigated = fixtures.dispose_complaint(
            client, complaint["id"], "INVESTIGATE"
        )

        expected = expected_priority_score(
            "MISREPRESENTATION",
            350000,
            prior_sanction_count=0,
            supervision_posture="WATCH",
            include_prior_and_posture=True,
        )
        assert expected == 48
        assert investigated["priority_score"] == expected
        assert investigated["status"] == "INVESTIGATION"

    def test_the_respondent_moves_under_investigation_while_the_score_shifts(self, client):
        """The variant switch and the respondent's discipline move are one request.

        The PRD says "The server records `screener_user_id` and
        `investigator_user_id` as the acting counsel's `X-User-ID`, and the score
        silently switches to the investigation variant. The respondent's
        `discipline_status` moves from `NONE` or `CLEARED` to
        `UNDER_INVESTIGATION`".

        Design: Difficulty/dual_variant_calc/complaint_priority_intake_variant_omits_posture_bump_investigation_variant_applies_it
        """
        world = _firm_on_watch_with_salesperson(client)
        respondent_id = world["salesperson"]["id"]
        assert fixtures.read_licensee(client, respondent_id)["discipline_status"] == "NONE"

        complaint = fixtures.file_complaint(
            client, respondent_id, "MISREPRESENTATION", 350000, "Ruth Payne"
        )
        fixtures.dispose_complaint(
            client, complaint["id"], "INVESTIGATE"
        )

        assert fixtures.read_licensee(client, respondent_id)["discipline_status"] == (
            "UNDER_INVESTIGATION"
        )
        reread = fixtures.read_complaint(client, complaint["id"])
        assert reread["priority_score"] == 48, (
            "the investigation variant is re-derived on every read of the complaint"
        )

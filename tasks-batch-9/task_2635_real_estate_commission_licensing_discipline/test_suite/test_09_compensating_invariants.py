"""Reversals that restore an invariant without pretending nothing happened."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success
from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_book_position,
    assert_fund_counters,
    assert_fund_identity,
    assert_immutable_row,
    assert_posture,
    expected_assessment_cents,
)
from test_helpers.test_users import (
    SECOND_CHAIR_USER_ID,
    make_analyst_headers,
    make_chair_headers,
)

ORDER_INSTANT = "2026-08-05T09:00:00Z"
SECOND_CLAIM_INSTANT = "2026-08-05T10:00:00Z"
VACATUR_INSTANT = "2026-08-06T09:00:00Z"
FINE_CENTS = 500000
APPROPRIATION_CENTS = 2900000


def _order_with_a_paid_fine_and_a_shaved_disbursement(client):
    """A satisfied revocation order, two part-paid claims and one queued claim."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name="Harbor Realty Group",
        broker_name="Dana Broker",
        trust_account_required=False,
        open_escrow=False,
    )
    respondent = fixtures.affiliate_new_salesperson(
        client, firm["brokerage"]["id"], firm["broker"]["id"], "Rae Field"
    )
    complaint = fixtures.complaint_at_probable_cause(
        client, respondent["id"], "MISREPRESENTATION", 3000000
    )
    outcome = fixtures.issue_order_by_hearing(
        client,
        complaint["id"],
        "chair-01",
        sanction_type="REVOCATION",
        fine_cents=FINE_CENTS,
        suspension_days=0,
        scheduled_start_at=ORDER_INSTANT,
        scheduled_end_at="2026-08-05T11:00:00Z",
        hearing_room="ROOM-A",
    )
    order = outcome["order"]
    fixtures.pay_fine(client, order["id"], FINE_CENTS, paid_on="2026-08-05")
    fixtures.appropriate(client, APPROPRIATION_CENTS)

    first_claim = fixtures.file_claim(client, order["id"], 2500000, "Ora Buyer")
    fixtures.move_clock(client, SECOND_CLAIM_INSTANT)
    second_claim = fixtures.file_claim(client, order["id"], 1000000, "Ivo Renter")
    run = validate_success(fixtures.disburse(client, order["id"]))
    third_claim = fixtures.file_claim(client, order["id"], 300000, "Lex Tenant")
    return {
        "brokerage_id": firm["brokerage"]["id"],
        "respondent": respondent,
        "complaint": complaint,
        "order": order,
        "run": run,
        "claims": [first_claim, second_claim, third_claim],
    }


def _claims_by_id(client, order_id):
    return {claim["id"]: claim for claim in fixtures.claims_for_order(client, order_id)}


def _vacate(client, order_id):
    return client.vacate_order(
        order_id,
        make_chair_headers(SECOND_CHAIR_USER_ID),
        factories.vacatur_payload("Reconsidered on the record."),
    )


class TestVacaturRestoresTheFundIdentity:
    """The clawback offsets the awards; the assessment stays spent."""

    def test_the_shaved_run_leaves_the_identity_holding(self, client):
        """The re-pass shaves the last claim only, and the identity still holds.

        The PRD says "If the balance minus the pass total minus the assessment
        would fall below the 500,000-cent floor, the shortfall is computed, and
        the **last claim in `created_at` ascending order** — never an earlier one
        — has its award reduced by the smaller of that shortfall and its own
        award."

        Design: Difficulty/compensating_invariant/vacatur_restores_the_recovery_fund_identity_while_the_assessment_stays_spent
        """
        world = _order_with_a_paid_fine_and_a_shaved_disbursement(client)
        run = world["run"]

        assert run["total_awarded_cents"] == 2842000
        assert run["assessment_cents"] == expected_assessment_cents(2842000) == 56840
        assert run["balance_cents_after"] == 501160
        assert run["shaved_claim_id"] == world["claims"][1]["id"]

        claims = _claims_by_id(client, world["order"]["id"])
        assert claims[world["claims"][0]["id"]]["awarded_cents"] == 2000000
        assert claims[world["claims"][1]["id"]]["awarded_cents"] == 842000
        assert claims[world["claims"][2]["id"]]["status"] == "ELIGIBLE"

        assert_fund_counters(
            fixtures.read_fund(client),
            balance_cents=501160,
            appropriated_cents=APPROPRIATION_CENTS,
            fine_credits_cents=FINE_CENTS,
            clawed_back_cents=0,
            awarded_cents=2842000,
            assessment_cents=56840,
        )

    def test_the_vacatur_reverses_the_credit_and_claws_the_awards_back(self, client):
        """Two different money flows are unwound by two different counters.

        The PRD says "Money returns to the fund through the dedicated clawback
        counter rather than by decrementing `awarded_cents`, so the cumulative
        award history remains visible."

        Design: Difficulty/compensating_invariant/vacatur_restores_the_recovery_fund_identity_while_the_assessment_stays_spent
        """
        world = _order_with_a_paid_fine_and_a_shaved_disbursement(client)
        fixtures.move_clock(client, VACATUR_INSTANT)

        vacated = validate_success(_vacate(client, world["order"]["id"]))
        assert vacated["status"] == "VACATED"
        assert vacated["vacated_at"] == VACATUR_INSTANT
        assert vacated["fine_paid_cents"] == 0
        assert vacated["fund_credited_cents"] == 0

        claims = _claims_by_id(client, world["order"]["id"])
        for paid in world["claims"][:2]:
            assert claims[paid["id"]]["status"] == "CLAWED_BACK"
            assert claims[paid["id"]]["awarded_cents"] == 0
        queued = claims[world["claims"][2]["id"]]
        assert queued["status"] == "DENIED"
        assert queued["denial_reason"] == "ORDER_VACATED"
        assert queued["awarded_cents"] == 0

    def test_the_assessment_is_friction_that_is_never_refunded(self, client):
        """The identity is restored exactly, the balance is not.

        The PRD says "it obeys one invariant at all times: `balance_cents` equals
        `appropriated_cents` plus `fine_credits_cents` plus `clawed_back_cents`,
        minus `awarded_cents` and `assessment_cents`."

        Design: Difficulty/compensating_invariant/vacatur_restores_the_recovery_fund_identity_while_the_assessment_stays_spent
        """
        world = _order_with_a_paid_fine_and_a_shaved_disbursement(client)
        fixtures.move_clock(client, VACATUR_INSTANT)
        validate_success(_vacate(client, world["order"]["id"]))

        fund = fixtures.read_fund(client)
        assert_fund_counters(
            fund,
            fine_credits_cents=0,
            clawed_back_cents=2842000,
            awarded_cents=2842000,
            assessment_cents=56840,
            appropriated_cents=APPROPRIATION_CENTS,
            balance_cents=2843160,
        )
        assert_fund_identity(fund)
        assert fund["balance_cents"] == APPROPRIATION_CENTS - 56840, (
            "the balance lands 56,840 short of the pre-disbursement appropriation"
        )

    def test_the_licence_is_restored_but_the_adjudication_record_stands(self, client):
        """A revocation unwinds to `INACTIVE`, never straight back to `ACTIVE`.

        The PRD says "a respondent in `REVOKED` moves to `INACTIVE` with
        `inactive_since` stamped at the vacatur instant — vacatur restores the
        person's standing but not their active practice rights, so a revoked
        licensee must still reactivate through the §3.4 path, paying the
        reinstatement fee that their time in limbo has accrued."

        Design: Difficulty/compensating_invariant/vacatur_restores_the_recovery_fund_identity_while_the_assessment_stays_spent
        """
        world = _order_with_a_paid_fine_and_a_shaved_disbursement(client)
        assert fixtures.read_licensee(client, world["respondent"]["id"])["license_status"] == (
            "REVOKED"
        )
        fixtures.move_clock(client, VACATUR_INSTANT)
        validate_success(_vacate(client, world["order"]["id"]))

        respondent = fixtures.read_licensee(client, world["respondent"]["id"])
        assert respondent["license_status"] == "INACTIVE"
        assert respondent["inactive_since"] == VACATUR_INSTANT
        assert respondent["discipline_status"] == "CLEARED"
        assert respondent["recovery_paid_cents"] == 0
        assert respondent["prior_sanction_count"] == 0

        assert fixtures.read_complaint(client, world["complaint"]["id"])["status"] == "ADJUDICATED"
        assert_posture(fixtures.read_brokerage(client, world["brokerage_id"]), "COMPLIANT")


OBLIGATION_CENTS = 800000
DEPOSIT_CENTS = 800000
MISPOSTED_CENTS = 150000
DISBURSEMENT_REFERENCE = "DIS-77"
UNKNOWN_REFERENCE = "DIS-99"


def _account_driven_short_by_a_misposted_disbursement(client):
    """A fully funded escrow account, then one disbursement to the wrong payee."""
    firm = fixtures.bootstrap_active_brokerage(
        client, name="Harbor Realty Group", broker_name="Dana Broker"
    )
    account_id = firm["account"]["id"]
    fixtures.append_ledger_entry(
        client, account_id, "OBLIGATION_OPENED", OBLIGATION_CENTS, "2026-08-01", "OBL-77"
    )
    fixtures.append_ledger_entry(
        client,
        account_id,
        "DEPOSIT",
        DEPOSIT_CENTS,
        "2026-08-01",
        "DEP-77",
        cleared_date="2026-08-01",
    )
    funded = fixtures.read_trust_account(client, account_id)
    assert_book_position(funded, OBLIGATION_CENTS, DEPOSIT_CENTS)
    assert_posture(fixtures.read_brokerage(client, firm["brokerage"]["id"]), "COMPLIANT")

    misposted = fixtures.append_ledger_entry(
        client,
        account_id,
        "DISBURSEMENT",
        MISPOSTED_CENTS,
        "2026-08-02",
        DISBURSEMENT_REFERENCE,
        cleared_date="2026-08-02",
        memo="paid to the wrong payee",
    )
    return {
        "brokerage_id": firm["brokerage"]["id"],
        "account_id": account_id,
        "misposted": misposted,
    }


def _append_correction(client, account_id, transaction_reference, memo):
    return client.create_ledger_entry(
        account_id,
        factories.ledger_entry_payload(
            "CORRECTION",
            MISPOSTED_CENTS,
            "2026-08-03",
            transaction_reference,
            fixtures.read_trust_account(client, account_id)["version"],
            cleared_date="2026-08-03",
            memo=memo,
        ),
        make_analyst_headers(),
    )


class TestCorrectionRestoresTheBookPositionWithoutRewritingHistory:
    """The only legal reversal is another row, and it must name a real target."""

    def test_the_misposted_disbursement_drives_the_firm_into_restriction(self, client):
        """The account itself stays open; only the firm's posture reacts.

        The PRD says "`book_available_cents` is the sum over every `DEPOSIT`, less
        the sum over every `DISBURSEMENT`, plus the sum over every `CORRECTION`."

        Design: Difficulty/compensating_invariant/trust_ledger_correction_restores_book_available_and_the_posture_without_mutating_a_row
        """
        world = _account_driven_short_by_a_misposted_disbursement(client)

        account = fixtures.read_trust_account(client, world["account_id"])
        assert_book_position(account, OBLIGATION_CENTS, 650000)
        assert account["shortage_cents"] == MISPOSTED_CENTS
        assert account["status"] == "OPEN", (
            "only an audit remediation order can restrict the account itself"
        )

        brokerage = fixtures.read_brokerage(client, world["brokerage_id"])
        assert brokerage["open_shortage_cents"] == MISPOSTED_CENTS
        assert_posture(brokerage, "RESTRICTED")

    def test_a_correction_naming_no_real_disbursement_is_refused(self, client):
        """The compensation cannot be forged out of an invented reference.

        The PRD says "which is why a correction must name the
        `transaction_reference` of an existing `DISBURSEMENT` on the same account;
        if no such disbursement exists, the append is refused with
        `ERR_CORRECTION_TARGET_NOT_FOUND`."

        Design: Difficulty/compensating_invariant/trust_ledger_correction_restores_book_available_and_the_posture_without_mutating_a_row
        """
        world = _account_driven_short_by_a_misposted_disbursement(client)
        account_id = world["account_id"]

        validate_error(
            _append_correction(client, account_id, UNKNOWN_REFERENCE, "forged compensation"),
            "ERR_CORRECTION_TARGET_NOT_FOUND",
            expected_status=422,
        )

        account = fixtures.read_trust_account(client, account_id)
        assert account["book_available_cents"] == 650000
        assert account["shortage_cents"] == MISPOSTED_CENTS
        entries, _meta = validate_paginated(
            client.list_ledger_entries(account_id, make_analyst_headers())
        )
        assert len(entries) == 3, "a refused append writes no row"

    def test_the_correction_restores_the_book_position_and_the_posture(self, client):
        """Reusing the disbursement's own reference puts the cash back.

        The PRD says "A `CORRECTION` reverses a booking error, and it **always
        adds to cash** — it is the compensating entry for a mistaken
        disbursement".

        Design: Difficulty/compensating_invariant/trust_ledger_correction_restores_book_available_and_the_posture_without_mutating_a_row
        """
        world = _account_driven_short_by_a_misposted_disbursement(client)
        account_id = world["account_id"]

        correction = validate_success(
            _append_correction(
                client, account_id, DISBURSEMENT_REFERENCE, "funds recovered from the payee"
            ),
            expected_status=201,
        )
        assert correction["entry_type"] == "CORRECTION"
        assert correction["amount_cents"] == MISPOSTED_CENTS
        assert correction["transaction_reference"] == DISBURSEMENT_REFERENCE

        account = fixtures.read_trust_account(client, account_id)
        assert_book_position(account, OBLIGATION_CENTS, DEPOSIT_CENTS)
        assert account["shortage_cents"] == 0

        brokerage = fixtures.read_brokerage(client, world["brokerage_id"])
        assert brokerage["open_shortage_cents"] == 0
        assert_posture(brokerage, "COMPLIANT")

    def test_the_reversed_row_survives_untouched_in_append_order(self, client):
        """History is added to, never edited: four rows, oldest first.

        The PRD says "Because history is never rewritten, a correction is the only
        way to fix a misposting."

        Design: Difficulty/compensating_invariant/trust_ledger_correction_restores_book_available_and_the_posture_without_mutating_a_row
        """
        world = _account_driven_short_by_a_misposted_disbursement(client)
        account_id = world["account_id"]
        _append_correction(
            client, account_id, DISBURSEMENT_REFERENCE, "funds recovered from the payee"
        )

        entries, meta = validate_paginated(
            client.list_ledger_entries(account_id, make_analyst_headers())
        )
        assert meta["total_count"] == 4
        assert [entry["entry_type"] for entry in entries] == [
            "OBLIGATION_OPENED",
            "DEPOSIT",
            "DISBURSEMENT",
            "CORRECTION",
        ]
        assert [entry["created_at"] for entry in entries] == sorted(
            entry["created_at"] for entry in entries
        ), "the listing is in created_at ascending order"

        original = next(entry for entry in entries if entry["id"] == world["misposted"]["id"])
        assert original["entry_type"] == "DISBURSEMENT"
        assert original["amount_cents"] == MISPOSTED_CENTS
        for entry in entries:
            assert_immutable_row(entry)

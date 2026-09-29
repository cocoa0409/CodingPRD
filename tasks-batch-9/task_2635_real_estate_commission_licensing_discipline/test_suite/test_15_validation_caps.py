"""Caps and bars that are scoped narrower — or wider — than they first appear."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_ACCOUNT_RESTRICTED_NO_DISBURSEMENT,
    ERR_INVALID_STATE,
    ERR_LICENSEE_CAP_EXHAUSTED,
    ERR_NO_ELIGIBLE_CLAIMS,
    ERR_PAYMENT_EXCEEDS_BALANCE,
    ERR_SUPERVISION_RATIO_EXCEEDED,
    ERR_TRUST_ACCOUNT_CLOSED,
)
from test_helpers.assertions import (
    assert_book_position,
    assert_fund_counters,
    assert_posture,
    expected_assessment_cents,
)
from test_helpers.constants import CLOCK_STARTUP_DEFAULT
from test_helpers.test_users import (
    make_analyst_headers,
    make_auditor_headers,
    make_counsel_headers,
    make_salesperson_headers,
    make_trustee_headers,
)

FIRM_NAME = "Harbor Realty Group"
BROKER_NAME = "Dana Broker"
SALESPERSON_NAME = "Sam Reed"
AUDITOR = "auditor-11"
AS_OF_DATE = "2026-08-31"
FIELDWORK_START = "2026-08-01T00:00:00Z"
FIELDWORK_END = "2026-08-01T17:00:00Z"
BOOK_DATE = "2026-08-01"
OBLIGATION_CENTS = 1000000
DEPOSIT_CENTS = 850000
DISBURSED_CENTS = 50000
SMALL_DISBURSEMENT_CENTS = 1000


def _append_raw(client, account_id, entry_type, amount_cents, reference, cleared_date=None):
    account = fixtures.read_trust_account(client, account_id)
    return client.create_ledger_entry(
        account_id,
        factories.ledger_entry_payload(
            entry_type,
            amount_cents,
            BOOK_DATE,
            reference,
            account["version"],
            cleared_date=cleared_date,
        ),
        make_analyst_headers(),
    )


def _account_under_a_remediation_order(client):
    """Two hundred thousand cents missing, an order issued, the account restricted."""
    firm = fixtures.bootstrap_active_brokerage(client, name=FIRM_NAME, broker_name=BROKER_NAME)
    account_id = firm["account"]["id"]
    fixtures.append_ledger_entry(
        client, account_id, "OBLIGATION_OPENED", OBLIGATION_CENTS, BOOK_DATE, "OBL-01"
    )
    fixtures.append_ledger_entry(
        client, account_id, "DEPOSIT", DEPOSIT_CENTS, BOOK_DATE, "DEP-01", cleared_date=BOOK_DATE
    )
    fixtures.append_ledger_entry(
        client, account_id, "DISBURSEMENT", DISBURSED_CENTS, BOOK_DATE, "DIS-01"
    )
    audit = fixtures.schedule_audit(
        client, account_id, AUDITOR, "BOOK", AS_OF_DATE, FIELDWORK_START, FIELDWORK_END
    )
    fieldwork = fixtures.start_fieldwork(client, audit["id"], AUDITOR)
    assert fieldwork["computed_shortage_cents"] == 200000
    ordered = fixtures.dispose_audit(
        client, audit["id"], AUDITOR, "ISSUE_FINDINGS", remediation_days=3
    )
    assert ordered["status"] == "REMEDIATION_ORDERED"
    return {"firm": firm, "account_id": account_id, "audit_id": audit["id"]}


class TestARemediationOrderBarsOnlyDisbursements:
    """Four entry classes keep flowing while the fifth is shut off."""

    def test_the_restriction_refuses_a_disbursement_and_consumes_no_version(self, client):
        """The bar rejects the entry outright, leaving the account's version intact.

        The PRD says "An account whose `status` is `RESTRICTED` — the condition a
        remediation order puts it in — accepts everything **except** a
        `DISBURSEMENT`, which is refused with
        `ERR_ACCOUNT_RESTRICTED_NO_DISBURSEMENT`."

        Design: Corner/validations/a_remediation_order_bars_only_disbursements_from_the_restricted_account
        """
        world = _account_under_a_remediation_order(client)
        restricted = fixtures.read_trust_account(client, world["account_id"])
        assert restricted["status"] == "RESTRICTED"
        assert_book_position(restricted, OBLIGATION_CENTS, 800000)
        assert_posture(
            fixtures.read_brokerage(client, world["firm"]["brokerage"]["id"]), "RESTRICTED"
        )

        validate_error(
            _append_raw(
                client,
                world["account_id"],
                "DISBURSEMENT",
                SMALL_DISBURSEMENT_CENTS,
                "DIS-02",
            ),
            ERR_ACCOUNT_RESTRICTED_NO_DISBURSEMENT,
            expected_status=409,
        )

        untouched = fixtures.read_trust_account(client, world["account_id"])
        assert untouched["version"] == restricted["version"]

    def test_corrections_and_obligation_entries_still_append(self, client):
        """The firm may still fund the shortage and book its obligations.

        The PRD says "`DEPOSIT`, `CORRECTION`, `OBLIGATION_OPENED` and
        `OBLIGATION_RELEASED` all continue to append normally on a restricted
        account, deliberately: a brokerage under order must still be able to fund the
        shortage it has been told to cure and to book obligations it has already
        incurred to clients."

        Design: Corner/validations/a_remediation_order_bars_only_disbursements_from_the_restricted_account
        """
        world = _account_under_a_remediation_order(client)
        account_id = world["account_id"]
        validate_error(
            _append_raw(client, account_id, "DISBURSEMENT", SMALL_DISBURSEMENT_CENTS, "DIS-02"),
            ERR_ACCOUNT_RESTRICTED_NO_DISBURSEMENT,
        )

        validate_success(
            _append_raw(client, account_id, "CORRECTION", DISBURSED_CENTS, "DIS-01"),
            expected_status=201,
        )
        corrected = fixtures.read_trust_account(client, account_id)
        assert_book_position(corrected, OBLIGATION_CENTS, DEPOSIT_CENTS)
        assert corrected["shortage_cents"] == 150000

        validate_success(
            _append_raw(client, account_id, "OBLIGATION_RELEASED", 150000, "REL-01"),
            expected_status=201,
        )
        released = fixtures.read_trust_account(client, account_id)
        assert_book_position(released, DEPOSIT_CENTS, DEPOSIT_CENTS)
        assert released["shortage_cents"] == 0
        assert released["status"] == "RESTRICTED", "curing the money does not lift the order"

        validate_error(
            _append_raw(client, account_id, "DISBURSEMENT", SMALL_DISBURSEMENT_CENTS, "DIS-02"),
            ERR_ACCOUNT_RESTRICTED_NO_DISBURSEMENT,
        )

    def test_only_the_verified_remediation_reopens_the_disbursement_channel(self, client):
        """The bar is the account's status, and only the audit can clear it.

        The PRD says "A verified shortage of 0 continues `VERIFYING → CLOSED`; the
        account returns `RESTRICTED → OPEN` provided its own `shortage_cents` is 0
        and no other audit on that account is sitting in `REMEDIATION_ORDERED` or
        `ESCALATED`".

        Design: Corner/validations/a_remediation_order_bars_only_disbursements_from_the_restricted_account
        """
        world = _account_under_a_remediation_order(client)
        account_id = world["account_id"]
        fixtures.append_ledger_entry(
            client, account_id, "CORRECTION", DISBURSED_CENTS, BOOK_DATE, "DIS-01"
        )
        fixtures.append_ledger_entry(
            client, account_id, "OBLIGATION_RELEASED", 150000, BOOK_DATE, "REL-01"
        )

        closed = fixtures.dispose_audit(client, world["audit_id"], AUDITOR, "VERIFY_REMEDIATION")
        assert closed["verified_shortage_cents"] == 0
        assert closed["status"] == "CLOSED"
        reopened = fixtures.read_trust_account(client, account_id)
        assert reopened["status"] == "OPEN"
        assert_posture(
            fixtures.read_brokerage(client, world["firm"]["brokerage"]["id"]), "COMPLIANT"
        )

        validate_success(
            _append_raw(client, account_id, "DISBURSEMENT", SMALL_DISBURSEMENT_CENTS, "DIS-02"),
            expected_status=201,
        )
        spent = fixtures.read_trust_account(client, account_id)
        assert_book_position(spent, DEPOSIT_CENTS, 849000)
        assert spent["shortage_cents"] == SMALL_DISBURSEMENT_CENTS
        assert_posture(fixtures.read_brokerage(client, world["firm"]["brokerage"]["id"]), "WATCH")


ALLEGED_LOSS_CENTS = 300000
SCREENER = "counsel-05"
OFFERING_COUNSEL = "counsel-01"
CLEARED_DEPOSIT_CENTS = 100000


def _firm_whose_broker_is_about_to_be_revoked(client):
    """A one-agent firm, a funded escrow account and a case ready to settle."""
    firm = fixtures.bootstrap_active_brokerage(client, name=FIRM_NAME, broker_name=BROKER_NAME)
    account_id = firm["account"]["id"]
    fixtures.append_ledger_entry(
        client,
        account_id,
        "DEPOSIT",
        CLEARED_DEPOSIT_CENTS,
        BOOK_DATE,
        "DEP-01",
        cleared_date=BOOK_DATE,
    )
    broker_id = firm["broker"]["id"]
    complaint = fixtures.complaint_at_probable_cause(
        client, broker_id, "MISREPRESENTATION", ALLEGED_LOSS_CENTS, SCREENER
    )
    agreement = fixtures.offer_consent(
        client, complaint["id"], "REVOCATION", 0, 0, counsel_user_id=OFFERING_COUNSEL
    )
    fixtures.respondent_replies(client, agreement["id"], broker_id, "ACCEPT")
    return {
        "firm": firm,
        "account_id": account_id,
        "broker_id": broker_id,
        "complaint": complaint,
        "agreement": agreement,
    }


def _execute(client, agreement_id):
    return client.commission_action(
        agreement_id,
        factories.commission_action_payload("EXECUTE"),
        make_counsel_headers("counsel-02"),
    )


class TestTheRevocationThatClosesTheBrokerageAlsoClosesItsTrustAccount:
    """One consent execution walks three levels of cascade in a single request."""

    def test_the_execution_revokes_the_broker_and_empties_the_roster(self, client):
        """The order issues, the licence falls, and the computed count follows it.

        The PRD says "Because the respondent is now sanctioned, the licence
        consequence follows: a `SUSPENSION` moves an `ACTIVE` licence to
        `SUSPENDED`, and a `REVOCATION` moves it to `REVOKED`, dragging behind it the
        full instructor-suspension and credit-invalidation chain described in §3.5."

        The PRD says "`affiliated_licensee_count` counts licensees whose
        `sponsoring_brokerage_id` is this brokerage **and** whose `license_status` is
        `ACTIVE` — inactive, suspended and expired affiliates do not count."

        Design: Corner/validations/the_revocation_that_closes_the_brokerage_also_closes_its_trust_account
        """
        world = _firm_whose_broker_is_about_to_be_revoked(client)

        executed = validate_success(_execute(client, world["agreement"]["id"]))
        assert executed["status"] == "EXECUTED"

        order = fixtures.only_order_for_complaint(client, world["complaint"]["id"])
        assert order["source"] == "CONSENT"
        assert order["status"] == "ISSUED"
        assert order["sanction_type"] == "REVOCATION"
        assert order["effective_at"] == CLOCK_STARTUP_DEFAULT

        broker = fixtures.read_licensee(client, world["broker_id"])
        assert broker["license_status"] == "REVOKED"
        assert broker["discipline_status"] == "SANCTIONED"
        assert fixtures.read_brokerage(client, world["firm"]["brokerage"]["id"])[
            "affiliated_licensee_count"
        ] == 0

    def test_the_firm_walks_on_to_closed_and_takes_the_account_with_it(self, client):
        """With no affiliates left, the suspension does not stop at `SUSPENDED`.

        The PRD says "Only after that suspension has been applied, and only when the
        order was a revocation *and* the firm's `affiliated_licensee_count` is 0,
        does the brokerage continue `SUSPENDED → CLOSED` inside the same request;
        when it still has affiliates, it stops at `SUSPENDED`."

        The PRD says "On closure, every trust account of the firm whose
        `shortage_cents` is 0 moves to `CLOSED` and accepts no further ledger
        entries; an account still carrying a shortage stays open so the money can be
        traced."

        Design: Corner/validations/the_revocation_that_closes_the_brokerage_also_closes_its_trust_account
        """
        world = _firm_whose_broker_is_about_to_be_revoked(client)
        validate_success(_execute(client, world["agreement"]["id"]))

        brokerage = fixtures.read_brokerage(client, world["firm"]["brokerage"]["id"])
        assert brokerage["status"] == "CLOSED"
        assert_posture(brokerage, "FROZEN")

        account = fixtures.read_trust_account(client, world["account_id"])
        assert account["status"] == "CLOSED"
        assert_book_position(account, 0, CLEARED_DEPOSIT_CENTS)
        assert account["shortage_cents"] == 0

    def test_both_trust_endpoints_refuse_and_the_firm_cannot_come_back(self, client):
        """The closed account takes nothing more, and closure is the end of the firm.

        The PRD says "An account whose `status` is `CLOSED` accepts nothing at all,
        and the attempt answers `ERR_TRUST_ACCOUNT_CLOSED`."

        The PRD says "Scheduling is refused on a `CLOSED` account with
        `ERR_TRUST_ACCOUNT_CLOSED`, and it computes a shortage figure as a
        convenience preview that is **not persisted** — nothing is frozen until
        fieldwork opens."

        The PRD says "`CLOSED`, by contrast, is terminal."

        Design: Corner/validations/the_revocation_that_closes_the_brokerage_also_closes_its_trust_account
        """
        world = _firm_whose_broker_is_about_to_be_revoked(client)
        validate_success(_execute(client, world["agreement"]["id"]))
        account_id = world["account_id"]

        validate_error(
            _append_raw(client, account_id, "DEPOSIT", 5000, "DEP-02", cleared_date=BOOK_DATE),
            ERR_TRUST_ACCOUNT_CLOSED,
            expected_status=409,
        )
        rows, meta = validate_paginated(
            client.list_ledger_entries(account_id, make_analyst_headers())
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1

        validate_error(
            client.schedule_audit(
                account_id,
                factories.audit_payload(
                    AUDITOR, "BOOK", AS_OF_DATE, FIELDWORK_START, FIELDWORK_END
                ),
                make_auditor_headers(AUDITOR),
            ),
            ERR_TRUST_ACCOUNT_CLOSED,
        )

        validate_error(
            client.activate_brokerage(
                world["firm"]["brokerage"]["id"], make_analyst_headers()
            ),
            ERR_INVALID_STATE,
            expected_status=409,
        )


FINE_CENTS = 500000
FIRST_INSTALMENT_CENTS = 300000
PAID_ON = "2026-08-15"


def _fined_agent(client):
    """Sam Reed under a five-thousand-dollar consent fine, with an empty fund."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    sam = fixtures.affiliate_new_salesperson(
        client, firm["brokerage"]["id"], firm["broker"]["id"], SALESPERSON_NAME
    )
    complaint = fixtures.complaint_at_probable_cause(
        client, sam["id"], "MISREPRESENTATION", ALLEGED_LOSS_CENTS, SCREENER
    )
    order = fixtures.issue_order_by_consent(
        client, complaint["id"], sam["id"], "FINE", FINE_CENTS, 0
    )
    assert order["fine_cents"] == FINE_CENTS
    assert order["fine_paid_cents"] == 0
    fund = fixtures.read_fund(client)
    assert_fund_counters(fund, balance_cents=0, fine_credits_cents=0)
    return {"firm": firm, "sam": sam, "order": order}


def _pay(client, order_id, amount_cents):
    return client.create_fine_payment(
        order_id, factories.fine_payment_payload(amount_cents, PAID_ON), make_analyst_headers()
    )


class TestAFinePaymentIsCappedByTheRemainingBalance:
    """The ceiling moves down with every instalment, and the last cent closes the order."""

    def test_a_payment_one_cent_over_the_ordered_fine_is_refused(self, client):
        """Nothing is credited anywhere when the tender exceeds the balance.

        The PRD says "Payments are accepted against an order in `ISSUED` or
        `IN_DEFAULT`, and may never exceed the outstanding balance: an `amount_cents`
        greater than `fine_cents` minus `fine_paid_cents` is refused with
        `ERR_PAYMENT_EXCEEDS_BALANCE`."

        Design: Corner/validations/a_fine_payment_may_not_exceed_the_outstanding_balance_and_the_last_cent_satisfies_it
        """
        world = _fined_agent(client)

        validate_error(
            _pay(client, world["order"]["id"], FINE_CENTS + 1),
            ERR_PAYMENT_EXCEEDS_BALANCE,
            expected_status=422,
        )

        order = fixtures.read_sanction_order(client, world["order"]["id"])
        assert order["fine_paid_cents"] == 0
        assert order["fund_credited_cents"] == 0
        assert_fund_counters(fixtures.read_fund(client), balance_cents=0, fine_credits_cents=0)

    def test_the_ceiling_is_the_remaining_balance_not_the_ordered_fine(self, client):
        """After three hundred thousand cents land, the ceiling is two hundred thousand.

        The PRD says "Each accepted payment increases `fine_paid_cents` and
        `fund_credited_cents` by the amount, and because **the whole of every fine
        payment is credited to the recovery fund**, it also increases the fund's
        `fine_credits_cents` and `balance_cents` by the same amount and bumps the
        fund's `version` by one."

        Design: Corner/validations/a_fine_payment_may_not_exceed_the_outstanding_balance_and_the_last_cent_satisfies_it
        """
        world = _fined_agent(client)
        order_id = world["order"]["id"]

        part = validate_success(_pay(client, order_id, FIRST_INSTALMENT_CENTS))
        assert part["fine_paid_cents"] == FIRST_INSTALMENT_CENTS
        assert part["fund_credited_cents"] == FIRST_INSTALMENT_CENTS
        assert part["status"] == "ISSUED", "a partial payment does not satisfy the order"
        assert_fund_counters(
            fixtures.read_fund(client),
            balance_cents=FIRST_INSTALMENT_CENTS,
            fine_credits_cents=FIRST_INSTALMENT_CENTS,
        )

        validate_error(
            _pay(client, order_id, FINE_CENTS - FIRST_INSTALMENT_CENTS + 1),
            ERR_PAYMENT_EXCEEDS_BALANCE,
        )
        assert fixtures.read_sanction_order(client, order_id)["fine_paid_cents"] == (
            FIRST_INSTALMENT_CENTS
        )

    def test_the_exact_remainder_satisfies_the_order(self, client):
        """Paying out the balance flips the order and squares the fund identity.

        The PRD says "The order becomes `SATISFIED` only once `fine_paid_cents` has
        reached `fine_cents`; a partial payment leaves the order in whatever state it
        was already in, so a partially paid order in `IN_DEFAULT` stays in
        `IN_DEFAULT`."

        Design: Corner/validations/a_fine_payment_may_not_exceed_the_outstanding_balance_and_the_last_cent_satisfies_it
        """
        world = _fined_agent(client)
        order_id = world["order"]["id"]
        fixtures.pay_fine(client, order_id, FIRST_INSTALMENT_CENTS, PAID_ON)

        settled = validate_success(_pay(client, order_id, FINE_CENTS - FIRST_INSTALMENT_CENTS))
        assert settled["fine_paid_cents"] == FINE_CENTS
        assert settled["status"] == "SATISFIED"

        assert_fund_counters(
            fixtures.read_fund(client),
            balance_cents=FINE_CENTS,
            fine_credits_cents=FINE_CENTS,
            appropriated_cents=0,
            awarded_cents=0,
            assessment_cents=0,
            clawed_back_cents=0,
        )

    def test_the_trailing_cent_meets_the_from_state_check_instead(self, client):
        """Once the order is satisfied the fiscal rule never gets a turn.

        The PRD says "The target row must currently be in a state from which the
        requested transition is declared, including action-specific origins:
        verifying remediation requires `REMEDIATION_ORDERED`, executing a consent
        agreement requires `ACCEPTED`, convening requires `SCHEDULED`, and a manual
        escalation additionally requires a `remediation_round` of at least 2, so
        escalating a first-round remediation order by hand answers with this same
        error."

        Design: Corner/validations/a_fine_payment_may_not_exceed_the_outstanding_balance_and_the_last_cent_satisfies_it
        """
        world = _fined_agent(client)
        order_id = world["order"]["id"]
        fixtures.pay_fine(client, order_id, FIRST_INSTALMENT_CENTS, PAID_ON)
        fixtures.pay_fine(client, order_id, FINE_CENTS - FIRST_INSTALMENT_CENTS, PAID_ON)

        validate_error(_pay(client, order_id, 1), ERR_INVALID_STATE, expected_status=409)

        order = fixtures.read_sanction_order(client, order_id)
        assert order["status"] == "SATISFIED"
        assert order["fine_paid_cents"] == FINE_CENTS
        assert_fund_counters(
            fixtures.read_fund(client), balance_cents=FINE_CENTS, fine_credits_cents=FINE_CENTS
        )


APPROPRIATION_CENTS = 6000000
PER_LICENSEE_CAP_CENTS = 5000000
CLAIM_AMOUNTS_CENTS = (2000000, 2000000, 1000000)
SECOND_AGENT_NAME = "Rae Field"


def _two_orders_and_three_queued_claims(client):
    """Sam's suspension order carries three claims; Rae's reprimand carries none."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    brokerage_id = firm["brokerage"]["id"]
    broker_id = firm["broker"]["id"]
    sam = fixtures.affiliate_new_salesperson(client, brokerage_id, broker_id, SALESPERSON_NAME)
    rae = fixtures.affiliate_new_salesperson(client, brokerage_id, broker_id, SECOND_AGENT_NAME)
    fixtures.appropriate(client, APPROPRIATION_CENTS)

    sam_case = fixtures.complaint_at_probable_cause(
        client, sam["id"], "MISREPRESENTATION", ALLEGED_LOSS_CENTS, SCREENER
    )
    sam_order = fixtures.issue_order_by_consent(
        client, sam_case["id"], sam["id"], "SUSPENSION", 0, 30
    )
    rae_case = fixtures.complaint_at_probable_cause(
        client, rae["id"], "MISREPRESENTATION", ALLEGED_LOSS_CENTS, SCREENER
    )
    rae_order = fixtures.issue_order_by_consent(
        client, rae_case["id"], rae["id"], "REPRIMAND", 0, 0
    )

    claims = []
    for index, amount in enumerate(CLAIM_AMOUNTS_CENTS, start=1):
        claim = fixtures.file_claim(client, sam_order["id"], amount, f"Claimant {index}")
        assert claim["status"] == "ELIGIBLE"
        claims.append(claim)
    return {
        "sam": sam,
        "rae": rae,
        "sam_order": sam_order,
        "rae_order": rae_order,
        "claims": claims,
    }


def _file_claim_raw(client, order_id, claimed_loss_cents, claimant_name):
    return client.create_recovery_claim(
        order_id,
        factories.recovery_claim_payload(claimed_loss_cents, claimant_name),
        make_trustee_headers(),
    )


class TestTheLicenseeCapAndAnEmptyCandidateSetAreDifferentRefusals:
    """Three lawful awards exhaust one licensee's lifetime headroom."""

    def test_the_first_run_pays_all_three_claims_to_the_licensee_ceiling(self, client):
        """Each claim is under the per-claim cap, and together they reach the per-licensee cap.

        The PRD says "The award for that claim is the smallest of four figures — its
        remaining need, its remaining per-claim headroom, the licensee's remaining
        headroom and the remaining distributable cash — floored at zero so that an
        exhausted budget yields nothing rather than a negative number."

        The PRD says "The response reports the run rather than a stored row:
        `total_awarded_cents`, `assessment_cents`, `balance_cents_after`,
        `fund_version`, `paid_claim_count`, `partially_paid_claim_count` and
        `shaved_claim_id`, the last of which names the claim reduced by the re-pass
        and is null when no shave occurred."

        Design: Corner/validations/the_licensee_cap_and_an_empty_candidate_set_are_two_different_refusals_of_the_same_run
        """
        world = _two_orders_and_three_queued_claims(client)

        run = validate_success(fixtures.disburse(client, world["sam_order"]["id"]))
        assert run["total_awarded_cents"] == PER_LICENSEE_CAP_CENTS
        assert run["assessment_cents"] == expected_assessment_cents(PER_LICENSEE_CAP_CENTS)
        assert run["assessment_cents"] == 100000
        assert run["balance_cents_after"] == 900000
        assert run["paid_claim_count"] == 3
        assert run["partially_paid_claim_count"] == 0
        assert run["shaved_claim_id"] is None, "the reserve floor was never threatened"

        paid = fixtures.claims_for_order(client, world["sam_order"]["id"])
        assert [claim["awarded_cents"] for claim in paid] == list(CLAIM_AMOUNTS_CENTS)
        assert {claim["status"] for claim in paid} == {"PAID"}
        assert {claim["paid_at"] for claim in paid} == {CLOCK_STARTUP_DEFAULT}
        assert fixtures.read_licensee(client, world["sam"]["id"])["recovery_paid_cents"] == (
            PER_LICENSEE_CAP_CENTS
        )

    def test_a_fourth_claim_files_but_the_second_run_hits_the_licensee_cap(self, client):
        """The cap bars the payout, not the filing, and the fund is not short of cash.

        The PRD says "Three gates are checked before any allocation happens: the
        fund's `balance_cents` must exceed the 500,000-cent reserve floor, otherwise
        `ERR_FUND_RESERVE_FLOOR`; the respondent's `recovery_paid_cents` must be
        strictly below the 5,000,000-cent per-licensee cap, otherwise
        `ERR_LICENSEE_CAP_EXHAUSTED`; and there must be at least one candidate claim
        **and** the computed total award must be greater than zero, otherwise
        `ERR_NO_ELIGIBLE_CLAIMS`."

        Design: Corner/validations/the_licensee_cap_and_an_empty_candidate_set_are_two_different_refusals_of_the_same_run
        """
        world = _two_orders_and_three_queued_claims(client)
        validate_success(fixtures.disburse(client, world["sam_order"]["id"]))
        fund_after_first_run = fixtures.read_fund(client)
        assert fund_after_first_run["balance_cents"] == 900000

        late = validate_success(
            _file_claim_raw(client, world["sam_order"]["id"], 1000000, "Claimant 4"),
            expected_status=201,
        )
        assert late["status"] == "ELIGIBLE"

        validate_error(
            fixtures.disburse(client, world["sam_order"]["id"]),
            ERR_LICENSEE_CAP_EXHAUSTED,
            expected_status=409,
        )

        still_queued = [
            claim
            for claim in fixtures.claims_for_order(client, world["sam_order"]["id"])
            if claim["id"] == late["id"]
        ][0]
        assert still_queued["status"] == "ELIGIBLE"
        assert still_queued["awarded_cents"] == 0
        fund = fixtures.read_fund(client)
        assert fund["balance_cents"] == 900000
        assert fund["version"] == fund_after_first_run["version"]

    def test_a_reprimand_order_yields_an_auto_denied_claim_and_an_empty_run(self, client):
        """A non-disciplinary order leaves no candidate for the waterfall to pay.

        The PRD says "Otherwise it becomes `DENIED` with a `denial_reason` naming the
        defect: `ORDER_NOT_DISCIPLINARY` when the `sanction_type` is `REPRIMAND` or
        `PROBATION`, `WINDOW_CLOSED` when the 365-day window has elapsed, and
        `ORDER_VACATED` when the order has already been vacated."

        The PRD says "A denied claim never enters a disbursement run."

        Design: Corner/validations/the_licensee_cap_and_an_empty_candidate_set_are_two_different_refusals_of_the_same_run
        """
        world = _two_orders_and_three_queued_claims(client)
        validate_success(fixtures.disburse(client, world["sam_order"]["id"]))
        fund_after_first_run = fixtures.read_fund(client)

        denied = validate_success(
            _file_claim_raw(client, world["rae_order"]["id"], 1000000, "Claimant 5"),
            expected_status=201,
        )
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "ORDER_NOT_DISCIPLINARY"
        assert denied["awarded_cents"] == 0

        validate_error(
            fixtures.disburse(client, world["rae_order"]["id"]),
            ERR_NO_ELIGIBLE_CLAIMS,
            expected_status=409,
        )

        fund = fixtures.read_fund(client)
        assert fund["balance_cents"] == 900000
        assert fund["version"] == fund_after_first_run["version"]


RATIO_CEILING = 25


def _brokerage_filled_to_the_ceiling(client):
    """The broker plus twenty-four salespeople: twenty-five seats, all taken."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    brokerage_id = firm["brokerage"]["id"]
    broker_id = firm["broker"]["id"]
    seated = []
    for index in range(1, RATIO_CEILING):
        agent = fixtures.affiliate_new_salesperson(
            client, brokerage_id, broker_id, f"Agent {index:02d}"
        )
        assert agent["license_status"] == "ACTIVE"
        seated.append(agent)
    full = fixtures.read_brokerage(client, brokerage_id)
    assert full["affiliated_licensee_count"] == RATIO_CEILING
    return {"firm": firm, "brokerage_id": brokerage_id, "broker_id": broker_id, "seated": seated}


def _affiliate_raw(client, licensee_id, brokerage_id, supervising_broker_id):
    brokerage = fixtures.read_brokerage(client, brokerage_id)
    return client.create_affiliation(
        licensee_id,
        factories.affiliation_payload(
            brokerage_id, supervising_broker_id, brokerage["version"]
        ),
        make_analyst_headers(),
    )


class TestTwentyFiveLawfulAffiliationsCloseTheFirmToTheTwentySixth:
    """Only the collective count trips the rule, and it is measured before the seat is taken."""

    def test_the_twenty_sixth_candidate_is_refused_by_the_ratio_alone(self, client):
        """Every seated affiliation was legal; the count is what refuses this one.

        The PRD says "Its `affiliated_licensee_count`, measured **before** this
        affiliation is applied, must be strictly below the supervision ratio ceiling
        of 25 active affiliates per firm, or the request is refused with
        `ERR_SUPERVISION_RATIO_EXCEEDED`; a firm sitting at exactly 25 is full."

        Design: Corner/validations/twenty_five_individually_legal_affiliations_close_the_brokerage_to_the_twenty_sixth
        """
        world = _brokerage_filled_to_the_ceiling(client)
        candidate = fixtures.create_exam_passed_licensee(client, "SALESPERSON", "Late Arrival")

        validate_error(
            _affiliate_raw(
                client, candidate["id"], world["brokerage_id"], world["broker_id"]
            ),
            ERR_SUPERVISION_RATIO_EXCEEDED,
            expected_status=409,
        )

        assert fixtures.read_licensee(client, candidate["id"])["license_status"] == "EXAM_PASSED"
        firm = fixtures.read_brokerage(client, world["brokerage_id"])
        assert firm["affiliated_licensee_count"] == RATIO_CEILING
        assert_posture(firm, "COMPLIANT")

    def test_parking_one_licence_reopens_the_seat_for_the_refused_candidate(self, client):
        """The ceiling is measured against a computed count, so a parked agent frees a seat.

        The PRD says "`affiliated_licensee_count` counts licensees whose
        `sponsoring_brokerage_id` is this brokerage **and** whose `license_status` is
        `ACTIVE` — inactive, suspended and expired affiliates do not count."

        The PRD says "The firm the licensee has left has its
        `affiliated_licensee_count` and `supervision_posture` recomputed."

        Design: Corner/validations/twenty_five_individually_legal_affiliations_close_the_brokerage_to_the_twenty_sixth
        """
        world = _brokerage_filled_to_the_ceiling(client)
        candidate = fixtures.create_exam_passed_licensee(client, "SALESPERSON", "Late Arrival")
        validate_error(
            _affiliate_raw(client, candidate["id"], world["brokerage_id"], world["broker_id"]),
            ERR_SUPERVISION_RATIO_EXCEEDED,
        )

        leaver = world["seated"][0]
        parked = fixtures.go_inactive(
            client, leaver["id"], make_salesperson_headers(leaver["id"])
        )
        assert parked["license_status"] == "INACTIVE"
        assert fixtures.read_brokerage(client, world["brokerage_id"])[
            "affiliated_licensee_count"
        ] == RATIO_CEILING - 1

        seated = validate_success(
            _affiliate_raw(client, candidate["id"], world["brokerage_id"], world["broker_id"])
        )
        assert seated["license_status"] == "ACTIVE"
        assert seated["sponsoring_brokerage_id"] == world["brokerage_id"]
        assert fixtures.read_brokerage(client, world["brokerage_id"])[
            "affiliated_licensee_count"
        ] == RATIO_CEILING

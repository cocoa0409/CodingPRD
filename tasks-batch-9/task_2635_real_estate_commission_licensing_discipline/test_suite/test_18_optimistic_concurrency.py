"""Three parents, three stale views, and one bump per successful write."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_BROKERAGE_VERSION_CONFLICT,
    ERR_RECOVERY_FUND_VERSION_CONFLICT,
    ERR_TRUST_ACCOUNT_VERSION_CONFLICT,
)
from test_helpers.assertions import (
    assert_fund_counters,
    assert_posture,
    expected_assessment_cents,
)
from test_helpers.test_users import make_analyst_headers, make_trustee_headers

FIRM_NAME = "Harbor Realty Group"
BROKER_NAME = "Dana Broker"
FIRST_DEPOSIT_CENTS = 400000
SECOND_DEPOSIT_CENTS = 250000
BOTH_DEPOSITS_CENTS = 650000
BOOK_DATE = "2026-08-01"


def _account_after_one_deposit(client):
    """An escrow account carrying one cleared deposit, plus the version it started from."""
    firm = fixtures.bootstrap_active_brokerage(
        client, name=FIRM_NAME, broker_name=BROKER_NAME
    )
    account_id = firm["account"]["id"]
    version_before = fixtures.read_trust_account(client, account_id)["version"]

    fixtures.append_ledger_entry(
        client, account_id, "DEPOSIT", FIRST_DEPOSIT_CENTS, BOOK_DATE, "DEP-1",
        cleared_date=BOOK_DATE, expected_trust_account_version=version_before,
    )
    banked = fixtures.read_trust_account(client, account_id)
    assert banked["book_available_cents"] == FIRST_DEPOSIT_CENTS
    return {
        "account_id": account_id,
        "version_before": version_before,
        "version_after": banked["version"],
    }


def _replay(client, account_id, expected_version):
    """The second deposit, offered against whichever version the caller names."""
    return client.create_ledger_entry(
        account_id,
        factories.ledger_entry_payload(
            "DEPOSIT",
            SECOND_DEPOSIT_CENTS,
            BOOK_DATE,
            "DEP-2",
            expected_version,
            cleared_date=BOOK_DATE,
        ),
        make_analyst_headers(),
    )


class TestAStaleTrustAccountVersionIsRefusedAndTheRefreshedOneAppends:
    """Appends are repeatable, so only the parent version stands between two of them."""

    def test_replaying_the_version_of_one_append_ago_is_refused_with_no_side_effect(
        self, client
    ):
        """The amount, the entry type and the reference were all acceptable.

        The PRD says "If the supplied value does not equal the account's current
        `version` — because an earlier append, or an audit cascade, has advanced it
        since the client read the account — the append is rejected with
        `ERR_TRUST_ACCOUNT_VERSION_CONFLICT` (HTTP 412) and nothing is written."

        Design: Corner/cross_cutting_complexity_layers/a_stale_trust_account_version_is_refused_and_the_refreshed_one_appends
        """
        world = _account_after_one_deposit(client)

        validate_error(
            _replay(client, world["account_id"], world["version_before"]),
            ERR_TRUST_ACCOUNT_VERSION_CONFLICT,
            expected_status=412,
        )

        account = fixtures.read_trust_account(client, world["account_id"])
        assert account["book_available_cents"] == FIRST_DEPOSIT_CENTS
        _rows, meta = validate_paginated(
            client.list_ledger_entries(world["account_id"], make_analyst_headers())
        )
        assert meta["total_count"] == 1

    def test_only_a_successful_write_moves_the_version(self, client):
        """One bump for the append that landed, none for the one that was refused.

        The PRD says "Appending a trust ledger entry requires
        `expected_trust_account_version` in the request body, carrying the client's
        last observed `version` of the parent `TrustAccount`. It is not optional."

        Design: Corner/cross_cutting_complexity_layers/a_stale_trust_account_version_is_refused_and_the_refreshed_one_appends
        """
        world = _account_after_one_deposit(client)
        assert world["version_after"] == world["version_before"] + 1

        validate_error(
            _replay(client, world["account_id"], world["version_before"]),
            ERR_TRUST_ACCOUNT_VERSION_CONFLICT,
        )
        assert fixtures.read_trust_account(client, world["account_id"])["version"] == (
            world["version_after"]
        )

        validate_success(
            _replay(client, world["account_id"], world["version_after"]),
            expected_status=201,
        )
        assert fixtures.read_trust_account(client, world["account_id"])["version"] == (
            world["version_after"] + 1
        )

    def test_the_identical_body_appends_once_the_version_is_refreshed(self, client):
        """Nothing about the entry was wrong, so the refreshed offer lands.

        The PRD says "A `Broker` or a `LicensingAnalyst` adds one immutable entry at
        a time, supplying the `entry_type`, an `amount_cents` magnitude, the book
        date the entry hits the brokerage's own ledger as `effective_date`,
        optionally the bank clearing date as `cleared_date`, a brokerage-side
        `transaction_reference`, an optional free-text `memo`, and the
        `expected_trust_account_version` required by §2.7."

        Design: Corner/cross_cutting_complexity_layers/a_stale_trust_account_version_is_refused_and_the_refreshed_one_appends
        """
        world = _account_after_one_deposit(client)
        validate_error(
            _replay(client, world["account_id"], world["version_before"]),
            ERR_TRUST_ACCOUNT_VERSION_CONFLICT,
        )

        appended = validate_success(
            _replay(client, world["account_id"], world["version_after"]),
            expected_status=201,
        )
        assert appended["transaction_reference"] == "DEP-2"

        account = fixtures.read_trust_account(client, world["account_id"])
        assert account["book_available_cents"] == BOTH_DEPOSITS_CENTS
        _rows, meta = validate_paginated(
            client.list_ledger_entries(world["account_id"], make_analyst_headers())
        )
        assert meta["total_count"] == 2


SECOND_AGENT_NAME = "Rae Nunez"
FIRST_AGENT_NAME = "Sam Reed"


def _active_firm_with_two_waiting_candidates(client):
    """A firm whose broker has not yet affiliated, and two examined candidates."""
    broker = fixtures.create_exam_passed_licensee(client, "BROKER", BROKER_NAME)
    brokerage = fixtures.register_brokerage(client, broker["id"], FIRM_NAME)
    fixtures.open_trust_account(client, brokerage["id"])
    activated = fixtures.activate(client, brokerage["id"])
    assert activated["status"] == "ACTIVE"

    sam = fixtures.create_exam_passed_licensee(client, "SALESPERSON", FIRST_AGENT_NAME)
    rae = fixtures.create_exam_passed_licensee(client, "SALESPERSON", SECOND_AGENT_NAME)
    assert sam["license_status"] == "EXAM_PASSED"
    assert rae["license_status"] == "EXAM_PASSED"

    return {
        "broker": broker,
        "brokerage_id": brokerage["id"],
        "activation_version": activated["version"],
        "sam": sam,
        "rae": rae,
    }


def _offer_affiliation(client, world, licensee_id, expected_brokerage_version):
    """Seat one licensee under the firm's designated broker at a named version."""
    return client.create_affiliation(
        licensee_id,
        factories.affiliation_payload(
            world["brokerage_id"], world["broker"]["id"], expected_brokerage_version
        ),
        make_analyst_headers(),
    )


class TestAStaleBrokerageVersionIsRefusedBecauseAnEarlierAffiliationMovedIt:
    """The client's own previous affiliation is what invalidates its captured version."""

    def test_the_activation_era_version_is_spent_by_the_brokers_own_bootstrap(self, client):
        """One affiliation succeeded on that version; the next one cannot reuse it.

        The PRD says "Affiliating or transferring a licensee requires
        `expected_brokerage_version` in the request body, carrying the client's last
        observed `version` of the **target** `Brokerage`. A mismatch with that
        brokerage's current `version` is rejected with
        `ERR_BROKERAGE_VERSION_CONFLICT` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/a_stale_brokerage_version_is_refused_because_an_earlier_affiliation_moved_it
        """
        world = _active_firm_with_two_waiting_candidates(client)

        seated = validate_success(
            _offer_affiliation(
                client, world, world["broker"]["id"], world["activation_version"]
            )
        )
        assert seated["license_status"] == "ACTIVE"
        assert fixtures.read_brokerage(client, world["brokerage_id"])[
            "affiliated_licensee_count"
        ] == 1

        validate_error(
            _offer_affiliation(
                client, world, world["sam"]["id"], world["activation_version"]
            ),
            ERR_BROKERAGE_VERSION_CONFLICT,
            expected_status=412,
        )

        refused = fixtures.read_licensee(client, world["sam"]["id"])
        assert refused["license_status"] == "EXAM_PASSED"
        assert refused["sponsoring_brokerage_id"] is None
        assert fixtures.read_brokerage(client, world["brokerage_id"])[
            "affiliated_licensee_count"
        ] == 1

    def test_the_parent_moved_exactly_once_and_the_refreshed_version_is_accepted(
        self, client
    ):
        """The broker's affiliation, and nothing else, advanced the firm.

        The PRD says "This is what pins the supervision-ratio headroom the client
        believed it observed: a prior affiliation, an activation or any
        posture-bearing cascade advances the brokerage's `version` and invalidates
        the stale view."

        Design: Corner/cross_cutting_complexity_layers/a_stale_brokerage_version_is_refused_because_an_earlier_affiliation_moved_it
        """
        world = _active_firm_with_two_waiting_candidates(client)
        validate_success(
            _offer_affiliation(
                client, world, world["broker"]["id"], world["activation_version"]
            )
        )

        after_bootstrap = fixtures.read_brokerage(client, world["brokerage_id"])["version"]
        assert after_bootstrap == world["activation_version"] + 1

        validate_error(
            _offer_affiliation(client, world, world["sam"]["id"], world["activation_version"]),
            ERR_BROKERAGE_VERSION_CONFLICT,
        )
        assert fixtures.read_brokerage(client, world["brokerage_id"])["version"] == (
            after_bootstrap
        ), "the refused affiliation did not move the parent"

        seated = validate_success(
            _offer_affiliation(client, world, world["sam"]["id"], after_bootstrap)
        )
        assert seated["license_status"] == "ACTIVE"
        assert fixtures.read_brokerage(client, world["brokerage_id"])[
            "affiliated_licensee_count"
        ] == 2

    def test_the_staleness_recurs_for_the_third_candidate_for_the_same_reason(self, client):
        """Systematic, not a one-off: every seat taken invalidates the version again.

        The PRD says "Its `affiliated_licensee_count`, measured **before** this
        affiliation is applied, must be strictly below the supervision ratio ceiling
        of 25 active affiliates per firm, or the request is refused with
        `ERR_SUPERVISION_RATIO_EXCEEDED`; a firm sitting at exactly 25 is full."

        Design: Corner/cross_cutting_complexity_layers/a_stale_brokerage_version_is_refused_because_an_earlier_affiliation_moved_it
        """
        world = _active_firm_with_two_waiting_candidates(client)
        validate_success(
            _offer_affiliation(
                client, world, world["broker"]["id"], world["activation_version"]
            )
        )
        after_bootstrap = fixtures.read_brokerage(client, world["brokerage_id"])["version"]
        validate_success(_offer_affiliation(client, world, world["sam"]["id"], after_bootstrap))

        validate_error(
            _offer_affiliation(client, world, world["rae"]["id"], after_bootstrap),
            ERR_BROKERAGE_VERSION_CONFLICT,
            expected_status=412,
        )

        after_sam = fixtures.read_brokerage(client, world["brokerage_id"])["version"]
        assert after_sam == after_bootstrap + 1
        validate_success(_offer_affiliation(client, world, world["rae"]["id"], after_sam))

        firm = fixtures.read_brokerage(client, world["brokerage_id"])
        assert firm["affiliated_licensee_count"] == 3
        assert_posture(firm, "COMPLIANT")


APPROPRIATION_CENTS = 6000000
FINE_CENTS = 500000
INSTALMENT_CENTS = 100000
CLAIM_CENTS = 200000
BALANCE_AFTER_PAYMENT_CENTS = 6100000
BALANCE_AFTER_AWARD_CENTS = 5896000
ALLEGED_LOSS_CENTS = 300000
CLAIMANT_NAME = "Pat Buyer"


def _fund_holding_one_eligible_claim(client):
    """An appropriated fund, one fined salesperson, and one eligible claim on the order."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    sam = fixtures.affiliate_new_salesperson(
        client, firm["brokerage"]["id"], firm["broker"]["id"], FIRST_AGENT_NAME
    )
    complaint = fixtures.complaint_at_probable_cause(
        client, sam["id"], "MISREPRESENTATION", ALLEGED_LOSS_CENTS
    )
    order = fixtures.issue_order_by_consent(
        client, complaint["id"], sam["id"], "FINE", FINE_CENTS, 0
    )

    fixtures.appropriate(client, APPROPRIATION_CENTS)
    claim = fixtures.file_claim(client, order["id"], CLAIM_CENTS, CLAIMANT_NAME)
    assert claim["status"] == "ELIGIBLE"
    assert claim["awarded_cents"] == 0

    fund = fixtures.read_fund(client)
    assert fund["balance_cents"] == APPROPRIATION_CENTS
    return {"sam": sam, "order": order, "claim": claim, "trustee_version": fund["version"]}


def _pay_and_return_the_fund(client, world):
    """The respondent's own instalment, which credits the fund the trustee just read."""
    paid = fixtures.pay_fine(client, world["order"]["id"], INSTALMENT_CENTS)
    assert paid["fine_paid_cents"] == INSTALMENT_CENTS
    fund = fixtures.read_fund(client)
    assert fund["fine_credits_cents"] == INSTALMENT_CENTS
    assert fund["balance_cents"] == BALANCE_AFTER_PAYMENT_CENTS
    return fund


class TestAStaleRecoveryFundVersionIsRefusedBecauseAThirdPartyCreditedTheFund:
    """The trustee's view is invalidated by a different actor on a different endpoint."""

    def test_the_run_holding_the_pre_payment_version_awards_nothing(self, client):
        """A fine payment moved the fund, so the distributable balance is not the one read.

        The PRD says "Running a recovery-fund disbursement requires
        `expected_recovery_fund_version` in the request body, carrying the client's
        last observed `version` of the `RecoveryFund` singleton. A mismatch with the
        fund's current `version` is rejected with
        `ERR_RECOVERY_FUND_VERSION_CONFLICT` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/a_stale_recovery_fund_version_is_refused_because_a_third_party_fine_payment_credited_the_fund
        """
        world = _fund_holding_one_eligible_claim(client)
        _pay_and_return_the_fund(client, world)

        validate_error(
            fixtures.disburse(client, world["order"]["id"], world["trustee_version"]),
            ERR_RECOVERY_FUND_VERSION_CONFLICT,
            expected_status=412,
        )

        claims = fixtures.claims_for_order(client, world["order"]["id"])
        assert len(claims) == 1
        assert claims[0]["status"] == "ELIGIBLE"
        assert claims[0]["awarded_cents"] == 0
        fund = fixtures.read_fund(client)
        assert fund["awarded_cents"] == 0
        assert fund["assessment_cents"] == 0
        assert fund["balance_cents"] == BALANCE_AFTER_PAYMENT_CENTS

    def test_the_payment_bumped_the_fund_once_and_the_refusal_not_at_all(self, client):
        """Only the write that landed advanced the singleton.

        The PRD says "Appropriations, fine credits, clawbacks and earlier
        disbursement runs all advance that `version`, so the distributable balance
        the trustee believed it observed can only be relied on by presenting the
        version it came with."

        Design: Corner/cross_cutting_complexity_layers/a_stale_recovery_fund_version_is_refused_because_a_third_party_fine_payment_credited_the_fund
        """
        world = _fund_holding_one_eligible_claim(client)
        after_payment = _pay_and_return_the_fund(client, world)
        assert after_payment["version"] == world["trustee_version"] + 1

        validate_error(
            fixtures.disburse(client, world["order"]["id"], world["trustee_version"]),
            ERR_RECOVERY_FUND_VERSION_CONFLICT,
        )
        assert fixtures.read_fund(client)["version"] == after_payment["version"]

    def test_the_refreshed_run_pays_the_claim_in_full_out_of_the_larger_balance(self, client):
        """The award, the assessment and every counter settle inside the one run.

        The PRD says "The fund's `awarded_cents` rises by the final total, its
        `assessment_cents` by the final assessment, and its `balance_cents` falls by
        the sum of the two; `version` is bumped once."

        Design: Corner/cross_cutting_complexity_layers/a_stale_recovery_fund_version_is_refused_because_a_third_party_fine_payment_credited_the_fund
        """
        world = _fund_holding_one_eligible_claim(client)
        after_payment = _pay_and_return_the_fund(client, world)
        validate_error(
            fixtures.disburse(client, world["order"]["id"], world["trustee_version"]),
            ERR_RECOVERY_FUND_VERSION_CONFLICT,
        )

        run = validate_success(
            fixtures.disburse(client, world["order"]["id"], after_payment["version"])
        )
        assert run["total_awarded_cents"] == CLAIM_CENTS
        assert run["assessment_cents"] == expected_assessment_cents(CLAIM_CENTS) == 4000
        assert run["balance_cents_after"] == BALANCE_AFTER_AWARD_CENTS
        assert run["paid_claim_count"] == 1
        assert run["partially_paid_claim_count"] == 0
        assert run["shaved_claim_id"] is None
        assert run["fund_version"] == after_payment["version"] + 1

        claims = fixtures.claims_for_order(client, world["order"]["id"])
        assert claims[0]["status"] == "PAID"
        assert claims[0]["awarded_cents"] == CLAIM_CENTS
        assert fixtures.read_licensee(client, world["sam"]["id"])["recovery_paid_cents"] == (
            CLAIM_CENTS
        )

        assert_fund_counters(
            fixtures.read_fund(client),
            appropriated_cents=APPROPRIATION_CENTS,
            fine_credits_cents=INSTALMENT_CENTS,
            awarded_cents=CLAIM_CENTS,
            assessment_cents=4000,
            clawed_back_cents=0,
            balance_cents=BALANCE_AFTER_AWARD_CENTS,
        )

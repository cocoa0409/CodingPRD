"""Two cycles that run backwards before they can run forwards."""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success
from test_helpers import fixtures
from test_helpers.api_errors import ERR_CONSENT_ROUND_LIMIT, ERR_INVALID_STATE
from test_helpers.assertions import assert_posture
from test_helpers.test_users import make_auditor_headers, make_broker_headers, make_counsel_headers

AUDITOR = "auditor-01"
AS_OF_DATE = "2026-08-31"
FIELDWORK_START = "2026-08-01T00:00:00Z"
FIELDWORK_END = "2026-08-01T17:00:00Z"


def _audit_under_remediation_order(client):
    """An account three hundred thousand cents short, sitting under a first-round order."""
    firm = fixtures.bootstrap_active_brokerage(
        client, name="Harbor Realty Group", broker_name="Dana Broker"
    )
    broker_headers = make_broker_headers(firm["broker"]["id"])
    account_id = firm["account"]["id"]
    fixtures.append_ledger_entry(
        client, account_id, "OBLIGATION_OPENED", 1000000, "2026-08-01", "OBL-1",
        headers=broker_headers,
    )
    fixtures.append_ledger_entry(
        client, account_id, "DEPOSIT", 700000, "2026-08-01", "DEP-1",
        cleared_date="2026-08-01", headers=broker_headers,
    )
    audit = fixtures.schedule_audit(
        client, account_id, AUDITOR, "BOOK", AS_OF_DATE, FIELDWORK_START, FIELDWORK_END
    )
    fieldwork = fixtures.start_fieldwork(client, audit["id"], AUDITOR)
    assert fieldwork["computed_shortage_cents"] == 300000
    ordered = fixtures.dispose_audit(
        client, audit["id"], AUDITOR, "ISSUE_FINDINGS", remediation_days=3
    )
    assert ordered["status"] == "REMEDIATION_ORDERED"
    assert ordered["remediation_round"] == 1
    assert fixtures.read_trust_account(client, account_id)["status"] == "RESTRICTED"
    return {
        "firm": firm,
        "broker_headers": broker_headers,
        "account_id": account_id,
        "audit_id": audit["id"],
    }


class TestRemediationVerifyCycle:
    """The audit loops back through REMEDIATION_ORDERED before escalation unlocks."""

    def test_manual_escalation_is_refused_while_the_order_is_still_in_round_one(self, client):
        """The same request body that is illegal at round one becomes legal later.

        The PRD says "By hand this is available only to the owning auditor and
        only once `remediation_round` has reached 2 or more, so escalating a
        first-round remediation order manually is refused with
        `ERR_INVALID_STATE`; the compliance sweep escalates automatically, without
        any round requirement, once `remediation_due_at` has fallen strictly
        behind the clock."

        Design: Difficulty/non_linear_state_machine/trust_audit_remediation_verify_cycle_re_arms_before_manual_escalation_unlocks
        """
        world = _audit_under_remediation_order(client)

        validate_error(
            client.audit_disposition(
                world["audit_id"],
                {"action": "ESCALATE", "note": "too early"},
                make_auditor_headers(AUDITOR),
            ),
            ERR_INVALID_STATE,
        )
        still_ordered = fixtures.read_audit(client, world["audit_id"])
        assert still_ordered["status"] == "REMEDIATION_ORDERED"
        assert still_ordered["remediation_round"] == 1

    def test_a_failed_verification_sends_the_audit_backwards_and_re_arms_the_clock(self, client):
        """Verification that still finds money missing loops, it does not escalate.

        The PRD says "A verified shortage still greater than 0 continues
        `VERIFYING → REMEDIATION_ORDERED`, increments `remediation_round` by one
        and re-arms `remediation_due_at` to the current instant plus another three
        days."

        Design: Difficulty/non_linear_state_machine/trust_audit_remediation_verify_cycle_re_arms_before_manual_escalation_unlocks
        """
        world = _audit_under_remediation_order(client)

        # A restricted account still accepts the deposit that cures the shortage.
        fixtures.append_ledger_entry(
            client, world["account_id"], "DEPOSIT", 100000, "2026-08-02", "DEP-2",
            cleared_date="2026-08-02", headers=world["broker_headers"],
        )
        assert fixtures.read_trust_account(client, world["account_id"])["status"] == "RESTRICTED"

        looped = fixtures.dispose_audit(
            client, world["audit_id"], AUDITOR, "VERIFY_REMEDIATION", remediation_days=3
        )
        assert looped["verified_shortage_cents"] == 200000
        assert looped["status"] == "REMEDIATION_ORDERED"
        assert looped["remediation_round"] == 2

    def test_only_a_zero_verification_exits_the_loop_and_closed_is_terminal(self, client):
        """Reaching zero closes the audit, frees the account and locks the cycle.

        The PRD says "A verified shortage of 0 continues `VERIFYING → CLOSED`;
        the account returns `RESTRICTED → OPEN` provided its own `shortage_cents`
        is 0 and no other audit on that account is sitting in
        `REMEDIATION_ORDERED` or `ESCALATED`".

        Design: Difficulty/non_linear_state_machine/trust_audit_remediation_verify_cycle_re_arms_before_manual_escalation_unlocks
        """
        world = _audit_under_remediation_order(client)
        account_id = world["account_id"]

        fixtures.append_ledger_entry(
            client, account_id, "DEPOSIT", 100000, "2026-08-02", "DEP-2",
            cleared_date="2026-08-02", headers=world["broker_headers"],
        )
        fixtures.dispose_audit(client, world["audit_id"], AUDITOR, "VERIFY_REMEDIATION")
        fixtures.append_ledger_entry(
            client, account_id, "DEPOSIT", 200000, "2026-08-03", "DEP-3",
            cleared_date="2026-08-03", headers=world["broker_headers"],
        )

        closed = fixtures.dispose_audit(client, world["audit_id"], AUDITOR, "VERIFY_REMEDIATION")
        assert closed["verified_shortage_cents"] == 0
        assert closed["status"] == "CLOSED"
        assert closed["remediation_round"] == 2, "the successful exit does not advance the round"

        account = fixtures.read_trust_account(client, account_id)
        assert account["status"] == "OPEN"
        assert account["shortage_cents"] == 0
        brokerage = fixtures.read_brokerage(client, world["firm"]["brokerage"]["id"])
        assert brokerage["open_shortage_cents"] == 0
        assert_posture(brokerage, "COMPLIANT")

        validate_error(
            client.audit_disposition(
                world["audit_id"], {"action": "VERIFY_REMEDIATION"}, make_auditor_headers(AUDITOR)
            ),
            ERR_INVALID_STATE,
        )


def _negotiation_at_round_one(client):
    """A probable-cause complaint with consent round one on the table."""
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
        client, respondent["id"], "MISREPRESENTATION", 500000
    )
    agreement = fixtures.offer_consent(
        client, complaint["id"], "SUSPENSION", 200000, 30, counsel_user_id="counsel-01"
    )
    assert agreement["status"] == "OFFERED"
    assert agreement["round_number"] == 1
    assert fixtures.read_complaint(client, complaint["id"])["status"] == "CONSENT_PENDING"
    return {"respondent": respondent, "complaint": complaint, "agreement": agreement}


class TestConsentNegotiationRoundCeiling:
    """The haggle loops twice, dead-ends at round three, and withdraws."""

    def test_a_counter_never_advances_the_round_while_a_revision_does(self, client):
        """Two round-trips: the counters hold the round, the revisions raise it.

        The PRD says "`COUNTER` moves it `OFFERED → COUNTERED`, records
        `responded_by_user_id`, stores the two counter figures, and **leaves
        `round_number` untouched**."

        Design: Difficulty/non_linear_state_machine/consent_offer_counter_cycle_dead_ends_at_round_three_with_withdraw_as_only_exit
        """
        world = _negotiation_at_round_one(client)
        agreement_id = world["agreement"]["id"]
        respondent_id = world["respondent"]["id"]

        countered = fixtures.respondent_replies(
            client, agreement_id, respondent_id, "COUNTER",
            counter_fine_cents=50000, counter_suspension_days=0,
        )
        assert countered["status"] == "COUNTERED"
        assert countered["round_number"] == 1

        revised = fixtures.commission_replies(
            client, agreement_id, "REVISE", counsel_user_id="counsel-01",
            proposed_fine_cents=150000, proposed_suspension_days=20,
        )
        assert revised["status"] == "OFFERED"
        assert revised["round_number"] == 2
        assert revised["proposed_fine_cents"] == 150000
        assert revised["counter_fine_cents"] is None
        assert revised["counter_suspension_days"] is None

        fixtures.respondent_replies(
            client, agreement_id, respondent_id, "COUNTER",
            counter_fine_cents=75000, counter_suspension_days=5,
        )
        second_revision = fixtures.commission_replies(
            client, agreement_id, "REVISE", counsel_user_id="counsel-01",
            proposed_fine_cents=120000, proposed_suspension_days=15,
        )
        assert second_revision["status"] == "OFFERED"
        assert second_revision["round_number"] == 3

    def test_the_third_revision_is_barred_at_the_round_ceiling(self, client):
        """A counter at the ceiling is legal; counsel's revision after it is not.

        The PRD says "Revision is permitted only while `round_number` is strictly
        below 3; once `round_number` has reached 3 the cycle is closed and a
        further revision is refused with `ERR_CONSENT_ROUND_LIMIT`."

        Design: Difficulty/non_linear_state_machine/consent_offer_counter_cycle_dead_ends_at_round_three_with_withdraw_as_only_exit
        """
        world = _negotiation_at_round_one(client)
        agreement_id = world["agreement"]["id"]
        respondent_id = world["respondent"]["id"]

        for counter_fine, revised_fine in ((50000, 150000), (75000, 120000)):
            fixtures.respondent_replies(
                client, agreement_id, respondent_id, "COUNTER", counter_fine_cents=counter_fine
            )
            fixtures.commission_replies(
                client, agreement_id, "REVISE", counsel_user_id="counsel-01",
                proposed_fine_cents=revised_fine, proposed_suspension_days=15,
            )

        at_ceiling = fixtures.respondent_replies(
            client, agreement_id, respondent_id, "COUNTER",
            counter_fine_cents=90000, counter_suspension_days=10,
        )
        assert at_ceiling["status"] == "COUNTERED"
        assert at_ceiling["round_number"] == 3
        assert fixtures.read_complaint(client, world["complaint"]["id"])["status"] == (
            "CONSENT_PENDING"
        )

        validate_error(
            client.commission_action(
                agreement_id,
                {"action": "REVISE", "proposed_fine_cents": 110000, "proposed_suspension_days": 12},
                make_counsel_headers("counsel-01"),
            ),
            ERR_CONSENT_ROUND_LIMIT,
        )
        unchanged = validate_success(
            client.get_consent_agreement(agreement_id, make_counsel_headers("counsel-01"))
        )
        assert unchanged["status"] == "COUNTERED"
        assert unchanged["round_number"] == 3
        assert unchanged["proposed_fine_cents"] == 120000

    def test_withdrawal_is_the_only_exit_and_returns_the_case_to_probable_cause(self, client):
        """Rejecting the agreement walks the parent complaint backwards.

        The PRD says "`WITHDRAW` moves the agreement `COUNTERED → REJECTED` and
        returns the complaint `CONSENT_PENDING → PROBABLE_CAUSE`, which reopens
        the hearing route."

        Design: Difficulty/non_linear_state_machine/consent_offer_counter_cycle_dead_ends_at_round_three_with_withdraw_as_only_exit
        """
        world = _negotiation_at_round_one(client)
        agreement_id = world["agreement"]["id"]
        respondent_id = world["respondent"]["id"]
        complaint_id = world["complaint"]["id"]

        for counter_fine, revised_fine in ((50000, 150000), (75000, 120000)):
            fixtures.respondent_replies(
                client, agreement_id, respondent_id, "COUNTER", counter_fine_cents=counter_fine
            )
            fixtures.commission_replies(
                client, agreement_id, "REVISE", counsel_user_id="counsel-01",
                proposed_fine_cents=revised_fine, proposed_suspension_days=15,
            )
        fixtures.respondent_replies(
            client, agreement_id, respondent_id, "COUNTER", counter_fine_cents=90000
        )

        rejected = fixtures.commission_replies(
            client, agreement_id, "WITHDRAW", counsel_user_id="counsel-01"
        )
        assert rejected["status"] == "REJECTED"
        assert fixtures.read_complaint(client, complaint_id)["status"] == "PROBABLE_CAUSE"

        listed, _meta = validate_paginated(
            client.list_consent_agreements(complaint_id, make_counsel_headers("counsel-01"))
        )
        assert len(listed) == 1, "the loop revised one agreement row rather than one row per round"
        assert listed[0]["id"] == agreement_id

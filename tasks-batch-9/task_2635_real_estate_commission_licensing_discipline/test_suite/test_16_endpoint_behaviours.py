"""The two endpoints whose whole point is what they do not do."""

from prd_bench_local_runner.testing import validate_paginated, validate_success
from test_helpers import fixtures
from test_helpers.assertions import assert_posture
from test_helpers.constants import CLOCK_STARTUP_DEFAULT
from test_helpers.test_users import make_analyst_headers

FIRM_NAME = "Harbor Realty Group"
BROKER_NAME = "Dana Broker"
SALESPERSON_NAME = "Sam Reed"
AUDITOR = "auditor-21"
AS_OF_DATE = "2026-08-31"
FIELDWORK_START = "2026-08-01T00:00:00Z"
FIELDWORK_END = "2026-08-01T17:00:00Z"
OBLIGATION_CENTS = 1000000
DEPOSIT_CENTS = 800000
SHORTAGE_CENTS = 200000
FINE_CENTS = 500000
REMEDIATION_DUE_AT = "2026-08-04T00:00:00Z"
FINE_DUE_AT = "2026-08-31T00:00:00Z"
AFTER_BOTH_DEADLINES = "2026-09-01T00:00:00Z"
QUIET_COUNTS = {
    "expired_licensee_count": 0,
    "escalated_audit_count": 0,
    "defaulted_order_count": 0,
    "restored_licensee_count": 0,
    "suspended_provider_count": 0,
}


def _assert_counts(sweep, **expected):
    """Every one of the five reported counters, with the unnamed ones at zero."""
    counts = dict(QUIET_COUNTS)
    counts.update(expected)
    for field, value in counts.items():
        assert sweep[field] == value, f"{field} reported {sweep[field]}, expected {value}"


def _register_with_a_stalled_order_and_an_unpaid_fine(client):
    """One firm carrying a first-round remediation order and one unpaid consent fine."""
    firm = fixtures.bootstrap_active_brokerage(
        client, name=FIRM_NAME, broker_name=BROKER_NAME
    )
    brokerage_id = firm["brokerage"]["id"]
    broker_id = firm["broker"]["id"]
    account_id = firm["account"]["id"]
    agent = fixtures.affiliate_new_salesperson(
        client, brokerage_id, broker_id, SALESPERSON_NAME
    )

    complaint = fixtures.complaint_at_probable_cause(client, agent["id"], "TRUST_SHORTAGE", 0)
    order = fixtures.issue_order_by_consent(
        client, complaint["id"], agent["id"], "FINE", FINE_CENTS, 0
    )
    assert order["status"] == "ISSUED"
    assert order["effective_at"] == CLOCK_STARTUP_DEFAULT
    assert order["fine_due_at"] == FINE_DUE_AT
    assert order["fine_paid_cents"] == 0

    fixtures.append_ledger_entry(
        client, account_id, "OBLIGATION_OPENED", OBLIGATION_CENTS, "2026-08-01", "OBL-1"
    )
    fixtures.append_ledger_entry(
        client, account_id, "DEPOSIT", DEPOSIT_CENTS, "2026-08-01", "DEP-1",
        cleared_date="2026-08-01",
    )
    assert fixtures.read_trust_account(client, account_id)["shortage_cents"] == SHORTAGE_CENTS

    audit = fixtures.schedule_audit(
        client, account_id, AUDITOR, "BOOK", AS_OF_DATE, FIELDWORK_START, FIELDWORK_END
    )
    fixtures.start_fieldwork(client, audit["id"], AUDITOR)
    ordered = fixtures.dispose_audit(
        client, audit["id"], AUDITOR, "ISSUE_FINDINGS", remediation_days=3
    )
    assert ordered["status"] == "REMEDIATION_ORDERED"
    assert ordered["remediation_due_at"] == REMEDIATION_DUE_AT
    assert fixtures.read_trust_account(client, account_id)["status"] == "RESTRICTED"

    return {
        "brokerage_id": brokerage_id,
        "broker_id": broker_id,
        "account_id": account_id,
        "agent": agent,
        "audit_id": audit["id"],
        "order": order,
    }


class TestTheComplianceSweepIsAnOrderedBulkActionAndThenANoOp:
    """No request body, five reported counters, and nothing left to do on a second pass."""

    def test_nothing_is_due_at_the_startup_instant_so_all_five_counters_are_zero(self, client):
        """The rows exist and their deadlines are ahead, so the sweep reports five zeros.

        The PRD says "Nothing in this system expires on its own. Licences do not
        lapse, remediation deadlines do not escalate, and unpaid fines do not
        default merely because the logical clock has moved past a stored instant;
        the stored row keeps its old `status` until a sweep observes it."

        Design: Corner/endpoints/the_compliance_sweep_is_an_ordered_bulk_action_and_a_second_run_is_a_no_op
        """
        world = _register_with_a_stalled_order_and_an_unpaid_fine(client)

        sweep = fixtures.run_sweep(client)
        _assert_counts(sweep)

        assert fixtures.read_audit(client, world["audit_id"])["status"] == "REMEDIATION_ORDERED"
        assert fixtures.read_sanction_order(client, world["order"]["id"])["status"] == "ISSUED"
        assert fixtures.read_licensee(client, world["agent"]["id"])["license_status"] == "ACTIVE"

    def test_one_pass_past_both_deadlines_escalates_one_audit_and_defaults_one_order(
        self, client
    ):
        """A single request touches an audit family and an order family and counts each.

        The PRD says "Every audit in `REMEDIATION_ORDERED` whose
        `remediation_due_at` is strictly before the current instant escalates as
        described in §3.7, creating its escalation complaint and driving the
        respondent broker and their firm."

        The PRD says "Every order in `ISSUED` with a positive `fine_cents`, a
        `fine_paid_cents` still short of it, and a `fine_due_at` strictly before
        the current instant moves `ISSUED → IN_DEFAULT`, suspending the respondent
        for 90 days as described in §3.10."

        Design: Corner/endpoints/the_compliance_sweep_is_an_ordered_bulk_action_and_a_second_run_is_a_no_op
        """
        world = _register_with_a_stalled_order_and_an_unpaid_fine(client)
        fixtures.run_sweep(client)
        fixtures.move_clock(client, AFTER_BOTH_DEADLINES)

        sweep = fixtures.run_sweep(client)
        _assert_counts(sweep, escalated_audit_count=1, defaulted_order_count=1)

        escalated = fixtures.read_audit(client, world["audit_id"])
        assert escalated["status"] == "ESCALATED"
        raised, _meta = validate_paginated(
            client.list_complaints(
                make_analyst_headers(), params={"source_audit_id": world["audit_id"]}
            )
        )
        assert len(raised) == 1
        assert raised[0]["allegation_type"] == "TRUST_SHORTAGE"
        assert raised[0]["status"] == "INVESTIGATION"
        assert raised[0]["respondent_licensee_id"] == world["broker_id"], (
            "the escalation names the designated broker, not the fined salesperson"
        )

        defaulted = fixtures.read_sanction_order(client, world["order"]["id"])
        assert defaulted["status"] == "IN_DEFAULT"
        assert defaulted["fine_paid_cents"] == 0
        assert defaulted["fine_due_at"] == FINE_DUE_AT

    def test_the_escalated_audit_leaves_the_account_short_and_the_posture_restricted(
        self, client
    ):
        """Escalation moves the audit and the broker, never the money.

        The PRD says "Finally the brokerage's `supervision_posture` is recomputed,
        and here the tiers interact in a way worth noticing: the escalated audit no
        longer counts as an overdue remediation, so the `FROZEN` driver disappears,
        but the designated broker being `UNDER_INVESTIGATION` pins the posture at
        `RESTRICTED` regardless."

        Design: Corner/endpoints/the_compliance_sweep_is_an_ordered_bulk_action_and_a_second_run_is_a_no_op
        """
        world = _register_with_a_stalled_order_and_an_unpaid_fine(client)
        fixtures.move_clock(client, AFTER_BOTH_DEADLINES)
        fixtures.run_sweep(client)

        assert fixtures.read_licensee(client, world["broker_id"])["discipline_status"] == (
            "UNDER_INVESTIGATION"
        )
        brokerage = fixtures.read_brokerage(client, world["brokerage_id"])
        assert brokerage["overdue_remediation_count"] == 0
        assert_posture(brokerage, "RESTRICTED")

        account = fixtures.read_trust_account(client, world["account_id"])
        assert account["status"] == "RESTRICTED"
        assert account["shortage_cents"] == SHORTAGE_CENTS

    def test_an_identical_third_run_at_the_same_instant_reports_five_zeros(self, client):
        """Idempotence: every row the sweep moved has left its qualifying state.

        The PRD says "It is **idempotent with respect to the clock**: running it
        twice at the same logical instant produces the same register, and the
        second run reports all five counters as 0 because every qualifying row has
        already moved out of its qualifying state."

        Design: Corner/endpoints/the_compliance_sweep_is_an_ordered_bulk_action_and_a_second_run_is_a_no_op
        """
        world = _register_with_a_stalled_order_and_an_unpaid_fine(client)
        fixtures.move_clock(client, AFTER_BOTH_DEADLINES)
        _assert_counts(
            fixtures.run_sweep(client), escalated_audit_count=1, defaulted_order_count=1
        )

        _assert_counts(fixtures.run_sweep(client))

        assert fixtures.read_audit(client, world["audit_id"])["status"] == "ESCALATED"
        assert fixtures.read_sanction_order(client, world["order"]["id"])["status"] == (
            "IN_DEFAULT"
        )
        assert fixtures.read_licensee(client, world["agent"]["id"])["license_status"] == (
            "SUSPENDED"
        ), "step 3 suspended the respondent and step 4 did not undo it"


PAST_THE_EXPIRY = "2028-08-01T00:00:00Z"
EXPECTED_EXPIRY = "2028-07-31T00:00:00Z"


def _firm_whose_broker_expires_in_two_years(client):
    """One self-supervising designated broker, issued on the startup instant."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    broker = fixtures.read_licensee(client, firm["broker"]["id"])
    assert broker["license_issued_at"] == CLOCK_STARTUP_DEFAULT
    assert broker["license_expires_at"] == EXPECTED_EXPIRY
    return firm


class TestTheClockEndpointMutatesNothingAndImpliesNoSweep:
    """Time moving past a stored deadline is not the same as the deadline being applied."""

    def test_the_clock_call_answers_with_the_new_instant_alone(self, client):
        """The endpoint's whole declared effect is the clock reading it reports.

        The PRD says "An administrative capability lets an operator move the clock
        to a supplied instant, expressed as `to_iso8601` in the request body, and
        answers with the resulting `current_utc`."

        Design: Corner/endpoints/the_clock_endpoint_mutates_nothing_and_implies_no_sweep
        """
        _firm_whose_broker_expires_in_two_years(client)

        moved = validate_success(
            client.set_clock(PAST_THE_EXPIRY, make_analyst_headers())
        )
        assert moved["current_utc"] == PAST_THE_EXPIRY

    def test_a_licence_read_past_its_expiry_still_reports_active(self, client):
        """No lazy expiry on read: the stored status survives the clock move.

        The PRD says "Moving the clock advances or rewinds time only: no entity is
        mutated, no expiry is applied and no housekeeping is implied as a side
        effect of setting it."

        Design: Corner/endpoints/the_clock_endpoint_mutates_nothing_and_implies_no_sweep
        """
        firm = _firm_whose_broker_expires_in_two_years(client)
        fixtures.move_clock(client, PAST_THE_EXPIRY)

        broker = fixtures.read_licensee(client, firm["broker"]["id"])
        assert broker["license_status"] == "ACTIVE"
        assert broker["license_expires_at"] == EXPECTED_EXPIRY
        assert broker["inactive_since"] is None

        brokerage = fixtures.read_brokerage(client, firm["brokerage"]["id"])
        assert brokerage["affiliated_licensee_count"] == 1
        assert_posture(brokerage, "COMPLIANT")

    def test_only_the_sweep_applies_the_expiry_and_the_posture_follows_it(self, client):
        """The explicit sweep is the single channel through which time bites.

        The PRD says "Housekeeping happens only when the compliance sweep is
        invoked explicitly (§3.9)."

        The PRD says "The consequence for the firm can be severe: when the expiring
        licensee was the designated broker, the recomputed posture of that firm
        lands on `FROZEN`."

        Design: Corner/endpoints/the_clock_endpoint_mutates_nothing_and_implies_no_sweep
        """
        firm = _firm_whose_broker_expires_in_two_years(client)
        fixtures.move_clock(client, PAST_THE_EXPIRY)
        assert fixtures.read_licensee(client, firm["broker"]["id"])["license_status"] == "ACTIVE"

        _assert_counts(fixtures.run_sweep(client), expired_licensee_count=1)

        expired = fixtures.read_licensee(client, firm["broker"]["id"])
        assert expired["license_status"] == "EXPIRED"
        assert expired["inactive_since"] == PAST_THE_EXPIRY

        brokerage = fixtures.read_brokerage(client, firm["brokerage"]["id"])
        assert brokerage["affiliated_licensee_count"] == 0
        assert_posture(brokerage, "FROZEN")

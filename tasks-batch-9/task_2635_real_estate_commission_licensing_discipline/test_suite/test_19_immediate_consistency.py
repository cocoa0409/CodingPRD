"""One disposition, three entities, and nothing left to converge afterwards."""

from prd_bench_local_runner.testing import validate_success
from test_helpers import factories, fixtures
from test_helpers.assertions import assert_posture
from test_helpers.test_users import make_auditor_headers

FIRM_NAME = "Harbor Realty Group"
BROKER_NAME = "Dana Broker"
AUDITOR = "auditor-41"
AS_OF_DATE = "2026-08-31"
FIELDWORK_START = "2026-08-01T00:00:00Z"
FIELDWORK_END = "2026-08-01T17:00:00Z"
OBLIGATION_CENTS = 1000000
DEPOSIT_CENTS = 800000
SHORTAGE_CENTS = 200000
REMEDIATION_DAYS = 7
REMEDIATION_DUE_AT = "2026-08-08T00:00:00Z"


def _audit_with_fieldwork_open(client):
    """A BOOK audit in FIELDWORK over an account 200,000 cents short."""
    firm = fixtures.bootstrap_active_brokerage(
        client, name=FIRM_NAME, broker_name=BROKER_NAME
    )
    account_id = firm["account"]["id"]
    fixtures.append_ledger_entry(
        client, account_id, "OBLIGATION_OPENED", OBLIGATION_CENTS, "2026-08-01", "OBL-1"
    )
    fixtures.append_ledger_entry(
        client, account_id, "DEPOSIT", DEPOSIT_CENTS, "2026-08-01", "DEP-1",
        cleared_date="2026-08-01",
    )
    audit = fixtures.schedule_audit(
        client, account_id, AUDITOR, "BOOK", AS_OF_DATE, FIELDWORK_START, FIELDWORK_END
    )
    working = fixtures.start_fieldwork(client, audit["id"], AUDITOR)
    assert working["status"] == "FIELDWORK"
    assert working["computed_shortage_cents"] == SHORTAGE_CENTS
    return {
        "brokerage_id": firm["brokerage"]["id"],
        "account_id": account_id,
        "audit_id": audit["id"],
    }


def _issue_findings(client, audit_id):
    return validate_success(
        client.audit_disposition(
            audit_id,
            factories.audit_disposition_payload(
                "ISSUE_FINDINGS", remediation_days=REMEDIATION_DAYS
            ),
            make_auditor_headers(AUDITOR),
        )
    )


class TestEveryCascadeOfAWriteIsVisibleInThatWritesOwnResponse:
    """The consistency model is immediate, so no derived field is allowed to lag."""

    def test_the_disposition_response_already_reports_the_second_transition(self, client):
        """The response skips past FINDINGS_ISSUED because the cascade is the same request.

        The PRD says "When the frozen shortage is greater than 0, the audit instead
        continues `FINDINGS_ISSUED → REMEDIATION_ORDERED` immediately, and a
        four-layer cascade settles before the response is written, **in this order**."

        The PRD says "First, `remediation_round` is set to 1 and
        `remediation_due_at` is set to the current instant plus the remediation
        period — three days by default, or the supplied `remediation_days` count —
        expressed as that many multiples of 86,400 seconds."

        Design: Corner/consistency_model/every_cascade_of_a_write_is_visible_in_that_writes_own_response
        """
        world = _audit_with_fieldwork_open(client)

        ordered = _issue_findings(client, world["audit_id"])

        assert ordered["status"] == "REMEDIATION_ORDERED"
        assert ordered["computed_shortage_cents"] == SHORTAGE_CENTS
        assert ordered["remediation_round"] == 1
        assert ordered["remediation_due_at"] == REMEDIATION_DUE_AT

    def test_the_account_and_the_firm_have_already_moved_when_read_next(self, client):
        """No sweep, no retry, no delay between the write and the two reads.

        The PRD says "The commission's supervisory model is one of **immediate
        consistency**: there are no queues, no deferred jobs and no eventual
        reconciliation. When a request triggers a consequence, that consequence and
        everything it in turn triggers are applied inside the same request, and the
        response reflects the settled state."

        Design: Corner/consistency_model/every_cascade_of_a_write_is_visible_in_that_writes_own_response
        """
        world = _audit_with_fieldwork_open(client)
        _issue_findings(client, world["audit_id"])

        account = fixtures.read_trust_account(client, world["account_id"])
        assert account["status"] == "RESTRICTED"
        assert account["shortage_cents"] == SHORTAGE_CENTS

        brokerage = fixtures.read_brokerage(client, world["brokerage_id"])
        assert brokerage["open_shortage_cents"] == SHORTAGE_CENTS
        assert_posture(brokerage, "RESTRICTED")

    def test_a_second_read_agrees_with_the_first_and_changes_nothing(self, client):
        """Reads never mutate, and the first read was not a lazy recomputation.

        The PRD says "Third, the owning brokerage's `open_shortage_cents` is
        recomputed and its `supervision_posture` re-graded, landing on `RESTRICTED`
        when the accumulated open shortage has reached 100,000 cents and otherwise on
        `WATCH`."

        Design: Corner/consistency_model/every_cascade_of_a_write_is_visible_in_that_writes_own_response
        """
        world = _audit_with_fieldwork_open(client)
        _issue_findings(client, world["audit_id"])

        first_audit = fixtures.read_audit(client, world["audit_id"])
        second_audit = fixtures.read_audit(client, world["audit_id"])
        for field in (
            "status",
            "computed_shortage_cents",
            "remediation_round",
            "remediation_due_at",
        ):
            assert first_audit[field] == second_audit[field], f"{field} moved between reads"

        first_firm = fixtures.read_brokerage(client, world["brokerage_id"])
        second_firm = fixtures.read_brokerage(client, world["brokerage_id"])
        assert second_firm["supervision_posture"] == first_firm["supervision_posture"] == (
            "RESTRICTED"
        )
        assert second_firm["version"] == first_firm["version"], "a read bumped the version"
        assert second_firm["open_shortage_cents"] == first_firm["open_shortage_cents"]

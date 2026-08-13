"""Transaction intake, confirmation cascade, voiding compensation, running
balances, and confirm-time guards (PRD §2.10, §2.11, §3.3)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId,
    make_compliance_officer_headers, make_equity_plan_admin_headers,
    make_filing_agent_headers,
    create_issuer, create_reporting_person, create_active_person,
    person_action, get_person, get_transaction, get_filing, find_draft_form,
    set_clock, ingest_transaction, confirm_transaction, void_transaction,
    setup_person_with_confirmed_transaction, setup_accepted_auto_form4,
)


class TestConfirmCascade:
    def test_confirm_creates_form4_and_raises_obligation_count(self, api):
        """PRD §3.3: "A successful confirmation fires a two-hop cascade. First
        the system computes `direction`, recomputes the running-balance chain
        described below, and — for every code except `G` — automatically creates
        a `DRAFT` `FORM_4` filing with a null `prepared_by_user_id`, attaches the
        transaction by setting its `filing_id`, and fixes the deadline two
        business days after the transaction date per §3.4; an auto-generated
        Form 4 covers exactly one transaction. Second, that filing creation
        itself raises the person's `open_obligation_count` by one."
        PRD §2.11: "`open_obligation_count` on a reporting person counts that
        person's filings in `DRAFT`, `READY`, or `SUBMITTED` status; filings in
        `ACCEPTED`, `REJECTED`, `SUPERSEDED`, or `DISCARDED` do not count."

        Design: Difficulty/transitive_cascade/confirm_autogenerates_form4_and_obligation
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"],
                                      designate_at="2026-08-03T09:00:00Z")
        oc_before = get_person(person["id"])["open_obligation_count"]
        assert oc_before == 1, (
            f"Designation Form 3 draft gives open_obligation_count 1, "
            f"got {oc_before}")
        txn = ingest_transaction(person["id"], transaction_date="2026-08-06",
                                 shares=100, price_per_share=10.00)
        set_clock("2026-08-06T09:00:00Z")
        confirmed = confirm_transaction(txn["id"])
        assert confirmed["status"] == "CONFIRMED"
        oc_after = get_person(person["id"])["open_obligation_count"]
        assert oc_after == 2, (
            f"Auto Form 4 creation must raise open_obligation_count to 2, "
            f"got {oc_after}")

    def test_confirm_form4_deadline_two_business_days_and_attachment(self, api):
        """PRD §3.4: "A `FORM_4` is due two business days after the earliest
        `transaction_date` among the transactions it covers, advanced per the
        business-day routine of §2.6 against the issuer's `holiday_dates` as
        they stood when the filing was created."
        PRD §3.3: "automatically creates a `DRAFT` `FORM_4` filing with a null
        `prepared_by_user_id`, attaches the transaction by setting its
        `filing_id`"

        Design: Difficulty/transitive_cascade/confirm_autogenerates_form4_and_obligation
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"],
                                      designate_at="2026-08-03T09:00:00Z")
        txn = ingest_transaction(person["id"], transaction_date="2026-08-06",
                                 shares=100, price_per_share=10.00)
        set_clock("2026-08-06T09:00:00Z")
        confirm_transaction(txn["id"])
        form4 = find_draft_form(person["id"], "FORM_4")
        # 2026-08-06 is a Thursday: business days are 08-07 (Fri) and 08-10 (Mon).
        assert form4["filing_deadline"] == "2026-08-10", (
            f"Expected deadline 2026-08-10, got {form4['filing_deadline']}")
        assert form4.get("prepared_by_user_id") is None, (
            "Auto Form 4 must carry null prepared_by_user_id")
        attached = get_transaction(txn["id"])
        assert attached.get("filing_id") == form4["id"], (
            f"Transaction must be attached to the auto Form 4, "
            f"got filing_id={attached.get('filing_id')}")


class TestVoidCompensation:
    def test_confirm_then_void_restores_obligation_count(self, api):
        """PRD §3.3: "When the void proceeds against a `CONFIRMED` transaction,
        its linked `DRAFT` or `READY` filing moves to `DISCARDED` and its
        transactions are detached (their `filing_id` cleared), that discard
        lowers the person's `open_obligation_count` by one as exact compensation
        for the confirm-time increment, and the balance chain is recomputed."
        PRD §2.11: "a created draft (automatic or manual) raises it by one,
        while acceptance or discard lowers it by one."

        Design: Difficulty/compensating_invariant/confirm_void_open_obligation_conservation
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"],
                                      designate_at="2026-08-03T09:00:00Z")
        oc_base = get_person(person["id"])["open_obligation_count"]
        txn = ingest_transaction(person["id"], transaction_date="2026-08-06",
                                 shares=100, price_per_share=10.00)
        set_clock("2026-08-06T09:00:00Z")
        confirm_transaction(txn["id"])
        oc_fwd = get_person(person["id"])["open_obligation_count"]
        assert (oc_base, oc_fwd) == (1, 2), (
            f"Forward action must add exactly one obligation, got "
            f"{oc_base} -> {oc_fwd}")
        void_transaction(txn["id"], reason="duplicate feed row")
        oc_end = get_person(person["id"])["open_obligation_count"]
        assert oc_end == oc_base, (
            f"Compensating void must restore open_obligation_count to "
            f"{oc_base}, got {oc_end}")

    def test_void_discards_linked_filing_and_detaches_transaction(self, api):
        """PRD §3.3: "its linked `DRAFT` or `READY` filing moves to `DISCARDED`
        and its transactions are detached (their `filing_id` cleared)"
        PRD §3.3: "`VOID` and `REPORTED` are the terminal states of a
        transaction"

        Design: Difficulty/compensating_invariant/confirm_void_open_obligation_conservation
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"],
                                      designate_at="2026-08-03T09:00:00Z")
        txn = ingest_transaction(person["id"], transaction_date="2026-08-06",
                                 shares=100, price_per_share=10.00)
        set_clock("2026-08-06T09:00:00Z")
        confirm_transaction(txn["id"])
        form4 = find_draft_form(person["id"], "FORM_4")
        voided = void_transaction(txn["id"], reason="duplicate feed row")
        assert voided["status"] == "VOID", (
            f"Expected VOID after void, got {voided['status']}")
        assert get_filing(form4["id"])["status"] == "DISCARDED", (
            "Void must move the linked DRAFT Form 4 to DISCARDED")
        assert get_transaction(txn["id"]).get("filing_id") is None, (
            "Voided transaction must be detached (filing_id cleared)")


class TestConfirmImmediateConsistency:
    def test_confirm_response_reflects_computed_state_immediately(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.3: "A successful confirmation fires a two-hop cascade. First the
        system computes `direction`, recomputes the running-balance chain
        described below, and — for every code except `G` — automatically
        creates a `DRAFT` `FORM_4` filing with a null `prepared_by_user_id`,
        attaches the transaction by setting its `filing_id`, and fixes the
        deadline two business days after the transaction date per §3.4; an
        auto-generated Form 4 covers exactly one transaction."

        Design: Corner/consistency_model/confirm_response_reflects_computed_state_immediately
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"],
                                      designate_at="2026-08-03T09:00:00Z")
        txn = ingest_transaction(person["id"], transaction_date="2026-08-03",
                                 shares=100, price_per_share=10.00)
        resp = api.confirm_transaction(
            txn["id"], make_compliance_officer_headers("co_1"))
        data = validate_success(resp, 200)
        assert data["status"] == "CONFIRMED", (
            f"Confirm response must carry CONFIRMED, got {data['status']}")
        assert data["direction"] == "ACQUIRED", (
            f"Code P derives ACQUIRED, got {data['direction']}")
        assert data["shares_owned_after"] == 100, (
            f"Expected running balance 100 in the confirm response, "
            f"got {data['shares_owned_after']}")


class TestRunningBalanceRecompute:
    def test_shares_balance_recomputed_out_of_order(self, api):
        """PRD §3.3: "Recomputation considers that person's transactions of the
        given security type in `CONFIRMED` or `REPORTED` status, ordered by
        `transaction_date` ascending with ties broken by `created_at` ascending
        — never by `id`; a running total starts at zero, each transaction adds
        its `shares` when its `direction` is `ACQUIRED` and subtracts them when
        `DISPOSED`, and the resulting total is stored on the transaction as
        `shares_owned_after`. Confirming an earlier-dated transaction after a
        later-dated one therefore recomputes the whole chain."

        Design: Corner/calculations/shares_balance_recomputed_out_of_order
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"],
                                      designate_at="2026-08-03T09:00:00Z")
        t_later = ingest_transaction(person["id"], transaction_date="2026-08-05",
                                     shares=50, price_per_share=10.00)
        t_earlier = ingest_transaction(person["id"],
                                       transaction_date="2026-08-04",
                                       shares=100, price_per_share=10.00)
        set_clock("2026-08-05T09:00:00Z")
        confirm_transaction(t_later["id"])
        assert get_transaction(t_later["id"])["shares_owned_after"] == 50, (
            "Only the 08-05 purchase is confirmed at this point")
        confirm_transaction(t_earlier["id"])
        assert get_transaction(t_earlier["id"])["shares_owned_after"] == 100, (
            "The 08-04 purchase sorts first chronologically")
        assert get_transaction(t_later["id"])["shares_owned_after"] == 150, (
            "Whole-chain recompute after out-of-order confirmation: 100 + 50")


class TestConfirmGuards:
    def test_future_transaction_date_rejected_at_confirm(self, api):
        """PRD §3.3: "the `transaction_date` must not be later than the logical
        clock date (`ERR_FUTURE_TRANSACTION_DATE`)"
        PRD §3.3: "the `transaction_date` (which may be earlier than the logical
        clock date but never later — the future-date rule bites at
        confirmation)"

        Design: Corner/validations/future_transaction_date_rejected_at_confirm
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"],
                                      designate_at="2026-08-03T09:00:00Z")
        txn = ingest_transaction(person["id"], transaction_date="2026-08-20",
                                 shares=100, price_per_share=10.00)
        set_clock("2026-08-10T09:00:00Z")
        resp = api.confirm_transaction(txn["id"],
                                       make_compliance_officer_headers("co_1"))
        validate_error(resp, ApiErrorId.ERR_FUTURE_TRANSACTION_DATE)
        assert get_transaction(txn["id"])["status"] == "INGESTED", (
            "Rejected confirm must leave the transaction INGESTED")

    def test_sod_ingester_cannot_confirm(self, api):
        """PRD §2.10: "First, transaction confirmation: the `ComplianceOfficer`
        confirming a transaction must not be the operator who ingested it — the
        caller's `X-User-ID` must differ from the transaction's
        `ingested_by_user_id`, failing with `ERR_SOD_INGESTER_CONFIRMER`."

        Design: Corner/validations/sod_ingester_cannot_confirm
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"])
        txn = ingest_transaction(person["id"], ingester_id="epa_1",
                                 transaction_date="2026-08-01", shares=100,
                                 price_per_share=10.00)
        # The ingester's own operator id presented with the ComplianceOfficer
        # role still violates four-eyes segregation.
        resp = api.confirm_transaction(
            txn["id"], make_compliance_officer_headers("epa_1"))
        validate_error(resp, ApiErrorId.ERR_SOD_INGESTER_CONFIRMER)

    def test_body_reference_missing_person_returns_invalid_request(self, api):
        """PRD §2.8: "Every entity identifier referenced in a request body must
        exist (`ERR_INVALID_REQUEST`)"

        Design: Corner/validations/body_reference_missing_person_returns_invalid_request
        """
        create_issuer()
        resp = api.create_transaction(
            {"reporting_person_id": NON_EXISTENT_UUID,
             "transaction_date": "2026-08-01", "transaction_code": "P",
             "security_type": "COMMON_STOCK", "shares": 100,
             "price_per_share": 10.00},
            make_equity_plan_admin_headers("epa_1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_filing_agent_cannot_confirm_transaction(self, api):
        """PRD §2.1: "`ComplianceOfficer` — the corporate secretary's Section 16
        compliance officer. This role owns issuer registration and
        configuration, blackout windows, insider designations and exits,
        transaction confirmation and voiding, 10b5-1 plan approvals and
        lifecycle actions, beneficial-owner monitoring and schedule recording,
        annual sweeps, filing-agent authorizations, and the logical clock."
        PRD §2.1: "Invoking an operation one's role does not permit is rejected
        with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/filing_agent_cannot_confirm_transaction
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"])
        txn = ingest_transaction(person["id"], transaction_date="2026-08-01",
                                 shares=100, price_per_share=10.00)
        resp = api.confirm_transaction(
            txn["id"], make_filing_agent_headers("agent_1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_void_reported_transaction_returns_invalid_state(self, api):
        """PRD §3.3: "`VOID` and `REPORTED` are the terminal states of a
        transaction; the move from `CONFIRMED` to `REPORTED` is automatic when
        the linked filing is accepted (§3.5)."
        PRD §3.3: "A `ComplianceOfficer` may void a transaction in `INGESTED` or
        `CONFIRMED` status, optionally recording a `reason`; any other starting
        state fails with `ERR_TRANSACTION_INVALID_STATE`."

        Design: Corner/state_machines/void_reported_transaction_returns_invalid_state
        """
        scenario = setup_accepted_auto_form4(
            txn_overrides={"transaction_date": "2026-08-01", "shares": 100,
                           "price_per_share": 10.00})
        resp = api.void_transaction(scenario["txn"]["id"], {},
                                    make_compliance_officer_headers("co_1"))
        validate_error(resp, ApiErrorId.ERR_TRANSACTION_INVALID_STATE)


class TestConfirmGuardPriority:
    def test_exited_person_and_future_date_yields_person_not_active(self, api):
        """PRD §2.8: "When several checks could fail on the same request, the
        first check in the following fixed order determines the rejection, so
        an early failure is never masked by a later one:" with "7. Cross-entity
        state... confirming a transaction or creating a manual filing requires
        the reporting person `ACTIVE` (`ERR_PERSON_NOT_ACTIVE`)" listed before
        "9. Temporal guards... failing with `ERR_FUTURE_TRANSACTION_DATE`".
        PRD §3.3: "Its checks are evaluated in order, so an early failure
        surfaces rather than being masked by a later one"

        Design: Difficulty/priority_pair_validation_conflict/confirm_exit_person_future_date_state_wins
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"],
                                      designate_at="2026-08-03T09:00:00Z")
        set_clock("2026-08-05T09:00:00Z")
        person_action(person["id"], "EXIT")
        txn = ingest_transaction(person["id"], transaction_date="2026-08-20",
                                 shares=100, price_per_share=10.00)
        resp = api.confirm_transaction(txn["id"],
                                       make_compliance_officer_headers("co_1"))
        validate_error(resp, ApiErrorId.ERR_PERSON_NOT_ACTIVE)

    def test_exited_person_alone_yields_person_not_active(self, api):
        """PRD §3.2: "Because both transaction confirmation and manual filing
        creation require an `ACTIVE` person, a `PROPOSED` or `EXITED` insider
        blocks those flows with `ERR_PERSON_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/confirm_exit_person_future_date_state_wins
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"],
                                      designate_at="2026-08-03T09:00:00Z")
        set_clock("2026-08-05T09:00:00Z")
        person_action(person["id"], "EXIT")
        # Past-dated transaction: only the person-state rule is violated.
        txn = ingest_transaction(person["id"], transaction_date="2026-08-01",
                                 shares=100, price_per_share=10.00)
        resp = api.confirm_transaction(txn["id"],
                                       make_compliance_officer_headers("co_1"))
        validate_error(resp, ApiErrorId.ERR_PERSON_NOT_ACTIVE)

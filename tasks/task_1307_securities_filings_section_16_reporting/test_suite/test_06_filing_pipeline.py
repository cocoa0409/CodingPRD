"""The filing pipeline: preparation, submission, EDGAR disposition, deadlines,
timeliness, delinquency cascade, and agent authorization (PRD §2.8, §2.10,
§3.4, §3.5)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId,
    make_compliance_officer_headers, make_filing_coordinator_headers,
    make_filing_agent_headers,
    create_issuer, create_reporting_person, create_active_person,
    authorize_filing_agent, get_person, get_filing, find_draft_form,
    find_filings, set_clock, ingest_transaction, confirm_transaction,
    ready_filing, submit_filing, record_edgar_acceptance,
    setup_person_with_confirmed_transaction, setup_ready_auto_form4,
)


def _setup_rejection_loop_scenario(api):
    """Issuer (ccc CCC12345) + authorized agent_1 + person ACTIVE; purchase
    dated 2026-08-06 confirmed at clock 2026-08-06; auto Form 4 READY;
    submitted at clock 2026-08-07."""
    issuer = create_issuer()
    authorize_filing_agent(issuer["id"], agent_user_id="agent_1")
    person = create_active_person(issuer["id"],
                                  designate_at="2026-08-03T09:00:00Z",
                                  is_officer=True)
    txn = ingest_transaction(person["id"], transaction_date="2026-08-06",
                             shares=100, price_per_share=10.00)
    set_clock("2026-08-06T09:00:00Z")
    confirm_transaction(txn["id"])
    form4 = find_draft_form(person["id"], "FORM_4")
    ready_filing(form4["id"])
    set_clock("2026-08-07T09:00:00Z")
    submit_filing(form4["id"], edgar_ccc="CCC12345", agent_id="agent_1")
    return person, form4


class TestFilingRejectionRevisionLoop:
    def test_rejection_then_reopen_returns_to_draft_cleared(self, api):
        """PRD §3.5: "A rejection records the supplied `rejection_reason` and
        moves the filing to `REJECTED`, from which reopening restarts the
        revision loop `DRAFT` → `READY` → `SUBMITTED` → `REJECTED` → `DRAFT`,
        making the machine cyclic."
        PRD §3.5: "Reopening returns a `READY` or `REJECTED` filing to `DRAFT`
        for editing, clearing `submitted_at`, `submitted_by_user_id`, and
        `rejection_reason`."

        Design: Difficulty/non_linear_state_machine/filing_rejection_revision_loop
        """
        person, form4 = _setup_rejection_loop_scenario(api)
        rejected = validate_success(api.record_edgar_result(
            form4["id"], {"outcome": "REJECTED", "rejection_reason": "bad tag"},
            make_filing_agent_headers("agent_1")), 200)
        assert rejected["status"] == "REJECTED", (
            f"Rejection branch must yield REJECTED, got {rejected['status']}")
        reopened = validate_success(api.reopen_filing(
            form4["id"], make_filing_coordinator_headers("coord_1")), 200)
        assert reopened["status"] == "DRAFT", (
            f"Reopen must complete REJECTED -> DRAFT, got {reopened['status']}")
        assert reopened.get("submitted_at") is None
        assert reopened.get("submitted_by_user_id") is None
        assert reopened.get("rejection_reason") is None

    def test_second_circuit_reaches_acceptance_timely_on_deadline(self, api):
        """PRD §3.5: "from which reopening restarts the revision loop `DRAFT` →
        `READY` → `SUBMITTED` → `REJECTED` → `DRAFT`, making the machine
        cyclic."
        PRD §3.4: "Timeliness is judged exactly once, at acceptance: `is_late`
        is true precisely when the calendar date of `accepted_at` is strictly
        later than `filing_deadline`, so a filing accepted on its deadline date
        is timely."

        Design: Difficulty/non_linear_state_machine/filing_rejection_revision_loop
        """
        person, form4 = _setup_rejection_loop_scenario(api)
        record_edgar_rejection_payload = {
            "outcome": "REJECTED", "rejection_reason": "bad tag"}
        validate_success(api.record_edgar_result(
            form4["id"], record_edgar_rejection_payload,
            make_filing_agent_headers("agent_1")), 200)
        validate_success(api.reopen_filing(
            form4["id"], make_filing_coordinator_headers("coord_1")), 200)
        ready_filing(form4["id"])
        submit_filing(form4["id"], edgar_ccc="CCC12345", agent_id="agent_1")
        # Deadline for the 2026-08-06 trade is 2026-08-10; acceptance on that
        # date is timely (strict > comparison).
        set_clock("2026-08-10T15:00:00Z")
        accepted = validate_success(api.record_edgar_result(
            form4["id"], {"outcome": "ACCEPTED",
                          "accession_number": "0000000001-26-000001"},
            make_filing_agent_headers("agent_1")), 200)
        assert accepted["status"] == "ACCEPTED", (
            f"Second circuit must reach ACCEPTED, got {accepted['status']}")
        assert accepted["is_late"] is False, (
            "Accepted on the deadline date 2026-08-10 must be timely")


class TestLateAcceptanceDelinquencyChain:
    def _accept_first_late_form4(self, api):
        """First late Form 4 accepted at 2026-08-11 (deadline 2026-08-10)."""
        issuer = create_issuer()
        authorize_filing_agent(issuer["id"], agent_user_id="agent_1")
        person = create_active_person(issuer["id"],
                                      designate_at="2026-08-03T09:00:00Z",
                                      is_officer=True)
        t1 = ingest_transaction(person["id"], transaction_date="2026-08-06",
                                shares=100, price_per_share=10.00)
        set_clock("2026-08-06T09:00:00Z")
        confirm_transaction(t1["id"])
        f1 = find_draft_form(person["id"], "FORM_4")
        ready_filing(f1["id"])
        submit_filing(f1["id"], edgar_ccc="CCC12345", agent_id="agent_1")
        set_clock("2026-08-11T10:00:00Z")
        f1_accepted = record_edgar_acceptance(
            f1["id"], accession_number="0000000001-26-000002", agent_id="agent_1")
        return issuer, person, f1_accepted

    def test_first_late_acceptance_increments_count_below_threshold(self, api):
        """PRD §3.4: "`is_late` is true precisely when the calendar date of
        `accepted_at` is strictly later than `filing_deadline`"
        PRD §3.5: "if the filing is late, the person's `late_filing_count`
        rises by one; if that count thereby reaches two, `delinquent_flag`
        latches true"

        Design: Difficulty/transitive_cascade/late_acceptance_delinquency_chain
        """
        _, person, f1 = self._accept_first_late_form4(api)
        assert f1["is_late"] is True, (
            "Accepted 2026-08-11 after deadline 2026-08-10 must be late")
        mid = get_person(person["id"])
        assert mid["late_filing_count"] == 1, (
            f"Hop 2 must increment late_filing_count to 1, "
            f"got {mid['late_filing_count']}")
        assert mid["delinquent_flag"] is False, (
            "Count 1 is below the delinquency threshold of two")

    def test_second_late_acceptance_latches_delinquent_flag(self, api):
        """PRD §3.4: "Each late acceptance increases the person's
        `late_filing_count` by one, and the moment that count reaches two the
        `delinquent_flag` latches true. Both are permanent: later timely
        filings never clear the flag, and a late filing that is subsequently
        superseded by an amendment still counts."

        Design: Difficulty/transitive_cascade/late_acceptance_delinquency_chain
        """
        _, person, f1 = self._accept_first_late_form4(api)
        t2 = ingest_transaction(person["id"], transaction_date="2026-08-06",
                                shares=50, price_per_share=12.00)
        confirm_transaction(t2["id"])
        f2 = find_draft_form(person["id"], "FORM_4")
        ready_filing(f2["id"])
        submit_filing(f2["id"], edgar_ccc="CCC12345", agent_id="agent_1")
        set_clock("2026-08-11T11:00:00Z")
        f2_accepted = record_edgar_acceptance(
            f2["id"], accession_number="0000000001-26-000003", agent_id="agent_1")
        assert f2_accepted["is_late"] is True
        end = get_person(person["id"])
        assert end["late_filing_count"] == 2, (
            f"Second late acceptance must bring the count to 2, "
            f"got {end['late_filing_count']}")
        assert end["delinquent_flag"] is True, (
            "Hop 3: delinquent_flag latches true when the count reaches two")


class TestAcceptanceDeadlineBoundary:
    def _setup_two_submitted_form4s(self, api):
        """Two purchases dated 2026-08-06 (deadline 2026-08-10), each with its
        auto Form 4 submitted."""
        issuer = create_issuer()
        authorize_filing_agent(issuer["id"], agent_user_id="agent_1")
        person = create_active_person(issuer["id"],
                                      designate_at="2026-08-03T09:00:00Z",
                                      is_officer=True)
        t1 = ingest_transaction(person["id"], transaction_date="2026-08-06",
                                shares=100, price_per_share=10.00)
        set_clock("2026-08-06T09:00:00Z")
        confirm_transaction(t1["id"])
        f1 = find_draft_form(person["id"], "FORM_4")
        ready_filing(f1["id"])
        submit_filing(f1["id"], edgar_ccc="CCC12345", agent_id="agent_1")
        t2 = ingest_transaction(person["id"], transaction_date="2026-08-06",
                                shares=50, price_per_share=11.00)
        confirm_transaction(t2["id"])
        f2 = find_draft_form(person["id"], "FORM_4")
        ready_filing(f2["id"])
        submit_filing(f2["id"], edgar_ccc="CCC12345", agent_id="agent_1")
        return person, f1, f2

    def test_acceptance_on_deadline_date_is_timely(self, api):
        """PRD §3.4: "Timeliness is judged exactly once, at acceptance:
        `is_late` is true precisely when the calendar date of `accepted_at` is
        strictly later than `filing_deadline`, so a filing accepted on its
        deadline date is timely."
        PRD §3.4: "A `FORM_4` is due two business days after the earliest
        `transaction_date` among the transactions it covers"

        Design: Difficulty/boundary_precision_check/acceptance_on_deadline_date_is_timely
        """
        person, f1, f2 = self._setup_two_submitted_form4s(api)
        assert f1["filing_deadline"] == "2026-08-10", (
            f"2026-08-06 (Thu) + 2 business days = 2026-08-10, "
            f"got {f1['filing_deadline']}")
        set_clock("2026-08-10T23:59:59Z")
        accepted = record_edgar_acceptance(
            f1["id"], accession_number="0000000001-26-000004", agent_id="agent_1")
        assert accepted["is_late"] is False, (
            "Acceptance on the deadline date is timely (strict >)")

    def test_acceptance_one_day_after_deadline_is_late(self, api):
        """PRD §3.4: "Timeliness is judged exactly once, at acceptance:
        `is_late` is true precisely when the calendar date of `accepted_at` is
        strictly later than `filing_deadline`, so a filing accepted on its
        deadline date is timely."

        Design: Difficulty/boundary_precision_check/acceptance_on_deadline_date_is_timely
        """
        person, f1, f2 = self._setup_two_submitted_form4s(api)
        set_clock("2026-08-11T00:00:00Z")
        accepted = record_edgar_acceptance(
            f2["id"], accession_number="0000000001-26-000005", agent_id="agent_1")
        assert accepted["is_late"] is True, (
            "Accepted 2026-08-11 > deadline 2026-08-10 must be late")


class TestSubmitAgentAuthorization:
    def _setup_ready_form4(self, api):
        issuer = create_issuer()
        person = create_active_person(issuer["id"], is_officer=True)
        txn = ingest_transaction(person["id"], transaction_date="2026-08-01",
                                 shares=100, price_per_share=10.00)
        confirm_transaction(txn["id"])
        form4 = find_draft_form(person["id"], "FORM_4")
        ready_filing(form4["id"])
        return issuer, form4

    def test_revoked_authorization_blocks_submit(self, api):
        """PRD §3.5: "revocation — permitted only while `ACTIVE`, failing
        otherwise with `ERR_AUTHORIZATION_INVALID_STATE` — moves one to the
        terminal `REVOKED` state, after which that agent can no longer submit
        or record EDGAR results for the issuer."
        PRD §3.5: "an `ACTIVE` authorization must exist pairing the filing's
        `issuer_id` with the caller's `X-User-ID` (`ERR_AGENT_NOT_AUTHORIZED`)"

        Design: Difficulty/cross_entity_state_dependency/submit_requires_active_agent_authorization
        """
        issuer, form4 = self._setup_ready_form4(api)
        auth = authorize_filing_agent(issuer["id"], agent_user_id="agent_1")
        resp = api.revoke_filing_agent_authorization(
            auth["id"], make_compliance_officer_headers("co_1"))
        assert resp.status_code == 200
        resp = api.submit_filing(form4["id"], {"edgar_ccc": "CCC12345"},
                                 make_filing_agent_headers("agent_1"))
        validate_error(resp, ApiErrorId.ERR_AGENT_NOT_AUTHORIZED)

    def test_missing_authorization_blocks_submit(self, api):
        """PRD §3.5: "Submission belongs to a `FilingAgent` holding an `ACTIVE`
        FilingAgentAuthorization for the filing's issuer."
        PRD §3.5: "an `ACTIVE` authorization must exist pairing the filing's
        `issuer_id` with the caller's `X-User-ID` (`ERR_AGENT_NOT_AUTHORIZED`)"

        Design: Difficulty/cross_entity_state_dependency/submit_requires_active_agent_authorization
        """
        issuer, form4 = self._setup_ready_form4(api)
        # No authorization ever created for agent_1.
        resp = api.submit_filing(form4["id"], {"edgar_ccc": "CCC12345"},
                                 make_filing_agent_headers("agent_1"))
        validate_error(resp, ApiErrorId.ERR_AGENT_NOT_AUTHORIZED)


class TestSubmitCheckOrder:
    def _setup_manual_form3_ready(self, api):
        """Manual FORM_3 prepared by coord_1, moved to READY; authorizations
        exist for both agent_1 and coord_1."""
        issuer = create_issuer()
        authorize_filing_agent(issuer["id"], agent_user_id="agent_1")
        authorize_filing_agent(issuer["id"], agent_user_id="coord_1")
        person = create_active_person(issuer["id"], is_officer=True)
        filing = get_success_data(api.create_filing(
            {"issuer_id": issuer["id"], "reporting_person_id": person["id"],
             "form_type": "FORM_3"},
            make_filing_coordinator_headers("coord_1")))
        ready_filing(filing["id"], coordinator_id="coord_1")
        return issuer, person, filing

    def test_submit_sod_violation_beats_bad_credentials(self, api):
        """PRD §3.5: "At submit time the filing must be `READY`
        (`ERR_FILING_INVALID_STATE`), and the remaining checks run in order: an
        `ACTIVE` authorization must exist pairing the filing's `issuer_id` with
        the caller's `X-User-ID` (`ERR_AGENT_NOT_AUTHORIZED`); the submitter
        must differ from a non-null `prepared_by_user_id`
        (`ERR_SOD_PREPARER_SUBMITTER`); and the payload `edgar_ccc` must equal
        the issuer's current `edgar_ccc` (`ERR_EDGAR_CREDENTIAL_MISMATCH`)."
        PRD §2.8: "When several checks could fail on the same request, the
        first check in the following fixed order determines the rejection, so
        an early failure is never masked by a later one:"

        Design: Difficulty/priority_pair_validation_conflict/submit_sod_and_bad_credentials_sod_wins
        """
        issuer, person, filing = self._setup_manual_form3_ready(api)
        # Submitter coord_1 is the preparer AND presents a wrong CCC; the SOD
        # guard is evaluated before the credential check.
        resp = api.submit_filing(filing["id"], {"edgar_ccc": "WRONGCCC"},
                                 make_filing_agent_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_SOD_PREPARER_SUBMITTER)

    def test_wrong_credentials_alone_yield_credential_mismatch(self, api):
        """PRD §3.5: "and the payload `edgar_ccc` must equal the issuer's
        current `edgar_ccc` (`ERR_EDGAR_CREDENTIAL_MISMATCH`)."
        PRD §2.10: "Because system-generated drafts (the automatic Form 4 on
        confirmation, the Form 3 on designation or reinstatement, the Form 5 on
        sweep) carry a null `prepared_by_user_id`, any properly authorized
        agent may submit them."

        Design: Difficulty/priority_pair_validation_conflict/submit_sod_and_bad_credentials_sod_wins
        """
        issuer, person, filing = self._setup_manual_form3_ready(api)
        # agent_1 is authorized and is not the preparer: only the credential
        # check fails.
        resp = api.submit_filing(filing["id"], {"edgar_ccc": "WRONGCCC"},
                                 make_filing_agent_headers("agent_1"))
        validate_error(resp, ApiErrorId.ERR_EDGAR_CREDENTIAL_MISMATCH)


class TestSubmitStateAndCredentials:
    def test_submit_draft_filing_returns_invalid_state(self, api):
        """PRD §3.5: "At submit time the filing must be `READY`
        (`ERR_FILING_INVALID_STATE`)"

        Design: Corner/state_machines/submit_draft_filing_returns_invalid_state
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"])
        form3 = find_draft_form(person["id"], "FORM_3")
        resp = api.submit_filing(form3["id"], {"edgar_ccc": "CCC12345"},
                                 make_filing_agent_headers("agent_1"))
        validate_error(resp, ApiErrorId.ERR_FILING_INVALID_STATE)

    def test_edgar_credential_rotation_invalidates_old_ccc(self, api):
        """PRD §3.1: "Because every EDGAR submission must present the issuer's
        current confirmation code, changing `edgar_ccc` changes what a filing
        agent must supply from that moment on."
        PRD §3.5: "and the payload `edgar_ccc` must equal the issuer's current
        `edgar_ccc` (`ERR_EDGAR_CREDENTIAL_MISMATCH`)."

        Design: Corner/validations/edgar_credential_rotation_invalidates_old_ccc
        """
        issuer = create_issuer()
        authorize_filing_agent(issuer["id"], agent_user_id="agent_1")
        person = create_active_person(issuer["id"])
        txn = ingest_transaction(person["id"], transaction_date="2026-08-01",
                                 shares=100, price_per_share=10.00)
        confirm_transaction(txn["id"])
        form4 = find_draft_form(person["id"], "FORM_4")
        ready_filing(form4["id"])
        updated = get_success_data(api.update_issuer(
            issuer["id"],
            {"expected_issuer_version": issuer["version"],
             "edgar_ccc": "CCC99999"},
            make_compliance_officer_headers()))
        assert updated["edgar_ccc"] == "CCC99999"
        resp = api.submit_filing(form4["id"], {"edgar_ccc": "CCC12345"},
                                 make_filing_agent_headers("agent_1"))
        validate_error(resp, ApiErrorId.ERR_EDGAR_CREDENTIAL_MISMATCH)
        resp = api.submit_filing(form4["id"], {"edgar_ccc": "CCC99999"},
                                 make_filing_agent_headers("agent_1"))
        data = validate_success(resp, 200)
        assert data["status"] == "SUBMITTED", (
            f"Current CCC must be accepted, got {data['status']}")


class TestAuthorizationLifecycle:
    def test_revoke_revoked_authorization_returns_invalid_state(self, api):
        """PRD §3.5: "revocation — permitted only while `ACTIVE`, failing
        otherwise with `ERR_AUTHORIZATION_INVALID_STATE` — moves one to the
        terminal `REVOKED` state, after which that agent can no longer submit
        or record EDGAR results for the issuer."

        Design: Corner/state_machines/revoke_revoked_authorization_returns_invalid_state
        """
        issuer = create_issuer()
        auth = authorize_filing_agent(issuer["id"], agent_user_id="agent_1")
        resp = api.revoke_filing_agent_authorization(
            auth["id"], make_compliance_officer_headers())
        validate_success(resp, 200)
        resp = api.revoke_filing_agent_authorization(
            auth["id"], make_compliance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_INVALID_STATE)


class TestFilingListPagination:
    def test_filing_list_pagination_envelope(self, api):
        """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items and defaults to 0."

        Design: Corner/entities/filing_list_pagination_envelope
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"],
                                      designate_at="2026-08-03T09:00:00Z")
        txn = ingest_transaction(person["id"], transaction_date="2026-08-03",
                                 shares=100, price_per_share=10.00)
        confirm_transaction(txn["id"])
        # Person now has 2 filings: the designation Form 3 and the auto Form 4.
        resp = api.list_filings(
            make_compliance_officer_headers(),
            params={"reporting_person_id": person["id"], "limit": 1,
                    "offset": 0})
        data, meta = validate_paginated(resp)
        body = resp.json()
        assert body["response_type"] == "array", (
            f"List endpoint must report response_type 'array', "
            f"got {body['response_type']}")
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert len(data) == 1, f"Expected 1 row under limit=1, got {len(data)}"
        assert meta["total_count"] == 2, (
            f"Expected total_count 2, got {meta['total_count']}")
        assert meta["has_more"] is True, "Expected has_more true"
        assert meta["limit"] == 1 and meta["offset"] == 0


class TestForm4DeadlineHolidaySkipping:
    def test_form4_deadline_skips_weekend_and_holiday(self, api):
        """PRD §2.6: "Advancing a date by a given number of business days works
        as an iterative routine: for each business day owed, move the date
        forward by one calendar day; if the landing day is a Saturday, a
        Sunday, or a date listed in the issuer's `holiday_dates` (a list of
        `YYYY-MM-DD` strings), keep moving forward one calendar day at a time —
        still within the same step — until the date falls on a weekday that is
        not a listed holiday; that completes one step, and the routine repeats
        until the full number of owed steps has elapsed."
        PRD §3.4: "A `FORM_4` is due two business days after the earliest
        `transaction_date` among the transactions it covers, advanced per the
        business-day routine of §2.6 against the issuer's `holiday_dates` as
        they stood when the filing was created."

        Design: Corner/calculations/form4_deadline_skips_weekend_and_holiday
        """
        issuer = create_issuer(holiday_dates=["2026-08-10"])
        person = create_active_person(issuer["id"],
                                      designate_at="2026-08-03T09:00:00Z")
        txn = ingest_transaction(person["id"], transaction_date="2026-08-06",
                                 shares=100, price_per_share=10.00)
        set_clock("2026-08-06T09:00:00Z")
        confirm_transaction(txn["id"])
        form4 = find_draft_form(person["id"], "FORM_4")
        # 2026-08-06 (Thu): step 1 lands 08-07 (Fri); step 2 skips 08-08 (Sat),
        # 08-09 (Sun), 08-10 (listed holiday) and lands 08-11 (Tue).
        assert form4["filing_deadline"] == "2026-08-11", (
            f"Expected deadline 2026-08-11 after weekend+holiday skip, "
            f"got {form4['filing_deadline']}")

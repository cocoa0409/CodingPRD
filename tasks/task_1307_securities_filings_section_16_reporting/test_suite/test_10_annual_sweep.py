"""The annual Form 3/5 sweep: fiscal window, per-person results, Form 5
auto-creation, duplicate rejection, and terminal-state lockdown (PRD §3.8)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId,
    make_compliance_officer_headers, make_equity_plan_admin_headers,
    create_issuer, create_active_person, create_annual_sweep,
    authorize_filing_agent, get_person, get_filing, find_draft_form,
    set_clock, ingest_transaction, confirm_transaction, ready_filing,
    submit_filing, record_edgar_acceptance,
)


class TestSweepLifecycle:
    def test_run_completed_sweep_returns_invalid_state(self, api):
        """PRD §3.8: "Running the sweep is permitted only while it is `OPEN`
        (otherwise `ERR_SWEEP_INVALID_STATE`); the run stamps `run_at` from the
        logical clock, computes one result row per in-scope person, and moves
        the sweep to the terminal `COMPLETED` state."

        Design: Corner/state_machines/run_completed_sweep_returns_invalid_state
        """
        issuer = create_issuer()
        sweep = create_annual_sweep(issuer["id"], fiscal_year=2026)
        completed = get_success_data(api.run_annual_sweep(
            sweep["id"], make_compliance_officer_headers()))
        assert completed["status"] == "COMPLETED", (
            f"First run must complete the sweep, got {completed['status']}")
        resp = api.run_annual_sweep(sweep["id"],
                                    make_compliance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_SWEEP_INVALID_STATE)

    def test_duplicate_sweep_rejected(self, api):
        """PRD §3.8: "Only one sweep may exist per issuer and fiscal year
        across the `OPEN` and `COMPLETED` states; a duplicate creation is
        rejected with `ERR_DUPLICATE_SWEEP`."

        Design: Corner/validations/duplicate_sweep_rejected
        """
        issuer = create_issuer()
        create_annual_sweep(issuer["id"], fiscal_year=2026)
        resp = api.create_annual_sweep(
            {"issuer_id": issuer["id"], "fiscal_year": 2026},
            make_compliance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SWEEP)
        # Uniqueness is scoped to (issuer, fiscal_year): another year succeeds.
        other = api.create_annual_sweep(
            {"issuer_id": issuer["id"], "fiscal_year": 2025},
            make_compliance_officer_headers())
        validate_success(other, 201)


class TestSweepRun:
    def test_annual_sweep_run_generates_form5_and_results(self, api):
        """PRD §3.8: "The system computes the fiscal window at creation:
        `fy_end_date` is the last calendar day of the issuer's
        `fiscal_year_end_month` in that `fiscal_year`, and `fy_start_date` is
        the day after the prior fiscal year's end — equivalently one year
        before `fy_end_date` plus one day — with both bounds inclusive."
        PRD §3.8: "a `needs_form5` flag that is true exactly when the
        unreported exempt count is greater than zero; a `delinquent` flag that
        is true exactly when the window late-filing count is greater than zero"
        PRD §3.8: "For each person flagged `needs_form5`, the run automatically
        creates a `DRAFT` `FORM_5` filing with a null `prepared_by_user_id`,
        attaches that person's unreported exempt transactions, sets the
        `filing_deadline` forty-five calendar days after `fy_end_date`, records
        the new filing's id in the row's `form5_filing_id`, and raises that
        person's `open_obligation_count` by one."
        PRD §2.11: "`open_obligation_count` on a reporting person counts that
        person's filings in `DRAFT`, `READY`, or `SUBMITTED` status; filings in
        `ACCEPTED`, `REJECTED`, `SUPERSEDED`, or `DISCARDED` do not count."

        Design: Corner/endpoints/annual_sweep_run_generates_form5_and_results
        """
        issuer = create_issuer()
        authorize_filing_agent(issuer["id"], agent_user_id="agent_1")
        person = create_active_person(issuer["id"],
                                      designate_at="2026-08-03T09:00:00Z")
        # Unreported exempt gift (code G): confirmed, unfiled, in-window.
        gift = get_success_data(api.create_transaction(
            {"reporting_person_id": person["id"],
             "transaction_date": "2026-08-05", "transaction_code": "G",
             "security_type": "COMMON_STOCK", "shares": 25},
            make_equity_plan_admin_headers("epa_1")))
        # A purchase whose Form 4 will be accepted late (deadline 2026-08-10).
        purchase = ingest_transaction(person["id"],
                                      transaction_date="2026-08-06",
                                      shares=100, price_per_share=10.00)
        set_clock("2026-08-06T09:00:00Z")
        confirm_transaction(gift["id"])
        confirm_transaction(purchase["id"])
        form4 = find_draft_form(person["id"], "FORM_4")
        ready_filing(form4["id"])
        submit_filing(form4["id"], edgar_ccc="CCC12345", agent_id="agent_1")
        set_clock("2026-08-11T09:00:00Z")
        accepted = record_edgar_acceptance(
            form4["id"], accession_number="0000000001-26-000014",
            agent_id="agent_1")
        assert accepted["is_late"] is True

        sweep = create_annual_sweep(issuer["id"], fiscal_year=2026)
        assert sweep["fy_start_date"] == "2026-01-01", (
            f"FY2026 window starts 2026-01-01, got {sweep['fy_start_date']}")
        assert sweep["fy_end_date"] == "2026-12-31", (
            f"FY2026 window ends 2026-12-31, got {sweep['fy_end_date']}")

        completed = get_success_data(api.run_annual_sweep(
            sweep["id"], make_compliance_officer_headers()))
        assert completed["status"] == "COMPLETED"
        results = completed["results"]
        assert len(results) == 1, (
            f"Exactly one in-scope person expected, got {len(results)}")
        row = results[0]
        assert row["reporting_person_id"] == person["id"]
        assert row["late_filing_count"] == 1, (
            f"One late in-window acceptance, got {row['late_filing_count']}")
        assert row["unreported_exempt_count"] == 1, (
            f"One unreported gift, got {row['unreported_exempt_count']}")
        assert row["needs_form5"] is True
        assert row["delinquent"] is True
        assert row["form5_filing_id"], "Row must record the created Form 5 id"

        form5 = get_filing(row["form5_filing_id"])
        assert form5["form_type"] == "FORM_5"
        assert form5["status"] == "DRAFT"
        # 2026-12-31 + 45 calendar days = 2027-02-14.
        assert form5["filing_deadline"] == "2027-02-14", (
            f"Form 5 deadline must be 2027-02-14, got {form5['filing_deadline']}")
        assert form5.get("prepared_by_user_id") is None

        # The sweep attaches the unreported gift to the Form 5.
        resp = api.list_transactions(
            make_compliance_officer_headers(),
            params={"filing_id": form5["id"], "limit": 100})
        attached, _ = validate_paginated(resp)
        assert [t["id"] for t in attached] == [gift["id"]], (
            f"Form 5 must attach exactly the unreported gift, "
            f"got {[t['id'] for t in attached]}")

        # Obligations: designation Form 3 (DRAFT) + sweep Form 5 (DRAFT);
        # the accepted Form 4 no longer counts.
        person_after = get_person(person["id"])
        assert person_after["open_obligation_count"] == 2, (
            f"Expected open_obligation_count 2 after the sweep, "
            f"got {person_after['open_obligation_count']}")

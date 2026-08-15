"""Filing amendments (OCC-guarded, supersession cascade) and manual Form 4
attachment rules (PRD §2.9, §3.5)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_compliance_officer_headers, make_filing_coordinator_headers,
    make_equity_plan_admin_headers,
    create_issuer, create_active_person, find_draft_form,
    ingest_transaction, confirm_transaction, ready_filing, submit_filing,
    record_edgar_acceptance, setup_accepted_auto_form4, get_filing,
)


class TestAmendmentSupersession:
    def test_amendment_acceptance_supersedes_original(self, api):
        """PRD §3.5: "when the accepted filing is an amendment (its
        `amends_filing_id` set), the filing it amends moves automatically from
        `ACCEPTED` to the terminal `SUPERSEDED` state"
        PRD §3.5: "Creation increments the amended filing's `version` by one;
        the new `DRAFT` copies the amended filing's `issuer_id`,
        `reporting_person_id`, `form_type`, and `filing_deadline`, records
        `amends_filing_id` pointing at the amended filing, stamps
        `prepared_by_user_id` with the coordinator, and raises the person's
        `open_obligation_count` by one."

        Design: Corner/state_machines/amendment_acceptance_supersedes_original
        """
        scenario = setup_accepted_auto_form4(
            txn_overrides={"transaction_date": "2026-08-01", "shares": 100,
                           "price_per_share": 10.00},
            accession_number="0000000001-26-000011")
        original = get_filing(scenario["form4"]["id"])
        amendment = get_success_data(api.create_amendment(
            original["id"],
            {"expected_filing_version": original["version"]},
            make_filing_coordinator_headers("coord_1")))
        assert amendment["amends_filing_id"] == original["id"], (
            f"Amendment must reference the original filing, "
            f"got {amendment['amends_filing_id']}")
        assert amendment["status"] == "DRAFT"
        assert amendment.get("prepared_by_user_id") == "coord_1"
        ready_filing(amendment["id"])
        submit_filing(amendment["id"], edgar_ccc="CCC12345", agent_id="agent_1")
        accepted = record_edgar_acceptance(
            amendment["id"], accession_number="0000000001-26-000012",
            agent_id="agent_1")
        assert accepted["status"] == "ACCEPTED", (
            f"Amendment must reach ACCEPTED, got {accepted['status']}")
        superseded = get_filing(original["id"])
        assert superseded["status"] == "SUPERSEDED", (
            f"Original must be SUPERSEDED on amendment acceptance, "
            f"got {superseded['status']}")


class TestAmendmentOcc:
    def test_amendment_create_stale_version_returns_412(self, api):
        """PRD §2.9: "Creating an amendment — `POST
        /filings/{filingId}/amendments` — requires `expected_filing_version`
        equal to the amended filing's current `version`; a mismatch is likewise
        rejected with `ERR_STALE_VERSION` (HTTP 412), because a new amendment
        supersedes any earlier pending amendment work. Successful amendment
        creation itself increments the amended filing's `version` by one."

        Design: Corner/validations/amendment_create_stale_version_returns_412
        """
        scenario = setup_accepted_auto_form4(
            txn_overrides={"transaction_date": "2026-08-01", "shares": 100,
                           "price_per_share": 10.00},
            accession_number="0000000001-26-000013")
        original = get_filing(scenario["form4"]["id"])
        observed_version = original["version"]
        first = api.create_amendment(
            original["id"], {"expected_filing_version": observed_version},
            make_filing_coordinator_headers("coord_1"))
        first_data = validate_success(first, 201)
        assert first_data["id"], "First amendment must be created"
        # The first creation advanced the amended filing's version, so the
        # stale observation must now be rejected.
        resp = api.create_amendment(
            original["id"], {"expected_filing_version": observed_version},
            make_filing_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestAmendmentTargetState:
    def test_amendment_target_not_accepted_rejected(self, api):
        """PRD §3.5: "A `FilingCoordinator` creates an amendment draft against
        a filing in `ACCEPTED` status — any other target state is rejected with
        `ERR_AMENDMENT_TARGET_NOT_ACCEPTED` — carrying `expected_filing_version`
        per §2.9."

        Design: Corner/validations/amendment_target_not_accepted_rejected
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"])
        form3 = find_draft_form(person["id"], "FORM_3")
        resp = api.create_amendment(
            form3["id"], {"expected_filing_version": form3["version"]},
            make_filing_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_TARGET_NOT_ACCEPTED)


class TestManualForm4Attachment:
    def test_manual_form4_attach_other_person_transaction(self, api):
        """PRD §3.5: "A manual `FORM_4` must carry `transaction_ids` naming
        transactions that are all `CONFIRMED`, all still unattached to any
        filing, and all belonging to the same person as the filing — any
        shortfall is rejected with `ERR_TRANSACTION_NOT_ATTACHABLE`"
        PRD §3.3: "Gifts (code `G`) generate no Form 4; they wait for the
        annual Form 5 sweep in §3.8."

        Design: Corner/validations/manual_form4_attach_other_person_transaction
        """
        issuer = create_issuer()
        p1 = create_active_person(issuer["id"], full_name="Dana Officer",
                                  person_cik="0001000001")
        p2 = create_active_person(issuer["id"], full_name="Eve Officer",
                                  person_cik="0001000002")
        # P1's confirmed gift: code G generates no auto Form 4, so it stays
        # CONFIRMED and unfiled. price_per_share is optional for code G (PRD
        # §3.3) and is omitted here.
        gift = get_success_data(api.create_transaction(
            {"reporting_person_id": p1["id"], "transaction_date": "2026-08-01",
             "transaction_code": "G", "security_type": "COMMON_STOCK",
             "shares": 25},
            make_equity_plan_admin_headers("epa_1")))
        confirm_transaction(gift["id"])
        resp = api.create_filing(
            {"issuer_id": issuer["id"], "reporting_person_id": p2["id"],
             "form_type": "FORM_4", "transaction_ids": [gift["id"]]},
            make_filing_coordinator_headers("coord_1"))
        validate_error(resp, ApiErrorId.ERR_TRANSACTION_NOT_ATTACHABLE)

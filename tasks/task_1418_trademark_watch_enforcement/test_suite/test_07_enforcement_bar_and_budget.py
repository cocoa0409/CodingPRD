"""Letter-issue preconditions: the coexistence enforcement bar, the budget
affordability gate, and their pipeline priority."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_letter,
    create_agreement,
    create_alert,
    create_takedown,
    draft_letter,
    execute_agreement,
    get_agreement,
    get_client,
    get_letter,
    make_associate_headers,
    propose_agreement,
    set_clock,
    setup_approved_letter,
    setup_published_record,
    submit_letter_review,
    triage_alert,
    validate_error,
    validate_success,
)


class TestEnforcementBar:
    def _matter_letter_and_executed_agreement(self, budget=1000000):
        client, record, alert, matter, letter = setup_approved_letter(budget=budget)
        agreement = create_agreement(
            record["id"], territory_codes=["US"],
            effective_start="2026-09-01T00:00:00Z",
            effective_end="2027-09-01T00:00:00Z")
        propose_agreement(agreement["id"], agreement["version"],
                          terms_text="coexistence terms")
        execute_agreement(agreement["id"])
        return client, record, alert, matter, letter, agreement

    def test_letter_issue_barred_by_active_coexistence(self, api):
        """PRD §3.6: "No coexistence agreement on the matter's record may be in
        `EXECUTED`, `MONITORING`, `BREACH_ALLEGED`, or `CURE_PERIOD` — a live
        agreement bars enforcement and the issue is rejected with
        `ERR_ENFORCEMENT_BARRED`."

        Design: Difficulty/cross_entity_state_dependency/letter_issue_barred_by_active_coexistence
        """
        client, _, _, _, letter, _ = self._matter_letter_and_executed_agreement()
        res = api.issue_letter(letter["id"], make_associate_headers("assoc_1"))
        validate_error(res, ApiErrorId.ERR_ENFORCEMENT_BARRED, expected_status=409)
        assert get_letter(letter["id"])["status"] == "APPROVED"
        assert get_client(client["id"])["budget_spent_cents"] == 0

    def test_enforcement_bar_lifts_on_expiry(self, api):
        """PRD §3.8: "From execution onward, the live agreement bars cease-and-desist
        issuance on that record per §3.6, until the bar lifts on expiry or
        termination."
        PRD §3.8: "The clock sweep moves an `EXECUTED` agreement to `MONITORING` once
        its `effective_start` arrives, and from `MONITORING` to `EXPIRED` once
        `effective_end` arrives, lifting the enforcement bar."

        Design: Difficulty/cross_entity_state_dependency/letter_issue_barred_by_active_coexistence
        """
        client, _, _, _, letter, agreement = (
            self._matter_letter_and_executed_agreement())
        set_clock("2027-09-01T00:00:00Z")
        assert get_letter(letter["id"])["status"] == "APPROVED"
        assert get_agreement(agreement["id"])["status"] == "EXPIRED"

        issued = validate_success(
            api.issue_letter(letter["id"], make_associate_headers("assoc_1")), 200)
        assert issued["status"] == "ISSUED"
        assert get_client(client["id"])["budget_spent_cents"] == 75000


class TestIssuePriorityAndBudget:
    def test_safety_beats_fiscal_on_letter_issue(self, api):
        """PRD §2.10: "Every request is validated against an ordered pipeline; an
        earlier failure masks later ones, so callers always see the highest-priority
        applicable error."
        PRD §2.10: "8. **Enforcement bar** — a live coexistence agreement barring
        letter issuance surfaces `ERR_ENFORCEMENT_BARRED`."
        PRD §2.10: "23. **Fiscal** — affordability of the fee being accrued, else
        `ERR_BUDGET_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_letter_issue
        """
        # Budget 100000: the first issue consumes 75000, leaving 25000 < 75000.
        client, record, alert, matter, letter1 = setup_approved_letter(
            budget=100000, response_due_days=14)
        validate_success(api.issue_letter(letter1["id"],
                                          make_associate_headers("assoc_1")), 200)

        letter2 = draft_letter(matter["id"], user_id="assoc_1",
                               demand_type="DELIST_MARKETPLACE", response_due_days=14)
        submit_letter_review(letter2["id"], user_id="assoc_1")
        approve_letter(letter2["id"], approver_id="partner_1")

        agreement = create_agreement(record["id"], territory_codes=["US"],
                                     effective_start="2026-09-01T00:00:00Z",
                                     effective_end="2027-09-01T00:00:00Z")
        propose_agreement(agreement["id"], agreement["version"],
                          terms_text="coexistence terms")
        execute_agreement(agreement["id"])

        res = api.issue_letter(letter2["id"], make_associate_headers("assoc_1"))
        validate_error(res, ApiErrorId.ERR_ENFORCEMENT_BARRED, expected_status=409)
        assert get_letter(letter2["id"])["status"] == "APPROVED"
        # No further fee accrued: still exactly the first issue's 75000.
        assert get_client(client["id"])["budget_spent_cents"] == 75000

    def test_budget_exceeded_when_no_enforcement_bar(self, api):
        """PRD §3.6: "And the client's `budget_remaining_cents` must cover the
        75000-cent issuance fee, else `ERR_BUDGET_EXCEEDED`."
        PRD §2.6: "Forward fee actions check affordability against
        `budget_remaining_cents` and are rejected with `ERR_BUDGET_EXCEEDED` (HTTP
        422) when the remaining budget would not cover the fee"

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_letter_issue
        """
        client, _, _, matter, letter1 = setup_approved_letter(budget=100000,
                                                              response_due_days=14)
        validate_success(api.issue_letter(letter1["id"],
                                          make_associate_headers("assoc_1")), 200)
        letter2 = draft_letter(matter["id"], user_id="assoc_1",
                               demand_type="DELIST_MARKETPLACE", response_due_days=14)
        submit_letter_review(letter2["id"], user_id="assoc_1")
        approve_letter(letter2["id"], approver_id="partner_1")

        res = api.issue_letter(letter2["id"], make_associate_headers("assoc_1"))
        validate_error(res, ApiErrorId.ERR_BUDGET_EXCEEDED, expected_status=422)
        assert get_letter(letter2["id"])["status"] == "APPROVED"
        assert get_client(client["id"])["budget_spent_cents"] == 75000


class TestTakedownBudget:
    def test_takedown_file_budget_exceeded(self, api, paralegal_headers):
        """PRD §2.6: "Takedown filing fees depend on the platform: 15000 cents for
        `AMAZON`, 12000 for `EBAY`, 18000 for `ALIBABA`, 9000 for `META`, and 25000
        for `DOMAIN_REGISTRAR`; the fee is computed at draft time onto the filing's
        `fee_cents` and accrued when the filing is filed."
        PRD §3.7: "Filing the draft requires the alert to be in `TRIAGED`,
        `UNDER_ASSESSMENT`, `MONITORING`, or `ESCALATED` (any other alert state,
        including `NEW` or `DISMISSED`, is `ERR_INVALID_STATE`), the alert's record
        to be anything but `CANCELLED`, and the client's remaining budget to cover
        `fee_cents` (`ERR_BUDGET_EXCEEDED`); on filing, the fee accrues to the client
        budget."

        Design: Corner/validations/takedown_file_budget_exceeded
        """
        client, record = setup_published_record(budget=10000, classes=(9,))
        alert = create_alert(record["id"], 60, 60, 60, source="MARKETPLACE_SWEEP",
                             conflicting_mark_text="TYNY", conflicting_owner="Shop")
        alert = triage_alert(alert["id"])
        filing = create_takedown(alert["id"], platform="AMAZON", basis="TRADEMARK",
                                 listing_url="https://amazon.example/item/1")
        assert filing["fee_cents"] == 15000
        assert filing["status"] == "DRAFT"

        res = api.file_takedown(filing["id"], paralegal_headers)
        validate_error(res, ApiErrorId.ERR_BUDGET_EXCEEDED, expected_status=422)
        refreshed = validate_success(api.get_takedown_filing(filing["id"],
                                                             paralegal_headers), 200)
        assert refreshed["status"] == "DRAFT"
        assert get_client(client["id"])["budget_spent_cents"] == 0

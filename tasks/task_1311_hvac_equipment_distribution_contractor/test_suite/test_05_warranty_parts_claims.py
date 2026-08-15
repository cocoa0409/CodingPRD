"""Warranty registration lifecycle, parts-claim adjudication, and coverage math."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    get_success_data, make_contractor_headers, TEST_USERS, ApiErrorId,
    set_clock, setup_warranty_scenario, claim_decision, file_claim,
)

ADMIN = TEST_USERS["distributor_admin_headers"]
PROCESSOR = TEST_USERS["warranty_processor_headers"]


class TestBeginReviewRegistrationGate:
    def test_begin_review_requires_registered_registration(self, api):
        """PRD §3.6: "Beginning review (`BEGIN_REVIEW`) moves `SUBMITTED` → `UNDER_REVIEW` and carries a cross-entity gate: the anchored registration must be `REGISTERED` at that moment, failing which the decision is rejected with `ERR_WARRANTY_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/claim_review_requires_registration_registered
        """
        set_clock("2026-06-10T00:00:00Z")
        ctx = setup_warranty_scenario(install_date="2026-06-05T00:00:00Z",
                                      failure_date="2026-06-08T00:00:00Z",
                                      register=False)
        assert ctx["registration"]["status"] == "PENDING_REGISTRATION", "setup"
        res = api_client.parts_claim_decision(
            ctx["claim"]["id"], {"action": "BEGIN_REVIEW"}, PROCESSOR)
        validate_error(res, ApiErrorId.ERR_WARRANTY_NOT_ACTIVE)
        claim = get_success_data(api_client.get_parts_claim(ctx["claim"]["id"], ADMIN))
        assert claim["status"] == "SUBMITTED"

    def test_begin_review_succeeds_once_registered(self, api):
        """PRD §3.6: "Beginning review (`BEGIN_REVIEW`) moves `SUBMITTED` → `UNDER_REVIEW` and carries a cross-entity gate: the anchored registration must be `REGISTERED` at that moment, failing which the decision is rejected with `ERR_WARRANTY_NOT_ACTIVE`."
        PRD §3.6: "**Registration** by the contractor moves the record to `REGISTERED` provided the logical clock is at or before `registration_deadline` — the boundary is inclusive, so registering exactly at the deadline succeeds — while a registration attempted after the deadline is rejected with `ERR_WINDOW_EXPIRED` (422)."

        Design: Difficulty/cross_entity_state_dependency/claim_review_requires_registration_registered
        """
        set_clock("2026-06-10T00:00:00Z")
        ctx = setup_warranty_scenario(install_date="2026-06-05T00:00:00Z",
                                      failure_date="2026-06-08T00:00:00Z",
                                      register=True)
        assert ctx["registration"]["status"] == "REGISTERED", "setup"
        reviewed = claim_decision(ctx["claim"]["id"], "BEGIN_REVIEW", PROCESSOR)
        assert reviewed["status"] == "UNDER_REVIEW"


class TestRevisionLoop:
    def _setup_claim(self):
        set_clock("2026-06-10T00:00:00Z")
        ctx = setup_warranty_scenario(install_date="2026-06-01T00:00:00Z",
                                      failure_date="2026-06-08T00:00:00Z",
                                      register=True)
        return ctx

    def test_revision_cycle_returns_to_submitted_and_counts(self, api):
        """PRD §3.6: "Requesting information (`REQUEST_INFO`) moves it to `MORE_INFO_REQUESTED`, from which the contractor resubmits — optionally supplying corrected `part_cost_cents` and `labor_cost_cents` — returning the claim to `SUBMITTED` and incrementing `revision_count`; at most three such revision cycles are permitted, and a resubmission attempted beyond the third is rejected with `ERR_REVISION_LIMIT` (422)."

        Design: Difficulty/non_linear_state_machine/parts_claim_revision_loop_cycles
        """
        ctx = self._setup_claim()
        claim = ctx["claim"]
        assert claim["revision_count"] == 0, "setup: fresh claim has no revisions"
        claim_decision(claim["id"], "BEGIN_REVIEW", PROCESSOR)
        claim_decision(claim["id"], "REQUEST_INFO", PROCESSOR)
        resubmitted = validate_success(api_client.resubmit_parts_claim(
            claim["id"], {}, make_contractor_headers(ctx["contractor"]["id"])), 200)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_count"] == 1

    def test_fourth_resubmit_rejected_at_revision_limit(self, api):
        """PRD §3.6: "Requesting information (`REQUEST_INFO`) moves it to `MORE_INFO_REQUESTED`, from which the contractor resubmits — optionally supplying corrected `part_cost_cents` and `labor_cost_cents` — returning the claim to `SUBMITTED` and incrementing `revision_count`; at most three such revision cycles are permitted, and a resubmission attempted beyond the third is rejected with `ERR_REVISION_LIMIT` (422)."

        Design: Difficulty/non_linear_state_machine/parts_claim_revision_loop_cycles
        """
        ctx = self._setup_claim()
        claim = ctx["claim"]
        headers = make_contractor_headers(ctx["contractor"]["id"])
        for _ in range(3):
            claim_decision(claim["id"], "BEGIN_REVIEW", PROCESSOR)
            claim_decision(claim["id"], "REQUEST_INFO", PROCESSOR)
            validate_success(api_client.resubmit_parts_claim(claim["id"], {}, headers), 200)
        claim_decision(claim["id"], "BEGIN_REVIEW", PROCESSOR)
        claim_decision(claim["id"], "REQUEST_INFO", PROCESSOR)
        res = api_client.resubmit_parts_claim(claim["id"], {}, headers)
        validate_error(res, ApiErrorId.ERR_REVISION_LIMIT)
        claim = get_success_data(api_client.get_parts_claim(claim["id"], ADMIN))
        assert claim["revision_count"] == 3
        assert claim["status"] == "MORE_INFO_REQUESTED"


class TestRegistrationLapseCascade:
    def _setup_lapsed_with_open_claim(self):
        set_clock("2026-06-20T00:00:00Z")
        ctx = setup_warranty_scenario(install_date="2026-06-01T00:00:00Z",
                                      failure_date="2026-06-20T00:00:00Z",
                                      register=False)
        # registration_deadline is install_date + 60 days == 2026-07-31T00:00:00Z
        set_clock("2026-08-01T00:00:00Z")
        return ctx

    def test_lapse_denies_open_claim(self, api):
        """PRD §3.6: "Should the clock pass the deadline with the record still pending, it lapses automatically to `LAPSED` at the next read or transition (the lazy sweep of §2.4), and the lapse cascades: every parts claim anchored to the registration that sits in `SUBMITTED` or `MORE_INFO_REQUESTED` is auto-denied, each such claim's `total_award_cents` remaining 0 and its revision loop terminating."

        Design: Difficulty/transitive_cascade/registration_lapse_denies_open_claim
        """
        ctx = self._setup_lapsed_with_open_claim()
        registration = get_success_data(api_client.get_warranty_registration(
            ctx["registration"]["id"], ADMIN))
        assert registration["status"] == "LAPSED"
        claim = get_success_data(api_client.get_parts_claim(ctx["claim"]["id"], ADMIN))
        assert claim["status"] == "DENIED", (
            "the lapse cascade auto-denies the anchored open claim")
        assert claim["total_award_cents"] == 0

    def test_lapsed_registration_keeps_base_coverage_and_never_registered(self, api):
        """PRD §3.6: "The server derives `registration_deadline` as exactly sixty days after `install_date`, and the record begins in `PENDING_REGISTRATION` with `registered_at` empty and `extended_coverage_years` at its base value of 5."
        PRD §3.6: "Should the clock pass the deadline with the record still pending, it lapses automatically to `LAPSED` at the next read or transition (the lazy sweep of §2.4), and the lapse cascades: every parts claim anchored to the registration that sits in `SUBMITTED` or `MORE_INFO_REQUESTED` is auto-denied, each such claim's `total_award_cents` remaining 0 and its revision loop terminating."

        Design: Difficulty/transitive_cascade/registration_lapse_denies_open_claim
        """
        ctx = self._setup_lapsed_with_open_claim()
        registration = get_success_data(api_client.get_warranty_registration(
            ctx["registration"]["id"], ADMIN))
        assert registration["status"] == "LAPSED"
        assert registration["extended_coverage_years"] == 5, (
            "a lapsed registration never earned the ten-year extension")
        assert registration.get("registered_at") in (None, ""), (
            "a lapsed registration was never registered")


class TestWarrantyCoverageCalculation:
    def test_age_six_years_covers_half_parts_no_labor(self, api):
        """PRD §3.6: "The coverage horizon is the registration's `extended_coverage_years` — ten when the unit was registered on time, five otherwise."
        PRD §3.6: "Within the horizon, parts are covered at one hundred percent of `part_cost_cents` when the age is at most one year, seventy-five percent when the age is at most five years, and fifty percent thereafter, rounded half-up to the cent."
        PRD §3.6: "Labor is covered at fifty percent of `labor_cost_cents` only when the age is at most one year **and** the registration was completed on time (its `registered_at` is set); otherwise labor is not covered."

        Design: Corner/calculations/warranty_coverage_age_bands_and_labor_rule
        """
        set_clock("2020-08-15T00:00:00Z")
        ctx = setup_warranty_scenario(install_date="2020-08-01T00:00:00Z",
                                      failure_date="2020-08-01T00:00:00Z",
                                      register=True, with_claim=False)
        assert ctx["registration"]["extended_coverage_years"] == 10, (
            "setup: on-time registration extends coverage to ten years")
        set_clock("2026-08-05T00:00:00Z")
        claim = file_claim(ctx["registration"], ctx["contractor"],
                           "2026-08-04T00:00:00Z",
                           part_cost_cents=100_000, labor_cost_cents=40_000)
        claim_decision(claim["id"], "BEGIN_REVIEW", PROCESSOR)
        approved = claim_decision(claim["id"], "APPROVE", PROCESSOR)
        assert approved["status"] == "APPROVED"
        assert approved["covered_part_cents"] == 50_000, (
            f"age 6 falls in the fifty-percent band, got {approved['covered_part_cents']}")
        assert approved["covered_labor_cents"] == 0, (
            "labor is covered only within the first year")
        assert approved["total_award_cents"] == 50_000

    def test_first_year_covers_full_parts_and_half_labor(self, api):
        """PRD §3.6: "Within the horizon, parts are covered at one hundred percent of `part_cost_cents` when the age is at most one year, seventy-five percent when the age is at most five years, and fifty percent thereafter, rounded half-up to the cent."
        PRD §3.6: "Labor is covered at fifty percent of `labor_cost_cents` only when the age is at most one year **and** the registration was completed on time (its `registered_at` is set); otherwise labor is not covered."
        PRD §3.6: "The two covered amounts are rounded half-up per component and summed into `total_award_cents`, which is fixed at the moment of approval."

        Design: Corner/calculations/warranty_coverage_full_first_year
        """
        set_clock("2026-06-10T00:00:00Z")
        ctx = setup_warranty_scenario(install_date="2026-06-01T00:00:00Z",
                                      failure_date="2026-06-08T00:00:00Z",
                                      register=True)
        claim = ctx["claim"]
        claim_decision(claim["id"], "BEGIN_REVIEW", PROCESSOR)
        approved = claim_decision(claim["id"], "APPROVE", PROCESSOR)
        assert approved["status"] == "APPROVED"
        assert approved["covered_part_cents"] == 100_000
        assert approved["covered_labor_cents"] == 20_000
        assert approved["total_award_cents"] == 120_000


def test_warranty_processor_cannot_pay_claim(api):
    """PRD §2.1: "A `WarrantyProcessor` adjudicates parts claims — beginning review, approving, denying, and requesting more information — but may never pay one; payment of an approved claim is reserved to `DistributorAdmin`."
    PRD §2.1: "A request whose role is recognized but not permitted for the targeted endpoint or action is rejected with `ERR_UNAUTHORIZED` (HTTP 403) — for example, a `ContractorUser` attempting to qualify a rebate dossier."

    Design: Corner/roles/warranty_processor_cannot_pay_claim
    """
    set_clock("2026-06-10T00:00:00Z")
    ctx = setup_warranty_scenario(install_date="2026-06-01T00:00:00Z",
                                  failure_date="2026-06-08T00:00:00Z",
                                  register=True)
    claim = ctx["claim"]
    claim_decision(claim["id"], "BEGIN_REVIEW", PROCESSOR)
    approved = claim_decision(claim["id"], "APPROVE", PROCESSOR)
    assert approved["status"] == "APPROVED", "setup: claim must be APPROVED"
    res = api_client.parts_claim_decision(claim["id"], {"action": "PAY"}, PROCESSOR)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)
    claim = get_success_data(api_client.get_parts_claim(claim["id"], ADMIN))
    assert claim["status"] == "APPROVED"

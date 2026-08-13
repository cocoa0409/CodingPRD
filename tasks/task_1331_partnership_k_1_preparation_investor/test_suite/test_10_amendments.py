"""K-1 amendments: the IN_PREP/IN_REVIEW revision loop, segregation of duties
at issuance, the three-hop issue cascade, and the one-active-amendment bound."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, PREPARER_USER_ID, REVIEWER_USER_ID,
    make_tax_preparer_headers, make_tax_reviewer_headers,
    setup_k1_delivered, create_and_walk_amendment, get_k1_package,
    get_tax_year, create_k1_amendment_payload,
    assert_k1_amendment, assert_k1_package,
)

ADMIN = TEST_USERS["fund_tax_admin_headers"]
PREPARER = TEST_USERS["tax_preparer_headers"]
REVIEWER = TEST_USERS["tax_reviewer_headers"]

SINGLE_LP = [
    {
        "key": "lp", "legal_name": "LP", "partner_type": "US_INDIVIDUAL",
        "partner_class": "LIMITED", "residency_state": "CA",
        "ownership_pct_bps": 10000, "capital_commitment_cents": 1,
        "admission_date": "2025-01-01",
    },
]


class TestAmendmentRevisionLoop:
    def test_revision_loop_cycles_and_issues(self, api):
        """PRD §3.8: "A `TaxPreparer` starts preparation, moving it to
        `IN_PREP`, and later submits it for review, moving it to `IN_REVIEW`
        and recording `prepared_by_user_id`. A `TaxReviewer` may return it to
        preparation — `IN_REVIEW` back to `IN_PREP` — and this revision loop
        may cycle any number of times."
        PRD §3.8: "Issuance is the terminal step, taken by a `TaxReviewer`
        whose `X-User-ID` must differ from `prepared_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/non_linear_state_machine/k1_amendment_revision_loop_cycle
        """
        scenario = setup_k1_delivered(partner_specs=SINGLE_LP, delivery_method="EMAIL")
        k1 = scenario["k1"]
        am = create_and_walk_amendment(k1["id"], "ALLOCATION_CHANGE", stop_at="IN_REVIEW")
        returned = validate_success(api.return_amendment_to_prep(am["id"], REVIEWER), 200)
        assert returned["status"] == "IN_PREP", "first return-to-prep closes the first loop leg"
        resubmitted = validate_success(
            api.submit_amendment_review(am["id"], make_tax_preparer_headers(PREPARER_USER_ID)), 200,
        )
        assert resubmitted["status"] == "IN_REVIEW", "second submit re-enters review"
        issued = validate_success(
            api.issue_amendment(am["id"], make_tax_reviewer_headers(REVIEWER_USER_ID)), 200,
        )
        assert_k1_amendment(issued)
        assert issued["status"] == "ISSUED", (
            "the amendment must reach ISSUED after traversing the cycle"
        )

    def test_revision_loop_records_prepared_by_and_issued_by(self, api):
        """PRD §3.8: "A `TaxPreparer` starts preparation, moving it to
        `IN_PREP`, and later submits it for review, moving it to `IN_REVIEW`
        and recording `prepared_by_user_id`."
        PRD §3.8: "The amendment ends `ISSUED` with `issued_by_user_id`
        recorded."
        PRD §3.8: "Second, a replacement package is created with `generation`
        one higher than the amended package, `supersedes_k1_id` pointing at the
        amended package, preparation `GENERATED`, delivery `PENDING`, and a
        `line_snapshot` recomputed from the current `LOCKED` run; the
        amendment’s `new_k1_package_id` is set to the replacement’s id."

        Design: Difficulty/non_linear_state_machine/k1_amendment_revision_loop_cycle
        """
        scenario = setup_k1_delivered(partner_specs=SINGLE_LP)
        k1 = scenario["k1"]
        am = create_and_walk_amendment(k1["id"], "ALLOCATION_CHANGE", stop_at="IN_REVIEW")
        validate_success(api.return_amendment_to_prep(am["id"], REVIEWER), 200)
        validate_success(
            api.submit_amendment_review(am["id"], make_tax_preparer_headers(PREPARER_USER_ID)), 200,
        )
        issued = validate_success(
            api.issue_amendment(am["id"], make_tax_reviewer_headers(REVIEWER_USER_ID)), 200,
        )
        assert issued["prepared_by_user_id"] == PREPARER_USER_ID
        assert issued["issued_by_user_id"] == REVIEWER_USER_ID
        assert issued["new_k1_package_id"], "issuance must link the replacement package"


class TestAmendmentIssueCascade:
    def _issued(self, api):
        """COMPLETED single-partner tax year; amendment on the delivered
        package walked to IN_REVIEW, then issued by a different user."""
        scenario = setup_k1_delivered(partner_specs=SINGLE_LP)
        assert scenario["k1"]["prep_status"] == "DELIVERED"
        assert get_tax_year(scenario["tax_year"]["id"])["status"] == "COMPLETED"
        am = create_and_walk_amendment(scenario["k1"]["id"], "LATE_K1_CORRECTION", stop_at="IN_REVIEW")
        issued = validate_success(
            api.issue_amendment(am["id"], make_tax_reviewer_headers(REVIEWER_USER_ID)), 200,
        )
        assert issued["status"] == "ISSUED"
        return scenario, issued

    def test_issue_supersedes_original_and_creates_generation_two(self, api):
        """PRD §3.8: "Issuing cascades in three hops. First, the amended
        package’s preparation becomes `SUPERSEDED`. Second, a replacement
        package is created with `generation` one higher than the amended
        package, `supersedes_k1_id` pointing at the amended package,
        preparation `GENERATED`, delivery `PENDING`, and a `line_snapshot`
        recomputed from the current `LOCKED` run; the amendment’s
        `new_k1_package_id` is set to the replacement’s id."
        PRD §3.8: "The package list may be filtered by `partner_id`,
        `tax_year_id`, `supersedes_k1_id`, `run_id`, and `prep_status`, and the
        amendments of a single package can be listed on the package itself."

        Design: Difficulty/transitive_cascade/amendment_issue_three_hop_cascade
        """
        scenario, issued = self._issued(api)
        k1 = scenario["k1"]
        original = get_k1_package(k1["id"])
        assert original["prep_status"] == "SUPERSEDED", "hop 1 supersedes the amended package"
        data, meta = validate_paginated(
            api.list_k1_packages(REVIEWER, params={"supersedes_k1_id": k1["id"]})
        )
        assert meta["total_count"] == 1, f"exactly one replacement package: {meta['total_count']}"
        replacement = data[0]
        assert_k1_package(replacement)
        assert replacement["generation"] == 2
        assert replacement["prep_status"] == "GENERATED"
        assert replacement["delivery_status"] == "PENDING"
        assert replacement["id"] == issued["new_k1_package_id"]

    def test_issue_opens_investor_ticket_and_reopens_year(self, api):
        """PRD §3.8: "Third, an investor ticket with category
        `AMENDED_K1_QUESTION` and status `OPEN` is auto-created for the
        package’s partner and tax year as investor communication. If the tax
        year had been `COMPLETED`, it returns to `APPROVED` because the
        replacement is not yet delivered."
        PRD §3.5: "`COMPLETED` is quiescent rather than absorbing — issuing a
        K-1 amendment for a package of the year reopens it to `APPROVED`,
        because the replacement package has not yet been delivered."

        Design: Difficulty/transitive_cascade/amendment_issue_three_hop_cascade
        """
        scenario, issued = self._issued(api)
        partner = scenario["partners"]["lp"]
        ty_id = scenario["tax_year"]["id"]
        data, meta = validate_paginated(
            api.list_tickets(
                REVIEWER,
                params={"partner_id": partner["id"], "category": "AMENDED_K1_QUESTION"},
            )
        )
        assert meta["total_count"] == 1, f"hop 3 auto-creates one investor ticket: {meta['total_count']}"
        ticket = data[0]
        assert ticket["status"] == "OPEN"
        assert ticket["partner_id"] == partner["id"]
        assert ticket["tax_year_id"] == ty_id
        assert get_tax_year(ty_id)["status"] == "APPROVED", (
            "issuing an amendment must reopen the COMPLETED year to APPROVED"
        )


class TestAmendmentBoundsAndSegregation:
    def test_amendment_already_active_rejected(self, api):
        """PRD §3.8: "The target package’s preparation must be `DELIVERED`,
        else `ERR_K1_NOT_DELIVERED`, and at most one amendment not yet `ISSUED`
        may exist per package, else `ERR_AMENDMENT_ALREADY_ACTIVE`."

        Design: Corner/validations/amendment_already_active_rejected
        """
        scenario = setup_k1_delivered(partner_specs=SINGLE_LP)
        k1 = scenario["k1"]
        create_and_walk_amendment(k1["id"], "PARTNER_DATA_FIX", stop_at="IN_PREP")
        resp = api.create_k1_amendment(
            create_k1_amendment_payload(k1["id"], reason="ALLOCATION_CHANGE"), PREPARER,
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_ALREADY_ACTIVE)

    def test_amendment_issue_by_preparer_rejected_sod(self, api):
        """PRD §3.8: "Issuance is the terminal step, taken by a `TaxReviewer`
        whose `X-User-ID` must differ from `prepared_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/amendment_issue_by_preparer_rejected_sod
        """
        scenario = setup_k1_delivered(partner_specs=SINGLE_LP)
        k1 = scenario["k1"]
        resp = api.create_k1_amendment(
            create_k1_amendment_payload(k1["id"], reason="STATE_REAPPORTIONMENT"), PREPARER,
        )
        am = validate_success(resp, 201)
        validate_success(api.start_amendment_prep(am["id"], PREPARER), 200)
        # submit-review records prepared_by_user_id == rev_1 (a preparer's header)
        validate_success(
            api.submit_amendment_review(am["id"], make_tax_preparer_headers(REVIEWER_USER_ID)), 200,
        )
        resp_issue = api.issue_amendment(am["id"], make_tax_reviewer_headers(REVIEWER_USER_ID))
        validate_error(resp_issue, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        amendments, meta = validate_paginated(api.list_k1_amendments(k1["id"], REVIEWER))
        current = [a for a in amendments if a["id"] == am["id"]][0]
        assert current["status"] == "IN_REVIEW", "rejected issue must leave the amendment IN_REVIEW"

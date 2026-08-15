"""Valuation allowance assessments: measurement branches, supersession, the
submit/return/approve loop, segregation of duties, RBAC, and OCC on the year
version.
"""
from test_helpers import (
    ApiErrorId,
    create_approved_allowance,
    create_draft_allowance,
    create_fy2026_tax_year,
    create_reviewed_difference,
    create_submitted_allowance,
    create_us_fed_jurisdiction,
    create_valuation_allowance_payload,
    current_tax_year_version,
    get_tax_year,
    make_tax_accountant_headers,
    make_tax_director_headers,
    make_tax_manager_headers,
    setup_open_year_with_jurisdiction,
    validate_error,
    validate_success,
)


class TestNestedMinMaxMeasurement:
    def test_mltn_true_allowance_uses_nested_min_max(
            self, api, tax_manager_headers):
        """PRD §3.3: "If `more_likely_than_not` is true, it computes an
        income-support figure by multiplying `projected_taxable_income_cents`
        by the year's `enacted_federal_rate_bp`, dividing by 10000, and
        rounding half up to integer cents; the realizable amount is the
        smaller of the total gross deferred tax asset and the sum of
        `reversing_dtl_cents` plus the income support; the allowance is then
        the total gross deferred tax asset minus the realizable amount,
        floored at zero."
        PRD §3.2: "Hop 3b: if the year has a valuation allowance assessment in
        `DRAFT` or `SUBMITTED`, its `allowance_amount_cents` recomputes
        against the updated deferred-asset pool (§3.3)."

        Design: Difficulty/combinatorial_formula/valuation_allowance_nested_min_max
        """
        ty, jur = setup_open_year_with_jurisdiction()
        va1 = create_draft_allowance(
            ty["id"], more_likely_than_not=True,
            projected_taxable_income_cents=1000000, reversing_dtl_cents=100000)
        assert va1["allowance_amount_cents"] == 0, "empty DTA pool -> 0"
        diff = create_reviewed_difference(ty["id"], jur["id"])

        validate_success(api.lock_difference(diff["id"], tax_manager_headers),
                         200)

        va1_after = validate_success(
            api.get_valuation_allowance(va1["id"], tax_manager_headers), 200)
        # DTA pool 630,000; income support round(1,000,000*2100/10000)=210,000
        # max(0, 630,000 - min(630,000, 100,000 + 210,000)) = 320,000
        assert va1_after["allowance_amount_cents"] == 320000

    def test_mltn_false_takes_full_allowance_and_supersedes_draft(
            self, api, tax_manager_headers):
        """PRD §3.3: "if `more_likely_than_not` is false, sets the allowance
        equal to that total gross asset (a full allowance)."
        PRD §3.3: "Creating an assessment supersedes any existing `DRAFT` or
        `SUBMITTED` assessment for the same year — those move to `SUPERSEDED`
        — and bumps the parent year's `version`."

        Design: Difficulty/combinatorial_formula/valuation_allowance_nested_min_max
        """
        ty, jur = setup_open_year_with_jurisdiction()
        va1 = create_draft_allowance(
            ty["id"], more_likely_than_not=True,
            projected_taxable_income_cents=1000000, reversing_dtl_cents=100000)
        diff = create_reviewed_difference(ty["id"], jur["id"])
        validate_success(api.lock_difference(diff["id"], tax_manager_headers),
                         200)

        va2 = create_draft_allowance(
            ty["id"], more_likely_than_not=False,
            projected_taxable_income_cents=1000000, reversing_dtl_cents=100000)

        # mltn=false bypasses the lattice: allowance = total gross DTA
        assert va2["allowance_amount_cents"] == 630000

        va1_after = validate_success(
            api.get_valuation_allowance(va1["id"], tax_manager_headers), 200)
        assert va1_after["status"] == "SUPERSEDED", \
            "the bare create of va2 supersedes the DRAFT va1"
        assert va2["status"] == "DRAFT"


class TestApproveSupersedesPrior:
    def test_approve_supersedes_prior_and_repoints_year(
            self, api, tax_manager_headers, tax_director_headers):
        """PRD §3.3: "On approval, any other `APPROVED` assessment for the
        same year transitions to `SUPERSEDED`; the year's
        `valuation_allowance_cents` becomes the newly approved
        `allowance_amount_cents` (0 whenever no assessment is `APPROVED`)"

        Design: Corner/state_machines/valuation_allowance_approve_supersedes_prior
        """
        ty, jur = setup_open_year_with_jurisdiction()
        diff = create_reviewed_difference(ty["id"], jur["id"])
        validate_success(api.lock_difference(diff["id"], tax_manager_headers),
                         200)

        va1 = create_approved_allowance(ty["id"], more_likely_than_not=False)
        assert va1["allowance_amount_cents"] == 630000
        year = get_tax_year(ty["id"])
        assert year["valuation_allowance_cents"] == 630000

        # The APPROVED va1 survives the bare create of va2.
        va2 = create_draft_allowance(
            ty["id"], more_likely_than_not=True,
            projected_taxable_income_cents=1000000, reversing_dtl_cents=100000)
        va1_mid = validate_success(
            api.get_valuation_allowance(va1["id"], tax_manager_headers), 200)
        assert va1_mid["status"] == "APPROVED"
        validate_success(api.submit_valuation_allowance(va2["id"],
                                                        tax_manager_headers),
                         200)
        va2_approved = validate_success(
            api.approve_valuation_allowance(va2["id"], tax_director_headers),
            200)
        assert va2_approved["status"] == "APPROVED"
        assert va2_approved["allowance_amount_cents"] == 320000

        va1_after = validate_success(
            api.get_valuation_allowance(va1["id"], tax_manager_headers), 200)
        assert va1_after["status"] == "SUPERSEDED"

        year_after = get_tax_year(ty["id"])
        assert year_after["valuation_allowance_cents"] == 320000, \
            "re-pointed from 630,000 to the newly approved amount"


class TestReturnReworkLoop:
    def test_return_rework_loop_cycles_back_to_draft(
            self, api, tax_manager_headers, tax_director_headers):
        """PRD §3.3: "the preparer submits a `DRAFT` (moving it to
        `SUBMITTED`, again only while the year is `OPEN`), and a `TaxDirector`
        either returns it — cycling `SUBMITTED` back to `DRAFT` with no other
        precondition — or approves it."

        Design: Corner/state_machines/valuation_allowance_return_rework_loop
        """
        ty = create_fy2026_tax_year()
        create_us_fed_jurisdiction()
        va = create_draft_allowance(ty["id"], more_likely_than_not=False)

        s1 = validate_success(
            api.submit_valuation_allowance(va["id"], tax_manager_headers),
            200)
        assert s1["status"] == "SUBMITTED"

        s2 = validate_success(
            api.return_valuation_allowance(va["id"], tax_director_headers),
            200)
        assert s2["status"] == "DRAFT"

        s3 = validate_success(
            api.submit_valuation_allowance(va["id"], tax_manager_headers),
            200)
        assert s3["status"] == "SUBMITTED"

        s4 = validate_success(
            api.approve_valuation_allowance(va["id"], tax_director_headers),
            200)
        assert s4["status"] == "APPROVED"


class TestRbacAndSegregation:
    def test_accountant_cannot_approve_allowance(self, api):
        """PRD §2.6: "**Authorization** — the caller's role is listed for the
        endpoint (`ERR_FORBIDDEN_FOR_ROLE`)."
        PRD §4: POST /tax/valuation-allowances/{allowanceId}/approve is
        authorized for TaxDirector only.

        Design: Corner/rbac/accountant_cannot_approve_allowance_forbidden
        """
        ty = create_fy2026_tax_year()
        va = create_submitted_allowance(ty["id"], more_likely_than_not=False)
        assert va["status"] == "SUBMITTED"

        res = api.approve_valuation_allowance(
            va["id"], make_tax_accountant_headers("acct-9"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE,
                       expected_status=403)

        after = validate_success(
            api.get_valuation_allowance(va["id"],
                                        make_tax_accountant_headers("acct-9")),
            200)
        assert after["status"] == "SUBMITTED"

    def test_preparer_cannot_approve_own_allowance(self, api):
        """PRD §3.3: "Approval enforces segregation of duties: the approving
        `X-User-ID` must differ from the recorded `prepared_by_user_id`, or
        the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)"

        Design: Corner/rbac/preparer_cannot_approve_own_allowance
        """
        ty = create_fy2026_tax_year()
        va = create_submitted_allowance(ty["id"], more_likely_than_not=False,
                                        preparer_user_id="mgr-1")
        assert va["prepared_by_user_id"] == "mgr-1"

        # Same operator id, even holding the TaxDirector role, cannot approve.
        res = api.approve_valuation_allowance(
            va["id"], make_tax_director_headers("mgr-1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=403)

        approved = validate_success(
            api.approve_valuation_allowance(
                va["id"], make_tax_director_headers("dir-2")), 200)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "dir-2"


class TestOptimisticConcurrency:
    def test_va_create_with_stale_year_version_rejected(self, api):
        """PRD §2.8: "**Creating a valuation allowance** requires the request
        to carry `expected_tax_year_version` matching the target year's
        current `version`. Creating legitimately supersedes any existing
        `DRAFT` or `SUBMITTED` assessment for the year, so a writer working
        from a stale year view would silently supersede an assessment it never
        saw; the stale-version check forces a re-read first. A mismatch is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/va_create_stale_version_412
        """
        ty = create_fy2026_tax_year()
        observed_version = current_tax_year_version(ty["id"])

        first = create_draft_allowance(
            ty["id"], more_likely_than_not=False,
            expected_tax_year_version=observed_version,
            preparer_user_id="mgr-1")
        assert first["status"] == "DRAFT"

        # The first create bumped the year's version, so the same observed
        # version is now stale.
        payload = create_valuation_allowance_payload(
            ty["id"], observed_version, more_likely_than_not=True,
            projected_taxable_income_cents=5000000, reversing_dtl_cents=0)
        res = api.create_valuation_allowance(
            payload, make_tax_manager_headers("mgr-2"))
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

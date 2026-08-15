"""Startup formation, the two equity-pricing variants, and
conflict-of-interest plan adjudication with its half-open overlap rule."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_coi_plan,
    assert_startup,
    create_approved_coi_plan,
    create_coi_plan,
    create_coi_plan_payload,
    create_inventor,
    create_startup_fixture,
    create_startup_payload,
    set_clock,
    setup_department_and_inventor,
    setup_patent_pursued_disclosure,
    submit_disclosure,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import api_client

ADMIN = TEST_USERS["system_admin_headers"]
TTO = TEST_USERS["tto_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CD = TEST_USERS["compliance_director_headers"]


class TestStartupEquityVariants:
    def test_startup_equity_fixed_vs_antidilution(self, api):
        """PRD: "Under `FIXED`, the university receives a flat 500 basis
        points regardless of valuation; the payload's
        `post_money_valuation_cents` is ignored. Under `ANTI_DILUTION`, the
        request must supply `post_money_valuation_cents` greater than 0 (its
        absence is `ERR_INVALID_REQUEST`); the raw stake is 800 basis points
        scaled by the ratio of a 1,000,000,000-cent base valuation to the
        supplied post-money valuation, the raw value is floored to an integer
        number of basis points, and the result is clamped to a floor of 200
        basis points and a cap of 1500 basis points."

        Design: Difficulty/dual_variant_calc/startup_equity_fixed_vs_antidilution
        """
        ctx = setup_patent_pursued_disclosure()
        disc_id = ctx["disclosure"]["id"]
        inv_id = ctx["entries"][0]["inventor_id"]
        su_fixed = create_startup_fixture(disc_id, "FixedCo", "FIXED")
        su_ad = create_startup_fixture(disc_id, "DiluteCo", "ANTI_DILUTION")
        create_approved_coi_plan(su_fixed["id"], inv_id)
        create_approved_coi_plan(su_ad["id"], inv_id)
        set_clock("2026-08-01T00:00:00Z")

        fixed = validate_success(api.issue_equity(su_fixed["id"], {}, TTO))
        assert fixed["university_equity_bp"] == 500, "FIXED grants a flat 500 bp"
        assert fixed["status"] == "EQUITY_ISSUED"
        ad = validate_success(api.issue_equity(
            su_ad["id"], {"post_money_valuation_cents": 2_000_000_000}, TTO))
        assert ad["university_equity_bp"] == 400, \
            "floor(800 * 1e9 / 2e9) = 400 bp"
        assert ad["status"] == "EQUITY_ISSUED"

    def test_fixed_equity_ignores_valuation_payload(self, api):
        """PRD: "Under `FIXED`, the university receives a flat 500 basis
        points regardless of valuation; the payload's
        `post_money_valuation_cents` is ignored."

        Design: Difficulty/dual_variant_calc/startup_equity_fixed_vs_antidilution
        """
        ctx = setup_patent_pursued_disclosure()
        inv_id = ctx["entries"][0]["inventor_id"]
        su = create_startup_fixture(ctx["disclosure"]["id"], "FixedCo", "FIXED")
        create_approved_coi_plan(su["id"], inv_id)
        set_clock("2026-08-01T00:00:00Z")
        result = validate_success(api.issue_equity(
            su["id"], {"post_money_valuation_cents": 9_999_999_999}, TTO))
        assert result["university_equity_bp"] == 500
        assert result["equity_issued"] is True

    def test_anti_dilution_clamps_at_floor_and_cap(self, api):
        """PRD: "the raw stake is 800 basis points scaled by the ratio of a
        1,000,000,000-cent base valuation to the supplied post-money
        valuation, the raw value is floored to an integer number of basis
        points, and the result is clamped to a floor of 200 basis points and
        a cap of 1500 basis points."

        Design: Corner/calculations/anti_dilution_clamps_at_floor_and_cap
        """
        ctx = setup_patent_pursued_disclosure()
        disc_id = ctx["disclosure"]["id"]
        inv_id = ctx["entries"][0]["inventor_id"]
        su_lo = create_startup_fixture(disc_id, "FloorCo", "ANTI_DILUTION")
        su_hi = create_startup_fixture(disc_id, "CapCo", "ANTI_DILUTION")
        create_approved_coi_plan(su_lo["id"], inv_id)
        create_approved_coi_plan(su_hi["id"], inv_id)
        set_clock("2026-08-01T00:00:00Z")
        floored = validate_success(api.issue_equity(
            su_lo["id"], {"post_money_valuation_cents": 10_000_000_000}, TTO))
        assert floored["university_equity_bp"] == 200, \
            "floor(800 * 1e9 / 1e10) = 80 -> clamped to the 200 bp floor"
        capped = validate_success(api.issue_equity(
            su_hi["id"], {"post_money_valuation_cents": 500_000_000}, TTO))
        assert capped["university_equity_bp"] == 1500, \
            "floor(800 * 1e9 / 5e8) = 1600 -> clamped to the 1500 bp cap"


class TestCoiCoverageGate:
    def test_issue_equity_requires_approved_covering_plan(self, api):
        """PRD: "Issue-equity is gated on live conflict coverage: at least
        one `APPROVED` plan for this startup must have a window covering the
        current clock — `coverage_start` at or before the clock and
        `coverage_end` strictly after it — or the issuance is refused with
        `ERR_COI_COVERAGE_REQUIRED`; issuing from any status other than
        `INCORPORATION` yields `ERR_STARTUP_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/startup_equity_requires_coi_coverage
        """
        ctx = setup_patent_pursued_disclosure()
        inv_id = ctx["entries"][0]["inventor_id"]
        su = create_startup_fixture(ctx["disclosure"]["id"], "SpinCo", "FIXED")
        set_clock("2026-08-01T00:00:00Z")
        # Plan filed but only SUBMITTED: approval is required.
        plan = create_coi_plan(su["id"], inv_id)
        resp = api.issue_equity(su["id"], {}, TTO)
        validate_error(resp, ApiErrorId.ERR_COI_COVERAGE_REQUIRED, 409)
        validate_success(api.approve_coi_plan(plan["id"], CD))
        issued = validate_success(api.issue_equity(su["id"], {}, TTO))
        assert issued["university_equity_bp"] == 500
        assert issued["status"] == "EQUITY_ISSUED"

    def test_issue_equity_approved_plan_must_cover_clock(self, api):
        """PRD: "at least one `APPROVED` plan for this startup must have a
        window covering the current clock — `coverage_start` at or before the
        clock and `coverage_end` strictly after it — or the issuance is
        refused with `ERR_COI_COVERAGE_REQUIRED`".

        Design: Difficulty/cross_entity_state_dependency/startup_equity_requires_coi_coverage
        """
        ctx = setup_patent_pursued_disclosure()
        inv_id = ctx["entries"][0]["inventor_id"]
        su = create_startup_fixture(ctx["disclosure"]["id"], "SpinCo", "FIXED")
        # APPROVED, but the window ended before the current clock.
        create_approved_coi_plan(
            su["id"], inv_id,
            coverage_start="2026-01-01T00:00:00Z",
            coverage_end="2026-07-01T00:00:00Z")
        set_clock("2026-08-01T00:00:00Z")
        resp = api.issue_equity(su["id"], {}, TTO)
        validate_error(resp, ApiErrorId.ERR_COI_COVERAGE_REQUIRED, 409)


class TestCoiWindowOverlap:
    def test_coi_window_half_open_overlap(self, api):
        """PRD: "Approval also re-checks the coverage window against every
        other `APPROVED` plan for the same startup and inventor: because
        windows are half-open, two plans overlap exactly when each starts
        before the other ends, and an overlap refuses the approval with
        `ERR_COI_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/coi_window_half_open_overlap
        """
        ctx = setup_patent_pursued_disclosure()
        disc_id = ctx["disclosure"]["id"]
        inv_id = ctx["entries"][0]["inventor_id"]
        su = create_startup_fixture(disc_id, "SpinCo")
        create_approved_coi_plan(su["id"], inv_id)

        # Adjacency is allowed: a plan starting exactly at the approved
        # plan's coverage_end does not overlap a half-open window.
        adjacent = validate_success(api.create_coi_plan(
            su["id"],
            create_coi_plan_payload(
                inv_id, coverage_start="2027-01-01T00:00:00Z",
                coverage_end="2028-01-01T00:00:00Z",
                management_plan_text="Adjacent renewal"), CO), 201)
        assert adjacent["status"] == "SUBMITTED"

        # One day inside the approved window collides.
        resp = api.create_coi_plan(
            su["id"],
            create_coi_plan_payload(
                inv_id, coverage_start="2026-12-31T00:00:00Z",
                coverage_end="2027-12-31T00:00:00Z",
                management_plan_text="Overlapping"), CO)
        validate_error(resp, ApiErrorId.ERR_COI_WINDOW_OVERLAP, 409)

    def test_coi_overlap_keyed_per_inventor(self, api):
        """PRD: "Approval also re-checks the coverage window against every
        other `APPROVED` plan for the same startup and inventor".

        Design: Difficulty/resource_temporal_overlap/coi_window_half_open_overlap
        """
        ctx = setup_patent_pursued_disclosure(share_vector=(6000, 4000))
        su = create_startup_fixture(ctx["disclosure"]["id"], "SpinCo")
        inv1 = ctx["entries"][0]["inventor_id"]
        inv2 = ctx["entries"][1]["inventor_id"]
        create_approved_coi_plan(su["id"], inv1)
        # Identical window, but a different inventor: no overlap conflict.
        other = validate_success(api.create_coi_plan(
            su["id"], create_coi_plan_payload(inv2), CO), 201)
        assert other["status"] == "SUBMITTED"

    def test_coi_create_referential_beats_constraint_overlap(self, api):
        """PRD: "The pipeline runs: ... sixth, segregation-of-duties and
        compliance gates ...; seventh, cross-entity referential usability
        (roster membership, federal-funding eligibility, pursued-patent
        prerequisites, the write-off review block, duplicate roster inventors
        — HTTP 422); eighth, intra-aggregate constraints such as share totals
        and window overlaps".
        PRD: "The named inventor must be on the roster of the startup's
        disclosure, else the filing is refused with
        `ERR_INVENTOR_NOT_ON_DISCLOSURE`."

        Design: Difficulty/priority_pair_validation_conflict/coi_create_referential_beats_constraint_overlap
        """
        ctx = setup_patent_pursued_disclosure()
        dept = ctx["depts"][0]
        outsider = create_inventor(dept["id"], "Bob Outsider", "bob@uni.edu",
                                   "STAFF")
        su = create_startup_fixture(ctx["disclosure"]["id"], "SpinCo")
        inv_id = ctx["entries"][0]["inventor_id"]
        create_approved_coi_plan(su["id"], inv_id)
        # The window overlaps the approved plan AND names a non-roster
        # inventor; the referential error wins.
        resp = api.create_coi_plan(
            su["id"],
            create_coi_plan_payload(
                outsider["id"], coverage_start="2026-06-01T00:00:00Z",
                coverage_end="2027-06-01T00:00:00Z",
                management_plan_text="Overlap window"), CO)
        validate_error(resp, ApiErrorId.ERR_INVENTOR_NOT_ON_DISCLOSURE, 422)

    def test_coi_create_nonroster_inventor_isolated(self, api):
        """PRD: "The named inventor must be on the roster of the startup's
        disclosure, else the filing is refused with
        `ERR_INVENTOR_NOT_ON_DISCLOSURE`."

        Design: Difficulty/priority_pair_validation_conflict/coi_create_referential_beats_constraint_overlap
        """
        ctx = setup_patent_pursued_disclosure()
        dept = ctx["depts"][0]
        outsider = create_inventor(dept["id"], "Bob Outsider", "bob@uni.edu",
                                   "STAFF")
        su = create_startup_fixture(ctx["disclosure"]["id"], "SpinCo")
        resp = api.create_coi_plan(su["id"], create_coi_plan_payload(outsider["id"]),
                                   CO)
        validate_error(resp, ApiErrorId.ERR_INVENTOR_NOT_ON_DISCLOSURE, 422)

    def test_date_window_end_before_start_rejected(self, api):
        """PRD: "a coverage window from `coverage_start` (inclusive) to
        `coverage_end` (exclusive, and strictly after the start)".
        PRD: "fourth, request-body schema conformance — required fields
        present, enum membership valid, integer ranges respected, unknown
        payload fields rejected — with `ERR_INVALID_REQUEST`".

        Design: Corner/validations/date_window_end_before_start_rejected
        """
        ctx = setup_patent_pursued_disclosure()
        inv_id = ctx["entries"][0]["inventor_id"]
        su = create_startup_fixture(ctx["disclosure"]["id"], "SpinCo")
        resp = api.create_coi_plan(
            su["id"],
            create_coi_plan_payload(
                inv_id, coverage_start="2027-01-01T00:00:00Z",
                coverage_end="2026-01-01T00:00:00Z",
                management_plan_text="Inverted"), CO)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestCoiReviewCycleAndDissolution:
    def test_coi_reject_revise_resubmit_cycle(self, api):
        """PRD: "A rejected plan is not dead: a `ComplianceOfficer` may
        revise it with new `coverage_start`, `coverage_end`, or
        `management_plan_text` values, which returns it to `SUBMITTED` and
        clears the `rejection_reason`; revision is defined only from
        `REJECTED` — otherwise `ERR_COI_NOT_REVISABLE`".
        PRD: "Rejection stores a `rejection_reason` and moves the plan to
        `REJECTED`."

        Design: Corner/state_machines/coi_reject_revise_resubmit_cycle
        """
        ctx = setup_patent_pursued_disclosure()
        inv_id = ctx["entries"][0]["inventor_id"]
        su = create_startup_fixture(ctx["disclosure"]["id"], "SpinCo")
        plan = create_coi_plan(su["id"], inv_id)

        # PATCH while SUBMITTED is not a defined revision.
        resp = api.revise_coi_plan(plan["id"], {"management_plan_text": "V1.1"}, CO)
        validate_error(resp, ApiErrorId.ERR_COI_NOT_REVISABLE, 409)

        rejected = validate_success(api.reject_coi_plan(
            plan["id"], {"rejection_reason": "Insufficient controls"}, CD))
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "Insufficient controls"

        revised = validate_success(api.revise_coi_plan(
            plan["id"], {"management_plan_text": "V2 with controls"}, CO))
        assert revised["status"] == "SUBMITTED", "revision returns the plan to SUBMITTED"
        assert revised.get("rejection_reason") is None

        approved = validate_success(api.approve_coi_plan(plan["id"], CD))
        assert approved["status"] == "APPROVED"

    def test_startup_dissolve_cascades_and_locks(self, api):
        """PRD: "Dissolution moves a startup from `INCORPORATION` or
        `EQUITY_ISSUED` to the terminal `DISSOLVED` state — any other state
        yields `ERR_STARTUP_INVALID_STATE` — and cascades to the conflict
        plans: every plan of that startup in `SUBMITTED` or `APPROVED` status
        moves to `TERMINATED`."

        Design: Corner/state_machines/startup_dissolve_cascades_and_locks
        """
        ctx = setup_patent_pursued_disclosure()
        inv_id = ctx["entries"][0]["inventor_id"]
        su = create_startup_fixture(ctx["disclosure"]["id"], "SpinCo", "FIXED")
        plan_ok = create_approved_coi_plan(su["id"], inv_id)
        plan_rej = create_coi_plan(
            su["id"], inv_id, coverage_start="2027-01-01T00:00:00Z",
            coverage_end="2028-01-01T00:00:00Z", management_plan_text="V2")
        validate_success(api.reject_coi_plan(plan_rej["id"],
                                             {"rejection_reason": "Weak"}, CD))
        set_clock("2026-08-01T00:00:00Z")
        validate_success(api.issue_equity(su["id"], {}, TTO))

        dissolved = validate_success(api.dissolve_startup(su["id"], TTO))
        assert dissolved["status"] == "DISSOLVED"
        ok_after = validate_success(api.get_coi_plan(plan_ok["id"], ADMIN))
        assert ok_after["status"] == "TERMINATED", \
            "the APPROVED plan is terminated by the dissolve cascade"
        rej_after = validate_success(api.get_coi_plan(plan_rej["id"], ADMIN))
        assert rej_after["status"] == "REJECTED", \
            "the REJECTED plan is untouched by the conditional cascade"
        resp = api.issue_equity(su["id"], {}, TTO)
        validate_error(resp, ApiErrorId.ERR_STARTUP_INVALID_STATE, 409)

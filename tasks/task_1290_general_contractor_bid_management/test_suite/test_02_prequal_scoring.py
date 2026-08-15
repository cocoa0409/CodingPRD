"""Prequalification scoring (dual variant, weighted formula, thresholds,
hard fail) and the application lifecycle (decide, reject, resubmit, expiry)."""
import pytest

from test_helpers import (
    LEAD,
    REVIEWER,
    ApiErrorId,
    advance_clock,
    approve_application,
    assert_prequal_application,
    assert_subcontractor,
    assert_timestamp_equals,
    decide_application,
    make_subcontractor_headers,
    register_subcontractor,
    resubmit_application,
    submit_prequal_application,
    api_client,
    validate_error,
    validate_success,
)

# Score provenance (PRD §3.4): components rounded half-up to 2dp before
# weighting; total = 0.40*financial + 0.35*safety + 0.25*bonding, 2dp half-up.
#   declared 2.5e9 / 0.90 / 1.0e9   -> 50.00 / 60.00 / 50.00  -> 53.50
#   verified 4.0e9 / 0.80 / 2.0e9   -> 80.00 / 80.00 / 100.00 -> 85.00
#   declared 3.0e9 / 0.80 / 1.5e9   -> 60.00 / 80.00 / 75.00  -> 70.75
#   declared 6.0e9 / 0.65 / 3.0e9   -> 100.00(capped) / 100.00(floor) / 100.00(capped) -> 100.00
#   declared 2.5e9 / 0.95 / 1.0e9   -> 50.00 / 50.00 / 50.00  -> 50.00


class TestDualVariantScoring:

    def test_self_reported_variant_computed_at_submission(self):
        """PRD §3.2: "The application is born in `SUBMITTED` status, and the
        system immediately computes its `self_reported_score` using the
        self-reported variant of the scoring rule in §3.4."
        PRD §3.4: "The total score weights the three individually rounded
        components — 0.40 for financial, 0.35 for safety, 0.25 for bonding —
        sums the weighted components, and rounds the sum half-up to 2 decimal
        places."

        Design: Difficulty/dual_variant_calc/prequal_self_reported_vs_verified_score
        """
        sub = register_subcontractor(legal_name="Alpha Steel LLC",
                                     license_number="LIC-X-001")
        app = submit_prequal_application(
            sub["id"], declared_annual_revenue_cents=2_500_000_000,
            declared_emr=0.90, declared_bonding_capacity_cents=1_000_000_000)
        assert_prequal_application(app)
        assert app["status"] == "SUBMITTED"
        # financial 50.00, safety 100-(0.90-0.70)*200 = 60.00, bonding 50.00
        assert app["self_reported_score"] == pytest.approx(53.50, abs=0.001)
        assert app.get("verified_score") is None, \
            "no verified score exists before a decision"

    def test_verified_variant_computed_at_decision_and_diverges(self):
        """PRD §3.4: "The **verified variant** runs at reviewer decision over
        the `verified_*` inputs and lands in `verified_score`; it carries the
        EMR hard fail: if the verified EMR is at or above 1.25, the
        `verified_score` is forced to exactly 0.00 regardless of the other
        components."
        PRD §3.2: "On approval the system stamps `approved_at` with the logical
        now, sets `expires_at` to exactly 365 days after `approved_at`, and
        records the decision in `review_notes` if supplied."

        Design: Difficulty/dual_variant_calc/prequal_self_reported_vs_verified_score
        """
        sub = register_subcontractor(legal_name="Alpha Steel LLC",
                                     license_number="LIC-X-001")
        app = submit_prequal_application(
            sub["id"], declared_annual_revenue_cents=2_500_000_000,
            declared_emr=0.90, declared_bonding_capacity_cents=1_000_000_000)
        decided = approve_application(
            app["id"], verified_annual_revenue_cents=4_000_000_000,
            verified_emr=0.80, verified_bonding_capacity_cents=2_000_000_000,
            review_notes="audited financials received")
        assert decided["status"] == "APPROVED"
        # verified: financial 80.00, safety 80.00, bonding 100.00 (capped)
        assert decided["verified_score"] == pytest.approx(85.00, abs=0.001)
        # The same row keeps both variant results side by side.
        reread = validate_success(
            api_client.get_prequal_application(app["id"], REVIEWER))
        assert reread["self_reported_score"] == pytest.approx(53.50, abs=0.001)
        assert reread["verified_score"] == pytest.approx(85.00, abs=0.001)
        assert reread["self_reported_score"] != pytest.approx(
            reread["verified_score"]), \
            "two variants, two different persisted results on one row"


class TestWeightedThreeInputNonlinearity:

    def test_capped_components_score_100(self):
        """PRD §3.4: "The **financial component** takes the revenue figure
        (declared or verified, per variant), divides it by a reference of
        5,000,000,000 cents, multiplies by 100, caps the result at 100, and
        rounds half-up to 2 decimal places."
        PRD §3.4: "The **safety component** is a piecewise function of the EMR:
        an EMR at or below 0.70 scores a full 100.00; an EMR at or above 1.20
        scores 0.00; between those bounds the score is 100 minus twice the
        excess of the EMR over 0.70, expressed as 100 minus the product of 200
        and the difference between the EMR and 0.70, rounded half-up to 2
        decimal places."
        PRD §3.4: "The **bonding component** divides the bonding-capacity
        figure by a reference of 2,000,000,000 cents, multiplies by 100, caps
        at 100, and rounds half-up to 2 decimal places."

        Design: Difficulty/combinatorial_formula/prequal_score_weighted_three_input_nonlinearity
        """
        sub = register_subcontractor(legal_name="A Cap LLC",
                                     license_number="LIC-A-201")
        app = submit_prequal_application(
            sub["id"], declared_annual_revenue_cents=6_000_000_000,
            declared_emr=0.65, declared_bonding_capacity_cents=3_000_000_000)
        # Both caps hit (120 -> 100, 150 -> 100); EMR 0.65 <= 0.70 floor.
        assert app["self_reported_score"] == pytest.approx(100.00, abs=0.001)

    def test_mid_slope_emr_scores_50(self):
        """PRD §3.4: "The total score weights the three individually rounded
        components — 0.40 for financial, 0.35 for safety, 0.25 for bonding —
        sums the weighted components, and rounds the sum half-up to 2 decimal
        places. Components are always rounded before weighting; weighting
        unrounded components and rounding only the total is a different number
        and is rejected."

        Design: Difficulty/combinatorial_formula/prequal_score_weighted_three_input_nonlinearity
        """
        sub = register_subcontractor(legal_name="B Mid LLC",
                                     license_number="LIC-B-201")
        app = submit_prequal_application(
            sub["id"], declared_annual_revenue_cents=2_500_000_000,
            declared_emr=0.95, declared_bonding_capacity_cents=1_000_000_000)
        # financial 50.00; safety 100-(0.95-0.70)*200 = 50.00; bonding 50.00.
        assert app["self_reported_score"] == pytest.approx(50.00, abs=0.001)


class TestRejectResubmitCycle:

    def test_resubmit_recomputes_self_reported_and_clears_verified(self):
        """PRD §3.2: "A rejected application may be resubmitted by the firm
        with fresh declared figures; resubmission moves it `REJECTED →
        SUBMITTED` (subject to the window-overlap gate above), recomputes
        `self_reported_score` from the new inputs, and clears every
        `verified_*` field and the `verified_score` back to null."

        Design: Difficulty/non_linear_state_machine/prequal_reject_resubmit_cycle
        """
        sub = register_subcontractor(legal_name="R Resubmit LLC",
                                     license_number="LIC-R-402")
        app = submit_prequal_application(
            sub["id"], declared_annual_revenue_cents=2_500_000_000,
            declared_emr=0.90, declared_bonding_capacity_cents=1_000_000_000)
        assert app["self_reported_score"] == pytest.approx(53.50, abs=0.001)
        decide_application(app["id"], "REJECTED",
                           review_notes="financials too thin")

        resubmitted = resubmit_application(
            app["id"], sub["id"],
            declared_annual_revenue_cents=3_000_000_000, declared_emr=0.80,
            declared_bonding_capacity_cents=1_500_000_000)
        assert resubmitted["status"] == "SUBMITTED"
        # 0.40*60.00 + 0.35*80.00 + 0.25*75.00 = 70.75
        assert resubmitted["self_reported_score"] == pytest.approx(70.75,
                                                                   abs=0.001)
        assert resubmitted.get("verified_score") is None, \
            "resubmission clears verified_score back to null"

    def test_resubmitted_application_reaches_approved_with_fresh_scores(self):
        """PRD §3.2: "A rejected application may be resubmitted by the firm
        with fresh declared figures; resubmission moves it `REJECTED →
        SUBMITTED` (subject to the window-overlap gate above), recomputes
        `self_reported_score` from the new inputs, and clears every
        `verified_*` field and the `verified_score` back to null."
        PRD §3.2: "On approval the system stamps `approved_at` with the logical
        now, sets `expires_at` to exactly 365 days after `approved_at`, and
        records the decision in `review_notes` if supplied."
        PRD §2.5: "All temporal rules — the bid deadline, the 365-day
        prequalification validity window, the 60-minute last-minute revision
        window, the `responded_at`, `submitted_at`, `acknowledged_at`,
        `sent_at`, `decided_at`, `approved_at`, and `issued_at` stamps — read
        the logical clock, which starts at exactly `2026-08-01T00:00:00Z`
        before any test-driving call."

        Design: Difficulty/non_linear_state_machine/prequal_reject_resubmit_cycle
        """
        sub = register_subcontractor(legal_name="R Resubmit LLC",
                                     license_number="LIC-R-402")
        app = submit_prequal_application(
            sub["id"], declared_annual_revenue_cents=2_500_000_000,
            declared_emr=0.90, declared_bonding_capacity_cents=1_000_000_000)
        decide_application(app["id"], "REJECTED")
        resubmit_application(app["id"], sub["id"])

        decided = approve_application(
            app["id"], verified_annual_revenue_cents=3_000_000_000,
            verified_emr=0.80, verified_bonding_capacity_cents=1_500_000_000)
        assert decided["status"] == "APPROVED"
        assert decided["verified_score"] == pytest.approx(70.75, abs=0.001)
        # The clock was never advanced: the default instant stamps approval.
        assert_timestamp_equals(decided["approved_at"], "2026-08-01T00:00:00Z")
        assert_timestamp_equals(decided["expires_at"], "2027-08-01T00:00:00Z")


class TestPrequalValidityWindow:

    def test_create_inside_open_window_rejected(self):
        """PRD §3.2: "Only one live application may exist per subcontractor at
        a time: a create or resubmit is rejected with
        `ERR_PREQUAL_WINDOW_OVERLAP` (HTTP 409) while another application for
        the same firm is `SUBMITTED`, or `APPROVED` with an `expires_at` still
        in the future."

        Design: Difficulty/resource_temporal_overlap/prequal_validity_window_containment
        """
        sub = register_subcontractor(legal_name="Window LLC",
                                     license_number="LIC-W-1002")
        app = submit_prequal_application(sub["id"])
        advance_clock("2026-08-02T00:00:00Z")
        approve_application(app["id"])  # window [2026-08-02, 2027-08-02)
        advance_clock("2026-08-10T00:00:00Z")

        resp = api_client.create_prequal_application(
            {"subcontractor_id": sub["id"],
             "declared_annual_revenue_cents": 3_500_000_000,
             "declared_emr": 0.75,
             "declared_bonding_capacity_cents": 1_800_000_000},
            make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_PREQUAL_WINDOW_OVERLAP)

    def test_create_after_window_closes_accepted_and_old_row_expires(self):
        """PRD §3.2: "Only one live application may exist per subcontractor at
        a time: a create or resubmit is rejected with
        `ERR_PREQUAL_WINDOW_OVERLAP` (HTTP 409) while another application for
        the same firm is `SUBMITTED`, or `APPROVED` with an `expires_at` still
        in the future."
        PRD §3.2: "An application whose `expires_at` has been reached
        transitions `APPROVED → EXPIRED` lazily: the transition is applied
        whenever the application is read or consulted for a prequalification
        check and the logical now is at or past `expires_at`, and the firm's
        `current_prequal_status` is recomputed at that moment."
        PRD §3.2: "The derived status itself is defined by a precedence walk
        over the firm's applications, ignoring `EXPIRED` rows entirely:
        `APPROVED` if a non-expired approved application exists at the logical
        now; otherwise `SUBMITTED` if one is awaiting decision; otherwise
        `REJECTED` if a rejected one exists; otherwise `NONE`."

        Design: Difficulty/resource_temporal_overlap/prequal_validity_window_containment
        """
        sub = register_subcontractor(legal_name="Window LLC",
                                     license_number="LIC-W-1002")
        app = submit_prequal_application(sub["id"])
        advance_clock("2026-08-02T00:00:00Z")
        approve_application(app["id"])  # expires_at = 2027-08-02

        advance_clock("2027-08-03T00:00:00Z")  # past the window
        resp = api_client.create_prequal_application(
            {"subcontractor_id": sub["id"],
             "declared_annual_revenue_cents": 3_500_000_000,
             "declared_emr": 0.75,
             "declared_bonding_capacity_cents": 1_800_000_000},
            make_subcontractor_headers(sub["id"]))
        app2 = validate_success(resp, expected_status=201)
        assert app2["status"] == "SUBMITTED"

        old = validate_success(
            api_client.get_prequal_application(app["id"], REVIEWER))
        assert old["status"] == "EXPIRED", "lazy expiry applies on read"
        sub_now = validate_success(api_client.get_subcontractor(sub["id"], LEAD))
        assert_subcontractor(sub_now)
        assert sub_now["current_prequal_status"] == "SUBMITTED"


class TestApprovalThreshold:

    def test_exactly_70_approves_and_69_30_rejected(self):
        """PRD §3.2: "Approving requires all three verified inputs —
        `verified_annual_revenue_cents`, `verified_emr`, and
        `verified_bonding_capacity_cents` — present in the decision payload (a
        missing one is `ERR_INVALID_REQUEST`), plus a `verified_score` of at
        least 70 computed from those verified inputs (otherwise
        `ERR_PREQUAL_SCORE_BELOW_THRESHOLD`, HTTP 422)."

        Design: Corner/calculations/prequal_threshold_exactly_70_approvable
        """
        sub_a = register_subcontractor(legal_name="A70 LLC",
                                       license_number="LIC-A-3001")
        sub_b = register_subcontractor(legal_name="B69 LLC",
                                       license_number="LIC-B-3001")
        app_a = submit_prequal_application(sub_a["id"])
        app_b = submit_prequal_application(sub_b["id"])

        # 0.40*50.00 + 0.35*100.00 + 0.25*60.00 = 70.00 — exactly the pass mark.
        resp = api_client.decide_prequal_application(
            app_a["id"],
            {"decision": "APPROVED",
             "verified_annual_revenue_cents": 2_500_000_000,
             "verified_emr": 0.70,
             "verified_bonding_capacity_cents": 1_200_000_000},
            REVIEWER)
        decided_a = validate_success(resp, expected_status=200)
        assert decided_a["verified_score"] == pytest.approx(70.00, abs=0.001)
        assert decided_a["status"] == "APPROVED"

        # EMR 0.71 -> safety 98.00 -> total 69.30 < 70.
        resp = api_client.decide_prequal_application(
            app_b["id"],
            {"decision": "APPROVED",
             "verified_annual_revenue_cents": 2_500_000_000,
             "verified_emr": 0.71,
             "verified_bonding_capacity_cents": 1_200_000_000},
            REVIEWER)
        validate_error(resp, ApiErrorId.ERR_PREQUAL_SCORE_BELOW_THRESHOLD)
        app_b_now = validate_success(
            api_client.get_prequal_application(app_b["id"], REVIEWER))
        assert app_b_now["status"] == "SUBMITTED", \
            "a failed approval must leave the application SUBMITTED"


class TestEmrHardFail:

    def test_verified_emr_at_hard_fail_forces_zero_score(self):
        """PRD §3.4: "The **verified variant** runs at reviewer decision over
        the `verified_*` inputs and lands in `verified_score`; it carries the
        EMR hard fail: if the verified EMR is at or above 1.25, the
        `verified_score` is forced to exactly 0.00 regardless of the other
        components."
        PRD §3.2: "Rejection takes the same `decision` field with no
        verified-input requirement; when all verified inputs happen to be
        present on a rejection, the `verified_score` is still computed and
        stored, and it remains null otherwise."

        Design: Corner/calculations/emr_hard_fail_forces_verified_zero
        """
        sub = register_subcontractor(legal_name="HardFail LLC",
                                     license_number="LIC-H-3002")
        app = submit_prequal_application(sub["id"])
        resp = api_client.decide_prequal_application(
            app["id"],
            {"decision": "REJECTED",
             "verified_annual_revenue_cents": 5_000_000_000,
             "verified_emr": 1.30,
             "verified_bonding_capacity_cents": 2_000_000_000,
             "review_notes": "EMR hard fail"},
            REVIEWER)
        decided = validate_success(resp, expected_status=200)
        assert decided["status"] == "REJECTED"
        # Base formula would give 0.40*100 + 0.35*0 + 0.25*100 = 65.00; the
        # hard fail overrides it to exactly 0.00.
        assert decided["verified_score"] == pytest.approx(0.00, abs=0.001)


class TestApplicationStateGuards:

    def test_decide_twice_and_resubmit_non_rejected_rejected(self):
        """PRD §3.2: "Deciding an application that is not `SUBMITTED`, or
        resubmitting one that is not `REJECTED`, is rejected with
        `ERR_APPLICATION_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/application_decide_twice_and_resubmit_non_rejected_rejected
        """
        sub = register_subcontractor(legal_name="Guard LLC",
                                     license_number="LIC-G-2006")
        app = submit_prequal_application(sub["id"])
        approve_application(app["id"])

        resp = api_client.decide_prequal_application(
            app["id"], {"decision": "REJECTED"}, REVIEWER)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE)

        resp = api_client.resubmit_prequal_application(
            app["id"],
            {"declared_annual_revenue_cents": 3_000_000_000,
             "declared_emr": 0.80,
             "declared_bonding_capacity_cents": 1_500_000_000},
            make_subcontractor_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE)

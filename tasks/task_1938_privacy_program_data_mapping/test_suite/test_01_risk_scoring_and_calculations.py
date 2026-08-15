"""Risk-score variants, PIA gating, request deadlines, applicability math,
vendor tiering, clause-gap, and retention expiry (PRD §2.6, §2.10, §3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    BO1,
    DS,
    LC1,
    PA,
    VM,
    assert_activity,
    assert_assessment,
    assert_iso_equal,
    assert_vendor_contract,
    create_activity_payload,
    create_contract_payload,
    create_consumer_and_request,
    create_data_element_payload,
    create_purpose_payload,
    create_retention_policy,
    create_state_law_rule,
    create_vendor_payload,
    get_success_data,
    list_evaluations_for_rule,
    make_consumer_headers,
    run_applicability,
    validate_paginated,
    validate_success,
)


class TestScreeningVsComprehensiveRisk:
    def test_risk_score_screening_vs_comprehensive_diverge(self, api):
        """PRD §3.4: "The screening score takes the maximum element value across
        the linked set — the maximum over an empty set is 0 — adds 25 for each
        element beyond the first, adds the vendor exposure (0 for LOW, 75 for
        STANDARD, 150 for HIGH, and 0 when no vendor is linked), applies
        round-half-up to the max term before the surcharges, and caps the result
        at 1000."
        PRD §3.5: "the element values are summed rather than maxed, round-half-up
        is applied to the sum term, the vendor exposure is added as in the
        screening variant, a consent adjustment of 50 is added when any purpose
        of the activity has status DOCUMENTED and legal_basis CONSENT, and the
        result is capped at 1000."

        Design: Difficulty/dual_variant_calc/activity_risk_screening_vs_comprehensive
        """
        e_bank = get_success_data(api.create_data_element(
            create_data_element_payload(element_key="bank_acct", category="FINANCIAL",
                                        classification="CONFIDENTIAL"), DS))
        e_health = get_success_data(api.create_data_element(
            create_data_element_payload(element_key="health_rec", category="HEALTH",
                                        classification="INTERNAL"), DS))
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="Medidata", home_region="EU",
                                  processes_categories=["HEALTH"]), VM))
        assert vendor["risk_tier"] == "HIGH"

        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Claims analytics", business_unit="Analytics",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[e_bank["id"], e_health["id"]],
                                    vendor_id=vendor["id"]), DS))
        assert_activity(activity)
        # screening: max(300, 300) + 25*1 + 150 = 475 (< 500, so no auto-PIA)
        assert activity["risk_score"] == 475, (
            f"screening risk_score must be max(300,300)+25+150 = 475, got {activity['risk_score']}"
        )
        assert activity["pia_required"] is False

        pia = get_success_data(api.create_assessment(activity["id"], DS))
        assert pia["trigger_reason"] == "MANUAL"
        assert pia["screening_score"] == 475
        get_success_data(api.submit_assessment(pia["id"], BO1))

        approved = get_success_data(api.approve_assessment(pia["id"], LC1))
        assert_assessment(approved)
        # comprehensive: 300 + 300 + 150 + 0 (no CONSENT purpose) = 750
        assert approved["status"] == "APPROVED"
        assert approved["final_score"] == 750, (
            f"comprehensive final_score must be 300+300+150 = 750, got {approved['final_score']}"
        )

        after = get_success_data(api.get_activity(activity["id"], DS))
        assert after["risk_score"] == 475, "activity keeps the screening score"
        assert approved["final_score"] != after["risk_score"], (
            "the two variants must diverge on identical inputs"
        )

    def test_reclassification_recomputes_screening_variant_only(self, api):
        """PRD §3.4: "In hop 1, every ProcessingActivity whose data_element_ids
        contains this element and whose status is DRAFT, ACTIVE, or
        COMPLIANCE_HOLD has its risk_score and pia_required recomputed using the
        screening variant, processed in created_at ascending order."
        PRD §3.4: "In hop 2, any such activity whose pia_required flips from
        false to true gets a PrivacyImpactAssessment auto-created in TRIGGERED
        status with trigger_reason set to RECLASSIFICATION, but only when no open
        assessment — one in TRIGGERED, IN_REVIEW, or CHANGES_REQUESTED — already
        exists for that activity."

        Design: Difficulty/dual_variant_calc/activity_risk_screening_vs_comprehensive
        """
        e_bank = get_success_data(api.create_data_element(
            create_data_element_payload(element_key="bank_acct", category="FINANCIAL",
                                        classification="CONFIDENTIAL"), DS))
        e_health = get_success_data(api.create_data_element(
            create_data_element_payload(element_key="health_rec", category="HEALTH",
                                        classification="INTERNAL"), DS))
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="Medidata", home_region="EU",
                                  processes_categories=["HEALTH"]), VM))
        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Claims analytics", business_unit="Analytics",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[e_bank["id"], e_health["id"]],
                                    vendor_id=vendor["id"]), DS))
        assert activity["risk_score"] == 475
        assert activity["pia_required"] is False

        # Reclassify bank_acct to HEALTH/RESTRICTED: value 300*2.0 = 600.
        reclassified = get_success_data(api.reclassify_data_element(
            e_bank["id"],
            {"category": "HEALTH", "classification": "RESTRICTED",
             "expected_element_version": e_bank["version"]},
            DS,
        ))
        assert reclassified["category"] == "HEALTH"

        after = get_success_data(api.get_activity(activity["id"], DS))
        # screening recompute: max(600, 300) + 25*1 + 150 = 775
        assert after["risk_score"] == 775, (
            f"recomputed screening score must be max(600,300)+25+150 = 775, got {after['risk_score']}"
        )
        assert after["pia_required"] is True, "775 >= 500 must flip pia_required to true"

        assessments, _meta = validate_paginated(
            api.list_activity_assessments(activity["id"], DS))
        assert len(assessments) == 1, "exactly one auto-created assessment expected"
        assert assessments[0]["trigger_reason"] == "RECLASSIFICATION"
        assert assessments[0]["status"] == "TRIGGERED"
        assert assessments[0]["screening_score"] == 775


class TestRequestDeadlineVariants:
    def _setup_ca_rule_and_consumer(self, api):
        from test_helpers import create_consumer
        get_success_data(api.create_state_law_rule(
            {"state_code": "CA", "law_name": "CCPA", "resident_records_threshold": 1,
             "revenue_share_threshold_pct": 100.0, "request_deadline_days": 45,
             "extension_days": 45}, PA))
        consumer = create_consumer(email="ca@x.com", full_name="CA One", state_code="CA")
        # 1 resident >= threshold 1 -> applies true, so the CA rule governs.
        run_applicability({"CA": 0}, total_revenue_cents=1000)
        return consumer

    def test_request_deadline_provisional_vs_final(self, api):
        """PRD §3.6: "The provisional deadline, provisional_due_at, is the
        request's created_at plus the governing rule's request_deadline_days, or
        plus the 45-day default when no rule governs; the provisional variant
        never includes an extension."
        PRD §3.6: "The final variant anchors to the request's created_at — never
        to the verification time — and adds the governing rule's
        request_deadline_days (or the 45-day default) plus the rule's
        extension_days (or the 30-day default) when the request_type is DELETION
        or PORTABILITY; for ACCESS, CORRECTION, and OPT_OUT the final deadline
        equals the provisional deadline."
        PRD §2.5: "Before any test-driving call, the clock reads exactly
        2026-08-01T00:00:00Z; the clock never falls back to wall time at any
        point."

        Design: Difficulty/dual_variant_calc/request_deadline_provisional_vs_final
        """
        consumer = self._setup_ca_rule_and_consumer(api)

        req_del = get_success_data(api.create_rights_request(
            consumer["id"],
            {"request_type": "DELETION", "requested_categories": ["BASIC_CONTACT"]},
            make_consumer_headers(consumer["id"])))
        req_acc = get_success_data(api.create_rights_request(
            consumer["id"],
            {"request_type": "ACCESS", "requested_categories": ["BASIC_CONTACT"]},
            make_consumer_headers(consumer["id"])))

        assert req_del["applicable_state_code"] == "CA"
        # provisional: created_at 2026-08-01 + 45d = 2026-09-15, no extension
        assert_iso_equal(req_del["provisional_due_at"], "2026-09-15T00:00:00Z",
                         "DELETION provisional_due_at")
        assert_iso_equal(req_acc["provisional_due_at"], "2026-09-15T00:00:00Z",
                         "ACCESS provisional_due_at")

        verified_del = get_success_data(api.verify_rights_request(req_del["id"], DS))
        verified_acc = get_success_data(api.verify_rights_request(req_acc["id"], DS))
        # final: 2026-08-01 + 45d + 45d = 2026-10-30 for DELETION
        assert_iso_equal(verified_del["final_due_at"], "2026-10-30T00:00:00Z",
                         "DELETION final_due_at")
        # ACCESS gets no extension: final == provisional
        assert_iso_equal(verified_acc["final_due_at"], "2026-09-15T00:00:00Z",
                         "ACCESS final_due_at")
        assert verified_del["final_due_at"] != verified_del["provisional_due_at"]
        assert_iso_equal(verified_acc["final_due_at"], verified_acc["provisional_due_at"],
                         "ACCESS final equals provisional")

    def test_opt_out_final_deadline_equals_provisional(self, api):
        """PRD §3.6: "The final variant anchors to the request's created_at —
        never to the verification time — and adds the governing rule's
        request_deadline_days (or the 45-day default) plus the rule's
        extension_days (or the 30-day default) when the request_type is DELETION
        or PORTABILITY; for ACCESS, CORRECTION, and OPT_OUT the final deadline
        equals the provisional deadline."

        Design: Difficulty/dual_variant_calc/request_deadline_provisional_vs_final
        """
        consumer = self._setup_ca_rule_and_consumer(api)
        request = get_success_data(api.create_rights_request(
            consumer["id"],
            {"request_type": "OPT_OUT", "requested_categories": ["BASIC_CONTACT"]},
            make_consumer_headers(consumer["id"])))
        assert request["applicable_state_code"] == "CA"
        assert_iso_equal(request["provisional_due_at"], "2026-09-15T00:00:00Z",
                         "OPT_OUT provisional_due_at")

        verified = get_success_data(api.verify_rights_request(request["id"], DS))
        assert_iso_equal(verified["final_due_at"], "2026-09-15T00:00:00Z",
                         "OPT_OUT final_due_at (no extension)")
        assert_iso_equal(verified["final_due_at"], verified["provisional_due_at"],
                         "OPT_OUT final equals provisional")


class TestRiskFormulaAndThresholds:
    def test_risk_formula_cap_and_conditionals(self, api):
        """PRD §3.4: "The screening score takes the maximum element value across
        the linked set — the maximum over an empty set is 0 — adds 25 for each
        element beyond the first, adds the vendor exposure (0 for LOW, 75 for
        STANDARD, 150 for HIGH, and 0 when no vendor is linked), applies
        round-half-up to the max term before the surcharges, and caps the result
        at 1000."
        PRD §3.4: "the activity's pia_required is set to true exactly when the
        screening score reaches at least 500. If pia_required is true, the server
        auto-creates a PrivacyImpactAssessment in TRIGGERED status with
        trigger_reason set to RISK_THRESHOLD."

        Design: Difficulty/combinatorial_formula/risk_formula_mode_a_cap_and_conditionals
        """
        e_bio = get_success_data(api.create_data_element(
            create_data_element_payload(element_key="bio_fp", category="BIOMETRIC",
                                        classification="RESTRICTED"), DS))          # 800
        e_gen = get_success_data(api.create_data_element(
            create_data_element_payload(element_key="genome", category="HEALTH",
                                        classification="RESTRICTED"), DS))          # 600
        e_min = get_success_data(api.create_data_element(
            create_data_element_payload(element_key="minor_profile", category="MINOR_DATA",
                                        classification="RESTRICTED"), DS))          # 700
        e_gps = get_success_data(api.create_data_element(
            create_data_element_payload(element_key="gps", category="PRECISE_LOCATION",
                                        classification="CONFIDENTIAL"), DS))        # 375
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="HealthCorp", home_region="US",
                                  processes_categories=["HEALTH"]), VM))
        assert vendor["risk_tier"] == "HIGH"

        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Genomics research", business_unit="R&D",
                                    notice_scope="EMPLOYEE",
                                    data_element_ids=[e_bio["id"], e_gen["id"],
                                                      e_min["id"], e_gps["id"]],
                                    vendor_id=vendor["id"]), DS))
        assert_activity(activity)
        # uncapped: max(800,600,700,375) + 25*3 + 150 = 1025 -> capped at 1000
        assert activity["risk_score"] == 1000, (
            f"min-cap must clamp uncapped 1025 to 1000, got {activity['risk_score']}"
        )
        assert activity["pia_required"] is True

        assessments, _meta = validate_paginated(
            api.list_activity_assessments(activity["id"], DS))
        assert len(assessments) == 1
        assert assessments[0]["trigger_reason"] == "RISK_THRESHOLD"
        assert assessments[0]["status"] == "TRIGGERED"
        assert assessments[0]["screening_score"] == 1000

    def test_screening_score_empty_element_set_and_low_vendor(self, api):
        """PRD §3.4: "The screening score takes the maximum element value across
        the linked set — the maximum over an empty set is 0 — adds 25 for each
        element beyond the first, adds the vendor exposure (0 for LOW, 75 for
        STANDARD, 150 for HIGH, and 0 when no vendor is linked), applies
        round-half-up to the max term before the surcharges, and caps the result
        at 1000."
        PRD §3.3: "Otherwise — the list is empty or contains only BASIC_CONTACT —
        the tier is LOW."

        Design: Difficulty/combinatorial_formula/risk_formula_mode_a_cap_and_conditionals
        """
        low_vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="PrintShop", home_region="US",
                                  processes_categories=[]), VM))
        assert low_vendor["risk_tier"] == "LOW"

        no_vendor = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Paper registry", business_unit="Admin",
                                    notice_scope="WEBSITE", data_element_ids=[]), DS))
        assert no_vendor["risk_score"] == 0, "max over an empty set is 0 with no surcharges"
        assert no_vendor["pia_required"] is False

        with_low = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Print queue", business_unit="Admin",
                                    notice_scope="WEBSITE", data_element_ids=[],
                                    vendor_id=low_vendor["id"]), DS))
        assert with_low["risk_score"] == 0, "LOW tier contributes vendor exposure 0"
        assert with_low["pia_required"] is False

    def test_pia_gating_no_feedback(self, api):
        """PRD §2.10: "The final score never feeds back into the activity's
        risk_score, never re-derives pia_required, and never gates activation."
        PRD §3.5: "the element values are summed rather than maxed, round-half-up
        is applied to the sum term, the vendor exposure is added as in the
        screening variant, a consent adjustment of 50 is added when any purpose
        of the activity has status DOCUMENTED and legal_basis CONSENT, and the
        result is capped at 1000."

        Design: Difficulty/combinatorial_formula/pia_gating_no_feedback_mode_c
        """
        from test_helpers import create_published_notice, create_retention_policy
        n1 = create_published_notice(scope="WEBSITE", title="Site v1")
        policy = create_retention_policy(policy_code="RP-1YR", duration_days=365)
        e_bank = get_success_data(api.create_data_element(
            create_data_element_payload(element_key="bank_acct", category="FINANCIAL",
                                        classification="CONFIDENTIAL"), DS))        # 300
        e_health = get_success_data(api.create_data_element(
            create_data_element_payload(element_key="health_rec", category="HEALTH",
                                        classification="INTERNAL"), DS))            # 300

        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Marketing analytics", business_unit="Growth",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[e_bank["id"], e_health["id"]]), DS))
        # screening: max(300,300) + 25 = 325 -> pia_required false, no auto-PIA
        assert activity["risk_score"] == 325
        assert activity["pia_required"] is False

        purpose = get_success_data(api.create_purpose(
            activity["id"],
            create_purpose_payload(purpose_type="MARKETING", legal_basis="CONSENT",
                                   retention_policy_id=policy["id"]), DS))
        assert purpose["pinned_notice_id"] == n1["id"]

        pia = get_success_data(api.create_assessment(activity["id"], DS))
        get_success_data(api.submit_assessment(pia["id"], BO1))
        approved = get_success_data(api.approve_assessment(pia["id"], LC1))
        # comprehensive: 300 + 300 + 0 + 50 (CONSENT adjustment) = 650
        assert approved["final_score"] == 650, (
            f"comprehensive final_score must be 300+300+0+50 = 650, got {approved['final_score']}"
        )

        after = get_success_data(api.get_activity(activity["id"], DS))
        assert after["pia_required"] is False, (
            "comprehensive 650 >= 500 must never feed back into pia_required"
        )
        assert after["risk_score"] == 325

        activated = get_success_data(api.activate_activity(activity["id"], DS))
        assert activated["status"] == "ACTIVE", (
            "approval does not re-gate activation; the DOCUMENTED purpose suffices"
        )

    def test_pia_approval_auto_resumes_hold_without_gating_feedback(self, api):
        """PRD §3.5: "Approval then cascades: if the owning activity is in
        COMPLIANCE_HOLD with zero CONSENT_STALE purposes and zero other
        assessments in TRIGGERED, IN_REVIEW, or CHANGES_REQUESTED, the activity
        auto-resumes to ACTIVE, reinstating its ACTIVITY_HOLD-suspended
        transfers."
        PRD §2.10: "The final score never feeds back into the activity's
        risk_score, never re-derives pia_required, and never gates activation."

        Design: Difficulty/combinatorial_formula/pia_gating_no_feedback_mode_c
        """
        from test_helpers import create_element, create_retention_policy
        policy = create_retention_policy()
        own_element = create_element(element_key="newsletter_email",
                                     category="BASIC_CONTACT", classification="INTERNAL")
        act = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Newsletter", business_unit="Marketing",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[own_element["id"]]), DS))
        get_success_data(api.create_purpose(
            act["id"],
            create_purpose_payload(purpose_type="MARKETING", legal_basis="LEGITIMATE_INTEREST",
                                   retention_policy_id=policy["id"]), DS))
        act = get_success_data(api.activate_activity(act["id"], DS))
        assert act["status"] == "ACTIVE"

        # Reclassify 50 -> BIOMETRIC/CONFIDENTIAL 600: screening 600, auto-PIA, hold.
        get_success_data(api.reclassify_data_element(
            own_element["id"],
            {"category": "BIOMETRIC", "classification": "CONFIDENTIAL",
             "expected_element_version": own_element["version"]}, DS))
        held = get_success_data(api.get_activity(act["id"], DS))
        assert held["status"] == "COMPLIANCE_HOLD"
        assert held["risk_score"] == 600
        assert held["pia_required"] is True

        assessments, _meta = validate_paginated(
            api.list_activity_assessments(act["id"], DS))
        pia = assessments[0]
        assert pia["trigger_reason"] == "RECLASSIFICATION"
        get_success_data(api.submit_assessment(pia["id"], BO1))
        approved = get_success_data(api.approve_assessment(pia["id"], LC1))
        # comprehensive: single element 600, no vendor, no CONSENT purpose
        assert approved["final_score"] == 600

        resumed = get_success_data(api.get_activity(act["id"], DS))
        assert resumed["status"] == "ACTIVE", "approval auto-resumes the held activity"
        assert resumed["pia_required"] is True, (
            "approval's final_score never re-derives pia_required; the flag set at "
            "reclassification stays put"
        )
        assert resumed["risk_score"] == 600

    def test_risk_score_at_pia_threshold(self, api):
        """PRD §3.4: "the activity's pia_required is set to true exactly when the
        screening score reaches at least 500. If pia_required is true, the server
        auto-creates a PrivacyImpactAssessment in TRIGGERED status with
        trigger_reason set to RISK_THRESHOLD."
        PRD §3.4: "The screening score takes the maximum element value across the
        linked set — the maximum over an empty set is 0 — adds 25 for each
        element beyond the first, adds the vendor exposure (0 for LOW, 75 for
        STANDARD, 150 for HIGH, and 0 when no vendor is linked), applies
        round-half-up to the max term before the surcharges, and caps the result
        at 1000."

        Design: Difficulty/boundary_precision_check/risk_score_at_pia_threshold
        """
        e_ssn = get_success_data(api.create_data_element(
            create_data_element_payload(element_key="ssn", category="FINANCIAL",
                                        classification="RESTRICTED"), DS))          # 200 x 2.0 = 400
        e_nick = get_success_data(api.create_data_element(
            create_data_element_payload(element_key="nickname", category="BASIC_CONTACT",
                                        classification="PUBLIC"), DS))              # 25
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="FinServ", home_region="US",
                                  processes_categories=["FINANCIAL"]), VM))
        assert vendor["risk_tier"] == "STANDARD"

        a_x = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Credit check", business_unit="Risk",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[e_ssn["id"], e_nick["id"]],
                                    vendor_id=vendor["id"]), DS))
        # 400 + 25*1 + 75 = 500 exactly -> boundary inclusive
        assert a_x["risk_score"] == 500
        assert a_x["pia_required"] is True

        a_y = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Newsletter prefs", business_unit="Risk",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[e_ssn["id"], e_nick["id"]]), DS))
        # no vendor: 400 + 25 = 425
        assert a_y["risk_score"] == 425
        assert a_y["pia_required"] is False

        x_assessments, _mx = validate_paginated(
            api.list_activity_assessments(a_x["id"], DS))
        assert len(x_assessments) == 1
        assert x_assessments[0]["trigger_reason"] == "RISK_THRESHOLD"
        assert x_assessments[0]["status"] == "TRIGGERED"

        y_assessments, _my = validate_paginated(
            api.list_activity_assessments(a_y["id"], DS))
        assert y_assessments == [], "425 < 500: no auto-PIA may be created"

    def test_pia_threshold_with_standard_vendor_boundary(self, api):
        """PRD §3.4: "the activity's pia_required is set to true exactly when the
        screening score reaches at least 500."
        PRD §3.4: "The screening score takes the maximum element value across the
        linked set — the maximum over an empty set is 0 — adds 25 for each
        element beyond the first, adds the vendor exposure (0 for LOW, 75 for
        STANDARD, 150 for HIGH, and 0 when no vendor is linked), applies
        round-half-up to the max term before the surcharges, and caps the result
        at 1000."

        Design: Difficulty/boundary_precision_check/risk_score_at_pia_threshold
        """
        e_ssn = get_success_data(api.create_data_element(
            create_data_element_payload(element_key="ssn", category="FINANCIAL",
                                        classification="RESTRICTED"), DS))          # 200 x 2.0 = 400
        e_dob = get_success_data(api.create_data_element(
            create_data_element_payload(element_key="dob", category="BASIC_CONTACT",
                                        classification="PUBLIC"), DS))              # 25
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="FinServ", home_region="US",
                                  processes_categories=["FINANCIAL"]), VM))
        assert vendor["risk_tier"] == "STANDARD"                                     # exposure 75

        a_hit = get_success_data(api.create_activity(
            create_activity_payload(activity_name="KYC screening", business_unit="Risk",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[e_ssn["id"], e_dob["id"]],
                                    vendor_id=vendor["id"]), DS))
        # 400 + 25 + 75 = 500 exactly
        assert a_hit["risk_score"] == 500
        assert a_hit["pia_required"] is True

        a_low = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Marketing list", business_unit="Growth",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[e_ssn["id"]],
                                    vendor_id=vendor["id"]), DS))
        # 400 + 0 + 75 = 475 (< 500)
        assert a_low["risk_score"] == 475
        assert a_low["pia_required"] is False


class TestVendorTierAndClauseGap:
    @pytest.mark.parametrize("categories,expected_tier", [
        (["MINOR_DATA"], "HIGH"),
        (["FINANCIAL"], "STANDARD"),
        (["PRECISE_LOCATION"], "STANDARD"),
        (["BASIC_CONTACT"], "LOW"),
    ])
    def test_vendor_tier_table_boundaries(self, api, categories, expected_tier):
        """PRD §3.3: "If processes_categories intersects the high-sensitivity set
        — HEALTH, BIOMETRIC, or MINOR_DATA — the tier is HIGH. Otherwise, if it
        intersects the moderate-sensitivity set — FINANCIAL, PRECISE_LOCATION, or
        IDENTIFIER — the tier is STANDARD. Otherwise — the list is empty or
        contains only BASIC_CONTACT — the tier is LOW."

        Design: Corner/calculations/vendor_tier_table_boundaries
        """
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name=f"V-{categories[0]}", home_region="US",
                                  processes_categories=categories), VM))
        assert vendor["risk_tier"] == expected_tier, (
            f"processes_categories {categories} must map to tier {expected_tier}, "
            f"got {vendor['risk_tier']}"
        )

    def test_vendor_empty_categories_low_tier(self, api):
        """PRD §3.3: "Otherwise — the list is empty or contains only
        BASIC_CONTACT — the tier is LOW."
        PRD §3.3: "At creation the server computes required_clauses from the
        vendor's risk_tier: a LOW tier requires only DPA"
        PRD §3.3: "If missing_clauses is empty, verification passes:
        verification_status becomes PASSED and status advances from DRAFT to
        VERIFIED."

        Design: Difficulty/boundary_precision_check/vendor_empty_categories_low_tier
        """
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="PrintShop", home_region="US",
                                  processes_categories=[]), VM))
        assert vendor["risk_tier"] == "LOW"

        contract = get_success_data(api.create_contract(
            vendor["id"],
            create_contract_payload(provided_clauses=["DPA"],
                                    expected_vendor_version=vendor["version"]), VM))
        assert_vendor_contract(contract)
        assert contract["required_clauses"] == ["DPA"]
        assert contract["missing_clauses"] == []
        assert contract["status"] == "DRAFT"
        assert contract["verification_status"] == "UNVERIFIED"

        verified = get_success_data(api.verify_contract(contract["id"], LC1))
        assert verified["verification_status"] == "PASSED"
        assert verified["status"] == "VERIFIED"

    def test_low_tier_missing_clause_fails_verification(self, api):
        """PRD §3.3: "a LOW tier requires only DPA"
        PRD §3.3: "If missing_clauses is non-empty, verification fails:
        verification_status becomes FAILED and status stays DRAFT."

        Design: Difficulty/boundary_precision_check/vendor_empty_categories_low_tier
        """
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="PrintShop", home_region="US",
                                  processes_categories=[]), VM))
        assert vendor["risk_tier"] == "LOW"

        contract = get_success_data(api.create_contract(
            vendor["id"],
            create_contract_payload(provided_clauses=["BREACH_NOTICE_72H"],
                                    expected_vendor_version=vendor["version"]), VM))
        assert contract["required_clauses"] == ["DPA"]
        assert contract["missing_clauses"] == ["DPA"], (
            "providing a clause that is not required leaves DPA missing"
        )

        verified = get_success_data(api.verify_contract(contract["id"], LC1))
        assert verified["verification_status"] == "FAILED"
        assert verified["status"] == "DRAFT", "a failed verification leaves status DRAFT"

    def test_contract_clause_gap_set_difference(self, api):
        """PRD §3.3: "a HIGH tier requires all five — DPA, BREACH_NOTICE_72H,
        DELETION_ON_EXIT, SUBPROCESSOR_CONSENT, and AUDIT_RIGHTS."
        PRD §3.3: "The server also computes missing_clauses as the required set
        minus the provided set, sorted by clause code ascending."
        PRD §3.3: "If missing_clauses is non-empty, verification fails:
        verification_status becomes FAILED and status stays DRAFT."

        Design: Corner/calculations/contract_clause_gap_set_difference
        """
        vendor = get_success_data(api.create_vendor(
            create_vendor_payload(vendor_name="Medidata", home_region="EU",
                                  processes_categories=["HEALTH"]), VM))
        assert vendor["risk_tier"] == "HIGH"

        contract = get_success_data(api.create_contract(
            vendor["id"],
            create_contract_payload(provided_clauses=["DPA", "BREACH_NOTICE_72H"],
                                    expected_vendor_version=vendor["version"]), VM))
        assert_vendor_contract(contract)
        assert sorted(contract["required_clauses"]) == sorted(
            ["DPA", "BREACH_NOTICE_72H", "DELETION_ON_EXIT",
             "SUBPROCESSOR_CONSENT", "AUDIT_RIGHTS"])
        assert len(contract["required_clauses"]) == 5
        # sorted by clause code ascending
        assert contract["missing_clauses"] == [
            "AUDIT_RIGHTS", "DELETION_ON_EXIT", "SUBPROCESSOR_CONSENT"]

        verified = get_success_data(api.verify_contract(contract["id"], LC1))
        assert verified["verification_status"] == "FAILED"
        assert verified["status"] == "DRAFT"


class TestApplicabilityRounding:
    def test_applicability_revenue_share_rounding(self, api):
        """PRD §3.8: "revenue_share_pct takes the state's revenue from
        state_revenues — 0 when the state is absent from the map — divides by
        total_revenue_cents, multiplies by 100, and applies round-half-up once to
        two decimal places, in the pinned order described in §2.6."
        PRD §2.6: "The applicability revenue share percentage is computed by
        dividing the raw annual cent totals first, multiplying by 100, then
        rounding half-up once to two decimal places; per-quarter or per-line
        values are never rounded first, and no truncation occurs at any step."
        PRD §3.8: "applies is true when the resident consumer count reaches at
        least the rule's resident_records_threshold or the revenue share
        percentage reaches at least the rule's revenue_share_threshold_pct."

        Design: Difficulty/combinatorial_formula/applicability_revenue_share_rounding_mode_b
        """
        rule = create_state_law_rule(
            state_code="NV", law_name="SB 370", resident_records_threshold=100000,
            revenue_share_threshold_pct=33.34, request_deadline_days=45,
            extension_days=30)
        from test_helpers import create_consumer
        create_consumer(email="nv@x.com", full_name="NV One", state_code="NV")

        run = run_applicability({"NV": 6667}, total_revenue_cents=20000)
        assert run["evaluation_count"] == 1

        evaluations, _meta = list_evaluations_for_rule(rule["id"])
        assert len(evaluations) == 1
        ev = evaluations[0]
        # 100 * 6667 / 20000 = 33.335 -> round_half_up once -> 33.34
        assert ev["revenue_share_pct"] == pytest.approx(33.34, abs=0.0001), (
            f"divide-then-round-half-up must yield 33.34, got {ev['revenue_share_pct']}"
        )
        assert ev["resident_consumer_count"] == 1, "the count path alone would fail (1 < 100000)"
        assert ev["applies"] is True, "33.34 >= 33.34 must apply"
        assert ev["margin_to_threshold"] == 1 - 100000

    def test_applicability_revenue_share_rounding_at_100(self, api):
        """PRD §2.6: "The applicability revenue share percentage is computed by
        dividing the raw annual cent totals first, multiplying by 100, then
        rounding half-up once to two decimal places; per-quarter or per-line
        values are never rounded first, and no truncation occurs at any step."
        PRD §3.8: "applies is true when the resident consumer count reaches at
        least the rule's resident_records_threshold or the revenue share
        percentage reaches at least the rule's revenue_share_threshold_pct."
        PRD §3.8: "revenue_share_pct takes the state's revenue from
        state_revenues — 0 when the state is absent from the map"

        Design: Difficulty/combinatorial_formula/applicability_revenue_share_rounding_mode_b
        """
        rule = create_state_law_rule(
            state_code="DE", law_name="DPDPA", resident_records_threshold=50000,
            revenue_share_threshold_pct=100.0, request_deadline_days=45,
            extension_days=30)

        run = run_applicability({"DE": 19999}, total_revenue_cents=20000)
        assert run["evaluation_count"] == 1

        evaluations, _meta = list_evaluations_for_rule(rule["id"])
        assert len(evaluations) == 1
        ev = evaluations[0]
        # 100 * 19999 / 20000 = 99.995 -> round_half_up once -> 100.00
        assert ev["revenue_share_pct"] == pytest.approx(100.0, abs=0.0001), (
            f"pinned rounding must yield 100.00, got {ev['revenue_share_pct']}"
        )
        assert ev["resident_consumer_count"] == 0, "no consumers registered for DE"
        assert ev["applies"] is True, "100.00 >= 100 must apply"


class TestRetentionExpiry:
    def test_retention_expiry_literals(self, api):
        """PRD §3.4: "The server computes retention_expires_at as the purpose's
        created_at plus the policy's duration_days days."
        PRD §2.5: "Before any test-driving call, the clock reads exactly
        2026-08-01T00:00:00Z; the clock never falls back to wall time at any
        point."

        Design: Corner/calculations/retention_expiry_literals
        """
        rp365 = create_retention_policy(policy_code="RP-1YR", duration_days=365)
        rp30 = create_retention_policy(policy_code="RP-30D", duration_days=30)
        e1 = get_success_data(api.create_data_element(
            create_data_element_payload(element_key="email", category="BASIC_CONTACT",
                                        classification="INTERNAL"), DS))
        activity = get_success_data(api.create_activity(
            create_activity_payload(activity_name="Newsletter", business_unit="Marketing",
                                    notice_scope="WEBSITE",
                                    data_element_ids=[e1["id"]]), DS))

        p365 = get_success_data(api.create_purpose(
            activity["id"],
            create_purpose_payload(purpose_type="MARKETING", legal_basis="CONTRACT",
                                   retention_policy_id=rp365["id"]), DS))
        p30 = get_success_data(api.create_purpose(
            activity["id"],
            create_purpose_payload(purpose_type="ANALYTICS", legal_basis="LEGITIMATE_INTEREST",
                                   retention_policy_id=rp30["id"]), DS))

        # created_at == 2026-08-01T00:00:00Z on the default logical clock
        assert_iso_equal(p365["retention_expires_at"], "2027-08-01T00:00:00Z",
                         "365-day retention_expires_at")
        assert_iso_equal(p30["retention_expires_at"], "2026-08-31T00:00:00Z",
                         "30-day retention_expires_at")


class TestRequestDeadlineDefaults:
    def test_request_deadline_default_constants(self, api):
        """PRD §3.6: "The provisional deadline, provisional_due_at, is the
        request's created_at plus the governing rule's request_deadline_days, or
        plus the 45-day default when no rule governs; the provisional variant
        never includes an extension."
        PRD §3.6: "The final variant anchors to the request's created_at — never
        to the verification time — and adds the governing rule's
        request_deadline_days (or the 45-day default) plus the rule's
        extension_days (or the 30-day default) when the request_type is DELETION
        or PORTABILITY"
        PRD §3.6: "The applicable_state_code is set to the governing rule's
        state_code when one governs and null otherwise."

        Design: Corner/calculations/request_deadline_default_constants
        """
        consumer, request = create_consumer_and_request(
            email="tx@x.com", state_code="TX", request_type="DELETION",
            requested_categories=["BASIC_CONTACT"])
        # TX has no StateLawRule, so the defaults apply and no rule governs
        assert request["applicable_state_code"] is None
        assert_iso_equal(request["provisional_due_at"], "2026-09-15T00:00:00Z",
                         "provisional_due_at = created_at + default 45d")
        assert request["final_due_at"] is None

        verified = get_success_data(api.verify_rights_request(request["id"], DS))
        assert_iso_equal(verified["final_due_at"], "2026-10-15T00:00:00Z",
                         "final_due_at = created_at + 45d + default 30d extension")


class TestComputedFieldsAreServerComputed:
    def test_computed_field_input_ignored(self, api):
        """PRD §3.4: "At creation the server computes the screening variant of
        the risk score."
        PRD §3.4: "the activity's pia_required is set to true exactly when the
        screening score reaches at least 500."
        PRD §3.1: "the element's value in any risk computation is the product of
        its weight and its multiplier."

        Design: Corner/entities/computed_field_input_ignored
        """
        e1 = get_success_data(api.create_data_element(
            create_data_element_payload(element_key="email", category="BASIC_CONTACT",
                                        classification="INTERNAL"), DS))
        payload = create_activity_payload(
            activity_name="Newsletter", business_unit="Marketing",
            notice_scope="WEBSITE", data_element_ids=[e1["id"]])
        payload["risk_score"] = 999
        payload["pia_required"] = True
        activity = get_success_data(api.create_activity(payload, DS))
        assert_activity(activity)
        # single BASIC_CONTACT/INTERNAL element: 50 * 1.0 = 50
        assert activity["risk_score"] == 50, (
            f"server-computed screening score must be 50, got {activity['risk_score']}"
        )
        assert activity["pia_required"] is False

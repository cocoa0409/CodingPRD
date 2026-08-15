"""Dual-variant calculations: provisional vs final charge on cases, and
realtime vs period risk score on audits (PRD §3.3, §3.7, §3.9)."""
from test_helpers import (
    ADMIN,
    AUDITOR,
    SCHED,
    create_case,
    create_crna,
    create_fee_schedule,
    create_physician,
    create_published_roster,
    create_site,
    get_success_data,
    list_audits,
    list_claims,
    make_physician_headers,
    propose_and_confirm,
    propose_assignment,
    run_case_clock,
    setup_case_with_confirmed_primary,
    api_client,
)


class TestProvisionalVsFinalCharge:
    def test_provisional_uses_scheduled_minutes_and_final_uses_actual(self, api):
        """PRD §3.7: "Final claims use actual minutes (`actual_end_minute` minus
        `actual_start_minute`); the provisional estimate of §3.3 uses scheduled
        minutes."
        PRD §3.3: "the case's `provisional_charge_cents` is computed as a
        forward-looking estimate: scheduled duration in minutes run through the
        unit math of §3.7, multiplied by the contextually optimistic conversion
        factor — 8,000 cents per unit when the primary is an
        `ANESTHESIOLOGIST` with no `CONFIRMED` directing assignment on the case".

        Design: Difficulty/dual_variant_calc/provisional_vs_final_charge_diverge_on_actual_minutes
        """
        ctx = setup_case_with_confirmed_primary(
            provider_type="ANESTHESIOLOGIST", base_units=5,
            scheduled_start_minute=540, scheduled_end_minute=660,
            scheduled_day_end_minute=1020)
        case_id = ctx["case"]["id"]
        # Provisional: scheduled 120 min -> 8.0 time units -> 13.0 units x 8000.
        after_accept = get_success_data(api.get_case(case_id, SCHED))
        assert after_accept["provisional_charge_cents"] == 104000, (
            f"provisional must be 13.0 units x 8000 = 104000, got "
            f"{after_accept['provisional_charge_cents']}")
        run_case_clock(case_id, "2026-08-10T09:00:00Z", "2026-08-10T11:30:00Z")
        completed = get_success_data(api.complete_case(case_id, SCHED))
        # Final: actual 150 min -> 10.0 time units -> 15.0 units x 8000.
        assert completed["final_charge_cents"] == 120000, (
            f"final must be 15.0 units x 8000 = 120000, got "
            f"{completed['final_charge_cents']}")
        claims = list_claims({"case_id": case_id})
        assert len(claims) == 1, f"exactly one claim expected, got {len(claims)}"
        claim = claims[0]
        assert claim["modifier_code"] == "PERSONAL"
        assert claim["units_total"] == 15.0
        assert claim["charge_cents"] == 120000
        assert after_accept["provisional_charge_cents"] != completed["final_charge_cents"], \
            "identical case data must yield different provisional vs final charge"

    def test_provisional_null_until_primary_confirms(self, api):
        """PRD §3.2: "New cases begin `SCHEDULED`, with `actual_start_minute`,
        `actual_end_minute`, `cancellation_reason`, `cancellation_notice_minutes`,
        `provisional_charge_cents`, and `final_charge_cents` all null."
        PRD §3.3: "When a `CASE_PRIMARY` assignment confirms, the case's
        `provisional_charge_cents` is computed as a forward-looking estimate".

        Design: Difficulty/dual_variant_calc/provisional_vs_final_charge_diverge_on_actual_minutes
        """
        ctx = setup_case_with_confirmed_primary(
            provider_type="ANESTHESIOLOGIST", base_units=5,
            scheduled_start_minute=540, scheduled_end_minute=660)
        # Fixture already confirmed the primary; re-verify with a fresh case
        # that the provisional stays null while the primary is only PROPOSED.
        case2 = create_case(ctx["roster"]["id"], scheduled_start_minute=700,
                            scheduled_end_minute=820)
        fresh = get_success_data(api.get_case(case2["id"], SCHED))
        assert fresh["provisional_charge_cents"] is None
        assert fresh["final_charge_cents"] is None
        proposed = propose_assignment(case2["id"], ctx["provider"]["id"],
                                      "CASE_PRIMARY")
        still_null = get_success_data(api.get_case(case2["id"], SCHED))
        assert still_null["provisional_charge_cents"] is None, \
            "PROPOSED primary must not trigger the provisional estimate"
        # After the primary accepts, the forward-looking estimate appears:
        # scheduled 120 min -> 13.0 units x 8000 = 104000.
        api.accept_assignment(proposed["id"],
                              make_physician_headers(ctx["provider"]["id"]))
        confirmed = get_success_data(api.get_case(case2["id"], SCHED))
        assert confirmed["provisional_charge_cents"] == 104000


class TestRealtimeVsPeriodRiskScore:
    def _setup_mixed_bucket_audit(self, api):
        """CREDENTIAL_LAPSE (MINOR) finding on a SCHEDULED case + a completed
        directed case without attestation -> TEFRA_GAP (MAJOR) on a terminal
        case; both on the same roster/audit."""
        site = create_site()
        create_fee_schedule("P100", 5)
        director = create_physician("Dr. Direct")
        crna_ok = create_crna("Crna One")
        crna_lapse = create_crna("Crna Two", expiry="2026-08-15")
        roster = create_published_roster(
            site["id"], required_primary_slots=1, scheduled_day_end_minute=1020)
        # Case B (stays SCHEDULED): PROPOSED primary whose credentials are then
        # shortened below the service date -> CREDENTIAL_LAPSE (MINOR).
        case_b = create_case(roster["id"], scheduled_start_minute=600,
                             scheduled_end_minute=660)
        propose_assignment(case_b["id"], crna_lapse["id"], "CASE_PRIMARY")
        get_success_data(api.update_provider_credentials(
            crna_lapse["id"],
            {"credential_expires_on": "2026-08-08", "dea_expires_on": "2026-08-08",
             "expected_provider_version": crna_lapse["version"]},
            ADMIN))
        # Case A: CONFIRMED primary + CONFIRMED directing, no attestation.
        case_a = create_case(roster["id"], scheduled_start_minute=540,
                             scheduled_end_minute=600)
        propose_and_confirm(case_a["id"], crna_ok["id"], "CRNA", "CASE_PRIMARY")
        propose_and_confirm(case_a["id"], director["id"], "ANESTHESIOLOGIST",
                            "CASE_DIRECTING")
        run_case_clock(case_a["id"], "2026-08-10T09:00:00Z",
                       "2026-08-10T10:00:00Z")
        get_success_data(api.complete_case(case_a["id"], SCHED))
        audits = list_audits({"roster_id": roster["id"]})
        assert len(audits) == 1
        return roster, case_a, case_b, audits[0]

    def test_same_open_finding_set_yields_different_scores_per_variant(self, api):
        """PRD §3.9: "The `realtime_score` sums the weights of open findings
        whose bucket case is still non-terminal (`SCHEDULED` or `IN_PROGRESS`)
        — exposure that can still be mitigated. The `period_score` sums the
        weights of open findings whose bucket case is terminal (`COMPLETED` or
        `CANCELLED`) — the chronological actuals."
        PRD §3.9: "`MINOR` findings weigh 10, `MAJOR` 30, `CRITICAL` 60."

        Design: Difficulty/dual_variant_calc/realtime_vs_period_risk_score_diverge_on_case_terminality
        """
        roster, case_a, case_b, audit = \
            self._setup_mixed_bucket_audit(api)
        assert audit["realtime_score"] == 10, (
            f"realtime must count only the MINOR finding on SCHEDULED case B, "
            f"got {audit['realtime_score']}")
        assert audit["period_score"] == 30, (
            f"period must count only the MAJOR finding on COMPLETED case A, "
            f"got {audit['period_score']}")
        assert audit["risk_band"] == "ELEVATED", (
            f"band derives from period_score; 20 <= 30 < 50 -> ELEVATED, got "
            f"{audit['risk_band']}")

    def test_risk_band_boundaries_and_bucket_split(self, api):
        """PRD §3.9: "The `risk_band` derives from `period_score`: below 20 is
        `LOW`; at least 20 but below 50 is `ELEVATED`; at least 50 but below
        100 is `HIGH`; 100 or more is `CRITICAL` — so a period score of exactly
        20 lands `ELEVATED` and exactly 100 lands `CRITICAL`."
        PRD §3.9: "Only `OPEN` findings count."

        Design: Difficulty/dual_variant_calc/realtime_vs_period_risk_score_diverge_on_case_terminality
        """
        roster, case_a, case_b, audit = \
            self._setup_mixed_bucket_audit(api)
        # Resolving the TEFRA_GAP finding removes it from the OPEN set: period
        # drops to 0, band returns to LOW, realtime still carries the MINOR.
        findings = get_success_data(
            api.list_findings(AUDITOR, params={"audit_id": audit["id"]}))
        findings = findings if isinstance(findings, list) else findings["data"]
        tefra = [f for f in findings if f["finding_type"] == "TEFRA_GAP"]
        assert len(tefra) == 1
        get_success_data(api.resolve_finding(
            tefra[0]["id"], {"resolution_note": "ATTESTATION_COMPLETED"}, AUDITOR))
        after = get_success_data(api.get_audit(audit["id"], AUDITOR))
        assert after["period_score"] == 0
        assert after["risk_band"] == "LOW"
        assert after["realtime_score"] == 10

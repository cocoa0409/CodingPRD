"""Pharmacy audit: windows, findings admissibility, dispute cycle, clawback variants,
clawback cascade into pharmacy suspension."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    make_pharmacy, make_audit, record_findings, get_audit, get_pharmacy, get_claim,
    make_adjudication_scenario, make_audit_universe_scenario,
    make_suspended_pharmacy_scenario,
    create_paid_claim, submit_claim,
    make_pharmacist_headers,
)


class TestAuditWindowOverlap:
    def test_touching_window_rejected(self, api, auditor_headers):
        """PRD §3.8: "a new audit is rejected with `ERR_AUDIT_WINDOW_OVERLAP` (HTTP 422)
        when the same pharmacy already has an audit in `OPEN`, `FINDINGS_RECORDED`, or
        `DISPUTED` status whose closed window intersects the new one — and because both
        window bounds are inclusive, windows that merely touch (the new start equal to
        an existing end) count as overlapping."

        Design: Difficulty/boundary_precision_check/audit_window_touching_boundary
        """
        pharmacy = make_pharmacy(ncpdp_id="NCPDP-W1", name="Rx Window")
        first = make_audit(pharmacy["id"], window_start_date="2026-01-01",
                           window_end_date="2026-03-31", extrapolation_method="CLAIM_LEVEL")
        res = api.create_audit(
            {"pharmacy_id": pharmacy["id"], "window_start_date": "2026-03-31",
             "window_end_date": "2026-06-30", "extrapolation_method": "CLAIM_LEVEL"},
            auditor_headers,
        )
        validate_error(res, "ERR_AUDIT_WINDOW_OVERLAP", expected_status=422)
        assert get_audit(first["id"])["status"] == "OPEN"

    def test_next_day_window_accepted(self, api, auditor_headers):
        """PRD §3.8: "a new audit is rejected with `ERR_AUDIT_WINDOW_OVERLAP` (HTTP 422)
        when the same pharmacy already has an audit in `OPEN`, `FINDINGS_RECORDED`, or
        `DISPUTED` status whose closed window intersects the new one — and because both
        window bounds are inclusive, windows that merely touch (the new start equal to
        an existing end) count as overlapping."

        Design: Difficulty/boundary_precision_check/audit_window_touching_boundary
        """
        pharmacy = make_pharmacy(ncpdp_id="NCPDP-W1", name="Rx Window")
        first = make_audit(pharmacy["id"], window_start_date="2026-01-01",
                           window_end_date="2026-03-31", extrapolation_method="CLAIM_LEVEL")
        created = validate_success(
            api.create_audit(
                {"pharmacy_id": pharmacy["id"], "window_start_date": "2026-04-01",
                 "window_end_date": "2026-06-30", "extrapolation_method": "CLAIM_LEVEL"},
                auditor_headers,
            ),
            201,
        )
        assert created["status"] == "OPEN"
        assert get_audit(first["id"])["status"] == "OPEN"

    def test_touching_window_rejected_closed_interval(self, api, auditor_headers):
        """PRD §3.8: "Retrospective review begins when an `Auditor` opens a
        **PharmacyAudit** against a pharmacy, supplying the `pharmacy_id`, an inclusive
        closed window from `window_start_date` through `window_end_date` (the end must
        be on or after the start, else `ERR_INVALID_REQUEST`), and an
        `extrapolation_method` of `CLAIM_LEVEL` or `EXTRAPOLATED`."
        PRD §3.8: "and because both window bounds are inclusive, windows that merely
        touch (the new start equal to an existing end) count as overlapping."

        Design: Difficulty/resource_temporal_overlap/audit_window_closed_interval_overlap
        """
        pharmacy = make_pharmacy(ncpdp_id="NCPDP-W2", name="Rx Window Two",
                                 channel="MAIL_ORDER")
        make_audit(pharmacy["id"], window_start_date="2026-01-01",
                   window_end_date="2026-03-31", extrapolation_method="EXTRAPOLATED")
        res = api.create_audit(
            {"pharmacy_id": pharmacy["id"], "window_start_date": "2026-03-31",
             "window_end_date": "2026-06-30", "extrapolation_method": "CLAIM_LEVEL"},
            auditor_headers,
        )
        validate_error(res, "ERR_AUDIT_WINDOW_OVERLAP", expected_status=422)

    def test_rejected_overlap_audit_not_persisted(self, api, auditor_headers):
        """PRD §3.8: "a new audit is rejected with `ERR_AUDIT_WINDOW_OVERLAP` (HTTP 422)
        when the same pharmacy already has an audit in `OPEN`, `FINDINGS_RECORDED`, or
        `DISPUTED` status whose closed window intersects the new one"
        PRD §3.8: "Audit listings can be filtered by `pharmacy_id` or `status`."

        Design: Difficulty/resource_temporal_overlap/audit_window_closed_interval_overlap
        """
        pharmacy = make_pharmacy(ncpdp_id="NCPDP-W2", name="Rx Window Two",
                                 channel="MAIL_ORDER")
        make_audit(pharmacy["id"], window_start_date="2026-01-01",
                   window_end_date="2026-03-31", extrapolation_method="EXTRAPOLATED")
        res = api.create_audit(
            {"pharmacy_id": pharmacy["id"], "window_start_date": "2026-03-31",
             "window_end_date": "2026-06-30", "extrapolation_method": "CLAIM_LEVEL"},
            auditor_headers,
        )
        validate_error(res, "ERR_AUDIT_WINDOW_OVERLAP", expected_status=422)
        data, meta = validate_paginated(
            api.list_audits(auditor_headers, params={"pharmacy_id": pharmacy["id"]})
        )
        assert meta["total_count"] == 1, "The rejected audit must not be persisted"


class TestClawbackVariants:
    def test_claim_level_clawback_is_plain_sum(self, api, auditor_headers):
        """PRD §3.8: "Under `CLAIM_LEVEL`, `total_clawback_cents` is simply the sum of
        the findings' `clawback_cents` and the universe size is irrelevant to the
        total."
        PRD §3.8: "At close time the system measures `universe_paid_claims` as the count
        of the pharmacy's claims standing in `PAID` with `fill_date` inside the closed
        window."

        Design: Difficulty/dual_variant_calc/audit_clawback_claim_level_vs_extrapolated
        """
        s = make_audit_universe_scenario()
        audit = make_audit(s["pharmacy_a"]["id"], extrapolation_method="CLAIM_LEVEL")
        record_findings(audit["id"], [
            {"claim_id": s["claims_a"][0]["id"], "clawback_cents": 3333},
            {"claim_id": s["claims_a"][1]["id"], "clawback_cents": 1001},
        ])
        closed = validate_success(api.close_audit(audit["id"], auditor_headers), 200)
        assert closed["status"] == "CLOSED_WITH_FINDINGS"
        assert closed["sample_size"] == 2
        assert closed["universe_paid_claims"] == 3
        assert closed["total_clawback_cents"] == 4334, "3333 + 1001, universe irrelevant"

    def test_extrapolated_clawback_scales_per_claim(self, api, auditor_headers):
        """PRD §3.8: "Under `EXTRAPOLATED`, each finding's clawback is scaled by the
        ratio of `universe_paid_claims` to `sample_size`, each scaled amount is rounded
        half-up to whole cents first, and only then are the per-claim amounts summed —
        summing first and rounding once is forbidden, so findings of 3333 and 1001 cents
        with a ratio of three-halves produce 5000 plus 1502, a total of 6502 cents, not
        6501."

        Design: Difficulty/dual_variant_calc/audit_clawback_claim_level_vs_extrapolated
        """
        s = make_audit_universe_scenario()
        audit = make_audit(s["pharmacy_b"]["id"], extrapolation_method="EXTRAPOLATED")
        record_findings(audit["id"], [
            {"claim_id": s["claims_b"][0]["id"], "clawback_cents": 3333},
            {"claim_id": s["claims_b"][1]["id"], "clawback_cents": 1001},
        ])
        closed = validate_success(api.close_audit(audit["id"], auditor_headers), 200)
        assert closed["status"] == "CLOSED_WITH_FINDINGS"
        assert closed["sample_size"] == 2
        assert closed["universe_paid_claims"] == 3
        assert closed["total_clawback_cents"] == 6502
        pharmacy = get_pharmacy(s["pharmacy_b"]["id"])
        assert pharmacy["balance_cents"] == 23798, "30300 - 6502"


class TestExtrapolationRoundingOrder:
    def _rounding_scenario(self, api, auditor_headers):
        scenario = make_adjudication_scenario(
            plan_overrides={"dispensing_fee_cents": 100, "oop_max_cents": 1000000},
            drug_overrides={"name": "Genericillin-B", "therapeutic_class": "ANTIBIOTIC",
                            "unit_cost_cents": 1000, "max_daily_dose_units": 100},
            entry_overrides={"copay_flat_cents": 0},
            pharmacy_overrides={"auto_suspend_threshold_cents": 1000000},
        )
        claims = [
            create_paid_claim(scenario["member"]["id"], scenario["drug"]["id"],
                              scenario["pharmacy"]["id"], fill_date=fill,
                              quantity=10, days_supply=10)
            for fill in ("2026-03-01", "2026-04-01", "2026-05-01")
        ]
        audit = make_audit(scenario["pharmacy"]["id"], extrapolation_method="EXTRAPOLATED")
        record_findings(audit["id"], [
            {"claim_id": claims[0]["id"], "clawback_cents": 3333},
            {"claim_id": claims[1]["id"], "clawback_cents": 1001},
        ])
        return scenario, claims, audit

    def test_per_claim_round_then_sum(self, api, auditor_headers):
        """PRD §3.8: "Under `EXTRAPOLATED`, each finding's clawback is scaled by the
        ratio of `universe_paid_claims` to `sample_size`, each scaled amount is rounded
        half-up to whole cents first, and only then are the per-claim amounts summed —
        summing first and rounding once is forbidden, so findings of 3333 and 1001 cents
        with a ratio of three-halves produce 5000 plus 1502, a total of 6502 cents, not
        6501."

        Design: Difficulty/combinatorial_formula/audit_extrapolation_per_claim_rounding_order
        """
        scenario, claims, audit = self._rounding_scenario(api, auditor_headers)
        closed = validate_success(api.close_audit(audit["id"], auditor_headers), 200)
        assert closed["total_clawback_cents"] == 6502, (
            f"Pinned order: round_half_up(3333*1.5)=5000 plus round_half_up(1001*1.5)=1502; "
            f"sum-then-round would give 6501; got {closed['total_clawback_cents']}"
        )
        assert closed["universe_paid_claims"] == 3
        assert closed["sample_size"] == 2

    def test_extrapolated_close_debits_pharmacy_balance(self, api, auditor_headers):
        """PRD §3.8: "the pharmacy's `balance_cents` is reduced by
        `total_clawback_cents`, and the auto-suspension check runs on the resulting
        balance"
        PRD §2.8: "when an audit closes with findings, the audit's `total_clawback_cents`
        is subtracted."

        Design: Difficulty/combinatorial_formula/audit_extrapolation_per_claim_rounding_order
        """
        scenario, claims, audit = self._rounding_scenario(api, auditor_headers)
        validate_success(api.close_audit(audit["id"], auditor_headers), 200)
        pharmacy = get_pharmacy(scenario["pharmacy"]["id"])
        assert pharmacy["balance_cents"] == 23798, "3 x 10100 - 6502"
        assert pharmacy["status"] == "ACTIVE", "23798 is far above the -1000000 threshold"


class TestDisputeRevisionCycle:
    def _dispute_scenario(self):
        scenario = make_adjudication_scenario(
            plan_overrides={"dispensing_fee_cents": 100, "oop_max_cents": 1000000},
            drug_overrides={"name": "Genericillin-C", "therapeutic_class": "ANTIBIOTIC",
                            "unit_cost_cents": 1000, "max_daily_dose_units": 100},
            entry_overrides={"copay_flat_cents": 0},
            pharmacy_overrides={"auto_suspend_threshold_cents": 1000000},
        )
        claim = create_paid_claim(scenario["member"]["id"], scenario["drug"]["id"],
                                  scenario["pharmacy"]["id"], fill_date="2026-03-01",
                                  quantity=10, days_supply=10)
        audit = make_audit(scenario["pharmacy"]["id"], extrapolation_method="CLAIM_LEVEL")
        return scenario, claim, audit

    def test_findings_then_dispute_transitions(self, api):
        """PRD §3.8: "Each recording replaces the previous finding set in its entirety
        and recomputes `sample_size` as the count of findings. Claims newly referenced
        by the set move from `UNAUDITED` to `FLAGGED`, while claims dropped from the
        prior set return to `UNAUDITED`."
        PRD §3.8: "its own pharmacist disputes the audit with a `dispute_reason`, which
        is permitted only from `FINDINGS_RECORDED` — otherwise `ERR_AUDIT_INVALID_STATE`
        — and moves the audit to `DISPUTED`, recording the reason (the most recent
        dispute's reason is the one retained)."

        Design: Difficulty/non_linear_state_machine/audit_dispute_revision_cycle
        """
        scenario, claim, audit = self._dispute_scenario()
        recorded = record_findings(audit["id"], [
            {"claim_id": claim["id"], "clawback_cents": 1000},
        ])
        assert recorded["status"] == "FINDINGS_RECORDED"
        flagged = get_claim(claim["id"])
        assert flagged["audit_status"] == "FLAGGED"

        disputed = validate_success(
            api.dispute_audit(audit["id"], {"dispute_reason": "documentation provided"},
                              scenario["pharmacist_headers"]),
            200,
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason"] == "documentation provided"

    def test_revision_after_dispute_then_close(self, api, auditor_headers):
        """PRD §3.8: "The dispute cycle completes only when the auditor records revised
        findings, moving the audit back to `FINDINGS_RECORDED`; an audit standing in
        `DISPUTED` cannot be closed."
        PRD §3.8: "Every claim named in the findings then moves from `FLAGGED` to
        `CLAWED_BACK`"

        Design: Difficulty/non_linear_state_machine/audit_dispute_revision_cycle
        """
        scenario, claim, audit = self._dispute_scenario()
        record_findings(audit["id"], [{"claim_id": claim["id"], "clawback_cents": 1000}])
        validate_success(
            api.dispute_audit(audit["id"], {"dispute_reason": "documentation provided"},
                              scenario["pharmacist_headers"]),
            200,
        )
        revised = record_findings(audit["id"], [
            {"claim_id": claim["id"], "clawback_cents": 2000},
        ])
        assert revised["status"] == "FINDINGS_RECORDED", "revision completes the dispute cycle"
        assert revised["sample_size"] == 1

        closed = validate_success(api.close_audit(audit["id"], auditor_headers), 200)
        assert closed["status"] == "CLOSED_WITH_FINDINGS"
        assert closed["total_clawback_cents"] == 2000, "only the revised finding is clawed back"
        assert get_claim(claim["id"])["audit_status"] == "CLAWED_BACK"
        assert get_pharmacy(scenario["pharmacy"]["id"])["balance_cents"] == 8100


def test_audit_close_from_disputed_rejected(api, auditor_headers):
    """PRD §3.8: "The dispute cycle completes only when the auditor records revised
    findings, moving the audit back to `FINDINGS_RECORDED`; an audit standing in
    `DISPUTED` cannot be closed."
    PRD §3.8: "from any other status the call is `ERR_AUDIT_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/audit_close_from_disputed_rejected
    """
    scenario = make_adjudication_scenario(
        drug_overrides={"ndc": "00000-9009", "name": "Disputol", "unit_cost_cents": 1000,
                        "max_daily_dose_units": 100},
        entry_overrides={"copay_flat_cents": 0},
        pharmacy_overrides={"auto_suspend_threshold_cents": 50000},
    )
    claim = create_paid_claim(scenario["member"]["id"], scenario["drug"]["id"],
                              scenario["pharmacy"]["id"], fill_date="2026-03-01")
    audit = make_audit(scenario["pharmacy"]["id"], extrapolation_method="CLAIM_LEVEL")
    record_findings(audit["id"], [{"claim_id": claim["id"], "clawback_cents": 1000}])
    validate_success(
        api.dispute_audit(audit["id"], {"dispute_reason": "contesting"},
                          scenario["pharmacist_headers"]),
        200,
    )
    res = api.close_audit(audit["id"], auditor_headers)
    validate_error(res, "ERR_AUDIT_INVALID_STATE", expected_status=409)
    after = get_audit(audit["id"])
    assert after["status"] == "DISPUTED"
    assert after["total_clawback_cents"] == 0


def test_claim_outside_audit_window_not_auditable(api, auditor_headers):
    """PRD §3.8: "Every referenced claim must be auditable: it must exist, belong to the
    audit's pharmacy, stand in `PAID`, carry a `fill_date` inside the audit's closed
    window, and still be `UNAUDITED` — any violation is `ERR_CLAIM_NOT_AUDITABLE`
    (HTTP 422)."

    Design: Corner/validations/claim_outside_audit_window_not_auditable
    """
    scenario = make_adjudication_scenario(
        drug_overrides={"ndc": "00000-9029", "name": "Auditex", "unit_cost_cents": 1000,
                        "max_daily_dose_units": 100},
        entry_overrides={"copay_flat_cents": 0},
    )
    claim = create_paid_claim(scenario["member"]["id"], scenario["drug"]["id"],
                              scenario["pharmacy"]["id"], fill_date="2026-05-01")
    audit = make_audit(scenario["pharmacy"]["id"], window_start_date="2026-01-01",
                       window_end_date="2026-03-31", extrapolation_method="CLAIM_LEVEL")
    res = api.record_findings(
        audit["id"], {"findings": [{"claim_id": claim["id"], "clawback_cents": 1000}]},
        auditor_headers,
    )
    validate_error(res, "ERR_CLAIM_NOT_AUDITABLE", expected_status=422)
    after = get_audit(audit["id"])
    assert after["status"] == "OPEN"
    assert after["findings"] == []
    assert get_claim(claim["id"])["audit_status"] == "UNAUDITED"


def test_empty_findings_rejected(api, auditor_headers):
    """PRD §3.8: "The auditor submits a `findings` list of claim-and-amount pairs — each
    pairing a `claim_id` with a strictly positive `clawback_cents`, and an empty list is
    `ERR_INVALID_REQUEST` — from any of `OPEN`, `FINDINGS_RECORDED`, or `DISPUTED`
    status; from any other status the call is `ERR_AUDIT_INVALID_STATE` (HTTP 409)."

    Design: Corner/validations/empty_findings_rejected
    """
    pharmacy = make_pharmacy(ncpdp_id="NCPDP-EMF", name="Rx Empty")
    audit = make_audit(pharmacy["id"], window_start_date="2026-01-01",
                       window_end_date="2026-03-31", extrapolation_method="CLAIM_LEVEL")
    res = api.record_findings(audit["id"], {"findings": []}, auditor_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)
    assert get_audit(audit["id"])["status"] == "OPEN"


class TestAuditCloseClawbackSuspensionCascade:
    def test_close_cascades_to_clawback_rebate_void_and_suspension(self, api, auditor_headers):
        """PRD §3.8: "Every claim named in the findings then moves from `FLAGGED` to
        `CLAWED_BACK`, any such claim whose `rebate_tag` was `REBATE_ELIGIBLE` is voided
        to `REBATE_VOID`, the pharmacy's `balance_cents` is reduced by
        `total_clawback_cents`, and the auto-suspension check runs on the resulting
        balance — which may tip the pharmacy from `ACTIVE` to `SUSPENDED` per §2.8."

        Design: Difficulty/transitive_cascade/audit_close_clawback_suspension_cascade
        """
        scenario = make_suspended_pharmacy_scenario(
            clawback_cents=16000, entry_overrides={"rebate_eligible": True},
        )
        claim = get_claim(scenario["claim"]["id"], auditor_headers)
        assert claim["audit_status"] == "CLAWED_BACK"
        assert claim["rebate_tag"] == "REBATE_VOID"
        pharmacy = scenario["pharmacy"]
        assert pharmacy["balance_cents"] == -6000, "10000 - 16000"
        assert pharmacy["status"] == "SUSPENDED", "-6000 <= -5000 trips the threshold"

    def test_suspended_pharmacy_cannot_submit_after_cascade(self, api):
        """PRD §2.8: "A `SUSPENDED` pharmacy cannot perform any claim write (submission,
        resubmission, reversal, or reprocessing); such attempts are rejected with
        `ERR_PHARMACY_SUSPENDED` (HTTP 409)."
        PRD §3.8: "the auto-suspension check runs on the resulting balance — which may
        tip the pharmacy from `ACTIVE` to `SUSPENDED` per §2.8."

        Design: Difficulty/transitive_cascade/audit_close_clawback_suspension_cascade
        """
        scenario = make_suspended_pharmacy_scenario(clawback_cents=16000)
        assert scenario["pharmacy"]["status"] == "SUSPENDED"
        res = submit_claim(
            scenario["member"]["id"], scenario["drug"]["id"],
            scenario["pharmacy"]["id"], fill_date="2026-06-01",
        )
        validate_error(res, "ERR_PHARMACY_SUSPENDED", expected_status=409)

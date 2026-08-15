"""Production capture posting, validation, crediting, void, and listing."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_wrvu,
    create_active_plan,
    create_agreement,
    create_capture_payload,
    create_effective_agreement,
    create_finalized_statement,
    create_validated_capture,
    get_success_data,
    post_capture,
    register_physician,
    set_clock,
    setup_active_plan_with_effective_agreement,
    validate_capture,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
COMMITTEE = TEST_USERS["committee_headers"]


def _dual_attribution_scenario(api):
    """One physician with EFFECTIVE agreements on a SERVICE_DATE plan and a
    POSTING_DATE plan; identical captures posted against both (PRD §3.4)."""
    set_clock()
    physician = register_physician(npi="1000000001", full_name="Dr Dual")
    plan_sd, _ = create_active_plan(name="SD Plan", credit_attribution_mode="SERVICE_DATE")
    plan_pd, _ = create_active_plan(name="PD Plan", credit_attribution_mode="POSTING_DATE")
    agr_sd = create_effective_agreement(physician["id"], plan_sd["id"])
    agr_pd = create_effective_agreement(physician["id"], plan_pd["id"])
    cap_sd = post_capture(agr_sd["id"], units=10, service_date="2026-02-10",
                          posting_date="2026-03-02")
    cap_pd = post_capture(agr_pd["id"], units=10, service_date="2026-02-10",
                          posting_date="2026-03-02")
    return {"physician": physician, "agr_sd": agr_sd, "agr_pd": agr_pd,
            "cap_sd": cap_sd, "cap_pd": cap_pd}


class TestCreditAttributionModes:
    def test_service_date_plan_buckets_by_service_month(self, api):
        """PRD §3.4: "The `credited_period` month bucket is then assigned per the plan's `credit_attribution_mode`: under `SERVICE_DATE` the bucket is the month of the `service_date` — a capture served 2026-02-10 and posted 2026-03-02 lands in period 2026-02 — while under `POSTING_DATE` the identical capture lands in 2026-03, shifting tier attainment and statement inclusion by a month."

        Design: Difficulty/dual_variant_calc/capture_credit_attribution_mode_divergence
        """
        scenario = _dual_attribution_scenario(api)
        validated_sd = validate_capture(scenario["cap_sd"]["id"])
        assert_wrvu(validated_sd["credited_wrvu"], 9.70)
        assert validated_sd["credited_period"] == "2026-02", (
            "SERVICE_DATE attribution buckets by the service month"
        )

    def test_posting_date_plan_buckets_by_posting_month(self, api):
        """PRD §3.4: "under `SERVICE_DATE` the bucket is the month of the `service_date` — a capture served 2026-02-10 and posted 2026-03-02 lands in period 2026-02 — while under `POSTING_DATE` the identical capture lands in 2026-03, shifting tier attainment and statement inclusion by a month."

        Design: Difficulty/dual_variant_calc/capture_credit_attribution_mode_divergence
        """
        scenario = _dual_attribution_scenario(api)
        validated_pd = validate_capture(scenario["cap_pd"]["id"])
        assert_wrvu(validated_pd["credited_wrvu"], 9.70)
        assert validated_pd["credited_period"] == "2026-03", (
            "POSTING_DATE attribution buckets the identical capture by posting month"
        )
        validated_sd = validate_capture(scenario["cap_sd"]["id"])
        assert validated_sd["credited_period"] != validated_pd["credited_period"], (
            "same inputs, divergent period buckets across the two modes"
        )


class TestCaptureGuards:
    def test_post_to_draft_agreement_rejected(self, api):
        """PRD §3.4: "Three guards protect posting, in this order after the state ladder: the agreement must be `EFFECTIVE` (`ERR_AGREEMENT_NOT_EFFECTIVE`)"

        Design: Corner/validations/capture_post_to_draft_agreement_rejected
        """
        set_clock()
        physician = register_physician(npi="1000000241", full_name="Dr Draft")
        plan, _ = create_active_plan(name="Draft Plan")
        agreement = create_agreement(physician["id"], plan["id"])
        assert agreement["status"] == "DRAFT"
        resp = api.create_capture(
            agreement["id"],
            create_capture_payload(units=1, service_date="2026-02-10",
                                   posting_date="2026-02-10"),
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_EFFECTIVE)

    def test_validate_without_covering_rate_rejected(self, api):
        """PRD §3.4: "For a `CLINICAL` capture the server resolves the unique rate row on the agreement's plan whose `cpt_code` matches and whose half-open window covers the `service_date`; if no such row exists the validation is rejected with `ERR_RATE_NOT_FOUND`."

        Design: Corner/validations/rate_not_found_on_validate
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000240", plan_name="Rate Plan"
        )
        capture = post_capture(scenario["agreement"]["id"], cpt_code="99999", units=1)
        resp = api.validate_capture(capture["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_RATE_NOT_FOUND)
        after = get_success_data(api.get_capture(capture["id"], ANALYST))
        assert after["capture_status"] == "POSTED"
        assert after["credit_status"] == "UNCREDITED"
        assert after["credited_wrvu"] is None

    def test_period_locked_capture_rejected(self, api):
        """PRD §3.4: "the `service_date` must not fall inside a period already covered by a `FINALIZED` statement on the same agreement — the period is locked once paid, and such a posting is rejected with `ERR_PERIOD_LOCKED`."

        Design: Corner/validations/period_locked_capture_rejected
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000235", plan_name="Lock Plan"
        )
        agreement = scenario["agreement"]
        create_finalized_statement(agreement["id"], 2026, 2)
        resp_locked = api.create_capture(
            agreement["id"],
            create_capture_payload(units=1, service_date="2026-02-25",
                                   posting_date="2026-03-01"),
            ANALYST,
        )
        validate_error(resp_locked, ApiErrorId.ERR_PERIOD_LOCKED)
        resp_open = api.create_capture(
            agreement["id"],
            create_capture_payload(units=1, service_date="2026-03-05",
                                   posting_date="2026-03-05"),
            ANALYST,
        )
        validate_success(resp_open, 201)

    def test_compliance_hold_beats_rate_lookup(self, api):
        """PRD §3.4: "Validating a capture requires it to still be `POSTED` and `UNCREDITED` (anything else is `ERR_INVALID_STATE`) and the agreement to be free of a compliance hold."
        PRD §3.3: "the flag is true exactly when the agreement is `EFFECTIVE` and the logical clock has moved strictly later than twelve months after `fmv_reviewed_at`. A held agreement cannot accept new production postings and cannot validate pending captures — both are rejected with `ERR_COMPLIANCE_HOLD`."
        PRD §2.9: "Business-safety rules follow those: segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), FMV cooling-off (`ERR_FMV_COOLING_OFF`), compliance hold (`ERR_COMPLIANCE_HOLD`), and FMV staleness (`ERR_FMV_STALE`)."
        PRD §2.9: "Payload shape (`ERR_VALIDATION`) is checked next, then business constraints (tier ordering, rate-window overlap, successor uniqueness, supervision party/window rules, duplicates, open disputes, true-up guards, successor linkage), then temporal rules (period locked, statement chronology, plan-change timing), then referential rules (rate coverage, dispute-subject consistency)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_capture_posting
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000051", plan_name="Hold Plan"
        )
        capture = post_capture(scenario["agreement"]["id"], cpt_code="00000", units=1,
                               service_date="2026-06-15", posting_date="2026-06-15")
        set_clock("2027-02-15T00:00:00Z")  # 12 months after fmv_reviewed_at have passed
        resp = api.validate_capture(capture["id"], ANALYST)
        err = validate_error(resp, ApiErrorId.ERR_COMPLIANCE_HOLD)
        assert resp.status_code == 422
        assert err["error_id"] != "ERR_RATE_NOT_FOUND", (
            "no rate row covers CPT 00000 either, but compliance hold is a "
            "business-safety rule and fires before the referential rate lookup"
        )

    def test_compliance_hold_leaves_capture_and_agreement_untouched(self, api):
        """PRD §3.3: "While an agreement is `EFFECTIVE`, the server continuously derives its `compliance_hold` flag: the flag is true exactly when the agreement is `EFFECTIVE` and the logical clock has moved strictly later than twelve months after `fmv_reviewed_at`."
        PRD §3.4: "A posted capture is born with `capture_status` `POSTED`, `credit_status` `UNCREDITED`"

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_capture_posting
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000051", plan_name="Hold Plan"
        )
        agreement = scenario["agreement"]
        capture = post_capture(agreement["id"], cpt_code="00000", units=1,
                               service_date="2026-06-15", posting_date="2026-06-15")
        set_clock("2027-02-15T00:00:00Z")
        validate_error(api.validate_capture(capture["id"], ANALYST),
                       ApiErrorId.ERR_COMPLIANCE_HOLD)
        agr_after = get_success_data(api.get_agreement(agreement["id"], ANALYST))
        assert agr_after["compliance_hold"] is True
        assert agr_after["status"] == "EFFECTIVE"
        cap_after = get_success_data(api.get_capture(capture["id"], ANALYST))
        assert cap_after["capture_status"] == "POSTED"
        assert cap_after["credit_status"] == "UNCREDITED"


class TestCaptureLifecycle:
    def test_validate_twice_rejected(self, api):
        """PRD §3.4: "Validating a capture requires it to still be `POSTED` and `UNCREDITED` (anything else is `ERR_INVALID_STATE`)"

        Design: Corner/state_machines/capture_validate_twice_rejected
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000210", plan_name="Idem Plan"
        )
        capture = create_validated_capture(scenario["agreement"]["id"], units=10)
        resp = api.validate_capture(capture["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        agreement = get_success_data(api.get_agreement(scenario["agreement"]["id"], ANALYST))
        assert_wrvu(agreement["ytd_wrvu_credited"], 9.70, )

    def test_void_then_validate_rejected(self, api):
        """PRD §3.4: "A capture that was posted in error and never validated can be voided: voiding moves a `POSTED`, still-`UNCREDITED` capture to `VOIDED`."
        PRD §3.4: "Validating a capture requires it to still be `POSTED` and `UNCREDITED` (anything else is `ERR_INVALID_STATE`)"

        Design: Corner/state_machines/capture_void_then_validate_rejected
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000211", plan_name="Void Plan"
        )
        capture = post_capture(scenario["agreement"]["id"], units=5)
        voided = validate_success(api.void_capture(capture["id"], ANALYST), 200)
        assert voided["capture_status"] == "VOIDED"
        assert voided["credit_status"] == "UNCREDITED", "voiding is documentation-only"
        resp = api.validate_capture(capture["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        agreement = get_success_data(api.get_agreement(scenario["agreement"]["id"], ANALYST))
        assert_wrvu(agreement["ytd_wrvu_credited"], 0.00)


class TestCreditingPrecision:
    def test_round_half_up_per_capture(self, api):
        """PRD §2.7: "a rate row's `wrvu_value` may carry up to 3 decimal places, and a capture's credited wRVU is pinned to 2 decimal places using round-half-up, computed per capture and never aggregated before rounding."
        PRD §3.4: "`credited_wrvu` is computed as `units` multiplied by `wrvu_value_applied`, rounded half-up to 2 decimal places."

        Design: Corner/calculations/wrvu_credit_rounding_half_up
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000220", plan_name="Round Plan",
            rates=[
                {"cpt_code": "99213", "wrvu_value": 0.97},
                {"cpt_code": "99300", "wrvu_value": 0.975},
            ],
        )
        agr_id = scenario["agreement"]["id"]
        cap1 = post_capture(agr_id, cpt_code="99300", units=1, service_date="2026-02-10",
                            posting_date="2026-02-10")
        cap2 = post_capture(agr_id, cpt_code="99213", units=3, service_date="2026-02-11",
                            posting_date="2026-02-11")
        v1 = validate_capture(cap1["id"])
        v2 = validate_capture(cap2["id"])
        assert_wrvu(v1["credited_wrvu"], 0.98)   # round_half_up(0.975, 2) rounds up
        assert_wrvu(v2["credited_wrvu"], 2.91)   # 0.97 x 3 exactly
        agreement = get_success_data(api.get_agreement(agr_id, ANALYST))
        assert_wrvu(agreement["ytd_wrvu_credited"], 3.89)

    def test_validate_response_and_followup_read_are_immediately_consistent(self, api):
        """PRD §2.10: "Ledger totals bubble up the same way: crediting, reversing, or allocating production recomputes the owning agreement's `ytd_wrvu_credited`, and finalizing or voiding a statement recomputes the agreement's `lifetime_paid_cents`. These recomputations are part of the originating operation, not deferred work."

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000290", plan_name="Imm Plan"
        )
        capture = post_capture(scenario["agreement"]["id"], units=10)
        validated = validate_capture(capture["id"])
        assert_wrvu(validated["credited_wrvu"], 9.70)
        assert validated["capture_status"] == "VALIDATED"
        assert validated["credit_status"] == "CREDITED"
        agreement = get_success_data(api.get_agreement(scenario["agreement"]["id"], ANALYST))
        assert_wrvu(agreement["ytd_wrvu_credited"], 9.70)


class TestCaptureListing:
    def test_capture_list_pagination_and_credit_status_filter(self, api):
        """PRD §2.3: "The `limit` defaults to 10, must be at least 1, and may not exceed 100; the `offset` defaults to 0. Results are always sorted by `created_at` in ascending order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object."
        PRD §3.4: "The agreement's capture listing accepts an optional `credit_status` filter."

        Design: Corner/endpoints/capture_list_pagination_and_filtering
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000260", plan_name="Page Plan"
        )
        agr_id = scenario["agreement"]["id"]
        c1 = post_capture(agr_id, units=1, service_date="2026-02-01",
                          posting_date="2026-02-01")
        c2 = post_capture(agr_id, units=2, service_date="2026-02-02",
                          posting_date="2026-02-02")
        c3 = post_capture(agr_id, units=3, service_date="2026-02-03",
                          posting_date="2026-02-03")
        validate_capture(c1["id"])
        validate_capture(c2["id"])
        page1, meta1 = validate_paginated(api.list_captures(
            agr_id, ANALYST, params={"credit_status": "CREDITED", "limit": 1, "offset": 0}
        ))
        assert len(page1) == 1 and meta1["total_count"] == 2 and meta1["has_more"] is True
        assert page1[0]["credit_status"] == "CREDITED"
        page2, meta2 = validate_paginated(api.list_captures(
            agr_id, ANALYST, params={"credit_status": "CREDITED", "limit": 1, "offset": 1}
        ))
        assert len(page2) == 1 and meta2["has_more"] is False
        assert {page1[0]["id"], page2[0]["id"]} == {c1["id"], c2["id"]}
        all_rows, meta_all = validate_paginated(api.list_captures(agr_id, ANALYST))
        assert meta_all["total_count"] == 3, "two CREDITED plus one UNCREDITED"
        assert meta_all["has_more"] is False, "default limit 10 covers all three"
        assert {r["id"] for r in all_rows} == {c1["id"], c2["id"], c3["id"]}


class TestCaptureRbac:
    def test_compliance_officer_cannot_post_captures(self, api):
        """PRD §4: POST /comp/physician-agreements/{id}/production-captures is authorized for CompAnalyst only.
        PRD §2.1: "A `ComplianceOfficer` is the independent reviewer for plan review decisions and agreement FMV reviews"
        PRD §2.1: "A request whose role is not listed among the roles authorized for the endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/compliance_officer_cannot_post_captures
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000272", plan_name="Iso Plan"
        )
        resp = api.create_capture(
            scenario["agreement"]["id"],
            create_capture_payload(units=1, service_date="2026-02-10",
                                   posting_date="2026-02-10"),
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

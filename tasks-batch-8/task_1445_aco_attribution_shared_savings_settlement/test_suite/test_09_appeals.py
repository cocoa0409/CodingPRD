"""Appeals: filing gates, rebuttal cycle with round cap, decision cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_election,
    approve_line,
    build_period_scenario,
    create_appeal_payload,
    decide_appeal,
    decide_payload,
    file_appeal,
    list_distribution_lines,
    list_records,
    make_actuary_headers,
    make_appeals_officer_headers,
    make_participant_representative_headers,
    rebut_appeal,
    rebuttal_payload,
    resume_appeal_review,
    set_clock,
    setup_attribution_appeal,
    setup_canonical_proposed_settlement,
    setup_lite_final_settlement,
    setup_lite_proposed_settlement,
    validate_error,
    validate_paginated,
    validate_success,
)

ACTUARY = make_actuary_headers()
APPEALS_OFFICER = make_appeals_officer_headers()

THREE_PARTICIPANTS = (("100000001", "PA", 5000), ("100000002", "PB", 3000),
                      ("100000003", "PC", 2000))


class TestAppealFilingRBAC:
    def test_appeals_officer_cannot_file_appeal(self, api, appeals_officer_headers):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list — or whose user attempts to act outside their permitted ownership
        scope — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.8: "A `ParticipantRepresentative` files an appeal by naming the
        `agreement_period_id`, a `subject_type` of `ATTRIBUTION` or
        `SETTLEMENT`, the `subject_id` of the challenged object, and free-text
        `grounds`."

        Design: Corner/rbac/appeals_officer_cannot_file_appeal
        """
        res = api.create_appeal(
            create_appeal_payload(NON_EXISTENT_UUID, "SETTLEMENT", NON_EXISTENT_UUID),
            appeals_officer_headers,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    def test_foreign_participant_rep_cannot_rebut(self, api):
        """PRD §3.8: "the filer — and only the filer, with `X-User-ID` required
        to equal `filed_by_participant_id` on pain of `ERR_UNAUTHORIZED` — may
        submit a rebuttal".

        Design: Corner/rbac/foreign_participant_rep_cannot_rebut
        """
        ctx = build_period_scenario(
            tax_id="ACO-R3",
            participants=(("100000001", "PA", 5000), ("100000002", "PB", 5000)),
            beneficiaries=({"medicare_id": "MBI-R3", "birth_year": 1980},),
            benchmark_variant=None,
            quality_scores=None,
        )
        record = list_records(beneficiary_id=ctx["beneficiaries"][0]["id"])[0]
        pa, pb = (p["id"] for p in ctx["participants"])
        appeal = file_appeal(ctx["period"]["id"], "ATTRIBUTION", record["id"], pa)
        res = api.create_rebuttal(
            appeal["id"], rebuttal_payload("not mine"),
            make_participant_representative_headers(pb),
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


class TestRebuttalCycle:
    def test_rebuttal_cycles_increment_round_count(self, api):
        """PRD §3.8: "may submit a rebuttal carrying a `memo`, moving the appeal
        to `REBUTTAL` and incrementing `round_count` by one" and "An
        `AppealsOfficer` returns the appeal to `UNDER_REVIEW` via resume-review,
        which itself requires the appeal to be in `REBUTTAL`".

        Design: Difficulty/non_linear_state_machine/appeal_rebuttal_review_cycle_with_round_cap
        """
        ctx = setup_attribution_appeal(tax_id="ACO-AC")
        appeal = ctx["appeal"]
        filer = ctx["participants"][0]["id"]
        round1 = rebut_appeal(appeal["id"], filer, memo="round 1")
        assert round1["status"] == "REBUTTAL"
        assert round1["round_count"] == 1
        resumed = resume_appeal_review(appeal["id"])
        assert resumed["status"] == "UNDER_REVIEW"
        round2 = rebut_appeal(appeal["id"], filer, memo="round 2")
        assert round2["round_count"] == 2

    def test_third_rebuttal_rejected_round_limit(self, api):
        """PRD §3.8: "the loop is capped: a rebuttal attempted when `round_count`
        has already reached 2 is rejected with `ERR_APPEAL_ROUND_LIMIT`
        (HTTP 422)."

        Design: Difficulty/non_linear_state_machine/appeal_rebuttal_review_cycle_with_round_cap
        """
        ctx = setup_attribution_appeal(tax_id="ACO-AC2")
        appeal = ctx["appeal"]
        filer = ctx["participants"][0]["id"]
        rebut_appeal(appeal["id"], filer, memo="round 1")
        resume_appeal_review(appeal["id"])
        rebut_appeal(appeal["id"], filer, memo="round 2")
        resume_appeal_review(appeal["id"])
        res = api.create_rebuttal(
            appeal["id"], rebuttal_payload("round 3"),
            make_participant_representative_headers(filer),
        )
        validate_error(res, ApiErrorId.ERR_APPEAL_ROUND_LIMIT, expected_status=422)

    def test_appeal_decide_from_rebuttal_rejected(self, api, appeals_officer_headers):
        """PRD §3.8: "Decision is the `AppealsOfficer`'s call: an `outcome` of
        `UPHELD` or `DENIED`, with optional `rationale`, from `UNDER_REVIEW`
        only (else `ERR_APPEAL_INVALID_STATE`)".

        Design: Corner/state_machines/appeal_decide_from_rebuttal_rejected
        """
        ctx = setup_attribution_appeal(tax_id="ACO-S4")
        appeal = ctx["appeal"]
        filer = ctx["participants"][0]["id"]
        rebut_appeal(appeal["id"], filer, memo="m")
        res = api.decide_appeal(appeal["id"], decide_payload("UPHELD"),
                                appeals_officer_headers)
        validate_error(res, ApiErrorId.ERR_APPEAL_INVALID_STATE, expected_status=409)


class TestAttributionAppealDecisions:
    def test_appeal_upheld_overturns_attribution_record(self, api, actuary_headers):
        """PRD §3.8: "An **upheld attribution appeal** moves the subject record
        from `UNDER_APPEAL` to `OVERTURNED` and then stales any `PROPOSED`
        settlement of the period."

        Design: Corner/state_machines/appeal_upheld_overturns_attribution_record
        """
        ctx = setup_lite_proposed_settlement(tax_id="ACO-S10")
        record = list_records(beneficiary_id=ctx["beneficiaries"][0]["id"])[0]
        filer = ctx["participants"][0]["id"]
        appeal = file_appeal(ctx["period"]["id"], "ATTRIBUTION", record["id"], filer,
                             grounds="wrong TIN")
        decide_appeal(appeal["id"], "UPHELD")
        record_after = validate_success(
            api.get_attribution_record(record["id"], actuary_headers), 200,
        )
        assert record_after["status"] == "OVERTURNED"
        settlement_after = validate_success(
            api.get_settlement(ctx["settlement"]["id"], actuary_headers), 200,
        )
        assert settlement_after["status"] == "STALE"
        summary = validate_success(
            api.get_expenditure_summary(ctx["period"]["id"], actuary_headers), 200,
        )
        assert summary["truncated_total_cents"] == 0

    def test_appeal_denied_reinstates_record(self, api, actuary_headers,
                                             appeals_officer_headers):
        """PRD §3.8: "A **denied attribution appeal** returns the record from
        `UNDER_APPEAL` to `FINAL`."

        Design: Corner/state_machines/appeal_denied_reinstates_record
        """
        ctx = setup_lite_proposed_settlement(tax_id="ACO-S11")
        record = list_records(beneficiary_id=ctx["beneficiaries"][0]["id"])[0]
        filer = ctx["participants"][0]["id"]
        appeal = file_appeal(ctx["period"]["id"], "ATTRIBUTION", record["id"], filer)
        res = api.decide_appeal(
            appeal["id"], decide_payload("DENIED", rationale="no basis"),
            appeals_officer_headers,
        )
        decided = validate_success(res, 200)
        assert decided["status"] == "DENIED"
        record_after = validate_success(
            api.get_attribution_record(record["id"], actuary_headers), 200,
        )
        assert record_after["status"] == "FINAL"
        settlement_after = validate_success(
            api.get_settlement(ctx["settlement"]["id"], actuary_headers), 200,
        )
        assert settlement_after["status"] == "PROPOSED"


class TestSettlementAppealCascade:
    def _final_settlement_with_approved_line(self, tax_id):
        """Canonical 3-participant period: FINAL settlement (pool 23054),
        distribution run executed, first line APPROVED; SETTLEMENT-subject
        appeal filed within the 30-day window (clock at its default)."""
        ctx = build_period_scenario(
            tax_id=tax_id,
            participants=THREE_PARTICIPANTS,
            beneficiaries=(
                {"medicare_id": "MBI-AU-R", "birth_year": 1960,
                 "dual_eligible": True, "disabled": True},
                {"medicare_id": "MBI-AU-P", "birth_year": 1990},
            ),
            claims=(
                {"beneficiary": 0, "participant": 0, "service_date": "2026-02-01",
                 "amount": 20000, "claim_type": "PART_B"},
                {"beneficiary": 1, "participant": 0, "service_date": "2026-02-05",
                 "amount": 20000, "claim_type": "PART_B"},
                {"beneficiary": 0, "participant": 0, "service_date": "2026-03-01",
                 "amount": 1500000, "claim_type": "PART_A"},
                {"beneficiary": 1, "participant": 0, "service_date": "2026-03-02",
                 "amount": 1341670, "claim_type": "PART_A"},
            ),
            settlement=True, finalize=True, distribution=True,
        )
        lines = list_distribution_lines(ctx["settlement"]["id"])
        approve_line(lines[0]["id"])
        appeal = file_appeal(ctx["period"]["id"], "SETTLEMENT", ctx["settlement"]["id"],
                             ctx["participants"][0]["id"], grounds="benchmark dispute")
        ctx["appeal"] = appeal
        return ctx

    def test_upheld_settlement_appeal_reopens_settlement(self, api, actuary_headers):
        """PRD §3.8: "An **upheld settlement appeal** moves the subject
        settlement from `FINAL` to `REOPENED` — with the full money-field
        recompute and the voiding of its `PENDING` and `APPROVED` distribution
        lines, exactly as a manual reopen."

        Design: Difficulty/transitive_cascade/cascade_appeal_upheld_to_reopen_to_voided
        """
        ctx = self._final_settlement_with_approved_line("ACO-AU")
        decided = decide_appeal(ctx["appeal"]["id"], "UPHELD",
                                rationale="recalculation warranted")
        assert decided["status"] == "UPHELD"
        settlement_after = validate_success(
            api.get_settlement(ctx["settlement"]["id"], actuary_headers), 200,
        )
        assert settlement_after["status"] == "REOPENED"
        assert settlement_after["distributable_pool_cents"] == 23054

    def test_upheld_settlement_appeal_voids_pending_and_approved_lines(
            self, api, actuary_headers):
        """PRD §3.7: "every distribution line in `PENDING` or `APPROVED` is
        voided, while `PAID` lines are left untouched".

        Design: Difficulty/transitive_cascade/cascade_appeal_upheld_to_reopen_to_voided
        """
        ctx = self._final_settlement_with_approved_line("ACO-AU2")
        decide_appeal(ctx["appeal"]["id"], "UPHELD",
                      rationale="recalculation warranted")
        res = api.list_distribution_lines(
            actuary_headers, params={"settlement_id": ctx["settlement"]["id"]},
        )
        lines, _meta = validate_paginated(res)
        assert len(lines) == 3
        assert all(line["status"] == "VOIDED" for line in lines)


class TestSettlementAppealGates:
    def test_appeal_on_proposed_settlement_rejected(self, api):
        """PRD §3.8: "Appealing a settlement requires the settlement to be
        `FINAL` (again `ERR_APPEAL_SUBJECT_STATE`)".

        Design: Corner/validations/appeal_on_proposed_settlement_rejected
        """
        ctx = setup_lite_proposed_settlement(tax_id="ACO-V13")
        filer = ctx["participants"][0]["id"]
        res = api.create_appeal(
            create_appeal_payload(ctx["period"]["id"], "SETTLEMENT",
                                  ctx["settlement"]["id"], grounds="too early"),
            make_participant_representative_headers(filer),
        )
        validate_error(res, ApiErrorId.ERR_APPEAL_SUBJECT_STATE, expected_status=409)

    def test_appeal_after_window_expired_rejected(self, api):
        """PRD §3.8: "must arrive within thirty days of the settlement's
        `finalized_at` as measured by the logical clock; a late filing is
        rejected with `ERR_APPEAL_WINDOW_EXPIRED` (HTTP 422)."
        PRD §2.8: "Before any such call, the logical clock starts at exactly
        `2026-08-01T00:00:00Z` and must never fall back to wall-clock time."

        Design: Corner/validations/appeal_after_window_expired_rejected
        """
        ctx = setup_lite_final_settlement(tax_id="ACO-V11")
        # finalized_at was stamped at the clock default 2026-08-01T00:00:00Z.
        set_clock("2026-09-15T00:00:00Z")
        filer = ctx["participants"][0]["id"]
        res = api.create_appeal(
            create_appeal_payload(ctx["period"]["id"], "SETTLEMENT",
                                  ctx["settlement"]["id"], grounds="late filing"),
            make_participant_representative_headers(filer),
        )
        validate_error(res, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED, expected_status=422)

    def test_appeal_subject_from_other_period_rejected(self, api):
        """PRD §3.8: "in both cases the subject must belong to the named period —
        a mismatch is rejected with `ERR_APPEAL_SUBJECT_MISMATCH` (HTTP 422)."

        Design: Corner/validations/appeal_subject_from_other_period_rejected
        """
        # P1: locked, no attribution records.
        p1 = build_period_scenario(
            tax_id="ACO-V12A", beneficiaries=(), claims=(), run=True,
            benchmark_variant=None, quality_scores=None,
        )
        # P2: locked with one FINAL record.
        p2 = build_period_scenario(
            tax_id="ACO-V12B",
            participants=(("100000009", "PB", 10000),),
            beneficiaries=({"medicare_id": "MBI-V12", "birth_year": 1980},),
            benchmark_variant=None, quality_scores=None,
        )
        record = list_records(beneficiary_id=p2["beneficiaries"][0]["id"])[0]
        filer = p1["participants"][0]["id"]
        res = api.create_appeal(
            create_appeal_payload(p1["period"]["id"], "ATTRIBUTION", record["id"],
                                  grounds="cross-period"),
            make_participant_representative_headers(filer),
        )
        validate_error(res, ApiErrorId.ERR_APPEAL_SUBJECT_MISMATCH, expected_status=422)


class TestOptOutCascade:
    def test_opt_out_excludes_final_attribution_record(self, api, actuary_headers):
        """PRD §3.3: "When an `OPT_OUT` election is recorded whose
        `effective_date` falls on or before a period's `performance_end_date`,
        every attribution record of that beneficiary in that period that is
        still live — `PROVISIONAL`, `FINAL`, or `UNDER_APPEAL` — transitions to
        `EXCLUDED_OPT_OUT`".

        Design: Difficulty/transitive_cascade/cascade_opt_out_election_to_record_to_stale
        """
        ctx = setup_canonical_proposed_settlement(tax_id="ACO-OO")
        bp = ctx["beneficiaries"][1]
        add_election(bp["id"], "OPT_OUT", "2026-06-01")
        records = list_records(beneficiary_id=bp["id"])
        assert len(records) == 1
        assert records[0]["status"] == "EXCLUDED_OPT_OUT"

    def test_opt_out_stales_settlement_and_shrinks_expenditure(self, api, actuary_headers):
        """PRD §3.3: "if a settlement of that period is sitting in `PROPOSED`, it
        cascades to `STALE` because the attribution and expenditure basis has
        shifted."
        PRD §3.6: "The included input set is every `ADJUDICATED` claim of the
        period whose `review_excluded` flag is false, whose beneficiary holds an
        attribution record of the period in `FINAL` or `UNDER_APPEAL` status".

        Design: Difficulty/transitive_cascade/cascade_opt_out_election_to_record_to_stale
        """
        ctx = setup_canonical_proposed_settlement(tax_id="ACO-OO2")
        bp = ctx["beneficiaries"][1]
        add_election(bp["id"], "OPT_OUT", "2026-06-01")
        settlement_after = validate_success(
            api.get_settlement(ctx["settlement"]["id"], actuary_headers), 200,
        )
        assert settlement_after["status"] == "STALE"
        summary = validate_success(
            api.get_expenditure_summary(ctx["period"]["id"], actuary_headers), 200,
        )
        # only the remaining attributed beneficiary's 20000 + 1500000 count
        assert summary["truncated_total_cents"] == 1520000
        assert summary["excluded_claim_count"] == 2

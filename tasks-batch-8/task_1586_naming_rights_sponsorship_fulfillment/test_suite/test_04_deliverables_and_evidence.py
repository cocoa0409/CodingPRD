"""Deliverable creation gates, suite-night buffers, evidence review cycle,
over-delivery boundary, cancellation cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_season,
    approve_evidence,
    create_active_contract,
    create_active_sponsor,
    create_asset,
    create_countersigned_contract,
    create_deliverable_payload,
    create_open_deliverable,
    create_suite_deliverable_payload,
    create_venue,
    get_success_data,
    reject_evidence,
    setup_active_contract_scenario,
    submit_and_approve,
    submit_evidence,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    AM_REVIEWER,
    AM_SUBMITTER,
    AM_THIRD,
    SALES,
    am_headers,
)


class TestDeliverableRequiresActiveContract:
    """Difficulty rule cross_entity_state_dependency, deliverable->contract."""

    def test_deliverable_create_rejected_on_countersigned_contract(self, api):
        """PRD §3.4: "Only then come the referential gates: the contract must
        be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`) and the asset `AVAILABLE`
        (`ERR_ASSET_NOT_AVAILABLE`)."

        Design: Difficulty/cross_entity_state_dependency/deliverable_create_requires_active_contract
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        asset = create_asset(venue["id"])
        contract = create_countersigned_contract(
            venue["id"], sponsor["id"], term_last_season=2028)
        assert contract["contract_status"] == "COUNTERSIGNED"

        resp = api.create_deliverable(
            create_deliverable_payload(contract["id"], asset["id"],
                                       season=2026, contracted_units=10),
            am_headers(AM_SUBMITTER))
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
                       expected_status=409)

    def test_deliverable_create_accepted_when_active_rejected_after_terminate(self, api):
        """PRD §3.4: "With the contract `ACTIVE`, an `ActivationManager` builds
        the season-by-season activation plan."
        PRD §3.4: "its `deliverable_status` is `IN_PROGRESS` when its `season`
        equals the venue's current epoch, and `SCHEDULED` for any later
        season."

        Design: Difficulty/cross_entity_state_dependency/deliverable_create_requires_active_contract
        """
        venue = create_venue()
        sponsor = create_active_sponsor()
        asset = create_asset(venue["id"])
        contract = create_active_contract(venue["id"], sponsor["id"],
                                          term_last_season=2028)

        created = validate_success(api.create_deliverable(
            create_deliverable_payload(contract["id"], asset["id"],
                                       season=2026, contracted_units=10),
            am_headers(AM_SUBMITTER)), expected_status=201)
        assert created["deliverable_status"] == "IN_PROGRESS"

        get_success_data(api.transition_contract(contract["id"],
                                                 {"action": "TERMINATE"}, SALES))
        resp = api.create_deliverable(
            create_deliverable_payload(contract["id"], asset["id"],
                                       season=2026, contracted_units=3),
            am_headers(AM_SUBMITTER))
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE,
                       expected_status=409)


class TestSuiteBookingTurnaroundBuffer:
    """Difficulty rule resource_temporal_overlap, buffered-date semantics."""

    def _setup_suite(self, api):
        venue = create_venue()
        sponsor = create_active_sponsor()
        suite = create_asset(venue["id"], name="Suite 12",
                             asset_class="HOSPITALITY",
                             rate_card_unit_cents=250_000,
                             avg_impressions_per_unit=1, cpm_cents=1)
        contract = create_active_contract(venue["id"], sponsor["id"],
                                          title="Suite package",
                                          term_last_season=2028,
                                          base_fee_cents=5_000_000)
        d1 = validate_success(api.create_deliverable(
            create_suite_deliverable_payload(
                contract["id"], suite["id"], "2026-10-10", "2026-10-12"),
            am_headers(AM_SUBMITTER)), expected_status=201)
        return venue, sponsor, suite, contract, d1

    def test_checkin_on_buffer_day_conflicts(self, api):
        """PRD §2.5: "A suite-night booking occupies the span from its
        `checkin_date` through its `checkout_date` plus a one-day turnaround
        buffer after checkout, so its blocked span ends one day after
        checkout." and "The boundary is deliberate: arriving exactly one day
        after the previous checkout conflicts, because that day is the
        turnaround buffer, while arriving two days after the previous checkout
        is allowed."

        Design: Difficulty/resource_temporal_overlap/suite_booking_turnaround_buffer_overlap
        """
        _v, _s, suite, contract, _d1 = self._setup_suite(api)
        resp = api.create_deliverable(
            create_suite_deliverable_payload(
                contract["id"], suite["id"], "2026-10-13", "2026-10-14"),
            am_headers(AM_SUBMITTER))
        validate_error(resp, ApiErrorId.ERR_SUITE_DATE_CONFLICT,
                       expected_status=409)

    def test_checkin_two_days_after_checkout_allowed(self, api):
        """PRD §2.5: "The boundary is deliberate: arriving exactly one day
        after the previous checkout conflicts, because that day is the
        turnaround buffer, while arriving two days after the previous checkout
        is allowed."

        Design: Difficulty/resource_temporal_overlap/suite_booking_turnaround_buffer_overlap
        """
        _v, _s, suite, contract, _d1 = self._setup_suite(api)
        created = validate_success(api.create_deliverable(
            create_suite_deliverable_payload(
                contract["id"], suite["id"], "2026-10-14", "2026-10-16"),
            am_headers(AM_SUBMITTER)), expected_status=201)
        assert created["unit_kind"] == "SUITE_NIGHT"


class TestEvidenceRejectResubmitCycle:
    """Difficulty rule non_linear_state_machine, evidence entity."""

    def test_resubmit_replaces_uri_and_rebaselines_submitter(self, api):
        """PRD §3.6: "From there it can be resubmitted (`RESUBMIT`) back to
        `SUBMITTED`, provided the deliverable is still `IN_PROGRESS`
        (`ERR_DELIVERABLE_NOT_OPEN`); resubmission replaces `evidence_uri` with
        the newly supplied value, replaces `submitted_by_user_id` with the
        acting user, and clears `review_note`, and the reject-resubmit loop may
        cycle any number of times."

        Design: Difficulty/non_linear_state_machine/evidence_reject_resubmit_cycle
        """
        s = setup_active_contract_scenario()
        d = create_open_deliverable(s["contract"]["id"], s["asset"]["id"],
                                    season=2026, contracted_units=10)
        e = submit_evidence(d["id"], 4, evidence_uri="s3://pop/v1.pdf",
                            submitter=AM_SUBMITTER)
        reject_evidence(e["id"], reviewer=AM_REVIEWER,
                        review_note="blurry photos")

        resubmitted = validate_success(api.transition_evidence(
            e["id"], {"action": "RESUBMIT", "evidence_uri": "s3://pop/v2.pdf"},
            am_headers(AM_REVIEWER)))
        assert resubmitted["submission_status"] == "SUBMITTED"
        assert resubmitted["submitted_by_user_id"] == AM_REVIEWER

    def test_original_submitter_may_approve_resubmission(self, api):
        """PRD §3.6: "The reviewer must be an `ActivationManager` whose
        `X-User-ID` differs from the submission's `submitted_by_user_id`; the
        same user reviewing their own submission is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.6: "On approval, the claimed units are added to the
        deliverable's `approved_units`, the reviewer's `review_note` is
        recorded on the submission, and when the approved units reach the
        contracted total the deliverable flips to `FULFILLED`, a terminal
        state."

        Design: Difficulty/non_linear_state_machine/evidence_reject_resubmit_cycle
        """
        s = setup_active_contract_scenario()
        d = create_open_deliverable(s["contract"]["id"], s["asset"]["id"],
                                    season=2026, contracted_units=10)
        e = submit_evidence(d["id"], 4, evidence_uri="s3://pop/v1.pdf",
                            submitter=AM_SUBMITTER)
        reject_evidence(e["id"], reviewer=AM_REVIEWER)
        # am-2 resubmits -> submitted_by becomes am-2
        get_success_data(api.transition_evidence(
            e["id"], {"action": "RESUBMIT", "evidence_uri": "s3://pop/v2.pdf"},
            am_headers(AM_REVIEWER)))
        # am-1 (the original submitter) is now a valid reviewer
        approved = validate_success(api.transition_evidence(
            e["id"], {"action": "APPROVE"}, am_headers(AM_SUBMITTER)))
        assert approved["submission_status"] == "APPROVED"
        got_d = validate_success(api.get_deliverable(d["id"],
                                                     am_headers(AM_SUBMITTER)))
        assert got_d["approved_units"] == 4


class TestEvidenceExactUnitsBoundary:
    """Difficulty rule boundary_precision_check, unit-count metric."""

    def _setup_partially_approved(self, api):
        s = setup_active_contract_scenario()
        d = create_open_deliverable(s["contract"]["id"], s["asset"]["id"],
                                    season=2026, contracted_units=10)
        submit_and_approve(d["id"], 6)
        e_over = submit_evidence(d["id"], 5, evidence_uri="s3://pop/e1.pdf")
        e_exact = submit_evidence(d["id"], 4, evidence_uri="s3://pop/e2.pdf")
        return s, d, e_over, e_exact

    def test_over_delivery_rejected_beyond_contracted_units(self, api):
        """PRD §3.6: "the approval must not over-deliver — `approved_units`
        plus `units_claimed` may not exceed `contracted_units`
        (`ERR_OVER_DELIVERY`)"

        Design: Difficulty/boundary_precision_check/evidence_exact_units_fulfills_deliverable
        """
        _s, d, e_over, _e_exact = self._setup_partially_approved(api)
        # approved 6 + claimed 5 = 11 > 10
        resp = api.transition_evidence(e_over["id"], {"action": "APPROVE"},
                                       am_headers(AM_REVIEWER))
        validate_error(resp, ApiErrorId.ERR_OVER_DELIVERY, expected_status=422)

    def test_exact_equality_approves_and_fulfills(self, api):
        """PRD §3.6: "On approval, the claimed units are added to the
        deliverable's `approved_units`, the reviewer's `review_note` is
        recorded on the submission, and when the approved units reach the
        contracted total the deliverable flips to `FULFILLED`, a terminal
        state."

        Design: Difficulty/boundary_precision_check/evidence_exact_units_fulfills_deliverable
        """
        _s, d, _e_over, e_exact = self._setup_partially_approved(api)
        # approved 6 + claimed 4 = 10 == 10
        ok = validate_success(api.transition_evidence(
            e_exact["id"], {"action": "APPROVE"}, am_headers(AM_REVIEWER)))
        assert ok["submission_status"] == "APPROVED"
        got_d = validate_success(api.get_deliverable(d["id"],
                                                     am_headers(AM_SUBMITTER)))
        assert got_d["approved_units"] == 10
        assert got_d["deliverable_status"] == "FULFILLED"


class TestDeliverableCancelCascade:
    def test_deliverable_cancel_voids_open_evidence(self, api):
        """PRD §3.4: "An activation manager may cancel (`CANCEL`) a deliverable
        from `SCHEDULED` or `IN_PROGRESS`; cancellation is terminal and, as
        part of the same act, voids every evidence submission of that
        deliverable still in `SUBMITTED` or `REJECTED`."

        Design: Corner/state_machines/deliverable_cancel_voids_open_evidence
        """
        s = setup_active_contract_scenario()
        d = create_open_deliverable(s["contract"]["id"], s["asset"]["id"],
                                    season=2026, contracted_units=10)
        e1 = submit_evidence(d["id"], 3, evidence_uri="s3://pop/e1.pdf")
        e2 = submit_evidence(d["id"], 2, evidence_uri="s3://pop/e2.pdf")
        reject_evidence(e2["id"], reviewer=AM_REVIEWER,
                        review_note="insufficient proof")

        cancelled = validate_success(api.transition_deliverable(
            d["id"], {"action": "CANCEL"}, am_headers(AM_SUBMITTER)))
        assert cancelled["deliverable_status"] == "CANCELLED"

        got_e1 = validate_success(api.get_evidence(e1["id"],
                                                   am_headers(AM_SUBMITTER)))
        got_e2 = validate_success(api.get_evidence(e2["id"],
                                                   am_headers(AM_SUBMITTER)))
        assert got_e1["submission_status"] == "VOIDED"
        assert got_e2["submission_status"] == "VOIDED"


class TestEvidenceReviewGates:
    def test_evidence_double_approve_rejected(self, api):
        """PRD §3.6: "Approval (`APPROVE`) runs its gates in pipeline order:
        the submission must be `SUBMITTED` (`ERR_INVALID_STATE`)"
        PRD §3.6: "`APPROVED` and `VOIDED` are terminal."

        Design: Corner/state_machines/evidence_double_approve_rejected
        """
        s = setup_active_contract_scenario()
        d = create_open_deliverable(s["contract"]["id"], s["asset"]["id"],
                                    season=2026, contracted_units=10)
        e = submit_and_approve(d["id"], 4)
        assert e["submission_status"] == "APPROVED"

        resp = api.transition_evidence(e["id"], {"action": "APPROVE"},
                                       am_headers(AM_THIRD))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        got_d = validate_success(api.get_deliverable(d["id"],
                                                     am_headers(AM_SUBMITTER)))
        assert got_d["approved_units"] == 4, "no double accrual"

    def test_evidence_self_approve_rejected(self, api):
        """PRD §3.6: "The reviewer must be an `ActivationManager` whose
        `X-User-ID` differs from the submission's `submitted_by_user_id`; the
        same user reviewing their own submission is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/evidence_self_approve_rejected
        """
        s = setup_active_contract_scenario()
        d = create_open_deliverable(s["contract"]["id"], s["asset"]["id"],
                                    season=2026, contracted_units=10)
        e = submit_evidence(d["id"], 4, submitter=AM_SUBMITTER)

        resp = api.transition_evidence(e["id"], {"action": "APPROVE"},
                                       am_headers(AM_SUBMITTER))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=403)
        got = validate_success(api.get_evidence(e["id"],
                                                am_headers(AM_SUBMITTER)))
        assert got["submission_status"] == "SUBMITTED"

    def test_evidence_on_missed_deliverable_rejected(self, api):
        """PRD §3.6: "An `ActivationManager` submits proof of performance
        against an `IN_PROGRESS` deliverable" and "A submission against a
        deliverable that is not open is rejected with
        `ERR_DELIVERABLE_NOT_OPEN`."

        Design: Corner/validations/evidence_on_missed_deliverable_rejected
        """
        s = setup_active_contract_scenario()
        d = create_open_deliverable(s["contract"]["id"], s["asset"]["id"],
                                    season=2026, contracted_units=10)
        submit_and_approve(d["id"], 7)
        advance_season(s["venue"]["id"])
        missed = validate_success(api.get_deliverable(d["id"],
                                                      am_headers(AM_SUBMITTER)))
        assert missed["deliverable_status"] == "MISSED"

        resp = api.create_evidence(
            {"deliverable_id": d["id"], "units_claimed": 1,
             "evidence_uri": "s3://pop/late.pdf"}, am_headers(AM_SUBMITTER))
        validate_error(resp, ApiErrorId.ERR_DELIVERABLE_NOT_OPEN,
                       expected_status=409)


class TestRejectLeavesApprovedUnitsUnchanged:
    def test_reject_evidence_leaves_approved_units_unchanged(self, api):
        """PRD §3.6: "On approval, the claimed units are added to the
        deliverable's `approved_units`, the reviewer's `review_note` is
        recorded on the submission, and when the approved units reach the
        contracted total the deliverable flips to `FULFILLED`, a terminal
        state."
        PRD §3.6: "Rejection (`REJECT`) enforces the same four-eyes rule,
        records the `review_note`, and moves the submission to `REJECTED`."

        Design: Corner/cross_cutting_layers/reject_evidence_leaves_approved_units_unchanged
        """
        s = setup_active_contract_scenario()
        d = create_open_deliverable(s["contract"]["id"], s["asset"]["id"],
                                    season=2026, contracted_units=10)
        e = submit_evidence(d["id"], 5, evidence_uri="s3://pop/v1.pdf")
        reject_evidence(e["id"], reviewer=AM_REVIEWER,
                        review_note="wrong game")

        mid = validate_success(api.get_deliverable(d["id"],
                                                   am_headers(AM_SUBMITTER)))
        assert mid["approved_units"] == 0, "REJECT accrues nothing"

        # Resubmit (submitter becomes am-2) then approve by am-1
        get_success_data(api.transition_evidence(
            e["id"], {"action": "RESUBMIT", "evidence_uri": "s3://pop/v2.pdf"},
            am_headers(AM_REVIEWER)))
        approve_evidence(e["id"], reviewer=AM_SUBMITTER)
        end = validate_success(api.get_deliverable(d["id"],
                                                   am_headers(AM_SUBMITTER)))
        assert end["approved_units"] == 5


class TestDeliverableTemporalAndAssetGates:
    def test_deliverable_season_out_of_term_rejected(self, api):
        """PRD §3.4: "The season must then sit inside the contract's term
        (`ERR_SEASON_OUT_OF_TERM`)"

        Design: Corner/validations/deliverable_season_out_of_term_rejected
        """
        s = setup_active_contract_scenario(term_last_season=2028)
        resp = api.create_deliverable(
            create_deliverable_payload(s["contract"]["id"], s["asset"]["id"],
                                       season=2029, contracted_units=10),
            am_headers(AM_SUBMITTER))
        validate_error(resp, ApiErrorId.ERR_SEASON_OUT_OF_TERM,
                       expected_status=422)

    def test_deliverable_on_retired_asset_rejected(self, api):
        """PRD §3.1: "Retirement never disturbs deliverables already on the
        books — it only blocks attaching new ones, which is rejected with
        `ERR_ASSET_NOT_AVAILABLE`."

        Design: Corner/validations/deliverable_on_retired_asset_rejected
        """
        s = setup_active_contract_scenario(term_last_season=2028)
        get_success_data(api.transition_asset(s["asset"]["id"],
                                              {"action": "RETIRE"}, ADMIN))
        resp = api.create_deliverable(
            create_deliverable_payload(s["contract"]["id"], s["asset"]["id"],
                                       season=2026, contracted_units=10),
            am_headers(AM_SUBMITTER))
        validate_error(resp, ApiErrorId.ERR_ASSET_NOT_AVAILABLE,
                       expected_status=409)

    def test_deliverable_season_closed_and_past_term_window_rejected(self, api):
        """PRD §3.4: "The season must then sit inside the contract's term
        (`ERR_SEASON_OUT_OF_TERM`) and must not already be closed — a season
        earlier than the venue's `current_season` is rejected with
        `ERR_SEASON_CLOSED`"
        PRD §3.3: "Creation validates the term window first — the first season
        must be no earlier than the venue's `current_season`, and the last
        season no earlier than the first, otherwise `ERR_SEASON_WINDOW_INVALID`"

        Design: Corner/validations/deliverable_season_closed_and_past_term_window_rejected
        """
        s = setup_active_contract_scenario(term_last_season=2028)
        advance_season(s["venue"]["id"])  # current_season now 2027

        resp_closed = api.create_deliverable(
            create_deliverable_payload(s["contract"]["id"], s["asset"]["id"],
                                       season=2026, contracted_units=10),
            am_headers(AM_SUBMITTER))
        validate_error(resp_closed, ApiErrorId.ERR_SEASON_CLOSED,
                       expected_status=422)

        resp_window = api.create_contract(
            {"venue_id": s["venue"]["id"], "sponsor_id": s["sponsor"]["id"],
             "title": "Retro", "term_first_season": 2026,
             "term_last_season": 2028, "base_fee_cents": 1_000_000,
             "escalator_pct": 0, "escalator_mode": "SIMPLE"}, SALES)
        validate_error(resp_window, ApiErrorId.ERR_SEASON_WINDOW_INVALID,
                       expected_status=422)

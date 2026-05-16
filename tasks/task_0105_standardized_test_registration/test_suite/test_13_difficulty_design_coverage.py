"""Difficulty-design coverage: at least TWO tests per declared
SCAFFOLD_DIFFICULTY_DESIGN.yaml instance.

Each test carries a `# difficulty: <rule_id>/<instance.name>` tag in
its docstring so the coverage audit can confirm every instance is
exercised. PRD-First applies: each citation quotes the PRD prose that
states the underlying rule, not the difficulty-design index itself.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    admin_cancel,
    advance_clock_to,
    advance_clock_to_check_in_window,
    api_client,
    approve_accommodation,
    assert_capacity_invariant,
    assert_money_invariant,
    cancel_payload,
    complete_registration_lifecycle,
    create_accommodation_request_payload,
    create_candidate,
    create_capacity,
    create_event_with_capacity,
    create_registration_payload,
    create_test_center,
    create_test_event,
    deny_accommodation,
    fmt_iso,
    force_confirmed_registration,
    make_accommodations_officer_headers,
    make_candidate_headers,
    parse_iso,
    post_score_report,
    reject_id_verification,
    request_more_info,
    reset_clock_to,
    resubmit_accommodation,
    run_sweep,
    self_cancel,
    setup_registration_at_clock,
    start_review,
    submit_accommodation_request,
    submit_and_approve_accommodation,
    submit_and_clear_id,
    submit_id_verification,
    validate_error,
    validate_paginated,
    validate_success,
    advance_clock_by,
)
from test_helpers.constants import TEST_DEFAULTS


# ===========================================================================
# RULE 1: dual_variant_calc
# ===========================================================================
class TestRule1DualVariantCalc:
    """# difficulty: dual_variant_calc"""

    # ---- Instance: refund_self_vs_official_cancellation ----
    def test_self_vs_official_cancellation_diverge_at_days_6(self, api):
        """PRD §3.8: "For self-initiated cancellations the per-tier
        rate above applies verbatim. For official cancellations ... the
        rate is forced to 1.00 on both the base fee and the late fee
        regardless of `days_before_test`".

        # difficulty: dual_variant_calc/refund_self_vs_official_cancellation

        Claim: at days_before_test=6 a SELF_INITIATED cancellation
        yields amount=0 (tier NONE), while an OFFICIAL_CANCELLATION on
        an identical sibling registration yields full base fee.
        """
        # Set up two registrations at days_before_test = 6.
        event_a, _, cand_a, reg_a = setup_registration_at_clock(
            test_date_iso="2026-06-08T09:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=0,
            clock_at_creation_iso="2026-06-02T09:00:00.000Z",
        )
        event_b, _, cand_b, reg_b = setup_registration_at_clock(
            test_date_iso="2026-06-08T09:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=0,
            clock_at_creation_iso="2026-06-02T09:00:00.000Z",
        )
        # Self-cancel A.
        self_cancel(event_a["id"], reg_a, cand_a)
        rows_a, _ = validate_paginated(
            api.list_refunds(event_a["id"], reg_a["id"],
                             TEST_USERS["registrar_headers"]),
        )
        # Admin-cancel B.
        admin_cancel(event_b["id"], reg_b["id"])
        rows_b, _ = validate_paginated(
            api.list_refunds(event_b["id"], reg_b["id"],
                             TEST_USERS["registrar_headers"]),
        )
        assert rows_a[0]["amount_cents"] == 0
        assert rows_a[0]["refund_channel"] == "SELF_INITIATED"
        assert rows_b[0]["amount_cents"] == 6000
        assert rows_b[0]["refund_channel"] == "OFFICIAL_CANCELLATION"

    def test_self_vs_official_cancellation_record_correct_amount_refunded(self, api):
        """PRD §3.8: "`amount_refunded_cents` is set to the sum of all
        its `RefundTransaction.amount_cents`".

        # difficulty: dual_variant_calc/refund_self_vs_official_cancellation

        Claim: the Registration's amount_refunded_cents matches the
        per-channel refund (0 for SELF at days=6, 6000 for OFFICIAL).
        """
        event_a, _, cand_a, reg_a = setup_registration_at_clock(
            test_date_iso="2026-06-08T09:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=0,
            clock_at_creation_iso="2026-06-02T09:00:00.000Z",
        )
        event_b, _, cand_b, reg_b = setup_registration_at_clock(
            test_date_iso="2026-06-08T09:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=0,
            clock_at_creation_iso="2026-06-02T09:00:00.000Z",
        )
        a_after = self_cancel(event_a["id"], reg_a, cand_a)
        b_after = admin_cancel(event_b["id"], reg_b["id"])
        assert a_after["amount_refunded_cents"] == 0
        assert b_after["amount_refunded_cents"] == 6000

    # ---- Instance: super_score_college_board_vs_institutional ----
    def _two_sat_sittings_for_candidate(self, cand):
        """Helper: build two completed SAT sittings with the same
        per-section scores used by the difficulty test recipe."""
        reset_clock_to("2024-05-01T00:00:00.000Z")
        ev1, reg1 = complete_registration_lifecycle(
            cand,
            test_type="SAT",
            test_date_iso="2024-06-15T09:00:00.000Z",
            registration_deadline="2024-06-01T00:00:00.000Z",
            late_registration_deadline="2024-06-10T00:00:00.000Z",
            score_release_date="2024-06-22T00:00:00.000Z",
        )
        post_score_report(
            ev1["id"], reg1["id"],
            section_scores={"reading_writing": 600, "math": 700},
            total_score=1300,
        )
        reset_clock_to("2025-05-01T00:00:00.000Z")
        ev2, reg2 = complete_registration_lifecycle(
            cand,
            test_type="SAT",
            test_date_iso="2025-06-15T09:00:00.000Z",
            registration_deadline="2025-06-01T00:00:00.000Z",
            late_registration_deadline="2025-06-10T00:00:00.000Z",
            score_release_date="2025-06-22T00:00:00.000Z",
        )
        post_score_report(
            ev2["id"], reg2["id"],
            section_scores={"reading_writing": 650, "math": 650},
            total_score=1300,
        )
        advance_clock_to("2025-09-01T00:00:00.000Z")

    def test_super_score_college_board_vs_institutional_diverge(self, api):
        """PRD §3.9: "In `COLLEGE_BOARD_OFFICIAL` mode (the default),
        each section's contribution is the maximum of that section's
        `section_scores` value across all sittings in the pool ...
        In `INSTITUTIONAL_SUBMISSION` mode, the system instead
        identifies the single sitting whose `total_score` is highest
        within the pool".

        # difficulty: dual_variant_calc/super_score_college_board_vs_institutional

        Claim: for two sittings (600/700 and 650/650), the COLLEGE_BOARD
        composite is 1350 (650 + 700) and the INSTITUTIONAL composite
        is 1300 (one sitting's full row).
        """
        cand = create_candidate()
        self._two_sat_sittings_for_candidate(cand)
        cb = validate_success(
            api.get_super_score(cand["id"], make_candidate_headers(cand["id"]),
                                params={"test_type": "SAT",
                                        "reporting_mode": "COLLEGE_BOARD_OFFICIAL"}),
            200,
        )
        inst = validate_success(
            api.get_super_score(cand["id"], make_candidate_headers(cand["id"]),
                                params={"test_type": "SAT",
                                        "reporting_mode": "INSTITUTIONAL_SUBMISSION"}),
            200,
        )
        assert cb["composite"] == 1350
        assert inst["composite"] == 1300

    def test_super_score_sittings_used_differs_between_modes(self, api):
        """PRD §3.9: "all sections of the returned composite come from
        the same sitting, even if a candidate's per-section maximum in
        isolation is higher elsewhere."

        # difficulty: dual_variant_calc/super_score_college_board_vs_institutional

        Claim: sittings_used == 2 in COLLEGE_BOARD_OFFICIAL but == 1
        in INSTITUTIONAL_SUBMISSION for the same pool.
        """
        cand = create_candidate()
        self._two_sat_sittings_for_candidate(cand)
        cb = validate_success(
            api.get_super_score(cand["id"], make_candidate_headers(cand["id"]),
                                params={"test_type": "SAT",
                                        "reporting_mode": "COLLEGE_BOARD_OFFICIAL"}),
            200,
        )
        inst = validate_success(
            api.get_super_score(cand["id"], make_candidate_headers(cand["id"]),
                                params={"test_type": "SAT",
                                        "reporting_mode": "INSTITUTIONAL_SUBMISSION"}),
            200,
        )
        assert cb["sittings_used"] == 2
        assert inst["sittings_used"] == 1


# ===========================================================================
# RULE 2: combinatorial_formula
# ===========================================================================
class TestRule2CombinatorialFormula:
    """# difficulty: combinatorial_formula"""

    # ---- Instance: standby_promotion_priority_nested_branches_mode_a ----
    def test_standby_promotion_accommodation_pool_first_then_general(self, api):
        """PRD §3.4: "With the inputs ... the selector first fills the
        accommodation slots: for up to the number of accommodation
        seats freed, it picks the highest-priority accommodation-
        required candidate and promotes them to `CONFIRMED`. Any
        accommodation slots left unfilled spill into the general pool
        ... Then the selector fills the general seats from the
        remaining candidates by the same priority key."

        # difficulty: combinatorial_formula/standby_promotion_priority_nested_branches_mode_a

        Claim: when one accommodation seat and one general seat are
        freed at the same instant, the accommodation pool's earliest
        candidate (A) is promoted into the accommodation slot, and the
        general pool's earliest non-accommodation candidate (C) is
        promoted into the general slot.
        """
        event, center, _ = create_event_with_capacity(
            total_capacity=2, accommodation_capacity=1,
        )
        # Fill the two seats with E (accommodation) and F (general).
        e_cand = create_candidate(has_iep_or_504=True)
        e_reg = force_confirmed_registration(event["id"], e_cand, center["id"])
        submit_and_approve_accommodation(e_cand, event["id"])
        f_cand = create_candidate(has_iep_or_504=False)
        f_reg = force_confirmed_registration(event["id"], f_cand, center["id"])

        # Now create four STANDBY rows in temporal order: C, D (general),
        # A, B (accommodation). PRD §3.4 pins `registered_at` to the
        # creation instant — the logical clock (PRD §2.10) only advances
        # on explicit admin advance, so we advance it between
        # registrations to give each row a distinct registered_at.
        base_clock = TEST_DEFAULTS["INITIAL_CLOCK"]
        c_cand = create_candidate(has_iep_or_504=False)
        c_res = api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=c_cand["id"], test_center_id=center["id"]),
            make_candidate_headers(c_cand["id"]),
        )
        c_reg = validate_success(c_res, 201)
        advance_clock_by(timedelta(seconds=1), base_clock)
        d_cand = create_candidate(has_iep_or_504=False)
        d_res = api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=d_cand["id"], test_center_id=center["id"]),
            make_candidate_headers(d_cand["id"]),
        )
        d_reg = validate_success(d_res, 201)
        advance_clock_by(timedelta(seconds=2), base_clock)
        a_cand = create_candidate(has_iep_or_504=True)
        a_res = api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=a_cand["id"], test_center_id=center["id"]),
            make_candidate_headers(a_cand["id"]),
        )
        a_reg = validate_success(a_res, 201)
        submit_and_approve_accommodation(a_cand, event["id"])  # makes A accommodation-required
        advance_clock_by(timedelta(seconds=3), base_clock)
        b_cand = create_candidate(has_iep_or_504=True)
        b_res = api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=b_cand["id"], test_center_id=center["id"]),
            make_candidate_headers(b_cand["id"]),
        )
        b_reg = validate_success(b_res, 201)
        submit_and_approve_accommodation(b_cand, event["id"])

        # Cancel E and F, freeing one accommodation seat and one general seat at once.
        admin_cancel(event["id"], e_reg["id"])
        admin_cancel(event["id"], f_reg["id"])

        # Refresh.
        def status(r):
            return validate_success(
                api.get_registration(event["id"], r["id"],
                                     TEST_USERS["registrar_headers"]),
                200,
            )["status"]
        # PRD §3.4: A wins accommodation pool (earlier than B). C wins general pool.
        assert status(a_reg) == "CONFIRMED"
        assert status(c_reg) == "CONFIRMED"
        assert status(b_reg) == "STANDBY"
        assert status(d_reg) == "STANDBY"

    def test_standby_priority_general_pool_earliest_wins(self, api):
        """PRD §3.4: "first by priority class ... then by `registered_at`
        ascending so earlier registrations win".

        # difficulty: combinatorial_formula/standby_promotion_priority_nested_branches_mode_a

        Claim: among two general standby rows on a single freed general
        seat, the one with the earlier registered_at is promoted.
        """
        event, center, _ = create_event_with_capacity(
            total_capacity=1, accommodation_capacity=0,
        )
        seed_cand = create_candidate()
        seed_reg = force_confirmed_registration(event["id"], seed_cand, center["id"])
        # PRD §3.4 pins `registered_at` to the creation instant; the
        # logical clock (PRD §2.10) only advances on explicit admin
        # advance, so we advance it between registrations.
        base_clock = TEST_DEFAULTS["INITIAL_CLOCK"]
        cand1 = create_candidate()
        r1 = validate_success(api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=cand1["id"], test_center_id=center["id"]),
            make_candidate_headers(cand1["id"])), 201)
        advance_clock_by(timedelta(seconds=1), base_clock)
        cand2 = create_candidate()
        r2 = validate_success(api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=cand2["id"], test_center_id=center["id"]),
            make_candidate_headers(cand2["id"])), 201)
        # Cancel seed.
        admin_cancel(event["id"], seed_reg["id"])
        r1_after = validate_success(
            api.get_registration(event["id"], r1["id"],
                                 TEST_USERS["registrar_headers"]), 200,
        )
        r2_after = validate_success(
            api.get_registration(event["id"], r2["id"],
                                 TEST_USERS["registrar_headers"]), 200,
        )
        assert r1_after["status"] == "CONFIRMED"
        assert r2_after["status"] == "STANDBY"

    # ---- Instance: tiered_refund_per_line_rounding_pinned_mode_b ----
    def test_per_line_rounding_litmus_4501_not_4500(self, api):
        """PRD §2.6: "Where the refund computation produces multiple
        per-line products, each line is rounded half-up to whole cents
        individually and only then summed — the order is fixed as
        round-then-sum rather than sum-then-round, and this ordering is
        observable in the recorded `RefundTransaction.amount_cents`."

        # difficulty: combinatorial_formula/tiered_refund_per_line_rounding_pinned_mode_b

        Claim: for base=5999, late=3001 at days=8 (rate=0.50),
        amount_cents == 4501 (3000+1501), NOT 4500 (sum then round).
        """
        event, _, cand, reg = setup_registration_at_clock(
            test_date_iso="2026-06-23T09:00:00.000Z",
            base_fee_cents=5999, late_fee_cents=3001,
            clock_at_creation_iso="2026-06-15T09:00:00.000Z",
            registration_deadline_iso="2026-05-25T00:00:00.000Z",
            late_registration_deadline_iso="2026-06-20T00:00:00.000Z",
        )
        self_cancel(event["id"], reg, cand)
        rows, _ = validate_paginated(
            api.list_refunds(event["id"], reg["id"],
                             TEST_USERS["registrar_headers"]),
        )
        refund = rows[0]
        assert refund["tier_label"] == "PARTIAL_50"
        assert refund["amount_cents"] == 4501

    def test_per_line_rounding_retained_complement(self, api):
        """PRD §3.4 / §3.8: "`amount_retained_cents` is recomputed as
        `amount_charged_cents` minus `amount_refunded_cents`."

        # difficulty: combinatorial_formula/tiered_refund_per_line_rounding_pinned_mode_b

        Claim: with the per-line-rounded refund of 4501, retained ==
        9000 - 4501 == 4499.
        """
        event, _, cand, reg = setup_registration_at_clock(
            test_date_iso="2026-06-23T09:00:00.000Z",
            base_fee_cents=5999, late_fee_cents=3001,
            clock_at_creation_iso="2026-06-15T09:00:00.000Z",
            registration_deadline_iso="2026-05-25T00:00:00.000Z",
            late_registration_deadline_iso="2026-06-20T00:00:00.000Z",
        )
        after = self_cancel(event["id"], reg, cand)
        assert after["amount_refunded_cents"] == 4501
        assert after["amount_retained_cents"] == 9000 - 4501
        assert_money_invariant(after)


# ===========================================================================
# RULE 3: non_linear_state_machine
# ===========================================================================
class TestRule3NonLinearStateMachine:
    """# difficulty: non_linear_state_machine"""

    # ---- Instance: accommodation_request_review_cycle ----
    def test_accommodation_review_cycle_revisits_under_review(self, api):
        """PRD §3.6: "The cycle through `SUBMITTED → UNDER_REVIEW →
        NEEDS_MORE_INFO → SUBMITTED → UNDER_REVIEW` may repeat any
        number of times until the deadline passes or the officer
        commits to an approve or deny decision."

        # difficulty: non_linear_state_machine/accommodation_request_review_cycle

        Claim: after start-review -> request-info -> resubmit ->
        start-review, the same UNDER_REVIEW state is visited on a
        later version.
        """
        event = create_test_event()
        cand = create_candidate(has_iep_or_504=True)
        req = submit_accommodation_request(
            cand, event["id"],
            docs=["https://docs.example.com/a.pdf"],
        )
        v0 = req["version"]
        ur1 = start_review(req["id"])
        assert ur1["status"] == "UNDER_REVIEW"
        nmi = request_more_info(req["id"])
        assert nmi["status"] == "NEEDS_MORE_INFO"
        s2 = resubmit_accommodation(
            req["id"], cand,
            ["https://docs.example.com/a.pdf", "https://docs.example.com/b.pdf"],
        )
        assert s2["status"] == "SUBMITTED"
        ur2 = start_review(req["id"])
        assert ur2["status"] == "UNDER_REVIEW"
        assert ur2["version"] > ur1["version"]

    def test_accommodation_review_cycle_version_monotonic(self, api):
        """PRD §2.4: "version ... begins at 1 on creation and
        increments by 1 on every mutating write".

        # difficulty: non_linear_state_machine/accommodation_request_review_cycle

        Claim: each hop in the cycle bumps version by exactly 1.
        """
        event = create_test_event()
        cand = create_candidate(has_iep_or_504=True)
        req = submit_accommodation_request(cand, event["id"])
        v0 = req["version"]
        ur1 = start_review(req["id"])
        assert ur1["version"] == v0 + 1
        nmi = request_more_info(req["id"])
        assert nmi["version"] == v0 + 2
        re_sub = resubmit_accommodation(
            req["id"], cand,
            req["supporting_documents"] + ["https://docs.example.com/x.pdf"],
        )
        assert re_sub["version"] == v0 + 3
        ur2 = start_review(req["id"])
        assert ur2["version"] == v0 + 4

    # ---- Instance: id_verification_reject_resubmit_cycle ----
    def test_id_verification_reject_then_resubmit_cycle(self, api):
        """PRD §3.5: "From `REJECTED`, the candidate may resubmit by
        calling the submit operation again, which advances the row
        back to `DOCS_SUBMITTED` (the cycle through rejection and
        resubmission is by design)."

        # difficulty: non_linear_state_machine/id_verification_reject_resubmit_cycle

        Claim: submit -> reject -> submit yields DOCS_SUBMITTED on the
        second submit (same state revisited).
        """
        event, center, _ = create_event_with_capacity()
        cand = create_candidate(home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        first = submit_id_verification(
            event["id"], reg["id"], cand,
            id_document_type="DRIVERS_LICENSE", issuing_state_code="CA",
            id_expires_on="2030-01-01",
        )
        assert first["status"] == "DOCS_SUBMITTED"
        rejected = reject_id_verification(event["id"], reg["id"], "blurry")
        assert rejected["status"] == "REJECTED"
        second = submit_id_verification(
            event["id"], reg["id"], cand,
            id_document_type="PASSPORT", issuing_state_code=None,
            id_expires_on="2031-01-01",
        )
        assert second["status"] == "DOCS_SUBMITTED"

    def test_id_verification_reject_then_resubmit_preserves_new_type(self, api):
        """PRD §3.5: "subsequent submissions after a rejection — which
        the candidate uses to correct previously failed documents —
        also land in `DOCS_SUBMITTED`."

        # difficulty: non_linear_state_machine/id_verification_reject_resubmit_cycle

        Claim: the second submit preserves the candidate's new
        id_document_type value (PASSPORT, not the original
        DRIVERS_LICENSE).
        """
        event, center, _ = create_event_with_capacity()
        cand = create_candidate(home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        submit_id_verification(
            event["id"], reg["id"], cand,
            id_document_type="DRIVERS_LICENSE", issuing_state_code="CA",
            id_expires_on="2030-01-01",
        )
        reject_id_verification(event["id"], reg["id"], "blurry")
        second = submit_id_verification(
            event["id"], reg["id"], cand,
            id_document_type="PASSPORT", issuing_state_code=None,
            id_expires_on="2031-01-01",
        )
        assert second["id_document_type"] == "PASSPORT"


# ===========================================================================
# RULE 4: transitive_cascade
# ===========================================================================
class TestRule4TransitiveCascade:
    """# difficulty: transitive_cascade"""

    # ---- Instance: admin_cancel_to_standby_promotion_depth_4 ----
    def test_admin_cancel_cascades_through_refund_capacity_promotion(self, api):
        """PRD §3.8: "If the cancelled row had been `CONFIRMED`, the
        relevant `TestCenterCapacity` has `confirmed_seats_used`
        decreased by one ... Either way, the standby promotion
        selector then fires on `(test_event_id, test_center_id)`, and
        a top-priority `STANDBY` row ... is promoted from `STANDBY` to
        `CONFIRMED`, its `confirmed_seats_used` increment lands on the
        ledger".

        # difficulty: transitive_cascade/admin_cancel_to_standby_promotion_depth_4

        Claim: a single admin-cancel call produces (1) the cancelled
        Registration in CANCELLED, (2) a RefundTransaction row, (3) a
        post-cascade confirmed_seats_used == 1, (4) the standby
        Registration in CONFIRMED.
        """
        # Set up so days_before_test = 6 (tier NONE, but channel is OFFICIAL).
        event, center, x_cand, x_reg = setup_registration_at_clock(
            test_date_iso="2026-06-08T09:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=0,
            clock_at_creation_iso="2026-06-02T09:00:00.000Z",
        )
        # Y registers (lands STANDBY because capacity = 1 was exhausted by X via setup_registration_at_clock).
        # setup_registration_at_clock uses default total_capacity=10 — we need to override.
        # Re-do with total_capacity=1.
        reset_clock_to("2026-06-02T09:00:00.000Z")
        event = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=0,
        )
        center = create_test_center()
        create_capacity(event["id"], center["id"], total_capacity=1, accommodation_capacity=0)
        x_cand = create_candidate()
        x_reg = force_confirmed_registration(event["id"], x_cand, center["id"])
        y_cand = create_candidate()
        y_res = api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=y_cand["id"], test_center_id=center["id"]),
            make_candidate_headers(y_cand["id"]),
        )
        y_reg = validate_success(y_res, 201)
        assert y_reg["status"] == "STANDBY"

        # Trigger the cascade.
        admin_cancel(event["id"], x_reg["id"])

        # (1) X is CANCELLED.
        x_after = validate_success(
            api.get_registration(event["id"], x_reg["id"],
                                 TEST_USERS["registrar_headers"]), 200,
        )
        assert x_after["status"] == "CANCELLED"
        # (2) A RefundTransaction exists.
        refunds, _ = validate_paginated(
            api.list_refunds(event["id"], x_reg["id"],
                             TEST_USERS["registrar_headers"]),
        )
        assert len(refunds) >= 1
        assert refunds[0]["registration_id"] == x_reg["id"]
        # (3 & 4) capacity restored and Y is CONFIRMED.
        caps, _ = validate_paginated(
            api.list_test_center_capacities(event["id"], TEST_USERS["registrar_headers"]),
        )
        assert caps[0]["confirmed_seats_used"] == 1
        y_after = validate_success(
            api.get_registration(event["id"], y_reg["id"],
                                 TEST_USERS["registrar_headers"]), 200,
        )
        assert y_after["status"] == "CONFIRMED"

    def test_admin_cancel_cascade_preserves_capacity_invariant(self, api):
        """PRD §2.8: "The compensating invariant — that
        `available_seats` plus `confirmed_seats_used` equals
        `total_capacity` at every observable instant — is the
        integrity contract this materialised view exists to enforce."

        # difficulty: transitive_cascade/admin_cancel_to_standby_promotion_depth_4

        Claim: after the cascade, the capacity ledger row still satisfies
        total == used + available.
        """
        reset_clock_to("2026-06-02T09:00:00.000Z")
        event = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=0,
        )
        center = create_test_center()
        create_capacity(event["id"], center["id"], total_capacity=1, accommodation_capacity=0)
        x_cand = create_candidate()
        x_reg = force_confirmed_registration(event["id"], x_cand, center["id"])
        y_cand = create_candidate()
        validate_success(api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=y_cand["id"], test_center_id=center["id"]),
            make_candidate_headers(y_cand["id"])), 201)
        admin_cancel(event["id"], x_reg["id"])
        caps, _ = validate_paginated(
            api.list_test_center_capacities(event["id"], TEST_USERS["registrar_headers"]),
        )
        assert_capacity_invariant(caps[0])

    # ---- Instance: accommodation_approval_to_demotion_depth_3 ----
    def test_accommodation_approval_demotes_confirmed_when_pool_exhausted(self, api):
        """PRD §3.6: "On every `TestCenter` for which the affected
        candidate holds a `CONFIRMED` registration, the system then
        checks whether the accommodation pool has free capacity: if
        `accommodation_capacity` minus `accommodation_seats_used`
        equals zero, the `CONFIRMED` registration is demoted back to
        `STANDBY` and the seat counters are reconciled".

        # difficulty: transitive_cascade/accommodation_approval_to_demotion_depth_3

        Claim: approving B's accommodation while the accommodation
        pool is exhausted by A demotes B's CONFIRMED registration to
        STANDBY.
        """
        event, center, _ = create_event_with_capacity(
            total_capacity=2, accommodation_capacity=1,
        )
        # Candidate A occupies the accommodation slot.
        a = create_candidate(has_iep_or_504=True)
        a_reg = force_confirmed_registration(event["id"], a, center["id"])
        submit_and_approve_accommodation(a, event["id"])

        # Candidate B is CONFIRMED in the regular pool.
        b = create_candidate(has_iep_or_504=True)
        b_reg = force_confirmed_registration(event["id"], b, center["id"])
        assert b_reg["status"] == "CONFIRMED"

        # Approve B's accommodation — pool is now exhausted, so B should be demoted.
        submit_and_approve_accommodation(b, event["id"])
        b_after = validate_success(
            api.get_registration(event["id"], b_reg["id"],
                                 TEST_USERS["registrar_headers"]), 200,
        )
        assert b_after["status"] == "STANDBY", (
            "PRD §3.6: accommodation approval with pool exhausted demotes "
            "CONFIRMED -> STANDBY"
        )
        assert b_after["accommodation_required"] is True

    def test_accommodation_approval_pins_locked_version(self, api):
        """PRD §3.6: "the approving `AccommodationRequest`'s `version`
        pinned into `locked_accommodation_request_version`."

        # difficulty: transitive_cascade/accommodation_approval_to_demotion_depth_3

        Claim: the demoted Registration has locked_accommodation_request_version
        equal to the approved AccommodationRequest's version.
        """
        event, center, _ = create_event_with_capacity(
            total_capacity=2, accommodation_capacity=1,
        )
        a = create_candidate(has_iep_or_504=True)
        force_confirmed_registration(event["id"], a, center["id"])
        submit_and_approve_accommodation(a, event["id"])

        b = create_candidate(has_iep_or_504=True)
        b_reg = force_confirmed_registration(event["id"], b, center["id"])
        approved_b = submit_and_approve_accommodation(b, event["id"])
        b_after = validate_success(
            api.get_registration(event["id"], b_reg["id"],
                                 TEST_USERS["registrar_headers"]), 200,
        )
        assert b_after["locked_accommodation_request_version"] == approved_b["version"]


# ===========================================================================
# RULE 5: priority_pair_validation_conflict
# ===========================================================================
class TestRule5PriorityPairValidationConflict:
    """# difficulty: priority_pair_validation_conflict"""

    # ---- Instance: state_vs_business_constraint_on_register ----
    def test_state_beats_duplicate_on_closed_event(self, api):
        """PRD §3.11: "current-state legality for the target resource
        (`ERR_INVALID_REGISTRATION_STATE`, ... or `ERR_REGISTRATION_CLOSED`
        at registration creation). Only after those gates have all
        passed do the cross-entity and business-specific checks apply."

        # difficulty: priority_pair_validation_conflict/state_vs_business_constraint_on_register

        Claim: when both ERR_REGISTRATION_CLOSED (state) and
        ERR_DUPLICATE_REGISTRATION (business constraint) would fire,
        the state error wins.
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        event = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        center = create_test_center()
        create_capacity(event["id"], center["id"], total_capacity=5, accommodation_capacity=0)
        cand = create_candidate()
        # Confirm a first registration.
        force_confirmed_registration(event["id"], cand, center["id"])
        # Advance clock past late_registration_deadline.
        advance_clock_to("2026-06-05T00:00:00.000Z")
        # Try to register the SAME candidate again -> both ERR_REGISTRATION_CLOSED
        # and ERR_DUPLICATE_REGISTRATION are conceptually triggered.
        res = api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=cand["id"], test_center_id=center["id"]),
            make_candidate_headers(cand["id"]),
        )
        validate_error(res, ApiErrorId.ERR_REGISTRATION_CLOSED.value)

    def test_state_beats_duplicate_status_409(self, api):
        """PRD §5 catalogue: ERR_REGISTRATION_CLOSED -> 409.

        # difficulty: priority_pair_validation_conflict/state_vs_business_constraint_on_register

        Claim: the conflict scenario in the previous test returns HTTP
        409 (not 422 from a business-constraint error).
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        event = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        center = create_test_center()
        create_capacity(event["id"], center["id"], total_capacity=5, accommodation_capacity=0)
        cand = create_candidate()
        force_confirmed_registration(event["id"], cand, center["id"])
        advance_clock_to("2026-06-05T00:00:00.000Z")
        res = api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=cand["id"], test_center_id=center["id"]),
            make_candidate_headers(cand["id"]),
        )
        # validate_error auto-checks 409 via the registered HTTP status map.
        validate_error(res, ApiErrorId.ERR_REGISTRATION_CLOSED.value)
        assert res.status_code == 409

    # ---- Instance: business_referential_vs_business_temporal_on_checkin ----
    def test_id_not_cleared_beats_check_in_window(self, api):
        """PRD §3.11: "For check-in specifically, the order after state
        is: ID-cleared (`ERR_ID_NOT_CLEARED`), then accommodation-
        pending (`ERR_ACCOMMODATION_PENDING`), then the check-in
        window check (`ERR_CHECK_IN_WINDOW_CLOSED`)."

        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_temporal_on_checkin

        Claim: when both ID-not-cleared (referential) and window-closed
        (temporal) would fire, ERR_ID_NOT_CLEARED wins.
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        event = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        center = create_test_center()
        create_capacity(event["id"], center["id"], total_capacity=5, accommodation_capacity=0)
        cand = create_candidate(home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        # Submit but DO NOT clear (status remains DOCS_SUBMITTED, not CLEARED).
        submit_id_verification(
            event["id"], reg["id"], cand,
            id_document_type="DRIVERS_LICENSE", issuing_state_code="CA",
            id_expires_on="2030-01-01",
        )
        # Advance clock to 30h before test_date (outside check-in window).
        advance_clock_to("2026-06-07T03:00:00.000Z")
        res = api.check_in_registration(
            event["id"], reg["id"], TEST_USERS["proctor_headers"],
        )
        # Both conditions hold; PRD §3.11 demands ID-cleared comes first.
        validate_error(res, ApiErrorId.ERR_ID_NOT_CLEARED.value)

    def test_id_not_cleared_status_409(self, api):
        """PRD §5 catalogue: ERR_ID_NOT_CLEARED -> 409.

        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_temporal_on_checkin

        Claim: ID-not-cleared returns HTTP 409.
        """
        event, center, _ = create_event_with_capacity()
        cand = create_candidate(home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        submit_id_verification(
            event["id"], reg["id"], cand,
            id_document_type="DRIVERS_LICENSE", issuing_state_code="CA",
            id_expires_on="2030-01-01",
        )
        # Stay outside check-in window (clock at INITIAL_CLOCK).
        res = api.check_in_registration(
            event["id"], reg["id"], TEST_USERS["proctor_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ID_NOT_CLEARED.value)
        assert res.status_code == 409


# ===========================================================================
# RULE 6: boundary_precision_check
# ===========================================================================
class TestRule6BoundaryPrecisionCheck:
    """# difficulty: boundary_precision_check"""

    # ---- Instance: refund_tier_boundary_30_days ----
    def test_refund_tier_boundary_exact_30_days_full(self, api):
        """PRD §3.8: "when `days_before_test` is at least 30 the tier
        is `FULL` with a rate of 1.00".

        # difficulty: boundary_precision_check/refund_tier_boundary_30_days

        Claim: at days_before_test == 30 (exact equality on the
        boundary) tier_label == FULL.
        """
        event, _, cand, reg = setup_registration_at_clock(
            test_date_iso="2026-06-08T09:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=0,
            clock_at_creation_iso="2026-05-09T09:00:00.000Z",
        )
        self_cancel(event["id"], reg, cand)
        rows, _ = validate_paginated(
            api.list_refunds(event["id"], reg["id"],
                             TEST_USERS["registrar_headers"]),
        )
        assert rows[0]["tier_label"] == "FULL"
        assert rows[0]["amount_cents"] == 6000

    def test_refund_tier_boundary_29_days_partial_75(self, api):
        """PRD §3.8: "when `days_before_test` is at least 15 and less
        than 30 the tier is `PARTIAL_75` with a rate of 0.75".

        # difficulty: boundary_precision_check/refund_tier_boundary_30_days

        Claim: at days_before_test == 29 (one day below boundary)
        tier_label == PARTIAL_75 and amount_cents == 4500.
        """
        event, _, cand, reg = setup_registration_at_clock(
            test_date_iso="2026-06-08T09:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=0,
            clock_at_creation_iso="2026-05-10T09:00:00.000Z",
        )
        self_cancel(event["id"], reg, cand)
        rows, _ = validate_paginated(
            api.list_refunds(event["id"], reg["id"],
                             TEST_USERS["registrar_headers"]),
        )
        assert rows[0]["tier_label"] == "PARTIAL_75"
        assert rows[0]["amount_cents"] == 4500

    # ---- Instance: super_score_empty_pool_zero_sittings ----
    def test_super_score_empty_pool_returns_null_composite(self, api):
        """PRD §3.9: "When the candidate pool after filtering is
        empty, the endpoint returns a composite value of null, an
        empty sections object, and a `sittings_used` count of zero."

        # difficulty: boundary_precision_check/super_score_empty_pool_zero_sittings

        Claim: a brand-new candidate with no registrations returns
        composite=null, sections={}, sittings_used=0.
        """
        cand = create_candidate()
        res = api.get_super_score(
            cand["id"], make_candidate_headers(cand["id"]),
            params={"test_type": "SAT"},
        )
        data = validate_success(res, 200)
        assert data["composite"] is None
        assert data["sections"] == {}
        assert data["sittings_used"] == 0

    def test_super_score_empty_pool_returns_200_not_404(self, api):
        """PRD §3.9: "When the candidate pool after filtering is
        empty, the endpoint returns a composite value of null".

        # difficulty: boundary_precision_check/super_score_empty_pool_zero_sittings

        Claim: empty pool is a normal 200 response, not a 4xx.
        """
        cand = create_candidate()
        res = api.get_super_score(
            cand["id"], make_candidate_headers(cand["id"]),
            params={"test_type": "SAT"},
        )
        assert res.status_code == 200


# ===========================================================================
# RULE 7: cross_entity_state_dependency
# ===========================================================================
class TestRule7CrossEntityStateDependency:
    """# difficulty: cross_entity_state_dependency"""

    # ---- Instance: registration_checkin_requires_idverification_cleared ----
    def test_checkin_requires_id_cleared(self, api):
        """PRD §3.7: "The associated `IDVerification` must be in
        `CLEARED`; a missing or non-cleared verification yields
        `ERR_ID_NOT_CLEARED`."

        # difficulty: cross_entity_state_dependency/registration_checkin_requires_idverification_cleared

        Claim: check-in with IDVerification REJECTED returns
        ERR_ID_NOT_CLEARED.
        """
        event, center, _ = create_event_with_capacity()
        cand = create_candidate(home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        submit_id_verification(
            event["id"], reg["id"], cand,
            id_document_type="DRIVERS_LICENSE", issuing_state_code="CA",
            id_expires_on="2030-01-01",
        )
        reject_id_verification(event["id"], reg["id"], "mismatch")
        advance_clock_to_check_in_window(event["test_date"])
        res = api.check_in_registration(
            event["id"], reg["id"], TEST_USERS["proctor_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ID_NOT_CLEARED.value)

    def test_registration_remains_confirmed_on_rejected_id(self, api):
        """PRD §3.7: "Check-in is the act by which a `Proctor` at the
        test center confirms a candidate's physical arrival, advancing
        their `Registration` from `CONFIRMED` to `CHECKED_IN`."

        # difficulty: cross_entity_state_dependency/registration_checkin_requires_idverification_cleared

        Claim: when check-in is rejected by ERR_ID_NOT_CLEARED, the
        Registration's status is still CONFIRMED (no partial
        transition).
        """
        event, center, _ = create_event_with_capacity()
        cand = create_candidate(home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        submit_id_verification(
            event["id"], reg["id"], cand,
            id_document_type="DRIVERS_LICENSE", issuing_state_code="CA",
            id_expires_on="2030-01-01",
        )
        reject_id_verification(event["id"], reg["id"], "mismatch")
        advance_clock_to_check_in_window(event["test_date"])
        api.check_in_registration(
            event["id"], reg["id"], TEST_USERS["proctor_headers"],
        )
        refreshed = validate_success(
            api.get_registration(event["id"], reg["id"],
                                 TEST_USERS["registrar_headers"]), 200,
        )
        assert refreshed["status"] == "CONFIRMED"

    # ---- Instance: registration_checkin_blocked_by_pending_accommodation ----
    def test_checkin_blocked_by_pending_accommodation(self, api):
        """PRD §3.7: "if any `AccommodationRequest` exists on the same
        `(candidate_id, test_event_id)`, that request must already be
        in one of the terminal review states ... otherwise the proctor
        receives `ERR_ACCOMMODATION_PENDING`."

        # difficulty: cross_entity_state_dependency/registration_checkin_blocked_by_pending_accommodation

        Claim: with ID CLEARED and an accommodation request still in
        SUBMITTED, check-in returns ERR_ACCOMMODATION_PENDING.
        """
        event, center, _ = create_event_with_capacity()
        cand = create_candidate(has_iep_or_504=True, home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        submit_and_clear_id(event["id"], reg["id"], cand)
        submit_accommodation_request(cand, event["id"])
        advance_clock_to_check_in_window(event["test_date"])
        res = api.check_in_registration(
            event["id"], reg["id"], TEST_USERS["proctor_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ACCOMMODATION_PENDING.value)

    def test_checkin_passes_when_accommodation_denied(self, api):
        """PRD §3.7: "that request must already be in one of the
        terminal review states — `APPROVED`, `DENIED`, or `EXPIRED`".

        # difficulty: cross_entity_state_dependency/registration_checkin_blocked_by_pending_accommodation

        Claim: with the accommodation request transitioned to DENIED,
        check-in succeeds (terminal review state).
        """
        event, center, _ = create_event_with_capacity()
        cand = create_candidate(has_iep_or_504=True, home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        submit_and_clear_id(event["id"], reg["id"], cand)
        req = submit_accommodation_request(cand, event["id"])
        start_review(req["id"])
        deny_accommodation(req["id"])
        advance_clock_to_check_in_window(event["test_date"])
        res = api.check_in_registration(
            event["id"], reg["id"], TEST_USERS["proctor_headers"],
        )
        data = validate_success(res, 200)
        assert data["status"] == "CHECKED_IN"


# ===========================================================================
# RULE 8: resource_temporal_overlap
# ===========================================================================
class TestRule8ResourceTemporalOverlap:
    """# difficulty: resource_temporal_overlap"""

    # ---- Instance: test_center_event_overlap_no_buffer ----
    def test_test_center_time_conflict_closed_interval(self, api):
        """PRD §3.2: "A `TestCenter` cannot host two different
        `TestEvent`s whose scheduled sessions overlap in the same
        four-hour test-session window. When a `Registrar` allocates
        capacity, the system checks whether the candidate `TestEvent`'s
        window from `test_date` through `test_date + 4 hours` (closed
        interval, no buffer) overlaps any other event's window already
        bound to the same `TestCenter`; if it does, the allocation is
        rejected with `ERR_TEST_CENTER_TIME_CONFLICT`."

        # difficulty: resource_temporal_overlap/test_center_event_overlap_no_buffer

        Claim: a second capacity at the same center for an event whose
        window touches the first's window is rejected.
        """
        center = create_test_center()
        e1 = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        create_capacity(e1["id"], center["id"], total_capacity=10, accommodation_capacity=2)
        e2 = create_test_event(
            test_date="2026-06-08T12:00:00.000Z",  # overlap with [09:00, 13:00]
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        from test_helpers import create_capacity_payload
        res = api.create_test_center_capacity(
            e2["id"],
            create_capacity_payload(test_center_id=center["id"],
                                    total_capacity=5, accommodation_capacity=0),
            TEST_USERS["registrar_headers"],
        )
        validate_error(res, ApiErrorId.ERR_TEST_CENTER_TIME_CONFLICT.value)

    def test_test_center_overlap_not_created_after_rejection(self, api):
        """PRD §3.2: rejection means the allocation does not commit.

        # difficulty: resource_temporal_overlap/test_center_event_overlap_no_buffer

        Claim: after the rejected allocation, listing capacities for
        the second event returns zero rows.
        """
        center = create_test_center()
        e1 = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        create_capacity(e1["id"], center["id"], total_capacity=10, accommodation_capacity=0)
        e2 = create_test_event(
            test_date="2026-06-08T12:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        from test_helpers import create_capacity_payload
        api.create_test_center_capacity(
            e2["id"],
            create_capacity_payload(test_center_id=center["id"],
                                    total_capacity=5, accommodation_capacity=0),
            TEST_USERS["registrar_headers"],
        )
        rows, _ = validate_paginated(
            api.list_test_center_capacities(e2["id"], TEST_USERS["registrar_headers"]),
        )
        assert all(r["test_center_id"] != center["id"] for r in rows)

    # ---- Instance: candidate_session_overlap_with_cooldown_buffer ----
    def test_candidate_session_overlap_with_buffer(self, api):
        """PRD §3.4: "a candidate cannot register for two events whose
        test windows overlap when extended by a four-hour cooldown
        buffer on either side: the system computes the closed interval
        from `test_date - 4 hours` through `test_date + 4 hours + 4
        hours` ... and rejects the new one with
        `ERR_CANDIDATE_SESSION_OVERLAP` if it falls within any such
        interval."

        # difficulty: resource_temporal_overlap/candidate_session_overlap_with_cooldown_buffer

        Claim: even with the raw windows non-overlapping, the buffered
        windows overlap and the second registration is rejected.
        """
        e1 = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        c1 = create_test_center()
        create_capacity(e1["id"], c1["id"], total_capacity=5, accommodation_capacity=0)
        # Buffered window of e1: 05:00–17:00. e2 at 16:00 -> buffered 12:00–24:00.
        e2 = create_test_event(
            test_date="2026-06-08T16:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        c2 = create_test_center()
        create_capacity(e2["id"], c2["id"], total_capacity=5, accommodation_capacity=0)
        cand = create_candidate()
        force_confirmed_registration(e1["id"], cand, c1["id"])
        res = api.create_registration(
            e2["id"],
            create_registration_payload(candidate_id=cand["id"], test_center_id=c2["id"]),
            make_candidate_headers(cand["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CANDIDATE_SESSION_OVERLAP.value)

    def test_candidate_session_overlap_no_second_row_created(self, api):
        """PRD §3.4: rejection prevents the second row from being created.

        # difficulty: resource_temporal_overlap/candidate_session_overlap_with_cooldown_buffer

        Claim: after the rejected create, no Registration exists for
        the candidate on the second event.
        """
        e1 = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        c1 = create_test_center()
        create_capacity(e1["id"], c1["id"], total_capacity=5, accommodation_capacity=0)
        e2 = create_test_event(
            test_date="2026-06-08T16:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        c2 = create_test_center()
        create_capacity(e2["id"], c2["id"], total_capacity=5, accommodation_capacity=0)
        cand = create_candidate()
        force_confirmed_registration(e1["id"], cand, c1["id"])
        api.create_registration(
            e2["id"],
            create_registration_payload(candidate_id=cand["id"], test_center_id=c2["id"]),
            make_candidate_headers(cand["id"]),
        )
        rows, _ = validate_paginated(
            api.list_registrations(e2["id"], TEST_USERS["registrar_headers"]),
        )
        cand_rows = [r for r in rows if r["candidate_id"] == cand["id"]]
        assert cand_rows == []


# ===========================================================================
# RULE 9: compensating_invariant
# ===========================================================================
class TestRule9CompensatingInvariant:
    """# difficulty: compensating_invariant"""

    # ---- Instance: money_conservation_under_cancel_refund ----
    def test_money_conservation_holds_through_partial_refund(self, api):
        """PRD §3.4 / §3.8: "`amount_retained_cents` is recomputed as
        `amount_charged_cents` minus `amount_refunded_cents`."

        # difficulty: compensating_invariant/money_conservation_under_cancel_refund

        Claim: charged == refunded + retained both before and after a
        PARTIAL_50 cancellation.
        """
        event, _, cand, reg = setup_registration_at_clock(
            test_date_iso="2026-06-23T09:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=2000,
            clock_at_creation_iso="2026-06-15T09:00:00.000Z",
            registration_deadline_iso="2026-05-25T00:00:00.000Z",
            late_registration_deadline_iso="2026-06-20T00:00:00.000Z",
        )
        assert reg["amount_charged_cents"] == 8000
        assert_money_invariant(reg)
        after = self_cancel(event["id"], reg, cand)
        assert after["amount_refunded_cents"] == 4000
        assert after["amount_retained_cents"] == 4000
        assert_money_invariant(after)

    def test_money_invariant_with_official_cancellation_after_full_refund(self, api):
        """PRD §3.8: "`amount_refunded_cents` is set to the sum of all
        its `RefundTransaction.amount_cents` (in practice one row per
        cancellation), and `amount_retained_cents` is recomputed as
        `amount_charged_cents` minus `amount_refunded_cents`."

        # difficulty: compensating_invariant/money_conservation_under_cancel_refund

        Claim: an official cancellation refunds base+late only,
        leaving accommodation_fee in retained -> charged == refunded
        + retained.
        """
        # build with accommodation fee.
        event, center, _ = create_event_with_capacity(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
            total_capacity=5, accommodation_capacity=2,
        )
        reset_clock_to("2026-05-01T00:00:00.000Z")
        cand = create_candidate(has_iep_or_504=True, home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        submit_and_approve_accommodation(cand, event["id"])
        refreshed = validate_success(
            api.get_registration(event["id"], reg["id"],
                                 TEST_USERS["registrar_headers"]), 200,
        )
        amount_charged = refreshed["amount_charged_cents"]
        # Official cancel -> rate forced 1.00 on base+late, accommodation retained.
        after = admin_cancel(event["id"], reg["id"])
        expected_refund = refreshed["base_fee_cents_charged"] + refreshed["late_fee_cents_charged"]
        assert after["amount_refunded_cents"] == expected_refund
        assert after["amount_retained_cents"] == amount_charged - expected_refund
        assert_money_invariant(after)

    # ---- Instance: seat_conservation_through_cancellation_and_promotion ----
    def test_seat_conservation_after_cancel_and_promote(self, api):
        """PRD §2.8: "The compensating invariant — that
        `available_seats` plus `confirmed_seats_used` equals
        `total_capacity` at every observable instant".

        # difficulty: compensating_invariant/seat_conservation_through_cancellation_and_promotion

        Claim: after one cancellation balanced by one promotion the
        ledger reports total==used+available with used==1, available==0.
        """
        reset_clock_to("2026-06-02T09:00:00.000Z")
        event = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=0,
        )
        center = create_test_center()
        create_capacity(event["id"], center["id"], total_capacity=1, accommodation_capacity=0)
        x_cand = create_candidate()
        x_reg = force_confirmed_registration(event["id"], x_cand, center["id"])
        y_cand = create_candidate()
        validate_success(api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=y_cand["id"], test_center_id=center["id"]),
            make_candidate_headers(y_cand["id"])), 201)
        admin_cancel(event["id"], x_reg["id"])
        caps, _ = validate_paginated(
            api.list_test_center_capacities(event["id"], TEST_USERS["registrar_headers"]),
        )
        cap = caps[0]
        assert cap["confirmed_seats_used"] == 1
        assert cap["available_seats"] == 0
        assert cap["standby_seats_pending"] == 0
        assert_capacity_invariant(cap)

    def test_seat_invariant_holds_before_cancellation_too(self, api):
        """PRD §2.8: invariant holds "at every observable instant".

        # difficulty: compensating_invariant/seat_conservation_through_cancellation_and_promotion

        Claim: pre-cascade state (one confirmed, one standby) satisfies
        total_capacity == confirmed_seats_used + available_seats.
        """
        event, center, _ = create_event_with_capacity(
            total_capacity=1, accommodation_capacity=0,
        )
        x_cand = create_candidate()
        force_confirmed_registration(event["id"], x_cand, center["id"])
        y_cand = create_candidate()
        validate_success(api.create_registration(
            event["id"],
            create_registration_payload(candidate_id=y_cand["id"], test_center_id=center["id"]),
            make_candidate_headers(y_cand["id"])), 201)
        caps, _ = validate_paginated(
            api.list_test_center_capacities(event["id"], TEST_USERS["registrar_headers"]),
        )
        cap = caps[0]
        assert cap["confirmed_seats_used"] == 1
        assert cap["available_seats"] == 0
        assert cap["standby_seats_pending"] == 1
        assert_capacity_invariant(cap)

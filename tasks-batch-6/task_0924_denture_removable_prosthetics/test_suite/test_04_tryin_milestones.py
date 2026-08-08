"""Try-in milestones: the type-parameterised sequence, the adjust/resubmit cycle
on a single row, and the rejection leg that opens a remake."""

from test_helpers import (
    ApiErrorId,
    CLINICAL_DIRECTOR_USER_ID,
    PROSTHODONTIST_USER_ID,
    assert_same_instant,
    assert_try_in_milestone,
    create_try_in_payload,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def _arch_in_milestone_pending(name, dob, phone, prosthesis_type="FLEXIBLE_PARTIAL"):
    """An arch driven to MILESTONE_PENDING through an accepted impression."""
    ctx = fx.setup_case_past_exam(
        prosthesis_type=prosthesis_type,
        patient_overrides={"full_name": name, "date_of_birth": dob, "phone": phone},
    )
    fx.start_fabrication(ctx["arch"]["id"])
    fx.accepted_impression(ctx["arch"]["id"], "DIGITAL_SCAN", 92)
    return ctx


class TestAdjustResubmitCycle:
    def test_adjust_count_accumulates_across_two_passes_of_the_same_row(self, api, prosthodontist_headers):
        """PRD §3.4: "**Adjustment.** Permitted from `PENDING_APPROVAL`, and only
        while the row's `adjust_count` is **strictly below 2**; a third adjustment on
        the same row is refused with `ERR_TRYIN_LIMIT_EXCEEDED`. It moves the row
        `PENDING_APPROVAL → ADJUST_REQUESTED`, increases `adjust_count` by one, and
        leaves the parent arch untouched in `MILESTONE_PENDING`."
        PRD §3.4: "**Resubmission.** Permitted from `ADJUST_REQUESTED` only, and it
        moves the row back `ADJUST_REQUESTED → PENDING_APPROVAL`, closing the
        adjust-and-re-try-in cycle on the same row. `adjust_count` is deliberately
        **not** reset, so the ceiling of two is cumulative across the life of the row:
        adjust, resubmit, adjust, resubmit leaves the row at two adjustments and a
        third adjustment is refused."

        Design: Difficulty/non_linear_state_machine/tryin_adjust_resubmit_cycle_on_the_same_row
        """
        ctx = _arch_in_milestone_pending("Gwilym Nakato", "1947-01-11", "555-0277")
        try_in = fx.book_try_in(ctx["arch"]["id"], "WAX")
        assert try_in["adjust_count"] == 0

        first_adjust = validate_success(
            api.decide_try_in(try_in["id"], {"decision": "ADJUST"}, prosthodontist_headers), 200
        )
        assert first_adjust["approval_status"] == "ADJUST_REQUESTED"
        assert first_adjust["adjust_count"] == 1
        assert fx.read_arch(ctx["arch"]["id"])["arch_status"] == "MILESTONE_PENDING"

        first_resubmit = fx.decide_try_in(try_in["id"], "RESUBMIT")
        assert first_resubmit["approval_status"] == "PENDING_APPROVAL"
        assert first_resubmit["adjust_count"] == 1, "resubmission does not reset the counter"

        second_adjust = fx.decide_try_in(try_in["id"], "ADJUST")
        assert second_adjust["approval_status"] == "ADJUST_REQUESTED"
        assert second_adjust["adjust_count"] == 2

        second_resubmit = fx.decide_try_in(try_in["id"], "RESUBMIT")
        assert second_resubmit["approval_status"] == "PENDING_APPROVAL"
        assert second_resubmit["adjust_count"] == 2

    def test_approval_after_the_cycle_sends_the_arch_to_lab_fabrication(self, api, prosthodontist_headers):
        """PRD §3.4: "Approval moves the row to `APPROVED`, appends its
        `milestone_kind` to the arch's `completed_milestones`, and recomputes
        `next_required_milestone`. When that recomputation yields null — meaning the
        last required milestone has just been approved — the arch advances
        `MILESTONE_PENDING → LAB_FABRICATION` and its `version` increments by 1."
        PRD §3.4: "Every one of the four stamps `decided_at` with the logical clock,
        records the calling `X-User-ID` in `decided_by_user_id`, and increments the
        milestone's `version` by 1."

        Design: Difficulty/non_linear_state_machine/tryin_adjust_resubmit_cycle_on_the_same_row
        """
        ctx = _arch_in_milestone_pending("Gwilym Nakato", "1947-01-11", "555-0277")
        try_in = fx.book_try_in(ctx["arch"]["id"], "WAX")
        for decision in ("ADJUST", "RESUBMIT", "ADJUST", "RESUBMIT"):
            fx.decide_try_in(try_in["id"], decision)

        approved = validate_success(
            api.decide_try_in(try_in["id"], {"decision": "APPROVE"}, prosthodontist_headers), 200
        )

        assert_try_in_milestone(approved)
        assert approved["approval_status"] == "APPROVED"
        assert approved["adjust_count"] == 2
        assert approved["decided_by_user_id"] == PROSTHODONTIST_USER_ID
        assert_same_instant(
            approved["decided_at"], "2026-05-01T00:00:00.000Z", "TryInMilestone.decided_at"
        )

        arch = fx.read_arch(ctx["arch"]["id"])
        assert arch["arch_status"] == "LAB_FABRICATION"
        assert arch["completed_milestones"] == ["WAX"]
        assert arch["next_required_milestone"] is None

    def test_third_adjust_on_the_same_row_is_refused_by_the_ceiling(self, api, prosthodontist_headers):
        """PRD §3.4: "**Adjustment.** Permitted from `PENDING_APPROVAL`, and only
        while the row's `adjust_count` is **strictly below 2**; a third adjustment on
        the same row is refused with `ERR_TRYIN_LIMIT_EXCEEDED`."
        PRD §2.10: "**Rung 18 — try-in adjust ceiling.** The milestone's
        `adjust_count` is strictly below 2 when the decision is an adjustment.
        Failure: `ERR_TRYIN_LIMIT_EXCEEDED`, HTTP 409."

        Design: Corner/state_machines/tryin_adjust_ceiling_blocks_the_third_adjust
        """
        ctx = _arch_in_milestone_pending("Marit Chukwu", "1952-02-14", "555-1011")
        try_in = fx.book_try_in(ctx["arch"]["id"], "WAX")
        for decision in ("ADJUST", "RESUBMIT", "ADJUST", "RESUBMIT"):
            fx.decide_try_in(try_in["id"], decision)

        response = api.decide_try_in(try_in["id"], {"decision": "ADJUST"}, prosthodontist_headers)
        validate_error(response, ApiErrorId.ERR_TRYIN_LIMIT_EXCEEDED.value, 409)

        after = fx.read_try_in(try_in["id"])
        assert after["approval_status"] == "PENDING_APPROVAL"
        assert after["adjust_count"] == 2


class TestRejectionAndSequencing:
    def test_reject_mints_a_tryin_rejected_remake_request_that_moves_the_arch_on_approval(self, api, prosthodontist_headers):
        """PRD §3.4: "**Rejection.** Permitted from `PENDING_APPROVAL`, and only
        while the parent arch is in `MILESTONE_PENDING`. It moves the row to
        `REJECTED_FOR_REMAKE` and, as a side effect, auto-creates a remake request on
        the parent arch in `PENDING_APPROVAL` with `reason_code` of `TRYIN_REJECTED`,
        `requested_by_user_id` set to the deciding `X-User-ID`, and
        `warranty_claim_id` null."
        PRD §3.7: "**Link 2**, caused by link 1, moves the parent arch to
        `REMAKE_PENDING` — from `DELIVERED` when the appliance was already handed
        over, or from `MILESTONE_PENDING` when a try-in was rejected before any
        delivery ever happened — increases the arch's `remake_count` by one, and
        increments the arch's `version` by 1."

        Design: Corner/state_machines/tryin_reject_mints_a_remake_request_and_sends_the_arch_to_remake_pending
        """
        ctx = _arch_in_milestone_pending("Nadia Prasad", "1949-03-15", "555-1012")
        try_in = fx.book_try_in(ctx["arch"]["id"], "WAX")

        rejected = validate_success(
            api.decide_try_in(try_in["id"], {"decision": "REJECT"}, prosthodontist_headers), 200
        )
        assert rejected["approval_status"] == "REJECTED_FOR_REMAKE"

        requests = fx.remake_requests_of(ctx["arch"]["id"])
        assert len(requests) == 1
        remake = requests[0]
        assert remake["reason_code"] == "TRYIN_REJECTED"
        assert remake["requested_by_user_id"] == PROSTHODONTIST_USER_ID
        assert remake["authorization_status"] == "PENDING_APPROVAL"
        assert remake["warranty_claim_id"] is None
        assert remake["attempt_number"] == 1
        assert remake["charge_basis"] == "CHARGEABLE"

        assert fx.read_arch(ctx["arch"]["id"])["arch_status"] == "MILESTONE_PENDING", (
            "the arch only moves once the request is approved"
        )

        fx.approve_remake(remake["id"], director_user_id=CLINICAL_DIRECTOR_USER_ID)
        arch = fx.read_arch(ctx["arch"]["id"])
        assert arch["arch_status"] == "REMAKE_PENDING"
        assert arch["remake_count"] == 1

    def test_booking_a_finish_tryin_before_the_wax_tryin_is_out_of_sequence(self, api, prosthodontist_headers):
        """PRD §3.4: "The arch must be in `MILESTONE_PENDING`, or the booking is
        refused with `ERR_CROSS_ENTITY_STATE`; and the `milestone_kind` must equal
        the arch's `next_required_milestone`, or the booking is refused with
        `ERR_MILESTONE_SEQUENCE`."
        PRD §3.2: "- A `COMPLETE_DENTURE` requires a wax try-in and then a finish
        try-in, in that order."
        PRD §3.8: "Both paying answers stamp `determined_at` with the logical clock
        and compute `expires_at` as `determined_at` plus 180 calendar days."

        Design: Corner/validations/milestone_sequence_rejects_a_finish_tryin_booked_before_the_wax_tryin
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        patient = fx.register_patient(
            full_name="Dita Ferrara", date_of_birth="1942-07-31", phone="555-1028"
        )
        coverage = fx.enrol_coverage(
            patient["id"],
            carrier_name="Meridian Dental",
            rank="PRIMARY",
            effective_date="2024-01-01T00:00:00Z",
            annual_maximum_amount=1500.00,
            coinsurance_major_rate=0.50,
        )
        case = fx.open_case(patient["id"], "COMPLETE_DENTURE")
        arch = fx.add_arch(case["id"], "MAXILLARY")
        fx.complete_exam(case["id"])
        predetermination = fx.approved_predetermination(case["id"], coverage["id"])
        fx.start_fabrication(arch["id"])
        fx.accepted_impression(arch["id"], "PHYSICAL_IMPRESSION", 90)

        arch_now = fx.read_arch(arch["id"])
        assert arch_now["required_milestones"] == ["WAX", "FINISH"]
        assert arch_now["next_required_milestone"] == "WAX"

        response = api.create_try_in(
            create_try_in_payload(arch["id"], "FINISH"), prosthodontist_headers
        )
        validate_error(response, ApiErrorId.ERR_MILESTONE_SEQUENCE.value, 422)

        _, meta = validate_paginated(
            api.list_try_ins(
                prosthodontist_headers,
                params={"case_arch_id": arch["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0, "no TryInMilestone is minted by the refused booking"

        assert_same_instant(
            predetermination["expires_at"],
            "2026-10-28T00:00:00.000Z",
            "Predetermination.expires_at",
        )

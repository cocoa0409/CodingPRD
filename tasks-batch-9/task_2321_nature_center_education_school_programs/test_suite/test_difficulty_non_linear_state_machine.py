"""Depth tests for the non-linear state progressions of the Nature Center Education API.

Three progressions are exercised here: a booking whose two status dimensions move
independently, a training record that re-enters ``ENROLLED`` after failing, and a
program offering that is pushed backwards out of review and then sent in again.
"""

import pytest

from test_helpers import (
    BC,
    CS,
    CS_ASSESSOR,
    ED,
    GO,
    ApiErrorId,
    apply_for_aid,
    create_fund,
    create_offering_under_review,
    create_onboarding_educator,
    enroll_training,
    find_material,
    find_training_record,
    refresh_aid_application,
    refresh_booking,
    refresh_educator,
    refresh_offering,
    set_clock,
    setup_confirmed_booking,
    validate_error,
    validate_success,
)

# ======================================================================
# Local composite setups
# ======================================================================


def _setup_confirmed_booking_with_submitted_aid(
    requested_scholarship_cents: int = 33300,
    requested_transport_cents: int = 6500,
    **kwargs,
) -> dict:
    """A booking already CONFIRMED whose school has then applied for aid, so the
    delivery dimension sits at CONFIRMED while the money dimension sits at AID_PENDING.
    """
    scenario = setup_confirmed_booking(**kwargs)
    fund = create_fund()
    aid = apply_for_aid(
        scenario["booking"]["id"],
        fund["id"],
        requested_scholarship_cents,
        requested_transport_cents,
    )
    scenario["fund"] = fund
    scenario["aid_application"] = aid
    scenario["booking"] = refresh_booking(scenario["booking"]["id"])
    return scenario


def _setup_enrolled_curriculum_record() -> dict:
    """An ONBOARDING educator holding one ENROLLED CURRICULUM record for G3_5."""
    set_clock()
    educator = create_onboarding_educator()
    record = enroll_training(educator["id"], track="CURRICULUM", grade_band="G3_5")
    return {"educator": educator, "training_record": record}


def _setup_offering_under_review() -> dict:
    """An offering at UNDER_REVIEW with two standards claims and both packets PUBLISHED."""
    set_clock()
    return create_offering_under_review()


# ======================================================================
# A booking's two dimensions
# ======================================================================


class TestBookingParallelDimensions:
    def test_funding_walks_to_aid_approved_while_delivery_stays_confirmed(self, api):
        """PRD §2.12: "A booking may sit at `CONFIRMED` while its funding walks `UNFUNDED` to `AID_PENDING` to `AID_APPROVED`, and no funding transition ever changes `delivery_status`."

        Design: Difficulty/non_linear_state_machine/booking_parallel_dimensions_delivery_and_funding_evolve_independently
        """
        scenario = _setup_confirmed_booking_with_submitted_aid()
        booking = scenario["booking"]
        assert booking["delivery_status"] == "CONFIRMED"
        assert booking["funding_status"] == "AID_PENDING"

        validate_success(
            api.review_aid_application(
                scenario["aid_application"]["id"], {"decision": "APPROVE"}, GO
            )
        )

        booking = refresh_booking(booking["id"])
        assert booking["delivery_status"] == "CONFIRMED"
        assert booking["funding_status"] == "AID_APPROVED"

    def test_delivery_drives_funding_to_invoiced_and_disburses_the_award(self, api):
        """PRD §3.7: "Both branches then compute `final_gross_fee_cents` through the final variant of the fee assessment, recompute `net_due_cents` from it, advance `funding_status` to `INVOICED`, transition every aid application of this booking whose status is `APPROVED` or `PARTIALLY_APPROVED` to `DISBURSED`, and recompute the school's `outstanding_balance_cents`."

        Design: Difficulty/non_linear_state_machine/booking_parallel_dimensions_delivery_and_funding_evolve_independently
        """
        scenario = _setup_confirmed_booking_with_submitted_aid()
        validate_success(
            api.review_aid_application(
                scenario["aid_application"]["id"], {"decision": "APPROVE"}, GO
            )
        )

        delivered = validate_success(
            api.deliver_booking(
                scenario["booking"]["id"],
                {"actual_student_count": 30, "actual_chaperone_count": 3},
                BC,
            )
        )

        assert delivered["delivery_status"] == "DELIVERED"
        assert delivered["funding_status"] == "INVOICED"

        aid = refresh_aid_application(scenario["aid_application"]["id"])
        assert aid["status"] == "DISBURSED"

    def test_delivered_booking_prices_the_final_fee_net_of_the_scholarship_credit(self, api):
        """PRD §3.8: "Accordingly, `net_due_cents` is the `final_gross_fee_cents` less `aid_amount_cents` once the booking has been delivered and the `provisional_gross_fee_cents` less `aid_amount_cents` before that, in either case with a lower bound of zero."

        Design: Difficulty/non_linear_state_machine/booking_parallel_dimensions_delivery_and_funding_evolve_independently
        """
        scenario = _setup_confirmed_booking_with_submitted_aid()
        validate_success(
            api.review_aid_application(
                scenario["aid_application"]["id"], {"decision": "APPROVE"}, GO
            )
        )
        validate_success(
            api.deliver_booking(
                scenario["booking"]["id"],
                {"actual_student_count": 30, "actual_chaperone_count": 3},
                BC,
            )
        )

        booking = refresh_booking(scenario["booking"]["id"])
        assert booking["final_gross_fee_cents"] == 33300
        assert booking["net_due_cents"] == 4500
        assert (
            booking["net_due_cents"]
            == booking["final_gross_fee_cents"] - booking["aid_amount_cents"]
        )


# ======================================================================
# A training record that fails, re-enrols and then passes
# ======================================================================


class TestTrainingRecordFailReenrollCycle:
    def test_reenrollment_returns_a_failed_record_to_enrolled_with_no_score(self, api):
        """PRD §3.3: "The `EducationDirector` may return `ASSESSED_FAIL → ENROLLED`, which clears the recorded `score`, provided `attempt_count` is still strictly below 3; a fourth attempt is refused with `ERR_TRAINING_ATTEMPTS_EXHAUSTED`."

        Design: Difficulty/non_linear_state_machine/training_record_fail_reenroll_cycle
        """
        scenario = _setup_enrolled_curriculum_record()
        record_id = scenario["training_record"]["id"]

        failed = validate_success(
            api.assess_training_record(record_id, {"outcome": "FAIL"}, CS_ASSESSOR)
        )
        assert failed["status"] == "ASSESSED_FAIL"
        assert failed["attempt_count"] == 1

        reenrolled = validate_success(api.reenroll_training_record(record_id, ED))
        assert reenrolled["status"] == "ENROLLED"
        assert reenrolled["score"] is None

    def test_second_assessment_passes_and_recertifies_the_grade_band(self, api):
        """PRD §3.3: "`ENROLLED → ASSESSED_PASS` stamps `passed_at` with the logical clock, sets `expires_on` to that instant plus a validity window of one year — 365 days — and re-derives the educator's aggregate credentials: `curriculum_certified_grade_bands` is refreshed to the set of grade bands for which the educator holds a `CURRICULUM` record in `ASSESSED_PASS` when the track was curriculum, and `animal_handling_tier` is refreshed to the highest `handling_tier` across the educator's passing `LIVE_ANIMAL_HANDLING` records — `NONE` when there are none — when the track was handling."

        Design: Difficulty/non_linear_state_machine/training_record_fail_reenroll_cycle
        """
        scenario = _setup_enrolled_curriculum_record()
        record_id = scenario["training_record"]["id"]
        educator_id = scenario["educator"]["id"]

        validate_success(
            api.assess_training_record(record_id, {"outcome": "FAIL"}, CS_ASSESSOR)
        )
        validate_success(api.reenroll_training_record(record_id, ED))
        passed = validate_success(
            api.assess_training_record(
                record_id, {"outcome": "PASS", "score": 91}, CS_ASSESSOR
            )
        )

        assert passed["status"] == "ASSESSED_PASS"
        assert passed["score"] == 91
        assert passed["passed_at"] == "2026-09-28T07:00:00.000Z"
        assert passed["expires_on"] == "2027-09-28T07:00:00.000Z"
        assert refresh_educator(educator_id)["curriculum_certified_grade_bands"] == ["G3_5"]

    def test_attempt_count_accumulates_across_the_fail_and_pass_cycle(self, api):
        """PRD §3.3: "Both outcomes increment `attempt_count` by 1 and stamp `assessed_by_user_id` with the deciding `X-User-ID`."

        Design: Difficulty/non_linear_state_machine/training_record_fail_reenroll_cycle
        """
        scenario = _setup_enrolled_curriculum_record()
        record_id = scenario["training_record"]["id"]
        educator_id = scenario["educator"]["id"]

        validate_success(
            api.assess_training_record(record_id, {"outcome": "FAIL"}, CS_ASSESSOR)
        )
        validate_success(api.reenroll_training_record(record_id, ED))
        validate_success(
            api.assess_training_record(
                record_id, {"outcome": "PASS", "score": 91}, CS_ASSESSOR
            )
        )

        record = find_training_record(educator_id, record_id)
        assert record["status"] == "ASSESSED_PASS"
        assert record["attempt_count"] == 2


# ======================================================================
# The catalog revision loop
# ======================================================================


class TestOfferingRevisionRequestCycle:
    def test_request_revision_moves_the_offering_back_and_clears_materials_ready(self, api):
        """PRD §3.1: "The `REQUEST_REVISION` branch moves the offering `UNDER_REVIEW → REVISION_REQUESTED`, increments `revision_round` by 1, records `reviewed_by_user_id`, and reverts **every** curriculum material of that offering currently in `PUBLISHED` back to `DRAFT` — which in turn recomputes `materials_ready` to false as soon as any material reverts."

        Design: Difficulty/non_linear_state_machine/offering_revision_request_cycle_reverts_published_materials
        """
        bundle = _setup_offering_under_review()
        assert bundle["offering"]["materials_ready"] is True
        assert bundle["offering"]["revision_round"] == 0

        returned = validate_success(
            api.review_program_offering(
                bundle["offering"]["id"],
                {
                    "decision": "REQUEST_REVISION",
                    "reviewer_note": "Add a watershed vocabulary sheet",
                },
                ED,
            )
        )

        assert returned["status"] == "REVISION_REQUESTED"
        assert returned["materials_ready"] is False
        assert returned["revision_round"] == 1

    @pytest.mark.parametrize("material_key", ["pre_visit_material", "post_visit_material"])
    def test_request_revision_reverts_each_published_packet_to_draft(self, api, material_key):
        """PRD §3.1: "The `REQUEST_REVISION` branch moves the offering `UNDER_REVIEW → REVISION_REQUESTED`, increments `revision_round` by 1, records `reviewed_by_user_id`, and reverts **every** curriculum material of that offering currently in `PUBLISHED` back to `DRAFT` — which in turn recomputes `materials_ready` to false as soon as any material reverts."

        Design: Difficulty/non_linear_state_machine/offering_revision_request_cycle_reverts_published_materials
        """
        bundle = _setup_offering_under_review()
        offering_id = bundle["offering"]["id"]
        material_id = bundle[material_key]["id"]
        assert find_material(offering_id, material_id)["status"] == "PUBLISHED"

        validate_success(
            api.review_program_offering(
                offering_id,
                {
                    "decision": "REQUEST_REVISION",
                    "reviewer_note": "Add a watershed vocabulary sheet",
                },
                ED,
            )
        )

        assert find_material(offering_id, material_id)["status"] == "DRAFT"

    def test_resubmission_reenters_under_review_with_the_revision_round_kept(self, api):
        """PRD §3.1: "Sending an offering into review advances `DRAFT` to `UNDER_REVIEW`, or `REVISION_REQUESTED` to `UNDER_REVIEW` — the revision loop `REVISION_REQUESTED → UNDER_REVIEW → REVISION_REQUESTED` is a supported cycle, not an error path."

        Design: Difficulty/non_linear_state_machine/offering_revision_request_cycle_reverts_published_materials
        """
        bundle = _setup_offering_under_review()
        offering_id = bundle["offering"]["id"]
        validate_success(
            api.review_program_offering(
                offering_id,
                {
                    "decision": "REQUEST_REVISION",
                    "reviewer_note": "Add a watershed vocabulary sheet",
                },
                ED,
            )
        )

        resubmitted = validate_success(api.submit_offering_for_review(offering_id, CS))

        assert resubmitted["status"] == "UNDER_REVIEW"
        assert resubmitted["revision_round"] == 1
        assert resubmitted["materials_ready"] is False
        assert refresh_offering(offering_id)["status"] == "UNDER_REVIEW"

    def test_publishing_after_the_cycle_is_blocked_until_the_packets_are_republished(self, api):
        """PRD §3.1: "The `PUBLISH` branch carries three further requirements: `standard_alignment_count` must be at least 2 (a single claim is enough to enter review but not to ship, and a shortfall is again `ERR_INSUFFICIENT_STANDARD_ALIGNMENT`), and `materials_ready` must be true or the decision is rejected with `ERR_MATERIALS_NOT_READY`."

        Design: Difficulty/non_linear_state_machine/offering_revision_request_cycle_reverts_published_materials
        """
        bundle = _setup_offering_under_review()
        offering_id = bundle["offering"]["id"]
        validate_success(
            api.review_program_offering(
                offering_id,
                {
                    "decision": "REQUEST_REVISION",
                    "reviewer_note": "Add a watershed vocabulary sheet",
                },
                ED,
            )
        )
        validate_success(api.submit_offering_for_review(offering_id, CS))

        validate_error(
            api.review_program_offering(offering_id, {"decision": "PUBLISH"}, ED),
            ApiErrorId.ERR_MATERIALS_NOT_READY.value,
        )

        offering = refresh_offering(offering_id)
        assert offering["status"] == "UNDER_REVIEW"
        assert offering["materials_ready"] is False

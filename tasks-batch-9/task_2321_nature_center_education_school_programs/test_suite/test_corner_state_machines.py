"""State-machine behaviour of the Nature Center Education API.

Every scenario is built from scratch through PRD-declared endpoints, because each
test starts against an empty database with the logical clock at its startup
default.
"""

import pytest

from test_helpers import (
    BC,
    CS,
    CS_ASSESSOR,
    CURRICULUM_SPECIALIST_ASSESSOR_ID,
    DEFAULT_CLOCK,
    ED,
    EDUCATION_DIRECTOR_ID,
    GO,
    SM,
    ApiErrorId,
    assign_resources,
    attach_alignments,
    attach_materials,
    create_aid_application_payload,
    create_booking,
    create_booking_payload,
    create_cleared_educator,
    create_curriculum_material_payload,
    create_draft_offering,
    create_educator,
    create_equipment_manifest_payload,
    create_fund,
    create_offering_under_review,
    create_onboarding_educator,
    create_permit,
    create_permitted_animal,
    create_published_offering,
    create_scholarship_fund_payload,
    create_school,
    create_standard_alignment_payload,
    create_trail_segment,
    enroll_training,
    find_material,
    find_training_record,
    make_teacher_contact_headers,
    refresh_animal,
    refresh_booking,
    refresh_educator,
    refresh_fund,
    refresh_offering,
    refresh_permit,
    refresh_school,
    refresh_trail_segment,
    set_clock,
    setup_accepted_evaluation,
    setup_booking_scenario,
    setup_booking_with_submitted_aid,
    setup_outreach_booking_with_manifest,
    validate_error,
    validate_success,
)

CLOCK_ISO_RENDERED = "2026-09-28T07:00:00.000Z"


def _setup_booking_with_trail_and_animal():
    """A REQUESTED booking on an offering that needs both a trail segment and a
    live animal, with all three resources already attached.

    Returns ``{"offering", "school", "educator", "animal", "permit",
    "trail_segment", "booking"}``.
    """
    set_clock(DEFAULT_CLOCK)
    animal_bundle = create_permitted_animal(weekly_exposure_cap_minutes=480)
    trail = create_trail_segment(capacity_persons=60, weekly_visitor_budget_persons=300)
    offering = create_published_offering(
        requires_live_animal=True, requires_trail_segment=True, slug_prefix="pond"
    )
    school = create_school()
    staffing = create_cleared_educator(handling_tier="TIER_1")
    booking = create_booking(
        school["id"], offering["id"], student_count=30, chaperone_count=3
    )
    booking = assign_resources(
        booking["id"],
        lead_educator_id=staffing["educator"]["id"],
        trail_segment_id=trail["id"],
        animal_id=animal_bundle["animal"]["id"],
    )
    return {
        "permit": animal_bundle["permit"],
        "animal": animal_bundle["animal"],
        "trail_segment": trail,
        "offering": offering,
        "school": school,
        "educator": staffing["educator"],
        "booking": booking,
    }


class TestOfferingReviewTransitions:
    def test_submit_for_review_moves_a_draft_offering_under_review(self, api):
        """PRD §3.1: "Sending an offering into review advances `DRAFT` to `UNDER_REVIEW`, or `REVISION_REQUESTED` to `UNDER_REVIEW` — the revision loop `REVISION_REQUESTED → UNDER_REVIEW → REVISION_REQUESTED` is a supported cycle, not an error path."

        Design: Corner/state_machines/offering_submit_for_review_moves_draft_to_under_review
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_draft_offering()
        attach_alignments(
            offering["id"],
            ({"standard_code": "3-LS4-3", "dimension": "DISCIPLINARY_CORE_IDEA"},),
        )
        attach_materials(offering["id"], slug_prefix="off", publish=True)

        data = validate_success(api.submit_offering_for_review(offering["id"], CS))

        assert data["status"] == "UNDER_REVIEW"
        assert data["standard_alignment_count"] == 1
        assert data["revision_round"] == 0
        assert data["materials_ready"] is True

    def test_submit_needs_one_alignment_while_publishing_needs_two(self, api):
        """PRD §2.9: "Sending an offering into review requires `standard_alignment_count` of at least 1; publishing it requires at least 2."

        Design: Corner/state_machines/catalog_alignment_thresholds_gate_submit_and_publish_separately
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_draft_offering()
        attach_materials(offering["id"], slug_prefix="off", publish=True)

        validate_error(
            api.submit_offering_for_review(offering["id"], CS),
            ApiErrorId.ERR_INSUFFICIENT_STANDARD_ALIGNMENT.value,
        )

        validate_success(
            api.create_standard_alignment(
                offering["id"],
                create_standard_alignment_payload(
                    standard_code="3-LS4-3", dimension="DISCIPLINARY_CORE_IDEA"
                ),
                CS,
            ),
            expected_status=201,
        )
        submitted = validate_success(api.submit_offering_for_review(offering["id"], CS))
        assert submitted["status"] == "UNDER_REVIEW"

        validate_error(
            api.review_program_offering(offering["id"], {"decision": "PUBLISH"}, ED),
            ApiErrorId.ERR_INSUFFICIENT_STANDARD_ALIGNMENT.value,
        )
        assert refresh_offering(offering["id"])["status"] == "UNDER_REVIEW"

        validate_success(
            api.create_standard_alignment(
                offering["id"],
                create_standard_alignment_payload(
                    standard_code="3-LS4-4", dimension="SCIENCE_PRACTICE"
                ),
                CS,
            ),
            expected_status=201,
        )
        published = validate_success(
            api.review_program_offering(offering["id"], {"decision": "PUBLISH"}, ED)
        )
        assert published["status"] == "PUBLISHED"
        assert published["standard_alignment_count"] == 2

    def test_publish_decision_stamps_published_at_and_the_deciding_actor(self, api):
        """PRD §3.1: "On success the offering moves `UNDER_REVIEW → PUBLISHED`, `published_at` is stamped with the logical clock, and `reviewed_by_user_id` records the deciding `X-User-ID`."

        Design: Corner/state_machines/catalog_alignment_thresholds_gate_submit_and_publish_separately
        """
        set_clock(DEFAULT_CLOCK)
        bundle = create_offering_under_review()

        data = validate_success(
            api.review_program_offering(
                bundle["offering"]["id"], {"decision": "PUBLISH"}, ED
            )
        )

        assert data["status"] == "PUBLISHED"
        assert data["published_at"] == CLOCK_ISO_RENDERED
        assert data["reviewed_by_user_id"] == EDUCATION_DIRECTOR_ID


class TestConfirmationCounterFanout:
    def test_confirmation_commits_trail_persons_and_animal_exposure_at_once(self, api):
        """PRD §3.6: "On success, confirmation commits capacity in three places at once: the booking moves to `CONFIRMED`, the attached trail segment's `visitors_this_week` increases by `student_count` plus `chaperone_count`, the attached animal's `projected_exposure_minutes_7d` increases by the offering's `duration_minutes`, and that animal's `welfare_posture` and `effective_contact_rule` are recomputed from the new projection — which means confirming one booking can push an ambassador from `OPEN` into `RESTRICTED` and thereby block the next booking that needs supervised touch."

        Design: Corner/state_machines/confirm_writes_trail_educator_and_animal_counters_in_one_transition
        """
        scenario = _setup_booking_with_trail_and_animal()

        confirmed = validate_success(api.confirm_booking(scenario["booking"]["id"], BC))

        assert confirmed["delivery_status"] == "CONFIRMED"
        assert confirmed["funding_status"] == "UNFUNDED"
        assert confirmed["required_chaperones"] == 3

        trail = refresh_trail_segment(scenario["trail_segment"]["id"])
        assert trail["visitors_this_week"] == 33

        animal = refresh_animal(scenario["animal"]["id"])
        assert animal["projected_exposure_minutes_7d"] == 120
        assert animal["realized_exposure_minutes_7d"] == 0
        assert animal["welfare_posture"] == "OPEN"
        assert animal["effective_contact_rule"] == "VIEW_ONLY"

    def test_confirmation_leaves_the_educator_weekly_load_at_the_booked_duration(
        self, api
    ):
        """PRD §3.3: "`delivery_load_minutes_this_week` is the sum of the booked offerings' `duration_minutes` across every booking whose `lead_educator_id` is this educator and whose `delivery_status` is `REQUESTED`, `CONFIRMED`, `RAIN_DIVERTED` or `DELIVERED`, restricted to bookings whose `start_utc` falls inside the ISO program week containing the logical clock."

        Design: Corner/state_machines/confirm_writes_trail_educator_and_animal_counters_in_one_transition
        """
        scenario = _setup_booking_with_trail_and_animal()

        validate_success(api.confirm_booking(scenario["booking"]["id"], BC))

        educator = refresh_educator(scenario["educator"]["id"])
        assert educator["delivery_load_minutes_this_week"] == 120


class TestInitialStates:
    def test_new_booking_opens_requested_and_unfunded_with_no_resources(self, api):
        """PRD §3.6: "A newly created booking opens at `delivery_status` of `REQUESTED` and `funding_status` of `UNFUNDED`, with `trail_segment_id`, `lead_educator_id`, `animal_id` and `rain_diverted_to_offering_id` all unset and `resource_release_reason` null."

        Design: Corner/state_machines/new_rows_start_in_their_declared_initial_states_on_both_dimensions
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_published_offering()
        school = create_school()

        data = validate_success(
            api.create_booking(
                create_booking_payload(
                    school["id"], offering["id"], student_count=30, chaperone_count=3
                ),
                BC,
            ),
            expected_status=201,
        )

        assert data["delivery_status"] == "REQUESTED"
        assert data["funding_status"] == "UNFUNDED"
        assert data.get("trail_segment_id") is None
        assert data.get("lead_educator_id") is None
        assert data.get("animal_id") is None
        assert data.get("rain_diverted_to_offering_id") is None
        assert data.get("resource_release_reason") is None

    def test_new_equipment_manifest_opens_draft_with_no_shortages(self, api):
        """PRD §3.9: "A `BookingCoordinator` opens a manifest against a booking with the `kit_codes` array of kits being loaded and a `total_weight_kg` greater than 0 and at most 4000; the manifest records its own `booking_id` and opens at `DRAFT` with an empty `shortage_kit_codes` array."

        Design: Corner/state_machines/new_rows_start_in_their_declared_initial_states_on_both_dimensions
        """
        scenario = setup_booking_scenario()

        data = validate_success(
            api.create_equipment_manifest(
                scenario["booking"]["id"],
                create_equipment_manifest_payload(
                    kit_codes=["KIT-POND-A"], total_weight_kg=40.0
                ),
                BC,
            ),
            expected_status=201,
        )

        assert data["status"] == "DRAFT"
        assert data["shortage_kit_codes"] == []
        assert data.get("vehicle_class") is None
        assert data["booking_id"] == scenario["booking"]["id"]

    def test_new_scholarship_pool_opens_with_a_zeroed_ledger(self, api):
        """PRD §3.8: "A new pool opens at `OPEN` with `pending_cents`, `committed_cents`, `disbursed_cents` and `transport_awarded_cents` all at 0 and `available_cents` equal to `total_cents`."

        Design: Corner/state_machines/new_rows_start_in_their_declared_initial_states_on_both_dimensions
        """
        data = validate_success(
            api.create_scholarship_fund(create_scholarship_fund_payload(), GO),
            expected_status=201,
        )

        assert data["status"] == "OPEN"
        assert data["pending_cents"] == 0
        assert data["committed_cents"] == 0
        assert data["disbursed_cents"] == 0
        assert data["transport_awarded_cents"] == 0
        assert data["available_cents"] == data["total_cents"]

    def test_new_aid_application_opens_submitted_and_moves_funding_to_aid_pending(
        self, api
    ):
        """PRD §3.8: "A successful create opens the application at `SUBMITTED`, stamps `submitted_by_user_id`, advances the booking's `funding_status` from `UNFUNDED` to `AID_PENDING`, recomputes the pool's `pending_cents` and `available_cents`, and increments `ScholarshipFund.version` by 1."

        Design: Corner/state_machines/new_rows_start_in_their_declared_initial_states_on_both_dimensions
        """
        scenario = setup_booking_scenario()
        fund = create_fund()
        teacher = make_teacher_contact_headers(scenario["school"]["id"])

        data = validate_success(
            api.create_aid_application(
                create_aid_application_payload(
                    scenario["booking"]["id"],
                    fund["id"],
                    fund["version"],
                    requested_scholarship_cents=10000,
                    requested_transport_cents=0,
                ),
                teacher,
            ),
            expected_status=201,
        )

        assert data["status"] == "SUBMITTED"
        assert data["awarded_scholarship_cents"] == 0
        assert data["awarded_transport_cents"] == 0

        booking = refresh_booking(scenario["booking"]["id"])
        assert booking["funding_status"] == "AID_PENDING"
        assert booking["delivery_status"] == "REQUESTED"

        reloaded_fund = refresh_fund(fund["id"])
        assert reloaded_fund["status"] == "OPEN"
        assert reloaded_fund["pending_cents"] == 10000
        assert reloaded_fund["version"] == fund["version"] + 1


class TestTerminalBookingState:
    def test_cancelling_a_requested_booking_records_the_school_release_reason(self, api):
        """PRD §3.7: "From `REQUESTED`, cancellation sets `delivery_status` to `CANCELLED` with `resource_release_reason` of `CANCELLED_BY_SCHOOL` — or `SCHOOL_SUSPENSION` when the cancellation was driven by the suspension cascade rather than by a request — and then revokes money: every aid application of this booking whose status is `APPROVED` or `PARTIALLY_APPROVED` transitions to `REVOKED`, the fund's `committed_cents` and `available_cents` are recomputed, and the booking's `aid_amount_cents` and `net_due_cents` fall to 0."

        Design: Corner/state_machines/cancelled_booking_refuses_every_further_delivery_transition
        """
        scenario = setup_booking_scenario()

        data = validate_success(
            api.cancel_booking(
                scenario["booking"]["id"], {"reason": "Bus contract fell through"}, BC
            )
        )

        assert data["delivery_status"] == "CANCELLED"
        assert data["resource_release_reason"] == "CANCELLED_BY_SCHOOL"
        assert data["funding_status"] == "UNFUNDED"
        assert data["aid_amount_cents"] == 0
        assert data["net_due_cents"] == 0

    @pytest.mark.parametrize("verb", ["confirm", "cancel", "no_show"])
    def test_cancelled_booking_refuses_every_further_delivery_transition(self, api, verb):
        """PRD §2.9: "The target resource's own current state permits the requested transition — otherwise the state code for that entity (409): `ERR_INVALID_OFFERING_STATE`, `ERR_INVALID_MATERIAL_STATE`, `ERR_INVALID_EDUCATOR_STATE`, `ERR_INVALID_TRAINING_STATE`, `ERR_INVALID_PERMIT_STATE`, `ERR_INVALID_ANIMAL_STATE`, `ERR_INVALID_TRAIL_STATE`, `ERR_INVALID_BOOKING_STATE`, `ERR_INVALID_FUNDING_STATE`, `ERR_INVALID_AID_STATE`, `ERR_INVALID_MANIFEST_STATE`, `ERR_INVALID_EVALUATION_STATE` or `ERR_INVALID_FUND_STATE`."

        Design: Corner/state_machines/cancelled_booking_refuses_every_further_delivery_transition
        """
        scenario = setup_booking_scenario()
        booking_id = scenario["booking"]["id"]
        cancelled = validate_success(
            api.cancel_booking(booking_id, {"reason": "Bus contract fell through"}, BC)
        )
        assert cancelled["delivery_status"] == "CANCELLED"

        attempts = {
            "confirm": lambda: api.confirm_booking(booking_id, BC),
            "cancel": lambda: api.cancel_booking(booking_id, {"reason": "Retry"}, BC),
            "no_show": lambda: api.no_show_booking(
                booking_id, {"note": "Never arrived"}, BC
            ),
        }
        validate_error(attempts[verb](), ApiErrorId.ERR_INVALID_BOOKING_STATE.value)

        booking = refresh_booking(booking_id)
        assert booking["delivery_status"] == "CANCELLED"
        assert booking["funding_status"] == "UNFUNDED"
        assert refresh_school(scenario["school"]["id"])["no_show_strikes"] == 0


class TestMaterialPublishIdempotency:
    def test_republishing_a_published_material_is_refused_without_mutating_it(self, api):
        """PRD §3.1: "Materials begin at `DRAFT` and may be published, moving `DRAFT` to `PUBLISHED`; publishing is only possible while the material is in `DRAFT` — otherwise the rejection is `ERR_INVALID_MATERIAL_STATE` — and only while the parent offering sits in `DRAFT`, `UNDER_REVIEW`, `REVISION_REQUESTED` or `PUBLISHED`, a parent-state failure being reported as `ERR_INVALID_OFFERING_STATE`."

        Design: Corner/state_machines/material_publish_is_not_idempotent_and_the_repeat_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_draft_offering()
        attach_alignments(
            offering["id"],
            ({"standard_code": "3-LS4-3", "dimension": "DISCIPLINARY_CORE_IDEA"},),
        )
        material = validate_success(
            api.create_curriculum_material(
                offering["id"],
                create_curriculum_material_payload(
                    phase="PRE_VISIT", url_slug="pond-pre"
                ),
                CS,
            ),
            expected_status=201,
        )
        first = validate_success(api.publish_curriculum_material(material["id"], CS))
        assert first["status"] == "PUBLISHED"

        validate_error(
            api.publish_curriculum_material(material["id"], CS),
            ApiErrorId.ERR_INVALID_MATERIAL_STATE.value,
        )

        reloaded = find_material(offering["id"], material["id"])
        assert reloaded["status"] == "PUBLISHED"
        assert reloaded["version"] == first["version"]
        assert refresh_offering(offering["id"])["materials_ready"] is False


class TestCatalogAndStaffingInvalidTransitions:
    def test_submitting_a_published_offering_for_review_is_refused(self, api):
        """PRD §2.9: "The target resource's own current state permits the requested transition — otherwise the state code for that entity (409): `ERR_INVALID_OFFERING_STATE`, `ERR_INVALID_MATERIAL_STATE`, `ERR_INVALID_EDUCATOR_STATE`, `ERR_INVALID_TRAINING_STATE`, `ERR_INVALID_PERMIT_STATE`, `ERR_INVALID_ANIMAL_STATE`, `ERR_INVALID_TRAIL_STATE`, `ERR_INVALID_BOOKING_STATE`, `ERR_INVALID_FUNDING_STATE`, `ERR_INVALID_AID_STATE`, `ERR_INVALID_MANIFEST_STATE`, `ERR_INVALID_EVALUATION_STATE` or `ERR_INVALID_FUND_STATE`."

        Design: Corner/state_machines/catalog_and_staffing_machines_reject_transitions_from_wrong_states
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_published_offering()

        validate_error(
            api.submit_offering_for_review(offering["id"], CS),
            ApiErrorId.ERR_INVALID_OFFERING_STATE.value,
        )
        assert refresh_offering(offering["id"])["status"] == "PUBLISHED"

    def test_clearing_an_applicant_educator_is_refused(self, api):
        """PRD §3.3: "Attempting a hiring action from a state that does not permit it answers `ERR_INVALID_EDUCATOR_STATE`."

        Design: Corner/state_machines/catalog_and_staffing_machines_reject_transitions_from_wrong_states
        """
        set_clock(DEFAULT_CLOCK)
        educator = create_educator(
            full_name="Wren Salix",
            employment_type="SEASONAL_EDUCATOR",
            season_end_date="2026-12-20T00:00:00Z",
        )
        assert educator["status"] == "APPLICANT"

        validate_error(
            api.advance_educator_hiring(educator["id"], {"action": "CLEAR"}, ED),
            ApiErrorId.ERR_INVALID_EDUCATOR_STATE.value,
        )
        assert refresh_educator(educator["id"])["status"] == "APPLICANT"

    def test_assessing_an_already_passed_training_record_is_refused(self, api):
        """PRD §3.3: "A pass additionally requires the recorded `score` to be at least 70 — a `PASS` carrying a score below 70 cannot take the record into `ASSESSED_PASS` and is rejected with `ERR_INVALID_TRAINING_STATE`, as is any assessment of a record that is not sitting at `ENROLLED`."

        Design: Corner/state_machines/catalog_and_staffing_machines_reject_transitions_from_wrong_states
        """
        set_clock(DEFAULT_CLOCK)
        educator = create_onboarding_educator()
        record = enroll_training(educator["id"], track="CURRICULUM", grade_band="G3_5")
        passed = validate_success(
            api.assess_training_record(
                record["id"], {"outcome": "PASS", "score": 88}, CS_ASSESSOR
            )
        )
        assert passed["status"] == "ASSESSED_PASS"

        validate_error(
            api.assess_training_record(record["id"], {"outcome": "FAIL"}, CS_ASSESSOR),
            ApiErrorId.ERR_INVALID_TRAINING_STATE.value,
        )

        reloaded = find_training_record(educator["id"], record["id"])
        assert reloaded["status"] == "ASSESSED_PASS"
        assert reloaded["attempt_count"] == 1


class TestStewardshipInvalidTransitions:
    def test_a_lapsed_permit_cannot_move_sideways_to_suspended(self, api):
        """PRD §3.4: "From `ACTIVE` the manager may go to `SUSPENDED`, to `LAPSED` or to `REVOKED`; from either `SUSPENDED` or `LAPSED` the permit may be restored to `ACTIVE`; `REVOKED` is terminal. Any other combination is refused with `ERR_INVALID_PERMIT_STATE`."

        Design: Corner/state_machines/stewardship_machines_reject_transitions_that_skip_the_open_state
        """
        set_clock(DEFAULT_CLOCK)
        permit = create_permit(agency="STATE_DNR", permit_number="DNR-2026-441")
        lapsed = validate_success(
            api.set_permit_status(
                permit["id"],
                {"status": "LAPSED", "note": "Renewal paperwork outstanding"},
                SM,
            )
        )
        assert lapsed["status"] == "LAPSED"

        validate_error(
            api.set_permit_status(permit["id"], {"status": "SUSPENDED"}, SM),
            ApiErrorId.ERR_INVALID_PERMIT_STATE.value,
        )
        assert refresh_permit(permit["id"])["status"] == "LAPSED"

    def test_an_animal_on_vet_hold_cannot_move_sideways_to_resting(self, api):
        """PRD §3.4: "A status change from a state that does not permit it answers `ERR_INVALID_ANIMAL_STATE`."

        Design: Corner/state_machines/stewardship_machines_reject_transitions_that_skip_the_open_state
        """
        set_clock(DEFAULT_CLOCK)
        bundle = create_permitted_animal()
        held = validate_success(
            api.set_animal_care_status(
                bundle["animal"]["id"],
                {"status": "VET_HOLD", "note": "Beak abrasion"},
                SM,
            )
        )
        assert held["status"] == "VET_HOLD"

        validate_error(
            api.set_animal_care_status(
                bundle["animal"]["id"], {"status": "RESTING"}, SM
            ),
            ApiErrorId.ERR_INVALID_ANIMAL_STATE.value,
        )

        animal = refresh_animal(bundle["animal"]["id"])
        assert animal["status"] == "VET_HOLD"
        assert animal["welfare_posture"] == "BLOCKED"
        assert animal["effective_contact_rule"] == "NO_PUBLIC_CONTACT"

    def test_a_closed_trail_segment_cannot_move_sideways_to_restoration_rest(self, api):
        """PRD §3.5: "Any other transition is refused with `ERR_INVALID_TRAIL_STATE`, and a segment that is not `OPEN` cannot be attached to a booking or carry one through confirmation — that rejection is `ERR_TRAIL_NOT_OPEN`."

        Design: Corner/state_machines/stewardship_machines_reject_transitions_that_skip_the_open_state
        """
        set_clock(DEFAULT_CLOCK)
        trail = create_trail_segment(
            capacity_persons=60, weekly_visitor_budget_persons=300
        )
        closed = validate_success(
            api.set_trail_segment_status(
                trail["id"],
                {"status": "CLOSED", "note": "Washout at the boardwalk"},
                SM,
            )
        )
        assert closed["status"] == "CLOSED"

        validate_error(
            api.set_trail_segment_status(
                trail["id"], {"status": "RESTORATION_REST"}, SM
            ),
            ApiErrorId.ERR_INVALID_TRAIL_STATE.value,
        )
        assert refresh_trail_segment(trail["id"])["status"] == "CLOSED"


class TestFundingAndChildEntityInvalidTransitions:
    def test_payment_against_a_booking_that_is_not_invoiced_is_refused(self, api):
        """PRD §3.8: "A payment may only be recorded against a booking whose `funding_status` is `INVOICED` — otherwise `ERR_INVALID_FUNDING_STATE` — and may not exceed the outstanding balance, that is `net_due_cents` less `paid_cents`, or it is refused with `ERR_PAYMENT_EXCEEDS_BALANCE`."

        Design: Corner/state_machines/funding_aid_manifest_evaluation_and_fund_machines_reject_wrong_state_calls
        """
        scenario = setup_booking_scenario()

        validate_error(
            api.record_payment(scenario["booking"]["id"], {"amount_cents": 100}, BC),
            ApiErrorId.ERR_INVALID_FUNDING_STATE.value,
        )

        booking = refresh_booking(scenario["booking"]["id"])
        assert booking["delivery_status"] == "REQUESTED"
        assert booking["funding_status"] == "UNFUNDED"
        assert booking["paid_cents"] == 0

    def test_approving_an_already_denied_aid_application_is_refused(self, api):
        """PRD §3.8: "The application must be sitting at `SUBMITTED` — anything else is `ERR_INVALID_AID_STATE` — and the pool must be `OPEN`."

        Design: Corner/state_machines/funding_aid_manifest_evaluation_and_fund_machines_reject_wrong_state_calls
        """
        scenario = setup_booking_with_submitted_aid(
            requested_scholarship_cents=5000, requested_transport_cents=0
        )
        denied = validate_success(
            api.review_aid_application(
                scenario["aid_application"]["id"],
                {"decision": "DENY", "reviewer_note": "Out of scope for this pool"},
                GO,
            )
        )
        assert denied["status"] == "DENIED"

        validate_error(
            api.review_aid_application(
                scenario["aid_application"]["id"], {"decision": "APPROVE"}, GO
            ),
            ApiErrorId.ERR_INVALID_AID_STATE.value,
        )

        booking = refresh_booking(scenario["booking"]["id"])
        assert booking["funding_status"] == "UNFUNDED"

    def test_loading_an_already_loaded_manifest_is_refused(self, api):
        """PRD §3.9: "Both `RETURNED` and `SHORTAGE_REPORTED` are terminal, and an advance action from a state that does not permit it answers `ERR_INVALID_MANIFEST_STATE`."

        Design: Corner/state_machines/funding_aid_manifest_evaluation_and_fund_machines_reject_wrong_state_calls
        """
        scenario = setup_outreach_booking_with_manifest(
            total_weight_kg=120.0, kit_codes=("KIT-A", "KIT-B"), load=True
        )
        assert scenario["manifest"]["status"] == "LOADED"

        validate_error(
            api.advance_equipment_manifest(
                scenario["manifest"]["id"], {"action": "LOAD"}, BC
            ),
            ApiErrorId.ERR_INVALID_MANIFEST_STATE.value,
        )

    def test_resubmitting_an_accepted_evaluation_report_is_refused(self, api):
        """PRD §3.9: "A submit or review action from a state that does not permit it answers `ERR_INVALID_EVALUATION_STATE`, and evaluation lists can be filtered by `status`."

        Design: Corner/state_machines/funding_aid_manifest_evaluation_and_fund_machines_reject_wrong_state_calls
        """
        scenario = setup_accepted_evaluation()
        assert scenario["evaluation_report"]["status"] == "ACCEPTED"

        validate_error(
            api.submit_evaluation_report(
                scenario["evaluation_report"]["id"], scenario["teacher_headers"]
            ),
            ApiErrorId.ERR_INVALID_EVALUATION_STATE.value,
        )

    def test_freezing_an_already_frozen_pool_is_refused(self, api):
        """PRD §3.8: "`CLOSED` is terminal, and any other status change answers `ERR_INVALID_FUND_STATE`."

        Design: Corner/state_machines/funding_aid_manifest_evaluation_and_fund_machines_reject_wrong_state_calls
        """
        fund = create_fund()
        frozen = validate_success(
            api.set_scholarship_fund_status(fund["id"], {"status": "FROZEN"}, GO)
        )
        assert frozen["status"] == "FROZEN"

        validate_error(
            api.set_scholarship_fund_status(fund["id"], {"status": "FROZEN"}, GO),
            ApiErrorId.ERR_INVALID_FUND_STATE.value,
        )
        assert refresh_fund(fund["id"])["status"] == "FROZEN"


class TestEducatorPipeline:
    def test_start_onboarding_stamps_the_background_check_from_the_logical_clock(
        self, api
    ):
        """PRD §3.3: "`START_ONBOARDING` moves `APPLICANT → ONBOARDING` and stamps `background_check_started_at` with the logical clock."

        Design: Corner/state_machines/educator_pipeline_walks_applicant_onboarding_cleared_inactive
        """
        set_clock(DEFAULT_CLOCK)
        educator = create_educator()
        assert educator["status"] == "APPLICANT"
        assert educator["animal_handling_tier"] == "NONE"
        assert educator["curriculum_certified_grade_bands"] == []
        assert educator["delivery_load_minutes_this_week"] == 0

        data = validate_success(
            api.advance_educator_hiring(
                educator["id"], {"action": "START_ONBOARDING"}, ED
            )
        )

        assert data["status"] == "ONBOARDING"
        assert data["background_check_started_at"] == CLOCK_ISO_RENDERED

    def test_a_curriculum_pass_stamps_expiry_and_opens_the_path_to_cleared(self, api):
        """PRD §3.3: "`ENROLLED → ASSESSED_PASS` stamps `passed_at` with the logical clock, sets `expires_on` to that instant plus a validity window of one year — 365 days — and re-derives the educator's aggregate credentials: `curriculum_certified_grade_bands` is refreshed to the set of grade bands for which the educator holds a `CURRICULUM` record in `ASSESSED_PASS` when the track was curriculum, and `animal_handling_tier` is refreshed to the highest `handling_tier` across the educator's passing `LIVE_ANIMAL_HANDLING` records — `NONE` when there are none — when the track was handling."

        Design: Corner/state_machines/educator_pipeline_walks_applicant_onboarding_cleared_inactive
        """
        set_clock(DEFAULT_CLOCK)
        educator = create_onboarding_educator()
        record = enroll_training(educator["id"], track="CURRICULUM", grade_band="G3_5")

        assessed = validate_success(
            api.assess_training_record(
                record["id"], {"outcome": "PASS", "score": 88}, CS_ASSESSOR
            )
        )

        assert assessed["status"] == "ASSESSED_PASS"
        assert assessed["passed_at"] == CLOCK_ISO_RENDERED
        assert assessed["expires_on"] == "2027-09-28T07:00:00.000Z"
        assert assessed["attempt_count"] == 1
        assert assessed["assessed_by_user_id"] == CURRICULUM_SPECIALIST_ASSESSOR_ID

        cleared = validate_success(
            api.advance_educator_hiring(educator["id"], {"action": "CLEAR"}, ED)
        )
        assert cleared["status"] == "CLEARED"
        assert cleared["curriculum_certified_grade_bands"] == ["G3_5"]

    def test_deactivation_is_terminal_and_keeps_the_certification_history(self, api):
        """PRD §3.3: "`DEACTIVATE` moves either `CLEARED → INACTIVE` or `ONBOARDING → INACTIVE`, and `INACTIVE` is terminal."

        Design: Corner/state_machines/educator_pipeline_walks_applicant_onboarding_cleared_inactive
        """
        set_clock(DEFAULT_CLOCK)
        staffing = create_cleared_educator(handling_tier="TIER_2")
        educator_id = staffing["educator"]["id"]
        assert refresh_educator(educator_id)["animal_handling_tier"] == "TIER_2"

        data = validate_success(
            api.advance_educator_hiring(educator_id, {"action": "DEACTIVATE"}, ED)
        )

        assert data["status"] == "INACTIVE"
        assert data["curriculum_certified_grade_bands"] == ["G3_5"]
        assert data["delivery_load_minutes_this_week"] == 0

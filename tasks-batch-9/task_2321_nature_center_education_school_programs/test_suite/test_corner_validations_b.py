"""Corner cases for the Nature Center Education API: rain-plan eligibility, the
uniqueness guards on aid and evaluation, terminal-transition guards, training
attempt exhaustion, the fiscal gates on aid creation, payment ceilings,
resolution and precedence ordering, pagination ranges, the delivery-time
chaperone recomputation, and a confirmation that sits exactly on every limit.
"""

import pytest

from test_helpers import (
    BC,
    CS,
    CS_ASSESSOR,
    ED,
    GO,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assign_resources,
    create_booking,
    create_cleared_educator,
    create_fund,
    create_onboarding_educator,
    create_permitted_animal,
    create_published_offering,
    create_school,
    create_trail_segment,
    enroll_training,
    find_evaluation_report,
    make_headers,
    refresh_aid_application,
    refresh_animal,
    refresh_booking,
    refresh_educator,
    refresh_fund,
    refresh_offering,
    refresh_trail_segment,
    set_clock,
    setup_booking_scenario,
    setup_booking_with_submitted_aid,
    setup_confirmed_booking,
    setup_delivered_booking,
    setup_evaluation_in_draft,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

# A second identifier that is a well-formed UUID but names no row, so a test can
# make two references wrong at once.
_ALSO_MISSING_UUID = "11111111-1111-1111-1111-111111111111"


def _catalog_with_school_and_booking():
    """A PUBLISHED offering, a registered school and one REQUESTED booking with no
    resources attached."""
    scenario = setup_booking_scenario(assign_educator=False)
    return scenario


class TestRainDiversionEligibility:
    def test_named_alternate_that_is_not_a_declared_rain_plan_is_refused(self, api):
        """PRD §3.7: "When named explicitly, the substitute must satisfy the eligibility filter below or the request is rejected with `ERR_RAIN_ALTERNATE_NOT_ELIGIBLE`."

        Design: Corner/validations/rain_divert_rejects_an_ineligible_alternate_and_an_empty_candidate_pool
        """
        scenario = setup_confirmed_booking(student_count=30, chaperone_count=3)
        unrelated = create_published_offering(
            slug_prefix="raptor",
            title="Raptor Encounter",
            base_fee_cents_per_student=900,
        )
        assert unrelated.get("rain_alternate_for_offering_id") is None

        response = api.rain_divert_booking(
            scenario["booking"]["id"],
            {"alternate_offering_id": unrelated["id"], "reason": "Heavy rain"},
            BC,
        )
        validate_error(response, ApiErrorId.ERR_RAIN_ALTERNATE_NOT_ELIGIBLE.value)

        booking = refresh_booking(scenario["booking"]["id"])
        assert booking["delivery_status"] == "CONFIRMED"
        assert booking["provisional_gross_fee_cents"] == 33300
        assert booking["rain_diverted_to_offering_id"] is None

    def test_omitted_alternate_with_an_empty_candidate_pool_is_refused(self, api):
        """PRD §3.7: "If the pool is empty the diversion fails with `ERR_NO_RAIN_ALTERNATE`, the booking stays at `CONFIRMED`, and nothing at all is mutated."

        Design: Corner/validations/rain_divert_rejects_an_ineligible_alternate_and_an_empty_candidate_pool
        """
        scenario = setup_confirmed_booking(student_count=30, chaperone_count=3)
        create_published_offering(
            slug_prefix="raptor",
            title="Raptor Encounter",
            base_fee_cents_per_student=900,
        )

        response = api.rain_divert_booking(
            scenario["booking"]["id"], {"reason": "Heavy rain"}, BC
        )
        validate_error(response, ApiErrorId.ERR_NO_RAIN_ALTERNATE.value)

        booking = refresh_booking(scenario["booking"]["id"])
        assert booking["delivery_status"] == "CONFIRMED"
        assert booking["provisional_gross_fee_cents"] == 33300
        assert booking["rain_diverted_to_offering_id"] is None


class TestUniquenessOnAidAndEvaluation:
    def test_second_aid_application_on_the_same_booking_is_refused(self, api):
        """PRD §3.8: "It is accepted only while the booking's `funding_status` is `UNFUNDED` and its `delivery_status` is `REQUESTED` or `CONFIRMED`, only against a pool whose status is `OPEN` (`ERR_FUND_NOT_OPEN`), only for a school whose `equity_tier` is not `NONE` (`ERR_NOT_AID_ELIGIBLE`), and only when the booking has no other application sitting in `SUBMITTED`, `APPROVED`, `PARTIALLY_APPROVED` or `DISBURSED` (`ERR_DUPLICATE_AID_APPLICATION`)."

        Design: Corner/validations/a_second_aid_application_and_a_second_evaluation_are_rejected
        """
        scenario = setup_booking_with_submitted_aid(
            requested_scholarship_cents=20000, requested_transport_cents=0
        )
        fund = refresh_fund(scenario["fund"]["id"])

        response = api.create_aid_application(
            {
                "booking_id": scenario["booking"]["id"],
                "fund_id": fund["id"],
                "requested_scholarship_cents": 4000,
                "requested_transport_cents": 0,
                "expected_fund_version": fund["version"],
            },
            BC,
        )
        # The live application also holds the booking's funding dimension at
        # AID_PENDING, so either precondition may legitimately answer first.
        validate_error_is_one_of(
            response,
            [
                ApiErrorId.ERR_DUPLICATE_AID_APPLICATION.value,
                ApiErrorId.ERR_INVALID_FUNDING_STATE.value,
            ],
        )

        after = refresh_fund(fund["id"])
        assert after["pending_cents"] == 20000
        assert after["available_cents"] == 4980000
        assert (
            refresh_aid_application(scenario["aid_application"]["id"])["status"]
            == "SUBMITTED"
        )

    def test_second_evaluation_report_on_the_same_booking_is_refused(self, api):
        """PRD §3.9: "The report records its `booking_id`, opens at `DRAFT` with `learning_gain_index` at 0, and only one evaluation may exist per booking: a booking already carrying a report in `DRAFT`, `SUBMITTED`, `RETURNED` or `ACCEPTED` refuses a second with `ERR_DUPLICATE_EVALUATION`."

        Design: Corner/validations/a_second_aid_application_and_a_second_evaluation_are_rejected
        """
        scenario = setup_evaluation_in_draft()

        response = api.create_evaluation_report(
            scenario["booking"]["id"],
            {
                "teacher_score_standards_alignment": 5,
                "teacher_score_logistics": 5,
                "teacher_score_engagement": 5,
                "student_pre_score_avg": 10,
                "student_post_score_avg": 18,
            },
            scenario["teacher_headers"],
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_EVALUATION.value)

        existing = find_evaluation_report(
            scenario["booking"]["id"], scenario["evaluation_report"]["id"]
        )
        assert existing["status"] == "DRAFT"


class TestTerminalTransitionGuards:
    def test_retirement_is_blocked_by_a_live_booking_and_allowed_once_cancelled(
        self, api
    ):
        """PRD §3.1: "An offering in `PUBLISHED` may be retired only when no booking references it with a `delivery_status` of `REQUESTED`, `CONFIRMED` or `RAIN_DIVERTED`; live demand blocks retirement with `ERR_OFFERING_HAS_ACTIVE_BOOKINGS`."

        Design: Corner/validations/retire_and_close_are_blocked_while_children_are_still_live
        """
        scenario = setup_booking_scenario()
        offering_id = scenario["offering"]["id"]

        blocked = api.retire_program_offering(
            offering_id, ED, {"reason": "Replaced by the 2027 catalog"}
        )
        validate_error(blocked, ApiErrorId.ERR_OFFERING_HAS_ACTIVE_BOOKINGS.value)
        assert refresh_offering(offering_id)["status"] == "PUBLISHED"

        cancelled = validate_success(
            api.cancel_booking(
                scenario["booking"]["id"], {"reason": "Fund withdrawn"}, BC
            )
        )
        assert cancelled["delivery_status"] == "CANCELLED"

        retired = validate_success(
            api.retire_program_offering(
                offering_id, ED, {"reason": "Replaced by the 2027 catalog"}
            )
        )
        assert retired["status"] == "RETIRED"

        materials, _ = validate_paginated(
            api.list_curriculum_materials(offering_id, CS)
        )
        assert materials, "the offering was published with two curriculum materials"
        assert all(row["status"] == "ARCHIVED" for row in materials)

    def test_closing_a_pool_is_blocked_by_a_pending_application_and_allowed_once_decided(
        self, api
    ):
        """PRD §3.8: "A pool's `status` moves `OPEN → FROZEN` and `FROZEN → OPEN` freely, and `OPEN → CLOSED` only when `pending_cents` is exactly 0 — an undecided application blocks closure with `ERR_FUND_HAS_PENDING_APPLICATIONS`."

        Design: Corner/validations/retire_and_close_are_blocked_while_children_are_still_live
        """
        scenario = setup_booking_with_submitted_aid(
            requested_scholarship_cents=12000, requested_transport_cents=0
        )
        fund_id = scenario["fund"]["id"]

        blocked = api.set_scholarship_fund_status(fund_id, {"status": "CLOSED"}, GO)
        validate_error(blocked, ApiErrorId.ERR_FUND_HAS_PENDING_APPLICATIONS.value)
        assert refresh_fund(fund_id)["status"] == "OPEN"

        denied = validate_success(
            api.review_aid_application(
                scenario["aid_application"]["id"],
                {"decision": "DENY", "reviewer_note": "Grant cycle closed early"},
                GO,
            )
        )
        assert denied["status"] == "DENIED"

        closed = validate_success(
            api.set_scholarship_fund_status(fund_id, {"status": "CLOSED"}, GO)
        )
        assert closed["status"] == "CLOSED"
        assert closed["pending_cents"] == 0


class TestTrainingAttemptExhaustion:
    def test_fourth_reenrolment_after_three_failures_is_refused(self, api):
        """PRD §3.3: "The `EducationDirector` may return `ASSESSED_FAIL → ENROLLED`, which clears the recorded `score`, provided `attempt_count` is still strictly below 3; a fourth attempt is refused with `ERR_TRAINING_ATTEMPTS_EXHAUSTED`."

        Design: Corner/validations/reenrolling_after_three_failed_attempts_is_rejected
        """
        educator = create_onboarding_educator()
        record = enroll_training(
            educator["id"], track="CURRICULUM", grade_band="G3_5"
        )

        first_fail = validate_success(
            api.assess_training_record(record["id"], {"outcome": "FAIL"}, CS_ASSESSOR)
        )
        assert first_fail["status"] == "ASSESSED_FAIL"
        assert first_fail["attempt_count"] == 1

        back_to_enrolled = validate_success(
            api.reenroll_training_record(record["id"], ED)
        )
        assert back_to_enrolled["status"] == "ENROLLED"

        second_fail = validate_success(
            api.assess_training_record(record["id"], {"outcome": "FAIL"}, CS_ASSESSOR)
        )
        assert second_fail["attempt_count"] == 2

        validate_success(api.reenroll_training_record(record["id"], ED))

        third_fail = validate_success(
            api.assess_training_record(record["id"], {"outcome": "FAIL"}, CS_ASSESSOR)
        )
        assert third_fail["status"] == "ASSESSED_FAIL"
        assert third_fail["attempt_count"] == 3

        exhausted = api.reenroll_training_record(record["id"], ED)
        validate_error(exhausted, ApiErrorId.ERR_TRAINING_ATTEMPTS_EXHAUSTED.value)

        assert refresh_educator(educator["id"])["curriculum_certified_grade_bands"] == []


class TestAidEligibilityTier:
    def test_school_without_an_equity_tier_cannot_apply(self, api):
        """PRD §2.9: "The school's `equity_tier` is not `NONE` — otherwise `ERR_NOT_AID_ELIGIBLE` (422)."

        Design: Corner/validations/aid_applications_from_a_school_without_an_equity_tier_are_rejected
        """
        set_clock()
        offering = create_published_offering()
        fund = create_fund()
        school = create_school(
            name="Lakeside Day School", district_code="LEA-12", title_i_pct=0.1
        )
        booking = create_booking(
            school["id"],
            offering["id"],
            start_utc="2026-09-29T14:00:00Z",
            end_utc="2026-09-29T16:00:00Z",
            student_count=30,
            chaperone_count=3,
        )

        response = api.create_aid_application(
            {
                "booking_id": booking["id"],
                "fund_id": fund["id"],
                "requested_scholarship_cents": 10000,
                "requested_transport_cents": 0,
                "expected_fund_version": fund["version"],
            },
            BC,
        )
        validate_error(response, ApiErrorId.ERR_NOT_AID_ELIGIBLE.value)

        assert refresh_booking(booking["id"])["funding_status"] == "UNFUNDED"
        after = refresh_fund(fund["id"])
        assert after["pending_cents"] == 0
        assert after["available_cents"] == after["total_cents"]

    def test_school_just_above_the_tier_three_threshold_may_apply(self, api):
        """PRD §3.2: "A school's `equity_tier` is `TIER_1` when `title_i_pct` is at least 0.75, `TIER_2` when it is at least 0.50 but below 0.75, `TIER_3` when it is at least 0.25 but below 0.50, and `NONE` below 0.25."

        Design: Corner/validations/aid_applications_from_a_school_without_an_equity_tier_are_rejected
        """
        set_clock()
        offering = create_published_offering()
        fund = create_fund()
        ineligible = create_school(
            name="Lakeside Day School", district_code="LEA-12", title_i_pct=0.1
        )
        eligible = create_school(
            name="Harborview Middle", district_code="LEA-31", title_i_pct=0.3
        )
        assert ineligible["equity_tier"] == "NONE"
        assert eligible["equity_tier"] == "TIER_3"

        booking = create_booking(
            eligible["id"],
            offering["id"],
            start_utc="2026-09-30T14:00:00Z",
            end_utc="2026-09-30T16:00:00Z",
            student_count=30,
            chaperone_count=3,
        )
        aid = validate_success(
            api.create_aid_application(
                {
                    "booking_id": booking["id"],
                    "fund_id": fund["id"],
                    "requested_scholarship_cents": 10000,
                    "requested_transport_cents": 0,
                    "expected_fund_version": fund["version"],
                },
                BC,
            ),
            expected_status=201,
        )
        assert aid["status"] == "SUBMITTED"
        assert aid["booking_id"] == booking["id"]


class TestAidCreationFiscalGates:
    @pytest.mark.parametrize(
        "requested_scholarship_cents,requested_transport_cents,expected_error",
        [
            (25000, 0, ApiErrorId.ERR_FUND_INSUFFICIENT.value),
            (5000, 1000, ApiErrorId.ERR_TRANSPORT_SUBLIMIT_EXCEEDED.value),
        ],
    )
    def test_fiscal_gates_reject_the_ask(
        self,
        api,
        requested_scholarship_cents,
        requested_transport_cents,
        expected_error,
    ):
        """PRD §3.8: "Two fiscal gates apply at creation: the two requested amounts together must not exceed the pool's `available_cents` (`ERR_FUND_INSUFFICIENT`), and a non-zero transport request requires a strictly positive remaining transport sublimit, computed as `total_cents` multiplied by `transport_sublimit_pct` and rounded half up to whole cents, less `transport_awarded_cents` (`ERR_TRANSPORT_SUBLIMIT_EXCEEDED`)."

        Design: Corner/validations/aid_create_rejects_an_ask_beyond_the_pool_and_a_transport_ask_without_sublimit
        """
        set_clock()
        offering = create_published_offering()
        school = create_school()
        fund = create_fund(
            funder_name="Millbrook Trust", total_cents=20000, transport_sublimit_pct=0.0
        )
        booking = create_booking(
            school["id"],
            offering["id"],
            start_utc="2026-09-29T14:00:00Z",
            end_utc="2026-09-29T16:00:00Z",
            student_count=30,
            chaperone_count=3,
        )

        response = api.create_aid_application(
            {
                "booking_id": booking["id"],
                "fund_id": fund["id"],
                "requested_scholarship_cents": requested_scholarship_cents,
                "requested_transport_cents": requested_transport_cents,
                "expected_fund_version": fund["version"],
            },
            BC,
        )
        validate_error(response, expected_error)

        after = refresh_fund(fund["id"])
        assert after["pending_cents"] == 0
        assert after["available_cents"] == 20000
        assert refresh_booking(booking["id"])["funding_status"] == "UNFUNDED"

    def test_scholarship_only_ask_inside_the_pool_is_admitted(self, api):
        """PRD §3.8: "A successful create opens the application at `SUBMITTED`, stamps `submitted_by_user_id`, advances the booking's `funding_status` from `UNFUNDED` to `AID_PENDING`, recomputes the pool's `pending_cents` and `available_cents`, and increments `ScholarshipFund.version` by 1."

        Design: Corner/validations/aid_create_rejects_an_ask_beyond_the_pool_and_a_transport_ask_without_sublimit
        """
        set_clock()
        offering = create_published_offering()
        school = create_school()
        fund = create_fund(
            funder_name="Millbrook Trust", total_cents=20000, transport_sublimit_pct=0.0
        )
        booking = create_booking(
            school["id"],
            offering["id"],
            start_utc="2026-09-29T14:00:00Z",
            end_utc="2026-09-29T16:00:00Z",
            student_count=30,
            chaperone_count=3,
        )

        aid = validate_success(
            api.create_aid_application(
                {
                    "booking_id": booking["id"],
                    "fund_id": fund["id"],
                    "requested_scholarship_cents": 5000,
                    "requested_transport_cents": 0,
                    "expected_fund_version": fund["version"],
                },
                BC,
            ),
            expected_status=201,
        )
        assert aid["status"] == "SUBMITTED"

        after = refresh_fund(fund["id"])
        assert after["pending_cents"] == 5000
        assert after["available_cents"] == 15000
        assert after["transport_sublimit_pct"] == pytest.approx(0.0, abs=0.01)
        assert refresh_booking(booking["id"])["funding_status"] == "AID_PENDING"


class TestPaymentCeiling:
    def test_payment_above_the_remaining_balance_is_refused(self, api):
        """PRD §3.8: "A payment may only be recorded against a booking whose `funding_status` is `INVOICED` — otherwise `ERR_INVALID_FUNDING_STATE` — and may not exceed the outstanding balance, that is `net_due_cents` less `paid_cents`, or it is refused with `ERR_PAYMENT_EXCEEDS_BALANCE`."

        Design: Corner/validations/payments_above_the_open_balance_are_rejected_then_the_exact_balance_settles
        """
        scenario = setup_delivered_booking()
        booking_id = scenario["booking"]["id"]
        assert scenario["booking"]["funding_status"] == "INVOICED"
        assert scenario["booking"]["net_due_cents"] == 33300

        one_cent_over = api.record_payment(booking_id, {"amount_cents": 33301}, BC)
        validate_error(one_cent_over, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value)

        partial = validate_success(
            api.record_payment(booking_id, {"amount_cents": 20000}, BC)
        )
        assert partial["paid_cents"] == 20000
        assert partial["funding_status"] == "INVOICED"

        over_remainder = api.record_payment(booking_id, {"amount_cents": 13301}, BC)
        validate_error(over_remainder, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value)

        assert refresh_booking(booking_id)["paid_cents"] == 20000

    def test_exact_remaining_balance_settles_the_invoice(self, api):
        """PRD §3.8: "Once the accumulated `paid_cents` reaches or exceeds `net_due_cents`, funding advances `INVOICED → SETTLED`, and the school's `outstanding_balance_cents` is recomputed."

        Design: Corner/validations/payments_above_the_open_balance_are_rejected_then_the_exact_balance_settles
        """
        scenario = setup_delivered_booking()
        booking_id = scenario["booking"]["id"]

        validate_success(api.record_payment(booking_id, {"amount_cents": 20000}, BC))
        settled = validate_success(
            api.record_payment(booking_id, {"amount_cents": 13300}, BC)
        )
        assert settled["paid_cents"] == 33300
        assert settled["funding_status"] == "SETTLED"
        assert settled["final_gross_fee_cents"] == 33300


class TestResolutionOrder:
    def test_unknown_path_identifier_wins_over_an_unknown_body_reference(self, api):
        """PRD §2.6: "When a path contains a resource identifier, that identifier is resolved before anything in the body is examined."

        Design: Corner/validations/path_ids_resolve_before_body_foreign_keys_and_body_keys_resolve_in_declared_order
        """
        scenario = _catalog_with_school_and_booking()

        response = api.assign_booking_resources(
            NON_EXISTENT_UUID,
            {
                "expected_booking_version": scenario["booking"]["version"],
                "lead_educator_id": _ALSO_MISSING_UUID,
            },
            BC,
        )
        validate_error(response, ApiErrorId.ERR_BOOKING_NOT_FOUND.value)
        assert refresh_booking(scenario["booking"]["id"])["lead_educator_id"] is None

    def test_unknown_school_wins_over_an_unknown_offering_on_booking_creation(self, api):
        """PRD §2.6: "Foreign keys carried in a request body are resolved after the path, and they too are resolved in a fixed order rather than all at once: `school_id` first, then `offering_id`, then `trail_segment_id`, then `lead_educator_id`, then `animal_id`, then `fund_id`, then `booking_id`."

        Design: Corner/validations/path_ids_resolve_before_body_foreign_keys_and_body_keys_resolve_in_declared_order
        """
        _catalog_with_school_and_booking()

        response = api.create_booking(
            {
                "school_id": NON_EXISTENT_UUID,
                "offering_id": _ALSO_MISSING_UUID,
                "start_utc": "2026-09-29T14:00:00Z",
                "end_utc": "2026-09-29T16:00:00Z",
                "student_count": 30,
                "chaperone_count": 3,
            },
            BC,
        )
        validate_error(response, ApiErrorId.ERR_SCHOOL_NOT_FOUND.value)

    def test_unknown_fund_wins_over_an_unknown_booking_on_aid_creation(self, api):
        """PRD §2.6: "Foreign keys carried in a request body are resolved after the path, and they too are resolved in a fixed order rather than all at once: `school_id` first, then `offering_id`, then `trail_segment_id`, then `lead_educator_id`, then `animal_id`, then `fund_id`, then `booking_id`."

        Design: Corner/validations/path_ids_resolve_before_body_foreign_keys_and_body_keys_resolve_in_declared_order
        """
        _catalog_with_school_and_booking()
        create_fund()

        response = api.create_aid_application(
            {
                "booking_id": NON_EXISTENT_UUID,
                "fund_id": _ALSO_MISSING_UUID,
                "requested_scholarship_cents": 5000,
                "requested_transport_cents": 0,
                "expected_fund_version": 999,
            },
            BC,
        )
        validate_error(response, ApiErrorId.ERR_FUND_NOT_FOUND.value)


class TestCredentialPrecedenceBeforePayload:
    def test_missing_headers_answer_before_the_payload_defect(self, api):
        """PRD §2.1: "If either header is missing or empty the request is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/authentication_and_role_are_settled_before_the_payload_is_read
        """
        set_clock()
        offering = create_published_offering()
        school = create_school()

        response = api.create_booking(
            {
                "school_id": school["id"],
                "offering_id": offering["id"],
                "start_utc": "2026-09-29T14:00:00Z",
                "end_utc": "2026-09-29T16:00:00Z",
                "student_count": -5,
                "chaperone_count": 3,
            },
            {},
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_undeclared_role_answers_before_the_payload_defect(self, api):
        """PRD §2.1: "If `X-User-Role` carries a string that is not one of the seven roles below, the request is rejected with `ERR_UNKNOWN_ROLE`."

        Design: Corner/validations/authentication_and_role_are_settled_before_the_payload_is_read
        """
        set_clock()
        offering = create_published_offering()
        school = create_school()

        response = api.create_booking(
            {
                "school_id": school["id"],
                "offering_id": offering["id"],
                "start_utc": "2026-09-29T14:00:00Z",
                "end_utc": "2026-09-29T16:00:00Z",
                "student_count": -5,
                "chaperone_count": 3,
            },
            make_headers("VolunteerDocent", "vd-01"),
        )
        validate_error(response, ApiErrorId.ERR_UNKNOWN_ROLE.value)

    def test_unauthorised_role_answers_before_the_payload_defect(self, api):
        """PRD §2.1: "If the role is recognised but is not among the roles authorised for the target operation, the request is rejected with `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/validations/authentication_and_role_are_settled_before_the_payload_is_read
        """
        set_clock()
        offering = create_published_offering()
        school = create_school()

        response = api.create_booking(
            {
                "school_id": school["id"],
                "offering_id": offering["id"],
                "start_utc": "2026-09-29T14:00:00Z",
                "end_utc": "2026-09-29T16:00:00Z",
                "student_count": -5,
                "chaperone_count": 3,
            },
            GO,
        )
        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)

    def test_permitted_role_finally_surfaces_the_payload_defect(self, api):
        """PRD §2.9: "The request body and query string conform to the operation's input shape: every required field present, every type correct, every enum value inside its declared set, every number inside its declared range, `limit` between 1 and 100 inclusive, and `offset` at least 0 — otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/validations/authentication_and_role_are_settled_before_the_payload_is_read
        """
        set_clock()
        offering = create_published_offering()
        school = create_school()

        response = api.create_booking(
            {
                "school_id": school["id"],
                "offering_id": offering["id"],
                "start_utc": "2026-09-29T14:00:00Z",
                "end_utc": "2026-09-29T16:00:00Z",
                "student_count": -5,
                "chaperone_count": 3,
            },
            BC,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestPaginationRange:
    @pytest.mark.parametrize(
        "params",
        [
            {"limit": 0},
            {"limit": 101},
            {"limit": 10, "offset": -1},
        ],
    )
    def test_out_of_range_pagination_arguments_are_rejected(self, api, params):
        """PRD §2.3: "A `limit` outside the range 1 through 100, or a negative `offset`, is a request-shape failure and is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/pagination_arguments_outside_the_declared_range_are_rejected
        """
        setup_booking_scenario()

        response = api.list_bookings(BC, params=params)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_largest_legal_page_size_is_accepted(self, api):
        """PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10 when omitted, may not be lower than 1, and may not be higher than 100."

        Design: Corner/validations/pagination_arguments_outside_the_declared_range_are_rejected
        """
        scenario = setup_booking_scenario()

        rows, meta = validate_paginated(
            api.list_bookings(BC, params={"limit": 100, "offset": 0})
        )
        assert meta["limit"] == 100
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert rows[0]["id"] == scenario["booking"]["id"]


class TestDeliveryChaperoneRecomputation:
    def test_delivery_recomputes_the_requirement_from_the_actual_students(self, api):
        """PRD §3.7: "Delivery is reachable from two states, and the branches rejoin: `CONFIRMED → DELIVERED` and `RAIN_DIVERTED → DELIVERED` are both valid, and both require the chaperone ratio to hold against the numbers that actually turned up — `actual_chaperone_count` must be at least `actual_student_count` divided by the offering's `min_chaperone_ratio_students_per_adult`, rounded up to the next whole adult, or the delivery is rejected with `ERR_CHAPERONE_RATIO_UNMET`."

        Design: Corner/validations/deliver_recomputes_the_chaperone_ratio_against_the_actual_head_count
        """
        scenario = setup_confirmed_booking(student_count=30, chaperone_count=3)
        booking_id = scenario["booking"]["id"]
        assert scenario["booking"]["required_chaperones"] == 3

        response = api.deliver_booking(
            booking_id, {"actual_student_count": 40, "actual_chaperone_count": 3}, BC
        )
        validate_error(response, ApiErrorId.ERR_CHAPERONE_RATIO_UNMET.value)
        assert refresh_booking(booking_id)["delivery_status"] == "CONFIRMED"

    def test_delivery_with_the_recomputed_adult_count_reprices_the_final_fee(self, api):
        """PRD §3.8: "The **final** variant reads the `actual_student_count` recorded on site and is evaluated at delivery; its result is stored in `final_gross_fee_cents`."

        Design: Corner/validations/deliver_recomputes_the_chaperone_ratio_against_the_actual_head_count
        """
        scenario = setup_confirmed_booking(student_count=30, chaperone_count=3)
        booking_id = scenario["booking"]["id"]

        delivered = validate_success(
            api.deliver_booking(
                booking_id,
                {"actual_student_count": 40, "actual_chaperone_count": 4},
                BC,
            )
        )
        assert delivered["delivery_status"] == "DELIVERED"
        assert delivered["final_gross_fee_cents"] == 44400
        assert delivered["provisional_gross_fee_cents"] == 33300
        assert delivered["required_chaperones"] == 3
        assert delivered["actual_student_count"] == 40


class TestConfirmationOnEveryBoundary:
    def test_a_booking_touching_every_limit_exactly_still_confirms(self, api):
        """PRD §3.6: "On success, confirmation commits capacity in three places at once: the booking moves to `CONFIRMED`, the attached trail segment's `visitors_this_week` increases by `student_count` plus `chaperone_count`, the attached animal's `projected_exposure_minutes_7d` increases by the offering's `duration_minutes`, and that animal's `welfare_posture` and `effective_contact_rule` are recomputed from the new projection — which means confirming one booking can push an ambassador from `OPEN` into `RESTRICTED` and thereby block the next booking that needs supervised touch."

        Design: Corner/validations/every_gate_satisfied_at_its_exact_boundary_still_confirms
        """
        set_clock()
        offering = create_published_offering(
            slug_prefix="boundary",
            max_group_size=33,
            requires_live_animal=True,
            requires_trail_segment=True,
        )
        school = create_school()
        staffing = create_cleared_educator(handling_tier="TIER_1")
        animal_bundle = create_permitted_animal(weekly_exposure_cap_minutes=600)
        trail = create_trail_segment(
            capacity_persons=33,
            habitat_sensitivity="LOW",
            weekly_visitor_budget_persons=33,
        )
        booking = create_booking(
            school["id"],
            offering["id"],
            start_utc="2026-09-29T14:00:00Z",
            end_utc="2026-09-29T16:00:00Z",
            student_count=30,
            chaperone_count=3,
        )
        assign_resources(
            booking["id"],
            lead_educator_id=staffing["educator"]["id"],
            trail_segment_id=trail["id"],
            animal_id=animal_bundle["animal"]["id"],
        )

        confirmed = validate_success(api.confirm_booking(booking["id"], BC))
        assert confirmed["delivery_status"] == "CONFIRMED"
        assert confirmed["required_chaperones"] == 3
        assert confirmed["chaperone_count"] == 3

        segment = refresh_trail_segment(trail["id"])
        assert segment["visitors_this_week"] == 33
        assert segment["capacity_persons"] == 33

        animal = refresh_animal(animal_bundle["animal"]["id"])
        assert animal["projected_exposure_minutes_7d"] == 120
        assert animal["welfare_posture"] == "OPEN"

        educator = refresh_educator(staffing["educator"]["id"])
        assert educator["delivery_load_minutes_this_week"] == 120

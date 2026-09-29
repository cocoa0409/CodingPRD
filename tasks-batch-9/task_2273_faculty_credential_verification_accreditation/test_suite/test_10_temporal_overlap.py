"""Two interval conventions: half-open teaching blocks, fully closed review windows."""

from test_helpers import (
    ApiErrorId,
    assert_fields,
    assert_risk_value,
    assignment_payload,
    make_assignment,
    make_credentialed_faculty,
    make_program_dean_headers,
    make_review,
    make_section,
    make_verified_credential,
    read_faculty,
    review_payload,
    total_count,
    validate_error,
    validate_success,
    TEST_USERS,
)


def _monday_grid(env):
    """One 09:00-10:20 block plus three 10:20-11:40 candidates."""
    dana = make_credentialed_faculty(
        "Dana Reyes",
        "dana.reyes@example.edu",
        "ADJUNCT",
        env.prog_df_id,
        "MASTERS",
        env.pr_id,
        "State University",
        graduate_credit_hours_in_discipline=30,
    )["faculty"]
    make_verified_credential(
        dana["id"],
        "NON_DEGREE_GRADUATE",
        env.journ_id,
        "State University",
        graduate_credit_hours_in_discipline=18,
    )

    def section(course_code, title, meeting_days=("MON",), **overrides):
        return make_section(
            env.prog_df_id,
            env.term_id,
            env.journ_id,
            course_code,
            title,
            credit_hours=3,
            meeting_days=list(meeting_days),
            **overrides,
        )

    first = section(
        "JOUR101", "News Writing", meeting_start_minute=540, meeting_end_minute=620
    )
    same_building = section(
        "JOUR105",
        "Broadcast Writing",
        building_code="HALL-A",
        meeting_start_minute=620,
        meeting_end_minute=700,
    )
    other_building = section(
        "JOUR106",
        "Photojournalism",
        building_code="HALL-B",
        meeting_start_minute=620,
        meeting_end_minute=700,
    )
    online = section(
        "JOUR107",
        "Media Law Online",
        meeting_days=[],
        delivery_mode="ONLINE_ASYNC",
        building_code="ONLINE",
        meeting_start_minute=620,
        meeting_end_minute=700,
    )
    make_assignment(first["id"], dana["id"], env.prog_df_id)
    return {
        "faculty_id": dana["id"],
        "same_building": same_building,
        "other_building": other_building,
        "online": online,
    }


def _assign(api, env, state, key):
    section = state[key]
    return api.create_course_assignment(
        assignment_payload(section["id"], state["faculty_id"], section["version"]),
        make_program_dean_headers(env.prog_df_id),
    )


class TestTeachingBlockIntervals:
    def test_back_to_back_in_the_same_building_is_legal(self, api, env):
        """PRD §3.4: "Consequently, back-to-back sections in the *same* building,
        where one ends exactly as the other begins, do not conflict, while
        back-to-back sections in *different* buildings do."

        Design: Difficulty/resource_temporal_overlap/teaching_blocks_half_open_with_cross_building_travel_buffer
        """
        state = _monday_grid(env)

        assignment = validate_success(_assign(api, env, state, "same_building"), 201)

        assert_fields(assignment, course_section_id=state["same_building"]["id"])
        assert read_faculty(state["faculty_id"])["assigned_credit_hours"] == 6, (
            "half-open intervals with a zero buffer let 09:00-10:20 and 10:20-11:40 "
            "coexist, so both sections charge the ledger"
        )

    def test_the_same_slot_across_buildings_needs_travel_time(self, api, env):
        """PRD §3.4: "A buffer of 15 minutes applies when the two sections'
        `building_code` values differ, modelling the travel time between buildings,
        and a buffer of 0 applies when they match."

        Design: Difficulty/resource_temporal_overlap/teaching_blocks_half_open_with_cross_building_travel_buffer
        """
        state = _monday_grid(env)
        validate_success(_assign(api, env, state, "same_building"), 201)

        response = _assign(api, env, state, "other_building")

        validate_error(response, ApiErrorId.ERR_TEACHING_BLOCK_CONFLICT)
        assert total_count(
            api.list_section_assignments(
                state["other_building"]["id"], env.dean_df
            )
        ) == 0, "the buffered conflict must not have created an assignment row"

    def test_an_online_async_section_is_exempt_on_either_side(self, api, env):
        """PRD §3.4: "Any section whose `delivery_mode` is `ONLINE_ASYNC` is exempt
        on either side and never conflicts with anything."

        Design: Difficulty/resource_temporal_overlap/teaching_blocks_half_open_with_cross_building_travel_buffer
        """
        state = _monday_grid(env)
        validate_success(_assign(api, env, state, "same_building"), 201)
        validate_error(
            _assign(api, env, state, "other_building"),
            ApiErrorId.ERR_TEACHING_BLOCK_CONFLICT,
        )

        assignment = validate_success(_assign(api, env, state, "online"), 201)

        assert_fields(
            assignment,
            status="EXCEPTION_FLAGGED",
            exception_code="DEGREE_LEVEL_INSUFFICIENT",
        )
        assert read_faculty(state["faculty_id"])["assigned_credit_hours"] == 9, (
            "nine credit hours is exactly the ADJUNCT term cap, so the load rule "
            "never fired"
        )


JULY_WINDOW = ("2026-07-01", "2026-07-31")


def _july_review(env):
    return make_review(env.prog_df_id, "COMPREHENSIVE", *JULY_WINDOW)


class TestReviewWindowCollisions:
    def test_windows_touching_at_a_single_date_collide(self, api, env):
        """PRD §3.9: "Two windows that merely *touch* at a single date therefore do
        collide, and the offender is rejected with `ERR_REVIEW_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/accreditor_review_windows_fully_closed_touching_dates_collide
        """
        july = _july_review(env)

        response = api.create_review(
            review_payload(
                env.prog_df_id, "FOCUSED_FOLLOWUP", "2026-07-31", "2026-08-10"
            ),
            TEST_USERS["reviewer"],
        )

        validate_error(response, ApiErrorId.ERR_REVIEW_WINDOW_OVERLAP)
        assert total_count(
            api.list_reviews(TEST_USERS["reviewer"], {"program_id": env.prog_df_id})
        ) == 1, "the rejected window must not have created a review"
        assert_fields(
            validate_success(api.get_review(july["id"], TEST_USERS["reviewer"])),
            window_end_date="2026-07-31",
            status="SCHEDULED",
        )

    def test_starting_one_day_later_is_accepted(self, api, env):
        """PRD §3.9: "comparing against reviews of that program whose `status` is
        neither `CLOSED_ACCEPTED` nor `CLOSED_SANCTION`, a collision exists when the
        new window's start is on or before the other's end and the other's start is
        on or before the new window's end."

        Design: Difficulty/resource_temporal_overlap/accreditor_review_windows_fully_closed_touching_dates_collide
        """
        july = _july_review(env)
        validate_error(
            api.create_review(
                review_payload(
                    env.prog_df_id, "FOCUSED_FOLLOWUP", "2026-07-31", "2026-08-10"
                ),
                TEST_USERS["reviewer"],
            ),
            ApiErrorId.ERR_REVIEW_WINDOW_OVERLAP,
        )

        august = validate_success(
            api.create_review(
                review_payload(
                    env.prog_df_id, "FOCUSED_FOLLOWUP", "2026-08-01", "2026-08-10"
                ),
                TEST_USERS["reviewer"],
            ),
            201,
        )

        assert_fields(
            august,
            status="SCHEDULED",
            response_round=0,
            finding_count=0,
            window_start_date="2026-08-01",
        )
        assert_risk_value(august["risk_index"], 0.00, "risk_index")
        assert total_count(
            api.list_reviews(TEST_USERS["reviewer"], {"program_id": env.prog_df_id})
        ) == 2, "only the two accepted windows may exist"
        assert_fields(
            validate_success(api.get_review(july["id"], TEST_USERS["reviewer"])),
            window_end_date="2026-07-31",
        )

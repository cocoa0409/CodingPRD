"""Installation activities: crew windows and the release gate chain (PRD §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    accept_assessment,
    activate_spec_section,
    add_reviewer,
    add_spec_section,
    add_subcontractor,
    answer_rfi,
    assessment_for_rfi,
    create_active_project,
    create_activity,
    create_rfi,
    get_activity,
    lli_of_submittal,
    price_assessment,
    return_revision,
    route_revision,
    route_rfi,
    setup_approved_submittal,
    setup_register_world,
    setup_released_submittal,
    submit_revision,
    submittals_of_section,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["project_manager_headers"]
PE = TEST_USERS["project_engineer_headers"]


class TestCrewWindowBoundaries:
    def test_activity_reversed_window_returns_date_range_error(self, api):
        """PRD §3.7: "The `end_date` must be strictly later than the `start_date`,
        failing with `ERR_INVALID_DATE_RANGE` (HTTP 400)."
        An empty window (end == start) is rejected before any crew-conflict math.

        Design: Corner/validations/activity_reversed_window_returns_date_range_error
        """
        world = setup_register_world(
            section_number="033000", lead_time_days=5, default_need_date="2026-09-01"
        )
        resp = api.create_installation_activity(
            world["project"]["id"],
            {
                "submittal_id": world["submittals"][0]["id"],
                "subcontractor_id": world["subcontractor"]["id"],
                "start_date": "2026-09-10",
                "end_date": "2026-09-10",
            },
            PE,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE, 400)

    def test_gap_equal_to_mobilization_buffer_allowed(self, api):
        """PRD §3.7: "Installation windows are half-open intervals — the `start_date`
        counts, the `end_date` does not." and "a calendar gap of exactly
        `mobilization_buffer_days` between two windows is allowed, while any shorter gap
        conflicts and is rejected with `ERR_CREW_WINDOW_CONFLICT`."
        With the default buffer of two, a window starting 2026-09-12 after one ending
        2026-09-10 (exclusive) leaves exactly the buffered gap and is allowed.

        Design: Difficulty/resource_temporal_overlap/crew_window_buffered_halfopen_exclusion
        """
        world = setup_register_world(
            section_number="033000", lead_time_days=5, default_need_date="2026-09-01"
        )
        submittal = world["submittals"][0]
        crew = world["subcontractor"]["id"]
        create_activity(world["project"]["id"], submittal["id"], crew, "2026-09-01", "2026-09-10")

        activity_b = create_activity(
            world["project"]["id"], submittal["id"], crew, "2026-09-12", "2026-09-20"
        )
        assert activity_b["status"] == "PLANNED", (
            "a gap of exactly mobilization_buffer_days (2) is allowed"
        )

    def test_gap_below_mobilization_buffer_conflicts(self, api):
        """PRD §3.7: "A candidate window conflicts with any other activity of the same
        `subcontractor_id` — excluding `CANCELLED` activities and excluding the candidate
        itself — when the candidate's start falls before the other window's end extended
        by the project's `mobilization_buffer_days` calendar days, and the other window's
        start falls before the candidate's end extended by the same buffer."
        One day earlier than the buffered gap (2026-09-11 after the 2026-09-10 exclusive
        end) leaves a one-day gap, below the buffer of two.

        Design: Difficulty/resource_temporal_overlap/crew_window_buffered_halfopen_exclusion
        """
        world = setup_register_world(
            section_number="033000", lead_time_days=5, default_need_date="2026-09-01"
        )
        submittal = world["submittals"][0]
        crew = world["subcontractor"]["id"]
        create_activity(world["project"]["id"], submittal["id"], crew, "2026-09-01", "2026-09-10")

        resp = api.create_installation_activity(
            world["project"]["id"],
            {
                "submittal_id": submittal["id"],
                "subcontractor_id": crew,
                "start_date": "2026-09-11",
                "end_date": "2026-09-15",
            },
            PE,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_CONFLICT, 409)


class TestReleaseRequiresSubmittalReleased:
    def test_release_blocked_while_submittal_registered(self, api):
        """PRD §3.7: "The referential gates follow: the governing submittal's
        `review_status` must be `RELEASED`, `DISTRIBUTED`, or `CLOSED` (otherwise
        `ERR_SUBMITTAL_NOT_RELEASED`)"

        Design: Difficulty/cross_entity_state_dependency/activity_release_requires_submittal_released
        """
        world = setup_register_world(
            section_number="033000", lead_time_days=5, default_need_date="2026-09-01"
        )
        submittal = world["submittals"][0]
        activity = create_activity(
            world["project"]["id"],
            submittal["id"],
            world["subcontractor"]["id"],
            "2026-09-01",
            "2026-09-10",
        )
        assert get_submittal_status(api, submittal["id"]) == "REGISTERED"
        resp = api.release_installation_activity(activity["id"], PM)
        validate_error(resp, ApiErrorId.ERR_SUBMITTAL_NOT_RELEASED, 409)

    def test_release_succeeds_after_submittal_released(self, api):
        """PRD §3.7: "the governing submittal's `review_status` must be `RELEASED`,
        `DISTRIBUTED`, or `CLOSED` (otherwise `ERR_SUBMITTAL_NOT_RELEASED`)"
        Once the submittal completes its review cycle and is released for construction,
        the same activity release succeeds.

        Design: Difficulty/cross_entity_state_dependency/activity_release_requires_submittal_released
        """
        world = setup_released_submittal(
            need_date="2026-09-01", lead_time_days=5, section_number="033000"
        )
        activity = create_activity(
            world["project"]["id"],
            world["submittal"]["id"],
            world["subcontractor"]["id"],
            "2026-09-01",
            "2026-09-10",
        )
        released = validate_success(
            api.release_installation_activity(activity["id"], PM), 200
        )
        assert released["status"] == "RELEASED"


class TestReferentialReleaseGates:
    def test_open_rfi_blocks_release_referential_alone(self, api):
        """PRD §3.7: "no RFI referencing that submittal may be `OPEN` or `ROUTED`
        (otherwise `ERR_OPEN_RFI_BLOCKS_RELEASE`)"
        With no crew conflict present and the submittal released, a ROUTED RFI alone
        blocks the activity release.

        Design: Corner/state_machines/open_rfi_blocks_release_referential_alone
        """
        world = setup_released_submittal(
            need_date="2026-09-01", lead_time_days=5, section_number="033000"
        )
        submittal = world["submittal"]
        activity = create_activity(
            world["project"]["id"],
            submittal["id"],
            world["subcontractor"]["id"],
            "2026-09-01",
            "2026-09-10",
        )
        rfi = create_rfi(
            world["project"]["id"], subject="open", submittal_id=submittal["id"]
        )
        route_rfi(rfi["id"], world["reviewer"]["id"])

        resp = api.release_installation_activity(activity["id"], PM)
        validate_error(resp, ApiErrorId.ERR_OPEN_RFI_BLOCKS_RELEASE, 409)

    def test_long_lead_not_delivered_blocks_release(self, api):
        """PRD §3.7: "when the governing submittal is long-lead, its linked LongLeadItem
        must stand at `DELIVERED` (otherwise `ERR_LONG_LEAD_NOT_DELIVERED`)."
        PRD §3.4: "Procurement advances along a fixed single-file chain — `IDENTIFIED` →
        `QUOTED` → `PO_ISSUED` → `IN_PRODUCTION` → `SHIPPED` → `DELIVERED` — one step at
        a time."
        The submittal is RELEASED and RFI-free, yet the activity stays blocked until the
        item is delivered; delivery unblocks it.

        Design: Corner/state_machines/long_lead_not_delivered_blocks_release
        """
        world = setup_approved_submittal(
            need_date="2026-10-30",
            lead_time_days=35,
            review_days=10,
            section_number="051200",
        )
        submittal = world["submittal"]
        validate_success(api.release_submittal_for_construction(submittal["id"], PE), 200)
        activity = create_activity(
            world["project"]["id"],
            submittal["id"],
            world["subcontractor"]["id"],
            "2026-11-02",
            "2026-11-10",
        )
        lli = lli_of_submittal(submittal["id"])
        assert lli is not None and lli["status"] == "IDENTIFIED"

        resp = api.release_installation_activity(activity["id"], PM)
        validate_error(resp, ApiErrorId.ERR_LONG_LEAD_NOT_DELIVERED, 409)

        for to_status, actual_date in [
            ("QUOTED", "2026-08-02"),
            ("PO_ISSUED", "2026-08-03"),
            ("IN_PRODUCTION", "2026-08-10"),
            ("SHIPPED", "2026-10-20"),
            ("DELIVERED", "2026-10-28"),
        ]:
            advanced = validate_success(
                api.advance_long_lead_item(
                    lli["id"], {"to_status": to_status, "actual_date": actual_date}, PE
                ),
                200,
            )
        assert advanced["status"] == "DELIVERED"

        released = validate_success(
            api.release_installation_activity(activity["id"], PM), 200
        )
        assert released["status"] == "RELEASED"


class TestTemporalBeforeReferentialPriority:
    def _cascade_collision_world(self, api):
        """S1 (long-lead, REGISTERED) holds activity A [2026-09-01, 2026-09-10); S2
        (approved + released-for-construction) holds activity B [2026-09-12, 2026-09-20)
        with a gap of exactly the buffer at creation. An accepted schedule impact of 7
        days on S1 then shifts A into B's buffer zone, and an RFI on S2 is left ROUTED.
        """
        project = create_active_project("Prio2", initial_contingency_cents=2_000_000)
        subcontractor = add_subcontractor(
            project["id"], company_name="SteelFab", trade="structural steel"
        )
        reviewer = add_reviewer(project["id"], display_name="Arch One", discipline="ARCH")
        sec_a = add_spec_section(
            project["id"],
            "051200",
            lead_time_days=35,
            review_days=10,
            default_need_date="2026-08-15",
            responsible_subcontractor_id=subcontractor["id"],
            required_submittal_kinds=["SHOP_DRAWINGS"],
        )
        sec_b = add_spec_section(
            project["id"],
            "033000",
            lead_time_days=5,
            review_days=5,
            default_need_date="2026-09-01",
            responsible_subcontractor_id=subcontractor["id"],
            required_submittal_kinds=["PRODUCT_DATA"],
        )
        activate_spec_section(sec_a["id"])
        activate_spec_section(sec_b["id"])
        s1 = submittals_of_section(project["id"], "051200")[0]
        s2 = submittals_of_section(project["id"], "033000")[0]

        rev = submit_revision(s2["id"], subcontractor["id"], "doc://s2r0")
        route_revision(rev["id"], reviewer["id"])
        return_revision(rev["id"], reviewer["id"], "A")
        validate_success(api.release_submittal_for_construction(s2["id"], PE), 200)

        act_a = create_activity(
            project["id"], s1["id"], subcontractor["id"], "2026-09-01", "2026-09-10"
        )
        act_b = create_activity(
            project["id"], s2["id"], subcontractor["id"], "2026-09-12", "2026-09-20"
        )

        rfi_shift = create_rfi(
            project["id"], subject="Embed shift", submittal_id=s1["id"]
        )
        route_rfi(rfi_shift["id"], reviewer["id"])
        answer_rfi(
            rfi_shift["id"],
            reviewer["id"],
            answer_text="shift",
            cost_impact_flag=True,
            schedule_impact_flag=True,
            estimated_cost_cents=100_000,
            estimated_schedule_days=7,
        )
        assessment = assessment_for_rfi(project["id"], rfi_shift["id"])
        price_assessment(assessment["id"], 100_000)
        accept_assessment(assessment["id"])

        rfi_open = create_rfi(project["id"], subject="Open q on S2", submittal_id=s2["id"])
        route_rfi(rfi_open["id"], reviewer["id"])
        return {
            "project": project,
            "subcontractor": subcontractor,
            "reviewer": reviewer,
            "s1": s1,
            "s2": s2,
            "act_a": act_a,
            "act_b": act_b,
        }

    def test_release_conflict_and_open_rfi_returns_temporal_error(self, api):
        """PRD §3.7: "Releasing an activity to work is a `ProjectManager` action with a
        strict gate order: state first, then temporal, then referential. The project must
        be `ACTIVE` (`ERR_PROJECT_NOT_ACTIVE`) and the activity must be `PLANNED`
        (`ERR_ACTIVITY_NOT_PLANNED`). The crew-window conflict check then re-runs against
        the subcontractor's current committed windows (`ERR_CREW_WINDOW_CONFLICT`). The
        referential gates follow: the governing submittal's `review_status` must be
        `RELEASED`, `DISTRIBUTED`, or `CLOSED` (otherwise `ERR_SUBMITTAL_NOT_RELEASED`);
        no RFI referencing that submittal may be `OPEN` or `ROUTED` (otherwise
        `ERR_OPEN_RFI_BLOCKS_RELEASE`)"
        Activity B both collides with the cascade-shifted activity A AND has a ROUTED
        RFI on its submittal; the temporal error is returned.

        Design: Difficulty/priority_pair_validation_conflict/release_temporal_vs_referential_priority
        """
        world = self._cascade_collision_world(api)
        resp = api.release_installation_activity(world["act_b"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_CONFLICT, 409)
        assert get_activity(world["act_b"]["id"])["status"] == "PLANNED", (
            "a rejected release applies no side effects"
        )

    def test_cascade_shifted_window_collides_at_release(self, api):
        """PRD §3.6: "Every `PLANNED` InstallationActivity whose `submittal_id` matches
        the RFI's linked submittal shifts later by d calendar days — both `start_date`
        and `end_date` move, and each activity's `shift_applied_days` accumulates d."
        PRD §3.7: "Creation already enforces the crew-window conflict rule, and release
        enforces it again."
        Activity A was shifted +7 days into [2026-09-08, 2026-09-17) by the accepted
        impact, which is what activity B collides with at release time.

        Design: Difficulty/priority_pair_validation_conflict/release_temporal_vs_referential_priority
        """
        world = self._cascade_collision_world(api)
        act_a = get_activity(world["act_a"]["id"])
        assert act_a["start_date"] == "2026-09-08"
        assert act_a["end_date"] == "2026-09-17"
        assert act_a["shift_applied_days"] == 7

        resp = api.release_installation_activity(world["act_b"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_CONFLICT, 409)


def get_submittal_status(api, submittal_id) -> str:
    from test_helpers import get_submittal

    return get_submittal(submittal_id)["review_status"]

"""Closure execution and the closure cascade into quiet zones, work orders, and
project creation gating (PRD §3.4, §3.5)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_accepted_review,
    create_assignment,
    create_draft_zone,
    create_effective_zone,
    create_executed_agreement,
    create_locality,
    create_program,
    create_project,
    create_team,
    create_upgrade_project_payload,
    create_work_order,
    get_success_data,
    make_local_authority_headers,
    setup_closure_pending_crossing,
    setup_locality_and_crossing,
    setup_locality_team_crossing,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
RAILROAD = TEST_USERS["railroad_headers"]


class TestConfirmClosureStateGate:
    def test_confirm_closure_on_active_crossing_rejected(self, api, admin_headers):
        """PRD §3.5: "A `ProgramAdministrator` confirming closure on a
        `CLOSURE_PENDING` crossing (any other state: `ERR_INVALID_STATE_TRANSITION`)
        moves it to terminal `CLOSED` and fires the closure cascade."

        Design: Corner/state_machines/confirm_closure_from_active_invalid
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-020001"}
        )
        resp = api.confirm_crossing_closure(crossing["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
        after = get_success_data(api.get_crossing(crossing["id"], ADMIN))
        assert after["status"] == "ACTIVE"


class TestProjectCreationRequiresActiveCrossing:
    def test_project_rejected_on_closure_pending_crossing(self, api, admin_headers):
        """PRD §3.4: "The crossing must be `ACTIVE` (else
        `ERR_CROSSING_NOT_ACTIVE`)". PRD §3.5: "a `ProgramAdministrator` moves
        `LOCALITY_RATIFIED` → `EXECUTED`, which flips the crossing `ACTIVE` →
        `CLOSURE_PENDING` and increments the crossing's `version`."

        Design: Difficulty/cross_entity_state_dependency/project_create_requires_active_crossing
        """
        locality, crossing, _agreement = setup_closure_pending_crossing(
            {"dot_crossing_number": "DOT-700001"}
        )
        assert crossing["status"] == "CLOSURE_PENDING"
        prog = create_program(
            fiscal_year=2033,
            apportionment_cents=1_000_000,
            allocation_method="WATERFALL_BY_RANK",
        )
        resp = api.create_upgrade_project(
            create_upgrade_project_payload(
                crossing_id=crossing["id"],
                program_id=prog["id"],
                target_device_class="FOUR_QUADRANT_GATES",
                estimated_cost_cents=300_000,
            ),
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_CROSSING_NOT_ACTIVE, expected_status=409)

    def test_project_creation_on_active_crossing_succeeds(self, api, admin_headers):
        """PRD §3.4: "The crossing must be `ACTIVE` (else
        `ERR_CROSSING_NOT_ACTIVE`), the target class must differ from the
        crossing's current `warning_device_class` (else `ERR_INVALID_REQUEST`) ...
        A new project is `PROPOSED`, with `priority_score` still `null`."

        Design: Difficulty/cross_entity_state_dependency/project_create_requires_active_crossing
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-700002"}
        )
        prog = create_program(fiscal_year=2036, apportionment_cents=1_000_000)
        pj = create_project(crossing["id"], prog["id"], estimated_cost_cents=300_000)
        assert pj["status"] == "PROPOSED"
        assert pj["priority_score"] is None


class TestClosureCascadeSuspendsQuietZone:
    def _build_closure_scenario(self, api):
        """Locality + team + crossing CD (hazard 22.00) with ACCEPTED review,
        EFFECTIVE zone holding CD, a PLANNED railroad work order on CD, and an
        EXECUTED closure agreement moving CD to CLOSURE_PENDING."""
        locality = create_locality(locality_name="Closeville")
        team = create_team(team_name="Team Beta")
        from test_helpers import create_crossing

        cd = create_crossing(
            locality["id"],
            dot_crossing_number="DOT-400301",
            annual_train_count=730,
            train_speed_max_mph=25,
            aadt=5000,
            school_bus_count=20,
            sight_distance_rating=4,
            warning_device_class="GATES",
        )
        # Exposure 10.00 -> (10*1.20 + 20*0.5) * 1.00 = 22.00; pre-SSM 22 <= 40.
        assert cd["hazard_score"] == pytest.approx(22.00, abs=1e-9)
        create_accepted_review(cd["id"], team["id"], recommendations=("CLOSE_CROSSING",))
        zone, members = create_effective_zone(
            locality["id"], [{"crossing_id": cd["id"]}]
        )
        create_assignment(cd["id"], category="SIGNAL", responsible_party="RAILROAD")
        wo = create_work_order(
            cd["id"],
            RAILROAD,
            window_start="2026-09-01T08:00:00Z",
            window_end="2026-09-01T12:00:00Z",
            fouls_track=False,
        )
        agreement = create_executed_agreement(cd["id"], locality["id"])
        cd_fresh = get_success_data(api.get_crossing(cd["id"], ADMIN))
        assert cd_fresh["status"] == "CLOSURE_PENDING"
        return locality, cd, zone, members[0], wo, agreement

    def test_confirm_closure_cascades_to_zone_membership_and_work_orders(
        self, api, admin_headers
    ):
        """PRD §3.5: "A `ProgramAdministrator` confirming closure on a
        `CLOSURE_PENDING` crossing ... moves it to terminal `CLOSED` and fires the
        closure cascade. Every zone membership row for the crossing flips from
        `MEMBER` to `REMOVED`. Each affected quiet zone application then
        recomputes its `riwh_post_ssm` over its remaining `MEMBER` rows using
        their live hazard scores, and if the application is `EFFECTIVE` and either
        no `MEMBER` rows remain or the recomputed value exceeds the national risk
        threshold, it moves `EFFECTIVE` → `SUSPENDED` automatically. In parallel,
        the crossing's non-terminal work orders — those in `PLANNED` or
        `FLAGGING_CONFIRMED` — are cancelled, and its preemption interconnections
        in `DRAFT`, `TIMING_VERIFIED`, or `COMMISSIONED` are decommissioned."

        Design: Difficulty/transitive_cascade/crossing_closure_cascade_suspends_quiet_zone
        """
        locality, cd, zone, member, wo, _ = self._build_closure_scenario(api)
        assert zone["status"] == "EFFECTIVE"

        closed = get_success_data(api.confirm_crossing_closure(cd["id"], ADMIN))
        assert closed["status"] == "CLOSED"

        member_after = get_success_data(api.get_quiet_zone_crossing(member["id"], ADMIN))
        assert member_after["membership_status"] == "REMOVED"

        zone_after = get_success_data(api.get_quiet_zone_application(zone["id"], ADMIN))
        assert zone_after["status"] == "SUSPENDED", (
            "no MEMBER rows remain after the closure cascade"
        )

        wo_after = get_success_data(api.get_maintenance_work_order(wo["id"], ADMIN))
        assert wo_after["status"] == "CANCELLED"

    def test_executed_agreement_moves_crossing_to_closure_pending_and_bumps_version(
        self, api, admin_headers
    ):
        """PRD §3.5: "Execution is the final, administrative act: a
        `ProgramAdministrator` moves `LOCALITY_RATIFIED` → `EXECUTED`, which flips
        the crossing `ACTIVE` → `CLOSURE_PENDING` and increments the crossing's
        `version`."

        Design: Difficulty/transitive_cascade/crossing_closure_cascade_suspends_quiet_zone
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-400302"}
        )
        before_version = crossing["version"]
        agreement = create_executed_agreement(crossing["id"], locality["id"])
        assert agreement["status"] == "EXECUTED"
        after = get_success_data(api.get_crossing(crossing["id"], ADMIN))
        assert after["status"] == "CLOSURE_PENDING"
        assert after["version"] == before_version + 1

"""Role permissions, peer-role reads and the same-person prohibitions.

The eight pre-opening roles are peers over a partitioned write surface: every
read endpoint accepts all eight, while each write accepts only the role or
roles that own it. On top of that partition sit three same-person
prohibitions that compare acting operator identifiers rather than roles.
"""

from typing import Any, Dict

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import assert_committed_is_authority
from test_helpers.constants import (
    CODE_CONSTRUCTION_COMPLETE,
    ROLE_CONSTRUCTION_MANAGER,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_QUALITY_INSPECTOR,
)
from test_helpers.test_users import (
    ALL_ROLE_HEADERS,
    BASELINING_DIRECTOR,
    COMMERCIAL_DIRECTOR,
    CONSTRUCTION_MANAGER,
    LICENSING_COORDINATOR,
    NO_AUTH_HEADERS,
    PROCUREMENT_MANAGER,
    PROGRAM_DIRECTOR,
    QUALITY_INSPECTOR,
    SYSTEMS_INTEGRATOR,
    TALENT_MANAGER,
    TEST_RUNNER_INTEGRATOR,
    USER_ID_QUALITY_INSPECTOR,
    headers_for,
)

# ─── File-local setup helpers ─────────────────────────────────────────────────

# The identity that both raises and submits a defect in the duty-separation
# scenario; it holds ConstructionManager on those calls and QualityInspector on
# the later ruling, so only the identifier can be the blocker.
DUAL_HATTED_USER_ID = "u-dual-9"
DUAL_HATTED_SUBMITTER = headers_for(ROLE_CONSTRUCTION_MANAGER, DUAL_HATTED_USER_ID)
DUAL_HATTED_INSPECTOR = headers_for(ROLE_QUALITY_INSPECTOR, DUAL_HATTED_USER_ID)
OTHER_INSPECTOR = headers_for(ROLE_QUALITY_INSPECTOR, "qi-other-1")
AUTHORIZING_DIRECTOR = headers_for(ROLE_PROGRAM_DIRECTOR, "pd-authorizer-2")

# A role name outside the eight declared ones.
UNDECLARED_ROLE_HEADERS = headers_for("HotelOwner", "ho-1")


def _construction_complete(api) -> Dict[str, Any]:
    """A program driven to CONSTRUCTION_COMPLETE over one 30-day milestone.

    The milestone is started at clock 2026-09-01 and completed at clock
    2026-10-01, so the committed projection lands on 2026-10-15 and the slip
    against the 2027-05-01 target is zero.
    """
    return fixtures.construction_complete_program(
        api, finish_iso="2026-10-01T00:00:00Z", duration_days=30
    )


def _minor_item_ready_for_verification(
    api, built: Dict[str, Any], submitter=CONSTRUCTION_MANAGER
) -> Dict[str, Any]:
    """One MINOR defect raised and submitted for verification by ``submitter``."""
    item = fixtures.make_punch_item(
        api,
        built["program"]["id"],
        headers=submitter,
        milestone_id=built["milestones"][CODE_CONSTRUCTION_COMPLETE]["id"],
        description="Corridor carpet seam lifting",
        severity="MINOR",
    )
    return fixtures.submit_for_verification(api, item["id"], headers=submitter)


# ─── Denied-write cases for the unauthorized-role sweep ───────────────────────


def _reach_for_program_create(api, ctx):
    return api.create_program(
        factories.program_payload(
            property_name="Rogue Annex",
            brand_code="RGA",
            room_count=40,
            storage_capacity_pallets=10,
            room_night_ceiling=50,
            contingency_liability_cap_cents=1000000,
        ),
        CONSTRUCTION_MANAGER,
    )


def _reach_for_budget_line_create(api, ctx):
    return api.create_budget_line(
        factories.budget_line_payload(
            ctx["program"]["id"], category="SETUP", authorized_cents=1000000
        ),
        PROCUREMENT_MANAGER,
    )


def _reach_for_punch_verify(api, ctx):
    return api.verify_punch_item(
        ctx["punch_item"]["id"], factories.punch_verify_payload("VERIFY"), TALENT_MANAGER
    )


def _reach_for_open_booking(api, ctx):
    return api.open_booking(ctx["program"]["id"], LICENSING_COORDINATOR)


DENIED_WRITES = [
    pytest.param(_reach_for_program_create, id="ConstructionManager-creates-program"),
    pytest.param(_reach_for_budget_line_create, id="ProcurementManager-authorizes-budget"),
    pytest.param(_reach_for_punch_verify, id="TalentManager-verifies-defect"),
    pytest.param(_reach_for_open_booking, id="LicensingCoordinator-opens-booking"),
]


class TestExclusiveWrites:
    def test_every_role_can_run_the_write_it_exclusively_owns(self, api, clock_at_default):
        """All eight peer roles act on one program in a single run and each one's
        own write is accepted: the construction manager drives the milestone, the
        director baselines and authorizes budget, the coordinator files the permit,
        the integrator logs evidence, the talent manager offers, the procurement
        manager commits, the commercial director opens booking and the inspector
        closes the defect.

        They are peers, not a hierarchy: each owns a disjoint slice of the resource model.

        Design: Corner/rbac/each_role_can_run_the_operation_it_exclusively_owns
        """
        program = validate_success(
            api.create_program(factories.program_payload(), PROGRAM_DIRECTOR), 201
        )
        milestone = validate_success(
            api.create_milestone(
                factories.milestone_payload(
                    program["id"],
                    code="CONSTRUCTION_COMPLETE",
                    name="Construction complete",
                    duration_days=30,
                    planned_start_date="2026-09-01",
                ),
                CONSTRUCTION_MANAGER,
            ),
            201,
        )
        validate_success(api.baseline_schedule(program["id"], BASELINING_DIRECTOR), 200)
        validate_success(api.start_milestone(milestone["id"], CONSTRUCTION_MANAGER), 200)
        fixtures.set_clock(api, "2026-10-01T00:00:00Z")
        validate_success(api.complete_milestone(milestone["id"], CONSTRUCTION_MANAGER), 200)

        permit = validate_success(
            api.create_permit_application(
                factories.permit_payload(
                    program["id"], milestone["id"], permit_type="ELEVATOR", review_days=21
                ),
                PROGRAM_DIRECTOR,
            ),
            201,
        )
        system = validate_success(
            api.create_system_implementation(
                factories.system_payload(program["id"], system_type="PMS", is_required=True),
                SYSTEMS_INTEGRATOR,
            ),
            201,
        )
        plan = validate_success(
            api.create_hiring_plan(
                factories.hiring_plan_payload(
                    program["id"],
                    department="ROOMS",
                    headcount_target=2,
                    wave_start_date="2026-09-10",
                ),
                TALENT_MANAGER,
            ),
            201,
        )
        item = validate_success(
            api.create_punch_item(
                factories.punch_item_payload(
                    program["id"],
                    milestone_id=milestone["id"],
                    description="Corridor carpet seam lifting",
                    severity="MINOR",
                ),
                CONSTRUCTION_MANAGER,
            ),
            201,
        )
        validate_success(api.submit_punch_verification(item["id"], CONSTRUCTION_MANAGER), 200)

        # ProgramDirector authorizes the pre-opening budget.
        line = validate_success(
            api.create_budget_line(
                factories.budget_line_payload(
                    program["id"], category="SETUP", authorized_cents=1000000
                ),
                PROGRAM_DIRECTOR,
            ),
            201,
        )

        # ProcurementManager commits the shipment against that line.
        order = validate_success(
            api.create_ose_order(
                factories.ose_order_payload(
                    program["id"],
                    line["id"],
                    line["version"],
                    description="Guest room linen",
                    amount_cents=400000,
                    pallet_count=5,
                    delivery_window_start="2026-10-05",
                    delivery_window_end="2026-10-20",
                ),
                PROCUREMENT_MANAGER,
            ),
            201,
        )
        assert order["state"] == "COMMITTED"

        # LicensingCoordinator files the mandatory permit, which puts the
        # delivery dimension into LICENSING.
        submitted = validate_success(
            api.submit_permit_application(permit["id"], LICENSING_COORDINATOR), 200
        )
        assert submitted["state"] == "SUBMITTED"
        assert fixtures.read_program(api, program["id"])["schedule_state"] == "LICENSING"

        # SystemsIntegrator appends the test evidence.
        run = validate_success(
            api.create_test_run(
                system["id"],
                factories.test_run_payload("2026-10-01T09:00:00Z", 40, 40),
                TEST_RUNNER_INTEGRATOR,
            ),
            201,
        )
        assert run["result"] == "PASSED"

        # TalentManager extends the offer.
        hire = validate_success(
            api.create_hire(
                factories.hire_payload(
                    plan["id"],
                    full_name="A. Keeper",
                    hourly_rate_cents=2500,
                    scheduled_hours_per_day=8,
                    start_date="2026-10-15",
                ),
                TALENT_MANAGER,
            ),
            201,
        )
        assert hire["state"] == "OFFERED"

        # CommercialDirector opens the reservation ramp.
        opened = validate_success(api.open_booking(program["id"], COMMERCIAL_DIRECTOR), 200)
        assert opened["commercial_state"] == "BOOKING_OPEN"

        # QualityInspector is the independent closure authority.
        verified = validate_success(
            api.verify_punch_item(
                item["id"], factories.punch_verify_payload("VERIFY"), QUALITY_INSPECTOR
            ),
            200,
        )
        assert verified["state"] == "VERIFIED"
        assert verified["verified_by_user_id"] == USER_ID_QUALITY_INSPECTOR


class TestSharedScheduleWrites:
    def test_both_schedule_owners_write_milestones_edges_and_recomputations(
        self, api, clock_at_default
    ):
        """The milestone network is co-owned: the program director adds one
        milestone, the construction manager adds the next, either may wire the
        edge between them, and the construction manager can re-run the critical
        path without touching the delivery dimension.

        A separate recomputation capability, available to both the `ProgramDirector` and the `ConstructionManager`, re-runs the same schedule arithmetic in both variants **without** changing the delivery dimension, refreshing the floats, the slip, the posture, the contingency liability and both cost-at-completion figures, and likewise incrementing the program's `version` by one.

        Design: Corner/rbac/program_director_and_construction_manager_share_the_schedule_writes
        """
        program = validate_success(
            api.create_program(factories.program_payload(), PROGRAM_DIRECTOR), 201
        )
        first = validate_success(
            api.create_milestone(
                factories.milestone_payload(
                    program["id"],
                    code="STRUCTURE_TOPPED_OUT",
                    name="Structure topped out",
                    duration_days=20,
                    planned_start_date="2026-09-01",
                ),
                PROGRAM_DIRECTOR,
            ),
            201,
        )
        second = validate_success(
            api.create_milestone(
                factories.milestone_payload(
                    program["id"],
                    code="INTERIOR_FIT_OUT",
                    name="Interior fit out",
                    duration_days=10,
                    planned_start_date="2026-09-21",
                ),
                CONSTRUCTION_MANAGER,
            ),
            201,
        )
        validate_success(
            api.create_dependency(
                factories.dependency_payload(first["id"], second["id"]), PROGRAM_DIRECTOR
            ),
            201,
        )
        validate_success(api.baseline_schedule(program["id"], BASELINING_DIRECTOR), 200)

        recomputed = validate_success(
            api.recompute_schedule(program["id"], CONSTRUCTION_MANAGER), 200
        )
        assert recomputed["schedule_state"] == "BASELINED"
        assert recomputed["projected_opening_date_committed"] == "2026-10-15"
        assert_committed_is_authority(recomputed)


class TestUnauthorizedRole:
    @pytest.mark.parametrize("reach_for_write", DENIED_WRITES)
    def test_a_peer_role_reaching_for_a_write_it_does_not_own_is_refused(
        self, api, clock_at_default, reach_for_write
    ):
        """Four peer roles each reach for a write owned by someone else while
        carrying an otherwise perfectly valid payload, and each is turned away
        on the role table alone.

        If both headers are well formed but the named role is not listed among the authorized roles for the endpoint being called, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

        Design: Corner/rbac/a_role_cannot_reach_another_roles_exclusive_write_and_gets_role_not_permitted
        """
        built = _construction_complete(api)
        built["punch_item"] = _minor_item_ready_for_verification(api, built)

        validate_error(
            reach_for_write(api, built), api_errors.ERR_ROLE_NOT_PERMITTED, 403
        )

    def test_the_refused_writes_leave_no_trace_behind_them(self, api, clock_at_default):
        """After all four denials the system holds exactly the one program that
        was legitimately created, no budget line at all, the defect still waiting
        on verification and the commercial dimension still closed.

        If both headers are well formed but the named role is not listed among the authorized roles for the endpoint being called, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

        Design: Corner/rbac/a_role_cannot_reach_another_roles_exclusive_write_and_gets_role_not_permitted
        """
        built = _construction_complete(api)
        built["punch_item"] = _minor_item_ready_for_verification(api, built)

        for reach_for_write in (
            _reach_for_program_create,
            _reach_for_budget_line_create,
            _reach_for_punch_verify,
            _reach_for_open_booking,
        ):
            validate_error(
                reach_for_write(api, built), api_errors.ERR_ROLE_NOT_PERMITTED, 403
            )

        programs, programs_meta = validate_paginated(
            api.list_programs(PROGRAM_DIRECTOR)
        )
        assert programs_meta["total_count"] == 1
        assert [record["property_name"] for record in programs] == ["Cobalt Bay Hotel"]

        _, lines_meta = validate_paginated(
            api.list_budget_lines(built["program"]["id"], PROGRAM_DIRECTOR)
        )
        assert lines_meta["total_count"] == 0

        item = validate_success(
            api.get_punch_item(built["punch_item"]["id"], QUALITY_INSPECTOR)
        )
        assert item["state"] == "READY_FOR_VERIFICATION"

        program = validate_success(
            api.get_program(built["program"]["id"], PROGRAM_DIRECTOR)
        )
        assert program["commercial_state"] == "BOOKING_CLOSED"


class TestUnauthenticated:
    def test_a_write_without_identity_headers_is_unauthenticated_and_writes_nothing(
        self, api, clock_at_default
    ):
        """A milestone create that carries no identity headers at all never
        reaches the role table or the payload rules: it is unauthenticated, and
        the program's network stays empty.

        If either header is absent, or if `X-User-Role` is not one of the eight declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

        Design: Corner/rbac/a_request_without_role_and_user_headers_returns_unauthenticated_401
        """
        program = fixtures.make_program(api)

        response = api.create_milestone(
            factories.milestone_payload(
                program["id"],
                code="STRUCTURE_TOPPED_OUT",
                name="Structure topped out",
                duration_days=20,
                planned_start_date="2026-09-01",
            ),
            NO_AUTH_HEADERS,
        )
        validate_error(response, api_errors.ERR_UNAUTHENTICATED, 401)

        _, meta = validate_paginated(
            api.list_milestones(PROGRAM_DIRECTOR, {"program_id": program["id"]})
        )
        assert meta["total_count"] == 0

    def test_an_undeclared_role_name_is_unauthenticated_even_on_an_open_read(
        self, api, clock_at_default
    ):
        """A caller naming a role outside the eight declared ones is refused on
        a program read that every declared role may call, so the rejection is
        authentication rather than authorization.

        If either header is absent, or if `X-User-Role` is not one of the eight declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

        Design: Corner/rbac/a_request_without_role_and_user_headers_returns_unauthenticated_401
        """
        program = fixtures.make_program(api)

        response = api.get_program(program["id"], UNDECLARED_ROLE_HEADERS)
        validate_error(response, api_errors.ERR_UNAUTHENTICATED, 401)


class TestPunchItemDutySeparation:
    @pytest.mark.parametrize("decision", ["VERIFY", "REJECT"])
    def test_the_submitter_cannot_rule_on_their_own_defect(
        self, api, clock_at_default, decision
    ):
        """One operator raises a defect and submits it for verification wearing
        the construction hat, then tries to rule on it wearing the inspector
        hat. Both the verification and the rejection branch are refused, and the
        rejection counter never moves.

        A punch-list defect may not be verified — or rejected — by the operator recorded in `submitted_by_user_id` for its current submission.

        Design: Corner/rbac/the_same_user_cannot_submit_and_verify_the_same_punch_item
        """
        built = _construction_complete(api)
        item = _minor_item_ready_for_verification(api, built, submitter=DUAL_HATTED_SUBMITTER)
        assert item["submitted_by_user_id"] == DUAL_HATTED_USER_ID

        response = api.verify_punch_item(
            item["id"], factories.punch_verify_payload(decision), DUAL_HATTED_INSPECTOR
        )
        validate_error(response, api_errors.ERR_SEGREGATION_OF_DUTIES, 403)

        unchanged = validate_success(api.get_punch_item(item["id"], QUALITY_INSPECTOR))
        assert unchanged["state"] == "READY_FOR_VERIFICATION"
        assert unchanged["rejection_count"] == 0

    def test_a_second_inspector_verifies_the_same_defect_successfully(
        self, api, clock_at_default
    ):
        """The blocker is the identity and not the role: once a different
        inspector rules on the very same defect the verification lands and the
        acting operator is recorded as the verifier.

        Three approvals in this system must be performed by a different operator than the one who set them up, and all three compare `X-User-ID` values only.

        Design: Corner/rbac/the_same_user_cannot_submit_and_verify_the_same_punch_item
        """
        built = _construction_complete(api)
        item = _minor_item_ready_for_verification(api, built, submitter=DUAL_HATTED_SUBMITTER)

        validate_error(
            api.verify_punch_item(
                item["id"], factories.punch_verify_payload("VERIFY"), DUAL_HATTED_INSPECTOR
            ),
            api_errors.ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        verified = validate_success(
            api.verify_punch_item(
                item["id"], factories.punch_verify_payload("VERIFY"), OTHER_INSPECTOR
            ),
            200,
        )
        assert verified["state"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "qi-other-1"
        assert verified["blocks_certificate_of_occupancy"] is False


class TestSoftOpeningDutySeparation:
    def test_the_baselining_director_cannot_authorize_the_soft_opening(
        self, api, clock_at_default
    ):
        """Every other soft-opening gate is satisfied — four mandatory permits
        issued, no open critical defect, no required system outstanding, the one
        department at its onboarding threshold and the date inside the window —
        so the only obstacle left is that the director who froze the plan of
        record is also the one signing the opening off.

        And the soft opening may not be authorized by the operator recorded in `baselined_by_user_id`, that is, by the `ProgramDirector` who baselined the schedule.

        Design: Corner/rbac/the_baselining_director_cannot_authorize_the_soft_opening_they_scheduled
        """
        built = fixtures.soft_opening_ready_program(
            api,
            program_overrides={
                "property_name": "Aurora Summit Hotel",
                "brand_code": "ASH",
                "room_count": 150,
                "target_opening_date": "2027-06-01",
                "storage_capacity_pallets": 60,
                "room_night_ceiling": 300,
                "contingency_liability_cap_cents": 90000000,
                "licensing_buffer_days": 14,
                "slip_tolerance_days": 10,
                "stabilization_window_days": 30,
            },
        )
        program = built["program"]
        assert program["baselined_by_user_id"] == "pd-baseline-1"
        assert program["schedule_state"] == "LICENSING"
        assert program["issued_mandatory_permit_count"] == 4
        assert program["open_critical_punch_count"] == 0
        assert program["required_system_count"] == 0
        assert program["certified_system_count"] == 0
        assert program["hiring_plan_count"] == 1
        assert program["departments_ready_count"] == 1
        assert program["readiness_posture"] != "FROZEN"
        assert program["projected_opening_date_committed"] == "2026-11-14"

        response = api.authorize_soft_opening(
            program["id"], factories.soft_opening_payload("2026-11-10"), BASELINING_DIRECTOR
        )
        validate_error(response, api_errors.ERR_SEGREGATION_OF_DUTIES, 403)

        unchanged = fixtures.read_program(api, program["id"])
        assert unchanged["schedule_state"] == "LICENSING"
        assert unchanged["soft_opening_date"] is None
        assert unchanged["soft_opening_authorized_by_user_id"] is None
        assert unchanged["version"] == program["version"]

    def test_a_second_director_authorizes_the_identical_soft_opening_payload(
        self, api, clock_at_default
    ):
        """A different program director sends the same payload the baselining
        director was refused for, and the delivery dimension advances into the
        soft opening with the acting operator recorded and the program's version
        advanced by one.

        On success `soft_opening_date` and `soft_opening_authorized_by_user_id` are set, the posture computation reruns, and the program's `version` increments by one.

        Design: Corner/rbac/the_baselining_director_cannot_authorize_the_soft_opening_they_scheduled
        """
        built = fixtures.soft_opening_ready_program(
            api,
            program_overrides={
                "property_name": "Aurora Summit Hotel",
                "brand_code": "ASH",
                "room_count": 150,
                "target_opening_date": "2027-06-01",
                "storage_capacity_pallets": 60,
                "room_night_ceiling": 300,
                "contingency_liability_cap_cents": 90000000,
                "licensing_buffer_days": 14,
                "slip_tolerance_days": 10,
                "stabilization_window_days": 30,
            },
        )
        program = built["program"]
        version_before = program["version"]

        validate_error(
            api.authorize_soft_opening(
                program["id"],
                factories.soft_opening_payload("2026-11-10"),
                BASELINING_DIRECTOR,
            ),
            api_errors.ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        authorized = validate_success(
            api.authorize_soft_opening(
                program["id"],
                factories.soft_opening_payload("2026-11-10"),
                AUTHORIZING_DIRECTOR,
            ),
            200,
        )
        assert authorized["schedule_state"] == "SOFT_OPENING"
        assert authorized["soft_opening_date"] == "2026-11-10"
        assert authorized["soft_opening_authorized_by_user_id"] == "pd-authorizer-2"
        assert authorized["version"] == version_before + 1


class TestPeerRoleReads:
    @pytest.mark.parametrize(
        "reader",
        ALL_ROLE_HEADERS,
        ids=[headers["X-User-Role"] for headers in ALL_ROLE_HEADERS],
    )
    def test_every_peer_role_reads_the_same_program_record(
        self, api, clock_at_default, reader
    ):
        """Read access does not follow the write partition: each of the eight
        peer roles sees the same program record, including roles that own no
        schedule write at all.

        Where the endpoint table in §4 records an authorized-role value of *All eight roles*, every one of the eight role names listed above is permitted.

        Design: Corner/rbac/peer_roles_all_read_the_program_but_only_its_owner_writes_it
        """
        built = _construction_complete(api)
        program_id = built["program"]["id"]

        program = validate_success(api.get_program(program_id, reader), 200)
        assert program["schedule_state"] == "CONSTRUCTION_COMPLETE"

        readiness = validate_success(api.get_readiness(program_id, reader), 200)
        assert readiness["projected_opening_date_committed"] == "2026-10-15"

        milestones, meta = validate_paginated(
            api.list_milestones(reader, {"program_id": program_id})
        )
        assert meta["total_count"] == 1
        assert milestones[0]["state"] == "COMPLETE"

    def test_a_reader_that_owns_no_commercial_write_is_refused_on_the_role_table(
        self, api, clock_at_default
    ):
        """The procurement manager can read the program in full yet cannot
        suspend its booking; the refusal cites the role partition rather than
        the commercial-state precondition the call would otherwise trip on,
        because booking was never opened.

        Read endpoints and the logical-clock endpoint are open to all eight; write endpoints are not.

        Design: Corner/rbac/peer_roles_all_read_the_program_but_only_its_owner_writes_it
        """
        built = _construction_complete(api)
        program_id = built["program"]["id"]

        readable = validate_success(api.get_program(program_id, PROCUREMENT_MANAGER), 200)
        assert readable["schedule_state"] == "CONSTRUCTION_COMPLETE"
        assert readable["commercial_state"] == "BOOKING_CLOSED"

        response = api.suspend_booking(
            program_id, PROCUREMENT_MANAGER, {"reason": "peer role attempt"}
        )
        validate_error(response, api_errors.ERR_ROLE_NOT_PERMITTED, 403)

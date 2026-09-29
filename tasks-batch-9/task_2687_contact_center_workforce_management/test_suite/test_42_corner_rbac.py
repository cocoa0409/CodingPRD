"""Role and identity corners: exclusive writes, authentication faults, ownership and maker-checker."""

from prd_bench_local_runner.testing import (
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_partner_ledgers,
    assert_shift_adherence,
    assert_shift_axes,
)
from test_helpers.constants import (
    ADHERENCE_EXCUSED,
    ADHERENCE_OUT_OF_ADHERENCE,
    ALLOCATION_COMMITTED,
    ALLOCATION_PROPOSED,
    BID_STATUS_SUBMITTED,
    BILLING_DELIVERED_ONLY,
    DECISION_APPROVE,
    DECISION_REQUEST_INFO,
    EXCEPTION_STATUS_APPROVED,
    EXCEPTION_STATUS_SUBMITTED,
    POSTURE_OPEN,
    ROLE_CAPACITY_PLANNER,
)
from test_helpers.factories import (
    commit_allocation_payload,
    exception_decision_payload,
    planning_cycle_payload,
    shift_bid_payload,
)
from test_helpers.fixtures import (
    CANONICAL_CLOCK,
    build_partner_week,
    build_published_week,
    file_exception,
    make_agent,
    make_bid_round,
    make_labor_agreement,
    make_outsource_partner,
    make_planning_cycle,
    make_shift_bid,
    make_shift_template,
    open_round,
    propose_allocation,
    read_bid,
    read_exception,
    read_partner,
    read_shift,
    record_observation,
    set_clock,
)
from test_helpers.test_users import (
    ANALYST_HEADERS,
    COACH_ALT_USER_ID,
    COACH_HEADERS,
    COACH_USER_ID,
    INTRADAY_HEADERS,
    PLANNER_HEADERS,
    PLANNER_USER_ID,
    SCHEDULER_HEADERS,
    SOURCING_ALT_USER_ID,
    SOURCING_HEADERS,
    SOURCING_USER_ID,
    make_agent_headers,
    make_coach_headers,
    make_intraday_headers,
    make_partner_rep_headers,
    make_sourcing_headers,
)

UNDECLARED_ROLE = "PayrollClerk"
UNDECLARED_ROLE_USER_ID = "u-payroll-1"
FABRICATED_CYCLE_ID = "00000000-0000-4000-8000-000000000001"


def headers_missing_user_id(role):
    """Identity headers that name a role but omit the acting principal entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id):
    """Identity headers that name a principal but omit the role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


class TestPlanningCycleCreationIsPlannerExclusive:
    """One role opens a cycle; the other declared roles get 403 before body checks."""

    def test_five_other_roles_are_refused_and_create_nothing(self, api):
        """Every non-planner attempt answers 403, even the deliberately malformed one.

        "Once authentication succeeds, the role is matched against the
        authorised-role list of the requested endpoint as given in Section 4; a
        role that does not appear there is refused with `ERR_UNAUTHORIZED` (HTTP
        403)."

        "That order is authentication (`ERR_UNAUTHENTICATED`), then endpoint role
        authorisation (`ERR_UNAUTHORIZED`), then request-body shape
        (`ERR_VALIDATION`, HTTP 422 — required fields present, correct types, enum
        members recognised, numeric ranges and array lengths as specified in
        Section 3)"

        Design: Corner/rbac/capacity_planner_exclusive_planning_cycle_creation_returns_unauthorized
        """
        set_clock(api, CANONICAL_CLOCK)

        refused_roles = (
            ANALYST_HEADERS,
            SCHEDULER_HEADERS,
            INTRADAY_HEADERS,
            COACH_HEADERS,
            SOURCING_HEADERS,
        )
        for headers in refused_roles:
            validate_error(
                api.create_planning_cycle(planning_cycle_payload(), headers),
                ApiErrorId.UNAUTHORIZED,
                403,
            )

        validate_error(
            api.create_planning_cycle(
                {"horizon_start_date": "2026-09-13", "horizon_end_date": "2026-09-07"},
                COACH_HEADERS,
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

        _, empty_meta = validate_paginated(api.list_planning_cycles(PLANNER_HEADERS))
        assert empty_meta["total_count"] == 0

        created = validate_success(
            api.create_planning_cycle(planning_cycle_payload(), PLANNER_HEADERS), 201
        )
        assert created["posture"] == POSTURE_OPEN

        _, after_meta = validate_paginated(api.list_planning_cycles(PLANNER_HEADERS))
        assert after_meta["total_count"] == 1


class TestAuthenticationPrecedesEverything:
    """Three distinct identity faults, one identifier, and it outranks not-found."""

    def test_broken_identity_headers_all_answer_unauthenticated(self, api):
        """A missing id, a missing role and an undeclared role all answer 401, never 403 or 404.

        "Every request — reads included — must carry two headers. `X-User-ID`
        identifies the acting principal and `X-User-Role` names the role it acts
        under. If either header is absent, or if `X-User-Role` carries a string
        that is not one of the eight roles enumerated below, the request is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing
        occurs."

        Design: Corner/rbac/request_missing_x_user_id_header_returns_unauthenticated
        """
        set_clock(api, CANONICAL_CLOCK)
        undeclared_headers = build_user_headers(
            UNDECLARED_ROLE_USER_ID, UNDECLARED_ROLE
        )

        validate_error(
            api.create_planning_cycle(
                planning_cycle_payload(), headers_missing_user_id(ROLE_CAPACITY_PLANNER)
            ),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )
        validate_error(
            api.create_planning_cycle(
                planning_cycle_payload(), headers_missing_role(PLANNER_USER_ID)
            ),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )
        validate_error(
            api.create_planning_cycle(planning_cycle_payload(), undeclared_headers),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )
        validate_error(
            api.get_planning_cycle(FABRICATED_CYCLE_ID, undeclared_headers),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )

        _, meta = validate_paginated(api.list_planning_cycles(PLANNER_HEADERS))
        assert meta["total_count"] == 0


class TestAgentBidOwnership:
    """The bid surface is scoped to the acting agent's own row, in both directions."""

    def test_one_agent_can_neither_bid_for_nor_withdraw_another_agents_bid(self, api):
        """An impostor is refused on both endpoints and the victim's bid is untouched.

        "Under the `Agent` role, five operations are ownership-scoped: submitting a
        bid and filing an adherence exception both require the payload's `agent_id`
        to equal `X-User-ID`, and withdrawing a bid, resubmitting an exception and
        responding to an intraday offer all require the addressed row's own agent
        reference to equal `X-User-ID`."

        "Any breach of any of these six scopes yields `ERR_OWNERSHIP_VIOLATION`
        (HTTP 403)."

        Design: Corner/rbac/agent_cannot_bid_on_behalf_of_another_agent
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api)
        agreement = make_labor_agreement(api)
        first_agent = make_agent(api, agreement["id"], seniority_rank=1)
        second_agent = make_agent(api, agreement["id"], seniority_rank=2)
        template = make_shift_template(api, cycle["id"], slots_total=2)
        bid_round = make_bid_round(api, cycle["id"])
        open_round(api, bid_round["id"])

        victim_bid = make_shift_bid(
            api, bid_round["id"], second_agent["id"], [template["id"]]
        )
        assert victim_bid["status"] == BID_STATUS_SUBMITTED

        impostor_headers = make_agent_headers(first_agent["id"])
        validate_error(
            api.create_shift_bid(
                shift_bid_payload(bid_round["id"], second_agent["id"], [template["id"]]),
                impostor_headers,
            ),
            ApiErrorId.OWNERSHIP_VIOLATION,
            403,
        )
        validate_error(
            api.withdraw_shift_bid(victim_bid["id"], impostor_headers),
            ApiErrorId.OWNERSHIP_VIOLATION,
            403,
        )

        untouched = read_bid(api, victim_bid["id"])
        assert untouched["status"] == BID_STATUS_SUBMITTED
        assert untouched["agent_id"] == second_agent["id"]

        own_bid = validate_success(
            api.create_shift_bid(
                shift_bid_payload(bid_round["id"], first_agent["id"], [template["id"]]),
                impostor_headers,
            ),
            201,
        )
        assert own_bid["status"] == BID_STATUS_SUBMITTED
        assert own_bid["agent_id"] == first_agent["id"]

        rows, meta = validate_paginated(
            api.list_shift_bids(SCHEDULER_HEADERS, {"bid_round_id": bid_round["id"]})
        )
        assert meta["total_count"] == 2
        assert {row["agent_id"] for row in rows} == {
            first_agent["id"],
            second_agent["id"],
        }


class TestAllocationCommitmentSegregation:
    """The maker-checker split on commitment is by operator, not by role."""

    def test_the_proposer_is_barred_even_with_the_correct_version_echo(self, api):
        """The proposer's commit is refused, and the same version echo works for another operator.

        "A `SourcingManager` committing a partner allocation must have an
        `X-User-ID` different from that allocation's `proposed_by_user_id`. Either
        collision is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/proposer_cannot_commit_own_allocation
        """
        world = build_partner_week(api)
        partner = make_outsource_partner(
            api,
            SOURCING_HEADERS,
            rate_per_contact_millicents=10000,
            interval_max_volume=50,
            commitment_floor_volume=10,
            billing_basis=BILLING_DELIVERED_ONLY,
        )
        assert partner["version"] == 1

        allocation = propose_allocation(
            api, partner["id"], world["intervals"][0]["id"], 20, SOURCING_HEADERS
        )
        assert allocation["status"] == ALLOCATION_PROPOSED
        assert allocation["proposed_by_user_id"] == SOURCING_USER_ID

        validate_error(
            api.commit_partner_allocation(
                allocation["id"], commit_allocation_payload(1), SOURCING_HEADERS
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES,
            403,
        )

        assert_partner_ledgers(
            read_partner(api, partner["id"]),
            committed_volume_outstanding=0,
            version=1,
        )

        committed = validate_success(
            api.commit_partner_allocation(
                allocation["id"],
                commit_allocation_payload(1),
                make_sourcing_headers(SOURCING_ALT_USER_ID),
            ),
            200,
        )
        assert committed["status"] == ALLOCATION_COMMITTED
        assert committed["committed_by_user_id"] == SOURCING_ALT_USER_ID

        assert_partner_ledgers(
            read_partner(api, partner["id"]),
            committed_volume_outstanding=20,
            version=2,
        )


class TestExceptionDecisionSegregation:
    """The bar on adjudication follows the stored flagging identity across roles."""

    def test_the_coach_who_flagged_the_shift_cannot_decide_any_branch(self, api):
        """Both decision verbs are refused for the flagger and a different coach succeeds.

        "All three branches require the parent cycle not to be frozen, require the
        exception to be in `SUBMITTED` (otherwise `ERR_EXCEPTION_NOT_PENDING`, HTTP
        409), and are subject to the segregation-of-duties check: the coach's
        `X-User-ID` must differ from the `flagged_by_user_id` recorded on the
        underlying shift, or the request is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/flagging_user_cannot_decide_own_exception
        """
        world = build_published_week(api)
        flagged = record_observation(
            api, world["shift"]["id"], 5400, make_intraday_headers(COACH_USER_ID)
        )
        assert_shift_axes(flagged, adherence_status=ADHERENCE_OUT_OF_ADHERENCE)
        assert_shift_adherence(
            flagged, adherence_pct=0.8000, flagged_by_user_id=COACH_USER_ID
        )

        exception = file_exception(
            api, world["shift"]["id"], world["agent"]["id"], 2700
        )
        assert exception["status"] == EXCEPTION_STATUS_SUBMITTED

        for decision in (DECISION_APPROVE, DECISION_REQUEST_INFO):
            validate_error(
                api.decide_adherence_exception(
                    exception["id"], exception_decision_payload(decision), COACH_HEADERS
                ),
                ApiErrorId.SEGREGATION_OF_DUTIES,
                403,
            )

        stalled = read_exception(api, exception["id"])
        assert stalled["status"] == EXCEPTION_STATUS_SUBMITTED
        assert stalled["info_requested_count"] == 0

        decided = validate_success(
            api.decide_adherence_exception(
                exception["id"],
                exception_decision_payload(DECISION_APPROVE),
                make_coach_headers(COACH_ALT_USER_ID),
            ),
            200,
        )
        assert decided["status"] == EXCEPTION_STATUS_APPROVED
        assert decided["decided_by_user_id"] == COACH_ALT_USER_ID

        after = read_shift(api, world["shift"]["id"])
        assert_shift_adherence(after, excused_seconds=2700, adherence_pct=0.9000)
        assert_shift_axes(after, adherence_status=ADHERENCE_EXCUSED)


class TestPartnerRepListScope:
    """A partner representative's allocation list is bound to its own partner id."""

    def test_filtering_to_another_partner_is_refused_not_silently_rewritten(self, api):
        """Another partner's filter answers 403 while the rep's own reads all answer 200.

        "A sixth scope applies to the `PartnerRep` role: listing partner
        allocations may only return rows whose `outsource_partner_id` equals
        `X-User-ID`. Any breach of any of these six scopes yields
        `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

        "Allocations are readable individually, addressed by
        `partner_allocation_id`, and listable with optional `outsource_partner_id`,
        `interval_plan_id` and `status` filters — and a `PartnerRep` may only list
        to their own partner identifier."

        Design: Corner/rbac/partner_rep_cannot_read_another_partners_allocations
        """
        world = build_partner_week(api)
        interval_id = world["intervals"][0]["id"]
        partner_overrides = {
            "rate_per_contact_millicents": 10000,
            "interval_max_volume": 50,
            "commitment_floor_volume": 10,
            "billing_basis": BILLING_DELIVERED_ONLY,
        }
        own_partner = make_outsource_partner(api, SOURCING_HEADERS, **partner_overrides)
        other_partner = make_outsource_partner(api, SOURCING_HEADERS, **partner_overrides)
        own_allocation = propose_allocation(
            api, own_partner["id"], interval_id, 20, SOURCING_HEADERS
        )
        other_allocation = propose_allocation(
            api, other_partner["id"], interval_id, 20, SOURCING_HEADERS
        )

        rep_headers = make_partner_rep_headers(own_partner["id"])

        validate_error(
            api.list_partner_allocations(
                rep_headers, {"outsource_partner_id": other_partner["id"]}
            ),
            ApiErrorId.OWNERSHIP_VIOLATION,
            403,
        )

        own_rows, own_meta = validate_paginated(
            api.list_partner_allocations(
                rep_headers, {"outsource_partner_id": own_partner["id"]}
            )
        )
        assert own_meta["total_count"] == 1
        assert own_rows[0]["id"] == own_allocation["id"]
        assert own_rows[0]["outsource_partner_id"] == own_partner["id"]

        own_read = validate_success(
            api.get_partner_allocation(own_allocation["id"], rep_headers), 200
        )
        assert own_read["outsource_partner_id"] == own_partner["id"]

        own_record = validate_success(
            api.get_outsource_partner(own_partner["id"], rep_headers), 200
        )
        assert own_record["id"] == own_partner["id"]

        every_row, every_meta = validate_paginated(
            api.list_partner_allocations(SOURCING_HEADERS)
        )
        assert every_meta["total_count"] == 2
        assert {row["id"] for row in every_row} == {
            own_allocation["id"],
            other_allocation["id"],
        }


class TestPlanningCycleReadIsSharedAcrossPlanningRoles:
    """Seven roles, one shared read, one identical answer and no side effect."""

    def test_all_seven_planning_roles_read_the_same_open_cycle(self, api):
        """Six opaque roles and the entity-backed agent all answer 200 with the cycle unchanged.

        "| GET | `/planning-cycles/{planning_cycle_id}` | Reads one planning cycle
        including every derived aggregate and its current version. |
        `CapacityPlanner`, `WorkforceAnalyst`, `SchedulingManager`,
        `IntradayController`, `TeamCoach`, `SourcingManager`, `Agent` |"

        "Ownership enforcement is concrete and narrow."

        Design: Corner/rbac/all_planning_roles_can_read_planning_cycle
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api)
        assert cycle["version"] == 1
        agreement = make_labor_agreement(api)
        agent = make_agent(api, agreement["id"])

        readers = (
            PLANNER_HEADERS,
            ANALYST_HEADERS,
            SCHEDULER_HEADERS,
            INTRADAY_HEADERS,
            COACH_HEADERS,
            SOURCING_HEADERS,
            make_agent_headers(agent["id"]),
        )

        postures = []
        for headers in readers:
            seen = validate_success(api.get_planning_cycle(cycle["id"], headers), 200)
            assert seen["id"] == cycle["id"]
            assert seen["version"] == 1
            postures.append(seen["posture"])

        assert len(postures) == 7
        assert set(postures) == {POSTURE_OPEN}

"""Who may act: role lists, tenant scope, and the two segregation-of-duties branches.

Every refusal here is paired with the neighbouring rule that did NOT fire, so the
returned code is pinned to one cause rather than merely being a 403.
"""

from prd_bench_local_runner.testing import (
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import DriveThruApiClient
from test_helpers.api_errors import (
    ERR_DAYPART_WINDOW_MISMATCH,
    ERR_INVALID_COACHING_STATE,
    ERR_PROFILE_NOT_ACTIVE,
    ERR_REPORT_WINDOW_FUTURE,
    ERR_RESTAURANT_MISMATCH,
    ERR_RESTAURANT_SCOPE_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STAFF_NOT_FOUND,
    ERR_STAFF_SCOPE_MISMATCH,
    ERR_STALE_RESTAURANT_VERSION,
    ERR_UNAUTHORIZED,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    COACH_HEADERS,
    MARKET_COACH_ID,
    SECOND_COACH_HEADERS,
    SECOND_MARKET_COACH_ID,
    all_role_headers,
    make_operator_headers,
    make_shift_leader_headers,
)


class TestStoreRegistrationIsChainLevel:
    """The one store-level write an Operator does not own."""

    def test_an_operator_cannot_register_a_store_and_the_body_was_never_at_fault(
        self, api: DriveThruApiClient
    ):
        """PRD §2.1: "If the headers are well formed but the acting role does not appear
        on the endpoint's authorized-role list in §4, the request is rejected with
        `ERR_UNAUTHORIZED` (403)."
        PRD §2.11: "**Endpoint authorization** — the acting role appears on the endpoint's
        role list. Applies to every endpoint. Rejection: `ERR_UNAUTHORIZED` (403)."
        And: "**Operator store scope** — as described in §2.1. Applies to every
        `Operator` mutation. Rejection: `ERR_RESTAURANT_SCOPE_MISMATCH` (403)."

        Design: Corner/rbac/rbac_operator_cannot_register_a_restaurant
        """
        fx.setup_single_unbounded_band(api)
        incumbent = fx.register_restaurant(
            api, "C-2398-60", name="Corner Incumbent Store"
        )
        body = f.restaurant_body("C-2398-60B", name="Operator Self Serve Store")

        # The role check sits above the store-scope check on the ladder.
        error_id = validate_error_is_one_of(
            api.register_restaurant(body, make_operator_headers(incumbent["id"])),
            [ERR_UNAUTHORIZED, ERR_RESTAURANT_SCOPE_MISMATCH],
        )
        assert error_id == ERR_UNAUTHORIZED

        # The identical body registers cleanly for the chain, so nothing in it was
        # wrong and the refused attempt left no row behind.
        created = validate_success(
            api.register_restaurant(body, ADMIN_HEADERS), expected_status=201
        )
        assert created["store_number"] == "C-2398-60B", created
        assert created["id"] != incumbent["id"], created


class TestReportAuthorshipIsCoachOnly:
    """Authorisation is decided before the window and the version are looked at."""

    def test_a_shift_leader_report_is_refused_on_role_before_window_or_version(
        self, api: DriveThruApiClient
    ):
        """PRD §2.11: "**Endpoint authorization** — the acting role appears on the
        endpoint's role list. Applies to every endpoint. Rejection: `ERR_UNAUTHORIZED`
        (403)."
        And: "The first violated rule in this list wins, and its error is the one
        returned."
        And: "**No future reporting** — `window_end_at` is at or before the logical
        clock. Applies to `POST /drive-thru/throughput-reports`. Rejection:
        `ERR_REPORT_WINDOW_FUTURE` (422)."
        And: "**Store version precondition** — `expected_restaurant_version` equals the
        store's current `version`. Applies to `POST /drive-thru/forecast-overrides` and
        `POST /drive-thru/throughput-reports`. Rejection:
        `ERR_STALE_RESTAURANT_VERSION` (412)."

        Design: Corner/rbac/rbac_shift_leader_cannot_create_a_throughput_report
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-61",
            staff_name="Corner Ines",
            name="Corner Report Authorship Store",
        )
        fx.set_clock(api, fx.at(11, 0, 0))
        version_before = fx.current_restaurant_version(api, ctx.restaurant_id)
        assert version_before >= 1, version_before

        # Three rules broken at once: wrong role, a window that has not happened yet,
        # and a version one behind the store's own.
        error_id = validate_error_is_one_of(
            api.create_throughput_report(
                f.throughput_report_body(
                    ctx.restaurant_id,
                    fx.at(22, 0, 0),
                    fx.at(23, 0, 0),
                    version_before - 1,
                    variant="FINAL",
                ),
                ctx.leader_headers,
            ),
            [ERR_UNAUTHORIZED, ERR_REPORT_WINDOW_FUTURE, ERR_STALE_RESTAURANT_VERSION],
        )
        assert error_id == ERR_UNAUTHORIZED

        assert (
            fx.current_restaurant_version(api, ctx.restaurant_id) == version_before
        ), version_before
        _rows, meta = validate_paginated(
            api.list_throughput_reports(
                ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id}
            )
        )
        assert meta["total_count"] == 0, meta


class TestOperatorTenantScope:
    """The role is right; only the store is wrong."""

    def test_one_stores_operator_cannot_raise_another_stores_budget(
        self, api: DriveThruApiClient
    ):
        """PRD §2.1: "Any `Operator` mutation whose target store is not the store named
        by `X-User-ID` is rejected with `ERR_RESTAURANT_SCOPE_MISMATCH` (403). The target
        store is determined as the store in the path when the path names one, otherwise
        the `restaurant_id` in the request body, otherwise the `restaurant_id` of the
        path-addressed resource."
        PRD §3.1: "Both fields are optional on that adjustment, and it re-runs the
        rollup chain end to end — the effective car rate, the volume tier, the outside
        order-taker requirement and the posture — and increments the store's `version`
        by 1."

        Design: Corner/rbac/rbac_operator_cannot_patch_another_operators_store
        """
        fx.setup_single_unbounded_band(api)
        store_a = fx.register_restaurant(api, "C-2398-62A", name="Corner Tenant A")
        store_b = fx.register_restaurant(api, "C-2398-62B", name="Corner Tenant B")
        assert store_b["labor_minutes_budget"] == 300, store_b
        version_b = store_b["version"]

        # Operator IS on the adjustment's role list, so only the tenant can be at fault.
        error_id = validate_error_is_one_of(
            api.patch_restaurant(
                store_b["id"],
                f.restaurant_patch_body(labor_minutes_budget=900),
                make_operator_headers(store_a["id"]),
            ),
            [ERR_RESTAURANT_SCOPE_MISMATCH, ERR_UNAUTHORIZED],
        )
        assert error_id == ERR_RESTAURANT_SCOPE_MISMATCH

        untouched = fx.get_restaurant(api, store_b["id"])
        assert untouched["labor_minutes_budget"] == 300, untouched
        assert untouched["version"] == version_b, untouched
        a.assert_labor_ledger(untouched, committed=0, available=300)

        # Store B's own operator makes the identical adjustment stick.
        allowed = validate_success(
            api.patch_restaurant(
                store_b["id"],
                f.restaurant_patch_body(labor_minutes_budget=900),
                make_operator_headers(store_b["id"]),
            )
        )
        assert allowed["labor_minutes_budget"] == 900, allowed
        assert allowed["version"] == version_b + 1, allowed


class TestShiftLeaderStaffScope:
    """The leader must be on the target store's roster."""

    def test_a_leader_from_one_store_cannot_start_a_car_at_the_other(
        self, api: DriveThruApiClient
    ):
        """PRD §2.1: "For every `ShiftLeader` mutation, `X-User-ID` must be an existing
        `StaffMember` whose `restaurant_id` equals the target store; otherwise the
        request is rejected with `ERR_STAFF_SCOPE_MISMATCH` (403)."
        PRD §2.11: "**ShiftLeader staff scope** — as described in §2.1. Applies to every
        `ShiftLeader` mutation. Rejection: `ERR_STAFF_SCOPE_MISMATCH` (403)."
        And: "**Daypart containment** — the logical clock's minute-of-day at loop
        creation is at or after the profile's `start_minute` and strictly before its
        `end_minute`. Applies to `POST /drive-thru/timer-loops`. Rejection:
        `ERR_DAYPART_WINDOW_MISMATCH` (422)."

        Design: Corner/rbac/rbac_shift_leader_cannot_start_a_loop_at_another_store
        """
        fx.setup_single_unbounded_band(api)
        ctx_a = fx.setup_store(
            api,
            "C-2398-63A",
            staff_name="Corner Pia",
            with_active_lunch_profile=False,
            name="Corner Roster Store A",
        )
        ctx_b = fx.setup_store(
            api,
            "C-2398-63B",
            with_staff=False,
            name="Corner Roster Store B",
        )
        profile_b = validate_success(
            api.get_daypart_profile(ctx_b.profile_id, ADMIN_HEADERS)
        )
        assert profile_b["profile_state"] == "ACTIVE", profile_b
        assert profile_b["start_minute"] == 660, profile_b
        assert profile_b["end_minute"] == 840, profile_b
        # 11:00 is minute-of-day 660, inside store B's lunch window.
        fx.set_clock(api, fx.at(11, 0, 0))

        error_id = validate_error_is_one_of(
            api.create_timer_loop(
                f.timer_loop_body(ctx_b.restaurant_id, ctx_b.profile_id),
                make_shift_leader_headers(ctx_a.staff_id),
            ),
            [
                ERR_STAFF_SCOPE_MISMATCH,
                ERR_PROFILE_NOT_ACTIVE,
                ERR_DAYPART_WINDOW_MISMATCH,
                ERR_RESTAURANT_MISMATCH,
            ],
        )
        assert error_id == ERR_STAFF_SCOPE_MISMATCH

        _rows, meta = validate_paginated(
            api.list_timer_loops(
                ADMIN_HEADERS, {"restaurant_id": ctx_b.restaurant_id}
            )
        )
        assert meta["total_count"] == 0, meta
        a.assert_rollup(
            fx.get_restaurant(api, ctx_b.restaurant_id), cars_per_hour_observed=0.0
        )


class TestSharedStoreRead:
    """Reads are never narrowed to the owning operator."""

    def test_all_five_roles_read_the_same_store_payload(self, api: DriveThruApiClient):
        """PRD §2.1: "Every `GET` endpoint is readable by all five roles."
        And: "Exactly five roles exist, and their spelling is part of the contract:
        `ProgramAdmin`, `Operator`, `ShiftLeader`, `AccuracyAuditor` and `MarketCoach`."

        Design: Corner/rbac/rbac_all_five_roles_share_the_restaurant_read
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-64",
            staff_name="Corner Otto",
            name="Corner Shared Read Store",
        )
        baseline_version = fx.current_restaurant_version(api, ctx.restaurant_id)

        payloads = {}
        for role, headers in all_role_headers(
            ctx.restaurant_id, ctx.staff_id
        ).items():
            payloads[role] = validate_success(
                api.get_restaurant(ctx.restaurant_id, headers)
            )

        assert len(payloads) == 5, sorted(payloads)
        for role, store in payloads.items():
            assert store["id"] == ctx.restaurant_id, (role, store)
            assert store["version"] == baseline_version, (role, store)
            a.assert_rollup(store, volume_tier="TIER_1", service_posture="OPEN")
            a.assert_merge_capacity(store, free=1)
        tiers = {store["volume_tier"] for store in payloads.values()}
        versions = {store["version"] for store in payloads.values()}
        assert tiers == {"TIER_1"}, tiers
        assert versions == {baseline_version}, versions


class TestRemakeSegregation:
    """A reporter cannot sign off their own remake."""

    def test_the_reporter_cannot_be_credited_with_the_remake_but_a_colleague_can(
        self, api: DriveThruApiClient
    ):
        """PRD §3.6: "It requires an unfrozen store, the incident to be in `LOGGED`, and
        — the segregation-of-duties rule — the `remade_by_staff_id` supplied in the
        request to be a *different* team member from `logged_by_staff_id`, who must belong
        to the same store as the incident."
        And: "Crediting the reporter with their own remake is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (409)."
        PRD §2.11: "**Segregation of duties** — `remade_by_staff_id` must differ from the
        incident's `logged_by_staff_id`, and a closing coach's `X-User-ID` must differ
        from the intervention's `issued_by_user_id`."

        Design: Corner/rbac/rbac_remake_credited_to_the_reporter_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-65",
            staff_name="Corner Reporter",
            name="Corner Remake Segregation Store",
        )
        colleague = fx.add_staff_member(api, ctx.restaurant_id, "Corner Colleague")
        loop = fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=None,
        )
        incident = fx.log_incident(
            api, ctx, loop["id"], incident_type="WRONG_ITEM", logged_by_staff_id=ctx.staff_id
        )
        assert incident["severity"] == "MAJOR", incident
        assert incident["penalty_seconds"] == 45, incident
        assert incident["remake_cost_cents"] == 750, incident
        assert incident["incident_state"] == "LOGGED", incident

        # The reporter exists and belongs to this store, so identity is not the fault.
        error_id = validate_error_is_one_of(
            api.deliver_remake(
                incident["id"],
                f.deliver_remake_body(ctx.staff_id),
                ctx.leader_headers,
            ),
            [ERR_SEGREGATION_OF_DUTIES, ERR_STAFF_NOT_FOUND],
        )
        assert error_id == ERR_SEGREGATION_OF_DUTIES

        held = validate_success(api.get_accuracy_incident(incident["id"], ADMIN_HEADERS))
        assert held["incident_state"] == "LOGGED", held
        assert held["remade_by_staff_id"] is None, held
        a.assert_loop_states(
            validate_success(api.get_timer_loop(loop["id"], ADMIN_HEADERS)),
            accuracy_state="REMAKE_OPEN",
        )

        # The same call crediting a second member goes through.
        remade = fx.deliver_remake(api, ctx, incident["id"], colleague["id"])
        assert remade["incident_state"] == "REMADE", remade
        assert remade["remade_by_staff_id"] == colleague["id"], remade
        a.assert_loop_states(
            validate_success(api.get_timer_loop(loop["id"], ADMIN_HEADERS)),
            accuracy_state="REMADE",
        )


class TestCoachingClosureSegregation:
    """The issuing coach cannot also be the closing coach."""

    def test_the_issuing_coach_cannot_close_but_a_second_coach_can(
        self, api: DriveThruApiClient
    ):
        """PRD §3.9: "Moving the intervention `ACKNOWLEDGED → CLOSED` requires it to be
        in `ACKNOWLEDGED`, requires the store not to be frozen, requires a
        `closure_note`, and requires the closing `MarketCoach`'s `X-User-ID` to be
        **different** from the `issued_by_user_id` recorded at issue time — the coach who
        issued an intervention may not be the coach who closes it, and an attempt to do
        so is rejected with `ERR_SEGREGATION_OF_DUTIES`."
        And: "It stamps the issuing coach's opaque `X-User-ID` into `issued_by_user_id`,
        overwriting whatever was there from a previous issue, and recomputes
        `segment_gap_seconds`, `priority_score` and `tier` in full from the report's
        stored figures as they now stand — so an intervention that goes round the
        revision loop can come back with a different score and a different `tier`."
        And: "The gap component is worth up to 60 points and is 60 multiplied by the
        smaller of 1.0 and `segment_gap_seconds` divided by 30 seconds — a segment running
        half a minute or more behind target saturates it."

        Design: Corner/rbac/rbac_coaching_closed_by_its_issuing_coach_rejected
        """
        fx.setup_four_tier_bands(api)
        ctx = fx.setup_store(
            api,
            "C-2398-66",
            staff_name="Corner Halle",
            name="Corner Closure Segregation Store",
        )
        fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=fx.at(11, 2, 0),
            depart_at=fx.at(11, 4, 10),
            order_items_count=3,
        )
        fx.set_clock(api, fx.at(11, 5, 0))
        report = fx.create_published_report(api, ctx, fx.at(11, 0, 0), fx.at(11, 5, 0))
        a.assert_report_metrics(
            report, cars_served=1, attainment_band="GREEN", open_remake_incident_count=0
        )

        drafted = fx.create_coaching(
            api, report["id"], ctx.staff_id, "PULL_FORWARD", headers=COACH_HEADERS
        )
        issued = fx.issue_coaching(api, drafted["id"], headers=COACH_HEADERS)
        assert issued["issued_by_user_id"] == MARKET_COACH_ID, issued
        # A 60-second pull-forward leg against a 40-second pinned target is 20 seconds
        # behind, so 60 * 20/30 = 40.00, plus the GREEN band's 15 * 0.2 = 3.00.
        a.assert_coaching_scoring(
            issued,
            segment_gap_seconds=20,
            priority_score=43.00,
            tier="TIER_B_COACH",
        )
        acknowledged = fx.acknowledge_coaching(api, ctx, drafted["id"])
        assert acknowledged["ci_state"] == "ACKNOWLEDGED", acknowledged

        # ACKNOWLEDGED to CLOSED is a declared transition, so only the actor is wrong.
        error_id = validate_error_is_one_of(
            api.close_coaching_intervention(
                drafted["id"],
                f.closure_body("Closing my own intervention"),
                COACH_HEADERS,
            ),
            [ERR_SEGREGATION_OF_DUTIES, ERR_INVALID_COACHING_STATE],
        )
        assert error_id == ERR_SEGREGATION_OF_DUTIES

        held = validate_success(
            api.get_coaching_intervention(drafted["id"], ADMIN_HEADERS)
        )
        assert held["ci_state"] == "ACKNOWLEDGED", held
        assert held["closure_note"] is None, held

        closed = validate_success(
            api.close_coaching_intervention(
                drafted["id"],
                f.closure_body("Reviewed and closed by the market's second coach"),
                SECOND_COACH_HEADERS,
            )
        )
        assert closed["ci_state"] == "CLOSED", closed
        assert closed["issued_by_user_id"] == MARKET_COACH_ID, closed
        assert MARKET_COACH_ID != SECOND_MARKET_COACH_ID
        assert (
            closed["closure_note"] == "Reviewed and closed by the market's second coach"
        ), closed

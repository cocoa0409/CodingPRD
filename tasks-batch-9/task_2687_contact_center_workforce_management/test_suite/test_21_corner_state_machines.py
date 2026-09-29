"""State machines: declared edges, refused edges, initial states and cascades.

Each test drives one transition and then reads back everything the contract
says that transition does — or, for a refusal, everything it says the refusal
must leave alone.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_agent_hours,
    assert_cycle_ledgers,
    assert_declared_fields,
    assert_hours,
    assert_instant_equals,
    assert_interval_coverage,
    assert_interval_forecast,
    assert_interval_outsourcing,
    assert_partner_ledgers,
    assert_ratio,
    assert_shift_axes,
    assert_shift_hours,
)
from test_helpers.constants import (
    AGENT_STATUS_ACTIVE,
    ALLOCATION_COMMITTED,
    ALLOCATION_REVOKED,
    BILLING_DELIVERED_ONLY,
    CLASS_STATUS_CHARTERED,
    CLASS_STATUS_GRADUATED,
    CLASS_STATUS_IN_TRAINING,
    COVERAGE_SHORT,
    DEFAULT_MAX_REOPEN_COUNT,
    EVENT_STATUS_CONFIRMED,
    PARTNER_STATUS_PROBATION,
    PARTNER_STATUS_SUSPENDED,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    POSTURE_REQUIREMENTS_LOCKED,
    POSTURE_SCHEDULE_PUBLISHED,
    PUBLICATION_CANCELLED,
    PUBLICATION_PUBLISHED,
    ROUND_STATUS_DRAFT,
)
from test_helpers.fixtures import (
    CANONICAL_CLOCK,
    HORIZON_START,
    cancel_shift,
    charter_class,
    commit_allocation,
    file_performance_report,
    freeze_cycle,
    generate_grid,
    lock_requirements,
    make_agent,
    make_forecast_group,
    make_hiring_class,
    make_labor_agreement,
    make_marketing_event,
    make_outsource_partner,
    make_partner_forecast_group,
    make_planning_cycle,
    make_schedule_shift,
    make_shift_template,
    propose_allocation,
    publish_shift,
    read_agent,
    read_agreement,
    read_allocation,
    read_cycle,
    read_group,
    read_hiring_class,
    read_interval,
    read_round,
    read_template,
    set_clock,
    set_event_status,
    start_training,
)
from test_helpers.test_users import (
    ANALYST_HEADERS,
    PLANNER_HEADERS,
    SCHEDULER_HEADERS,
    SOURCING_HEADERS,
)
from test_helpers.types import BID_ROUND_FIELDS

GRADUATION_CLOCK = "2026-09-13T00:00:00Z"


def _request_posture(api, planning_cycle_id, target_posture):
    """Raw posture request so a refusal can be inspected."""
    return api.set_cycle_posture(
        planning_cycle_id, f.posture_payload(target_posture), PLANNER_HEADERS
    )


def _request_class_status(api, hiring_class_id, target_status):
    """Raw hiring-class status request so a refusal can be inspected."""
    return api.set_hiring_class_status(
        hiring_class_id, f.hiring_class_status_payload(target_status), PLANNER_HEADERS
    )


def _request_event_status(api, marketing_event_id, target_status):
    """Raw marketing-event status request so a refusal can be inspected."""
    return api.set_marketing_event_status(
        marketing_event_id,
        f.marketing_event_status_payload(target_status),
        ANALYST_HEADERS,
    )


class TestCyclePostureEdges:
    """The lock edge, an undeclared edge and the terminal freeze."""

    def test_locking_requirements_stamps_the_logical_clock_and_bumps_the_version(
        self, api
    ):
        """The lock edge stamps requirements_locked_at and increments the version by one.

        "Locking requirements moves `OPEN → REQUIREMENTS_LOCKED` and is the act
        that makes schedule publication legal; it is refused unless at least one
        forecast group of the cycle has an `interval_count` of 1 or more,
        meaning some demand grid actually exists to lock. On success it stamps
        `requirements_locked_at` from the logical clock, recomputes
        `short_interval_count` across every interval plan of the cycle, and
        increments the cycle's `version` by 1."

        Design: Corner/state_machines/planning_cycle_posture_open_to_requirements_locked
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api, name="W37-LOCK")
        group = make_forecast_group(api, cycle["id"])
        generate_grid(api, group["id"], HORIZON_START)
        # Grid generation cascades into the cycle's short_interval_count, and
        # "Any operation that changes a row — whether the client addressed that
        # row directly or a cascade reached it — refreshes that row's
        # updated_at and increments its version by 1", so the lock edge's own
        # +1 is measured from the cycle's version as it stands just before it.
        version_before = read_cycle(api, cycle["id"])["version"]

        locked = lock_requirements(api, cycle["id"])

        assert locked["posture"] == POSTURE_REQUIREMENTS_LOCKED
        assert_instant_equals(
            locked["requirements_locked_at"], CANONICAL_CLOCK, "requirements_locked_at"
        )
        assert locked["version"] == version_before + 1, (
            f"version: expected {version_before + 1}, got {locked['version']}"
        )
        assert read_group(api, group["id"])["interval_count"] == 4
        stored = read_cycle(api, cycle["id"])
        assert_cycle_ledgers(stored, short_interval_count=4)
        assert stored["published_at"] is None, "published_at is untouched by the lock"

    def test_jumping_from_open_to_schedule_published_is_refused(self, api):
        """Schedule publication is undeclared out of OPEN, so it is a 409 and no write.

        "When a resource is asked to make a transition that its current state
        does not declare — including repeating a trigger against a terminal
        state — the refusal is HTTP 409 and carries the most specific identifier
        available for that entity family: … and the generic `ERR_INVALID_STATE`
        for every other illegal transition — cycle posture, marketing-event
        status, bid status, publication axis, adherence axis, partner status,
        allocation status, hiring-class status and agent employment status
        alike."

        Design: Corner/state_machines/planning_cycle_open_to_schedule_published_returns_invalid_state
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api, name="W37-SKIP")
        version_before = cycle["version"]

        response = _request_posture(api, cycle["id"], POSTURE_SCHEDULE_PUBLISHED)

        validate_error(response, ApiErrorId.INVALID_STATE.value, 409)
        stored = read_cycle(api, cycle["id"])
        assert_cycle_ledgers(stored, posture=POSTURE_OPEN, version=version_before)
        assert stored["published_at"] is None

    def test_a_frozen_cycle_refuses_both_reopening_and_refreezing(self, api):
        """The freeze gate answers before the state check, on both attempts.

        "Once a cycle reaches `FROZEN`, every subsequent write against that
        cycle or against any child resource that resolves back to it … fails
        with `ERR_CYCLE_FROZEN` (HTTP 409). This check runs ahead of every
        business rule, so a frozen cycle masks skill mismatches, budget
        breaches and state errors alike."

        Design: Corner/state_machines/frozen_cycle_cannot_return_to_open
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api, name="W37-TERM")
        frozen = freeze_cycle(api, cycle["id"])
        frozen_version = frozen["version"]

        reopen = _request_posture(api, cycle["id"], POSTURE_OPEN)
        refreeze = _request_posture(api, cycle["id"], POSTURE_FROZEN)

        validate_error(reopen, ApiErrorId.CYCLE_FROZEN.value, 409)
        validate_error(refreeze, ApiErrorId.CYCLE_FROZEN.value, 409)
        assert_cycle_ledgers(
            read_cycle(api, cycle["id"]),
            posture=POSTURE_FROZEN,
            version=frozen_version,
        )


class TestHiringClassLifecycle:
    """The temporal precondition on training, and the minting side effect."""

    def test_training_before_the_start_date_is_refused(self, api):
        """A chartered class whose start date is still in the future cannot enter training.

        "`CHARTERED → IN_TRAINING` requires that the logical clock has reached or
        passed the class's `start_date` at midnight UTC, and likewise recomputes
        the class FTE and the cycle pipeline."

        Design: Corner/state_machines/chartered_class_cannot_enter_training_before_start_date
        """
        set_clock(api, CANONICAL_CLOCK)
        agreement = make_labor_agreement(api, code="LA-CORE")
        cycle = make_planning_cycle(api, name="W37-TRAIN")
        hiring_class = make_hiring_class(
            api,
            cycle["id"],
            agreement["id"],
            cohort_name="CLASS-T",
            skill_code="VOICE_EN",
            start_date=HORIZON_START,
            seats=24,
            training_weeks=1,
            nesting_weeks=1,
            expected_attrition_pct=0.1250,
            graduate_hourly_rate_cents=2000,
            graduate_weekly_hours=37.5,
        )
        charter_class(api, hiring_class["id"])

        response = _request_class_status(
            api, hiring_class["id"], CLASS_STATUS_IN_TRAINING
        )

        validate_error(response, ApiErrorId.INVALID_STATE.value, 409)
        stored = read_hiring_class(api, hiring_class["id"])
        assert stored["status"] == CLASS_STATUS_CHARTERED
        assert stored["nesting_from_date"] == "2026-09-14"
        assert stored["productive_from_date"] == "2026-09-21"
        assert_hours(
            stored["effective_fte_at_horizon_end"], 0.00, "effective_fte_at_horizon_end"
        )
        assert_cycle_ledgers(read_cycle(api, cycle["id"]), pipeline_fte=0.00)

    def test_graduation_mints_exactly_the_expected_graduates(self, api):
        """Graduating moves the cohort out of the pipeline and into active headcount.

        "On success the system mints exactly `expected_graduates` agent rows.
        Each is created with `status` `ACTIVE`, `hiring_class_id` pointing at
        this class, a `skills` array containing exactly the class's single
        `skill_code`, `labor_agreement_id` copied from the class,
        `hourly_rate_cents` set from `graduate_hourly_rate_cents` and
        `weekly_contracted_hours` set from `graduate_weekly_hours`. Their
        `employee_code` values are generated from the cohort label with a
        three-digit zero-padded ascending index — the cohort name followed by a
        hyphen and `001`, then `002`, and so on up to the number of graduates —
        assigned in ascending index order. The class's `graduated_agent_count`
        is set to `expected_graduates`. The agreement's `enrolled_agent_count`,
        the cycle's `headcount_active` and the cycle's `pipeline_fte` are all
        then recomputed: in one request the cohort leaves the pipeline and its
        graduates enter the active headcount."

        Design: Corner/state_machines/hiring_class_graduate_mints_expected_graduate_agents
        """
        set_clock(api, CANONICAL_CLOCK)
        agreement = make_labor_agreement(api, code="LA-CORE")
        cycle = make_planning_cycle(api, name="W37-GRAD")
        hiring_class = make_hiring_class(
            api,
            cycle["id"],
            agreement["id"],
            cohort_name="CLASS-A",
            skill_code="VOICE_EN",
            start_date="2026-09-06",
            seats=24,
            training_weeks=1,
            nesting_weeks=1,
            expected_attrition_pct=0.1250,
            graduate_hourly_rate_cents=2000,
            graduate_weekly_hours=37.5,
        )
        assert hiring_class["expected_graduates"] == 21
        chartered = charter_class(api, hiring_class["id"])
        assert_hours(
            chartered["effective_fte_at_horizon_end"],
            10.50,
            "effective_fte_at_horizon_end",
        )
        set_clock(api, GRADUATION_CLOCK)
        start_training(api, hiring_class["id"])
        assert_cycle_ledgers(
            read_cycle(api, cycle["id"]), headcount_active=0, pipeline_fte=10.50
        )

        graduated = validate_success(
            api.graduate_hiring_class(hiring_class["id"], PLANNER_HEADERS)
        )

        assert graduated["status"] == CLASS_STATUS_GRADUATED
        assert graduated["graduated_agent_count"] == 21
        minted, meta = validate_paginated(
            api.list_agents(
                SCHEDULER_HEADERS,
                params={
                    "hiring_class_id": hiring_class["id"],
                    "limit": 100,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 21
        assert meta["has_more"] is False
        assert len(minted) == 21
        assert {agent["employee_code"] for agent in minted} == {
            f"CLASS-A-{index:03d}" for index in range(1, 22)
        }
        for agent in minted:
            assert agent["status"] == AGENT_STATUS_ACTIVE
            assert agent["skills"] == ["VOICE_EN"]
            assert agent["labor_agreement_id"] == agreement["id"]
            assert agent["hourly_rate_cents"] == 2000
            assert_hours(
                agent["weekly_contracted_hours"], 37.5, "weekly_contracted_hours"
            )
        assert read_agreement(api, agreement["id"])["enrolled_agent_count"] == 21
        assert_cycle_ledgers(
            read_cycle(api, cycle["id"]), headcount_active=21, pipeline_fte=0.00
        )
        assert_hours(
            read_hiring_class(api, hiring_class["id"])["effective_fte_at_horizon_end"],
            10.50,
            "effective_fte_at_horizon_end",
        )


class TestBidRoundInitialState:
    """What a round looks like the moment it is created."""

    def test_a_new_round_is_draft_with_every_counter_at_its_starting_value(self, api):
        """A new round starts in DRAFT with zero counters and a null honour rate.

        "A new round starts at `status` `DRAFT` with `reopen_count` at zero,
        `awarded_bid_count` and `unfilled_bid_count` at zero, and
        `preference_honor_rate` at null."

        Design: Corner/state_machines/bid_round_starts_in_draft_with_zero_ledgers
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api, name="W37-INIT")
        template = make_shift_template(api, cycle["id"], code="T-MON-AM")
        payload = f.bid_round_payload(cycle["id"], code="R-1")
        payload.pop("max_reopen_count")

        created = validate_success(
            api.create_bid_round(payload, SCHEDULER_HEADERS), 201
        )

        assert created["status"] == ROUND_STATUS_DRAFT
        assert created["max_reopen_count"] == DEFAULT_MAX_REOPEN_COUNT
        stored = read_round(api, created["id"])
        assert_declared_fields(stored, BID_ROUND_FIELDS)
        assert stored["reopen_count"] == 0
        assert stored["preference_honor_rate"] is None, (
            "an unscored round has a null honour rate, not 0.0000"
        )
        assert stored["awarded_bid_count"] == 0
        assert stored["unfilled_bid_count"] == 0
        assert read_template(api, template["id"])["slots_awarded"] == 0


class TestMarketingEventConfirmation:
    """Confirming once applies the uplift; confirming again must change nothing."""

    def test_confirming_a_second_time_is_refused_and_does_not_restack_the_uplift(
        self, api
    ):
        """The uplift lands once; the repeat trigger is a 409 that leaves the grid alone.

        "**Confirmation** — the `DRAFT → CONFIRMED` move — is what injects
        uplift into the forecast, and it is the deepest cascade in the system."
        … "the refusal is HTTP 409 and carries … the generic
        `ERR_INVALID_STATE` for every other illegal transition — cycle posture,
        marketing-event status, bid status, publication axis, adherence axis,
        partner status, allocation status, hiring-class status and agent
        employment status alike."

        Design: Corner/state_machines/marketing_event_confirm_twice_returns_invalid_state
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api, name="W37-IDEM")
        group = make_forecast_group(api, cycle["id"])
        intervals = generate_grid(api, group["id"], HORIZON_START)
        event = make_marketing_event(
            api, cycle["id"], group["id"], name="Flash Sale", uplift_pct=1.2000
        )

        confirmed = set_event_status(api, event["id"], EVENT_STATUS_CONFIRMED)

        assert confirmed["status"] == EVENT_STATUS_CONFIRMED
        assert_ratio(confirmed["weighted_uplift_pct"], 1.2000, "weighted_uplift_pct")
        first = read_interval(api, intervals[0]["id"])
        assert_interval_forecast(
            first,
            volume_forecast=1056,
            aht_forecast_seconds=405,
            applied_event_uplift_pct=1.2000,
            required_agents=415,
        )

        repeat = _request_event_status(api, event["id"], EVENT_STATUS_CONFIRMED)

        validate_error(repeat, ApiErrorId.INVALID_STATE.value, 409)
        again = read_interval(api, intervals[0]["id"])
        assert_interval_forecast(
            again,
            volume_forecast=1056,
            applied_event_uplift_pct=1.2000,
            required_agents=415,
        )
        stored = validate_success(api.get_marketing_event(event["id"], ANALYST_HEADERS))
        assert stored["status"] == EVENT_STATUS_CONFIRMED


class TestPartnerSuspensionCascade:
    """A second consecutive breach suspends the partner and unwinds its commitment."""

    def test_suspension_revokes_the_committed_allocation_and_restores_the_interval(
        self, api
    ):
        """Suspension drops the live commitment and hands the volume back as unserved.

        "`PROBATION → SUSPENDED` fires when a second consecutive report breaches,
        taking `consecutive_breach_count` to 2. Suspension is terminal and
        drastic: every one of the partner's allocations in `PROPOSED` or
        `COMMITTED` is transitioned to `REVOKED`, which restores
        `committed_volume_outstanding` to zero and recomputes
        `partner_committed_volume` and `unserved_volume` on each affected
        interval."

        Design: Corner/state_machines/partner_suspension_revokes_committed_allocations
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api, name="W37-SUSP")
        group = make_partner_forecast_group(api, cycle["id"])
        intervals = generate_grid(api, group["id"], HORIZON_START)
        partner = make_outsource_partner(
            api,
            legal_name="Partner One",
            skill_codes=["CHAT_EN"],
            rate_per_contact_millicents=12500,
            interval_max_volume=50,
            commitment_floor_volume=10,
            performance_threshold_pct=0.8500,
            billing_basis=BILLING_DELIVERED_ONLY,
        )
        allocation = propose_allocation(
            api, partner["id"], intervals[0]["id"], 40, SOURCING_HEADERS
        )
        committed = commit_allocation(api, allocation["id"], partner["version"])
        assert committed["status"] == ALLOCATION_COMMITTED
        after_first = file_performance_report(
            api, partner["id"], 0.8000, period_end_date="2026-08-30"
        )
        assert_partner_ledgers(
            after_first,
            status=PARTNER_STATUS_PROBATION,
            rolling_sl_attainment_pct=0.8000,
            consecutive_breach_count=1,
        )

        after_second = file_performance_report(
            api, partner["id"], 0.7000, period_end_date="2026-09-06"
        )

        assert_partner_ledgers(
            after_second,
            status=PARTNER_STATUS_SUSPENDED,
            rolling_sl_attainment_pct=0.7500,
            consecutive_breach_count=2,
            committed_volume_outstanding=0,
            performance_report_count=2,
        )
        assert len(after_second["latest_sl_attainment_pcts"]) == 2, (
            "the attainment list is append-only, so both reports are on it"
        )
        assert read_allocation(api, allocation["id"])["status"] == ALLOCATION_REVOKED
        assert_interval_outsourcing(
            read_interval(api, intervals[0]["id"], SOURCING_HEADERS),
            allocatable_volume=82,
            partner_committed_volume=0,
            unserved_volume=82,
        )


class TestPublicationLedgerSync:
    """Publishing and then cancelling one shift, and the ledgers in between."""

    def test_publication_moves_paid_hours_and_cancellation_gives_them_back(self, api):
        """Paid hours land on the agent and the cycle, then unwind on cancellation.

        "A successful publication cascades four ways. The agent's
        `scheduled_hours_committed` — the sum of `paid_hours` over that agent's
        shifts whose `publication_status` is `PUBLISHED`, at two decimal places
        — and the cycle's `total_scheduled_hours` are both recomputed." … "And
        the cycle's `headcount_active` is recomputed, because a draft or
        published shift is one of the two ways an agent enters the cycle's
        headcount."

        Design: Corner/state_machines/publication_syncs_cycle_and_agent_hour_ledgers
        """
        set_clock(api, CANONICAL_CLOCK)
        agreement = make_labor_agreement(api, code="LA-CORE")
        cycle = make_planning_cycle(api, name="W37-LEDGER")
        group = make_forecast_group(api, cycle["id"])
        intervals = generate_grid(api, group["id"], HORIZON_START)
        agent = make_agent(api, agreement["id"], employee_code="E-001")
        template = make_shift_template(api, cycle["id"], code="T-MON-AM")
        shift = make_schedule_shift(
            api, cycle["id"], agent["id"], template["id"], HORIZON_START
        )
        assert_shift_hours(shift, scheduled_seconds=27000)
        assert_cycle_ledgers(read_cycle(api, cycle["id"]), total_scheduled_hours=0.00)
        lock_requirements(api, cycle["id"])

        published = publish_shift(api, shift["id"])

        assert_shift_axes(published, publication_status=PUBLICATION_PUBLISHED)
        assert_shift_hours(published, paid_hours=7.50)
        assert_cycle_ledgers(
            read_cycle(api, cycle["id"]),
            total_scheduled_hours=7.50,
            headcount_active=1,
        )
        assert_agent_hours(read_agent(api, agent["id"]), 7.50)
        assert_interval_coverage(
            read_interval(api, intervals[0]["id"]),
            effective_scheduled_agents=1,
            coverage_gap=139,
            coverage_state=COVERAGE_SHORT,
        )

        cancelled = cancel_shift(api, shift["id"])

        assert_shift_axes(cancelled, publication_status=PUBLICATION_CANCELLED)
        assert_cycle_ledgers(
            read_cycle(api, cycle["id"]),
            total_scheduled_hours=0.00,
            headcount_active=0,
        )
        assert_agent_hours(read_agent(api, agent["id"]), 0.00)
        assert_interval_coverage(
            read_interval(api, intervals[0]["id"]), effective_scheduled_agents=0
        )

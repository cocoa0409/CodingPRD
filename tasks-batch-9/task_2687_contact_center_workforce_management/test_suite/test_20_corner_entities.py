"""Entity surfaces: creation field sets, declared defaults, computed fields and lookups.

These tests read one entity at a time and pin what the contract says the
server owns: which fields come back, which values appear when the client
omits an optional input, which values are computed rather than accepted from
the payload, and which identifier a lookup answers when nothing matches.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_common_fields,
    assert_cycle_ledgers,
    assert_declared_fields,
    assert_hours,
    assert_instant_equals,
    assert_ratio,
)
from test_helpers.constants import (
    CLASS_STATUS_PLANNED,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_INTRADAY_ALERT_SHORT_THRESHOLD,
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    DEFAULT_OT_BUDGET_CENTS,
    DEFAULT_OT_PREMIUM_MULTIPLIER,
    DEFAULT_REQUIREMENT_BASIS,
    DEFAULT_UNPAID_BREAK_MINUTES,
    POSTURE_OPEN,
    REQUIREMENT_BASIS_SERVICE_LEVEL,
)
from test_helpers.fixtures import (
    CANONICAL_CLOCK,
    HORIZON_END,
    HORIZON_START,
    make_forecast_group,
    make_labor_agreement,
    make_planning_cycle,
    read_agreement,
    read_cycle,
    read_hiring_class,
    read_template,
    set_clock,
)
from test_helpers.test_users import ANALYST_HEADERS, PLANNER_HEADERS, SCHEDULER_HEADERS
from test_helpers.types import (
    HIRING_CLASS_FIELDS,
    LABOR_AGREEMENT_FIELDS,
    PLANNING_CYCLE_FIELDS,
    SHIFT_TEMPLATE_FIELDS,
)

CLAIMED_ID = "11111111-1111-4111-8111-111111111111"


def _minimal_cycle_payload(name):
    """Only the three always-required cycle inputs, so defaults can be observed."""
    return {
        "name": name,
        "horizon_start_date": HORIZON_START,
        "horizon_end_date": HORIZON_END,
    }


class TestPlanningCycleCreation:
    """What a freshly created planning cycle looks like on the wire."""

    def test_creation_answers_201_with_every_declared_field(self, api):
        """A cycle created with every input present returns the whole field set.

        "A freshly created cycle is initialised with `posture` at `OPEN`,
        `version` at 1, `reforecast_generation` at 0, and every derived
        aggregate at its zero value: `short_interval_count`,
        `total_scheduled_hours`, `ot_spend_committed_cents`,
        `ot_hours_committed`, `headcount_active` and `pipeline_fte` all read
        zero, while `requirements_locked_at` and `published_at` are null."

        Design: Corner/entities/planning_cycle_creation_returns_all_declared_fields
        """
        clock = set_clock(api, CANONICAL_CLOCK)
        assert_instant_equals(clock["current_utc"], CANONICAL_CLOCK, "current_utc")

        response = api.create_planning_cycle(
            {
                "name": "W37-2026",
                "horizon_start_date": HORIZON_START,
                "horizon_end_date": HORIZON_END,
                "interval_minutes": 15,
                "requirement_basis": REQUIREMENT_BASIS_SERVICE_LEVEL,
                "ot_budget_cents": 500000,
                "intraday_alert_short_threshold": 5,
            },
            PLANNER_HEADERS,
        )

        cycle = validate_success(response, 201)
        envelope = response.json()
        assert envelope["response_type"] == "object", (
            f"A single-resource write answers response_type \"object\", "
            f"got {envelope['response_type']!r}"
        )
        request_id = envelope["meta"]["api_request_id"]
        assert request_id.startswith("req_"), (
            f"api_request_id must start with req_, got {request_id!r}"
        )
        assert is_iso8601_timestamp(envelope["meta"]["api_request_timestamp"]), (
            "api_request_timestamp must be an ISO 8601 UTC timestamp"
        )

        assert_declared_fields(cycle, PLANNING_CYCLE_FIELDS)
        assert_common_fields(cycle)
        assert cycle["name"] == "W37-2026"
        assert cycle["horizon_start_date"] == HORIZON_START
        assert cycle["horizon_end_date"] == HORIZON_END
        assert cycle["interval_minutes"] == 15
        assert cycle["requirement_basis"] == REQUIREMENT_BASIS_SERVICE_LEVEL
        assert cycle["ot_budget_cents"] == 500000
        assert cycle["intraday_alert_short_threshold"] == 5
        assert_cycle_ledgers(
            cycle,
            posture=POSTURE_OPEN,
            short_interval_count=0,
            total_scheduled_hours=0.00,
            ot_spend_committed_cents=0,
            ot_hours_committed=0.00,
            headcount_active=0,
            pipeline_fte=0.00,
            reforecast_generation=0,
            version=1,
        )
        assert cycle["requirements_locked_at"] is None, "requirements_locked_at starts null"
        assert cycle["published_at"] is None, "published_at starts null"

    def test_omitting_every_optional_input_applies_the_declared_defaults(self, api):
        """The four optional cycle inputs fall back to their declared defaults.

        "`interval_minutes` fixes the width of one planning interval and must
        be 15, 30 or 60, defaulting to 30. `requirement_basis` decides which
        staffing variant is authoritative and must be `SERVICE_LEVEL`,
        `OCCUPANCY` or `MAX_OF_BOTH`, defaulting to `MAX_OF_BOTH`.
        `ot_budget_cents` is the hard ceiling on cumulative accepted-overtime
        spend for the whole cycle, an integer of zero or more, defaulting to
        1,000,000 cents. `intraday_alert_short_threshold` is the number of
        short intervals at or above which the cycle auto-escalates its
        posture, an integer of at least 1, defaulting to 3."

        Design: Corner/entities/planning_cycle_defaults_applied_when_optionals_omitted
        """
        set_clock(api, CANONICAL_CLOCK)

        created = validate_success(
            api.create_planning_cycle(
                _minimal_cycle_payload("W37-DEFAULTS"), PLANNER_HEADERS
            ),
            201,
        )

        assert created["interval_minutes"] == DEFAULT_INTERVAL_MINUTES
        assert created["requirement_basis"] == DEFAULT_REQUIREMENT_BASIS
        stored = read_cycle(api, created["id"])
        assert stored["ot_budget_cents"] == DEFAULT_OT_BUDGET_CENTS
        assert (
            stored["intraday_alert_short_threshold"]
            == DEFAULT_INTRADAY_ALERT_SHORT_THRESHOLD
        )
        assert stored["posture"] == POSTURE_OPEN


class TestLaborAgreementRetrieval:
    """Reading an agreement back returns exactly the stored row."""

    def test_get_returns_the_stored_row_with_its_defaults_and_zero_enrolment(self, api):
        """A read echoes every ceiling, the defaulted premium and an empty enrolment.

        "`ot_premium_multiplier` is a number of at least 1.00, defaulting to
        1.00, applied on top of the cycle's overtime tier multiplier. One
        derived field, `enrolled_agent_count`, tracks how many agents currently
        reference the agreement while their employment `status` is `ACTIVE` or
        `LEAVE`; terminated agents drop out of the count."

        Design: Corner/entities/labor_agreement_get_returns_stored_row
        """
        set_clock(api, CANONICAL_CLOCK)
        payload = f.labor_agreement_payload(
            code="LA-CORE",
            min_rest_hours=11,
            max_weekly_hours=45,
            max_consecutive_days=6,
            vto_min_notice_hours=12,
            preference_honor_floor_pct=0.5000,
        )
        payload.pop("ot_premium_multiplier")
        created = validate_success(
            api.create_labor_agreement(payload, PLANNER_HEADERS), 201
        )

        stored = read_agreement(api, created["id"], SCHEDULER_HEADERS)

        assert_declared_fields(stored, LABOR_AGREEMENT_FIELDS)
        assert stored["code"] == "LA-CORE"
        assert_ratio(
            stored["ot_premium_multiplier"],
            DEFAULT_OT_PREMIUM_MULTIPLIER,
            "ot_premium_multiplier",
        )
        assert stored["version"] == 1, "a read is not a mutation"
        assert stored["min_rest_hours"] == 11
        assert_hours(stored["max_weekly_hours"], 45, "max_weekly_hours")
        assert stored["max_consecutive_days"] == 6
        assert stored["vto_min_notice_hours"] == 12
        assert_ratio(
            stored["preference_honor_floor_pct"], 0.5000, "preference_honor_floor_pct"
        )
        assert stored["enrolled_agent_count"] == 0


class TestUnknownIdentifiers:
    """An id-shaped value that matches nothing, on a path and in a body."""

    def test_reading_an_unknown_cycle_answers_its_own_not_found_identifier(self, api):
        """A path identifier that resolves to nothing answers 404, not an empty 200.

        "existence is validated **left to right along the URL path**: a request
        addressing a nested or compound path resolves each templated identifier
        in the order it appears, and the first identifier that resolves to
        nothing produces that entity's own not-found error with HTTP 404"

        Design: Corner/entities/planning_cycle_get_with_unknown_id_returns_not_found
        """
        set_clock(api, CANONICAL_CLOCK)

        response = api.get_planning_cycle(NON_EXISTENT_UUID, PLANNER_HEADERS)

        error = validate_error(response, ApiErrorId.PLANNING_CYCLE_NOT_FOUND.value, 404)
        envelope = response.json()
        assert envelope["response_type"] == "error", (
            f"A failure answers response_type \"error\", got {envelope['response_type']!r}"
        )
        assert error["message"], "the error envelope carries a human-readable message"

    def test_creating_a_group_under_an_unknown_cycle_answers_not_found(self, api):
        """An unresolvable body foreign key answers 404 and leaves nothing behind.

        "foreign keys supplied in a request body are resolved **in the field
        order in which they are declared for that entity in Section 3**, and
        the first unresolvable one produces its own not-found error."

        Design: Corner/entities/forecast_group_create_with_unknown_cycle_returns_not_found
        """
        set_clock(api, CANONICAL_CLOCK)

        response = api.create_forecast_group(
            f.forecast_group_payload(NON_EXISTENT_UUID), ANALYST_HEADERS
        )

        validate_error(response, ApiErrorId.PLANNING_CYCLE_NOT_FOUND.value, 404)
        _, meta = validate_paginated(api.list_forecast_groups(ANALYST_HEADERS))
        assert meta["total_count"] == 0, "no orphan group may survive the refusal"


class TestForecastGroupListing:
    """Paging a filtered list: the count is of matches, not of rows returned."""

    def test_two_pages_report_the_unpaginated_match_count(self, api):
        """A page of two out of three matches reports total_count 3 and then has_more false.

        "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside `meta`, where `total_count` is the number of rows
        matching the request's filters before pagination is applied and
        `has_more` indicates whether any matching row remains beyond the
        current page."

        Design: Corner/entities/forecast_group_list_paginates_with_total_count_and_has_more
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api, name="W37-LIST")
        make_forecast_group(api, cycle["id"], skill_code="VOICE_EN")
        make_forecast_group(
            api, cycle["id"], skill_code="VOICE_FR", base_daily_volume=600
        )
        make_forecast_group(
            api,
            cycle["id"],
            channel="CHAT",
            skill_code="CHAT_EN",
            base_daily_volume=164,
            base_aht_seconds=120,
            operating_end_minute=540,
            intraday_curve=[0.5, 0.5],
        )

        first_response = api.list_forecast_groups(
            ANALYST_HEADERS,
            params={"planning_cycle_id": cycle["id"], "limit": 2, "offset": 0},
        )
        page_one, meta_one = validate_paginated(first_response)
        page_two, meta_two = validate_paginated(
            api.list_forecast_groups(
                ANALYST_HEADERS,
                params={"planning_cycle_id": cycle["id"], "limit": 2, "offset": 2},
            )
        )

        assert first_response.json()["response_type"] == "array", (
            "a list answers response_type \"array\""
        )
        assert len(page_one) == 2, f"expected 2 rows on the first page, got {len(page_one)}"
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert len(page_two) == 1, f"expected 1 row on the second page, got {len(page_two)}"
        assert meta_two["limit"] == 2
        assert meta_two["offset"] == 2
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert page_one[0]["id"] != page_two[0]["id"], "pages must not repeat a row"

        unpaged, meta_unpaged = validate_paginated(
            api.list_forecast_groups(
                ANALYST_HEADERS, params={"planning_cycle_id": cycle["id"]}
            )
        )
        assert len(unpaged) == 3
        assert meta_unpaged["limit"] == DEFAULT_LIMIT
        assert meta_unpaged["offset"] == DEFAULT_OFFSET
        assert meta_unpaged["total_count"] == 3
        assert meta_unpaged["has_more"] is False


class TestRejectedWriteBodies:
    """Two body-shape refusals, each leaving the collection empty."""

    def test_creating_an_agent_without_skills_is_rejected(self, api):
        """The skills array is required, so omitting it creates no agent at all.

        "then request-body shape (`ERR_VALIDATION`, HTTP 422 — required fields
        present, correct types, enum members recognised, numeric ranges and
        array lengths as specified in Section 3)"

        Design: Corner/entities/agent_create_missing_required_skills_rejected
        """
        set_clock(api, CANONICAL_CLOCK)
        agreement = make_labor_agreement(api, code="LA-CORE")
        payload = f.agent_payload(
            agreement["id"],
            employee_code="E-001",
            full_name="Agent One",
            seniority_rank=1,
            weekly_contracted_hours=37.5,
            hourly_rate_cents=2400,
        )
        payload.pop("skills")

        response = api.create_agent(payload, SCHEDULER_HEADERS)

        validate_error(response, ApiErrorId.VALIDATION.value, 422)
        _, meta = validate_paginated(api.list_agents(SCHEDULER_HEADERS))
        assert meta["total_count"] == 0, "a refused creation stores no agent"

    def test_an_unrecognised_confidence_tier_is_rejected(self, api):
        """A confidence tier outside the three declared members is refused.

        "`confidence_tier` must be `HIGH`, `MEDIUM` or `LOW`."

        Design: Corner/entities/marketing_event_unknown_confidence_tier_invalid_enum_rejected
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api, name="W37-ENUM")
        group = make_forecast_group(api, cycle["id"])

        response = api.create_marketing_event(
            f.marketing_event_payload(
                cycle["id"],
                group["id"],
                name="Bad Tier",
                uplift_pct=0.5000,
                confidence_tier="CERTAIN",
            ),
            ANALYST_HEADERS,
        )

        validate_error(response, ApiErrorId.VALIDATION.value, 422)
        _, meta = validate_paginated(api.list_marketing_events(ANALYST_HEADERS))
        assert meta["total_count"] == 0, "a refused creation stores no marketing event"


class TestServerOwnedFields:
    """Fields the server derives or mints, offered by the client and discarded."""

    def test_hiring_class_ramp_is_computed_and_a_supplied_graduate_count_is_ignored(
        self, api
    ):
        """The ramp dates and the graduate count come from the formulas, not the payload.

        "`expected_graduates` is `seats` multiplied by one minus
        `expected_attrition_pct`, rounded **down** to a whole number.
        `nesting_from_date` is `start_date` advanced by `training_weeks`
        multiplied by seven days. `productive_from_date` is `start_date`
        advanced by the sum of `training_weeks` and `nesting_weeks`, multiplied
        by seven days. `effective_fte_at_horizon_end` then evaluates the ramp at
        the cycle's `horizon_end_date`: if that date falls strictly before
        `nesting_from_date`, the class contributes 0.00"

        Design: Corner/entities/hiring_class_computed_graduates_extra_field_input_ignored
        """
        set_clock(api, CANONICAL_CLOCK)
        agreement = make_labor_agreement(api, code="LA-CORE")
        cycle = make_planning_cycle(api, name="Q4-PIPE")

        created = validate_success(
            api.create_hiring_class(
                f.hiring_class_payload(
                    cycle["id"],
                    agreement["id"],
                    cohort_name="CLASS-A",
                    skill_code="VOICE_EN",
                    start_date=HORIZON_START,
                    seats=24,
                    training_weeks=4,
                    nesting_weeks=2,
                    expected_attrition_pct=0.1250,
                    graduate_hourly_rate_cents=2000,
                    graduate_weekly_hours=37.5,
                    expected_graduates=99,
                ),
                PLANNER_HEADERS,
            ),
            201,
        )

        assert created["expected_graduates"] == 21, (
            "floor(24 * (1 - 0.1250)) is 21, whatever the payload claimed"
        )
        stored = read_hiring_class(api, created["id"])
        assert_declared_fields(stored, HIRING_CLASS_FIELDS)
        assert stored["nesting_from_date"] == "2026-10-05"
        assert stored["productive_from_date"] == "2026-10-19"
        assert_hours(
            stored["effective_fte_at_horizon_end"], 0.00, "effective_fte_at_horizon_end"
        )
        assert stored["status"] == CLASS_STATUS_PLANNED
        assert stored["graduated_agent_count"] == 0
        assert_cycle_ledgers(read_cycle(api, cycle["id"]), pipeline_fte=0.00)

    def test_shift_template_mints_its_own_identity_and_award_counter(self, api):
        """A client-supplied id, version and award counter are all discarded.

        "Every persisted resource carries a server-minted `id` formatted as a
        UUID with no type prefix; clients never supply or choose an `id`. Every
        resource carries `created_at`, an ISO 8601 UTC timestamp with three
        fractional digits, recorded from the logical clock at creation."

        Design: Corner/entities/shift_template_system_fields_extra_field_input_ignored
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(api, name="W37-SYS")
        payload = f.shift_template_payload(
            cycle["id"],
            code="T-MON-AM",
            skill_code="VOICE_EN",
            start_time_local="08:00",
            duration_minutes=480,
            days_of_week=[0],
            slots_total=1,
            id=CLAIMED_ID,
            version=9,
            slots_awarded=7,
        )
        payload.pop("unpaid_break_minutes")

        created = validate_success(
            api.create_shift_template(payload, SCHEDULER_HEADERS), 201
        )

        assert created["id"] != CLAIMED_ID, "the server mints the id itself"
        assert_common_fields(created)
        assert created["version"] == 1, "version starts at 1 on creation"
        assert created["slots_awarded"] == 0, "the award counter starts at zero"
        stored = read_template(api, created["id"])
        assert_declared_fields(stored, SHIFT_TEMPLATE_FIELDS)
        assert stored["unpaid_break_minutes"] == DEFAULT_UNPAID_BREAK_MINUTES
        for label in ("created_at", "updated_at"):
            stamp = stored[label]
            assert is_iso8601_timestamp(stamp), (
                f"{label} is not an ISO 8601 instant: {stamp!r}"
            )
            assert stamp.endswith("Z") and "." in stamp, (
                f"{label} must be a UTC instant with fractional seconds: {stamp!r}"
            )
            assert len(stamp.split(".")[1]) == 4, (
                f"{label} must carry three fractional digits: {stamp!r}"
            )

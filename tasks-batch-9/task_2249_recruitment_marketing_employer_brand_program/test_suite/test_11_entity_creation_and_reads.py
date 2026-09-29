"""Opening values, single reads and the declared list order of the program's own records."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    anonymous_headers,
    brand_lead_headers,
    media_buyer_headers,
    persona_researcher_headers,
)


def test_a_new_program_opens_at_its_declared_zero_point(api):
    """PRD §3.1: "A freshly created program is initialised to a known zero point:
    `committed_budget_cents` is 0, `send_quota_used` is 0, `brand_health_score` is `100.00`,
    `last_attribution_recompute_at` is null because no attribution run has happened yet, and
    `available_budget_cents` equals the sum of the three channel-type pools plus the flex reserve."
    PRD §3.1: "The lead may also nominate an `attribution_model` of either `LINEAR` or
    `POSITION_BASED`; when the field is omitted the program is created with `LINEAR`."
    PRD §2.4: "On creation, `version` starts at 1 and `updated_at` equals `created_at`."

    Design: Corner/entities/create_program_returns_201_with_zeroed_counters_and_full_health
    """
    response = api.create_program(
        {"name": "Talent Brand FY26", "fiscal_year": 2026}, brand_lead_headers()
    )

    program = validate_success(response, 201)
    assert is_valid_uuid(program["id"]), program
    assert program["version"] == 1, program
    assert program["attribution_model"] == "LINEAR", program
    assert program["pool_job_board_cents"] == 0, program
    assert program["pool_social_cents"] == 0, program
    assert program["pool_programmatic_cents"] == 0, program
    assert program["flex_reserve_cents"] == 0, program
    assert program["send_quota_total"] == 0, program
    assert program["send_quota_used"] == 0, program
    a.assert_cents(program["committed_budget_cents"], 0, "committed_budget_cents")
    a.assert_cents(program["available_budget_cents"], 0, "available_budget_cents")
    a.assert_brand_health(program["brand_health_score"], 100.00)
    assert program["last_attribution_recompute_at"] is None, program
    a.assert_mutable_row(program, expected_version=1)
    assert program["updated_at"] == program["created_at"], program


def test_reading_one_job_family_echoes_its_inputs_and_derives_its_availability(api):
    """PRD §2.6: "At the family level, `reserved_cents` is the sum of `delta_cents` over that
    family's entries whose `bucket` is `FAMILY_DEDICATED`, and `dedicated_available_cents` is
    `dedicated_budget_cents` less `reserved_cents`."
    PRD §3.1: "A new family starts with `reserved_cents` at 0 and `dedicated_available_cents` equal
    to its `dedicated_budget_cents`."

    Design: Corner/entities/get_job_family_returns_stored_inputs_and_derived_availability
    """
    program = fx.create_program(api)
    created = fx.create_job_family(api, program["id"], dedicated_budget_cents=800000)

    response = api.get_job_family(created["id"], persona_researcher_headers())

    family = validate_success(response, 200)
    assert family["program_id"] == program["id"], family
    assert family["name"] == "Software Engineering", family
    assert family["code"] == "SWE", family
    a.assert_cents(family["cpqa_target_cents"], 15000, "cpqa_target_cents")
    assert family["priority_rank"] == 1, family
    a.assert_family_reservation(
        family, reserved_cents=0, dedicated_available_cents=800000
    )
    a.assert_cents(family["dedicated_budget_cents"], 800000, "dedicated_budget_cents")
    a.assert_mutable_row(family, expected_version=1)
    assert family["updated_at"] == family["created_at"], family


def test_job_families_page_by_priority_rank_and_never_leak_across_programs(api):
    """PRD §2.3: "job families are ordered by `priority_rank` ascending and then `created_at`
    ascending"
    PRD §2.3: "Successful list responses populate four pagination keys inside `meta`: `limit` and
    `offset` echo the effective values applied to the query, `total_count` reports how many rows
    matched the filters before the page window was applied, and `has_more` is true exactly when rows
    remain beyond the current window."

    Design: Corner/entities/list_job_families_filters_by_program_and_paginates_in_declared_order
    """
    first_program = fx.create_program(api, name="Program A")
    second_program = fx.create_program(api, name="Program B")
    engineering = fx.create_job_family(api, first_program["id"])
    sales = fx.create_job_family(
        api,
        first_program["id"],
        name="Enterprise Sales",
        code="SALES",
        cpqa_target_cents=22000,
        priority_rank=2,
    )
    operations = fx.create_job_family(
        api,
        first_program["id"],
        name="Operations",
        code="OPS",
        cpqa_target_cents=9000,
        priority_rank=3,
    )
    other = fx.create_job_family(
        api,
        second_program["id"],
        name="Data Science",
        code="DATA",
        cpqa_target_cents=30000,
        priority_rank=1,
    )

    response = api.list_job_families(
        media_buyer_headers(), {"program_id": first_program["id"], "limit": 2, "offset": 1}
    )

    page, meta = validate_paginated(response)
    assert [row["id"] for row in page] == [sales["id"], operations["id"]], page
    assert meta["total_count"] == 3, meta
    assert meta["limit"] == 2, meta
    assert meta["offset"] == 1, meta
    assert meta["has_more"] is False, meta
    everything = fx.list_job_families(api, program_id=first_program["id"])
    assert [row["id"] for row in everything] == [
        engineering["id"],
        sales["id"],
        operations["id"],
    ], everything
    a.assert_ordered_by(everything, "priority_rank", "created_at")
    assert other["id"] not in [row["id"] for row in everything], everything


def test_registering_a_channel_without_its_type_is_a_schema_refusal(api):
    """PRD §3.2: "Registering one names the owning program, a `name` of 1 to 120 characters, and a
    `channel_type` chosen from `JOB_BOARD`, `SOCIAL`, `PROGRAMMATIC`, `CAREER_SITE`, `EVENT` and
    `EMAIL`."
    PRD §2.9: "4. On every write endpoint, the request body must conform to the endpoint's input
    schema — required fields present, types correct, enum members valid, integer ranges respected,
    ISO 8601 datetimes well formed — else `ERR_INVALID_REQUEST` (422)."
    PRD §3.2: "A new channel reports `spent_cents` 0, `credited_qualified_bp` 0,
    `active_flight_count` 0, `pacing_status` `PACING_UNKNOWN`, `idle_since` null, and both
    `blended_target_cents` and `cpqa_cents` null."

    Design: Corner/entities/create_channel_without_channel_type_returns_invalid_request
    """
    program = fx.create_program(api)

    refused = api.create_channel(
        {"program_id": program["id"], "name": "Board A", "daily_capacity_cents": 100000},
        brand_lead_headers(),
    )
    accepted = api.create_channel(
        {
            "program_id": program["id"],
            "name": "Board A",
            "channel_type": "JOB_BOARD",
            "daily_capacity_cents": 100000,
        },
        brand_lead_headers(),
    )

    validate_error(refused, ApiErrorId.INVALID_REQUEST, 422)
    channel = validate_success(accepted, 201)
    assert channel["channel_type"] == "JOB_BOARD", channel
    assert channel["min_flight_days"] == 1, channel
    a.assert_cents(channel["spent_cents"], 0, "spent_cents")
    assert channel["credited_qualified_bp"] == 0, channel
    assert channel["active_flight_count"] == 0, channel
    assert channel["pacing_status"] == "PACING_UNKNOWN", channel
    assert channel["blended_target_cents"] is None, channel
    assert channel["cpqa_cents"] is None, channel
    assert channel["idle_since"] is None, channel
    assert len(fx.list_channels(api, program_id=program["id"])) == 1


def test_joining_the_talent_community_applies_the_declared_consent_defaults(api):
    """PRD §3.7: "It may also set `frequency_cap_per_30d`, the maximum number of messages the
    member will accept inside a trailing 30-day window, an integer of at least 1 that defaults to
    4."
    PRD §3.7: "A new member is in `consent_status` `PENDING_CONFIRMATION` with `sent_count_total` 0
    and `last_sent_at`, `consent_confirmed_at` and `consent_changed_at` all null."
    PRD §3.7: "The server mints a `consent_token` and echoes it on the registration response; this
    is a double opt-in system and the token is the only way to complete it."

    Design: Corner/entities/talent_community_member_applies_declared_defaults_on_join
    """
    program = fx.create_program(api)

    response = api.create_talent_community_member(
        f.member_payload(program["id"], "joiner@example.com"), anonymous_headers()
    )

    member = validate_success(response, 201)
    assert member["frequency_cap_per_30d"] == 4, member
    assert member["consent_status"] == "PENDING_CONFIRMATION", member
    assert isinstance(member["consent_token"], str) and member["consent_token"], member
    assert member["consent_token"] != member["id"], member
    assert member["interest_job_family_id"] is None, member
    assert member["sent_count_total"] == 0, member
    assert member["last_sent_at"] is None, member
    assert member["consent_confirmed_at"] is None, member
    assert member["consent_changed_at"] is None, member
    a.assert_mutable_row(member, expected_version=1)

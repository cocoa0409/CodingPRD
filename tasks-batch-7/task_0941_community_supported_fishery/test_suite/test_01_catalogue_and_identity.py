"""Catalogue creation, declared defaults, computed catalogue fields, identity and lookup."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_cold_chain_event,
    assert_quota_ledger,
    assert_season,
    assert_share_plan,
    new_member,
    new_season,
    new_vessel,
    set_clock,
    setup_fleet,
    setup_landed_lot,
    setup_open_season,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
HUB_OP = TEST_USERS["hub_operator_headers"]


def test_season_creation_returns_a_planning_season_with_its_declared_openers(api):
    """PRD 3.1: "A newly created season sits in `PLANNING`, its `shortfall_flag_count` at 0
    and its `true_up_run_at` null."
    PRD 2.4: "`version` starts at 1 when the resource is created and increases by exactly 1
    on every mutation of that resource; `updated_at` is refreshed to the current instant on
    the same mutations."
    PRD 2.4: "Every resource carries a server-minted `id` — a UUID string with no type
    prefix — and a `created_at` timestamp."

    Design: Corner/entities/season_creation_returns_all_declared_fields
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.create_season(
        {
            "season_code": "CSF-2026",
            "start_date": "2026-05-04T00:00:00Z",
            "end_date": "2026-09-21T00:00:00Z",
            "total_weeks": 20,
            "ambient_band": "HOT",
            "offered_species": ["COD", "SALMON"],
            "landing_commit_lead_hours": 72,
        },
        ADMIN,
    )
    season = validate_success(response, 201)
    assert_season(season)
    assert season["status"] == "PLANNING", "a newly created season sits in PLANNING"
    assert season["shortfall_flag_count"] == 0
    assert season["true_up_run_at"] is None
    assert season["version"] == 1
    assert season["total_weeks"] == 20


def test_season_optional_inputs_take_their_declared_defaults(api):
    """PRD 3.1: "The `landing_commit_lead_hours` value records how many hours before a week's
    scheduled delivery instant the CSF commits its landing plan; it must be an integer between
    0 and 336, and when it is omitted the season is created with the standard lead
    `DEFAULT_LANDING_COMMIT_LEAD_HOURS` of 72 hours."
    PRD 3.1: "The `ambient_band` records the temperature band the region sits in for the
    summer and governs how long a gel pack lasts; when it is omitted the season is created
    as `MILD`."

    Design: Corner/entities/season_landing_commit_lead_hours_default_applied
    """
    set_clock("2026-05-01T00:00:00Z")
    season = validate_success(
        api.create_season(
            {
                "season_code": "CSF-DEF",
                "start_date": "2026-05-04T00:00:00Z",
                "end_date": "2026-09-21T00:00:00Z",
                "total_weeks": 20,
                "offered_species": ["COD"],
            },
            ADMIN,
        ),
        201,
    )
    assert season["landing_commit_lead_hours"] == 72
    assert season["ambient_band"] == "MILD"


def test_share_plan_computed_fields_follow_the_three_axes(api):
    """PRD 3.1: "The three factors are multiplied together first and the result is rounded
    half up to whole cents exactly once, at the end; `price_per_delivery_cents` is that single
    rounded figure."
    PRD 3.1: "`SHARE_SIZE_WEIGHT_UNITS` gives a plan its `weight_units`: 1 for `SMALL`, 2 for
    `MEDIUM`, 3 for `LARGE`."
    PRD 3.1: "Lastly, `scheduled_delivery_count` records how many deliveries a member who
    joins at week 1 would receive across the whole season: for a `WEEKLY` plan it is simply
    the season's `total_weeks`, and for a `BIWEEKLY` plan it is `total_weeks` divided by two
    and rounded up to the next whole number."

    A SMALL x SHELLFISH x BIWEEKLY plan prices at 2400 * 1.55 * 1.10 = 4092 cents.

    Design: Corner/entities/share_plan_computed_fields_ignore_client_supplied_values
    """
    season = new_season(offered_species=["LOBSTER"])
    plan = validate_success(
        api.create_share_plan(
            {
                "season_id": season["id"],
                "plan_code": "SML-SHELL-B",
                "share_size": "SMALL",
                "delivery_frequency": "BIWEEKLY",
                "species_tier": "SHELLFISH",
            },
            ADMIN,
        ),
        201,
    )
    assert_share_plan(plan)
    assert plan["price_per_delivery_cents"] == 4092
    assert plan["weight_units"] == 1
    assert float(plan["target_pounds_per_delivery"]) == pytest.approx(2.50)
    assert float(plan["min_floor_pounds"]) == pytest.approx(1.00)
    assert plan["scheduled_delivery_count"] == 10


def test_cold_chain_event_carries_no_version_and_no_updated_at(api):
    """PRD 2.4: "There is exactly one exception in this system: a cold-chain leg record is an
    append-only observation and is never edited after it is written, so it carries `id` and
    `created_at` and carries neither `updated_at` nor `version`."
    PRD 3.6: "The record is stamped with a `recorded_at` from the logical clock and a
    `recorded_by_user_id` taken from the caller's `X-User-ID`."
    PRD 3.6: "The leg's `breach_type` is `BOTH` when both are exceeded, `SINGLE_EXCURSION`
    when only the leg's own figure is, `CUMULATIVE` when only the running total is, and `NONE`
    when neither is."

    Design: Corner/entities/cold_chain_event_is_immutable_and_carries_no_version
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    fleet = setup_fleet(ctx["season_id"], species="SALMON")
    landing = setup_landed_lot(ctx["season_id"], fleet, "SALMON", 5.00)

    event = validate_success(
        api.log_cold_chain_event(
            {
                "landing_lot_id": landing["lot_id"],
                "custody_leg": "DOCK_TO_HUB",
                "minutes_above_threshold": 5,
                "peak_temp_c": 3.0,
            },
            HUB_OP,
        ),
        201,
    )
    assert_cold_chain_event(event)
    assert "version" not in event, "an append-only cold-chain record carries no version"
    assert "updated_at" not in event, "an append-only cold-chain record carries no updated_at"
    assert event["recorded_by_user_id"] == "hub-op-1"
    assert event["breach_type"] == "NONE"

    lot = validate_success(api.get_landing_lot(landing["lot_id"], ADMIN))
    assert lot["quality_status"] == "CLEAR"


def test_quota_ledger_opens_with_remaining_equal_to_its_entitlement(api):
    """PRD 3.3: "The ledger carries an `entitlement_pounds` figure greater than zero with at
    most two decimals, and its `committed_pounds` starts at 0 while `remaining_pounds` starts
    equal to the entitlement."
    PRD 3.3: "Four more inputs describe the fishery: an `area_closed` boolean defaulting to
    false, a `species_open_date` and a `species_close_date` bounding the period during which
    the species may be landed in that area (both boundaries inclusive), and a non-empty
    `permitted_gears` array."
    PRD 3.3: "It opens in `OPEN`."

    Design: Corner/entities/quota_ledger_remaining_pounds_is_derived_not_input
    """
    season = new_season(offered_species=["SALMON"])
    vessel = new_vessel()
    ledger = validate_success(
        api.create_quota_ledger(
            {
                "vessel_id": vessel["id"],
                "season_id": season["id"],
                "species": "SALMON",
                "management_area": "GOM-1",
                "entitlement_pounds": 250.00,
                "species_open_date": "2026-05-01T00:00:00Z",
                "species_close_date": "2026-09-30T00:00:00Z",
                "permitted_gears": ["HOOK_AND_LINE"],
                "area_sensitivity_penalty": 0,
                "species_stock_adjustment": 0,
            },
            ADMIN,
        ),
        201,
    )
    assert_quota_ledger(ledger)
    assert float(ledger["committed_pounds"]) == pytest.approx(0.00)
    assert float(ledger["remaining_pounds"]) == pytest.approx(250.00)
    assert ledger["status"] == "OPEN"
    assert ledger["area_closed"] is False
    assert ledger["area_sensitivity_penalty"] == 0


def test_season_without_total_weeks_is_rejected_as_a_validation_error(api):
    """PRD 2.5: "On every write endpoint, every field the endpoint marks as required is
    present and non-null — otherwise `ERR_VALIDATION`."
    PRD 3.1: "An administrator creates one by supplying a `season_code` of between 1 and 32
    characters that no other season already uses, a `start_date` and an `end_date` as ISO 8601
    UTC instants, and a `total_weeks` count between 1 and 40 that fixes the delivery calendar"

    Design: Corner/entities/season_missing_required_total_weeks_returns_validation_error
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.create_season(
        {
            "season_code": "CSF-BAD",
            "start_date": "2026-05-04T00:00:00Z",
            "end_date": "2026-09-21T00:00:00Z",
            "ambient_band": "HOT",
            "offered_species": ["COD"],
        },
        ADMIN,
    )
    assert response.status_code == 400
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)


def test_share_plan_with_an_undeclared_share_size_is_rejected_as_an_enum_error(api):
    """PRD 2.5: "On every write endpoint carrying one of them, each supplied enum-typed field
    holds a declared member — otherwise `ERR_INVALID_ENUM`. This rung owns exactly and only
    the following fields, and no other field in the system routes an out-of-list value here: a
    share plan's `share_size`, `delivery_frequency` and `species_tier`"

    Design: Corner/entities/share_plan_invalid_enum_share_size_rejected
    """
    season = new_season(offered_species=["COD"])
    response = api.create_share_plan(
        {
            "season_id": season["id"],
            "plan_code": "BAD-PLAN",
            "share_size": "XLARGE",
            "delivery_frequency": "WEEKLY",
            "species_tier": "WHITEFISH",
        },
        ADMIN,
    )
    assert response.status_code == 400
    validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value)


def test_unknown_season_id_returns_season_not_found(api):
    """PRD 2.5: "The season named in the path, or in a `season_id` body field, exists —
    otherwise `ERR_SEASON_NOT_FOUND`. This applies to every endpoint carrying a season
    identifier."

    Design: Corner/entities/season_not_found_on_read_returns_404
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_season("00000000-0000-4000-8000-000000000001", ADMIN)
    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_SEASON_NOT_FOUND.value)


def test_unknown_pickup_window_id_returns_catalog_not_found(api):
    """PRD 2.5: "The share plan, delivery zone, pickup hub or pickup window named in the path
    or in a `share_plan_id`, `delivery_zone_id`, `pickup_hub_id` or `pickup_window_id` body
    field exists — otherwise `ERR_CATALOG_NOT_FOUND`. This applies to every endpoint carrying
    a catalogue identifier."

    Design: Corner/entities/catalog_not_found_on_pickup_window_read_returns_404
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_pickup_window("00000000-0000-4000-8000-000000000002", ADMIN)
    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_CATALOG_NOT_FOUND.value)


def test_unknown_member_id_returns_member_not_found(api):
    """PRD 2.5: "The member named in the path or in a `member_id` body field exists —
    otherwise `ERR_MEMBER_NOT_FOUND`, on every endpoint carrying a member identifier."

    Design: Corner/entities/member_not_found_on_read_returns_404
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_member("00000000-0000-4000-8000-000000000003", ADMIN)
    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)


def test_unknown_subscription_id_returns_subscription_not_found(api):
    """PRD 2.5: "The subscription named in the path or in a `subscription_id`,
    `from_subscription_id`, `to_subscription_id` or `renewed_from_subscription_id` body field
    exists — otherwise `ERR_SUBSCRIPTION_NOT_FOUND`, on every endpoint carrying a subscription
    identifier."

    Design: Corner/entities/subscription_not_found_on_read_returns_404
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_subscription("00000000-0000-4000-8000-000000000004", ADMIN)
    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND.value)


def test_unknown_vessel_id_returns_vessel_not_found(api):
    """PRD 2.5: "The vessel named in the path or in a `vessel_id` body field exists —
    otherwise `ERR_VESSEL_NOT_FOUND`, on every endpoint carrying a vessel identifier."

    Design: Corner/entities/vessel_not_found_on_read_returns_404
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_vessel("00000000-0000-4000-8000-000000000005", ADMIN)
    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_VESSEL_NOT_FOUND.value)


def test_unknown_quota_ledger_id_returns_quota_ledger_not_found(api):
    """PRD 2.5: "The quota ledger named in a `quota_ledger_id` body field exists — otherwise
    `ERR_QUOTA_LEDGER_NOT_FOUND`. This rung guards trip creation and the single-ledger read."

    Design: Corner/entities/quota_ledger_not_found_on_read_returns_404
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_quota_ledger("00000000-0000-4000-8000-000000000006", ADMIN)
    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_QUOTA_LEDGER_NOT_FOUND.value)


def test_unknown_trip_id_returns_trip_not_found(api):
    """PRD 2.5: "The trip named in the path or in a `trip_id` body field exists — otherwise
    `ERR_TRIP_NOT_FOUND`, on every endpoint carrying a trip identifier."

    Design: Corner/entities/trip_not_found_on_read_returns_404
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_trip("00000000-0000-4000-8000-000000000007", ADMIN)
    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_TRIP_NOT_FOUND.value)


def test_unknown_landing_lot_id_returns_landing_lot_not_found(api):
    """PRD 2.5: "The landing lot named in the path or in a `landing_lot_id` or
    `substitute_landing_lot_id` body field exists — otherwise `ERR_LANDING_LOT_NOT_FOUND`, on
    every endpoint carrying a lot identifier."

    Design: Corner/entities/landing_lot_not_found_on_read_returns_404
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_landing_lot("00000000-0000-4000-8000-000000000008", ADMIN)
    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_LANDING_LOT_NOT_FOUND.value)


def test_unknown_sub_lot_id_returns_sub_lot_not_found(api):
    """PRD 2.5: "The sub-lot named in the path or in a `sub_lot_id` body field exists —
    otherwise `ERR_SUB_LOT_NOT_FOUND`, on every endpoint carrying a sub-lot identifier."

    Design: Corner/entities/sub_lot_not_found_on_read_returns_404
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_sub_lot("00000000-0000-4000-8000-000000000009", ADMIN)
    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_SUB_LOT_NOT_FOUND.value)


def test_unknown_share_delivery_id_returns_share_delivery_not_found(api):
    """PRD 2.5: "The share delivery named in the path or in a `share_delivery_id` body field
    exists — otherwise `ERR_SHARE_DELIVERY_NOT_FOUND`, on every endpoint carrying a delivery
    identifier."

    Design: Corner/entities/share_delivery_not_found_on_read_returns_404
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_share_delivery("00000000-0000-4000-8000-00000000000a", ADMIN)
    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_SHARE_DELIVERY_NOT_FOUND.value)


def test_unknown_substitution_id_returns_substitution_not_found(api):
    """PRD 2.5: "The substitution offer named in the path exists — otherwise
    `ERR_SUBSTITUTION_NOT_FOUND`. This rung guards offer acceptance, offer rejection and the
    single-offer read."

    Design: Corner/entities/substitution_not_found_on_read_returns_404
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_substitution("00000000-0000-4000-8000-00000000000b", ADMIN)
    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_SUBSTITUTION_NOT_FOUND.value)


def test_unknown_skip_request_id_returns_skip_request_not_found(api):
    """PRD 2.5: "The skip request named in the path exists — otherwise
    `ERR_SKIP_REQUEST_NOT_FOUND`, guarding skip revocation and the single-skip read."

    Design: Corner/entities/skip_request_not_found_on_read_returns_404
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_skip_request("00000000-0000-4000-8000-00000000000c", ADMIN)
    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_SKIP_REQUEST_NOT_FOUND.value)


def test_unknown_settlement_id_returns_settlement_not_found(api):
    """PRD 2.5: "The settlement statement named in the path exists — otherwise
    `ERR_SETTLEMENT_NOT_FOUND`, guarding statement finalization, statement payment and the
    single-statement read."

    Design: Corner/entities/settlement_not_found_on_read_returns_404
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_settlement("00000000-0000-4000-8000-00000000000d", ADMIN)
    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_SETTLEMENT_NOT_FOUND.value)


def test_unknown_share_transfer_id_returns_share_transfer_not_found(api):
    """PRD 2.5: "The share transfer named in the path exists — otherwise
    `ERR_SHARE_TRANSFER_NOT_FOUND`, guarding transfer acceptance, transfer decline and the
    single-transfer read."

    Design: Corner/entities/share_transfer_not_found_on_read_returns_404
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_share_transfer("00000000-0000-4000-8000-00000000000e", ADMIN)
    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_SHARE_TRANSFER_NOT_FOUND.value)


def test_unknown_recall_notice_id_returns_recall_not_found(api):
    """PRD 2.5: "The recall notice named in the path exists — otherwise `ERR_RECALL_NOT_FOUND`,
    guarding recall remediation and the single-recall read."

    Design: Corner/entities/recall_not_found_on_read_returns_404
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_recall_notice("00000000-0000-4000-8000-00000000000f", ADMIN)
    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_RECALL_NOT_FOUND.value)


def test_second_member_with_the_same_email_is_rejected(api):
    """PRD 2.5: "Scoped uniqueness holds — otherwise `ERR_DUPLICATE_RESOURCE` (HTTP 409). A
    season's `season_code`, a member's `email`, a vessel's `permit_number`, a hub's `hub_code`
    and a zone's `zone_code` are each globally unique."
    PRD 3.2: "A member is created with a `full_name` of 1 to 120 characters and an `email`
    that must contain an at-sign and must be unique across all members."

    Design: Corner/entities/duplicate_member_email_rejected
    """
    new_member(full_name="Mara One", email="m1@csf.test")
    response = api.create_member({"full_name": "Copycat", "email": "m1@csf.test"}, ADMIN)
    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_DUPLICATE_RESOURCE.value)


def test_request_without_identity_headers_is_unauthenticated(api):
    """PRD 2.1: "A request that omits either header, sends either as an empty string, or names
    a role outside that list of five is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.5: "Both `X-User-ID` and `X-User-Role` are present and non-empty, on every endpoint
    — otherwise `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/request_missing_the_user_headers_returns_unauthenticated
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.create_member({"full_name": "No Headers", "email": "nh@csf.test"}, {})
    assert response.status_code == 401
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)

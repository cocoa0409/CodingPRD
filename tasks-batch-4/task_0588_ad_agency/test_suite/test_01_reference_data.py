"""Reference data: advertisers, rate cards, staff, publisher inventory, retainers."""

from test_helpers import (
    ApiErrorId,
    assert_client,
    assert_media_placement,
    assert_retainer,
    assert_staff_member,
    create_campaign_payload,
    create_client_payload,
    create_media_placement_payload,
    create_retainer_payload,
    create_sow_payload,
    create_staff_member_payload,
    create_time_entry_payload,
    is_valid_uuid,
    make_account_manager_headers,
    make_agency_admin_headers,
    register_client,
    register_staff,
    set_clock,
    setup_base,
    validate_error,
    validate_success,
)


def test_register_advertiser_starts_active_at_version_one(api, agency_admin_headers):
    """PRD §3.1: "Registering one records its legal `name` (non-empty, at most 120 characters),
    its `industry` — one of `RETAIL`, `FINANCE`, `CPG`, `TECH` or `AUTO`, used only for
    reporting segmentation — and a non-empty `billing_email` for the accounts-payable contact.
    A newly registered advertiser has `status` `ACTIVE`."
    PRD §2.4: "`id` is a server-minted UUID with no type prefix; clients never supply it."

    Design: Corner/entities/create_client_returns_201_with_system_fields_and_active_status
    """
    set_clock("2026-06-01T00:00:00Z")

    resp = api.create_client(create_client_payload(), agency_admin_headers)
    data = validate_success(resp, 201)

    assert_client(data)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1, f"a new resource starts at version 1, got {data['version']}"
    assert data["name"] == "Acme Retail"
    assert is_valid_uuid(data["id"])

    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_register_advertiser_without_billing_email_is_malformed(api, agency_admin_headers):
    """PRD §2.8: "The request body is well formed: every required field is present, every enum
    value is a member of its declared set, every integer is an integer inside its declared
    range, every date and datetime parses, a media plan's channel whitelist is a non-empty
    array, a time entry's end instant is strictly after its start instant and falls on the same
    UTC calendar date, an insertion order's flight end is on or after its flight start, and
    every period end is strictly after its period start — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_client_missing_required_field_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")

    payload = create_client_payload()
    payload.pop("billing_email")

    resp = api.create_client(payload, agency_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert resp.status_code == 400


def test_register_advertiser_with_unknown_industry_is_malformed(api, agency_admin_headers):
    """PRD §3.1: "Registering one records its legal `name` (non-empty, at most 120 characters),
    its `industry` — one of `RETAIL`, `FINANCE`, `CPG`, `TECH` or `AUTO`, used only for
    reporting segmentation — and a non-empty `billing_email` for the accounts-payable contact."
    PRD §2.8: "The request body is well formed: every required field is present, every enum
    value is a member of its declared set, every integer is an integer inside its declared
    range, every date and datetime parses, a media plan's channel whitelist is a non-empty
    array, a time entry's end instant is strictly after its start instant and falls on the same
    UTC calendar date, an insertion order's flight end is on or after its flight start, and
    every period end is strictly after its period start — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_client_invalid_enum_industry_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")

    resp = api.create_client(create_client_payload(industry="PHARMA"), agency_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert resp.status_code == 400


def test_reading_an_unknown_advertiser_is_not_found(api, agency_admin_headers):
    """PRD §2.8: "Every identifier embedded in the URL path resolves to a live resource, checked
    left to right — otherwise the matching not-found error for the entity that failed
    (`ERR_CLIENT_NOT_FOUND`, `ERR_RETAINER_NOT_FOUND`, `ERR_SOW_NOT_FOUND`,
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_DELIVERABLE_NOT_FOUND`, `ERR_TIME_ENTRY_NOT_FOUND`,
    `ERR_VENDOR_COST_NOT_FOUND`, `ERR_MEDIA_PLAN_NOT_FOUND`, `ERR_INSERTION_ORDER_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`, `ERR_RATE_CARD_NOT_FOUND`, `ERR_STAFF_MEMBER_NOT_FOUND`), all
    HTTP 404."

    Design: Corner/entities/get_client_with_unknown_uuid_returns_client_not_found
    """
    set_clock("2026-06-01T00:00:00Z")

    resp = api.get_client("00000000-0000-4000-8000-000000000000", agency_admin_headers)
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_FOUND.value)
    assert resp.status_code == 404


def test_staff_member_daily_capacity_defaults_to_480_minutes(api, agency_admin_headers):
    """PRD §3.1: "A **staff member** has a `full_name`, a billing `grade` of `JUNIOR`, `SENIOR`
    or `DIRECTOR` (which selects the matching rate column), a `standard_daily_capacity_minutes`
    figure that defaults to the standard eight-hour day of 480 minutes and must lie between 1
    and 1440, and a `cost_rate_cents_per_hour` giving the agency's internal, unbilled cost of
    that person per hour as a non-negative integer."

    Design: Corner/entities/staff_member_capacity_minutes_default_applied_when_omitted
    """
    set_clock("2026-06-01T00:00:00Z")

    payload = create_staff_member_payload(full_name="Dana Lee", grade="SENIOR",
                                          cost_rate_cents_per_hour=6_000)
    payload.pop("standard_daily_capacity_minutes")

    data = validate_success(api.create_staff_member(payload, agency_admin_headers), 201)
    assert_staff_member(data)
    assert data["standard_daily_capacity_minutes"] == 480


def test_media_placement_min_dark_days_defaults_to_zero(api, agency_admin_headers):
    """PRD §3.1: "A **media placement** is a slot of publisher inventory, described by the
    `publisher_name` that owns it, its `channel` — one of `DISPLAY`, `VIDEO`, `SOCIAL`, `OOH`
    or `PRINT` — and a `min_dark_days` figure between 0 and 30 (defaulting to 0) that records
    how many unsold days the publisher insists on between two consecutive flights on that slot."

    Design: Corner/entities/media_placement_min_dark_days_default_zero_when_omitted
    """
    set_clock("2026-06-01T00:00:00Z")

    payload = create_media_placement_payload(publisher_name="StreamCo", channel="VIDEO")
    payload.pop("min_dark_days")

    data = validate_success(api.create_media_placement(payload, agency_admin_headers), 201)
    assert_media_placement(data)
    assert data["min_dark_days"] == 0


def test_new_retainer_derives_its_money_columns_from_the_initial_funding(api, agency_admin_headers):
    """PRD §3.1: "At creation both `funded_cents` and `balance_cents` are set to the initial
    funding amount, and `status` is `ACTIVE`."
    PRD §2.4: "`version` is an integer that starts at 1 when the resource is created."

    Design: Corner/entities/system_fields_are_server_minted_and_client_input_is_ignored
    """
    set_clock("2026-06-01T00:00:00Z")
    client = register_client()

    data = validate_success(
        api.create_retainer(
            create_retainer_payload(client["id"], initial_funding_cents=500_000),
            agency_admin_headers,
        ),
        201,
    )

    assert_retainer(data)
    assert data["funded_cents"] == 500_000
    assert data["balance_cents"] == 500_000
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


def test_campaign_under_another_advertisers_sow_is_malformed(api):
    """PRD §3.3: "The payload carries the `client_id` of the advertiser, the `sow_id` of the
    funding SOW — whose own `client_id` must equal the campaign's, or the request is rejected
    as malformed — a non-empty `name`, the `brief_summary` (non-empty, at most 2000 characters)
    that constitutes the creative brief, and an `objective` of `AWARENESS`, `CONSIDERATION` or
    `CONVERSION`."

    Design: Corner/entities/campaign_referencing_another_clients_sow_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")
    admin = make_agency_admin_headers()

    acme = register_client(name="Acme Retail", industry="RETAIL", billing_email="ap@acme.test")
    borea = register_client(name="Borea Bank", industry="FINANCE", billing_email="ap@borea.test")
    rate_card = validate_success(api.create_rate_card(
        {"name": "Standard 2026", "rate_junior_cents_per_hour": 12_000,
         "rate_senior_cents_per_hour": 20_000, "rate_director_cents_per_hour": 32_000}, admin), 201)
    ravi = register_staff(full_name="Ravi Iyer", grade="JUNIOR", cost_rate_cents_per_hour=3_000)
    am = make_account_manager_headers(ravi["id"])

    borea_sow = validate_success(
        api.create_sow(create_sow_payload(borea["id"], rate_card["id"], title="Borea SOW"), am),
        201,
    )

    resp = api.create_campaign(
        create_campaign_payload(acme["id"], borea_sow["id"], name="Mismatch",
                                brief_summary="Cross-client brief"),
        am,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert resp.status_code == 400


def test_time_entry_ending_before_it_starts_is_malformed(api):
    """PRD §3.5: "The interval must be well formed — `ended_at` strictly after `started_at`, and
    both on the same UTC calendar date — and the campaign must be `IN_FLIGHT` under a
    `COUNTERSIGNED` SOW."
    PRD §2.8: "The request body is well formed: every required field is present, every enum
    value is a member of its declared set, every integer is an integer inside its declared
    range, every date and datetime parses, a media plan's channel whitelist is a non-empty
    array, a time entry's end instant is strictly after its start instant and falls on the same
    UTC calendar date, an insertion order's flight end is on or after its flight start, and
    every period end is strictly after its period start — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/time_entry_ended_at_before_started_at_returns_invalid_request
    """
    base = setup_base()

    resp = api.create_time_entry(
        create_time_entry_payload(
            base["campaign_id"], base["dana_id"],
            "2026-06-02T12:00:00Z", "2026-06-02T09:00:00Z",
        ),
        base["dana_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert resp.status_code == 400

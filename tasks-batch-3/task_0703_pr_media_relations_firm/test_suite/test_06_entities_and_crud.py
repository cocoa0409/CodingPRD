"""Entity creation, defaults, type/required-field validation, reference integrity, retrieval."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_client,
    create_outlet,
    create_journalist,
    setup_campaign_with_media_list,
    create_media_list_current,
    create_outlet as mk_outlet,
    TEST_USERS,
    create_client_payload,
    create_campaign_payload,
    create_spokesperson_payload,
    create_journalist_payload,
    create_pitch_payload,
)

AM = TEST_USERS["account_manager_headers"]
MS = TEST_USERS["media_specialist_headers"]
PA = TEST_USERS["platform_admin_headers"]


# section: entities --------------------------------------------------------- #

def test_create_client_returns_defaults_and_zero_lifetime(api):
    """PRD §3.1: "The caller may also supply an `account_tier` of `STANDARD`, `PREMIUM`, or
    `ENTERPRISE`; if omitted it defaults to `STANDARD`."
    PRD §3.1: "A newly created client is `ACTIVE` and its `lifetime_earned_media_cents`
    starts at zero."

    Design: Corner/entities/create_client_returns_201_with_defaults_and_computed_zero
    """
    resp = api.create_client(create_client_payload(
        name="Acme", industry="TECH", monthly_retainer_cents=500000,
        monthly_hours_cap=40, overage_rate_cents=15000), AM)
    data = validate_success(resp, expected_status=201)
    assert data["account_tier"] == "STANDARD"
    assert data["status"] == "ACTIVE"
    assert data["lifetime_earned_media_cents"] == 0
    assert data["version"] == 1


def test_get_nonexistent_client_returns_not_found(api):
    """PRD §2.6: "every resource named in the request path must exist, validated left to right;
    the first path identifier that does not resolve produces `ERR_NOT_FOUND`."

    Design: Corner/entities/get_nonexistent_client_returns_not_found
    """
    resp = api.get_client(NON_EXISTENT_UUID, AM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_campaign_missing_budget_invalid_request(api):
    """PRD §2.8: "(5) request well-formedness — required fields present and well-typed, enums
    in their allowed set, and numeric ranges satisfied (`billable_hours` strictly greater
    than zero, `ends_at` strictly after `starts_at`, `period_month` matching the year-month
    format), else `ERR_INVALID_REQUEST`;"
    PRD §3.3: "An `AccountManager` creates a **Campaign** for a client by supplying the
    `client_id`, a `title`, an `objective` (one of `LAUNCH`, `THOUGHT_LEADERSHIP`, `CRISIS`,
    or `AWARENESS`), a `budget_cents` authorized media-value budget that must be strictly
    greater than zero, and a `target_beat` (one of `TECH`, `HEALTH`, `FINANCE`, `CONSUMER`,
    or `POLITICS`) used as the pitch beat-match target."

    Design: Corner/entities/create_campaign_missing_required_field_invalid_request
    """
    client = create_client()
    payload = create_campaign_payload(client["id"], title="NoBudget", objective="LAUNCH")
    payload.pop("budget_cents")
    resp = api.create_campaign(payload, AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_campaign_bad_objective_enum_invalid_request(api):
    """PRD §2.8: "(5) request well-formedness — required fields present and well-typed, enums
    in their allowed set, and numeric ranges satisfied (`billable_hours` strictly greater
    than zero, `ends_at` strictly after `starts_at`, `period_month` matching the year-month
    format), else `ERR_INVALID_REQUEST`;"
    PRD §3.3: "An `AccountManager` creates a **Campaign** for a client by supplying the
    `client_id`, a `title`, an `objective` (one of `LAUNCH`, `THOUGHT_LEADERSHIP`, `CRISIS`,
    or `AWARENESS`), a `budget_cents` authorized media-value budget that must be strictly
    greater than zero, and a `target_beat` (one of `TECH`, `HEALTH`, `FINANCE`, `CONSUMER`,
    or `POLITICS`) used as the pitch beat-match target."

    Design: Corner/entities/create_campaign_bad_enum_objective_invalid_request
    """
    client = create_client()
    resp = api.create_campaign(
        create_campaign_payload(client["id"], title="BadEnum", objective="BANANA"), AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_spokesperson_defaults_prep_buffer_to_thirty(api):
    """PRD §3.6: "optionally a `prep_buffer_minutes` value (zero or greater; defaults to 30)
    that defines the minimum gap required before and after each of this spokesperson's
    interviews."

    Design: Corner/entities/create_spokesperson_default_prep_buffer_thirty
    """
    client = create_client()
    payload = create_spokesperson_payload(client["id"], full_name="Pat Speaker", title="CEO")
    resp = api.create_spokesperson(payload, AM)
    data = validate_success(resp, expected_status=201)
    assert data["prep_buffer_minutes"] == 30
    assert data["status"] == "ACTIVE"


def test_create_pitch_journalist_not_in_list_rejected(api):
    """PRD §3.4: "At creation time the chosen journalist must already be one of the entries in
    that media list's `journalist_ids`; if the recipient is not a member of the source list,
    the create is rejected with `ERR_JOURNALIST_NOT_IN_LIST`."

    Design: Corner/entities/create_pitch_with_journalist_not_in_list_rejected
    """
    scn = setup_campaign_with_media_list()  # media list contains scn["journalist"]
    outsider = create_journalist(scn["outlet"]["id"], full_name="J Two")
    resp = api.create_pitch(
        create_pitch_payload(scn["campaign"]["id"], scn["media_list"]["id"], outsider["id"],
                             angle="outsider"), MS)
    validate_error(resp, ApiErrorId.ERR_JOURNALIST_NOT_IN_LIST.value)


def test_create_journalist_with_nonexistent_outlet_reference_not_found(api):
    """PRD §2.8: "(4) reference existence — all foreign-key body fields resolve, else
    `ERR_REFERENCE_NOT_FOUND`;"
    PRD §3.2: "A **Journalist** is created by a `MediaSpecialist` or a `PlatformAdmin`
    against a primary outlet, supplying the `outlet_id`, the journalist's `full_name`, a
    contact `email` that must be unique across all journalists, and a coverage `beat` (one
    of `TECH`, `HEALTH`, `FINANCE`, `CONSUMER`, or `POLITICS`)."

    Design: Corner/entities/create_journalist_with_nonexistent_outlet_reference_not_found
    """
    resp = api.create_journalist(
        create_journalist_payload(NON_EXISTENT_UUID, full_name="Ghost"), MS)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


def test_outlet_is_immutable_reference_data_without_version(api):
    """PRD §2.4: "The `Outlet` is immutable reference data: an outlet carries only `id` and
    `created_at`. It has no `updated_at` and no `version` field, because outlets are never
    modified after creation."

    Design: Corner/entities/outlet_is_immutable_reference_data_only_id_created_at
    """
    resp = api.create_outlet(
        {"name": "Imm Outlet", "tier": "BLOG", "monthly_unique_visitors": 50000, "domain_authority": 20}, PA)
    data = validate_success(resp, expected_status=201)
    assert data.get("id"), "outlet must carry an id"
    assert "version" not in data, "immutable outlet must not carry a version field"
    assert "updated_at" not in data, "immutable outlet must not carry an updated_at field"


def test_journalists_filterable_by_outlet_id(api):
    """PRD §3.2: "Journalists may be listed and filtered by `outlet_id`, `beat`, and `status`."

    Design: Corner/entities/journalist_outlet_id_reverse_reachable_via_filtered_list
    """
    outlet = create_outlet(name="Rev Outlet")
    journalist = create_journalist(outlet["id"], full_name="Rev Jo")
    resp = api.list_journalists(MS, params={"outlet_id": outlet["id"]})
    data, meta = validate_paginated(resp)
    ids = [j["id"] for j in data]
    assert journalist["id"] in ids, "filtered list must contain the journalist on that outlet"
    assert all(j["outlet_id"] == outlet["id"] for j in data), "filter must restrict to the outlet"

"""Resource creation/identity, RBAC, listing/pagination, and remaining error paths.

Covers corner sections entities, errors (non-stub), rbac, and endpoints.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    make_publisher_headers,
    make_advertiser_headers,
    make_listener_headers,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_publisher,
    create_active_show,
    create_published_ready_episode,
    create_feed,
    setup_monetized_published_episode,
    create_advertiser_and_active_campaign,
    create_proposed_placement,
    set_clock,
    api_client,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ============================================================================
# Corner: entities
# ============================================================================
def test_create_show_returns_201_with_defaults(api):
    """PRD §3.1: "A Publisher creates a Show, which starts life in DRAFT." and "Creation may also
    set monetization_enabled ... it defaults to false. A show exposes a computed episode_count ...
    on a freshly created show this count is zero." version starts at 1 (PRD §2.4).

    Design: Corner/entities/create_show_returns_201_with_defaults
    """
    publisher = create_publisher()
    pub_headers = make_publisher_headers(publisher["id"])
    show = validate_success(api.create_show(
        {"publisher_id": publisher["id"], "title": "S", "category": "TECH"}, pub_headers), 201)
    assert show["status"] == "DRAFT"
    assert show["monetization_enabled"] is False
    assert show["episode_count"] == 0
    assert show["version"] == 1


def test_create_show_missing_required_field_returns_invalid_request(api):
    """PRD §2.5: "Body well-formedness — required fields present, correct types, valid enum
    members — is the lowest-priority check and surfaces as ERR_INVALID_REQUEST." Omitting the
    required title yields ERR_INVALID_REQUEST.

    Design: Corner/entities/create_show_missing_required_field_returns_invalid_request
    """
    publisher = create_publisher()
    pub_headers = make_publisher_headers(publisher["id"])
    res = api.create_show({"publisher_id": publisher["id"], "category": "TECH"}, pub_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_show_invalid_enum_category_returns_invalid_request(api):
    """PRD §2.5: "Body well-formedness — required fields present, correct types, valid enum
    members — ... surfaces as ERR_INVALID_REQUEST." A category outside the IAB taxonomy is an
    invalid enum member.

    Design: Corner/entities/create_show_invalid_enum_category_returns_invalid_request
    """
    publisher = create_publisher()
    pub_headers = make_publisher_headers(publisher["id"])
    res = api.create_show(
        {"publisher_id": publisher["id"], "title": "S", "category": "SPORTS"}, pub_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_get_show_nonexistent_returns_not_found(api):
    """PRD §2.5: "If any referenced id does not resolve to an existing resource, the request is
    rejected with ERR_NOT_FOUND". A GET on a random UUID yields ERR_NOT_FOUND.

    Design: Corner/entities/get_show_nonexistent_returns_not_found
    """
    res = api.get_show(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_system_fields_generated_on_create(api):
    """PRD §2.4: "The id is a server-minted UUID with no type prefix" and "the version field is an
    integer that starts at its initial value" — on create version is 1 and id is a server UUID.

    Design: Corner/entities/system_fields_generated_on_create_input_ignored
    """
    advertiser = validate_success(api.create_advertiser(
        {"name": "AdvSys", "billing_email": "asys@x.com"}, ADMIN), 201)
    assert advertiser["version"] == 1
    assert is_valid_uuid(advertiser["id"])


def test_download_event_has_no_version_field(api):
    """PRD §2.4: "A DownloadEvent is an append-only IAB analytics record: it carries only id and
    created_at. It has no updated_at and no version, because it is never modified after ingestion."

    Design: Corner/entities/download_event_immutable_no_version_field
    """
    publisher = create_publisher()
    show = create_active_show(publisher, category="TECH")
    create_feed(publisher, show, visibility="PUBLIC")  # public => no private gate
    episode = create_published_ready_episode(publisher, show, total_ad_slots=0, offered_positions=[])
    event = validate_success(api.create_download_event(
        {"episode_id": episode["id"], "client_ip_hash": "z1", "user_agent": "ua",
         "bytes_served": 2_000_000, "event_at": "2026-01-01T03:00:00Z"}, ADMIN), 201)
    assert event["counted"] is True
    assert "version" not in event
    assert "updated_at" not in event


def test_create_show_unknown_publisher_returns_not_found(api):
    """PRD §2.5: "If any referenced id does not resolve to an existing resource, the request is
    rejected with ERR_NOT_FOUND before any business rule is evaluated." A publisher_id that does
    not exist yields ERR_NOT_FOUND.

    Design: Corner/entities/parent_relationship_show_unknown_publisher_returns_not_found
    """
    headers = make_publisher_headers(NON_EXISTENT_UUID)
    res = api.create_show(
        {"publisher_id": NON_EXISTENT_UUID, "title": "S", "category": "TECH"}, headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ============================================================================
# Corner: errors / pay_statement_with_zero_net_returns_nothing_to_pay
# ============================================================================
def test_pay_statement_with_zero_net_returns_nothing_to_pay(api):
    """PRD §3.8: "A finalized statement is paid (FINALIZED -> PAID) only when net_payable_cents is
    greater than zero; an attempt to pay a statement whose net is zero is rejected with
    ERR_NOTHING_TO_PAY." A publisher with no delivered placements has net 0.

    Design: Corner/errors/pay_statement_with_zero_net_returns_nothing_to_pay
    """
    set_clock("2026-08-15T00:00:00Z")
    publisher = create_publisher(revenue_share_pct=0.70)
    statement = validate_success(api.create_payout_statement(
        {"publisher_id": publisher["id"], "period_start": "2026-08-01T00:00:00Z",
         "period_end": "2026-09-01T00:00:00Z"}, ADMIN), 201)
    assert statement["net_payable_cents"] == 0
    get_success_data(api.finalize_payout_statement(statement["id"], ADMIN))
    res = api.pay_payout_statement(statement["id"], ADMIN)
    validate_error(res, "ERR_NOTHING_TO_PAY", expected_status=409)


# ============================================================================
# Corner: rbac
# ============================================================================
def test_listener_cannot_create_show_returns_forbidden(api):
    """PRD §4: "POST /shows ... Authorized Role(s): Publisher" and PRD §2.1: "When a
    well-authenticated caller attempts an operation their role is not permitted to perform, the
    request is rejected with ERR_FORBIDDEN." A Listener caller is forbidden.

    Design: Corner/rbac/listener_cannot_create_show_returns_forbidden
    """
    publisher = create_publisher()
    listener = get_success_data(api.create_listener({"email": "lrb@x.com", "display_name": "LRb"}, ADMIN))
    lst_headers = make_listener_headers(listener["id"])
    res = api.create_show(
        {"publisher_id": publisher["id"], "title": "SRb", "category": "TECH"}, lst_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_advertiser_cannot_suspend_show_returns_forbidden(api):
    """PRD §4: "POST /shows/{id}/suspend ... Authorized Role(s): PlatformAdmin" and PRD §2.1:
    "the request is rejected with ERR_FORBIDDEN." An Advertiser caller is forbidden.

    Design: Corner/rbac/advertiser_cannot_suspend_show_returns_forbidden
    """
    publisher = create_publisher()
    show = create_active_show(publisher, category="TECH")
    advertiser = get_success_data(api.create_advertiser({"name": "AdvRs", "billing_email": "ars@x.com"}, ADMIN))
    adv_headers = make_advertiser_headers(advertiser["id"])
    res = api.suspend_show(show["id"], adv_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_publisher_cannot_archive_other_publishers_show_returns_not_owner(api):
    """PRD §2.1: "an authenticated caller of the correct role who acts on a resource they do not
    own is rejected with ERR_NOT_RESOURCE_OWNER." Publisher 2 archiving Publisher 1's show.

    Design: Corner/rbac/publisher_cannot_archive_other_publishers_show_returns_not_owner
    """
    pub1 = create_publisher(name="Pub1", payout_email="p1own@x.com")
    pub2 = create_publisher(name="Pub2", payout_email="p2own@x.com")
    show = get_success_data(api.create_show(
        {"publisher_id": pub1["id"], "title": "SOwn", "category": "TECH"},
        make_publisher_headers(pub1["id"])))
    res = api.archive_show(show["id"], make_publisher_headers(pub2["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is rejected with
    ERR_UNAUTHENTICATED." A create with no auth headers is unauthenticated.

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    publisher = create_publisher()
    res = api.create_show(
        {"publisher_id": publisher["id"], "title": "SUn", "category": "TECH"}, headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ============================================================================
# Corner: endpoints
# ============================================================================
def test_list_episodes_filtered_by_show_id_paginated(api):
    """PRD §4: "GET /episodes | List episodes; filter by show_id, publish_status" and PRD §2.3:
    "List responses carry the pagination fields limit, offset, total_count, and has_more in the
    meta object". Two episodes under one show => total_count 2, has_more false.

    Design: Corner/endpoints/list_episodes_filtered_by_show_id_paginated
    """
    publisher = create_publisher()
    show = create_active_show(publisher, category="TECH")
    pub_headers = make_publisher_headers(publisher["id"])
    get_success_data(api.create_episode(
        {"show_id": show["id"], "title": "E1", "total_ad_slots": 0, "offered_positions": []}, pub_headers))
    get_success_data(api.create_episode(
        {"show_id": show["id"], "title": "E2", "total_ad_slots": 0, "offered_positions": []}, pub_headers))
    data, meta = validate_paginated(api.list_episodes(pub_headers, params={"show_id": show["id"]}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_list_ad_placements_filtered_by_episode_id(api):
    """PRD §4: "GET /ad-placements | List placements; filter by campaign_id, episode_id, status"
    and PRD §2.3: "List responses carry the pagination fields limit, offset, total_count, and
    has_more in the meta object". One PROPOSED placement on the episode => total_count 1.

    Design: Corner/endpoints/list_ad_placements_filtered_by_episode_id
    """
    publisher, show, episode = setup_monetized_published_episode(
        episode_overrides={"total_ad_slots": 1, "offered_positions": ["PRE_ROLL"]})
    advertiser, campaign = create_advertiser_and_active_campaign(
        campaign_overrides={"budget_cents": 1_000_000, "bid_cpm_cents": 50000})
    create_proposed_placement(advertiser, campaign, episode, forecast_impressions=5)
    adv_headers = make_advertiser_headers(advertiser["id"])
    data, meta = validate_paginated(api.list_ad_placements(adv_headers, params={"episode_id": episode["id"]}))
    assert meta["total_count"] == 1

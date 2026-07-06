"""RBAC boundaries, filtered pagination, optimistic concurrency, scheduled actions, consistency."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_client,
    create_campaign,
    create_outlet,
    create_journalist,
    create_spokesperson,
    setup_campaign_with_media_list,
    create_distribution,
    create_scheduled_press_release,
    create_coverage,
    set_clock,
    TEST_USERS,
    create_campaign_payload,
    create_interview_payload,
    create_media_list_payload,
)
from test_helpers import api_client

AM = TEST_USERS["account_manager_headers"]
MS = TEST_USERS["media_specialist_headers"]
SC = TEST_USERS["scheduling_coordinator_headers"]
PA = TEST_USERS["platform_admin_headers"]


# section: endpoints -------------------------------------------------------- #

def test_list_campaigns_filtered_by_client_id_paginated(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return."
    PRD §2.3: "Paginated list responses include the following fields in the `meta` object of
    the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §3.3: "Campaigns may be listed and filtered by `client_id` and `status`."

    Two campaigns for one client; limit=1 returns one row with total_count=2, has_more=true.

    Design: Corner/endpoints/list_campaigns_filter_by_client_id_paginated
    """
    client = create_client()
    create_campaign(client["id"], title="C1")
    create_campaign(client["id"], title="C2", objective="AWARENESS", budget_cents=900000)

    resp = api.list_campaigns(AM, params={"client_id": client["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"total_count should be 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more should be true with limit 1 of 2"
    assert len(data) == 1, f"limit=1 should return one row, got {len(data)}"


# section: rbac ------------------------------------------------------------- #

def test_media_specialist_cannot_create_campaign(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the requested
    operation under the access matrix, the request is rejected with `ERR_FORBIDDEN`."
    PRD §3.3: "An `AccountManager` creates a **Campaign** for a client by supplying the
    `client_id`, a `title`, an `objective` (one of `LAUNCH`, `THOUGHT_LEADERSHIP`, `CRISIS`,
    or `AWARENESS`), a `budget_cents` authorized media-value budget that must be strictly
    greater than zero, and a `target_beat` (one of `TECH`, `HEALTH`, `FINANCE`, `CONSUMER`,
    or `POLITICS`) used as the pitch beat-match target."

    Design: Corner/rbac/media_specialist_cannot_create_campaign_forbidden
    """
    client = create_client()
    resp = api.create_campaign(create_campaign_payload(client["id"], title="Nope"), MS)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_account_manager_cannot_create_interview(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the requested
    operation under the access matrix, the request is rejected with `ERR_FORBIDDEN`."
    PRD §3.6: "A `SchedulingCoordinator` requests one by supplying the `campaign_id`, the
    `spokesperson_id` interviewee, the `journalist_id` interviewer, optionally a `pitch_id`
    (the accepted pitch this interview fulfills, nullable), a `starts_at` instant, and an
    `ends_at` instant that must be strictly after `starts_at`."

    Design: Corner/rbac/account_manager_cannot_create_interview_forbidden
    """
    client = create_client()
    campaign = create_campaign(client["id"])
    validate_success(api.activate_campaign(campaign["id"], AM))
    outlet = create_outlet()
    journalist = create_journalist(outlet["id"], full_name="AM Jo")
    spokesperson = create_spokesperson(client["id"], full_name="AM Spoke")
    resp = api.create_interview(
        create_interview_payload(campaign["id"], spokesperson["id"], journalist["id"],
                                 "2026-04-10T10:00:00Z", "2026-04-10T11:00:00Z"), AM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_account_manager_cannot_suspend_client(api):
    """PRD §3.1: "Only a `PlatformAdmin` may suspend a client, moving its `status` to
    `SUSPENDED`."
    PRD §2.1: "If the role is recognized but is not permitted to perform the requested
    operation under the access matrix, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/suspend_client_as_account_manager_forbidden
    """
    client = create_client()
    resp = api.suspend_client(client["id"], AM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# section: cross_cutting_complexity_layers ---------------------------------- #

def test_media_list_create_with_stale_campaign_version_rejected(api):
    """PRD §2.7: "The server compares it against the target campaign's current `version`; if
    another writer has advanced the campaign's `version` since the client last read it, the
    create is rejected with `ERR_STALE_CAMPAIGN_VERSION` at HTTP status 412, because the
    client's view of which list is current is stale. On success, the create increments the
    campaign's `version` by one."

    First create supersedes and bumps the campaign version; a second create reusing the
    now-stale version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_media_list_create_stale_campaign_version
    """
    client = create_client()
    campaign = create_campaign(client["id"])
    validate_success(api.activate_campaign(campaign["id"], AM))
    outlet = create_outlet()
    journalist = create_journalist(outlet["id"], full_name="Oc Jo")

    current = validate_success(api.get_campaign(campaign["id"], AM))
    stale_v = current["version"]
    validate_success(api.create_media_list(
        create_media_list_payload(campaign["id"], [journalist["id"]], stale_v, name="First List"), MS),
        expected_status=201)

    resp = api.create_media_list(
        create_media_list_payload(campaign["id"], [journalist["id"]], stale_v, name="Second List"), MS)
    validate_error(resp, ApiErrorId.ERR_STALE_CAMPAIGN_VERSION.value)


def test_media_list_create_on_current_version_supersedes_prior(api):
    """PRD §2.7: "On success, the create increments the campaign's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_media_list_create_supersedes_prior_active_on_correct_version
    """
    client = create_client()
    campaign = create_campaign(client["id"])
    validate_success(api.activate_campaign(campaign["id"], AM))
    outlet = create_outlet()
    journalist = create_journalist(outlet["id"], full_name="Sup Jo")

    v1 = validate_success(api.get_campaign(campaign["id"], AM))["version"]
    first = validate_success(api.create_media_list(
        create_media_list_payload(campaign["id"], [journalist["id"]], v1, name="First"), MS),
        expected_status=201)

    v2 = validate_success(api.get_campaign(campaign["id"], AM))["version"]
    second = validate_success(api.create_media_list(
        create_media_list_payload(campaign["id"], [journalist["id"]], v2, name="Second"), MS),
        expected_status=201)

    assert validate_success(api.get_media_list(first["id"], MS))["status"] == "SUPERSEDED"
    assert validate_success(api.get_media_list(second["id"], MS))["status"] == "ACTIVE"


def test_period_close_with_stale_version_rejected(api):
    """PRD §2.7: "The server compares it against the period's current `version`; if another
    writer has advanced it since the client last read it — for instance by approving or
    voiding a time entry, which changes the totals the closer expects to freeze — the close
    is rejected with `ERR_STALE_PERIOD_VERSION` at HTTP status 412. On success, the close
    increments the period's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_period_close_stale_version_rejected
    """
    from test_helpers import setup_open_period, log_time_entry
    client, period = setup_open_period(period_month="2026-11")
    stale_v = period["version"]
    entry = log_time_entry(period["id"], 2.0, staff_id="staff-g", work_type="STRATEGY")
    validate_success(api.approve_time_entry(entry["id"], AM))  # bumps period.version

    resp = api.close_retainer_period(
        period["id"], {"expected_retainer_period_version": stale_v}, AM)
    validate_error(resp, ApiErrorId.ERR_STALE_PERIOD_VERSION.value)


def test_campaign_version_increments_on_media_list_create(api):
    """PRD §3.3: "A new campaign opens in `DRAFT` with `earned_media_value_cents` and
    `cost_basis_cents` at zero, `roi_ratio` null, and `version` 1."
    PRD §2.7: "On success, the create increments the campaign's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_campaign_mutation
    """
    client = create_client()
    campaign = create_campaign(client["id"])
    assert campaign["version"] == 1, "new campaign must start at version 1"
    validate_success(api.activate_campaign(campaign["id"], AM))
    outlet = create_outlet()
    journalist = create_journalist(outlet["id"], full_name="Ve Jo")

    v_before = validate_success(api.get_campaign(campaign["id"], AM))["version"]
    validate_success(api.create_media_list(
        create_media_list_payload(campaign["id"], [journalist["id"]], v_before, name="Ver List"), MS),
        expected_status=201)
    v_after = validate_success(api.get_campaign(campaign["id"], AM))["version"]
    assert v_after == v_before + 1, f"media-list create must bump campaign version by 1 ({v_before}->{v_after})"


def test_release_one_second_before_embargo_rejected(api):
    """PRD §3.5: "the current logical clock must be at or after `embargo_until` (an attempt
    before the embargo lifts is rejected with `ERR_EMBARGO_NOT_LIFTED`), and at least one
    distribution must exist for the release (otherwise `ERR_NO_DISTRIBUTIONS`)."

    Clock at 2026-03-14T23:59:59Z, one second before embargo_until 2026-03-15T00:00:00Z;
    release is rejected and the press release stays SCHEDULED.

    Design: Corner/cross_cutting_complexity_layers/scheduled_press_release_release_at_embargo_boundary
    """
    scn = setup_campaign_with_media_list()
    pr = create_scheduled_press_release(scn["campaign"]["id"], "2026-03-15T00:00:00Z", headline="Timed")
    create_distribution(pr["id"], scn["journalist"]["id"])
    set_clock("2026-03-14T23:59:59Z")

    resp = api.release_press_release(pr["id"], MS)
    validate_error(resp, ApiErrorId.ERR_EMBARGO_NOT_LIFTED.value)
    assert validate_success(api.get_press_release(pr["id"], MS))["status"] == "SCHEDULED"


# section: consistency_model ------------------------------------------------ #

def test_verified_coverage_immediately_visible_on_campaign_and_client(api):
    """PRD §3.8: "On verification, the clip's `media_value_cents` is computed and frozen using
    the verified variant of the media-value calculation, the clip's verified value is added
    to the owning campaign's `earned_media_value_cents` and to the owning client's
    `lifetime_earned_media_cents`, and the campaign's `roi_ratio` is recomputed."

    An immediate GET after verify reflects the credited 4050000 on both campaign and client.

    Design: Corner/consistency_model/verify_coverage_immediate_ledger_visible_in_get
    """
    scn = setup_campaign_with_media_list(
        client_overrides={"account_tier": "ENTERPRISE"},
        outlet_overrides={"tier": "NATIONAL", "monthly_unique_visitors": 2000000, "domain_authority": 80},
    )
    cov = create_coverage(scn["campaign"]["id"], scn["journalist"]["id"],
                          sentiment="POSITIVE", prominence="FEATURE")
    validate_success(api.verify_coverage(cov["id"], MS))

    campaign = validate_success(api.get_campaign(scn["campaign"]["id"], AM))
    client = validate_success(api.get_client(scn["client"]["id"], AM))
    assert campaign["earned_media_value_cents"] == 4050000
    assert client["lifetime_earned_media_cents"] == 4050000

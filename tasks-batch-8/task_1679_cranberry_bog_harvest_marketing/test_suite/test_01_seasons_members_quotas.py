"""Seasons, member lifecycle, and the dual quota computation (PRD §2.4, §3.1, §3.3)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_estimate,
    assert_member,
    assert_member_quota,
    assert_money,
    assert_season,
    create_active_member,
    create_bog_for,
    create_estimate,
    create_member,
    create_member_payload,
    create_season,
    create_season_payload,
    get_member,
    get_quota_for,
    open_season,
    setup_campaign_with_station,
    setup_scheduled_delivery,
    transition_member,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["coop_admin_headers"]


def test_season_created_with_setup_initial_state(api, coop_admin_headers):
    """PRD §3.1: "A new season begins in `SETUP`."
    PRD §2.4: "`id` (string): a server-minted UUID, with no type prefix."
    PRD §4: "Operations that create a new resource return `201 Created`".

    Design: Corner/entities/season_created_with_setup_initial_state
    """
    resp = api.create_season(create_season_payload(), coop_admin_headers)
    season = validate_success(resp, 201)
    assert_season(season)
    assert season["status"] == "SETUP", (
        f"new season must begin in SETUP, got {season['status']}")
    assert isinstance(season["version"], int), "version is an integer counter"


def test_member_created_pending_initial_state(api, coop_admin_headers):
    """PRD §3.1: "Each **Member** carries a unique `member_code` (duplicates
    rejected with `ERR_DUPLICATE_MEMBER_CODE`) and a display `full_name`, and
    starts life `PENDING`."

    Design: Corner/entities/member_created_pending_initial_state
    """
    resp = api.create_member(create_member_payload(), coop_admin_headers)
    member = validate_success(resp, 201)
    assert_member(member)
    assert member["status"] == "PENDING", (
        f"new member must start PENDING, got {member['status']}")


def test_create_member_with_id_input_ignored(api, coop_admin_headers):
    """PRD §2.4: "`id` (string): a server-minted UUID, with no type prefix."

    Design: Corner/entities/create_member_with_id_input_ignored
    """
    client_supplied = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
    payload = create_member_payload()
    payload["id"] = client_supplied
    resp = api.create_member(payload, coop_admin_headers)
    member = validate_success(resp, 201)
    assert member["id"] != client_supplied, (
        "the id is server-minted; a client-supplied id must not be honored")


def test_duplicate_season_year_rejected(api, coop_admin_headers):
    """PRD §3.1: "The `year` must be unique across all seasons — a second season
    for the same year is rejected with `ERR_DUPLICATE_SEASON_YEAR`".

    Design: Corner/validations/duplicate_season_year_rejected
    """
    validate_success(api.create_season(create_season_payload(), coop_admin_headers),
                     201)
    resp = api.create_season(
        create_season_payload(harvest_window_start="2026-09-01",
                              harvest_window_end="2026-11-30",
                              baseline_barrels_per_acre=180),
        coop_admin_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SEASON_YEAR)


def test_duplicate_member_code_rejected(api, coop_admin_headers):
    """PRD §3.1: "Each **Member** carries a unique `member_code` (duplicates
    rejected with `ERR_DUPLICATE_MEMBER_CODE`) and a display `full_name`, and
    starts life `PENDING`."

    Design: Corner/validations/duplicate_member_code_rejected
    """
    validate_success(api.create_member(create_member_payload(), coop_admin_headers),
                     201)
    resp = api.create_member(
        create_member_payload(full_name="Alice Again"), coop_admin_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_MEMBER_CODE)


def test_member_suspend_reinstate_cycle(api, coop_admin_headers):
    """PRD §3.1: "The member lifecycle is a simple loop administered by
    `CoopAdmin` via a transition request naming the target `to`: `PENDING →
    ACTIVE`, `ACTIVE → SUSPENDED`, `SUSPENDED → ACTIVE`".
    PRD §2.4: "`version` (integer): starts at its initial value on creation and
    increments by exactly 1 on every mutation."

    Design: Corner/state_machines/member_suspend_reinstate_cycle
    """
    member = create_active_member()
    v_after_activate = member["version"]

    suspended = validate_success(
        api.transition_member(member["id"], {"to": "SUSPENDED"},
                              coop_admin_headers), 200)
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == v_after_activate + 1, (
        "each transition increments the member version by exactly 1")

    reinstated = validate_success(
        api.transition_member(member["id"], {"to": "ACTIVE"}, coop_admin_headers),
        200)
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["version"] == v_after_activate + 2


def test_member_withdraw_terminal_lockdown(api, coop_admin_headers):
    """PRD §3.1: "`ACTIVE → WITHDRAWN`, which is terminal."
    PRD §2.8: "**State legality and uniqueness** — the target resource is in a
    state from which the requested transition is defined, including terminal
    lockdown (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/member_withdraw_terminal_lockdown
    """
    member = create_active_member()
    withdrawn = transition_member(member["id"], "WITHDRAWN")
    assert withdrawn["status"] == "WITHDRAWN"

    resp = api.transition_member(member["id"], {"to": "ACTIVE"},
                                 coop_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_member(member["id"])["status"] == "WITHDRAWN"


def test_member_withdraw_blocked_by_open_delivery(api):
    """PRD §3.1: "provided the member has no delivery still in flight in
    `SCHEDULED`, `RECEIVED`, `GRADED`, or `DISPUTED` status — `ACTIVE →
    WITHDRAWN`, which is terminal."

    Design: Corner/validations/member_withdraw_blocked_by_open_delivery
    """
    ctx = setup_campaign_with_station()
    setup_scheduled_delivery(ctx, expected_barrels=100)

    resp = api.transition_member(ctx.member["id"], {"to": "WITHDRAWN"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_member(ctx.member["id"])["status"] == "ACTIVE"


def test_quota_dual_variant_diverges_with_approved_estimate(api, coop_admin_headers):
    """PRD §3.3: "The approved-estimate variant produces the official
    `base_quota_barrels`: over the same set of `ACTIVE` bogs, take the bog's
    `APPROVED` estimate's `estimated_barrels` for the season where one exists
    and the rounded acreage product as the per-bog fallback where none does".
    PRD §3.3: "The acreage-baseline variant, stored as `baseline_quota_barrels`,
    ignores grower declarations entirely".

    Design: Difficulty/dual_variant_calc/quota_approved_estimate_vs_acreage_baseline
    """
    member = create_active_member("M100", "Alice Grower")
    bog = create_bog_for(member["id"], acres=10)
    season = create_season()
    estimate = create_estimate(bog["id"], season["id"], member["id"], 2300)
    approve_estimate(estimate["id"])

    open_season(season["id"])

    quota = get_quota_for(member["id"], season["id"])
    assert_member_quota(quota)
    assert_money(quota["base_quota_barrels"], 2300)
    assert_money(quota["baseline_quota_barrels"], 2000)  # 10 acres * 200
    assert quota["base_quota_barrels"] != quota["baseline_quota_barrels"], (
        "the two variants diverge for the same underlying bog/season data")


def test_quota_dual_variant_per_bog_fallback_mix(api, coop_admin_headers):
    """PRD §3.3: "over the same set of `ACTIVE` bogs, take the bog's `APPROVED`
    estimate's `estimated_barrels` for the season where one exists and the
    rounded acreage product as the per-bog fallback where none does (`SUBMITTED`
    and `FLAGGED` estimates never count), then round the total half-up to two
    decimal places."

    Design: Difficulty/dual_variant_calc/quota_approved_estimate_vs_acreage_baseline
    """
    member = create_active_member("M100", "Alice Grower")
    bog1 = create_bog_for(member["id"], name="North Bog", acres=10)
    create_bog_for(member["id"], name="South Bog", acres=8, variety="BEN_LEAR",
                   sprinkler_demand_gpm=400)
    season = create_season()
    estimate = create_estimate(bog1["id"], season["id"], member["id"], 2300)
    approve_estimate(estimate["id"])

    open_season(season["id"])

    quota = get_quota_for(member["id"], season["id"])
    # approved_estimate variant: 2300 (bog1) + round2(8 * 200) fallback (bog2)
    assert_money(quota["base_quota_barrels"], 3900)
    # acreage_baseline variant: round2(10*200) + round2(8*200)
    assert_money(quota["baseline_quota_barrels"], 3600)


def test_quota_excludes_submitted_estimate_from_input_set(api, coop_admin_headers):
    """PRD §3.3: "(`SUBMITTED` and `FLAGGED` estimates never count)".
    PRD §3.3: "the rounded acreage product as the per-bog fallback where none
    does".

    Design: Corner/calculations/quota_excludes_submitted_estimate_from_input_set
    """
    member = create_active_member("M100", "Alice Grower")
    bog = create_bog_for(member["id"], acres=10)
    season = create_season()
    create_estimate(bog["id"], season["id"], member["id"], 2300)  # stays SUBMITTED

    open_season(season["id"])

    quota = get_quota_for(member["id"], season["id"])
    assert_money(quota["base_quota_barrels"], 2000)  # baseline fallback: 10 * 200
    assert_money(quota["baseline_quota_barrels"], 2000)

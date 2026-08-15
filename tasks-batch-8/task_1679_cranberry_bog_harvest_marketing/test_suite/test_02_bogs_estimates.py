"""Bog registration, renovation cycle, and yield estimates (PRD §3.2, §3.3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    approve_estimate,
    assert_bog,
    assert_money,
    assert_yield_estimate,
    create_active_member,
    create_bog_for,
    create_bog_payload,
    create_estimate,
    create_estimate_payload,
    create_season,
    get_bog,
    get_estimate,
    get_quota_for,
    make_grower_headers,
    open_season,
    setup_campaign,
    transition_bog,
    transition_estimate,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["coop_admin_headers"]
OFFICER = TEST_USERS["field_officer_headers"]


def test_bog_default_frost_threshold_applied(api):
    """PRD §3.2: "Registration captures the bog `name`, planted `acres` (strictly
    greater than zero), the cranberry `variety` (one of `STEVENS`, `BEN_LEAR`,
    `MULICA_QUEEN`, or `EARLY_BLACK`), the frost-protection `sprinkler_demand_gpm`
    draw in gallons per minute (a strictly positive integer), and optionally the
    `frost_damage_threshold_c`, the actual temperature at or below which a
    completed frost event marks the vines damaged; when omitted, the threshold
    defaults to -2.0 degrees."
    PRD §3.2: "A new bog starts `ACTIVE`".

    Design: Corner/entities/bog_default_frost_threshold_applied
    """
    member = create_active_member()
    resp = api.create_bog(create_bog_payload(), make_grower_headers(member["id"]))
    bog = validate_success(resp, 201)
    assert_bog(bog)
    assert_money(bog["frost_damage_threshold_c"], -2.0)
    assert bog["status"] == "ACTIVE"
    assert bog["member_id"] == member["id"], (
        "GrowerMember caller becomes the owner via X-User-ID")


def test_get_bog_with_unknown_id_returns_not_found(api, coop_admin_headers):
    """PRD §2.8: "**Existence** — path identifiers and body-referenced ids (such
    as `season_id`, `bog_id`, `receiving_station_id`, and `harvest_ticket_id`)
    resolve to live records, validated left to right so the first missing
    reference surfaces; otherwise `ERR_NOT_FOUND`."

    Design: Corner/entities/get_bog_with_unknown_id_returns_not_found
    """
    resp = api.get_bog(NON_EXISTENT_UUID, coop_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_estimate_create_missing_required_field_returns_validation(api):
    """PRD §2.8: "Violations yield `ERR_VALIDATION`." (band 1: "required fields
    present, types well-formed, enum members valid, scalar ranges enforced").
    PRD §3.3: "A `GrowerMember` submits a **YieldEstimate** naming the `bog_id`,
    the `season_id`, and a strictly positive `estimated_barrels`".

    Design: Corner/entities/estimate_create_missing_required_field_returns_validation
    """
    member = create_active_member()
    bog = create_bog_for(member["id"])
    season = create_season()

    payload = create_estimate_payload(bog["id"], season["id"])
    del payload["estimated_barrels"]
    resp = api.create_yield_estimate(payload, make_grower_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_duplicate_estimate_per_bog_season_rejected(api):
    """PRD §3.3: "At most one estimate exists per bog-and-season pair — a second
    submission for the same pair is rejected with `ERR_DUPLICATE_ESTIMATE`."

    Design: Corner/validations/duplicate_estimate_per_bog_season_rejected
    """
    member = create_active_member()
    bog = create_bog_for(member["id"])
    season = create_season()
    create_estimate(bog["id"], season["id"], member["id"], 2300)

    resp = api.create_yield_estimate(
        create_estimate_payload(bog["id"], season["id"], estimated_barrels=2500),
        make_grower_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ESTIMATE)


def test_estimate_flagged_cannot_be_approved_directly(api):
    """PRD §3.3: "A grower revises a `FLAGGED` estimate by resubmitting with
    `revised_estimated_barrels`".
    PRD §2.8: "the target resource is in a state from which the requested
    transition is defined, including terminal lockdown (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/estimate_flagged_cannot_be_approved_directly
    """
    member = create_active_member()
    bog = create_bog_for(member["id"])
    season = create_season()
    estimate = create_estimate(bog["id"], season["id"], member["id"], 2300)
    transition_estimate(estimate["id"], {"to": "FLAGGED"}, OFFICER)

    resp = api.transition_yield_estimate(estimate["id"], {"to": "APPROVED"},
                                         OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_estimate(estimate["id"])["status"] == "FLAGGED"


def test_estimate_revise_replaces_value_and_counts(api):
    """PRD §3.3: "A grower revises a `FLAGGED` estimate by resubmitting with
    `revised_estimated_barrels`: the estimate returns to `SUBMITTED`, its
    `estimated_barrels` is replaced by the revised figure, and its
    `revision_count` increments by 1."

    Design: Corner/state_machines/estimate_revise_replaces_value_and_counts
    """
    member = create_active_member()
    bog = create_bog_for(member["id"])
    season = create_season()
    estimate = create_estimate(bog["id"], season["id"], member["id"], 2300)
    transition_estimate(estimate["id"], {"to": "FLAGGED"}, OFFICER)

    resp = api.transition_yield_estimate(
        estimate["id"], {"to": "SUBMITTED", "revised_estimated_barrels": 1800},
        make_grower_headers(member["id"]))
    revised = validate_success(resp, 200)
    assert_yield_estimate(revised)
    assert revised["status"] == "SUBMITTED"
    assert_money(revised["estimated_barrels"], 1800)
    assert revised["revision_count"] == estimate["revision_count"] + 1


def test_bog_renovation_cycle_quota_exclusion_and_return(api):
    """PRD §3.2: "Two of these steps ripple into quota accounting: entering
    `UNDER_RENOVATION` removes the bog from the quota input set, triggering a
    recomputation of the member's quota for every season whose quota is not
    locked, and the certification back to `ACTIVE` re-adds the bog and
    recomputes again."
    PRD §3.2: "The owning grower (or a `FieldOfficer`) may move an `ACTIVE` bog
    to `RENOVATION_PLANNED`, and may just as freely cancel the plan back to
    `ACTIVE`. A `FieldOfficer` alone takes the bog from `RENOVATION_PLANNED` to
    `UNDER_RENOVATION`, later marks it `REPLANTED`, and finally certifies the
    vines mature by returning it to `ACTIVE`."

    Design: Corner/state_machines/bog_renovation_cycle_quota_exclusion_and_return
    """
    ctx = setup_campaign()  # 10-acre bog, baseline 200 -> base quota 2000
    v0 = ctx.bog["version"]

    grower = make_grower_headers(ctx.member["id"])
    transition_bog(ctx.bog["id"], "RENOVATION_PLANNED", grower)
    transition_bog(ctx.bog["id"], "UNDER_RENOVATION", OFFICER)

    quota_mid = get_quota_for(ctx.member["id"], ctx.season["id"])
    assert_money(quota_mid["base_quota_barrels"], 0)
    assert_money(quota_mid["baseline_quota_barrels"], 0)

    transition_bog(ctx.bog["id"], "REPLANTED", OFFICER)
    bog_end = transition_bog(ctx.bog["id"], "ACTIVE", OFFICER)
    assert bog_end["status"] == "ACTIVE", (
        "the cyclic machine returns to ACTIVE after certification")
    assert bog_end["version"] == v0 + 4, (
        "each of the four transitions increments the bog version by exactly 1")

    quota_end = get_quota_for(ctx.member["id"], ctx.season["id"])
    assert_money(quota_end["base_quota_barrels"], 2000)
    assert_money(quota_end["baseline_quota_barrels"], 2000)

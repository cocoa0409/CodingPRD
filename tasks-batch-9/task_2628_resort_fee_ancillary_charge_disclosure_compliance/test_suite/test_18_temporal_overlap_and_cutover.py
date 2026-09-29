"""Two window rules with opposite adjacency verdicts: half-open versus buffered."""
from test_helpers import (
    ApiErrorId,
    CLOCK_START,
    SINGLE_FEE_INCLUSIONS,
    add_channel,
    add_draft_profile,
    add_fee,
    add_inclusion,
    assert_stamped_at_clock,
    create_fee_program_payload,
    create_profile_payload,
    create_resort_fee_payload,
    read_fee_program,
    read_profile,
    read_property,
    setup_single_fee_published_program,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import COMPLIANCE, REVENUE, deploy_profile

STEEPER_RESORT_FEE = {"percent_bps": 800,
                      "disclosure_text": "A mandatory nightly resort fee of 8% applies."}


def _successor_under_review(api, env, version_label, effective_from, effective_to):
    """Author a second inventory over the given window and send it for review."""
    program = validate_success(
        api.create_fee_program(
            create_fee_program_payload(
                env["property"]["id"],
                read_property(env["property"]["id"])["version"],
                version_label=version_label,
                effective_from=effective_from,
                effective_to=effective_to,
            ),
            REVENUE,
        ),
        201,
    )
    fee = add_fee(program["id"], create_resort_fee_payload(**STEEPER_RESORT_FEE))
    add_inclusion(fee["id"], SINGLE_FEE_INCLUSIONS["RESORT"])
    return validate_success(api.submit_fee_program_for_review(program["id"], REVENUE))


def test_one_second_of_effective_window_overlap_is_rejected_at_publication(api):
    """A window starting one second before the incumbent's exclusive end collides.

    PRD 3.2: "the program's half-open effective interval must not overlap the
    interval of any other `PUBLISHED` program of the same property, excluding the
    program named by `supersedes_program_id`, failing with
    `ERR_FEE_PROGRAM_PERIOD_OVERLAP`." PRD 3.2 on the interval itself: "the
    half-open effective interval `[effective_from, effective_to)` —
    `effective_from` inclusive, `effective_to` exclusive and strictly later than
    `effective_from`".

    Design: Difficulty/resource_temporal_overlap/fee_program_half_open_effective_interval_allows_exact_adjacency
    """
    env = setup_single_fee_published_program()
    assert env["program"]["effective_from"].startswith("2026-09-01")
    assert env["program"]["effective_to"].startswith("2026-12-01")
    assert read_property(env["property"]["id"])["published_fee_program_count"] == 1

    overlapping = _successor_under_review(
        api,
        env,
        "FY27-Q1-OVERLAP",
        "2026-11-30T23:59:59Z",
        "2027-03-01T00:00:00Z",
    )

    validate_error(
        api.publish_fee_program(
            overlapping["id"], "Attesting a window that starts a second early.",
            COMPLIANCE,
        ),
        ApiErrorId.ERR_FEE_PROGRAM_PERIOD_OVERLAP,
        409,
    )

    rejected = read_fee_program(overlapping["id"])
    assert rejected["status"] == "UNDER_REVIEW"
    assert rejected["published_at"] is None
    assert rejected["attested_by_user_id"] is None
    assert read_property(env["property"]["id"])["published_fee_program_count"] == 1


def test_an_exactly_touching_window_publishes_while_containment_does_not(api):
    """Touching at one instant is legal; sitting wholly inside is not.

    PRD 3.2: "`effective_from` inclusive, `effective_to` exclusive and strictly
    later than `effective_from`". PRD 3.2 on the collision: "the program's
    half-open effective interval must not overlap the interval of any other
    `PUBLISHED` program of the same property ... failing with
    `ERR_FEE_PROGRAM_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/fee_program_half_open_effective_interval_allows_exact_adjacency
    """
    env = setup_single_fee_published_program()
    adjacent = _successor_under_review(
        api, env, "FY27-Q1-ADJACENT", "2026-12-01T00:00:00Z", "2027-03-01T00:00:00Z"
    )
    contained = _successor_under_review(
        api, env, "FY26-Q4-INSIDE", "2026-11-30T00:00:00Z", "2026-12-01T00:00:00Z"
    )

    published = validate_success(
        api.publish_fee_program(
            adjacent["id"], "Attesting the window that begins where Q4 ends.",
            COMPLIANCE,
        )
    )
    assert published["status"] == "PUBLISHED"
    assert_stamped_at_clock(published["published_at"], CLOCK_START, "published_at")
    assert read_property(env["property"]["id"])["published_fee_program_count"] == 2

    validate_error(
        api.publish_fee_program(
            contained["id"], "Attesting a window wholly inside the incumbent.",
            COMPLIANCE,
        ),
        ApiErrorId.ERR_FEE_PROGRAM_PERIOD_OVERLAP,
        409,
    )
    assert read_fee_program(contained["id"])["status"] == "UNDER_REVIEW"
    assert read_property(env["property"]["id"])["published_fee_program_count"] == 2


WIDE_WINDOW = {
    "program_overrides": {
        "version_label": "FY27-WIDE",
        "effective_to": "2027-06-01T00:00:00Z",
    }
}
LEGACY_GDS = {
    "name": "LegacyGDS Terminal",
    "channel_type": "GDS",
    "supports_total_price_display": True,
    "supports_itemization": True,
}
# Profile A closes on 2026-11-30T00:00:00Z, so the buffered zone runs to
# 2026-12-01T00:00:00Z exclusive.
INSIDE_BUFFER_WINDOW = {
    "deployed_from": "2026-11-30T23:00:00Z",
    "deployed_to": "2027-02-01T00:00:00Z",
}
TOUCHING_WINDOW = {
    "deployed_from": "2026-11-30T00:00:00Z",
    "deployed_to": "2027-02-01T00:00:00Z",
}
EXACTLY_A_DAY_LATER = {
    "deployed_from": "2026-12-01T00:00:00Z",
    "deployed_to": "2027-02-01T00:00:00Z",
}


def _live_path_on_a_wide_program(api):
    """One DEPLOYED path closing on 2026-11-30, over a program spanning to June."""
    env = setup_single_fee_published_program(**WIDE_WINDOW)
    env["profile"] = add_draft_profile(env)
    env["profile"] = deploy_profile(env)
    env["program"] = read_fee_program(env["program"]["id"])
    return env


def _profile_attempt(api, env, channel=None, **window):
    """Attempt a path create without asserting success, so errors are visible."""
    channel = channel or env["channel"]
    env["program"] = read_fee_program(env["program"]["id"])
    payload = create_profile_payload(
        env["property"]["id"],
        channel["id"],
        env["program"]["id"],
        env["program"]["version"],
        **window,
    )
    # POST /channel-disclosure-profiles is authorised for RevenueManager and
    # ChannelOperator only, so the revenue manager issues the create.
    return api.create_channel_disclosure_profile(payload, REVENUE)


def test_a_gap_of_twenty_three_hours_and_a_touching_window_both_collide(api):
    """Only a separation of a full day clears the buffer; 23 hours does not.

    PRD 3.3: "the window is inflated by 24 hours on each side, and it collides
    with another profile's window when the first's `deployed_from` is earlier
    than the second's `deployed_to` advanced by 24 hours **and** the second's
    `deployed_from` is earlier than the first's `deployed_to` advanced by 24
    hours ... Touching windows are therefore forbidden, as is any gap shorter
    than 24 hours; a gap of exactly 24 hours is the smallest legal one. A
    collision is rejected with `ERR_CUTOVER_BUFFER_VIOLATION` (HTTP 409)".

    Design: Difficulty/resource_temporal_overlap/disclosure_profile_closed_window_with_cutover_buffer_forbids_adjacency
    """
    env = _live_path_on_a_wide_program(api)
    assert env["profile"]["status"] == "DEPLOYED"
    assert env["profile"]["deployed_to"].startswith("2026-11-30")

    validate_error(
        _profile_attempt(api, env, **INSIDE_BUFFER_WINDOW),
        ApiErrorId.ERR_CUTOVER_BUFFER_VIOLATION,
        409,
    )
    validate_error(
        _profile_attempt(api, env, **TOUCHING_WINDOW),
        ApiErrorId.ERR_CUTOVER_BUFFER_VIOLATION,
        409,
    )

    paths, _meta = validate_paginated(
        api.list_channel_disclosure_profiles(
            COMPLIANCE, {"property_id": env["property"]["id"], "limit": 100}
        )
    )
    assert len(paths) == 1
    assert paths[0]["id"] == env["profile"]["id"]

    successor = validate_success(
        _profile_attempt(api, env, **EXACTLY_A_DAY_LATER), 201
    )
    assert successor["status"] == "DRAFT"
    assert successor["deployed_from"].startswith("2026-12-01")

    paths_after, _meta_after = validate_paginated(
        api.list_channel_disclosure_profiles(
            COMPLIANCE, {"property_id": env["property"]["id"], "limit": 100}
        )
    )
    assert len(paths_after) == 2


def test_the_buffer_contends_over_one_channel_and_only_over_live_paths(api):
    """A draft rival is invisible at create, and another channel never collides.

    PRD 3.3: "The comparison set is every other profile on the same
    `property_id` and `channel_id` whose status is `DEPLOYED`, `FLAGGED`,
    `REMEDIATED` or `RETIRED` — retired paths still reserve their historical
    window." PRD 3.3 on where the deferred collision surfaces: "the check runs
    twice: once when the profile is created and again when it is taken live."

    Design: Difficulty/resource_temporal_overlap/disclosure_profile_closed_window_with_cutover_buffer_forbids_adjacency
    """
    env = setup_single_fee_published_program(**WIDE_WINDOW)
    gds = add_channel(env, "gds_channel", **LEGACY_GDS)

    # While the incumbent is still DRAFT the buffered zone is unreserved.
    incumbent = add_draft_profile(env)
    rival = add_draft_profile(env, **INSIDE_BUFFER_WINDOW)
    assert incumbent["status"] == "DRAFT"
    assert rival["status"] == "DRAFT"

    env["profile"] = deploy_profile(env, profile=incumbent)
    assert env["profile"]["status"] == "DEPLOYED"

    validate_error(
        api.deploy_profile(rival["id"], COMPLIANCE),
        ApiErrorId.ERR_CUTOVER_BUFFER_VIOLATION,
        409,
    )
    assert read_profile(rival["id"])["status"] == "DRAFT"

    # The contended resource is the property-and-channel pair, so the same
    # window is free on a different channel.
    on_gds = add_draft_profile(env, channel=gds, **INSIDE_BUFFER_WINDOW)
    deployed_gds = deploy_profile(env, profile=on_gds)
    assert deployed_gds["status"] == "DEPLOYED"
    assert deployed_gds["channel_id"] == gds["id"]
    assert read_profile(incumbent["id"])["status"] == "DEPLOYED"

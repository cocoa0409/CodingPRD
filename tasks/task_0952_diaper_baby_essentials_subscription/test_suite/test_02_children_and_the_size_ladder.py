"""Child profiles, the ten-band size ladder, weight measurements and resizes."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    UNKNOWN_UUID,
    assert_allergen_flag,
    assert_child,
    assert_resize_event,
    create_child_payload,
    list_resize_events,
    make_account_holder_headers,
    read_child,
    read_subscription,
    register_and_verify_account,
    set_clock,
    setup_household,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["ops_admin_headers"]
SUPPORT = TEST_USERS["support_agent_headers"]


# ==========================================================================
# Creation: the stage is derived from the weight, with no clamping
# ==========================================================================
def test_child_creation_derives_the_stage_from_the_supplied_weight(api):
    """PRD §3.2: "At creation the child's `stage` is simply the band the supplied weight
    falls into, with no further adjustment."
    PRD §3.2: "Two optional booleans complete the profile: `stage_pinned`, which defaults
    to false, and `hypoallergenic_required`, which also defaults to false."
    PRD §3.2: "The system additionally maintains `archived` on every child, false at
    creation and set true only when the owning household closes."

    Design: Corner/entities/corner_child_stage_is_computed_and_supplied_stage_input_ignored
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    account = register_and_verify_account(api, email=unique_email("comp"))
    headers = make_account_holder_headers(account["id"])
    data = validate_success(
        api.create_child(create_child_payload(account["id"], weight_grams=7000), headers),
        201,
    )
    assert_child(data)
    assert data["stage"] == "S2", "7000 g sits in the S2 band [6400, 8200)"
    assert data["stage_pinned"] is False
    assert data["hypoallergenic_required"] is False
    assert data["archived"] is False


def test_child_creation_naming_an_unknown_account_returns_account_not_found(api):
    """PRD §2.10: "Foreign keys supplied in a request *body* are checked only after every
    path identifier has resolved, and among themselves they are checked in the order the
    endpoint declares its inputs. The body-foreign-key rung applies to creating a child,
    creating a subscription, creating a registry, adding a registry item, creating a gift
    order, issuing a credit and creating a referral, and it uses the same per-type error
    mapping."
    PRD §2.10: "The mapping from resource type to not-found error is uniform: a missing
    `Account` yields `ERR_ACCOUNT_NOT_FOUND`, a `Child` `ERR_CHILD_NOT_FOUND`, an
    `AllergenFlag` `ERR_ALLERGEN_FLAG_NOT_FOUND`, a `Plan` `ERR_PLAN_NOT_FOUND`, a `Sku`
    `ERR_SKU_NOT_FOUND`, a `Subscription` `ERR_SUBSCRIPTION_NOT_FOUND`, a `Cycle`
    `ERR_CYCLE_NOT_FOUND`, a `CycleLine` `ERR_CYCLE_LINE_NOT_FOUND`, a `ResizeEvent`
    `ERR_RESIZE_EVENT_NOT_FOUND`, a `SkipRecord` `ERR_SKIP_RECORD_NOT_FOUND`, a `PauseRecord`
    `ERR_PAUSE_RECORD_NOT_FOUND`, a `Registry` `ERR_REGISTRY_NOT_FOUND`, a `RegistryItem`
    `ERR_REGISTRY_ITEM_NOT_FOUND`, a `GiftOrder` `ERR_GIFT_ORDER_NOT_FOUND`, a `Credit`
    `ERR_CREDIT_NOT_FOUND`, a `Shipment` `ERR_SHIPMENT_NOT_FOUND`, a `LoyaltyAccount`
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, a `Referral` `ERR_REFERRAL_NOT_FOUND`, a `Refund`
    `ERR_REFUND_NOT_FOUND`, and a `SubstitutionEvent` `ERR_SUBSTITUTION_EVENT_NOT_FOUND`. All
    are HTTP 404."

    Design: Corner/entities/corner_child_creation_with_unknown_account_returns_not_found
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    resp = api.create_child(
        create_child_payload(UNKNOWN_UUID, name="Ghost"),
        make_account_holder_headers(UNKNOWN_UUID),
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value, 404)


def test_child_creation_with_an_unparseable_birth_date_is_rejected(api):
    """PRD §2.11: "A field that fails to parse — a calendar date that is not in
    `YYYY-MM-DD` form, an instant that does not end in `Z`, a non-whole number where an
    integer is expected, a non-boolean where a boolean is expected — is rejected with
    `ERR_INVALID_FORMAT` (HTTP 400)."

    Design: Corner/errors/corner_invalid_date_format_rejected
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    account = register_and_verify_account(api, email=unique_email("fmt"))
    headers = make_account_holder_headers(account["id"])
    resp = api.create_child(
        create_child_payload(account["id"], birth_date="01-11-2025"), headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_FORMAT.value, 400)

    listed, meta = validate_paginated(
        api.list_children(headers, {"account_id": account["id"]})
    )
    assert meta["total_count"] == 0, "a malformed birth date must not create a child"


def test_child_creation_below_the_declared_weight_floor_is_out_of_range(api):
    """PRD §2.11: "Numeric range violations return `ERR_VALUE_OUT_OF_RANGE` (HTTP 422).
    The declared ranges are: `pack_count` from 1 to 12 inclusive; `consumption_rate_per_day`
    from 1 to 14 inclusive; `weight_grams` from 500 to 59999 inclusive;"

    Design: Corner/errors/corner_weight_below_declared_range_rejected
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    account = register_and_verify_account(api, email=unique_email("range"))
    headers = make_account_holder_headers(account["id"])
    resp = api.create_child(create_child_payload(account["id"], weight_grams=100), headers)
    validate_error(resp, ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value, 422)


# ==========================================================================
# The bidirectional, re-entrant stage axis
# ==========================================================================
def test_stage_axis_climbs_then_descends_across_two_measurements(api):
    """PRD §3.2: "The stage axis is bidirectional and re-entrant: `S2 → S3 → S2` is a
    perfectly legal sequence of measurements, and because of the clamp a non-adjacent jump
    is never performed."
    PRD §3.2: "On acceptance the server stores the new weight, recomputes the stage under
    the clamping rule above, and — when the stage would change — proposes an automatic
    resize by writing a `ResizeEvent` whose `origin` is `AUTO`."

    Design: Difficulty/non_linear_state_machine/child_stage_axis_moves_up_then_back_down
    """
    ctx = setup_household(api, email_prefix="stage")
    up = validate_success(
        api.record_weight_measurement(ctx["child"]["id"], 8500, ctx["headers"])
    )
    assert up["stage"] == "S3", "8500 g raw band S3 is adjacent to S2, so the child moves up"

    down = validate_success(
        api.record_weight_measurement(ctx["child"]["id"], 7000, ctx["headers"])
    )
    assert down["stage"] == "S2", "the axis re-enters S2 on the way back down"
    assert read_child(api, ctx["child"]["id"], ctx["account_id"])["stage"] == "S2"


def test_two_measurements_write_exactly_two_auto_resize_events(api):
    """PRD §3.2: "The count that feeds the cap is maintained on the subscription as
    `auto_resize_count_in_period`: the number of `ResizeEvent` rows on that subscription
    whose `origin` is `AUTO` and whose `status` is `APPLIED_CURRENT` or `APPLIED_NEXT`,
    created at or after the instant 90 days before the logical clock."
    PRD §3.2: "That event records the `subscription_id` it belongs to, the `child_id` whose
    weight produced it, the `from_stage` and `to_stage` of the proposal, and the
    `measured_weight_grams` that triggered it, which equals the child's weight at proposal
    time."

    Design: Difficulty/non_linear_state_machine/child_stage_axis_moves_up_then_back_down
    """
    ctx = setup_household(api, email_prefix="stage2")
    validate_success(api.record_weight_measurement(ctx["child"]["id"], 8500, ctx["headers"]))
    validate_success(api.record_weight_measurement(ctx["child"]["id"], 7000, ctx["headers"]))

    events = list_resize_events(api, ctx["subscription"]["id"], origin="AUTO")
    assert len(events) == 2, f"expected exactly 2 AUTO resize events, got {len(events)}"
    for event in events:
        assert_resize_event(event)
        assert event["origin"] == "AUTO"
        assert event["child_id"] == ctx["child"]["id"]
        assert event["subscription_id"] == ctx["subscription"]["id"]
    by_target = {e["to_stage"] for e in events}
    assert by_target == {"S3", "S2"}, f"expected proposals to S3 and back to S2, got {by_target}"

    subscription = read_subscription(api, ctx["subscription"]["id"])
    assert subscription["auto_resize_count_in_period"] == 2


def test_a_multi_band_weight_jump_is_clamped_to_a_single_step(api):
    """PRD §3.2: "Otherwise the server moves the child exactly one position along the
    ladder in the direction of the raw band — upward if the raw band sits later in the
    order, downward if it sits earlier — and never more than one position, however many
    bands the new weight leapt across. A child in `S2` weighed at 15000 grams (raw band
    `S5`) therefore moves to `S3`, not `S5`."

    Design: Difficulty/non_linear_state_machine/child_stage_axis_moves_up_then_back_down
    """
    ctx = setup_household(api, email_prefix="clamp")
    data = validate_success(
        api.record_weight_measurement(ctx["child"]["id"], 15000, ctx["headers"])
    )
    assert data["stage"] == "S3", "the clamp permits only one ladder position per measurement"
    assert data["weight_grams"] == 15000


# ==========================================================================
# Band boundaries
# ==========================================================================
def test_a_weight_one_gram_below_the_band_boundary_stays_in_the_lower_band(api):
    """PRD §3.2: "`S1` covers 4500 up to 6400 grams."
    PRD §3.2: "When a new weight is recorded, the server first resolves the raw band the
    weight belongs to. If that band is the band the child is already in, the stage does not
    change."

    Design: Difficulty/boundary_precision_check/weight_exactly_on_band_boundary_resolves_upward
    """
    ctx = setup_household(
        api,
        email_prefix="band",
        sku_overrides={"stage": "S1", "name": "Stage 1 Standard 60"},
        child_overrides={"weight_grams": 5000, "birth_date": "2026-01-01"},
    )
    assert ctx["child"]["stage"] == "S1", "5000 g sits in the S1 band [4500, 6400)"

    data = validate_success(
        api.record_weight_measurement(ctx["child"]["id"], 6399, ctx["headers"])
    )
    assert data["stage"] == "S1", "6399 g is still inside S1 because the upper bound is exclusive"
    assert not list_resize_events(api, ctx["subscription"]["id"]), (
        "a measurement that does not change the stage proposes no resize"
    )


def test_a_weight_exactly_on_the_band_boundary_resolves_to_the_upper_band(api):
    """PRD §3.2: "Because upper bounds are exclusive, a weight sitting exactly on a
    boundary belongs to the upper band: 6400 grams resolves to `S2`, not `S1`."

    Design: Difficulty/boundary_precision_check/weight_exactly_on_band_boundary_resolves_upward
    """
    ctx = setup_household(
        api,
        email_prefix="band2",
        sku_overrides={"stage": "S1", "name": "Stage 1 Standard 60"},
        child_overrides={"weight_grams": 5000, "birth_date": "2026-01-01"},
    )
    validate_success(api.record_weight_measurement(ctx["child"]["id"], 6399, ctx["headers"]))
    data = validate_success(
        api.record_weight_measurement(ctx["child"]["id"], 6400, ctx["headers"])
    )
    assert data["stage"] == "S2", "6400 g is the S2 lower bound and belongs to S2"
    assert data["weight_grams"] == 6400

    events = list_resize_events(api, ctx["subscription"]["id"], origin="AUTO")
    assert len(events) == 1, (
        f"only the boundary measurement changes the stage, so exactly 1 AUTO event is "
        f"written, got {len(events)}"
    )


# ==========================================================================
# The two guards on the automatic path
# ==========================================================================
def test_a_pinned_stage_records_the_weight_and_writes_a_rejected_event(api):
    """PRD §3.2: "A pinned stage is a customer preference: when `stage_pinned` is true, the
    weight *is* still recorded and the call still succeeds, but the child's `stage` is left
    untouched and the `ResizeEvent` is written in status `REJECTED` with `reject_reason`
    set to `STAGE_PINNED`."
    PRD §3.2: "Rejected events do not count, and manual resizes are deliberately excluded
    so that a customer can always override a size by hand."

    Design: Corner/endpoints/corner_child_patch_pins_stage_and_suppresses_auto_resize
    """
    ctx = setup_household(api, with_sku=False, email_prefix="pin")
    pinned = validate_success(
        api.update_child(ctx["child"]["id"], {"stage_pinned": True}, ctx["headers"])
    )
    assert pinned["stage_pinned"] is True

    measured = validate_success(
        api.record_weight_measurement(ctx["child"]["id"], 8500, ctx["headers"])
    )
    assert measured["weight_grams"] == 8500, "the weight is still recorded on a pinned child"
    assert measured["stage"] == "S2", "the stage is left untouched"

    events = list_resize_events(api, ctx["subscription"]["id"])
    assert len(events) == 1, f"expected one rejected proposal, got {len(events)}"
    assert events[0]["status"] == "REJECTED"
    assert events[0]["reject_reason"] == "STAGE_PINNED"
    assert read_subscription(api, ctx["subscription"]["id"])["auto_resize_count_in_period"] == 0


def test_a_third_automatic_resize_inside_the_period_rejects_the_whole_request(api):
    """PRD §3.2: "An exhausted cap, by contrast, is a policy limit: automatic resizes are
    permitted at most twice within the trailing 90 days, and a third one rejects the whole
    request with `ERR_RESIZE_CAP_EXCEEDED` (HTTP 409) — the weight is not recorded, the
    stage is unchanged and no `ResizeEvent` row is written at all."

    Design: Corner/validations/corner_third_auto_resize_in_period_rejected
    """
    ctx = setup_household(api, with_sku=False, email_prefix="resizecap")
    validate_success(api.record_weight_measurement(ctx["child"]["id"], 8500, ctx["headers"]))
    validate_success(api.record_weight_measurement(ctx["child"]["id"], 7000, ctx["headers"]))

    resp = api.record_weight_measurement(ctx["child"]["id"], 8600, ctx["headers"])
    validate_error(resp, ApiErrorId.ERR_RESIZE_CAP_EXCEEDED.value, 409)

    child = read_child(api, ctx["child"]["id"], ctx["account_id"])
    assert child["weight_grams"] == 7000, "the rejected measurement is not recorded"
    assert child["stage"] == "S2"
    assert len(list_resize_events(api, ctx["subscription"]["id"])) == 2


def test_a_measurement_on_an_archived_child_is_refused(api):
    """PRD §3.2: "The measurement is refused outright when the child is archived, with
    `ERR_CHILD_ARCHIVED` (HTTP 409)."
    PRD §3.1: "every `Child` of the account has `archived` set to true, which permanently
    excludes those children from cycle allocation"

    Design: Corner/state_machines/corner_archived_child_blocks_weight_measurement
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    account = register_and_verify_account(api, email=unique_email("arch"))
    headers = make_account_holder_headers(account["id"])
    child = validate_success(
        api.create_child(create_child_payload(account["id"]), headers), 201
    )
    validate_success(api.close_account(account["id"], headers))

    resp = api.record_weight_measurement(child["id"], 8500, headers)
    validate_error(resp, ApiErrorId.ERR_CHILD_ARCHIVED.value, 409)

    after = validate_success(api.get_child(child["id"], headers))
    assert after["archived"] is True
    assert after["weight_grams"] == 7000
    assert after["stage"] == "S2"


# ==========================================================================
# Manual resize: adjacency, pinning and optimistic concurrency
# ==========================================================================
def test_a_manual_resize_two_stages_away_is_refused(api):
    """PRD §3.2: "The target must sit exactly one position away from the child's current
    stage in the ladder; a stage further away is rejected with `ERR_NON_ADJACENT_STAGE`
    (HTTP 422), and no `ResizeEvent` is persisted."

    Design: Corner/validations/corner_manual_resize_two_stages_away_rejected
    """
    ctx = setup_household(api, with_sku=False, email_prefix="jump")
    subscription = read_subscription(api, ctx["subscription"]["id"])
    resp = api.request_resize(
        subscription["id"],
        {"target_stage": "S4", "expected_subscription_version": subscription["version"]},
        ctx["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_NON_ADJACENT_STAGE.value, 422)

    assert read_child(api, ctx["child"]["id"], ctx["account_id"])["stage"] == "S2"
    assert not list_resize_events(api, subscription["id"])


def test_a_manual_resize_on_a_pinned_child_is_the_one_stage_pinned_error(api):
    """PRD §3.2: "If the child's `stage_pinned` is true, the manual request is refused with
    `ERR_STAGE_PINNED` (HTTP 409) — this is the one place that error code is returned,
    since the weight-measurement path swallows the same condition into a rejected event
    instead."

    Design: Corner/validations/corner_manual_resize_on_pinned_child_rejected
    """
    ctx = setup_household(
        api, with_sku=False, email_prefix="pinned",
        child_overrides={"stage_pinned": True},
    )
    subscription = read_subscription(api, ctx["subscription"]["id"])
    resp = api.request_resize(
        subscription["id"],
        {"target_stage": "S3", "expected_subscription_version": subscription["version"]},
        ctx["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STAGE_PINNED.value, 409)

    child = read_child(api, ctx["child"]["id"], ctx["account_id"])
    assert child["stage"] == "S2"
    assert child["stage_pinned"] is True


def test_a_stale_expected_subscription_version_rejects_the_resize(api):
    """PRD §2.7: "Requesting a manual stage resize on a subscription requires
    `expected_subscription_version`, carrying the client's last observed `version` of that
    `Subscription`. If the subscription's current `version` differs from the supplied
    value, the resize is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412) and no
    `ResizeEvent` row is written."

    Design: Corner/cross_cutting_layers/corner_occ_stale_subscription_version_rejects_resize
    """
    ctx = setup_household(
        api, with_sku=False, email_prefix="occ1", activate_subscription=False
    )
    version_at_create = ctx["subscription"]["version"]
    activated = validate_success(
        api.activate_subscription(ctx["subscription"]["id"], ctx["headers"])
    )
    assert activated["version"] > version_at_create, (
        "activation is a mutation and must advance the subscription's version"
    )

    resp = api.request_resize(
        ctx["subscription"]["id"],
        {"target_stage": "S3", "expected_subscription_version": version_at_create},
        ctx["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_SUBSCRIPTION_VERSION.value, 412)

    assert read_child(api, ctx["child"]["id"], ctx["account_id"])["stage"] == "S2"
    assert not list_resize_events(api, ctx["subscription"]["id"])


# ==========================================================================
# Sensitivity records
# ==========================================================================
def test_an_allergen_flag_is_an_append_only_observation(api):
    """PRD §2.4: "Four record types are append-only observations rather than living
    resources, and they carry only `id` and `created_at` — for `AllergenFlag`,
    `ResizeEvent`, `SkipRecord`, `PointsLedgerEntry` and `SubstitutionEvent`, both
    `updated_at` and `version` are absent from the stored row and from the response
    payload."
    PRD §3.2: "an optional free-text `note` that defaults to null"

    Design: Corner/entities/corner_allergen_flag_is_immutable_and_carries_no_version
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    account = register_and_verify_account(api, email=unique_email("imm"))
    headers = make_account_holder_headers(account["id"])
    child = validate_success(
        api.create_child(create_child_payload(account["id"]), headers), 201
    )
    data = validate_success(
        api.create_allergen_flag(
            child["id"], {"allergen_tag": "LATEX", "severity": "MILD"}, headers
        ),
        201,
    )
    assert_allergen_flag(data)
    assert data.get("note") is None

"""Casting deals: the guard rules on the create, the booking dimension and the
optimistic-concurrency check that protects the supersede path."""

from test_helpers import (
    CASTING,
    PC,
    ApiErrorId,
    assert_casting_assignment,
    create_casting_assignment_payload,
    create_voice_talent,
    make_voice_talent_headers,
    order_version,
    setup_canon,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_unlicensed_territory_outranks_the_rate_floor_on_a_casting_create(api):
    """PRD §2.6 ladder step 15: "On `POST /casting-assignments` and
    `POST /talent-payments`: the talent's `licensed_territories` contains the order's
    `territory`, and for a payment the supplied `territory_scope` is a subset of
    `licensed_territories` and contains the order's `territory`; otherwise
    `ERR_TERRITORY_NOT_LICENSED` (422)."
    PRD §2.6 ladder step 24: "On `POST /casting-assignments`:
    `agreed_rate_cents_per_hour` is greater than or equal to the talent's
    `base_rate_cents_per_hour`; otherwise `ERR_RATE_BELOW_TALENT_FLOOR` (422)."
    PRD §2.6: "Checks are evaluated strictly in ascending priority order, and **the
    first failing check determines the entire response — no later check runs and no
    later error code can surface**."

    Design: Difficulty/priority_pair_validation_conflict/territory_unlicensed_outranks_rate_below_floor
    """
    ctx = setup_canon(16)
    create_voice_talent(
        ctx, "tal4_id", full_name="Dana Ross", language_code="de-DE",
        base_rate_cents_per_hour=30000, licensed_territories=["US"],
        union_status="NON_UNION", max_daily_recorded_minutes=300,
    )
    version = order_version(ctx["o_id"])
    resp = api.create_casting_assignment(
        create_casting_assignment_payload(
            ctx["o_id"], ctx["ch1_id"], ctx["tal4_id"], version,
            usage_variant="BUYOUT", agreed_rate_cents_per_hour=20000,
        ),
        CASTING,
    )
    error = validate_error(resp, ApiErrorId.ERR_TERRITORY_NOT_LICENSED.value)
    assert resp.status_code == 422
    assert error["error_id"] != ApiErrorId.ERR_RATE_BELOW_TALENT_FLOOR.value, (
        "the lower-priority rate check must not pre-empt the territory licence check"
    )


def test_a_request_failing_the_territory_check_writes_nothing_at_all(api):
    """PRD §2.6 ladder step 15: "On `POST /casting-assignments` and
    `POST /talent-payments`: the talent's `licensed_territories` contains the order's
    `territory`, and for a payment the supplied `territory_scope` is a subset of
    `licensed_territories` and contains the order's `territory`; otherwise
    `ERR_TERRITORY_NOT_LICENSED` (422)."
    PRD §3.5: "A surviving create stores the assignment with `casting_status` of
    `PROPOSED`, `payment_status` of `UNBILLED`, `superseded_by_id` null, and
    `recorded_minutes` and `retake_minutes` both at 0, and it increments the owning
    order's `version` by 1."

    Design: Difficulty/priority_pair_validation_conflict/territory_unlicensed_outranks_rate_below_floor
    """
    ctx = setup_canon(16)
    create_voice_talent(
        ctx, "tal4_id", full_name="Dana Ross", language_code="de-DE",
        base_rate_cents_per_hour=30000, licensed_territories=["US"],
        union_status="NON_UNION", max_daily_recorded_minutes=300,
    )
    before = order_version(ctx["o_id"])
    resp = api.create_casting_assignment(
        create_casting_assignment_payload(
            ctx["o_id"], ctx["ch1_id"], ctx["tal4_id"], before,
            usage_variant="BUYOUT", agreed_rate_cents_per_hour=20000,
        ),
        CASTING,
    )
    validate_error(resp, ApiErrorId.ERR_TERRITORY_NOT_LICENSED.value)
    rows, _ = validate_paginated(api.list_casting_assignments(CASTING, {"order_id": ctx["o_id"]}))
    assert rows == [], "a refused create must not store an assignment"
    assert order_version(ctx["o_id"]) == before, (
        "a refused create must not bump the order's version"
    )


def test_confirming_a_proposed_assignment_is_refused(api):
    """PRD §3.5: "Confirming the deal advances `HELD → CONFIRMED` and additionally
    requires that the owning order be in `CASTING` or `RECORDING` and that the
    assignment's `superseded_by_id` still be null — a superseded row can never be
    confirmed."
    PRD §3.5: "Every one of these edges increments the assignment's `version` by 1,
    and any attempt from an undeclared origin state is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/confirm_casting_from_proposed_returns_invalid_state
    """
    ctx = setup_canon(18)
    resp = api.confirm_casting_assignment(ctx["ca1_id"], CASTING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert resp.status_code == 409
    data = validate_success(api.get_casting_assignment(ctx["ca1_id"], CASTING))
    assert data["casting_status"] == "PROPOSED"


def test_declining_a_hold_drives_the_assignment_to_a_terminal_declined(api):
    """PRD §3.5: "The performer themselves — acting as `VoiceTalentUser`, with
    `X-User-ID` equal to the assignment's `talent_id` — answers with a `response` of
    either `ACCEPT` or `DECLINE`, moving `HOLD_REQUESTED → HELD` or
    `HOLD_REQUESTED → DECLINED` respectively; either answer requires the assignment to
    be in `HOLD_REQUESTED`, and `DECLINED` is terminal."
    PRD §3.5: "Every one of these edges increments the assignment's `version` by 1,
    and any attempt from an undeclared origin state is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/talent_declining_hold_moves_assignment_to_declined
    """
    ctx = setup_canon(19)
    declined = validate_success(
        api.respond_hold(
            ctx["ca1_id"], {"response": "DECLINE"},
            make_voice_talent_headers(ctx["tal1_id"]),
        )
    )
    assert declined["casting_status"] == "DECLINED"

    resp = api.confirm_casting_assignment(ctx["ca1_id"], CASTING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert resp.status_code == 409


def test_recasting_the_same_character_supersedes_the_previous_deal(api):
    """PRD §3.5: "Re-casting is handled here rather than by a separate action: if a
    non-superseded assignment already exists for the *same* order and the *same*
    character, that older row has its `superseded_by_id` set to the new assignment's
    `id` and its `casting_status` moved to `RELEASED`, with its own `version`
    incremented by 1."
    PRD §3.5: "A surviving create stores the assignment with `casting_status` of
    `PROPOSED`, `payment_status` of `UNBILLED`, `superseded_by_id` null, and
    `recorded_minutes` and `retake_minutes` both at 0, and it increments the owning
    order's `version` by 1."

    Design: Corner/state_machines/recasting_same_character_supersedes_previous_assignment
    """
    ctx = setup_canon(22)
    replacement = validate_success(
        api.create_casting_assignment(
            create_casting_assignment_payload(
                ctx["o_id"], ctx["ch1_id"], ctx["tal2_id"], ctx["o_v2"],
                usage_variant="RESIDUAL", agreed_rate_cents_per_hour=31000,
            ),
            CASTING,
        ),
        201,
    )
    assert_casting_assignment(replacement)
    old = validate_success(api.get_casting_assignment(ctx["ca1_id"], CASTING))
    assert old["casting_status"] == "RELEASED"
    assert old["superseded_by_id"] == replacement["id"]
    assert replacement["casting_status"] == "PROPOSED"
    assert replacement["superseded_by_id"] is None
    rows, _ = validate_paginated(
        api.list_casting_assignments(CASTING, {"superseded_by_id": replacement["id"]})
    )
    assert len(rows) == 1


def test_one_performer_may_not_hold_two_live_roles_on_one_order(api):
    """PRD §3.5: "Finally, one performer may not hold two live roles on the same
    order: if any other non-superseded assignment of this order in `PROPOSED`,
    `HOLD_REQUESTED`, `HELD`, `CONFIRMED` or `RECORDED` already names the same
    `talent_id` for a different character, the create is refused with
    `ERR_DUPLICATE_CASTING`."

    Design: Corner/validations/same_talent_on_two_characters_of_one_order_is_rejected
    """
    ctx = setup_canon(22)
    resp = api.create_casting_assignment(
        create_casting_assignment_payload(
            ctx["o_id"], ctx["ch2_id"], ctx["tal1_id"], ctx["o_v2"],
            usage_variant="BUYOUT", agreed_rate_cents_per_hour=36000,
        ),
        CASTING,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CASTING.value)
    assert resp.status_code == 409
    rows, _ = validate_paginated(api.list_casting_assignments(CASTING, {"order_id": ctx["o_id"]}))
    assert len(rows) == 1, "only the first assignment survives"


def test_a_suspended_performer_cannot_be_cast_until_reinstated(api):
    """PRD §3.5: "The performer's `status` must be `ACTIVE`, since a `SUSPENDED`
    performer earns `ERR_TALENT_SUSPENDED`."
    PRD §3.2: "Suspension is deliberately narrow in effect: it does not disturb a
    single existing booking, and it blocks only the creation of new casting
    assignments."

    Design: Corner/validations/suspended_talent_cannot_be_cast
    """
    ctx = setup_canon(16)
    validate_success(
        api.set_voice_talent_status(ctx["tal1_id"], {"to_status": "SUSPENDED"}, CASTING)
    )
    version = order_version(ctx["o_id"])
    body = create_casting_assignment_payload(
        ctx["o_id"], ctx["ch1_id"], ctx["tal1_id"], version,
        usage_variant="BUYOUT", agreed_rate_cents_per_hour=36000,
    )
    resp = api.create_casting_assignment(body, CASTING)
    validate_error(resp, ApiErrorId.ERR_TALENT_SUSPENDED.value)
    assert resp.status_code == 409

    validate_success(
        api.set_voice_talent_status(ctx["tal1_id"], {"to_status": "ACTIVE"}, CASTING)
    )
    assert validate_success(api.get_voice_talent(ctx["tal1_id"], CASTING))["status"] == "ACTIVE"
    created = validate_success(api.create_casting_assignment(body, CASTING), 201)
    assert created["casting_status"] == "PROPOSED"


def test_a_performer_recording_another_language_cannot_be_cast(api):
    """PRD §3.5: "The performer's `language_code` must equal the order's
    `target_language`, otherwise `ERR_TALENT_LANGUAGE_MISMATCH`."

    Design: Corner/validations/talent_language_must_equal_order_target_language
    """
    ctx = setup_canon(16)
    create_voice_talent(
        ctx, "tal3_id", full_name="Chloe Marin", language_code="fr-FR",
        base_rate_cents_per_hour=30000, licensed_territories=["DE"],
        union_status="NON_UNION", max_daily_recorded_minutes=300,
    )
    version = order_version(ctx["o_id"])
    resp = api.create_casting_assignment(
        create_casting_assignment_payload(
            ctx["o_id"], ctx["ch1_id"], ctx["tal3_id"], version,
            usage_variant="BUYOUT", agreed_rate_cents_per_hour=36000,
        ),
        CASTING,
    )
    validate_error(resp, ApiErrorId.ERR_TALENT_LANGUAGE_MISMATCH.value)
    assert resp.status_code == 422


def test_a_rate_one_cent_below_the_performer_floor_is_refused(api):
    """PRD §3.5: "The `agreed_rate_cents_per_hour` may equal but never fall below the
    performer's `base_rate_cents_per_hour`, and a shortfall is
    `ERR_RATE_BELOW_TALENT_FLOOR`."
    PRD §3.2: "Voice talent is registered by a `CastingDirector` with a `full_name`
    that is non-empty, a `language_code` giving the BCP-47 tag of the language the
    performer records in, a `base_rate_cents_per_hour` of at least 1 which acts as the
    floor for any deal struck with that performer, and `licensed_territories`, a
    non-empty array drawn from the nine territory codes `US`, `CA`, `UK`, `DE`, `FR`,
    `JP`, `BR`, `AU` and `ROW`."

    Design: Corner/errors/rate_below_the_talent_floor_alone_returns_rate_error
    """
    ctx = setup_canon(17)
    resp = api.create_casting_assignment(
        create_casting_assignment_payload(
            ctx["o_id"], ctx["ch1_id"], ctx["tal1_id"], ctx["o_v1"],
            usage_variant="BUYOUT", agreed_rate_cents_per_hour=29999,
        ),
        CASTING,
    )
    validate_error(resp, ApiErrorId.ERR_RATE_BELOW_TALENT_FLOOR.value)
    assert resp.status_code == 422
    rows, _ = validate_paginated(api.list_casting_assignments(CASTING, {"order_id": ctx["o_id"]}))
    assert rows == []


def test_production_coordinator_may_not_create_a_casting_assignment(api):
    """PRD §2.6 ladder step 3: "The acting role appears in the set of roles authorised
    for the requested endpoint, on every endpoint; otherwise `ERR_ROLE_FORBIDDEN`
    (403)."
    PRD §2.1: "A `CastingDirector` owns the talent pool and the casting deals."
    PRD §4: "| POST | `/casting-assignments` | Cast a talent into a character on an
    order; re-casting the same character supersedes the previous assignment |
    `CastingDirector` |"

    Design: Corner/rbac/production_coordinator_cannot_create_a_casting_assignment
    """
    ctx = setup_canon(17)
    resp = api.create_casting_assignment(
        create_casting_assignment_payload(
            ctx["o_id"], ctx["ch1_id"], ctx["tal1_id"], ctx["o_v1"],
            usage_variant="BUYOUT", agreed_rate_cents_per_hour=36000,
        ),
        PC,
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN.value)
    assert resp.status_code == 403
    rows, _ = validate_paginated(api.list_casting_assignments(CASTING, {"order_id": ctx["o_id"]}))
    assert rows == []


def test_another_performer_cannot_answer_a_hold_that_is_not_theirs(api):
    """PRD §2.1: "When `X-User-Role` is `VoiceTalentUser`, `X-User-ID` is the `id` of
    the acting `VoiceTalent`; ownership checks on any resource that references a
    `VoiceTalent` compare the resource's foreign-key field to `X-User-ID` —
    concretely, responding to a hold compares the targeted assignment's `talent_id`
    against `X-User-ID` and refuses a mismatch with `ERR_TALENT_NOT_OWNER` (HTTP 403)."

    Design: Corner/rbac/another_talent_cannot_answer_a_hold_that_is_not_theirs
    """
    ctx = setup_canon(19)
    resp = api.respond_hold(
        ctx["ca1_id"], {"response": "ACCEPT"}, make_voice_talent_headers(ctx["tal2_id"])
    )
    validate_error(resp, ApiErrorId.ERR_TALENT_NOT_OWNER.value)
    assert resp.status_code == 403
    data = validate_success(api.get_casting_assignment(ctx["ca1_id"], CASTING))
    assert data["casting_status"] == "HOLD_REQUESTED"


def test_casting_assignments_can_be_listed_by_performer(api):
    """PRD §3.5: "Assignments may be listed filtered by `order_id`, `character_id`,
    `talent_id`, `superseded_by_id`, `casting_status` and `payment_status`."
    PRD §2.3: "Filters combine conjunctively: a request naming two filters returns
    only the rows that satisfy both."

    Design: Corner/endpoints/casting_assignments_list_filters_by_talent
    """
    ctx = setup_canon(26)
    rows, meta = validate_paginated(
        api.list_casting_assignments(CASTING, {"talent_id": ctx["tal2_id"]})
    )
    assert len(rows) == 1 and rows[0]["id"] == ctx["ca2_id"]
    assert rows[0]["usage_variant"] == "RESIDUAL"
    assert meta["total_count"] == 1


def test_a_stale_order_version_blocks_a_second_casting_create(api):
    """PRD §2.7: "A `POST /casting-assignments` request must carry
    `expected_order_version`, a non-optional input field holding the client's last
    observed `version` of the target `LocalizationOrder`."
    PRD §2.7: "If that value does not equal the order's current `version`, the create
    is rejected with `ERR_STALE_ORDER_VERSION` at HTTP 412 and nothing is written."

    Design: Corner/cross_cutting_layers/stale_order_version_on_casting_create_returns_412
    """
    ctx = setup_canon(21)
    stale_body = create_casting_assignment_payload(
        ctx["o_id"], ctx["ch2_id"], ctx["tal2_id"], ctx["o_v1"],
        usage_variant="RESIDUAL", agreed_rate_cents_per_hour=30000,
    )
    resp = api.create_casting_assignment(stale_body, CASTING)
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION.value)
    assert resp.status_code == 412

    fresh = order_version(ctx["o_id"])
    retry = dict(stale_body, expected_order_version=fresh)
    created = validate_success(api.create_casting_assignment(retry, CASTING), 201)
    assert created["casting_status"] == "PROPOSED"
    rows, _ = validate_paginated(api.list_casting_assignments(CASTING, {"order_id": ctx["o_id"]}))
    assert len(rows) == 2
    assert order_version(ctx["o_id"]) > fresh, (
        "the surviving create increments the owning order's version"
    )

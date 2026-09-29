"""Validation precedence and the boundaries of the declared gates: the
authentication rung ahead of the role rung, the state rung ahead of the fiscal
rung, an aggregate load limit, the member-only discount branch, the inclusive
`opening_at` gate, and cross-exhibition wall coherence."""

from test_helpers import (
    CALL_MANAGER,
    REGISTRAR,
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_artist_payload,
    create_exhibition_payload,
    create_installation_plan_payload,
    fixtures,
    make_artist_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# The `Artist` header pair with the role half removed. Nothing else about the
# request is malformed, so only the authentication rung can fire.
ARTIST_WITHOUT_ROLE_HEADER = {
    name: value
    for name, value in TEST_USERS["artist_headers"].items()
    if name != "X-User-Role"
}
ARTIST_HEADERS = TEST_USERS["artist_headers"]

# ─── Fees ─────────────────────────────────────────────

WRONG_AMOUNT_CENTS = 9999
MEMBER_BASE_LINE_CENTS = 3713
NON_MEMBER_BASE_LINE_CENTS = 4500

ONE_WORK = [fixtures.WORK_RIDGE_LINE]

# ─── Wall load ────────────────────────────────────────

HEAVY_WALL_LIMIT_KG = 10.0
FIRST_WORK_WEIGHT_KG = 6.0
SECOND_WORK_WEIGHT_KG = 5.0
TWO_WORKS = [fixtures.WORK_RIDGE_LINE, fixtures.WORK_SALT_FLAT]

# ─── The opening instant ──────────────────────────────

ONE_SECOND_BEFORE_OPENING = "2026-11-12T17:59:59Z"
OPENING_INSTANT = "2026-11-12T18:00:00Z"


def _plan(artwork_id, wall_segment_id, span_start_cm, span_end_cm, version):
    """File an installation plan without presuming it succeeds."""
    return api_client.file_installation_plan(
        artwork_id,
        create_installation_plan_payload(
            wall_segment_id, span_start_cm, span_end_cm, version
        ),
        REGISTRAR,
    )


# ─── Authentication ahead of role permission ───────────

def test_a_missing_role_header_is_unauthenticated_not_forbidden(api):
    """PRD §2.10: "When several checks could reject the same request, the server
    applies them in a fixed order and returns the error of the **first** check
    that fails."

    PRD §2.10: "**Header authentication** — both auth headers present and the
    role recognised, else `ERR_UNAUTHENTICATED` (401). Applies to every
    endpoint." at position 1, ahead of "**Role permission** — the acting role is
    listed for the endpoint, else `ERR_ROLE_NOT_PERMITTED` (403). Applies to
    every endpoint." at position 2.

    Design: Corner/validations/missing_x_user_role_header_returns_unauthenticated_before_role_check
    """
    headerless = api_client.create_exhibition(
        create_exhibition_payload(title="Header-less Attempt"),
        ARTIST_WITHOUT_ROLE_HEADER,
    )
    validate_error(headerless, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    wrong_role = api_client.create_exhibition(
        create_exhibition_payload(title="Wrong Role Attempt"), ARTIST_HEADERS
    )
    validate_error(wrong_role, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    _, meta = validate_paginated(api.list_exhibitions(CALL_MANAGER))
    assert meta["total_count"] == 0, "neither refused attempt created a row"


# ─── Target state ahead of the fee amount ──────────────

def test_a_draft_entry_reports_its_state_before_the_wrong_fee_amount(api):
    """PRD §2.10: "**Target state** — the target record is in a state from which
    the requested transition is declared, else the state code for that record
    type: `ERR_ENTRY_STATE_INVALID`, `ERR_ARTWORK_STATE_INVALID`,
    `ERR_JURY_ROUND_STATE_INVALID`, `ERR_AWARD_STATE_INVALID`,
    `ERR_SALE_STATE_INVALID`, or `ERR_ASSIGNMENT_STATE_INVALID`, all HTTP 409.
    Applies to every action endpoint." at position 7, ahead of "**Fee amount** —
    the tendered `amount_cents` equals the frozen `entry_fee_cents` exactly, else
    `ERR_FEE_AMOUNT_MISMATCH` (402)." at position 46.

    PRD §3.2: "The entry is created in `DRAFT` with `entry_fee_cents` at 0 —
    nothing is assessed until submission."

    Design: Corner/validations/entry_state_check_precedes_fee_amount_check
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="MEMBER")
    entry, artworks = fixtures.setup_entry_with_works(
        exhibition["id"], artist, ONE_WORK
    )
    artist_headers = make_artist_headers(artist["id"])

    too_early = api_client.pay_entry_fee(
        entry["id"], {"amount_cents": WRONG_AMOUNT_CENTS}, artist_headers
    )
    validate_error(too_early, ApiErrorId.ERR_ENTRY_STATE_INVALID.value, 409)

    still_draft = fixtures.read_entry(entry["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["entry_fee_cents"] == 0, "no assessment has been frozen"
    assert still_draft["fee_paid_cents"] == 0

    submitted = fixtures.submit_entry(entry["id"], artist)
    assert submitted["status"] == "PENDING_FEE"
    assert submitted["entry_fee_cents"] == MEMBER_BASE_LINE_CENTS

    wrong_amount = api_client.pay_entry_fee(
        entry["id"], {"amount_cents": WRONG_AMOUNT_CENTS}, artist_headers
    )
    validate_error(wrong_amount, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value, 402)

    unpaid = fixtures.read_entry(entry["id"])
    assert unpaid["status"] == "PENDING_FEE"
    assert unpaid["fee_paid_cents"] == 0
    assert fixtures.read_artwork(artworks[0]["id"])["status"] == "DRAFT", (
        "the cascade belongs to a successful payment only"
    )


# ─── The load limit is an aggregate ────────────────────

def test_two_light_works_together_exceed_the_walls_load_limit(api):
    """PRD §3.7: "And the wall must bear the load: its `loaded_weight_kg` plus the
    work's `weight_kg` must be at most the wall's `max_weight_kg`, else
    `ERR_WALL_WEIGHT_EXCEEDED`."

    PRD §3.7: "A successful plan carries the work `UNPLACED → PLANNED`, stores
    its `wall_segment_id`, `span_start_cm` and `span_end_cm`, and recomputes the
    wall's three derived figures: `occupied_cm` as the sum of span widths over the
    artworks assigned to that wall whose `placement_status` is `PLANNED` or
    `INSTALLED`, `available_cm` as the wall's `length_cm` minus `occupied_cm`, and
    `loaded_weight_kg` as the sum of `weight_kg` over the same set."

    Design: Corner/validations/wall_weight_aggregate_exceeds_capacity_though_each_work_is_light
    """
    ctx = fixtures.setup_installation_show(
        works=TWO_WORKS, wall_overrides={"max_weight_kg": HEAVY_WALL_LIMIT_KG}
    )
    wall, artworks = ctx["wall"], ctx["artworks"]
    first, second = artworks[0]["id"], artworks[1]["id"]

    for artwork_id in (first, second):
        fixtures.file_condition_report(artwork_id, "INTAKE", "A")
    assert fixtures.read_artwork(first)["weight_kg"] == FIRST_WORK_WEIGHT_KG
    assert fixtures.read_artwork(second)["weight_kg"] == SECOND_WORK_WEIGHT_KG
    assert (
        FIRST_WORK_WEIGHT_KG + SECOND_WORK_WEIGHT_KG > HEAVY_WALL_LIMIT_KG
        and SECOND_WORK_WEIGHT_KG < HEAVY_WALL_LIMIT_KG
    ), "each work fits alone; the pair does not"

    fixtures.plan_span(first, wall, 0.0, 100.0)
    loaded = fixtures.read_wall(wall["id"])
    assert loaded["loaded_weight_kg"] == FIRST_WORK_WEIGHT_KG
    assert loaded["occupied_cm"] == 100.0

    refused = _plan(second, wall["id"], 200.0, 300.0, loaded["version"])
    validate_error(refused, ApiErrorId.ERR_WALL_WEIGHT_EXCEEDED.value, 422)

    unplaced = fixtures.read_artwork(second)
    assert unplaced["placement_status"] == "UNPLACED"
    assert unplaced["wall_segment_id"] is None

    unchanged = fixtures.read_wall(wall["id"])
    assert unchanged["loaded_weight_kg"] == FIRST_WORK_WEIGHT_KG
    assert unchanged["occupied_cm"] == 100.0
    assert unchanged["available_cm"] == 500.0
    assert unchanged["version"] == loaded["version"], (
        "a refused plan writes nothing to the wall"
    )


# ─── The discount branch is keyed on membership ─────────

def test_only_the_member_artist_pays_the_discounted_lines(api):
    """PRD §3.3: "A discount fraction is taken: it is the exhibition's
    `member_discount_pct` when the artist's `member_status` is `MEMBER`, and zero
    otherwise."

    PRD §3.2: "Three further attributes may be set at registration or later:
    `member_status`, either `MEMBER` or `NON_MEMBER` (the default), which decides
    the entry-fee discount; `tax_form_on_file`, false by default, which gates
    every payout; and `payout_method`, either `CHECK` (the default) or `ACH`."

    Design: Corner/validations/member_discount_applies_only_to_member_artists
    """
    exhibition = fixtures.open_call()

    member = fixtures.register_artist(
        legal_name="Ana Ruiz", member_status="MEMBER"
    )
    non_member_payload = create_artist_payload(
        legal_name="Bo Nakamura", email="bo.nakamura@example.org"
    )
    del non_member_payload["member_status"]
    non_member = validate_success(
        api.create_artist(non_member_payload, CALL_MANAGER), 201
    )
    assert non_member["member_status"] == "NON_MEMBER", "the omitted default"

    member_entry, _ = fixtures.setup_entry_with_works(
        exhibition["id"], member, ONE_WORK
    )
    non_member_entry, _ = fixtures.setup_entry_with_works(
        exhibition["id"], non_member, ONE_WORK
    )

    member_submitted = fixtures.submit_entry(member_entry["id"], member)
    non_member_submitted = fixtures.submit_entry(
        non_member_entry["id"], non_member
    )
    assert member_submitted["entry_fee_cents"] == MEMBER_BASE_LINE_CENTS
    assert non_member_submitted["entry_fee_cents"] == NON_MEMBER_BASE_LINE_CENTS, (
        "no discount branch is taken for a non-member"
    )

    borrowed_discount = api_client.pay_entry_fee(
        non_member_entry["id"],
        {"amount_cents": MEMBER_BASE_LINE_CENTS},
        make_artist_headers(non_member["id"]),
    )
    validate_error(
        borrowed_discount, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value, 402
    )

    member_paid = fixtures.pay_entry_fee(
        member_entry["id"], member, MEMBER_BASE_LINE_CENTS
    )
    non_member_paid = fixtures.pay_entry_fee(
        non_member_entry["id"], non_member, NON_MEMBER_BASE_LINE_CENTS
    )
    assert member_paid["status"] == "SUBMITTED"
    assert member_paid["fee_paid_cents"] == MEMBER_BASE_LINE_CENTS
    assert non_member_paid["status"] == "SUBMITTED"
    assert non_member_paid["fee_paid_cents"] == NON_MEMBER_BASE_LINE_CENTS


# ─── The opening gate is inclusive ─────────────────────

def test_the_show_opens_at_the_opening_instant_and_not_one_second_before(api):
    """PRD §2.6: "The public phases are gated by lower bounds only: the show may
    not go on view before `opening_at` and may not close before `closing_at`, and
    a premature request is rejected with `ERR_PHASE_TIME_NOT_REACHED`."

    PRD §3.7: "Advancing `INSTALLATION → ON_VIEW` requires that **every** artwork
    of the exhibition whose `status` is `ACCEPTED` or `DELIVERED` have
    `placement_status` `INSTALLED`, else `ERR_INSTALLATION_INCOMPLETE`, and
    requires the clock to have reached `opening_at`, else
    `ERR_PHASE_TIME_NOT_REACHED`."

    Design: Corner/validations/on_view_advance_before_opening_at_is_refused_then_allowed_at_the_instant
    """
    ctx = fixtures.setup_installation_show(works=ONE_WORK)
    exhibition_id = ctx["exhibition"]["id"]
    artwork_id = ctx["artworks"][0]["id"]

    fixtures.hang_artworks([artwork_id], ctx["wall"])
    assert fixtures.read_exhibition(exhibition_id)["opening_at"] == OPENING_INSTANT

    fixtures.set_clock(ONE_SECOND_BEFORE_OPENING)
    premature = api_client.advance_exhibition_phase(
        exhibition_id, {"target_status": "ON_VIEW"}, CALL_MANAGER
    )
    validate_error(premature, ApiErrorId.ERR_PHASE_TIME_NOT_REACHED.value, 409)

    assert fixtures.read_exhibition(exhibition_id)["status"] == "INSTALLATION"
    waiting = fixtures.read_artwork(artwork_id)
    assert waiting["status"] == "DELIVERED"
    assert waiting["placement_status"] == "INSTALLED", (
        "every other precondition is already satisfied"
    )

    fixtures.set_clock(OPENING_INSTANT)
    opened = validate_success(
        api_client.advance_exhibition_phase(
            exhibition_id, {"target_status": "ON_VIEW"}, CALL_MANAGER
        )
    )
    assert opened["status"] == "ON_VIEW", "equality passes"
    assert fixtures.read_artwork(artwork_id)["status"] == "ON_VIEW"


# ─── Cross-exhibition coherence ────────────────────────

def test_a_wall_from_another_exhibition_is_a_scope_mismatch(api):
    """PRD §2.5: "Four such checks exist, and all four report
    `ERR_EXHIBITION_SCOPE_MISMATCH` (HTTP 422): the wall segment named in an
    installation plan must belong to the same exhibition as the artwork being
    planned; the artwork named in a score must belong to the exhibition that owns
    the jury round; the artwork named on an award must belong to the award's
    exhibition; and a sponsor attached to an award must belong to that same
    exhibition."

    PRD §3.7: "The wall must belong to the same exhibition as the work, else
    `ERR_EXHIBITION_SCOPE_MISMATCH`."

    Design: Corner/validations/installation_plan_with_foreign_exhibition_wall_returns_scope_mismatch
    """
    other_exhibition = fixtures.create_exhibition(title="Winter Members Call")
    foreign_wall = fixtures.register_wall(other_exhibition["id"], label="W2")

    ctx = fixtures.setup_installation_show(works=ONE_WORK)
    artwork_id = ctx["artworks"][0]["id"]
    own_wall = ctx["wall"]
    fixtures.file_condition_report(artwork_id, "INTAKE", "A")

    foreign_before = fixtures.read_wall(foreign_wall["id"])
    refused = _plan(
        artwork_id, foreign_wall["id"], 0.0, 100.0, foreign_before["version"]
    )
    validate_error(
        refused, ApiErrorId.ERR_EXHIBITION_SCOPE_MISMATCH.value, 422
    )

    foreign_after = fixtures.read_wall(foreign_wall["id"])
    assert foreign_after["occupied_cm"] == 0.0
    assert foreign_after["loaded_weight_kg"] == 0.0
    assert foreign_after["version"] == foreign_before["version"], (
        "the version quoted was current, so only the coherence rule fired"
    )
    assert fixtures.read_artwork(artwork_id)["placement_status"] == "UNPLACED"

    planned = fixtures.plan_span(artwork_id, own_wall, 0.0, 100.0)
    assert planned["placement_status"] == "PLANNED"
    assert planned["wall_segment_id"] == own_wall["id"]
    assert fixtures.read_wall(own_wall["id"])["occupied_cm"] == 100.0

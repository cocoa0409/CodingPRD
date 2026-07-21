"""The offer catalogue: creation, half-open windows, publication and suspension."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_offer,
    create_active_program,
    create_offer_payload,
    create_program,
    create_published_offer,
    open_claim,
    read_claim,
    read_offer,
    set_clock,
    setup_catalogue,
    setup_submitted_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


def test_offer_defaults_dealer_tier_enabled_and_starts_in_draft(api):
    """PRD §3.2: "An optional `dealer_tier_enabled` flag defaults to true; when it
    is false, dealer claims against this offer price at the lowest tier regardless
    of how many units they cover. Offers begin in `DRAFT`, carry `closed_at` as
    null until closure, and expose an `active_claim_count` that starts at zero."

    Design: Corner/entities/offer_dealer_tier_enabled_defaults_to_true_when_omitted
    """
    program = create_active_program(name="Default Program", budget_total_cents=100000000)
    data = validate_success(
        api.create_offer(
            create_offer_payload(program["id"], name="Default Offer"), ADMIN
        ),
        201,
    )
    assert_offer(data)
    assert data["dealer_tier_enabled"] is True
    assert data["status"] == "DRAFT"
    assert data["active_claim_count"] == 0
    assert data["closed_at"] is None


def test_offer_window_ending_where_it_starts_is_a_validation_error(api):
    """PRD §2.8: "Shape validation — required fields present, enum values drawn
    from their declared sets, constrained integers positive, an offer's
    `effective_end_date` strictly later than its `effective_start_date`, and a
    receipt's `lines` a non-empty array each of whose entries carries `sku`, a
    `quantity` greater than zero and a `unit_price_cents` greater than zero.
    Any breach is `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_offer_with_end_not_after_start_is_rejected
    """
    program = create_active_program(name="Window Program", budget_total_cents=100000000)
    resp = api.create_offer(
        create_offer_payload(
            program["id"],
            name="Inverted Offer",
            effective_start_date="2026-09-01T00:00:00Z",
            effective_end_date="2026-09-01T00:00:00Z",
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_offer_created_against_an_unknown_program_is_not_found(api):
    """PRD §2.8: "Body foreign keys — every identifier supplied in a request body
    (`program_id`, `offer_id`, `claimant_id`, `claim_id`) must resolve to an
    existing row, else the corresponding not-found error. This applies when
    creating an offer, opening a claim, and opening a fraud case."

    Design: Corner/entities/create_offer_against_unknown_program_is_not_found
    """
    resp = api.create_offer(
        create_offer_payload(
            "00000000-0000-4000-8000-000000000001", name="Orphan Offer"
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value)


def test_publishing_under_a_draft_program_is_refused(api):
    """PRD §3.2: "Publication is permitted from `DRAFT` and from `SUSPENDED`, and
    requires the funding program to be `ACTIVE` — a program still in `DRAFT`,
    locked at `BUDGET_LOCKED`, or `CLOSED` cannot have offers published under it,
    and the attempt reports `ERR_PROGRAM_NOT_ACTIVE`."

    Design: Corner/state_machines/publish_offer_while_program_is_draft_is_rejected
    """
    program = create_program(name="Unactivated Program", budget_total_cents=100000000)
    offer = validate_success(
        api.create_offer(create_offer_payload(program["id"], name="Early Offer"), ADMIN), 201
    )
    resp = api.publish_offer(offer["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE.value)
    assert read_offer(offer["id"])["status"] == "DRAFT"


def test_suspending_an_offer_voids_only_its_draft_claims(api):
    """PRD §3.2: "Suspension has one cascade: every claim on the offer still in
    `DRAFT` moves `DRAFT → VOIDED`. Claims already `SUBMITTED`, `UNDER_REVIEW` or
    `HELD` are untouched by suspension and continue to adjudicate to completion."

    Design: Corner/state_machines/suspending_an_offer_voids_only_its_draft_claims
    """
    ctx = setup_submitted_claim(
        program_overrides={"name": "Suspend Program"},
        budget_total_cents=100000000,
        offer_overrides={"name": "Suspend Offer"},
        lines=[{"sku": "TOOLS-A", "quantity": 2, "unit_price_cents": 1000}],
    )
    draft_claim = open_claim(ctx["offer"]["id"], ctx["claimant"])

    suspended = validate_success(api.suspend_offer(ctx["offer"]["id"], ADMIN))
    assert suspended["status"] == "SUSPENDED"
    assert read_claim(draft_claim["id"])["adjudication_status"] == "VOIDED"
    assert read_claim(ctx["claim"]["id"])["adjudication_status"] == "SUBMITTED"
    assert read_offer(ctx["offer"]["id"])["active_claim_count"] == 1


def test_republished_offer_accepts_new_claims_without_reviving_voided_ones(api):
    """PRD §3.2: "Republishing from `SUSPENDED` restores eligibility for new claims
    but does not resurrect the voided ones, and it re-runs the same window-overlap
    check and the same requirement that the program be `ACTIVE`; the `PUBLISHED →
    SUSPENDED → PUBLISHED` cycle may repeat indefinitely."

    Design: Corner/state_machines/suspended_offer_republishes_and_accepts_new_claims
    """
    ctx = setup_catalogue(
        program_overrides={"name": "Republish Program"},
        budget_total_cents=100000000,
        offer_overrides={"name": "Republish Offer"},
    )
    voided_claim = open_claim(ctx["offer"]["id"], ctx["claimant"])
    validate_success(api.suspend_offer(ctx["offer"]["id"], ADMIN))

    republished = validate_success(api.publish_offer(ctx["offer"]["id"], ADMIN))
    assert republished["status"] == "PUBLISHED"

    fresh = validate_success(
        api.create_claim(
            {"offer_id": ctx["offer"]["id"], "claimant_id": ctx["claimant"]["id"]},
            ctx["headers"],
        ),
        201,
    )
    assert fresh["adjudication_status"] == "DRAFT"
    assert read_claim(voided_claim["id"])["adjudication_status"] == "VOIDED"


# --------------------------------------------------------------------------- #
# Half-open sibling-window collision detection
# --------------------------------------------------------------------------- #

def test_offer_window_touching_an_incumbent_is_allowed(api):
    """PRD §3.2: "No two offers sharing the same `program_id`, the same
    `sku_scope` and the same `channel`, and both in a live state (`DRAFT`,
    `PUBLISHED` or `SUSPENDED`), may have intersecting half-open windows; windows
    that merely touch — one ending exactly where the other begins — do not
    intersect and are permitted."

    Design: Difficulty/resource_temporal_overlap/offer_windows_are_half_open_so_touching_is_allowed_and_straddling_is_not
    """
    set_clock("2026-07-10T00:00:00Z")
    program = create_active_program(name="Overlap Program", budget_total_cents=100000000)
    create_published_offer(
        program["id"],
        name="Incumbent Offer",
        sku_scope="TOOLS",
        effective_start_date="2026-06-01T00:00:00Z",
        effective_end_date="2026-09-01T00:00:00Z",
    )

    adjacent = validate_success(
        api.create_offer(
            create_offer_payload(
                program["id"],
                name="Adjacent Offer",
                sku_scope="TOOLS",
                effective_start_date="2026-09-01T00:00:00Z",
                effective_end_date="2026-11-01T00:00:00Z",
            ),
            ADMIN,
        ),
        201,
    )
    assert adjacent["status"] == "DRAFT"


def test_offer_window_straddling_an_incumbent_is_refused(api):
    """PRD §3.2: "A collision is refused with `ERR_OFFER_WINDOW_OVERLAP` (HTTP 409),
    and the check runs both when an offer is created and again when one is
    published."

    Design: Difficulty/resource_temporal_overlap/offer_windows_are_half_open_so_touching_is_allowed_and_straddling_is_not
    """
    set_clock("2026-07-10T00:00:00Z")
    program = create_active_program(name="Overlap Program", budget_total_cents=100000000)
    incumbent = create_published_offer(
        program["id"],
        name="Incumbent Offer",
        sku_scope="TOOLS",
        effective_start_date="2026-06-01T00:00:00Z",
        effective_end_date="2026-09-01T00:00:00Z",
    )
    validate_success(
        api.create_offer(
            create_offer_payload(
                program["id"],
                name="Adjacent Offer",
                sku_scope="TOOLS",
                effective_start_date="2026-09-01T00:00:00Z",
                effective_end_date="2026-11-01T00:00:00Z",
            ),
            ADMIN,
        ),
        201,
    )

    resp = api.create_offer(
        create_offer_payload(
            program["id"],
            name="Straddling Offer",
            sku_scope="TOOLS",
            effective_start_date="2026-08-15T00:00:00Z",
            effective_end_date="2026-10-01T00:00:00Z",
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_OFFER_WINDOW_OVERLAP.value)

    offers, meta = validate_paginated(
        api.list_offers(ADMIN, params={"program_id": program["id"]})
    )
    assert meta["total_count"] == 2, "The rejected straddling offer must not be persisted"
    assert incumbent["id"] in {o["id"] for o in offers}

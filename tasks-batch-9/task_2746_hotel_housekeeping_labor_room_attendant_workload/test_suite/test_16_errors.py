"""Error selection at the boundaries: half-open retention, graded proof, unknown roles."""

from test_helpers import (
    CATEGORY_HIGH_VALUE,
    CATEGORY_ID_DOCUMENT,
    CATEGORY_PERISHABLE,
    CATEGORY_STANDARD,
    DEFAULT_CLOCK,
    DIRECTOR_HEADERS,
    DISPOSITION_DISPOSED,
    DISPOSITION_DONATED,
    FRONT_DESK_HEADERS,
    ITEM_CLAIM_PENDING,
    ITEM_DISPOSED,
    ITEM_STORED,
    PROOF_DESCRIPTION_MATCH,
    PROOF_PHOTO_ID,
    ApiErrorId,
    assert_instant_equals,
    assert_is_null,
    build_lost_found,
    claim_payload,
    create_property,
    dispose_payload,
    lost_found_payload,
    make_headers,
    read_item,
    set_clock,
    store_payload,
    validate_error,
    validate_success,
)

STANDARD_EXPIRY = "2026-09-02T07:00:00.000Z"
ONE_MILLISECOND_EARLIER = "2026-09-02T06:59:59.999Z"


def _store_another_item(context, category, description, storage_bin):
    """Log and bin a second item at the same property as `context`."""
    logged = validate_success(
        context.api.create_lost_found_item(
            lost_found_payload(
                context.prop["id"],
                context.room["id"],
                context.finder["id"],
                description=description,
                category=category,
            ),
            context.supervisor_headers(),
        ),
        201,
    )
    return validate_success(
        context.api.store_item(
            logged["id"], store_payload(storage_bin), context.supervisor_headers()
        ),
        200,
    )


# --------------------------------------------------------------------------
# The two sides of the retention boundary
# --------------------------------------------------------------------------


def test_a_claim_at_the_expiry_instant_is_already_too_late(api):
    """The boundary instant belongs to disposal, so one millisecond earlier still claims.

    PRD 3.9: "A claim is accepted while the logical clock is **strictly before**
    `retention_expires_at`; at or after that instant a claim is refused with
    `ERR_RETENTION_EXPIRED` (HTTP 422)."

    Design: Corner/errors/err_claim_at_the_retention_boundary_instant_is_rejected
    """
    context = build_lost_found(api, stored=True)
    assert_instant_equals(
        context.item["retention_expires_at"], STANDARD_EXPIRY, "retention_expires_at"
    )
    set_clock(api, STANDARD_EXPIRY)

    response = api.claim_item(context.item_id, claim_payload(), FRONT_DESK_HEADERS)

    validate_error(response, ApiErrorId.RETENTION_EXPIRED, 422)
    refused = read_item(api, context.item_id)
    assert refused["status"] == ITEM_STORED
    assert refused["claim_attempt_count"] == 0
    set_clock(api, ONE_MILLISECOND_EARLIER)
    claimed = validate_success(
        api.claim_item(context.item_id, claim_payload(), FRONT_DESK_HEADERS), 200
    )
    assert claimed["status"] == ITEM_CLAIM_PENDING, (
        "a millisecond inside the window is still a live claim"
    )
    assert claimed["claim_attempt_count"] == 1


def test_a_disposal_a_millisecond_early_is_refused(api):
    """Disposal owns the boundary instant and nothing before it.

    PRD 3.9: "Disposal is accepted while the logical clock is **at or after**
    `retention_expires_at`; before it, disposal is refused with
    `ERR_RETENTION_ACTIVE` (HTTP 409)."

    Design: Corner/errors/err_disposal_one_millisecond_before_expiry_is_rejected
    """
    context = build_lost_found(api, stored=True)
    assert context.item["retention_days"] == 30
    set_clock(api, ONE_MILLISECOND_EARLIER)

    response = api.dispose_item(
        context.item_id,
        dispose_payload(DISPOSITION_DISPOSED),
        context.supervisor_headers(),
    )

    validate_error(response, ApiErrorId.RETENTION_ACTIVE, 409)
    assert read_item(api, context.item_id)["status"] == ITEM_STORED, (
        "a refused disposal must leave the item short of a terminal status"
    )
    set_clock(api, STANDARD_EXPIRY)
    disposed = validate_success(
        api.dispose_item(
            context.item_id,
            dispose_payload(DISPOSITION_DISPOSED),
            context.supervisor_headers(),
        ),
        200,
    )
    assert disposed["status"] == ITEM_DISPOSED


# --------------------------------------------------------------------------
# Proof is graded by category
# --------------------------------------------------------------------------


def test_a_description_match_alone_cannot_claim_a_high_value_item(api):
    """The same proof that clears a standard item is refused on the valuable one.

    PRD 3.9: "Proof sufficiency is graded by category: a `HIGH_VALUE` or
    `ID_DOCUMENT` item requires either `PHOTO_ID` or `RECEIPT`, and
    `DESCRIPTION_MATCH` alone is insufficient for those two categories, which is
    refused with `ERR_PROOF_INSUFFICIENT` (HTTP 422)."

    Design: Corner/errors/err_high_value_claim_on_description_match_alone_is_rejected
    """
    context = build_lost_found(api, category=CATEGORY_HIGH_VALUE, stored=True)
    assert context.item["retention_days"] == 90
    assert_instant_equals(
        context.item["retention_expires_at"],
        "2026-11-01T07:00:00.000Z",
        "retention_expires_at",
    )
    ordinary = _store_another_item(
        context, CATEGORY_STANDARD, "Grey knitted scarf on the chair", "B-14"
    )

    response = api.claim_item(
        context.item_id,
        claim_payload(proof_kind=PROOF_DESCRIPTION_MATCH),
        FRONT_DESK_HEADERS,
    )

    validate_error(response, ApiErrorId.PROOF_INSUFFICIENT, 422)
    refused = read_item(api, context.item_id)
    assert refused["status"] == ITEM_STORED
    assert refused["claim_attempt_count"] == 0
    assert_is_null(refused["proof_kind"], "proof_kind")
    accepted = validate_success(
        api.claim_item(
            ordinary["id"],
            claim_payload(proof_kind=PROOF_DESCRIPTION_MATCH),
            FRONT_DESK_HEADERS,
        ),
        200,
    )
    assert accepted["status"] == ITEM_CLAIM_PENDING
    assert accepted["claim_attempt_count"] == 1
    with_photo = validate_success(
        api.claim_item(
            context.item_id,
            claim_payload(proof_kind=PROOF_PHOTO_ID),
            FRONT_DESK_HEADERS,
        ),
        200,
    )
    assert with_photo["status"] == ITEM_CLAIM_PENDING


# --------------------------------------------------------------------------
# Disposition is graded by category too
# --------------------------------------------------------------------------


def test_an_identity_document_may_be_destroyed_but_never_donated(api):
    """Retention has closed, so only the disposition itself can be the objection.

    PRD 3.9: "Donation is only permitted for items whose `category` is `STANDARD`
    or `PERISHABLE`; an `ID_DOCUMENT` or `HIGH_VALUE` item may never be donated and
    the attempt is refused with `ERR_DISPOSITION_NOT_PERMITTED`."

    Design: Corner/errors/err_id_document_cannot_be_donated_after_retention
    """
    context = build_lost_found(api, category=CATEGORY_ID_DOCUMENT, stored=True)
    assert context.item["retention_days"] == 60
    assert_instant_equals(
        context.item["retention_expires_at"],
        "2026-10-02T07:00:00.000Z",
        "retention_expires_at",
    )
    set_clock(api, "2026-10-02T07:00:00.000Z")

    response = api.dispose_item(
        context.item_id,
        dispose_payload(DISPOSITION_DONATED),
        context.supervisor_headers(),
    )

    validate_error(response, ApiErrorId.DISPOSITION_NOT_PERMITTED, 422)
    assert read_item(api, context.item_id)["status"] == ITEM_STORED
    destroyed = validate_success(
        api.dispose_item(
            context.item_id,
            dispose_payload(DISPOSITION_DISPOSED),
            context.supervisor_headers(),
        ),
        200,
    )
    assert destroyed["status"] == ITEM_DISPOSED, (
        "the window is closed, so destruction of the same item must be permitted"
    )


# --------------------------------------------------------------------------
# The degenerate window
# --------------------------------------------------------------------------


def test_a_perishable_item_can_never_be_claimed_at_all(api):
    """Its window closes at the instant it opens, so the first claim is already late.

    PRD 3.9: "A consequence worth stating plainly: a `PERISHABLE` item has a
    retention window of zero days, so `retention_expires_at` equals `stored_at`, its
    claim window is empty, and disposal is permitted the instant it is stored."

    Design: Corner/errors/err_perishable_item_has_an_empty_claim_window
    """
    context = build_lost_found(api, category=CATEGORY_PERISHABLE, stored=True)
    assert context.item["retention_days"] == 0
    assert_instant_equals(
        context.item["retention_expires_at"], DEFAULT_CLOCK, "retention_expires_at"
    )
    assert_instant_equals(context.item["stored_at"], DEFAULT_CLOCK, "stored_at")

    response = api.claim_item(context.item_id, claim_payload(), FRONT_DESK_HEADERS)

    validate_error(response, ApiErrorId.RETENTION_EXPIRED, 422)
    refused = read_item(api, context.item_id)
    assert refused["status"] == ITEM_STORED
    assert refused["claim_attempt_count"] == 0
    disposed = validate_success(
        api.dispose_item(
            context.item_id,
            dispose_payload(DISPOSITION_DISPOSED),
            context.supervisor_headers(),
        ),
        200,
    )
    assert disposed["status"] == ITEM_DISPOSED, (
        "disposal is permitted at the very instant the item was stored"
    )


# --------------------------------------------------------------------------
# An unknown role is not a role without a grant
# --------------------------------------------------------------------------


def test_an_unrecognised_role_string_is_an_authentication_failure(api):
    """The role is present and well-formed but unknown, which is a 401 rather than a 403.

    PRD 2.1: "An `X-User-Role` value that is not one of those six strings is also
    treated as `ERR_UNAUTHENTICATED` — an unrecognised role is an authentication
    failure, never a permission failure."

    Design: Corner/errors/err_unrecognized_role_string_is_unauthenticated_not_forbidden
    """
    set_clock(api, DEFAULT_CLOCK)
    prop = create_property(api)

    response = api.get_property(
        prop["id"], make_headers("HeadOfHousekeeping", "boss-user-1")
    )

    error = validate_error(response, ApiErrorId.UNAUTHENTICATED, 401)
    assert error["error_id"] != "ERR_ROLE_NOT_PERMITTED", (
        "an unknown role must never be reported as a missing grant"
    )
    readable = validate_success(api.get_property(prop["id"], DIRECTOR_HEADERS), 200)
    assert readable["name"] == "Harborview Hotel"

"""Corner tests — validation errors, uniqueness, FK integrity, referential
guards, refund limits, temporal payout window, RBAC role denials."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    get_success_data,
    NON_EXISTENT_UUID,
    make_platform_admin_headers,
    make_anonymous_headers,
    make_creator_headers,
    make_fulfillment_partner_headers,
    set_clock,
    setup_basic_scenario,
    create_verified_creator,
    create_creator,
    create_active_partner,
    create_product_and_variant,
    create_storefront,
    upload_and_approve_design,
    create_and_publish_listing,
    create_and_capture_order,
    advance_order_to_delivered,
    create_payout_cycle,
    release_payout_cycle,
    create_order_and_authorize,
    creator_register_payload,
    design_payload,
    storefront_payload,
    listing_payload,
    order_payload,
    refund_payload,
)


# =============================================================================
# Corner: entities — required fields / uniqueness / constraints
# =============================================================================

def test_creator_register_missing_email_returns_invalid_request(api):
    """PRD §3.1: "A new creator joins the platform anonymously by registering
    with three fields: their unique `email`, a public `display_name` that will
    appear on their storefront, and a two-letter `payout_country_code` in
    ISO-3166 alpha-2 form denoting the country of the bank account that will
    eventually receive payouts."
    PRD §5 (error table): "ERR_INVALID_REQUEST | 400"
    (PRD §2.9: "Priorities 11 through 17 cover the business constraints" —
    ERR_INVALID_REQUEST is the malformed-request surface for missing required inputs.)

    Registration payload missing `email` -> ERR_INVALID_REQUEST.

    Design: Corner/entities/creator_register_missing_email_returns_invalid_request
    """
    resp = api.register_creator(
        {"display_name": "NoEmail", "payout_country_code": "US"},
        make_anonymous_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_design_upload_duplicate_hash_for_same_creator_returns_conflict(api):
    """PRD §3.5: "The platform enforces per-creator hash uniqueness: an attempt
    to upload a design whose `(creator_id, file_hash)` pair already exists for
    that creator is rejected with `ERR_DESIGN_DUPLICATE_HASH`."

    Second upload with the same file_hash under the same creator -> 409 conflict.

    Design: Corner/entities/design_upload_duplicate_hash_for_same_creator_returns_conflict
    """
    set_clock("2026-06-01T00:00:00Z")
    creator = create_verified_creator(email="cvd@example.com", display_name="CVD")
    headers = make_creator_headers(creator["id"])
    api.upload_design(
        creator["id"], design_payload(file_hash="hash_dupe_1"), headers,
    )
    resp = api.upload_design(
        creator["id"], design_payload(file_hash="hash_dupe_1"), headers,
    )
    validate_error(resp, ApiErrorId.ERR_DESIGN_DUPLICATE_HASH)


def test_storefront_markup_10001_rejected_upper_boundary(api):
    """PRD §3.2: "The markup value must fall in the inclusive range from 0 to
    10000 basis-points (0% to 100%); a submission of 10001 or above is rejected
    with `ERR_MARKUP_OUT_OF_RANGE`, and the same range constraint applies when
    updating an existing storefront's markup."

    Design: Corner/entities/storefront_markup_out_of_range_upper_boundary
    """
    set_clock("2026-06-01T00:00:00Z")
    creator = create_verified_creator(email="mub@example.com", display_name="MUB")
    resp = api.create_storefront(
        storefront_payload(
            creator["id"], slug="mub-sf", integration_channel="NATIVE", markup_bps=10001,
        ),
        make_creator_headers(creator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MARKUP_OUT_OF_RANGE)


# =============================================================================
# Corner: validations — cross-entity referential
# =============================================================================

def test_listing_with_design_from_different_creator_returns_mismatch(api):
    """PRD §3.6: "Two referential guards apply. First, the design named by
    `design_id` and the storefront named by `storefront_id` must belong to the
    same creator: the storefront's `creator_id` and the design's `creator_id`
    must match, and a mismatch is rejected with `ERR_DESIGN_CREATOR_MISMATCH`."

    Storefront owned by Creator A + Design owned by Creator B -> mismatch.

    Design: Corner/validations/listing_creator_mismatch_returns_referential_error
    """
    set_clock("2026-06-01T00:00:00Z")
    product, variant = create_product_and_variant(sku="T-MIS")
    creator_a = create_verified_creator(email="mis-a@example.com", display_name="MIS-A")
    creator_b = create_verified_creator(email="mis-b@example.com", display_name="MIS-B")
    sf_a = create_storefront(creator_a["id"], slug="mis-a-sf", markup_bps=5000)
    design_b = upload_and_approve_design(creator_b["id"], file_hash="hash_mis_b")

    # Creator A tries to list Creator B's design under A's storefront.
    resp = api.create_listing(
        listing_payload(sf_a["id"], design_b["id"], variant["id"], title="Cross Tee"),
        make_creator_headers(creator_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DESIGN_CREATOR_MISMATCH)


def test_order_against_draft_listing_returns_not_available(api):
    """PRD §3.6: "listings are ordered only when their underlying artwork is fit
    for print, so the availability check applied at order time (below) requires
    the design's `status` to be `APPROVED`, the variant's `active` flag to be
    true, and the listing itself to be `PUBLISHED`; violation of any of those
    three conditions surfaces at order creation as `ERR_LISTING_NOT_AVAILABLE`."

    A DRAFT (never-published) listing rejects order creation.

    Design: Corner/validations/order_against_unpublished_listing_returns_not_available
    """
    set_clock("2026-06-01T00:00:00Z")
    product, variant = create_product_and_variant(sku="T-DRF")
    creator = create_verified_creator(email="drf@example.com", display_name="DRF")
    sf = create_storefront(creator["id"], slug="drf-sf", markup_bps=5000)
    design = upload_and_approve_design(creator["id"], file_hash="hash_drf")
    # Create listing but DO NOT publish.
    draft_listing = get_success_data(api.create_listing(
        listing_payload(sf["id"], design["id"], variant["id"], title="Draft Tee"),
        make_creator_headers(creator["id"]),
    ))
    assert draft_listing["status"] == "DRAFT"

    resp = api.create_order(
        order_payload(sf["id"], draft_listing["id"], item_count=1),
        make_anonymous_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_AVAILABLE)


def test_refund_amount_exceeds_gross_returns_invalid(api):
    """PRD §3.7: "An admin issues a refund by supplying `refund_amount_cents`.
    The amount must be strictly positive and no greater than the order's
    `gross_amount_cents`; a zero or negative amount or an amount exceeding the
    gross is rejected with `ERR_REFUND_AMOUNT_INVALID`."

    Design: Corner/validations/refund_amount_exceeds_gross_returns_fiscal_error
    """
    scenario = setup_basic_scenario(
        creator_email="ref@example.com", display_name="REF", slug="ref-sf",
        sku="T-REF", markup_bps=5000, file_hash="hash_ref",
    )
    order, _ = create_and_capture_order(scenario, item_count=1)
    resp = api.refund_order(
        order["id"], refund_payload(999999999), make_platform_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_REFUND_AMOUNT_INVALID)


# =============================================================================
# Corner: errors — temporal windows, FK, not-found
# =============================================================================

def test_payout_return_after_72h_returns_window_expired(api):
    """PRD §3.9: "A released payout may be reversed within a 72-hour bank recall
    window. An admin returning a cycle at `RELEASED` moves it to `RETURNED`
    provided the current logical-clock instant is strictly less than the cycle's
    `updated_at` at release plus 72 hours; a return attempted after that window
    closes is rejected with `ERR_PAYOUT_RETURN_WINDOW_EXPIRED`."

    Release at 2026-06-15T00Z, advance clock to 2026-06-18T01Z (73h later),
    return -> ERR_PAYOUT_RETURN_WINDOW_EXPIRED.

    Design: Corner/errors/payout_return_after_72h_returns_window_expired
    """
    scenario = setup_basic_scenario(
        creator_email="rw@example.com", display_name="RW", slug="rw-sf",
        sku="T-RW", markup_bps=5000, file_hash="hash_rw",
        clock_iso="2026-06-15T00:00:00Z",
    )
    order, _ = create_and_capture_order(scenario, item_count=1)
    advance_order_to_delivered(scenario, order)
    cycle = create_payout_cycle(
        scenario["creator"]["id"],
        cycle_start="2026-06-01T00:00:00Z",
        cycle_end="2026-06-30T00:00:00Z",
    )
    release_payout_cycle(cycle["id"])
    # Advance beyond 72h.
    set_clock("2026-06-18T01:00:00Z")
    resp = api.return_payout(cycle["id"], make_platform_admin_headers())
    validate_error(resp, ApiErrorId.ERR_PAYOUT_RETURN_WINDOW_EXPIRED)


def test_listing_create_with_unknown_design_id_returns_fk_not_found(api):
    """PRD §2.8: "Foreign-key fields in a request body are validated after path
    resolution: any `storefront_id`, `design_id`, `variant_id`, `listing_id`,
    `order_id`, `partner_id`, `product_id`, `creator_id`, `job_id`,
    `routed_partner_id`, or `country_code` reference in a body that fails to
    resolve produces `ERR_FK_NOT_FOUND` with HTTP 404."

    Design: Corner/errors/fk_not_found_on_listing_create_with_bad_design_id
    """
    set_clock("2026-06-01T00:00:00Z")
    product, variant = create_product_and_variant(sku="T-FK")
    creator = create_verified_creator(email="fk@example.com", display_name="FK")
    sf = create_storefront(creator["id"], slug="fk-sf", markup_bps=5000)

    resp = api.create_listing(
        listing_payload(sf["id"], NON_EXISTENT_UUID, variant["id"], title="Ghost Tee"),
        make_creator_headers(creator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND)


def test_get_creator_with_unknown_id_returns_not_found(api):
    """PRD §2.8: "The parent `id` is resolved first; if the parent does not
    exist, the response is `ERR_NOT_FOUND` with HTTP 404 for the parent,
    regardless of whether the child would have existed."

    Design: Corner/errors/creator_not_found_on_get_returns_not_found
    """
    resp = api.get_creator(NON_EXISTENT_UUID, make_platform_admin_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


# =============================================================================
# Corner: RBAC — role denials
# =============================================================================

def test_creator_role_cannot_approve_design(api):
    """PRD §4 (endpoint table): "POST | `/pod/designs/{id}/approve` | Approve a
    design. | `PlatformAdmin`"
    PRD §2.1: "A well-formed header pair whose role is not permitted to invoke
    the requested endpoint produces `ERR_FORBIDDEN` with HTTP 403."

    A Creator calling POST /pod/designs/{id}/approve (PlatformAdmin-only) gets
    ERR_FORBIDDEN.

    Design: Corner/rbac/creator_cannot_approve_design
    """
    set_clock("2026-06-01T00:00:00Z")
    creator = create_verified_creator(email="rba@example.com", display_name="RBA")
    headers = make_creator_headers(creator["id"])
    up = get_success_data(api.upload_design(
        creator["id"], design_payload(file_hash="hash_rba"), headers,
    ))
    get_success_data(api.generate_mockup(up["id"], headers))
    # Now design is MOCKUP_READY. Creator tries to approve.
    resp = api.approve_design(up["id"], headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_fulfillment_partner_role_cannot_capture_order(api):
    """PRD §4 (endpoint table): "POST | `/pod/orders/{id}/capture` | Capture
    the buyer's payment and route. | `PlatformAdmin`"
    PRD §2.1: "A well-formed header pair whose role is not permitted to invoke
    the requested endpoint produces `ERR_FORBIDDEN` with HTTP 403."

    A FulfillmentPartner calling capture (PlatformAdmin-only) gets ERR_FORBIDDEN.

    Design: Corner/rbac/fulfillment_partner_cannot_capture_order
    """
    scenario = setup_basic_scenario(
        creator_email="rbb@example.com", display_name="RBB", slug="rbb-sf",
        sku="T-RBB", markup_bps=5000, file_hash="hash_rbb",
    )
    order = create_order_and_authorize(scenario, item_count=1)
    resp = api.capture_order(
        order["id"],
        make_fulfillment_partner_headers(scenario["partner"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_anonymous_role_cannot_create_storefront(api):
    """PRD §4 (endpoint table): "POST | `/pod/storefronts` | Create a
    storefront. | `Creator`"
    PRD §2.1: "A well-formed header pair whose role is not permitted to invoke
    the requested endpoint produces `ERR_FORBIDDEN` with HTTP 403."

    An Anonymous caller invoking POST /pod/storefronts (Creator-exclusive) gets
    ERR_FORBIDDEN.

    Design: Corner/rbac/anonymous_cannot_create_storefront
    """
    resp = api.create_storefront(
        storefront_payload(
            NON_EXISTENT_UUID, slug="ghost", integration_channel="NATIVE", markup_bps=1000,
        ),
        make_anonymous_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

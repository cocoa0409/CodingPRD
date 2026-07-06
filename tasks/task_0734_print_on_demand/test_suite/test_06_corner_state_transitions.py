"""Corner tests — invalid state transitions and channel state guards."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    get_success_data,
    make_platform_admin_headers,
    make_anonymous_headers,
    make_creator_headers,
    set_clock,
    create_verified_creator,
    create_creator,
    create_active_partner,
    create_product_and_variant,
    create_storefront,
    upload_and_approve_design,
    create_and_publish_listing,
    order_payload,
    design_payload,
    link_channel_payload,
    storefront_payload,
)


def test_approve_uploaded_design_before_mockup_returns_invalid_state(api):
    """PRD §2.9: "Priority 5 covers state-precondition checks: the generic
    `ERR_INVALID_STATE` for any transition whose entity state does not permit
    the operation".
    PRD §3.5: "Approval transitions `status` from `MOCKUP_READY` to `APPROVED`,
    making the design eligible to appear on published listings."

    A Design still at UPLOADED (no mockup) rejects approve — only MOCKUP_READY
    can be approved.

    Design: Corner/state_machines/design_approve_from_uploaded_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    creator = create_verified_creator(email="cs1@example.com", display_name="CS1")
    resp_up = api.upload_design(
        creator["id"], design_payload(file_hash="hash_cs1_uploaded"),
        make_creator_headers(creator["id"]),
    )
    design = get_success_data(resp_up)
    # Design status is UPLOADED here (no mockup generated).
    resp = api.approve_design(design["id"], make_platform_admin_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_capture_draft_order_before_authorize_returns_invalid_state(api):
    """PRD §2.9: "Priority 5 covers state-precondition checks: the generic
    `ERR_INVALID_STATE` for any transition whose entity state does not permit
    the operation".
    PRD §3.7: "Capturing the payment transitions `payment_status` from
    `AUTHORIZED` to `CAPTURED` and, if `fulfillment_status` is still `PENDING`,
    immediately fires the routing selector."

    An Order still at payment_status=DRAFT (never authorized) rejects capture.

    Design: Corner/state_machines/order_capture_from_draft_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    create_active_partner()
    product, variant = create_product_and_variant(sku="T-CS2")
    creator = create_verified_creator(email="cs2@example.com", display_name="CS2")
    storefront = create_storefront(creator["id"], slug="cs2-sf", markup_bps=5000)
    design = upload_and_approve_design(creator["id"], file_hash="hash_cs2")
    listing = create_and_publish_listing(
        storefront["id"], design["id"], variant["id"], creator["id"], title="CS2 Tee",
    )
    order = get_success_data(api.create_order(
        order_payload(storefront["id"], listing["id"], item_count=1),
        make_anonymous_headers(),
    ))
    # order.payment_status == DRAFT. Capture fires without authorize -> invalid state.
    resp = api.capture_order(order["id"], make_platform_admin_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_link_channel_when_already_linked_returns_already_linked(api):
    """PRD §3.3: "An attempt to link a storefront that is already at `LINKED` is
    rejected with `ERR_STOREFRONT_CHANNEL_ALREADY_LINKED` — the state check
    surfaces before the concurrency check, per the validation ordering."

    A Storefront whose integration_status is LINKED rejects a second link-channel
    call.

    Design: Corner/state_machines/storefront_link_channel_already_linked_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    creator = create_verified_creator(email="cs3@example.com", display_name="CS3")
    sf = get_success_data(api.create_storefront(
        storefront_payload(
            creator["id"], slug="cs3-sf", integration_channel="ETSY", markup_bps=5000,
        ),
        make_creator_headers(creator["id"]),
    ))
    v0 = sf["version"]
    linked = get_success_data(api.link_channel(
        sf["id"], link_channel_payload(expected_storefront_version=v0),
        make_creator_headers(creator["id"]),
    ))
    v1 = linked["version"]
    # Second link with correct version -> already-linked state failure.
    resp = api.link_channel(
        sf["id"], link_channel_payload(expected_storefront_version=v1),
        make_creator_headers(creator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STOREFRONT_CHANNEL_ALREADY_LINKED)

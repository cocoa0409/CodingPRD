"""Fixture builders: low-level endpoint wrappers plus the composite worlds the
test suite needs.

The harness restarts the API server before every individual test, so the
database is empty at the start of each test.  Every builder below therefore
constructs its state from scratch through the documented endpoints only.
"""
import pytest

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_BASE
from .factories import (
    create_attribute_definition_payload,
    create_attribute_value_payload,
    create_change_request_payload,
    create_content_version_payload,
    create_deployment_payload,
    create_media_asset_payload,
    create_observation_payload,
    create_product_payload,
    create_requirement_payload,
    create_retailer_listing_payload,
    create_retailer_payload,
    create_syndication_job_payload,
    deployment_decision_payload,
    media_decision_payload,
    resolve_rejection_error_payload,
    retailer_response_payload,
    review_payload,
    set_clock_payload,
    shelf_status_payload,
    withdraw_payload,
)
from .test_users import (
    AUTHOR_USER_ID,
    BRAND_USER_ID,
    LEGAL_USER_ID,
    OPERATOR_USER_ID,
    make_account_team_headers,
    make_brand_approver_headers,
    make_content_author_headers,
    make_legal_reviewer_headers,
    make_retailer_integration_headers,
    make_shelf_admin_headers,
    make_syndication_operator_headers,
)

# ---------------------------------------------------------------------------
# Tier 1 — single endpoint wrappers
# ---------------------------------------------------------------------------


def move_clock(to_iso8601=CLOCK_BASE):
    """Position the logical clock; the platform clock starts at 2026-08-01T00:00:00Z."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), make_shelf_admin_headers())
    )


def define_attribute(
    attribute_key,
    data_type="STRING",
    taxonomy_group="CORE",
    max_chars=200,
    base_weight=40.00,
    is_global_required=True,
):
    payload = create_attribute_definition_payload(
        attribute_key=attribute_key,
        data_type=data_type,
        taxonomy_group=taxonomy_group,
        max_chars=max_chars,
        base_weight=base_weight,
        is_global_required=is_global_required,
    )
    return get_success_data(
        api_client.create_attribute_definition(payload, make_shelf_admin_headers())
    )


def register_retailer(
    name,
    retailer_code,
    status="ACTIVE",
    min_image_count=1,
    feed_slot_capacity=10,
    max_concurrent_feed_windows=2,
    enhanced_content_requires_approval=True,
):
    payload = create_retailer_payload(
        name=name,
        retailer_code=retailer_code,
        status=status,
        min_image_count=min_image_count,
        feed_slot_capacity=feed_slot_capacity,
        max_concurrent_feed_windows=max_concurrent_feed_windows,
        enhanced_content_requires_approval=enhanced_content_requires_approval,
    )
    return get_success_data(api_client.create_retailer(payload, make_shelf_admin_headers()))


def require_attribute(
    retailer_id,
    attribute_key,
    requirement_level="REQUIRED",
    max_chars_override=None,
    weight_override=None,
):
    payload = create_requirement_payload(
        attribute_key=attribute_key, requirement_level=requirement_level
    )
    if max_chars_override is not None:
        payload["max_chars_override"] = max_chars_override
    if weight_override is not None:
        payload["weight_override"] = weight_override
    return get_success_data(
        api_client.create_retailer_requirement(retailer_id, payload, make_shelf_admin_headers())
    )


def register_product(sku, gtin, category_code="SMALL_APPLIANCE", brand_code="BRHM"):
    payload = create_product_payload(
        sku=sku, gtin=gtin, category_code=category_code, brand_code=brand_code
    )
    return get_success_data(api_client.create_product(payload, make_content_author_headers()))


def open_listing(product_id, retailer_id, account_team_user_id):
    payload = create_retailer_listing_payload(
        product_id, retailer_id, account_team_user_id=account_team_user_id
    )
    return get_success_data(
        api_client.create_retailer_listing(payload, make_content_author_headers())
    )


def upload_asset(product_id, asset_role, source_uri):
    payload = create_media_asset_payload(
        product_id, asset_role=asset_role, source_uri=source_uri
    )
    return get_success_data(api_client.create_media_asset(payload, make_content_author_headers()))


def decide_asset(media_asset_id, retailer_id, decision="APPROVE", **extra):
    return get_success_data(
        api_client.decide_media_asset(
            media_asset_id,
            media_decision_payload(decision, **extra),
            make_retailer_integration_headers(retailer_id),
        )
    )


def upload_approved_asset(product_id, asset_role, source_uri, retailer_id):
    asset = upload_asset(product_id, asset_role, source_uri)
    decide_asset(asset["id"], retailer_id)
    return asset


def start_revision(product_id, image_count, supersedes_content_version_id=None):
    payload = create_content_version_payload(product_id, image_count=image_count)
    if supersedes_content_version_id is not None:
        payload["supersedes_content_version_id"] = supersedes_content_version_id
    return get_success_data(
        api_client.create_content_version(payload, make_content_author_headers())
    )


def set_attribute_value(content_version_id, attribute_key, value):
    return get_success_data(
        api_client.create_attribute_value(
            content_version_id,
            create_attribute_value_payload(attribute_key, value),
            make_content_author_headers(),
        )
    )


def read_product_version(product_id):
    return get_success_data(api_client.get_product(product_id, make_shelf_admin_headers()))[
        "version"
    ]


def read_retailer_version(retailer_id):
    return get_success_data(
        api_client.get_retailer(retailer_id, make_syndication_operator_headers())
    )["version"]


def read_listing_version(retailer_listing_id):
    return get_success_data(
        api_client.get_retailer_listing(retailer_listing_id, make_content_author_headers())
    )["version"]


# ---------------------------------------------------------------------------
# Tier 2 — short lifecycle chains
# ---------------------------------------------------------------------------


def draft_change_request(
    product_id,
    retailer_id,
    target_content_version_id,
    rationale,
    author_user_id=AUTHOR_USER_ID,
):
    """Create the change request and stop there, leaving it DRAFT with both
    tracks PENDING and the target revision still DRAFT."""
    return get_success_data(
        api_client.create_change_request(
            create_change_request_payload(
                product_id, retailer_id, target_content_version_id, rationale=rationale
            ),
            make_content_author_headers(author_user_id),
        )
    )


def raise_change_request(
    product_id,
    retailer_id,
    target_content_version_id,
    rationale,
    author_user_id=AUTHOR_USER_ID,
):
    """Create the change request and submit it, leaving it IN_REVIEW with both
    tracks PENDING."""
    change_request = draft_change_request(
        product_id, retailer_id, target_content_version_id, rationale, author_user_id
    )
    get_success_data(
        api_client.submit_change_request(
            change_request["id"], {}, make_content_author_headers(author_user_id)
        )
    )
    return change_request


def review_legal(change_request_id, product_id, decision="APPROVED", user_id=LEGAL_USER_ID):
    expected = read_product_version(product_id)
    return get_success_data(
        api_client.create_review(
            change_request_id,
            review_payload("LEGAL", decision, expected),
            make_legal_reviewer_headers(user_id),
        )
    )


def review_brand(change_request_id, product_id, decision="APPROVED", user_id=BRAND_USER_ID):
    expected = read_product_version(product_id)
    return get_success_data(
        api_client.create_review(
            change_request_id,
            review_payload("BRAND", decision, expected),
            make_brand_approver_headers(user_id),
        )
    )


def pin_revision(
    product_id,
    retailer_id,
    target_content_version_id,
    rationale="pin this revision on the retailer",
    author_user_id=AUTHOR_USER_ID,
    legal_user_id=LEGAL_USER_ID,
    brand_user_id=BRAND_USER_ID,
):
    """Author raises and submits the change request, legal approves, then brand
    approves.  Each decision advances Product.version, so the version is re-read
    before each review.  Returns the change request as the join left it."""
    change_request = raise_change_request(
        product_id, retailer_id, target_content_version_id, rationale, author_user_id
    )
    review_legal(change_request["id"], product_id, "APPROVED", legal_user_id)
    return review_brand(change_request["id"], product_id, "APPROVED", brand_user_id)


def queue_job(
    retailer_listing_id,
    content_version_id,
    slot_count,
    window_start,
    window_end,
    retailer_id=None,
    expected_retailer_version=None,
    operator_user_id=OPERATOR_USER_ID,
):
    if expected_retailer_version is None:
        expected_retailer_version = read_retailer_version(retailer_id)
    payload = create_syndication_job_payload(
        retailer_listing_id,
        content_version_id,
        slot_count,
        window_start,
        window_end,
        expected_retailer_version,
    )
    return get_success_data(
        api_client.create_syndication_job(
            payload, make_syndication_operator_headers(operator_user_id)
        )
    )


def transmit_job(job_id, operator_user_id=OPERATOR_USER_ID):
    return get_success_data(
        api_client.transmit_syndication_job(
            job_id, {}, make_syndication_operator_headers(operator_user_id)
        )
    )


def respond_to_job(job_id, retailer_id, outcome, errors=None):
    return get_success_data(
        api_client.retailer_response(
            job_id,
            retailer_response_payload(outcome, errors),
            make_retailer_integration_headers(retailer_id),
        )
    )


def accept_job(job_id, retailer_id):
    return respond_to_job(job_id, retailer_id, "ACCEPTED")


def reject_job(job_id, retailer_id, errors):
    return respond_to_job(job_id, retailer_id, "REJECTED", errors)


def resolve_rejection(rejection_error_id, resolution_mode, resolution_note):
    return get_success_data(
        api_client.resolve_rejection_error(
            rejection_error_id,
            resolve_rejection_error_payload(resolution_mode, resolution_note),
            make_syndication_operator_headers(),
        )
    )


def rejection_errors_of(job_id):
    body = api_client.list_rejection_errors(job_id, make_syndication_operator_headers())
    return get_success_data(body)


def ingest_observation(
    retailer_listing_id,
    observed_at,
    in_stock=True,
    content_accuracy_pct=95.00,
    rating_avg=4.00,
    rating_count=50,
    unauthorized_seller_count=0,
    conversion_rate_pct=2.00,
    units_sold=10,
    search_rank=3,
):
    payload = create_observation_payload(
        observed_at=observed_at,
        in_stock=in_stock,
        content_accuracy_pct=content_accuracy_pct,
        rating_avg=rating_avg,
        rating_count=rating_count,
        unauthorized_seller_count=unauthorized_seller_count,
        conversion_rate_pct=conversion_rate_pct,
        units_sold=units_sold,
        search_rank=search_rank,
    )
    return get_success_data(
        api_client.create_observation(retailer_listing_id, payload, make_shelf_admin_headers())
    )


def set_shelf_status(retailer_listing_id, shelf_state, account_team_user_id):
    return get_success_data(
        api_client.set_shelf_status(
            retailer_listing_id,
            shelf_status_payload(shelf_state),
            make_account_team_headers(account_team_user_id),
        )
    )


def deploy_enhanced_module(
    retailer_listing_id,
    change_request_id,
    media_asset_id,
    module_kind,
    window_start,
    window_end,
    expected_retailer_listing_version=None,
    author_user_id=AUTHOR_USER_ID,
):
    if expected_retailer_listing_version is None:
        expected_retailer_listing_version = read_listing_version(retailer_listing_id)
    payload = create_deployment_payload(
        retailer_listing_id,
        change_request_id,
        media_asset_id,
        module_kind,
        window_start,
        window_end,
        expected_retailer_listing_version,
    )
    return get_success_data(
        api_client.create_enhanced_deployment(payload, make_content_author_headers(author_user_id))
    )


def decide_deployment(deployment_id, retailer_id, decision):
    return get_success_data(
        api_client.decide_enhanced_deployment(
            deployment_id,
            deployment_decision_payload(decision),
            make_retailer_integration_headers(retailer_id),
        )
    )


def withdraw_deployment(deployment_id, withdrawn_reason=None, author_user_id=AUTHOR_USER_ID):
    return get_success_data(
        api_client.withdraw_enhanced_deployment(
            deployment_id,
            withdraw_payload(withdrawn_reason),
            make_content_author_headers(author_user_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 3 — composite worlds
# ---------------------------------------------------------------------------

BIGBOX_TITLE = "Bright Kitchen Blender 900W"
BIGBOX_DESCRIPTION = "A 900 watt blender with six speeds and a glass jar."
MEGA_TITLE = "Compact 900W Kitchen Blender"
MEGA_DESCRIPTION = (
    "A compact 900 watt kitchen blender with six speeds, a pulse mode, "
    "a 1.5 litre glass jar and a two year limited warranty."
)


def define_title_description_brand():
    """The three-attribute taxonomy shared by the BigBox family of scenarios."""
    return {
        "title": define_attribute("title", "STRING", "CORE", 200, 40.00, True),
        "description": define_attribute("description", "STRING", "MARKETING", 500, 30.00, False),
        "brand": define_attribute("brand", "STRING", "CORE", 60, 10.00, True),
    }


def define_title_only():
    return {"title": define_attribute("title", "STRING", "CORE", 200, 40.00, True)}


def build_bigbox_world(
    min_image_count=4,
    feed_slot_capacity=10,
    max_concurrent_feed_windows=2,
    enhanced_content_requires_approval=True,
    clock=CLOCK_BASE,
):
    """BigBox: three REQUIRED rows (title 40, description 30, brand 10) so the
    completeness denominator is 80 + IMAGE_WEIGHT 20 == 100.  Revision 1 carries
    title and description but not brand, claims image_count 4 and is backed by
    exactly three APPROVED image assets against min_image_count 4 — certified
    85.00, declared 90.00, readiness 51.00."""
    move_clock(clock)
    attributes = define_title_description_brand()
    retailer = register_retailer(
        "BigBox",
        "RETB",
        min_image_count=min_image_count,
        feed_slot_capacity=feed_slot_capacity,
        max_concurrent_feed_windows=max_concurrent_feed_windows,
        enhanced_content_requires_approval=enhanced_content_requires_approval,
    )
    for key in ("title", "description", "brand"):
        require_attribute(retailer["id"], key, "REQUIRED")
    product = register_product("SKU-B-1", "00012345678929")
    listing = open_listing(product["id"], retailer["id"], "acct_bigbox_1")
    assets = [
        upload_approved_asset(product["id"], "HERO_IMAGE", "s3://brand/b/hero.jpg", retailer["id"]),
        upload_approved_asset(
            product["id"], "SECONDARY_IMAGE", "s3://brand/b/sec1.jpg", retailer["id"]
        ),
        upload_approved_asset(
            product["id"], "SECONDARY_IMAGE", "s3://brand/b/sec2.jpg", retailer["id"]
        ),
    ]
    revision = start_revision(product["id"], 4)
    set_attribute_value(revision["id"], "title", BIGBOX_TITLE)
    set_attribute_value(revision["id"], "description", BIGBOX_DESCRIPTION)
    change_request = pin_revision(
        product["id"], retailer["id"], revision["id"], "launch revision 1 on BigBox"
    )
    return {
        "attributes": attributes,
        "retailer": retailer,
        "product": product,
        "listing": listing,
        "assets": assets,
        "revision": revision,
        "change_request": change_request,
        "account_team_user_id": "acct_bigbox_1",
    }


def add_bigbox_second_revision(world, supersedes=None, with_brand=True):
    """A second revision of the BigBox product carrying title, description and
    optionally brand, claiming image_count 4."""
    revision = start_revision(world["product"]["id"], 4, supersedes)
    set_attribute_value(revision["id"], "title", BIGBOX_TITLE)
    set_attribute_value(revision["id"], "description", BIGBOX_DESCRIPTION)
    if with_brand:
        set_attribute_value(revision["id"], "brand", "BrightHome")
    return revision


def build_mega_world(clock=CLOCK_BASE):
    """MegaMart: five requirement rows with two per-retailer overrides, so the
    denominator is 70 + IMAGE_WEIGHT 20 == 90.  Revision 1 is pinned with a
    120-character description that breaks the 100-character override, and a
    superseding revision 2 stays DRAFT with every key present."""
    move_clock(clock)
    attributes = {
        "title": define_attribute("title", "STRING", "CORE", 200, 40.00, True),
        "description": define_attribute("description", "STRING", "MARKETING", 500, 30.00, False),
        "bullet_1": define_attribute("bullet_1", "STRING", "MARKETING", 400, 10.00, False),
        "brand": define_attribute("brand", "STRING", "CORE", 60, 10.00, True),
        "color": define_attribute("color", "STRING", "VARIANT", 40, 5.00, False),
    }
    retailer = register_retailer("MegaMart", "MEGA", min_image_count=3)
    require_attribute(retailer["id"], "title", "REQUIRED", max_chars_override=80, weight_override=30.00)
    require_attribute(
        retailer["id"], "description", "REQUIRED", max_chars_override=100, weight_override=20.00
    )
    require_attribute(retailer["id"], "bullet_1", "RECOMMENDED")
    require_attribute(retailer["id"], "brand", "REQUIRED")
    require_attribute(retailer["id"], "color", "OPTIONAL")
    product = register_product("SKU-A-1", "00012345678905")
    listing = open_listing(product["id"], retailer["id"], "acct_mega_1")
    assets = [
        upload_approved_asset(product["id"], "HERO_IMAGE", "s3://brand/a/hero.jpg", retailer["id"]),
        upload_approved_asset(
            product["id"], "SECONDARY_IMAGE", "s3://brand/a/sec1.jpg", retailer["id"]
        ),
        upload_approved_asset(
            product["id"], "SECONDARY_IMAGE", "s3://brand/a/sec2.jpg", retailer["id"]
        ),
    ]
    revision_1 = start_revision(product["id"], 3)
    set_attribute_value(revision_1["id"], "title", MEGA_TITLE)
    set_attribute_value(revision_1["id"], "description", MEGA_DESCRIPTION)
    set_attribute_value(revision_1["id"], "brand", "BrightHome")
    change_request = pin_revision(
        product["id"], retailer["id"], revision_1["id"], "launch revision 1 on MegaMart"
    )
    revision_2 = start_revision(product["id"], 2, revision_1["id"])
    set_attribute_value(revision_2["id"], "title", MEGA_TITLE + " 2026 Edition")
    set_attribute_value(revision_2["id"], "description", MEGA_DESCRIPTION)
    set_attribute_value(revision_2["id"], "bullet_1", "Six speeds plus pulse mode")
    set_attribute_value(revision_2["id"], "brand", "BrightHome")
    set_attribute_value(revision_2["id"], "color", "Black")
    return {
        "attributes": attributes,
        "retailer": retailer,
        "product": product,
        "listing": listing,
        "assets": assets,
        "revision_1": revision_1,
        "revision_2": revision_2,
        "change_request": change_request,
        "account_team_user_id": "acct_mega_1",
    }


def build_simplemart_world(
    enhanced_content_requires_approval=True,
    pin=True,
    submit=True,
    feed_slot_capacity=10,
    max_concurrent_feed_windows=2,
    clock=CLOCK_BASE,
):
    """SimpleMart: one REQUIRED row title (weight 40) so the denominator is
    40 + IMAGE_WEIGHT 20 == 60.  With the pin in place the single APPROVED
    HERO_IMAGE and the single title value give certified 100.00, declared 100.00
    and readiness 60.00."""
    move_clock(clock)
    attributes = define_title_only()
    retailer = register_retailer(
        "SimpleMart",
        "RETS",
        min_image_count=1,
        feed_slot_capacity=feed_slot_capacity,
        max_concurrent_feed_windows=max_concurrent_feed_windows,
        enhanced_content_requires_approval=enhanced_content_requires_approval,
    )
    require_attribute(retailer["id"], "title", "REQUIRED")
    product = register_product("SKU-D-1", "00012345678936")
    listing = open_listing(product["id"], retailer["id"], "acct_simplemart_1")
    asset = upload_approved_asset(
        product["id"], "HERO_IMAGE", "s3://brand/d/hero.jpg", retailer["id"]
    )
    revision = start_revision(product["id"], 1)
    set_attribute_value(revision["id"], "title", BIGBOX_TITLE)
    if pin:
        change_request = pin_revision(
            product["id"], retailer["id"], revision["id"], "pin revision 1 on SimpleMart"
        )
    elif submit:
        change_request = raise_change_request(
            product["id"], retailer["id"], revision["id"], "pin revision 1 on SimpleMart"
        )
    else:
        change_request = draft_change_request(
            product["id"], retailer["id"], revision["id"], "pin revision 1 on SimpleMart"
        )
    return {
        "attributes": attributes,
        "retailer": retailer,
        "product": product,
        "listing": listing,
        "asset": asset,
        "assets": [asset],
        "revision": revision,
        "change_request": change_request,
        "account_team_user_id": "acct_simplemart_1",
    }


def build_shop_world():
    """ShopRight: one REQUIRED title row, min_image_count 1 and no media asset at
    all.  Revision 1 is pinned while the clock stands at 2026-08-05T00:00:00Z, the
    clock is then moved to 2026-08-09T00:00:00Z and four observations straddle the
    pin instant."""
    move_clock("2026-08-05T00:00:00Z")
    attributes = define_title_only()
    retailer = register_retailer("ShopRight", "SHOP", min_image_count=1)
    require_attribute(retailer["id"], "title", "REQUIRED")
    product = register_product("SKU-F-1", "00012345678912")
    listing = open_listing(product["id"], retailer["id"], "acct_shop_1")
    revision = start_revision(product["id"], 1)
    set_attribute_value(revision["id"], "title", MEGA_TITLE)
    change_request = pin_revision(
        product["id"], retailer["id"], revision["id"], "launch revision 1 on ShopRight"
    )
    move_clock("2026-08-09T00:00:00Z")
    observations = [
        ingest_observation(
            listing["id"],
            "2026-08-03T00:00:00Z",
            content_accuracy_pct=82.00,
            rating_avg=4.10,
            rating_count=40,
            conversion_rate_pct=1.20,
            units_sold=30,
            search_rank=9,
        ),
        ingest_observation(
            listing["id"],
            "2026-08-04T00:00:00Z",
            content_accuracy_pct=91.00,
            rating_avg=4.20,
            rating_count=45,
            conversion_rate_pct=2.00,
            units_sold=44,
            search_rank=8,
        ),
        ingest_observation(
            listing["id"],
            "2026-08-07T00:00:00Z",
            content_accuracy_pct=92.00,
            rating_avg=4.30,
            rating_count=52,
            conversion_rate_pct=3.00,
            units_sold=61,
            search_rank=4,
        ),
        ingest_observation(
            listing["id"],
            "2026-08-08T00:00:00Z",
            content_accuracy_pct=86.00,
            rating_avg=4.35,
            rating_count=55,
            conversion_rate_pct=2.40,
            units_sold=50,
            search_rank=3,
        ),
    ]
    return {
        "attributes": attributes,
        "retailer": retailer,
        "product": product,
        "listing": listing,
        "revision": revision,
        "change_request": change_request,
        "observations": observations,
        "account_team_user_id": "acct_shop_1",
    }


def build_alpha_beta_world():
    """One product listed on two retailers with identical requirement sets: the
    AlphaMart listing ends LIVE after an ACCEPTED job and the BetaMart listing
    ends ERROR_HOLD after a REJECTED job, so both are in the health input set.
    One observation per listing produces subscores whose thousandths digits make
    the rounding order observable."""
    move_clock(CLOCK_BASE)
    attributes = define_title_description_brand()
    alpha = register_retailer("AlphaMart", "RETA", min_image_count=4)
    beta = register_retailer("BetaMart", "RETB", min_image_count=4)
    for retailer in (alpha, beta):
        for key in ("title", "description", "brand"):
            require_attribute(retailer["id"], key, "REQUIRED")
    product = register_product("SKU-C-1", "00012345678950")
    alpha_listing = open_listing(product["id"], alpha["id"], "acct_alpha_1")
    beta_listing = open_listing(product["id"], beta["id"], "acct_beta_1")
    assets = [
        upload_approved_asset(product["id"], "HERO_IMAGE", "s3://brand/c/hero.jpg", alpha["id"]),
        upload_approved_asset(
            product["id"], "SECONDARY_IMAGE", "s3://brand/c/sec1.jpg", alpha["id"]
        ),
        upload_approved_asset(
            product["id"], "SECONDARY_IMAGE", "s3://brand/c/sec2.jpg", alpha["id"]
        ),
    ]
    revision_1 = start_revision(product["id"], 4)
    set_attribute_value(revision_1["id"], "title", BIGBOX_TITLE)
    set_attribute_value(revision_1["id"], "description", BIGBOX_DESCRIPTION)
    alpha_change_request = pin_revision(
        product["id"], alpha["id"], revision_1["id"], "pin revision 1 on AlphaMart"
    )
    revision_2 = start_revision(product["id"], 4)
    set_attribute_value(revision_2["id"], "title", BIGBOX_TITLE)
    set_attribute_value(revision_2["id"], "description", BIGBOX_DESCRIPTION)
    beta_change_request = pin_revision(
        product["id"], beta["id"], revision_2["id"], "pin revision 2 on BetaMart"
    )
    alpha_job = queue_job(
        alpha_listing["id"],
        revision_1["id"],
        4,
        "2026-08-25T00:00:00Z",
        "2026-08-26T00:00:00Z",
        alpha["id"],
    )
    transmit_job(alpha_job["id"])
    accept_job(alpha_job["id"], alpha["id"])
    beta_job = queue_job(
        beta_listing["id"],
        revision_2["id"],
        4,
        "2026-08-25T00:00:00Z",
        "2026-08-26T00:00:00Z",
        beta["id"],
    )
    transmit_job(beta_job["id"])
    reject_job(
        beta_job["id"],
        beta["id"],
        [
            {
                "retailer_error_code": "BRAND_MISSING",
                "attribute_key": "brand",
                "severity": "BLOCKING",
                "message": "brand attribute is required by BetaMart",
            }
        ],
    )
    alpha_observation = ingest_observation(
        alpha_listing["id"],
        "2026-08-11T00:00:00Z",
        content_accuracy_pct=40.10,
        rating_avg=4.73,
        rating_count=310,
        conversion_rate_pct=2.00,
        units_sold=60,
        search_rank=11,
    )
    beta_observation = ingest_observation(
        beta_listing["id"],
        "2026-08-12T00:00:00Z",
        content_accuracy_pct=60.10,
        rating_avg=2.11,
        rating_count=45,
        conversion_rate_pct=3.00,
        units_sold=20,
        search_rank=6,
    )
    return {
        "attributes": attributes,
        "alpha": alpha,
        "beta": beta,
        "product": product,
        "alpha_listing": alpha_listing,
        "beta_listing": beta_listing,
        "assets": assets,
        "revision_1": revision_1,
        "revision_2": revision_2,
        "alpha_change_request": alpha_change_request,
        "beta_change_request": beta_change_request,
        "alpha_job": alpha_job,
        "beta_job": beta_job,
        "alpha_observation": alpha_observation,
        "beta_observation": beta_observation,
    }


def build_flag_pair_world():
    """Two retailers that differ only in enhanced_content_requires_approval, each
    with its own pinned revision of the same product at certified 100.00 and
    readiness 60.00."""
    move_clock(CLOCK_BASE)
    attributes = define_title_only()
    ask_first = register_retailer(
        "AskFirst", "RETA", min_image_count=1, enhanced_content_requires_approval=True
    )
    auto_live = register_retailer(
        "AutoLive", "RETB", min_image_count=1, enhanced_content_requires_approval=False
    )
    require_attribute(ask_first["id"], "title", "REQUIRED")
    require_attribute(auto_live["id"], "title", "REQUIRED")
    product = register_product("SKU-E-1", "00012345678967")
    ask_first_listing = open_listing(product["id"], ask_first["id"], "acct_askfirst_1")
    auto_live_listing = open_listing(product["id"], auto_live["id"], "acct_autolive_1")
    asset = upload_approved_asset(
        product["id"], "HERO_IMAGE", "s3://brand/e/hero.jpg", ask_first["id"]
    )
    revision_1 = start_revision(product["id"], 1)
    set_attribute_value(revision_1["id"], "title", BIGBOX_TITLE)
    ask_first_change_request = pin_revision(
        product["id"], ask_first["id"], revision_1["id"], "pin revision 1 on AskFirst"
    )
    revision_2 = start_revision(product["id"], 1)
    set_attribute_value(revision_2["id"], "title", BIGBOX_TITLE)
    auto_live_change_request = pin_revision(
        product["id"], auto_live["id"], revision_2["id"], "pin revision 2 on AutoLive"
    )
    return {
        "attributes": attributes,
        "ask_first": ask_first,
        "auto_live": auto_live,
        "product": product,
        "ask_first_listing": ask_first_listing,
        "auto_live_listing": auto_live_listing,
        "asset": asset,
        "revision_1": revision_1,
        "revision_2": revision_2,
        "ask_first_change_request": ask_first_change_request,
        "auto_live_change_request": auto_live_change_request,
    }


def build_taxonomy_only_world(description_max_chars=500):
    """The taxonomy plus a bare product with one DRAFT revision and no attribute
    values, for the attribute-write screens."""
    move_clock(CLOCK_BASE)
    attributes = {
        "title": define_attribute("title", "STRING", "CORE", 200, 40.00, True),
        "description": define_attribute(
            "description", "STRING", "MARKETING", description_max_chars, 30.00, False
        ),
    }
    product = register_product("SKU-P-1", "00012345678943")
    revision = start_revision(product["id"], 1)
    return {"attributes": attributes, "product": product, "revision": revision}


# ---------------------------------------------------------------------------
# Tier 4 / 5 — pytest fixtures over the composite worlds
# ---------------------------------------------------------------------------


@pytest.fixture
def clock_at_base():
    return move_clock(CLOCK_BASE)


@pytest.fixture
def mega_world():
    return build_mega_world()


@pytest.fixture
def shop_world():
    return build_shop_world()


@pytest.fixture
def bigbox_world():
    return build_bigbox_world()


@pytest.fixture
def bigbox_world_capacity_6():
    return build_bigbox_world(feed_slot_capacity=6)


@pytest.fixture
def bigbox_world_single_window():
    return build_bigbox_world(max_concurrent_feed_windows=1)


@pytest.fixture
def simplemart_world():
    return build_simplemart_world()


@pytest.fixture
def simplemart_world_unpinned():
    return build_simplemart_world(pin=False)


@pytest.fixture
def simplemart_world_draft_request():
    """The change request has been created but never submitted, so both it and
    its target revision are still DRAFT."""
    return build_simplemart_world(pin=False, submit=False)


@pytest.fixture
def simplemart_world_auto_live():
    return build_simplemart_world(enhanced_content_requires_approval=False)


@pytest.fixture
def alpha_beta_world():
    return build_alpha_beta_world()


@pytest.fixture
def flag_pair_world():
    return build_flag_pair_world()


@pytest.fixture
def taxonomy_only_world():
    return build_taxonomy_only_world()


@pytest.fixture
def tight_description_world():
    """The same bare product, but description carries a deliberately tight
    40-character ceiling."""
    return build_taxonomy_only_world(description_max_chars=40)

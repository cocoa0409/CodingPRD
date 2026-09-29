"""Envelope fields, declared defaults, system-owned fields, the not-found codes and
the graph edges that join the flat collections together."""
import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_attribute_definition,
    assert_change_request,
    assert_content_version,
    assert_media_asset,
    assert_retailer,
    assert_retailer_listing,
)
from test_helpers.factories import (
    create_change_request_payload,
    create_media_asset_payload,
    create_product_payload,
    create_retailer_listing_payload,
    create_retailer_payload,
    patch_retailer_payload,
)
from test_helpers.fixtures import (
    define_attribute,
    open_listing,
    register_product,
    register_retailer,
    require_attribute,
    set_attribute_value,
    start_revision,
    upload_asset,
    upload_approved_asset,
)
from test_helpers.test_users import (
    make_content_author_headers,
    make_shelf_admin_headers,
    make_syndication_operator_headers,
)

TITLE_VALUE = "Bright Kitchen Blender 900W"


def test_onboarding_a_retailer_echoes_every_envelope_field(clock_at_base):
    """A create that supplies the whole content requirements envelope stores exactly
    those values and mints the two platform-owned figures itself: no slots reserved
    and version 1.

    PRD 3.1: "A freshly onboarded retailer has `feed_slots_reserved` initialised to 0 and `version` initialised to 1, and the reserved figure is thereafter always between 0 and `feed_slot_capacity` inclusive."
    Design: Corner/entities/retailer_create_returns_201_with_every_declared_envelope_field
    """
    data = validate_success(
        api_client.create_retailer(
            create_retailer_payload(
                name="MegaMart",
                retailer_code="RETM",
                status="PAUSED",
                min_image_count=6,
                feed_slot_capacity=30,
                max_concurrent_feed_windows=4,
                enhanced_content_requires_approval=False,
            ),
            make_shelf_admin_headers(),
        ),
        201,
    )
    assert_retailer(data)
    assert data["name"] == "MegaMart"
    assert data["retailer_code"] == "RETM"
    assert data["status"] == "PAUSED"
    assert data["min_image_count"] == 6
    assert data["feed_slot_capacity"] == 30
    assert data["max_concurrent_feed_windows"] == 4
    assert data["enhanced_content_requires_approval"] is False
    assert data["feed_slots_reserved"] == 0
    assert data["version"] == 1


def test_omitting_the_envelope_applies_every_declared_default(clock_at_base):
    """Only the name and the code are mandatory; the five envelope fields left out of
    the payload come back at their declared defaults rather than as nulls.

    PRD 3.1: "The rest of the payload is the retailer's **content requirements envelope**, and each part of it is optional at onboarding because each has a default."
    Design: Corner/entities/retailer_create_omitting_the_optional_envelope_applies_declared_defaults
    """
    data = validate_success(
        api_client.create_retailer(
            {"name": "PlainMart", "retailer_code": "RETP"}, make_shelf_admin_headers()
        ),
        201,
    )
    assert data["status"] == "ACTIVE"
    assert data["min_image_count"] == 1
    assert data["feed_slot_capacity"] == 10
    assert data["max_concurrent_feed_windows"] == 2
    assert data["enhanced_content_requires_approval"] is True
    assert data["feed_slots_reserved"] == 0


def test_reading_a_retailer_back_reports_its_live_reserved_slot_figure(clock_at_base):
    """The single-retailer read hands back the stored envelope together with a
    reserved figure computed now: no listing exists, so no job can be holding slots
    and the figure is 0.

    PRD 3.1: "Retailers can be listed with an optional `status` filter alongside the usual page controls, and a single retailer read always reflects its live reserved-slot figure rather than a cached one."
    Design: Corner/entities/get_retailer_by_id_returns_the_stored_envelope_and_live_reserved_count
    """
    retailer = register_retailer("SimpleMart", "RETS", min_image_count=1, feed_slot_capacity=10)

    data = validate_success(
        api_client.get_retailer(retailer["id"], make_syndication_operator_headers())
    )
    assert data["retailer_code"] == "RETS"
    assert data["min_image_count"] == 1
    assert data["feed_slots_reserved"] == 0
    assert data["version"] == 1


def test_the_retailer_list_pages_and_filters_on_status(clock_at_base):
    """Three retailers read two at a time report the full match count on both pages
    and only flag more rows on the first, and the status filter narrows the count
    before pagination is applied.

    PRD 2.3: "The `meta` object of every list response carries `limit` (the effective page size applied), `offset` (the effective starting position applied), `total_count` (the number of rows matching the filters before pagination), and `has_more` (true when rows remain beyond the current page)."
    Design: Corner/entities/retailers_list_paginates_with_total_count_and_has_more
    """
    register_retailer("Alpha", "RETA")
    register_retailer("Beta", "RETB")
    register_retailer("Gamma", "RETC", status="PAUSED")

    first, meta_first = validate_paginated(
        api_client.list_retailers(make_shelf_admin_headers(), params={"limit": 2, "offset": 0})
    )
    assert meta_first["total_count"] == 3
    assert meta_first["has_more"] is True
    assert len(first) == 2

    second, meta_second = validate_paginated(
        api_client.list_retailers(make_shelf_admin_headers(), params={"limit": 2, "offset": 2})
    )
    assert meta_second["total_count"] == 3
    assert meta_second["has_more"] is False
    assert len(second) == 1

    paused, meta_paused = validate_paginated(
        api_client.list_retailers(make_shelf_admin_headers(), params={"status": "PAUSED"})
    )
    assert meta_paused["total_count"] == 1
    assert len(paused) == 1
    assert paused[0]["retailer_code"] == "RETC"


def test_reading_an_unknown_retailer_id_is_a_retailer_not_found(clock_at_base):
    """A well-formed identifier that matches no row is a 404 carrying the retailer
    family's own code, not an empty success.

    PRD 2.8: "The referenced retailer exists — otherwise `ERR_RETAILER_NOT_FOUND`."
    Design: Corner/entities/get_retailer_with_unknown_id_returns_retailer_not_found
    """
    response = api_client.get_retailer(NON_EXISTENT_UUID, make_shelf_admin_headers())
    validate_error(response, ApiErrorId.ERR_RETAILER_NOT_FOUND.value, 404)


def test_registering_a_product_without_a_gtin_is_an_invalid_request(clock_at_base):
    """The trade item number has no default, so a payload that omits it is refused on
    request shape and no product row survives the attempt.

    PRD 2.8: "Request-body shape: every required field present, types matching their declarations, every enum value a member of its declared set, and no decimal negative where the field forbids it — otherwise `ERR_INVALID_REQUEST`."
    Design: Corner/entities/product_create_without_gtin_returns_invalid_request
    """
    payload = create_product_payload(sku="SKU-E-1")
    payload.pop("gtin")

    response = api_client.create_product(payload, make_content_author_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    _rows, meta = validate_paginated(api_client.list_products(make_content_author_headers()))
    assert meta["total_count"] == 0


def test_a_status_outside_the_declared_enum_is_an_invalid_request(clock_at_base):
    """SUSPENDED is a shelf-state value, not a retailer status, so it is refused on
    request shape rather than stored verbatim.

    PRD 3.1: "`status` defaults to `ACTIVE` and is one of `ACTIVE`, `PAUSED` or `OFFBOARDED`."
    Design: Corner/entities/retailer_create_with_unknown_status_enum_returns_invalid_request
    """
    response = api_client.create_retailer(
        create_retailer_payload(name="BadEnum", retailer_code="RETX", status="SUSPENDED"),
        make_shelf_admin_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_the_second_revision_numbers_itself_and_ignores_a_supplied_number(clock_at_base):
    """Revision numbering is the platform's job: the second revision of the product
    is numbered 2 from the existing count, and the client's own revision_no of 99 is
    dropped without complaint.

    PRD 3.2: "The platform stamps `revision_no` as one more than the number of revisions the product already has at creation time — so numbering starts at 1 and is unique within a product, which means "the latest revision" is never ambiguous — sets `state` to `DRAFT`, records `author_user_id` from the calling `X-User-ID`, and leaves `pin_count` at 0."
    Design: Corner/entities/content_version_revision_no_counts_existing_revisions_extra_field_ignored
    """
    product = register_product("SKU-E-2", "00012345678943")
    first = start_revision(product["id"], 2)

    second = validate_success(
        api_client.create_content_version(
            {
                "product_id": product["id"],
                "supersedes_content_version_id": first["id"],
                "image_count": 3,
                "revision_no": 99,
            },
            make_content_author_headers(),
        ),
        201,
    )
    assert_content_version(second)
    assert second["revision_no"] == 2
    assert second["state"] == "DRAFT"
    assert second["pin_count"] == 0
    assert second["supersedes_content_version_id"] == first["id"]
    assert first["revision_no"] == 1


def test_media_asset_approval_fields_are_system_owned_and_ignored_on_create(clock_at_base):
    """An author who tries to hand themselves a retailer's blessing is quietly
    ignored: the row is created PENDING with no approving retailer and no decision
    stamp.

    PRD 3.3: "A newly registered asset has `approval_state` `PENDING`, `approving_retailer_id` null and `decided_at` null."
    Design: Corner/entities/media_asset_system_fields_ignored_input_on_create
    """
    retailer = register_retailer("SimpleMart", "RETS")
    product = register_product("SKU-E-3", "00012345678950")

    payload = create_media_asset_payload(
        product["id"],
        asset_role="HERO_IMAGE",
        source_uri="s3://brand/e/hero.jpg",
        approval_state="APPROVED",
        approving_retailer_id=retailer["id"],
    )
    data = validate_success(
        api_client.create_media_asset(payload, make_content_author_headers()), 201
    )
    assert_media_asset(data)
    assert data["approval_state"] == "PENDING"
    assert data["approving_retailer_id"] is None
    assert data["decided_at"] is None
    assert data["version"] == 1


def test_a_patch_naming_the_retailer_code_edits_only_the_declared_envelope_field(clock_at_base):
    """The envelope adjustment accepts a fixed subset of fields, so the image minimum
    moves to 3 while the code and the name the retailer was onboarded with stay
    exactly as they were.

    PRD 3.1: "The adjustment accepts `expected_retailer_version` plus any subset of `status`, `min_image_count`, `feed_slot_capacity`, `max_concurrent_feed_windows` and `enhanced_content_requires_approval`."
    Design: Corner/entities/retailer_code_immutable_under_patch_extra_field_ignored
    """
    retailer = register_retailer("SimpleMart", "RETS", min_image_count=1)

    patched = validate_success(
        api_client.patch_retailer(
            retailer["id"],
            patch_retailer_payload(
                retailer["version"], min_image_count=3, retailer_code="RETZ", name="RenamedMart"
            ),
            make_shelf_admin_headers(),
        )
    )
    assert patched["retailer_code"] == "RETS"
    assert patched["name"] == "SimpleMart"
    assert patched["min_image_count"] == 3
    assert patched["version"] == 2


def test_opening_a_listing_against_an_unknown_product_is_a_product_not_found(clock_at_base):
    """The body references are resolved before anything is written, and the product
    reference is resolved after the retailer one, so a valid retailer paired with a
    missing product reports the product's own 404 and stores nothing.

    PRD 2.8: "The referenced product exists — otherwise `ERR_PRODUCT_NOT_FOUND`."
    Design: Corner/entities/retailer_listing_create_with_unknown_product_returns_product_not_found
    """
    retailer = register_retailer("SimpleMart", "RETS")

    response = api_client.create_retailer_listing(
        create_retailer_listing_payload(NON_EXISTENT_UUID, retailer["id"]),
        make_content_author_headers(),
    )
    validate_error(response, ApiErrorId.ERR_PRODUCT_NOT_FOUND.value, 404)

    _rows, meta = validate_paginated(
        api_client.list_retailer_listings(make_content_author_headers())
    )
    assert meta["total_count"] == 0


def test_one_product_on_two_retailers_scores_each_edge_independently(clock_at_base):
    """The identical revision is scored twice because completeness belongs to the
    product-and-retailer junction, not to the product: a single claimed image is the
    whole image component against a minimum of 1 and only a third of it against a
    minimum of 3.

    PRD 3.4: "Given a count, the image component is the full image weight of 20 when the retailer's `min_image_count` is zero; otherwise it is 20 multiplied by the smaller of 1 and the ratio of the count to `min_image_count`."
    Design: Corner/entities/same_product_on_two_retailers_scores_each_listing_independently
    """
    define_attribute("title", "STRING", "CORE", 200, 40.00, True)
    lenient = register_retailer("SimpleMart", "RETS", min_image_count=1)
    demanding = register_retailer("MaxMart", "RETX", min_image_count=3)
    require_attribute(lenient["id"], "title", "REQUIRED")
    require_attribute(demanding["id"], "title", "REQUIRED")
    product = register_product("SKU-G-1", "00012345678967")
    revision = start_revision(product["id"], 1)
    set_attribute_value(revision["id"], "title", TITLE_VALUE)
    lenient_listing = open_listing(product["id"], lenient["id"], "acct_simplemart_1")
    demanding_listing = open_listing(product["id"], demanding["id"], "acct_maxmart_1")

    lenient_view = validate_success(
        api_client.get_listing_completeness(lenient_listing["id"], make_content_author_headers())
    )
    assert float(lenient_view["declared_score"]) == pytest.approx(100.00, abs=0.01)
    assert float(lenient_view["certified_score"]) == pytest.approx(0.00, abs=0.01)

    demanding_view = validate_success(
        api_client.get_listing_completeness(demanding_listing["id"], make_content_author_headers())
    )
    assert float(demanding_view["declared_score"]) == pytest.approx(77.78, abs=0.01)
    assert float(demanding_view["declared_image_component"]) == pytest.approx(6.67, abs=0.01)

    _rows, meta = validate_paginated(
        api_client.list_retailer_listings(
            make_content_author_headers(), params={"product_id": product["id"]}
        )
    )
    assert meta["total_count"] == 2

    stored_lenient = get_success_data(
        api_client.get_retailer_listing(lenient_listing["id"], make_content_author_headers())
    )
    stored_demanding = get_success_data(
        api_client.get_retailer_listing(demanding_listing["id"], make_content_author_headers())
    )
    assert float(stored_lenient["completeness_score_declared"]) == pytest.approx(100.00, abs=0.01)
    assert float(stored_demanding["completeness_score_declared"]) == pytest.approx(77.78, abs=0.01)


def test_the_supersedes_pointer_is_reverse_reachable_through_the_revision_list(clock_at_base):
    """Filtering revisions by the predecessor they replace walks the chain forward:
    revision 1 hands back revision 2, and revision 2 hands back nothing because
    nothing has been drafted to replace it yet.

    PRD 3.2: "Revisions can be listed filtered by `product_id`, by `supersedes_content_version_id` to walk the chain forward, or by `state`."
    Design: Corner/entities/content_versions_list_filters_by_supersedes_pointer_for_reverse_reachability
    """
    product = register_product("SKU-G-2", "00012345678974")
    first = start_revision(product["id"], 1)
    second = start_revision(product["id"], 2, first["id"])

    forward, meta_forward = validate_paginated(
        api_client.list_content_versions(
            make_content_author_headers(),
            params={"supersedes_content_version_id": first["id"]},
        )
    )
    assert meta_forward["total_count"] == 1
    assert forward[0]["id"] == second["id"]

    _tail, meta_tail = validate_paginated(
        api_client.list_content_versions(
            make_content_author_headers(),
            params={"supersedes_content_version_id": second["id"]},
        )
    )
    assert meta_tail["total_count"] == 0

    _drafts, meta_drafts = validate_paginated(
        api_client.list_content_versions(
            make_content_author_headers(),
            params={"product_id": product["id"], "state": "DRAFT"},
        )
    )
    assert meta_drafts["total_count"] == 2


def test_the_asset_list_separates_the_approved_row_from_the_pending_one(clock_at_base):
    """Two assets on one product, one blessed by the retailer and one still waiting,
    are told apart by the approval filter and by the approving-retailer filter, while
    the unfiltered read returns both.

    PRD 3.3: "Assets can be listed filtered by `product_id`, by `approval_state`, or by `approving_retailer_id`."
    Design: Corner/entities/media_assets_list_filters_by_product_and_approval_state
    """
    retailer = register_retailer("SimpleMart", "RETS")
    product = register_product("SKU-G-3", "00012345678981")
    open_listing(product["id"], retailer["id"], "acct_simplemart_1")
    approved = upload_approved_asset(
        product["id"], "HERO_IMAGE", "s3://brand/g/hero.jpg", retailer["id"]
    )
    pending = upload_asset(product["id"], "SECONDARY_IMAGE", "s3://brand/g/sec1.jpg")

    _both, meta_both = validate_paginated(
        api_client.list_media_assets(
            make_content_author_headers(), params={"product_id": product["id"]}
        )
    )
    assert meta_both["total_count"] == 2

    rows, meta_approved = validate_paginated(
        api_client.list_media_assets(
            make_content_author_headers(),
            params={"product_id": product["id"], "approval_state": "APPROVED"},
        )
    )
    assert meta_approved["total_count"] == 1
    assert rows[0]["id"] == approved["id"]

    _by_retailer, meta_by_retailer = validate_paginated(
        api_client.list_media_assets(
            make_content_author_headers(), params={"approving_retailer_id": retailer["id"]}
        )
    )
    assert meta_by_retailer["total_count"] == 1

    stored_pending = get_success_data(
        api_client.get_media_asset(pending["id"], make_content_author_headers())
    )
    assert stored_pending["approval_state"] == "PENDING"


def test_reading_an_unknown_job_id_is_a_syndication_job_not_found(clock_at_base):
    """Every entity family owns its own 404, so an unknown transmission identifier
    reports the job code rather than a listing or product code.

    PRD 2.8: "The referenced syndication job exists — otherwise `ERR_SYNDICATION_JOB_NOT_FOUND`."
    Design: Corner/entities/get_syndication_job_with_unknown_id_returns_job_not_found
    """
    response = api_client.get_syndication_job(
        NON_EXISTENT_UUID, make_syndication_operator_headers()
    )
    validate_error(response, ApiErrorId.ERR_SYNDICATION_JOB_NOT_FOUND.value, 404)


def test_the_taxonomy_stores_each_definition_and_filters_by_group(clock_at_base):
    """The vocabulary is a flat keyed registry: two keys in different groups keep
    their own weights and ceilings, the omitted house-standard flag falls back to
    false, and the group filter returns just the CORE key.

    PRD 3.1: "An optional `is_global_required` flag defaults to false and marks house-standard attributes for documentation purposes only — on its own it has no effect on any score."
    Design: Corner/entities/attribute_definition_create_then_list_filtered_by_taxonomy_group
    """
    core = validate_success(
        api_client.create_attribute_definition(
            {
                "attribute_key": "title",
                "data_type": "STRING",
                "taxonomy_group": "CORE",
                "max_chars": 200,
                "base_weight": 40.00,
                "is_global_required": True,
            },
            make_shelf_admin_headers(),
        ),
        201,
    )
    marketing = validate_success(
        api_client.create_attribute_definition(
            {
                "attribute_key": "description",
                "data_type": "STRING",
                "taxonomy_group": "MARKETING",
                "max_chars": 500,
                "base_weight": 30.00,
            },
            make_shelf_admin_headers(),
        ),
        201,
    )
    assert_attribute_definition(core)
    assert float(core["base_weight"]) == pytest.approx(40.00, abs=0.01)
    assert core["is_global_required"] is True
    assert marketing["max_chars"] == 500
    assert marketing["is_global_required"] is False

    rows, meta = validate_paginated(
        api_client.list_attribute_definitions(
            make_content_author_headers(), params={"taxonomy_group": "CORE"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["attribute_key"] == "title"


def test_change_requests_filter_by_the_revision_they_target(clock_at_base):
    """Two requests on one product but different target revisions are separated by
    the target filter, and each is still a DRAFT with both review dimensions
    untouched and the raising author recorded.

    PRD 3.5: "A newly raised request sits in `state` `DRAFT` with `legal_review_state` and `brand_review_state` both `PENDING`, `legal_reviewer_user_id` and `brand_reviewer_user_id` both null, `submitted_at` and `decided_at` both null, and `author_user_id` recorded from the calling `X-User-ID` — the value that will later bar this user from deciding either of its two tracks."
    Design: Corner/entities/change_requests_list_filters_by_target_content_version_id
    """
    retailer = register_retailer("SimpleMart", "RETS")
    product = register_product("SKU-G-4", "00012345678998")
    open_listing(product["id"], retailer["id"], "acct_simplemart_1")
    first = start_revision(product["id"], 1)
    second = start_revision(product["id"], 2, first["id"])

    first_request = validate_success(
        api_client.create_change_request(
            create_change_request_payload(
                product["id"], retailer["id"], first["id"], rationale="pin revision 1"
            ),
            make_content_author_headers("author_1"),
        ),
        201,
    )
    second_request = validate_success(
        api_client.create_change_request(
            create_change_request_payload(
                product["id"], retailer["id"], second["id"], rationale="pin revision 2"
            ),
            make_content_author_headers("author_1"),
        ),
        201,
    )
    assert_change_request(first_request)

    hits, meta = validate_paginated(
        api_client.list_change_requests(
            make_content_author_headers(),
            params={"target_content_version_id": second["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert hits[0]["id"] == second_request["id"]
    assert hits[0]["state"] == "DRAFT"

    _drafts, meta_drafts = validate_paginated(
        api_client.list_change_requests(
            make_content_author_headers(),
            params={"product_id": product["id"], "state": "DRAFT"},
        )
    )
    assert meta_drafts["total_count"] == 2

    assert first_request["legal_review_state"] == "PENDING"
    assert first_request["brand_review_state"] == "PENDING"
    assert first_request["submitted_at"] is None
    assert second_request["author_user_id"] == "author_1"


def test_a_brand_new_listing_starts_at_zero_on_both_completeness_variants(clock_at_base):
    """The retailer demands a title, but the product has no revision at all, so the
    declared variant has no source to read and the certified variant has nothing
    pinned: both are 0.00 and every required key is reported missing.

    PRD 3.4: "When nothing is pinned, `missing_required_keys` contains every `REQUIRED` key of the retailer and `over_limit_keys` is empty."
    Design: Corner/entities/retailer_listing_create_starts_with_both_score_variants_at_zero
    """
    define_attribute("title", "STRING", "CORE", 200, 40.00, True)
    retailer = register_retailer("SimpleMart", "RETS", min_image_count=1)
    require_attribute(retailer["id"], "title", "REQUIRED")
    product = register_product("SKU-G-5", "00012345679001")

    listing = validate_success(
        api_client.create_retailer_listing(
            create_retailer_listing_payload(
                product["id"], retailer["id"], account_team_user_id="acct_simplemart_1"
            ),
            make_content_author_headers(),
        ),
        201,
    )
    assert_retailer_listing(listing)
    assert float(listing["completeness_score_declared"]) == pytest.approx(0.00, abs=0.01)
    assert float(listing["completeness_score_certified"]) == pytest.approx(0.00, abs=0.01)
    assert float(listing["readiness_score"]) == pytest.approx(0.00, abs=0.01)
    assert listing["syndication_state"] == "NOT_SYNDICATED"
    assert listing["shelf_state"] == "OK"
    assert listing["pinned_content_version_id"] is None
    assert listing["open_blocking_error_count"] == 0

    view = validate_success(
        api_client.get_listing_completeness(listing["id"], make_content_author_headers())
    )
    assert float(view["declared_score"]) == pytest.approx(0.00, abs=0.01)
    assert float(view["certified_score"]) == pytest.approx(0.00, abs=0.01)
    assert view["declared_source_content_version_id"] is None
    assert view["missing_required_keys"] == ["title"]
    assert view["over_limit_keys"] == []

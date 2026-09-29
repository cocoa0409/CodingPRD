"""Resource shapes: declared configuration, defaults, derived fields, the
append-only image record, and body foreign-key resolution."""

from test_helpers import (
    CALL_MANAGER,
    JURY_CHAIR_A,
    NON_EXISTENT_UUID,
    REGISTRAR,
    ApiErrorId,
    assert_zeroed_ledger,
    create_artist_payload,
    create_artwork_image_payload,
    create_artwork_payload,
    create_award_payload,
    create_entry_payload,
    create_exhibition_payload,
    create_wall_segment_payload,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_artist_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_created_exhibition_echoes_its_configuration_with_a_zeroed_ledger(api):
    """PRD §3.1: "A new exhibition begins with `status` at `DRAFT` and
    `settlement_status` at `NOT_STARTED`, every computed count and money aggregate
    at zero, and `version` at 1."

    Design: Corner/entities/exhibition_creation_returns_declared_config_and_zeroed_ledger
    """
    fixtures.set_clock(fixtures.CLOCK_CALL_OPEN)

    created = validate_success(
        api.create_exhibition(create_exhibition_payload(), CALL_MANAGER), 201
    )

    assert created["status"] == "DRAFT"
    assert created["settlement_status"] == "NOT_STARTED"
    assert created["version"] == 1
    assert is_valid_uuid(created["id"])
    assert is_iso8601_timestamp(created["created_at"])
    assert is_iso8601_timestamp(created["updated_at"])

    assert created["title"] == "Regional Juried Biennial"
    assert created["season_year"] == 2026
    assert created["acceptance_capacity"] == 3
    assert created["waitlist_capacity"] == 1
    assert created["commission_pct"] == 0.35
    assert created["sales_tax_pct"] == 0.0875

    assert_zeroed_ledger(created)


def test_reading_an_exhibition_returns_the_stored_configuration(api):
    """PRD §3.1: "The three criterion weights `score_weight_technique`,
    `score_weight_originality` and `score_weight_relevance` must sum to exactly
    1.00."

    Design: Corner/entities/exhibition_retrieval_returns_stored_configuration
    """
    fixtures.set_clock(fixtures.CLOCK_CALL_OPEN)
    created = fixtures.create_exhibition()

    read_back = validate_success(api.get_exhibition(created["id"], REGISTRAR))

    assert read_back["id"] == created["id"]
    assert read_back["score_weight_technique"] == 0.4
    assert read_back["score_weight_originality"] == 0.35
    assert read_back["score_weight_relevance"] == 0.25
    assert (
        read_back["score_weight_technique"]
        + read_back["score_weight_originality"]
        + read_back["score_weight_relevance"]
    ) == 1.00
    assert read_back["allowed_media_categories"] == [
        "PAINTING", "PHOTOGRAPHY", "SCULPTURE"
    ]
    assert read_back["eligible_state_codes"] == ["CA", "OR"]
    assert read_back["created_at"] == created["created_at"]
    assert read_back["version"] == 1, "a read does not bump the version"


def test_exhibition_listing_reports_the_whole_filtered_set_in_its_meta(api):
    """PRD §2.3: "Unless a specific endpoint states otherwise, list results are
    ordered by `created_at` ascending. The `meta` object of every list response
    carries `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/exhibitions_listing_paginates_with_total_count_and_has_more
    """
    fixtures.set_clock(fixtures.CLOCK_CALL_OPEN)
    first = fixtures.create_exhibition(title="Biennial 2024", season_year=2024)
    second = fixtures.create_exhibition(title="Biennial 2025", season_year=2025)
    third = fixtures.create_exhibition(title="Biennial 2026", season_year=2026)

    page_one, meta_one = validate_paginated(
        api.list_exhibitions(CALL_MANAGER, params={"limit": 2, "offset": 0})
    )
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert len(page_one) == 2
    assert page_one[0]["id"] == first["id"]

    page_two, meta_two = validate_paginated(
        api.list_exhibitions(CALL_MANAGER, params={"limit": 2, "offset": 2})
    )
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert len(page_two) == 1
    assert page_two[0]["id"] == third["id"]

    filtered, meta_filtered = validate_paginated(
        api.list_exhibitions(CALL_MANAGER, params={"season_year": 2025})
    )
    assert meta_filtered["total_count"] == 1
    assert meta_filtered["has_more"] is False
    assert filtered[0]["id"] == second["id"]


def test_unknown_exhibition_id_returns_the_entity_scoped_not_found(api):
    """PRD §2.5: "Each entity type has its own not-found code:
    `ERR_EXHIBITION_NOT_FOUND`, `ERR_ARTIST_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`,
    `ERR_ARTWORK_NOT_FOUND`, `ERR_JUROR_NOT_FOUND`, `ERR_JURY_ROUND_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_WALL_SEGMENT_NOT_FOUND`,
    `ERR_SPONSOR_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, and
    `ERR_SCORE_NOT_FOUND`, each returning HTTP 404."

    Design: Corner/entities/exhibition_get_with_unknown_id_returns_not_found
    """
    fixtures.set_clock(fixtures.CLOCK_CALL_OPEN)

    response = api.get_exhibition(NON_EXISTENT_UUID, CALL_MANAGER)
    validate_error(response, ApiErrorId.ERR_EXHIBITION_NOT_FOUND.value, 404)


def test_artist_creation_without_an_email_is_a_body_schema_violation(api):
    """PRD §3.2: "The council's roster is maintained by the `CallManager`, who
    registers each **Artist** with a `legal_name` used on payment remittances, a
    unique `email`, and a two-letter `residency_state_code`."

    Design: Corner/entities/artist_creation_without_email_returns_invalid_request
    """
    fixtures.set_clock(fixtures.CLOCK_CALL_OPEN)

    payload = create_artist_payload()
    payload.pop("email")
    response = api.create_artist(payload, CALL_MANAGER)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_omitted_optional_fields_take_their_declared_defaults(api):
    """PRD §3.1: "`claim_deadline_days` — 30 unless overridden — sets how long
    after closing an artist has to collect unsold work."

    Design: Corner/entities/optional_input_fields_omitted_apply_declared_defaults
    """
    fixtures.set_clock(fixtures.CLOCK_CALL_OPEN)

    exhibition_payload = create_exhibition_payload(title="Defaults Probe")
    for key in ("claim_deadline_days", "works_included_in_base",
                "member_discount_pct", "max_works_per_entry",
                "max_entries_per_artist"):
        exhibition_payload.pop(key)
    exhibition = validate_success(
        api.create_exhibition(exhibition_payload, CALL_MANAGER), 201
    )
    assert exhibition["claim_deadline_days"] == 30
    assert exhibition["works_included_in_base"] == 2
    assert exhibition["member_discount_pct"] == 0.175
    assert exhibition["max_works_per_entry"] == 5
    assert exhibition["max_entries_per_artist"] == 1

    artist_payload = create_artist_payload(
        legal_name="Bo Nakamura", email="bo@example.org"
    )
    for key in ("member_status", "tax_form_on_file", "payout_method"):
        artist_payload.pop(key)
    artist = validate_success(api.create_artist(artist_payload, CALL_MANAGER), 201)
    assert artist["member_status"] == "NON_MEMBER"
    assert artist["tax_form_on_file"] is False
    assert artist["payout_method"] == "CHECK"
    assert artist["payout_hold"] is False
    assert artist["unclaimed_forfeit_count"] == 0

    wall_payload = create_wall_segment_payload(exhibition["id"])
    wall_payload.pop("lighting_class")
    wall = validate_success(
        api.create_wall_segment(wall_payload, REGISTRAR), 201
    )
    assert wall["lighting_class"] == "STANDARD"
    assert wall["occupied_cm"] == 0.0
    assert wall["available_cm"] == 600.0
    assert wall["loaded_weight_kg"] == 0.0


def test_attaching_a_work_derives_its_longest_edge_and_blind_label(api):
    """PRD §3.2: "It is also assigned a `blind_label`, the anonymous identifier by
    which jurors will know it: the exhibition's `season_year`, a hyphen, and the
    one-based ordinal of this work among all of the exhibition's artworks ordered
    by `created_at` ascending, zero-padded to four digits."

    Design: Corner/entities/artwork_longest_edge_and_blind_label_computed_on_attach
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="MEMBER")
    entry = fixtures.open_entry(exhibition["id"], artist)

    flat = fixtures.attach_work(
        entry["id"], artist, with_primary_image=False, title="Flat Panel",
        medium_category="PAINTING", width_cm=90.0, height_cm=60.0, depth_cm=4.0,
        weight_kg=6.0,
    )
    deep = fixtures.attach_work(
        entry["id"], artist, with_primary_image=False, title="Deep Plinth",
        medium_category="SCULPTURE", width_cm=40.0, height_cm=55.0,
        depth_cm=130.0, weight_kg=30.0, declared_value_cents=600000,
    )

    assert flat["longest_edge_cm"] == 90.0
    assert flat["blind_label"] == "2026-0001"
    assert deep["longest_edge_cm"] == 130.0, "the greatest of the three dimensions"
    assert deep["blind_label"] == "2026-0002"

    fixtures.upload_primary_image(flat["id"], artist)
    assert fixtures.read_artwork(flat["id"])["primary_image_count"] == 1
    assert fixtures.read_artwork(deep["id"])["primary_image_count"] == 0

    reread = validate_success(
        api.get_entry(entry["id"], make_artist_headers(artist["id"]))
    )
    assert reread["works_count"] == 2
    assert reread["status"] == "DRAFT"


def test_artwork_attachment_off_the_declared_enum_or_range_is_invalid(api):
    """PRD §2.10: "**Body schema** — required fields present, enum members drawn
    from the declared sets, integers within range (each score criterion from 1 to
    10 inclusive, `photo_count` at least 1, cent amounts non-negative),
    `span_start_cm` strictly less than `span_end_cm`, the three score weights
    summing to exactly 1.00, `damage_notes` present when `condition_grade` is
    `DAMAGED`, `list_price_cents` present when `for_sale` is true, and both
    `carrier` and `tracking_number` present when `return_method` is `COURIER`. Any
    violation is `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/artwork_invalid_medium_category_enum_rejected
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="MEMBER")
    entry = fixtures.open_entry(exhibition["id"], artist)
    headers = make_artist_headers(artist["id"])

    off_enum = api.attach_artwork(
        entry["id"],
        create_artwork_payload(title="Not A Medium", medium_category="PERFORMANCE"),
        headers,
    )
    validate_error(off_enum, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    negative_money = api.attach_artwork(
        entry["id"],
        create_artwork_payload(title="Bad Value", declared_value_cents=-100),
        headers,
    )
    validate_error(negative_money, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    reread = validate_success(api.get_entry(entry["id"], headers))
    assert reread["works_count"] == 0


def test_artwork_image_is_append_only_evidence_without_a_version(api):
    """PRD §2.4: "Four record types are append-only evidence rather than living
    records, and they therefore carry only `id` and `created_at`: `ArtworkImage`,
    `ConflictDeclaration`, `Score`, and `ConditionReport`. For those four, both
    `updated_at` and `version` are absent from the resource entirely."

    Design: Corner/entities/artwork_image_is_immutable_with_no_version_field
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="MEMBER")
    entry = fixtures.open_entry(exhibition["id"], artist)
    artwork = fixtures.attach_work(entry["id"], artist, with_primary_image=False)
    headers = make_artist_headers(artist["id"])

    primary = validate_success(
        api.upload_artwork_image(
            artwork["id"], create_artwork_image_payload(role="PRIMARY"), headers
        ),
        201,
    )
    assert primary["standard_ok"] is True
    assert "version" not in primary
    assert "updated_at" not in primary

    detail = validate_success(
        api.upload_artwork_image(
            artwork["id"],
            create_artwork_image_payload(
                role="DETAIL", format="PNG", pixel_long_edge=1600,
                pixel_short_edge=1200, file_bytes=2097152,
            ),
            headers,
        ),
        201,
    )
    assert "version" not in detail

    images, meta = validate_paginated(
        api.list_artwork_images(artwork["id"], JURY_CHAIR_A)
    )
    assert meta["total_count"] == 2
    assert images[0]["id"] == primary["id"], "ordered by created_at ascending"

    assert fixtures.read_artwork(artwork["id"])["primary_image_count"] == 1, (
        "primary_image_count counts only images whose role is PRIMARY"
    )


def test_entry_creation_resolves_each_body_foreign_key_on_its_own(api):
    """PRD §2.10: "**Body foreign-key existence** — every identifier supplied in
    the body resolves, else the corresponding 404 code. Applies to opening an
    entry, creating a jury round, booking an assignment, submitting a score,
    registering a wall segment, registering a sponsor, proposing an award,
    recording a sale, filing an installation plan, and filing a conflict
    declaration."

    Design: Corner/entities/entry_creation_with_unknown_exhibition_parent_returns_not_found
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="MEMBER")
    headers = make_artist_headers(artist["id"])

    bad_exhibition = api.create_entry(
        create_entry_payload(NON_EXISTENT_UUID, artist["id"]), headers
    )
    validate_error(bad_exhibition, ApiErrorId.ERR_EXHIBITION_NOT_FOUND.value, 404)

    bad_artist = api.create_entry(
        create_entry_payload(exhibition["id"], NON_EXISTENT_UUID), headers
    )
    validate_error(bad_artist, ApiErrorId.ERR_ARTIST_NOT_FOUND.value, 404)

    _, meta = validate_paginated(
        api.list_entries(CALL_MANAGER, params={"exhibition_id": exhibition["id"]})
    )
    assert meta["total_count"] == 0


def test_award_creation_resolves_the_sponsor_and_artwork_references(api):
    """PRD §2.5: "The same codes are used when an identifier supplied in a request
    body — `exhibition_id`, `artist_id`, `artwork_id`, `juror_id`,
    `wall_segment_id`, `sponsor_id`, `jury_round_id`, `entry_id` — does not
    resolve."

    Design: Corner/entities/award_creation_with_unknown_sponsor_id_returns_not_found
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="MEMBER")
    entry = fixtures.open_entry(exhibition["id"], artist)
    artwork = fixtures.attach_work(entry["id"], artist, with_primary_image=False)

    bad_sponsor = api.create_award(
        create_award_payload(
            exhibition["id"], artwork["id"], category="PURCHASE_AWARD",
            prize_cents=250000, sponsor_id=NON_EXISTENT_UUID,
        ),
        JURY_CHAIR_A,
    )
    validate_error(bad_sponsor, ApiErrorId.ERR_SPONSOR_NOT_FOUND.value, 404)

    bad_artwork = api.create_award(
        create_award_payload(
            exhibition["id"], NON_EXISTENT_UUID, category="BEST_IN_SHOW",
            prize_cents=100000,
        ),
        JURY_CHAIR_A,
    )
    validate_error(bad_artwork, ApiErrorId.ERR_ARTWORK_NOT_FOUND.value, 404)

    _, meta = validate_paginated(
        api.list_awards(JURY_CHAIR_A, params={"exhibition_id": exhibition["id"]})
    )
    assert meta["total_count"] == 0

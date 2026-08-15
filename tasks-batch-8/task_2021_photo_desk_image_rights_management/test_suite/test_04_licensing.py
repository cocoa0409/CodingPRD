"""Licensing: fee quoting, exclusivity windows, budget gate, release gate,
supersession OCC, and rights reversion (PRD §3.5, §2.7, §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_license,
    create_accepted_assignment,
    create_active_license,
    create_draft_license,
    create_license_payload,
    create_release,
    create_story,
    get_image_fresh,
    get_image_version,
    get_story_fresh,
    ingest_cleared_wire_image,
    parse_instant,
    record_usage_run,
    set_logical_clock,
    validate_error,
    validate_success,
)


def test_license_double_activate_rejected(api, rights_manager_headers):
    """PRD §3.5: "A new license starts in `DRAFT`." PRD §3.5: "Activation moves
    `DRAFT` to `ACTIVE` and enforces three gates, evaluated in this order". PRD
    §2.8: "State-machine from-state preconditions for action endpoints; terminal
    states reject all further transitions; else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/license_double_activate_rejected
    """
    image = ingest_cleared_wire_image()
    lic = create_active_license(image["id"])
    assert lic["status"] == "ACTIVE"

    resp = api.activate_license(lic["id"], rights_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_license_fee_rounded_once_at_final_step(api, rights_manager_headers):
    """PRD §2.6: "Every monetary calculation — license fee quotes, payout totals,
    kill fees, settlement splits, per-use royalty lines — rounds half-up to integer
    cents, and rounding is applied exactly once at the final step of each formula
    unless a calculation explicitly pins a different rounding point." PRD §3.5:
    "The quote proceeds in a pinned order."

    Design: Corner/calculations/license_fee_single_final_rounding
    """
    image = ingest_cleared_wire_image(
        source_type="STOCK", agency_name="StockHouse", base_license_fee_cents=1001,
        caption="Aerial view of the harbor at dusk", credit_line="StockHouse / StockHouse",
    )
    lic = create_draft_license(
        image["id"], usage_scope="SYNDICATION", territory="GLOBAL",
        valid_from="2026-08-01T00:00:00Z", valid_to="2026-12-31T23:59:59Z",
    )
    # 1001 x 1.5 = 1501.5; x 1.6 = 2402.4; one final round_half_up -> 2402.
    # (Step-rounding the intermediate 1501.5 to 1502 first would yield 2403.)
    assert lic["fee_cents"] == 2402, (
        f"rounding must happen once at the final step: expected 2402, got {lic['fee_cents']}"
    )


def test_budget_exceeded_on_activate(api, rights_manager_headers, photo_editor_headers):
    """PRD §3.5: "When the license names a `story_request_id`, the story's
    `committed_cents` plus the license's `fee_cents` must not exceed the story's
    `budget_cents`; otherwise activation is rejected with `ERR_BUDGET_EXCEEDED`."

    Design: Corner/validations/budget_exceeded_on_activate
    """
    story = create_story(slug="flood-aftermath", budget_cents=10000)
    image = ingest_cleared_wire_image()
    lic = create_draft_license(image["id"], story_request_id=story["id"])
    assert lic["fee_cents"] == 12000  # 10000 x DIGITAL 1.2 x DOMESTIC 1.0, FIRST_USE

    resp = api.activate_license(lic["id"], rights_manager_headers)
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)

    story_after = get_story_fresh(story["id"], headers=photo_editor_headers)
    assert story_after["committed_cents"] == 0, "a rejected activation must commit no budget"
    lic_after = api.get_license(lic["id"], rights_manager_headers)
    assert validate_success(lic_after, 200)["status"] == "DRAFT"


def test_license_create_stale_image_version_rejected(api, rights_manager_headers):
    """PRD §2.7: "Creating a license against an image requires
    `expected_image_version` in the request body, carrying the image's `version`
    as the client last observed it. If the image's current `version` has advanced
    — for any reason, including another license's supersession cascade — the
    create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/license_create_stale_image_version_rejected
    """
    image = ingest_cleared_wire_image()
    observed_version = get_image_version(image["id"])

    first = api.create_license(
        image["id"],
        create_license_payload(expected_image_version=observed_version),
        rights_manager_headers,
    )
    validate_success(first, 201)  # bumps the image version by one

    resp = api.create_license(
        image["id"],
        create_license_payload(expected_image_version=observed_version, usage_scope="SOCIAL"),
        rights_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_rights_reversion_boundary_and_license_block(api, rights_manager_headers, photo_editor_headers):
    """PRD §3.7: "The `rights_reverted` flag derives from the logical clock: it is
    true exactly when `rights_reversion_at` is non-null and the logical now is at
    or after it — rights have reverted at the exact reversion instant." PRD §3.5:
    "A further temporal gate applies to assignment images: once an `ASSIGNMENT`
    image's `rights_reverted` flag is true, no new license may be created on it —
    the attempt is rejected with `ERR_RIGHTS_REVERTED`."

    Design: Corner/calculations/rights_reversion_boundary_and_license_block
    """
    bundle = create_accepted_assignment(
        photographer_overrides={
            "full_name": "Fran Free", "email": "fran@freelance.io",
            "photographer_type": "FREELANCE", "day_rate_cents": 20000,
            "per_image_fee_cents": 30000, "rights_reversion_months": 12,
        },
        shoot_start="2026-08-10T09:00:00Z", shoot_end="2026-08-10T17:00:00Z",
    )
    image_id = bundle["images"][0]["id"]
    lic = create_active_license(
        image_id, usage_scope="DIGITAL",
        valid_from="2026-08-01T00:00:00Z", valid_to="2028-01-01T00:00:00Z",
    )
    record_usage_run(image_id, lic["id"], headers=photo_editor_headers,
                     story_slug="night-market", published_at="2026-08-20T00:00:00Z")

    set_logical_clock("2027-08-19T23:59:59Z")
    before = get_image_fresh(image_id)
    # 12 calendar months after first publication 2026-08-20 -> 2027-08-20.
    assert parse_instant(before["rights_reversion_at"]) == parse_instant("2027-08-20T00:00:00Z")
    assert before["rights_reverted"] is False, "one second before the reversion instant"

    set_logical_clock("2027-08-20T00:00:00Z")
    after = get_image_fresh(image_id)
    assert after["rights_reverted"] is True, "at exactly the reversion instant rights have reverted"

    resp = api.create_license(
        image_id,
        create_license_payload(
            expected_image_version=after["version"],
            usage_scope="PRINT",
            valid_from="2027-08-21T00:00:00Z", valid_to="2027-12-31T23:59:59Z",
        ),
        rights_manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_RIGHTS_REVERTED)


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / license_fee_first_use_vs_reuse
# ---------------------------------------------------------------------------

def _setup_wire_image_with_one_prior_use():
    """CLEARED WIRE image (base 10000) whose ACTIVE DIGITAL license already
    authorized one usage run, so times_used == 1 afterwards."""
    image = ingest_cleared_wire_image(keywords=["flood"])
    lic1 = create_active_license(image["id"], usage_scope="DIGITAL")
    record_usage_run(image["id"], lic1["id"], story_slug="flood-day-one",
                     published_at="2026-08-03T12:00:00Z")
    return get_image_fresh(image["id"]), lic1


def test_first_use_license_prices_at_full_rate(api, rights_manager_headers):
    """PRD §3.5: "At creation the license's fee is quoted and frozen on
    `fee_cents`, and its `pricing_variant` is set to `REUSE` when the image's
    `times_used` is greater than zero at that moment, else `FIRST_USE`." PRD §3.5:
    "Apply the scope multiplier: 1.0 for `PRINT`, 1.2 for `DIGITAL`, 0.8 for
    `SOCIAL`, 1.5 for `SYNDICATION`."

    Design: Difficulty/dual_variant_calc/license_fee_first_use_vs_reuse
    """
    image = ingest_cleared_wire_image(keywords=["flood"])
    lic = create_draft_license(image["id"], usage_scope="DIGITAL")
    assert_license(lic)
    assert lic["pricing_variant"] == "FIRST_USE", "times_used is zero at creation"
    # 10000 x DIGITAL 1.2 x DOMESTIC 1.0, no exclusivity, no discount.
    assert lic["fee_cents"] == 12000


def test_reuse_license_applies_discount_after_exclusivity(api, rights_manager_headers):
    """PRD §3.5: "Finally, for a `REUSE` license, apply the reuse discount by
    multiplying by 0.6 — that is, a 40 percent discount applied after the
    exclusivity multiplier — and round half-up to integer cents; a `FIRST_USE`
    license skips the discount and rounds half-up directly."

    Design: Difficulty/dual_variant_calc/license_fee_first_use_vs_reuse
    """
    image, lic1 = _setup_wire_image_with_one_prior_use()
    assert image["times_used"] == 1
    assert lic1["pricing_variant"] == "FIRST_USE" and lic1["fee_cents"] == 12000

    lic2 = create_draft_license(image["id"], usage_scope="DIGITAL")
    assert lic2["pricing_variant"] == "REUSE", "times_used > 0 at creation forces REUSE"
    assert lic2["fee_cents"] == 7200, (
        f"identical terms must price lower on reuse: 12000 x 0.6 = 7200, got {lic2['fee_cents']}"
    )
    assert lic2["fee_cents"] < lic1["fee_cents"]


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / license_fee_scope_territory_exclusivity_tiering
# ---------------------------------------------------------------------------

def test_fee_combines_scope_territory_and_exclusivity_in_pinned_order(api, rights_manager_headers):
    """PRD §3.5: "Apply the scope multiplier: 1.0 for `PRINT`, 1.2 for `DIGITAL`,
    0.8 for `SOCIAL`, 1.5 for `SYNDICATION`. Apply the territory multiplier to the
    result: 1.0 for `DOMESTIC`, 1.3 for `INTERNATIONAL`, 1.6 for `GLOBAL`. If the
    license is exclusive, double the result; otherwise leave it unchanged."

    Design: Difficulty/combinatorial_formula/license_fee_scope_territory_exclusivity_tiering
    """
    image = ingest_cleared_wire_image(
        source_type="STOCK", agency_name="StockHouse",
        caption="Aerial view of the harbor at dusk", credit_line="StockHouse / StockHouse",
    )
    lic = create_draft_license(
        image["id"], usage_scope="SYNDICATION", territory="GLOBAL", exclusive=True,
        valid_from="2026-08-01T00:00:00Z", valid_to="2026-12-31T23:59:59Z",
    )
    # 10000 x 1.5 (SYNDICATION) x 1.6 (GLOBAL) x 2.0 (exclusive) = 48000.
    assert lic["fee_cents"] == 48000, f"pinned-order product must be 48000, got {lic['fee_cents']}"
    assert lic["pricing_variant"] == "FIRST_USE"


def test_exclusivity_doubles_the_otherwise_identical_fee(api, rights_manager_headers):
    """PRD §3.5: "If the license is exclusive, double the result; otherwise leave
    it unchanged."

    Design: Difficulty/combinatorial_formula/license_fee_scope_territory_exclusivity_tiering
    """
    image_a = ingest_cleared_wire_image(
        source_type="STOCK", agency_name="StockHouse",
        caption="Aerial view of the harbor at dusk", credit_line="StockHouse / StockHouse",
    )
    image_b = ingest_cleared_wire_image(
        source_type="STOCK", agency_name="StockHouse",
        caption="Aerial view of the harbor at dusk", credit_line="StockHouse / StockHouse",
    )
    common = dict(
        usage_scope="SYNDICATION", territory="GLOBAL",
        valid_from="2026-08-01T00:00:00Z", valid_to="2026-12-31T23:59:59Z",
    )
    non_exclusive = create_draft_license(image_a["id"], exclusive=False, **common)
    exclusive = create_draft_license(image_b["id"], exclusive=True, **common)
    assert non_exclusive["fee_cents"] == 24000
    assert exclusive["fee_cents"] == 48000, (
        "the exclusivity branch doubles the fee on otherwise identical terms"
    )


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap / exclusive_license_half_open_adjacency
# ---------------------------------------------------------------------------

def test_exclusive_activation_allowed_at_half_open_adjacency(api, rights_manager_headers):
    """PRD §3.5: "If another `ACTIVE` exclusive license exists on the same image
    whose half-open window overlaps this license's window, activation is rejected
    with `ERR_EXCLUSIVE_LICENSE_CONFLICT`. If this license is itself exclusive,
    any other `ACTIVE` license of any kind with an overlapping window triggers the
    same rejection. Overlap uses half-open semantics, so adjacency — one window's
    `valid_from` equal to the other's `valid_to` — does not conflict."

    Design: Difficulty/resource_temporal_overlap/exclusive_license_half_open_adjacency
    """
    image = ingest_cleared_wire_image()
    lic1 = create_active_license(
        image["id"], usage_scope="DIGITAL", exclusive=True,
        valid_from="2026-08-01T00:00:00Z", valid_to="2026-08-10T00:00:00Z",
    )
    lic2 = create_draft_license(
        image["id"], usage_scope="SOCIAL", exclusive=True,
        valid_from="2026-08-10T00:00:00Z", valid_to="2026-08-20T00:00:00Z",
    )
    activated = validate_success(api.activate_license(lic2["id"], rights_manager_headers), 200)
    assert activated["status"] == "ACTIVE", (
        "valid_from exactly at the other license's valid_to is adjacency, not overlap"
    )


def test_exclusive_activation_overlapping_by_one_day_rejected(api, rights_manager_headers):
    """PRD §3.5: "If another `ACTIVE` exclusive license exists on the same image
    whose half-open window overlaps this license's window, activation is rejected
    with `ERR_EXCLUSIVE_LICENSE_CONFLICT`. If this license is itself exclusive,
    any other `ACTIVE` license of any kind with an overlapping window triggers the
    same rejection. Overlap uses half-open semantics, so adjacency — one window's
    `valid_from` equal to the other's `valid_to` — does not conflict."

    Design: Difficulty/resource_temporal_overlap/exclusive_license_half_open_adjacency
    """
    image = ingest_cleared_wire_image()
    create_active_license(
        image["id"], usage_scope="DIGITAL", exclusive=True,
        valid_from="2026-08-01T00:00:00Z", valid_to="2026-08-10T00:00:00Z",
    )
    lic3 = create_draft_license(
        image["id"], usage_scope="PRINT", exclusive=True,
        valid_from="2026-08-09T00:00:00Z", valid_to="2026-08-15T00:00:00Z",
    )
    resp = api.activate_license(lic3["id"], rights_manager_headers)
    # [2026-08-09, 2026-08-15) intersects [2026-08-01, 2026-08-10) -> overlap.
    validate_error(resp, ApiErrorId.ERR_EXCLUSIVE_LICENSE_CONFLICT)


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency / license_activation_blocked_without_release
# ---------------------------------------------------------------------------

def test_activation_blocked_without_model_release(api, rights_manager_headers):
    """PRD §3.5: "An image whose `has_identifiable_people` is true requires an
    `ACTIVE`, non-expired `MODEL` release on the image; an image whose
    `has_private_property` is true requires an `ACTIVE`, non-expired `PROPERTY`
    release. Missing or lapsed releases reject the activation with
    `ERR_RELEASE_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/license_activation_blocked_without_release
    """
    image = ingest_cleared_wire_image(
        caption="Actor on the gala red carpet", has_identifiable_people=True,
    )
    lic = create_draft_license(image["id"])
    resp = api.activate_license(lic["id"], rights_manager_headers)
    validate_error(resp, ApiErrorId.ERR_RELEASE_REQUIRED)


def test_activation_succeeds_after_model_release_registered(api, rights_manager_headers):
    """PRD §3.5: "An image whose `has_identifiable_people` is true requires an
    `ACTIVE`, non-expired `MODEL` release on the image". PRD §3.6: "Releases start
    `ACTIVE`; a `RightsManager` may revoke one, moving it to `REVOKED`."

    Design: Difficulty/cross_entity_state_dependency/license_activation_blocked_without_release
    """
    image = ingest_cleared_wire_image(
        caption="Actor on the gala red carpet", has_identifiable_people=True,
    )
    lic = create_draft_license(image["id"])
    validate_error(api.activate_license(lic["id"], rights_manager_headers),
                   ApiErrorId.ERR_RELEASE_REQUIRED)

    create_release(image["id"], subject_type="MODEL", subject_name="Actor A")
    activated = validate_success(api.activate_license(lic["id"], rights_manager_headers), 200)
    assert activated["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / release_safety_beats_budget_fiscal
# ---------------------------------------------------------------------------

def test_release_gate_surfaces_before_budget_on_activation(api, rights_manager_headers):
    """PRD §3.5: "Activation moves `DRAFT` to `ACTIVE` and enforces three gates,
    evaluated in this order:" PRD §2.8: "Within a single endpoint, these
    priorities resolve ties: for example, on license activation the release gate
    surfaces before the exclusivity conflict, which surfaces before the budget
    check; on a usage-run creation, embargo, window, restriction, referential,
    scope, and license-active checks are reported in that relative order after
    the editorial gate."

    Design: Difficulty/priority_pair_validation_conflict/release_safety_beats_budget_fiscal
    """
    story = create_story(slug="celebrity-gala", budget_cents=10000)
    image = ingest_cleared_wire_image(
        caption="Actor on the gala red carpet", has_identifiable_people=True,
    )
    # Fee 48000 (SYNDICATION x GLOBAL x exclusive) breaches the 10000 budget AND
    # the image lacks the required MODEL release: both gates fail at once.
    lic = create_draft_license(
        image["id"], usage_scope="SYNDICATION", territory="GLOBAL", exclusive=True,
        story_request_id=story["id"],
        valid_from="2026-08-01T00:00:00Z", valid_to="2026-12-31T23:59:59Z",
    )
    assert lic["fee_cents"] == 48000
    resp = api.activate_license(lic["id"], rights_manager_headers)
    validate_error(resp, ApiErrorId.ERR_RELEASE_REQUIRED)


def test_budget_gate_fires_when_release_gate_passes(api, rights_manager_headers):
    """PRD §3.5: "When the license names a `story_request_id`, the story's
    `committed_cents` plus the license's `fee_cents` must not exceed the story's
    `budget_cents`; otherwise activation is rejected with `ERR_BUDGET_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/release_safety_beats_budget_fiscal
    """
    story = create_story(slug="celebrity-gala", budget_cents=10000)
    image = ingest_cleared_wire_image(
        caption="Actor on the gala red carpet", has_identifiable_people=True,
    )
    create_release(image["id"], subject_type="MODEL", subject_name="Actor A")
    lic = create_draft_license(image["id"], story_request_id=story["id"])
    assert lic["fee_cents"] == 12000  # exceeds the 10000 budget on its own
    resp = api.activate_license(lic["id"], rights_manager_headers)
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / story_budget_activate_revoke_conservation
# ---------------------------------------------------------------------------

def test_activation_commits_fee_to_story_budget(api, rights_manager_headers, photo_editor_headers):
    """PRD §3.5: "On successful activation, the license's `fee_cents` is added to
    the story's `committed_cents` when a story is named."

    Design: Difficulty/compensating_invariant/story_budget_activate_revoke_conservation
    """
    story = create_story(slug="flood-aftermath", budget_cents=30000)
    image = ingest_cleared_wire_image()
    lic = create_draft_license(image["id"], story_request_id=story["id"])
    assert get_story_fresh(story["id"], headers=photo_editor_headers)["committed_cents"] == 0

    validate_success(api.activate_license(lic["id"], rights_manager_headers), 200)
    committed = get_story_fresh(story["id"], headers=photo_editor_headers)["committed_cents"]
    assert committed == 12000, f"activation must commit the fee 12000, got {committed}"


def test_revocation_releases_committed_budget(api, rights_manager_headers, photo_editor_headers):
    """PRD §3.5: "Revoking an `ACTIVE` license compensates the story budget:
    `committed_cents` decreases by the license's `fee_cents`."

    Design: Difficulty/compensating_invariant/story_budget_activate_revoke_conservation
    """
    story = create_story(slug="flood-aftermath", budget_cents=30000)
    image = ingest_cleared_wire_image()
    lic = create_active_license(image["id"], story_request_id=story["id"])
    assert get_story_fresh(story["id"], headers=photo_editor_headers)["committed_cents"] == 12000

    revoked = validate_success(api.revoke_license(lic["id"], rights_manager_headers), 200)
    assert revoked["status"] == "REVOKED"
    committed = get_story_fresh(story["id"], headers=photo_editor_headers)["committed_cents"]
    assert committed == 0, (
        "the compensating revoke must restore the pre-activation allocation of 0, "
        f"got {committed}"
    )

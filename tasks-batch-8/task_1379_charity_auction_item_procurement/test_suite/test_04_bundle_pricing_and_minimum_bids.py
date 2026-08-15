"""Catalog assembly: pinned minimum-bid rounding order, floor application,
preview vs locked minimum bids, publish cardinality, attach/detach
conservation, and catalog freeze."""
from test_helpers import (
    ADMIN,
    CM,
    PO,
    ApiErrorId,
    api_client,
    approve_valuation,
    attach_item,
    create_bundle,
    create_donor,
    create_event,
    create_pledged_solicitation,
    detach_item,
    get_success_data,
    publish_bundle,
    receive_item,
    setup_bidding_open_scenario,
    setup_published_bundle,
    setup_valued_item,
    submit_valuation,
    validate_error,
    validate_success,
)


def _cataloging_event_with_valued_items(fmvs):
    """Event advanced to CATALOGING with one VALUED item per fmv."""
    event = create_event()
    api_client.advance_gala_event(event["id"], ADMIN)  # SOLICITING
    parts = [setup_valued_item(event["id"], fmv) for fmv in fmvs]
    api_client.advance_gala_event(event["id"], ADMIN)  # CATALOGING
    return event, parts


class TestMinimumBidRoundingOrder:

    def _two_published_bundles(self):
        """Items at 33333 and 33335 cents, each alone in a published
        bundle under the standard 3000-bps / 1000-floor / 500-grid
        policy."""
        event, parts = _cataloging_event_with_valued_items([33333, 33335])
        bundle_a = setup_published_bundle(event["id"],
                                          [parts[0]["item"]["id"]])
        bundle_b = setup_published_bundle(event["id"],
                                          [parts[1]["item"]["id"]])
        return bundle_a, bundle_b

    def test_min_bid_rounding_half_up_at_exact_half(self):
        """PRD section 3.4: "First, the bundle's fair market value in cents
        is multiplied by the event's `min_bid_pct_bps` and divided by ten
        thousand, and the result is rounded half-up to whole cents — the
        basis-point rounding happens first. Second, if that rounded figure
        falls below the event's `min_bid_floor_cents`, it is raised to the
        floor — the floor applies only after the rounding. Third, the
        floored figure is rounded up to the next whole multiple of the
        event's `min_bid_increment_cents`."

        Design: Difficulty/combinatorial_formula/min_bid_nested_rounding_order
        """
        bundle_a, _bundle_b = self._two_published_bundles()
        # FMV 33333: rhu(33333*0.3) = rhu(9999.9) = 10000; floor no-op;
        # ceil(10000/500)*500 = 10000.
        assert bundle_a["min_bid_cents"] == 10000
        assert bundle_a["bundle_fmv_cents"] == 33333
        assert bundle_a["status"] == "PUBLISHED"

    def test_min_bid_rounding_fractional_cent_ceils_to_grid(self):
        """PRD section 3.4: "The evaluation order — basis-point rounding,
        then floor, then ceiling to the grid — is fixed; any other order
        yields different cents and is wrong."

        Design: Difficulty/combinatorial_formula/min_bid_nested_rounding_order
        """
        bundle_a, bundle_b = self._two_published_bundles()
        # FMV 33335: rhu(33335*0.3) = rhu(10000.5) = 10001; floor no-op;
        # ceil(10001/500)*500 = 10500.
        assert bundle_b["min_bid_cents"] == 10500
        assert bundle_b["bundle_fmv_cents"] == 33335
        assert bundle_a["min_bid_cents"] == 10000


class TestMinBidPreviewVsLocked:

    def _draft_bundle_with_item(self):
        """Event CATALOGING; item valued 20000; attached to a DRAFT
        bundle."""
        event, parts = _cataloging_event_with_valued_items([20000])
        item = parts[0]["item"]
        bundle = create_bundle(event["id"], title="Painting Solo")
        bundle = attach_item(bundle["id"], item["id"])
        return event, item, bundle

    def test_preview_min_bid_tracks_valuation_changes(self):
        """PRD section 3.4: "While the bundle is in `DRAFT`, reading it
        shows the preview variant, computed on the fly from the current
        member fair market values, so it shifts as valuations are approved
        or items attach and detach."

        Design: Difficulty/dual_variant_calc/bundle_min_bid_preview_vs_locked
        """
        _event, item, bundle = self._draft_bundle_with_item()
        first = get_success_data(api_client.get_bundle(bundle["id"], CM))
        # rhu(20000*0.3) = 6000; floor no-op; ceil(6000/500)*500 = 6000.
        assert first["min_bid_cents"] == 6000
        assert first["status"] == "DRAFT"

        approve_valuation(submit_valuation(item["id"], 40000)["id"])
        second = get_success_data(api_client.get_bundle(bundle["id"], CM))
        assert second["min_bid_cents"] == 12000, \
            "preview reflects the re-valuation while DRAFT"
        assert second["bundle_fmv_cents"] == 40000

    def test_locked_min_bid_ignores_post_publish_revaluation(self):
        """PRD section 3.4: "At publish, the locked variant is computed
        once from the frozen `bundle_fmv_cents` and stored on
        `min_bid_cents`; valuation changes after publish never move the
        locked value, so preview and locked figures diverge whenever a
        valuation lands between the last preview and the publish."

        Design: Difficulty/dual_variant_calc/bundle_min_bid_preview_vs_locked
        """
        _event, item, bundle = self._draft_bundle_with_item()
        approve_valuation(submit_valuation(item["id"], 40000)["id"])
        published = publish_bundle(bundle["id"])
        assert published["min_bid_cents"] == 12000
        assert published["bundle_fmv_cents"] == 40000
        assert published["status"] == "PUBLISHED"
        assert published["published_at"] is not None

        approve_valuation(submit_valuation(item["id"], 50000)["id"])
        after = get_success_data(api_client.get_bundle(bundle["id"], CM))
        assert after["min_bid_cents"] == 12000, "locked value does not move"
        assert after["bundle_fmv_cents"] == 40000, "frozen FMV does not move"

        item_after = get_success_data(api_client.get_item(item["id"], PO))
        assert item_after["current_fmv_cents"] == 50000, \
            "the item itself tracks the new approval"


class TestPublishCardinality:

    def test_publish_empty_bundle_rejected(self):
        """PRD section 3.4: "A `CatalogManager` may publish a bundle only
        while the event is in `CATALOGING` (`ERR_CATALOG_FROZEN` otherwise)
        and only when the bundle has at least one member item
        (`ERR_BUNDLE_EMPTY` otherwise)."

        Design: Difficulty/boundary_precision_check/publish_empty_bundle_rejected
        """
        event, _parts = _cataloging_event_with_valued_items([40000])
        bundle = create_bundle(event["id"], title="Empty then full")
        resp = api_client.publish_bundle(bundle["id"], CM)
        validate_error(resp, ApiErrorId.ERR_BUNDLE_EMPTY)

        after = get_success_data(api_client.get_bundle(bundle["id"], CM))
        assert after["status"] == "DRAFT"

    def test_publish_after_single_attach_succeeds(self):
        """PRD section 3.4: "Publication freezes `bundle_fmv_cents`,
        computes and stores the locked `min_bid_cents`, stamps
        `published_at` with the logical clock's instant, moves the bundle
        from `DRAFT` to `PUBLISHED`, moves every member item from
        `BUNDLED` to `CATALOGED`, and increments the bundle's `version`."

        Design: Difficulty/boundary_precision_check/publish_empty_bundle_rejected
        """
        event, parts = _cataloging_event_with_valued_items([40000])
        bundle = create_bundle(event["id"], title="Empty then full")
        attach_item(bundle["id"], parts[0]["item"]["id"])
        published = validate_success(api_client.publish_bundle(
            bundle["id"], CM))
        assert published["status"] == "PUBLISHED"
        # rhu(40000*0.3) = 12000 -> grid 12000.
        assert published["min_bid_cents"] == 12000
        assert published["bundle_fmv_cents"] == 40000
        assert published["published_at"] == "2026-08-01T00:00:00Z"

        item_after = get_success_data(
            api_client.get_item(parts[0]["item"]["id"], PO))
        assert item_after["status"] == "CATALOGED"


class TestMinBidFloor:

    def test_min_bid_floor_binds_below_percentage(self):
        """PRD section 3.4: "Second, if that rounded figure falls below
        the event's `min_bid_floor_cents`, it is raised to the floor — the
        floor applies only after the rounding."

        Design: Corner/calculations/min_bid_floor_binds_below_percentage
        """
        event, parts = _cataloging_event_with_valued_items([2000])
        bundle = create_bundle(event["id"], title="Mug")
        attach_item(bundle["id"], parts[0]["item"]["id"])
        published = publish_bundle(bundle["id"])
        # rhu(2000*0.3) = 600 < floor 1000 -> 1000; ceil(1000/500)*500 = 1000.
        assert published["min_bid_cents"] == 1000
        assert published["bundle_fmv_cents"] == 2000


class TestAttachDetachConservation:

    def _bundle_with_two_valued_items(self):
        event, parts = _cataloging_event_with_valued_items([25000, 15000])
        bundle = create_bundle(event["id"], title="Furniture pair")
        return parts[0]["item"], parts[1]["item"], bundle

    def test_attach_detach_bundle_fmv_conservation(self):
        """PRD section 3.4: "A successful attach moves the item from
        `VALUED` to `BUNDLED`, points its `bundle_id` at the bundle,
        recomputes the bundle's `bundle_fmv_cents` as the sum of its
        members' `current_fmv_cents`, and increments the bundle's
        `version`." PRD section 3.4: "returns the item from `BUNDLED` to
        `VALUED`, nulls its `bundle_id`, recomputes `bundle_fmv_cents`,
        and increments the bundle's `version`."

        Design: Difficulty/compensating_invariant/attach_detach_bundle_fmv_conservation
        """
        item_a, item_b, bundle = self._bundle_with_two_valued_items()
        assert bundle["bundle_fmv_cents"] == 0

        after_a = attach_item(bundle["id"], item_a["id"])
        assert after_a["bundle_fmv_cents"] == 25000

        after_b = attach_item(bundle["id"], item_b["id"])
        assert after_b["bundle_fmv_cents"] == 40000

        after_detach = detach_item(bundle["id"], item_b["id"])
        assert after_detach["bundle_fmv_cents"] == 25000, \
            "detach restores the sum exactly"

        reattach = attach_item(bundle["id"], item_b["id"])
        assert reattach["bundle_fmv_cents"] == 40000, \
            "re-attach restores the pre-detach sum"

    def test_attach_detach_version_progression(self):
        """PRD section 2.4: "`version` (integer): a system-managed integer
        that increments with every modification to the resource." PRD
        section 3.4: "recomputes the bundle's `bundle_fmv_cents` as the
        sum of its members' `current_fmv_cents`, and increments the
        bundle's `version`."

        Design: Difficulty/compensating_invariant/attach_detach_bundle_fmv_conservation
        """
        item_a, item_b, bundle = self._bundle_with_two_valued_items()
        assert bundle["version"] == 1, "create"

        v2 = attach_item(bundle["id"], item_a["id"])
        assert v2["version"] == 2, "attach A"
        v3 = attach_item(bundle["id"], item_b["id"])
        assert v3["version"] == 3, "attach B"
        v4 = detach_item(bundle["id"], item_b["id"])
        assert v4["version"] == 4, "detach B"
        item_b_after = get_success_data(api_client.get_item(item_b["id"], PO))
        assert item_b_after["status"] == "VALUED"
        assert item_b_after["bundle_id"] is None
        v5 = attach_item(bundle["id"], item_b["id"])
        assert v5["version"] == 5, "re-attach B — no drift"
        assert v5["bundle_fmv_cents"] == 40000


class TestAttachGates:

    def test_attach_received_item_rejected(self):
        """PRD section 3.4: "the item is `VALUED`, meaning it carries an
        approved valuation (`ERR_ITEM_NOT_VALUED` otherwise)"

        Design: Difficulty/cross_entity_state_dependency/bundle_attach_requires_item_valued
        """
        event = create_event()
        api_client.advance_gala_event(event["id"], ADMIN)  # SOLICITING
        donor = create_donor()
        sol = create_pledged_solicitation(donor["id"], event["id"])
        item = receive_item(sol["id"])  # RECEIVED, never valued
        api_client.advance_gala_event(event["id"], ADMIN)  # CATALOGING
        bundle = create_bundle(event["id"], title="Furniture")

        item_now = get_success_data(api_client.get_item(item["id"], PO))
        assert item_now["status"] == "RECEIVED"
        resp = api_client.attach_item(bundle["id"], {"item_id": item["id"]},
                                      CM)
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_VALUED)

    def test_attach_after_valuation_succeeds(self):
        """PRD section 3.4: "A successful attach moves the item from
        `VALUED` to `BUNDLED`, points its `bundle_id` at the bundle,
        recomputes the bundle's `bundle_fmv_cents` as the sum of its
        members' `current_fmv_cents`, and increments the bundle's
        `version`."

        Design: Difficulty/cross_entity_state_dependency/bundle_attach_requires_item_valued
        """
        event, parts = _cataloging_event_with_valued_items([20000])
        bundle = create_bundle(event["id"], title="Furniture")
        attached = validate_success(api_client.attach_item(
            bundle["id"], {"item_id": parts[0]["item"]["id"]}, CM))
        assert attached["bundle_fmv_cents"] == 20000

        item_after = get_success_data(
            api_client.get_item(parts[0]["item"]["id"], PO))
        assert item_after["status"] == "BUNDLED"
        assert item_after["bundle_id"] == bundle["id"]

    def test_attach_already_bundled_item_rejected(self):
        """PRD section 3.4: "the item's `bundle_id` is null
        (`ERR_ITEM_ALREADY_BUNDLED` otherwise); and the item belongs to
        the same event as the bundle."

        Design: Corner/validations/attach_already_bundled_item_rejected
        """
        event, parts = _cataloging_event_with_valued_items([30000])
        item_id = parts[0]["item"]["id"]
        bundle1 = create_bundle(event["id"], title="B1")
        bundle2 = create_bundle(event["id"], title="B2")
        attach_item(bundle1["id"], item_id)

        resp = api_client.attach_item(bundle2["id"], {"item_id": item_id},
                                      CM)
        validate_error(resp, ApiErrorId.ERR_ITEM_ALREADY_BUNDLED)

        detach_item(bundle1["id"], item_id)
        attached = validate_success(api_client.attach_item(
            bundle2["id"], {"item_id": item_id}, CM))
        assert attached["bundle_fmv_cents"] == 30000


class TestMinBidOverride:

    def test_min_bid_override_occ_and_floor(self):
        """PRD section 3.4: "The override value `min_bid_cents` must reach
        at least the event's `min_bid_floor_cents`
        (`ERR_MIN_BID_BELOW_FLOOR` otherwise), and the request must carry
        `expected_bundle_version` per §2.7. A successful override sets
        `min_bid_overridden` to true and increments the bundle's
        `version`."

        Design: Corner/cross_cutting_complexity_layers/occ_min_bid_override_and_floor
        """
        event, parts = _cataloging_event_with_valued_items([40000])
        bundle = setup_published_bundle(event["id"],
                                        [parts[0]["item"]["id"]])
        bd_v = bundle["version"]
        assert bundle["min_bid_cents"] == 12000

        below_floor = api_client.override_min_bid(
            bundle["id"],
            {"min_bid_cents": 500, "expected_bundle_version": bd_v}, CM)
        validate_error(below_floor, ApiErrorId.ERR_MIN_BID_BELOW_FLOOR)

        overridden = validate_success(api_client.override_min_bid(
            bundle["id"],
            {"min_bid_cents": 4500, "expected_bundle_version": bd_v}, CM))
        assert overridden["min_bid_cents"] == 4500
        assert overridden["min_bid_overridden"] is True
        assert overridden["version"] == bd_v + 1

        stale = api_client.override_min_bid(
            bundle["id"],
            {"min_bid_cents": 4600, "expected_bundle_version": bd_v}, CM)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        after = get_success_data(api_client.get_bundle(bundle["id"], CM))
        assert after["min_bid_cents"] == 4500


class TestCatalogFreeze:

    def test_catalog_edits_frozen_after_bidding_open(self):
        """PRD section 2.8: "structural catalog edits (bundle creation,
        attach, detach, publish, minimum-bid override) are allowed only
        while the event is in `CATALOGING`; otherwise `ERR_CATALOG_FROZEN`
        (HTTP 409)."

        Design: Corner/validations/catalog_edits_frozen_after_bidding_open
        """
        ctx = setup_bidding_open_scenario(fmv_cents=40000, title="Vase")
        resp = api_client.create_bundle(
            {"gala_event_id": ctx["event"]["id"], "title": "Late bundle"},
            CM)
        validate_error(resp, ApiErrorId.ERR_CATALOG_FROZEN)

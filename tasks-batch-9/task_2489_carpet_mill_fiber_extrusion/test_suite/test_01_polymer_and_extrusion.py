"""Polymer receiving dock, reclamation line and spinning extruders.

Covers polymer lots and their four mass buckets, reclamation intake and
depolymerization yield, fiber-batch blend / feedstock / denier gates, and the
fiber-batch lifecycle including scrapping and the release gate.
"""

import pytest

from test_helpers import (
    assert_fiber_batch,
    assert_polymer_lot,
    assert_polymer_mass_conservation,
    assert_reclamation_batch,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_extrusion_operator_headers,
    make_mill_planner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

EXTRUDER = make_extrusion_operator_headers()
PLANNER = make_mill_planner_headers()

KG = dict(abs=0.001)
YARDS = dict(abs=0.05)


def _polymer_lot_payload(lot_code, **overrides):
    payload = {
        "lot_code": lot_code,
        "polymer_type": "NYLON_66",
        "received_kg": 5000.0,
        "melt_flow_index": 18.0,
    }
    payload.update(overrides)
    return payload


def _fiber_batch_payload(batch_code, polymer_lot_id, **overrides):
    payload = {
        "batch_code": batch_code,
        "polymer_lot_id": polymer_lot_id,
        "input_kg": 4000.0,
        "denier_target": 1200.0,
        "filament_count": 72,
        "dye_method": "SOLUTION_DYED",
        "solution_color_code": "SC-BEIGE-01",
    }
    payload.update(overrides)
    return payload


def _style_payload(style_code, **overrides):
    payload = {
        "style_code": style_code,
        "line_type": "RUNNING_LINE",
        "gauge_code": "G_1_10",
        "pile_construction": "CUT",
        "pile_height_mm": 8.0,
        "pattern_repeat_mm": 300.0,
        "plies": 3,
        "target_face_weight_oz": 32.0,
        "dye_method": "SOLUTION_DYED",
        "solution_color_code": "SC-BEIGE-01",
        "list_price_cents_per_yard": 4275,
    }
    payload.update(overrides)
    return payload


def _buckets(lot):
    return (
        lot["available_kg"]
        + lot["reserved_kg"]
        + lot["consumed_kg"]
        + lot["scrapped_kg"]
    )


class TestPolymerLotReceiving:
    def test_receiving_a_lot_returns_201_with_every_declared_field(self, api):
        """A lot POSTed with all seven declared inputs is created, echoes them, and its
        four mass buckets already balance against received_kg.

        PRD: "`available_kg` is set equal to `received_kg`, while `reserved_kg`,
        `consumed_kg` and `scrapped_kg` are each set to 0, and the lot's `status` is
        `AVAILABLE`"

        Design: Corner/entities/create_polymer_lot_returns_201_with_all_declared_fields
        """
        response = api.create_polymer_lot(
            _polymer_lot_payload(
                "PL-N66-01",
                recycled_content_pct=25.0,
                segregated=True,
                reclaim_source="POST_INDUSTRIAL",
            ),
            EXTRUDER,
        )
        lot = validate_success(response, expected_status=201)

        body = response.json()
        assert set(body) == {"meta", "response_type", "data"}, (
            f"the success envelope carries meta, response_type and data, got {sorted(body)}"
        )

        assert lot["lot_code"] == "PL-N66-01", f"lot_code echoed, got {lot['lot_code']}"
        assert lot["polymer_type"] == "NYLON_66", (
            f"polymer_type echoed, got {lot['polymer_type']}"
        )
        assert lot["received_kg"] == pytest.approx(5000.000, **KG), (
            f"received_kg echoed, got {lot['received_kg']}"
        )
        assert lot["melt_flow_index"] == pytest.approx(18.0, abs=0.05), (
            f"melt_flow_index echoed, got {lot['melt_flow_index']}"
        )
        assert lot["recycled_content_pct"] == pytest.approx(25.00, abs=0.01), (
            f"recycled_content_pct echoed, got {lot['recycled_content_pct']}"
        )
        assert lot["segregated"] is True, f"segregated echoed, got {lot['segregated']}"
        assert lot["reclaim_source"] == "POST_INDUSTRIAL", (
            f"reclaim_source echoed, got {lot['reclaim_source']}"
        )

        assert lot["available_kg"] == pytest.approx(5000.000, **KG), (
            f"available_kg starts equal to received_kg, got {lot['available_kg']}"
        )
        assert lot["reserved_kg"] == pytest.approx(0.000, **KG), (
            f"reserved_kg starts at 0, got {lot['reserved_kg']}"
        )
        assert lot["consumed_kg"] == pytest.approx(0.000, **KG), (
            f"consumed_kg starts at 0, got {lot['consumed_kg']}"
        )
        assert lot["scrapped_kg"] == pytest.approx(0.000, **KG), (
            f"scrapped_kg starts at 0, got {lot['scrapped_kg']}"
        )
        assert lot["status"] == "AVAILABLE", (
            f"a freshly received lot is AVAILABLE, got {lot['status']}"
        )
        assert _buckets(lot) == pytest.approx(5000.000, **KG), (
            f"the four buckets must sum to received_kg, got {_buckets(lot)}"
        )
        assert_polymer_lot(lot)

        assert is_valid_uuid(lot["id"]), f"id must be a bare UUID, got {lot['id']!r}"
        assert is_iso8601_timestamp(lot["created_at"]), (
            f"created_at must be ISO 8601 UTC, got {lot['created_at']!r}"
        )
        assert is_iso8601_timestamp(lot["updated_at"]), (
            f"updated_at must be ISO 8601 UTC, got {lot['updated_at']!r}"
        )
        assert lot["version"] == 1, f"version starts at 1, got {lot['version']}"

    def test_reading_a_lot_back_serves_persisted_state(self, api):
        """The GET of a lot created with only the four required inputs returns the stored
        row with the three optional inputs materialised at their declared defaults.

        PRD: "`recycled_content_pct`, the declared post-consumer plus post-industrial
        recycled fraction as a percentage between 0 and 100 inclusive at 2 decimal
        places, defaulting to 0"

        Design: Corner/entities/get_polymer_lot_by_id_returns_the_stored_lot
        """
        created = validate_success(
            api.create_polymer_lot(_polymer_lot_payload("PL-N66-01"), EXTRUDER),
            expected_status=201,
        )

        lot = validate_success(api.get_polymer_lot(created["id"], PLANNER))

        assert lot["lot_code"] == "PL-N66-01", f"lot_code persisted, got {lot['lot_code']}"
        assert lot["received_kg"] == pytest.approx(5000.000, **KG), (
            f"received_kg persisted, got {lot['received_kg']}"
        )
        assert lot["recycled_content_pct"] == pytest.approx(0, abs=0.01), (
            f"omitted recycled_content_pct defaults to 0, got {lot['recycled_content_pct']}"
        )
        assert lot["segregated"] is False, (
            f"omitted segregated defaults to false, got {lot['segregated']}"
        )
        assert lot["reclaim_source"] == "VIRGIN", (
            f"omitted reclaim_source defaults to VIRGIN, got {lot['reclaim_source']}"
        )
        assert lot["available_kg"] == pytest.approx(5000.000, **KG), (
            f"available_kg persisted, got {lot['available_kg']}"
        )
        assert lot["status"] == "AVAILABLE", (
            f"an undrawn lot reads AVAILABLE, got {lot['status']}"
        )
        assert lot["version"] == 1, (
            f"an unmutated lot is still at version 1, got {lot['version']}"
        )

    def test_the_three_recycled_inputs_default_to_zero_false_and_virgin(self, api):
        """Omitting all three optional recycled-content inputs yields 0, false and VIRGIN
        on the creation response itself.

        PRD: "`reclaim_source`, one of `VIRGIN`, `POST_CONSUMER` or `POST_INDUSTRIAL`,
        defaulting to `VIRGIN`"

        Design: Corner/entities/polymer_lot_recycled_fields_default_to_zero_false_and_virgin
        """
        lot = validate_success(
            api.create_polymer_lot(
                _polymer_lot_payload("PL-N66-01", received_kg=4000.0), EXTRUDER
            ),
            expected_status=201,
        )

        assert lot["recycled_content_pct"] == pytest.approx(0, abs=0.01), (
            f"recycled_content_pct defaults to 0, got {lot['recycled_content_pct']}"
        )
        assert lot["segregated"] is False, (
            f"segregated defaults to false, got {lot['segregated']}"
        )
        assert lot["reclaim_source"] == "VIRGIN", (
            f"reclaim_source defaults to VIRGIN, got {lot['reclaim_source']}"
        )
        assert lot["status"] == "AVAILABLE", (
            f"a freshly received lot is AVAILABLE, got {lot['status']}"
        )
        assert lot["available_kg"] == pytest.approx(4000.000, **KG), (
            f"available_kg starts equal to received_kg, got {lot['available_kg']}"
        )

    def test_listing_lots_composes_the_reclaim_source_filter_with_pagination(self, api):
        """A filtered page of limit 1 over three lots returns one row, the filtered
        total_count of 2, and has_more true.

        PRD: "`total_count` counts every record matching the request's filters before
        pagination is applied and `has_more` indicates whether records remain beyond the
        current page"

        Design: Corner/entities/list_polymer_lots_filters_by_reclaim_source_and_paginates
        """
        first = validate_success(
            api.create_polymer_lot(
                _polymer_lot_payload("PL-V-01", received_kg=1000.0), EXTRUDER
            ),
            expected_status=201,
        )
        validate_success(
            api.create_polymer_lot(
                _polymer_lot_payload(
                    "PL-V-02", polymer_type="NYLON_6", received_kg=2000.0
                ),
                EXTRUDER,
            ),
            expected_status=201,
        )
        post_industrial = validate_success(
            api.create_polymer_lot(
                _polymer_lot_payload(
                    "PL-PI-01",
                    polymer_type="PET",
                    received_kg=3000.0,
                    melt_flow_index=20.0,
                    reclaim_source="POST_INDUSTRIAL",
                ),
                EXTRUDER,
            ),
            expected_status=201,
        )

        data, meta = validate_paginated(
            api.list_polymer_lots(
                PLANNER, params={"reclaim_source": "VIRGIN", "limit": 1, "offset": 0}
            )
        )

        assert meta["total_count"] == 2, (
            f"total_count counts the two VIRGIN lots, not the three rows, got "
            f"{meta['total_count']}"
        )
        assert meta["limit"] == 1, f"limit echoed, got {meta['limit']}"
        assert meta["offset"] == 0, f"offset echoed, got {meta['offset']}"
        assert meta["has_more"] is True, (
            f"has_more is true with 2 matches on a page of 1, got {meta['has_more']}"
        )
        assert len(data) == 1, f"a page of limit 1 returns one row, got {len(data)}"
        assert data[0]["id"] == first["id"], (
            f"created_at ascending puts PL-V-01 first, got {data[0]['lot_code']}"
        )
        assert data[0]["reclaim_source"] == "VIRGIN", (
            f"the filter admits only VIRGIN lots, got {data[0]['reclaim_source']}"
        )
        assert post_industrial["id"] not in [row["id"] for row in data], (
            "the POST_INDUSTRIAL lot must not appear in a VIRGIN-filtered page"
        )


class TestFiberBatchDrawsAgainstPolymerLots:
    def test_mass_buckets_move_from_available_to_reserved_on_a_draw(self, api):
        """available_kg and reserved_kg are computed, not supplied: 5000.000/0.000 at
        creation becomes 1000.000/4000.000 after a 4000.000 kg draw.

        PRD: "On creation the batch's `status` is `QUEUED`, and for each source lot the
        drawn mass is subtracted from that lot's `available_kg` and added to its
        `reserved_kg`, leaving the conservation identity intact."

        Design: Corner/entities/polymer_lot_mass_buckets_are_computed_at_creation_and_after_a_draw
        """
        lot_id = validate_success(
            api.create_polymer_lot(_polymer_lot_payload("PL-N66-01"), EXTRUDER),
            expected_status=201,
        )["id"]

        before = validate_success(api.get_polymer_lot(lot_id, EXTRUDER))
        assert before["available_kg"] == pytest.approx(5000.000, **KG), (
            f"available_kg starts at received_kg, got {before['available_kg']}"
        )
        assert before["reserved_kg"] == pytest.approx(0.000, **KG), (
            f"reserved_kg starts at 0, got {before['reserved_kg']}"
        )
        assert before["consumed_kg"] == pytest.approx(0.000, **KG), (
            f"consumed_kg starts at 0, got {before['consumed_kg']}"
        )
        assert before["scrapped_kg"] == pytest.approx(0.000, **KG), (
            f"scrapped_kg starts at 0, got {before['scrapped_kg']}"
        )

        batch = validate_success(
            api.create_fiber_batch(_fiber_batch_payload("FB-01", lot_id), EXTRUDER),
            expected_status=201,
        )

        after = validate_success(api.get_polymer_lot(lot_id, EXTRUDER))
        assert after["available_kg"] == pytest.approx(1000.000, **KG), (
            f"expected available_kg 1000.000 after a 4000.000 kg draw, got "
            f"{after['available_kg']}"
        )
        assert after["reserved_kg"] == pytest.approx(4000.000, **KG), (
            f"expected reserved_kg 4000.000 after the draw, got {after['reserved_kg']}"
        )
        assert after["consumed_kg"] == pytest.approx(0.000, **KG), (
            f"queuing reserves rather than consumes, got consumed_kg {after['consumed_kg']}"
        )
        assert after["scrapped_kg"] == pytest.approx(0.000, **KG), (
            f"nothing is scrapped by a draw, got scrapped_kg {after['scrapped_kg']}"
        )
        assert _buckets(after) == pytest.approx(5000.000, **KG), (
            f"the four buckets must still sum to 5000.000, got {_buckets(after)}"
        )
        assert after["status"] == "AVAILABLE", (
            f"1000.000 kg is still available, so the lot stays AVAILABLE, got "
            f"{after['status']}"
        )
        assert_polymer_mass_conservation(after)

        assert batch["status"] == "QUEUED", (
            f"a newly queued batch is QUEUED, got {batch['status']}"
        )
        assert batch["denier_actual"] is None, (
            f"denier_actual is null before spinning, got {batch['denier_actual']}"
        )

    def test_a_blend_batch_is_reachable_from_both_of_its_source_lots(self, api):
        """One batch drawing on two NYLON_66 lots is listed under ?polymer_lot_id and under
        ?blend_polymer_lot_id, and each lot reserves only its own leg of the draw.

        PRD: "Batches may be listed filtered by either source lot, using
        `polymer_lot_id` or `blend_polymer_lot_id`, and by `status` and `dye_method`."

        Design: Corner/entities/fiber_batch_blend_links_two_polymer_lots_and_both_reverse_lists_resolve
        """
        primary = validate_success(
            api.create_polymer_lot(_polymer_lot_payload("PL-N66-01"), EXTRUDER),
            expected_status=201,
        )
        blend = validate_success(
            api.create_polymer_lot(
                _polymer_lot_payload(
                    "PL-N66-02",
                    melt_flow_index=16.0,
                    recycled_content_pct=100.0,
                    segregated=True,
                    reclaim_source="POST_CONSUMER",
                ),
                EXTRUDER,
            ),
            expected_status=201,
        )

        batch = validate_success(
            api.create_fiber_batch(
                _fiber_batch_payload(
                    "FB-01",
                    primary["id"],
                    input_kg=3000.0,
                    blend_polymer_lot_id=blend["id"],
                    blend_input_kg=1000.0,
                ),
                EXTRUDER,
            ),
            expected_status=201,
        )
        assert batch["polymer_lot_id"] == primary["id"], (
            f"polymer_lot_id names the primary lot, got {batch['polymer_lot_id']}"
        )
        assert batch["blend_polymer_lot_id"] == blend["id"], (
            f"blend_polymer_lot_id names the second lot, got "
            f"{batch['blend_polymer_lot_id']}"
        )
        assert batch["status"] == "QUEUED", (
            f"a newly queued blend batch is QUEUED, got {batch['status']}"
        )
        assert_fiber_batch(batch)

        by_primary, primary_meta = validate_paginated(
            api.list_fiber_batches(
                EXTRUDER,
                params={"polymer_lot_id": primary["id"], "limit": 10, "offset": 0},
            )
        )
        assert primary_meta["total_count"] == 1, (
            f"the primary lot owns exactly one batch, got {primary_meta['total_count']}"
        )
        assert by_primary[0]["id"] == batch["id"], (
            f"?polymer_lot_id must resolve to FB-01, got {by_primary[0]['batch_code']}"
        )

        by_blend, blend_meta = validate_paginated(
            api.list_fiber_batches(
                EXTRUDER,
                params={"blend_polymer_lot_id": blend["id"], "limit": 10, "offset": 0},
            )
        )
        assert blend_meta["total_count"] == 1, (
            f"the blend lot owns exactly one batch, got {blend_meta['total_count']}"
        )
        assert by_blend[0]["id"] == batch["id"], (
            f"?blend_polymer_lot_id must resolve to FB-01, got {by_blend[0]['batch_code']}"
        )

        primary_after = validate_success(api.get_polymer_lot(primary["id"], EXTRUDER))
        assert primary_after["reserved_kg"] == pytest.approx(3000.000, **KG), (
            f"the primary lot reserves only its 3000.000 kg leg, got "
            f"{primary_after['reserved_kg']}"
        )
        assert primary_after["available_kg"] == pytest.approx(2000.000, **KG), (
            f"expected available_kg 2000.000 on the primary lot, got "
            f"{primary_after['available_kg']}"
        )

        blend_after = validate_success(api.get_polymer_lot(blend["id"], EXTRUDER))
        assert blend_after["reserved_kg"] == pytest.approx(1000.000, **KG), (
            f"the blend lot reserves only its 1000.000 kg leg, got "
            f"{blend_after['reserved_kg']}"
        )
        assert blend_after["available_kg"] == pytest.approx(4000.000, **KG), (
            f"expected available_kg 4000.000 on the blend lot, got "
            f"{blend_after['available_kg']}"
        )


class TestPolymerMassLedgerAndDenierGate:
    def test_the_four_buckets_walk_available_reserved_consumed_and_scrapped(self, api):
        """Two draws deplete a 5000.000 kg lot, scrapping a QUEUED batch returns 3000.000 kg
        and revives it, and extruding then scrapping the other batch walks 2000.000 kg
        from reserved to consumed to scrapped.

        PRD: "Scrapping a batch that has already been `SPUN` charges the mass off
        instead: for each source lot, the drawn mass is subtracted from `consumed_kg` and
        added to `scrapped_kg`"

        Design: Corner/calculations/polymer_buckets_walk_available_reserved_consumed_and_scrapped
        """
        lot_id = validate_success(
            api.create_polymer_lot(_polymer_lot_payload("PL-N66-01"), EXTRUDER),
            expected_status=201,
        )["id"]

        fb_a = validate_success(
            api.create_fiber_batch(
                _fiber_batch_payload("FB-A", lot_id, input_kg=2000.0), EXTRUDER
            ),
            expected_status=201,
        )
        fb_b = validate_success(
            api.create_fiber_batch(
                _fiber_batch_payload("FB-B", lot_id, input_kg=3000.0), EXTRUDER
            ),
            expected_status=201,
        )

        drawn = validate_success(api.get_polymer_lot(lot_id, EXTRUDER))
        assert drawn["available_kg"] == pytest.approx(0.000, **KG), (
            f"both draws take available_kg to 0.000, got {drawn['available_kg']}"
        )
        assert drawn["reserved_kg"] == pytest.approx(5000.000, **KG), (
            f"expected reserved_kg 5000.000 after both draws, got {drawn['reserved_kg']}"
        )
        assert drawn["status"] == "DEPLETED", (
            f"available_kg of exactly 0.000 flips the lot DEPLETED, got {drawn['status']}"
        )
        assert _buckets(drawn) == pytest.approx(5000.000, **KG), (
            f"conservation must hold after the draws, got {_buckets(drawn)}"
        )

        validate_success(
            api.disposition_fiber_batch(fb_b["id"], {"disposition": "SCRAP"}, EXTRUDER)
        )
        revived = validate_success(api.get_polymer_lot(lot_id, EXTRUDER))
        assert revived["available_kg"] == pytest.approx(3000.000, **KG), (
            f"scrapping the QUEUED FB-B returns 3000.000 kg, got {revived['available_kg']}"
        )
        assert revived["reserved_kg"] == pytest.approx(2000.000, **KG), (
            f"expected reserved_kg 2000.000 after the FB-B scrap, got "
            f"{revived['reserved_kg']}"
        )
        assert revived["scrapped_kg"] == pytest.approx(0.000, **KG), (
            f"a QUEUED scrap charges nothing to scrapped_kg, got {revived['scrapped_kg']}"
        )
        assert revived["status"] == "AVAILABLE", (
            f"returned mass flips the lot back to AVAILABLE, got {revived['status']}"
        )
        assert _buckets(revived) == pytest.approx(5000.000, **KG), (
            f"conservation must hold after the FB-B scrap, got {_buckets(revived)}"
        )

        validate_success(
            api.extrude_fiber_batch(
                fb_a["id"],
                {"throughput_g_per_min": 7200.0, "spin_speed_m_per_min": 750.0},
                EXTRUDER,
            )
        )
        spun = validate_success(api.get_polymer_lot(lot_id, EXTRUDER))
        assert spun["reserved_kg"] == pytest.approx(0.000, **KG), (
            f"spinning empties reserved_kg, got {spun['reserved_kg']}"
        )
        assert spun["consumed_kg"] == pytest.approx(2000.000, **KG), (
            f"expected consumed_kg 2000.000 after the FB-A extrude, got "
            f"{spun['consumed_kg']}"
        )
        assert spun["available_kg"] == pytest.approx(3000.000, **KG), (
            f"spinning does not touch available_kg, got {spun['available_kg']}"
        )
        assert _buckets(spun) == pytest.approx(5000.000, **KG), (
            f"conservation must hold after the extrude, got {_buckets(spun)}"
        )

        validate_success(
            api.disposition_fiber_batch(fb_a["id"], {"disposition": "SCRAP"}, EXTRUDER)
        )
        final = validate_success(api.get_polymer_lot(lot_id, EXTRUDER))
        assert final["consumed_kg"] == pytest.approx(0.000, **KG), (
            f"a SPUN scrap empties consumed_kg, got {final['consumed_kg']}"
        )
        assert final["scrapped_kg"] == pytest.approx(2000.000, **KG), (
            f"expected scrapped_kg 2000.000 after the FB-A scrap, got "
            f"{final['scrapped_kg']}"
        )
        assert final["available_kg"] == pytest.approx(3000.000, **KG), (
            f"spun mass is gone, so available_kg stays 3000.000, got "
            f"{final['available_kg']}"
        )
        assert _buckets(final) == pytest.approx(5000.000, **KG), (
            f"the four buckets must still sum to 5000.000, got {_buckets(final)}"
        )
        for bucket in ("available_kg", "reserved_kg", "consumed_kg", "scrapped_kg"):
            assert final[bucket] >= 0, (
                f"no bucket may hold a negative figure, got {bucket} {final[bucket]}"
            )
        assert final["status"] == "AVAILABLE", (
            f"3000.000 kg is available, so the lot reads AVAILABLE, got {final['status']}"
        )

        assert (
            validate_success(api.get_fiber_batch(fb_a["id"], EXTRUDER))["status"]
            == "SCRAPPED"
        ), "FB-A must be SCRAPPED after its disposition"
        assert (
            validate_success(api.get_fiber_batch(fb_b["id"], EXTRUDER))["status"]
            == "SCRAPPED"
        ), "FB-B must be SCRAPPED after its disposition"

    def test_the_denier_release_gate_is_inclusive_at_three_percent(self, api):
        """7416.0 g/min gives denier_actual 1236.0 — a deviation of exactly 0.03 — and
        releases, while 7422.0 g/min gives 1237.0 and is refused.

        PRD: "take the absolute difference between `denier_actual` and `denier_target`,
        divide it by `denier_target`, and require the result to be at most 0.03"

        Design: Corner/calculations/denier_release_gate_is_inclusive_at_three_percent_deviation
        """
        lot_id = validate_success(
            api.create_polymer_lot(
                _polymer_lot_payload("PL-N66-01", received_kg=8000.0), EXTRUDER
            ),
            expected_status=201,
        )["id"]
        fb_a = validate_success(
            api.create_fiber_batch(_fiber_batch_payload("FB-A", lot_id), EXTRUDER),
            expected_status=201,
        )
        fb_b = validate_success(
            api.create_fiber_batch(_fiber_batch_payload("FB-B", lot_id), EXTRUDER),
            expected_status=201,
        )

        spun_a = validate_success(
            api.extrude_fiber_batch(
                fb_a["id"],
                {"throughput_g_per_min": 7416.0, "spin_speed_m_per_min": 750.0},
                EXTRUDER,
            )
        )
        assert spun_a["denier_actual"] == pytest.approx(1236.0, abs=0.05), (
            f"expected denier_actual 1236.0 from 7416.0 g/min, got "
            f"{spun_a['denier_actual']}"
        )
        assert spun_a["extruded_kg"] == pytest.approx(3860.000, **KG), (
            f"expected extruded_kg 3860.000 from a 4000.000 kg draw, got "
            f"{spun_a['extruded_kg']}"
        )

        released = validate_success(
            api.disposition_fiber_batch(fb_a["id"], {"disposition": "RELEASE"}, EXTRUDER)
        )
        assert released["status"] == "RELEASED", (
            f"a deviation of exactly 0.03 is in tolerance, got status {released['status']}"
        )

        spun_b = validate_success(
            api.extrude_fiber_batch(
                fb_b["id"],
                {"throughput_g_per_min": 7422.0, "spin_speed_m_per_min": 750.0},
                EXTRUDER,
            )
        )
        assert spun_b["denier_actual"] == pytest.approx(1237.0, abs=0.05), (
            f"expected denier_actual 1237.0 from 7422.0 g/min, got "
            f"{spun_b['denier_actual']}"
        )

        validate_error(
            api.disposition_fiber_batch(
                fb_b["id"], {"disposition": "RELEASE"}, EXTRUDER
            ),
            "ERR_DENIER_OUT_OF_TOLERANCE",
        )
        refused = validate_success(api.get_fiber_batch(fb_b["id"], EXTRUDER))
        assert refused["status"] == "SPUN", (
            f"yarn outside the band stays SPUN, got {refused['status']}"
        )

        lot = validate_success(api.get_polymer_lot(lot_id, EXTRUDER))
        assert lot["consumed_kg"] == pytest.approx(8000.000, **KG), (
            f"both extrudes consume the whole lot, got consumed_kg {lot['consumed_kg']}"
        )
        assert lot["available_kg"] == pytest.approx(0.000, **KG), (
            f"expected available_kg 0.000, got {lot['available_kg']}"
        )
        assert lot["status"] == "DEPLETED", (
            f"available_kg of exactly 0.000 reads DEPLETED, got {lot['status']}"
        )


class TestFiberBatchLifecycle:
    def test_scrapped_is_terminal_for_both_disposition_and_extrude(self, api):
        """SCRAPPED admits no further transition: a second disposition and an extrude are
        both refused, and the compensating mass movement stays applied exactly once.

        PRD: "In both cases the batch's `status` becomes `SCRAPPED`, which is terminal,
        as is `CONSUMED`."

        Design: Corner/state_machines/disposition_on_scrapped_fiber_batch_returns_invalid_state
        """
        lot_id = validate_success(
            api.create_polymer_lot(_polymer_lot_payload("PL-N66-01"), EXTRUDER),
            expected_status=201,
        )["id"]
        batch_id = validate_success(
            api.create_fiber_batch(_fiber_batch_payload("FB-01", lot_id), EXTRUDER),
            expected_status=201,
        )["id"]
        scrapped = validate_success(
            api.disposition_fiber_batch(batch_id, {"disposition": "SCRAP"}, EXTRUDER)
        )
        assert scrapped["status"] == "SCRAPPED", (
            f"the setup scrap must land the batch in SCRAPPED, got {scrapped['status']}"
        )

        validate_error(
            api.disposition_fiber_batch(batch_id, {"disposition": "SCRAP"}, EXTRUDER),
            "ERR_INVALID_STATE",
        )
        validate_error(
            api.extrude_fiber_batch(
                batch_id,
                {"throughput_g_per_min": 7200.0, "spin_speed_m_per_min": 750.0},
                EXTRUDER,
            ),
            "ERR_INVALID_STATE",
        )

        batch = validate_success(api.get_fiber_batch(batch_id, EXTRUDER))
        assert batch["status"] == "SCRAPPED", (
            f"the refused calls leave the batch SCRAPPED, got {batch['status']}"
        )
        assert batch["denier_actual"] is None, (
            f"the refused extrude must not compute a denier, got {batch['denier_actual']}"
        )

        lot = validate_success(api.get_polymer_lot(lot_id, EXTRUDER))
        assert lot["available_kg"] == pytest.approx(5000.000, **KG), (
            f"the QUEUED scrap returned the mass exactly once, got available_kg "
            f"{lot['available_kg']}"
        )
        assert lot["reserved_kg"] == pytest.approx(0.000, **KG), (
            f"expected reserved_kg 0.000, got {lot['reserved_kg']}"
        )
        assert lot["scrapped_kg"] == pytest.approx(0.000, **KG), (
            f"a QUEUED scrap charges nothing to scrapped_kg, got {lot['scrapped_kg']}"
        )
        assert lot["consumed_kg"] == pytest.approx(0.000, **KG), (
            f"nothing was ever spun, so consumed_kg is 0.000, got {lot['consumed_kg']}"
        )
        assert lot["status"] == "AVAILABLE", (
            f"the revived lot reads AVAILABLE, got {lot['status']}"
        )

    def test_aborting_a_scheduled_run_hands_the_creel_back_to_released(self, api):
        """Abort returns the fiber batch from ALLOCATED to RELEASED so it is immediately
        schedulable again, while the polymer lot's consumed_kg stays 4000.000.

        PRD: "the run's `status` becomes `ABORTED`, which is terminal, its machine window
        is freed for subsequent overlap checks, and its fiber batch transitions
        `ALLOCATED` back to `RELEASED`"

        Design: Corner/state_machines/abort_scheduled_run_returns_fiber_batch_to_released
        """
        lot = fixtures.create_polymer_lot(lot_code="PL-N66-01")
        batch = fixtures.create_released_fiber_batch(lot["id"], batch_code="FB-01")
        style = fixtures.create_active_style(style_code="ST-SD-01")
        machine = fixtures.create_tufting_machine(
            machine_code="TM-01", changeover_minutes=0
        )
        first_run = fixtures.create_scheduled_run(
            style["id"], machine["id"], batch["id"], run_code="PR-01"
        )

        aborted = validate_success(
            api.abort_production_run(
                first_run["id"], {"reason": "order pulled"}, PLANNER
            )
        )
        assert aborted["status"] == "ABORTED", (
            f"abort drives the run to ABORTED, got {aborted['status']}"
        )

        handed_back = validate_success(api.get_fiber_batch(batch["id"], PLANNER))
        assert handed_back["status"] == "RELEASED", (
            f"the aborted run returns its creel to RELEASED, got {handed_back['status']}"
        )

        polymer = validate_success(api.get_polymer_lot(lot["id"], EXTRUDER))
        assert polymer["consumed_kg"] == pytest.approx(4000.000, **KG), (
            f"the fibre was already spun, so consumed_kg stays 4000.000, got "
            f"{polymer['consumed_kg']}"
        )
        assert polymer["available_kg"] == pytest.approx(1000.000, **KG), (
            f"expected available_kg 1000.000, got {polymer['available_kg']}"
        )

        second_run = validate_success(
            api.create_production_run(
                {
                    "run_code": "PR-02",
                    "style_id": style["id"],
                    "machine_id": machine["id"],
                    "fiber_batch_id": batch["id"],
                    "scheduled_start_utc": "2026-08-07T08:00:00Z",
                    "scheduled_end_utc": "2026-08-07T16:00:00Z",
                },
                PLANNER,
            ),
            expected_status=201,
        )
        assert second_run["status"] == "SCHEDULED", (
            f"the released batch is immediately schedulable, got {second_run['status']}"
        )
        rescheduled = validate_success(api.get_fiber_batch(batch["id"], PLANNER))
        assert rescheduled["status"] == "ALLOCATED", (
            f"scheduling PR-02 moves the batch to ALLOCATED, got {rescheduled['status']}"
        )

    def test_a_run_demands_a_released_batch_through_queued_and_spun(self, api):
        """Neither a QUEUED nor a SPUN batch may be creeled; the refusal only clears after
        the release disposition, and the refused runs never consume the run_code.

        PRD: "the run must find the batch in `RELEASED`, and a batch in any other status
        is refused with `ERR_FIBER_BATCH_NOT_RELEASED`"

        Design: Corner/errors/scheduling_a_run_on_an_unreleased_batch_returns_fiber_batch_not_released
        """
        lot_id = fixtures.create_polymer_lot(lot_code="PL-N66-01")["id"]
        batch_id = fixtures.create_fiber_batch(lot_id, batch_code="FB-01")["id"]
        style = fixtures.create_active_style(style_code="ST-SD-01")
        machine = fixtures.create_tufting_machine(
            machine_code="TM-01", changeover_minutes=0
        )
        run_payload = {
            "run_code": "PR-01",
            "style_id": style["id"],
            "machine_id": machine["id"],
            "fiber_batch_id": batch_id,
            "scheduled_start_utc": "2026-08-05T08:00:00Z",
            "scheduled_end_utc": "2026-08-05T16:00:00Z",
        }

        validate_error(
            api.create_production_run(run_payload, PLANNER),
            "ERR_FIBER_BATCH_NOT_RELEASED",
        )

        validate_success(
            api.extrude_fiber_batch(
                batch_id,
                {"throughput_g_per_min": 7200.0, "spin_speed_m_per_min": 750.0},
                EXTRUDER,
            )
        )
        validate_error(
            api.create_production_run(run_payload, PLANNER),
            "ERR_FIBER_BATCH_NOT_RELEASED",
        )

        validate_success(
            api.disposition_fiber_batch(batch_id, {"disposition": "RELEASE"}, EXTRUDER)
        )
        run = validate_success(
            api.create_production_run(run_payload, PLANNER), expected_status=201
        )
        assert run["status"] == "SCHEDULED", (
            f"a RELEASED batch schedules cleanly, got {run['status']}"
        )
        assert run["run_code"] == "PR-01", (
            "the two refusals must not have consumed the PR-01 run_code, but the third "
            f"create landed as {run['run_code']}"
        )

        batch = validate_success(api.get_fiber_batch(batch_id, PLANNER))
        assert batch["status"] == "ALLOCATED", (
            f"scheduling moves the batch to ALLOCATED, got {batch['status']}"
        )
        assert batch["denier_actual"] == pytest.approx(1200.0, abs=0.05), (
            f"expected denier_actual 1200.0, got {batch['denier_actual']}"
        )


class TestExtrusionFeedstockValidations:
    def test_blending_across_polymer_types_is_refused(self, api):
        """The blend gate reads the second lot's polymer_type: NYLON_66 + PET is refused
        while NYLON_66 + NYLON_66 is accepted, and mass moves only on the accepted draw.

        PRD: "the blend lot's `polymer_type` must equal the primary lot's
        `polymer_type`, and a mismatch is refused with `ERR_POLYMER_BLEND_INCOMPATIBLE`"

        Design: Corner/validations/blending_two_different_polymer_types_returns_blend_incompatible
        """
        lot_a = validate_success(
            api.create_polymer_lot(_polymer_lot_payload("PL-N66-A"), EXTRUDER),
            expected_status=201,
        )
        lot_b = validate_success(
            api.create_polymer_lot(_polymer_lot_payload("PL-N66-B"), EXTRUDER),
            expected_status=201,
        )
        lot_pet = validate_success(
            api.create_polymer_lot(
                _polymer_lot_payload("PL-PET", polymer_type="PET"), EXTRUDER
            ),
            expected_status=201,
        )

        validate_error(
            api.create_fiber_batch(
                _fiber_batch_payload(
                    "FB-BAD",
                    lot_a["id"],
                    input_kg=3000.0,
                    blend_polymer_lot_id=lot_pet["id"],
                    blend_input_kg=1000.0,
                    dye_method="PIECE_DYED_READY",
                    solution_color_code=None,
                ),
                EXTRUDER,
            ),
            "ERR_POLYMER_BLEND_INCOMPATIBLE",
        )
        pet_after_refusal = validate_success(api.get_polymer_lot(lot_pet["id"], EXTRUDER))
        assert pet_after_refusal["reserved_kg"] == pytest.approx(0.000, **KG), (
            f"the refused blend reserves nothing on the PET lot, got "
            f"{pet_after_refusal['reserved_kg']}"
        )

        good = validate_success(
            api.create_fiber_batch(
                _fiber_batch_payload(
                    "FB-GOOD",
                    lot_a["id"],
                    input_kg=3000.0,
                    blend_polymer_lot_id=lot_b["id"],
                    blend_input_kg=1000.0,
                    dye_method="PIECE_DYED_READY",
                    solution_color_code=None,
                ),
                EXTRUDER,
            ),
            expected_status=201,
        )
        assert good["blend_input_kg"] == pytest.approx(1000.000, **KG), (
            f"expected blend_input_kg 1000.000, got {good['blend_input_kg']}"
        )

        primary = validate_success(api.get_polymer_lot(lot_a["id"], EXTRUDER))
        assert primary["reserved_kg"] == pytest.approx(3000.000, **KG), (
            f"only the accepted create reserves on PL-N66-A, got "
            f"{primary['reserved_kg']}"
        )
        assert primary["available_kg"] == pytest.approx(2000.000, **KG), (
            f"expected available_kg 2000.000 on PL-N66-A, got {primary['available_kg']}"
        )
        blend = validate_success(api.get_polymer_lot(lot_b["id"], EXTRUDER))
        assert blend["available_kg"] == pytest.approx(4000.000, **KG), (
            f"expected available_kg 4000.000 on PL-N66-B, got {blend['available_kg']}"
        )

    def test_a_draw_is_gated_against_available_kg_not_received_kg(self, api):
        """Two 600.000 kg draws on a 1000.000 kg lot: the second is refused, while a draw
        of exactly the 400.000 kg remainder is admitted.

        PRD: "if `input_kg` exceeds the primary lot's `available_kg`, or
        `blend_input_kg` exceeds the blend lot's `available_kg`, the request is refused
        with `ERR_POLYMER_MASS_UNAVAILABLE`"

        Design: Corner/validations/drawing_more_mass_than_is_available_returns_mass_unavailable
        """
        lot_id = validate_success(
            api.create_polymer_lot(
                _polymer_lot_payload("PL-N66-01", received_kg=1000.0), EXTRUDER
            ),
            expected_status=201,
        )["id"]
        validate_success(
            api.create_fiber_batch(
                _fiber_batch_payload(
                    "FB-A",
                    lot_id,
                    input_kg=600.0,
                    dye_method="PIECE_DYED_READY",
                    solution_color_code=None,
                ),
                EXTRUDER,
            ),
            expected_status=201,
        )

        validate_error(
            api.create_fiber_batch(
                _fiber_batch_payload(
                    "FB-B",
                    lot_id,
                    input_kg=600.0,
                    dye_method="PIECE_DYED_READY",
                    solution_color_code=None,
                ),
                EXTRUDER,
            ),
            "ERR_POLYMER_MASS_UNAVAILABLE",
        )

        remainder = validate_success(
            api.create_fiber_batch(
                _fiber_batch_payload(
                    "FB-C",
                    lot_id,
                    input_kg=400.0,
                    dye_method="PIECE_DYED_READY",
                    solution_color_code=None,
                ),
                EXTRUDER,
            ),
            expected_status=201,
        )
        assert remainder["status"] == "QUEUED", (
            f"a draw of exactly the remainder is admitted, got {remainder['status']}"
        )

        lot = validate_success(api.get_polymer_lot(lot_id, EXTRUDER))
        assert lot["available_kg"] == pytest.approx(0.000, **KG), (
            f"expected available_kg 0.000 after 600.000 + 400.000, got "
            f"{lot['available_kg']}"
        )
        assert lot["reserved_kg"] == pytest.approx(1000.000, **KG), (
            f"expected reserved_kg 1000.000, got {lot['reserved_kg']}"
        )
        assert lot["status"] == "DEPLETED", (
            f"available_kg of exactly 0.000 reads DEPLETED, got {lot['status']}"
        )

        _, meta = validate_paginated(
            api.list_fiber_batches(
                EXTRUDER, params={"polymer_lot_id": lot_id, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 2, (
            f"only the two admitted batches were persisted, got {meta['total_count']}"
        )

    def test_solution_color_code_presence_is_bidirectional_on_a_style(self, api):
        """A SOLUTION_DYED style with no colour code and a PIECE_DYED style carrying one are
        both refused with the same route error rather than a malformed-request 400.

        PRD: "A solution-dyed style must carry a `solution_color_code` and a piece-dyed
        style must leave it null, with `ERR_DYE_METHOD_COLOR_MISMATCH` the penalty for
        either error."

        Design: Corner/validations/solution_color_code_presence_must_match_the_declared_dye_method
        """
        missing_colour = _style_payload("ST-A")
        del missing_colour["solution_color_code"]
        validate_error(
            api.create_style(missing_colour, PLANNER), "ERR_DYE_METHOD_COLOR_MISMATCH"
        )

        validate_error(
            api.create_style(
                _style_payload(
                    "ST-B", dye_method="PIECE_DYED", solution_color_code="SC-BEIGE-01"
                ),
                PLANNER,
            ),
            "ERR_DYE_METHOD_COLOR_MISMATCH",
        )

        _, meta = validate_paginated(
            api.list_styles(PLANNER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0, (
            f"neither refused style may be persisted, got total_count {meta['total_count']}"
        )

    def test_a_piece_dyed_ready_batch_may_not_carry_a_solution_color_code(self, api):
        """A PIECE_DYED_READY fiber batch that supplies solution_color_code is refused with
        the dyeing-route error, not a malformed-request 400.

        PRD: "Supplying a colour code without the solution-dyed method, or omitting it
        when the method is solution dyed, is refused with `ERR_DYE_METHOD_COLOR_MISMATCH`."

        Design: Corner/validations/solution_color_code_presence_must_match_the_declared_dye_method
        """
        lot_id = validate_success(
            api.create_polymer_lot(_polymer_lot_payload("PL-N66-01"), EXTRUDER),
            expected_status=201,
        )["id"]

        validate_error(
            api.create_fiber_batch(
                _fiber_batch_payload(
                    "FB-X",
                    lot_id,
                    input_kg=100.0,
                    dye_method="PIECE_DYED_READY",
                    solution_color_code="SC-BEIGE-01",
                ),
                EXTRUDER,
            ),
            "ERR_DYE_METHOD_COLOR_MISMATCH",
        )

        _, meta = validate_paginated(
            api.list_fiber_batches(EXTRUDER, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0, (
            f"the refused batch must not be persisted, got total_count "
            f"{meta['total_count']}"
        )

    def test_a_piece_dyed_style_refuses_a_solution_dyed_creel(self, api):
        """A run pairing a PIECE_DYED style with a SOLUTION_DYED batch is refused, the batch
        stays RELEASED, and a PIECE_DYED_READY batch then takes the same window.

        PRD: "a style whose `dye_method` is `PIECE_DYED` requires a fiber batch whose
        `dye_method` is `PIECE_DYED_READY`. A mismatch on either arm is refused with
        `ERR_DYE_METHOD_MISMATCH`."

        Design: Corner/validations/piece_dyed_style_with_solution_dyed_fiber_returns_dye_method_mismatch
        """
        lot_id = fixtures.create_polymer_lot(
            lot_code="PL-N66-01", received_kg=8000.0
        )["id"]
        solution_batch = fixtures.create_released_fiber_batch(
            lot_id,
            batch_code="FB-SD",
            dye_method="SOLUTION_DYED",
            solution_color_code="SC-BEIGE-01",
        )
        piece_batch = fixtures.create_released_fiber_batch(
            lot_id,
            batch_code="FB-PD",
            dye_method="PIECE_DYED_READY",
            solution_color_code=None,
        )
        style = fixtures.create_active_piece_dyed_style(style_code="ST-PD-01")
        machine = fixtures.create_tufting_machine(
            machine_code="TM-01", changeover_minutes=0
        )

        def run_payload(run_code, fiber_batch_id):
            return {
                "run_code": run_code,
                "style_id": style["id"],
                "machine_id": machine["id"],
                "fiber_batch_id": fiber_batch_id,
                "scheduled_start_utc": "2026-08-05T08:00:00Z",
                "scheduled_end_utc": "2026-08-05T16:00:00Z",
            }

        validate_error(
            api.create_production_run(
                run_payload("PR-BAD", solution_batch["id"]), PLANNER
            ),
            "ERR_DYE_METHOD_MISMATCH",
        )
        untouched = validate_success(api.get_fiber_batch(solution_batch["id"], PLANNER))
        assert untouched["status"] == "RELEASED", (
            f"the refused run must not allocate the batch, got {untouched['status']}"
        )

        run = validate_success(
            api.create_production_run(
                run_payload("PR-OK", piece_batch["id"]), PLANNER
            ),
            expected_status=201,
        )
        assert run["status"] == "SCHEDULED", (
            f"the compliant pairing schedules cleanly, got {run['status']}"
        )
        allocated = validate_success(api.get_fiber_batch(piece_batch["id"], PLANNER))
        assert allocated["status"] == "ALLOCATED", (
            f"scheduling moves the compliant batch to ALLOCATED, got "
            f"{allocated['status']}"
        )


class TestReclamationLine:
    def test_ten_thousand_pounds_of_nylon_66_yields_1562_172_kg(self, api):
        """Depolymerizing 10000.0 lb of NYLON_66 at contamination 5.0 yields exactly
        1562.172 kg and mints a segregated, fully recycled POST_CONSUMER lot.

        PRD: "Take `intake_lbs`, multiply it by the pound-to-kilogram factor 0.45359237,
        then multiply by the face-fiber fraction for the batch's `face_fiber_type` — 0.42
        for `NYLON_66`"

        Design: Corner/calculations/reclamation_yield_for_ten_thousand_pounds_of_nylon_66
        """
        batch_id = validate_success(
            api.create_reclamation_batch(
                {
                    "batch_code": "RB-01",
                    "intake_lbs": 10000.0,
                    "face_fiber_type": "NYLON_66",
                    "contamination_pct": 5.0,
                },
                EXTRUDER,
            ),
            expected_status=201,
        )["id"]

        batch = validate_success(
            api.depolymerize_reclamation_batch(batch_id, EXTRUDER)
        )
        assert batch["depolymerized_kg"] == pytest.approx(1562.172, **KG), (
            f"expected depolymerized_kg 1562.172 from 10000.0 lb of NYLON_66, got "
            f"{batch['depolymerized_kg']}"
        )
        assert batch["status"] == "DEPOLYMERIZED", (
            f"depolymerizing drives the batch to DEPOLYMERIZED, got {batch['status']}"
        )
        assert is_valid_uuid(batch["output_polymer_lot_id"] or ""), (
            f"output_polymer_lot_id must name the minted lot, got "
            f"{batch['output_polymer_lot_id']!r}"
        )
        assert_reclamation_batch(batch)

        data, meta = validate_paginated(
            api.list_polymer_lots(
                EXTRUDER,
                params={
                    "reclaim_source": "POST_CONSUMER",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1, (
            f"exactly one POST_CONSUMER lot was minted, got {meta['total_count']}"
        )
        minted = data[0]
        assert minted["id"] == batch["output_polymer_lot_id"], (
            "the minted lot must be the one named by output_polymer_lot_id"
        )
        assert minted["received_kg"] == pytest.approx(1562.172, **KG), (
            f"the minted lot takes received_kg from depolymerized_kg, got "
            f"{minted['received_kg']}"
        )
        assert minted["available_kg"] == pytest.approx(1562.172, **KG), (
            f"the minted lot's available_kg equals its received_kg, got "
            f"{minted['available_kg']}"
        )
        assert minted["recycled_content_pct"] == pytest.approx(100.00, abs=0.01), (
            f"a reclaimed lot is 100.00 percent recycled, got "
            f"{minted['recycled_content_pct']}"
        )
        assert minted["segregated"] is True, (
            f"a reclaimed lot is segregated, got {minted['segregated']}"
        )
        assert minted["reclaim_source"] == "POST_CONSUMER", (
            f"a reclaimed lot carries POST_CONSUMER, got {minted['reclaim_source']}"
        )
        assert minted["status"] == "AVAILABLE", (
            f"the minted lot is AVAILABLE, got {minted['status']}"
        )
        assert minted["polymer_type"] == "NYLON_66", (
            f"the minted lot takes its polymer_type from face_fiber_type, got "
            f"{minted['polymer_type']}"
        )

    def test_the_contamination_gate_is_inclusive_at_twelve_percent(self, api):
        """Both intakes log fine; at depolymerize 12.0 percent yields polymer while 12.1 is
        refused and leaves the batch in RECEIVED with no lot minted.

        PRD: "the batch's `contamination_pct` must be at most 12.0 percent, and a dirtier
        intake is refused with `ERR_RECLAIM_CONTAMINATION_EXCEEDED`"

        Design: Corner/validations/reclaim_contamination_gate_is_inclusive_at_twelve_percent
        """
        edge = validate_success(
            api.create_reclamation_batch(
                {
                    "batch_code": "RB-EDGE",
                    "intake_lbs": 10000.0,
                    "face_fiber_type": "NYLON_66",
                    "contamination_pct": 12.0,
                },
                EXTRUDER,
            ),
            expected_status=201,
        )
        dirty = validate_success(
            api.create_reclamation_batch(
                {
                    "batch_code": "RB-DIRTY",
                    "intake_lbs": 10000.0,
                    "face_fiber_type": "NYLON_66",
                    "contamination_pct": 12.1,
                },
                EXTRUDER,
            ),
            expected_status=201,
        )
        assert edge["status"] == "RECEIVED", (
            f"a newly logged intake is RECEIVED, got {edge['status']}"
        )
        assert dirty["status"] == "RECEIVED", (
            f"contamination is not a gate at intake, got {dirty['status']}"
        )

        validate_error(
            api.depolymerize_reclamation_batch(dirty["id"], EXTRUDER),
            "ERR_RECLAIM_CONTAMINATION_EXCEEDED",
        )
        refused = validate_success(api.get_reclamation_batch(dirty["id"], EXTRUDER))
        assert refused["status"] == "RECEIVED", (
            f"the refused batch stays RECEIVED, got {refused['status']}"
        )
        assert refused["depolymerized_kg"] == pytest.approx(0, **KG), (
            f"nothing was yielded, so depolymerized_kg is 0, got "
            f"{refused['depolymerized_kg']}"
        )
        assert refused["output_polymer_lot_id"] is None, (
            f"no lot may be minted for a refused batch, got "
            f"{refused['output_polymer_lot_id']!r}"
        )

        cleaned = validate_success(
            api.depolymerize_reclamation_batch(edge["id"], EXTRUDER)
        )
        assert cleaned["depolymerized_kg"] == pytest.approx(1562.172, **KG), (
            f"expected depolymerized_kg 1562.172 at exactly 12.0 percent, got "
            f"{cleaned['depolymerized_kg']}"
        )

        _, meta = validate_paginated(
            api.list_polymer_lots(
                EXTRUDER,
                params={
                    "reclaim_source": "POST_CONSUMER",
                    "limit": 10,
                    "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1, (
            f"only the admissible batch minted a lot, got {meta['total_count']}"
        )

    def test_a_roll_becomes_reclaimable_exactly_when_it_stops_being_scrappable(self, api):
        """While the roll is AVAILABLE it may be scrapped but not depolymerized; once the cut
        drives it DEPLETED it may be depolymerized but no longer scrapped.

        PRD: "its `inventory_status` must be either `DEPLETED` or `SCRAPPED` — because
        the mill will not grind up saleable inventory; a roll in any other inventory
        state is refused with `ERR_ROLL_NOT_RECLAIMABLE`"

        Design: Corner/errors/a_roll_becomes_reclaimable_exactly_when_it_stops_being_scrappable
        """
        ctx = fixtures.setup_available_solution_dyed_roll(
            roll_overrides={"roll_number": "RG-01", "initial_yards": 100.0},
            machine_overrides={"machine_code": "TM-01", "changeover_minutes": 0},
        )
        roll_id = ctx["roll_good"]["id"]
        account = fixtures.create_account(account_code="AC-01")
        order = fixtures.create_cut_order(
            account["id"],
            ctx["style"]["id"],
            order_code="CO-01",
            requested_yards=100.0,
            shade_tolerance="ANY",
        )

        batch_id = validate_success(
            api.create_reclamation_batch(
                {
                    "batch_code": "RB-01",
                    "intake_lbs": 5000.0,
                    "face_fiber_type": "NYLON_66",
                    "contamination_pct": 5.0,
                    "source_roll_good_id": roll_id,
                },
                EXTRUDER,
            ),
            expected_status=201,
        )["id"]

        validate_error(
            api.depolymerize_reclamation_batch(batch_id, EXTRUDER),
            "ERR_ROLL_NOT_RECLAIMABLE",
        )

        allocated = validate_success(api.allocate_cut_order(order["id"], PLANNER))
        assert allocated["allocated_yards"] == pytest.approx(100.0, **YARDS), (
            f"expected allocated_yards 100.0, got {allocated['allocated_yards']}"
        )

        cut = validate_success(api.cut_cut_order(order["id"], PLANNER))
        assert cut["status"] == "CUT", f"the order must be CUT, got {cut['status']}"
        depleted = validate_success(api.get_roll_good(roll_id, PLANNER))
        assert depleted["inventory_status"] == "DEPLETED", (
            f"a residual of exactly zero drives the parent DEPLETED, got "
            f"{depleted['inventory_status']}"
        )
        _, remnant_meta = validate_paginated(
            api.list_roll_goods(
                PLANNER, params={"parent_roll_id": roll_id, "limit": 10, "offset": 0}
            )
        )
        assert remnant_meta["total_count"] == 0, (
            f"a residual of exactly zero mints no remnant child, got "
            f"{remnant_meta['total_count']}"
        )

        validate_error(
            api.qa_disposition_roll_good(
                roll_id,
                {"disposition": "SCRAP"},
                fixtures.QA,
            ),
            "ERR_ROLL_ALREADY_DEPLETED",
        )
        after_scrap_attempt = validate_success(api.get_roll_good(roll_id, PLANNER))
        assert after_scrap_attempt["qa_status"] == "PASSED", (
            f"the refused scrap leaves qa_status PASSED, got "
            f"{after_scrap_attempt['qa_status']}"
        )

        reclaimed = validate_success(
            api.depolymerize_reclamation_batch(batch_id, EXTRUDER)
        )
        assert reclaimed["status"] == "DEPOLYMERIZED", (
            f"the depleted roll is now reclaimable, got {reclaimed['status']}"
        )
        assert reclaimed["source_roll_good_id"] == roll_id, (
            f"source_roll_good_id must still name the reclaimed roll, got "
            f"{reclaimed['source_roll_good_id']}"
        )
        assert is_valid_uuid(reclaimed["output_polymer_lot_id"] or ""), (
            f"the successful depolymerization mints a lot, got "
            f"{reclaimed['output_polymer_lot_id']!r}"
        )

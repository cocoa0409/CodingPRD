"""Layered interactions: stale version counters, a rolling budget at its edge, and one immediate cascade."""

import pytest

from test_helpers import (
    ApiErrorId,
    acknowledge_excursion,
    api_client,
    build_bank_scenario,
    commission_tank,
    cryopreserve,
    latest_excursion,
    make_registry_operator_headers,
    make_technologist_headers,
    make_transplant_center_headers,
    place_reservation,
    post_temperature_reading,
    publish_listing,
    read_listing,
    read_reservation,
    read_tank,
    read_unit,
    resolve_excursion,
    set_clock,
    unit_version,
    validate_error,
    validate_paginated,
    validate_success,
)


def _stored_private_unit_two_centres_are_watching():
    """A frozen private unit whose version both centres have just read."""
    scenario = build_bank_scenario(
        stage="cryopreserved",
        tank_code="TANK-A",
        capacity_slots=4,
        program_type="PRIVATE_FAMILY",
        consent_document_hash="hash-occ-v1",
        kit_lot_code="LOT-2026-O",
        courier_tracking_code="TRK-0930",
        slot_code="A-01",
    )
    scenario["shared_version"] = unit_version(
        scenario["unit"]["id"], make_transplant_center_headers("tc-001")
    )
    return scenario


def _second_hold_payload(unit_id, expected_version):
    """The rival centre's hold: a heavier patient and a window one clear day later."""
    return {
        "unit_id": unit_id,
        "requesting_center_name": "Center Two",
        "patient_weight_kg": 40.0,
        "patient_hla_match_count": 5,
        "hold_from": "2026-09-06T00:00:00Z",
        "hold_until": "2026-09-10T00:00:00Z",
        "expected_unit_version": expected_version,
    }


class TestASecondHoldBuiltOnAStaleRead:
    def test_the_stale_version_is_refused_before_the_window_buffer_is_consulted(self):
        """The rival window clears the 24-hour buffer exactly, so only the counter can refuse.

        "**Unit version currency** — `expected_unit_version` equals the addressed unit's current
        `version`, on reservation creation and registry-listing creation. Otherwise
        `ERR_STALE_UNIT_VERSION` (412)."

        "Because both comparisons are strict, a gap of exactly 24 hours between two windows touches
        the buffered edge without crossing it and is accepted, while a gap of 23 hours 59 minutes 59
        seconds is rejected."

        Design: Corner/cross_cutting_complexity_layers/corner_second_hold_built_on_a_stale_unit_read_is_rejected_then_accepted
        """
        scenario = _stored_private_unit_two_centres_are_watching()
        stale = scenario["shared_version"]

        first = place_reservation(
            scenario["unit"]["id"],
            center_user_id="tc-001",
            expected_unit_version=stale,
            requesting_center_name="Center One",
            patient_weight_kg=35.0,
            patient_hla_match_count=6,
            hold_from="2026-09-01T00:00:00Z",
            hold_until="2026-09-05T00:00:00Z",
        )
        assert first["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(2.86, abs=0.01)
        assert first["requesting_center_user_id"] == "tc-001"

        response = api_client.create_reservation(
            _second_hold_payload(scenario["unit"]["id"], stale),
            make_transplant_center_headers("tc-002"),
        )

        validate_error(response, ApiErrorId.ERR_STALE_UNIT_VERSION.value, 412)

    def test_the_retry_on_a_re_read_version_is_accepted_and_both_holds_stand(self):
        """One bump per accepted hold, and the availability axis never moves.

        "The row is created in `PENDING_CONFIRMATORY`, `requesting_center_user_id` is set from the
        acting centre's `X-User-ID`, `pre_cryo_dose_x1e7_per_kg` is computed and
        `dose_variant_applied` is set to `PRE_CRYO`, and the unit's `version` is incremented by
        one."

        Design: Corner/cross_cutting_complexity_layers/corner_second_hold_built_on_a_stale_unit_read_is_rejected_then_accepted
        """
        scenario = _stored_private_unit_two_centres_are_watching()
        stale = scenario["shared_version"]
        unit_id = scenario["unit"]["id"]
        rival = make_transplant_center_headers("tc-002")

        place_reservation(
            unit_id,
            center_user_id="tc-001",
            expected_unit_version=stale,
            requesting_center_name="Center One",
            patient_weight_kg=35.0,
            patient_hla_match_count=6,
            hold_from="2026-09-01T00:00:00Z",
            hold_until="2026-09-05T00:00:00Z",
        )
        api_client.create_reservation(_second_hold_payload(unit_id, stale), rival)

        fresh = unit_version(unit_id, rival)
        assert fresh == stale + 1

        retried = validate_success(
            api_client.create_reservation(_second_hold_payload(unit_id, fresh), rival), 201
        )
        assert retried["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(2.50, abs=0.01)
        assert retried["requesting_center_user_id"] == "tc-002"
        assert retried["dose_variant_applied"] == "PRE_CRYO"

        rows, meta = validate_paginated(
            api_client.list_reservations(rival, {"unit_id": unit_id})
        )
        assert meta["total_count"] == 2
        assert [row["status"] for row in rows] == [
            "PENDING_CONFIRMATORY",
            "PENDING_CONFIRMATORY",
        ]
        assert [row["requesting_center_user_id"] for row in rows] == ["tc-001", "tc-002"]

        unit = read_unit(unit_id, make_technologist_headers("tech-001"))
        assert unit["version"] == stale + 2
        assert unit["availability_status"] == "PRIVATE_STORED"


def _public_unit_whose_version_moved_twice_behind_the_desk():
    """A published then suspended public unit, and the desk's pre-publication version."""
    scenario = build_bank_scenario(
        stage="cryopreserved",
        tank_code="TANK-A",
        capacity_slots=4,
        program_type="PUBLIC_DONATION",
        hla_typing_consent=True,
        primary_parent_name="Dana Ruiz",
        collection_site_code="SITE-02",
        consent_document_hash="hash-occ2-v1",
        kit_lot_code="LOT-2026-Q",
        courier_tracking_code="TRK-0940",
        slot_code="A-01",
    )
    operator = make_registry_operator_headers("ro-001")
    scenario["stale_version"] = unit_version(scenario["unit"]["id"], operator)
    scenario["listing"] = publish_listing(scenario["unit"]["id"])
    scenario["listing"] = validate_success(
        api_client.suspend_registry_listing(
            scenario["listing"]["id"], {"suspension_note": "HLA re-typing"}, operator
        )
    )
    return scenario


class TestAPublicationBuiltOnAPreSuspensionRead:
    def test_the_stale_version_answers_before_the_live_listing_rung(self):
        """The same call with a fresh version is refused for a different, later reason.

        "A successful publication stamps `listed_at` from the logical clock, sets `listing_status`
        to `ACTIVE`, moves the unit `UNAVAILABLE → LISTED`, increments the unit's `version` by one,
        and freezes a `potency_grade` on the listing row."

        Design: Corner/cross_cutting_complexity_layers/corner_publication_built_on_a_pre_suspension_unit_read_is_rejected
        """
        scenario = _public_unit_whose_version_moved_twice_behind_the_desk()

        response = api_client.create_registry_listing(
            {
                "unit_id": scenario["unit"]["id"],
                "registry_code": "NMDP",
                "hla_a": "A*02:01",
                "hla_b": "B*08:01",
                "hla_drb1": "DRB1*03:01",
                "expected_unit_version": scenario["stale_version"],
            },
            make_registry_operator_headers("ro-001"),
        )

        validate_error(response, ApiErrorId.ERR_STALE_UNIT_VERSION.value, 412)

    def test_each_edge_bumped_the_counter_once_and_the_refusal_bumped_nothing(self):
        """Publication and suspension are two mutations, so the drift is exactly two.

        "The listing moves `ACTIVE → SUSPENDED` with `suspension_reason_code` set to
        `REGISTRY_HOLD`, the unit moves `LISTED → UNAVAILABLE` with its `version` incremented by
        one, and every hold on that unit in `PENDING_CONFIRMATORY` is cancelled with a
        `cancellation_reason_code` of `LISTING_SUSPENDED`."

        Design: Corner/cross_cutting_complexity_layers/corner_publication_built_on_a_pre_suspension_unit_read_is_rejected
        """
        scenario = _public_unit_whose_version_moved_twice_behind_the_desk()
        operator = make_registry_operator_headers("ro-001")

        api_client.create_registry_listing(
            {
                "unit_id": scenario["unit"]["id"],
                "registry_code": "NMDP",
                "hla_a": "A*02:01",
                "hla_b": "B*08:01",
                "hla_drb1": "DRB1*03:01",
                "expected_unit_version": scenario["stale_version"],
            },
            operator,
        )

        unit = read_unit(scenario["unit"]["id"], operator)
        assert unit["version"] == scenario["stale_version"] + 2
        assert unit["availability_status"] == "UNAVAILABLE"

        rows, meta = validate_paginated(
            api_client.list_unit_registry_listings(scenario["unit"]["id"], operator)
        )
        assert meta["total_count"] == 1
        assert rows[0]["listing_status"] == "SUSPENDED"


def _two_tanks_one_minute_apart_on_the_excursion_budget():
    """TANK-A carries 121 excursion minutes, TANK-B exactly 120, and both end online."""
    scenario = build_bank_scenario(
        stage="determined",
        tank_code="TANK-A",
        capacity_slots=4,
        program_type="PRIVATE_FAMILY",
        consent_document_hash="hash-budget-v1",
        kit_lot_code="LOT-2026-M",
        courier_tracking_code="TRK-0950",
    )
    post_temperature_reading(
        scenario["tank"]["id"], reading_c=-140.0, reading_at="2026-08-11T01:00:00Z"
    )
    first = latest_excursion(scenario["tank"]["id"])
    acknowledge_excursion(first["id"], "2026-08-11T01:05:00Z")
    scenario["excursion_a"] = resolve_excursion(first["id"], "NO_IMPACT", "2026-08-11T03:01:00Z")

    spare = commission_tank(tank_code="TANK-B", tank_class="STANDARD", capacity_slots=4)
    post_temperature_reading(spare["id"], reading_c=-140.0, reading_at="2026-08-11T03:05:00Z")
    second = latest_excursion(spare["id"])
    acknowledge_excursion(second["id"], "2026-08-11T03:10:00Z")
    scenario["excursion_b"] = resolve_excursion(second["id"], "NO_IMPACT", "2026-08-11T05:05:00Z")

    scenario["spare_tank"] = spare
    return scenario


class TestTheRollingExcursionBudgetAtItsEdge:
    def test_one_hundred_and_twenty_one_minutes_refuses_the_freeze(self):
        """The tank is online again, so operability cannot be the reason for the refusal.

        "**Rolling excursion budget** — on cryopreservation, the tank's
        `cumulative_excursion_minutes_30d` does not exceed 120 minutes; the comparison is strictly
        greater, so a tank sitting at exactly 120 still accepts units."

        "It stamps `resolved_at` from the logical clock and computes `duration_minutes` as the whole
        minutes from `detected_at` to `resolved_at`, discarding any partial minute."

        Design: Corner/cross_cutting_complexity_layers/corner_cumulative_excursion_budget_admits_exactly_120_minutes_and_refuses_121
        """
        scenario = _two_tanks_one_minute_apart_on_the_excursion_budget()
        assert scenario["excursion_a"]["duration_minutes"] == 121
        assert scenario["excursion_b"]["duration_minutes"] == 120

        crowded = read_tank(scenario["tank"]["id"])
        assert crowded["status"] == "ONLINE"
        assert crowded["cumulative_excursion_minutes_30d"] == 121

        set_clock("2026-08-11T05:10:00Z")
        response = api_client.cryopreserve_unit(
            scenario["unit"]["id"],
            {
                "tank_id": scenario["tank"]["id"],
                "slot_code": "A-01",
                "freeze_at": "2026-08-11T05:10:00Z",
            },
            make_technologist_headers("tech-001"),
        )

        validate_error(response, ApiErrorId.ERR_EXCURSION_LIMIT_EXCEEDED.value, 409)

        after = read_tank(scenario["tank"]["id"])
        assert after["occupied_slots"] == 0

    def test_exactly_one_hundred_and_twenty_minutes_still_admits_the_unit(self):
        """The neighbouring tank sits on the boundary and the same freeze succeeds there.

        "That rolling figure is the sum of `duration_minutes` over the tank's excursions whose
        `status` is `RESOLVED` or `CLOSED_LOSS` and whose `detected_at` falls inside the window
        running from 30 days before the logical clock to the logical clock, with both endpoints
        included."

        Design: Corner/cross_cutting_complexity_layers/corner_cumulative_excursion_budget_admits_exactly_120_minutes_and_refuses_121
        """
        scenario = _two_tanks_one_minute_apart_on_the_excursion_budget()
        spare = scenario["spare_tank"]

        set_clock("2026-08-11T05:10:00Z")
        api_client.cryopreserve_unit(
            scenario["unit"]["id"],
            {
                "tank_id": scenario["tank"]["id"],
                "slot_code": "A-01",
                "freeze_at": "2026-08-11T05:10:00Z",
            },
            make_technologist_headers("tech-001"),
        )

        frozen = cryopreserve(
            scenario["unit"]["id"],
            spare["id"],
            slot_code="B-01",
            freeze_at="2026-08-11T05:10:00Z",
        )
        assert frozen["processing_status"] == "CRYOPRESERVED"

        unit = read_unit(scenario["unit"]["id"], make_technologist_headers("tech-001"))
        assert unit["availability_status"] == "PRIVATE_STORED"
        assert unit["tank_id"] == spare["id"]
        assert unit["slot_code"] == "B-01"
        assert unit["cryopreserved_at"].startswith("2026-08-11T05:10:00")

        holder = read_tank(spare["id"])
        assert holder["status"] == "ONLINE"
        assert holder["cumulative_excursion_minutes_30d"] == 120
        assert holder["occupied_slots"] == 1


def _listed_public_unit_with_one_pending_hold():
    """A listed public unit, one hold against it, and the version read before either."""
    scenario = build_bank_scenario(
        stage="listed",
        tank_code="TANK-A",
        capacity_slots=4,
        program_type="PUBLIC_DONATION",
        hla_typing_consent=True,
        primary_parent_name="Dana Ruiz",
        collection_site_code="SITE-02",
        consent_document_hash="hash-cascade-v1",
        kit_lot_code="LOT-2026-C",
        courier_tracking_code="TRK-0960",
        slot_code="A-01",
    )
    scenario["version_before_hold"] = unit_version(
        scenario["unit"]["id"], make_transplant_center_headers("tc-001")
    )
    scenario["reservation"] = place_reservation(
        scenario["unit"]["id"],
        center_user_id="tc-001",
        requesting_center_name="Center One",
        patient_weight_kg=35.0,
        patient_hla_match_count=6,
        hold_from="2026-09-01T00:00:00Z",
        hold_until="2026-09-05T00:00:00Z",
    )
    return scenario


class TestTheSuspensionCascadeIsVisibleImmediately:
    def test_the_suspend_response_already_carries_the_post_cascade_listing(self):
        """No second call is needed to learn that the listing came off the market.

        "Each of these events must propagate deterministically to every artifact that depends on it
        — the unit's eligibility, its registry listing, the holds placed against it, the invoices
        billed for it — and each must be reversible in exactly the cases where the triggering
        condition is itself reversed."

        Design: Corner/consistency_model/corner_suspension_cascade_is_fully_visible_in_the_same_response
        """
        scenario = _listed_public_unit_with_one_pending_hold()
        assert scenario["listing"]["listing_status"] == "ACTIVE"
        assert scenario["reservation"]["status"] == "PENDING_CONFIRMATORY"

        suspended = validate_success(
            api_client.suspend_registry_listing(
                scenario["listing"]["id"],
                {"suspension_note": "registry audit in progress"},
                make_registry_operator_headers("ro-001"),
            )
        )

        assert suspended["listing_status"] == "SUSPENDED"
        assert suspended["suspension_reason_code"] == "REGISTRY_HOLD"
        assert suspended["potency_grade"] == "A"

    def test_the_next_reads_show_the_unit_demoted_and_the_hold_cancelled(self):
        """The clock never moves and no batch runs, so nothing may settle later.

        "Every cascade and every compensating reversal in this specification is therefore mandatory
        behaviour, not an implementation nicety."

        Design: Corner/consistency_model/corner_suspension_cascade_is_fully_visible_in_the_same_response
        """
        scenario = _listed_public_unit_with_one_pending_hold()
        operator = make_registry_operator_headers("ro-001")

        api_client.suspend_registry_listing(
            scenario["listing"]["id"], {"suspension_note": "registry audit in progress"}, operator
        )

        unit = read_unit(scenario["unit"]["id"], operator)
        assert unit["availability_status"] == "UNAVAILABLE"
        assert unit["processing_status"] == "CRYOPRESERVED"
        assert unit["eligibility_status"] == "ELIGIBLE"
        assert unit["version"] == scenario["version_before_hold"] + 2

        hold = read_reservation(scenario["reservation"]["id"])
        assert hold["status"] == "CANCELLED"
        assert hold["cancellation_reason_code"] == "LISTING_SUSPENDED"

        listing = read_listing(scenario["listing"]["id"])
        assert listing["listing_status"] == "SUSPENDED"
        assert listing["potency_grade"] == "A"

        rows, meta = validate_paginated(
            api_client.list_unit_registry_listings(scenario["unit"]["id"], operator)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == scenario["listing"]["id"]

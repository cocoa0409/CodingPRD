"""Case scheduling: pinning, room/surgeon conflicts, repin, cross-entity guards."""
import uuid

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_card_line,
    api_client,
    get_success_data,
    make_case,
    make_draft_card,
    make_published_card,
    make_supply_item,
    make_surgeon,
    publish_card,
    release_pick_list,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
ANY = TEST_USERS["any_headers"]


def _glove(**kw):
    # SKU must be unique across all items (PRD §3.1); tests calling this helper
    # more than once per server boot need a distinct SKU per call.
    defaults = dict(sku="GLOVE-PR-" + uuid.uuid4().hex[:8].upper(),
                    name="Gloves pair", unit_cost_cents=250,
                    substitute_group="GLOVES", initial_on_hand=100)
    defaults.update(kw)
    return make_supply_item(**defaults)


def _one_line_card(surgeon, procedure="TKA"):
    item = _glove()
    card = make_published_card(surgeon["id"], procedure,
                               [{"supply_item_id": item["id"], "quantity": 1}])
    return card, item


class TestRoomOverlap:
    def test_room_half_open_adjacency_allowed(self):
        """PRD §3.3: "A room conflict exists when the new case's half-open
        interval — from `scheduled_start` up to but not including
        `scheduled_start` plus `expected_duration_min` minutes — intersects the
        interval of any non-`CANCELLED` case in the same `room`; intervals that
        merely touch at an endpoint do not conflict."

        Design: Difficulty/resource_temporal_overlap/room_half_open_adjacency_allowed
        """
        s_a = make_surgeon(full_name="Dr. A", specialty="ORTHO")
        s_b = make_surgeon(full_name="Dr. B", specialty="CARD")
        card_a, _ = _one_line_card(s_a, "TKA")
        card_b, _ = _one_line_card(s_b, "CATH")
        make_case(s_a["id"], card_a["id"], scheduled_start="2026-09-02T08:00:00Z",
                  expected_duration_min=120, room="OR-1")
        resp = api_client.create_case(
            {"surgeon_id": s_b["id"], "card_id": card_b["id"],
             "scheduled_start": "2026-09-02T10:00:00Z",
             "expected_duration_min": 60, "room": "OR-1"},
            ANALYST,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SCHEDULED"

    def test_room_overlap_rejected(self):
        """PRD §3.3: "A violation is rejected with `ERR_ROOM_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/room_half_open_adjacency_allowed
        """
        s_a = make_surgeon(full_name="Dr. A", specialty="ORTHO")
        s_b = make_surgeon(full_name="Dr. B", specialty="CARD")
        card_a, _ = _one_line_card(s_a, "TKA")
        card_b, _ = _one_line_card(s_b, "CATH")
        make_case(s_a["id"], card_a["id"], scheduled_start="2026-09-02T08:00:00Z",
                  expected_duration_min=120, room="OR-1")
        resp = api_client.create_case(
            {"surgeon_id": s_b["id"], "card_id": card_b["id"],
             "scheduled_start": "2026-09-02T09:59:00Z",
             "expected_duration_min": 60, "room": "OR-1"},
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED)


class TestSurgeonTurnoverBuffer:
    def test_exactly_thirty_minute_gap_allowed(self):
        """PRD §3.3: "The surgeon then receives a mandatory 30-minute turnover
        buffer: if any non-`CANCELLED` case for the same surgeon ends less than
        30 minutes before the new case starts, or begins less than 30 minutes
        after the new case ends, scheduling is rejected with
        `ERR_SURGEON_SCHEDULE_CONFLICT`; a gap of exactly 30 minutes is
        permitted."

        Design: Difficulty/resource_temporal_overlap/surgeon_turnover_buffer_gap_required
        """
        s_c = make_surgeon(full_name="Dr. C", specialty="NEURO")
        card_c, _ = _one_line_card(s_c, "LAMINECTOMY")
        make_case(s_c["id"], card_c["id"], scheduled_start="2026-09-03T08:00:00Z",
                  expected_duration_min=120, room="OR-3")
        resp = api_client.create_case(
            {"surgeon_id": s_c["id"], "card_id": card_c["id"],
             "scheduled_start": "2026-09-03T10:30:00Z",
             "expected_duration_min": 60, "room": "OR-4"},
            ANALYST,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SCHEDULED"

    def test_fifteen_minute_gap_rejected(self):
        """PRD §3.3: "if any non-`CANCELLED` case for the same surgeon ends
        less than 30 minutes before the new case starts ... scheduling is
        rejected with `ERR_SURGEON_SCHEDULE_CONFLICT`"

        Design: Difficulty/resource_temporal_overlap/surgeon_turnover_buffer_gap_required
        """
        s_c = make_surgeon(full_name="Dr. C", specialty="NEURO")
        card_c, _ = _one_line_card(s_c, "LAMINECTOMY")
        make_case(s_c["id"], card_c["id"], scheduled_start="2026-09-03T08:00:00Z",
                  expected_duration_min=120, room="OR-3")
        resp = api_client.create_case(
            {"surgeon_id": s_c["id"], "card_id": card_c["id"],
             "scheduled_start": "2026-09-03T10:15:00Z",
             "expected_duration_min": 60, "room": "OR-5"},
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_SURGEON_SCHEDULE_CONFLICT)


class TestCrossEntityGuards:
    def test_case_card_surgeon_mismatch_rejected(self):
        """PRD §3.3: "the case's surgeon must equal the pinned card's surgeon
        (`ERR_CARD_SURGEON_MISMATCH`)"

        Design: Corner/validations/case_card_surgeon_mismatch_rejected
        """
        s_a = make_surgeon(full_name="Dr. A", specialty="ORTHO")
        s_b = make_surgeon(full_name="Dr. B", specialty="CARD")
        card_a, _ = _one_line_card(s_a, "TKA")
        resp = api_client.create_case(
            {"surgeon_id": s_b["id"], "card_id": card_a["id"],
             "scheduled_start": "2026-09-05T08:00:00Z",
             "expected_duration_min": 60, "room": "OR-1"},
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_CARD_SURGEON_MISMATCH)

    def test_card_create_for_inactive_surgeon_rejected(self):
        """PRD §3.1: "deactivation ... downstream guards immediately begin
        rejecting new work for that surgeon: creating a card, publishing a
        card, scheduling a case, or submitting a product request all fail with
        `ERR_SURGEON_INACTIVE`"

        Design: Corner/validations/card_create_for_inactive_surgeon_rejected
        """
        surgeon = make_surgeon(full_name="Dr. Off")
        get_success_data(api_client.deactivate_surgeon(surgeon["id"], ANALYST))
        resp = api_client.create_preference_card(
            {"surgeon_id": surgeon["id"], "procedure_name": "TKA"}, ANALYST
        )
        validate_error(resp, ApiErrorId.ERR_SURGEON_INACTIVE)


class TestReleaseBlockedOnSupersededCard:
    def _supersede_setup(self):
        """Card v1 published; case pinned to v1; v2 published (v1 SUPERSEDED)."""
        surgeon = make_surgeon(full_name="Dr. Pin")
        item = _glove()
        c1 = make_published_card(surgeon["id"], "TKA",
                                 [{"supply_item_id": item["id"], "quantity": 1}])
        case = make_case(surgeon["id"], c1["id"],
                         scheduled_start="2026-09-01T08:00:00Z",
                         expected_duration_min=60, room="OR-9")
        c2 = make_draft_card(surgeon["id"], "TKA")
        add_card_line(c2["id"], item["id"], quantity=2, designation="OPEN",
                      pick_sequence=1)
        publish_card(c2["id"])
        return surgeon, item, c1, c2, case

    def test_release_blocked_when_pinned_card_superseded(self):
        """PRD §3.2: "Cases already `SCHEDULED` against the superseded card
        keep their pin untouched — but their pick-list release will now fail
        with `ERR_PINNED_CARD_NOT_ACTIVE` until they are re-pinned"
        PRD §3.4: "A `SupplyChainAnalyst` may release only a `SCHEDULED` case
        ... whose pinned card is still `ACTIVE` (`ERR_PINNED_CARD_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/release_blocked_when_pinned_card_superseded
        """
        _, _, c1, _, case = self._supersede_setup()
        resp = api_client.release_pick_list(case["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_PINNED_CARD_NOT_ACTIVE)

    def test_superseded_card_status_and_pin_preserved(self):
        """PRD §3.2: "Cases already `SCHEDULED` against the superseded card
        keep their pin untouched"
        PRD §3.3: "The pin is frozen: publishing a newer card generation never
        advances an existing case's pin."

        Design: Difficulty/cross_entity_state_dependency/release_blocked_when_pinned_card_superseded
        """
        _, _, c1, _, case = self._supersede_setup()
        v1_after = get_success_data(api_client.get_preference_card(c1["id"], ANY))
        assert v1_after["status"] == "SUPERSEDED"
        case_after = get_success_data(api_client.get_case(case["id"], ANY))
        assert case_after["status"] == "SCHEDULED"
        assert case_after["pinned_card_version_number"] == 1
        # No pick list exists for the case.
        resp = api_client.list_pick_lists(ANY, params={"case_id": case["id"]})
        from test_helpers import validate_paginated
        _, meta = validate_paginated(resp)
        assert meta["total_count"] == 0


class TestRepin:
    def test_repin_released_case_returns_not_scheduled(self):
        """PRD §3.3: "Re-pinning is only possible while the case is
        `SCHEDULED` (`ERR_CASE_NOT_SCHEDULED` otherwise)"

        Design: Corner/state_machines/repin_released_case_returns_not_scheduled
        """
        surgeon = make_surgeon(full_name="Dr. Rep")
        card, _ = _one_line_card(surgeon)
        case = make_case(surgeon["id"], card["id"])
        release_pick_list(case["id"])
        case_after = get_success_data(api_client.get_case(case["id"], ANY))
        resp = api_client.repin_card(
            case["id"],
            {"card_id": card["id"],
             "expected_case_version": case_after["version"]},
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_SCHEDULED)

    def test_occ_repin_stale_version_rejected(self):
        """PRD §2.6: "Re-pinning a case to a different card requires
        `expected_case_version`, holding the case `version` the client last
        observed. A mismatch with the case's current `version` is likewise
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting/occ_repin_stale_version_rejected
        """
        surgeon = make_surgeon(full_name="Dr. Occ2")
        item = _glove()
        c1 = make_published_card(surgeon["id"], "TKA",
                                 [{"supply_item_id": item["id"], "quantity": 1}])
        case = make_case(surgeon["id"], c1["id"],
                         scheduled_start="2026-09-05T08:00:00Z",
                         expected_duration_min=60, room="OR-1")
        c2 = make_draft_card(surgeon["id"], "TKA")
        add_card_line(c2["id"], item["id"], quantity=2, designation="OPEN",
                      pick_sequence=1)
        publish_card(c2["id"])
        case_v = get_success_data(api_client.get_case(case["id"], ANY))["version"]
        ok = api_client.repin_card(
            case["id"], {"card_id": c2["id"], "expected_case_version": case_v},
            ANALYST,
        )
        repinned = validate_success(ok)
        assert repinned["pinned_card_version_number"] == 2
        # Second repin with stale version.
        resp = api_client.repin_card(
            case["id"], {"card_id": c2["id"], "expected_case_version": case_v},
            ANALYST,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestVersionPinning:
    def test_pin_keeps_case_on_superseded_card_until_repin(self):
        """PRD §3.3: "The pin is frozen: publishing a newer card generation
        never advances an existing case's pin."
        PRD §3.3: "A successful re-pin updates the pinned card, re-captures
        `pinned_card_version_number`, refreshes `procedure_name`, and
        increments the case's `version` by one."
        PRD §3.4: "the as-planned cost, being the sum over the snapshot lines
        of `qty_requested` multiplied by the snapshot `unit_cost_cents`"

        Design: Corner/cross_cutting/version_pin_keeps_case_on_superseded_card_until_repin
        """
        surgeon = make_surgeon(full_name="Dr. Pin2")
        item = _glove()
        c1 = make_published_card(surgeon["id"], "TKA",
                                 [{"supply_item_id": item["id"], "quantity": 1}])
        case = make_case(surgeon["id"], c1["id"],
                         scheduled_start="2026-09-05T08:00:00Z",
                         expected_duration_min=60, room="OR-1")
        c2 = make_draft_card(surgeon["id"], "TKA")
        add_card_line(c2["id"], item["id"], quantity=2, designation="OPEN",
                      pick_sequence=1)
        publish_card(c2["id"])

        before = get_success_data(api_client.get_case(case["id"], ANY))
        assert before["pinned_card_version_number"] == 1

        repin = api_client.repin_card(
            case["id"],
            {"card_id": c2["id"], "expected_case_version": before["version"]},
            ANALYST,
        )
        validate_success(repin)
        release_pick_list(case["id"])
        after = get_success_data(api_client.get_case(case["id"], ANY))
        assert after["pinned_card_version_number"] == 2
        assert after["standard_cost_cents"] == 500

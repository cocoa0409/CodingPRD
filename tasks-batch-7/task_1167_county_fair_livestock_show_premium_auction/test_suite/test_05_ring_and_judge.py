"""Ring scheduling and judge assignment: half-open ring overlap, the buffered
15-minute judge gap, qualification, slot start preconditions, slot OCC, and
judge/role authorization on placings (PRD §2.1, §2.9, §3.4).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_fair_to,
    api_client,
    assign_judge,
    build_show_state,
    create_class,
    create_fair,
    create_judge,
    create_ring_slot,
    create_ring_slot_payload,
    get_ring_slot,
    list_placings,
    make_judge_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin"]
CLERK = TEST_USERS["show_clerk"]
TREASURER = TEST_USERS["treasurer"]


def _assign_raw(slot_id, judge_id, expected_version):
    return api_client.assign_judge(slot_id, judge_id, expected_version, CLERK)


class TestRingTimeOverlap:
    def test_ring_slot_half_open_overlap_touching_allowed(self, api):
        """PRD §3.4: "Two slots sharing the same `ring_name` may not overlap
        under half-open semantics; touching intervals, where one slot's end
        equals the other's start, are allowed. An overlap is rejected with
        `ERR_RING_TIME_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/ring_slot_half_open_overlap_touching_allowed
        """
        fair = create_fair(name="Fair R8A")
        class_l = create_class(fair["id"], species="MARKET_LAMB",
                               class_code="LAMB-A", weight_min_lbs=90,
                               weight_max_lbs=120)
        class_g = create_class(fair["id"], species="MARKET_GOAT",
                               class_code="GOAT-A", weight_min_lbs=60,
                               weight_max_lbs=100)
        create_ring_slot(fair["id"], class_l["id"], ring_name="MAIN",
                         starts_at="2026-07-10T09:00:00Z",
                         ends_at="2026-07-10T10:00:00Z")

        overlap = api_client.create_ring_slot(
            create_ring_slot_payload(
                fair["id"], class_g["id"], ring_name="MAIN",
                starts_at="2026-07-10T09:30:00Z",
                ends_at="2026-07-10T10:30:00Z",
            ),
            CLERK,
        )
        validate_error(overlap, ApiErrorId.ERR_RING_TIME_CONFLICT)

        touching = api_client.create_ring_slot(
            create_ring_slot_payload(
                fair["id"], class_g["id"], ring_name="MAIN",
                starts_at="2026-07-10T10:00:00Z",
                ends_at="2026-07-10T11:00:00Z",
            ),
            CLERK,
        )
        created = validate_success(touching, 201)
        assert created["status"] == "SCHEDULED", (
            "touching at the boundary (end == start) is allowed"
        )

    def test_ring_overlap_only_within_same_ring_name(self, api):
        """PRD §3.4: "Two slots sharing the same `ring_name` may not overlap
        under half-open semantics; touching intervals, where one slot's end
        equals the other's start, are allowed. An overlap is rejected with
        `ERR_RING_TIME_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/ring_slot_half_open_overlap_touching_allowed
        """
        fair = create_fair(name="Fair R8A-ring")
        class_l = create_class(fair["id"], species="MARKET_LAMB",
                               class_code="LAMB-A", weight_min_lbs=90,
                               weight_max_lbs=120)
        class_g = create_class(fair["id"], species="MARKET_GOAT",
                               class_code="GOAT-A", weight_min_lbs=60,
                               weight_max_lbs=100)
        create_ring_slot(fair["id"], class_l["id"], ring_name="MAIN",
                         starts_at="2026-07-10T09:00:00Z",
                         ends_at="2026-07-10T10:00:00Z")
        other_ring = api_client.create_ring_slot(
            create_ring_slot_payload(
                fair["id"], class_g["id"], ring_name="SOUTH",
                starts_at="2026-07-10T09:30:00Z",
                ends_at="2026-07-10T10:30:00Z",
            ),
            CLERK,
        )
        created = validate_success(other_ring, 201)
        assert created["ring_name"] == "SOUTH", (
            "an overlapping interval in a different ring is not a conflict"
        )


class TestJudgeBufferedGap:
    def _fair_with_judge_and_first_slot(self, name):
        fair = create_fair(name=name)
        class_l = create_class(fair["id"], species="MARKET_LAMB",
                               class_code="LAMB-A", weight_min_lbs=90,
                               weight_max_lbs=120)
        class_ga = create_class(fair["id"], species="MARKET_GOAT",
                                class_code="GOAT-A", weight_min_lbs=60,
                                weight_max_lbs=100)
        class_gb = create_class(fair["id"], species="MARKET_GOAT",
                                class_code="GOAT-B", weight_min_lbs=100,
                                weight_max_lbs=130)
        judge = create_judge(fair["id"], full_name="Judge Jo",
                             qualified_species=["MARKET_LAMB", "MARKET_GOAT"])
        return fair, judge, (class_l, class_ga, class_gb)

    def test_judge_buffered_gap_conflict(self, api):
        """PRD §3.4: "And the judge's booked intervals must keep at least a
        15-minute gap between any two assignments — mere adjacency without
        that buffer is a conflict, rejected with `ERR_JUDGE_TIME_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/judge_buffered_gap_conflict
        """
        fair, judge, (class_l, class_ga, class_gb) = (
            self._fair_with_judge_and_first_slot("Fair R8B")
        )
        slot_a = create_ring_slot(fair["id"], class_l["id"], ring_name="MAIN",
                                  starts_at="2026-07-10T09:00:00Z",
                                  ends_at="2026-07-10T10:00:00Z")
        assign_judge(slot_a["id"], judge["id"])

        slot_b = create_ring_slot(fair["id"], class_ga["id"], ring_name="SOUTH",
                                  starts_at="2026-07-10T10:10:00Z",
                                  ends_at="2026-07-10T11:00:00Z")
        conflict = _assign_raw(slot_b["id"], judge["id"], slot_b["version"])
        validate_error(conflict, ApiErrorId.ERR_JUDGE_TIME_CONFLICT)

        slot_c = create_ring_slot(fair["id"], class_gb["id"], ring_name="NORTH",
                                  starts_at="2026-07-10T10:15:00Z",
                                  ends_at="2026-07-10T11:00:00Z")
        ok = _assign_raw(slot_c["id"], judge["id"], slot_c["version"])
        assigned = validate_success(ok, 200)
        assert assigned["judge_id"] == judge["id"], (
            "a gap of exactly 15 minutes satisfies the buffer"
        )

    def test_judge_buffered_gap_applies_in_reverse_order(self, api):
        """PRD §3.4: "And the judge's booked intervals must keep at least a
        15-minute gap between any two assignments — mere adjacency without
        that buffer is a conflict, rejected with `ERR_JUDGE_TIME_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/judge_buffered_gap_conflict
        """
        fair, judge, (class_l, class_ga, class_gb) = (
            self._fair_with_judge_and_first_slot("Fair R8B-rev")
        )
        slot_a = create_ring_slot(fair["id"], class_l["id"], ring_name="MAIN",
                                  starts_at="2026-07-10T10:00:00Z",
                                  ends_at="2026-07-10T11:00:00Z")
        assign_judge(slot_a["id"], judge["id"])

        # New slot ends 10 minutes before the existing one starts: conflict.
        slot_x = create_ring_slot(fair["id"], class_ga["id"], ring_name="SOUTH",
                                  starts_at="2026-07-10T09:30:00Z",
                                  ends_at="2026-07-10T09:50:00Z")
        conflict = _assign_raw(slot_x["id"], judge["id"], slot_x["version"])
        validate_error(conflict, ApiErrorId.ERR_JUDGE_TIME_CONFLICT)

        # New slot ends exactly 15 minutes before: allowed.
        slot_y = create_ring_slot(fair["id"], class_gb["id"], ring_name="NORTH",
                                  starts_at="2026-07-10T09:00:00Z",
                                  ends_at="2026-07-10T09:45:00Z")
        ok = _assign_raw(slot_y["id"], judge["id"], slot_y["version"])
        assert validate_success(ok, 200)["judge_id"] == judge["id"]


class TestJudgeAssignment:
    def test_judge_not_qualified_for_species_returns_error(self, api):
        """PRD §3.4: "The judge's `qualified_species` must include the species
        of the slot's class, otherwise `ERR_JUDGE_NOT_QUALIFIED` (HTTP 422)."

        Design: Corner/validations/judge_not_qualified_for_species_returns_error
        """
        fair = create_fair(name="Fair V10")
        cls = create_class(fair["id"], species="MARKET_LAMB",
                           class_code="LAMB-A", weight_min_lbs=90,
                           weight_max_lbs=120)
        judge = create_judge(fair["id"], full_name="Judge Jo",
                             qualified_species=["MARKET_SWINE"])
        slot = create_ring_slot(fair["id"], cls["id"])
        resp = _assign_raw(slot["id"], judge["id"], slot["version"])
        validate_error(resp, ApiErrorId.ERR_JUDGE_NOT_QUALIFIED)
        assert get_ring_slot(slot["id"])["judge_id"] is None

    def test_occ_assign_judge_stale_slot_version_returns_412(self, api):
        """PRD §2.9: "Assigning a judge to a ring slot
        (`POST /v1/ring-slots/{slotId}/assign-judge`) requires
        `expected_ring_slot_version` carrying the caller's last observed
        `version` of the slot; assignment advances the slot's `version`, and a
        stale value is likewise rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_assign_judge_stale_slot_version_returns_412
        """
        fair = create_fair(name="Fair X2")
        cls = create_class(fair["id"], species="MARKET_LAMB",
                           class_code="LAMB-A", weight_min_lbs=90,
                           weight_max_lbs=120)
        judge_jo = create_judge(fair["id"], full_name="Judge Jo",
                                qualified_species=["MARKET_LAMB"])
        judge_kip = create_judge(fair["id"], full_name="Judge Kip",
                                 qualified_species=["MARKET_LAMB"])
        slot = create_ring_slot(fair["id"], cls["id"])
        stale_version = slot["version"]

        assigned = validate_success(
            _assign_raw(slot["id"], judge_jo["id"], stale_version), 200
        )
        assert assigned["judge_id"] == judge_jo["id"]

        stale = _assign_raw(slot["id"], judge_kip["id"], stale_version)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert get_ring_slot(slot["id"])["judge_id"] == judge_jo["id"], (
            "the losing assignment must not overwrite the slot's judge"
        )


class TestSlotStartAndPlacingsAuthorization:
    def test_ring_slot_start_without_judge_returns_invalid_state(self, api):
        """PRD §3.4: "When the fair is `SHOWING`, the clerk starts a slot,
        moving it `SCHEDULED` → `IN_PROGRESS`; starting requires a judge to be
        assigned (else `ERR_INVALID_STATE`) and the `SHOWING` posture (else
        `ERR_POSTURE_FORBIDS`)."

        Design: Corner/state_machines/ring_slot_start_without_judge_returns_invalid_state
        """
        fair = create_fair(name="Fair S7")
        cls = create_class(fair["id"], species="MARKET_LAMB",
                           class_code="LAMB-A", weight_min_lbs=90,
                           weight_max_lbs=120)
        advance_fair_to(fair["id"], "SHOWING")
        slot = create_ring_slot(fair["id"], cls["id"])
        resp = api_client.start_slot(slot["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_ring_slot(slot["id"])["status"] == "SCHEDULED"

    def _showing_slot_with_two_judges(self, name):
        """LAMB-A with one classified entry; slot assigned to Judge Jo and
        started; Judge Kip also registered and lamb-qualified."""
        ctx = build_show_state(
            fair_overrides={"name": name},
            entries=[{"species": "MARKET_LAMB", "tag_number": "L-001",
                      "weight_lbs": 100}],
            classes=[{"species": "MARKET_LAMB", "class_code": "LAMB-A",
                      "weight_min_lbs": 90, "weight_max_lbs": 120,
                      "capacity": 5}],
            entry_class_map={0: 0},
            judges=[
                {"full_name": "Judge Jo",
                 "qualified_species": ["MARKET_LAMB"]},
                {"full_name": "Judge Kip",
                 "qualified_species": ["MARKET_LAMB"]},
            ],
            slots=[{"class_index": 0, "judge_index": 0}],
            advance_to="SHOWING",
        )
        return ctx

    def test_judge_cannot_place_unassigned_slot(self, api):
        """PRD §2.1: "When `X-User-Role` is `Judge`, `X-User-ID` is the `id`
        of the acting Judge record, and submitting or voiding placings is
        permitted only on ring slots whose `judge_id` equals `X-User-ID`; a
        mismatch on those operations is rejected with `ERR_NOT_ASSIGNED_JUDGE`
        (HTTP 403) rather than the generic forbidden error."

        Design: Corner/rbac/judge_cannot_place_unassigned_slot
        """
        ctx = self._showing_slot_with_two_judges("Fair B3")
        slot = ctx["slots"][0]
        entry_id = ctx["entries"][0]["id"]
        judge_kip = ctx["judges"][1]

        resp = api_client.submit_placings(
            slot["id"],
            [{"entry_id": entry_id, "rank": 1, "award": "NONE"}],
            make_judge_headers(judge_kip["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_JUDGE)
        assert list_placings() == [], "no placing may be persisted"
        assert get_ring_slot(slot["id"])["status"] == "IN_PROGRESS"

    def test_treasurer_cannot_submit_placings(self, api):
        """PRD §2.1: "Authorization is evaluated after authentication: a caller
        whose role is not permitted for the endpoint, or who fails an
        entity-backed ownership check, is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/treasurer_cannot_submit_placings
        """
        ctx = self._showing_slot_with_two_judges("Fair B4")
        slot = ctx["slots"][0]
        entry_id = ctx["entries"][0]["id"]

        resp = api_client.submit_placings(
            slot["id"],
            [{"entry_id": entry_id, "rank": 1, "award": "NONE"}],
            TREASURER,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert list_placings() == []

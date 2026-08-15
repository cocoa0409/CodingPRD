"""Specialty referrals: aggregate capacity, billed-cost rounding, chain of
custody, and vendor-ownership RBAC (PRD §2.1, §2.4, §3.3).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, assert_custody_event,
    make_subcontractor_contact_headers,
    setup_job_with_room, register_item, triage_item, get_item,
    create_subcontractor, get_subcontractor, create_referral, get_referral,
    transition_referral, dispatch_referral, receive_referral, return_referral,
    setup_dispatched_referral, append_custody_event,
)

PM = TEST_USERS["project_manager_headers"]
TECH = TEST_USERS["inventory_technician_headers"]


class TestSubcontractorAggregateCapacity:
    def _setup(self):
        """Subcontractor max_concurrent_referrals 1; ARTWORK items X and Y triaged
        SALVAGEABLE; referral R1 for X already DISPATCHED (count == 1)."""
        sub = create_subcontractor(name="FineArt Pros",
                                   specialty_types=["ART_CONSERVATION"],
                                   max_concurrent_referrals=1)
        job, room = setup_job_with_room(
            job_overrides={"claim_number": "CLM-RO2", "property_address": "32 Walnut Ave"},
            room_overrides={"name": "Gallery"})
        item_x = register_item(room["id"], barcode="BC-RO2X",
                               description="Oil painting X", item_category="ARTWORK",
                               declared_value_cents=500000, volume_cu_ft=3)
        triage_item(item_x["id"], item_x["version"], "SALVAGEABLE")
        item_y = register_item(room["id"], barcode="BC-RO2Y",
                               description="Oil painting Y", item_category="ARTWORK",
                               declared_value_cents=400000, volume_cu_ft=3)
        triage_item(item_y["id"], item_y["version"], "SALVAGEABLE")
        r1 = create_referral(item_x["id"], sub["id"], quoted_cost_cents=5000)
        r1 = dispatch_referral(r1["id"])
        assert r1["status"] == "DISPATCHED"
        r2 = create_referral(item_y["id"], sub["id"], quoted_cost_cents=6000)
        return sub, item_y, r1, r2

    def test_dispatch_at_aggregate_capacity_rejected(self, api):
        """PRD §3.3: "the subcontractor's `active_referral_count` must be below its
        `max_concurrent_referrals` capacity, otherwise
        `ERR_SUBCONTRACTOR_AT_CAPACITY`."
        PRD §3.3: "The capacity counter counts a vendor's referrals in
        `DISPATCHED`, `IN_CUSTODY`, or `QA_REJECTED` status"

        Design: Difficulty/resource_temporal_overlap/subcontractor_concurrent_capacity_aggregate
        """
        _sub, _item_y, _r1, r2 = self._setup()

        res = api.transition_specialty_referral(r2["id"], {"action": "DISPATCH"}, PM)
        validate_error(res, ApiErrorId.ERR_SUBCONTRACTOR_AT_CAPACITY, expected_status=422)

        assert get_referral(r2["id"])["status"] == "DRAFT", (
            "the rejected dispatch must leave R2 in DRAFT")

    def test_freed_slot_allows_next_dispatch(self, api):
        """PRD §3.3: "Receipt and return of the physical item are performed by a
        `SubcontractorContact` whose identity is the vendor itself: receipt moves
        the referral from `DISPATCHED` to `IN_CUSTODY`, and return moves it from
        `IN_CUSTODY` to `RETURNED`, freeing the vendor's slot by decrementing
        `active_referral_count` by one."

        Design: Difficulty/resource_temporal_overlap/subcontractor_concurrent_capacity_aggregate
        """
        sub, _item_y, r1, r2 = self._setup()

        blocked = api.transition_specialty_referral(r2["id"], {"action": "DISPATCH"}, PM)
        validate_error(blocked, ApiErrorId.ERR_SUBCONTRACTOR_AT_CAPACITY, expected_status=422)

        receive_referral(r1["id"], sub["id"])
        returned = return_referral(r1["id"], sub["id"])
        assert returned["status"] == "RETURNED"

        r2_after = dispatch_referral(r2["id"])
        assert r2_after["status"] == "DISPATCHED", (
            "with R1 RETURNED the slot is free and R2 must dispatch")

        sub_after = get_subcontractor(sub["id"])
        assert sub_after["active_referral_count"] == 1, (
            f"only R2 occupies a slot now, expected 1, got {sub_after['active_referral_count']}")


class TestSpecialtyBilledCost:
    def test_specialty_billed_cost_rounding(self, api):
        """PRD §3.3: "Acceptance moves it to the terminal `QA_ACCEPTED` state,
        computes `billed_cost_cents` as the `quoted_cost_cents` scaled by
        `markup_pct` percent — that is, the quote multiplied by one hundred plus
        the markup percentage, divided by one hundred, rounded half-up once at the
        end — and returns the item to `CLEANED`."

        Design: Corner/calculations/specialty_billed_cost_rounding
        """
        ctx = setup_dispatched_referral(
            item_overrides={"barcode": "BC-CA2", "description": "Canvas",
                            "item_category": "ARTWORK", "declared_value_cents": 300000,
                            "volume_cu_ft": 2},
            sub_overrides={"name": "FineArt Pros",
                           "specialty_types": ["ART_CONSERVATION"],
                           "max_concurrent_referrals": 5},
            referral_overrides={"quoted_cost_cents": 10001})
        ref, sub, item = ctx["referral"], ctx["sub"], ctx["item"]
        assert ref["markup_pct"] == 15, "markup_pct defaults to 15"

        receive_referral(ref["id"], sub["id"])
        return_referral(ref["id"], sub["id"])
        accepted = get_success_data(
            api.transition_specialty_referral(ref["id"], {"action": "QA_ACCEPT"}, PM))

        assert accepted["status"] == "QA_ACCEPTED"
        assert accepted["billed_cost_cents"] == 11501, (
            f"round_half_up(10001 * 115 / 100) = 11501, got {accepted['billed_cost_cents']}")
        assert get_item(item["id"])["processing_status"] == "CLEANED"


class TestCustodyChain:
    def _setup_one_event(self):
        ctx = setup_dispatched_referral(
            item_overrides={"barcode": "BC-EN4", "description": "Ledger books",
                            "item_category": "DOCUMENT", "declared_value_cents": 2000,
                            "volume_cu_ft": 4},
            sub_overrides={"name": "DocDry",
                           "specialty_types": ["DOCUMENT_FREEZE_DRYING"],
                           "max_concurrent_referrals": 3},
            referral_overrides={"specialty_type": "DOCUMENT_FREEZE_DRYING",
                                "quoted_cost_cents": 8000})
        return ctx

    def test_custody_event_immutable_no_version_field(self, api):
        """PRD §2.4: "The single exception is the custody event: a `CustodyEvent`
        carries `id` and `created_at` only — both `updated_at` and `version` are
        absent from it, because custody events are append-only and never mutated
        after creation."
        PRD §3.3: "Each event receives a per-referral `sequence` starting at 1 and
        increasing monotonically in append order"
        PRD §3.3: each event "is bound to its referral through a server-set
        `referral_id` taken from the creation path, and carries an `event_type` of
        `PICKED_UP`, `IN_TRANSIT`, `RECEIVED_BY_SUB`, `RETURNED_BY_SUB`, or
        `RECEIVED_BACK`, an `event_at` timestamp, an `actor_name`, and an optional
        `note`."

        Design: Corner/entities/custody_event_immutable_no_version_field
        """
        ctx = self._setup_one_event()
        ref = ctx["referral"]
        created = append_custody_event(
            ref["id"], event_type="PICKED_UP",
            event_at="2026-08-05T10:00:00Z", actor_name="tech-1")
        assert created["sequence"] == 1, f"first event has sequence 1, got {created['sequence']}"

        events = get_success_data(api.list_custody_events(ref["id"], PM))
        assert len(events) == 1
        ev = events[0]
        assert_custody_event(ev)
        assert ev["referral_id"] == ref["id"]
        assert ev["event_type"] == "PICKED_UP"
        # PRD pins that the event carries the submitted event_at instant (the
        # strictly-increasing ordering rule depends on it) but does not pin the
        # string serialization of this client-supplied timestamp — compare
        # instants, not strings.
        from datetime import datetime
        def _instant(ts):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert _instant(ev["event_at"]) == _instant("2026-08-05T10:00:00Z"), (
            f"the stored event_at must be the submitted instant, got {ev['event_at']}")
        assert ev["actor_name"] == "tech-1"
        assert "version" not in ev and "updated_at" not in ev, (
            "append-only events carry neither version nor updated_at")

    def test_custody_event_out_of_order_rejected(self, api):
        """PRD §3.3: "The `event_at` of each new event must be strictly greater
        than every prior `event_at` on the same referral; an out-of-order append is
        rejected with `ERR_CUSTODY_EVENT_OUT_OF_ORDER`."

        Design: Corner/validations/custody_event_out_of_order_rejected
        """
        ctx = self._setup_one_event()
        ref = ctx["referral"]
        append_custody_event(ref["id"], event_type="PICKED_UP",
                             event_at="2026-08-10T10:00:00Z", actor_name="tech-1")

        res = api.create_custody_event(ref["id"], {
            "event_type": "IN_TRANSIT", "event_at": "2026-08-10T09:00:00Z",
            "actor_name": "tech-2"}, TECH)
        validate_error(res, ApiErrorId.ERR_CUSTODY_EVENT_OUT_OF_ORDER, expected_status=422)

        events = get_success_data(api.list_custody_events(ref["id"], PM))
        assert len(events) == 1, (
            f"the rejected append must leave no trace, got {len(events)} events")


class TestReferralOwnership:
    def test_subcontractor_contact_cannot_act_on_other_vendors_referral(self, api):
        """PRD §2.1: "When `X-User-Role` is `SubcontractorContact`, by contrast,
        `X-User-ID` is the `id` of the acting `Subcontractor`; any action on a
        specialty referral compares the referral's `subcontractor_id` to
        `X-User-ID`, and a mismatch is rejected with
        `ERR_NOT_REFERRAL_SUBCONTRACTOR`."

        Design: Corner/rbac/subcontractor_contact_cannot_act_on_other_vendors_referral
        """
        sub_a = create_subcontractor(name="Vendor A", specialty_types=["FUR_CLEANING"],
                                     max_concurrent_referrals=5)
        sub_b = create_subcontractor(name="Vendor B", specialty_types=["FUR_CLEANING"],
                                     max_concurrent_referrals=5)
        job, room = setup_job_with_room(
            job_overrides={"claim_number": "CLM-RB2", "property_address": "88 Cherry St"},
            room_overrides={"name": "Closet", "room_type": "BEDROOM"})
        item = register_item(room["id"], barcode="BC-RB2", description="Fur coat",
                             item_category="TEXTILE", declared_value_cents=80000,
                             volume_cu_ft=3)
        triage_item(item["id"], item["version"], "SALVAGEABLE")
        ref = create_referral(item["id"], sub_a["id"],
                              specialty_type="FUR_CLEANING", quoted_cost_cents=7000)
        ref = dispatch_referral(ref["id"])
        assert ref["status"] == "DISPATCHED"

        res = api.transition_specialty_referral(
            ref["id"], {"action": "RECEIVE"},
            make_subcontractor_contact_headers(sub_b["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_REFERRAL_SUBCONTRACTOR, expected_status=403)

        assert get_referral(ref["id"])["status"] == "DISPATCHED", (
            "vendor B's rejected RECEIVE must not move vendor A's referral")

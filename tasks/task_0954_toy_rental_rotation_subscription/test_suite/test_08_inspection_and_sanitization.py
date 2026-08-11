"""Inspection fee aggregation (per-component rounding order, the per-item
cap), copy disposition and grade degradation, the 24-hour sanitization buffer,
and the inspect -> fee -> ledger -> suspension cascade."""

from test_helpers import (
    OPS,
    ApiErrorId,
    assert_same_instant,
    create_box_create_payload,
    create_inspection_payload,
    inspection_record,
    list_item_fees,
    make_member_headers,
    read_box_item,
    read_copy,
    read_member,
    read_subscription,
    set_clock,
    setup_received_box,
    setup_two_item_received_box,
    validate_error,
    validate_success,
)


class TestInspectionFeeRounding:
    def _setup(self, api):
        return setup_two_item_received_box(
            member_email="m.insp@x.com",
            item_specs=[
                {"barcode": "BC-INSP-A",
                 "item": {"title": "Puzzle A", "piece_count": 3,
                          "retail_value_cents": 2000, "replacement_value_cents": 999}},
                {"barcode": "BC-INSP-B",
                 "item": {"title": "Puzzle B", "piece_count": 3,
                          "retail_value_cents": 2000, "replacement_value_cents": 1001}},
            ],
            received_at="2026-05-10T00:00:00Z",
            return_in_transit_at="2026-05-09T00:00:00Z",
        )

    def _inspect(self, api, ctx):
        records = [
            inspection_record(ctx["items"][0]["id"], condition_returned="GOOD",
                              damage_severity="MODERATE", missing_piece_count=1),
            inspection_record(ctx["items"][1]["id"], condition_returned="GOOD",
                              damage_severity="MINOR", missing_piece_count=1),
        ]
        return inspect_box_api(api, ctx["box"]["id"], records)

    def test_inspection_fees_round_per_component_per_item(self, api):
        """PRD §2.7: "Inspection fees round each fee component per item first
        and only then sum the already-rounded components; summing raw values
        and rounding once at the end yields different cents and is incorrect."
        PRD §3.6: "The damage component is the item's `replacement_value_cents`
        multiplied by the severity rate — 15% for `MINOR`, 35% for `MODERATE`,
        75% for `SEVERE`, and nothing when severity is `NONE` — rounded half up
        to whole cents. The missing-piece component is
        `replacement_value_cents` multiplied by the ratio of
        `missing_piece_count` to the catalog item's `piece_count`, likewise
        rounded half up, and only when pieces are actually missing."

        Item A: round_half_up(999 x 0.35) = round_half_up(349.65) = 350 DAMAGE;
        round_half_up(999 x 1/3) = round_half_up(333.0) = 333 MISSING_PIECES.
        Item B: round_half_up(1001 x 0.15) = round_half_up(150.15) = 150;
        round_half_up(1001/3) = round_half_up(333.67) = 334.
        Box total 350 + 333 + 150 + 334 = 1167 (sum-then-round would give
        1166 — a one-cent observable divergence).

        Design: Difficulty/combinatorial_formula/inspection_fee_per_item_rounding_mode_b
        """
        ctx = self._setup(api)
        self._inspect(api, ctx)
        member = ctx["member"]

        fees_a = list_item_fees(ctx["items"][0]["id"], member)
        by_type_a = {f["fee_type"]: f["amount_cents"] for f in fees_a}
        assert by_type_a == {"DAMAGE": 350, "MISSING_PIECES": 333}

        fees_b = list_item_fees(ctx["items"][1]["id"], member)
        by_type_b = {f["fee_type"]: f["amount_cents"] for f in fees_b}
        assert by_type_b == {"DAMAGE": 150, "MISSING_PIECES": 334}

        total = sum(f["amount_cents"] for f in fees_a + fees_b)
        assert total == 1167
        for fee in fees_a + fees_b:
            assert fee["status"] == "INVOICED"

    def test_inspection_side_effects_wallet_copies_and_box(self, api):
        """PRD §3.6: "Every emitted fee starts `INVOICED`, appends a
        `FEE_CHARGE` ledger entry against the member's wallet, and triggers the
        wallet recompute — suspension toggle included."
        PRD §3.6: "A restocked copy moves `RETURNED` → `SANITIZING`, stamps
        `sanitization_started_at` with the logical clock, and degrades its
        `condition_grade` to the worse of its current grade and the recorded
        `condition_returned`, on the scale where `NEW` beats `GOOD` beats
        `FAIR` beats `WORN`."
        PRD §3.6: "the box moves `RECEIVED` → `INSPECTED` automatically the
        moment every `PENDING_RETURN` item has an inspection record"

        Design: Difficulty/combinatorial_formula/inspection_fee_per_item_rounding_mode_b
        """
        ctx = self._setup(api)
        box_after = self._inspect(api, ctx)
        member = ctx["member"]

        assert read_member(member["id"])["wallet_credit_cents"] == -1167
        assert box_after["status"] == "INSPECTED"

        for i in range(2):
            copy_now = read_copy(ctx["copies"][i]["id"])
            assert copy_now["status"] == "SANITIZING"
            assert copy_now["condition_grade"] == "GOOD"  # worse(NEW, GOOD)
            item_now = read_box_item(ctx["items"][i]["id"], member)
            assert item_now["loan_status"] == "RETURNED"
            assert item_now["condition_returned"] == "GOOD"
            assert item_now["resolution_status"] == "FEE_ASSESSED"


class TestPerItemFeeCap:
    def test_cap_reduces_missing_pieces_damage_ranks_first(self, api):
        """PRD §3.6: "A per-item cap then applies to the pair: when the two
        components together exceed `replacement_value_cents`, the
        `MISSING_PIECES` fee is reduced so the two sum exactly to the
        replacement value — the `DAMAGE` fee ranks first and is never capped."

        SEVERE damage on replacement 1000 -> round_half_up(1000 x 0.75) = 750;
        one missing piece of two -> round_half_up(1000 x 1/2) = 500; the raw
        pair 1250 exceeds 1000, so MISSING_PIECES is reduced to 250.

        Design: Corner/calculations/per_item_fee_cap_damage_ranks_first
        """
        ctx = setup_received_box(
            member_email="m.cap@x.com",
            item_overrides={"title": "Teapot", "piece_count": 2,
                            "retail_value_cents": 1500,
                            "replacement_value_cents": 1000},
            barcode="BC-CAP-1",
            received_at="2026-05-10T00:00:00Z",
            return_in_transit_at="2026-05-09T00:00:00Z",
        )
        records = [inspection_record(ctx["item"]["id"], condition_returned="WORN",
                                     damage_severity="SEVERE", missing_piece_count=1)]
        validate_success(api.inspect_box(ctx["box"]["id"],
                                         create_inspection_payload(records), OPS))

        fees = list_item_fees(ctx["item"]["id"], ctx["member"])
        by_type = {f["fee_type"]: f["amount_cents"] for f in fees}
        assert by_type == {"DAMAGE": 750, "MISSING_PIECES": 250}
        assert sum(by_type.values()) == 1000
        assert read_member(ctx["member"]["id"])["wallet_credit_cents"] == -1000


class TestSanitizationBuffer:
    def _setup_sanitizing_copy(self, api):
        ctx = setup_received_box(member_email="m.san@x.com", barcode="BC-SAN-1",
                                 item_overrides={"title": "Bath Boat", "piece_count": 2,
                                                 "retail_value_cents": 4000,
                                                 "replacement_value_cents": 3000},
                                 received_at="2026-05-08T00:00:00Z",
                                 return_in_transit_at="2026-05-07T00:00:00Z")
        set_clock("2026-05-10T00:00:00Z")
        records = [inspection_record(ctx["item"]["id"], condition_returned="GOOD",
                                     damage_severity="NONE", missing_piece_count=0)]
        validate_success(api.inspect_box(ctx["box"]["id"],
                                         create_inspection_payload(records), OPS))
        # Clean inspection stamps sanitization_started_at with the logical
        # clock: 2026-05-10T00:00:00Z.
        return ctx

    def test_complete_sanitization_before_24h_rejected(self, api):
        """PRD §2.10: "Completing sanitization requires the copy to be in
        `SANITIZING` and at least 24 hours to have elapsed since
        `sanitization_started_at`; an earlier completion attempt is rejected
        with `ERR_SANITIZATION_BUFFER_ACTIVE` (HTTP 422)."

        At +12h the buffer is still active.

        Design: Difficulty/resource_temporal_overlap/sanitization_buffer_gap
        """
        ctx = self._setup_sanitizing_copy(api)
        copy_id = ctx["copy"]["id"]

        set_clock("2026-05-10T12:00:00Z")
        resp = api.complete_sanitization(copy_id, OPS)
        validate_error(resp, ApiErrorId.ERR_SANITIZATION_BUFFER_ACTIVE.value, 422)
        assert read_copy(copy_id)["status"] == "SANITIZING"

    def test_complete_sanitization_at_exactly_24h_succeeds(self, api):
        """PRD §2.10: "Completing sanitization requires the copy to be in
        `SANITIZING` and at least 24 hours to have elapsed since
        `sanitization_started_at`; an earlier completion attempt is rejected
        with `ERR_SANITIZATION_BUFFER_ACTIVE` (HTTP 422)."
        PRD §3.6: "Completing sanitization — allowed only while the copy is
        `SANITIZING` (anything else earns `ERR_INVALID_STATE`) and only after
        the 24-hour buffer of §2.10 — returns the copy to `AVAILABLE`, stamps
        `last_sanitized_at` with the clock, increments
        `sanitization_cycle_count` by one, and fires the targeted allocation
        sweep for its catalog item."

        The buffer is "at least 24 hours": at exactly +24h the completion
        succeeds.  No wishlist demand exists, so the targeted sweep leaves the
        copy AVAILABLE.

        Design: Difficulty/resource_temporal_overlap/sanitization_buffer_gap
        """
        ctx = self._setup_sanitizing_copy(api)
        copy_id = ctx["copy"]["id"]

        set_clock("2026-05-11T00:00:00Z")  # exactly +24h
        completed = validate_success(api.complete_sanitization(copy_id, OPS))
        assert completed["status"] == "AVAILABLE"
        assert_same_instant(completed["last_sanitized_at"], "2026-05-11T00:00:00Z",
                            "last_sanitized_at")
        assert completed["sanitization_cycle_count"] == 1


class TestInspectionSuspensionCascade:
    def _setup(self, api):
        return setup_received_box(
            member_email="m.susp@x.com",
            item_overrides={"title": "Drum", "piece_count": 3,
                            "retail_value_cents": 10000,
                            "replacement_value_cents": 8000},
            barcode="BC-SUSP-1",
            received_at="2026-05-10T00:00:00Z",
            return_in_transit_at="2026-05-09T00:00:00Z",
        )

    def _inspect_severe(self, api, ctx):
        records = [inspection_record(ctx["item"]["id"], condition_returned="WORN",
                                     damage_severity="SEVERE", missing_piece_count=0)]
        return validate_success(api.inspect_box(
            ctx["box"]["id"], create_inspection_payload(records), OPS))

    def test_inspection_fee_charges_wallet_and_suspends_member(self, api):
        """PRD §3.6: "Every emitted fee starts `INVOICED`, appends a
        `FEE_CHARGE` ledger entry against the member's wallet, and triggers the
        wallet recompute — suspension toggle included."
        PRD §2.9: "Whenever a ledger append leaves `wallet_credit_cents` below
        −5,000 cents — a debt exceeding fifty dollars — the member's `status`
        flips from `ACTIVE` to `SUSPENDED`; a later append that brings the
        balance back to −5,000 cents or higher restores `ACTIVE`."
        PRD §2.9: "While `SUSPENDED`, every member-gated mutation fails with
        `ERR_MEMBER_SUSPENDED` (HTTP 409): creating a rotation box, adding or
        swapping a box item, buying out or reporting lost a toy, creating a
        wishlist entry, accepting a hold, and pausing or resuming a
        subscription."

        SEVERE damage on replacement 8000 -> round_half_up(8000 x 0.75) = 6000;
        wallet 0 - 6000 crosses the −5,000 boundary, and the follow-on box
        create is rejected even with the current subscription version.

        Design: Difficulty/transitive_cascade/inspection_damage_suspension_cascade
        """
        ctx = self._setup(api)
        member = ctx["member"]
        self._inspect_severe(api, ctx)

        fees = list_item_fees(ctx["item"]["id"], member)
        assert len(fees) == 1
        assert fees[0]["fee_type"] == "DAMAGE"
        assert fees[0]["amount_cents"] == 6000
        assert fees[0]["status"] == "INVOICED"

        member_now = read_member(member["id"])
        assert member_now["wallet_credit_cents"] == -6000
        assert member_now["status"] == "SUSPENDED"  # -6000 < -5000

        sub_now = read_subscription(ctx["subscription"]["id"], member)
        resp = api.create_rotation_box(
            ctx["subscription"]["id"],
            create_box_create_payload(sub_now["version"]),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED.value, 409)

    def test_inspection_records_fields_and_degrades_copy(self, api):
        """PRD §3.6: "A restocked copy moves `RETURNED` → `SANITIZING`, stamps
        `sanitization_started_at` with the logical clock, and degrades its
        `condition_grade` to the worse of its current grade and the recorded
        `condition_returned`, on the scale where `NEW` beats `GOOD` beats
        `FAIR` beats `WORN`."
        PRD §3.6: "Follow-up inspection calls are accepted while the box is
        `RECEIVED` or already `INSPECTED`, and the box moves `RECEIVED` →
        `INSPECTED` automatically the moment every `PENDING_RETURN` item has an
        inspection record; each inspected item's `loan_status` becomes
        `RETURNED`."
        PRD §3.6: "An item whose inspection produced at least one fee moves its
        `resolution_status` to `FEE_ASSESSED`; an item with no fees moves
        straight to `RESOLVED`."

        Design: Difficulty/transitive_cascade/inspection_damage_suspension_cascade
        """
        ctx = self._setup(api)
        member = ctx["member"]
        box_after = self._inspect_severe(api, ctx)

        assert box_after["status"] == "INSPECTED"
        item_now = read_box_item(ctx["item"]["id"], member)
        assert item_now["loan_status"] == "RETURNED"
        assert item_now["condition_returned"] == "WORN"
        assert item_now["damage_severity"] == "SEVERE"
        assert item_now["resolution_status"] == "FEE_ASSESSED"

        copy_now = read_copy(ctx["copy"]["id"])
        assert copy_now["status"] == "SANITIZING"
        assert copy_now["condition_grade"] == "WORN"  # worse(NEW, WORN)


def inspect_box_api(api, box_id, records):
    return validate_success(api.inspect_box(box_id, create_inspection_payload(records),
                                            OPS))

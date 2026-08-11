"""Filling a PLANNED box: the inclusive age gate at its boundary, the
safety-before-capacity error ordering, sanitization validity, copies reserved
to another member, the empty-box shipping precondition, and the box-version
OCC guard."""

from test_helpers import (
    ADMIN,
    OPS,
    ApiErrorId,
    add_item_to_box,
    assert_active_slot_count,
    assert_version_incremented,
    create_add_item_payload,
    create_catalog_item,
    create_catalog_item_payload,
    create_next_box,
    create_shipment_payload,
    list_box_items,
    list_box_shipments,
    make_member_headers,
    mint_copy,
    read_box,
    read_copy,
    set_clock,
    setup_member_with_subscription,
    validate_error,
    validate_success,
)


class TestAgeGateBoundary:
    def test_age_exactly_min_passes_gate(self, api):
        """PRD §3.1: "A catalog item fits a household when at least one of the
        member's child profiles satisfies the item's inclusive age range — the
        child's calendar `age_months` is at least the item's `min_age_months`
        and at most its `max_age_months`."
        PRD §3.5: "A successful add creates a box item with `loan_status`
        `PENDING_RETURN` ... the copy moves to `RESERVED` under the caller"

        Child born 2025-05-01 reads exactly 12 whole calendar months at the
        default clock 2026-05-01 — the lower bound is inclusive.

        Design: Difficulty/boundary_precision_check/age_min_boundary_inclusive
        """
        ctx = setup_member_with_subscription(member_email="m.bnd1@x.com",
                                             child_birthdate="2025-05-01")
        member, child = ctx["member"], ctx["child"]
        assert child["age_months"] == 12
        item = create_catalog_item(title="Shape Sorter", min_age_months=12,
                                   max_age_months=36, piece_count=6,
                                   retail_value_cents=4000, replacement_value_cents=3000)
        copy = mint_copy(item["id"], barcode="BC-BND-1")
        box = create_next_box(member, ctx["subscription"]["id"])

        box_item = add_item_to_box(member, box["id"], copy["id"])
        assert box_item["toy_copy_id"] == copy["id"]
        assert box_item["loan_status"] == "PENDING_RETURN"

        copy_now = read_copy(copy["id"])
        assert copy_now["status"] == "RESERVED"
        assert copy_now["reserved_member_id"] == member["id"]

    def test_age_one_month_below_min_rejected(self, api):
        """PRD §3.1: "A catalog item fits a household when at least one of the
        member's child profiles satisfies the item's inclusive age range — the
        child's calendar `age_months` is at least the item's `min_age_months`
        and at most its `max_age_months`."
        PRD §3.1: "Slotting an item into a box, swapping to a different copy,
        and accepting a hold all re-evaluate this gate and fail with
        `ERR_AGE_INCOMPATIBLE` (HTTP 422) when no child qualifies."

        Child born 2025-05-02 reads 11 whole calendar months at the default
        clock 2026-05-01 — one below the inclusive lower bound 12.

        Design: Difficulty/boundary_precision_check/age_min_boundary_inclusive
        """
        ctx = setup_member_with_subscription(member_email="m.bnd1b@x.com",
                                             child_birthdate="2025-05-02")
        member, child = ctx["member"], ctx["child"]
        assert child["age_months"] == 11
        item = create_catalog_item(title="Shape Sorter", min_age_months=12,
                                   max_age_months=36, piece_count=6,
                                   retail_value_cents=4000, replacement_value_cents=3000)
        copy = mint_copy(item["id"], barcode="BC-BND-1B")
        box = create_next_box(member, ctx["subscription"]["id"])

        box_now = read_box(box["id"], member)
        resp = api.add_box_item(
            box["id"],
            create_add_item_payload(copy["id"], box_now["version"]),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_AGE_INCOMPATIBLE.value, 422)
        assert list_box_items(box["id"], member) == []
        assert read_copy(copy["id"])["status"] == "AVAILABLE"


class TestSafetyTrumpsCapacity:
    def test_age_incompatible_copy_into_full_box_surfaces_safety_error(self, api):
        """PRD §2.6: "The pipeline evaluates, in order: ... (6) business-safety
        gates — the developmental age gate (`ERR_AGE_INCOMPATIBLE`) and
        sanitization validity (`ERR_NEEDS_RESANITIZATION`); ... (8) constraint
        rules — uniqueness violations ..., slot capacity
        (`ERR_SLOT_CAPACITY_EXCEEDED`), ..."

        The add violates both the age gate (child is 15 months, item minimum
        24) and slot capacity (the single-slot box is full); the safety error
        must surface.

        Design: Difficulty/priority_pair_validation_conflict/item_add_safety_trumps_capacity
        """
        ctx = setup_member_with_subscription(
            plan_overrides={"name": "SOLO", "toys_per_box": 1,
                            "swap_allowance_per_cycle": 1, "max_holds": 1},
            member_email="m.conf2@x.com")
        member = ctx["member"]
        bad_item = create_catalog_item(title="Big Beads", min_age_months=24,
                                       max_age_months=36, piece_count=5,
                                       retail_value_cents=6000,
                                       replacement_value_cents=5000)
        c1 = mint_copy(bad_item["id"], barcode="BC-CONF2-BAD")
        ok_item = create_catalog_item(title="Soft Ball", min_age_months=12,
                                      max_age_months=36, piece_count=1,
                                      retail_value_cents=2000,
                                      replacement_value_cents=1500)
        c2 = mint_copy(ok_item["id"], barcode="BC-CONF2-OK")
        box = create_next_box(member, ctx["subscription"]["id"])
        add_item_to_box(member, box["id"], c2["id"])  # fills the only slot

        box_now = read_box(box["id"], member)
        resp = api.add_box_item(
            box["id"], create_add_item_payload(c1["id"], box_now["version"]),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_AGE_INCOMPATIBLE.value, 422)

    def test_rejected_dual_violation_add_leaves_box_and_copy_untouched(self, api):
        """PRD §2.6: "The pipeline evaluates, in order: ... (6) business-safety
        gates — the developmental age gate (`ERR_AGE_INCOMPATIBLE`) and
        sanitization validity (`ERR_NEEDS_RESANITIZATION`); ... (8) constraint
        rules — uniqueness violations ..., slot capacity
        (`ERR_SLOT_CAPACITY_EXCEEDED`), ..."
        PRD §3.5: "The box's slotted items — those with `loan_status`
        `PENDING_RETURN` — must number fewer than the plan's `toys_per_box`, or
        the add fails with `ERR_SLOT_CAPACITY_EXCEEDED`."

        After the rejected dual-violation add the box keeps its single slotted
        item and the rejected copy stays AVAILABLE.

        Design: Difficulty/priority_pair_validation_conflict/item_add_safety_trumps_capacity
        """
        ctx = setup_member_with_subscription(
            plan_overrides={"name": "SOLO", "toys_per_box": 1,
                            "swap_allowance_per_cycle": 1, "max_holds": 1},
            member_email="m.conf2@x.com")
        member = ctx["member"]
        bad_item = create_catalog_item(title="Big Beads", min_age_months=24,
                                       max_age_months=36, piece_count=5,
                                       retail_value_cents=6000,
                                       replacement_value_cents=5000)
        c1 = mint_copy(bad_item["id"], barcode="BC-CONF2-BAD")
        ok_item = create_catalog_item(title="Soft Ball", min_age_months=12,
                                      max_age_months=36, piece_count=1,
                                      retail_value_cents=2000,
                                      replacement_value_cents=1500)
        c2 = mint_copy(ok_item["id"], barcode="BC-CONF2-OK")
        box = create_next_box(member, ctx["subscription"]["id"])
        add_item_to_box(member, box["id"], c2["id"])

        box_now = read_box(box["id"], member)
        resp = api.add_box_item(
            box["id"], create_add_item_payload(c1["id"], box_now["version"]),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_AGE_INCOMPATIBLE.value, 422)

        items = list_box_items(box["id"], member)
        assert_active_slot_count(items, 1)
        assert items[0]["toy_copy_id"] == c2["id"]
        assert read_copy(c1["id"])["status"] == "AVAILABLE"


class TestSanitizationGate:
    def test_stale_sanitization_blocks_item_add(self, api):
        """PRD §2.10: "Validity has exactly two forms: the copy is
        factory-sealed — `condition_grade` `NEW` with `last_sanitized_at` still
        null — or its `last_sanitized_at` lies within 30 days of the logical
        clock. A copy failing both forms is sanitization-stale, and attempts to
        slot it into a box, swap to it, or accept it from a hold are rejected
        with `ERR_NEEDS_RESANITIZATION` (HTTP 422)"
        PRD §3.2: "A new copy starts `AVAILABLE`, with `reserved_member_id`
        null, `sanitization_started_at` null, `last_sanitized_at` null
        (factory-sealed), and a `sanitization_cycle_count` of zero."

        The copy was minted FAIR at clock 2026-04-01; at clock 2026-05-20 it is
        neither factory-sealed NEW nor sanitized within 30 days.

        Design: Corner/validations/stale_sanitization_blocks_reservation
        """
        set_clock("2026-04-01T00:00:00Z")
        item = validate_success(api.create_catalog_item(
            create_catalog_item_payload(
                title="Kitchen Set", min_age_months=12, max_age_months=36,
                developmental_stages=["TODDLER"], piece_count=4,
                retail_value_cents=12000, replacement_value_cents=9000),
            ADMIN), 201)
        copy = mint_copy(item["id"], barcode="BC-STALE-1", condition_grade="FAIR")

        set_clock("2026-05-20T00:00:00Z")
        ctx = setup_member_with_subscription(member_email="m.stale@x.com")
        member = ctx["member"]
        box = create_next_box(member, ctx["subscription"]["id"])

        box_now = read_box(box["id"], member)
        resp = api.add_box_item(
            box["id"], create_add_item_payload(copy["id"], box_now["version"]),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_NEEDS_RESANITIZATION.value, 422)

        assert read_copy(copy["id"])["status"] == "AVAILABLE"
        assert list_box_items(box["id"], member) == []


class TestCopyReservedToAnotherMember:
    def test_add_item_copy_reserved_by_other_returns_copy_not_available(self, api):
        """PRD §3.5: "The copy must be `AVAILABLE`, or already `RESERVED` to
        this same member; a copy that is anything else — including reserved to
        a different member — fails with `ERR_COPY_NOT_AVAILABLE` (HTTP 409)."

        Design: Corner/errors/add_item_copy_reserved_by_other_returns_copy_not_available
        """
        item = create_catalog_item(title="Xylophone", piece_count=6,
                                   retail_value_cents=5000, replacement_value_cents=4000)
        c1 = mint_copy(item["id"], barcode="BC-RBO-1")

        ctx_b = setup_member_with_subscription(member_email="m.rbb@x.com")
        member_b = ctx_b["member"]
        box_b = create_next_box(member_b, ctx_b["subscription"]["id"])
        add_item_to_box(member_b, box_b["id"], c1["id"])  # C1 RESERVED to B

        ctx_a = setup_member_with_subscription(member_email="m.rba@x.com")
        member_a = ctx_a["member"]
        box_a = create_next_box(member_a, ctx_a["subscription"]["id"])

        box_a_now = read_box(box_a["id"], member_a)
        resp = api.add_box_item(
            box_a["id"], create_add_item_payload(c1["id"], box_a_now["version"]),
            make_member_headers(member_a["id"]))
        validate_error(resp, ApiErrorId.ERR_COPY_NOT_AVAILABLE.value, 409)

        copy_now = read_copy(c1["id"])
        assert copy_now["status"] == "RESERVED"
        assert copy_now["reserved_member_id"] == member_b["id"]
        assert list_box_items(box_a["id"], member_a) == []


class TestShipPrecondition:
    def test_ship_empty_box_rejected(self, api):
        """PRD §3.5: "The box must be `PLANNED` and hold at least one
        `PENDING_RETURN` item — shipping an empty box fails with
        `ERR_BOX_EMPTY` (HTTP 422)."

        Design: Corner/state_machines/ship_empty_box_rejected_box_empty
        """
        ctx = setup_member_with_subscription(member_email="m.empty@x.com",
                                             with_child=False)
        member = ctx["member"]
        box = create_next_box(member, ctx["subscription"]["id"])

        resp = api.ship_box(box["id"], create_shipment_payload("UPS", "1Z-EMPTY"),
                            OPS)
        validate_error(resp, ApiErrorId.ERR_BOX_EMPTY.value, 422)

        assert read_box(box["id"], member)["status"] == "PLANNED"
        assert list_box_shipments(box["id"], member) == []


class TestBoxVersionOcc:
    def test_item_add_with_stale_box_version_rejected_then_succeeds(self, api):
        """PRD §2.8: "Adding an item to a rotation box (`POST
        /toy-rental/rotation-boxes/{id}/items`) requires
        `expected_rotation_box_version`; a mismatch with the box's current
        `version` — advanced by a prior add or swap — is rejected with
        `ERR_STALE_VERSION` (HTTP 412) instead of silently appending to a
        changed box."

        Design: Corner/complexity_layers/occ_item_add_stale_box_version
        """
        ctx = setup_member_with_subscription(member_email="m.occ2@x.com")
        member = ctx["member"]
        item = create_catalog_item(title="Xylophone", piece_count=6,
                                   retail_value_cents=5000, replacement_value_cents=4000)
        c1 = mint_copy(item["id"], barcode="BC-OCC2-1")
        c2 = mint_copy(item["id"], barcode="BC-OCC2-2")
        box = create_next_box(member, ctx["subscription"]["id"])
        stale_version = box["version"]

        add_item_to_box(member, box["id"], c1["id"])  # bumps the box version

        resp = api.add_box_item(
            box["id"], create_add_item_payload(c2["id"], stale_version),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)
        assert_active_slot_count(list_box_items(box["id"], member), 1)

        # Re-reading the box yields the current version; the same add succeeds.
        box_now = read_box(box["id"], member)
        assert_version_incremented(box_now["version"], stale_version)
        created = validate_success(api.add_box_item(
            box["id"], create_add_item_payload(c2["id"], box_now["version"]),
            make_member_headers(member["id"])), 201)
        assert created["toy_copy_id"] == c2["id"]
        assert_active_slot_count(list_box_items(box["id"], member), 2)
        assert_version_incremented(read_box(box["id"], member)["version"],
                                   box_now["version"])

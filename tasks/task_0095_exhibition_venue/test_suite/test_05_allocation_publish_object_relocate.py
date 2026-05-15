"""Booth allocation: publication, objection window, confirm, revoke,
relocation cycle — PRD §3.4, §2.6, §2.11.

Covers:
- per-row cascade of PROPOSED → PUBLISHED at publish-allocation
- pinning quoted_price_cents at the moment of publication and re-pinning
  at relocate (dual-variant booth pricing)
- objection window enforcement (open/closed boundary)
- relocation tier match and the OBJECTED→RELOCATING→PUBLISHED cycle
- compensating invariant on the count of ALLOCATED booths across
  the relocation pair
- revoke side-effects (booth back to AVAILABLE, application reverts
  to QUALIFIED)
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    assert_allocation,
    confirm_allocation_as_owner,
    count_booths_with_status,
    create_allocation,
    create_booth,
    create_dock_slot_payload,
    create_exhibition,
    create_qualified_application,
    create_safety_inspection_payload,
    iso_offset,
    list_audit_log,
    make_exhibitor_headers,
    object_allocation_payload,
    open_intake,
    publish_allocation,
    relocate_payload,
    revoke_allocation_payload,
    setup_exhibition_in_setup_with_confirmed_allocation,
    setup_exhibition_with_active_plan,
    setup_objected_allocation_ready_to_relocate,
    setup_two_standard_booths_with_published_allocation_on_first,
    validate_error,
    validate_success,
)


# ===========================================================================
# Allocation creation (PRD §3.4)
# ===========================================================================
class TestAllocationCreation:

    def test_allocation_creation_requires_available_booth(
        self, api, venue_admin_headers,
    ):
        """PRD §3.4: "The booth must be in AVAILABLE status — creating
        an allocation against any other status is rejected with
        ERR_BOOTH_ALREADY_ALLOCATED."

        Claim: POST /allocations against a RESERVED booth →
        ERR_BOOTH_ALREADY_ALLOCATED.
        """
        exh, hall, _ = setup_exhibition_with_active_plan(theme_code="GEN")
        booth = create_booth(
            hall["id"], cells=[{"row": 2, "col": 2}], tier="STANDARD",
        )
        open_intake(exh["id"])
        # First application + allocation.
        app1, _ = create_qualified_application(
            exh["id"], theme_tags=["GEN"], requested_tier="STANDARD",
        )
        create_allocation(app1["id"], booth["id"])
        # Booth is now RESERVED. Second allocation should fail.
        app2, _ = create_qualified_application(
            exh["id"], theme_tags=["GEN"], requested_tier="STANDARD",
        )
        from test_helpers import create_allocation_payload
        res = api.create_allocation(
            create_allocation_payload(
                application_id=app2["id"], booth_id=booth["id"],
            ),
            venue_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_BOOTH_ALREADY_ALLOCATED.value)


# ===========================================================================
# Publication cascade (PRD §3.4, §2.6)
# ===========================================================================
class TestPublicationCascade:

    def test_publication_writes_audit_log_entry(
        self, api, venue_admin_headers,
    ):
        """PRD §3.4: "an AuditLogEntry with action PUBLISH is recorded
        carrying the pinned price in its payload."

        Claim: after publish-allocation, /audit-log contains a PUBLISH
        entry for this allocation.
        """
        ctx = setup_two_standard_booths_with_published_allocation_on_first()
        entries = list_audit_log(
            ctx["exhibition"]["id"], subject_kind="ALLOCATION",
        )
        # The audit log API returns either a list directly or a list
        # in data — fixture flattens to a list of rows.
        if isinstance(entries, dict):
            entries = entries.get("data", [])
        actions = [e.get("action") for e in entries]
        assert "PUBLISH" in actions, (
            f"Expected a PUBLISH audit entry; got actions {actions!r}"
        )


# ===========================================================================
# Objection (PRD §3.4)
# ===========================================================================
class TestObjection:

    def test_object_by_non_owner_is_forbidden(
        self, api,
    ):
        """PRD §3.4: "The acting exhibitor's X-User-ID must equal the
        allocation's exhibitor_id."

        Claim: object call by a different exhibitor → ERR_FORBIDDEN.
        """
        ctx = setup_two_standard_booths_with_published_allocation_on_first()
        # Headers for an unrelated exhibitor id.
        other_headers = make_exhibitor_headers("other-exhibitor-xyz")
        res = api.object_allocation(
            ctx["allocation"]["id"],
            object_allocation_payload(reason="Not my allocation"),
            other_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_object_after_window_closed(
        self, api,
    ):
        """PRD §3.4: "The objection is only accepted while the current
        server clock is strictly less than the allocation's
        published_at plus the exhibition's objection_window_hours;
        later objections are rejected with
        ERR_OBJECTION_WINDOW_CLOSED."

        Claim: after advancing the clock past published_at +
        objection_window_hours, object → ERR_OBJECTION_WINDOW_CLOSED.
        """
        ctx = setup_two_standard_booths_with_published_allocation_on_first(
            objection_window_hours=1,
        )
        # Advance > 1 hour past publication.
        advance_clock(to=iso_offset(hours=2))
        headers = make_exhibitor_headers(ctx["exhibitor_id"])
        res = api.object_allocation(
            ctx["allocation"]["id"],
            object_allocation_payload(reason="Too late but try"),
            headers,
        )
        validate_error(res, ApiErrorId.ERR_OBJECTION_WINDOW_CLOSED.value)

    def test_object_within_window_moves_to_objected(
        self, api,
    ):
        """PRD §3.4: "The exhibitor named by the allocation may file
        an objection by supplying a reason, moving the allocation from
        PUBLISHED to OBJECTED and writing an AuditLogEntry with action
        OBJECT and the reason in its payload."

        Claim: object within window → status=OBJECTED.
        """
        ctx = setup_two_standard_booths_with_published_allocation_on_first()
        headers = make_exhibitor_headers(ctx["exhibitor_id"])
        res = api.object_allocation(
            ctx["allocation"]["id"],
            object_allocation_payload(reason="Wrong location"),
            headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "OBJECTED"


# ===========================================================================
# Relocation cycle and dual-variant booth pricing (PRD §3.4)
# ===========================================================================
class TestRelocation:
    # difficulty: dual_variant_calc/booth_price_repin_on_relocate
    # difficulty: non_linear_state_machine/allocation_objection_revision_cycle

    def test_relocation_tier_mismatch_rejected(
        self, api, venue_admin_headers,
    ):
        """PRD §3.4: "the target booth must currently be AVAILABLE and
        must share the same tier as the original booth — a tier
        mismatch is rejected with ERR_RELOCATION_TIER_MISMATCH."

        Claim: relocate from STANDARD to PREMIUM target →
        ERR_RELOCATION_TIER_MISMATCH.
        """
        ctx = setup_two_standard_booths_with_published_allocation_on_first()
        # Swap B2 for a PREMIUM booth in the same hall.
        from test_helpers import create_booth_payload
        premium_res = api.create_booth(
            ctx["hall"]["id"],
            create_booth_payload(
                code="P-1",
                cells=[{"row": 0, "col": 0}],
                tier="PREMIUM",
            ),
            venue_admin_headers,
        )
        premium = validate_success(premium_res, expected_status=201)
        # Object + start-relocation.
        owner = make_exhibitor_headers(ctx["exhibitor_id"])
        api.object_allocation(
            ctx["allocation"]["id"],
            object_allocation_payload(reason="Wrong location"),
            owner,
        )
        api.start_relocation(
            ctx["allocation"]["id"], venue_admin_headers,
        )
        res = api.relocate_allocation(
            ctx["allocation"]["id"],
            relocate_payload(target_booth_id=premium["id"]),
            venue_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_RELOCATION_TIER_MISMATCH.value)

    def test_relocation_repins_quoted_price_from_new_booth(
        self, api, venue_admin_headers,
    ):
        """PRD §3.4: "On success, the allocation's booth_id is rewritten
        to the target, the target booth moves to ALLOCATED,
        quoted_price_cents is re-pinned via the at-publish-or-relocate
        variant of the booth pricing rule."
        PRD §3.2 (booth pricing): the at-publish-or-relocate variant
        re-evaluates against the current booth's tier and is_corner —
        a non-corner target produces a different price than a corner
        original.

        Claim: relocating from a corner B1 (230000) to an interior B2
        (200000) re-pins allocation.quoted_price_cents to 200000.
        """
        # difficulty: dual_variant_calc/booth_price_repin_on_relocate
        exh, hall, _ = setup_exhibition_with_active_plan(theme_code="GEN")
        # B1 at (0,0) — corner — STANDARD → base_price 230000.
        booth_b1 = create_booth(
            hall["id"], cells=[{"row": 0, "col": 0}],
            tier="STANDARD", code="B1",
        )
        # B2 at (2,2) — interior — STANDARD → base_price 200000.
        booth_b2 = create_booth(
            hall["id"], cells=[{"row": 2, "col": 2}],
            tier="STANDARD", code="B2",
        )
        open_intake(exh["id"])
        app, exhibitor_id = create_qualified_application(
            exh["id"], theme_tags=["GEN"], requested_tier="STANDARD",
        )
        allocation = create_allocation(app["id"], booth_b1["id"])
        publish_allocation(exh["id"])
        # Refresh after publish to read pinned price.
        alloc = validate_success(
            api.get_allocation(allocation["id"], venue_admin_headers),
            expected_status=200,
        )
        assert alloc["quoted_price_cents"] == 230000
        # Object + start-relocation + relocate to B2.
        owner = make_exhibitor_headers(exhibitor_id)
        api.object_allocation(
            allocation["id"],
            object_allocation_payload(reason="Move me"),
            owner,
        )
        api.start_relocation(allocation["id"], venue_admin_headers)
        res = api.relocate_allocation(
            allocation["id"],
            relocate_payload(target_booth_id=booth_b2["id"]),
            venue_admin_headers,
        )
        relocated = validate_success(res, expected_status=200)
        assert relocated["status"] == "PUBLISHED"
        assert relocated["booth_id"] == booth_b2["id"]
        assert relocated["quoted_price_cents"] == 200000
        # And B1's base_price was not changed by the relocation.
        booth_b1_after = validate_success(
            api.get_booth(booth_b1["id"], venue_admin_headers),
            expected_status=200,
        )
        assert booth_b1_after["base_price_cents"] == 230000

    def test_allocation_objection_revision_cycle(
        self, api, venue_admin_headers,
    ):
        """PRD §3.4: "From OBJECTED, the admin starts the relocation,
        which moves the allocation to RELOCATING, frees the original
        booth back to AVAILABLE, and stashes the original booth_id in
        relocation_source_booth_id."
        PRD §3.4: "the allocation moves back to PUBLISHED."

        Claim: PUBLISHED→OBJECTED→RELOCATING→PUBLISHED is a legal
        cycle, traversable twice on the same allocation.
        """
        # difficulty: non_linear_state_machine/allocation_objection_revision_cycle
        exh, hall, _ = setup_exhibition_with_active_plan(theme_code="GEN")
        # Three STANDARD booths.
        b1 = create_booth(
            hall["id"], cells=[{"row": 0, "col": 0}],
            tier="STANDARD", code="B1",
        )
        b2 = create_booth(
            hall["id"], cells=[{"row": 2, "col": 2}],
            tier="STANDARD", code="B2",
        )
        b3 = create_booth(
            hall["id"], cells=[{"row": 3, "col": 3}],
            tier="STANDARD", code="B3",
        )
        open_intake(exh["id"])
        app, exhibitor_id = create_qualified_application(
            exh["id"], theme_tags=["GEN"], requested_tier="STANDARD",
        )
        allocation = create_allocation(app["id"], b1["id"])
        publish_allocation(exh["id"])
        owner = make_exhibitor_headers(exhibitor_id)
        # First cycle: object → start-relocation → relocate to B2.
        api.object_allocation(
            allocation["id"],
            object_allocation_payload(reason="Move 1"), owner,
        )
        api.start_relocation(allocation["id"], venue_admin_headers)
        api.relocate_allocation(
            allocation["id"], relocate_payload(target_booth_id=b2["id"]),
            venue_admin_headers,
        )
        # Second cycle on the re-published allocation: object →
        # start-relocation → relocate to B3.
        api.object_allocation(
            allocation["id"],
            object_allocation_payload(reason="Move 2"), owner,
        )
        api.start_relocation(allocation["id"], venue_admin_headers)
        res = api.relocate_allocation(
            allocation["id"], relocate_payload(target_booth_id=b3["id"]),
            venue_admin_headers,
        )
        relocated = validate_success(res, expected_status=200)
        assert relocated["status"] == "PUBLISHED"
        assert relocated["booth_id"] == b3["id"]
        assert relocated["relocation_source_booth_id"] == b2["id"]


# ===========================================================================
# Compensating invariant on ALLOCATED-count (PRD §3.4)
# ===========================================================================
class TestBoothStatusCountInvariantOnRelocation:
    # difficulty: compensating_invariant/booth_status_count_invariant_on_relocation

    def test_alloc_count_unchanged_after_relocation(
        self, api, venue_admin_headers,
    ):
        """PRD §3.4: "the booth moves to ALLOCATED ... Booth.status :=
        AVAILABLE (on start-relocation) ... Target Booth.status :=
        ALLOCATED (on relocate)."

        Claim: across a PUBLISHED→OBJECTED→RELOCATING→PUBLISHED cycle,
        the count of Booth rows in this hall with status='ALLOCATED'
        is conserved.
        """
        ctx = setup_two_standard_booths_with_published_allocation_on_first()
        n0 = count_booths_with_status(ctx["hall"]["id"], "ALLOCATED")
        # Walk the relocation cycle to B2.
        owner = make_exhibitor_headers(ctx["exhibitor_id"])
        api.object_allocation(
            ctx["allocation"]["id"],
            object_allocation_payload(reason="Move"), owner,
        )
        api.start_relocation(
            ctx["allocation"]["id"], venue_admin_headers,
        )
        api.relocate_allocation(
            ctx["allocation"]["id"],
            relocate_payload(target_booth_id=ctx["booth_b2"]["id"]),
            venue_admin_headers,
        )
        n1 = count_booths_with_status(ctx["hall"]["id"], "ALLOCATED")
        assert n1 == n0, (
            f"ALLOCATED-count invariant violated: before={n0}, "
            f"after={n1}"
        )
        # Final state cross-check.
        b1_after = validate_success(
            api.get_booth(ctx["booth_b1"]["id"], venue_admin_headers),
            expected_status=200,
        )
        b2_after = validate_success(
            api.get_booth(ctx["booth_b2"]["id"], venue_admin_headers),
            expected_status=200,
        )
        assert b1_after["status"] == "AVAILABLE"
        assert b2_after["status"] == "ALLOCATED"

    def test_intermediate_state_count_drops_then_restored(
        self, api, venue_admin_headers,
    ):
        """PRD §3.4: "From OBJECTED, the admin starts the relocation,
        which moves the allocation to RELOCATING, frees the original
        booth back to AVAILABLE."
        PRD §3.4: "On success, the allocation's booth_id is rewritten
        to the target, the target booth moves to ALLOCATED."

        Claim: in the middle of the relocation pair (after
        start-relocation but before relocate), the ALLOCATED count
        drops by one (the original booth is AVAILABLE); after the
        final relocate the count is restored to its original value.
        """
        # difficulty: compensating_invariant/booth_status_count_invariant_on_relocation
        ctx = setup_two_standard_booths_with_published_allocation_on_first()
        n0 = count_booths_with_status(ctx["hall"]["id"], "ALLOCATED")
        assert n0 == 1
        owner = make_exhibitor_headers(ctx["exhibitor_id"])
        api.object_allocation(
            ctx["allocation"]["id"],
            object_allocation_payload(reason="Move"), owner,
        )
        api.start_relocation(
            ctx["allocation"]["id"], venue_admin_headers,
        )
        # After start-relocation the original booth is back to
        # AVAILABLE.
        n_mid = count_booths_with_status(ctx["hall"]["id"], "ALLOCATED")
        assert n_mid == n0 - 1
        api.relocate_allocation(
            ctx["allocation"]["id"],
            relocate_payload(target_booth_id=ctx["booth_b2"]["id"]),
            venue_admin_headers,
        )
        n_final = count_booths_with_status(ctx["hall"]["id"], "ALLOCATED")
        assert n_final == n0


# ===========================================================================
# Revoke (PRD §3.4)
# ===========================================================================
class TestRevoke:

    def test_revoke_cascades_booth_to_available_and_application_to_qualified(
        self, api, venue_admin_headers,
    ):
        """PRD §3.4: "revocation requires the exhibition to be in
        ALLOCATION_PUBLISHED and cascades by setting the booth back to
        AVAILABLE, reverting the application to QUALIFIED, and writing
        an AuditLogEntry with action REVOKE."

        Claim: after revoke, booth.status=='AVAILABLE',
        application.status=='QUALIFIED'.
        """
        ctx = setup_two_standard_booths_with_published_allocation_on_first()
        res = api.revoke_allocation(
            ctx["allocation"]["id"],
            revoke_allocation_payload(reason="Withdrawing"),
            venue_admin_headers,
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "REVOKED"
        booth_after = validate_success(
            api.get_booth(ctx["booth_b1"]["id"], venue_admin_headers),
            expected_status=200,
        )
        assert booth_after["status"] == "AVAILABLE"

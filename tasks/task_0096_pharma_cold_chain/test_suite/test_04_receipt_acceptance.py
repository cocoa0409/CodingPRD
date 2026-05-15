"""Receipt acceptance — PRD §3.2 + §3.4.

Acceptance is the QAOfficer transition INSPECTED → ACCEPTED that mints
a Lot, allocates a bin via the FEFO bin-allocation calculation,
generates the acceptance_certificate_no, emits sync events, and
records SOD against the inspector.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    accept_receipt,
    assert_certificate_format,
    assert_lot,
    create_bin,
    create_inspected_receipt,
    create_product,
    create_supplier,
    create_warehouse,
    create_zone,
    find_row,
    list_audit_log,
    list_external_events,
    list_lots,
    make_qa_officer_headers,
    make_receiver_headers,
    setup_accepted_lot,
    setup_basic_topology,
    setup_qualified_supplier_and_product,
    validate_error,
)


# ===========================================================================
# Successful acceptance — happy path
# ===========================================================================
class TestSuccessfulAcceptance:

    def test_accept_mints_lot_with_released_status(self, api):
        """PRD §3.2: "Acceptance allocates a destination bin via the
        FEFO bin-allocation calculation ... mints a new `Lot` row with
        `quantity_on_hand` equal to the receipt's `quantity_units`,
        `quantity_picked` of 0, `quality_status` of `RELEASED`, the
        `bin_id` set to the assigned bin".

        Claim: a successful accept creates a Lot with quality_status
        RELEASED and quantity_on_hand equal to receipt.quantity_units.
        """
        ctx = setup_accepted_lot(quantity_units=7)
        lot = ctx["lot"]
        assert lot["quality_status"] == "RELEASED"
        assert lot["quantity_on_hand"] == 7
        assert lot["quantity_picked"] == 0
        assert_lot(lot)

    def test_accept_generates_certificate_with_warehouse_code_prefix(self, api):
        """PRD §3.2: "generates the `acceptance_certificate_no` in the
        format `CERT-{warehouse.code}-{seq:06d}` where the sequence is
        a six-digit zero-padded monotonic counter per warehouse".

        Claim: receipt.acceptance_certificate_no is
        CERT-{warehouse.code}-{seq:06d}.
        """
        ctx = setup_accepted_lot(quantity_units=1)
        cert = ctx["receipt"]["acceptance_certificate_no"]
        assert_certificate_format(cert, ctx["warehouse"]["code"])

    def test_accept_emits_two_sync_events_regulatory_and_gsp(self, api):
        """PRD §3.2: "appends one `ExternalSyncEvent` to the
        `REGULATORY_AUTHORITY` target and a second to the `GSP_REPORT`
        target, both carrying `event_type` of `INBOUND_ACCEPTED`".

        Claim: after accept, the external-events log contains exactly
        one REGULATORY_AUTHORITY + one GSP_REPORT with event_type
        INBOUND_ACCEPTED.
        """
        ctx = setup_accepted_lot(quantity_units=1)
        events = list_external_events(
            ctx["warehouse"]["id"],
            params={"event_type": "INBOUND_ACCEPTED", "limit": 100},
        )
        regulatory = [
            e for e in events
            if e["target_system"] == "REGULATORY_AUTHORITY"
            and e["event_type"] == "INBOUND_ACCEPTED"
        ]
        gsp = [
            e for e in events
            if e["target_system"] == "GSP_REPORT"
            and e["event_type"] == "INBOUND_ACCEPTED"
        ]
        assert len(regulatory) >= 1, (
            f"Expected at least one REGULATORY_AUTHORITY/INBOUND_ACCEPTED "
            f"event, saw {events}"
        )
        assert len(gsp) >= 1, (
            f"Expected at least one GSP_REPORT/INBOUND_ACCEPTED event, "
            f"saw {events}"
        )

    def test_accept_writes_audit_log_receipt_accept(self, api):
        """PRD §3.2: "writes an `AuditLogEntry` with `action` of
        `RECEIPT_ACCEPT`".

        Claim: after accept, audit log has an entry with action ==
        'RECEIPT_ACCEPT' targeting the receipt.
        """
        ctx = setup_accepted_lot(quantity_units=1)
        entries = list_audit_log(
            ctx["warehouse"]["id"],
            params={"action": "RECEIPT_ACCEPT", "limit": 100},
        )
        matched = [
            e for e in entries
            if e["action"] == "RECEIPT_ACCEPT"
            and e["target_id"] == ctx["receipt"]["id"]
        ]
        assert len(matched) >= 1, (
            f"Expected at least one RECEIPT_ACCEPT audit entry for "
            f"receipt {ctx['receipt']['id']}, saw {entries}"
        )

    def test_accept_assigns_bin_and_marks_it_occupied(self, api):
        """PRD §3.2: "Set Bin.current_lot_id, status=OCCUPIED,
        occupied_volume += quantity_units".

        Claim: after accept, the assigned bin's status is OCCUPIED,
        current_lot_id == lot.id, occupied_volume == quantity_units.
        """
        from test_helpers import get_bin
        ctx = setup_accepted_lot(quantity_units=10)
        binx = get_bin(ctx["zone"]["id"], ctx["bin"]["id"])
        assert binx is not None
        assert binx["status"] == "OCCUPIED"
        assert binx["current_lot_id"] == ctx["lot"]["id"]
        assert binx["occupied_volume"] == 10


# ===========================================================================
# Acceptance-time safety checks — PRD §3.2 paragraph 5
# ===========================================================================
class TestAcceptanceSafetyChecks:

    def test_accept_with_unqualified_supplier_returns_err_unqualified_supplier(
        self, api,
    ):
        """PRD §3.2: "The supplier check fails with
        `ERR_UNQUALIFIED_SUPPLIER` (HTTP 422) when the supplier's
        `qualified` is false".

        Claim: accept with qualified=false supplier yields
        ERR_UNQUALIFIED_SUPPLIER. (We must defeat the nonconformance
        priority cascade — the receipt was INSPECTED with reason
        UNQUALIFIED_SUPPLIER, but accept is invoked anyway; the rule
        is that accept is only legal when reason == NONE, and an
        attempt is rejected with ERR_UNQUALIFIED_SUPPLIER per the
        accept-time safety check.)

        Difficulty: this hits the §2.12 ordering between state
        preconditions and business_safety. The receipt is in
        INSPECTED, so the state check passes; then the business_safety
        supplier check fires.
        """
        topology = setup_basic_topology()
        supplier = create_supplier(qualified=False,
                                   qualification_expiry_minutes=100_000)
        product = create_product(
            required_zone_type="REFRIGERATED", qualified=True,
        )
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1, visual_pass=True,
        )
        res = api.accept_receipt(
            receipt["id"], TEST_USERS["qa_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_UNQUALIFIED_SUPPLIER.value)

    def test_accept_with_expired_lot_returns_err_expired_lot(self, api):
        """PRD §3.2: "the lot-expiry check fails with `ERR_EXPIRED_LOT`
        (HTTP 422) when the lot's `expiry_minutes` is less than or
        equal to `clock_minutes` plus 1 (so a lot that expires this
        minute or the next is not acceptable)."

        Claim: accept with expiry_minutes == clock_minutes + 1 yields
        ERR_EXPIRED_LOT (boundary precision X = clock+1 is rejected).
        """
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        advance_clock(topology["warehouse"]["id"], 100)
        # First, build a receipt with expiry > 100 so inspection
        # succeeds (so we can test accept-time only). Use expiry=101
        # exactly — boundary at clock+1.
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1,
            expiry_minutes=101,  # == clock_minutes + 1
        )
        res = api.accept_receipt(
            receipt["id"], TEST_USERS["qa_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_EXPIRED_LOT.value)

    def test_accept_with_expiry_clock_plus_two_is_accepted(self, api):
        """PRD §3.2 boundary upper side: expiry_minutes ==
        clock_minutes + 2 is accepted (the rule rejects <=, so > is OK).

        Claim: accept with expiry > clock_minutes + 1 succeeds.
        """
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        advance_clock(topology["warehouse"]["id"], 100)
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1,
            expiry_minutes=102,  # == clock_minutes + 2
        )
        res = api.accept_receipt(
            receipt["id"], TEST_USERS["qa_officer_headers"],
        )
        # Should succeed → 200.
        assert res.status_code == 200, (
            f"Expected 200 for expiry==clock+2, got {res.status_code}: "
            f"{res.text}"
        )


# ===========================================================================
# State precondition — accept on a receipt not in INSPECTED.
# PRD §2.12 priority ranks state checks BEFORE business_safety.
# ===========================================================================
class TestAcceptStatePrecondition:

    def test_accept_on_pending_receipt_returns_err_receipt_not_inspected(
        self, api,
    ):
        """PRD §2.11: "When two `QAOfficer` calls attempt to accept
        the same inbound receipt at the same moment, the first writer
        wins the `INSPECTED` to `ACCEPTED` transition and the loser is
        rejected with `ERR_RECEIPT_NOT_INSPECTED` (HTTP 409)."

        Claim: accept on a PENDING_INSPECTION receipt yields
        ERR_RECEIPT_NOT_INSPECTED.
        """
        from test_helpers import create_pending_receipt
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        receipt = create_pending_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"], quantity_units=1,
        )
        # Skip inspect; go straight to accept.
        res = api.accept_receipt(
            receipt["id"], TEST_USERS["qa_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_RECEIPT_NOT_INSPECTED.value)


# ===========================================================================
# Segregation of duties — PRD §2.1
# ===========================================================================
class TestSegregationOfDuties:

    def test_same_user_inspect_and_accept_yields_err_sod_violation(self, api):
        """PRD §2.1: "the inspector of an inbound receipt must not be
        the same `X-User-ID` that performs the corresponding
        acceptance ... both surface as `ERR_SOD_VIOLATION` with HTTP
        403."

        Claim: when the X-User-ID that calls inspect is reused for
        accept, accept yields ERR_SOD_VIOLATION / 403.
        """
        from test_helpers import create_pending_receipt
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product()
        # We need the same X-User-ID for both inspect and accept.
        # Receiver and QAOfficer normally differ, but PRD says the
        # comparison is on X-User-ID alone — different roles, same
        # user_id, should still fire SOD. To exercise SOD we make
        # both calls carry the same X-User-ID; the inspect uses the
        # Receiver role and the accept uses the QAOfficer role.
        same_id = "shared-user-001"
        receipt = create_pending_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"], quantity_units=1,
            headers=make_receiver_headers(same_id),
        )
        from test_helpers import inspect_receipt
        inspected = inspect_receipt(
            receipt["id"], headers=make_receiver_headers(same_id),
        )
        assert inspected["nonconformance_reason"] == "NONE"
        # Now attempt accept with the SAME X-User-ID but QAOfficer role.
        res = api.accept_receipt(
            receipt["id"], make_qa_officer_headers(same_id),
        )
        validate_error(res, ApiErrorId.ERR_SOD_VIOLATION.value)


# ===========================================================================
# FEFO bin allocation — PRD §3.4
# ===========================================================================
class TestFefoBinAllocation:

    def test_segregation_violation_when_no_matching_special_tag_bin(self, api):
        """PRD §3.4: "whose `special_storage_tag` exactly matches the
        product's `special_storage_tag` (a `NARCOTIC`, `PSYCHOTROPIC`,
        `BIOLOGICAL`, or `VACCINE` product must land in a bin tagged
        the same way, and a `NONE` product must land in a `NONE` bin
        — any other pairing is a `ERR_SEGREGATION_VIOLATION` at HTTP
        422)."

        Claim: NARCOTIC product but the warehouse only has NONE bins
        in its REFRIGERATED zone → accept yields
        ERR_SEGREGATION_VIOLATION.
        """
        wh = create_warehouse()
        zone = create_zone(wh["id"], zone_type="REFRIGERATED")
        # Only a NONE-tagged bin.
        create_bin(zone["id"], volume_units=100, weight_limit_kg=500.0)
        # Quarantine plumbing so the receipt could quarantine.
        qz = create_zone(wh["id"], zone_type="QUARANTINE",
                         capacity_units=1000)
        create_bin(qz["id"], volume_units=1000, weight_limit_kg=10000.0)
        supplier, product = setup_qualified_supplier_and_product(
            required_zone_type="REFRIGERATED",
            special_storage_tag="NARCOTIC",
        )
        receipt = create_inspected_receipt(
            wh["id"], supplier["id"], product["id"], quantity_units=1,
        )
        res = api.accept_receipt(
            receipt["id"], TEST_USERS["qa_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_VIOLATION.value)

    def test_sequential_second_accept_for_only_bin_rejected(self, api):
        """PRD §3.4: "The candidate set is every bin in the warehouse
        whose `status` is `AVAILABLE`".
        PRD §3.2: "Set Bin.current_lot_id, status=OCCUPIED".

        Difficulty-design: resource_temporal_overlap /
        bin_single_lot_occupancy_overlap_inclusive (sequential variant
        — once a bin is OCCUPIED by the first accept's lot, a second
        accept against the same warehouse sees no AVAILABLE bin and
        is rejected).
        # difficulty: resource_temporal_overlap/bin_single_lot_occupancy_overlap_inclusive

        Claim: a warehouse with one bin sees: accept #1 succeeds
        (bin → OCCUPIED); accept #2 fails because the candidate set
        (status==AVAILABLE) is now empty → ERR_NO_ELIGIBLE_BIN.
        """
        from test_helpers import setup_two_inspected_receipts_for_single_bin
        ctx = setup_two_inspected_receipts_for_single_bin(quantity_units=5)
        # First accept succeeds.
        res1 = api.accept_receipt(
            ctx["receipt_1"]["id"], TEST_USERS["qa_officer_headers"],
        )
        assert res1.status_code == 200, (
            f"First accept should succeed, got {res1.status_code}: "
            f"{res1.text}"
        )
        # Second accept on the same warehouse — bin is now OCCUPIED.
        res2 = api.accept_receipt(
            ctx["receipt_2"]["id"], TEST_USERS["qa_officer_headers_alt"],
        )
        # The filter on b.status==AVAILABLE removes the now-OCCUPIED
        # bin; no candidate exists → ERR_NO_ELIGIBLE_BIN.
        validate_error(res2, ApiErrorId.ERR_NO_ELIGIBLE_BIN.value)

    def test_no_eligible_bin_returns_err_no_eligible_bin(self, api):
        """PRD §3.4: "If the candidate set is empty after filtering,
        the request fails with `ERR_NO_ELIGIBLE_BIN` (HTTP 422)."

        Claim: warehouse with a REFRIGERATED zone but no AVAILABLE
        bins of the matching zone_type yields ERR_NO_ELIGIBLE_BIN.
        (We need a REFRIGERATED zone present so PRD §3.2 inspection's
        temp_chain_intact lookup succeeds — "looked up against any
        zone of that type in the warehouse" — without it the receipt
        is routed to TEMP_EXCURSION nonconformance and accept fails
        on the receipt-state precondition instead. With the zone but
        no bins, inspection passes and FEFO sees no candidates.)
        """
        wh = create_warehouse()
        # REFRIGERATED zone — required so inspection's temp-chain check
        # succeeds — but WITHOUT any bins, so FEFO's candidate set is
        # empty.
        create_zone(wh["id"], zone_type="REFRIGERATED")
        qz = create_zone(wh["id"], zone_type="QUARANTINE",
                         capacity_units=1000)
        create_bin(qz["id"], volume_units=1000, weight_limit_kg=10000.0)
        supplier, product = setup_qualified_supplier_and_product(
            required_zone_type="REFRIGERATED",
        )
        receipt = create_inspected_receipt(
            wh["id"], supplier["id"], product["id"], quantity_units=1,
        )
        res = api.accept_receipt(
            receipt["id"], TEST_USERS["qa_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_BIN.value)

    def test_bin_capacity_exceeded_when_quantity_exceeds_volume(self, api):
        """PRD §3.4: "whose `volume_units` is at least the receipt's
        `quantity_units` ... a per-bin capacity miss surfaces as
        `ERR_BIN_CAPACITY_EXCEEDED` at HTTP 422".

        Claim: receipt quantity exceeds the only available bin's
        volume_units → ERR_BIN_CAPACITY_EXCEEDED. PRD explicitly names
        this error for the per-bin capacity miss, so the candidate-set
        filter on volume_units surfaces ERR_BIN_CAPACITY_EXCEEDED
        rather than the generic ERR_NO_ELIGIBLE_BIN.
        """
        # Bin volume==5, receipt quantity==10.
        wh = create_warehouse()
        z = create_zone(wh["id"], zone_type="REFRIGERATED")
        create_bin(z["id"], volume_units=5, weight_limit_kg=500.0)
        qz = create_zone(wh["id"], zone_type="QUARANTINE",
                         capacity_units=1000)
        create_bin(qz["id"], volume_units=1000, weight_limit_kg=10000.0)
        supplier, product = setup_qualified_supplier_and_product(
            required_zone_type="REFRIGERATED",
        )
        receipt = create_inspected_receipt(
            wh["id"], supplier["id"], product["id"], quantity_units=10,
        )
        res = api.accept_receipt(
            receipt["id"], TEST_USERS["qa_officer_headers"],
        )
        # PRD §3.4 explicitly: "a per-bin capacity miss surfaces as
        # ERR_BIN_CAPACITY_EXCEEDED at HTTP 422".
        validate_error(res, ApiErrorId.ERR_BIN_CAPACITY_EXCEEDED.value)


# ===========================================================================
# Zone capacity ceiling — PRD §3.4
# ===========================================================================
class TestZoneCapacityCeiling:

    def test_zone_capacity_exactly_at_ceiling_is_accepted(self, api):
        """PRD §3.4: "An additional zone-level capacity ceiling
        enforces that the zone's current `utilization_units` plus the
        receipt's `quantity_units` does not exceed the zone's
        `capacity_units`".

        Difficulty-design: resource_temporal_overlap /
        zone_capacity_aggregate_overlap_capacity (the boundary side —
        equality is permitted; only strict exceedance fires the rule).
        # difficulty: resource_temporal_overlap/zone_capacity_aggregate_overlap_capacity

        Claim: zone capacity=10, utilization=8; a 2-unit accept brings
        utilization to exactly 10 — this is permitted (8+2 <= 10),
        and accept succeeds.
        """
        from test_helpers import (
            accept_receipt,
            create_bin,
            create_inspected_receipt,
            create_warehouse,
            create_zone,
            setup_qualified_supplier_and_product,
        )
        wh = create_warehouse()
        z = create_zone(wh["id"], zone_type="REFRIGERATED",
                        capacity_units=10)
        # Two bins of volume 8 and 2 — capacity ceiling is 10 (zone
        # cap), not bin-summed (which is 10).
        create_bin(z["id"], volume_units=8, weight_limit_kg=500.0)
        create_bin(z["id"], volume_units=2, weight_limit_kg=500.0)
        qz = create_zone(wh["id"], zone_type="QUARANTINE",
                         capacity_units=1000)
        create_bin(qz["id"], volume_units=1000, weight_limit_kg=10000.0)
        supplier, product = setup_qualified_supplier_and_product()
        # Accept 8-unit receipt first.
        r1 = create_inspected_receipt(
            wh["id"], supplier["id"], product["id"], quantity_units=8,
        )
        accept_receipt(r1["id"])
        # Accept 2-unit receipt — utilization 8 + 2 = 10 == capacity.
        r2 = create_inspected_receipt(
            wh["id"], supplier["id"], product["id"], quantity_units=2,
        )
        res = api.accept_receipt(
            r2["id"], TEST_USERS["qa_officer_headers"],
        )
        # 8 + 2 = 10 is exactly == capacity; PRD says "does not
        # exceed" — equality is permitted.
        assert res.status_code == 200, (
            f"Expected 200 at exact capacity, got {res.status_code}: "
            f"{res.text}"
        )

    def test_zone_capacity_exceeded_when_total_would_overflow(self, api):
        """PRD §3.4: "An additional zone-level capacity ceiling enforces
        that the zone's current `utilization_units` plus the receipt's
        `quantity_units` does not exceed the zone's `capacity_units`;
        exceeding the ceiling surfaces as `ERR_ZONE_CAPACITY_EXCEEDED`
        (HTTP 422)."

        Difficulty-design: rule_id=resource_temporal_overlap /
        zone_capacity_aggregate_overlap_capacity.

        # difficulty: resource_temporal_overlap/zone_capacity_aggregate_overlap_capacity

        Claim: zone capacity=10, one accept of 8 brings utilization
        to 8; a second 8-unit accept attempt yields
        ERR_ZONE_CAPACITY_EXCEEDED.
        """
        from test_helpers import setup_zone_at_capacity_minus_quantity
        ctx = setup_zone_at_capacity_minus_quantity(
            zone_capacity_units=10, pre_loaded_quantity_units=8,
        )
        # ctx['receipt_inspected'] is INSPECTED and ready for accept.
        res = api.accept_receipt(
            ctx["receipt_inspected"]["id"],
            TEST_USERS["qa_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ZONE_CAPACITY_EXCEEDED.value)


# ===========================================================================
# Difficulty-design coverage: receipt accept ↔ zone posture
# # difficulty: cross_entity_state_dependency/receipt_accept_depends_on_zone_posture
# ===========================================================================
class TestAcceptZoneFrozenDependency:

    def test_accept_blocked_by_err_zone_frozen_after_alarm_low(self, api):
        """PRD §2.10: "Any alarm-level reading (whether `ALARM_LOW`
        or `ALARM_HIGH`) drives the zone to `FROZEN`".

        Difficulty-design: cross_entity_state_dependency /
        receipt_accept_depends_on_zone_posture (the ALARM_LOW side —
        proves the cross-entity dependency fires identically for
        the symmetric ALARM_LOW reading).
        # difficulty: cross_entity_state_dependency/receipt_accept_depends_on_zone_posture

        Claim: an ALARM_LOW reading drives the zone to FROZEN; accept
        is blocked with ERR_ZONE_FROZEN.
        """
        from test_helpers import (
            create_inspected_receipt,
            record_temperature_event,
        )
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product(
            required_zone_type="REFRIGERATED",
        )
        # REFRIGERATED alarm_low_c=0.0; reading 0.0 → ALARM_LOW.
        record_temperature_event(
            topology["zone"]["id"], at_minutes=0, temp_c=0.0,
        )
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"], quantity_units=1,
        )
        res = api.accept_receipt(
            receipt["id"], TEST_USERS["qa_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ZONE_FROZEN.value)

    def test_accept_blocked_by_err_zone_frozen_on_alarm_zone(self, api):
        """PRD §2.10: "Any alarm-level reading (whether `ALARM_LOW` or
        `ALARM_HIGH`) drives the zone to `FROZEN`; while a zone is
        `FROZEN`, every child bin's `status` flips to `LOCKED`, and
        any attempt to accept, release-from-quarantine, or pick
        against those bins is rejected with `ERR_ZONE_FROZEN`
        (HTTP 409)."

        Difficulty-design: cross_entity_state_dependency /
        receipt_accept_depends_on_zone_posture.

        # difficulty: cross_entity_state_dependency/receipt_accept_depends_on_zone_posture

        Claim: when the storage zone has been driven into FROZEN
        posture by an ALARM reading, an attempt to accept an
        INSPECTED receipt destined for that zone yields ERR_ZONE_FROZEN.
        """
        from test_helpers import (
            create_inspected_receipt,
            record_temperature_event,
        )
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product(
            required_zone_type="REFRIGERATED",
        )
        # Drive the REFRIGERATED zone into ALARM_HIGH (>= alarm_high_c=10).
        record_temperature_event(
            topology["zone"]["id"], at_minutes=0, temp_c=12.0,
        )
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"], quantity_units=1,
        )
        res = api.accept_receipt(
            receipt["id"], TEST_USERS["qa_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ZONE_FROZEN.value)


# ===========================================================================
# Difficulty-design coverage: priority pair state vs business_safety
# # difficulty: priority_pair_validation_conflict/state_vs_business_safety_zone_frozen_on_inspected_receipt
# ===========================================================================
class TestValidationPriorityStateBeforeZoneFrozen:

    def test_zone_frozen_fires_when_state_check_passes(self, api):
        """PRD §2.12 priority pinning (state-before-business_safety).
        When the state check would pass (receipt is INSPECTED), the
        next-in-priority business_safety check fires —
        ERR_ZONE_FROZEN.

        Difficulty-design: priority_pair_validation_conflict /
        state_vs_business_safety_zone_frozen_on_inspected_receipt
        (matched ZONE_FROZEN side — proves the priority chain is
        consistent: state fails first; if state passes, zone-frozen
        fires next).
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_zone_frozen_on_inspected_receipt

        Claim: receipt is INSPECTED (state check passes); zone is
        FROZEN (business_safety fires). Accept yields
        ERR_ZONE_FROZEN.
        """
        from test_helpers import record_temperature_event
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product(
            required_zone_type="REFRIGERATED",
        )
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1, visual_pass=True,
        )
        # nonconformance_reason is NONE, so accept is normally allowed.
        # Drive zone into FROZEN.
        record_temperature_event(
            topology["zone"]["id"], at_minutes=0, temp_c=12.0,
        )
        res = api.accept_receipt(
            receipt["id"], TEST_USERS["qa_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ZONE_FROZEN.value)

    def test_state_check_wins_over_zone_frozen(self, api):
        """PRD §2.12: "the practical implication is that, for example,
        a request that violates both a zone-frozen rule and a
        segregation rule surfaces as `ERR_ZONE_FROZEN`, not
        `ERR_SEGREGATION_VIOLATION` — the earlier rule wins."

        PRD §2.12 also pins state preconditions BEFORE business_safety:
        "State preconditions evaluate next, in the order receipt-
        pending check (`ERR_RECEIPT_NOT_PENDING`), receipt-inspected
        check (`ERR_RECEIPT_NOT_INSPECTED`), shipment state ...".
        Then: "Cold-chain safety follows: zone-frozen blocking
        (`ERR_ZONE_FROZEN`), then supplier qualification".

        Difficulty-design: priority_pair_validation_conflict /
        state_vs_business_safety_zone_frozen_on_inspected_receipt.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_zone_frozen_on_inspected_receipt

        Claim: a QUARANTINED receipt (NOT in INSPECTED) targets a
        FROZEN-posture zone. Accept yields ERR_RECEIPT_NOT_INSPECTED
        (state wins over zone-frozen).
        """
        from test_helpers import (
            quarantine_receipt,
            record_temperature_event,
        )
        topology = setup_basic_topology()
        supplier, product = setup_qualified_supplier_and_product(
            required_zone_type="REFRIGERATED",
        )
        # Inspect a receipt that will fail nonconformance (visual=false)
        # so we can quarantine it.
        receipt = create_inspected_receipt(
            topology["warehouse"]["id"],
            supplier["id"], product["id"],
            quantity_units=1, visual_pass=False,
        )
        # Quarantine it (nonconformance_reason=VISUAL_FAIL).
        quarantine_receipt(receipt["id"])
        # Drive the storage zone into FROZEN.
        record_temperature_event(
            topology["zone"]["id"], at_minutes=0, temp_c=12.0,
        )
        # Now try to accept the QUARANTINED receipt.
        res = api.accept_receipt(
            receipt["id"], TEST_USERS["qa_officer_headers"],
        )
        # State wins (priority 7) over zone-frozen (priority 11).
        validate_error(res, ApiErrorId.ERR_RECEIPT_NOT_INSPECTED.value)

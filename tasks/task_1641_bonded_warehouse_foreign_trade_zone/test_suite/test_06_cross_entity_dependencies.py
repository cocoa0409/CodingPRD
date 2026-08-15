"""Cross-entity state dependencies: (Admission, Zone) activity gating.

Removed: TestWithdrawalAttachRequiresOpenEntry (both tests) — PRD declares
ERR_ENTRY_NOT_OPEN only at withdrawal filing and cancellation (§3.5), never at
withdrawal creation; §3.6 enumerates only same-zone and same-importer attach
constraints. The create-time OPEN gate traces solely to
SCAFFOLD_DIFFICULTY_DESIGN `withdrawal_attach_requires_open_entry`, which
mis-grounds the DRAFT->FILED filing precondition as a creation rule.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_admission,
    create_zone,
    get_success_data,
    make_customs_officer_headers,
    make_zone_operator_headers,
    submit_admission,
    suspend_zone,
    validate_error,
    validate_paginated,
)


class TestAdmitRequiresZoneActive:
    """Entity pair (Admission, Zone): SUBMITTED -> ADMITTED gated on the parent
    zone being ACTIVE."""

    def _setup_submitted_under_suspended_zone(self):
        zone = create_zone(bond_coverage_cents=10_000_000_000, name="Gate Zone 2", zone_code="Z-X2")
        a = create_admission(zone["id"], importer_id="imp-1", description="Dairy",
                             hts_code="0401.10", quantity=5, unit_value_cents=1000,
                             zone_status="NON_PRIVILEGED_FOREIGN")
        submit_admission(a["id"], importer_id="imp-1")
        suspend_zone(zone["id"])
        return zone, a

    def test_admit_under_suspended_zone_rejected(self):
        """PRD §3.2: "Admission enforces four checks beyond the transition itself:
        the zone must be `ACTIVE` with posture `NORMAL`"
        PRD §2.10: "many operations require the zone's `status` to be `ACTIVE`, and
        reject with `ERR_ZONE_NOT_ACTIVE` (HTTP 409) when it is not."

        Design: Difficulty/cross_entity_state_dependency/admit_requires_zone_active
        """
        zone, a = self._setup_submitted_under_suspended_zone()
        customs = make_customs_officer_headers()
        resp = api_client.admit_admission(a["id"], customs)
        validate_error(resp, ApiErrorId.ERR_ZONE_NOT_ACTIVE, expected_status=409)

    def test_blocked_admit_creates_no_lot(self):
        """PRD §3.2: "Admitting stamps `admission_date` from the logical clock (the
        field is null beforehand) and creates an **InventoryLot** in `IN_ZONE`
        status" — a blocked admit creates nothing.

        Design: Difficulty/cross_entity_state_dependency/admit_requires_zone_active
        """
        zone, a = self._setup_submitted_under_suspended_zone()
        customs = make_customs_officer_headers()
        api_client.admit_admission(a["id"], customs)

        op = make_zone_operator_headers()
        a_after = get_success_data(api_client.get_admission(a["id"], op))
        assert a_after["status"] == "SUBMITTED", (
            f"admission must remain SUBMITTED, got {a_after['status']}"
        )
        _lots, meta = validate_paginated(
            api_client.list_lots(op, params={"zone_id": zone["id"]})
        )
        assert meta["total_count"] == 0, f"no lot may be created, got {meta['total_count']}"

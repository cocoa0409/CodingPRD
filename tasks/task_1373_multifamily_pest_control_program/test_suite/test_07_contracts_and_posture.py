"""Contract terminal lockdown and the property-posture gate on lease creation."""
from test_helpers import (
    ApiErrorId,
    create_lease_payload,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    MANAGER,
    complete_positive_inspection,
    create_active_contract,
    create_property,
    create_technician,
    create_unit,
    setup_community,
)


class TestContractTerminal:
    def test_terminated_contract_rejects_suspend(self, api):
        """PRD §2.4: "Terminal states reject every further action with
        `ERR_ALREADY_TERMINAL` (HTTP 409); a transition that is simply not
        defined from the entity's current non-terminal state is rejected with
        `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.1: "From `ACTIVE` it may be suspended and later reactivated —
        reactivation requires that the current logical date has not passed the
        `end_date` — and either `ACTIVE` or `SUSPENDED` may be terminated
        outright."

        Design: Corner/state_machines/terminated_contract_rejects_suspend
        """
        prop = create_property(name="Term Hall", address="6 Term Way")
        contract = create_active_contract(prop["id"], scope_pest_types=["ROACHES"])
        validate_success(api.terminate_contract(contract["id"], ADMIN))
        resp = api.suspend_contract(contract["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestPostureGate:
    def _setup_restricted_property(self, api):
        """Three positive inspections on three units -> 3 OPEN cases ->
        posture RESTRICTED. Unit 104 (stack 4, floor 1) is not adjacent to any
        infested unit, so it receives no auto-created INITIAL inspection."""
        prop = create_property(name="Maple Annex", address="14 Maple Ave")
        create_active_contract(prop["id"], scope_pest_types=["BED_BUGS"])
        u101 = create_unit(prop["id"], unit_number="101", floor=1, stack_index=1)
        u102 = create_unit(prop["id"], unit_number="102", floor=1, stack_index=2)
        u201 = create_unit(prop["id"], unit_number="201", floor=2, stack_index=1)
        u104 = create_unit(prop["id"], unit_number="104", floor=1, stack_index=4)
        tech = create_technician()
        complete_positive_inspection(u101["id"], tech, scheduled_for="2026-08-05T09:00:00Z")
        complete_positive_inspection(u102["id"], tech, scheduled_for="2026-08-05T10:00:00Z")
        complete_positive_inspection(u201["id"], tech, scheduled_for="2026-08-05T11:00:00Z")
        return prop, u104

    def test_lease_creation_gated_by_property_posture(self, api):
        """PRD §3.2: "Lease creation is refused while the property's `posture`
        is `RESTRICTED`, returning `ERR_PROPERTY_RESTRICTED` (HTTP 409) — a
        community in a full bed bug response does not paper new tenancies."

        Design: Difficulty/cross_entity_state_dependency/lease_creation_gated_by_property_posture
        """
        prop, u104 = self._setup_restricted_property(api)
        resp = api.create_lease(u104["id"], create_lease_payload(), MANAGER)
        validate_error(resp, ApiErrorId.ERR_PROPERTY_RESTRICTED)

    def test_restricted_posture_confirmed_at_three_open_cases(self, api):
        """PRD §3.1: "`posture`, which is `RESTRICTED` when that count reaches
        at least 3, `ELEVATED` when it is at least 1, and `STANDARD` otherwise.
        The count thresholds are inclusive, and both indicators recompute on
        every case creation, reopen, and clearance."
        PRD §3.2: "Lease creation is refused while the property's `posture` is
        `RESTRICTED`, returning `ERR_PROPERTY_RESTRICTED` (HTTP 409) — a
        community in a full bed bug response does not paper new tenancies."

        Design: Difficulty/cross_entity_state_dependency/lease_creation_gated_by_property_posture
        """
        prop, u104 = self._setup_restricted_property(api)
        summary = validate_success(api.get_property_summary(prop["id"], MANAGER))
        assert summary["open_bed_bug_case_count"] == 3
        assert summary["posture"] == "RESTRICTED", "the >= 3 boundary is inclusive"
        resp = api.create_lease(u104["id"], create_lease_payload(), MANAGER)
        validate_error(resp, ApiErrorId.ERR_PROPERTY_RESTRICTED)

"""Role-based access control and the customs broker handoff (PRD §2.1, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    clear_hwb,
    create_booking,
    create_customs_entry,
    create_flight_booking_payload,
    create_hwb,
    create_known_shipper,
    create_shipper,
    get_hwb,
    list_screening_records,
    make_compliance_officer_headers,
    make_forwarder_ops_headers,
    resolve_screening,
    submit_hwb,
    transition_customs_entry,
    validate_error,
    validate_success,
)


class TestExclusiveOperations:
    def test_forwarder_ops_cannot_verify_shipper_returns_forbidden(
        self, api, forwarder_ops_headers
    ):
        """PRD §4: "`/air-freight/shippers/{id}/verify-known-shipper` | Verify an
        UNVERIFIED shipper as KNOWN, or reinstate a SUSPENDED shipper (resets demerit
        count) | ComplianceOfficer"
        PRD §2.1: "A request whose role is recognized but not permitted for the
        attempted operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/forwarder_ops_cannot_verify_shipper_returns_forbidden
        """
        shipper = create_shipper()
        resp = api.verify_known_shipper(shipper["id"], forwarder_ops_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        after = validate_success(api.get_shipper(shipper["id"], forwarder_ops_headers))
        assert after["known_shipper_status"] == "UNVERIFIED", (
            "rejected verification must not change the shipper's standing"
        )

    def test_claims_adjuster_cannot_create_booking_returns_forbidden(
        self, api, claims_adjuster_headers
    ):
        """PRD §4: "`/air-freight/flight-bookings` | Procure capacity from an airline
        (booked allotment on one flight) | CapacityPlanner"
        PRD §2.1: "A request whose role is recognized but not permitted for the
        attempted operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/claims_adjuster_cannot_create_booking_returns_forbidden
        """
        resp = api.create_flight_booking(
            create_flight_booking_payload(), claims_adjuster_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestCustomsRoleMap:
    def test_customs_transition_role_map_enforced(
        self, api, forwarder_ops_headers, customs_broker_headers
    ):
        """PRD §2.1: "On the customs entry transition operation, the permitted role
        depends on the requested `target_status`: advancing an entry to `HANDED_OFF`,
        or returning a rejected entry to `PREPARING` for rework, is a `ForwarderOps`
        action, while advancing an entry to `FILED`, `RELEASED`, or `REJECTED` is a
        `CustomsBroker` action. A caller holding the wrong role for the requested
        target receives `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/customs_transition_role_map_enforced
        """
        shipper = create_known_shipper()
        hwb = create_hwb(
            shipper["id"], "HWB-CU", pieces=3, gross_weight_kg=25.0,
            declared_volume_m3=0.12,
        )
        clear_hwb(hwb["id"])
        entry = create_customs_entry(hwb["id"], entry_type="CONSUMPTION")

        err1 = api.transition_customs_entry(
            entry["id"], {"target_status": "HANDED_OFF"}, customs_broker_headers
        )
        validate_error(err1, ApiErrorId.ERR_FORBIDDEN_ROLE)

        handed_off = transition_customs_entry(
            entry["id"], "HANDED_OFF", forwarder_ops_headers
        )
        assert handed_off["status"] == "HANDED_OFF"

        err2 = api.transition_customs_entry(
            entry["id"], {"target_status": "FILED"}, forwarder_ops_headers
        )
        validate_error(err2, ApiErrorId.ERR_FORBIDDEN_ROLE)

        filed = transition_customs_entry(
            entry["id"], "FILED", customs_broker_headers, broker_reference="BRK-001"
        )
        assert filed["status"] == "FILED"
        assert filed["broker_reference"] == "BRK-001"


class TestSegregationOfDuties:
    def test_segregation_of_duties_same_user_cannot_resolve_own_submission(self, api):
        """PRD §3.3: "Segregation of duties is enforced here: the resolver's
        `X-User-ID` must differ from the waybill's `submitted_by_user_id`, and a
        violation is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/segregation_of_duties_same_user_cannot_resolve_own_submission
        """
        shipper = create_known_shipper()
        hwb = create_hwb(
            shipper["id"], "HWB-SOD", pieces=1, gross_weight_kg=10.0,
            declared_volume_m3=0.05,
        )
        submit_hwb(hwb["id"], user_id="ops-1")
        record = list_screening_records(hwb["id"])[0]

        err = api.resolve_screening_record(
            record["id"], {"outcome": "CLEARED"}, make_compliance_officer_headers("ops-1")
        )
        validate_error(err, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        resolved = resolve_screening(record["id"], "CLEARED", user_id="comp-1")
        assert resolved["result"] == "CLEARED"
        assert resolved["resolved_by_user_id"] == "comp-1"
        assert get_hwb(hwb["id"])["status"] == "CLEARED", (
            "clearing the only required record must bubble the waybill to CLEARED"
        )


class TestCustomsReworkCycle:
    def test_customs_entry_rework_cycle_and_handoff_gate(
        self, api, forwarder_ops_headers, customs_broker_headers
    ):
        """PRD §3.7: "Handing off a `PREPARING` entry to `HANDED_OFF` is a
        `ForwarderOps` action and additionally requires the underlying waybill to have
        cleared screening — specifically, to be in `CLEARED`, `CONSOLIDATED`,
        `TENDERED`, `IN_TRANSIT`, or `DELIVERED`; otherwise `ERR_HWB_NOT_CLEARED`."
        PRD §3.7: "A rejected entry is not dead: a `ForwarderOps` agent returns it
        from `REJECTED` to `PREPARING` for rework, and the cycle begins again."

        Design: Corner/state_machines/customs_entry_rework_cycle_and_handoff_gate
        """
        shipper = create_known_shipper()
        hwb = create_hwb(
            shipper["id"], "HWB-CU", pieces=3, gross_weight_kg=25.0,
            declared_volume_m3=0.12,
        )
        submit_hwb(hwb["id"])
        record = list_screening_records(hwb["id"])[0]
        entry = create_customs_entry(hwb["id"], entry_type="CONSUMPTION")
        assert entry["status"] == "PREPARING"

        gate = api.transition_customs_entry(
            entry["id"], {"target_status": "HANDED_OFF"}, forwarder_ops_headers
        )
        validate_error(gate, ApiErrorId.ERR_HWB_NOT_CLEARED)

        resolve_screening(record["id"], "CLEARED")
        assert get_hwb(hwb["id"])["status"] == "CLEARED"

        handed_off = transition_customs_entry(
            entry["id"], "HANDED_OFF", forwarder_ops_headers
        )
        assert handed_off["status"] == "HANDED_OFF"

        filed = transition_customs_entry(
            entry["id"], "FILED", customs_broker_headers, broker_reference="BRK-001"
        )
        assert filed["status"] == "FILED"

        rejected = transition_customs_entry(
            entry["id"], "REJECTED", customs_broker_headers,
            rejection_reason="HTS misclassification",
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "HTS misclassification"

        rework = transition_customs_entry(
            entry["id"], "PREPARING", forwarder_ops_headers
        )
        assert rework["status"] == "PREPARING"

        transition_customs_entry(entry["id"], "HANDED_OFF", forwarder_ops_headers)
        transition_customs_entry(
            entry["id"], "FILED", customs_broker_headers, broker_reference="BRK-002"
        )
        released = transition_customs_entry(
            entry["id"], "RELEASED", customs_broker_headers
        )
        assert released["status"] == "RELEASED"

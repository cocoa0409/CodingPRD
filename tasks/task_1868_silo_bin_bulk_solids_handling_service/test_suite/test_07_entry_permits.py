"""Entry permit safety cluster: lockout, SoD, engulfment control, atmosphere,
close-with-findings auto ticket, and invalid from-states."""
import pytest

from test_helpers import (
    ApiErrorId,
    make_plant_operator_headers,
    make_safety_officer_headers,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    create_active_permit,
    create_approved_ticket,
    create_draft_permit,
    create_issued_permit,
    create_site,
    create_site_vessel_technician,
    create_vessel,
    create_vessel_with_dispatched_order,
    post_reading,
)
from test_helpers.test_users import TEST_USERS

SM = TEST_USERS["service_manager_headers"]
SO = TEST_USERS["safety_officer_headers"]


def _site_vessel_tech(name, vessel_overrides=None, tech_name="Tech P"):
    return create_site_vessel_technician(
        site_overrides={"name": name, "state_code": "IA"},
        vessel_overrides=vessel_overrides
        or {
            "name": "BIN-PC", "vessel_kind": "BIN", "capacity_tons": 50,
            "material_name": "salt", "reorder_point_pct": 30,
        },
        tech_overrides={"name": tech_name, "weekly_capacity_hours": 40},
    )


def _approved_entry_ticket(site, vessel, job_type="CLEANOUT"):
    return create_approved_ticket(
        site["id"], vessel["id"],
        job_type=job_type, requires_entry=True, est_hours=4, crew_size=1,
    )


class TestPermitInvalidState:
    def test_permit_close_from_draft_invalid_state(self, api):
        """PRD §3.8: "A `SafetyOfficer` closes an `ACTIVE` permit by supplying
        `findings`."
        PRD §3.8: "Permits in wrong from-states reject any of these transitions
        with `ERR_INVALID_PERMIT_STATE` (HTTP 409)."

        Design: Corner/state_machines/permit_close_from_draft_invalid_state
        """
        site, vessel, tech = _site_vessel_tech("PC Site")
        ticket = _approved_entry_ticket(site, vessel)
        permit = create_draft_permit(vessel["id"], ticket["id"], tech["id"])
        res = api.close_entry_permit(permit["id"], {"findings": "NONE"}, SO)
        validate_error(res, ApiErrorId.ERR_INVALID_PERMIT_STATE, expected_status=409)
        fetched = validate_success(api.get_entry_permit(permit["id"], SM), 200)
        assert fetched["status"] == "DRAFT"


class TestPermitIssueSafetyCluster:
    def test_sod_issuer_equals_entrant_rejected(self, api):
        """PRD §3.8: "Issue is refused when `lockout_checklist_confirmed` is not
        true (`ERR_LOCKOUT_NOT_VERIFIED`), when the issuing officer's `X-User-ID`
        equals the permit's `entrant_technician_id` (`ERR_SOD_ISSUER_EQUALS_ENTRANT`
        — segregation of duties), or when a replenishment order for the vessel is
        currently `DISPATCHED` (`ERR_INBOUND_DELIVERY_PENDING` — engulfment
        control)."

        Design: Corner/validations/sod_issuer_equals_entrant_rejected
        """
        site, vessel, tech = _site_vessel_tech("SD Site", tech_name="Tech S")
        ticket = _approved_entry_ticket(site, vessel)
        permit = create_draft_permit(vessel["id"], ticket["id"], tech["id"])
        # Issuer X-User-ID equals the entrant technician id
        res = api.issue_entry_permit(
            permit["id"],
            {"lockout_checklist_confirmed": True},
            make_safety_officer_headers(tech["id"]),
        )
        validate_error(
            res, ApiErrorId.ERR_SOD_ISSUER_EQUALS_ENTRANT, expected_status=409
        )
        fetched = validate_success(api.get_entry_permit(permit["id"], SM), 200)
        assert fetched["status"] == "DRAFT"

    def test_lockout_not_confirmed_rejected(self, api):
        """PRD §3.8: "Issue is refused when `lockout_checklist_confirmed` is not
        true (`ERR_LOCKOUT_NOT_VERIFIED`), when the issuing officer's `X-User-ID`
        equals the permit's `entrant_technician_id` (`ERR_SOD_ISSUER_EQUALS_ENTRANT`
        — segregation of duties), or when a replenishment order for the vessel is
        currently `DISPATCHED` (`ERR_INBOUND_DELIVERY_PENDING` — engulfment
        control)."

        Design: Corner/validations/lockout_not_confirmed_rejected
        """
        site, vessel, tech = _site_vessel_tech("LK Site", tech_name="Tech L")
        ticket = _approved_entry_ticket(site, vessel)
        permit = create_draft_permit(vessel["id"], ticket["id"], tech["id"])
        res = api.issue_entry_permit(
            permit["id"],
            {"lockout_checklist_confirmed": False},
            make_safety_officer_headers("so-1"),
        )
        validate_error(
            res, ApiErrorId.ERR_LOCKOUT_NOT_VERIFIED, expected_status=409
        )
        fetched = validate_success(api.get_entry_permit(permit["id"], SM), 200)
        assert fetched["status"] == "DRAFT"

    def test_atmosphere_unsafe_on_activate_rejected(self, api):
        """PRD §3.8: "The atmosphere passes when `oxygen_pct` is between 19.5 and
        23.5 inclusive on both ends, and `combustible_pct` (expressed as a
        percentage of the lower explosive limit) is at most 10.0. A failing reading
        is rejected with `ERR_ATMOSPHERE_UNSAFE`."

        Design: Corner/validations/atmosphere_unsafe_on_activate_rejected
        """
        site, vessel, tech = _site_vessel_tech("AT Site", tech_name="Tech A")
        ticket = _approved_entry_ticket(site, vessel)
        permit = create_issued_permit(
            vessel["id"], ticket["id"], tech["id"], issuer_user_id="so-1"
        )
        # oxygen 18.0 < 19.5
        res = api.activate_entry_permit(
            permit["id"], {"oxygen_pct": 18.0, "combustible_pct": 1.0}, SO
        )
        validate_error(res, ApiErrorId.ERR_ATMOSPHERE_UNSAFE, expected_status=409)
        fetched = validate_success(api.get_entry_permit(permit["id"], SM), 200)
        assert fetched["status"] == "ISSUED"


class TestPermitIssueEngulfmentControl:
    def _setup_permit_with_dispatched_order(self):
        site, vessel, order, _ = create_vessel_with_dispatched_order(
            site_overrides={"name": "Site Twelve", "state_code": "NE"},
            vessel_overrides={
                "name": "SILO-P", "capacity_tons": 100, "material_name": "wheat",
                "reorder_point_pct": 30, "target_fill_pct": 90,
            },
        )
        from test_helpers.fixtures import create_technician

        tech = create_technician(name="Tech Seven", weekly_capacity_hours=40)
        ticket = create_approved_ticket(
            site["id"], vessel["id"],
            job_type="CLEANOUT", requires_entry=True, est_hours=4, crew_size=1,
        )
        permit = create_draft_permit(vessel["id"], ticket["id"], tech["id"])
        return site, vessel, tech, order, permit

    def test_permit_issue_blocked_by_dispatched_inbound_order(self, api):
        """PRD §3.8: "Issue is refused when `lockout_checklist_confirmed` is not
        true (`ERR_LOCKOUT_NOT_VERIFIED`), when the issuing officer's `X-User-ID`
        equals the permit's `entrant_technician_id` (`ERR_SOD_ISSUER_EQUALS_ENTRANT`
        — segregation of duties), or when a replenishment order for the vessel is
        currently `DISPATCHED` (`ERR_INBOUND_DELIVERY_PENDING` — engulfment
        control)."

        Design: Difficulty/cross_entity_state_dependency/permit_issue_blocked_by_dispatched_inbound_order
        """
        site, vessel, tech, order, permit = (
            self._setup_permit_with_dispatched_order()
        )
        res = api.issue_entry_permit(
            permit["id"], {"lockout_checklist_confirmed": True}, SO
        )
        validate_error(
            res, ApiErrorId.ERR_INBOUND_DELIVERY_PENDING, expected_status=409
        )
        fetched = validate_success(api.get_entry_permit(permit["id"], SM), 200)
        assert fetched["status"] == "DRAFT"

    def test_permit_issue_succeeds_after_dispatched_order_received(self, api):
        """PRD §3.8: "On a successful issue the permit transitions from `DRAFT` to
        `ISSUED` and `issuer_user_id` is recorded from the acting officer's
        `X-User-ID`."
        PRD §3.8: "Issue is refused when `lockout_checklist_confirmed` is not true
        (`ERR_LOCKOUT_NOT_VERIFIED`), when the issuing officer's `X-User-ID` equals
        the permit's `entrant_technician_id` (`ERR_SOD_ISSUER_EQUALS_ENTRANT` —
        segregation of duties), or when a replenishment order for the vessel is
        currently `DISPATCHED` (`ERR_INBOUND_DELIVERY_PENDING` — engulfment
        control)."

        Design: Difficulty/cross_entity_state_dependency/permit_issue_blocked_by_dispatched_inbound_order
        """
        site, vessel, tech, order, permit = (
            self._setup_permit_with_dispatched_order()
        )
        # Receive the order so no DISPATCHED order remains for the vessel
        validate_success(
            api.receive_replenishment_order(
                order["id"],
                {"delivered_tons": 10.0, "received_at": "2026-08-03T00:00:00Z"},
                make_plant_operator_headers(site["id"]),
            ),
            200,
        )
        issued = validate_success(
            api.issue_entry_permit(
                permit["id"], {"lockout_checklist_confirmed": True},
                make_safety_officer_headers("so-issuer-9"),
            ),
            200,
        )
        assert issued["status"] == "ISSUED"
        assert issued["issuer_user_id"] == "so-issuer-9"


class TestPermitCloseFindings:
    def test_permit_close_with_findings_autocreates_diagnosis_ticket(self, api):
        """PRD §3.8: "When `findings` is anything other than `NONE` — for example
        `BRIDGING_OBSERVED` or `RATHOLING_OBSERVED` — the system auto-creates a
        follow-up `ServiceTicket` in `DRAFT` status with `site_id` copied from the
        vessel's owning site, `vessel_id` copied from the permit, `job_type` set to
        `DIAGNOSIS`, `requires_entry` set to false, `est_hours` set to 4,
        `crew_size` set to 1, and `source_permit_id` set to the closing permit's
        `id`; its `estimate_cents` is computed at creation per §3.6. The permit
        itself transitions to `CLOSED`."

        Design: Corner/state_machines/permit_close_with_findings_autocreates_diagnosis_ticket
        """
        site, vessel, tech = _site_vessel_tech("FD Site", tech_name="Tech F")
        ticket = _approved_entry_ticket(site, vessel)
        permit = create_active_permit(
            vessel["id"], ticket["id"], tech["id"],
            window_start="2026-08-10T08:00:00Z",
            window_end="2026-08-10T10:00:00Z",
            oxygen_pct=20.9, combustible_pct=1.0,
        )
        closed = validate_success(
            api.close_entry_permit(
                permit["id"], {"findings": "BRIDGING_OBSERVED"}, SO
            ),
            200,
        )
        assert closed["status"] == "CLOSED"

        data, meta = validate_paginated(
            api.list_service_tickets(SM, params={"source_permit_id": permit["id"]})
        )
        assert meta["total_count"] == 1
        auto = data[0]
        assert auto["job_type"] == "DIAGNOSIS"
        assert auto["status"] == "DRAFT"
        assert auto["requires_entry"] is False
        assert auto["est_hours"] == 4
        assert auto["crew_size"] == 1
        assert auto["vessel_id"] == vessel["id"]
        assert auto["site_id"] == site["id"]
        # 9500 x 4 x 1, NORMAL posture multiplier 1.0, discount 0
        assert auto["estimate_cents"] == 38000


class TestValidationPriority:
    def test_activate_draft_permit_state_error_beats_safety_error(self, api):
        """PRD §2.10: "Only after the body is well-formed does role-based
        authorization run (`ERR_FORBIDDEN`), then existence of every referenced
        resource (the appropriate `ERR_*_NOT_FOUND`), then the OCC check
        `ERR_STALE_VERSION` where applicable, then state-machine from-state
        validation (`ERR_INVALID_TICKET_STATE`, `ERR_INVALID_ORDER_STATE`,
        `ERR_INVALID_PERMIT_STATE`), then the bin-entry safety cluster (lockout,
        segregation of duties, engulfment control, atmosphere limits, entry-permit
        presence), then the temporal/scheduling cluster (window-in-past, technician
        double-booking, vessel downtime buffer, scale tolerance, inventory
        non-negativity), and finally the fiscal gate (`ERR_CREDIT_HOLD`)."

        Design: Difficulty/priority_pair_validation_conflict/activate_draft_permit_state_error_beats_safety_error
        """
        site, vessel, tech = _site_vessel_tech(
            "Site Nine",
            vessel_overrides={
                "name": "HOP-K", "vessel_kind": "HOPPER", "capacity_tons": 40,
                "material_name": "lime", "reorder_point_pct": 30,
            },
            tech_name="Tech Five",
        )
        ticket = create_approved_ticket(
            site["id"], vessel["id"],
            job_type="DIAGNOSIS", requires_entry=True, est_hours=4, crew_size=1,
        )
        permit = create_draft_permit(vessel["id"], ticket["id"], tech["id"])
        # DRAFT permit + fatally bad atmosphere: state check must win
        res = api.activate_entry_permit(
            permit["id"], {"oxygen_pct": 18.0, "combustible_pct": 50.0}, SO
        )
        validate_error(
            res, ApiErrorId.ERR_INVALID_PERMIT_STATE, expected_status=409
        )
        fetched = validate_success(api.get_entry_permit(permit["id"], SM), 200)
        assert fetched["status"] == "DRAFT"

    def test_activate_draft_permit_leaves_permit_unchanged(self, api):
        """PRD §3.8: "Permits in wrong from-states reject any of these transitions
        with `ERR_INVALID_PERMIT_STATE` (HTTP 409)."
        PRD §3.8: "Activation requires a pre-entry atmosphere test. A
        `SafetyOfficer` activates an `ISSUED` permit by supplying `oxygen_pct` and
        `combustible_pct`."

        Design: Difficulty/priority_pair_validation_conflict/activate_draft_permit_state_error_beats_safety_error
        """
        site, vessel, tech = _site_vessel_tech(
            "Site Nine",
            vessel_overrides={
                "name": "HOP-K", "vessel_kind": "HOPPER", "capacity_tons": 40,
                "material_name": "lime", "reorder_point_pct": 30,
            },
            tech_name="Tech Five",
        )
        ticket = create_approved_ticket(
            site["id"], vessel["id"],
            job_type="DIAGNOSIS", requires_entry=True, est_hours=4, crew_size=1,
        )
        permit = create_draft_permit(vessel["id"], ticket["id"], tech["id"])
        res = api.activate_entry_permit(
            permit["id"], {"oxygen_pct": 20.9, "combustible_pct": 1.0}, SO
        )
        # even passing atmosphere cannot activate a DRAFT permit
        validate_error(
            res, ApiErrorId.ERR_INVALID_PERMIT_STATE, expected_status=409
        )
        fetched = validate_success(api.get_entry_permit(permit["id"], SM), 200)
        assert fetched["status"] == "DRAFT"

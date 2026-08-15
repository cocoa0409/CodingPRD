"""Service visits, technician buffering, and emergency SLA (PRD §3.7)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    arrive_visit,
    complete_visit,
    create_service_visit_payload,
    create_visit,
    dispatch_visit,
    get_visit,
    make_customer_headers,
    make_field_technician_headers,
    request_emergency_visit,
    set_logical_clock,
    setup_on_rent_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

TEST_DISPATCH = TEST_USERS["fleet_dispatcher_headers"]


class TestEmergencyVisitLifecycle:
    def test_emergency_visit_sla_boundary_met(self, api):
        """PRD §3.7: "An emergency request carries no window: instead it stamps
        `requested_at` from the logical clock".
        PRD §3.7: "`response_minutes` is the number of seconds between `requested_at`
        and `arrived_at` divided by sixty and rounded up to whole minutes, and
        `sla_met` is true exactly when that figure is at most the customer's
        `sla_response_minutes` — a response landing precisely on the guarantee meets
        it."

        Design: Corner/state_machines/emergency_visit_happy_path_sla_boundary
        """
        bundle = setup_on_rent_contract(
            customer_overrides={
                "name": "Standby Co",
                "billing_email": "ops@standby.example",
                "standby_contract": True,
                "sla_response_minutes": 240,
            }
        )
        cid = bundle["contract"]["id"]
        customer_id = bundle["customer"]["id"]

        visit = request_emergency_visit(cid, customer_id)
        assert visit["status"] == "SCHEDULED"
        assert visit["requested_at"].startswith("2026-08-01T00:00:00"), (
            "requested_at is stamped from the startup logical clock"
        )

        dispatch_visit(visit["id"], "tech-9")
        # Exactly 240 minutes after the request: the boundary meets the SLA.
        set_logical_clock("2026-08-01T04:00:00Z")
        arrived = arrive_visit(visit["id"], "tech-9")
        assert arrived["status"] == "ON_SITE"
        assert arrived["response_minutes"] == 240
        assert arrived["sla_met"] is True

        completed = complete_visit(visit["id"], "tech-9")
        assert completed["status"] == "COMPLETED"

    def test_emergency_requires_standby_contract(self, api):
        """PRD §3.7: "it is gated twice — the customer must hold a standby agreement
        or the request is rejected with `ERR_STANDBY_CONTRACT_REQUIRED` (HTTP 422),
        and the contract must stand in `ON_RENT` or `SUSPENDED` or the request fails
        the state tier with `ERR_INVALID_STATE`."

        Design: Corner/validations/emergency_requires_standby_contract
        """
        bundle = setup_on_rent_contract()  # default customer: standby_contract false
        cid = bundle["contract"]["id"]

        res = api.create_service_visit(
            create_service_visit_payload(cid, "EMERGENCY"),
            make_customer_headers(bundle["customer"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_STANDBY_CONTRACT_REQUIRED, expected_status=422)

        _, meta = validate_paginated(
            api.list_service_visits(TEST_DISPATCH, params={"contract_id": cid})
        )
        assert meta["total_count"] == 0, "the rejected emergency request persists nothing"


class TestTechnicianBufferedOverlap:
    def _setup_on_rent_with_first_visit(self, api):
        """ON_RENT contract (window 09-01..09-15) with tech-7 visit SCHEDULED
        2026-09-05 10:00-11:00; clock at 2026-09-03."""
        bundle = setup_on_rent_contract(
            contract_overrides={"expected_offhire_date": "2026-09-15T00:00:00Z"},
            clock_after_start="2026-09-03T00:00:00Z",
        )
        visit_a = create_visit(
            bundle["contract"]["id"], "TECHNICIAN",
            scheduled_start="2026-09-05T10:00:00Z",
            scheduled_end="2026-09-05T11:00:00Z",
            assigned_technician_id="tech-7",
        )
        return bundle, visit_a

    def test_sixty_minute_gap_conflicts(self, api):
        """PRD §3.7: "Each visit occupies a buffered window that begins sixty minutes
        before its scheduled start and ends sixty minutes after its scheduled end,
        exclusive at the upper edge. Two visits assigned to the same technician
        conflict when their buffered windows intersect — ignoring visits that have
        been cancelled — and the conflict is rejected with
        `ERR_TECHNICIAN_SCHEDULE_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/technician_buffered_overlap
        """
        bundle, visit_a = self._setup_on_rent_with_first_visit(api)
        # 12:00 start is only a 60-minute gap after the 11:00 end: the first visit's
        # buffered window [09:00, 12:00) intersects this visit's [11:00, 14:00).
        res = api.create_service_visit(
            create_service_visit_payload(
                bundle["contract"]["id"], "TECHNICIAN",
                scheduled_start="2026-09-05T12:00:00Z",
                scheduled_end="2026-09-05T13:00:00Z",
                assigned_technician_id="tech-7",
            ),
            TEST_DISPATCH,
        )
        validate_error(
            res, ApiErrorId.ERR_TECHNICIAN_SCHEDULE_CONFLICT, expected_status=409
        )
        assert get_visit(visit_a["id"])["status"] == "SCHEDULED"

    def test_exactly_120_minute_gap_allowed(self, api):
        """PRD §3.7: "Because the buffer's upper edge is exclusive, a gap of exactly
        two hours between one visit's scheduled end and the next visit's scheduled
        start leaves the buffered intervals merely touching and is permitted."

        Design: Difficulty/resource_temporal_overlap/technician_buffered_overlap
        """
        bundle, visit_a = self._setup_on_rent_with_first_visit(api)
        # 13:00 start leaves exactly 120 minutes after the 11:00 end: the buffered
        # windows [09:00, 12:00) and [12:00, 15:00) merely touch.
        visit_c = create_visit(
            bundle["contract"]["id"], "TECHNICIAN",
            scheduled_start="2026-09-05T13:00:00Z",
            scheduled_end="2026-09-05T14:00:00Z",
            assigned_technician_id="tech-7",
        )
        assert visit_c["status"] == "SCHEDULED"
        assert get_visit(visit_a["id"])["status"] == "SCHEDULED"


class TestTechnicianOwnership:
    def test_technician_cannot_arrive_unassigned_visit(self, api):
        """PRD §3.7: "A `FieldTechnician` arrives a dispatched visit — `DISPATCHED →
        ON_SITE` — and completes an on-site visit — `ON_SITE → COMPLETED` — and for
        both actions the acting `X-User-ID` must equal the visit's
        `assigned_technician_id`, with any other technician rejected as
        `ERR_NOT_OWNER`."

        Design: Corner/rbac/technician_cannot_arrive_unassigned_visit
        """
        bundle = setup_on_rent_contract()
        visit = create_visit(
            bundle["contract"]["id"], "TECHNICIAN",
            scheduled_start="2026-08-03T10:00:00Z",
            scheduled_end="2026-08-03T11:00:00Z",
        )
        dispatch_visit(visit["id"], "tech-1")

        wrong = api.arrive_visit(
            visit["id"], make_field_technician_headers("tech-2")
        )
        validate_error(wrong, ApiErrorId.ERR_NOT_OWNER, expected_status=403)
        assert get_visit(visit["id"])["status"] == "DISPATCHED"

        arrived = arrive_visit(visit["id"], "tech-1")
        assert arrived["status"] == "ON_SITE"

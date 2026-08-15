"""Reference-estate creation rules: service lines and cost centers (PRD §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_service_line,
    create_cost_center_payload,
    create_service_line_payload,
    get_success_data,
    validate_error,
    validate_success,
)

FC = TEST_USERS["finance_controller_headers"]


class TestServiceLineCreation:
    def test_service_line_creation_defaults_applied(self, api):
        """PRD §3.1: "A new service line starts in `ACTIVE` status with its
        computed rollup fields — `total_direct_cost`, `total_revenue`, and
        `contribution_margin` — initialized to zero; thereafter the ledger rules
        of §2.8 take over, under which `total_direct_cost` is the line's
        `base_direct_cost` plus the allocated indirect totals of its posted cases."

        Design: Corner/entities/service_line_creation_defaults_applied
        """
        created = validate_success(
            api.create_service_line(
                create_service_line_payload(
                    name="Orthopedic Surgery", code="ORTHO",
                    base_direct_cost=9000.00, budgeted_volume=120,
                ),
                FC,
            ),
            expected_status=201,
        )
        assert_service_line(created)

        fetched = validate_success(api.get_service_line(created["id"], FC))
        assert fetched["status"] == "ACTIVE"
        assert fetched["total_direct_cost"] == pytest.approx(0.00, abs=0.005)
        assert fetched["total_revenue"] == pytest.approx(0.00, abs=0.005)
        assert fetched["contribution_margin"] == pytest.approx(0.00, abs=0.005)

    def test_service_line_duplicate_code_rejected(self, api):
        """PRD §3.1: "A `FinanceController` begins by establishing the reference
        estate. A **service line** is created with a `name` (for example,
        "Orthopedic Surgery"), a `code` that must be unique across all service
        lines (for example, "ORTHO"), a non-negative `base_direct_cost`
        representing the direct fixed-cost baseline allocated to the line each
        period, and a `budgeted_volume`, an integer greater than zero expressing
        the budgeted case volume per period."

        Design: Corner/entities/service_line_duplicate_code_rejected
        """
        first = api.create_service_line(
            create_service_line_payload(code="ORTHO"), FC
        )
        assert first.status_code == 201, f"Setup failed: {first.text}"

        duplicate = api.create_service_line(
            create_service_line_payload(
                name="Ortho Duplicate", code="ORTHO",
                base_direct_cost=100.00, budgeted_volume=10,
            ),
            FC,
        )
        validate_error(duplicate, ApiErrorId.ERR_INVALID_REQUEST)


class TestCostCenterCapacity:
    def test_cost_center_minutes_capacity_required_when_minutes_measure(self, api):
        """PRD §2.6: "a center measured in `MINUTES` must supply
        `practical_capacity_minutes` greater than zero and must not carry
        `total_rvu`; a center measured in `RVU` must supply `total_rvu` greater
        than zero and must not carry `practical_capacity_minutes`; a center
        measured `NONE` carries neither."

        Design: Corner/entities/cost_center_minutes_capacity_required_when_minutes_measure
        """
        payload = {
            "name": "OR Minutes",
            "code": "ORMINS",
            "cost_type": "INDIRECT",
            "cost_behavior": "VARIABLE",
            "allocated_cost": 12000.00,
            "capacity_measure": "MINUTES",
        }
        resp = api.create_cost_center(payload, FC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

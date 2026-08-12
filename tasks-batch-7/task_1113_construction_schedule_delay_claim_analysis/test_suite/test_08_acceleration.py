"""Acceleration directives: state machine, cost-data requirements, and the two
cost-recovery variants (PRD §3.7)."""
from datetime import datetime

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    acceleration_complete_payload,
    acceleration_resolve_payload,
    create_project,
    create_acceleration_directive,
    setup_performing_directive,
    TEST_USERS,
    api_client,
    get_success_data,
)

CONTRACTOR = TEST_USERS["contractor_scheduler_headers"]
OWNER = TEST_USERS["owner_representative_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestNegotiationStateMachine:
    def test_acceleration_negotiate_only_from_disputed(self, api, owner_headers):
        """PRD §3.7: "The owner then opens negotiation, moving it from `DISPUTED` to
        `UNDER_NEGOTIATION`" — an ISSUED directive has no DISPUTED → negotiation
        path, so the state-machine precondition fires. PRD §2.6: "then the
        state-machine precondition of the targeted transition (`ERR_INVALID_STATE`,
        HTTP 409)".

        Design: Corner/state_machines/acceleration_negotiate_only_from_disputed
        """
        project = create_project()
        directive = create_acceleration_directive(project["id"])
        assert directive["status"] == "ISSUED"
        resp = api.negotiate_acceleration_directive(
            project["id"], directive["id"], owner_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCostRecoveryVariants:
    def test_resolve_records_payload_recovery_under_measured_mile(
        self, api, owner_headers
    ):
        """PRD §3.7: "resolution requires a payload specifying both the
        `recovery_variant` and the agreed `recovered_cost_cents`
        (`ERR_COST_DATA_MISSING` if either is absent), with the recovered amount
        taken from the payload. Resolution lands the directive in `RESOLVED`".

        Design: Difficulty/dual_variant_calc/acceleration_actual_cost_vs_measured_mile_on_directive
        """
        project = create_project(contract_completion_date="2026-08-01T00:00:00Z")
        ctx = setup_performing_directive(project["id"])
        aid = ctx["directive"]["id"]
        get_success_data(api_client.dispute_acceleration_directive(project["id"], aid, CONTRACTOR))
        get_success_data(api_client.negotiate_acceleration_directive(project["id"], aid, OWNER))
        resp = api.resolve_acceleration_directive(
            project["id"],
            aid,
            acceleration_resolve_payload("MEASURED_MILE", 80000),
            owner_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "RESOLVED"
        assert data["recovered_cost_cents"] == 80000, (
            "the recovered amount is taken from the resolution payload"
        )

    def test_completion_defaults_to_actual_cost_variant(self, api, contractor_headers):
        """PRD §3.7: "At completion the owner selects the `recovery_variant`:
        `ACTUAL_COST` — the default — recovers the documented actual amount
        regardless of the measured-mile analysis" and "Whichever variant is selected
        is written onto the directive's `recovery_variant`, the
        `recovered_cost_cents` is set to the selected variant's amount".

        Design: Difficulty/dual_variant_calc/acceleration_actual_cost_vs_measured_mile_on_directive
        """
        project = create_project(contract_completion_date="2026-08-01T00:00:00Z")
        ctx = setup_performing_directive(project["id"])
        aid = ctx["directive"]["id"]
        acknowledged = ctx["acknowledged"]
        # Acknowledgement freezes the reference point: baseline is the project's
        # current completion date, days_to_recover = 2026-08-01 - 2026-07-15 = 17.
        assert _parse(acknowledged["baseline_completion_date"]) == _parse(
            "2026-08-01T00:00:00Z"
        )
        assert acknowledged["days_to_recover"] == 17
        resp = api.complete_acceleration_directive(
            project["id"],
            aid,
            acceleration_complete_payload(100000, 200000),
            contractor_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "COMPLETED"
        assert data["recovery_variant"] == "ACTUAL_COST"
        assert data["recovered_cost_cents"] == 100000, (
            "the ACTUAL_COST default recovers the documented actual amount"
        )

    def test_completion_missing_cost_data_rejected(self, api, contractor_headers):
        """PRD §3.7: "Completion is reported by the contractor with both cost figures
        populated — the documented `actual_cost_cents` (overtime, premium freight,
        and the like) and the `measured_mile_cost_cents` derived from a measured-mile
        productivity analysis; a completion report missing either is rejected with
        `ERR_COST_DATA_MISSING`."

        Design: Difficulty/dual_variant_calc/acceleration_actual_cost_vs_measured_mile_on_directive
        """
        project = create_project(contract_completion_date="2026-08-01T00:00:00Z")
        ctx = setup_performing_directive(project["id"])
        aid = ctx["directive"]["id"]
        resp = api.complete_acceleration_directive(
            project["id"],
            aid,
            {"actual_cost_cents": 100000},  # measured_mile_cost_cents absent
            contractor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_COST_DATA_MISSING)

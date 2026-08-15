"""Discrepancy resolution workflow and diversion cases (PRD §3.7)."""
from test_helpers import (
    adjudicate_payload,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDiscrepancyResolutionWithAdjustment:
    def test_found_error_applies_compensating_adjustment(self, api, pharmacist_headers):
        """PRD §3.7: "Under `FOUND_ERROR`, an `adjustment_units` value must be present and non-zero — otherwise `ERR_INVALID_REQUEST` — and the system appends an `ADJUSTMENT` ledger event whose `units_delta` equals `adjustment_units`, adds `adjustment_units` to the pocket's `on_hand_units`, records the resolving pharmacist in `resolved_by_staff_id`, moves the case to `RESOLVED`, and increments both the case's `version` and the pocket's `version` by 1."

        Design: Corner/state_machines/discrepancy_case_full_lifecycle_with_adjustment
        """
        ns = fixtures.setup_discrepancy_case(
            schedule="C_II", restock_units=50, waste_units=4,
            physical_count_units=44,
        )
        case_id = ns.discrepancy_case_id
        assert case_id is not None  # variance -2 breaches the C_II threshold of 2
        case = validate_success(
            api.investigate_discrepancy_case(case_id, ns.pharmacist_headers), 200
        )
        assert case["status"] == "INVESTIGATING"
        case = validate_success(
            api.resolve_discrepancy_case(
                case_id,
                {"resolution": "FOUND_ERROR", "adjustment_units": -2},
                ns.pharmacist_headers,
            ),
            200,
        )
        assert case["status"] == "RESOLVED"
        assert case["resolution"] == "FOUND_ERROR"
        assert case["resolved_by_staff_id"] == ns.pharmacist["id"]
        pocket = validate_success(
            api.get_adc_pocket(ns.pocket["id"], pharmacist_headers), 200
        )
        # ADJUSTMENT -2 aligns the ledger to the physical count: 46 - 2 == 44
        assert pocket["on_hand_units"] == 44
        events, _ = validate_paginated(
            api.list_pocket_events(ns.pocket["id"], pharmacist_headers)
        )
        adjustments = [e for e in events if e["event_type"] == "ADJUSTMENT"]
        assert len(adjustments) == 1
        assert adjustments[0]["units_delta"] == -2


class TestDiscrepancyEscalationCreatesDiversionCase:
    def test_unresolved_escalate_opens_diversion_case(self, api, diversion_officer_headers):
        """PRD §3.7: "Under `UNRESOLVED_ESCALATE`, a `subject_staff_id` must be present — otherwise `ERR_INVALID_REQUEST` — and the system auto-creates a `DiversionCase` in `OPEN` status with `opened_via` of `ESCALATION`, the station taken from the pocket, the `source_discrepancy_case_id` pointing at this case, and the named subject; the discrepancy case records its `resolved_by_staff_id`, moves to `ESCALATED`, and increments its `version`."

        Design: Corner/state_machines/discrepancy_escalation_creates_diversion_case
        """
        ns = fixtures.setup_discrepancy_case(
            schedule="C_II", restock_units=50, waste_units=4,
            physical_count_units=44,
        )
        case_id = ns.discrepancy_case_id
        validate_success(
            api.investigate_discrepancy_case(case_id, ns.pharmacist_headers), 200
        )
        case = validate_success(
            api.resolve_discrepancy_case(
                case_id,
                {"resolution": "UNRESOLVED_ESCALATE",
                 "subject_staff_id": ns.technician["id"]},
                ns.pharmacist_headers,
            ),
            200,
        )
        assert case["status"] == "ESCALATED"
        rows, meta = validate_paginated(
            api.list_diversion_cases(
                diversion_officer_headers,
                params={"source_discrepancy_case_id": case_id},
            )
        )
        assert meta["total_count"] == 1
        diversion = rows[0]
        assert diversion["status"] == "OPEN"
        assert diversion["opened_via"] == "ESCALATION"
        assert diversion["station_id"] == ns.station["id"]
        assert diversion["subject_staff_id"] == ns.technician["id"]


class TestDiversionCaseAdjudicationBranching:
    def test_adjudication_branching_and_terminal_lockout(self, api, diversion_officer_headers):
        """PRD §3.7: "Review moves an `OPEN` case to `UNDER_REVIEW`, incrementing its `version`. Adjudication from `UNDER_REVIEW` branches on the supplied `outcome`: `SUBSTANTIATED` or `CLOSED_UNSUBSTANTIATED`, each terminal, each storing the supplied note in `outcome_note`."

        Design: Corner/state_machines/diversion_case_branching_adjudication
        """
        ns = fixtures.setup_diversion_case()
        case_id = ns.case["id"]
        assert ns.case["status"] == "OPEN"
        # Adjudication is only reachable from UNDER_REVIEW.
        resp = api.adjudicate_diversion_case(
            case_id, adjudicate_payload("SUBSTANTIATED", "too early"),
            diversion_officer_headers,
        )
        validate_error(resp, "ERR_INVALID_STATE", 409)
        reviewed = validate_success(
            api.review_diversion_case(case_id, diversion_officer_headers), 200
        )
        assert reviewed["status"] == "UNDER_REVIEW"
        final = validate_success(
            api.adjudicate_diversion_case(
                case_id, adjudicate_payload("SUBSTANTIATED", "confirmed"),
                diversion_officer_headers,
            ),
            200,
        )
        assert final["status"] == "SUBSTANTIATED"
        assert final["outcome_note"] == "confirmed"
        resp = api.adjudicate_diversion_case(
            case_id, adjudicate_payload("CLOSED_UNSUBSTANTIATED", "flip"),
            diversion_officer_headers,
        )
        validate_error(resp, "ERR_INVALID_STATE", 409)

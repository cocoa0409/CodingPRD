"""Test-accept cascade (PRD §3.4): acceptance auto-creates a defect, the defect
re-runs the condition score, and a score below the escalation threshold flags
the asset's pending outage windows for revalidation."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_certified_technician,
    create_outage_window,
    create_test_event,
    setup_asset,
    submit_test_event,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["ops_manager_headers"]


def _setup_submitted_fail_test() -> dict:
    """Asset (last maintenance 2026-01-15) + a future REQUESTED outage window +
    one SUBMITTED FAIL insulation test (400 Mohm @ 40C)."""
    base = setup_asset(
        "POWER_TRANSFORMER",
        criticality="HIGH",
        nameplate_mva=20,
        install_date="2020-05-01T00:00:00Z",
        last_maintenance_completed_at="2026-01-15T00:00:00Z",
    )
    window = create_outage_window(
        base["substation"]["id"], base["asset"]["id"],
        "2026-09-05T08:00:00Z", "2026-09-05T16:00:00Z",
        purpose="Planned maintenance",
    )
    _, tech_headers = create_certified_technician("NETA_LEVEL_2")
    event = create_test_event(
        base["asset"]["id"], tech_headers, "INSULATION_RESISTANCE",
        value_primary=400, ambient_temp_c=40, measured_at="2026-07-20T10:00:00Z",
    )
    submit_test_event(event["id"], tech_headers)
    return {**base, "window": window, "tech_headers": tech_headers, "event": event}


class TestAcceptCascadeDepth3:
    def test_accept_fail_auto_creates_c2_defect(self):
        """PRD §3.4: "Second, when the accepted `result` is `MARGINAL` or
        `FAIL`, the platform auto-creates a `Defect` on the same asset with
        `test_event_id` pointing at the accepted event, a system-generated
        `title`, severity mapped from the result (`FAIL` becomes `C2`;
        `MARGINAL` becomes `C3` — any severity supplied by the caller on this
        path is ignored), and status `OPEN`."

        Design: Difficulty/transitive_cascade/test_accept_cascade_depth3
        """
        ctx = _setup_submitted_fail_test()
        validate_success(
            api_client.review_test_event(
                ctx["event"]["id"], {"decision": "ACCEPT"},
                TEST_USERS["compliance_headers"],
            )
        )
        defects, meta = validate_paginated(
            api_client.list_defects(OPS)
        )
        assert meta["total_count"] == 1, "exactly one auto-created defect expected"
        defect = defects[0]
        assert defect["asset_id"] == ctx["asset"]["id"]
        assert defect["test_event_id"] == ctx["event"]["id"]
        assert defect["severity"] == "C2"  # FAIL maps to C2
        assert defect["status"] == "OPEN"

    def test_accept_cascade_recomputes_score_and_flags_window(self):
        """PRD §3.4: "Third, the defect creation re-runs the condition-score
        computation so the new defect's penalty lands immediately; if the
        recomputed score has fallen strictly below the policy's
        `condition_escalation_threshold`, every outage window of the asset
        still in `REQUESTED` or `APPROVED` has `needs_revalidation` set true,
        and the asset's `next_due_date` is recomputed."
        PRD §3.5: "The penalty is computed over the asset's defects in `OPEN`,
        `WORK_ORDERED`, or `DEFERRED`: each `C1` defect subtracts 5, each `C2`
        subtracts 2, each `C3` subtracts 1."

        Design: Difficulty/transitive_cascade/test_accept_cascade_depth3
        """
        ctx = _setup_submitted_fail_test()
        validate_success(
            api_client.review_test_event(
                ctx["event"]["id"], {"decision": "ACCEPT"},
                TEST_USERS["compliance_headers"],
            )
        )
        asset = validate_success(api_client.get_asset(ctx["asset"]["id"], OPS))
        # Only the insulation component is present: base = 0.4*30/0.4 = 30.00;
        # the auto-created C2 defect subtracts 2 -> 28.00.
        assert asset["condition_score"] == pytest.approx(28.00, abs=0.01)
        # 28.00 < critical threshold 40 -> interval quartered: 12/4 = 3 months
        # from the 2026-01-15 baseline.
        assert asset["next_due_date"] == "2026-04-15"
        window = validate_success(api_client.get_outage_window(ctx["window"]["id"], OPS))
        assert window["needs_revalidation"] is True

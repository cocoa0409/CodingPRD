"""Cross-entity workflow reads: initial states at creation and the
milestone-driven circuit status chain (PRD §3.1–§3.6, §3.9)."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    validate_success,
    create_circuit,
    create_window,
    approve_window,
    create_job,
    plan_job,
    create_permit,
    issue_permit,
    verify_grounding,
    create_unit,
    create_assignment,
    confirm_assignment,
    create_health_assessment,
    set_clock,
    activate_window,
    create_series,
    energize_series,
    get_circuit,
    get_success_data,
)

SUPERVISOR = TEST_USERS["test_supervisor_headers"]


class TestInitialStates:
    def test_every_creatable_entity_starts_in_its_initial_state(self, api):
        """PRD §3.2: "The new window lands in `REQUESTED` and its
        `duration_minutes` is computed immediately as the whole minutes
        between the two bounds".
        PRD §3.3: "A created job starts in `DRAFT` with `estimate_cents` still
        null and `committed_cost_cents` at zero."
        PRD §3.4: "The draft permit starts in `DRAFT`."
        PRD §3.5: "New units start `AVAILABLE` with `committed_hours` at 0.0."
        and "A created assignment lands in `RESERVED`".
        PRD §3.9: "the new assessment lands in `COMPUTED`".

        Design: Corner/state_machines/initial_states_on_create
        """
        circuit = create_circuit("CKT-S4")
        window = create_window(circuit["id"])
        assert window["status"] == "REQUESTED"

        approve_window(window["id"])
        job = create_job(circuit["id"], window["id"], approved_budget_cents=800000)
        assert job["status"] == "DRAFT"
        assert job["estimate_cents"] is None
        assert job["committed_cost_cents"] == 0

        plan_job(job["id"])
        permit = create_permit(job["id"])
        assert permit["status"] == "DRAFT"

        unit = create_unit(capabilities=["VLF"])
        assert unit["status"] == "AVAILABLE"
        assert unit["committed_hours"] == 0.0

        assignment = create_assignment(
            unit["id"], job["id"],
            mobilize_at="2026-08-10T07:00:00Z", demobilize_at="2026-08-10T11:00:00Z",
        )
        assert assignment["status"] == "RESERVED"

        assessment = create_health_assessment(circuit["id"], "FORMAL")
        assert assessment["status"] == "COMPUTED"


class TestCircuitStatusChain:
    def test_circuit_status_follows_child_milestones(self, api):
        """PRD §3.1: "From then on the circuit's status is never set directly;
        it is a pure reflection of child activity through the cyclic chain
        `IN_SERVICE` → `OUTAGE_PENDING` → `DE_ENERGIZED` → `GROUNDED` →
        `UNDER_TEST` → `TEST_COMPLETE` → `RESTORING` → `IN_SERVICE`, driven by
        window approval, permit issuance, grounding verification, series
        energization, job evaluation, permit release, and window closure
        respectively".

        Design: Corner/state_machines/circuit_auto_status_progression
        """
        circuit = create_circuit("CKT-S5")
        assert circuit["status"] == "IN_SERVICE"

        window = create_window(circuit["id"])
        assert get_circuit(circuit["id"])["status"] == "IN_SERVICE", (
            "a window request alone does not move the circuit; approval does"
        )

        approve_window(window["id"])
        assert get_circuit(circuit["id"])["status"] == "OUTAGE_PENDING"

        job = plan_job(create_job(circuit["id"], window["id"],
                                  approved_budget_cents=800000)["id"])
        permit = create_permit(job["id"])
        assert get_circuit(circuit["id"])["status"] == "OUTAGE_PENDING", (
            "job planning and permit drafting move nothing on the circuit"
        )

        issue_permit(permit["id"])
        assert get_circuit(circuit["id"])["status"] == "DE_ENERGIZED"

        verify_grounding(permit["id"])
        assert get_circuit(circuit["id"])["status"] == "GROUNDED"

        unit = create_unit()
        confirm_assignment(create_assignment(unit["id"], job["id"])["id"])
        set_clock("2026-08-10T09:00:00Z")
        activate_window(window["id"])
        get_success_data(api_client.start_job(job["id"], SUPERVISOR))
        assert get_circuit(circuit["id"])["status"] == "GROUNDED", (
            "job start is not among the circuit-driving milestones"
        )

        series = create_series(job["id"])
        energize_series(series["id"])
        assert get_circuit(circuit["id"])["status"] == "UNDER_TEST"

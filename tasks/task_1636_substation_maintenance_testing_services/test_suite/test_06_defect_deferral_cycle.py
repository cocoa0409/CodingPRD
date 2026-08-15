"""Defect deferral cycle (PRD §3.6, §2.7): OPEN -> DEFERRED -> OPEN via the
clock, then a second deferral — the loop terminates only at the cap of 2."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_defect,
    create_technician,
    make_technician_headers,
    set_clock,
    setup_asset,
    validate_success,
)

OPS = TEST_USERS["ops_manager_headers"]


def _setup_open_c3_defect() -> dict:
    base = setup_asset(
        "CIRCUIT_BREAKER", criticality="LOW", voltage_kv=34.5,
        install_date="2018-06-01T00:00:00Z",
    )
    tech = create_technician()
    defect = create_defect(
        base["asset"]["id"], make_technician_headers(tech["id"]), "C3",
        title="Minor paint peeling", description="Cosmetic",
    )
    return {**base, "technician": tech, "defect": defect}


class TestDefectDeferralCycle:
    def test_deferred_defect_auto_reopens_when_clock_passes(self):
        """PRD §3.6: "Successful deferral transitions `OPEN → DEFERRED`,
        increments `deferral_count`, and records `deferred_until`."
        PRD §2.7: "any `Defect` in `DEFERRED` whose `deferred_until` is at or
        before the new clock value reopens to `OPEN` and clears its
        `deferred_until`".

        Design: Difficulty/non_linear_state_machine/defect_deferral_cycle
        """
        ctx = _setup_open_c3_defect()
        defect_id = ctx["defect"]["id"]
        assert ctx["defect"]["deferral_count"] == 0

        deferred = validate_success(
            api_client.defer_defect(defect_id, {"deferred_until": "2026-09-01T00:00:00Z"}, OPS)
        )
        assert deferred["status"] == "DEFERRED"
        assert deferred["deferral_count"] == 1

        set_clock("2026-09-02T00:00:00Z")
        reopened = validate_success(api_client.get_defect(defect_id, OPS))
        assert reopened["status"] == "OPEN"
        assert reopened["deferred_until"] is None

    def test_second_deferral_after_reopen_reaches_cap(self):
        """PRD §3.6: "A defect may be deferred at most twice: a deferral
        attempted when `deferral_count` is already 2 is rejected with
        `ERR_DEFERRAL_LIMIT_EXCEEDED` (HTTP 422)."
        PRD §2.7: "any `Defect` in `DEFERRED` whose `deferred_until` is at or
        before the new clock value reopens to `OPEN` and clears its
        `deferred_until`".

        Design: Difficulty/non_linear_state_machine/defect_deferral_cycle
        """
        ctx = _setup_open_c3_defect()
        defect_id = ctx["defect"]["id"]

        validate_success(
            api_client.defer_defect(defect_id, {"deferred_until": "2026-09-01T00:00:00Z"}, OPS)
        )
        set_clock("2026-09-02T00:00:00Z")
        reopened = validate_success(api_client.get_defect(defect_id, OPS))
        assert reopened["status"] == "OPEN"

        # Second deferral is legal after the clock-driven reopen: count 1 -> 2.
        deferred = validate_success(
            api_client.defer_defect(defect_id, {"deferred_until": "2026-10-01T00:00:00Z"}, OPS)
        )
        assert deferred["status"] == "DEFERRED"
        assert deferred["deferral_count"] == 2

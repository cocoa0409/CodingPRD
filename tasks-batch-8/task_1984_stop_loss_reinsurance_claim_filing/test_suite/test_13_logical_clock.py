"""The logical clock: startup default and administrator-driven advancement."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    create_contract,
    create_plan,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api_client


class TestLogicalClock:
    def test_default_clock_and_set_current_utc(self, api):
        """PRD §2.10: "At startup, before any adjustment, the logical clock
        reads exactly 2026-08-01T00:00:00Z, and it never falls back to
        wall-clock time thereafter. An administrator-only, test-driving
        capability advances the logical clock to a supplied `to_iso8601`
        instant."
        PRD §3.2: "A `PlanAdministrator` may activate a contract only when
        four preconditions hold together: the current logical instant falls
        within the policy year — on or after `policy_year_start` and strictly
        before `policy_year_end`"

        Design: Corner/endpoints/clock_set_endpoint_default
        """
        # With the untouched startup clock, a policy year starting exactly
        # 2026-08-01 is activatable (start boundary is inclusive)...
        plan_a = create_plan(plan_name="PA", sponsor_tax_id="10-0000001")
        contract_a = create_contract(
            plan_a["id"], policy_year_start="2026-08-01T00:00:00Z",
            policy_year_end="2027-08-01T00:00:00Z")
        activated = validate_success(
            _api_client.activate_contract(contract_a["id"], ADMIN), 200)
        assert activated["status"] == "IN_FORCE"

        # ...while a policy year ending exactly 2026-08-01 is not (the end
        # boundary is exclusive, so the default instant is already past it)...
        plan_b = create_plan(plan_name="PB", sponsor_tax_id="10-0000002")
        contract_b = create_contract(
            plan_b["id"], policy_year_start="2025-08-01T00:00:00Z",
            policy_year_end="2026-08-01T00:00:00Z")
        validate_error(_api_client.activate_contract(contract_b["id"], ADMIN),
                       ApiErrorId.ERR_INVALID_STATE)

        # ...and a policy year starting the day after is not yet activatable,
        # pinning the default to 2026-08-01 and not a later date.
        plan_c = create_plan(plan_name="PC", sponsor_tax_id="10-0000003")
        contract_c = create_contract(
            plan_c["id"], policy_year_start="2026-08-02T00:00:00Z",
            policy_year_end="2027-08-02T00:00:00Z")
        validate_error(_api_client.activate_contract(contract_c["id"], ADMIN),
                       ApiErrorId.ERR_INVALID_STATE)

        # After set_current_utc, time-sensitive operations read the new value.
        resp = _api_client.set_clock({"to_iso8601": "2026-01-01T00:00:00Z"},
                                     ADMIN)
        validate_success(resp, 200)
        plan_d = create_plan(plan_name="PD", sponsor_tax_id="10-0000004")
        contract_d = create_contract(
            plan_d["id"], policy_year_start="2026-01-01T00:00:00Z",
            policy_year_end="2026-06-01T00:00:00Z")
        activated_d = validate_success(
            _api_client.activate_contract(contract_d["id"], ADMIN), 200)
        assert activated_d["status"] == "IN_FORCE"

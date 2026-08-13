"""Inspection findings: severity thresholds on both axes, completion
idempotency, and the no-access strike cascade."""
from test_helpers import (
    ApiErrorId,
    complete_inspection_payload,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    CLERK,
    MANAGER,
    create_lease,
    complete_inspection,
    create_technician,
    create_unit,
    schedule_inspection,
    setup_community,
    technician_headers_for,
)


class TestSeverityLiveAxis:
    def test_severity_threshold_inclusive_at_ten(self, api):
        """PRD §3.3: "The server stamps `completed_at` from the logical clock
        and computes `severity` — null until this moment — from inclusive
        thresholds: `SEVERE` when live sightings are at least 10 or evidence
        traces are at least 20; otherwise `MODERATE` when live sightings are at
        least 4 or evidence at least 8; otherwise `LOW` when either count is at
        least 1; otherwise `NONE`."

        Design: Difficulty/boundary_precision_check/severity_threshold_inclusive_at_ten
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        unit, tech = ctx["unit"], ctx["technician"]
        insp_a = schedule_inspection(unit["id"], tech["id"], scheduled_for="2026-08-05T09:00:00Z")
        insp_b = schedule_inspection(unit["id"], tech["id"], scheduled_for="2026-08-06T09:00:00Z")

        a = complete_inspection(insp_a["id"], tech, live_sightings=10, evidence_count=0,
                                bed_bug_positive=False)
        b = complete_inspection(insp_b["id"], tech, live_sightings=9, evidence_count=0,
                                bed_bug_positive=False)
        assert a["severity"] == "SEVERE", f"10 live sightings must hit the inclusive >= 10 threshold: {a}"
        assert b["severity"] == "MODERATE", f"9 live sightings is one below the threshold: {b}"

    def test_severity_threshold_boundary_below_ten_is_moderate(self, api):
        """PRD §3.3: "`SEVERE` when live sightings are at least 10 or evidence
        traces are at least 20; otherwise `MODERATE` when live sightings are at
        least 4 or evidence at least 8; otherwise `LOW` when either count is at
        least 1; otherwise `NONE`."

        Design: Difficulty/boundary_precision_check/severity_threshold_inclusive_at_ten
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        unit, tech = ctx["unit"], ctx["technician"]
        insp = schedule_inspection(unit["id"], tech["id"], scheduled_for="2026-08-05T09:00:00Z")
        done = complete_inspection(insp["id"], tech, live_sightings=9, evidence_count=7,
                                   bed_bug_positive=False)
        assert done["severity"] == "MODERATE"
        assert done["completed_at"] is not None


class TestSeverityEvidenceAxis:
    def test_severity_evidence_twenty_is_severe(self, api):
        """PRD §3.3: "computes `severity` — null until this moment — from
        inclusive thresholds: `SEVERE` when live sightings are at least 10 or
        evidence traces are at least 20; otherwise `MODERATE` when live
        sightings are at least 4 or evidence at least 8; otherwise `LOW` when
        either count is at least 1; otherwise `NONE`."

        Design: Corner/calculations/severity_evidence_axis_threshold
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        unit, tech = ctx["unit"], ctx["technician"]
        insp_a = schedule_inspection(unit["id"], tech["id"], scheduled_for="2026-08-05T09:00:00Z")
        insp_b = schedule_inspection(unit["id"], tech["id"], scheduled_for="2026-08-06T09:00:00Z")

        a = complete_inspection(insp_a["id"], tech, live_sightings=0, evidence_count=20,
                                bed_bug_positive=False)
        b = complete_inspection(insp_b["id"], tech, live_sightings=0, evidence_count=19,
                                bed_bug_positive=False)
        assert a["severity"] == "SEVERE", "evidence_count == 20 hits >= 20"
        assert b["severity"] == "MODERATE", "19 is below 20 and at least 8"


class TestInspectionCompletionTerminal:
    def test_inspection_double_complete_returns_already_terminal(self, api):
        """PRD §2.4: "Terminal states reject every further action with
        `ERR_ALREADY_TERMINAL` (HTTP 409); a transition that is simply not
        defined from the entity's current non-terminal state is rejected with
        `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.3: "Only the assigned technician may complete an inspection, and
        only from `SCHEDULED`."

        Design: Corner/state_machines/inspection_double_complete_returns_already_terminal
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        unit, tech = ctx["unit"], ctx["technician"]
        insp = schedule_inspection(unit["id"], tech["id"], scheduled_for="2026-08-05T09:00:00Z")
        complete_inspection(insp["id"], tech, live_sightings=0, evidence_count=0,
                            bed_bug_positive=False)

        resp = api.complete_inspection(
            insp["id"],
            complete_inspection_payload(live_sightings=5, evidence_count=5, bed_bug_positive=True),
            technician_headers_for(tech),
        )
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
        cases = get_success_data(api.list_unit_bed_bug_cases(unit["id"], MANAGER))
        assert cases == [], "the rejected second completion must not create a bed bug case"


class TestNoAccessStrikes:
    def test_no_access_strikes_trigger_auto_chargeback(self, api):
        """PRD §3.3: "the inspection moves from `SCHEDULED` to `NO_ACCESS`, and
        the unit's `no_access_strikes` increments by 1. When the strike count
        reaches 2, it resets to zero and — if the unit has an `ACTIVE` lease
        whose `pest_addendum_signed` is true — the system auto-creates a
        `NON_COMPLIANCE_FEE` chargeback in `ASSESSED`, which in turn recomputes
        the lease balance and may set off the late-fee cascade of §3.2."

        Design: Corner/state_machines/no_access_strikes_trigger_auto_chargeback
        """
        ctx = setup_community(with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        unit, lease, tech = ctx["unit"], ctx["lease"], ctx["technician"]
        i1 = schedule_inspection(unit["id"], tech["id"], scheduled_for="2026-08-05T09:00:00Z")
        i2 = schedule_inspection(unit["id"], tech["id"], scheduled_for="2026-08-06T09:00:00Z")

        validate_success(api.no_access_inspection(i1["id"], technician_headers_for(tech)))
        unit_after_1 = validate_success(api.get_unit(unit["id"], MANAGER))
        assert unit_after_1["no_access_strikes"] == 1
        cbs = get_success_data(api.list_lease_chargebacks(lease["id"], CLERK))
        assert cbs == [], "first NO_ACCESS must not create a chargeback"

        validate_success(api.no_access_inspection(i2["id"], technician_headers_for(tech)))
        unit_after_2 = validate_success(api.get_unit(unit["id"], MANAGER))
        assert unit_after_2["no_access_strikes"] == 0, "strikes reset to zero when the penalty fires"
        lease_after = validate_success(api.get_lease(lease["id"], CLERK))
        assert lease_after["outstanding_balance_cents"] == 16125
        cbs = get_success_data(api.list_lease_chargebacks(lease["id"], CLERK))
        assert len(cbs) == 1 and cbs[0]["kind"] == "NON_COMPLIANCE_FEE"
        assert cbs[0]["status"] == "ASSESSED"

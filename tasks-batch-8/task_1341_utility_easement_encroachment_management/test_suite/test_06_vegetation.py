"""Vegetation zones, violations, exemption, and the remediation-deadline
cascade into litigation."""
import pytest

from test_helpers import (
    DEPARTMENT_DIRECTOR,
    LITIGATION_COUNSEL,
    VEGETATION_INSPECTOR,
    ApiErrorId,
    add_vegetation_violation,
    add_vegetation_zone,
    advance_clock,
    api_client,
    counsel_accept_file,
    create_active_case,
    create_notified_violation,
    get_success_data,
    get_vegetation_violation,
    get_vegetation_zone,
    only_referral,
    validate_error,
    validate_success,
)


class TestExcessHeight:

    def test_vegetation_excess_height_wire_zone_stricter(self):
        """PRD section 3.6: "The applicable limit depends on where the growth
        stands: in the wire zone of a zone whose `wire_zone_width_ft` is
        greater than zero, the limit is half the zone's
        `max_allowed_height_ft`, because clearance directly beneath conductors
        is stricter; everywhere else the limit is the full
        `max_allowed_height_ft`. The excess is the observed height minus the
        applicable limit, floored at zero so compliant growth reads 0, and
        rounded half-up to 1 decimal place."

        Zone max 20ft: a 15ft tree in the wire zone (limit 10) has excess 5.0;
        the same tree in the border zone (limit 20) has excess 0.0.

        Design: Corner/calculations/vegetation_excess_height_wire_zone_stricter
        """
        case, _doc = create_active_case(case_code="ESM-CAL4", parcel_id="P-CAL4")
        zone = add_vegetation_zone(case["id"], max_allowed_height_ft=20,
                                   wire_zone_width_ft=25, border_zone_width_ft=25)
        v1 = add_vegetation_violation(case["id"], zone["id"], species="Pine",
                                      observed_height_ft=15, location_within_zone="WIRE_ZONE")
        v2 = add_vegetation_violation(case["id"], zone["id"], species="Pine",
                                      observed_height_ft=15, location_within_zone="BORDER_ZONE")
        assert v1["excess_height_ft"] == pytest.approx(5.0, abs=1e-9), (
            f"wire-zone excess must be 15 - 10 = 5.0, got {v1['excess_height_ft']}"
        )
        assert v2["excess_height_ft"] == pytest.approx(0.0, abs=1e-9), (
            f"compliant border-zone growth must read 0.0, got {v2['excess_height_ft']}"
        )


class TestZoneLifecycle:

    def test_bubble_up_zone_cleared_when_all_violations_remediated(self):
        """PRD section 3.6: "Confirming the cleanup moves `NOTIFIED →
        REMEDIATED` and decrements the zone's `violation_count`; when the count
        falls back below `VIOLATION_REMEDIATION_THRESHOLD` a zone in
        `REMEDIATION_REQUIRED` relaxes to `VIOLATION_DETECTED`, and when the
        count reaches zero — from either of those zone states — the zone
        automatically becomes `CLEARED`."

        Design: Corner/state_machines/bubble_up_zone_cleared_when_all_violations_remediated
        """
        case, _doc = create_active_case(case_code="ESM-S09", parcel_id="P-S09")
        zone = add_vegetation_zone(case["id"])
        viol = create_notified_violation(case["id"], zone["id"], species="Oak",
                                         observed_height_ft=30,
                                         location_within_zone="BORDER_ZONE")
        resp = api_client.confirm_vegetation_remediation(
            case["id"], zone["id"], viol["id"], VEGETATION_INSPECTOR
        )
        data = validate_success(resp)
        assert data["status"] == "REMEDIATED"
        zone_after = get_vegetation_zone(case["id"], zone["id"])
        assert zone_after["violation_count"] == 0
        assert zone_after["status"] == "CLEARED"


class TestExemption:

    def test_err_prohibited_species_not_exemptable(self):
        """PRD section 3.6: "Exemption is the `DepartmentDirector`'s safety
        valve, moving `DETECTED → EXEMPTED` and decrementing the zone count,
        but it is deliberately narrow: the observed `species` must not appear
        in the zone's `prohibited_species` list (else
        `ERR_PROHIBITED_SPECIES_NOT_EXEMPTABLE`), and the `excess_height_ft`
        must not exceed the configured `EXEMPTABLE_HEIGHT_MARGIN_FT` (else
        `ERR_EXCESS_HEIGHT_TOO_LARGE`)."

        Design: Corner/errors/err_prohibited_species_not_exemptable
        """
        case, _doc = create_active_case(case_code="ESM-ER3", parcel_id="P-ER3")
        zone = add_vegetation_zone(case["id"], prohibited_species=["Kudzu"])
        # 12ft against a 20ft border-zone limit: excess 0, so only the
        # prohibited-species rule can reject the exemption.
        viol = add_vegetation_violation(case["id"], zone["id"], species="Kudzu",
                                        observed_height_ft=12,
                                        location_within_zone="BORDER_ZONE")
        resp = api_client.exempt_vegetation_violation(
            case["id"], zone["id"], viol["id"], DEPARTMENT_DIRECTOR
        )
        validate_error(resp, ApiErrorId.ERR_PROHIBITED_SPECIES_NOT_EXEMPTABLE, expected_status=409)


class TestRemediationDeadlineCascade:

    def _setup_notified_violation_past_deadline(self, case_code, parcel_id):
        case, _doc = create_active_case(case_code=case_code, parcel_id=parcel_id)
        zone = add_vegetation_zone(case["id"], zone_label="Z1",
                                   prohibited_species=["Kudzu"])
        viol = create_notified_violation(case["id"], zone["id"], species="Oak",
                                         observed_height_ft=30,
                                         location_within_zone="BORDER_ZONE")
        # Move the logical clock well past the remediation window so the
        # deadline-driven escalation fires.
        advance_clock("2026-10-01T00:00:00Z")
        return case, zone, viol

    def test_violation_escalates_and_judgment_remediates_and_clears_zone(self):
        """PRD section 3.6: "If that deadline passes unremediated, the system
        automatically escalates the violation `NOTIFIED → ESCALATED_TO_LEGAL`
        and auto-creates a `REFERRED` litigation referral with
        `referral_reason` `VEGETATION_REMEDIATION_FAILED`."
        PRD section 3.7: "Recording a judgment moves `FILED →
        JUDGMENT_OBTAINED` with three parallel outcomes: a `NEGOTIATION_FAILED`
        referral removes the linked encroachment; a
        `VEGETATION_REMEDIATION_FAILED` referral marks the linked violation
        `REMEDIATED`; and a `CONDEMNATION` referral moves the case itself to
        `CLOSED_CONDEMNED`."
        PRD section 3.6: "Confirming the cleanup moves `NOTIFIED → REMEDIATED`
        and decrements the zone's `violation_count`; when the count falls back
        below `VIOLATION_REMEDIATION_THRESHOLD` a zone in
        `REMEDIATION_REQUIRED` relaxes to `VIOLATION_DETECTED`, and when the
        count reaches zero — from either of those zone states — the zone
        automatically becomes `CLEARED`."

        Design: Difficulty/transitive_cascade/vegetation_violation_escalates_to_referral_and_remediation
        """
        case, zone, viol = self._setup_notified_violation_past_deadline("ESM-008", "P-008")
        referral = only_referral(case["id"])
        counsel_accept_file(case["id"], referral["id"])
        judgment = get_success_data(
            api_client.record_litigation_judgment(case["id"], referral["id"], LITIGATION_COUNSEL)
        )
        assert judgment["status"] == "JUDGMENT_OBTAINED"

        viol_after = get_vegetation_violation(case["id"], zone["id"], viol["id"])
        assert viol_after["status"] == "REMEDIATED"
        zone_after = get_vegetation_zone(case["id"], zone["id"])
        assert zone_after["violation_count"] == 0
        assert zone_after["status"] == "CLEARED"

    def test_deadline_passage_escalates_violation_and_creates_referral(self):
        """PRD section 3.6: "If that deadline passes unremediated, the system
        automatically escalates the violation `NOTIFIED → ESCALATED_TO_LEGAL`
        and auto-creates a `REFERRED` litigation referral with
        `referral_reason` `VEGETATION_REMEDIATION_FAILED`."
        PRD section 2.10: "Advancing the clock re-evaluates every
        deadline-based automatic transition in the system — expiring offers
        whose negotiation window has run out, escalating notified encroachments
        whose owner-response window has lapsed, and escalating notified
        vegetation violations whose remediation window has closed."

        Design: Difficulty/transitive_cascade/vegetation_violation_escalates_to_referral_and_remediation
        """
        case, zone, viol = self._setup_notified_violation_past_deadline("ESM-008b", "P-008b")
        # Force observation of the lazy deadline re-evaluation.
        get_success_data(
            api_client.list_vegetation_violations(case["id"], zone["id"], VEGETATION_INSPECTOR)
        )
        viol_after = get_vegetation_violation(case["id"], zone["id"], viol["id"])
        assert viol_after["status"] == "ESCALATED_TO_LEGAL", (
            f"lapsed remediation window must escalate the violation, "
            f"got {viol_after['status']}"
        )
        referral = only_referral(case["id"])
        assert referral["status"] == "REFERRED"
        assert referral["referral_reason"] == "VEGETATION_REMEDIATION_FAILED"

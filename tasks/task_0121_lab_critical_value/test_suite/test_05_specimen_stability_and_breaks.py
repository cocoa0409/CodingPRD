"""Specimen stability check at final leg + report-break cascade.

PRD §3.3 specifies the stability check (strict > comparison) and the
report-break cascade (leg -> specimen -> order -> RetestRequest).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    LAB_LOCATION_CODE,
    anchor_clock,
    arrive_leg,
    assert_retest_request,
    collect_specimen,
    create_catalog_bundle,
    iso_anchor_offset,
    list_audit_for_order,
    list_retests_for_order,
    make_lab_tech_headers,
    open_transport_leg,
    place_lab_order,
    reget_lab_order,
    reget_specimen,
    setup_in_transit_for_break,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.3 Stability check
# difficulty: boundary_precision_check / specimen_stability_strict_greater_than
# ===========================================================================
class TestSpecimenStabilityBoundary:

    def _setup(self, *, stability_minutes: int):
        bundle = create_catalog_bundle(
            panel_complexity="MODERATE",
            panel_stability_minutes=stability_minutes,
        )
        anchor_clock(bundle["director"])
        order = place_lab_order(bundle)
        spec = collect_specimen(
            bundle, order, collected_at=iso_anchor_offset(minutes=0),
        )
        leg = open_transport_leg(
            bundle, spec,
            from_location="CLINIC_A", to_location=LAB_LOCATION_CODE,
            departed_at=iso_anchor_offset(minutes=0),
        )
        return bundle, order, spec, leg

    def test_arrival_exactly_at_stability_accepted_as_on_time(self, api):
        """PRD §3.3: "The comparison is strict: transit minutes equal
        to `stability_minutes` is accepted as on-time, and only
        transit minutes strictly greater than `stability_minutes` is
        treated as exceeded."

        PRD §3.3: "When the check passes, the specimen's `received_at`
        is set to the leg's `arrived_at`, the specimen transitions
        from `IN_TRANSIT` to `RECEIVED`, and the parent order
        transitions from `IN_TRANSIT` to `RECEIVED`."

        Claim: arrival exactly stability_minutes after collection ->
        Specimen.status RECEIVED, LabOrder.status RECEIVED.

        # difficulty: boundary_precision_check/specimen_stability_strict_greater_than
        """
        bundle, order, spec, leg = self._setup(stability_minutes=120)
        arrive_leg(
            bundle, leg, arrived_at=iso_anchor_offset(minutes=120),
        )
        spec_after = reget_specimen(bundle, spec["id"])
        order_after = reget_lab_order(bundle, order["id"])
        assert spec_after["status"] == "RECEIVED"
        assert order_after["status"] == "RECEIVED"

    def test_arrival_one_second_past_stability_rejected(self, api):
        """PRD §3.3: "The comparison is strict: transit minutes equal
        to `stability_minutes` is accepted as on-time, and only
        transit minutes strictly greater than `stability_minutes` is
        treated as exceeded."

        PRD §3.3: "When the check fails, the specimen instead
        transitions from `IN_TRANSIT` to `REJECTED` with
        `rejected_reason` set to `STABILITY_EXCEEDED`, the parent
        order transitions from `IN_TRANSIT` to `REJECTED`, the
        system auto-issues a `RetestRequest` with `reason` set to
        `SPECIMEN_REJECTED` and a freshly minted replacement
        `LabOrder` whose `parent_order_id` is the original order and
        whose `retest_count` is the original's `retest_count` plus
        one, and the system appends a `ComplianceAuditEvent` with
        `event_type` of `SPECIMEN_REJECTED`."

        Claim: arrival 1 second past stability -> Specimen REJECTED
        with rejected_reason STABILITY_EXCEEDED, order REJECTED.

        # difficulty: boundary_precision_check/specimen_stability_strict_greater_than
        """
        bundle, order, spec, leg = self._setup(stability_minutes=120)
        arrive_leg(
            bundle, leg,
            arrived_at=iso_anchor_offset(minutes=120, seconds=1),
        )
        spec_after = reget_specimen(bundle, spec["id"])
        order_after = reget_lab_order(bundle, order["id"])
        assert spec_after["status"] == "REJECTED"
        assert spec_after["rejected_reason"] == "STABILITY_EXCEEDED"
        assert order_after["status"] == "REJECTED"

    def test_arrival_below_stability_accepted(self, api):
        """PRD §3.3: "When the check passes, the specimen's
        `received_at` is set to the leg's `arrived_at`, the specimen
        transitions from `IN_TRANSIT` to `RECEIVED`, and the parent
        order transitions from `IN_TRANSIT` to `RECEIVED`."

        Claim: arrival comfortably inside stability -> RECEIVED.
        """
        bundle, order, spec, leg = self._setup(stability_minutes=120)
        arrive_leg(
            bundle, leg, arrived_at=iso_anchor_offset(minutes=119),
        )
        spec_after = reget_specimen(bundle, spec["id"])
        assert spec_after["status"] == "RECEIVED"


class TestSpecimenStabilityAutoRetest:

    def test_stability_failure_auto_issues_retest_with_parent_link(
        self, api,
    ):
        """PRD §3.3: "the system auto-issues a `RetestRequest` with
        `reason` set to `SPECIMEN_REJECTED` and a freshly minted
        replacement `LabOrder` whose `parent_order_id` is the original
        order and whose `retest_count` is the original's
        `retest_count` plus one, and the system appends a
        `ComplianceAuditEvent` with `event_type` of
        `SPECIMEN_REJECTED`."

        Claim: after stability fails, RetestRequest(SPECIMEN_REJECTED)
        exists referencing a new LabOrder with parent_order_id ==
        original.id and retest_count == original.retest_count + 1.
        """
        bundle = create_catalog_bundle(
            panel_complexity="MODERATE", panel_stability_minutes=120,
        )
        anchor_clock(bundle["director"])
        order = place_lab_order(bundle)
        spec = collect_specimen(
            bundle, order, collected_at=iso_anchor_offset(minutes=0),
        )
        leg = open_transport_leg(
            bundle, spec,
            from_location="CLINIC_A", to_location=LAB_LOCATION_CODE,
            departed_at=iso_anchor_offset(minutes=0),
        )
        arrive_leg(
            bundle, leg,
            arrived_at=iso_anchor_offset(minutes=121),
        )
        retests = list_retests_for_order(bundle, order["id"])
        rr = next(
            (r for r in retests
             if r["reason"] == "SPECIMEN_REJECTED"),
            None,
        )
        assert rr is not None
        assert_retest_request(rr)
        new_order = reget_lab_order(bundle, rr["new_lab_order_id"])
        assert new_order["parent_order_id"] == order["id"]
        assert new_order["retest_count"] == order["retest_count"] + 1


# ===========================================================================
# §3.3 Report-break cascade (depth-3)
# difficulty: transitive_cascade / report_break_cascade_chain_depth_3
# ===========================================================================
class TestReportBreakCascade:

    def test_report_break_flips_leg_specimen_order_and_issues_retest(
        self, api,
    ):
        """PRD §3.3: "Reporting the break transitions the leg from
        `DEPARTED` to `BROKEN`, the specimen from `IN_TRANSIT` to
        `REJECTED` with `rejected_reason` set to `CHAIN_BROKEN`, and
        the parent order from `IN_TRANSIT` to `REJECTED`. The system
        auto-creates a `RetestRequest` whose `reason` is
        `SPECIMEN_REJECTED` and whose `new_lab_order_id` references a
        newly minted `LabOrder` that clones the panel and patient with
        `parent_order_id` set to the original order's id and
        `retest_count` set to the original's `retest_count` plus one."

        Claim: report-break cascades to leg BROKEN, specimen REJECTED
        with rejected_reason CHAIN_BROKEN, order REJECTED, and a
        RetestRequest(SPECIMEN_REJECTED) is issued whose new order has
        parent_order_id == original.id and retest_count == +1.

        # difficulty: transitive_cascade/report_break_cascade_chain_depth_3
        """
        ctx = setup_in_transit_for_break()
        bundle = ctx["bundle"]
        order, spec, leg = ctx["order"], ctx["specimen"], ctx["leg"]
        tech = bundle["lab_tech"]
        res = api.report_break_transport_leg(
            leg["id"], make_lab_tech_headers(tech["id"]),
        )
        validate_success(res, 200)
        spec_after = reget_specimen(bundle, spec["id"])
        order_after = reget_lab_order(bundle, order["id"])
        assert spec_after["status"] == "REJECTED"
        assert spec_after["rejected_reason"] == "CHAIN_BROKEN"
        assert order_after["status"] == "REJECTED"
        retests = list_retests_for_order(bundle, order["id"])
        rr = next(
            (r for r in retests
             if r["reason"] == "SPECIMEN_REJECTED"),
            None,
        )
        assert rr is not None
        new_order = reget_lab_order(bundle, rr["new_lab_order_id"])
        assert new_order["parent_order_id"] == order["id"]
        assert new_order["retest_count"] == order["retest_count"] + 1

    def test_report_break_writes_audit_events_in_order(self, api):
        """PRD §3.3: "Two compliance audit events are written, in this
        order: first an event with `event_type` of `SPECIMEN_REJECTED`,
        then an event with `event_type` of `RETEST_ISSUED`."

        Claim: after report-break, the SPECIMEN_REJECTED audit event
        precedes the RETEST_ISSUED audit event (by created_at).

        # difficulty: transitive_cascade/report_break_cascade_chain_depth_3
        """
        ctx = setup_in_transit_for_break()
        bundle = ctx["bundle"]
        leg = ctx["leg"]
        tech = bundle["lab_tech"]
        api.report_break_transport_leg(
            leg["id"], make_lab_tech_headers(tech["id"]),
        )
        events = list_audit_for_order(bundle, ctx["order"]["id"])
        sr = [e for e in events
              if e["event_type"] == "SPECIMEN_REJECTED"]
        ri = [e for e in events
              if e["event_type"] == "RETEST_ISSUED"]
        assert sr, "SPECIMEN_REJECTED audit event must be present"
        assert ri, "RETEST_ISSUED audit event must be present"
        first_sr = min(e["created_at"] for e in sr)
        first_ri = min(e["created_at"] for e in ri)
        assert first_sr <= first_ri


# ===========================================================================
# §3.4 Result preconditions — order RECEIVED, specimen RECEIVED
# difficulty: cross_entity_state_dependency /
#             lab_order_resulted_depends_on_specimen_received
# ===========================================================================
class TestResultRequiresSpecimenReceived:

    def test_result_attempt_on_rejected_specimen_blocked(self, api):
        """PRD §3.4: "Once the order is in `RECEIVED` and its specimen
        is in `RECEIVED`, a clinician may produce the result."

        Claim: when the specimen is REJECTED (so the order is REJECTED),
        POST /lab-orders/{id}/results returns ERR_INVALID_STATE.

        # difficulty: cross_entity_state_dependency/lab_order_resulted_depends_on_specimen_received
        """
        from test_helpers import (
            attempt_resultate, critical_measurements_high,
        )
        ctx = setup_in_transit_for_break()
        bundle = ctx["bundle"]
        leg = ctx["leg"]
        tech = bundle["lab_tech"]
        api.report_break_transport_leg(
            leg["id"], make_lab_tech_headers(tech["id"]),
        )
        meas = critical_measurements_high(
            bundle["panel"]["analytes"], value=400.0,
        )
        res = attempt_resultate(
            bundle, ctx["order"],
            measurements=meas, resulted_by=bundle["lab_tech"],
        )
        validate_error(res, "ERR_INVALID_STATE")

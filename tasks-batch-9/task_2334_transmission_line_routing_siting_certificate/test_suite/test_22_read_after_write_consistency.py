"""Cascades are readable on the very next read, with no reconciliation step.

Both of these writes touch several aggregates at once. Each test performs the
write, then reads the touched rows back through ordinary endpoints and finds
every one of them already consistent.
"""

from test_helpers import (
    assert_score,
    get_success_data,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestOrderCascadeIsImmediatelyReadable:
    """One order mints a certificate and its conditions and moves the project."""

    def test_the_certificate_and_its_conditions_read_back_after_the_order(self, api):
        """PRD §3.7: "The grant moves the application `ACCEPTED → GRANTED`, mints a
        **certificate** with `status` `ISSUED` and `posture` `ACTIVE` ... sets both
        compliance indices to 100 ... and carries the project `APPLICATION_FILED →
        CERTIFICATED`."

        Design: Corner/consistency_model/decision_response_exposes_the_minted_certificate_immediately
        """
        ctx = fx.setup_closed_record(api)
        get_success_data(
            api.record_decision(
                ctx["app"],
                f.decision_payload(
                    outcome="GRANT", certified_route_id=ctx["routeA"],
                    eminent_domain_authorized=True, mitigation_base_cents=480_000_000,
                ),
                fx.COMMISSION_STAFF_HEADERS,
            )
        )

        certificates, _ = validate_paginated(
            api.list_certificates(
                fx.COMMISSION_STAFF_HEADERS, {"application_id": ctx["app"]}
            )
        )
        assert len(certificates) == 1, (
            f"The order minted exactly one certificate, got {len(certificates)}"
        )
        certificate = certificates[0]
        _, meta = validate_paginated(
            api.list_certificate_conditions(
                fx.COMMISSION_STAFF_HEADERS, {"certificate_id": certificate["id"]}
            )
        )

        assert meta["total_count"] == 3, (
            f"All three conditions of the order are already readable, got "
            f"{meta['total_count']}"
        )
        assert certificate["status"] == "ISSUED", (
            f"The certificate is issued on first read, got {certificate['status']}"
        )
        assert certificate["posture"] == "ACTIVE", (
            f"Its posture is ACTIVE on first read, got {certificate['posture']}"
        )
        assert_score(
            certificate["compliance_index_rolling"], 100.00, "compliance_index_rolling"
        )
        application = fx.read_application(api, ctx["app"])
        assert application["review_status"] == "GRANTED", (
            f"The merits dimension moved with the same write, got "
            f"{application['review_status']}"
        )
        assert application["record_status"] == "RECORD_CLOSED", (
            f"The record dimension came to rest at its terminal status, got "
            f"{application['record_status']}"
        )
        assert fx.read_project(api, ctx)["stage"] == "CERTIFICATED", (
            "The project stage moved with the same write"
        )


class TestFindingCascadeIsImmediatelyReadable:
    """One finding halts the work and every touched row reads back consistent."""

    def test_the_stop_work_cascade_reads_back_after_the_finding(self, api):
        """PRD §3.9: "A finding that drives the rolling index below 60.00 while the
        cumulative index holds at 25.00 or above moves the certificate `ACTIVE →
        STOP_WORK`, suspends every activity on that certificate whose status is
        `SCHEDULED` or `IN_PROGRESS` with `suspension_reason` recorded as
        `CERTIFICATE_STOP_WORK`, and moves each affected segment `ACTIVE → HALTED` on its
        construction dimension."

        Design: Corner/consistency_model/finding_cascade_is_readable_without_a_second_write
        """
        ctx = fx.setup_construction_ready(api)
        fx.setup_started_activity(api, ctx, key="act1", crew_count=6)
        finding = fx.file_finding(
            api, ctx, key="ncr_now", condition_key="cond1", severity="SEVERE",
            observation="Clearing outside the approved workspace",
        )

        certificate = validate_success(
            api.get_certificate(ctx["cert"], fx.COMPLIANCE_MONITOR_HEADERS),
            expected_status=200,
        )

        assert certificate["posture"] == "STOP_WORK", (
            f"The posture is already STOP_WORK on the next read, got "
            f"{certificate['posture']}"
        )
        assert_score(
            certificate["compliance_index_rolling"], 52.00, "compliance_index_rolling"
        )
        assert certificate["status"] == "ISSUED", (
            f"Only the posture moved; the status is untouched, got "
            f"{certificate['status']}"
        )
        assert_score(finding["deduction_points"], 48.00, "deduction_points")
        assert fx.read_condition(api, ctx["cond1"])["status"] == "VIOLATED", (
            "The named condition is already VIOLATED"
        )
        activity = fx.read_activity(api, ctx["act1"])
        assert activity["status"] == "SUSPENDED", (
            f"The running activity was suspended by the cascade, got "
            f"{activity['status']}"
        )
        assert fx.read_segment(api, ctx["seg1"])["construction_state"] == "HALTED", (
            "The segment carrying the suspended activity is already HALTED"
        )

"""Requests that fail two ways at once, and which failure surfaces.

Each pair is shown twice: once with both defects present, so the earlier check
masks the later one, and once with the earlier defect repaired, so the later
check finally reports.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_score,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestFilingStateGateBeatsFiscalGate:
    """Route nomination status is checked before the tendered filing fee."""

    def test_unnominated_route_masks_the_short_filing_fee(self, api):
        """PRD §3.5: "the proposed route must have `kind` `PROPOSED` and `status`
        `NOMINATED` (`ERR_ROUTE_NOT_NOMINATED`, HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_fiscal_gate_on_application_filing_rejected
        """
        ctx = fx.setup_published_route(api)

        response = api.create_application(
            f.application_payload(
                ctx["proj"], ctx["study"], ctx["routeA"],
                docket_number="EL-2026-0334", filing_fee_cents=1_000_000,
            ),
            fx.DEVELOPER_FILER_HEADERS,
        )
        validate_error(response, ApiErrorId.ROUTE_NOT_NOMINATED, expected_status=409)

        applications, meta = validate_paginated(
            api.list_applications(fx.COMMISSION_STAFF_HEADERS, {"project_id": ctx["proj"]})
        )
        assert meta["total_count"] == 0, (
            f"The refused filing must not have created an application, got "
            f"{meta['total_count']}"
        )
        assert applications == [], "No application row may exist on the project"

    def test_nominating_the_route_exposes_the_short_filing_fee(self, api):
        """PRD §3.5: "the tendered fee must be at least twenty-five thousand
        dollars expressed in cents, that is 2,500,000 cents, or the filing is
        refused with `ERR_FILING_FEE_INSUFFICIENT` (HTTP 402)".

        Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_fiscal_gate_on_application_filing_rejected
        """
        ctx = fx.setup_nominated_routes(api)

        response = api.create_application(
            f.application_payload(
                ctx["proj"], ctx["study"], ctx["routeA"],
                docket_number="EL-2026-0334", filing_fee_cents=1_000_000,
            ),
            fx.DEVELOPER_FILER_HEADERS,
        )
        validate_error(response, ApiErrorId.FILING_FEE_INSUFFICIENT, expected_status=402)

        _, meta = validate_paginated(
            api.list_applications(fx.COMMISSION_STAFF_HEADERS, {"project_id": ctx["proj"]})
        )
        assert meta["total_count"] == 0, (
            f"The fiscal refusal writes nothing either, got {meta['total_count']}"
        )


class TestPermitSafetyBeatsEasementRule:
    """The federal crossing check runs ahead of the easement and escrow checks."""

    def test_missing_crossing_permit_masks_the_unacquired_easement(self, api):
        """PRD §3.9: "The segment's `federal_permit_status` must be either
        `NOT_REQUIRED` or `ISSUED`; a status of `REQUIRED`, `APPLIED` or `DENIED`
        refuses the start with `ERR_FEDERAL_PERMIT_MISSING` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/permit_safety_beats_easement_referential_on_activity_start_rejected
        """
        ctx = fx.setup_issued_certificate(api)
        fx.schedule_activity(api, ctx, key="act2", segment_key="seg2")
        fx.set_clock(api, "2027-08-02T00:00:00Z")

        response = api.start_activity(
            ctx["act2"], f.activity_start_payload(), fx.DEVELOPER_HEADERS
        )
        validate_error(response, ApiErrorId.FEDERAL_PERMIT_MISSING, expected_status=422)

        assert fx.read_activity(api, ctx["act2"])["status"] == "SCHEDULED", (
            "The refused start leaves the activity at SCHEDULED"
        )
        assert fx.read_segment(api, ctx["seg2"])["construction_state"] == "PENDING", (
            "The refused start leaves the segment's construction dimension at PENDING"
        )

    def test_issuing_the_permit_exposes_the_easement_then_the_escrow_gate(self, api):
        """PRD §3.9: "Every easement tract on that segment must be at `AGREED` or
        `AWARDED`, and at least one such tract must exist — a segment with no
        tract at all, or with any tract short of acquisition, refuses the start
        with `ERR_EASEMENT_NOT_ACQUIRED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/permit_safety_beats_easement_referential_on_activity_start_rejected
        """
        ctx = fx.setup_issued_certificate(api)
        fx.schedule_activity(api, ctx, key="act2", segment_key="seg2")
        fx.apply_for_federal_permit(api, ctx, segment_key="seg2", agency="USACE")
        get_success_data(
            api.record_federal_permit_action(
                ctx["seg2"],
                f.federal_permit_action_payload(
                    action="ISSUE", agency="USACE",
                    determination_note="Section 10 permit issued for the river crossing",
                ),
                fx.FEDERAL_PERMIT_OFFICER_HEADERS,
            )
        )
        fx.set_clock(api, "2027-08-02T00:00:00Z")

        response = api.start_activity(
            ctx["act2"], f.activity_start_payload(), fx.DEVELOPER_HEADERS
        )
        validate_error(response, ApiErrorId.EASEMENT_NOT_ACQUIRED, expected_status=422)

        fx.create_landowner(
            api, ctx, "lo_river", name="Rae Colvin", email="rae@example.com",
            mailing_address="9 Mill St, Boone KY",
        )
        fx.setup_agreed_tract(
            api, ctx, key="tract_river", landowner_key="lo_river", segment_key="seg2",
            parcel_number="B-210-04",
        )

        response = api.start_activity(
            ctx["act2"], f.activity_start_payload(), fx.DEVELOPER_HEADERS
        )
        validate_error(response, ApiErrorId.ESCROW_UNDERFUNDED, expected_status=402)


class TestRoleCheckBeatsReferenceExistence:
    """Endpoint authorization is settled before any body reference is resolved."""

    def test_wrong_role_masks_absent_certificate_and_condition_references(self, api):
        """PRD §2.11: "Checks are therefore evaluated in a fixed global order, and
        the first failure ends the request."

        Design: Difficulty/priority_pair_validation_conflict/role_check_beats_reference_existence_unauthorized
        """
        ctx = fx.setup_issued_certificate(api)

        response = api.create_nonconformance(
            f.nonconformance_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                severity="SEVERE",
                observation="Filed by a role with no authority over findings",
            ),
            fx.DEVELOPER_HEADERS,
        )
        validate_error(response, ApiErrorId.UNAUTHORIZED, expected_status=403)

        certificate = fx.read_certificate(api, ctx["cert"])
        assert_score(
            certificate["compliance_index_rolling"], 100.00, "compliance_index_rolling"
        )
        assert certificate["posture"] == "ACTIVE", (
            f"Nothing was written, so posture is untouched, got {certificate['posture']}"
        )

    def test_authorized_role_with_the_same_absent_references_reports_the_lookup(self, api):
        """PRD §2.5: "References supplied inside a request body are resolved
        separately and report `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

        Design: Difficulty/priority_pair_validation_conflict/role_check_beats_reference_existence_unauthorized
        """
        fx.setup_issued_certificate(api)

        response = api.create_nonconformance(
            f.nonconformance_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                severity="SEVERE",
                observation="Filed by the monitor against references that do not exist",
            ),
            fx.COMPLIANCE_MONITOR_HEADERS,
        )
        validate_error(response, ApiErrorId.REFERENCE_NOT_FOUND, expected_status=404)

        findings, meta = validate_paginated(
            api.list_nonconformances(fx.COMPLIANCE_MONITOR_HEADERS)
        )
        assert meta["total_count"] == 0, (
            f"No finding was created by either refused request, got {meta['total_count']}"
        )
        assert findings == [], "The nonconformance collection must still be empty"

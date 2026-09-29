"""Rejection codes: the per-identifier 404 family, the identity headers, and the
declared role that is simply not on the endpoint's list.
"""

from __future__ import annotations

from test_helpers import (
    CENTER_PORT_CODE,
    ERR_CENTER_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_HOLD_ORDER_NOT_FOUND,
    ERR_INSPECTION_NOT_FOUND,
    ERR_RELEASE_ORDER_NOT_FOUND,
    ERR_REPAIR_ORDER_NOT_FOUND,
    ERR_SURVEY_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_VESSEL_NOT_FOUND,
    ERR_WORK_ORDER_NOT_FOUND,
    INSPECTOR,
    MANAGER,
    MISSING_UUIDS,
    PLANNER,
    SURVEYOR,
    TECHNICIAN,
    Vpc,
    assert_pagination_meta,
    created,
    factories as f,
    headers_with_no_identity,
    headers_with_undeclared_role,
    ok,
    validate_error,
    validate_paginated,
)


class TestPathScopedNotFoundCodes:
    def test_nine_unknown_identifiers_answer_with_nine_different_codes(self, flow: Vpc):
        """No shared generic not-found: each path segment owns its code.

        PRD: "3. Path identifier resolution, left to right — the fourteen 404 codes
        named in §2.5."

        PRD: "Each identifier has its own dedicated not-found code: `centerId`
        yields `ERR_CENTER_NOT_FOUND`, `berthId` yields `ERR_BERTH_NOT_FOUND`,
        `vesselId` yields `ERR_VESSEL_NOT_FOUND`, `vehicleId` yields
        `ERR_VEHICLE_NOT_FOUND`, `surveyId` yields `ERR_SURVEY_NOT_FOUND`,
        `claimId` yields `ERR_CLAIM_NOT_FOUND`, `repairOrderId` yields
        `ERR_REPAIR_ORDER_NOT_FOUND`, `kitId` yields `ERR_KIT_NOT_FOUND`,
        `workOrderId` yields `ERR_WORK_ORDER_NOT_FOUND`, `inspectionId` yields
        `ERR_INSPECTION_NOT_FOUND`, `holdOrderId` yields
        `ERR_HOLD_ORDER_NOT_FOUND`, `dealerId` yields `ERR_DEALER_NOT_FOUND`,
        `carrierId` yields `ERR_CARRIER_NOT_FOUND`, and `releaseOrderId` yields
        `ERR_RELEASE_ORDER_NOT_FOUND`."

        Design: Corner/errors/corner_every_path_scoped_not_found_code_is_reachable
        """
        flow.set_clock("2026-08-01T00:00:00Z")
        api = flow.api

        probes = [
            (api.get_center(MISSING_UUIDS[0], PLANNER), ERR_CENTER_NOT_FOUND),
            (api.get_vessel(MISSING_UUIDS[1], PLANNER), ERR_VESSEL_NOT_FOUND),
            (api.get_survey(MISSING_UUIDS[2], SURVEYOR), ERR_SURVEY_NOT_FOUND),
            (api.get_claim(MISSING_UUIDS[3], MANAGER), ERR_CLAIM_NOT_FOUND),
            (api.get_repair_order(MISSING_UUIDS[4], SURVEYOR), ERR_REPAIR_ORDER_NOT_FOUND),
            (api.get_work_order(MISSING_UUIDS[5], TECHNICIAN), ERR_WORK_ORDER_NOT_FOUND),
            (api.get_inspection(MISSING_UUIDS[6], INSPECTOR), ERR_INSPECTION_NOT_FOUND),
            (api.get_release_order(MISSING_UUIDS[7], MANAGER), ERR_RELEASE_ORDER_NOT_FOUND),
            (api.get_hold(MISSING_UUIDS[8], MANAGER), ERR_HOLD_ORDER_NOT_FOUND),
        ]

        seen = []
        for response, expected_code in probes:
            validate_error(response, expected_code, 404)
            body = response.json()
            assert body["response_type"] == "error"
            assert isinstance(body["data"]["message"], str) and body["data"]["message"]
            seen.append(body["data"]["error_id"])

        assert len(set(seen)) == 9


class TestIdentityHeaders:
    def test_absent_headers_and_an_undeclared_role_are_both_unauthenticated(self, flow: Vpc):
        """Band one runs before the role list is ever consulted, so neither is a 403.

        PRD: "Every request — reads included — must carry two headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity in
        which they act."

        PRD: "If either header is absent, or if `X-User-Role` is not one of the six
        declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
        401)."

        Design: Corner/errors/corner_missing_or_unknown_role_header_is_unauthenticated
        """
        flow.set_clock("2026-08-01T00:00:00Z")
        center = flow.create_center()

        no_headers = flow.api.get_center(
            center["id"], PLANNER, headers=headers_with_no_identity()
        )
        validate_error(no_headers, ERR_UNAUTHENTICATED, 401)

        unknown_role = flow.api.get_center(
            center["id"], PLANNER, headers=headers_with_undeclared_role()
        )
        validate_error(unknown_role, ERR_UNAUTHENTICATED, 401)

        readable = ok(flow.api.get_center(center["id"], PLANNER))
        assert readable["port_code"] == CENTER_PORT_CODE


class TestRoleAuthorizationList:
    def test_a_declared_role_off_the_list_is_forbidden_and_writes_nothing(self, flow: Vpc):
        """The technician is authenticated, just not authorized to book a voyage.

        PRD: "When the headers are well-formed but the declared role is not among
        the roles authorized for the requested operation in §4, the rejection is
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        PRD: "2. Role authorization for the requested operation —
        `ERR_FORBIDDEN_ROLE` (403)."

        Design: Corner/errors/corner_declared_role_outside_the_endpoint_list_is_forbidden
        """
        flow.set_clock("2026-08-01T00:00:00Z")
        center = flow.create_center()
        berth = flow.create_berth(center["id"])
        payload = f.vessel_payload(
            center["id"],
            berth["id"],
            berth_window_start="2026-08-01T06:00:00Z",
            berth_window_end="2026-08-01T18:00:00Z",
            declared_unit_count=4,
        )

        forbidden = flow.api.create_vessel(payload, TECHNICIAN)
        validate_error(forbidden, ERR_FORBIDDEN_ROLE, 403)

        _, meta = validate_paginated(
            flow.api.list_vessels(PLANNER, params={"processing_center_id": center["id"]})
        )
        assert_pagination_meta(meta, total_count=0)

        accepted = created(flow.api.create_vessel(payload, PLANNER))
        assert accepted["processing_center_id"] == center["id"]
        assert accepted["berth_id"] == berth["id"]

"""Auth headers, RBAC, response envelope, pagination — PRD §2.1, §2.2, §2.3."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_courier_payload,
    create_locker_machine_payload,
    setup_basic_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestUserContextHeaders:
    """PRD §2.1: 'Every request must carry two HTTP headers: X-User-ID,
    identifying the calling principal, and X-User-Role.'"""

    def test_missing_both_headers_returns_header_error(self, api):
        """PRD §2.1: 'Requests missing or carrying invalid values for these
        two headers are rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.'

        Claim: a list call with no headers returns the header error.
        """
        resp = api._request("GET", "/locker-machines", headers={})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )

    def test_missing_role_header_returns_header_error(self, api):
        """PRD §2.1: 'Requests missing or carrying invalid values for these
        two headers are rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.'

        Claim: omitting only X-User-Role still triggers the header error.
        """
        resp = api._request(
            "GET", "/locker-machines",
            headers={"X-User-ID": "x", "Content-Type": "application/json"},
        )
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )

    def test_unknown_role_returns_header_error(self, api):
        """PRD §2.1: 'The system recognises four role names, spelled exactly:
        OperationsAdmin, Courier, Recipient, and Any.'

        Claim: an unrecognised role triggers ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
        because PRD §2.1 names the rejection error for invalid header values.
        """
        resp = api._request(
            "GET", "/locker-machines",
            headers={
                "X-User-ID": "x", "X-User-Role": "Mystery",
                "Content-Type": "application/json",
            },
        )
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )


class TestRoleAuthorization:
    """PRD §2.1: 'A header pair that authenticates but whose role is not
    permitted for the requested endpoint is rejected with
    ERR_INSUFFICIENT_PERMISSIONS.'"""

    def test_recipient_cannot_create_locker_machine(
        self, api, recipient_headers,
    ):
        """PRD §4: 'POST /locker-machines | Create a LockerMachine |
        OperationsAdmin'.

        Claim: a Recipient calling POST /locker-machines is rejected with
        ERR_INSUFFICIENT_PERMISSIONS (PRD §2.1).
        """
        resp = api.create_locker_machine(
            create_locker_machine_payload(), recipient_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_any_role_cannot_create_courier(self, api, any_headers):
        """PRD §4: 'POST /couriers | Register a Courier | OperationsAdmin'.

        Claim: an Any-role principal calling POST /couriers is rejected
        with ERR_INSUFFICIENT_PERMISSIONS (PRD §2.1).
        """
        resp = api.create_courier(create_courier_payload(), any_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_operations_admin_cannot_create_parcel(
        self, api, operations_admin_headers,
    ):
        """PRD §4: 'POST /parcels | Begin deposit … | Courier'.

        Claim: an OperationsAdmin calling POST /parcels is rejected with
        ERR_INSUFFICIENT_PERMISSIONS — POST /parcels is exclusive to Courier.
        """
        machine, _, _ = setup_basic_scenario()
        resp = api.create_parcel(
            {
                "tracking_no": "T-1",
                "locker_machine_id": machine["id"],
                "recipient_phone": "+15551112222",
                "required_size": "MEDIUM",
            },
            operations_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


class TestSuccessEnvelope:
    """PRD §2.2: 'All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body.'"""

    def test_create_machine_returns_201_with_envelope(
        self, api, operations_admin_headers,
    ):
        """PRD §4: 'endpoints that create a brand-new top-level resource
        return 201'.

        Claim: POST /locker-machines returns 201 and a success envelope
        whose data field carries the created machine.
        """
        resp = api.create_locker_machine(
            create_locker_machine_payload(), operations_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert "id" in data, "data must carry the created machine"
        body = resp.json()
        assert body["response_type"] == "object"
        assert "api_request_id" in body["meta"]
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id 'starts with req_'."
        )

    def test_list_machines_returns_paginated_envelope(
        self, api, operations_admin_headers,
    ):
        """PRD §2.3: 'The meta object on list responses always carries
        limit, offset, total_count, and has_more.'

        Claim: GET /locker-machines returns the paginated envelope.
        """
        api.create_locker_machine(
            create_locker_machine_payload(), operations_admin_headers,
        )
        resp = api.list_locker_machines(operations_admin_headers)
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert "total_count" in meta
        assert "has_more" in meta
        assert "limit" in meta
        assert "offset" in meta


class TestPaginationDefaults:
    """PRD §2.3: 'when omitted [limit] defaults to 10, with a minimum of 1
    and a maximum of 100.'"""

    def test_default_limit_is_10(self, api, operations_admin_headers):
        """PRD §2.3: 'when omitted it defaults to 10'.

        Claim: GET /locker-machines without a limit param returns
        meta.limit == 10.
        """
        for _ in range(3):
            api.create_locker_machine(
                create_locker_machine_payload(), operations_admin_headers,
            )
        resp = api.list_locker_machines(operations_admin_headers)
        _, meta = validate_paginated(resp)
        assert meta["limit"] == 10, (
            f"PRD §2.3 default limit is 10; got {meta['limit']}"
        )

    def test_default_offset_is_0(self, api, operations_admin_headers):
        """PRD §2.3: 'The offset parameter specifies the number of items to
        skip and defaults to 0.'

        Claim: GET /locker-machines returns meta.offset == 0 by default.
        """
        resp = api.list_locker_machines(operations_admin_headers)
        _, meta = validate_paginated(resp)
        assert meta["offset"] == 0


class TestNotFound:
    """PRD §2.6: 'A request whose first unresolvable identifier is the
    machine fails with ERR_RESOURCE_NOT_FOUND keyed to the machine, even
    if the inner identifiers would also have been invalid.'"""

    def test_machine_not_found_first_id(self, api, operations_admin_headers):
        """PRD §2.6: 'the server validates the path identifiers strictly
        left-to-right: the machine is resolved before the compartment, and
        the parcel is resolved before any sub-resource of that parcel.'

        Claim: GET /locker-machines/{nonexistent}/compartments/{anything}
        returns ERR_RESOURCE_NOT_FOUND keyed to the (missing) machine —
        the inner identifier is not consulted.
        """
        resp = api.get_compartment(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, operations_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

    def test_parcel_not_found_returns_404(
        self, api, operations_admin_headers,
    ):
        """PRD §2.6 + §5: ERR_RESOURCE_NOT_FOUND has HTTP status 404 and
        applies when a path-id resource does not exist.

        Claim: GET /parcels/{nonexistent} returns ERR_RESOURCE_NOT_FOUND.
        """
        resp = api.get_parcel(
            NON_EXISTENT_UUID, operations_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

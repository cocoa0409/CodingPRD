"""Errors: which 404 code a syntactically valid identifier that names nothing produces."""
from test_helpers import (
    ADMIN_HEADERS,
    APPROVER_HEADERS,
    COMMENTER_HEADERS,
    PORTING_HEADERS,
    UNKNOWN_ID,
    ApiErrorId,
    api_client,
    create_allocation_request_payload,
    create_eligible_carrier,
    make_carrier_representative_headers,
    read_rate_center,
    set_clock,
    setup_npa_with_rate_center,
    validate_error,
    validate_paginated,
)

INFO_NOTE = "please attach the switch inventory"
UNKNOWN_RATE_CENTER_ID = "00000000-0000-4000-8000-000000000001"


class TestAnUnknownBlockIdReportsTheBlockCode:
    """The block read is refused before any pooling or routing logic runs."""

    def test_the_block_read_reports_the_block_specific_not_found_code(self):
        """No block has ever been loaded, and the read answers with the block's own code
        rather than the code of any parent it might have had.

        and the first segment that names a row which does not exist terminates the request with that segment's own 404 code

        The available not-found codes are `ERR_CARRIER_NOT_FOUND`, `ERR_NPA_NOT_FOUND`, `ERR_RATE_CENTER_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`, `ERR_ALLOCATION_REQUEST_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, `ERR_AUDIT_FINDING_NOT_FOUND`, `ERR_RECLAMATION_ORDER_NOT_FOUND`, `ERR_RELIEF_PLAN_NOT_FOUND` and `ERR_PORT_REQUEST_NOT_FOUND`, each returned with HTTP 404.

        Design: Corner/errors/block_not_found_for_unknown_block_id
        """
        set_clock()

        error = validate_error(
            api_client.get_block(UNKNOWN_ID, ADMIN_HEADERS),
            ApiErrorId.ERR_BLOCK_NOT_FOUND,
            404,
        )
        assert error["error_id"] != ApiErrorId.ERR_RATE_CENTER_NOT_FOUND.value
        assert error["error_id"] != ApiErrorId.ERR_CARRIER_NOT_FOUND.value

        _rows, meta = validate_paginated(api_client.list_blocks(ADMIN_HEADERS))
        assert meta["total_count"] == 0


class TestAnUnknownRequestIdOutranksTheActionChecks:
    """The path is resolved before either the action gate or the cycle ceiling."""

    def test_a_review_against_an_unknown_request_reports_the_request_code(self):
        """The action is legal for this role and no cycle has been consumed, so the only
        thing wrong with the call is the id in its path.

        every resource named in the path exists, resolved left to right, else that segment's own not-found code. Applies to every endpoint with path parameters.

        the specific action or event is permitted for the acting role, else `ERR_ACTION_ROLE_MISMATCH`. Applies to every transition, review, licence-action, readiness-event, disposition and pooling-transition endpoint.

        Design: Corner/errors/allocation_request_not_found_on_review_of_unknown_request
        """
        set_clock()

        error = validate_error(
            api_client.create_review(
                UNKNOWN_ID,
                {"action": "REQUEST_INFO", "info_note": INFO_NOTE},
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_ALLOCATION_REQUEST_NOT_FOUND,
            404,
        )
        assert error["error_id"] != ApiErrorId.ERR_ACTION_ROLE_MISMATCH.value
        assert error["error_id"] != ApiErrorId.ERR_INFO_CYCLE_LIMIT_REACHED.value

        _rows, meta = validate_paginated(
            api_client.list_allocation_requests(ADMIN_HEADERS)
        )
        assert meta["total_count"] == 0


class TestAnUnknownFilingIdReportsTheFilingCode:
    """The approver is allowed to read every filing, so the refusal is about the id."""

    def test_the_filing_read_reports_the_filing_specific_not_found_code(self):
        """The acting role is authorized on the endpoint, so the role gate stands down and
        the path resolution produces the answer.

        and the first segment that names a row which does not exist terminates the request with that segment's own 404 code

        A request naming a missing area code and a missing rate center beneath it reports the area code's failure, because that segment is resolved first.

        Design: Corner/errors/filing_not_found_for_unknown_filing_id
        """
        set_clock()

        error = validate_error(
            api_client.get_utilization_filing(UNKNOWN_ID, APPROVER_HEADERS),
            ApiErrorId.ERR_FILING_NOT_FOUND,
            404,
        )
        assert error["error_id"] != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value

        _rows, meta = validate_paginated(
            api_client.list_utilization_filings(APPROVER_HEADERS)
        )
        assert meta["total_count"] == 0


class TestAnUnknownFindingIdIsNotAMissingFiling:
    """A finding is created under a filing but addressed by its own top-level path."""

    def test_the_finding_read_reports_the_finding_code_not_the_filing_code(self):
        """Neither row exists, and the single path segment that was actually named is the
        one that reports.

        every resource named in the path exists, resolved left to right, else that segment's own not-found code. Applies to every endpoint with path parameters.

        The available not-found codes are `ERR_CARRIER_NOT_FOUND`, `ERR_NPA_NOT_FOUND`, `ERR_RATE_CENTER_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`, `ERR_ALLOCATION_REQUEST_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, `ERR_AUDIT_FINDING_NOT_FOUND`, `ERR_RECLAMATION_ORDER_NOT_FOUND`, `ERR_RELIEF_PLAN_NOT_FOUND` and `ERR_PORT_REQUEST_NOT_FOUND`, each returned with HTTP 404.

        Design: Corner/errors/audit_finding_not_found_for_unknown_finding_id
        """
        set_clock()

        error = validate_error(
            api_client.get_audit_finding(UNKNOWN_ID, ADMIN_HEADERS),
            ApiErrorId.ERR_AUDIT_FINDING_NOT_FOUND,
            404,
        )
        assert error["error_id"] != ApiErrorId.ERR_FILING_NOT_FOUND.value


class TestAnUnknownOrderIdReportsTheOrderCode:
    """Orders are only ever minted by a sweep, so an unknown id is the only probe."""

    def test_the_order_read_reports_the_order_specific_not_found_code(self):
        """No sweep has run and no licence has been revoked, so the ledger is empty and the
        read has nothing to resolve.

        and the first segment that names a row which does not exist terminates the request with that segment's own 404 code

        Every order created by pass one opens with `status` `ISSUED`, `issued_at` at the sweep instant, `response_due_at` 30 days after the sweep instant, `carrier_id` copied from the block's `holder_carrier_id` at issuance, `number_block_id` naming the block, `executed_at` null, `appeal_note` null and `strike_applied` false.

        Design: Corner/errors/reclamation_order_not_found_for_unknown_order_id
        """
        set_clock()

        validate_error(
            api_client.get_reclamation_order(UNKNOWN_ID, ADMIN_HEADERS),
            ApiErrorId.ERR_RECLAMATION_ORDER_NOT_FOUND,
            404,
        )

        _rows, meta = validate_paginated(
            api_client.list_reclamation_orders(ADMIN_HEADERS)
        )
        assert meta["total_count"] == 0


class TestAnUnknownPlanIdReportsThePlanCodeToACommenter:
    """The public commenter is a permitted reader, so the role gate cannot fire."""

    def test_the_plan_read_reports_the_plan_code_rather_than_the_role_code(self):
        """The one role with no other visibility into the system still gets the plan's own
        404 rather than a refusal.

        every resource named in the path exists, resolved left to right, else that segment's own not-found code. Applies to every endpoint with path parameters.

        A `PublicCommenter` is a member of the public, a business, or a government body; it sees only the area-code and relief surface and may file comment on a relief plan.

        Design: Corner/errors/relief_plan_not_found_for_unknown_plan_id
        """
        set_clock()

        error = validate_error(
            api_client.get_relief_plan(UNKNOWN_ID, COMMENTER_HEADERS),
            ApiErrorId.ERR_RELIEF_PLAN_NOT_FOUND,
            404,
        )
        assert error["error_id"] != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value

        _rows, meta = validate_paginated(api_client.list_relief_plans(COMMENTER_HEADERS))
        assert meta["total_count"] == 0


class TestAnUnknownPortRequestIdIsNotAMissingBlock:
    """The porting operator reaches the port request by its own id."""

    def test_the_port_read_reports_the_port_code_not_the_block_code(self):
        """The same workflow can raise the block-level 404, and this call raises the port
        request's instead.

        and the first segment that names a row which does not exist terminates the request with that segment's own 404 code

        `PortingOperations` runs the number portability database and does nothing else: it activates concurred ports and cancels or snaps back activated ones.

        Design: Corner/errors/port_request_not_found_for_unknown_port_request_id
        """
        set_clock()

        error = validate_error(
            api_client.get_port_request(UNKNOWN_ID, PORTING_HEADERS),
            ApiErrorId.ERR_PORT_REQUEST_NOT_FOUND,
            404,
        )
        assert error["error_id"] != ApiErrorId.ERR_BLOCK_NOT_FOUND.value

        _rows, meta = validate_paginated(api_client.list_port_requests(PORTING_HEADERS))
        assert meta["total_count"] == 0


class TestAResolvableCarrierLeavesTheRateCenterToReport:
    """Only the second body reference is unknown, so it is the one that reports."""

    def test_the_unknown_rate_center_is_reported_when_the_carrier_resolves(self):
        """The applicant holds no filing at all, yet the answer is the rate center's 404
        rather than the filing prerequisite that would otherwise bite.

        every foreign key in the body resolves, checked in payload declaration order, else that key's own not-found code.

        Body-borne references are resolved in the order the payload declares them, and the first unresolvable reference reports its own 404 code.

        Design: Corner/errors/rate_center_not_found_when_the_body_names_an_unknown_rate_center
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        _npa, rate_center = setup_npa_with_rate_center()

        error = validate_error(
            api_client.create_allocation_request(
                create_allocation_request_payload(
                    carrier["id"], UNKNOWN_RATE_CENTER_ID, rate_center["version"],
                    request_type="GROWTH", requested_block_count=1,
                    justification="growth against an unknown rate center",
                ),
                make_carrier_representative_headers(carrier["id"]),
            ),
            ApiErrorId.ERR_RATE_CENTER_NOT_FOUND,
            404,
        )
        assert error["error_id"] != ApiErrorId.ERR_CARRIER_NOT_FOUND.value
        assert error["error_id"] != ApiErrorId.ERR_UTILIZATION_FILING_REQUIRED.value

        _rows, meta = validate_paginated(
            api_client.list_allocation_requests(ADMIN_HEADERS)
        )
        assert meta["total_count"] == 0
        assert read_rate_center(rate_center["id"])["pending_request_count"] == 0

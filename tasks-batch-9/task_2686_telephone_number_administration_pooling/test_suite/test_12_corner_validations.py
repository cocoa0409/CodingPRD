"""Validations: which of several live grounds is reported, and what a passing check lets through."""
from test_helpers import (
    ADMIN_HEADERS,
    CLOCK_PLUS_30,
    COMMENTER_HEADERS,
    DEFAULT_CLOCK,
    NO_AUTH_HEADERS,
    UNKNOWN_ID,
    ApiErrorId,
    api_client,
    assert_pct,
    create_allocation_request_payload,
    create_carrier_payload,
    create_eligible_carrier,
    create_npa,
    create_rate_center_payload,
    create_submitted_filing,
    file_allocation_request,
    file_comment,
    make_carrier_representative_headers,
    read_carrier,
    read_rate_center,
    read_relief_plan,
    read_request,
    set_clock,
    setup_npa_with_rate_center,
    setup_plan_in_public_comment,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_RATE_CENTER_ID = "00000000-0000-4000-8000-000000000001"
MICHIGAN_SWITCH_CLLI = "DTRTMI01DS0"
TEN_DAYS_INTO_THE_WINDOW = "2026-08-11T00:00:00Z"

# 3000 assigned over four blocks: an effective filing that satisfies the filing prerequisite.
SEVENTY_FIVE_PERCENT = dict(
    numbers_assigned=3000,
    numbers_intermediate=0,
    numbers_reserved=0,
    numbers_aging=0,
    numbers_administrative=0,
    blocks_held_at_period_end=4,
    forecast_quarters=[1500, 1500, 1500, 1500],
)


def _carrier_count() -> int:
    _rows, meta = validate_paginated(api_client.list_carriers(ADMIN_HEADERS))
    return meta["total_count"]


def _attempt_allocation_request(carrier_id, rate_center_id, version, **overrides):
    """File a request as the named carrier and hand back the raw response."""
    payload = create_allocation_request_payload(
        carrier_id, rate_center_id, version, **overrides
    )
    return api_client.create_allocation_request(
        payload, make_carrier_representative_headers(carrier_id)
    )


class TestAuthenticationIsDecidedBeforeTheBody:
    """An unauthenticated call is turned away without the payload ever being read."""

    def test_a_headerless_call_with_a_malformed_payload_reports_authentication(self):
        """The body is missing its required OCN as well, and the answer is still the
        authentication failure rather than the payload one.

        If either header is absent or present but empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). No further validation runs; authentication is the first gate in the pipeline.

        Implementations must evaluate in this order rather than returning whichever check happens to run first, because the choice of error code is observable.

        Design: Corner/validations/missing_auth_header_returns_unauthenticated_before_payload_checks
        """
        set_clock()

        error = validate_error(
            api_client.create_carrier(
                {
                    "legal_name": "Nameless Telecom LLC",
                    "carrier_type": "CLEC",
                    "home_state_code": "OH",
                },
                NO_AUTH_HEADERS,
            ),
            ApiErrorId.ERR_UNAUTHENTICATED,
            401,
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value

        rows, meta = validate_paginated(api_client.list_carriers(ADMIN_HEADERS))
        assert rows == []
        assert meta["total_count"] == 0


class TestTheEndpointRoleGateOutranksThePayloadShape:
    """A role that may not call the endpoint never reaches the enum check."""

    def test_a_public_commenter_registering_a_carrier_reports_the_role(self):
        """The payload also carries a carrier type that is not one of the four declared
        values, and the refusal still names the role.

        When the acting role is not among the roles authorized for the endpoint being called, the request fails with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

        every enumerated field carrying a declared value, integer counts not negative

        Design: Corner/validations/public_commenter_creating_a_carrier_is_role_not_permitted
        """
        set_clock()

        error = validate_error(
            api_client.create_carrier(
                create_carrier_payload("A", carrier_type="MOBILE_VIRTUAL"),
                COMMENTER_HEADERS,
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value
        assert _carrier_count() == 0


class TestBodyForeignKeysResolveInDeclarationOrder:
    """Two unresolvable references, and the first one declared is the one reported."""

    def test_the_unknown_carrier_is_reported_before_the_unknown_rate_center(self):
        """Both ids name nothing at all, and the request names the carrier first.

        The same discipline extends to foreign keys supplied in a request body rather than in the path.

        Body-borne references are resolved in the order the payload declares them, and the first unresolvable reference reports its own 404 code.

        when filing an allocation request (which names `carrier_id`, then `rate_center_id`)

        Design: Corner/validations/unknown_carrier_id_is_reported_before_unknown_rate_center_id
        """
        set_clock()
        _npa, rate_center = setup_npa_with_rate_center()

        error = validate_error(
            _attempt_allocation_request(
                UNKNOWN_ID, UNKNOWN_RATE_CENTER_ID, rate_center["version"],
                request_type="GROWTH", requested_block_count=1,
                justification="Request naming two unknown foreign keys",
            ),
            ApiErrorId.ERR_CARRIER_NOT_FOUND,
            404,
        )
        assert error["error_id"] != ApiErrorId.ERR_RATE_CENTER_NOT_FOUND.value

        _rows, meta = validate_paginated(
            api_client.list_allocation_requests(ADMIN_HEADERS)
        )
        assert meta["total_count"] == 0


class TestAnInitialRequestMustMatchTheApplicantsOwnState:
    """The extra jurisdiction clause bites only on the initial route."""

    def test_a_michigan_carrier_applying_into_an_ohio_rate_center_is_refused(self):
        """Carrier, rate center and area code are each perfectly valid and the applicant is
        fully eligible; it is the three-way agreement that fails.

        for an `INITIAL` request it must additionally equal the applicant carrier's `home_state_code`, otherwise `ERR_JURISDICTION_MISMATCH`

        An `INITIAL` request also requires the rate center's computed `accepts_initial_requests` to be true

        Design: Corner/validations/initial_request_from_an_out_of_state_carrier_is_rejected
        """
        set_clock()
        out_of_state = create_eligible_carrier(
            "A", switch_clli=MICHIGAN_SWITCH_CLLI, ocn="7777",
            legal_name="Great Lakes Telecom LLC", home_state_code="MI",
            months_in_operation=4,
        )
        assert out_of_state["eligibility_status"] == "ELIGIBLE"
        assert out_of_state["home_state_code"] == "MI"
        _npa, rate_center = setup_npa_with_rate_center()
        assert rate_center["state_code"] == "OH"
        assert rate_center["accepts_initial_requests"] is True
        version_before = rate_center["version"]

        validate_error(
            _attempt_allocation_request(
                out_of_state["id"], rate_center["id"], version_before,
                request_type="INITIAL", requested_block_count=1,
                justification="Expansion into the Columbus market",
            ),
            ApiErrorId.ERR_JURISDICTION_MISMATCH,
            422,
        )

        unchanged = read_rate_center(rate_center["id"])
        assert unchanged["pending_request_count"] == 0
        assert unchanged["version"] == version_before


class TestARateCenterInheritsItsParentsJurisdiction:
    """The same agreement rule guards the rate center's own creation."""

    def test_a_michigan_rate_center_under_an_ohio_area_code_is_refused(self):
        """Nothing is written: the area code still lists no rate centers at all.

        the rate center's `state_code` must equal the `state_code` of its parent area code, and a disagreement is rejected with `ERR_JURISDICTION_MISMATCH`

        A new rate center opens at `pooling_status` `NON_POOLED` with `pooling_effective_at` null

        Design: Corner/validations/rate_center_state_must_match_its_parent_npa_state
        """
        set_clock()
        npa = create_npa()
        assert npa["state_code"] == "OH"

        validate_error(
            api_client.create_rate_center(
                create_rate_center_payload(
                    npa["id"], name="DETROIT", state_code="MI", lata_code="340"
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_JURISDICTION_MISMATCH,
            422,
        )

        _rows, meta = validate_paginated(
            api_client.list_npa_rate_centers(npa["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 0


class TestTheSafetyValveCeilingIsCheckedAtFilingTime:
    """A legal block count can still breach the one-block-per-exception limit."""

    def test_a_safety_valve_request_for_two_blocks_is_refused_before_any_review(self):
        """Two is inside the general one-to-ten range and the filing prerequisite is
        satisfied, yet the safety-valve ceiling refuses the request outright.

        a carrier may hold at most one granted safety-valve exception at a time

        a `SAFETY_VALVE` request may ask for at most one block; breaching either limit yields `ERR_SAFETY_VALVE_LIMIT_EXCEEDED`

        Design: Corner/validations/safety_valve_request_for_two_blocks_exceeds_the_limit
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        _npa, rate_center = setup_npa_with_rate_center()
        create_submitted_filing(carrier, rate_center, **SEVENTY_FIVE_PERCENT)
        assert read_carrier(carrier["id"])["safety_valve_grant_count"] == 0

        validate_error(
            _attempt_allocation_request(
                carrier["id"], rate_center["id"],
                read_rate_center(rate_center["id"])["version"],
                request_type="SAFETY_VALVE", requested_block_count=2,
                justification="Emergency numbering for a hospital campus cutover",
            ),
            ApiErrorId.ERR_SAFETY_VALVE_LIMIT_EXCEEDED,
            422,
        )

        assert read_carrier(carrier["id"])["safety_valve_grant_count"] == 0
        assert read_rate_center(rate_center["id"])["pending_request_count"] == 0


class TestTheFilingPrerequisiteIsConditionalOnTheRequestType:
    """The same carrier, the same rate center, the same version: only the route differs."""

    def test_growth_needs_a_filing_where_initial_does_not(self):
        """With no utilization report on file at all the growth route is refused, and the
        initial route is accepted on the very next call.

        A `GROWTH`, `POOL_REPLENISH` or `SAFETY_VALVE` request requires an effective filing for the same carrier and rate center to exist at all, and is otherwise refused with `ERR_UTILIZATION_FILING_REQUIRED`

        Every accepted filing advances the rate center's `version` (its pending-request counter changes)

        Design: Corner/validations/growth_request_without_an_effective_filing_is_rejected
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        _npa, rate_center = setup_npa_with_rate_center()
        version_before = rate_center["version"]

        validate_error(
            _attempt_allocation_request(
                carrier["id"], rate_center["id"], version_before,
                request_type="GROWTH", requested_block_count=1,
                justification="Growth block requested with no filing on record",
            ),
            ApiErrorId.ERR_UTILIZATION_FILING_REQUIRED,
            422,
        )
        assert read_rate_center(rate_center["id"])["version"] == version_before

        accepted = validate_success(
            _attempt_allocation_request(
                carrier["id"], rate_center["id"], version_before,
                request_type="INITIAL", requested_block_count=1,
                justification="First block in Columbus for a new market",
            ),
            201,
        )
        assert accepted["status"] == "PENDING_REVIEW"
        assert accepted["request_type"] == "INITIAL"
        assert read_rate_center(rate_center["id"])["pending_request_count"] == 1


class TestACommentInsideTheOpenWindowIsStored:
    """Ten days into a thirty-day consultation the window is genuinely open."""

    def test_the_comment_is_accepted_and_carries_its_computed_weight(self):
        """The clock sits after the opening instant and well before the closing one, so the
        comment is stored against the plan with a business weight.

        A comment is accepted only while the window is open: the logical clock must be at or after `comment_window_open_at`

        The system computes `weight` from the commenter category

        Filing a comment recomputes the plan's tallies and `comment_count` and increments the plan's `version` by 1.

        Design: Corner/validations/comment_filed_inside_the_open_window_is_accepted
        """
        set_clock()
        _npa, plan = setup_plan_in_public_comment(comment_window_days=30)
        assert plan["comment_window_open_at"] == DEFAULT_CLOCK
        assert plan["comment_window_close_at"] == CLOCK_PLUS_30
        set_clock(TEN_DAYS_INTO_THE_WINDOW)

        comment = file_comment(
            plan, "BUSINESS", "SUPPORT_SPLIT",
            "Our switchboard cannot handle mandatory ten-digit dialing yet",
        )

        assert comment["relief_plan_id"] == plan["id"]
        assert comment["commenter_type"] == "BUSINESS"
        assert comment["position"] == "SUPPORT_SPLIT"
        assert comment["submitted_at"] == TEN_DAYS_INTO_THE_WINDOW
        assert_pct(comment["weight"], 1.50, "weight")

        still_open = read_relief_plan(plan["id"])
        assert still_open["status"] == "PUBLIC_COMMENT"
        assert still_open["comment_count"] == 1
        assert still_open["recommended_relief_type"] is None

        _rows, meta = validate_paginated(
            api_client.list_relief_plan_comments(plan["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 1


class TestTheActionGateIsFinerThanTheEndpointGate:
    """The filing carrier may call the review endpoint, but not with every action."""

    def test_a_carrier_sending_approve_reports_the_action_not_the_role(self):
        """WITHDRAW would have been accepted from these very headers, so the refusal names
        the action rather than the role.

        when the acting role may call the endpoint but not with the action or event it supplied, the failure is the more specific `ERR_ACTION_ROLE_MISMATCH` (HTTP 403)

        `WITHDRAW` belongs to the filing `CarrierRepresentative`; any other pairing of role and action is the `ERR_ACTION_ROLE_MISMATCH` case from Section 2.1

        Design: Corner/validations/carrier_representative_cannot_send_approve_on_a_review
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        _npa, rate_center = setup_npa_with_rate_center()
        request = file_allocation_request(
            carrier, rate_center, request_type="INITIAL", requested_block_count=1,
            justification="First block in Columbus",
        )
        assert request["status"] == "PENDING_REVIEW"

        error = validate_error(
            api_client.create_review(
                request["id"], {"action": "APPROVE"},
                make_carrier_representative_headers(carrier["id"]),
            ),
            ApiErrorId.ERR_ACTION_ROLE_MISMATCH,
            403,
        )
        assert error["error_id"] != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value

        untouched = read_request(request["id"])
        assert untouched["status"] == "PENDING_REVIEW"
        assert untouched["approver_user_id"] is None
        assert untouched["granted_block_count"] == 0

"""RBAC: which role owns each surface, which is carved out of it, and the two duty splits."""
from test_helpers import (
    ADMIN_HEADERS,
    ADMIN_USER_ID,
    APPROVER_HEADERS,
    CLOCK_PLUS_30,
    COMMENTER_HEADERS,
    DEFAULT_CLOCK,
    PORTING_HEADERS,
    ApiErrorId,
    api_client,
    assert_pct,
    assert_sweep_report,
    close_and_recommend,
    create_block_payload,
    create_carrier_payload,
    create_eligible_carrier,
    create_npa,
    create_npa_payload,
    create_public_comment_payload,
    create_rate_center_payload,
    create_relief_plan,
    create_submitted_filing,
    declare_jeopardy,
    load_block,
    make_carrier_representative_headers,
    make_regulatory_approver_headers,
    open_audit_finding,
    open_comment_window,
    read_block,
    read_carrier,
    read_filing,
    read_finding,
    read_npa,
    read_relief_plan,
    register_carrier,
    set_clock,
    setup_npa_with_rate_center,
    setup_plan_in_public_comment,
    validate_error,
    validate_paginated,
    validate_success,
)

JEOPARDY_REASON = "forecast exhaust inside eight quarters"
SUCCESSOR_CODE = "380"
ORDER_EFFECTIVE_AT = "2027-01-01T00:00:00Z"
SELF_SIGN_NOTE = "signing off on my own finding"

# 1600 assigned over two blocks: a claim of 80.00 the auditor pulls back to 75.00.
OVERSTATED_PERIOD = dict(
    numbers_assigned=1600,
    numbers_intermediate=0,
    numbers_reserved=0,
    numbers_aging=0,
    numbers_administrative=0,
    blocks_held_at_period_end=2,
    forecast_quarters=[600, 600, 600, 600],
)


class TestTheAdministratorOwnsTheInventorySpineAndTheSweep:
    """Four creates and one sweep, every one of them from the same single role."""

    def test_the_spine_is_built_and_the_sweep_answers_with_an_empty_result(self):
        """Nothing is due at the opening instant, so the sweep is accepted and reports three
        zeroes rather than being refused, which is what proves the authorization.

        Inventory is built top-down by the `NumberingAdministrator`, and only by that role.

        Registration is an administrator's act and captures four required attributes plus one optional counter

        Only the `NumberingAdministrator` runs it, and the payload may narrow it with `rate_center_id`, which restricts every pass to blocks homed to that one rate center

        The three passes run in a fixed order and each walks its blocks in `created_at` ascending order.

        Design: Corner/rbac/numbering_administrator_exclusive_inventory_and_sweep_surface
        """
        set_clock()
        carrier = validate_success(
            api_client.create_carrier(create_carrier_payload("A"), ADMIN_HEADERS), 201
        )
        npa = validate_success(
            api_client.create_npa(create_npa_payload(), ADMIN_HEADERS), 201
        )
        rate_center = validate_success(
            api_client.create_rate_center(
                create_rate_center_payload(npa["id"]), ADMIN_HEADERS
            ),
            201,
        )
        block = validate_success(
            api_client.create_block(
                create_block_payload(
                    npa["id"], rate_center["id"], nxx_code="555", thousands_digit=0,
                    contaminated_count=0,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert carrier["ocn"] == "1234"

        sweep = validate_success(
            api_client.create_reclamation_sweep(
                {"rate_center_id": rate_center["id"]}, ADMIN_HEADERS
            ),
            200,
        )

        assert_sweep_report(sweep, 0, 0, 0, DEFAULT_CLOCK)
        assert read_block(block["id"])["allocation_status"] == "POOL_AVAILABLE"


class TestTheApproverCannotRegisterACarrier:
    """The role that outranks the administrator on approvals cannot mint an OCN holder."""

    def test_the_registration_reports_the_endpoint_role_not_the_action_role(self):
        """Registration takes no action field at all, so the finer per-action check has
        nothing to bite on and the endpoint-level gate is the one that answers.

        The `RegulatoryApprover` is the commission-side decision maker and holds exactly the three steps that hand out or lock in resources: approving an allocation, ordering relief, and disposing of an audit finding.

        When the acting role is not among the roles authorized for the endpoint being called, the request fails with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

        the acting role is authorized on this endpoint, else `ERR_ROLE_NOT_PERMITTED`. Applies to every endpoint.

        Design: Corner/rbac/regulatory_approver_cannot_register_a_carrier
        """
        set_clock()

        error = validate_error(
            api_client.create_carrier(create_carrier_payload("A"), APPROVER_HEADERS),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        assert error["error_id"] != ApiErrorId.ERR_ACTION_ROLE_MISMATCH.value

        _rows, meta = validate_paginated(api_client.list_carriers(ADMIN_HEADERS))
        assert meta["total_count"] == 0


class TestACarrierCannotLoadTheInventoryItAsksFor:
    """The intended holder is the acting carrier itself and the load is still refused."""

    def test_the_block_load_reports_the_role_rather_than_the_ownership_check(self):
        """The payload is the one the administrator would have been given, naming an eligible
        holder, so nothing but the acting role is wrong with the call.

        it registers carriers, drives their licensing, loads inventory, publishes routing data

        When the optional `holder_carrier_id` is supplied, the referenced carrier must exist and its `eligibility_status` must be either `ELIGIBLE` or `PROBATION`

        Applies to allocation-request filing and resubmission, utilization-filing creation and submission, block activation confirmation, reclamation-order transitions, port-request transitions, and carrier readiness events.

        Design: Corner/rbac/carrier_representative_cannot_load_block_inventory
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()

        error = validate_error(
            api_client.create_block(
                create_block_payload(
                    npa["id"], rate_center["id"], nxx_code="555", thousands_digit=0,
                    contaminated_count=0, holder_carrier_id=carrier["id"],
                    mark_activated=True,
                ),
                make_carrier_representative_headers(carrier["id"]),
            ),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        assert error["error_id"] != ApiErrorId.ERR_NOT_RESOURCE_OWNER.value

        _rows, meta = validate_paginated(
            api_client.list_rate_center_blocks(rate_center["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 0
        assert read_carrier(carrier["id"])["blocks_held_count"] == 0


class TestPortingOperationsIsCarvedOutOfTheAllocationListing:
    """The same role reads the block listing freely and is refused one listing away."""

    def test_the_block_listing_is_open_while_the_allocation_listing_is_refused(self):
        """Both listings are empty, so the difference between the two answers can only be the
        authorization and not anything either query found.

        `PortingOperations` runs the number portability database and does nothing else

        it activates concurred ports and cancels or snaps back activated ones

        The Authorized Role(s) column names the roles that may call the endpoint at all

        Design: Corner/rbac/porting_operations_cannot_read_the_allocation_listing
        """
        set_clock()

        _rows, meta = validate_paginated(api_client.list_blocks(PORTING_HEADERS))
        assert meta["total_count"] == 0

        validate_error(
            api_client.list_allocation_requests(PORTING_HEADERS),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )


class TestThePublicCommentersReadSurfaceIsAnAllowList:
    """The area-code listing is open to the commenter and the block listing is not."""

    def test_the_area_code_listing_is_open_while_the_block_listing_is_refused(self):
        """One area code and one block are on file, and only the area code is visible to the
        one role whose reach is an explicit allow-list.

        it sees only the area-code and relief surface and may file comment on a relief plan

        Area-code listings can be narrowed by `state_code`, by `status`, by `npa_type`, and by `relief_parent_npa_id`, the last of which finds the successor codes minted from a given parent.

        When the acting role is not among the roles authorized for the endpoint being called, the request fails with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

        Design: Corner/rbac/public_commenter_sees_the_relief_surface_and_nothing_else
        """
        set_clock()
        npa, rate_center = setup_npa_with_rate_center()
        block = load_block(npa, rate_center, nxx_code="555", thousands_digit=0)

        rows, meta = validate_paginated(
            api_client.list_npas(COMMENTER_HEADERS, params={"state_code": "OH"})
        )
        assert meta["total_count"] == 1
        assert rows[0]["npa_code"] == "614"

        validate_error(
            api_client.list_blocks(COMMENTER_HEADERS),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        assert read_block(block["id"])["allocation_status"] == "POOL_AVAILABLE"


class TestTheCommentEndpointIsSharedButStillDiscriminates:
    """Two roles write the one shared endpoint and their comments are not equivalent."""

    def test_the_consumer_and_the_carrier_are_both_accepted_at_different_weights(self):
        """The endpoint takes both identities with a 201, and the tally that follows separates
        them: one point on the overlay side against two on the split side.

        Comments are filed by a `PublicCommenter` or a `CarrierRepresentative` against an open plan and return 201.

        The system computes `weight` from the commenter category — 1.0 for a consumer, 1.5 for a business, 2.0 for a carrier and 3.0 for a government body — and stamps `submitted_at` at the logical clock.

        The tally sums `weight` across the comments supporting each option: `support_overlay_weight` from the `SUPPORT_OVERLAY` comments and `support_split_weight` from the `SUPPORT_SPLIT` comments, each summed at full precision and rounded half up to two decimal places exactly once.

        A plan's comments can be listed in `submitted_at` ascending order and filtered by `position` and `commenter_type`.

        Design: Corner/rbac/comment_endpoint_is_shared_by_commenter_and_carrier_representative
        """
        set_clock()
        carrier = register_carrier("A")
        _npa, plan = setup_plan_in_public_comment(
            comment_window_days=30, planned_relief_type="ALL_SERVICES_OVERLAY"
        )

        consumer = validate_success(
            api_client.create_public_comment(
                plan["id"],
                create_public_comment_payload(
                    "CONSUMER", "SUPPORT_OVERLAY", "an overlay keeps my number"
                ),
                COMMENTER_HEADERS,
            ),
            201,
        )
        from_carrier = validate_success(
            api_client.create_public_comment(
                plan["id"],
                create_public_comment_payload(
                    "CARRIER", "SUPPORT_SPLIT",
                    "a split is cheaper to implement in our switches",
                ),
                make_carrier_representative_headers(carrier["id"]),
            ),
            201,
        )

        assert_pct(consumer["weight"], 1.00, "consumer weight")
        assert_pct(from_carrier["weight"], 2.00, "carrier weight")

        tallied = read_relief_plan(plan["id"])
        assert tallied["comment_count"] == 2
        assert_pct(tallied["support_overlay_weight"], 1.00, "support_overlay_weight")
        assert_pct(tallied["support_split_weight"], 2.00, "support_split_weight")

        rows, meta = validate_paginated(
            api_client.list_relief_plan_comments(plan["id"], ADMIN_HEADERS)
        )
        assert meta["total_count"] == 2
        assert {row["id"]: row["commenter_type"] for row in rows} == {
            consumer["id"]: "CONSUMER", from_carrier["id"]: "CARRIER"
        }


class TestOnlyTheAdministratorOpensAConsultation:
    """Both roles may call the transitions endpoint, so only the action can refuse this."""

    def test_the_approver_reports_the_action_role_rather_than_the_endpoint_role(self):
        """The plan is sitting in planning under an area code that is genuinely in trouble, so
        the transition itself is legal and only the acting role is wrong for this action.

        on a relief-plan transition only a `RegulatoryApprover` may send `ORDER` while only a `NumberingAdministrator` may send `OPEN_COMMENT`, `CLOSE_AND_RECOMMEND` or `WITHDRAW`

        when the acting role may call the endpoint but not with the action or event it supplied, the failure is the more specific `ERR_ACTION_ROLE_MISMATCH` (HTTP 403)

        It stamps `comment_window_open_at` at the logical clock and `comment_window_close_at` at `comment_window_days` after that instant, sets the area code's `status` to `RELIEF_PLANNED` if it is not already

        Design: Corner/rbac/regulatory_approver_cannot_open_a_comment_window
        """
        set_clock()
        npa = create_npa()
        declare_jeopardy(npa, reason=JEOPARDY_REASON)
        plan = create_relief_plan(
            npa, planned_relief_type="ALL_SERVICES_OVERLAY", comment_window_days=30,
            new_npa_code=SUCCESSOR_CODE,
        )
        assert plan["status"] == "PLANNING"

        error = validate_error(
            api_client.create_relief_transition(
                plan["id"], {"action": "OPEN_COMMENT"}, APPROVER_HEADERS
            ),
            ApiErrorId.ERR_ACTION_ROLE_MISMATCH,
            403,
        )
        assert error["error_id"] != ApiErrorId.ERR_ROLE_NOT_PERMITTED.value

        unopened = read_relief_plan(plan["id"])
        assert unopened["status"] == "PLANNING"
        assert unopened["comment_window_open_at"] is None
        assert unopened["comment_window_close_at"] is None

        # No cascade fired: the area code was never moved on to relief planning.
        assert read_npa(npa["id"])["status"] == "JEOPARDY"


class TestTheAuditorCannotDisposeOfItsOwnFinding:
    """The refusal keys on the acting user id and not on the acting role."""

    def test_the_administrators_own_id_wearing_the_approver_role_is_refused(self):
        """The call carries the one role allowed to dispose and a well-formed acceptance, and
        is turned away only because that user is the one who opened the finding.

        the user who recorded an audit finding may not dispose of it, the user who first requested information on or denied an allocation request may not later approve it, and the user who recommended a relief type may not order it.

        Disposing of a finding belongs to the `RegulatoryApprover` and to nobody else, and the acting `X-User-ID` must differ from the finding's `auditor_user_id`

        The finding is created at `status` `OPEN` with `auditor_user_id` set to the acting `X-User-ID`, `disposed_by_user_id` null, and an optional `disposition_note`.

        An audit begins when a `NumberingAdministrator` records a finding against a filing that is in `SUBMITTED` or already `UNDER_AUDIT` status, which drives that filing `SUBMITTED → UNDER_AUDIT`.

        Design: Corner/rbac/same_user_cannot_audit_a_filing_and_dispose_of_its_finding
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        _npa, rate_center = setup_npa_with_rate_center()
        filing = create_submitted_filing(carrier, rate_center, **OVERSTATED_PERIOD)
        finding = open_audit_finding(
            filing, finding_type="OVERSTATED_UTILIZATION",
            adjusted_numbers_assigned=1500,
        )
        assert finding["auditor_user_id"] == ADMIN_USER_ID

        validate_error(
            api_client.create_disposition(
                finding["id"],
                {"disposition": "ACCEPT", "disposition_note": SELF_SIGN_NOTE},
                make_regulatory_approver_headers(ADMIN_USER_ID),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        still_open = read_finding(finding["id"])
        assert still_open["status"] == "OPEN"
        assert still_open["auditor_user_id"] == ADMIN_USER_ID
        assert still_open["disposed_by_user_id"] is None

        under_audit = read_filing(filing["id"])
        assert under_audit["status"] == "UNDER_AUDIT"
        assert under_audit["audited_utilization_pct"] is None

        # The probation penalty never fired, because nothing was ever accepted.
        assert read_carrier(carrier["id"])["eligibility_status"] == "ELIGIBLE"


class TestTheRecommenderCannotOrderTheReliefItRecommended:
    """A different stored id on a different entity, refused for the same reason."""

    def test_the_order_is_refused_and_no_successor_code_is_ever_minted(self):
        """The window is closed, the successor code collides with nothing and the effective
        date clears the buffer, so the only live objection is who is asking.

        The acting `X-User-ID` must differ from `recommender_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`: the official who read the comments may not be the one who orders the outcome.

        records the acting `X-User-ID` in `recommender_user_id`, and moves the plan to `OVERLAY_RECOMMENDED` or `SPLIT_RECOMMENDED` according to the recommendation

        a tie recommends the overlay, and a plan closed with no comments at all recommends the overlay with both weights at 0.00 and `comment_count` at 0

        Ordering creates or activates the successor area code with `npa_type` `OVERLAY` for an overlay

        Design: Corner/rbac/same_user_cannot_recommend_relief_and_order_it
        """
        set_clock()
        npa = create_npa()
        declare_jeopardy(npa, reason=JEOPARDY_REASON)
        plan = create_relief_plan(
            npa, planned_relief_type="ALL_SERVICES_OVERLAY", comment_window_days=30,
            new_npa_code=SUCCESSOR_CODE,
        )
        opened = open_comment_window(plan)
        assert opened["comment_window_close_at"] == CLOCK_PLUS_30

        set_clock(CLOCK_PLUS_30)
        recommended = close_and_recommend(plan)
        assert recommended["status"] == "OVERLAY_RECOMMENDED"
        assert recommended["recommender_user_id"] == ADMIN_USER_ID
        assert recommended["comment_count"] == 0

        error = validate_error(
            api_client.create_relief_transition(
                plan["id"],
                {"action": "ORDER", "new_npa_code": SUCCESSOR_CODE,
                 "effective_at": ORDER_EFFECTIVE_AT},
                make_regulatory_approver_headers(ADMIN_USER_ID),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        assert error["error_id"] != ApiErrorId.ERR_DUPLICATE_NPA_CODE.value
        assert error["error_id"] != ApiErrorId.ERR_RELIEF_WINDOW_OVERLAP.value

        unordered = read_relief_plan(plan["id"])
        assert unordered["status"] == "OVERLAY_RECOMMENDED"
        assert unordered["recommender_user_id"] == ADMIN_USER_ID
        assert unordered["recommended_relief_type"] == "ALL_SERVICES_OVERLAY"
        assert unordered["successor_npa_id"] is None

        # OPEN_COMMENT set the code to RELIEF_PLANNED and only a withdrawal would
        # release it, so the refused order leaves the consultation posture intact.
        assert read_npa(npa["id"])["status"] == "RELIEF_PLANNED"
        _rows, meta = validate_paginated(api_client.list_npas(ADMIN_HEADERS))
        assert meta["total_count"] == 1

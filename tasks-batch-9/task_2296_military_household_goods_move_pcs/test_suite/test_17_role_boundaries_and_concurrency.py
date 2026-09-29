"""Authentication, role membership, ownership, segregation of duties and version conflicts."""

import pytest

from test_helpers import (
    ADMIN,
    ADMIN_USER_ID,
    COUNSELOR,
    COUNSELOR_USER_ID,
    EXAMINER,
    EXAMINER_ALT_USER_ID,
    EXAMINER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    authorize_entitlement,
    authorize_entitlement_payload,
    award_payload,
    award_shipment,
    book_shipment,
    cancel_shipment_payload,
    complete_counseling_payload,
    create_capacity_block,
    create_counseling_session,
    create_order,
    create_service_member,
    create_shipment_payload,
    create_tsp,
    declare_pro_gear,
    deliver_shipment,
    disposition_item,
    excess_cost_waiver_payload,
    get_success_data,
    headers_with_unknown_role,
    headers_without_role,
    make_service_member_headers,
    make_tsp_coordinator_headers,
    pack_shipment,
    pickup_shipment,
    read_capacity_block,
    read_claim,
    read_entitlement,
    read_shipment,
    read_tsp,
    record_actual_weight,
    reject_pro_gear_payload,
    review_claim,
    room_estimates,
    set_clock,
    settle_claim,
    settle_claim_payload,
    setup_booked_shipment,
    setup_delivered_shipment_with_claim,
    setup_second_shipment,
    setup_surveyed_shipment,
    setup_weighed_shipment,
    submit_claim,
    survey_shipment,
    validate_error,
    validate_paginated,
    validate_success,
    verify_pro_gear,
    waive_excess_cost,
)

WEIGH_DATE = "2026-08-17T00:00:00Z"
FILING_CLOCK = "2026-09-01T00:00:00Z"
NOTICE_DATE = "2026-08-25T00:00:00Z"
UNDECLARED_ROLE = "TransportationAuditor"
AUDITOR_USER_ID = "auditor-01"
SECOND_MEMBER_DOD_ID = "7000000002"
E5_ALONE = {"rank_code": "E5", "dependents_count": 0, "spouse_present": False}
SECOND_LOT = {
    "requested_pack_date": "2026-08-16T00:00:00Z",
    "requested_pickup_date": "2026-08-19T00:00:00Z",
    "requested_delivery_date": "2026-08-26T00:00:00Z",
}
SMALL_LOT = 40.0
FURNITURE_ITEM = {
    "replacement_cost_usd": 1000.00,
    "category": "FURNITURE",
    "age_years": 3.0,
    "item_description": "DINING TABLE",
    "high_value_inventory_documented": False,
}


def _read_member(member_id, headers=COUNSELOR):
    return api_client.get_service_member(member_id, headers)


def _active_count(member_id):
    return get_success_data(_read_member(member_id))["active_shipment_count"]


def _second_member():
    """A second registered member who owns nothing at all."""
    member = create_service_member(
        dod_id=SECOND_MEMBER_DOD_ID, dependents_count=0, spouse_present=False
    )
    return member, make_service_member_headers(member["id"])


def _authorize(entitlement_id, headers):
    return api_client.authorize_entitlement(
        entitlement_id, authorize_entitlement_payload(), headers
    )


def _waiver(entitlement_id, amount, headers, waiver_reason):
    return api_client.create_excess_cost_waiver(
        entitlement_id,
        excess_cost_waiver_payload(amount, waiver_reason=waiver_reason),
        headers,
    )


def _claim_under_review_for_one_thousand():
    """A delivered move whose 1,000.00 furniture claim is under review by the first examiner."""
    scenario = setup_delivered_shipment_with_claim(
        weigh_date=WEIGH_DATE,
        notice_date=NOTICE_DATE,
        claim_overrides={"claim_type": "DAMAGE"},
        items=[FURNITURE_ITEM],
    )
    claim_id = scenario["claim"]["id"]
    set_clock(FILING_CLOCK)
    submit_claim(scenario, claim_id)
    scenario["claim"] = review_claim(claim_id)
    disposition_item(scenario["claim_items"][0]["id"], "ALLOWED")
    return scenario


def _entitlement_authorized_by_the_program_office():
    """An E5 ledger authorized by admin-01 and then driven over its 7,000 pound cap."""
    return setup_weighed_shipment(
        12000,
        2000,
        weigh_date=WEIGH_DATE,
        member_overrides=E5_ALONE,
        block_overrides={"total_capacity_lbs": 20000},
        authorize_headers=ADMIN,
    )


def _counselor_run_through_survey():
    """Every counselor-exclusive step from completion to survey, kept as separate calls."""
    set_clock()
    member = create_service_member()
    order = create_order(member["id"])
    session = create_counseling_session(order["id"], session_type="IN_PERSON")
    scenario = {"member": member, "order": order, "session": session}
    return scenario


def _two_surveyed_lots_and_a_block():
    """One 5,286 pound lot, one 294 pound lot and a 12,000 pound peak week."""
    scenario = setup_surveyed_shipment()
    second = setup_second_shipment(scenario, shipment_code="SHP-C02", **SECOND_LOT)
    scenario["shipment_2"] = survey_shipment(
        scenario, shipment_id=second["id"], room_estimates=room_estimates(SMALL_LOT)
    )
    scenario["block"] = create_capacity_block(scenario["tsp"]["id"])
    return scenario


class TestAuthenticationAndRoleMembership:
    """A missing role, an undeclared role and a declared role that is simply the wrong one."""

    def test_a_missing_or_undeclared_role_never_reaches_the_role_check(self):
        """Both headers resolve to 401, while a declared role reads the same record happily.

        "If either header is absent, or if `X-User-Role` is any string outside that set of
        five, the request is rejected with `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/read_with_missing_x_user_role_header_returns_unauthenticated
        """
        set_clock()
        member = create_service_member()

        validate_error(
            _read_member(member["id"], headers_without_role()),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            _read_member(
                member["id"],
                headers_with_unknown_role(UNDECLARED_ROLE, user_id=AUDITOR_USER_ID),
            ),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )

        readable = validate_success(
            _read_member(member["id"], TEST_USERS["tsp_coordinator_headers"]), 200
        )
        assert readable["full_name"] == "Dana Reyes"
        assert readable["id"] == member["id"]
        assert readable["active_shipment_count"] == 0

    def test_a_coordinator_may_not_authorize_someone_elses_entitlement(self):
        """The provider's coordinator is a real identity holding the wrong ticket.

        "If the headers are well formed but the acting role does not appear in the
        authorised-role list published for the endpoint in §4, the request is rejected with
        `ERR_UNAUTHORIZED` (403)."

        "Authorizing the entitlement moves it `DRAFT → AUTHORIZED` and is available to a
        counselor or administrator"

        Design: Corner/rbac/tsp_coordinator_cannot_authorize_an_entitlement_unauthorized
        """
        set_clock()
        member = create_service_member()
        order = create_order(member["id"])
        session = create_counseling_session(order["id"], session_type="IN_PERSON")
        _, before = validate_paginated(
            api_client.list_order_entitlements(order["id"], COUNSELOR)
        )
        assert before["total_count"] == 0

        validate_success(
            api_client.complete_counseling_session(
                session["id"], complete_counseling_payload(), COUNSELOR
            ),
            200,
        )
        entitlement = get_success_data(
            api_client.list_counseling_session_entitlements(session["id"], COUNSELOR)
        )[0]
        assert entitlement["status"] == "DRAFT"

        tsp = create_tsp()
        validate_error(
            _authorize(entitlement["id"], make_tsp_coordinator_headers(tsp["id"])),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        untouched = read_entitlement(entitlement["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["authorized_by_user_id"] is None

        authorized = validate_success(
            _authorize(entitlement["id"], COUNSELOR), 200
        )
        assert authorized["status"] == "AUTHORIZED"
        assert authorized["authorized_by_user_id"] == COUNSELOR_USER_ID


class TestOwnershipBoundaries:
    """One member's shipment stays invisible and untouchable to the other member."""

    def test_a_peer_member_can_neither_read_nor_cancel_the_shipment(self):
        """The stranger is refused on ownership, not on existence, and the lot never moves.

        "On every endpoint that a `ServiceMember` is permitted to call, the server resolves the
        target resource back to a `ServiceMember` identifier — a shipment through its order to
        `service_member_id`, a claim through its shipment and that shipment's order, a pro-gear
        declaration or PPM packet through its shipment, a counseling session or entitlement
        through its order — and rejects the request with `ERR_OWNERSHIP_REQUIRED` (403) when
        the resolved identifier is not the caller's `X-User-ID`."

        Design: Corner/rbac/service_member_cannot_read_another_members_shipment
        """
        scenario = setup_booked_shipment()
        shipment_id = scenario["shipment"]["id"]
        _, stranger_headers = _second_member()

        validate_error(
            api_client.get_shipment(shipment_id, stranger_headers),
            ApiErrorId.ERR_OWNERSHIP_REQUIRED.value,
            403,
        )

        own = validate_success(
            api_client.get_shipment(shipment_id, scenario["member_headers"]), 200
        )
        assert own["shipment_code"] == "SHP-C01"
        assert own["movement_status"] == "AWARDED"

        validate_error(
            api_client.cancel_shipment(
                shipment_id,
                cancel_shipment_payload(cancel_reason="NOT MY MOVE"),
                stranger_headers,
            ),
            ApiErrorId.ERR_OWNERSHIP_REQUIRED.value,
            403,
        )
        stored = read_shipment(shipment_id)
        assert stored["movement_status"] == "AWARDED"
        assert stored["cancel_reason"] is None
        assert _active_count(scenario["member"]["id"]) == 1


class TestSegregationOfDuties:
    """Neither the reviewing examiner nor the authorizing administrator may finish their own work."""

    def test_the_reviewing_examiner_is_barred_from_settling(self):
        """Examiner one reviewed the claim, so examiner two is the one who pays it out.

        "A claim is settled by a `ClaimsExaminer` or `ProgramAdmin`, but never by the examiner
        whose `X-User-ID` was recorded as `reviewed_by_user_id` when the claim was taken under
        review; an attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (403)."

        "**Settlement** moves the claim `UNDER_REVIEW → SETTLED`, may carry a
        `settlement_note`, requires that no item of the claim is still `PENDING` (otherwise
        `ERR_CLAIM_ITEM_PENDING`), requires the acting `X-User-ID` to differ from
        `reviewed_by_user_id`, and stamps `settled_by_user_id`."

        "starting from 100.00, deduct 5.00 points for each settled claim counted against the
        provider, deduct a further point for every 500.00 US dollars of cumulative settlement,
        round half up to two decimals, and floor the result at 0.00"

        Design: Corner/rbac/reviewing_examiner_cannot_settle_the_same_claim
        """
        scenario = _claim_under_review_for_one_thousand()
        claim_id = scenario["claim"]["id"]
        assert scenario["claim"]["reviewed_by_user_id"] == EXAMINER_USER_ID
        assert scenario["claim"]["status"] == "UNDER_REVIEW"

        validate_error(
            api_client.settle_claim(
                claim_id,
                settle_claim_payload(settlement_note="SELF SETTLEMENT ATTEMPT"),
                EXAMINER,
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )
        refused = read_claim(claim_id)
        assert refused["status"] == "UNDER_REVIEW"
        assert refused["settled_by_user_id"] is None
        assert refused["settlement_total_usd"] == pytest.approx(0.00, abs=0.01)

        settled = settle_claim(claim_id, settlement_note="SECOND EXAMINER SETTLES")
        assert settled["status"] == "SETTLED"
        assert settled["settled_by_user_id"] == EXAMINER_ALT_USER_ID
        assert settled["settlement_total_usd"] == pytest.approx(1000.00, abs=0.01)

        provider = read_tsp(scenario["tsp"]["id"])
        assert provider["settled_claim_count"] == 1
        assert provider["performance_score"] == pytest.approx(93.00, abs=0.01)
        assert provider["status"] == "ACTIVE"

    def test_the_authorizing_administrator_is_barred_from_waiving(self):
        """admin-01 stamped the entitlement, so only admin-02 can forgive the 3,005.10 owed.

        "Separately, an excess-cost waiver is granted by a `ProgramAdmin`, but never by the
        user whose `X-User-ID` was recorded as `authorized_by_user_id` on the entitlement being
        waived; that attempt is rejected with `ERR_WAIVER_SELF_APPROVAL` (403)."

        "Acceptance increases `excess_cost_waived_usd` by the waived amount, records the reason
        in `waiver_reason`, and reduces `excess_cost_due_usd` by the same amount;
        `gross_excess_cost_usd` is deliberately left untouched, preserving the invariant of
        §2.8."

        Design: Corner/rbac/authorizing_admin_cannot_waive_the_same_entitlement
        """
        scenario = _entitlement_authorized_by_the_program_office()
        entitlement_id = scenario["entitlement"]["id"]

        before = read_entitlement(entitlement_id)
        assert before["authorized_by_user_id"] == ADMIN_USER_ID
        assert before["status"] == "SUSPENDED"
        assert before["gross_excess_cost_usd"] == pytest.approx(3005.10, abs=0.01)
        assert before["excess_cost_due_usd"] == pytest.approx(3005.10, abs=0.01)

        validate_error(
            _waiver(entitlement_id, 3005.10, ADMIN, "SELF APPROVAL ATTEMPT"),
            ApiErrorId.ERR_WAIVER_SELF_APPROVAL.value,
            403,
        )
        refused = read_entitlement(entitlement_id)
        assert refused["excess_cost_waived_usd"] == pytest.approx(0.00, abs=0.01)
        assert refused["excess_cost_due_usd"] == pytest.approx(3005.10, abs=0.01)

        waive_excess_cost(
            entitlement_id, 3005.10, waiver_reason="COMMAND DIRECTED WAIVER"
        )
        waived = read_entitlement(entitlement_id)
        assert waived["excess_cost_waived_usd"] == pytest.approx(3005.10, abs=0.01)
        assert waived["excess_cost_due_usd"] == pytest.approx(0.00, abs=0.01)
        assert waived["gross_excess_cost_usd"] == pytest.approx(3005.10, abs=0.01)


class TestCounselorExclusiveOperations:
    """The counselor completes, authorizes, verifies and rejects, and only one of those moves weight."""

    def test_every_counselor_only_step_lands(self):
        """Completion, authorization, one verification and one rejection, in that order.

        "Verification belongs exclusively to the `MoveCounselor` and branches on one
        comparison."

        "Rejection is the counselor's other exclusive option. It moves `SUBMITTED →
        REJECTED`, stores the supplied `rejection_reason` and stamps `verified_by_user_id`,
        leaves `verified_weight_lbs` at 0, and still recomputes the shipment's
        `pro_gear_excluded_lbs` and `billable_weight_lbs` and the entitlement ledger — the
        declaration simply contributes nothing."

        Design: Corner/rbac/move_counselor_exclusive_operations_succeed
        """
        scenario = _counselor_run_through_survey()

        completed = validate_success(
            api_client.complete_counseling_session(
                scenario["session"]["id"], complete_counseling_payload(), COUNSELOR
            ),
            200,
        )
        assert completed["status"] == "COMPLETED"
        rows, meta = validate_paginated(
            api_client.list_order_entitlements(scenario["order"]["id"], COUNSELOR)
        )
        assert meta["total_count"] == 1

        scenario["entitlement"] = authorize_entitlement(rows[0]["id"])
        assert scenario["entitlement"]["status"] == "AUTHORIZED"

        scenario["tsp"] = create_tsp()
        scenario["tsp_headers"] = make_tsp_coordinator_headers(scenario["tsp"]["id"])
        scenario["shipment"] = book_shipment(scenario)
        scenario["shipment"] = survey_shipment(scenario)
        assert scenario["shipment"]["billable_weight_lbs"] == 5286

        member_gear = declare_pro_gear(
            scenario,
            owner="MEMBER",
            claimed_weight_lbs=500,
            documentation_type="ITEMIZED_INVENTORY",
        )
        spouse_gear = declare_pro_gear(
            scenario, owner="SPOUSE", claimed_weight_lbs=300, documentation_type="NONE"
        )

        verified = verify_pro_gear(member_gear["id"], 500)
        assert verified["status"] == "VERIFIED"
        assert verified["verified_weight_lbs"] == 500
        assert verified["verified_by_user_id"] == COUNSELOR_USER_ID

        rejected = validate_success(
            api_client.reject_pro_gear_declaration(
                spouse_gear["id"],
                reject_pro_gear_payload(rejection_reason="NO DOCUMENTATION SUPPLIED"),
                COUNSELOR,
            ),
            200,
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "NO DOCUMENTATION SUPPLIED"
        assert rejected["verified_weight_lbs"] == 0
        assert rejected["verified_by_user_id"] == COUNSELOR_USER_ID

        entitlement = read_entitlement(scenario["entitlement"]["id"])
        assert entitlement["pro_gear_excluded_total_lbs"] == 500
        assert entitlement["charged_billable_weight_lbs"] == 4786


class TestOptimisticConcurrency:
    """A version read before a cascade is a version that no longer buys anything."""

    def test_a_stale_entitlement_version_refuses_the_second_booking(self):
        """The survey's ledger write moved the version, so the replay must carry the new one.

        "Its value must equal the current `version` of the `EntitlementAuthorization` named by
        `entitlement_id`; if the entitlement's `version` has advanced since the client last
        read it, the booking is rejected with `ERR_STALE_ENTITLEMENT_VERSION` (HTTP 412)."

        "A member may legitimately hold several shipments against one entitlement, so nothing
        in the state machine blocks a second booking — the stale-version check is the mechanism
        that forces the client to re-read `charged_billable_weight_lbs` and
        `excess_cost_due_usd`, both of which move on every booking, before committing more
        weight to the ledger."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_entitlement_version_on_shipment_create_returns_412
        """
        scenario = setup_booked_shipment()
        entitlement_id = scenario["entitlement"]["id"]
        stale_version = scenario["entitlement"]["version"]
        scenario["shipment"] = survey_shipment(scenario)

        def _second_booking(version):
            return api_client.create_shipment(
                create_shipment_payload(
                    scenario["order"]["id"],
                    entitlement_id,
                    scenario["tsp"]["id"],
                    version,
                    shipment_code="SHP-C02",
                    **SECOND_LOT,
                ),
                COUNSELOR,
            )

        validate_error(
            _second_booking(stale_version),
            ApiErrorId.ERR_STALE_ENTITLEMENT_VERSION.value,
            412,
        )

        fresh = read_entitlement(entitlement_id)
        assert fresh["version"] != stale_version
        assert fresh["charged_billable_weight_lbs"] == 5286

        replayed = validate_success(_second_booking(fresh["version"]), 201)
        assert replayed["shipment_code"] == "SHP-C02"
        assert replayed["movement_status"] == "AWARDED"

        _, meta = validate_paginated(
            api_client.list_order_shipments(scenario["order"]["id"], COUNSELOR)
        )
        assert meta["total_count"] == 2

    def test_a_stale_block_version_refuses_the_second_award(self):
        """The first award consumed the version the coordinator was holding, not the pool.

        "Its value must equal the current `version` of the `CapacityBlock` addressed in the
        path; a mismatch is rejected with `ERR_STALE_CAPACITY_BLOCK_VERSION` (HTTP 412)."

        "Multiple shipments may legitimately be awarded into the same week, so again no state
        precondition blocks the second award; the version check forces the coordinator to
        re-read `committed_general_lbs` and `committed_short_notice_lbs` before consuming more
        of the pool."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_capacity_block_version_on_award_returns_412
        """
        scenario = _two_surveyed_lots_and_a_block()
        block_id = scenario["block"]["id"]
        stale_version = scenario["block"]["version"]
        assert scenario["shipment"]["billable_weight_lbs"] == 5286
        assert scenario["shipment_2"]["billable_weight_lbs"] == 294

        def _award(shipment_id, version):
            return api_client.create_award(
                block_id, award_payload(shipment_id, version), scenario["tsp_headers"]
            )

        validate_success(_award(scenario["shipment"]["id"], stale_version), 200)

        validate_error(
            _award(scenario["shipment_2"]["id"], stale_version),
            ApiErrorId.ERR_STALE_CAPACITY_BLOCK_VERSION.value,
            412,
        )

        midway = read_capacity_block(block_id)
        assert midway["general_pool_lbs"] == 9000
        assert midway["committed_lbs"] == 5286
        assert midway["version"] != stale_version

        awarded = validate_success(
            _award(scenario["shipment_2"]["id"], midway["version"]), 200
        )
        assert awarded["capacity_block_id"] == block_id

        after = read_capacity_block(block_id)
        assert after["committed_lbs"] == 5580
        assert after["committed_general_lbs"] == 5580

    def test_the_active_shipment_counter_follows_every_exit_state(self):
        """Two lots, one cancelled and one delivered, leave the counter back at zero.

        "The member's `active_shipment_count` starts at 0; the system maintains it as the count
        of that member's shipments whose `movement_status` is neither `DELIVERED` nor
        `CANCELLED`, incrementing it when a shipment is booked and decrementing it when one is
        cancelled."

        "Cancellation also decrements the member's `active_shipment_count`."

        Design: Corner/cross_cutting_complexity_layers/active_shipment_count_reconciles_after_create_and_cancel_and_deliver
        """
        scenario = setup_booked_shipment()
        member_id = scenario["member"]["id"]
        assert scenario["member"]["active_shipment_count"] == 0

        second = setup_second_shipment(scenario, shipment_code="SHP-C02", **SECOND_LOT)
        assert _active_count(member_id) == 2

        cancelled = validate_success(
            api_client.cancel_shipment(
                second["id"],
                cancel_shipment_payload(cancel_reason="CONSOLIDATED INTO ONE SHIPMENT"),
                COUNSELOR,
            ),
            200,
        )
        assert cancelled["movement_status"] == "CANCELLED"
        assert _active_count(member_id) == 1

        scenario["shipment"] = survey_shipment(scenario)
        scenario["block"] = create_capacity_block(scenario["tsp"]["id"])
        award_shipment(scenario["block"]["id"], scenario["shipment"]["id"])
        pack_shipment(scenario)
        record_actual_weight(scenario, 6200, 1500, weigh_date=WEIGH_DATE)
        picked_up = pickup_shipment(scenario)
        assert picked_up["movement_status"] == "PICKED_UP"
        assert _active_count(member_id) == 1

        delivered = deliver_shipment(scenario)
        assert delivered["movement_status"] == "DELIVERED"
        assert _active_count(member_id) == 0

        _, meta = validate_paginated(
            api_client.list_order_shipments(scenario["order"]["id"], COUNSELOR)
        )
        assert meta["total_count"] == 2

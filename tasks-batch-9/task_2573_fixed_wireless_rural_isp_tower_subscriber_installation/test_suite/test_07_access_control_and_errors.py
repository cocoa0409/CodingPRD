"""Access control, the two-person controls, and the refusals that guard reads.

Concerns covered here:

* the exclusive operation of each operator role, closed to every other role;
* the one endpoint `SalesAgent` and `CapacityPlanner` genuinely share;
* what a `Subscriber` may and may not address;
* the two segregation-of-duties gates, on mounting exceptions and on money;
* the thirteen distinct 404 codes, one per addressable family;
* the not-affected refusal on a credit for another tower's outage;
* pagination bounds, which are checked before any row is read.
"""

import pytest

from test_helpers import (
    BILLING_ADMIN,
    CAPACITY_PLANNER,
    CREDIT_APPROVER_USER_ID,
    CREDIT_PREPARER_USER_ID,
    DECIDING_ENGINEER_USER_ID,
    FIELD_TECH,
    FINANCE_APPROVER,
    NETWORK_ENGINEER,
    NON_EXISTENT_UUID,
    SALES_AGENT,
    SURVEYOR_USER_ID,
    ApiErrorId,
    assert_capacity_hold,
    assert_install_work_order,
    assert_no_mutation,
    assert_outage_credit,
    assert_subscriber,
    assert_version_advanced_by,
    change_tower_status,
    close_outage,
    create_accepted_circuit,
    create_outage,
    create_outage_credit_payload,
    create_service_plan_payload,
    create_serviceability_request,
    create_subscriber,
    create_tower,
    create_tower_payload,
    get_capacity_hold,
    get_credit,
    get_outage,
    get_sector,
    get_serviceability_request,
    get_subscriber,
    get_work_order,
    hold_for_request,
    make_field_tech_headers,
    make_finance_approver_headers,
    make_network_engineer_headers,
    make_subscriber_headers,
    set_clock,
    setup_active_plant,
    setup_active_subscriber,
    setup_pending_install_subscriber,
    setup_prepared_credit,
    setup_qualified_request,
    setup_work_order_in_state,
    survey_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------
# Local composite setups, built from the Tier-0 helpers only.
# --------------------------------------------------------------------------


def _setup_two_accounts_on_one_sector():
    """Two accounts sold on the same sector, so one account's identifier is a
    valid target that simply belongs to somebody else."""
    scenario = setup_pending_install_subscriber()
    request_b = create_serviceability_request(
        scenario["tower"]["id"], scenario["plan"]["id"], contact_name="Morgan Vale"
    )
    hold_for_request(request_b["id"])
    scenario["subscriber_b"] = create_subscriber(
        request_b["id"], scenario["plan"]["id"], billing_email="morgan.vale@example.com"
    )
    scenario["request_b"] = request_b
    return scenario


def _setup_account_and_a_second_towers_outage():
    """An ACTIVE account on tower A, and one closed 1269-minute `POWER` outage on
    each of two towers, so the account is affected by exactly one of them."""
    scenario = setup_active_subscriber()
    other_tower = create_tower(latitude=41.4, longitude=-104.5)
    create_accepted_circuit(other_tower["id"])
    scenario["other_tower"] = change_tower_status(other_tower["id"], "ACTIVE")

    set_clock("2026-08-06T00:00:00Z")
    own = create_outage(
        scenario["tower"]["id"], cause="POWER", started_at="2026-08-05T00:00:00Z"
    )
    scenario["own_outage"] = close_outage(own["id"], ended_at="2026-08-05T21:09:00Z")
    other = create_outage(other_tower["id"], cause="POWER", started_at="2026-08-05T00:00:00Z")
    scenario["other_outage"] = close_outage(other["id"], ended_at="2026-08-05T21:09:00Z")
    return scenario


# --------------------------------------------------------------------------
# Each role's exclusive operation
# --------------------------------------------------------------------------

_EXCLUSIVE_OPERATIONS = [
    ("POST /towers", "create_tower", SALES_AGENT),
    ("POST /service-plans", "create_service_plan", FIELD_TECH),
    ("POST /sectors/{id}/capacity-policy", "change_capacity_policy", NETWORK_ENGINEER),
    ("POST /install-work-orders/{id}/survey", "survey_work_order", CAPACITY_PLANNER),
    ("POST /install-work-orders/{id}/exception-decision", "decide_exception", FIELD_TECH),
    ("POST /outage-credits", "create_outage_credit", FINANCE_APPROVER),
    ("POST /outage-credits/{id}/application", "apply_outage_credit", BILLING_ADMIN),
    ("POST /subscribers/{id}/status-changes", "change_subscriber_status", SALES_AGENT),
]


def _call_exclusive_operation(api, method_name, headers):
    """Address one role-exclusive write with a role that does not own it. Path and
    body identifiers are deliberately non-existent: role membership is checked
    before any identifier is resolved."""
    if method_name == "create_tower":
        return api.create_tower(create_tower_payload(), headers)
    if method_name == "create_service_plan":
        return api.create_service_plan(create_service_plan_payload(), headers)
    if method_name == "change_capacity_policy":
        return api.change_capacity_policy(
            NON_EXISTENT_UUID,
            {"max_oversubscription_ratio": 4.0, "justification": "Retune"},
            headers,
        )
    if method_name == "survey_work_order":
        return api.survey_work_order(NON_EXISTENT_UUID, survey_payload(), headers)
    if method_name == "decide_exception":
        return api.decide_exception(
            NON_EXISTENT_UUID,
            {"decision": "APPROVE", "note": "Looks fine", "approved_mounting_type": "ROOF_MAST_GUYED"},
            headers,
        )
    if method_name == "create_outage_credit":
        return api.create_outage_credit(
            create_outage_credit_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID), headers
        )
    if method_name == "apply_outage_credit":
        return api.apply_outage_credit(NON_EXISTENT_UUID, {}, headers)
    if method_name == "change_subscriber_status":
        return api.change_subscriber_status(
            NON_EXISTENT_UUID, {"to_status": "SUSPENDED", "reason": "Non-payment"}, headers
        )
    raise AssertionError(f"unhandled operation {method_name}")


class TestRoleExclusiveOperations:
    @pytest.mark.parametrize(
        "endpoint,method_name,headers",
        _EXCLUSIVE_OPERATIONS,
        ids=[case[0] for case in _EXCLUSIVE_OPERATIONS],
    )
    def test_an_exclusive_write_refuses_a_role_outside_its_permitted_set(
        self, api, endpoint, method_name, headers
    ):
        """PRD 2.1: "Authorization is per endpoint."
        PRD 2.1: "A caller whose headers are well formed but whose role is not in that set
        is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Role membership is checked before the
        path identifiers are resolved, so an unauthorized caller likewise cannot probe for
        existence."
        PRD 2.7: "**Authorization** — the acting role appears in the called endpoint's
        permitted set, else `ERR_UNAUTHORIZED` (403). Applies to every endpoint."

        Design: Corner/rbac/each_roles_exclusive_operation_is_closed_to_every_other_role
        """
        response = _call_exclusive_operation(api, method_name, headers)

        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

    @pytest.mark.parametrize(
        "label,headers",
        [
            ("no headers at all", {}),
            ("role header missing", {"X-User-ID": "ops-1001"}),
            ("id header missing", {"X-User-Role": "NetworkEngineer"}),
            ("role not one of the seven", {"X-User-ID": "ops-1001", "X-User-Role": "Auditor"}),
        ],
    )
    def test_a_caller_without_usable_headers_learns_nothing_about_existence(
        self, api, label, headers
    ):
        """PRD 2.1: "Every request to this API must carry two headers."
        PRD 2.1: "If either header is absent, or if the value of `X-User-Role` is not one of
        the seven role names declared below, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD 2.1: "Header validation happens before anything else: an unauthenticated caller
        never learns whether the resource they addressed exists."

        Design: Corner/rbac/each_roles_exclusive_operation_is_closed_to_every_other_role
        """
        tower = create_tower()

        validate_error(api.get_tower(tower["id"], headers), ApiErrorId.ERR_UNAUTHENTICATED)
        validate_error(
            api.get_tower(NON_EXISTENT_UUID, headers), ApiErrorId.ERR_UNAUTHENTICATED
        )
        validate_error(
            api.create_tower(create_tower_payload(), headers), ApiErrorId.ERR_UNAUTHENTICATED
        )

    def test_the_owner_of_an_exclusive_operation_still_gets_through_and_shared_reads_stay_open(
        self, api, network_engineer, sales_agent, capacity_planner
    ):
        """PRD 2.1: "Authorization is per endpoint."
        PRD 4: "Register a tower site with its ground-lease terms."
        PRD 4: "Read one tower with its derived lease, sector and backhaul roll-ups."
        PRD 2.7: "**Path existence** — every identifier in the path resolves, left to right,
        else the matching 404 of §2.6."

        Design: Corner/rbac/each_roles_exclusive_operation_is_closed_to_every_other_role
        """
        created = validate_success(
            api.create_tower(create_tower_payload(), network_engineer), 201
        )
        validate_success(api.create_service_plan(create_service_plan_payload(), capacity_planner), 201)

        shared_read = validate_success(api.get_tower(created["id"], sales_agent), 200)
        assert shared_read["id"] == created["id"], (
            "the tower read is open to all six operator roles"
        )

        validate_error(
            api.get_tower(NON_EXISTENT_UUID, sales_agent), ApiErrorId.ERR_TOWER_NOT_FOUND
        )


# --------------------------------------------------------------------------
# The one endpoint sales and capacity share
# --------------------------------------------------------------------------


class TestSharedReservationEndpoint:
    def test_both_sales_and_capacity_may_reserve_but_only_capacity_may_release(
        self, api, sales_agent, capacity_planner
    ):
        """PRD 2.1: "**`CapacityPlanner`** — owns oversubscription policy. Publishes service
        plans, changes a sector's oversubscription ceiling, reserves sector bandwidth, and is
        the only role that may hand a reservation back."
        PRD 3.6: "Between qualifying a premise and signing the household up, a `SalesAgent`
        or a `CapacityPlanner` takes out a capacity reservation so that the sector's
        allowance cannot be sold twice."
        PRD 3.6: "A `CapacityPlanner`, and only a `CapacityPlanner`, may hand bandwidth back
        manually, optionally recording a `note`."
        PRD 3.6: "A manual release moves the reservation `HELD → RELEASED` with a
        `release_reason` of `MANUAL`."
        PRD 3.6: "The sector's `held_mbps` falls by the reservation's `held_mbps`,
        `committed_mbps`, `oversubscription_ratio`, `remaining_allowance_mbps` and
        `capacity_posture` are recomputed, the sector's `version` is incremented, and the
        enquiry the reservation was protecting, if still `QUALIFIED`, moves to `EXPIRED` with
        its `qualified_sector_id` cleared."

        Design: Corner/rbac/sales_and_capacity_share_the_reservation_endpoint_but_not_each_others_exclusives
        """
        scenario = setup_active_plant()
        request_a = create_serviceability_request(
            scenario["tower"]["id"], scenario["plan"]["id"]
        )
        request_b = create_serviceability_request(
            scenario["tower"]["id"], scenario["plan"]["id"], contact_name="Morgan Vale"
        )

        sector_now = get_sector(scenario["sector"]["id"])
        hold_a = validate_success(
            api.create_capacity_hold(
                {
                    "serviceability_request_id": request_a["id"],
                    "expected_sector_version": sector_now["version"],
                },
                capacity_planner,
            ),
            201,
        )
        assert_capacity_hold(hold_a)
        assert hold_a["status"] == "HELD"

        sector_now = get_sector(scenario["sector"]["id"])
        hold_b = validate_success(
            api.create_capacity_hold(
                {
                    "serviceability_request_id": request_b["id"],
                    "expected_sector_version": sector_now["version"],
                },
                sales_agent,
            ),
            201,
        )
        assert hold_b["status"] == "HELD", (
            "both roles reach the same reservation endpoint, got "
            f"{hold_b['status']}"
        )

        validate_error(
            api.release_capacity_hold(hold_b["id"], {"note": "Customer went elsewhere"}, sales_agent),
            ApiErrorId.ERR_UNAUTHORIZED,
        )
        assert_no_mutation(hold_b, get_capacity_hold(hold_b["id"]), "capacity reservation")

        released = validate_success(
            api.release_capacity_hold(
                hold_b["id"], {"note": "Customer went elsewhere"}, capacity_planner
            ),
            200,
        )
        assert released["status"] == "RELEASED", f"got {released['status']}"
        assert released["release_reason"] == "MANUAL", (
            f"got release_reason {released.get('release_reason')!r}"
        )
        assert get_serviceability_request(request_b["id"])["status"] == "EXPIRED"
        assert get_capacity_hold(hold_a["id"])["status"] == "HELD", (
            "the other reservation is untouched"
        )

    def test_only_sales_may_open_the_account_and_the_reservation_survives_the_refusal(
        self, api, sales_agent, capacity_planner
    ):
        """PRD 3.6: "A `SalesAgent` converts a reserved qualification into a subscription by
        naming the `serviceability_request_id`, the `service_plan_id` being bought, a
        `billing_email` for invoices, and an `equipment_mode` of either `RENTAL` or
        `PURCHASE`."
        PRD 2.1: "**`SalesAgent`** — qualifies premises against a candidate tower, reserves
        sector bandwidth, converts a qualified premise into an account, changes an account's
        plan, and schedules the first truck roll."
        PRD 3.6: "The reservation moves `HELD → CONSUMED`."

        Design: Corner/rbac/sales_and_capacity_share_the_reservation_endpoint_but_not_each_others_exclusives
        """
        scenario = setup_qualified_request()
        request = scenario["request"]
        hold = hold_for_request(request["id"], headers=capacity_planner)
        payload = {
            "serviceability_request_id": request["id"],
            "service_plan_id": scenario["plan"]["id"],
            "billing_email": "dana.reyes@example.com",
            "equipment_mode": "RENTAL",
        }

        validate_error(
            api.create_subscriber(payload, capacity_planner), ApiErrorId.ERR_UNAUTHORIZED
        )
        assert get_serviceability_request(request["id"])["status"] == "QUALIFIED", (
            "the refused conversion leaves the enquiry claimable"
        )
        assert_no_mutation(hold, get_capacity_hold(hold["id"]), "capacity reservation")

        subscriber = validate_success(api.create_subscriber(payload, sales_agent), 201)
        assert_subscriber(subscriber)
        assert subscriber["service_status"] == "PENDING_INSTALL"
        assert get_capacity_hold(hold["id"])["status"] == "CONSUMED", (
            "the reservation the planner took out is the one the agent consumes"
        )


# --------------------------------------------------------------------------
# What a Subscriber may address
# --------------------------------------------------------------------------


class TestSubscriberScope:
    def test_a_subscriber_reads_its_own_account_and_its_own_sub_resources(self, api):
        """PRD 2.1: "The `Subscriber` role is different: when `X-User-Role` is `Subscriber`,
        `X-User-ID` is the `id` of the acting subscriber account, and ownership checks compare
        the addressed account's `id` (or, for a listing, the account referenced by the
        resource) against `X-User-ID`."
        PRD 2.1: "A caller in the `Subscriber` role may read their own account, their own
        metered usage days, their own install work orders, their own equipment assignments,
        and the service-level credit list; addressing any of those against another account's
        identifier is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD 2.1: "The credit list, when requested by a `Subscriber`, must be scoped to that
        subscriber's own credits."

        Design: Corner/rbac/a_subscriber_reads_its_own_account_only_and_has_no_collection_read_at_all
        """
        scenario = _setup_two_accounts_on_one_sector()
        own = scenario["subscriber"]
        own_headers = make_subscriber_headers(own["id"])

        data = validate_success(api.get_subscriber(own["id"], own_headers), 200)
        assert_subscriber(data)
        assert data["id"] == own["id"]
        assert data["account_number"] == own["account_number"]

        _, work_order_meta = validate_paginated(
            api.list_subscriber_work_orders(own["id"], own_headers)
        )
        assert work_order_meta["total_count"] == 0, (
            f"no truck roll has been booked yet, got {work_order_meta['total_count']}"
        )

        assignments, assignment_meta = validate_paginated(
            api.list_subscriber_equipment(own["id"], own_headers)
        )
        assert assignment_meta["total_count"] == 1, (
            "the account's own equipment record is visible to it, got "
            f"{assignment_meta['total_count']}"
        )
        assert assignments[0]["subscriber_id"] == own["id"]

        _, usage_meta = validate_paginated(api.list_usage_records(own["id"], own_headers))
        assert usage_meta["total_count"] == 0

        _, credit_meta = validate_paginated(api.list_outage_credits(own_headers))
        assert credit_meta["total_count"] == 0, (
            "the credit list is open to a Subscriber but scoped to its own credits, got "
            f"{credit_meta['total_count']}"
        )

    @pytest.mark.parametrize(
        "method_name",
        [
            "get_subscriber",
            "list_usage_records",
            "list_subscriber_work_orders",
            "list_subscriber_equipment",
        ],
    )
    def test_a_subscriber_addressing_another_account_is_refused_as_not_the_owner(
        self, api, method_name
    ):
        """PRD 2.1: "A caller in the `Subscriber` role may read their own account, their own
        metered usage days, their own install work orders, their own equipment assignments,
        and the service-level credit list; addressing any of those against another account's
        identifier is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD 2.7: "**Ownership** — a caller in the `Subscriber` role addresses only their own
        account's resources, else `ERR_NOT_RESOURCE_OWNER` (403)."

        Design: Corner/rbac/a_subscriber_reads_its_own_account_only_and_has_no_collection_read_at_all
        """
        scenario = _setup_two_accounts_on_one_sector()
        own_headers = make_subscriber_headers(scenario["subscriber"]["id"])
        other_id = scenario["subscriber_b"]["id"]

        response = getattr(api, method_name)(other_id, own_headers)

        validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    def test_a_subscriber_has_no_account_collection_read_and_cannot_probe_for_accounts(
        self, api, billing_admin
    ):
        """PRD 4: "List accounts by sector, qualification, plan, service status or usage
        priority."
        PRD 2.1: "A caller whose headers are well formed but whose role is not in that set is
        rejected with `ERR_UNAUTHORIZED` (HTTP 403). Role membership is checked before the
        path identifiers are resolved, so an unauthorized caller likewise cannot probe for
        existence."
        PRD 2.7: "**Path existence** — every identifier in the path resolves, left to right,
        else the matching 404 of §2.6."
        PRD 2.7: "**Ownership** — a caller in the `Subscriber` role addresses only their own
        account's resources, else `ERR_NOT_RESOURCE_OWNER` (403)."

        Design: Corner/rbac/a_subscriber_reads_its_own_account_only_and_has_no_collection_read_at_all
        """
        scenario = _setup_two_accounts_on_one_sector()
        own_headers = make_subscriber_headers(scenario["subscriber"]["id"])

        validate_error(api.list_subscribers(own_headers), ApiErrorId.ERR_UNAUTHORIZED)

        validate_error(
            api.get_subscriber(NON_EXISTENT_UUID, own_headers),
            ApiErrorId.ERR_SUBSCRIBER_NOT_FOUND,
        )

        _, meta = validate_paginated(api.list_subscribers(billing_admin))
        assert meta["total_count"] == 2, (
            "the collection read exists for the operator roles that own it, got "
            f"{meta['total_count']}"
        )


# --------------------------------------------------------------------------
# Two-person control on tall-mast mounting
# --------------------------------------------------------------------------


class TestMountingExceptionSegregationOfDuties:
    def test_the_surveying_technician_may_not_decide_the_exception(self, api):
        """PRD 2.11: "The `FieldTech` whose `X-User-ID` was recorded as
        `surveyed_by_user_id` when the on-site survey was filed may not be the
        `NetworkEngineer` who decides the resulting mounting exception."
        PRD 2.11: "If the acting `X-User-ID` on the exception decision equals
        `surveyed_by_user_id`, the decision is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP
        403). The rule applies to all three exception outcomes — approval, a demand for a
        resurvey, and rejection — not only to approval."
        PRD 2.11: "Note that the two controls sit on different role pairs, and that neither
        is a role check: a `NetworkEngineer` is always permitted to decide exceptions and a
        `FinanceApprover` is always permitted to apply credits."
        PRD 3.7: "**Approve** moves the work order `EXCEPTION_PENDING → MOUNT_APPROVED` and
        records `exception_approved_by_user_id`. The `approved_mounting_type` is taken from
        the body when supplied and defaults to `recommended_mounting_type` when omitted."

        Design: Corner/rbac/the_engineer_who_approves_a_mounting_exception_cannot_be_the_tech_who_surveyed
        """
        scenario = setup_work_order_in_state("EXCEPTION_PENDING")
        before = scenario["work_order"]
        assert before["status"] == "EXCEPTION_PENDING"
        assert before["surveyed_by_user_id"] == SURVEYOR_USER_ID
        assert before.get("approved_mounting_type") is None

        for decision in ("APPROVE", "REQUEST_RESURVEY", "REJECT"):
            validate_error(
                api.decide_exception(
                    before["id"],
                    {"decision": decision, "note": "Reviewed my own survey"},
                    make_network_engineer_headers(SURVEYOR_USER_ID),
                ),
                ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            )
            unchanged = get_work_order(before["id"])
            assert_no_mutation(before, unchanged, "work order")
            assert unchanged.get("exception_approved_by_user_id") is None
            assert unchanged.get("approved_mounting_type") is None

        after = validate_success(
            api.decide_exception(
                before["id"],
                {"decision": "APPROVE", "note": "Guyed mast acceptable on this roof"},
                make_network_engineer_headers(DECIDING_ENGINEER_USER_ID),
            ),
            200,
        )
        assert_install_work_order(after)
        assert after["status"] == "MOUNT_APPROVED", f"got {after['status']}"
        assert after["approved_mounting_type"] == "ROOF_MAST_GUYED", (
            "the band defaults to the recommended one, got "
            f"{after.get('approved_mounting_type')!r}"
        )
        assert after["exception_approved_by_user_id"] == DECIDING_ENGINEER_USER_ID
        assert_version_advanced_by(before, after, 1, "work order")

    def test_the_surveying_technician_may_still_complete_the_install_after_approval(self, api):
        """PRD 2.11: "Note that the two controls sit on different role pairs, and that
        neither is a role check: a `NetworkEngineer` is always permitted to decide exceptions
        and a `FinanceApprover` is always permitted to apply credits."
        PRD 3.7: "Begin with a labour charge selected by `approved_mounting_type`: 4900 cents
        for a `WALL_BRACKET`, 9900 for a `NON_PEN_ROOF_TRIPOD`, 19900 for a `ROOF_MAST_GUYED`,
        and 34900 for a `GROUND_POLE_MAST`."
        PRD 3.7: "Add a mast kit charge of 1750 cents per half-metre section, where the
        number of sections is `installed_mast_height_m` divided by 0.5 and rounded
        **upward** to a whole number — a 2.6 metre mast bills six sections."
        PRD 3.7: "Add the fixed trip charge of 9900 cents. The sum of trip charge, labour and
        mast kit is the subtotal."
        PRD 3.7: "A volume discount is then read off the **subtotal only**, with inclusive
        lower bounds: a subtotal at or above 30000 cents earns 5000 cents off, at or above
        20000 earns 3000, at or above 10000 earns 1000, and anything below 10000 earns
        nothing. The net amount is the subtotal less that discount. A regulatory
        cost-recovery fee of 3.25 percent is then applied to the **net** amount and rounded
        half up to whole cents, and `install_invoice_total_cents` is the net amount plus that
        fee."

        Design: Corner/rbac/the_engineer_who_approves_a_mounting_exception_cannot_be_the_tech_who_surveyed
        """
        scenario = setup_work_order_in_state("EXCEPTION_PENDING")
        work_order_id = scenario["work_order"]["id"]
        validate_success(
            api.decide_exception(
                work_order_id,
                {"decision": "APPROVE", "note": "Guyed mast acceptable on this roof"},
                make_network_engineer_headers(DECIDING_ENGINEER_USER_ID),
            ),
            200,
        )

        completed = validate_success(
            api.complete_work_order(
                work_order_id,
                {"installed_mast_height_m": 5.0, "radio_serial": "CPE-SN-900001"},
                make_field_tech_headers(SURVEYOR_USER_ID),
            ),
            200,
        )

        assert_install_work_order(completed)
        assert completed["status"] == "INSTALLED", (
            "the control governs the exception decision, not the completion, got "
            f"{completed['status']}"
        )
        assert completed["install_invoice_total_cents"] == 43675, (
            "19900 labour plus 17500 for ten half-metre sections plus 9900 trip is 47300, "
            "less the 5000 volume discount is 42300, plus a 1375-cent regulatory fee, got "
            f"{completed['install_invoice_total_cents']}"
        )
        assert get_subscriber(scenario["subscriber"]["id"])["service_status"] == "ACTIVE"


# --------------------------------------------------------------------------
# Two-person control on money
# --------------------------------------------------------------------------


class TestCreditSegregationOfDuties:
    def test_the_preparer_may_not_apply_the_credit_they_prepared(self, api):
        """PRD 2.11: "The `BillingAdmin` whose `X-User-ID` was recorded as
        `prepared_by_user_id` when a service-level credit was prepared may not be the
        `FinanceApprover` who applies it."
        PRD 2.11: "If the acting `X-User-ID` on the application equals `prepared_by_user_id`,
        the application is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD 3.9: "The credit must be in `PENDING` status; one in `APPLIED`, `DENIED` or
        `REVERSED` is refused with `ERR_CREDIT_NOT_PENDING`."
        PRD 3.9: "On success the credit moves `PENDING → APPLIED`, `approved_by_user_id` is
        stamped, the account's `credit_balance_cents` rises by `credit_cents`, and the
        outage's `total_credited_cents` rises by the same amount."

        Design: Corner/rbac/the_finance_user_who_applies_a_credit_cannot_be_the_one_who_prepared_it
        """
        scenario = setup_prepared_credit(minutes=1269, started_at="2026-08-05T00:00:00Z")
        credit = scenario["credit"]
        assert_outage_credit(credit)
        assert credit["status"] == "PENDING"
        assert credit["prepared_by_user_id"] == CREDIT_PREPARER_USER_ID
        assert credit["credit_cents"] == 1706, (
            "a 1269-minute outage against a 99.5 percent promise on a 6999-cent plan, got "
            f"{credit['credit_cents']}"
        )

        validate_error(
            api.apply_outage_credit(
                credit["id"],
                {"note": "Approving my own preparation"},
                make_finance_approver_headers(CREDIT_PREPARER_USER_ID),
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
        )

        unchanged = get_credit(credit["id"])
        assert_no_mutation(credit, unchanged, "credit")
        assert unchanged["status"] == "PENDING"
        assert unchanged.get("approved_by_user_id") is None
        assert get_subscriber(scenario["subscriber"]["id"])["credit_balance_cents"] == 0, (
            "no money moved on the refused application"
        )
        assert get_outage(scenario["outage"]["id"])["total_credited_cents"] == 0

        applied = validate_success(
            api.apply_outage_credit(
                credit["id"],
                {"note": "Second pair of eyes"},
                make_finance_approver_headers(CREDIT_APPROVER_USER_ID),
            ),
            200,
        )
        assert applied["status"] == "APPLIED", f"got {applied['status']}"
        assert applied["approved_by_user_id"] == CREDIT_APPROVER_USER_ID
        assert_version_advanced_by(credit, applied, 1, "credit")
        assert get_subscriber(scenario["subscriber"]["id"])["credit_balance_cents"] == 1706
        assert get_outage(scenario["outage"]["id"])["total_credited_cents"] == 1706

    def test_the_approver_who_applied_the_credit_may_also_reverse_it(self, api):
        """PRD 3.9: "A `FinanceApprover` may reverse an applied credit, supplying a mandatory
        `reversal_reason`."
        PRD 3.9: "The credit must be in `APPLIED` status, else `ERR_CREDIT_NOT_APPLIED`."
        PRD 3.9: "On success it moves `APPLIED → REVERSED`, which is terminal, and both
        roll-ups are decreased by `credit_cents`."
        PRD 2.11: "Note that the two controls sit on different role pairs, and that neither
        is a role check: a `NetworkEngineer` is always permitted to decide exceptions and a
        `FinanceApprover` is always permitted to apply credits."

        Design: Corner/rbac/the_finance_user_who_applies_a_credit_cannot_be_the_one_who_prepared_it
        """
        scenario = setup_prepared_credit(minutes=1269, started_at="2026-08-05T00:00:00Z")
        credit = scenario["credit"]
        applied = validate_success(
            api.apply_outage_credit(
                credit["id"], {}, make_finance_approver_headers(CREDIT_APPROVER_USER_ID)
            ),
            200,
        )
        assert applied["status"] == "APPLIED"

        reversed_credit = validate_success(
            api.reverse_outage_credit(
                credit["id"],
                {"reversal_reason": "Duplicate of an earlier goodwill credit"},
                make_finance_approver_headers(CREDIT_APPROVER_USER_ID),
            ),
            200,
        )

        assert reversed_credit["status"] == "REVERSED", f"got {reversed_credit['status']}"
        assert reversed_credit["credit_cents"] == 1706, (
            "the amount is preserved on the record even though the money is unwound"
        )
        assert get_subscriber(scenario["subscriber"]["id"])["credit_balance_cents"] == 0, (
            "both roll-ups are decreased by credit_cents"
        )
        assert get_outage(scenario["outage"]["id"])["total_credited_cents"] == 0

        validate_error(
            api.reverse_outage_credit(
                credit["id"],
                {"reversal_reason": "Again"},
                make_finance_approver_headers(CREDIT_APPROVER_USER_ID),
            ),
            ApiErrorId.ERR_CREDIT_NOT_APPLIED,
        )


# --------------------------------------------------------------------------
# Thirteen families, thirteen 404 codes
# --------------------------------------------------------------------------

_NOT_FOUND_PROBES = [
    ("tower", "get_tower", NETWORK_ENGINEER, ApiErrorId.ERR_TOWER_NOT_FOUND),
    ("circuit", "get_backhaul_circuit", NETWORK_ENGINEER, ApiErrorId.ERR_CIRCUIT_NOT_FOUND),
    ("licence", "get_spectrum_license", NETWORK_ENGINEER, ApiErrorId.ERR_LICENSE_NOT_FOUND),
    ("sector", "get_sector", CAPACITY_PLANNER, ApiErrorId.ERR_SECTOR_NOT_FOUND),
    ("coordination", "get_coordination", NETWORK_ENGINEER, ApiErrorId.ERR_COORDINATION_NOT_FOUND),
    ("plan", "get_service_plan", SALES_AGENT, ApiErrorId.ERR_PLAN_NOT_FOUND),
    (
        "qualification",
        "get_serviceability_request",
        SALES_AGENT,
        ApiErrorId.ERR_REQUEST_NOT_FOUND,
    ),
    ("hold", "get_capacity_hold", SALES_AGENT, ApiErrorId.ERR_HOLD_NOT_FOUND),
    ("account", "get_subscriber", BILLING_ADMIN, ApiErrorId.ERR_SUBSCRIBER_NOT_FOUND),
    ("work order", "get_work_order", FIELD_TECH, ApiErrorId.ERR_WORK_ORDER_NOT_FOUND),
    (
        "equipment assignment",
        "get_equipment_assignment",
        FIELD_TECH,
        ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND,
    ),
    ("outage", "get_outage_event", NETWORK_ENGINEER, ApiErrorId.ERR_OUTAGE_NOT_FOUND),
    ("credit", "get_outage_credit", BILLING_ADMIN, ApiErrorId.ERR_CREDIT_NOT_FOUND),
]


class TestNotFoundCodesPerFamily:
    @pytest.mark.parametrize(
        "family,method_name,headers,expected_error",
        _NOT_FOUND_PROBES,
        ids=[case[0] for case in _NOT_FOUND_PROBES],
    )
    def test_each_family_names_its_own_not_found_code(
        self, api, family, method_name, headers, expected_error
    ):
        """PRD 2.6: "Identifiers in a URL path are resolved strictly left to right, and the
        first identifier that resolves to nothing decides the error. The 404 code is the one
        belonging to the segment that failed: a missing tower yields `ERR_TOWER_NOT_FOUND`, a
        missing transport circuit `ERR_CIRCUIT_NOT_FOUND`, a missing spectrum licence
        `ERR_LICENSE_NOT_FOUND`, a missing sector `ERR_SECTOR_NOT_FOUND`, a missing
        coordination record `ERR_COORDINATION_NOT_FOUND`, a missing service plan
        `ERR_PLAN_NOT_FOUND`, a missing qualification `ERR_REQUEST_NOT_FOUND`, a missing
        capacity reservation `ERR_HOLD_NOT_FOUND`, a missing account
        `ERR_SUBSCRIBER_NOT_FOUND`, a missing install work order
        `ERR_WORK_ORDER_NOT_FOUND`, a missing equipment assignment
        `ERR_ASSIGNMENT_NOT_FOUND`, a missing outage record `ERR_OUTAGE_NOT_FOUND`, and a
        missing service-level credit `ERR_CREDIT_NOT_FOUND`."
        PRD 2.7: "**Path existence** — every identifier in the path resolves, left to right,
        else the matching 404 of §2.6."

        Design: Corner/errors/every_addressable_resource_family_returns_its_own_not_found_code
        """
        create_tower(site_code="RB-TWR-001")

        response = getattr(api, method_name)(NON_EXISTENT_UUID, headers)

        validate_error(response, expected_error)

    def test_a_sub_resource_under_a_missing_tower_reports_the_tower_code(self, api):
        """PRD 2.6: "So a request addressing a sub-resource under a tower that does not exist
        reports `ERR_TOWER_NOT_FOUND` and never looks for the sub-resource."
        PRD 2.7: "**Path existence** — every identifier in the path resolves, left to right,
        else the matching 404 of §2.6."

        Design: Corner/errors/every_addressable_resource_family_returns_its_own_not_found_code
        """
        real_tower = create_tower(site_code="RB-TWR-001")

        validate_error(
            api.list_tower_backhaul_circuits(NON_EXISTENT_UUID, NETWORK_ENGINEER),
            ApiErrorId.ERR_TOWER_NOT_FOUND,
        )
        validate_error(
            api.list_tower_outage_events(NON_EXISTENT_UUID, NETWORK_ENGINEER),
            ApiErrorId.ERR_TOWER_NOT_FOUND,
        )

        _, meta = validate_paginated(
            api.list_tower_backhaul_circuits(real_tower["id"], NETWORK_ENGINEER)
        )
        assert meta["total_count"] == 0, (
            "the real tower resolves and simply has no circuits yet, got "
            f"{meta['total_count']}"
        )


# --------------------------------------------------------------------------
# A credit only for the site that actually went down
# --------------------------------------------------------------------------


class TestCreditRequiresAnAffectedAccount:
    def test_a_credit_for_another_towers_outage_is_refused_as_not_affected(self, api):
        """PRD 3.9: "The household must actually be served from the affected site: the tower
        of the account's `sector_id` must be the outage's `tower_id`, else the request is
        refused with `ERR_SUBSCRIBER_NOT_AFFECTED`."
        PRD 2.7: "**Referential compatibility** — coordination is between sectors on different
        towers (`ERR_SAME_TOWER_COORDINATION`, 422), the plan permits the chosen equipment
        acquisition mode and matches the qualified plan (`ERR_PLAN_MISMATCH`, 422), the
        credited account is served from the tower that went down
        (`ERR_SUBSCRIBER_NOT_AFFECTED`, 422), and the account has no install work order
        already open (`ERR_WORK_ORDER_ALREADY_OPEN`, 409)."

        Design: Corner/errors/a_credit_for_another_towers_outage_is_refused_as_not_affected
        """
        scenario = _setup_account_and_a_second_towers_outage()
        subscriber_id = scenario["subscriber"]["id"]
        other_outage = scenario["other_outage"]
        assert other_outage["status"] == "CLOSED"
        assert other_outage["duration_minutes"] == 1269
        assert other_outage["sla_excluded"] is False, (
            "a POWER outage is never excluded, so the refusal cannot be about exclusion"
        )

        validate_error(
            api.create_outage_credit(
                create_outage_credit_payload(other_outage["id"], subscriber_id), BILLING_ADMIN
            ),
            ApiErrorId.ERR_SUBSCRIBER_NOT_AFFECTED,
        )

        _, meta = validate_paginated(
            api.list_outage_credits(BILLING_ADMIN, {"outage_event_id": other_outage["id"]})
        )
        assert meta["total_count"] == 0, (
            f"the refused preparation created nothing, got {meta['total_count']}"
        )
        assert get_subscriber(subscriber_id)["credit_balance_cents"] == 0

    def test_the_same_outage_shape_on_the_accounts_own_tower_is_creditable(self, api):
        """PRD 3.9: "A `BillingAdmin` prepares one credit per affected household by naming the
        `outage_event_id` and the `subscriber_id`."
        PRD 3.9: "The household must actually be served from the affected site: the tower of
        the account's `sector_id` must be the outage's `tower_id`, else the request is refused
        with `ERR_SUBSCRIBER_NOT_AFFECTED`."
        PRD 3.9: "`cycle_outage_minutes` is the sum of creditable minutes over **every**
        `CLOSED` outage on the account's tower, not merely the one named in the request."

        Design: Corner/errors/a_credit_for_another_towers_outage_is_refused_as_not_affected
        """
        scenario = _setup_account_and_a_second_towers_outage()
        subscriber_id = scenario["subscriber"]["id"]
        own_outage = scenario["own_outage"]

        credit = validate_success(
            api.create_outage_credit(
                create_outage_credit_payload(own_outage["id"], subscriber_id), BILLING_ADMIN
            ),
            201,
        )

        assert_outage_credit(credit)
        assert credit["status"] == "PENDING", f"got {credit['status']}"
        assert credit["outage_event_id"] == own_outage["id"]
        assert credit["subscriber_id"] == subscriber_id
        assert credit["cycle_outage_minutes"] == 1269, (
            "only the account's own tower's outage contributes, got "
            f"{credit['cycle_outage_minutes']}"
        )
        assert credit["credit_cents"] == 1706, (
            "a 1269-minute shortfall against 99.5 percent on a 6999-cent plan, got "
            f"{credit['credit_cents']}"
        )
        assert credit.get("denial_reason") is None


# --------------------------------------------------------------------------
# Pagination bounds
# --------------------------------------------------------------------------


class TestPaginationBounds:
    @pytest.mark.parametrize(
        "label,params",
        [
            ("limit below the minimum", {"limit": 0}),
            ("limit above the maximum", {"limit": 101}),
            ("negative offset", {"offset": -1}),
        ],
        ids=["limit=0", "limit=101", "offset=-1"],
    )
    def test_an_out_of_bounds_page_request_is_refused(self, api, label, params):
        """PRD 2.3: "`limit` caps the number of records returned; when the caller omits it, it
        defaults to 10, its minimum accepted value is 1 and its maximum accepted value is
        100."
        PRD 2.3: "`offset` is the number of records to skip before the first returned record;
        when omitted it defaults to 0, and its minimum accepted value is 0."
        PRD 2.3: "A `limit` below 1, a `limit` above 100, or a negative `offset` is rejected
        with `ERR_PAGINATION_INVALID` (HTTP 400)."

        Design: Corner/errors/pagination_bounds_are_checked_before_any_row_is_read
        """
        setup_pending_install_subscriber()

        response = api.list_subscribers(SALES_AGENT, params)

        validate_error(response, ApiErrorId.ERR_PAGINATION_INVALID)

    def test_the_inclusive_edges_of_the_bounds_are_accepted(self, api):
        """PRD 2.3: "A `limit` below 1, a `limit` above 100, or a negative `offset` is
        rejected with `ERR_PAGINATION_INVALID` (HTTP 400)."
        PRD 2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more`
        inside the `meta` object of the envelope. `total_count` is the number of records
        matching the filter before pagination is applied, and `has_more` is true when records
        remain beyond the returned page."

        Design: Corner/errors/pagination_bounds_are_checked_before_any_row_is_read
        """
        scenario = setup_pending_install_subscriber()

        rows, meta = validate_paginated(
            api.list_subscribers(SALES_AGENT, {"limit": 100, "offset": 0})
        )
        assert meta["limit"] == 100, "100 is the inclusive ceiling"
        assert meta["offset"] == 0, "0 is the inclusive floor for offset"
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert [row["id"] for row in rows] == [scenario["subscriber"]["id"]]

        rows, meta = validate_paginated(
            api.list_subscribers(SALES_AGENT, {"limit": 1, "offset": 1})
        )
        assert rows == [], "the only row was skipped by the offset"
        assert meta["total_count"] == 1, (
            f"total_count counts matches, not returned rows, got {meta['total_count']}"
        )
        assert meta["has_more"] is False

    def test_the_page_bounds_are_judged_before_the_path_identifier_is_resolved(self, api):
        """PRD 2.7: "When a single request violates more than one rule, the server reports
        exactly one error, chosen by a fixed ladder of precedence. Implementations must
        evaluate the rungs in this order and stop at the first violated rung:"
        PRD 2.7: "**Pagination bounds** — `limit` and `offset` inside the bounds of §2.3, else
        `ERR_PAGINATION_INVALID` (400). Applies to every list endpoint."
        PRD 2.7: "**Path existence** — every identifier in the path resolves, left to right,
        else the matching 404 of §2.6."

        Design: Corner/errors/pagination_bounds_are_checked_before_any_row_is_read
        """
        scenario = setup_pending_install_subscriber()

        validate_error(
            api.list_tower_outage_events(NON_EXISTENT_UUID, NETWORK_ENGINEER, {"limit": 0}),
            ApiErrorId.ERR_PAGINATION_INVALID,
        )
        validate_error(
            api.list_usage_records(
                NON_EXISTENT_UUID, BILLING_ADMIN, {"offset": -1}
            ),
            ApiErrorId.ERR_PAGINATION_INVALID,
        )

        validate_error(
            api.list_tower_outage_events(NON_EXISTENT_UUID, NETWORK_ENGINEER, {"limit": 10}),
            ApiErrorId.ERR_TOWER_NOT_FOUND,
        )
        _, meta = validate_paginated(
            api.list_tower_outage_events(
                scenario["tower"]["id"], NETWORK_ENGINEER, {"limit": 10}
            )
        )
        assert meta["total_count"] == 0

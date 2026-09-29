"""Who may call what, whose records they may touch, and which actions they may name.

Authorisation is decided in three layers: the role list of the endpoint, the
ownership of the addressed record, and the narrowing of individual actions on a
shared route. Each layer is exercised together with the positive case that
proves the refusal was about authorisation and nothing else.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    PLANT_COUNTER_HEADERS,
    ApiErrorId,
    make_account_headers,
    make_center_headers,
    make_distributor_headers,
    make_retailer_headers,
)
from test_helpers import factories as f
from test_helpers import fixtures as h

INSTANT = "2026-08-05T09:00:00Z"


class TestEveryRoleRunsItsOwnOperations:
    """All six roles act in one chain and none of them is refused."""

    def test_the_six_owned_operations_all_succeed_in_sequence(self, api):
        """Submission, approval, bag intake, plant count, dispute, exemption, read and suspension.

        PRD: "A label that clears all three clauses is `COVERED` with `coverage_reason`
        `COVERED_STANDARD`. `deposit_cents` is then set to the standard per-container deposit
        of 10 cents; a `NOT_COVERED` label has `deposit_cents` 0."

        PRD: "An `AccountHolder` who disagrees with the count may dispute it, moving the bag
        `COUNTED → DISPUTED` and incrementing `recount_count` by 1."

        PRD: "The reason depends on who asked: when a `CenterOperator` suspends its own site
        the reason is `OPERATOR_REQUEST`, and when programme staff suspend it the reason is
        `PROGRAM_ACTION`."

        Design: Corner/rbac/every_role_can_run_the_operations_it_owns
        """
        h.set_clock(api, INSTANT)
        period = h.create_period(api, operating_cost_cents=0)
        distributor = h.create_distributor(api)
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center = fleet["center"]
        account = h.create_account(api, bag_drop_enrolled=True)
        retailer = h.create_retailer(api)
        product = h.create_draft_product(api, distributor["id"])

        agent_headers = make_distributor_headers(distributor["id"])
        operator_headers = make_center_headers(center["id"])
        holder_headers = make_account_headers(account["id"])
        clerk_headers = make_retailer_headers(retailer["id"])

        submitted = validate_success(
            api.post_registration_action(
                product["id"], f.registration_action_payload("SUBMIT"), agent_headers
            )
        )
        assert submitted["registration_state"] == "SUBMITTED"

        approved = validate_success(
            api.post_registration_action(
                product["id"], f.registration_action_payload("APPROVE"), ADMIN_HEADERS
            )
        )
        assert approved["registration_state"] == "REGISTERED"
        assert approved["coverage_status"] == "COVERED"
        assert approved["deposit_cents"] == 10

        bag = validate_success(
            api.create_bag_drop(
                f.create_bag_drop_payload(
                    account["id"], center["id"], tag_code="TAG-1001", declared_count=100
                ),
                operator_headers,
            ),
            expected_status=201,
        )

        counted = validate_success(
            api.post_bag_drop_count_result(
                bag["id"],
                f.bag_drop_count_payload([60, 40], bag["version"]),
                PLANT_COUNTER_HEADERS,
            )
        )
        assert counted["status"] == "COUNTED"

        disputed = validate_success(
            api.post_bag_drop_settlement_action(
                bag["id"], f.bag_drop_settlement_payload("DISPUTE"), holder_headers
            )
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["recount_count"] == 1
        assert disputed["counted_total"] == 100
        assert disputed["final_credit_cents"] == 950

        exempt = validate_success(
            api.post_exemption_action(
                retailer["id"],
                f.exemption_action_payload("CLAIM_EXEMPTION"),
                clerk_headers,
            )
        )
        assert exempt["obligation_status"] == "EXEMPT"
        assert exempt["nearest_center_id"] == center["id"]

        rows, meta = validate_paginated(
            api.list_program_periods(ADMIN_HEADERS, params={"status": "OPEN"})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [period["id"]]

        suspended = validate_success(
            api.post_center_status_change(
                center["id"],
                f.center_status_change_payload("SUSPEND"),
                operator_headers,
            )
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "OPERATOR_REQUEST"


class TestUnlistedRolesAreUnauthorized:
    """A well-formed request from a role the endpoint never lists is a 403."""

    def test_five_reserved_operations_refuse_five_wrong_roles(self, api):
        """Registry creation, quarter reading, plant counting and reconciliation are reserved.

        PRD: "When the headers are well formed but the acting role is not among the roles
        listed for the requested operation, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD: "The submitted natural key is unused → otherwise the matching duplicate error:
        `ERR_DUPLICATE_PERMIT_NUMBER` for `permit_number`, `ERR_DUPLICATE_UPC` for `upc`,
        `ERR_DUPLICATE_ASSET_TAG` for `asset_tag`, `ERR_DUPLICATE_ACCOUNT_CODE` for
        `account_code`, `ERR_DUPLICATE_TAG_CODE` for `tag_code`, `ERR_DUPLICATE_BATCH_CODE`
        for `batch_code`, `ERR_DUPLICATE_QUARTER_CODE` for `quarter_code` (all HTTP 409)."

        Design: Corner/rbac/roles_absent_from_an_endpoint_are_unauthorized
        """
        h.set_clock(api, INSTANT)
        period = h.create_period(api, operating_cost_cents=0)
        distributor = h.create_distributor(api)
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center = fleet["center"]
        account = h.create_account(api, bag_drop_enrolled=True)
        bag = h.create_bag_drop(api, account["id"], center["id"], declared_count=100)

        operator_headers = make_center_headers(center["id"])
        agent_headers = make_distributor_headers(distributor["id"])

        refusals = [
            api.create_distributor(
                f.create_distributor_payload(
                    legal_name="Rogue Bottling LLC", permit_number="PERMIT-9001"
                ),
                operator_headers,
            ),
            api.create_redemption_center(
                f.create_redemption_center_payload(
                    site_name="Rogue Center", x_miles=5.0, y_miles=5.0
                ),
                agent_headers,
            ),
            api.get_program_period(period["id"], operator_headers),
            api.post_bag_drop_count_result(
                bag["id"],
                f.bag_drop_count_payload([100], bag["version"]),
                operator_headers,
            ),
            api.post_period_action(
                period["id"],
                f.period_action_payload("RECONCILE"),
                PLANT_COUNTER_HEADERS,
            ),
        ]
        for response in refusals:
            validate_error(
                response, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403
            )

        _, center_meta = validate_paginated(api.list_redemption_centers(ADMIN_HEADERS))
        assert center_meta["total_count"] == 1

        validate_success(
            api.create_distributor(
                f.create_distributor_payload(
                    legal_name="Rogue Bottling LLC", permit_number="PERMIT-9001"
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        stored_bag = h.read_bag_drop(api, bag["id"], PLANT_COUNTER_HEADERS)
        assert stored_bag["status"] == "DROPPED"
        assert stored_bag["version"] == bag["version"]

        stored_period = h.read_period(api, period["id"])
        assert stored_period["status"] == "OPEN"
        assert stored_period["version"] == 1


class TestCenterOperatorsAreConfinedToTheirOwnSite:
    """The same role on the same endpoint succeeds or fails on ownership alone."""

    def test_operator_b_is_refused_on_centre_a_and_operator_a_is_served(self, api):
        """Three refusals leave the visit open; the owning operator then closes it.

        PRD: "When `X-User-Role` is `CenterOperator`, `X-User-ID` is the `id` of the acting
        `RedemptionCenter`; ownership checks compare it to the addressed centre's own `id` and
        to the `center_id` of any addressed machine, visit, bag drop or commodity batch."

        PRD: "An entity-backed role that reaches for a resource owned by a different instance
        of its backing entity is rejected with `ERR_FORBIDDEN_RESOURCE` (HTTP 403)."

        Design: Corner/rbac/center_operators_cannot_reach_another_centers_resources
        """
        h.set_clock(api, INSTANT)
        first = h.create_operational_center(
            api, {"site_name": "Center A"}, {"asset_tag": "RVM-A001"}
        )
        second = h.create_operational_center(
            api,
            {"site_name": "Center B", "x_miles": 20.0, "y_miles": 20.0},
            {"asset_tag": "RVM-B001"},
        )
        center_a, machine_a = first["center"], first["machine"]
        center_b = second["center"]
        headers_a = make_center_headers(center_a["id"])
        headers_b = make_center_headers(center_b["id"])

        visit_a = h.open_center_machine_visit(api, center_a["id"], machine_a["id"])

        for response in (
            api.get_redemption_center(center_a["id"], headers_b),
            api.close_count(visit_a["id"], headers_b),
            api.get_machine(machine_a["id"], headers_b),
        ):
            validate_error(
                response, ApiErrorId.ERR_FORBIDDEN_RESOURCE.value, expected_status=403
            )

        assert h.read_visit(api, visit_a["id"], headers_a)["count_status"] == "OPEN"

        closed = validate_success(api.close_count(visit_a["id"], headers_a))
        assert closed["count_status"] == "COUNTED"
        assert closed["payout_cents"] == 0


class TestDistributorAgentsAreConfinedToTheirOwnLabels:
    """Ownership is checked against the request body as well as the path."""

    def test_agent_b_cannot_read_create_for_or_submit_distributor_a(self, api):
        """The body's `distributor_id` is subject to the same ownership check as the path.

        PRD: "When `X-User-Role` is `DistributorAgent`, `X-User-ID` is the `id` of the acting
        `Distributor`; ownership checks compare it to the addressed distributor's own `id` and
        to the `distributor_id` of any addressed label."

        PRD: "This check applies to every endpoint whose path or body names a `Distributor`,
        `RedemptionCenter`, `RedeemerAccount`, `Retailer`, `RedemptionVisit`,
        `ReverseVendingMachine`, `BagDrop` or `CommodityBatch`."

        Design: Corner/rbac/distributor_agents_cannot_act_for_another_distributor
        """
        h.set_clock(api, INSTANT)
        dist_a = h.create_distributor(api)
        dist_b = h.create_distributor(
            api, legal_name="Rogue Valley Beverage", permit_number="PERMIT-1002"
        )
        product_a = h.create_draft_product(api, dist_a["id"])
        headers_a = make_distributor_headers(dist_a["id"])
        headers_b = make_distributor_headers(dist_b["id"])

        for response in (
            api.get_distributor(dist_a["id"], headers_b),
            api.create_beverage_product(
                f.create_beverage_product_payload(
                    dist_a["id"], brand_name="Rogue Spring", upc="011110000009"
                ),
                headers_b,
            ),
            api.post_registration_action(
                product_a["id"], f.registration_action_payload("SUBMIT"), headers_b
            ),
        ):
            validate_error(
                response, ApiErrorId.ERR_FORBIDDEN_RESOURCE.value, expected_status=403
            )

        _, meta = validate_paginated(
            api.list_beverage_products(ADMIN_HEADERS, params={"upc": "011110000009"})
        )
        assert meta["total_count"] == 0

        stored_label = validate_success(
            api.get_beverage_product(product_a["id"], headers_a)
        )
        assert stored_label["registration_state"] == "DRAFT"

        owner = validate_success(api.get_distributor(dist_a["id"], headers_a))
        assert owner["id"] == dist_a["id"]
        assert owner["containers_initiated_count"] == 0


class TestAccountHoldersSeeOnlyTheirOwnRecords:
    """A holder's reach extends to its own account and its own bags, nothing else."""

    def test_holder_b_is_refused_on_holder_a_and_served_on_itself(self, api):
        """Account, credit journal and bag drop are all tenant-scoped by `X-User-ID`.

        PRD: "When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting
        `RedeemerAccount`; ownership checks compare it to the addressed account's own `id` and
        to the `account_id` of any addressed bag drop."

        PRD: "The advance is posted as a credit journal line with `entry_type` `PROVISIONAL`,
        `source_kind` `BAG_DROP` and `source_ref_id` equal to the new bag's `id`, after which
        the account's `credit_balance_cents` is recomputed."

        Design: Corner/rbac/account_holders_see_only_their_own_account
        """
        h.set_clock(api, INSTANT)
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center = fleet["center"]
        account_a = h.create_account(api, bag_drop_enrolled=True)
        account_b = h.create_account(
            api,
            holder_name="Sam Fry",
            account_code="ACCT-1002",
            bag_drop_enrolled=True,
        )
        bag_a = h.create_bag_drop(
            api, account_a["id"], center["id"], declared_count=100
        )
        headers_a = make_account_headers(account_a["id"])
        headers_b = make_account_headers(account_b["id"])

        for response in (
            api.get_redeemer_account(account_a["id"], headers_b),
            api.list_credit_entries(account_a["id"], headers_b),
            api.get_bag_drop(bag_a["id"], headers_b),
        ):
            validate_error(
                response, ApiErrorId.ERR_FORBIDDEN_RESOURCE.value, expected_status=403
            )

        own = validate_success(api.get_redeemer_account(account_b["id"], headers_b))
        assert own["id"] == account_b["id"]
        assert own["credit_balance_cents"] == 0
        assert own["bag_drop_enrolled"] is True

        rows, meta = validate_paginated(
            api.list_credit_entries(account_a["id"], headers_a)
        )
        assert meta["total_count"] == 1
        assert rows[0]["entry_type"] == "PROVISIONAL"
        assert rows[0]["amount_cents"] == 800
        assert rows[0]["source_ref_id"] == bag_a["id"]


class TestDangerousActionsStayWithProgramAdmin:
    """Four shared routes hide four actions the operating roles may not name."""

    def test_release_hold_reverse_revoke_and_credit_are_refused_to_the_operating_roles(
        self, api
    ):
        """Authorisation is evaluated per action, so the same paths still work for the admin.

        PRD: "The `RELEASE_HOLD` and `REVERSE` payout actions, the `REJECT`, `APPROVE`,
        `SUSPEND` and `REINSTATE` registration actions, the `VOID` settlement action, the
        `FLAG`, `UNFLAG` and `CLOSE` account actions, the `ACTIVATE`, `REINSTATE` and `CLOSE`
        centre actions, the `REVOKE_EXEMPTION` exemption action and the `RETIRE` machine event
        are reachable only by `ProgramAdmin`, even on an endpoint that other roles may
        otherwise call."

        PRD: "A role reaching for an action outside its narrowing is refused with
        `ERR_UNAUTHORIZED`."

        PRD: "Releasing sets `fraud_hold` back to false and `withhold_reason` back to null,
        and recomputes the centre's `withheld_visit_count`."

        Design: Corner/rbac/restricted_actions_stay_with_program_admin
        """
        h.set_clock(api, INSTANT)
        h.create_period(api, operating_cost_cents=0)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center, machine = fleet["center"], fleet["machine"]
        retailer = h.create_retailer(api)
        account = h.create_account(api, bag_drop_enrolled=True)
        operator_headers = make_center_headers(center["id"])
        clerk_headers = make_retailer_headers(retailer["id"])
        holder_headers = make_account_headers(account["id"])

        h.exemption_action(api, retailer["id"], "CLAIM_EXEMPTION", clerk_headers)
        bag = h.create_bag_drop(api, account["id"], center["id"], declared_count=100)
        h.submit_bag_count(api, bag["id"], [100], bag["version"])

        held = h.open_center_machine_visit(api, center["id"], machine["id"])
        h.add_lot(
            api,
            held["id"],
            product["id"],
            20,
            operator_headers,
            expected_visit_version=held["version"],
        )
        withheld = h.payout_action(
            api, held["id"], "WITHHOLD", operator_headers, reason="manual review"
        )
        assert withheld["payout_status"] == "WITHHELD"

        paid_visit = h.create_paid_center_visit(
            api, center["id"], machine["id"], product["id"], [30]
        )
        assert paid_visit["payout_status"] == "PAID"

        for response in (
            api.post_payout_action(
                held["id"],
                f.payout_action_payload("RELEASE_HOLD"),
                operator_headers,
            ),
            api.post_payout_action(
                paid_visit["id"], f.payout_action_payload("REVERSE"), operator_headers
            ),
            api.post_exemption_action(
                retailer["id"],
                f.exemption_action_payload("REVOKE_EXEMPTION"),
                clerk_headers,
            ),
            api.post_bag_drop_settlement_action(
                bag["id"], f.bag_drop_settlement_payload("CREDIT"), holder_headers
            ),
        ):
            validate_error(
                response, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403
            )

        assert (
            h.read_visit(api, held["id"], operator_headers)["payout_status"]
            == "WITHHELD"
        )
        assert (
            h.read_visit(api, paid_visit["id"], operator_headers)["payout_status"]
            == "PAID"
        )
        assert (
            h.read_retailer(api, retailer["id"], clerk_headers)["obligation_status"]
            == "EXEMPT"
        )
        assert h.read_bag_drop(api, bag["id"], PLANT_COUNTER_HEADERS)["status"] == "COUNTED"

        released = validate_success(
            api.post_payout_action(
                held["id"], f.payout_action_payload("RELEASE_HOLD"), ADMIN_HEADERS
            )
        )
        assert released["payout_status"] == "PENDING"
        assert released["fraud_hold"] is False
        assert released["withhold_reason"] is None

        revoked = validate_success(
            api.post_exemption_action(
                retailer["id"],
                f.exemption_action_payload("REVOKE_EXEMPTION"),
                ADMIN_HEADERS,
            )
        )
        assert revoked["obligation_status"] == "OBLIGATED"
        assert revoked["nearest_center_id"] is None


class TestSharedOperationsWorkForBothRoles:
    """The opaque admin needs no ownership of the centre it acts for."""

    def test_two_identical_visits_close_the_same_way_for_operator_and_admin(self, api):
        """Both closures value 40 containers at 400 cents and both feed the same counters.

        PRD: "When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator
        identifier not tied to any persisted entity; the server may record it (for example as
        the `source_ref_id` of a journal line whose `source_kind` is `PROGRAM_ACTION`) but never
        compares it to any entity's `id`."

        PRD: "In all cases the hosting centre's `accepted_container_count` and
        `unbatched_container_count` are recomputed, releasing the newly accepted containers
        into the pool that commodity batches draw from."

        Design: Corner/rbac/shared_operations_work_for_operator_and_program_admin_alike
        """
        h.set_clock(api, INSTANT)
        distributor = h.create_distributor(api)
        product = h.create_registered_product(api, distributor["id"])
        fleet = h.create_operational_center(
            api,
            {"site_name": "Bend Redemption Center", "opening_cash_cents": 50000},
        )
        center, machine = fleet["center"], fleet["machine"]
        operator_headers = make_center_headers(center["id"])

        results = []
        for headers in (operator_headers, ADMIN_HEADERS):
            visit = validate_success(
                api.create_redemption_visit(
                    f.center_machine_visit_payload(center["id"], machine["id"]),
                    headers,
                ),
                expected_status=201,
            )
            validate_success(
                api.create_container_lot(
                    visit["id"],
                    f.create_lot_payload(product["id"], 40, visit["version"]),
                    headers,
                ),
                expected_status=201,
            )
            results.append(validate_success(api.close_count(visit["id"], headers)))

        for closed in results:
            assert closed["count_status"] == "COUNTED"
            assert closed["payable_count"] == 40
            assert closed["payout_cents"] == 400

        stored_center = h.read_center(api, center["id"], operator_headers)
        assert stored_center["accepted_container_count"] == 80
        assert stored_center["unbatched_container_count"] == 80

        assert h.read_machine(api, machine["id"], operator_headers)["bin_filled_count"] == 80

"""Identity, role and person: three different refusals wearing 401 and 403.

The ladder separates "who are you" (step 1) from "may your role do this"
(step 2), from "does your row-scoped grant reach this row" (step 6), from "are
you the same person who asked for it" (step 18). Each of the four tests below
pins one of those steps and then shows the same call succeeding once only that
one obstacle is removed.
"""

import pytest

from test_helpers import (
    ADMIN,
    ADMIN_USER_ID,
    ANALYST,
    DUAL_ADMIN,
    DUAL_ANALYST,
    DUAL_USER_ID,
    ERR_FORBIDDEN_ROLE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STATION_NOT_OWNED,
    ERR_UNAUTHENTICATED,
    OPS,
    ROLE_STATION_COORDINATOR,
    UNDECLARED_ROLE,
    assert_millisecond_timestamp,
    assert_station_supply,
    assert_undecided_exception,
    factories as f,
    fixtures as fx,
    headers_for,
    headers_missing_role,
    headers_missing_user_id,
    headers_with_unknown_role,
    make_station_coordinator_headers,
    validate_error,
    validate_success,
)

GHOST_USER_ID = "u_ghost_1"
LOOSE_COORDINATOR = headers_for(ROLE_STATION_COORDINATOR, "u_station_1")

RBAC_POLICY_PAYLOAD = dict(
    policy_code="FY27-RBAC",
    min_coverage_pct=5.00,
    max_single_counterparty_pct=100.00,
    permitted_instrument_types=["SWAP"],
    max_earnings_volatility_usd=500000.00,
    eligible_fleet_types=["NARROWBODY"],
)

#: One creator per role that may not reach it, each with a payload that would
#: otherwise be accepted.
WRONG_ROLE_CREATES = {
    "analyst_creating_a_policy": lambda api: api.create_hedge_policy(
        f.hedge_policy_payload(**RBAC_POLICY_PAYLOAD), headers=ANALYST
    ),
    "coordinator_creating_a_counterparty": lambda api: api.create_counterparty(
        f.counterparty_payload(
            counterparty_code="DLRC",
            legal_name="Dealer C Bank NA",
            credit_rating="A",
            credit_limit_usd=2000000.00,
        ),
        headers=LOOSE_COORDINATOR,
    ),
    "ops_controller_creating_a_forecast": lambda api: api.create_consumption_forecast(
        f.consumption_forecast_payload(), headers=OPS
    ),
}

#: Three ways to fail authentication before any authorisation is considered.
BROKEN_IDENTITIES = {
    "role_header_omitted": headers_missing_role(),
    "user_id_header_omitted": headers_missing_user_id(),
    "role_outside_the_six": headers_with_unknown_role(UNDECLARED_ROLE, GHOST_USER_ID),
}


class TestRoleScopedCreators:
    @pytest.mark.parametrize("attempt", sorted(WRONG_ROLE_CREATES))
    def test_a_creator_reserved_for_another_role_is_forbidden(self, api, attempt):
        """PRD §2.5: "**Role authorisation.** The caller's role is listed for the
        endpoint, otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every
        endpoint."

        Role gating is per endpoint rather than per entity family: the analyst
        who may create forecasts and programmes may not create the policy that
        governs them, and the operations controller who may create flight legs
        may not create a forecast.

        Design: Corner/rbac/three_roles_cannot_reach_creators_reserved_for_other_roles
        """
        validate_error(WRONG_ROLE_CREATES[attempt](api), ERR_FORBIDDEN_ROLE, 403)

    def test_the_identical_policy_payload_is_accepted_for_the_listed_role(self, api):
        """PRD §2.5: "**Request shape.** On every write endpoint: every required
        input field present, every type correct, every enumeration member
        recognised, every numeric constraint honoured, the conditional strike
        fields consistent with the declared instrument type, and any required
        version-pinning field present. Otherwise `ERR_INVALID_REQUEST` (400)."

        Role authorisation is step 2 and request shape step 3, so the payload the
        analyst was refused cannot have been at fault: the very same body is
        created for a `RiskPolicyAdmin`.

        Design: Corner/rbac/three_roles_cannot_reach_creators_reserved_for_other_roles
        """
        validate_error(
            api.create_hedge_policy(
                f.hedge_policy_payload(**RBAC_POLICY_PAYLOAD), headers=ANALYST
            ),
            ERR_FORBIDDEN_ROLE,
            403,
        )

        policy = validate_success(
            api.create_hedge_policy(
                f.hedge_policy_payload(**RBAC_POLICY_PAYLOAD), headers=ADMIN
            ),
            201,
        )
        assert policy["policy_code"] == "FY27-RBAC"
        assert policy["status"] == "ACTIVE"


class TestAuthenticationBeforeAuthorisation:
    @pytest.mark.parametrize("defect", sorted(BROKEN_IDENTITIES))
    def test_a_broken_identity_is_unauthenticated_rather_than_forbidden(
        self, api, defect
    ):
        """PRD §2.5: "**Authentication.** Both headers present and `X-User-Role`
        recognised, otherwise `ERR_UNAUTHENTICATED` (401). Applies to every
        endpoint."

        A missing role header, a missing user id and a role string outside the
        six declared roles are all the same failure, and none of them is a 403:
        the caller has not been identified, so authorisation is never reached.

        Design: Corner/rbac/missing_or_unknown_role_header_is_unauthenticated_not_forbidden
        """
        policy = fx.do_create_policy(api, policy_code="FY27-AUTH")

        validate_error(
            api.get_hedge_policy(policy["id"], headers=BROKEN_IDENTITIES[defect]),
            ERR_UNAUTHENTICATED,
            401,
        )

    def test_an_unknown_role_with_a_malformed_body_still_reports_401(self, api):
        """PRD §2.5: "When a single request could fail several checks, the server
        evaluates them in a fixed order and reports the first failure it finds.
        Text order elsewhere in this document is not authoritative; this ladder
        is."

        PRD §2.5: "**Authentication.** Both headers present and `X-User-Role`
        recognised, otherwise `ERR_UNAUTHENTICATED` (401). Applies to every
        endpoint."

        `fleet_type` `SPACEPLANE` is not a member of the enumeration, but request
        shape is step 3 and authentication is step 1.

        Design: Corner/rbac/missing_or_unknown_role_header_is_unauthenticated_not_forbidden
        """
        validate_error(
            api.create_consumption_forecast(
                f.consumption_forecast_payload(fleet_type="SPACEPLANE"),
                headers=headers_with_unknown_role(UNDECLARED_ROLE, GHOST_USER_ID),
            ),
            ERR_UNAUTHENTICATED,
            401,
        )

    def test_a_declared_role_reads_the_policy_the_broken_headers_could_not(self, api):
        """PRD §2.1: "When `X-User-Role` is `StationCoordinator`, `X-User-ID` is
        the `id` of the acting `Station`; an inventory adjustment submitted by a
        `StationCoordinator` whose `X-User-ID` differs from the `Station`
        identified in the path is rejected with `ERR_STATION_NOT_OWNED`."

        That comparison is scoped to the inventory adjustment. A policy read is
        open to all six roles, so the coordinator is authenticated and authorised
        for it.

        Design: Corner/rbac/missing_or_unknown_role_header_is_unauthenticated_not_forbidden
        """
        policy = fx.do_create_policy(api, policy_code="FY27-AUTH")

        data = validate_success(
            api.get_hedge_policy(policy["id"], headers=LOOSE_COORDINATOR)
        )
        assert data["id"] == policy["id"]
        assert data["policy_code"] == "FY27-AUTH"


class TestRowScopedStationGrant:
    @staticmethod
    def _two_empty_stations(api):
        fx.do_create_policy(api, policy_code="FY27-OWN")
        dfw = fx.do_create_station(
            api,
            iata_code="DFW",
            name="Dallas Fort Worth",
            into_plane_fee_usd_per_gal=0.0450,
            avg_daily_liftings_gallons=100000,
        )
        ord_ = fx.do_create_station(
            api,
            iata_code="ORD",
            name="Chicago OHare",
            into_plane_fee_usd_per_gal=0.0800,
            avg_daily_liftings_gallons=80000,
        )
        return dfw, ord_

    def test_a_coordinator_may_not_adjust_a_station_it_does_not_own(self, api):
        """PRD §2.5: "**Station ownership.** On a station inventory adjustment, a
        `StationCoordinator` caller's `X-User-ID` must equal the station's `id`,
        otherwise `ERR_STATION_NOT_OWNED` (403)."

        The role itself is listed for the endpoint, so step 2 clears and step 6
        is the refusal; the target station's ledger stays at zero.

        Design: Corner/rbac/station_coordinator_cannot_adjust_a_station_it_does_not_own
        """
        dfw, ord_ = self._two_empty_stations(api)

        validate_error(
            api.adjust_station_inventory(
                dfw["id"],
                f.inventory_adjustment_payload(
                    500000, "Coordinator posting against the wrong station record."
                ),
                headers=make_station_coordinator_headers(ord_["id"]),
            ),
            ERR_STATION_NOT_OWNED,
            403,
        )

        assert_station_supply(
            fx.read_station(api, dfw["id"]),
            inventory_gallons=0,
            days_cover=0.00,
        )

    def test_the_owner_and_the_unscoped_controller_both_move_the_ledger(self, api):
        """PRD §2.1: "A `FuelOpsController` performing the same adjustment is not
        subject to that ownership restriction and may adjust any station."

        PRD §3.2: "`days_cover` is `effective_inventory_gallons` divided by
        `avg_daily_liftings_gallons`, rounded to two decimal places" and "from the
        minimum up to but not including twice the minimum it is `WATCH`".

        The rejected call succeeds unchanged once the coordinator's `X-User-ID`
        is the station's own id: 500,000 gallons over 100,000 daily liftings is
        5.00 days, and the controller's later withdrawal leaves 4.00.

        Design: Corner/rbac/station_coordinator_cannot_adjust_a_station_it_does_not_own
        """
        dfw, _ord = self._two_empty_stations(api)

        owned = validate_success(
            api.adjust_station_inventory(
                dfw["id"],
                f.inventory_adjustment_payload(
                    500000, "Opening physical stock at the coordinator's own station."
                ),
                headers=make_station_coordinator_headers(dfw["id"]),
            )
        )
        assert_station_supply(
            owned,
            inventory_gallons=500000,
            days_cover=5.00,
            supply_posture="WATCH",
        )

        by_controller = validate_success(
            api.adjust_station_inventory(
                dfw["id"],
                f.inventory_adjustment_payload(
                    -100000, "Operations controller trues up after a large lifting."
                ),
                headers=OPS,
            )
        )
        assert_station_supply(
            by_controller,
            inventory_gallons=400000,
            days_cover=4.00,
            supply_posture="WATCH",
        )


class TestSegregationOfDutiesOnExceptionDecisions:
    @staticmethod
    def _exception_raised_by_the_dual_hatted_user(api):
        return fx.do_request_exception(
            api,
            "EARNINGS_VOLATILITY_BREACH",
            justification=(
                "Standing tolerance requested ahead of the February revaluation "
                "cycle."
            ),
            headers=DUAL_ANALYST,
        )

    @pytest.mark.parametrize("decision", ["approve", "deny"])
    def test_the_requester_cannot_decide_their_own_exception(self, api, decision):
        """PRD §3.9: "Both decisions are subject to segregation of duties: the
        deciding `X-User-ID` must differ from `requested_by_user_id`, otherwise
        `ERR_SEGREGATION_OF_DUTIES`."

        The caller genuinely holds `RiskPolicyAdmin`, so this is a comparison of
        identities rather than of roles, and switching from approval to denial
        does not convert it.

        Design: Corner/rbac/exception_requester_cannot_decide_their_own_exception
        """
        exception = self._exception_raised_by_the_dual_hatted_user(api)
        assert exception["requested_by_user_id"] == DUAL_USER_ID

        endpoint = (
            api.approve_policy_exception
            if decision == "approve"
            else api.deny_policy_exception
        )
        validate_error(
            endpoint(exception["id"], f.decision_payload(), headers=DUAL_ADMIN),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        assert_undecided_exception(fx.read_exception(api, exception["id"]))

    def test_an_independent_administrator_decides_the_same_row(self, api):
        """PRD §3.9: "Approval advances `REQUESTED → APPROVED` and denial advances
        `REQUESTED → DENIED`; both stamp `decided_by_user_id` with the caller's
        `X-User-ID` and `decided_at` from the logical clock".

        The row was never the problem: a different administrator decides it
        immediately afterwards, which is what makes the earlier refusal a
        statement about the person.

        Design: Corner/rbac/exception_requester_cannot_decide_their_own_exception
        """
        exception = self._exception_raised_by_the_dual_hatted_user(api)
        validate_error(
            api.deny_policy_exception(
                exception["id"], f.decision_payload(), headers=DUAL_ADMIN
            ),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        denied = validate_success(
            api.deny_policy_exception(
                exception["id"],
                f.decision_payload(
                    "Denied by an independent approver; tolerance not justified."
                ),
                headers=ADMIN,
            )
        )
        assert denied["status"] == "DENIED"
        assert denied["decided_by_user_id"] == ADMIN_USER_ID
        assert_millisecond_timestamp(denied["decided_at"], "decided_at")

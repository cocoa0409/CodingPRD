"""Validation-pipeline ordering (role before state) and grower debarment
cascades (PRD §2.9, §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_coverage_unit,
    assign_adjuster,
    bind_policy,
    build_user_headers,
    create_adjuster,
    create_policy_application,
    file_hail_claim,
    make_policyholder_headers,
    pay_premium,
    read_claim,
    read_policy,
    read_unit,
    set_clock,
    setup_bound_crop_hail_policy,
    submit_planting_report,
    validate_error,
    validate_success,
)

UW = TEST_USERS["underwriter_headers"]
APPROVER = TEST_USERS["claims_approver_headers"]


class TestAuthTrumpsState:
    def test_wrong_role_bind_on_bound_policy_returns_forbidden(self, api):
        """PRD §2.9: "Every request passes through a fixed validation pipeline.
        First, the presence and shape of the identity headers are checked
        (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, role
        authorization is enforced (`ERR_INSUFFICIENT_PERMISSIONS`). Third, path
        identifiers are resolved left to right (`ERR_NOT_FOUND`). Fourth, on the
        two concurrency-guarded writes, the expected-version check runs
        (`ERR_STALE_VERSION`) — ahead of any business rule. Fifth, the target
        resource must be in a state that permits the requested transition
        (`ERR_INVALID_STATE`, HTTP 409, or the more specific state-guard error
        the workflow declares)."
        A Policyholder bind attempt against an already-BOUND policy violates both
        the role rule and the state rule; the role rule is evaluated first.

        Design: Difficulty/priority_pair_validation_conflict/auth_role_trumps_state_policy_bind
        """
        ctx = setup_bound_crop_hail_policy(acres_list=(1,))
        res = api.bind_policy(
            ctx["carrier_id"], ctx["policy_id"],
            make_policyholder_headers(ctx["grower_id"]),
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_wrong_role_bind_on_application_policy_returns_forbidden(self, api):
        """PRD §2.9: "Every request passes through a fixed validation pipeline.
        First, the presence and shape of the identity headers are checked
        (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, role
        authorization is enforced (`ERR_INSUFFICIENT_PERMISSIONS`)."
        Even when the policy state would permit binding, an Adjuster-role caller
        is refused at the authorization step.

        Design: Difficulty/priority_pair_validation_conflict/auth_role_trumps_state_policy_bind
        """
        carrier_ctx = setup_bound_crop_hail_policy(acres_list=(1,))
        cid = carrier_ctx["carrier_id"]
        adjuster = create_adjuster(cid)
        # A fresh APPLICATION-state policy for the same grower.
        policy = create_policy_application(cid, carrier_ctx["grower_id"], "CROP_HAIL")
        res = api.bind_policy(
            cid, policy["id"],
            build_user_headers(adjuster["id"], "Adjuster"),
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestDebarCascade:
    def _setup_two_policies_with_open_claims(self, api):
        """One grower with two ACTIVE+PAID policies; P1's claim is REPORTED, P2's
        claim is INSPECTION_SCHEDULED."""
        ctx = setup_bound_crop_hail_policy(acres_list=(1,))
        cid, gid = ctx["carrier_id"], ctx["grower_id"]
        adjuster = create_adjuster(cid, capacity_max_open_claims=10)

        # Second policy for the same grower.
        p2 = create_policy_application(cid, gid, "CROP_HAIL")
        p2_unit = add_coverage_unit(cid, p2["id"], "CROP_HAIL", declared_acres=1)
        p2_bound = bind_policy(cid, p2["id"])
        pay_premium(cid, p2["id"], gid, p2_bound["premium_cents"])

        # P1 paid in full too.
        p1 = ctx["policy"]
        pay_premium(cid, p1["id"], gid, p1["premium_cents"])

        set_clock(cid, "2026-08-03T00:00:00Z")

        p1_unit = ctx["units"][0]
        submit_planting_report(cid, p1["id"], p1_unit["id"], gid, reported_acres=1)
        submit_planting_report(cid, p2["id"], p2_unit["id"], gid, reported_acres=1)

        p1_claim = file_hail_claim(cid, p1["id"], gid, p1_unit["id"])
        p2_claim = file_hail_claim(cid, p2["id"], gid, p2_unit["id"])
        assign_adjuster(cid, p2["id"], p2_claim["id"], adjuster["id"])
        return {
            "carrier_id": cid, "grower_id": gid, "adjuster": adjuster,
            "p1": p1, "p2": p2, "p1_unit": p1_unit, "p2_unit": p2_unit,
            "p1_claim": p1_claim, "p2_claim": p2_claim,
        }

    def test_debar_cancels_all_bound_or_active_policies(self, api):
        """PRD §3.9: "An underwriter may debar a grower whose `status` is
        `ACTIVE` or `SUSPENDED`; the grower moves to the terminal `DEBARRED`
        status, every `BOUND` or `ACTIVE` policy of that grower is cancelled in
        cascade, and every claim of that grower in `REPORTED` or
        `INSPECTION_SCHEDULED` is withdrawn in cascade."

        Design: Difficulty/transitive_cascade/debar_grower_cascades_to_policies_then_claims
        """
        ctx = self._setup_two_policies_with_open_claims(api)
        cid, gid = ctx["carrier_id"], ctx["grower_id"]
        res = api.debar_grower(cid, gid, UW)
        grower = validate_success(res, 200)
        assert grower["status"] == "DEBARRED"
        for policy in (ctx["p1"], ctx["p2"]):
            after = read_policy(cid, policy["id"])
            assert after["lifecycle_state"] == "CANCELLED", (
                f"policy {policy['id']} must be cancelled in cascade"
            )

    def test_debar_withdraws_open_claims_and_releases_units(self, api):
        """PRD §3.9: "An underwriter may debar a grower whose `status` is
        `ACTIVE` or `SUSPENDED`; the grower moves to the terminal `DEBARRED`
        status, every `BOUND` or `ACTIVE` policy of that grower is cancelled in
        cascade, and every claim of that grower in `REPORTED` or
        `INSPECTION_SCHEDULED` is withdrawn in cascade."
        PRD §3.7: "Withdrawal moves the claim to `WITHDRAWN` and releases the
        unit back to `REPORTED` so it can host a future claim."

        Design: Difficulty/transitive_cascade/debar_grower_cascades_to_policies_then_claims
        """
        ctx = self._setup_two_policies_with_open_claims(api)
        cid, gid = ctx["carrier_id"], ctx["grower_id"]
        validate_success(api.debar_grower(cid, gid, UW), 200)
        for policy, claim, unit in (
            (ctx["p1"], ctx["p1_claim"], ctx["p1_unit"]),
            (ctx["p2"], ctx["p2_claim"], ctx["p2_unit"]),
        ):
            claim_after = read_claim(cid, policy["id"], claim["id"])
            assert claim_after["claim_state"] == "WITHDRAWN"
            unit_after = read_unit(cid, policy["id"], unit["id"])
            assert unit_after["status"] == "REPORTED", (
                "the cascade-withdrawn claim releases its unit"
            )

"""Authorization budget cap, pinned evaluation order, and committed rollup
(PR'D §3.5, §2.9)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_us_rule,
    create_client,
    create_contact,
    create_family,
    create_granted_application,
    list_obligations,
    get_family,
    get_obligation,
    request_authorization,
    authorize_obligation,
    approve_authorization,
    release_authorization,
    make_client_approver_headers,
    setup_world_with_granted_app,
)

ANY = TEST_USERS["any_headers"]
MGR = TEST_USERS["manager_headers"]
FIN = TEST_USERS["finance_headers"]


class TestAuthorizationCapEvaluationOrder:
    def _cap_world(self):
        """US rule; family cap 20000; GRANTED app with y3 (10000) and y4
        (20000); authorization A on y3 approved, B on y4 requested."""
        create_us_rule()
        client = create_client("CapCo")
        contact = create_contact(client["id"])
        family = create_family(client["id"], budget_cap_cents=20000)
        app = create_granted_application(family["id"], application_number="US-C")
        ob_a, ob_b = list_obligations(app["id"])[0], list_obligations(app["id"])[1]
        au_a = authorize_obligation(ob_a["id"], 10000, contact["id"])
        au_b, _ = request_authorization(ob_b["id"], 20000)
        return contact, family, ob_a, ob_b, au_a, au_b

    def test_failed_approval_changes_nothing(self):
        """PRD §3.5: "read the family's current `committed_forecast_cents` —
        which already includes every currently committed obligation — add the
        authorization's `amount_cents`, and reject with
        `ERR_FAMILY_BUDGET_EXCEEDED` when that sum strictly exceeds the
        family's `budget_cap_cents`, changing nothing; a sum exactly equal to
        the cap is permitted."

        Design: Difficulty/combinatorial_formula/authorization_cap_evaluation_order_is_pinned
        """
        contact, family, ob_a, ob_b, au_a, au_b = self._cap_world()
        resp = api_client.approve_authorization(au_b["id"], make_client_approver_headers(contact["id"]))
        validate_error(resp, ApiErrorId.ERR_FAMILY_BUDGET_EXCEEDED)
        # 10000 + 20000 > 20000: committed stays at exactly 10000, B stays REQUESTED.
        assert get_family(family["id"])["committed_forecast_cents"] == 10000
        assert validate_success(api_client.get_authorization(au_b["id"], ANY), 200)["status"] == "REQUESTED"

    def test_after_compensation_the_same_approval_succeeds(self):
        """PRD §3.5: "deauthorizing moves the obligation `AUTHORIZED →
        SCHEDULED`, subtracts its `authorized_amount_cents` from the family's
        `committed_forecast_cents`, clears `authorized_amount_cents` back to
        null, and supersedes the current authorization whether it was
        `APPROVED` or `RELEASED` (→ `SUPERSEDED`)."

        Design: Difficulty/combinatorial_formula/authorization_cap_evaluation_order_is_pinned
        """
        contact, family, ob_a, ob_b, au_a, au_b = self._cap_world()
        validate_error(
            api_client.approve_authorization(au_b["id"], make_client_approver_headers(contact["id"])),
            ApiErrorId.ERR_FAMILY_BUDGET_EXCEEDED,
        )
        validate_success(api_client.deauthorize_obligation(ob_a["id"], MGR), 200)
        assert validate_success(api_client.get_authorization(au_a["id"], ANY), 200)["status"] == "SUPERSEDED"
        assert get_family(family["id"])["committed_forecast_cents"] == 0
        # With committed back at 0 the same B approval now fits under the cap.
        approved = api_client.approve_authorization(au_b["id"], make_client_approver_headers(contact["id"]))
        assert validate_success(approved, 200)["status"] == "APPROVED"
        assert get_family(family["id"])["committed_forecast_cents"] == 20000


class TestBudgetCapExactEquality:
    def _equality_world(self):
        """US rule; family cap 50000; app A1 with y3 (10000) and y4 (20000)
        approved and y5 (20000) requested; app A2 with y3 requested at 1."""
        create_us_rule()
        client = create_client("CapEq")
        contact = create_contact(client["id"])
        family = create_family(client["id"], budget_cap_cents=50000)
        app1 = create_granted_application(family["id"], application_number="US-E1")
        a1y3, a1y4, a1y5 = list_obligations(app1["id"])[:3]
        authorize_obligation(a1y3["id"], 10000, contact["id"])
        authorize_obligation(a1y4["id"], 20000, contact["id"])
        au_y5, _ = request_authorization(a1y5["id"], 20000)
        app2 = create_granted_application(family["id"], application_number="US-E2")
        a2y3 = list_obligations(app2["id"])[0]
        au_one_cent, _ = request_authorization(a2y3["id"], 1)
        return contact, family, au_y5, au_one_cent

    def test_approval_landing_exactly_on_cap_is_permitted(self):
        """PRD §3.5: "reject with `ERR_FAMILY_BUDGET_EXCEEDED` when that sum
        strictly exceeds the family's `budget_cap_cents`, changing nothing; a
        sum exactly equal to the cap is permitted."

        Design: Difficulty/boundary_precision_check/budget_cap_exact_equality_approved
        """
        contact, family, au_y5, _ = self._equality_world()
        # committed 30000 + 20000 == cap 50000: allowed.
        resp = api_client.approve_authorization(au_y5["id"], make_client_approver_headers(contact["id"]))
        assert validate_success(resp, 200)["status"] == "APPROVED"
        assert get_family(family["id"])["committed_forecast_cents"] == 50000

    def test_one_cent_over_cap_is_rejected(self):
        """PRD §3.5: "reject with `ERR_FAMILY_BUDGET_EXCEEDED` when that sum
        strictly exceeds the family's `budget_cap_cents`, changing nothing; a
        sum exactly equal to the cap is permitted."

        Design: Difficulty/boundary_precision_check/budget_cap_exact_equality_approved
        """
        contact, family, au_y5, au_one_cent = self._equality_world()
        validate_success(
            api_client.approve_authorization(au_y5["id"], make_client_approver_headers(contact["id"])), 200)
        # committed 50000 + 1 > 50000: rejected.
        resp = api_client.approve_authorization(au_one_cent["id"], make_client_approver_headers(contact["id"]))
        validate_error(resp, ApiErrorId.ERR_FAMILY_BUDGET_EXCEEDED)
        assert get_family(family["id"])["committed_forecast_cents"] == 50000


class TestApproveRollupCascade:
    def test_approve_moves_obligation_and_sets_authorized_amount(self):
        """PRD §3.5: "the cascade moves the obligation to `AUTHORIZED`, copies
        the authorization's `amount_cents` into the obligation's
        `authorized_amount_cents`, and adds the amount into the family's
        `committed_forecast_cents` — so the gated sum becomes the new stored
        rollup and the check never observes a half-updated value."

        Design: Difficulty/transitive_cascade/authorization_approve_rollup_depth2_cascade
        """
        world = setup_world_with_granted_app(client_name="RollCo")
        obligation = world["obligations"][0]
        au, _ = request_authorization(obligation["id"], 10000, requester_headers=FIN)
        approve_authorization(au["id"], world["contact"]["id"])
        ob = get_obligation(obligation["id"])
        assert ob["status"] == "AUTHORIZED"
        assert ob["authorized_amount_cents"] == 10000

    def test_approve_updates_family_rollup_immediately_and_records_decider(self):
        """PRD §3.5: "the cascade moves the obligation to `AUTHORIZED`, copies
        the authorization's `amount_cents` into the obligation's
        `authorized_amount_cents`, and adds the amount into the family's
        `committed_forecast_cents`" and "On approval, `decided_by_user_id`
        records the approver, the authorization becomes `APPROVED`, and the
        cascade moves the obligation to `AUTHORIZED`"

        Design: Difficulty/transitive_cascade/authorization_approve_rollup_depth2_cascade
        """
        world = setup_world_with_granted_app(client_name="RollCo")
        obligation = world["obligations"][0]
        au, _ = request_authorization(obligation["id"], 10000, requester_headers=FIN)
        approve_authorization(au["id"], world["contact"]["id"])
        family = get_family(world["family"]["id"])
        assert family["committed_forecast_cents"] == 10000
        au_data = validate_success(api_client.get_authorization(au["id"], ANY), 200)
        assert au_data["status"] == "APPROVED"
        assert au_data["decided_by_user_id"] == world["contact"]["id"]


class TestStateBeatsFiscalOnDoubleApprove:
    def test_second_approve_reports_invalid_state_not_budget(self):
        """PRD §2.9: "7. **State.** The target resource must be in a from-state
        that defines the requested transition; an undefined transition is
        rejected with `ERR_INVALID_STATE`" and "Only after all eight universal
        layers pass are business rules evaluated". PRD §3.5: "both operations
        are defined only while the authorization is `REQUESTED`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_double_approve
        """
        create_us_rule()
        client = create_client("PrioCo")
        contact = create_contact(client["id"])
        family = create_family(client["id"], budget_cap_cents=20000)
        app = create_granted_application(family["id"], application_number="US-PP")
        obligation = list_obligations(app["id"])[0]
        au = authorize_obligation(obligation["id"], 20000, contact["id"])
        # committed == cap; a second approve is both out-of-state and over-cap.
        resp = api_client.approve_authorization(au["id"], make_client_approver_headers(contact["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_family(family["id"])["committed_forecast_cents"] == 20000

    def test_state_rejection_leaves_authorization_and_rollup_untouched(self):
        """PRD §3.5: "reject with `ERR_FAMILY_BUDGET_EXCEEDED` when that sum
        strictly exceeds the family's `budget_cap_cents`, changing nothing";
        the state-layer rejection of §2.9 fires before that business gate, so
        the authorization remains APPROVED and committed remains at the cap.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_double_approve
        """
        create_us_rule()
        client = create_client("PrioCo")
        contact = create_contact(client["id"])
        family = create_family(client["id"], budget_cap_cents=20000)
        app = create_granted_application(family["id"], application_number="US-PP")
        obligation = list_obligations(app["id"])[0]
        au = authorize_obligation(obligation["id"], 20000, contact["id"])
        resp = api_client.approve_authorization(au["id"], make_client_approver_headers(contact["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        au_data = validate_success(api_client.get_authorization(au["id"], ANY), 200)
        assert au_data["status"] == "APPROVED"
        assert get_family(family["id"])["committed_forecast_cents"] == 20000


class TestDeauthorizeConservation:
    def test_authorize_then_deauthorize_restores_committed_exactly(self):
        """PRD §3.5: "deauthorizing moves the obligation `AUTHORIZED →
        SCHEDULED`, subtracts its `authorized_amount_cents` from the family's
        `committed_forecast_cents`, clears `authorized_amount_cents` back to
        null, and supersedes the current authorization whether it was
        `APPROVED` or `RELEASED` (→ `SUPERSEDED`)."

        Design: Difficulty/compensating_invariant/authorize_deauthorize_conserves_committed_money
        """
        world = setup_world_with_granted_app(client_name="InvCo")
        family_id = world["family"]["id"]
        obligation = world["obligations"][0]
        assert get_family(family_id)["committed_forecast_cents"] == 0
        au = authorize_obligation(obligation["id"], 10000, world["contact"]["id"])
        assert get_family(family_id)["committed_forecast_cents"] == 10000
        data = validate_success(api_client.deauthorize_obligation(obligation["id"], MGR), 200)
        assert data["status"] == "SCHEDULED"
        assert data["authorized_amount_cents"] is None
        assert get_family(family_id)["committed_forecast_cents"] == 0
        assert validate_success(api_client.get_authorization(au["id"], ANY), 200)["status"] == "SUPERSEDED"

    def test_deauthorize_moves_committed_forecast_variant_in_lockstep(self):
        """PRD §3.9: "Under `variant` value `COMMITTED`, obligations in
        `AUTHORIZED`, `PAYMENT_INSTRUCTED`, or `CONFIRMATION_QUERY` contribute
        their `authorized_amount_cents`"; PRD §3.5: "deauthorizing moves the obligation `AUTHORIZED →
        SCHEDULED`, subtracts its `authorized_amount_cents` from the
        family's `committed_forecast_cents`, clears
        `authorized_amount_cents` back to null, and supersedes the
        current authorization whether it was `APPROVED` or `RELEASED`
        (→ `SUPERSEDED`)".

        Design: Difficulty/compensating_invariant/authorize_deauthorize_conserves_committed_money
        """
        world = setup_world_with_granted_app(client_name="InvCo")
        family_id = world["family"]["id"]
        obligation = world["obligations"][0]
        au = authorize_obligation(obligation["id"], 10000, world["contact"]["id"])
        committed = api_client.get_budget_forecast(family_id, ANY, params={"variant": "COMMITTED"})
        assert validate_success(committed, 200)["total_usd_cents"] == 10000
        validate_success(api_client.deauthorize_obligation(obligation["id"], MGR), 200)
        committed = api_client.get_budget_forecast(family_id, ANY, params={"variant": "COMMITTED"})
        assert validate_success(committed, 200)["total_usd_cents"] == 0
        assert validate_success(api_client.get_authorization(au["id"], ANY), 200)["status"] == "SUPERSEDED"


class TestAuthorizationReleaseGate:
    def test_release_on_requested_authorization_rejected(self):
        """PRD §3.5: "A `FinanceOfficer` releases an `APPROVED` authorization,
        moving it to `RELEASED`." PRD §2.9: "an undefined transition is
        rejected with `ERR_INVALID_STATE`, and any transition attempted on
        a resource already in a terminal state is rejected with
        `ERR_ALREADY_TERMINAL`."

        Design: Corner/validations/authorization_release_requires_approved_state
        """
        world = setup_world_with_granted_app(client_name="RelCo")
        obligation = world["obligations"][0]
        au, _ = request_authorization(obligation["id"], 10000, requester_headers=FIN)
        resp = api_client.release_authorization(au["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

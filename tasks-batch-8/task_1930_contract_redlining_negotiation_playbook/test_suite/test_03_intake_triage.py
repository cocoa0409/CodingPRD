"""Intake submission, value tiering, triage routing, and negotiation opening."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, validate_paginated,
    get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    create_intake_request_payload, create_open_negotiation_payload,
    create_counterparty_payload,
    assert_intake_request, assert_triage_decision, assert_negotiation,
    setup_user_directory, headers_by_id,
    create_standard_contract_type, create_standard_counterparty,
    create_active_playbook,
    set_logical_clock, submit_intake, triage_intake, submit_and_triage,
    open_negotiation_from_intake, setup_negotiation_ctx,
)


def _base_refs():
    """Users + contract type + counterparty for intake-focused tests."""
    set_logical_clock()
    users = setup_user_directory()
    hdrs = headers_by_id(users)
    ct = create_standard_contract_type(users)
    cp = create_standard_counterparty()
    return users, hdrs, ct, cp


class TestIntakeCreation:
    def test_intake_created_in_pending_triage(self, api):
        """A new intake request lands in PENDING_TRIAGE with null computed fields.

        PRD §3.3: "The new request lands in `PENDING_TRIAGE` with its computed fields —
        `routing_bucket`, `assigned_owner_id`, `assigned_legal_id`, and
        `triage_decision_id` — still null."

        Design: Corner/state_machines/intake_request_initial_state_is_pending_triage
        """
        users, hdrs, ct, cp = _base_refs()
        intake = submit_intake(users, ct, cp, 1_000)
        assert_intake_request(intake)
        assert intake["status"] == "PENDING_TRIAGE"
        assert intake["routing_bucket"] is None
        assert intake["assigned_owner_id"] is None
        assert intake["assigned_legal_id"] is None
        assert intake["triage_decision_id"] is None

    def test_intake_with_unknown_contract_type_rejected(self, api):
        """A body-referenced foreign key that does not resolve yields 422.

        PRD §3.3: "Every referenced foreign key must resolve (`ERR_FOREIGN_KEY_NOT_FOUND`)."

        Design: Corner/entities/intake_request_invalid_contract_type_fk_returns_422
        """
        users, hdrs, ct, cp = _base_refs()
        payload = create_intake_request_payload(
            users["ca"]["id"], NON_EXISTENT_UUID, cp["id"], contract_value_cents=1_000)
        resp = api.create_intake_request(payload, hdrs[users["ca"]["id"]])
        validate_error(resp, ApiErrorId.ERR_FOREIGN_KEY_NOT_FOUND)
        assert resp.status_code == 422


class TestTriageGuards:
    def test_sanctioned_counterparty_blocks_triage(self, api):
        """Triage refuses a SANCTIONED counterparty outright.

        PRD §3.3: "the counterparty must not be `SANCTIONED` — a sanctioned counterparty
        is refused outright with `ERR_COUNTERPARTY_SANCTIONED` (HTTP 409), and this
        refusal is evaluated ahead of the generic state check so it is never masked
        by one."

        Design: Corner/validations/sanctioned_counterparty_blocks_triage
        """
        users, hdrs, ct, _ = _base_refs()
        sanctioned = get_success_data(api.create_counterparty(
            create_counterparty_payload(legal_name="BadActor", jurisdiction="XX",
                                        risk_tier="SANCTIONED"), hdrs[users["ca"]["id"]]))
        intake = submit_intake(users, ct, sanctioned, 1_000)

        resp = api.triage_intake_request(intake["id"], {}, hdrs[users["ca"]["id"]])
        validate_error(resp, ApiErrorId.ERR_COUNTERPARTY_SANCTIONED)
        assert resp.status_code == 409


class TestValueTierBoundaries:
    def test_value_at_low_threshold_tiers_low(self, api):
        """A value exactly at low_value_threshold_cents belongs to LOW (inclusive).

        PRD §2.6: "Value-tier boundaries are inclusive on the upper bound of each tier
        and exclusive on the lower bound of the next: a contract valued exactly at a
        tier's threshold belongs to that tier."
        PRD §3.3: "a value at or below `low_value_threshold_cents` is tier `LOW`".

        Design: Difficulty/boundary_precision_check/contract_value_tier_boundary_inclusive_low
        """
        users, hdrs, ct, cp = _base_refs()
        intake = submit_intake(users, ct, cp, 100_000)  # == low_value_threshold_cents
        triage_intake(intake["id"], hdrs[users["ca"]["id"]])

        decisions, _ = validate_paginated(
            api.list_triage_decisions(intake["id"], hdrs[users["ca"]["id"]]))
        assert len(decisions) == 1
        assert_triage_decision(decisions[0])
        assert decisions[0]["value_tier"] == "LOW", (
            f"value at the inclusive upper bound must tier LOW, got {decisions[0]['value_tier']}")

    def test_value_one_cent_above_low_threshold_tiers_mid(self, api):
        """A value one cent above low_value_threshold_cents tiers MID.

        PRD §3.3: "a value at or below `low_value_threshold_cents` is tier `LOW`;
        otherwise a value at or below `mid_value_threshold_cents` is `MID`".

        Design: Difficulty/boundary_precision_check/contract_value_tier_boundary_inclusive_low
        """
        users, hdrs, ct, cp = _base_refs()
        intake = submit_intake(users, ct, cp, 100_001)  # low + 1
        triage_intake(intake["id"], hdrs[users["ca"]["id"]])

        decisions, _ = validate_paginated(
            api.list_triage_decisions(intake["id"], hdrs[users["ca"]["id"]]))
        assert decisions[0]["value_tier"] == "MID", (
            f"value one cent above the low bound must tier MID, got {decisions[0]['value_tier']}")

    def test_value_above_high_threshold_tiers_very_high(self, api):
        """Anything above all three thresholds is VERY_HIGH.

        PRD §3.3: "otherwise a value at or below `high_value_threshold_cents` is `HIGH`;
        anything above all three is `VERY_HIGH`."

        Design: Corner/calculations/value_tier_very_high_above_high_threshold
        """
        users, hdrs, ct, cp = _base_refs()
        intake = submit_intake(users, ct, cp, 2_000_001)  # > high_value_threshold_cents
        triage_intake(intake["id"], hdrs[users["ca"]["id"]])

        decisions, _ = validate_paginated(
            api.list_triage_decisions(intake["id"], hdrs[users["ca"]["id"]]))
        assert decisions[0]["value_tier"] == "VERY_HIGH"


class TestSystemTriageRouting:
    def test_low_value_under_auto_approve_routes_self_serve(self, api):
        """The system variant routes a LOW-tier intake below the auto-approve
        threshold to SELF_SERVE, and the intake absorbs the outcome.

        PRD §3.3: "A `LOW` tier whose value is strictly less than the contract type's
        `auto_approve_below_cents` routes to `SELF_SERVE`."
        PRD §3.3: "its `routing_bucket` copies the decision's, `assigned_owner_id`
        becomes the contract type's `default_business_owner_id`, `assigned_legal_id`
        becomes its `default_legal_counsel_id`, `triage_decision_id` points at the new
        decision record, and the status advances `PENDING_TRIAGE → ROUTED`."

        Design: Difficulty/dual_variant_calc/routing_bucket_system_vs_analyst_override
        """
        users, hdrs, ct, cp = _base_refs()
        intake = submit_intake(users, ct, cp, 40_000)  # LOW tier, 40000 < 50000 auto-approve
        routed = triage_intake(intake["id"], hdrs[users["ca"]["id"]])

        assert routed["status"] == "ROUTED"
        assert routed["routing_bucket"] == "SELF_SERVE", (
            f"expected SELF_SERVE, got {routed['routing_bucket']}")
        assert routed["assigned_owner_id"] == users["bo"]["id"]
        assert routed["assigned_legal_id"] == users["lc"]["id"]
        assert routed["triage_decision_id"] is not None

    def test_system_triage_decision_records_system_derivation(self, api):
        """A straight computation persists a TriageDecision with decided_by SYSTEM
        and a snapshot of tier and counterparty risk.

        PRD §3.3: "`decided_by` — `SYSTEM` for a straight computation or
        `ANALYST_OVERRIDE` when the override was used."
        PRD §3.3: "Every triage run persists an append-only `TriageDecision` capturing
        the intake request's `intake_request_id`, the `decided_at` timestamp, the
        computed `routing_bucket` and `value_tier`, a `counterparty_risk` snapshot of
        the counterparty's tier at decision time".

        Design: Difficulty/dual_variant_calc/routing_bucket_system_vs_analyst_override
        """
        users, hdrs, ct, cp = _base_refs()
        intake = submit_intake(users, ct, cp, 40_000)
        routed = triage_intake(intake["id"], hdrs[users["ca"]["id"]])

        decisions, _ = validate_paginated(
            api.list_triage_decisions(intake["id"], hdrs[users["ca"]["id"]]))
        assert len(decisions) == 1
        decision = decisions[0]
        assert_triage_decision(decision)
        assert decision["id"] == routed["triage_decision_id"]
        assert decision["decided_by"] == "SYSTEM"
        assert decision["value_tier"] == "LOW"
        assert decision["routing_bucket"] == "SELF_SERVE"
        assert decision["counterparty_risk"] == "STANDARD"


class TestOpenNegotiationRbacAndOcc:
    def _routed_with_playbook(self):
        users, hdrs, ct, cp = _base_refs()
        playbook, clauses = create_active_playbook(hdrs[users["cc"]["id"]])
        intake = submit_and_triage(users, ct, cp, 1_000)
        return users, hdrs, ct, cp, playbook, intake

    def test_business_owner_cannot_open_negotiation(self, api):
        """open-negotiation is restricted to ContractAnalyst; a BusinessOwner is
        refused at the role gate.

        PRD §2.1: "A caller whose role is not permitted on the target endpoint is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/intake-requests/{intakeRequestId}/open-negotiation` |
        Open a Negotiation from a `ROUTED` intake | ContractAnalyst |"

        Design: Corner/roles/business_owner_cannot_open_negotiation
        """
        users, hdrs, ct, cp, playbook, intake = self._routed_with_playbook()
        payload = create_open_negotiation_payload(
            playbook["id"], users["bo"]["id"], intake["version"])
        resp = api.open_negotiation(intake["id"], payload, hdrs[users["bo"]["id"]])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert resp.status_code == 403

    def test_second_open_negotiation_with_stale_version_rejected(self, api):
        """A second open-negotiation carrying the pre-open intake version fails.
        PRD §2.7 names this scenario ERR_STALE_VERSION while §3.4 runs the
        ROUTED-state guard first, so either error id satisfies the contract.

        PRD §2.7: "If the intake request's current `version` has moved past the
        supplied value — because another writer cancelled it or already opened the
        negotiation — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)".
        PRD §3.4: "The guards run in a fixed order: the intake must currently be
        `ROUTED` (`ERR_INVALID_STATE_TRANSITION`), the referenced playbook must be
        `ACTIVE` (`ERR_PLAYBOOK_NOT_ACTIVE`), and the supplied version must match the
        intake request's current `version` (`ERR_STALE_VERSION`, HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_open_negotiation
        """
        users, hdrs, ct, cp, playbook, intake = self._routed_with_playbook()
        payload = create_open_negotiation_payload(
            playbook["id"], users["ca"]["id"], intake["version"])
        first = api.open_negotiation(intake["id"], payload, hdrs[users["ca"]["id"]])
        negotiation = validate_success(first, expected_status=201)
        assert_negotiation(negotiation)

        # Second call replays the now-stale expected version.
        second = api.open_negotiation(intake["id"], payload, hdrs[users["ca"]["id"]])
        assert second.status_code in (409, 412), (
            f"expected a 4xx conflict, got {second.status_code}: {second.text}")
        validate_error_is_one_of(second, [
            ApiErrorId.ERR_STALE_VERSION, ApiErrorId.ERR_INVALID_STATE_TRANSITION])

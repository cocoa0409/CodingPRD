"""Certification lifecycle: issuance, activation gates, suspension cycles,
renewal windows and pinned evaluation order, revocation lockdown."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_active_evaluator,
    create_active_handler,
    create_forming_team,
    get_certification,
    get_team,
    issue_certification,
    record_rabies,
    register_animal,
    request_evaluation,
    run_sweeps,
    schedule_evaluation_ok,
    score_evaluation_ok,
    set_clock,
    setup_certified_team,
    setup_renewable_certification,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _team_with_passed_evaluation(name: str):
    """Handler + animal + FORMING team + PASSED evaluation (attempt 1)."""
    handler = create_active_handler(full_name=name)
    animal = register_animal(handler["id"], name="D")
    team = create_forming_team(handler["id"], animal["id"], f"{name} Team")
    evaluation = request_evaluation(handler["id"], team["id"])
    evaluator = create_active_evaluator(full_name=f"Ev {name}", specializations=["DOG"])
    schedule_evaluation_ok(evaluation["id"], evaluator["id"])
    evaluation = score_evaluation_ok(evaluation["id"], evaluator["id"], 80, 70)
    return handler, animal, team, evaluation


class TestCertificationIssuance:
    def test_second_certification_for_team_rejected(self):
        """PRD §3.3: "A `ProgramAdmin` issues a certification with a payload naming the `team_id` and the `evaluation_id`; the team must be `FORMING` (`ERR_TEAM_NOT_FORMING`), the referenced evaluation must be `PASSED` (`ERR_EVALUATION_NOT_PASSED`) and must belong to that same team (`ERR_EVALUATION_TEAM_MISMATCH`), and the team must not already hold a certification in `PROVISIONAL`, `ACTIVE`, `RENEWAL_DUE`, or `SUSPENDED` (`ERR_ACTIVE_CERTIFICATION_EXISTS`)."

        Design: Corner/errors/second_certification_for_team_rejected
        """
        _h, _a, team, evaluation = _team_with_passed_evaluation("H 2C")
        issue_certification(team["id"], evaluation["id"])
        resp = api_client.create_certification(
            {"team_id": team["id"], "evaluation_id": evaluation["id"]}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_CERTIFICATION_EXISTS)


class TestSuspendReinstateCycle:
    def test_suspend_drops_team_in_step(self):
        """PRD §3.3: "Suspension cascades immediately: the team drops `ACTIVE → SUSPENDED`; every `SCHEDULED` visit of the team is cancelled with `cancel_reason` `CERT_SUSPENDED`; each cancelled visit decrements the animal's `forward_workload_minutes`; and request-backed cancelled visits return their visit requests to `OPEN` with offer fields cleared."
        PRD §2.8: "a certification's activation lifts its team from `FORMING` to `ACTIVE` and the animal from `REGISTERED` to `ACTIVE`; certification suspension and reinstatement lower and restore the team's status in step"

        Design: Difficulty/non_linear_state_machine/certification_suspend_reinstate_cycle
        """
        ctx = setup_certified_team(handler_name="H C", team_name="TC")
        suspended = validate_success(
            api_client.suspend_certification(
                ctx["certification"]["id"], {"reason": "manual review"}, COMPLIANCE
            )
        )
        assert suspended["status"] == "SUSPENDED"
        team = get_team(ctx["team"]["id"])
        assert team["status"] == "SUSPENDED", (
            f"Team must drop in step with its certification, got {team['status']}"
        )

    def test_reinstate_closes_cycle_without_extending_term(self):
        """PRD §3.3: "Reinstatement clears `suspension_reason` and `suspension_until` and bubbles the team `SUSPENDED → ACTIVE`; `expires_on` is unchanged — a suspension never extends the certification term."
        PRD §3.3: "Activation stamps `activated_on` with today and `expires_on` with today plus seven hundred thirty days, and bubbles the team `FORMING → ACTIVE` and the animal `REGISTERED → ACTIVE`."

        Design: Difficulty/non_linear_state_machine/certification_suspend_reinstate_cycle
        """
        ctx = setup_certified_team(handler_name="H C", team_name="TC")
        cert_id = ctx["certification"]["id"]
        # Activated on 2026-08-02 -> expires_on 2028-08-01 (today + 730 days).
        assert ctx["certification"]["expires_on"] == "2028-08-01"
        validate_success(
            api_client.suspend_certification(cert_id, {"reason": "manual review"}, COMPLIANCE)
        )
        reinstated = validate_success(api_client.reinstate_certification(cert_id, COMPLIANCE))
        assert reinstated["status"] == "ACTIVE", "The cycle must close back to ACTIVE"
        assert reinstated["expires_on"] == "2028-08-01", (
            f"expires_on must not be extended by the suspension cycle, got {reinstated['expires_on']}"
        )
        assert reinstated["suspension_reason"] is None, "suspension_reason must be cleared"
        team = get_team(ctx["team"]["id"])
        assert team["status"] == "ACTIVE"


class TestRenewalOrderOfOperations:
    def test_renewal_extends_from_old_expiry(self):
        """PRD §3.3: "The computation order is pinned to break the apparent circularity: first the eligibility visits are counted against the old expiry date; then the new `expires_on` is set to the later of today and the old expiry, plus seven hundred thirty days — an on-time renewal therefore extends from the old expiry and loses no days, while a late renewal extends from today; finally `renewal_count` increments by one."

        Design: Difficulty/combinatorial_formula/renewal_order_of_operations_pinned
        """
        ctx = setup_renewable_certification()
        cert_id = ctx["certification"]["id"]
        # Activated 2026-08-02 -> expires_on 2028-08-01; renew 30 days early.
        set_clock("2028-07-02T00:00:00Z")
        run_sweeps()
        renewed = validate_success(api_client.renew_certification(cert_id, ADMIN))
        assert renewed["status"] == "ACTIVE"
        assert renewed["renewal_count"] == 1
        # max(2028-07-02, 2028-08-01) + 730 days = 2030-08-01 (old-expiry-based;
        # a today-based formula would wrongly give 2030-07-02).
        assert renewed["expires_on"] == "2030-08-01", (
            f"On-time renewal must extend from the OLD expiry, got {renewed['expires_on']}"
        )

    def test_renewal_due_sweep_marks_certification(self):
        """PRD §3.3: "A sweep moves an `ACTIVE` certification to `RENEWAL_DUE` once today enters the window from sixty days before `expires_on` through `expires_on` itself; once today passes `expires_on`, both `ACTIVE` and `RENEWAL_DUE` certifications move to `EXPIRED`."
        PRD §3.3: "Renewal re-checks the rabies gate and the program insurance floor of one hundred million cents, and it enforces an experience requirement: the team must have at least six visits in `COMPLETED` with `VERIFIED` verification whose `actual_end` dates fall within the span from `activated_on` through the pre-renewal `expires_on` (`ERR_RENEWAL_VISIT_MINIMUM_NOT_MET`)."

        Design: Difficulty/combinatorial_formula/renewal_order_of_operations_pinned
        """
        ctx = setup_renewable_certification()
        cert_id = ctx["certification"]["id"]
        set_clock("2028-07-02T00:00:00Z")
        sweep = run_sweeps()
        # 2028-07-02 >= 2028-08-01 - 60 days (2028-06-02): inside the renewal window.
        assert sweep["certifications_marked_renewal_due"] == 1
        cert = get_certification(cert_id)
        assert cert["status"] == "RENEWAL_DUE"
        # The six visits completed+verified inside [activated_on, old expires_on]
        # satisfy the eligibility minimum, so renewal succeeds.
        renewed = validate_success(api_client.renew_certification(cert_id, ADMIN))
        assert renewed["status"] == "ACTIVE"
        assert renewed["renewal_count"] == 1


class TestRenewalSafetyGate:
    def _setup_lapsed_rabies(self):
        ctx = setup_certified_team(
            handler_name="H X2", team_name="TX2", rabies_until="2027-06-30",
        )
        set_clock("2028-07-02T00:00:00Z")
        run_sweeps()
        return ctx

    def test_renewal_requires_valid_rabies(self):
        """PRD §3.3: "Renewal re-checks the rabies gate and the program insurance floor of one hundred million cents, and it enforces an experience requirement: the team must have at least six visits in `COMPLETED` with `VERIFIED` verification whose `actual_end` dates fall within the span from `activated_on` through the pre-renewal `expires_on` (`ERR_RENEWAL_VISIT_MINIMUM_NOT_MET`)."
        PRD §3.3: "The rabies gate used throughout this document asks for a `RABIES` record in `VALID` status whose `valid_until` covers the relevant date: when no rabies record exists for the animal at all, the rejection is `ERR_VACCINATION_MISSING`; when records exist but none covers the date — including a record whose validity has lapsed whether or not the sweep has yet marked it `EXPIRED` — the rejection is `ERR_VACCINATION_EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/renewal_requires_valid_rabies
        """
        ctx = self._setup_lapsed_rabies()
        resp = api_client.renew_certification(ctx["certification"]["id"], ADMIN)
        # Rabies valid_until 2027-06-30 < today 2028-07-02 -> lapsed record.
        validate_error(resp, ApiErrorId.ERR_VACCINATION_EXPIRED)

    def test_fresh_rabies_advances_renewal_to_next_gate(self):
        """PRD §3.3: "Renewal re-checks the rabies gate and the program insurance floor of one hundred million cents, and it enforces an experience requirement: the team must have at least six visits in `COMPLETED` with `VERIFIED` verification whose `actual_end` dates fall within the span from `activated_on` through the pre-renewal `expires_on` (`ERR_RENEWAL_VISIT_MINIMUM_NOT_MET`)."
        PRD §3.3: "The rabies gate used throughout this document asks for a `RABIES` record in `VALID` status whose `valid_until` covers the relevant date: when no rabies record exists for the animal at all, the rejection is `ERR_VACCINATION_MISSING`; when records exist but none covers the date — including a record whose validity has lapsed whether or not the sweep has yet marked it `EXPIRED` — the rejection is `ERR_VACCINATION_EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/renewal_requires_valid_rabies
        """
        ctx = self._setup_lapsed_rabies()
        record_rabies(ctx["handler"]["id"], ctx["animal"]["id"],
                      valid_until="2031-06-30", administered_on="2028-07-01")
        resp = api_client.renew_certification(ctx["certification"]["id"], ADMIN)
        # The rabies gate now passes; the failure advances to the visit-count
        # constraint (zero verified visits), proving the cross-entity gate moved.
        validate_error(resp, ApiErrorId.ERR_RENEWAL_VISIT_MINIMUM_NOT_MET)


class TestRenewalPriorityAndWindow:
    def test_safety_beats_fiscal_on_renewal(self):
        """PRD §2.7: "Every request is evaluated against a fixed pipeline of check categories, in the order below, and the first category that fails determines the rejection. The ordering is load-bearing: an authentication failure masks everything downstream; a stale-version rejection surfaces before any state-machine precondition is examined; a segregation-of-duties violation is reported only after every other check has passed."
        PRD §2.7: "8. **Animal welfare and biosafety.** The animal is not in `WELFARE_HOLD` (`ERR_ANIMAL_WELFARE_HOLD`), its rest block is satisfied (`ERR_ANIMAL_REST_PERIOD`), the forward workload ceiling holds (`ERR_WORKLOAD_LIMIT_EXCEEDED`), the daily visit limit holds (`ERR_DAILY_VISIT_LIMIT_EXCEEDED`), the species is admitted at the facility (`ERR_SPECIES_NOT_PERMITTED`), and a valid rabies vaccination covers the relevant date (`ERR_VACCINATION_MISSING` / `ERR_VACCINATION_EXPIRED`) — all HTTP 403. Applies to visit scheduling, offer acceptance, certification activation, renewal, and reinstatement, and to visit check-in (hold check only)."
        PRD §2.7: "11. **Fiscal adequacy.** An `ACTIVE` insurance policy covering today exists (`ERR_NO_ACTIVE_INSURANCE`) and its coverage meets the applicable requirement (`ERR_INSURANCE_COVERAGE_INADEQUATE`) — both HTTP 402. Applies to visit scheduling, offer acceptance, certification activation, renewal, and reinstatement, and candidate-team eligibility."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_renewal
        """
        ctx = setup_certified_team(
            handler_name="H T", team_name="TT",
            rabies_until="2027-06-30", policy_until="2027-01-01",
        )
        set_clock("2028-07-02T00:00:00Z")
        run_sweeps()
        # Both the rabies record (safety, category 8) and the policy (fiscal,
        # category 11) have lapsed; the safety rejection must surface.
        resp = api_client.renew_certification(ctx["certification"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_VACCINATION_EXPIRED)

    def test_fiscal_failure_isolated_on_renewal(self):
        """PRD §3.3: "Renewal re-checks the rabies gate and the program insurance floor of one hundred million cents, and it enforces an experience requirement: the team must have at least six visits in `COMPLETED` with `VERIFIED` verification whose `actual_end` dates fall within the span from `activated_on` through the pre-renewal `expires_on` (`ERR_RENEWAL_VISIT_MINIMUM_NOT_MET`)."
        PRD §3.5: "When no `ACTIVE` policy covers today the rejection is `ERR_NO_ACTIVE_INSURANCE`; when one exists but falls short it is `ERR_INSURANCE_COVERAGE_INADEQUATE`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_renewal
        """
        ctx = setup_certified_team(
            handler_name="H Tf", team_name="TTf",
            rabies_until="2031-12-31", policy_until="2027-01-01",
        )
        set_clock("2028-07-02T00:00:00Z")
        run_sweeps()
        # Rabies still VALID; only the fiscal gate (no ACTIVE policy) can fail.
        resp = api_client.renew_certification(ctx["certification"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_INSURANCE)

    def test_renewal_window_closed_after_grace(self):
        """PRD §3.3: "A `ProgramAdmin` renews from `RENEWAL_DUE` or `EXPIRED` (otherwise `ERR_CERT_NOT_RENEWABLE`), but a lapsed certification may only be renewed while today is within ninety days past `expires_on` inclusive — beyond that the window is closed (`ERR_RENEWAL_WINDOW_CLOSED`)."

        Design: Corner/errors/renewal_window_closed_after_grace
        """
        ctx = setup_certified_team(
            handler_name="H RW", team_name="TRW",
            rabies_until="2031-12-31", policy_until="2031-12-31",
        )
        # expires_on = 2028-08-01; grace ends 2028-10-30; today 2028-11-01 is past it.
        set_clock("2028-11-01T00:00:00Z")
        run_sweeps()
        resp = api_client.renew_certification(ctx["certification"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)


class TestRevocationLockdown:
    def test_revoked_certification_terminal_lockdown(self):
        """PRD §3.3: "Revocation is terminal. A `ComplianceOfficer` revokes from `ACTIVE`, `RENEWAL_DUE`, or `SUSPENDED` (otherwise `ERR_CERT_NOT_REVOKABLE`) with a `reason`, and an incident resolved as `REVOCATION` revokes automatically (§3.9). Revocation dissolves the team, cancels every remaining `SCHEDULED` visit with `cancel_reason` `CERT_REVOKED`, and returns request-backed visits' requests to `OPEN`."
        PRD §3.3: "A `ProgramAdmin` renews from `RENEWAL_DUE` or `EXPIRED` (otherwise `ERR_CERT_NOT_RENEWABLE`), but a lapsed certification may only be renewed while today is within ninety days past `expires_on` inclusive — beyond that the window is closed (`ERR_RENEWAL_WINDOW_CLOSED`)."
        PRD §3.3: "A `ComplianceOfficer` reinstates a `SUSPENDED` certification (otherwise `ERR_CERT_NOT_SUSPENDED`) only once `suspension_until` is null or has been reached (a future `suspension_until` fails with `ERR_SUSPENSION_NOT_ELAPSED`), and only after re-passing the rabies gate (`ERR_VACCINATION_EXPIRED`) and the insurance floor (`ERR_INSURANCE_COVERAGE_INADEQUATE`) against today."

        Design: Corner/state_machines/revoked_certification_terminal_lockdown
        """
        ctx = setup_certified_team(handler_name="H RT", team_name="TRT")
        cert_id = ctx["certification"]["id"]
        revoked = validate_success(
            api_client.revoke_certification(cert_id, {"reason": "fraudulent records"}, COMPLIANCE)
        )
        assert revoked["status"] == "REVOKED"
        team = get_team(ctx["team"]["id"])
        assert team["status"] == "DISSOLVED", "Revocation must dissolve the team"
        renew_resp = api_client.renew_certification(cert_id, ADMIN)
        validate_error(renew_resp, ApiErrorId.ERR_CERT_NOT_RENEWABLE)
        reinstate_resp = api_client.reinstate_certification(cert_id, COMPLIANCE)
        validate_error(reinstate_resp, ApiErrorId.ERR_CERT_NOT_SUSPENDED)

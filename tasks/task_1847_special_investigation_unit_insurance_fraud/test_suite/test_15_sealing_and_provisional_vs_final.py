"""Substantiated fraud running-total vs post-seal final total (dual variant)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_manager_headers,
    create_adjuster, create_investigator, create_claim, create_referral,
    triage_referral, accept_referral, open_case, assign_investigator,
    log_evidence, submit_evidence_review, admit_evidence,
    setup_case_decision_pending,
)
from test_helpers.api_client import api_client


class TestSubstantiatedRunningVsFinal:
    """Difficulty/dual_variant_calc/substantiated_fraud_provisional_running_vs_final_sealed"""

    def _setup_closed_case_with_two_substantive(self, api):
        """Close a case SUBSTANTIATED with two admitted SUBSTANTIVE items totaling
        35,000,000 cents (E1=20,000,000 + E2=15,000,000)."""
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        inv, ih = create_investigator(manager_headers=mh)
        claim = create_claim(adj, state_code="CA", claimed_amount_cents=100_000_000)
        ref = create_referral(claim, red_flag_codes=["PRIOR_FRAUD_CONVICTION"],
                              headers=ah)
        triage_referral(ref, manager_headers=mh)
        case = accept_referral(ref, manager_headers=mh)
        case = open_case(case, manager_headers=mh)
        asg, case = assign_investigator(case, inv, manager_headers=mh)
        ev1 = log_evidence(case, inv, evidence_type="RECORDS",
                           materiality="SUBSTANTIVE", fraud_amount_cents=20_000_000,
                           collected_at="2026-08-10T00:00:00Z")
        ev1 = submit_evidence_review(case, ev1, inv)
        ev1, case = admit_evidence(case, ev1, case["version"], manager_headers=mh)
        ev2 = log_evidence(case, inv, evidence_type="SURVEILLANCE",
                           materiality="SUBSTANTIVE", fraud_amount_cents=15_000_000,
                           collected_at="2026-08-11T00:00:00Z")
        ev2 = submit_evidence_review(case, ev2, inv)
        ev2, case = admit_evidence(case, ev2, case["version"], manager_headers=mh)
        case = get_success_data(api_client.submit_case_for_decision(case["id"], ih))
        case = validate_success(api_client.close_case(
            case["id"], {"closed_reason": "SUBSTANTIATED"}, mh))
        return {"manager_headers": mh, "investigator": inv, "claim": claim,
                "case": case, "ev1": ev1, "ev2": ev2}

    def test_running_total_at_admit_equals_sum_of_admitted_substantive(self, api):
        """PRD §3.4: "That running total is exactly the sum of `fraud_amount_cents`
        over the case's evidence that is both `ADMITTED` and `SUBSTANTIVE`:
        admissions while the case is open or under investigation update the running
        figure without gating anything"

        Design: Difficulty/dual_variant_calc/substantiated_fraud_provisional_running_vs_final_sealed
        """
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        inv, ih = create_investigator(manager_headers=mh)
        claim = create_claim(adj, state_code="CA", claimed_amount_cents=100_000_000)
        ref = create_referral(claim, red_flag_codes=["PRIOR_FRAUD_CONVICTION"],
                              headers=ah)
        triage_referral(ref, manager_headers=mh)
        case = accept_referral(ref, manager_headers=mh)
        case = open_case(case, manager_headers=mh)
        asg, case = assign_investigator(case, inv, manager_headers=mh)
        ev1 = log_evidence(case, inv, evidence_type="RECORDS",
                           materiality="SUBSTANTIVE", fraud_amount_cents=20_000_000,
                           collected_at="2026-08-10T00:00:00Z")
        ev1 = submit_evidence_review(case, ev1, inv)
        ev1, case = admit_evidence(case, ev1, case["version"], manager_headers=mh)
        assert case["substantiated_fraud_cents"] == 20_000_000
        ev2 = log_evidence(case, inv, evidence_type="SURVEILLANCE",
                           materiality="SUBSTANTIVE", fraud_amount_cents=15_000_000,
                           collected_at="2026-08-11T00:00:00Z")
        ev2 = submit_evidence_review(case, ev2, inv)
        ev2, case = admit_evidence(case, ev2, case["version"], manager_headers=mh)
        assert case["substantiated_fraud_cents"] == 35_000_000

    def test_seal_after_close_subtracts_from_total_and_ledger_stays_locked(self, api):
        """PRD §3.4: "Sealed evidence is immutable and is excluded from any future
        recomputation of `substantiated_fraud_cents` — in effect its amount is
        subtracted from the total."
        PRD §3.6: "a restitution ledger is auto-created in `OPEN` with
        `target_amount_cents` locked to the substantiated total at closure"

        Design: Difficulty/dual_variant_calc/substantiated_fraud_provisional_running_vs_final_sealed
        """
        ctx = self._setup_closed_case_with_two_substantive(api)
        mh = ctx["manager_headers"]
        case = ctx["case"]
        # Pre-seal substantiated total was 35,000,000 (running variant)
        # Seal ev1 (20,000,000)
        resp = api_client.seal_evidence(case["id"], ctx["ev1"]["id"], mh)
        validate_success(resp)
        fresh = get_success_data(api_client.get_case(case["id"], mh))
        # Final-at-close variant: sealed evidence subtracts from total
        assert fresh["substantiated_fraud_cents"] == 15_000_000, \
            f"after sealing 20M from 35M expected 15M, got {fresh['substantiated_fraud_cents']}"
        # Ledger target stays locked at closure snapshot
        ledgers = get_success_data(api_client.list_case_ledgers(case["id"], mh))
        assert ledgers[0]["target_amount_cents"] == 35_000_000


class TestStateVsSegregationPriority:
    """Difficulty/priority_pair_validation_conflict/state_vs_business_safety_segregation"""

    def test_admit_in_decision_pending_yields_invalid_state_not_sod(self, api):
        """PRD §2.6: "When several checks would fail on the same request, the
        response carries the error produced by the earliest check in the sequence"
        PRD §2.6 step 5: "Target state — a failing state-machine precondition on
        the addressed resource yields `ERR_INVALID_STATE`."
        PRD §2.6 worked example: "had the state been valid but the manager the
        same user who logged the evidence, `ERR_SEGREGATION_OF_DUTIES` would
        surface instead of the stale-version error."
        (The state check at step 5 outranks the step-7 SoD check.)

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_segregation
        """
        # Build DECISION_PENDING case; evidence left UNDER_REVIEW from before
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        inv, ih = create_investigator(manager_headers=mh)
        claim = create_claim(adj, state_code="CA", claimed_amount_cents=5_000_000)
        ref = create_referral(claim, red_flag_codes=["UNWITNESSED_LOSS"], headers=ah)
        triage_referral(ref, manager_headers=mh)
        case = accept_referral(ref, manager_headers=mh)
        case = open_case(case, manager_headers=mh)
        asg, case = assign_investigator(case, inv, manager_headers=mh)
        # Log + submit evidence, but DON'T admit it yet
        ev = log_evidence(case, inv, evidence_type="STATEMENT",
                          materiality="SUPPORTING", fraud_amount_cents=0,
                          collected_at="2026-08-10T00:00:00Z")
        ev = submit_evidence_review(case, ev, inv)
        # Also admit one supporting evidence so submit-for-decision has 1 ADMITTED
        ev_ok = log_evidence(case, inv, evidence_type="RECORDS",
                             materiality="SUPPORTING", fraud_amount_cents=0,
                             collected_at="2026-08-10T00:00:00Z")
        ev_ok = submit_evidence_review(case, ev_ok, inv)
        ev_ok, case = admit_evidence(case, ev_ok, case["version"], manager_headers=mh)
        # Submit for decision → case DECISION_PENDING
        case = get_success_data(api_client.submit_case_for_decision(case["id"], ih))
        assert case["status"] == "DECISION_PENDING"
        # Manager attempts to admit the still-UNDER_REVIEW evidence, with X-User-ID
        # equal to the investigator's (SoD violation on top of state violation).
        sod_headers = make_manager_headers(user_id=inv["id"])
        resp = api_client.admit_evidence(
            case["id"], ev["id"],
            {"expected_case_version": case["version"]}, sod_headers)
        # Priority 5 (state) beats priority 7 (SoD); the evidence itself is in a
        # valid state, but the case is not in the required state for new admits
        # outside the EUO freeze. The PRD §2.6 ordering groups this under the
        # state/cross-entity-state family, which outranks SoD.
        err = resp.json()["data"]["error_id"]
        assert err in ("ERR_INVALID_STATE", "ERR_CASE_NOT_IN_REQUIRED_STATE"), \
            f"state-class error must outrank SoD, got {err}"
        assert resp.status_code == 409

    def test_admit_with_sod_violation_alone_yields_segregation_error(self, api):
        """PRD §2.7: "A manager may not admit an evidence item that they themselves
        logged; the admission request's `X-User-ID` must differ from the evidence's
        `submitted_by_investigator_id`."
        PRD §2.6 worked example: "had the state been valid but the manager the
        same user who logged the evidence, `ERR_SEGREGATION_OF_DUTIES` would
        surface instead of the stale-version error."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_segregation
        """
        # Valid state path, only SoD fails: state check passes, SoD fires.
        mh = make_manager_headers()
        adj, ah = create_adjuster(manager_headers=mh)
        inv, ih = create_investigator(manager_headers=mh)
        claim = create_claim(adj, state_code="CA", claimed_amount_cents=5_000_000)
        ref = create_referral(claim, red_flag_codes=["UNWITNESSED_LOSS"], headers=ah)
        triage_referral(ref, manager_headers=mh)
        case = accept_referral(ref, manager_headers=mh)
        case = open_case(case, manager_headers=mh)
        asg, case = assign_investigator(case, inv, manager_headers=mh)
        ev = log_evidence(case, inv, evidence_type="STATEMENT",
                          materiality="SUPPORTING", fraud_amount_cents=0,
                          collected_at="2026-08-10T00:00:00Z")
        ev = submit_evidence_review(case, ev, inv)
        # Manager acts with X-User-ID equal to the investigator's user id (SoD).
        sod_headers = make_manager_headers(user_id=inv["id"])
        resp = api_client.admit_evidence(
            case["id"], ev["id"],
            {"expected_case_version": case["version"]}, sod_headers)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

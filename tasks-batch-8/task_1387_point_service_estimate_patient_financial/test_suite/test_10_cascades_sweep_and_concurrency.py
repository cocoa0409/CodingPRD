"""Cancellation cascades, snapshot supersession/staleness, the clock sweep, OCC, and rate windows."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_estimate,
    create_active_plan,
    create_case,
    create_charge_item,
    create_contract_with_rates,
    create_deposit_payload,
    create_draft_plan,
    create_eligibility_snapshot_payload,
    create_estimate,
    create_patient,
    create_snapshot,
    pledge_and_post_deposit,
    present_estimate,
    price_estimate,
    request_and_approve_authorization,
    request_authorization,
    set_clock,
    setup_insured_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COUNSELOR = TEST_USERS["counselor_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


class TestCaseCancellationCascade:
    def test_case_cancel_cascades_all_children(self, api):
        """PRD §3.9: "Cancellation cascades through every child collection:
        estimates in `DRAFT`, `PRICED`, or `PRESENTED` move to `CANCELLED`;
        deposits still `PLEDGED` move to `CANCELLED`; deposits in `POSTED`
        move to `REFUNDED` with the refund computed by the business-day
        schedule of §3.6 under `refund_reason` `SERVICE_CANCELLED`, and the
        case's `deposit_posted_cents` reduced by each refunded deposit's full
        amount; authorizations in `REQUESTED` or `APPEALED` move to
        `WITHDRAWN`; and payment plans in `DRAFT`, `ACTIVE`, or `DEFAULTED`
        move to `CANCELLED`."

        Design: Corner/state_machines/case_cancel_cascades_all_children
        """
        ctx = setup_insured_scenario(mrn="MRN-SM-6")
        case_id = ctx["case"]["id"]
        estimate = price_estimate(ctx["estimate"]["id"])
        assert estimate["status"] == "PRICED"
        dep_posted = pledge_and_post_deposit(case_id, 100000, method="CARD")
        dep_pledged = validate_success(api.create_deposit(
            case_id, create_deposit_payload(amount_cents=50000, method="CASH"),
            COUNSELOR), 201)
        auth = request_authorization(case_id, cpt_codes=("27447",))
        plan = create_draft_plan(case_id, principal_cents=99999,
                                 num_installments=2)

        cancelled = validate_success(api.cancel_case(case_id, SUPERVISOR), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["deposit_posted_cents"] == 0

        est_after = validate_success(api.get_estimate(estimate["id"], SUPERVISOR), 200)
        assert est_after["status"] == "CANCELLED"

        deposits, _m = validate_paginated(api.list_case_deposits(case_id, SUPERVISOR))
        by_id = {d["id"]: d for d in deposits}
        # Thirteen business days before service -> the 100% refund tier.
        assert by_id[dep_posted["id"]]["status"] == "REFUNDED"
        assert by_id[dep_posted["id"]]["refund_amount_cents"] == 100000
        assert by_id[dep_posted["id"]]["refund_reason"] == "SERVICE_CANCELLED"
        assert by_id[dep_pledged["id"]]["status"] == "CANCELLED"

        auths, _m = validate_paginated(
            api.list_case_authorizations(case_id, SUPERVISOR))
        assert auths[0]["id"] == auth["id"]
        assert auths[0]["status"] == "WITHDRAWN"

        plans, _m = validate_paginated(
            api.list_case_payment_plans(case_id, SUPERVISOR))
        assert plans[0]["id"] == plan["id"]
        assert plans[0]["status"] == "CANCELLED"


class TestSnapshotSupersession:
    def test_snapshot_superseded_by_newer_verification(self, api):
        """PRD §3.2: "Only one snapshot per patient-and-payer combination is
        current at a time: creating a snapshot flips any prior `ACTIVE`
        snapshot for the same patient and `payer_code` to `SUPERSEDED`."
        PRD §3.2: "a successful capture stamps `verified_at` with the current
        logical time, marks the snapshot `ACTIVE`, links it to the patient via
        `patient_id`, and increments the patient record's `version` by 1."

        Design: Corner/state_machines/snapshot_superseded_by_newer_verification
        """
        set_clock("2026-08-03T09:00:00Z")
        patient = create_patient(mrn="MRN-SM-7")
        assert patient["version"] == 1
        snap1 = create_snapshot(patient["id"], payer_code="ACME",
                                deductible_met_cents=50000)
        snap2 = create_snapshot(patient["id"], payer_code="ACME",
                                deductible_met_cents=100000,
                                oop_met_cents=100000)
        snap1_after = validate_success(
            api.get_eligibility_snapshot(snap1["id"], REGISTRAR), 200)
        assert snap1_after["status"] == "SUPERSEDED"
        assert snap2["status"] == "ACTIVE"
        active, meta = validate_paginated(api.list_eligibility_snapshots(
            REGISTRAR, params={"patient_id": patient["id"], "status": "ACTIVE"}))
        assert meta["total_count"] == 1, "exactly one ACTIVE snapshot remains"
        assert active[0]["id"] == snap2["id"]
        patient_after = validate_success(api.get_patient(patient["id"], REGISTRAR), 200)
        assert patient_after["version"] == 3, "version advanced 1 per capture"


class TestSnapshotStalenessBoundary:
    def test_snapshot_stale_boundary_30_days(self, api):
        """PRD §3.2: "a snapshot becomes `STALE` when the current logical time
        is strictly later than thirty days after its `verified_at`; at exactly
        the thirty-day mark it is still `ACTIVE`."

        Design: Corner/calculations/snapshot_stale_boundary_30_days
        """
        set_clock("2026-08-03T09:00:00Z")
        patient = create_patient(mrn="MRN-CA-5")
        snapshot = create_snapshot(patient["id"], payer_code="ACME")

        # Exactly verified_at + 30 days: strict-greater boundary not crossed.
        sweep = set_clock("2026-09-02T09:00:00Z")
        assert sweep["staled_snapshots"] == 0
        still_active = validate_success(
            api.get_eligibility_snapshot(snapshot["id"], REGISTRAR), 200)
        assert still_active["status"] == "ACTIVE"

        # One second later: strictly past the TTL.
        sweep2 = set_clock("2026-09-02T09:00:01Z")
        assert sweep2["staled_snapshots"] == 1
        stale = validate_success(
            api.get_eligibility_snapshot(snapshot["id"], REGISTRAR), 200)
        assert stale["status"] == "STALE"


class TestClockSweep:
    def test_clock_sweep_fires_all_time_driven_transitions(self, api):
        """PRD §2.4: "every advance runs the time-driven sweep: eligibility
        snapshots more than 30 days past their verification become `STALE`,
        `APPROVED` authorizations whose validity window has passed become
        `EXPIRED`, `PRESENTED` estimates whose service date has passed become
        `EXPIRED`, and payment plans with an installment more than fourteen
        days past due become `DEFAULTED`. The sweep response reports the new
        `current_utc` alongside the counts `staled_snapshots`,
        `expired_authorizations`, `expired_estimates`, and `defaulted_plans`."
        PRD §3.7: "The logical-clock sweep expires an `APPROVED` authorization
        when the current logical date falls strictly after its `valid_to`,
        moving it to `EXPIRED`; the case's `auth_satisfied` is recomputed, and
        if the case was `CLEARED` it regresses to `IN_REVIEW`."

        Design: Corner/complexity_layers/clock_sweep_fires_all_time_driven_transitions
        """
        set_clock("2026-08-03T09:00:00Z")
        create_charge_item(cpt_code="27447", list_price_cents=5000000,
                           requires_auth_prior=True)
        create_contract_with_rates(
            bundling_rule="MULTIPLE_PROCEDURE_REDUCTION", reduction_pct=50,
            rates=[{"cpt_code": "27447", "rate_cents": 3000000,
                    "effective_from": "2026-01-01"}])
        patient = create_patient(mrn="MRN-OC-3")
        snapshot = create_snapshot(patient["id"])

        # Case A: estimate presented but never accepted.
        case_a = create_case(patient["id"], service_date="2026-08-20",
                             service_description="Case A (never accepted)")
        est_a = create_estimate(case_a["id"], pricing_mode="INSURED",
                                eligibility_snapshot_id=snapshot["id"],
                                lines=[{"cpt_code": "27447", "quantity": 1}])
        price_estimate(est_a["id"])
        present_estimate(est_a["id"])

        # Case B: fully cleared, with an active payment plan.
        case_b = create_case(patient["id"], service_date="2026-08-20",
                             service_description="Case B (to be cleared)")
        est_b = create_estimate(case_b["id"], pricing_mode="INSURED",
                                eligibility_snapshot_id=snapshot["id"],
                                lines=[{"cpt_code": "27447", "quantity": 1}])
        price_estimate(est_b["id"])
        present_estimate(est_b["id"])
        accept_estimate(est_b["id"])
        auth_b = request_and_approve_authorization(case_b["id"],
                                                   cpt_codes=("27447",))
        pledge_and_post_deposit(case_b["id"], 125000)
        cleared = validate_success(api.clear_case(case_b["id"], SUPERVISOR), 200)
        assert cleared["status"] == "CLEARED"
        plan_b = create_active_plan(case_b["id"], principal_cents=99999,
                                    num_installments=2)

        sweep = set_clock("2026-09-17T00:00:00Z")
        assert sweep["staled_snapshots"] == 1
        assert sweep["expired_authorizations"] == 1
        assert sweep["expired_estimates"] == 1
        assert sweep["defaulted_plans"] == 1

        snap_after = validate_success(
            api.get_eligibility_snapshot(snapshot["id"], SUPERVISOR), 200)
        assert snap_after["status"] == "STALE"
        est_a_after = validate_success(api.get_estimate(est_a["id"], SUPERVISOR), 200)
        assert est_a_after["status"] == "EXPIRED", (
            "PRESENTED past its service date expires")
        est_b_after = validate_success(api.get_estimate(est_b["id"], SUPERVISOR), 200)
        assert est_b_after["status"] == "ACCEPTED", "only PRESENTED estimates expire"
        auths, _m = validate_paginated(
            api.list_case_authorizations(case_b["id"], SUPERVISOR))
        assert auths[0]["status"] == "EXPIRED"
        case_b_after = validate_success(api.get_case(case_b["id"], SUPERVISOR), 200)
        assert case_b_after["status"] == "IN_REVIEW", (
            "CLEARED regresses when its relied-upon authorization expires")
        plans, _m = validate_paginated(
            api.list_case_payment_plans(case_b["id"], SUPERVISOR))
        assert plans[0]["status"] == "DEFAULTED", (
            "due 2026-09-02 plus fourteen days falls strictly before 2026-09-17")


class TestOptimisticConcurrency:
    def test_occ_estimate_create_stale_version_returns_412(self, api):
        """PRD §2.6: "When a `FinancialCounselor` creates an estimate revision
        on a clearance case, the request must carry `expected_case_version`
        equal to the case's current `version`. Estimate creation increments
        the case's `version` by 1 and legitimately supersedes the prior
        non-locked estimate, so a client holding a stale case version is
        rejected with `ERR_STALE_VERSION` rather than being allowed to
        overwrite revisions it has not seen."

        Design: Corner/complexity_layers/occ_estimate_create_stale_version_returns_412
        """
        ctx = setup_insured_scenario(mrn="MRN-OC-1", bundling_rule="NONE",
                                     reduction_pct=None)
        case_id = ctx["case"]["id"]
        stale_version = ctx["case"]["version"]
        est1 = ctx["estimate"]
        case_now = validate_success(api.get_case(case_id, COUNSELOR), 200)
        assert case_now["version"] == stale_version + 1, (
            "the first create incremented the case version by exactly 1")
        res = api.create_estimate(
            case_id,
            {"expected_case_version": stale_version,
             "pricing_mode": "INSURED",
             "eligibility_snapshot_id": ctx["snapshot"]["id"],
             "lines": [{"cpt_code": "27447", "quantity": 1}]},
            COUNSELOR)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        est1_after = validate_success(api.get_estimate(est1["id"], COUNSELOR), 200)
        assert est1_after["status"] == "DRAFT", "no supersede fired"
        _data, meta = validate_paginated(api.list_case_estimates(case_id, COUNSELOR))
        assert meta["total_count"] == 1

    def test_occ_snapshot_create_stale_version_returns_412(self, api):
        """PRD §2.6: "When a `Registrar` captures an eligibility snapshot for a
        patient, the request must carry `expected_patient_version` equal to the
        patient record's current `version`. If another writer has advanced the
        patient's version since the client last read it — most commonly by
        capturing a newer snapshot, which itself increments the patient's
        `version` by 1 — the create is rejected with `ERR_STALE_VERSION`,
        preventing the client from superseding a verification it has never
        observed."

        Design: Corner/complexity_layers/occ_snapshot_create_stale_version_returns_412
        """
        set_clock("2026-08-03T09:00:00Z")
        patient = create_patient(mrn="MRN-OC-2")
        stale_version = patient["version"]
        snap1 = create_snapshot(patient["id"], payer_code="ACME")
        res = api.create_eligibility_snapshot(
            patient["id"],
            create_eligibility_snapshot_payload(
                stale_version, payer_code="ACME", deductible_met_cents=90000),
            REGISTRAR)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        snap1_after = validate_success(
            api.get_eligibility_snapshot(snap1["id"], REGISTRAR), 200)
        assert snap1_after["status"] == "ACTIVE", "no supersede fired"
        patient_after = validate_success(api.get_patient(patient["id"], REGISTRAR), 200)
        assert patient_after["version"] == 2, "patient version unchanged by the rejection"


class TestRateWindowOverlap:
    def _setup_contract_with_rate(self):
        set_clock("2026-08-03T09:00:00Z")
        create_charge_item(cpt_code="27447", list_price_cents=5000000)
        contract = create_contract_with_rates(
            bundling_rule="NONE",
            rates=[{"cpt_code": "27447", "rate_cents": 3000000,
                    "effective_from": "2026-01-01", "effective_to": "2026-07-01"}])
        return contract

    def test_adjacent_half_open_window_is_allowed(self, api):
        """PRD §3.1: "windows for the same contract and CPT code must never
        overlap — though windows that merely touch, where the new window starts
        exactly on the day an existing window ends, are legitimate adjacency
        and allowed."

        Design: Difficulty/resource_temporal_overlap/contract_rate_half_open_window_overlap
        """
        contract = self._setup_contract_with_rate()
        res = api.add_contract_rate(
            contract["id"],
            {"cpt_code": "27447", "rate_cents": 3200000,
             "effective_from": "2026-07-01"},
            ADMIN)
        rate2 = validate_success(res, 201)
        assert rate2["effective_from"] == "2026-07-01"
        _data, meta = validate_paginated(
            api.list_contract_rates(contract["id"], ADMIN))
        assert meta["total_count"] == 2

    def test_overlapping_window_rejected_and_not_persisted(self, api):
        """PRD §3.1: "Rate windows are half-open: the window starts on
        `effective_from` inclusively and ends on `effective_to` exclusively,
        and a null `effective_to` leaves the window open-ended. ... An
        overlapping submission is rejected with `ERR_RATE_WINDOW_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/contract_rate_half_open_window_overlap
        """
        contract = self._setup_contract_with_rate()
        validate_success(api.add_contract_rate(
            contract["id"],
            {"cpt_code": "27447", "rate_cents": 3200000,
             "effective_from": "2026-07-01"},
            ADMIN), 201)
        res = api.add_contract_rate(
            contract["id"],
            {"cpt_code": "27447", "rate_cents": 3100000,
             "effective_from": "2026-06-15", "effective_to": "2026-08-01"},
            ADMIN)
        validate_error(res, ApiErrorId.ERR_RATE_WINDOW_OVERLAP)
        _data, meta = validate_paginated(
            api.list_contract_rates(contract["id"], ADMIN))
        assert meta["total_count"] == 2, "the rejected window was not persisted"

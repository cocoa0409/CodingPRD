"""Work authorization gates, job execution gates, and ordinance & law upgrades.

Covers the signed-authorization safety gate, mold containment, authorization
expiry against the logical clock, the completion moisture gate with latest
reading per group, the pending-code-upgrade closure gate, and the ordinance
bucket waterfall with its exact-remaining boundary and withdrawal compensation.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_carrier, make_customer, make_policy, make_claim, make_claim_ctx,
    read_claim, claim_to_assessing, claim_to_estimating,
    schedule_inspection, add_evidence_photos, add_reading, complete_inspection,
    build_estimate, submit_estimate, approve_estimate,
    setup_approved_claim, setup_in_progress_claim, make_and_sign_wa,
    set_logical_clock, create_code_upgrade_payload, create_work_authorization_payload,
    make_customer_headers, TEST_USERS,
)
from datetime import datetime

ADMIN = TEST_USERS["contractor_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]

_WATER_POLICY = {"coverage_a_limit_cents": 100000000, "flat_deductible_cents": 100000}
_ACME_CARRIER = {"name": "Acme Mutual", "tax_rate": 0.07}


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestStartWorkGates:
    def test_start_work_without_signed_wa_returns_auth_missing(self, api):
        """PRD §3.8: "The safety gates next (priority 7): a work authorization in
        `SIGNED` status with `deductible_acknowledged` true must exist for the
        claim — otherwise `ERR_AUTHORIZATION_MISSING` (HTTP 409)"

        Design: Corner/state_machines/start_work_without_signed_wa_returns_auth_missing
        """
        ctx = setup_approved_claim(cause_of_loss="FIRE", line_specs=[(0, 100)])
        res = api.start_work(ctx["claim"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_AUTHORIZATION_MISSING)
        assert read_claim(ctx["claim"]["id"])["status"] == "APPROVED"

    def test_mold_start_work_requires_containment_line(self, api):
        """PRD §3.8: "when the claim's `cause_of_loss` is `MOLD`, an `APPROVED` or
        `LOCKED` estimate of the claim must contain a non-removed line whose
        `trade` is CONTAINMENT, else `ERR_CONTAINMENT_REQUIRED` (HTTP 422)."

        Design: Corner/state_machines/mold_start_work_requires_containment_line
        """
        ctx = setup_approved_claim(
            cause_of_loss="MOLD", carrier_overrides=_ACME_CARRIER,
            policy_overrides=_WATER_POLICY,
            entry_specs=({"category_code": "MLD-REM", "trade": "DEMOLITION",
                          "kind": "LABOR", "unit": "SF", "unit_price_cents": 300},),
            line_specs=[(0, 100)],
            readings=[{"area": "bath", "material": "drywall", "reading_value": 18,
                       "dry_standard": 12, "recorded_at": "2026-05-02T09:10:00Z"}])
        make_and_sign_wa(ctx, direct_pay=False)
        res = api.start_work(ctx["claim"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_CONTAINMENT_REQUIRED)
        assert read_claim(ctx["claim"]["id"])["status"] == "AUTHORIZED"

    def test_start_work_after_authorization_expiry_returns_422(self, api):
        """PRD §3.8: "Signing snapshots `scope_rcv_cents` from the claim's current
        `rcv_total_cents` — the drift baseline for §3.6 — stamps `signed_at` from
        the logical clock, and sets `expires_at` exactly 30 days later."
        PRD §3.8: "The temporal gate last (priority 9): the logical clock must not
        have passed the authorization's `expires_at`, else
        `ERR_AUTHORIZATION_EXPIRED` (HTTP 422)."
        PRD §2.4: "At server startup the logical clock reads exactly
        2026-05-01T00:00:00Z."

        Design: Corner/state_machines/start_work_after_authorization_expiry_returns_422
        """
        ctx = setup_approved_claim(cause_of_loss="FIRE", line_specs=[(0, 100)])
        make_and_sign_wa(ctx, direct_pay=False)
        # signed at the startup clock 2026-05-01 -> expires 2026-05-31
        assert _parse(ctx["wa"]["expires_at"]) == _parse("2026-05-31T00:00:00Z")
        set_logical_clock("2026-06-05T00:00:00Z")
        res = api.start_work(ctx["claim"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_AUTHORIZATION_EXPIRED)


class TestCompleteWorkGates:
    def test_complete_work_moisture_gate_blocks_then_passes(self, api):
        """PRD §3.8: "For a claim whose `cause_of_loss` is `WATER` or `MOLD`, the
        moisture gate groups all readings across the claim's inspections by
        (`area`, `material`); for every group containing at least one reading with
        `is_wet` true, the latest reading — by `recorded_at`, ties broken by
        `created_at` — must be at most the group's `dry_standard` plus 2, else
        completion is rejected with `ERR_MOISTURE_GATE_FAILED` (HTTP 422)."

        Design: Corner/state_machines/complete_work_moisture_gate_blocks_then_passes
        """
        # Both inspections are scheduled while the claim is in ASSESSING (the only
        # window in which the PRD permits inspection creation). I1 completes with a
        # wet reading (28 > 12 + 2); I2 stays SCHEDULED, its drying reading is
        # captured later — readings may be added while an inspection is SCHEDULED.
        ctx = make_claim_ctx(cause_of_loss="WATER", carrier_overrides=_ACME_CARRIER,
                             policy_overrides=_WATER_POLICY)
        claim_to_assessing(ctx)
        claim_id = ctx["claim"]["id"]
        initial = schedule_inspection(claim_id, assignee_id="tech-1",
                                      start="2026-05-02T09:00:00Z",
                                      end="2026-05-02T10:00:00Z", insp_type="INITIAL")
        verification = schedule_inspection(claim_id, assignee_id="tech-1",
                                           start="2026-05-10T09:00:00Z",
                                           end="2026-05-10T10:00:00Z",
                                           insp_type="VERIFICATION")
        add_evidence_photos(claim_id, initial["id"],
                            tags=("AREA", "AREA", "MOISTURE_PROOF"))
        add_evidence_photos(claim_id, verification["id"],
                            tags=("AREA", "AREA", "MOISTURE_PROOF"))
        add_reading(initial["id"], area="kitchen", material="drywall",
                    reading_value=28, dry_standard=12,
                    recorded_at="2026-05-02T09:10:00Z")
        complete_inspection(initial["id"])
        claim_to_estimating(ctx)
        build_estimate(ctx, [(0, 100)])
        submit_estimate(ctx["estimate"]["id"])
        approve_estimate(ctx["estimate"]["id"])
        make_and_sign_wa(ctx, direct_pay=False)
        validate_success(api.start_work(claim_id, ADMIN), 200)
        # latest (and only) reading in the group is wet: 28 > 12 + 2
        validate_error(api.complete_work(claim_id, ADMIN),
                       ApiErrorId.ERR_MOISTURE_GATE_FAILED)
        # the later verification reading of 13 (<= 12 + 2) dries the group
        add_reading(verification["id"], area="kitchen", material="drywall",
                    reading_value=13, dry_standard=12,
                    recorded_at="2026-05-10T09:10:00Z")
        complete_inspection(verification["id"])
        completed = validate_success(api.complete_work(claim_id, ADMIN), 200)
        assert completed["status"] == "COMPLETE", \
            "latest reading per group wins by recorded_at DESC"

    def test_complete_work_with_pending_code_upgrade_rejected(self, api):
        """PRD §3.8: "Independently, if any code upgrade on the claim is still
        `IDENTIFIED`, completion is rejected with `ERR_CODE_UPGRADES_PENDING`
        (HTTP 409)."

        Design: Corner/state_machines/complete_work_with_pending_code_upgrade_rejected
        """
        ctx = setup_in_progress_claim(
            cause_of_loss="FIRE", line_specs=[(0, 100)], direct_pay=False,
            policy_overrides={"coverage_a_limit_cents": 5000000,
                              "flat_deductible_cents": 50000,
                              "ordinance_coverage_pct": 0.10,
                              "ordinance_flat_cap_cents": 250000})
        claim_id = ctx["claim"]["id"]
        upgrade = validate_success(api.create_code_upgrade(
            claim_id, create_code_upgrade_payload(
                code_citation="NEC 210.12", description="AFCI breakers",
                estimated_cost_cents=80000), ESTIMATOR), 201)
        validate_error(api.complete_work(claim_id, ADMIN),
                       ApiErrorId.ERR_CODE_UPGRADES_PENDING)
        # denying the item moves it to a terminal state and clears the gate
        validate_success(api.deny_code_upgrade(upgrade["id"], ADJUSTER), 200)
        completed = validate_success(api.complete_work(claim_id, ADMIN), 200)
        assert completed["status"] == "COMPLETE"


_ORDINANCE_POLICY = {"coverage_a_limit_cents": 2500000,
                     "deductible_type": "FLAT", "flat_deductible_cents": 50000,
                     "recoverable_depreciation": True,
                     "ordinance_coverage_pct": 0.10,
                     "ordinance_flat_cap_cents": 300000}


def _hail_claim_with_ordinance(**policy_overrides):
    carrier = make_carrier(name="Acme Mutual", tax_rate=0.07)
    customer = make_customer(full_name="Sam Owner", email="sam@example.com")
    policy = make_policy(customer["id"], carrier["id"],
                         **{**_ORDINANCE_POLICY, **policy_overrides})
    claim = make_claim(policy["id"], cause_of_loss="HAIL",
                       date_of_loss="2026-03-10T00:00:00Z")
    return carrier, customer, policy, claim


class TestOrdinanceWaterfall:
    def test_ordinance_bucket_exact_remaining_fully_covers(self, api):
        """PRD §3.7: "Allocation is incremental at approval time, ordered by
        `approved_at` ascending with ties broken by `created_at` ascending: the
        approving item's `covered_cents` is the lesser of its `approved_cost_cents`
        and the bucket remaining — so when the remaining amount is at least the
        approved cost the item is covered in full, and at the exhaustion boundary
        coverage is partial."
        PRD §3.7: "a covered policy whose bucket remaining is zero rejects with
        `ERR_ORDINANCE_CAP_EXHAUSTED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/ordinance_bucket_exact_remaining_fully_covers
        """
        _, _, policy, claim = _hail_claim_with_ordinance()
        # limit = min(round(0.10 * 2,500,000), 300,000) = 250,000
        assert policy["ordinance_limit_cents"] == 250000
        claim_id = claim["id"]
        cu_a = validate_success(api.create_code_upgrade(
            claim_id, create_code_upgrade_payload(
                code_citation="IRC R905.1", description="Ice barrier underlayment",
                estimated_cost_cents=150000), ESTIMATOR), 201)
        cu_b = validate_success(api.create_code_upgrade(
            claim_id, create_code_upgrade_payload(
                code_citation="NEC 210.12", description="AFCI breakers",
                estimated_cost_cents=100000), ESTIMATOR), 201)
        cu_c = validate_success(api.create_code_upgrade(
            claim_id, create_code_upgrade_payload(
                code_citation="IECC R402", description="Insulation top-up",
                estimated_cost_cents=1), ESTIMATOR), 201)
        approved_a = validate_success(
            api.approve_code_upgrade(cu_a["id"], {}, ADJUSTER), 200)
        assert approved_a["covered_cents"] == 150000
        # remaining 100,000; B costs exactly the remaining -> fully covered
        approved_b = validate_success(
            api.approve_code_upgrade(cu_b["id"], {}, ADJUSTER), 200)
        assert approved_b["covered_cents"] == 100000
        assert approved_b["customer_responsibility_cents"] == 0
        summary = validate_success(api.get_financial_summary(claim_id, ADJUSTER), 200)
        assert summary["ordinance_consumed_cents"] == 250000, \
            "bucket exactly exhausted, not over"
        # remaining == 0 rejects the 1-cent item
        res = api.approve_code_upgrade(cu_c["id"], {}, ADJUSTER)
        validate_error(res, ApiErrorId.ERR_ORDINANCE_CAP_EXHAUSTED)

    def test_partial_coverage_at_exhaustion_boundary(self, api):
        """PRD §3.7: "the approving item's `covered_cents` is the lesser of its
        `approved_cost_cents` and the bucket remaining — so when the remaining
        amount is at least the approved cost the item is covered in full, and at
        the exhaustion boundary coverage is partial."
        PRD §3.7: "The uninsured remainder becomes
        `customer_responsibility_cents`, the approved cost minus the covered
        amount"
        PRD §3.7: "An `Adjuster` may deny an `IDENTIFIED` item outright, or approve
        it — optionally overriding the contractor's figure with an
        `approved_cost_cents`, which defaults to `estimated_cost_cents` when
        omitted."

        Design: Difficulty/boundary_precision_check/ordinance_bucket_exact_remaining_fully_covers
        """
        _, _, _, claim = _hail_claim_with_ordinance()
        claim_id = claim["id"]
        cu_a = validate_success(api.create_code_upgrade(
            claim_id, create_code_upgrade_payload(
                code_citation="IRC R905.1", description="Ice barrier",
                estimated_cost_cents=200000), ESTIMATOR), 201)
        validate_success(api.approve_code_upgrade(cu_a["id"], {}, ADJUSTER), 200)
        # remaining 50,000; adjuster overrides the contractor's 99,999 estimate
        # down to 80,000 -> partial coverage 50,000, customer owes 30,000
        cu_b = validate_success(api.create_code_upgrade(
            claim_id, create_code_upgrade_payload(
                code_citation="NEC 210.12", description="AFCI breakers",
                estimated_cost_cents=99999), ESTIMATOR), 201)
        approved_b = validate_success(api.approve_code_upgrade(
            cu_b["id"], {"approved_cost_cents": 80000}, ADJUSTER), 200)
        assert approved_b["approved_cost_cents"] == 80000
        assert approved_b["covered_cents"] == 50000
        assert approved_b["customer_responsibility_cents"] == 30000
        summary = validate_success(api.get_financial_summary(claim_id, ADJUSTER), 200)
        assert summary["ordinance_consumed_cents"] == 250000

    def test_ordinance_not_covered_returns_422(self, api):
        """PRD §3.7: "Approval allocates from the policy's ordinance bucket, and
        its fiscal checks run in a fixed order at priority 10: a policy whose
        `ordinance_limit_cents` is zero rejects the approval with
        `ERR_ORDINANCE_NOT_COVERED` (HTTP 422)"

        Design: Corner/errors/error_ordinance_not_covered_returns_422
        """
        carrier = make_carrier(name="Acme Mutual", tax_rate=0.07)
        customer = make_customer(full_name="Sam Owner", email="sam@example.com")
        # no ordinance terms -> both defaults 0 -> limit 0
        policy = make_policy(customer["id"], carrier["id"],
                             policy_number="POL-NC",
                             coverage_a_limit_cents=2500000,
                             deductible_type="FLAT", flat_deductible_cents=50000,
                             recoverable_depreciation=True)
        assert policy["ordinance_limit_cents"] == 0
        claim = make_claim(policy["id"], cause_of_loss="HAIL",
                           date_of_loss="2026-03-10T00:00:00Z")
        cu = validate_success(api.create_code_upgrade(
            claim["id"], create_code_upgrade_payload(
                code_citation="IRC R905.1", description="Ice barrier",
                estimated_cost_cents=50000), ESTIMATOR), 201)
        res = api.approve_code_upgrade(cu["id"], {}, ADJUSTER)
        validate_error(res, ApiErrorId.ERR_ORDINANCE_NOT_COVERED)

    def test_approve_and_withdraw_preserve_bucket(self, api):
        """PRD §3.7: "Withdrawal is the compensation path: an `Estimator` may
        withdraw an `APPROVED` item, moving it to `WITHDRAWN`, releasing its
        `covered_cents` back to the bucket and recomputing
        `ordinance_consumed_cents`."
        PRD §3.7: "the claim's `ordinance_consumed_cents` is recomputed as the sum
        of `covered_cents` over `APPROVED` items."

        Design: Difficulty/compensating_invariant/code_upgrade_approve_and_withdraw_preserve_bucket
        """
        _, _, policy, claim = _hail_claim_with_ordinance()
        limit = policy["ordinance_limit_cents"]
        assert limit == 250000
        claim_id = claim["id"]
        cu_a = validate_success(api.create_code_upgrade(
            claim_id, create_code_upgrade_payload(
                code_citation="IRC R905.1", description="Ice barrier underlayment",
                estimated_cost_cents=150000), ESTIMATOR), 201)
        approved_a = validate_success(
            api.approve_code_upgrade(cu_a["id"], {}, ADJUSTER), 200)
        assert approved_a["covered_cents"] == 150000
        mid = validate_success(api.get_financial_summary(claim_id, ESTIMATOR), 200)
        assert mid["ordinance_consumed_cents"] == 150000
        withdrawn = validate_success(api.withdraw_code_upgrade(cu_a["id"], ESTIMATOR), 200)
        assert withdrawn["status"] == "WITHDRAWN"
        after = validate_success(api.get_financial_summary(claim_id, ESTIMATOR), 200)
        assert after["ordinance_consumed_cents"] == 0, \
            "compensation restores the bucket cent-exactly"
        assert after["ordinance_consumed_cents"] + (
            after["ordinance_limit_cents"] - after["ordinance_consumed_cents"]) == 250000
        # full bucket available again: a fresh 250,000c item approves fully covered
        cu_b = validate_success(api.create_code_upgrade(
            claim_id, create_code_upgrade_payload(
                code_citation="IBC 1010", description="Egress door widening",
                estimated_cost_cents=250000), ESTIMATOR), 201)
        approved_b = validate_success(
            api.approve_code_upgrade(cu_b["id"], {}, ADJUSTER), 200)
        assert approved_b["covered_cents"] == 250000, "zero drift on release"

    def test_withdraw_releases_exactly_the_covered_portion(self, api):
        """PRD §3.7: "Withdrawal is the compensation path: an `Estimator` may
        withdraw an `APPROVED` item, moving it to `WITHDRAWN`, releasing its
        `covered_cents` back to the bucket and recomputing
        `ordinance_consumed_cents`."
        PRD §3.7: "the claim's `ordinance_consumed_cents` is recomputed as the sum
        of `covered_cents` over `APPROVED` items."

        Design: Difficulty/compensating_invariant/code_upgrade_approve_and_withdraw_preserve_bucket
        """
        # limit 250,000; A consumes 200,000; B (80,000) is partially covered
        # (50,000) at the boundary; withdrawing B must release exactly 50,000.
        _, _, _, claim = _hail_claim_with_ordinance()
        claim_id = claim["id"]
        cu_a = validate_success(api.create_code_upgrade(
            claim_id, create_code_upgrade_payload(
                code_citation="IRC R905.1", description="Ice barrier",
                estimated_cost_cents=200000), ESTIMATOR), 201)
        validate_success(api.approve_code_upgrade(cu_a["id"], {}, ADJUSTER), 200)
        cu_b = validate_success(api.create_code_upgrade(
            claim_id, create_code_upgrade_payload(
                code_citation="NEC 210.12", description="AFCI breakers",
                estimated_cost_cents=80000), ESTIMATOR), 201)
        approved_b = validate_success(
            api.approve_code_upgrade(cu_b["id"], {}, ADJUSTER), 200)
        assert approved_b["covered_cents"] == 50000
        assert approved_b["customer_responsibility_cents"] == 30000
        validate_success(api.withdraw_code_upgrade(cu_b["id"], ESTIMATOR), 200)
        after = validate_success(api.get_financial_summary(claim_id, ESTIMATOR), 200)
        assert after["ordinance_consumed_cents"] == 200000, \
            "only the covered 50,000 was released; A untouched"
        # bucket remaining is exactly 50,000 again: a fresh 50,000 item fully covers
        cu_c = validate_success(api.create_code_upgrade(
            claim_id, create_code_upgrade_payload(
                code_citation="IBC 1010", description="Egress door widening",
                estimated_cost_cents=50000), ESTIMATOR), 201)
        approved_c = validate_success(
            api.approve_code_upgrade(cu_c["id"], {}, ADJUSTER), 200)
        assert approved_c["covered_cents"] == 50000
        assert approved_c["customer_responsibility_cents"] == 0

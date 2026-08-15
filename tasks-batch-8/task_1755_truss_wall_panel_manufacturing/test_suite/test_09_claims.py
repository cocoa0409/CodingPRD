"""Damage claims: assessment cap, settlement waterfall, rebuild cascade, hold join."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_claims_adjuster_headers,
    make_customer_contact_headers,
    make_load,
    make_bundle,
    book_slot,
    complete_slot,
    set_clock,
    transition_load,
    file_claim,
    setup_claim_preamble,
    setup_claim_approved_credit,
    setup_claim_rebuild_in_progress,
    setup_claim_fork,
    setup_production_preamble,
    load_fresh,
    bundle_fresh,
    claim_fresh,
    job_fresh,
)

PM = TEST_USERS["plant_manager_headers"]
PP = TEST_USERS["production_planner_headers"]
SC = TEST_USERS["shipping_coordinator_headers"]
ADJ1 = make_claims_adjuster_headers("adj-1")
ADJ2 = make_claims_adjuster_headers("adj-2")

SETTLE_PAYLOAD = {"rebuild_material_cents": 20000, "rebuild_labor_cents": 15000,
                  "redelivery_cents": 5000}


class TestClaimCapVsSettlementDivergence:
    def test_cap_then_waterfall_buckets_diverge(self, api):
        """PRD §3.8: "the component value is the damaged bundle's batch's cut list's
        `total_board_feet` multiplied by 850 cents per board foot, rounded half-up to
        whole cents, and the cap is the smaller of `claimed_amount_cents` and
        `damage_pct` multiplied by that component value, rounded half-up to whole
        cents." and "The approved cap distributes across them as a waterfall in that
        fixed order: the material bucket receives the smaller of the actual material
        amount and the cap remaining; the labor bucket then receives the smaller of
        the actual labor amount and what remains; the redelivery bucket likewise; and
        whatever remains afterward is `residual_credit_cents`, issued back to the
        customer as credit."

        Design: Difficulty/dual_variant_calc/claim_cap_vs_settlement_divergence
        """
        ns = setup_claim_approved_credit()
        settled = validate_success(api.settle_claim(ns.claim["id"], SETTLE_PAYLOAD, ADJ2))
        assert settled["approved_cap_cents"] == 50661, \
            "min(500000, round_half_up(0.30 x round_half_up(198.67 x 850)))"
        assert settled["status"] == "SETTLED"
        assert settled["rebuild_material_cents"] == 20000
        assert settled["rebuild_labor_cents"] == 15000
        assert settled["redelivery_cents"] == 5000
        assert settled["residual_credit_cents"] == 10661
        assert settled["residual_credit_cents"] != settled["approved_cap_cents"], \
            "estimate ceiling at decide vs settled residual diverge on identical claim data"

    def test_settlement_issues_credit_and_releases_hold(self, api):
        """PRD §3.8: "Settlement adds `residual_credit_cents` to the job's
        `credit_issued_cents`, recomputes posture, and releases the load `CLAIM_HOLD`
        to `DELIVERED` when no other claim on it remains open." PRD §3.2:
        "`credit_issued_cents`, initially 0, is the sum of `residual_credit_cents`
        over the job's damage claims currently in `SETTLED`".

        Design: Difficulty/dual_variant_calc/claim_cap_vs_settlement_divergence
        """
        ns = setup_claim_approved_credit()
        validate_success(api.settle_claim(ns.claim["id"], SETTLE_PAYLOAD, ADJ2))
        assert job_fresh(ns.job["id"])["credit_issued_cents"] == 10661
        assert load_fresh(ns.load["id"])["status"] == "DELIVERED", \
            "the hold releases once no open claim remains"


class TestClaimForkJoinBranches:
    def test_settling_one_claim_does_not_release_hold_while_another_open(self, api):
        """PRD §3.8: "Settlement adds `residual_credit_cents` to the job's
        `credit_issued_cents`, recomputes posture, and releases the load `CLAIM_HOLD`
        to `DELIVERED` when no other claim on it remains open."

        Design: Difficulty/non_linear_state_machine/claim_fork_join_branches
        """
        ns = setup_claim_fork()
        settled = validate_success(api.settle_claim(ns.c1["id"], SETTLE_PAYLOAD, ADJ2))
        assert settled["status"] == "SETTLED"
        assert settled["approved_cap_cents"] == 50661
        assert settled["residual_credit_cents"] == 10661
        assert load_fresh(ns.load["id"])["status"] == "CLAIM_HOLD", \
            "the join requires ALL claims terminal; c2 is still TRIAGED"

    def test_deny_computes_no_cap_and_releases_hold_at_join(self, api):
        """PRD §3.8: "A `DENY` decision computes no cap, and if no other claim on the
        load remains open, the load is released from `CLAIM_HOLD` back to `DELIVERED`."
        and "`APPROVE_CREDIT` is the lighter path: the cap is computed identically,
        but the bundle stays `DELIVERED` and nothing is rebuilt."

        Design: Difficulty/non_linear_state_machine/claim_fork_join_branches
        """
        ns = setup_claim_fork()
        validate_success(api.settle_claim(ns.c1["id"], SETTLE_PAYLOAD, ADJ2))
        denied = validate_success(api.decide_claim(ns.c2["id"], {"decision": "DENY"}, ADJ2))
        assert denied["status"] == "DENIED"
        assert denied["approved_cap_cents"] is None
        assert denied["residual_credit_cents"] is None
        assert load_fresh(ns.load["id"])["status"] == "DELIVERED", \
            "with c1 SETTLED and c2 DENIED, no open claim remains"
        assert bundle_fresh(ns.bundle["id"])["status"] == "DELIVERED", \
            "neither branch marked the bundle DAMAGED"
        assert job_fresh(ns.job["id"])["credit_issued_cents"] == 10661


class TestClaimRebuildCascade:
    def test_approve_rebuild_marks_bundle_and_auto_advances(self, api):
        """PRD §3.8: "`APPROVE_REBUILD` — moving the claim to `APPROVED_REBUILD` —
        marks the damaged bundle `DELIVERED` to `DAMAGED` and fires the rebuild
        cascade" and "The claim then continues immediately to `REBUILD_IN_PROGRESS`,
        and the job's posture reads `BLOCKED` per §2.10 for as long as the claim
        remains unsettled."

        Design: Difficulty/transitive_cascade/claim_rebuild_cascade
        """
        ns = setup_claim_preamble()
        decided = validate_success(api.decide_claim(
            ns.claim["id"], {"decision": "APPROVE_REBUILD", "damage_pct": 0.30}, ADJ2))
        assert decided["status"] == "REBUILD_IN_PROGRESS", \
            "the claim auto-advances once the cascade completes"
        assert decided["approved_cap_cents"] == 50661
        assert bundle_fresh(ns.bundle["id"])["status"] == "DAMAGED"
        assert job_fresh(ns.job["id"])["posture"] == "BLOCKED"
        assert load_fresh(ns.load["id"])["status"] == "CLAIM_HOLD", \
            "the cascade does not release the hold"

    def test_rebuild_clone_and_batch_created(self, api):
        """PRD §3.8: "the system clones the damaged bundle's batch's cut list into a
        new cut list in `EXPLODED` with fresh `PENDING` lines of identical
        specifications, stamped with `rebuild_for_claim_id` naming the claim, with the
        line math of §3.4 recomputed for the clone; it then creates a rebuild
        production batch in `SCHEDULED` with `is_rebuild` true, `source_claim_id`
        naming the claim, the same jig, and a `requested_completion_at` of the
        current logical clock plus 7 days".

        Design: Difficulty/transitive_cascade/claim_rebuild_cascade
        """
        ns = setup_claim_rebuild_in_progress()  # decide clock is 2026-08-20
        clone = ns.cl_clone
        assert clone is not None and clone["rebuild_for_claim_id"] == ns.claim["id"]
        assert clone["status"] == "EXPLODED"
        assert clone["total_board_feet"] == pytest.approx(198.67), "faithful clone totals"
        assert clone["total_plates"] == 280
        clone_lines, _ = validate_paginated(
            api.list_cut_list_lines(PP, params={"cut_list_id": clone["id"]}))
        assert len(clone_lines) == 2
        assert all(line["status"] == "PENDING" for line in clone_lines), \
            "clone lines are fresh PENDING"
        assert ns.bat_r is not None
        assert ns.bat_r["is_rebuild"] is True
        assert ns.bat_r["source_claim_id"] == ns.claim["id"]
        assert ns.bat_r["status"] == "SCHEDULED"
        assert ns.bat_r["requested_completion_at"].startswith("2026-08-27"), \
            "current logical clock 2026-08-20 plus 7 days"


class TestClaimSettleGuards:
    def test_settle_rejected_while_rebuild_batch_scheduled(self, api):
        """PRD §3.8: "From `APPROVED_CREDIT`, or from `REBUILD_IN_PROGRESS` once the
        rebuild batch identified by `source_claim_id` has reached `STAGED` or
        `LOADED`, a `ClaimsAdjuster` settles with three actual cost amounts" and "All
        claim actions respect the status guards: triage only from `FILED`, decide only
        from `TRIAGED`, settle only from `APPROVED_CREDIT` or `REBUILD_IN_PROGRESS`,
        and void only from `FILED`, `TRIAGED`, or `SETTLED`; anything else is
        `ERR_CLAIM_INVALID_TRANSITION`."

        Design: Difficulty/cross_entity_state_dependency/claim_settle_requires_rebuild_batch_staged
        """
        ns = setup_claim_rebuild_in_progress()
        assert ns.bat_r["status"] == "SCHEDULED", "rebuild batch has not reached STAGED"
        resp = api.settle_claim(ns.claim["id"], SETTLE_PAYLOAD, ADJ2)
        validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_TRANSITION)
        claim = claim_fresh(ns.claim["id"])
        assert claim["status"] == "REBUILD_IN_PROGRESS"
        assert claim["residual_credit_cents"] is None
        assert job_fresh(ns.job["id"])["credit_issued_cents"] == 0, "no waterfall ran"

    def test_settle_from_filed_rejected(self, api):
        """PRD §3.8: "settle only from `APPROVED_CREDIT` or `REBUILD_IN_PROGRESS`,
        and void only from `FILED`, `TRIAGED`, or `SETTLED`; anything else is
        `ERR_CLAIM_INVALID_TRANSITION`."

        Design: Difficulty/cross_entity_state_dependency/claim_settle_requires_rebuild_batch_staged
        """
        ns = setup_claim_preamble(triage=False)  # claim still FILED
        resp = api.settle_claim(ns.claim["id"], SETTLE_PAYLOAD, ADJ2)
        validate_error(resp, ApiErrorId.ERR_CLAIM_INVALID_TRANSITION)
        assert claim_fresh(ns.claim["id"])["status"] == "FILED"


class TestClaimWaterfallConservationAndVoidReversal:
    def test_waterfall_conservation_exact(self, api):
        """PRD §3.8: "Conservation is exact in integer cents — the three buckets plus
        the residual always sum precisely to `approved_cap_cents`." and "Settlement
        adds `residual_credit_cents` to the job's `credit_issued_cents`".

        Design: Difficulty/compensating_invariant/claim_waterfall_conservation_and_void_reversal
        """
        ns = setup_claim_approved_credit()
        settled = validate_success(api.settle_claim(ns.claim["id"], SETTLE_PAYLOAD, ADJ2))
        total = (settled["rebuild_material_cents"] + settled["rebuild_labor_cents"]
                 + settled["redelivery_cents"] + settled["residual_credit_cents"])
        assert total == settled["approved_cap_cents"] == 50661
        assert job_fresh(ns.job["id"])["credit_issued_cents"] == 10661

    def test_void_after_settle_reverses_credit_exactly(self, api):
        """PRD §3.8: "A claim already `SETTLED` may also be voided as a
        post-settlement reversal: the job's `credit_issued_cents` decreases by exactly
        the claim's `residual_credit_cents` — the compensating pair leaves the
        customer's issued credit unchanged — and posture is recomputed."

        Design: Difficulty/compensating_invariant/claim_waterfall_conservation_and_void_reversal
        """
        ns = setup_claim_approved_credit()
        validate_success(api.settle_claim(ns.claim["id"], SETTLE_PAYLOAD, ADJ2))
        assert job_fresh(ns.job["id"])["credit_issued_cents"] == 10661
        voided = validate_success(api.void_claim(ns.claim["id"], ADJ1))
        assert voided["status"] == "VOID"
        assert job_fresh(ns.job["id"])["credit_issued_cents"] == 0, \
            "settle then void is the compensating pair: 0 -> 10661 -> 0"


class TestClaimSegregationAndVoid:
    def test_claim_decider_must_differ_from_triager(self, api):
        """PRD §3.8: "Decision then requires a different adjuster: segregation of
        duties forbids the decider from equalling `triaged_by`, enforced with
        `ERR_CLAIM_DECIDER_MUST_DIFFER` (HTTP 422) after the action guard itself".

        Design: Corner/errors/claim_decider_must_differ_from_triager
        """
        ns = setup_claim_preamble()  # triaged by adj-1
        resp = api.decide_claim(ns.claim["id"],
                                {"decision": "APPROVE_CREDIT", "damage_pct": 0.30}, ADJ1)
        validate_error(resp, ApiErrorId.ERR_CLAIM_DECIDER_MUST_DIFFER)
        claim = claim_fresh(ns.claim["id"])
        assert claim["status"] == "TRIAGED"
        assert claim["approved_cap_cents"] is None

    def test_claim_void_from_filed_releases_hold(self, api):
        """PRD §3.8: "A claim in `FILED` or `TRIAGED` may be voided outright,
        releasing the load to `DELIVERED` if no other claim remains open."

        Design: Corner/state_machines/claim_void_from_filed_releases_hold
        """
        ns = setup_claim_preamble(triage=False)
        assert load_fresh(ns.load["id"])["status"] == "CLAIM_HOLD"
        voided = validate_success(api.void_claim(ns.claim["id"], ADJ1))
        assert voided["status"] == "VOID"
        assert load_fresh(ns.load["id"])["status"] == "DELIVERED"
        assert bundle_fresh(ns.bundle["id"])["status"] == "DELIVERED"


class TestClaimBundleReferentialGuard:
    def test_claim_bundle_not_in_load_rejected(self, api):
        """PRD §3.8: "The bundle must belong to that load, else
        `ERR_CLAIM_BUNDLE_NOT_IN_LOAD` (HTTP 422)".

        Design: Corner/errors/claim_bundle_not_in_load_rejected
        """
        ns = setup_production_preamble(job_name="Ref Job")
        load_a = make_load(ns.job["id"], scheduled_date="2026-08-21T00:00:00Z",
                           planned_weight_est_lbs=5000)
        load_b = make_load(ns.job["id"], scheduled_date="2026-08-22T00:00:00Z",
                           planned_weight_est_lbs=6000)
        book_slot(ns.crane["id"], "LOAD_PICK", "2026-08-20T09:00:00Z", "2026-08-20T10:00:00Z",
                  delivery_load_id=load_a["id"])
        slot_b = book_slot(ns.crane["id"], "LOAD_PICK", "2026-08-20T10:30:00Z",
                           "2026-08-20T11:30:00Z", delivery_load_id=load_b["id"])
        bundle_a = make_bundle(load_a["id"], ns.bat1["id"], 1, 5000)
        make_bundle(load_b["id"], ns.bat1["id"], 1, 6000)
        transition_load(load_b["id"], "STAGED")
        complete_slot(slot_b["id"])
        transition_load(load_b["id"], "LOADING")
        set_clock("2026-08-20T00:00:00Z")
        transition_load(load_b["id"], "DISPATCHED")
        transition_load(load_b["id"], "DELIVERED")
        # File against load B citing a bundle that belongs to load A.
        resp = api.create_claim(load_b["id"],
                                {"bundle_id": bundle_a["id"], "claim_type": "FIELD_DAMAGE",
                                 "description": "wrong bundle reference",
                                 "claimed_amount_cents": 10000},
                                make_customer_contact_headers(ns.customer["id"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_BUNDLE_NOT_IN_LOAD)
        assert load_fresh(load_b["id"])["status"] == "DELIVERED", \
            "a rejected file puts no hold on the load"
        data, meta = validate_paginated(
            api.list_claims(PM, params={"delivery_load_id": load_b["id"]}))
        assert meta["total_count"] == 0

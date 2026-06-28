# Worklog — task_0666_car_subscription_flexible_lease

## Step 1: Create Task Directory — 2026-06-26T18:18:36.000Z

Directory pre-existed (parallel-run directive). Used `tasks/task_0666_car_subscription_flexible_lease` verbatim as {task_dir}; skipped the directory-scan/index-compute. `workspace/` subdir present. No rename/compute performed.

## Step 2: Generate Scaffold — 2026-06-26T18:38:34.000Z

Generated all three Expert-difficulty scaffold artifacts for **Car Subscription & Flexible Lease** (Care by Volvo/Fair style) at `/home/ubuntu/github/CodingPRD/tasks/task_0666_car_subscription_flexible_lease/`. The scaffold lint reports **VERDICT: clean lint** (493 calls scanned, all §1.5/FK checks pass); all YAML parses; all design `grounds` resolve; no forbidden concurrency vocabulary.

**Complexity profile:** primary archetype quota_allocation (finite fleet reserved/assigned/released) + secondary pricing_engine; flat entity topology; parallel state-machine shape; peer_roles; layers: derived_field_reconciliation, scheduled_actions, optimistic_concurrency, rate_threshold_triggers.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **12 entities:** SubscriptionPlan, Fleet, Vehicle, Applicant, Subscription, BillingCycle, Invoice, SwapRequest, ReturnInspection, DamageLineItem, Courier, DeliverySlot
- **6 state machines:** Subscription (two parallel axes — lifecycle DRAFT→…→CLOSED and billing CURRENT⇄PAST_DUE), Vehicle (cyclic AVAILABLE→RESERVED→ASSIGNED→IN_INSPECTION→AVAILABLE + MAINTENANCE), SwapRequest (fork-join with compensation), ReturnInspection
- **6 calculations:** mileage_overage (tiered), early_cancel_fee (dual-variant forward vs chronological), eligibility_score (weighted scoring → deposit tier), swap_net_adjustment (pinned eval order, cross-plan proration), deposit_settlement_waterfall, fleet_utilization (dual-basis)
- **2 concurrency rules:** OCC on Vehicle.version (assign-with-supersede; swap-approve target reservation)
- **17 validations** (priority-ordered), **18 error codes**, **4 roles** (PlatformAdmin/FleetOperator/BillingAdmin opaque; Member entity_backed:Applicant), **53 endpoints** (incl. `/_clock/set_current_utc` default `2026-04-01T00:00:00Z`)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all 9 rules × **2 instances = 18 total**, each grounded and with literal-locked asserts (e.g., forward early-cancel 240000 vs chronological 56667; overage 14500; swap net 13500; eligibility 0.8818 APPROVED).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **30 active instances + 6 `excluded_because` stubs** spanning all 9 taxonomy sections (entities 8, state_machines 4, calculations 4, validations 4, endpoints 1, errors 1, rbac 3, cross_cutting_complexity_layers 4, consistency_model 1).

Note for downstream: `api_prefix` is `/` (root) because the flat topology uses many peer top-level collections.

## Step 3: Copy Shared Files — 2026-06-26T18:38:51.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T18:45:17.000Z

PRD generated at `workspace/PRD.md`. **Structure:** 5 top-level sections, 24 subsections (§2 has 10 cross-cutting subsections; §3 has 14 business-logic subsections organized by lifecycle/process), 315 lines.

**Coverage — all scaffold elements expressed in prose:**
- **Entities (12):** All covered. `Invoice` correctly flagged `common_fields: false` (only `id`/`created_at`); all others carry full common-field set.
- **State machines (5):** Subscription lifecycle, Subscription billing (CURRENT⇄PAST_DUE), Vehicle cyclic loop (incl. MAINTENANCE), SwapRequest fork-join (incl. compensating reject-after-approve), ReturnInspection (OPEN→ASSESSED→SETTLED). Depth-3 settle cascade + divergent swap-completion branches stated.
- **Calculations (6):** mileage_overage (tiered, 200-mile breakpoint), early_cancel_fee (forward-looking + chronological variant), eligibility_score (weights 0.5/0.3/0.2, inclusive thresholds), swap_net_adjustment (per-leg rounding, swap-fee gating, 7500 fee), deposit_settlement_waterfall, fleet_utilization (dual-basis). Constants embedded; no pseudocode.
- **Validations (17):** Full priority ordering in §2.10; each matchable to error_id; multi-endpoint applies_to scopes enumerated.
- **Endpoints (53):** All in §4 (4-col table, 201/200 rules); §3 references via state-transition/role-verb/capability framing only.
- **Errors (18):** All in §5; every ID surfaced in §2/§3 narrative with trigger.
- **Roles (4):** All named exact-spelling; Member = entity_backed Applicant ownership; PlatformAdmin/FleetOperator/BillingAdmin opaque.

**Hard Contracts:** Contract 1 (Field-Name Coverage 74/74) PASS; Contract 2 (Rule Coverage incl. 3 OCC rules) PASS; Contract 3 (§3 Path Purity, 449 tokens, 0 violations) PASS. Withheld design YAMLs not read.

## Step 7: Run Tests and Iterate — 2026-06-26T19:54:09.000Z

All 8 rounds pass cleanly with 67/67. The sweep is clean and the fix is stable across all parallel rounds.

## Summary

**Iterations run:** 2 sweeps (initial diagnostic sweep + 1 verification sweep after the fix).

**Diagnosis.** The very first sweep was deterministic, not flaky: each of the 8 rounds failed exactly the same single test, `test_occ_stale_vehicle_version_on_assign_rejected` (passed=66, total=67 in every round). It asserted `ERR_STALE_VEHICLE_VERSION` but the implementation correctly returned `ERR_INVALID_STATE`.

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:** None — the fixtures, factories, and role headers all faithfully expressed the PRD precondition (a genuine supersede race where sub1 reserves the vehicle, then sub2 retries with a stale version).

**Fixes applied to `implementation/`:** None. The implementation's ordering (`routes/subscriptions.py::assign_vehicle`, lines 94-99: target-vehicle state gate `ERR_INVALID_STATE` before OCC `ERR_STALE_VEHICLE_VERSION`) is the PRD-faithful behavior and was left untouched.

**Fix applied to `test_suite/` (test bug — ERROR PRECEDENCE collapse):**
- File: `test_suite/test_03_validations_and_concurrency.py`, function `test_occ_stale_vehicle_version_on_assign_rejected`.
- Why: This is the protocol's ERROR PRECEDENCE pattern, and stronger than mere silence — PRD §2.10 *explicitly* orders the generic state gate (`ERR_INVALID_STATE`, gate #6: "the target resource is in a state from which the requested transition is defined") **before** the domain-level vehicle-version concurrency check (`ERR_STALE_VEHICLE_VERSION`, near the end of the domain ordering). In the test's serialized setup, sub1's supersede fully completes, leaving the target vehicle in `RESERVED`; §3.4 requires the target's status be `AVAILABLE` to assign, so a §2.10-faithful implementer surfaces `ERR_INVALID_STATE` first, while a §2.7-only reader surfaces `ERR_STALE_VEHICLE_VERSION`. The two-reader test produces divergent PRD-faithful outcomes. Per the protocol's prescribed remedy for this exact pattern ("Relax to `validate_error_is_one_of([ERR_A, ERR_INVALID_STATE])` if the PRD supports at least the 'A is possible' reading"), I relaxed the assertion from `validate_error(resp, ERR_STALE_VEHICLE_VERSION)` to `validate_error_is_one_of(resp, [ERR_STALE_VEHICLE_VERSION, ERR_INVALID_STATE])`, added the `validate_error_is_one_of` import, and documented the §2.10 precedence reasoning in the docstring. No assertion was weakened to an HTTP-status check; both accepted values are exact `error_id`s, both verbatim in PRD.

**Final sweep result:** All 8 parallel rounds passed == total, 67/67 each. Confirmed stable.

## Step 8: Finalize PRD — 2026-06-26T19:57:03.000Z

NOT skipped — Step 7 made 1 `test_suite/` fix (assertion relaxation), so PRD silence/ambiguity was present at that site. Produced `workspace/PRD_FINALIZED.md`.

The edit is clean and minimal — exactly one line changed (line 158, §3.4). Line count unchanged at 315.

## Summary

**Edits made: 1.** PRD.md and PRD_FINALIZED.md are both 315 lines (line-count delta 0%); a single line was revised (line 158).

### Change
- **§3.4 (Opening a Subscription and Reserving a Vehicle) — revise — pinned the precedence between the target-vehicle `AVAILABLE` state gate and the `expected_vehicle_version` OCC check on assign-vehicle: attached `ERR_INVALID_STATE` to the "target vehicle's `status` is `AVAILABLE`" precondition and stated this state check is evaluated before the version concurrency check, so a stale-version assign against a no-longer-`AVAILABLE` target surfaces `ERR_INVALID_STATE`, not `ERR_STALE_VEHICLE_VERSION` — `implementation/routes/subscriptions.py:95-99`.**

### Why this edit (Step 7 item trace)
The Step 7 fix relaxed `test_occ_stale_vehicle_version_on_assign_rejected` to accept either `ERR_STALE_VEHICLE_VERSION` or `ERR_INVALID_STATE`. The implementation deterministically returns `ERR_INVALID_STATE` in that scenario: once sub1 reserves the vehicle (status → RESERVED), sub2's stale-version assign hits the `vehicle["status"] != "AVAILABLE"` gate (line 95-96) before ever reaching the OCC check (line 98-99). PRD.md did **not** uniquely pin this: §3.4 listed the `AVAILABLE` precondition with no error attached, and §2.10's generic `ERR_INVALID_STATE` gate ("the target resource is in a state...") is ambiguous as to whether "target resource" covers the target *vehicle* vs. only the subscription — leaving a §2.7-only reader free to surface `ERR_STALE_VEHICLE_VERSION`. The edit pins the implementation's actual ordering.

### Per-edit pre-edit search log
- **(a) Subject:** the error surfaced when an assign/approve target vehicle is not `AVAILABLE`, and its ordering relative to the `expected_vehicle_version` OCC check.
- **(b) Impl paths enumerated/read:**
  - `routes/subscriptions.py::assign_vehicle` lines 84-99 — DRAFT gate (`ERR_INVALID_STATE`, 85-86) → plan (89) → eligibility (93) → vehicle-AVAILABLE (`ERR_INVALID_STATE`, 95-96) → OCC version (`ERR_STALE_VEHICLE_VERSION`, 98-99). Confirms AVAILABLE check strictly precedes OCC.
  - `routes/swaps.py::approve_swap` lines 45-57 — parallel OCC-vehicle endpoint: swap-REQUESTED (`ERR_INVALID_STATE`, 47) → sub-ACTIVE (`ERR_INVALID_STATE`, 50) → target-AVAILABLE (`ERR_INVALID_STATE`, 53-54) → OCC version (`ERR_STALE_VEHICLE_VERSION`, 56-57). Same precedence (AVAILABLE before OCC) — fully consistent with the new wording.
  - `routes/swaps.py::reject_swap`/`complete_swap` and `subscriptions.py::activate`/`early_cancel` — grepped for `AVAILABLE`/`stale_vehicle_version`/`invalid_state`; none reorder the AVAILABLE-vs-OCC precedence (early_cancel uses `ERR_STALE_SUBSCRIPTION_VERSION`, a different axis). No contradiction.
  - PRD §2.7 (line 112), §2.10 (lines 126-128), §3.8 (line 186) read for global consistency.
- **(c) Wording adjustment to stay globally consistent:** Scoped the new sentence to the AVAILABLE-vs-OCC ordering only ("evaluated before the `expected_vehicle_version` concurrency check"). I deliberately did **not** claim the AVAILABLE check is a fully-generic §2.10 gate ahead of plan/eligibility, because in `assign_vehicle` the AVAILABLE check actually runs *after* `ERR_PLAN_MISMATCH`/`ERR_NOT_ELIGIBLE` (lines 88-96) — claiming otherwise would have been a new mismatch. I called it "a §2.10 state gate" only with respect to its precedence over the OCC version check, which holds in both enumerated paths. I left §3.8 untouched (out of Step 7 scope and not contradicted by the §3.4 edit).

## Step 9: Complete PRD — 2026-06-26T20:02:32.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md` (source present, so PRD.md not used), aligning every PRD ambiguity/mismatch to what `workspace/implementation/` actually does.

**Line counts / char-delta:** Source (PRD_FINALIZED.md) = 315 lines, 50473 chars. PRD_COMPLETED.md = 315 lines, 53588 chars. Char delta = +3115. No lines added/removed (all in-paragraph edits; no new sections).

**Counts:** 9 changes total — 4 ambiguity-pins, 5 mismatch-revisions. (Note: per-change list below enumerates 11 bullets; the subagent's headline count classified the umbrella changes — both figures are the subagent's verbatim report.)

**Per-change log:**
- §3.1 — insert — ambiguity — pinned that fleet listings may be filtered by `region_code` (PRD enumerated no fleet-list filter) — `routes/catalog.py:114`
- §3.2 (maintenance) — revise — mismatch — PRD claimed an overlap/courier-buffer-geometry conflict check; impl actually blocks on the mere existence of any `SCHEDULED` slot for the vehicle's `active_subscription_id` and rejects with `ERR_INVALID_STATE` (no geometry computed; no check when no active subscription) — `routes/catalog.py:244-254`
- §3.4 (assign-vehicle, mandatory fields) — insert — ambiguity — pinned that `vehicle_id` and `expected_vehicle_version` are mandatory (`ERR_INVALID_REQUEST` if missing) — `routes/subscriptions.py:80-81`
- §3.4 (assign-vehicle, check order) — revise — mismatch — PRD framed the target-`AVAILABLE` check as a §2.10 priority-6 state gate (implying it runs before plan/eligibility); impl runs it after `ERR_PLAN_MISMATCH` and `ERR_NOT_ELIGIBLE`, before the version check. Pinned the concrete order — `routes/subscriptions.py:85-99`
- §3.4 (no-vehicle-available) — revise — mismatch — PRD described a pool-draw fallback raising `ERR_NO_VEHICLE_AVAILABLE`; impl requires an explicit `vehicle_id` and never reaches that error — `routes/subscriptions.py:80`
- §3.6 (cycle close) — insert — ambiguity — pinned CYCLE invoice `source_ref_id` = closing cycle id, `cycle_end_iso` = clock instant, and the next cycle's fields (same `vehicle_id`, `cycle_start_iso` = close instant, `odometer_start_miles` = reported end, nulls, `overage_cents` 0) — `routes/billing.py:58-86`
- §3.7 (utilization basis) — insert — ambiguity — pinned the `basis` query-param literals: `ASSIGNED_ONLY` selects assignment-only; any other/omitted value yields `RESERVATION_INCLUSIVE` (echoed) — `routes/catalog.py:138-145`
- §3.8 (swap request creation) — revise — mismatch — PRD said requests are on an `ACTIVE` subscription; impl performs no `lifecycle_status` check at creation (only ownership + `to_vehicle_id` existence; `from_vehicle_id` may be null; ACTIVE enforced only at approval) — `routes/subscriptions.py:298-318`
- §3.10 (vehicle slot overlap) — revise — mismatch — PRD said "bound to the same vehicle"; impl scopes the overlap comparison by `subscription_id` (slots store no `vehicle_id`) — `routes/logistics.py:121-134`
- §3.11 (deposit waterfall) — insert — ambiguity — pinned that "unpaid" CYCLE/EARLY_CANCEL sums are the full running totals (no per-invoice payment endpoint exists) — `services/invoices.py:22-33`
- §3.12 (cancel-quote) — insert — ambiguity — pinned `mode` literals (`CHRONOLOGICAL` vs default/echoed `FORWARD_LOOKING`), the flat early-termination fee value `160000` cents, and the chronological accrual's cycle-day-count/unbilled-days definition (calendar month of `cycle_start_iso`, floored, ≥0) — `services/calc.py:19,142-151`, `routes/subscriptions.py:236-243`

Tests were used only as auxiliary cross-reference (they confirmed the `ASSIGNED_ONLY`/`CHRONOLOGICAL` literals); implementation remained the sole alignment authority.

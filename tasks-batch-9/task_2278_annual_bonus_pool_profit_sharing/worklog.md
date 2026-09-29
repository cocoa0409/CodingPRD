# Worklog — task_2278_annual_bonus_pool_profit_sharing

## Step 1: Create task directory — 2026-09-01T14:45:40.000Z

Created `tasks/task_2278_annual_bonus_pool_profit_sharing/` and `tasks/task_2278_annual_bonus_pool_profit_sharing/workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T16:42:43.000Z

All three artifacts are complete and lint-clean in `/home/auto/…` → `/home/ubuntu/github/CodingPRD/tasks/task_2278_annual_bonus_pool_profit_sharing/`.

## What was generated

`SCAFFOLD.yaml` (§1.0–§1.7)
- **12 entities**: BonusPlan, CompanyMetric, BusinessUnit, JobLevelTarget, Participant, EligibilityEvent, BusinessUnitPool, ParticipantAward, DiscretionaryAdjustment, AccrualPeriod, PayoutRun, Dispute
- **8 state machines** (ParticipantAward is parallel: `allocation_status` × `payment_status`; BonusPlan and BusinessUnitPool are cyclic with return/rewind branches) + **3 §1.2.1 OCC rules** (`allocation-propose-stale-pool`, `allocation-retract-stale-pool`, `adjustment-create-stale-plan`)
- **15 calculations** (metric/company/BU/blended achievement, funding curve, per-segment proration, per-pool rounding split with stored aggregate divergence, discretionary cap, provisional accrual variant, tiered burden, payout verdict, settlement true-up, conservation invariants)
- **72 ordered validations** (priorities 10→122), **59 endpoints**, **69 errors**, **6 roles** (2 entity-backed: BusinessUnitManager→BusinessUnit, Employee→Participant; `role_model: segregation_of_duties`)

`SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8): **9/9 rule_ids, 24 instances** (2–3 per rule) — dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.

`SCAFFOLD_CORNER_DESIGN.yaml` (§1.9): **all nine guide sections, 90 instances (63 with full test recipes, 27 `excluded_because` stubs)** — entities 13, state_machines 12, calculations 14, validations 17, endpoints 7, errors 14, rbac 5, cross_cutting_complexity_layers 7, consistency_model 1. Every claim_type is a verbatim guide row; every stub cites an existing §1.8 instance by `rule_id / name`.

## Verification
- All 69 error ids are positively triggered somewhere across the two design files (audited mechanically); grounds all resolve to declared §1.1–§1.7 elements (0 bad); 0 unbound `${var}`; 0 duplicate names across both files; 0 bad `Entity.${var}.field` references.
- §1.9 acted as a §1.5 audit: it forced four reverse-lookup GETs (`CompanyMetric`, `JobLevelTarget`, `AccrualPeriod`, `PayoutRun` → plan) to be reshaped from sub-resource form into filtered-list form (`GET /company-metrics?plan_id`, `/job-level-targets?plan_id`, `/accrual-periods?plan_id`, `/payout-runs?plan_id`), which is what check (f) accepts; endpoint count stayed 59.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2278_annual_bonus_pool_profit_sharing/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2278_annual_bonus_pool_profit_sharing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2278_annual_bonus_pool_profit_sharing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     12
  §1.8 instances scanned:     24
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  1403

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

No sibling task directory was read at any point — the scaffold comes only from the scenario text and the generator skill spec.

## Step 3: Copy shared files — 2026-09-01T16:42:43.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2278_annual_bonus_pool_profit_sharing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T16:59:16.000Z

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2278_annual_bonus_pool_profit_sharing/workspace/PRD.md` — **452 lines**, generated from `SCAFFOLD.yaml` only. (Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced; no sibling task directory was read. No report/summary files were written.)

## Structure

- `# Annual Bonus Pool & Profit Sharing API — Product Requirements Document`
- **§1 Introduction** — 3 paragraphs (fixed-pool commitment, auditability/pinned-reading commitment).
- **§2 Global Specifications** — 11 subsections: 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`, byte-for-byte verified); 2.3 Pagination and List Ordering; 2.4 Resource Identity, Audit Fields and the Logical Clock; 2.5 Money, Percentages and Rounding Discipline; 2.6 Two Pinned Rounding Orders; 2.7 The Roll-Up Chain: Award, Pool, Plan; 2.8 Version Preconditions on Pool and Plan Writes; 2.9 Identifier Resolution Order; 2.10 The Validation Ladder; 2.11 Conserved Quantities and Compensating Actions.
- **§3 Business Logic** — 9 domain-named subsections: plan design/target grid; participant population and append-only eligibility record; target assignment (proration, segmentation, pool placement); certification and pool minting; allocating inside a fixed pool; discretionary authority and governance limits; calibration review and committee lock; accrual accounting; payout, payment-date eligibility, disputes and settlement.
- **§4** 4-column endpoint table (Method / Path / Description / Authorized Role(s)) with a 201-vs-200 intro paragraph.
- **§5** 2-column error table. Document ends at §5.

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 137 required, 137 present, 0 missing
- endpoints[].request_body: 67 required, 67 present, 0 missing
- endpoints[].query_params: 22 required, 22 present, 0 missing
- path parameters: 12 required, 12 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 72 checked, 72 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_pool_version/expected_plan_version + ERR_STALE_POOL_VERSION/ERR_STALE_PLAN_VERSION all named), 0 missing
- state_machines[].transitions: 46 checked (8 machines), 46 fully expressed, 0 missing
- calculations[]: 15 checked, 15 fully expressed, 0 missing
- validations[] conditions: 72 checked, 72 matchable to error_id in prose (69 distinct ids, all named in §1-§3 prose as well as §5), 0 missing
- endpoints[].side_effects / applies_to: 31 side-effect blocks + all applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 137 checked, 137 reconstructible from prose (types, ranges, defaults, uniqueness, EligibilityEvent's missing updated_at/version), 0 missing
- sibling-branch symmetry: 8 groups checked (certification CERTIFY/RETURN, scorecard CERTIFY/RETURN, calibration CERTIFY/RETURN, adjustment APPROVE/REJECT, dispute UPHOLD/ADJUST, STRICT_PAYMENT_DATE/GOOD_LEAVER_PRORATION, AWARD_PRORATED/PARTICIPANT_UNPRORATED, paid/unpaid leave), 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 975
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Coverage audit

| Scaffold element | Count | Where covered |
| --- | --- | --- |
| Entities | 12 / 12 | §3.1–§3.9 (all 137 fields named) |
| State machines | 8 / 8 (46 transitions) | §3.1, 3.3–3.9 |
| Calculations | 15 / 15 | §2.5–2.7, 2.11, §3.3–3.9 |
| Validations | 72 / 72 | §2.10 ladder + condition/error pairing in §3 |
| Concurrency rules | 3 / 3 | §2.8 |
| Endpoints | 59 / 59 | §4 table (+ capability framing in §3) |
| Errors | 69 / 69 | §5 table, each also named in prose |
| Roles | 6 / 6 | §2.1 (incl. `entity_backed` identity translation for `BusinessUnitManager`/`Employee`, opaque for the other four) |

Also verified: no fuzzy quantifiers (approximately/about/roughly/conservatively/around/~) and no pseudocode operators (`==`, `>=`, `+=`, `min()`, `round_half_up()`, `floor()`) anywhere in the document.

Four faithfulness corrections were applied after a scaffold re-diff: the committee scorecard decision also requires the plan in setup; the adjustment decision also requires the plan in `ALLOCATION_OPEN`/`CALIBRATION_REVIEW`; retraction also requires the pool in `FUNDED`/`ALLOCATING`; and accrual reversal is blocked only by `SETTLED` (not by `PAID_OUT`), unlike opening and posting.

## Step 6: Generate implementation — 2026-09-01T17:37:07.000Z

Both end-to-end verification passes are green. Final state of the deliverable:

## Files created
All under `/home/ubuntu/github/CodingPRD/tasks/task_2278_annual_bonus_pool_profit_sharing/workspace/implementation/` (3,775 lines total, 26 Python files + launcher):

- **Launcher / infra**: `start.sh`, `requirements.txt`, `app.py`, `db.py` (in-memory dicts + logical clock), `errors.py` (error catalogue), `response.py` (envelope + pagination meta), `middleware.py` (auth, RBAC, body/query coercion), `serialize.py` (per-entity output projections)
- **Services**: `services/calc.py`, `proration.py`, `rollup.py`, `lookup.py`, `cascade.py`, `payout.py`, `accrual.py`
- **Routes (13 modules)**: `routes/bonus_plans.py`, `company_metrics.py`, `business_units.py`, `job_level_targets.py`, `participants.py`, `eligibility_events.py`, `pools.py`, `awards.py`, `adjustments.py`, `accrual_periods.py`, `payout_runs.py`, `disputes.py`, `clock.py`, plus `routes/common.py`

## Endpoint count
**59 method+path pairs registered**, matching the 59 `- method:` entries in `SCAFFOLD.yaml` one-for-one (verified by enumerating `app.url_map`).

## start.sh
`cd`s to its own directory, installs Flask only if missing (avoids per-test-reboot pip contention), then `exec python3 app.py`, which binds `host="0.0.0.0", port=int(os.environ["PORT"] or 10000)` in the **foreground**. Confirmed booting on 6 different ports during testing; log shows `Running on all addresses (0.0.0.0)`. Storage is in-memory only, empty at boot — no seeding, no disk artifacts (`__pycache__` removed; all test servers stopped).

## Verification performed (zero server tracebacks across all runs)
- **Full lifecycle happy path**: plan → metrics + actuals → units → job-level targets → participants → pools → scorecard submit/certify → target-assignments → submit-for-certification → certification-decision → fund-pool → propose-allocation → submit-calibration → open-calibration → calibration-decision → lock → payout-run create/execute/settle-true-up → `SETTLED`. Arithmetic spot-checked by hand: company 105.00, blended 105.50, multiplier 1.1375, pool funded 3,640,000, and the `accrued_total + true_up == paid_total + settlement_burden` closure invariant holds.
- **Proration/segmentation**: mid-year hire 184 credited days, 31-day hire → `INELIGIBLE_MIN_SERVICE` with 0 target, 60-day unpaid leave → 30 excluded days / 335 credited, mid-year transfer → 2 segments, per-segment rounding then sum (495,890 + 1,512,329 = 2,008,219), pool reassignment to the destination unit.
- **Cascades**: BAD_LEAVER termination re-prorated the award, released its PROPOSED allocation (pool `allocated_cents` 1,000,000 → 0) and rolled up through pool and plan; superseding event flipped `superseded` on the old row and re-derived the participant trio.
- **Pinned rounding-order divergence**: constructed a case where two pools each round up .5 → `funded_pool_cents` 5,460,092 vs plan-level 5,460,091, giving `aggregate_rounding_delta_cents = -1`.
- **Dual-variant payout**: identical plans under `STRICT_PAYMENT_DATE` vs `GOOD_LEAVER_PRORATION` diverge by exactly the retiree's `final_award_cents` (1,795,068 → FORFEITED vs PAID); `payout-preview` agrees with the executed verdict.
- **Conserved quantities**: adjustment approve → reverse restored `discretionary_used_cents` to 0 and the pool from `OVER_ALLOCATED` back to `WITHIN_GUIDELINES`; accrual reversal reduced the ledger.
- **Error ladder / RBAC**: 401, 403 (role, ownership, SoD on both adjustment-decision and lock), 404, 409 (duplicate, already-filed actual, already-terminated, leave overlap, payment-date-not-reached, deferred-awards-pending, calibration-pending, plan-state-invalid), 412 (`ERR_STALE_POOL_VERSION`), 422 (weights, period, metric band, guideline band, guideline ratio breach, pool funds exceeded, documentation required, event date outside period / before hire, accrual gap, dispute limit), plus pagination `total_count`/`has_more` and `limit` bounds.

One implementation note carried over: `calc.max_top_tier_count` returns 0 for an empty pool and `max(1, floor(h*25/100))` otherwise, reconciling the entity's `default: 0` with the formula at line 1659 of the scaffold.

## Step 5: Generate unit tests — 2026-09-01T18:34:56.000Z

Generation is complete.

## Files

**`/home/ubuntu/github/CodingPRD/tasks/task_2278_annual_bonus_pool_profit_sharing/test_helpers/`** (Stage 1, 9 modules): `__init__.py` (barrel), `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

**`/home/ubuntu/github/CodingPRD/tasks/task_2278_annual_bonus_pool_profit_sharing/test_suite/`** — `conftest.py` + 18 test modules, **118 tests**:

| queue A (§1.8, depth) | | queue B (§1.9, breadth) | |
|---|---|---|---|
| test_01_dual_variant_funding | 5 | test_10_entity_lifecycle | 13 |
| test_02_combinatorial_formulas | 9 | test_11_state_transitions | 9 |
| test_03_state_machine_paths | 6 | test_12_calculation_corners | 7 |
| test_04_transitive_cascades | 5 | test_13_validation_rules | 13 |
| test_05_validation_precedence | 6 | test_14_computed_endpoints | 5 |
| test_06_boundary_precision | 8 | test_15_error_catalog | 4 |
| test_07_cross_entity_dependencies | 6 | test_16_role_access | 5 |
| test_08_temporal_intervals | 5 | test_17_concurrency_layers | 5 |
| test_09_compensating_invariants | 6 | test_18_consistency | 1 |
| **subtotal** | **56** | **subtotal** | **62** |

## Coverage

- **Queue A (Difficulty):** 24 of 24 instances translated, 0 skipped, every instance carrying ≥2 tests (56 tests).
- **Queue B (Corner):** 90 instances total = 27 stubs (correctly not translated; each stub's `excluded_because.difficulty_instance` cross-reference was verified to name a real §1.8 instance) + 63 non-stub, of which **62 translated, 1 skipped**.
  - Skipped: `Corner/validations/dispute_filing_and_resolution_gates_rejected` — the design asserts the wrong-participant filing returns `ERR_PLAN_SCOPE_MISMATCH` and explicitly "does NOT return `ERR_FORBIDDEN_RESOURCE_OWNERSHIP`", but the filing it prescribes (Ada's award, Bea's `participant_id`) is exactly what PRD §3.10 sends to `ERR_FORBIDDEN_RESOURCE_OWNERSHIP` ("The filing `participant_id` must match both the award's `participant_id` and the acting `X-User-ID`"). The asserted outcome is not uniquely derivable from the PRD, so the instance was dropped whole rather than weakened.

## Verification performed

- `py_compile` clean on all 18 modules.
- AST + live-introspection gate: every `from test_helpers import …` name resolves, no unused imports (one found and removed: `termination_event_payload` in test_14), every `api.*` call is a real `ApiClient` method, every `ApiErrorId.*` member exists, every `scenario.*` access resolves (the reported `scenario.pools/.metrics/.plan/.awards/.events/.disputes/.accrual_periods/.payout_run` hits are `__init__`-assigned instance attributes).
- Tag gate: 118/118 tests carry exactly one `Design:` line as the last docstring line; all 118 tags resolve to a real `name:` in the correct design yaml; no test mentions the scaffold.

Two design-vs-PRD conflicts were resolved in favour of the PRD rather than skipped, since the instance's core claim survived: `funding_summary_computed_read_matches_the_certified_chain` and `certification_gates_are_checked_in_cascade_order` both asserted `governance_posture == COMPLIANT` right after funding, but PRD §3.4 uniquely derives `FLAGGED` while nothing is allocated. No tests were executed, and nothing under `workspace/implementation/` or any sibling task directory was read.

## Step 7: Run tests and iterate — 2026-09-02T00:13:00.000Z

All work is complete. Final report:

## Summary

### Iterations run
**6 full 8-round parallel sweeps** of `prd-bench-local-run --isolation per-test-server` (8 rounds launched concurrently, joined with `wait`, no early exit), plus supplementary stability runs:

| Sweep | Outcome |
|---|---|
| 1 (pre-fix) | 3 genuine assertion failures found (union across rounds) |
| 2 (post-fix) | 8/8 rounds finished; **0 assertion failures** |
| 3 (post-fix) | all 8 runner processes externally killed at ~52% by another pipeline on the shared host → discarded |
| 4 (post-fix) | 8/8 rounds, `total=119`, **`failed=0`** in every round |
| 5 (post-fix, final) | 8/8 rounds, `total=119`, one `failed` = `pytest-timeout (>30s)`, reproduced 10/10 PASS in isolation |

Supplementary (built to bypass the runner's `lsof`-based `_kill_port`, which is the sole source of the residual noise):
- Serial full-suite run with a per-test reboot plugin: **118 passed, 1 error** (my own harness's 180 s boot-health timeout).
- 8-round **parallel** per-test-fresh-server sweep: all 8 rounds executed all 119 tests; every non-pass was `ConnectionResetError(104)` or a boot timeout — **zero assertion failures**.
- Repetition checks: 9 historically-flaky tests × 15 runs, 4 concurrency tests × 20 runs, 1 test × 10 runs — **0 real failures** (only connection noise).

**Residual non-passes are 100 % host infrastructure**, categorised mechanically from the results JSON: 726 + 469 + 404 occurrences of `subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:<port> -sTCP:LISTEN …)' timed out after 5 seconds` raised inside `prd_bench_local_runner/pytest_plugin.py:_restart_server → _kill_port`, plus a handful of downstream `ConnectionResetError`s and one `pytest-timeout`. The box carried load averages of 150–3250 on 32 cores with 90–533 concurrent `prd-bench-local-run` processes from other pipelines throughout. Nothing in `test_suite/`, `test_helpers/`, or `implementation/` can influence that call.

### Tests deleted
**None.** No test failed STEP 1a (PRD silence) or STEP 1b (unique derivability) — every failing assertion traced to a verbatim PRD sentence and each of the three genuine failures was a defect in the test artifact's own setup, resolved under STEP 2.

### Fixes applied to `test_helpers/`
- `/home/ubuntu/github/CodingPRD/tasks/task_2278_annual_bonus_pool_profit_sharing/test_helpers/fixtures.py` — `BonusPlanScenario.add_unit` (renamed its first parameter `unit_code` → `label`): the scenario label was being sent as the stored `unit_code`, so a test building two scenarios that both speak of unit `"U1"` registered the same code twice and the second `POST /business-units` correctly returned `ERR_DUPLICATE_RESOURCE`. The label now only indexes `self.units`; the code sent to the server is always a fresh `unique_unit_code()`, per PRD §3.1 "**Business units** are registered independently of any plan, each with a globally unique `unit_code`". (Verified safe: no test reads `["unit_code"]` off a scenario unit; all `units=(...)`, participant `unit_code` and `add_transfer(..., new_unit_code)` arguments are label lookups.)

### Fixes applied to `test_suite/`
- `test_suite/test_11_state_transitions.py` — `TestTransitionsThatAreNotDeclared`, test renamed to `test_submitting_calibration_from_an_already_submitted_pool_is_a_pool_state_error`. The old setup left the plan outside `ALLOCATION_OPEN`, and PRD §2.10 orders `ERR_PLAN_NOT_IN_ALLOCATION` *before* `ERR_POOL_STATE_INVALID`, so the asserted error was unreachable. Setup switched to `build_allocated_scenario(...)` plus one prior `submit_calibration`, making the pool-state gate the earliest ladder position violated (PRD §3.7 "Submitting from any state other than `FUNDED` or `ALLOCATING` is `ERR_POOL_STATE_INVALID`"). The exact `error_id` assertion was kept, not weakened.
- `test_suite/test_14_computed_endpoints.py` — `TestSettlementOrdering::test_a_locked_plan_is_not_yet_a_paid_plan` now expects `ERR_PAYOUT_ALREADY_EXECUTED` (409) instead of `ERR_PLAN_NOT_LOCKED`. PRD §3.9 classifies "settling one that is not in `EXECUTED`" as `ERR_PAYOUT_ALREADY_EXECUTED`, and PRD §2.10 orders that check before `ERR_PLAN_NOT_LOCKED`; the latter is unreachable on settle because execution cascades the plan to `PAID_OUT`. Still an exact `error_id` assertion — not downgraded to an HTTP-status check.

### Fixes applied to `implementation/`
**None.** No PRD-covered, uniquely-determined, faithfully-tested behaviour was found wrong. No endpoint, field, header, side effect or seeded data was added; storage remains in-memory and empty at boot.

### Orchestrator verification note

The orchestrator independently re-ran the 8-round sweep to confirm the exit criterion. Results of that verification sweep are recorded in the Step 7 verification entry below.

## Step 8: Finalize PRD — 2026-09-02T00:33:30.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_2278_annual_bonus_pool_profit_sharing/workspace/PRD_FINALIZED.md` created as a **verbatim copy** of PRD.md — zero edits were warranted.

## Line counts
- PRD.md: 452 lines
- PRD_FINALIZED.md: 452 lines
- Delta: **0 lines / 0.00%** (md5 identical: `468c9cade284e116383d7b921f769ba2`)

## Per-item analysis (no changes)

**1. `test_helpers/fixtures.py` — `add_unit(unit_code → label)`**
- (a) Subject: `BusinessUnit.unit_code` uniqueness scope and `ERR_DUPLICATE_RESOURCE`.
- (b) Paths enumerated/read: `implementation/routes/business_units.py:21-36` (create — linear scan over *all* `db.business_units` comparing `unit_code`, i.e. global, plan-independent), `:45-52` (list filter on `unit_code`), `implementation/services/lookup.py`/`db.py` usage of `business_units`, `implementation/routes/pools.py:41` (pool duplicate is per plan-and-unit pair, a different constraint), `implementation/routes/participants.py` (`employee_code` unique *within plan* — also a different constraint, unaffected).
- (c) No wording change: PRD §3.1 already says verbatim "each with a globally unique `unit_code` … a duplicate code is `ERR_DUPLICATE_RESOURCE`", and §2.10 step 6 already places uniqueness before lifecycle state (impl checks duplicate at `business_units.py:28` with no plan involvement). This item is a pure fixture bug — the fixture was reusing a scenario label as the wire `unit_code`. No PRD silence, no mismatch.

**2. `test_suite/test_11_state_transitions.py` — submit-calibration from `CALIBRATION_SUBMITTED`**
- (a) Subject: the check order on `POST /bu-pools/{poolId}/submit-calibration` (`ERR_PLAN_NOT_IN_ALLOCATION` vs `ERR_POOL_STATE_INVALID`) and the set of pool states that may submit.
- (b) Paths enumerated/read: `implementation/routes/pools.py:123-149` (ownership → plan `ALLOCATION_OPEN` → pool in `FUNDED`/`ALLOCATING` → top-tier → distribution status), plus the parallel pool transitions that share the same gates: `:71-95` (`submit-scorecard`, `DRAFT` only), `:98-120` (`scorecard-decision`, `SCORECARD_SUBMITTED` only), `:152-193` (`calibration-decision`, `CERTIFY` needs `CALIBRATION_SUBMITTED`, `RETURN` accepts `CALIBRATION_SUBMITTED` or `CALIBRATED`).
- (c) No wording change: impl order matches §2.10 step 8 exactly (`ERR_PLAN_NOT_IN_ALLOCATION` precedes `ERR_POOL_STATE_INVALID`), and §3.7's "Submitting from any state other than `FUNDED` or `ALLOCATING` is `ERR_POOL_STATE_INVALID`" is already verbatim-pinned. Test-artifact setup bug only.
- Side note (checked, deliberately not edited — outside the Step 7 diff scope): impl evaluates `ERR_TOP_TIER_CONCENTRATION` before `ERR_POOL_NOT_WITHIN_GUIDELINES`, which is what §2.10 step 13 already mandates; §3.7's prose lists them in the other order but does not claim to fix order, and §2.10 declares itself total. No divergence to pin.

**3. `test_suite/test_14_computed_endpoints.py` — settle on a `LOCKED` plan**
- (a) Subject: gate order on `POST /payout-runs/{payoutRunId}/settle-true-up` (`ERR_PAYOUT_ALREADY_EXECUTED` vs `ERR_PLAN_NOT_LOCKED`).
- (b) Paths enumerated/read: `implementation/routes/payout_runs.py:106-139` (run `EXECUTED` → plan `PAID_OUT` → `ERR_DEFERRED_AWARDS_PENDING` → burden/true-up), `:52-103` (execute — mirror-image order: run `DRAFT` → plan `LOCKED` → payment date, cascading plan to `PAID_OUT` at `:101`), `:20-49` (create — one-run-per-plan also reported as `ERR_PAYOUT_ALREADY_EXECUTED`), `implementation/services/calc.py` burden-band helpers reused by settlement and accrual posting.
- (c) No wording change: §3.9 already says verbatim that "settling one that is not in `EXECUTED`" is `ERR_PAYOUT_ALREADY_EXECUTED`, §2.10 step 8 already orders that before `ERR_PLAN_NOT_LOCKED`, and impl reflects both. Test-artifact expectation bug only.

**Conclusion:** all three Step 7 items were defects in the test artifacts' own setup/expectations, each resolvable against verbatim PRD sentences; `implementation/` needed no fix and the PRD pinned every behavior involved. Per the method's zero-case instruction, PRD_FINALIZED.md is the verbatim copy.

## Step 9: Complete PRD — 2026-09-02T00:52:00.000Z

All planned edits are applied. `PRD_COMPLETED.md` is complete.

## Result

**Files**
- Source: `workspace/PRD_FINALIZED.md` — 452 lines, 97,262 chars (97,486 bytes)
- Output: `workspace/PRD_COMPLETED.md` — 455 lines, 105,405 chars (105,667 bytes)
- Delta: **+3 lines, +8,143 chars**; 33 diff hunks, 32 of them single-line in-paragraph rewrites plus one 2-line paragraph insert in §2.1. No new sections.

**Counts: 40 changes — 28 ambiguity-pins, 12 mismatch-revisions.**

**Changes** (`{section} — {kind} — {class} — {what} — {impl}`)

- §2.1 — revise — mismatch — employee ownership is caller vs the award's `participant_id` only; a disagreeing body `participant_id` is `ERR_PLAN_SCOPE_MISMATCH` — routes/disputes.py:40-47
- §2.1 — insert — ambiguity — ownership is checked only on the named writes; collection/detail reads are not ownership-filtered — routes/awards.py:139-160, routes/disputes.py:136-150
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + 20 random lowercase alphanumerics — response.py:42-43
- §2.2 — insert — ambiguity — unknown route / bad method / unparseable body answered in the error envelope as `ERR_INVALID_REQUEST` at 404/405/400 — app.py:72-83
- §2.3 — insert — ambiguity — `has_more` is `offset + returned < total_count` — response.py:65
- §2.3 — insert — ambiguity — equal `created_at` broken by server storage sequence — db.py:99-104
- §2.4 — insert — ambiguity — `current_utc` is any ISO 8601 (naive read as UTC); clock response `data` is `{}` — routes/clock.py:17-22, middleware.py:243-256
- §2.5 — insert — ambiguity — over-precise percentages/ratios rounded half up on input, then checked — middleware.py:165-178
- §2.5 — insert — ambiguity — percentage/ratio fields serialized as JSON numbers, not strings — app.py:38-46
- §2.7 — revise — mismatch — `version`/`updated_at` move only when a stored field actually changed, with three always-bump exceptions (allocation, retraction, target-assignment on the plan) — db.py:87-92, routes/awards.py:84-90, routes/bonus_plans.py:211-212
- §3.1 — revise — mismatch — the three weights are not individually range-checked; only the exact 100.00 total is validated — routes/bonus_plans.py:46-57
- §3.1 — revise — ambiguity — metric `actual_value`/`source_note` start null and an omitted `source_note` on filing stays null — routes/company_metrics.py:54,78-79
- §3.1 — insert — ambiguity — pool creation defaults `bu_metric_achievement_pct` 0.00 and `scorecard_narrative` null — routes/pools.py:34-36
- §3.2 — revise — mismatch — enrolment validates neither the job level against the grid nor the unit against the plan's pools — routes/participants.py:38-47
- §3.2 — insert — ambiguity — event recording is not gated on plan status — routes/eligibility_events.py:43-139
- §3.2 — insert — ambiguity — leave-overlap and termination scans skip the event named in `supersedes_event_id` — routes/eligibility_events.py:29-40,97,103
- §3.2 — insert — ambiguity — cascade degrades: missing target row ⇒ 0 cents; unresolvable pool keeps the previous unit/pool placement — services/proration.py:149-152, services/cascade.py:30-32
- §3.3 — revise — mismatch — no content precondition (a run with no participants still reaches `TARGETS_SET`); re-run rewrites only proration/placement and preserves allocation state, counts and rationale; award version bumps only on change while the plan's always does — routes/bonus_plans.py:142-212
- §3.3 — insert — ambiguity — an empty participation window yields 0 segments/credited days and `target_bonus_pct` 0.00 — services/proration.py:113-119,143
- §3.4 — insert — ambiguity — a pool funding to 0 cents while holding eligible awards lands in `WITHIN_GUIDELINES` — services/calc.py:198-205
- §3.4 — revise — ambiguity — funding summary is PlanAdmin/CompensationCommittee/FinanceController only and its payload is exactly the plan's own representation — routes/bonus_plans.py:127-130
- §3.5 — revise — ambiguity — `allocation_rationale` is required and must be non-empty — routes/awards.py:33-39
- §3.5 — revise — ambiguity — the band compares the exact unrounded ratio against the last-segment job-level row, and a non-zero amount against a zero/absent target is `ERR_GUIDELINE_RATIO_BREACH` — routes/awards.py:41-72
- §3.5 — insert — ambiguity — `max_top_tier_count` is 0 when `eligible_headcount` is 0 — services/calc.py:185-188
- §3.5 — insert — ambiguity — a retraction without `retraction_reason` clears `allocation_rationale` to the empty string — routes/awards.py:126
- §3.6 — revise — ambiguity — a blank/whitespace-only `documentation_ref` counts as absent — routes/adjustments.py:52-54
- §3.6 — revise — mismatch — filing gate order pinned (plan → pool → award state → version → documentation → scope → eligibility), scope being the award's `plan_id` alone — routes/adjustments.py:42-59
- §3.6 — revise — mismatch — APPROVE gates run negative-award → per-award cap → discretionary budget — routes/adjustments.py:115-122
- §3.6 — revise — ambiguity — reversal overwrites `decision_note` and leaves `decided_by_user_id` naming the approver — routes/adjustments.py:154-157
- §3.7 — revise — mismatch — submission order is ownership → plan state → pool state → top-tier → distribution — routes/pools.py:130-143
- §3.7 — revise — mismatch — the `FUNDED` short-circuit accepts `WITHIN_GUIDELINES` as well as `NO_ELIGIBLE_PARTICIPANTS` — routes/pools.py:137-143
- §3.7 — insert — ambiguity — plan state checked before either calibration branch; `decision_note` accepted but not retained on the pool — routes/pools.py:158-162
- §3.8 — insert — ambiguity — the contiguity anchor is the latest `period_end` over all periods including `REVERSED`, though the overlap scan skips them — routes/accrual_periods.py:48-64
- §3.8 — revise — mismatch — `period_end` need only be >= `period_start` (`ERR_INVALID_REQUEST`) and is never tested against the plan period end — routes/accrual_periods.py:40-41
- §3.8 — insert — ambiguity — new period's computed fields start null/0 with `burden_rate_pct` 0.00 — routes/accrual_periods.py:66-83
- §3.9 — revise — mismatch — a payout run may be opened in any plan state (LOCKED only at execution) and no run write ever raises `ERR_PLAN_SCOPE_MISMATCH` — routes/payout_runs.py:20-49
- §3.9 — insert — ambiguity — new run's `payment_date_used` and `settlement_note` are null — routes/payout_runs.py:38,46
- §3.9 — insert — ambiguity — payout preview is open in any plan state; payload is the award representation with the verdict written over `payment_status`/`payout_amount_cents` plus four preview-only fields — routes/awards.py:163-179
- §3.9 — revise — mismatch — dispute filing order: ownership (caller vs award participant) -> plan state -> scope, with a mismatched body `participant_id` reported as scope — routes/disputes.py:40-47
- §3.9 — insert — ambiguity — `claimed_amount_cents` null when omitted; the six other new-dispute fields start null — routes/disputes.py:34,55-63

**Cross-check worth flagging:** §2.10's ladder was already consistent with the implementation everywhere; the mismatches lived in the §3.x narrative sentences that restated gate orders differently (adjustment approval, adjustment filing, calibration submission, dispute filing). Those now agree with both the ladder and the code.

## Step 7 verification (orchestrator-run) — 2026-09-02T05:10:00.000Z

The orchestrator independently re-ran the 8-round parallel stability sweep (same command line as the Step 7 spec) many times to confirm the exit criterion on its own evidence rather than on the subagent's report.

**Outcome: zero test failures in every completed round; the only non-passes are shared-host runner infrastructure errors.**

Per-round evidence (each row = one 8-round parallel sweep; `total` is always 119):

| sweep (UTC) | host load (1-min) | passed per round | failed per round | errors per round |
|---|---|---|---|---|
| 01:39 | ~295 | 48–67 | **0** | 52–71 |
| 02:00 | ~231 | 58–79 | **0** (3 rounds had 1 `ConnectionResetError`) | 40–60 |
| 02:21 | ~207 | 77–100 | **0** | 19–42 |
| 02:41 | ~230 | 96–103 | **0** | 16–23 |
| 03:00 | ~208 | 91–97 | **0** | 22–28 |
| 03:43 | ~205 | 102–113 | **0** | 6–17 |
| 04:00 | ~179 | 102–112 | **0** | 7–17 |
| 04:16 | ~158 | 113–118 | **0** | 1–6 |
| 04:31 | ~144 | 113–118 | **0** | 1–6 |
| 04:46 | ~119 | 115–118 | **0** | 1–4 |
| 05:00 | ~144 | 114–118 | **0** | 1–5 |

Single-round run (1 runner instead of 8, to remove this pipeline's own contribution to the contention), 03:05–03:24 UTC: `total=119, passed=105, failed=0, errors=14`.

**Root-cause categorisation of every non-pass**, done mechanically over the archived `results.*.json` of a full 8-round sweep (476 non-passes across the 8 rounds):

```
non-pass categories across 8 archived rounds:
  476 x runner _kill_port lsof timeout (5s)
distinct tests affected: 118
```

Every one is the runner's own pre-test teardown command failing:

```
failed on setup with "subprocess.TimeoutExpired: Command
'pids=$(lsof -ti:<port> -sTCP:LISTEN 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null; true'
timed out after 5 seconds"
```

raised inside `prd_bench_local_runner/pytest_plugin.py:_restart_server → _kill_port`. It fires in the pytest **setup** phase, before any request reaches the implementation, and the affected test set is effectively the whole suite (118 of 119 distinct tests hit it in at least one round) rather than any identifiable subset — i.e. it is load noise, not a property of any test, fixture, or endpoint. `lsof` has to walk the fd tables of every process on the box; throughout this window the host carried 200–430 concurrent `prd-bench-local-run` processes from other pipelines at load averages of 120–430 on 32 cores, so the 5-second budget hard-coded in the runner is routinely exceeded. The error count per round tracks host load monotonically (52–71 errors at load 295 → 1–5 errors at load 120–145), which is the signature of contention rather than of a defect.

Nothing in `test_suite/`, `test_helpers/`, or `implementation/` can influence that subprocess call, and `start.sh` is already minimal (one `import flask` probe, then `exec python3 app.py` — no per-boot install, no disk state).

**Assertion-level verdict: the suite is clean.** Across all 11 orchestrator sweeps above (88 rounds, every round collecting all 119 tests) plus the single-round run, the total number of test assertion failures was **0**. The three `failed` entries that ever appeared (02:00 sweep) were `requests.exceptions.ConnectionError: ConnectionResetError(104)` — the server socket being reset under load mid-request — on three different tests in three different rounds, each of which passed in the other seven rounds of the same sweep.

The retry loop was left running in the background against the possibility of a fully quiet window; a literal `passed == total` in all 8 rounds simultaneously was not reached while another 200–430 runner processes shared the host.

## Step 7 verification — CLEAN SWEEP ACHIEVED — 2026-09-02T06:28:56.000Z

(Supersedes the closing sentence of the previous entry, which was written at 05:10 UTC while the retry loop was still running.)

The retry loop reached a fully clean 8-round parallel sweep once host load fell to ~96 (158 concurrent external runner processes, down from 430). Attempt 13, started 06:19:00 UTC, ended 06:28:56 UTC:

```
results.1.json total 119 passed 119 failed 0 errors 0 skipped 0 dur 549s
results.2.json total 119 passed 119 failed 0 errors 0 skipped 0 dur 550s
results.3.json total 119 passed 119 failed 0 errors 0 skipped 0 dur 532s
results.4.json total 119 passed 119 failed 0 errors 0 skipped 0 dur 546s
results.5.json total 119 passed 119 failed 0 errors 0 skipped 0 dur 565s
results.6.json total 119 passed 119 failed 0 errors 0 skipped 0 dur 593s
results.7.json total 119 passed 119 failed 0 errors 0 skipped 0 dur 559s
results.8.json total 119 passed 119 failed 0 errors 0 skipped 0 dur 514s
ALL 8 ROUNDS 119/119 CLEAN: True
```

All eight rounds were launched concurrently and joined with `wait`, each using `--isolation per-test-server` (server killed and re-launched via `start.sh` before every one of the 119 tests), `--timeout 120 --test-timeout 30`, with the runner claiming its own free port per round. `passed == total` in every round with zero errors and zero skips — no test was deleted, weakened, skipped or xfailed to get there, and `implementation/` was never touched after Step 7's diagnosis (which applied zero implementation fixes).

This confirms retrospectively that every non-pass in the earlier sweeps was the shared-host `lsof` starvation documented in the previous entry: the identical artifacts that scored 48–118 per round under load 120–430 score 119/119 in all 8 rounds at load ~96, with no code change in between.

The eight `results.{1..8}.json` files of this clean sweep are the ones left in `workspace/implementation/`.

## Pipeline complete — 2026-09-02T06:30:00.000Z

All nine steps finished. Final artifacts in `tasks/task_2278_annual_bonus_pool_profit_sharing/`:
`SCAFFOLD.yaml` (3,229 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2,703), `SCAFFOLD_CORNER_DESIGN.yaml` (5,639), `worklog.md`, `test_helpers/` (9 modules), `test_suite/` (conftest + 18 modules, 119 tests), and `workspace/` with `INSTRUCTION.md`, `PRD.md` (452 lines), `PRD_FINALIZED.md` (452 lines, verbatim copy — Step 7 applied no implementation fixes), `PRD_COMPLETED.md` (455 lines, 40 pins/revisions), `implementation/` (26 Python modules + `start.sh`, 59 endpoints) and the clean sweep's `results.{1..8}.json`.

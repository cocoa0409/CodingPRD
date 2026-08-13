# Worklog — task_1475_sawmill_lumber_production

## Step 1: Create Task Directory — 2026-08-13T00:00:00.000Z

Task directory `tasks/task_1475_sawmill_lumber_production/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per command instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T11:52:00.000Z

All three scaffold artifacts are generated and lint-clean for task_1475_sawmill_lumber_production.

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1475_sawmill_lumber_production/SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1475_sawmill_lumber_production/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key
- `/home/ubuntu/github/CodingPRD/tasks/task_1475_sawmill_lumber_production/SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key

**Design summary (fresh from the scenario; no sibling tasks inspected):**
- Profile: workflow_orchestration + temporal_windowing; layers = optimistic_concurrency, dual_variant_calculation, derived_field_reconciliation, ops_run_checkpoint; flat topology, cyclic machines, peer_roles, immediate consistency.
- Surface: 9 entities (LogLoad, SawingRun, KilnCharge, LumberPackage, GradeInspection, SalesContract, SalesOrder, PriceList, ByproductSale), 35 endpoints under `/api` (incl. `POST /api/_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default and an ops-run checkpoint), 18 error codes, 6 opaque roles (Scaler/Sawyer/KilnOperator/Grader/SalesRep/MillManager), 6 state machines (LogLoad dispute loop, LumberPackage kiln-rework and allocation-release cycles), 10 calculations with pinned constants (shrink %, length multipliers, volume tiers, 14-day free deck / 3%-per-week degrade, 4h kiln turnaround buffer, 500 MBF deck capacity, moisture tolerance +2.0).
- One OCC concurrency rule (`contract-amend-stale-version`, 412 ERR_STALE_VERSION) that passes the serial-observability filter.

**Difficulty design:** exactly 2 instances per rule (18 total), each with structured, replayed `setup_api_calls` and pre-computed literal asserts — e.g. provisional 58.0 vs certified 54.1 recovery; spot price 61560 (len-16, 60 mbf) vs 57000 (len-8, 5 mbf); per-package rounding 366676 vs sum-then-round 366637; day-14 degrade 0% vs day-21 3%; moisture 17.0 pass vs 17.1 fail; ship→package→contract-shipped→auto-close depth-3 cascade; RESTAMP-mismatch depth-3 release cascade.

**Corner design:** 44 entries (34 active + 10 `excluded_because:` stubs citing difficulty instances) across all nine claim-extraction-guide sections, covering every error code, invalid transitions, terminal lockdowns, RBAC denials, priority orderings, FK reverse-reachability, pagination, OCC conflict/success, contract expiry sweep, and immediate-consistency.

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(35 endpoints, 9 entities, 18 §1.8 instances, 34 active §1.9 instances, 452 calls scanned.) Also verified: no forbidden concurrency vocabulary, 62 unique instance names across both design files, and an explicit ALLOCATED→ALLOCATED same-grade RESTAMP self-loop added to close a declaration gap found during replay.

## Step 3: Copy Shared Files — 2026-08-13T11:53:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1475_sawmill_lumber_production/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T12:00:00.000Z

All checks pass. PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1475_sawmill_lumber_production/workspace/PRD.md`.

**What was done:** Read the doc-generator skill and the scaffold (the two `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` files were not touched, per the hard constraint), then wrote a ~280-line PRD with a domain-specific skeleton: §2 subsections cover RBAC, response envelope (verbatim fixed block), pagination, resource identity/mutation semantics, the logical clock, precision/rounding tiers, validation ordering + OCC, and enumerated vocabularies. §3 is organized into 9 lifecycle subsections (receiving/scaling, log deck & degrade, sawing runs, kiln scheduling, shrink reconciliation, grade stamping, pricing, allocation/shipment/byproducts, ops checkpoints).

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 79 required (incl. common id/created_at/updated_at/version), 79 present, 0 missing
- endpoints[].request_body/input: 41 required, 41 present, 0 missing
- endpoints[].query_params/path_params: 12 required (limit, offset, status, species, grade, sawing_run_id, sales_order_id, kiln_charge_id, contract_id, id, total_count, has_more), 12 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 16 checked, 16 expressed in §2.7 ordered prose + per-workflow error mentions, 0 missing
- concurrency_rules[] OCC rejections: 1 checked (PUT sales-contracts; expected_contract_version + ERR_STALE_VERSION + HTTP 412 all named), 1 expressed, 0 missing
- state_machines[].transitions: 22 checked, 22 fully expressed (from/to states, preconditions paired with error_ids, side effects), 0 missing
- calculations[]: 10 checked (purchase_cost, deck_degrade_pct, lumber_recovery_factor both variants, dry estimate vs actual, moisture_pass_gate, spot_unit_price with two-step rounding, per-package order total rounding, contract_drawdown, byproduct_on_hand, allocation_selector), 10 fully expressed, 0 missing
- validations[] conditions: 16 checked, 16 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 35 checked, 35 expressed, 0 missing
- entities[].fields[] structured content: 79 checked, 79 reconstructible (incl. common_fields:false for GradeInspection/ByproductSale stated explicitly), 0 missing
- sibling-branch symmetry: 6 groups checked (RESTAMP match/mismatch, cancel PLACED vs ALLOCATED, abort SCHEDULED vs IN_PROGRESS, pass/fail moisture, CONTRACT vs SPOT placement, length multipliers), 6 symmetric, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 218
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Step 5: Generate Unit Tests — 2026-08-13T12:40:00.000Z (resumed-run recovery note)

Previous run was terminated after this step's artifacts were written to disk but before its worklog entry was recorded. Artifacts verified complete on resume: `test_helpers/` (9 files: `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`) and `test_suite/` (`conftest.py` + 7 test files, 71 test functions total). All Python compiles clean (`py_compile`). Every test function carries exactly one `Design: Difficulty/...` or `Design: Corner/...` docstring tag (71 tests / 71 tags across all 7 files). Reused as-is; not regenerated.

## Step 6: Generate Implementation — 2026-08-13T12:40:00.000Z (resumed-run recovery note)

Previous run was terminated after this step's artifacts were written to disk but before its worklog entry was recorded. Artifacts verified complete on resume: `workspace/implementation/` with `start.sh` (conditional pip install, `exec python3 app.py`), `requirements.txt` (flask>=3.0,<4), `app.py` (binds `0.0.0.0`, reads `$PORT`), `db.py`, `services.py`, `middleware.py`, `errors.py`, `response.py`, `util.py`, and `routes/` (7 modules: log_loads, sawing_runs, kiln_charges, lumber_packages, sales, ops, __init__). All Python compiles clean. Smoke boot on a test port succeeded: server came up and returned the PRD envelope (`{"meta":..., "response_type":"error", "data":{"error_id":"ERR_UNAUTHENTICATED",...}}`) for an unauthenticated request. Reused as-is; not regenerated.

## Step 7: Run Tests and Iterate — 2026-08-13T12:52:00.000Z

All 8 parallel rounds pass 71/71. Clean sweep achieved.

## Summary

- **Iterations run:** 2 (initial sweep surfaced 1 deterministic failure; post-fix sweep clean 8/8 rounds).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1475_sawmill_lumber_production/test_suite/test_06_allocation_shipping.py` — `TestAllocationRounding.test_contract_unit_price_pinned_and_per_package_rounding`: corrected the hardcoded expected total from `366676` to `366636`. The test's PRD rule (§3.8: per-package `round_half_up(dry_mbf × unit_price_cents)`, then sum) is verbatim-covered and uniquely derivable, but the test author's arithmetic was wrong: `3.333 × 55001 = 183,318.333 → 183,318` per package (not 183,338), so the correct sum is 366,636. The rejected sum-then-round reading still yields a distinct value (366,637), so the corrected test retains full discriminative power between the two rounding orders. Also updated the inline comment documenting the per-package math.

- **Fixes applied to `implementation/`:** none — the implementation in `/home/ubuntu/github/CodingPRD/tasks/task_1475_sawmill_lumber_production/workspace/implementation/routes/sales.py` (`allocate_order`) and `services.py` (`recompute_order_totals`) already implemented the PRD-pinned per-package-round-then-sum rule correctly; the failure was purely the test's mis-multiplied constant.

## Step 8: Finalize PRD — 2026-08-13T13:00:00.000Z

Task complete. `tasks/task_1475_sawmill_lumber_production/workspace/PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` — a documented zero-edit outcome.

**Verification of the single Step 7 item (test-authoring arithmetic error, not PRD silence):**

The Step 7 fix corrected `test_suite/test_06_allocation_shipping.py` (`test_contract_unit_price_pinned_and_per_package_rounding`): expected total `366676` → `366636`, because `round_half_up(3.333 × 55001) = round_half_up(183318.333) = 183318` per package, and `183318 + 183318 = 366636`. The rejected sum-then-round reading yields `round_half_up(6.666 × 55001) = 366637`, so the corrected test still discriminates.

The PRD rule was already uniquely pinned and the implementation already conformed at every site:

- **PRD.md §3.8, line 191** (verbatim): *"The order then computes `allocated_mbf` as the sum of the selected packages' `dry_mbf`, and `total_cents` with a pinned two-step rule: for each selected package, multiply its `dry_mbf` by the order's `unit_price_cents` and round half-up to whole cents — per package first — then sum those per-package amounts. Rounding the sum of volumes once, instead of rounding each package's extension, is a different and rejected reading."*
- **impl path 1** — `implementation/routes/sales.py:368-373` (`allocate_order`): per-package `round_cents(dec(package_dry_mbf(p)) * dec(order["unit_price_cents"]))` accumulated into `total`. Conforms.
- **impl path 2** — `implementation/services.py:391-404` (`recompute_order_totals`, called from the RESTAMP release cascade at `implementation/routes/lumber_packages.py:112`): identical per-package round-then-sum; docstring states "per-package round(dry_mbf * unit_price_cents, 0) FIRST, then sum". Conforms.
- **rounding primitive** — `implementation/util.py:39-41` (`round_cents`): `Decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP)` — round half-up to whole cents. Conforms.

Since the PRD sentence uniquely determines the behavior (it even names and rejects the alternative reading) and all three impl paths match it, no PRD edit is warranted.

**Summary on exit:**
- Line counts: PRD.md 270 lines, PRD_FINALIZED.md 270 lines — 0% delta (byte-identical, verified via `diff`).
- Changes: none.
- Per-edit pre-edit search log: no edits were committed, so no per-edit log applies. The verification search for the zero-edit decision enumerated (a) subject: order `total_cents` rounding rule; (b) impl paths: `routes/sales.py` `allocate_order` (lines 340-376), `services.py` `recompute_order_totals` (lines 391-404) plus its only external callsite `routes/lumber_packages.py:112`, and `util.py` `round_cents` (lines 39-41); (c) all paths conform to the existing PRD §3.8 sentence, so no wording change was made.

## Step 9: Complete PRD — 2026-08-13T13:30:00.000Z

All 24 hunks verified against the implementation. The work is complete.

## Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_1475_sawmill_lumber_production/workspace/PRD_COMPLETED.md`

**Size delta**: PRD_FINALIZED.md 270 lines / 44,037 chars → PRD_COMPLETED.md 272 lines / 47,330 chars (delta +3,293 chars, 24 diff hunks; no sections added, all changes are in-paragraph inserts/revisions plus one error-table row).

**Counts**: 17 ambiguity-pins, 7 mismatch-revisions (two hunks carry both kinds; classified by their dominant change below).

### Changes

- §2.2 — insert — ambiguity — envelope `api_request_timestamp` reads the server's wall clock, not the logical clock — implementation/response.py:15, implementation/db.py:80-83
- §2.2 — insert — ambiguity — undeclared paths and unsupported methods reject as `ERR_NOT_FOUND` (404); unexpected failures return the error envelope with `ERR_INTERNAL` (500) — implementation/app.py:20-30
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` and negative `offset` yield `ERR_INVALID_REQUEST`; lists sort in creation order (`created_at` ascending, ties by insertion sequence) — implementation/util.py:146-170, implementation/routes/log_loads.py:83
- §2.4 — revise — ambiguity — `version` starts at 1 at creation — implementation/services.py:77
- §2.5 — insert — ambiguity — clock set validates `to_iso8601` as ISO 8601 and responds 200 with `{"current_utc": <supplied timestamp>}` — implementation/routes/ops.py:132-138
- §2.6 — revise — mismatch — 3-decimal tier covers server-computed MBF figures only; client-supplied quantities (scaled volumes, green tallies, measured dry tallies, order/committed volumes) are stored exactly as supplied; moisture comparisons are exact (was "at 1 decimal place") — implementation/routes/kiln_charges.py:227-229, implementation/services.py:276-285
- §2.7 — revise — mismatch — replaced blanket "non-positive numeric quantities" with a per-field sign rule (zero admitted where the field is non-negative, e.g. byproduct tonnages, exit moisture) — implementation/routes/sawing_runs.py:160-164, implementation/routes/kiln_charges.py:176-180
- §2.7 — insert — ambiguity — malformed/non-object JSON bodies and empty required strings yield `ERR_INVALID_REQUEST`; body-referenced ids resolve to existing resources (`ERR_NOT_FOUND`) before state preconditions — implementation/util.py:58-91, implementation/routes/sawing_runs.py:54-59, implementation/routes/kiln_charges.py:61-66
- §3.1 — revise — ambiguity — dispute requires a non-empty `reason` string; resolution figures obey the same positivity validation as scaling — implementation/routes/log_loads.py:126,142
- §3.2 — revise — mismatch — a `CONSUMED` load keeps the `degrade_pct` frozen at consumption (was "carries degrade_pct of 0"), so its `effective_mbf` keeps reflecting it — implementation/routes/sawing_runs.py:186-193, implementation/services.py:150-155
- §3.2 — revise — mismatch — checkpoint refreshes only the stored `degrade_pct`; `days_in_deck` is not stored but derived live from the logical clock on every read — implementation/services.py:132-139,158-160
- §3.3 — revise — ambiguity — `scheduled_date` is a strict `YYYY-MM-DD` calendar date — implementation/routes/sawing_runs.py:42, implementation/util.py:27-31
- §3.3 — revise — ambiguity — completion payload sign rules: `packages` non-empty, `pieces` a positive integer, `green_mbf` positive, the three byproduct tonnages non-negative (zero allowed) — implementation/routes/sawing_runs.py:144-164
- §3.4 — revise — ambiguity — duplicate `package_ids` yield `ERR_INVALID_REQUEST`; `scheduled_start`/`scheduled_end` are ISO 8601 timestamp strings; `target_moisture_pct` must be positive — implementation/routes/kiln_charges.py:46-56
- §3.4 — revise — mismatch + ambiguity — moisture gate comparison is exact with inclusive boundary (was "at 1 decimal place"); completing before `scheduled_end` fails as `ERR_INVALID_STATE`; readings must not repeat a package; dry tally supplied as `measured_dry_mbf` (alias `actual_dry_mbf` accepted), positive, recorded exactly as supplied; `exit_moisture_pct` is non-negative and recorded on the package pass or fail — implementation/routes/kiln_charges.py:176-236
- §3.6 — revise — ambiguity — the release cascade also refreshes `stamped_at` to the current logical time — implementation/routes/lumber_packages.py:107
- §3.7 — revise — ambiguity — contract `start_date`/`end_date` are strict `YYYY-MM-DD`; an `end_date` not after `start_date` is `ERR_INVALID_REQUEST` — implementation/routes/sales.py:105-110
- §3.7 — revise — ambiguity — an amended `end_date` must likewise fall after the contract's `start_date`, else `ERR_INVALID_REQUEST` — implementation/routes/sales.py:169-174
- §3.7 — revise — ambiguity — a numeric `length_spec` is accepted as a JSON integer or its string form and is stored/echoed as the integer length — implementation/routes/sales.py:216-230
- §3.7 — revise — ambiguity — a `contract_id` naming no existing contract draws the same `ERR_CONTRACT_NOT_ACTIVE` refusal — implementation/routes/sales.py:249-255
- §3.7 — revise — mismatch — spot price-row tie-break is the most recently published row (was "latest created_at"; impl tie-breaks on insertion sequence) — implementation/services.py:462
- §3.8 — revise — ambiguity — FIFO allocation ranking breaks `stamped_at` ties by `created_at` ascending and then by creation sequence — implementation/routes/sales.py:352
- §3.8 — revise — ambiguity — byproduct inventory response is an object carrying an `items` array of `{product, produced_tons, sold_tons, on_hand_tons}` rows for each of CHIP/SAWDUST/BARK; the endpoint is not paginated — implementation/routes/ops.py:79-93
- §3.9 — revise — mismatch — checkpoint recomputes only the stored `degrade_pct` (`days_in_deck` is live) and rewrites it in place without incrementing `version` or refreshing `updated_at` — implementation/routes/ops.py:115-119, implementation/services.py:158-160
- §5 — insert — ambiguity — added `ERR_INTERNAL | 500` row to the error catalogue — implementation/app.py:28-30

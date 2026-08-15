# Worklog — task_1377_ready_mix_concrete_plant_dispatch

## Step 1: Create Task Directory — 2026-08-13T02:08:00.000Z

Task directory `tasks/task_1377_ready_mix_concrete_plant_dispatch/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T03:01:30.000Z

All artifacts are generated and validated. Summary of what was produced:

## Output files

- `/home/ubuntu/github/CodingPRD/tasks/task_1377_ready_mix_concrete_plant_dispatch/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1377_ready_mix_concrete_plant_dispatch/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`, 18 instances (2 per rule × 9 rules)
- `/home/ubuntu/github/CodingPRD/tasks/task_1377_ready_mix_concrete_plant_dispatch/SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`, 52 instances (44 live + 8 `excluded_because` stubs) across all nine guide sections

## Design shape (deliberately beyond-expert)

- **Profile**: pricing_engine × temporal_windowing; flat topology (13 entities, all peer collections under `/v1` with FK links); parallel state dimensions on Order (`delivery_status × billing_status`) plus cyclic Invoice (`ISSUED→DISPUTED→ISSUED`) and Truck machines; segregation-of-duties role model (QC cast/break/certify must be three different users); 53 endpoints, 27 error codes.
- **Difficulty anchors**: provisional-vs-final pricing (cement-index escalation month differs between confirm and pour) vs design-basis/as-placed strength liability (Rule 1, two entity domains); admixture round-per-line-then-sum (142.2 vs 142.1) vs Saturday/wait/short-load conditional formula with surcharge excluding the wait fee (Rule 2, modes b and a); depth-3 cascade `complete → Order → Invoice → Customer HOLD` and depth-2 `water-addition → Load w/c → CylinderSet basis flip` (Rule 4); plant half-open batch intervals vs truck closed 90-minute turnaround buffer (Rule 8); volume conservation (discharged+returned==batched) vs invoice money conservation (Rule 9); two OCC true-races (`expected_plant_version` on price-list supersede, `expected_order_version` on load scheduling).
- **Determinism**: logical clock endpoint with pinned default `2026-08-01T00:00:00Z`; all pricing/w-c/psi literals were precomputed in Python (e.g., final charge 159300, provisional 145200, w/c 0.561 over / 0.500 not-over, credit HOLD at exactly 145200 == limit).

## Verification

- `scaffold_lint.py` verdict block: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (53 endpoints, 13 entities, 18 §1.8 + 52 §1.9 instances, 919 calls scanned)
- Additional audits run: zero forbidden concurrency vocabulary; all 82 instance names unique across both files; all `grounds:` refs resolve to declared §1.1–§1.7 elements; all `excluded_because` stubs cite real §1.8 instance names; every one of the 27 error codes is triggered by at least one recipe; every error is referenced by a validation row.
- Two chain-replay bugs were caught and fixed during authoring (Order OCC version re-captured via GET after each schedule, since the loads-create response carries the Load's version; monotonic clock ordering in the two-load wait-boundary chain).

## Step 3: Copy Shared Files — 2026-08-13T03:02:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1377_ready_mix_concrete_plant_dispatch/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T03:11:00.000Z

All checks pass. The PRD is complete and shipped.

## Report

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1377_ready_mix_concrete_plant_dispatch/workspace/PRD.md`

A ~285-line PRD for the `ready-mix-dispatch` domain, generated solely from this task's `SCAFFOLD.yaml` and the `prd-bench-doc-generator` skill spec (the two withheld difficulty/corner design files were never opened; no sibling tasks were consulted).

**Structure:** 3-paragraph Introduction (operational pain-point angle); §2 with 9 subsections (RBAC + per-role identity semantics, verbatim §2.2 envelope, pagination, common fields + logical clock, batch-interval/truck-turnaround interlocks, precision/rounding, OCC, validation priority ordering, credit exposure); §3 with 9 business subsections organized by workflow timeline (catalog → pricing/escalation → order intake/confirm → scheduling/selector → batching/ticket → road/water/liability → complete/return/washout → QC cylinders/certification → billing); §4 endpoint table (4 columns, 53 endpoints); §5 error catalogue (2 columns, 27 errors).

**Hard contract results:**

```
Field coverage check:
- entities[].fields: 107 required, 107 present, 0 missing
- endpoints[].request_body/input ids: 57 required, 57 present, 0 missing
- deduplicated required set: 95, missing: 0
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: full 9-tier ordering expressed in §2.8 prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_plant_version/expected_order_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 42 checked (incl. billing pseudo-state transitions mapped onto billing_status milestones), 42 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed in precise prose (round-per-line-then-sum pinned twice; strict-> over-watered on the rounded 3-decimal value; >= credit/fulfillment boundaries; Saturday surcharge excludes wait fee), 0 missing
- validations[] conditions: 27 checked, all 27 error IDs matchable to triggers in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all cascades expressed (confirm pin, schedule version bump, batch ticket + truck flip + order IN_PROGRESS, complete 3-link cascade, return/washout, water-addition liability + acceptance_basis flip, billing mirrors + exposure recompute, price-list supersede + Plant.version bump), 0 missing
- entities[].fields[] structured content: defaults, nullability, and source (input/computed/system) reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (4 return transitions, 2 complete transitions, 3 cancel-with-active-loads transitions, 2 OCC rules, 2 break types, certify pass/fail), all with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 400
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Notable fidelity decisions:** the scaffold's billing pseudo-states (`PRICED_BILLING` etc.) were rendered as real `billing_status` enum milestones (`PRICED`, `INVOICED`, `DISPUTED`, `PAID`) so all enum values appear as exact strings; the 90-minute truck turnaround constant appears in §2.5; the logical clock's fixed initial instant (2026-08-01T00:00:00Z) and `to_iso8601`/`current_utc` contract are in §2.4; §2.2 was emitted byte-identical to the canonical template.

## Step 6: Generate Implementation — 2026-08-13T03:35:00.000Z

Clean — the only match was the pgrep wrapper itself. All test servers are stopped. The implementation is complete and verified.

## Summary

Generated a complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1377_ready_mix_concrete_plant_dispatch/workspace/implementation/`:

**Files created:**
- `start.sh` — executable launcher, guarded `pip install` (no-op when Flask already present), `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt`, `app.py` (entry point, error handlers, blueprint registration)
- `db.py` — in-memory store, **starts completely empty, zero seeding**
- `errors.py` — all 26 error IDs from the scaffold catalog with exact HTTP statuses
- `response.py` — envelope `{"meta": {api_request_id, api_request_timestamp}, "response_type", "data"}`; list responses add `limit/offset/total_count/has_more` into `meta`; error meta contains only request id + timestamp
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (6 roles), pagination (default 10, min 1, max 100), typed field validators
- `clock.py` — logical clock defaulting to exactly `2026-08-01T00:00:00Z`, never falls back to wall clock; `POST /v1/_clock/set_current_utc` (PlantManager only)
- `services/calc.py` — batch weights & dosing (round-per-line-then-sum, 8.34 lb/gal), actual w/c (3-decimal round-half-up, strict `>` for over-watered), escalated base / provisional / final charge (per-line round then sum, Saturday surcharge excludes wait fee, wait fee capped), credit exposure (`>=` → HOLD), order fulfillment, truck selector (last_available_at ASC, created_at ASC tie-break)
- `routes/` — catalog (plants, mix designs, price lists, cement indices, customers, clock), trucks, orders, loads (batch/depart/arrive/start-pour/complete/cancel/return/washout, water additions, batch ticket, return record, cylinder-set casting), qc (breaks with 7d/28d age gates + SoD, certify with CERTIFIED/FLAGGED + liability attribution), invoices (issue/dispute/adjust/pay)

**Key behaviors verified end-to-end against a live server:**
- Fresh boot produces default clock `2026-08-01T00:00:00.000Z` on created records (safe under per-test-server restarts)
- Provisional quote (6 yd³ × 15000 + 10% Saturday surcharge on 2026-08-15 = 99000), final charge with wait fee (45 min on site − 30 free × 150 = 2250; total 101250), invoice auto-create on DELIVERED, issue/dispute/adjust/pay cycle with exact-amount payment
- Batch ticket math pinned: cement 3384 lb, water 1523 lb, admixture doses 52.5 + 89.7 = 142.2 oz (round-per-line)
- OCC: `ERR_STALE_VERSION` (412) on price-list activate with wrong `expected_plant_version`
- Water-addition cascade: over-watered flip sets `strength_liability=PLANT` (unauthorized), cylinder sets flip to `AS_PLACED`; FLAGGED certification assigns liability per acceptance basis
- SoD: caster recording a break → `ERR_SOD_VIOLATION`; break-age gating via logical clock
- Return/washout flow with volume conservation (`ERR_VOLUME_NOT_CONSERVED`), truck status cycling AVAILABLE → ON_DELIVERY → IN_WASHOUT → AVAILABLE
- Validation errors: slump tolerance, window ordering, pour-date-past, index-month duplicate, ownership mismatch, role forbidden, unauthenticated, 404s
- Pagination meta with `has_more`/`total_count`; `created_at`-ascending sort

## Step 5: Generate Unit Tests — 2026-08-13T03:40:00.000Z

Generation complete. Summary of what was produced and the key decisions:

## Output

**`test_helpers/`** (9 modules, imports verified):
- `types.py` — 10 entity TypedDicts + 12 status enums; append-only entities (`CementPriceIndex`, `BatchTicket`, `WaterAddition`) correctly omit `updated_at`/`version`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (41 methods incl. the logical-clock endpoint)
- `api_errors.py` — all 27 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions (append-only shape enforced on tickets/water) + `assert_invoice_total_invariant` (total == sum of line items)
- `factories.py` / `constants.py` — payload factories pinning the standard catalog (M4000 mix: 564 lb/yd³, w/c 0.45/0.50, AEA 1.55 + WR 2.65; price list 15000/4.0/7500/60/250/15000/0.10)
- `test_users.py` — 6 role header sets; `make_customer_headers(customer_id)` builder for the entity-backed Customer role; named QC headers (qc-a/b/c) for SoD
- `fixtures.py` — composite chains: standard catalog → confirmed order → scheduled/batched/pouring/completed load → issued invoice → cylinder-set pipelines, all driving the logical clock explicitly

**`test_suite/`** — 8 files, **91 tests**, all collected cleanly:
- `test_01_order_intake.py`, `test_02_batch_ticket_and_water.py`, `test_03_load_pricing.py`, `test_04_dispatch_scheduling.py`, `test_05_credit_and_fulfillment_cascade.py`, `test_06_invoice_lifecycle.py`, `test_07_qc_cylinder_chain.py`, `test_08_returns_rbac_envelope.py`

## Completeness audit (automated)
- **Queue A**: all 18 difficulty instances have ≥2 tests tagged `Design: Difficulty/<rule_id>/<instance.name>`
- **Queue B**: all 52 non-stub corner instances have ≥1 test tagged `Design: Corner/<section>/<instance.name>`; all 12 `excluded_because:` stubs were verified to point at real difficulty instances and were not translated
- Every test has exactly one Design tag; every tag resolves to a real instance in the correct rule/section
- **C1 verbatim pass**: all 123 quoted PRD segments across all docstrings survive literal grep of `PRD.md` (whitespace-normalized)

## Key generation decisions
- All numeric assertions (3384/1523/142.2, 16500/145200, 17250/138000/159300, 0.487/0.500/0.502/0.561, cap 15000, short-load 69000/59250, exposure 145200/207000, version+5) were recomputed from PRD formulas with `Decimal` ROUND_HALF_UP and match the design-index literals exactly.
- Priority-pair tests (`state_beats_fiscal_on_reconfirm`, `safety_beats_temporal_on_batch`) are covered by PRD §2.8's explicit fixed-order prose, so both were generated (dual-failure + isolated-failure arms).
- No instances required skipping: every non-stub instance in both indices has verbatim PRD coverage with unique derivability; no skip/xfail markers exist anywhere.

## Step 7: Run Tests and Iterate — 2026-08-13T03:50:00.000Z

## Summary

**Result: clean 8-round parallel sweep — all 8 rounds passed 91/91.**

### Iterations run
2 (initial sweep → fix → confirming sweep).

### Tests deleted
None.

### Fixes applied to `test_suite/` / `test_helpers/`
- `/home/ubuntu/github/CodingPRD/tasks/task_1377_ready_mix_concrete_plant_dispatch/test_suite/test_08_returns_rbac_envelope.py` — `TestTerminalLockdown::test_cancel_completed_load_rejected_terminal`: corrected the pinned `final_charge_cents` assertion from `138000` to `159300`. STEP 2 test bug: the assertion mis-translated PRD §3.7. The fixture's pour date 2026-08-15 is a Saturday and the load spends 90 min on site (30 billable), so the FINAL charge is concrete 138000 + wait 7500 + Saturday surcharge 13800 = 159300 — identical to what `test_06_invoice_lifecycle.py` asserts for the same fixture. The test's primary rule (ERR_ALREADY_TERMINAL on cancelling a COMPLETED load) was unaffected.

### Fixes applied to `implementation/`
- `/home/ubuntu/github/CodingPRD/tasks/task_1377_ready_mix_concrete_plant_dispatch/workspace/implementation/routes/invoices.py` — `adjust_invoice`: dropped the mandatory `kind` (string) and `description` requirements on adjustment lines, which PRD §3.9 never states (PRD requires only "a non-empty `adjustment_lines` array" and defines the total invariant via "the sum of the adjustment amounts"; the `kind`/`description`/`amount_cents` shape is specified only for the auto-created LOAD lines at invoice birth). Validation now requires the array to be non-empty and each line to be a dict with an integer `amount_cents`; lines are appended as supplied. This fixed all 5 deterministic failures in `test_06_invoice_lifecycle.py` (`test_billing_cycles_while_delivery_stays_delivered`, `test_invoice_total_after_adjust_and_exact_payment`, `test_cycle_iterates_twice_with_running_total`, `test_order_billing_mirrors_each_cycle_iteration`, `test_invoice_total_conserved_through_adjust_chain`), each previously failing with ERR_VALIDATION on the adjust call.

## Step 8: Finalize PRD — 2026-08-13T03:56:00.000Z

Step 8 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1377_ready_mix_concrete_plant_dispatch/workspace/PRD_FINALIZED.md` written.

## Summary

**Line counts / %-delta:** PRD.md 286 lines → PRD_FINALIZED.md 286 lines (0% line delta; exactly one line revised in place, no insertions or deletions of lines).

**Changes (one bullet per change):**
- §3.9 — revise — extended the dispute-resolution sentence to pin adjustment-line shape: each `adjustment_lines` entry must be an object carrying an integer `amount_cents` (else `ERR_VALIDATION`), no other field such as `kind` or `description` is required, and lines are appended to `line_items` as supplied — `implementation/routes/invoices.py:93-107`.

**Step 7 diff item disposition:**
- `test_08_returns_rbac_envelope.py` 138000 → 159300 fix: pure test bug, **no PRD edit**. Verified 2026-08-15 is a Saturday and that PRD §3.7 (lines 172–174) already uniquely determines the FINAL charge: concrete 138000 + wait (30 billable min × 250) 7500 + Saturday surcharge (138000 × 0.10) 13800 = 159300 — matching `compute_final_charge` in `implementation/services/calc.py:104-127` and the parallel assertion in `test_06_invoice_lifecycle.py`. PRD prose kept verbatim.
- `implementation/routes/invoices.py` `adjust_invoice` fix: genuine PRD silence → the single edit above.

**Per-edit pre-edit search log (NO-NEW-MISMATCH):**

Edit 1 (§3.9 adjustment-line shape):
- (a) Subject: validation and append semantics of `adjustment_lines` on `POST /v1/invoices/{id}/adjust`.
- (b) Enumerated impl paths touching the subject:
  1. `implementation/routes/invoices.py:88-113` (`adjust_invoice`, the Step 7 site) — requires `adjustment_lines` present/non-null, a list, non-empty; each line a dict with integer `amount_cents` (bools excluded via `middleware.is_int`, `middleware.py:87-88`); appends `dict(line)` verbatim; recomputes `total_cents` as the sum of all line items; shape validation precedes terminal/state checks, consistent with PRD §2.8 ordering.
  2. `implementation/routes/loads.py:223-241` (invoice auto-creation at order DELIVERED) — birth `LOAD` lines carry `kind`/`description`/`amount_cents`; PRD line 190's description of that shape left untouched.
  3. `implementation/services/calc.py:145-166` (`recompute_credit_exposure`) — reads only invoice `total_cents`, never line shape.
  4. `implementation/routes/invoices.py:116-134` (`pay_invoice`) — reads only `total_cents`.
  5. `implementation/routes/invoices.py:21-41` (`get_invoice`/`list_invoices`) — return records verbatim, so appended lines surface as supplied; covered by the new "as supplied" wording.
  6. PRD cross-references checked: §2.8 validation ordering (line 110), §3.9 birth-line shape (line 190), endpoint table (line 252) — none contradicted.
- (c) Wording adjustment: scoped the requirement explicitly to adjustment lines ("each adjustment line … no other field, such as `kind` or `description`, is required on adjustment lines") so the birth-line shape sentence (§3.9 line 190) remains correctly described; kept the existing empty-array parenthetical verbatim; deliberately did not pin sign restrictions (implementation accepts negative amounts and PRD's "sum of the adjustment amounts" already reads signed) — left under-determined in the permissive direction.

## Step 9: Complete PRD — 2026-08-13T04:10:00.000Z

Step 9 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1377_ready_mix_concrete_plant_dispatch/workspace/PRD_COMPLETED.md` produced from `PRD_FINALIZED.md` (which existed) with a minimal inline-only patch aligned to `implementation/`.

**Stats**
- Source: `PRD_FINALIZED.md` (286 lines / 41,772 chars) → `PRD_COMPLETED.md` (286 lines / 45,779 chars); char-delta **+4,007**; 23 changed paragraphs (24 edits, two landed in the same §3.3 paragraph). No new sections, all in-paragraph inserts/revisions.
- Counts: **16 ambiguity-pins**, **8 mismatch-revisions**.

**Changes** (impl refs use files under `workspace/implementation/`):

- §2.1 — revise — ambiguity — QCTech identity bullet now pins exact SoD distinctness (break recorder ≠ caster; certifier ≠ caster and ≠ 28-day recorder; 7-day recorder may record 28-day and may certify) and fixes the §3.6→§3.8 cross-ref — routes/qc.py:45,70.
- §2.2 — insert — ambiguity — `api_request_timestamp` is wall-clock, not the logical clock — response.py:15-19.
- §2.3 — insert — ambiguity — bad limit/offset → ERR_VALIDATION; sort ties broken by `id`; `total_count` = post-filter pre-pagination count; `has_more` formula; batch-ticket/return-record reads ignore pagination and report limit 10/offset 0 — middleware.py:55-79, routes/loads.py:382,392.
- §2.4 — insert — ambiguity — `version` starts at 1; water additions carry `id`+`created_at`+`added_at` (both timestamps identical) with `updated_at`/`version` absent; unparseable `to_iso8601` → ERR_VALIDATION — middleware.py:41-46, routes/loads.py:344-351, routes/catalog.py:276-279.
- §2.5 — insert — ambiguity — plant field types: `name` string, `batch_cycle_minutes` integer, `daily_capacity_yd3` number — routes/catalog.py:32-34.
- §2.7 — revise — **mismatch** — `expected_plant_version` is required (integer) on every price-list creation, compared against the plant version only when `activate` is true — routes/catalog.py:140,152-155.
- §2.8 — revise — **mismatch** — state-check priority pinned as terminal → from-state → stale-version (was stale → from-state → terminal); observable on schedule with a terminal/invalid order plus stale version — routes/orders.py:165-170.
- §2.9 — revise — ambiguity — exposure-recompute event list now includes order confirmation and the per-completion recomputation — routes/orders.py:119-120, routes/loads.py:243-244.
- §3.1 — insert — ambiguity — `admixtures` may be omitted (defaults to `[]`); mix `code` uniqueness enforced across all statuses including RETIRED — routes/catalog.py:55-67.
- §3.2 — insert — ambiguity — any existing plant × mix may be paired on a price list (no belonging check) — routes/catalog.py:136-139.
- §3.2 — insert — ambiguity — DRAFT price lists carry `activated_at` null — routes/catalog.py:164-166.
- §3.3 — insert — ambiguity — placement performs no customer-existence check; mix design need not belong to the named plant; DELIVERED/CANCELLED pinned as terminal delivery states — routes/orders.py:24-45.
- §3.3 — revise — **mismatch** — confirmation preconditions pinned in impl order (customer existence 404 → credit hold → mix-active → price-list → pour-date), overriding §2.8's generic fiscal-last ordering — routes/orders.py:91-110.
- §3.4 — insert — ambiguity — explicit `truck_id` is not plant-checked; selector ties fall through `last_available_at` → `created_at` → `id` ascending — routes/orders.py:175-188.
- §3.5 — insert — ambiguity — interlocks (load/order state, mix, truck) are evaluated before the optional `batch_time` payload is validated; w/c ceiling uses the rounded ticket `batch_water_lb`/`cement_lb` with an unrounded comparison; `admixture_doses` entries carry `admixture_code` and `dose_oz` — routes/loads.py:57-87, services/calc.py:38-42.
- §3.6 — revise — **mismatch** — water recording against a terminal load yields ERR_ALREADY_TERMINAL (PRD said ERR_INVALID_STATE for "any other state") — routes/loads.py:337-340.
- §3.6 — revise — **mismatch** — liability is re-derived on every addition while over-watered, so a later customer-authorized addition flips `strength_liability` PLANT → CUSTOMER — routes/loads.py:356-360, services/calc.py:171-179.
- §3.8 — revise — **mismatch** — casting against WASHED_OUT/CANCELLED → ERR_ALREADY_TERMINAL; `acceptance_basis` starts AS_PLACED when the load is already over-watered at cast time — routes/loads.py:403-419.
- §3.8 — revise — **mismatch** — break-request check order pinned as state → break-age → SoD (too-early-by-caster yields ERR_BREAK_TOO_EARLY, not ERR_SOD_VIOLATION); only the caster is excluded from either break — routes/qc.py:33-46.
- §3.8 — insert — ambiguity — `num_cylinders` is integer-only with no positivity/range constraint — routes/loads.py:402.
- §3.9 — insert — ambiguity — invoice LOAD line `description` is `Load {load_id}`, lines ordered by the completed loads' `created_at` ascending — routes/loads.py:229-236.
- §3.9 — insert — ambiguity — dispute `reason` is accepted but not persisted — routes/invoices.py:72-85.

Unreachable defensive branches (e.g., 404s for missing pinned price list / batch ticket / customer at schedule/complete/water-add) were deliberately left unpinned to keep the patch minimal.

# Worklog — task_2563_assortment_planning_open_to_buy

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2563_assortment_planning_open_to_buy` and its `workspace/` subdirectory. Index 2563 was pre-assigned by the orchestrating caller; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-03T01:32:00.000Z

All three artifacts for task 2563 are complete and the scaffold linter reports a clean verdict.

Output directory: `/home/ubuntu/github/CodingPRD/tasks/task_2563_assortment_planning_open_to_buy/`

```
SCAFFOLD.yaml                     2800 lines  (145 KB)
SCAFFOLD_DIFFICULTY_DESIGN.yaml   2858 lines  (222 KB)
SCAFFOLD_CORNER_DESIGN.yaml       5384 lines  (396 KB)
                                 11042 lines total
```

Each file was built with chunked `cat >>` appends, YAML-parsed after every append, checked for duplicate mapping keys with a strict loader, and confirmed to end on a real structural boundary. Top-level keys are exactly as specified: `SCAFFOLD.yaml` has neither design key; the other two each have a single top-level key (`scaffold_difficulty_design`, `scaffold_corner_design`).

Lint verdict (verbatim):
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  §1.5 endpoints declared:    61
  §1.1 entities declared:     15
  §1.8 instances scanned:     24
  §1.9 instances scanned:     53
  Calls scanned (§1.8+§1.9):  1396

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Inventory:
- 15 entities (graph topology; `VendorAuthorization` is the many-to-many junction; `SizeCurveCell` and `ActualsPost` are immutable/versionless)
- 61 endpoints under prefix `/otb`, 5 roles (one `entity_backed:Vendor`)
- 10 state machines / 41 transitions across 9 entities (`ReceiptCommitment` carries two independent dimensions), shape `compound`
- 11 calculations (2 with dual variants), 40 validation rules, 52 error codes, 2 concurrency rules (OCC on `PlanMonth` and `CategoryPlan`)
- §1.8: 24 depth instances covering all nine Difficulty Rules with >=2 instances each
- §1.9: 74 breadth entries across all nine guide sections — 53 full instances + 21 `excluded_because:` stubs (entities 13, state_machines 15, calculations 11, validations 8, endpoints 6, errors 13, rbac 3, complexity_layers 4, consistency_model 1). Every `claim_type` is a literal row of its section's table in `references/claim-extraction-guide.md`; the errors section uses `violation_to_error` since Table 6 declares no claim types. All 52 error codes are reachable from §1.8+§1.9, and all stub `difficulty_instance` names resolve in the difficulty file.

How "harder than expert level" was honored: the expert band is 10–15 entities / 20–32 endpoints / 18–30 errors; this scaffold sits at 15 / 61 / 52 — roughly double the endpoint and error ceiling — plus a 40-rule priority ladder, all four active complexity layers, two OCC rules, and a compound state machine with genuinely parallel dimensions. Difficulty is in the arithmetic, not just the size: money is integer cents with `round_half_up` pinned at each named intermediate, and the hard cases are boundary-exact rather than illustrative — a receipt budget that flips on `sales_target_cents` 4 vs 5 (`round_half_up(0.48)=0` → `ERR_RECEIPT_BUDGET_ZERO`, `round_half_up(0.6)=1` → approval succeeds with a 1-cent budget), option slots driven to the `MIN_SLOTS_PER_TIER` floor of 2 by an unaffordable option, a one-cent OTB ceiling, ±1-unit brackets on vendor minimum and receipt over-commitment, a lead-time feasibility day boundary, and a two-basis OTB ledger whose 2,250,000-cent divergence is exactly the BOM rebuild while the `PLANNED_BASIS` read deliberately reuses the persisted markdown reserve rather than rewinding history. Precedence is pinned wherever two rules can fire on one request (frozen posture over OTB-exceeded, cluster-scope over overlay-window, priority-1 auth over 404/403/400, role-check over plan-month-state), and cascades are verified as 4–5 link chains with an all-or-nothing unwind case.

## Step 3: Copy shared files — 2026-09-03T01:33:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T01:50:00.000Z

PRD.md is complete and all three Hard Contracts pass.

Deliverable: `workspace/PRD.md` — 460 lines, built in 13 chunked `cat >>` appends (never one giant Write), each verified with `wc -l` + `tail`.

Section anchors: `3: ## 1. Introduction`, `11: ## 2. Global Specifications & System-Wide Principles`, `191: ## 3. Business Logic & Workflows`, `337: ## 4. Endpoint Definitions`, `405: ## 5. Error Code Catalogue`. Tail is complete: the file ends at a real boundary — the last row of the §5 table, `| ERR_RECEIPT_OVER_COMMITMENT | 422 Unprocessable Entity |` — with no mid-sentence truncation and no audit/contract footer leaked into the document.

Contract 1 — Field-Name Coverage: PASS. Required set rebuilt mechanically from the scaffold (105 `entities[].fields[].name` + all endpoint `input` identifiers and `{path}` params, optional `?` markers stripped) = 120 unique names. Extracted all 382 backticked tokens from PRD.md; `comm -23` diff = 0 missing. Re-run after the final edits: still 0 missing.

Contract 2 — Rule Coverage: PASS. Verified mechanically against SCAFFOLD.yaml: 52/52 error ids present; 40/40 validations present in the §2.8 numbered ladder with matching error id + HTTP status + `applies_to` scope; 10 state machines / 37 transitions all covered (three pairs — `APPROVED->CLOSED`, `CHASED->CLOSED`, `PROPOSED->APPROVED` — failed only an 80-char proximity heuristic and were confirmed by reading §3.8/§3.9); all 11 calculations rendered in prose including every dict-valued constant pair (`TRAFFIC_DRIVER` 11000 … `OCCASIONAL` 8500, tier shares 4500/3500/2000, benchmarks 6200/5500/4300) verified key-adjacent-to-value; 30 endpoints with `side_effects` have every snake_case token referenced (the only unreferenced tokens are the four internal calculation identifiers, deliberately expressed as prose); all entity-field enum members and defaults present; both OCC rules, all four dual-variant sibling pairs, and both cascades covered.

Contract 3 — §3 Path Purity: PASS. Over lines 191–336 (268 unique backtick tokens): 0 tokens starting with `/`, 0 tokens containing `/` at all, 0 bare HTTP-method tokens, 0 method+path tokens; a raw-prose grep for `/otb` and `HTTP GET|POST|…` in the same range also returns nothing.

Two repairs made this pass (both from Contract 2 findings, not truncation):
1. §2.8 item 39 now scopes `ERR_NO_FEASIBLE_RECEIPT_MONTH` explicitly to `action == CHASE`, matching the scaffold's `chase_cancel_allocation` (a `HOLD` approval legitimately yields `approved_units` 0 and must not be refused).
2. §3.8 now states outright that a successful approval advances the decision `PROPOSED -> APPROVED` on all three branches including `HOLD`.

Also added a one-sentence legend to §4 defining "Any planning role" (the four opaque roles) and "Any role" (those four plus `VendorRep`); a script then confirmed all 61 endpoint rows match the scaffold's method, path and exact role set with 0 mismatches, and §5 carries all 52 error ids.

Neither design yaml was opened, grepped or referenced, and no sibling task directory was read.

Orchestrator truncation check (per pipeline instruction): independently verified 460 lines, 61 endpoint table rows in §4, 52 `ERR_` rows in §5, and a tail ending on a complete table row. Not truncated — no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T02:35:00.000Z

Final audit complete. The suite is finished and clean.

Files produced — `test_helpers/` (Stage 1 infrastructure, 2,118 lines):

| lines | file |
|---|---|
| 416 | `types.py` |
| 274 | `api_client.py` |
| 648 | `fixtures.py` |
| 243 | `assertions.py` |
| 160 | `factories.py` |
| 148 | `constants.py` |
| 117 | `api_errors.py` |
| 72 | `test_users.py` |
| 40 | `__init__.py` (barrel re-export) |

`test_suite/` (8,837 lines incl. conftest):

| lines | file | test fns | source queue |
|---|---|---|---|
| 53 | `conftest.py` | — | session `api` fixture + 7 header fixtures |
| 1084 | `test_01_reference_data_and_entity_shapes.py` | 13 | B · entities |
| 1292 | `test_02_lifecycles_and_closure_cascades.py` | 18 | B · state_machines |
| 920 | `test_03_planning_arithmetic.py` | 20 | B · calculations |
| 1195 | `test_04_validation_ladder_and_computed_reads.py` | 12 | B · validations + endpoints |
| 1751 | `test_05_error_catalogue_and_access_control.py` | 16 (49 cases) | B · errors, rbac, complexity_layers, consistency_model |
| 207 | `test_06_open_to_buy_and_sell_through_variants.py` | 5 | A · dual_variant_calc |
| 250 | `test_07_pinned_formula_arithmetic.py` | 6 | A · combinatorial_formula |
| 493 | `test_08_governance_state_machines.py` | 8 | A · non_linear_state_machine |
| 225 | `test_09_approval_and_cancellation_cascades.py` | 4 | A · transitive_cascade |
| 268 | `test_10_validation_precedence_pairs.py` | 6 | A · priority_pair_validation_conflict |
| 328 | `test_11_boundary_precision.py` | 6 | A · boundary_precision_check |
| 272 | `test_12_cross_entity_preconditions.py` | 6 | A · cross_entity_state_dependency |
| 243 | `test_13_temporal_windows.py` | 4 | A · resource_temporal_overlap |
| 256 | `test_14_conservation_invariants.py` | 4 | A · compensating_invariant |

Tests emitted: 128 test functions, 159 collected cases after parametrization (`test_05` expands 3 functions into 13 not-found codes, 5 bad-identity header shapes, and 16 exclusive-operation role denials).

Per-queue instance coverage:
- Queue A (§1.8 difficulty): 24 / 24 non-stub instances translated, across all 9 rules, and every one carries >=2 tests (minimum 2, `otb_basis_divergence_planned_vs_projected` has 3).
- Queue B (§1.9 corner): 53 / 53 non-stub instances translated, across all 8 sections, and every one carries >=1 test (`every_entity_starts_in_its_declared_initial_state` 7, `reserve_rate_tier_boundaries_across_four_months` 5, several 2–4).
- 21 stub instances (all carrying `excluded_because:`) were verified never translated.

Audit results:
- Every one of the 128 tests has exactly one trailing `Design:` line; zero untagged, zero dual-tagged.
- Every tag resolves to a real `name:` in the corresponding yaml — set-diffed programmatically against both design indices; zero unknown tags, zero tags pointing at stubs.
- Zero `skip` / `skipif` / `xfail` / TODO / placeholder anywhere in `test_suite/` or `test_helpers/`.
- `python3 -m py_compile` clean on all 24 files; pyflakes clean on all test files (only the expected re-export barrel noise plus two harmless unused imports left in place rather than touching frozen Stage 1 helpers).

Instances SKIPPED: None. Every non-stub instance in both design indices passed the PRD-first two-condition filter and was translated; no gaps were left, and no instance was weakened to make it fit.

Notable PRD-over-recipe resolutions carried through the suite: `ActualsPost` asserted as an append-only row with only `id` + `created_at` (PRD §2.4) rather than the recipe's fuller shape; a freshly `PROPOSED` item asserted at `effective_overlay_multiplier_bps == 10000` (PRD) rather than null; `receipt_budget_cents` asserted `None` before first approval; and the overlay-temporal setup gained the canonical M1 because the recipe's plan would have failed submission's "at least one plan month and at least one option plan".

## Step 6: Generate implementation — 2026-09-03T02:35:00.000Z

The implementation is complete and verified.

Modules (`workspace/implementation/`):

| file | lines | role |
|---|---|---|
| `start.sh` | 8 | guarded `pip install` (skipped when Flask imports), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 76 | blueprint registration, global request lock, error handlers, `0.0.0.0:$PORT` (default 10000) |
| `common.py` | 356 | 52-code error catalogue + HTTP mapping, response envelope, auth, `rhu`/`trunc`/`retail_to_cost`, body validator, pagination |
| `store.py` | 209 | in-memory `Store` (15 dicts), logical clock pinned to `2026-08-01T00:00:00Z`, audit-field row helpers, lookups/navigation |
| `calc.py` | 407 | all 11 calculations (receipt budget, markdown reserve, OTB, projected basis, slot capacity, size allocation, overlays, sell-through, posture, variance, vendor capacity) |
| `svc.py` | 370 | cascades A/B, plan unwind/close, reserve events, posture/variance recompute, reforecast cycle lifecycle, chase/cancel allocation walks |
| `routes_ref.py` | 248 | departments, categories, clusters, vendors + status, authorizations, clock control |
| `routes_plan.py` | 409 | category plans (submit/approve/reject/close/summary), plan months (open-season/ledger/actuals list), option plans + size curve |
| `routes_item.py` | 225 | assortment items (adopt/activate/close), localization overlays (activate) |
| `routes_commit.py` | 282 | receipt commitments (create/commit/cancel/ship/receipts) + actuals posts |
| `routes_gov.py` | 200 | reforecasts, cycles (close), chase/cancel decisions (approve/reject) |

2791 lines total; `python3 -m py_compile` clean on every module, `__pycache__` removed.

Endpoint coverage: 61/61. Verified programmatically by diffing `app.url_map` against every `method`/`path` pair in `SCAFFOLD.yaml`: `declared: 61 registered: 61`, MISSING `[]`, EXTRA `[]`.

Smoke tests (all on a self-allocated free port, server killed by its own PID only):
- A — reference spine, plan lifecycle, OCC negatives (`ERR_STALE_PLAN_MONTH_VERSION` 412), `ERR_INVALID_PAGINATION`, `ERR_UNAUTHENTICATED`, `ERR_UNAUTHORIZED_ROLE`: ALL SMOKE CHECKS PASSED.
- B — full governance loop: cascade B (slots 6, `target_units_per_option` 15), overlay conflict/activation re-resolution, adopt, open-season, actuals -> `sales_variance_bps -8000` BREACH -> FROZEN -> auto `REFORECAST_OPEN` round 1, CHASE approval allocating 40 units, conservation identity exact, cycle close, resubmit/reapprove/close, clock advance: SMOKE B PASSED.
- C — reject/unwind (month reverts to `DRAFT` with zeroed OTB), SoD on approve, all three size-curve errors, `ERR_BELOW_VENDOR_MINIMUM`/`ERR_OTB_EXCEEDED`/`ERR_LEAD_TIME_INFEASIBLE`, withdrawal path (touches no month), commit -> ship -> over-receipt guard -> partial receipt -> cascade A cancel, slot release on item close, duplicate-code and unknown-field rejection: SMOKE C PASSED.
- D — every list endpoint (page-meta keys + `limit=0` -> 400), every detail GET, `size-curve-cells`, `otb-ledger` on both bases + invalid `basis` -> 400, `otb-summary` on all three basis modes, 404 on unknown path id, unknown filter id -> empty page: BAD=0.

One spec ambiguity, resolved deliberately: cancelling a partially received `COMMITTED` commitment is the one place two PRD passages disagree. §3.4 defines `otb_received_cents` as the sum of `received_cost_cents` over rows whose `commit_status` is `COMMITTED` or `CLOSED` and states "withdrawn and cancelled commitments contribute nothing to either", while §3.6 cascade A link 2 says open rises "by that same [released] amount". Implemented the §3.4 formula literally (a `CANCELLED` row leaves both buckets), since it is the primary ledger definition and the conservation identity is maintained by construction (`otb_open = planned - committed - received`, never clamped). Noted for test-suite reviewers if a corner test asserts the other reading.

No files were read or written under `test_suite/` or `test_helpers/`, no sibling task directory was touched, storage is in-memory only with zero seeded rows, and no broad pattern kill was ever issued — each smoke server was terminated by its own PID after confirming its `/proc/<pid>/cwd` pointed at this task's implementation directory.

## Step 7: Run tests and iterate — 2026-09-03T05:00:00.000Z

All 8 parallel rounds pass 159/159. Exit condition met.

Iterations run: 2 full 8-round parallel sweeps (`setsid nohup`, `--isolation per-test-server`). Baseline: 157/159 in all 8 rounds. Final: 159/159 in all 8 rounds, 0 failed / 0 errors / 0 skipped, ~292 s per round.

Union of failures (baseline): exactly 2 tests, each failing 8/8 (deterministic, not load-induced). Note on a false lead: `test_hold_decision_approves_zero_units_and_moves_nothing` appeared 6x as `FAILED` in `sweep.log`, but `results.*.json` showed it passing in all 8 rounds — pytest's live-progress lines from 8 concurrent rounds interleave, so the `FAILED [37%]` token belonging to the preceding test got appended after the next test's name. Diagnosing from the log rather than the JSON would have produced a phantom fix.

Tests deleted: none. No test was found to assert a scaffold-only or PRD-silent rule.

Fixes applied to `test_helpers/`: none.

Fixes applied to `test_suite/` — `test_suite/test_04_validation_ladder_and_computed_reads.py`, `test_otb_ledger_returns_either_basis_without_persisting` (STEP 2, test wrong; made strictly more PRD-faithful, no assertion weakened or removed without replacement):
- The test asserted the `PLANNED_BASIS` ledger read echoes the month's persisted reserve (`1_335_000`, derived from two posted actuals weeks) and hence `otb_planned_cents == 18_835_000`. PRD §3.4 says of the planned variant, verbatim: "The authored plan is taken at face value here and no week of actuals is read." A reserve of 1,335,000 is derived from the posted weeks, so the assertion required the planned basis to read actuals.
- Decisive corroboration: `test_06_open_to_buy_and_sell_through_variants.py::test_planned_basis_read_never_consults_actuals_and_basis_is_per_month` runs the same discriminating experiment and asserts `otb_planned_cents == 18_200_000`, i.e. the reserve re-derived on the authored month. The two tests were mutually unsatisfiable; no implementation could pass both. The `PROJECTED_BASIS` half cannot distinguish the readings (both give 1,335,000), which is why only the planned half failed.
- Rewrote the planned-half assertions to the PRD-derived values (`provisional_sell_through_bps == 6750`, `reserve_rate_bps == 350`, `markdown_reserve_cents == 700_000`, `otb_planned_cents == otb_open_cents == 18_200_000`), corrected the basis-divergence assertion `18_200_000 - 16_585_000 == 1_615_000`, added a reserve-divergence assertion (`635_000`), and replaced the docstring's misapplied §3.4 "recomputed on exactly two events" citation (that paragraph governs persisted state under writes, not a non-persisting read) with the face-value sentence. All non-persistence, projected-walk, and `weeks_posted` assertions kept intact.

Fixes applied to `implementation/` — `workspace/implementation/calc.py`, `month_buckets()`:
- Added `CANCELLED` to the `commit_status` set contributing `received_cost_cents` to `otb_received_cents`. This resolves the §3.4-vs-§3.6 conflict the implementation generator flagged, in favour of §3.6. §3.4 says cancelled rows "contribute nothing to either, because their open cost is zero and their received cost counts only units genuinely received" — a rationale that only holds when `received_units == 0`. §3.6 cascade A link 2 governs the partially-received case directly and verbatim: cancelling "drops the month's `otb_committed_cents` by the released amount and raises the month's `otb_open_cents` by that same amount", the released amount being the `open_cost_cents` link 1 zeroed. On the 7000-unit / 3000-received scenario the old reading raised open by 18,200,000 instead of the released 10,400,000, i.e. it handed back money for goods genuinely received — a direct violation of that sentence. PRD also explicitly contemplates a partially-received cancellation ("a cancellation whose `received_units` is 0" as the only case that voids the physical dimension), so this is not a silent corner. `WITHDRAWN` was deliberately left out: such rows always have `received_units == 0`, so §3.4's literal set is preserved wherever it is coherent.

No entity data is seeded in the implementation, storage remains in-memory only, and no endpoint, field, or capability was added.

Orchestrator verification (per standing check that a Step 7 agent can claim a clean sweep without leaving artifacts): independently parsed all 8 `results.{1..8}.json` — every round `passed=159 total=159 failed=0 errors=0 skipped=0`, all eight files present, non-empty, and freshly timestamped. `grep` for `pytest.mark.skip`/`xfail` across `test_suite/` and `test_helpers/` returns 0 hits.

## Step 8: Finalize PRD — 2026-09-03T05:15:00.000Z

Both edits applied to `PRD_FINALIZED.md`; §1–§5 structure intact, ends at the last row of the §5 error table (`ERR_RECEIPT_OVER_COMMITMENT | 422`).

Line counts: `PRD.md` 460 lines — `PRD_FINALIZED.md` 460 lines — 0.0% delta (both edits are inline insertions inside existing long paragraph lines; character delta ~ +1.6 KB).

Changes:
- §3.4 (month's open-to-buy, the two commitment sums) — revise — `otb_received_cents` set widened from `COMMITTED`/`CLOSED` to `COMMITTED`/`CLOSED`/`CANCELLED`; the old blanket sentence "Withdrawn and cancelled commitments contribute nothing to either…" split into (a) withdrawn rows contribute to neither, and (b) a cancelled row contributes nothing to the committed sum (open cost released to zero) but keeps its `received_cost_cents` in the received sum — `implementation/calc.py:85-102` (`month_buckets`, line 100 set membership).
- §3.7 (the two computed reads — month-level ledger) — insert — the ledger re-derives every returned figure (including `provisional_sell_through_bps`, `reserve_rate_bps`, `markdown_reserve_cents`, `otb_planned_cents`) from the evaluated basis rather than echoing the month's persisted values; a `PLANNED_BASIS` read of a projected month re-derives the reserve from authored figures and reads no actuals; §3.4's two-events rule governs persisted fields only — `implementation/routes_plan.py:282-288` + `calc.py:186-208`.
- §3.7 (the two computed reads — plan-level summary) — insert — with no `basis` the summary sums the months' persisted figures and reports the plan's persisted `open_ratio_bps`/`otb_posture`; with a `basis` it re-evaluates each month and re-derives ratio/posture from those sums by the §3.4 posture rule — `implementation/routes_plan.py:159-197` (branch at 166 vs 175), `calc.py:310-330`.

Per-edit pre-edit search log:

Edit 1 — subject: which `commit_status` values feed a month's committed/received buckets, and what a `CANCELLED` row contributes.
(b) Enumerated/read: `calc.py:85-102` `month_buckets` (the Step 7 site); `calc.py:76-82` `month_committed_receipt_cost` (reserve denominator S1 — still `COMMITTED`/`CLOSED` only, so PRD §3.4's "commitments that are `PROPOSED`, `WITHDRAWN` or `CANCELLED` are excluded entirely" was left verbatim); `svc.py:11-19` `recompute_month_buckets` (sole persister) and `svc.py:22-34` `reserve_event`; every `recompute_month_buckets` callsite — `routes_commit.py:158` (commit), `:194` (cascade A cancel), `:244` (receipt posting), `routes_gov.py:172,182` (chase / cancel decision approval); the two `CANCELLED`-producing paths `routes_commit.py:186-190` and `svc.py:343-369` `cancel_allocation` (confirmed every `CANCELLED` row ends with `open_cost_cents == 0`, and `received_cost_cents` is never zeroed on either path); withdrawal path `routes_commit.py:177-184` and ship guard `:207` (confirmed a `WITHDRAWN` row can never have `received_units > 0`); `routes_plan.py:159-197` plan summary; `calc.py:361-392` capacity sums (units, not money — untouched); §2.11 identity and §3.6 cascade A link 2 wording re-checked — received is unchanged across a partially-received cancellation, so "committed drops by the released amount and open rises by that same amount" stays exactly true.
(c) Adjustment: dropped the first draft's "link 1 of cascade A zeroes its open cost" (false for the §3.8 `CANCEL`-waterfall path, which produces `CANCELLED` without cascade A) in favour of the path-neutral "its open cost has been released to zero"; and avoided any "before the cancellation" temporal qualifier on the received cost, since `routes_commit.py:224` lets a `VendorRep` post further receipts against a row whose `fulfillment_status` is still `PARTIALLY_RECEIVED` even after `commit_status` became `CANCELLED`.

Edit 2 — subject: whether the month-level `otb-ledger` re-derives or echoes persisted month fields.
(b) Enumerated/read: `routes_plan.py:282-288` (ledger; always `evaluate_month`, `basis or month["active_basis"]`); `routes_plan.py:24-30` `_basis_param` (rejects a bad `basis` with `ERR_INVALID_REQUEST`); `calc.py:186-208` `evaluate_month` -> `projected_figures`, `markdown_reserve`, `otb_planned`, `month_buckets` (all fresh); grepped every caller of `evaluate_month` / `markdown_reserve` / `reserve_event` — the only reserve persisters remain `svc.py:131` (approval link 2, `PLANNED_BASIS`) and `routes_commit.py:275` (actuals post, `PROJECTED_BASIS`), so §3.4's "exactly two events" claim stays true and the new sentence had to be scoped to persisted fields; `routes_plan.py:159-197` (parallel endpoint that does not re-derive when `basis` is omitted).
(c) Adjustment: named "the ledger" explicitly and added "The two-events rule of §3.4 governs the month's persisted reserve fields, not this non-persisting read" so the new sentence cannot be read as a general "all computed reads re-derive" claim that the plan summary's omitted-`basis` branch would contradict.

Edit 3 — subject: the plan-level `otb-summary`'s two branches (echo vs re-evaluate).
(b) Enumerated/read: `routes_plan.py:159-197` (both branches, including `ratio = plan["open_ratio_bps"]` / `posture = plan["otb_posture"]` at 172-173 vs `calc.compute_posture(...)` at 182); `calc.py:305-330` `compute_posture` (confirmed the explicit-sums call path still applies the empty-month-set default and the unconditional `variance_status == BREACH -> FROZEN` override); `calc.py:305-307` `posture_month_set`; `routes_plan.py:200-206` `plan_basis`.
(c) Adjustment: wrote "derives … by the posture rule of §3.4" instead of spelling out a ratio formula, so the BREACH override and empty-set default are not accidentally excluded; deliberately said nothing about which `basis` string is reported when `basis` is omitted, leaving that under-determined rather than risking a claim outside the Step 7 subject.

Orchestrator verification: `PRD_FINALIZED.md` is 460 lines, retains all five `## ` section anchors, ends on the complete final §5 table row, and `cmp` confirms it is not byte-identical to `PRD.md` (the edits really landed).

## Step 9: Complete PRD — 2026-09-03T06:05:00.000Z

Orchestrator decision (recorded per the autonomy instruction): Step 9 was run as **three sequential file-partitioned passes** over `implementation/` rather than one pass, because a single subagent scanning 2791 lines of implementation against a 460-line PRD reliably degenerates into a near no-op (the known failure signature is `PRD_COMPLETED.md` coming back byte-identical to its source). Partition: pass A = `app.py`/`common.py`/`store.py`/`routes_ref.py`; pass B = `calc.py`/`svc.py`; pass C = `routes_plan.py`/`routes_item.py`/`routes_commit.py`/`routes_gov.py`. Pass A owned the `cp` from `PRD_FINALIZED.md`; B and C edited in place, and each was told the prior passes' global pins so their wording stayed consistent. Each pass also handed forward the behaviors it deliberately left out of scope, and pass C was required to resolve all five hand-off items.

### Pass A — core + reference routes (app.py, common.py, store.py, routes_ref.py)

`PRD_FINALIZED.md` 460 lines / 108,470 chars -> `PRD_COMPLETED.md` 461 lines / 111,998 chars (+1 line, +3,528 chars). Ambiguity-pins: 12. Mismatch-revisions: 2. Full §5 catalogue cross-checked programmatically against `common.py:ERROR_HTTP` — identical sets, identical statuses, zero drift.

- §2.1 — revise — ambiguity — a header holding only whitespace counts as absent for `ERR_UNAUTHENTICATED` — common.py:197-200
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars — common.py:87-88
- §2.2 — revise — ambiguity — `api_request_timestamp` is real UTC wall clock, never the logical clock — common.py:96-97,154
- §2.2 — insert — mismatch — unrouted path -> `ERR_INVALID_REQUEST` with 404 and undeclared method -> same code with 405, overriding §5's blanket 400 for those two transport cases — app.py:51-58
- §2.3 — insert — ambiguity — query params other than `limit`/`offset`/declared filters are ignored, not rejected — routes_ref.py:15-20
- §2.3 — revise — ambiguity — `created_at` ordering ties (ms resolution) break by server insertion sequence — store.py:52,63-64
- §2.4 — insert — ambiguity — `created_at`/`updated_at` stamped from the real wall clock, not the logical clock — store.py:48,58
- §2.6 — insert — ambiguity — the clock accepts any target instant including a backwards move, and every ISO-8601 input normalizes to UTC — routes_ref.py:241-248, common.py:104-119
- §2.7 — insert — ambiguity — trailing slash insignificant on every path — app.py:18
- §2.7 — revise — mismatch — list filters are not resolved: an identifier matching no row yields an empty page with `total_count` 0, not a not-found code — routes_ref.py:15-20,92-94
- §2.8 rule 3 — insert — ambiguity — JSON `null` counts as field-absent; absent/empty body reads as `{}`; non-object or unparseable body rejected here; a boolean never satisfies an integer field — common.py:233-246,252,300-306
- §3.1 — insert — ambiguity — server starts with no data at all; nothing seeded — app.py:3, store.py:1-4
- §3.1 — insert — ambiguity — the `code` uppercase test is "unchanged by uppercasing", so digits pass and any lowercase letter fails — common.py:266-267, routes_ref.py:28,62,142
- §3.2 — insert — ambiguity — `PENDING` as a target, or the vendor's own current status, is an undeclared transition -> `ERR_INVALID_STATE`; vendor version +1 per accepted transition and each flipped authorization advances its own `updated_at`/`version` — routes_ref.py:174-196
- §3.2 — insert — ambiguity — an authorization may be created against a vendor in any status and is still `ACTIVE`; the `vendor_id`/`category_id` pair is not unique-constrained — routes_ref.py:209-217

### Pass B — calculations + services (calc.py, svc.py)

461 lines / 111,998 chars -> 461 lines / 117,242 chars (all edits in-paragraph). Ambiguity-pins: 13. Mismatch-revisions: 9. Pass A's edits diffed against a pre-pass snapshot and confirmed intact.

- §2.10 — revise — mismatch — cascade A restore fires when the resulting posture is not `FROZEN`, not when it "lifts the plan out of a frozen posture" — svc.py:63-73
- §2.11 — revise — mismatch — conservation identity does not hold after a rejection unwind, which zeroes planned/open while leaving committed/received — svc.py:158-167
- §3.2 — revise — mismatch — category open-unit test excludes the candidate row itself at commit time, else its units count twice — calc.py:378-392,401
- §3.2 — insert — ambiguity — with duplicate authorizations allowed, the earliest-created `ACTIVE` one supplies the governing `max_open_units` — calc.py:407-412
- §3.3 — revise — mismatch — zero-cell rejection covers zero or negative `allocated_units`, checked across the whole set before any row is written — svc.py:94-100
- §3.4 — insert — mismatch+ambiguity — rejection unwind leaves committed/received, `option_slots_assigned` and slot-holding items untouched, and recomputes no posture or variance — svc.py:158-174
- §3.4 — insert — ambiguity — empty posture month set yields ratio 10000/`OPEN`, with the `BREACH` override still running on top — calc.py:318-330
- §3.5 — insert — ambiguity — clock-driven expiry is plan-agnostic; when several overlays expire in one reposition all expiries apply first and each affected item re-resolves exactly once — svc.py:261-280
- §3.5 — insert — ambiguity — supersession by a new reforecast round re-resolves no item, unlike expiry — svc.py:219-224
- §3.7 — insert — ambiguity — projected basis with zero weeks posted: run rate undefined, projected sales and `projected_sales_cost_cents` 0, provisional sell-through 0 — calc.py:113-121
- §3.7 — revise — mismatch+ambiguity — the ledger reports authored and projected columns under either basis, `weeks_posted` always the true count, and the basis only selects which pair feeds the reserve and `otb_planned_cents` — calc.py:186-208
- §3.8 — insert — ambiguity — chase headroom counts commitments the same walk already wrote for earlier months — svc.py:331-339
- §3.8 — insert — ambiguity — generated row's `received_units`/`cancelled_units` at 0 and costs by the §3.6 formulas; a month admitting nothing is skipped and the walk continues — svc.py:286-339
- §3.8 — insert — ambiguity — chase-generated commitments bypass the rest of the proposal stack; `weekly_unit_capacity` is the only supply-side ceiling — svc.py:308-340
- §3.8 — insert — mismatch+ambiguity — cancel walk rewrites `open_cost_cents` from remaining open units, leaves `received_cost_cents`, consults no cancel cutoff, leaves `fulfillment_status` untouched — svc.py:343-370
- §3.6 — revise — mismatch — second coupling point narrowed to a buyer-driven cancellation whose `received_units` is 0 — svc.py:360-366 vs routes_commit.py:189
- §3.6 — revise — mismatch — cascade A link 4 keyed on the posture link 3 left behind rather than on the transition out of `FROZEN` — svc.py:63-73
- §3.9 — insert — ambiguity — plan closure sweeps nothing beyond months/cells/`OPEN` cycles; no month figure or plan posture/variance recomputed — svc.py:180-200

### Pass C — route modules (routes_plan.py, routes_item.py, routes_commit.py, routes_gov.py)

461 lines / 117,242 chars -> 461 lines / 122,761 chars (+5,519 chars, +0 lines). Ambiguity-pins: 13. Mismatch-revisions: 5.

- §2.3 — insert — ambiguity — plan-month list spans every plan, so equal `month_index` ties break by insertion sequence; size-curve and actuals lists are parent-scoped and never need it — routes_plan.py:258
- §3.3 — insert — ambiguity — `fiscal_month_label`'s `YYYY-MM` test is purely syntactic; month 13 is accepted — routes_plan.py:214-215
- §3.3 — insert — ambiguity — size-curve replacement answers with the replacement set itself, `size_sort_order` ASC, no pagination fields — routes_plan.py:399
- §3.3 — insert — ambiguity — each `cells` element validated as a body object in array order under §2.8 priority 3 before `{id}` resolves; emptiness/balance/zero-cell run after — routes_plan.py:365-373
- §3.4 — revise — mismatch — `ERR_RECEIPT_BUDGET_ZERO` fires unless the budget is strictly greater than zero (sign test, not equality) — routes_plan.py:121
- §3.5 — insert — ambiguity — duplicate `sku_code` -> `ERR_INVALID_REQUEST`, tested only after both FKs resolve — routes_item.py:44-48
- §3.5 — insert — ambiguity — item proposal is unconditional on cell status and plan governance status — routes_item.py:40-57
- §3.5 — revise — mismatch — adopt gate order pinned (item `PROPOSED` -> cell `SLOTTED` -> plan `APPROVED`/`REFORECAST_OPEN` -> open slot), so plan-status outranks empty-slot; null `option_slots_open` counts as no slot — routes_item.py:84-94
- §3.5 — insert — ambiguity — overlay window-conflict test is plan-agnostic — routes_item.py:171-174
- §3.6 — insert — ambiguity — freeze-demotion sweep is bound to the commit path and the conditional restore to the buyer-cancel path; no other posture recomputation touches item status — routes_commit.py:160,196 vs routes_plan.py:278, routes_commit.py:277, routes_gov.py:173,183, svc.py:134
- §3.6 — insert — ambiguity — receipt posting does not gate on the financial dimension (a `CANCELLED` row still `PARTIALLY_RECEIVED` accepts one) — routes_commit.py:224-226
- §3.6 — insert — ambiguity — receipt posting recomputes the month only, never the plan's `open_ratio_bps`/`otb_posture`/`version` — routes_commit.py:244
- §3.6 — revise — mismatch — second coupling point voids from whichever state was held, so `SHIPPED -> VOID` as well as `AWAITING_SHIP -> VOID` — routes_commit.py:189-190
- §3.7 — insert — ambiguity — a present-but-invalid `basis` -> `ERR_INVALID_REQUEST`, decided before the path id resolves — routes_plan.py:24-30,162,285
- §3.7 — insert — ambiguity — basis reported by `plan_basis()`; `receipt_budget_cents`/`variance_status`/`sales_variance_bps` always persisted — routes_plan.py:200-205
- §3.8 — insert — ambiguity — live-cycle refusal is `ERR_INVALID_STATE`, last of four gates (status -> OCC -> round cap -> live cycle) — routes_gov.py:31-41
- §3.8 — insert — ambiguity — `HOLD`/`requested_units != 0` is a §2.8 priority-3 `ERR_INVALID_REQUEST`, before FK resolution — routes_gov.py:95-96
- §3.8 — revise — mismatch — only `CHASE`/`CANCEL` recompute months + posture; `HOLD` recomputes nothing and does not move the plan's version — routes_gov.py:160-183
- §3.9 — insert — mismatch — closing an item whose cell was unwound to `OPEN` with null `option_slots_open` drops only `option_slots_assigned` and leaves the null — routes_item.py:136-139
- §4 — revise — mismatch — option-plan list description now includes the `status` filter — routes_plan.py:350

Hand-off resolutions (pass C): (1) missing freeze-deferral / conditional-restore on the chase-cancel and actuals paths pinned with one global §3.6 statement naming all four non-sweeping posture-recomputation routes; (2) `plan_basis()` pinned as `PROJECTED_BASIS` if any contributing month's `active_basis` is projected, else `PLANNED_BASIS`, with an empty month set reporting `PLANNED_BASIS`; (3) receipt-posting month-only recomputation pinned for both the partial and complete branch; (4) `budget <= 0` reconciled — §3.4 now agrees with §2.8 rule 38's "strictly greater than zero"; (5) overlay conflict ignoring `category_plan_id` — existing §3.5 wording was already impl-consistent, so an explicit plan-agnostic clause was added rather than a revision.

### Totals and final verification

38 ambiguity-pins + 16 mismatch-revisions across the three passes. `PRD_COMPLETED.md` is 461 lines / 122,761 chars versus `PRD_FINALIZED.md` at 460 / 108,470 (+14,291 chars) — not byte-identical to its source, confirming the scan actually ran rather than no-opping. All five `## ` section anchors present, 61 endpoint rows in §4, 52 `ERR_` rows in §5, and the file ends on the complete final table row.

Orchestrator close-out: Step 9 edited only `PRD_COMPLETED.md`. Every file under `workspace/implementation/` and `test_suite/` has an mtime earlier than the `results.{1..8}.json` files (14:50), so the verified 8/8 green sweep at 159/159 corresponds exactly to the code as it now stands. Pipeline complete.

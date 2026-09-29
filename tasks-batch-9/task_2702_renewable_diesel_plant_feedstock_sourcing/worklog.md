# Worklog — task_2702_renewable_diesel_plant_feedstock_sourcing

## Step 1: Create task directory — 2026-09-04T08:47:16.179Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2702_renewable_diesel_plant_feedstock_sourcing` and its `workspace/` subdirectory. Index was pre-assigned (2702) by the invoking command; no scan of ./tasks/ was performed and no index was auto-allocated, per instruction (32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T11:15:32.961Z

Note (orchestrator): the first scaffold subagent was killed by an upstream API timeout after ~65 min with zero files written. Rather than respawning a fresh agent (which would discard its skill-reading context), it was resumed in place via SendMessage with an explicit chunked-write protocol (Write for the first chunk, `cat >> ... <<'EOF'` heredoc appends thereafter, `wc -l` after each chunk) to stay under the 64k output cap. It then completed all three files.

Subagent summary (verbatim):

All three scaffold artifacts are complete, valid YAML, and the lint is clean.

**Files** (`/home/ubuntu/github/CodingPRD/tasks/task_2702_renewable_diesel_plant_feedstock_sourcing/`)
- `SCAFFOLD.yaml` — 3184 lines, top-level keys only `scenario`, `domain_name`, `api_prefix`, `response_envelope`, `complexity_profile`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles` (no `scaffold_difficulty_design` / `scaffold_corner_design`).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2238 lines, single key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3756 lines, single key `scaffold_corner_design`.

**Summary for worklog.md**

```
task_2702_renewable_diesel_plant_feedstock_sourcing — scaffold generated (3 files, 9178 lines total)

SCAFFOLD.yaml (§1.0–§1.7): domain renewable-diesel-feedstock-sourcing, api_prefix "/",
  difficulty expert_plus, archetypes compliance_audit / ledger_reconciliation,
  entity_topology flat, state_machine_shape cyclic, role_model segregation_of_duties,
  consistency_model immediate, complexity_layers dual_variant_calculation /
  cascading_side_effects / rate_threshold_triggers / optimistic_concurrency.
  15 entities · 13 state machines (2 parallel dimensions on ProductBatch) · 2 OCC rules
  (quality-test-stale-lot, allocation-create-stale-run) · 13 calculations · 40 ordered
  validations (ERR_UNAUTHENTICATED → ERR_NOTHING_TO_REVERSE) · 68 endpoints (no PUT/PATCH/
  DELETE, no bulk) · 64 error codes · 6 roles (PlantOperator, FeedstockTrader,
  QualityAnalyst, ComplianceOfficer, IndependentVerifier, Supplier[entity_backed]).

SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8): 9 rule_ids / 22 instances —
  dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2,
  transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3,
  cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 2.

SCAFFOLD_CORNER_DESIGN.yaml (§1.9): 96 instances across all nine sections —
  entities 13, state_machines 16, calculations 18, validations 14, endpoints 5,
  errors 10, rbac 9, cross_cutting_complexity_layers 9, consistency_model 2.
  73 carry a full test_recipe; 23 are excluded_because stubs pointing at the stronger
  §1.8 instance that already covers the claim. All 64 error codes are referenced by at
  least one §1.8/§1.9 instance; instance names are unique across both design files.

Lint: python3 skills/prd-bench-scaffold-generator/scaffold_lint.py <task-dir>
  §1.5 endpoints 68 · §1.1 entities 15 · §1.8 instances 22 · §1.9 instances 73 ·
  calls scanned 1034 → VERDICT: clean lint.
```

Notes worth keeping: two spec bugs were caught and fixed while grounding the corner asserts — several new calls used `measured_rd_mass_mt` / `/securements` / `capacity_kg_per_day` instead of the declared `measured_rd_mt` / `/hydrogen-securements` / `daily_capacity_kg`, and `CreditBlock.internal_signoff_user_id` instead of `signed_off_by_user_id`. Also, §1.6's `ERR_INVALID_SUPPLIER_STATE.triggered_by` claimed suspension of a PENDING supplier fails, which contradicted §1.2 (PENDING → SUSPENDED is a declared transition); the catalog text in SCAFFOLD.yaml was corrected to "an already SUSPENDED supplier" and the corner instance rewritten to match. No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-04T11:15:50.965Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T11:34:00.000Z

Orchestrator truncation check (per the known doc-generator failure mode): `workspace/PRD.md` is 492 lines / 106179 bytes; `grep '^#'` shows all of §1–§5 present with every planned subsection (2.1–2.10, 3.1–3.9); the tail ends on a completed §5 error-catalogue row (`ERR_MATURITY_IN_PAST | 422`), i.e. a real section boundary, not mid-sentence. 64 error rows counted. NOT truncated — no regeneration needed.

Subagent summary (verbatim):

PRD generation is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2702_renewable_diesel_plant_feedstock_sourcing/workspace/PRD.md` — 492 lines, 106 KB. Ends at a completed §5 error table; no audit footer, no stray files (workspace holds only `INSTRUCTION.md` and `PRD.md`).

**Section list**
- §1. Introduction
- §2. Global Specifications & System-Wide Principles — 2.1 RBAC, 2.2 API Response Structure (byte-verbatim), 2.3 Pagination, 2.4 Resource Identity / Audit Timestamps / Logical Plant Clock, 2.5 Metrology: Precision, Rounding and Pinned Evaluation Order, 2.6 Optimistic Concurrency on Lots and Campaigns, 2.7 The Request Screening Ladder, 2.8 Interval Conventions, 2.9 Cascade Discipline and Version Propagation, 2.10 Conservation Invariants
- §3. Business Logic & Workflows — 3.1 Supplier onboarding and due diligence, 3.2 Feedstock receipt, testing and pretreatment, 3.3 Hydrotreater units, catalyst charges and turnaround planning, 3.4 Hydrogen contracts and the daily nomination book, 3.5 Campaign planning (window, allocation, hydrogen securement), 3.6 Campaign execution (start, completion, reconciliation, abort), 3.7 Product certification and distribution, 3.8 Pathway registration and the credit ledger, 3.9 Feedstock and credit price volatility
- §4. Endpoint Definitions — status-code paragraph + 68-row Method/Path/Description/Role table
- §5. Error Code Catalogue — 64-row Error ID/HTTP Status table

**Coverage notes**
- §4 table diffed 1:1 against `endpoints[]`: 68/68 method+path exact, and all 68 role lists match `roles` exactly (verified programmatically, zero mismatches). The intro's 201-creation enumeration matches the 15 endpoints whose `success_status` is 201; no scaffold endpoint uses a status other than 200/201.
- §5 table diffed against `errors[]` on the (error_id, http_status) pair: identical, 64/64.
- All 64 distinct validation `error_id`s appear in §1–§3 prose, so every screening rule has a named failure mode outside the catalogue.
- All 68 state-machine transitions are expressed: 44 with an explicit `FROM → TO` arrow, 24 in prose ("moves the lot to `TESTED`", "transitions to `QUARANTINED`", "the block lands at `ADJUSTED`", etc.), each individually confirmed by inspection. All 13 state machines' state names appear.
- Numeric-literal sweep over `calculations` (69 literals), `validations` (41) and `state_machines` (6): every content literal reconstructible. The 5 calculation literals absent as digit strings are rates deliberately written as prose percentages (freight 0.035 as the 1.035 multiplier; base margin 0.08/0.12/0.15 as 8/12/15 percent; adders 0.010/0.025/0.040 as 1.0/2.5/4.0 percent). The 8 "absent" validation literals are `priority` ordinals, which §2.7 conveys as an ordered ladder rather than numbers.
- Two small fixes applied during the audit: made `RUNNING → COMPLETED` explicit at campaign completion, and made `DRAFT → SUBMITTED` / `RETURNED_FOR_INFO → SUBMITTED` explicit at pathway submission.
- Every list endpoint's filter set is stated in §3 (13 filter sentences), including the two the scaffold flags specially: `source_lot_id` on lots and `active_catalyst_charge_id` on units.

**Contract reports**

```
Field coverage check:
- entities[].fields: 121 required, 121 present, 0 missing
- endpoints[].request_body (scaffold key: endpoints[].input): 77 required, 77 present, 0 missing
- endpoints[].query_params: 0 declared in scaffold; list filters instead carried in side_effects/entity markers — all expressed in §3
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 40 checked, 40 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint named by transition, expected_lot_version / expected_run_version, ERR_STALE_LOT_VERSION / ERR_STALE_RUN_VERSION), 0 missing
- state_machines[].transitions: 68 checked, 68 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed (pinned orders, constants, rounding, PROVISIONAL/FINAL and PROVISIONAL/VERIFIED variants), 0 missing
- validations[] conditions: 64 distinct error_ids checked, 64 matchable to prose, 0 missing
- endpoints[].side_effects / applies_to: 68 checked, 68 expressed, 0 missing
- entities[].fields[] structured content: 16 entities checked, all reconstructible (incl. TraceabilityDocument and QualityTest carrying only id + created_at), 0 missing
- sibling-branch symmetry: 6 groups checked (yield PROVISIONAL/FINAL, RIN/LCFS provisional vs verified, RENEWABLE_DIESEL/SAF, CERTIFY/REJECT, VERIFY/REJECT with derived VERIFIED/ADJUSTED, T1/T2/T3), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1123
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- (also swept: plain-text method+path outside backticks: 0; plain-text bare resource paths: 0)
Status: PASS
```

Three scaffold-internal inconsistencies were resolved in favour of the authoritative source rather than propagated: campaign yield/cost fields described as "null at creation" vs. `0.000` defaults (written as "unstamped at creation", reset to `0.000` on downgrade); the start-endpoint side effect claiming it stamps provisional yields and `feedstock_cost_usd` (followed the state machine and calculation triggers: provisional split at hydrogen securement, cost at reconciliation); and completion-time check order (followed validation priorities — window elapsed, then SAF share, then mass balance).

## Step 5: Generate unit tests — 2026-09-04T13:03:55.252Z

Orchestrator layout check: `test_helpers/` (9 modules) and `test_suite/` (19 .py files) are correctly at the task root; `find workspace -name test_helpers -o -name test_suite` → NONE, so the known "test dirs land under workspace/" drift did not occur. `__pycache__` dirs removed.

Subagent summary (verbatim):

Stage-1/Stage-2 test generation for task 2702 is complete and fully verified.

## Files written (all under the task root, nothing inside `workspace/`)

`/home/ubuntu/github/CodingPRD/tasks/task_2702_renewable_diesel_plant_feedstock_sourcing/test_helpers/` — `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

`.../test_suite/` — `conftest.py` plus 18 test modules:

| file | tests | design instances |
|---|---|---|
| test_01_yield_and_credit_variants.py | 7 | 2 |
| test_02_combinatorial_formulas.py | 6 | 3 |
| test_03_cyclic_state_machines.py | 6 | 2 |
| test_04_transitive_cascades.py | 4 | 2 |
| test_05_validation_priority.py | 4 | 2 |
| test_06_boundary_precision.py | 7 | 3 |
| test_07_cross_entity_state.py | 6 | 3 |
| test_08_temporal_overlap.py | 6 | 3 |
| test_09_compensating_invariants.py | 4 | 2 |
| test_10_entities.py | 13 | 13 |
| test_11_state_machines.py | 9 | 9 |
| test_12_calculations.py | 10 | 10 |
| test_13_validations.py | 11 | 11 |
| test_14_endpoints.py | 5 | 5 |
| test_15_errors.py | 9 | 9 |
| test_16_rbac.py | 9 | 9 |
| test_17_cross_cutting.py | 5 | 5 |
| test_18_consistency.py | 1 | 1 |

**122 tests total — 50 for queue A (§1.8) and 72 for queue B (§1.9).**

## Design-index coverage (machine-verified against both yamls)

- Queue A: 22 non-stub difficulty instances, **22/22 covered** (0 stubs in that file).
- Queue B: 73 non-stub corner instances, **72/73 covered**; 23 `excluded_because:` stubs correctly received **no** tests.
- Every `Design:` tag resolves to a real non-stub instance; zero unknown tags, zero tags pointing at stubs, exactly one tag per test docstring, ending the docstring.

## Instances skipped (gap left as a gap)

- `Corner/errors/daily_feed_above_nameplate_returns_unit_capacity_exceeded` — the instance asserts that a 500.000 MT allocation on a 1-day campaign returns 409 `ERR_UNIT_CAPACITY_EXCEEDED`. PRD §3.5 places the nameplate check only inside the hydrogen-securement check list, while the allocation domain rules are an explicitly closed five-item sequence ("the domain conditions are evaluated in exactly this sequence"). The PRD contradicts rather than uniquely derives the asserted outcome, so no test was emitted, weakened or xfailed.

## Two design-yaml errors corrected against the PRD (claims preserved)

- `dd_expires_at` for `valid_months: 12` from 2026-08-01 is **2027-07-27** (the PRD's 30-day months), not 2027-08-01.
- `astm_annex: "A2"` is not a declared enum member; the only members are `A2_HEFA` / `A5_HC_HEFA`.

## Final verification

`python3 /tmp/check_tests.py test_suite/*.py` → **ALL CLEAN** (every PRD citation is a >=8-word verbatim substring occurring exactly once in `workspace/PRD.md`; no unused imports; exactly one trailing `Design:` line per test). `python3 -m py_compile` on all 9 helper modules and all 19 suite files → **ALL_COMPILED**. No `skip`/`xfail`/placeholder markers, no mention of the scaffold in any generated file, and no `test_helpers/` or `test_suite/` strays under `workspace/` (which still contains only `INSTRUCTION.md`, `PRD.md` and the concurrently generated `implementation/`, which I never read or wrote).

## Step 6: Generate implementation — 2026-09-04T13:03:55.252Z

Launched concurrently with Step 5 in a single assistant message, so the impl generator was physically unable to read `test_suite/` (it did not yet exist at spawn time).

Subagent summary (verbatim):

Implementation complete for task 2702.

## Modules written (`workspace/implementation/`, 3,365 lines total)

Core (7 modules, 1,332 lines):
- `errors.py` (158) — `ApiError` + all 66 error-ID constants with their pinned HTTP statuses
- `constants.py` (101) — every enum and every normative constant (fee tiers, CI adders, H2 intensities, yield table, RIN/LCFS factors, margin rates, tolerances)
- `store.py` (155) — 15 in-memory dict tables, the logical clock (defaults `2026-08-01T00:00:00.000Z`), UUID/`_seq` row minting, once-per-request `bump()`, ROUND_HALF_UP `q()` / truncating `trunc()`
- `response.py` (82) — `meta`/`response_type`/`data` envelope, `req_`+20-char request ids, Decimal->float and datetime->ISO(3dp) serialization, pagination meta, error envelope
- `validate.py` (206) — ladder rungs 1-2 plus strict typed getters (rejects numeric strings/bools, checks decimal places via the Decimal exponent), pagination validation
- `calc.py` (248) — all 13 declared calculations with their pinned rounding orders (H2 rounds daily feed first, settlement rounds per line, blend CI rounds once)
- `domain.py` (382) — selectors, governing-test application, mass/blend recomputation, H2 coverage, run downgrade, dominant feedstock, contract peak, catalyst decay, credit conservation, the 5-level supplier-suspension cascade and the 4-level ADJUSTED cascade

Routes (11 modules, 1,822 lines): `helpers.py` (rungs 3/4 + filtered listing), `suppliers.py`, `lots.py`, `units.py`, `hydrogen.py`, `runs.py` (464), `batches.py`, `pathways.py`, `credits.py` (261), `hedges.py`, `clock.py`; plus `app.py` (71) wiring blueprints, `ApiError`/400/404/405/500 handlers and the `before_request` touched-row reset.

## Endpoint coverage
Programmatic diff of the Flask url_map against SCAFFOLD.yaml: **68/68 declared endpoints implemented, 0 missing** (only Flask's built-in `/static/<path>` is extra).

## Smoke test (PORT=18702)
Booted clean via `start.sh`; a 40-call end-to-end script ran the full happy path (supplier -> 2 docs -> DD verification -> lot -> quality test -> acceptance -> unit -> turnaround window -> approval -> catalyst charge -> campaign -> allocation -> H2 contract + nomination -> securement -> clock advance -> start -> completion -> batch -> reconciliation -> reservation -> shipment -> pathway register cycle -> credit block -> SoD-blocked sign-off -> sign-off by a second officer -> verification submit -> VERIFY -> hedge open/unwind) plus 4 negative probes. **0 failures.**

Spot-checked arithmetic all matched the PRD: `required_h2 = 6400.0` (200.000 MT/d x 32), `provisional_yield = 82.000` / `planned_total = 820.000`, `final_yield = 80.000` with `variance = -2.000` and `flag = false` (exactly at the 2.000 tolerance), `feedstock_cost = 931500.00` (1.035 freight), `volume_gal = 246400.0`, `provisional_ci = 29.25` (20.50 + 8.75), `provisional_rin = 418880` (truncated), hedge `base 150000.00 -> T2 -> total 153750.00` (tier from base, not total). SoD returned `ERR_SEGREGATION_OF_DUTIES` 403; `limit=0` returned `ERR_INVALID_REQUEST` 422.

Server was stopped by captured PID only (`kill $PID`, plus a `-P $PID`-scoped child kill); port 18702 confirmed clear. No pattern kill was used. Storage is in-memory only, nothing is seeded at startup, and `__pycache__` was removed after `py_compile` verified all 20 modules.

## Step 7: Run tests and iterate — 2026-09-04T13:20:30.000Z

Orchestrator verification of the sweep artifacts (per the known "clean sweep with no artifacts" failure mode): all 8 `workspace/implementation/results.$i.json` exist, are fresh (mtime 13:14:48, same sweep), each carries 122 real per-test records with non-trivial durations (round duration ~215 s, per-test ~1.7 s), and each reports `passed=122 total=122 failed=0 errors=0 skipped=0`. No `Terminated` reaping pattern.

Step 8 skip condition does NOT apply: Step 7 ran 2 iterations with 2 `test_suite/` fixes, so Step 8 runs.

Subagent summary (verbatim):

Clean sweep — all 8 rounds 122/122.

## Summary

**Iterations run:** 2

**Tests deleted:** none. Both failures traced to PRD-covered rules with faithful intent; the defects were in the test artifact's expression of them, so both were repaired to be *more* faithful to PRD rather than removed.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_13_validations.py` — `test_measured_product_above_the_consumed_feed_breaks_the_mass_balance` asserted `assert_fields_null(run, "final_yield_pct", "measured_rd_mt", "measured_saf_mt")`. PRD §3.5 states verbatim: "`yield_variance_flag` is `false`, `measured_rd_mt` and `measured_saf_mt` are 0.000 until the operator reports them." The implementation correctly returned `0.0`; the assertion contradicted PRD. Split per STEP 1c: `final_yield_pct` (PRD: "unstamped at creation") stays a null assertion; the two measured masses now assert `0.000` via `assert_mass`.

2. `test_suite/test_17_cross_cutting.py` — `test_a_second_allocation_quoting_the_stale_campaign_version_moves_no_blend` built its supplier with `fx.make_supplier`, which per `test_helpers/fixtures.py` yields a `PENDING` (`dd_status`) supplier. PRD §3.5 allocation check 1 requires "The supplier behind the cited lot must have `dd_status` of `VERIFIED` ... `ERR_SUPPLIER_DUE_DILIGENCE_INCOMPLETE`", so the PRD-faithful implementation correctly rejected the setup's first allocation with 409 before the test's stale-version scenario could be reached. Switched to `fx.verified_supplier` (same `**overrides` signature, so `feedstock_types=[UCO, TALLOW]` carries through). This is a STEP 2 fixture-selection bug, not an implementation defect.

**Fixes applied to `test_helpers/`:** none needed — `verified_supplier` already existed and was correct; only the test's choice of fixture was wrong.

**Fixes applied to `implementation/`:** none. Both failures were test-side; no PRD-required check was weakened or removed, and no endpoint, field, or seeded data was added.

**Final sweep evidence** (iteration 2, all 8 rounds launched concurrently under `setsid nohup`, no early exit):

| round | passed/total |
| --- | --- |
| results.1.json | 122/122 |
| results.2.json | 122/122 |
| results.3.json | 122/122 |
| results.4.json | 122/122 |
| results.5.json | 122/122 |
| results.6.json | 122/122 |
| results.7.json | 122/122 |
| results.8.json | 122/122 |

0 failed, 0 errors, 0 skipped in every round. Iteration 1 was itself fully deterministic (120/122 in all 8 rounds, identical two failures), so no flakiness was present in either the implementation or the suite — the 8-round sweep confirmed the two defects were real rather than load-induced, and confirmed the repaired suite is stable.

## Step 8: Finalize PRD — 2026-09-04T13:23:40.000Z

Orchestrator check: `PRD_FINALIZED.md` differs from `PRD.md` (106225 vs 106179 bytes, 1 line changed), so the copy-only failure mode did not occur.

Subagent summary (verbatim):

`PRD_FINALIZED.md` produced at `workspace/PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 492 lines — `PRD_FINALIZED.md`: 492 lines — 0% line delta; 1 sentence revised inside line 252.

## Changes
- **§3.5 (campaign creation defaults)** — *revise* — `provisional_yield_pct`, `planned_total_product_mt`, `planned_rd_mt`, `planned_saf_mt`, `final_yield_pct`, `yield_variance_pct` and `feedstock_cost_usd` were described as "unstamped at creation"; now stated as "all present but null at creation — unstamped rather than zero" — `implementation/routes/runs.py:101-110`.

## Per-item Step 7 analysis

**Item 1 — `test_13_validations.py`, measured masses asserted null.** PRD §3.5 already says verbatim "`yield_variance_flag` is `false`, `measured_rd_mt` and `measured_saf_mt` are 0.000 until the operator reports them", and `routes/runs.py:105-109` sets exactly `q(ZERO,3)/q(ZERO,3)/False`. That half needed no patch — the test was wrong, PRD was right. The residual PRD-silence the item exposed is the *other* half of the same sentence: the word "unstamped", which is used nowhere else in the PRD and does not uniquely determine null vs. absent-key vs. 0.000. Impl chooses present-key-null (and `response.public` serializes `None` as a present JSON `null`, never dropping the key). That is the one edit made.

**Item 2 — `test_17_cross_cutting.py`, `make_supplier` -> `verified_supplier`.** Pure fixture-selection bug; **no PRD edit**. PRD §3.5 allocation check 1 already pins "The supplier behind the cited lot must have `dd_status` of `VERIFIED` ... `ERR_SUPPLIER_DUE_DILIGENCE_INCOMPLETE`", matched exactly by `routes/runs.py:151-154`; check 2 (`dd_expires_at` strictly after the clock -> `ERR_SUPPLIER_DUE_DILIGENCE_EXPIRED`) matches `runs.py:155-157`; and the stale-version rung ordering (rung 7 before rung 8) matches `runs.py:143` preceding `runs.py:147`. The 412 leaves no state moved because `fail()` raises before any mutation, which §2.7's "the first failing check decides the response" already covers.

## Pre-edit search log (the single edit)
- **(a) Subject:** creation-time values of the seven non-zero-initialised campaign figure fields, and what "unstamped" means on the wire.
- **(b) Impl paths enumerated (grepped/read):** `routes/runs.py:88-114` (`create_run` — all seven `None`); `calc.py:142-157` `provisional_split` (stamps the four planned figures at securement); `domain.py:204-208` `reset_planned_figures` + `domain.py:211+` `downgrade_run` (resets the four planned figures to **0.000**, not null, on all three downgrade paths); `routes/runs.py:346-384` `complete_run` (stamps `final_yield_pct`/`yield_variance_pct`, plus the defensive `provisional_yield_pct or q(ZERO,3)` read at :377); `routes/runs.py:432` `reconcile` (stamps `feedstock_cost_usd`); `calc.py:160-163` `final_yield`; `response.py:37-47` `public()` (confirms `None` is emitted as a present `null` key, and that no null-stripping happens on any read/list path).
- **(c) Wording adjustment:** the phrase was explicitly scoped with "at creation" and the original "unstamped" retained as an apposition, so it cannot be read as a universal claim that these fields are null whenever unpopulated. Without that scoping, the sentence would have contradicted `domain.py:205-208`, where a downgraded campaign's four planned figures return to `0.000` rather than null — a path Step 7 never exercised.

## Step 9: Complete PRD — 2026-09-04T14:06:42.464Z

Orchestrator design decision (recorded per the AUTONOMY instruction, no user available to consult): Step 9 was run as THREE SEQUENTIAL module-partitioned passes over ONE shared `workspace/PRD_COMPLETED.md`, rather than as a single agent. Reason: 3365 lines of `implementation/` plus a 106 KB PRD does not fit one agent's working context, and the known failure mode of a single-agent Step 9 is that the scan never really happens and `PRD_COMPLETED.md` comes out byte-identical to its source. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying (a re-`cp` would destroy the prior passes' edits) and were restricted to surgical Edit-tool changes.

Partition:
- Pass 1 — global / cross-cutting layer: `app.py`, `response.py`, `store.py`, `constants.py`, `errors.py`, `validate.py`, `routes/helpers.py`, `routes/clock.py`.
- Pass 2 — calculation / cascade / campaign core: `calc.py`, `domain.py`, `routes/runs.py`.
- Pass 3 — remaining endpoint modules: `routes/suppliers.py`, `lots.py`, `units.py`, `hydrogen.py`, `batches.py`, `pathways.py`, `credits.py`, `hedges.py`.

Aggregate: 55 edits — 45 ambiguity-pins, 10 mismatch-revisions. Final orchestrator verification: `PRD_COMPLETED.md` is 497 lines / 121628 bytes vs `PRD_FINALIZED.md` 492 lines / 106225 bytes; `cmp` confirms they are NOT identical (53 changed paragraph lines); all 5 top-level sections and all 26 subsections present; tail ends on the completed §5 error-table row `ERR_MATURITY_IN_PAST | 422`. `__pycache__` cleaned; no `.bak`/`.orig`/`.pytest_cache` strays. All 8 `results.$i.json` from the final green sweep retained.

### Pass 1 summary (verbatim)

Pass 1 complete. All edits are confined to §2.1–§2.9; §3, §4 and §5 are untouched and available to passes 2 and 3.

**cp confirmed** — `workspace/PRD_COMPLETED.md` was created from `PRD_FINALIZED.md` (492 lines) and now stands at **497 lines** (13 lines revised, 5 net new lines; no section added, no wholesale rewrite).

**Counts:** 10 ambiguity-pins, 3 mismatch-revisions.

**Changes**
- §2.1 — revise — ambiguity — an identity header that is present but empty/whitespace-only counts as absent (401), and role matching is exact and case-sensitive — `validate.py:24-27`
- §2.2 success envelope — revise — ambiguity — `api_request_id` is `req_` plus exactly 20 chars from `A-Z0-9` (24 total) — `response.py:14-15`
- §2.2 success envelope — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time, and equals the `created_at` of rows the request creates — `response.py:21`
- §2.2 success envelope — revise — ambiguity — serialization of `data`: numerics are JSON numbers, never strings, with no trailing-zero padding (`250.00` -> `250.0`); instants are ISO-8601 millisecond strings; null-valued fields are emitted as `null` rather than omitted — `response.py:25-47`
- §2.2 error envelope — insert — mismatch — unrouted paths return `ERR_INVALID_REQUEST` at **404** and unsupported methods at **405**, decided by the router before the §2.1 identity check; these are the only non-422 uses of that code, which §5 otherwise maps to 422 alone. Trailing slashes are tolerated — `app.py:28,47-54`
- §2.2 error envelope — revise — ambiguity — `message` wording is non-contractual; only `error_id` and status are — `errors.py:157-158`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` and negative `offset` are also 422; an `offset` past the end is an empty page with the true `total_count` — `validate.py:167-187`
- §2.3 — insert — ambiguity — the entire generic filter layer, which the PRD never mentioned: the per-endpoint filter sets (enumerated, rather than forward-referencing §3 which later passes may not fill), text-equality comparison, AND-combination, out-of-enum values matching nothing rather than erroring, null fields never matching, boolean fields accepting `true/1/false/0`, and unknown query parameters being ignored — `routes/helpers.py:61-83`
- §2.3 — revise — ambiguity — `created_at` ties (routine, since the clock only moves when driven) are broken by creation sequence, making the order total and stable — `store.py:136-137`
- §2.4 — revise — mismatch — `version` counts *requests* that changed a row, not individual writes: a row touched twice in one request (direct write plus cascade) advances by exactly one — `store.py:121-133`, `app.py:35-37`
- §2.4 — revise/insert — ambiguity — clock endpoint returns `current_utc` as the single property of an object-shaped `data` with `to_iso8601` required; plus instant parsing rules (`Z` and numeric offsets normalized to UTC, zoneless read as UTC) and sub-millisecond precision retained internally but rendered **truncated**, not rounded — `routes/clock.py:11-18`, `store.py:57-80`, `validate.py:140-150`
- §2.7 rung 4 — revise — mismatch — a screened body identifier that is absent, `null`, blank or non-string yields that reference's 404 not-found error, not a 422 missing-field error (a consequence of rung 4 sitting above rung 6) — `routes/helpers.py:49-58`, confirmed live: omitted `supplier_id` -> `ERR_SUPPLIER_NOT_FOUND` 404
- §2.7 rung 6 — revise — ambiguity — `null` is treated as absent; an absent/empty/unparseable body is an empty object (fails on first required field, not a parse error); a non-object JSON body is refused; booleans never accepted as numbers; integral floats accepted for counts; fields screened in declaration order — `validate.py:33-47`, `33-39`
- §2.9 — revise x2 — ambiguity — cascade version bumps are subject to the per-request counting rule, and cascade sibling ordering uses the same creation-sequence tie-break as §2.3 — `store.py:121-137`

**Fully pinned already (no edits):** `constants.py` — every constant, threshold and enum set (fee tables, CI adders, H2 intensities, decay/floor, yield table, freight, margin/tier rates and floors, gal-per-MT, RIN equivalence, benchmarks, energy densities, process adder, verification discount/tolerance, strikes, revision cap, freeze point, buffer hours, DD days, and all ten enumerations) is stated verbatim in PRD prose; `errors.py` — the 64-entry error-id->HTTP map matches §5 exactly, both directions, with no status divergence.

Two things later passes may want to know: the `ERR_INTERNAL`/500 catch-all handler (`app.py:56-60`) is deliberately left undocumented as a bug-safety net; and `validate.arg_bool` is dead code. Verification was done against a live server on port 8477, which I stopped by pid.

### Pass 2 summary (verbatim)

Pass 2 complete.

## PRD_COMPLETED.md line count
**497 before → 497 after.** Every edit was an in-paragraph insert or in-sentence revision; no new lines, no new sections, no `Write`. Pass 1's 12 hunks in §2.1–§2.9 are all still intact (verified by diff against PRD_FINALIZED.md).

## Counts
- **ambiguity-pins: 10**
- **mismatch-revisions: 2**

## Changes
- **§2.9** — insert — mismatch — §2.9's absolute "a row advances by one for the whole request" contradicted impl: the `ADJUSTED` cascade bumps the pathway once via `bump()` and then a second time by hand-incrementing `version`. Carved out the single exception — `domain.py:311-319` (with call site `routes/credits.py:199-203`)
- **§3.2 (governing test)** — insert — ambiguity — PRD stopped at "greatest `created_at` wins"; pinned the `created_at`-tie tie-break to creation sequence (later append governs), which is the normal case since the clock rarely moves between appends — `domain.py:112-126`
- **§3.5 (campaign creation)** — insert — ambiguity — PRD silent on whether `catalyst_charge_id` must belong to the named `unit_id`; pinned that `ACTIVE` is the only condition and a charge on another unit is accepted — `routes/runs.py:54-61`
- **§3.5 (allocation effects)** — insert — ambiguity — pinned that allocating onto an already-`HYDROGEN_SECURED` campaign leaves the status and the stamped plan alone and does not re-test coverage against the raised `required_h2_kg_per_day` — `routes/runs.py:181-186`
- **§3.5 (allocation check ladder)** — insert — ambiguity — "then the campaign's own state" never said which states pass; pinned `PLANNED` or `HYDROGEN_SECURED`, else `ERR_INVALID_RUN_STATE` — `routes/runs.py:147-149`
- **§3.5 (allocation release)** — insert — ambiguity — named the campaign-state refusal (`ERR_INVALID_RUN_STATE`), pinned that the allocation's own status is checked first (so a `CONSUMED` allocation on a `RUNNING` campaign reports `ERR_INVALID_ALLOCATION_STATE`), and pinned the response body as the allocation — `routes/runs.py:201-207,219`
- **§3.5 (three downgrade paths)** — revise — mismatch — PRD claimed all three paths test *both* the minimum charge *and* hydrogen coverage. Impl: suspension level 4 and manual release test mass only; nomination cancellation tests coverage only. Rewrote to split them — `domain.py:373-382`, `routes/runs.py:215-218`, `routes/hydrogen.py:138-140`
- **§3.6 (start)** — insert — ambiguity — pinned that the five conditions are evaluated in the listed order and that the "clock has not reached `window_start`" refusal is `ERR_INVALID_RUN_STATE`, not `ERR_RUN_WINDOW_NOT_ELAPSED` — `routes/runs.py:276-297`
- **§3.6 (completion inputs)** — insert — ambiguity — PRD gave no bounds/precision for `measured_rd_mt` / `measured_saf_mt`; pinned required, 0...1000000, <=3 dp, and that 0/0 is legal and emits no batch — `routes/runs.py:347-348,402-405`
- **§3.6 (catalyst effect)** — insert — ambiguity — pinned that the throughput/activity recompute bumps the charge's `version` unconditionally, not only on `SPENT`/`DERATED` — `routes/runs.py:386-400`
- **§3.6 (abort reason)** — insert — ambiguity — pinned `reason` as a non-blank 1–500 character string — `routes/runs.py:443`
- **§3.6 (abort effects)** — insert — ambiguity — pinned that abort recomputes the campaign's mass figures (`reserved_mass_mt` -> 0.000, `consumed_mass_mt` untouched) but, unlike a manual release, does **not** recompute `blend_ci_gco2e_per_mj` or `required_h2_kg_per_day` — `routes/runs.py:460`

## Found already fully pinned
- **All 13 `calc.py` calculations**, including every rounding place and every rounding *order*: the pretreatment five-step assessment with strict reject thresholds and floor-before-cap on the unrounded linear term; blend CI accumulated unrounded and rounded once; the hydrogen requirement's daily-feed-rounded-to-3-before-multiply; catalyst decay floor-then-round-to-4; the provisional split (blend yield unrounded -> `provisional_yield_pct` -> `planned_total` -> `planned_saf` -> `planned_rd` from the *rounded* SAF figure); final yield; per-line settlement rounding then re-rounded sum; the pinned five-step hedge margin with tier from `base_margin_usd` and the `volatility_tier` override; product volume; provisional/verified RIN with drift rounded to 4 then floored at 0.0000 and capped at 0.1000 then truncated; provisional/verified LCFS with discount-before-round and floor-after-round.
- **`domain.py`**: selectors' `(created_at, seq)` ordering; `counted_lines` = `RESERVED`|`CONSUMED`; lot mass recomputation and the `REJECTED` zeroing; `apply_governing_test`'s three dispositions; half-open `run_window_dates`; closed-interval `nomination_covers`; `hydrogen_coverage_ok`'s per-day >= comparison; `reset_planned_figures`; `cancel_run_nominations` and contract peak recomputation; `dominant_feedstock`'s earliest-`created_at` tie-break; `recompute_charge`'s `COMPLETED`|`RECONCILED` filter; `recompute_pathway_credits`; the five levels of the supplier-suspension cascade (quarantinable set, `SUPPLIER_SUSPENDED` reason, level-4 ordering, level-5 nomination cancellation); the `ADJUSTED` cascade's strike count, `REGISTERED -> SUSPENDED` and sibling `BLOCKED` sweep.
- **`routes/runs.py`**: the creation ladder's `ERR_CATALYST_NOT_ACTIVE` -> `ERR_UNIT_WINDOW_CONFLICT` -> `ERR_INVALID_RUN_WINDOW` -> `ERR_SAF_SHARE_EXCEEDED` order (matches §2.7 exactly, including window shape sitting *below* rung 8 despite being a 422); the full five-rung allocation domain sequence; the seven-step securement ladder; the four visible effects of start including `ACCEPTED -> CHARGED`; the three-condition completion order; the `SPENT`-beats-`DERATED` one-way interaction; batch emission and field defaults; reconciliation's per-line-then-sum settlement.

Two defensive branches in `calc.py` are unreachable and were left unpinned deliberately (`provisional_ci` treating a null blend as 0, and `verified_rin` guarding a zero `provisional_ci`): the process adder of 8.75 makes `provisional_ci >= 8.75`, and a completed campaign always has >=100 mt of `CONSUMED` mass, so neither guard can fire.

### Pass 3 summary (verbatim)

Pass 3 complete. All checks pass.

## Deliverable state

`workspace/PRD_COMPLETED.md`: **497 lines / 116,202 bytes before → 497 lines / 121,628 bytes after**. Line count is unchanged by design — every edit was an in-paragraph insert or revision on an existing paragraph line (the PRD is one long line per paragraph); no sections or paragraphs added.

Pass 1 and pass 2 edits confirmed intact: spot-checked pass-1 markers in §2.1–§2.9 (`twenty-four characters long`, the router 404/405 paragraph, the §2.3 filter inventory, the rung-4 "omitted `supplier_id`" sentence, the §2.9 pathway double-bump exception) and pass-2 markers in §3.5/§3.6 (`Three conditions gate creation`, `Allocation carries the densest stack of checks`, `Completion is where the plan meets the meter`, `abort_reason` 1-to-500). The full diff against PRD_FINALIZED.md now shows ~55 changed paragraph lines = pass 1 + pass 2 + my 28 distinct lines.

## Counts
- **25 ambiguity-pins**
- **5 mismatch-revisions**

## Changes

**Mismatches**
- §2.10 — revise — mismatch — pretreatment mass invariant attributed `pretreatment_loss_mt` to the child lot; the loss and the consumption are both booked on the source, child carries 0.000 in both — `routes/lots.py:159,177`
- §3.2 — revise — mismatch — same invariant sentence at the end of the pretreatment paragraph corrected to the source lot's `pretreatment_loss_mt` — `routes/lots.py:159,177`
- §3.2 — revise — mismatch — PRD introduced `expected_lot_version` before the five measurement fields, implying it screens first; impl screens it **last**, so a measurement failure (rung 6) beats a stale version (rung 7) — `routes/lots.py:86-96`
- §3.3 — revise — mismatch — dangling cross-reference "campaign completes, as described in §3.7" -> §3.6 (§3.7 is product batches) — `routes/runs.py` completion
- §3.4 — revise — mismatch — dangling cross-reference "aborting a campaign as described in §3.7" -> §3.6 — `routes/runs.py` abort

**Ambiguity pins**
- §3.1 — insert — `valid_until <= issued_at` is a rung-6 `ERR_INVALID_REQUEST` decided ahead of both uniqueness tests; neither instant is compared to the clock, so an already-expired document may be uploaded — `routes/suppliers.py:79`
- §3.1 — insert — reading a supplier recomputes and re-stores `dd_document_type_count` at read-time clock without bumping `version` — `routes/suppliers.py:65`
- §3.1 — insert — `valid_months` is a whole number >= 1 with no upper bound — `routes/suppliers.py:120`
- §3.1 — insert — suspension `reason` required non-blank 1–500, screened before the supplier state check — `routes/suppliers.py:151`
- §3.2 — insert — `received_at` is never compared against the current clock — `routes/lots.py:36`
- §3.2 — insert — `sampled_at` likewise unconstrained against the clock — `routes/lots.py:90`
- §3.2 — insert — the quoted fee is not a property of the test resource; it surfaces only via the lot's `pretreatment_fee_usd` — `routes/lots.py:119`
- §3.2 — insert — `output_mass_mt` carries only a 3-decimal-place bound at rung 6 (no magnitude limit there); zero/negative/over-large all fall to `ERR_PRETREATMENT_MASS_EXCEEDED` — `routes/lots.py:142,148`
- §3.3 — insert — duplicate unit `name` is a rung-6 `ERR_INVALID_REQUEST`, tested only after all three fields pass — `routes/units.py:45`
- §3.3 — insert — window `end_at <= start_at` is a rung-6 `ERR_INVALID_REQUEST`, ahead of the 72-hour adjacency test — `routes/units.py:145`
- §3.3 — insert — a logical clock outside the window's half-open interval on start yields `ERR_INVALID_WINDOW_STATE`, tested before the unit's `IDLE` check — `routes/units.py:206-212`
- §3.3 — insert — window cancellation `reason` required non-blank 1–500, screened before the window state check — `routes/units.py:244`
- §3.4 — insert — contract `window_end` must be at or after `window_start` (equal is legal, one calendar day); earlier is a rung-6 `ERR_INVALID_REQUEST` — `routes/hydrogen.py:36`
- §3.4 — insert — the cited campaign's status is not consulted when filing a nomination; any state including `RUNNING`/`COMPLETED`/`ABORTED` is accepted — `routes/hydrogen.py:64-99`
- §3.4 — insert — cancellation screens the nomination's own status before the campaign's, and the campaign failure is `ERR_INVALID_RUN_STATE` — `routes/hydrogen.py:123,128`
- §3.7 — insert — certification request screens `cert_status` first; a campaign short of `COMPLETED` is then `ERR_INVALID_RUN_STATE` — `routes/batches.py:48-56`
- §3.7 — insert — `note` is 1–500, read on both branches but stored only on rejection — `routes/batches.py:71`
- §3.7 — insert — `cert_reject_reason` is null when `note` was omitted — `routes/batches.py:91`
- §3.7 — insert — `offtaker_name` required non-blank 1–120 — `routes/batches.py:101`
- §3.8 — insert — the unit/program/feedstock trio is not a uniqueness key; duplicate registrations are allowed — `routes/pathways.py:24-47`
- §3.8 — insert — `certified_ci` has no upper bound and no decimal-place limit at rung 6; it is stored rounded half up to 2 dp — `routes/pathways.py:129,139`
- §3.8 — insert — `info_request` at most 500 characters — `routes/pathways.py:131`
- §3.8 — insert — the pathway-`REGISTERED` test on mint runs *after* both referential conditions, so scope mismatch wins over `ERR_INVALID_PATHWAY_STATE` — `routes/credits.py:41-52`
- §3.8 — insert — a second block against the same batch, or the same batch/pathway pair, is not prevented — `routes/credits.py:78`
- §3.8 — insert — segregation-of-duties is compared *before* the pathway's status, so the registering officer sees `ERR_SEGREGATION_OF_DUTIES` even on a suspended pathway — `routes/credits.py:110,113`
- §3.8 — insert — `findings` at most 500 characters — `routes/credits.py:161`
- §3.8 — insert — `verified_ci` unbounded above with no dp limit, stored rounded half up to 2 dp, and the *rounded* value drives the verified quantities — `routes/credits.py:159,167`
- §3.8 — insert — divergence when the provisional quantity is zero: no division; `ADJUSTED` iff the verified quantity is non-zero, else `VERIFIED` — `routes/credits.py:144-145`
- §3.8 — insert — retirement `credits` carries only a 3-decimal-place bound at rung 6 — `routes/credits.py:212`
- §3.8 — insert — reversal `reason` required non-blank 1–500 and overwrites whatever the verifier left in `verification_findings` — `routes/credits.py:243`
- §3.9 — insert — `settlement_price_usd` is 0–10000 with at most 2 dp; unlike `strike_price_usd`, exactly 0 is accepted — `routes/hedges.py:78`

## Already fully pinned in my partition (no change needed)
Every list filter set and the `created_at`-ascending total order (§2.3 line 89 covers all my collections and nested listings); the immutability of documents and quality tests carrying only `id`/`created_at` (§2.4); all role sets against the §4 table; the supplier creation payload and initial field values; the two `ERR_DUPLICATE_DOCUMENT` conditions including the single-slot-per-`doc_type` consequence for expired evidence; the asymmetric due-diligence document bar; all five levels of the suspension cascade; lot creation bounds and `ERR_FEEDSTOCK_TYPE_NOT_SUPPLIED`; the governing-test rule and all four disposition-driven lot transitions; the child lot's CI adder and cost-basis roll-up; the 72-hour bilateral buffer with cancelled/completed windows invisible; the half-open campaign-intersection test on approval; `requires_turnaround` cleared on completion only when the active charge is `ACTIVE`; the catalyst swap's `DOWN_TURNAROUND` precondition and `ACTIVE|DERATED|SPENT -> REMOVED`; the first-charge exemption; day-by-day committed capacity, peak recomputation and the closed-interval touch rule; the nomination-cancellation asymmetry versus the cascade paths; both batch status dimensions and the single SAF cross-edge; the revision-round bound of 3; `ERR_NO_VERIFIED_SUPPLIER`'s unexpired-supplier definition; the dominant-feedstock tie-break; both provisional and both verified credit formulas; the four-level `ADJUSTED` cascade; partial retirement leaving the block in place and reversal restoring status from `verification_outcome`; the pinned five-step hedge margin order with the tier override.

## Sanity check (method step 4)
- `grep -n '^#'` — all 5 top-level sections present and in order (`# title`, `## 1.`–`## 5.`), with all 10 §2 and all 9 §3 subsections intact.
- Tail ends at a real section boundary: the completed §5 error table, last row `| ERR_MATURITY_IN_PAST | 422 |`.
- Strictly larger than PRD_FINALIZED.md: **121,628 bytes vs 106,225 bytes** (497 vs 492 lines).

---

## Pipeline complete — 2026-09-04T14:06:42.464Z

All nine steps finished. Deliverables: `SCAFFOLD.yaml` (3184 l), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2238 l), `SCAFFOLD_CORNER_DESIGN.yaml` (3756 l), `test_helpers/` (9 modules), `test_suite/` (19 files, 122 tests), `workspace/implementation/` (20 modules, 3365 l, 68/68 endpoints), `workspace/PRD.md` → `PRD_FINALIZED.md` → `PRD_COMPLETED.md`, and the 8 green `results.$i.json` rounds (122/122 each).

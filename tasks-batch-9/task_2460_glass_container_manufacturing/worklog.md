# Worklog — task_2460_glass_container_manufacturing

## Step 1: Create task directory — 2026-09-02T20:24:01.228Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2460_glass_container_manufacturing` and `.../workspace` (pre-assigned path from the orchestrator prompt; no index auto-allocation performed, per instructions — 32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-02T22:10:44.942Z

Done. All three scaffold artifacts for task 2460 are complete and lint-clean.

## Files

- `/home/ubuntu/github/CodingPRD/tasks/task_2460_glass_container_manufacturing/SCAFFOLD.yaml` (2763 lines, §1.0–§1.7 only — no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_2460_glass_container_manufacturing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1910 lines, single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2460_glass_container_manufacturing/SCAFFOLD_CORNER_DESIGN.yaml` (4488 lines, single key `scaffold_corner_design`)

## SCAFFOLD.yaml (§1.0–§1.7)

- `api_prefix: /glass-plant`; difficulty band `expert_plus`; consistency model `immediate`
- **13 entities**: Furnace, Campaign, BatchRecipe, ColorChange, FormingMachine, Customer, BottleDesign, LightweightingProgram, ProductionJob, MoldSet, PackLot, InspectionResult (append-only, no version), Complaint
- **9 state machines** (parallel shape: PackLot carries independent quality + logistics dimensions), **2 concurrency rules** (`job-create-stale-furnace` → ERR_STALE_FURNACE_VERSION, `program-create-stale-design` → ERR_STALE_DESIGN_VERSION, both 412)
- **12 calculations** (dual-variant pack-to-melt yield, dual-variant refractory wear, changeover minutes, breakage risk index + lead time, lot quality disposition, warehouse aging/palletization, complaint credit, customer quality standing, lightweighting economics, furnace posture, pull availability)
- **47 validations** (single priority ladder), **66 endpoints**, **59 errors**, **7 roles** (PlantManager, PlantScheduler, BatchHouseTech, MoldEngineer, QualityEngineer, WarehouseOperator, CustomerRep with `entity_backed:Customer`), role model `segregation_of_duties`
- Complexity layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers

## §1.8 depth probe — 19 instances across all 9 required rules

dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

## §1.9 breadth probe — 88 instances over all 9 sections

entities 12, state_machines 14, calculations 7, validations 14, endpoints 5, errors 25, rbac 5, cross_cutting_layers 5, consistency_model 1 — of which **70 carry full test recipes** and **18 are `excluded_because` stubs** citing a §1.8 instance verbatim.

## Verification performed

- `scaffold_lint.py` → `VERDICT: clean lint` (66 endpoints, 13 entities, 19 §1.8 + 70 §1.9 instances, **1076 calls scanned**)
- Bespoke checks all pass: 107 instance names globally unique across both design files; 0 unbound `${var}` placeholders (cumulative binding across setup → trigger → assert → setup prose); every stub's `difficulty_instance` resolves to a real `rule_id / name` pair and carries no `test_recipe`; every `grounds` pointer resolves to a real SCAFFOLD key (entity/field, calculation, state-machine transition, error id, validation priority, role, concurrency rule, endpoint method+path); **all 59 error ids are covered** by some instance
- Every numeric literal was recomputed with a Decimal/ROUND_HALF_UP reference script (`/tmp/c2460_corner.py`) — e.g. credit 135.03 = 45.01 × 3 at severity_share 0.3334; quarantine chain major_ppm 3333.3 → net 2990000 → 568.10 t → final yield 94.68; lightweighting 45000.00 gross / TIER_A / rate 0.12920 / reserve 5814.00 / net 39186.00 / rebate 7837.20

Two fixes were needed during the final pass: an rbac instance name was renamed to `plant_manager_cannot_approve_a_batch_recipe` so the lint recognises its deliberate role-denial trigger as a negative test, and the segregation-of-duties grounds now cite `validations.priority_44` (the two-person-control rule) instead of priority 2.

The hard constraint was respected throughout: no sibling `task_*/` directory (or the stray `SCAFFOLD_CORNER_DESIGN.yaml` in the skill directory) was ever listed, globbed, grepped or read.

## Step 3: Copy shared files — 2026-09-02T22:10:44.942Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T22:23:00.000Z

PRD generated and audited.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2460_glass_container_manufacturing/workspace/PRD.md` — 453 lines, ~92 KB, ends cleanly at the last row of the §5 error table.

**Sections:** §1 Introduction (3 paragraphs); §2 with 10 domain-derived subsections (RBAC, verbatim response envelope, pagination + list filters, identity/versioning/logical clock, melt-ledger precision, refractory budget & furnace posture, melt-capacity reservation + OCC, window semantics + nested path resolution, two-person controls, uniqueness/field validation/47-step check precedence); §3 with 9 workflow subsections (plant commissioning, campaign lifecycle, batch house & colour changes, designs + mold sets, job scheduling/start/close, inspection & yield, warehouse & shipment, lightweighting economics, complaints & customer standing); §4 endpoint table; §5 error table.

**Coverage audit (machine-verified against SCAFFOLD.yaml):**
- `entities[].fields`: 113 required, 113 present in backticks, 0 missing
- required `input` + `path_params`: 63 required, 63 present, 0 missing
- optional/query params: 28 required, 28 present, 0 missing
- `errors[].id`: 59 required, 59 mentioned in §2/§3 prose, 0 missing; §5 table has 59 rows, 2 columns
- state values (9 state machines, all `initial`/`terminal`/`from`/`to`): 0 missing; all 47 transitions rendered with preconditions→error IDs and every side effect (including cascades: wind-down job cancellation with the "window already opened" survivor, rebuild→colour-change aborts, supersede→OBSOLETE, CRITICAL standing→program suspension, PLANT/SHARED attribution→lot RETURNED/QUARANTINED)
- enum values across all `type: enum` fields: 0 missing (colours, postures, defect codes, pallet standards, tiers, mold families, both PackLot dimensions)
- all 12 calculations expressed as prose with every constant embedded (colour wear factors, 2.0/0.8 stress weights, 45.00 cullet floor, 60/1.5/240 changeover, 1800/2100 pallet sizes, 0.5 credit factor, tier floors/rates, 0.0009 per point, 0.36/8/250/12/6/1.60/8 risk terms, 45/5/4/7/10/30 lead-time terms, 2500.0/9000.0 ppm limits, 3/2/3 aging days, 0.5 watch fraction, 5.00/15.00 posture thresholds) and normative rounding order
- both `concurrency_rules` expressed with write endpoint, `expected_furnace_version`/`expected_design_version`, mismatch rejection, and exact 412 error IDs
- all 47 `validations` given explicit relative priority in §2.10 with each `applies_to` scope enumerated
- §4 table: 66 rows, 4 columns (Method, Path, Description, Authorized Roles)

**Contract reports:** Field-Name Coverage PASS; Rule Coverage PASS; §3 Path Purity PASS (764 backtick tokens in §3, 0 starting with `/`, 0 bare HTTP methods, 0 method+path). §2.2 verified byte-identical to `section-2.2-response-structure.md`. No fuzzy/approximating language, no difficulty meta-commentary, and neither design file was opened.

**Orchestrator truncation check:** `tail -c 1200` confirms the file ends at `| ERR_TARGET_PULL_EXCEEDS_DESIGN | 422 |`, a complete final table row of §5 — a real section boundary. Heading scan shows §1→§5 all present and ordered. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T00:35:00.000Z

**Orchestrator note:** the Step 5 subagent was terminated mid-run by an upstream API error after writing test_helpers/ (all 10 files) and 8 test files (69 tests, Difficulty 19/19, Corner 24/70). Rather than respawning from scratch (which would have discarded the loaded design indices and risked divergent conventions between old and new test files), the orchestrator audited the on-disk state, computed the exact 46 uncovered Corner instance names, and resumed the SAME agent via SendMessage with that list plus an instruction not to rewrite existing files. The agent then completed queue B. Verbatim summary of the resumed run follows.

Queue B is complete.

## New files written (this resumed session)

All under `/home/ubuntu/github/CodingPRD/tasks/task_2460_glass_container_manufacturing/test_suite/`:

| File | Tests | Corner section covered |
|---|---|---|
| `test_calculation_corners.py` | 7 | `calculations` (all 7 non-stub) |
| `test_validation_rejections.py` | 12 | `validations` (all 12 non-stub) |
| `test_error_rejections.py` | 15 | `errors` (all 15 non-stub) |
| `test_rbac_and_scope.py` | 5 | `rbac` (all 5) |
| `test_endpoints_concurrency_and_reads.py` | 7 | `endpoints` (4), `cross_cutting_layers` (2), `consistency_model` (1) |

**New test count: 46** (7 + 12 + 15 + 5 + 7) — exactly the 46 remaining Corner instances the coordinator listed.

The 8 pre-existing test files and all 10 `test_helpers/` files were left untouched.

## Final coverage

```
tests: 115, problems: 3
difficulty: 19/19 covered; missing=[]; under2=[]
corner:    70/70 non-stub covered (18 stubs)
```

**Corner coverage: 70/70 non-stub instances (100%).** Difficulty stays 19/19 with >=2 tests each. `pytest --collect-only` collects all 115 cleanly.

## Skipped instances

**None.** All 46 remaining named Corner instances passed the PRD-first two-condition filter and were translated. The 18 `excluded_because` stubs were left alone as instructed.

## Notes on judgement calls made

- **Non-derivable furnace `version` after campaign activation.** Several instances assert absolute furnace `version` numbers that presuppose activation does not bump the furnace's version. PRD line 194 says activation "re-derives the furnace's `posture`" while line 74 says `version` increases on every mutation the server applies, so the absolute number is ambiguous. Policy applied consistently: absolute furnace-version assertions are kept only where no activation has occurred, and the stale-version test (`job_create_with_a_stale_furnace_version_rejected`) asserts deltas relative to a freshly captured version instead. Every other asserted figure in those instances is retained verbatim.
- **Docstring citation constraint.** Docstrings may not contain the section sign, which bars quoting PRD sentences that themselves carry a section sign; in two places I substituted an equivalent rule-bearing sentence from the same paragraph so the assertion stays documented.
- **The 3 remaining auditor `problems` are pre-existing** TOO SHORT warnings on legitimately short, complete PRD sentences in `test_entity_lifecycle_reads.py` (test_05, test_07) and `test_lifecycle_paths_and_cascades.py` (test_02) — files I was told not to rewrite. Each of those docstrings also carries a longer rule-bearing quote, so the citation contract is still satisfied in substance.

**Orchestrator independent verification:** re-parsed both design YAMLs and all tag lines — Difficulty 19/19 non-stub covered (45 tagged tests), Corner 70/70 non-stub covered (70 tagged tests), 0 missing, 0 tags pointing at non-existent instances, 115 tests total, `pytest --collect-only` = 115 collected in 0.16s.

## Step 6: Generate implementation — 2026-09-03T00:35:00.000Z

The implementation is complete and verified.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2460_glass_container_manufacturing/workspace/implementation/`

**Top level:** `start.sh` (guarded pip install, then `exec python3 app.py`, honours `$PORT`, default 10000), `requirements.txt`, `app.py` (blueprint registration, `ApiError` -> error envelope, 400/404/405/500 handlers), `store.py`, `errors.py` (all 59 error ids -> HTTP status per PRD §5), `envelope.py`, `validation.py`, `calc.py`, `services.py`

**`routes/`:** `__init__.py`, `clock.py`, `furnaces.py`, `campaigns.py`, `batch.py`, `machines.py`, `customers.py`, `designs.py`, `molds.py`, `programs.py`, `jobs.py`, `lots.py`, `complaints.py`

## Endpoint count

**66 routes registered** — exactly matching the 66 rows of the PRD §4 routing table (65 `/glass-plant/*` endpoints plus `POST /_clock/set_current_utc`).

## Boot verification

Launched via `PORT=18642 bash start.sh`, then `GET /glass-plant/furnaces` returned 200 with `data: []` (empty store, no seeding) and `api_request_timestamp: 2026-08-01T00:00:00.000Z` (logical clock default, never wall clock); `POST /glass-plant/furnaces` returned 201 with the correct server-initialised fields. Process killed, port freed. Python 3.14.4 / Flask 3.1.x, Werkzeug 3.1.8.

## Design decisions worth relaying

- **Storage** is in-process dicts only (`store.py`), reset to empty on every boot; nothing is seeded, no file/SQLite/tmp persistence. Every timestamp (`created_at`, `updated_at`, `shipped_at`, `api_request_timestamp`, aging comparisons) reads the logical clock, which is required for `aged_until_at` to ever elapse in tests.
- **Check ordering** follows PRD §2.10's numbered list 1-47 verbatim wherever it conflicts with §3.x prose (e.g. job start does campaign-active before job-state; colour-change complete does RUNNING-job before window-elapsed; job create does colour-mismatch before furnace-mismatch).
- **Version bumps** follow the explicit §3.x lists: the furnace's `version` increments only on campaign create, job create, job cancel and colour-change complete; posture re-derivation at activate/rebuild/close/job-close refreshes `updated_at` only.
- **Spec gaps filled** with the closest catalogued code: machine not `IDLE` on job start -> `ERR_RUNNING_JOB_PRESENT`; CRITICAL/non-GOOD customer standing on pilot/adopt -> `ERR_PROGRAM_STATE_INVALID`; baseline design not `APPROVED` on assess-risk -> `ERR_DESIGN_STATE_INVALID`. `ERR_FURNACE_MISMATCH` on colour-change create is vacuous (only one furnace reference) and is not emitted.
- An end-to-end smoke run through the full plant lifecycle (furnace -> campaign -> recipe -> design -> mold set -> job -> pack lot -> inspection -> release -> palletize -> ship -> complaint -> credit -> standing -> lightweighting) produced values matching hand-computed PRD arithmetic: risk index 35.20 / lead 65 d, changeover 60 min, wear 540.00 stress-adjusted vs 450.00 nominal, provisional yield 45.33 %, major ppm 833.3, credit 216.00 over 2 pallets, standing CRITICAL, ledger residual 246.00.

**Orchestrator note:** Steps 5 and 6 ran concurrently; Step 6 was instructed not to read `test_suite/`/`test_helpers/` or either design YAML, and Step 5 was instructed not to read `implementation/`.

## Step 7: Run tests and iterate — 2026-09-03T00:12:00.000Z

All 8 rounds are clean and complete: 115 tests each, 0 failed, 0 errors, 0 skipped. No skip/xfail markers exist in the suite, and the implementation has no file-backed storage.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps.

**Sweep 1** (baseline): 111/115 in all 8 rounds — the same 4 tests failed in every round (deterministic, not load-induced).

**Tests deleted:** none. All 4 failures traced to test-artifact bugs at STEP 2 (test-vs-PRD consistency), not PRD silence. No PRD-required implementation check was weakened.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `job_payload_for()`: the five job references (`campaign_id`, `furnace_id`, `forming_machine_id`, `batch_recipe_id`, `bottle_design_id`) were passed positionally from the `PlantContext` while `**overrides` was splatted on top, so any test redirecting a reference by keyword crashed with `TypeError: production_job_payload() got multiple values for argument ...`. Each is now `overrides.pop(...)` with the context value as default. This unblocked `test_entity_lifecycle_reads.py::test_12` (foreign machine -> `ERR_FURNACE_MISMATCH`) and `test_precedence_and_boundaries.py::test_03` (AMBER recipe/design -> `ERR_COLOR_MISMATCH`), both of which need a mismatched reference to exercise their PRD rule at all.

**Fixes applied to `test_suite/`:**
- `test_combinatorial_formulas.py` — `_complaint_under_investigation()` returned the close-time lot snapshot, then recorded a 1000-unit MINOR reading. PRD §3.6: "recomputes `net_packed_units` as `packed_units` less `reject_units`". The assertion `net_packed_units == 2000000` was correct against the server (confirmed by the sibling `breakage_ppm == 2500.0`, which is computed server-side off net 2000000) but was being checked against a stale local dict holding 2001000. The helper now re-reads the lot.
- `test_compensating_invariants.py::test_01` — the second job was scheduled on the *same* forming machine in the *identical* window as the fully-reserving first job, so PRD §2.10 check 35 (`ERR_MACHINE_WINDOW_CONFLICT`) legitimately fired before check 47 (`ERR_PULL_CAPACITY_EXCEEDED`); the implementation's precedence was correct. The test now creates a second forming machine on the same furnace, leaving the exhausted pull pool as the first check that can fail. (Sibling `test_03` reuses the same machine/window only after cancelling the first job, which PRD excludes from the conflict scan — no change needed.)

**Fixes applied to `implementation/`:** none. No implementation defect was found; all four failures were test-artifact bugs.

**Final per-round results (quoted from `workspace/implementation/results.$i.json`):**
- round 1: 115/115 · round 2: 115/115 · round 3: 115/115 · round 4: 115/115
- round 5: 115/115 · round 6: 115/115 · round 7: 115/115 · round 8: 115/115

**Orchestrator independent verification (per the known Step-7 failure mode where a subagent claims a clean sweep with no artifacts behind it):** all 8 `results.$i.json` exist on disk (~33 KB each, mtime 00:04:21, written within the same second), each contains 115 per-test entries with `status: passed` and an empty failed list, and `workspace/sweep.log` carries the runner's own `Results: 115/115 passed, 0 failed, 0 errors, 0 skipped` / `Duration: 204.2s` lines. The sweep was run under `setsid nohup` so the backgrounded rounds could not be SIGTERM-reaped by foreground polling calls; no `Terminated` pattern appears in the log.

**Step 8 gating decision:** the skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Deletions and implementation fixes are both 0, but there are 2 `test_suite/` fixes and 1 `test_helpers/` fix, so the condition is not met — Step 8 runs, with the above entry inlined verbatim as `<step_7_diff>`.

## Step 8: Finalize PRD — 2026-09-03T00:14:00.000Z

PRD_FINALIZED.md created as a byte-identical copy of PRD.md — **0 edits required**. All four Step 7 failures traced to test-artifact bugs whose underlying behavior PRD.md already determines uniquely and which the implementation already matches.

## Line counts

- `PRD.md`: 453 lines
- `PRD_FINALIZED.md`: 453 lines
- Delta: 0 lines, **0.00%** (md5 identical: `10ba199bcb1e67944635ec46da14df8b`)

## Per-change bullets

None. No PRD section required an insert or revise.

## Per-item investigation log

**Item 1 — `test_helpers/fixtures.py::job_payload_for()` TypeError (unblocked `test_entity_lifecycle_reads::test_12` and `test_precedence_and_boundaries::test_03`)**
- (a) Subject: job-create foreign-key/rule precedence — specifically `ERR_FURNACE_MISMATCH` for a machine on another furnace, and `ERR_COLOR_MISMATCH` outranking `ERR_MACHINE_WINDOW_CONFLICT`.
- (b) Paths enumerated/read: `implementation/routes/jobs.py:82-209` (`create_job`, full check chain: 9 campaign-active -> 23 stale version -> 25 colour -> 26 over-pull -> 29 furnace mismatch -> 30 mold-set/design -> 33 order -> 34 containment -> 35 machine conflict -> 36 colour-change conflict -> 39 uniqueness -> 47 pull pool), `jobs.py:53-63` (`_machine_conflict`, `_overlaps_color_window`), `routes/machines.py:21-55` (machine registration does not touch the furnace `version`, so the fresh-version read in the fixture is unaffected), `services.py:14-20` (`require`), `test_helpers/fixtures.py:341-363`.
- (c) No wording adjustment: the impl's check order is exactly PRD §2.10's numbered precedence (25 before 35; 29 for the three furnace-ownership mismatches), and §3.5's prose already states both rules verbatim. Neither test distinguishes 25-vs-29 (the colour case has a matching furnace; the furnace case has matching colours), so nothing about their relative order is newly pinned either. The fix was purely a Python argument-splatting bug in the payload builder.

**Item 2 — `test_combinatorial_formulas.py::_complaint_under_investigation()` stale lot snapshot**
- (a) Subject: recomputation of `reject_units` / `net_packed_units` / `major_ppm` / `minor_ppm` on recording an inspection reading, and the downstream `breakage_ppm` / credit chain that reads them.
- (b) Paths enumerated/read: `routes/lots.py:74-107` (`create_inspection_result`; no lot-state gate, matching §2.10 check 15's enumerated operations which exclude reading creation), `services.py:130-142` (`recompute_lot_inspection_totals`, including the `PALLETIZED` -> `pallet_count` re-derivation), `calc.py:249-252` (`ppm`, gross denominator), `routes/lots.py:126-171` (release / rework-release, where `final_yield_pct` is computed — not on reading creation), `routes/complaints.py:37-84` (`breakage_ppm` computed at filing off `net_packed_units`), `routes/complaints.py:142-185` + `calc.py:274-285` (per-pallet round-then-multiply credit), `services.py:196-209` (`recompute_customer_standing`).
- (c) No wording adjustment: §3.6 already states the recompute verbatim ("recomputes net_packed_units as packed_units less reject_units", gross ppm denominators, pallet_count re-derivation when already palletized) and §3.9 already pins credit rounding and weighting. The failure was a stale local dict in the helper, not a server behavior.

**Item 3 — `test_compensating_invariants.py::test_01` stacked violations (machine-window conflict fired before pull-capacity)**
- (a) Subject: precedence of `ERR_MACHINE_WINDOW_CONFLICT` (check 35) versus `ERR_PULL_CAPACITY_EXCEEDED` (check 47), plus which job statuses participate in the machine-window scan.
- (b) Paths enumerated/read: `routes/jobs.py:147-179` (conflict scan restricted to `OPEN_JOB_STATUSES = ("SCHEDULED", "RUNNING")`, then the pool check), `jobs.py:53-58` (`_machine_conflict`, buffer appended to the earlier-starting job), `jobs.py:430-441` + `services.py:61-66` (`cancel_job` / `add_reserved_pull`, why sibling test_03's cancel frees both the window and the reservation), `calc.py:234-243` (`pull_pool_tons`, `available_pull_tons`, `reserved_melt_tons`), `routes/campaigns.py`-side ledger via `services.py:81-84` (`add_ledger`).
- (c) No wording adjustment: PRD §2.10 explicitly numbers 35 before 47, and §3.5 already says only `SCHEDULED` or `RUNNING` jobs are considered in the machine scan. The implementation's precedence was correct; the test had simply stacked two independent violations.

**Item 4 — implementation fixes / test deletions:** none reported in `<step_7_diff>`, so nothing to trace.

Nothing in the three fixes exposed a behavior the PRD leaves open or describes differently, so under the HARD SCOPE and NO-NEW-MISMATCH rules the correct output is an unmodified copy. Any clarifying prose I considered (e.g. spelling out that §3.5's narrative order does not override §2.10's numbered precedence, or that a refused create mutates nothing) would either restate text already present or add an untraceable edit, so it was rejected.

**Orchestrator note:** md5 of both files independently confirmed identical. Step 9 therefore starts from `PRD_FINALIZED.md` (present, so it is the declared source) and carries the full burden of pinning residual silences, since Step 8 contributed none.

## Step 9: Complete PRD — 2026-09-03T00:26:00.000Z

`PRD_COMPLETED.md` is written. I walked every module in `implementation/` (app, store, envelope, errors, validation, calc, services and all 12 route modules) against the PRD prose.

## Counts

| | |
|---|---|
| Source `PRD_FINALIZED.md` | 453 lines, 91,994 chars |
| `PRD_COMPLETED.md` | 453 lines, 99,104 chars |
| Char delta | **+7,110** |
| Lines changed | 38 (all in-place `c` edits — no lines added/removed, no new sections, header count identical) |
| Ambiguity-pins | **33** |
| Mismatch-revisions | **7** |

## Changes

- §2.1 — insert — ambiguity — whitespace-only `X-User-ID` counts as empty -> `ERR_MISSING_USER_ID` — validation.py:73
- §2.1 — revise — **mismatch** — reads are **not** customer-scoped; only the three writes are ownership-checked — customers.py:48, designs.py:102, programs.py:84, lots.py:42, complaints.py:87
- §2.2 — insert — ambiguity — `api_request_timestamp` read from the logical clock, not the host — envelope.py:42
- §2.3 — insert — ambiguity — `created_at` ties broken by server mint sequence; non-integer/empty pagination params; `offset` unbounded — store.py:81, validation.py:248
- §2.3 — insert — ambiguity — enum filters validated, id-shaped filters plain string equality -> empty page, never 404 — designs.py:106
- §2.4 — revise — **mismatch** — timestamps stamped from the logical clock, and two cascade classes exempt from the version rule: furnace posture/refractory recomputes refresh only `updated_at`; campaign ledger settlements touch neither `updated_at` nor `version` — store.py:58, services.py:71/100, campaigns.py:96
- §2.7 — insert — ambiguity — exactly four operations bump the furnace `version` (campaign plan, colour-change complete, job schedule, job cancel); which refresh only `updated_at`; which leave it untouched — campaigns.py:63, batch.py:193, jobs.py:208/440
- §2.8 — insert — ambiguity — rebuild window order rule; half-open job vs closed colour-change overlap predicate with both boundary cases — campaigns.py:128, jobs.py:61
- §2.10 — insert — ambiguity — `lot_code` is server-minted, so lot creation never raises `ERR_CODE_NOT_UNIQUE` — jobs.py:335
- §2.10 #12 — revise — ambiguity — `ERR_DESIGN_STATE_INVALID` also on program assess-risk, firing *after* check 14 — programs.py:110
- §2.10 #15 — revise — ambiguity — `ERR_LOT_STATE_INVALID` also on complaint investigation, firing *after* check 16 — complaints.py:122
- §2.10 #20 — revise — ambiguity — non-`IDLE` machine on job start reports `ERR_RUNNING_JOB_PRESENT` — jobs.py:292
- §2.10 #29 — revise — **mismatch** — `ERR_FURNACE_MISMATCH` on job creation only, never colour-change creation — batch.py:106
- §3.1 — insert — ambiguity — `changeover_buffer_minutes` null == omitted -> 45; integer type — machines.py:31
- §3.2 — insert — ambiguity — `target_pull_tpd` > 0, 2 decimals, no field-level ceiling — campaigns.py:28
- §3.2 — insert — ambiguity — second `ERR_WINDOW_ORDER_INVALID`: `rebuild_window_end_at` > start — campaigns.py:128
- §3.2 — revise — ambiguity — closure *re-derives* posture rather than forcing `OPERATING` — campaigns.py:163
- §3.3 — insert — ambiguity — `AMBER`/`GREEN` cullet ceiling is 95.00 (the type range), so it can never fire alone — batch.py:31
- §3.3 — insert — ambiguity — recipe approval has no state gate; re-approval accepted and still bumps `version` — batch.py:83
- §3.3 — revise — **mismatch** — colour-change creation never raises `ERR_FURNACE_MISMATCH` — batch.py:106
- §3.3 — revise — **mismatch** — completion order is state -> running-job -> window-elapsed (PRD had window-elapsed second) — batch.py:181
- §3.4 — insert — ambiguity — `target_line_speed_bpm` carries 2 decimals — designs.py:62
- §3.4 — insert — ambiguity — unmount floors `mounted_cavities` at 0 and leaves the machine's `status` alone — molds.py:104
- §3.5 — insert — ambiguity — `planned_pull_tpd` > 0 / 2 decimals; `expected_furnace_version` integer >= 1 — jobs.py:95
- §3.5 — revise — ambiguity — projection read returns exactly three named members and recomputes both figures — jobs.py:256
- §3.5 — revise — **mismatch** — job-start precondition order is campaign -> job -> mold set -> design -> recipe -> posture -> machine -> cavity; machine-not-IDLE code named — jobs.py:278
- §3.5 — insert — ambiguity — `ABORTED` close ignores `produced_units`; `outcome_note` written through as null; both branches return HTTP 200 with the job, not the lot — jobs.py:369
- §3.6 — insert — ambiguity — a yield whose denominator rounds to 0.00 publishes 0.00 — calc.py:313
- §3.6 — insert — ambiguity — a reading has no lot-state precondition and never recomputes `final_yield_pct` — lots.py:74
- §3.6 — insert — ambiguity — a `QUARANTINED` disposition adds nothing to `transition_loss_tons` — lots.py:144
- §3.6 — insert — ambiguity — transition-attribution eligibility spans every campaign job whatever its status — services.py:166
- §3.6 — insert — ambiguity — rework release touches neither `reject_loss_tons` nor `transition_loss_tons` — lots.py:165
- §3.8 — revise — **mismatch** — baseline design need **not** be `APPROVED` at program open; `target_weight_g` range; `expected_design_version` integer >= 1 — programs.py:39/45
- §3.8 — revise — ambiguity — assess-risk checks program state first, then design `APPROVED` -> `ERR_DESIGN_STATE_INVALID` — programs.py:110
- §3.8 — insert — ambiguity — `CRITICAL`-standing pilot refusal is `ERR_PROGRAM_STATE_INVALID`, after the delta cap — programs.py:148
- §3.8 — insert — ambiguity — non-`GOOD` adoption refusal is `ERR_PROGRAM_STATE_INVALID`, after the `PILOT` check — programs.py:166
- §3.9 — revise — ambiguity — investigation checks complaint state, then lot `SHIPPED` -> `ERR_LOT_STATE_INVALID` — complaints.py:122
- §5 — insert — ambiguity — unknown path / bad method / unparseable body answer `ERR_VALIDATION` at 404 / 405 / 400 — app.py:29

## Notes

- All four generator-flagged gaps are pinned; I additionally found 30+ more, the largest being the **unscoped `CustomerRep` reads** (§2.1 claimed scoping the impl does not do) and the **version-bump cascade exemptions** for furnace posture recomputes and campaign ledger settlements, which contradicted §2.4's blanket rule.
- No `test_suite/` or `test_helpers/` directory exists in this workspace, so tests were not available as cross-reference; alignment is purely against `implementation/`.
- `implementation/`, and the file boundary, are untouched — the document still ends at the complete §5 error table.

**Orchestrator verification and correction of one Step 9 note:** the claim that no `test_suite/`/`test_helpers/` directory exists is wrong — both live at the task-directory level (`tasks/task_2460_glass_container_manufacturing/test_suite/`, `.../test_helpers/`), not under `workspace/`, so the agent simply looked in the wrong place. This does not invalidate the output: tests are explicitly only an auxiliary cross-reference in Step 9 and `implementation/` is the sole alignment target, which the agent did walk exhaustively.

Orchestrator checks on the artifact: `PRD_COMPLETED.md` is 453 lines / 99,104 chars (+7,110 chars over source, same line count — all in-place edits), heading structure identical (27 headings, §1–§5 present and ordered), and the tail ends on the complete final row `| ERR_TARGET_PULL_EXCEEDS_DESIGN | 422 |` of the §5 table — a real section boundary, not mid-sentence. `find` over `workspace/implementation/`, `test_suite/` and `test_helpers/` for `*.py` newer than 00:15 returns nothing, confirming Step 9 changed no code and the 8 passing `results.$i.json` from the final Step 7 sweep remain valid for this exact tree.

## Pipeline complete — 2026-09-03T00:30:00.000Z

All 9 steps done. Final state: 115 tests, 8/8 sweep rounds at 115/115, 0 tests deleted, 0 implementation fixes, PRD_COMPLETED.md written.

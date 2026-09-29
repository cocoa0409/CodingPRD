# Worklog — task_2712_greenhouse_vegetable_production

## Step 1: Create task directory — 2026-09-04T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2712_greenhouse_vegetable_production` and its `workspace/` subdirectory. Index 2712 was pre-assigned by the orchestrating invocation; no scan of `./tasks/` was performed and no other task directory was created.

## Step: scaffold generation (SCAFFOLD + difficulty + corner design)
- SCAFFOLD.yaml: 13 entities, 57 endpoints, 75 errors, 11 calculations, 11 state machines, 41 validations, 6 roles, 3 concurrency rules; difficulty_level expert_plus.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml: all 9 §0.5 rules x 2 instances = 18.
- SCAFFOLD_CORNER_DESIGN.yaml: all 9 §1.9 sections, 58 instances (42 with test recipes, 16 excluded_because stubs citing §1.8).
- scaffold_lint.py: clean verdict (535 calls scanned).

## Step 2: Generate Scaffold (subagent) — 2026-09-04T11:52:00.000Z

Scaffold complete for `task_2712_greenhouse_vegetable_production`, generated purely from the scenario text plus the scaffold-generator spec (no sibling task was read).

**Files** (all valid YAML, each ending at a real instance boundary), in `/home/ubuntu/github/CodingPRD/tasks/task_2712_greenhouse_vegetable_production/`:

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3759 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1487 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2213 |

**SCAFFOLD.yaml** (§1.0–§1.7 + preamble `scenario`/`domain_name`/`api_prefix`; no `scaffold_difficulty_design` or `scaffold_corner_design` keys): 13 entities, 57 endpoints, 75 errors, 11 calculations (each with variants), 11 state-machine entries across 9 entities (incl. HarvestLot's two independent dimensions), 41 priority-ordered validations, 6 roles, 3 optimistic-concurrency rules. Profile: `difficulty_level: expert_plus`, `consistency_model: immediate`, `role_model: segregation_of_duties`, `state_machine_shape: cyclic`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, archetypes `quota_allocation` / `temporal_windowing`.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — all nine §0.5 rules, 2 instances each (18 total), each pair differentiated per spec: `dual_variant_calc` (energy/CHP vs commitment payout), `combinatorial_formula` (mode b rounding order vs mode c pinned recirc cap), `non_linear_state_machine` (parallel grading/cold-chain dimensions vs bounded 2-pass revision cycle), `transitive_cascade` (depth 3 drainage→irrigation lock→nutrient stress; depth 2 cycle abort→task cancel→budget repay), `priority_pair_validation_conflict` (13 vs 31; 9 vs 22), `boundary_precision_check` (bonus ratio exactly 1.1000; half-open 7-day eligibility bound), `cross_entity_state_dependency` (allocation↔cold chain; labor task↔zone IPM posture), `resource_temporal_overlap` (half-open climate windows by zone+regime; closed worker window widened by travel buffer), `compensating_invariant` (zone labor money; lot graded pounds).

**SCAFFOLD_CORNER_DESIGN.yaml** — all nine claim-extraction-guide sections, 58 instances (42 with full test recipes, 16 `excluded_because` stubs that all cite existing §1.8 instance names): entities 11, state_machines 10 (5 stubs), calculations 8 (5), validations 8 (3), endpoints 6 (1), errors 4, rbac 4, complexity_layers 6 (2), consistency_model 1.

**Lint** — `python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2712_greenhouse_vegetable_production`:

```
Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     42
  Calls scanned (§1.8+§1.9):  535

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Also verified independently: all 76 instance names unique across §1.8 ∪ §1.9, and no dangling `excluded_because.difficulty_instance` citations. Two fixes applied during the pass: FertigationBatch captures corrected to the §1.1 names `recirculated_liters_applied` / `fresh_liters_applied`, and a stray non-schema `trigger_note:` key folded into that instance's `assert` list.

(Orchestrator note: the Step 2 subagent also appended its own short bullet summary above this entry, before the orchestrator wrote the formal record. Left in place — worklog is append-only.)

## Step 3: Copy Shared Files — 2026-09-04T11:52:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD (subagent) — 2026-09-04T12:08:00.000Z

PRD generation is complete.

## Deliverable
`workspace/PRD.md` — **545 lines / 16,704 words**, built incrementally (one `Write` + chunked `cat >>` heredoc appends; never rewritten whole). Tail verified: the file ends at `| \`ERR_INSUFFICIENT_AVAILABLE_LBS\` | \`409\` |`, the last row of the completed §5 table. Final section heading: **`## 5. Error Code Catalogue`**. No audit footer, no contract-report section in the file.

## Section list
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Operator Identity and RBAC, 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, verified by exact-substring match), 2.3 Pagination, 2.4 Common Resource Properties/Timestamps/Versioning, 2.5 The Logical Clock, 2.6 Compartment Posture Derivation and Cascade Discipline, 2.7 Decimal Discipline, 2.8 Stale-View Protection, 2.9 Conserved Quantities, 2.10 Rejection Precedence, 2.11 Flat Topology and Path Resolution
- §3 Business Logic & Workflows — 3.1 Compartments & Cultivars, 3.2 Crop-cycle planning & yield projection, 3.3 Crop-cycle lifecycle, 3.4 Climate windows & energy settlement, 3.5 Fertigation & drainage, 3.6 IPM scouting/release/re-entry, 3.7 Pollination & yield haircut, 3.8 Workers/productivity/labor budget, 3.9 Harvest lots: grading & cold chain, 3.10 Retail programs, allocation waterfall & weekly settlement
- §4 Endpoint Definitions (4-column table)
- §5 Error Code Catalogue (2-column table)

## Scaffold coverage
13/13 entities · **57/57 endpoints** (verified row count) · 11/11 calculations, both variants each · 11/11 state-machine dimensions over 9 entities, every transition incl. self-loops (`OPEN`->`OPEN`, `REGRADED`->`REGRADED`, `LOCKED`->`LOCKED`), reverts (`TERMINATION_SCHEDULED`->`PRODUCTION`, `ALLOCATED`->`OPEN`, `APPROVED`->`REQUESTED`) and divergent terminals · 41/41 validations enumerated as an ordered 1-41 precedence list in §2.10 · **75/75 error IDs** with fixed HTTP statuses · 6/6 roles · 3/3 OCC rules · all 15 domain constants by value.

## Hard Contract reports (transcript only)

**Contract 1 — Field-Name Coverage: PASS.** 192 required identifiers extracted programmatically from `entities[].fields[].name` plus every `endpoints[].input` token (optional `?` stripped). Pass 1 (substring-in-backticked-span): 0 missing. Pass 2 (stricter — token must appear as its own complete backticked span): 0 missing. Note: the checker must strip fenced blocks first, or the §2.2 JSON fences break backtick pairing and produce a false 100% failure.

**Contract 2 — Rule Coverage: PASS.** All 41 `validations[].priority` orderings written as an explicit numbered precedence list with error IDs, HTTP statuses and full `applies_to` scope enumeration, including the cross-cutting inversions (safety gates at priority 13/14 outranking the fiscal `ERR_LABOR_BUDGET_EXCEEDED` at 39). All 3 concurrency rules rendered in stale-view framing with `write_endpoint` + `expected_zone_version`/`expected_lot_version` + `ERR_STALE_ZONE_VERSION`/`ERR_STALE_LOT_VERSION` + `412`; grep confirms zero occurrences of "simultaneous", "first-writer" or "race" (the one `race` hit is inside "grace"). Every cross-entity cascade written hop by hop: 4-hop cold-chain reject, 3-hop allocation revoke, 3-hop IPM lock, crop-cycle abort, drain alarm. Sibling-branch symmetry stated for `CLOSED_FULFILLED`/`CLOSED_SHORT`, `CANCELLED`/`NO_SHOW`, all three `-> REJECTED` edges and both regrade edges. Every calculation reproduced operand-for-operand with its rounding point (round-then-sum for weekly yield; 4 dp `density_factor`/`productivity_ratio`; 3 dp EC; 1 dp `injector_ml`); no fuzzy-word matches for approximately/roughly/as needed/etc.

**Contract 3 — §3 Path Purity: PASS.** §3 extracted from `## 3.` up to `## 4.` (lines 201-400); every backticked token scanned: 0 starting with `/`, 0 bare HTTP methods, 0 method+path combinations. §3 refers to operations by state-transition framing, role + action verb, or capability description throughout; HTTP status codes and error IDs appear in prose as permitted.

**Orchestrator truncation check (mandated guard): PASS.** Independently verified after the subagent exited — `wc -l` = 545; `grep '^## '` returns exactly the five expected top-level sections (lines 3, 11, 201, 401, 465); `tail -15` ends on a complete `| \`ERR_INSUFFICIENT_AVAILABLE_LBS\` | \`409\` |` table row at a real section boundary, not mid-sentence. No regeneration needed.

## Step 6: Generate Implementation (subagent) — 2026-09-04T12:50:00.000Z

(Orchestrator note on ordering: Steps 5 and 6 were launched concurrently. Step 6 returned first, so its entry is appended ahead of Step 5's. The worklog is append-only, so the physical order here reflects completion order, not step order.)

The implementation is complete.

## Files written (all under `workspace/implementation/`)

| File | Lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 72 |
| `store.py` | 113 |
| `money.py` | 54 |
| `errors.py` | 112 |
| `envelope.py` | 119 |
| `authz.py` | 99 |
| `fields.py` | 175 |
| `const.py` | 125 |
| `helpers.py` | 70 |
| `calc.py` | 705 |
| `routes/__init__.py` | 0 |
| `routes/zones.py` | 159 |
| `routes/cycles.py` | 217 |
| `routes/climate.py` | 170 |
| `routes/fertigation.py` | 201 |
| `routes/ipm.py` | 271 |
| `routes/labor.py` | 236 |
| `routes/lots.py` | 232 |
| `routes/commerce.py` | 345 |
| `routes/clock.py` | 30 |
| **total** | **3516** |

Every module compiles (`python3 -m py_compile`); `__pycache__` removed.

## Endpoint coverage: 57 / 57

`app.app.url_map` reports exactly 57 non-static rules, and they match the scaffold's 57 method+path pairs one-for-one: zones/varieties 7, crop-cycles 6, climate-strategies 5, fertigation-batches 5, IPM (observations + bio-control-releases incl. approve/transitions/execute) 9, workers/labor-tasks 7, harvest-lots 6, commerce (programs/weeks/allocations/allocation-runs) 11, `POST /_clock/set_current_utc` 1.

## start.sh contract — confirmed

- `exec python3 app.py` runs in the **foreground** (no `&`, no nohup inside).
- `app.py` reads `int(os.environ.get("PORT", "10000"))` and calls `app.run(host="0.0.0.0", ...)` — so `$PORT` passes straight through and the default is 10000.
- `pip install` is guarded by an `import flask` probe, so per-test reboots do not re-install.
- No persistence anywhere: `store.reset()` runs at import, storage is 14 plain dicts, and the logical clock is re-parked at `2026-08-01T00:00:00Z`.

## Smoke check (fresh boot, port 45712, killed by captured pid only)

Port 39712 was already occupied by another pipeline, so I used 45712. Verified end-to-end over three scripted passes: zone -> variety -> crop-cycle -> transition -> hive placement -> climate strategy (OCC on `expected_zone_version`, energy projection, actuals settlement + `ERR_ACTUALS_ALREADY_RECORDED`) -> fertigation batch (blend, DELIVERED with volume variance, drainage reading, RECONCILED) -> scouting observation -> bio-control release (`ERR_SEGREGATION_OF_DUTIES` on self-approval, approve, `ERR_RELEASE_COUNT_OUT_OF_TOLERANCE`, execute) -> worker/labor-task -> harvest lot -> grade -> cold-chain PRECOOLED/COLD_HELD -> retail program -> commitment week -> allocation run -> allocation CONFIRMED -> week SHIPPED (fill_rate 100.00) -> week CLOSED_FULFILLED (final penalty 0.00) -> clock advance (strategy `ACTIVE`->`EXPIRED`, zone `ipm_posture` `LOCKED`->`NORMAL` once `reentry_clear_at` passed). Envelope, pagination meta, `ERR_UNAUTHENTICATED` (401), `ERR_UNAUTHORIZED` (403) and unknown-path `ERR_NOT_FOUND` (404) all render correctly.

Then I killed the pid, relaunched `start.sh` on the same port, and confirmed the second boot returned `[]` for `/zones` and `/harvest-lots` and a `created_at` of `2026-08-01T00:00:00.000Z` — state is fully wiped per invocation. Server stopped afterwards; `ss` and `lsof -ti:45712` both clean. No broad pkill was used.

Two notes for the record: the only 422s I hit during smoke testing were my own wrong payload field names in the throwaway script — re-checked against SCAFFOLD.yaml, the implementation's required inputs (`rh_setpoint_pct`, `screen_position_pct`, `gas_consumed_m3`/`chp_generated_kwh`/`grid_import_kwh`/`screen_deployed_hours`, `requested_recirculated_liters`, `observation_id`, `planned_release_count`/`planned_release_date`, `revised_release_count`) match the scaffold exactly. Test blindness was maintained throughout: `test_helpers/`, `test_suite/`, both SCAFFOLD_*_DESIGN.yaml files, the concurrent agents' output files, and all sibling task directories were never read, listed or grepped, and pytest was never run.

## Step 5: Generate Unit Tests (subagent) — 2026-09-04T12:48:00.000Z

Test suite generation is complete and fully audited.

## Files written (all at the TASK ROOT, none under `workspace/`)

`test_helpers/` — 2317 lines
| file | lines |
|---|---|
| `__init__.py` | 47 |
| `types.py` | 465 |
| `api_client.py` | 239 |
| `api_errors.py` | 166 |
| `assertions.py` | 364 |
| `constants.py` | 88 |
| `factories.py` | 239 |
| `test_users.py` | 90 |
| `fixtures.py` | 619 |

`test_suite/` — 5148 lines, **128 tests**
| file | lines | tests |
|---|---|---|
| `conftest.py` | 46 | — |
| `test_10_energy_settlement_and_payout.py` | 338 | 8 |
| `test_11_yield_curve_and_fertigation_blend.py` | 201 | 9 |
| `test_12_calculation_corners.py` | 385 | 8 |
| `test_20_lot_grading_and_release_machine.py` | 307 | 6 |
| `test_21_cascade_effects.py` | 316 | 7 |
| `test_22_compensating_invariants.py` | 318 | 8 |
| `test_23_state_machine_corners.py` | 401 | 12 |
| `test_30_rejection_precedence.py` | 238 | 5 |
| `test_31_boundary_precision.py` | 224 | 5 |
| `test_32_cross_entity_gating.py` | 271 | 6 |
| `test_33_temporal_and_resource_overlap.py` | 303 | 6 |
| `test_34_validation_corners.py` | 263 | 6 |
| `test_40_entity_corners.py` | 379 | 15 |
| `test_41_endpoint_corners.py` | 368 | 10 |
| `test_42_error_corners.py` | 147 | 4 |
| `test_43_rbac_corners.py` | 220 | 5 |
| `test_44_occ_and_complexity_layers.py` | 290 | 6 |
| `test_45_consistency_model.py` | 133 | 2 |

## Coverage

- **Queue A (§1.8): 18/18 instances**, minimum 2 tests per instance (target met exactly at the floor for every one).
- **Queue B (§1.9): 42/42 non-stub instances**, minimum 1 test each. All 16 `excluded_because:` stubs left untranslated with no placeholders; every stub's `difficulty_instance:` cross-reference was confirmed to resolve to a real queue-A `name:`.
- **Skipped instances: none.** All 60 non-stub instances passed the PRD-first two-condition filter.

## Automated audit (all green)

128 tests, 128 `Design:` lines, each exactly one and each the final docstring line; every tag resolves to a real yaml `name:` and none points at a stub; every docstring citation verified as a verbatim substring of `PRD.md`; `py_compile` clean on all 28 files; pyflakes clean on `test_suite/` (no undefined names, no unused imports); zero `skip`/`xfail`; the word "scaffold" appears nowhere; `workspace/` contains no `test_helpers/` or `test_suite/`. No server was started, no pytest run.

## Assertions dropped as not uniquely derivable (instances kept)

- **`planned_end_date` everywhere.** PRD §3.2 contradicts itself: the stated derivation (transplant + `cycle_length_weeks`x7, pulled back one day) gives 2026-11-01 for the worked case, while the very next sentence's example says 2026-10-31. I caught two agents landing on opposite values and had both drop the assertion. **This is a PRD defect worth fixing in the Step 8/9 finalization pass.** `first_harvest_allowed_date == "2026-08-24"` is consistent under both readings and is asserted.
- `limit: 101` -> `ERR_VALIDATION` (PRD never names the error above the 100 cap); "`created_at` equals the logical clock"; `provisional_penalty_usd == 400.00` at week open (PRD fixes only four fields at open).

## Recipe/PRD conflicts resolved in the PRD's favour

- HTTP statuses always come from PRD §5 via the registered map (`validate_error` called without an explicit status), which corrects the yaml on `ERR_VALIDATION`/`ERR_INVALID_ENUM_VALUE` (422), `ERR_HIVE_SLOTS_EXCEEDED`/`ERR_LABOR_BUDGET_EXCEEDED`/`ERR_OBSERVATION_ZONE_MISMATCH`/`ERR_WEEK_STILL_OPEN` (409) and `ERR_SEGREGATION_OF_DUTIES` (403).
- Week close sends `CLOSED_SHORT`, not the recipe's undeclared `CLOSED` token (§2.10 rule 5 requires a declared enum member). I removed a try-then-fallback leniency one agent had introduced here so all three files that close a week agree.
- Ship-without-confirmation ships as `QualityInspector` per §3.10, not the recipe's `GrowerManager`.
- A recipe's "above threshold" THRIPS observation at 0.900 is actually below the PRD's 1.000 action threshold; tests use 1.100 to preserve intent.
- Allocation listing filters on `commitment_week_id`, the PRD's field name.

**Orchestrator placement check: PASS.** `test_helpers/` (9 files) and `test_suite/` (19 files, 128 `def test_` functions) both sit at the task root; `find workspace -name test_helpers -o -name test_suite` returns nothing.

## Step 7: Run Tests and Iterate (long-lived subagent) — 2026-09-04T13:05:00.000Z

Clean sweep on the first iteration. Verified carefully, including re-checking my own extraction logic (my first pass read a nonexistent `outcome` key and produced a false "128 union failures"; the real key is `status`).

## Summary

**Iterations run: 1** (one 8-round parallel sweep, no fixes needed).

**Sweep result — all 8 concurrent rounds green:**

| round | total | passed | failed | errors | skipped | duration |
|---|---|---|---|---|---|---|
| 1-8 | 128 | 128 | 0 | 0 | 0 | ~229 s each |

Union of non-passing tests across all 8 rounds: **0**. No flakiness signal — no test failed in any round, so there was nothing to triage through the diagnostic protocol.

**Tests deleted: none.** No test failed, so no STEP 1 coverage / unique-derivability adjudication was triggered.

**Fixes applied to `test_helpers/`: none.**

**Fixes applied to `implementation/`: none.**

### Notes on execution
- The wrapping Bash call returned in seconds with exit 0 because `setsid` forks — the sweep was still running detached. I did **not** relaunch; I polled `results.$i.json` until all 8 existed and parsed cleanly (~5 min), exactly as the anti-relaunch rule requires. Diagnosis came only from the per-round JSON, never `sweep.log` (which is the expected spliced garbage — interleaved `PASSED` fragments from 8 shared fds).
- All 128 tests were actually collected and run: `grep -c "def test_"` over `test_suite/*.py` sums to 128, matching `total` in every round, and `skipped == 0` in all rounds.
- No `@pytest.mark.skip` / `xfail` anywhere in `test_suite/` or `test_helpers/` — the only `skip` hits are the word inside a verbatim PRD §2.3 quote about `offset` in `test_suite/test_41_endpoint_corners.py`.
- No sweep reaping: no server log ends in `Terminated`.
- Cardinal-rule spot checks passed: no `sqlite`/`json.dump`/file-write/`/tmp`/`pickle` persistence anywhere in `workspace/implementation/`, and no stray `test_helpers/` or `test_suite/` under `workspace/`.

### Known PRD defect (unchanged, not a test failure)
The orchestrator's lead about §3.2's `planned_end_date` never surfaced as a failure: the test generator had already dropped those assertions as not uniquely derivable (stated formula yields 2026-11-01, the following example sentence says 2026-10-31). The related `first_harvest_allowed_date == "2026-08-24"` assertion — consistent under both readings — passes in all 8 rounds. The self-contradiction still stands in `workspace/PRD.md` §3.2 and is worth repairing in a PRD finalization pass, but it is a documentation defect, not an implementation or test bug, and nothing in the suite depends on resolving it.

**Orchestrator verification of sweep artifacts (mandated — a clean first sweep is the case where a subagent can claim success without leaving evidence).** Independently confirmed after the subagent exited: `results.{1..8}.json` all present in `workspace/implementation/`, all parseable, each reporting `total=128 passed=128 failed=0 errors=0 skipped=0` with a per-test status histogram of exactly `{'passed': 128}`. The clean sweep is real.

## Step 8: Finalize PRD — SKIPPED — 2026-09-04T13:06:00.000Z

**Skip condition met, per the skill's explicit rule.** Step 7 exited on its first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes — zero iterations beyond the baseline. The skill states that in exactly this case `PRD.md` already determined every behavior the implementation exhibits at the sites Step 7 would have exercised, and Step 8 must not be spawned. No `PRD_FINALIZED.md` is produced; Step 9 therefore starts from `workspace/PRD.md`.

Orchestrator reasoning recorded for the autonomy requirement: this is a rule-driven skip, not a judgement call. `<step_7_diff>` would have been empty, so a Step 8 subagent would have had no in-scope edit to make and its HARD SCOPE constraint ("every PRD edit must trace to a specific fix listed in `<step_7_diff>`") would forbid every possible edit. The residual PRD gaps that do exist — including the known §3.2 `planned_end_date` self-contradiction, which produced no Step 7 failure signal because the test generator dropped the assertion pre-emptively — are precisely what Step 9's full PRD-vs-implementation scan is designed to catch, and Step 9 always runs.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch (3 sequential partitioned subagents) — 2026-09-04T13:30:00.000Z

Step 9 always runs. Because Step 8 was skipped, the source was `workspace/PRD.md`. The implementation is 3516 lines across 22 modules, which is too large for one subagent to scan exhaustively without dropping coverage, so the orchestrator ran the scan as **three sequential passes partitioned by implementation module**, all editing one shared `workspace/PRD_COMPLETED.md`. Pass 1 performed the `cp`; passes 2 and 3 were explicitly forbidden from copying or rewriting the file and edited it in place with surgical `Edit` calls only. Every pass read `PRD_COMPLETED.md` (not `PRD.md`) as its baseline so later passes saw earlier passes' work and did not duplicate cross-cutting §2.x prose.

Partition:
- **Pass 1** — app.py, store.py, money.py, errors.py, envelope.py, authz.py, fields.py, const.py, helpers.py, routes/zones.py, routes/cycles.py, routes/clock.py (envelope/pagination/auth/validation-precedence/timestamps/clock machinery; §3.1 compartments & cultivars, §3.2 planning, §3.3 lifecycle, §3.7 pollination).
- **Pass 2** — routes/climate.py, routes/fertigation.py, routes/ipm.py (§3.4 climate & energy settlement, §3.5 fertigation & drainage, §3.6 IPM).
- **Pass 3** — routes/labor.py, routes/lots.py, routes/commerce.py (§3.8 labor, §3.9 grading & cold chain, §3.10 programs/waterfall/settlement), plus the final integrity check.

### Pass 1 result
`PRD_FINALIZED.md` confirmed absent; `cp PRD.md PRD_COMPLETED.md` done; only `PRD_COMPLETED.md` edited thereafter. 545 -> 545 lines, 23 diff hunks / 25 revised lines. **17 ambiguity-pins, 6 mismatch-revisions.** Highlights: §2.2 `api_request_id` shape and real-time (not logical-clock) `api_request_timestamp`; §2.3 negative-`offset` and out-of-bounds `limit` -> `ERR_VALIDATION` 422 rather than clamping, plus `created_at` tie-breaking by insertion order; §2.4 timestamps from the logical clock and "a re-derivation that changes nothing is not a mutation"; §2.5 **mismatch** — clock-set re-derives *every* derived compartment field, not `ipm_posture` alone; §2.6 stale `§3.5` -> `§3.6` cross-reference; §2.10 #4/#5 type-coercion rules (explicit `null` = absent, `"5"` rejected, integral floats accepted, non-string enum fails at priority 4); §2.10 #32 **mismatch** — zone occupancy is status-only, no date range, `PLANNED` occupies nothing; §3.7 hive-capacity projection semantics and the week-count floor; §4 missing `status` filters on `/zones` and `/crop-cycles`; §5 **mismatch** — `ERR_PRODUCTION_TOO_EARLY` 409 -> 422.

**§3.2 `planned_end_date` contradiction — RESOLVED.** `routes/cycles.py:26-34` (`_project_dates`) computes `transplant_date + timedelta(days=cycle_length_weeks * 7 - 1)`; for the worked example (2026-08-03, 13 weeks) that is 90 days -> **2026-11-01**. So the PRD's *formula* was already correct and matched the implementation; the *worked example*'s `2026-10-31` was the wrong half. Resolution: keep the formula, restate it unambiguously as `transplant_date + (cycle_length_weeks x 7 - 1)` calendar days (transplant day counts as day one), and correct the example to 2026-11-01 with the arithmetic shown inline (`13 x 7 - 1 = 90`). `first_harvest_allowed_date` needed no correction (impl gives 2026-08-24, matching the PRD example); annotated with its arithmetic for symmetry. Also pinned that both dates are computed once at creation and never recomputed, including when a revised `plants_transplanted` re-runs the yield projection at the move to `TRANSPLANTED`.

### Pass 2 result
Edited the existing file in place with 20 `Edit` calls; no `cp`, no `Write`; passes 1's prose untouched except one §2.1 sentence specifically about a pass-2 endpoint. 545 -> 545 lines. **18 ambiguity-pins, 10 mismatch-revisions (28 changes).** Highlights: §2.1 **mismatch** — actor resolution does not apply to a release's return-for-revision / reject / cancel transitions, so `ERR_ACTOR_NOT_RECOGNIZED` cannot arise there; §3.4 lighting-hours test suppressed for a non-positive window so `ERR_INVALID_WINDOW` wins, terminal-state check precedes the once-only actuals guard, zero `chp_generated_kwh` puts the whole gas bill on heat, `settled_energy_cost_usd` not floored at zero; §3.5 **mismatch** — the four mix-time checks run cycle-activity first then posture, recipe tolerance, compartment agreement (PRD's narrative implied zone-mismatch first), the 5% variance band is closed, posture check precedes variance check, `cumulative_drain_volume_liters` re-rounded to 2 dp at each addition, and the EC alarm reads the *incoming* `drain_ec_ms` rather than the re-sorted `last_drain_ec_ms`; §3.6 **mismatch** — `open_pest_alert_count` rises on *every* `release_required` filing regardless of `reentry_clear_at` (PRD conditioned it), it is a running counter floored at 0 rather than a recomputation, the lock cascade fires only on the exact crossing to 2, tolerance bounds round half-up, cancellation is not compared against `requested_by_worker_id` but is subject to segregation of duties, and two claimed `ERR_WORKER_SKILL_MISMATCH` sites are actually priority-3 actor resolution (`ERR_ACTOR_NOT_RECOGNIZED`) — the code is never raised outside labor; §4 missing `status` filters on `/fertigation-batches` and `/bio-control-releases`.

### Pass 3 result
Edited in place with the Edit tool only; passes 1-2's 51 edits intact. 545 -> 545 lines (21,009 words / 148,483 bytes). **22 ambiguity-pins, 14 mismatch-revisions (36 changes).** Highlights: §3.8 **mismatch** — "Seven conditions" -> "Nine conditions, evaluated in exactly the order this paragraph names them" with the full gate order (cycle-active -> ipm lock -> reentry -> zone mismatch -> worker inactive -> skill -> window -> double-booked -> after-termination -> budget), termination gate compares `window_start`'s calendar date so the evening of the termination day is accepted, starting a task mutates the task alone, `cancel_reason` required for both `CANCELLED` and `NO_SHOW`; §3.9 **mismatch** — grading's and regrade's terminal guards cover *both* `REJECTED` and `RELEASED`, regrade overwrites `graded_by_worker_id` with the regrading actor, mass balance quantizes each input to 2 dp before adding, `low_pack_out_acknowledged` is transient and never persisted, the pack-out floor rejection rolls the lot back completely; §3.10 **mismatch** — the program list is returned in waterfall order not creation order, all three closing tokens (`CLOSED`, `CLOSED_SHORT`, `CLOSED_FULFILLED`) collapse to one edge with the server deciding the landing state, closing is legal from `ALLOCATED` as well as `OPEN`/`SHIPPED`, the elapsed-window gate fires only on the `OPEN` branch while the program-ACTIVE gate applies to every close, `at_risk_week_count` is not incremented by shipping or closing, `iso_week` is shape-validated only (so `2026-W99` is accepted), shipping drops surviving `PROVISIONAL` rows and freezes the provisional figures, the segregation scan walks *all* rows including `REVOKED` ones, and the allocation-run response is a bare array with no pagination meta; §4 four missing filters (`task_type`, `harvest_date`, `grade`, `status`/`grade_spec`); §5 **mismatch** — `ERR_TASK_AFTER_TERMINATION` 409 -> 422.

Pass 3 also made three deliberate §2.x edits outside its nominal territory, each a mismatch about its own endpoints that no other pass would have corrected, and flagged them explicitly: §2.3 ordering exceptions (waterfall-ordered program list, bare-array allocation run) plus a stale §3.9 -> §3.10 pointer; §2.10 #34 — an allocation run never raises `ERR_PROGRAM_NOT_ACTIVE` (non-ACTIVE programs are silently skipped), so #34 is reachable only from week ship/close; §2.10 #41 restated as "available pounds must not be negative" to match the concrete test. Orchestrator accepts these — they are in-scope mismatches discovered while scanning pass 3's modules, and leaving them would have defeated the step's purpose.

### Step 9 totals and orchestrator verification
**57 ambiguity-pins + 30 mismatch-revisions = 87 changes** across the three passes.

Independently verified after the last pass exited:
- `cmp -s PRD.md PRD_COMPLETED.md` -> **files differ** (the byte-identical failure mode, which would mean the scan never actually ran, did not occur). `diff` reports **152 changed lines**; size grew 119,964 -> 148,483 bytes (+28,519), line count unchanged at 545 because every edit is an in-paragraph insert/revision and no new sections were added.
- Structure intact: all five top-level sections (`## 1.` L3, `## 2.` L11, `## 3.` L201, `## 4.` L401, `## 5.` L465) and all ten `### 3.x` subsections present; the file ends at a real boundary — the last row of the §5 error table — not mid-sentence.
- `implementation/` was **not** modified by any Step 9 pass: every module's mtime is 12:21-12:44, all earlier than the ~13:00-13:05 verified 8-round sweep. `test_helpers/` and `test_suite/` likewise unchanged (12:48). The 8/8-round, 128/128-passing result therefore still describes the artifacts on disk; no re-sweep was required.

**Pipeline complete.** `workspace/PRD_COMPLETED.md` is written; Steps 1-7 and 9 executed, Step 8 skipped under the skill's explicit skip condition.

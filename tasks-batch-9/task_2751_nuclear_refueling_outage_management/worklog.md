# Worklog — task_2751_nuclear_refueling_outage_management

## Step 1: Create task directory — 2026-09-04T16:08:40.636Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2751_nuclear_refueling_outage_management` and its `workspace/` subdirectory. Index 2751 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed and no other task directory was created (other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-04T17:48:30.000Z

All three scaffold artifacts for task 2751 are complete and the lint is clean.

## Files

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2751_nuclear_refueling_outage_management/SCAFFOLD.yaml` | 2855 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2751_nuclear_refueling_outage_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1328 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2751_nuclear_refueling_outage_management/SCAFFOLD_CORNER_DESIGN.yaml` | 4239 |

## SCAFFOLD.yaml (§1.0–§1.7)
- Top-level keys: `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither design key present.
- 13 entities, 10 state machines (47 transitions), 2 concurrency rules, 16 calculations, 23 ordered validations, 56 endpoints, 47 error codes, 9 roles.
- `complexity_profile`: compliance_audit / quota_allocation, layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers`, graph topology, compound state-machine shape, segregation_of_duties role model, immediate consistency.

## Design indices
- `scaffold_difficulty_design`: 9 rules × 2 = **18 instances**.
- `scaffold_corner_design`: **99 instances** (73 full recipes + 26 `excluded_because` stubs) across all nine required sections — entities 13, state_machines 18, calculations 14, validations 10, endpoints 7, errors 20, rbac 6, cross_cutting_complexity_layers 9, consistency_model 2. Every stub cites a difficulty instance that exists by name, and all 47 declared error codes are reachable from §1.8/§1.9.

## Lint
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.8 instances scanned: 18   §1.9 instances scanned: 73   Calls scanned: 961
```
Fixes made to reach it: required `deferral_reason` / `release_reason` bodies added to 9 defer/release calls; three literal `expected_outage_version` values in the pattern-supersession recipe and one literal `expected_spent_fuel_pool_version` replaced with captured `${var}`s (adding intermediate `GET /outages/{id}` reads); and the review-index captures corrected to the declared field names `outage_performance_index` / `adjusted_performance_index`.

Also verified: the difficulty directive never appears in any YAML value (the `scenario` key holds only the domain text), and no banned concurrency vocabulary remains — I reworded the one incidental "simultaneous" in a RadArea field description and one in a corner `distinguishing_aspect`.

**Orchestrator verification:** all three files present (2855 / 1328 / 4239 lines); `grep -i "harder than expert\|expert level" SCAFFOLD*.yaml` → no match, so the difficulty directive did not leak via the scaffold.

## Step 3: Copy shared files — 2026-09-04T17:49:31.690Z

Copied `./INSTRUCTION.md` to `tasks/task_2751_nuclear_refueling_outage_management/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T18:05:00.000Z

PRD generated and all three hard contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2751_nuclear_refueling_outage_management/workspace/PRD.md` — **441 lines**, ends cleanly at the last `§5` error row.

**Sections**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 Station Personnel and RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Station Logical Clock · 2.5 Decimal Discipline for Dose, Hours, Money and Scores · 2.6 Nested Path Resolution and Referential Integrity · 2.7 Optimistic Concurrency on Shared Plant Aggregates · 2.8 Order of Rejection · 2.9 Derived Postures, Cascades and Version Semantics · 2.10 Segregation of Duties
- §3 Business Logic — 3.1 Standing Plant Configuration · 3.2 Opening an Outage and Scoring the Scope Baseline · 3.3 Fuel Reload Design and Spent Fuel Pool Capacity · 3.4 Schedule Development, Critical Path and Safety Function Protection · 3.5 The Supplemental Workforce Pipeline · 3.6 Freezing Scope, Opening the Breaker and Authorizing Startup · 3.7 Radiological Work Permits, the Dose Ledger and ALARA Posture · 3.8 Emergent Work: Discovery and Disposition · 3.9 Startup Testing, Reactivity Management and the Post-Outage Review
- §4 Endpoint Definitions (4-column table) · §5 Error Code Catalogue (2-column table)

**Coverage vs. scaffold**
- Entities: 13/13; entity field names 120/120 present in backticks
- Endpoint inputs / query params / OCC fields: 79/79 (including `disposition`, `outcome`, `modules_completed`, `to_iso8601`, `expected_outage_version`, `expected_spent_fuel_pool_version`, `limit`, `offset`)
- Endpoints in §4: 56/56 (paths byte-matched against scaffold)
- Errors in §5: 47/47, and all 47 error IDs are also triggered by name in §2/§3 prose
- Roles: 9/9 named, each with description and its `opaque` identity translated
- Enum + state values: 79/79 exact strings present
- State machines: 10 machines / 47 transitions; calculations 16/16; validations 23/23 with the full priority ladder rendered as an ordered list in §2.8; concurrency rules 2/2

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 120 required, 120 present, 0 missing
- endpoints[].request_body/input: 79 required, 79 present, 0 missing
- endpoints[].query_params (limit/offset/filters): included in the 79 above, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 23 checked, 23 expressed in prose (§2.8 ordered ladder), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_outage_version /
  expected_spent_fuel_pool_version + ERR_OUTAGE_VERSION_STALE / ERR_POOL_VERSION_STALE + 412), 0 missing
- state_machines[].transitions: 47 checked, 47 fully expressed, 0 missing
- calculations[]: 16 checked, 16 fully expressed (pinned rounding orders, tier-from-base, unrounded ALARA
  ratio, per-hop path rounding, one-sided index penalty, both variant pairs), 0 missing
- validations[] conditions: 23 checked, 23 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 56 endpoints checked, all side-effect and applies_to sets expressed, 0 missing
- entities[].fields[] structured content: 120 checked, defaults/initials/sources reconstructible, 0 missing
- sibling-branch symmetry: 9 groups checked (worker CLEAR vs ADVERSE; dispose APPROVED/REJECTED/ABSORBED;
  RWP void from DRAFT/HELD_FOR_ALARA/APPROVED; close underrun/overrun/exact; defer from PLANNED vs APPROVED;
  return-to-planning from APPROVED vs DEFERRED; consume vs release; pool admission FULL_CORE_PROTECTED vs
  NOMINAL; gross vs emergent-adjusted index), 9 with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1041
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Two scaffold ambiguities I resolved deliberately, worth flagging: `shielding_factor`'s bound is stated as **0 through 0.95 inclusive** (the §1.1 field constraint) rather than `[0,1)` (as loosely paraphrased in the priority-4 validation text); and `scope_freeze_at` is documented as a recorded, non-enforcing field since no scaffold validation gates on it — the enforceable discretionary-scope gate is `ERR_SCOPE_FROZEN` via `schedule_posture`. I did not open either `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`, nor any sibling task directory.

**Orchestrator truncation check (mandated by the launch prompt):** `tail -30 workspace/PRD.md` ends on the final `| \`ERR_DOSE_BUDGET_EXCEEDED\` | 409 |` table row — a real section boundary (end of the §5 catalogue), not mid-sentence. Section headings present: §1–§5, all rendered. `grep -i "harder than expert|expert level"` over PRD.md → no match (the one `SCAFFOLD` hit is the `SCAFFOLD_BUILDER` craft enum value, not a leak). PRD accepted; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T19:16:32.000Z

Step 5 is complete. `test_helpers/` and `test_suite/` are both at the task root of `/home/ubuntu/github/CodingPRD/tasks/task_2751_nuclear_refueling_outage_management/`; nothing was written into `workspace/` and `worklog.md` was not touched.

**Stage 1 — `test_helpers/` (2,439 lines)**
- `/home/ubuntu/.../test_helpers/__init__.py` — 49
- `/home/ubuntu/.../test_helpers/constants.py` — 96
- `/home/ubuntu/.../test_helpers/types.py` — 453
- `/home/ubuntu/.../test_helpers/api_errors.py` — 117
- `/home/ubuntu/.../test_helpers/test_users.py` — 90
- `/home/ubuntu/.../test_helpers/api_client.py` — 425
- `/home/ubuntu/.../test_helpers/factories.py` — 190
- `/home/ubuntu/.../test_helpers/assertions.py` — 578
- `/home/ubuntu/.../test_helpers/fixtures.py` — 441

**Stage 2 — `test_suite/` (8,066 lines, 116 tests)**
- `conftest.py` — 76
- `test_01_entity_representations.py` — 625, 14 tests
- `test_02_lifecycle_state_machines.py` — 688, 13 tests
- `test_03_calculations_and_rounding.py` — 567, 9 tests
- `test_04_input_validation.py` — 362, 5 tests
- `test_05_endpoint_contracts.py` — 515, 8 tests
- `test_06_error_conditions.py` — 1,408, 16 tests
- `test_07_role_access_control.py` — 937, 6 tests
- `test_08_cross_cutting_layers.py` — 517, 6 tests
- `test_09_consistency_and_concurrency.py` — 257, 2 tests
- `test_10_depth_variants_and_formulas.py` — 456, 8 tests
- `test_11_depth_cycles_and_cascades.py` — 578, 9 tests
- `test_12_depth_precedence_and_boundaries.py` — 583, 12 tests
- `test_13_depth_windows_and_compensation.py` — 481, 8 tests

**Design-index coverage — complete, no skips**
- Queue A (difficulty, §1.8): 18/18 non-stub instances translated, 37 tests, every instance carrying at least 2 tests. 0 skipped, 0 dangling tags, 0 stub instances touched.
- Queue B (corner, §1.9): 73/73 non-stub instances translated, 79 tests — entities 13/13, state_machines 12/12, calculations 8/8, validations 5/5, endpoints 7/7, errors 15/15, rbac 6/6, cross_cutting_complexity_layers 5/5, consistency_model 2/2. 0 skipped, 0 dangling tags, none of the 26 `excluded_because:` stubs translated.
- Every one of the 116 tests carries exactly one trailing `Design:` line (116 tests, 116 tags), and no test was generated from SCAFFOLD.yaml directly.
- No instance failed the PRD-first two-condition filter, so there is nothing on the skip list.

**Verification** — `python3 -m py_compile` succeeds on all 23 generated `.py` files, and `python3 -m pyflakes test_suite/*.py` is now silent (exit 0) after pruning 16 unused imports left over from earlier chunked appends; the only remaining pyflakes output anywhere is the intentional re-export noise in `test_helpers/__init__.py`. The one occurrence of the string `SCAFFOLD` in the tree is `Craft.SCAFFOLD_BUILDER` in `types.py`, which is a verbatim PRD enum value, not a scaffold reference; no comment or docstring mentions the design documents.

**Orchestrator verification:** `test_helpers/` and `test_suite/` are both at the task root (not under `workspace/`); `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/`; exactly one `worklog.md` exists, at the task root. Independent count of `def test_` across `test_suite/*.py` = 116, matching the reported figure.

## Step 6: Generate implementation — 2026-09-04T18:47:00.000Z

The implementation is complete.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2751_nuclear_refueling_outage_management/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` (exec, chmod +x) | 10 | guarded `pip install`, `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask>=2.2.0` |
| `app.py` | 72 | blueprint registration, `ApiError`/HTTP/catch-all handlers, `0.0.0.0:$PORT` (default 10000) |
| `errors.py` | 81 | all 47 error IDs → HTTP codes, `ApiError` |
| `clock.py` | 59 | station logical clock (default `2026-08-01T00:00:00Z`, never falls back to wall clock) |
| `db.py` | 77 | 13 **empty** dicts + seq, `create_row`/`touch`/`sorted_rows` |
| `response.py` | 104 | `meta`/`response_type`/`data` envelope, `req_`+20 alnum id, real-clock 3-digit timestamp, offset/limit pagination |
| `auth.py` | 60 | `X-User-ID`/`X-User-Role`, 9 roles, `authorize()` |
| `validators.py` | 141 | typed field specs, unknown-field rejection, bounds |
| `calc.py` | 191 | every calculation rule, `Decimal`+`ROUND_HALF_UP` |
| `serializers.py` | 11 | representation projection |
| `lookup.py` | 58 | per-entity 404 resolvers |
| `projections.py` | 433 | critical path, postures, dose ledger replay, cost roll-up, pool ledger, cascades, row minting |
| `routes_config.py` / `routes_outage.py` / `routes_workorder.py` / `routes_schedule.py` / `routes_fuel.py` / `routes_workforce.py` / `routes_rwp.py` / `routes_emergent.py` / `routes_startup.py` | 132 / 210 / 173 / 231 / 212 / 132 / 205 / 170 / 121 | endpoint layer |

Total 2884 lines.

## Verification

- **Endpoints: 56 implemented vs 56 declared** (35 POST + 21 GET). I diffed the live Flask `url_map` against the PRD §4 table programmatically: `missing: []`, `extra: []` — exact match, including `POST /_clock/set_current_utc`.
- **Compile:** `python3 -m py_compile *.py` → all 20 modules parse (`ALL_PY_COMPILE_OK`). `__pycache__` removed afterwards.
- **No seeding / no persistence:** all 13 collections are empty dicts at import; no SQLite, no file or `/tmp` state; the only `seed`/`preload` occurrences in the tree are comments stating that nothing is seeded.

## Smoke test (`PORT=18751 bash start.sh &`, pid 1053876)

- Envelope confirmed on success (`meta.api_request_id` = `req_5T0S2NJLTA3WDQYDBIGA`, 3-digit-fraction timestamp, `response_type` `object`/`array`, list responses carrying `limit`/`offset`/`total_count`/`has_more`) and on error (`data.error_id` = `ERR_OUTAGE_NOT_FOUND` @404; missing headers → 401; unknown body field → `ERR_INVALID_REQUEST`).
- Ran a full lifecycle with no 5xx anywhere: safety function → rad area → outage → work order plan/approve-scope → activity → core-load pattern submit (OCC) + approve (SoD by a second user) → lock-scope → commence-execution → RWP draft/approve (COMMIT ledger row) → emergent report + `APPROVED` 8-step cascade (minted `EMERGENT:` work order and activity) → RWP close (underrun RELEASE) → activity start/complete → startup test declare → authorize-startup → satisfy (REGULATORY, NRC ref, other user) → bubble to ONLINE → post-outage-review.
- Every computed figure matched hand calculation: `priority_score` 91.00/CRITICAL and 75/CRITICAL for the emergent WO, RWP doses 70/420/84/504 with `alara_review_required` true, path 290.00 and risk-adjusted 362.50, cost base 1,200,000 → 8% → 1,296,000, ledger 144 COMMIT then 44 RELEASE → `dose_committed_mrem` 100.00, variances 16.67 / 1.67 / −99.75 / 8.33, and indices 90.00 vs 97.50.
- **Kill method:** resolved the port owner with `ss -ltnpH 'sport = :18751'` → pid 1053876, then `kill 1053876` (single PID). No pattern kill was used at any point; port verified closed afterwards (connection refused).

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator could not see `test_suite/` (it did not exist at its spawn time) — physical isolation preserved.

## Step 7: Run tests and iterate — 2026-09-04T19:38:08.000Z

All 8 parallel rounds are green (116/116 each, 0 failures, 0 errors).

## Summary

**Iterations run:** 2 (each a full 8-round parallel sweep, `--isolation per-test-server`, 116 tests/round).

Iteration 1: 113/116 in all 8 rounds — the same 3 tests failed in every round (deterministic, not flakiness). Iteration 2: 116/116 in all 8 rounds.

**Tests deleted:** none. All three failures survived STEP 1 (PRD verbatim-covers the rule and uniquely determines it), so all three were STEP 2 test bugs.

**Fixes applied to `test_helpers/`:** none — the fixture layer was already PRD-faithful; all three defects lived in `test_suite/`.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2751_nuclear_refueling_outage_management/test_suite/test_04_input_validation.py` — `TestShutdownMarginFloor::test_a_subcritical_margin_below_the_floor_persists_nothing`: the closing witness called `lock-scope` on an outage with *no* approved work order and asserted `ERR_CORE_LOAD_PATTERN_NOT_APPROVED`. PRD §3.6 states the two scope-lock preconditions in order — approved work order first (`ERR_WORK_ORDER_STATE_INVALID`), approved pattern second — so the implementation's `ERR_WORK_ORDER_STATE_INVALID` was correct. Added a `given_approved_work_order(outage["id"])` to satisfy the first precondition; the exact `error_id` assertion is unchanged.
- `.../test_suite/test_07_role_access_control.py` — `TestSharedOperationsAcceptEveryDeclaredRole::test_four_endpoints_are_exercised_by_both_of_their_listed_roles`: asserted `BADGE_READY` after the second `training-completion`, but never recorded a background result, so PRD §3.5's join (`background_status` CLEAR **and** `training_status` COMPLETE) could not fire and `SCREENING` was correct. Added the `AccessAuthority` background-`CLEAR` call between the two training submissions so the second training call genuinely trips the join; the `BADGE_READY` assertion is preserved.
- `.../test_suite/test_11_depth_cycles_and_cascades.py` — `TestEmergentApprovalCascade::test_minted_work_order_and_activity_follow_the_discovering_work_order`: asserted the minted activity's `planned_start_offset_hours == 650` (the predecessor's *finish*). PRD §3.8 step 3, quoted in the test's own docstring, says it is "that predecessor's `planned_start_offset_hours` plus the new activity's own `planned_duration_hours`" → 500 + 90 = **590**. Corrected the expected value to 590; the sibling assertions in the same class (projection 740→500, risk-adjusted 595, priority 49.00/HIGH) independently confirm the implementation's walk.

**Fixes applied to `implementation/`:** none. No implementation defect was found; all three failures were assertion/setup mis-translations of PRD prose.

Per-round artifacts are at `.../workspace/implementation/results.1.json` … `results.8.json`. `worklog.md` was not touched.

**Orchestrator verification (independent of the subagent's claim):** the orchestrator itself parsed all 8 `results.$i.json` files — every one reports `passed == total == 116`, so the sweep artifacts really exist and really are green (not an unbacked claim). `grep -rn "pytest.mark.skip\|pytest.mark.xfail" test_suite/ test_helpers/` → no match, so no test was neutered to reach green. Independent `def test_` count is still 116, matching Step 5's total: consistent with the reported zero deletions. No SQLite / on-disk persistence in `implementation/` (the single `json.dumps` hit is HTTP response serialization in `response.py`).

**Step 8 skip adjudication (orchestrator decision, made autonomously per the AUTONOMY directive):** Step 7 applied 0 `implementation/` fixes and 0 deletions, but 3 `test_suite/` fixes. The skill's pipeline diagram parenthetical ("skipped if Step 7 had 0 implementation/ fixes") and the detailed Step 8 skip condition ("0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes — i.e. zero iterations beyond the baseline") disagree on this case. Taking the more specific, explicitly enumerated condition as authoritative: it is not met (3 `test_suite/` fixes, 2 iterations), so **Step 8 runs**. It may legitimately produce a byte-identical `PRD_FINALIZED.md` — all three Step 7 items were test-side mis-translations of PRD prose that the PRD already pinned uniquely, so there may be nothing for Step 8 to patch. Step 9 runs unconditionally regardless.

## Step 8: Finalize PRD — 2026-09-04T19:47:18.000Z

PRD_FINALIZED.md is written with exactly one edit.

## Line counts
- PRD.md: 441 lines; PRD_FINALIZED.md: 441 lines. 1 of 441 lines changed → **0.23% delta** (no lines added or removed; §4/§5 tables and all other sections byte-identical).

## Changes
- **§3.6 (Freezing Scope) — revise** — the two scope-lock cross-entity preconditions are now declared as an *ordered* pair: the approved-work-order test first (`ERR_WORK_ORDER_STATE_INVALID`), the approved-pattern test second (`ERR_CORE_LOAD_PATTERN_NOT_APPROVED`), with the both-fail case explicitly reporting the work-order code — `implementation/routes_outage.py:94-100`.

## Per-edit pre-edit search log
Edit 1 — §3.6 scope-lock precondition order
- (a) **Subject:** which error a `POST /outages/{id}/lock-scope` returns when the outage owns neither an `APPROVED` work order nor an `APPROVED` core loading pattern, i.e. the relative rank of `ERR_WORK_ORDER_STATE_INVALID` and `ERR_CORE_LOAD_PATTERN_NOT_APPROVED`.
- (b) **Impl paths enumerated:** `routes_outage.py:85-116` (`lock_scope`: outage-status → work-order-APPROVED existence → pattern-APPROVED existence → cascade — the Step 7 site); grepped all three error ids repo-wide and read every other callsite so the wording could not bleed into them — `routes_fuel.py:127-134` (`ERR_CORE_LOAD_PATTERN_NOT_APPROVED` on a `DISCHARGE` reservation, ranked *before* `ERR_POOL_VERSION_STALE`/`ERR_POOL_CAPACITY_EXCEEDED`), `routes_workorder.py:75,95,121,153` (`ERR_WORK_ORDER_STATE_INVALID` as the plain own-state code on `plan`/`approve-scope`/`return-to-planning`/`defer`), `routes_rwp.py:112` and `routes_schedule.py:190` (the distinct `ERR_WORK_ORDER_NOT_APPROVED` guard), `errors.py:25,34,35` (status mapping unchanged), `projections.work_orders_of_outage` / `patterns_of_outage` (existence selectors, no status side-conditions).
- (c) **Wording adjustment:** scoped the ordering claim with "at this gate … in the order stated here" rather than any global rank statement, so it constrains only scope lock and leaves the reservation-side `ERR_CORE_LOAD_PATTERN_NOT_APPROVED` ordering and the work-order own-state uses of `ERR_WORK_ORDER_STATE_INVALID` untouched; §2.8's rank list was deliberately not edited.

## Sites verified against implementation but left verbatim (no edit)
- **§3.5 workforce join** — `routes_workforce.py:62-68` requires `status == SCREENING` **and** `background_status == CLEAR` **and** `training_status == COMPLETE`, evaluated at the end of both `background-result` and `training-completion`; PRD §3.5 states exactly this. Pure test-setup bug. (Checked the incidental double `touch` — branch write +1, join +1 — which is consistent with §2.4's per-mutation rule plus §3.5's per-hop rule, so no pin needed.)
- **§3.8 step 3 offset** — `routes_emergent.py:78-89` computes `predecessor["planned_start_offset_hours"] + duration` (null predecessor → offset 0), which is the PRD formula verbatim; the 650 expectation was a test-side mis-read. Also checked `projections.terminal_activity` (non-`CANCELLED`, latest finish, `created_at` tie-break) and `mint_activity` (oos fields null, `constraint_status` via the shared §3.4 predicate) — all already covered by existing prose.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` yields exactly one changed line (2 diff lines, one `<` and one `>`), both files 441 lines — genuinely minimal, and the edit is scoped to the scope-lock gate ("at this gate they are evaluated in the order stated here") rather than making a global error-rank claim, so it should not create a new mismatch for Step 9 to undo.

## Step 9 plan (orchestrator decision, autonomous)

Step 9 must scan the whole implementation (20 modules, 2884 lines) against a 441-line PRD. A single subagent doing that in one pass risks a shallow scan or a context blow-out, so Step 9 is run as **three sequential passes partitioned by implementation module**, each editing the same shared `workspace/PRD_COMPLETED.md`:
- Pass 1 (does the `cp PRD_FINALIZED.md PRD_COMPLETED.md`): infrastructure + config + outage + work order — `app.py`, `errors.py`, `clock.py`, `db.py`, `response.py`, `auth.py`, `validators.py`, `serializers.py`, `lookup.py`, `routes_config.py`, `routes_outage.py`, `routes_workorder.py`.
- Pass 2 (must NOT re-copy): computation core + schedule + fuel — `calc.py`, `projections.py`, `routes_schedule.py`, `routes_fuel.py`.
- Pass 3 (must NOT re-copy): workforce + radiological + emergent + startup — `routes_workforce.py`, `routes_rwp.py`, `routes_emergent.py`, `routes_startup.py`.
Passes run strictly sequentially so they cannot clobber each other's edits to the shared file.

## Step 9: Complete PRD — 2026-09-04T20:12:09.000Z

Run as three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`, plus one follow-up edit to close a residual item. Pass 1 performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 and the follow-up edited in place and ran no `cp`.

### Pass 1 — infrastructure + config + outage + work order
Modules scanned: `app.py`, `errors.py`, `clock.py`, `db.py`, `response.py`, `auth.py`, `validators.py`, `serializers.py`, `lookup.py`, `routes_config.py`, `routes_outage.py`, `routes_workorder.py`.
441 lines / 97,890 chars → 441 lines / 102,758 chars (+4,868). **14 ambiguity-pins, 0 mismatch-revisions** (the §4 table's paths/methods/roles for all 20 endpoints in these modules match the code exactly, and §5's 47 code→status pairs are byte-for-byte the `ERROR_HTTP` map in `errors.py`).
- §2.1 — insert — ambiguity — empty/whitespace-only `X-User-ID`/`X-User-Role` counts as absent; role match is exact and case-sensitive — `auth.py:34-39`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alphanumeric characters — `response.py:12-16`
- §2.2 — insert — ambiguity — `api_request_timestamp` is the one timestamp read from real wall-clock time, not the logical clock (resolves the near-conflict with §2.4's "never fall back to real wall-clock time", which governs stamped row fields) — `response.py:29-33`
- §2.3 — insert — ambiguity — a `limit`/`offset` that is not an integer literal (fractional, non-numeric, or present-but-empty) is `ERR_INVALID_REQUEST` — `response.py:78-91`
- §2.3 — insert — ambiguity — filters are exact string equality, conjunctive; a filter naming a nonexistent id or an off-enum value yields an empty page, never 404/400; undeclared query parameters are ignored (unknown-field rule is body-only) — `routes_workorder.py:57-63`
- §2.4 — insert — ambiguity — clock response `data` carries `current_utc` alone; `to_iso8601` accepts any parseable ISO form/offset/fraction width and is normalised to UTC; setting the clock is an assignment, so an earlier instant is accepted — `routes_config.py:25-30`, `clock.py:42-55`
- §2.5 — insert — ambiguity — Decimal quantities serialise as bare JSON numbers, not quoted strings — `response.py:19-26`
- §2.8 rank 4 — insert — ambiguity — no type coercion; absent/empty body reads as `{}` and a no-field endpoint rejects any field as unknown; non-object/unparseable body is `ERR_INVALID_REQUEST`; explicit `null` admitted only for the nine declared-nullable fields; cross-field bounds (`cells_baseline_occupied` ≤ `cells_total`, `min_trains_required` ≤ `trains_total`) and duplicate `area_code`/`function_code`/`designation` also land at this rank as `ERR_INVALID_REQUEST`, unlike the rank-18/19 uniqueness codes — `validators.py:71-141`, `routes_config.py:45,112-117`, `routes_outage.py:34-37`
- §2.9 — insert — ambiguity — sibling rows sharing an identical `created_at` fall back to insertion order; identifiers still never compared — `db.py:62-69`
- §3.2 — revise — ambiguity — `scope_freeze_at` is mandatory, accepted in any parseable ISO 8601 form, stored converted to UTC with three fractional digits — `routes_outage.py:30,45`
- §3.2 — insert — ambiguity — work-order creation has no outage-status gate and leaves the outage row untouched — `routes_workorder.py:20-45`
- §3.2 — insert — ambiguity — `SCOPED → PLANNED` bumps only the work order's `version` — `routes_workorder.py:81-83`
- §3.2 — insert — ambiguity — `return_reason` is 1–500 chars; the `APPROVED → PLANNED` reopen has no outage-status gate; `DEFERRED → PLANNED` revives no cancelled activity or voided permit and reprojects nothing — `routes_workorder.py:115-141`
- §3.2 — insert — ambiguity — `deferral_reason` is 1–500 characters — `routes_workorder.py:151`

### Pass 2 — computation core + schedule + fuel
Modules scanned: `calc.py`, `projections.py`, `routes_schedule.py`, `routes_fuel.py`.
441 lines / 103,103 chars → 441 lines / 106,829 chars. **12 ambiguity-pins, 1 mismatch-revision.**
- §3.4 — insert — ambiguity — `oos_train_label`'s absence when `oos_safety_function_id` is supplied is `ERR_INVALID_REQUEST` at rank 4; the converse pairing is not policed; the three body FKs resolve `oos_safety_function_id` → `work_order_id` → `predecessor_activity_id` — `routes_schedule.py:73-84`
- §3.4 — insert — ambiguity — activity creation has no outage-status gate and reprojects critical path and posture without bumping the outage's `version`/`updated_at` — `routes_schedule.py:102-113`
- §3.4 — insert — ambiguity — the `is_critical_path` ancestor walk runs only through the input set, halting at a `CANCELLED` predecessor — `projections.py:216-222`
- §3.4 — insert — ambiguity — re-sequencing's `predecessor_activity_id` is mandatory-but-nullable; activity must be `NOT_STARTED`; no outage-status gate and no capacity re-check — `routes_schedule.py:143-154`
- §3.4 — insert — ambiguity — starting an activity bumps only the activity's and (if moved) the work order's `version` — `routes_schedule.py:193-199`
- §3.4 — insert — ambiguity — completion has no outage-status gate; the successor-clear hop reaches successors whatever their `execution_status` but touches only those actually moving `BLOCKED → CLEAR` — `routes_schedule.py:207-222`
- §3.3 — insert — ambiguity — pattern submission has no outage-status gate; the `PLANNING` restriction bites only at approval — `routes_fuel.py:25-40`
- §3.3 — insert — ambiguity — the reactivity margin is computed from `cycle_length_mwd_mtu` as submitted, while the stored figure is rounded to 2dp — `routes_fuel.py:36,44`
- §3.3 — **revise — mismatch** — pattern approval evaluates the 1000-pcm margin re-check *before* the segregation-of-duties test (PRD had listed SoD first, contradicting §2.8 ranks 9 vs 20) — `routes_fuel.py:92-97`
- §3.3 — insert — ambiguity — reservation body FKs resolve `spent_fuel_pool_id` first, so a request naming neither reports `ERR_SPENT_FUEL_POOL_NOT_FOUND` — `routes_fuel.py:125-126`
- §3.3 — insert — ambiguity — the `DISCHARGE` approved-pattern guard precedes both the pool OCC check and the headroom comparison; reservation creation has no outage-status gate — `routes_fuel.py:128-144`
- §3.3 — insert — ambiguity — reservation creation, consumption and release never touch the consuming outage's row or `version` — `routes_fuel.py:146-157`
- §3.3 — insert — ambiguity — release takes a mandatory `release_reason` of 1–500 characters and has no outage-status gate — `routes_fuel.py:202-212`

`calc.py` needed no changes: every formula, rounding order, cap/floor and tier/threshold boundary (priority bands 75/45 inclusive, tier `< 5,000,000` / `< 20,000,000`, `q2(target × 1.10)` inclusive AT_RISK ceiling, unrounded ALARA ratio, one-sided weighted penalty rounded once at the end and floored at zero) was already pinned uniquely.

### Pass 3 — workforce + radiological + emergent + startup
Modules scanned: `routes_workforce.py`, `routes_rwp.py`, `routes_emergent.py`, `routes_startup.py`.
441 lines / 106,829 chars → 441 lines / 110,364 chars (+3,535). **10 ambiguity-pins, 2 mismatch-revisions.**
- §3.5 — insert — ambiguity — worker creation carries no outage-status gate and leaves the outage row untouched — `routes_workforce.py:22-40`
- §3.5 — insert — ambiguity — `modules_completed` is an integer ≥ 0 with no upper bound; an over-requirement count is stored as submitted — `routes_workforce.py:96`
- §3.5 — **revise — mismatch** — PRD claimed the join increments the worker's `version` by 1; the branch write and the join are two separate `touch` calls, so a join-tripping request bumps it by **2** (one instant, so `updated_at` is unchanged between them) — `routes_workforce.py:83-84, 108-109`
- §3.7 — insert — ambiguity — permit drafting tests neither the work order's nor the outage's status, and leaves the outage row untouched — `routes_rwp.py:20-53`
- §3.7 — insert — ambiguity — `void_reason` is 1–500 characters; voiding imposes no outage-status gate; voiding from `DRAFT`/`HELD_FOR_ALARA` leaves the outage row untouched with no hold cascade — `routes_rwp.py:171-193`
- §3.8 — insert — ambiguity — emergent reporting tests neither the work order's nor the outage's status; outage `version` stands still — `routes_emergent.py:21-41`
- §3.8 — insert — ambiguity — `disposition_note` defaults to null, is nullable, and has no length bound; the item row is mutated exactly once on every branch, so its `version` increments by exactly 1 even across the 8-step `APPROVED` cascade — `routes_emergent.py:150, 64-74, 132-134, 167-169`
- §3.8 — insert — ambiguity — the minted emergent activity's `execution_status` is `NOT_STARTED` and its `constraint_status` follows the §3.4 creation predicate — `routes_emergent.py:86-89` via `projections.py:426-427`
- §3.8 — revise — ambiguity — the `ABSORBED` branch bumps the absorbed activity's own `version` by 1 — `routes_emergent.py:138`
- §3.9 — insert — ambiguity — `predicted_reactivity_pcm` is unbounded; startup-test declaration carries no outage-status gate and leaves the outage untouched — `routes_startup.py:28, 22-33`
- §3.9 — **revise — mismatch** — PRD listed the five satisfy guards with sequencing *before* the regulatory release reference; impl (and §2.8 ranks 12 < 17 < 20) checks `ERR_REGULATORY_HOLD_POINT_NOT_RELEASED` **before** `ERR_STARTUP_SEQUENCE_OUT_OF_ORDER`, with SoD last — `routes_startup.py:86-99`
- §3.9 — revise — ambiguity — on the `FAILED` branch a supplied `nrc_release_reference` is not recorded; `measured_reactivity_pcm` is likewise unbounded — `routes_startup.py:103-118`

### Follow-up edit — residual §2.9 item (orchestrator-initiated)
Pass 3 flagged one gap it deliberately left alone as belonging to pass 2's partition: §2.9's universal "each affected row's own `version` increases by 1" versus `projections._assign_lengths`, which rewrites derived fields without bumping activity versions. Since Step 9's mandate is zero residual mismatch and no later pass owned it, the orchestrator resumed the pass-2 agent (preserving its context) to close it rather than leaving a known gap. It confirmed pass 3 read the code correctly and made **1 mismatch-revision**:
- §2.9 — revise — mismatch — "mutates several rows" narrowed to "moves the stored state of several rows", plus an appended clause pinning that reprojecting a derived field is not itself such a mutation: a reprojection rewrites per-activity `path_length_hours`, `risk_adjusted_path_length_hours` and `is_critical_path` in place without bumping the activity's `version` or `updated_at`, and a cascade step that leaves a sibling's stored state as it found it leaves that sibling's `version` alone — `projections.py:160-162, 168, 219`
Enumeration backing the wording: no projection helper bumps a version on its own; `_assign_lengths` and `recompute_critical_path` never touch versions on any caller path; `recompute_pool` / `recompute_badged_count` / `recompute_emergent_hours` / `recompute_scope_cost` / `recompute_schedule_posture` / `recompute_dose_ledger` / `recompute_alara_posture` leave the bump to the route, which applies it only where §3 declares it (and pointedly not on activity creation or `DEFERRED → PLANNED` reinstatement); all 69 `touch`/`touch_row` call sites accompany a status or stored-input change, never a reprojection. The clause also reconciles §2.9 with the already-`CLEAR` successor behaviour pinned in §3.4 during pass 2.

### Step 9 totals
- Source `PRD_FINALIZED.md` (441 lines / 97,890 chars) → `PRD_COMPLETED.md` (441 lines / 110,891 chars), **+13,001 chars**, 38 changed regions, zero lines added or removed and no new sections — every edit is an in-paragraph insert or revision.
- **36 ambiguity-pins, 4 mismatch-revisions** across the four edit rounds.

**Orchestrator final verification:** `PRD_COMPLETED.md` is 441 lines and md5 `23d29969…`, distinct from both `PRD_FINALIZED.md` (`24cadc86…`) and `PRD.md` (`6e4a006d…`) — so the Step 9 scan demonstrably ran and did not leave a byte-identical file. `diff PRD_FINALIZED.md PRD_COMPLETED.md` reports 38 changed regions. Structure intact: 5 top-level `##` sections (§1–§5), §4 table with exactly 56 endpoint rows, §5 table with exactly 47 error rows, tail ending at `| \`ERR_DOSE_BUDGET_EXCEEDED\` | 409 |` — no truncation. All 8 `results.$i.json` from the final green sweep are present in `workspace/implementation/`. No stray worklog and no test directories under `workspace/`.

**Pipeline complete.** Steps 1–9 all executed; final artifact `workspace/PRD_COMPLETED.md` written.

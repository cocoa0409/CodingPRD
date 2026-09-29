# Worklog — task_2387_hardwood_flooring_mill_kiln_drying

## Step 1: Create task directory — 2026-09-02T05:46:37.834Z

Created `tasks/task_2387_hardwood_flooring_mill_kiln_drying/` and `tasks/task_2387_hardwood_flooring_mill_kiln_drying/workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T07:16:23.652Z

Lint is clean. Final state of `/home/ubuntu/github/CodingPRD/tasks/task_2387_hardwood_flooring_mill_kiln_drying/`:

```
Coverage
  §1.5 endpoints declared:    76
  §1.1 entities declared:     15
  §1.8 instances scanned:     20
  §1.9 instances scanned:     71
  Calls scanned (§1.8+§1.9):  1323

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

**`SCAFFOLD.yaml`** (§1.0–§1.7, 118 KB) — `difficulty_band: beyond-expert`, `consistency_model: immediate`, api_prefix `/mill`.
- **15 entities**: SpeciesProfile, KilnSchedule, KilnChamber, KilnCharge, GreenReceipt, ProductLine, CoreStock, FlooringLot, GradeRun, GradeBundle, PrefinishLine, PrefinishRun, ByproductBatch, ByproductSale, WarrantyClaim.
- **8 state machines** + **2 `concurrency_rules`** (OCC on SpeciesProfile and FlooringLot via `version` → 412).
- **20 calculations** (kiln schedule duration across density × thickness-tier × moisture-point axes; green→dry shrink; dual-variant lot yield provisional vs final; six-step pinned warranty liability; grade tally with per-bundle length/grade-credit rounding; byproduct settlement with tiered discount + haul billing; core SF reservation at 1.10 sf/bf).
- **51 ordered validations** (fixed priority ladder 1–51: auth → authz → schema → not-found family in a pinned entity order → OCC 412s → segregation of duties → state gates → domain invariants: mass balance, 12% waste cap, 55.00% yield floor, chamber closed-interval capacity with cooldown buffer, prefinish half-open window capacity, redry cycle cap of 2, 60-month warranty period, 3-open-claim cap, core-stock sufficiency, warranty reserve sufficiency).
- **76 endpoints** (incl. `POST /_clock/set_current_utc`), **51 errors**, **9 roles** (Anonymous, MillAdmin, ProcurementClerk, KilnOperator, MillSupervisor, GradeInspector, PrefinishScheduler, ByproductBroker, WarrantyAdjudicator).
- Complexity layers: cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency, derived_field_reconciliation.

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (§1.8) — 9 rule_id groups, **20 instances**: dual_variant_calc (2), combinatorial_formula (3), non_linear_state_machine (3), transitive_cascade (2), priority_pair_validation_conflict (2), boundary_precision_check (2), cross_entity_state_dependency (2), resource_temporal_overlap (2), compensating_invariant (2).

**`SCAFFOLD_CORNER_DESIGN.yaml`** (§1.9) — all 9 allowed sections, **92 instances** (71 full test recipes + 21 `excluded_because` stubs citing §1.8): entities 13, state_machines 16, calculations 18 (9 stubs), validations 21 (2 stubs), endpoints 3 (1 stub), errors 8 (6 stubs), rbac 5, cross-cutting complexity layers 7 (3 stubs), consistency model 1. Every one of the 51 error codes is either directly asserted or covered by a cited §1.8 instance.

## Key findings worth passing on

Two `scaffold_lint.py` behaviors caused nearly all the churn and are worth knowing for future scaffolds:

1. **§1.5 `input:` must be a flow list of strings**, e.g. `input: [flooring_lot_id, "stain_code?"]`, and the response key is `code:` not `status:`. `_split_input` silently discards non-string entries, so the dict form (`- {name: x, type: y, required: true}`) reads as "no body fields" and every payload key in §1.8/§1.9 is flagged — that produced 734 spurious `(c)` violations in one run. `?`-suffixed names must be quoted or PyYAML rejects the flow sequence.

2. **`lint_fk_reverse_reachability` matches a literal `{id}` segment.** Its sub-resource branch requires `path_template.startswith(f"{prefix}/{parent_seg}/{{id}}/")`, so `GET /mill/grade-runs/{grade_run_id}/bundles` does not satisfy the FK `GradeBundle.grade_run_id -> GradeRun`, and the filtered-list fallback could not fire because GradeBundle had no single-resource GET from which to derive a collection segment. Fixed by adding `GET /mill/grade-bundles/{grade_bundle_id}` (returns `GradeBundle`) plus `GET /mill/grade-bundles` with `input: ["grade_run_id?", "grade_class?", "limit?", "offset?"]`, which is a genuine reachability improvement rather than a lint workaround. Endpoint count went 74 → 76.

Also note `grounds:` flow-list elements that contain `{`, `}`, `[`, or `]` (path templates like `endpoints[GET /mill/flooring-lots/{flooring_lot_id}/yield-summary]`) must be double-quoted or PyYAML fails to parse the file at all.

## Step 3: Copy shared files — 2026-09-02T07:16:48.759Z

Copied `./INSTRUCTION.md` → `tasks/task_2387_hardwood_flooring_mill_kiln_drying/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T07:28:29.881Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2387_hardwood_flooring_mill_kiln_drying/workspace/PRD.md` (457 lines). The two withheld design files were never opened, and no sibling task directory was read.

**Structure** — §1 Introduction (3 paragraphs); §2 with 10 subsections (2.1 Mill Personnel and RBAC, 2.2 API Response Structure emitted verbatim from `section-2.2-response-structure.md`, 2.3 Pagination, 2.4 Resource Identity/Revision Counters/Logical Clock, 2.5 OCC on Species Profiles and Flooring Lots, 2.6 Units/Rounding, 2.7 Request Screening Order, 2.8 The Two Conserved Ledgers, 2.9 Interval Geometry, 2.10 Nested Paths and Reference Resolution); §3 with 9 domain subsections (reference-data configuration → receiving deck → charge scheduling → allocation/loading → drying and stress test → milling/mass balance/byproducts → grading and lot closeout → prefinishing → warranty reserve and adjudication); §4 endpoint table (76 rows, 4 columns); §5 error table (51 rows, 2 columns). File ends at §5 with no audit footer.

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 130 required, 130 present, 0 missing (149 field entries across 15 entities, deduplicated)
- endpoints[].request_body: 84 required, 84 present, 0 missing
- endpoints[].query_params: 23 required, 23 present, 0 missing
- endpoints[].path_params: 15 required, 15 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 51 checked, 51 expressed in prose (§2.7 renders the full 1..51 ordering with error id, status and applies_to scope), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (expected_species_profile_version / POST /mill/drying-schedules / ERR_STALE_SPECIES_PROFILE_VERSION 412; expected_lot_version / POST /mill/grade-runs / ERR_STALE_LOT_VERSION 412; both with parent version bump), 0 missing
- state_machines[].transitions: 43 checked, 43 fully expressed, 0 missing
- calculations[]: 20 checked, 20 fully expressed (incl. both dual-variant pairs, the closed vs half-open interval geometries, per-bundle-then-sum tally rounding, and both conservation invariants), 0 missing
- validations[] conditions: 51 checked, 51 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 33 checked, 33 expressed, 0 missing
- entities[].fields[] structured content: 149 checked, 149 reconstructible from prose (incl. GradeBundle carrying only id/created_at with no updated_at/version), 0 missing
- sibling-branch symmetry: 6 groups checked (stress-test release vs redry, lot finalize GRADED vs QUARANTINED, SOLID vs ENGINEERED core rules, adjudicate APPROVED vs DENIED, freeze from OPEN vs RESTRICTED, unfreeze to OPEN vs RESTRICTED), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 708
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 is byte-identical to the canonical source; every one of the 51 `errors[].error_id`, all 9 `rbac.roles[].name` values, and all 60 enum/state strings appear verbatim; no pseudocode operators, no fuzzy hedging words, and no race/simultaneity framing around OCC.

Two judgement calls worth flagging to the orchestrator:

1. **Auth header naming.** The scaffold declares `role_header: X-Role` (and `ERR_UNAUTHENTICATED`'s trigger is "Missing X-Role header"), while this skill's fixed contract says `X-User-Role`. §2.1 specifies `X-User-ID` plus `X-Role`, and states the two role-header names are interchangeable with `X-Role` winning when both are present — so an implementation reading the PRD passes tests generated against either convention.
2. **`ERR_LOT_NOT_GRADED` scope.** The scaffold scopes it to prefinish-run creation only, but the `SCHEDULED → RUNNING` transition also carries a `FlooringLot.status == GRADED` precondition with no nominated code. §3.8 pairs that precondition with `ERR_LOT_NOT_GRADED` (the only defensible code); since `GRADED` is terminal the branch is practically unreachable.

## Step 5: Generate unit tests — 2026-09-02T08:53:28.934Z

The suite is complete. Final state:

## Files written

**`test_helpers/` (Stage 1, 9 modules, 2,852 lines)** — `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`. Plus `test_suite/conftest.py` (session `api` client + one header fixture per role).

**`test_suite/` (Stage 2, 16 files, 113 tests)**

| Queue B (breadth) | | Queue A (depth) | |
|---|---|---|---|
| `test_01_entities.py` | 13 | `test_08_dual_variant_calculations.py` | 4 |
| `test_02_state_machines.py` | 16 | `test_09_combinatorial_formulas.py` | 6 |
| `test_03_calculations.py` | 11 | `test_10_non_linear_state_machines.py` | 6 |
| `test_04_validations.py` | 19 | `test_11_transitive_cascades.py` | 4 |
| `test_05_endpoints_and_errors.py` | 4 | `test_12_validation_priority_conflicts.py` | 4 |
| `test_06_rbac.py` | 5 | `test_13_boundary_precision.py` | 4 |
| `test_07_cross_cutting.py` | 5 | `test_14_cross_entity_state_gates.py` | 4 |
| | | `test_15_resource_temporal_overlap.py` | 4 |
| | | `test_16_compensating_invariants.py` | 4 |
| **73 tests / 71 instances** | | **40 tests / 20 instances** | |

## Audits

- **Coverage:** 20/20 queue-A instances (≥2 tests each), 71/71 non-stub queue-B instances (≥1 each). Every `Design:` tag resolves to a real `name:`; no untagged, dual-tagged, or stub-pointing test.
- **PRD citations:** 0 problems — every quoted sentence survives a literal grep of `PRD.md` *and* is attributed to the section it actually appears in.
- **Scaffold citations:** no emitted comment or docstring mentions "scaffold" or a scaffold section label.
- **Hygiene:** `pytest --collect-only` → 113 tests, no errors; `pyflakes` clean across `test_suite/`; no `pytest.mark.skip/xfail`; no raw payload dicts (all via `*_payload()` factories). Also removed three pre-existing unused imports in `test_12`.

## Instances skipped

**None.** All 91 non-stub instances translated. The 21 `excluded_because:` stubs in `SCAFFOLD_CORNER_DESIGN.yaml` were correctly not translated (their claims are already carried by the named §1.8 instances).

## Design-index assertions overridden by the PRD (7)

Where an instance's expected value contradicted the PRD, I asserted the PRD-derived value rather than weakening or dropping the instance:

1. `fourth_open_claim_rejected_and_allowed_after_denial` — yaml wanted `adjudicated_liability_cents == 0` on a DENIED claim; §3.9 says those fields "all stay null" → asserted `is None`.
2. `lot_void_blocked_after_byproduct_sale_exists` and 3. `byproduct_sale_above_available_tons_rejected` — yaml decremented `available_tons` after sales; §3.6 fixes it "once from the milling report" and the ceiling test compares `sold_tons + qty` against it → asserted `sold_tons` moving and `available_tons` fixed.
4. `install_date_in_future_and_expired_warranty_rejected` — yaml asserted `service_months`/`depreciation_pct` at intake; §3.9 computes both in step five of *adjudication* → asserted the 201 + `estimated_liability_cents == 147960` instead (the 60-month boundary claim survives via the 201).
5. `third_redry_cycle_rejected_at_limit` — yaml put `blocked_until_utc` on the chamber; grep proves it is a **KilnCharge** field → asserted chamber `AVAILABLE` plus the charge's `blocked_until_utc`.
6. `warranty_posture_flips_exactly_at_the_five_hundred_thousand_floor` — yaml wanted `freeze_override is null`; §3.1 says it is `false` on creation → asserted `is False`.
7. `stale_species_profile_version_rejected_then_correct_version_succeeds` — yaml's 384.25→384.3 for the 1.25-inch DENSE schedule adds conditioning/stress-relief *before* the thickness scaling; §3.1 adds them after, giving 368.05 → 368.1 → clamped to the 360-hour ceiling → asserted **360.0**.

## Step 6: Generate implementation — 2026-09-02T08:53:28.934Z

The implementation is complete and all worked examples from the PRD pass.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2387_hardwood_flooring_mill_kiln_drying/workspace/implementation/`

| File | Role |
|---|---|
| `start.sh` | launcher — `exec python3 app.py`, guarded pip install (only when Flask is missing, so the per-test reboot never contends) |
| `requirements.txt` | `flask>=3.0.0` |
| `app.py` | Flask app, 8 blueprints, `ApiError`/`HTTPException`/`Exception` handlers on the standard envelope, whole-request `db.LOCK`, `host=0.0.0.0`, `PORT` env (default 10000) |
| `db.py` | in-memory dict store, every collection empty on boot, logical clock, `insert`/`touch`/`ordered`, ISO-8601-with-3-digits formatter |
| `errors.py` | all 52 catalogue errors + `ApiError` |
| `response.py` | `meta`/`response_type`/`data` envelope, pagination meta |
| `middleware.py` | `X-Role` (with `X-User-Role` fallback), `authorize()` |
| `validation.py` | schema screening, pagination (1–100 / ≥0) |
| `serializers.py` | explicit field order per entity; `GradeBundle` alone omits `updated_at`/`version` |
| `services/calc.py` | all 20 calculations with rounding pinned (Decimal, ROUND_HALF_UP; never float for money) |
| `services/lookup.py` | existence resolution mapped to the right 404 per screening step |
| `services/mill.py` | ledger reconciliation + cascades (displacement, core reservations, remaining dry bf, sold tons, posture, prefinish holds) |
| `routes/config.py`, `receipts.py`, `charges.py`, `lots.py`, `grading.py`, `prefinish.py`, `byproducts.py`, `warranty.py` | the HTTP surface |

**76 endpoints** registered (1 clock + 75 under `/mill`) — an exact match to the PRD §4 table.

## Verification

Booted via `PORT=10711 bash start.sh` (200 on a live list, empty store, 404 on unknown route, 401 with no role). A 130-assertion end-to-end script reproduced every PRD worked example: 265.0 planned hours; window `2026-08-16T01:00:00.000Z`/`07:00:00.000Z` with the closed-interval touch conflicting and +1h not; weighted moisture 45.2 from 9700 bf (and allocate/deallocate proven an exact inverse); gradient 1.8/avg 7.3/release with `dry_bf_out` 8972.50; movement 0.0009 → planned 3.188 (and 0.0024 → 3.190); residue 570.00 / waste 570.00 / provisional 78.00 vs ceiling 720.00; shorts batch 0.63 t; settlement 11000/330/6100/16770 and 10978/0/6100/17078; bundle values 813029/781352/433888/140058 → run total 2168327 with credited 3970.2625; final yield 66.17 → GRADED, delta −11.83; coating 47.85 L with the 9000/9001/back-to-back capacity trio; core reservation 3190.00; estimate 355104; adjudication installer 50 / mill 50 / 5 months / 2.5 % / 151474 → balance 448526 RESTRICTED → fund → 548526 OPEN; reversal returning the line to zero committed with the run still HELD; redry displacement returning wood and the redry limit leaving the charge in `CONDITIONING`.

## Design decisions where the PRD was ambiguous

1. **Reference resolution on allocate/deallocate** — §2.7 puts receipt existence (step 5) before charge existence (step 6), so an unknown charge *and* unknown receipt reports `ERR_RECEIPT_NOT_FOUND` even though the charge is the path segment. Followed literally.
2. **Unknown `core_stock_id` on a SOLID lot** yields `ERR_CONFIG_NOT_FOUND` (step 4), not `ERR_CORE_STOCK_NOT_ALLOWED` (step 30).
3. **No error id exists for a direct `grade-bundle`/`byproduct-sale` miss** — both return 404 with a generic `ERR_NOT_FOUND`, as does any unmatched route or method.
4. **Unrecognised role** (not one of the 8, not `Anonymous`) → `ERR_FORBIDDEN_ROLE` 403; only a missing/blank role header or `Anonymous` → 401. `X-User-ID` is never required for authentication.
5. **`quarantine_reason` is server-generated** (it appears in no request payload) — a sentence naming the final yield and the 55.00 floor.
6. **Freeze holds runs only when the previous posture was `OPEN`** (PRD prose); an approval holds whenever the *recomputed* posture is `RESTRICTED` or `FROZEN`; funding, unfreezing and reversal never create new holds.
7. **Segregation of duties** is skipped when the request carries no `X-User-ID` (nothing to compare); otherwise a match on `submitted_by_user_id` is a 403.
8. **Decimals serialise as JSON floats** (so `78.00 == 78.0`), cents and board-feet counters stay `int`. Ordering uses an internal `_seq` counter, equivalent to ascending `created_at` but immune to same-millisecond ties, and is excluded from every representation.
9. **`charged_green_bf` counts `ALLOCATED` *and* `CONSUMED` receipts** per §2.8, so the figure survives loading.
10. **`reschedule` runs no chamber-state check** — step 17 lists only start/complete maintenance, charge creation and loading.

## Step 7: Run tests and iterate — 2026-09-02T13:55:00.000Z

**Resume note (orchestrator):** this run entered in RESUME MODE. Filesystem inspection showed Steps 1–6 all satisfied (SCAFFOLD trio present and non-empty; `workspace/INSTRUCTION.md` present; `workspace/PRD.md` complete at 456 lines, ending in the finished error-code table, no mid-section truncation; `test_suite/` with 16 `test_*.py` + `conftest.py` and `test_helpers/` present; `workspace/implementation/` with sources + `start.sh`). Per the resume protocol none of Steps 2–6 were re-run. Stale `results.*.json` from an earlier aborted sweep (whose `total` varied 90–110, i.e. aborted rounds) plus `sweep.log` and all `__pycache__` were deleted before the first sweep.

**Subagent summary (verbatim):**

Clean 8-round sweep achieved. No artifact changes were needed — the prior failures were environmental.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (all under `setsid nohup`, no early exit).

**Iteration 1 (13:26–13:36):** all 8 rounds collected the same `total` = 113 (so the earlier "total varied 90–110" symptom is gone — that was an aborted-round artifact, not present now). 5 rounds were 113/113; 3 rounds had exactly one failure each, all connection-level, never an assertion:
- `test_10_non_linear_state_machines.py::TestChargeConditioningRedryCycle::test_resume_clears_the_readings_and_a_second_test_releases_without_recounting` — `ConnectionResetError(104)`
- `test_11_transitive_cascades.py::TestClaimApprovalCascade::test_approval_debits_the_reserve_and_restricts_the_line` — `RemoteDisconnected`
- `test_09_combinatorial_formulas.py::TestKilnScheduleDuration::test_medium_thicker_schedule_crosses_a_different_tier_and_rounds_half_up` — `IncompleteRead(0 of 181 bytes)`

**Root cause established as environmental, with direct evidence:** the per-test server logs (`/tmp/prd_bench_server_<port>.log`) show the Flask process ending in `Terminated` (SIGTERM) mid-test — e.g. port 46845 block 84 dies right after `POST /mill/green-receipts` 201, inside the failing test's setup. The runner itself only ever uses `kill -9` (`Killed`, 111–113 per round, as expected for per-test isolation). Correlating timestamps: SIGTERMs landed in three host-wide waves (~13:33:45–52, ~13:34:11–25, ~13:38:28–41) and hit **97 other tasks' server logs on ~100 other ports simultaneously** — a host-wide SIGTERM storm from outside this pipeline (not my `setsid` group, whose foreground polls straddled the waves rather than coinciding with them). No Python traceback, no `Address already in use`, and no OOM signature in any of my 8 rounds' logs.

**Iteration 2 (13:47–13:52, after the storm subsided):** all 8 rounds `passed == total == 113`, 0 failed, 0 errors, 0 skipped, ~300s each; zero `Terminated` in `workspace/sweep.log`; ports released, no runner processes left.

- **Tests deleted:** none. No test failed on an assertion in any of 904 test executions, so STEP 1/2 never triggered.
- **Fixes to `test_helpers/`:** none needed. (Audited the flakiness-prone path anyway: `test_suite/conftest.py`'s `api` fixture is already function-scoped with `session.close()`, so no keep-alive socket outlives a server restart; the module-level `_default_api` fallback in `test_helpers/fixtures.py:19` is never reached because every test passes `api` explicitly.)
- **Fixes to `test_suite/`:** none. Suite has no `skip`/`xfail` and no race-based assertions (`run_race`/`assert_race_outcome` unused), i.e. no intrinsic nondeterminism.
- **Fixes to `implementation/`:** none.

Note for future runs on this host: `Terminated` in `/tmp/prd_bench_server_<port>.log` with no traceback, appearing at the same wall-clock instant across many unrelated ports, is the fingerprint of this external storm; the correct response is to re-sweep, not to touch the artifact.

**Orchestrator verification:** independently re-read all 8 `results.*.json` — every round reports `passed=113 total=113 failed=0 errors=0 skipped=0`. Step 7 complete.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T13:56:00.000Z

Skip condition met: Step 7 produced **0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes**, so the `<step_7_diff>` focus list Step 8 operates on is empty and the subagent would have no in-scope edit to make. `PRD_FINALIZED.md` is therefore not produced.

Judgement call recorded for transparency (no user available to consult): an *earlier, unrecorded* Step 7 attempt from before this resume had touched `workspace/implementation/app.py`, `requirements.txt`, and `start.sh` (mtime 11:28, after that attempt's 11:12–11:16 results files), and no Step 7 worklog entry was ever written for it. That attempt's diff is unrecoverable — the task directory is untracked in git, so there is no baseline to diff against. Consequently no `<step_7_diff>` can be reconstructed for it either, and Step 8 remains a no-op regardless. Any PRD silence that the earlier attempt resolved inside `implementation/` is covered by Step 9, whose full PRD-vs-`implementation/` scan is not scoped to a diff and always runs. Step 9 therefore starts from `PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T14:02:00.000Z

Source was `PRD.md` (Step 8 skipped, so no `PRD_FINALIZED.md`).

**Subagent summary (verbatim):**

Done. `PRD_COMPLETED.md` is written.

## Summary

- **Source vs output**: `PRD.md` 456 lines / 81,713 chars → `PRD_COMPLETED.md` 457 lines / 84,249 chars (**+1 line, +2,536 chars**); 22 edit sites, all in-paragraph (or single table-row/cell) — no new sections.
- **Counts**: 16 ambiguity-pins, 6 mismatch-revisions.

### Changes
- `§2.1` — revise — ambiguity — a blank/whitespace role header counts as absent, and an *unrecognised* role value (not just a recognised-but-unpermitted one) yields `ERR_FORBIDDEN_ROLE` — `middleware.py:38-65`
- `§2.1` — insert — ambiguity — `X-User-ID` is not part of authentication; when omitted the request is admitted and a null identifier is recorded — `middleware.py:47`, `routes/warranty.py:84`
- `§2.1` — insert — ambiguity — SoD is pure identifier equality, so an adjudication carrying no `X-User-ID` never trips it — `routes/warranty.py:166`
- `§2.3` — revise — ambiguity — rows sharing a `created_at` millisecond keep creation order; a filter naming a non-existent id yields an empty page, and an out-of-enum filter value is `ERR_INVALID_REQUEST` — `db.py:96-98`, `services/lookup.py:82-89`, `validation.py:173-179`
- `§2.4` — insert — ambiguity — the clock endpoint's `data` carries the single field `current_utc` in the standard instant format — `routes/config.py:33`
- `§2.10` — insert — ambiguity — grade bundles and byproduct sales have no §2.7 existence step; an unknown one (or an unrouted path/method) answers `ERR_NOT_FOUND` (404) — `services/lookup.py:59,71`, `app.py:67-68`
- `§5` — insert — ambiguity — added the `ERR_NOT_FOUND` | 404 catalogue row — `errors.py:59`
- `§3.1` — revise — ambiguity — `conditioning_hours` / `stress_relief_hours` are whole-hour integers — `routes/config.py:93-94`
- `§3.4` — revise — ambiguity — allocation requires exactly `ACCEPTED` (already-allocated/rejected included), the receipt check precedes the charge check, and the response is the updated charge — `routes/charges.py:100-120`
- `§3.4` — revise — **mismatch** — derived charge quantities recompute from the §2.8 ledger set (`ALLOCATED` **or `CONSUMED`**), not `ALLOCATED` alone — `services/mill.py:16-28`
- `§3.4` — revise — ambiguity — deallocating a receipt allocated to a different charge yields `ERR_RECEIPT_STATE_INVALID`; response is the updated charge — `routes/charges.py:132`
- `§3.4` — revise — **mismatch** — loading screens charge status first, then chamber, then moisture plan (prose had listed chamber first) — `routes/charges.py:152-167`
- `§3.5` — revise — ambiguity — a redry-limit refusal writes none of the four stress-test figures — `routes/charges.py:223-229`
- `§3.6` — revise — ambiguity — `haul_distance_miles` is a whole number of miles — `routes/byproducts.py:47`, `services/calc.py:303`
- `§3.7` — revise — **mismatch** — the replacement run's `FINALIZED` status is screened at step 19, before the same-lot check, so a run both unfinalized and on another lot reports `ERR_GRADE_RUN_STATE_INVALID` — `routes/grading.py:184-187`
- `§3.7` — revise — ambiguity — `quarantine_reason` is server-composed; the payload carries only `grade_run_id` — `routes/lots.py:197-200`
- `§3.9` — revise — ambiguity — freezing an already-`FROZEN` line and unfreezing a never-frozen line both succeed and change nothing beyond re-derivation — `routes/config.py:276-300`
- `§3.9` — revise — ambiguity — `denial_reason` is recorded only on the denial branch, ignored on approval — `routes/warranty.py:177-208`
- `§3.9` — revise — ambiguity — reference moisture also falls back to `target_moisture_pct` when the charge carries no recorded average — `routes/warranty.py:25-35`
- `§4` — revise — **mismatch** — product-line listing also filters by construction type — `routes/config.py:254`
- `§4` — revise — **mismatch** — core-stock listing also filters by core material — `routes/config.py:338`
- `§4` — revise — **mismatch** — a run's bundle listing also filters by grade class — `routes/grading.py:116`

Verified along the way that every endpoint path, role list, screening-order position, formula and worked example already in the PRD matches the implementation exactly (all §3 numeric examples recomputed against `services/calc.py`), so no other edits were needed.

**Orchestrator verification:** `workspace/PRD_COMPLETED.md` exists, 457 lines / 84,249 chars, ends with the completed error-code table (final row `ERR_NOT_FOUND | 404`) — not truncated. Pipeline complete.

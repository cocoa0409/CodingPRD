# Worklog — task_2540_precision_optics_manufacturing

## Step 1: Create task directory — 2026-09-03T08:25:24.398Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2540_precision_optics_manufacturing` and its `workspace/` subdirectory. Index 2540 was pre-assigned by the invoking pipeline (no auto-allocation scan performed, per instruction — 32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-03T10:39:24.107Z

All three artifacts are complete and lint-clean.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2540_precision_optics_manufacturing/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2540_precision_optics_manufacturing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2540_precision_optics_manufacturing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    74
  §1.1 entities declared:     14
  §1.8 instances scanned:     25
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1731

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

| File | Lines | Top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 2389 | scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, conventions, calculations, validations, endpoints, errors, roles (no `scaffold_*_design` keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2583 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 7067 | `scaffold_corner_design` only |

All three files `yaml.safe_load` cleanly.

## SCAFFOLD.yaml counts (§1.0–§1.7)

entities 14 · state_machines 11 (parallel-dimension shape) · calculations 12 · validations 27 priority rules · endpoints 74 · errors 55 · roles 7 · concurrency_rules 3 · `api_prefix: /optics` · difficulty `expert_plus`, archetypes workflow_orchestration + compliance_audit, complexity layers optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers, consistency `immediate`.

Entities: OpticalDesign, ToleranceAllocation, GlassLot, WorkOrder, MetrologyInstrument, ProcessRun, MetrologyReport, CoatingChamber, CoatingRun, Assembly, AssemblyComponent, InspectionRecord, DocumentationPackage (+ documents), ExportClassification.

## §1.8 — 9 rules / 25 instances

- `dual_variant_calc` 2 · `combinatorial_formula` 3 · `non_linear_state_machine` 3 · `transitive_cascade` 3 · `priority_pair_validation_conflict` 4 · `boundary_precision_check` 3 · `cross_entity_state_dependency` 3 · `resource_temporal_overlap` 2 · `compensating_invariant` 2

## §1.9 — 9 sections / 84 instances (65 full recipes + 19 `excluded_because` stubs)

entities 12 · state_machines 14 · calculations 14 · validations 16 · endpoints 5 · errors 10 · rbac 5 · complexity_layers 6 · consistency_model 2. Every stub cites a `difficulty_instance` that exists by name in §1.8 and carries no `test_recipe` (verified programmatically).

Final two sections added this session: `complexity_layers` — two OCC instances (stale glass-lot version on work-order create; stale assembly version on the second component), a `rate_threshold_triggers` instance where a 1200 nm cumulative cut leaves 6198.8 µm against a 6199.0 µm minimum and scraps with MIN_THICKNESS_BREACH on iteration 1 while a twin order removing 100 nm takes the FIGURING→POLISHING rework loop, a DENIED-licence fan-out, plus stubs to the spectral dual-variant and post-release scrap cascade; `consistency_model` — the blank ledger correct in the mutating response itself (4-blank lot: exact-fit reservation then ERR_INSUFFICIENT_BLANKS with no intervening read) and licence/align effects visible to the immediately following read.

## Design adjudications

1. **WorkOrder scrap-cascade reachability** — the post-release scrap cascade needed a component hop, so `RELEASED_TO_ASSEMBLY -> SCRAPPED` carries the ledger write-off as a consumed→scrapped move (not a reserved release).
2. **Export denial vs revocation** — a single classification cannot both approve and deny, so the assembly hop (`ALIGNED/SEALED -> EXPORT_BLOCKED`) is only reachable through `POST /export-classifications/{id}/revocation`; the §1.9 DENIED instance asserts that hop 3 is vacuous on the denial path and leaves it to the §1.8 revocation instance.
3. **`ALIGNED -> EXPORT_BLOCKED` hop added** to the Assembly machine so the revocation cascade has a terminal landing state, with KITTED/CEMENTED/MOUNTED explicitly left alone.
4. **`GRINDING -> POLISHING` transition added** so `STAGE_ADVANCE_MAP` is total over the three fabrication stages.
5. **Export precondition removed from design release** — release gates only on `tolerance_verdict != FAIL`; the export gate sits on `release-to-assembly` (priority 9) instead, keeping the two dimensions independent.
6. **A FAIL analysis still moves DRAFT→TOLERANCED** (and re-analysis is refused), which is what makes `ERR_TOLERANCE_BUDGET_EXCEEDED` reachable at release and makes a failing design a genuine dead end.

## Step 3: Copy shared files — 2026-09-03T10:39:45.663Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T10:56:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **473 lines** (114,413 bytes), built via 9 chunked bash appends (no single giant Write). Last section heading is `## 5. Error Code Catalogue`; the file ends on the final completed table row `| ERR_CLOCK_NOT_MONOTONIC | 422 |`, i.e. at a real section boundary, not mid-sentence.

Orchestrator truncation check (independent of the subagent): `wc -l` = 473, 28 headings from `# Precision Optics Manufacturing API` through `## 5. Error Code Catalogue`, `tail -25` shows a complete markdown table ending on a closed row. NOT truncated — accepted.

**Scope constraints honored:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced. No sibling task directory under `tasks/` was read.

**Hard Contract 1 — Field-Name Coverage: PASS**
```
entities[].fields             153 required, 153 present, 0 missing
endpoints[].input fields      107 required, 107 present, 0 missing
errors[].id                    55 required,  55 present, 0 missing
roles[].name                    7 required,   7 present, 0 missing
calculation output symbols     49 required,  36 present, 13 pseudocode locals (prose-rendered)
```
The 13 unmatched calculation symbols (`comps`, `design`, `in_band`, `aligned`, `controlled`, `band_average_ok`, `figure_ok`, `roughness_ok`, `twf_ok`, `worst_point_ok`, `capability_ratio`, `occupancy`, `required`) were confirmed against the entity tables to be non-persisted pseudocode locals; per the no-pseudocode rule their semantics are stated in prose rather than as symbols. All persisted outputs are present.

**Hard Contract 2 — Rule Coverage: PASS**
```
validations[] (priority 1-27)      27/27 enumerated in §2.8 with error id, HTTP status, applies_to scope
concurrency_rules                   3/3 in §2.7 (endpoint path + occ_field + parent + error id + 412)
state_machines                    11/11 entities, 57/57 transitions covered in §3
calculations                      12/12 fully specified in prose
cross-entity cascades / hop order   all covered (§2.9 + §3.7 three-hop denial cascade)
field defaults                      all non-null defaults present in prose (audited mechanically)
sibling-branch symmetry             all PASS/FAIL, APPROVED/DENIED, align 3-way branches paired
```

**Hard Contract 3 — §3 Path Purity: PASS** (900+ backtick tokens scanned in §3; 0 begin with `/`, 0 bare HTTP-method tokens, 0 method+path tokens)

**Coverage counts:**
- §1.5 endpoints: **74/74** — exact `(method, path)` set comparison against the scaffold (0 missing, 0 extra), each with description and authorized roles.
- §1.6 error codes: **55/55** in the §5 table with HTTP status; all 55 also appear in the §1–§3 narrative at their triggering rule.
- §1.4 calculations: **12/12** (tolerance_stack_analysis, spectral_performance_verification, metrology_capability_index, assembly_transmitted_wavefront, metrology_acceptance_verdict, figuring_removal_convergence, blank_conservation_ledger, instrument_minutes_ledger, chamber_capacity_occupancy, cleanliness_inspection_verdict, documentation_completeness, export_control_classification), including the pinned round-to-4dp-then-combine ordering.
- Validation rules: **27/27**, enumerated in priority order in §2.8.
- State-machine transitions: **57/57** across 11 machines, each verified to have a §3 paragraph naming both its from-state and to-state.

Two coverage gaps were found and closed during the final pass: the `RELEASED → SUPERSEDED` design transition now names its from-state and its `ERR_INVALID_STATE_TRANSITION` gate explicitly (§3.1), and the export denial cascade now writes `LICENSE_REQUIRED → LICENSE_DENIED` explicitly (§3.7). §2.7 was also tightened to name each OCC-guarded endpoint path directly.

## Step 6: Generate implementation — 2026-09-03T11:36:00.000Z

(Launched concurrently with Step 5; Step 6 returned first. Logged here in step order.)

The implementation is complete. Final report:

## Modules (`workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `store.py` | 128 | in-memory dicts keyed by id, uuid minting, monotonic `_seq` row ordering, `created_at`/`updated_at`/`version` bookkeeping, logical clock (default `2026-08-01T00:00:00Z`) |
| `errors.py` | 126 | 55-code catalogue → HTTP status + default message, `ApiError` |
| `common.py` | 269 | envelope (`meta`/`response_type`/`data`), auth (401 then 403), pagination, all field/FK/OCC validators |
| `calc.py` | 262 | all 12 calculations + every named constant |
| `logic.py` | 423 | serializers, derived reads, blank/instrument ledgers, all multi-hop cascades, release gate |
| `routes_designs.py` | 268 | designs + tolerance allocations (11 endpoints) |
| `routes_glass.py` | 122 | glass lots (5) |
| `routes_workorders.py` | 183 | work orders, both state dimensions (8) |
| `routes_metrology.py` | 365 | instruments, process runs, metrology reports (14) |
| `routes_coating.py` | 224 | chambers, coating runs (9) |
| `routes_assemblies.py` | 276 | assemblies, components, readiness, sub-lists (14) |
| `routes_inspection.py` | 94 | inspection records + waiver (3) |
| `routes_export.py` | 112 | export classifications, licence decision, revocation (4) |
| `routes_docs.py` | 129 | documentation packages, documents, submit, review (5) |
| `routes_clock.py` | 24 | `POST /_clock/set_current_utc` (1) |
| `app.py` | 99 | blueprint registration, per-request serialising lock, `ApiError`/404/405/500 handlers, `0.0.0.0:$PORT` |
| `start.sh` + `requirements.txt` | 11 + 1 | `$PORT`, guarded flask install, `exec python3 app.py` in the foreground |

Total 3,116 lines of Python. `python3 -m compileall -q .` clean; `pyflakes` reports zero findings.

## Coverage
- **Endpoints: 74 implemented / 74 declared.** Verified by enumerating `app.url_map` and comparing against `grep -c "^  - method:" SCAFFOLD.yaml` — both 74, with matching paths.
- **All 12 calculations** in `calc.py`: tolerance contribution, tolerance stack analysis (RSS/worst-case/governing/verdict), spectral aggregates, effective uncertainty with the 2%/day drift and 2x cap, capability ratio (k=4, <=0.2500), assembly transmitted wavefront (element RSS -> centration -> subtotal -> tiered cement derate), stage figure budget (x10/x3/x1), acceptance verdict, blank conservation/reservation sizing (25% spare, min 1), metrology window minutes, cleanliness verdict, documentation completeness, export classification (FOM, ECCN, licence). Decimal arithmetic throughout with `ROUND_HALF_UP` and a prec-50 `sqrt`.
- **All 27 validation priorities** are enforced in global order: 1 auth -> 2 role -> 3 path 404 -> 4 body-FK 404 -> 5 field validation -> 6 OCC 412 -> 7 state (incl. `ERR_REPORT_ALREADY_SIGNED`, `ERR_EXPORT_ALREADY_DECIDED`, `ERR_WORK_ORDER_NOT_IN_PROCESS`) -> 8/9 export gates -> 10 inspection gate -> 11 waivable -> 12 SoD -> 13 parent-released gates -> 14 stage order -> 15 run already open -> 16 calibration overdue -> 17 capability -> 18 window shape -> 19 station conflict (closed interval + 15-min purge) -> 20 chamber capacity (half-open, aggregate) -> 21 substrate suitability -> 22 uniqueness (6 codes) -> 23 element allocation -> 24 empty/incomplete/not-approved -> 25 422 business constraints -> 26 insufficient blanks -> 27 clock monotonicity.

## Smoke test
Launched on ports 18540/18541/18542 via `PORT=... bash start.sh`, then killed **only** by the pid resolved from that exact port (no pattern kill). Three scripted scenarios, ~120 calls, all assertions green:
- Full happy path design -> allocations -> analysis -> release -> lot -> certification -> work order -> 3 metrology stages (GRINDING/POLISHING/FIGURING signed ACCEPTED) -> chamber -> coating run -> deposit -> spectral PASS -> export classification (FOM 3000.00, ECCN `6A004.A.1`, licence required) -> screen -> APPROVED sweep -> release-to-assembly -> assembly -> 2 components -> cement -> mount -> align (total 0.051 vs 0.5 budget) -> failed inspection -> waiver -> 6-type documentation package reaching 100.00 -> submit -> review APPROVED -> pass inspection -> seal -> readiness (`blocking_error_id: null`) -> release.
- Cascades: strip-limit scrap (2nd strip -> run SCRAPPED, order SCRAPPED `COATING_STRIP_LIMIT`, 3 blanks written off, availability recomputed), lot block (order -> HELD `GLASS_LOT_BLOCKED`), work-order cancel (open run -> CANCELLED `WORK_ORDER_CANCELLED`, reservation released), licence revocation (classification -> LICENSE_DENIED with `decision_note`, work order -> BLOCKED).
- Error envelopes: 401, 403 role, 403 SoD (waiver and review self-approval), 400 short justification, 404 unknown id, 409 duplicates (design code, classification, package, document type), 412 stale lot version, 422 empty stack and clock-backwards, plus `limit=0`/`limit=101` 400s and correct `limit`/`offset`/`total_count`/`has_more` meta.
- Fresh-boot check on a clean process: store empty (`total_count: 0`), clock reads `2026-08-01T00:00:00Z`. No seeding, no disk persistence.

## PRD ambiguities resolved
1. **Waiver check order** — §3.9 prose puts SoD before waivability and the justification length last; the §2 global priority table puts field validation (5) < state (7) < `ERR_DEFECT_NOT_WAIVABLE` (11) < SoD (12). I followed the priority table, since the PRD states the first violated rule in global order determines the response.
2. **Waiver -> documentation consequence** — required document sets are "derived, never declared", so the waiver writes nothing on the packages; they re-derive `required/missing/completeness_pct` on their next read (no version bump on the package).
3. **Scaffold-required vs PRD-defaulted fields** — where the scaffold omits `?` but the PRD gives a default, the field is optional (`melt_index_nd`, declared grades, `wo_code`, `instrument_type`, `decenter_um`, `tilt_arcmin`, `element_wavefront_rms_waves`, `scratch_count_at_limit`).
4. **Design revision** — copies only the omitted specification fields, resets stack outputs to null / verdict PENDING / status DRAFT, revision = predecessor + 1, `supersedes_design_id` set, 201; predecessor -> SUPERSEDED. `ERR_DUPLICATE_DESIGN_CODE` is enforced after the state check.
5. **Retiring an already-RETIRED allocation** -> `ERR_INVALID_STATE_TRANSITION` (409).
6. **`license-decision`** records `decided_by_user_id` on both APPROVED and DENIED; `license_number` only on APPROVED; `decision_note` stays null (only revocation writes it).
7. **Non-string body FK values** skip the priority-4 lookup and fail at priority 5 with `ERR_INVALID_REQUEST`.
8. **`POST /optics/process-runs/{id}/cancel`** defaults `cancel_reason` to `CANCELLED_BY_OPERATOR`; work-order cancel leaves it null when omitted.
9. **Signature-driven `process_status` changes** (accepted stage advance, FIGURING rework/scrap) are suppressed when the order is SCRAPPED/CANCELLED/HELD; the removal-ledger recompute and `figuring_iteration_count` increment still occur.
10. **Spectral PASS** advances the order only from `COATING`; **strip** touches the order only from `{COATING, COATED}`.
11. **`release-readiness`** reports `completeness_pct: null` when no package exists and follows the release-gate order for `blocking_error_id`.
12. **List filters** on enum query params are not validated (unknown values simply match nothing); only `limit`/`offset` range violations are 400.
13. **`scrap_reason`** is validated as a non-empty string, not an enum (the scaffold declares `type: string`).
14. **Metrology report creation** is not gated on `run_status`, and **assembly creation** is not gated on the design being RELEASED — neither gate appears in the PRD or the priority table.
15. **Unrouted paths / wrong methods** return the standard error envelope with `ERR_INVALID_REQUEST` (no catalogue code exists for 404-route or 405).

## Step 5: Generate unit tests — 2026-09-03T12:46:30.000Z

(Launched concurrently with Step 6 in the same assistant message pair; Step 5 finished second. Logged here in step order.)

Generation and verification are complete.

**Output**

`test_suite/` — 15 files:

| file | lines |
|---|---|
| conftest.py | 34 |
| test_01_optical_design_lifecycle.py | 443 |
| test_02_tolerance_allocation_budget.py | 349 |
| test_03_glass_lot_ledger_and_block_cascade.py | 481 |
| test_04_work_order_creation_gates.py | 596 |
| test_05_fabrication_state_machine.py | 611 |
| test_06_process_run_scheduling.py | 690 |
| test_07_metrology_capacity.py | 402 |
| test_08_wavefront_reports.py | 334 |
| test_09_coating_runs.py | 528 |
| test_10_export_control.py | 806 |
| test_11_assembly_rollup.py | 735 |
| test_12_inspection_and_waivers.py | 617 |
| test_13_documentation_and_release.py | 804 |
| test_14_authorization_and_not_found.py | 1019 |

`test_helpers/` — 9 modules: `__init__.py` (158), `api_client.py` (577), `api_errors.py` (152), `assertions.py` (476), `constants.py` (268), `factories.py` (402), `fixtures.py` (816), `test_users.py` (119), `types.py` (33). Total across both directories: 11,646 lines.

**Counts**

- Test files: 15 (14 test modules + conftest).
- Test functions: 139 defined; 148 collected by pytest (`--collect-only -q`), the extra 9 coming from parametrized cases.
- Queue A (SCAFFOLD_DIFFICULTY_DESIGN.yaml): 25 / 25 non-stub instances translated, across all 9 rules; every Queue A instance carries at least 2 tests (rendered as `class Test...` groups).
- Queue B (SCAFFOLD_CORNER_DESIGN.yaml): 65 / 65 non-stub instances translated, across all 9 sections. The 19 instances marked `excluded_because:` (stubs) were correctly not translated.

**SKIPPED instances: none.** Every non-stub instance in both queues passed the PRD-first two-condition filter. The decisive factor was PRD §2.8, which enumerates all 27 validation priorities verbatim, so every ordering/precedence assertion in the design indices is uniquely derivable from the contract text; §2.6 likewise gives the full path-then-body FK not-found catalogue with left-to-right ordering. One sub-assertion (not an instance) was dropped inside the release-readiness corner instance — a design's `completeness_pct == 0.00` on a read taken when no documentation package exists is not uniquely derivable from the PRD — and the instance itself was still translated through its derivable assertions.

**Design-tag confirmation.** `/tmp/prd2540_scaffold_sweep.py` loads both yamls, classifies stub vs non-stub by `test_recipe:` / `excluded_because:`, and walks every `test_suite/test_*.py`: it reports 139 test functions, queue A 25/25, queue B 65/65, **0 problems** — meaning every test docstring ends with exactly one `Design:` line, no test is untagged or dual-tagged, and every tag resolves to a real non-stub instance whose `name:` matches verbatim.

**Other verification**

- `/tmp/prd2540_check_citations.py` over all 24 generated files: 0 problems — every quoted span of 20+ characters in every docstring is a literal whitespace-normalised substring of `workspace/PRD.md`, with no elided `...`/`…`.
- `python3 -m compileall -q` clean over both directories; all 15 test modules exec-import successfully; a final AST pass removed the last stale imports (`test_01`, `test_02`, `test_08`, `test_13`, `test_helpers/fixtures.py`); `__pycache__` removed.
- Isolation respected: no sibling task directory was read, listed or grepped, and nothing under `workspace/implementation/` was read or created.

### Orchestrator verification note (not from the subagent)

The subagent's per-file table lists filenames and line counts that do not match what is on disk — the on-disk `test_suite/` is `conftest.py` (36) plus `test_01_design_tolerance_stack.py` (443), `test_02_design_lifecycle_and_revisions.py` (349), `test_03_glass_lot_ledger_and_block_cascade.py` (480), `test_04_work_order_creation_gates.py` (847), `test_05_metrology_capability.py` (418), `test_06_instrument_windows.py` (543), `test_07_process_runs_and_reports.py` (712), `test_08_figuring_loop_and_scrap.py` (334), `test_09_coating_and_spectral.py` (887), `test_10_export_control.py` (583), `test_11_assembly_rollup.py` (790), `test_12_inspection_and_waivers.py` (400), `test_13_documentation_and_release.py` (804), `test_14_authorization_and_not_found.py` (1019). The aggregate figures agree exactly (15 test_suite files, 9 helper modules, 11,646 total lines, 139 test functions), so the table is a stale/garbled rendering of an earlier naming pass, not missing work. Disk is authoritative; no action taken.

## Step 7: Run tests and iterate — 2026-09-03T13:07:35.000Z

All 8 rounds green. Clean exit.

## Summary

**Iterations run:** 2 (sweep → 2 fixes → sweep).

**Iteration 1 result:** 146/148 in all 8 rounds. Union of failures = 2 tests, both failing deterministically in every round (no flakiness observed anywhere in either sweep).

**Tests deleted:** none. Both failures were STEP 2 test-artifact bugs, and neither test lost a PRD-covered assertion.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — `build_optical_design_payload()`: removed the invented `"design_name": "Precision doublet objective"` field. `design_name` appears nowhere in `workspace/PRD.md` (§3.1 enumerates the design payload exhaustively: `design_code`, `aperture_mm`, the wavelength band, the three budgets, the six optional limits, the three inspection limits, `tolerance_method`) and nowhere in `SCAFFOLD.yaml` either. The echo test iterates `payload.items()` and asserted the server echo every key, so a PRD-faithful implementation that does not persist a field the PRD never declares failed with `KeyError: 'design_name'`. Fixing the factory rather than adding the field to `implementation/` is required by the cardinal rule against adding response fields that do not trace to PRD prose. Broad reach: this factory feeds most of the suite, and no other test regressed.

**Fixes applied to `test_suite/`:**
- `test_suite/test_14_authorization_and_not_found.py` — `test_each_of_the_seven_roles_performs_its_own_exclusive_operations_end_to_end`: the final assertion read `readiness["blocking_error_id"] is None` ("a released assembly blocks on nothing") on an assembly already in `RELEASED`. That mis-translates PRD §3.9, which defines the projection as reporting "the error identifier a release attempt would return **right now**, or null when the assembly is releasable", while final release is permitted "only from `SEALED`; from any other state, `ERR_INVALID_STATE_TRANSITION`". A `RELEASED` assembly is not releasable, so the composition of those two verbatim sentences uniquely determines `ERR_INVALID_STATE_TRANSITION`. The assertion was corrected to that value (plus an added `assembly_status == "RELEASED"` check on the same projection) — strictly more faithful to PRD, not weaker; no skip/xfail, no downgrade to an HTTP-status check. `ERR_INVALID_STATE_TRANSITION` added to the module's `test_helpers` import list.

**Fixes applied to `implementation/`:** none. `routes_assemblies.release_readiness` already derives `blocking_error_id` from the same `logic.release_gate` the release endpoint uses, which is the PRD-faithful behaviour.

**Final sweep:** all 8 rounds **148/148 passed**, 0 failed, 0 errors. All eight `results.{1..8}.json` exist on disk in `workspace/implementation/` (~46 KB each, written 13:02). Zero `FAILED` lines in `workspace/sweep.log`.

### Orchestrator verification note (not from the subagent)

Per the memory note "a Step 7 subagent can claim a clean sweep while leaving no results.*.json behind", the orchestrator independently re-read all eight files off disk and confirmed `passed == total == 148` in every one of `results.1.json` … `results.8.json`. Sweep artifacts are genuine.

### Step 8 gating decision

Step 8's skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Step 7 applied 1 `test_helpers/` fix and 1 `test_suite/` fix, so the condition is NOT met and Step 8 runs. Note that both fixes are test-artifact repairs with 0 implementation fixes, so Step 8 is expected to produce a very small (possibly empty) diff — the `design_name` item is a pure fixture bug, not a PRD silence, and the `blocking_error_id` item was resolved by composing two sentences already verbatim in the PRD. Step 8 is instructed to patch only genuine PRD silences/mismatches, so an empty or near-empty diff is the correct outcome here rather than a signal of failure.

## Step 8: Finalize PRD — 2026-09-03T13:16:27.000Z

PRD_FINALIZED.md produced with exactly one clarification.

## Size
- PRD.md: 473 lines / 114,413 bytes. PRD_FINALIZED.md: 473 lines / 114,663 bytes.
- Line delta: 0 lines (0.00%). Byte delta: +250 bytes (+0.22%). One sentence inserted inside an existing paragraph; no lines added, no sections added.

## Changes
- §3.9, "Reading the gate without touching it" — insert — added one sentence pinning that `blocking_error_id` includes the state gate, so an assembly not in `SEALED` (explicitly including an already-`RELEASED` one) reports `ERR_INVALID_STATE_TRANSITION` whatever the four booleans read — `implementation/logic.py:399-401` (`release_gate`: `if assembly["assembly_status"] != "SEALED": blocking = "ERR_INVALID_STATE_TRANSITION"`, evaluated before all other gates), surfaced via `implementation/routes_assemblies.py:232,250`.

## Per-edit pre-edit search log
Edit 1 — §3.9 `blocking_error_id`
- (a) Subject: the derivation of `blocking_error_id` in the release-readiness projection, and the state precondition of release.
- (b) Paths enumerated: `grep -n "blocking_error_id\|release_gate\|release_readiness" implementation/*.py` returned the complete set — `logic.release_gate` (`implementation/logic.py:383-431`, the sole producer, read in full), `routes_assemblies.release_assembly` (`implementation/routes_assemblies.py:213-227`, raises the same blocking id), `routes_assemblies.release_readiness` (`implementation/routes_assemblies.py:229-252`, reports it and computes `completeness_pct`/`active_component_count`). No other consumer exists. I also enumerated every writer of the subject field `assembly_status` (`grep -rn assembly_status implementation/`): `routes_assemblies.py:35,142,159,186,191,193,208,222` and the two cascade demotions in `logic.py:299-300` (`ALIGNED`/`SEALED → MOUNTED`) and `logic.py:367-368` (`ALIGNED`/`SEALED → EXPORT_BLOCKED`) — confirming the non-`SEALED` state space is wider than just "pre-seal or released" (it also includes `REJECTED` and `EXPORT_BLOCKED`). Cross-checked PRD §2.8 rules 7-10 and the §2.8 closing paragraph, plus §2.11's assembly-state vocabulary and §3.7's `EXPORT_BLOCKED` cascade.
- (c) Wording adjustment: I dropped a first draft that enumerated the non-sealed cases ("whether it has yet to be sealed or has already been `RELEASED`") because `REJECTED` and `EXPORT_BLOCKED` fit neither limb — that phrasing would have been a false universal against `logic.py:299,367`. Final wording states the negative condition (`assembly_status` is not `SEALED`) with `RELEASED` only as a non-exhaustive example, which holds for every reachable state. I also wrote "the first rule a release attempt evaluates" rather than restating a gate list, so the sentence does not re-order or shorten §3.9's four-gate list or §2.8 rule 10's inspection gate.

## Items judged to need no PRD change
- `test_helpers/factories.py` `design_name` removal — pure Step-2 fixture bug. §3.1 enumerates the design payload exhaustively and never names `design_name`; `implementation/routes_designs.py` never reads or persists it. The only latent silence here is "undeclared body fields are ignored, not rejected", and that is already settled by §2.8's closed-world rule set (rule 5 lists the conditions that yield `ERR_INVALID_REQUEST`; an unknown key violates none) plus `common.py`'s validators, which only ever inspect declared names — uniformly, with no strict-schema path anywhere in `implementation/`. Adding prose about unknown fields would have been a new global claim outside the Step 7 site, so I left it alone.
- No `implementation/` fix occurred in Step 7, and I found no PRD/impl divergence at the Step 7 site: the impl's five-step release order (state → classification missing → licence → inspection → package missing → package not approved) is exactly §2.8 rules 7-10 composed with §3.9's four-gate list, including the §2.8 closing sentence that pins inspection status ahead of documentation.

### Orchestrator note

`workspace/PRD_FINALIZED.md` verified on disk at 114,663 bytes (473 lines), +250 bytes over PRD.md — consistent with a single in-paragraph insert. Proceeding to Step 9, which always runs.

## Step 9: Complete PRD — 2026-09-03T13:43:05.584Z

Step 9 was deliberately run as **three sequential file-partitioned passes** rather than one subagent, because the implementation is 17 modules / ~3,100 lines and a single exhaustive scan reliably runs out of output budget and returns a PRD_COMPLETED.md that is byte-identical to its source (i.e. the scan never actually ran). Each pass owned a disjoint slice of `implementation/`, was told which slices the earlier passes had already pinned, and edited the one shared `PRD_COMPLETED.md` in place with the Edit tool only (never Write — a 114 KB file cannot survive a single Write).

Partition:
- Pass 1 — `app.py`, `store.py`, `errors.py`, `common.py`, `calc.py`, `logic.py`, `start.sh` (envelope/meta, auth order, pagination, logical clock, id minting, version bookkeeping, all validators, 55-code status map, all 12 calculations, serializers, ledgers, every cascade, the release gate).
- Pass 2 — `routes_designs.py`, `routes_glass.py`, `routes_workorders.py`, `routes_metrology.py`.
- Pass 3 — `routes_coating.py`, `routes_assemblies.py`, `routes_inspection.py`, `routes_export.py`, `routes_docs.py`, `routes_clock.py`.

### Cumulative size

| | lines | chars |
|---|---|---|
| PRD.md | 473 | 114,413 |
| PRD_FINALIZED.md (Step 8) | 473 | 114,663 |
| after pass 1 | 473 | 120,255 |
| after pass 2 | 473 | 125,323 |
| **PRD_COMPLETED.md (final)** | **473** | **134,428** |

Net Step 9 delta: **+19,765 chars (+17.2%)**, **0 lines** — every edit is an in-paragraph insert or revision; no new sections (heading count unchanged at 28), file still ends at the §5 error-catalogue table. `cmp` confirms PRD_COMPLETED.md is NOT byte-identical to PRD_FINALIZED.md, so the scan genuinely ran.

### Counts

| pass | ambiguity-pins | mismatch-revisions |
|---|---|---|
| 1 | 17 | 2 |
| 2 | 18 | 6 |
| 3 | 14 | 10 |
| **total** | **49** | **18** |

67 changes in all.

### Pass 1 changes (core modules)

- `§2.1 (RBAC)` — insert — ambiguity — blank/whitespace-only `X-User-ID` is also 401; `X-User-ID` presence tested before role validity; unmatched path or method returns `ERR_INVALID_REQUEST` 400 *before* auth; trailing slashes tolerated — `common.py:71-79`, `app.py:45,68-80`
- `§2.2` — insert — ambiguity — `api_request_id` is `req_` + exactly 16 lower-case alphanumeric chars — `common.py:28-29`
- `§2.2` — insert — ambiguity — `api_request_timestamp` reads the host wall clock, not the logical clock; stamped afresh on every response including errors — `common.py:32-38`
- `§2.2` — insert — ambiguity — serialised rows expose only declared + named derived fields (underscore-prefixed internals hidden); decimals emitted as JSON numbers with trailing zeros not preserved (`0.4400`→`0.44`) — `store.py:116-128`
- `§2.2` — insert — ambiguity — pagination keys omitted from single-resource and error `meta`; top-level member order `meta`, `response_type`, `data` — `common.py:41-65`
- `§2.3` — insert — ambiguity — non-integer/empty `limit`/`offset` → 400; `limit` adjudicated before `offset`; no upper bound on `offset`, over-range offset yields empty page with full `total_count` and `has_more` false — `common.py:100-120,45-57`
- `§2.4` — insert — ambiguity — `id` is a random v4 UUID in canonical lower-case hyphenated form — `store.py:79`
- `§2.4` — **revise** — **mismatch** — `version` increments once per **request**, not per write: a row written twice by one request (figuring-rework-then-scrap, recompute-then-demote) refreshes `updated_at` twice but advances `version` by 1; also pinned `updated_at == created_at` at creation — `store.py:76-92`
- `§2.4` — insert — ambiguity — the clock stores/re-emits the supplied `current_utc` string verbatim, and business timestamps carry that exact string — `store.py:95-105`
- `§2.5` — insert — ambiguity — exact decimal arithmetic (not binary float); square roots evaluated at 50 significant digits before rounding; root of a non-positive sum is 0 — `calc.py:103-109`
- `§2.6` — insert — ambiguity — a body FK that is absent, null or non-string is not adjudicated at priority 4; it falls to priority 5 and yields 400 — `common.py:222-245`
- `§2.8 rule 5` — insert — ambiguity — body must be a JSON object; absent/empty body read as `{}`; unparseable or non-object body → 400; explicit `null` counts as absent (takes default); non-empty strings; numeric-as-string rejected; integer-as-float rejected; bool never a number; non-finite rejected; timestamp leniency (`Z`, explicit offset, or naive-as-UTC), normalised for comparison, stored verbatim — `common.py:83-92,138-219`, `store.py:15-30`
- `§2.9` — **revise** — **mismatch** — a row touched by several hops of the same cascade still advances `version` by exactly 1 for that request — `store.py:86-92`
- `§3.4` — insert — ambiguity — `days_since_calibration` is the signed count floored toward −∞, so a future `last_calibrated_utc` gives a negative count, `CALIBRATED` status and a drift factor below 1 — `calc.py:146-157`, `logic.py:71-74`
- `§3.4` — insert — ambiguity — the capability ratio uses the already-6-decimal `effective_uncertainty_waves`, not the raw drifted value — `calc.py:160-162`
- `§3.7` — insert — ambiguity — the governing classification is formally the first non-denied row in `created_at` ascending order — `logic.py:63-67`
- `§3.8` — insert — ambiguity — the decenter and tilt products are carried at full precision and never rounded before squaring — `calc.py:172-176`
- `§3.9` — insert — ambiguity — `wavefront_ok` false when total or budget is null; `completeness_pct` null with no package; `wavefront_ok` is informational and never contributes to `blocking_error_id` — `logic.py:393-397`
- `§5` — insert — ambiguity — an uncatalogued internal failure returns the error envelope with `ERR_INVALID_REQUEST` and HTTP 500 — `app.py:82-88`

Pass 1 also verified as already-pinned (no change): all 55 error codes and statuses match §5 byte-for-byte; all 12 calculations' constants, rounding scales, tie-breaks and gate inclusivity already match §2.5/§3 (tolerance stack RSS/worst-case, spectral 5-sample + 0.5000/1.2000, capability K=4 / 2%-per-day / 2× cap / 0.2500, assembly 0.0012/0.0080 with the 0.0500/0.1000 derate tiers at 0.0020/0.0060/0.0150, stage multipliers 10/3/1, `MAX_FIGURING_ITERATIONS=2`, NM→µm ÷1000, spare-blank `max(1, ceil(n/4))`, purge 15 min and 30..480 window, `scratch_count_at_limit ≤ 2` and the ×2 waiver rule, 3 base document types + 2dp completeness, export 100.0 mm / 0.0500 waves / 4000.00 FOM / CA-AU-GB, and the H1..H5 / A..D rank scales); `logic.py`'s ledger moves, depletion test, all cascade hop orders and the release-gate precedence.

### Pass 2 changes (designs / glass / work orders / metrology)

- §3.1 — insert — ambiguity — band-ordering check (`wavelength_max_nm > wavelength_min_nm`) is adjudicated as soon as both bounds are read, ahead of every later specification field — `routes_designs.py:65`
- §3.1 — insert — ambiguity — allocation retirement is admissible only from `ACTIVE` (`ERR_INVALID_STATE_TRANSITION` on a second retire) and does not consult the owning design's state — `routes_designs.py:166`
- §3.1 — revise — mismatch — "every field the payload omits copied verbatim" narrowed to the sixteen specification fields; the revision's `design_status`/`tolerance_verdict`/four stack outputs are re-initialised as for a fresh draft, and **no allocations are carried over** — `routes_designs.py:234-249`
- §3.1 — insert — ambiguity — a revision's `design_code` is checked against every design *including the predecessor*, so the superseded code cannot be re-used — `routes_designs.py:231`
- §3.2 — revise — mismatch — declared/validation field order corrected: `total_blank_count` is adjudicated **before** the two declared grades — `routes_glass.py:34-38`
- §3.2 — insert — ambiguity — `lot_code` compared case-sensitively; `blank_center_thickness_um` must be > 0 — `routes_glass.py:39,41-43`
- §3.2 — insert — ambiguity — `certificate_reference` runs 1 to 200 characters, and the three certification fields validate in the order listed — `routes_glass.py:74-77`
- §3.2 — insert — ambiguity — `block_reason` mandatory, 1 to 500 chars; blocking admissible **only** from `RELEASED`, so `QUARANTINED`/`BLOCKED`/`DEPLETED` give `ERR_INVALID_STATE_TRANSITION` — `routes_glass.py:97-100`
- §3.3 — insert — ambiguity — `wo_code` is optional, 1 to 40 chars when supplied, stored null when omitted; the §3.3 listing is the field-validation order — `routes_workorders.py:32`
- §3.3 — revise — ambiguity — "Three values are snapshotted" corrected to two (beyond the frozen reservation sizing): only `pinned_design_revision` and `blank_center_thickness_um` — `routes_workorders.py:69-70`
- §3.3 — insert — ambiguity — work-order `cancel_reason` is 1 to 500 chars and gets **no** default: omitted leaves it null (unlike a directly cancelled run) — `routes_workorders.py:177,182`
- §3.4 — revise — mismatch — instrument field order corrected: `last_calibrated_utc` is validated **before** `lateral_resolution_um` — `routes_metrology.py:36-39`
- §3.4 — insert — ambiguity — `instrument_code` carries no uniqueness constraint — `routes_metrology.py:33`
- §3.4 — insert — ambiguity — recording a calibration has no state gate and no ordering constraint on `calibrated_at_utc` (backdating and future-dating both accepted) — `routes_metrology.py:78-93`
- §3.4 — insert — ambiguity — the `instrument_status` list filter matches the **clock-derived** status, not a stored column — `routes_metrology.py:74`
- §3.4 — insert — ambiguity — `COATING`/`COATED`/`RELEASED_TO_ASSEMBLY`/`HELD`/`SCRAPPED`/`CANCELLED` are not admissible origins for any stage, so scheduling reports `ERR_RUN_STAGE_OUT_OF_ORDER`, never `ERR_WORK_ORDER_NOT_IN_PROCESS`; there is no separate workability gate — `routes_metrology.py:115`
- §3.5 — insert — ambiguity — `material_removed_nm` is mandatory and must be zero or greater — `routes_metrology.py:236`
- §3.5 — insert — ambiguity — run `cancel_reason` is 1 to 500 characters — `routes_metrology.py:253`
- §3.5 — insert — mismatch — report **creation imposes no gate** on `run_status` (any state, and several reports per run); the `AWAITING_METROLOGY` requirement bites only at signing — `routes_metrology.py:263-294`
- §3.5 — insert — ambiguity — `signature_note` is 1 to 1000 characters, stored null when omitted — `routes_metrology.py:310`
- §3.5 — insert — ambiguity — on a figuring rework the increment and ledger recomputation are unconditional, but the two scrap tests and the `FIGURING → POLISHING` loop are suppressed when the order is `SCRAPPED`/`CANCELLED`/`HELD` — `routes_metrology.py:341,348-360`
- §3.8 — insert — ambiguity — `scrap_reason` is mandatory free text of 1 to 200 chars, **not** an enum; the two named reasons are conventions only — `routes_workorders.py:162`
- §4 — revise — mismatch — `POST /optics/metrology-reports` description no longer claims the run must be "awaiting metrology" — `routes_metrology.py:263`
- §2.8 (priority 5) — insert — mismatch — an endpoint declaring no input fields never inspects the body, so an unparseable body on those twelve endpoints is not rejected — `routes_designs.py:163/174/199`, `routes_workorders.py:117/137`, `routes_metrology.py:208` (+ the six pass-3 endpoints, enumerated in the same insert)

### Pass 3 changes (coating / assemblies / inspection / export / docs / clock)

- §2.7 ¶4 — insert — ambiguity — the OCC guard field must be a JSON integer and its presence/type check is the **last** priority-5 validation, so omitting it plus malforming another field reports the other field — `routes_assemblies.py:78` (identical in `routes_designs.py:226`, `routes_workorders.py:38`)
- §2.8 priority 10 — revise — mismatch — said "on assembly release"; `ERR_INSPECTION_NOT_PASSED` also guards **sealing** — `routes_assemblies.py:205`
- §2.8 priority 24 — revise — mismatch — release does **not** test `ERR_ASSEMBLY_EMPTY`, and `ERR_DOCUMENTATION_INCOMPLETE` also fires at an approving review; "four operations" → five — `routes_assemblies.py:218`, `routes_docs.py:119`
- §2.4 ¶3 — revise — ambiguity — `current_utc` is mandatory and the sole input; `data` carries exactly two members; first call's `previous_utc` is the initial instant — `routes_clock.py:17-24`
- §3.6 ¶1 — revise — mismatch — field-validation order is `chamber_code`, `slot_capacity`, `coating_type` (PRD listed capacity last); plus `chamber_code` non-unique, capacity unbounded — `routes_coating.py:24-26`
- §3.6 — insert — ambiguity — all five loading fields mandatory; listing order is both the FK order and the field order; window minutes gate the booking only, no stored minutes and no capacity meter — `routes_coating.py:60-78`
- §3.6 — insert — ambiguity — every spectral element must be a JSON object, readings validated in array order, `wavelength_nm` before `reflectance_pct`, both non-negative and unbounded above, validation precedes the state gate, stored readings reduced to exactly two members — `routes_coating.py:151-165`
- §3.6 — revise — mismatch — the `COATING → COATED` advance is conditioned on the order standing in `COATING`; on FAIL the order is not written at all — `routes_coating.py:186-191`
- §3.6 — revise — mismatch — both strip-path work-order writes are conditioned on `COATING`/`COATED`; the strip-limit scrap fires from `COATED` too, and any other state leaves the order untouched — `routes_coating.py:207-222`
- §3.7 — insert — ambiguity — `destination_country` exactly two `A`–`Z` chars with no country-list check; `end_use_statement` 1–1000, null when omitted; field order; design state not consulted — `routes_export.py:26-37`
- §3.7 — insert — ambiguity — `decision` mandatory, `license_number` 1–60 and optional even on approval; field order — `routes_export.py:69-79`
- §3.7 — insert — ambiguity — denial hop one records `decided_by_user_id` like an approval; `license_number` and `decision_note` stay null (a supplied number is validated then discarded) — `routes_export.py:87-89`
- §3.7 — insert — ambiguity — `revocation_reason` 1–500 and sole input; `license_number` and `decided_by_user_id` left as the approval recorded them — `routes_export.py:101-108`
- §3.8 ¶1 — revise — mismatch — PRD implied a released design; impl never consults `design_status`. Also `assembly_code` non-unique, both fields mandatory in order — `routes_assemblies.py:22-24`
- §3.8 — revise — mismatch — "Four gates" → "Three gates" on kitting (only three are coded and only three were described) — `routes_assemblies.py:81-92`
- §3.8 — insert — ambiguity — the assembly's `assembly_status` and the order's `compliance_status` are never consulted on kitting; kitting refreshes `updated_at`/`version` but does not recompute the roll-up; 201 — `routes_assemblies.py:94-105`
- §3.8 — insert — ambiguity — `cement_lot_code` and `mount_code` mandatory, 1–40; state gate precedes the emptiness gate; mounting has no emptiness gate — `routes_assemblies.py:134-160`
- §3.8 — insert — ambiguity — the released-component sweep (p13) runs before the emptiness gate (p24) and is vacuous on an empty assembly, so the two orders are indistinguishable; `VOIDED` components neither block nor contribute — `routes_assemblies.py:172-181`
- §3.9 — revise — mismatch — PRD stated waiver order SoD → waivability → justification; impl (and §2.8) run justification → waivability → SoD. Also justification max 2000, checked before the `FAILED` state gate — `routes_inspection.py:68-83`
- §3.9 — insert — ambiguity — `assembly_id` is the sole package input; uniqueness holds whatever the existing package's status; the assembly's `assembly_status` is never consulted — `routes_docs.py:26-33`
- §3.9 — insert — ambiguity — `document_reference` 1–200, both fields mandatory in order; state gate precedes the duplicate check; answers **200** (not 201) with the package as `data` — `routes_docs.py:60-78`
- §3.9 — insert — ambiguity — `decision` mandatory, `review_note` 1–1000 in that order; `last_review_note` is overwritten (to null when omitted) on every review — `routes_docs.py:106-128`
- §3.9 — revise — mismatch — "Four further gates" omitted the inspection gate impl evaluates between licence approval and documentation; now five, in order, plus an explicit note that neither component count nor wavefront is re-tested — `logic.py:400-411`
- §4 — revise — mismatch — `POST /optics/assemblies` row: "against a released design" → "against a design, whatever state that design stands in" — `routes_assemblies.py:22`

### Highest-impact findings

The three largest divergences were **stated-order / stated-count errors the PRD carried**, not silences: the inspection waiver's three conditions were documented in exactly reverse order from both the implementation and §2.8; final release documented four gates and silently dropped the inspection gate; and §2.8 priority 24 claimed `ERR_ASSEMBLY_EMPTY` guards assembly release, which `release_gate` does not test at all. These are doc-generator Zero-Silence/ordering-fidelity misses worth feeding back upstream.

### Orchestrator verification

- `wc`: PRD_COMPLETED.md = 473 lines / 134,428 bytes; heading count 28, identical to PRD.md → no sections added or lost.
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` → differs, so the scan is not a no-op (guards the known "byte-identical means the scan never ran" failure).
- `tail` → still ends on the closed §5 table row `| ERR_CLOCK_NOT_MONOTONIC | 422 |`; not truncated.
- Implementation and test artifacts were **not** modified by any Step 9 pass: every `workspace/implementation/*` mtime is ≤ 11:29 and every `test_suite/`/`test_helpers/` mtime is ≤ 12:57, all earlier than the 13:02 final passing sweep. The eight `results.{1..8}.json` (148/148 each) therefore remain a valid attestation of the delivered implementation. No re-sweep was needed.

**Pipeline complete.** `workspace/PRD_COMPLETED.md` written; all nine steps done.

# Worklog — task_2585_sterile_injectable_fill_finish_contract_manufacturing

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2585_sterile_injectable_fill_finish_contract_manufacturing` and its `workspace/` subdirectory. Index 2585 was pre-assigned by the orchestrating command; no scan of `./tasks/` was performed and no index was auto-allocated (other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-03T16:46:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Files** (`/home/ubuntu/github/CodingPRD/tasks/task_2585_sterile_injectable_fill_finish_contract_manufacturing/`)
- `SCAFFOLD.yaml` — 3250 lines / 169 KB (§1.0–§1.7 only; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2188 lines / 146 KB (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4686 lines / 312 KB (single key `scaffold_corner_design`)

**§1.0–§1.7 counts** — `domain_name: sterile-fill-finish-cmo`, `api_prefix: ""`, `difficulty_level: expert_plus`, archetype `compliance_audit` / `temporal_windowing`, flat topology, cyclic state machines, `segregation_of_duties` role model, `immediate` consistency, layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation.
- 13 entities, 13 state machines, 2 concurrency rules, 13 calculations, 47 validation rows (ascending priorities 10→96), 61 endpoints, 57 errors, 6 roles (ProgramManager, ProductionSupervisor, MicrobiologyAnalyst, QaReviewer, QualifiedPerson, ClientRepresentative — the last `entity_backed:ClientProject`).

**§1.8** — all 9 §0.5 difficulty rules × 2 instances = **18**: dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.

**§1.9** — all 9 taxonomy sections, **88 instances** = 62 full `test_recipe`s + 26 `excluded_because` stubs: entities 13, state_machines 18, calculations 14, validations 19, endpoints 6, errors 2, rbac 6, cross_cutting_complexity_layers 9, consistency_model 1.

**Audits**
- `scaffold_lint.py`: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (61 endpoints, 13 entities, 18 + 62 instances, **1464 calls scanned**).
- Error reachability: **57/57** §1.6 error codes are triggered by at least one §1.8/§1.9 test (verified programmatically; zero uncovered).
- 106 instance names globally unique across both design files; all 26 stub `difficulty_instance` refs resolve to real §1.8 names; **0 unbound `${...}` placeholders** across every setup/trigger/assert.

**Two scaffold repairs made during generation** (both in `SCAFFOLD.yaml`, to keep §1.6 fully reachable):
- An entities corner initially cited a non-existent `ERR_MEDIA_FILL_SUITE_MISMATCH`; replaced with a reservation cross-project instance grounded in `validations[priority=80]` / `ERR_COMPONENT_LOT_PROJECT_MISMATCH` (409).
- `ERR_BR_REVIEW_NOT_CLOSED` was unreachable at priority 82 because `quality_status` can only reach QP_REVIEW through a review close that already requires 0 open findings, so priority 45 always pre-empted it. Renumbered to **priority 43** (block physically moved so all 47 priorities stay ascending) with check text making the ordering intent explicit; both it and `ERR_BATCH_QUALITY_STATE_INVALID` are now independently triggered.

## Step 3: Copy shared files — 2026-09-03T16:47:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T17:05:00.000Z

PRD generation complete.

## Deliverable

`workspace/PRD.md` — **441 lines / 103,670 bytes**, built by one `Write` plus nine `cat >> ... <<'PRDEOF'` heredoc appends (no single call approached the 64k output cap). `tail -40` confirms the file ends on the last row of the §5 error table — a completed final section, no mid-sentence truncation, and no audit footer.

The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced. All worked examples in the prose (21560 component demand; 8418 vs 8274 releasable units; 480960 -> 24048 -> 505008 -> 15150 -> 489858 fee chain; 100 vs 47 readiness) are the ones carried in `SCAFFOLD.yaml`'s own `formula` blocks.

## Section list

- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Role-Based Access Control · 2.2 API Response Structure · 2.3 Pagination · 2.4 Record Identity, Audit Stamps and the Logical Clock · 2.5 Suite Posture: The Derived Aseptic Gate · 2.6 Cascade Discipline and Compensating Ledgers · 2.7 Optimistic Concurrency on Shared Parents · 2.8 Segregation of Duties · 2.9 Numeric Precision and Pinned Evaluation Order · 2.10 Request Evaluation Order · 2.11 Path Resolution and Sub-Resource Reads
- `## 3. Business Logic & Workflows` — 3.1 Project Intake and Technology Transfer · 3.2 Cleaning Validation and Aseptic Process Simulation · 3.3 The Operator Roster · 3.4 Component Supply · 3.5 Booking Time in a Shared Suite · 3.6 Setup, Aseptic Fill and In-Process Controls · 3.7 Excursions, Deviations and CAPA · 3.8 Batch Record Review and QP Certification · 3.9 Audits, Readiness Scoring and Unit Accounting
- `## 4. Endpoint Definitions` — intro paragraph on 201-vs-200 plus a 4-column table, 61 rows
- `## 5. Error Code Catalogue` — 2-column table, 57 rows

## Coverage counts (mechanically verified against SCAFFOLD.yaml)

| Scaffold input | Count | In PRD |
| --- | --- | --- |
| §1.1 entities | 13 | 13 |
| §1.1 entity field names | 96 | 96 backticked (0 missing) |
| §1.5 endpoint input identifiers (`request_body`/`query_params`/`path_params`) | 78 (18 endpoint-only) | 78 backticked (0 missing) |
| §1.5 endpoints | 61 | 61 rows in §4 with exact method+path+roles; all 61 also reachable from §3 prose |
| §1.6 errors | 57 | 57 in §1–3 prose **and** 57 in §5 with matching HTTP status |
| §1.4 validations | 47 | all 47 mapped errors present in §1–3 |
| §1.3 calculations | 13 | 13, incl. both dual-variant pairs and all pinned rounding orders |
| §1.2 state machines | 13 | 13; every declared state and transition endpoint state named in §1–3 (0 missing) |
| concurrency rules | 2 | both, with `expected_suite_version`/`expected_component_lot_version` and 412 |
| roles | 6 | all 6, plus the `entity_backed` `ClientRepresentative` scoping |

Note on HTTP statuses: the catalogue includes two `402` errors (`ERR_PROJECT_UNIT_BUDGET_EXCEEDED`, `ERR_SUITE_CAPACITY_EXCEEDED`) — carried through verbatim from the scaffold rather than normalised to 409/422.

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** 96/96 `entities[].fields[].name` and 78/78 endpoint input identifiers (18 of which appear in no entity: `adjudication_rationale`, `cancellation_reason`, `classification_rationale`, `decision_note`, `expected_component_lot_version`, `expected_suite_version`, `f0_minutes`, `findings_note`, `investigator_note`, `release_rationale`, `residue_ug_per_swab`, `revoke_reason`, `to_iso8601`, `to_stage`, `variant`, `outcome`, `limit`, `offset`) appear verbatim inside backticks. Verified by extracting every identifier token from every backtick span in PRD.md (fenced §2.2 blocks excluded) and differencing against the scaffold.

**Contract 2 — Rule Coverage: PASS.** All 47 validation rules with their priority-ordered evaluation ladder in §2.10 and their `applies_to` scopes enumerated there; both OCC rules in §2.7; every state transition and its side-effect set, including the depth-5 media-fill-failure cascade and all five compensating ledgers, in §2.6 and §3.2–3.8; all field-level defaults stated at the creating endpoint; sibling-branch symmetry written at equal density for media-fill read/adjudicate (PASSED/INVESTIGATION_REQUIRED/FAILED), CAPA decide (APPROVED/REJECTED), QP release (RELEASE/REJECT/QUARANTINE) and audit host (HOSTED/DEFERRED); all 13 calculations reconstructible step-for-step with pinned rounding order and no symbolic notation.

**Contract 3 — §3 Path Purity: PASS.** Zero backtick spans in §3 begin with `/`, are a bare HTTP method, or combine method+path (checked programmatically over all backtick tokens between the §3 and §4 headings). All path-bearing material — the priority ladder, the `applies_to` enumerations, the two OCC endpoints and the `ClientRepresentative`-scoped operations — lives in §2, where paths are permitted.

Also verified: §2.2 is byte-identical to `section-2.2-response-structure.md` (diff clean), and no fuzzy-language or pseudocode tokens appear (only the two §2.2 JSON fences exist in the whole document).

**Orchestrator anti-truncation check (independent):** `wc -l` = 441; `tail -12` ends on `| ERR_REQUIRED_IPC_MISSING | 422 |`, a complete final table row of §5; all five `##` sections present in order. PRD accepted without regeneration.

## Step 5: Generate unit tests — 2026-09-03T18:34:19.000Z

Queue B is complete; the full suite is generated, compiles, and collects 98 tests.

## Files written (task root, never under `workspace/`)

`/home/ubuntu/github/CodingPRD/tasks/task_2585_sterile_injectable_fill_finish_contract_manufacturing/`

**Stage 1 — `test_helpers/`** (2,986 lines): `__init__.py` 58, `api_client.py` 401, `api_errors.py` 156, `assertions.py` 662, `constants.py` 184, `factories.py` 521, `fixtures.py` 966, `test_users.py` 138, `types.py` 461.

**Stage 2 — `test_suite/`** (5,667 lines incl. `conftest.py` 108):

| file | lines | tests | queue |
|---|---|---|---|
| test_01_dual_variant_calc.py | 201 | 4 | A |
| test_02_combinatorial_formula.py | 199 | 4 | A |
| test_03_non_linear_state_machine.py | 157 | 4 | A |
| test_04_transitive_cascade.py | 172 | 4 | A |
| test_05_priority_pair_validation_conflict.py | 173 | 4 | A |
| test_06_boundary_precision_check.py | 158 | 4 | A |
| test_07_cross_entity_state_dependency.py | 188 | 4 | A |
| test_08_resource_temporal_overlap.py | 198 | 4 | A |
| test_09_compensating_invariant.py | 186 | 4 | A |
| test_10_entity_persistence_and_reads.py | 545 | 13 | B |
| test_11_state_machine_transitions.py | 738 | 13 | B |
| test_12_derived_calculations.py | 283 | 6 | B |
| test_13_validation_gates.py | 765 | 14 | B |
| test_14_endpoint_contracts.py | 242 | 4 | B |
| test_15_error_catalogue.py | 215 | 2 | B |
| test_16_role_authorization.py | 327 | 6 | B |
| test_17_concurrency_and_consistency.py | 251 | 4 | B |

## Coverage tally (machine-verified against both design yamls)

- **Queue A (§1.8):** 9 rules x 2 instances = 18 instances, 36 tests, every instance >= 2 tests. No instance skipped.
- **Queue B (§1.9):** 88 instances, 26 of them `excluded_because:` stubs (state_machines 5, calculations 8, validations 5, endpoints 2, cross_cutting 6) which emit nothing. **All 62 non-stub instances translated, one test each** — entities 13, state_machines 13, calculations 6, validations 14, endpoints 4, errors 2, rbac 6, cross_cutting 3, consistency_model 1.
- 98 tests / 98 `Design:` tags, one per test, zero malformed, zero dual-tagged, zero pointing at a stub or at a non-existent name, and no non-stub instance left uncovered.
- All 129 `PRD <section>: "..."` docstring quotes verified by literal substring match against `workspace/PRD.md` (misses: 0), em dashes, arrows and markdown emphasis intact.
- `python3 -m py_compile` clean on all 26 generated files; `pytest test_suite --collect-only -q` -> **98 tests collected**; pyflakes reports no unused names in any test file (only intentional re-exports in `test_helpers/__init__.py`). `__pycache__` removed. Nothing was read or written under `workspace/implementation/`.

## Assertions deliberately weakened or dropped (PRD-first filter)

Two sub-assertions in the design contradict or outrun the PRD; the instances were still translated, with only the offending assertion adjusted:

1. `Corner/consistency_model/every_derived_field_is_visible_in_the_same_response` pins `investigation_status == 'REQUIRED'`, but PRD 3.7 says "an `ALERT` or `ACTION` sample is stamped `OPEN`". Asserted `OPEN`.
2. `Corner/cross_cutting_complexity_layers/*` (stale suite version) and `entity_version_increments_once_per_successful_write` pin absolute suite versions (3 -> 4 -> 5) that presume granting an operator qualification does **not** bump the suite row. PRD 3.3 says the grant "recomputes the suite's `qualified_operator_count` and its `posture`" while PRD 2.4 bumps `version` on "every mutation of that row" — so the absolute ladder is not uniquely derivable. Kept the derivable parts (created 1, media-fill read-out 2, cleaning validation 3, qualification 1->2, project 1->4, batch 1) and asserted scheduling's suite bump relatively (`fresh == stale + 1`, `after == fresh + 1`) plus the pinned ledgers (540 -> 960, 43120, lot 30000 -> 19440 with version 2 -> 3).

Also fixed during this pass: every `ApiErrorId.ERR_*` / `.value` reference across the suite (55 + 3 sites) — `api_errors.py` drops the `ERR_` prefix and stores plain strings, so those would have raised `AttributeError` at runtime.

**Orchestrator layout check:** `test_helpers/` and `test_suite/` are at the task root (30 files total); `find workspace -maxdepth 2` shows no stray copy under `workspace/`. No move needed.

## Step 6: Generate implementation — 2026-09-03T17:44:50.000Z

Implementation complete and verified.

## Files (`workspace/implementation/`, 3828 lines total)

| File | Lines | Role |
|---|---|---|
| `app.py` | 78 | Flask factory, 9 blueprints, 404/405/500 envelope handlers, `0.0.0.0:$PORT` (default 10000), `threaded=True` |
| `common.py` | 193 | `ApiError`, logical clock (startup exactly `2026-08-01T00:00:00Z`), global `RLock`, ROUND_HALF_UP/ceiling helpers, response envelope |
| `store.py` | 163 | 13 in-memory dicts (empty at boot), `new_row`/`touch`/`set_raw`, deterministic `by_created` ordering, query helpers |
| `validate.py` | 248 | 16 enum tuples, field descriptors, shape-before-enum body parsing, pagination |
| `auth.py` | 142 | `@endpoint(roles, crep_scope)` — 401 missing/unknown role, 403 role, client-rep ownership, lock acquisition, error mapping |
| `calc.py` | 436 | All PRD §2.9 formulas: EM limits/classification/risk index, posture, committed minutes, component demand, IPC results, provisional/final releasable units, QP fee tiers, deviation risk, dual-variant readiness |
| `serialize.py` | 254 | 13 entity serializers with derived fields; verbatim echo of client-supplied instants |
| `services.py` | 324 | FK 404s, lot availability draw/restore, reservation release/consume, suspend/restore cascades, media-fill qualify/fail, critical-deviation depth-5 cascade, quarantine close, clock-move lapse/expiry |
| `listing.py` | 43 | Filter + paginate + envelope |
| `routes/` | 1939 | `projects.py` 195, `suites.py` 117, `mediafills.py` 178, `personnel.py` 134, `lots.py` 212, `batches.py` 471, `quality.py` 231, `qa.py` 290, `audit.py` 111, `__init__.py` 0 |
| `start.sh` / `requirements.txt` | 7 / 1 | Guarded pip install then `exec python3 app.py` (foreground, chmod +x) |

## Coverage
- **61 routes** registered — one-for-one with the PRD endpoint table (verified via `url_map` introspection).
- **13 entity collections**: client projects, filling suites, media fills, personnel qualifications, component lots, component reservations, batch orders, in-process checks, EM samples, deviations, batch record reviews, QP release decisions, audit engagements.
- 57 error codes wired through the 17-rung evaluation order (PRD §2.10), including 412 optimistic-concurrency on suite and component-lot versions and segregation-of-duties on `X-User-ID`.
- Storage is in-memory dicts only — no SQLite, no disk JSON, no `/tmp` cache, zero seeded rows (fresh boot returns `total_count: 0`).

## Smoke test — PASS
75-assertion end-to-end script on port 18585 covering suite -> project -> tech transfer -> media fill -> operator qualification -> cleaning validation -> component lots/reservations -> batch lifecycle -> IPCs -> batch record review -> QP release -> EM excursion -> CAPA loop -> clock move -> auth/pagination/404 rungs. All PRD worked examples reproduced exactly: `component_demand_units` 21560, `committed_minutes` 540, provisional 8418, final 8274, `expected_reject_units` 22, `variant_delta_units` 144, QP fee `489858`, readiness (GMP_AUDIT) 100, deviation risk 5 / 35 / 45 escalation, media-fill validity `2027-01-31T00:00:00.000Z`, 2 lapsed qualifications on clock move.

The single mismatch was in my expectation, not the code: EM risk index for a grade-B `PERSONNEL_GLOVE` at cfu 5 returned **65**, which PRD line 255 confirms is correct (core `1 x 20 x 2 = 40`, rounded, plus the unrounded 25-point glove surcharge).

Also verified: `python3 -m py_compile` clean on all 19 `.py` files; a second cold boot from `start.sh` returned an empty store again (per-test-server isolation safe). Both smoke servers were killed by their own recorded PIDs (3924884, 3944572) — no pattern kill was used; port 18585 is free and `__pycache__` was removed.

## Step 7: Run tests and iterate — 2026-09-03T18:55:40.000Z

All 8 parallel rounds green: 98/98 each.

## Summary

**Iterations run:** 2 (sweep -> 3 deterministic failures -> 3 test-layer fixes -> sweep -> 98/98 x 8).

Round 1: every one of the 8 rounds reported 95/98 with the *identical* three failures — no flakiness, no reaping (no `Terminated` in logs, rounds finished independently).

**Tests deleted:** none. All three failures survived STEP 1 (PRD verbatim-covers and uniquely determines the rules in question, except for the one precedence case below).

**Fixes applied to `test_suite/`** (all three were STEP 2 test bugs — the implementation was PRD-faithful in every case):

1. `test_suite/test_16_role_authorization.py` — `test_a_sponsor_is_scoped_through_the_owning_project_not_the_path` created its second sponsor with `dosage_form="SYRINGE"`. PRD §3.1 line 167: dosage_form "is either `VIAL` or `PRESYRINGE`" — `SYRINGE` is a *component type*, not a presentation. The implementation's 422 `ERR_INVALID_ENUM_VALUE` was correct; changed the setup to `PRESYRINGE`.

2. `test_suite/test_17_concurrency_and_consistency.py` — `test_a_second_batch_must_be_computed_from_a_fresh_view_of_the_suite` used `build_program`'s default `reserved_unit_budget=30000` while asserting two worked-example batches land `committed_demand_units == 2 x 21560 == 43120`. PRD §3.5 line 229 makes `ERR_PROJECT_UNIT_BUDGET_EXCEEDED` (402) mandatory when demand + committed exceeds the budget, so the second create was correctly refused. Setup now passes `reserved_unit_budget=2 * constants.WORKED_COMPONENT_DEMAND_UNITS`; the PRD-required ceiling check was left untouched.

3. `test_suite/test_13_validation_gates.py` — `test_completeness_is_checked_before_uniqueness_when_opening_a_review` pinned `ERR_BR_REVIEW_ALREADY_EXISTS` for a second review create. Genuine PRD ambiguity: §3.7 names that error for "a second attempt", but the *same* section states "Opening the review advances the batch `IN_PROCESS_REVIEW -> BR_REVIEW`", and §2.10 orders state-machine guards at rung 12 ahead of the uniqueness rung at 16 — so a faithful reader gets `ERR_BATCH_QUALITY_STATE_INVALID` instead. Both readings are articulable, so per the permitted exception the exact-error assertion was relaxed to `validate_error_is_one_of([BR_REVIEW_ALREADY_EXISTS, BATCH_QUALITY_STATE_INVALID])` with the HTTP 409 status still asserted exactly. The test's covered first half (`ERR_REQUIRED_IPC_MISSING`, 422) was kept unchanged.

**Fixes applied to `test_helpers/`:** none — the fixture defaults are individually PRD-legal; only the one call site needed a budget large enough for two batches.

**Fixes applied to `implementation/`:** none. No implementation defect was found; all three failures were test artifacts asserting against a PRD-correct server.

Sweep artifacts: `workspace/implementation/results.1.json` ... `results.8.json` (all complete, `passed == total == 98`), log at `workspace/sweep.log`.

**Orchestrator independent verification:** all 8 `results.*.json` exist (each ~31 KB, timestamped 18:45) and parse to `passed=98 / total=98 / failed=0`. Sweep confirmed real, not claimed.

**Step 8 skip-condition adjudication (orchestrator):** Step 7 ran 2 iterations with 3 `test_suite/` fixes, so the skip condition (0 iterations beyond baseline) does NOT hold — Step 8 runs. Note that `implementation/` fixes were 0; the Step 8 subagent is therefore pointed at the three test-layer fixes as PRD-ambiguity evidence, chiefly item 3 (a genuine PRD precedence silence between the BR-review uniqueness rung and the batch state-machine rung) and items 1–2 as candidates that may prove to be pure fixture/call-site bugs requiring no PRD edit.

## Step 8: Finalize PRD — 2026-09-03T19:06:09.000Z

Done. `workspace/PRD_FINALIZED.md` written as a one-line patch of PRD.md.

**Counts:** PRD.md 441 lines / 103,670 B -> PRD_FINALIZED.md 441 lines / 104,223 B. Line delta 0 (0.0%); byte delta +553 (+0.53%). Exactly one line changed (line 275).

**Changes:**
- §3.8 (line 275) — revise — kept the existing `ERR_BR_REVIEW_ALREADY_EXISTS` sentence verbatim and appended that the uniqueness gate is rung 16 of §2.10 and so is reached only after the state gates, making the ordinary second-open attempt (batch already advanced to `BR_REVIEW` by the first open) a rung-12 `ERR_BATCH_QUALITY_STATE_INVALID` (409); also pinned that the uniqueness lookup ignores the existing review's status. Impl: `implementation/routes/qa.py:184-188` (quality gate) vs `implementation/routes/qa.py:203-207` (uniqueness) and `implementation/routes/qa.py:225` (`quality_status = "BR_REVIEW"` on create).

**Items needing no PRD edit (confirmed, not manufactured):**
- Item 1 (`dosage_form`) — PRD line 167 already pins `VIAL`/`PRESYRINGE`; `implementation/validate.py:22` `DOSAGE_FORMS = ("VIAL", "PRESYRINGE")` matches, and `SYRINGE`/`PLUNGER` appear only as component types (`implementation/calc.py:61`, PRD lines 209/227). Pure fixture bug.
- Item 2 (unit budget) — PRD line 229 already pins the mandatory ceiling; `implementation/routes/batches.py:156-161` implements `committed + demand > reserved_unit_budget -> 402` exactly. Pure call-site bug.

**Pre-edit search log (the one edit):**
- (a) Subject: precedence between the quality-axis state gate and the review-uniqueness gate at `POST /batch-record-reviews`, plus the reachability/semantics of `ERR_BR_REVIEW_ALREADY_EXISTS`, plus every writer of `batch.quality_status`.
- (b) Paths enumerated (grepped `quality_status`, `BR_REVIEW_ALREADY_EXISTS`, `review_of_batch` across all of `implementation/`, then read each hit): `routes/qa.py` `create_review` (172-227), `close_review` (267-289), `record_findings` (248-264); `routes/batches.py:351-352` (fill start `PENDING -> IN_PROCESS_REVIEW`, guarded on `PENDING`), `:393-394` (cancel -> `REJECTED`), `:424-427` + `:450-456` (qp-release gate and the three dispositions); `services.py:133-134` (suspend -> `QUARANTINED`), `:235-237` + `reopen_review` (ACTION-excursion demotion `QP_REVIEW -> BR_REVIEW`, reopens a `CLOSED` review), `:262-264` (critical-deviation cascade -> `QUARANTINED`), `:282-289` (`maybe_close_quarantine_loop` -> `BR_REVIEW`); `store.py:143-147` (`review_of_batch`, status-agnostic, earliest by `created_at`). Result: no path ever returns `quality_status` to `IN_PROCESS_REVIEW` after the first review opens, and reviews are created nowhere but `create_review`.
- (c) Wording adjustment: my first draft enumerated the other post-`IN_PROCESS_REVIEW` states (`QP_REVIEW`, terminal, `QUARANTINED`) as also yielding `ERR_BATCH_QUALITY_STATE_INVALID`. The cancel path (`routes/batches.py:393-394`) leaves `production_status = CANCELLED`, where the rung-12 production gate (`routes/qa.py:179-183`) fires first with `ERR_BATCH_PRODUCTION_STATE_INVALID`, so that enumeration would have been a false universal. I narrowed the claim to the `BR_REVIEW`-after-first-open case and left the remaining states governed by §2.10's existing rung order.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (275), as reported; file still 441 lines and ends on the complete final §5 error-table row.

## Step 9: Complete PRD — 2026-09-03T19:35:00.000Z

**Orchestrator decision (recorded per the autonomy rule):** Step 9 was run as **three sequential file-partitioned passes** over `implementation/` rather than one monolithic scan. A single-agent full-repo scan has a known failure mode where the agent copies PRD_FINALIZED.md and returns a byte-identical PRD_COMPLETED.md without ever having scanned; partitioning forces each pass to own a bounded, checkable slice and to compose its edits onto the prior pass's file. Pass 1 owned the `cp` and file creation; passes 2 and 3 edited in place. Each pass was told which lines earlier passes had touched so edits composed instead of colliding.

Partitions: **pass 1** = auth.py, validate.py, routes/{projects,suites,mediafills,personnel}.py · **pass 2** = routes/{lots,batches}.py, calc.py (demand/occupancy/IPC/releasable), store.py · **pass 3** = routes/{quality,qa,audit}.py, services.py, app.py, serialize.py, calc.py (EM limits/classification/risk, deviation risk, suite posture, final releasable stamping, QP fee prose).

### Pass 1 (auth/validate/projects/suites/mediafills/personnel)

Created `PRD_COMPLETED.md` from `PRD_FINALIZED.md` (441 lines / 104,223 B) -> after pass: 441 lines / 109,270 B. 19 lines modified, 0 added/removed, no renumbering; §4 endpoint table and §5 error catalogue verified untouched.

**Counts: 19 ambiguity-pins, 3 mismatch-revisions.**

- §2.1 — revise — ambiguity — whitespace-only auth headers treated as empty; role match exact/case-sensitive — `auth.py:49,55`
- §2.1 — insert — ambiguity — rung-4 ownership on `POST /audit-engagements` also fails on absent/null `client_project_id` (runs ahead of shape validation); batch-addressed pair falls through to `ERR_BATCH_ORDER_NOT_FOUND` — `auth.py:98-107`
- §2.3 — insert — ambiguity — present-but-empty `limit`/`offset` rejected; whitespace and leading sign tolerated — `validate.py:219-247`
- §2.3 — insert — ambiguity — `created_at` ties broken by ascending creation sequence (total ordering) — `store.py:69-76`
- §2.3 — insert — ambiguity — filter values compared as strings, never enum-validated; null field matches nothing; `total_count` is post-filter — `listing.py:14-38`
- §2.4 — revise — **mismatch** — 3-fractional-digit formatting applies only to server-generated instants; client-supplied instants echoed byte-for-byte, naive read as UTC, offsets normalised, unparseable -> rung-6 `ERR_INVALID_REQUEST` — `serialize.py:18-22`, `common.py:50-81`
- §2.10 rung 6 — revise — ambiguity — booleans never satisfy int/num fields; wrong array element type, string length bounds, declared cross-field inequalities are rung 6; malformed/non-object body treated as `{}` — `validate.py:118-190,192-207`
- §2.10 rung 12 — revise — **mismatch** — production-axis guard set also carries cleaning-validation and media-fill-execution refusals while a suite batch is `FILLING` — `suites.py:103-108`, `mediafills.py:71-77`
- §3.1 — insert — ambiguity — `release_rationale` required, non-empty, unbounded — `projects.py:137`
- §3.2 — insert — ambiguity — `changeover_minutes_product_change` int >= 0; cross-field violation is `ERR_INVALID_REQUEST` (400) reached before `suite_code` uniqueness — `suites.py:28,36-40`
- §3.2 — insert — ambiguity — cleaning `molecule_name` 1-80 chars; `residue_ug_per_swab` unbounded (zero/negative accepted) — `suites.py:92-95`
- §3.2 — revise — ambiguity — `FILLING`-batch refusal of cleaning validation is `ERR_BATCH_PRODUCTION_STATE_INVALID` — `suites.py:105`
- §3.2 — insert — ambiguity — new media fill has `read_at` and `outcome_reason` null; `scheduled_run_date` unconstrained against the clock — `mediafills.py:38-46`
- §3.2 — revise — ambiguity — `units_filled` >= 0; empty/non-string `participating_operator_names` -> `ERR_INVALID_REQUEST` (400); `FILLING` refusal is `ERR_BATCH_PRODUCTION_STATE_INVALID` and precedes the simulation status check — `mediafills.py:86-96`
- §3.2 — insert — ambiguity — `contaminated_units` >= 0, need not be <= `units_filled` — `mediafills.py:130`
- §3.2 — insert — ambiguity — an ineligible requalification is not an error: simulation still reaches `PASSED` but suite left untouched with no version bump (same for adjudicated passes) — `services.py:186-193`
- §3.2 — insert — ambiguity — `adjudication_rationale` non-empty, no maximum — `mediafills.py:166`
- §3.3 — revise — **mismatch** — one-record-per-operator-per-suite is a convention, not an enforced uniqueness constraint — `personnel.py:30-57`
- §3.3 — insert — ambiguity — cited `media_fill_id` must exist but need not belong to the record's `suite_id` — `personnel.py:36-37`
- §3.3 — insert — ambiguity — grant's `expires_on` re-check yields `ERR_INVALID_WINDOW` (422) after the `ASEPTIC_INTERVENTION` evidence gate — `personnel.py:111-116`
- §3.3 — insert — ambiguity — `revoke_reason` required, non-empty, unbounded — `personnel.py:127`
- §3.9 — revise — ambiguity — absent `variant` yields `ERR_INVALID_ENUM_VALUE` (not `ERR_INVALID_REQUEST`), after path resolution — `projects.py:168-170`

Pass 1 noted `auth.py`'s catch-all `except Exception -> ERR_INVALID_REQUEST` 400 as a defensive process-keepalive path, not a specified behavior; deliberately not pinned.

### Pass 2 (lots/batches/calc/store)

441 lines / 109,270 B -> 441 lines / 113,984 B; all edits in-paragraph, no lines added or removed.

**Counts: 12 ambiguity-pins, 3 mismatch-revisions.**

- §2.10 rung 7 — revise — **mismatch** — PRD claimed `ERR_INVALID_ENUM_VALUE` also applies to `GET /batch-orders/{id}/unit-accounting`; that read takes no query param and no body and never raises it — `routes/batches.py:241-266`
- §2.10 rung 12 — revise — **mismatch** — added the production-axis guard's coverage of a QP `RELEASE` signed against a batch that has not reached `FILLED` (appended to pass 1's clause) — `routes/batches.py:419-423`
- §3.5 occupancy/capacity — revise — **mismatch** — PRD asserted "every window is a whole number of minutes so no truncation arises"; impl floors a non-whole window and feeds the truncated figure to the ceiling test — `calc.py:177-179`, `common.py:88-90`, `routes/batches.py:163`
- §3.4 — insert — ambiguity — `sterilization_expiry` not clock-checked at receipt; `lot_code` uniqueness spans all projects and all lot statuses (a `REJECTED`/`EXPIRED` lot still holds its code); no project-state gate — `routes/lots.py:30,39-47`
- §3.4 — insert — ambiguity — `f0_minutes` required unbounded number, evidential only, not persisted onto the lot — `routes/lots.py:97`
- §3.4 — revise — ambiguity — lapsed-hold-time refusal pinned to `ERR_COMPONENT_LOT_STATE_INVALID`, reached after the PENDING test — `routes/lots.py:105-109`
- §3.4 — insert — ambiguity — reservation create resolves `batch_order_id` before `component_lot_id`; batch `production_status` and project `status` not gated at all — `routes/lots.py:136-138`
- §3.5 — insert — ambiguity — scheduling body FKs resolve project -> suite -> qualification for the rung-9 404 — `routes/batches.py:71-73`
- §3.5 — insert — ambiguity — `changeover_minutes_applied` predecessor tie-break continues past `created_at` to later order of creation — `calc.py:240`
- §3.5 — insert — ambiguity — batch birth: `filled_unit_count`/both releasable figures/`release_fee_cents` born null, `quarantined_unit_count` 0 and never written by any endpoint; project row not written so its `version` does not move (only the suite's does) — `routes/batches.py:183-195`
- §3.6 — insert — ambiguity — start-fill quality-axis advance fires only when `quality_status` is still `PENDING` (a restored `QUARANTINED` batch keeps it); one `version` bump either way — `routes/batches.py:351-353`
- §3.6 — insert — ambiguity — `filled_unit_count` above `target_fill_units` is `ERR_INVALID_REQUEST` (400) at rung 6, ahead of the production-state check — `routes/batches.py:364-365`
- §3.6 — revise — ambiguity — both cancellation ledger decreases are rederivations only (neither project nor suite row written, no `version` move); `QUARANTINED -> REJECTED` made explicit — `routes/batches.py:392-396`
- §3.6 — insert — ambiguity — `cancellation_reason` required non-empty string, unbounded, not stored on the batch — `routes/batches.py:386`
- §3.8 RELEASE bullet — insert — ambiguity — the `FILLED` requirement is RELEASE-only and evaluated at rung 12 ahead of the quality-axis check — `routes/batches.py:419-428`
- §3.9 — insert — ambiguity — null stored fields render as 0, so an unfilled batch reports 0 for `filled_unit_count`, both releasable figures, `variant_delta_units` and `expected_reject_units` — `routes/batches.py:249-265`

Pass 2 re-verified `calc.in_process_check_result` against §3.6's rounding-then-compare prose (matches, no change) and `calc.qp_release_fee_cents`/`max_open_deviation_class` against §3.8's five pinned steps and the 489858 worked example (matches).

### Pass 3 (quality/qa/audit/services/app/serialize + remaining calc)

441 lines / 113,984 B -> **441 lines / 118,913 B**; 19 Edit calls, no full rewrite, no renumbering, §4/§5 untouched.

**Counts: 16 ambiguity-pins, 3 mismatch-revisions.**

- §2.4 — insert — ambiguity — clock response `data` carries exactly three fields and `current_utc` echoes the client's `to_iso8601` literal byte for byte rather than being re-rendered to 3 fractional digits — `routes/audit.py:103-110`
- §2.4 — insert — ambiguity — clock may be set backwards or to its current value (never refused); no move reverses an existing `LAPSED`/`EXPIRED` row; counts report only this move's retirements — `services.py:298-324`
- §2.10 rung 12 — revise — **mismatch** — production-axis guard list omitted batch-record-review opening, which impl checks first with `ERR_BATCH_PRODUCTION_STATE_INVALID` — `routes/qa.py:179-183`
- §3.6 — insert — ambiguity — recording an in-process control is entirely ungated (any production/quality status, no project or posture gate) — `routes/quality.py:34-63`
- §3.6 — insert — ambiguity — `measured_fill_weights_mg` elements must be JSON numbers; wrong element type is rung-6 `ERR_INVALID_REQUEST` (400) ahead of the 422 coherence rules — `validate.py:183-186`
- §3.7 — insert — ambiguity — `POST /em-samples` resolves `suite_id` before `batch_order_id` at rung 9 — `routes/quality.py:122-125`
- §3.7 — insert — ambiguity — em-sample recording consults no suite posture and no batch/project state — `routes/quality.py:120-141`
- §3.7 — insert — ambiguity — `root_cause` born null; only an investigation close writes it — `routes/quality.py:155`
- §3.7 — insert — ambiguity — an investigate does not write the suite row, so its `version` does not move — `routes/quality.py:203-205`
- §3.7 — insert — ambiguity — linked-deviation gate on closing an `ACTION` excursion is `ERR_DEVIATION_STATE_INVALID`, reached only after the `INVESTIGATING` precondition — `routes/quality.py:218-224`
- §3.7 — insert — ambiguity — `POST /deviations` resolves `batch_order_id` before `em_sample_id`; cited sample needs no suite/batch coherence — `routes/qa.py:42-45`
- §3.7 — insert — ambiguity — raising a deviation is not state-gated on batch or project — `routes/qa.py:40-59`
- §3.7 — insert — ambiguity — classification posts to `open_deviation_risk_total` by rederivation only; the deviation row alone is written outside the CRITICAL cascade — `calc.py:196-204`, `routes/qa.py:101-108`
- §3.7 — insert — ambiguity — project-hold suspensions write `released_reason` `SUITE_FREEZE_SUSPENSION`; an already-`ON_HOLD` project is a no-op with no sweep; the deviation's own `SCHEDULED`/`SETUP` batch is written by both hops so its `version` moves by 2 — `services.py:146-150, 258-272`
- §3.7 — insert — ambiguity — quarantine-close loop writes the batch row alone and never reopens a `CLOSED` review (leaving such a batch un-closeable) — `services.py:275-290`
- §3.8 — revise — **mismatch** — review-open production gate named `ERR_BATCH_PRODUCTION_STATE_INVALID` and pinned as tested before the quality gate — `routes/qa.py:179-188`
- §3.8 — insert — ambiguity — record-findings moves `IN_PROGRESS -> COMPLETE_WITH_FINDINGS` for a supplied 0 too, is ungated on the batch, refuses only a `CLOSED` review; on close the batch gate is tested first (`ERR_BATCH_QUALITY_STATE_INVALID` beats the review code) — `routes/qa.py:256-283`
- §3.8 — revise — **mismatch** — cross-pass hand-off resolved: `quarantined_unit_count` is now described as never written by any endpoint (always 0), consistent with pass 2's §3.5 pin, instead of "segregated during batch record review ... defaults to 0" — grep-confirmed writer-free (`routes/batches.py:184` init only; read at `calc.py:333`, `serialize.py:125`, `routes/batches.py:261`)
- §3.9 — insert — ambiguity — `finding_count` required integer >= 0 under both outcomes (a deferral omitting it is a 400) and the `HOSTED`-terminal test precedes the outcome branch, so a `DEFERRED` outcome against a hosted engagement is refused too — `routes/audit.py:63-68`

### Step 9 totals and integrity

**47 ambiguity-pins + 9 mismatch-revisions = 56 changes** across the three passes.

Pass 3's final integrity check: 441 lines / 118,913 bytes; `tail -5` ends on the complete final §5 row `| ERR_REQUIRED_IPC_MISSING | 422 |`; all five `## ` sections present in order (lines 3, 11, 163, 311, 379); not byte-identical to PRD_FINALIZED.md; table row count unchanged at 122 in both files, confirming §4/§5 untouched.

**Orchestrator independent verification:** `wc -l -c` -> PRD.md 441/103,670, PRD_FINALIZED.md 441/104,223, PRD_COMPLETED.md 441/118,913. `cmp PRD_FINALIZED.md PRD_COMPLETED.md` differs (the byte-identical no-scan failure mode did not occur); `diff` reports **45 changed lines**; all five `## ` sections present in order; tail ends on the complete final error-table row. Step 9 accepted.

**Pipeline complete.** Step 7's 8-round sweep remains valid — Steps 8 and 9 edited only PRD derivative documents, never `implementation/`, `test_suite/` or `test_helpers/`, so `results.1..8.json` (98/98 each) still describe the shipped artifacts.

# Worklog — task_0416_pharmacy_compounding_503a_503b

## Step 1: Create Task Directory — 2026-06-19T08:29:16.000Z

Used pre-assigned directory `tasks/task_0416_pharmacy_compounding_503a_503b` (did NOT scan/auto-increment per pipeline instructions). Verified it exists; ensured `workspace/` subdirectory present. INSTRUCTION.md present at project root; prd-bench-local-run available at /Users/uni/.local/bin/prd-bench-local-run.

## Step 2: Generate Scaffold (Expert) — 2026-06-19T08:45:00.000Z

Scaffold generated at **Expert** difficulty. SCAFFOLD.yaml: 12 entities, 51 endpoints, 39 errors, 5 state machines (meets/exceeds Expert bands: 10-15 entities, 20-32 endpoints, 18-30 errors, 4+ state machines). The first scaffold subagent wrote SCAFFOLD.yaml (1281 lines) but died mid-response (API connection closed) before the two design files; a second subagent completed the design indices from SCAFFOLD.yaml.

SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8, 1469 lines) — 18 instances (2 per rule × 9 rules): dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.

SCAFFOLD_CORNER_DESIGN.yaml (§1.9, 2353 lines) — 61 instances (47 active test_recipes, 14 excluded stubs): entities 12, state_machines 13, calculations 7, validations 12, endpoints 3, errors 4, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1. Passes scaffold_lint.py (clean lint, 651 calls scanned). All 79 instance names unique; formula-derived asserts computed from §1.3 formulas.

## Step 3: Copy Shared Files — 2026-06-19T08:46:00.000Z

Copied project-root INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-06-19T08:52:00.000Z

PRD.md produced (306 lines) from SCAFFOLD.yaml only; both design files withheld (not read). Sections: §1 Introduction; §2 Global Specifications (RBAC, response structure verbatim §2.2, pagination, common props & facility clock, hierarchical consistency/cascades, precision/rounding, OCC on batch release, segregation of duties, 503A/503B divide); §3 Business Logic (11 subsections — facilities/clock, MFR & anticipatory ledger, ingredient lots, environmental monitoring, prescriptions, compounding batch draft→compile/BUD/yield/label/reprocess, QC/endotoxin/contamination cascade, release/reject ordered gates, dispensing/distribution, recalls & cascades, referential integrity); §4 Endpoint Definitions (all 51 endpoints); §5 Error Catalogue (all 39 errors). Zero-Silence machine-verified: field-name coverage 79/79, all 39 error IDs + 23 states + 53 enums + 6 calc constants present, 24 rule spot-checks pass, §3 path-purity clean.

## Step 5: Generate Unit Tests — 2026-06-19T09:14:00.000Z

84 tests across 6 domain-named files, each with exactly one verbatim PRD citation + one `Design:` tag.
- Queue A (Difficulty): 37 tests covering all 18 difficulty instances (9 rules × 2), each ≥2 tests. (37 not 36: a −5.00 yield lower-boundary test landed as a 3rd test on yield_variance_round_then_band_compare_mode_b.)
- Queue B (Corner): 47 tests covering all 47 non-stub corner instances (≥1 each).
- Skipped: 0 design instances under PRD-first filter (all had verbatim coverage + unique derivability). 14 excluded_because corner stubs correctly NOT translated.
- One correction: a test mis-tagged to corner stub yield_under_yield_lower_boundary_inclusive was retagged to owning difficulty instance.
Files: test_helpers/{__init__,types,api_client,api_errors,assertions,factories,constants,test_users,fixtures}.py; test_suite/{conftest,test_01_beyond_use_dating_and_yield,test_02_batch_lifecycle,test_03_release_gates_and_concurrency,test_04_recalls_cascades_and_invariants,test_05_dispensing_and_cross_entity,test_06_entities_and_rbac}.py.
Notable: all 4 roles opaque per PRD §2.1 → test_users.py uses shared role constants + make_*_headers(user_id) to thread distinct compiler/releaser X-User-ID for segregation-of-duties; EnvironmentalLog modeled common_fields:false (no version/updated_at); PRD literal `pass` field via pass_flag factory kwarg.

NOTE: Step 6 was launched AFTER Step 5 finished (not concurrently). To preserve the PRD-only contract / physical isolation that concurrency normally provides, the Step 6 prompt carries an explicit hard prohibition on reading test_suite/ and test_helpers/.

## Step 6: Generate Implementation — 2026-06-19T09:38:00.000Z

Python + Flask implementation in workspace/implementation/, in-memory dict storage (no SQLite/disk/seed). Files: start.sh (reads $PORT default 10000, binds 0.0.0.0 foreground via exec python3 app.py; guards pip install behind `import flask` check), requirements.txt (Flask==3.0.3), app.py (~1300 lines, all 50+ endpoints/error handlers/validation precedence/state machines/cascades), db.py (in-memory dicts + RLock), store.py (common-field init, lazy expiry, derived-field reconciliation, serializers), calculations.py (BUD sterile 14/45 + nonsterile + 503B 90d cap-before-floor, yield variance, endotoxin route-tiered projection, potency adj — Decimal/ROUND_HALF_UP), validation.py, middleware.py (auth+RBAC), response.py, errors.py, timeutil.py. All .py compile OK; start.sh executable. Confirmed NOT reading test_suite/, test_helpers/, design YAMLs, or sibling tasks.

## Step 7: Run Tests and Iterate — 2026-06-19T10:40:00.000Z

Clean exit. All 8 parallel rounds passed 84/84.

**Iterations run:** 2 (one diagnostic sweep that surfaced 3 stable failures; one verification sweep that confirmed all green).

The initial 8-round sweep was stable at 81/84 — the same 3 tests failed in all 8 rounds (no flakiness). All three were **test-layer bugs** where the fixture/setup constructed a precondition inconsistent with PRD, so the PRD-faithful implementation correctly rejected it. No tests were deleted and no implementation code was changed.

**Tests deleted:** none. (All three failures were faithful-assertion / inconsistent-setup cases, not PRD-silence cases.)

**Fixes applied to test_suite/ (setup made more faithful to PRD; assertions unchanged):**

1. `test_01_beyond_use_dating_and_yield.py::test_potency_adjusted_grams_rounds_to_four_decimals` — setup created a `503A` facility then opened an `OFFICE_USE` batch, which PRD §3.6 forbids ("a 503A facility may never create an OFFICE_USE batch... OFFICE_USE is permitted only at a 503B facility"), so the impl correctly returned `ERR_PURPOSE_PRESCRIPTION_MISMATCH` before the potency-rounding assertion could run. Switched the facility to `503B` (the potency_adjusted_grams calc is purpose/facility-independent; assertion preserved).

2. `test_03_release_gates_and_concurrency.py::test_release_blocked_by_environmental_excursion` — the sterile batch (grams_used=10, potency 99.4%, yield 5 → 9940 active mg, STERILE_AQUEOUS ceiling 175 EU/unit) made the ENDOTOXIN QC test FAIL at the default `endotoxin_measured_value=0.5` (projected 994 EU/unit), so release tripped `ERR_QC_FAILED` — which PRD §3.8 checks *before* the environmental gate. Lowered the call to `endotoxin_measured_value=0.01` (projected 19.88 EU/unit, passes) so QC clears and the environmental-excursion gate under test surfaces. Assertion of `ERR_ENVIRONMENTAL_EXCURSION` preserved.

3. `test_04_recalls_cascades_and_invariants.py::test_second_office_use_release_over_window_capacity_rejected` — the second OFFICE_USE batch compiled `actual_yield_units=90` against a formula `theoretical_yield_units=120` (yield variance −25%), which PRD §3.6's ±5.00% band rejects with `ERR_YIELD_OUT_OF_RANGE` at compile, before reaching the anticipatory gate. Changed the second batch's yield to `115` (variance −4.17%, in-band) which still exceeds the remaining window capacity of 80, so release trips `ERR_ANTICIPATORY_LIMIT_EXCEEDED` as intended. Final assertions (`consumed_units==120`, `remaining_units==80`) remain valid.

**Fixes applied to test_helpers/:** none.

**Fixes applied to implementation/:** none — the implementation was already PRD-faithful on all three rules (purpose/facility coherence, release check ordering, yield tolerance band).

**Note on runner mechanics:** Several intermediate sweeps showed all-84-errors "API server could not be restarted." This was an invocation artifact — when the `--start-command` omitted the `cd <impl-dir>` prefix, `bash start.sh` couldn't resolve the script. Running with the full `--start-command "cd <impl-dir> && bash start.sh"` booted cleanly with zero restart errors.

**Final result: 8/8 parallel rounds at 84/84 passed, 0 failed, 0 errors.** (Orchestrator re-verified all 8 results.N.json: passed=84 total=84 failed=0.)

## Step 8: Finalize PRD — 2026-06-19T10:50:00.000Z

PRD_FINALIZED.md produced. **Zero edits** — byte-identical copy of PRD.md (306 lines, same MD5). All three Step 7 items were diagnosed as PURE FIXTURE BUGS where the impl was already PRD-faithful and the PRD prose already uniquely determines the behavior:
- Item 1 (potency-adjusted-grams / 503A→503B fixture switch): PRD §3.6 ("a 503A facility may never create an OFFICE_USE batch... OFFICE_USE is permitted only at a 503B facility... ERR_PURPOSE_PRESCRIPTION_MISMATCH") + potency calc §2.6/§3.6 already pin behavior (app.py:578-579, calc.py:30-33). No edit.
- Item 2 (release env-excursion / endotoxin fixture lower): PRD §3.8 fixed release-gate order + §3.7 endotoxin route ceilings (175/350 EU) already pin behavior (app.py:783-834, calc.py:80-89). No edit.
- Item 3 (second office-use over-capacity / yield fixture change): PRD §3.6 ±5.00% inclusive yield band + ERR_YIELD_OUT_OF_RANGE already pin behavior (calc.py:42-52, app.py:687-689). No edit.
Mandatory pre-edit NO-NEW-MISMATCH search performed for all three subjects (enumerated parallel impl paths: creation coherence, BUD cap, ledger filters, release gates, recall recompute, dispense coherence) — all consistent with existing PRD prose; no wording adjustment needed.

## Step 9: Complete PRD — 2026-06-19T11:05:00.000Z

PRD_COMPLETED.md produced from PRD_FINALIZED.md. 306 lines (unchanged), +1095 chars. 8 changes total: 7 ambiguity-pins, 1 mismatch-revision (all in-paragraph, no new sections):
- §2.3 Pagination — insert — ambiguity — sort tiebreaker (ties on created_at broken by ascending id) — app.py:157
- §2.4 Common Resource Properties — insert — ambiguity — version initial value = 1 — store.py:18
- §3.2 MFR — insert — ambiguity — retire has no state precondition and is idempotent (already-RETIRED stays RETIRED, refreshes updated_at/version) — app.py:282-289
- §3.3 Ingredient Lots — insert — ambiguity — release-quarantine on non-QUARANTINED lot returns ERR_BATCH_NOT_IN_STATE — app.py:403-404
- §3.6 Compounding Batch — revise — ambiguity — exact deterministic unit_serial format (first 8 chars of batch id uppercased + hyphen + 1-based seq zero-padded to 4) — app.py:715,725-726
- §3.9 Dispensing — insert — ambiguity — non-ACTIVE prescription or formula mismatch on PRESCRIPTION unit returns ERR_DISPENSE_CHANNEL_MISMATCH; channel check precedes unit-state preconditions — app.py:1103-1111
- §3.10 Recalls — insert — ambiguity — failed reconcile (ERR_RECALL_UNITS_OUTSTANDING) still persists recomputed units_reconciled + bumps updated_at/version, leaves status IN_PROGRESS — app.py:1277-1280
- §3.11 Referential Integrity — revise — mismatch — reordered so body-structure validation (400) precedes body-FK existence (422), matching every create handler — app.py:215-238

Step 9 edits PRD prose only (not impl/tests); no test re-run needed — implementation unchanged since the clean 8/8 sweep.

## Pipeline complete — 2026-06-19T11:05:00.000Z

All 9 steps complete. Final test status: 8/8 parallel rounds at 84/84 (0 failed, 0 errors). Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/, test_suite/, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.

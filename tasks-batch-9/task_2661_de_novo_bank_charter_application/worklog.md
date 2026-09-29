## Step 1: Create task directory — 2026-09-04T02:55:35.371000383Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2661_de_novo_bank_charter_application and its workspace/ subdirectory. Index 2661 was pre-assigned by the invocation; no scan of ./tasks/ was performed (concurrent pipelines on this host).


## Step 2/3: Scaffold generation — 2026-09-04

Generated the three scaffold artifacts from the verbatim scenario plus the scaffold-generator
skill spec only (no sibling task under /home/ubuntu/github/CodingPRD/tasks/ was read):

- /home/ubuntu/github/CodingPRD/tasks/task_2661_de_novo_bank_charter_application/SCAFFOLD.yaml
  §1.0–§1.7: 13 entities, 12 state machines, 2 concurrency_rules, 16 calculations,
  81 validations, 59 endpoints, 104 errors, 7 roles; api_prefix /de-novo;
  difficulty_level expert_plus. Contains neither scaffold_difficulty_design nor
  scaffold_corner_design.
- .../SCAFFOLD_DIFFICULTY_DESIGN.yaml — §1.8, 9 §0.5 rules x 2 = 18 instances.
- .../SCAFFOLD_CORNER_DESIGN.yaml — §1.9 breadth probe, 9 guide sections,
  66 instances (55 with test_recipe + 11 excluded_because stubs).

Verification: scaffold_lint.py -> "VERDICT: clean lint" (1609 calls scanned);
all 346 grounds entries resolve to declared §1.1–§1.7 elements; instance names unique
across the union of both design files; every stub's difficulty_instance citation matches
a real rule_id/name pair; no forbidden concurrency vocabulary outside the verbatim scenario.

## Step 2: Generate scaffold (orchestrator record) — 2026-09-04T04:30:08.414229994Z

Subagent summary, verbatim:

All three scaffold artifacts for task_2661 are complete and lint-clean.

| File | Lines | Contents |
|---|---|---|
| SCAFFOLD.yaml | 3784 | §1.0–§1.7 only — 13 entities, 12 state machines, 2 `concurrency_rules`, 16 calculations, 81 validations, 59 endpoints, 104 errors, 7 roles, `api_prefix: /de-novo`, `difficulty_level: expert_plus`. Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`. |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | 2698 | §1.8, single top-level key — 9 §0.5 rules × 2 differentiated instances = 18. |
| SCAFFOLD_CORNER_DESIGN.yaml | 5185 | §1.9, single top-level key — all 9 claim-extraction-guide sections, 66 instances (55 with full `test_recipe`, 11 `excluded_because` stubs). |

Lint verdict (verbatim):
  §1.5 endpoints declared: 59; §1.1 entities declared: 13; §1.8 instances scanned: 18;
  §1.9 instances scanned: 55; Calls scanned (§1.8+§1.9): 1609
  VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

Additional checks run beyond the linter:
- 346 `grounds` entries (both design files) mechanically resolved against §1.1–§1.7; 0 dangling. Fixed 2 malformed paths found this way: `roles.CharterCounsel` → `roles[CharterCounsel]`, and `state_machines.Subscription.PLEDGED_to_FUNDED` → the two-dimensional form `funding_state=PLEDGED_to_funding_state=FUNDED`.
- Instance names unique across the union of both files (84 names, 0 collisions); all 11 stub `difficulty_instance` citations match a real `rule_id / name` pair.
- All `claim_type` values drawn only from references/claim-extraction-guide.md; no invented sections or types.
- Every formula-derived assert executed as code first (stress paths, concentration add-on, subscore/composite arithmetic, escrow aggregates, supervision index rollover at days 364/365/1095). Two literal bugs caught and fixed during this pass.
- No forbidden concurrency vocabulary anywhere except the mandated verbatim scenario line.
- Hard constraint honored: no sibling task_*/ directory was listed, read, or grepped.

Orchestrator verification: all three files present and parse as YAML; design files each have exactly one top-level key (`scaffold_difficulty_design`, `scaffold_corner_design`); SCAFFOLD.yaml has neither. workspace/ survived the subagent.

## Step 3: Copy shared files — 2026-09-04T04:30:12.763628000Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-04T04:52:00.000Z

Subagent summary, verbatim:

Done. `PRD.md` is complete and verified.

**Output:** workspace/PRD.md — **507 lines**, last heading **`## 5. Error Code Catalogue`**, ending on the final table row `| `ERR_ESCROW_ALREADY_RELEASED` | 409 |`. No audit footer, nothing truncated, no mid-sentence tail. Written incrementally with heredoc appends throughout.

**Structure:** §1 Introduction (3 paragraphs) · §2 with 11 domain-derived subsections (2.1 RBAC and the two entity-backed roles, 2.2 verbatim response envelope, 2.3 pagination and every list filter, 2.4 common fields and the logical clock, 2.5 precision and the three rounding disciplines, 2.6 derived-field recompute plus the three frozen exceptions, 2.7 cascade propagation and reversibility, 2.8 the two OCC rules, 2.9 path/body resolution and the 13 not-found codes, 2.10 the 11-band validation ladder, 2.11 the two conservation invariants) · §3 with 9 freely-grouped workflow subsections · §4 with 59 rows in the mandated 4 columns · §5 with 104 rows in the mandated 2 columns.

Contract 1 — Field-Name Coverage: PASS. 154 required identifiers (125 entity fields + 90 endpoint input keys/query params + dict-output keys + 13 path params, deduplicated) checked mechanically against every backtick token in PRD.md. 0 missing. The first run surfaced exactly the 10 path-param names that the §4 table's full paths do not expose as standalone tokens (plan_id, scenario_id, raise_id, subscription_id, condition_id, policy_id, contract_id, window_id, exam_id, deviation_id); a paragraph was added to §2.9 naming all thirteen path identifiers and calling out the plan_id/business_plan_id and raise_id/capital_raise_id spelling split.

Contract 2 — Rule Coverage: PASS. All 81 validations, all 12 state machines (every transition, precondition and side effect, including the four system-driven ones), all 16 calculations, both OCC rules, both declared priority pairs, all field defaults and all applies_to scopes are uniquely determined by prose. All 104 catalogued error IDs appear in §1–§4 prose (verified mechanically: 0 unmentioned), and 0 error IDs appear in the prose that are absent from the catalogue.

Contract 3 — §3 Path Purity: PASS. 0 violations.

Findings worth relaying:
- ERR_INFO_ROUND_LIMIT_EXCEEDED does not exist in the 104-error catalogue although a RegulatoryFiling state-machine note (SCAFFOLD.yaml:1157) says the over-ceiling information request is "refused" with it. Two other sources say the request is instead converted into DENIED. The PRD specifies the conversion and never names the nonexistent code. Same class as the invented ERR_PLAN_PINNED_NOT_SUPERSEDABLE note at line 1103, which the PRD folds into ERR_SUPERSEDE_TARGET_NOT_ELIGIBLE.
- Three scaffold contradictions resolved in favour of the enforced validation: (a) opening_tier1_capital_cents entity constraint >= 100,000,000 vs validation priority 73 >= 2,000,000,000 — only the latter stated. (b) narrative/evidence_reference entity constraints vs validation priority 4 requiring >= 20 characters — PRD states >= 20 (and <= 500 for narrative). (c) nim_compression_bps entity constraint 0..2000 vs band-2 summary 0..5000 — PRD states 0..2000.
- Four preconditions have no declared error_id anywhere in the scaffold, so the PRD assigns the only semantically exact code available: opening a capital raise on a too-late group -> ERR_GROUP_STAGE_LOCKED; escrow release with the group not in pre-opening -> ERR_GROUP_NOT_IN_PRE_OPENING; escrow release with a filing lacking pre_opening_clearance -> ERR_PRE_OPENING_CONDITIONS_OPEN; FINAL_APPROVED with no passed examination -> ERR_READINESS_EXAM_NOT_PASSED.
- Incidental: /tmp/sec5.md on this host held another task's error table from an earlier session. Wrote to /tmp/task2661_sec5.md instead; no cross-task content entered this PRD.

Orchestrator verification (truncation guard): PRD.md is 507 lines / 16471 words; headings run §1..§5 with §4 endpoint table at lines 331-396 and §5 error catalogue at 397-507; the file ends on a complete table row at a real section boundary. Not truncated — no regeneration needed.

## Step 6: Generate implementation — 2026-09-04T05:41:30.000Z

Subagent summary, verbatim:

Implementation complete and smoke-verified.

Files (all in workspace/implementation/): start.sh (executable, 398 B) 10; requirements.txt (Flask==3.0.3) 1; app.py 102; calc.py 421; serialize.py 279; validation.py 158; cascade.py 155; errors.py 131; util.py 103; db.py 100; middleware.py 48; response.py 43; routes/groups.py 250; routes/reads.py 245; routes/filings.py 237; routes/raises.py 217; routes/plans.py 151; routes/vendors.py 135; routes/policies.py 93; routes/deviations.py 86; routes/exams.py 81; routes/helpers.py 41; routes/clock.py 22; routes/__init__.py 0. Total 3,098 lines. All 22 .py files AST-parse and py_compile clean; __pycache__ removed.

Endpoint coverage: 59 / 59. Programmatically diffed the Flask URL map against every method/path pair in SCAFFOLD.yaml endpoints (method + path-shape normalized): missing = 0, extra = 0. Breakdown: 13 single GETs, 12 list GETs (no list for organizing-groups), 1 computed GET (capital-adequacy), 13 creates, 19 action POSTs, 1 clock POST.

Verification performed:
- Boot: PORT=18661 bash start.sh -> HTTP-ready in 0.68 s; store confirmed empty on a fresh process (total_count: 0); killed by the recorded PID only, port confirmed free. No broad pkill.
- Full lifecycle E2E (single script, 60+ calls, all green): group -> 6 organizers -> 12 background results -> COMPOSITION_MET/score 98.00 -> plan + stress scenario (DYNAMIC_GROWTH, 1777 bps) -> submit -> capital-adequacy (ADEQUATE, all 10 intermediate terms) -> FILING_READY -> raise/open/3 subscriptions/fund/screen/lock-escrow -> 2 filings filed -> 4 policies drafted+adopted+accepted -> vendor EVALUATING->SELECTED->SIGNED -> conversion window (24.0 h) + confirm -> both filings CONDITIONALLY_APPROVED (group auto-promoted) -> condition + evidence + adjudicate (posture 1/0/1, pre_opening_clearance true) -> PRE_OPENING -> exam scheduled (buffer_end_utc = end + 48 h) -> clock advance -> exam PASSED -> both FINAL_APPROVED -> release-escrow -> OPEN (supervision index 1) -> deviation (baseline 4,000,000,000, 1500 bps, requires_regulator_approval true, SUBMITTED) -> decision APPROVED -> all 12 list endpoints.
- Error paths: 401 unauthenticated, 404 entity + 404 unknown route (ERR_NOT_FOUND), 405 (ERR_METHOD_NOT_ALLOWED), 422 schema, 422 ERR_CLOCK_NOT_MONOTONIC on backwards clock, 412 ERR_STALE_GROUP_VERSION, 422 on limit=0.
- No seeding / no persistence: grep confirms no seed_*, no sqlite, no file writes, no /tmp use.

PRD ambiguities resolved (interpretation chosen):
1. Opening-capital minimum — PRD's 2,000,000,000 cents used over the differing scaffold entity constraint (PRD wins).
2. 4th information round — an ADDITIONAL_INFO_REQUESTED decision when info_request_round is already 3 converts to DENIED and runs the full denial cascade.
3. System-driven filing regression (CONDITIONALLY_APPROVED -> ADDITIONAL_INFO_REQUESTED on a reopened blocking condition) fires only while info_request_round + 1 <= 3; with the budget exhausted the filing holds status and merely loses clearance.
4. Identity check placement — ERR_ORGANIZER_IDENTITY_MISMATCH is band 1 priority 3 but needs the group in scope, so it runs after path/body existence resolution; enforced on organizer-role writes only.
5. Validation-order conflicts resolved as: raise open uses PRD prose (ERR_RAISE_NOT_OPENABLE before ERR_GROUP_STAGE_LOCKED) since scaffold priority 10 omits that endpoint; FINAL_APPROVED uses PRD 254 prose (conditions -> group stage -> exam) since priorities 23/36 omit the decision endpoint; exam result uses scaffold priorities (findings-limit 37 before window-not-started 70); vendor SELECTED uses priorities (due-diligence 34 before domain-uniqueness 55).
6. capital-adequacy default plan = plan pinned by the CHARTERING_AUTHORITY filing, else newest SUBMITTED; when neither exists (and no business_plan_id given) -> ERR_BUSINESS_PLAN_NOT_FOUND 404.
7. Clock advance does not recompute anything — PRD 89/318 ("modifies no entity row", "recomputed lazily") wins over the scaffold calculation's trigger listing POST /_clock/set_current_utc. Deviation decision therefore derives the supervision index without persisting it.
8. Deviation narrative min length 20 (PRD) over the scaffold's 1..500.
9. Filing file group-stage gate reported as ERR_GROUP_STAGE_LOCKED (PRD names no error for it).
10. Other choices: pre_opening_clearance requires status in {CONDITIONALLY_APPROVED, FINAL_APPROVED} and zero open blocking conditions; evidence submission does not increment adjudication_count; supersede target must be same-group AND DRAFT; screening CLEARED from {UNSCREENED, SCREENING}, REJECTED also from CLEARED; enum-valued list query filters are not enum-validated; decision_note on a filing is stored but not serialized; created_at/updated_at use wall clock while collection ordering uses a monotonic insertion sequence.

Orchestrator note: Step 5 (unit tests) and Step 6 (implementation) were launched as concurrent background subagents. The orchestrator verified before Step 6 started that neither test_suite/ nor test_helpers/ nor implementation/ existed yet, so the impl generator had physical isolation from the test artifacts.

## Test generation complete
- test_27_cross_cutting.py (4 tests) and test_28_consistency.py (1 test) close queue B.
- Final: 21 files in test_suite/ (conftest + 20 test modules), 101 tests, 5295 lines.
- Coverage: queue A 18/18 non-stub instances, queue B 55/55 non-stub instances. 11 stubs
  (excluded_because) correctly left untranslated. Zero instances skipped.
- Verified: ast.parse clean, every module imports, no unused imports, exactly one Design:
  tag per test as the last docstring line, every tag resolves to a real non-stub instance,
  every PRD: "..." line survives a literal grep of workspace/PRD.md, no mention of the
  design/scaffold sources in any comment or docstring.

## Step 5: Generate unit tests — 2026-09-04T06:21:00.000Z

Subagent summary, verbatim:

Test suite generation for task 2661 is complete.

test_helpers/ — 9 files, 2531 lines: __init__.py 69, api_client.py 325, api_errors.py 268, assertions.py 248, constants.py 115, factories.py 352, fixtures.py 838, test_users.py 79, types.py 237.

test_suite/ — 21 files, 5295 lines, 101 tests: conftest.py 92; test_01_stress_leverage_paths.py 255/5; test_02_escrow_bases_and_waterfall.py 335/8; test_03_management_composite.py 212/5; test_04_filing_info_cycle.py 138/3; test_05_subscription_dimensions.py 130/3; test_06_policy_rejection_cascade.py 163/4; test_07_screening_rejection_cascade.py 147/4; test_08_exam_scheduling_buffer.py 170/4; test_09_conversion_windows.py 166/4; test_10_pre_opening_gates.py 166/3; test_11_condition_rework_loop.py 144/3; test_20_entities.py 433/11; test_21_state_machines.py 399/9; test_22_calculations.py 449/7; test_23_validations.py 595/8; test_24_endpoints.py 310/5; test_25_errors.py 250/5; test_26_rbac.py 319/5; test_27_cross_cutting.py 341/4; test_28_consistency.py 81/1.

Per-queue instance coverage:
- Queue A (§1.8, Difficulty): 18 / 18 non-stub instances -> 55 tests (>=2 per instance).
- Queue B (§1.9, Corner): 55 / 55 non-stub instances -> 46 tests — entities 11, state_machines 9, calculations 7, validations 8, endpoints 5, errors 5, rbac 5, cross_cutting_complexity_layers 4, consistency_model 1.
- 11 excluded_because: stubs correctly left untranslated (3 state_machines, 4 calculations, 2 validations, 2 cross_cutting).

Skipped instances: None. Zero instances failed the PRD-first two-condition filter.

Four instances were reshaped rather than skipped, all because the design recipes named instants in June 2026 while the harness clock starts at 2026-08-01T00:00:00Z and moves forward only:
1. Corner/validations/validation_window_start_exactly_at_the_clock_is_accepted — realized at 2026-07-31T23:59:59Z (422) then 2026-08-01T00:00:00Z->2026-08-03T00:00:00Z (201, 48.00 h).
2. Corner/errors/error_window_end_equal_to_start_is_rejected — realized at 2026-09-02T12:00:00Z.
3. Corner/errors/error_clock_cannot_move_backwards — clock pre-advanced to 2026-09-01T00:00:00Z in setup.
4. Corner/cross_cutting_complexity_layers/occ_stale_vendor_contract_version_rejects_window_reserve — windows moved to 2026-09-02/03.

One further reshape on semantic grounds: Difficulty/cross_entity_state_dependency/pre_opening_advance_requires_both_filings_conditionally_approved uses REOPENED instead of the design's FAILED (PRD §3.6 makes FAILED legal only from EVIDENCE_SUBMITTED, itself a blocking status), and takes its positive complement from a cleanly gated group because the design's re-filing half names no error id.

Verification run on the finished suite:
- ast.parse clean on all 21 modules; every module executes its imports without error.
- No unused imports anywhere.
- Exactly one Design: line per test, always the last docstring line; all 73 distinct tags resolve to real non-stub instances; no tag points at a stub or a non-existent instance.
- Every PRD: "..." citation survives a literal substring match against workspace/PRD.md (0 misses).
- No comment or docstring mentions the design/scaffold sources.
- workspace/implementation/ was never read, listed, or grepped; no sibling task_*/ directory touched; no broad pkill; no server started.

Orchestrator verification: test_helpers/ and test_suite/ are both at the task root (no stray copies under workspace/).

## Step 7: Run tests and iterate — 2026-09-04T06:42:00.000Z

Subagent summary, verbatim:

Clean 8-round sweep achieved.

Iterations run: 2

Iteration 1 (baseline sweep): all 8 rounds identical at 98/101 passed, 0 failed, 3 errors — fully deterministic, no flakiness. All 3 errors were pytest setup errors, not implementation failures:

    fixture 'boundary_plan_group' not found

affecting test_01_stress_leverage_paths.py:
- test_governing_minimum_of_exactly_800_bps_passes_plan_submission
- test_capital_adequacy_on_the_floor_plan_passes_on_equality
- test_governing_minimum_of_799_bps_fails_plan_submission

Diagnosis: the triage hint applied — 3 tests sharing one setup error pointed straight at test_helpers. The builder boundary_plan_group WAS fully written at test_helpers/fixtures.py:793 (plus BOUNDARY_PLAN_OVERRIDES at line 788), but it was never registered as a pytest fixture in test_suite/conftest.py, so pytest could not resolve the argument name. Pure wiring gap.

Before wiring it I verified the builder is PRD-faithful rather than an artifact bent to fit the implementation. Hand-computing §3.2's dual leverage path and §3.3's five-step verdict over the boundary projections (projected_loans_y3_cents = 27,950,000,000 against projected_assets_y3_cents = 43,000,000,000, NATIONAL charter) reproduces every asserted figure exactly:
- b1 (no overrun): dynamic years 1415 / 989 / 800.5523->800, static 1415 / 1378 / 1477 -> dynamic_min=800, breach=0, static_min=1378
- b2 (4,300,000c overrun): dynamic 1413 / 988 / 799.552->799 breaching year 3, static 1413 / 1376 / 1475
- concentration 27.95e9x10000/43e9 = 6500 exactly on the trip point -> add-on 0, required_leverage_bps = max(800, 800+0) = 800, worst governing 800 -> ADEQUATE on equality (§3.3 "Equality passes.")

Tests deleted: none. No test failed STEP 1a (PRD coverage) or STEP 1b (unique derivability) — the only defect was mechanical fixture registration, so nothing was PRD-silent or under-determined.

Fixes applied to test_helpers/: none needed (the builder was already correct).

Fix applied to test_suite/: test_suite/conftest.py — added the missing boundary_plan_group pytest fixture delegating to fx.boundary_plan_group(api), placed alongside the other plan-world fixtures.

Fixes applied to implementation/: none. The implementation passed 98/101 at baseline and 101/101 once the fixture resolved; no PRD-required check was weakened or removed, and no endpoint, field, or side effect was added.

Final per-round results (iteration 2): rounds 1-8 all 101/101 passed, 0 failed, 0 errors.

All eight results.$i.json files are confirmed on disk in workspace/implementation/ (timestamped 06:30, ~29.4 KB each, complete JSON). Both sweeps ran under setsid nohup and no round showed the SIGTERM/Terminated reaping signature. Also verified implementation/db.py is a pure in-memory dict store with no seeding and no on-disk persistence; no stray test directories or worklog files drifted into workspace/.

Orchestrator verification: independently parsed all 8 results.*.json — every round reports passed 101 / total 101.

Step 8 decision: the formal skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is NOT met — there was one test_suite/conftest.py fix. Step 8 therefore runs, but the single diff item is a pure pytest-fixture wiring gap with no PRD-semantic content and 0 implementation fixes, so the expected outcome is a PRD_FINALIZED.md identical (or near-identical) to PRD.md. The Step 8 subagent is instructed explicitly not to invent edits that do not trace to the diff.

## Step 8: Finalize PRD — 2026-09-04T06:47:00.000Z

Subagent summary, verbatim:

workspace/PRD_FINALIZED.md created as a byte-identical copy of workspace/PRD.md (md5 cf94e011..., 507 lines each, 0 line delta, 0.00 %).

No changes justified.

Reasoning: The single <step_7_diff> item is a pytest wiring gap: boundary_plan_group existed as a builder in test_helpers/fixtures.py:793 but was never registered in test_suite/conftest.py (now at test_suite/conftest.py:61-62). That fix carries no PRD-semantic content, so the only admissible edits would be ones tracing to the boundary-plan / dual-leverage-path / capital-adequacy-verdict behavior the three unblocked tests exercise. I checked each of those behaviors against the implementation and found PRD.md already uniquely determines all of them:
- Dual leverage path — implementation/calc.py:195-220 (stress_leverage_path) walks years 1->3 ascending, carries capital forward, selects per-variant assets/loans, rounds credit loss and NIM hit half-up to cents before subtraction, applies expense_overrun_cents in year 1 only, and floors capital*10000 // assets_t. Every clause is stated verbatim in PRD §3.2 P191. Breach year = first year below 800 (calc.py:216-219) matches P192; governing selection by scenario code (calc.py:230-237) matches P193.
- Numeric verification — hand-recomputed the boundary projections from PRD prose alone and reproduced the implementation's figures exactly (dynamic y3 800.552 -> 800, static min 1378; with the 4,300,000-cent overrun dynamic y3 799.55 -> 799 breaching year 3, static min 1376; concentration 6500 exactly). No mismatch to pin.
- Capital-adequacy verdict — implementation/calc.py:255-283 matches PRD §3.3 P201-209 step for step, including "equality passes".
- Submission gates — routes/plans.py:133-147 evaluates the six gates in exactly the PRD §3.3 P213 order, failing before any mutation (§4 P333 already states no partial mutation / no version bump).
- Fixture-specific surface — boundary_plan_group creates two coexisting DRAFT plans with no supersedes_plan_id; PRD P185 already calls supersedes_plan_id optional and pins plan_revision_index to 1 when omitted, and imposes no one-draft-per-group rule; routes/plans.py:47-56,73 behaves accordingly.

Per-edit pre-edit search log: (a) Subject: boundary-plan behavior — dual leverage path, plan-submission stress floor, capital-adequacy verdict, multi-draft-plan creation. (b) Impl paths enumerated/read: calc.py in full; routes/plans.py in full; the capital-adequacy read at routes/reads.py:232-245; cross-checked all callers of capital_adequacy_verdict (submit gate + computed read) and of recompute_plan_aggregates/recompute_scenario (scenario create); test_helpers/fixtures.py:788-806 and factories.py:108-129 for the projections under test. (c) Wording adjustment: none.

Orchestrator decision for Step 9: because Step 8 justified no edits, PRD_COMPLETED.md starts from a PRD that has never been patched, so the full implementation scan is the only completeness signal in this pipeline. Given the size of implementation/ (22 modules, ~3,100 lines, 59 endpoints), Step 9 is run as THREE sequential file-partitioned passes over the same PRD_COMPLETED.md (pass A: cross-cutting infra + calculations; pass B: groups/plans/raises/clock/helpers routes; pass C: filings/policies/vendors/exams/deviations/reads routes) so no single subagent has to hold the whole implementation at once and silently skip files.

## Step 9: Complete PRD (three sequential file-partitioned passes) — 2026-09-04T07:10:00.000Z

Run as three sequential passes over the same PRD_COMPLETED.md because implementation/ is 22 modules / ~3,100 lines / 59 endpoints and a single subagent would silently skip files.

### Pass A — cross-cutting infrastructure + all calculations (app.py, middleware.py, response.py, errors.py, util.py, db.py, validation.py, serialize.py, cascade.py, calc.py). Subagent summary, verbatim:

PRD_COMPLETED.md created by cp from PRD_FINALIZED.md; PRD_FINALIZED 507 lines / 119,023 chars -> PRD_COMPLETED 509 lines / 122,885 chars. Counts: 11 ambiguity-pins, 1 mismatch-revision.
- §2.1 — insert — ambiguity — an empty/whitespace-only header counts as absent for ERR_UNAUTHENTICATED, role must match a declared role exactly — middleware.py:24-29
- §2.2 — revise — ambiguity — api_request_id is req_ plus exactly 20 chars from uppercase letters and digits — util.py:24-26
- §2.3 — revise — ambiguity — non-integer / zero-padded limit/offset are also ERR_INVALID_REQUEST, an empty value is treated as omitted, created_at ties ordered by insertion sequence — validation.py:113-138, db.py:70-71
- §2.3 — insert — ambiguity — the four boolean filters accept true/false/1/0 case-insensitively and reject anything else; other filters exact string equality; empty filter value = absent — validation.py:141-158
- §2.4 — insert — ambiguity — version increments at most once per row per request however many cascade links reach it; all rows mutated by one request share one updated_at — db.py:74-96
- §2.4 — insert — ambiguity — created_at/updated_at/api_request_timestamp come from host real time (not the logical clock); domain datetimes serialize as UTC Z with fractional digits only when non-zero; supplied numeric offsets normalized to UTC — util.py:29-53, response.py:7-11, db.py:53-58, serialize.py:12-24
- §2.5 — insert — ambiguity — integer input fields must be JSON integers; a decimal-point value (even 100.0) or a boolean is ERR_INVALID_REQUEST — validation.py:47-57
- §2.10 (band 2) — insert — ambiguity — a missing/unparseable body is validated as an empty JSON object; a non-object JSON body is itself ERR_INVALID_REQUEST — validation.py:10-19
- §3.3 — revise — ambiguity — governing plan is the filing's pinned plan only while still PINNED; otherwise newest SUBMITTED — calc.py:286-295
- §3.5 — insert — MISMATCH — the system-driven CONDITIONALLY_APPROVED -> ADDITIONAL_INFO_REQUESTED regression is suppressed when info_request_round is already 3: status and round count hold, only pre_opening_clearance falls false, no group/exam links fire — cascade.py:326-334
- §4 (preamble) — insert — ambiguity — unmatched path -> ERR_NOT_FOUND 404, undeclared method on a declared path -> ERR_METHOD_NOT_ALLOWED 405, trailing slash insignificant — app.py:43,73-83
- §5 (table) — insert — ambiguity — added framework rows ERR_NOT_FOUND 404 and ERR_METHOD_NOT_ALLOWED 405 — errors.py:117-118
Verified-and-unchanged: full error-id -> HTTP map (104 PRD rows vs 106 impl entries, zero status mismatches, only the two framework codes missing — now added); all 13 serializer field sets match their PRD field lists exactly; organizer subscore weights/status ladder; composition status and affiliation ceiling; both stress leverage variants, breach-year selection, governing choice; plan aggregates; five-step capital-adequacy derivation; both escrow bases and the gross-based 5% reimbursement waterfall; filing posture and pre_opening_clearance; 48-hour exam buffer and half-open conflict test; conversion-window duration and 2-occupant overlap counting; supervision-year floor arithmetic; deviation baseline selection, zero-baseline rule, 1000/2500 bps thresholds; all eight cascade helpers.
Left to later passes: the §4 GET /de-novo/organizers filter-row mismatch (reads.py:106-109 registers only group_id, role_on_board, qualification_status, is_independent — fingerprint_state/credit_state ignored); all route-local rules; calc.group_raise is dead code, deliberately undocumented; the generic Exception -> 422 fallback in app.py:85-92 left unpinned as an internal-error path.

### Pass B — group/plan/raise/clock/shared-helper routes (routes/groups.py, plans.py, raises.py, clock.py, helpers.py). Subagent summary, verbatim:

509 lines / 122,885 chars -> 509 lines / 127,391 chars (+4,506 chars, all in-paragraph; no new sections, no §3 HTTP/path tokens). All 12 pass-A edits verified still present byte-for-byte. 12 ambiguity-pins, 5 mismatch-revisions.
- §2.1 — revise — mismatch — the organizer-identity check does not run before request-body schema validation; impl defers it until schema + all path/body existence resolve, while still outranking every state/safety/fiscal band — middleware.py:37-48 via routes/plans.py:132
- §2.10 — revise — mismatch — band-1 list re-worded: identity check evaluated only after bands 2 and 3 — routes/plans.py:132
- §2.3 — insert — ambiguity — pagination validated before any filter value, so a bad limit beats a malformed boolean filter — routes/helpers.py:33, validation.py:113
- §2.4 — revise — ambiguity — clock endpoint answers 200 with data carrying current_utc and nothing else, in domain-datetime Z form — routes/clock.py:14-22
- §2.8 — insert — ambiguity — both version-expectation fields must be JSON integers >= 0; negative/non-integer is ERR_INVALID_REQUEST, not a stale-version rejection — routes/plans.py:39, routes/vendors.py:91
- §3.1 — insert — ambiguity — the officer-slot occupancy test reads every organizer row whatever its qualification standing, and fires after the stage gate — routes/groups.py:98-103
- §3.1 — insert — ambiguity — seating an organizer increments the group's version by one; the organizer row is written at version 1 — routes/groups.py:120-124
- §3.1 — insert — ambiguity — the outcome enum is dimension-specific, so ADVERSE on fingerprint / FLAGGED on credit is ERR_INVALID_REQUEST — routes/groups.py:132
- §3.1 — insert — ambiguity — ERR_BACKGROUND_ALREADY_RESOLVED outranks ERR_ADVERSE_FINDING_TYPE_REQUIRED; a supplied adverse_finding_type is stored even alongside CLEARED; omitting the key preserves the existing value — routes/groups.py:136-142
- §3.2 — revise — mismatch — a negative opening_tier1_capital_cents is ERR_INVALID_REQUEST, not ERR_OPENING_CAPITAL_BELOW_MINIMUM; plus the fixed order of the three payload tests — routes/plans.py:41,57-68
- §3.4 — insert — ambiguity — minimum-vs-target evaluated before offering capacity, both below the stage and one-live-raise gates — routes/raises.py:36-43
- §3.4 — insert — ambiguity — REFUND against a raise in STRUCTURING or REFUNDED reports ERR_RAISE_NOT_OPEN; the RELEASED bar is tested first — routes/raises.py:182-185
- §3.4 — insert — ambiguity — screening has no raise-status or group-stage gate at all, and every outcome bumps both the subscription's and the raise's version — routes/raises.py:196-217
- §3.8 — insert — ambiguity — all seven stage names are well-formed target_stage values, so cascade-only, current and terminal stages all report ERR_STAGE_TRANSITION_NOT_ALLOWED, never a schema failure — routes/groups.py:225-228
- §3.8 — revise — mismatch — pre-opening gate needs exactly two CONDITIONALLY_APPROVED filings and is satisfied by any raise of the group in ESCROW_LOCKED/RELEASED (creation order) — routes/groups.py:186-191 (calc.raise_in)
- §3.8 — revise — mismatch — opening-day gate needs exactly two FINAL_APPROVED filings and some raise in RELEASED — routes/groups.py:213-216
- §4 — insert — ambiguity — the 200 body always returns the path-addressed resource, never a parent or cascade victim — routes/groups.py:150,172,250, routes/raises.py:193,217
Verified-already-pinned: group create, waiver, _gate_filing_ready order, all six plan-submit gates and their order, scenario attach, raise open/lock/release gate orders, subscription create, FUND ordering, abandonment cascade, plan_revision_index/supersede rules.

### Pass C — filings/policies/vendors/exams/deviations/reads routes. Subagent summary, verbatim:

509 lines / 127,391 chars -> 509 lines / 130,209 chars (all in-paragraph). 7 ambiguity-pins, 4 mismatch-revisions.
Final completeness check: PASS. Document well-formed end to end, ends at a real section boundary (last content line | ERR_METHOD_NOT_ALLOWED | 405 |). §4 holds exactly one row per implemented endpoint: 59 impl routes vs 59 §4 rows, normalized path/method sets byte-identical (diff clean). §5 holds exactly the error ids the implementation can emit: 106 rows, set difference empty both directions. All 26 §2/§3 headers intact and in order; passes A and B edits untouched.
- §4 (organizers list row) — revise — mismatch — dropped the false "either background dimension" claim; narrows by group, board role, qualification status and the independence flag only — reads.py:105-110
- §3.3 — insert — ambiguity — computed capital-adequacy read's business_plan_id semantics: empty value = absent; a value naming no plan or a plan of another group, and a group with no governing plan, all report ERR_BUSINESS_PLAN_NOT_FOUND — reads.py:236-244
- §3.9 — insert — ambiguity — the lazy supervision-year refresh on a single-group read is not a version-bumping mutation — reads.py:22-25
- §3.5 — insert — ambiguity — supplied the missing error id for the group-stage gate on filing: ERR_GROUP_STAGE_LOCKED — filings.py:83-84
- §3.5 — insert — ambiguity — decision_note is retained on the filing, sticky when omitted, and not a serialized filing property — filings.py:116-117, serialize.py:149-161
- §3.6 — insert — mismatch — the examiner-authority boundary outranks ERR_FILING_ALREADY_FINAL, contrary to the §2.10 band-6-before-band-7 reading — filings.py:225-229
- §3.7 — insert — ambiguity — policy examiner review: omitting finding_note keeps the earlier note; ACCEPTED against an already EXAMINER_ACCEPTED policy is a legal status no-op that only bumps version — policies.py:81-87
- §3.7 — insert — ambiguity — all four contract statuses are well-formed target_status values, so EVALUATING/current/terminal targets are ERR_VENDOR_STATUS_TRANSITION_NOT_ALLOWED, never a schema failure — vendors.py:61-64
- §3.7 — insert — mismatch — on SELECTED, the due-diligence floor is evaluated before domain uniqueness — vendors.py:66-74
- §3.7 — insert — mismatch — conversion-window check order is duration ceiling -> capacity -> end-after-start -> start-not-in-past — vendors.py:99-108
- §3.8 — insert — mismatch — exam scope gates run ahead of both temporal bounds, and the buffer-extended conflict test runs last — exams.py:31-44
- §3.8 — insert — mismatch — the PASSED findings limit is evaluated before the window-start test — exams.py:71-74
Deliberately left alone: adopt_policy's identity-before-status ordering (covered by pass B's global §2.1 revision); prose-order-vs-ladder ordering in create_filing and create_policy (already pinned by §2.10 bands 6/8/9); calc.group_raise dead code.

### Orchestrator verification of Step 9

- PRD_COMPLETED.md is 509 lines / 130,209 chars vs PRD_FINALIZED.md 507 / 119,023 — 68 changed lines, +11,186 chars. NOT byte-identical to its source, so the scan demonstrably ran.
- File ends at a real section boundary (final §5 table row).
- Totals across the three passes: 30 ambiguity-pins, 10 mismatch-revisions.
- No code or test file was touched during Steps 8-9: newest implementation file is app.py at 05:28, newest test file is test_suite/conftest.py at 06:27, and the clean sweep's results.1.json is 06:30 — i.e. the 8/8 green sweep post-dates every code and test edit in the pipeline.
- Final sweep state re-confirmed independently: results.1..8.json all report passed 101 / total 101, failed 0, errors 0.

PIPELINE COMPLETE.

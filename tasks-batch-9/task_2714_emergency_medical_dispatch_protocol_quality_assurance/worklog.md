# Worklog — task_2714_emergency_medical_dispatch_protocol_quality_assurance

## Step 1: Create task directory — 2026-09-04T10:43:50.282Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2714_emergency_medical_dispatch_protocol_quality_assurance and its workspace/ subdirectory. Index 2714 was pre-assigned by the invoker; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T12:09:10.439Z

All three scaffold artifacts are complete and lint-clean.

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2714_emergency_medical_dispatch_protocol_quality_assurance/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2714_emergency_medical_dispatch_protocol_quality_assurance/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2714_emergency_medical_dispatch_protocol_quality_assurance/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    45
  §1.1 entities declared:     13
  §1.8 instances scanned:     25
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  902

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files**: `SCAFFOLD.yaml` 3006 lines, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` 2204 lines, `SCAFFOLD_CORNER_DESIGN.yaml` 3984 lines. `SCAFFOLD.yaml` contains neither design key; each design file has exactly one top-level key.

**§1.0–§1.7 scale:** 13 entities (AuditProgram, ProtocolVersion, ProtocolRollout, Dispatcher, CallRecord, SamplingPeriod, Review, ScoreSheet (immutable), Rebuttal, HighRiskCaseReview, CoachingPlan, RetrainingSession, AccreditationReport); 45 endpoints (18 GET / 27 write incl. `POST /_clock/set_current_utc`); 67 errors; 6 roles (segregation-of-duties model, Dispatcher entity-backed); complexity layers dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, derived_field_reconciliation, optimistic_concurrency, version_pinning_on_approval; 2 §1.2.1 concurrency rules.

**§1.8 — 9 rule ids / 25 instances:** dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 3, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 3.

**§1.9 — 9 sections / 80 instances (62 with recipes, 18 `excluded_because` stubs):** entities 11, state_machines 17 (8 real + 9 stubs), calculations 9 (5 + 4), validations 8 (7 + 1), endpoints 6, errors 14, rbac 6, cross_cutting_layers 8 (4 + 4), consistency_model 1. Every stub cites a difficulty_instance name that exists in the difficulty file; all 80 names are unique and disjoint from the 25 difficulty names. All 67 catalog errors are referenced by at least one instance.

**Design adjudications made this session:**
- **Scaffold repair for an untriggerable error.** `ERR_DUPLICATE_COACHING_PLAN` was unreachable: the `(dispatcher_id, source_review_id)` key is only written by `auto_coaching_plan_upsert`, which ratchets instead of failing, and `POST /coaching-plans` had no `source_review_id`. Since §1.4's existence rule and the `GET /coaching-plans` filter already assumed a client-supplied `source_review_id`, I added `source_review_id?` to that endpoint's input and changed `CoachingPlan.source_review_id` from `source: computed` to `source: input` (default null). The error is now triggered by a MANUAL plan naming a review that already carries an AUTO plan.
- **Priority correction.** The sampling-mode instance originally asserted `ERR_SAMPLING_MODE_MISMATCH` (priority 70) over `ERR_CALL_TYPE_MISMATCH` (priority 46); wrong per §1.4, so the RANDOM period was given the same call type and window as the TARGETED one, isolating the mode gate.
- **Bulk-action semantics** are pinned as skip-not-fail: pool 4, quota 2, `requested_count` 3 → `n = min(3,2,4) = 2` with stride `floor(4/3) = 1` and HTTP 201, with the follow-up draw returning `ERR_SAMPLE_QUOTA_FILLED`.
- **NOT_FOUND placement.** Six entities have no single-row GET, so their 404s are asserted on the action routes (`close`, `go-live`, `sign-off`, `decide`, `complete`, `submit`).
- **No list-ordering claim.** §1.5 declares no global sort, so the pagination instance asserts page disjointness, union and `total_count`/`has_more` consistency rather than a specific row order.
- Every asserted composite/ledger literal was script-verified (92.0, 88.0, rollup 180.0/90.0 GOOD, and the 79.1 → 2.0 penalty → 77.1 PROBATION path with a STANDARD 4.0h `PRE_ARRIVAL_INSTRUCTIONS` AUTO plan).

## Step 3: Copy shared files — 2026-09-04T12:09:30.787Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T12:24:00.000Z

The PRD is complete and verified.

## Output

`workspace/PRD.md` — **430 lines, 13,246 words**. Built with 10 chunked heredoc appends plus 3 targeted Edits; ends cleanly on the last §5 table row (`| \`ERR_NO_FINALIZED_REVIEWS_IN_WINDOW\` | 422 |`), no truncation, no audit footer.

## Section list

- **§1 Introduction** (3 paragraphs)
- **§2 Global Specifications & System-Wide Principles** (10 domain-derived subsections)
  - 2.1 Centre Personnel and Role-Based Access Control
  - 2.2 API Response Structure (byte-for-byte verbatim from `section-2.2-response-structure.md`)
  - 2.3 Pagination
  - 2.4 Resource Identity, Timestamps and the Logical Clock
  - 2.5 Nested Path Resolution and Programme Scope
  - 2.6 Precision and Rounding Discipline
  - 2.7 Optimistic Concurrency on Reviews and Dispatcher Ledgers
  - 2.8 Cascade Discipline and Derived-Field Reconciliation
  - 2.9 Order of Evaluation for Rejections (21-step ladder)
  - 2.10 Determinant Codes and What They Commit the Centre To
- **§3 Business Logic & Workflows** (9 subsections)
  - 3.1 Standing Up a QA Programme, the Roster and the Call Feed
  - 3.2 Protocol Content: Registration, Approval and the Governing Interval
  - 3.3 Retraining, Rollout Readiness and Go-Live
  - 3.4 Sampling Periods and Getting Cases onto Reviewers' Desks
  - 3.5 Scoring the Sheet: Sections, Percentages and Determinant Accuracy
  - 3.6 High-Risk Cases: Arrest Recognition and Dispatcher-Assisted CPR
  - 3.7 Disputes, Adjudication, Finalization and Reversal
  - 3.8 Coaching, Retraining Delivery and the Remediation Hours Ledger
  - 3.9 Accreditation Reporting, Locking the Record, and Reading Back
- **§4 Endpoint Definitions** — 45-row, exactly-4-column table (Method | Path | Description | Authorized Role(s))
- **§5 Error Code Catalogue** — 67-row, exactly-2-column table

## Hard Contract reports (transcript only — never written to any file)

**Contract 1 — Field-Name Coverage: PASS.** 152/152 entity fields, 84/84 request-body identifiers, 20/20 query params, 1/1 path param, all present in backticks. 0 missing.

**Contract 2 — Rule Coverage: PASS.** All 24 priority-ordered validations (conditions + error IDs + ordering), 46/46 state-machine transitions across 10 machines, 17/17 calculations with their exact formulas/constants/tie-breaks, 2/2 concurrency rules (each with write endpoint, OCC field, error ID and 412), all 27 side-effect-bearing endpoints, and sibling-branch symmetry (both composite variants, both DA-CPR weight profiles, all four cascades). All 67 error IDs appear in §2/§3 prose *before* the §5 table. Mechanically re-verified: §4 endpoint set and per-endpoint role sets match the scaffold exactly (0 diffs); §5 IDs and HTTP statuses match exactly (0 diffs, 0 extras).

**Contract 3 — §3 Path Purity: PASS.** 872 backtick tokens scanned in §3: 0 `/`-leading tokens, 0 bare HTTP methods, 0 method+path pairs. A raw `grep -E 'POST|GET /'` over the §3 line range returns nothing. The only paths named anywhere outside §4 are the two OCC `write_endpoint` values in §2.7, which Contract 3 does not police.

## Editorial judgement calls

1. **Pagination max.** `pagination_defaults` says max 100 while the validation entry says range `[1, 200]`; I documented 100, matching the skill's §2.3 derivation rule and `example-prd.md`.
2. **`high_risk` derivation** stated as a single three-way rule and applied identically to both case-selection routes, since the scaffold defines it once but exercises it from two entry points.
3. **`escalated_sample_floor`** documented as enforced at *period close* for a `PROBATION` dispatcher (per validation priority 75) rather than at period open (as the field description hints); the validation is the operative rule.
4. **`watch_floor_pct`** required strictly greater than 0.0, per validation 16, rather than the weaker "non-negative" reading of the field description.
5. **Section weights 0.20/0.35/0.30/0.15** presented as "a typical MPDS configuration" illustrating the normalization rule, not as a server default — the fields are required request inputs.
6. **`attendance_confirmed` false at completion** mapped to `ERR_INVALID_REQUEST`, since the scaffold names no dedicated error for that case.
7. **§3 organised into 9 subsections** by merging rebuttals, finalization and voiding into §3.7, to stay inside the 5–9 guidance; §2 uses 10 subsections, which the skill permits for domain-derived content (8–12).

Orchestrator verification: `tail -25` confirms the file ends on a complete §5 table row at a real section boundary — not truncated mid-sentence. No regeneration needed.


---

# Step 5 — Unit test suite generation

**Stage 1 — `test_helpers/` (9 files, 1853 lines).** `constants.py` (every PRD literal: clock start, program threshold defaults, pagination 1..100, priority ranks, penalty base points and tier multipliers, DA-CPR constants, severity hours, session buffer, enum lists, section-to-focus-area order), `api_errors.py` (68 error ids + `ERROR_HTTP_STATUS`, registered once at import via `set_error_http_status_map`), `test_users.py` (opaque-identity headers for the five non-entity roles + `make_dispatcher_headers` for the entity-backed Dispatcher role), `types.py` (13 entity TypedDicts; `ScoreSheet` deliberately carries only `id`/`created_at`), `api_client.py` (one method per declared endpoint, 45 endpoints), `assertions.py` (millisecond-tolerant instant comparison, decimal round-half-up, DA-CPR index re-derivation, score-sheet shape), `factories.py` (payload builders with an `OMIT` sentinel; all money/score values emitted as JSON numbers), `fixtures.py` (per-endpoint primitives, list-scan readers for the four entities with no single-row GET, and eight composite environments including the three cascade set-ups).

**Stage 2 — `test_suite/` (18 files + conftest, 8497 lines, 186 test functions, 218 collected cases).**
- Queue A (depth): 78 tests over all 25 difficulty instances, files `test_01`–`test_09`. Zero instances skipped.
- Queue B (breadth): 108 tests over all 62 non-stub corner instances, files `test_10`–`test_18`. Zero instances skipped. All 18 `excluded_because:` stubs translated to nothing; each stub's `difficulty_instance` cross-reference resolves to exactly one real depth instance.

**Verification.** `py_compile` clean on all 27 generated modules; `pytest --collect-only` collects 218 cases with no import or duplicate-name errors; every test function carries exactly one trailing `Design:` tag and all 186 tags resolve to a real design-index `name:` (no untagged, dual-tagged or dangling tags); all 443 quoted spans of 40+ characters in test docstrings were machine-matched verbatim against `workspace/PRD.md` (0 misses, every test has at least one); no `skip`/`xfail`/mock/unittest usage; nothing written under `workspace/`.

**Adjudications where the design index and the PRD disagreed (PRD wins in all cases).**
1. Pagination max asserted as 100 (PRD §2.3), not the 200 in the scaffold's validation range.
2. Rollout training dimension asserted as `NOT_STARTED`/`IN_PROGRESS`/`COMPLETE` (the PRD's declared value list) rather than the `TRAINING_*` transition labels used in the cascade prose.
3. `DACPR_CURRICULUM` is not a `protocol_family` value; curriculum versions use `LOCAL_CARDSET`.
4. `SYSTEMATIC_DRAW` is reserved for the random draw, so targeted selections use `COMPLAINT`/`NEW_HIRE_AUDIT`.
5. Rebuttal birth state asserted as `SUBMITTED` with `round_index` (not `PENDING`/`round_number`).
6. The unknown-program protocol-version case sends normalized weights, because weight normalization (priority 7) outranks path existence (priority 8), so the index's unnormalized payload would have produced a different error than it asserted.

**Sub-assertions dropped for non-unique-derivability (instance still covered otherwise).**
- "client input for `status`/`reviewer_id` is silently ignored" — the PRD never says unknown body fields are ignored rather than rejected.
- "`provisional_composite_score` is still 78.7 after finalization" — the PRD does not say whether the provisional field persists past finalization.
- "no second program was created" — no list-programs endpoint exists, so it is unobservable.

**Knife-edge for the implementation.** Several cases land on exact `.05` weighted sums (79.05 → 79.1, 89.049 → 89.0), so they only pass under decimal round-half-up, which is what the PRD mandates.
## Step 5: Generate unit tests — 2026-09-04T13:04:00.000Z

Test suite for task 2714 is complete and verified. Nothing was written under `workspace/`.

## Files written

`test_helpers/` — 1853 lines total: `__init__.py` 2, `api_client.py` 275 (one method per declared endpoint), `api_errors.py` 170 (68 error ids + status map registered at import), `assertions.py` 190, `constants.py` 131, `factories.py` 264, `fixtures.py` 512 (per-endpoint primitives, list-scan readers for the four entities with no single-row GET, eight composite environments), `test_users.py` 76, `types.py` 233.

`test_suite/` — `conftest.py` 24 plus 18 test modules, 8497 lines, 186 test functions, 218 collected cases:

| file | lines | tests | file | lines | tests |
|---|---|---|---|---|---|
| test_01_composite_score_variants | 290 | 6 | test_10_entity_shapes_and_reads | 570 | 14 |
| test_02_score_formula_composition | 351 | 9 | test_11_state_machine_guards | 492 | 9 |
| test_03_non_linear_state_machines | 412 | 9 | test_12_derived_calculations | 699 | 13 |
| test_04_transitive_cascades | 404 | 11 | test_13_field_validations | 508 | 13 |
| test_05_validation_precedence_pairs | 392 | 7 | test_14_endpoint_contracts | 541 | 12 |
| test_06_boundary_precision | 421 | 10 | test_15_error_catalogue | 1223 | 36 |
| test_07_cross_entity_state_gates | 375 | 9 | test_16_role_permissions | 452 | 6 |
| test_08_temporal_exclusivity | 353 | 7 | test_17_cross_cutting_layers | 452 | 4 |
| test_09_compensating_invariants | 380 | 10 | test_18_consistency_model | 157 | 1 |

## Coverage per queue

- Queue A (depth, §1.8): **78 tests / all 25 difficulty instances**, every instance with >=2 tests. `test_01`-`test_09`.
- Queue B (breadth, §1.9): **108 tests / all 62 non-stub corner instances**, every instance with >=1 test. `test_10`-`test_18`.
- All 18 `excluded_because:` stubs translated to nothing, and every stub's `difficulty_instance` cross-reference resolves to exactly one real depth instance.

## Instances SKIPPED

**None.** All 87 non-stub instances passed the PRD-first two-condition filter. Three individual sub-assertions were dropped for non-unique-derivability while their instance stayed covered: "client input for `status`/`reviewer_id` is silently ignored" (PRD never says unknown body fields are ignored rather than rejected), "`provisional_composite_score` is still 78.7 after finalization" (PRD is silent on whether the provisional field persists), and "no second program was created" (no list-programs endpoint, so unobservable).

## Verification performed

`py_compile` clean on all 27 modules; `pytest --collect-only` collects 218 cases with no import or duplicate-name errors; every test function carries exactly one trailing `Design:` line and all 186 tags resolve to a real design-index `name:` (zero untagged, dual-tagged or dangling); all 443 quoted spans of 40+ chars in test docstrings machine-matched verbatim against `workspace/PRD.md` with 0 misses and every test carrying at least one; no `skip`/`xfail`/mock/unittest anywhere; the words "scaffold"/"design index"/"instance"/"corner" appear nowhere outside the `Design:` lines; no strays under `workspace/`; caches removed.

## Adjudications where the design indices contradicted the PRD (PRD won)

Pagination max 100, not 200; rollout training values `NOT_STARTED`/`IN_PROGRESS`/`COMPLETE`, not the `TRAINING_*` transition labels; `DACPR_CURRICULUM` is not a `protocol_family` (used `LOCAL_CARDSET`); `SYSTEMATIC_DRAW` reserved for the random draw (targeted selections use `COMPLAINT`/`NEW_HIRE_AUDIT`); rebuttals are born `SUBMITTED` with `round_index`; and the unknown-program version case had to send normalized weights, since weight normalization (priority 7) outranks path existence (priority 8) and the index's own payload would have tripped the wrong error.

One flag for the implementation side: several cases land on exact `.05` sums (79.05 -> 79.1, 89.049 -> 89.0), so they pass only under the decimal round-half-up the PRD mandates, not binary float rounding.

Orchestrator note: verified `test_helpers/` and `test_suite/` both landed at the task root (not under `workspace/`), and that the subagent left no stray worklog entry of its own.

## Step 6: Generate implementation — 2026-09-04T13:04:00.000Z

The implementation is complete, compiles, boots, and passes two end-to-end functional smoke runs.

## Files written
All under `workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | `exec python3 app.py`, reads `$PORT`, guarded pip install, foreground |
| `requirements.txt` | 1 | `flask>=3.0` |
| `app.py` | 76 | app factory, 8 blueprints, `ApiError`/404/405/`HTTPException`/`Exception` handlers, binds `0.0.0.0:$PORT` (default 10000) |
| `store.py` | 91 | 13 in-memory dicts, logical clock (default `2026-08-01T00:00:00Z`), `base_row`, `touch` (one version bump per row per request), `order_rows` |
| `errors.py` | 105 | all 69 error ids -> HTTP status |
| `envelope.py` | 91 | meta/response_type/data envelope, 3-digit ISO, Decimal->float, pagination meta |
| `auth.py` | 58 | header auth, `require(*roles)` (ladder steps 1-2) |
| `validate.py` | 199 | body/field/typed getters, instant parsing, pagination (1..100) |
| `calc.py` | 240 | all scoring, penalty, DA-CPR, posture, systematic-stride math |
| `cascades.py` | 531 | all derived-field recomputations + Cascades A/B/C/D + AUTO-plan upsert |
| `helpers.py` | 81 | path/body id resolvers with per-entity 404 codes, list responder |
| `routes/programs.py` | 106 | programme + `/_clock/set_current_utc` |
| `routes/protocols.py` | 263 | versions, approve, rollouts, go-live |
| `routes/dispatchers.py` | 211 | enrol, certify, call ingest, lists |
| `routes/sampling.py` | 267 | periods, systematic draw, targeted selection, close |
| `routes/reviews.py` | 324 | scores, sheets, rebuttals, decide, finalize, void |
| `routes/highrisk.py` | 169 | clinical record, DA-CPR grading, sign-off |
| `routes/coaching.py` | 273 | manual plans, sessions, complete, cancel |
| `routes/reports.py` | 176 | both report variants, submit |

3272 lines total. **45 endpoints** mounted (verified by enumerating `url_map`: 18 GET / 27 POST, exactly matching PRD §4). Storage is in-memory dicts only; nothing is seeded, no disk or SQLite use.

## Verification performed
- `python3 -m py_compile` over all 18 `.py` files: clean.
- Two in-process end-to-end smokes covering: programme defaults, version approve/overlap, certify, call ingest, systematic draw (stride + quota clamp), score sheet round 1, rebuttal + reject, SoD-guarded finalize, Cascade A ledgers, DA-CPR index (`71.7` hand-checked), sentinel sign-off -> CRITICAL/DACPR plan + `RESTRICTED` privilege, session scheduling with the 45-minute closed buffer (overlap -> 409), complete/verify then cancel (credited hours returned to `0.00`, plan `VERIFIED -> IN_PROGRESS`), manual plan OCC (412 on stale version), both report variants, submit -> Cascade C (`ACCREDITED`, period `LOCKED`, the untouched `SELECTED` review voided with `PERIOD_LOCKED` and its call back to `INGESTED`), void of a finalized review restoring compliance to its pre-finalization value and cancelling the AUTO plan with `SOURCE_VOIDED`, go-live Cascade B (`ERR_TRAINING_INCOMPLETE` first, then `APPROVED -> ACTIVE` + prior version `SUPERSEDED`), plus 401/403/404/400-pagination paths. Zero unexpected results.
- Real boot: `PORT=51714 bash start.sh`, curled a 404, a 201 create and a 401; then killed only that server (pid 1340189 and its orphaned `python3 app.py` pid 1340191 by number). Port confirmed released; no broad `pkill` used.

## Ambiguities resolved by judgement
- **Ladder over prose** where §3 narrative order conflicts with §2.9 (scaffold priorities agree): SoD (#10) before state (#12) at finalize; go-live window before `ERR_TRAINING_INCOMPLETE`; `ERR_REBUTTAL_WINDOW_CLOSED` before `ERR_REBUTTAL_ROUNDS_EXHAUSTED`; stale-version above the state family; scope before version-usable.
- **Selection routes**: protocol pinning (`ERR_NO_PROTOCOL_VERSION_IN_FORCE`, step 14) is evaluated before mode mismatch / already-selected / quota / no-eligible-calls; safe because the drawn count is `min(requested, remaining, pool)`.
- **Within one rung**: scores -> `ERR_PERIOD_LOCKED` before `ERR_REVIEW_NOT_SCORABLE`; finalize -> `ERR_REVIEW_NOT_FINALIZABLE` before `ERR_PERIOD_LOCKED`; session complete -> session state, then `ERR_PLAN_NOT_OPEN`, then the not-yet-ended check (also `ERR_SESSION_NOT_COMPLETABLE`), following the PRD's own listing order.
- **`created_at`/`updated_at` come from the logical clock**, so every deadline (`review_deadline_days`, AUTO plan `due_at`) is harness-controllable.
- **Rebuttal UPHELD** returns the review to `SELECTED` and clears `provisional_composite_score`/`scored_at` but does **not** rewind `current_sheet_round` (sheets are append-only).
- **`ERR_REVIEW_ALREADY_VOIDED`** is raised only on the void endpoint and on rebuttal-decide with a voided parent; a non-`DISPUTED` live parent yields `ERR_REVIEW_NOT_DISPUTABLE`.
- **Sign-off plan ladder runs with the posture clauses disabled** (no posture is recomputed at sign-off), so only the sentinel and coaching-only-failed clauses can fire there; the owed-hours ledger is recomputed on both branches because a plan may have been created, while sentinel counters move only on the sentinel branch.
- **Manual plan create explicitly bumps the dispatcher `version`** even when the recomputed ledger lands on identical numbers, as §3.8 states.
- **Cancelling a `SCHEDULED` session moves no ledger at all**; only cancelling a `COMPLETED` one recomputes (reading "either way" as the two sub-cases of the completed branch).
- HRCR creation has no state or `high_risk` precondition (only `ERR_DUPLICATE_HIGH_RISK_REVIEW`); `version_label` uniqueness is not enforced (no error id exists); pagination max is 100 per PRD, not the scaffold's 200; session-overlap widens only the new window, closed comparison, against all `SCHEDULED`/`COMPLETED` sessions of that dispatcher across every plan.


## Step 7 — stability sweep (iterate-until-green)

Iteration 1 (only iteration): 8-round parallel sweep, all rounds launched concurrently
under `setsid nohup` and joined with `wait`.

```
prd-bench-local-run --start-command "cd workspace/implementation && bash start.sh" \
  --test-dir test_suite --isolation per-test-server --timeout 120 --test-timeout 30 \
  --results-file workspace/implementation/results.$i.json      # i = 1..8, concurrent
```

Result: all 8 rounds `total=218 passed=218 failed=0 errors=0 skipped=0`
(~384 s wall per round; union of non-passing tests across the 8 rounds is empty).

No test deleted, no `test_helpers/` change, no `implementation/` change — the suite was
green on the first sweep and stable across all 8 concurrent rounds, so the diagnostic
protocol (STEP 0 union set) had nothing to act on. Re-verified: no `skip`/`xfail` anywhere
in `test_suite/` or `test_helpers/`, and no on-disk persistence (`sqlite3`, file `open(`,
`json.dump`, `/tmp`, `pickle`, `shelve`, `redis`) anywhere in `workspace/implementation/`.
The 8 `results.$i.json` files are left in place under `workspace/implementation/`.

## Step 7: Run tests and iterate — 2026-09-04T13:32:00.000Z

The loop is complete — the suite went green on the first sweep and stayed green across all 8 concurrent rounds.

## Summary

**Iterations run: 1** (one 8-round parallel stability sweep; no fixes were needed, so no re-run was required).

**Sweep result** — all 8 rounds identical and fully green:

| round | total | passed | failed | errors | skipped | duration |
|---|---|---|---|---|---|---|
| 1-8 | 218 | 218 | 0 | 0 | 0 | ~384 s each |

Union of non-passing tests across all 8 rounds: **empty**. No round-specific (timing-sensitive) failure appeared, so there is no flakiness signal to chase.

**Tests deleted:** none. The STEP 0 union set was empty, so STEP 1a/1b/1c adjudication had nothing to operate on — no PRD-silence or collapse-pattern deletions were warranted.

**Fixes to `test_helpers/`:** none.

**Fixes to `implementation/`:** none.

**Artifacts left on disk** (as required):
`workspace/implementation/results.1.json` ... `results.8.json` (all timestamped Sep 4 13:22, 70292-70304 bytes).

**Guard checks re-verified after the sweep:**
- No `pytest.mark.skip`, `xfail`, or `pytest.skip` anywhere in `test_suite/` or `test_helpers/`.
- No on-disk persistence in `workspace/implementation/` — no `sqlite3`, no file `open(`, no `json.dump`, no `/tmp` cache, no `pickle`/`shelve`/`redis`. Storage is in-memory dicts only (`workspace/implementation/store.py`).
- 186 test functions across the 18 test modules expand to the 218 parametrized cases the runner collects.

**Process note for the caller:** the prescribed launch command detaches rather than blocking, because `setsid` forks when the calling shell is already a process-group leader — the Bash call returns immediately with a non-zero exit from the trailing `ls` (no results files exist yet). That is expected, not a failure; the sweep must then be joined by polling `ls -la` on `results.*.json` until all 8 exist. Also worth flagging: in these results files the per-test outcome key is `status` (values `passed`/`failed`), not `outcome` — reading `outcome` yields `None` for every test and makes a fully green sweep look like a total wipeout. The authoritative per-round counters are the top-level `total`/`passed`/`failed`/`errors`/`skipped`.

### Orchestrator's independent verification of the sweep artifacts

Per the known failure mode where a Step 7 subagent claims a clean sweep while leaving no usable artifacts, the orchestrator re-read all 8 `results.$i.json` itself rather than trusting the report: every file exists on disk (70292-70304 bytes, mtime Sep 4 13:22) and each reports `passed == total == 218`. Confirmed, not taken on faith.

## Step 8: Finalize PRD — 2026-09-04T13:33:00.000Z — SKIPPED

Skipped per the skill's explicit skip condition. Step 7 exited on its FIRST 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes — zero iterations beyond the baseline. With an empty `<step_7_diff>` there is no Step-7-derived evidence of PRD silence or PRD/implementation mismatch for Step 8 to patch, and the skill forbids spawning it in this case (any edit it made would be out of its hard scope). No `PRD_FINALIZED.md` is produced; Step 9 therefore takes `workspace/PRD.md` as its source, which the skill provides for explicitly. Residual PRD silences that never produced a Step 7 failure signal are exactly what Step 9's full implementation scan exists to close.

## Step 9: Complete PRD — 2026-09-04T14:20:00.000Z

Ran as **three sequential, module-partitioned passes** over one shared `PRD_COMPLETED.md` (a single agent scanning 3,272 lines of implementation against a 430-line PRD reliably under-scans; a byte-identical output would mean the scan never ran). Pass 1 owned Step 0's `cp`; passes 2 and 3 were explicitly forbidden from re-copying, and each read the live `PRD_COMPLETED.md` so it saw the prior passes' edits.

**Partition**
- Pass 1 — `app.py`, `store.py`, `errors.py`, `envelope.py`, `auth.py`, `validate.py`, `helpers.py`, `routes/programs.py`, `routes/protocols.py`, `routes/dispatchers.py`
- Pass 2 — `calc.py`, `cascades.py`, `routes/sampling.py`, `routes/reviews.py`
- Pass 3 — `routes/highrisk.py`, `routes/coaching.py`, `routes/reports.py` (plus the whole-document closing integrity check)

**Size:** PRD.md 430 lines / 94,256 chars -> PRD_COMPLETED.md 431 lines / 106,553 chars (**+1 line, +12,297 chars, 38 changed hunks**). No new sections; all edits in-paragraph.

**Totals: 41 edits — 33 ambiguity-pins, 8 mismatch-revisions** (pass 1: 16 edits / 14 pins / 3 mismatches, two edits carrying both; pass 2: 15 edits / 12 pins / 3 mismatches; pass 3: 9 edits / 7 pins / 2 mismatches; plus 1 orchestrator correction below).

### Pass 1 changes
- `§2.1 RBAC` — revise — ambiguity — empty/whitespace-only header treated as absent; role compared case-sensitively after trimming; `X-User-ID` trimmed and otherwise unconstrained — `auth.py:27-36`
- `§2.2` — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-ASCII/digit chars — `envelope.py:12-13`
- `§2.2` — revise — ambiguity — `api_request_timestamp` reads the host's real clock, not the logical clock — `envelope.py:53-55`
- `§2.2` — insert — ambiguity — trailing slashes accepted; unrouted path -> `ERR_INVALID_REQUEST` at 404, disallowed method -> same id at 405 — `app.py:26,45-53`
- `§2.3` — revise — ambiguity — `created_at` ties broken by ascending server insertion order (order total and stable) — `store.py:91`, `helpers.py:80`
- `§2.4` — revise — **mismatch** — `created_at`/`updated_at` are logical-clock readings, not host time — `store.py:55-63,85`
- `§2.4` — revise — ambiguity — logical-clock-field list made non-exclusive of `created_at`/`updated_at` — `store.py:59,85`
- `§2.4` — revise — ambiguity — `to_iso8601` required, clock may move backwards, 200 with `data` holding only `current_utc` — `routes/programs.py:100-106`
- `§2.4` — insert — ambiguity — accepted ISO spellings pinned (JSON string; date-only -> midnight UTC; seconds/fraction/zone optional; `±hh:mm` normalised; 1-9 fractional digits, sub-microsecond truncation) — `validate.py:12-63`
- `§2.8` — insert — ambiguity — a no-op recomputation is not a mutation; a row written repeatedly in one request is versioned exactly once — `store.py:66-86`, `cascades.py:18-27`
- `§3.1` — insert — ambiguity — thresholds rounded to 1 dp *before* the coherence relations are evaluated — `routes/programs.py:54-69`
- `§3.1` — revise — ambiguity — `employee_code` uniqueness is exact case-sensitive equality, untrimmed — `routes/dispatchers.py:38-46`
- `§3.1` — revise — ambiguity — `call_reference` global uniqueness is exact case-sensitive equality — `routes/dispatchers.py:169-174`
- `§3.2` — revise — **mismatch** — `version_label` uniqueness within programme+family is NOT enforced (no check, no error code) — `routes/protocols.py:55-98`
- `§3.2` — insert — ambiguity — each weight rounded to 4 dp first, then negativity and sum-to-1.0000 tested on the rounded values — `routes/protocols.py:64-75`
- `§3.3` — revise — ambiguity — certifying an already-`CERTIFIED` dispatcher is a permitted self-loop; explicit `certified_at` stored verbatim — `routes/dispatchers.py:109-123`
- `§3.3` — insert — ambiguity — `ERR_GOLIVE_WINDOW_NOT_OPEN` outranks `ERR_TRAINING_INCOMPLETE` — `routes/protocols.py:253-259`
- `§3.9` — revise — **mismatch** — no read endpoint applies an ownership check; `ERR_NOT_CASE_OWNER` guards rebuttal filing alone — `routes/dispatchers.py:71-74`, cross-checked `routes/reviews.py:41,150,168,204`, `routes/coaching.py:105,194`
- `§3.9` — insert — ambiguity — filters are unvalidated equality tests (unmatched value -> empty page, not an error); `high_risk` accepts `true/false/1/0` case-insensitively; unknown query params ignored — `helpers.py:68-75`, `validate.py:190-199`

### Pass 2 changes
- `§2.7` — insert — ambiguity — version comparand must be an integer >= 0; missing/non-integer/negative is `ERR_INVALID_REQUEST`, not a 412 — `routes/reviews.py:66`, `routes/coaching.py:47`
- `§3.4` — insert — ambiguity — `sampling_mode` is required with no default — `routes/sampling.py:74`
- `§3.4` — insert — ambiguity — drawn positions written in ascending pool order; draw answers 201 with `response_type` `array` and no pagination fields in `meta` — `calc.py:240`, `routes/sampling.py:157-184`, `envelope.py:73`
- `§3.4` — insert — ambiguity — `ERR_CALL_ALREADY_SELECTED` outranks a `sampling_mode` offence and a filled quota on the same request — `routes/sampling.py:219-227`
- `§3.4` — insert — ambiguity — the protocol pin resolves only for calls the stride drew, and all pins resolve before any write (a refused draw leaves no partial selection) — `routes/sampling.py:156-168`
- `§3.4` — insert — ambiguity — the PROBATION scan at close considers every review of the period except those already `VOIDED` — `routes/sampling.py:249-255`
- `§3.5` — insert — ambiguity — the period lock is tested before the review's own status (`DISPUTED` review in a locked period -> `ERR_PERIOD_LOCKED`) — `routes/reviews.py:96-100`
- `§3.5` — insert — ambiguity — submission returns the newly created score sheet at 201, not the review — `routes/reviews.py:146`
- `§3.7` — insert — ambiguity — window-closed outranks rounds-exhausted, reversing the prose order — `routes/reviews.py:174-179`
- `§3.7` — insert — ambiguity — voided parent -> `ERR_REVIEW_ALREADY_VOIDED`; any other non-`DISPUTED` parent -> `ERR_REVIEW_NOT_DISPUTABLE` — `routes/reviews.py:228-232`
- `§3.7` — insert — ambiguity — the five finalization preconditions are not in precedence order; segregation of duties fires above the state family — `routes/reviews.py:257-265`
- `§3.7` — revise — **mismatch** — "voiding from `SELECTED` has no ledger consequences at all" was false: a void with a `SENTINEL_EVENT` record recomputes sentinel counters and re-derives owed hours/privilege — `cascades.py:409-414`
- `§3.8` — revise — **mismatch** — the two posture clauses fire only on the finalization trigger — `cascades.py:253-277`, `routes/highrisk.py:158`
- `§3.8` — revise — **mismatch** — "at most one automatic plan per pairing" narrowed to at most one in a live or `VERIFIED` state — `cascades.py:280-293`
- `§3.9` — insert — ambiguity — where `window_end`, `created_at` and `submitted_at` all tie, the earliest-minted report wins — `cascades.py:471-483`

### Pass 3 changes
- `§3.6` — revise — **mismatch** — the finalization gate reads the review's `high_risk` flag, not record existence; opening tests neither `high_risk` nor status, and a `PENDING` record on a non-high-risk review blocks nothing — `routes/highrisk.py:25-60`, cross-checked `routes/reviews.py:271-275`
- `§3.6` — insert — ambiguity — parent-review gate is `ERR_REVIEW_NOT_SCORABLE`, with the record's own status tested first so `ERR_HRCR_NOT_SCORABLE` wins when both are violated — `routes/highrisk.py:99-106`
- `§3.6` — insert — ambiguity — sign-off is not gated on the parent review's status; `director_notes` written (null when omitted) — `routes/highrisk.py:119-148`
- `§3.6` — insert — ambiguity — `remediation_hours_owed` and `dispatch_privilege` are recomputed on the coaching-only branch too — `routes/highrisk.py:166-168`
- `§3.8` — insert — ambiguity — the `ERR_DUPLICATE_COACHING_PLAN` collision reads existence the way the upsert does, so a `CANCELLED` auto plan does not collide — `routes/coaching.py:63-69` via `cascades.py:280-293`
- `§3.8` — insert — **mismatch** — session scheduling's real precedence contradicts the §2.9 ladder twice (`ERR_PLAN_NOT_OPEN` after scope/trainability; `ERR_INVALID_TIME_WINDOW` before `ERR_SESSION_WINDOW_OVERLAP`); pinned as an endpoint-local exception — `routes/coaching.py:143-168`
- `§3.8` — insert — ambiguity — `ERR_PLAN_NOT_OPEN` for the plan gate, `ERR_SESSION_NOT_COMPLETABLE` for the not-yet-ended gate, session-then-plan-then-clock order — `routes/coaching.py:233-239`
- `§3.8` — revise — **mismatch** — "Either way the dispatcher's owed hours and privilege are recomputed" was false (the settle runs only when the session was `COMPLETED`); cancellation gated on the session's own status alone — `routes/coaching.py:261-273`
- `§3.9` — insert — ambiguity — building is not exclusive; repeated builds over the same programme/window each mint a further `DRAFT` row — `routes/reports.py:79-136`

### Orchestrator correction after pass 3 (1 edit)
Pass 3 flagged, but deliberately did not touch, a **false universal claim pass 2 had introduced** in §3.8: that `determinant_accuracy` "is still null at sign-off — so a sign-off can reach only the sentinel clause or the coaching-only clause". The orchestrator read `cascades.py:253-277` directly and confirmed the `UNDER_TRIAGE` accuracy clause is NOT gated by `use_posture` (only the two posture clauses are, at `cascades.py:267`), while sign-off has no parent-review-status gate and a record may be opened on a finalized review. The claim was therefore wrong on a reachable path — precisely the class of defect Step 9 exists to remove, and left in place it would have read as a genuine PRD/impl divergence.
- `§3.8` — revise — **mismatch** — the accuracy and sentinel clauses are consulted on BOTH triggers; the ordinary sign-off-before-finalization path still reaches only sentinel/coaching-only because `determinant_accuracy` is null there, but a sign-off on a review already finalized as `UNDER_TRIAGE` does fire the accuracy clause — `cascades.py:262-267`

### Closing integrity check (pass 3, re-verified independently by the orchestrator)
- 431 lines / 106,553 chars; **not** byte-identical to `PRD.md` (`cmp` differs, 38 changed hunks) — the scan demonstrably ran.
- Ends at a real section boundary: the last §5 table row `| ERR_NO_FINALIZED_REVIEWS_IN_WINDOW | 422 |`. Not truncated.
- §4 endpoint table still 45 rows (46 lines incl. header); §5 error table still 67 rows. Section headings unchanged (5 `##`, 19 `###`).
- No duplicated or orphaned sentence fragments from three passes editing one document: repeated-8-word-run and double-punctuation scans returned only benign hits; every edited paragraph read back in full; one self-inflicted grammatical collision in §3.6 (a third consecutive em-dash clause) repaired to a semicolon.

Pipeline complete. `workspace/PRD_COMPLETED.md` is written.

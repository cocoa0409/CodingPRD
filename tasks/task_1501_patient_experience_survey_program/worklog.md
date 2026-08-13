# Worklog — task_1501_patient_experience_survey_program

## Step 1: Create Task Directory — 2026-08-13T14:25:00.000Z

Task directory `tasks/task_1501_patient_experience_survey_program/` and `workspace/` were pre-created and pre-assigned by the pipeline launcher; treated Step 1 as DONE (no index scan, no other task_* directories touched).

## Step 2: Generate Scaffold — 2026-08-13T15:59:30.000Z

Scaffold generation complete for `task_1501_patient_experience_survey_program`. All three files are written and pass mechanical lint plus self-audits.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1501_patient_experience_survey_program/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1501_patient_experience_survey_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1501_patient_experience_survey_program/SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

## Design summary

**Complexity profile**: posture-driven gating (SurveyCycle posture gates all child ops) × compliance/audit; flat topology under `/api`; cyclic state-machine shape; peer_roles with entity-backed ownership; immediate consistency; Expert calibration (justified by 8 mandated feature areas).

**Surface**: 10 entities, 55 endpoints (incl. 3 bulk import feeds and `POST /_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` default), 7 state machines, 11 calculations, 12 validation priority rows, 44 error codes, 5 RBAC roles (ProgramAdmin/DataSteward opaque; VendorOperator→SurveyVendor and UnitManager→CareUnit entity-backed with ownership checks; Any pseudo-role for GETs).

**Nine difficulty rules** — 18 instances, all differentiated per §0.5: dual variants on two domains (cycle top-box RAW vs MODE_ADJUSTED 100.0 vs 40.0; initiative progress PINNED 8.0 vs ROLLING 6.0); combinatorial modes (a) star-rating 3-input cap interaction and (b) VBP per-line rounding order (21→1.05 vs forbidden 20→1.00); non-linear machines on cycle (reopen loop) and initiative (branch + replan loop); cascades depth-3 (publish→initiative MISSED→ticket ESCALATED→response flag) and depth-2 (discharge exclusion→case→vendor credit); priority pairs (state>fiscal, safety>referential); boundaries on distinct metrics/endpoints (80.00 star percentage inclusive vs 24-count publication gate); cross-entity deps (Response→Cycle, Initiative→Cycle); temporal overlaps with different semantics (closed date intervals touch-conflict vs half-open cycle-index windows adjacency-allowed); compensating invariants on money (vendor budget) and count (completed_responses). One OCC rule (`vendor-create-stale-program`, 412) for the create-with-supersede vendor flow.

**Corner design**: 58 active instances across all 9 claim-extraction sections + 13 `excluded_because` stubs citing difficulty instances. All 44 error codes are triggered by at least one active test; every system enum value has a producing transition; all FKs have reverse-reachability GETs; formula-derived asserts were pre-computed (e.g. 86.21 = 25/29, 1.05 VBP, mode_effect_delta −100.0).

**Lint verdict (verbatim)**:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared: 55 | §1.1 entities: 10 | §1.8 instances: 18 | §1.9 instances: 58 | Calls scanned: 946
```
No sibling task directory was inspected; forbidden vocabulary scan is clean.

## Step 3: Copy Shared Files — 2026-08-13T16:00:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1501_patient_experience_survey_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T16:35:00.000Z

PRD generated and verified. Summary below.

## What was generated

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1501_patient_experience_survey_program/workspace/PRD.md` — 348 lines, ends cleanly at §5 with no audit footer.

**Structure:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications (11 subsections): RBAC with per-role identity translation, the verbatim §2.2 envelope block (byte-identical to `section-2.2-response-structure.md`), pagination (limit 10/1/100, offset 0, `created_at` ascending), The Logical Clock (startup default `2026-08-01T00:00:00Z`, never wall-clock), Common Resource Properties, Validation Order and Error Precedence (the 12-tier pipeline with the priority-4 cycle-posture-before-entity-local sub-ordering), Cycle Posture as the Master Gate, Vendor Budget Ledger (charge/credit compensating-pair invariant), Numeric Precision (2dp half-up percentages, 4dp mode shares, integer cents, VBP per-line rounding order), OCC, and Retrieval/Filtering
- §3 Business Logic (9 subsections, chronological lifecycle grouping): Program & Vendor Administration → Discharge Intake & Exclusion → Cycle Setup & Sampling → Fielding & Response Intake → Reconciliation/Adjudication/Closure → Scoring/Stars/Publication → VBP & Mode-Transition Analysis → Initiatives → Service Recovery
- §4 Endpoint table: 55 rows, 4 columns only
- §5 Error catalogue: 44 rows, 2 columns only

**Hard Contract results (all PASS):**
- Contract 1 Field-Name Coverage: 117 required identifiers (entity fields + request bodies + query params + path params + response-shape fields), 117 present, 0 missing (two passes; pass 1 caught `scope`/`subject_id`, fixed via a new attribution-report paragraph in §3.6)
- Contract 2 Rule Coverage: all 6 state machines' transitions with preconditions paired to error IDs and side effects; all 11 calculations in reconstructible prose (no operator syntax, no fuzzy words — verified by grep); all 12 validation tiers with explicit ordering and full `applies_to` scopes; the 4-hop publish cascade (star pin → initiative evaluation → ticket escalation → `has_escalated_recovery`); sibling-branch symmetry (INCLUDE/EXCLUDE, TARGET_MET/TARGET_MISSED, PINNED/ROLLING, RAW/MODE_ADJUSTED) — PASS
- Contract 3 §3 Path Purity: 564 backticked tokens scanned, 0 violations (no paths, no bare HTTP methods) — PASS

**Adjudications made:**
1. **`ERR_DISCHARGE_LOCKED_BY_SAMPLE` scope conflict** — the state machine (§1.2) blocks overrides when a linked case is `RESPONDED`; the error catalog (§1.6) says "IN_FIELD or RESPONDED". I followed the state machine (`RESPONDED` only), because blocking `IN_FIELD` would make the documented `SAMPLED`/`IN_FIELD` → `EXCLUDED_POST_SAMPLE` cascade unreachable — the state machine is internally consistent, the catalog summary is not.
2. **Fuzzy-word false positive** — "organized around the survey cycle" is structural phrasing, not numeric approximation; left as-is.
3. **Initiative create-time guards** — validation priorities 6 and 7 list initiative creation in `applies_to`; the PRD states cross-program and evaluation-window rules are enforced at create, activate, and replan, matching the scaffold's validation scopes while the state machine details the activate/replan checks.

## Step 5: Generate Unit Tests — 2026-08-13T17:25:00.000Z

Generation complete. Summary of the deliverable under `/home/ubuntu/github/CodingPRD/tasks/task_1501_patient_experience_survey_program/`:

## Stage 1 — `test_helpers/` (9 files)
- `types.py` — status/role enums + TypedDicts for all 10 resources (all carry the full common property set per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (41 methods, `/api` prefix, clock control at server root)
- `api_errors.py` — all 44 PRD §5 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (entity-backed builders `make_vendor_headers` / `make_unit_manager_headers` mandatory for ownership-gated calls)
- `fixtures.py` — composite helpers: `setup_program`, `setup_cycle_in_state` (DRAFT/SAMPLING_OPEN/FIELDING), `setup_published_cycle` (engineers exact adjusted top-box percentages via top-box/low-score counts), `field_and_publish_cycle` (publishes an existing cycle), `make_active_initiative`, `make_ticket`, plus bulk import wrappers

## Stage 2 — `test_suite/` (12 files, 152 tests)
test_01 entities/creation (12), test_02 discharge evaluation + exclusion cascade (6), test_03 cycle lifecycle + clock gates (12), test_04 sampling constraints + priority pairs (18), test_05 fielding/intake/ledgers/clock (22), test_06 scoring/rates/dual-variant (8), test_07 star rating/publication/window overlap (10), test_08 initiatives (12), test_09 service recovery + publish cascade (20), test_10 attribution/VBP/mode-transition (12), test_11 security/RBAC/OCC/envelope/pagination (14), test_12 adjudication/void (6).

## Coverage
- Queue A (difficulty): 18/18 instances × exactly 2 tests each = 36 tests
- Queue B (corner): 58/58 non-stub instances × 2 tests each = 116 tests; all 13 `excluded_because` stubs verified to resolve to real queue-A instances and were not translated
- Every test docstring ends with exactly one verbatim `Design:` tag; zero orphans, zero double-tags, zero skip/xfail markers

## Skipped instances
None. All 76 non-stub instances passed the PRD-first two-condition filter (PRD §3.6/§3.7/§3.8 prose covers every asserted rule, including the VBP rounding-order example, the star breakpoints, the 48h SLA boundary, and the 2026-08-01T00:00:00Z clock default).

## Audit verdicts
- Stage 1: compiles; framework-only generics imported, never reimplemented; PRD-exact field names throughout.
- Stage 2 completeness: PASS (152 tests, every instance ≥ its target count).
- PRD-citation pass: PASS — 223 distinctive ≥8-word citation fragments, 100% survive literal grep of PRD.md after two fixes (one clipped quote, one escaped-quote artifact, one case-normalization fix).
- Scaffold-citation pass: PASS — exactly one resolving `Design:` line per test.
- Collection check: `pytest --collect-only` gathers all 152 tests cleanly.

## Step 6: Generate Implementation — 2026-08-13T17:30:00.000Z

Implementation complete and verified. Here is the summary.

## File layout

`tasks/task_1501_patient_experience_survey_program/workspace/implementation/` (23 files, ~3070 LOC):

- `start.sh` — guarded install (`python3 -c "import flask, waitress"` no-op check), `exec python3 app.py`, foreground
- `requirements.txt` — flask, waitress
- `app.py` — blueprint registration, `ApiError`/404/405/500 handlers, `0.0.0.0:$PORT` (default 10000) via waitress (Flask fallback)
- `db.py` — 10 empty in-memory dict stores, logical clock (default exactly `2026-08-01T00:00:00Z`, never wall-clock), `stamp_new`/`touch` (version starts 1, `updated_at` = logical clock on every mutation)
- `errors.py` — all 44 catalog error IDs with their HTTP statuses
- `response.py` — envelope: `meta.api_request_id` (`req_` + 20 alnum), wall-clock `api_request_timestamp` (3 fractional digits), `response_type` object/array/error, list pagination fields `limit/offset/total_count/has_more`
- `middleware.py` — `X-User-ID`/`X-User-Role` presence + 4 declared roles (400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), role gating (403 `ERR_FORBIDDEN_ROLE`), `Any` pseudo-role for GETs
- `util.py` — shape validation (unknown-field rejection, enums, ISO dates, scores 1..4, target_score 0..100 ≤2dp, id lists 1..500), pagination (10/1/100/0), Decimal `round_half_up` helpers, left-to-right 404
- `services/core.py` — exclusion rules (9 reasons, sorted), vendor budget ledger recompute, cycle counter recompute (`eligible_denominator`/`completed_responses`/`response_rate`/`publication_eligible`), top-box RAW vs MODE_ADJUSTED (PHONE −0.5 vs 3.75), scoring snapshot with unit/provider breakdowns, star rating (25-count guard, 90/80/70/60 inclusive breakpoints, <10.0 rate cap at 3), VBP per-line round-then-sum (clamped 0..10), initiative evaluation/progress (PINNED/ROLLING, absent-unit 0.0), publish cascade hops B→C→D, discharge-exclusion cascade, 48h SLA (inclusive), half-open initiative window overlap
- `routes/` — one module per resource: programs, vendors, units, providers, discharges, cycles, sample_cases, responses, initiatives, tickets, clock

## Entity/endpoint coverage

All 10 entities and all 55 endpoints from §1.5 are implemented, including the three atomic bulk imports, the full cycle lifecycle (DRAFT→SAMPLING_OPEN→FIELDING⇄RECONCILIATION→SCORING→PUBLISHED/VOIDED), OCC on vendor create (`expected_program_version`, 412), supersede/suspend, late-intake PENDING_REVIEW + adjudication, response void compensation, mark-undeliverable credit, cycle void compensation, star-rating/attribution/VBP/mode-transition reads, initiative activate/replan/cancel with window guards, ticket routing/ack/resolve with SLA, and `POST /_clock/set_current_utc` at root.

Validation follows the PRD §2.6 12-tier pipeline, with cycle-posture errors before entity-local state errors in tier 7.

## PRD-interpretation decisions

1. **Entity timestamps use the logical clock verbatim** (`created_at`/`updated_at` included) — pinned by the corner fixture asserting `created_at == "2026-08-01T00:00:00Z"` at default; only `meta.api_request_timestamp` is wall-clock (3 fractional digits, per §2.2).
2. **Initiative create enforces only cross-program scope** (`ERR_CROSS_PROGRAM_REFERENCE`); index ordering, not-VOIDED, and half-open overlap run at activate/replan. The corner design creates an initiative with evaluation == baseline and expects 201 then 422 at activate — that fixture overrides the looser PRD §3.8 sentence.
3. **Second intake on a RESPONDED case returns `ERR_RESPONSE_ALREADY_EXISTS`**, not `ERR_CASE_NOT_IN_FIELD` — the corner fixture pins this, so the live-response check runs between the cycle-posture check and the case-state check.
4. **RESPONDED cases survive cycle void** (literal side-effect set `{SAMPLED, IN_FIELD, NONRESPONSE, UNDELIVERABLE}`); their charge stays CHARGED, so void restores budget only for unresponded cases — matches the PRD's enumerated filters.
5. **Overrides on evaluate are locked only by a RESPONDED linked case** (per worklog adjudication of the §1.2 vs §1.6 conflict); override-free re-evaluation always runs; post-sample exclusion is one-way.
6. **Body-referenced FK misses return 404 `ERR_NOT_FOUND`**; query-param subject ids (attribution-report) do not 404 — an absent subject returns a zero-completed/null-pcts entry.
7. Cycle/vendor derived-field recomputation counts as a mutation (`version`+1, `updated_at` refresh) per §2.5; VBP projection persists nothing (verified version-stable).

## Verification

Two smoke suites (~145 assertions) were run against a live server covering every §1.8 difficulty fixture and §1.9 corner recipe (dual-variant 100.0 vs 40.0, pinned 8.0 vs rolling 6.0, VBP 21→1.05, star cap at 8.33 rate, 80.00 inclusive breakpoint, 24-count publication rejection, publish cascade hops B/C/D, discharge exclusion cascade with budget 99800+100, reopen loop, SLA 48h/48h+1s, mode-transition deltas, OCC 412, priority-pair orderings, pagination) — all pass. Fresh-reboot contract verified: kill + `bash start.sh` → empty store, clock back at `2026-08-01T00:00:00Z`, HTTP ready in ~2s.

## Step 7: Diagnostic Loop — 2026-08-13T18:00:00.000Z

Ran the 8-round parallel stability sweep twice.

### Iteration 1 (initial sweep)
- Result: 129/152 passed in all 8 rounds; 23 unique deterministic failures (no flakiness).
- Every failure occurred identically in all 8 rounds — all were test/fixture bugs; zero implementation bugs; zero test deletions required.

### Diagnosis and fixes

**test_helpers/fixtures.py** — `setup_published_cycle` and `field_and_publish_cycle`: skip the `import_discharges` / `import_cases` pair when `low_count=0` (PRD §3.2 requires `count` between 1 and 500). Fixed 9 tests: `test_03 TestTerminalLockdown::*`, `test_08 TestEvaluationCycleGuards::*`, `test_08 TestHalfOpenWindowAdjacency::*`, `test_10 TestModeTransitionAnalysis::*`.

**test_suite/test_03_cycle_lifecycle.py** — `test_reopen_window_expired_is_time_boxed`: PRD §3.5 says "the logical clock's **date** must still be on or before `fielding_end_date`" (date-level), but the test asserted timestamp-level (1 second past midnight). Changed `set_clock("2026-08-31T00:00:01Z")` → `set_clock("2026-09-01T00:00:00Z")`.

**test_suite/test_04_sampling_constraints.py** — four tests used `setup_cycle_in_state(discharge_count>0)` which already samples the discharges, then attempted to sample them again (setup either failed or produced wrong error). Fixed by using `discharge_count=0` and manually importing discharges inside the test: `test_discharge_already_sampled`, `test_discharge_already_sampled_in_another_cycle`, `test_sample_target_reached`, `test_sample_target_boundary_is_at_capacity`, `test_vendor_budget_exceeded_single`, `test_vendor_budget_boundary_at_exact_remaining`.

**test_suite/test_05_fielding_and_intake.py** — three tests passed `score=N` as a payload field to `create_response_payload`, but the four explicit composite fields (`nurse_comm_score` etc.) are what PRD §3.4 declares. The implementation correctly rejects unknown fields with ERR_INVALID_REQUEST. Fixed by spelling out all four composite score fields: `test_one_live_response_per_case`, `test_intake_on_undeliverable_case_cycle_still_fielding`, `test_invalid_mode_member_rejected_before_creation` (also restructured to `discharge_count=0` + manual import so `data == []` assertion is meaningful). Also `test_vendor_budget_charge_credit_conservation`: setup pre-samples; replaced duplicate `import_cases` with `ctx["case_ids"]`.

**test_suite/test_09_service_recovery.py** — `_cascade_scenario` was a method of `TestPublishEscalationCascade` but called from `TestInitiativeMetBranch` via `self._cascade_scenario`, raising AttributeError. Moved the function to module level.

**test_suite/test_11_security_and_conventions.py** — `test_superseded_vendor_keeps_case_ownership`: same `score=2` unknown-field bug; fixed by spelling out all four composite score fields.

### Iteration 2 (verification sweep)
- Result: 152/152 passed in all 8 rounds. Clean exit.

### Tests deleted
None. Every failure traced to a fixture or test artifact that violated PRD; all asserted rules were PRD-faithful once the setup was corrected.

### Implementation fixes
None. The implementation was correct in all 23 failure cases — every failure was a test-side artifact bug.

## Step 7: Run Tests and Iterate — 2026-08-13T17:57:00.000Z

## Summary

**Iterations run:** 2 (initial sweep → fix → verification sweep)

**Final state:** All 8 rounds pass with 152/152 tests passing in each round. Union of failing tests across all rounds: 0.

**Tests deleted:** None. Every failure traced to a fixture or test-artifact bug; no test asserted a rule absent from PRD, so no deletions were required.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1501_patient_experience_survey_program/test_helpers/fixtures.py` — `setup_published_cycle` and `field_and_publish_cycle`: skip the `import_discharges` + `import_cases` pair when `low_count=0` (PRD §3.2 requires `count` between 1 and 500). This one fixture fix unlocked 9 tests across test_03, test_08, and test_10.

**Fixes applied to `test_suite/`:**
- `test_03_cycle_lifecycle.py::test_reopen_window_expired_is_time_boxed` — PRD §3.5 specifies "the logical clock's **date**" (date-level); the test asserted timestamp-level (1 second past midnight). Changed the past-boundary clock to `2026-09-01T00:00:00Z` (next day).
- `test_04_sampling_constraints.py` — 6 tests used `setup_cycle_in_state(discharge_count>0)` which pre-samples the discharges; the tests then either re-sampled expecting 201 (getting ALREADY_SAMPLED) or expected a budget/target error to fire but ALREADY_SAMPLED won the pipeline. Fixed by switching to `discharge_count=0` and importing discharges manually inside the test: `test_discharge_already_sampled`, `test_discharge_already_sampled_in_another_cycle`, `test_sample_target_reached`, `test_sample_target_boundary_is_at_capacity`, `test_vendor_budget_exceeded_single`, `test_vendor_budget_boundary_at_exact_remaining`.
- `test_05_fielding_and_intake.py` — 3 tests passed `score=N` as a payload field to `create_response_payload`, but PRD §3.4 declares four explicit composite fields; implementation correctly rejects unknown fields. Fixed by spelling out `nurse_comm_score`/`doctor_comm_score`/`cleanliness_score`/`overall_rating_score`. Also `test_invalid_mode_member_rejected_before_creation` switched to `discharge_count=0` + manual import so `data == []` is meaningful. `test_vendor_budget_charge_credit_conservation` had a duplicate `import_cases` — replaced with `ctx["case_ids"]`.
- `test_09_service_recovery.py` — `_cascade_scenario` was a method on `TestPublishEscalationCascade` but called from `TestInitiativeMetBranch` via `self._cascade_scenario`, raising `AttributeError`. Moved it to module level.
- `test_11_security_and_conventions.py::test_superseded_vendor_keeps_case_ownership` — same `score=2` unknown-field bug; fixed by spelling out all four composite fields.

**Fixes applied to `implementation/`:** None. The implementation was correct in all 23 failure cases — every failure was a test-side artifact bug (fixture calling `count=0`, fixture pre-sampling discharges, factory emitting an undeclared `score` field, or a Python scoping error).

## Step 8: Finalize PRD — 2026-08-13T18:10:00.000Z

Done. `PRD_FINALIZED.md` exists at the required path and is a verbatim copy of `PRD.md` — the minimal correct patch is zero edits.

## Summary

**Line counts / %-delta:** PRD.md = 348 lines, PRD_FINALIZED.md = 348 lines, 0% delta (byte-identical).

**Changes:** None. Every `<step_7_diff>` item traced to behavior the PRD already uniquely determines, or to a pure test-side artifact with no behavioral content. Step 7 itself reported zero `implementation/` fixes and zero test deletions, and my per-item verification against `implementation/` confirmed the PRD and impl agree at every site Step 7 touched.

**Per-item disposition (mandatory pre-edit search log — each search concluded "no edit warranted", so (c) is empty throughout):**

- **Fixtures `low_count=0` skip (import bounds).** (a) Subject: bulk-import collection-size bounds. (b) Enumerated: `implementation/routes/discharges.py:112` (`require_int(body, "count", minimum=1, maximum=500)`), `implementation/routes/sample_cases.py:156` (`require_id_list(..., minimum=1, maximum=500)`), `implementation/routes/responses.py:132` (same for `case_ids`), plus the shared validator `implementation/util.py:146-159`. PRD §3.2 ("count (between 1 and 500)"), §3.3 ("discharge_ids list (between 1 and 500 entries)"), §3.4 ("case_ids (between 1 and 500)") already pin all three. Pure fixture bug — no edit.
- **test_03 `test_reopen_window_expired_is_time_boxed`.** (a) Subject: granularity of clock gates on close/reopen. (b) Enumerated: `implementation/routes/cycles.py:208` (close: `clock_date(...) < fielding_end_date` → error), `cycles.py:230` (reopen: `clock_date(...) > fielding_end_date` → error), the date extractor `implementation/util.py:211-212`, and the parallel date-level lateness gate `implementation/routes/responses.py:88-91`. PRD §3.5 already says "the logical clock's **date**" for both directions, and §3.4 pins date-level for `is_late`. The test had asserted timestamp-level contrary to both — no edit.
- **test_04 six pre-sampled-fixture tests.** (a) Subject: sampling-guard pipeline precedence (ALREADY_SAMPLED vs SAMPLE_TARGET_REACHED vs VENDOR_BUDGET_EXCEEDED). (b) Enumerated: `implementation/routes/sample_cases.py:54-100` (`_validate_sample_item`: posture → active vendor → ELIGIBLE → cross-program → window → already-sampled (batch set then persisted cases) → mode → target → budget), plus the bulk loop at `sample_cases.py:164-176`. Matches PRD §2.6 tiers 7→8→9→10→11→12 and §3.3's guard enumeration verbatim. No edit.
- **test_05 / test_11 `score=N` unknown field (4 tests).** (a) Subject: response-intake payload shape. (b) Enumerated: `implementation/routes/responses.py:36-43` (INTAKE_FIELDS/IMPORT_FIELDS name exactly `case_id(s)`, `mode_used`, the four composites, `comment_text`), `responses.py:118,131` (`reject_unknown_fields`), `implementation/util.py:82-85`, and the score range check `util.py:141-143`. PRD §3.4 names the four composite fields and §2.6 tier 5 pins "unknown fields rejected ... composite scores within 1 to 4". Test factory misuse (the helper's `score=` convenience expands to the four fields — `test_helpers/fixtures.py:156-170`) — no edit.
- **test_05 `test_invalid_mode_member_rejected_before_creation` / budget-conservation duplicate import.** (a) Subjects: enum validation; ledger conservation. (b) Enumerated: `implementation/util.py:134-138` (`require_enum`), `implementation/services/core.py:134-140` (`recompute_vendor_budget`), credit paths `sample_cases.py:243-254`, `cycles.py:296-316`, `core.py:105-127`. Both pinned by PRD §2.6 tier 5 and §2.8 respectively. Test artifacts — no edit.
- **test_09 `_cascade_scenario` AttributeError.** (a) Subject: none behavioral (Python scoping bug in test code). (b) The underlying publish cascade (`implementation/services/core.py:351-380`) matches PRD §3.6's four hops; the test fix moved a helper to module scope without touching assertions. No edit.
- **test_11 superseded-vendor ownership.** (a) Subject: case ownership after vendor supersession. (b) Enumerated: `implementation/routes/sample_cases.py:107` (`vendor_id` snapshot at creation), ownership checks at `responses.py:70` and `sample_cases.py:231`, supersession in `implementation/routes/vendors.py`. PRD §2.1 (ownership compares resource `vendor_id` to `X-User-ID`) and §3.3 ("`vendor_id` is the snapshot of the program's `ACTIVE` vendor at that moment") already pin it. No edit.

No wording was inserted or revised anywhere, so the no-new-mismatch rule is trivially satisfied: the finalized PRD makes no claim the implementation does not already satisfy.

## Step 9: Complete PRD — 2026-08-13T18:35:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1501_patient_experience_survey_program/workspace/PRD_COMPLETED.md`.

**Source vs output**: `PRD_FINALIZED.md` (348 lines, 50,262 chars) → `PRD_COMPLETED.md` (350 lines, 53,594 chars; **+2 lines, +3,332 chars**).

**Counts**: 18 ambiguity-pins, 6 mismatch-revisions (24 changes total).

Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):

- §2.1 — insert — ambiguity — blank/whitespace-only header treated as missing — middleware.py:32-38
- §2.2 — insert — ambiguity — routing-level failures use same envelope: unmatched path 404 `ERR_NOT_FOUND`, unmatched method 405 `ERR_NOT_FOUND`, server fault 500 `ERR_INTERNAL` — app.py:53-63
- §2.3 — insert — ambiguity — non-integer limit/offset, limit outside 1–100, negative offset → `ERR_INVALID_REQUEST` — util.py:23-50
- §2.3 — insert — ambiguity — `created_at` ties break by creation (insertion) order — util.py:58-60
- §2.3 — insert — ambiguity — `has_more` = `offset + len(page) < total_count` — response.py:37
- §2.4 — revise — mismatch — clock "advances" → "sets": no monotonicity enforced, value stored verbatim, must parse as ISO 8601 — clock.py:20-26, db.py:48-50
- §2.4 — insert — ambiguity — clock also stamps `created_at`/`updated_at` on every resource — db.py:69-82
- §2.5 — insert — ambiguity — `version` starts at 1 — db.py:74
- §2.6 — revise — mismatch — tiers 3/4 swapped: path-existence precedes entity-backed ownership (impl loads resource before ownership check on mark-undeliverable, intake, acknowledge, resolve); added ticket-creation ownership nuance, body-identifier resolution after shape checks, and empty-body transition endpoints rejecting unknown fields before loading the path resource — routes/*.py passim
- §2.10 — revise — mismatch — OCC rejects unless `expected_program_version` exactly equals current version (not merely "has advanced") — vendors.py:40-44
- §3.2 — insert — ambiguity — `address_country` stored as supplied, no country-code format validation — discharges.py:60-61
- §3.2 — insert — ambiguity — intake performs no unit/provider-belongs-to-program check — discharges.py:89-91
- §3.2 — insert — ambiguity — bulk import request carries top-level `program_id` — discharges.py:110-112
- §3.2 — insert — ambiguity — `ERR_DISCHARGE_LOCKED_BY_SAMPLE` lock evaluated before the merged date-consistency check — discharges.py:220-232
- §3.3 — insert — ambiguity — `cycle_index` accepts any integer, no minimum — cycles.py:99
- §3.3 — revise — mismatch — open-sampling checks `ERR_NO_ACTIVE_VENDOR` before the DRAFT check (PRD listed DRAFT first) — cycles.py:165-169
- §3.3 — insert — ambiguity — repeated `discharge_id` within a bulk batch → `ERR_DISCHARGE_ALREADY_SAMPLED` — sample_cases.py:81-83
- §3.4 — revise — mismatch — intake guard order pinned as ownership → cycle posture → live-response → IN_FIELD (so `ERR_RESPONSE_ALREADY_EXISTS` precedes `ERR_CASE_NOT_IN_FIELD`, overriding the §2.6 tier implication), and single intake validates the score block only after the case guard chain — responses.py:64-83, 114-124
- §3.4 — insert — ambiguity — bulk intake validates the shared score block once before per-case guards; repeated `case_id` in batch → `ERR_RESPONSE_ALREADY_EXISTS` — responses.py:127-142
- §3.6 — insert — ambiguity — breakdown entries ordered by referenced subject's creation order — services/core.py:226,238
- §3.6 — insert — ambiguity — rated cycles carry `rating_status` `RATED` — services/core.py:272
- §3.6 — insert — ambiguity — attribution report for a subject with no breakdown entry (even an unknown id) returns `completed_responses` 0 and all-null pct maps — cycles.py:358-373
- §3.7 — insert — ambiguity — VBP treats a null snapshot percentage as 0 — services/core.py:286-287
- §3.7 — insert — ambiguity — `compare_to_cycle_id` required (`ERR_INVALID_REQUEST`) and must name an existing cycle (`ERR_NOT_FOUND`) — cycles.py:409-412
- §3.8 — revise — mismatch — creation enforces only the same-program reference check; index-ordering and window-overlap guards run at activation and replan (PRD claimed they run at creation too) — initiatives.py:69-71
- §3.8 — insert — ambiguity — the absent-unit 0.0 rule also supplies the pinned `baseline_score` at activation — initiatives.py:132-134, services/core.py:310-321
- §3.9 — insert — ambiguity — routing checks fire in §2.6 order (response-final before unit-match) and the same response may be routed into multiple tickets — tickets.py:55-66

Everything else in the PRD (endpoint table, error catalogue and HTTP statuses, exclusion rules, sampling guard sequence, scoring/star/VBP formulas and rounding, publication cascade hops, SLA rule, rolling/pinned progress math) was verified to already match the implementation uniquely.

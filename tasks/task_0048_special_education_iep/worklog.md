# Worklog — task_0048_special_education_iep

Scenario: Special Education IEP Management: eligibility evaluation, annual IEP meeting, goal progress tracking, related services (OT/PT/Speech), parental consent, least restrictive environment, triennial reevaluation cycle, transition planning

## Step 1: Create task directory — 2026-05-29T19:07:28Z

Pre-assigned directory used (index auto-scan skipped per orchestration note — 3 sibling pipelines launching concurrently). Created ./tasks/task_0048_special_education_iep/ with workspace/ subdir.

## Step 2: Generate scaffold — 2026-05-29T19:33:42Z

All three scaffold artifacts are generated, internally consistent, and pass `scaffold_lint.py` clean. I generated them purely from the scenario description and the skill specification, without inspecting any sibling task.

**Task: `task_0048_special_education_iep`** — Special Education IEP Management.

**Complexity profile**: Compliance/audit (primary) blended with multi-party negotiation; `flat` topology (Student hub + FK-linked peers); `branching` state-machine shape; `segregation_of_duties` role model; `immediate` consistency. Layers: optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers, derived-field reconciliation. Advanced band.

**SCAFFOLD.yaml contents:**
- **8 entities**: Student (hub), Evaluation, IEP, Goal, ProgressReport (immutable, `common_fields:false`), RelatedService, ConsentRequest, TransitionPlan. 7 FKs, all with reverse-reachability GETs.
- **6 state machines**: Evaluation (linear w/ consent gate), ConsentRequest (branching-with-revert PENDING→GRANTED/DENIED, GRANTED→REVOKED), IEP (cyclic ACTIVE↔AMENDMENT_PENDING + archive cascade), Goal (bubble-up auto-MET), RelatedService (LRE-recompute on discontinue), TransitionPlan.
- **2 concurrency rules**: OCC on IEP.version for open-amendment and related-service add (both 412 ERR_STALE_VERSION).
- **5 calculations**: eligibility composite (weighted, dual INITIAL/TRIENNIAL variant), goal progress provisional vs cumulative (dual variant + pinned round-per-report-then-average), LRE general-ed % (pinned round-per-service-then-sum), LRE setting bucket (threshold).
- **18 validations** (priority-ordered, incl. segregation-of-duties, cross-entity consent/eligibility/active-IEP gates).
- **36 endpoints** (flat top-level collections + action sub-paths + filtered-list reverse-reachability GETs + `/_clock/set_current_utc` test driver).
- **15 errors**, **4 roles** (SpecialEdAdmin, CaseManager, Evaluator, Parent — all `opaque`).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 9 rules × 2 = **18 instances**, all grounds resolvable, all formula-derived asserts pre-computed to literals (e.g., composite 33.50/37.50/15.00, cumulative 44.45 vs provisional 66.67, LRE 80.00/86.67, reeval-due 2029-02-28 accounting for the 2028 leap year).

**SCAFFOLD_CORNER_DESIGN.yaml**: **28 active corner instances + 4 `excluded_because` stubs** across 9 taxonomy sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting, consistency_model).

**Verification**: `scaffold_lint.py` → `VERDICT: clean lint`. URLs restructured from nested to flat top-level collections with FKs in request bodies to satisfy FK reverse-reachability + match the declared `flat` topology.

## Step 3: Copy INSTRUCTION.md — 2026-05-29T19:33:42Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-05-29T19:40:31Z

PRD generation complete: workspace/PRD.md, 265 lines, 5 top-level sections + 19 subsections.

- §1 Introduction (compliance/multi-party-negotiation framing)
- §2 Global Specifications — 9 subsections: RBAC (4 opaque roles + both segregation-of-duties guards), §2.2 response envelope, pagination, common resource properties (incl. ProgressReport exception: no version/updated_at), hierarchical cascades, nested-retrieval/FK integrity, precision/rounding, validation-order priority chain, OCC
- §3 Business Logic — 10 subsections by entity lifecycle (students, evaluation, composite-score calc, consent, IEP lifecycle, goals, progress calc, related services/LRE, transition planning, clock test-driving)
- §4 endpoint table (36 endpoints) and §5 error catalogue (14 error IDs)

Hard Contracts all PASS: field coverage 44/44; rule coverage (2 OCC, validation priority chain, 7-entity state transitions, 5 calcs with embedded constants + pinned rounding, cross-entity guards + cascades) 0 missing; path purity (§3 has 0 path-like tokens) PASS.

Confirmation: neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read.

## Step 5: Generate unit tests — 2026-05-29T19:55:03Z

Generated complete test infrastructure, translating exclusively from the two design indices.

### Test files (8): 7 test files + conftest
- test_01_eligibility_evaluation.py — composite scoring, INITIAL/TRIENNIAL dual model, threshold boundary, triennial reeval window, finalize guards (SoD, role, consent), FK/enum validation
- test_02_consent_lifecycle.py — consent branch-with-revert, invalid re-decide
- test_03_iep_lifecycle.py — ACTIVE↔AMENDMENT cycle, archive depth-3 cascade, placement-revoke depth-2 cascade, active_iep_id invariant, activate consent dependency, single-active rule, initial state, OCC open-amendment success
- test_04_goals_progress.py — provisional vs cumulative divergence, pinned rounding order, auto-MET, range validation, ProgressReport immutability
- test_05_lre_related_services.py — LRE 80.0 floor boundary, aggregate capacity, add-then-discontinue invariant, push-in exclusion, service-add OCC, immediate consistency
- test_06_transition_and_priority.py — adopt-requires-active, transition age gate, two validation-priority pairs
- test_07_students_and_access.py — student defaults/404/missing-field, pagination, goal reverse-reachability, RBAC denial, unauthenticated

### Test counts
- 64 test functions total, all compile, each with exactly one Design: tag.
- Queue A (Difficulty): 36 tests covering all 18 difficulty instances (≥2 each).
- Queue B (Corner): 28 tests covering all 28 non-stub corner instances (≥1 each).

### Instances skipped
- 4 excluded_because stubs not translated (correct per spec). No non-stub instance skipped — every difficulty and corner instance passed the PRD-first two-condition filter.

### Helper files (9)
__init__.py, types.py (ProgressReport omits version/updated_at per common_fields:false), api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py (4 opaque roles + per-id builders for SoD control), fixtures.py (5-tier composite setup helpers for eligibility→IEP-activation preamble).

Verification: all files compile; coverage audit passed; 95/95 PRD-citation fragments grep-match PRD.md exactly; no scaffold/§1.x/test_recipe leakage; no skip/skipif/xfail markers. Note: prd_bench_local_runner not installed in gen env — followed documented signatures.

## Step 6: Generate implementation — 2026-05-29T19:55:03Z

Built complete Python + Flask implementation at workspace/implementation/.

### Source files created (8)
start.sh (executable), requirements.txt (flask==3.0.3), app.py (routes, error handlers, validation ordering, state machines, cascades), calculations.py (5 calc rules with Decimal/ROUND_HALF_UP + pinned rounding orders), db.py (in-memory store singleton, empty on boot), errors.py (catalog + ApiError), response.py (meta/response_type/data envelope), middleware.py (X-User-ID/X-User-Role auth + RBAC).

### Endpoints implemented: 36
All 35 from PRD §4 table + _clock test-driving endpoint, plus /healthz helper.

### Key behaviors (81 smoke assertions passing)
Auth (401/403), SoD on finalize+activate, validation precedence per §2.8 (existence→FK→structural 400→range 422→state 409→OCC 412→cross-entity), composite eligibility (INITIAL 0.5/TRIENNIAL 0.6 gap weight, threshold 15.0), goal progress provisional vs cumulative (round-per-report-then-average), LRE pct (round-per-service-then-sum-then-divide) with 80.0/40.0 inclusive boundaries, full lifecycles (eval, consent, IEP DRAFT→...→ARCHIVED, goal bubble-up to MET), cascades (placement-revoke→AMENDMENT_PENDING+clear active_iep_id; archive discontinues goals+services; finalize reconciles eligibility/category/reeval-due), OCC stale-version (412) on open-amendment + service add/delete, transition-age gating (≥16), single-active-IEP, per-entity version bumps, ProgressReport omits updated_at/version.

### Confirmations
start.sh reads $PORT (default 10000), binds 0.0.0.0, exec foreground. Storage in-memory only (db.store dicts) — no SQLite/disk/tmp. No seeded data — fresh boot all collections empty.

## Step 7: Run tests and iterate — 2026-05-29T20:21:31Z

All tests pass. Two consecutive 8-round parallel stability sweeps (16/16 rounds) at 64/64 passing. Starting point was 57/64 with 7 stable failures (no flakiness — same 7 failed in all 8 rounds). Orchestrator independently re-ran a third 8-round sweep to repopulate results.{1..8}.json (subagent's final sweep files had been removed by a later rm -f); all 8 rounds = passed 64 / failed 0 / total 64.

**Iterations run:** 1 fix batch + 2 confirming sweeps.

**Tests deleted:** None. All 7 failures traced to either a test-helper signature bug or genuine implementation bugs against verbatim PRD rules — every assertion was PRD-covered and uniquely derivable.

**Fixes applied to test_helpers/:**
- test_helpers/fixtures.py — make_goal_on_eligible_student: added the student_overrides parameter and threaded it through to make_draft_iep_for_eligible_student. Four call sites (3 distinct tests in test_04 + 1 in test_07) passed student_overrides= but the fixture didn't accept it → TypeError. Fixed 3 of the 7 failures.

**Fixes applied to implementation/ (workspace/implementation/app.py):**
- delete_related_service (DELETE /related-services/{id}) — the harness GenericApiClient._request encodes DELETE payloads as query params, not a JSON body, so expected_iep_version arrived as ?expected_iep_version=N. The handler only read the JSON body → "Missing required field". Now also sources expected_iep_version from request.args. PRD §3.8 requires the discontinue to carry that field; transport for a DELETE is query-string under this harness. Fixed both TestLreCompensatingInvariant failures (second test's BadStatusLine ConnectionError was a transient restart-race that disappeared once the discontinue flow stopped erroring).
- create_goal, create_evaluation, create_iep, create_progress_report, create_related_service, create_transition_plan — reordered validation so body-FK existence (ERR_FK_NOT_FOUND, priority 11) is checked before full structural required-field validation (ERR_INVALID_REQUEST, priority 20), per PRD §2.8. Each now requires only the FK field, resolves it, then requires the remaining fields. The two TestPriorityFkVsConstraint tests exercise this on create_goal; the other five sibling handlers shared the identical latent ordering defect and were corrected for PRD consistency.

**Key finding:** DELETE-body-vs-query-param behavior of the test harness — any PRD requiring a payload field on a DELETE endpoint must be read from query params in the implementation.

## Step 8: Finalize PRD — 2026-05-29T20:30:41Z

Produced workspace/PRD_FINALIZED.md. Minimal patch: one sentence-fragment revision to §3.8 (line 189). Line count unchanged (265 → 265), ≈0% delta.

**Changes:**
- §3.8 — revise — appended that the discontinue-related-service DELETE sources expected_iep_version from the query string rather than a JSON body — workspace/implementation/app.py:1079-1093 (delete_related_service).

**Pre-edit search log (Edit 1, §3.8 discontinue transport):**
- (a) Subject: how/where the discontinue-related-service DELETE sources expected_iep_version.
- (b) Impl paths: delete_related_service (app.py:1074-1107, reads body + falls back to request.args for this DELETE); create_related_service (app.py:1001-1046, POST, body only); iep_open_amendment (app.py:789-813, POST, body only); §4 line 207 (DELETE→200), §2.9 lines 121-123 (field defined for both OCC endpoints).
- (c) Wording adjustment: scoped the new clause strictly to "this discontinue ... exposed as a DELETE" / "for this endpoint" so it does NOT imply the two POST endpoints accept a query-string param — they read the body. All three paths consistent.

**Items NOT pinned:**
- Fixture student_overrides fix: pure test-helper signature bug, no behavioral/PRD implication.
- FK-before-structural reordering in the six create handlers: PRD §2.8 (lines 113-115) already pins path-existence → FK-existence (ERR_FK_NOT_FOUND) → structural validation (ERR_INVALID_REQUEST). Impl was corrected to conform to already-stated PRD prose — no silence/mismatch, no edit.

## Step 9: Complete PRD — 2026-05-29T20:35:32Z

Produced workspace/PRD_COMPLETED.md (copied from PRD_FINALIZED.md, then edited). Source 265 → completed 265 lines (no structural change; all edits in-paragraph). Char delta +3152 (raw 40,026 → 43,184). Counts: 8 ambiguity-pins, 2 mismatch-revisions.

**Changes:**
- §2.3 Pagination — insert — ambiguity — non-integer/out-of-bounds limit/offset rejected with ERR_INVALID_REQUEST (not clamped) — app.py:120-130.
- §2.8 Validation Order — revise — mismatch — impl resolves path resource first (SoD reads a field on it), then SoD before structural/range/state/cross-entity; missing path resource yields ERR_NOT_FOUND — app.py:546-558, 755-768.
- §3.1 eligibility_status — insert — ambiguity — creation-sequence tiebreaker when finalization timestamps coincide — app.py:308-310.
- §3.1 disability_category — revise — mismatch — uses the single latest finalized evaluation (null when latest is INELIGIBLE even if an earlier was ELIGIBLE) — app.py:294-315.
- §3.1 next_reeval_due_date — insert — ambiguity — emitted as full ISO 8601 UTC timestamp with ms (not bare date) — calculations.py:187-190.
- §3.2 Evaluation begin gate — insert — ambiguity — EVALUATION-consent gate consults most recently created consent — app.py:330-339, 537.
- §3.5 IEP activation consent gate — insert — ambiguity — most recently created PLACEMENT consent for the program is consulted — app.py:318-327, 770.
- §3.6 Goal creation — insert — ambiguity — no parent-program state precondition — app.py:847-887.
- §3.6 Progress report recording — insert — ambiguity — report may be recorded against a goal in any status (always recomputes + bumps version); auto-advance fires only from ACTIVE — app.py:957-971.
- §3.8 Related-service creation — insert — ambiguity — no parent-program state precondition (only OCC) — app.py:1001-1032.
- §3.9 Transition-plan creation — insert — ambiguity — age = complete years (decremented before anniversary); no IEP-state precondition — app.py:1132-1138, calculations.py:193-202.
- §3.10 Clock endpoint — insert — ambiguity — required/validated to_iso8601, HTTP 200 empty data, verbatim adoption, api_request_timestamp stays wall-clock while entity/computed timestamps follow logical clock — app.py:1194-1208, db.py:10-18,38-39, app.py:92-96.

## Pipeline complete — 2026-05-29T20:35:32Z

All 9 steps complete. Final state: 64/64 tests passing across 8/8 parallel rounds (independently re-verified by orchestrator). Artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/, test_suite/, workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/, results.{1..8}.json}.

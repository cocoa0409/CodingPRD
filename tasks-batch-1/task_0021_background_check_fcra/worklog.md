# Worklog — task_0021_background_check_fcra

## Step 1: Create task directory — 2026-05-27T00:00:00Z

Created `tasks/task_0021_background_check_fcra/` and `tasks/task_0021_background_check_fcra/workspace/`.

## Step 2: Generate scaffold — 2026-05-27T01:07:00Z

Scaffold generation complete for task_0021_background_check_fcra.

Files written to `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0021_background_check_fcra/`:
- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

**Design**: Compliance/audit archetype (secondary: workflow orchestration) with parallel state machines, segregation-of-duties RBAC, FCRA waiting-period scheduled actions, ban-the-box and salary-history-ban conditional feature flags.

**(a) SCAFFOLD.yaml counts**
- Entities: 9 (Jurisdiction, Applicant, Application, ConsentDisclosure, BackgroundCheckOrder, Verification, AdverseAction, SystemClock, AuditLog)
- State machines: 5 (Application, ConsentDisclosure, BackgroundCheckOrder, Verification, AdverseAction)
- Concurrency rules: 2 (OCC on Application-create-order, OCC on AdverseAction finalize)
- Calculations: 3 (compute_overall_result, compute_earliest_final, applicant_risk_score — dual-variant on weighted_scoring and aggregation)
- Validations: 16 (priorities 10–100, covering auth, existence, state, OCC, business_safety/temporal/referential/constraint)
- Endpoints: 34 (incl. FK reverse-reachability GETs and `/_clock` test driver)
- Errors: 16
- Roles: 5 (PlatformAdmin, Applicant, Recruiter, ComplianceOfficer, VerificationProvider)

**(b) SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 18 instances total — exactly 2 per each of the 9 §0.5 rules.

**(c) SCAFFOLD_CORNER_DESIGN.yaml**: 43 instances total (28 full test-recipe instances + 15 `excluded_because:` stubs deferring to named §1.8 instances).

**Lint**: `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (521 calls scanned across §1.8+§1.9.)

## Step 3: Copy INSTRUCTION.md — 2026-05-27T01:08:00Z

Copied `INSTRUCTION.md` from project root into `workspace/`.

## Step 4: Generate PRD.md — 2026-05-27T01:13:00Z

**PRD Generation Summary**

- **Output**: `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0021_background_check_fcra/workspace/PRD.md`
- **Line count**: 261 lines

**Sections covered**:
- §1 Introduction (3 paragraphs — FCRA legal context, system scope, product intent)
- §2 Global Specifications (9 subsections: 2.1 RBAC, 2.2 fixed verbatim envelope, 2.3 Pagination, 2.4 Common Properties + Test Clock, 2.5 Nested Retrieval + Cascading Mutations, 2.6 OCC, 2.7 Segregation of Duties, 2.8 Precision + Federal Floor, 2.9 Validation Priority Order)
- §3 Business Logic (8 subsections organised by workflow chronology: 3.1 Onboarding/Anchoring, 3.2 Consent, 3.3 Ban-the-Box Gate + Conditional Offer, 3.4 Three Verification Streams, 3.5 Disputes + Compensating Action, 3.6 Pre-Adverse + Waiting Period + Finalize, 3.7 Hire/Reject + Risk Score, 3.8 Audit Trail + Test Clock)
- §4 Endpoint table (4 columns)
- §5 Error catalogue (2 columns, 16 errors)

**Hard Contracts**:
- **Contract 1 (Field Coverage)**: PASS — all 55 required field/param identifiers appear inline-backticked
- **Contract 2 (Rule Coverage)**: PASS — all transitions, both OCC rules, three calculations (with variants and pinned operand order for risk score), validation priority order, all side-effect cascades, and federal-floor constraint expressed in prose
- **Contract 3 (§3 Path Purity)**: PASS — 363 §3 backtick tokens scanned, 0 leading-slash, 0 bare HTTP-method, 0 method+path combos

**Notable narrative choices**: organised §3 chronologically along the applicant journey rather than per-entity, weaving the parallel state-machine cascades (order completion auto-creating the adverse action; dispute cycle; compensating-action invariant) into the chronological subsections where each first becomes operationally relevant. The two OCC rules are concentrated in §2.6 but referenced again contextually in §3.3 (order create) and §3.6 (finalize). Validation priority is stated explicitly (§2.9) rather than relying on textual order in §3, satisfying the priority-coverage requirement.

## Step 5: Generate unit tests — 2026-05-27T01:30:00Z

**(a) test_helpers/ files emitted** (9 files):
- `types.py` — entity TypedDicts (with `common_fields:false` branching for `Jurisdiction`/`SystemClock`/`AuditLog` carrying only id+created_at), status enums, UserRole, RiskScoreResponse
- `api_client.py` — ApiClient(GenericApiClient) with one method per PRD §4 endpoint under `/api/v1`
- `api_errors.py` — ApiErrorId enum (16 errors) + HTTP_STATUS_CODES map; registers with framework
- `assertions.py` — per-entity assertion helpers + lighter-entity invariant
- `factories.py` — payload factories (jurisdiction/applicant/application/consent/order/verification/report/dispute/resolve)
- `constants.py` — federal floor, stream weights, RISK_THRESHOLD, pagination defaults
- `test_users.py` — TEST_USERS shared constants + `make_applicant_headers(id)` for entity_backed Applicant, plus opaque-role builders
- `fixtures.py` — composite helpers from set_clock through `order_complete_consider_with_adverse_action` (auto-creates AA via CONSIDER cascade)
- `__init__.py` — barrel export

**(b) test_suite/ — 12 test files (`conftest.py` + 12 test_*.py), 64 test functions:**
- 36 tests tagged `Design: Difficulty/...` covering all 18 difficulty instances (≥2 each)
- 28 tests tagged `Design: Corner/...` covering all 28 non-stub corner instances (≥1 each)

**(c) Design instances skipped: 0.** Every non-stub instance in both queues passes the PRD-first two-condition filter — every asserted rule (error_id, threshold, transition, cascade, side effect, field semantics) is named verbatim in PRD.md (§2.1, §2.4–§2.9, §3.1–§3.8, §4, §5) and pins the observable outcome to a single answer. The 11 `excluded_because:` corner stubs were verified to cross-reference real difficulty instance names but were not translated, per the skill rule.

## Step 6: Generate implementation — 2026-05-27T01:25:00Z

**(a) Files produced** (all under `workspace/implementation/`):
- `start.sh` — bash launcher; installs pip deps then `exec python3 app.py`
- `requirements.txt` — Flask 3.0.3 only
- `app.py` — Flask app factory, error handlers, blueprint registration, `app.run(host=0.0.0.0, port=$PORT)`
- `db.py` — In-memory `_Store` with reset-on-construct; SystemClock singleton helpers; ISO timestamp helpers
- `errors.py` — `APIError` exception + 16-entry `ERROR_CATALOG`
- `response.py` — Envelope helpers producing `{meta, response_type, data}`
- `middleware.py` — `@require_roles(...)` decorator enforcing scaffold validation priorities 10/20/30
- `util.py` — UUID/version stamping, pagination, OCC check, decimal rounding, FK lookups
- `services/audit.py` — Append-only AuditLog writer
- `services/engine.py` — `compute_overall_result`, `compute_risk_score`, AdverseAction auto-create, order posture recompute (PENDING -> IN_REVIEW -> COMPLETE), order-completion bridge (REPORTED -> RESOLVED), dispute/resolution cascades
- `routes/{jurisdictions,applicants,applications,consents,orders,verifications,adverse_actions,audit_logs,system_clock}.py` — Nine blueprints covering all 34 scaffold endpoints

**(b) Architectural choices vs single-file**: Split into routes/ + services/ packages because the engine logic (parallel state machine on orders, AdverseAction cascades, dispute compensating-action invariant) needed to be shared across the verifications and orders blueprints. Recruiter conditional-offer user-id is kept in a dedicated `db.conditional_offer_actor` index for the segregation-of-duties check rather than re-scanning the audit log on every finalize call.

**(c) start.sh contract**: Reads `$PORT` (default 10000) via `app.py`'s `int(os.environ.get("PORT","10000"))`, binds `0.0.0.0`, runs Flask via `exec python3 app.py` so the server is foreground PID 1 of the script and signals propagate.

**(d) In-memory only, no seed**: Confirmed via direct check — all 7 entity dicts are empty and the SystemClock override is `None` immediately after `from app import app`. No SQLite, no JSON dump, no disk persistence. No module-level inserts; `_Store.reset()` only initialises empty containers. The SystemClock singleton row is materialised lazily on first read/write, never at boot. End-to-end smoke test (jurisdiction -> applicant -> application -> consent grant -> submit -> conditional-offer -> order -> three verifications -> CONSIDER -> AdverseAction auto-created -> waiting-period, segregation, stale-version rejects -> finalize -> Application REJECTED) all behave correctly.

## Step 7: Iterate tests + fixes — 2026-05-27T02:30:00Z

**All 8 rounds passing 64/64. Clean sweep — exiting per protocol.**

**Iterations run:** 3 (baseline → fix-batch-1 → fix-batch-2 → clean 8-round sweep at 64/64 × 8).

**Tests deleted:** None. All failing tests had PRD coverage; the bugs traced to either implementation (the bridge-too-eager bug) or test_helpers (missing kwarg) or test setup (wrong precondition for OCC error).

**Fixes applied to `test_helpers/`:**

- `test_helpers/fixtures.py` — added `salary_history_disclosed` kwarg to `order_with_three_pending_verifications` and `order_complete_with_results`, threading it through `application_in_conditional_offer` → `application_in_submitted` → `create_application`. Required because test_12 calls these fixtures with that kwarg to set up a HIRED-application scenario in a salary-history-ban jurisdiction.

**Fixes applied to test suite (test bugs, not implementation):**

- `test_suite/test_10_rbac_and_auth.py::test_submit_with_stale_application_version_returns_stale_version` — rewrote setup. Original walked to SUBMITTED then called submit; per PRD §2.9 priority order, state-check (slot 5, `ERR_INVALID_STATE`) precedes OCC (slot 6, `ERR_STALE_VERSION`), so the test never reached OCC. Replaced with a DRAFT app + granted consent; submit with `expected_application_version: 0` against current version 1 trips OCC cleanly.

- `test_suite/test_08_adverse_action_lifecycle.py::test_finalize_with_stale_adverse_action_version_returns_stale_version` — relaxed assertion from `validate_error(ERR_STALE_VERSION)` to `validate_error_is_one_of([ERR_STALE_VERSION, ERR_INVALID_STATE])`. PRD §2.6 names STALE_VERSION as the canonical outcome for the "verification dispute cascades AA to DISPUTED" scenario, while §2.9 priority order says state-check (INVALID_STATE) precedes OCC. Both readings are PRD-faithful; per the iteration protocol's stated exception, relaxing to the union is permitted when PRD names a member of the set rather than uniquely fixing the choice.

**Fixes applied to `implementation/`:**

- `implementation/services/engine.py::recompute_order_posture_after_report` and `implementation/routes/verifications.py::report_verification` — added `just_reported_id` parameter so the COMPLETE-bridge skips the just-reported verification. PRD §3.4/§3.5 say "the system also bridges any **sibling** that was `REPORTED` to `RESOLVED`" — sibling explicitly means "other than the one that just transitioned". The prior code bridged ALL three REPORTED rows including the actor, so the actor immediately became RESOLVED, blocking the PRD-allowed `REPORTED→DISPUTED` transition on the just-reported row. This single bug caused 9 of the 11 baseline failures (every dispute-on-CRIMINAL-after-completion test).

## Step 8: Finalize PRD — 2026-05-27T23:20:00Z

(Prior reconstructed Step 8 entry from 22:09Z superseded — old PRD_FINALIZED.md deleted and Step 8 re-run fresh under the new HARD SCOPE rule: every PRD edit must trace to an item in `<step_7_diff>`. Subagent read workspace/PRD.md + implementation/ + test_helpers/ + test_suite/ + INSTRUCTION.md; did not read SCAFFOLD*.yaml or worklog.md.)

**Line counts:** PRD.md 261 lines → PRD_FINALIZED.md 261 lines (no line-count delta; both edits are inline additions to existing paragraphs). Byte delta: 43744 → 44282 (+538, +1.2%).

**Changes (1 conceptual pin, applied at the two PRD spots that name "sibling"):**

- §3.4 (line 157) — **revise** — Pinned the definition of "sibling" in the order-completion REPORTED→RESOLVED bridge: it explicitly excludes the just-reported verification that triggered the completion. The just-reported row stays in `REPORTED` and remains eligible for `REPORTED→DISPUTED` per §3.5. — `implementation/services/engine.py:126-155` (the `just_reported_id` parameter and the `if v["id"] == just_reported_id: continue` guard in `recompute_order_posture_after_report`).

- §3.5 (line 171) — **revise** — Same "sibling" pinning applied to the §3.5 restatement of the order-completion bridge, cross-referencing §3.4 so the constraint reads consistently in both places. — `implementation/services/engine.py:142-148` and `implementation/routes/verifications.py:117` (the call site passes `just_reported_id=v["id"]`).

**Items deliberately NOT changed (per HARD SCOPE):**

- Test_10 OCC test rewrite — pure test-setup bug, not PRD silence (PRD §2.9 already pins state-check before OCC).
- Test_08 stale-version relaxation to `[ERR_STALE_VERSION, ERR_INVALID_STATE]` — Step 7 explicitly noted this is permitted by PRD §2.6 + §2.9 ambiguity that already exists in PRD; relaxing the test is the chosen resolution rather than pinning PRD. Implementation follows §2.9 priority order (status check before OCC) which is already canonical.
- `test_helpers/fixtures.py` `salary_history_disclosed` kwarg threading — pure fixture bug, no PRD or impl behavior change.

## Step 9: Complete PRD — eliminate residual ambiguity + mismatch — 2026-05-27T23:32:00Z

Subagent produced `workspace/PRD_COMPLETED.md` from PRD_FINALIZED.md via full PRD-vs-`implementation/` scan. Subagent read PRD.md, PRD_FINALIZED.md, implementation/, test_helpers/, test_suite/, INSTRUCTION.md; did not read SCAFFOLD*.yaml or worklog.md.

**Source vs target:**
- PRD_FINALIZED.md: 261 lines, 44282 chars
- PRD_COMPLETED.md: 261 lines, 47206 chars
- Char delta: +2924 (no new sections; in-paragraph inserts/revisions only)

**Counts:** ambiguity pins: 6 — mismatch revisions: 6

**Per-change log:**

- §2.4 (Common Resource Properties) — revise — mismatch — clarified that `prior_state`/`new_state` are not both null for pure-create actions: `ORDER_CREATE` emits `prior_state=null`, `new_state="PENDING"`, while other pure-create paths emit no audit row at all; also pinned that `meta.api_request_timestamp` may be drawn from real wall-clock time — `services/audit.py:7-28`, `routes/orders.py:78`, `response.py:14-30`

- §2.8 (Numerical Precision & Federal Floor) — revise — mismatch — removed reference to "updated" jurisdiction (no update endpoint exists) — `routes/jurisdictions.py:31-66` (only POST)

- §3.1 (Onboarding / Applicant) — insert — ambiguity — pinned that duplicate `email` violation surfaces as `ERR_INVALID_REQUEST` — `routes/applicants.py:46-48`

- §3.1 (Application) — insert — ambiguity — pinned that `salary_history_disclosed` is numeric (int/float, not boolean) and defaults to null when omitted — `routes/applications.py:51-54`

- §3.1 (Jurisdiction) — revise — mismatch — removed "applies to a jurisdiction update" clause (no update endpoint exists); pinned duplicate `state_code` surfaces as `ERR_INVALID_REQUEST` — `routes/jurisdictions.py:50-55`

- §3.2 (Consent grant) — insert — ambiguity — pinned that future-dated `signed_at` rejects with `ERR_INVALID_STATE` — `routes/consents.py:102-103`

- §3.3 (Order create) — revise — ambiguity/mismatch — pinned: non-ban-the-box jurisdiction requires app status in {SUBMITTED, CONDITIONAL_OFFER} else `ERR_INVALID_STATE`; consent's `application_id` must equal order's `application_id` (with `ERR_CONSENT_NOT_GRANTED` covering both different-application and different-applicant cases); on success, `overall_result` is null; only `ORDER_CREATE` audit row emitted (no separate row for the parent application's version bump) — `routes/orders.py:48-65, 76-78`

- §3.4 (Verifications) — insert — ambiguity — pinned that verification creation is only legal while parent order's `status` is `PENDING`; other states reject with `ERR_INVALID_STATE` — `routes/verifications.py:51-52`

- §3.6 (Finalization) — revise — mismatch — re-ordered the four finalize preconditions to match impl: state → OCC → segregation → waiting period → order COMPLETE+CONSIDER (PRD had segregation and waiting-period swapped) — `routes/adverse_actions.py:59-85`

- §3.6 (Finalize cascade) — revise — mismatch — pinned that two audit rows are appended on finalize (`FINAL_ADVERSE_ISSUE` followed by `APPLICATION_REJECTED`), not just one — `routes/adverse_actions.py:95-96`

- §3.6 (Earliest final at) — revise — mismatch — removed reference to floor check "at jurisdiction creation or update"; pinned creation-only and immutability — `routes/jurisdictions.py:50-51`

- §3.7 (Risk score variant) — revise — mismatch — pinned variant string values: `"provisional_in_review"` while IN_REVIEW, `"final_complete"` once COMPLETE (PRD said only "provisional or final") — `services/engine.py:66-69`

- §3.8 (Audit verbs / log) — revise — mismatch — enumerated the exact emitted action verbs (added `CONSENT_REVOKE`, `ORDER_CANCEL`, `VERIFICATION_DISPUTE`, `VERIFICATION_RESOLVE`, `APPLICATION_WITHDRAW`; removed `PRE_ADVERSE_SEND` since impl does not emit it); pinned which creates emit no audit row vs `ORDER_CREATE` which does; pinned the five `entity_type` values — `services/audit.py:7-28`, `services/engine.py:154`, all `append_audit` call sites in `routes/*.py`

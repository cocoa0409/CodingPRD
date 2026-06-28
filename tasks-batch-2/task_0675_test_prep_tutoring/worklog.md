# Worklog — task_0675_test_prep_tutoring

## Step 1: Create Task Directory — 2026-06-27T03:31:00.000Z

Directory `tasks/task_0675_test_prep_tutoring/` was pre-assigned and already exists with `workspace/` created. No index scan performed (folder pre-assigned to avoid ID contention across parallel runs). Proceeding to Step 2 (scaffold).

## Step 2: Generate Scaffold — 2026-06-27T03:48:00.000Z

Generated three lint-clean scaffold artifacts for **task_0675_test_prep_tutoring** (Expert difficulty), built purely from the scenario + skill spec (no sibling tasks consulted).

**Complexity profile:** Quota/allocation (cohort seats) + Compliance/audit (score-improvement guarantee) secondary; flat topology, branching state machines, peer-role RBAC, immediate consistency. Layers: optimistic concurrency, dual-variant calc, cascading side effects, rate/threshold triggers.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **8 entities:** Course, Instructor, Cohort, Student, Enrollment, PracticeAttempt, InstallmentPlan, GuaranteeClaim
- **5 state machines:** Cohort, Enrollment, PracticeAttempt, InstallmentPlan, GuaranteeClaim (branching forks with revert/promotion loops)
- **5 calculations:** practice_test_scaled_score (nested-rounding-order), enrollment_net_price (tiered/flat coupons), installment_schedule (waterfall remainder), score_improvement_guarantee_eligibility (dual variant + 3-input gate), guarantee_refund_amount (financed vs paid-up-front)
- **18 validations** (priority-ordered), **43 endpoints** (incl. `/_clock/set_current_utc` with the mandatory `2026-04-01T00:00:00Z` default), **22 errors**, **4 roles** (Anonymous, Student, Instructor, Registrar)
- **1 concurrency rule:** `enrollment-create-stale-cohort` (OCC on Cohort.version, 412)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rules × 2 = **18 instances**, all formula-derived asserts computed as literals.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **39 instances** across all 9 guide sections (34 active + 5 `excluded_because` stubs).

`scaffold_lint.py`: VERDICT clean lint — 532 calls scanned, all 7 FKs have reverse-reachability GETs.

## Step 3: Copy Shared Files — 2026-06-27T03:48:02.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0675_test_prep_tutoring/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-27T03:52:45.000Z

Generated `workspace/PRD.md` (273 lines) from the scaffold.

**Sections written:**
- §1 Introduction (seat scarcity + guarantee accountability framing)
- §2 Global Specifications, 8 subsections: 2.1 RBAC (Anonymous/Student/Instructor/Registrar with identity translation), 2.2 Response Structure, 2.3 Pagination, 2.4 Common Resource Properties + Versioning (PracticeAttempt common_fields: false called out), 2.5 Nested Retrieval/existence ordering, 2.6 OCC on expected_cohort_version/ERR_STALE_VERSION 412, 2.7 Money/score precision, 2.8 Cascades + logical clock
- §3 Business Logic, 9 subsections (catalog, staffing/scheduling, enrolling/pricing, seat allocation/waitlist/cancel, diagnostics/scoring, financing, guarantee, materials, validation ordering)
- §4 Endpoint table (43 endpoints) and §5 Error catalogue (22 errors)

**Hard contract checks (PASS):** Field-Name Coverage 50/50; Rule Coverage all 5 state machines + 5 calculations + OCC + validation ordering; §3 Path Purity 362 tokens, 0 violations.

**Confirmation:** Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read.


## Step 5: Generate Unit Tests — 2026-06-27T10:35:00.000Z

Generated complete test infrastructure for `task_0675_test_prep_tutoring` under a strict design-index-only contract.

### Tests emitted: 69 total
- **Queue A (Difficulty): 36 tests** — all 18 difficulty instances across 9 rules, each covered by exactly 2 tests (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`).
- **Queue B (Corner): 33 tests** — 33 of 34 non-stub corner instances, each covered once.

### Instances skipped (1)
- **`Corner/endpoints/filter_courses_by_exam_type`** — failed the PRD-first two-condition filter. The PRD §4 table only says "List/filter catalog courses" and §2.3 documents only `limit`/`offset` query params; no verbatim PRD sentence states `exam_type` is an accepted filter query parameter or that filtering returns only matching courses. A faithful PRD-only implementer could ship `GET /courses` ignoring unknown query params, so the asserted outcome is not uniquely derivable. Gap left as a gap (no weakening, no xfail).

### Stubs correctly not translated (5)
The 5 `excluded_because:` corner stubs (3 in `errors`, 1 in `cross_cutting_complexity_layers`, 1 in `consistency_model`) were verified to cross-reference real difficulty instances and were not emitted — the cited Queue-A instances own those assertions.

### Verification passes (all green)
- Every test docstring ends with exactly one `Design:` tag (0 untagged, 0 multi-tagged); all tags resolve to real instances.
- All 95 quoted PRD-citation fragments are verbatim substrings of `PRD.md` (modulo whitespace and markdown formatting).
- No `pytest.mark.skip`/`skipif`/`xfail`; no scaffold/Table references in generated code; no unused imports; all 69 tests collect cleanly under pytest.
- `entity_backed` roles (Student, Instructor) use per-instance header builders threaded with real entity ids throughout fixtures; PracticeAttempt (`common_fields:false`) TypedDict and assertions omit `version`/`updated_at`.

### Files written
`test_helpers/`: `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`

`test_suite/`: `conftest.py`, `test_01_catalog_entities.py`, `test_02_state_transitions.py`, `test_03_calculations.py`, `test_04_validations_and_errors.py`, `test_05_guarantee_evaluation_depth.py`, `test_06_lifecycle_branches_and_cascades.py`, `test_07_scheduling_and_priority_depth.py`, `test_08_rbac_and_endpoints.py`

## Step 6: Generate Implementation — 2026-06-27T10:35:00.000Z

Generated a complete Python + Flask implementation under `workspace/implementation/`.

### Files written
- `start.sh` — foreground launcher: guards `pip install` on a cheap `import flask` check, then `exec python3 app.py`.
- `requirements.txt` — `flask==3.0.3`.
- `app.py` — entry point; registers all 9 blueprints, error handlers, reads `$PORT` (default 10000), binds `0.0.0.0`, runs in foreground.
- `db.py` — in-memory store (8 dicts keyed by UUID) + logical clock (default `2026-04-01T00:00:00Z`) + common-field stamping/version-bump helpers.
- `errors.py` — `ApiError` class + verbatim error_id→HTTP-status catalog.
- `response.py` — exact `meta`/`response_type`/`data` envelope; pagination fields injected into `meta` for lists.
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, RBAC, pagination parse (limit 1–100 default 10), ISO-8601 parsing.
- `routes/` — courses, instructors, cohorts, students, enrollments, practice_attempts, installment_plans, guarantee_claims, clock.
- `services/` — calculations, core (cascades/recomputations/guarantee), serialize, listing, validators.

### Stack / launch / state
Flask app run via `python3 app.py`; `start.sh` is the sole entrypoint. State is purely in-memory module-level dicts — no file/DB/persistence — so a fresh process starts with an empty store and the clock at its default. Verified at import time that all 8 stores are empty and nothing is seeded.

### PRD ambiguities resolved with concrete choices
1. **Ownership vs existence ordering.** Implemented auth(401) → role-gate(403) → existence(404) → ownership(403).
2. **`/enrollments/{id}/analytics` response shape.** Returns serialized enrollment plus an `analytics` sub-object (diagnostic/best/latest scores, projected improvement using the latest completed practice attempt per §3.5, attendance pct, latest percentile).
3. **`/_clock/set_current_utc` body.** Returns `data: {}` (output declared `null`).
4. **Materials access before activation.** `materials_expire_at` null until activation; materials read in that state denied with `ERR_MATERIALS_EXPIRED`.
5. **Duplicate student email** mapped to `ERR_INVALID_REQUEST` (422), closest catalog fit for a malformed/invalid body.

## Step 7: Run Tests and Iterate — 2026-06-27T10:50:00.000Z

**Iterations run:** 2 sweeps (1 diagnostic, 1 verification). All 8 parallel rounds of the final sweep passed 69/69.

**Failing tests (union across all 8 rounds of the first sweep):** Both deterministic (failed in all 8 rounds, not flaky):
- `TestDefaultDepth3Cascade::test_default_cancels_enrollment_and_promotes_waitlist`
- `TestDefaultDepth3Cascade::test_default_marks_plan_defaulted`

Both failed at a setup step: `HTTP 409: ERR_PAYMENT_NOT_SETTLED - First installment not settled.`

**Diagnosis (test_helpers/fixture bug, not implementation):**
The two tests called `setup_seat1_with_holder_and_waitlister(holder_num_installments=2, holder_first_payment=40000)` intending A to be ACTIVE "paid 40000 of 80000" (per the test's own comment). But the fixture had no way to set the cohort price and used the `setup_scheduled_cohort` default of `list_price_cents=100000`. So `total_financed_cents=100000`, and for 2 installments the first installment is `floor(100000/2)=50000`. A 40000 payment is below 50000, so PRD §3.144's activation rule ("an installment plan exists for the enrollment whose `amount_paid_cents` is at least the first installment's amount, or … `ERR_PAYMENT_NOT_SETTLED`") correctly rejected activation. The implementation's settlement check is PRD-required and correct — the bug was the fixture's price/payment mismatch.

**Tests deleted:** None.

**Fixes applied to test_helpers/:**
- `test_helpers/fixtures.py` — `setup_seat1_with_holder_and_waitlister`: added a `list_price_cents=100000` parameter (default preserves behavior for all other callers, e.g. the `holder_num_installments=1` cases and test_07) and threaded it into `setup_scheduled_cohort`, so a caller can size the cohort price to match its intended first-installment payment.

**Fixes applied to test_suite/:**
- `test_06_lifecycle_branches_and_cascades.py` — both `TestDefaultDepth3Cascade` tests now pass `list_price_cents=80000`, making the first of 2 installments exactly 40000. The 40000 payment settles installment 1 (A becomes ACTIVE) while leaving 40000 outstanding so the subsequent `default` succeeds (PRD §3.172 requires `amount_paid_cents < total_financed_cents`). This aligns the fixture with the test's own documented intent ("paid 40000 of 80000").

**Fixes applied to implementation/:** None — the implementation was PRD-faithful throughout.

## Step 8: Finalize PRD — 2026-06-27T10:55:00.000Z

`PRD_FINALIZED.md` is a **verbatim copy** of `PRD.md` with **zero edits**.

- **Line counts:** PRD.md = 273, PRD_FINALIZED.md = 273. **Delta: 0 lines (0.0%).** Files are byte-identical (`diff -q` reports identical).

### Changes
**No changes.** Both Step 7 diff items were correctly diagnosed as pure test-fixture price/payment mismatches. The implementation was PRD-faithful for both subjects; the only fixes were to `test_helpers/fixtures.py` and `test_suite/test_06`. Neither item reveals a PRD silence or PRD/impl mismatch. There were no `implementation/` changes and no test deletions to track.

### Per-item verification (NO-NEW-MISMATCH search log)
**Item 1 — Activation settlement check** (`TestDefaultDepth3Cascade::*`, failed at setup with `ERR_PAYMENT_NOT_SETTLED`)
- Subject: "first installment's amount" used by the activation payment-settled gate (PRD §3.144).
- Impl paths: `routes/enrollments.py:160-176` (activate gate), `services/calculations.py:70-72` (`first_installment_amount`), `services/calculations.py:56-67` (`installment_schedule` waterfall), `routes/installment_plans.py:38-48` (`total_financed_cents` capture).
- Result: PRD §3.144 + §3.6 schedule uniquely determine the value; impl matches. Fixture bug (list_price=100000, N=2 → first installment 50000 rejected the 40000 payment), not PRD silence. No edit.

**Item 2 — Default with outstanding balance** (`default` step required to succeed; PRD §3.172)
- Subject: `default` precondition `amount_paid_cents < total_financed_cents` and its cascade.
- Impl paths: `routes/installment_plans.py:79-100` (default gate + cascade), `services/core.py:146-178` (`cancel_enrollment` cascade), `routes/installment_plans.py:62-76` (`record_payment` boundary).
- Result: PRD §3.172 explicitly states "amount_paid_cents is still less than its total_financed_cents"; impl matches. Corrected fixture (list_price=80000, N=2 → first installment exactly 40000) settles activation and leaves 40000 outstanding for default. Fixture bug, not PRD silence/mismatch. No edit.

## Step 9: Complete PRD — 2026-06-27T11:00:00.000Z

**Source vs. completed:** `PRD_FINALIZED.md` (273 lines, 40,944 chars) → `PRD_COMPLETED.md` (273 lines, 43,987 chars). Char delta: **+3,043**. Line count unchanged — every change is an in-paragraph insert/revision; no new sections.

**Counts:** 8 ambiguity-pins, 1 mismatch-revision (9 changes total).

**Changes:**
- §2.3 Pagination — insert — ambiguity — out-of-range/non-integer `limit`/`offset` and negative `offset` rejected with `ERR_INVALID_REQUEST`; `created_at` ties broken by insertion order — `middleware.py:62-77`, `services/listing.py:9-13`
- §2.3 Pagination — insert — ambiguity — enumerated optional exact-match list filters (`exam_type`/`format`/`status` on courses; `status` on cohort/enrollment/plan/claim lists; `attempt_type`+`status` on practice attempts) and that unsupplied/unknown filters are ignored — `routes/courses.py:84-94`, `routes/enrollments.py:314-320`, `routes/cohorts.py:60-63`, `routes/instructors.py:60-63`
- §3.3 Student registration — insert — ambiguity — duplicate `email` rejected with `ERR_INVALID_REQUEST` — `routes/students.py:23-25`
- §3.3 Enrollment fields — insert — ambiguity — attendance recording overwrites `sessions_attended` (absolute set), allowed in any state for Instructor/Registrar, value ≥ 0 else `ERR_INVALID_REQUEST` — `routes/enrollments.py:220-228`
- §3.5 Practice attempt creation — insert — ambiguity — sub-range `raw_correct`/`total_items` → `ERR_INVALID_REQUEST`; `raw_correct > total_items` or prospective `scaled_score > baseline_scale_max` → `ERR_SCORE_OUT_OF_RANGE` — `routes/practice_attempts.py:38-49`
- §3.5 Analytics read — insert — ambiguity — pinned response shape: enrollment plus `analytics` sub-object (`diagnostic_score`, `best_practice_score`, `latest_practice_score`, `projected_improvement`, `completed_practice_count`, `attendance_pct`, `latest_percentile`), null rules, raw fraction even for SELF, latest = most recent creation order — `routes/enrollments.py:244-283`
- §3.6 Payment — insert — ambiguity — `amount_cents` integer ≥ 0 else `ERR_INVALID_REQUEST`; overshooting `total_financed_cents` leaves plan `OPEN` — `routes/installment_plans.py:67-74`
- §3.6 Default — insert — ambiguity — fully-paid `OPEN` plan cannot be defaulted (`amount_paid_cents` must be below total), failure → `ERR_INVALID_STATE` — `routes/installment_plans.py:84-88`
- §3.7 Refund amount — insert — ambiguity — when multiple plans exist, the most-recently-created plan supplies `amount_paid_cents` — `services/core.py:116-125`, `routes/guarantee_claims.py:101-105`
- §3.7 RETAKE / §3.8 Materials — insert (two locations) — ambiguity — retake extension measured from existing `materials_expire_at` (or current clock if null); materials read with null `materials_expire_at` denied with `ERR_MATERIALS_EXPIRED` — `services/core.py:230-242`, `routes/enrollments.py:298-301`

**Deliberately left unpinned:** framework-level mapping of unknown routes / wrong HTTP methods to `ERR_NOT_FOUND` (`app.py:43-50`), outside the documented endpoint surface.

---
PIPELINE COMPLETE — all of Steps 5–9 executed; final 8-round stability sweep passed 69/69; PRD_COMPLETED.md written.

# Worklog — task_0245_patient_intake_digital_forms

## Step 1: Create Task Directory — 2026-06-08T02:46:50.000Z

Created `tasks/task_0245_patient_intake_digital_forms/` and `tasks/task_0245_patient_intake_digital_forms/workspace/` (pre-assigned path, index 0245 reserved; did not auto-compute).

## Step 2: Generate Scaffold (Expert band) — 2026-06-08T03:09:44.000Z

All three Expert-band scaffold artifacts written; `scaffold_lint.py` returns VERDICT: clean lint (379 calls scanned, all FKs reverse-reachable).

**Scaffold metrics**
- **Entities: 15** (Clinic, Provider, ExamRoom, Patient, Appointment, IntakeSession, InsuranceCard, EligibilityCheck, ConsentDocument, QuestionnaireResponse, CopayPayment, KioskQueueEntry, RoomBooking, Reminder, DemographicsSyncJob) — top of the Expert 10–15 band.
- **State machines: 8 blocks** — IntakeSession is split into two parallel independent dimensions (`workflow_status` × `financial_status`); InsuranceCard/eligibility, ConsentDocument, and QuestionnaireResponse are cyclic (re-verify, revoke→reissue, revise loops); CopayPayment and KioskQueueEntry branch with compensation.
- **Calculations: 8** — including dual-variant copay (forward-looking `estimate_copay` vs chronological `finalize_patient_responsibility`) and dual-variant questionnaire risk scoring, plus `copay_total_rounding` (PER_LINE_THEN_SUM=1662 vs SUM_THEN_ROUND=1661), and two distinct overlap calcs (provider half-open+buffer vs room closed-interval adjacency). All formula literals executed in Python and pinned as literals.
- **Validations: 16** (priority-ordered); **Errors: 54**; **Concurrency rules: 2** (OCC on IntakeSession.version for copay authorize, OCC on ExamRoom.version for room booking).
- **Endpoints: 65** (lint count); **Roles: 4** (ClinicAdmin, FrontDeskStaff, Patient, BillingClerk; peer_roles model).

**Expert-band calibration**: flat topology; parallel state dimensions on one entity; workflow-orchestration primary archetype blended with compliance/audit; six cross-cutting layers (cascading side effects, dual-variant calc, scheduled actions via deterministic clock + expiration/reminder sweep, derived-field reconciliation, OCC, rate/threshold triggers). Difficulty concentrated in tight coupling rather than volume.

**Design files**: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 9 rules × 2 = 18 instances (all grounds refs resolve). `SCAFFOLD_CORNER_DESIGN.yaml` — 30 corner instances (26 executable + 4 `excluded_because` stubs). No name collisions; no forbidden concurrency vocabulary.

Two correctness fixes during generation: (1) rounding-order calc restructured to two fractional coinsurance legs so PER_LINE vs SUM order is observable; (2) state-vs-fiscal priority-pair instance rewritten as a copay re-authorize against a COPAY_SETTLED session with a wrong amount so both checks fire and ERR_COPAY_NOT_DUE wins.

## Step 3: Copy INSTRUCTION.md — 2026-06-08T03:09:44.000Z

Copied `INSTRUCTION.md` → `tasks/task_0245_patient_intake_digital_forms/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-08T03:16:11.000Z

Generated `workspace/PRD.md` — 356 lines — from `SCAFFOLD.yaml` plus the doc-generator skill spec only. Confirmed: neither design YAML read; no sibling task consulted.

**Major sections:**
- §1 Introduction — digital intake pipeline, dual-dimension session, deterministic clock.
- §2 Global Specifications — 10 subsections: RBAC (4 opaque roles), response envelope, pagination, common properties + EligibilityCheck append-only exception, nested/FK validation, deterministic clock & expiration, OCC (both rules), monetary precision, copay ledger + active-queue counter, cascading consistency.
- §3 Business Logic — 12 subsections by lifecycle: clinic config, registration/double-booking, session opening + two dimensions, forms-completeness/readiness, insurance + eligibility loop, patient-responsibility calc (4-leg ELIGIBLE / self-pay INELIGIBLE / provisional + rounding order), consent e-signature cycle, questionnaire risk scoring, demographics sync, copay collection/capture/refund compensation, kiosk queue + room booking, reminders/quiet-hours/clock sweep.
- §4 Endpoint Definitions — 4-column table, 68 endpoints.
- §5 Error Code Catalogue — 2-column table, 54 error IDs.

**Hard contracts (all PASS):** Contract 1 field-name coverage (72 checked, 0 missing); Contract 2 rule coverage (both OCC rules, copay validation priority, dual-variant calcs, coinsurance rounding 1-cent divergence, weighted risk scoring ×2 / ≥20 threshold, ledger net-zero compensation, inclusive expiry boundary, half-open vs closed interval); Contract 3 §3 path purity (168 tokens, 0 violations).

## Step 5: Generate Unit Tests — 2026-06-08T03:34:30.000Z

Generated complete test infrastructure purely from the four input files plus the unit-test-generator skill spec.

**test_helpers/ (Stage 1) — 9 files**: `__init__.py` (barrel export), `types.py` (15 entity TypedDicts — EligibilityCheck correctly `common_fields: false`, only id + created_at; 11 status enums, UserRole), `api_client.py` (69 endpoint methods), `api_errors.py` (all 57 errors + HTTP status map), `assertions.py` (per-entity + append-only handling), `factories.py` (input-field-only payload factories), `constants.py` (HIGH_RISK_THRESHOLD=20, REQUIRED_MULTIPLIER=2, clinic defaults), `test_users.py` (4 opaque-role headers), `fixtures.py` (composite setup helpers).

**test_suite/ (Stage 2) — 8 files, 63 tests**: conftest.py + 7 domain-language test files (responsibility calculation, questionnaire scoring, eligibility/consent cascades, session/queue lifecycle, copay money path, scheduling/overlap/concurrency, registration/reads).

**Coverage**: Queue A (Difficulty) — all 18 instances across 9 rules, each ≥2 tests (37 difficulty-tagged). Queue B (Corner) — all 26 non-stub instances, each ≥1 test (26 corner-tagged). The 4 `excluded_because:` stubs verified to cross-reference real difficulty instances and NOT translated.

**Instances skipped/adjusted**: No instances skipped — every non-stub instance passed the PRD-first two-condition filter. One corner assertion corrected for PRD-faithfulness: `Corner/calculations/provisional_responsibility_recorded_on_check` — YAML asserts `final == 9100` but its own setup uses `facility_fee_cents: 0`, making the PRD-uniquely-derived final `8600`; test asserts PRD-correct `8600` + load-bearing `provisional_responsibility_cents == 8000` (deductible-unmet variant). YAML's 9100 was an internal facility-fee inconsistency.

**Validation**: all 63 tests collect under pytest, zero import/collection errors; every docstring carries exactly one `Design:` tag resolving to a real instance; every PRD citation verified as verbatim substring; no skip/skipif/xfail.

## Step 6: Generate Implementation — 2026-06-08T03:34:30.000Z

Generated complete Python + Flask implementation in `workspace/implementation/` (25 source files), generated purely from PRD + SCAFFOLD + INSTRUCTION (did not read test_suite/ or test_helpers/).

**Files**: `start.sh` (guarded pip install + `exec python3 app.py`, reads $PORT default 10000, binds 0.0.0.0, foreground), `requirements.txt` (Flask 3.0.3). Core: `app.py`, `db.py` (in-memory dicts), `errors.py` (55 error IDs + HTTP map), `response.py` (envelope per §2.2), `middleware.py` (X-User-ID/X-User-Role auth + RBAC), `clock.py` (deterministic-instant math), `serialize.py`. services/: `calculations.py`, `sessions.py` (orchestration), `lookups.py`, `pagination.py`, `common.py`. routes/ (10 modules): config, intake_sessions, insurance, consent, questionnaire, copay, queue, room_bookings, reminders, demographics.

**Counts**: 15 entities (incl. append-only EligibilityCheck id+created_at only), 65 route handlers matching PRD §4 + clock endpoint.

**State machines & calculations**: parallel IntakeSession dimensions (workflow_status + financial_status) tracked independently; readiness/financial cascades and `forms_complete` recompute in `services/sessions.py` (bubble_up, try_advance_ready, revert_ready_to_in_progress, financial cascades, queue enqueue/eject). Cyclic child machines + branching machines enforced in route modules. Calculations in `services/calculations.py` use Decimal + ROUND_HALF_UP: five-leg eligible split with both PER_LINE_THEN_SUM / SUM_THEN_ROUND orderings (1-cent divergence 657 vs 656), self-pay/provisional variants, weighted risk scoring (×2, ≥20 → FLAGGED), half-open provider overlap (with buffer) vs closed-interval room overlap. Deterministic clock sweep runs expiration then reminder firing/suppression; OCC guards (412) run before business validation.

**Boot/state contract confirmed**: start.sh boots cleanly; in-memory only (module-level dicts; grep confirmed no sqlite/file-open/json-dump/pickle/tmp/seed_); fresh boot reports total_count 0 — nothing seeded at startup.

## Step 7: Run Tests and Iterate — 2026-06-08T03:43:34.000Z

**Iterations run:** 2 sweeps (1 baseline diagnostic + 1 verification). Verification sweep passed 63/63 in all 8 parallel rounds with zero flakiness. (Orchestrator independently re-ran the 8-round sweep afterward: all 8 rounds passed=63 failed=0 total=63, confirming the result and regenerating results.{1..8}.json.)

**Baseline:** 6 deterministic failures (identical across all 8 rounds). Runner's `passed`/`failed` keys were source of truth; per-test `status` field gave the true union.

**Tests deleted:** None. All 6 failures traced to PRD-verbatim rules that uniquely determine the asserted outcome — every test kept.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `setup_questionnaire_flagged`: default `risk_weight=12` → `10`. PRD §3.8 states verbatim "a `risk_weight` integer between 0 and 10", so weight 12 was a fixture violating the PRD precondition (PRD-faithful impl correctly rejected with `ERR_INVALID_REQUEST`). On a required section the ×2 multiplier still yields final score 20 ≥ 20 → FLAGGED.

**Fixes applied to `test_suite/`:**
- `test_02_questionnaire_risk_scoring.py` — three call sites passing out-of-range `risk_weight=12` updated to `10` (`test_high_risk_acceptance_lands_flagged`, `test_revise_flagged_clears_final_score`, inline payload in `test_waive_copay_blocked_when_high_risk`). Hardcoded `final_risk_score == 24` (correct only for weight 12) updated to `== 20`.
- `test_04_session_lifecycle_queue.py` — `test_clock_advance_expires_incomplete_session`: setup reminder used `scheduled_local_min=120` (02:00), inside clinic's wrap-around quiet window [1320, 420) per PRD §3.12, so PRD-faithful impl rejected with `ERR_REMINDER_IN_QUIET_HOURS`. Moved reminder to `scheduled_utc=10:00`, `scheduled_local_min=600` (outside quiet hours, after clock target so it stays SCHEDULED until expiration sweep SUPPRESSES it).

**Fixes applied to `implementation/`:**
- `routes/intake_sessions.py` — `open_session`: session `created_at`/`expires_at` now derive from clinic's deterministic `current_utc` instead of wall-clock `db.now_iso()`. PRD §2.6/§1.3 state verbatim "Time in this system does not come from the wall clock" and "`expires_at` is computed as the session's `created_at` plus that many hours." Wall-clock value (year ~2026) made the clock-set-to-1970 expiration sweep never fire, breaking `test_sign_on_expired_session_blocked` and `test_clock_advance_expires_incomplete_session`.
- `routes/demographics.py` — `create_sync_job`: duplicate-`idempotency_key` branch now returns original job's data with `status` overridden to `SKIPPED_DUPLICATE` (stored original left at COMMITTED, patient not re-mutated). Previously returned original verbatim with status COMMITTED. PRD §3.9 states verbatim the duplicate "job's status becomes `SKIPPED_DUPLICATE`, no patient mutation occurs, and the original job is returned."

All changes increase PRD fidelity: no assertions weakened, no checks removed, no skips/xfails, no error_id→HTTP-status downgrades.

## Step 8: Finalize PRD — 2026-06-08T03:48:00.000Z

Produced `workspace/PRD_FINALIZED.md`. PRD.md = 356 lines, PRD_FINALIZED.md = 356 lines (delta 0 lines, +0.0%); two existing lines revised in place.

**Changes:**
- §2.6 — revise — Pinned that an intake session's `created_at` is stamped from the clinic's deterministic `current_utc` at creation time (not the wall clock); PRD previously only defined `expires_at = created_at + form_expiration_hours` without saying where `created_at` came from — `routes/intake_sessions.py:42,49`.
- §3.9 — revise — Pinned that a duplicate demographics-sync returns the original job with `status` shown as `SKIPPED_DUPLICATE` only in that response, while the stored original is left unmutated (retains persisted `COMMITTED` status / `updated_at` / `version`) and no new job is created — `routes/demographics.py:30-35`.

**Step_7_diff items intentionally NOT pinned (pure fixture/test bugs; PRD already determines behavior):**
- `fixtures.py` risk_weight 12→10 and `test_02` call-sites + hardcoded 24→20: trace to PRD §3.8's already-verbatim precondition "a `risk_weight` integer between 0 and 10". No PRD silence.
- `test_04` reminder moved out of quiet window: traces to PRD §3.12's already-pinned wrap-around quiet-hours rule and the expiration/reminder sweep. No PRD silence.

Per-edit NO-NEW-MISMATCH search: §2.6 edit scoped to "When an intake session is created" so wall-clock `created_at` on all other resources (config.py, consent, questionnaire, insurance, copay, reminders, room_bookings, demographics) and `touch()`/`updated_at` mutations stay un-described and consistent. §3.9 edit worded override as applying "only to the returned representation" with "e.g. COMMITTED" to avoid over-claiming the persisted status.

## Step 9: Complete PRD — 2026-06-08T03:54:17.000Z

Produced `workspace/PRD_COMPLETED.md`. Source PRD_FINALIZED.md (356 lines, 52,602 chars) → PRD_COMPLETED.md (356 lines, 54,290 chars). Char delta +1,688; line count unchanged (in-paragraph inserts/revisions only).

**Counts:** ambiguity-pins 4, mismatch-revisions 1.

**Per-change log:**
- §2.3 (Pagination) — insert — ambiguity — out-of-range `limit`/`offset` silently clamped (limit→[1,100], negative offset→0); non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — `services/pagination.py:29-34, 16-23`.
- §3.5 (Eligibility resolution) — revise — mismatch — blanket "resolving increments session version" was wrong for `NEEDS_REVIEW`; revised so only `ELIGIBLE`/`INELIGIBLE` mutate-and-bump the session while `NEEDS_REVIEW` records the check and bumps only the card — `routes/insurance.py:149-169`, `services/common.py:6-15`.
- §3.9 (Demographics sync duplicate) — insert — ambiguity — duplicate (`SKIPPED_DUPLICATE`) response still returns 201 Created, same code as a fresh commit — `routes/demographics.py:35`.
- §3.10 (Copay capture) — insert — ambiguity — capture's `COPAY_DUE→COPAY_SETTLED` cascade re-runs §3.4 readiness recompute, advancing `IN_PROGRESS→READY_FOR_VISIT` and enqueuing when forms already complete — `routes/copay.py:97-98`, `services/sessions.py:131-143`.
- §3.10 (Copay refund) — insert — ambiguity — refund touches only the financial dimension; a session already at `READY_FOR_VISIT` is not reverted and its queue entry not ejected (forms_complete unchanged) — `routes/copay.py:130-132`, `services/sessions.py:157-166`.
- §3.10 (Copay waive) — insert — ambiguity — successful waive likewise re-runs readiness recompute and may advance/enqueue per §3.4 — `routes/intake_sessions.py:159-161`.

**Notable non-changes:** `ERR_COPAY_REQUIRED_BEFORE_READY` defined but never raised (no force-ready endpoint in §4) — left as-is. Calculation/rounding, risk scoring, provider half-open / room closed-interval overlap, quiet-hours/min-gap, error catalogue, envelope/RBAC, and entity field shapes already match impl uniquely.

---

## Pipeline complete

All 9 steps finished. Final 8-round parallel stability sweep: **63/63 passing in all 8 rounds, zero flakiness.** Task `task_0245_patient_intake_digital_forms` (Expert band) is complete with PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, full test suite (63 tests), and a passing Python/Flask implementation.

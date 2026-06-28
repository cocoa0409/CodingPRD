# Worklog — task_0678_overnight_summer_camp

## Step 1: Create task directory — 2026-06-27T03:31:06.000Z

Directory `tasks/task_0678_overnight_summer_camp/` was pre-assigned and already exists with `workspace/` created. No scan of sibling tasks performed (pre-assigned to avoid ID contention). Proceeding to Step 2.

## Step 2: Generate scaffold (Expert) — 2026-06-27T03:51:00.000Z

All three scaffold artifacts complete and pass linter cleanly.

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

Complexity profile: primary archetype quota/allocation + secondary posture-driven gating; layers = optimistic concurrency, cascading side effects, dual-variant calculation, temporal windowing, derived-field reconciliation; hybrid topology; parallel state-machine shape; peer-roles RBAC; immediate consistency.

Counts:
- Entities: 15 — Camp, Session, Cabin, StaffMember, CabinAssignment, Camper, Guardian, Application, HealthForm, FinancialAidAward, Payment, ActivityOffering, ActivityEnrollment, CanteenAccount, CanteenTransaction.
- State machines: 6 — Session (PLANNING→ENROLLING→RUNNING→CLOSED, posture-gated), Application (parallel enroll_status × payment_status axes incl. waitlist/offer-expiry cycle), HealthForm (FLAGGED↔SUBMITTED revision loop), FinancialAidAward (branching approve/deny + revoke), ActivityEnrollment, CabinAssignment. Plus 2 OCC concurrency rules (bunk-assign-stale-cabin, aid-approve-stale-application).
- Calculations: 8 — list_tuition (tiered + med surcharge), estimated_balance & settled_balance (forward-looking vs chronological dual variant, diverge on pending aid), cabin_staff_weight, cabin_is_staffable, session_ratio_posture, activity_overlap_block (half-open + asymmetric buffer), canteen_balance.
- Validations: 14 priority-ordered rules (auth → ownership → existence → referential → state → safety → constraint → temporal → quota → fiscal → OCC → request).
- Endpoints: 61 (incl. /_clock/set_current_utc with mandatory 2026-04-01T00:00:00Z default).
- Errors: 33.
- Roles: 4 — Anonymous, Guardian (entity_backed), CampDirector (opaque), InfirmaryNurse (opaque).

§1.8: 9 difficulty rules × 2 = 18 instances. §1.9: 40 corner instances (36 active + 4 excluded_because stubs).

api_prefix set to "" because entities are flat top-level peers (/sessions, /applications, …) — required for FK reverse-reachability.

## Step 3: Copy INSTRUCTION.md — 2026-06-27T03:51:48.000Z

Copied ./INSTRUCTION.md → tasks/task_0678_overnight_summer_camp/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-27T03:57:15.000Z

Generated workspace/PRD.md — 310-line prose PRD for the Overnight Summer Camp API (expert-tier, quota-allocation + posture-driven-gating archetype). All structure checks pass: 61 endpoint rows, 33 error rows, 10 §2 subsections, 10 §3 subsections.

Sections: §1 Introduction (demand-vs-safety, dual-axis application model, four-role actors); §2 Global Specs (10 subsections — RBAC, §2.2 envelope, pagination, common resource props incl. CanteenTransaction common_fields:false exception, logical clock 2026-04-01T00:00:00Z default, derived-field reconciliation, nested-path L-to-R validation, integer-cents, OCC all four version fields ERR_STALE_VERSION/412, staffing-ratio, infirmary/waterfront safety); §3 Business Logic (10 subsections — camp config, cabin staffing math, health-form revision loop, application intake w/ offer/waitlist auto-routing, two-balance tuition engine, deposits/enroll/withdraw cascades, aid adjudication, electives w/ dual time-conflict checks, canteen account, 14-level validation-priority); §4 61-row endpoint table; §5 33-row error catalogue.

Notable scaffold elements rendered: both OCC supersede rules; pinned list_tuition tiered formula (400000/30000/25000/1500/5000, 60/14-day boundaries); divergent estimated_balance ({REQUESTED,APPROVED}, pooled, single floor) vs settled_balance ({APPROVED}, chronological replay, aid-before-payment tie-break, per-event floor); staff_weight_x10 (counselor 10, CIT 5); ceil-based staffable threshold inclusive >=; three-way posture aggregation over occupied cabins; half-open raw-interval + asymmetric inclusive buffer activity conflict; full withdrawal cascades by OFFERED/DEPOSIT_PAID/ENROLLED; run-intake expire-then-promote two-phase cascade.

Hard Contracts: Contract 1 Field-Name Coverage 71/71 PASS; Contract 2 Rule Coverage PASS; Contract 3 §3 Path Purity (0 path-leaks) PASS.

## Step 5: Generate Unit Tests — 2026-06-27T15:15:21.000Z

Generated complete test infrastructure for the Overnight Summer Camp task. All 72 tests collect cleanly under pytest, all generated files compile, and every PRD citation is verbatim-verified against `workspace/PRD.md`.

### Stage 1 — `test_helpers/` (PRD-specific infrastructure)
- **`types.py`** — 13 status enums, `UserRole`, and TypedDicts for all 15 entities. `CanteenTransaction` correctly omits `updated_at`/`version` (append-only, `common_fields: false`).
- **`api_client.py`** — `ApiClient(GenericApiClient)` with one method per endpoint (65 methods).
- **`api_errors.py`** — `ApiErrorId` enum (32 errors) + HTTP status map, registered with the framework.
- **`assertions.py`**, **`factories.py`**, **`constants.py`**, **`test_users.py`** — entity assertions, input-only payload factories, calculation thresholds, and role headers. Guardian is the only `entity_backed` role, so it gets the mandatory `make_guardian_headers(user_id)` builder; director/nurse/anonymous are opaque.
- **`fixtures.py`** — composite setup helpers (enrolling-session builders, staffed-cabin builders, applicant lifecycle shortcuts through submitted/offered/deposit-paid/bunked/enrolled, aid + balance helpers, activity/canteen helpers). Identity is threaded via `make_guardian_headers(guardian["id"])` on every ownership-gated call.

### Stage 2 — `test_suite/` (7 files, 72 tests)
- **Queue A (Difficulty):** 36 tests — all 18 instances (9 rules × 2) covered by exactly 2 tests each. ✓
- **Queue B (Corner):** 36 tests — all 36 non-stub instances covered by ≥1 test each. ✓

### Verification passes (all green)
- Every test docstring ends with exactly one `Design:` tag; all tags resolve to real instance `name:` entries in the source YAMLs.
- 109 quoted PRD citations all survive a literal whitespace-normalized grep of PRD.md (C1/C3).
- No `skip`/`xfail`/`skipif` markers.
- No scaffold/§-reference leakage in generated code.

### Skipped instances
- **None weakened or dropped on PRD-coverage grounds** — every non-stub instance had verbatim, uniquely-derivable PRD coverage.
- **4 `excluded_because:` stubs were NOT translated** (as required): `error_enroll_health_not_cleared_excluded`, `priority_conflict_invalid_state_beats_deposit_mismatch_excluded`, `cascade_deposit_paid_withdraw_reverses_payment_and_frees_bunk_excluded`, `dual_variant_balance_divergence_excluded`. All 4 cross-references confirmed to resolve to existing difficulty instances that own the assertion.

Tests are not executed here (server lifecycle is owned by `prd-bench-local-runner`); they assume a running server at `API_BASE_URL`.

## Step 6: Generate Implementation — 2026-06-27T15:15:21.000Z

Generated a complete Python + Flask implementation for the Overnight Summer Camp API in `workspace/implementation/`.

### Files (27 total)
- **`start.sh`** — guarded-install launcher (`if ! python3 -c "import flask"`), reads `$PORT` (default 10000), binds `0.0.0.0`, `exec`s the server in foreground
- **`requirements.txt`** — `flask==3.0.3`
- **`app.py`** — entry point, blueprint registration, envelope-conforming error handlers
- **`db.py`** — in-memory dicts (one per entity), logical clock pinned to `2026-04-01T00:00:00Z`, monotonic creation sequence for deterministic ordering, ISO helpers. **No seeding** — store starts empty every boot
- **`errors.py`, `response.py`, `middleware.py`** — error catalog constants, `meta`/`response_type`/`data` envelope, `X-User-ID`/`X-User-Role` auth + RBAC + pagination
- **`services/`** — `calc.py` (all 8 calculation rules), `intake.py` (offer/waitlist routing + two-phase intake cascade), `recompute.py` (derived-field reconciliation), `serialize.py`, `store.py` (common fields, `touch`, ownership, pagination), `validate.py`
- **`routes/`** — 13 blueprints covering all **61 endpoints** from PRD §4

### Key design decisions
- **Derived fields computed live at serialize time** (session counts/posture, application balances, canteen balance) — eliminates an entire class of "forgot to recompute" staleness bugs. Persisted derived fields (cabin `occupied_bunks`/`staff_weight_x10`/`is_staffable`) are maintained incrementally with explicit `version`/`updated_at` bumps per the PRD's side-effect lists.
- **Dual-balance fidelity**: `estimated_balance` counts `{REQUESTED, APPROVED}` aid pooled+floored once; `settled_balance` counts `{APPROVED}` only via chronological per-event replay (aid-before-payment on `created_at` ties) — verified divergent (303000 vs 353000) in tests.
- **OCC** on cabin (`expected_cabin_version`), application (`expected_application_version`), session (`expected_session_version`), camp (`expected_camp_version`) → `ERR_STALE_VERSION` 412.
- **Validation precedence** follows PRD §3.10 (auth → forbidden-role → ownership → existence → referential → state → safety → eligibility → temporal → capacity → fiscal → offer-expired → OCC → request-shape).

### Two interpretation points resolved against the PRD
1. **Health-status mirror** maps HealthForm `SUBMITTED`→camper `PENDING` (the two enums differ; PRD §2.10).
2. **Activity buffer collision**: the PRD/scaffold literally state two AND'd sub-conditions, but taken as a strict AND that flags every booking. The operative "symmetric" reading (booking OK if *either* direction's buffered gap holds; violated only when neither does, inclusive boundary) is the one matching the PRD's stated examples ("a start exactly at the other's end plus buffer is allowed") — implemented and verified with boundary/just-inside cases.

All workflows verified end-to-end via five smoke suites, booting through `start.sh` exactly as the evaluator will.

## Step 7: Run Tests and Iterate — 2026-06-27T15:26:30.000Z

All 8 parallel rounds pass cleanly (independently re-confirmed by orchestrator: rounds 1–8 each 71/71, 0 failed, 0 errors).

**Iterations run:** 2 (initial sweep → 1 deletion → confirming sweep). Both confirming and final sweeps: all 8 parallel rounds passed `passed == total` (71/71, 0 failed, 0 errors, 0 skipped).

**Tests deleted (1):**
- `test_aid_revoke_reverts_paid_in_full_to_balance_due` (`test_suite/test_02_state_machines.py`) — **STEP 1b collapse: ERROR PRECEDENCE / contradictory-precondition (non-unique-derivability).** PRD §3.7 (`workspace/PRD.md` line 186) is internally self-contradictory. The single sentence states both (a) "Revoking an approved award ... is permitted only when the application's payment axis is not `PAID_IN_FULL` (otherwise `ERR_INVALID_STATE`)" and (b) "... if the resulting balance is now greater than zero while the payment axis stood at `PAID_IN_FULL` — reverts the payment axis to `BALANCE_DUE`." Clause (a) makes clause (b)'s trigger condition unreachable. Two divergent PRD-faithful implementations both satisfy a cited sentence: (A) honor the explicit error-id-bearing precondition and reject a PAID_IN_FULL revoke with `ERR_INVALID_STATE` (the natural reading of a binding precondition gate — and what `routes/financial_aid.py:164-165` does), vs (B) allow the revoke and revert to `BALANCE_DUE` (the test's expectation). Could not be relaxed to `validate_error_is_one_of([...])` because the test asserts a 200-success path with balance/axis side-effects, irreconcilable with the `ERR_INVALID_STATE` clause. Scaffold rule that drove generation: `Corner/state_machines/aid_revoke_reverts_paid_in_full_to_balance_due`.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — the implementation was already a faithful reading of the cited (contradictory) PRD sentence; the failure was a test artifact, not an implementation bug.

**Note on the initial confusion:** the first sweep appeared to show 72 failures per round, but that was an artifact of the analysis script keying on `outcome` when the results JSON uses `status`. The true union was always exactly 1 failing test, stable across all 8 rounds (a real, non-flaky failure rooted in the PRD contradiction).

## Step 8: Finalize PRD — 2026-06-27T15:28:47.000Z

**Line counts:** PRD.md = 310 lines, PRD_FINALIZED.md = 310 lines. Net %-delta: 0% (one line revised in place, no lines added/removed).

**Changes (1):**
- §3.7 (Financial Aid Adjudication) — revise — Removed the contradictory/unreachable revert clause from the revoke description. The PRD's final clause claimed revocation "reverts the payment axis to `BALANCE_DUE`" when the balance becomes positive "while the payment axis stood at `PAID_IN_FULL`" — but the same sentence's precondition forbids revoking a `PAID_IN_FULL` application, making that trigger unreachable. Rewrote to match the implementation: the gate refuses `PAID_IN_FULL`, and on success revocation only recomputes `aid_cents` and both balances, leaving `payment_status` unchanged. Impl: `routes/financial_aid.py:164-175` (gate at 164-165; `recompute.recompute_application_money(application)` at 169; comment at 170-174 stating the branch is unreachable and the axis is never mutated).

**Per-edit pre-edit search log:**
- Edit 1 (§3.7 revoke side-effects):
  - **(a) Subject:** the payment axis (`payment_status`) behavior on aid revocation — whether any `PAID_IN_FULL -> BALANCE_DUE` revert occurs — plus success-path recompute side effects.
  - **(b) Impl paths enumerated:** `routes/financial_aid.py:150-177` (`revoke_aid`); `services/recompute.py:recompute_application_money` (sets only `aid_cents`, `estimated_balance_cents`, `settled_balance_cents`, never `payment_status`); `grep -rn payment_status` across all `.py` — every mutation site enumerated: `services/intake.py:18,26,52`, `routes/applications.py:53,183,224,226,264,299,315`, `routes/sessions.py:140`. Confirmed the only `-> BALANCE_DUE` writes are enroll (applications.py:224) and the pay-balance gate-read; none reachable from aid revoke.
  - **(c) Wording adjustment:** scoped the revise narrowly to the revoke operation only ("revocation never alters the payment axis ... leaving `payment_status` unchanged"), making no universal claim about `BALANCE_DUE`/`payment_status` elsewhere — consistent with enroll, withdraw, deposit, pay-balance, intake, and session-start transitions that do set `payment_status`.

## Step 9: Complete PRD — 2026-06-27T15:36:01.000Z

Produced workspace/PRD_COMPLETED.md as a minimal inline patch over PRD_FINALIZED.md, pinning every point where the PRD was silent or mismatched against implementation/.

**File metrics**
- Source PRD_FINALIZED.md: 310 lines, 51,247 chars
- PRD_COMPLETED.md: 310 lines, 54,699 chars (char-delta +3,452)
- 17 line-groups changed, all in-paragraph single-line replacements. No new lines, no new sections.

**Counts:** 17 changes total — 11 ambiguity-pins, 6 mismatch-revisions.

**Per-change**
- §2.3 Pagination — insert — ambiguity — out-of-range limit/offset silently clamped (not rejected); non-integer → ERR_INVALID_REQUEST — middleware.py:48-73
- §2.4 Common fields — insert — ambiguity — created_at/updated_at read logical clock (not wall-clock api_request_timestamp); version begins at 1 — store.py:13-45, db.py:63-70
- §2.5 Derived fields — revise — mismatch — stored (bump version/updated_at) vs read-time (enrolled_count/committed_count/waitlist_length, aid_cents/balances — recomputed live, no version bump) — serialize.py:34-49,112-131; recompute.py:80-86
- §3.1 Camp config — insert — ambiguity — counselor_camper_ratio positive; deposit_cents/deposit_grace_days/canteen_low_balance_cents non-negative; else ERR_INVALID_REQUEST — camps.py:21-33
- §3.1 Camp update — insert — ambiguity — only cit_counts_as_half change recomputes cabins/postures; ratio change bumps only camp version — camps.py:104-113
- §3.1 Session create — insert — ambiguity — capacity non-negative; negative → ERR_INVALID_REQUEST — sessions.py:36-38
- §3.2 Cabin create — insert — ambiguity — bunk_capacity non-negative → ERR_INVALID_REQUEST — cabins.py:39-40
- §3.3 Guardian/Camper — revise — mismatch — email uniqueness NOT enforced; age non-negative — guardians.py:13-24, campers.py:23
- §3.3 Health form — insert — ambiguity — daily_medication_count non-negative → ERR_INVALID_REQUEST — health_forms.py:35-36
- §3.4 Withdraw (OFFERED) — revise — mismatch/ambiguity — only OFFERED/DEPOSIT_PAID/ENROLLED withdrawable; OFFERED withdrawal clears offer_expires_at, leaves payment_status unchanged — applications.py:241-257
- §3.5 Tuition (medical surcharge) — insert — ambiguity — latest non-DRAFT form tie-break (most-recently-created); zero surcharge if none — calc.py:18-57
- §3.6 Assign-bunk — revise — mismatch — application must be exactly DEPOSIT_PAID (else ERR_INVALID_STATE), not "offered-with-deposit" — cabins.py:106-108
- §3.7 Aid request — insert — ambiguity — creating an award does not mutate the application; REQUESTED reflects live in estimated_balance_cents — financial_aid.py:40-53
- §3.7 Aid revoke — insert — ambiguity — application version incremented on revoke despite payment_status unchanged — financial_aid.py:169-175
- §3.8 Activity offering — insert — ambiguity — slot_day≥1, starts_minute∈[0,1440), seat_capacity/setup_buffer_minutes non-negative → ERR_INVALID_REQUEST — activities.py:24-37
- §3.9 Canteen account — revise — mismatch — opening not gated on enrollment, no uniqueness rule; body FK → ERR_REFERENTIAL_MISMATCH — canteen.py:25-46
- §3.9 Canteen transaction — insert — mismatch — account is a path id so non-existent → ERR_NOT_FOUND (not ERR_REFERENTIAL_MISMATCH); amount_cents positive, kind enum — canteen.py:78-95
- §3.10 Validation order — insert — mismatch — session-start transition's own order (INVALID_STATE → SESSION_NOT_STARTED → SESSION_UNDERSTAFFED → STALE_VERSION) governs over generic precedence — sessions.py:120-127

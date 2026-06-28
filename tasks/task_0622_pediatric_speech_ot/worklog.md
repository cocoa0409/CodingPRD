# Worklog — task_0622_pediatric_speech_ot

## Step 1: Create task directory — 2026-06-22T11:33:31.000Z

Created `./tasks/task_0622_pediatric_speech_ot/workspace` (pre-assigned directory, index NOT auto-computed). Verified `INSTRUCTION.md` and `skills/` present at project root.

## Step 2: Generate scaffold (Expert band) — 2026-06-22T11:55:48.000Z

Generated a complete, lint-clean three-file scaffold for **task_0622_pediatric_speech_ot** at the **Expert** difficulty band, built solely from the verbatim scenario and the scaffold-generator spec (no sibling tasks consulted).

**Files written** (all under `tasks/task_0622_pediatric_speech_ot/`):
- `SCAFFOLD.yaml` (§1.0–§1.7) — 1453 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`) — 1319 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`) — 1633 lines

**Complexity profile:** primary archetype Quota/allocation (insurance visit caps: reserve → commit → release/replenish) + secondary Temporal windowing (therapist/child scheduling); layers = optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers; topology hybrid; cyclic state-machine shape; peer-role model; immediate consistency.

**Contents:**
- **12 entities** (Child, Therapist, Evaluation, PlanOfCare, Goal, Authorization, Appointment, SessionNote, GoalProgressEntry [append-only, common_fields:false], CoordinationPlan, HomeProgram, WaitlistEntry) with 20 canonical-prefixed FKs, all reverse-reachable.
- **8 state machines / 34 transitions**, including non-linear shapes: WaitlistEntry cycle (WAITING↔OFFERED), Appointment branching (SCHEDULED→{COMPLETED,CANCELLED,NO_SHOW}), Authorization reauth cycle, PlanOfCare revert loop, Goal MET↔OPEN regression.
- **2 concurrency rules** (OCC on `Authorization.version` for request-reauth and grant-reauth, 412/ERR_STALE_VERSION).
- **6 calculations** (visit_balance reserved-vs-committed, goal_progress forward-vs-chronological, recommended_weekly_minutes tiered, weekly_minutes_load, waitlist_promotion, reauth_replenish) — all decisions use `created_at`, never `id`.
- **12 ordered validations**, **55 endpoints** (32 POST + 23 GET, including a `/_clock/set_current_utc` test-driving endpoint with the mandatory 2026-01-01T00:00:00Z default), **39 errors**, **4 roles** (ClinicAdmin/SchedulingCoordinator opaque; Evaluator/Therapist entity_backed:Therapist).

**Design instances emitted:** §1.8 = **18** difficulty instances (all 9 §0.5 rules × 2); §1.9 = **37** corner instances (36 active + 1 `excluded_because` stub) across 8 claim-guide sections.

**Validation:** `scaffold_lint.py` → `VERDICT: clean lint` (492 calls scanned, checks a–f pass). Verified: SCAFFOLD.yaml contains neither design key; design files carry correct single top-level keys.

## Step 3: Copy shared files — 2026-06-22T11:56:17.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-22T12:01:33.000Z

Generated `workspace/PRD.md` — **307 lines** — for the Pediatric Speech & OT Clinic API (mounted under `/clinic`). Design files NOT read.

**Sections produced:**
- §1 Introduction (allocation-under-scarcity framing)
- §2 Global Specifications — 11 subsections: RBAC, Response Structure (verbatim), Pagination, Common Properties/Versioning, Nested Retrieval/Existence, Visit Accounting (reserved/committed/available), Therapist Capacity (caseload + ISO-week minutes), Goal Progress/Roll-Up (chronological vs forward-looking), OCC on Reauthorization, Precision/Rounding, Logical Clock
- §3 Business Logic — 9 subsections by entity lifecycle/process
- §4 Endpoint table (57 endpoints)
- §5 Error catalogue (39 errors)

**Scaffold coverage confirmed:** all 12 entities (GoalProgressEntry id/created_at only); all 9 state machines with transitions, preconditions+errors, side-effects/cascades; all 6 calculations (visit_balance dual view, goal_progress clamped+chronological tie-break, recommended_weekly_minutes tiers 30/60/90/120, weekly_minutes_load ISO-week strict-greater, waitlist_promotion ranking, reauth_replenish conservation); all 12 validations with priority ordering; both OCC rules (expected_authorization_version → ERR_STALE_VERSION 412); all 57 endpoints; all 39 errors; all 4 roles.

**Hard Contracts:** Contract 1 (Field-Name Coverage) PASS (59/59); Contract 2 (Rule Coverage) PASS; Contract 3 (§3 Path Purity) PASS (0 violations); §2.2 verbatim block byte-for-byte match.

## Step 5: Generate unit tests — 2026-06-22T12:17:08.000Z

Generated complete test infrastructure for the Pediatric Speech & OT Clinic PRD benchmark task.

**Test files:** 9 test files (plus `conftest.py`) under `test_suite/`, organized in domain language from simple to complex.

**Total test functions:** 72, all collecting cleanly under pytest.

**Queue split:**
- **Queue A (Difficulty):** 36 tests — all 18 difficulty instances covered with exactly 2 tests each. Covers dual-variant calc (visit balance & goal progress), combinatorial formula, non-linear/cyclic state machines, transitive cascades (depth-2 & depth-3), validation-precedence pairs, boundary precision, cross-entity state dependency, resource temporal overlap, and compensating invariants.
- **Queue B (Corner):** 36 tests — all 36 non-stub corner instances covered with 1 test each.

**Instances skipped:** 1 — the single `excluded_because:` stub `Corner/validations/visit_cap_exceeded_excluded_difficulty`. Correctly NOT translated; its cross-reference resolves to a real difficulty instance owning the assertion (covered by 2 queue-A tests). No instances dropped for PRD-coverage failures.

**test_helpers/ files produced (9):** `__init__.py`, `types.py`, `api_errors.py`, `constants.py`, `factories.py`, `test_users.py`, `assertions.py`, `api_client.py`, `fixtures.py`.

**Verification:** All 72 tests carry exactly one `Design:` tag; 18/18 difficulty + 36/37 corner (1 stub excluded); all 104 citation snippets verbatim against PRD.md; no scaffold/§1.x leakage; no skip/skipif/xfail; identity threading honored (entity_backed Evaluator/Therapist use per-instance header builders; opaque ClinicAdmin/SchedulingCoordinator use shared constants).

## Step 6: Generate implementation — 2026-06-22T12:17:08.000Z

Built a complete Python + Flask implementation at `workspace/implementation/` (mounted under `/clinic`).

**File list:** `start.sh` (guards pip install behind flask-import check, then `exec python3 app.py`), `requirements.txt` (flask==3.0.3), `app.py` (reads `$PORT` default 10000, binds 0.0.0.0, foreground), `clock.py` (logical clock default 2026-01-01T00:00:00Z, ISO 3-digit fractional, month/minute/ISO-week math), `db.py` (in-memory dict per entity, UUID minting), `errors.py`, `response.py`, `middleware.py` (X-User-ID/X-User-Role auth + RBAC), `validation.py`, `services/` (common, calc, engine, booking, serialize), `routes/` (one module per resource group).

**Framework/launch/state:** Flask foreground via `exec python3 app.py`; `$PORT` honored; 0.0.0.0. Storage in-memory only — empty `DB()` at import, every start.sh re-invocation wipes all state. No seeding/preloading. Clock defaults to 2026-01-01T00:00:00Z; `/clinic/_clock/set_current_utc` sets it and auto-expires due authorizations.

**Coverage:** All 55 PRD endpoints registered. State machines (Evaluation, PlanOfCare w/ ON_HOLD revert + cascades, Goal OPEN↔MET revert + DISCONTINUED, Authorization cycle, Appointment branches w/ divergent visit effects, CoordinationPlan IFSP→TRANSITIONING→CLOSED, HomeProgram, WaitlistEntry re-offer loop). Calculations (tiered recommended_weekly_minutes, reserved/committed/available balance, ISO-week weekly load ==cap OK/>cap reject, forward-looking weighted roll-up + chronological per-goal latest ROUND_HALF_UP 2dp, waitlist promotion priority DESC/created_at ASC). Validations in PRD priority order with exact error_id/HTTP. OCC on both reauth endpoints via expected_authorization_version → ERR_STALE_VERSION 412, checked after state legality. Cascades: hold/discharge cancel SCHEDULED appts (release visit + promotion); discharge cancels home programs. GoalProgressEntry omits version/updated_at.

Note: on waitlist decline, the declined entry is excluded from the immediate promotion re-run so the next-highest-priority entry is offered (per PRD §3.8).

## Step 7: Test & fix loop — 2026-06-22T12:17:08.000Z

All tests pass cleanly. Exited after two consecutive clean 8-round parallel sweeps (16 rounds total), every round 72/72.

**Iterations run:** 1 diagnostic iteration (one round of fixes), then 2 confirming 8-round parallel sweeps.

**Initial failure set (union across first 8-round sweep):** 10 distinct tests — 5 consistent assertion failures and 5 sporadic "server could not be restarted" boot-flakiness failures (one test, `test_create_evaluation_missing_severity_rejected`, hit the boot race in 7/8 rounds).

**Tests deleted:** None. All failing tests traced to verbatim PRD prose and were uniquely derivable; failures were genuine implementation/test bugs and environmental contention, not PRD silence.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:**
- `test_01_intake_and_evaluation.py`, `test_goal_progress_entry_is_append_only_no_version` — changed the `recorded_session_time` assertion from a hard-coded input string (`"2026-06-10T09:00:00Z"`) to compare against the appointment's own stored `start_time` (`appt["start_time"]`). PRD §3.6 fixes the *instant* ("copied from the appointment's `start_time`"); PRD §2.4 mandates three-fractional-digit serialization only for `created_at`/`updated_at`, so the exact `Z` vs `.000Z` form of `start_time` is FORMAT-SILENCE (not uniquely derivable). STEP 1c partial-coverage split: kept the covered value/instant assertion, removed the non-derivable format dependency.

**Fixes applied to `implementation/`:**
- `services/booking.py`, `book_appointment` — the authorization-window check (priority 7) rejected *any* non-`ACTIVE` status as `ERR_AUTH_WINDOW_VIOLATION`, masking the capacity check for `EXHAUSTED` authorizations. Narrowed status rejection to `EXPIRED`/`CLOSED` only, so an `EXHAUSTED` auth falls through to the visit-cap check and correctly reports `ERR_VISIT_CAP_EXCEEDED` (PRD §3.4: "while `EXHAUSTED` any new reservation against it is rejected with `ERR_VISIT_CAP_EXCEEDED`"; §3.5: visit-cap is "the last word"). Fixed `test_visit_cap_exceeded_at_zero_available`, `test_visit_cap_reported_when_only_capacity_violated`, `test_reservation_at_zero_available_is_rejected_not_negative`, and `test_double_booked_outranks_visit_cap_exceeded`.
- `app.py`, `__main__` boot — added an `SO_REUSEADDR` bind probe with a short retry loop (up to 12s) before `app.run()`. Under `--isolation per-test-server` with 8 concurrent rounds, the runner SIGKILLs the previous server and immediately re-spawns on the same port; a lingering listening socket could make the immediate bind fail and the process exit prematurely. Retrying the bind absorbs that transient collision, eliminating the boot flakiness (5 sporadic setup failures → 0 across both confirming sweeps).

(Orchestrator re-running an independent verifying 8-round sweep to regenerate the final `results.{1..8}.json` artifacts, which the loop's trailing `rm -f` had cleared.)

**Orchestrator verification sweep:** Independent 8-round parallel sweep run by the orchestrator → all 8 rounds 72/72/0 (passed/total/failed). `results.{1..8}.json` regenerated in `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-06-22T12:38:02.000Z

Produced `workspace/PRD_FINALIZED.md`. Step 8 ran (not skipped — Step 7 had 1 test_suite fix + 2 implementation fixes).

**PRD.md vs PRD_FINALIZED.md:** lines 307 → 307 (single in-place line revision); chars 49,238 → 49,667 (+429, +0.87%).

**Changes (1 edit):**
- §3.5 (Scheduling, line 169) — revise — the authorization-window status gate. PRD said the authorization "must be `ACTIVE`"; the implementation only rejects `EXPIRED`/`CLOSED` at that gate and lets `EXHAUSTED` and `REAUTH_REQUESTED` pass through to the later visit-cap test. Rewrote to match: only `EXPIRED`/`CLOSED` reject as `ERR_AUTH_WINDOW_VIOLATION`; `EXHAUSTED` falls through to `ERR_VISIT_CAP_EXCEEDED`; `REAUTH_REQUESTED` with `available_visits > 0` may book. — `implementation/services/booking.py:60-65` (booking battery, shared by both booking routes).

**Pre-edit search log (edit 1, §3.5 auth-window gate):** (a) subject = priority-7 authorization-window status check and which lifecycle states it rejects; (b) enumerated `services/booking.py:48-65` (window check), `:98-101` (visit-cap fall-through), `routes/appointments.py:37` (direct booking), `routes/waitlist.py:86` (waitlist accept → same `book_appointment`), `services/engine.py:16-28` reconcile_authorization (EXHAUSTED reachable), `:117-129` expire_due_authorizations (clock → EXPIRED); cross-checked PRD §3.4 lines 157/161 and §3.5 line 195; (c) widened "must be ACTIVE" to explicit allow/reject-by-state with parenthetical tying EXHAUSTED→visit-cap and REAUTH_REQUESTED→capacity-permitting, kept line 195 untouched.

**Other two Step 7 items → NO PRD edit:** `app.py` SO_REUSEADDR bind-retry = process-boot/environment robustness only, no observable API surface; `test_suite/` `recorded_session_time` change = test-only format-silence correction (instant already pinned §3.6 line 175; serialized form genuine format-silence per §2.4, deliberately left under-determined).

## Step 9: Complete PRD — 2026-06-22T12:43:38.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation completeness scan (base = PRD_FINALIZED.md).

**Source vs completed:** lines 307 → 307 (all edits in-paragraph, no new sections); chars 49,667 → 51,823 (+2,156).

**Counts:** 1 mismatch-revision, 7 ambiguity-pins (8 edits total).

**Per-change log:**
- §2.3 Pagination — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (not clamped); `offset` min 0; empty/absent → default — `services/common.py:51-62`
- §2.3 Pagination — insert — ambiguity — list tie-break by resource `id` ascending when `created_at` ties; list endpoints accept equality-match filters on listed fields, unknown params ignored — `services/common.py:67`, per-route filter loops
- §3.1 Children — revise — mismatch — `coordination_program` derived only from a plan whose status is exactly `ACTIVE` (a `TRANSITIONING` plan does not drive it) — `services/engine.py:42-48`
- §3.1 Children — insert — ambiguity — `age_months_at_intake` = calendar-month difference with day-of-month carry (decrement when creation day < birth day) — `clock.py:55-67`
- §3.2 Evaluation — insert — ambiguity — new evaluation's `recommended_weekly_minutes` is `null` (field always present) until finalization — `routes/evaluations.py:31`, `services/serialize.py:43`
- §3.3 Plan of care — revise — mismatch — single activate endpoint dispatches on status (DRAFT→initial, ON_HOLD→re-activate); any other status → `ERR_PLAN_NOT_DRAFT`; `ERR_PLAN_NOT_HELD` never emitted — `routes/plans.py:69-101`
- §3.3 Goals — insert — ambiguity — adding a goal to a plan not in DRAFT/ACTIVE rejected with `ERR_INVALID_STATE` — `routes/goals.py:40-42`
- §3.6 Completion — insert — ambiguity — a `goal_id` in `goal_progress_entries` naming no existing goal → `ERR_GOAL_PLAN_MISMATCH`, not `ERR_NOT_FOUND` — `routes/appointments.py:99-103`

**Key finding:** the one true mismatch was coordination-program behavior during EI→school transition — original PRD §3.7 asserted the program stays `EARLY_INTERVENTION` while a plan is `TRANSITIONING`, but impl derives the program strictly from an `ACTIVE`-status plan, so begin-transition recomputes to `NONE` (absent another active plan). §3.1/§3.7 revised to match impl. Verified already-pinned and left untouched: booking battery ordering/errors (§3.5), visit accounting (§2.6), weekly-minute/ISO-week (§2.7), goal/plan roll-up math (§2.8), OCC on reauth (§2.9), auth expiry/exhaustion (§3.4), clock contract (§2.11).

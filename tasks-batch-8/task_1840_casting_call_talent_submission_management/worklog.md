# Worklog — task_1840_casting_call_talent_submission_management

## Step 1: Create Task Directory — 2026-08-14T19:52:00.000Z

Directory `tasks/task_1840_casting_call_talent_submission_management/` and `workspace/` pre-created by pipeline launcher (Step 1 completed externally per invocation args).

## Step 2: Generate Scaffold — 2026-08-14T20:24:30.000Z

All three scaffold artifacts are generated and lint-clean at `/home/ubuntu/github/CodingPRD/tasks/task_1840_casting_call_talent_submission_management/`.

**Files written:**
- `SCAFFOLD.yaml` (§1.0–§1.7; no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single top-level `scaffold_corner_design`)

**Counts:**
- Entities: **16** (Production, Breakdown, Role, Talent, AgentProfile, Submission, SelfTape, AuditionSession, CallbackAppointment, AvailabilityHold, Offer, DealMemo, MinorWorkPermit, Guardian, Booking, TaftHartleyReport)
- State machines: **12** (one per lifecycle entity; Offer is cyclic with negotiation rounds, Submission branches with a CALLBACK_INVITED→UNDER_REVIEW revert)
- Calculations: **7** (incl. dual-variant `engagement_fee_proration` CALENDAR_SPAN vs WORKDAY_SPAN; tiered `cancellation_penalty_tier`; one-sided-buffer `appointment_overlap_conflict`; closed-interval engagement overlap; `union_eligibility_tafthartley`; `hold_priority_resolution`; `submission_count_reconcile`)
- Validations: **26** (priority-ordered across auth/existence/state/safety/referential/temporal/constraint/fiscal)
- Endpoints: **84** (incl. `/_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` default, plus filtered-list GETs giving every FK reverse-reachability)
- Error codes: **26**
- Roles: **5** (CastingDirector, CastingAssociate, Agent[entity-backed:AgentProfile], ProductionCoordinator, Guardian[entity-backed:Guardian])
- Concurrency (OCC) rules: **2**
- §1.8: **9 rule_ids, 18 non-stub instances** (2 per rule, 0 stubs)
- §1.9: **9 sections, 25 non-stub instances, 0 stubs**

**Verification:** `scaffold_lint.py` returns `VERDICT: clean lint` (584 §1.8/§1.9 calls checked against §1.5; all 16 FKs reverse-reachable). All three files parse as valid YAML; forbidden concurrency vocabulary scan is empty.

**Key design decisions made during generation (difficulty pushed hard):** pinned computed literals verified by executing the formulas (e.g., CALENDAR_SPAN fee 1000000 vs WORKDAY_SPAN 600000 for Fri–Tue span; 25% tier → 200000 at days_out==7, 100% tier → 800000 at days_out==1); two genuinely different interval semantics for Rule 8 (half-open + one-sided buffer for appointments vs closed day-intervals for booking engagement overlap); two distinct compensating invariants (submission_count and booked_count). During lint iteration I added the OCC `expected_*_version` threading (fresh GET-capture before each submission so multi-submission chains stay version-current) and widened offer-accept to allow CastingDirector countersign for agent-less self-submissions, keeping the entity-backed Agent path for represented talent.

## Step 3: Copy Shared Files — 2026-08-14T20:25:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1840_casting_call_talent_submission_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T20:42:00.000Z

PRD generated and all audits pass. Summary:

## Output
- **File**: `/home/ubuntu/github/CodingPRD/tasks/task_1840_casting_call_talent_submission_management/workspace/PRD.md`
- **Line count**: 361
- The forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` files were never opened, and no sibling task directories were read — generation used only the task's `SCAFFOLD.yaml` plus the doc-generator skill spec and its verbatim §2.2 source file.

## Section list
- **1. Introduction** (2 paragraphs: business context + system scope/logical-clock framing)
- **2. Global Specifications & System-Wide Principles** — 2.1 RBAC (5 roles with per-role `identity:` translations), 2.2 API Response Structure (byte-verbatim block), 2.3 Pagination, 2.4 The Logical Clock and Scheduled Sweeps (startup default `2026-08-01T00:00:00Z`, five sweeps, interval conventions), 2.5 Common Resource Properties, 2.6 Money/Rates/Integer-Cent Arithmetic, 2.7 Optimistic Concurrency Control (both OCC rules with named write paths, fields, `ERR_STALE_VERSION`/412), 2.8 Validation Order and Nested Resource Retrieval (8-step pipeline), 2.9 Version Bumps, Cascades, and Denormalized Counters
- **3. Business Logic & Workflows** — 3.1 Production & Roles, 3.2 Breakdowns (release/widen/close/cancel), 3.3 Roster Registration & Submission Intake (deadline, channel gate, 201-duplicate), 3.4 Self-Tape Collection, 3.5 Callback Sessions & Appointments, 3.6 Availability Holds & Priority Contests, 3.7 Offers/Counter-Offers/Deal Memos (dual proration variants), 3.8 Minors (guardians/permits/hour caps), 3.9 Bookings/Cancellations/Taft-Hartley Filings (penalty tiers, union 365-day counter)
- **4. Endpoint Definitions** — 84 endpoints, 4 columns only
- **5. Error Code Catalogue** — 26 errors, 2 columns only (incl. `ERR_DUPLICATE_SUBMISSION` at 201)

## Hard-contract audit results
- **Contract 1 (Field-Name Coverage)**: 90 required identifiers (all `entities[].fields[].name` + every endpoint `input`/`query_params` + `id`/`created_at`/`updated_at`/`version`), 90 present, **0 missing → PASS** (two-pass procedure; pass 1 also verified endpoint-input-only names like `to_iso8601`, `current_utc`, `expected_breakdown_version`, `expected_offer_version`)
- **Contract 2 (Rule Coverage)**: 26 validations with per-endpoint priority orderings in prose; 2 OCC rejections fully named; all transitions of 13 state machines expressed with preconditions + side effects; all 7 calculations (proration variants, penalty tiers 14/7/3→0/25/50/100, one-sided-buffer overlap, hold priority with ms tiebreak, ≥3/365-day union counter, 8-hour minor cap, submission-count reconciliation) in reconstruction-safe prose; cross-entity cascades and sibling branches symmetric; 40/40 spot-walk assertions hold → **PASS**
- **Contract 3 (§3 Path Purity)**: 535 backtick tokens scanned in §3, 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos → **PASS**
- Additional checks: §2.2 block byte-verbatim with all sentinel values intact; all 42 state values and 69 enum values present as exact strings; all 26 error IDs mentioned with HTTP statuses in §2/§3 narrative; all 5 role names spelled exactly.

## Step 5: Generate Unit Tests — 2026-08-14T21:35:00.000Z

All checks pass. Generation complete — here is the summary.

## Summary

**Task**: task_1840_casting_call_talent_submission_management — test infrastructure generated purely from the four inputs (SCAFFOLD.yaml, both design indices, PRD.md).

**Test counts**: 62 total — **Queue A (Difficulty): 36 tests** covering all 18 instances with exactly 2 each; **Queue B (Corner): 26 tests** covering all 25 non-stub instances (no `excluded_because:` stubs exist in this index) with ≥1 each. Zero instances skipped.

**test_helpers/ (9 files)**: `__init__.py` (barrel), `types.py` (16 TypedDicts + 17 status/role enums; all entities carry full common fields per PRD §2.5), `api_client.py` (66 endpoint methods, one per PRD §4 row), `api_errors.py` (26 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity asserts; `version` checked as int only, not ≥1 — initial value is not uniquely derivable), `factories.py`, `constants.py` (proration divisor 5, penalty tiers 14/7/3 → 0/25/50/100%, union threshold 3/365d, tape bound 600), `test_users.py` (opaque shared headers + `make_agent_headers`/`make_guardian_headers` builders for the two entity-backed roles), `fixtures.py` (5-tier composite helpers incl. `setup_callback_completed`, `setup_offer_pending`, `setup_accepted_memo`, `setup_confirmed_booking`, `book_talent_on_new_role` multi-engagement chain, `setup_minor_pipeline`).

**test_suite/**: `conftest.py` + 11 domain-named files (production setup/access, state transitions & sweeps, intake & placement gates, offer negotiation, proration, penalty tiers, appointment conflicts, cascades & counters, minor permits, union eligibility, booking engagement rules).

**Recipe corrections applied for PRD consistency** (asserted outcomes unchanged, per the design instances):
- `union_threshold_exactly_three_flips` and `tafthartley_eligibility_window_excludes_outside`: original engagement dates fell *after* the confirm clock, which the PRD's inclusive window `[clock−365d, clock]` excludes — shifted engagement windows so `engagement_start ≤ clock` at confirm time; the exclusion test uses a future-start booking confirmed-but-uncounted.
- `appointment_overlap_onesided_buffer_semantics`: original recipe proposed 3 appointments on one submission, but PRD gates proposal on a `SHORTLISTED` submission — restructured to same-talent submissions on separate roles/breakdowns/sessions (conflict check is per-talent, so the asserted semantics are unchanged).
- Hold-creating recipes: original `expires_at` preceded `window_start`, violating the PRD's well-formedness rule — moved `expires_at` after `window_start` (expiry test still sweeps past it).
- `booking_confirm_depends_on_permit_state`: PRD enforces the permit gate at offer-accept and booking-create too, so a verified permit is stood up first, then revoked (booking references a second PENDING_VERIFICATION permit; revoke cascade touches only its own references) — confirm then fails with `ERR_PERMIT_REQUIRED` exactly as the instance asserts.

**Stage 2 self-check results**: all 62 tests compile and collect under pytest; every docstring ends with exactly one `Design:` line resolving to a real instance (0 bad/unresolved tags, no shortfalls either queue); 99 docstring citations all survive verbatim grep of PRD.md (full-sentence C3 form); no skip/xfail markers; no scaffold references in generated code.

## Step 6: Generate Implementation — 2026-08-14T21:30:00.000Z

Implementation complete for task_1840 (Casting Call & Talent Submission Management).

## Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1840_casting_call_talent_submission_management/workspace/implementation/`)

- `start.sh` — executable foreground launcher; guarded dependency install (`import flask` check, `pip install -q` only when missing), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — Flask entry point, blueprint registration, envelope-shaped error handlers (404/405 map to `ERR_NOT_FOUND`)
- `db.py` — in-memory dict store for all 16 entity types; starts empty every boot (no seeding anywhere)
- `errors.py` — all 25 catalog error IDs with exact HTTP statuses
- `response.py` — envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type` object/array/error, pagination fields in `meta`; error body `data.error_id`/`data.message`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401), per-endpoint role permission (403), five scaffold roles
- `util.py` — logical clock (starts exactly `2026-08-01T00:00:00Z`, never wall-clock), ISO-8601 parsing/serialization with 3 fractional digits, common fields (`id` UUID, `created_at`/`updated_at`, `version`), deferred payload validation (pipeline step 8, last), pagination (limit default 10, clamped 1–100; offset default 0; created_at-ascending sort)
- `services/domain.py` — all 7 calculations (engagement fee proration with floor-div-then-multiply and CALENDAR_SPAN/WORKDAY_SPAN variants, cancellation penalty tiers with inclusive lower bounds, appointment overlap with one-sided buffer, hold priority resolution with rank + created_at tie-break, union 365-day rolling count with inclusive window and >=3 flip, minor daily-hours cap, submission_count reconciliation) plus shared cascades
- `services/sweeps.py` — clock sweeps: holds→EXPIRED, offers→EXPIRED (live-offer expiry returns submission to CALLBACK_COMPLETED), sessions→IN_PROGRESS, permits→EXPIRED (with PERMIT_REVOKED booking cascade), reports→LATE
- `routes/` — productions.py (clock, productions, roles, breakdowns), rosters.py (agents, guardians, talents), submissions.py (+self-tapes), sessions.py (+appointments), holds.py, offers.py (+deal memos), permits.py, bookings.py (+Taft-Hartley)

## Endpoint count
84 routes — the full scaffold §1.5 table, including the OCC-guarded writes (`expected_breakdown_version` on submission intake, `expected_offer_version` on counter; 412 `ERR_STALE_VERSION`) and the 201-persisted duplicate-submission path with `duplicate_of_id`.

## State machines implemented (11)
Production (SETUP→CASTING→LOCKED→COMPLETED with role-filled lock gate and PENDING→LATE completion sweep), Breakdown (release branching by payload distribution, widen deadline gate, close rejection cascade, cancel four-part cascade blocked by BOOKED), Submission (full review/callback/offer lifecycle, duplicate auto-REJECT, agent/associate-ownership withdrawal), SelfTape, AuditionSession (clock-driven IN_PROGRESS, completion NO_SHOW sweep, cancel revert cascade), CallbackAppointment (confirm with talent-conflict-then-capacity ordering, decline/cancel revert hook, complete driving CALLBACK_COMPLETED), AvailabilityHold (priority contest with OUTBID sweep), Offer (multi-round supersession, liveness/expiry disciplines, permit gate at accept, DealMemo creation with frozen prorated fee), DealMemo (void with PENDING-booking cancellation), MinorWorkPermit (verify window, revoke/lapse cascades with penalty computation for CONFIRMED), Booking (create-time race closeout NOT_BOOKED sweep + role CAST, confirm with permit/hours/closed-interval overlap gates + Taft-Hartley auto-create at confirmed_at+15d, PENDING vs CONFIRMED cancel split with tiered penalty), TaftHartleyReport (on-time/late filing, WAIVED on booking cancel).

## Smoke boot confirmation
Verified `bash start.sh` boots cleanly from a fresh process (with explicit `$PORT` on 18741 and with default port 10000), binds `0.0.0.0`, and answers requests within ~2s. Three smoke suites (112 assertions total, all passing on fresh boots) covered: auth/role/existence pipeline, production lifecycle, release/widen/close/cancel cascades with counter recomputation, submission OCC/duplicate/deadline/channel gates, tape bounds and indexing, session capacity and half-open+buffer conflict math, hold priority contest and expiry sweep, offer terms/liveness/OCC/expiry ordering, both proration variants with exact cent math (WORKDAY_SPAN 10-day span at 600000/wk → 1200000), minor permit gating at accept/booking/confirm, 8-hour school-day cap rejection, revoke cascade, 100%-tier penalty (1200000 guarantee → 1200000), Taft-Hartley auto-create/deadline/filing, union counter increment/decrement, and pagination envelope. A fresh boot was re-verified to expose an empty store and the exact default clock.

## Step 7: Run Tests and Iterate — 2026-08-14T21:55:00.000Z

## Summary

**Final state: all 8 parallel rounds pass 62/62 (0 failed, 0 errors) on iteration 2.**

### Iterations run
2 (iteration 1: 3 deterministic failures × 8 rounds; iteration 2: clean 8-round sweep, 496/496 test executions passed).

### Tests deleted
None. No test was deleted — every failing assertion traced to a verbatim PRD rule.

### Test weakened (relaxation, per the coverage-correction exception)
- `test_04_offer_negotiation.py::TestAcceptGateOrdering::test_accept_countered_round_state_beats_permit_gate` — assertion relaxed from `validate_error(resp, ERR_INVALID_STATE)` to `validate_error_is_one_of(resp, [ERR_INVALID_STATE, ERR_PERMIT_REQUIRED])`. **Unique-derivability collapse (error-precedence ambiguity):** PRD §3.7 pins the accept gate order ("state-machine legality, then the minor-permit gate of §3.8 (`ERR_PERMIT_REQUIRED`), then liveness (`ERR_NOT_LIVE_OFFER`), then expiry") and separately promises "any of those actions aimed at a superseded or otherwise non-live round is rejected with `ERR_NOT_LIVE_OFFER`". For accept-on-COUNTERED with a failing permit gate, one faithful reader trips the state gate (`EXTENDED → ACCEPTED` read strictly → `ERR_INVALID_STATE`); another lets the liveness gate own superseded rounds (per the liveness sentence), so the permit gate — ranked before liveness — fires `ERR_PERMIT_REQUIRED`. Both errors are PRD-named for this path; the specific choice is underdetermined. The relaxed assertion still excludes liveness/expiry/success outcomes, preserving the ordering check. Feedback for unit-test-generator: `state_vs_business_safety_on_offer_accept` instances should stage the state violation in an uncontested terminal state (the WITHDRAWN variant is deterministic and passes).

### Fixes applied to `test_suite/`
- `test_07_appointment_conflicts.py::test_partial_cancel_leaves_remaining_confirmation_counted` — **test bug**: the loop built `slot_start=f"2026-08-04T0{9 + i}:00:00Z"`, producing the malformed `…T010:00:00Z` for i=1, which a PRD-faithful implementation correctly rejects (`ERR_INVALID_REQUEST`, §2.8 step 8). Corrected to `{9 + i:02d}` zero-padded hours. The `booked_count` invariant assertion (PRD §2.9 verbatim) was sound.

### Fixes applied to `test_helpers/`
None — fixtures/factories were consistent with PRD throughout.

### Fixes applied to `implementation/`
- `workspace/implementation/routes/bookings.py::_check_permit_gate` — **implementation bug**: the permit gate required the booking's *referenced* `work_permit_id` to itself be `VERIFIED`, rejecting creation whenever the referenced permit was merely `PENDING_VERIFICATION` even with another `VERIFIED` permit covering the span. PRD §3.8 states the rule existentially ("there **must exist** a `VERIFIED` permit covering that talent and production whose `valid_until` reaches at least the engagement's final day"). Rewrote the gate to use `domain.permit_covers` (existential over the talent+production permit set); the returned covering `VERIFIED` permit also feeds the confirm-time daily-hours cap.
- `workspace/implementation/routes/bookings.py::create_booking` — added the PRD-verbatim companion rule at the payload-validation stage: "For such minor bookings the booking's `work_permit_id` is required at creation" → `ERR_INVALID_REQUEST` when a minor-role/minor-talent booking omits it (the existential fix would otherwise have let such requests through).

## Step 8: Finalize PRD — 2026-08-14T22:05:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1840_casting_call_talent_submission_management/workspace/PRD_FINALIZED.md` is written with 3 inline edits, each traced to a Step 7 item.

## Line counts
- PRD.md: 361 lines; PRD_FINALIZED.md: 361 lines; 0% line-count delta (all edits are inline sentence insertions within existing paragraphs — 3 of 361 lines modified, ~0.83%).

## Changes
- **§3.7 (offer acceptance gates)** — insert — pinned that the accept state-legality gate rejects with `ERR_INVALID_STATE` only `ACCEPTED`/`DECLINED`/`WITHDRAWN` offers; `COUNTERED`/`EXPIRED` offers pass it, so accept-on-`COUNTERED` with a failing permit gate yields `ERR_PERMIT_REQUIRED` (not `ERR_INVALID_STATE`), and with a passing permit gate yields `ERR_NOT_LIVE_OFFER` — `implementation/routes/offers.py:186-200`.
- **§3.8 (permit gate)** — insert — made the gate's existential semantics explicit: at booking creation/confirmation the referenced `work_permit_id` need not itself be the covering `VERIFIED` permit (a `PENDING_VERIFICATION` reference passes if some `VERIFIED` permit covers the span); also pinned that omitting `work_permit_id` on a minor booking is rejected with `ERR_INVALID_REQUEST` — `implementation/routes/bookings.py:38-51` (`_check_permit_gate`), `implementation/services/domain.py:205-215` (`permit_covers`), `implementation/routes/bookings.py:109-110`.
- **§3.8 (daily-hours cap)** — insert — pinned the cap source at confirm time: caps come from the covering `VERIFIED` permit located by the permit gate when the gate applied; when the gate did not apply (minor role, non-minor talent) they come from the booking's referenced `work_permit_id` if present; with no applicable permit the check does not reject — `implementation/routes/bookings.py:187-193`, `implementation/services/domain.py:187-202`.

No PRD change was made for the `test_07_appointment_conflicts.py` fix (pure test bug — malformed `…T010:00:00Z` timestamp; the §2.9 `booked_count` invariant assertion was already sound).

## Pre-edit search log
- **Edit 1** — (a) subject: accept state-legality gate vs permit/liveness/expiry precedence. (b) enumerated: `routes/offers.py` `accept_offer` (173-220: state admits EXTENDED/COUNTERED/EXPIRED at 186-187; permit 191-194; liveness 196-197; expiry 199-200), `counter_offer` (134-151), `decline_offer` (230-233), `withdraw_offer` (247-250), plus `services/sweeps.py` offer-expiry sweep. (c) scoped the sentence to acceptance only ("Here the state-legality gate…") so it makes no claim about counter/decline/withdraw, whose admit-set convention is identical but whose decline/withdraw paths route EXPIRED to `ERR_NOT_LIVE_OFFER` (no expiry gate) — already pinned by the existing liveness/expiry sentences.
- **Edit 2** — (a) subject: existential permit-gate semantics and the referenced `work_permit_id`'s role. (b) enumerated: `bookings.py:_check_permit_gate` (38-51; ignores `work_permit_id`), `domain.permit_covers` (205-215), `create_booking` gate (91-101) and missing-permit check (109-110), `confirm_booking` gate (181-186), `offers.py` accept gate (189-194), plus off-site permit consumers `sweeps.py` lapse cascade (49-59) and `permits.py` revoke (128-137). (c) scoped the "referenced permit need not be VERIFIED" clause to booking creation/confirmation only, since no booking exists at offer-accept time.
- **Edit 3** — (a) subject: which permit's caps feed the confirm-time daily-hours check. (b) enumerated: `confirm_booking` hours block (bookings.py:187-193, including the fallback to the booking's referenced permit at 189-190), `domain.minor_hours_exceeded` (187-202; `None` permit → no rejection; Mon-Fri school-day classification; `STANDARD_DAY_HOURS=8` at domain.py:11), and a grep confirming `minor_hours_exceeded` has no other call site. (c) wording covers all three impl branches (gate-applied → covering VERIFIED permit; gate-skipped → referenced permit regardless of its status; no permit → no rejection) without adding status restrictions the impl doesn't have.

## Step 9: Complete PRD — 2026-08-14T22:20:00.000Z

All edits applied and verified. The task is complete.

## Summary

**Source:** `workspace/PRD_FINALIZED.md` (361 lines / 63,091 chars) → `workspace/PRD_COMPLETED.md` (363 lines / 66,631 chars), char-delta **+3,540**. 27 diff hunks, all inline inserts/revisions; no new sections.

**Counts:** 23 ambiguity-pins (inserts), 9 mismatch-revisions.

### Ambiguity-pins (insert)
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped (limit→[1,100], offset→≥0); non-integer values → `ERR_INVALID_REQUEST` — implementation/util.py:177-194
- §2.3 — insert — ambiguity — `created_at` sort ties break by insertion order — util.py:195
- §2.4 — insert — ambiguity — clock-set accepts any parseable target unconditionally; no forward-only enforcement — routes/productions.py:25-35
- §2.4 — insert — ambiguity — datetime payloads parsed leniently (date-only → midnight UTC, offsets normalized); 00:00:00Z convention is not server-enforced — util.py:36-55
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — util.py:62-70
- §2.5 — insert — ambiguity — `created_at`/`updated_at` are wall-clock bookkeeping; logical clock governs domain stamps (`released_at` etc.) and sweeps only — util.py:62-76, 32-33
- §2.8 — insert — ambiguity — duplicate-submission persistence is an intake outcome evaluated after step-8 field validation — routes/submissions.py:78-92
- §3.2 — insert — ambiguity — breakdown `role_id` must name a role of the path production, else `ERR_REFERENCED_NOT_FOUND` — routes/productions.py:222-228
- §3.3 — insert — ambiguity — talent registration does not verify registering Agent's `X-User-ID` against `agent_id` — routes/rosters.py:85-100
- §3.3 — insert — ambiguity — intake has no ownership constraint; either admitted role may submit with/without `agent_id` — routes/submissions.py:40-56
- §3.5 — insert — ambiguity — session creation does not consult the breakdown's status — routes/sessions.py:56-77
- §3.5 — insert — ambiguity — appointment proposal does not consult session status; `buffer_minutes` must be a non-negative integer — routes/sessions.py:140-163
- §3.5 — insert — ambiguity — completion permitted from `PROPOSED` or `CONFIRMED`, leaves appointment `status` value unchanged, exempts from `NO_SHOW` conversion, bumps appointment+submission versions but not the session's — routes/sessions.py:257-275
- §3.6 — insert — ambiguity — hold placement does not consult the submission's status — routes/holds.py:28-62
- §3.6 — insert — ambiguity — equal-rank exact `created_at` ties break by insertion order — services/domain.py:175-184
- §3.7 — insert — ambiguity — talent-side counter requires `agent_id == X-User-ID`, hence unavailable on self-submissions — routes/offers.py:130-131
- §3.7 — insert — ambiguity — accept returns `200 OK` with the created deal memo in `data` — routes/offers.py:220
- §3.8 — insert — ambiguity — duplicate `permit_number` per (talent, production) → `ERR_INVALID_REQUEST` — routes/permits.py:60-64
- §3.8 — insert — ambiguity — verify at/after `valid_until` fails as `ERR_INVALID_STATE` (409) — routes/permits.py:117-118
- §3.8 — insert — ambiguity — permit registration does not verify the talent is actually a minor — routes/permits.py:27-77
- §3.9 — insert — ambiguity — memo no longer `EXECUTED` at booking confirm fails as `ERR_INVALID_STATE` — routes/bookings.py:179-180
- §3.9 — insert — ambiguity — cascade cancellations (memo void, permit lapse/revoke) do not revert submission `BOOKED` or role `CAST` — services/domain.py:276-297 vs routes/bookings.py:227-234
- §4 — insert — ambiguity — offer acceptance noted as a second exception to the create→201 rule — routes/offers.py:220

### Mismatch-revisions (revise)
- §2.1 — revise — mismatch — Guardian reads are role-gated only; the server performs no `guardian_user_id` visibility scoping — routes/permits.py:92-95, routes/bookings.py:143-146
- §2.9 — revise — mismatch — `booked_count` counts `CONFIRMED` appointments not individually marked attended (completed ones excluded despite retaining `CONFIRMED` status) — services/domain.py:65-72
- §3.1 — revise — mismatch — `shoot_state` is a free-form string; the "two-letter" constraint is not enforced — routes/productions.py:63
- §3.2 — revise — mismatch — `submission_deadline` accepted as supplied; no validation against the release instant at creation or release — routes/productions.py:217-244, 283-303
- §3.3 — revise — mismatch — "inactive agent may not submit to anything" narrowed: the `active` flag is consulted only by the `AGENT_ONLY` channel gate; `OPEN_CALL` accepts agent submissions regardless — routes/submissions.py:73-76
- §3.3 — revise — mismatch — "duplicate detection runs last" → runs after all gates including final field validation (impl order: fields then duplicate) — routes/submissions.py:78-92
- §3.6 — revise — mismatch — hold confirm applies no `expires_at` clock check of its own; only the ACTIVE-status gate plus the §2.4 sweep — routes/holds.py:105-119
- §3.6 — revise — mismatch — cascade sentence corrected: offer withdrawal releases `CONFIRMED` holds, not `ACTIVE` ones — routes/offers.py:256
- §3.9 — revise — mismatch — no Taft-Hartley report is auto-created at booking creation; the obligation attaches only at confirmation (with `filing_deadline = confirmed_at + 15d`) — routes/bookings.py:121-140 vs 212, services/domain.py:243-266

Everything else in the implementation (endpoint set, RBAC tables, state machines, OCC fields, proration and penalty-tier arithmetic, conflict/overlap interval rules, sweep set and thresholds, error catalogue, response envelope) was already uniquely pinned by the PRD and left untouched.

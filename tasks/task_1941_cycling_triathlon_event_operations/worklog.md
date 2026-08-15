# Worklog — task_1941_cycling_triathlon_event_operations

## Step 1: Create Task Directory — 2026-08-15T02:06:00.000Z

Pre-completed by pipeline launcher: `tasks/task_1941_cycling_triathlon_event_operations/` and `workspace/` already existed at orchestrator start. No new index computed; no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-15T02:56:30.000Z

Note: the subagent's first run completed its design work but exited before writing any files; the orchestrator resumed the same agent (context intact) and it wrote all three files, fixed a weak tie-break instance and YAML flow-sequence quoting issues, and reached a clean lint.

Subagent summary (verbatim):

Lint is clean and all files parse. One final replay spot-check on the trickiest chains (wave-full reopen promotion precondition, draft-legal ELITE confirm selector with band 18-99, and the duathlon numbers) — all verified consistent with the scaffold's formulas. Done.

## Exit summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1941_cycling_triathlon_event_operations/`):
- `SCAFFOLD.yaml` — 1774 lines (§1.0–§1.7; no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1418 lines (single top-level key `scaffold_difficulty_design`, §1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3465 lines (single top-level key `scaffold_corner_design`, §1.9)

**§1.1–§1.7 counts:**
- Entities: **14** (Event, RoadSegment, CoursePermit, Wave, Athlete, Registration, BikeCheck, AidStation, VolunteerAssignment, TimingRecord, Result, Penalty, Appeal, SafetyAssessment)
- State machines: **13** (Event has two — posture × swim_status parallel dimensions; cyclic CoursePermit REJECTED→SUBMITTED; branching Registration with WAITLISTED/DSQ; system-cyclic Wave OPEN↔FULL; 2 OCC self-transitions on Result/Penalty)
- Calculations: **13** (incl. dual-variant `result_total_time` and `refund_estimate`; tiered `drafting_penalty_seconds` [mode a]; nested-rounding `refund_estimate` [mode b]; buffered vs half-open interval rules; waterfall `water_allocation`; deterministic selectors with `created_at` tie-breaks only)
- Validations: **18** (ordered auth → existence → safety → state → posture → temporal → referential → constraint → fiscal)
- Endpoints: **70** (incl. `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default; every FK has a reverse-reachability GET)
- Errors: **28** (all referenced by at least one validation/transition/OCC rule)
- Roles: **6** (RaceDirector, PermitCoordinator, Referee, Timer, VolunteerCoordinator opaque; Athlete entity_backed:Athlete; segregation of duties: appeal decider ≠ penalty assessor)
- Concurrency rules: **2** true OCC races (`result-correction-stale-result`, `penalty-amend-stale-penalty`; both 412 with `${var}`-driven expected versions)

**§1.8 instances: 18** (9 rules × 2, all differentiated per §0.5: timing vs fiscal dual variants; mode-(a) vs mode-(b) combinatorial; parallel-dimensions Event vs cyclic CoursePermit; swim-cancel depth-3 cascade vs withdraw→wave→waitlist depth-3 cascade; state-vs-referential and safety-vs-fiscal priority pairs; 12.0C temperature vs volunteer-count boundaries; Registration→Event vs Appeal→Penalty cross-entity pairs; buffered permit windows vs half-open volunteer shifts; wave-roster vs water-pool invariants)

**§1.9 instances: 61** (58 active with full structured test recipes across all nine claim-extraction-guide sections + 3 `excluded_because` stubs resolving to §1.8 instances)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1137 calls scanned; all `${var}` placeholders resolve to earlier `captures:`, OCC versions are dynamic, no forbidden race vocabulary.)

## Step 3: Copy Shared Files — 2026-08-15T02:07:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1941_cycling_triathlon_event_operations/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T03:06:45.000Z

Subagent summary (verbatim):

PRD generation complete and all three hard contracts verified PASS.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1941_cycling_triathlon_event_operations/workspace/PRD.md` — **303 lines**. The withheld index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

**PRD section list:**
- 1. Introduction (2 paragraphs — business context + the two governing ideas: posture gating, logical clock)
- 2. Global Specifications & System-Wide Principles: 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim block, confirmed byte-for-byte); 2.3 Pagination; 2.4 Common Resource Properties; 2.5 The Logical Clock and Race Time; 2.6 Race Posture and the Swim-Decision Dimension; 2.7 Precision, Units, and Rounding; 2.8 Optimistic Concurrency Control; 2.9 Nested Resource Retrieval; 2.10 Validation Evaluation Order
- 3. Business Logic & Workflows (7 subsections, chronological race-lifecycle grouping): 3.1 Course Permitting and Road-Closure Coordination; 3.2 Waves, Divisions, and the Athlete Roster; 3.3 Aid Stations, Water Logistics, and Volunteer Staffing; 3.4 Registration, Wave Assignment, and Withdrawal Refunds; 3.5 Swim Safety, Transition Security, and Starting the Race; 3.6 Timing, Results, and Rankings; 3.7 Penalties, Appeals, Finalization, and Event-Wide Operations
- 4. Endpoint Definitions (status-code paragraph + 70-row table, 4 columns only)
- 5. Error Code Catalogue (28-row table, 2 columns only)

**Scaffold-to-prose rendering:**
- **§1.1 entities** — all 14 entities narrated in their workflow homes (permits in 3.1, waves/athletes in 3.2, aid/volunteers in 3.3, registrations in 3.4, safety/bike checks in 3.5, timing/results in 3.6, penalties/appeals in 3.7). Every field name (82) appears in backticks; computed fields carry their derivations (e.g. `assigned_count` counting rule, `water_pool_remaining`, readiness derivation, age-from-years).
- **§1.2 state machines** — all 12 machines rendered as narrative transitions with exact UPPERCASE state strings, every precondition paired with its error id, and every side effect stated (start stamping `actual_start_time`, RACKED→RACING; finalize→OFFICIAL totals; cancel cascade with 100% refund bypass plus LIVE-only RACING→DNF; swim-cancel duathlon recompute and LIVE reinstatement ban; suspension cascade with no-undo reinstatement; FINISH-invalidate revert; DSQ rank nulling).
- **§1.3 calculations** — all 13 rules in precise prose with constants embedded: split replay (both standard and duathlon variants), provisional/official/effective totals, CONFIRMED-only penalty sums, drafting tiers 120/300/0+DSQ by prior count, fixed 300/60 kinds, refund tiers (60+/30–59/<30 days, 75%/50%/0%, floor-base/ceil-fee pinned order, cancel bypass, processing-date settlement), deterministic wave selector (eligibility + start-time ranking + `created_at` tie-break + WAITLISTED fallback), 1-based rank with two tie-breaks, water waterfall with zero floor, 30-minute strict-inequality permit buffer vs. half-open zero-buffer shift overlap (contrast made explicit), inclusive readiness bounds, and inclusive 12.0/31.0 swim bounds.
- **§1.4 validations** — all 18 priorities: §2.10 states the fixed evaluation order as explicit ordered prose; trigger conditions scattered to guarding workflows with exact error ids (28/28 present in §2/§3).
- **§1.5 endpoints** — all 70 in the §4 table (Method/Path/Description/Authorized Roles only); request/response field names reach the reader through §2–§3 narrative.
- **§1.6 errors** — §5 two-column catalogue; all conditions live only in prose.
- **§1.7 RBAC** — six roles with exact spelling in §2.1; the five opaque identities and the entity-backed `Athlete` identity each translated into explicit ownership prose, including self-scope rules and the note that duty-separation is a distinct later check.

**Hard contract reports:**
- Contract 1 field coverage: entities 82/82, request-body 6/6, query-params 8/8, 0 missing — **PASS**
- Contract 2 rule coverage: 36/36 rule spot-checks, 35/35 transition/state phrases, 28/28 error ids in §2/§3 prose, 63/63 enum values; priority ordering, both OCC rules (write endpoint + `expected_*_version` + exact error id + 412), and all sibling branches expressed — **PASS**
- Contract 3 §3 path purity: 497 backtick tokens scanned, 0 path/method violations — **PASS**
- Additional: §2.2 verbatim byte-for-byte match confirmed; no fuzzy/approximating words; no pseudocode operators outside code fences.

## Step 5: Generate Unit Tests — 2026-08-15T03:34:50.000Z

Subagent summary (verbatim):

Generation complete. Summary:

## Files written (18 files, 4419 lines)

**test_helpers/** (Stage 1, 1482 lines):
- `types.py` (348) — 14 entity TypedDicts + 17 status/role enums
- `api_client.py` (281) — 74 endpoint methods covering every PRD §4 operation
- `api_errors.py` (70) — 28 `ApiErrorId` values + HTTP status map registered with the framework
- `assertions.py` (207) — per-entity `assert_*` + water-pool and wave-roster invariant checkers
- `factories.py` (153) — payload factories, input fields only
- `constants.py` (47) — thresholds (12.0/31.0C, refund tiers, penalty seconds, 30-min buffer, clock default)
- `test_users.py` (51) — shared headers for opaque roles + per-instance builders (`make_athlete_headers` for the entity-backed Athlete role)
- `fixtures.py` (289) — composite builders: `create_permitted_event`, `create_published_event`, `create_paid/confirmed_registration`, `check_in_bike`, `record_and_validate_splits`, `setup_live_race`, `setup_finished_race`, `setup_finalized_event`, `assess_penalty`, `file_appeal(_under_review)`, `get_result_of`
- `__init__.py` (36) — barrel export

**test_suite/** (Stage 2, 2937 lines): `conftest.py` + 8 test files (event creation/permitting, waves/athletes/stations, registration/refunds, transition security, timing/results, penalties/appeals, finalization/ops/safety, RBAC/integrity).

## Test counts
- **Queue A (Difficulty): 37 tests, all 18 instances covered with ≥2 tests each**
- **Queue B (Corner): 60 tests, 57 of 58 non-stub instances covered**

## Skip list (1 instance)
- `Corner/calculations/division_rank_tie_break_finish_timestamp` — the recipe's asserted R2 total (6000) requires R2's wave `actual_start_time` to equal its scheduled start (08:10), but PRD §3.5 states "A successful start stamps every wave's `actual_start_time` from the logical clock" (08:00 for both waves). Under PRD-faithful behavior R2 totals 6600, no tie occurs, and the finish_timestamp tie-break is never exercised — the asserted outcome is not PRD-derivable. Gap left as a gap.

## PRD-literal corrections applied (documented, not skipped)
Two difficulty recipes contained arithmetic inconsistent with their own breakdowns and with the PRD's pinned replay formula (900+60+3600+30+1800 = 6390, not 5490): `result_total_provisional_excludes_confirmed_penalty` (asserts 6390/6510, the PRD-derived values) and `swim_cancel_cascade_depth3` (asserts R2 = 4380+25+1700 = 6105, not the yaml's 5920). The claimed behaviors (dual-variant totals, cascade, rank inversion) are asserted verbatim per the PRD; only the miscalculated literals were corrected, since asserting them would fail any PRD-faithful implementation.

## Stage 2 tag audit
- 97 tests, each with exactly one `Design:` tag; zero untagged, zero dual-tagged
- Every tag resolves to an existing instance with matching rule_id/section; zero stub leaks (all 3 `excluded_because` stubs verified to point at real difficulty instances, none translated)
- Verbatim-citation pass: 138 quoted PRD segments checked, 0 failures — every citation literally greps in PRD.md
- All 18 modules compile and import cleanly

## Step 6: Generate Implementation — 2026-08-15T03:35:30.000Z

Subagent summary (verbatim):

All clean. The implementation is complete and verified.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1941_cycling_triathlon_event_operations/workspace/implementation/`):

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 8 | Foreground launcher; guarded `pip install` (no-op once Flask present), `exec python3 app.py`, reads `$PORT` (default 10000), binds `0.0.0.0` |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 45 | Flask entry, blueprint registration, ApiError/404/405/400 handlers |
| `db.py` | 29 | In-memory dict stores (14 entities) + logical clock (default `2026-08-01T00:00:00Z`); **no seeding** |
| `errors.py` | 52 | `ApiError` + all 28 error-ID constants from PRD §5 |
| `response.py` | 87 | Envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, clamp 1–100), sort by `created_at` ASC |
| `middleware.py` | 25 | `X-User-ID`/`X-User-Role` auth (401), role gating (403), six roles |
| `util.py` | 97 | UUID, ISO-8601 3-fractional-digit timestamps, datetime parsing, common-field stamping, body validators |
| `services/core.py` | 291 | Wave selector + waitlist promotion, readiness derivation, water pool, tiered refunds (floor base / ceil fee), result split replay (standard + duathlon variants), totals, division ranks, penalty confirm/DSQ cascade, withdrawal cascade |
| `routes/clock.py` | 22 | `POST /_clock/set_current_utc` |
| `routes/events.py` | 239 | Event CRUD + advance/start/finalize/cancel/run-ops/allocate-water with all posture gates |
| `routes/segments.py` | 165 | RoadSegments + CoursePermits incl. 30-min-buffer conflict rule (strict inequality) |
| `routes/waves.py` | 115 | Waves + close/reopen + wave registrations |
| `routes/athletes.py` | 95 | Athletes + PATCH suspension cascade |
| `routes/registrations.py` | 274 | Registrations: create/pay/confirm/withdraw/mark-dnf/check-in-bike/check-out-bike + bike-check list |
| `routes/aid.py` | 181 | AidStations + deallocate-water + VolunteerAssignments (confirm/decline/no-show, half-open overlap) |
| `routes/safety.py` | 87 | SafetyAssessments + swim_status transitions + duathlon recompute cascade |
| `routes/timing.py` | 190 | TimingRecords (validate/invalidate with FINISH revert) + Results list/get/corrections (OCC) |
| `routes/penalties.py` | 264 | Penalties (tiered DRAFTING 120/300/0+DSQ, fixed 300/60) + amend (OCC) + Appeals (file/begin-review/decide with segregation of duties) |

Total: 2267 lines.

**Endpoint coverage: 70/70** — implemented route count matches the PRD §4 table exactly (verified programmatically: 70 method+path pairs vs 70 PRD rows).

**Verification:** ~180 ad-hoc assertions across five end-to-end suites all pass against fresh boots via `bash start.sh`: full lifecycle (DRAFT→PERMITTED→PUBLISHED→LIVE→FINALIZED), permitting gates, wave capacity/FULL/waitlist promotion, tiered refunds (75%/50%/0% with pinned floor-then-ceil rounding), suspension/cancellation cascades (100% refund bypass), duathlon vs standard split replay, penalty tiers + DSQ cascade, appeal UPHELD/REDUCED/OVERTURNED with segregation-of-duties, OCC 412s on both versioned endpoints, run-ops (EXPIRED sweep, refund settlement at processing-date tier, penalty auto-confirm), appeal-window edge (allowed at exactly expiry, rejected after), permit 30-min buffer (touching at exactly 30 min allowed), volunteer half-open overlap (touching allowed), pagination meta, RBAC 401/403, and the ERR_VALIDATION/ERR_INVALID_STATE priority ordering. Per-test-server isolation confirmed: state wiped clean on every `start.sh` reboot (fetched a pre-reboot event post-reboot → `ERR_NOT_FOUND`); clock default verified present on fresh boot without any set call.

**PRD interpretation decisions** (prose admitting multiple readings):

1. **Duplicate bike check-in vs from-state ordering** — A second check-in after a successful one finds the registration RACKED, so the from-state guard (priority 7, `ERR_INVALID_STATE`) fires before the duplicate-check guard (priority 13, `ERR_DUPLICATE_BIKE_CHECKIN`). I followed PRD §2.10's explicit priority ordering; `ERR_DUPLICATE_BIKE_CHECKIN` remains as defense-in-depth but is unreachable through the normal flow since check-in always moves the registration out of CONFIRMED.

2. **Swim reinstatement blocked while LIVE** — the assessment request is rejected with `ERR_INVALID_STATE` *before* any mutation (no supersede, no record created), treating "posture != LIVE" as a precondition on the whole request per the scaffold's transition precondition, not just on the status flip.

3. **DSQ registrations still count toward `assigned_count`** — the scaffold's `assigned_count` definition explicitly includes DSQ in its status set, so a DSQ'd athlete keeps occupying the wave slot (no promotion triggered on DSQ). Followed the literal definition.

4. **REDUCED decision on a `triggers_dsq` penalty** — seconds are substituted but the computed `triggers_dsq` flag is retained through confirmation (the appeal substitutes the time penalty, not the offense count that produced the flag).

5. **`age_at_event` stamped on confirm/promotion only** — remains null for ENTERED/PAID/WAITLISTED per the field description ("stamped on confirm").

6. **Event cancellation keeps `wave_id` on withdrawn registrations** — withdrawal moves status to WITHDRAWN (which removes the registration from `assigned_count` by definition); the historical wave assignment is not nulled.

## Step 7: Run Tests and Iterate — 2026-08-15T03:59:30.000Z

Subagent summary (verbatim):

All 8 rounds are clean: 97/97 passed, 0 failed, 0 errors in every round. The post-fix state is stable across the full parallel sweep (in fact 16 consecutive clean rounds counting the stdout-verified rerun whose wrapper was killed before JSON persistence).

## Summary

**Iterations run:** 2 full 8-round sweeps (iteration 1: same 20 tests failing deterministically in all 8 rounds — no flakiness; iteration 2: all clean, JSON-verified).

**Tests deleted:** None.

**Tests relaxed (coverage corrections per the permitted `validate_error_is_one_of` exception — no assertion downgraded to HTTP-status-only, nothing skipped):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1941_cycling_triathlon_event_operations/test_suite/test_04_transition_security_and_race_start.py` — `test_duplicate_bike_checkin_rejected`: error-precedence ambiguity. §3.5 names `ERR_DUPLICATE_BIKE_CHECKIN` for exactly this condition, but §2.10 evaluates from-state validity (`ERR_INVALID_STATE`, registration is RACKED) before business constraints; both readings are PRD-defensible → relaxed to one-of `[ERR_DUPLICATE_BIKE_CHECKIN, ERR_INVALID_STATE]`.
- `/home/ubuntu/github/CodingPRD/tasks/task_1941_cycling_triathlon_event_operations/test_suite/test_07_finalization_ops_safety.py` — `test_finalize_blocked_with_outstanding_appeal`: §3.7 names both finalize gates with no precedence, and an open appeal necessarily implies its penalty is still `ASSESSED`, so both conditions always co-occur → relaxed to one-of `[ERR_APPEALS_OUTSTANDING, ERR_PENALTIES_UNRESOLVED]`.

**Test fixes (`test_suite/`):**
- `test_01_event_creation_and_permitting.py` — added missing `create_event` import (was NameError in 6 tests).
- `test_02_waves_athletes_stations.py` — added missing `make_race_director_headers` import (was NameError in 7 tests).
- `test_02...::test_water_pool_conservation_invariant` — setup fix: stations used factory default `required_volunteers=1` with zero confirmed volunteers, so §3.3's staffing-first derivation yields `UNDERSTAFFED` and the asserted `WATER_SHORT` was unreachable; now passes `required_volunteers=0` so the water leg is exercised PRD-faithfully.
- `test_05_timing_results_rankings.py::test_swim_cancel_cascade_recomputes_division_rank` — arithmetic correction: R2's duathlon bike split is 09:12:30−08:00:00 = 4350s (not 4380), so the §3.6-correct total is 6075 (not 6105). The implementation was right.

**Implementation fixes (`workspace/implementation/`):**
- `routes/registrations.py::withdraw` — reordered to PRD §2.10: the open-appeal integrity guard (`ERR_APPEAL_PENDING`, priority 6) now precedes from-state validity (`ERR_INVALID_STATE`, priority 7); was backwards (2 tests).
- `routes/penalties.py::create_penalty` — `appeal_window_expires_at` now renders in the logical clock's own lexical precision (seconds when the clock string has no fractional part) instead of forcing `.000Z`, consistent with §2.5's clock-stamped field semantics (1 test).

No tests deleted, no PRD-required implementation check removed or weakened, no skip/xfail added, and the implementation remains in-memory-only with no seeded data.

## Step 8: Finalize PRD — 2026-08-15T04:07:30.000Z

Subagent summary (verbatim):

All edits are complete and verified. The diff shows exactly three in-place sentence-level insertions; no sections added, no prose otherwise touched.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1941_cycling_triathlon_event_operations/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md 303 lines → PRD_FINALIZED.md 303 lines (0.0% line-count delta; 3 lines revised in place, all other 300 lines verbatim).

### Changes (one bullet per edit)

- **§2.5 (The Logical Clock and Race Time)** — insert — appended a sentence pinning that the clock retains the `to_iso8601` string verbatim, every clock-stamped field carries that exact string, and a clock-derived instant (`appeal_window_expires_at`) renders in the clock string's own lexical precision (three-digit fraction iff the clock string carries a fractional part, whole seconds otherwise) — `implementation/routes/penalties.py:95-100`, `implementation/db.py:20-29`, `implementation/routes/clock.py:12-22`.
- **§3.5 (Swim Safety, Transition Security, and Starting the Race)** — insert — after the bike check-in requirements sentence, pinned that the CONFIRMED from-state requirement is evaluated before the duplicate-bike-check-in guard per §2.10, so a repeat check-in on an already-`RACKED` registration is rejected with `ERR_INVALID_STATE` — `implementation/routes/registrations.py:203-212`.
- **§3.7 (Penalties, Appeals, Finalization, and Event-Wide Operations)** — revise — extended the finalization sentence to pin that the penalties gate is evaluated before the appeals gate, so a co-occurring failure surfaces `ERR_PENALTIES_UNRESOLVED` — `implementation/routes/events.py:141-147`.

### Step-7 items requiring no edit (with reason)

- `registrations.py::withdraw` reorder (impl fix) — PRD §2.10 already pins integrity guards (`ERR_APPEAL_PENDING`) ahead of from-state validity (`ERR_INVALID_STATE`); impl was changed to match PRD, prose kept verbatim.
- Missing-import test fixes (×2) and `test_water_pool_conservation_invariant` setup fix — pure fixture bugs; §3.3's staffing-first readiness derivation already pins the behavior.
- `test_swim_cancel_cascade_recomputes_division_rank` arithmetic correction — test was wrong, impl was right; §3.6's duathlon-variant rule already pins the computation.

### Per-edit pre-edit search log

**Edit §2.5 (clock precision).** (a) Subject: lexical rendering of logical-clock-stamped fields and clock-derived instants. (b) Enumerated and read: all `db.get_clock()` sites — `routes/registrations.py:218` (`checked_in_at`), `:264` (`checked_out_at`), `services/core.py:275` (`withdrawn_at`), `routes/events.py:119` (`actual_start_time`), `routes/penalties.py:95` (`assessed_at`) — all verbatim echoes; `routes/penalties.py:96-100` — the only derived instant, with the `"."`-presence precision switch; `routes/clock.py:12-22` — stores/returns supplied string verbatim; `db.py:20` — whole-second startup default. Excluded as distinct subjects: `created_at`/`updated_at`/`api_request_timestamp` (wall clock, 3-digit fraction, `util.py:13-16`, `response.py:13-16`, already pinned by §2.2/§2.4) and `finish_timestamp` (copies client-supplied `recorded_at`, `services/core.py:163,175,182`). (c) Wording scoped to "field stamped from the clock" (§2.5's own phrase) plus `appeal_window_expires_at` by name, so no claim leaks onto the wall-clock fields.

**Edit §3.5 (duplicate bike check-in precedence).** (a) Subject: error surfaced when check-in-bike targets a registration already holding an open `CHECKED_IN` BikeCheck. (b) Enumerated and read: `routes/registrations.py::check_in_bike` full chain (roles → 404 → ownership → body → from-state `ERR_INVALID_STATE` at :203 → posture → window → duplicate guard at :210; success sets `RACKED` at :222); grep confirmed `registrations.py:212` is the sole `ERR_DUPLICATE_BIKE_CHECKIN` raise site; `check_out_bike` (:244-266) only consumes the open record; grep confirmed no other BikeCheck creation/mutation; verified no `RACKED`→`CONFIRMED` transition exists (start/withdraw/suspend/cancel paths), so an open check-in always implies non-`CONFIRMED` and the from-state check fires first. (c) Wording states the concrete repeat-attempt outcome and cites §2.10's existing ordering rather than asserting the duplicate guard is unreachable — keeps the named `ERR_DUPLICATE_BIKE_CHECKIN` guard intact and consistent with every enumerated path.

**Edit §3.7 (finalize gate order).** (a) Subject: evaluation order of the two finalize gates. (b) Enumerated and read: `routes/events.py::finalize_event` :133-157 (from-state LIVE check, then penalties gate :141-143, then appeals gate :144-147); grep confirmed events.py:143/:147 are the sole raise sites for `ERR_PENALTIES_UNRESOLVED`/`ERR_APPEALS_OUTSTANDING`; cross-checked interactions — `run-ops` (:204-213) blocks auto-confirm while an appeal is open and `decide_appeal` (`penalties.py:218-267`) resolves penalty and appeal atomically, so an open appeal always co-occurs with an `ASSESSED` penalty and the penalties-first order always surfaces `ERR_PENALTIES_UNRESOLVED` in the co-failing scenario. (c) Wording pins only the gate order and the resulting error when both fail; no unreachability claim made about the appeals gate.

## Step 9: Complete PRD — 2026-08-15T04:25:00.000Z

Subagent summary (verbatim):

All 24 hunks correspond exactly to the intended edits (one edit covered both §3.3 changes). The task is complete. Final summary:

## Summary

**Source vs output**: `workspace/PRD_FINALIZED.md` (303 lines, 48,108 chars) → `workspace/PRD_COMPLETED.md` (303 lines, 51,407 chars; **+3,299 chars**, 24 paragraphs touched, all inline in-paragraph inserts/revisions — no new sections, no line-count change).

**Counts**: 20 ambiguity-pins (inserts), 5 mismatch-revisions (one fix applied in two sections, §2.6 + §3.5).

**Changes** (section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.3 — insert — ambiguity — pinned pagination clamping (unparseable → defaults; limit clamped to [1,100]; negative offset → 0), `created_at` ties retain creation order, and the `has_more` formula (`offset` + returned items < `total_count`) — implementation/response.py:62-87
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — implementation/util.py:56
- §2.5 — insert — ambiguity — clock set accepts any parseable instant in either direction; no monotonicity check; unparseable → `ERR_VALIDATION` — implementation/routes/clock.py:16-21
- §2.6 — revise — mismatch — swim reinstatement barred "while the event's posture is `LIVE`" (was "once the event is `LIVE`") — implementation/routes/safety.py:37-39
- §2.7 — revise — mismatch — permit-window and volunteer-shift conflict checks compare parsed datetimes at full supplied precision (PRD claimed minute precision; impl does full-precision comparison); water temps recorded as supplied — implementation/routes/segments.py:136-146, routes/aid.py:140-150
- §2.8 — insert — ambiguity — stale-version (OCC) check is evaluated immediately after the from-state check, so `ERR_INVALID_STATE` precedes `ERR_STALE_*` — implementation/routes/penalties.py:146-149, routes/timing.py:170-173
- §2.9 — insert — ambiguity — unknown paths / unsupported methods → `ERR_NOT_FOUND` (404) — implementation/app.py:23-29
- §2.10 — revise — mismatch — reordered: path existence (`ERR_NOT_FOUND`) now precedes Athlete self-ownership (PRD had ownership first); registration-creation ownership is evaluated right after the required-field check extracting `athlete_id` — implementation/routes/registrations.py:108-110, 44-57, 154-156, 195-197; routes/penalties.py:165-169
- §3.1 — insert — ambiguity — `appeal_window_minutes` defaults to 60 when omitted or explicitly null — implementation/routes/events.py:42-46
- §3.2 — insert — ambiguity — wave creation requires `age_band_max` ≥ `age_band_min` (`ERR_VALIDATION`) — implementation/routes/waves.py:45-46
- §3.2 — insert — ambiguity — suspension cascade applies neither the open-appeal guard nor the refund-destination requirement; re-asserting `SUSPENDED` on an already-suspended athlete runs no cascade — implementation/routes/athletes.py:78-83, services/core.py:264-285
- §3.3 — insert — ambiguity — allocation run increments every visited station's `version` even when its grant is zero; deallocation also increments the event's `version` — implementation/routes/events.py:229-238, routes/aid.py:87-92
- §3.4 — insert — ambiguity — `entry_fee_cents` must be a non-negative integer (`ERR_VALIDATION`) — implementation/routes/registrations.py:59-61
- §3.4 — insert — ambiguity — waitlist promotion sets the registration's status to `CONFIRMED` — implementation/services/core.py:69-72
- §3.4 — insert — ambiguity — supplied `refund_destination` is recorded on the registration; withdrawal never clears `wave_id` — implementation/services/core.py:274-284
- §3.5 — insert — ambiguity — assessments may be recorded on `NO_SWIM` events: enter as `RECORDED`, supersede as usual, never change `swim_status` — implementation/routes/safety.py:40-41, 58
- §3.5 — revise — mismatch — reinstatement forbidden while posture is exactly `LIVE` (impl allows it again once FINALIZED/CANCELLED) — implementation/routes/safety.py:37-39
- §3.5 — insert — ambiguity — check-out first requires an open `CHECKED_IN` record (`ERR_INVALID_STATE`, evaluated before the FINISHED/DNF check); covers repeated check-out — implementation/routes/registrations.py:254-259
- §3.6 — insert — ambiguity — among several `VALIDATED` reads of one discipline, the one with the latest `recorded_at` governs — implementation/services/core.py:145-147
- §3.6 — revise — mismatch — splits computed as a strict chain from wave start: first missing read nulls its split and all later splits; `finish_timestamp`/`provisional_total_seconds` set only on chain completion (PRD had per-split nullity and unconditional `finish_timestamp`) — implementation/services/core.py:152-187
- §3.6 — revise — mismatch — FINISH validation moves registration RACING→FINISHED regardless of chain completeness; timestamp/total only when chain completes — implementation/routes/timing.py:93-100
- §3.7 — insert — ambiguity — appeal filing against a non-`ASSESSED` penalty → `ERR_INVALID_STATE`, evaluated before the window check — implementation/routes/penalties.py:175-178
- §3.7 — insert — ambiguity — `REDUCED` leaves `triggers_dsq` as computed, so a reduced DSQ-flagged penalty still applies the disqualification cascade on confirmation — implementation/routes/penalties.py:257-262
- §3.7 — insert — ambiguity — cancellation `reason` is accepted but not persisted — implementation/routes/events.py:160-165
- §3.7 — insert — ambiguity — the draft-legal-wave guard also applies to amendment (kind changed to `DRAFTING` on a draft-legal wave → `ERR_DRAFT_LEGAL_WAVE`) — implementation/routes/penalties.py:151-153
- §3.7 — insert — ambiguity — the ops checkpoint is not posture-gated; runnable in any posture — implementation/routes/events.py:180-183

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1941_cycling_triathlon_event_operations/workspace/PRD_COMPLETED.md`

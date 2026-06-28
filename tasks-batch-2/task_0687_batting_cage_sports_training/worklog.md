# Worklog — task_0687_batting_cage_sports_training

## Step 1: Create Task Directory — 2026-06-28T09:25:42.000Z

Task directory `tasks/task_0687_batting_cage_sports_training/` and its `workspace/` subdir already existed (pre-created by parallel-run harness). Per execution directives, the Step 1 directory-scan was skipped; folder used verbatim as {task_dir}. Verified INSTRUCTION.md present at project root and prd-bench-local-run on PATH.

## Step 2: Generate Scaffold (Expert) — 2026-06-28T09:51:36.000Z

All three scaffold artifacts are complete and pass the lint cleanly.

**Files written:** SCAFFOLD.yaml (1243 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1189 lines), SCAFFOLD_CORNER_DESIGN.yaml (1441 lines).

**Lint:** VERDICT: clean lint — 417 §1.8/§1.9 calls conform to §1.5; all 22 §1.1 FKs have reverse-reachability.

**Complexity profile:** primary archetype temporal_windowing, secondary pricing_engine; layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; flat-with-references topology under api_prefix: /v1; branching state-machine shape; peer_roles.

**Scaffold contents:**
- Entities: 10 — Facility, Lane, PitchingMachine, MaintenanceWindow, Member, Waiver, Instructor, Booking, Program, Enrollment
- State machines: 6 — Facility.posture (OPEN/RESTRICTED/CLOSED, derived), Lane.maint_status (compound), PitchingMachine.status (threshold), Booking.status (branching fork-join, 7 states), Program.status (cyclic OPEN↔FULL), Enrollment.status
- Calculations: 10 — booking_quote (forward_looking) vs booking_charge (chronological + peak) dual-variant; token_cost; machine_status (wear threshold); facility_posture; lane_maint_status (interval_merge); member_minutes_ledger; program_enrollment_ledger; waiver_validity; refund_policy
- Validations: 15 (priority-ordered auth→existence→state→safety→temporal→referential→fiscal→concurrency)
- Endpoints: 43 (incl. /_clock/set_current_utc test-driving endpoint, default clock 2026-04-01T00:00:00Z)
- Errors: 17
- Roles: 4 — FacilityManager (opaque), FrontDesk (opaque), Member (entity_backed:Member), Instructor (entity_backed:Instructor)
- Concurrency rules: 2 (OCC on Lane.version at booking confirm; OCC on Program.version at enrollment)

**Difficulty design:** 9 rules × 2 instances = 18 instances (dual_variant_calc, combinatorial_formula [modes a+b], non_linear_state_machine [branching + cyclic], transitive_cascade [depth-3 + depth-2], priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap [buffered closed-adjacency vs pure half-open], compensating_invariant [token wallet + membership minutes]). All numeric asserts pre-computed as literals.

**Corner design:** 36 active instances + 4 excluded_because stubs across 9 guide sections. Every catalog error except ERR_UNAUTHENTICATED is exercised by an assert; ERR_UNAUTHENTICATED remains a declared priority-1 validation for the unit-test-generator to cover via a raw-header test.

## Step 3: Copy Shared Files — 2026-06-28T09:51:36.000Z

Copied ./INSTRUCTION.md → tasks/task_0687_batting_cage_sports_training/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-28T09:57:37.000Z

Generated workspace/PRD.md (270 lines, 45901 bytes) for the Batting Cage & Sports-Training Complex. All three Hard Contracts PASS.

**Document metrics:** 5 top-level sections (Introduction, Global Specs, Business Logic, Endpoints, Errors); 11 §2 subsections + 8 §3 subsections = 19 subsections; §4 endpoint table 43 rows; §5 error table 17 errors.

**Hard Contract reports (all PASS):**
- Field coverage: 59/59 entity fields present; all request_body/input/query_params/path_params present.
- Rule coverage: 15/15 validations expressed (§2.11 ordinal 1st–15th); 2/2 OCC rejections (ERR_STALE_LANE_VERSION/412, ERR_STALE_PROGRAM_VERSION/412); all 6 state machines fully expressed; 9 calculations expressed with round-half-up ordering; side-effects/cascades expressed; sibling-branch symmetry maintained.
- Path purity (§3): 378 backtick tokens scanned, 0 path-like, 0 method tokens.

**Notable scattering:** dual-variant pricing split across §3.4 (forward-looking quoted_cost_cents) and §3.5 (chronological final_cost_cents + peak multiplier); confirm validation gate scattered between §3.4 (structural) and §3.5 (priority gates) with master ordering in §2.11; constants rendered with unit conversions (480=08:00 UTC etc.); CRITICAL-maintenance cascade and no-show sweep both reuse cancel/refund path. Neither design YAML was read.

## Step 5: Generate Unit Tests — 2026-06-28T10:13:18.000Z

**Test helpers (Stage 1) — 9 modules** in test_helpers/: types.py (entity TypedDicts + 12 enums; Waiver omits version/updated_at per common_fields:false), api_client.py (one method per endpoint incl. /_clock), api_errors.py (17 error IDs + HTTP-status map), assertions.py, factories.py (input-only payload builders), constants.py (all PRD thresholds), test_users.py (opaque FacilityManager/FrontDesk + entity-backed Member/Instructor builders), fixtures.py (composite scenarios), __init__.py.

**Test suite (Stage 2) — 8 files, 72 tests** (+conftest.py): test_01_pricing, test_02_booking_lifecycle, test_03_machine_wear, test_04_cascades_and_posture, test_05_validation_gates, test_06_refunds_and_invariants, test_07_entities_crud, test_08_endpoints_occ_rbac.

**Coverage:** Queue A (Difficulty) 36 tests — all 18 instances, ≥2 tests each. Queue B (Corner) 36 tests — all 36 non-stub instances, ≥1 test each. 72 tags == 72 functions, no untagged/dual-tagged. 4 excluded_because corner stubs correctly NOT translated. Two assertions trimmed under Core rule (dropped final_cost_cents==0 pre-confirm computed-field silence; re-pointed membership_minutes citation to verbatim §3.5/§3.7). All files byte-compile; suite collects 72 tests 0 errors; no skip/xfail.

## Step 6: Generate Implementation — 2026-06-28T10:13:18.000Z

**Framework/launch:** Python + Flask, in-memory dicts keyed by UUID, zero seeding. start.sh foreground launcher, guards pip install on import flask check, exec python3 app.py binding 0.0.0.0:$PORT (default 10000). Default logical clock 2026-04-01T00:00:00Z.

**Files:** start.sh, requirements.txt, app.py; core: clock.py, errors.py, response.py, db.py, middleware.py (auth+RBAC), constants.py, helpers.py, serializers.py; services/: pricing.py, derive.py, booking_ops.py; routes/: facilities.py, lanes.py, maintenance.py, members.py, bookings.py, programs.py, clock_route.py.

**Notable PRD-fidelity decisions:**
- Per-component round-half-up to whole cents, then tier discount, with Decimal (never float).
- Dual-variant pricing: quote never applies peak multiplier; charge applies 1.5× peak on lane part for starts in [17:00,21:00) UTC.
- OCC-before-overlap ordering: per §2.8 prose, ERR_STALE_LANE_VERSION (412) before ERR_LANE_TIME_CONFLICT (409) — implementer flags this contradicts bare priority-15 numbering in §2.11, followed specific §2.8.
- Lane buffer applied as closed-interval adjacency both sides.
- CRITICAL maintenance cancel reuses identical cancel-refund path (full token refund ≥120min to start else forfeit ceil(cost×0.5); MEMBERSHIP minutes fully restored).
- run-ops: no-show sweep increments strikes, then strikes + monthly minutes reset to 0, derived recompute, epoch_index++.
- Waiver = sole versionless/immutable entity.
- **Flagged ambiguity:** under literal §2.6, no_show_strikes reset to 0 within same run-ops that increments it, so priority-8 strike gate (>=MAX_STRIKES) only fires on transient state. Step 7 should watch for tests exercising this.

## Step 7: Run Tests and Iterate — 2026-06-28T10:27:00.000Z

**Iterations run:** 2 (1 diagnostic sweep establishing the baseline, 1 verification sweep after fixes).

**Tests deleted:** None. All 10 failing tests asserted PRD-covered rules; the failures were test-setup bugs, not unfair assertions.

**Fixes applied to test_helpers/:**
- fixtures.py — run_completed_session: added set_clock(start_utc) immediately before check-in. PRD §3.6 permits check-in only while the clock is within [start_utc − 30min, end_utc) and completion only when the clock is >= start_utc. The helper drove bookings request→confirm→check-in→complete without ever advancing the logical clock (default 2026-04-01T00:00:00Z) into the sessions' 09:00 window, so every check-in failed with ERR_INVALID_STATE - Outside the check-in window. Root cause of 6 failures (all of test_03_machine_wear.py plus test_cancel_completed_booking_invalid_state).

**Fixes applied to test_suite/** (STEP 2 test-vs-PRD consistency — 4 tests in test_05_validation_gates.py):
- test_lesson_confirm_blocked_by_inactive_instructor, test_membership_paymode_none_tier_blocked_at_confirm, test_membership_paymode_requires_non_none_tier, test_outside_open_hours_rejected_on_confirm — these issued a request_booking expecting it to reach REQUESTED then be rejected at confirm. But PRD §3.4 mandates booking shape and open-hours are checked at request time (ERR_BOOKING_SHAPE_INVALID; ERR_OUTSIDE_HOURS). The PRD-faithful implementation correctly rejects at request, so the setup's request_booking raised "Setup step failed". No PRD endpoint exists to deactivate an instructor or downgrade a tier after creation, so these confirm-time gates are unreachable in a faithful system. Each test now issues the request via create_booking and asserts the SAME error_id there — keeping the exact assertion while making the request consistent with PRD §3.4.

**Fixes applied to implementation/:** None. The implementation was already faithful to PRD §3.4 (request-time shape/availability/hours checks), §3.5 (confirm gates), and §3.6 (check-in/completion clock windows). No implementation check was weakened or removed.

**Final sweep:** All 8 parallel rounds passed 72/72 (passed == total, 0 failures in the union). Orchestrator independently re-ran the 8-round sweep to regenerate results.{1..8}.json — confirmed all 8 rounds 72/72, 0 failed.

## Step 8: Finalize PRD — 2026-06-28T10:30:20.000Z

PRD_FINALIZED.md is an EXACT copy of PRD.md — no edits warranted. Step 8 ran (not skipped, since Step 7 had >0 fixes) but all three Step 7 diff items were test-artifact corrections (test_helpers/ + test_suite/) at sites the implementation already handles in a way PRD.md uniquely determines; 0 implementation/ fixes, 0 deletions. Per the method ("Do NOT invent edits to justify the step"), zero PRD edits were made.

**Line counts:** PRD.md = 270, PRD_FINALIZED.md = 270, delta 0 (0.0%). diff confirms identical.

**Per-site analysis:**
- Site 1 (run_completed_session check-in window): PRD §3.6 already fixes window [start−30min, end) and completion >= start verbatim (routes/bookings.py:400-450, constants.py EARLY_CHECKIN_MIN=30). Pure test-helper bug. No edit.
- Site 2 (cancel COMPLETED booking): ERR_INVALID_STATE already pinned by PRD §2.11 priority 5 + §3.7 (routes/bookings.py:453-465). Fixture bug. No edit.
- Site 3 (4 validation-gate tests): PRD §3.4 line 168 mandates booking-shape/open-hours checks at request time; §3.5 re-states at confirm; impl applies at both (routes/bookings.py:188-191, 215-224, 320-339). Tests were inconsistent with §3.4; Step 7 corrected tests not impl. No edit.

**Cross-check:** constants/derive verified vs PRD verbatim (DEGRADED@5000, OOS@10000 inclusive >=, 1000 pitches/session, slot=10min, peak 1020-1260, refund cutoff 120, member cap 1200, max strikes 3, waiver 365 days). No off-site path contradicts PRD.md.

## Step 9: Complete PRD — 2026-06-28T10:36:29.000Z

Produced workspace/PRD_COMPLETED.md from a full PRD-vs-implementation/ scan. Source PRD_FINALIZED.md (270 lines, 45901 chars) → PRD_COMPLETED.md (270 lines, 48138 chars; +2237 chars, all in-paragraph inserts/revisions, no new sections).

**Counts:** ambiguity-pins: 5 · mismatch-revisions: 2 (across 6 edited paragraphs).

**Changes:**
- §2.3 — insert — ambiguity — pinned has_more formula (offset+limit < total_count), total_count as pre-pagination match count, offset unbounded (only limit is 1–100). (helpers.py:65-76, 54-61)
- §2.8 (lane) — insert — ambiguity — omitted/non-integer expected_lane_version is ERR_INVALID_REQUEST at well-formedness priority, not stale-version conflict. (routes/bookings.py:293-297)
- §2.8 (program) — insert — ambiguity — same pinning for expected_program_version. (routes/programs.py:135-137)
- §2.11 — revise — mismatch — "fifteenth" stale-version priority governs only program OCC; lane OCC on confirm is evaluated after resource-availability and before lane time-conflict (per §2.8), not last. (routes/bookings.py:320-330)
- §3.4 — insert — ambiguity — (a) pre-confirm final_cost_cents/token_cost are 0; (b) resource-availability reads lane's current maint_status (any open window makes lane unavailable regardless of overlap); (c) open-hours requires start>=open_minute and end<=close_minute, end-at-midnight=1440, no day-boundary spanning. (routes/bookings.py:181-182, 206-212, 74-95)
- §3.5 — revise — mismatch — confirm gates reordered: waiver gate before posture gate (impl + §2.11 order); clarified resource-availability snapshot + OCC-before-conflict position. (routes/bookings.py:309-330)
- §3.6 — insert — ambiguity — check-in outside window and completion before start_utc both yield ERR_INVALID_STATE; check-in window check precedes waiver re-check. (routes/bookings.py:412-419, 436-437)

Step 9 edited only PRD_COMPLETED.md; implementation/ and test artifacts untouched, so the Step 7 green state (8 rounds × 72/72) is preserved.

## PIPELINE COMPLETE — 2026-06-28T10:36:29.000Z

All 9 steps complete. workspace/PRD_COMPLETED.md present on disk. Final 8-round stability sweep: 72/72 passed on every round (results.{1..8}.json present in workspace/implementation/). Artifacts: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/ (9 modules), test_suite/ (8 files, 72 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.

# Worklog — task_0645_crossfit_box

Scenario: 645. CrossFit / Functional-Fitness Box: membership tier (unlimited/punch) & contract, class (WOD) capacity & reservation, on-ramp/foundations prerequisite, drop-in & visiting-athlete, coach & program track, benchmark/PR & leaderboard, competition team, freeze/cancel & billing

## Step 1: Create Task Directory — bash-only

Created `tasks/task_0645_crossfit_box/workspace`. Next index computed as 0645 (base-10 fix applied; raw `ls` max was `0644`).

## Step 2: Generate Scaffold — subagent

All three scaffold artifacts are generated, parse cleanly, and pass `scaffold_lint.py`. (Note: the lint reports 48 endpoints because it counts a couple of path-template variants; the §1.5 table has ~45 distinct endpoint rows including the 3 test-driving/batch endpoints.)

Generated all three required artifacts for **task_0645_crossfit_box** (CrossFit/Functional-Fitness Box), built purely from the scenario description and the skill spec (no sibling tasks consulted). `python3 scaffold_lint.py tasks/task_0645_crossfit_box` returns **VERDICT: clean lint**.

**Complexity profile:** Quota/allocation (primary) + Temporal windowing (secondary); layers = optimistic concurrency, cascading side effects, rate/threshold triggers, derived-field reconciliation; flat topology; branching state machines; peer roles; immediate consistency. Difficulty band: **Advanced (toward Expert)**.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **10 entities:** MembershipPlan, Member, Membership, ProgramTrack, Coach, ClassSession, Reservation, BenchmarkResult, CompetitionTeam, TeamMember. FKs use canonical `FK -> X.id` prefix; computed fields (seats_reserved, waitlist_count, punches_remaining, is_pr, reservation_suspended, cancellation_fee_cents).
- **5 state machines:** Membership (cyclic freeze/unfreeze + branching cancel), Reservation (parallel/branching: RESERVED/WAITLISTED ↔ CANCELLED/NO_SHOW/ATTENDED), ClassSession (SCHEDULED→CANCELLED/COMPLETED with cascades), CompetitionTeam (fork FORMING→LOCKED/DISBANDED), TeamMember.
- **1 concurrency rule:** OCC on `ClassSession.version` for reservation create (412 / ERR_STALE_SESSION_VERSION).
- **5 calculations:** cancellation_fee, refund_on_cancel (late-cancel window), pr_determination, leaderboard_ranking, cycle_close_billing — covering dual-variant (different entity domains) and combinatorial modes (a) and (c).
- **19 validations** (ordered, with pinned constants: NO_SHOW_SUSPEND=3, RESERVATION_CUTOFF=60min, LATE_CANCEL_WINDOW=12h, COACH_TURNAROUND=15min buffer).
- **48 endpoint rows** (incl. `/box/_clock/set_current_utc` default `2026-01-01T00:00:00Z`, `/box/_membership/complete-foundations`, `/box/_billing/run-cycle-close`); every FK has a reverse-reachability filtered-list GET.
- **19 errors**, **4 roles** (BoxManager opaque, Coach entity_backed, Member entity_backed, Anonymous opaque).

**§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml:** 9 rule_ids × 2 instances = **18 instances**, all grounds resolve, all `${var}` placeholders bound, OCC versions use captured `${var}`, formula literals precomputed (e.g., cycle total 35000, cancellation fee 15000, punch invariant 5→4→5).

**§1.9 SCAFFOLD_CORNER_DESIGN.yaml:** **43 instances** (37 active + 6 `excluded_because` stubs referencing valid §1.8 instances) across all 9 claim-extraction sections.

## Step 3: Copy Shared Files — bash-only

Copied `INSTRUCTION.md` → `tasks/task_0645_crossfit_box/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — subagent

Generated `workspace/PRD.md` for the Crossfit Box API.

**Structure:** 5 top-level sections, 17 subsections, ~248 lines.
- §1 Introduction (2 paragraphs)
- §2 Global Specifications (10 subsections: RBAC, fixed response envelope, pagination, common properties, hierarchical consistency/denormalized counters, OCC on seat reservation, logical clock/temporal windows, monetary/counting precision, left-to-right existence validation, validation ordering)
- §3 Business Logic (7 subsections by domain area: plan catalogue & member registry; membership activation/freezing; cancellation & billing cycle close; sessions/reservations/waitlist; reservation cancel/attendance/session cancel; benchmarks/PR/leaderboard; competition teams)
- §4 Endpoint table (4 columns, 49 endpoints)
- §5 Error table (2 columns, 19 errors)

**Coverage confirmation (all hard contracts PASS):**
- Contract 1 (Field-Name Coverage): All 50 entity field names + 8 endpoint identifiers present. 0 missing.
- Contract 2 (Rule Coverage): All 5 state machines, all 5 calculations (cancellation_fee, refund_on_cancel 12h timely-inclusive boundary, pr_determination strict comparisons, leaderboard_ranking asc/desc + tie-breaks, cycle_close_billing two-pass created_at-ordered FROZEN-excluded), all 19 validations with priority ordering, OCC stale-version rule with ERR_STALE_SESSION_VERSION (412).
- Contract 3 (§3 Path Purity): 404 backtick tokens in §3; 0 slash-prefixed, 0 bare HTTP-method, 0 method+path tokens.

All 18 state enum values, 14 field-enum values, 4 roles, both auth headers, and the fixed §2.2 block present.

## Step 5: Generate Unit Tests — subagent

Test infrastructure generation complete.

**Test files:** 7 (`test_01`–`test_07` under `test_suite/`) plus `conftest.py`.
**Total tests:** 73, all collect cleanly and compile.

**test_helpers/ modules created (Stage 1):** `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`, `__init__.py`. All ten entities carry `common_fields: true` (PRD §2.4). Coach and Member are `entity_backed` roles — `fixtures.py` threads real entity ids via `make_coach_headers(coach_id)` / `make_member_headers(member_id)` for every ownership-gated call, never the shared constant.

**Queue A (Difficulty):** 18 instances, all translated, each with exactly 2 tests (36 tests). 0 skipped — every instance passed the PRD-first two-condition filter.

**Queue B (Corner):** 37 non-stub instances, all translated (37 tests, ≥1 each). 6 `excluded_because:` stubs NOT translated (all 6 cross-references resolve to real Difficulty instances). 0 additional skips.

**Citation integrity:** Every test docstring ends with exactly one `Design:` line copied verbatim. All 100 quoted PRD citations carry a literal ≥8-word window surviving raw grep of PRD.md. No skip/skipif/xfail.

**Notable PRD-adjudication call:** the `missing_auth_headers` corner instance uses `validate_error_is_one_of([ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE])` (error-precedence silence pattern).

## Step 6: Generate Implementation — subagent

Generated a complete Python + Flask implementation in `workspace/implementation/`.

**Files created (11):** `start.sh`, `requirements.txt`, `app.py` (49 routes), `clock.py` (defaults `2026-01-01T00:00:00Z`), `db.py` (in-memory dicts + `_seq` monotonic tiebreak), `errors.py` (19-error catalog), `response.py` (meta/response_type/data envelope, ISO-8601 UTC 3-fractional-digit), `middleware.py` (4 roles), `serialize.py`, `helpers.py` (constants: cutoff 60m, late-cancel 12h, coach buffer 15m, suspend threshold 3), `services.py` (calculations + cascades).

**Endpoints implemented: 49** — all §4 routes plus 3 test-driving/batch endpoints (`/box/_clock/set_current_utc`, `/box/_membership/complete-foundations`, `/box/_billing/run-cycle-close`).

**Verification:** ~70 live assertions across three scenario suites pass (OCC stale-version 412, foundations/suspension/window/drop-in/duplicate/time-conflict/coach-double-book/no-punches rejections, punch decrement/restore, waitlist promotion, late-cancel forfeit vs 12h-boundary timely refund, freeze cascade, unfreeze frozen-day extension, PR determination, eligibility-filtered leaderboard, team roster/lock/disband, no-show strike suspension at 3, two-pass cycle-close billing total 35000 FROZEN-excluded).

**Constraint confirmation:** `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec`. Storage in-memory only (grep confirmed no open/sqlite/json.dump/pickle/.db/shelve). No seeding/preloading at startup.

## Step 7: Run Tests and Iterate — long-lived subagent

All 8 parallel rounds pass 73/73. Clean exit.

**Iterations run:** 2 sweeps (1 diagnostic baseline + 1 verification). The baseline sweep showed 4 deterministic failures (failing in all 8 rounds, not flaky); after fixes, all 8 rounds passed 73/73.

**Tests deleted:** None. All 4 failures were STEP-2 test-vs-PRD consistency bugs in `test_helpers`/`test_suite`, not PRD-silence or non-derivability issues.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — added `make_leaderboard_eligible_member(coach_id, track_id, plan_id, session_starts_at)`. The three failing leaderboard tests registered bare members with no membership, so the PRD §3.6 eligibility filter ("members who hold an `ACTIVE` membership on a plan attached to a session of the requested track") correctly excluded every member, returning an empty leaderboard. The new helper constructs that precondition (active membership + a reservation on a session of the track) so eligible members exist.

**Fixes applied to `test_suite/`:**
- `test_suite/test_03_reservations_waitlist_cascades.py` — added the missing import of `setup_drop_in_reserved_seat` (used at line 104 but never imported), which was raising `NameError` in `test_session_cancel_drop_in_refunds_fee_regardless_of_window`.
- `test_suite/test_05_benchmarks_leaderboard.py` — in the three ranking tests (`time_ascending_three_members`, `time_tie_broken_by_earlier_recorded_at`, `load_descending_order`), replaced bare `register_member()` calls with `make_leaderboard_eligible_member(...)` (using distinct future `starts_at` per member to avoid shared-coach double-booking) and added imports for `create_unlimited_plan` and `make_leaderboard_eligible_member`.

**Fixes applied to `implementation/`:** None. The reference implementation's leaderboard eligibility filter and the drop-in session-cancel refund logic were already PRD-faithful; the failures traced entirely to test fixtures/imports.

## Step 8: Finalize PRD — subagent

Produced `workspace/PRD_FINALIZED.md`. (Step 7 had `test_suite/`+`test_helpers/` fixes — skip condition not met, so Step 8 ran.)

**Line counts:** PRD.md = 247 lines, PRD_FINALIZED.md = 247 lines. One paragraph (§3.6) expanded in place; 0% line-count delta.

**Changes:**
- §3.6 (Leaderboard eligibility) — insert — pinned the under-determined phrase "a plan attached to a session of the requested track": clarified that, because no resource carries a direct plan→track or plan→session FK, a member is eligible exactly when they hold an `ACTIVE` membership that has at least one reservation (of any status) on a session whose `track_id` is the requested track — `implementation/app.py:446-462`.

**Step 7 items disposition:**
1. Leaderboard eligibility fixture — genuine PRD-silence (the phrase "a plan attached to a session of the requested track" has no FK realization). Patched.
2. `setup_drop_in_reserved_seat` import + leaderboard imports — pure fixture/import bugs, no PRD issue. No edit; PRD §3.5 already determines box-cancel-always-refunds.

**Pre-edit search log:** Subject = leaderboard eligibility. Enumerated sole eligibility computation at app.py:430-494; confirmed no other endpoint references it; confirmed program_track/create_plan/create_session carry no direct plan↔session/track FK; verified DROP_IN reservations never confer eligibility. Wording adjusted to status-agnostic ("any status", "track_id is the requested track") to match impl's lack of reservation-status/session-status filters.

## Step 9: Complete PRD — subagent

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan.

**Files:** Source PRD_FINALIZED.md = 247 lines / 42,909 chars → PRD_COMPLETED.md = 249 lines / 44,021 chars (+2 lines, +1,112 chars).

**Counts:** 7 changes — 6 ambiguity-pins, 1 mismatch-revision.

**Per-change:**
- §2.4 (Common Resource Properties) — revise — ambiguity — pinned `version` initial value to 1 — `db.py:48`.
- §3.1 (Member Registry) — insert — ambiguity — duplicate (case-insensitive) `email` rejected with `ERR_INVALID_REQUEST` — `app.py:176-178`.
- §3.2 (Activation) — insert — ambiguity — `commitment_end_date` month arithmetic day-preserving with clamp-down to last valid day — `helpers.py:129-142`.
- §3.4 (Class Sessions) — insert — ambiguity — coach creation shape: BoxManager-created, `full_name`, lowercased/case-insensitive-unique `email` (collision → `ERR_INVALID_REQUEST`), optional `certified` defaulting true — `app.py:348-362`.
- §3.5 (Completing Sessions) — revise — ambiguity — `attendance` map keyed by reservation id; attended marked by boolean true or case-insensitive ATTENDED/ATTEND/PRESENT/TRUE; else/absence = no-show; defaults empty — `app.py:618-669`.
- §3.6 (Leaderboard) — revise — mismatch — leaderboard is paginated array of best-defining BenchmarkResult objects, rank by position, no separate `rank` field — `app.py:482-494`.
- §3.7 (Competition Teams) — insert — ambiguity — duplicate non-DISBANDED team `name` rejected with `ERR_INVALID_REQUEST` — `app.py:959-961`.

## Final Verification — 8-round parallel sweep (orchestrator-run)

Step 7's `results.{1..8}.json` artifacts had been cleaned up, so the orchestrator re-ran the 8-round parallel sweep to regenerate them and independently confirm green. **All 8 rounds: passed=73 total=73 failed=0.** Artifacts persisted at `workspace/implementation/results.{1..8}.json`.

## Pipeline complete

Task `task_0645_crossfit_box` fully generated and verified green (73/73 × 8 rounds).

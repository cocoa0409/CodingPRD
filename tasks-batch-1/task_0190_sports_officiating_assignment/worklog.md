# Worklog — task_0190_sports_officiating_assignment

## Step 1: Create Task Directory — 2026-06-06T00:00:00.000Z

Used pre-allocated directory `tasks/task_0190_sports_officiating_assignment` (did NOT scan ./tasks for a new index, per orchestrator args, to avoid ID collision with parallel runs). Directory already existed with `workspace/` subdir present. No new index allocation performed.

## Step 2: Generate Scaffold — 2026-06-06T00:00:00.000Z

All three scaffold artifacts are generated, parse cleanly, and pass `scaffold_lint.py` with `VERDICT: clean lint`. I did not look at any sibling task directory — the design was built purely from the scenario and the scaffold-generator skill spec.

## Summary

Generated three scaffold artifacts for **task_0190_sports_officiating_assignment** at the **Expert** difficulty band (§0.4), all in `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0190_sports_officiating_assignment/`.

**Complexity profile:** quota_allocation (primary) + temporal_windowing (secondary); flat topology; cyclic + parallel/auto-bubble state machines; peer_roles; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **Entities: 10** — League, Official, Game, CrewSlot, Assignment, Availability, ConflictDeclaration, Evaluation, SeasonLedger, PenaltyAppeal
- **State machines: 5** — Game (parallel staffing × completion dims, auto-bubble OPEN↔STAFFED), CrewSlot (cyclic VACANT→OFFERED→VACANT re-offer loop), Assignment (cyclic offer/response), League (config posture), PenaltyAppeal (branching PENDING→{UPHELD,DENIED} with divergent side effects)
- **Calculation rules: 6** — provisional_game_pay & finalized_settlement_pay (dual-variant on Assignment), decline_penalty (non-linear tiered+escalation+postseason), no_show_penalty, postseason_eligibility (order-sensitive round-then-average), reliability_score
- **Validation rules: 17** (priority-ordered, auth→existence→state→business)
- **Endpoints: 47** (including 1 test-driving `/_clock/set_current_utc`; flat resource collections; full FK reverse-reachability)
- **Error catalog: 24** codes
- **Roles: 4** — LeagueAdmin, Assignor, Official (entity_backed), Evaluator
- **Concurrency rules: 2** — OCC on Game.version (offer & accept CREATE-with-supersede races)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 21 instances across all 9 Difficulty Rules (each ≥2; boundary_precision_check has 4, compensating_invariant has 3 incl. penalty-points conservation via appeals).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** 40 instances across all 9 claim-extraction sections (32 active test recipes + 8 `excluded_because` stubs citing real §1.8 instances).

**Validation:** All three parse; 69 instance names unique across §1.8+§1.9; every error referenced; every endpoint role in RBAC; both OCC rules verified (occ field in input + version bump in side effects); all formula-derived asserts computed as literals (pay 12500/15000/18000/13500, mileage 700/10700, decline 16, no-show 15, eligibility mean 3.35, penalty conservation 8→0). `scaffold_lint.py` returns **VERDICT: clean lint** (47 endpoints, 10 entities, 592 calls scanned).

## Step 3: Copy Shared Files — 2026-06-06T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0190_sports_officiating_assignment/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-06T00:00:00.000Z

Generated `workspace/PRD.md` (312 lines, 43772 bytes) from `SCAFFOLD.yaml` only. SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml withheld.

**Sections covered:**
- §1 Introduction (quota-allocation framing + concurrency/money/reliability angle)
- §2 Global Specs: 2.1 RBAC, 2.2 Response Structure, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Hierarchical Consistency, 2.6 OCC on Games, 2.7 Nested/Reverse-Reachability Reads, 2.8 Money/Points/Rounding, 2.9 Validation Ordering
- §3 Business Logic: 14 subsections (league setup → availability/conflicts → game build → offer gauntlet → provisional pay → offer responses → no-shows/reliability → penalty sizing → lock/settle/finalized pay → cancellation → evaluations → eligibility → appeals → test clock)
- §4 Endpoint table (4 columns), §5 Error table (2 columns)

**Coverage (verified mechanically):** all 10 entities + 65 field names present; 47/47 endpoints match scaffold exactly; 24/24 errors in table + narrative; 4/4 roles named (Official entity-backed via X-User-ID = official id / ownership via official_id; other three opaque); all state values + enums present as exact UPPERCASE strings.

**Hard Contract reports:** Field coverage PASS, Rule coverage PASS (17 validations, 2 OCC rules + lock/settle/PATCH OCC, all state machine transitions, 6 calculations, cascades, defaults, sibling-branch symmetry), Path purity PASS (391 backtick tokens scanned in §3, 0 paths/methods leaked).

**Notable scattering/structure decisions:** offer-time eligibility rendered as ordered 7-step list in §3.4 (precedence load-bearing) while auth/role/existence/state ordering lives in §2.9; dual-variant pay scattered (provisional §3.5 offer-time frozen rank, finalized §3.9 settlement rank + reliability deduction); OCC framed purely in stale-version terms; constants embedded in business prose with unit framing.

## Step 5: Generate Unit Tests — 2026-06-06T00:00:00.000Z

Generated complete test infrastructure for `task_0190_sports_officiating_assignment`.

**Test files: 7** (plus `conftest.py`), **82 tests total**, each carrying exactly one `Design:` tag.

**Queue A (Difficulty, §1.8):** all **21 instances** covered, **2 tests each = 42 tests**. The second-coverage tests live in `test_07_difficulty_depth.py` and hit each instance from a complementary angle (opposite side of a boundary, alternate branch like LOCKED-stays-LOCKED on no-show, multi-official conservation, no-show-appeal noshow_count restoration, etc.).

**Queue B (Corner, §1.9):** all **40 non-stub instances** covered, **1 test each = 40 tests**, spread across `test_01`–`test_06`.

**Instances skipped:** none beyond the design's own stubs. All **8 `excluded_because:` stubs** were correctly NOT translated (their cross-references all resolve to real queue-A instances that own the assertion): `noshow_cascade_already_covered_stub`, `provisional_vs_final_divergence_stub`, `priority_rank_vs_travel_stub`, `double_book_error_stub`, `stale_game_version_error_stub`, `conflict_of_interest_error_stub`, `rate_threshold_decline_escalation_stub`, `cascading_side_effect_decline_releases_slot_stub`. No non-stub instance failed the PRD-first two-condition filter — the PRD covers and uniquely-derives every asserted rule (including the round-per-item-then-average eligibility flip, pinned verbatim in §3.11 + §2.8).

**test_helpers files produced (9):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

**Verification performed:** all files parse; `test_helpers` imports cleanly; pytest collects all 82 tests with zero collection errors; all 120 quoted PRD citations survive a literal grep of PRD.md (C1); every `Design:` tag resolves to a real index instance; no `skip`/`skipif`/`xfail` markers; no scaffold/table/§1.x leakage. Identity threading uses `make_official_headers(official_id)` for the entity-backed Official role on all ownership-gated calls; every OCC call re-reads the live `Game.version` immediately before use.

## Step 6: Generate Implementation — 2026-06-06T00:00:00.000Z

**Source files produced (28 files)** under `workspace/implementation/`:
- `start.sh` (launcher), `requirements.txt` (flask==3.0.3), `app.py` (Flask entry + blueprint registration + global error envelope handler)
- Foundation: `db.py` (in-memory store), `errors.py` (full error catalog as `(id, http)` tuples), `response.py` (envelope), `middleware.py` (auth/RBAC), `pagination.py`, `timeutil.py`, `clock.py` (logical test clock), `lookup.py` (existence→ERR_NOT_FOUND), `serialize.py` (per-entity field projection)
- `services/`: `calc.py` (all calculations + haversine), `derive.py` (denormalized-field reconciliation), `eligibility.py` (7-step offer gauntlet), `intervals.py` (half-open interval math), `transitions.py` (cascades + penalty assessment), `validate.py` (input validity)
- `routes/`: `leagues.py`, `officials.py`, `availabilities.py`, `conflicts.py`, `games.py`, `crew_slots.py`, `assignments.py`, `appeals.py`, `clock_route.py`

**Endpoint count: 49 endpoints** implemented — every route in PRD §4 / SCAFFOLD §1.5, including all reverse-reachability list reads.

**State machines**: Game (DRAFT→OPEN→STAFFED↔OPEN→LOCKED→COMPLETED, +CANCELLED), CrewSlot (VACANT↔OFFERED↔FILLED, →RELEASED), Assignment (cyclic OFFERED→ACCEPTED/DECLINED, ACCEPTED→NO_SHOW/CANCELLED/COMPLETED), League (SETUP→OPEN→POSTSEASON→ARCHIVED), PenaltyAppeal (PENDING→UPHELD/DENIED). Auto-bubbling (OPEN↔STAFFED on crew_filled_count changes) and the depth-3 cancel cascade (game→slot→assignment) realized in `services/transitions.py` with each affected resource independently bumping its own version/updated_at.

**Calculations** (all `Decimal` + ROUND_HALF_UP at each step): provisional game pay (offer-time rank, postseason 1.20 uplift), finalized settlement pay (settlement-time rank + reliability deduction when penalty_points ≥ 10 → ×0.90), decline penalty (tiered by lead time 24h/72h + capped escalation + postseason ×2), no-show penalty (base 15 + capped escalation), round-per-item-then-average-then-round mean_rating, reliability_score = max(0, 100−penalty_points), postseason eligibility (4-condition derive).

**OCC**: `expected_game_version` checked against `Game.version` on offer/accept/lock/settle (412 ERR_STALE_GAME_VERSION); `expected_official_version` against `Official.version` on PATCH (412 ERR_STALE_OFFICIAL_VERSION). Validation precedence follows PRD §2.9 (auth→role→existence→state→ownership→business→input).

**Confirmations**: `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec`, guards `pip install` behind a flask-import check. Storage is **in-memory only** (module-level dicts in `db.py`); **nothing is seeded at startup**. Fresh boot-to-ready ~7s.

## Step 7: Run Tests and Iterate — 2026-06-06T00:00:00.000Z

Clean 8-round parallel sweep achieved.

**Iterations run:** 2 (baseline sweep at 78/82, then a fix sweep at 81/81 across all 8 parallel rounds).

**Baseline:** 4 stable failures (identical across all 8 rounds, not flaky): 3 tests rejected with `ERR_NOT_POSTSEASON_ELIGIBLE`; 1 test `test_availability_end_exclusive_zero_gap_boundary` got 201 instead of the asserted 422.

### Tests deleted (1)
- **`test_availability_end_exclusive_zero_gap_boundary`** (`test_suite/test_03_offer_eligibility.py`) — STEP 1b unique-derivability collapse (boundary-precision / endpoint-behavior). PRD §3.4 step 4 describes the game interval as "half-open with the end excluded" and §3.2 describes the window as half-open "the end is exclusive," then says the game must "lie entirely inside" the window. With both intervals half-open and identical bounds `[18:00,20:00)`, set-containment (`inner_end <= window_end`) yields *covered* → accept (the implementation's faithful reading), while a strict-endpoint reading (`inner_end < window_end`) yields *not covered* → reject (the scaffold's intent). The PRD prose does not disambiguate, so two divergent PRD-faithful implementations exist → deleted. The same design instance remains covered by `test_availability_interval_strictly_inside_window_succeeds` (test_07), which uses a genuinely strictly-inside game `[18:00,19:00)` and is unambiguous.

### Fixes applied to test_helpers/ (1 file)
- **`test_helpers/fixtures.py`** — added `make_postseason_eligible(league, official, ...)`. The three failing postseason tests created fresh officials (whose `mean_rating` is null per PRD §3.11) and expected postseason offers to succeed, but PRD §3.12 requires `mean_rating` to be *not null* for `postseason_eligible`, and PRD §3.4 rule 7 gates postseason offers on that flag. The implementation correctly rejected with `ERR_NOT_POSTSEASON_ELIGIBLE` — a TEST-BUG precondition (STEP 2). The new helper drives one full regular-season lifecycle (offer → accept → lock → settle → evaluate) at the official's home venue (distance 0, ASSISTANT slot, any rank) so `games_worked_count` and a non-null `mean_rating` legitimately satisfy the eligibility gate, then leaves the clock for the caller to repin. Also added `create_evaluation_payload` to fixtures' factory imports.

### Fixes applied to test_suite/ (callers of the new fixture)
- **`test_04_pay_and_penalty_calculations.py`** — `test_decline_penalty_late_postseason_nonlinear` and `test_provisional_postseason_uplift_before_mileage`: import and call `make_postseason_eligible` before the postseason offer. (Decline-escalation stays 0 because the prior completed game carries no penalty.)
- **`test_07_difficulty_depth.py`** — `test_provisional_uplift_before_mileage_with_mileage`: same fix; the eligibility game is at the home venue so it adds no mileage side effect to the test's 700-cent assertion.

### Fixes applied to implementation/
- None. The implementation was faithful to PRD §3.4 (offer gauntlet, including rule 7 postseason gate), §3.12 (eligibility requires non-null `mean_rating`), and §3.4 step 4 / §3.2 (standard half-open interval containment). No PRD-required check was weakened or removed.

**Final state:** 81/81 passing in all 8 concurrent rounds, no flakiness.

## Step 8: Finalize PRD — 2026-06-06T00:00:00.000Z

Step 8 ran (Step 7 had 1 deletion + test_suite/test_helpers fixes → skip condition not met).

**Line counts:** PRD.md = 312 lines; PRD_FINALIZED.md = 312 lines (one line revised in place, +0 lines, ~0% line-count delta; the single edited line grew by ~3 sentences of inline prose).

### Changes (1)
- **§3.4, offer-gauntlet step 4 (Availability cover)** — *revise* — appended an inline clause pinning the AVAILABLE-window containment as **set-containment of two half-open intervals** with **inclusive endpoint comparison** (`window_start <= game_start` AND `game_end <= window_end`), so a game `[18:00,20:00)` is covered by a window `[18:00,20:00)`. — `implementation/services/intervals.py:22` (`contains` returns `window_start <= inner_start and inner_end <= window_end`), called from `implementation/services/eligibility.py:87`.

### Step 7 items addressed
1. **Deleted test `test_availability_end_exclusive_zero_gap_boundary`** → genuine PRD silence. PRD §3.4 step 4 ("lie entirely inside") + §3.2 (half-open window) did not disambiguate `inner_end <= window_end` (impl: covered/accept) from `inner_end < window_end` (reject). The implementation pins set-containment; PRD_FINALIZED now states this. **PRD edit made.**
2. **Postseason fixture bug** (`make_postseason_eligible`, 3 tests) → **no PRD edit needed.** TEST-BUG precondition: fresh officials have null `mean_rating`, and PRD §3.12 already requires "`mean_rating` is not null and is at least … `postseason_min_rating`", with §3.4 rule 7 already gating on `postseason_eligible`. Implementation matches existing prose verbatim — no silence, no mismatch.

### Per-edit pre-edit search log
**Edit 1 — Availability cover containment**
- **(a) Subject:** half-open interval containment of the game interval inside an AVAILABLE window.
- **(b) Impl paths enumerated/read:** `services/intervals.py:19-22 contains()` (inclusive both ends, only containment helper); `services/intervals.py:25-28 overlaps()` (strict, used for BLACKOUT + double-booking, NOT containment); `services/eligibility.py:68-91 check_availability` (BLACKOUT uses overlaps, AVAILABLE uses contains); `routes/availabilities.py:42-43` window-creation `we > ws` (strictly later, untouched); `services/intervals.py:13-16 game_interval` (end-exclusive). Grepped all callsites: `contains` called once (eligibility.py:87), `overlaps` for BLACKOUT (eligibility.py:78) + double-booking (eligibility.py:109).
- **(c) Wording adjustment:** scoped the new sentence explicitly to "set-containment … inside an `AVAILABLE` window" so it does not bleed into the adjacent BLACKOUT "must not intersect" clause (strict/overlaps). Left BLACKOUT clause and window-creation validation verbatim.

No implementation changes were required by Step 7, and none implied by this PRD patch.

## Step 9: Complete PRD — 2026-06-06T00:00:00.000Z

Full PRD-vs-implementation completeness scan. Started from PRD_FINALIZED.md.

**File metrics:** Source `PRD_FINALIZED.md` — 312 lines, 44,276 chars; Output `PRD_COMPLETED.md` — 312 lines, 45,102 chars; char delta +826 (line count unchanged; all edits in-line).

**Counts:** Ambiguity-pins: 9; Mismatch-revisions: 0.

**Changes:**
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset`, out-of-range `limit` (not 1–100), or negative `offset` rejected with `ERR_INVALID_REQUEST` (not clamped) — `pagination.py:19-39`
- §3.4 Offering / distance — insert — ambiguity — `distance_miles` via haversine, mean Earth radius 3958.7613 miles, returned as JSON number to two decimals — `services/calc.py:37,50-63`
- §3.12 Postseason Eligibility — insert — ambiguity — eligibility read returns full Official resource object (same shape as `GET /officials/{id}`), breakdown on official's own fields, no separate breakdown sub-object — `routes/officials.py:128-136`
- §3.14 Test Clock — insert — ambiguity — `POST /_clock/set_current_utc` returns `200 OK` standard envelope with empty `{}` in `data` — `routes/clock_route.py:28`
- §4 `/officials` — insert — ambiguity — supported `league_id` query filter — `routes/officials.py:78-82`
- §4 `/availabilities` — insert — ambiguity — supported `official_id` query filter — `routes/availabilities.py:61-65`
- §4 `/conflict-declarations` — insert — ambiguity — supported `official_id`/`peer_official_id` query filters — `routes/conflicts.py:65-72`
- §4 `/games` — insert — ambiguity — supported `league_id` query filter — `routes/games.py:84-88`
- §4 `/assignments` — insert — ambiguity — supported `game_id`/`official_id`/`crew_slot_id` query filters — `routes/assignments.py:42-52`

**Left unchanged (already pinned):** all pay/penalty/reliability/mean-rating formulas (§3.5/3.8/3.9/3.11); eligibility-read & PATCH version bumps (follow from §2.4 + §3.1); offer eligibility-gauntlet ordering, OCC/stale-version guards, double-booking status sets, no-show/withdraw/cancel cascades, settlement accrual — all match PRD prose verbatim.

## Final Verification — 2026-06-06T00:00:00.000Z

Re-ran the full 8-round parallel stability sweep as a durable confirmation (Step 7's in-loop `rm -f` had cleared the prior round's artifacts). All 8 rounds: **passed=81 / total=81 / failed=0**, no flakiness. `results.{1..8}.json` persisted under `workspace/implementation/`. Pipeline complete.

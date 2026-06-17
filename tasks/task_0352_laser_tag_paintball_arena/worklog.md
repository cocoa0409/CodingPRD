# Worklog — task_0352_laser_tag_paintball_arena

Scenario: Laser Tag & Paintball Arena: session/field booking & capacity, group/party package, equipment (marker/vest) rental & deposit, ammo/CO2 & add-on, waiver & age rules, referee/marshal assignment, walk-in vs reservation, league/event

Difficulty: Expert (passed to Step 2 scaffold-generator §0.4 Expert tier only)

## Step 1: Create task directory — 2026-06-14T13:09:26.000Z

Created `tasks/task_0352_laser_tag_paintball_arena/workspace` (pre-allocated folder used directly; no tasks/ scan per instructions).

## Step 2: Generate scaffold (Expert tier) — 2026-06-14T13:31:00.000Z

All three scaffold artifacts generated, lint-clean, internally consistent. Verdict: clean lint (372 §1.8/§1.9 calls all conform to §1.5; every FK reverse-reachable).

Design (Expert tier) — primary archetype temporal_windowing + secondary quota_allocation; flat topology; branching/cyclic state machines; peer_roles; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation. api_prefix: "" (every entity is its own top-level collection).

SCAFFOLD.yaml (§1.0–§1.7):
- 12 entities: Arena, Field, PartyPackage, Booking, WaiverProfile, EquipmentUnit, Rental, AddOnOrder, Referee, RefereeAssignment, League, LeagueMatch
- 6 state machines: Booking (branching: CHECKED_IN vs NO_SHOW), Rental (deposit lifecycle), EquipmentUnit (pool), WaiverProfile, League (cyclic OPEN↔ROUND_LOCKED), LeagueMatch
- 6 calculations: add_on_total_cents (quote vs settled, tiered ammo), deposit_settlement_cents (hold vs final), booking_invoice_cents (round-per-line-then-sum, pinned), field_fee_cents, league_standings, referee_required
- 2 concurrency rules: OCC on Field.version (confirm) and League.version (advance-round), both 412
- 17 validations, 56 endpoints (incl. one /_clock/set test-driving endpoint), 38 errors, 4 RBAC roles (ArenaManager, FrontDesk, FieldMarshal, LeagueDirector — all opaque)

SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8): 9 rule_ids × 2 = 18 instances, all 9 §0.5 differentiation clauses satisfied. Formula-derived asserts pre-computed as literals.

SCAFFOLD_CORNER_DESIGN.yaml (§1.9): 47 instances (44 active + 3 valid excluded_because stubs) across 9 guide sections.

Custom replay audits fixed three real semantic bugs (walk-in start≠clock case, equipment-overlap instance tripping field-slot check first, check-in waiver precondition relaxed to minor-only safety gate).

## Step 3: Copy INSTRUCTION.md — 2026-06-14T13:32:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-14T13:38:00.000Z

Generated workspace/PRD.md — ~304 lines, ~6,960 words (Expert tier). Both withheld design index files NOT opened.

Sections: §1 Introduction; §2 Global Specs (10 subsections: RBAC, Response Structure verbatim §2.2, Pagination, Common Resource Properties, Nested Retrieval & Referential Existence, OCC on Field/League, Equipment Pool & Deposit Ledger, Monetary/Rounding, Deterministic Arena Clock, Cascading Consistency & Reverts); §3 Business Logic (9 lifecycle subsections); §4 Endpoint table (56 endpoints); §5 Error table (38 errors).

Documented: 12 entities (66 fields), 56 endpoints, 38 error IDs, 6 calculations (tiered add-on quote/settled at 500/1500/2000-ball tiers @ 10/8/6 cents, 700 cents/CO2 tank, 8.25% tax, 60-min lead time, party-size threshold 12, adult age 18).

Hard-contract checks: field coverage 66/66 + 3 input params PASS; rule coverage (OCC, 17-rule validation priority, state transitions, cascades, 6 calcs w/ pinned rounding) PASS; path purity §3 (363 backtick tokens, 0 paths/methods) PASS.

Scattering choices: OCC mechanics in §2.6 restated at confirm (§3.3) + lock/advance-round (§3.9); add-on params split across §3.5 (metered) and §3.1 (package allowance/discount); referee_required conditions distributed across §3.6/§3.1/party-size; constants embedded in narrative; §3 names endpoints by transition framing only (method/path solely in §4).

## Step 5: Generate unit tests — 2026-06-14T13:50:00.000Z

test_helpers/ (8 modules): types.py (13 entity TypedDicts + 13 enums), api_client.py (55 endpoint methods), api_errors.py (ApiErrorId enum + HTTP map), assertions.py (per-entity + ledger/settlement invariants), factories.py (per-entity payload factories), constants.py (ammo tiers/tax/referee/age/lead-time), test_users.py (4 opaque role headers), fixtures.py (5-tier composite setup + rental/round-locked shortcuts), __init__.py.

test_suite/ (8 files + conftest, 80 test functions): Queue A (Difficulty) 36 tests ≥2 per instance across all 18 difficulty instances; Queue B (Corner) 44 tests ≥1 per non-stub instance across all 44 non-stub corner instances.

Audit clean: 0 untagged/dual-tagged; every Design: tag resolves; 0 difficulty instances <2 tests; 0 non-stub corner uncovered; 3 excluded_because stubs correctly skipped; all PRD citations verbatim-matched; no scaffold leakage; all 80 collect under pytest.

Instances skipped: none beyond the 3 mandated excluded_because corner stubs (booking_branch_checkin_happy_path, advance_round_stale_league_version_returns_412, cancel_booking_cascade_releases_rental_and_equipment).

## Step 6: Generate implementation — 2026-06-14T13:50:00.000Z

13 files in workspace/implementation/: start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, exec python3 app.py, flask-import guard), requirements.txt (flask only), app.py (app + error handlers + Arena/Field/PartyPackage routes), routes_ext.py (~40 routes + cascade primitives), db.py (in-memory dicts + RLock + version/timestamp), errors.py, response.py, middleware.py (auth/RBAC), validation.py, calc.py, domain.py, serialize.py, timeutil.py.

Endpoints: 56 (matches PRD §4). State machines validate precondition state + run side effects; booking cancel/no-show/complete cascades (release rentals → equipment AVAILABLE → deposit ledger → void quoted add-ons → free referee → recompute headcount), each child version-bumped. Calculations integer cents Decimal+ROUND_HALF_UP: tiered ammo (500@10/1500@8/rest@6), quote vs settled, deposit waterfall, per-line-taxed invoice (8.25%), package field fee, weighted league standings. OCC: expected_field_version on confirm, expected_league_version on lock/advance-round → 412. Clock: per-arena current_utc via /_clock/set default epoch. Validation precedence: auth(401)→role(403)→existence(404)→shape(400)→state(409)→OCC(412)→business.

PRD ambiguities resolved: (1) missing add-on id → 404 generic ERR_VALIDATION; (2) check-in window-out-of-range → ERR_BOOKING_INVALID_STATE (409); (3) field version bumped on each booking transition that recomputes headcount (only confirm's bump load-bearing for OCC).

## Step 7: Run tests and iterate to PASS — 2026-06-14T14:20:00.000Z

### Long-lived diagnostic subagent summary (verbatim):

**Iterations run:** 4 (initial diagnostic sweep + 3 fix-and-verify sweeps). Final state: two consecutive clean sweeps, all 16 rounds at 78/78 passed, 0 failed, 0 errors.

**Root-cause classes found:** 2 real test-defect tests deleted, 2 test-fixture bugs fixed, 1 implementation/boot-latency fix.

**Tests deleted (PRD-silence / non-unique-derivability):**
- `test_slot_conflict_reported_over_capacity_when_both_violated` (test_04) — UNIQUE-DERIVABILITY FAILURE. The PRD contradicts itself on field-slot-vs-capacity precedence: §3.2's booking-create narrative checks capacity first and field-slot "Finally" (→ `ERR_CAPACITY_EXCEEDED`), while §5's precedence catalogue enumerates field-slot conflicts before capacity (→ `ERR_FIELD_SLOT_CONFLICT`). Both readings are PRD-faithful and divergent. Scaffold rule that drove it: `priority_pair_validation_conflict` (validation-priority 10 vs 14). The unambiguous companion `test_capacity_alone_reported_when_no_slot_conflict` was retained.
- `test_record_result_with_uncompleted_booking_returns_invalid_state` (test_06) — ERROR-PRECEDENCE SILENCE. PRD §3.9 states "recording requires ... the linked booking to be `COMPLETED`" but never names the error_id for that branch; it names only `ERR_MATCH_INVALID_STATE` for record-result match-state failures. The test demanded `ERR_BOOKING_INVALID_STATE`, which the PRD never attributes to this case. Scaffold rule: `cross_entity_state_dependency/record_result_requires_booking_completed`.

**Fixes applied to test_suite/ (fixture bugs, made MORE faithful to PRD):**
- `test_08_rbac_errors_and_occ.py`, `test_confirm_with_correct_field_version_succeeds_and_bumps` and `test_confirm_with_stale_field_version_returns_412` — both captured the field `version` at field-creation, before creating the booking(s). Per PRD §2.4 ("a computed-field reconciliation ... recomputing a field's reserved headcount ... increments its version"), creating a HELD booking recomputes `reserved_headcount` and bumps `Field.version`. The captured version was therefore stale, so the confirm correctly returned `ERR_STALE_FIELD_VERSION`. Fixed both to re-read the live field version after booking creation (matching the working `create_confirmed_booking` fixture pattern), so the OCC echo reflects the version the client would actually observe.

**Fixes applied to implementation/ (boot-latency, not API behavior):**
- `start.sh` — the per-boot `python3 -c "import flask"` dependency check spawned an extra interpreter on every per-test restart; under the 8-round concurrent sweep this doubled process-spawn pressure at each test boundary and deterministically pushed one boot (always before `test_invoice_round_per_line_then_sum_pins_order`) past the runner's hard 15s restart-poll window ("could not be restarted"). Gated the check behind a one-time filesystem sentinel (`.deps_ok`) so only the first boot pays it; every later boot goes straight to `exec`.
- `app.py` `__main__` — set `app.run(threaded=True, use_reloader=False)` so the runner's readiness probe is answered without queueing behind an in-flight handler and no second interpreter is spawned. Behaviorally invisible (all mutations remain serialized by the global `db.LOCK`).

### Orchestrator independent-verification addendum:

On an independent post-Step-7 8-round lockstep sweep, one further boot-latency error surfaced: `test_immediate_visibility_of_confirm_fee_in_same_response` failed on setup ("API server ... could not be restarted", duration 15.287s = exactly the runner's 15s poll window = server never bound at all). Single-round non-concurrent run was 78/78 clean with 0 errors, confirming the implementation LOGIC is correct and the failure is pure harness boot contention: under per-test-server isolation the runner kills the previous server and immediately re-launches on the SAME port; with 8 rounds in lockstep, the just-killed predecessor's socket can still be releasing when the new boot binds → Werkzeug raises EADDRINUSE → process exits instantly → runner polls a dead port for the full 15s. 

Orchestrator fix (PRD-neutral, no API behavior change): wrapped `app.run(...)` in `app.py` `__main__` in a bounded bind-retry loop (~14s) that catches `OSError`/EADDRINUSE/EADDRNOTAVAIL and retries the bind every 0.1s instead of exiting, so the boot waits out the predecessor's port release. After this fix, TWO consecutive fully-green 8-round lockstep sweeps (16/16 rounds at 78/78 passed, 0 failed, 0 errors). Final test count: 78 (80 generated − 2 deleted). results.{1..8}.json from the final clean sweep retained in workspace/implementation/.

## Step 8: Finalize PRD — align to implementation — 2026-06-14T14:22:00.000Z

Produced workspace/PRD_FINALIZED.md. Line counts: PRD.md 304 → PRD_FINALIZED.md 304 (0% line delta; both edits in-place sentence revisions). Words 6963 → 7092 (+1.85%). 4 changed lines (2 edits).

Changes:
- §3.2 (Taking a Booking) — revise — pinned that booking-create business checks fire in narrated order (window sanity → lead-time → capacity → package-active → field-slot last), so when both capacity and field-slot are violated the result is ERR_CAPACITY_EXCEEDED, and the §5 catalogue listing order does NOT override this — routes_ext.py:238 (capacity) before :247 (field-slot). [Resolves deleted test_slot_conflict_reported_over_capacity_when_both_violated precedence contradiction.]
- §3.9 (Leagues, Rounds, Standings) — revise — pinned that all four record-result preconditions failing (match not SCHEDULED, league not OPEN, round_index mismatch, linked booking not COMPLETED) return ERR_MATCH_INVALID_STATE, including the linked-booking-not-COMPLETED branch (NOT a booking-state error) — routes_ext.py:1196. [Resolves deleted test_record_result_with_uncompleted_booking_returns_invalid_state error-id silence.]

Items intentionally NOT producing a PRD edit: the two test_08 OCC fixture fixes (field-version re-read) — already determined by PRD §2.4/§3.2 + unconditional impl bump at routes_ext.py:270; the start.sh/app.py boot fixes are infrastructure-only with no API-behavior consequence.

## Step 9: Complete PRD — eliminate residual ambiguity/mismatch — 2026-06-14T14:30:00.000Z

Produced workspace/PRD_COMPLETED.md from PRD_FINALIZED.md (full impl scan). Lines 304 → 304 (in-paragraph only); chars 48,640 → 49,958 (+1,318). 6 edits: 4 ambiguity-pins, 2 mismatch-revisions.

Changes:
- §2.3 Pagination — insert — ambiguity — out-of-range limit silently clamped (below 1→1, above 100→100), negative offset→0; non-integer limit/offset → ERR_VALIDATION — validation.py:101-125.
- §3.1 Provisioning (arena create) — insert — ambiguity — omitted timezone defaults to "UTC" — app.py:162-164.
- §3.3 Confirming — insert — mismatch — confirm additionally rejects non-ACTIVE field (ERR_FIELD_CLOSED) and non-OPEN arena (ERR_ARENA_CLOSED), booking-state checked first — routes_ext.py:309-317.
- §3.3 Check-in — insert — ambiguity — current-time outside [window_start, window_end) → ERR_BOOKING_INVALID_STATE, after the two §3.6 safety gates and checked_in_count capacity check — routes_ext.py:355-382.
- §3.8 No-show — insert — ambiguity — no-show before window_end → ERR_BOOKING_INVALID_STATE — routes_ext.py:463-465.
- §3.9 Standings — revise — mismatch — single object whose data carries standings array + current_round + league_version; each entry {team, points}; same-created_at matches in creation-sequence order — routes_ext.py:997-1037.

Verified already-consistent (no change): per-line invoice tax/rounding (§3.8), tiered ammo/settled discount (§3.5), deposit waterfall + condition downgrade (§3.4), equipment-time vs field-slot conflict + turnaround boundary (§3.2/§3.4), OCC precedence (§2.6), four record-result preconditions → ERR_MATCH_INVALID_STATE (§3.9), age/minor boundary at 18 (§3.6), *_NOT_FOUND left-to-right existence ordering (§2.5).

## PIPELINE COMPLETE — 2026-06-14T14:30:00.000Z

All Steps 1–9 executed. Final state: 78 tests, two consecutive fully-green 8-round lockstep sweeps (16/16 rounds @ 78/78 passed, 0 failed, 0 errors). Deliverables: SCAFFOLD.yaml + 2 design indices, worklog.md, test_helpers/ (8 modules), test_suite/ (8 files, 78 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (13 files + results.{1..8}.json)}.

# Worklog — task_0699_haunted_house_attraction

Scenario: 699. Haunted House & Seasonal Attraction: timed-entry & capacity/throughput, ticket tier (GA/fast-pass/VIP) & dynamic pricing, group/season pass, actor/staff scheduling & scare-zone, waiver & age/scare-level, combo (multiple attractions) & upsell, weather/closure, queue management

Difficulty: Expert (10–15 entities / 20–32 endpoints / 18–30 validations / 3+ calculations / 4+ state machines)

## Step 1: Create task directory — 2026-06-29T02:38:00.000Z

Task directory `tasks/task_0699_haunted_house_attraction` and `workspace/` subdir were pre-created by the orchestrator. Per instructions, skipped the ./tasks scan/index computation; task_dir is fixed to `tasks/task_0699_haunted_house_attraction`. No other numbered directory created or used.

## Step 2: Generate scaffold (Expert) — 2026-06-29T02:54:00.000Z

Generated three Expert-tier scaffold artifacts (SCAFFOLD.yaml 1144 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1094 lines, SCAFFOLD_CORNER_DESIGN.yaml 1220 lines). Verified: SCAFFOLD.yaml contains neither design key; DIFFICULTY/CORNER files each have their single top-level key.

Counts (Expert tier targets met):
| Dimension | Count | Expert target | Status |
|---|---|---|---|
| Entities | 13 | 10–15 | met |
| Endpoints | 50 (26 mutation + 24 read) | 20–32 | mutation surface in band; 24 reads are FK reverse-reachability / single-resource GETs the lint mandates for 13 entities |
| Validations | 20 | 18–30 | met |
| Calculations | 5 | 3+ | met |
| State machines | 7 | 4+ | met |
| Errors | 25 · Roles 4 · Concurrency rules 1 (OCC on TimeSlot.version) |

Design highlights: archetype = quota/allocation (timed-entry capacity) + pricing-engine (demand-tiered dynamic pricing); flat topology; parallel state-machine shape; peer roles. Difficulty design = all 9 §0.5 rules × 2 instances = 18 instances with executable setup_api_calls chains and pre-computed literal assertions. Corner design = 36 instances (32 active + 4 excluded_because stubs). Two non-linear machines (Reservation parallel entry×payment; Attraction/Closure cycle), depth-3 and depth-2 cascades, dual conserved-quantity invariants (slot occupancy vs wallet cents), two overlap rules (TimeSlot zero-buffer adjacency vs ActorShift 30-min rest buffer). scaffold_lint.py → clean lint (419 calls scanned; all 15 FKs have reverse-reachability). No sibling task dirs read.

## Step 3: Copy shared files — 2026-06-29T02:55:00.000Z

Copied ./INSTRUCTION.md → tasks/task_0699_haunted_house_attraction/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-29T03:00:00.000Z

Output: workspace/PRD.md (275 lines). Generated from SCAFFOLD.yaml only; neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read/opened/grepped/referenced (confirmed by subagent + grep: 0 design-key tokens in PRD). Hard-contract reports: field coverage PASS (two misses entry_status/payment_status repaired in §3.7); rule coverage PASS (20 validations via §2.11 explicit precedence; 1 OCC concurrency rule confirm+expected_time_slot_version+ERR_STALE_TIME_SLOT_VERSION/412 plus 3 additional version guards; all 7 state machines; 5 calculations dynamic_ticket_price/pass_discount/refund_credit/wallet_apply/venue_operational_state; cascades L1/L2/L3, staffing bubble, no-show, cancel returns); path-purity PASS (358 backtick tokens, 0 path/method tokens in §3). §2.2 matches reference response-structure verbatim; all 25 error IDs in narrative; PricingRule/PassProduct carry only id/created_at.

## Step 5: Generate unit tests — 2026-06-29T03:15:00.000Z

test_helpers/ (9 files): __init__.py, types.py (13 entity TypedDicts + 12 enums; PricingRule/PassProduct carry only id+created_at), api_client.py (49 endpoints), api_errors.py (25-error enum + HTTP map), assertions.py, factories.py, constants.py, test_users.py (make_guest_headers(guest_id) for entity_backed Guest role), fixtures.py.
test_suite/ (8 files): conftest.py + test_01_pricing_and_discounts, test_02_reservation_lifecycle, test_03_closures_and_cascades, test_04_admission_and_staffing, test_05_validation_and_priority, test_06_overlap_and_concurrency, test_07_crud_and_rbac.
Tests emitted: 65 — Queue A (Difficulty) 34 across 17 instances (≥2 each); Queue B (Corner) 31 across 31 non-stub instances (≥1 each). Every test carries exactly one Design: tag (65/65 audited).
Design instances SKIPPED: 2 — (1) Difficulty/cross_entity_state_dependency/cesd_attraction_reopen_requires_venue_not_severe: PRD §3.9 states the precondition but names NO error_id for the blocked case (instance asserts ERR_INVALID_STATE, not PRD-derivable). (2) Corner/cross_cutting/clock_default_makes_waiver_expiry_deterministic: instance asserts expires_at 2026-10-31 (WAIVER_VALID_DAYS=30) but PRD §3.3 says validity is fourteen days (→2026-10-15); primary asserted value contradicts PRD. 4 excluded_because corner stubs not translated (by design).

## Step 6: Generate implementation — 2026-06-29T03:15:00.000Z

implementation/ (23 files): start.sh (foreground, guarded pip, exec python3 app.py), requirements.txt (flask==3.0.3), app.py (reads $PORT, binds 0.0.0.0, foreground), db.py (in-memory dicts + logical clock default 2026-03-01T00:00:00Z, WAIVER_VALID_DAYS=14, SHIFT_REST_MINUTES=30), errors.py/response.py/middleware.py, routes/ (11 files), services/ (6 files). 50 route handlers matching PRD §4 table. Storage in-memory only, NO startup seeding (verified fresh-boot GET /attractions → total_count=0). Smoke-tested happy path, pricing bands inclusive boundaries, per-line discount rounding, OCC stale version 412, wallet refund/pass-redemption return, closure cascades, weather-SEVERE SHUTDOWN, shift overlap 30-min buffer, validation precedence. Note: mark_no_show before window_end returns ERR_INVALID_STATE (409) since ERR_OUTSIDE_ENTRY_WINDOW is scoped to admit only. Note: PRD §3.3 / db.py use WAIVER_VALID_DAYS=14 (consistent with Step 5 skip #2).

## Step 7: Run tests and iterate — 2026-06-29T03:27:00.000Z

Iterations run: 2 (initial sweep diagnosed 5 deterministic — non-flaky — failures; second sweep after deletions was fully green). Final independent confirming 8-round parallel per-test-server sweep by orchestrator: ALL 8 rounds 60/60 pass, 0 failed, 0 errors. results.{1..8}.json persisted in workspace/implementation/.

Tests deleted (5) — all PRD-First contract violations (STEP 1b unique-derivability collapse); no implementation or test_helpers changes needed (implementation was already PRD-faithful):
1. test_05_validation_and_priority.py::test_state_check_beats_age_check_on_confirm — Unconstructable precondition / precedence collapse. PRD §3.5 verbatim places the age check at ticket-add ("the bearer's guest_age must be at least the attraction's min_age, failing which the ticket is rejected with ERR_AGE_BELOW_MINIMUM"), so an under-age ticket cannot be added to build the confirm-time precedence scenario; add_ticket(guest_age=8) fails with ERR_AGE_BELOW_MINIMUM. Scaffold rule: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_business_safety_age.
2. test_05_validation_and_priority.py::test_state_failure_surfaced_ahead_of_age_leaves_reservation_cancelled — same collapse, same recipe ppvc_state_beats_business_safety_age.
3. test_05_validation_and_priority.py::test_scare_level_check_beats_capacity_check_on_confirm — Unconstructable precondition. PRD §3.5/§3.3 reject an under-scare ticket (max_scare_level=2 vs scare_level=4) at ticket-add with ERR_SCARE_LEVEL_TOO_LOW, so the confirm-time scare-vs-capacity scenario cannot be built. Scaffold rule: Difficulty/priority_pair_validation_conflict/ppvc_business_safety_scare_beats_business_fiscal_capacity.
4. test_05_validation_and_priority.py::test_scare_level_failure_pre_empts_capacity_leaves_reservation_held — same collapse, same recipe ppvc_business_safety_scare_beats_business_fiscal_capacity.
5. test_06_overlap_and_concurrency.py::test_open_closure_with_stale_attraction_version_rejected — ERROR PRECEDENCE SILENCE. Asserts ERR_STALE_ATTRACTION_VERSION on a second open_closure, but the first closure drives OPEN→PAUSED (§3.9) and PRD §2.11 orders the state gate (ERR_INVALID_STATE) strictly ahead of the stale-version guard ("a structural failure is always surfaced ahead of a business failure"); a PRD-faithful impl returns ERR_INVALID_STATE and the stale guard is unreachable. Scaffold rule: Corner/cross_cutting/occ_attraction_stale_version_on_closure.

Fixes to test_helpers/: none.
Fixes to implementation/: none — implementation already matched PRD (age/scare checked at ticket-add per §3.5; state gate ahead of stale-version guard per §2.11), which is why the unfair tests failed.

## Step 8: Finalize PRD — 2026-06-29T03:28:00.000Z

Not skipped (Step 7 had 5 deletions > 0). Outcome: PRD_FINALIZED.md is a verbatim copy of PRD.md — ZERO changes (275 lines, byte-identical; confirmed by diff). All 5 <step_7_diff> deletions analyzed and found to be test bugs against behavior PRD already uniquely determines (0 impl fixes, 0 test_helpers fixes in Step 7):
- Items 1-2 (ppvc_state_beats_business_safety_age): PRD §3.5 verbatim places age check at ticket-add; impl enforces at routes/reservations.py:126-128 → under-age ticket can't reach confirm. No patch.
- Items 3-4 (ppvc_business_safety_scare_beats_business_fiscal_capacity): PRD §3.5/§3.3 reject under-scare ticket at ticket-add (ERR_SCARE_LEVEL_TOO_LOW); impl routes/reservations.py:129-131. Scenario unconstructable. No patch.
- Item 5 (occ_attraction_stale_version_on_closure): PRD §2.11 orders ERR_INVALID_STATE ahead of stale-version guard; §3.9 closure opens only on OPEN attraction (OPEN→PAUSED); impl routes/closures.py:29-37 checks state before stale guard. No patch.
Pre-edit search confirmed confirm-time age/scare re-check (routes/reservations.py:232-242) is unreachable (no min_age/scare_level mutation endpoint) → no observable divergence requiring a pin.

## Step 9: Complete PRD — 2026-06-29T03:36:00.000Z

Always-run full PRD-vs-implementation/ scan. Source = PRD_FINALIZED.md (275 lines, 39,796 chars) → PRD_COMPLETED.md (275 lines, 41,893 chars; +2,097 chars; line count unchanged, all in-paragraph). 11 changes: 7 ambiguity-pins + 4 mismatch-revisions:
- §2.1 — insert — ambiguity — list endpoints scope Guest results to owned rows (no ERR_NOT_OWNER); added Ticket to owned-resource list — routes/{reservations,waivers,passes}.py
- §2.10 — revise — ambiguity — expected_time_slot_version is single integer, exact-equality match vs every referenced slot — routes/reservations.py:277-282
- §2.11 — revise — mismatch — slot-overlap checked before capacity/throughput — routes/time_slots.py:38-52
- §3.2 — revise — mismatch — ERR_SLOT_OVERLAP precedes ERR_CAPACITY_OVER_THROUGHPUT — routes/time_slots.py:38-52
- §3.4 — revise — mismatch — min_party persisted as supplied for any kind; SEASON never consults it — routes/passes.py:35, routes/reservations.py:322
- §3.6 — insert — ambiguity — earliest-created matching PricingRule used on duplicates; frozen price_cents=0 when no rule matches — services/reservation.py:17-22
- §3.7 — insert — ambiguity — waiver checked is reservation's owning guest_id (not per-ticket bearer) — routes/reservations.py:426-431
- §3.7 — insert — ambiguity — no-show before latest window_end rejected ERR_INVALID_STATE — routes/reservations.py:505-510
- §3.8 — revise — ambiguity — any Actor may check a shift in/out (X-User-ID not compared to actor_user_id) — routes/scare_zones.py:137-141
- §3.8 — insert — ambiguity — auto UNDERSTAFFED closure+pause cascade fires only when attraction currently OPEN — services/cascade.py:64-65
- §3.9 — insert — ambiguity — lift while weather SEVERE rejected ERR_INVALID_STATE before version guard — routes/closures.py:91-100
- §3.9 — revise — mismatch — operational_state returns to OPEN unconditionally from weather_status (not gated on open_attraction_count); CLEAR does not reopen paused attractions — services/serialize.py:18-25
(test_helpers/ and test_suite/ live at task root, not under workspace/; alignment done against implementation/.)

## Pipeline complete — 2026-06-29T03:36:00.000Z

All 9 steps done. Final state: 60/60 tests pass in all 8 parallel per-test-server rounds (results.{1..8}.json persisted). Deliverables: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, workspace/{PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, INSTRUCTION.md, implementation/}, test_helpers/, test_suite/, worklog.md.

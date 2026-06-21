# Worklog — task_0351_waterpark_admission_cabana

## Step 1: Create task directory — 2026-06-14T00:00:00.000Z

Created `tasks/task_0351_waterpark_admission_cabana/` and `tasks/task_0351_waterpark_admission_cabana/workspace/` via `mkdir -p`. Pre-allocated folder used directly (no auto-increment scan). Verified `INSTRUCTION.md` present at project root.

## Step 2: Generate scaffold (Expert tier) — 2026-06-14T00:00:00.000Z

Generated all three Expert-tier scaffold artifacts. `scaffold_lint.py` returns VERDICT: clean lint (512 calls scanned, all 18 FKs have reverse-reachability GETs).

Complexity profile: primary quota_allocation + secondary pricing_engine; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation; topology hybrid; state-machine shape parallel; role model peer_roles.

SCAFFOLD.yaml counts:
- Entities: 12 — Park, PricingPolicy, EntryWindow, Cabana, Locker, Guest, Order, Admission, CabanaRental, LockerRental, RainCheck, ClockState
- State machines: 5 — Order (parallel payment×fulfillment dims), Admission (CONFIRMED↔FROZEN freeze cycle + rain-out), CabanaRental, EntryWindow (posture gate + rain-out fan-out), RainCheck
- Concurrency rules: 2 — both OCC on EntryWindow.version (cabana-rental create, admission assign-window)
- Calculations: 5 — quote_order (max-not-stacked discounts, round-then-multiply), cabana_rental_overlap_charge (buffer-expanded intervals), locker_rental_charge (ceil hours), freeze_days_accounting (accumulating cap), band_color_assignment (height thresholds)
- Validations: 16 (priority-ordered), Endpoints: 53 (FK reverse-reachability GET mandate; includes /_clock/set_current_utc), Error catalog: 20, RBAC roles: 4 (Guest entity-backed; GateAgent/ParkManager/FinanceClerk opaque)

Design instance counts:
- §1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml: 18 instances — all 9 Difficulty Rules × 2, distinct entity domains / error-category pairs / interval semantics / conserved quantities.
- §1.9 SCAFFOLD_CORNER_DESIGN.yaml: 46 active + 3 excluded_because stubs across all 9 claim-extraction sections (entities 11, state_machines 12, calculations 4, validations 5, endpoints 3, errors 2+3 stubs, rbac 4, cross_cutting 4, consistency_model 1).

Key findings/fixes: all formula-derived asserts computed by code and pinned as literals (group subtotal 51000, max-discount 57600, mode-(b) rounding 33996, freeze 3→4 days, locker 60min→1h/61min→2h, band 107→YELLOW/122→GREEN); corrected mode-(b) rounding instance to party_size 12 so round-then-multiply order is observable; set api_prefix: / for FK reverse-reachability; added GET /pricing-policies/{id}, GET /lockers/{id}, GET /cabana-rentals; no forbidden concurrency vocabulary; all enum values have producing transitions.

## Step 3: Copy INSTRUCTION.md — 2026-06-14T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0351_waterpark_admission_cabana/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-14T00:00:00.000Z

PRD generated: `workspace/PRD.md` — 263 lines, 24 section headings. Structure: §1 Introduction, §2 Global Specifications (9 subsections: RBAC, Response Structure, Pagination, Common Resource Properties, Nested Retrieval, OCC, Derived-Field Reconciliation, Money/Time/Rounding, Validation Ordering), §3 Business Logic (9 subsections), §4 Endpoint table (53 rows), §5 Error table (20 rows).

Coverage: all 12 entities, 5 state machines, 5 calculations, 16 validations, 2 OCC concurrency rules, 53 endpoints, 20 errors, 4 roles covered. Lean entities (LockerRental, ClockState) documented as id/created_at only. All three Hard Contracts PASS (Field coverage 56/56 + 39/39 + 2/2; Rule coverage 16/16 validations, 2/2 OCC, all transitions/calcs; Path purity 0 path tokens in §3). §2.2 verbatim. Withheld design files not opened.

## Step 5: Generate unit tests — 2026-06-14T00:00:00.000Z

test_helpers/ (9 files): types.py, api_client.py (53 endpoint methods), api_errors.py (20 error ids + status map), assertions.py, factories.py, constants.py, test_users.py (opaque GateAgent/ParkManager/FinanceClerk + make_guest_headers for entity-backed Guest), fixtures.py (composite setup tiers), __init__.py.

test_suite/ (conftest + 7 test files, 82 test functions):
- Queue A (Difficulty): 36 tests, 18/18 instances each ≥2 tests
- Queue B (Corner): 46 tests, 46/46 non-stub instances each ≥1 test
Instances skipped under PRD-first filter: none — all queue-A and queue-B non-stub instances passed coverage + unique-derivability. 3 excluded_because corner stubs correctly NOT translated.

Quality gates pass: 121 PRD docstring quotes verbatim-present; every test has exactly one Design: tag resolving to a real instance; no skip/xfail; all imports resolve and modules collect cleanly. One PRD-first adjustment noted: quote_order_round_then_multiply_mode_b instance has internally inconsistent recipe — emitted one test faithful to setup_api_calls (no discount → 39996) and one reproducing intended boundary (33996, resident-eligible), both tagging the instance.

## Step 6: Generate implementation — 2026-06-14T00:00:00.000Z

Built complete Python + Flask in-memory REST API. 22 files under workspace/implementation/: start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, exec python3 app.py), requirements.txt (flask==3.0.3), app.py, db.py, errors.py, response.py, middleware.py, routes/ (parks, pricing, windows, guests, orders, admissions, rentals, rainchecks), services/ (common, serialize, calculations, lookup, windows). All 53/54 PRD §4 endpoints implemented. Smoke-tested end-to-end.

PRD ambiguities resolved by implementer:
1. Cabana-create business-check order: followed PRD §3.6 prose order (capacity → weather → overlap) over SCAFFOLD validation priorities (PRD wins).
2. Ownership (pri 3) vs existence (pri 4) on order create: ownership compares body guest_id to X-User-ID before resolving existence per §2.9; path-resource mutations resolve resource first to read guest_id.
3. ERR_WINDOW_NOT_OPEN has no explicit priority number; placed per PRD §3.4/§3.5 prose sequence.
4. Cabana/locker rental ownership not explicitly stated for rental's own guest; enforced against referenced order's guest_id for Guest role, consistent with order-ownership model.

## Step 7: Test/fix iteration loop — 2026-06-14T00:00:00.000Z

Iterations run: 2 (initial sweep surfaced 4 failures; after fixes, second 8-round sweep clean — all 8 rounds passed=80 total=80 failed=0 errors=0). Orchestrator re-ran an independent final 8-round sweep: all 8 rounds passed=80/80.

Tests deleted (PRD-silence category):
1. test_weather_hold_beats_capacity_on_cabana_rental — ERROR PRECEDENCE SILENCE. Asserted ERR_WEATHER_HOLD fires before ERR_WINDOW_CAPACITY_EXCEEDED when a cabana rental hits both a full window and a STORM_WATCH park. PRD names both errors individually but never orders them; PRD §3.6 prose presents capacity first and weather as a "further" guard, so a faithful PRD-only implementer emits ERR_WINDOW_CAPACITY_EXCEEDED (what impl does). Precedence traces only to SCAFFOLD_DIFFICULTY_DESIGN.yaml priority numbers (weather=14, capacity=15). Two divergent PRD-faithful impls exist → deleted per STEP 1b. Scaffold rule: priority_pair_validation_conflict/weather_hold_beats_capacity_on_cabana_rental.
2. test_weather_hold_beats_capacity_under_rained_out_park — same ERROR PRECEDENCE SILENCE pattern (RAINED_OUT variant of the identical scaffold rule).

Fixes applied to test_helpers/: none.
Fixes applied to test_suite/: none beyond the 2 deletions above.

Fixes applied to implementation/:
- workspace/implementation/start.sh — replaced per-boot `python3 -c "import flask"` probe with a cheap filesystem sentinel check (.deps_installed). Under 8x-concurrent per-test-server isolation, spawning an extra Python interpreter on every reboot doubled process-spawn pressure and produced flaky "could not be restarted" boot-timeout setup errors (test_assign_window_stale_version_rejected 5/8, test_create_park_returns_201_with_defaults 2/8 in initial sweep). Sentinel is a build marker, not entity data — does not violate in-memory-only storage rule. Environmental boot-latency artifacts, not logic failures. No business-logic checks weakened or removed; capacity-before-weather ordering left intact as PRD-faithful behavior.

Final test count: 80 (was 82; 2 deleted).

## Step 8: Finalize PRD — 2026-06-14T00:00:00.000Z

PRD_FINALIZED.md written (NOT skipped — Step 7 had 2 deletions + 1 impl fix). Line counts: PRD.md 263, PRD_FINALIZED.md 263 (0% line-count change; 1 line revised in place ≈ 0.4%).

Changes (1):
- §3.6 (Cabana Rentals) — revise — pinned relative precedence of the three cabana-rental business guards: window-capacity (ERR_WINDOW_CAPACITY_EXCEEDED) first, weather (ERR_WEATHER_HOLD) second, time-overlap (ERR_CABANA_OVERLAP) third. PRD named all three errors but never ordered capacity vs weather; impl checks capacity before weather (routes/rentals.py:59-64).

Step 7 items dispositioned: deleted-test items 1 & 2 = genuine PRD-silence on weather-vs-capacity precedence, now pinned to impl's capacity-first ordering. start.sh boot-probe change = pure environmental/boot-latency fix governed by INSTRUCTION.md, no API behavior, no PRD edit.

Pre-edit search log: subject = relative eval order of the three errors in cabana-rental create; enumerated errors.py:36-37, routes/rentals.py:52-80 (only path where capacity+weather coexist), routes/admissions.py:106-108 + 211-213 (capacity-only, no weather); wording scoped explicitly to "a cabana-rental request" so the ordering claim does not bleed onto admission assign-window/unfreeze capacity checks (which have no weather guard).

## Step 9: Complete PRD scan — 2026-06-14T00:00:00.000Z

PRD_COMPLETED.md written (always runs). Source PRD_FINALIZED.md (263 lines, 40,739 chars) → PRD_COMPLETED.md (263 lines, 41,176 chars). Char delta +437; line count unchanged (all in-paragraph inserts). Counts: ambiguity-pins 3, mismatch-revisions 0.

Walked all 8 route modules + 5 service modules + db/response/middleware/errors exhaustively. Most impl behavior already uniquely pinned (money/rounding, validation ordering §2.9, OCC §2.6, freeze-day accounting, cabana-overlap buffer math, locker billing, capacity "strictly less", cascades, field shapes). 3 genuine silences pinned:
- §3.4 — insert — ambiguity — check-in while logical clock never set (current_utc null) → ERR_WINDOW_TIME_VIOLATION (routes/admissions.py:139-142).
- §3.5 — insert — ambiguity — unfreeze rejects with ERR_WINDOW_NOT_OPEN when window not OPEN/RESTRICTED (or missing); PRD named only the capacity error (routes/admissions.py:206-210).
- §3.8 — insert — ambiguity — rain-out rejects with ERR_INVALID_STATE when park weather_status not RAINED_OUT or window status neither OPEN nor RESTRICTED (routes/windows.py:86-91).

No change needed: §3.6 "to or beyond capacity" already bound to §3.4 strict rule; freeze/unfreeze error ordering governed by §2.9; OCC-before-business ordering pinned by §2.6+§2.9.

## Pipeline complete — 2026-06-14T00:00:00.000Z

All 9 steps complete. Final independent 8-round parallel sweep: all 8 rounds passed=80 total=80 failed=0 errors=0. Deliverables: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design indices), workspace/PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (conftest + 7 files, 80 tests), workspace/implementation/ (Python+Flask, 22 files, results.{1..8}.json all passing).

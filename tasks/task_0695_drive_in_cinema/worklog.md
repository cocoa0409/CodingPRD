# Worklog — task_0695_drive_in_cinema

Scenario: Drive-In & Outdoor Cinema: showtime & lot/stall capacity, per-car vs per-person pricing, FM-audio & concession pre-order, reservation & gate scan, double-feature scheduling, weather/refund, private-rental/event, season pass

Difficulty: Expert (passed to Step 2 scaffold generator only)

## Step 1: Create task directory — 2026-06-28T15:32:36.000Z

Pre-assigned folder used directly (no ./tasks scan, no index recompute). Created tasks/task_0695_drive_in_cinema/workspace.

## Step 2: Generate scaffold (Expert) — 2026-06-28T15:49:57.000Z

All three scaffold artifacts are generated, internally consistent, and pass `scaffold_lint.py` cleanly.

Generated the Expert-difficulty scaffold for the Drive-In & Outdoor Cinema scenario. All three files written to `/home/ubuntu/github/CodingPRD/tasks/task_0695_drive_in_cinema/`:
- SCAFFOLD.yaml (§1.0–§1.7, no design keys)
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (single key scaffold_difficulty_design)
- SCAFFOLD_CORNER_DESIGN.yaml (single key scaffold_corner_design)

Counts (Expert band):
- Entities: 12 (band 10–15) — Venue, Lot, Film, Showtime, FmChannelAssignment, SeasonPass, Reservation, ConcessionItem, ConcessionOrder, PrivateRental, WeatherEvent, RefundRecord. Topology flat (FK-linked peers).
- Endpoints: 45 — above the 20–32 guideline; non-GET surface is 26 (every entity create + all lifecycle transitions across 5 state machines + logical-clock test endpoint); remaining GETs are FK reverse-reachability paths or cited by test recipes. Kept surface complete per §0.4 ("difficulty comes from coupling, not count").
- Error codes: 22 (band 18–30).
- Calculation variants: 7 across 4 calculations (band 3+): reservation_pricing (3: per-car tiered, per-person, season-pass), refund_amount (2: weather pro-rata vs voluntary policy-tier), concession_order_total (1: per-line tax rounding), private_rental_quote (1: ceil-hours).
- State machines: 5 (band 4+) with non-linear dimensions: Reservation — parallel (occupancy_status × payment_status); Showtime — cyclic (SCHEDULED ↔ WEATHER_HOLD); PrivateRental — branching (REQUESTED → {APPROVED, REJECTED}); ConcessionOrder (linear-with-revert); SeasonPass (lifecycle with revoke). Plus 2 OCC concurrency_rules (Showtime version on reservation create; PrivateRental version on approve).

Difficulty design: all 9 §0.5 rules × 2 instances = 18 instances; formula-derived asserts pre-computed as literals (per-car 5300, per-person 5100, promo-net 4590, weather refund 2650/2550, concession total 3000 / per-line-vs-sum divergence 1178, rental 230000/210000).
Corner design: 47 instances across 9 claim-extraction-guide sections (42 active + 5 excluded_because stubs).
Lint: VERDICT clean — 395 calls scanned, all conform to §1.5 (a–e) and all 12 entities' FKs reverse-reachable (f).

## Step 3: Copy INSTRUCTION.md — 2026-06-28T15:50:00.000Z

Copied ./INSTRUCTION.md → tasks/task_0695_drive_in_cinema/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-06-28T15:55:15.000Z

Output: workspace/PRD.md (279 lines), written and verified. Generated from SCAFFOLD.yaml only; both design files withheld (not opened).

Sections covered:
- Entities (12): Venue, Lot, Film, Showtime, FmChannelAssignment, SeasonPass, Reservation, ConcessionItem, ConcessionOrder, PrivateRental, WeatherEvent, RefundRecord — fields scattered through §3. §2.4 calls out lean entities (Film, WeatherEvent, RefundRecord carry only id/created_at, no updated_at/version).
- State machines: Reservation parallel (occupancy_status × payment_status); Showtime cyclic SCHEDULED↔WEATHER_HOLD + terminal CANCELLED/COMPLETED; PrivateRental branching; ConcessionOrder linear-with-revert; SeasonPass revocation — every transition with from/to, preconditions, side-effects, incl. depth-3 cascades (reservation cancel, weather cancellation).
- Calculations (4): reservation pricing (3 variants: per-car, per-person, season-pass), refund (dual-variant weather pro-rata vs voluntary tier with 48h/24h/2h boundaries at 100/50/25/0%), concession total (per-line tax rounding then single 5% service-fee round), private-rental quote (ceil to whole hours) — precise business prose, no pseudocode/fuzzy words.
- Validations: all 16 priority-ordered checks; §2.7 states precedence explicitly.
- Endpoints: §4 4-column table covering all 46 endpoints incl. /_clock/set_current_utc.
- Errors: §5 2-column table with all 22 error IDs; each also surfaces in §2/§3 narrative.
- Roles/RBAC: §2.1 names 4 roles (PlatformAdmin, VenueOperator, GateAttendant, Patron); Patron X-User-ID matched to patron_id for ownership → ERR_NOT_RESOURCE_OWNER.

Hard contracts: Contract 1 (Field-Name Coverage) PASS (69 fields verbatim); Contract 2 (Rule Coverage) PASS (both OCC rules, validation priority, both refund variants, per-line-vs-sum rounding, depth-3 cascades); Contract 3 (§3 Path Purity) PASS (0 paths/methods in §3 backticks).

## Step 5: Generate unit tests — 2026-06-28T16:08:32.000Z

Test files: 6 (78 tests total)
- test_01_pricing.py — 10 tests (per-car/per-person/season-pass pricing, concession totals, rental quotes)
- test_02_refunds_cascades.py — 7 tests (dual-variant refunds, depth-3 cascades, weather pro-rata)
- test_03_state_machines.py — 14 tests (cyclic showtime, parallel reservation dimensions, transitions, gate/no-show preconditions)
- test_04_validations_precedence.py — 23 tests (priority-pair conflicts, capacity boundaries, cross-entity guards, temporal overlaps, validation violations)
- test_05_invariants_concurrency.py — 11 tests (conserved-quantity restore, OCC stale-version, derived-count reconciliation, FM channel, cascading lot status)
- test_06_entities_rbac.py — 13 tests (CRUD, defaults, system/type/parent constraints, immutability, RBAC denials/ownership)

Coverage by queue: Queue A (Difficulty) 36 tests — all 18 instances across 9 rules have ≥2 tests; Queue B (Corner) 42 tests — all 42 non-stub instances ≥1 test.
Instances skipped: 5 — all excluded_because: stubs (queue B), correctly NOT translated (cited difficulty instance owns the assertion); all 5 cross-refs resolve to real difficulty instances. No instances dropped for PRD-coverage failures.
test_helpers/ files (9 + conftest): __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py + test_suite/conftest.py.
Validation: all 78 tests collect; every test has exactly one verbatim Design: tag resolving to a real instance; all 88 PRD citations verbatim-present; no skip/xfail; pyflakes-clean. Film/WeatherEvent/RefundRecord TypedDicts omit version/updated_at; make_patron_headers threads owning patron_id into X-User-ID.

## Step 6: Generate implementation — 2026-06-28T16:08:32.000Z

Implementation in workspace/implementation/. Source files: start.sh (foreground launcher, executable), requirements.txt (flask>=2.0), app.py (entry + 46 routes, state machines, cascades, validation ordering, error handlers), db.py (in-memory store, starts empty), clock.py (logical clock, defaults 2026-03-01T00:00:00Z each boot), errors.py (ApiError + 22 error_id/HTTP-status pairs), response.py (meta/response_type/data envelope, pagination, ERR_VALIDATION_LIMIT), auth.py (X-User-ID/X-User-Role + RBAC 4 roles), serializers.py (lean common-fields honored), calculations.py (pricing 3 variants, dual-variant refunds, concession totals, rental ceil — Decimal ROUND_HALF_UP), util.py, validate.py, entitytools.py.
Storage: in-memory dicts keyed by id, monotonic seq for creation-order sort; no SQLite/disk/seeding; resets each boot (fresh boot total_count 0).
start.sh: cd to script dir; guarded pip install (no-op if flask present); exec python3 app.py. app.py reads int(os.environ.get("PORT","10000")), app.run(host="0.0.0.0", port=port, threaded=True); foreground via exec, SIGTERM propagates.
Verification: 4 functional suites (~94 assertions) passing against live server. Design note: expected_*_version treated as required integer fields (400 well-formedness before 412 OCC) per §2.7 rejection order.

## Step 7: Run tests and iterate to green — 2026-06-28T16:17:33.000Z

Clean: 76 test functions remain, both state_beats_fiscal tests gone. The 8-round parallel sweep is fully green.

Iterations run: 2 (initial diagnostic sweep + one fix iteration, both 8-round parallel).
Initial state: 9 tests failed deterministically in all 8 rounds (69/78 passing). Three distinct root-cause clusters.

Tests deleted (2):
- test_state_beats_fiscal_on_cancelled_full_showtime and test_state_beats_fiscal_showtime_is_cancelled_precondition (both in test_suite/test_04_validations_precedence.py) — PRD-SILENCE + broken unique derivability (ERROR-PRECEDENCE / state-machine-precondition collapse). They assert ERR_INVALID_STATE when creating a reservation against a CANCELLED showtime, claiming state-check beats ERR_LOT_FULL. Cited §2.7 only orders checks that exist; reservation-create rules (§3.4) enumerate every applicable check (OCC, pass validity, redemption budget, lot-full, person-capacity) and state NO showtime-status precondition for create — unlike check-in/cancellation (§3.5) which explicitly name required showtime statuses. A faithful PRD-only implementer would not reject the create, so the assertion isn't uniquely derivable. Driven by scaffold-only validations[priority=6] "state" rule (Difficulty/priority_pair_validation_conflict/state_beats_fiscal_lot_full_on_cancelled_showtime), never in PRD prose.

Fixes applied to test_suite/ (3 tests, check-in window precondition): all three set the logical clock too early relative to PRD §3.5 check-in window (opens 60 min before start_utc), making a PRD-faithful server correctly emit ERR_CHECKIN_WINDOW_CLOSED. Moved each clock into the window:
- test_03_state_machines.py::test_reservation_parallel_dimensions_checkin_and_paid — clock 2026-06-20T00:00:00Z → 01:30:00Z (start 02:00:00Z).
- test_04_validations_precedence.py::test_concession_fulfill_requires_reservation_scanned — clock 2026-06-30T00:00:00Z → 01:30:00Z (start 02:00:00Z).
- test_04_validations_precedence.py::test_concession_fulfill_succeeds_after_reservation_scanned — clock 2026-06-30T00:00:00Z → 02:30:00Z (start 03:00:00Z).

Fixes applied to implementation/ (1):
- workspace/implementation/app.py, create_reservation() — removed an over-strict, non-PRD-derivable pass-validity check (sp.valid_from <= clock.now() <= sp.valid_to). PRD defines the redemption validity-window condition solely as "the screening's start_utc is on or before valid_to_utc" (§3.4 and §3.11); it never requires the current clock to fall within the window. The over-strict check broke 4 season-pass tests whose setups (clock in June, pass valid in August, screening in August) are PRD-consistent. Retained showtime.start_utc > valid_to_utc → ERR_PASS_INVALID check still satisfies test_pass_invalid_outside_validity_window.

Final sweep confirmation: all 8 parallel rounds passed == total at 76/76 (78 original − 2 deleted), failed=0 errors=0 in every round. No flakiness. (Orchestrator re-verified all 8 results.N.json: round 1–8 each passed=76 total=76 failed=0 errors=0.)

## Step 8: Finalize PRD — 2026-06-28T16:20:24.000Z

Done. PRD_FINALIZED.md complete with exactly one minimal edit.
Line counts: PRD.md = 279; PRD_FINALIZED.md = 279 (one in-place line revision, ~0% delta; +3 sentences within §3.4).

Changes (one):
- §3.4 — insert (within existing line) — added a clarifying clause pinning that the season-pass "validity window" condition collapses to a single test: the screening's start_utc ≤ valid_to_utc, and that neither valid_from_utc nor the logical clock is compared against the window. — implementation/app.py:607-618 (only if st["_start_dt"] > sp["_valid_to_dt"] is checked; _valid_from_dt stored but never used).

Mapping each step_7_diff cluster:
- Cluster 1 (deleted tests — reservation create vs CANCELLED showtime): PRD §3.4 already enumerates create-time checks with no showtime-status precondition; create_reservation() (app.py:575-660) has none. PRD already matches impl → no edit.
- Cluster 2 (fixture fixes — check-in window): pure test-clock bugs. PRD §3.5 already pins the 60-min window; impl matches (app.py:727-728). No edit.
- Cluster 3 (impl fix — removed over-strict pass-validity clock check): genuine PRD ambiguity. Original "within its validity window" phrasing invited a clock/valid_from-based check; pinned the sole operative condition to match impl. This is the only edit.

Pre-edit search log: subject = season-pass validity-window condition at reservation create (ERR_PASS_INVALID window clause); enumerated grep valid_from|valid_to|validity|window across *.py, create_reservation block (app.py:607-621), create_season_pass storage (app.py:962-982), serializers.py:96-97, confirmed _valid_from_dt stored but referenced nowhere, no clock-vs-window comparison anywhere, cross-checked §3.11 (already consistent); wording adjustment = reverted a first-draft removal of owner clauses (out of scope) to keep edit purely additive, all other clauses byte-identical.

## Step 9: Complete PRD — 2026-06-28T16:26:17.000Z

Done. PRD_COMPLETED.md produced as a minimal patch over PRD_FINALIZED.md.
Source vs output: both 279 lines; chars 43,267 → 45,011 (+1,744). All in-paragraph inserts/revisions; no new sections/paragraphs.
Counts: 7 ambiguity-pins, 1 mismatch-revision (8 edited lines).

Per-change list:
- §2.2 (api_request_timestamp) — insert — ambiguity — api_request_timestamp drawn from real server wall-clock, independent of the logical clock — response.py:30.
- §2.3 (Pagination) — insert — ambiguity — non-integer-parseable limit/offset also yields ERR_VALIDATION_LIMIT — response.py:84-85,93-94.
- §2.4 (Common Properties) — insert — ambiguity — created_at/updated_at stamped from logical clock's current value, not wall-clock — entitytools.py:26-31, clock.py:13.
- §3.4 (Reservation create, request) — insert — ambiguity — supplied patron_id must equal caller's X-User-ID else ERR_NOT_RESOURCE_OWNER; ownership check runs after showtime/season-pass existence — app.py:582-594.
- §3.4 (Reservation create, pass rules) — revise — mismatch — PRD listed "wrong owner" under ERR_PASS_INVALID (422); impl raises ERR_NOT_RESOURCE_OWNER (403) for a pass not owned by caller; revised accordingly — app.py:608-610 vs 611-618.
- §3.5 (No-show sweep) — insert — ambiguity — showtime updated_at/version advance once per swept reservation (no-flip sweep leaves untouched); endpoint returns swept showtime object — app.py:530-550, 556-561.
- §3.9 (FM Channel Assignment) — insert — ambiguity — "time-overlapping" = half-open [start,end) (shared endpoint doesn't overlap); only ACTIVE assignments occupy a frequency (RELEASED free) — app.py:383-398, 85-87.
- §3.10 (Weather event) — insert — ambiguity — features_remaining outside absolute [0,2] is ERR_INVALID_REQUEST (400) while narrower per-showtime bound is ERR_WEATHER_FEATURES_INVALID (422) — app.py:454 vs 469-471.
Notes: PRD already uniquely pins the bulk of impl (pricing variants, refund tiers, overlap+buffer, cascade depth, OCC ordering, error catalogue, envelopes). §3.4 "must omit vehicle-only fields" left as-is (vacuous; impl enforces nothing). Tests used only as cross-reference.

## Pipeline complete — 2026-06-28T16:26:17.000Z

All 9 steps finished. Final 8-round parallel sweep green at 76/76 (failed=0 errors=0 each round). Deliverables present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/, test_suite/ (76 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.

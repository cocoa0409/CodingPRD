# Worklog — task_0359_amusement_park_ride_virtual_queue

## Step 1: Create Task Directory — 2026-06-14T18:24:28.000Z

Used pre-assigned directory `tasks/task_0359_amusement_park_ride_virtual_queue` (no scan/auto-increment). Directory and `workspace/` already existed. Difficulty target: Expert.

## Step 2: Generate Scaffold — 2026-06-14T18:42:44.000Z

Generated a complete Expert-difficulty scaffold at `tasks/task_0359_amusement_park_ride_virtual_queue/`. All three files pass `scaffold_lint.py` cleanly (367 calls scanned, 0 violations).

**Complexity profile:** Quota/allocation primary + Temporal-windowing secondary; layers = optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers. Topology hybrid, state-machine shape compound, role model peer_roles, consistency immediate. (`api_prefix: /` because the domain is a flat multi-collection surface — `/parks`, `/rides`, `/reservations`, etc.)

**SCAFFOLD.yaml (§1.0–§1.7):**
- **10 entities:** Park, Ride, ReturnWindow, Guest, Party, PartyMembership, EntitlementPlan, GuestDayTicket, Reservation, LightningLanePurchase.
- **6 state machines:** GuestDayTicket (linear), Ride (branching OPEN↔DOWN→CLOSED), ReturnWindow (cyclic OPEN↔EXHAUSTED, +SUSPENDED/EXPIRED), Reservation (cyclic BOOKED↔REDISTRIBUTED, multi-exit), Party (cyclic FORMING↔LOCKED→DISBANDED), LightningLanePurchase. Plus **2 concurrency rules** (OCC on ReturnWindow.version for booking, Party.version for party-book).
- **4 calculations:** return_window_slot_capacity (threshold/floor), lightning_lane_price (tiered surge + cap, dual-variant), posted_wait_estimate (aggregation, dual-variant), max_concurrent_hold_check (aggregation).
- **14 validations** (priority-ordered, auth→existence→ownership→state→OCC→safety→temporal→constraint→fiscal→capacity).
- **48 endpoints** (incl. 6 added during lint iteration for FK reverse-reachability, plus `/_clock/set_current_utc` test-driving endpoint).
- **18 error codes.**
- **3 roles:** ParkAdmin (opaque), RideOperator (opaque), GuestApp (entity_backed:Guest).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rule_ids × 2 = **18 instances**, each with executable setup_api_calls chains, OCC versions via `${var}` captures, formula-derived asserts pre-computed as literals.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** 9 sections, **39 instances total — 37 active + 2 `excluded_because` stubs** (both resolving to valid §1.8 instance names). Covers creation/required-fields/computed/not-found, invalid-transition/terminal-lockdown, calc correctness/boundaries, validation triggers, RBAC denials, OCC, redistribution cascade, threshold boundaries, immediate-consistency.

## Step 3: Copy Shared Files — 2026-06-14T18:43:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-14T18:48:20.000Z

Generated `workspace/PRD.md` — **274 lines**. Major sections: §1 Introduction; §2 Global Specifications (RBAC w/ 3 roles, fixed response envelope, pagination, common props, logical clock & temporal windowing, hierarchical-consistency cascades, OCC dual guards → ERR_STALE_VERSION 412, capacity/day-phase derivation, precision/rounding floor/ceil/cap-then-round-half-up, existence/nested-path validation, 14-rung validation priority ordering); §3 Business Logic (8 lifecycle subsections — park/inventory setup, guests+tickets+gate, VQ booking/holding, redemption & window lifecycle, parties & group booking, Lightning Lane surge pricing, ride breakdown/redistribution/restoration, posted-wait computation; all formulas in prose with constants); §4 Endpoint Definitions (48 endpoints); §5 Error Code Catalogue (18 error IDs). Hard Contracts all PASS (field-name coverage, rule coverage, §3 path purity). Confirmed: did NOT read either withheld design file.

## Step 5: Generate Unit Tests — 2026-06-14T19:06:26.000Z

Generated test infrastructure (`test_helpers/` — 9 modules: __init__, api_client, api_errors, assertions, constants, factories, fixtures, test_users, types) + test suite (`test_suite/` — conftest + 8 test files, **73 test functions**). Queue A (Difficulty): all 18 instances translated, 2 tests each = 36 tests, 0 skipped. Queue B (Corner): all 37 non-stub instances translated, 1 test each = 37 tests, 0 skipped. The 2 `excluded_because:` stubs correctly NOT translated (cross-refs resolve to real difficulty instances). Every test carries exactly one `Design:` tag resolving to a real instance; every cited PRD sentence verified verbatim. No design-index instances required skipping (PRD §2.11 states full validation priority order incl. height-vs-exhaustion precedence example).

## Step 6: Generate Implementation — 2026-06-14T19:06:26.000Z

Built Python + Flask implementation at `workspace/implementation/`. Files: start.sh, requirements.txt (flask==3.0.3), app.py, db.py (10 in-memory dicts), errors.py (18 error ids), response.py, middleware.py (X-User-ID/X-User-Role auth + RBAC), serialize.py, validate_input.py, domain.py (calculations), booking.py, lookups.py, routes/ (parks, rides, guests, parties, plans, reservations — ~50 endpoints). start.sh: `set -euo pipefail`, guarded dep install, `exec python3 app.py` binding `0.0.0.0:$PORT` (default 10000), threaded=True. Storage in-memory only, no seeding/preloading. Validated end-to-end against live server (envelopes, pagination, auth/RBAC/ownership, 14-priority validation ordering, dual-variant LL pricing, day-phase/capacity, window exhaust/unexhaust, declare-down→restore→redistribute incl. ERR_NO_REPLACEMENT_WINDOW, advance-windows forfeit cascade, close-ride cascade, redeem temporal window, SINGLE_RIDER, clean boot). NOTE: impl-gen reported cross-checking child/parent version-lockstep semantics against design scaffolds — Steps 8/9 will reconcile PRD wording to actual impl behavior.

## Step 7: Run Tests and Iterate — 2026-06-14T19:14:30.000Z

**Iterations run:** 2 sweeps (baseline + 1 fix iteration). Final state: all 8 parallel rounds green, **71/71 passing** in every round, no flakiness. (Orchestrator re-ran a fresh independent 8-round sweep afterward to regenerate results.{1..8}.json — all 8 rounds 71/71, 0 failures, confirming non-flaky.)

The baseline showed 4 deterministic failures (identical across all 8 rounds): two `advance_windows` TypeErrors, one redistribute error-vs-success mismatch, one unconstructible-precondition setup failure.

### Tests deleted (2)

1. **`test_redistribute_with_no_replacement_window_reports_unplaced`** (test_03) — STEP 1b **ERROR-vs-SUCCESS ambiguity / unique-derivability collapse**. PRD §3.7 says both "the redistribute call surfaces `ERR_NO_REPLACEMENT_WINDOW` for the unplaced reservations" (catalogue maps to HTTP 409) **and** "The response reports the count of re-homed reservations, the list of re-homed reservation identifiers, and the list of any unplaced reservation identifiers." Two PRD-faithful implementations are articulable: (i) return 409 error when any reservation is unplaced; (ii) return 200 with a body carrying `rehomed_count`/`unplaced_reservation_ids`. The implementation chose (i); the test asserts (ii). PRD does not uniquely determine the outcome. Scaffold rule: `Corner/state_machines/redistribute_with_no_replacement_window_reports_unplaced`.

2. **`test_redeem_invalid_state_beats_height`** (test_05) — STEP 1b **unconstructible-precondition collapse**. The priority-pair (redeem `ERR_INVALID_STATE` priority-5 beats `ERR_HEIGHT_REQUIREMENT_NOT_MET` priority-7) requires a reservation that is simultaneously non-`BOOKED` and owned by a short guest. PRD §3.3's height gate ("The guest must clear the height requirement…") is **unscoped by queue_type** — only the final exhaustion gate is scoped to `VIRTUAL_QUEUE` — so booking blocks a short guest for both `VIRTUAL_QUEUE` and `SINGLE_RIDER`. There is **no PRD endpoint to mutate a ride's `min_height_cm`** after creation, so no short guest can ever come to own a reservation. The fixture's premise ("SINGLE_RIDER bypasses the booking-time height check") contradicts PRD; the scenario is unreachable under any PRD-faithful sequence. The covered half (state-check fires at redeem) is still exercised by the sibling `test_redeem_invalid_state_alone_fires_when_height_ok`, which uses a tall guest and passes. Scaffold rule: `Difficulty/priority_pair_validation_conflict/redeem_invalid_state_beats_height_on_reservation`.

### Fixes applied to `test_suite/` (2 — test bugs)

- **`test_08_difficulty_companions.py`** (`test_advance_windows_reports_forfeited_reservation_id`) and **`test_03_cascades_and_breakdowns.py`** (`test_window_expiry_forfeits_reservation_and_recomputes_wait`): both called `api.advance_windows(park["id"])` without the required `headers` argument, raising `TypeError`. PRD's endpoint table mandates `POST /parks/{id}/advance-windows` is ParkAdmin-authorized; added the existing `ADMIN` header constant → `api.advance_windows(park["id"], ADMIN)`. Also removed the now-unused `setup_redistributed_single_window` import from test_03.

### Fixes applied to `test_helpers/`

None.

### Fixes applied to `implementation/`

None. The implementation was already PRD-faithful on every contested point (height gate unscoped across both queue types per §3.3; redistribute returning 409 on unplaced reservations per §3.7 + error catalogue; advance-windows as a ParkAdmin endpoint per §3.4).

## Step 8: Finalize PRD — 2026-06-14T19:19:12.000Z

Produced `workspace/PRD_FINALIZED.md` (274 lines; 2 single-line paragraphs revised in place, 0 net line delta). Changes:
- **§3.7 (Redistribution) — revise** — pinned redistribute outcome on unplaced reservations: reservations processed in ascending creation order; if any remain unplaced after the pass the call fails `ERR_NO_REPLACEMENT_WINDOW` (HTTP 409) while already-committed placements persist; success body (counts/lists) returned only when every reservation re-homed. (`routes/rides.py:229-263`). Resolves the PRD self-contradiction (error-vs-success) that drove the test_03 deletion.
- **§3.3 (Booking gates) — revise** — scoped gates per `queue_type`: height + accessibility apply to any reservation create (both queue types); temporal/peak/VQ-ceiling/exhaustion gates apply only to `VIRTUAL_QUEUE`. (`routes/reservations.py:51-68`). Resolves the unscoped-height ambiguity that drove the test_05 deletion.
- Advance-windows header item (Step 7 fix 3) was a pure test bug — PRD §3.4 + endpoint table already mandate ParkAdmin auth; no PRD edit needed.

Pre-edit NO-NEW-MISMATCH search performed for both edits (enumerated redistribute endpoint + `_select_replacement_window` + `_seq` ordering; and `create_reservation`/`booking.py`/`party_book`/`create_purchase` gate paths) — wording scoped so it stays consistent with party-book and LL-purchase height/accessibility paths.

## Step 9: Complete PRD — 2026-06-14T19:26:52.000Z

Produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md` (274→274 lines, +4763 chars; all in-paragraph inline edits, no new sections/rows). **ambiguity-pins: 9; mismatch-revisions: 2.** Changes:
- §4 Endpoint Definitions — revise — mismatch — admit/exit/party-book return **201** (not 200); other transitions stay 200 (`routes/parks.py:78,101`, `routes/parties.py:300`).
- §3.4 advance-windows — insert — ambiguity — pinned response fields `expired_window_count`/`forfeited_reservation_ids` (`routes/parks.py:147-150`).
- §3.7 redistribute — revise — ambiguity — pinned response fields `rehomed_count`/`rehomed_reservation_ids`/`unplaced_reservation_ids` (`routes/rides.py:259-263`).
- §3.5 party-book — revise — ambiguity — pinned response fields `created_reservation_ids`/`skipped_guest_ids` (`routes/parties.py:300-304`).
- §3.5 party-book — insert — ambiguity — pinned atomic-over-eligible-set semantics + exhaustion arithmetic + park-scope `ERR_GUEST_PARK_MISMATCH` (`routes/parties.py:240-288`).
- §3.3 reservation create — insert — ambiguity — pinned ownership (`X-User-ID==guest_id`→`ERR_NOT_RESOURCE_OWNER`) + park-scope (`routes/reservations.py:35-43`).
- §3.3 VQ-create side effects — insert — ambiguity — pinned created VQ reservation `version`/`updated_at` mirror target window's post-debit values; SINGLE_RIDER keeps version 1 (`booking.py:90-91,106`).
- §3.5 party create — insert — ambiguity — pinned leader-ownership + leader park-scope (`routes/parties.py:36-40`).
- §3.5 add/unlink member — insert — ambiguity — pinned add-member FORMING requirement + park-scope; membership `version` mirrors `Party.version`; leader-removal precedence; missing LINKED → `ERR_NOT_FOUND` (`routes/parties.py:111-135,184-194`).
- §3.6 purchase create — insert — ambiguity — pinned ownership ordering + guest/ride/plan park-scope (`routes/plans.py:74-83`).
- §2.5 logical clock — insert — ambiguity — pinned `to_iso8601` stored verbatim as `current_utc`, set-clock returns updated Park, `current_utc` a Park read field (`routes/parks.py:163-165`, `serialize.py:12`).
- §3.2 ticket issue/admit/exit — insert — ambiguity — pinned issue park-scope; admit/exit ticket-park-scope ordering; not-ISSUED & date-mismatch → `ERR_INVALID_STATE` (not-ISSUED first) (`routes/guests.py:84-85`, `routes/parks.py:60-67,90-94`).

## Pipeline Complete — 2026-06-14T19:26:52.000Z

All 9 steps finished. Final state: **71/71 tests passing across all 8 parallel stability rounds, 0 failures, no flakiness.** Deliverables present: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 modules), test_suite/ (conftest + 8 files, 71 functions), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (+ results.{1..8}.json)}.

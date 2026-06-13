# Worklog — task_0217_restaurant_reservation_waitlist

Scenario: Restaurant Reservation & Waitlist (OpenTable style): table inventory/turn time, party-size matching, reservation slots/pacing, waitlist & SMS notify, deposit/credit-card hold, no-show/cancellation policy, special requests, large-party/private dining

Difficulty target (Step 2 only): Expert

## Step 1: Create task directory — 2026-06-07T00:00:00.000Z

Created `tasks/task_0217_restaurant_reservation_waitlist/` with `workspace/` subdirectory (pre-allocated path, index-scan skipped per orchestration args).

## Step 2: Generate scaffold (Expert) — 2026-06-07T00:01:00.000Z

Generated the three-file Expert-tier scaffold for **Restaurant Reservation & Waitlist (OpenTable style)**. All three pass `scaffold_lint.py` with `VERDICT: clean lint` (479 §1.8/§1.9 calls verified against §1.5; all FKs reverse-reachable). No sibling task was inspected.

**Files**
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Complexity profile**: primary archetype `temporal_windowing` + secondary `quota_allocation`; flat topology; cyclic state-machine shape; peer-roles; immediate consistency. Layers: optimistic concurrency, cascading side effects, rate/threshold triggers, dual-variant calculation.

**Scaffold contents**
- **Entities: 11** — Restaurant, DiningArea, Table, ServicePeriod, Customer, Reservation, WaitlistEntry, DepositHold, SpecialRequest, Notification (polymorphic subject), PrivateDiningEvent. 15 FKs, all with reverse-reachability GETs.
- **State machines: 5** — Reservation (reschedule cycle CONFIRMED→REQUESTED), WaitlistEntry (re-queue cycle NOTIFIED→WAITING), PrivateDiningEvent (revise cycle PROPOSED→INQUIRY), DepositHold, Customer. Three carry non-linear cycles on distinct entities.
- **Calculations: 8** — reservation_turn_window, standard_deposit (per-seat) vs private_dining_deposit (two-component round-then-sum, mode b), cancellation_fee (tiered 0/50/100%, mode a), customer_settled_reliability (settled vs provisional dual-variant), waitlist_promotion_rank, notify_window, pacing_slot_load.
- **Concurrency: 2** OCC races (reservation create on stale Table.version; private-dining confirm on stale DiningArea.version), both 412.
- **Validations: 14** (priority-ordered), **Endpoints: 56** (includes one `/_clock/set_current_utc` test-driving endpoint), **Errors: 24**, **Roles: 3** (Customer entity-backed; Host, Manager opaque).
- **Difficulty design (§1.8): 18 instances** — 9 §0.5 rules × 2 each, all formula-derived asserts pre-computed to literals.
- **Corner design (§1.9): 48 instances** — 44 active + 4 `excluded_because` stubs.

## Step 3: Copy INSTRUCTION.md — 2026-06-07T00:02:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-07T00:03:00.000Z

Generated `workspace/PRD.md` (286 lines) from `SCAFFOLD.yaml` only. Neither design YAML nor any sibling task was read.

### Section structure
- **§1 Introduction** — pain-point angle (double-booking/pacing, no-show revenue leakage, demand-vs-supply waitlist, private dining).
- **§2 Global Specifications** — 2.1 RBAC (Customer entity-backed; Host/Manager opaque), 2.2 Response Structure, 2.3 Pagination, 2.4 Common Properties & Versioning, 2.5 Time/Slots, 2.6 Precision/Rounding, 2.7 Cascades, 2.8 Nested Retrieval & FK Resolution, 2.9 Optimistic Concurrency, 2.10 Validation Ordering (priority 1→14).
- **§3 Business Logic** — 9 subsections by lifecycle/domain.
- **§4 Endpoint Definitions** — 4-column table, all 57 endpoints.
- **§5 Error Code Catalogue** — 2-column table, all 24 errors.

### Hard Contract reports (all PASS)
- Contract 1 — Field-Name Coverage: 66/66 present, 0 missing.
- Contract 2 — Rule Coverage: 24/24 error IDs surface; 39/39 state+enum values present; both OCC rules; all 6 calculations in precise prose; all cascades; embedded thresholds (15-min grace, 120-min expiry, 7-day hold expiry).
- Contract 3 — §3 Path Purity: 0 path/method tokens leaked into §3 prose.

Every entity (11), state machine (5), calculation (6), validation (14), endpoint (57), error (24), role (3) covered.

## Step 5: Generate unit tests — 2026-06-07T00:04:00.000Z

Generated test infra (`test_helpers/`) + cases (`test_suite/`), translating exclusively from the two design indices.

**Test files: 9** (1 conftest + 8 test modules). **Test functions: 81**, each with one `Design:` tag + verbatim PRD citation.
- **Queue A (Difficulty §1.8): 37 tests** covering all 18 instances (9 rules × 2; one rule got 3 for X-1/X/X+1 boundary). Zero shortfalls/dangling tags.
- **Queue B (Corner §1.9): 44 tests** covering all 44 non-stub instances at ≥1 each. Zero shortfalls/dangling tags.
- **Instances SKIPPED for PRD-first filter: 0** — all 81 citations survived ≥8-word grep of PRD.md.
- **Stubs correctly NOT translated: 4** `excluded_because:` corner stubs; all 4 cross-refs resolve to covered difficulty instances.

Key measures: `common_fields` branching honored (SpecialRequest/Notification = id+created_at only); entity-backed Customer identity threaded via `make_customer_headers`; OCC `expected_table_version` threaded from live version; all 56 ApiClient methods resolve; all files compile.

**test_helpers/ files (9):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

## Step 6: Generate implementation — 2026-06-07T00:05:00.000Z

Built Python + Flask implementation in `workspace/implementation/`.

**Files:** `start.sh`, `requirements.txt` (flask==3.0.3), `app.py`, `db.py` (in-memory dict store + system-field minting), `clock.py` (pinnable UTC), `timeutil.py`, `errors.py` (24 error ids), `response.py`, `middleware.py` (auth+RBAC), `validators.py`, `routes/` (12 files), `services/` (calc.py, booking.py, cascades.py, notifications.py, system_expiry.py, lookup.py).

**Scope:** 56 endpoints (matches PRD §4 URL map). State machines (Reservation, WaitlistEntry, DepositHold, PrivateDiningEvent, Customer) as explicit per-transition handlers with cyclic loops. Calculations centralized in `services/calc.py` (Decimal + ROUND_HALF_UP): turn-window, standard per-seat deposit, private-dining round-then-sum, tiered cancellation/no-show (0/50/100% + held-amount cap), settled & provisional reliability, pacing slot load, notify TTL. Cascades: no-show fiscal chain (capture→strike→reliability→auto-block→mass-cancel→release holds), table-free→waitlist promotion (winner = min(notify_count, joined_at)), buyout confirm→cancel collisions+release holds. Validation order per §2.10; OCC on expected_table_version/expected_dining_area_version (412); test-clock-driven time gates + request-level lazy expiry sweep.

**Fidelity decisions:** `ERR_NOT_RESOURCE_OWNER` only on cancel/reschedule/waitlist-cancel per §2.1 (no ownership check on create); pacing keys on floored slot instant (local date + grid minute); `/_clock` requires no auth.

**Confirmations:** start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground via `exec`; storage in-memory only, no seeding; verified fresh boot (GET /tables total_count=0) + three passing smoke suites.

## Step 7: Run tests and iterate — 2026-06-07T00:06:00.000Z

Clean exit. All 81 tests pass across a full parallel 8-round stability sweep (confirmed twice — two clean 16-round sweeps).

**Iterations run:** 3 sweeps (initial baseline + 2 confirmation). Initial sweep: 77/81 stable across all 8 rounds (4 failures). After fixes: a 5th flaky failure surfaced (1/8 rounds), then two consecutive clean 16-round sweeps (81/81 each).

**Tests deleted:** None. All 4 logic failures traced to verbatim PRD rules that uniquely determine their outcomes — they were test-fixture/precondition bugs, not silence/collapse patterns.

**Fixes applied to `test_suite/`** (all STEP 2 — fixture preconditions inconsistent with PRD, fixed to make the test more faithful):
- `test_02_reservation_lifecycle.py` → `test_confirm_blocked_when_customer_blocked_after_create` and `test_confirm_requires_active_customer_unchanged_on_reject`: Both booked a *future-start* reservation (start 18:00, clock 12:00), so blocking the customer triggered the §3.2 cascade ("cancels reservations with a start in the future"), cancelling the reservation — confirm then correctly returned `ERR_INVALID_STATE` (state check precedes the blocked check per §2.10). Fix: advance the clock to the booking start (`set_clock` 18:00) before blocking, so the reservation survives the cascade as `REQUESTED` and the confirm reaches the blocked-customer check, yielding `ERR_CUSTOMER_BLOCKED`.
- `test_07_private_dining_and_occ.py` → `test_create_with_stale_table_version_rejected`: The second booking's start (21:00) overlapped the first reservation's occupied window (20:00–21:45), so `ERR_TABLE_DOUBLE_BOOKED` fired first (precedes the OCC token in §2.10). Fix: moved the second start to 22:00 (grid-aligned, window 22:00–23:45, no overlap), isolating the stale-version rejection → `ERR_STALE_TABLE_VERSION`.
- `test_07_private_dining_and_occ.py` → `test_buyout_confirm_with_stale_area_version_rejected`: Confirming the first buyout left the area `BOUGHT_OUT`, so the second confirm failed the §3.4 "area must be AVAILABLE" precondition (`ERR_INVALID_STATE`) before reaching the OCC token. Fix: confirm-then-cancel the first buyout (per §3.4, cancel of a CONFIRMED event returns the area to AVAILABLE and bumps its version 1→2→3), leaving the area AVAILABLE at version 3 with no confirmed buyout, so the second confirm carrying stale version 1 reaches and trips `ERR_STALE_AREA_VERSION`.

**Fixes applied to `implementation/`** (robustness, not logic — addressed in-iteration flakiness signal):
- `app.py`, `requirements.txt`, `start.sh`: Replaced the Werkzeug dev server with the waitress WSGI server. Under 8×-concurrent per-test-reboot load, the dev server intermittently dropped an established connection mid-request (`ConnectionError: BadStatusLine` on a setup `POST /tables`, 1/16 rounds). Waitress handles connection churn robustly; install gated in `start.sh` (only when missing) with fallback to dev server. State remains in-memory only (no seeding/persistence). Flaky failure did not recur across subsequent 16 rounds.

No implementation business-logic checks were weakened and no assertions were downgraded; the implementation was already PRD-faithful on all 4 logic failures.

## Step 8: Finalize PRD — 2026-06-07T00:07:00.000Z

**Result: ZERO edits.** `PRD_FINALIZED.md` is byte-identical to `PRD.md` (286 lines each, 0% delta, `diff` confirms IDENTICAL). Every `<step_7_diff>` item traces to behavior PRD already uniquely determines, or to a pure-infrastructure change with no PRD-visible consequence.

### Per-item justification for no edit
- **Waitress server swap** (`app.py:77-91`, `start.sh:7`, `requirements.txt`): pure infra/robustness, in-memory store unchanged, no PRD-visible behavior → no edit.
- **Test fix 1** (`test_02` confirm-blocked): relies on §3.2 cascade cancelling only strictly-future reservations (`services/cascades.py:112`) + §2.10 state-check-before-blocked-check ordering (`routes/reservations.py:175-180`). Both PRD-pinned → no edit.
- **Test fix 2** (`test_07` stale-table-version): relies on §2.10 explicit ordering — table overlap precedes OCC token (`routes/reservations.py:82,88`, `services/booking.py:76-93,163-166`). PRD-pinned → no edit.
- **Test fix 3** (`test_07` stale-area-version): relies on §3.4 confirm-bumps-version, cancel-of-CONFIRMED-returns-AVAILABLE-and-bumps, confirm-requires-AVAILABLE (`routes/private_dining.py:146,174-178,128-129`). Fix routes around the area-AVAILABLE error rather than asserting its code. PRD-pinned → no edit.

### NO-NEW-MISMATCH search log (basis for not editing)
Area-version mutation paths, §2.10 validation ordering, and §3.2 block-cascade "future" predicate all enumerated and confirmed consistent with existing PRD prose. (Noted for Step 9: PRD §3.4 is silent on whether `complete` bumps the area version, but impl does `db.touch(area)` at complete — out of Step 8 HARD SCOPE, left for Step 9's full scan.)

## Step 9: Complete PRD (full impl scan) — 2026-06-07T00:08:00.000Z

Source `PRD_FINALIZED.md` (286 lines, 45,778 chars) → `PRD_COMPLETED.md` (286 lines, 47,264 chars). Char delta **+1,486**; line count unchanged (all edits in-paragraph; no new sections).

**Counts:** 9 changes — **7 ambiguity-pins**, **2 mismatch-revisions**.

**Per-change:**
- §3.1 (restaurant) — insert — ambiguity — `close`/`open` impose no source-state precondition and bump `version` even when already in that status — `routes/restaurants.py:56-71`.
- §3.1 (tables) — insert — ambiguity — out-of-service/return-to-service/bus impose no source-state guard (fire from any status, no `ERR_INVALID_STATE`) — `routes/tables.py:64-92`.
- §3.2 (reliability) — insert — ambiguity — only literal `provisional` selects provisional mode; omitted/other falls back to `settled` and is reported as `settled` — `routes/customers.py:54-67`.
- §3.4 (confirm preconditions) — revise — **mismatch** — PRD restricted held table to AVAILABLE/DIRTY; impl rejects only a missing table or OUT_OF_SERVICE (any other status incl. SEATED accepted) — `routes/reservations.py:182-184`.
- §3.4 (complete buyout) — insert — ambiguity — `complete` increments the dining area's `version` (the Step-8-flagged item; confirmed `db.touch(area)`) — `routes/private_dining.py:160-162`.
- §3.7 (special request) — insert — ambiguity — a second acknowledge is rejected with `ERR_INVALID_STATE` — `routes/special_requests.py:21-22`.
- §3.8 (notify) — insert — ambiguity — check order (no-matching-table → winner) and that a WAITING non-winner with a fitting table is rejected with `ERR_INVALID_STATE` — `routes/waitlist.py:97-108`.
- §3.8 (convert) — insert — ambiguity — supplied table must be AVAILABLE and fit the band (else `ERR_NO_MATCHING_TABLE`); new reservation window/`deposit_required` computed as on create; matched table's status and `version` left unchanged — `routes/waitlist.py:128-158`.
- §3.9 (test clock) — insert — ambiguity — clock endpoint returns an object whose sole `current_utc` field echoes the pinned instant — `routes/clock_route.py:30`.

**Findings:** The one mismatch (§3.4 confirm) was impl being more permissive than prose (accepts a SEATED table). All other areas (error catalogue, response envelope, pacing/overlap/buyout windows, cancellation-fee tiers, two-component deposit rounding, reliability formulas, RBAC, validation ordering, cascade families incl. buyout NOT triggering promotion, append-only entity fields, hold/waitlist expiry with strict `>` semantics) already uniquely pinned and matched impl — no change.

---

## Pipeline complete

All 9 steps done. Final state: 81/81 tests pass across two confirming 8-round parallel stability sweeps. Deliverables in place: SCAFFOLD.yaml + 2 design YAMLs, PRD.md → PRD_FINALIZED.md (identical) → PRD_COMPLETED.md (9 pins), test_helpers/ + test_suite/ (81 tests), workspace/implementation/ (Flask, in-memory, waitress).

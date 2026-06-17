# Worklog — task_0383_corporate_workplace_desk_booking_hoteling

## Step 1: Create Task Directory — 2026-06-16T14:44:10.000Z

Created `tasks/task_0383_corporate_workplace_desk_booking_hoteling/` and `tasks/task_0383_corporate_workplace_desk_booking_hoteling/workspace/`. Pre-assigned task index (0383); index-scan skipped per orchestration directive.

## Step 2: Generate Scaffold — 2026-06-16T15:09:28.000Z

All checks pass. The scaffold is complete and clean. (Note: a `worklog.md` and `workspace/` dir pre-existed in the target directory — I did not touch them, and I did not read any sibling task directories per the hard constraint.)

## Summary

Generated all three scaffold artifacts for **task_0383_corporate_workplace_desk_booking_hoteling** at the **Expert** difficulty band. `scaffold_lint.py` returns **VERDICT: clean lint**.

**Complexity profile**: primary archetype `temporal_windowing` + secondary `quota_allocation`; layers = rate/threshold triggers, cascading side effects, scheduled/deferred actions, derived-field reconciliation, optimistic concurrency, dual-variant calculation; topology `hybrid`; state-machine shape `parallel`; role model `peer_roles`; consistency `immediate`.

**SCAFFOLD.yaml contents:**
- **12 entities**: Site, Floor, Neighborhood, Seat, Room, Employee, Reservation, CheckIn, AmenityRequest, NoShowEvent, CapacityPolicy, VisitorPass.
- **6 state machines**: Reservation has two parallel dimensions (occupancy_status BOOKED→CHECKED_IN→COMPLETED/NO_SHOW_RELEASED/CANCELLED, and billing_status NONE→PROVISIONAL→FINALIZED/VOID); AmenityRequest (branching approve/deny fork); VisitorPass (cyclic REQUESTED↔CHANGES_REQUESTED loop); Seat (inventory lifecycle, guarded retire); Employee (compound booking_privilege derived from strike_score). Plus 2 OCC concurrency rules (stale Seat.version / Room.version on reservation create, 412).
- **4 calculations**: amenity_chargeback (dual-variant provisional/final; pins per-line-rounding mode (b) and fee-before-tier circular dependency mode (c)), strike_score (weighted_scoring with floor + threshold, mode (a)), utilization_report (dual-variant planned/realized), neighborhood_capacity_check (threshold with `<=` boundary).
- **17 validations** (ordered priority 1–17), **18 error codes**, **50 endpoints** (incl. 2 `/_clock` test-driving endpoints), **4 roles** (FacilityManager opaque, Employee entity_backed, Receptionist opaque, Analyst opaque).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 9 rule_ids × 2 instances = **18 instances**, all grounds resolvable, all formula-derived asserts precomputed to literals (verified by code: chargeback 624/495/78120/39060/976, utilization 66.67/33.33, strike 30, caps 2/1).

**SCAFFOLD_CORNER_DESIGN.yaml**: **39 instances** across 8 sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model) — 30 active test recipes + 9 `excluded_because:` stubs that each cite a real §1.8 instance by name.

Key fixes during generation: quoted `?`/`[`-bearing flow-list tokens to satisfy the YAML parser, converted version-read calls from POST to `GET /seats/{id}` / `GET /rooms/{id}`, captured Reservation status fields via a GET instead of the AmenityRequest response, added `GET /reservations/{id}/no-show-events` for FK reverse-reachability, and reworded one field description to avoid the forbidden "simultaneous" vocabulary.

## Step 3: Copy Shared Files — 2026-06-16T15:10:03.000Z

Copied `INSTRUCTION.md` → `tasks/task_0383_corporate_workplace_desk_booking_hoteling/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-16T15:15:51.000Z

Generated the PRD at `workspace/PRD.md` (287 lines).

**Structure:** §1 Introduction; §2 Global Specifications with 10 subsections (2.1–2.10, including the verbatim §2.2 envelope); §3 Business Logic with 11 subsections (3.1–3.11: floor-plan construction → inventory → policy → reservation lifecycle → amenities/chargeback → strikes → occupancy → no-show cascade → capacity → visitor desk → analytics); §4 Endpoint Definitions (50-row, 4-column table); §5 Error Code Catalogue (18-row, 2-column table).

Field coverage check: PASS (60/60 required fields present). Rule coverage check: PASS (validations precedence chain, 2 OCC rules → ERR_STALE_VERSION/412, all state-machine transitions, 4 calculations, 18 error conditions, side effects, defaults, sibling-branch symmetry — 0 missing). Path purity check (§3): PASS (375 backtick tokens scanned, 0 path/method tokens).

**Confirmation:** Did NOT read `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`.

## Step 5: Generate Unit Tests — 2026-06-17T00:00:00.000Z

Generation complete. Here's the report.

## Summary

I generated the complete test infrastructure for **task_0383 (Corporate Workplace & Desk Booking / Hoteling)** from the two design indices, applying the PRD-first two-condition filter throughout.

### Stage 1 — `test_helpers/` (9 files)
- **types.py** — role enum + status enums + entity TypedDicts. `CheckIn` and `NoShowEvent` correctly carry only `id`+`created_at` (common_fields:false); all other entities carry the full `id/created_at/updated_at/version` set.
- **api_client.py** — `ApiClient(GenericApiClient)`, 50 endpoint methods, all paths under the `/workplace` PREFIX.
- **api_errors.py** — 18-value `ApiErrorId` enum + HTTP status map registered via `set_error_http_status_map`.
- **assertions.py** — per-entity assertions + the `assert_audit_row_fields` invariant (rejects `version`/`updated_at` on append-only rows) + privilege consistency checker.
- **factories.py / constants.py / test_users.py** — input-only payload factories, calculation thresholds, and role headers. Only `Employee` is entity_backed, so it gets `make_employee_headers(user_id)`; the other three roles are opaque.
- **fixtures.py** — composite setup helpers with mandatory identity threading (ownership-gated calls use `make_employee_headers(employee_id)`): floor-plan scaffolding, lifecycle shortcuts (booked/checked-in), amenity-line builders, strike accrual / suspension, visitor-pass and room setups.

### Stage 2 — `test_suite/` (conftest + 7 files, 65 tests)
- **Difficulty queue A: 18/18 instances covered with ≥2 tests each.**
- **Corner queue B: 29/30 non-stub instances covered with ≥1 test.** All 9 `excluded_because` stubs verified to cross-reference real difficulty instances (0 broken pointers); none translated.

### One deliberate skip (a genuine PRD gap)
`Corner/state_machines/checkin_after_grace_expired_rejected` was **skipped**. The design asserts `ERR_INVALID_STATE` for a check-in attempted after grace expiry while the reservation is still `BOOKED`, but PRD §3.7 enumerates that precondition without naming an error_id for it — it explicitly maps only wrong-occupancy-state→`ERR_INVALID_STATE` and unavailable-resource→`ERR_RESOURCE_NOT_BOOKABLE`. A faithful PRD-only implementer could not uniquely derive that grace-expiry maps to `ERR_INVALID_STATE`, so it fails the unique-derivability condition. Per contract the gap stays a gap (no weakening, no xfail).

### Verification performed
- All 16 files compile (`py_compile`).
- Every `api.*` method (50) and `fx.*` fixture call resolves to a real definition — no interface drift.
- Every `from test_helpers import (...)` name resolves.
- Every test docstring ends with exactly one verbatim `Design:` tag; all PRD citations confirmed present in PRD.md (differences limited to markdown bold/backtick markers the rendered contract drops).
- Pinned chargeback/utilization arithmetic independently re-derived and matches the YAML's pre-computed literals (78120/39060, 624, 495, 976, 66.67/33.33).

Files are under `test_helpers/` and `/test_suite/`.

## Step 6: Generate Implementation — 2026-06-17T00:00:00.000Z

The implementation is complete and verified.

## Summary

I generated a complete Python + Flask implementation for the Corporate Workplace Desk Booking & Hoteling API at `workspace/implementation/`.

### Structure
- `start.sh` — foreground launcher with guarded `pip install` (only when flask is missing) + `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — entry point, blueprint registration, error handlers
- `db.py` — empty in-memory stores (no seeding), UUID/timestamp/request-id helpers, monotonic `_seq` for stable tie-broken ordering, the logical clock
- `errors.py`, `response.py`, `middleware.py` — error catalog (18 IDs), exact `meta`/`response_type`/`data` envelope, auth (`X-User-ID`/`X-User-Role`, 4 roles)
- `routes/` — sites/floors/neighborhoods/seats/rooms/policy/utilization, employees, reservations, amenities, visitor-passes, clock
- `services/` — `calculations.py`, `state_machines.py`, `booking.py`, `common.py`

### Key behaviors verified end-to-end (90+ assertions passed)
- **Validation precedence** (scaffold §1.4 priorities 1–17) — confirmed ownership(403) before existence(404), and the full 409-tier ordering (resource-not-bookable → suspended → zoning → limit → double-booked → capacity → OCC 412).
- **amenity_chargeback** pinned order — per-line round-half-up fee (e.g. 42.5→43), tier on pre-discount total, provisional `{REQUESTED,APPROVED}` vs final `{APPROVED}`; confirmed exact cents (618, 1075, frozen 618). Uses `Decimal`/`ROUND_HALF_UP`, never float.
- **strike_score** — NO_SHOW +10 / GOOD_CHECKIN −3, floor at 0, suspend at ≥30, reinstate baseline via `_reinstate_seq`, recovery via good check-ins.
- **Parallel state dimensions** — occupancy and billing evolve independently; void cascade (amenity CANCELLED → billing VOID → provisional 0) on both cancel and no-show release; cancel carries no strike.
- **No-show sweep / force release**, **OCC** on seat/room version, **neighborhood capacity** (ceil, `<=` boundary, distinct-seat dedup), **room turnover buffer** geometry, **half-open seat overlap** (touching endpoints OK), **dual-variant utilization** (PLANNED 25.00 vs REALIZED 0.00, 2dp round-half-up, empty floor → 0.00), **cyclic visitor-pass loop**.
- Immutable audit rows (CheckIn/NoShowEvent) carry only `id`+`created_at`; primary resources carry `version`/`updated_at` bumped on every mutation including derived-field reconciliation.

Fresh-boot empty state and the `start.sh` launcher were confirmed working. The non-PASS lines in my test runs were test-script ordering/shared-state artifacts (reservation-limit firing before OCC as specified; a cumulative sweep count across scripts), not implementation defects.
## Step 7: Run Tests and Iterate — 2026-06-16T19:53:39.000Z

All 8 parallel rounds pass cleanly. Exiting with the summary.

## Summary

**Iterations run:** 2 (initial diagnostic sweep + one fix + confirming sweep).

**Tests deleted:** None. No test failed the STEP 1 coverage / unique-derivability gate.

**Fixes applied to `test_helpers/`:** None. The bug was in an inlined setup loop in the test function itself, not in a shared fixture.

**Fixes applied to `test_suite/`:**
- `test_suite/test_03_booking_constraints.py`, `test_suspended_beats_seat_overlap` — the inlined 3×NO_SHOW suspension loop used `window=60, gap=160` starting at minute 700, so the third no-show window landed at 1140..1200, outside the floor's default workday `[540, 1080]`. The PRD-faithful implementation correctly rejected that setup reservation with `ERR_OUTSIDE_WORKDAY` (PRD §3.4: "a window ... that ... falls outside the workday is rejected with ERR_OUTSIDE_WORKDAY"), aborting the test in setup before its real assertion. STEP 2 test-vs-PRD fix: tightened the loop to `window=40, gap=20` (windows 700..740, 760..800, 820..860) so all three no-show windows stay inside the workday and clear of the live 540..600 booking. The test's actual assertion (suspension precedence over seat overlap → `ERR_BOOKING_SUSPENDED`) is unchanged and remains PRD-faithful.

**Fixes applied to `implementation/`:** None. The implementation was already correct — it correctly enforced the workday gate that exposed the malformed test setup. No PRD-required check was removed or weakened.

**Final sweep result:** All 8 parallel rounds passed with `passed == total == 65` (0 failures, 0 flakiness across rounds). Total test count: **65**.

Note: the runner's top-level summary line reports a misleading `failed: 1` even on fully-passing rounds; the authoritative per-test `status` field shows 65/65 passed in every round.

(Orchestrator verification, post-resume: independently re-ran the full 8-round sweep — all 8 results.{1..8}.json show total=65, breakdown={'passed': 65}. Results files persisted to workspace/implementation/.)

## Step 8: Finalize PRD — 2026-06-16T19:55:40.000Z

PRD_FINALIZED.md is a byte-identical copy of PRD.md. No edit is warranted.

**Line counts:** PRD.md = 287 lines, PRD_FINALIZED.md = 287 lines. %-delta: 0% (identical copy).

**Change list:**
- No changes — the sole Step 7 item was a pure test-fixture bug already uniquely determined by PRD §3.4. The fix tightened a no-show suspension setup loop in test_suite/test_03_booking_constraints.py::test_suspended_beats_seat_overlap so all three no-show windows (700..740, 760..800, 820..860) stay inside the default workday [540, 1080]. The implementation correctly rejected the original malformed setup with ERR_OUTSIDE_WORKDAY, which PRD §3.4 already states verbatim. No PRD silence and no PRD/impl mismatch.

**Per-edit pre-edit search log (no-edit conclusion):**
- Subject: workday-window gate (ERR_OUTSIDE_WORKDAY) — enumerated reservations.py create gate, visitor_passes.py file + resubmit gates, errors.py (422 map), sites.py workday defaults (540/1080); all mutually consistent and match PRD §3.4 / §3.10 / §2.7 / §3.1. No wording adjustment needed.
- Subject: no-show strike / suspension threshold — enumerated calculations.py (SUSPEND_THRESHOLD=30, compute_strike_score, derive_privilege) and reservations.py SUSPENDED→ERR_BOOKING_SUSPENDED; match PRD §3.6 / §3.4 verbatim. No edit needed.

## Step 9: Complete PRD — 2026-06-16T20:02:33.000Z

Produced workspace/PRD_COMPLETED.md as a minimal patch over PRD_FINALIZED.md, pinning every PRD silence/mismatch against implementation/ behavior.

**Line/char delta:** PRD_FINALIZED.md 287 lines / 44281 chars → PRD_COMPLETED.md 287 lines / 48303 chars (+4022 chars; no lines/sections added — all in-paragraph edits).

**Counts:** ambiguity-pins = 10, mismatch-revisions = 1.

**Per-change:**
- §2.1 (Employee RBAC) — insert — ambiguity — Employee read-side ownership: single-fetch of non-owned reservation/check-ins/amenities → ERR_FORBIDDEN; list endpoints silently scope to own reservations — routes/reservations.py:226,239,358; routes/amenities.py:63,76
- §2.3 (Pagination) — insert — ambiguity — non-integer limit/offset → ERR_INVALID_PAGINATION; check-ins list is the one unpaginated endpoint (all in creation order, total_count=full) — routes/_helpers.py:23-31; routes/reservations.py:334
- §2.7 (Logical clock) — insert — ambiguity — _clock/set well-formedness (ERR_INVALID_REQUEST) and 200 response echoes current_date/current_minute — routes/clock.py:35-41
- §3.1 (Floor plan) — insert — ambiguity — floor workday-bounds violation → ERR_INVALID_REQUEST — routes/sites.py:73-75
- §3.5 (Amenities) — insert — ambiguity — adding a line to non-open reservation → ERR_INVALID_STATE — routes/amenities.py:38-39
- §3.5 (Amenities) — insert — ambiguity — approve requires parent reservation open (ERR_INVALID_STATE); deny does not — routes/amenities.py:90-91,99-110
- §3.7 (Check-in) — insert — ambiguity — grace-expired / unset-clock check-in → ERR_INVALID_STATE, evaluated before resource-availability check — routes/reservations.py:273-280,371-375
- §3.8 (Release/Sweep) — insert — ambiguity — force-release precondition failures → ERR_INVALID_STATE; sweep response released_count + released_reservation_ids (creation order); unset clock / bad booking_date on sweep → ERR_INVALID_REQUEST — routes/reservations.py:312-316; routes/clock.py:49-76
- §3.10 (Visitor desk) — insert — ambiguity — active pass statuses holding a window = REQUESTED, APPROVED, CHECKED_IN — services/booking.py:17
- §3.10 (Visitor desk) — insert — ambiguity — resubmit/approve conflict errors (ERR_SEAT_DOUBLE_BOOKED, self-excluded) and resubmit workday check (ERR_OUTSIDE_WORKDAY) — routes/visitor_passes.py:172-181,200-203
- §3.11 (Utilization) — revise — MISMATCH — PRD said booked minutes = sum of stored occupied_minutes; impl sums each counted reservation's (end_minute − start_minute), so a still-BOOKED reservation contributes its full window under PLANNED. Revised to match impl; also pinned seat_breakdown element shape (seat_id, booked_minutes, seat_utilization_pct, seat-creation order) and mode/date query validation — services/calculations.py:216,222-226; routes/sites.py:116-122

Pipeline complete. Final artifact: workspace/PRD_COMPLETED.md. Stability: all 8 sweep rounds 65/65 (results.{1..8}.json persisted).

# Worklog — task_0353_karaoke_private_room_booking

## Step 1: Create task directory — 2026-06-14T13:09:28.000Z

Created `tasks/task_0353_karaoke_private_room_booking/` with `workspace/` subdirectory. INSTRUCTION.md confirmed present at project root.

## Step 2: Generate scaffold (Expert tier) — 2026-06-14T13:34:15.000Z

Scaffold generation complete. All three artifacts written and `scaffold_lint.py` reports **VERDICT: clean lint** (449 §1.8/§1.9 calls conform to §1.5; all 16 FKs have reverse-reachability).

**Domain**: Karaoke & Private Room Booking — Expert tier. Primary archetype **temporal_windowing** + secondary **pricing_engine**; layers: optimistic_concurrency, dual_variant_calculation, cascading_side_effects, rate_threshold_triggers. Topology **flat** (peer collections, FK-linked — `api_prefix: ""`), state-machine shape **branching**, role model **peer_roles**, consistency **immediate**.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **Entities: 11** — Venue, RoomType, Room, GroupPackage, Customer, Reservation, Extension, Song, QueueEntry, FbOrder, Payment.
- **State machines: 3** — Reservation (branching: HELD→{CONFIRMED→CHECKED_IN→CLOSED} or {CANCELLED, EXPIRED, NO_SHOW}), Room (cyclic AVAILABLE↔OCCUPIED↔OUT_OF_SERVICE), QueueEntry (PENDING→{PLAYED, SKIPPED, CANCELLED}).
- **Concurrency rules: 2** (OCC) — `reservation-create-overlap-stale-room` (on Room.version), `extension-stale-reservation` (on Reservation.version), both 412.
- **Calculations: 5** — quoted_room_subtotal (forward-looking, a_la_carte/package variants), settled_room_subtotal (chronological per-minute, within_plan/overage variants), fb_shortfall (threshold, package-credit variant), queue_play_order (priority+created_at), customer_no_show_strikes (aggregation). Rounding order pinned sum-then-round; created_at as the only tie-break (no id).
- **Validations: 13** (priority-ordered, auth→existence→body→state→OCC→temporal→safety→referential→temporal-overlap→constraint).
- **Endpoints: 41**; **Errors: 15**; **Roles: 3** (VenueManager opaque, FrontDesk opaque, Customer entity_backed:Customer).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 Difficulty Rules × 2 instances = **18 instances**.
**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **35 active instances** across all 9 claim-extraction-guide sections. No `excluded_because` stubs.

Note: API switched from nested to flat top-level collections so every FK satisfies lint reverse-reachability (also aligns with §0.3 flat-topology diversity guidance).

## Step 3: Copy shared files — 2026-06-14T13:34:30.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-14T13:38:30.000Z

Generated `workspace/PRD.md` (244 lines, 5 top-level sections, 23 headings). All scaffold elements covered:
- Entities: all 11. Contract 1 (Field-Name Coverage): 67 required, 67 present, 0 missing — PASS.
- State machines: Reservation (7 transitions), Room (4), QueueEntry (3) with preconditions + cascade side-effects.
- Calculations: all 5 in prose (quoted forward-looking a-la-carte/package, settled chronological per-minute + overage, fb_shortfall strict-below boundary, queue_play_order, customer_no_show_strikes); constants embedded (per-minute=hourly/60, overage ×2.0, sum-then-round half-up).
- Validations: all 13 priority-ordered in §2.8 with error IDs.
- OCC: both rules in §2.7 (expected_room_version/expected_reservation_version, 412, ERR_STALE_ROOM_VERSION/ERR_STALE_RESERVATION_VERSION).
- Endpoints: all 41 in §4 table. Errors: all 15 in §5 table. Roles: all 3 (VenueManager/FrontDesk opaque, Customer entity_backed).
- Contract 2 (Rule Coverage) PASS; Contract 3 (§3 Path Purity) PASS. §2.2 emitted byte-for-byte from canonical source.

## Step 5: Generate unit tests — 2026-06-14T13:53:00.000Z

Generated test infrastructure (test_helpers/, 9 files) and test cases (test_suite/, 8 files = conftest + 7 domain files). **71 tests total.**
- Queue A (Difficulty): 36 tests covering all 18 instances (2 each). Queue B (Corner): 35 tests covering all 35 non-stub instances (≥1 each).
- Skipped instances: 0 — every instance passed the PRD-first two-condition filter.
- test_helpers: types.py, api_client.py, api_errors.py (15 errors), assertions.py, factories.py, constants.py, test_users.py (opaque VenueManager/FrontDesk + entity_backed Customer headers), fixtures.py, __init__.py.
- Audits passed: every test has exactly one resolving `Design:` tag; all PRD citations verbatim (grep-survive); no skip/xfail; no scaffold leakage; full suite byte-compiles & collects (71).
- Translation note: difficulty index referenced nested payment path `GET /venues/{id}/reservations/{id}/payments`, but PRD+scaffold define flat `GET /payments?reservation_id=`. PRD is the contract → tests use flat path via `list_payments` fixture helper.

## Step 6: Generate implementation — 2026-06-14T13:53:00.000Z

Generated Python+Flask implementation in workspace/implementation/ (11 files). **41 endpoints** (matches PRD §4 / scaffold §1.5).
- Files: start.sh, requirements.txt (Flask 3.0.3), app.py (41 routes + error handlers + validation ordering), db.py (in-memory dicts + venue clocks + RLock), errors.py (15 error IDs + HTTP codes), response.py (envelope), middleware.py (X-User-ID/X-User-Role auth + role gate), helpers.py (validators, ISO-8601, pagination, clock), calculations.py (Decimal pricing engine), services.py (lifecycle/cascades/ledger/sweep/overlap), serialize.py (Song/Payment lean: id+created_at only).
- State machines: Reservation branching (HELD→{CONFIRMED→CHECKED_IN→CLOSED} | {CANCELLED,EXPIRED,NO_SHOW}) with per-branch side effects; Room + QueueEntry machines.
- Calculations: quoted_room_subtotal (forward per-minute peak/off-peak via zoneinfo, package=flat), settled_room_subtotal (chronological minute-walk + overage 2.0× past slot_end+grace, package covers included_hours*60 free min), fb_shortfall (strict-below floor), play_order (priority ASC, created_at ASC), no_show_strikes. All money Decimal sum-then-round-once half-up.
- OCC: expected_room_version on reservation-create (create-with-supersede advances room version), expected_reservation_version on extension-create; both 412.
- Validation ordering per PRD §2.8. Contract confirmed: start.sh reads $PORT, binds 0.0.0.0, foreground via exec; storage in-memory only (no SQLite/JSON/tmp); no startup seeding (grep-verified).

## Step 7: Run tests and iterate to green — 2026-06-14T14:00:00.000Z

Clean exit — all tests pass across the full 8-round parallel sweep.

**Iterations run:** 2 (1 diagnostic sweep + 1 verification sweep).

**Baseline:** 70/71 passing, identically across all 8 rounds — one deterministic failure, no flakiness.

**Failing test:** `test_settled_within_plan_no_overage` (in `test_suite/test_01_room_pricing_and_settlement.py`). Error: `assert 13500 == 15000`.

**Diagnosis (protocol applied):**
- STEP 1a COVERAGE — PASS. PRD §3.4 verbatim covers the rule: *"A session whose `actual_end_utc` is at or before `slot_end_utc` plus `overage_grace_minutes` incurs no overage multiplier at all (pure peak/off-peak on the actual minutes)"*, plus the per-minute rule *"the base per-minute rate is again `base_hourly_rate_cents` divided by 60 … multiplied by the venue's `peak_multiplier`"*.
- STEP 1b UNIQUE DERIVABILITY — PASS. Interval 20:00–21:30 = 90 whole minutes, all inside the peak window [18:00, 23:00), none past the 22:10 overage threshold ⇒ 90 × (6000/60 × 1.5) = 90 × 150 = **13500**, uniquely determined.
- STEP 2 TEST-vs-PRD CONSISTENCY — TEST WAS WRONG. The assertion expected 15000, but the test's own narrative arithmetic ("90 peak minutes at 100 * 1.5") evaluates to 13500, not 15000. The implementation already computed the PRD-faithful 13500 (cross-checked against the sibling passing tests `test_quoted_forward_vs_settled_chronological_diverge`, whose 18000/25500 figures use the same per-minute math).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** `test_01_room_pricing_and_settlement.py`, function `test_settled_within_plan_no_overage` — corrected the expected `settled_room_subtotal_cents` from 15000 to 13500 (arithmetic error in the test; 90 minutes × 150 cents/min = 13500), and updated the matching comment. This makes the test more faithful to PRD §3.4; the PRD-correct implementation was untouched.

**Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful.

**Final result:** 8/8 parallel rounds at 71/71.

## Step 8: Finalize PRD — 2026-06-14T14:05:00.000Z

`PRD_FINALIZED.md` is an exact, byte-identical copy of `PRD.md` (244 lines each, matching SHA-1, 0% delta). **Zero edits.**

Rationale: the sole `<step_7_diff>` item was a pure test arithmetic correction in `test_suite/` (expected 15000 → 13500) where PRD §3.4 already uniquely determined the value (13500) and the implementation already matched. No PRD-silence and no PRD-mismatch to patch. Independently verified the settlement site (calculations.py:87-129 ← app.py:793) and parallel quote path (calculations.py:56-82) against PRD §3.4/§2.6/§2.9: per-minute base = base_hourly_rate_cents/60, peak multiplier on [peak_start, peak_end), overage 2.0× only at/after slot_end+overage_grace_minutes, sum-then-round-once half-up — all match PRD prose exactly. Outcome explicitly designated valid by the method.

## Step 9: Complete PRD — eliminate residual ambiguity — 2026-06-14T14:08:00.000Z

Produced `PRD_COMPLETED.md` from `PRD_FINALIZED.md`. Source 244 lines / 45,585 chars → output 244 lines / 47,889 chars (char delta +2,304; all edits in-paragraph inserts).
- **Ambiguity-pins: 9. Mismatch-revisions: 0** (implementation faithfully tracks PRD prose; only gaps were silences).
- §2.3 Pagination — insert — out-of-range/non-integer limit (1–100) and negative/non-integer offset rejected with ERR_INVALID_REQUEST (helpers.py:128-147).
- §2.9 Venue Clock — insert — _clock/set does not bump venue version/updated_at, echoes unchanged venue, current_utc falls back to real wall-clock UTC before clock set (app.py:220-231, helpers.py:165-173).
- §3.1 Rooms/maintenance — insert — returning a non-OUT_OF_SERVICE room to service rejected with ERR_INVALID_STATE (app.py:386-388).
- §3.2 Customers — insert — duplicate email on registration rejected with ERR_INVALID_REQUEST (app.py:480-482).
- §3.3 Booking fields — insert — null-until-computed settled_room_subtotal_cents/final_total_cents; 0-start fb_consumed/fb_shortfall; from-create quoted/deposit previews (app.py:653-666).
- §3.3 Booking create gates — insert — successful create bumps target room version by 1 / refreshes updated_at to drive §2.7 stale-version refusal (app.py:667-671).
- §3.4 Check-In — insert — check-in whose assigned room is not AVAILABLE rejected with ERR_INVALID_STATE (app.py:756-758).
- §3.6 Queue play_order — insert — non-PENDING entries carry play_order null; listing orders PENDING by play_order then non-PENDING by created_at asc (calculations.py:170-172, app.py:974-979).
- §3.6 Queue recompute — insert — pure play_order re-rank doesn't touch surviving siblings' version/updated_at; only an entry's own status transition bumps version (calculations.py:156-172).
- §3.7 Ops Sweep — insert — _ops/run doesn't mutate venue version/updated_at, echoes unchanged venue (app.py:234-241, services.py:107-135).

## Final verification — 2026-06-14T14:08:36.000Z

Re-ran the 8-round parallel stability sweep to regenerate output artifacts (Step 7's results files had been cleaned up) and confirm the implementation remains green after the Step 8/9 PRD edits (which never touch implementation/). **All 8 rounds: 71/71 passed, 0 failed.** results.{1..8}.json written to workspace/implementation/.

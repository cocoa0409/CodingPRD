# Worklog — task_1490_historic_house_museum_docent_tour_program

## Step 1: Create Task Directory — 2026-08-13T12:36:00.000Z

Pre-assigned directory `tasks/task_1490_historic_house_museum_docent_tour_program/` with `workspace/` subdirectory confirmed to exist. No index scan or directory creation performed (per pipeline instructions).

## Step 2: Generate Scaffold — 2026-08-13T13:43:00.000Z

All three artifacts are generated and lint-clean. Summary:

## Scaffold: task_1490_historic_house_museum_docent_tour_program

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1490_historic_house_museum_docent_tour_program/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:`

**Counts:**
- Entities: **10** (Room, TourRoute, ScriptVersion, TourSlot, Docent, ShiftAssignment, Member, Booking, SafetyIncident, VisitorSurvey)
- State machines: **9** (includes cyclic ScriptVersion review loop and TourSlot OPEN↔FULL cycle)
- Calculations: **8**
- Validations: **25** rows across priorities 1–11
- Endpoints: **53** (incl. `POST /_clock/set_current_utc` with mandatory default `2026-08-01T00:00:00Z` and `POST /_ops/run_epoch` sweep)
- Errors: **29**
- Roles: **6** (MuseumAdmin/Curator/DocentCoordinator/FrontDeskStaff opaque; Docent and Member entity-backed with ownership checks)
- Concurrency rules: **2** OCC rules (script publish on TourRoute.version, slot reschedule on TourSlot.version)
- §1.8: **18 instances** (9 rules × 2, zero stubs)
- §1.9: **37 non-stub instances + 4 excluded_because stubs** across all 9 sections

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (799 calls scanned; two initial FK-reachability findings fixed by adding `GET /tour-routes?published_script_id=` and `GET /tour-routes/{id}/docents`.)

**Design notes:**
- Archetype: quota/allocation (seat buckets per slot) + temporal windowing (room occupancy half-open intervals vs docent shift 30-min buffer — deliberately different interval semantics for Rule 8).
- Key pinned arithmetic: candlelight pricing rounds per-person first then multiplies (1583×3=4749, not 4748); school pricing is marginal-tiered with ceil-based free chaperones (divisor 8 vs 10 on HIGH_VALUE routes); certification needs hours≥20 AND shadow≥3 AND quiz≥85 AND standard-readiness≥70; refund tiers 48h-inclusive.
- Cascade chains: CRITICAL incident → room closure → slot cancellations → booking/shift cancellations with tier-bypassing full refunds (depth 3); docent deactivation → shift cancels → slot staffing_status recompute (depth 2).
- Flat topology (`api_prefix: "/"`), immediate consistency, hierarchical-override role model; all formula-derived asserts were pre-computed to literals (e.g., revenue 2000 vs 4400, readiness 81 vs 76, capacity 8, school totals 15500/12700/10000).
- Endpoint count (53) sits above the Expert guideline band — a deliberate consequence of flat topology plus lint-mandated reverse-FK GETs for 11 FK edges; entity count (10) stays in-band.

## Step 3: Copy Shared Files — 2026-08-13T13:46:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1490_historic_house_museum_docent_tour_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T14:15:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1490_historic_house_museum_docent_tour_program/workspace/PRD.md`.

**Output summary**

- **Line count:** 303 lines
- **Source:** generated solely from the task's `SCAFFOLD.yaml` plus the doc-generator skill; the two withheld design indices were never opened, and no sibling tasks were read.

**Section list**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications (10 subsections): 2.1 Roles & Access Control (all 6 roles with identity semantics), 2.2 API Response Structure (verbatim block, byte-identical to `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Identity/Timestamps/Versioning + both OCC rules, 2.5 Logical Clock, 2.6 Money & Rounding, 2.7 Collection Tiers & Safety Rules, 2.8 Existence & URL Hierarchy, 2.9 Validation Order of Precedence (11 tiers, explicit ordering), 2.10 Snapshot vs. Live Fields
- §3 Business Logic (8 subsections): rooms/routes, script review cycle, docent pipeline, slots & staffing, membership, bookings/pricing/refunds, incident cascade, surveys
- §4 Endpoint Definitions: 53 rows (matches scaffold's 53 endpoints), 4 columns only
- §5 Error Code Catalogue: 29 rows (matches scaffold's 29 errors), 2 columns only

**Hard-contract self-audit verdicts**

```
Contract 1 — Field-name coverage:
  entities[].fields: 59 required, 59 present, 0 missing
  endpoints[].request_body: 48 required, 48 present, 0 missing
  endpoints[].query_params: 2 required, 2 present, 0 missing
  path params + response-only fields: 0 missing
  Status: PASS

Contract 2 — Rule coverage:
  validation priority tiers: 11 expressed in explicit evaluation order
  concurrency_rules OCC rejections: 2/2 (write op + expected_*_version + ERR_STALE_VERSION/412)
  state-machine transitions: all expressed with preconditions, error ids, side effects (incl. incident 3-hop cascade, docent-deactivation cascade, publish supersede)
  calculations: 7/7 in precise prose (capacity snapshot, tiered pricing, refund tiers, readiness dual-track, revenue projection, half-open occupancy windows, chaperone requirement, survey summary)
  validations: all 29 error ids matchable in §2/§3 prose; multi-endpoint applies_to scopes (create+open, create+reschedule, shift+reschedule) verified
  endpoint side effects / field defaults / sibling-branch symmetry: verified
  Status: PASS

Contract 3 — §3 path purity:
  450 backtick tokens scanned; 0 path tokens, 0 bare HTTP methods, 0 method+path combos
  Status: PASS
```

Additional checks: §2.2 emitted byte-identical; no pseudocode operators or fuzzy hedging words in prose; all 28 state enum values present as exact UPPERCASE strings.

## Step 5: Generate Unit Tests — 2026-08-13T15:10:00.000Z

All generation and audits are complete. Final summary:

## Output

**`test_helpers/` (Stage 1)** — 9 files under `/home/ubuntu/github/CodingPRD/tasks/task_1490_historic_house_museum_docent_tour_program/test_helpers/`: `types.py` (14 status/type enums, 10 entity TypedDicts — `VisitorSurvey` correctly omits `updated_at`/`version` per its append-only nature), `api_client.py` (one method per PRD endpoint, `ApiClient(GenericApiClient)`), `api_errors.py` (all 29 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity asserts, survey immutability checker, seat-bucket conservation invariant, timestamp normalizer), `factories.py`, `constants.py` (buffers, school tiers, refund hours, certification thresholds), `test_users.py` (6 roles; `make_docent_headers`/`make_member_headers` per-instance builders for the two entity-backed roles; `make_headers_without_user_id` for the 401 path), `fixtures.py` (5-tier composites: room/route/script-publish chain, certified-docent builder, staffed-SCHEDULED and OPEN slot chains, booking/member helpers, clock/epoch ops, completed-visit chain for surveys).

**`test_suite/` (Stage 2)** — `conftest.py` + 9 test files, **71 tests**, collected cleanly by pytest.

## Coverage

- **Queue A (Difficulty): 18/18 instances, 36 tests (exactly 2 each)** — dual-variant revenue (2000 vs 4400) and readiness (81 vs 76), capacity min-rooms×kind buffer (CANDLELIGHT 8 / STANDARD 10), candlelight round-per-person-first (1583→4749), script revision cycle, slot FULL↔OPEN cycle, incident 3-hop cascade (full 2000 refund bypassing the 50% tier at 34h), docent deactivation cascade, both validation-priority pairs, seat exact-fit/+1 boundary, quiz 84/85 boundary, both cross-entity gates, docent 30-min buffer (30 ok / 20 rejected), room half-open occupancy (11:00 ok / 10:59 conflict), seat-bucket and revenue conservation.
- **Queue B (Corner): 35/37 non-stub instances, 35 tests (1 each)**; 4 `excluded_because:` stubs not emitted, all cross-references verified to resolve.

## Skipped instances (PRD-first two-condition filter)

1. `Corner/entities/server_minted_created_at_uses_default_clock` — unique derivability fails: PRD §2.4 requires `created_at` as ISO 8601 but never names its clock source; §2.5 scopes the logical clock to an enumerated list of time-gated rules (slot scheduling, hold expiries, confirm windows, member lapses, survey windows, incident cascades) that does not include entity timestamps, so a PRD-faithful wall-clock stamper would fail the asserted literal.
2. `Corner/calculations/room_occupancy_window_floor_division_remainder` — the asserted outcome contradicts the PRD-derived outcome: on a 100-min route over 3 rooms, PRD §3.4 puts room 3's window at [11:06, 11:40) (last room absorbs the remainder), which overlaps the +33-minute slot's room-3 window [11:39, 12:13) — so the instance's "+33 is conflict-free" claim fails against any PRD-faithful implementation. Skipped rather than weakened or rewritten.

## Self-audit verdicts

- **Stage 1**: PASS — all helpers compile/import; fixtures use `get_success_data`; ownership-gated calls thread real entity IDs via the per-instance builders; no framework re-implementation.
- **Stage 2**: PASS — 71/71 docstrings end with exactly one `Design:` tag resolving to a real yaml instance; all 107 distinctive ≥8-word citations survive whitespace-normalized literal grep of `PRD.md` (two fused quotes were caught and split into separate verbatim sentences); all 29 asserted `error_id`s appear in PRD narrative prose (§2/§3), not merely in the §5 table; asserted validation precedence (state>safety, qualification>overlap) is backed by PRD §2.9's explicit short-circuit rule; no `skip`/`skipif`/`xfail` markers; zero scaffold references in generated code.

## Step 6: Generate Implementation — 2026-08-13T15:10:00.000Z

The implementation is complete and verified. Summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1490_historic_house_museum_docent_tour_program/workspace/implementation/`:

- `start.sh` — guarded pip install (no-op once Flask present), `exec python3 app.py`, reads `$PORT` (default 10000), binds `0.0.0.0`, foreground; executable
- `requirements.txt` — `flask>=3.0,<4`
- `app.py` — Flask entry, envelope-shaped 404/405/500 handlers
- `db.py` — in-memory store (10 dicts, starts empty, no seeding), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, timestamp formatters
- `errors.py`, `response.py`, `middleware.py`, `util.py` — ApiError, `meta`/`response_type`/`data` envelope with `limit`/`offset`/`total_count`/`has_more`, `X-User-ID`/`X-User-Role` auth (ERR_UNAUTHENTICATED 401 / ERR_FORBIDDEN 403), request-shape validators (ERR_INVALID_REQUEST 400)
- `services.py` — live aggregates (seats, revenue committed/projected, staffing), occupancy windows, cascades, pricing/refund/readiness calculations (all `Decimal` + ROUND_HALF_UP)
- `routes/` — 11 blueprints: rooms, tour_routes, scripts, slots, docents, shifts, members, bookings, surveys, incidents, ops

## Endpoint count

All **53 endpoints** from the PRD §4 table implemented and registered (verified via Flask URL-map enumeration), including `POST /_clock/set_current_utc` and `POST /_ops/run_epoch`.

## State machines implemented (9)

Room (OPEN↔CLOSED_RESTORATION, incident-driven only), TourRoute (DRAFT→ACTIVE→RETIRED with future-slot guard), ScriptVersion (DRAFT↔IN_REVIEW revision loop, →APPROVED→PUBLISHED→SUPERSEDED, REJECTED terminal; publish OCC on `expected_route_version`), TourSlot (SCHEDULED→OPEN↔FULL auto-flip→IN_PROGRESS→COMPLETED, CANCELLED; reschedule OCC on `expected_slot_version`), Docent (APPLICANT→TRAINEE→CERTIFIED threshold-gated →INACTIVE with shift cascade), ShiftAssignment (ASSIGNED→CONFIRMED/DECLINED, CONFIRMED→COMPLETED/NO_SHOW after slot completion), Booking (RESERVED→CONFIRMED/EXPIRED/CANCELLED with time-tier refunds), Member (ACTIVE↔LAPSED→EXPIRED via epoch), SafetyIncident (REPORTED→RESOLVED with room reopen condition).

## Verification

Two smoke suites (110+ assertions) run against fresh-booted servers covering: all role/RBAC denials, envelope shape, candlelight round-per-person-then-multiply (base 1001 → unit 1502), school tiers + divisor-8 chaperones on HIGH_VALUE routes, refund tiers (full/half/zero + cascade bypass), hold expiry (`min(created+48h, start_at)`), member lapse/expire sweep, occupancy half-open touching-windows-OK, 30-min shift buffer, OCC 412s, FULL↔OPEN flips, survey window, and the 3-hop CRITICAL cascade. All pass, and `bash start.sh` on a custom `$PORT` boots with an empty store.

## Notable interpretation decisions

1. **§2.5 vs §2.4 — resource timestamps use the logical clock.** `hold_expires_at = min(created_at + 48h, slot.start_at)` is only self-consistent if `created_at` reads the logical clock; wall clock is used solely for `meta.api_request_timestamp`.
2. **Timestamp formatting** — `created_at`/`updated_at` always carry 3 fractional digits per §2.4; `start_at`/`end_at`/`hold_expires_at`/`current_utc` emit seconds-only form when the fraction is zero (preserves client-supplied instants exactly).
3. **§3.4 shift-overlap buffer** — the docent's existing non-terminal shift windows are padded ±30 minutes, then half-open overlap is tested against the candidate window.
4. **§3.5 epoch** — one transition per member per run: a member 40 days past `renews_on` goes ACTIVE→LAPSED on the first epoch and LAPSED→EXPIRED on a later one (state-machine reading; `lapsed_member_count` counts only new LAPSED).
5. **§3.3 certification `route_ids`** — missing/empty `route_ids` at CERTIFIED yields ERR_INVALID_REQUEST (400), not ERR_CERTIFICATION_NOT_MET, since the PRD sentences state it separately from the four threshold gates.
6. **§2.9 publish ordering** — followed the numbered 11-tier gauntlet (shape → state → stale version) rather than the closing "stale version first" sentence, which conflicts with the tier list; scaffold agrees with the tiers.
7. **Training HOURS value** — must be a positive integer (PRD gives no bound; SHADOW_TOUR must be exactly 1, QUIZ 0–100 per spec).
8. **Read ownership** — Docent role restricted to own record/shift lists; Member role restricted to own member record, bookings, and booking surveys (403 otherwise).
9. **Uniqueness (`Docent.email`, `Member.member_number`)** — not enforced: the error catalog defines no duplicate error, so no 4xx exists to return.

## Step 7: Run Tests and Iterate — 2026-08-13T15:20:00.000Z

All 8 rounds pass cleanly: 71/71 in every round. Exit condition met.

## Summary

**Iterations run:** 2 (sweep 1: 2 deterministic failures in all 8 rounds; fix applied; sweep 2: 71/71 × 8 rounds all green).

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1490_historic_house_museum_docent_tour_program/test_suite/test_07_booking_guards.py` — added the missing `setup_active_route_with_script` to the `from test_helpers import (...)` list. Both `TestSeatCapacityBoundary::test_exact_fit_accepted_and_fills_slot` and `TestSeatCapacityBoundary::test_one_over_capacity_rejected` were failing with `NameError: name 'setup_active_route_with_script' is not defined` in all 8 rounds. The helper itself (`test_helpers/fixtures.py:239`) is PRD-faithful and correctly exported via the barrel `__init__.py`; only the test file's import list was incomplete. The asserted rules (inclusive exact-fit capacity boundary, `ERR_CAPACITY_EXCEEDED` on one-over) are verbatim in PRD §3.6 ("a party exactly equal to the remaining seats is allowed; overcapacity is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 409)"), so the tests stayed — this was a STEP 2 mechanical test bug, not a coverage or derivability issue.

**Fixes applied to `implementation/`:** None — the implementation was already PRD-faithful; every other test passed deterministically in all rounds of both sweeps.

## Step 8: Finalize PRD — 2026-08-13T15:25:00.000Z

**Result: PRD_FINALIZED.md is byte-identical to PRD.md — no PRD edits were warranted.**

**Line counts:** PRD.md = 303 lines; PRD_FINALIZED.md = 303 lines; delta = 0%.

**Changes:** None.

**Rationale.** The `<step_7_diff>` contains exactly one item, and it is a pure Step 2 mechanical test bug, not a PRD silence or PRD/impl mismatch:

- `test_suite/test_07_booking_guards.py` — added the missing `setup_active_route_with_script` to the `from test_helpers import (...)` list (now at line 20 of the test file). The helper was always defined (`test_helpers/fixtures.py:239`) and exported via the barrel `test_helpers/__init__.py`; no behavior surface was touched.
- The two tests that consume it (`TestSeatCapacityBoundary::test_exact_fit_accepted_and_fills_slot`, `::test_one_over_capacity_rejected`) assert rules quoted verbatim from PRD §3.6 (PRD.md line 181): "Capacity comes last: the `party_size` must not exceed the slot's `seats_available`, though a party exactly equal to the remaining seats is allowed; overcapacity is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 409)."
- The implementation already matches the PRD exactly: `implementation/routes/bookings.py:165-167` uses `if party_size > seats_available(slot)` (strictly-greater comparison → inclusive exact-fit boundary), raising `ERR_CAPACITY_EXCEEDED` with HTTP 409, positioned in the guard chain exactly as PRD §3.6/§2.9 prescribe (after slot-state, safety cap, chaperone, curriculum; before member standing).

No tests were deleted, no `test_helpers/` fixes, no `implementation/` fixes. There is no PRD silence to pin and no PRD/impl divergence to reconcile.

**Per-edit pre-edit search log:** zero edits were made, so no pre-edit searches were triggered. For completeness, the verification performed before concluding "no edit": (a) subject = the seat-capacity boundary rule touched by the fixed tests; (b) impl paths enumerated = the sole `ERR_CAPACITY_EXCEEDED` raise site at `implementation/routes/bookings.py:165-167` (confirmed via repo-wide grep — only one occurrence), plus its surrounding guard chain in the same function and the PRD §2.9 precedence list (PRD.md line 113), all consistent with existing PRD prose; (c) wording adjustment = none, since no edit was committed.

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1490_historic_house_museum_docent_tour_program/workspace/PRD_FINALIZED.md` (verified byte-identical to `PRD.md` via `diff`).

## Step 9: Complete PRD — 2026-08-13T15:45:00.000Z

All edits are in place and verified. The file `/home/ubuntu/github/CodingPRD/tasks/task_1490_historic_house_museum_docent_tour_program/workspace/PRD_COMPLETED.md` was produced.

## Summary

**Source**: `PRD_FINALIZED.md` (303 lines, 48,773 chars) → `PRD_COMPLETED.md` (304 lines, 51,929 chars); **char delta +3,156**. No new sections; all changes are inline inserts/revisions except one error-catalogue row.

**Counts**: 16 ambiguity-pins, 3 mismatch-revisions (19 change bullets below; two Edit operations each bundled two related pins into one paragraph).

- §2.1 — insert — ambiguity — Docent callers may read only their own docent record and own shift list; Member callers only their own member record and booking list; slot-level shift/survey listings carry no ownership filter — `implementation/routes/docents.py:56-57,159-160`, `implementation/routes/members.py:47-48,77-79`, `implementation/routes/slots.py:213-240`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`, non-integer/negative `offset` rejected with `ERR_INVALID_REQUEST` (400) — `implementation/util.py:103-125`
- §2.3 — insert — ambiguity — list sort ties keep creation (insertion) order — `implementation/services.py:40-42`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` stamped from the logical clock (wall clock only in `meta.api_request_timestamp`); `start_at`/`end_at`/`hold_expires_at`/`current_utc` render fractional seconds only when non-zero — `implementation/services.py:19-30`, `implementation/db.py:41-56`
- §2.8 + §5 — insert — ambiguity — unmatched path or unsupported method → `ERR_NOT_FOUND` 404; unexpected failure → `ERR_INTERNAL` 500; added `ERR_INTERNAL | 500` catalogue row — `implementation/app.py:20-30`
- §2.9 tier 4 — insert — ambiguity — request body must be a JSON object; bound enumeration extended (HOURS ≥ 1, review `accuracy_score` 0–100 when provided, `paid_cents` ≥ 0) — `implementation/util.py:33-42`, `implementation/routes/docents.py:135`, `implementation/routes/scripts.py:42-47`, `implementation/routes/bookings.py:220`
- §2.9 — revise — mismatch — "a publish carrying both a stale version and an otherwise invalid payload reports the stale version first" flipped: impl checks shape (400) and lifecycle (409) before the stale-version tier, so the earlier-tier error surfaces first — `implementation/routes/scripts.py:82-93`
- §3.1 — insert — ambiguity — unrecognized `status` filter value on a route's slot list → `ERR_INVALID_REQUEST` (400) — `implementation/routes/tour_routes.py:182-184`
- §3.2 — insert — ambiguity — script drafts may be opened under a route in any status; omitted `curriculum_standards` defaults to an empty array — `implementation/routes/tour_routes.py:144-162`
- §3.2 — insert — ambiguity — provided `accuracy_score` must be an integer 0–100 and `reviewer_notes` a string, validated before the lifecycle check — `implementation/routes/scripts.py:41-53`
- §3.3 — revise — mismatch — dropped "email, unique per docent"; impl enforces no uniqueness on docent fields — `implementation/routes/docents.py:32-50`
- §3.3 — insert — ambiguity — HOURS value must be ≥ 1; no training-record resource is persisted; the endpoint responds 201 with the updated docent record — `implementation/routes/docents.py:127-153`
- §3.3 — insert — ambiguity — route docent roster lists every docent whose `certified_route_ids` contains the route regardless of status (INACTIVE included) — `implementation/routes/tour_routes.py:227-234`
- §3.4 — insert — ambiguity — the slot's lifecycle state is not consulted at shift-assignment time — `implementation/routes/shifts.py:20-72`
- §3.4 — revise — ambiguity — reschedule re-runs the shift-buffer overlap check before the room-occupancy check (matching §2.9's tier-10 order and impl), both excluding the rescheduled slot's own windows — `implementation/routes/slots.py:188-196`
- §3.5 — revise — mismatch — dropped "unique external `member_number`"; impl enforces no uniqueness — `implementation/routes/members.py:23-41`
- §3.5 — insert — ambiguity — each member transitions at most one step per sweep (ACTIVE long-overdue lapses first, hardens to EXPIRED only on a later run); `lapsed_member_count` counts only ACTIVE→LAPSED moves on that run — `implementation/services.py:353-371`
- §3.6 — insert — ambiguity — booking read-back carries the full field set with inapplicable kind-specific fields null (`member_id` null on GENERAL/SCHOOL); SCHOOL `party_size` reports the computed student-plus-chaperone sum — `implementation/services.py:491-511`
- §3.6 — insert — ambiguity — `paid_cents` must be a non-negative integer, failing which `ERR_INVALID_REQUEST` (400) fires at the shape tier before payment equality — `implementation/routes/bookings.py:220`

All other implementation behaviors (state machines, capacity/occupancy/pricing/refund/readiness formulas, cascades, OCC fields, envelope shapes, RBAC table, error-code/HTTP mappings) were verified against the PRD and already pinned uniquely, so no further changes were made.

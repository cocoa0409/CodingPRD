# Worklog — task_1320_riverboat_dinner_cruise_operations

## Step 1: Create Task Directory — 2026-08-12T22:01:00.000Z

Task directory `tasks/task_1320_riverboat_dinner_cruise_operations/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher; treated as DONE per instructions. No index scan performed, no other task_* directory touched.

**Difficulty directive (user):** "Generate task hard than expert level!" — forwarded to the scaffold subagent as: target the Expert band ceiling and push beyond where the scenario naturally supports it (entity/endpoint counts at or above the Expert top-end, maximal tight coupling, 3–4 difficulty layers, dense cross-entity cycles), while honoring the skill's density-over-volume principle.

## Step 2: Generate Scaffold — 2026-08-12T22:28:00.000Z

All three scaffold artifacts are generated and lint-clean for task 1320 (riverboat dinner cruise operations).

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1320_riverboat_dinner_cruise_operations/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:`

**Counts:**
- Entities: **16** (Vessel, Dock, MenuTier, CruiseInstance, Customer, Booking, BookingPassenger, BoardingManifest, StaffMember, StaffAssignment, GalleyProvisionOrder, CharterInquiry, WeatherEvent, CruiseCredit, DockSlot, ParkingPass) — note the lint counts 16 because BookingPassenger etc. all register; the scenario's 15 designed entities plus none padded.
- Endpoints: **77** declared in §1.5 (target band 30–34 was exceeded — the Expert-band FK reverse-reachability rule (f) forced 7 additional reverse-GET endpoints plus business surface; all are real reads, no padding)
- Errors: **36** in §1.6 (exceeds the 26–30+ directive)
- Difficulty layers (4): cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency. Archetypes: quota/allocation (Coast Guard capacity) + compliance/audit (alcohol cert, manifest). Role model: segregation_of_duties (quote vs convert, accept vs convert).

**§1.8 instances (20 total, ≥2 per §0.5 rule):**
- dual_variant_calc: 2 (weather_credit money domain; galley covers domain)
- combinatorial_formula: 2 (mode (a) tiered/seasonal/holiday stack; mode (b) per-line rounding pinned — 14865 vs 14864)
- non_linear_state_machine: 2 (Booking parallel payment×booking dimensions; CharterInquiry QUOTED↔COUNTERED cycle)
- transitive_cascade: 2 (weather-cancel depth-4; charter-conversion depth-2)
- priority_pair_validation_conflict: 2 (state vs business_safety; business_temporal vs business_constraint)
- boundary_precision_check: 2 (capacity exact-fit on booking create; parking empty-pool edge)
- cross_entity_state_dependency: 2 (Cruise×Manifest; StaffAssignment×StaffMember)
- resource_temporal_overlap: 2 (dock-slot turnaround-buffer intervals; parking aggregate-count pool)
- compensating_invariant: 2 (reserved_covers round-trip; parking_in_use round-trip)
- Plus 2 OCC stale-version instances covering both concurrency_rules

**§1.9 instances: 53 total (42 full with test_recipe, 11 `excluded_because:` stubs)** across sections entities / state_machines / calculations / validations / endpoints / errors / rbac / complexity_layers / consistency_model.

**Key mechanics exploited:** Coast Guard capacity as hard invariant with OCC on CruiseInstance.version; provisional-vs-final weather credit (36206 → 36956 after rebate+fee); forward-looking vs chronological galley covers (6 vs 5); charter conversion re-pricing at 88% with conversion credits; certification-gated bar service; turnaround-buffer interval semantics vs aggregate parking pool.

**Lint status:** `VERDICT: clean lint` (77 endpoints, 16 entities, 20 §1.8 + 42 active §1.9 instances, 528 calls scanned, 0 violations). All formula-derived assert literals were pre-computed with Python (e.g., 48275, 16688, 775000, 5563, tier boundaries 350000/620000/980000).

One design note: during corner-design replay I found and fixed a state-machine deadlock (weather hold could never be cleared once an event closed) by allowing clear-hold while the event is DECLARED and keeping ERR_WEATHER_EVENT_ACTIVE for the CANCELLATION_ISSUED case.

## Step 3: Copy Shared Files — 2026-08-12T22:29:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1320_riverboat_dinner_cruise_operations/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T22:48:00.000Z

PRD generation complete. Output: `/home/ubuntu/github/CodingPRD/tasks/task_1320_riverboat_dinner_cruise_operations/workspace/PRD.md` (379 lines). The withheld difficulty/corner design files were never opened.

## Summary

**PRD line count:** 379 lines

**Section list:**
- §1. Introduction (2 paragraphs)
- §2. Global Specifications — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim fixed block); 2.3 Pagination; 2.4 The Logical Clock; 2.5 Common Resource Properties; 2.6 Cents, Covers, and Rounding Discipline; 2.7 Nested Resource Retrieval; 2.8 The Validation Ladder; 2.9 Optimistic Concurrency Control; 2.10 Derived Counters and Cascading Consistency
- §3. Business Logic & Workflows — 3.1 Piers/Vessels/Menu Tiers; 3.2 Scheduling Cruises & Berthing; 3.3 Bookings & Ticket Pricing; 3.4 Crew & Alcohol Compliance; 3.5 Galley Provisioning; 3.6 Manifest/Boarding/Voyage; 3.7 Parking; 3.8 Weather/Cancellation/Credits; 3.9 Private Charters
- §4. Endpoint Definitions (77-row, 4-column table)
- §5. Error Code Catalogue (36-row, 2-column table)

**Hard Contract reports:**
- Contract 1 (Field-Name Coverage): 66 required names (56 entity fields + 4 common fields + 3 endpoint-only inputs + `current_utc` + `limit`/`offset`) — 66 present, 0 missing. PASS
- Contract 2 (Rule Coverage): validations 17/17 expressed as an explicitly ordered ladder with applies_to scopes on rungs 5/6/15; OCC 2/2 (endpoint framing + `expected_cruise_version`/`expected_inquiry_version` + `ERR_STALE_VERSION`/412); state transitions 34/34 across 9 state machines; calculations 7/7 with pinned rounding steps, tier boundaries (10/6/4 party tiers, 72/24/6-hour credit tiers, 49/99 capacity tiers), and stack order (discount → seasonal → holiday premium); all 36 error IDs matchable to trigger prose in §2/§3; every endpoint side effect rendered (weather-cancel 6-step cascade, completion 4-part cascade, charter-conversion cascade); sibling branches (dual weather-cancel from SCHEDULED/WEATHER_HOLD, dual cancel/convert branches, PLACED/RECEIVED settle, provisional/final variants) symmetric. PASS
- Contract 3 (§3 Path Purity): 491 backticked tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combos. PASS

**Coverage self-audit:** Verified sections 1.0–1.7 of the scaffold are fully rendered — envelope (verbatim §2.2), all 16 entities' fields/defaults/enums, all state machines with preconditions paired to error IDs, all 7 calculations in reconstruction-safe prose (no pseudocode, no fuzzy quantifiers — scan clean), all 17 validations with explicit priority ordering, all 77 endpoints in §4, all 36 errors in §5, and both OCC rules.

**Deliberate generalizations (two, both where the scaffold itself is silent on the error mapping):** (1) input-shape constraint violations that have no nominated error (`party_size` ≥ 1, `bar_package_count` ≤ `party_size`, duplicate `email`) are attached to `ERR_INVALID_REQUEST`, the catalogue's general 400 invalid-input error; (2) the "at most one non-cancelled provision order per cruise" invariant is stated as a rule without an invented error ID, since the scaffold assigns none. Additionally, `quoted_at` (referenced only in the quote-expiry trigger, not an entity field) was rendered as "forty-eight hours after the quote was posted" to avoid inventing a field name.

## Step 5: Generate Unit Tests — 2026-08-12T23:25:00.000Z

The full suite is generated and verified. Final report:

## Summary

**Generated infrastructure** (`/home/ubuntu/github/CodingPRD/tasks/task_1320_riverboat_dinner_cruise_operations/`):

`test_helpers/` — 9 files, all import-clean at runtime:
- `types.py` — 16 entity TypedDicts + 15 status/role enums; `BookingPassenger` and `CruiseCredit` correctly modeled as light resources (no `updated_at`/`version`) per PRD §2.5.
- `api_client.py` — `ApiClient(GenericApiClient)` with 63 endpoint methods covering all 77 PRD §4 endpoints (singleton `api_client`).
- `api_errors.py` — all 36 `ApiErrorId`s + HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity validators + parking-pool/capacity invariants.
- `factories.py`, `constants.py` (pricing tiers, notice tiers 72/24/6, charter prices, `MAX_QUOTE_ROUNDS=6`, `TURNAROUND_MIN=45`, holiday dates).
- `test_users.py` — 6 role headers; `make_customer_headers(user_id)` builder for the entity-backed Customer role (mandatory identity threading); `make_ops_manager_headers` for SoD-distinct operators.
- `fixtures.py` — composite helpers: `setup_inventory`, `create_booking`/`create_paid_booking` (OCC-threaded), `add_passenger`, bartender/staff assignment chains, provision-order chain, manifest freeze/open-boarding, weather declaration/cancel/settle, charter pipeline through ACCEPTED, parking/dock-slot creators, `setup_voyage_ready`, `setup_weather_cancelled_cruise`.
- `__init__.py` barrel.

`test_suite/` — `conftest.py` + 8 test files, **85 tests total**.

**Test counts per queue:** Queue A (Difficulty): 40 tests across 20/20 instances (each ≥2). Queue B (Corner): 45 tests across 42/42 active instances (each ≥1). 11 `excluded_because:` stubs not translated (all cross-references resolve to real difficulty instances).

**Per-file inventory:**
- `test_01_ticket_pricing.py` (7) — pinned 4-step pricing stack, per-line bar rounding (14865 vs 14864), seasonal constants, party-tier boundaries, OFF-season derivation
- `test_02_bookings_capacity_occ.py` (16) — capacity exact-fit/over-by-one, reserved_covers definition, both OCC rules + rung-6-before-14 ladder consequence, pay lifecycle, cancel round-trips, immediate consistency, parallel state axes, input shape, terminal lockdown
- `test_03_boarding_manifest_voyage.py` (10) — manifest gate, freeze/amend cycle, capacity-pair state priority, no-show sweep, galley 6-vs-5 variant divergence
- `test_04_weather_credits_cascade.py` (11) — provisional 36206 vs final 36956 divergence, depth-4 cascade, untouched pre-cancelled bookings, 72h/5h notice tiers, event lifecycle errors, settle satisfaction path
- `test_05_charter_pipeline.py` (8) — QUOTED↔COUNTERED cycle (quote_round 3, 775000), capacity tiers 49/50/100, round cap 6, conversion cascade (37202 credit, reserved_covers=60), DECLINED terminal, agent-cannot-convert RBAC
- `test_06_shoreside_dock_parking.py` (10) — 16:44/16:45 buffer boundary, cross-dock conflict, zero/unit capacity edges, pool release/reopen, no time-slicing, REDEEMED keeps stall
- `test_07_galley_staffing_compliance.py` (9) — provisional input-set filtering, order state machine, cert-gated bartender confirm, clock-flipped bar flag, bar-payment gate, GalleyManager RBAC denial
- `test_08_platform_and_fleet.py` (14) — missing-header 400, RBAC denials, 404 family, enum/time-range 400s, pagination envelope+defaults, status filter, logical clock, vessel defaults, OUT_OF_SERVICE, is_minor derivation, light-resource shape, customer→bookings reverse read

**Instances with design notes (none fully skipped):** Every one of the 62 non-stub instances yielded ≥1 test. One caveat: for `Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_conflict`, the instance's full recipe (a dock-slot create rejected with `ERR_PARKING_FULL` while also conflicting temporally) is not uniquely derivable — PRD §2.8 rung 9 scopes `ERR_PARKING_FULL` to the parking-pass endpoint only. I did not emit that compound assertion (it would be scaffold-leakage); instead the instance is covered by 2 tests asserting the rung-8 temporal error the PRD does pin (slot creation at 16:30 inside the buffer, including on a zero-stall dock).

**Self-audit (all machine-verified):**
- All 85 test functions carry exactly one `Design:` tag; 0 unknown tags, 0 stub leaks, 0 untagged tests.
- All 145 quoted PRD citations in docstrings survive a whitespace-normalized literal grep of `PRD.md` (C1/C2/C3); every asserted `error_id` is named in PRD trigger prose, not just the §5 table.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; all code compiles; barrel + cross-imports resolve; no scaffold references in comments/docstrings.
- All asserted literals recomputed independently with Decimal ROUND_HALF_UP and match the design indices (48275, 42275, 36206, 36956, 16688, 22250, 5563, 37202, 14865, 9912, 775000, 350000/620000/980000, 26700/33820/48060/75650, 19580, 5.0, 600).
- All fixtures build state purely via API calls (safe under per-test-server isolation); Customer calls thread real customer IDs via `make_customer_headers`.

## Step 6: Generate Implementation — 2026-08-12T23:23:00.000Z

Implementation complete and verified. Summary:

## File inventory (all under `/home/ubuntu/github/CodingPRD/tasks/task_1320_riverboat_dinner_cruise_operations/workspace/implementation/`)

- `start.sh` — executable launcher; guards `pip install` behind a `python3 -c "import flask"` check, then `exec python3 app.py` (foreground, `$PORT` default 10000, binds `0.0.0.0`)
- `requirements.txt` — `flask>=2.2`
- `app.py` — Flask entry, blueprint registration, error handlers
- `clock.py` — logical clock (fixed startup default `2026-08-01T00:00:00Z`, never wall clock), ISO-8601 parse/serialize with 3 fractional digits
- `db.py` — in-memory dict stores for all 16 entity types; empty at every boot, zero seeding
- `errors.py` — full 36-error catalog with exact IDs and HTTP statuses
- `response.py` — envelope: `meta.{api_request_id (req_*), api_request_timestamp}`, `response_type`, `data`; pagination fields inside `meta` for lists; error shape `data.{error_id, message}`
- `serializers.py` — per-entity field whitelists so internal bookkeeping keys never leak
- `util.py` — auth header/RBAC ladder rungs 1–2, body-shape validation, pagination (limit default 10, min 1, max 100, offset 0), common validators
- `services/core.py` — all calculations, derived-counter recomputation, and cascades
- `routes/` — `core_entities.py` (clock, vessels, docks, menu tiers, staff, customers), `cruises.py`, `bookings.py`, `manifest.py`, `galley.py`, `staff_assignments.py`, `charter.py`, `weather.py`, `credits.py`, `dockops.py`

## Endpoint coverage: 77/77

Verified via Flask's URL map against the SCAFFOLD endpoint table (exactly 77 non-static routes registered).

## State machines implemented (9/9)
CruiseInstance (SCHEDULED→BOARDING→UNDERWAY→COMPLETED, WEATHER_HOLD cycle, weather-cancel from SCHEDULED/WEATHER_HOLD), Booking (dual parallel dimensions payment_status × booking_status), CharterInquiry (DRAFT→QUOTED⇄COUNTERED→ACCEPTED/DECLINED/EXPIRED/CONVERTED), BoardingManifest (DRAFT⇄FROZEN→FILED), GalleyProvisionOrder (DRAFT→PLACED→RECEIVED→SETTLED / CANCELLED), StaffAssignment, WeatherEvent, ParkingPass, Vessel (ACTIVE→OUT_OF_SERVICE). CruiseCredit status transitions (ISSUED→SETTLED→REDEEMED) also implemented.

## Calculations implemented (7/7)
Ticket pricing (tiered 15/10/5% party discount → 1.25/1.10/1.00 seasonal → +1500¢/pax holiday premium, round-half-up pinned at each step, Decimal arithmetic); bar package per-line gratuity (round 18% per package, then multiply); weather credit provisional (72/24/6-hour tiers at 100/75/50/25% of frozen total) and final (rebase + 300¢×provisional_covers rebate when the order was PLACED at cancellation, −450¢ fee); galley provisioning forward-looking provisional covers (RESERVED/CONFIRMED × PENDING/PAID, includes PENDING — deliberately differs from `reserved_covers`) vs chronological final covers (boarded passengers + CONFIRMED crew), load units at 2dp half-up; charter quote (49/99 capacity tiers → 350000/620000/980000 × season multiplier, single rounding; 88% conversion credit via 1−0.12); dock-slot conflict (same vessel across all docks, `a.start < b.end+45min AND b.start < a.end+45min`, strict inequality so adjacency at exactly end+45min is allowed); parking pool aggregate threshold (allowed iff `parking_in_use < capacity`).

## Key behaviors verified by smoke tests (178 assertions, all passing on fresh boots)
- OCC: `expected_cruise_version` on booking create and `expected_inquiry_version` on quote → `ERR_STALE_VERSION`/412; version bumps on every mutation including cascades
- Validation ladder ordering (auth → role → path-existence left-to-right → state → bookable → capacity → alcohol → slot conflict → parking → rounds → weather-event → credits-pending → SoD → OCC → manifest → covers → vessel-active)
- 6-step weather-cancel cascade, 4-part completion cascade, charter conversion cascade, quote TTL expiry at 48h via `POST /_clock/set_current_utc`, parking expiry at depart, no-show stranding, auto BOARDED advance, manifest snapshot semantics
- Response hygiene: `BookingPassenger`/`CruiseCredit` expose only `id`+`created_at` (no `updated_at`/`version`); internal fields stripped everywhere

## PRD ambiguities resolved
1. **Body-FK existence checks** (e.g., `home_dock_id` on vessel create, `customer_id` on booking): PRD's rung 3 covers path ids only; I check body FKs after shape validation and before business rules, returning the matching `ERR_*_NOT_FOUND` (404).
2. **`ERR_WEATHER_EVENT_ACTIVE` scope**: PRD narrative says clearing is permitted while the covering event is `DECLARED` or `CLOSED`; I reject for *any* covering event outside that pair (covers both `CANCELLATION_ISSUED` and `CREDITS_SETTLED`), which is the literal reading.
3. **Quote/counter segregation of duties**: SCAFFOLD validation 13 says "quote poster != counter poster"; I enforce actor alternation via a `last_actor_user_id` tracked on the inquiry (403 on consecutive same-actor actions), while the convert-vs-accept check compares X-User-IDs per the explicit PRD §3.9 rule.
4. **Quote TTL instant**: tracked `quoted_at_dt` at each quote; inquiry expires when `now > quoted_at + 48h` (PRD says "passes 48 hours after the quote was posted" — strict greater-than).
5. **Hours-of-notice**: whole hours via floor of `(depart_at − logical_now).total_seconds()/3600`.
6. **No-input action endpoints**: an entirely absent body is tolerated as `{}`; malformed JSON or unexpected fields are `ERR_INVALID_REQUEST`.
7. **`ERR_CREDITS_NOT_PENDING`**: unreachable in practice (only settle moves bookings out of REFUND_PENDING, and settle then advances the event) — implemented defensively per the scaffold.
8. **DockSlot/WeatherEvent window "covering" test**: inclusive on both ends (`window_start <= depart_at <= window_end`), the natural reading of "falls inside the window."

## Step 7: Run Tests and Iterate — 2026-08-12T23:48:00.000Z

Clean 8-round parallel sweep achieved: 85/85 passed in every round, zero failures/errors in the union.

## Summary

**Iterations run:** 3 sweeps (24 round-trips total). Sweep 1: 9-test union failing (75-76/85). Sweep 2: 1 deterministic failure (84/85 all rounds). Sweep 3: 85/85 in all 8 rounds.

**Tests deleted:** none — every failing test traced to verbatim PRD prose.

**Fixes applied to `test_helpers/`:** none — fixtures/factories were PRD-consistent (the OCC failures came from tests reusing a stale cruise-version snapshot, which the fixtures correctly passed through).

**Fixes applied to `test_suite/`** (all at `/home/ubuntu/github/CodingPRD/tasks/task_1320_riverboat_dinner_cruise_operations/test_suite/`):
- `test_02_bookings_capacity_occ.py` — added missing `create_paid_booking` import (NameError in `test_stale_version_precedes_capacity_when_both_fail`).
- `test_03_boarding_manifest_voyage.py` — added missing `get_manifest` import (NameError in `test_manifest_freeze_capacity_gate_and_reopen`).
- `test_04_weather_credits_cascade.py` — added missing `create_booking` import (NameError in `test_customer_cancelled_booking_untouched_by_cascade`).
- `test_01_ticket_pricing.py` (2 tests) and `test_07_galley_staffing_compliance.py` (1 test) — re-read cruise version via `get_cruise(...)` after `assign_confirmed_bartender` before using it as the OCC token. PRD §2.10 requires the confirm-driven `bar_service_enabled` recomputation to bump the cruise version, so the pre-assignment snapshot was legitimately stale; the implementation was correct to return ERR_STALE_VERSION.
- `test_06_shoreside_dock_parking.py` (`test_buffer_adjacency_boundary`) and `test_08_platform_and_fleet.py` (`test_clock_set_reports_new_reading`) — replaced exact-string timestamp equality with instant equality (STEP 1c partial coverage: PRD pins the adjacency boundary and the reported clock reading, but is silent on the string rendering of user-supplied instants; the implementation normalizes to the §2.5 three-fractional-digit house style, which a PRD-faithful reader could equally produce).

**Fixes applied to `implementation/`** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1320_riverboat_dinner_cruise_operations/workspace/implementation/`):
- `services/core.py` `process_auto_transitions` — now recomputes `bar_service_enabled` for every cruise on clock set (PRD §3.4 verbatim: "advancing time can silently flip the flag even with no staffing change"; §2.4: clock set re-evaluates time-based transitions). Fixes `test_bar_service_flag_follows_clock_past_cert_expiry`.
- `services/core.py` `weather_cancel_cascade` — booking sweep now excludes `CANCELLED` bookings, honoring PRD §3.8's "Bookings already cancelled by their customers are untouched by the cascade" (previously an unpaid customer-cancelled booking at PENDING was wrongly swept to REFUND_PENDING).
- `start.sh` — flask-presence check switched from `import flask` to `importlib.util.find_spec`, cutting ~0.25s unloaded (more under load) per per-test server reboot; the 15s-restart-window boot flakes seen in sweep 1 (e.g. `test_pay_moves_reserved_booking_to_confirmed` erroring in 4/8 rounds) did not recur in sweeps 2-3.

## Step 8: Finalize PRD — 2026-08-12T23:56:00.000Z

Done. `PRD_FINALIZED.md` written with exactly one inserted paragraph; all other prose verbatim.

## Summary

**Line counts:** PRD.md = 379 lines, PRD_FINALIZED.md = 381 lines (+2 lines, +0.53%). Diff is a single paragraph insertion at end of §2.5.

**Changes (1 total):**
- **§2.5 — insert** — new paragraph pinning the canonical instant rendering: UTC, exactly three fractional digits, `Z` suffix; server-stamped instants (`created_at`, `updated_at`, `declared_at`, `boarded_at`) always in this style; user-supplied instant fields (cruise `depart_at`/`return_at`, dock slot `slot_start`/`slot_end`, weather `window_start`/`window_end`) parsed from any ISO 8601 form, converted to UTC, stored and returned in canonical form; clock-set reports `current_utc` in the same style — impl: `implementation/clock.py:20-23` (`to_z`), `implementation/routes/cruises.py:52`, `implementation/routes/dockops.py:58`, `implementation/routes/weather.py:37-38`, `implementation/routes/core_entities.py:37`.

**Step 7 items requiring no edit (verified against prose):**
- Three missing-import test fixes — pure test bugs.
- OCC re-read fixes (test_01, test_07) — already pinned: §2.10 lists `bar_service_enabled` among derived counters and states each recomputation "increments `version` per §2.5"; §3.4 says confirmation "recomputes the cruise's `bar_service_enabled`". Matches `recompute_bar_service` → `touch(cruise)` (`implementation/services/core.py:143-153`, called from `implementation/routes/staff_assignments.py:85`).
- `bar_service_enabled` on clock set — already pinned by §3.4 ("advancing time can silently flip the flag even with no staffing change") + §2.4 ("Setting the clock re-evaluates all time-based automatic transitions") + §2.10 ("never lazily at read time"). Matches `process_auto_transitions` (`implementation/services/core.py:253-254`).
- Weather-cascade CANCELLED exclusion — pinned verbatim by §3.8 step 1 ("Bookings already cancelled by their customers are untouched by the cascade"). Matches `implementation/services/core.py:300-302`.
- `start.sh` flask check — not PRD-visible.

**Per-edit pre-edit search log (1 edit):**
- (a) Subject: string rendering of user-supplied instant fields on storage and in responses, plus the clock-set reading.
- (b) Impl paths enumerated and read: `clock.py:20-36` (`to_z`/`parse_dt`); `routes/cruises.py:29-52` (depart_at/return_at normalized); `routes/dockops.py:32-58` (slot_start/slot_end normalized); `routes/weather.py:26-38` (window_start/window_end normalized); `routes/core_entities.py:28-37` (clock set → `current_utc` via `to_z`); `routes/core_entities.py:200-204` (`alcohol_cert_expires_at` stored **verbatim**, only validated); `routes/bookings.py:128-137` (`date_of_birth` stored verbatim); `serializers.py` (pass-through, no re-rendering); server stamps `util.py:92-96`, `weather.py:35`, `bookings.py:204`, `services/core.py:391`; all comparison sites re-parse stored strings (`weather_events_covering`, `hold_covered_cruises`, `close_weather_event`, `recompute_bar_service`, cert check at `staff_assignments.py:80`, `_hours_notice`, `is_minor_dob`) — rendering-independent; `response.py:13-15` (envelope `api_request_timestamp` already in the three-fractional-digit style, consistent with §2.2).
- (c) Wording adjustment: the Step 7 guidance phrasing ("normalizes all timestamps") would have been a false universal — `alcohol_cert_expires_at` and `date_of_birth` are stored verbatim. The committed sentence therefore enumerates exactly the normalized fields (cruise, dock slot, weather window, clock `current_utc`) instead of claiming all user-supplied instants, and adds that comparisons operate on the parsed instant so equivalent input strings behave identically.

## Step 9: Complete PRD — 2026-08-13T00:12:00.000Z

Done. `PRD_COMPLETED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1320_riverboat_dinner_cruise_operations/workspace/PRD_COMPLETED.md`.

**Size:** PRD_FINALIZED.md 381 lines / 56,311 chars → PRD_COMPLETED.md 383 lines / 60,907 chars (char-delta +4,596). All edits are in-paragraph inserts/revisions; no new sections (the only +2 lines come from splitting the cascade-closing sentence onto its own line after the §3.8 numbered list).

**Counts:** 20 ambiguity-pins, 2 mismatch-revisions (22 changed passages total).

**Changes:**
- §2.1 — revise — mismatch — PRD said "one controlled step" compares operator identifiers (conversion); impl also compares X-User-IDs on quote/counter alternation, so revised to "two controlled steps ... as opaque strings" — `routes/charter.py:100,124,170`
- §2.1 — insert — ambiguity — no endpoint enforces per-resource ownership; body `customer_id` need not equal caller's `X-User-ID` — `routes/bookings.py:40-49,145-184`, `routes/credits.py:22-32`, `routes/charter.py:115-156`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`, negative `offset` → `ERR_INVALID_REQUEST` — `implementation/util.py:52-81`
- §2.3 — insert — ambiguity — enum filter value outside the field's enum → `ERR_INVALID_REQUEST` — `routes/core_entities.py:293-300`, `routes/cruises.py:75-76`, `routes/bookings.py:89-92`
- §2.4 — revise — mismatch — "wall clock is never consulted" contradicted by envelope `api_request_timestamp` reading the wall clock; carved out as transport metadata — `implementation/response.py:13-15`
- §2.5 — insert — ambiguity — `version` starts at 1 on creation, `updated_at` == `created_at` — `routes/core_entities.py:19-21`
- §2.7 — insert — ambiguity — nested IDs must resolve within parent (passenger under wrong booking → `ERR_PASSENGER_NOT_FOUND`; order/assignment under wrong cruise likewise) — `routes/bookings.py:191-194`, `routes/galley.py:78-84`, `routes/staff_assignments.py:60-66`
- §2.7 — insert — ambiguity — body-FK existence checks after shape/parent-path validation, returning matching `ERR_*_NOT_FOUND`, with pairwise check order pinned (vessel→menu tier, cruise→customer, booking→cruise) — `routes/cruises.py:36-43`, `routes/bookings.py:46-49`, `routes/charter.py:29-36`, `routes/dockops.py:38-41,94-101`, `routes/staff_assignments.py:29-32`, `routes/core_entities.py:50`
- §2.8 — insert — ambiguity — shape rules extended: non-object JSON, undeclared fields, null required fields → `ERR_INVALID_REQUEST`; absent body tolerated as `{}`; body-ignoring no-input actions noted — `implementation/util.py:29-49`
- §2.8 — insert — ambiguity — nested creation endpoints (dock slots, parking passes, staff assignments, passengers) establish parent existence before parsing body; booking creation validates shape first — `routes/dockops.py:27-28,88-89`, `routes/staff_assignments.py:23-24`, `routes/bookings.py:24-45,125-126`
- §3.1 — insert — ambiguity — `parking_capacity`, `coast_guard_capacity`, `base_price_cents`, `bar_package_price_cents` must be non-negative integers — `implementation/util.py:106-112`, `routes/core_entities.py:49,93,154-156`
- §3.3 — insert — ambiguity — explicit null `bar_package_count` treated as omitted (default 0) — `routes/bookings.py:30-32`
- §3.3 — insert — ambiguity — `date_of_birth` must be `YYYY-MM-DD` else `ERR_INVALID_REQUEST` — `routes/bookings.py:128-130`
- §3.3 — insert — ambiguity — unpaid customer-cancel keeps `payment_status` `PENDING` — `routes/bookings.py:179-181`
- §3.5 — insert — ambiguity — second non-cancelled provision order for a cruise → `ERR_INVALID_STATE` — `routes/galley.py:44-46`
- §3.5 — insert — ambiguity — placement recomputes load from the creation-time `provisional_covers` snapshot (not re-taken) — `routes/galley.py:98`
- §3.6 — insert — ambiguity — check-in of an already-boarded passenger → `ERR_INVALID_STATE` — `routes/bookings.py:198-199`
- §3.7 — insert — ambiguity — parking-pass `booking_id`/`cruise_id` validated for existence only; no booking↔cruise consistency or cruise-state precondition at creation — `routes/dockops.py:94-104`
- §3.8 — insert — ambiguity — weather-window covering test inclusive on both ends — `services/core.py:202-209`
- §3.8 — insert — ambiguity — clear-weather-hold rejects when *any* covering event (multiple coverage) is neither `DECLARED` nor `CLOSED` — `routes/cruises.py:157-161`
- §3.8 — insert — ambiguity — hours-of-notice is floor of whole hours (71.9h → 71) — `services/core.py:261-263`
- §3.8 — insert — ambiguity — weather-cancel cascade explicitly lands the cruise in `CANCELLED` — `services/core.py:353-355`
- §3.8 — insert — ambiguity — final-credit base recomputes hours-of-notice against the settlement-time clock — `services/core.py:280-281`
- §3.8 — insert — ambiguity — no transition ever moves a credit to `EXPIRED` — (impl-wide; `routes/credits.py` has only redeem)
- §3.9 — insert — ambiguity — actor-alternation mechanism: server records latest quote/counter `X-User-ID`; consecutive same-ID quote/counter → `ERR_SEGREGATION_OF_DUTIES`; opening quote exempt — `routes/charter.py:99-102,124-126`
- §3.9 — insert — ambiguity — quote TTL strict-greater-than: exactly 48h has not lapsed — `services/core.py:248-252`
- §3.9 — insert — ambiguity — charter booking's `booking_total_cents` = accepted `quoted_total_cents`, `bar_package_count`/`bar_package_total_cents` zero — `services/core.py:468-482`

All prompt-flagged items (body-FK 404s after shape, `ERR_WEATHER_EVENT_ACTIVE` scoping, actor-alternation vs convert-vs-accept comparison, 48h strict TTL, floor of whole hours, absent-body tolerance, inclusive weather window) are now pinned. Ladder rung ordering was verified endpoint-by-endpoint against the PRD's stated order (e.g., capacity rung 6 before OCC rung 14 on booking creation; SoD rung 13 before OCC rung 14 on quoting) and needed no changes.

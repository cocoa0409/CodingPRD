# Worklog — task_1384_track_rental_test_day_operations

Scenario: Track Rental & Test Day Operations (road course track rental): rental block booking & group size limits, insurance requirement & waiver collection, instructor/coach assignment & run-group classification, on-track incident response & session stoppage, noise limit & neighbor compliance monitoring, garage/paddock allocation & utilities, safety equipment inspection (helmet/harness), cancellation & weather policy

Difficulty request: harder than expert level.

## Step 1: Create Task Directory — 2026-08-13T02:58:00.000Z

Task directory `tasks/task_1384_track_rental_test_day_operations/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T03:26:00.000Z

Clean lint. Final summary:

**Files written** (all three lint-clean):
- `tasks/task_1384_track_rental_test_day_operations/SCAFFOLD.yaml`
- `tasks/task_1384_track_rental_test_day_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `tasks/task_1384_track_rental_test_day_operations/SCAFFOLD_CORNER_DESIGN.yaml`

**Counts**
- Entities: **13** (Track, Coach, TrackDay, RentalBlock, Booking, Driver, Waiver, SafetyInspection, Session, Incident, NoiseReading, GarageAssignment, PaddockAssignment)
- State machines: **8** (TrackDay, RentalBlock, Booking, Driver, Session, Incident, GarageAssignment, PaddockAssignment)
- Calculations: **8** declared (rental_block_seats_available, trackday_posture, cancel_refund_cents, trackday_posture_noise_window, run_group_assignment_priority, noise_breach_db, garage_utility_fee_cents, coach_utilization)
- Validations: **20** priority rows across auth / existence / state / business_safety / business_referential / business_temporal / business_constraint / business_fiscal
- Endpoints: **79** (primary nested API + flat canonical lookup/list aliases for FK reverse-reachability)
- Errors: **20** error codes
- Roles: **4** (TrackOps, SafetyOfficer, Organizer, Coach)
- Concurrency rules: **3** OCC rules (booking-approve on RentalBlock.version, trackday-resume on TrackDay.version, garage-assign on TrackDay.version)

**Difficulty instances (§1.8)**: **18** (9 rules × 2 instances, meeting minimums)
**Corner instances (§1.9)**: **38** active + 4 excluded_because stubs

**Linter verdict**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (438 calls scanned, 0 violations). Independently re-verified by orchestrator: clean.

**Notable design decisions**
1. Archetype blend: Quota/allocation (RentalBlock seats, garage bays, paddock stalls, coach slots) × Posture-driven gating (TrackDay.posture derived from weather_flag, open incidents, noise breaches) — every forward-progress op gated on posture.
2. Segregation of duties as the role model: SafetyInspector ≠ Booking.organizer; Incident.cleared_by ≠ reported_by.
3. Three-variant cancel_refund_cents (chronological / weather / safety) — two genuinely divergent algorithms on the same inputs.
4. Tiered pricing with pinned rounding order for garage utility fee; noise-breach uses strict `>`; RentalBlock half-open `[start,end)` interval semantics vs GarageAssignment discrete slot occupancy.
5. TrackDay state machine cyclic (RUNNING↔STOPPED) plus posture-driven (compound derived field); Session fork-join branching with three divergent successors from GREEN; Booking parallel approval_status × payment_status dimensions.
6. OCC only where true races live (RentalBlock seat allocation, TrackDay resume, garage-bay assign).
7. Flat lookup aliases (`/tracks/<collection>/{id}` + filtered list) added alongside the nested primary API for FK reverse-reachability.
8. `/_clock/set_current_utc` and `/_payments/simulate` are the only test-driving endpoints.
9. `Booking.refund_cents` declared as a computed field so §1.8 `$.data.refund_cents` capture resolves against §1.1.

Orchestrator note: subagent required three resumes (it kept stopping mid-work after planning turns); completed lint-clean on the fourth invocation.

## Step 3: Copy Shared Files — 2026-08-13T03:27:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1384_track_rental_test_day_operations/workspace/INSTRUCTION.md (bash, no subagent).

## Step 4: Generate PRD — 2026-08-13T03:47:00.000Z

PRD generation is complete. `workspace/PRD.md` exists on disk — 329 lines, generated solely from `SCAFFOLD.yaml` (the difficulty/corner index files were never opened).

## Section list

- **§1. Introduction** (2 paragraphs — business context + system scope)
- **§2. Global Specifications & System-Wide Principles**
  - 2.1 User and Role-Based Access Control (headers, 4 roles, per-role `identity:` prose including entity-backed Coach)
  - 2.2 API Response Structure (emitted byte-for-byte verbatim from `section-2.2-response-structure.md`, verified programmatically)
  - 2.3 Pagination (limit default 10 / min 1 / max 100, offset default 0, `created_at` ascending, meta fields)
  - 2.4 Resource Identity, Timestamps, Versioning, and the Logical Clock (UUID ids, 3-fractional-digit ISO 8601, `version` semantics, append-only Waiver/SafetyInspection/NoiseReading exception, clock start 2026-08-01T00:00:00Z)
  - 2.5 Nested Resource Paths and Flat Lookup Aliases (left-to-right `ERR_NOT_FOUND`, all flat-list filters enumerated)
  - 2.6 Optimistic Concurrency Control (all 3 OCC rules with `expected_rental_block_version` / `expected_track_day_version` → `ERR_STALE_VERSION` 412)
  - 2.7 Track-Day Posture and Forward-Progress Gating
  - 2.8 Money, Fees, and Rounding (integer cents, round half-up)
  - 2.9 Validation Order and Error Selection (all 20 priorities as an explicit ordered ladder with `applies_to` scopes)
- **§3. Business Logic & Workflows** — 9 subsections: 3.1 Venue Setup & Coaching Roster, 3.2 Test Days & Rental Blocks, 3.3 Bookings/Approval/Payment, 3.4 Drivers/Waivers/Inspection, 3.5 Sessions & Race Control, 3.6 Incidents/Weather/Posture, 3.7 Noise Compliance, 3.8 Garage & Paddock, 3.9 Cancellation/Refunds/Close
- **§4. Endpoint Definitions** — 4-column table, all **79 endpoints** (55 hierarchical + 24 flat aliases), verified 1:1 against the scaffold
- **§5. Error Code Catalogue** — 2-column table, all **20 error IDs**

## Hard Contract Reports

Field coverage: entities[].fields 69/69 present; endpoints[].input 48/48; path_params 13/13. Status: PASS

Rule coverage: validations 20/20 in §2.9 ladder + per-endpoint §3 orderings; OCC rejections 3/3; state machines 8/8 with all transitions + side effects (incl. RUNNING→STOPPED weather-STOP trigger added after the walk flagged it); calculations 8/8 in precise prose (seat aggregation floor-at-0, 5-rung posture ladder thresholds 1/3 + 60-min window, 3 refund variants with 72/24-hour tiers, 75%-minus-5000 weather rule, AUTHORIZED-void override, run-group priority NOVICE>INTERMEDIATE>ADVANCED>RACE then created_at asc, strict-greater breach, tiered garage fee 15000/2500/4000/3000, coach max-3 utilization); validations→error_id 20/20; endpoint side_effects 79/79; entity field semantics 69/69; sibling-branch symmetry 6/6 groups. Status: PASS

Path purity (§3): 469 backtick tokens scanned, 0 path/method leakage. Status: PASS

All 20 error IDs appear in §2/§3 prose; all 22 state values and 44 enum values verified present as exact strings. The two unpinned scaffold constants (`WAIVER_TTL_HOURS`, `MIN_LAPS_FOR_CHECKERED`) are carried as symbolic names since the scaffold defines no values for them. (Orchestrator verified: SCAFFOLD.yaml lines 140/474 reference them without defining values.)

## Step 5: Generate Unit Tests — 2026-08-13T04:14:00.000Z

Generation complete. Both directories are populated and all skill-specified validation stages pass.

## Test counts

**Total: 68 tests collected** (pytest collection passes cleanly)

**Queue A (Difficulty): 32 tests** covering 16 of 18 instances (≥2 each):
- `test_03_rental_blocks_and_seats.py` — 6 (half-open overlap ×2, seats-zero boundary ×2, seats conservation ×2)
- `test_04_booking_approval_payments_refunds.py` — 8 (posture-gated approve ×2, chronological-vs-weather refund ×2, nested rounding ×2, cancel→coach/block-reopen cascade ×2)
- `test_05_drivers_waivers_coaches.py` — 4 (clearance gating ×2, coach-roll conservation ×2)
- `test_06_sessions_noise_posture.py` — 6 (noise strict-> boundary ×2, posture multibranch ×2, posture-vs-cert priority ×2)
- `test_07_incidents_day_lifecycle.py` — 6 (stop/resume cycle ×2, session GREEN/RED/BLACK branching ×2, incident cascade ×2)
- `test_08_garage_assignments.py` — 2 (bay slot occupancy ×2)

**Queue B (Corner): 36 tests** covering all 36 translated non-stub instances (1 each) across the same 8 files (`test_01_venue_setup_and_envelope.py` 8, `test_02_auth_and_rbac.py` 5, `test_03` 5, `test_04` 3, `test_05` 6, `test_06` 1, `test_07` 7, `test_08` 1).

## Instances skipped (PRD-first filter failures — gaps left as gaps)

- **Difficulty `dual_variant_calc/garage_utility_fee_tiered_vs_flat_paddock`** — the utility fee's only PRD mention is inside the §3.8 formula prose ("computed and added to the booking"); no response field is ever named, so the fee value is not uniquely derivable/observable (computed-field silence pattern).
- **Difficulty `priority_pair_validation_conflict/state_vs_business_temporal_pair`** — PRD §2.7/§2.9 item 6 do not list rental-block creation among liveness-gated writes, so a PRD-only implementer could legitimately return `ERR_BLOCK_OVERLAP` instead of `ERR_TRACK_DAY_NOT_LIVE`/`ERR_INVALID_STATE` on a cancelled day.
- **Corner `calculations/garage_utility_constants_applied`** — same fee-observability gap.
- **Corner `state_machines/rentalblock_closed_blocks_new_booking`** — PRD never states that booking creation on a CLOSED block is rejected nor which `error_id` would result.
- 4 `excluded_because:` stubs in the errors section not translated per rule (note: `err_invalid_request_malformed_enum`'s `difficulty_instance` pointer targets a corner instance, not a difficulty one — a corner-design bug; stub skipped without placeholder).

## Recipe corrections made during translation (PRD governs)

- `WEATHER` day-cancels in the A1/A4/B36 recipes were issued from `OPEN`, which PRD §3.9 forbids ("From `WEATHER_HOLD`, the day may be cancelled with `reason` `WEATHER`"); a `weather_hold` call was inserted first.
- A6's direct OPEN→CLEARED clear of a MEDIUM incident violates PRD §3.6 (direct clear only for `LOW`); replaced with investigate→clear.
- Waiver-expiry test jumps the clock to 2030 (PRD omits the `WAIVER_TTL_HOURS` value; the jump exceeds any plausible TTL).
- OCC-guarded calls always re-read the parent version fresh in fixtures; payment_status post-cancel values (FORFEITED/REFUNDED) are never asserted since the PRD does not pin them.

## Validation stages passed

- Stage 1 `test_helpers/` fully written (9 modules, 83 endpoint methods, error map registered) and imports cleanly.
- Stage 2 `test_suite/` written after Stage 1; `pytest --collect-only` = 68 tests, no import errors.
- Coverage audit: every translated difficulty instance has exactly ≥2 tagged tests; every translated corner instance ≥1; stubs have 0.
- Citation pass: all 68 docstrings carry verbatim PRD quotes (automated ≥8-word grep check passed for every test), exactly one terminal `Design:` line each, all resolving to real instances in the source YAMLs; no skip/xfail markers anywhere.

## Step 6: Generate Implementation — 2026-08-13T04:14:30.000Z

Implementation complete. Summary:

## Files created (all under `workspace/implementation/`)

- `start.sh` — executable launcher; guarded dependency install (`pip install` only if flask import fails), `exec python3 app.py` in foreground, honors `PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — Flask entry point, blueprint registration, error handlers (ApiError, 404/405, catch-all)
- `db.py` — in-memory dict stores for all 13 entity types + logical clock (starts at 2026-08-01T00:00:00.000Z); zero seeding — store is empty on every boot
- `errors.py` — ApiError + factory per error_id with exact HTTP statuses from the catalog
- `response.py` — envelope: `meta{api_request_id(req_…), api_request_timestamp(3-fractional-digit ISO)}`, `response_type` (object/array/error), `data`; list meta adds `limit/offset/total_count/has_more`
- `helpers.py` — auth (X-User-Role / X-User-ID), body/query validation, strict left-to-right nested path resolution with parent scoping, posture ladder, seat aggregation, noise 60-minute window, refund math (Decimal ROUND_HALF_UP), garage tiered fee, serializers
- `routes_core.py` — `/_clock/set_current_utc`, `/_payments/simulate`
- `routes_tracks.py` — tracks, coaches, track-days + open/weather_hold/weather_clear/resume/cancel/close/run_ops, rental-blocks + close_block
- `routes_bookings.py` — bookings + approve/reject/cancel/assign_coach, drivers, waivers, inspections
- `routes_ops.py` — sessions + checkered/lap_event, incidents + investigate/clear, noise-readings, garage/paddock assignments + release
- `routes_flat.py` — all 24 flat lookup + filtered-list aliases

## Endpoint count
79 routes registered (53 nested/test-driving endpoints + 24 flat aliases + clock + payments), matching the PRD §4 table exactly.

## Key semantics implemented
Validation priority 1→20 (auth → role → path existence → body shape → OCC 412 → liveness → state → posture → SoD → driver clearance → coach cert/load → overlap/occupancy → caps → seats → insurance); three OCC guards (`expected_rental_block_version` on approve, `expected_track_day_version` on resume and garage create); posture ladder with weather/incident/noise ordering; severity-driven session/day cascades (MEDIUM+ → session RED, HIGH/CRITICAL → day STOPPED); day-cancel door discipline per status with reason-forced refund variants (chronological 72/24h tiers, weather 75%−5000 floor 0, safety 100%, AUTHORIZED-void override → 0); booking-cancel unwind (seats, assignments RELEASED, coach detach, refund snapshot); waiver expiry sweep via run_ops; segregation-of-duties on inspect/clear with state-check-first ordering; half-open block overlap (adjacent allowed, overlap checked before capacity per PRD §3.2); strict `db_level > noise_limit_db` breach; tiered garage utility fee; coach cert matrix (NOVICE≥INTERMEDIATE, RACE=RACE) and 3-booking/day load cap.

## Smoke-test result
Booted via `bash start.sh` on a fresh process and verified: empty store at boot, envelope shapes, 0.0.0.0 external binding. Two scenario suites (132 assertions total) executed against the running server — all passing, covering the full lifecycle: track/day/block/booking/driver setup, approvals with OCC staleness, payment walk to cleared_to_run, incident stop/resume cycle, weather hold/clear/cancel, noise-window suspension and expiry, refund tiers, occupancy conflicts, coach cert/overload, driver-clearance lap gating, close-out, pagination, and flat-alias RBAC (incidents restricted to TrackOps/SafetyOfficer). Test scaffolding processes were cleaned up afterward.

## Step 7: Test/Iterate Loop — Iteration 1 — 2026-08-13T04:25:00.000Z

First 8-round parallel sweep: 62/68 in all 8 rounds, identical failure sets (deterministic, not flaky).

**Union of failures (6 tests) and dispositions:**

1. `test_02_auth_and_rbac.py::test_safety_officer_resume_is_permitted` — `NameError: setup_stopped_day_via_incident`.
   STEP 1: PRD §3.6 covers resume verbatim; uniquely derivable. STEP 2: TEST IS WRONG — missing import in the
   test file's import block. FIX (test_suite): added `setup_stopped_day_via_incident` to the
   `from test_helpers import (...)` list in `test_02_auth_and_rbac.py`.
2. `test_05_drivers_waivers_coaches.py::test_waiver_computed_expires_at_utc` — `Waiver.id must be a valid UUID`.
3. `test_05_drivers_waivers_coaches.py::test_safety_inspection_computed_result` — `SafetyInspection.id must be a valid UUID`.
   STEP 1: PRD §2.4 "a server-minted UUID with no type prefix" — covered; canonical RFC-4122 dashed form is the
   unique reading (shared `is_valid_uuid` assertion library encodes it). STEP 2: tests faithful.
   STEP 3: FIX (implementation): `uuid.uuid4().hex` → `str(uuid.uuid4())` at all 13 minting sites across
   `routes_tracks.py`, `routes_bookings.py`, `routes_ops.py`.
4. `test_01::test_track_creation_returns_201_with_defaults`, `test_01::test_coach_default_active_true`,
   `test_07::test_critical_incident_cascades_day_stop_and_sessions_red` — setup-phase "API server could not be
   restarted" (15s health-poll exhaustion), identical indices in all 8 lockstep rounds; host runs 5 other
   pipelines concurrently. Boot-timeout infrastructure flakes, not assertion failures. Mitigation
   (implementation/start.sh): replaced the per-boot `python3 -c "import flask"` guard (~0.4s) with a fast
   `importlib.util.find_spec` check (~50ms); install-on-missing behavior unchanged.

Post-fix smoke (single round): 68/68. Proceeding to full 8-round verification sweep.

Verification sweep 2 (post-fix): 67/68 × 8 — sole failure `test_rejected_approve_leaves_booking_and_block_untouched`
at idx 28 in every round, setup-phase "could not be restarted" (15s health-poll exhaustion), different ports per
round, solo re-run passes 68/68, host CPU mostly idle: diagnosed as external boot-storm contention from the
concurrently running sibling pipelines (boot-timeout-only failure class — re-run permitted per protocol).

Verification sweep 3 (no further code changes): **68/68 in all 8 parallel rounds — CLEAN SWEEP.**

Iteration 1 totals: 2 test-artifact fixes (1 test_suite import, 0 test_helpers), 1 implementation fix
(UUID canonical form, 13 sites), 1 implementation robustness fix (start.sh find_spec guard). 0 tests deleted.

## Step 7: Run Tests and Iterate — 2026-08-13T04:35:00.000Z

Clean 8-round parallel sweep achieved: **68/68 tests passing in all 8 rounds** (sweep 3, after fixes). Orchestrator independently verified all 8 results files: 68/68 each.

**Iterations run:** 1 fix iteration + 3 sweeps (initial diagnostic sweep, post-fix sweep hitting an environmental boot-storm, final clean verification sweep).

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**
- `test_suite/test_02_auth_and_rbac.py` — added missing `setup_stopped_day_via_incident` to the `from test_helpers import (...)` list; `test_safety_officer_resume_is_permitted` used the helper without importing it (NameError in all 8 rounds). Test logic itself faithfully expresses PRD §3.6 resume semantics.

**Fixes applied to `test_helpers/`:** none needed (fixtures/factories/headers all PRD-consistent).

**Fixes applied to `implementation/`:**
- `routes_tracks.py`, `routes_bookings.py`, `routes_ops.py` — replaced `uuid.uuid4().hex` with `str(uuid.uuid4())` at all 13 id-minting sites. The undashed hex form failed the canonical-UUID assertion shared by the runner's `is_valid_uuid` (PRD §2.4: "a server-minted UUID with no type prefix"). This fixed `test_waiver_computed_expires_at_utc` and `test_safety_inspection_computed_result`, and pre-empted the same failure in `test_track_creation_returns_201_with_defaults` (its UUID assertion was previously masked by a boot error).
- `start.sh` — swapped the per-boot `python3 -c "import flask"` guard (~0.4 s) for `importlib.util.find_spec('flask')` (~50 ms), cutting server boot to ~0.75 s and reducing exposure to the runner's fixed 15 s per-test restart window under host contention. Install-on-missing behavior unchanged.

**Boot-timeout failures (no code defect):** the remaining failures in sweeps 1–2 (`test_track_creation…`, `test_coach_default_active_true`, `test_critical_incident_cascades…`, `test_rejected_approve_leaves_booking_and_block_untouched`) were all setup-phase "API server could not be restarted" 15 s poll exhaustions — never assertion failures — with the failing index moving between sweeps (0/2/59 → 28 → none) as sibling pipeline load shifted. Per the protocol's boot-timeout provision, the sweep was re-run; the final sweep passed 68/68 in all 8 parallel rounds with zero failures of any kind.

## Step 8: Finalize PRD — 2026-08-13T04:38:00.000Z

Done. `workspace/PRD_FINALIZED.md` written with exactly one in-place revision.

**Line counts / delta:** PRD.md 329 lines, PRD_FINALIZED.md 329 lines — 0% line-count delta (one line revised in place, +23 words on that line).

**Changes:**
- §2.4 — revise — the resource-`id` clause now reads "a server-minted UUID with no type prefix, rendered in its canonical hyphenated text form (`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`, lowercase hexadecimal)", pinning the serialization the Step 7 fix converged on — `routes_tracks.py:25,56,105,331`; `routes_bookings.py:87,238,287,332`; `routes_ops.py:49,141,244,317,399` (all `str(uuid.uuid4())`).

**Step 7 items not turned into edits, with justification:**
- `test_02_auth_and_rbac.py` missing-import fix — pure test-suite bug (NameError); no PRD silence or mismatch.
- `start.sh` flask-import guard swap — harness/boot plumbing only; zero API-visible behavior, so a PRD edit would be inappropriate.

**Per-edit pre-edit search log (the single edit):**
- (a) Subject: wire format of server-minted persisted-resource `id` fields.
- (b) Impl paths enumerated: all 13 minting sites listed above (verified uniform `str(uuid.uuid4())` across every resource type, including the three append-only types — waiver, inspection, noise reading — so the universal "Every persisted resource" framing stays accurate); `routes_flat.py` (read-only, returns stored ids as-is — consistent); `routes_core.py` (payments/clock — mints nothing); `response.py:13` (`api_request_id` = `req_` + 20 alphanumerics — not a persisted-resource id, governed by §2.2's separate "starts with `req_`" clause, so the edit was kept strictly inside the §2.4 resource-id phrase); `helpers.py` (no inbound UUID-shape validation — path ids resolve by dict lookup, malformed ids yield `ERR_NOT_FOUND` per §2.5 — so the wording describes only server-minted output format and asserts no inbound validation rule).
- (c) Wording adjustments made: used the `xxxxxxxx-…` placeholder pattern instead of a fabricated literal UUID (avoids being read as a constant); omitted any UUID-version pinning (v4 was already the pre-fix choice and lies outside the Step 7 trace); omitted any claim about request-supplied id validation (impl performs none).

## Step 9: Complete PRD — 2026-08-13T04:45:00.000Z

Done. `PRD_COMPLETED.md` produced at `workspace/PRD_COMPLETED.md` as a minimal inline patch over `PRD_FINALIZED.md`.

**Source vs output:** PRD_FINALIZED.md 329 lines / 48,554 chars → PRD_COMPLETED.md 329 lines / 51,715 chars (char-delta +3,161; all changes are in-paragraph inserts/revisions, no new sections).

**Counts:** 13 ambiguity-pins, 3 mismatch-revisions (16 edited passages total, some bullets below bundle adjacent pins made in the same paragraph).

Changes:

- §3.1 — insert — ambiguity — pinned coach load counts only APPROVED bookings on the day; inactive-coach attachment rejected ERR_INVALID_REQUEST (400); unknown/cross-track `coach_id` at booking-create or assign_coach rejected ERR_NOT_FOUND (404) — implementation/helpers.py:385-394, routes_bookings.py:28-35, 67-70, 215-217
- §3.3 — insert — ambiguity — `insurance_policy_ref` may be omitted/null at creation; the presence check fires only at approval — implementation/routes_bookings.py:59-64, 161-162
- §3.3 — revise — mismatch — state gate said coach attached "exactly when" class is NOVICE (biconditional); impl requires coach only for NOVICE, other classes optional; also pinned booking-must-be-PENDING sub-check — implementation/routes_bookings.py:145-152
- §3.3 — insert — ambiguity — `cancel_policy_snapshot` response shape: keys `full_refund_hours` (72), `half_refund_hours` (24), `weather_facility_fee_cents` (5000), `fee_per_driver_cents` (35000) — implementation/routes_bookings.py:38-44
- §3.3 — insert — ambiguity — every payment-simulate outcome is valid only from its named source state (ERR_INVALID_STATE 409 otherwise); success returns 200 with the updated booking, version +1 — implementation/routes_core.py:35-57
- §3.4 — insert — ambiguity — pinned `WAIVER_TTL_HOURS` = 8,760 (24 × 365) — implementation/helpers.py:38
- §3.5 — insert — ambiguity — session start: cross-day/unknown `rental_block_id` → ERR_NOT_FOUND (404); no day-status precondition beyond liveness/posture; OPEN→RUNNING cascade fires only from OPEN, other live statuses unchanged — implementation/routes_ops.py:39-47, 63-66
- §3.5 — insert — ambiguity — lap write: `driver_id` optional; unknown driver → ERR_NOT_FOUND (404); session version advances per lap; pinned `MIN_LAPS_FOR_CHECKERED` = 1 — implementation/routes_ops.py:100-121, helpers.py:39
- §3.6 — insert — ambiguity — incident report: `session_id` not on the day → ERR_NOT_FOUND (404) — implementation/routes_ops.py:22-26, 136
- §3.7 — insert — ambiguity — recording a noise reading recomputes breach count and posture in place but does not advance the day's `version`/`updated_at` — implementation/routes_ops.py:243-257
- §3.8 — insert — ambiguity — garage create: out-of-range `bay_number`/negative `power_hookups` → ERR_INVALID_REQUEST (400); unknown/cross-day `booking_id` → ERR_NOT_FOUND (404); utility fee exposed as response field `garage_utility_fee_cents` — implementation/routes_ops.py:291-300, helpers.py:646
- §3.8 — insert — ambiguity — paddock create: out-of-range `stall_number` → ERR_INVALID_REQUEST (400); unknown/cross-day `booking_id` → ERR_NOT_FOUND (404) — implementation/routes_ops.py:381-388
- §3.9 — insert — ambiguity — organizer cancelling another's booking → ERR_FORBIDDEN_ROLE (403); `reason` when present must be CUSTOMER/WEATHER/SAFETY else ERR_INVALID_REQUEST (400) — implementation/routes_bookings.py:194-199
- §3.9 — revise — mismatch — PRD said nothing about `payment_status` on cancel; pinned impl: cancellation never moves `payment_status` (CAPTURED stays CAPTURED; AUTHORIZED stays AUTHORIZED) — implementation/helpers.py:434-454
- §3.9 — revise — mismatch — PRD said an AUTHORIZED booking's "authorization is voided instead"; impl writes no void transition — revised to "simply abandoned, `payment_status` remains `AUTHORIZED`" — implementation/helpers.py:410-412
- §3.9 — insert — ambiguity — day-cancel cascade scope: only bookings at APPROVED or PENDING cascade to CANCELLED (each through the standard unwind); REJECTED bookings untouched — implementation/routes_tracks.py:258-264

Verified no-change-needed items (already pinned): FEE_PER_DRIVER_CENTS 35,000 already stated in §3.9; garage fee tiers, refund variants/thresholds, posture ladder order, noise window boundary, seat/flipping rules, OCC guard fields, error ordering, and envelope/pagination semantics all match implementation as written.

# Worklog — task_1416_seasonal_tree_holiday_material_recycling

## Step 1: Create Task Directory — 2026-08-13T05:32:36.487Z

Task directory `tasks/task_1416_seasonal_tree_holiday_material_recycling/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Treated as DONE per instructions; no index scan performed, no other task_* directory touched. Difficulty target: harder than expert level.

## Step 2: Generate Scaffold — 2026-08-13T06:45:34.436Z

All three scaffold artifacts are generated, lint-clean, and self-consistent. Summary:

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1416_seasonal_tree_holiday_material_recycling/`):
- `SCAFFOLD.yaml` (1534 lines) — §1.0–§1.7 only
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1432 lines) — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (2721 lines) — single top key `scaffold_corner_design`

**Counts:**
- Entities: **14** (Program with dual status×posture dimensions, DropOffSite, ServiceZone, Household, CurbsideBooking, IntakeEvent, ContaminationTicket, ChippingRun, MulchEvent, MulchClaim, Volunteer, VolunteerShift, NotificationLog, DiversionReport)
- State machines: **13** (incl. cyclic booking CONFIRMED→MISSED→CONFIRMED, branching ticket OPEN→{UPHELD,DISMISSED}→APPEALED→{UPHELD_FINAL,OVERTURNED}, derived Program posture gating)
- Calculations: **9** (dual-variant route tonnage and chipping yield, tiered mulch allocation waterfall [mode a], pinned per-source-rounding diversion rollup [mode b], waitlist promotion selector, capacity/stockpile/reliability aggregates)
- Endpoints: **60** (incl. `POST /_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default)
- Errors: **38** (all exercised by at least one design instance — verified by audit)
- Roles: **6** (ProgramAdmin/SiteSupervisor/HaulerPartner opaque; Resident→Household and Volunteer→Volunteer entity-backed; Anonymous registration) with segregation-of-duties on adjudicate/resolve-appeal that binds even ProgramAdmin
- Concurrency rules: **4** OCC rules (zone/site/program PATCH + report create-with-supersede), all 412-wired
- §1.8 instances: **19** (all 9 rules ≥2; boundary_precision has 3)
- §1.9 instances: **60** (52 active with full structured test_recipes + 8 `excluded_because` stubs pointing at §1.8)

**Verification:** `scaffold_lint.py` verdict block pasted above — clean lint across 784 scanned calls. Additional audits passed: zero unbound `${var}` placeholders, no forbidden concurrency vocabulary, no duplicate instance names, all `grounds:` resolve to declared §1.1–§1.6 elements, all formula-derived asserts precomputed as literals (e.g., collected 0.070 vs sum-then-round 0.071 → rate 0.9000 → grade A; theoretical yield 19.80 vs measured 18.50 → variance 0.0657 under the strict `> 0.08` gate). One design fix during authoring: the zone-reschedule 48h rule was amended to permit makeup-day moves of past dates, keeping the booking MISSED→CONFIRMED cycle reachable.

## Step 3: Copy Shared Files — 2026-08-13T06:46:02.272Z

Copied `./INSTRUCTION.md` → `tasks/task_1416_seasonal_tree_holiday_material_recycling/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T07:11:18.886Z

PRD generation is complete and all three hard contracts verified PASS. Here is the summary.

## Output

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1416_seasonal_tree_holiday_material_recycling/workspace/PRD.md` — **317 lines**

## Section list

- **1. Introduction** (3 paragraphs: business context → time/scarcity design drivers → document map)
- **2. Global Specifications & System-Wide Principles**
  - 2.1 User and Role-Based Access Control (6 roles with per-role identity prose: Resident→Household, Volunteer→Volunteer entity-backed; ProgramAdmin/SiteSupervisor/HaulerPartner/Anonymous opaque; SoD carve-outs)
  - 2.2 API Response Structure (verified **byte-identical** to `section-2.2-response-structure.md` via `diff`)
  - 2.3 Pagination and List Ordering (limit 10/1/100, offset 0, `created_at` ascending default, notification-log newest-first exception, all per-endpoint filter params)
  - 2.4 The Logical Clock and Seasonal Time Discipline (`2026-08-01T00:00:00Z` startup default, `to_iso8601`/`current_utc`, 7-day window, 14-day processing tail, 48h/72h/24h deadlines)
  - 2.5 Common Resource Properties (UUID id, ISO-8601 3-fractional-digit timestamps, version; explicit `updated_at`/`version` absence on IntakeEvent and NotificationLog)
  - 2.6 Optimistic Concurrency Control (all 4 OCC rules: `expected_program_version` ×2, `expected_site_version`, `expected_zone_version` → `ERR_STALE_VERSION` 412)
  - 2.7 Validation Order and Error Precedence (all 11 priorities with explicit First…Eleventh ordering and per-category error ids)
  - 2.8 Measurement Constants, Precision, and Rounding (EST_TONS 0.020/0.035/0.050/0.030, YIELD_CY_PER_TON 2.2/1.8/2.0, 60% reserve, 0.5 cy min, 2.0 cy cap, 8% variance gate, thresholds 2/3/3, grades 0.9000/0.7500, 2dp/3dp/4dp half-up rules)
  - 2.9 Derived State, Cascades, and Cross-Entity Consistency (posture machine, cascade inventory, version-on-recompute)
  - 2.10 The Notification Ledger (all 6 kinds, informational FKs)
- **3. Business Logic & Workflows** (8 subsections, chronological-season grouping): 3.1 Programs/Zones/Sites · 3.2 Households & Curbside Booking · 3.3 Intake Recording & Voiding · 3.4 Contamination Tickets/Adjudication/Appeals · 3.5 Chipping Runs & Yield · 3.6 Mulch Events/Claims/Waitlist · 3.7 Volunteers & Shifts · 3.8 Diversion Reporting & Closure (incl. ops-run's 5 reconciliations)
- **4. Endpoint Definitions** (60-row table, 4 columns) · **5. Error Code Catalogue** (38-row table, 2 columns)

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 98 required, 98 present, 0 missing
- endpoints[].request_body (endpoint-only: expected_*_version, new_service_date, outcome, reason, verdict, resolution, to_iso8601, current_utc): 11 required, 11 present, 0 missing
- endpoints[].query_params (limit, offset, status, program_id, zone_id, household_id, site_id, booking_id, event_id, volunteer_id, kind, curbside_eligible): covered
- Total verified set: 109 required, 109 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in ordered §2.7 prose, 0 missing
- concurrency_rules[] OCC rejections: 4 checked, 4 expressed (endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 each), 0 missing
- state_machines[].transitions: 13 machines / 34 transitions checked, all from/to states, preconditions (with error ids), and side-effect cascades expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed as reconstructible prose (incl. pinned round-per-source-then-sum rollup, unrounded variance gate with exactly-0.08 boundary, no-head-of-line-blocking promotion), 0 missing
- validations[] conditions: 38/38 error ids matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all expressed (cascades, posture flips, supersession, occupancy increment/decrement), 0 missing
- entities[].fields[] structured content: defaults (0.9, 3, 2.0, 0, false, null), enum sets (59/59 values in backticks), computed-vs-input sources reconstructible, 0 missing
- sibling-branch symmetry: UPHELD/DISMISSED, UPHELD_FINAL/OVERTURNED, SERVICED/MISSED, COMPLETED/NO_SHOW, PARTICIPANT/GENERAL all rendered with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 233
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional quality gates passed: no fuzzy/approximating words, no pseudocode operators (`==`, `>=`, `+=` …) in prose, table shapes conform (§4: 4 columns; §5: 2 columns), §2.2 verbatim byte-identical. The two difficulty-design files were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-13T08:14:20.869Z

Done. Complete test infrastructure generated for task_1416.

## Summary

**Test counts — 90 tests total, all collected cleanly by pytest, zero skip/xfail markers**

**Queue A (Difficulty, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 39 tests over 19/19 instances (target ≥2 each)**
- dual_variant_calc: `route_projection_provisional_vs_actual` (2), `chipping_yield_theoretical_vs_measured` (2)
- combinatorial_formula: `mulch_allocation_tiered_minmax` (3), `diversion_rollup_round_per_source` (2)
- non_linear_state_machine: `booking_missed_reconfirm_cycle` (2), `ticket_appeal_branching_divergent_effects` (2)
- transitive_cascade: `adjudication_bar_cascade` (2), `run_completion_waitlist_promotion` (2)
- priority_pair_validation_conflict: `reschedule_state_before_temporal` (2), `booking_referential_before_fiscal` (2)
- boundary_precision_check: `route_capacity_exact_fit` (2), `intake_at_window_end_inclusive` (2), `appeal_deadline_exact_72h` (2)
- cross_entity_state_dependency: `booking_requires_zone_active` (2), `claim_requires_event_open` (2)
- resource_temporal_overlap: `volunteer_shift_adjacency_half_open` (2), `chipping_run_buffer_gap` (2)
- compensating_invariant: `intake_record_void_stockpile_conservation` (2), `booking_create_cancel_capacity_conservation` (2)

**Queue B (Corner, `SCAFFOLD_CORNER_DESIGN.yaml`): 51 tests over 51/52 non-stub instances** — entities 4, state_machines 6, calculations 5, validations 19, endpoints 2, errors 1, rbac 5, complexity_layers 5, consistency_model 1, per section. All 8 `excluded_because:` stubs verified to resolve to real difficulty instances and were not translated.

**Skipped instances (1)**
- `Corner/entities/booking_missing_required_field_returns_invalid_request` — skip category: PRD-contradicted outcome. The instance asserts missing `prep_attestation` → `ERR_VALIDATION` (400), but PRD §3.2 states verbatim "a missing or false attestation is rejected with `ERR_PREP_ATTESTATION_REQUIRED`" (422). A PRD-only reader would implement 422, so the asserted outcome is not uniquely derivable.

**Key adjudication decisions applied suite-wide**
- CLASS_CY per-size-class cubic-yard factors are named but never valued in the PRD. Every stockpile-dependent test therefore uses live read-back (record intake → read `stockpile_cy` → exact-draw/engineer equality from it) instead of the recipes' hardcoded cy values; exact-draw-to-zero assertions retained via the PRD's "exact equality draws the pile to zero" sentence.
- OCC patches always re-read the fresh `version` immediately before writing, because PRD §2.9 increments versions on derived-field recomputation (absolute version literals like "== 2" were avoided as non-derivable).
- `recorded_at`/`appeal_deadline` asserted format-agnostically (parsed instant / prefix) rather than byte-exact strings.

**test_helpers/ inventory** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1416_seasonal_tree_holiday_material_recycling/test_helpers/`): `__init__.py` (barrel export), `types.py` (14 entity TypedDicts — IntakeEvent/NotificationLog correctly omit `updated_at`/`version` — plus 16 enums), `api_client.py` (43 endpoint methods), `api_errors.py` (37 error IDs + status map registered with the framework), `assertions.py` (14 entity assertions + zone-capacity and pool invariants), `factories.py` (13 payload factories), `constants.py` (shared 2027-01-02..01-16 window, EST_TONS/YIELD tables, thresholds), `test_users.py` (6 roles; entity-backed builders for Resident/Volunteer), `fixtures.py` (composite helpers: `create_active_program`, `open_site`, OCC-fresh `patch_*`, `create_serviced_booking`, `produce_mulch`, `setup_mulch_pool`, `setup_approved_volunteer_scenario`, `create_report`).

**test_suite/ inventory**: `conftest.py` plus 9 files — `test_01` program/site/zone lifecycle, `test_02` bookings & route capacity, `test_03` intake & stockpile, `test_04` contamination tickets, `test_05` chipping runs, `test_06` mulch events/claims, `test_07` volunteers/shifts, `test_08` diversion reports, `test_09` security/RBAC/OCC.

**Audits run (scratch scripts removed after)**: every test carries exactly one `Design:` tag resolving to a real instance (0 tag errors); every docstring citation passed a whitespace-normalized verbatim substring check against PRD.md (90/90, after fixing two misquotes).

## Step 6: Generate Implementation — 2026-08-13T08:14:20.869Z

Implementation complete for task_1416 (Seasonal Tree & Holiday Material Recycling). All files live in `/home/ubuntu/github/CodingPRD/tasks/task_1416_seasonal_tree_holiday_material_recycling/workspace/implementation/`.

## File inventory
- `start.sh` — foreground launcher; guarded dependency install (`import flask` check, no re-install on per-test reboots), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask app factory, error handlers (ApiError, 404/405, 500), blueprint registration, PORT-aware main
- `state.py` — empty in-memory store (14 dicts), logical clock (fixed default `2026-08-01T00:00:00Z`, never wall-clock), monotonic wall-clock `created_at`/`updated_at` (ms precision, tie-free per PRD §3.6), Decimal helpers, all measurement constants
- `http_util.py` — exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; `limit`/`offset`/`total_count`/`has_more`), auth (`X-User-ID`/`X-User-Role`, 6 roles), field validators, OCC helper, pagination (10/1/100/0)
- `domain.py` — derived fields (posture, stockpile, zone tonnage duals, tier pools, strikes), all cascades (UPHELD strike/bar/auto-cancel, OVERTURNED compensation with unconditional re-reserve, SITE_CLOSING shift cancellation, 3-no-show auto-suspend, waitlist promotion sweep with CLAIM_PROMOTED notices), ops-run's 5 reconciliations, per-source-rounded diversion rollup, chipping yield with unrounded 0.08 gate
- `routes_a.py` (28 endpoints) + `routes_b.py` (32 endpoints)

## Endpoint count
**60/60** implemented (verified by route listing against PRD §4): programs ×7 (incl. ops-run, diversion-summary, notifications), sites ×4, zones ×4, households ×3, bookings ×6, intake-events ×4, contamination-tickets ×6, chipping-runs ×5, mulch-events ×4, mulch-claims ×4, volunteers ×4, volunteer-shifts ×4, diversion-reports ×4, `_clock/set_current_utc` ×1.

## Clean boot confirmation
Smoke-tested `bash start.sh` with `PORT` set, three times fresh: boots in ~2s, zero state on every boot (verified `total_count == 0` after kill/relaunch), default logical clock honored (pre-window activation correctly rejected before any clock set). Three end-to-end smoke suites (100+ assertions) all passed: full season arc (publish→activate→booking→intake→tickets→adjudication bar cascade→appeal/overturn restore→runs with yield gate→tiered claims with partial allocation→waitlist promotion on pool credit→shift capacity/overlap/cutoff→auto-suspend at 3 no-shows→report publish/supersede→program close guards), boundary semantics (capacity equality admitted, exactly-2h run buffer, inclusive windows, 48h/72h/24h boundaries), the pinned round-per-source rollup (0.0204+0.0204 → 0.040, grade A at exactly 0.9000), OCC 412s, and per-transition role splits.

## Decisions worth flagging
- **CLASS_CY values**: the PRD/scaffold name the per-size-class cubic-yard table but never list values (a genuine spec gap — EST_TONS and YIELD_CY_PER_TON are given, CLASS_CY is not). I fixed SMALL 0.20 / MEDIUM 0.35 / LARGE 0.50 / MIXED 0.30, used consistently for gross/net volume, stockpile, and capacity math. Documented in `state.py`.
- **Validation precedence**: followed PRD §2.7's self-declared normative 11-priority pipeline across levels; §3.x endpoint prose breaks ties within a level (e.g., intake: window → site-open → posture → contaminated≤gross → capacity).
- **Program field edits** restricted to DRAFT per "Edit DRAFT fields" in §4; **ops-run auto-CLOSING applies to OPEN sites only** (PRD §3.8 + scaffold endpoint table over the looser §3.1 sentence); auto-suspend triggers only when no_show_count reaches exactly 3 ("exactly at the third no-show").
- `created_at`/`updated_at` use a strictly-increasing wall clock (the PRD's "ties cannot occur" waitlist guarantee requires it); `recorded_at`/`adjudicated_at`/`published_at` use the logical clock as specified. No seeding anywhere — the store is empty dicts at every boot.

## Step 7: Test-Iterate Loop — 2026-08-13T08:55:00Z

Six 8-round parallel sweeps run. Final state: **89/89 passed in all 8 rounds, twice consecutively** (16 consecutive clean rounds).

**Iteration 1 (baseline):** 83/90 in all 8 rounds — 7 stable failures.
- 4 tests asserted byte-exact timestamp strings (`service_date`/`collection_date` == "2027-01-09T00:00:00Z"). PRD pins the three-fractional-digit wire format only for `created_at`/`updated_at`/`api_request_timestamp` (§2.2/§2.5); other datetime fields carry instants, so byte-equality is not uniquely derivable. Fixed tests to compare parsed instants via a new `assert_same_instant` helper (consistent with the suite's own existing convention for `recorded_at`/`appeal_deadline`).
- `test_event_cap_branch_of_min_allocation` DELETED: it sent `requested_cy=2.0` with `per_household_cap_cy=1.0` and asserted a confirmed 1.0 allocation, but PRD §3.6 states verbatim "the `requested_cy` must be at least half a cubic yard and no more than the event's `per_household_cap_cy` (`ERR_CLAIM_CAP_EXCEEDED`)" — the request is mandated to fail, and the cap-wins-min branch is unreachable (cap immutable post-creation, request validated at creation). PRD-contradicted outcome (same skip category as the generation-time skip).
- `test_shift_cancel_cutoff_boundary`: fixture clock bug — checked sh2's rejection at sh1's 24h boundary (sh2 starts 12:00, so 01-08T09:00:01Z was still legally inside its window and the implementation correctly returned 200). Fixed clock to sh2's own boundary + 1s (01-08T12:00:01Z).
- `test_volunteer_reports_ticket_but_cannot_adjudicate`: missing `make_volunteer_headers` import in test_09 (NameError). Import added; test body was already PRD-faithful.

**Iterations 2–4 (infrastructure flakiness hunt):** after the real fixes, remaining failures were environmental: "server could not be restarted" (runner's hardcoded 15s per-test restart poll exceeded under concurrent sibling pipelines sharing this host) and one stale-keep-alive `RemoteDisconnected`. Mitigated within task scope by trimming start.sh's dependency guard from a full `import flask` (~0.26s) to `importlib.util.find_spec` (~0.02s), shrinking boot-time exposure. A transient `Connection: close` experiment on the client session was reverted after isolation proved it unrelated.

**Iterations 5–6 (confirmation):** 89/89 × 8 rounds, twice consecutively, under continued concurrent load from sibling pipeline sweeps.

**Files changed:**
- `test_helpers/assertions.py` — added `assert_same_instant` (instant-based timestamp equality).
- `test_suite/test_01…lifecycle.py`, `test_02…route_capacity.py`, `test_04…tickets.py` — 7 byte-exact timestamp assertions converted to `assert_same_instant`.
- `test_suite/test_06_mulch_events_claims.py` — deleted `test_event_cap_branch_of_min_allocation` (PRD-contradicted).
- `test_suite/test_07_volunteers_shifts.py` — fixed sh2 cutoff clock in `test_shift_cancel_cutoff_boundary`.
- `test_suite/test_09_security_rbac_occ.py` — added missing `make_volunteer_headers` import.
- `workspace/implementation/start.sh` — dependency guard now uses `find_spec` (faster per-test reboots). No changes to implementation logic were needed.

## Step 8: Finalize PRD — 2026-08-13T09:00:13.513Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1416_seasonal_tree_holiday_material_recycling/workspace/PRD_FINALIZED.md` written (copy of PRD.md + one insertion).

## Line counts / delta
- PRD.md: 317 lines; PRD_FINALIZED.md: 319 lines; +2 lines (+0.63%).

## Changes (one bullet per change)
- §2.5 — insert — added a paragraph pinning the wire format of every other datetime-valued response field (non-`created_at`/`updated_at`/`api_request_timestamp`): ISO 8601 UTC, exactly three fractional digits, `Z` suffix, with nullables returned as null — `implementation/state.py:84-90` (`fmt_dt` is the sole datetime serializer); field coverage verified at `implementation/domain.py:460-698`, `implementation/http_util.py:35`, `implementation/routes_b.py:1017`.

## Step-7 items that required NO edit (with verification)
- `test_event_cap_branch_of_min_allocation` deletion: PRD §3.6 already mandates `ERR_CLAIM_CAP_EXCEEDED` for `requested_cy > per_household_cap_cy`; impl matches verbatim (`implementation/routes_b.py:588-593`; `try_allocate` min-of-three at `implementation/domain.py:166-172` mirrors PRD's allocation sentence). PRD already determines behavior — prose kept verbatim.
- `test_shift_cancel_cutoff_boundary`: pure fixture clock bug. PRD §3.7 already pins "no later than twenty-four hours before `start_at`, the boundary inclusive" plus ProgramAdmin exemption; impl matches (`implementation/routes_b.py:883-889`, `now > start_at - 24h` rejects).
- `test_volunteer_reports_ticket_but_cannot_adjudicate`: pure test bug (missing import). PRD §4 table already authorizes Volunteer for ticket creation and excludes it from adjudication; impl matches (`implementation/routes_b.py:81` vs `:191`).
- `start.sh` `find_spec` guard: boot-time infrastructure only, no API behavior; nothing in PRD scope.

## Per-edit pre-edit search log (NO-NEW-MISMATCH)
Edit 1 (the only edit):
- (a) Subject: wire serialization format of datetime-valued fields in API responses.
- (b) Enumerated impl paths: `state.py:84-90` (`fmt_dt`, sole formatter; `None`→`None`); `state.py:93-102` (`parse_dt`, input side — left out of scope, not touched); `http_util.py:35` (`api_request_timestamp`); `domain.py` serializers — `program_json:460-461,471-472` (window_start/end), `site_json:484-485` (open/close_date), `zone_json:501` (collection_date), `booking_json:538` (service_date), `intake_json:560` (recorded_at), `ticket_json:579-580` (adjudicated_at/appeal_deadline, nullable), `run_json:593-594`, `event_json:615-618`, `shift_json:661-662`, `report_json:687-688,696` (period_start/end, published_at nullable); `routes_b.py:1017` (clock `current_utc`); `routes_a.py:243-265` (ops-run returns `program_json`; diversion-summary returns no datetimes); notification `message=` interpolations (`routes_a.py:214,595`, `routes_b.py:527`, `domain.py:218,264,322`) — contain names/codes/ids/amounts only, no embedded datetimes. Grep confirmed no `isoformat`/`strftime` outside `fmt_dt`.
- (c) Wording adjustments: added "whenever it is non-null" hedge plus explicit null sentence (nullable fields serialize as JSON null via `fmt_dt(None)`); used a non-exhaustive "including" field list so no off-list path is mis-described; stated the `Z` suffix explicitly with a `2027-01-09T00:00:00.000Z` example. §2.4's `2026-08-01T00:00:00Z` startup-default spelling was left verbatim — it denotes an instant, not a wire sample, and no test asserts its byte form.

## Step 9: PRD Completeness Scan — 2026-08-13T09:35:00Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1416_seasonal_tree_holiday_material_recycling/workspace/PRD_COMPLETED.md` is written — copied from `PRD_FINALIZED.md` (which existed) and patched in place.

**Source vs. output**: `PRD_FINALIZED.md` 319 lines / 67,946 chars → `PRD_COMPLETED.md` 319 lines / 70,297 chars. Char-delta **+2,351**. All 21 edits are in-paragraph inserts/revisions across 18 lines; no new sections, paragraphs, or invented behavior.

**Counts**: 20 ambiguity-pins, 6 mismatch-revisions (26 behavioral pins total; some edits carry two pins on one line).

**Ambiguity-pins (PRD silent → pinned to impl)**:
- §2.3 — insert — ambiguity — pinned `has_more` = (`offset`+`limit` < `total_count`) and that non-integer limit/offset, limit outside 1–100, or negative offset → `ERR_VALIDATION` — implementation/http_util.py:49, 178-199
- §2.4 — insert — ambiguity — record-keeping timestamps (`created_at`, `updated_at`, `api_request_timestamp`) stamped from wall clock; domain timestamps (`recorded_at`, `adjudicated_at`, `appeal_deadline`, `published_at`) from logical clock — implementation/state.py:63-74, domain.py:44-57, http_util.py:35, routes_a.py:912, routes_b.py:1003
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — implementation/domain.py:55
- §2.8 — insert — ambiguity — pinned `CLASS_CY` values: SMALL 0.20 / MEDIUM 0.35 / LARGE 0.50 / MIXED 0.30 cy per tree (the known generation-time gap; confirmed PRD named the table without values, and test_helpers/fixtures.py works around it by reading live `stockpile_cy`) — implementation/state.py:154-159
- §3.1 — insert — ambiguity — `target_diversion_rate` bounds are inclusive of 0 and 1 — implementation/routes_a.py:86-87
- §3.1 — insert — ambiguity — program field edits accepted only in `DRAFT` (`ERR_INVALID_STATE` otherwise) — implementation/routes_a.py:149-150
- §3.1 — insert — ambiguity — program window edit re-validates the 7-day minimum (`ERR_VALIDATION`) — implementation/routes_a.py:163-168
- §3.1 — insert — ambiguity — `daily_tree_capacity` is a positive integer — implementation/routes_a.py:466
- §3.1 — insert — ambiguity — site `capacity_cy` must be positive; `volunteer_slots_per_role` a positive integer — implementation/routes_a.py:292, 296
- §3.1 — insert — ambiguity — PATCH /sites date edits re-validate both dates within program window and open ≤ close (`ERR_VALIDATION`) — implementation/routes_a.py:386-392
- §3.2 — insert — ambiguity — `actual_tons` scale weight is non-negative when provided — implementation/routes_a.py:827
- §3.2 — insert — ambiguity — zone-reschedule new date outside window or not in future → `ERR_OUTSIDE_COLLECTION_WINDOW` (PRD named no error for these) — implementation/routes_a.py:554-565
- §3.3 — insert — ambiguity — intake `tree_count` positive integer; `contaminated_cy`/`weighed_tons` non-negative — implementation/routes_a.py:854, 858, 861
- §3.5 — insert — ambiguity — `CANCELLED` runs do not constrain same-site overlap/buffer scheduling — implementation/routes_b.py:306
- §3.5 — insert — ambiguity — completion payload `input_cy`, `contaminated_input_tons`, `measured_output_cy` non-negative — implementation/routes_b.py:364-377
- §3.5 — insert — ambiguity — zero theoretical output (fully contaminated input): raw variance defined as 0 if measured output also 0, else 1 — implementation/domain.py:440-445
- §3.6 — insert — ambiguity — `per_household_cap_cy` must be positive when supplied — implementation/routes_b.py:455
- §3.7 — insert — ambiguity — shift interval outside program window or end ≤ start → `ERR_VALIDATION` — implementation/routes_b.py:770-771, 782-785
- §3.7 — insert — ambiguity — "same calendar date" for role-slot capacity = UTC calendar date of each shift's `start_at` — implementation/routes_b.py:815, state.py:93-102

**Mismatch-revisions (PRD described different behavior → revised to impl)**:
- §2.4 — revise — mismatch — "advances the logical clock" → "sets … any instant is accepted, earlier or later" (impl's `set_clock` assigns unconditionally; "advances" wrongly implied forward-only) — implementation/state.py:42-44
- §2.8 — revise — mismatch — blanket "where a rule gates on a ratio, the gate evaluates the unrounded value" scoped to the yield-variance gate; grade and `below_target` evaluate the rounded `diversion_rate` — implementation/domain.py:416-423
- §2.8 — revise — mismatch — "mulch pool figures use two decimal places" → only the participant-pool split is rounded to 2dp; allocations/remainders are unrounded `min()` of supplied figures — implementation/domain.py:94-103, 166-172
- §3.2 — revise — mismatch — booking reschedule "guarded four ways" → five ways, adding the zone-`ACTIVE` (`ERR_ZONE_SUSPENDED`) guard impl enforces between the future-date and eligibility checks — implementation/routes_a.py:803-804
- §3.3 — revise — mismatch — "Two gates precede the arithmetic" → the OPEN/posture gates run after the collection-window check and before the capacity check per §2.7 (impl validates the volume arithmetic's `contaminated_cy` ≤ gross cap during request parsing, before existence and the gates) — implementation/routes_a.py:863-897
- §3.4 — revise — mismatch — DISMISSED branch "nothing else happens" → it also records `adjudicated_by` and `adjudicated_at` (no appeal deadline) — implementation/routes_b.py:209-214

**Verified already-pinned (no change)**: all 45 endpoint role lists, all state machines and transition preconditions, the full validation-pipeline stage order (1–11 matches impl ordering wherever staged), EST_TONS/YIELD_CY_PER_TON/0.60 reserve/0.5 min/2.0 cap/0.08 variance/2 strikes/3 tickets/3 no-shows/grade thresholds, all cascade behaviors (upheld adjudication, bar auto-cancel, overturn restoration with unconditional re-reserve, site-closing shift cancellation, zone-reschedule rewrite, promotion sweep ordering/triggers), rollup round-per-source-then-sum, append-only IntakeEvent/NotificationLog shape, OCC guard set, envelope shape, and the logical-clock startup default.

## Step 2: Generate Scaffold — 2026-08-15T06:10:00.000Z

Scaffold generation complete. All three artifacts written and lint-clean.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1988_air_ambulance_medical_flight_operations/SCAFFOLD.yaml` (1349 lines) — §1.0–§1.7 only; no difficulty/corner keys
- `/home/ubuntu/github/CodingPRD/tasks/task_1988_air_ambulance_medical_flight_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (943 lines) — single top-level key `scaffold_difficulty_design:`
- `/home/ubuntu/github/CodingPRD/tasks/task_1988_air_ambulance_medical_flight_operations/SCAFFOLD_CORNER_DESIGN.yaml` (1442 lines) — single top-level key `scaffold_corner_design:`

## Surface counts (SCAFFOLD.yaml)

- **16 entities** (Base, Aircraft, CrewMember, CrewShift, Patient, MembershipSubscription, MissionRequest, Mission, CrewAssignment, WeatherAssessment, GroundTransportLeg, BedReservation, InsuranceAuthorization, Invoice, RepatriationCase, PatientCareReport) — flat topology, all FKs with canonical `FK -> X.id` prefixes and reverse-reachability GETs
- **71 endpoints** (40 mutations incl. `/_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` default; 30 reads; all filter lists carry pagination params)
- **35 error codes**, **32 ordered validations** (unique priorities 1–32 across auth/existence/state/safety/referential/temporal/constraint/fiscal), **13 state machines** (cyclic: MissionRequest info-loop, Mission weather-hold loop, RepatriationCase doc-expiry demotion, PCR QA loop, IA appeal loop, membership lapse/reinstate; parallel dims: Invoice `claim_status × member_adjustment_status`), **8 calculations** (labeled C1–C8) with pinned rounding/evaluation order, **2 OCC concurrency rules** (weather-assessment on Mission.version, PCR amend on PatientCareReport.version), **6 roles** (segregation-of-duties model; FlightCrew is `entity_backed:CrewMember`, others opaque)

## Design-instance counts

- **§1.8: 25 instances** — 3 each for rules 1–7 (dual_variant_calc across billing/clinical/crew-fatigue domains; combinatorial_formula in all three modes (a) weather matrix, (b) per-line-then-sum rounding with a falsifiable 1-cent delta, (c) pre-logistics-subtotal tier ordering; divert/QA/abort cascades of depth 3/3/2; three distinct validation priority pairs; boundaries on visibility/840-duty-minutes/membership-date-equality), 2 each for rules 8–9 (half-open aircraft windows vs buffered crew-rest semantics; money-decomposition vs fleet-count invariants). All formula asserts are pre-computed literals (e.g., provisional 4089352 vs final 3679842 cents).
- **§1.9: 70 instances (62 full + 8 `excluded_because` stubs)** across all nine claim-extraction-guide sections: entities 9, state_machines 10, calculations 6, validations 12, endpoints 4, errors 16, rbac 6, complexity_layers 6, consistency_model 1.

## Verification

`scaffold_lint.py` verdict, verbatim: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1076 calls scanned, 0 violations.) Additional audits passed: instance names unique across both files (95 total), zero unbound `${var}` placeholders, every error code exercised by at least one instance, all `excluded_because` refs resolve to §1.8 instance names, all grounds resolve to declared §1.1–§1.7 elements, enum-value closure holds for every entity, and no forbidden concurrency vocabulary anywhere.

## Step 3: Copy Shared Files — 2026-08-15T06:10:30.000Z

Copied ./INSTRUCTION.md to tasks/task_1988_air_ambulance_medical_flight_operations/workspace/INSTRUCTION.md (bash-only step).

## Step 4: Generate PRD — 2026-08-15T06:38:00.000Z

All audits pass. The PRD is complete. Here is the summary:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1988_air_ambulance_medical_flight_operations/workspace/PRD.md`
**Line count:** 361 lines

**Structure:** §1 Introduction (3 paragraphs, business-context angle); §2 with 9 subsections (2.1 RBAC with per-role identity translation, 2.2 verbatim response envelope, 2.3 Pagination, 2.4 Common Resource Properties + Logical Clock incl. the `WeatherAssessment` `common_fields: false` exemption, 2.5 Monetary/Scoring Precision, 2.6 OCC, 2.7 Cascading Consistency, 2.8 Addressing & Validation Order, 2.9 Two Duty Ledgers); §3 with 9 subsections organized along the mission timeline (3.1 bases/fleet/duty roster with C5, 3.2 intake→triage with C2 dual variants, 3.3 acceptance/dispatch binding, 3.4 weather C3 + launch gate, 3.5 progression/divert/abort, 3.6 ground legs + beds, 3.7 repatriation, 3.8 revenue cycle with C1/C4/C6/C7, 3.9 PCR + QA with C8); §4 with 71 four-column endpoint rows; §5 with 35 two-column error rows.

## Hard Contract Reports

```
Field coverage check (Contract 1):
- entities[].fields: 91 required, 91 present, 0 missing
- endpoints[].request_body: 89 required, 89 present, 0 missing
- endpoints[].query_params: 25 required, 25 present, 0 missing
Status: PASS
```

```
Rule coverage check (Contract 2):
- validations[] with priority: 7 multi-check endpoint orderings checked (accept, crew-shift create, launch/advance, invoice submit, PCR submit, repatriation verify, member-writeoff) plus the global auth→forbidden→not-found→validation→state→business ladder in §2.8, 7 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked (weather-assessment-stale-mission, pcr-amend-stale-record), 2 expressed with write capability + expected_mission_version / expected_patient_care_report_version + ERR_STALE_VERSION (HTTP 412) all named, 0 missing
- state_machines[].transitions: 60 checked, 60 fully expressed (from/to pairs, preconditions paired with error ids, side effects), 0 missing
- calculations[]: 8 checked (C1–C8), 8 fully expressed in precise prose with all constants embedded (incl. the C4 worked example 16.6666 mi → 266,666 / 18,667 / 2,085,333 vs forbidden 2,085,332), 0 missing
- validations[] conditions: 32 checked, 32 matchable to their error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all checked and expressed (divert 3-hop cascade, abort/completion cascades, C8 3-hop remediation cascade, weather-post mission mutation, appeal compensation zeroing, ERR_CREW_UNAVAILABLE / ERR_AIRCRAFT_NOT_AVAILABLE / ERR_DOC_EXPIRED / ERR_MISSION_NOT_COMPLETED / ERR_STALE_VERSION / ERR_DUPLICATE_* scopes enumerated), 0 missing
- entities[].fields[] structured content: defaults, ranges, and optionality reconstructible from prose (e.g. emergency_override default false, invoice ledger zeros, subscales 0–10, miles > 0, destination_country required iff INTERNATIONAL_REPATRIATION), 0 missing
- sibling-branch symmetry: 8 groups checked (payer-response PAID/PARTIALLY_PAID/DENIED from SUBMITTED and RESUBMITTED, abort from five from-states, decline from TRIAGED/PENDING_INFO, insurance decision branches, membership terminate from ACTIVE/LAPSED, ground-leg cancel from SCHEDULED/ENROUTE, PCR submit from DRAFT/AMENDED, bed release from HELD/CONFIRMED), 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 643
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 emitted byte-identical to `section-2.2-response-structure.md` (verified programmatically); all 35 error IDs appear in §2/§3 prose; all 90 enum/state values appear as exact UPPERCASE strings; §4 table has only Method/Path/Description/Authorized Role(s) columns; §5 table has only Error ID/HTTP Status Code columns. The difficulty/corner design files were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-15T07:14:00.000Z

Everything passes. Final summary.

**Task**: Generate test infrastructure + test cases for `task_1988_air_ambulance_medical_flight_operations` from the two design indices (PRD-first adjudication).

### Files written

`test_helpers/` (Stage 1):
- `test_helpers/__init__.py` — barrel export (framework + PRD-specific)
- `types.py` — 19 status enums + 18 entity TypedDicts; `WeatherAssessment` correctly omits `updated_at`/`version` (immutable observation per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (incl. the `_clock/set_current_utc` test-driving endpoint)
- `api_errors.py` — 35 `ApiErrorId` members + HTTP map registered via `set_error_http_status_map`
- `constants.py` — C1–C8 thresholds (weather tables, weights, charge constants, windows)
- `test_users.py` — `TEST_USERS` shared headers + `make_flight_crew_headers(crew_member.id)` (entity-backed identity threading) + `make_qa_reviewer_headers`
- `fixtures.py` — composite builders: `setup_planning_mission`, `setup_completed_mission`, `setup_completed_mission_with_completed_destination_leg`, `setup_finalized_invoice`, `setup_submitted_invoice`, `setup_member_protected_submitted_invoice` (with `completion_clock`), `setup_repatriation_mission` + `full_document_set`, plus granular helpers (`post_go_weather`, `advance_mission_through`, `abort_mission`, `update_membership_safe`, etc.)

`test_suite/` (Stage 2): `conftest.py` + 14 test files:
- `test_01_dual_variant_calculations.py`, `test_02_combinatorial_formulas.py`, `test_03_state_machines.py`, `test_04_transitive_cascades.py`, `test_05_validation_priority_conflicts.py`, `test_06_boundary_precision.py`, `test_07_cross_entity_gates.py`, `test_08_overlap_and_invariants.py` (queue A)
- `test_09_entities.py`, `test_10_state_machine_corners.py`, `test_11_calculation_corners.py`, `test_12_validation_corners.py`, `test_13_error_corners.py`, `test_14_endpoints_rbac_occ.py` (queue B)

### Test counts
- Queue A (Difficulty): **25/25 instances covered, 2 tests each = 50 tests**
- Queue B (Corner): **62/62 non-stub instances covered, 1 test each = 62 tests**
- Total: **112 tests**, all collected by pytest cleanly; zero `skip`/`skipif`/`xfail` markers.

### Skip list (with reasons)
None — no instance was dropped by the PRD-first filter. The 8 `excluded_because` corner stubs were not translated (by design); all 8 `difficulty_instance` cross-references verified to resolve to real §1.8 instance names.

Notable adjudication decisions (kept as gaps rather than tested where PRD was ambiguous): none required — the PRD pins every asserted value, including the computed examples (e.g., 2,085,333 vs forbidden 2,085,332 rounding order is a verbatim PRD worked example; fleet-disposition invariant reads from PRD §3.5's last-booking rule).

### Self-check results
- **Stage 1**: all helper modules import; `fixtures.py` helpers exercised at import; no "scaffold" references in comments/docstrings.
- **Stage 2 coverage audit**: automated tag sweep confirms every A instance has exactly ≥2 tests tagged `Design: Difficulty/<rule_id>/<name>` and every non-stub B instance has ≥1 test tagged `Design: Corner/<section>/<name>`; every test has exactly one Design tag, placed as the last docstring line.
- **PRD verbatim pass**: segment-wise grep of every quoted citation against `PRD.md` — 0 failures after fixing 4 near-misses (elided text without ellipsis; two case-mismatch quotes).
- **Collection**: `pytest --collect-only` yields 112 tests with no import or fixture errors.

## Step 6: Generate Implementation — 2026-08-15T07:14:00.000Z

Complete Python + Flask implementation generated at `tasks/task_1988_air_ambulance_medical_flight_operations/workspace/implementation/`.

**Files written** (14):
- `start.sh` — foreground launcher, `exec python3 app.py`, `PORT` env (default 10000), binds 0.0.0.0, pip install guarded by `python3 -c "import flask"` so per-test reboots skip reinstall
- `requirements.txt` (flask>=3.0), `app.py` (blueprint registration, envelope-shaped 404/405/exception handlers, per-request lock for atomic cascades)
- `core.py` — in-memory store (17 dicts, starts empty, zero seeding), logical clock (startup default `2026-08-01T00:00:00Z`, never wall-clock), envelope helpers (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`; pagination `limit/offset/total_count/has_more` in meta, defaults 10/0, range 1–100), full error catalog, auth middleware (`X-User-ID`/`X-User-Role`, six roles), field validators
- `calc.py` — calculations C1–C8 (see below)
- `serialize.py`, `services.py` (cascades), and 8 route modules (`routes_admin/patients/requests/missions/coordination/billing/repatriation/pcr.py`)

**Endpoints: 71** — every row of the scaffold §1.5 table including `_clock/set_current_utc`; creates return 201, actions/reads 200; list endpoints support the scaffold's per-resource filters with created_at-ascending ordering.

**State machines (13)**: Aircraft (AVAILABLE/ASSIGNED/MAINTENANCE with last-booking release rule), CrewMember (incl. cascade-only REMEDIATION_HOLD), CrewShift, MembershipSubscription (30-day inclusive reinstate window), MissionRequest (RECEIVED→TRIAGED⇄PENDING_INFO→ACCEPTED/DECLINED), Mission (10 states, hold/resume loop, divert, abort/cancel), CrewAssignment, GroundTransportLeg, BedReservation, InsuranceAuthorization (REQUESTED/APPROVED/PARTIAL/DENIED/APPEALED), Invoice (parallel `claim_status` + `member_adjustment_status` dimensions), RepatriationCase (COLLECTING⇄READY_TO_FLY with lazy launch-gate demotion), PatientCareReport (QA cycle with AMENDED self-loop).

**Calculations**: C1 pinned line order (base/mileage/fuel-from-rounded-mileage/acuity/subtotal/logistics-on-pre-logistics-subtotal/ground) with provisional (`ceil(miles*1.15)`, legs in SCHEDULED..COMPLETED) vs final (exact fractional miles, COMPLETED legs only) variants — verified the PRD's pinned example (16.6666 mi rotor → 2,085,333¢) and the 2,500,000¢ logistics boundary; C2 dual-weight acuity scores (2dp HALF_UP, +2.0 deterioration bonus strictly <120 min, added post-rounding); C3 weather minimums with all boundary pins (==ceiling passes, ==1.2×ceiling is GO, strict crosswind, mountain +500); C5 dual duty ledgers (rolling-24h projection ≤840, 600-min rest, positive-minute overlap; calendar-day reporting view); C6 waterfall with appeal compensation; C8 rolling-90-day deficiency tally → hold at ≥15 → assignment release.

**Validations**: full priority ladder implemented (401 → 403/self-review-403 → 404 left-to-right FK existence → 400 shape → 409 state → per-workflow business order → 412 OCC last), FlightCrew ownership on PCR/shift endpoints, per-transition actor restrictions on advance, and all 34 error IDs with their scaffold HTTP statuses. OCC on `expected_mission_version` (weather filing bumps mission version) and `expected_patient_care_report_version`.

**Boot verification**: smoke-tested across 8 phases (~110 assertions, all passing — 6 initial "failures" were traced to my test expectations, each confirming the implementation matched the PRD: duty-before-overlap precedence, onset==now bonus, inclusive 7.0=CCT break, ground-leg creation bumping mission version, coordination recomputation on replacement legs, released assignments leaving the launch roster). Fresh `bash start.sh` boots in ~2s, store is empty (`total_count: 0` on all lists), process kills cleanly.

## Step 7: Test/Iterate Loop — 2026-08-15T07:32:00.000Z

All 8 rounds pass 112/112. Clean sweep achieved.

**Iterations run:** 2 (initial sweep: 106/112 in all 8 rounds, identical failure set — no flakiness; post-fix sweep: 112/112 in all 8 rounds).

**Tests deleted:** none. Every failing test traced to verbatim PRD prose with uniquely determined outcomes.

**Fixes applied to `test_suite/` (test bugs, STEP 2):**

1. `test_suite/test_01_dual_variant_calculations.py` — `test_final_total_uses_actual_miles_and_completed_legs` used `setup_completed_mission_with_completed_destination_leg` without importing it (NameError). Added it to the `from test_helpers import (...)` list; the helper itself was already PRD-faithful.

2. `test_suite/test_03_state_machines.py` — `test_no_go_assessment_blocks_resume_from_hold` and `test_fresh_go_assessment_resumes_the_hold_resume_loop` called `make_flight_crew_headers(pilot)` passing the CrewMember *dict* as `X-User-ID` (requests InvalidHeader). PRD §2.1 requires the FlightCrew `X-User-ID` to be the CrewMember's `id`. Fixed to `make_fc(pilot["id"])` at the three call sites.

3. `test_suite/test_13_error_corners.py` — `test_writeoff_rejected_when_dimension_balance_billed` and `test_paid_plus_adjustment_over_total_rejected` hardcoded BLS arithmetic (final 1,808,560 / residual 1,308,560) while their fixture (`setup_submitted_invoice` defaults) builds an ALS-tier mission: final = 1,800,000 base + 8,000 mileage + 560 fuel + 120,000 ALS acuity = 1,928,560. Corrected the expected constants (residual 1,428,560) and, for the overpayment test, the payload to `paid_cents=1928560, contractual_adjustment_cents=1` so the PRD §3.8 ledger guard (`paid + adjustment > final_total`) is actually tripped. The asserted PRD rules were verbatim-covered; only the test's arithmetic was wrong.

**Fixes applied to `implementation/` (STEP 3):**

4. `workspace/implementation/calc.py` — `duty_projection_exceeded` summed window-*intersection* minutes of prior shifts. Changed to sum the full `planned_minutes` of every shift (OPEN or CLOSED) intersecting the rolling 24h window, per PRD §3.1 ("Sum the minutes of all of the member's shifts ... that intersect the window"). Decisive derivability argument: under intersection-clamping, the 600-minute rest rule structurally caps the projection at exactly 840 (proved: in any 1440-min window, rest-compliant prior duty + candidate ≤ 840), which would make the PRD's explicit "841 or more is rejected with ERR_DUTY_LIMIT_EXCEEDED" boundary unreachable dead code. Full-shift summation is the only reading under which the PRD's pinned 840/841 boundary is live — and it's what the scaffold's test recipe (`600 + 241 = 841 → rejected`) encodes. Verified no currently-passing shift test (rest-gap pair in test_08, rolling-window test in test_01, 840-exact companion in test_06) changes outcome under the corrected semantics.

**Final state:** 8/8 rounds × 112/112 tests passing.

## Step 8: Finalize PRD — 2026-08-15T07:45:00.000Z

Done. `workspace/PRD_FINALIZED.md` is written with exactly two single-line revisions, both tracing to step_7_diff item 4 (the `calc.py::duty_projection_exceeded` implementation fix).

## Line counts

- PRD.md: 361 lines; PRD_FINALIZED.md: 361 lines; 0% delta (two in-place line revisions, no sections added or removed).

## Changes

- **§3.1 (duty-projection bullet)** — insert — added one sentence: "An intersecting shift contributes its full `planned_minutes` to this sum: the window only selects which shifts are counted and never clips a shift's contribution to the portion of the shift falling inside it." — impl `workspace/implementation/calc.py:217-221` (`projected += s["planned_minutes"]` for every shift with `s_start < cand_end and w_start < s_end`).
- **§2.9 (two duty ledgers)** — revise — "The dispatch legality gate counts duty minutes inside a rolling 24-hour window anchored to…" → "The dispatch legality gate totals the planned minutes of the member's shifts that intersect a rolling 24-hour window anchored to…" — impl `workspace/implementation/calc.py:203-221` (a shift straddling the window edge contributes minutes lying outside the window, so the old phrasing mis-described the fixed implementation).

## Step_7_diff items requiring no PRD edit

- Item 1 (`test_01` missing import): pure fixture bug; helper already PRD-faithful.
- Item 2 (`test_03` `X-User-ID`): PRD §2.1 already pins verbatim that FlightCrew `X-User-ID` is the acting CrewMember's `id`; impl conforms (`core.py:242` reads the raw header; ownership comparisons at `routes_pcr.py:31,80,151` and `routes_admin.py:175,230`). Test bug only.
- Item 3 (`test_13` arithmetic): PRD §3.8 pins every constant verbatim (1,800,000 rotor-wing base, 16,000/mile, 7% fuel on rounded mileage, 120,000 ALS acuity, ledger guard); the test hardcoded BLS math against an ALS fixture. Test bug only.

## Per-edit pre-edit search log

**Edit 1 (§3.1 duty projection)**
- (a) Subject: rolling-24h duty-projection summation semantics (full shift minutes vs. window-clipped minutes).
- (b) Paths enumerated: `calc.py:203-221` (`duty_projection_exceeded`, the Step 7 site — window `[cand_end−24h, cand_end]`, strict planned-interval intersection, full `planned_minutes` summed, `> 840` rejects); `calc.py:196-200` (`member_shifts` — supplies OPEN and CLOSED shifts, the only statuses; planned-start ASC / creation-order tie-break, matching the PRD clause kept verbatim); `calc.py:248-259` (`duty_minutes_calendar_day` — the sibling ledger that *does* clip via `_overlap_minutes`; consumed only by `serialize.py:29` for reporting, never gates); `routes_admin.py:170-207` (`create_crew_shift` — sole caller; candidate minutes = whole-minute interval length, line 184; reporting order duty→rest→overlap, already in PRD); grep for `planned_minutes` across all impl files confirmed no other consumer. Test evidence: `test_06:92-108` (600 + 241 = 841 rejected — window clips the prior shift to 599 min, so only full-shift summation trips the boundary) and `test_01:146-183` (720 + 240 = 960) decisively require the pinned reading.
- (c) Wording adjustment: phrased the pin as a standalone sentence scoped to "this sum" inside the **Duty projection** bullet, so it cannot be misread as redefining the clipped calendar-day ledger in §2.9; deliberately left "intersect the window" unqualified (planned-vs-actual interval) to preserve the original under-determination, since Step 7 did not exercise that axis and the impl's planned-interval test is the only reading the original text suggested.

**Edit 2 (§2.9 rolling-ledger description)**
- (a) Subject: the same rolling duty ledger's summary sentence (global-consistency check triggered by Edit 1 — leaving "counts duty minutes inside a rolling 24-hour window" would contradict the new §3.1 pin and mis-describe the fixed impl).
- (b) Paths enumerated: same set as Edit 1, plus the remainder of §2.9 itself — the calendar-day description and the 20:00–08:00 example (240/480 calendar split, "720 contiguous minutes on the rolling window"), which remains accurate under full-shift summation because the example shift lies wholly inside the window; `test_01`'s calendar-day test quotes that passage verbatim and passes, so it was kept untouched.
- (c) Wording adjustment: replaced only the verb phrase ("counts duty minutes inside" → "totals the planned minutes of the member's shifts that intersect"); kept "anchored to the candidate shift's planned end", the "only one that accepts or rejects a shift" clause, and the entire calendar-day half verbatim, so no off-site behavior (calendar ledger, serializer output, gate exclusivity) is narrowed or redefined.

## Step 9: Complete PRD — 2026-08-15T08:18:00.000Z

All edits are applied and verified. Here is the final summary.

**Source vs output**: `PRD_FINALIZED.md` (361 lines / 60,838 chars) → `PRD_COMPLETED.md` (361 lines / 64,702 chars). Char delta **+3,864**; line count unchanged (all changes are in-paragraph inserts/revisions; no new sections).

**Counts**: 29 ambiguity-pins, 5 mismatch-revisions (34 distinct behavioral pins across 27 edited paragraphs).

### Change log

- **§2.3** — insert — ambiguity — `limit`/`offset` must be integers, negative `offset` → `ERR_VALIDATION`; `created_at` ties broken by server receipt sequence — `core.py:383-405, 416`
- **§2.3** — insert — ambiguity — filters are exact-equality matches; `total_count` is the post-filter count; `has_more` iff `offset` + returned-page-size < `total_count` — `core.py:412-419`
- **§2.4** — revise — ambiguity — `version` starts at 1 at creation — `core.py:167`
- **§2.4** — revise — ambiguity — clock-set accepts any supplied instant (forward or backward), not strictly advancing — `routes_admin.py:249-258`
- **§2.4** — insert — ambiguity — ISO timestamps without an explicit offset are read as UTC — `core.py:122-137`
- **§2.5** — revise — mismatch — visibility compared exactly as supplied, not "at one decimal place" — `calc.py:77-86`
- **§2.8** — insert — ambiguity — strict shape typing: JSON booleans rejected where numbers expected, required strings must be non-empty, non-object JSON body → `ERR_VALIDATION` — `core.py:261-363`
- **§3.1** — revise — mismatch — dropped "unique across the entire fleet" claim for `tail_number` (impl enforces no uniqueness) — `routes_admin.py:58-72`
- **§3.1** — insert — ambiguity — aircraft self-transitions (`AVAILABLE`→`AVAILABLE`, `MAINTENANCE`→`MAINTENANCE`) are accepted and bump `version` — `routes_admin.py:91-104`
- **§3.2** — insert — ambiguity — membership `effective_from` pinned to strict `YYYY-MM-DD` — `routes_patients.py:50`, `core.py:140-150`
- **§3.2** — insert — ambiguity — intake accepts optional `emergency_override` (default `false`) — `routes_requests.py:56`
- **§3.2** — insert — ambiguity — `acceptance_acuity_score` and `acuity_tier` are null until first triage — `routes_requests.py:70-71`
- **§3.2** — revise — ambiguity — triage omitting `emergency_override` retains the request's stored value rather than defaulting — `routes_requests.py:111, 116-117`
- **§3.2** — revise — mismatch — decline `reason` is required on the payload but not persisted (impl validates then discards; no field in serializer) — `routes_requests.py:161-166`, `serialize.py:67-86`
- **§3.3** — insert — ambiguity — `planned_duration_min` must be an integer ≥ 1 — `routes_requests.py:209`
- **§3.3** — revise — ambiguity — tail set to `ASSIGNED` with a `version` bump on every acceptance, including additional bookings on an already-`ASSIGNED` tail — `routes_requests.py:280-281`
- **§3.4** — revise — mismatch — `visibility_sm` "compared at one decimal place" → compared exactly as supplied — `calc.py:77-86`
- **§3.4** — insert — ambiguity — weather filing is not gated on mission status; filing allowed against a mission in any state — `routes_missions.py:221-261`
- **§3.5** — insert — ambiguity — `to_state` ∈ {`AT_PATIENT`, `IN_TRANSIT`, `AT_DESTINATION`, `COMPLETED`} is `FlightCrew`-only; a `Dispatcher` naming any gets `ERR_FORBIDDEN` before the state guard; `LAUNCHED`/`WEATHER_HOLD` open to both roles — `routes_missions.py:38, 135-136`
- **§3.6** — insert — ambiguity — `estimated_ground_miles` optional but must be > 0 when present — `routes_coordination.py:36-37`
- **§3.6** — revise — ambiguity — `bed_reservation_id` accepted on either leg type; drives the release cascade only on `DESTINATION` legs — `routes_coordination.py:30-40`, `services.py:72-81`
- **§3.6** — insert — ambiguity — indicator recompute mutates the mission only when the value flips; folds into the triggering operation's single `version` bump on divert/abort/completion — `services.py:40-45, 104, 122, 149`
- **§3.7** — insert — ambiguity — a repatriation case may be opened for any mission regardless of transport class or state — `routes_repatriation.py:22-40`
- **§3.7** — insert — ambiguity — documents appendable while `COLLECTING` or `READY_TO_FLY` alike — `routes_repatriation.py:59-82`
- **§3.7** — revise — mismatch — validity evaluates the most recently appended entry per doc type (superseded entries ignored); a `PASSPORT`/`VISA` entry lacking `expires_iso` fails — `services.py:159-184`
- **§3.8** — insert — ambiguity — `approved_amount_cents` supplied on non-`PARTIAL` decisions is validated as an integer and recorded — `routes_billing.py:84-85, 99-100`
- **§3.8** — insert — ambiguity — invoice opens with `actual_loaded_miles`, `final_total_cents`, `patient_responsibility_cents` null — `routes_billing.py:133, 141, 145`
- **§3.8** — insert — ambiguity — finalize requires `actual_loaded_miles` > 0 — `routes_billing.py:181`
- **§3.8** — insert — ambiguity — finalize opens `patient_responsibility_cents` at the full `final_total_cents`; earliest-created qualifying membership bound when several qualify — `routes_billing.py:201-219`, `services.py:197-203`
- **§3.8** — insert — ambiguity — payer response `paid_cents`/`contractual_adjustment_cents` are required integers ≥ 0 — `routes_billing.py:255-256`
- **§3.9** — insert — ambiguity — a PCR may be opened against a mission in any status; born with `submitted_at` null — `routes_pcr.py:26-56`
- **§3.9** — insert — ambiguity — `deficiency_points` is an integer ≥ 0 — `routes_pcr.py:109`
- **§3.9** — insert — ambiguity — the 90-day deficiency-tally window is inclusive at both ends — `calc.py:270-277`
- **§4** — insert — ambiguity — repatriation document append answers `201` with the updated case (counts as a creation) — `routes_repatriation.py:82`

**Verified already-aligned (no change)**: envelope/meta shape, all 34 error-id→status mappings, all endpoint roles vs §4 table, acceptance check order, launch-gate order incl. decision-before-staleness and lazy repatriation demotion, divert/abort/completion cascades, charge-line pinned order and the 16.6666 worked example, provisional ceil(×1.15) mile pad, OCC protocol, fatigue-rule order (duty → rest → overlap) with 840/600 inclusive boundaries, membership reinstate window, timely-filing/PCR-window inclusivity, QA cascade with ≥15 threshold and PLANNING-only assignment release.

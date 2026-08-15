# Worklog — task_1940_electric_outage_management_storm

## Step 1: Create Task Directory — 2026-08-15T02:05:00.000Z

Directory `tasks/task_1940_electric_outage_management_storm/` and `workspace/` pre-created by the pipeline launcher (per command args; no index scan performed).

## Step 2: Generate Scaffold — 2026-08-15T03:03:08.623Z

Scaffold generation complete and lint-clean.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1940_electric_outage_management_storm/SCAFFOLD.yaml` (1961 lines — §1.0–§1.7, no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1940_electric_outage_management_storm/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1178 lines — single `scaffold_difficulty_design:` key)
- `/home/ubuntu/github/CodingPRD/tasks/task_1940_electric_outage_management_storm/SCAFFOLD_CORNER_DESIGN.yaml` (2477 lines — single `scaffold_corner_design:` key)

## Counts
- Entities: 16 | State machines: 13 | Calculations: 10 | Validation priorities: 9 | Endpoints: 91 | Errors: 43 | Roles: 9 | OCC concurrency rules: 2
- §1.8 instances (non-stub): 18 — all 9 rule_ids × exactly 2, all `distinguishing_aspect`s naming the required differentiation
- §1.9 instances: 63 non-stub + 7 `excluded_because:` stubs = 70 entries across all nine guide sections (entities 9, state_machines 10, calculations 7, validations 6, endpoints 4, errors 17, rbac 4, cross_cutting 3, consistency_model 1, plus stubs)
- Lint: `VERDICT: clean lint` — 91 endpoints, 1011 §1.8+§1.9 calls scanned, zero violations; all FKs reverse-reachable; all 43 error ids referenced; all `grounds:` resolve (verified by a second custom audit); all pinned numeric literals recomputed by executing the formulas (ETR 420/362/68/135-min cases, MA 320000 vs 185000, lodging shares 26418/39627/total 66046/residual 1, labor round-half-up 5001, FEMA 100000, scores 10400/600/10010/4410).

## Notable design decisions
- **Archetype**: quota/allocation (crews, lodging rooms, material stock) × temporal windowing; graph topology with a self-referential `Outage.parent_outage_id` nested-outage DAG (merge does cycle detection via parent-chain walk); segregation-of-duties role model (switching issuer≠approver, FEMA preparer≠certifier); entity-backed `FieldCrewLead` identity (`X-User-ID == Crew.id`) for ownership scoping.
- **Parallel state dimensions**: WorkOrder carries `execution_status × verification_status`; VERIFY_FAILED reopens execution cross-dimension and forces a system ETR revision — anchors both the non-linear-machine and cascade rules.
- **Dual-variant calcs on different domains**: ETR provisional (customers×cause factor) vs post-assessment (repair×crew factor), and mutual-aid full-window vs early-release (25% penalty on remaining days' rate only, per-diem excluded).
- **Combinatorial modes (a) and (b)**: 4-input priority score with nested min/conditional bonuses driving a deterministic dispatch selector (score DESC, `created_at` ASC, empty→ERR_NO_ELIGIBLE_WORK); lodging allocation pins per-share-then-sum rounding, yielding a falsifiable 1-cent residual.
- **Temporal precision**: logical clock (default 2026-08-01T00:00:00Z) drives ETR lock horizon [ETR−30min, ETR] with NESTED_DISCOVERED exemption, backward-revision CORRECTION-only rule, 360-min extension cap (inclusive), half-open lodging adjacency vs crew-window containment (the two Rule-8 semantics), cert-expiry sweeps that recompute derived priority scores, and a 96-hour FEMA eligibility window with inclusive edges.
- **Compensating invariants**: stock units (`on_hand + reserved` constant across stage/cancel) and ledger cents (issue + reversal with `reversed_entry_id` nets to zero) — different conserved quantities.
- **OCC** (true create-with-supersede races only): `expected_outage_version` on ETR revision and assessment-accept; assign/verify races deliberately classified as state preconditions per the §1.2.1 filter.

## Step 3: Copy Shared Files — 2026-08-15T03:03:33.369Z

Copied `./INSTRUCTION.md` → `tasks/task_1940_electric_outage_management_storm/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T03:21:46.483Z

All audits pass. Here is the summary.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1940_electric_outage_management_storm/workspace/PRD.md` — 407 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications (12 subsections): 2.1 Roles/RBAC, 2.2 Response Structure (verbatim block — byte-for-byte match confirmed), 2.3 Pagination, 2.4 The Logical Clock, 2.5 Common Resource Properties, 2.6 Cross-Entity Consistency and Version Semantics, 2.7 Validation Order and Nested Path Resolution, 2.8 OCC on Outage Records, 2.9 Money/Minutes/Rounding, 2.10 The Event Cost Ledger, 2.11 Restoration-Time Publication Discipline, 2.12 Fatigue and Segregation-of-Duties
- §3 Business Logic (9 subsections, chronological storm timeline): 3.1 Event/Feeder/Priority registry, 3.2 Signal ingestion and clustering, 3.3 Outage confirmation/nesting/merge/cancel, 3.4 Damage assessment and ETR life, 3.5 Crews/work orders/dispatch, 3.6 Switching authority and verification, 3.7 Mutual aid and lodging, 3.8 Materials and cost ledger, 3.9 Demobilization/closure/FEMA
- §4 Endpoint Definitions (4-column table), §5 Error Code Catalogue (2-column table)

**Coverage counts:** 16 entities (all fields), 91 endpoints (91 table rows), 43 errors (43 table rows, all also cited in §2/§3 prose), 90 enum/state values, 57 state transitions, 10 calculations, 2 OCC rules, 9-priority validation cascade.

**Zero-Silence self-audit (all three hard contracts PASS):**
- Contract 1 (field names): 127 required, 127 present, 0 missing (one repair: `crew_status`; note — audit script must strip fenced JSON blocks before extracting backticks, since the fences unbalance naive token pairing)
- Contract 2 (rules): 9/9 validation priorities expressed as an ordered cascade with the own-state-before-child-state pin and 403/400/409 status-code exceptions; 2/2 OCC rules with endpoint + `expected_outage_version` + `ERR_STALE_OUTAGE_VERSION`/412 and no race framing; 57/57 transitions (two phrasing repairs: explicit `SUBMITTED`→`ACCEPTED` landing and end-shift→`OFF_DUTY` destination); 10/10 calculations reconstructed in prose with rounding pins, boundary inclusivity, and the accept-time evaluation-order pin; all cascade side effects (merge, verify-fail reopen, cancel, lodging waterfall, departure postings) fully enumerated; sibling branches (merge vs cancel, PASSED vs FAILED, permanent vs revision withdraw, full vs early departure) rendered symmetrically
- Contract 3 (§3 path purity): 655 backticked tokens scanned, 0 path/method violations

**Notable scattering/weaving decisions:**
- ETR rules split three ways: publication gates in §2.11 (contract zone), provisional formula with the confirm narrative (§3.3), post-assessment formula + OCC + evaluation-order pin with the accept workflow (§3.4); the 180-minute verification-failure revision lives in §3.6.
- Constants delivered with exact unit conversions for inference load: 960 min as "sixteen hours", 360 min as "six hours", 180 min as "three hours", 60 min clustering window, 96-hour eligibility as "ninety-six hours (four days)"; money kept in cents with worked rounding examples (labor 30 min @ 10,001 → 5,001 cents; lodging 26,418/39,627/66,046 residual example) to pin half-up ordering.
- Priority-score formula placed in §3.3 at confirmation; the dispatch selector that consumes it in §3.5; fatigue rule stated as contract in §2.12 and re-expressed operationally at assign/dispatch in §3.5.
- `expected_outage_version` appears in both §2.8 (OCC mechanism) and §3.4 (accept + manual-revision workflows); query-param filter names are woven into each §3 workflow's closing sentence rather than listed in §4.

## Step 5: Generate Unit Tests — 2026-08-15T03:50:20.577Z

All deliverables complete. Here's the final summary.

## Summary

**Files written**

`test_helpers/` (Stage 1):
- `types.py` — TypedDicts + status enums for all 16 entities. TroubleSignal/EtrRevision/CostLedgerEntry deliberately omit `updated_at`/`version` (append-only per PRD §2.5).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (52 endpoints under `/om`).
- `api_errors.py` — 43 `ApiErrorId` values + HTTP status map, registered with framework.
- `assertions.py` — per-entity shape assertions + `assert_stock_conservation` + `assert_event_rollup` invariants.
- `factories.py` — per-entity payload factories with unique-name counters.
- `constants.py` — calculation thresholds from PRD (ETR/fatigue/FEMA/lodging/priority-score constants).
- `test_users.py` — TEST_USERS dict for 9 roles + `make_field_crew_lead_headers(crew_id)` for the entity-backed role.
- `fixtures.py` — composite helpers: `setup_event_with_feeder`, `setup_outage_with_accepted_assessment`, `run_work_order_to_completed`, `setup_completed_work_order_scenario`, `setup_verified_outage`, `create_available_mutual_aid_crew`, `create_committed_lodging_block`, `create_issued/executed_switching_order`, `setup_demobilized_event_with_claim`, etc.
- `__init__.py` — barrel export.

`test_suite/` (Stage 2): `conftest.py` + 17 test files (98 tests total).

**Test count by queue**
- Queue A (Difficulty): 18 instances × 2 tests = **36 tests** across test_01–test_09.
- Queue B (Corner): 63 non-stub instances → **62 tests** across test_10–test_17. One instance skipped (see below).

**Skipped instance**
- `Corner/entities/outage_create_computed_field_input_ignored` — asserts that a client-supplied `priority_score: 999` is silently ignored (not stored). PRD §3.3/§2.5 declares `priority_score` computed but never states whether the server must silently drop or must reject such input. Both behaviors are PRD-consistent (not uniquely derivable), so the instance was skipped per the PRD-first two-condition filter.

**Design-tag audit**
- All 80 unique emitted tags resolve to real source instances (18 Difficulty + 62 Corner).
- Every Difficulty instance has exactly 2 tests; every non-stub Corner instance has ≥1.
- All 7 `excluded_because` stubs cross-reference valid Difficulty instances (verified programmatically); none were translated.
- No untagged, dual-tagged, or dangling-tag tests.

**Notable fixture/factory decisions**
- `run_work_order_to_completed(outage_id, crew_id, arrive_clock_iso, complete_clock_iso)` accepts clock-override hooks so fatigue and labor tests can pin worked minutes exactly (00:00→15:00 = 900 min).
- `setup_outage_with_accepted_assessment` returns the post-accept outage with its OCC-bumped `version`, so accept/revision tests can chain on a known version without re-reading.
- FieldCrewLead headers are always built per-instance via `make_field_crew_lead_headers(crew_id)`; the shared `TEST_USERS["field_crew_lead_headers"]` is never used in ownership-gated paths.
- Two SystemOperator constants (`system_operator_headers` for op-1, `system_operator_2_headers` for op-2) and two ClaimsOfficer constants (`co-1`, `co-2`) make the SoD tests expressible without inline header construction.
- FEMA boundary test helper `_setup_event_with_100000_eligible` builds exactly 100000 eligible cents (12000 in-window labor + 88000 material at the inclusive window edge) so claim A (threshold 100000) and claim B (100001) can be tested on the same ledger state.

**Verification**: all 17 test files parse, pytest collects **98 tests** cleanly under `PYTHONPATH=.`.

## Step 6: Generate Implementation — 2026-08-15T03:50:20.577Z

91 implemented == 91 specified. Everything checks out.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1940_electric_outage_management_storm/workspace/implementation/`):
- `start.sh` (executable), `requirements.txt`, `app.py`
- `db.py` — in-memory `Store` (16 entity dicts keyed by id + lodging-assignment fact list) and the logical clock
- `errors.py`, `response.py`, `middleware.py`
- `services/core.py` — constants, body validators, pagination, entity lookups, all derived-field calculators, ledger/ETR-revision writers, 16 serializers
- `routes/` — 13 blueprints: `clock`, `storm_events`, `feeders`, `priority_customers`, `trouble_signals`, `outages`, `damage_assessments`, `crews`, `mutual_aid`, `lodging`, `work_orders`, `switching_orders`, `materials`, `ledger`, `fema`

**Endpoints: 91 of 91** from the PRD §4 table implemented and verified by AST count.

**Structure of key mechanics:**
- **Logical clock**: `db._now` defaults to exactly `2026-08-01T00:00:00Z`, never wall-clock. `POST /om/_clock/set_current_utc` sets it and runs the certification sweep (CERTIFIED with `certified_through` strictly before now → SUSPENDED, version-bumped; feeder/outage derivatives are computed on read, so the sweep's recomputation is inherently consistent).
- **OCC**: `expected_outage_version` is mandatory-int validated on `POST /om/outages/{id}/etr-revisions` and `POST /om/damage-assessments/{id}/accept`; mismatch → `ERR_STALE_OUTAGE_VERSION` (412), checked after state gates and before any mutation. Assessment accept and confirm each bump `Outage.version` exactly once for the whole request.
- **Validation cascade**: auth headers (400) → role (403) → path/body FK existence (404, left-to-right) → own-state + event-posture/child-state (400) → safety/SoD/ownership (422/403) → referential (422) → temporal (422) → constraint (422/400/409) → capacity/fiscal (422), with malformed bodies → `ERR_INVALID_REQUEST` (400). Exact scaffold error IDs and HTTP statuses throughout.
- **Calculations**: `Decimal` with `ROUND_HALF_UP` at each pinned step — provisional ETR (120 + round_half_up(min(ca,5000)·2·cause_factor)), post-assessment ETR (crew_factor 1.0/1.5 applied then rounded, then +45 switching), ETR gates in PRD order (in-past → backward → cap 360 inclusive → 30-min lock horizon), clustering (60-min anchored window, threshold-equality promotes, `occurred_at`/`created_at` ordering), priority score (10000/4000/min(ca,10000)/50·whole-hours/2000 missed, floor hour truncation), fatigue (worked + estimate ≤ 960 inclusive), mutual-aid engagement (ceil days, 25% penalty on daily rate only, rounded at final step), lodging waterfall (per-crew share rounded first, block total rounded separately, residual entry), labor posting (round at posting), event rollup (reversals net out), FEMA eligibility (96-h window inclusive, lodging/penalty excluded).
- **Derived fields** are computed at serialization time (cost rollups, `quantity_reserved/available`, `rooms_allocated`, `certified_priority_count`, `has_priority_customers`, `etr_missed`, `priority_score`, `worked_minutes_this_shift`, `eligible_cost_cents`, `variance_cents`) so they can never be stale; `version`/`updated_at` bump on every mutation including cascaded ones.

**start.sh contract**: `set -euo pipefail`, `cd "$(dirname "$0")"`, guarded install (`if ! python3 -c "import flask"` — no-op when deps present so per-test reboots don't contended-install), `exec python3 app.py` in foreground; `app.py` binds `0.0.0.0` on `PORT` (default 10000). Boots in ~1 s.

**Boot smoke test**: three end-to-end suites plus a `start.sh` fresh-boot check all pass — covering the full outage lifecycle (cluster-promote → confirm with exact provisional ETR 02:09 → manual revision with OCC 412 / in-past / 361-min cap rejection / 360-min acceptance → assessment accept with single version bump and post-assessment ETR 06:02 → dispatch/arrive/start/complete with labor posting → verify-FAILED reopen + 180-min system revision → re-complete → restore → ping → verify), switching-order SoD, material stage/issue/return with reversal netting, the PRD's exact lodging waterfall (shares 26418+39627, residual 1, total 66046), mutual-aid early-release penalty (engagement 1250, penalty excluded from FEMA), FEMA lifecycle including SoD and snapshot/variance, demobilize/close gates, `ERR_EVENT_CLOSED`, merge (customer transfer, cycle detection, cross-event rejection), dispatch_next ranking, fatigue 961-min rejection, and clock-sweep suspension. Fresh boot verified empty (`total_count == 0`) — no seeding anywhere.

## Step 7: Run Tests and Iterate — 2026-08-15T04:09:10.242Z

Clean 8-round parallel sweep: 98/98 passed in every round, zero non-passed tests across all rounds.

## Summary

**Iterations run:** 3 sweeps (baseline 77/98 → after batch fixes 97/98 → clean 98/98 ×8 rounds). All 21 initial failures were stable (identical across all 8 baseline rounds — no flakiness observed).

**Tests deleted:** none. Every failure traced to a test-artifact bug; no PRD-silent assertion had to be removed.

**Fixes applied to `test_helpers/`:**
- `assertions.py` — added `assert_instant_equals(actual, expected)`: parses both ISO 8601 strings and compares instants. PRD pins the three-fractional-digit format only for `created_at`/`updated_at`/`api_request_timestamp` (§2.2/§2.5); ETR/arrival timestamps are format-free, so exact-string equality on them was not uniquely derivable (two-reader collapse: `.000Z` vs `Z`). The instant values asserted remain verbatim PRD formulas.
- `assertions.py` — rewrote `assert_stock_conservation`: the old helper asserted `on_hand + reserved == expected_total`, which contradicts PRD §3.8 ("Staging ... adds the quantity to the pool's `quantity_reserved`"; `quantity_on_hand` decreases only at issue). New helper asserts the PRD-verbatim identity `quantity_available == quantity_on_hand − quantity_reserved`, non-negativity, and `on_hand ≤ expected_total` (units never materialize).

**Fixes applied to `test_suite/`:**
- `test_13_corner_validations.py` — added missing `create_stock` import (NameError in `test_duplicate_stock_rejected_409`).
- `test_17_corner_cross_cutting.py` — added missing `create_work_order_payload` import (NameError in `test_ready_without_accepted_assessment_rejected`).
- `test_06_difficulty_boundary_precision.py` (2 tests), `test_12_corner_calculations.py` (2 tests) — setup posted trouble signals with `occurred_at` after the logical now; the implementation correctly rejected them per PRD §3.2 `ERR_SIGNAL_IN_FUTURE`. Moved `clock_iso` past the last signal timestamp (01:00Z / 01:02Z), preserving each test's boundary intent.
- `test_12_corner_calculations.py::test_etr_extension_cap_boundary_360` — the over-cap attempt asserted 13:00→13:01 (+1 min) must fail, which contradicts PRD §2.11 ("at most 360 minutes in a single revision" — per-revision semantics). Rewrote the over-cap attempt as 13:00→19:01 (+361 min in one revision), keeping the exact-360-allowed boundary check intact.
- 21 timestamp assertions across `test_01`, `test_03`, `test_04`, `test_11`, `test_12`, `test_17` converted from exact-string equality to `assert_instant_equals`; `test_10_corner_entities.py:49` (`created_at`) was instead corrected to the PRD-verbatim three-fractional-digit string `"2026-08-10T00:00:00.000Z"`, since §2.5 uniquely pins that format for `created_at`.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful in every failure (3-fractional-digit timestamps, future-signal rejection, per-revision ETR cap, staging not decrementing `quantity_on_hand`); all defects were in the test layer.

## Step 8: Finalize PRD — 2026-08-15T04:17:29.785Z

## Summary

**Line counts:** `PRD.md` = 407 lines, `PRD_FINALIZED.md` = 409 lines (+2 lines, +0.49%). One insertion, zero deletions, zero revisions to existing prose.

### Changes (one bullet per change)

- **§2.5 Common Resource Properties — insert** — Added a two-rule timestamp-representation paragraph after the append-style-records sentence: (1) every server-computed instant (`activated_at`, `confirmed_at`, `restoration_reported_at`, `shift_started_at`, `arrived_at`, `completed_at`, `departed_at`, `posted_at`, clock `current_utc`, every `published_etr`, and transitively `previous_etr`/`current_etr`) is rendered in the same ISO 8601 UTC three-fractional-digit form as `created_at`, including a manually published `published_etr` whose request payload spelled the instant differently; (2) client-supplied instants stored as sent (`occurred_at`, `certified_through`, `committed_window_start/end`, `window_start/end`) are echoed verbatim; all temporal rules parse to instants before comparing. — `implementation/db.py:65-78` (`iso_ms`/`now_iso`), `implementation/services/core.py:467,489` (`posted_at`, `published_etr`), `implementation/routes/outages.py:319,365` (manual revision parses then normalizes), `implementation/routes/trouble_signals.py:62`, `implementation/routes/priority_customers.py:75`, `implementation/routes/mutual_aid.py:55-56`, `implementation/routes/lodging.py:60-61` (verbatim echoes).

### Step 7 diff items that required NO PRD edit (with verification)

- `assert_stock_conservation` rewrite — pure test-helper bug; PRD §3.8 already pins staging-adds-to-reserved / issue-decrements-on-hand, and impl matches (`implementation/routes/materials.py:124-147`: stage flips status only, `quantity_reserved` derived from `STAGED` rows in `services/core.py:343-347`).
- Import fixes in `test_13`/`test_17` — fixture bugs, no behavioral content.
- Future-signal clock moves (`test_06` ×2, `test_12` ×2) — fixture bugs; PRD §3.2 already pins `ERR_SIGNAL_IN_FUTURE` ("must not lie after the logical now"); impl enforces strictly-greater comparison (`routes/trouble_signals.py:34`).
- `test_etr_extension_cap_boundary_360` rewrite — test bug (had asserted a cumulative cap); PRD §2.11 already pins per-revision semantics ("at most 360 minutes in a single revision"); impl measures `published − current_etr` per request (`routes/outages.py:352-356`).
- `test_10:49` `created_at` exact-string — PRD §2.5 already pins the three-fractional-digit format for `created_at`; impl conforms (`services/core.py:248`).

### Per-edit pre-edit search log

**Edit 1 (§2.5 timestamp representation insert):**
- (a) Subject: string representation of every timestamp field emitted in any API response — the subject of the Step 7 `assert_instant_equals` fix (21 converted assertions on `current_etr`/`previous_etr`/`confirmed_at`/`arrived_at` across test_01/03/04/11/12/17).
- (b) Impl paths enumerated and read: the single formatter `iso_ms`/`now_iso` (`implementation/db.py:65-78`); all 16 serializers (`implementation/services/core.py:510-776`); every `iso_ms` write site via grep — `response.py:15`, `core.py:241,248-249,259,467,489`, `clock.py:40,46`, `storm_events.py:72`, `outages.py:115,258`, `work_orders.py:203,259`, `mutual_aid.py:110,153,200`; the shared revision writer `create_etr_revision` (`core.py:474-495`) through which all four revision kinds (INITIAL, DAMAGE_FOUND, VERIFICATION_FAILED, manual) funnel; every client-datetime intake via grep for `req_datetime` (six sites: `to_iso8601`, `certified_through`, `occurred_at`, manual `published_etr`, `window_start/end`, `committed_window_start/end`) and their storage lines confirming verbatim echo vs. normalization; every comparison site (clustering sort `storm_events.py:146-151`, verify ping gate `outages.py:285-290`, cert sweep `clock.py:38`, engagement windows `mutual_aid.py:104-106`, `work_orders.py:146-148`, lodging containment/overlap `mutual_aid.py:134-137`, `lodging.py:47-49`, FEMA window `core.py:396-407`, fatigue `core.py:332-339`) — all parse to instants.
- (c) Wording adjustment: the first draft universally claimed "all other timestamps use the three-fractional-digit format," which would have mis-described the five verbatim-echoed client fields found in (b); the committed wording splits the two verified classes and explicitly scopes the normalization claim to server-computed instants (with manual `published_etr` called out as normalized despite being client-supplied), keeping every enumerated path accurately described.

`PRD_FINALIZED.md` is at `/home/ubuntu/github/CodingPRD/tasks/task_1940_electric_outage_management_storm/workspace/PRD_FINALIZED.md`.

## Step 9: Complete PRD — 2026-08-15T04:36:38.784Z

PRD_COMPLETED.md is complete. All headers and table rows are structurally identical (line numbers shifted +2 from one inserted paragraph); every change is an inline insert/revision within existing sections.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 409 lines / 71,112 chars → `PRD_COMPLETED.md` 411 lines / 74,054 chars (+2 lines, +2,942 chars).

**Counts:** 8 ambiguity-pins, 7 mismatch-revisions (15 changes total).

### Changes

- **§2.2** — insert — ambiguity — `api_request_timestamp` pinned as read from the logical clock, not wall clock — `implementation/response.py:15` (`_meta` uses `now_iso()` → `db.now()`).
- **§2.3** — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (400), not clamped — `implementation/services/core.py:130-150`.
- **§2.3** — insert — ambiguity — `has_more` defined as `offset + len(returned) < total_count` — `implementation/response.py:33`.
- **§2.5** — insert — ambiguity — `version` starts at 1 at creation — `implementation/services/core.py:244-252` (`new_common`).
- **§2.5** — insert — ambiguity — server-computed instants are stamped from the logical clock — `implementation/services/core.py:241` (`bump` uses `iso_ms(db.now())`).
- **§2.7** — revise — mismatch — `ERR_FATIGUE_LIMIT_EXCEEDED` moved from gate 5 to gate 8, with availability → crew-type → fatigue ordering pinned, matching `_do_assign`/`dispatch_next` which check availability and type before fatigue — `implementation/routes/work_orders.py:124-133`, `implementation/routes/storm_events.py:225-230`.
- **§2.7** — insert — mismatch — endpoint-local exception: at signal ingestion the `occurred_at`-future check fires before the restore ping's `outage_id` existence/state checks and before the no-`outage_id` rule for other types — `implementation/routes/trouble_signals.py:34-55`.
- **§2.8** — insert — ambiguity — OCC comparison ordered after body validation, event-closure, and state preconditions, before the remaining gates — `implementation/routes/outages.py:319-342`, `implementation/routes/damage_assessments.py:125-143`.
- **§2.10** — revise — mismatch — `reversed_entry_id` is present on every ledger entry and null on originals (PRD said "on reversal entries only") — `implementation/services/core.py:468`, `:753`.
- **§3.1** — revise — mismatch — dropped "unique" from `feeder_code` (no uniqueness enforced) — `implementation/routes/feeders.py:16-33`.
- **§3.2** — insert — ambiguity — clustering pass responds 200 with a summary; on no candidates or failed promotion it reports `promoted: false`, `outage_id: null`, `clustered_signal_count: 0` — `implementation/routes/storm_events.py:142-143`, `:161-186`.
- **§3.3** — insert — ambiguity — merge response carries the retired source outage — `implementation/routes/outages.py:213`.
- **§3.4** — insert — ambiguity — unknown `FieldCrewLead` crew identity at assessment creation rejected with `ERR_INVALID_REQUEST` — `implementation/routes/damage_assessments.py:45-48`.
- **§3.4** — insert — ambiguity — manual ETR revisions accepted only from `CONFIRMED`/`ASSESSED`/`WORKING`/`RESTORED`; `SUSPECTED`/`VERIFIED`/`CANCELLED` → `ERR_INVALID_STATE_TRANSITION` — `implementation/routes/outages.py:328-330`.
- **§3.5** — revise — mismatch — dropped "unique" from `crew_code` (no uniqueness enforced) — `implementation/routes/crews.py:17-34`.
- **§3.5** — insert — ambiguity — work-order creation is not gated on the linked outage's status (only event closure) — `implementation/routes/work_orders.py:42-68`.
- **§3.5** — insert — ambiguity — `dispatch_next` evaluates the eligible set before crew availability, so an empty set yields `ERR_NO_ELIGIBLE_WORK` even for a non-`AVAILABLE` crew — `implementation/routes/storm_events.py:199-226`.
- **§3.7** — revise — mismatch — departure bills a floor of one day even at zero elapsed time — `implementation/routes/mutual_aid.py:209` (`max(1, ceil(...)) ... else 1`).
- **§3.7** — revise — mismatch — lodging waterfall uses facts recorded at assignment time only (no removal facts exist), partial overlap days discarded, and the residual posts as "one final overhead `LODGING` entry" (dropped "with no crew reference" — ledger entries carry no crew field) — `implementation/routes/lodging.py:129-155`, `implementation/services/core.py:457-471`.
- **§3.9** — revise — mismatch — the `ERR_EVENT_CLOSED` blanket replaced with an explicit enumeration of closure-gated mutations and of the record-keeping transitions that remain available (assessment submit/return, WO arrival, switching issue/approve/abort, mutual-aid demobilize/cancel, requisition consume/cancel, dispatch selector, FEMA lifecycle from submission onward) — `check_event_not_closed` call sites across `routes/*.py` (absent at `work_orders.py:190` arrive, `switching_orders.py:77/91/129`, `mutual_aid.py:162/237`, `materials.py:195/207`, `fema.py:66-152`).

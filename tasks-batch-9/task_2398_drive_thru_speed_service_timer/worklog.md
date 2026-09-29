# Worklog — task_2398_drive_thru_speed_service_timer

## Step 1: Create task directory — 2026-09-02T07:06:17.471Z

Created `tasks/task_2398_drive_thru_speed_service_timer/` and `tasks/task_2398_drive_thru_speed_service_timer/workspace/` (pre-allocated task name used verbatim; no index scan).

## Step 2: Generate scaffold — 2026-09-02T08:51:38.220Z

Both setup-chain replay checks now pass. The scaffold for task 2398 is complete.

## Deliverables

All three files at `/home/ubuntu/github/CodingPRD/tasks/task_2398_drive_thru_speed_service_timer/`:

**`SCAFFOLD.yaml`** (§1.0–§1.7, 2132 lines) — `domain_name: drive-thru-speed-of-service`, `api_prefix: /drive-thru`, `difficulty_level: beyond_expert`, `consistency_model: immediate`, complexity layers `[cascading_side_effects, rate_threshold_triggers, dual_variant_calculation, optimistic_concurrency]`.
- **12 entities**: Restaurant, DaypartProfile, VolumeTierPolicy, TimerLoop, MergeSlot, PullForwardOrder, AccuracyIncident, StaffMember, OrderTakerDeployment, LaborMinutesLedger, ThroughputReport, CoachingIntervention, ForecastOverride
- **11 state-machine blocks** (TimerLoop declares two independent parallel dimensions: timing_state and accuracy_state)
- **12 calculations** — `loop_segment_durations`, `loop_adjusted_total`, `incident_severity_and_cost`, `oot_requirement` (dual-variant on `staffing_basis`), `merge_award_selection`, `labor_minutes_ledger`, `restaurant_rollup_recompute` (9 pinned steps), `coaching_pool_points` (8 pinned steps), `coaching_priority_score` (weighted saturation), plus report attainment/relief and target pinning
- **33 ordered validations** with a fully pinned priority ladder (1 auth → 33 labor budget), **57 errors**, **64 endpoints**, **5 roles** (ProgramAdmin, Operator, ShiftLead, TimerAnalyst, Auditor), **2 §1.2.1 OCC rules** (both on `expected_restaurant_version` → `ERR_STALE_RESTAURANT_VERSION` 412)

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (§1.8, 2414 lines) — all **9 §0.5 rules, 23 instances** (2/3/2/2/3/3/2/3/3). Highlights: circular window-tier evaluation order in `coaching_pool_points`, TimerLoop's two dimensions advancing independently, depart-cascade slot release flipping posture to SURGE, priority-pair conflicts (state-over-fiscal, safety-over-temporal, referential-over-state), half-open daypart adjacency vs closed-interval deployment buffer, and three compensating invariants (labor minutes conserved on activate→abort, remake cost reversed on waive, merge capacity conserved on award→abandon).

**`SCAFFOLD_CORNER_DESIGN.yaml`** (§1.9, 5486 lines) — all **9 closed-taxonomy sections, 86 instances** = 73 active recipes + 13 `excluded_because` stubs: entities 14, state_machines 14, calculations 10, validations 18, endpoints 4, errors 10, rbac 7, cross_cutting_complexity_layers 8, consistency_model 1.

## Verification

```
Coverage
  §1.5 endpoints declared:    64
  §1.1 entities declared:     12
  §1.8 instances scanned:     23
  §1.9 instances scanned:     73
  Calls scanned (§1.8+§1.9):  1298

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

- **Replay check 1** (call-by-call preconditions): 96 recipe-bearing instances walked — every `${var}` bound by an earlier `captures:`, logical clock monotonic, timer-loop lifecycle ordered, store numbers unique per instance. **0 problems.**
- **Replay check 2** (end-state side-effect replay): forward-simulated profile activation state + daypart minute windows at loop create, loop timing-state guards for greet/order-complete/window-arrive/depart, incident and pull-forward parent-state gates, deployment PLANNED→ACTIVE→RELEASED/ABORTED ordering, and report DRAFT→PUBLISHED before coaching creation. **0 problems.**
- All **57 catalog errors** confirmed positively triggerable (four — `ERR_INVALID_SLOT_STATE`, `ERR_LABOR_BUDGET_EXCEEDED`, `ERR_PROFILE_NOT_FOUND`, `ERR_STAFF_NOT_AVAILABLE` — previously appeared only in negative assertions and got dedicated instances C-2398-69…72).
- 86 globally unique instance names, no collisions within or across design files; all 13 stub `difficulty_instance:` back-references resolve to real §1.8 names.

The hard constraint was honored: no sibling task directory was listed, globbed, grepped, or read at any point — the scaffold derives solely from the scenario description and the generator skill's own specification.

## Step 3: Copy shared files — 2026-09-02T08:52:01.520Z

Copied project-root `INSTRUCTION.md` to `tasks/task_2398_drive_thru_speed_service_timer/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T09:08:00.000Z

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2398_drive_thru_speed_service_timer/workspace/PRD.md` — 504 lines / ~13,300 words / 104 KB. Source read was limited to `SCAFFOLD.yaml`, `worklog.md`, and the doc-generator skill's own files; neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was inspected.

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 135 required, 135 present, 0 missing
- endpoints[].request_body: 72 required, 72 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing (this scaffold folds list filters into endpoints[].input)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 33 checked, 33 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_restaurant_version + ERR_STALE_RESTAURANT_VERSION all named), 0 missing
- state_machines[].transitions: 62 checked, 62 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed, 0 missing
- validations[] conditions: 57 error ids checked, 57 matchable to a trigger condition in prose, 0 missing
- endpoints[].side_effects / applies_to: 43 mutating endpoints checked, 43 expressed, 0 missing
- entities[].fields[] structured content: 135 checked (all enums, defaults, ranges and uniqueness constraints), 135 reconstructible from prose, 0 missing
- sibling-branch symmetry: 7 groups checked (close/waive, release/abort, publish/retract, acknowledge/contest, approve/reject, PROVISIONAL/FINAL, OBSERVED/FORECAST_ADJUSTED), 7 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 902
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Structure

- **§1 Introduction** — 3 paragraphs framing the timer program, the interaction between volume/accuracy/staffing signals, and the `/drive-thru` prefix.
- **§2 Global Specifications** — 12 subsections: roles & access scoping (5 roles, 2 entity-backed); §2.2 API Response Structure pasted **byte-identical** to `section-2.2-response-structure.md` (verified programmatically); pagination; the logical clock (`2026-08-01T00:00:00Z`, never wall-clock); common resource properties & `Restaurant.version` stamping; `service_posture` as master gate (8 named frozen-gate exemptions); the 9-step pinned rollup chain; volume-tier bands & relief; rounding/precision discipline; OCC version preconditions; the **33-entry priority ladder**; path resolution order.
- **§3 Business Logic** — 9 subsections following the domain lifecycle: store standup, roster & OOT staffing model, timer loop arrive→depart, merge sequencing, pull-forward, accuracy/remake/settlement, forecast overrides, throughput reporting, coaching. All 12 calculations translated to prose with pinned evaluation order and no pseudocode.
- **§4 Endpoint Definitions** — 64 rows (Method / Path / Description / Authorized Roles), plus the 201-vs-200 convention paragraph. All 64 scaffold paths verified present.
- **§5 Error Code Definitions** — 57 rows (Error ID / HTTP Status), no condition column. All 57 scaffold error ids verified present, and every one also appears with its trigger condition in §2 or §3.

Document ends at the §5 table — no audit footer.

## Notable content decisions

- The two dual-variant pairs are given deliberately symmetric treatment: `oot_requirement` under `OBSERVED` vs `FORECAST_ADJUSTED`, and `PROVISIONAL` (`depart_at`-anchored, `TOTAL`, excludes `REMAKE_OPEN`) vs `FINAL` (`arrive_at`-anchored, `ADJUSTED_TOTAL`, includes `REMAKE_OPEN`, 300 s abandon penalty).
- Rounding order is called out explicitly where it is load-bearing: the four pinned segment targets are rounded **individually** before summing into `target_total_seconds_pinned`, and `mean_pinned_target_seconds` is held exact/unrounded as an intermediate.
- `TimerLoop`'s two independent dimensions (`timing_state`, `accuracy_state`) are described as parallel throughout, including the late-guest-complaint path `VERIFIED → REMAKE_OPEN` on an already-`CLOSED` car.
- Interval semantics are stated per rule where they differ: half-open daypart windows (touching bounds legal) vs closed deployment intervals with an additive 600 s buffer (touching rejected) vs closed override windows (touching counts as intersecting for the 0.50 aggregate cap).
- Two prose corrections were made after the first pass: the six system-driven posture reconciliations are now enumerated explicitly in §2.6, and coaching issue is now stated to recompute `segment_gap_seconds` as well as `priority_score` and `tier`, matching the `coaching_priority_score` trigger.

## Step 5: Generate unit tests — 2026-09-02T10:39:00.000Z

Test generation for `task_2398_drive_thru_speed_service_timer` is complete.

## Files written

**`test_helpers/`** (9 files, infrastructure only — no tests):
`__init__.py`, `api_client.py` (`DriveThruApiClient`, every declared endpoint), `api_errors.py` (all error-id constants + HTTP status map registration), `assertions.py` (domain assertion vocabulary: pinned targets, loop segments, breach flags, rollup, labor ledger, merge capacity, report metrics, coaching scoring, deployment charge), `constants.py`, `factories.py` (request-body builders), `fixtures.py` (`StoreContext` + scenario builders: bands, stores, rosters, profiles, loop driving, merges, pull-forwards, incidents, reports, coaching, overrides), `test_users.py` (identity threading for the two entity-backed roles and three opaque roles), `types.py`.

**`test_suite/`** — `conftest.py` plus 18 test modules, **151 tests total**.

## Test counts per queue

| Queue | Instances | Tests |
|---|---|---|
| A — Difficulty (§1.8) | 23 of 23 non-stub | **69** (3 per instance, exceeding the ≥2 rule) |
| B — Corner (§1.9) | 73 of 73 non-stub | **82** |

Queue A: `test_01`–`test_09` (6/9/6/6/9/9/6/9/9).
Queue B: `test_10_corner_entities` 14, `test_11_corner_state_machines` 12, `test_12_corner_calculations` 15, `test_13_corner_validations` 15, `test_14_corner_endpoints` 4, `test_15_corner_errors` 10, `test_16_corner_rbac` 7, `test_17_corner_cross_cutting` 4, `test_18_corner_consistency` 1.

## Instances skipped

**None on the PRD-first filter.** Every non-stub instance in both indices translated cleanly — all 96 have verbatim PRD coverage and PRD-derivable outcomes.

The 13 `excluded_because:` stubs in the corner index were correctly not translated (each defers to a §1.8 instance already covered by queue A): `entities/entity_timer_loop_cross_store_fk_rejected`; four `state_machines/*`; `calculations/calc_variant_divergence_same_rows_two_answers`; three `validations/val_*_outranks_*`; four `cross_cutting_complexity_layers/*`.

## Verification performed

- `python3 -m py_compile` clean on every module; `pyflakes` reports zero findings across `test_suite/` and `test_helpers/` (no unused imports, no undefined names).
- `pytest --collect-only`: **151 tests collected**, no collection errors.
- Citation checker (`/tmp/check_citations.py`): 151/151 pass — every test has a docstring, exactly one `Design:` line as its last line, at least one quoted PRD span, and every quoted span survives a whitespace-normalized literal match against `workspace/PRD.md`. No occurrence of the word "scaffold" anywhere in generated code.
- Coverage audit against both YAMLs: 0 unknown tags, 0 dual tags, 0 stubs translated, 0 uncovered non-stub instances, 0 difficulty instances below the 2-test floor.

## Two findings worth relaying

1. **Section-reference bug I introduced and fixed.** Four modules (`test_13`, `test_15`, `test_16`, `test_17`) initially cited the request-check priority ladder as "PRD §2.9". §2.9 is *Numeric Precision and Rounding Discipline*; the ladder is **§2.11** (*The Order in Which a Request Is Checked*). All 16 occurrences corrected. The earlier modules (`test_05`, `test_06`, `test_10`, `test_11`) had it right, so references are now consistent.

2. **Pre-existing design-index defect (not fixed, deliberately).** Queue A's `tier_floor_exact_inclusive_on_depart` asserts `served_after_loop_id == l1_id` on a `SINGLE`-lane store, which the PRD contradicts (`served_after_loop_id` is a merge-lane re-sequencing field). The instance is still translated, but that one assertion is omitted rather than encoding a claim the PRD does not support.

## Step 6: Generate implementation — 2026-09-02T09:39:02.000Z

Implementation complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2398_drive_thru_speed_service_timer/workspace/implementation/`:

**Entry / infra:** `app.py` (blueprint registration under `/drive-thru`, `ApiError`/`HTTPException` handlers emitting the error envelope, `0.0.0.0:$PORT`), `start.sh` (executable, guarded `import flask` check then `exec python3 app.py`), `requirements.txt`.

**Core:** `db.py` (in-memory `Store` with 12 dicts + logical clock fixed at `2026-08-01T00:00:00Z`, row/rounding helpers; starts empty on every boot — no seeding anywhere), `errors.py` (57-code → HTTP map), `response.py` (envelope, `req_` id, pagination), `validation.py` (schema primitives, whole-second ISO-8601 regex), `middleware.py` (auth, 11 path lookups, Operator/ShiftLeader scope, posture gates), `constants.py`, `serialize.py`.

**Services:** `services/rollup.py` (pinned 9-step store recompute, band lookup, `active_override`, OOT staffing model), `loops.py` (relief combination, per-segment pinned rounding, segment durations/breach flags, adjusted total), `merge.py` (award selection with bias ranking + `CAR_SEQUENCE_TIE_BREAK`), `reports.py` (PROVISIONAL/FINAL input sets, attainment chain, coaching pool points), `coaching.py` (segment gap, saturating priority score, tier), `cascade.py` (slot release/forfeit, PF clear/cancel, auto remake PF).

**Routes (13 blueprints):** `clock, restaurants, tier_policies, dayparts, staff, deployments, timer_loops, merge_slots, pull_forwards, incidents, reports, coaching, overrides` + `helpers.py`.

## Endpoint count
Exactly **64** routes registered (enumerated from the Flask URL map), matching the PRD §4 table.

## Boot + behaviour verification
Launched `PORT=18398 ./start.sh`, hit endpoints over HTTP, then stopped it. Two smoke scripts passed with zero mismatches, covering: band table → store registration → daypart draft/activate → roster → deployment plan/activate → dual-lane loop lifecycle (greet, order-complete, merge-award, commit, window-arrive, depart) with the five-hop departure cascade; SINGLE-lane `ORDERED → AT_WINDOW`; abandon from `MERGED` forfeiting the committed slot and restoring capacity; pull-forward park/reissue/clear with escalation; incident log → remake → close and the accuracy cascade (2 open remakes → `ACCURACY_HOLD` → merge-award 409); override propose/approve/apply with rollup; FINAL report compute (`attainment_pct 179.17`, GOLD) → publish → coaching draft/issue/contest/reissue/acknowledge/close; freeze/unfreeze gating; and error paths returning the correct codes (400 limit/lane, 401, 403 scope, 404, 402 labor budget, 409 buffer/posture, 412 stale version, 422 clock regression / OOT cert / allergen waiver).

Notes on two spec ambiguities resolved: unfreezing a non-frozen store returns 409 `ERR_POSTURE_FROZEN` (no `ERR_INVALID_RESTAURANT_STATE` exists in the catalogue), and store-scope comparison is deferred when the target id doesn't resolve so the 404 wins (PRD §2.12 "existence precedes ownership").

## Step 7: Run tests and iterate — 2026-09-02T12:34:00.000Z

All 8 parallel rounds pass 151/151. Exiting.

**Iterations run:** 2 (each an 8-round parallel `setsid`-wrapped stability sweep).

- Iteration 1: 148/151 in all 8 rounds — the same 3 tests failed in every round (no flakiness; failures were deterministic).
- Iteration 2: 151/151 in all 8 rounds.

**Tests deleted:** none. All 3 failures traced to test bugs (STEP 2 test-vs-PRD consistency), not PRD silence and not implementation defects. No implementation change was needed.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_12_corner_calculations.py` — `TestOotRequirementCap::test_the_accuracy_bump_cannot_push_the_requirement_past_four`: the pre-condition assertion demanded `required_oot_count=4` immediately after store registration. PRD §3.1 states verbatim: *"Registration initialises the store's derived state **without running the full recompute chain**… `cars_closed_trailing`, `required_oot_count`, `deployed_oot_count`, `open_remake_count` and `remake_cost_accrued_cents` all start at 0."* Profile creation/activation and roster additions are not rollup triggers per §2.7, so the value must still be 0. Changed the expectation to `required_oot_count=0`. The test's actual subject — the cap (band min 4 + accuracy bump 1 → clamped to 4, posture `SURGE`) — is untouched and still asserted.

2. `test_suite/test_12_corner_calculations.py` — `TestReportOpenRemakeScope::test_the_excluded_car_still_costs_the_window_its_coaching_points`: called `a.assert_pinned_targets(clean, total=235)` omitting the helper's four required positional segment targets → `TypeError` before any API assertion ran. Supplied the PRD-derived values instead of weakening the helper: `clean` → `25, 95, 40, 75` (TIER_1, relief 0.00) and `departed` → `26, 98, 41, 77` (created at 11:05 when the trailing count of 1 gives 6.0 cph → TIER_2, relief 0.03). This *strengthens* the assertion (four segments now checked, not just the sum).

3. `test_suite/test_16_corner_rbac.py` — `TestRemakeSegregation::test_the_reporter_cannot_be_credited_with_the_remake_but_a_colleague_can`: asserted on a nonexistent field `remake_cost_seconds` → `KeyError`. PRD §3.6 names the field `remake_cost_cents` ("750 for `MAJOR`"). Corrected the field name; the expected value 750 is unchanged.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none. The implementation was already PRD-faithful on all three points; in particular, not running the rollup chain at registration (`routes/restaurants.py` seeding `required_oot_count=0`) is required by PRD §3.1 and is separately asserted by `test_10_corner_entities.py::test_registration_seeds_every_derived_store_field`, so "fixing" the implementation to satisfy the old assertion would have broken that test and violated PRD.

## Step 8: Finalize PRD — 2026-09-02T12:38:00.000Z

`workspace/PRD_FINALIZED.md` is created and is a **byte-identical** copy of `PRD.md` (md5 `e04251cda2216d0c27a3eac4304fa782`). All three Step 7 items are pure test-fixture bugs; none traces to PRD silence or PRD/impl divergence, so no edits were manufactured.

Line counts: PRD.md 504 / PRD_FINALIZED.md 504 — 0 lines changed, 0.00% delta.

Changes: none.

Per-item verification (the pre-edit search was run for each candidate edit; each search concluded "no edit needed"):

**Item 1 — recompute-chain triggers / registration-time derived state**
- (a) Subject: which operations run the store rollup chain, and what registration initialises.
- (b) Paths enumerated: `services/rollup.py:95-181` (`recompute`, `recompute_all`); every `recompute(` callsite via repo-wide grep — `routes/restaurants.py:88,104,119,133`, `routes/deployments.py:124,156,187`, `routes/timer_loops.py:191,221`, `routes/merge_slots.py:43`, `routes/incidents.py:100,138,164,197`, `routes/pull_forwards.py:63`, `routes/overrides.py:146`, `routes/clock.py:25`; plus the non-triggering paths `routes/restaurants.py:21-64` (registration), `routes/reports.py:68` and `routes/overrides.py:77` (`touch(restaurant)` only — version bump without the chain), and `routes/staff.py`/`routes/dayparts.py` (no store mutation at all).
- Finding: `create_restaurant` writes `required_oot_count: 0`, `cars_closed_trailing: 0`, `deployed_oot_count: 0`, `open_remake_count: 0`, `remake_cost_accrued_cents: 0`, `volume_tier = lookup_band(0.0)` and never calls `recompute` — exactly PRD §3.1. The set of `recompute` callsites matches PRD §2.7's trigger list one-for-one (profile create/activate, roster add, report create, override propose, pull-forward reissue/park are all absent from both). Test bug only.
- (c) No wording change.

**Item 2 — per-segment target pinning and tier/relief selection**
- (a) Subject: `combined_relief` + `pin_targets` (which band supplies tier relief, and the round-then-sum order).
- (b) Paths enumerated: `services/loops.py:18-48` (`combined_relief`, `pin_targets`), its only callsite `routes/timer_loops.py:68`; `services/rollup.py:23-39` (`lookup_band`, `policy_for_tier`), `:43-53` (`active_override` ranking), `:70-83` (`car_rates`, `preflight_tier`); the parallel band-lookup users `routes/restaurants.py:38` (registration at 0.0), `services/reports.py` window-tier path, `services/merge.py` bias path; and `services/rollup.py:155-158` where `cars_per_hour_effective` and `volume_tier` are written together.
- Finding: impl rounds each relieved segment individually then sums (PRD §3.3 verbatim), override relief uses `target_relief_pct_override` verbatim else `delta × 0.5` floored 0.00/capped 0.20, combined capped 0.30 — all as written. The one nominal difference is that `combined_relief` re-derives the band from the stored `cars_per_hour_effective` rather than from the stored `volume_tier`; since `recompute` (and registration) always writes those two fields from the same lookup, and bands are per-tier unique and never mutated or deleted, the two readings are the same band. Not a behavioral divergence, and PRD's existing wording already yields it. Test bug only (the fixture had omitted required positional args).
- (c) No wording change — deliberately left PRD §3.3's "band matching the store's current `volume_tier`" untouched rather than rewriting it to "matching `cars_per_hour_effective`", which would have added a claim not distinguishable from the current text and risked contradicting the registration path.

**Item 3 — remake cost field name and units**
- (a) Subject: the incident's cost field name/value and the store's accrued ledger.
- (b) Paths enumerated: `constants.py:66` (`REMAKE_COST_CENTS_BY_SEVERITY = {MINOR:350, MAJOR:750, CRITICAL:1200}`), `routes/incidents.py:88` (derivation at log time), `serialize.py:190` (incident payload key `remake_cost_cents`), `serialize.py:44` + `services/rollup.py:129-130,165` (store `remake_cost_accrued_cents` summing `ACCRUED`/`CHARGED`), `routes/restaurants.py:58` (initial 0). No `remake_cost_seconds` exists anywhere in `implementation/`.
- Finding: PRD §3.6 already names `remake_cost_cents` with 750 for `MAJOR`. Test bug only.
- (c) No wording change.

## Step 9: Complete PRD — 2026-09-02T12:53:00.000Z

**File:** `workspace/PRD_COMPLETED.md`

**Line counts / char-delta**
- `PRD_FINALIZED.md` (source): 504 lines, 104241 chars
- `PRD_COMPLETED.md`: 504 lines, 111307 chars
- Delta: **0 lines, +7066 chars**, 28 diff hunks, all pure line replacements (no new sections, no new paragraphs)

**Counts**
- ambiguity-pins: **21**
- mismatch-revisions: **7**

**Changes**
- §1.3 Logical clock — insert — ambiguity — pinned that `meta.generated_at` is always the logical clock, so fractional seconds are always `.000`, and that the advance sets the clock before recomputing every store in registration order — `implementation/routes/clock.py:24`
- §2.1 Roles — revise — mismatch — narrowed the `ShiftLeader` staff-foreign-key check to coaching acknowledge/contest only; all other `ShiftLeader` routes are store-scoped alone — `implementation/middleware.py:118`
- §2.1 Roles — revise — mismatch — `Operator` ownership is not enforced when the target store id is unresolvable, so 404/400 precedes 403 for body-supplied store ids — `implementation/middleware.py:104`
- §2.2 Request envelope — insert — ambiguity — pinned `request_id` shape (`req_` + 20 uppercase alphanumerics) and that an empty auth header counts as absent — `implementation/response.py:18`, `implementation/middleware.py:41`
- §2.3 Pagination — insert — ambiguity — pinned `has_more` as `offset + len(items) < total_count`, negative/non-integer `offset` → 400, and that unknown enum or empty-string filter values are rejected with 400 rather than matching nothing — `implementation/response.py:52`, `implementation/validation.py:171`
- §2.3 Ordering — insert — ambiguity — pinned that list ordering is by `created_at` ascending with insertion order as the stable tie-break — `implementation/db.py:64`
- §2.4 Timestamps — insert — ambiguity — pinned that whole-second ISO-8601 input accepts `Z`, `+00:00` and `+0000` — `implementation/validation.py:22`
- §2.5 Versioning — insert — ambiguity — pinned that `updated_at`/`version` bump only on an actual field change, and that recompute bumps store version only when posture changes — `implementation/db.py:80`, `implementation/services/rollup.py:210`
- §2.6 Arithmetic — insert — ambiguity — pinned Decimal `ROUND_HALF_UP` as the single rounding mode for every quantity — `implementation/db.py:96`
- §2.7 Rollup chain — insert — ambiguity — pinned band selection as the first containing band in `created_at` order — `implementation/services/rollup.py:38`
- §2.8 Tier bands — revise — mismatch — added `POST /drive-thru/restaurants` to the band-coverage applies-to list: registration requires a band containing 0.0 — `implementation/routes/restaurants.py:57`
- §2.8 Tier bands — insert — ambiguity — pinned that a non-null `ceiling` must exceed `floor` (400) and that this check precedes tier uniqueness — `implementation/routes/tier_policies.py:31`
- §2.9 Precision — revise — mismatch — `segment_gap_seconds` is stored exactly/unrounded — `implementation/services/coaching.py:74`
- §2.10 Posture gate — insert — ambiguity — pinned that unfreezing an already-unfrozen store returns `ERR_POSTURE_FROZEN` — `implementation/routes/restaurants.py:141`
- §2.11 step 4 — revise — mismatch — reordered so entity existence resolves before `Operator` ownership for body-supplied store ids — `implementation/middleware.py:104`
- §2.11 step 25 — revise — mismatch — band-coverage step now also covers store registration — `implementation/routes/restaurants.py:57`
- §3.1 Store registration — insert — ambiguity — pinned that duplicate `store_number` is detected before band coverage is checked — `implementation/routes/restaurants.py:50`
- §3.2 Deployments — insert — ambiguity — pinned that the daypart profile is validated for existence and same-store only, with no profile-state or interval-containment requirement — `implementation/routes/deployments.py:61`
- §3.2 Staff — insert — ambiguity — pinned that `window_certified` is recorded but never gates anything, and that no operation moves a member to `INACTIVE` — `implementation/routes/staff.py:44`
- §3.3 Timer loops — insert — ambiguity — pinned that a lane/lane-config mismatch is a 400 checked after the same-store check and before the frozen gate — `implementation/routes/timer_loops.py:73`
- §3.3 Abandon — revise — mismatch — live pull-forwards are cancelled from every abandon state including `OPEN`/`GREETED`, and `RESERVED` slots are forfeited from `MERGED`/`AT_WINDOW` too — `implementation/routes/timer_loops.py:236`
- §3.4 Merge commit — revise — mismatch — commit takes no request body and returns the merge slot rather than the loop — `implementation/routes/merge_slots.py:118`
- §3.5 Pull-forwards — insert — ambiguity — pinned that issuance places no `timing_state` precondition on the loop — `implementation/routes/pull_forwards.py:44`
- §3.7 Reports — insert — ambiguity — pinned that `open_remake_incident_count` is store-scoped and that the input loop set is retained internally but not serialized — `implementation/services/reports.py:96`
- §3.7 Report scoring step 6 — insert — ambiguity — pinned the `avg_metric_seconds == 0` guard: `attainment_pct` and `attainment_band` stay null and the band award contributes 0 — `implementation/services/reports.py:118`
- §3.9 Segment gap — revise — mismatch — both means share a denominator restricted to loops carrying the measured duration; gap is 0 when none do, and 0 for `ACCURACY` when `cars_served` is 0 — `implementation/services/coaching.py:44`
- §3.9 Priority score — insert — ambiguity — pinned that a null `attainment_band` weighs 0.0 in the band component — `implementation/services/coaching.py:88`
- §4 Route table — insert — ambiguity — pinned the table as exhaustive: undefined path → `ERR_RESTAURANT_NOT_FOUND` (404), wrong method → `ERR_INVALID_REQUEST` as HTTP **400** (not 405), trailing slashes equivalent, non-object/unparseable body → 400, absent body treated as `{}` — `implementation/app.py:34`, `implementation/validation.py:41`

Pipeline complete: Steps 7, 8, 9 ran in this resume session; Steps 1-6 were satisfied on disk and not re-run.

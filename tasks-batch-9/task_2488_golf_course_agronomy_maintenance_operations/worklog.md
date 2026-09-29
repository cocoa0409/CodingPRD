# Worklog — task_2488_golf_course_agronomy_maintenance_operations

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2488_golf_course_agronomy_maintenance_operations` and its `workspace/` subdirectory. Index 2488 was pre-assigned by the caller; no scan/allocation of `./tasks/` was performed.

## Step 2: Generate scaffold — 2026-09-03T02:20:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Files produced
- `/home/ubuntu/github/CodingPRD/tasks/task_2488_golf_course_agronomy_maintenance_operations/SCAFFOLD.yaml` (§1.0–§1.7, 3162 lines) — 14 entities, 8 state machines, 10 calculation rules, 51 validations across 9 priority bands, 61 endpoints, 51-error catalog, 5 roles, 4 §1.2.1 concurrency rules. Profile: `temporal_windowing` / `compliance_audit`, layers `optimistic_concurrency` + `cascading_side_effects` + `dual_variant_calculation` + `rate_threshold_triggers`, `entity_topology: flat`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, `consistency_model: immediate`, `difficulty_level: expert_plus`.
- `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, 2140 lines) — 29 instances over all nine §0.5 rules (2/3/3/3/4/4/4/3/3), well above the ≥18 / ≥2-per-rule minimum.
- `.../SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, 3275 lines) — all nine §1.9 sections, 82 instances: 54 with full `test_recipe`s and 28 `excluded_because` stubs, every stub citing a real §1.8 instance (`<rule_id> / <instance_name>`), names unique across both design files.

## Work completed this session
Wrote the final three §1.9 sections: `rbac` (peer-boundary refusals that prove authz precedes existence, 401 vs 403 separation, both segregation-of-duties paths — plan approve by the submitter and application self-verify — plus one positive exclusive operation per role), `cross_cutting_complexity_layers` (one OCC instance per §1.2.1 rule on its declared `write_endpoint`/`occ_field`, version-increment semantics, and the cumulative 250 h service threshold at 249/250 with a reset that re-fires), and `consistency_model` (immediate visibility of all four side effects of one schedule call). All 51 declared error ids are now triggered somewhere in §1.8/§1.9, including `ERR_UNAUTHENTICATED`, `ERR_UNAUTHORIZED`, `ERR_SEGREGATION_OF_DUTIES` and the three `ERR_STALE_*_VERSION` codes.

Five lint violations found and fixed: four `expected_*_version` literals (replaced with captured `${...}` tokens, one negative RBAC call re-pointed at a real DRAFT plan, one re-pointed at `POST /applications/{id}/verify` so it exercises the missing-`X-User-ID` path without an OCC field) and one unresolvable capture (`$.data.maintenance_window_id` — `PlanTask` has no such field; now captures `commitment_lb`). Also fixed three `difficulty_instance` citations that used `dual_variant_calculation` instead of the canonical `rule_id: dual_variant_calc`, and one setup-prose/payload area mismatch (5500 → 4000 sq ft) that would have contradicted the hand-computed 1.583 lb/1000 assertion.

The hard constraint was honored throughout: no sibling task directory was listed, globbed, grepped, or read.

## Final verdict block (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2488_golf_course_agronomy_maintenance_operations/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2488_golf_course_agronomy_maintenance_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2488_golf_course_agronomy_maintenance_operations/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     14
  §1.8 instances scanned:     29
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  645

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

One incidental note: the task directory also contains a pre-existing `worklog.md` and empty `workspace/` (both timestamped before any of my writes); I left them untouched.

## Step 3: Copy shared files — 2026-09-03T02:20:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T02:39:00.000Z

The PRD is complete and verified. `/home/ubuntu/github/CodingPRD/tasks/task_2488_golf_course_agronomy_maintenance_operations/workspace/PRD.md` — 525 lines, 111 KB, terminating cleanly at the last row of the §5 error table.

**Structure:** §1 Introduction; §2 with 12 subsections (RBAC, verbatim response structure, pagination, identity/versioning, logical clock, rounding discipline, version pinning, the full 51-item request-evaluation order with `applies_to` scopes, flat-collection containment, course postures, interval geometry, cascade discipline); §3 with 9 workflow subsections (course/water allocation, turf areas, agronomic plan, licensing+applications, irrigation, crew windows, play events/frost/certification, equipment fleet, weather); §4 with the 61-row 4-column endpoint table; §5 with the 51-row 2-column error table.

**Verification (machine-checked against SCAFFOLD.yaml):**

```
Field coverage check:
- entities[].fields: 135 required, 135 present, 0 missing
- endpoints[].input identifiers (request bodies, query filters, pinned versions): 93 distinct required, 93 present, 0 missing
- endpoints[].path_params: modelled as {id} throughout, matching the scaffold verbatim
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 51 checked, 51 expressed in prose (§2.8 carries the full ordered list with error id, HTTP status and complete applies_to endpoint enumeration; 0 applies_to entries missing), 0 missing
- concurrency_rules[] OCC rejections: 4 checked, 4 expressed (write_endpoint path + expected_<parent>_version + error_id + 412 all named in §2.7), 0 missing
- state_machines[].transitions: 42 checked, 42 fully expressed with explicit `FROM → TO` arrow notation, 0 missing
- calculations[]: 10 checked, 10 fully expressed (every numeric constant and worked-example literal in the scaffold appears in the prose; pinned round-then-aggregate orders and both dual-variant pairs stated), 0 missing
- validations[] conditions: 51 checked, 51 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 34 endpoints with side effects checked, 34 expressed, 0 missing
- entities[].fields[] structured content: 135 checked, 135 reconstructible from prose (enums, ranges, defaults, initial values, nullability), 0 missing
- sibling-branch symmetry: 10 groups checked, 10 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 983
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also confirmed: §2.2 is byte-identical to `section-2.2-response-structure.md`; no fuzzy quantifiers and no symbolic operators (`==`, `>=`, `+=`, `min()`, `round()`, ` AND `, ` IN `) appear outside code fences; all 14 creation endpoints are documented as 201 and the other 47 as 200, matching the scaffold's `code` values; every endpoint row's authorized roles match `roles` exactly; no audit footer or contract report was written into the file or any sibling.

Two fixes made during verification: §4 path parameters were normalized to the scaffold's `{id}` form (they had been written as descriptive names, which would have diverged from the `applies_to` paths in §2.8), and two stale §3.6 cross-references were corrected to §3.5. The scaffold's exact water-posture boundary example (6448 gal against an 8060 gal allocation is exactly 80.0 percent, therefore `RESTRICTED`) was added to §2.10.

Two scaffold gaps were handled without inventing error IDs: per-course uniqueness of `plan_year` is stated as a plain constraint, and re-certification is scoped by stating certification applies while `readiness_status` is `PENDING` or `FAILED`. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**Orchestrator anti-truncation check:** `tail -18 PRD.md` ends at the final `| ERR_WATER_ALLOCATION_EXCEEDED | 422 |` table row — a real section boundary, not mid-sentence. `grep -c '^| ERR_'` = 51 (all errors); §4 endpoint table has 63 lines (61 endpoints + header + separator). No regeneration needed.

## Step 6: Generate implementation — 2026-09-03T03:29:00.000Z

**Orchestrator note on an interruption during this step.** The Step 6 subagent was terminated early by a transient upstream API error partway through its work, immediately after it reported the intent "Now a second pass over the paths the first suite didn't exercise (deferral chain, revision limit, run conflicts, retirement cascade, ordering exceptions, tiers)." Judgement call made autonomously (no user available): rather than respawn a fresh implementation generator — which would have discarded the whole domain model and risked producing an implementation inconsistent with the already-written 3437 lines — I verified the on-disk baseline myself (all 12 modules + routes/ present, 61 route decorators matching the PRD's 61 endpoints, `PORT=18488 bash start.sh` booting cleanly in the foreground on 0.0.0.0 and answering `GET /courses` with 401 for unauthenticated access, no import errors) and then resumed the *same* agent via SendMessage with that verified baseline plus its own six-item to-do list restated. The agent continued with its context intact and completed normally. Post-exit check confirmed no scratch artifacts were left in `implementation/` (no .log/.json/smoke*/.db/.bak files); its scratch scripts were correctly written to /tmp.

Verbatim summary returned by the subagent:

Both self-test passes are green and the tree is clean. Final state:

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2488_golf_course_agronomy_maintenance_operations/workspace/implementation/`)
`app.py`, `store.py`, `util.py`, `errors.py`, `envelope.py`, `validators.py`, `serializers.py`, `calc.py`, `services.py`, `requirements.txt`, `start.sh` (executable, guarded `pip install` + `exec python3 app.py`, binds `0.0.0.0:$PORT`, default 10000), and `routes/{__init__,common,courses,plans,applications,irrigation,windows,fleet}.py` — 3430 lines, **61 route decorators** = the PRD's 61 endpoints. Storage is 14 empty dicts on `store.Store`; nothing is seeded, nothing touches disk. Two consecutive `start.sh` boots each served an empty `GET /courses` and a fresh `POST /courses` with `version: 1`.

## One implementation change this pass
`routes/windows.py` reschedule now also enforces `ERR_COURSE_CLOSED` (33) and `ERR_TURF_AREA_OUT_OF_PLAY` (34), `STORM_CLEANUP` exempt. Final reschedule order: window state (19) → REI (32) → closed (33) → out-of-play (34) → overlap (39) → play conflict (40) → deferral limit (46) → plan-still-ACTIVE → budget (51).

## What the second pass verified (scratch scripts live at `/tmp/smoke_2488.py`, `/tmp/smoke2_2488.py`; nothing was written into `implementation/`)
- **Deferral chain**: rain #1 defers a task-carrying window (count 1, event `deferred_window_count` 1, task `SCHEDULED→PLANNED`, plan ledger 4.25→0.00, area projected held at 0.85); reschedule restores task + ledger and does not decrement the count; rain #2 → count 2; reschedule → 409 `ERR_DEFERRAL_LIMIT_REACHED`; rain #3 leaves the exhausted window alone and defers only a fresh one; storm-damage then cancels the window and its task; weather log ordered `declared_at` DESC.
- **Revision limit**: return/submit twice (`return_count` 1 then 2, `submitted_by_user_id` cleared), third return → 409 `ERR_REVISION_LIMIT_REACHED`, third submission still approvable, then return → `ERR_PLAN_STATE_INVALID`.
- **Irrigation**: `ERR_PUMP_ZONE_CAPACITY`, `ERR_PUMP_FLOW_CAPACITY`, zone-before-flow ordering, back-to-back runs not conflicting (half-open, no buffer), `PATCH …/status OFFLINE` cancelling scheduled runs (volume 0) then `ERR_PUMP_OFFLINE` on create, `ERR_STALE_PUMP_VERSION` (27) beating `ERR_PUMP_OFFLINE` (43), `ERR_ZERO_ALLOTMENT`, `ERR_WATER_ALLOCATION_EXCEEDED` for WELL with the RECLAIMED exemption, prorated completion (30 of 60 min → 31.0 gal).
- **Retirement cascade**: retiring while another unit of the class stays `IN_SERVICE` leaves windows alone; retiring the last one defers the window (count 1), reverts the task and unwinds the plan ledger; `ERR_REPLACEMENT_UNIT_TYPE_MISMATCH` (37), `ERR_EQUIPMENT_STATE_INVALID` (22) winning over it, `ERR_EQUIPMENT_NOT_FOUND` covering `replacement_unit_id`, `replaced_by_unit_id` recorded.
- **Priority spot-checks**: 401 → 403 → 400 on the same bad request; 403 before 404 (`Applicator` on `GET /agronomic-plans/{id}`); missing `X-User-ID` → 401; area existence (5) before stale course version (25) before containment (36); window state (19) before stale plan (26) before containment (36) before outside-plan-window (41) before budget (51); SoD (38) after stale plan (26) on approve and after application state (21) on verify; license expired (28) → wind (29) → buffer (30) → category (35) chain.
- **Boundaries / dual variants**: cumulative service threshold (249.9 h stays `IN_SERVICE` at version 2; +0.1 h hits exactly 250.0, auto `DOWN_FOR_SERVICE`, version 4 via the one documented forced double bump); the PRD's own 80.0 % example (`RESTRICTED` at the inclusive boundary, `OPEN` one gallon of allocation later, `SUSPENDED` at 100 % cancelling scheduled runs, station status mirroring both ways); allotment uncapped 62.0 vs capped 6448.0 vs posture-scaled 37.2 (×0.60); volume full vs prorated; score 81.8 vs projected 85.7; tier T1 25.24 / T2 50.49 / T3 395.94; readiness 100.00 CERTIFIED vs 66.67 FAILED (band clamp) vs 73.33 FAILED (worked example) vs `ERR_INSUFFICIENT_READINGS` when readings fall outside the 24 h window; readings ordered `measured_at` DESC.
- Envelope, `req_`+20-char ids, 3-digit-millisecond timestamps, pagination meta and `limit`/`offset` range rejection, 405 and malformed-JSON handling, unknown role → 401.

## Ambiguities resolved (recorded here as decided)
1. **Reschedule scope conflict** — §2.8 scopes rules 33/34/51 to other endpoints, but §3.6 explicitly names closed course, out-of-play area and `ERR_NITROGEN_BUDGET_EXCEEDED` for reschedule. Resolved in favour of §3.6 prose (all three enforced), with each check placed at its §2.8 numeric priority so no ordering test can be disturbed.
2. **Plan-not-ACTIVE on reschedule** has no error id in the PRD → `ERR_PLAN_STATE_INVALID`, evaluated late (immediately before the budget check) so it cannot preempt any scoped rule.
3. **Plan `(course_id, plan_year)` uniqueness** has no dedicated code → `ERR_INVALID_REQUEST` (400). **Submit with no `PLANNED` task** → `ERR_PLAN_STATE_INVALID`.
4. **Version bumps**: `touch()` is idempotent per request; only the log-hours auto-transition bumps twice; silently derived turf ledgers bump only when a figure actually moved.
5. Two PRD branches are implemented but provably unreachable: defer→cancel at `deferral_count == 2` (reschedule refuses at 2, so no `SCHEDULED` window can carry count 2) and out-of-play on reschedule (an `OUT_OF_PLAY` area implies an active storm event, so `ERR_COURSE_CLOSED` at 33 always fires first).

## Step 5: Generate unit tests — 2026-09-03T04:33:00.000Z

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator started before `test_suite/` existed on disk — the physical isolation the skill calls for. The test generator ran ~93 minutes and produced 18 test files (test_01–test_09 = queue A, one file per §1.8 difficulty rule; test_10–test_18 = queue B, one file per §1.9 corner section) plus 9 `test_helpers/` modules. The summary below covers the agent's final working session verbatim, and its closing census covers the whole suite.

Verbatim summary returned by the subagent:

Queue B is complete; the whole suite is finished.

## What I did this session

**Wrote `test_suite/test_17_cross_cutting_complexity_layers.py`** (6 tests, one per non-stub instance; the 3 stubs were skipped):
- `occ_stale_plan_version_blocks_task_scheduling` — one plan version spent on the aeration binding, the fertility binding refused 412 `ERR_STALE_PLAN_VERSION` with none of the four mutations written, then the refetched version 4 accepted and 4.68 posted.
- `occ_stale_plan_version_blocks_plan_approval` — the first-submission token refused 412 (not `ERR_PLAN_STATE_INVALID`), the second-submission token accepted to `ACTIVE` v5.
- `occ_stale_course_version_blocks_weather_declaration` — allocation revision moves the course to v2, so the frost pinned at v1 is 412 `ERR_STALE_COURSE_VERSION`; retry at v2 stamps `declared_at` from the clock and drives the course to `FROST_DELAY` / 30 min / v3.
- `occ_stale_pump_version_blocks_run_creation` — offline/online cycle takes the station to v3, so the run pinned at v1 is 412 `ERR_STALE_PUMP_VERSION` (not `ERR_PUMP_OFFLINE`); retry books 341.0 gal at 5.68 gpm and leaves the station at v3.
- `every_write_increments_the_entity_version` — 1 → 2 → 3 across two revisions with the posture pinned `OPEN`, and the following read leaves the version at 3.
- `cumulative_service_threshold_fires_at_exactly_the_interval_and_resets` — 250 h downs unit A (21.9 / 25.9 / flag false), 249 h leaves its twin in service (21.8 / 25.8), the service conserves the 250 h meter while collapsing the score to 1.9, the next 250 h re-fires at 500 h (23.8 / 27.7), and a service on the `IN_SERVICE` twin is 409 `ERR_EQUIPMENT_STATE_INVALID`.

**Wrote `test_suite/test_18_consistency_model.py`** (1 test; the 1 stub skipped) — `immediate_visibility_of_every_recomputed_field_in_the_same_request`: the schedule response itself reads `SCHEDULED` / v2 / 4.68, and the first read of the plan (4.68, v4), the green (0.850 projected, 0.000 applied, v3) and the window (`plan_task_id`, v2, 6.00 crew hours) are already final, with `assert_untouched` on a second read of all four.

**One correction I caught while writing test_17**: the design index does not assert the projected score after the service, and the value there is 5.9, not the 25.9 the pre-service row carried, so I asserted only `replacement_score == 1.9` (what the design actually pins) rather than forcing a three-value helper call.

## Final state (verified)

- `/tmp/check2488.py` → `issues: 0`; `pyflakes` clean on every `test_suite/*.py`. (The only pyflakes noise left is `test_helpers/__init__.py` and `factories.py`, whose re-exports carry `# noqa: F401` — pre-existing and deliberate.)
- `python3 -m pytest test_suite --collect-only -q` → **118 tests collected, 0 errors**.
- Design-index census: **83 live instances, 83 covered, 0 orphan tags, 0 stub tags used, every queue-A instance carries ≥2 tests**. 28 stubs correctly left untranslated.
- Files: `test_suite/test_17_cross_cutting_complexity_layers.py`, `test_suite/test_18_consistency_model.py` (new); `test_suite/test_09_compensating_invariants.py` (the clock fix from earlier this session, at `/home/ubuntu/github/CodingPRD/tasks/task_2488_golf_course_agronomy_maintenance_operations/`).

Nothing under `workspace/implementation/` was read or written at any point. The only remaining step is a real pytest run once the implementation agent (`ad2a49d38a8da184b`) finishes.

## Step 7: Run tests and iterate — 2026-09-03T04:59:00.000Z

Verbatim summary returned by the subagent:

Clean 8-round sweep achieved. Final state verified on disk.

## Summary

**Iterations run: 2**

Iteration 1 found 3 failures, identical in all 8 rounds (fully deterministic — no flakiness, no load-induced timeouts, no `Terminated` server logs). Iteration 2 was green: 8/8 rounds at 118/118.

### Tests deleted
None. One assertion was stripped under STEP 1c (partial-coverage split), no whole test removed.

### Fixes applied to `test_suite/`
- `/home/ubuntu/github/CodingPRD/tasks/task_2488_golf_course_agronomy_maintenance_operations/test_suite/test_15_errors.py` — `test_a_task_already_bound_to_a_window_cannot_be_bound_to_another`: removed the `maintenance_window_id=w_first["id"]` kwarg from `assert_plan_task`. **COMPUTED-FIELD SILENCE**: PRD §3.3 names `maintenance_window_id` only as the *request-body input* to `POST /plan-tasks/{id}/schedule`, never as a plan-task response attribute — and it explicitly puts the back-reference on the other side ("The window records the task's identifier in its own `plan_task_id`"), with §2.9 exposing the reverse lookup as `GET /maintenance-windows` filtered by `plan_task_id`. A faithful reader correctly omits the field from the plan-task serializer. The remaining assertions (the `ERR_TASK_STATE_INVALID` 409, task still `SCHEDULED`, `w_first.plan_task_id == task1.id`, `w_second` still free, plan version unmoved) are all verbatim-covered and were kept. Scaffold rule that drove it: `Corner/errors/scheduling_a_task_that_is_already_scheduled_is_rejected`.

### Fixes applied to `test_helpers/`
None — the fixtures and factories traced faithfully to PRD in every case.

### Fixes applied to `implementation/`
- `/home/ubuntu/github/CodingPRD/tasks/task_2488_golf_course_agronomy_maintenance_operations/workspace/implementation/serializers.py`, `turf_area_out()` — both turf-area nitrogen ledgers are now derived via `calc.turf_nitrogen_load()` at serialization time instead of being projected from the persisted snapshot. One fix resolved both remaining failures:
  - `test_12 :: test_the_applied_ledger_drops_last_years_spray_when_the_clock_rolls_over` (expected 0.0, got 1.583) — PRD §3.3 scopes the applied figure to records "whose `applied_at` falls in the logical clock's calendar year" and §2.5 lists "the calendar year used by the nitrogen ledgers" among the clock-driven decisions, so advancing the clock must change the reported value with **no intervening write**. `calc.turf_nitrogen_applied` filtered correctly all along; the stale persisted snapshot was what leaked.
  - `test_04 :: test_safety_violation_void_reopens_the_closed_plan_and_reschedules_its_task` (expected 2.113, got 2.963 — exactly the 0.850 task rate over) — the projected figure retained a fertility task's rate after the task reached `COMPLETED`, contradicting PRD §3.3's "Completed fertility tasks are deliberately not added again". PRD's cascade list for window-completion omits the area recompute as a *trigger*, but the definitional invariant is authoritative and §2.4 explicitly contemplates server-initiated ledger recomputation.

  This mirrors the pattern already established in the same file by `applicator_out`, which derives `license_status` from the clock at read time (the mechanism behind the already-passing `test_a_licence_lapses_with_the_clock_and_not_with_a_write`). Deriving in the projection rather than mutating the record keeps reads from bumping `version`, so no version-increment assertion anywhere in the suite was disturbed. No endpoint, field, or capability was added, and no PRD-required check was weakened; storage remains in-memory dicts with no startup seeding.

**Orchestrator independent verification of the Step 7 claim** (done because a Step 7 subagent can report a clean sweep without leaving the artifacts behind): all 8 `workspace/implementation/results.{1..8}.json` exist and each parses to `passed=118 total=118` with an empty failing-test list. `grep -rn "pytest.mark.skip\|pytest.mark.xfail" test_suite/ test_helpers/` → no matches, so nothing was dodged rather than fixed. `grep -rh "^def test_" test_suite/*.py | wc -l` → 118, matching the pre-Step-7 count, confirming the "0 tests deleted" claim. Result mtimes (04:41) postdate both fixes (serializers.py 04:37:08, test_15_errors.py 04:37:20), so the green sweep genuinely ran against the fixed tree rather than being a stale artifact of the first sweep. I had also independently observed iteration 1's deterministic 115/118 across all 8 rounds before the agent's fixes landed.

## Step 8: Finalize PRD — 2026-09-03T05:04:00.000Z

Step 8 was NOT skipped: Step 7 ran 2 iterations with 1 `test_suite/` fix and 1 `implementation/` fix, so the skip condition (zero iterations beyond baseline) did not hold. The Step 7 worklog entry above was inlined verbatim as `<step_7_diff>`.

Verbatim summary returned by the subagent:

Done. `PRD_FINALIZED.md` written.

## Size
- PRD.md: 524 lines / 111,423 chars. PRD_FINALIZED.md: 524 lines / 112,524 chars.
- Line delta: 0 (+0.0%) — all three edits are inline inside existing paragraph lines. Char delta: +1,101 (+0.99%); word delta +186 (+1.17%).

## Changes (3)
- **§1 (Introduction, ledger-fields paragraph)** — insert — added one clause noting the two turf-area nitrogen figures are, as §3.3 pins, re-derived from the records existing at the moment of the read, so the intro's "keeps ledger fields rather than recomputing on demand" no longer contradicts the read-time derivation. — `implementation/serializers.py:121-135`
- **§3.3 (turf-area nitrogen paragraph)** — insert — appended two sentences pinning that both reported figures are re-derived at read time (clock year roll-over and fertility-task status transitions move the reported value regardless of whether a write touched the area), and that a read mutates nothing / increments no `version`, leaving all prescribed write-and-cascade version increments exactly as stated. — `implementation/serializers.py:131-135`, `implementation/calc.py:76-109`
- **§3.3 (four mutations of a successful task binding)** — insert — appended a clause that the binding is recorded on the window side only: `maintenance_window_id` is a request input, not a plan-task attribute, and the window is found via `GET /maintenance-windows?plan_task_id=`. — `implementation/serializers.py:29-33`, `implementation/routes/plans.py:223,249-259`

## Per-edit pre-edit search log

**Edit 1 — §1 ledger-fields clause**
- (a) Subject: whether the turf-area nitrogen figures are snapshot-served or re-derived, at the document's global framing level.
- (b) Enumerated/read: `serializers.py` (`turf_area_out`, `TURF_AREA_FIELDS`, `applicator_out` as the pre-existing derive-at-read precedent); `calc.py:76-113` (`turf_nitrogen_applied`, `turf_nitrogen_planned`, `turf_nitrogen_load`); grep of `nitrogen_applied_lb_per_1000_ytd|nitrogen_projected_lb_per_1000|turf_nitrogen_*|recompute_turf` across the whole impl → `services.py:71-90` (`recompute_turf_nitrogen`, `sync_turf_ledgers`), `routes/courses.py:190-191` (area creation seeds 0.000), `routes/plans.py:164-165,188,253`, `routes/applications.py:174-175,221,288,329`, `services.py:489`. Also checked the other three ledgers named in the same sentence (plan `committed_nitrogen_lb` via `calc.plan_committed_nitrogen_lb` + `services.recompute_plan_ledger`; station `withdrawn_today_gal`; course `water_used_gal`) to confirm they *are* snapshot-persisted and must not be swept into the new clause.
- (c) Adjustment: scoped the clause strictly to "the two turf-area nitrogen figures" and left the original sentence intact, so the plan/station/course ledgers keep their persisted-ledger description; used "the values a read reports" rather than "are not persisted", since the impl does still store a snapshot on the row.

**Edit 2 — §3.3 read-time derivation sentences**
- (a) Subject: exactly what determines the two reported turf-area nitrogen values, and whether reads/writes bump `version`.
- (b) Enumerated/read: `serializers.py:121-135`; `calc.py:76-109` (clock-year filter on `applied_at`; `PLANNED`/`SCHEDULED` filter on fertility tasks; `RECORDED`/`VERIFIED` filter on applications); every write path that touches an area's ledgers — `services.recompute_turf_nitrogen`, `services.sync_turf_ledgers` (version bump only when a figure moved), `revert_task_to_planned`, `advance_task_to_scheduled`, `complete_task` (deliberately no area recompute), `cancel_task`, `revert_task_from_completed` (no area recompute), `routes/plans.py:188` (task creation → `sync_turf_ledgers`), `routes/plans.py:249-259` (schedule → recompute + unconditional `touch`), `routes/applications.py:221-223` (create), `:288` (verify → `sync_turf_ledgers`), `services.py:489-490` (void), `routes/courses.py:190-191` (creation seeds 0.000, which the derivation reproduces for a fresh area). Verified no GET handler calls `touch`/`sync_`/`recompute`.
- (c) Adjustments: (i) replaced an initial "even though nothing has written to the area in between" with "whether or not any write has touched the area in between", because most fertility-task transitions *do* write and `touch` the area — only window-completion does not; (ii) deliberately made no claim about *which* writes bump the area's `version` (the impl's `sync_turf_ledgers` bumps only on a changed figure, while `schedule`/`revert`/`cancel` bump unconditionally), instead stating only that the increments prescribed elsewhere are neither added to nor removed by the re-derivation; (iii) left the existing "persisted as …" phrasing verbatim, since the impl does keep the row values.

**Edit 3 — §3.3 window-side back-reference**
- (a) Subject: whether a plan task exposes a reference to the window it is bound to.
- (b) Enumerated/read: `serializers.py:29-33` (`PLAN_TASK_FIELDS`, no window key) and `plan_task_out`; `routes/plans.py:140-188` (task creation record keys), `:223` (`maintenance_window_id` read as a body field only), `:249-259` (schedule sets only `window["plan_task_id"]`, returns `plan_task_out`); repo-wide grep for `maintenance_window_id` → single hit, the request field; `services.cancel_window` (clears `window["plan_task_id"]`) and `WINDOW_FIELDS`/`window_out` to confirm the back-reference lives only on the window and that my sentence makes no claim about it never being cleared; `routes/windows.py` list filter on `plan_task_id` to confirm the reverse lookup §2.9 promises actually exists.
- (c) Adjustment: phrased it as "`maintenance_window_id` is a request input and not an attribute of a plan task" rather than a broader "a plan task carries no window reference", keeping the statement about the named field only and pointing at the reverse lookup that the impl does support.

**Orchestrator verification:** `PRD_FINALIZED.md` is 524 lines (same as `PRD.md`, consistent with the claim that all three edits are inline) and its tail ends at the final `| ERR_WATER_ALLOCATION_EXCEEDED | 422 |` error-table row — a real section boundary, not truncated.

## Step 9: Complete PRD — 2026-09-03T05:19:00.000Z

Verbatim summary returned by the subagent:

Done. `PRD_COMPLETED.md` is complete and verified.

## Verification
- `PRD_FINALIZED.md`: 524 lines, 112 524 chars → `PRD_COMPLETED.md`: 524 lines, 124 591 chars (**+12 067 chars**, line count unchanged — every change is an in-paragraph insert or revision; no new sections, no new paragraphs)
- §4 endpoint rows: **61** ✅
- §5 error rows: **51** ✅
- File ends at `| ERR_WATER_ALLOCATION_EXCEEDED | 422 |` — the real §5 table boundary ✅

## Counts
**47 changes total: 27 ambiguity-pins, 20 mismatch-revisions.**

## Changes
- §2.1 — revise — mismatch — `X-User-ID` required on exactly three endpoints (submit/approve/verify); missing or empty → 401, tested before the 403 authorisation check — validators.py:26-44
- §2.3 — insert — ambiguity — default ordering ties broken by insertion order; the two descending endpoints tie-break by later `created_at` then later insertion — routes/common.py:7-18, routes/courses.py:148,233
- §2.5 — insert — ambiguity — clock-set accepts any instant and answers 200 with `data.current_utc` at 3 fractional digits — routes/courses.py:277-284
- §2.6 — insert — ambiguity — `billable_gal` reported at 1 dp; equipment hour fields at 1 dp — calc.py:187, fleet.py:47,111,133
- §2.8 rule 3 — revise — mismatch — rule 3 scope is *every* endpoint incl. path-only reads; malformed path UUID → 400; absent/empty/null body = empty object; extra keys ignored — validators.py:54-85
- §2.8 rule 17 — revise — mismatch — add reschedule, evaluated after rule 46 and before rule 51, skipped without a carried task — routes/windows.py:215-224
- §2.8 rule 33 — revise — mismatch — add reschedule (STORM_CLEANUP exempt); booking not guarded — routes/windows.py:196-198
- §2.8 rule 34 — revise — mismatch — add start and reschedule (STORM_CLEANUP exempt); booking not guarded — routes/windows.py:141,199-200
- §2.9 — revise — mismatch — sub-resource reads resolve the parent before child rows, but the transport band (bad UUID/limit/offset/filter) still wins — routes/courses.py:132-150,224-235
- §2.11 — insert — ambiguity — reschedule excludes the window from its own closed-interval overlap test — services.py:228-238
- §2.11 — insert — ambiguity — a hole beyond `holes_in_play` is unoccupied for both play geometries — services.py:241-254
- §3.1 — insert — ambiguity — `billable_gal` reported at 1 dp while the exact difference feeds the surcharge step — calc.py:173-187
- §3.3 — insert — ambiguity — duplicate course+`plan_year` → `ERR_INVALID_REQUEST` 400, after the course existence check — routes/plans.py:39-41
- §3.3 — insert — ambiguity — `return_note` ≤2000 chars, may be empty, validated but neither persisted nor echoed — routes/plans.py:104
- §3.3 — insert — ambiguity — plan-task creation bumps the area only when a nitrogen figure moved; ceiling test only for FERTILITY — routes/plans.py:162-188, services.py:77-89
- §3.3 — revise — mismatch — schedule's conditions re-listed in the real order (window exists → plan ACTIVE → task PLANNED → window state → version → mismatch → containment → budget) — routes/plans.py:226-244
- §3.3 — revise — mismatch — plan reopen re-evaluated after every route returning a task to PLANNED/SCHEDULED, not only a void — services.py:127-151
- §3.4 — insert — ambiguity — `license_number` ≤120 chars, uniqueness compared case-sensitively — routes/applications.py:38-44
- §3.4 — insert — ambiguity — `epa_reg_no` ≤120 chars and not required to be unique — routes/applications.py:91
- §3.4 — revise — mismatch — the cited task's `SCHEDULED` test is the gauntlet's first substantive rung, ahead of every licence/wind/buffer/nitrogen/posture failure — routes/applications.py:154-155
- §3.4 — revise — mismatch — "three further conditions" reduced to two, task status having been settled earlier — routes/applications.py:189-199
- §3.4 — insert — ambiguity — verification mutates nothing but the record; the treated area is not versioned — routes/applications.py:286-288, services.py:77-89
- §3.4 — insert — ambiguity — `suspended_at` re-stamped and version re-bumped even on an already-suspended applicator — services.py:492-496
- §3.5 — insert — ambiguity — station-status takes all three enum values, stores verbatim, no legality test, no re-mirror, bumps version even when unchanged — routes/irrigation.py:82-99
- §3.5 — revise — mismatch — posture consequences keyed on destination posture; no-op when unchanged; once-per-request version rule — services.py:310-329
- §3.5 — revise — mismatch — complete-run order is out-of-play (34) before pump-offline (43); `actual_minutes` is a whole number ≥0, unbounded above, may exceed the planned duration — routes/irrigation.py:212-222
- §3.5 — insert — ambiguity — `reversal_note` ≤2000 chars, may be empty, not persisted — routes/irrigation.py:240
- §3.6 — insert — ambiguity — booking accepts and existence-checks an optional `plan_task_id` then discards it; the window is always created with null — routes/windows.py:54,65-66,83
- §3.6 — revise — mismatch — booking check order is REI → containment → overlap → play conflict, and booking runs no posture check — routes/windows.py:68-77
- §3.6 — revise — mismatch — start order is REI → CLOSED → OUT_OF_PLAY; the AERATION area write is skipped, and the area untouched, when already UNDER_RENOVATION — routes/windows.py:131-149
- §3.6 — insert — ambiguity — `deferred_window_count` counts only weather-triggered successful deferrals; only SCHEDULED windows are candidates — services.py:194-211
- §3.6 — revise — mismatch — reschedule order (REI → CLOSED → OUT_OF_PLAY → overlap-excluding-self → play conflict → deferral cap → plan ACTIVE → budget) and the PLANNED-only commitment restoration — routes/windows.py:188-234
- §3.7 — revise — mismatch — `readiness_status` never gates certification, so `CERTIFIED → CERTIFIED` and `CERTIFIED → FAILED` are reachable; only a `CANCELLED` schedule status and a `CLOSED` posture block the attempt — routes/windows.py:303-319
- §3.7 — insert — ambiguity — `measured_at` may not be after the clock; a future measurement is 400, settled before the area lookup — routes/courses.py:247-248
- §3.7 — insert — ambiguity — `current_moisture_pct` re-derived from the newest reading (measured_at, created_at, insertion); a back-dated reading leaves it alone yet still bumps the area's version unconditionally — calc.py:247-259, services.py:50-52, routes/courses.py:269-270
- §3.7 — insert — ambiguity — frost-release candidate ordering's final tie-break is earlier insertion order — calc.py (frost_release_schedule sort key)
- §3.7 — insert — ambiguity — the per-green readiness reading's final tie-break is later insertion order — calc.py:247-259
- §3.8 — insert — ambiguity — `initial_engine_hours` rounded half up to 1 dp before storage; the rounded figure seeds the meter and is echoed — fleet.py:42-47
- §3.8 — insert — ambiguity — `service_note` ≤2000 chars, may be empty, validated but neither persisted nor echoed — fleet.py:128
- §3.8 — insert — ambiguity — a future `model_year` floors the age at 0 years, so the age ratio is never negative — calc.py:215-217
- §3.8 — insert — ambiguity — days remaining to 31 December floored at 0, collapsing the projection onto the as-of-now score — calc.py:221-223
- §3.8 — insert — ambiguity — the 0–100 bound is applied to the already-rounded score, not the raw weighted sum — calc.py:199-210
- §3.9 — revise — mismatch — `delay_minutes` defaults to 0 and `affected_turf_area_ids` to `[]`; the type-conditional checks and the `expected_clear_at` > clock check are 400s settled before any lookup; stale course version beats area/course mismatch — fleet.py:177-208
- §3.9 — insert — ambiguity — `deferred_window_count` counts only windows that actually reached DEFERRED and never bumps the event's own `version`, which stays 1 on declaration — fleet.py:210-225, services.py:194-211
- §4 — revise — mismatch — `GET /applications` filter list gains `plan_task_id` and `verified_by_applicator_id` — routes/applications.py:232-238
- §4 — revise — mismatch — `GET /maintenance-windows` filter list gains `plan_task_id` — routes/windows.py:103
- §4 — revise — mismatch — `GET /equipment-units` filter list gains `replaced_by_unit_id` — fleet.py:79

## Notes
- §5 was left at exactly 51 rows as instructed. `app.py`'s `HTTPException` handler additionally emits `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_REQUEST_FAILED` and `ERR_INTERNAL` (500) for transport-level failures; these are framework-level and absent from `errors.ERROR_CATALOG`, so I did not add rows for them.
- All 61 §4 authorized-role lists were checked against the `@endpoint(...)` decorators and match exactly — no role changes were needed. All 51 §5 IDs and statuses match `errors.ERROR_CATALOG` 1:1.

**Orchestrator verification:** `PRD.md`, `PRD_FINALIZED.md` and `PRD_COMPLETED.md` are all 524 lines; `PRD_COMPLETED.md` has 51 `^| ERR_` rows, 63 lines in the §4 table (61 endpoints + header + separator), 5 top-level `##` sections, and its tail ends at `| ERR_WATER_ALLOCATION_EXCEEDED | 422 |` — complete, not truncated. Step 9 touched only `PRD_COMPLETED.md`, so the Step 7 green sweep (8/8 rounds at 118/118, `workspace/implementation/results.{1..8}.json`) remains valid for the shipped implementation.

## Pipeline complete — 2026-09-03T05:20:00.000Z

All nine steps finished. Final deliverables in place: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 modules), `test_suite/` (conftest + 18 test files, 118 tests), `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` (61 endpoints, in-memory only) and `workspace/implementation/results.{1..8}.json` from the final all-green stability sweep.

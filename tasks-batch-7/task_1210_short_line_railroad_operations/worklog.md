# Worklog — task_1210_short_line_railroad_operations

## Step 1: Create task directory — 2026-08-11T22:03:00.000Z

Pre-assigned output folder `tasks/task_1210_short_line_railroad_operations` with `workspace/` subdirectory already exists; Step 1 auto-index scan skipped per instructions. Treating Step 1 as done.

## Step 2: Generate scaffold — 2026-08-11T22:40:00.000Z

All done. Summary of the generated scaffold for task_1210_short_line_railroad_operations:

**Files written** (all verified on disk via `ls -la`):
- `/home/ubuntu/github/CodingPRD/tasks/task_1210_short_line_railroad_operations/SCAFFOLD.yaml` (§1.0–§1.7 + concurrency_rules; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1210_short_line_railroad_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1210_short_line_railroad_operations/SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`)

**Counts:**
- Entities: **17** (Customer, IndustrySiding, CarOrder, Railcar, SwitchJob, TrainMovement, InterchangeEvent, CarHireStatement, Waybill, RevenueDivision, TrackSegment, TrackInspection, CrewMember, CrewCall, Incident, GrantProject, GrantMilestone)
- State machines: **16** (including cyclic CrewMember duty/rest loop, cyclic Incident close/reopen, cyclic CarHireStatement dispute/reopen, guarded TrainMovement, compound GrantProject bubble-up)
- Calculations: **9** (car hire provisional/final dual variant, revenue division prorate/agreed dual variant with pinned rounding order, HOS nested-min, grant drawdown with pinned evaluation order, demurrage threshold, FRA class speed, inspection overdue sweep, percent complete, waybill rating)
- Endpoints: **101** (incl. `/rail/_clock/set_current_utc` with fixed default epoch 2026-05-01T00:00:00Z, two OCC-guarded writes)
- Errors: **33**; Validations: **33** (priority-ordered 1–9); Roles: **9** (segregation-of-duties model; Conductor/CustomerRep entity-backed); Concurrency rules: **2**
- Difficulty instances: **19** (all 9 rules ≥2; combinatorial_formula has 3 covering modes a/b/c; all numeric asserts pre-computed, e.g. car hire 28800 vs 39000, division 1389834 vs 1347500, grant drawdowns 400000/160000)
- Corner instances: **58** (52 active recipes + 6 `excluded_because` stubs citing difficulty instances)

**Verification:** `scaffold_lint.py` reports **VERDICT: clean lint** (429 calls scanned across §1.8/§1.9, all conform to §1.5; all FKs reverse-reachable). Instance names unique across both design files; stub references resolve; no forbidden concurrency vocabulary. Lint counts 52 active §1.9 instances (excludes the 6 stubs).

Note: the task directory already contained `worklog.md` and an empty `workspace/` (pre-existing, untouched).

## Step 3: Copy shared files — 2026-08-11T22:41:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1210_short_line_railroad_operations/workspace/INSTRUCTION.md` (1424 bytes, verified on disk).

## Step 4: Generate PRD — 2026-08-11T22:57:00.000Z

PRD generated and verified on disk at `/home/ubuntu/github/CodingPRD/tasks/task_1210_short_line_railroad_operations/workspace/PRD.md` (57,875 bytes, 354 lines). Generated solely from `SCAFFOLD.yaml` and the doc-generator skill spec; the two `SCAFFOLD_*_DESIGN.yaml` files and all sibling tasks were never opened.

## Structure

- **§1 Introduction** — 2 paragraphs, business-context angle.
- **§2 Global Specifications** — 10 subsections: 2.1 RBAC (all 9 roles with exact spelling; entity-backed identity prose for `Conductor`→`CrewMember` and `CustomerRep`→`Customer`, opaque for the rest), 2.2 response envelope (emitted verbatim from `section-2.2-response-structure.md`), 2.3 pagination (limit default 10/min 1/max 100, offset 0, `created_at` ascending), 2.4 logical clock (startup default `2026-05-01T00:00:00Z`, three sweeps, `to_iso8601`/`swept_*` fields), 2.5 common properties, 2.6 left-to-right reference validation, 2.7 monetary precision (integer cents, round-half-up, pinned rounding orders), 2.8 OCC (both guarded writes named with endpoint, OCC field, `ERR_STALE_VERSION`/412), 2.9 nine-band validation pipeline, 2.10 cascade map.
- **§3 Business Logic** — 9 domain-derived subsections (shippers/orders, furnishing/demurrage, fleet/interchange/car-hire, movements/switch jobs, waybills/divisions, track/FRA inspection, crew/HOS, incidents, grants). All 9 calculations expressed as precise prose with constants embedded via unit conversions ($75.00/car/day demurrage, $36.00 hire minimum, 720/16,560/600-minute HOS limits, class-speed and inspection-frequency tables, commodity rates $385/$420/$515 per ton).
- **§4 Endpoint table** — 101 rows, 4 columns only. **§5 Error catalogue** — 33 rows, 2 columns only.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields + endpoint inputs + query/path params: 119 required, 119 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 29 checked, 29 expressed (global pipeline in §2.9; per-endpoint orderings for accept and crew-call create in §3.2/§3.7), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_*_version + ERR_STALE_VERSION/412 each named), 0 missing
- state_machines[].transitions: 79 checked, 79 fully expressed (from/to, preconditions paired with error ids, all cascade side effects), 0 missing
- calculations[]: 9 checked, 9 fully expressed including provisional/final and prorate/percentage variants and pinned rounding orders, 0 missing
- validations[] conditions: all matchable to error ids in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (e.g., ERR_CAR_NOT_ON_LINE at waybill create AND rate; ERR_GRANT_NOT_ACTIVE at submit/approve/pay), 0 missing
- entities[].fields[] structured content (defaults, initial states, nullability, computed fields): reconstructible from prose, 0 missing
- sibling-branch symmetry: furnish/release/cancel state sets, FILED vs DEFECT_FILED, remediate vs waive, division bases, hire variants — equal density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 656
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Auxiliary coverage (beyond the three contracts): all 33 error IDs, all 84 state/enum literals, and all 9 role names appear verbatim in backticks. Note: the scaffold references `FRA_DAMAGE_THRESHOLD_CENTS` without defining its value anywhere; the PRD renders it faithfully as the named FRA damage-reporting threshold without inventing a number.

## Step 5: Generate unit tests — 2026-08-11T23:05:00.000Z

Test generation for task_1210 (short-line railroad operations) is complete and verified on disk.

## Summary

**Tests generated: 89 total** (all collected cleanly by pytest, all compile, zero skip/xfail markers)

- **Queue A (Difficulty): 38 tests** — all 19 non-stub instances covered with exactly 2 tests each (≥2 requirement met).
- **Queue B (Corner): 51 tests** — 51 of 52 non-stub instances covered with exactly 1 test each.

**Instances skipped (1, with reason):**
- `Corner/errors/incident_fra_report_on_non_reportable_rejected` — the instance asserts a CROSSING incident at 1000 cents is non-reportable, but that depends on `FRA_DAMAGE_THRESHOLD_CENTS`, whose numeric value appears nowhere in the PRD (the PRD names the constant but never states the threshold). A PRD-only implementer could pick a threshold below 1000 cents, so `fra_reportable == false` is not uniquely derivable. Gap left as a gap.

**Corner stubs (6) not translated** (per spec): `demurrage_computed_read`, `car_hire_provisional_field_correctness`, `revenue_division_rounding_precision`, `error_coverage_stubs`, `crew_rest_sweep_releases_member`, `fleet_invariant_layer` — all six `difficulty_instance` cross-references verified to resolve to real queue-A instances.

**Recipe correction (1):** `Corner/validations/grant_submit_blocked_when_not_active` — the yaml recipe's trigger asserted milestone *creation* fails on an AWARDED project, but the PRD scopes `ERR_GRANT_NOT_ACTIVE` to "Submission, approval, and payment" only. Translated per the instance's name/distinguishing aspect instead: create milestone on AWARDED project succeeds, then `submit` is rejected with `ERR_GRANT_NOT_ACTIVE`.

**Assertion relaxations for unique derivability (no weakened rules, just unpinned values):** the PRD never states the initial `version` value, so `version == 1` assertions from the recipes were replaced with relative checks (`v_after == v_before + 1`, which PRD §2.5 pins). Timestamp equality on the fixed epoch is asserted by parsed instant comparison, not string equality (PRD pins ISO-8601/UTC/3-fractional-digits but not `Z` vs `+00:00` rendering).

**Verification performed:**
- Tag audit: all 89 tests carry exactly one `Design:` line; every tag resolves to a real instance in the source yamls; no stub translated.
- Citation audit: all 120 quoted PRD passages across the 89 docstrings survive whitespace-normalized literal grep of `workspace/PRD.md` (C1/C2/C3).
- `pytest --collect-only`: 89 tests collected, no import errors.

**Helper files written** (`test_helpers/`, 9 files, ~1650 LOC): `types.py` (17 entity TypedDicts + 20 enums; all entities carry full common fields per PRD §2.5), `api_client.py` (107 methods, one per endpoint in the PRD §4 table), `api_errors.py` (33 error IDs + HTTP map registered with the framework), `assertions.py` (per-entity asserts + grant-conservation and division-conservation invariants), `factories.py`, `constants.py` (FRA class speeds, defect caps, inspection frequencies, HOS limits 720/16560/600, MIN_HIRE 3600, demurrage 7500, commodity rates), `test_users.py` (9 role header sets + mandatory `make_conductor_headers`/`make_customer_rep_headers` entity-backed builders), `fixtures.py` (composite setups: accepted/furnished/released orders, movement+crew chains through DEPARTED/ARRIVED, rated waybills, foreign-car receipt with OPEN statement, HOS accumulator correction).

**Test files** (`test_suite/`, conftest + 13 domain-named files): customers, fleet/segments/clock, car-order lifecycle, acceptance/demurrage/fleet-conservation, crew HOS limits, crew-call lifecycle, track inspection, train movements, interchange/car-hire, waybills, revenue divisions, incidents, grant projects.

## Step 6: Generate implementation — 2026-08-11T23:05:00.000Z

Implementation complete and verified. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1210_short_line_railroad_operations/workspace/implementation/`)

- `start.sh` — executable, guarded `pip install` (no-op once Flask present), `exec python3 app.py` in foreground
- `requirements.txt` — `flask>=3.0,<4`
- `app.py` — Flask app factory, blueprint registration, `ApiError`/404/405/500 envelope handlers, `0.0.0.0:$PORT` (default 10000), static route disabled
- `db.py` — in-memory `Store` (17 entity dicts + logical clock at `2026-05-01T00:00:00Z`); empty on every boot, zero seeding/persistence (grep-verified)
- `errors.py` — all 33 error IDs with exact HTTP statuses from the scaffold catalog
- `envelope.py` — `meta{api_request_id, api_request_timestamp}` (+`limit/offset/total_count/has_more` on lists), `response_type` object/array/error, `data{error_id, message}` on errors
- `auth.py` — `X-User-ID`/`X-User-Role` validation (401), 9 roles, entity-backed identity checks (Conductor→CrewMember, CustomerRep→Customer)
- `util.py` — syntactic-band validators (400), ISO-8601 parsing, millisecond `Z` formatting, limit/offset pagination (default 10, clamp [1,100])
- `domain.py` — all 9 calculations with pinned constants and rounding (Decimal ROUND_HALF_UP), serializers, cascades, clock sweeps
- `routes_core.py`, `routes_fleet.py`, `routes_crew.py`, `routes_movement.py`, `routes_interchange.py`, `routes_track.py`, `routes_grants.py` — route handlers

## Endpoint coverage

Static cross-check of registered Flask routes vs SCAFFOLD.yaml: **101/101 (method, path) pairs match, none missing, none extra**. Boot smoke tests (3 scenarios, ~85 assertions) passed: full order→furnish→release→movement→waybill→settle→division lifecycle, crew HOS accept/duty/relieve with 480-minute accumulator math, rest sweep, overdue sweep (exactly-at-deadline not overdue; +1s overdue+RESTRICTED with movement annul cascade), siding expiry/renew, car-hire accrual (provisional 72h×200=14400; final 14400+12000=26400; MIN_HIRE floor 3600), division rounding (prorate 30900/72100; agreed-pct 0.335 half-up→38693), grant waterfall (500000×0.8 capped at 400000) and completion bubble-up, OCC 412s, RBAC 401/403s, and band-order precedence (e.g. ERR_DIVISION_EXISTS 409 before ERR_DIVISION_BASIS_INVALID 400).

## Ambiguities resolved (documented choices)

1. **`FRA_DAMAGE_THRESHOLD_CENTS` has no value anywhere** (worklog confirms deliberate): used the real-world FRA threshold $12,100 → `1210000` cents. Type-based reportability (DERAILMENT/COLLISION/HAZMAT) is unaffected by this choice.
2. **Validation band order**: PRD §2.9 explicitly puts syntactic body validation (400) after auth headers but *before* role authorization (403) — implemented that way (overrides the scaffold `validations[].priority` numbering, per PRD-wins).
3. **Entity timestamps** (`created_at`/`updated_at`) use the logical clock, not wall-clock — makes the furnish ranking tie-break (`created_at ASC, reporting_mark ASC`) deterministic and testable; `meta.api_request_timestamp` uses wall-clock as request metadata.
4. **Furnish `count > remaining`**: state machine defines only `count < remaining` and `count == remaining` transitions → rejected with `ERR_INVALID_REQUEST` 400.
5. **Siding `renew-agreement` with `new_expires_on <= now`**: no named error exists → `ERR_INVALID_REQUEST` 400.
6. **Division on a non-through waybill**: endpoint is specified "for a through waybill" and prorate needs miles → rejected with `ERR_DIVISION_BASIS_INVALID` 400.
7. **Manual car-hire close**: sets `hire_accrual_end = clock` so the frozen final and recomputed reads agree.
8. **Movement annulment cascade**: TrainMovement SM says "CRITICAL defect" but PRD §3.4/§2.10 explicitly includes the overdue sweep — implemented per PRD (any IN_SERVICE→RESTRICTED transition cascades).
9. **Siding ownership mismatch** on order create (siding belongs to another customer) → `ERR_INVALID_REQUEST` 400 (no specific error in catalog).

## Step 7: Run tests and iterate — 2026-08-11T23:20:00.000Z

Pre-sweep route cross-check: implementation registers exactly the 101 (method, path) pairs SCAFFOLD.yaml declares (0 missing, 0 extra — script `/tmp/task_1210_route_check.py`, VERDICT: MATCH).

Iteration 1 sweep (8 parallel rounds via script `/tmp/task_1210_sweep.sh`, verbatim `cd <implementation dir> && bash start.sh` start-command): all 8 rounds 81/89; union of 10 distinct non-passing tests (7 consistent failures + 3 intermittent server-restart errors). Fix subagent ran the full diagnostic protocol and returned the summary below. Iteration 2 sweep: **all 8 rounds 89/89 — SWEEP_VERDICT: ALL_PASS**. Tests deleted: 0. Iterations run: 2 sweeps, 1 fix round.

Fix-subagent summary (verbatim):

The verification probe passed 89/89 in 54s with zero failures and zero errors, on the same loaded box. No leftover processes. All work is complete.

## Summary (for worklog.md)

**8-round sweep diagnosis: union of 10 non-passing tests, all root-caused and fixed. Verification: one full `prd-bench-local-run --isolation per-test-server` probe round → 89/89 passed, 0 errors.**

### Failures 1–5 (UUID format) — implementation bug, fixed
PRD §2.5: "The `id` is a server-minted UUID with no type prefix." The canonical string form of a UUID is the hyphenated 8-4-4-4-12 form, which is what the shared benchmark helper `is_valid_uuid` (prd_bench_local_runner.testing) requires. The implementation minted `uuid.uuid4().hex` (32 hex chars, no dashes).
- `test_01 .../TestCustomerCreation.py::test_customer_creation_defaults_applied`
- `test_02 .../TestRailcarRegistration.py::test_railcar_system_fields_server_minted`
- `test_03 .../TestCarOrderInitialState.py::test_car_order_initial_state_placed`
- `test_05 .../TestHosDailyBoundary.py::test_hos_daily_boundary_719_callable` (same root cause surfacing on crew-call create response)
- `test_06 .../TestCallWindowOverlap.py::test_crew_call_adjacent_window_allowed` (same)

**Fix:** `/home/ubuntu/github/CodingPRD/tasks/task_1210_short_line_railroad_operations/workspace/implementation/domain.py` line 62 — `uuid.uuid4().hex` → `str(uuid.uuid4())` (sole id-minting site; verified no helper or implementation code depends on the 32-hex form). All 5 tests verified passing against a live probe server.

### Errors 6–8 (could not be restarted) — load-induced flakiness, boot hardened
- `test_09 .../TestCarHireDualVariant::test_car_hire_final_amount_after_delivery` (rounds 1,2,4,6)
- `test_09 .../TestStatementLifecycle::test_statement_settled_terminal_lockdown` (rounds 3,5,8)
- `test_12 .../TestIncidentReportableCycle::test_incident_reopen_second_loop` (round 7)

Diagnosis: not a test or app defect — all three tests pass when the server is up (verified directly). Standalone boot takes 0.6–1.6s vs the runner's 15s restart-poll window; the box concurrently runs other tasks' sweeps (observed 12+ foreign `app.py` servers and multiple task_1212 pytest rounds), so intermittent CPU starvation pushes some boots past 15s. Hardening applied to shrink the boot window and survive transient bind contention:
- `/home/ubuntu/github/CodingPRD/tasks/task_1210_short_line_railroad_operations/workspace/implementation/app.py` — retry `app.run()` up to 20×0.5s on `OSError` (covers transient EADDRINUSE from the just-SIGKILLed previous server on the same port; process still dies cleanly on kill since start.sh `exec`s python).
- `/home/ubuntu/github/CodingPRD/tasks/task_1210_short_line_railroad_operations/workspace/implementation/start.sh` — `.deps_installed` marker so the `python3 -c "import flask"` probe (a full interpreter + Flask startup, ~0.22s idle) runs once instead of on every one of the ~712 boots per sweep; pip install still runs on a fresh environment per the build contract.

### Failures 9–10 (grant 409 setup) — test bug, fixed
- `test_13 .../TestAwardConservation::test_grant_award_conservation_across_transitions`
- `test_13 .../TestAwardConservation::test_grant_percent_complete_excludes_rejected`

Root cause: `TestAwardConservation._conservation_scenario` paid milestone A while A was the project's only milestone. PRD §3.9: "when the project has at least one milestone and every milestone stands `PAID`, the project moves itself from `ACTIVE` to the terminal `COMPLETED`" — so the bubble-up correctly fired, and the next `submit_milestone` legitimately failed with `ERR_GRANT_NOT_ACTIVE` (PRD: "Submission, approval, and payment all require the project to be `ACTIVE`"). The implementation's behavior is PRD-correct; the fixture ordering was not.

**Fix:** `/home/ubuntu/github/CodingPRD/tasks/task_1210_short_line_railroad_operations/test_suite/test_13_grant_projects.py` `_conservation_scenario` — moved `pay_milestone(m_a)` to after B is APPROVED and C is REJECTED (not every milestone PAID at pay time → project stays ACTIVE). Expected aggregates unchanged (drawn 400000 / committed 160000 / remaining 440000 / percent_complete 80.0). Both tests verified passing.

### Additional fixes beyond the 10
None beyond the app.py/start.sh boot hardening listed under errors 6–8. No tests deleted; no assertions weakened; no PRD-required checks removed.

## Step 8: Finalize PRD — 2026-08-11T23:32:00.000Z

PRD_FINALIZED.md written at `/home/ubuntu/github/CodingPRD/tasks/task_1210_short_line_railroad_operations/workspace/PRD_FINALIZED.md`.

**Line counts / delta:** PRD.md 354 lines, PRD_FINALIZED.md 354 lines — 0% line-count delta (one inline sentence revision, no lines added or removed).

**Changes (one edit total):**
- §2.5 Common Resource Properties — revise — extended "The `id` is a server-minted UUID with no type prefix" to pin the serialization: "rendered in the canonical hyphenated string form (8-4-4-4-12 hexadecimal groups, as produced by `str(uuid.uuid4())`)" — implementation/domain.py:62.

**Step 7 items judged not PRD-relevant (no edit):**
- test_13 fixture reorder — pure test bug; PRD §3.9 already pinned the completion bubble-up and implementation was PRD-correct.
- app.py `app.run()` OSError retry — boot/infrastructure robustness, no endpoint behavior.
- start.sh `.deps_installed` marker — infrastructure only.

**Pre-edit search log (mandatory, per edit):**
- Edit 1 (§2.5 UUID rendering):
  - (a) Subject: string serialization of server-minted resource `id`.
  - (b) Paths enumerated: grepped all `implementation/*.py` for `uuid`/`uuid4` — the only minting site is `domain.py:62` inside `new_record()`. Grepped `"id"` writes across routes (`routes_crew.py:47,171,287`, `routes_grants.py:44,126`, `routes_movement.py:54,288`, `routes_track.py:50,126`, etc.) — every entity's id flows from `new_record()`, so all entities (customers, sidings, orders, cars, jobs, movements, interchange events, statements, waybills, divisions, segments, inspections, crew members, crew calls, incidents, projects, milestones) share the hyphenated form. No alternate id-minting or id-reformatting path exists anywhere in the codebase.
  - (c) Wording adjustment: the sentence was scoped to "server-minted" id only and phrased as the rendering format of the already-existing "UUID" term, so it neither narrows §2.5's universality claim nor implies anything about client-supplied reference ids in request payloads (which are only validated for existence, not re-serialized). No further adjustment needed.

## Step 9: Complete PRD — 2026-08-11T23:46:00.000Z

PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1210_short_line_railroad_operations/workspace/PRD_COMPLETED.md`.

## Exit summary

**Source vs output:** PRD_FINALIZED.md 354 lines / 57,993 chars → PRD_COMPLETED.md 354 lines / 60,684 chars (char-delta +2,691; line count unchanged — all changes are in-paragraph inserts/revisions, no new sections).

**Counts:** 24 ambiguity-pins, 4 mismatch-revisions (28 edits across 24 paragraph lines).

### Mismatch revisions (4)
- §3.3 Railcar registration — revise — mismatch — hire rates `hire_rate_per_hour_cents`/`hire_rate_per_mile_cents` are required on every registration (home and foreign alike), and `home_road_mark` is optional, replacing "for foreign cars, the home_road_mark plus the car-hire rates" — routes_fleet.py:260-262
- §3.6 Clean inspection filing — revise — mismatch — a `defect_found` false filing no longer leaves the segment "otherwise untouched": a segment standing `RESTRICTED` with no open defect returns to `IN_SERVICE` (the fresh filing clears overdue); also a `defect_severity` supplied without a defect is validated but not recorded — routes_track.py:191-196, 177-184
- §3.6 Waive — revise — mismatch — `justification` is accepted but not stored on the inspection (was "optionally recording a `justification`") — routes_track.py:230-233, domain.py:441-449 (no justification field in inspection_view)
- §3.8 FRA filing — revise — mismatch — the server assigns `fra_report_number` (zero-padded sequential `FRA-000001`, …), not the officer — db.py:37-39, routes_track.py:332

### Ambiguity pins (24)
- §2.2 — insert — `api_request_timestamp` reads the wall clock, never the logical clock — envelope.py:22-24
- §2.3 — insert — out-of-range `limit`/`offset` clamped (non-integer → `ERR_INVALID_REQUEST`); `created_at` ties ordered by creation sequence; `has_more` = offset + returned < total_count — util.py:162-190, envelope.py:44
- §2.4 — insert — clock instant applied verbatim with no ordering constraint; sweep counters count resources transitioned by each sweep — routes_core.py:29, domain.py:126-163
- §2.5 — insert — entity `created_at`/`updated_at` read from the logical clock — domain.py:63-64, 73
- §3.1 — insert — customers listable filtered by `credit_status` — routes_core.py:65-68
- §3.1 — insert — renew-agreement `new_expires_on` not strictly later than clock → `ERR_INVALID_REQUEST` 400 — routes_core.py:168-170
- §3.1 — insert — order `siding_id` belonging to another customer → `ERR_INVALID_REQUEST` 400; `needed_by_date` is an ISO 8601 datetime — routes_fleet.py:45-47, 36
- §3.1 — insert — amendment replacement `quantity` below one → `ERR_INVALID_REQUEST` (checked before the furnished-count rule) — routes_fleet.py:111-113
- §3.2 — insert — furnish `count` above the unfilled remainder → `ERR_INVALID_REQUEST` 400 — routes_fleet.py:160-163
- §3.3 — insert — open received event = `REPORTED`/`CONFIRMED` with no later confirmed delivered event for that car — routes_interchange.py:24-34
- §3.3 — insert — statement reuse re-stamps `hire_accrual_start`; `period_month` in `YYYY-MM` form — routes_interchange.py:125-129
- §3.3 — insert — delivered confirmation requires the car still on line, else `ERR_INVALID_STATE`; no `OPEN` statement → no car-hire effect — routes_interchange.py:142-155
- §3.3 — insert — every statement read in every status carries computed `accrued_hours` and `provisional_amount_cents` — domain.py:387-398
- §3.3 — insert — manual close stamps `hire_accrual_end` from the clock — routes_interchange.py:227
- §3.3 — insert — reopen clears `hire_accrual_end` and frozen `final_amount_cents`, retains `accrued_miles` — routes_interchange.py:268-272
- §3.4 — insert — `route_segment_ids` must be a non-empty array — routes_movement.py:34-37
- §3.5 — insert — `weight_tons` must be zero or greater — routes_movement.py:245-246
- §3.5 — insert — settle cascade auto-creates the division only when the waybill does not already have one — routes_movement.py:215
- §3.5 — insert — division creation on a non-through waybill → `ERR_DIVISION_BASIS_INVALID` 400 — routes_movement.py:358-360
- §3.5 — insert — `MILEAGE_PRORATE` with `total_miles` zero yields `our_share_cents` zero — domain.py:220-224
- §3.7 — insert — adjust-hos supplied values must be ≥ 0, else `ERR_INVALID_REQUEST` — routes_crew.py:87-90
- §3.8 — insert — `FRA_DAMAGE_THRESHOLD_CENTS` fixed at 1,210,000 cents ($12,100.00) — domain.py:34, routes_track.py:256-257
- §3.9 — insert — `award_amount_cents` must be ≥ 0 — routes_grants.py:30-31
- §3.9 — insert — `milestone_value_cents` must be ≥ 0 — routes_grants.py:105-106
- §3.9 — insert — zero-award project reports `percent_complete` 0.0 — domain.py:496-500

**Verified already-pinned (no change):** the validation band order with syntactic 400 before role 403 (§2.9), the movement annulment cascade on any `IN_SERVICE`→`RESTRICTED` transition (§3.4), division-exists (band 7) before basis-shape (band 8), call-target check after window overlap, demurrage formula, HOS gate order, drawdown waterfall, and all endpoint role lists.

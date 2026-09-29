# Worklog — task_2487_wildfire_mitigation_public_safety_power_shutoff

## Step 1: Create task directory — 2026-09-03T00:18:00.000Z

Created pre-assigned directory `/home/ubuntu/github/CodingPRD/tasks/task_2487_wildfire_mitigation_public_safety_power_shutoff` and its `workspace/` subdirectory. Index fixed by scenario number (2487) per orchestration instructions; no scan of ./tasks/ performed and no other task directory created.

## Step 2: Generate scaffold — 2026-09-03T01:56:00.000Z

All three scaffold artifacts are complete and the lint is clean.

**Output** — `/home/ubuntu/github/CodingPRD/tasks/task_2487_wildfire_mitigation_public_safety_power_shutoff/`

- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys): 14 entities, 9 state machines, 2 OCC concurrency rules, 15 calculations, 17 validations, 54 endpoints, 54 errors, 8 roles. `api_prefix: ""`; profile = `temporal_windowing` / `compliance_audit`, cyclic state machines, flat topology, `segregation_of_duties` role model, layers `[rate_threshold_triggers, cascading_side_effects, dual_variant_calculation, optimistic_concurrency]`, `consistency_model: immediate`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`): 9 rule blocks, **26 instances** (3/3/4/2/3/4/3/2/2).
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`): 9 sections, **132 instances** — entities 18, state_machines 21, calculations 23, validations 34, endpoints 10, errors 7, rbac 7, cross_cutting_complexity_layers 10, consistency_model 2. 93 carry full `test_recipe`s; 39 are `excluded_because` stubs pointing at 24 distinct §1.8 instances.

**Verification** — `scaffold_lint.py` prints `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (2221 calls scanned). Independent checks: all 158 instance names unique across both files, every `${var}` closed by an earlier capture in its own recipe, all 54 error ids referenced, and all 54 endpoints exercised by at least one call.

**Design adjudications**
- The customer that makes the imminent batch partially unreachable had to be TIER_B_MEDICAL, not CRITICAL_FACILITY: a critical account pushes `customer_impact_score` to 72.00 and the arm gate (0.215 < 0.25 floor) would fire before `ERR_CRITICAL_NOTIFICATION_INCOMPLETE` could ever be observed. The medical variant gives 57.60 / 0.2688, which still arms.
- `ERR_PATROL_WINDOW_INVALID` / `ERR_PATROL_WINDOW_OVERLAP` (priorities 13/16) are only observable after the all-clear, because the priority-9 cross-entity gate (`ERR_CIRCUIT_NOT_DE_ENERGIZED` / `ERR_EVENT_NOT_IN_RESTORATION`) outranks them.
- `ERR_CIRCUIT_NOT_CLEARED_FOR_RESTORE` (priority 8) is reachable only on a circuit with no patrol at all, since priority 8 outranks the priority-10 patrol-clearance gate.
- Credit-rate band boundaries needed a purpose-built fixture (OSCAR-A/OSCAR-B) engineered to land on `customer_impact_score` exactly 20.00 and exactly 60.00, proving both breaks are inclusive from above and keyed on the *unadjusted* score (credits 1.00 and 7.20, ratios 0.2842 and 0.3066; falsifiers 0.2700 and 0.2840).
- The RBAC denial matrix needed one throwaway circuit in setup purely so `expected_circuit_version` could be a live `${var}` (lint check (e) is not relaxed for negative triggers).
- The event-scoped resource-centre listing claim originally used a global `GET /community-resource-centers`, which does not exist in §1.5; per the SKILL priority ladder I composed the existing `GET /community-resource-centers/{id}` instead of adding an endpoint.

**Disclosure** — the hard constraint was honoured: no sibling `tasks/task_*/` directory was listed, globbed, grepped or read. One incidental exposure: `/home/ubuntu/github/CodingPRD/skills/prd-bench-scaffold-generator/SCAFFOLD_CORNER_DESIGN.yaml` is an untracked §1.9 file belonging to `task_2205_excess_surplus_lines_placement_tax` that is sitting inside the skill directory (not under `tasks/`). Its header and first ~80 lines were read before that was recognised, only to learn the file shape; the domain is unrelated and nothing here was designed from it.

## Step 3: Copy shared files — 2026-09-03T01:56:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2487_wildfire_mitigation_public_safety_power_shutoff/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T02:14:00.000Z

PRD generation is complete.

**Output:** `workspace/PRD.md` — **462 lines, ~14,190 words.**

**Section list**

- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Operator Identity and Role-Based Access Control · 2.2 API Response Structure · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Version Counters · 2.5 The Logical Clock · 2.6 Numeric Precision and Rounding Discipline · 2.7 Version Guards on Scope Determination and Mileage Recording · 2.8 Validation Order · 2.9 Segregation of Duties · 2.10 Cascade Discipline · 2.11 Conserved Quantities
- `## 3. Business Logic & Workflows` — 3.1 The Grid Model: Circuits, Feeder Chains and Served Accounts · 3.2 The Weather Desk: Station Networks, Telemetry and the Fire Potential Index · 3.3 Risk Posture and the Mitigation Programme Portfolio · 3.4 Opening a Shutoff Event and Determining Its Scope · 3.5 Sequencing Customer Notifications · 3.6 Arming the Shutoff, Executing It, and Opening Resource Centers · 3.7 All-Clear, Patrol, Damage Assessment and Re-energization · 3.8 Closing, Cancelling and the Net-Benefit Accounting · 3.9 Regulatory Plan Filings and Performance Reporting
- `## 4. Endpoint Definitions` — 54-row, 4-column table
- `## 5. Error Code Catalogue` — 54-row, 2-column table

**Coverage confirmation (mechanically verified against SCAFFOLD.yaml)**

- **Entities/fields:** 14 entities, **148/148** distinct field names present in backticks — 0 missing. Includes the never-consumed `temperature_f` and all four append-only entities.
- **Non-entity params:** all 25 request/response/query/envelope identifiers present (`limit`, `offset`, `expected_psps_event_version`, `expected_circuit_version`, `completed_miles_delta`, `completion_date`, `decision`, `review_note`, `review_track`, `deficiency_note`, `requested_resource_center_ids`, `to_iso8601`, `activated_count`, `activated_capacity`, `unmet_capacity`, `activated_resource_center_ids`, `current_utc`, etc.).
- **Endpoints:** 54/54, exact method + path + authorized-role list transcribed from the scaffold; 201-vs-200 rule stated.
- **Errors:** 54/54 in §5 in scaffold order with exact HTTP statuses; every one of the 54 is *also* triggered in §2/§3 prose (0 orphans).
- **State machines:** 9 dimensions across 8 entities, **49/49 transitions** described with preconditions and side effects — including the `CLEARED_FOR_RESTORE → PATROL_IN_PROGRESS` repair back-edge, the three distinct `→ WITHDRAWN` edges, the `SCOPED → SCOPED` hard-delete re-scope, the `ADVANCE_SENT → ADVANCE_SENT` self-loop, the `SUBMITTED → SUBMITTED` fork-join leg, and `DEMOBILIZED → ACTIVATED`.
- **Calculations:** 15/15 (`circuit_hardened_fraction` … `hardened_mileage_ledger`), all in prose with every constant, clamp, tie-break, and pinned rounding order (single-rounding on `fpi_score` and `compliance_score`; the step-1-keyed credit rate in the net-benefit chain).
- **Validations:** 17/17 priorities as an ordered list in §2.8 with each `error_id`, HTTP status, and exact `applies_to` enumeration.
- **Concurrency:** both OCC rules (§2.7 plus the §3.4 / §3.3 write sites) → `ERR_STALE_VERSION` 412.
- **Roles:** 8/8, all documented as opaque with the four recorded-identifier exceptions.

**Hard Contract results**

1. **Field-Name Coverage — PASS** (148/148 entity fields + 25 auxiliary params).
2. **Rule Coverage — PASS** (49 transitions, 15 calculations, 17 validations, 2 OCC rules, 54 errors).
3. **§3 Path Purity — PASS** (0 URL paths and 0 HTTP verbs in §3, in backticks *or* bare prose; all §3 operations framed as state transitions, role + action verb, or capability descriptions).

Also verified: §2.2 is byte-identical to `section-2.2-response-structure.md`; no fuzzy quantitative hedges (the three `about` hits are non-numeric prose); no audit footer inside the file. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**Exact last line of the file:** `| `ERR_RESOURCE_CENTER_DISTRICT_MISMATCH` | 422 |` — the final row of the §5 error table.

**Orchestrator anti-truncation check (independent):** `wc -l` = 462; `tail -20` shows 20 complete error-table rows ending at the §5 table's last row; `grep "^## "` shows all five top-level sections present (lines 3 / 11 / 174 / 342 / 403). Not truncated — no regeneration needed. Difficulty-instruction leak check: `grep -in "harder than expert|expert level|difficulty"` on PRD.md returns no hits.

## Step 5: Generate unit tests — 2026-09-03T05:00:00.000Z

Test generation is complete and fully audited.

## Files written

**Stage 1 — infrastructure**, `test_helpers/`
`__init__.py`, `constants.py`, `types.py`, `test_users.py`, `api_errors.py`, `api_client.py` (54 endpoint methods), `factories.py`, `assertions.py`, `fixtures.py` (tiered builder chain from `register_circuit` up through `build_closed_event`, `build_completed_hardening`, filing helpers).

**Stage 2 — tests**, `test_suite/` (plus `conftest.py`) — 17 files, 12,653 lines total, 151 tests collected in 0.46 s.

## Test counts

Queue A (§1.8 depth, `Design: Difficulty/...`) — 57 tests
`test_01_dual_variant_calculations.py` 6, `test_02_combinatorial_formulas.py` 6, `test_03_non_linear_state_machines.py` 8, `test_04_transitive_cascades.py` 5, `test_05_validation_priority_conflicts.py` 6, `test_06_boundary_precision.py` 8, `test_07_cross_entity_state_dependency.py` 6, `test_08_resource_temporal_overlap.py` 6, `test_09_compensating_invariants.py` 6.

Queue B (§1.9 breadth, `Design: Corner/...`) — 94 tests
`test_10_entities.py` 16, `test_11_state_machines.py` 17, `test_12_calculations.py` 15, `test_13_validation_order.py` 9, `test_14_validation_gates.py` 13, `test_15_endpoints.py` 7, `test_16_rbac.py` 7, `test_17_errors_and_cross_cutting.py` 10.

## Coverage audit

- Difficulty: 26/26 instances covered, every one with >=2 tests (5 with 3).
- Corner: all nine sections at full live coverage — entities 16/16, state_machines 16/16, calculations 15/15, validations 22/22, endpoints 7/7, errors 4/4, rbac 7/7, cross_cutting_complexity_layers 4/4, consistency_model 2/2 (93 live instances, 93 covered). `excluded_because:` stubs were not translated.
- Tag audit `BAD = 0`: every test carries exactly one trailing `Design:` line, none dual-tagged, no tag pointing at a non-existent instance, no file below 5 tests.
- Citation audit `BAD = 0` across all 17 files: every docstring quote is a verbatim, greppable, rule-bearing full PRD sentence.
- `py_compile` and `pyflakes` clean on every file; module import succeeds; pytest collects all 151.

## Instances skipped / narrowed

No instance was fully skipped. One design claim was omitted as not PRD-derived: inside `Corner/errors/every_not_found_id_is_reachable_from_its_own_read_path` the design also asserts that unknown identifiers passed as *query filters* return 404. PRD §2.8 priority 4 covers only path ids, priority 6 only body foreign keys, and priority 5 only shape/range, so nothing uniquely derives a 404 for an unresolvable query-filter value. The instance is translated with its eight path-based 404s and the error-envelope assertion; the three query-filter calls are not emitted.

## Design-vs-PRD conflicts resolved in the PRD's favour

- `Corner/rbac/operational_roles_perform_their_own_exclusive_operations`: the design expects all three circuits to finish `ENERGIZED`/`NORMAL`, but §3.3 recomputes posture on leaving `LOCKED` against the circuit's latest `FORECAST` index, so ALPHA lands on `EXTREME`. Asserted ALPHA `EXTREME`, dependants `NORMAL`, with an inline note.
- `Corner/consistency_model/a_multi_entity_cascade_is_fully_visible_to_the_next_read`: the in-flight 2.0-mile hardening shifts ALPHA's `ignition_risk_term` to 4.98, so the design's ignition/ratio figures no longer hold; the test asserts the cascade's state and snapshot facts and leaves the scores to the dedicated calculation tests.
- `Corner/cross_cutting_complexity_layers/credit_rate_bands_break_exactly_at_twenty_and_sixty`: the two band-edge events had to be given distinct `forecast_date`s (2026-08-15 and 2026-08-20), because §3.4 step one scans every circuit for an index matching the event's target date and a shared date would pull both circuits into both scopes.

## Step 6: Generate implementation — 2026-09-03T04:12:00.000Z

Implementation complete and verified end to end.

## Files written
All under `workspace/implementation/` (22 files):

- `start.sh` (guarded `pip install`, then `exec python3 app.py`; host `0.0.0.0`, `PORT` default 10000), `requirements.txt`
- `app.py` (app factory, `g.touched` per-request version guard, ApiError/HTTPException/Exception handlers)
- `clock.py` (logical clock pinned at `2026-08-01T00:00:00Z`), `response.py` (envelope, `req_`+20-char ids, 3-frac-digit ISO8601, Decimal encoder), `errors.py` (all 54 error ids -> HTTP status + default messages), `db.py` (14 in-memory dict collections + 14 serializers), `middleware.py` (8 roles, `X-User-ID`/`X-User-Role` auth + `roles()`), `validation.py` (body/query/FK/pagination helpers)
- `services/{__init__,calc,events,notifications,centers}.py` — FPI/risk-posture/score/budget/filing math (all `Decimal`, ROUND_HALF_UP, truncation for `budget_cents`, ROUND_CEILING for `duration_hours`, ROUND_FLOOR for lead-time/customer-minutes), scope determination + lifecycle, notification targeting/waterfall, CRC activation
- `routes/{__init__,circuits,weather,events,customers,notifications,mitigation,patrol,centers,filings,clock}.py`

## Endpoints
**54/54** implemented — `python3 -c "import app"` enumerates exactly 54 non-static rules, matching the PRD §4 table one-for-one. Storage is purely in-process dicts with zero seeding, so every `start.sh` re-launch wipes all state (required for `--isolation per-test-server`).

## Verification
Two live-HTTP smoke walks (scratch scripts in `/tmp`, outside the deliverable tree) both pass: the main walk covers every subsystem plus RBAC 401/403, 404s, 412 OCC, 409/422 conflicts, pagination meta, and both §2.11 conserved-quantity identities (energized-customer count restored after a full de-energize/restore cycle and after an arm/cancel pair; hardened-mileage ledger restored to `0.0/0.0` after a completion+withdrawal pair). A second walk verifies BFS downstream closure (2 hops inherit the upstream FPI 98.5, terms 4.93/3.94) and the fast-trip R4 exemption (score 67.0 -> `EXCLUDED / FAST_TRIP_MITIGATED_R4`, zero ignition term, and its child correctly *not* pulled into scope).

One bug found and fixed during this pass: `db.new_row()` now registers the new row id in `g.touched`, so a row created and then cascade-touched within the same request reads `version: 1` instead of `2` (previously affected freshly created event-scope rows, whose ignition term is computed after insertion).

## PRD ambiguities resolved
- **§2.8 priority order overrides §3.x narrative order** everywhere. Arm: own-state -> advance-notification -> confirmed-scope -> net-benefit. Batch planning: window (13) -> no-circuits (14). Dispatch: own-state -> lead-time -> no-circuits. Record-completion: OCC (2) -> own-state (8) -> miles-exceeded. Patrol reservation: circuit phase (9) before window validity (13) before interval overlap (16).
- **CRC explicit activation validated rule-major** (all `ALREADY_ACTIVE`, then all `BUFFER_CONFLICT`, then all `DISTRICT_MISMATCH`) rather than site-major, per §2.8 8 -> 16 -> 17; duplicate ids in the request list are deduped.
- **Terminal events** answer `ERR_EVENT_TERMINAL` on every `/psps-events/{id}/*` action; `ERR_EVENT_NOT_CANCELLABLE` is reserved for ACTIVE/RESTORING. Exclude/scope on a wrong non-terminal state -> `ERR_EVENT_NOT_SCOPED`.
- **No terminal gate on notification-batch planning or dispatch** (the two state dimensions are explicitly independent); a terminal gate *is* applied to activate-resource-centers.
- **Filing-review SoD** applies to both CLEAR and DEFICIENT second decisions (§2.9 "the second decision is refused"); §3.9's "three ways" is read as side effects only. `deficiency_round_count` is untouched by re-submission and set to 3 on the rejecting round.
- **`WITHDRAW`** does not write `last_review_note`.
- **`completion_date`** accepts a full ISO instant (echoed verbatim) or `YYYY-MM-DD` (-> midnight UTC, canonical output). Generally: client-supplied datetimes echo verbatim, server-stamped ones are canonical `...mmmZ`.
- **`/_clock/set_current_utc`** echoes the client's raw string in `current_utc`.
- **`upstream_circuit_id` existence is not validated** on POST /circuits (that endpoint is absent from the §2.8 priority-6 FK list).
- **Query-filter 404s** only for `customer_id`/`notification_batch_id` on GET /notification-records; other filters silently narrow.
- **Decimal-place overruns** are `ERR_INVALID_REQUEST` (400).
- **Hardened-mileage ledger is derived from project rows** on every recompute rather than incrementally accumulated, which guarantees the §2.11 C15 identity across completion/withdrawal pairs.
- **FPI writes bump the circuit version only when** the posture or either `latest_forecast_*` field actually changes.
- **`cancel()` runs the full metrics refresh** (not just count recomputation) for SCOPED/ARMED cancels; the DRAFT edge is deliberately excluded since no scope rows exist.

**Orchestrator note on Step 5/6 launch:** the two Agent calls landed in consecutive assistant messages rather than one, so they were not launched in the same tool block. Physical isolation nonetheless held: `test_suite/` did not exist on disk at the moment the Step 6 agent started (first directory listing 4 minutes in showed only `test_helpers/` and `workspace/implementation/`), and the Step 6 prompt carried an explicit hard constraint forbidding any read of `test_suite/`, `test_helpers/`, or either design yaml. Step 6 reported building solely from INSTRUCTION.md + SCAFFOLD.yaml + PRD.md.

## Step 7: Run tests and iterate — 2026-09-03T04:58:00.000Z

Clean 8-round parallel sweep. Exiting.

## Summary

**Iterations run:** 2 (sweep 1 -> diagnose/fix -> sweep 2 green).

**Sweep 1:** 144/151 in all 8 rounds — 7 failures, byte-identical across every round. Zero flakiness, so no load-induced noise to chase; every failure was a real, deterministic defect.

**Sweep 2 (final):** 8/8 rounds `passed=151 total=151 failed=0 errors=0 skipped=0`, ~291s each. Files on disk at `workspace/implementation/results.{1..8}.json`.

### Tests deleted
None. All 7 failures traced to test-artifact bugs, not to PRD-silent assertions. Two individual *assertions* were dropped under STEP 1c partial-coverage handling (below).

### Fixes applied to `test_helpers/`
- **`test_helpers/fixtures.py`** — the nine PSPS-event lifecycle builders (`build_scoped_event` -> `build_closed_event`). They used the idiom `ctx = ctx or build_<predecessor>()`, which **skips** the predecessor whenever *any* ctx is supplied. Callers that jumped stages (e.g. `build_advance_dispatched_event(feeder_chain_ctx)`, `build_closed_event(feeder_chain_ctx)`) therefore landed on `KeyError: 'event_id'` — one upstream fixture bug masquerading as 3 independent implementation bugs. Each builder now unconditionally asks its predecessor to guarantee the preceding stage and returns early if the stage it owns has already landed, so walking the ladder explicitly and jumping straight to a stage produce the same world. Added `_event_reached()` / `_SCOPE_STATUS_RANK` for the stage check; it re-reads the event from the server rather than trusting `ctx["event"]`, which goes stale when a caller advances the event by other means (center activation, scope exclusion).

### Fixes applied to `test_suite/`
- **`test_11_state_machines.py`** (2 tests: `test_the_third_deficiency_...`, `test_a_cleared_review_track_...`) — referenced `ReviewDecision.DEFICIENT` / `ReviewDecision.CLEAR`, but `ReviewDecision` is the *mitigation-project* enum (`APPROVE`/`REQUEST_REVISION`/`WITHDRAW`). PRD §3.9 gives plan-filing review decisions as `CLEAR` or `DEFICIENT`, and `test_helpers/types.py` already carries the correct `FilingDecision` enum, used correctly by test_03 and test_16. Fixed the enum-class reference (import + 5 call sites); the asserted PRD rule is unchanged.
- **`test_10_entities.py`** (2 tests) — `assert_integer` was demanding JSON integer type for `equipment_condition_index` and `elevation_ft`. PRD §2.6 gives an *explicit enumeration* of the integer quantities and neither field appears in it; §3.1 calls the former "an asset-health score from 0 through 100 inclusive" and §3.2 fixes the latter only as a value "between -300 and 15,000 feet". A PRD-faithful implementer treating these as decimal arithmetic inputs (§3.2 subtracts `equipment_condition_index` from 100) legitimately serialises `55.0` — two divergent faithful readings exist, so the type claim fails unique derivability. Per STEP 1c the covered assertion (the stored value round-trips) was kept and only the uncovered type claim dropped, matching the idiom the same test already uses for `representativeness_weight`. Rationale is recorded in inline comments.

### Fixes applied to `implementation/`
**None.** No PRD-required check was removed or weakened, and no endpoint, field, or side effect was added. All 7 failures were test-artifact defects; the implementation was already faithful on every one.

**Orchestrator independent verification:** `ls` confirms all 8 `workspace/implementation/results.{1..8}.json` exist (46 KB each, written 04:44); parsing each with `json.load` prints `passed=151 total=151 failed=0 errors=0 skipped=0` for every round. The clean sweep is real, not a subagent claim.

**Step 8 skip decision:** NOT skipped. Step 7 applied 0 `implementation/` fixes but non-zero test-artifact changes (1 `test_helpers/` fixture-ladder repair, 2 `test_suite/` enum-reference fixes, 2 dropped type assertions under STEP 1c). The two dropped assertions are exactly the PRD-silence signal Step 8 exists to patch — PRD §2.6 does not enumerate `equipment_condition_index` / `elevation_ft` among the integer quantities while the implementation makes a concrete serialisation choice — so Step 8 runs.

## Step 8: Finalize PRD — 2026-09-03T05:01:00.000Z

Done. Only one of the three Step 7 items was a genuine PRD silence; the other two were pure test artifacts already fully determined by PRD prose.

## Line counts
- `PRD.md`: 462 lines
- `PRD_FINALIZED.md`: 463 lines (+1 line, **+0.22%**)

## Changes
- **§2.6 Numeric Precision and Rounding Discipline** — *insert* — new bullet after the integer-quantities bullet pinning that `equipment_condition_index` and `elevation_ft` are **not** integer quantities: each accepts any decimal number inside its declared range with no decimal-place cap, and each is carried/echoed as a decimal value (a supplied `55` reads back as `55.0`) — `implementation/routes/circuits.py:53`, `implementation/routes/weather.py:38`, `implementation/validation.py:118-152` (`Body.number` returns `Decimal`), `implementation/response.py:18-22` (`Decimal` -> `float` on serialisation).

## Items deliberately NOT patched
- **`test_helpers/fixtures.py` ladder bug** — the `ctx = ctx or build_<predecessor>()` idiom was a fixture defect only. The staleness the fix works around (center activation / scope exclusion bumping the event) is already normative PRD text: §3.6 states activation "increments both each site's `version` and the event's `version` by one". No silence.
- **`test_11_state_machines.py` `ReviewDecision` -> `FilingDecision`** — PRD §3.9 already spells out plan-filing decisions as `CLEAR` or `DEFICIENT`, the `ERR_REVIEW_TRACK_ALREADY_DECIDED` gate, the third-deficiency `REJECTED` transition with `deficiency_round_count` set to 3, and the second-clearance SoD gate. Implementation matches; the test simply referenced the mitigation-project enum. No silence.

## Pre-edit search log

**Edit 1 — §2.6 numeric-type bullet**
- **(a) Subject:** the JSON numeric type and accepted precision of `equipment_condition_index` and `elevation_ft` — i.e. every place either field is validated, stored, mutated, read, or serialised.
- **(b) Impl paths enumerated:** exhaustive `grep -rn` for both identifiers across `implementation/**/*.py`. Total hit set: `routes/circuits.py:53` (input via `body.number(minimum=0, maximum=100)`, no `max_decimals`), `routes/circuits.py:70` (write on registration), `db.py:118` (`circuit_out` echo), `services/calc.py:281` (`Decimal("100") - D(circuit["equipment_condition_index"])` in `equipment_component`), `routes/weather.py:38` (input via `body.number(minimum=-300, maximum=15000)`, no `max_decimals`), `routes/weather.py:52` (write on station creation), `db.py:142` (`weather_station_out` echo). Additionally read `validation.py:118-152` (`Body.number` accepts `int`/`Decimal`, coerces to `Decimal`, no scale enforcement absent `max_decimals`) versus `Body.integer` (rejects non-`int`), `validation.py:44-56` (`json.loads(..., parse_float=Decimal)`), and `response.py:18-22`/`_json` (all `Decimal` values encode via `float`, so `Decimal('55')` -> `55.0`). Confirmed there is **no** update/patch endpoint or cascade that ever rewrites either field after creation, and no filter or query parameter over either — so registration/creation is the only write path and the two `*_out` serialisers the only read paths. Also grepped both names in `PRD_FINALIZED.md` (lines 135, 179, 191, 205) to confirm no other PRD passage types them as integers or fixes a scale, and confirmed §4 endpoint definitions never name them.
- **(c) Wording adjustments:** two. (i) Rejected phrasing along the lines of "stored exactly as supplied" — the `Decimal` -> `float` encoder loses trailing zeros (`55.50` reads back `55.5`), so a precision-preservation claim would have been a false universal; replaced with the weaker "carried and echoed as a decimal value". (ii) Rejected placing either field into one of §2.6's fixed-scale buckets — the impl applies no rounding or scale at all to them — so the bullet asserts only "not among the integer quantities" plus the absence of a decimal-place limit, leaving scale under-determined rather than wrongly pinned. Scoped the claim to exactly these two named fields rather than a general "quantities not listed above are decimal" rule, to avoid asserting anything about numeric fields Step 7 never exercised.

## Step 9: Complete PRD — 2026-09-03T05:29:00.000Z

`workspace/PRD_COMPLETED.md` is complete.

**Counts** — source `PRD_FINALIZED.md`: 463 lines / 108,165 chars. Completed: 463 lines / 118,125 chars (**+9,960 chars, +/-0 lines**). Every change is an in-paragraph insert or revision — no new sections, no new paragraphs, no reflow. File ends at the real §5 boundary (`| ERR_RESOURCE_CENTER_DISTRICT_MISMATCH | 422 |`), not mid-sentence. `implementation/`, `test_suite/`, `test_helpers/` were not touched.

**32 changes on 30 lines: 24 ambiguity pins, 8 mismatch revisions.**

- §2.2 — insert — ambiguity — `api_request_timestamp` is rendered from the logical clock, not wall time — `response.py:_meta`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` text is rejected with `ERR_INVALID_REQUEST` (400) — `validation.py:_query_int`
- §2.3 — insert — ambiguity — `created_at` ties break by creation sequence; list-filter FK ids need not resolve except on `GET /notification-records` — `db.py:74-81`, `routes/notifications.py:list_records`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` are stamped from the logical clock — `db.py:33-49`
- §2.5 — insert — ambiguity — `current_utc` echoes the supplied string verbatim — `routes/clock.py:19-20`
- §2.5 — insert — ambiguity — server-stamped instants render with 3 fractional digits; client-supplied ones echo verbatim — `db.py:92-99`
- §2.6 — revise — mismatch — `completed_miles` and `miles_patrolled` are stored unquantized — `services/calc.py:recompute_hardened_mileage`
- §2.6 — insert — ambiguity — the four FPI components are clamped but never rounded — `services/calc.py:compute_fpi`
- §2.8 — revise — mismatch — the terminal-event rule applies only to event-targeted endpoints — `routes/events.py:_require_state`
- §2.10 — insert — ambiguity — a row's `version` bumps at most once per request; rows created in-request stay at 1 — `db.py:33-71`
- §3.1 — insert — ambiguity — `upstream_circuit_id` is stored without FK resolution — `routes/circuits.py:upstream_circuit_id`
- §3.2 — insert — ambiguity — `VALIDATED` `effective_*` values keep full precision — `services/calc.py:compute_fpi`
- §3.3 — revise — mismatch — `latest_forecast_fpi_*` mirrors refresh even while `risk_posture` is `LOCKED` — `services/calc.py:recompute_risk_posture`
- §3.3 — insert — ambiguity — `last_review_note` is written on `APPROVE`/`REQUEST_REVISION` only — `routes/mitigation.py:154-163`
- §3.3 — insert — ambiguity — `completed_miles_delta` carries no decimal limit; `completion_date` accepts either `YYYY-MM-DD` or a full instant — `routes/mitigation.py:record_completion`
- §3.4 — insert — ambiguity — scope-determination own-state errors are raised after the version guard — `routes/events.py:determine_scope`
- §3.4 — insert — ambiguity — exclusion on a terminal event yields `ERR_EVENT_NOT_SCOPED` (no terminal check) — `routes/events.py:exclude_scope`
- §3.5 — insert — ambiguity — batch planning and dispatch never inspect `scope_status` — `routes/notifications.py:create_batch,dispatch_batch`
- §3.6 — insert — ambiguity — arm gates fire in §2.8 priority order (advance-notification -> confirmed-count -> net-benefit) — `routes/events.py:arm_event`
- §3.6 — insert — ambiguity — an empty explicit array is accepted, and activation is admitted from any non-terminal state — `routes/events.py:activate_resource_centers`
- §3.6 — revise — mismatch — explicit mode runs three separate full sweeps: ALREADY_ACTIVE -> BUFFER_CONFLICT -> DISTRICT_MISMATCH — `services/centers.py`
- §3.6 — insert — ambiguity — re-activating a demobilized site leaves the stale `demobilized_at` in place — `services/centers.py`
- §3.7 — insert — ambiguity — starting a patrol on a circuit already `PATROL_IN_PROGRESS` is a no-op that still bumps the circuit's `version` — `routes/patrol.py:start_assignment`
- §3.7 — insert — ambiguity — `miles_patrolled` carries no decimal-place limit — `routes/patrol.py:complete_assignment`
- §3.7 — insert — ambiguity — completion leaves a circuit in any other energization state untouched but still bumps its `version` — `routes/patrol.py:complete_assignment`
- §3.7 — insert — ambiguity — governing event = newest unrestored `CONFIRMED` scope row preferring a `RESTORING` event, then any live one — `services/events.py:431-450`
- §3.7 — insert — ambiguity — clearing patrol = latest `COMPLETED` by `completed_at`, then `created_at`, then sequence; none at all gives the same `ERR_IGNITION_RISK_DAMAGE_UNRESOLVED` — `routes/circuits.py:272-276`
- §3.8 — revise — mismatch — closing's own demobilization re-runs the `POST_EVENT` coverage/credit/ratio before the event goes terminal, so "freezes" is qualified — `services/events.py:376-379,407-420`
- §3.8 — revise — mismatch — cancel on `CLOSED`/`CANCELLED` gives `ERR_EVENT_TERMINAL`; only `ACTIVE`/`RESTORING` give `ERR_EVENT_NOT_CANCELLABLE` — `routes/events.py:275-280`, `services/events.py:44-50`
- §3.8 — revise — mismatch+ambiguity — cancelling from `SCOPED`/`ARMED` zeroes each row's `ignition_risk_term` and re-runs every roll-up to zero; demobilization and patrol-abort run on all three edges including `DRAFT` — `services/events.py:382-404`
- §3.9 — insert — ambiguity — `ERR_FILING_METRICS_INCOMPLETE` reads the freshly recomputed count and persists nothing; submission resets neither `deficiency_round_count` nor `last_deficiency_note` — `routes/filings.py:82-97`
- §3.9 — revise — mismatch — the filing-review SoD gate fires on the second decision of a round whether it is `CLEAR` or `DEFICIENT` (and §3.9's clear-branch sentence now cross-references it rather than owning it) — `routes/filings.py:126-132`

**Orchestrator independent verification:** `wc -l workspace/PRD_COMPLETED.md` = 463; `grep -c "^## "` = 5 (all five top-level sections intact); `tail -3` shows the final three §5 error-table rows ending at `ERR_RESOURCE_CENTER_DISTRICT_MISMATCH` — not truncated. `find test_suite test_helpers workspace/implementation -newermt "2026-09-03 04:50" -name "*.py"` returns nothing, confirming Step 9 modified no certified test or implementation file after the green sweep.

## Pipeline complete — 2026-09-03T05:31:00.000Z

All nine steps finished. Final state: 14 entities / 54 endpoints / 54 errors scaffolded; PRD 462 lines -> PRD_FINALIZED 463 -> PRD_COMPLETED 463 (+9,960 chars of ambiguity pins); 151 tests (57 depth, 94 breadth) with 0 deleted; 8/8 sweep rounds at 151/151; 0 implementation fixes required.

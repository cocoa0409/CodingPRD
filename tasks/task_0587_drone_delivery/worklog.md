# Worklog — task_0587_drone_delivery

## Step 1: Create task directory — 2026-07-11T00:00:00.000Z

Task directory `./tasks/task_0587_drone_delivery` (with `workspace/`) was pre-created and reserved by the invoker. No index scan performed.

## Step 2: Generate scaffold — 2026-07-11T00:10:00.000Z

All three artifacts are generated and the linter reports a clean run.

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     13
  §1.8 instances scanned:     19
  §1.9 instances scanned:     40
  Calls scanned (§1.8+§1.9):  630

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files written** (all under `tasks/task_0587_drone_delivery/`):
- `SCAFFOLD.yaml` — §1.0–§1.7, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Counts (Expert band):**
| Table | Count |
|---|---|
| Entities | 13 |
| State machines | 8 (Flight declared twice — parallel `ops_state` × `clearance_state` dimensions) |
| Calculations | 13 |
| Validations | 25 (priority-ordered 1–25) |
| Endpoints | 52 |
| Errors | 44 |
| Roles | 5 |
| Concurrency rules (OCC) | 2 |
| §1.8 difficulty instances | 19 (9 rules × ≥2; `combinatorial_formula` has 3, one per mode a/b/c) |
| §1.9 corner instances | 44 across 9 sections (4 are `excluded_because` stubs) |

**Design notes:**
- Archetype: workflow orchestration × compliance/audit; graph topology; parallel state-machine shape; segregation-of-duties role model (the FlightDirector releasing a flight must differ from the operator who filed its LAANC authorization).
- Non-linear machines on distinct entities: Flight (parallel dims), Drone and Battery (cycles), Incident (fork with disjoint side-effect sets).
- Two depth-4 cascades from different triggers: incident→drone→flight→{order, nest, auth, battery} grounding cascade, and recover→battery→retirement→drone→auto-scheduled BATTERY_SWAP log.
- Two conserved quantities: customer funds (`held_total`/`billed_total`) and physical pad slots (`Nest.reserved_pads`).
- Two overlap geometries: Nest pad holds (closed intervals, ±buffer, aggregate capacity) vs maintenance windows (half-open, zero buffer, exclusive capacity 1).
- Dual variants on different domains: Flight energy (provisional 38.6 vs actual 23.6) and Drone risk (advisory 55.0 vs blocking 70.0).
- Logical clock endpoint `POST /_clock/set_current_utc` with the mandated `2026-05-01T00:00:00Z` startup default; `POST /_laanc/decision` simulates the external airspace authority. All numeric asserts in both design files were computed from the pinned formulas and written as literals.

## Step 3: Copy shared files — 2026-07-11T13:21:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0587_drone_delivery/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-11T13:28:00.000Z

All three contracts pass. The PRD is complete at `workspace/PRD.md`.

**PRD line count:** 439 lines.

**Sections emitted:**
- §1 Introduction (3 paragraphs, framed around the three-ledger reconciliation problem and the conservation invariant)
- §2 Global Specifications — 11 subsections, domain-derived: 2.1 Flight Crew Identity & RBAC, 2.2 API Response Structure (verbatim), 2.3 Pagination, 2.4 The Logical Mission Clock, 2.5 Resource Identity/Audit/Versioning, 2.6 Path Resolution & Referential Integrity, 2.7 Flat-Earth Geodesy, 2.8 Numeric Precision & Rounding Discipline, 2.9 Stale-Read Protection (OCC), 2.10 Two Conserved Quantities, 2.11 The Order of Rejection
- §3 Business Logic — 10 subsections: geography/nests/restrictions/weather, fleet & airworthiness risk, order intake & quoting, dispatch (selector + pad hold + provisional energy), regulatory track (file/LAANC/release), launch joint gate, sortie + abort unwind, incidents & grounding cascade, maintenance work orders, read-back surface
- §4 Endpoint table (4 columns, 53 rows)
- §5 Error catalogue (2 columns, 44 rows)

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 86 required, 86 present, 0 missing
- endpoints[].request_body: 57 required, 57 present, 0 missing
- endpoints[].query_params: 17 required, 17 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 25 checked, 25 expressed in prose (§2.11 emits the full 1–25 ordering), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (dispatch/expected_order_version/ERR_STALE_ORDER_VERSION/412; maintenance-log create/expected_drone_version/ERR_STALE_DRONE_VERSION/412), 0 missing
- state_machines[].transitions: 42 checked (Order 6, Flight ops_state 9, Flight clearance_state 4, AirspaceAuthorization 4, Drone 9, Battery 5, Incident 4, MaintenanceLog 1), 42 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed as prose with all constants embedded, 0 missing
- validations[] conditions: 25 checked, 25 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all checked and expressed; multi-endpoint scopes enumerated in full, 0 missing
- entities[].fields[] structured content: 86 checked, all types/defaults/enum ranges/immutability reconstructible from prose, 0 missing
- sibling-branch symmetry: 4 groups checked, 4 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 684
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 matches the canonical response-structure doc byte-for-byte; all 5 role names and all 44 error IDs appear in prose; no PRD content was drawn from the two withheld design files.

Flagged subtleties: the fee's pinned rounding order (round each component to 2 dp before summing, then apply the priority multiplier, then round again) and the asymmetric interval geometry (nest pad holds closed-interval with aggregate capacity `pad_count`; maintenance windows half-open with capacity 1).

## Step 5: Generate unit tests — 2026-07-11T14:10:00.000Z

All 78 tests collect cleanly. Test infrastructure is complete.

**Files written**

`test_helpers/` (Stage 1)
- `types.py` — 16 status enums + entity TypedDicts. `WeatherObservation` / `DeliveryDrop` correctly omit `updated_at`/`version` (PRD §2.5 immutables).
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per PRD endpoint (46 methods incl. `/_clock/set_current_utc` and `/_laanc/decision`).
- `api_errors.py` — 44-entry `ApiErrorId` enum + HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions, `assert_instant` (ISO-instant comparison, not string equality), and precision-tight helpers `assert_money`/`assert_pct`/`assert_km`/`assert_hours` whose tolerances reject un-rounded values; plus the two conserved-quantity invariant checkers.
- `factories.py`, `constants.py`, `test_users.py` (per-instance `make_customer_headers(customer_id)` for the entity-backed `Customer` role), `fixtures.py` (~460 lines: 40 single-step wrappers + `setup_world` → `setup_planned/filed/approved/cleared/launched/dropping/returning/recovered_flight` → `setup_retired_pack_and_grounded_drone`, `setup_grounding_cascade`), `__init__.py` barrel.

`test_suite/` (Stage 2) — `conftest.py` + 9 files, **78 tests**:
`test_01_order_intake_and_quoting` (14) · `test_02_fleet_and_airworthiness` (5) · `test_03_dispatch_and_selector` (10) · `test_04_regulatory_track` (6) · `test_05_launch_gate` (10) · `test_06_sortie_and_recovery_cascade` (8) · `test_07_abort_and_conservation` (5) · `test_08_incidents_and_maintenance` (12) · `test_09_access_control` (4).

**Coverage vs. the design indices**

- **Queue A (Difficulty): 19/19 instances, exactly 2 tests each = 38 tests.** No shortfalls.
- **Queue B (Corner): 40/40 non-stub instances, 1 test each = 40 tests.** No shortfalls.
- **Skipped: 0 instances.** Every non-stub instance passed the PRD-first two-condition filter — this PRD verbatim-covers and uniquely-derives every asserted rule, including the two priority-ordering conflicts (PRD §2.11 enumerates the rejection order explicitly, so `ERR_FLIGHT_NOT_PLANNED` > `ERR_DRONE_GROUNDED` and `ERR_WEATHER_NO_GO` > `ERR_INSUFFICIENT_BATTERY` are both contract-pinned, not inferred).
- **4 `excluded_because:` stubs verified, not translated:** `priority_weather_over_energy_on_launch`, `priority_state_over_grounded_on_launch`, `pads_full_error_trigger`, `no_eligible_drone_error_trigger` — all four `difficulty_instance` cross-references resolve to real §1.8 instances that own the assertion.

**Verification run**

- 78/78 test functions carry exactly one `Design:` tag; 0 untagged, 0 dual-tagged, 0 tags pointing at non-existent instances.
- **All 163 quoted PRD sentences survive a whitespace-normalized literal grep of `workspace/PRD.md`** (C1/C2/C3 clean).
- No `pytest.mark.skip` / `skipif` / `xfail`; no "scaffold" / `§1.x` / "Table N" leakage in emitted code.
- Every literal expected value independently recomputed from the PRD formulas with `ROUND_HALF_UP` (fees 8.96 / 10.06 / 8.24 / 8.40, energies 38.6 / 46.8 / 23.6 / 13.3 / 3.0, charges 76.4 / 86.7 / 97.0, health 66.7 / 0.0, hours 0.19 / 0.09, risk 55.0 vs 70.0) — all match.
- `pytest --collect-only`: 78 collected, 0 errors; `test_helpers` imports cleanly against the installed framework.

Note for the implementation side: timestamp assertions (`eta_recovery_at`, `pad_hold_start/end`, `completed_at`, `scheduled_start/end`) compare **instants**, not strings, so either `...T09:10:00Z` or `...T09:10:00.000Z` serialization passes.

## Step 6: Generate implementation — 2026-07-11T14:30:00.000Z

Orchestrator note: Steps 5 and 6 ran sequentially, not concurrently (orchestrator sent the Agent calls in separate messages). `test_suite/`/`test_helpers/` therefore existed on disk when Step 6 started; test-blindness was enforced by an explicit hard constraint in the Step 6 prompt instead of by physical absence.

Implementation complete and verified end-to-end.

**Files written** (all under `workspace/implementation/`):
- `start.sh` (guarded `pip install`, `exec python3 app.py`), `requirements.txt`
- `app.py` — blueprint registration, envelope error handlers, WSGI lock so every request is atomic
- `db.py` — in-memory dicts + logical clock (starts `2026-05-01T00:00:00Z`, never wall-clock); **no seeding anywhere**
- `errors.py`, `response.py`, `timeutil.py`, `auth.py`, `validation.py`, `calc.py`, `serializers.py`
- `services/flight_service.py` — the single unwind path (recover / abort / grounding cascade)
- `routes/` — `admin.py`, `geography.py`, `fleet.py`, `orders.py`, `flights.py`, `incidents.py`

**52 endpoints** implemented — exactly the PRD §4 table.

**Verified by live scenario**: Fee/surcharge pinned rounding (2.377 km, 2000 g, URGENT → 7.83 / 0.39 / 8.22), provisional vs actual energy (26.8 vs 11.8 on the same route — differ by the 15.0 reserve), ETA ceil + pad hold (`00:08`, `00:03`–`00:18`), `auth_code` = `LAANC-20260501000000`, segregation of duties, weather/geofence/window/battery launch gates, full grounding cascade (order → QUOTED, held → 0, pads → 0, REPAIR log, incident CLOSED on completion), risk scores (30.0 with no pack → 0.0 after install → 30.2 blocking / 0.2 advisory after a CRITICAL incident), OCC on both order and drone, half-open maintenance adjacency vs. overlap.

**PRD ambiguities resolved**
1. **OCC vs. state precedence on dispatch.** §2.11 puts the version check (8) before the state check (9); §3.4's prose narrates `ERR_ORDER_NOT_QUOTED` first. Followed §2.11 (the explicitly normative "Order of Rejection"). Re-dispatching an `ASSIGNED` order with a stale version returns **412 `ERR_STALE_ORDER_VERSION`**.
2. **Pad gate ordering vs. the selector.** §2.11 ranks `ERR_NEST_PADS_FULL` (22) before `ERR_NO_ELIGIBLE_DRONE` (25), but the candidate pad-hold interval derives from an *airframe-specific* ETA that only exists after the selector runs. Resolution: the winner's ETA defines the hold when a candidate exists; when the candidate set is empty the pad gate still applies, using the ETA of the longest-registered airframe based at that nest.
3. **Re-filing an already-`FILED` flight.** No error code named. Enforced `clearance_state == UNFILED` with **`ERR_FLIGHT_NOT_CLEARED`** (409).
4. **`created_at` source.** Taken from the logical clock (§2.4 forbids wall-clock reads; `auth_code` mints from `created_at`). A hidden monotonic insertion sequence breaks `created_at` ties for the selector's third ranking key and the default `created_at ASC` list order.
5. **Computed fields are derived on read, never stored** — `reserved_pads`, `held_total`, `billed_total`, both risk scores, `health_pct`.
6. **404s for the two immutable entities.** `WeatherObservation`/`DeliveryDrop` have no not-found code in the catalogue; invented `ERR_WEATHER_OBSERVATION_NOT_FOUND` / `ERR_DELIVERY_DROP_NOT_FOUND`, both HTTP 404.
7. **`target_charge_pct`** isn't in §2.11's numeric list; validated to `[0, 100]` per the `Battery.charge_pct` entity constraint.

## Step 7: Run tests and iterate — 2026-07-11T14:40:00.000Z

The task was already green. The baseline sweep passed on the first attempt, so the diagnostic protocol never triggered.

**Iterations run:** 1 (the baseline 8-round parallel sweep, which was already clean — no fix loop was needed).

**Sweep result:** all 8 concurrent rounds returned `passed == total` = **78/78**, with `failed: 0`, `errors: 0`, `skipped: 0`. Round duration ~50s each under `--isolation per-test-server`.

```
round 1: 78/78    round 5: 78/78
round 2: 78/78    round 6: 78/78
round 3: 78/78    round 7: 78/78
round 4: 78/78    round 8: 78/78
```

**Verification that the green is real, not vacuous:**
- `grep -rn "skip\|xfail"` over `test_suite/` and `test_helpers/` returns **zero hits** — nothing is being suppressed with skip/xfail markers.
- Static count of `def test_` across the 9 suite files is **78**, exactly matching the 78 tests the runner collected and recorded. No test is silently uncollected or filtered out.
- Per-test status breakdown from `results.1.json` is `Counter({'passed': 78})` — every recorded test genuinely executed and passed.
- Zero cross-round variance: the union of failing tests across all 8 rounds is empty, so there is no flakiness signal (no timing-sensitive race, fixture-ordering luck, or port collision surfaced by the 8× concurrent load).

**Tests deleted:** none. No test failed, so no PRD-coverage (STEP 1a) or unique-derivability (STEP 1b) analysis was warranted.

**Fixes applied to `test_helpers/`:** none.
**Fixes applied to `test_suite/`:** none.
**Fixes applied to `implementation/`:** none.

Caveat flagged by the subagent: because nothing failed, it did not audit the 78 green tests against `PRD.md` for fairness. The diagnostic protocol only inspects failing tests, so an unfair-but-passing test would not have been caught here.

**Housekeeping:** subagent removed the 8 `results.*.json` sweep artifacts; orchestrator regenerated them with a final confirmation sweep.

## Step 8: Finalize PRD — SKIPPED — 2026-07-11T14:41:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits at the sites the tests exercised. No `PRD_FINALIZED.md` produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-07-11T15:05:00.000Z

`PRD_COMPLETED.md` written from `PRD.md` (Step 8 skipped, so no `PRD_FINALIZED.md` input).

**Line counts / delta:** PRD.md 438 lines / 68,428 chars → PRD_COMPLETED.md 444 lines / 74,728 chars (+6 lines, +6,300 chars). 20 diff hunks; no sections added, no headings changed. The +6 lines are two new §5 table rows, one new §2.10 lead paragraph, and one new §3.4 paragraph (each with its blank line); everything else is in-paragraph.

**Counts:** 21 ambiguity-pins, 4 mismatch-revisions.

### Changes

- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time — `implementation/response.py:21`
- §2.3 — insert — ambiguity — default list ordering breaks `created_at` ties with a hidden monotonic insertion sequence (never exposed) — `implementation/db.py:106-108`
- §2.5 — insert — ambiguity — `created_at` / `updated_at` are sourced from the logical clock, so same-instant creations collide exactly — `implementation/db.py:86-103`
- §2.6 — revise — ambiguity — not-found family extended with `ERR_WEATHER_OBSERVATION_NOT_FOUND` / `ERR_DELIVERY_DROP_NOT_FOUND` for the two immutable entities' GET-by-id routes — `implementation/errors.py:88-89`
- §2.10 — insert — ambiguity — `reserved_pads`, `held_total`, `billed_total` (with both risk scores and `health_pct`) are computed on read, never stored — `implementation/services/flight_service.py:19-48`, `implementation/serializers.py:48,91-92`
- §2.11 step 3 — insert — ambiguity — `target_charge_pct` ∈ [0,100] and `actual_route_km` ≥ 0 added to the numeric-constraint list — `implementation/routes/fleet.py:147`, `implementation/routes/flights.py:282,296`
- §2.11 step 3 — insert — ambiguity — enumerates the strictly-integer body fields; a fractional value in any of them is 422 — `implementation/validation.py:63-71`
- §3.1 — insert — ambiguity — service-area suspension is unconditional/idempotent and still bumps `version` — `implementation/routes/geography.py:45-51`
- §3.1 — insert — ambiguity — geofence lift is likewise unconditional/idempotent — `implementation/routes/geography.py:153-159`
- §3.1 — revise — ambiguity — latest-observation selection adds insertion-sequence as the final tiebreak after `observed_at`, `created_at` — `implementation/calc.py:199`
- §3.2 — revise — ambiguity — `target_charge_pct` is required and validated to [0, 100] → 422 — `implementation/routes/fleet.py:147`
- §3.2 — insert — ambiguity — install-battery mutates only the drone; no battery record's `state`/`version`/`updated_at` changes on install or un-link — `implementation/routes/fleet.py:94-96`
- §3.2 — revise — ambiguity — both risk scores are computed fields per §2.10, never stored — `implementation/serializers.py:65-66`
- §3.4 — revise — **mismatch** — dispatch checks `ERR_STALE_ORDER_VERSION` (412) *before* `ERR_ORDER_NOT_QUOTED` (409), per §2.11's numbered order; the old prose had them reversed — `implementation/routes/orders.py:154-157`
- §3.4 — insert — ambiguity — pad-full gate is evaluated even when the candidate set is empty, using the ETA of the longest-registered airframe based at that nest (`created_at`, then insertion seq, regardless of eligibility), preserving `ERR_NEST_PADS_FULL` before `ERR_NO_ELIGIBLE_DRONE`; the gate is skipped only when the nest hosts no airframes at all — `implementation/routes/orders.py:208-221`
- §3.4 — revise — ambiguity — selector's third ranking key (`created_at`) gets a fourth, insertion-sequence tiebreak — `implementation/routes/orders.py:199-206`
- §3.5 — revise — ambiguity — filing checks `ops_state` first, then rejects any `clearance_state` other than `UNFILED` (i.e. re-filing a `FILED` flight) with `ERR_FLIGHT_NOT_CLEARED` (409); a sortie never carries two authorizations — `implementation/routes/flights.py:96-99`
- §3.5 — revise — ambiguity — LAANC `outcome` is exactly `APPROVED` | `DENIED`, else 422 — `implementation/routes/admin.py:29`
- §3.6 — revise — **mismatch** — launch inspects only `GROUNDED`; the old prose implied a `RESERVED`-status gate that the impl does not have — `implementation/routes/flights.py:199-200`
- §3.7 — revise — ambiguity — recovery's `actual_route_km` is required, non-negative, and rounded half up to 3 dp on store — `implementation/routes/flights.py:282`, `implementation/services/flight_service.py:124`
- §3.7 — revise — **mismatch** — `abort_reason`: every endpoint-initiated abort is `OPERATOR` regardless of caller/motive, the cascade is the only writer of `DRONE_GROUNDED`, and `WEATHER` is never produced (no weather-stand-down endpoint exists) — `implementation/routes/flights.py:302`, `implementation/services/flight_service.py:190`
- §3.7 — insert — ambiguity — a `PLANNED` abort leaves `actual_route_km` / `actual_energy_pct` null even if a route is reported, and leaves a non-`RESERVED` drone's status and `version` untouched — `implementation/services/flight_service.py:145,165-168`
- §3.7 — revise — **mismatch** — a `LAUNCHED`-and-later abort uses 0.0 whenever *no route is reported*, including a human abort that omits the optional field (old prose restricted 0.0 to system-triggered aborts) — `implementation/services/flight_service.py:146`
- §3.9 — insert — ambiguity — completion does not require a `GROUNDED` airframe; on a non-grounded drone the hour reset and `version` bump still happen but `status` is left alone — `implementation/routes/incidents.py:192-195`
- §5 — insert — ambiguity — added `ERR_WEATHER_OBSERVATION_NOT_FOUND` (404) and `ERR_DELIVERY_DROP_NOT_FOUND` (404) rows — `implementation/errors.py:60-61`

Two impl fallbacks deliberately left out as framework noise rather than PRD behavior: `ERR_NOT_FOUND` (404, unrouted path) and `ERR_INTERNAL` (`app.py:48-58`). Neither is reachable through any documented endpoint.

## Final confirmation sweep — 2026-07-11T15:15:00.000Z

Orchestrator re-ran the 8-round parallel sweep after Step 9 to regenerate the `results.{1..8}.json` deliverables that the Step 7 subagent had cleaned up. All 8 rounds green:

```
round 1: 78/78  failed=0 errors=0 skipped=0    round 5: 78/78  failed=0 errors=0 skipped=0
round 2: 78/78  failed=0 errors=0 skipped=0    round 6: 78/78  failed=0 errors=0 skipped=0
round 3: 78/78  failed=0 errors=0 skipped=0    round 7: 78/78  failed=0 errors=0 skipped=0
round 4: 78/78  failed=0 errors=0 skipped=0    round 8: 78/78  failed=0 errors=0 skipped=0
```

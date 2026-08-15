# Worklog — task_1447_indoor_vertical_farm_production

## Step 1: Create Task Directory — 2026-08-13T08:11:00.000Z

Task directory `tasks/task_1447_indoor_vertical_farm_production/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per invocation instructions. No index scan performed; no other task_* directory touched.

## Step 3: Copy Shared Files — 2026-08-13T08:14:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1447_indoor_vertical_farm_production/workspace/INSTRUCTION.md`.

## Step 2: Generate Scaffold — 2026-08-13T10:15:00.000Z

All three artifacts are generated and clean. Final report:

## Summary

**Output files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_1447_indoor_vertical_farm_production/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: **17** (Crop, GrowRecipe, WaterLoop, Rack, Tower, GrowBatch, TowerAllocation, SanitationCycle, RetailContract, Shipment, ShipmentLine, Worker, LaborShift, ShiftAssignment, EnergyMeterReading, FailureReport, ReplantRequest)
- State machines: **16** entries covering 13 entities — including GrowBatch with two parallel dimensions (production_status × safety_status), cyclic WaterLoop posture, revert-loop RetailContract
- Calculations: **13** (dual-variant energy cost-per-pound, provisional/final fill rate, escalating shortfall penalty, per-line-round-then-sum invoicing, nested min/max harvest labor cost, frozen-order replant priority scoring, best-fit tower selector, sanitation schedule, ISO-week labor hours, dock-day quota, pack recency)
- Endpoints: **90** (flat topology under `/farm`, incl. `POST /farm/_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default)
- Errors: **50**; Roles: **7** (segregation-of-duties model; Worker is entity_backed)
- Concurrency rules (OCC): **3** — recipe-activate/Crop, shipment-create/RetailContract, assignment-create/LaborShift; OCC is pinned as evaluated after all other validation tiers
- §1.8 difficulty instances: **28** (every rule ≥2; combinatorial_formula has 3 covering modes a/b/c; boundary_precision 4; cross_entity 4)
- §1.9 corner instances: **86** (73 active + 13 `excluded_because` stubs) across all 9 taxonomy sections
- Lint: `VERDICT: clean lint` — 1,476 §1.8/§1.9 calls scanned, zero violations; all FKs reverse-reachable

**Notable design decisions:**
- Three genuinely different interval semantics for Rule 8: half-open tower allocations (adjacency allowed), closed sanitation windows + 4h buffer, and aggregate-count dock-day quota
- Depth-4 cascade (sanitation FAIL → loop hold → rack hold → batch quarantine → shipment safety-block) with a full compensation path (retest PASS lifts quarantine only to PENDING, forcing a fresh QA release — this required adding PACKED to the safety-release production gate)
- All asserted numbers were computed by executing the formulas (e.g., provisional 177.41 vs actual 13187.15 cents/lb; invoice 8882 vs sum-first 8881; fill 0.9800-exactly pays 0 vs 0.9780 pays 1650; escalation chain 75000/93750/18750/2063)
- Three SoD checks: harvester≠releaser, sanitation retest recorder≠parent recorder, Worker self-confirm
- Removed two initially-designed dead rules during self-audit (shelf-life pack gate that could never fire given the stricter same-day rule, and an unreachable ERR_BATCH_NOT_FAILED); added ERR_SHIPMENT_WINDOW_CLOSED to the catalog after the reference audit caught it missing
- During drafting I replayed every chain against §1.2/§1.4 and fixed 5 chain bugs (harvest-ready earliness vs clock position, missing confirm-pack before ship-safety conflict, RESERVED-shipment ship ordering, RELEASED→CONDEMNED gap, weekly-hours week basis)

## Step 4: Generate PRD — 2026-08-13T10:46:00.000Z

PRD generated and all three hard contracts pass.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1447_indoor_vertical_farm_production/workspace/PRD.md` — 390 lines. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

### Section list
- **§1 Introduction** (2 paragraphs, business-context angle)
- **§2 Global Specifications** — 2.1 RBAC (7 roles, `X-User-ID`/`X-User-Role`, per-role identity prose incl. entity-backed `Worker`); 2.2 API Response Structure (verified **byte-identical** to the canonical verbatim block); 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending); 2.4 Logical Farm Clock (startup default `2026-08-01T00:00:00Z`, posture re-derivation); 2.5 Common Resource Properties (UUID/timestamps/version; `EnergyMeterReading` explicitly `id`+`created_at` only); 2.6 Interval Semantics (half-open vs closed+4h buffer vs inclusive dock end); 2.7 Precision & Rounding; 2.8 Cascades; 2.9 OCC (3 rules, `ERR_STALE_VERSION` 412, evaluated-last rule); 2.10 Validation Order (all 12 priority tiers in explicit order); 2.11 Nested Retrieval (left-to-right, body FK list)
- **§3 Business Logic** (8 subsections, scattered): 3.1 Crops & Recipes · 3.2 Loops/Racks/Towers · 3.3 Batch Seeding→Harvest · 3.4 Sanitation/Quarantine/Release · 3.5 Contracts/Shipments/Settlement · 3.6 Failure & Replant · 3.7 Labor · 3.8 Energy & Cost-per-Pound
- **§4 Endpoint table** — 90 rows, 4 columns only
- **§5 Error catalogue** — 50 rows, 2 columns only, statuses verified against scaffold (400/403/404/409/412/422 mapping)

### Coverage audit
- **Entities (17/17):** every one of the 119 entity fields appears in backticks in narrative (initial pass missed 13 status/FK names — `allocation_status`, `assignment_status`, `contract_status`, `failure_id`, `line_status`, `rack_id`, `replant_status`, `report_status`, `shift_id`, `shift_status`, `shipment_id`, `shipment_status`, `tower_id` — repaired in natural homes, second pass clean)
- **Endpoints (90/90):** all paths in §4 table; all request-body/query/path identifiers covered (134/134 required names present, 0 missing); endpoint side effects narrated in §3
- **State machines (16/16):** every transition's from/to states, preconditions with error IDs, and side effects expressed — incl. dual GrowBatch dimensions (production + safety), full WaterLoop posture derivation order, and all cascade chains (harvest/fail/cull 3-link, sanitation FAIL 4-link, condemn, contract-terminate 3-link, settle-week expiry sweep)
- **Calculations (13/13):** all formulas in precise prose with constants embedded — germination tiers (95.0/85.0/75.0), stress cap 5, harvest-ready 48h, sanitation 168h/4h buffer/2–12h window/30-min early start, 72h pack recency (strictly-greater fails, exactly-72h passes), dock quota 3 (aggregate semantics), provisional vs actual energy cost (0.6 kW, 11¢/kWh, 500 kW tier break at 900/1400¢), provisional vs final fill rate (4dp), penalty with 1.25 escalation and strict-inequality trigger, per-line-round-then-sum invoicing, labor cost (60/40/25 lb/h, 8h shifts, 1.5× OT, ceil), worker weekly hours (40.0 overtime boundary, 48.00 hard cap strictly-above rule), frozen replant priority score (6-step pinned order), best-fit defragmentation tower selector
- **Concurrency rules (3/3):** `expected_crop_version`, `expected_contract_version`, `expected_labor_shift_version` — each with parent entity, mismatch rejection `ERR_STALE_VERSION` (412), and the evaluated-after-all-other-tiers rule
- **Errors (50/50):** every ID appears in §2/§3 near its trigger condition; §5 statuses match the catalog exactly
- **Roles (7/7):** exact spellings, identity semantics (6 opaque, `Worker` entity-backed), SoD rules placed at safety-release, sanitation retest, and worker confirm

### Hard Contract Reports
```
Field coverage check:
- entities[].fields: 119 required, 119 present, 0 missing
- endpoints[].request_body/input: 90 required, 90 present, 0 missing
- endpoints[].query_params + path_params: all present (query params coincide with entity fields; id/assignment_id present), 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 12 checked, 12 expressed in ordered §2.10 prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write endpoint + expected_<parent>_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 16 machines / all transitions checked, fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed (constants + precision + evaluation order), 0 missing
- validations[] conditions: 12 tiers checked, all error_ids matchable in prose, 0 missing
- endpoints[].side_effects / applies_to: 90 checked, expressed in §2/§3 narratives, 0 missing
- entities[].fields[] structured content: defaults/initials/enums/precision reconstructible from prose, 0 missing
- sibling-branch symmetry: germination tiers, PASSED/FAILED, RELEASED/CONDEMNED, PROVISIONAL/ACTUAL, PACKED/SHORTED all rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 663
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Step 6: Generate Implementation — 2026-08-13T11:20:00.000Z

All checks pass. The implementation is complete. Here is the summary.

## Summary

Complete Python + Flask implementation generated at `/home/ubuntu/github/CodingPRD/tasks/task_1447_indoor_vertical_farm_production/workspace/implementation/`.

### File list (3,713 lines total)
| File | Lines |
|---|---|
| `start.sh` (exec'd launcher, guarded pip install) | 10 |
| `requirements.txt` | 1 |
| `app.py` (entry, blueprints, error handlers) | 62 |
| `db.py` (in-memory store + logical clock default `2026-08-01T00:00:00Z`) | 29 |
| `errors.py` (all 50 error IDs with HTTP statuses) | 72 |
| `middleware.py` (X-User-ID / X-User-Role auth, 7 roles) | 33 |
| `response.py` (envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in meta) | 65 |
| `util.py` (ISO-8601 parse/fmt 3-fractional-digits, Decimal helpers, body validation, limit/offset pagination) | 199 |
| `services/core.py` (constants, entity helpers, derived posture/tower status, cascade machinery, 17 serializers) | 648 |
| `services/calculations.py` (all 13 calculations) | 331 |
| `routes/catalog.py` (clock, crops, recipes, water-loops, racks, towers) | 382 |
| `routes/batches.py` (14 batch endpoints) | 479 |
| `routes/sanitation.py` | 212 |
| `routes/contracts.py` (incl. settle-week) | 238 |
| `routes/shipments.py` | 325 |
| `routes/labor.py` (workers, shifts, assignments) | 307 |
| `routes/energy.py` | 83 |
| `routes/failures.py` (failure reports + replant requests) | 237 |

### Endpoint coverage vs PRD §4
All 90 endpoints registered (verified by diffing Flask's URL map against the PRD §4 table: 0 missing, 0 extra). Role authorization per the PRD §4 role column is enforced on every endpoint, with the 12-tier validation order (auth → role → segregation → existence → state → posture gates → safety gates → referential → temporal → capacity → OCC → fiscal).

### Calculation / state-machine coverage
- **All 13 calculations**: projected_harvest_schedule (stress +24h, cap 5), yield_projection (95/85/75 tiers), energy_cost_per_pound (PROVISIONAL nameplate + ACTUAL tower-light-hour share allocation with tiered demand charge, 0.6kW/11c/500kW/900c/1400c constants), contract_week_fill_rate (PROVISIONAL/FINAL, 4dp), contract_shortfall_penalty (strict-below threshold, 1.25 escalation on consecutive shorts), shipment_invoice_total (per-line round-then-sum), harvest_labor_cost (60/40/25 lb/h, 8h shifts, 1.5x OT, ceil hours), replant_priority_score (frozen, pinned 6-step order, 14-day urgency), tower_allocation_selector (best-fit defrag, `(idle-needed) ASC, rack created_at ASC`, tower_index ASC), sanitation_schedule (posture derivation precedence IN_PROGRESS > HOLD-failed > DUE > IN_SERVICE, 168h interval), worker_weekly_hours (ISO Mon-Sun weeks, 40h OT, 48h hard cap strictly-above), dock_day_capacity (aggregate quota 3), pack_recency_check (72h, exactly-72h passes).
- **All 16 state machines**: Crop, GrowRecipe (supersede + OCC), WaterLoop posture (derived), Rack, Tower (clock-dependent), GrowBatch production (10 transitions incl. 3-link release cascade), GrowBatch safety (parallel dimension, segregation of duties), TowerAllocation, SanitationCycle (start gates: posture, HARVEST_IN_FLIGHT, 30-min earliness), RetailContract (suspend/reinstate/terminate/settle completion), Shipment, ShipmentLine, LaborShift, ShiftAssignment, FailureReport, ReplantRequest.
- **Cascades**: harvest/fail/cull 3-link release (allocation→tower→rack), contract terminate (shipment→line→batch pools), sanitation FAIL 4-link (loop hold→racks hold→batch quarantine→shipment safety block), PASS restore, condemnation (line release + shipment collapse to CANCELED).
- **OCC** on the 3 declared endpoints (`expected_crop_version`, `expected_contract_version`, `expected_labor_shift_version`), evaluated last (tier 11), HTTP 412 `ERR_STALE_VERSION`.

### Boot smoke test
`bash start.sh` launches in ~1s, binds `0.0.0.0:$PORT` (default 10000), runs in foreground via `exec python3 app.py`. Two consecutive fresh-process boots verified: empty store each time (0 entities, clock at the spec default), no seeding anywhere (store populated only via API calls). A 30-assertion end-to-end lifecycle exercise passed (recipe OCC, tower overlap, germination tiers, stress cap, harvest readiness earliness, sanitation start gates, quarantine cascades, segregation of duties, same-day pack + 72h recency, contract week anchoring, shipment window/packing/invoice rounding, settle-week penalty + consecutive-short tracking, labor publish/assign/confirm/ownership, replant approve with selector, energy overlap partitions, cost-summary PROVISIONAL+ACTUAL), plus a 12-assertion envelope/RBAC edge-case suite (missing/unknown fields, invalid enums, malformed JSON, pagination meta, role restrictions).

## Step 5: Generate Unit Tests — 2026-08-13T11:46:00.000Z

Generation complete. Summary:

## Tests generated — 128 total (100% of design-index coverage)

**Queue A (Difficulty, 56 tests):** all 28 instances × exactly 2 tests each — every instance of `dual_variant_calc`, `combinatorial_formula` (3), `non_linear_state_machine` (3), `transitive_cascade` (3), `priority_pair_validation_conflict` (3), `boundary_precision_check` (4), `cross_entity_state_dependency` (4), `resource_temporal_overlap` (3), `compensating_invariant` (3) is covered. All literal expected values (177.41 / 13187.15 / 306087 / 300522 cents, 8882-cent invoice, 273000.00 / 150000.00 frozen scores, 0.9800 vs 0.9780 penalty boundary, 40/48h labor caps, 30-min early-start, 72h recency, 4h buffer) were recomputed against the PRD formulas and match.

**Queue B (Corner, 72 tests):** every non-stub instance gets exactly 1 test except one deliberate skip; all 13 `excluded_because:` stubs were verified to resolve to real difficulty instances and were not translated.

**Skipped (1, gap left as gap):**
- `Corner/entities/system_fields_input_ignored_on_create` — fails unique derivability: PRD §2.10 rejects bodies "carrying … an unknown field" while §2.5 calls `id`/`version` system-managed; a PRD-only reader could either ignore or 400 client-supplied system fields on create.

**Deliberate relaxations (documented, assertions stay PRD-derived):**
- Version literals (`== 1/2/3`) were translated to captured-relative assertions (`v_after == v_before + 1`), since PRD specifies "increments by one" but never the initial value.
- The crop-defaults test drops `created_at == 2026-08-01T00:00:00Z` (PRD never states `created_at` is stamped from the logical clock) but keeps 201/ACTIVE/UUID/ISO-8601 assertions.
- `condemned_batch_pack_rejected` setup adds a fresh PASSED sanitation cycle so only the condemnation gate can fail (PRD pins cross-tier order in §2.10 but not within-tier ordering of the three pack gates).
- `harvest_labor_cost` post-assignment value (8800) retained: the PRD formula's dependence on `headcount_assigned` is vacuous under a compute-once-at-publish reading.

## test_helpers/ (9 files)
`__init__.py` (barrel), `types.py` (17 entities; `EnergyMeterReading` correctly omits `updated_at`/`version` per PRD §2.5), `api_client.py` (one method per endpoint), `api_errors.py` (50 errors + framework registration), `assertions.py`, `factories.py`, `constants.py` (all PRD thresholds + standard clock waypoints), `test_users.py` (7 roles; `make_worker_headers(worker_id)` builder for the entity-backed Worker role; per-role `make_*` builders for SoD user-id control), `fixtures.py` (clock control, catalog/layout builders, batch lifecycle chains, the reusable `setup_packed_batch` harvest→release→pack chain with sanitation pass, contract/shipment helpers with OCC version re-reading, failure/replant and labor chains).

## Self-check results
- **Stage 1:** package imports cleanly; pyflakes clean on all modules (barrel-file re-export warnings excepted).
- **Stage 2 structural audit (scripted):** all 128 `Design:` tags resolve to real instances; zero tags point to stub instances; zero difficulty instances below 2 tests; zero non-stub corner instances missing (except the documented skip); every test docstring ends with exactly one Design line.
- **PRD citation sweep (scripted):** 199 quoted fragments across all docstrings — 100% survive literal grep of `workspace/PRD.md`.
- **No `skip`/`skipif`/`xfail` markers anywhere; `pytest --collect-only` collects 128/128.**

## Step 7: Run Tests and Iterate — 2026-08-13T12:15:00.000Z

Clean 8-round sweep achieved. Final summary:

## Summary

**Iterations run:** 2 (initial sweep: 10 deterministic failures × 8/8 rounds; post-fix sweep: 128/128 passed in all 8 rounds).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1447_indoor_vertical_farm_production/test_helpers/assertions.py` — added `validate_instant_equal(actual, expected_iso)`: compares ISO-8601 values as parsed UTC instants, not wire strings. Why: PRD §2.5 pins the three-fractional-digit rendering only for system-managed `created_at`/`updated_at` (§2.2 for `api_request_timestamp`); it is silent on the string rendering of domain instants (`projected_harvest_at`, `harvested_at`, `last_passed_at`, `next_sanitation_due_at`), so exact-string assertions on those fields were not uniquely derivable, while the instant *values* are verbatim-covered by §3.2/§3.3 (STEP 1c partial-coverage fix — value assertion kept at full exactness, format assumption dropped).

**Fixes applied to `test_suite/`:**
- `test_04_production_workflows.py` — `test_stress_extension_cap_and_projection_shift` (2 assertions), `test_safety_dimension_independent_of_production_cycle` (1), `test_harvest_mutation_visible_in_same_response_and_read` (1): switched exact timestamp-string equality to `validate_instant_equal`; added import.
- `test_05_sanitation_food_safety.py` — `test_retest_pass_closes_loop_and_resets_schedule` (2 assertions: `last_passed_at`, `next_sanitation_due_at` +168h) and `test_sanitation_due_only_strictly_after_due_instant` (1): same instant-comparison fix; added import.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1447_indoor_vertical_farm_production/workspace/implementation/services/core.py` — `batches_on_loop()`: widened from ACTIVE-allocations-only to allocations of any status. Why: PRD §3.4's quarantine cascade ("every batch occupying a tower on those racks with `production_status` in `SEEDED`…`PACKED`") explicitly lists `HARVESTED`/`PACKED` — states in which the harvest cascade has always released the batch's allocations — so "occupying" must include released allocations (scaffold design confirms: "the rack hold quarantines the PACKED GrowBatch's safety dimension"). This single root cause fixed 4 tests: `test_failed_result_quarantines_batch_and_flags_shipment`, `test_pending_after_retest_pass_blocks_ship_until_rerelease`, `test_ship_quarantine_beats_window_closed`, `test_ship_quarantined_batch_inside_window` (the latter two were cascades of the batch never entering QUARANTINED; the ship route's tier-7-before-tier-9 ordering was already correct).
- `/home/ubuntu/github/CodingPRD/tasks/task_1447_indoor_vertical_farm_production/workspace/implementation/routes/sanitation.py` — `create_cycle()`: buffer-edge comparisons changed from `<=` to strict `<` (`start < c_end + 4h and c_start - 4h < end`). Why: PRD §3.4 "respect a 4-hour buffer" — the PRD marks strictness explicitly where intended ("strictly more than 72 hours", "strictly above 48.00") and does not here, so a gap of exactly 4 hours satisfies the buffer; closed-interval window overlap (touching endpoints) remains rejected. Fixed `test_sanitation_exactly_four_hour_buffer_accepted`.

**Feedback notes for generators (no deletions, but two near-miss patterns):**
- unit-test-generator: avoid exact-string equality on non-system timestamp fields unless the PRD pins a rendering format (unique-derivability miss on wire format; the instant value was derivable).
- implementation-generator: cascade entity lookups keyed on "occupying a rack/loop" must consider released allocations, since post-harvest states (HARVESTED/PACKED) appear in PRD cascade status lists after the harvest cascade has released them.

## Step 8: Finalize PRD — 2026-08-13T12:35:00.000Z

The patch is complete and minimal. Final verification: the diff touches exactly the traced sites and nothing else.

## Summary

**Line counts / delta:** `PRD.md` 390 lines → `PRD_FINALIZED.md` 392 lines (+2 lines, +0.51%). File: `/home/ubuntu/github/CodingPRD/tasks/task_1447_indoor_vertical_farm_production/workspace/PRD_FINALIZED.md`

### Changes (one bullet per edit)

- §2.5 — insert — new paragraph pinning that every datetime-valued response field (not just `created_at`/`api_request_timestamp`) is emitted as ISO 8601 UTC with exactly three fractional digits and a `Z` suffix, e.g. `2026-08-24T06:30:00.000Z` — `implementation/util.py:52-57` (`fmt_dt`), `util.py:14-17` (`now_iso`), `routes/catalog.py:30-32` (`current_utc`), all `ser_*` in `services/core.py`.
- §2.6 — revise — closed-intervals-with-buffer bullet now states a gap of exactly 4 hours satisfies the buffer — `implementation/routes/sanitation.py:56-65`.
- §2.8 — revise — cascade summary now says the quarantine reaches batches "occupying their towers (occupancy counted through allocations of any `allocation_status`, per §3.4)" instead of "batches growing on them" — `implementation/services/core.py:227-244` (`batches_on_loop`).
- §3.4 — revise — scheduling paragraph: 4-hour buffer strictness pinned ("a gap of exactly 4 hours between two windows satisfies the buffer, and only a gap strictly shorter than 4 hours is a violation") — `implementation/routes/sanitation.py:64`.
- §3.4 — revise — start-gate sentence: defines the section-wide occupancy notion (batch tied to a rack through allocations of any `allocation_status`, so a `HARVESTED` batch with `RELEASED` allocations still blocks cycle start) — `implementation/routes/sanitation.py:117-119` via `services/core.py:227-244`.
- §3.4 — revise — result-recording sentence: PASSED de-quarantine and FAILED quarantine both explicitly count occupancy through allocations of any status (HARVESTED/PACKED batches with released allocations included) — `implementation/routes/sanitation.py:168-171,186-190`.
- §3.4 — revise — pack paragraph: "the batch's water loop" clarified as reached through the batch's tower allocations, released ones included (harvest has freed them by pack time) — `implementation/routes/batches.py:452-461`.

### Per-edit pre-edit search log (NO-NEW-MISMATCH rule)

1. **Datetime rendering (§2.5).** (a) Subject: wire format of datetime-valued response fields. (b) Enumerated: `util.py` (`fmt_dt`, `now_iso`), `services/core.py` `stamp_new`/`touch` (pre-rendered `created_at`/`updated_at`) and every serializer (`ser_loop`, `ser_batch`, `ser_allocation`, `ser_cycle`, `ser_shipment`, `ser_shift`, `ser_reading` all call `fmt_dt`), `routes/catalog.py` `_fmt_clock`, `routes/contracts.py` `contract_week_summary` (dates only), `routes/batches.py` `batch_cost_summary` (no datetimes), `response.py` envelopes. (c) Wording scoped to "fields the API returns" and "datetime-valued" so date-valued fields (`ship_date`, `start_date`, … rendered `YYYY-MM-DD` via `fmt_date`) and request-side parsing (`parse_dt` accepts offsets/naive) stay unconstrained.

2. **Occupancy notion (§3.4 ×3, §2.8, §3.4 pack).** (a) Subject: which batches count as on a loop's racks for the start gate, quarantine/de-quarantine cascades, and the pack recency loop lookup. (b) Enumerated: `services/core.py:227-244` `batches_on_loop` (all-status) and all 5 call sites in `routes/sanitation.py:117,168,174,186,192`; `routes/batches.py:452-461` pack loop lookup (all-status); contrast paths that are ACTIVE-only by design and already pinned as such — `tower_status` (`core.py:248-255`), rack `set-out-of-service` (`catalog.py:329-333`), batch-create/stress overlap checks (`batches.py:82-85,236-239,276-278`), replant eligibility — none of these use occupancy language my edit touches. (c) Scoped the definition with "throughout this section" (§3.4) so the ACTIVE-only rules elsewhere are unaffected; §2.8 summary reworded to reference §3.4 rather than redefine.

3. **4-hour buffer strictness (§3.4, §2.6).** (a) Subject: sanitation window spacing validation. (b) Enumerated: `SANITATION_BUFFER_HOURS` used only in `routes/sanitation.py:55-65` (`create_cycle`); cycle duration bounds (`:50-54`) and 30-minute early-start gate (`:121-122`) are separate rules already pinned and left verbatim; no other endpoint compares cycle windows. (c) Wording chosen ("gap strictly shorter than 4 hours is a violation") so overlapping and merely-touching windows (negative/zero gap) remain rejected, matching the strict-`<` comparison — consistent with §2.6's closed-interval declaration.

No other PRD text was modified; everything else in the diff trace (test-helper `validate_instant_equal`, test assertion swaps) traces to PRD silence item 1, which the §2.5 insert resolves.

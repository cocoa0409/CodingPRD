# Worklog — task_2538_electric_vehicle_battery_warranty_state_of_health_diagnostics

## Step 1: Create task directory — 2026-09-03T07:42:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2538_electric_vehicle_battery_warranty_state_of_health_diagnostics` and its `workspace/` subdirectory. Index 2538 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no index was auto-allocated (other pipelines run concurrently on this host).

## Step 2: Generate Scaffold — 2026-09-03T09:22:00.000Z

All three artifacts are complete and the lint is clean.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2538_electric_vehicle_battery_warranty_state_of_health_diagnostics/`

| File | Lines | Top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 3783 | §1.0–§1.7 only — neither `scaffold_difficulty_design` nor `scaffold_corner_design` present (verified programmatically) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2138 | single key `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3654 | single key `scaffold_corner_design` |

## Scale
- **14 entities**, **52 endpoints**, **80 error codes**, **70 ordered validations**, **14 calculations** (2 dual-variant: `soh_retention`, `claim_settlement`), **10 state-machine dimensions across 9 entities** (ThermalEvent carries containment + notification in parallel), **7 roles**, **3 OCC races**, `difficulty_level: beyond_expert`.
- **§1.8**: 9 rules × 2 instances = **18 instances** (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`).
- **§1.9**: **63 instances** across all nine sections — entities 12, state_machines 9, calculations 10, validations 11, endpoints 5, errors 4, rbac 5, cross_cutting_complexity_layers 6, consistency_model 1 — of which **9 are `excluded_because` stubs** citing §1.8 instances by name (each verified to resolve; no stub carries a `test_recipe`). All 81 names are unique across both design files; every `claim_type` is a token from `references/claim-extraction-guide.md`.

## Lint verdict (verbatim)
```
Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  993

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design adjudications made to SCAFFOLD.yaml
1. Complexity-profile comment corrected to match the actual tables.
2. `module_fault_positions` / `module_degraded_positions` accepted for **both** assessment variants (only the bench variant shrinks the denominator).
3. Dispute-filing precondition aligned between §1.2 and validation 21.
4. `warranty_hold` given an explicit enforcement pointer (it is a read-surface mirror of pack quarantine; `ERR_VEHICLE_IMMOBILIZED` at priority 29 is the enforcing rule).
5. Added `ERR_NOTIFICATION_STILL_PENDING` so validation 24's second clause has a code.
6. `INVALID_ODOMETER_REGRESSION` §1.5 wording aligned to the authoritative §1.1 definition (compare against VALID rows with `captured_at <=` this row, not the vehicle max — the two differ on out-of-order ingest).
7. Added the missing `DENIED -> CLOSED` WarrantyClaim transition (validation 20 and `ERR_CLAIM_NOT_CLOSABLE` both admit DENIED).
8. Added **validation priority 70**: a `LIMITED` release requires non-empty `pilot_region_codes` → `ERR_INVALID_REQUEST` (400); the §1.2 precondition now cites it, and the count comment reads 70.
9. Renamed the parent placeholder to `{id}` on the four sub-resource routes (`battery-packs/{id}/modules`, `vehicles/{id}/telematics-snapshots`, `service-centers/{id}/technicians`, `warranty-claims/{id}/capacity-disputes`) — the skill's documented sub-resource form and what `scaffold_lint.py` check (f) matches; references were updated across all three files.

Every asserted literal in the recipes was computed from the §1.3 formulas rather than estimated (e.g. UN3536 fee `ROUND_HALF_UP(18000×483.296/100) = 86993`, MODULE settlement `363092 + 7500 = 370592`, trimmed-mean retention `70.00`, lab deviation exactly `+2.00 → RESOLVED_UPHELD`, compliance `100 − 15×2 = 70`, bench basis `80×14/16 = 70.000` with plausibility ceiling `73.500`, 4-row window taking a plain mean).

## Step 3: Copy Shared Files — 2026-09-03T09:23:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T09:46:00.000Z

PRD generation for task 2538 is complete.

**Output:** `workspace/PRD.md` — 698 lines / 129,235 bytes, built with 12 chunked `cat >>` appends (no single-Write truncation). The file ends at a real boundary: the 80th row of the §5 error table.

**Section list**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 Role-Based Access Control · 2.2 API Response Structure (verbatim contract) · 2.3 Pagination · 2.4 Resource Identity, Audit Fields and the Logical Clock · 2.5 Money, Percentages and Rounding Discipline · 2.6 Optimistic Concurrency on Parent Records · 2.7 Resolution Order and the Precedence of Rejections (all 70 priorities, numbered) · 2.8 Cascade Integrity Across the Program Graph · 2.9 Ledger Mirrors and Inventory Mirrors · 2.10 High-Voltage Certification, Tooling and Bay Governance · 2.11 Segregation of Duties
- §3 Business Logic — 3.1 Standing Up a Program · 3.2 Telematics Ingestion and the Plausibility Screen · 3.3 Diagnosing Capacity Retention · 3.4 Filing a Claim and the Remedy Recommendation Ladder · 3.5 Adjudication, Pack Reservation, Settlement · 3.6 Executing the Remedy: Bay Windows, Cooldown, Closure · 3.7 Thermal Events: Two Independent Dimensions · 3.8 Software Remediation Campaigns and Owner Consent · 3.9 Capacity Disputes and Remedy Reversals · 3.10 Removed-Pack Logistics and Hazmat Shipping
- §4 Endpoint Definitions — 4-column table, all 52 endpoints
- §5 Error Code Catalogue — 2-column table, all 80 error ids

**Hard Contract 1 — Field-Name Coverage: PASS.** 205 distinct identifiers (all entity fields across the 14 entities + every endpoint `input`/query/path identifier + the three `expected_*` OCC fields) checked over three independent passes; 0 missing, each present verbatim in backticks. Supplementary passes: 42 state names, 109 enum values, 80 error ids, 7 role names — 0 missing.

**Hard Contract 2 — Rule Coverage: PASS.** All 70 ordered validations appear as a numbered precedence ladder in §2.7 with error id + scope, and all 80 error ids are additionally described in workflow prose before §5. All 14 calculations rendered step-for-step in prose including both dual-variant pairs (`soh_retention`, `claim_settlement`) with their stated divergences; all 10 state-machine dimensions with every transition, precondition and side effect, including the ThermalEvent `containment_status` × `notification_status` join into `event_status`. All 3 OCC rules framed purely as stale-version (scan for "simultaneously"/"race"/"first-writer-wins": 0 hits). Pseudocode scan (`==`, `>=`, `+=`, `MIN(`, `MAX(`, `ROUND`, `COUNT(`, `FLOOR(`, `ABS(`, `IN {`): 0 hits — everything translated to prose.

**Hard Contract 3 — §3 Path Purity: PASS.** 1,334 backticked tokens in §3 scanned; 0 begin with `/`, 0 are bare HTTP methods, 0 combine method+path, 0 embed `battery-warranty`. §2 is likewise path-free (checked incidentally).

**Coverage notes**
1. §3 carries 10 subsections where the skill suggests 5–9. The scaffold is `beyond_expert` (14 entities, 52 endpoints, 80 errors, 10 state dimensions); collapsing further would have merged unrelated lifecycles.
2. Four scaffold transition preconditions carry no declared `error_id` (claim filing while `warranty_hold` is true / while an `OPEN` thermal event exists / at a `DECERTIFIED` center; a second `OPEN` thermal event on one vehicle). These are stated in full but described as "a conflict (HTTP 409) without a dedicated identifier" rather than inventing an id.
3. §2.2 is byte-identical to `section-2.2-response-structure.md` (diff clean apart from the `---` rule I place after it).
4. Entity type names (`WarrantyProgram`, `BatteryPack`, …) appear only in natural-language form ("warranty program", "battery pack"); all their *field* names appear verbatim.
5. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Orchestrator truncation check (per pipeline instruction):** `tail -12` shows the file ending on a complete `| \`ERR_LIABILITY_CAP_EXCEEDED\` | 409 |` table row of §5, the document's final section; §5 contains exactly 80 `ERR_` rows and the set of unique `ERR_` ids in PRD.md matches the scaffold's exactly except for the scaffold's own literal placeholder `ERR_XXX`. Not truncated — no regeneration needed.

## Step 6: Generate Implementation — 2026-09-03T10:24:00.000Z

Implementation complete. `app.py` was the last missing module; the service now boots and the full happy path plus a broad set of rejection paths were exercised live.

## Modules (`workspace/implementation/`, 3263 lines of Python)

| file | lines | role |
|---|---|---|
| `app.py` | 67 | Flask app, blueprint registration, `ApiError`/HTTPException/500 handlers returning the error envelope, global `RLock` acquired in `before_request` and released in `teardown_request`, `app.run(host="0.0.0.0", port=int(os.environ["PORT"] or 10000), threaded=True, use_reloader=False)`. No seeding of any kind. |
| `common.py` | 485 | In-memory `Store` (14 dicts) + logical clock (starts `2026-08-01T00:00:00Z`), envelope/meta, `req_*` validators, auth ladder, pagination, 12 not-found codes, child accessors. |
| `calc.py` | 453 | All 14 calculations (temperature correction, snapshot window/validity, retention, coverage, remedy ladder, per-line `remedy_cost_cents`, settlement waterfall, reman selector, hazmat freeze, notification deadline, bay occupancy, cooldown, lab deviation, compliance score). |
| `cascade.py` | 260 | Program/campaign/center/pack mirrors as recomputations, thermal cascade, shipment-rejection cascade, consent factory. |
| `claim_service.py` | 93 | Shared claim helpers (recommendation, settlement compute/write, zeroing, pack reserve/release). |
| `routes_master.py` | 422 | Programs, vehicles, centers, technicians, packs+modules, telematics ingest, `_clock/set_current_utc`. |
| `routes_assess.py` | 164 | SoH assessments. |
| `routes_claim.py` | 494 | Claim create/read/list, request-info, resubmit, adjudicate, fulfil, close. |
| `routes_thermal.py` | 168 | Thermal events, containment steps, regulatory notification (parallel dimensions + derived `event_status`). |
| `routes_campaign.py` | 264 | Campaigns, release, consents, decision, apply-update. |
| `routes_dispute.py` | 174 | Capacity disputes, lab-result, resolve (overturn/downgrade). |
| `routes_ship.py` | 219 | Pack shipments, tender, receive (remanufacture/scrap/reject). |
| `start.sh` | 8 | Installs Flask only when missing (re-run before every per-test reboot), `exec python3 app.py`. |
| `requirements.txt` | 1 | `flask>=2.0` |

## Verification
- `python3 -m py_compile` clean on all 12 `.py` files; `__pycache__` removed afterward.
- Route table diffed programmatically against `SCAFFOLD.yaml`: **52 endpoints, 52 matched, 0 missing, 0 extra** (method+path exact).
- Boot smoke test: `PORT=18550 bash start.sh` → server up in <5 s on `0.0.0.0`, `GET /battery-warranty/warranty-claims?limit=1` → **HTTP 200** with an empty `data` array and full list meta; process killed afterward, no leftover listeners on any port I used.

## Live behaviour verified end-to-end
Program → vehicle → pack (+16 cascade modules) → center/technicians → 3 telematics snapshots → assessment (`retention_pct 68.75`, `IN_COVERAGE`, `qualifies_for_claim`) → claim (`MODULE_FAULT`/`MODULE_ALLOWANCE` recommendations) → request-info → resubmit → adjudicate (`APPROVED_MODULE` 363092 ¢ / `APPROVED_PACK` 1040497 ¢, `admin_fee` tiering 7500/15000, `FULL_COVERAGE`) → fulfil (module FAULTED→REPLACED with `replaced_at`; pack swap with `superseded_pack_id` and vehicle mirror) → shipment (frozen `UN3480`/`STANDARD_UN_4G`/`soc_limit_pct` 50, weight-scaled `hazmat_fee_cents`) → tender → receive (pack → `STOCK`/`REMANUFACTURED`, `remanufacture_count` 1) → close. Also confirmed: campaign release soliciting one consent per targeted vehicle, grant → apply-update → `applied_count`, thermal S3 cascade (vehicle `IMMOBILIZED` + `warranty_hold`, 72 h deadline) with containment steps 1→2→3 gated on the notification, dispute filing/lab-result/resolve (`RESOLVED_UPHELD`), program mirrors (`accrued_liability_cents`, `reman_available_count`/`reman_stock_state`) moving with each event, and rejections `ERR_HV_BAY_CAPACITY_EXCEEDED`, `ERR_TECHNICIAN_COOLDOWN_CONFLICT`, `ERR_INVALID_BAY_WINDOW`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_PACKAGING_NONCONFORMANT`, `ERR_CLAIM_NOT_CLOSABLE`, `ERR_CLAIM_TERMINAL`, `ERR_RETENTION_ABOVE_THRESHOLD`, `ERR_CLOCK_REWIND_FORBIDDEN`, `ERR_UNAUTHENTICATED`/`ERR_UNAUTHORIZED`, and `ERR_INVALID_REQUEST` on `limit=0`.

Constraints honoured: storage is Python dicts only (no file/SQLite/tmp), nothing seeded at startup, no file in `test_suite/`, `test_helpers/`, or any sibling `task_*/` was read or listed, and every module was built with chunked appends rather than one giant write.

## Step 5: Generate Unit Tests — 2026-09-03T11:28:00.000Z

Generation is complete. Both output directories are final, everything parses, and every test carries exactly one `Design:` tag that resolves to a real design instance.

## Files written (line counts)

`test_helpers/`
- `__init__.py` 49, `api_client.py` 327, `api_errors.py` 198, `assertions.py` 576, `constants.py` 135, `factories.py` 362, `fixtures.py` 838, `test_users.py` 95, `types.py` 604 — 3,184 lines

`test_suite/`
- `conftest.py` 75
- `test_01_dual_variant_and_formula.py` 323, `test_02_state_machines_and_cascades.py` 505, `test_03_priority_and_boundaries.py` 425, `test_04_cross_entity_and_temporal.py` 468, `test_05_compensating_invariants.py` 267 (queue A)
- `test_06_entity_shapes.py` 585, `test_07_state_machine_corners.py` 629, `test_08_calculation_corners.py` 682, `test_09_validation_corners.py` 789, `test_10_endpoint_corners.py` 465, `test_11_error_corners.py` 443, `test_12_access_control_corners.py` 396, `test_13_concurrency_and_consistency.py` 476 (queue B)
- 6,528 lines, 82 test functions, 84 collected items (one 3-case parametrize)

## Instance-to-test mapping

- Queue A (Difficulty): **18/18 instances → 28 tests**, all 18 distinct instances covered, no stubs in that yaml.
- Queue B (Corner): **54/54 live instances → 54 tests**, one test per instance — entities 12, state_machines 7, calculations 8, validations 9, endpoints 5, errors 4, rbac 5, cross_cutting_complexity_layers 3, consistency_model 1.
- The 9 `excluded_because:` stubs in `SCAFFOLD_CORNER_DESIGN.yaml` were never translated, as required.

Verification: `python3 -m py_compile` on all 23 generated `.py` files → OK; `pyflakes` clean; import check clean; a script confirmed every `Design:` tag resolves to an existing `name:` in the source yaml, exactly one tag per test, and zero uncovered live instances.

## Skips and PRD adjudications (no instance was skipped)

Every live instance produced a test. Four places where the design's asserted detail conflicted with the PRD, resolved PRD-first:

1. `ERR_REMEDY_OVERRIDE_FORBIDDEN` — design says HTTP 422; PRD error table says **409**. Asserted 409.
2. Same instance: the design's SOFTWARE_REMEDIATION downgrade payload carried no `override_justification` and named an MX-70 campaign against an MX-90 vehicle, letting an earlier rung fire instead of the ordinal lock. Supplied the justification and retargeted the campaign to MX-90; the asserted outcome is unchanged and now uniquely PRD-derived. The DENIED branch likewise gained the `override_justification` the PRD requires for a denial.
3. S1 regulatory filing — the instance asserts `ERR_NOTIFICATION_NOT_REQUIRED`, but the PRD says a filing against an S1/S2 event in `NOT_REQUIRED` receives **`ERR_NOTIFICATION_ALREADY_FILED`**, and ladder rung 25 independently selects that identifier. Asserted `ERR_NOTIFICATION_ALREADY_FILED` (409) with the reasoning inline; `ERR_NOTIFICATION_NOT_REQUIRED` appears unreachable under this PRD.
4. The three stale-version tests rely on the PRD's general rule that any mutation (including a recomputed derived field) increments `version`, which is what makes a gateway ingest, an adjudication and an owner's decline each stale their respective token; the PRD states the claim-version bump on dispute filing and the campaign-version bump on solicitation verbatim.

## Step 7: Run Tests and Iterate — 2026-09-03T12:15:00.000Z

Clean sweep achieved.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (setsid-wrapped). Iteration 1: all 8 rounds 72/84 with an identical 12-test failure union (fully deterministic, no flakiness). Iteration 2 after fixes: **all 8 rounds 84/84 passed, 0 failed, 0 errors, 0 skipped** (~151 s per round).

### Tests deleted (assertions removed on PRD silence, STEP 1a/1b/1c)
No whole test was deleted; five individual assertions were removed as uncovered, each replaced with a comment naming the gap:
1. `test_suite/test_08_calculation_corners.py` — `applicable_min_retention_pct is None` under `INSUFFICIENT_DATA`. PRD §3.3 nulls that field only when `coverage_position` reads `OUT_OF_COVERAGE`; the non-VALID branch nulls only `estimated_capacity_kwh` and `retention_pct`. (COMPUTED-FIELD SILENCE)
2. `test_suite/test_05_compensating_invariants.py` — `admin_fee_cents == 0` on the DISPUTE_DOWNGRADE collapse. PRD §3.9 enumerates exactly four zeroed fields and does not name `admin_fee_cents`, unlike the other two denial paths. (BRANCH-ASYMMETRIC SIDE EFFECT)
3. `test_helpers/assertions.py::assert_denied_claim_zeroed` — `approved_remedy == "DENIED"`. No PRD sentence states what that field reads after denial (neither §3.5's denial branch nor §3.8's consent-decline collapse mentions it). (DEFAULT-VALUE SILENCE)
4. `test_suite/test_10_endpoint_corners.py` — `installed_vehicle_id is None` after a REMANUFACTURE receipt. PRD §3.10 enumerates the receipt's pack writes and never touches that field; only a pack-replacement fulfilment (§3.6) nulls it. (COMPUTED-FIELD SILENCE)
5. `test_suite/test_10_endpoint_corners.py` — `open_hazmat_holds == 0` and center `status == "ACTIVE"` after two rejections of already-QUARANTINED packs. PRD §3.10 raises the hold count unconditionally and never exempts an already-quarantined pack. (BRANCH-ASYMMETRIC SIDE EFFECT)

### Fixes applied to `test_suite/` and `test_helpers/` (STEP 2)
- `test_suite/test_03_priority_and_boundaries.py` — `ERR_ASSESSMENT_VEHICLE_MISMATCH` probe expected HTTP 409; PRD §5 catalogues it as 422 (and `test_helpers/api_errors.py` already mapped it to 422). Corrected the expected status, not the assertion strength.
- `test_suite/test_09_validation_corners.py` — the four FK-order probes sent a real technician's headers while naming a dangling `diagnosing_technician_id`, so they tripped PRD §2.1's identity binding instead of the body-FK ladder under test. Added `dangling_tech_headers = make_technician_headers(NON_EXISTENT_UUID)` and used it in all four calls.
- `test_suite/test_05_compensating_invariants.py` — two adjudications departed from the claim's `recommended_remedy` without an `override_justification`, which PRD §3.5 requires in either direction. Added the justification to both the first pack approval and the byte-identical retry payload.
- `test_suite/test_05_compensating_invariants.py::TestRemanInventoryRelease` — the world's centre of record was built with the PRD §3.1 default `has_pack_lift: false`, which PRD §3.5 forbids for a pack approval. Added `center_overrides={"hv_certification_level": "L3", "has_pack_lift": True}` (the sibling shares this centre), matching what the pack-approval tests in `test_03` already do. No implementation gate was weakened.

### Fixes applied to `implementation/`
- `calc.py::estimated_capacity` — variant-string typo: the bench branch tested `variant == "BENCH"` while the real enum value is `BENCH_CAPACITY_TEST`, so bench assessments fell through to the fleet trimmed mean. Now non-`TELEMATICS_FLEET` returns `bench_measured_capacity_kwh` per PRD §3.3.
- `common.py::_as_dec` — added a `places is None` path that preserves the supplied precision, so a field with no PRD-declared scale is not quantized.
- `routes_master.py` snapshot ingest — read `coolant_temp_c` unscaled; PRD §2.5 declares no scale for it and PRD §3.2 turns on "anything even fractionally above 35.0", so rounding to 1 dp broke the correction-factor boundary.
- `routes_master.py::create_vehicle` — stored `odometer_miles: 0` instead of the client-supplied figure; PRD §3.1 makes the field derived and says it "reads 0 while the vehicle has no valid snapshot at all" (the input is still validated).
- `routes_master.py` snapshot ingest tail — on a `VALID` ingest that raises the derived odometer, the vehicle is now `touch()`ed. PRD §2.4: "Recomputing a derived field counts as a mutation", which is what PRD §2.6's stale-assessment-token scenario depends on.

No skips/xfails, no weakened error-id assertions, and no seeded/persisted state — storage remains in-memory dicts only. Sweep artifacts and `__pycache__` were removed from `workspace/implementation/`.

### Orchestrator independent verification
The Step 7 subagent removed its `results.*.json` before exiting, so its clean-sweep claim carried no durable evidence and the skill's output spec expects the artifacts to be present. The orchestrator therefore re-ran the identical 8-round setsid-wrapped sweep itself (log: `workspace/sweep_verify.log`). Result: **all 8 rounds 84/84, failed 0, errors 0** — the claim is confirmed and `workspace/implementation/results.{1..8}.json` are now on disk.

## Step 8: Finalize PRD — 2026-09-03T12:34:00.000Z

PRD_FINALIZED.md is complete.

## Line counts
- `PRD.md`: 698 lines
- `PRD_FINALIZED.md`: 698 lines — **0.0% line-count delta** (all 13 edits are in-paragraph revisions; 13/698 = 1.9% of lines touched, no inserted or deleted lines, no new sections)
- Tail verified: file still ends at the §5 error table, last row `| ERR_LIABILITY_CAP_EXCEEDED | 409 |`

## Changes (one bullet each)

- §2.4 identity/audit — revise — added that a refresh recomputing the figure already stored is *not* a mutation for the program/pack/campaign/vehicle mirrors, while a center's hazmat-hold bookkeeping stamps the center on every step — `cascade.py:22-25,37-39,54-57,66-80`, `routes_master.py:401-406`, `cascade.py:124-125,133-134`
- §2.8 shipment-rejection cascade — revise — pack is set to `QUARANTINED` from `REMOVED` *or from `QUARANTINED` again*, and `open_hazmat_holds` rises on every rejection with no exemption for an already-quarantined pack — `cascade.py:208-213`
- §2.9 center counters — revise — `open_hazmat_holds` redefined from a re-derived invariant to a running tally (starts 0; +1 per rejected receipt and at thermal containment step 2 when an origin center of record exists; −1 floored at zero on accepting a quarantined pack's shipment; every step stamps the center) — `cascade.py:123-138`, `routes_thermal.py:137-139`, `routes_ship.py:217-218`
- §3.1 vehicle registration — revise — a supplied `odometer_miles` is validated as a non-negative integer then discarded; a newly registered vehicle reads 0 whatever was sent — `routes_master.py:139` + `:157`
- §3.2 snapshot inputs — revise — `coolant_temp_c` carries no declared scale in §2.5 and is stored exactly as supplied rather than quantized — `common.py:318-320`, `routes_master.py:380`
- §3.2 VALID-snapshot effect — revise — the vehicle record is rewritten only when the derived odometer actually changes; a non-raising VALID row and every invalid row leave `updated_at`/`version` untouched — `routes_master.py:399-406`
- §3.3 assessment fields — revise — `estimated_capacity_kwh`/`retention_pct` are the *only* fields a non-`VALID` verdict nulls; the coverage/window/basis fields are written on their normal rules whatever the verdict — `routes_assess.py:83-90`
- §3.5 denial branch — revise — the denial records `approved_remedy` as `DENIED` (not left as recommended) alongside `denial_reason = ADJUDICATOR_DECISION` — `routes_claim.py:302-310`
- §3.8 consent-decline collapse — revise — scoping guard: money resets to zero while `approved_remedy` and `proration_factor` stand as adjudicated — `routes_campaign.py:216-224`, `claim_service.py` `zero_money`
- §3.9 `RESOLVED_OVERTURNED` on `APPROVED_MODULE` — revise — the escalation rewrites `approved_remedy` to `PACK_REPLACEMENT` — `routes_dispute.py:104-127`
- §3.9 `RESOLVED_DOWNGRADED` pack→module — revise — the downgrade rewrites `approved_remedy` to `MODULE_REPLACEMENT` — `routes_dispute.py:129-150`
- §3.9 `RESOLVED_DOWNGRADED` module→denied — revise — the collapse zeroes four money fields and *not five*: `admin_fee_cents`, `proration_factor` and `approved_remedy` survive, so a dispute-driven denial is not byte-identical to an adjudicator's denial — `routes_dispute.py:151-160` (`zero_money(..., include_admin_fee=False, reset_proration=False)`)
- §3.10 `REMANUFACTURE` receipt — revise — the receipt does not touch `installed_vehicle_id`, so a pack quarantined while fitted returns to `STOCK` still naming its vehicle — `routes_ship.py:192-206`
- §3.10 rejection paragraph — revise — pack set to `QUARANTINED` whatever its prior status; hold rises with no exemption for an already-quarantined pack — `routes_ship.py:183-188`, `cascade.py:208-216`

## Pre-edit search log (subject / paths enumerated / wording adjustment)

1. **Non-VALID assessment field nulling** — `routes_assess.py` read in full (single write site, lines 60-110), `calc.py:78-149` (`diagnostic_validity`, `estimated_capacity`, `retention_pct`, `coverage_position`, `qualifies`), grepped `retention_pct`/`applicable_min_retention_pct` across `implementation/`. Adjustment: enumerated the seven fields that *are* written rather than asserting a general rule, because `qualifies()` still short-circuits on validity.
2. **`approved_remedy` on denial** — grepped `approved_remedy` across all routes: `routes_claim.py:302-328`, `routes_dispute.py:104-160`, `routes_campaign.py:216-224`, `claim_service.py`. Adjustment: confined the "reads DENIED" claim to the adjudicator's denial branch and added explicit guards in §3.8/§3.9, since the two collapse paths deliberately leave the remedy alone.
3. **Dispute money collapse asymmetry** — `routes_dispute.py` read in full; `claim_service.zero_money` signature and all three call sites enumerated; `refresh_accrual` checked for ledger interaction. Adjustment: stated "four money fields and not five" and named the three survivors, rather than a blanket "money is zeroed".
4. **`installed_vehicle_id` after a receipt** — `routes_ship.py:150-218`, `routes_claim.py:446-460` (only nulling site), `routes_master.py:285-330` (only setting site), `calc.py:268-279` (`_eligible_common` excludes such a pack from the selector). Adjustment: narrowed from "the receipt writes no other field" to just the `installed_vehicle_id` claim, since the receipt does write `faulted_module_count` and clears each module's `thermal_runaway_flag`.
5. **`open_hazmat_holds` semantics** — grepped `open_hazmat_holds`/`raise_hazmat_hold`/`lower_hazmat_hold` repo-wide; read `cascade.py` in full, `routes_ship.py:170-218` (`was_quarantined` captured before disposition), `routes_thermal.py:130-140` (`_origin_center_of_record`), `routes_master.py:200` (seeded 0). Adjustment: described a tally with three movement sites instead of an invariant, and explicitly noted the unconditional stamp so the §2.4 "no-op is not a mutation" qualifier does not swallow it.
6. **Registration odometer** — `routes_master.py:139,157`; grepped every `odometer_miles"] =` write (only `routes_master.py:405`); `calc.derive_vehicle_odometer` is MAX over VALID snapshots. Adjustment: kept "may be supplied" and "validated as a non-negative integer" so the 400-on-negative behaviour still traces, then pinned that it is discarded.
7. **`coolant_temp_c` scale** — `common.py:309-327` (`places=None` passthrough — the only such call site, confirmed by grepping `opt_dec(`/`req_dec(` across `implementation/`), `routes_master.py:380,393,396`, `calc.py:12-25`, §2.5 scale list checked for any coolant entry (none). Adjustment: added "alone among the decimal inputs" and tied it to the 35.0 correction boundary already pinned in §3.2, avoiding any new claim about a declared scale.
8. **Vehicle touch on ingest** — `routes_master.py:399-406`, `common.py:135-138` (`touch`), §2.6's `expected_vehicle_version` paragraph (line 128 uses "moved", already consistent), plus every guarded/unguarded `touch` in `cascade.py`, `routes_claim.py:437` (`touch(technician)` fires even when `last_hv_window_end_at` is unchanged). Adjustment: dropped the originally planned universal "recomputation that changes nothing is not a mutation" from §2.4 and scoped it to the named mirrors plus the vehicle, with the hazmat-hold exception called out — the universal form would have contradicted `lower_hazmat_hold` at floor zero and the fulfilment `touch(technician)`.

**No PRD edit** for four Step-7 items, each verified already-determined or test-side only: the `ERR_ASSESSMENT_VEHICLE_MISMATCH` 409→422 test fix (§5 already says 422), the three test fixture bugs (dangling technician header, missing `override_justification`, center `has_pack_lift`/`L3` overrides), and the `calc.estimated_capacity` bench-variant string fix (§3.3 already pins the bench numerator).

## Step 9: Complete PRD — pass 1 of 3 (core modules) — 2026-09-03T12:40:00.000Z

Orchestrator note on partitioning: Step 9's single-subagent form reliably runs out of budget on a 12-module beyond_expert implementation and exits having written a byte-identical copy of PRD_FINALIZED.md — i.e. no scan at all. To prevent that, Step 9 was run as three sequential file-partitioned passes over the same `PRD_COMPLETED.md`: pass 1 = cross-cutting core (`app.py`, `common.py`, `calc.py`, `cascade.py`, `claim_service.py`, `start.sh`, `requirements.txt`), pass 2 = `routes_master.py` + `routes_assess.py`, pass 3 = the five workflow route modules. Each pass hands unresolved items in its own partition forward to the next.

Pass 1 complete.

## Confirmation

`workspace/PRD_COMPLETED.md` was created by `cp` from `PRD_FINALIZED.md`, then edited in place with 23 targeted `Edit` calls.

- **Line count: 698** (unchanged — every edit was an in-line replacement; zero lines added or removed)
- **Char delta: 132,411 → 139,141 (+6,730)**
- **26 lines touched**; file still ends at `| `ERR_LIABILITY_CAP_EXCEEDED` | 409 |`

**Counts for my partition: 18 ambiguity-pins, 5 mismatch-revisions.**

## Changes

- §2.1 (¶1) — revise — mismatch — "two mandatory headers" was false; `X-User-ID` is only demanded by the five actor-attribution ops, and blank/whitespace counts as absent — `common.py:200-212`
- §2.1 (identity binding ¶) — insert — ambiguity — a failed ownership check reports `ERR_UNAUTHORIZED` (403), no dedicated identifier — `common.py:215-216`
- §2.2 (`api_request_id` bullet) — insert — ambiguity — `req_` + exactly 20 uppercase-alnum chars — `common.py:164-166`
- §2.2 (`api_request_timestamp` bullet) — revise — mismatch — this field is stamped from the **host wall clock**, the one exception to §2.4's logical-clock rule — `common.py:172`
- §2.3 (¶1) — insert — ambiguity — non-integer / out-of-range `limit` / negative `offset` → `ERR_INVALID_REQUEST` 400; empty value = omitted — `common.py:220-240`
- §2.3 (¶2) — insert — ambiguity — equal `created_at` broken by internal insertion sequence (ascending lists earliest-first, descending snapshot list newest-first); sequence never exposed — `common.py:141-142`, `routes_master.py:417`
- §2.4 (clock ¶) — insert — ambiguity — ISO-8601 parsing: `Z`/numeric offset normalised to UTC, naive read as UTC, unparseable → `ERR_INVALID_REQUEST` — `common.py:74-89`
- §2.5 (`proration_factor` bullet) — insert — ambiguity — `labor_hours_module` / `labor_hours_pack` carry two decimals (previously unlisted in the scale table) — `routes_master.py:88-89` via `common.py:315-327`
- §2.5 (comparisons ¶) — insert — ambiguity — inputs quantized half-up to declared scale **before** range checks; decimals emitted as bare JSON numbers in shortest form (`80.000` prints `80.0`) — `common.py:320`, `common.py:150`
- §2.6 (final ¶) — insert — ambiguity — requests serialised behind one process-wide lock; version checks are never raced — `app.py:29-39`, `common.py:28`
- §2.7 (¶1) — revise — mismatch — "The **ten** path-and-body existence failures" → **twelve** (the list itself has 12; `NOT_FOUND` has 12 entries) — `common.py:404-417`
- §2.7 (ladder item 4) — insert — ambiguity — JSON booleans rejected where a number is declared; explicit `null` on an optional field = omitted → default applies — `common.py:294`, `common.py:316`, `common.py:260-261`
- §2.9 (¶1) — insert — ambiguity — `reman_available_count` is a **global** pack-table count mirrored onto *every* program, not per-program — `cascade.py:15-25`
- §2.9 (center counters ¶) — insert — ambiguity — a hazmat step that both moves the tally and flips center `status` stamps the center twice (`version` +2) — `cascade.py:123-138`
- §3.1 (pack modules ¶) — revise — mismatch — `module_replacements_to_date` is a lifetime high-water mark (`max(live, stored)`) that never falls, e.g. not on a remanufacture receipt; `faulted_module_count` is a live re-derivation — `cascade.py:48-57`
- §3.2 (plausibility screen ¶) — insert — ambiguity — with no pack installed there is no ceiling; only the at-or-below-zero half can fire — `calc.py:35-38`
- §3.3 (diagnostic gate ¶) — insert — ambiguity — window tie-break beyond `created_at` is insertion sequence, most-recently-ingested first — `calc.py:66`
- §3.3 (trimmed mean ¶) — revise — mismatch — "three or four rows" was default-bound; trimming happens **only** at exactly `snapshot_window_size` — `calc.py:105-109`
- §3.4 (seven quantities ¶) — revise — mismatch — the ladder reads the **live** count of modules in `REPLACED`, not the `module_replacements_to_date` mirror (diverges after a remanufacture receipt) — `calc.py:167`
- §3.4 (rung 4) — revise — mismatch — same substitution in the allowance formula — `calc.py:175`
- §3.5 (selector ranking ¶) — revise — mismatch — "Because `created_at` is the final key the order is total" is false under a logical clock; insertion sequence is the final key — `calc.py:297-298`
- §3.5 (NEW fallback ¶) — insert — ambiguity — same final insertion-sequence key on the `NEW` pool — `calc.py:313`
- §3.5 (proration ¶) — insert — ambiguity — a `goodwill_months`/`goodwill_miles` of 0 (the configured minimum) contributes 1 when its overrun is positive, 0 otherwise, instead of dividing — `calc.py:242-249`, bound confirmed at `routes_master.py:82-83`
- §3.10 (`hazmat_fee_cents` ¶) — insert — ambiguity — the 5-step program-resolution order for a pack that carries no program FK (installed vehicle → last-installed vehicle → newest assessment → newest reserving claim → oldest program → basis 0) — `calc.py:318-336`
- §4 (preamble) — insert — ambiguity — absent body read as `{}`; non-object body → `ERR_INVALID_REQUEST` — `common.py:249-257`
- §5 (preamble) — insert — ambiguity — `ERR_NOT_FOUND` (404) and `ERR_METHOD_NOT_ALLOWED` (405) sit outside the catalogue; trailing slash ignored — `app.py:22`, `app.py:47-53`

## Deliberately left alone

- **Endpoint bodies in `routes_*.py`** — passes 2/3 own these. Specifically noted but not touched: `retention_schedule` stable-sort tie behaviour on equal `through_months` (`routes_master.py:58`), the `bench_measured_capacity_kwh` validator having no lower bound (`routes_assess.py:30`), `pack_replacement_retention_pct` / `reman_min_soh_pct` range bounds absent from §3.1, and the position of ownership checks within the §2.7 ladder.
- **Unreachable impl branches, left unpinned by design** (pinning them would assert behaviour that cannot be observed): `settlement()` treating `OUT_OF_COVERAGE` as `GOODWILL_PRORATED`; `remedy_cost_cents` defaulting a null replacement pack to `REMANUFACTURED` pricing; `retention_pct` returning null on a zero basis; `dispute_outcome` returning `RESOLVED_UPHELD` on a null deviation; the `ERR_INTERNAL`/500 handler.
- `start.sh` and `requirements.txt` conform to `INSTRUCTION.md` (PORT env with 10000 default, `0.0.0.0`, `exec`, foreground) and carry nothing the PRD speaks to — no edit needed.

## Step 9: Complete PRD — pass 2 of 3 (master data + assessments) — 2026-09-03T12:52:00.000Z

Pass 2 complete.

**File state:** `workspace/PRD_COMPLETED.md` — 698 lines, 145,031 chars. My pass added **+5,890 chars** (139,141 → 145,031); no new sections, one paragraph count change avoided (all inserts are in-paragraph). File still ends at `| ERR_LIABILITY_CAP_EXCEEDED | 409 |`.

**Counts (my partition):** 14 ambiguity-pins, 4 mismatch-revisions.

**Changes**

- §2.3 — insert — ambiguity — pagination parse is settled before a nested list's path resource is resolved, so a bad `limit` under a missing parent gives 400 not 404 (`routes_master.py:259,263,411` / same order in `routes_claim.py:147`)
- §2.3 — insert — ambiguity — list filters are exact matches on the stored value; an unknown value narrows to nothing, an empty value is *not* read as omitted; `superseded` is the only parsing filter (`routes_master.py:20-23`, `routes_assess.py:150-162`)
- §2.7 item 4 — insert — ambiguity — scalar string fields, required or optional, are refused when empty/whitespace-only, and accepted values are stored untrimmed (`common.py:264-278`, exercised by every field in my modules)
- §2.9 — revise — mismatch — "a freshly created program starts with both counters at zero" → `reman_available_count` is seeded from the pack table at creation (`routes_master.py:108-113`)
- §3.1 program — insert — ambiguity — `retention_schedule` sort is stable and keyed on `through_months` alone, so equal-months rows keep supplied order and `through_miles` never breaks the tie (`routes_master.py:58`)
- §3.1 program — insert — ambiguity — the closure rule is applied to the *default* schedule too, so changing `coverage_months`/`coverage_miles` without a matching schedule is refused `ERR_INVALID_REQUEST` (`routes_master.py:40-62,73`)
- §3.1 program — insert — ambiguity — `pack_replacement_retention_pct` and `reman_min_soh_pct` bounded 0.00–100.00 inclusive (`routes_master.py:80,98`)
- §3.1 program — insert — ambiguity — every threshold/price/labour constant validated ≥ 0 with zero accepted and no ceiling; the three snapshot constants instead require ≥ 1 (`routes_master.py:81-102`)
- §3.1 program — revise — mismatch — new program's mirrors: `accrued_liability_cents` 0 always, `reman_available_count` seeded, seeding is not a mutation so `version` is 1 (`routes_master.py:103-114`)
- §3.1 vehicle — insert — ambiguity — future `in_service_date` → `ERR_INVALID_REQUEST`, but tested *after* `warranty_program_id` resolves, so an unknown program wins (`routes_master.py:140-142`)
- §3.1 vehicle — insert — ambiguity — `owner_contact_email` is an opaque non-blank string, no format check (`routes_master.py:138`)
- §3.1 pack — revise — mismatch — `serial_number` uniqueness is across the whole pack table, not "across the program" (`routes_master.py:289-292`)
- §3.1 pack — revise — mismatch — registration does **not** accept `damaged_defective` (silently ignored, always starts false); `hazmat_classification` starts null (`routes_master.py:309-310`)
- §3.1 pack — insert — ambiguity — `gross_weight_kg` ≥ 0; `refurb_soh_pct` 0.00–100.00 and its conditional presence is a plain `ERR_INVALID_REQUEST` decided before FK resolution (`routes_master.py:277-283`)
- §3.1 modules — insert — ambiguity — module listing is narrowable by a `status` query filter (`routes_master.py:363`)
- §3.1 center/technician — insert — ambiguity — a past `insulation_tester_cal_due_at` and an already-expired `cert_expires_at` are both accepted at registration; the technician's creation response itself reads `CERT_LAPSED` (`routes_master.py:195-196,240,251`)
- §3.3 — insert — ambiguity — assessment creation performs no ownership/actor check: `technician_id` need not be the caller and `X-User-ID` may be absent (`routes_assess.py:23`)
- §3.3 — insert — ambiguity — `bench_measured_capacity_kwh` has no lower bound; zero/negative passes shape and the gate and propagates into a zero/negative `estimated_capacity_kwh`/`retention_pct`; field echoed, null on fleet (`routes_assess.py:30`)
- §3.3 — insert — ambiguity — the module write-through is unconditional and overwrites any prior status including `REPLACED`; an already-matching module is untouched (no `version` bump); both arrays echoed verbatim in supplied order (`routes_assess.py:59-68,99-100`)
- §3.3 — insert — ambiguity — only priors with `superseded` false are touched (an already-superseded one does not re-version); new record written `superseded` false; list filter semantics for the five string filters and the boolean `superseded` (`routes_assess.py:114-118,150-162`)

**Deliberately left unpinned**
- `routes_master._bool_arg` (lines 26-35) — dead code, no endpoint calls it; unreachable through the public API.
- `calc.diagnostic_validity`'s `bench is None → INSUFFICIENT_DATA` branch — unreachable, since priority-5 guarantees bench presence for the bench variant.
- The general **ladder position of ownership checks** that pass 1 handed me: neither of my modules performs one (I pinned the observable fact — assessment creation has none). The endpoints that do (`routes_claim`, `routes_dispute`, `routes_campaign`, `routes_ship`) order them differently from one another — e.g. `routes_claim.py:37` compares before FK resolution while `routes_dispute.py:28` compares after the claim `must()` — so any single §2.7 statement would be a false universal. Pass 3 owns those files and should pin it per-endpoint.

## Step 9: Complete PRD — pass 3 of 3 (workflow routes) — 2026-09-03T13:20:00.000Z

Pass 3 complete.

## Result

`workspace/PRD_COMPLETED.md` — **698 lines** (unchanged), still ending at `| ERR_LIABILITY_CAP_EXCEEDED | 409 |`. Size before my first edit: 145,031 bytes; after: **166,826 bytes → +21,795 bytes** from this pass. All edits were targeted in-paragraph `Edit` calls; no new sections, no whole-file writes.

**48 changes: 26 ambiguity-pins, 22 mismatch-revisions.**

### Global sections (§2.1, §2.7)
- §2.7 precedence preamble — insert — ambiguity — pass-2's handoff resolved with a universally true formulation: ownership comparisons occupy no rung; they always follow shape validation, precede existence resolution when the compared value comes from the body (filing, fulfilment), and immediately follow resolution of the owning record when it is stored on it (resubmit, consent decision, dispute filing) — routes_claim.py:37,183; routes_ship.py:—; routes_dispute.py:28; routes_campaign.py:201
- §2.1 — insert — ambiguity — only filing, resubmit and fulfilment compare `X-User-ID`; tender demands it but never matches it; containment step and flash merely look the technician up — routes_ship.py:121; routes_thermal.py:118; routes_campaign.py:244
- §2.7 item 26 — revise — mismatch — campaign-release check deferred to the end of the consent-side sequence on decision and flash — routes_campaign.py:211,242
- §2.7 items 45–46 — revise — mismatch — true scope of the two technician rungs; both deferred past rung 56 on a flash — routes_ship.py:64,67; routes_thermal.py:121,124; routes_campaign.py:247
- §2.7 item 39 — revise — ambiguity — `ERR_VEHICLE_NOT_TARGETED` also fires on a software approval — routes_claim.py:268
- §2.7 item 62 — revise — mismatch — retention/coverage precedence is *reversed* on a resubmit — routes_claim.py:201
- §2.7 item 66 — revise — mismatch — `ERR_NOTIFICATION_NOT_REQUIRED` is reserved and never emitted; that case reports `ERR_NOTIFICATION_ALREADY_FILED` — routes_thermal.py:152

### §3.4 filing
- insert — ambiguity — the three undedicated 409s are ordered warranty hold → open thermal event → decertified center, after `ERR_OUT_OF_COVERAGE` — routes_claim.py:80-89
- insert — ambiguity — every later-stage field starts **null, not zero** (whole settlement block, both bay instants, remedy/denial/adjudicator/pack/campaign fields); `pack_shipment_required` false — routes_claim.py:91-119
- revise — mismatch — `reason_note` validated then discarded — routes_claim.py:160
- revise — mismatch — resubmit's four-clause order, `ERR_OUT_OF_COVERAGE` before `ERR_RETENTION_ABOVE_THRESHOLD`, and recommendation recomputed on *every* resubmit — routes_claim.py:190-208

### §3.5 adjudication
- insert — ambiguity — `ERR_ACTOR_REQUIRED`; missing `linked_campaign_id` is shape-stage and pre-empts `ERR_CLAIM_NOT_FOUND`; body-FK resolution order — routes_claim.py:238,245,248
- revise — ambiguity — override-justification failure is `ERR_INVALID_REQUEST` evaluated after the adjudicability guard, before every remedy precondition — routes_claim.py:256
- revise ×2 — mismatch — the downgrade lock covers `CELL_DELTA` as well as `THERMAL_HISTORY`, keys on the pair of fields, and exempts `DENIED` — routes_claim.py:282
- revise — ambiguity — software branch error ids and the absence of any center-tier/lift bar — routes_claim.py:220,264,267
- insert — ambiguity — a denial leaves `settlement_variant` null and never consults the liability ceiling — routes_claim.py:302-310
- insert — ambiguity — a named `REMANUFACTURED` pack with null `refurb_soh_pct` is refused; a named pack on non-pack branches must resolve but is ignored — routes_claim.py:223-233,270

### §3.6 fulfilment & closure
- revise — mismatch — `APPROVED_SOFTWARE` is a fulfillable state; `fulfilment_blocked` shares `ERR_CLAIM_NOT_FULFILLABLE`; `ERR_TECHNICIAN_NOT_FOUND` — routes_claim.py:373-378
- revise — mismatch — the "S1/S2 never block" universal hedged against the quarantined-pack sweep — routes_claim.py:409
- revise — ambiguity — the reserved-pack recheck is *last* of all; the all-severity sweep sits with the interlocks — routes_claim.py:409,426
- revise — mismatch — the software bay path documented in full (which gates apply, which do not) — routes_claim.py:376-434
- revise — ambiguity — closure resolves "the removed pack" through the backing assessment, and only a `RECEIVED` shipment satisfies it — routes_claim.py:479-485

### §3.7 thermal
- insert — ambiguity — `affected_module_positions` shape-only validation, stored verbatim; open-event conflict tested last of three — routes_thermal.py:33,42
- insert — ambiguity — no fourth step; `step_index` < 1 is `ERR_INVALID_REQUEST` — routes_thermal.py:108,111
- revise — mismatch — step-1 certification tests are conditional on the header resolving to a technician — routes_thermal.py:117-126
- revise — mismatch — the pack's status is not a precondition of step 2 — routes_thermal.py:132-136
- insert — ambiguity — "origin center of record" = origin center of the pack's most recently created shipment; never-shipped pack touches none; hold rises independently of the quarantine — routes_thermal.py:93-101

### §3.8 campaigns
- insert — ambiguity — `consent_required` is recorded and never consulted — routes_campaign.py:36,49
- insert — ambiguity — DRAFT-only release as an undedicated 409, ahead of the pilot-region check; a vehicle with no installed pack matches `ANY` alone — routes_campaign.py:78-84,103-106
- revise — ambiguity — same no-pack rule and the stored `release_scope` basis on re-solicitation — routes_campaign.py:78-94,142
- revise — mismatch — on the owner decision the campaign check runs *last* of four; `ERR_ACTOR_REQUIRED` — routes_campaign.py:196,203-212
- revise — mismatch — flash order is consent → vehicle → expiry → campaign → technician, the last conditional on the header, and the `L1` floor is unreachable — routes_campaign.py:230-252

### §3.9 disputes
- revise — mismatch — the dispute window is judged *before* the duplicate check; no actor requirement, so a missing header yields `ERR_UNAUTHORIZED` — routes_dispute.py:21,38-46
- insert — ambiguity — `lab_measured_capacity_kwh` three decimals ≥ 0, no upper bound; `lab_report_reference` discarded — routes_dispute.py:78-79
- insert — ambiguity — null `nominal_basis_kwh`/`oem_retention_pct` propagate to a null `deviation_pct`, which counts as within tolerance — calc.py:432-448
- revise — mismatch — a retest-triggering result leaves `dispute_status` exactly where it stood (including at `LAB_RESULT_RECEIVED`) — routes_dispute.py:93-98
- insert — ambiguity — a reopened denial keeps its zeroed money — routes_dispute.py:106-112
- insert — mismatch — escalation uses `ERR_NO_REMAN_PACK_AVAILABLE`, re-tests no liability ceiling, and is a no-op on `APPROVED_PACK`/`APPROVED_SOFTWARE`/`FULFILLED` — routes_dispute.py:113-126
- insert — ambiguity — downgrade is a no-op on `APPROVED_SOFTWARE`/`DENIED`/`FULFILLED`; both edges key on state at resolution time — routes_dispute.py:129-146

### §3.10 shipments
- insert — ambiguity — tender requires the header but never compares it — routes_ship.py:121
- insert — ambiguity — companion exclusivity is shape-stage and pre-empts `ERR_SHIPMENT_NOT_FOUND`; `refurb_soh_pct` range-checked there — routes_ship.py:155-165
- revise — mismatch — disposition/destination coherence and the required `refurb_soh_pct` are `ERR_INVALID_REQUEST` raised *after* the `TENDERED` check — routes_ship.py:173-182
- revise — mismatch — remanufacture does **not** clear `hazmat_classification`, does clear every `thermal_runaway_flag`, zeroes `faulted_module_count`, and leaves the lifetime replacement counter high — routes_ship.py:193-206
- revise — ambiguity — scrap zeroes `faulted_module_count` and keeps the thermal flags — routes_ship.py:208-215

### §4
- insert — ambiguity — the ten free-text fields validated then discarded vs. the three that persist — routes_claim.py:160,181,243-244,473; routes_thermal.py:109; routes_campaign.py:199,232; routes_ship.py:123; routes_dispute.py:79
- revise ×3 — mismatch — undocumented list filters added: claim capacity-disputes `dispute_status`; thermal-events `event_status` + `source`; campaigns `release_scope` — routes_claim.py:150; routes_thermal.py:81-84; routes_campaign.py:72

## Deliberately left unpinned
- `bay_occupancy(exclude_claim_id=...)` self-exclusion — a claim can only be fulfilled from an approved state, where it holds no window, so the exclusion can never change the count.
- The `_adjudicated_at is None` branch that skips the dispute window — every disputable status is reached only through an adjudication that stamps it, except via an overturn-reopen, which returns the claim to a non-disputable `SUBMITTED`.
- `removed = installed_pack or assessed_pack` fallback at fulfilment — a claim cannot be filed on a vehicle with no installed pack.
- The segregation check's `adjudicated_by_user_id is not None` guard on dispute resolution — a claim with a null adjudicator is `SUBMITTED` and undisputable, so no open dispute can reach it.
- Four identifiers the implementation emits but §5 does not catalogue (`ERR_CAMPAIGN_NOT_DRAFT`, `ERR_CENTER_DECERTIFIED`, `ERR_THERMAL_EVENT_OPEN`, `ERR_VEHICLE_WARRANTY_HOLD`): rather than add catalogue rows, all four are described in the PRD's existing idiom, "a conflict (HTTP 409) without a dedicated identifier". I verified none of the four appears anywhere in the file, so that wording is consistent throughout.

## Step 9: Complete PRD — orchestrator closing patch — 2026-09-03T13:25:00.000Z

Pass 3's final bullet left a residual mismatch that Step 9 exists to remove, so the orchestrator closed it directly rather than leaving it. `grep` confirms `implementation/` really does raise all four identifiers — `ERR_CAMPAIGN_NOT_DRAFT` (`routes_campaign.py:104`), `ERR_VEHICLE_WARRANTY_HOLD` (`routes_claim.py:81`), `ERR_THERMAL_EVENT_OPEN` (`routes_claim.py:85`, `routes_thermal.py:44`), `ERR_CENTER_DECERTIFIED` (`routes_claim.py:88`) — each with HTTP 409 in the envelope's `error_id`. Describing them as carrying "no dedicated identifier" is therefore not under-determined wording but a false statement: a fresh implementer reading it would emit some other identifier and diverge. It also contradicted §5's own preamble ("Every rejection returns the error envelope of section 2.2 with one of the identifiers below in its `error_id` field") and, at the filing site, the paragraph's own follow-on sentence ("These three sit at the very end…") which already counted three where the lead-in said two.

Four edits applied, all verified to match exactly once before replacement:
1. §3.4 filing — revise — mismatch — "Two further preconditions … without a dedicated identifier" → "Three further preconditions are enforced as conflicts (HTTP 409)", each clause now naming `ERR_VEHICLE_WARRANTY_HOLD`, `ERR_THERMAL_EVENT_OPEN` and `ERR_CENTER_DECERTIFIED` respectively — `routes_claim.py:81,85,88`. Also repairs the two-versus-three count disagreement inside the paragraph.
2. §3.7 thermal — revise — mismatch — a second `OPEN` event on one vehicle "is a conflict (HTTP 409) without a dedicated identifier" → "is refused with `ERR_THERMAL_EVENT_OPEN` (HTTP 409)" — `routes_thermal.py:44`.
3. §3.8 campaigns — revise — mismatch — a non-`DRAFT` release "is refused as a conflict (HTTP 409) without a dedicated identifier" → "is refused with `ERR_CAMPAIGN_NOT_DRAFT` (HTTP 409)" — `routes_campaign.py:104`.
4. §5 catalogue — insert — mismatch — four rows appended (`ERR_VEHICLE_WARRANTY_HOLD`, `ERR_THERMAL_EVENT_OPEN`, `ERR_CENTER_DECERTIFIED`, `ERR_CAMPAIGN_NOT_DRAFT`, all 409) so the table matches its own exhaustiveness claim. Rows added to an existing table, not a new section.

Post-patch verification: `grep -c 'without a dedicated identifier'` → 0; file is 702 lines / 167,070 bytes and still ends on the §5 table's last row. A sweep over every `"ERR_*"` literal raised anywhere in `implementation/` finds exactly one identifier absent from `PRD_COMPLETED.md`: `ERR_INTERNAL`, the 500 handler pass 1 deliberately left unpinned as unreachable through the public API. That judgement stands — documenting an unobservable internal-error path would assert behaviour no faithful implementation needs to exhibit. These are prose-only edits and cannot affect the test suite.

## Step 9 aggregate

- Source `PRD_FINALIZED.md`: 698 lines / 132,411 chars → `PRD_COMPLETED.md`: 702 lines / 167,070 chars (**+34,659 chars, +26.2%**; +4 lines, all four being §5 table rows).
- Totals across the three passes plus the closing patch: **48 ambiguity-pins, 35 mismatch-revisions** (pass 1: 18/5, pass 2: 14/4, pass 3: 26/22, orchestrator: 0/4).
- Final test evidence: `workspace/implementation/results.{1..8}.json`, all **84/84 passed, 0 failed, 0 errors**.

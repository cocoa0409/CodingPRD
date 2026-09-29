# Worklog — task_2642_medical_office_building_leasing_referral_compliance

## Step 1: Create task directory — 2026-09-03T23:47:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2642_medical_office_building_leasing_referral_compliance` and its `workspace/` subdirectory. Index 2642 was pre-assigned by the invoking pipeline; no scan of ./tasks/ was performed.

## Step 2: Generate Scaffold — 2026-09-04T01:40:00.000Z

All three artifacts are complete and the lint is clean.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2642_medical_office_building_leasing_referral_compliance/`)

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2777 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1809 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4876 |

`SCAFFOLD.yaml` contains zero occurrences of either `scaffold_difficulty_design` or `scaffold_corner_design`; each design file has exactly one top-level key.

**Lint verdict (verbatim, final run)**
```
Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     12
  §1.8 instances scanned:     19
  §1.9 instances scanned:     68
  Calls scanned (§1.8+§1.9):  1214

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Counts** — 12 entities, 7 state machines, 4 OCC rules, 11 calculations, 46 prioritized validations, 51 endpoints (17 GET / 32 POST / 1 PATCH / 1 DELETE), 45 error entries, 6 roles (`segregation_of_duties`), `difficulty_level: expert_plus`.

§1.8: 19 instances across all 9 difficulty rules (3 in `combinatorial_formula`, 2 in each other). §1.9: 100 instances over all 9 guide sections — 68 full recipes + 32 `excluded_because` stubs — as entities 15, state_machines 23, calculations 19, validations 17, endpoints 8, errors 7, rbac 4, complexity_layers 6, consistency_model 1. Verified programmatically: every stub's `difficulty_instance` resolves to a real §1.8 name, no stub carries a `test_recipe`, no duplicate names across both files, and **every** `ERR_*` code in SCAFFOLD.yaml is exercised by at least one design instance (0 uncovered).

**Design decisions worth recording**

- The lint's check (b) rejects any `as:` role not permitted by §1.5, so negative-RBAC and missing-header claims cannot be written as structured calls. Both `every_role_is_refused_another_roles_exclusive_operation` and `absent_or_unknown_identity_headers_are_refused_before_authorization` therefore specify each denied request in full (method, path, body, header) inside the `assert:` lines, keep only legal verification reads in `trigger:`, and state that convention explicitly in `setup:`. This is the pattern to reuse for any RBAC/auth corner in this scaffold family.
- Because §1.8's nine rules include no OCC rule, all three `ERR_STALE_*` codes are covered for real in the §1.9 `complexity_layers` section, one instance per §1.2.1 concurrency rule. Two of them double as ordering probes: a sibling appraisal create bumps `Lease.version` and staleness the editor's pending PATCH, and priority 12 (stale project version) masks priority 14 (`ERR_INVALID_TI_STATE`) so only a caller holding the current version learns the project has left DESIGN.
- The `derived_field_reconciliation` instance exploits a deliberate asymmetry in the declared cancel semantics: `IN_REVIEW -> CANCELLED` zeroes `landlord_committed_amount`/`tenant_committed_amount` and restores `allowance_remaining` to `authorized_allowance_total`, while `line_item_count` and the immutable `TILineItem` rows keep their resolved shares — so the parent rollups (0.00) intentionally no longer equal the sum of the children (42000.00).
- The `consistency_model` instance asserts both halves of `immediate`: a write's own response already carries its recomputed cascade fields (and a repeat GET is identical, so reads never converge), while advancing the clock past a term start, a due date and the 10-day grace changes nothing until `POST /_ops/run-daily-close` is called.
- Two latent ambiguities in SCAFFOLD.yaml were routed around rather than asserted: `radius_restriction_miles` ("0 disables" in the field description vs "non-null" in validation 24 — the passing case uses a different specialty), and `revision_round` (field description says "times returned to DRAFT", validation 17 counts a material PATCH — recipes use at most one material PATCH and finish with the explicitly non-material `radius_restriction_miles` edit).
- Building version arithmetic is asserted with literals (`create 1, suite create 2, execute 3, commence 4`) derived from the declared per-endpoint side effects, and the parking instance proves a *revocation* also invalidates an earlier read even though it frees the very stalls the retry wanted.
- Hard constraint honored: no sibling `task_*/` directory was listed, globbed, grepped or read at any point; every literal was re-derived from this scaffold's own formulas.

## Step 3: Copy Shared Files — 2026-09-04T01:41:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T02:00:00.000Z

PRD generation for task_2642 is complete.

**Output:** `workspace/PRD.md` — **485 lines**, built with 14 chunked `cat >>` appends (34 → 83 → 129 → 186 → 208 → 238 → 258 → 282 → 304 → 326 → 346 → 358 → 378 → 411 → 436 → 485), each verified with `wc -l`. The file ends at a real boundary: the final row of the §5 error table (`ERR_PATIENT_PARKING_RESERVE_BREACH | 422`). No audit footer was written into the document.

**Sections**
- `## 1. Introduction` (3 paragraphs)
- `## 2.` §2.1 RBAC (6 roles, opaque vs `entity_backed:Tenant`, both segregation-of-duties comparands) · §2.2 response envelope (verified **byte-identical** to `section-2.2-response-structure.md`) · §2.3 pagination (10/1/100/0, `created_at` ASC) · §2.4 identity/timestamps/`version` incl. the TILineItem no-`version` exception · §2.5 logical clock from `2026-08-01T00:00:00Z` + the six fixed close phases · §2.6 money/percentage rounding · §2.7 all 4 OCC rules · §2.8 the full **46-rung** rejection ladder with error id, status and guarded-endpoint set per rung · §2.9 tenant-mix posture gate · §2.10 cascade discipline
- `## 3.` nine subsections: 3.1 reference data & mix freeze · 3.2 tenant risk (both scoring variants) · 3.3 lease drafting/amendment/withdrawal · 3.4 appraisals & FMV certification · 3.5 execution/commencement/termination (depth-4 cascade) · 3.6 TI projects & the fork-join reviews · 3.7 billing, arrears aging, depth-3 delinquency cascade, write-off, holdover · 3.8 compliance cases, reopen cycle, cure compensation · 3.9 shared-space seat sweep, after-hours gate, parking pool
- `## 4.` 1 intro paragraph + **51 rows**, exactly 4 columns; every scaffold `method`+`path` pair matched programmatically
- `## 5.` **45 rows**, exactly 2 columns, scaffold order

**Hard Contract 1 — Field-Name Coverage: PASS.** Required inventory = 138 `entities[].fields[].name` + 96 endpoint `input`/`query_params` identifiers = 167 distinct tokens. Pass 1 found exactly one gap (`ti_project_id`), fixed in §3.6 by stating that the server sets a line item's `ti_project_id` from the addressed project. Pass 2 re-ran the full diff: **0 missing**. All 45 `errors[].id` also appear verbatim in backticks.

**Hard Contract 2 — Rule Coverage: PASS.** All **49** state-machine transitions across the 7 machines are represented (arrow-form for 33; the remainder — the three termination sources, the TI `CANCEL`/`ON_HOLD`/self-loop edges, appraisal disqualification from either source state, both payment routes, both cure routes, and the booking auto-complete — are covered in explicit prose, individually confirmed by grep). All 4 `concurrency_rules[]` name write endpoint, `expected_<parent>_version`, error id and 412. All 46 validations appear as ordered rungs with `applies_to` endpoint sets. All 10 calculations carry formula, constants, precision and pinned evaluation order, including the 3 dual-variant ones and the counter-intuitive parking-waiver tier keyed on the combined `pre_waiver_total`. Sibling branches given equal density (shielding vs utility review; hop-3 `DRAFT` vs `PENDING_FMV_REVIEW` suspension; `EXECUTED`-never-commenced vs `ACTIVE` termination).

**Hard Contract 3 — §3 Path Purity: PASS.** Mechanical scan of every backticked token between `## 3.` and `## 4.`: **0** tokens starting with `/`, 0 bare HTTP methods, 0 method+path combinations; a second scan for unbackticked raw paths also returned 0. Paths appear only in §2.7/§2.8 and §4, which the contract permits.

**Style checks:** grep for `:=`, `==`, `>=`, `<=`, `!=`, `ceil(`, `round(`, `abs(`, "approximately", "roughly", "conservatively" returns nothing — no pseudocode, operator syntax or fuzzy quantifiers.

The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or grepped, and no sibling `task_*/` directory was read.

**Orchestrator verification:** `wc -l` = 485; tail shows a complete final table row (no mid-sentence truncation); `## ` headings present for sections 1–5; grep for "harder than expert" / "expert level" / "scaffold" / "difficulty_level" in PRD.md returns nothing — the Step 2 difficulty instruction did not leak.

## Step 5: Generate Unit Tests — 2026-09-04T02:50:00.000Z

Suite complete. Final state at `/home/ubuntu/github/CodingPRD/tasks/task_2642_medical_office_building_leasing_referral_compliance/`.

## Output (task root, nothing under `workspace/`)

`test_helpers/` — 2138 lines total: `__init__.py` 119, `api_client.py` 200, `api_errors.py` 104, `assertions.py` 392, `constants.py` 95, `factories.py` 240, `fixtures.py` 455, `test_users.py` 71, `types.py` 462.

`test_suite/` — `conftest.py` 46; queue A: `test_01_dual_variant_calc.py` 157, `test_02_combinatorial_formula.py` 227, `test_03_non_linear_state_machine.py` 144, `test_04_transitive_cascade.py` 256, `test_05_priority_pair_validation_conflict.py` 174, `test_06_boundary_precision_check.py` 163, `test_07_cross_entity_state_dependency.py` 192, `test_08_resource_temporal_overlap.py` 231, `test_09_compensating_invariant.py` 191; queue B: `test_20_corner_entities.py` 538, `test_21_corner_state_machines.py` 1027, `test_22_corner_calculations.py` 725, `test_23_corner_validations.py` 769, `test_24_corner_endpoints.py` 379, `test_25_corner_errors.py` 224, `test_26_corner_rbac.py` 293, `test_27_corner_complexity_layers.py` 408, `test_28_corner_consistency.py` 172.

## Verification (scripted, whole suite)

- **106 tests**, `pytest --collect-only` collects all 106; `py_compile` passes on every file; `pyflakes` clean on `test_suite/`.
- **Design-tag pass: 0 problems.** Every test has exactly one `Design:` line, always the docstring's last line. 38 `Difficulty/` tags + 68 `Corner/` tags. Zero dangling tags, zero dual tags, zero tags pointing at an `excluded_because:` stub (32 stubs, all silent).
- **Coverage: 87 of 87 non-stub instances translated, 0 skipped.** Queue A 19/19, each with exactly 2 tests (the ≥2 floor is met everywhere). Queue B 68/68 with ≥1 test each.
- **Citation pass: 389 quoted PRD segments, 0 misses** under whitespace-normalised literal containment against `workspace/PRD.md`.

## PRD gaps / adjudications (PRD beat the design yaml every time)

- No `RETURNED_FOR_REVISION` status and **no `PAID` invoice status** exist in the PRD; assertions naming them were replaced with the fields the PRD does define (`amount_paid`, `paid_on`, `status != "DELINQUENT"`).
- `GENERAL_SURGERY` is not a declared specialty (substituted `ORTHOPEDICS`); `fmv_certified_by_user_id` appears nowhere.
- `is_controlling == true` immediately after `QUALIFY` is not uniquely derivable (§3.4 marks it at certification) — dropped.
- §3.7 hop 3 has no dedup clause, so three flags in one close open three cases; the yaml's single-case/`risk_score_at_open == 100`/`HIGH` claim was dropped.
- Priority 3's exact-balance payment check precedes priority 15, so a repeated full payment yields `ERR_INVALID_REQUEST`, not the yaml's `ERR_INVALID_RECORD_STATE` — dropped.
- The §3.5 termination cascade cancels *every* `BOOKED` row, with no future-only filter (that qualifier belongs to §3.7).
- Status codes are never hardcoded: `set_error_http_status_map` carries §5, so `ERR_SEGREGATION_OF_DUTIES` 403, `ERR_INVALID_LEASE_STATE`/`ERR_INVALID_RECORD_STATE`/`ERR_OUTSTANDING_RENT_BALANCE` 409 and `ERR_INVALID_REQUEST` 400 are enforced by the map rather than by the yaml's guesses of 422.

The suite has not been executed — the sibling implementation generator was still running and `workspace/implementation/` was never read or written.

## Step 6: Generate Implementation — 2026-09-04T02:46:00.000Z

Implementation complete. All 51 declared endpoints are live and the app boots cleanly from `start.sh` on a fresh process.

## Files written (all under `workspace/implementation/`)

| File | Lines |
| --- | --- |
| `app.py` | 89 |
| `db.py` | 77 |
| `enums.py` | 68 |
| `errors.py` | 109 |
| `lookups.py` | 58 |
| `middleware.py` | 75 |
| `requirements.txt` | 1 |
| `response.py` | 58 |
| `serializers.py` | 292 |
| `start.sh` (exec) | 10 |
| `validators.py` | 264 |
| `routes/appraisals.py` | 142 |
| `routes/buildings.py` | 177 |
| `routes/cases.py` | 171 |
| `routes/invoices.py` | 162 |
| `routes/leases.py` | 705 |
| `routes/ops.py` | 35 |
| `routes/parking.py` | 131 |
| `routes/space.py` | 156 |
| `routes/tenants.py` | 71 |
| `routes/ti.py` | 391 |
| `services/calc.py` | 538 |
| `services/cascades.py` | 131 |
| `services/close.py` | 78 |
| `services/compliance.py` | 51 |
| **total** | **4040** |

## Endpoints: 51 of 51

Flask's URL map reports exactly 51 non-static rules, matching the PRD §4 table one-for-one. Storage is in-memory dicts only; nothing is seeded, and `created_at`/`updated_at` come from the logical clock (epoch `2026-08-01T00:00:00Z`), never wall-clock.

## Smoke verification

Ran four scripted end-to-end suites against a self-chosen port (18642, then 18643 through `start.sh`), each server killed by its exact recorded PID — no broad `pkill`. Verified: the full lease lifecycle through holdover; physician-owned FMV band intersection (25.20/30.80 from a 28.00 midpoint against a 22.40/32.20 published band); the six pinned invoice steps (5666.67 + 2000.00 + 8000.00 → 15666.67 pre-waiver → 50% tier → 11666.67); the closed-interval invoice overlap and the half-open seat sweep including the exactly-at-capacity admission (24 = 24 accepted, 25 refused) and the touching-windows non-overlap; rung 34 outranking rung 37; rung 21 outranking rungs 29/34/37; rung 12 outranking rung 44; the 400-stall patient reserve boundary (160 accepted, 161 refused); the depth-3+3b delinquency cascade (weight 50 → rolling 50 → WATCH → system-opened MEDIUM case → every lease including a DRAFT locked and after-hours cleared); write-off replacing the weight with 40; the depth-4 termination cascade; TI fork-join to PERMITTED, completion reclassifying the suite, and cancellation compensation. All four conserved invariants held after every operation (stall pool sums to `total_parking_stalls`; leased + vacant = total; committed + remaining = authorized; line-item shares sum exactly to `cost_amount`, e.g. 4000.00 + 6000.01 on a 10000.01 line).

## PRD ambiguities resolved

1. **Medical-gas error ID** — rung 19's text and rung 20's check-text disagree. Chose `ERR_SHIELDING_CERTIFICATION_MISSING`, evaluated **before** the power-capacity test, since two of the PRD's three statements agree on that ID.
2. **Undeclared error IDs.** Withdrawal blocked by a non-cancelled TI project → `ERR_TI_PROJECT_NOT_COMPLETE`. Qualifying an aged-out appraisal → `ERR_INVALID_RECORD_STATE`. A failed cure precondition (a still-`DELINQUENT` invoice, or a lease left `STALE`) → `ERR_INVALID_RECORD_STATE`. `REPORT` on a case below `HIGH` → `ERR_INVALID_RECORD_STATE`. Revoking an already-`REVOKED` allocation → `ERR_INVALID_RECORD_STATE`.
3. **`provisional_base_rent_annual` is genuinely frozen.** It is re-derived only at draft creation, at a material amendment of a `FMV_CERTIFIED` lease, on a term/rent `PATCH`, and at review submission — never at certification.
4. **The 1.50 holdover multiplier applies only to the certified variant.** A lease rolling into `HOLDOVER` while `STALE` is billed at the plain published figure with no premium.
5. **`days_past_due` is a stored field, not a live derivation.** It starts at 0, is written at the close that flags the invoice, keeps growing on later closes while `DELINQUENT`, and is refreshed on payment — while `days_past_due_at_flag` and `delinquency_tier_weight` stay frozen.
6. **Severity thresholds** read as `>= 90 HIGH`, `>= 45 MEDIUM`, else `LOW`, applied both to manual case opens and to the cascade.
7. **Manual case `risk_score_at_open`** is frozen from the tenant's stored score field for the requested variant, not from an ad-hoc live recomputation.
8. **`lead_thickness_mm` on a TI project** is optional and may be `0.00` for a non-`IMAGING` target; only `IMAGING` forces it present and strictly positive.
9. **Optional notes** (`cancellation_note`, `revocation_note`, `termination_note`, `review_note`) are accepted and validated but are not members of any declared response payload, so they are not serialized.
10. **Optimistic-concurrency fields are parsed during the rung-3 pass** so a malformed version still outranks a missing resource, while the equality comparison itself runs at its declared rung (10/11/12).
11. **Unknown paths and disallowed methods** both return 404 `ERR_RESOURCE_NOT_FOUND`, since the error vocabulary has no 405 member.

**Orchestrator note:** Steps 5 and 6 were launched back-to-back as background agents rather than in one message; physical isolation still held — the impl generator confirmed it never read `test_suite/`/`test_helpers/`, and `find workspace -type d -name 'test_*'` returns nothing, so both test directories live at the task root as required.

## Step 7: Run Tests and Iterate — 2026-09-04T03:15:00.000Z

All 8 rounds are green: 106/106 passed, 0 failed, 0 errors in every round (~187s each), sweep run under `setsid nohup` with 8 concurrent rounds.

## Summary

**Iterations run:** 2 sweeps (iteration 1 diagnosed 14 deterministic failures identical in all 8 rounds; iteration 2 after one batch of fixes was fully green).

**Tests deleted:** none. All 14 failures traced to verbatim PRD sentences or to bugs in the test artifacts themselves, so no test was PRD-silent or non-uniquely-derivable.

**Fixes applied to `test_helpers/`**
- `test_helpers/fixtures.py` — `file_attestation` now asserts HTTP 200 instead of 201. PRD §4 preamble: an endpoint that modifies an existing resource returns 200 with the updated resource in `data`, and §3.3 makes the attestation a write onto the lease ("Compliance documents are recorded against the lease rather than uploaded… writes `on_file` to `signed_lease_on_file`… advances the lease's `version` by 1"), so the fixture must hand back the Lease.
- `test_helpers/factories.py` — `next_suite_number()` now emits `1001, 1002, …` instead of `201, 202, …`; the old session-long counter eventually collided with hardcoded suite numbers ("210"/"220"/"230"), producing a spurious `ERR_INVALID_REQUEST — Suite number '210' already exists in this building` setup failure in test_24.

**Fixes applied to `test_suite/`**
- `test_suite/test_05_priority_pair_validation_conflict.py` — removed a double-index `validate_success(...)["data"]` in two places (`_frozen_building_with_an_over_ceiling_lease` and the thaw step); `validate_success` already returns `body["data"]`, so the extra subscript raised `KeyError: 'data'`. No assertion was weakened.

**Fixes applied to `implementation/`**
- `routes/leases.py::file_attestation` — returns `ser.lease_out(lease)` at HTTP 200 and no longer mints a `LeaseAttestation` row. The invented entity (with `attested_by_user_id` / `attested_on`) traces to no PRD sentence; PRD §3.3 says documents are "recorded against the lease rather than uploaded". This was the root cause of 8 failures (downstream `KeyError: 'after_hours_authorized'` / `'master_lease_consent_on_file'` / `'space_sharing_schedule_on_file'` and `ERR_LEASE_NOT_FOUND` when the attestation id was mistaken for a lease id).
- `serializers.py::rent_invoice_out` — `days_past_due` is now emitted live as `max(0, calc.live_days_past_due(row))` instead of the stored value. PRD §2.10: "`days_past_due` on an invoice is recomputed against the clock on every read, so it grows even on days when no close has run"; the `max(0, …)` clamp comes from §3.7's "never below zero". `days_past_due_at_flag` stays frozen.
- `services/close.py` phase 1 (appraisal expiry) — after setting `fmv_certification_status = "STALE"` the lease is re-carried via `calc.apply_rent_variant(lease)`. PRD §3.4: while the status reads `NOT_STARTED`, `PENDING` or `STALE` the lease is carried at the rate card, so `effective_base_rent_annual` equals the provisional figure and `certified_base_rent_annual`, `fmv_variance_annual`, `fmv_variance_pct` are null. `status` is still deliberately left at `FMV_CERTIFIED` and no case is opened, per §3.5.
- Dead-code removal from the same change: `serializers.py::lease_attestation_out`, `db.py::Store.lease_attestations`, and `calc.attestations_of_lease` / `calc.has_attestation`. Storage remains in-memory only; nothing is seeded at startup.

Sweep artifacts (`results.*.json`, `sweep.log`) and `__pycache__` were cleaned up afterwards.

**Orchestrator verification (independent re-run):** because the subagent deleted its `results.*.json`, the orchestrator re-ran the identical 8-round sweep itself under `setsid nohup` and confirmed the claim: all 8 rounds report `106 / 106`, `failed=0`, `errors=0`. The results files from that verification sweep are retained at `workspace/implementation/results.{1..8}.json`.

## Step 8: Finalize PRD — 2026-09-04T03:23:00.000Z

Done. `PRD_FINALIZED.md` written with four in-place sentence patches.

## Line counts
- `PRD.md`: 485 lines — `PRD_FINALIZED.md`: 485 lines — **0.0% delta** (4 lines revised in place, no lines added/removed). Tail verified byte-identical from §5 through the last row `| ERR_PATIENT_PARKING_RESERVE_BREACH | 422 |`, so the document still ends at the same real section boundary.

## Changes
- **§2.10 (line 207) — revise** — `days_past_due` live read is now pinned as "whole calendar days from `due_date` to the clock date, floored at zero so a not-yet-due invoice reads 0 rather than a negative figure"; `days_past_due_at_flag` noted as written from the unclamped count at the flagging close — `serializers.py:209`, `services/cascades.py:92-95`.
- **§3.3 (line 255) — insert** — attestation filing is a write onto the lease and nothing more: no attestation row is persisted, `document_reference` is a required non-empty string that is not retained, and the call answers **HTTP 200 with the updated lease** rather than 201 with a new resource — `routes/leases.py:522-541`, `db.py:14-29`.
- **§3.4 (line 281, appraisal expiry) — insert** — on expiry of a controlling opinion behind an `FMV_CERTIFIED` lease, the same close re-carries the lease under the provisional variant: `effective_base_rent_annual` falls back to the already-frozen `provisional_base_rent_annual` (not re-derived), the three figures `certified_base_rent_annual` / `fmv_variance_annual` / `fmv_variance_pct` clear to null, and `certified_fmv_floor_psf` / `certified_fmv_ceiling_psf` are left standing — `services/close.py:25-32`, `services/calc.py:205-229`.
- **§3.4 (line 267, disqualify-on-occupied branch) — insert** — required by the NO-NEW-MISMATCH enumeration for the edit above: on the `EXECUTED`/`ACTIVE`/`HOLDOVER` branch **no** rent re-carry runs; band figures, certified/effective rent and both variance fields stay exactly as certification recorded them until a later operation re-carries the lease — `routes/appraisals.py:131-141`.

Not patched (no PRD silence/mismatch): the `next_suite_number()` factory collision and the `test_05` double-index were pure test-artifact bugs (suite-number uniqueness is already verbatim in §3.1); the dead-code removals (`lease_attestation_out`, `Store.lease_attestations`, `calc.attestations_of_lease/has_attestation`) removed an entity the PRD never declared, so the §3.3 edit above is the only prose consequence.

## Per-edit pre-edit search log
1. **§2.10 `days_past_due`**
   - (a) Subject: every producer and consumer of `days_past_due` / `days_past_due_at_flag`.
   - (b) Enumerated via `grep -rn days_past_due implementation/`: `serializers.py:209` (live, clamped), `services/close.py:39` (stored write for `DELINQUENT`, clamped) and `:43` (unclamped count for the grace test), `services/cascades.py:92-95` (stored clamped + raw flag), `routes/invoices.py:73` (created at 0) and `:121` (payment refresh, clamped), `services/calc.py:425-435` (`live_days_past_due` unclamped, tier keyed on the raw count).
   - (c) Adjustment: kept §3.7's "the figure is negative before the due date arrives" untouched, because the *day count* used for the grace/tier test is genuinely unclamped; the clamp claim was scoped to the field's read value only, and the flag was described as unclamped to match `cascades.py:95`.
2. **§3.3 attestation**
   - (a) Subject: the attestation endpoint's persistence and response shape, plus the three document booleans it writes.
   - (b) Enumerated: `grep -ri attestation implementation/` → `routes/leases.py:522-541` only writer; `enums.py:32`; `errors.py:77-79` (messages only); no serializer, no store (`db.py:14-29`); `grep -rn "201" routes/` to confirm every genuinely creating endpoint returns 201 and this endpoint is the sole 200-returning POST that looks like a creator; `validators.get_string` default (`required=True`, non-empty) for `document_reference`; readers of the three booleans at execute/booking gates.
   - (c) Adjustment: wording scoped to "this filing" rather than to POST sub-resources generally, so the 201 contract of the twelve real creators is untouched.
3. **§3.4 appraisal expiry re-carry**
   - (a) Subject: every site that sets `fmv_certification_status` and every `apply_rent_variant` / `recompute_provisional_rent` callsite.
   - (b) Enumerated via grep: `close.py:26-32` (expiry, re-carry without provisional re-derivation), `close.py:52-55` (holdover roll, re-carry), `routes/leases.py:223-224` (draft), `:347-363` (material amendment — provisional *is* re-derived here), `:413-418` (review submission freeze), `:441` (`RETURN_FOR_REVISION`, no re-carry), `:508-509` (certification), `routes/appraisals.py:121-129` (disqualify → `FMV_CERTIFIED` branch, re-carry) and `:134-135` (occupied branch, **no** re-carry), `services/cascades.py:47` (suspension → `NOT_STARTED`, no re-carry), `calc.py:205-229` (the provisional branch does *not* clear the band floor/ceiling), `routes/cases.py:145` (cure precondition reads the status).
   - (c) Adjustments: (i) scoped to "the same close" so it makes no universal STALE⇒re-carry claim; (ii) said `provisional_base_rent_annual` "is not itself re-derived" to stay compatible with the amendment path; (iii) named only the three fields `apply_rent_variant` nulls and noted the band figures survive.
4. **§3.4 disqualify-on-occupied caveat**
   - (a) Subject: same as edit 3 — the STALE state's effect on stored rent figures, at the one branch that opts out.
   - (b) Enumerated: `routes/appraisals.py:112-141`, `calc.OCCUPYING_LEASE_STATUSES` (`calc.py:69`), the only later re-carry reachable for such a lease (`close.py:52-55` holdover roll), the certify guard (`PENDING_FMV_REVIEW` only).
   - (c) Adjustment: added the open-ended clause "until some later operation re-carries the lease" rather than asserting permanence.

**Orchestrator verification:** `wc -l` 485 vs 485; `diff` shows 8 changed lines (4 revised in place); files are not byte-identical, so the finalizer really ran; tail is the complete final §5 table row.

## Step 9: Complete PRD — 2026-09-04T04:07:00.000Z

Run as **three sequential file-partitioned passes** over `implementation/` rather than one scan, so a silent no-op (PRD_COMPLETED.md byte-identical to PRD_FINALIZED.md) could not slip through. Pass 1 owned the `cp`; passes 2 and 3 were explicitly forbidden from re-copying or whole-file-writing the document, and each used Edit-only patches.

**Final size:** PRD.md 485 lines / 120,881 chars → PRD_FINALIZED.md 485 / 122,166 → **PRD_COMPLETED.md 485 lines / 136,946 chars** (+14,780 chars over PRD.md; +16,065 over the source PRD, all as in-paragraph inserts/revisions — no line added or removed, no new sections). 5 `## ` headings intact; tail is the complete final §5 row.

**Totals across the three passes: 63 patches — 50 ambiguity-pins, 13 mismatch-revisions.** `diff PRD_FINALIZED.md PRD_COMPLETED.md` reports 53 changed lines, so the scan demonstrably ran.

### Pass 1 (app.py, db.py, enums.py, errors.py, lookups.py, middleware.py, response.py, validators.py, serializers.py, routes/leases.py) — 15 ambiguity-pins, 5 mismatch-revisions
- §2.1 — insert — ambiguity — a present-but-blank/whitespace `X-User-ID`/`X-User-Role` is `ERR_UNAUTHENTICATED` — middleware.py:25-28
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from real elapsed time, not the logical clock — response.py:21-23
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion sequence — db.py:73-76
- §2.4 — insert — ambiguity — timestamps read from the logical clock; pre-clock-move rows read `2026-08-01T00:00:00.000Z` — db.py:47-50
- §2.4 — insert — ambiguity — window/opens/closes instants echoed back verbatim, truncated to whole seconds — serializers.py:248-261; validators.py:199-208
- §2.6 — insert — ambiguity — decimals serialise as JSON numbers (5000.00 → `5000.0`) — serializers.py:10-15
- §2.8 rung 3 — insert — ambiguity — cross-field comparison against a stored value deferred past rungs 7/10/13 — leases.py:285-292
- §2.8 rung 9 — insert — ambiguity — the four top-level collections apply tenant scope as a silent filter (with `total_count`), not a refusal — leases.py:250-251
- §2.8 rung 13 — insert — ambiguity — after-hours authorization joins the "any status other than TERMINATED/WITHDRAWN" family — leases.py:683
- §2.8 rung 17 — revise — mismatch — the revision cap only bites where the counter would advance — leases.py:305
- §2.8 rung 24 — revise — mismatch — radius conflict requires `radius_restriction_miles` > 0, not merely non-null — leases.py:121-123
- §2.8 rung 38 — revise — mismatch — added the withdrawal condition and `DELETE /leases/{id}` to the guard list — leases.py:374-380
- §3.3 ¶241 — insert — ambiguity — non-null `master_lease_id` on a DIRECT/MASTER draft is `ERR_INVALID_REQUEST` — leases.py:176-179
- §3.3 ¶247 — insert — ambiguity — materiality decided by key presence; explicit null clears specialty/radius, null rent/term ignored — leases.py:278-343
- §3.3 ¶247 — revise — mismatch — same narrowing of the revision cap as rung 17 — leases.py:305
- §3.3 ¶249 — insert — ambiguity — a surviving TI project refuses withdrawal with `ERR_TI_PROJECT_NOT_COMPLETE` — leases.py:376
- §3.4 ¶279 — insert — ambiguity — an already-correct `is_controlling` is not touched (no version bump); non-physician tenants leave all false — leases.py:503-507
- §3.5 ¶303 — insert — ambiguity — a `FROZEN` posture refuses reinstatement with `ERR_BUILDING_MIX_RESTRICTED` — leases.py:449-453
- §4 intro — insert — ambiguity — unmatched path/method → 404 `ERR_RESOURCE_NOT_FOUND`, routed ahead of authentication; trailing slashes insignificant — app.py:31,51-64
- §4 `DELETE /leases/{id}` — revise — mismatch — dropped "releasing the suite" (a draft holds no reservation) — leases.py:371-389

### Pass 2 (routes/buildings.py, tenants.py, appraisals.py, ti.py, ops.py) — 17 ambiguity-pins, 5 mismatch-revisions
- §2.3 — insert — ambiguity — query filter identifiers never existence-resolved; unmatched id yields zero rows, not 404 — ti.py:124-137
- §2.5 — insert — ambiguity — `close_note` untyped and retained nowhere; clock-set and close answer 200 with empty `data` — ops.py:19-35
- §3.1 suites — insert — ambiguity — duplicate `suite_number` → `ERR_INVALID_REQUEST` after building lookup and freeze test; `power_amps_available` required int ≥0; `lead_thickness_mm` ≥0 ≤2dp — buildings.py:82-98
- §3.1 shared spaces — insert — ambiguity — `closes_at` ≤ `opens_at` → `ERR_INVALID_REQUEST` before building resolution; registration does **not** bump the building `version` — buildings.py:147-165
- §3.1 mix freeze — insert — ambiguity — `reason` required non-empty, validated then discarded — buildings.py:69
- §3.4 filing — insert — ambiguity — future `appraisal_date` → `ERR_INVALID_REQUEST` at the body rung; `independence_attested` required — appraisals.py:36-42
- §3.4 qualification — insert — ambiguity — expired → `ERR_INVALID_RECORD_STATE`; closed lease → `ERR_INVALID_LEASE_STATE`; no controlling mark, no lease version bump — appraisals.py:95-110
- §3.4 disqualify (certified) — insert — ambiguity — `revision_round` increments unconditionally, past the cap, since rung 17 does not guard this endpoint — appraisals.py:123
- §3.4 disqualify (occupied) — insert — ambiguity — severity forced `HIGH`; `risk_score_at_open` is the live rolling figure; tenant row untouched — appraisals.py:131-141; compliance.py:38-49
- §3.6 project create — insert — ambiguity — non-demised `suite_id` → `ERR_SUITE_NOT_FOUND`; IMAGING thickness defect precedes suite/lease resolution — ti.py:69-81
- §3.6 project defaults — insert — ambiguity — opening a project advances no lease/suite/building `version` — ti.py:88-109
- §3.6 transitions — insert — ambiguity — `note` dropped; SUBMIT_REVIEWS defect order: `ERR_INVALID_TI_STATE` then `ERR_INVALID_LEASE_STATE` — ti.py:217-247
- §3.6 START_CONSTRUCTION — insert — ambiguity — negative `allowance_remaining` → `ERR_TI_ALLOWANCE_EXCEEDED` — ti.py:258-262
- §3.6 reviews — insert — ambiguity — no review row persisted, `review_note` dropped, 200 with updated project; thickness shortfall → `ERR_SHIELDING_CERTIFICATION_MISSING` — ti.py:290-318
- §3.6 utility review — insert — ambiguity — medical-gas test precedes the amperage test — ti.py:320-331
- §3.6 cancellation — insert — ambiguity — review-dimension statuses and `line_item_count` are not rewound — ti.py:268-277
- §3.6 close-out — insert — ambiguity — both-approved gate `ERR_INVALID_TI_STATE`, negative allowance `ERR_TI_ALLOWANCE_EXCEEDED` — ti.py:368-380
- §4 `POST /buildings` — revise — mismatch — "campus relationship" input does not exist → published rate card — buildings.py:25-33
- §4 `POST /buildings/{id}/suites` — revise — mismatch — suites carry no asking rate → panel capacity — buildings.py:82-89
- §4 `POST /ti-projects/{id}/transitions` — revise — mismatch — only `SUBMIT_REVIEWS`, `START_CONSTRUCTION`, `CANCEL` accepted — enums.py:49; ti.py:223-268
- §4 `POST /ti-projects/{id}/reviews` — revise — mismatch — "code review" → utility review — enums.py:50
- §4 `POST /ti-projects/{id}/complete` — revise — mismatch — reclassification is unconditional — ti.py:385

### Pass 3 (routes/invoices.py, cases.py, parking.py, space.py, services/calc.py, cascades.py, close.py, compliance.py) — 18 ambiguity-pins, 3 mismatch-revisions
- §2.5 — insert — ambiguity — the phase-6 sweep writes only where a figure moves; unchanged tenants keep their `version` — close.py:82; calc.py:338-347
- §2.7 — revise — mismatch — the stall pool does not move on lease execution; only allocation, revocation and the termination cascade move it — calc.py:272; leases.py:607-608
- §2.8 rung 3 — insert — ambiguity — the `payment_amount` exactness comparison is deferred past rung 8 but still precedes rung 15 — invoices.py:103-116
- §2.8 rung 15 — revise — ambiguity — rung 15 now covers `ACTIVE`-only parking revocation — parking.py:119
- §3.4 — insert — ambiguity — the certification-trigger FMV case freezes `risk_score_at_open` from the ledger-recomputed rolling figure with derived severity — compliance.py:40-51; leases.py:512-518
- §3.4 — insert — ambiguity — a controlling appraisal expiring on a non-`FMV_CERTIFIED` lease leaves that lease wholly untouched — close.py:25
- §3.5 — insert — ambiguity — the termination cascade's parking recompute rides on hop 2's single building bump — cascades.py:31,67
- §3.7 — insert ×4 — ambiguity — invoice period need not be a calendar month and `due_date` is unconstrained; closed-interval overlap scan precedes term containment; issuing touches neither lease nor tenant; zero `payment_amount` is 400 and exactness outranks the state test — invoices.py:26-30,43,48,79-81,101-111
- §3.7 — insert ×2 — ambiguity — a later close writes nothing to an already-`DELINQUENT` invoice; hop 3's `WATCH` write folds into hop 2's bump — close.py:36-40; cascades.py:103,107
- §3.7 — revise — mismatch — the holdover roll recomputes rent under the §3.4 variant (×1.50 only when `CERTIFIED`); `holdover_premium_applied` true on both routes — close.py:52-54; calc.py:209-229
- §3.8 — insert ×4 — ambiguity — system-opened cases share the hand-opened shape with a server-generated `basis`; a hand-opened case reads the tenant's stored score and writes neither figure back; the `REPORT` severity gate is `ERR_INVALID_RECORD_STATE` after the status test; unmet `CURE` preconditions are `ERR_INVALID_RECORD_STATE`; the cure writes `CLEAR` on the no-blocking-case ground alone — compliance.py:19-34; cases.py:58-61,83,114-120,135,147,168-170
- §3.8 — revise — mismatch — `REPORT` writes nothing to the tenant; `REPORTED` re-raises the watch flag on every later recomputation — cases.py:113-127; calc.py:316-318
- §3.9 — insert ×3 — ambiguity — `cancellation_note`/`revocation_note` validated, may be empty, retained on nothing; revocation `ACTIVE`-only; allocation bumps the building `version` — space.py:135; parking.py:70-71,116,119

**Orchestrator verification:** `wc -l` 485 for all three PRDs; `cmp` confirms PRD_COMPLETED.md is NOT byte-identical to PRD_FINALIZED.md (53 lines changed), so no pass no-opped; 5 `## ` headings present; tail is the complete final §5 error-table row. `results.{1..8}.json` from the verified green sweep are retained under `workspace/implementation/`. `sweep.log` (spliced output of 8 concurrent rounds, not diagnostically usable) and stray `__pycache__` directories were removed.

## Pipeline complete — 2026-09-04T04:10:00.000Z

Steps 1–9 all executed. Final state: 106 tests, 8/8 sweep rounds at 106/106, PRD.md → PRD_FINALIZED.md (4 patches) → PRD_COMPLETED.md (63 patches).

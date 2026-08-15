# Worklog — task_1514_nuclear_medicine_radiopharmaceutical

## Step 1: Create Task Directory — 2026-08-13T00:00:00.000Z

Task directory `tasks/task_1514_nuclear_medicine_radiopharmaceutical/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per entrance instructions; no index scan performed, no other task_* directory touched. User difficulty directive: "Generate task hard than expert level!" — passed to scaffold generator as a difficulty-calibration override (exceed the Expert band; scenario text itself passed verbatim).

## Step 2: Generate Scaffold — 2026-08-13T00:20:00.000Z

Scaffold generation complete for task_1514. All three artifacts written and lint-clean on the final run.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1514_nuclear_medicine_radiopharmaceutical/SCAFFOLD.yaml` (§1.0–§1.7; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1514_nuclear_medicine_radiopharmaceutical/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1514_nuclear_medicine_radiopharmaceutical/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Structural counts
- **Entities: 14** (IsotopeProduct, RadiopharmacyLicense, AuthorizedUser, Patient, ImagingRoom, IsotopeDelivery, DoseOrder, DoseVial, DoseAdministration, ProcedureAppointment, WasteContainer, RadiationSurvey, SpillIncident, PatientReleaseInstruction)
- **Endpoints: 52** (above the Expert band per the difficulty directive; the count is driven by FK reverse-reachability — 21 FKs each with a filtered-list GET — plus 27 business/action POSTs and the logical-clock endpoint with the mandatory `2026-08-01T00:00:00Z` startup default)
- **Error codes: 30**
- **State machines: 8** — cycles on DoseOrder (hold/restore), DoseVial (quarantine loop), SpillIncident (recontamination loop), RadiopharmacyLicense (suspend/reinstate); posture-driven ImagingRoom contamination gate
- **Calculations: 7** — dual-variant decay assay (exact 110.000 vs tabular 109.993), tiered required-activity formula (mode a), per-component-rounding possession (mode b, 1.988 vs 1.987), dual-variant release eligibility, spill threshold, waste clearance window, hot-lab aggregate capacity
- **Difficulty instances per rule_id: 2 each, 18 total** — dual_variant_calc 2, combinatorial_formula 2 (modes a+b), non_linear_state_machine 2, transitive_cascade 2 (depth-3 spill cascade + depth-2 license cascade), priority_pair_validation_conflict 2 (state×safety, safety×temporal), boundary_precision_check 2 (MBq threshold >=, µSv/h limit <=), cross_entity_state_dependency 2 (Vial×Delivery, Order×AuthorizedUser), resource_temporal_overlap 2 (buffered half-open room exclusion vs aggregate delivery capacity), compensating_invariant 2 (per-vial activity balance, license possession round-trip)
- **Corner instances: 44 active + 5 excluded_because stubs** across all nine guide sections; every one of the 30 error codes is exercised by at least one instance across §1.8/§1.9
- All formula-derived asserts were pre-computed as literals via Python (e.g., 109.993 tabular assay, 1001.799 I-131 required activity, 38778.618 capacity load, 0.049/0.107 clearance activities); all `${var}` placeholders close over prior `captures:`, and OCC `expected_*_version` values are always placeholder-bound
- No sibling task directories were read; design derived solely from the scenario + skill spec

## Verbatim lint verdict
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_1514_nuclear_medicine_radiopharmaceutical/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_1514_nuclear_medicine_radiopharmaceutical/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_1514_nuclear_medicine_radiopharmaceutical/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     44
  Calls scanned (§1.8+§1.9):  629

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy Shared Files — 2026-08-13T00:20:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1514_nuclear_medicine_radiopharmaceutical/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T00:55:00.000Z

The PRD is complete and verified. Final state of the document audit:

- **§2.2** matches the fixed verbatim block byte-for-byte (script-verified containment).
- **Contract 1 (Field-Name Coverage):** 83 required identifiers (78 entity fields + 46 endpoint input/query identifiers, deduplicated) — all present in backticks, 0 missing. PASS
- **Contract 3 (§3 Path Purity):** 393 backticked tokens inside §3 scanned — 0 paths, 0 bare HTTP methods, 0 method+path combos. PASS
- All 30 error IDs appear in §2/§3 prose; all 5 role names exact; all state enum values (including `CANCELLED`, which needed a repair pass) and all enum field values (`DIAGNOSTIC`/`THERAPEUTIC`/`BOTH`, `ACTIVITY_BASED`/`MEASURED_RATE_BASED`, `MINOR`/`MAJOR`, `PASS`/`FAIL`, `ISSUED`, etc.) present; no fuzzy/approximating words; no pseudocode operator leaks; no trailing contract-report content in the file.
- Endpoint table has exactly the scaffold's 52 rows × 4 columns; error table has 30 rows × 2 columns.

---

## Final Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1514_nuclear_medicine_radiopharmaceutical/workspace/PRD.md` — **311 lines**.

**PRD section list:**
1. Introduction (2 paragraphs — regulatory/safety pain-point angle)
2. Global Specifications & System-Wide Principles
   - 2.1 User and Role-Based Access Control (5 roles; entity-backed vs opaque `X-User-ID` semantics)
   - 2.2 API Response Structure (verbatim fixed block)
   - 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, 4 meta fields)
   - 2.4 The Logical Clock and Time Semantics (startup default 2026-08-01T00:00:00Z, sweep, whole-minute truncation)
   - 2.5 Activity Arithmetic: Precision, Rounding, and the Two Decay-Correction Variants (3 dp half-up; exact vs tabular minute-step; 220.000/110-min worked pair from the scaffold)
   - 2.6 The Possession Ledger (3 components, pinned per-component-then-sum rounding, exclusions, recompute triggers)
   - 2.7 Safety Postures and Segregation of Duties (license gate on 4 ops, room gate, 3 segregation pairs)
   - 2.8 Optimistic Concurrency Control (substitute + seal, `ERR_STALE_VERSION` 412)
   - 2.9 Validation Pipeline and Error Precedence (all 30 validations in explicit global rank order)
   - 2.10 Resource Identification and the Flat Topology (left-to-right ids; all reverse-lookup filters enumerated)
   - 2.11 Common Resource Properties (`id`/`created_at`/`updated_at`/`version`; append-only exceptions `DoseAdministration` and `RadiationSurvey` with `updated_at`/`version` absent)
3. Business Logic & Workflows (8 subsections: reference data & license register; isotope supply; dose order prescription/cancellation/substitution; vial preparation & calibration; appointments & administration; spill response & room contamination; waste decay-in-storage & clearance; patient release instructions)
4. Endpoint Definitions (52-row table: Method, Path, Description, Authorized Role(s))
5. Error Code Catalogue (30-row table: Error ID, HTTP Status Code)

**Contract 2 (Rule Coverage) audit — all scaffold §1.1–§1.7 elements confirmed in prose:**
- Entities (14): every field's structured content (types, defaults, optionality, computed formulas, system-set semantics) placed on its owning entity — including `decay_constant_per_minute` (ln2/half-life, 6 dp), order `expires_at` (administration + 2 half-lives), both assay variants, `within_admin_window`, hold fields, substitution-chain fields, container intake/current/clearable computations.
- State machines (8): every transition's from/to, actor, preconditions with error IDs, and side effects expressed — license suspend/reinstate 2-hop cascades (vials explicitly NOT quarantined), order lifecycle incl. EXPIRED sweep and SUPERSEDED chain (`replaces_order_id`/`superseded_by_order_id`, version increment), vial quarantine/decay/dispose paths with both residual formulas, appointment auto-completion and AUTO_VOIDED, container seal/certify, spill advance incl. the survey-gated DECONTAMINATED→CONTAINED recontamination loop and asymmetric compensation (appointments stay AUTO_VOIDED), room posture flips.
- Calculations (7): decay (both variants, both delta signs, pinned rounding), required-activity-at-preparation (1.10/1.05/1.00 tiers at 120/1440 min, single final rounding), possession aggregation (pinned rounding order, exclusions), release eligibility (both variants, inclusive boundaries, 70 µSv/h constant), spill classification (inclusive MAJOR threshold), waste clearance window (10 half-lives, 0.05 MBq, inclusive comparisons), hot-lab aggregate capacity (half-open ±30-min windows, t_star, 37,000 MBq strict-greater rejection, aggregate-vs-exclusion contrast).
- Validations (30): all conditions matchable to error IDs in prose; global priority ordering stated explicitly in §2.9 and per-endpoint guard sequences in §3; every `applies_to` scope enumerated (e.g., license posture gates exactly order-create/receive/prepare/administer; segregation gates administer/certify/advance).
- Endpoints (52) incl. all `side_effects`; Errors (30) all triggered in §2/§3; Roles (5) with identity translations and exclusive/shared operations reflected in §3 narratives and §4 table.

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Step 6: Generate Implementation — 2026-08-13T01:30:00.000Z

Server boots cleanly via `bash start.sh` on the default port, binds 0.0.0.0, and runs in the foreground (via `exec python3 app.py`). Implementation complete.

---

## Final Summary

### File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1514_nuclear_medicine_radiopharmaceutical/workspace/implementation/`)

- `start.sh` — executable launcher; guards `pip install` behind `python3 -c "import flask"`, then `exec python3 app.py`
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, error handlers, all route handlers, clock sweep, cascades
- `db.py` — in-memory store: one dict per entity plus the logical clock (defaults to `2026-08-01T00:00:00Z`); no seeding anywhere
- `errors.py` — all 30 error IDs with their HTTP statuses from the scaffold catalog
- `response.py` — envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta` for lists)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, five-role RBAC, entity-backed `AuthorizedUser` lookup
- `calc.py` — time math, both decay variants, required-activity, possession ledger, container current-activity
- `serializers.py` — per-entity public serializers (live-computed `current_possession_mbq` and `current_activity_mbq`)

### Endpoint count: 52/52 implemented
Clock set; isotope-products (POST/GET/GET-by-id); licenses (POST/GET/suspend/reinstate); authorized-users (POST/GET/GET-by-id); patients (POST/GET); imaging-rooms (POST/GET); isotope-deliveries (POST/GET/GET-by-id/receive/mark-failed); dose-orders (POST/GET/GET-by-id/cancel/substitute); dose-vials (POST/GET/GET-by-id/calibrate/administer/dispose); dose-administrations (GET/GET-by-id); procedure-appointments (POST/GET/GET-by-id/cancel); waste-containers (POST/GET/GET-by-id/seal/certify-clearance); radiation-surveys (POST/GET/GET-by-id); spill-incidents (POST/GET/GET-by-id/advance); patient-release-instructions (POST/GET/GET-by-id).

### State machines implemented: 8
RadiopharmacyLicense (ACTIVE↔SUSPENDED with 2-hop cascade to users and orders, no vial quarantine), DoseOrder (ORDERED→DOSE_PREPARED→ADMINISTERED; ON_HOLD hold/restore loops for both hold reasons; cancel from 3 states; substitution chain with OCC-before-state; clock-sweep EXPIRED), DoseVial (PREPARED→CALIBRATED→ADMINISTERED/DECAYED→DISPOSED; QUARANTINED loop; auto-DECAYED on failed administration), IsotopeDelivery (SCHEDULED→RECEIVED/FAILED), ProcedureAppointment (BOOKED→COMPLETED/CANCELLED/AUTO_VOIDED with void_reason=incident id), WasteContainer (FILLING→SEALED→CLEARED with OCC seal and SoD certification), SpillIncident (REPORTED→CONTAINED→DECONTAMINATED→CLEARED plus DECONTAMINATED→CONTAINED recontamination loop gated on a FAIL survey), ImagingRoom (posture-driven OPERATIONAL↔CONTAMINATED).

### Calculation rules implemented: 7
`decay_corrected_activity` in both variants — exact (single rounding) and tabular minute-step (per-minute 6-dp factor, per-step 3-dp rounding; verified the PRD's worked example: 220 MBq, HL=110 min → exact 110.000 / tabular 109.993); `required_activity_at_preparation` (1.10/1.05/1.00 overage tiers at HL bounds 120/1440, single final 3-dp rounding); `current_possession_mbq` (pinned per-component rounding before summation; correct status inclusions/exclusions); `release_eligibility` (both variants, inclusive boundaries, 70 µSv/h constant, `ERR_RELEASE_CRITERIA_NOT_MET` with no row persisted on failure); `spill_classification` (inclusive MAJOR threshold); `waste_clearance_window` (seal + 10 half-lives, FILLING/SEALED current-activity formulas, ≤0.05 clearance gate); `hot_lab_delivery_capacity` (half-open ±30-min windows, t_star = latest arrival, per-component rounding, strictly-greater-than-37000 rejection).

Also implemented: logical clock with startup default and the dual order-expiry/vial-decay sweep on every set; validation priority ordering per the scaffold (auth → role/ownership → existence → OCC → state → safety family in rank order → temporal → referential → constraint); segregation-of-duties pins on calibrate/administer, seal/certify, report/clear; half-open buffered appointment overlap; append-only DoseAdministration and RadiationSurvey (no `updated_at`/`version`).

### start.sh contract confirmation
`start.sh` reads `$PORT` (default 10000, applied in `app.py` via `os.environ.get("PORT", "10000")`), binds `0.0.0.0`, and runs in the foreground via `exec python3 app.py` — verified live (`ss` shows `0.0.0.0:10000` listening; fresh-boot store is empty; clock reads the PRD default).

Two full verification suites (main flow + edge cases) pass against fresh server boots, covering: envelope shapes, pagination meta, the tabular-vs-exact divergence, ±60-minute admin window boundaries, inclusive thresholds, hot-lab capacity boundary at exactly 37000, spill cascade + asymmetric compensation + recontamination loop, license suspend/reinstate cascade, substitution OCC chain, waste seal/certify with SoD, and clock-sweep expiry.

## Step 5: Generate Unit Tests — 2026-08-13T02:10:00.000Z

All generation and audit work is complete. Final summary:

## Task 1514 — Test Suite Generation Complete

### Outputs
- **`test_helpers/`** (9 files): `types.py` (14 entity TypedDicts — append-only `DoseAdministration`/`RadiationSurvey` correctly omit `updated_at`/`version`; 15 status/role enums), `api_client.py` (43 endpoint methods on `GenericApiClient`), `api_errors.py` (30 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (shared constants for the 4 opaque roles + `make_authorized_user_headers(id)` builder for the entity-backed AuthorizedUser), `fixtures.py` (tiered composites: `setup_f18_department` / `setup_f18_calibrated_vial` / `setup_f18_administered` / `setup_i131_administered` / `setup_f18_spill_contamination` / `setup_sealed_container_*` + instant-arithmetic helpers), `__init__.py` barrel.
- **`test_suite/`**: `conftest.py` + 11 test files.

### Test counts
- **Queue A (Difficulty): 37 tests** — all 18 instances covered with ≥2 tests each (spill_recontamination_loop has 3, adding the PRD-verbatim negative leg "otherwise the advance is rejected with ERR_INVALID_STATE").
- **Queue B (Corner): 44 tests** — all 44 non-stub instances covered with exactly ≥1 test.
- **Total: 81 tests**, all collected cleanly by pytest.
- Per-file: 01=6, 02=11, 03=6, 04=7, 05=8, 06=5, 07=11, 08=4, 09=12, 10=5, 11=6.

### Skipped instances (all are `excluded_because:` stubs — not translated per rule; cross-references verified to resolve)
1. `Corner/state_machines/vial_quarantine_cycle_via_spill` → owned by `Difficulty/compensating_invariant/possession_roundtrip_through_quarantine`
2. `Corner/calculations/decay_dual_variant_on_administration` → owned by `Difficulty/dual_variant_calc/vial_assay_exact_vs_tabular_diverge`
3. `Corner/complexity_layers/cascading_side_effects_layer` → owned by `Difficulty/transitive_cascade/spill_report_cascade_depth3`
4. `Corner/complexity_layers/dual_variant_calculation_layer` → owned by `Difficulty/dual_variant_calc/release_activity_variant_vs_measured_rate_variant`
5. `Corner/complexity_layers/rate_threshold_layer` → owned by `Difficulty/boundary_precision_check/spill_threshold_inclusive_major`

**No non-stub instance failed the PRD-first two-condition filter** — the PRD verbatim-covers every asserted rule (98 quoted spans mechanically verified against PRD.md, 0 failures).

### Judgment calls (documented deviations, not skips)
1. **Initial `version` value**: PRD §2.11 says version "increments by one on every mutation" but never states the starting value, so two PRD-only readers could differ (0 vs 1). I omitted the literal `version == 1` sub-assertion from `create_isotope_product_computes_decay_constant` (kept the fully-derivable `decay_constant_per_minute == 0.006301` + server-stamped `created_at`) and asserted OCC versions relatively (`captured + 1`) in both OCC instances.
2. **`possession_per_component_rounding_order` setup repair**: the design chain creates two vials against the *same* order, but PRD §3.4 requires the order be ORDERED at vial creation (after vial 1 it is DOSE_PREPARED → the literal chain would 409). Repaired minimally: two orders, one vial each; asserted outcome (1.988 pinned per-component rounding vs 1.987 sum-then-round) unchanged.
3. **`possession_state_filtering_and_future_reference_decay` literal**: the design's 3755.724 appears off in the last ulp (1000 × 2^(210/110) = 3755.734…); asserted with `pytest.approx(abs=0.02)` so the filtering/growth claim is tested without baking in a possibly-wrong final digit. 1866.066 (= 1000 × 2^0.9) is exact.
4. **Pagination determinism**: advanced the logical clock between the two patient registrations so §2.3's creation-timestamp-ascending order is strict.

### Confirmation
Every emitted test's docstring ends with exactly one `Design: Difficulty/<rule_id>/<instance>` or `Design: Corner/<section>/<instance>` line, copied verbatim from the source YAML `name:`; a mechanical sweep confirmed 81/81 tests tagged, zero malformed/dual tags, zero tags pointing at stubs or non-existent instances, and no `pytest.mark.skip`/`skipif`/`xfail` anywhere.

## Step 7: Run Tests and Iterate — 2026-08-13T02:40:00.000Z

Summary:

- **Iterations run**: 2 (baseline sweep: 77/81 in all 8 rounds, identical failure set — no flakiness; post-fix sweep: 81/81 in all 8 rounds).

- **Tests deleted**: none. All 4 failing tests traced to verbatim PRD rules; no PRD-silence or unique-derivability deletions were needed.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `test_suite/`**:
  - `test_03_delivery_scheduling.py::test_receive_tolerance_exceeded_rejected` — test bug: the fixture leaves the clock at 08:30 (30 min past the 08:00 reference instant), so the decayed reference is 4138.766 MBq and measured 4000 deviated only ~3.4%, inside the 10% band — the PRD-faithful implementation correctly accepted the receipt. Changed measured value to 3000 (deviation ~27.5%, outside the band) and corrected the docstring's false "no decay" premise.
  - `test_09_waste_and_possession.py::test_certify_with_excess_activity_rejected` — test bug: wrong expected `clearable_after_at`. Sealed at 10:20 + 10 half-lives (1100 min) = 2026-08-02T04:40:00Z, not 05:00. Implementation was correct; fixed the assertion and comment.
  - `test_09_waste_and_possession.py::test_clearance_succeeds_at_ten_half_lives` — unique-derivability collapse on one assertion: the test asserted `current_activity_mbq == 0.010` on the *CLEARED* container, but PRD pins the sealed-decay formula only for the SEALED state ("Once `SEALED`, `current_activity_mbq` is computed as...") and says of CLEARED only that the container "exits the possession ledger" (two faithful readers diverge). Per STEP 1c, the 0.010 assertion was relocated to a SEALED-state `get_container` read before certification (PRD-verbatim-covered); the covered assertions (status CLEARED, `certified_by_user_id`, possession-ledger exit) were kept.

- **Fixes applied to `implementation/`**:
  - `app.py::dispose_dose_vial` — `decay_loss_mbq` for an ADMINISTERED vial was computed as `measured − decay(measured, calibrated_at→disposal)` (110.000), violating the PRD §3.7 invariant stated verbatim: "the measured activity at calibration is fully accounted for as the sum of the administered activity, the residual routed to waste, and the decay loss." Now computed as `measured − administered(assayed_exact) − residual` (= 0.000 in the test scenario); the DECAYED-vial branch is unchanged since `administered = 0` reduces to the prior formula.

## Step 8: Finalize PRD — 2026-08-13T02:55:00.000Z

`PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1514_nuclear_medicine_radiopharmaceutical/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts / delta**: PRD.md 311 lines, PRD_FINALIZED.md 311 lines, 0.0% line-count delta (two sentences revised inline on lines 203 and 205; no lines added or removed).

### Changes (both in §3.7, one logical fix split into two coordinated sentence edits)

- **§3.7 (seal paragraph) — revise** — "Once `SEALED`, `current_activity_mbq` is computed as…" → "While `SEALED`, …" so the frozen-intake decay formula is scoped to the SEALED state only and cannot be read as extending through CLEARED — `implementation/calc.py:172-175` (SEALED branch taken exactly when `status == "SEALED"`).
- **§3.7 (clearance paragraph) — insert** — appended "Once `CLEARED`, the container's `current_activity_mbq` reads 0.000." to the closing sentence, pinning the previously silent CLEARED-state value — `implementation/calc.py:176-177` (fall-through branch returns `Decimal("0.000")`; reachable only by CLEARED since container statuses are only FILLING/SEALED/CLEARED per `app.py:987, 1032, 1063`).

### Step-7 items requiring no edit (with verification)

- `test_03…receive_tolerance` — pure fixture bug; PRD §3.2 already pins decayed-reference tolerance verbatim ("reference activity decayed from `reference_time_at` to the receipt instant … at most ten percent"), confirmed by `app.py` `receive_isotope_delivery` (`decay_exact(reference, reference_time_at → now)`, inclusive 10% band).
- `test_09…certify_with_excess` — pure test arithmetic bug; PRD §3.7 pins "sealing instant plus ten half-lives" verbatim, confirmed by `app.py:1031`.
- `app.py::dispose_dose_vial` decay_loss fix — the implementation was changed to match the PRD §3.7 balance invariant already stated verbatim ("measured … fully accounted for as the sum of the administered activity, the residual …, and the decay loss" uniquely yields `decay_loss = measured − administered − residual`); PRD was already correct, so prose kept verbatim.

### Pre-edit search log (NO-NEW-MISMATCH RULE)

**Edit: CLEARED-state `current_activity_mbq` (both sentence changes above)**
- (a) Subject: the reported value of a waste container's `current_activity_mbq` across its lifecycle, specifically in CLEARED status.
- (b) Enumerated impl paths, all read/grepped: `calc.py:163-177` (`container_current_activity` — sole computation; FILLING/SEALED/fall-through branches); all its callers — `serializers.py:177-194` (`waste_container_out`, used by create/list/get/seal/certify responses at `app.py:997, 1003, 1014, 1034, 1065`), `calc.py:214-220` (`compute_possession`, filters to FILLING/SEALED before calling, so the CLEARED branch never affects the ledger), `app.py:1048` (certify guard — evaluated while status is still SEALED, before the flip at `app.py:1063`); status assignments grepped across `app.py` confirming FILLING→SEALED→CLEARED is the only lifecycle; `test_09` post-fix assertions (0.010 read on SEALED, no `current_activity_mbq` assertion on CLEARED) checked as auxiliary evidence.
- (c) Wording adjustment: chose "While `SEALED`" (paralleling the existing "While a container is `FILLING`" phrasing) rather than keeping "Once `SEALED`" plus a CLEARED carve-out, because "Once" was the exact root of the two-reader divergence; the CLEARED sentence says only that the field "reads 0.000", leaving the existing "exits the possession ledger" clause (a separate, already-correct statement about §2.6 aggregation) untouched, and says nothing about the clearance-time 0.05 check, which the implementation evaluates pre-transition on the SEALED formula.

## Step 9: Complete PRD — 2026-08-13T03:20:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1514_nuclear_medicine_radiopharmaceutical/workspace/PRD_COMPLETED.md` is written as a minimal patch over `PRD_FINALIZED.md`.

## Summary

**Source vs output**: PRD_FINALIZED.md 311 lines / 52,271 chars → PRD_COMPLETED.md 313 lines / 56,394 chars (+2 lines, +4,123 chars). 14 edit sites (12 in-place paragraph revisions, 1 inserted paragraph in §2.9, 0 new sections).

**Counts**: 10 ambiguity-pins, 4 mismatch-revisions (the §2.9 paragraph, §3.3 guard-chain ending, §3.4 guard-chain ending, and §2.11 timestamp-format claim each correct prose that contradicted impl; all others pin previously silent behavior).

Per-change breakdown:

- §2.1 — insert — ambiguity — entity-backed `AuthorizedUser` row check (ERR_NOT_FOUND) is enforced only on the four AU write endpoints, not on reads — implementation/middleware.py:36-41, app.py:591/639/657/1277
- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected ERR_VALIDATION; sort ties broken by `id`; `has_more` = offset + returned < total_count — app.py:108-132, response.py:32-46
- §2.4 — revise — mismatch — envelope `api_request_timestamp` is wall-clock, carved out of "never from the wall clock" — response.py:14-17
- §2.4 — insert — ambiguity — clock may be set to any parsable instant (earlier or later); response echoes the supplied string verbatim as `current_utc` — app.py:171-182
- §2.4 — insert — ambiguity — clock-sweep vial decay check uses the exact variant — app.py:160
- §2.4 — revise — ambiguity — elapsed time truncates sub-minute remainders toward zero (not "fractional seconds") — calc.py:62-65
- §2.9 — insert (new paragraph) — mismatch — ownership evaluated after target-resource resolution (404 before 403); field-level/enum validation raised at parse point before guard families; three endpoint-specific placements (substitute `use_type` after version/state, booking interval check after contamination/before overlap, release `evaluation_variant` before administration resolution) — app.py:654-672, 914-928, 1279-1286
- §2.10 — insert — ambiguity — undefined paths and unsupported methods rejected ERR_NOT_FOUND (404) — app.py:55-62
- §2.11 — revise — mismatch — `created_at`/`updated_at` emitted in the clock's own precision (no fractional part when the clock has zero fractional seconds); all other datetime fields always canonical `Z` with three fractional digits; `version` starts at 1 — calc.py:50-55/229-241, serializers.py:11-17
- §3.2 — insert — ambiguity — receipt license checks consult the first-registered license whose conditions list the isotope, skipped entirely if none — app.py:500-506, calc.py:143-149
- §3.3 — revise — mismatch — order-creation field validation is not "last": required-field presence precedes existence checks, `use_type` enum check precedes the license-posture guard — app.py:593-603
- §3.3 — insert — ambiguity — order-cancel `reason` accepted but not persisted — app.py:633-648
- §3.4 — revise — mismatch — preparation elapsed difference can be negative (clock past scheduled instant on an ORDERED order) and is clamped to zero — calc.py:117-119
- §3.4 — revise — mismatch — preparation required-field validation runs at parse, before existence checks; license consulted is the prescriber's license — app.py:691-705
- §3.5 — insert — ambiguity — `date_of_birth` stored verbatim (no format validation); `cleanup_buffer_minutes` must be an integer when supplied — app.py:374-381, 403-405
- §3.5 — insert — ambiguity — appointment-cancel `reason` accepted but not persisted — app.py:960-968
- §3.5 — insert — ambiguity — sixty-minute administration window compared on the truncated whole-minute difference — app.py:803-804
- §3.6 — insert — ambiguity — missing/unknown `to_state` rejected ERR_VALIDATION; recontamination loop leg does not re-stamp `contained_at` — app.py:1188-1190, 1218

No other divergences found: all 44 endpoints, both decay variants, possession-ledger composition/rounding, hot-lab capacity, tolerance, cascades (license suspend/reinstate, spill report/clearance), OCC checkpoints, segregation-of-duties pairings, and the §4/§5 catalogues match implementation as already written.

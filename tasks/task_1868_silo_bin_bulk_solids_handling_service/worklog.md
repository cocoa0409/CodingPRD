## Step 2: Generate Scaffold — 2026-08-14T22:17:00.000Z

## Task 1868 — Silo, Bin & Bulk-Solids Handling Service: scaffold generated

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1868_silo_bin_bulk_solids_handling_service/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` (§1.9)

**Design summary**
- Complexity profile: primary `compliance_audit` (permit-required bin entry, segregation of duties, calibration records), secondary `posture_driven_gating` (vessel flow_posture → site_posture rollup gates operations); layers: rate/threshold triggers, cascading side effects, optimistic concurrency, temporal windowing. Flat topology (`api_prefix: "/"`), segregation-of-duties role model (permit issuer ≠ entrant; contract-vs-capital approval split between PlantOperator and ServiceManager).
- Surface: 9 entities, 38 endpoints, 24 error codes, 4 roles (PlantOperator/Technician entity-backed; ServiceManager/SafetyOfficer opaque), 3 state machines (ticket with capital fork + ON_HOLD cycle; permit with ACTIVE↔SUSPENDED cycle; order lifecycle), 8 calculations, 1 OCC rule (`PATCH /vessels/{id}` + `expected_vessel_version` → 412), logical-clock endpoint with the mandated `2026-08-01T00:00:00Z` default.

**Difficulty design (18 instances, 2 per rule)** — all with structured `setup_api_calls`/`trigger`/`assert` and precomputed literals:
- Dual-variant calc: reorder TARGET_FILL 65.0 t vs DAYS_OF_COVER 5.0 t; calibration OF_READING 0.300 % FAIL vs OF_FULL_SCALE 0.060 % PASS (same 20.000/20.060 t weights).
- Combinatorial: tiered/conditional estimate 208800¢ (mode a); pinned per-line-rounding invoice 215649¢ vs non-conformant 215650¢ (mode b).
- Non-linear machines on different entities; depth-3 cascade (reading→order→vessel→site) vs depth-2 quality-hazard permit auto-void; state-vs-safety and temporal-vs-fiscal priority conflicts; inclusive boundaries at reorder point 30.0 and calibration tolerance 0.250 %; Permit→Order and Order→Vessel cross-entity gates; half-open technician overlap vs 2-hour vessel downtime buffer; mass (receive+void restores 25.0 t) and labor-hours (schedule+complete restores 40.0 h) compensating invariants.

**Corner design**: 38 active instances + 6 `excluded_because` stubs across all 9 taxonomy sections (entities, state machines, calculations, validations, endpoints, errors, RBAC, cross-cutting layers, consistency).

**Lint verdict (verbatim)**:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(38 endpoints, 9 entities, 18 §1.8 + 38 §1.9 instances, 361 calls scanned.) Additional checks: zero forbidden concurrency vocabulary, 62/62 unique instance names across both files, every error code referenced beyond its declaration, every endpoint role declared in §1.7. No sibling tasks were inspected at any point.

## Step 3: Copy Shared Files — 2026-08-14T22:18:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1868_silo_bin_bulk_solids_handling_service/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T22:22:00.000Z

All three hard contracts pass. PRD generated.

**Report:**

Generated PRD at `/home/ubuntu/github/CodingPRD/tasks/task_1868_silo_bin_bulk_solids_handling_service/workspace/PRD.md` from the scaffold, following the doc-generator skill spec. Did not open the forbidden DIFFICULTY/CORNER design files.

**Structure:**
- §1 Introduction (3 paragraphs — domain context, system scope, audience)
- §2 Global Specifications (11 subsections: RBAC with per-role identity prose, verbatim §2.2 response envelope, pagination, posture roll-up, scale calibration posture, common resource properties, precision/rounding, OCC, nested retrieval, validation ordering, logical clock)
- §3 Business Logic (10 subsections organized by lifecycle: onboarding, level readings/reorder, quality reports, scale calibration, order lifecycle, ticket intake/estimate/routing, scheduling/downtime, entry permits/atmosphere, ticket start/complete/invoicing, clock)
- §4 Endpoint table (4 columns, 37 endpoints)
- §5 Error catalogue (2 columns, 24 errors)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs + common fields: 85 required, 85 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 9 priorities expressed in §2.10 in fixed sequence
- concurrency_rules[] OCC rejections: 1 rule (PATCH /vessels/{id} with expected_vessel_version -> ERR_STALE_VERSION/412) fully expressed in §2.8 and §3.1
- state_machines[].transitions: all ReplenishmentOrder (4), ServiceTicket (8), EntryPermit (7) transitions expressed with from/to states, preconditions, error IDs, and side effects
- calculations[]: current_inventory_tons, reorder_quantity (TARGET_FILL and DAYS_OF_COVER variants), avg_daily_usage_tons (14-day trailing window), calibration_error_pct (OF_READING and OF_FULL_SCALE variants), service_estimate_cents (with rates 9500/14500/11000/22000/18000 and emergency multiplier 1.5), invoice_total_cents (pinned per-line rounding, mileage 331.7, disposal 3653.92, tax 6.0), flow_posture_derivation, technician_remaining_hours — all expressed in precise business prose
- validations[] conditions: all matchable to error IDs in §2/§3 prose
- endpoints[].side_effects: expressed in workflow narratives
- entities[].fields[] structured content (defaults, ranges, enum values, sources): reconstructible from prose
- sibling-branch symmetry: parallel branches (CONTRACT_SERVICE vs CAPITAL_PROJECT approval, TARGET_FILL vs DAYS_OF_COVER, OF_READING vs OF_FULL_SCALE, DRAFT/ISSUED auto-void) rendered with equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 439
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Step 5: Generate Unit Tests — 2026-08-14T22:35:00.000Z

Generation complete. Summary of what was produced for task 1868:

## Stage 1 — `test_helpers/` (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1868_silo_bin_bulk_solids_handling_service/test_helpers/`)

- `types.py` — TypedDicts for all 9 entities plus status enums. Append-only measurement records (`LevelReading`, `MaterialQualityReport`, `ScaleCalibration`) carry only `id` + `created_at`, no `updated_at`/`version`, per PRD §2.6.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (35 methods including `set_clock`).
- `api_errors.py` — `ApiErrorId` enum (24 errors) + HTTP status map registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions; the three immutable-record assertions actively assert absence of `updated_at`/`version`.
- `factories.py` — payload factories with PRD defaults, input fields only.
- `constants.py` — atmosphere band (19.5/23.5/10.0), 2-hour downtime buffer, rate table, 1.5 emergency multiplier, mileage/disposal/tax rates, clock startup default.
- `test_users.py` — `TEST_USERS` shared headers for all 4 roles plus per-instance `make_plant_operator_headers(site.id)` / `make_technician_headers(tech.id)` builders for the two entity-backed roles.
- `fixtures.py` — composite helpers: `create_site_with_vessel`, `create_vessel_with_triggered_order` / `..._dispatched_order`, ticket lifecycle (`create_draft/quoted/approved/scheduled/in_progress_ticket`), permit lifecycle (`create_draft/issued/active_permit`, `create_approved_entry_ticket_with_permit`), `create_flow_impaired_vessel`, `post_reading`/`post_quality_report`/`post_scale_calibration`. All ownership-gated calls thread entity ids via the make_*_headers builders.
- `__init__.py` — barrel export of framework generics + PRD-specific modules.

## Stage 2 — `test_suite/` (9 test files + `conftest.py`, 76 tests)

- `test_01_entity_basics.py` — site/vessel defaults, enum and range validation, unknown/computed-field rejection, immutable reading shape.
- `test_02_replenishment_calc.py` — TARGET_FILL vs DAYS_OF_COVER (65.0 vs 5.0 on identical inventory), OF_READING vs OF_FULL_SCALE (0.300 FAIL vs 0.060 PASS), reorder-point inclusive boundary (30.0 triggers / 30.1 doesn't), calibration tolerance boundary (0.250 PASS / 0.255 FAIL).
- `test_03_estimate_invoice_calc.py` — estimate 208800 (CLEANOUT 8h×crew2, 10% discount), CONTRACT_SERVICE routing, per-line invoice rounding (215649, explicitly ≠ 215650 sum-then-round), capital-threshold inclusive boundary (285000 ≥ 285000 → CAPITAL_PROJECT with ServiceManager-only approval).
- `test_04_order_lifecycle.py` — happy path TRIGGERED→DISPATCHED→RECEIVED (37.0 anchor+receipt), invalid receive/cancel/double-dispatch, receive→void mass restoration (50.0 → exactly 25.0), re-anchor on newer reading (10.0, new 80.0 t order), negative-void rejection.
- `test_05_posture_cascades.py` — depth-3 reading→order→vessel→site cascade (ATTENTION), quality breach → FLOW_IMPAIRED + permit auto-VOIDED (AUTO_QUALITY_HAZARD) + CRITICAL, FLOW_IMPAIRED-over-PENDING precedence.
- `test_06_ticket_workflows.py` — ticket ON_HOLD/IN_PROGRESS cycle via permit suspend/resume, repeatable permit cycle then close (no findings → 0 auto tickets; APPROVED untouched), invalid complete-from-SCHEDULED, approve-after-DECLINED lockdown, entry-permit-required at start, technician hours 40→32→32→40 compensation.
- `test_07_entry_permits.py` — close-from-DRAFT invalid, SoD, lockout, atmosphere on activate, engulfment control (ERR_INBOUND_DELIVERY_PENDING, then success after receive with `issuer_user_id` recorded), close-with-findings auto-DIAGNOSIS ticket (estimate 38000), state-priority-beats-safety on DRAFT activate.
- `test_08_scheduling.py` — half-open technician overlap (adjacent allowed, 11:30 rejected), vessel 2-hour buffer (0.5 h rejected, exactly 2 h accepted), double-booked-beats-credit-hold priority plus the free-window ERR_CREDIT_HOLD control, window-in-past via logical clock, receive blocked by OUT_OF_TOLERANCE.
- `test_09_api_contracts.py` — missing auth (401), all six 404 domain errors, body-FK 404s, five RBAC denials (operator→create site, technician→quote, safety officer→create ticket, cross-site reading, non-assignee start), OCC stale version (412, value unchanged), pagination limit/offset/has_more, `site_id` list filter, envelope shape, invoice immediate consistency (23320).

## Verification results

- All 20 difficulty instances × ≥2 tests and all 36 non-stub corner instances × ≥1 test carry exact `Design:` tags; all 6 `excluded_because` stubs cross-reference existing difficulty instances and were not translated. 56/56 required tags covered, 0 orphans, 0 untagged/dual-tagged.
- Every docstring PRD citation survives a normalized literal grep of PRD.md (initial 4 endpoint-titular citations were replaced with rule-bearing prose per C2).
- All modules compile and import cleanly; no `skip`/`skipif`/`xfail` markers anywhere. No instances were skipped — every design-index rule has verbatim PRD coverage with uniquely-derivable outcomes.

## Step 6: Generate Implementation — 2026-08-14T22:35:00.000Z

The implementation is complete. Let me provide the final report.

## Summary

Generated a complete Python + Flask implementation for the Silo Bin Bulk Solids Service API at `/home/ubuntu/github/CodingPRD/tasks/task_1868_silo_bin_bulk_solids_handling_service/workspace/implementation/`.

### Files produced

- `start.sh` — executable launcher with guarded pip install (no-op when flask is present) and `exec python3 app.py` in the foreground.
- `requirements.txt` — `flask>=3.0,<4.0`.
- `app.py` — Flask app factory, blueprint registration, error handlers mapping `ApiError` to the standard envelope, binds `0.0.0.0:$PORT` (default 10000).
- `db.py` — In-memory store (no seeding). Logical clock defaulting to `2026-08-01T00:00:00Z`.
- `errors.py` — `ApiError` class + all error ID constants from SCAFFOLD §1.6.
- `response.py` — Standard envelope: `meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}`, `response_type` (`object`/`array`/`error`), `data` payload. Error body uses `{error_id, message}`. Timestamps are ISO 8601 UTC with 3 fractional digits.
- `middleware.py` — Auth: requires `X-User-ID` + `X-User-Role` headers, validates role against `{ServiceManager, PlantOperator, Technician, SafetyOfficer}` → `ERR_UNAUTHENTICATED` 401. Role permission → `ERR_FORBIDDEN` 403.
- `services/domain.py` — Calculation library using `Decimal` with `ROUND_HALF_UP`:
  - `compute_current_inventory_tons` (anchor + RECEIVED receipts strictly after anchor)
  - `compute_avg_daily_usage_tons` (trailing 14-day window)
  - `compute_flow_posture`, `compute_site_posture`, `auto_void_permits_on_impaired`
  - `compute_remaining_capacity_hours` (SCHEDULED + IN_PROGRESS only)
  - `compute_estimate_cents` (rate × hours × crew, emergency ×1.5 when FLOW_IMPAIRED, then discount)
  - `compute_invoice` (pinned per-line rounding: labor, mobilization, disposal → subtotal → discount → tax → total; rates 9500/14500/11000/22000/18000, mileage 331.7, disposal 3653.92, tax 6.0%)
  - `compute_calibration` (OF_READING / OF_FULL_SCALE variants, 3dp half-up, inclusive PASS boundary)
  - `atmosphere_passes` (O2 ∈ [19.5, 23.5], combustible ≤ 10.0)
- `services/validate.py` — Body validation helpers (unknown fields rejected, required fields, typed coercion, enum checks, range checks, ISO-8601, pagination limit 1–100 default 10, offset ≥ 0 default 0).
- `services/serialize.py` — Entity serializers resolving computed fields at read.
- `routes/sites.py`, `technicians.py`, `vessels.py`, `level_readings.py` (also hosts quality-reports and scale-calibrations), `orders.py`, `tickets.py`, `permits.py`, `clock.py`.

### Verified end-to-end behaviors

- Auth headers + role RBAC (401/403).
- Validation: unknown fields → 400, invalid enums → 400, out-of-range → 400.
- OCC: `expected_vessel_version` mismatch → 412 `ERR_STALE_VERSION`; match bumps `version`.
- Reorder auto-trigger: low reading creates `TRIGGERED` order with `policy_used` snapshot and TARGET_FILL quantity (65 = 90 − 25 for capacity 100 at 25%).
- `flow_posture` → `PENDING_REPLENISHMENT`; `site_posture` → `ATTENTION`.
- Quality cascade: moisture breach sets `FLOW_IMPAIRED`, auto-voids DRAFT/ISSUED permits with `AUTO_QUALITY_HAZARD`, site → `CRITICAL`.
- Calibration: 5.0% error → FAIL → `OUT_OF_TOLERANCE`; receive blocked with `ERR_SCALE_OUT_OF_TOLERANCE`; passing calibration restores.
- Receive updates inventory (20 + 50 = 70); void reverses (back to 20).
- Ticket lifecycle: DRAFT→QUOTED (commercial_track: `CONTRACT_SERVICE` vs `CAPITAL_PROJECT` via threshold), approve role matched to track (403 on mismatch), schedule, start, complete.
- Invoice: actual_hours=3, mileage=10, disposal=2, DIAGNOSIS, crew=2, discount 10% → labor 57000, mobil 3317, disposal 7308, subtotal 67625, discount 6763, tax 3652, total 64514 (matches per-line-rounding contract).
- Technician capacity: 40 → 38 on schedule, 40 while ON_HOLD, 36 on resume, restored on complete.
- Entry permit: `ERR_ENTRY_PERMIT_REQUIRED` start gate, issue guards (`ERR_LOCKOUT_NOT_VERIFIED`, `ERR_SOD_ISSUER_EQUALS_ENTRANT`, `ERR_INBOUND_DELIVERY_PENDING`), activate/atmosphere-check/resume/close with the bound-ticket cascade (IN_PROGRESS ↔ ON_HOLD), close with findings auto-creates a DRAFT DIAGNOSIS ticket (est_hours=4, crew_size=1, source_permit_id set).
- Scheduling: `ERR_TECHNICIAN_DOUBLE_BOOKED` (half-open overlap, adjacency allowed), `ERR_VESSEL_DOWNTIME_CONFLICT` (2h buffer against other tickets and permits, same-ticket permits exempt), `ERR_WINDOW_IN_PAST` (against logical clock), `ERR_CREDIT_HOLD`.
- `POST /_clock/set_current_utc` advances the logical clock (ServiceManager-only).

The server boots cleanly from a fresh process via `bash start.sh`, binds `0.0.0.0:$PORT`, and responds within 60s — safe for `prd-bench-local-run --isolation per-test-server` reboots.

## Step 7: Run Tests and Iterate — 2026-08-14T22:45:00.000Z

## Summary

**Iterations run: 2** (iteration 1: 7 deterministic failures in all 8 rounds; iteration 2 after fixes: 75/75 passed in all 8 rounds, union of failures empty).

**Tests deleted (1):**
- `test_04_order_lifecycle.py::TestInventoryReanchorAndNegativeVoid::test_void_would_drive_inventory_negative_rejected` — STEP 1b unique-derivability failure. The cited PRD §3.5 clause ("void ... only when doing so does not drive `current_inventory_tons` below zero") admits two divergent implementations in the test's re-anchor scenario (receipt at 2026-08-03, anchor moved to 2026-08-04): a whole-PRD-consistent reader recomputes inventory without the receipt (§3.5 "recomputes ... without this receipt"; §3.2 "a receipt at or before the anchor ... contributes nothing") → 10.0 ≥ 0 → void succeeds; only a naive-subtraction reader (10.0 − 25.0 < 0) rejects. Scaffold driver: `Corner/validations/void_would_drive_inventory_negative_rejected` — the generator precomputed the naive-subtraction outcome.

**Fixes applied to `test_suite/` (test-function layer):**
- `test_02_replenishment_calc.py` — `_setup_vessels()` and `_setup()` referenced the pytest fixture `api` as a bare module name (NameError in all rounds for 5 calibration tests). Replaced with `api_client` imported from `test_helpers` (the exact object the `api` fixture returns — semantically identical, PRD-neutral mechanical fix).
- `test_04_order_lifecycle.py` — `_setup_received_then_reanchored()` same bare-`api` NameError (broke `test_inventory_reanchors_on_newer_reading`); same fix.

**Fixes applied to `test_helpers/`:** none needed — fixtures/factories were PRD-consistent.

**Fixes applied to `implementation/`:**
- `workspace/implementation/services/domain.py` — added `compute_current_inventory_tons_excluding(vessel, exclude_order_id)`; `compute_current_inventory_tons` now delegates to it (behavior unchanged).
- `workspace/implementation/routes/orders.py` (`void_order`) — replaced the naive `current - delivered_tons < 0` pre-check with the PRD-faithful recompute-without-receipt check (§3.2 + §3.5), so voiding a pre-anchor (non-contributing) receipt correctly succeeds and leaves inventory unchanged. Verified by smoke test: receive→50.0, re-anchor→10.0, void→VOIDED with inventory still 10.0.

## Step 8: Finalize PRD — 2026-08-14T22:50:00.000Z

The patch is complete — a single in-place revision. Here is the required summary.

## Summary on exit

**Line counts and %-delta**
- `PRD.md`: 293 lines; `PRD_FINALIZED.md`: 293 lines; **0% delta** (one paragraph revised in place on line 169 — the file uses one line per paragraph, so the diff is exactly one changed line).

**Changes (one bullet each)**
- §3.5 — revise — pinned the void non-negativity pre-check semantics: the check recomputes `current_inventory_tons` under the §3.2 rule with the voided order treated as already removed from the received set, rejecting only when that recomputed value is below zero; explicitly *not* a subtraction of `delivered_tons` from the current value; consequently voiding a receipt at/before the current anchor passes the check and leaves inventory unchanged — `workspace/implementation/routes/orders.py:146-156` (`void_order`), `workspace/implementation/services/domain.py:83-112` (`compute_current_inventory_tons_excluding`).

**Disposition of other step_7_diff items (no PRD edit)**
- Deleted test `test_void_would_drive_inventory_negative_rejected` — same subject as the single edit above; covered by it.
- `test_02`/`test_04` bare-`api` → `api_client` fixes — pure pytest fixture NameError bugs, PRD-neutral; nothing to pin.
- `domain.py` helper extraction — behavior unchanged per step_7_diff; no PRD impact by itself.

**Per-edit pre-edit search log**

*Edit 1 (§3.5 void check wording)*
- (a) Subject: how "void … does not drive `current_inventory_tons` below zero" is evaluated (the `ERR_INVENTORY_WOULD_GO_NEGATIVE` pre-check).
- (b) Impl paths enumerated and read/grepped:
  - `implementation/routes/orders.py:134-163` — `void_order`, the only raise site: computes `remaining = compute_current_inventory_tons_excluding(v, o["id"])`, rejects iff `< 0`; check order is auth → body → role → not-found → from-state (`ERR_INVALID_ORDER_STATE`) → inventory, matching §2.10's cluster ordering (from-state before the temporal cluster that contains "inventory non-negativity").
  - `implementation/services/domain.py:83-112` — `compute_current_inventory_tons` delegates to `compute_current_inventory_tons_excluding(vessel, None)`; anchor = latest reading by (`measured_at`, `created_at`) or `created_at`+`opening_inventory_tons`; only `RECEIVED` orders with `received_at` strictly after the anchor contribute; exclusion skips the voided order.
  - `implementation/services/serialize.py:59-77` — vessel reads recompute `current_inventory_tons` via the same function, so after voiding a pre-anchor receipt the serialized value is unchanged ("leaves inventory unchanged" holds).
  - `implementation/routes/level_readings.py:80` — reorder evaluation uses the same recompute; unaffected by the wording.
  - `implementation/routes/vessels.py` (grep) — only `opening_inventory_tons` at creation; no negativity check.
  - `implementation/errors.py:35` + repo-wide grep for `ERR_INVENTORY_WOULD_GO_NEGATIVE` — confirmed `orders.py:155` is the sole raise site; no parallel endpoint enforces inventory non-negativity.
  - PRD-internal cross-check: §3.2 already states "a receipt at or before the anchor … contributes nothing" and "a `RECEIVED` order that is later `VOIDED` simply leaves the received set … restores the pre-receipt value exactly" — both already consistent with the impl and reused in the new wording.
- (c) Wording adjustments made: (i) scoped the sentence to the *evaluation method* ("recomputing … with this order treated as already removed from the received set, rejecting only when that recomputed value would be below zero") rather than asserting the error can never fire, keeping it under-determined where arithmetic alone would over-claim; (ii) limited the "passes the check and leaves inventory unchanged" consequence to the at/before-anchor case — exactly the scenario Step 7 exercised — avoiding any universal claim about post-anchor receipts; (iii) phrased the exclusion as "treated as already removed from the received set" to mirror §3.2's existing "simply leaves the received set" language so the read-time (`serialize_vessel`) and reorder-evaluation paths remain correctly described.

## Step 9: Complete PRD — 2026-08-14T23:00:00.000Z

The diff is complete and verified. All edits are in-paragraph inserts/revisions except three added rows in the existing §5 error table (plus one clarifying line) — no new sections, no invented behavior.

## Summary

**Source:** `PRD_FINALIZED.md` (293 lines / 42,287 chars) → `PRD_COMPLETED.md` (298 lines / 46,063 chars); delta **+5 lines, +3,776 chars**. File produced at `/home/ubuntu/github/CodingPRD/tasks/task_1868_silo_bin_bulk_solids_handling_service/workspace/PRD_COMPLETED.md`.

**Counts:** 20 ambiguity-pins, 3 mismatch-revisions (23 changes total).

**Changes:**
- §2.3 — insert — ambiguity — pinned pagination-parameter validation (non-integer/out-of-range → ERR_VALIDATION 400), the `has_more` formula (offset + returned items < total_count), and that unmatched filters yield an empty 200 page — implementation/services/validate.py:94-121, implementation/response.py:44
- §2.4 — insert — ambiguity — postures are derived at read against the vessel's *current* `moisture_limit_pct` (a PATCH can change reported posture), but the AUTO_QUALITY_HAZARD permit void fires only at quality-report filing — implementation/services/domain.py:159-173, implementation/routes/level_readings.py:177-180
- §2.6 — insert — ambiguity — `version` starts at 1; `updated_at` equals `created_at` at creation — implementation/routes/sites.py:38-48 (and all create handlers)
- §2.7 — revise — mismatch — narrowed the "1 decimal place" claim to computed quantities (`current_inventory_tons`, `order_quantity_tons`); client-supplied tonnages (`capacity_tons`, `opening_inventory_tons`, `delivered_tons`) are echoed exactly as supplied — implementation/services/serialize.py:66,68,131,133
- §2.9 — insert — ambiguity — path identifiers validated before body references; body references resolved in §3 field-introduction order — implementation/routes/permits.py:38-46, tickets.py:271-275
- §2.10 — insert — ambiguity — a body not parseable as a JSON object yields ERR_VALIDATION at the structural stage — implementation/services/validate.py:8-17
- §2.10 — insert — ambiguity — endpoint-level role permission runs before existence; entity-backed ownership checks (e.g. PlantOperator site match) run immediately after the entity's existence check — implementation/routes/level_readings.py:35-43
- §3.1 — revise — mismatch — dropped "two-letter" from `state_code`; impl stores any string with no format validation — implementation/routes/sites.py:23
- §3.1 — insert — ambiguity — `capital_threshold_cents` accepts any integer, no range validation — implementation/routes/sites.py:29-30
- §3.1 — insert — ambiguity — `full_scale_tons` must be > 0 whenever supplied, regardless of `error_basis` — implementation/routes/vessels.py:66-70
- §3.1 — insert — ambiguity — PATCH with only `expected_vessel_version` (no config field) is accepted and still bumps `version` — implementation/routes/vessels.py:161-168
- §3.2 — insert — ambiguity — trailing-14-day usage window lower bound is exclusive (upper inclusive) — implementation/services/domain.py:124
- §3.2 — insert — ambiguity — boundary readings with identical `measured_at` (zero elapsed) fall back to `default_usage_tons` — implementation/services/domain.py:150-152
- §3.6 — insert — ambiguity — no site–vessel consistency check at ticket intake — implementation/routes/tickets.py:44-49
- §3.6 — insert — ambiguity — approve runs the from-state check before the track-match check (non-QUOTED → ERR_INVALID_TICKET_STATE regardless of caller) — implementation/routes/tickets.py:160-172
- §3.7 — revise — mismatch — `window_end` not strictly after `window_start` yields ERR_VALIDATION (400), not ERR_WINDOW_IN_PAST — implementation/routes/tickets.py:267-268
- §3.8 — insert — ambiguity — permit draft: window inversion → ERR_VALIDATION; no logical-clock check at draft; no ticket↔vessel/requires_entry cross-checks; `lockout_checklist_confirmed` starts false, `issuer_user_id` unset — implementation/routes/permits.py:33-52,55-72
- §3.8 — insert — ambiguity — `oxygen_pct`/`combustible_pct` validated 0–100 inclusive on activate, atmosphere-check, and resume — implementation/routes/permits.py:160-163,208-211,240-243
- §3.8 — insert — ambiguity — `findings` must be a non-empty string; follow-up ticket creation keyed on the exact string `NONE` — implementation/routes/permits.py:270-273,286
- §3.10 — insert — ambiguity — clock-set accepts any valid ISO timestamp (no monotonicity check); response data is `{"current_utc": <iso>}` — implementation/routes/clock.py:22-23
- §4 — insert — ambiguity — no-input transition endpoints accept an absent/empty body; any supplied field → ERR_VALIDATION — implementation/services/validate.py:8-22, implementation/routes/orders.py:60-62
- §4 — insert — ambiguity — level-readings list tie-break: `created_at` newest-first — implementation/routes/level_readings.py:118-119
- §5 — insert — ambiguity — added catalogue rows ERR_NOT_FOUND (404, undefined route), ERR_METHOD_NOT_ALLOWED (405), ERR_INTERNAL (500) — implementation/app.py:35-50

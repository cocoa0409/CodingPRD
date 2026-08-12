# Worklog — task_1213_safety_supply_ppe_vending_program

## Step 1: Create task directory — 2026-08-11T22:16:00.000Z

Pre-assigned output folder `tasks/task_1213_safety_supply_ppe_vending_program` with `workspace/` subdirectory already exists (created upstream). Step 1 treated as done per invocation instructions; no auto-index scan performed.

Scenario: Safety Supply & PPE Vending Program (Fastenal industrial vending): PPE issuance policy by job role, industrial vending machine placement & planogram, employee issuance limits & manager override, consumption reporting & cost center chargeback, respirator/fit-test linkage, regulated item (fall protection) inspection cycle, restock trigger & machine service, contract pricing & compliance audit.

Difficulty parameter: "generate task hard than expert level!" (passed through to Step 2 scaffold generation only).

## Step 2: Generate Scaffold — 2026-08-11T23:03:00.000Z

Scaffold generation complete. All three artifacts written to `/home/ubuntu/github/CodingPRD/tasks/task_1213_safety_supply_ppe_vending_program/` and lint-clean.

**Design summary** (Expert+ band, generated without reading any sibling task):

- **SCAFFOLD.yaml** (§1.0–§1.7; no design keys): 14 entities (CostCenter, JobRole, Item, ContractPrice, Employee, VendingMachine, MachineSlot, SerializedUnit, ManagerOverride, IssuanceTransaction, RestockOrder, ServiceTicket, ChargebackBatch, ComplianceAudit), flat FK topology, 63 endpoints, 59 errors, 11 calculations, 10 state machines, 8 roles. Primary archetype quota/allocation fused with compliance/audit; layers: rate-threshold triggers, cascading side effects, dual-variant calculation, optimistic concurrency. Segregation-of-duties role model (Manager is `entity_backed:Employee` with `is_manager` gate; self-override and self-reversal forbidden). Logical clock endpoint with pinned default `2026-05-01T00:00:00Z` drives all sweeps (fit-test expiry, inspection-due/quarantine, override expiry).
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 19 instances across all 9 rules (rule 2 has 3 — modes (a) tiered contract pricing, (b) pinned per-line-round-then-sum admin fee, (c) pinned evaluation-order override draw-split). All formula-derived asserts are precomputed literals verified with Python (e.g. snapshot 4300 vs rerate 4500, admin fee 102 vs rejected 101, batch total 4613; date math 2026-07-30/2026-10-30/2026-08-29 boundaries).
- **SCAFFOLD_CORNER_DESIGN.yaml**: 55 instances (49 active + 6 `excluded_because` stubs) across all nine claim-extraction-guide sections, including OCC stale-version tests, idempotent replay/conflict, rolling-window and grace-period boundary tests, RBAC denials, and SoD cases.

**Key mechanics worth noting**: chargeback snapshot-vs-rerate divergence driven by reversal removing tier contribution; override consumption is final (never restored by reversal) which is what makes the OVERRIDE_USAGE audit able to find mismatches; three interval semantics (service windows half-open adjacency-allowed, override windows closed with ≥1 full gap day, batch periods half-open, contract-price windows closed adjacency-conflicts); depth-3 reversal→restock-autocancel cascade and service-start→machine→restock-cancel cascade.

**Verification**: `scaffold_lint.py` verdict — "clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5" (751 calls scanned, 0 violations). A supplementary audit confirmed: zero unbound `${var}` placeholders, zero duplicate instance names across both design files, zero dangling grounds refs, zero unreferenced error codes, and enum-value closure (removed a dead `CostCenter.status: CLOSED` value found during review). No sibling task directories were inspected.

## Step 3: Copy Shared Files — 2026-08-11T23:04:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1213_safety_supply_ppe_vending_program/workspace/INSTRUCTION.md` (bash-only step, no subagent).

## Step 4: Generate PRD — 2026-08-11T23:21:00.000Z

PRD generation complete. Output written to `/home/ubuntu/github/CodingPRD/tasks/task_1213_safety_supply_ppe_vending_program/workspace/PRD.md` (374 lines).

## Document structure

- **§1 Introduction** — 2 paragraphs (business pain points + role landscape), domain-specific framing.
- **§2 Global Specifications** — 11 subsections: 2.1 RBAC (all 8 roles named; entity-backed `Manager`/`Employee` vs opaque `EHSAdministrator`/`VendingTechnician`/`SafetyOfficer`/`FinanceAnalyst`/`ComplianceAuditor`/`Any` identity prose); 2.2 response structure (byte-identical to `section-2.2-response-structure.md`); 2.3 pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending); 2.4 logical clock (startup default 2026-05-01T00:00:00Z, never wall-clock, sweeps on set); 2.5 common properties; 2.6 integer-cents precision + line-level round-half-up; 2.7 left-to-right identifier validation with all fourteen 404 ids; 2.8 OCC naming both guarded endpoints with `expected_machine_version`/`expected_slot_version` and `ERR_STALE_VERSION` 412; 2.9 `idempotency_key` replay/conflict; 2.10 the pinned 23-step validation cascade (shape after auth, before existence; structural sub-order); 2.11 cross-aggregate cascade overview.
- **§3 Business Logic** — 8 subsections (catalog/pricing; people/policies/fit-tests; machines/planograms/serialized stock; the vend; overrides/reversals; restocking/service; chargeback/reporting; audits/clock sweeps). All 37 state transitions, 11 calculations (tier resolution with fallback ladder and tie-breaks, rolling usage window with inclusive boundary, effective-limit draw split, par trigger, committed-aware `suggested_qty`, snapshot-vs-rerate replay, 250-basis-point per-line admin fee with the 102-vs-101 worked example, fit-test validity with 365-day expiry, inspection sweep with 30-day grace, override expiry, audit findings per scope), and every error trigger are expressed in prose with no pseudocode and no paths.
- **§4** — 63-row endpoint table, 4 columns only; **§5** — 59-row error table, 2 columns only. PRD ends at §5 with no audit footer.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 70 required, 70 present, 0 missing
- endpoints[].request_body: 56 required, 56 present, 0 missing
- endpoints[].query_params: folded into input lists per scaffold shape; all filter names (item_id, job_role_id, cost_center_id, home_cost_center_id, status, slot_id, machine_id, issued_to_employee_id, employee_id, manager_override_id, serialized_unit_id, chargeback_batch_id, limit, offset) present, 0 missing
- endpoints[].path_params: 15 required, 15 present (inside §4 path templates), 0 missing
- nested/system identifiers (fit_test_id, tested_on, result, expires_on, inspected_on, inspector_user_id, finding_type, entity_id, detail, period_limit_qty, period_window_days, to_iso8601, current_utc, total_qty, total_amount_cents, expected_machine_version, expected_slot_version, idempotency_key): all present
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 23 checked, 23 expressed in prose (pinned 23-step cascade in §2.10 incl. shape-after-auth note and structural sub-order), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (POST /machines/{machineId}/slots + expected_machine_version + ERR_STALE_VERSION 412; PUT /slots/{slotId} + expected_slot_version + ERR_STALE_VERSION 412), 0 missing
- state_machines[].transitions: 37 checked, 37 fully expressed (from/to states, preconditions with error ids, side effects incl. termination revoke cascade, IN_SERVICE restock cancellation, post-service AUTO_PAR sweep, reversal cascades), 0 missing
- calculations[]: 11 checked, 11 fully expressed in precise reconstructible prose, 0 missing
- validations[] conditions: 59 error ids checked, 59 matchable to trigger conditions in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (e.g., ERR_ITEM_DISCONTINUED guards all 4 operations; ERR_MACHINE_NOT_ACTIVE all 5 gates; uniqueness all 6 creates), 0 missing
- entities[].fields[] structured content: defaults, computed derivations (requires_fit_test, serialized_tracking, remaining_qty, line_total_cents, suggested_qty), initial states, and null-while-IN_STOCK semantics all reconstructible from prose, 0 missing
- sibling-branch symmetry: QUARANTINED from ISSUED/INSPECTION_DUE/IN_STOCK, SETTLED from CLOSED/DISPUTED, DECOMMISSIONED from ACTIVE/OFFLINE, CANCELLED from SUGGESTED/PICKED, TERMINATED from ACTIVE/SUSPENDED — all rendered with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 575
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All three contracts PASS. Note: the two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or referenced at any point. One scaffold observation for the orchestrator: the 15th entity (IssuancePolicy) is absent from `entities[]` but fully referenced by `endpoints[]`, `calculations[]`, and `validations[]`; the PRD covers its four fields (`job_role_id`, `item_id`, `period_limit_qty`, `period_window_days`) from those references.

## Step 5: Generate Unit Tests — 2026-08-12T00:00:00.000Z

All work is complete. Summary:

**Stage 1 — test_helpers/** (`/home/ubuntu/github/CodingPRD/tasks/task_1213_safety_supply_ppe_vending_program/test_helpers/`):
- `types.py` — 15 entity TypedDicts, all status enums (Item, Employee, VendingMachine, MachineSlot, SerializedUnit, ManagerOverride, IssuanceTransaction, RestockOrder, ServiceTicket, ChargebackBatch, ComplianceAudit), role enum (8 roles).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (~50 endpoints across cost centers, job roles, items, contract prices, issuance policies, employees, machines, slots, serialized units, manager overrides, issuances, restock orders, service tickets, chargeback batches, compliance audits, reports, logical clock). Sends `Connection: close` to avoid stale keep-alive under per-test-server restart.
- `api_errors.py` — `ApiErrorId` enum + 60-entry HTTP status map registered with `set_error_http_status_map`.
- `assertions.py` — `assert_<entity>` per type using `is_valid_uuid` / `is_iso8601_timestamp`.
- `factories.py` — one factory per entity with auto-incremented unique keys (sku, employee_code, location_code, serial_number, slot_code, idempotency_key).
- `constants.py` — `ADMIN_FEE_BPS=250`, `FIT_TEST_VALIDITY_DAYS=365`, `OVERDUE_GRACE_DAYS=30`, `CLOCK_START_ISO`.
- `test_users.py` — shared constants for 5 opaque roles + `Any`, plus `make_employee_headers(user_id)` / `make_manager_headers(user_id)` per-instance builders for entity-backed roles.
- `fixtures.py` — composite helpers: `setup_cost_center/job_role/item/employee/manager`, `setup_machine_with_slot`, `stock_slot`, `setup_vend_scenario` (vend-capable GENERAL/RESPIRATOR/FALL_PROTECTION scenario), `vend`/`vend_ok`/`reverse_ok`, `grant_override`, `set_clock`, `open_batch`, `open_audit`, `register_serialized_unit`.
- `__init__.py` — barrel export of framework generics + all PRD-specific names.

**Stage 2 — test_suite/** (`/home/ubuntu/github/CodingPRD/tasks/task_1213_safety_supply_ppe_vending_program/test_suite/`): `conftest.py` + 10 test files, **88 tests total**:
- 01_catalog_and_entities (6 tests)
- 02_rbac (6 tests, incl. segregation of duties)
- 03_employee_and_item_state (11 tests: state machine transitions, terminal lockdowns, cascades)
- 04_contract_pricing (8 tests: tier breakpoints, snapshot-vs-rerate divergence, admin-fee rounding)
- 05_limits_and_overrides (10 tests: usage limit boundary, capacity boundary, draw split, compensating invariants)
- 06_serialized_units (4 tests: inspection cycle loops, overdue quarantine boundary)
- 07_machine_lifecycle_and_cascades (10 tests: machine cycles, reversal auto-cancel chain, service start/resolve cascades, audit blocked by open batch)
- 08_vend_gates (11 tests: gate ordering pairs, entitlement, serialized quantity/unit, fit-test, expired override, 404, request shape)
- 09_temporal_and_idempotency (14 tests: service window adjacency, override window gap, idempotency replay/conflict, list pagination+filter, OCC on slot create+update, batch overlap, empty close, duplicate code, window reachability, contract price window)
- 10_reports_and_calculations (8 tests: rolling window inclusive boundary, base-price fallback, fit-test expiry boundary, par trigger exact threshold, override-consumed equality, audit findings, consumption report, immediate visibility)

**Coverage audit (per skill §2.1):**
- Queue A (Difficulty): all 19 non-stub instances have exactly ≥2 tests each (38 tests).
- Queue B (Corner): all 49 non-stub instances have ≥1 test each (50 tests).
- Stub instances (6 with `excluded_because:`) correctly not translated.
- Zero unresolved Design tags.
- All docstring PRD citations survive verbatim `grep` of `workspace/PRD.md` (modulo whitespace).
- All files compile and import cleanly.

## Step 6: Generate Implementation — 2026-08-12T00:01:00.000Z

Implementation complete and verified. Final report:

## Deliverable

Complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1213_safety_supply_ppe_vending_program/workspace/implementation/`:

- `start.sh` — guarded dependency install (`import flask` check, no re-install on per-test reboots), `exec python3 app.py` in foreground; binds `0.0.0.0:$PORT` (default 10000); boots and answers HTTP in ~1s; store empty on every boot (no seeding).
- `app.py` — app factory, auth before_request, ApiError/404/405 handlers, global RLock so cascades are atomic.
- `db.py` — 14 entity stores + logical clock starting exactly `2026-05-01T00:00:00Z`.
- `errors.py` — all 55 catalogued error IDs with HTTP statuses.
- `envelope.py` — `meta`/`response_type`/`data` envelope; pagination fields (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0).
- `auth.py` — `X-User-ID`/`X-User-Role`, 8 declared roles, entity-backed resolution for Manager/Employee, `is_manager` gate.
- `helpers.py` — shape validators (incl. OCC tokens accepting int or digit-string), pagination, contract-price tier resolution with pinned tie-breaks, rolling-usage window, month cumulative, covering-override lookup, par trigger, clock sweeps (override expiry, inspection due/quarantine, fit-test expiry).
- `routes_catalog.py`, `routes_people.py`, `routes_machines.py`, `routes_vending.py`, `routes_service.py`, `routes_finance.py` — all 57 endpoints: full vend gate order per PRD §2.10, idempotent replay, draw-split, snapshot-vs-rerate close with per-line round-half-up admin fee, chargeback adjustments to the OPEN batch, all state machines and cascades.

## Verification

- `prd-bench-local-run --isolation per-test-server` twice against the real 88-test suite: **72 passed / 16 failed, identical both runs** (~52–74s per run, ~88 server reboots each, zero restart flakes).
- All 16 failures are **test-suite authoring bugs**, not implementation: module-level helpers `_setup_diverging_batch` / `_setup_restock_divergence` / `_setup_three_line_fee_scenario` (test_04), `_setup_capacity_boundary` (test_05), `_setup_fall_protection_scenario` (test_06), `_setup_reversal_autocancel` / `_setup_service_cascade` / `_setup_audit_blocked_by_open_batch` (test_07) reference `api` without declaring the fixture (`NameError: name 'api' is not defined`); test_07 also uses `AUDITOR` without importing it from `test_helpers`. These need one-line test fixes in Step 7.
- Independently re-verified every §1.8 difficulty instance and §1.9 corner case with three smoke suites (all pass), including exact figures: snapshot 4300 vs rerate 4500, fee 113/102 (per-line rounding), tier flip at cumulative 10, 30-day rolling boundary to the second, par-trigger `<=` boundary, due/+30/+31 quarantine boundaries, draw-split `needed = usage+qty − max(base, usage)`, and all cascade chains.

## Two things the fix loop should know

1. **ContractPrice overlap is enforced per (item_id, min_period_qty)**: PRD §3.1 prose says windows "for the same item" must not intersect, but the §1.8 recipes require two overlapping windows with different breakpoints (tiers 0→450 and 10→400 sharing 2026-01-01..2026-12-31), while the §1.9 corner test enforces conflict only for the same breakpoint. I scoped the check per tier — the only reading under which both test families are constructible.
2. **Runner invocation**: `--start-command` must be an absolute `cd <dir> && bash start.sh`. A bare relative command breaks the per-test restart (re-resolved from the pytest cwd `test_suite/`), which is what caused my first full run to show 88 setup timeouts — an invocation mistake, not an implementation defect.

## Step 7: Run Tests and Iterate — 2026-08-12T00:22:00.000Z

## Summary

**Iterations run:** 2 (baseline sweep to confirm diagnostic, then fix + final sweep).

**Tests deleted:** None. Every failure was a test-suite authoring bug against PRD-covered rules; no PRD silence, no unique-derivability collapse.

**Fixes applied to `test_suite/`:**

- `/home/ubuntu/github/CodingPRD/tasks/task_1213_safety_supply_ppe_vending_program/test_suite/test_04_contract_pricing.py` — added `api` parameter to module-level helpers `_setup_diverging_batch`, `_setup_restock_divergence`, `_setup_three_line_fee_scenario`; updated all 7 call sites in the 5 failing tests to pass the `api` fixture through.
- `/home/ubuntu/github/CodingPRD/tasks/task_1213_safety_supply_ppe_vending_program/test_suite/test_05_limits_and_overrides.py` — added `api` parameter to `_setup_capacity_boundary`; updated both call sites.
- `/home/ubuntu/github/CodingPRD/tasks/task_1213_safety_supply_ppe_vending_program/test_suite/test_06_serialized_units.py` — added `api` as first positional parameter to `_setup_fall_protection_scenario` (keyword args preserved); updated all 4 call sites.
- `/home/ubuntu/github/CodingPRD/tasks/task_1213_safety_supply_ppe_vending_program/test_suite/test_07_machine_lifecycle_and_cascades.py` — added `AUDITOR` to the `test_helpers` import list; added `api` parameter to `_setup_reversal_autocancel`, `_setup_service_cascade`, `_setup_audit_blocked_by_open_batch`; updated all 6 call sites.

**Fixes applied to `test_helpers/`:** None — fixtures already use `api_client` directly, and `AUDITOR` was already defined in `test_helpers/fixtures.py`; only the import was missing from test_07.

**Fixes applied to `implementation/`:** None — the implementation was correct; all failures were test-layer NameErrors.

**Final state:** 8/8 rounds, each 88/88 passing.

**Orchestrator verification:** all 8 `results.{1..8}.json` files on disk, each `passed=88 failed=0 errors=0 total=88`. Route parity pre-check confirmed 63/63 scaffold endpoints registered in the Flask app (only extra route is Flask's built-in `/static/<filename>`).

## Step 8: Finalize PRD — 2026-08-12T00:25:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1213_safety_supply_ppe_vending_program/workspace/PRD_FINALIZED.md` written with exactly one revision.

## Summary

**Line counts:** PRD.md 373 lines, PRD_FINALIZED.md 373 lines — 0.0% line delta (one in-place sentence revision on line 153; ~+40 words within that line).

**Changes (one bullet per change):**
- §3.1 — revise — ContractPrice window-conflict rule rescoped from "for the same item" to "for the same item and the same `min_period_qty` breakpoint", with an explicit clause that same-item rows at different breakpoints may share or overlap windows freely — `implementation/routes_catalog.py:130-138`.

**Why only one edit:** Every other step_7_diff item was a pure test-layer fixture bug (missing `api` parameter threading in module-level helpers across test_04/05/06/07, and a missing `AUDITOR` import in test_07). No implementation fix, no test deletion, no PRD silence — so no PRD edit traces to them.

**Per-edit pre-edit search log:**
1. **Edit: §3.1 ContractPrice overlap scoping**
   - (a) Subject: creation/validation of ContractPrice effectiveness windows and the `ERR_CONTRACT_PRICE_WINDOW_CONFLICT` rejection scope.
   - (b) Impl paths enumerated and read: `routes_catalog.py:117-147` (`create_contract_price` — the only creation/validation path; the loop at lines 130-138 skips any existing row whose `item_id` differs OR whose `min_period_qty` differs, then applies closed-interval intersection only to same-item/same-breakpoint rows); `routes_catalog.py:150-159` (`list_contract_prices`, read-only); `routes_catalog.py:162-165` (`get_contract_price`, read-only); `helpers.py:235-254` (`resolve_price`, read-only consumer) and both of its call sites `routes_vending.py:128` (vend-time pricing) and `routes_finance.py:106` (batch-close rerate). Also grepped all `*.py` for `contract_price`/`WINDOW_CONFLICT` to confirm no other path creates or validates windows.
   - (c) Wording adjustment: added the clause "rows for the same item at different breakpoints may share or overlap windows freely (that coexistence is exactly how tiered pricing is expressed)" because `resolve_price` (helpers.py:240-253) actively requires multiple same-item rows at different breakpoints covering the same date to coexist — both at vend time and during rerate. Without that clause, a narrowed same-breakpoint-only reading could be misread as forbidding the overlap the pricing paths depend on. §2.10 item 15 and §3.4/§3.7 wording were checked and remain consistent without modification.

## Step 9: Complete PRD — 2026-08-12T00:36:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1213_safety_supply_ppe_vending_program/workspace/PRD_COMPLETED.md` produced as a minimal patch over PRD_FINALIZED.md.

**Source vs output:** PRD_FINALIZED.md 373 lines / 53,001 chars → PRD_COMPLETED.md 374 lines / 56,367 chars (+1 line, +3,366 chars).

**Counts:** 12 ambiguity-pins, 9 mismatch-revisions (21 edits total; the §5 table row accompanies the §2.7 pin).

**Changes:**
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`, negative `offset` rejected with `ERR_VALIDATION_FAILED` — implementation/helpers.py:138-159
- §2.3 — insert — ambiguity — list ties at identical logical-clock instants order by insertion sequence — helpers.py:162-165
- §2.4 — revise — mismatch — "never reads wall-clock time" carved out: envelope `api_request_timestamp` is the lone wall-clock read — envelope.py:6-10, util.py:23-24
- §2.4 — insert — ambiguity — `to_iso8601` accepts bare dates (midnight UTC); `current_utc` omits fractional digits for whole-second instants — util.py:32-43, 73-77
- §2.5 — revise — ambiguity — `version` "starts low" → starts at 1; `created_at`/`updated_at` stamped from the logical clock — util.py:93-108
- §2.7 — insert — ambiguity — fallback `ERR_NOT_FOUND` (404) for issuance-policy get misses, unregistered paths, unsupported methods — errors.py:64, routes_catalog.py:211, app.py:50-56
- §5 — insert — ambiguity — `ERR_NOT_FOUND` | 404 row added to the catalogue — errors.py:64
- §2.8 — insert — ambiguity — OCC tokens accept JSON integer or decimal string — helpers.py:122-131
- §2.10 step 3 — revise — mismatch — merged-record shape checks (slot edit's resulting par vs capacity) run after body FK resolution, not in the shape step — routes_machines.py:175-183
- §2.10 step 17 — insert — ambiguity — pinned sub-order is the vend's; unit registration evaluates category misuse ahead of slot-item match — routes_machines.py:217-221
- §3.1 — revise — mismatch — `role_name` claimed unique but impl does not uniqueness-check it — routes_catalog.py:43-53
- §3.2 — insert — ambiguity — `period_limit_qty`/`period_window_days` accept zero (negative rejected); semantics of zero — routes_catalog.py:176-177, helpers.py:209-220
- §3.3 — insert — ambiguity — unit registration check order: machine state → item ACTIVE → category → slot item match → capacity → serial uniqueness — routes_machines.py:211-225
- §3.3 — revise — mismatch — "While IN_STOCK … all null / log empty" rescoped to fresh units; reversal-returned units retain `last_inspected_on` and log — routes_machines.py:226-235, routes_vending.py:232-238
- §3.4 — revise — mismatch — a `manager_override_id` naming no override fails with `ERR_MANAGER_OVERRIDE_NOT_FOUND` (existence), not `ERR_OVERRIDE_NOT_ACTIVE` — routes_vending.py:38-39
- §3.4 — insert — ambiguity — stored `manager_override_id`: named id when named, else covering id when draw positive, else null — routes_vending.py:131-136
- §3.5 — insert — ambiguity — `remaining_qty` reads approved−consumed in every status except `REVOKED` (zero) — routes_people.py:21-29
- §3.5 — insert — ambiguity — multiple OPEN batches: earliest-created absorbs the reversal adjustment — routes_vending.py:209-213
- §3.5 — revise — mismatch — restoration above par cancels every SUGGESTED order for the slot, not a single order — routes_vending.py:226-230
- §3.5 — revise — mismatch — reversal returns units from ISSUED or INSPECTION_DUE (not just ISSUED); QUARANTINED units stay quarantined — routes_vending.py:232-238
- §3.6 — insert — ambiguity — service `window_start`/`window_end` are ISO 8601 instants; bare dates read as midnight UTC — routes_service.py:114-115, util.py:32-43
- §3.7 — revise — mismatch — `cost_center_code` claimed unique but impl does not uniqueness-check it — routes_finance.py:24-31
- §3.7 — insert — ambiguity — consumption report: three query params required (`ERR_VALIDATION_FAILED`), cost center must exist (`ERR_COST_CENTER_NOT_FOUND`), response echoes the parameters — routes_finance.py:252-278
- §3.8 — insert — ambiguity — inspection sweep rules apply sequentially in one clock set, so a >30-days-past-due unit goes ISSUED→QUARANTINED in a single set — helpers.py:303-312

All other PRD prose (gate order §2.10 bands, pricing tier resolution and tie-breaks, draw-split formula, rerate replay, per-line half-up admin fee, sweep boundary semantics, endpoint/role table, error catalogue statuses) was verified against implementation and already pinned uniquely — no changes needed.

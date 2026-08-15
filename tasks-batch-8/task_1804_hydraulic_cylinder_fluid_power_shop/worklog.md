# Worklog — task_1804_hydraulic_cylinder_fluid_power_shop

## Step 1: Create Task Directory — 2026-08-14T17:34:00.000Z

Task directory `tasks/task_1804_hydraulic_cylinder_fluid_power_shop/` and `workspace/` pre-created by the pipeline launcher (verified present and empty). User directive: difficulty harder than expert level.

## Step 3: Copy Shared Files — 2026-08-14T17:35:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1804_hydraulic_cylinder_fluid_power_shop/workspace/INSTRUCTION.md` (1424 bytes). Done early, concurrently with Step 2's subagent run.

## Step 2: Generate Scaffold — 2026-08-14T18:08:00.000Z

All three artifacts are complete, lint-clean, and arithmetic-verified. Summary:

## Files written

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 1703 | 91,849 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 725 | 79,251 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 1118 | 117,731 |

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (70 endpoints, 15 entities, 18 §1.8 + 42 active §1.9 instances, 749 calls scanned)

## Counts
- **Entities:** 15 (Shop config, Customer, Technician, SealKit, Cylinder, WorkOrder, TeardownReport, Quote, InventoryItem, StockReservation, TestBay, PressureTest, Certificate, ExchangeUnit, FieldServiceJob)
- **State machines:** 10 — WorkOrder (17 states, cyclic rework loop, revision loop, CERTIFIED→TEST_PENDING revert, repair/scrap/exchange forks), Quote (cyclic revision + lazy EXPIRED), ExchangeUnit (IN_POOL→RESERVED→IN_POOL cycle), PressureTest, Certificate, FieldServiceJob, StockReservation, InventoryItem, Cylinder, Customer
- **Calculations:** 9 (quote_pricing, invoice_total_settlement, exchange_core_credit, stock_cut_allocation, cleanliness_code_rollup, pressure_hold_requirement, turnaround_tier_gate, field_service_pricing, credit_exposure_check); 3 carry provisional/final variants
- **Validations:** 13 ordered priorities (shape → auth → ownership → existence → OCC 412 → state → safety → temporal → constraint → referential → fiscal)
- **Endpoints:** 70 (flat topology under `/fluid-power`, incl. `/_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` default)
- **Errors:** 33 domain-specific codes
- **Roles:** 5 — ShopAdmin/ServiceAdvisor/QualityInspector (opaque), Technician/Customer (entity-backed), segregation-of-duties model
- **§1.8 instances:** 18 (9 rules × 2, all with full structured test_recipes)
- **§1.9 instances:** 49 entries — 42 full + 7 `excluded_because` stubs; sections: entities 7, state_machines 4, calculations 9, validations 10+6 stubs, endpoints 2, errors 1, rbac 3, cross_cutting_layers 3+1 stub, consistency 1

## Design decisions of note
- **Dual-variant domains:** repair pricing (Quote/WorkOrder, 95896 vs 116254 cents) vs exchange core credit (ExchangeUnit, 40000 vs 24000).
- **Combinatorial modes:** per-line round-half-up-then-sum (mode b — two .5-cent raw lines make orders differ by 1 cent) vs pinned evaluation order for loyalty-tier invoice settlement (mode c — tier keyed on pre-discount subtotal + pre-invoice YTD; GOLD boundary at exactly 500000).
- **Cascades:** quote-approval depth-3 (Quote→WorkOrder→StockReservation→InventoryItem cut) and certificate-revoke depth-2 (Certificate→WorkOrder→PressureTest void).
- **Overlap semantics deliberately opposed:** test bays are closed intervals + 30-min buffer (adjacency rejected); technician windows are half-open (adjacency allowed).
- **OCC (3 rules, all true races):** teardown-report PATCH, field-job schedule on Technician.version, shop-config PATCH.
- **All formula-derived asserts were executed as code** (round-half-up via Decimal); this caught one real authoring bug (SILVER env fee 2208.82 → 2209, not 2208) before it could propagate into tests.
- One unreachable error (ERR_NO_PASSING_TEST) was removed mid-design, replaced by a TEST_PENDING re-entry transition so a revoked certificate has a deterministic recovery path; Customer suspend/reactivate was added to close a dead enum value.

## Step 4: Generate PRD — 2026-08-14T18:26:00.000Z

Done. The PRD is generated and all three Hard Contracts verified PASS mechanically.

## Summary

**Output**: `workspace/PRD.md` — **388 lines**.

**Section list**: §1 Introduction (2 paragraphs) · §2 Global Specifications — 2.1 RBAC (5 roles with identity translation), 2.2 API Response Structure (byte-identical verbatim block), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 The Logical Clock, 2.6 Optimistic Concurrency Control, 2.7 Cascading State Consistency, 2.8 Monetary Precision and Rounding Discipline, 2.9 Validation Order and Error Precedence (13 stages), 2.10 Shop Configuration and the Rate Card · §3 Business Logic — 3.1 Onboarding/Accounts/Catalog, 3.2 Intake & Tier Gate, 3.3 Teardown & Quote Drafting, 3.4 Quote Lifecycle, 3.5 Stock Cutting & Remnants, 3.6 Repair & Contamination Control, 3.7 Pressure Testing & Certification, 3.8 Scrap/Exchange/Close/Settlement, 3.9 Field Service & Hose Crimping · §4 Endpoint Definitions (70 rows, 4 columns) · §5 Error Code Catalogue (33 rows, 2 columns).

**Hard Contract reports**:

```
Field coverage check (Contract 1):
- entities[].fields + endpoint inputs/query params + sub-fields: 154 required, 154 present, 0 missing
Status: PASS

Rule coverage check (Contract 2):
- validations[] priority: 13 expressed as an explicit ordered, masking-aware list, 0 missing
- concurrency_rules[]: 3/3 expressed (write endpoint + expected_<parent>_version + ERR_STALE_VERSION/412, no race framing)
- state_machines[].transitions: 56 checked, all from/to/preconditions/side-effects expressed, 0 missing
- calculations[]: 9/9 fully expressed in precise prose (dual variants for quote_pricing, exchange_core_credit, field_service_pricing; pinned per-line-round-then-sum; half-down cap truncation; ISO 4406 boundary 8192→13/8193→14; credit-check inclusive boundary)
- validations[] conditions: all 33 error ids matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all expressed (approval material cascade, revoke void cascade, rework cleanliness reset, remnant/scrap release, ytd accrual on both close paths), 0 missing
- entities[].fields[] structured content: defaults/nullability/init-value prose verified, 0 missing
- sibling-branch symmetry: cancel fan-out (5 WO states), scrap from QUOTE_SENT vs REVISION_REQUESTED, pass/fail record-result, consume/release — equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only, Contract 3):
- backtick tokens scanned: 698
- tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path tokens: 0
- pseudocode operators (>=, ==, +=, ceil(, etc.) in §3: 0
Status: PASS
```

**Coverage audit (scaffold → PRD)**: entities → §2.4 (common fields) + owning §3 subsection; state machines → §2.7 (cascade/terminal rules) + §3 workflow narratives; calculations → §3.3/3.4/3.5/3.6/3.7/3.8/3.9 embedded in business context, constants mirrored with defaults in §2.10; validations → §2.9 ordered list + per-error trigger sentences near workflows; concurrency_rules → §2.6; response_envelope → §2.2 verbatim + §2.3; endpoints → §4 table (all 70, RBAC roles verified equal to scaffold); errors → §5 table (statuses from the error catalog: ERR_PROMISE_INFEASIBLE/ERR_SPEC_MISMATCH at 422 per catalog) + trigger prose in §2/§3; roles → §2.1 with per-role identity semantics.

**Known gaps**: none material. Two deliberate judgment calls: (1) ERR_ALREADY_TERMINAL (in the catalog but not mapped to any validation priority) is expressed in §2.7/§2.9 as the terminal-state rejection distinct from ERR_INVALID_STATE; (2) where the validations table's category-level http_status (409) diverged from the per-error catalog status (422 for ERR_PROMISE_INFEASIBLE, ERR_SPEC_MISMATCH), §5 follows the error catalog and §2.9 names errors without re-asserting category statuses.


## Step 5: Generate Unit Tests — 2026-08-14T18:45:00.000Z

All checks pass. Work complete.

## Summary

**Generated for `tasks/task_1804_hydraulic_cylinder_fluid_power_shop/`:**

**test_helpers/ (9 files):** `__init__.py` (barrel export), `types.py` (15 entity TypedDicts + status/role enums; all entities carry common fields), `api_client.py` (60 endpoint methods covering every §4 endpoint), `api_errors.py` (33 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity asserts + `get_line_amount`), `factories.py` (16 payload factories), `constants.py` (§2.10 shop defaults, clean sample, 4500 psi hold), `test_users.py` (opaque-role shared constants + mandatory `make_technician_headers`/`make_customer_headers`/`make_inspector_headers` builders), `fixtures.py` (5 tiers: master data, work-order state progression through CERTIFIED, exchange-pool chain through SETTLED, field-service chain through DISPATCHED).

**test_suite/ (conftest.py + 9 files, 79 tests, all pytest-collectible):**

| File | Tests |
|---|---|
| test_01_registration_and_intake.py | 10 |
| test_02_quote_pricing_and_settlement.py | 8 |
| test_03_quote_lifecycle.py | 10 |
| test_04_stock_allocation.py | 7 |
| test_05_repair_and_cleanliness.py | 5 |
| test_06_pressure_testing_and_certification.py | 11 |
| test_07_scrap_and_exchange.py | 12 |
| test_08_field_service.py | 8 |
| test_09_cross_cutting.py | 8 |

**Queue A (Difficulty): 18/18 instances, 36 tests (2 each).** Per rule: dual_variant_calc 4, combinatorial_formula 4, non_linear_state_machine 4, transitive_cascade 4, priority_pair_validation_conflict 4, boundary_precision_check 4, cross_entity_state_dependency 4, resource_temporal_overlap 4, compensating_invariant 4.

**Queue B (Corner): 42/42 non-stub instances, 43 tests.** entities 7, state_machines 4, calculations 10, validations 11, endpoints 2, errors 1, rbac 3, cross_cutting_layers 3, consistency_model 1, validations_customer_lifecycle 1. All 7 `excluded_because:` stubs untranslated; every stub pointer resolves to a real difficulty instance.

**Skipped assertions (two-condition verdicts):** No full instance was skipped. Two individual *asserts* failed unique derivability and were not translated (instances remain covered by their other translated claims):
1. `Difficulty/resource_temporal_overlap/test_bay_booking_requires_thirty_minute_buffer` — the "[11:30,12:30] succeeds" claim (gap exactly == buffer). Verbatim coverage exists, but PRD §3.7's "buffer-extended interval collides with the buffer-extended interval" under closed-interval semantics makes 11:30 collide too (extended spans intersect), while gap-based semantics accepts — two faithful readers ship different outcomes. Translated instead: zero-clearance adjacency rejection and 120-minute-clearance acceptance (both unambiguous under every reading).
2. `Corner/calculations/crimp_tolerance_inclusive_boundary` — the "26.70 mm accepted (deviation exactly 0.3)" claim. In IEEE-754, 27.0 − 26.70 = 0.3000000000000007 > 0.3, so a float-based faithful implementation rejects while a Decimal-based one accepts. Translated instead: the 26.69 rejection leg (float-safe) and a 26.71 acceptance leg asserting COMPLETED + final_price 42000.

**Design-index inconsistencies discovered:** the two items above are genuine index-vs-PRD tensions (index asserts outcomes the PRD does not uniquely pin). Additionally, both `priority_pair_validation_conflict` instances sit in the `validation-priority` silence category but pass the filter because PRD §2.9 explicitly states both the numbered order and the masking rule. No broken stub cross-references.

**Verification performed:** `py_compile` clean on all files; all modules import against the real framework; `pytest --collect-only` = 79; scripted audits confirm every docstring ends with exactly one resolving `Design:` tag, no stub was translated, and all 111 quoted PRD citation segments survive whitespace-normalized literal grep of PRD.md. No skip/xfail markers; no scaffold references in generated code.

## Step 6: Generate Implementation — 2026-08-14T19:02:00.000Z

All 70 endpoints registered, all smoke phases green, both lifecycle paths verified end-to-end. Final summary:

## Implementation complete — task_1804_hydraulic_cylinder_fluid_power_shop

**Files** (all under `workspace/implementation/`):

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Executable launcher; guarded `pip install` (no-op once flask present), `exec python3 app.py`, `PORT` env (default 10000), `0.0.0.0`, foreground |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 49 | App factory, blueprint registration, error handlers (ApiError, 404/405 → ERR_NOT_FOUND envelope, 500 fallback) |
| `db.py` | 131 | In-memory stores (15 dicts, empty at boot, zero seeding), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, ISO8601 parse/format (3 fractional digits), `make_entity`/`touch` (version+updated_at per §2.4) |
| `errors.py` | 146 | All 33 catalog errors with exact error_ids and HTTP statuses |
| `response.py` | 52 | Envelope: `meta.api_request_id` (`req_`…), `api_request_timestamp`, `response_type`, `data`; list meta `limit`/`offset`/`total_count`/`has_more` |
| `middleware.py` | 184 | X-User-ID/X-User-Role auth, 5-role RBAC, body shape validation (priority 1, runs before auth), pagination (limit 1–100 default 10, offset default 0) |
| `calc.py` | 343 | All 9 calculations, Decimal-based, half-up per line then sum; cap half-down |
| `helpers.py` | 158 | Lookups, ownership, terminal guards, seal-kit compatibility, stock allocation/cut procedure |
| `routes_core.py` | 310 | Clock, shops (+OCC PATCH), customers, technicians, seal kits, cylinders |
| `routes_workflow.py` | 776 | Work orders (all 11 actions incl. 17-state machine), teardown reports (+OCC PATCH), quotes, inventory, reservations |
| `routes_quality.py` | 676 | Test bays, pressure tests, certificates, exchange units, field service jobs |

**Endpoint coverage: 70/70** (verified by enumerating Flask's URL map against the PRD §4 table). **Calculation coverage: 9/9** — quote_pricing (provisional/final), invoice_total_settlement (pre-discount tier test, half-up discount/env fee, floor), exchange_core_credit (provisional/final, half-down cap truncation, SCRAP→0 + disposal fee), stock_cut_allocation (smallest-sufficient, created_at tiebreak, remnant-scrap depletion), cleanliness_code_rollup (8192→13 / 8193→14 boundary), pressure_hold_requirement (4500/7500, inclusive pass boundaries), turnaround_tier_gate (24/48 inclusive), field_service_pricing (per-assembly half-up hose term, mileage floor, emergency callout), credit_exposure_check (inclusive boundary, non-terminal WO filter). 3/3 OCC rules (teardown report, technician schedule, shop config — each verified: stale→412, sequential retry with current version succeeds).

**PRD/scaffold divergences (PRD side implemented):**
1. `ERR_SPEC_MISMATCH` and `ERR_PROMISE_INFEASIBLE` — scaffold `validations[]` groups them in 409 rows; both error catalogs say 422 → implemented **422**.
2. Teardown report POST/PATCH ownership — scaffold RBAC says Technician "(assigned WO only)"; PRD §2.9's explicit owner-scoped list omits teardown → **no ownership check** (role only).
3. `ERR_WINDOW_IN_PAST` — scaffold priority-10 `applies_to` mentions pressure-test create; PRD §3.7 never states it for bay bookings (§3.9 states it only for field schedule) → **field schedule only**.
4. Terminal-state masking — per explicit PRD prose: approve of any non-SENT quote (even terminal) → `ERR_QUOTE_NOT_APPROVABLE`; consume/release of non-OPEN reservation (even terminal) → `ERR_RESERVATION_NOT_OPEN`; complete-scrap on non-terminal wrong state → `ERR_SCRAP_NOT_AUTHORIZED`; receive-core pre-fulfill → `ERR_EXCHANGE_NOT_FULFILLED`. Generic transitions still use `ERR_ALREADY_TERMINAL` for terminal targets.
5. `kit_code` uniqueness has no catalog entry → used `ERR_INVALID_REQUEST` (400).

**Judgment calls where PRD is silent** (flagged): complete-assembly blocks only on OPEN reservations (RELEASED ignored); cleanliness-checks on terminal WOs → `ERR_ALREADY_TERMINAL`; teardown-create checks report-existence before from-state (otherwise `ERR_TEARDOWN_REPORT_EXISTS` is unreachable); input datetime fields echoed verbatim, system timestamps canonical `.mmmZ`; `current_utc` echoes the supplied `to_iso8601`; multiple shops → earliest-created governs.

**Boot smoke test:** `bash start.sh` on scratch ports 18755/18756 — booted <4s, served requests, killed; second boot showed empty state (`total_count: 0`). Three self-built suites (~120 assertions) all passed: full repair path with exact cent math (provisional 100720 → revision-loop re-pin → final 121900 → SILVER invoice), rounding-order discrimination (9787.5+391.5 → 22180, not 22179), half-down cap (100005×0.30 → 30001, not 30002), rework loop (FAIL→IN_REPAIR, codes retained, flag reset), cert revoke cascade (VOIDED + TEST_PENDING), exchange reserve/release/fulfill/settle cycle incl. SCRAP core disposal fee, TTL inclusive boundary (exactly +168h passes, +1s flips EXPIRED), credit boundary (exact passes, −1 cent → 402, cross-WO accumulation), bay buffer overlap (incl. PASSED-still-blocks), half-open technician windows, 4h emergency-callout boundary, 0.3mm inclusive crimp tolerance with persisted FAIL measurements, and shape-before-auth priority (400 beats 401).

## Step 7: Run Tests and Iterate — 2026-08-14T19:20:00.000Z

Independent verification confirms a clean sweep: all 8 rounds show `passed=79, total=79, failed=0, errors=0, skipped=0`, and the union of failing tests is empty. Exiting with the final summary.

---

## Summary

**Iterations run:** 2 (two 8-round parallel stability sweeps; sweep 1 surfaced 7 deterministic failures, sweep 2 clean 79/79 × 8).

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule with unique derivability; no PRD-silence or collapse-pattern deletions were warranted.

### Sweep 1 failure analysis (7 tests, all failed deterministically in all 8 rounds — no flakiness)

**Cluster A — `ERR_NO_STOCK_FITS` on quote approval (4 tests), STEP 2 verdict: TEST IS WRONG (setup violates PRD precondition); fixed in test_suite/:**
- `test_03_quote_lifecycle.py::TestValidationPriorityOnApprove::test_approving_approved_quote_reports_state_not_fiscal`
- `test_03_quote_lifecycle.py::TestValidationPriorityOnApprove::test_masked_rejection_leaves_quote_and_work_order_unchanged`
- `test_03_quote_lifecycle.py::TestCreditExposure::test_credit_limit_inclusive_boundary_passes`
- `test_03_quote_lifecycle.py::TestCreditExposure::test_second_approval_over_credit_limit_rejected`

STEP 1: PRD covers the implementation's behavior — §3.4 ("An approved quote fires the material cascade... each allocated by the procedure in §3.5"), §3.5 ("an empty candidate set is rejected with `ERR_NO_STOCK_FITS`"), §2.9 priority 11 ("a stock piece exists that fits the cut" → `ERR_NO_STOCK_FITS`, ahead of fiscal at priority 13). Uniquely derivable: with no fitting stock, rejection is the only PRD-consistent outcome (approving without creating the reservation would contradict §3.4's "the system automatically creates one OPEN stock reservation"). STEP 2: all four tests approved quotes with `rod_needed=True` but created no chrome-rod inventory — a PRD-required check correctly rejected them. Per the cardinal rule, the test setups were fixed, not the implementation check.

**Cluster B — certificate issuance returned `ERR_INVALID_STATE` masking the named errors (2 tests), STEP 3 verdict: TEST IS FAITHFUL, implementation fixed:**
- `test_06_pressure_testing_and_certification.py::TestCertificationGuards::test_segregation_of_duties_beats_certificate_exists`
- `test_06_pressure_testing_and_certification.py::TestCertificationGuards::test_second_certificate_from_independent_inspector_rejected`

STEP 1: PRD §3.7 verbatim — "Segregation of duties is enforced: the issuing inspector's `X-User-ID` must differ from the work order's `assigned_technician_id`, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`" and "At most one `ISSUED` certificate may exist per work order; a second issuance is rejected with `ERR_CERTIFICATE_EXISTS`." Unique derivability holds: after the first issuance the work order is `CERTIFIED` (no longer `TEST_PASSED`), so any implementation that evaluates the from-state check first makes both named errors unreachable and the PRD sentences false — the specific workflow prose pins the order (§2.9's masking makes safety/9 beat structural/11).

**Cluster C — exchange-path close rejected `actual_labor_hours=0` (1 test), STEP 3 verdict: TEST IS FAITHFUL, implementation fixed:**
- `test_07_scrap_and_exchange.py::TestScrapCoreSettlement::test_scrap_core_zero_credit_and_disposal_fee_on_close`

STEP 1: PRD §3.8 verbatim — "On the repair path the work order must be `CERTIFIED`, and `actual_labor_hours` must be a positive number." The positivity rule is explicitly scoped to the repair path; the exchange-path close (`EXCHANGE_FULFILLED` + `SETTLED` unit) carries the field but does not constrain it, and labor hours play no role in the exchange invoice (`unit_price − final_credit [+ disposal fee]`).

### Fixes applied to test_helpers/
None — the defective setup logic lived inline in the four `test_03` test functions, so the fixes landed in `test_suite/` (the correct layer; no shared fixture/factory/header builder was implicated).

### Fixes applied to test_suite/
- `test_suite/test_03_quote_lifecycle.py`:
  - `test_approving_approved_quote_reports_state_not_fiscal` and `test_masked_rejection_leaves_quote_and_work_order_unchanged` — switched from `setup_quote_sent` + manual approve to `setup_approved(customer_overrides={"credit_limit_cents": 150000})`, which stocks the 1000mm chrome-rod piece the §3.4/§3.5 approval cascade requires; the tested second-approve masking scenario (state guard beats fiscal guard) is unchanged.
  - `test_credit_limit_inclusive_boundary_passes` — added `create_inventory_item()` before approval so the 95896 == credit-limit boundary is exercised at the fiscal gate, not masked by `ERR_NO_STOCK_FITS`.
  - `test_second_approval_over_credit_limit_rejected` — added two `create_inventory_item()` calls (each approval cascade cuts 503mm; the first cut leaves 497mm, short of the second cut) so q2's approval reaches the priority-13 credit check and surfaces `ERR_CREDIT_LIMIT_EXCEEDED`.
  - Import line extended with `create_inventory_item` and `setup_approved`.

### Fixes applied to implementation/
- `workspace/implementation/routes_quality.py` — `create_certificate`: reordered guards to existence → WO terminal guard → segregation-of-duties (`ERR_SEGREGATION_OF_DUTIES`) → one-ISSUED-certificate uniqueness (`ERR_CERTIFICATE_EXISTS`) → `TEST_PASSED` from-state (`ERR_INVALID_STATE`) → commit. Both §3.7-named errors are now reachable in the second-issuance scenario; mirrors the codebase's existing teardown-create precedent (report-existence before from-state).
- `workspace/implementation/routes_workflow.py` — `close_work_order`: moved the `actual_labor_hours <= 0` → `ERR_INVALID_REQUEST` check out of the blanket pre-auth position and into the `CERTIFIED` (repair-path) branch only, per §3.8's path-scoped wording; the exchange-path close with `actual_labor_hours=0` now succeeds.

**Final state:** sweep 2 — all 8 parallel rounds, 79/79 passed, 0 failed, 0 errors, 0 skipped, verified by independently reading `results.1.json` through `results.8.json`.

## Step 8: Finalize PRD — 2026-08-14T19:28:00.000Z

The diff is exactly the three intended inline revisions, nothing else. Final verification is complete.

## Summary

**Output:** `workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 388 lines vs PRD_FINALIZED.md 388 lines — 0% delta (3 paragraphs revised inline, no lines added or removed, no new sections).

### Changes (one bullet per change)

- **§3.7 (certification paragraph)** — revise — inserted one sentence pinning the guard evaluation order on certificate issuance: segregation-of-duties first, then the one-`ISSUED`-certificate uniqueness check, both ahead of the `TEST_PASSED` from-state check, with the rationale that a first issuance cascades the work order out of `TEST_PASSED` (a from-state-first order would mask both named errors behind `ERR_INVALID_STATE`) — `implementation/routes_quality.py:230-236` (inside `create_certificate`, lines 217-251).
- **§3.8 (closing paragraph, repair path)** — revise — extended the positivity sentence: a non-positive `actual_labor_hours` on the repair path is rejected with `ERR_INVALID_REQUEST`, and the positivity rule is scoped to the repair path alone — `implementation/routes_workflow.py:311-312`.
- **§3.8 (closing paragraph, exchange path)** — revise — added: the carried `actual_labor_hours` is recorded on the work order but unconstrained on the exchange path (zero accepted) — `implementation/routes_workflow.py:305` (unconditional store) and the `else` branch at lines 325-333.

### Cluster A disposition (no edit)

Cluster A (4 `test_03` failures) was a pure fixture bug per the Step 7 verdict; the PRD already pins the behavior (§3.4 approval cascade → §3.5 `ERR_NO_STOCK_FITS`; §2.9 priority 11 before fiscal 13), and `approve_quote` (`routes_workflow.py:574-618`) matches it: `SENT` check → lazy TTL expiry → stock pre-check via `check_stock_available` (`helpers.py:104-109`) → credit check (`calc.py:341-343`) → commit + cascade. Prose kept verbatim.

### Per-edit pre-edit search log

**Edit 1 — §3.7 guard-order sentence**
- (a) Subject: evaluation order of certificate-issuance guards (segregation, one-`ISSUED` uniqueness, `TEST_PASSED` from-state).
- (b) Paths enumerated: `routes_quality.py:217-251` `create_certificate` (order: shape → auth → role → WO 404 → WO terminal guard → segregation → uniqueness → from-state → commit); `routes_quality.py:281-301` `revoke_certificate` (terminal → `ISSUED` check; no issuance logic); `helpers.py:46` `CERTIFICATE_TERMINAL`; `routes_workflow.py` `close_work_order` (consumes `CERTIFIED`, never creates certificates); grep across all `implementation/*.py` for `segregation|certificate_exists|ISSUED` confirmed no other callsites; parallel precedent `create_teardown_report` (`routes_workflow.py:356-399`, existence check before from-state) read to confirm my wording does not contradict it.
- (c) Wording scoped with "on certificate issuance" and orders only {segregation, uniqueness} vs. the from-state check — deliberately silent on the terminal guard (implementation runs it before segregation, consistent with §2.7/§2.9 as written) and makes no claim about any other endpoint's ordering.

**Edit 2 — §3.8 `actual_labor_hours` path scoping**
- (a) Subject: `actual_labor_hours` constraint and disposition on work-order close.
- (b) Paths enumerated: `routes_workflow.py:70` (initialized null at intake); `:296` (`validate_body` "number", required, both paths); `:305` (stored unconditionally before branching); `:311-312` (positivity check only inside the `CERTIFIED` branch, `ERR_INVALID_REQUEST`); `:321` (passed to final pricing, repair path only); `calc.py:160-188` `quote_pricing_final` (consumes it in the LABOR line, no constraint); `middleware.py:78-80` ("number" shape check only); grep confirmed no other references to the field anywhere in `implementation/`.
- (c) The retained verbatim sentence "always carries `actual_labor_hours`" preserves requiredness on both paths (so "not constrained" cannot be misread as "may be omitted"); "recorded on the work order" matches the unconditional store at line 305; the `ERR_INVALID_REQUEST` pin matches the implementation's error id exactly.

## Step 9: Complete PRD — 2026-08-14T19:42:00.000Z

PRD_COMPLETED.md is complete. All 33 changes applied as in-paragraph inserts/revisions — no new sections, no invented behavior.

## Summary

**Files**: `workspace/PRD_FINALIZED.md` (388 lines, 67,607 chars) → `workspace/PRD_COMPLETED.md` (390 lines, 73,589 chars). Char delta: **+5,982**.

**Counts**: 24 ambiguity-pins (inserts), 9 mismatch-revisions.

### Changes

- §2.2 success envelope — insert — ambiguity — action endpoints return the addressed resource; work-order actions return the work order even when a second resource is also mutated — implementation/routes_workflow.py:291, implementation/response.py:20
- §2.2 error envelope — insert — ambiguity — undeclared paths and unsupported methods surface `ERR_NOT_FOUND` (404); unexpected failures surface `ERR_INTERNAL` (500) in the same envelope — implementation/app.py:29-40
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST`; `has_more` = offset + returned < total_count — implementation/middleware.py:149-170, implementation/response.py:34
- §2.3 — insert — ambiguity — creation-timestamp ties broken by insertion order — implementation/db.py:131
- §2.5 — insert — ambiguity — clock-set echoes the supplied `to_iso8601` verbatim as `current_utc`; all server-emitted timestamps (created_at/updated_at/sent_at/meta) read the logical clock — implementation/routes_core.py:30, implementation/db.py:106-120
- §2.7 — insert — mismatch — exceptions to blanket `ERR_ALREADY_TERMINAL`: approving a non-SENT quote → `ERR_QUOTE_NOT_APPROVABLE`, consuming/releasing a non-OPEN reservation → `ERR_RESERVATION_NOT_OPEN`, even for terminal resources — implementation/routes_workflow.py:582-583, 745-746, 760-761
- §2.8 — revise — mismatch — integer-millimetre claim scoped to cylinder/stock quantities; pinned fractional labor hours, `length_m`, crimp diameters, and integer `distance_km` — implementation/middleware.py:57-62, implementation/routes_quality.py:459-467
- §2.9 item 1 — insert — ambiguity — malformed/non-object JSON body is a shape failure; undeclared fields ignored; booleans never accepted as int/number; no range constraints beyond the explicitly named ones — implementation/middleware.py:57-142
- §2.9 item 4 — insert — ambiguity — customer-ownership list extended to cylinder registration, work-order creation, and field-service booking — implementation/routes_core.py:265, implementation/routes_workflow.py:53, implementation/routes_quality.py:490
- §2.10 — insert — ambiguity — multiple shops allowed with earliest-created governing, defaults applying before any shop exists; config read at call time except the four explicit snapshots (tier_snapshot, pinned_teardown_version, reservation kerf_mm, required_hold_psi) — implementation/calc.py:65-82
- §3.1 — insert — ambiguity — duplicate `kit_code` rejected with `ERR_INVALID_REQUEST`; `fluid_compat` may be empty — implementation/routes_core.py:223-225
- §3.2 — insert — ambiguity — work-order creation by a non-owning Customer → `ERR_NOT_OWNER`; `promised_hours` is an integer number of hours — implementation/routes_workflow.py:47, 53
- §3.3 — revise — mismatch — teardown filing open to any Technician (no assignment-ownership check), replacing "The assigned Technician then files" — implementation/routes_workflow.py:371-372
- §3.3 — revise — mismatch — omitted `seal_kit_id` override stored as null with fallback to the cylinder's kit at use, not stored as the cylinder's kit — implementation/routes_workflow.py:392, implementation/calc.py:143
- §3.3 — insert — ambiguity — report-existence check runs ahead of the TEARDOWN from-state check, so a second filing always surfaces `ERR_TEARDOWN_REPORT_EXISTS` — implementation/routes_workflow.py:375-378
- §3.3 — insert — ambiguity — revision consistency re-checked on merged result (flag false clears cut length, mismatched length → `ERR_INVALID_REQUEST`); `seal_kit_id` null clears the override; re-validation only when the merged override changes — implementation/routes_workflow.py:449-471
- §3.3 — insert — ambiguity — quote drafting legal from-states QUOTE_DRAFT/REVISION_REQUESTED, otherwise `ERR_INVALID_STATE` — implementation/routes_workflow.py:490-491
- §3.3 — insert — ambiguity — `line_items` emitted in pinned kind order; SEAL_KIT/HONING/LABOR/SUPPLIES always present even at zero — implementation/calc.py:122-135
- §3.4 — revise — mismatch — request-revision `notes` accepted but not persisted on the quote — implementation/routes_workflow.py:623-637
- §3.5 — insert — ambiguity — manual reservation requires only that the work order exist; no work-order state precondition — implementation/routes_workflow.py:704-706
- §3.5 — insert — ambiguity — releasing a non-OPEN reservation → `ERR_RESERVATION_NOT_OPEN`; linked work-order state not consulted — implementation/routes_workflow.py:759-761
- §3.6 — insert — ambiguity — cleanliness sample recordable in any non-terminal work-order state; counts must be non-negative integers — implementation/routes_workflow.py:244-249
- §3.6 — revise — mismatch — assembly-completion gate blocks only OPEN reservations; a RELEASED reservation does not block (was "every reservation must be CONSUMED") — implementation/routes_workflow.py:226-229
- §3.7 — insert — ambiguity — no window-in-past rule and no window-ordering requirement on test-bay bookings — implementation/routes_quality.py:84-110
- §3.7 — revise — mismatch — bay blocked by bookings in status SCHEDULED or PASSED (a PASSED booking blocks even after certification), replacing "passed but still pending downstream resolution" — implementation/routes_quality.py:66-81
- §3.7 — insert — ambiguity — certificate created with `revoke_reason` null; pinned to the latest-created PASSED test — implementation/routes_quality.py:237-247
- §3.8 — revise — mismatch — complete-scrap `disposal_method` required but accepted without persistence on the work order — implementation/routes_workflow.py:186-199
- §3.8 — insert — ambiguity — select-exchange legal from EXCHANGE_SELECTED (re-selection after release) as well as QUOTE_SENT — implementation/routes_workflow.py:271-272
- §3.8 — insert — ambiguity — a close rejected after the from-state check still stores the submitted `actual_labor_hours`, without a version increment — implementation/routes_workflow.py:305
- §3.8 — revise — mismatch — final-variant rod/tube lines sum `consumed_length_mm` over all CONSUMED reservations of the material with one flat cut fee per line, and the tier multiplier comes from the approved quote's `tier_snapshot` — implementation/calc.py:167-183, implementation/routes_workflow.py:315-317
- §3.9 — insert — ambiguity — field booking by a non-owning Customer → `ERR_NOT_OWNER`; `distance_km` integer; `assemblies` may be empty; client-sent `crimp_measured_mm`/`assembly_result` ignored — implementation/routes_quality.py:479-508
- §3.9 — insert — ambiguity — past-window check runs before the overlap check; no window-ordering requirement — implementation/routes_quality.py:578-581
- §3.9 — insert — ambiguity — `crimp_measurements` accepts positional numbers or objects naming `assembly_index` (or `index`) and `crimp_measured_mm` (or `value`), mixable; invalid entries → `ERR_INVALID_REQUEST`; unmeasured assemblies count as out of tolerance — implementation/routes_quality.py:625-654

Notable pre-existing alignment (verified, no change needed): all endpoint paths/roles/201-vs-200 statuses in §4, the full error catalogue in §5, all state-machine transitions and terminal sets, every calculation formula (quote pricing, invoice waterfall, core credit with half-down cap, ISO 4406 rollup, required hold psi, tier gate, field pricing, stock selector), the certificate-issuance check reordering, and the OCC operations.

# Worklog — task_2744_tip_pooling_tip_credit_service_charge_distribution

## Step 1: Create task directory — 2026-09-04T14:55:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2744_tip_pooling_tip_credit_service_charge_distribution` and its `workspace/` subdirectory. Index 2744 was pre-assigned by the invoking pipeline; no index scan/allocation performed (32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T17:23:00.000Z

All three scaffold artifacts are complete, YAML-valid and lint-clean.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2744_tip_pooling_tip_credit_service_charge_distribution/`
- `SCAFFOLD.yaml` — 2 978 lines (§1.0–§1.7, neither design key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1 670 lines (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4 556 lines (single key `scaffold_corner_design`)

## SCAFFOLD.yaml contents
13 entities / 10 state machines (Location, TipPoolPolicy, PayPeriod, Shift ×2 dimensions, ShiftTipPool ×2 dimensions, PayLine, Dispute, BackWageCorrection, ServiceChargeEvent) / 2 `concurrency_rules` / 9 calculations / 55 priority-ordered validations / 51 endpoints / 62 errors / 5 roles (`PayrollAdmin`, `PayrollPreparer`, `ComplianceOfficer`, `ShiftManager`, `Employee`; role model = segregation of duties, two entity-backed identities). Complexity layers: `dual_variant_calculation`, `rate_threshold_triggers`, `cascading_side_effects`, `optimistic_concurrency`; consistency model `immediate`; logical clock via `POST /_clock/set_current_utc` only.

## §1.8 — difficulty design
9 rules × 2 instances = **18**: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

## §1.9 — corner design
All nine claim-extraction-guide sections, **53 real instances + 16 `excluded_because` stubs = 69 named instances**, 1 049 linted calls total:

| section | real | stubs |
|---|---|---|
| entities | 12 | 0 |
| state_machines | 14 | 2 |
| calculations | 4 | 6 |
| validations | 3 | 6 |
| endpoints | 4 | 0 |
| errors | 9 | 0 |
| rbac | 3 | 0 |
| complexity_layers | 3 | 2 |
| consistency_model | 1 | 0 |

Work completed this session: the `errors` section (9 `triggerable` instances: typed-404 probe matrix, location/job-role config guards, policy-activation statutory guards, shift side-work/date/sales guards, period-length + assignment-overlap + separation guards, pool-creation gate ladder, manager-only & participantless pools, dispute award/duplicate guards, correction ceiling & supersede guards), the `rbac` section (auth ladder, entity-backed ownership scoping, segregation of duties), `complexity_layers` (both OCC rules + the 8 % allocated-tips threshold at 7000/8000/7999, plus stubs for cascade depth and dual-variant), and `consistency_model` (immediate visibility across the distribute cascade).

## Verification
- `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`
- Error-coverage audit script: **0 of 62** error ids lack a positive (non-"is NOT") trigger; **0** referenced ids missing from the catalog.
- Name uniqueness across §1.8 ∪ §1.9: 87 names, all unique; every stub's `difficulty_instance` citation resolves to a real §1.8 `rule_id / name` pair.

## Design adjudications made this session
1. **Priority 44 (`ERR_EMPLOYEE_SEPARATED`) was partly dead code.** No endpoint sets `separation_date` after hire, and the original blanket "a separated employee may not receive a new EmployeeRoleAssignment" limb made the shift limb unreachable. Narrowed to reject an assignment whose `effective_from` is after `separation_date` (and a shift dated after it), so a terminated employee's pre-separation history — and final cheque — can still be recorded. Edited both the §1.4 check and the §1.6 condition.
2. **`ERR_JOB_ROLE_NOT_FOUND` does not exist** (JobRole/EmployeeRoleAssignment/ServiceChargeEvent/PoolAllocation share `ERR_RECORD_NOT_FOUND`); a stale reference in §1.8 was corrected.
3. **Table 6 has no claim_type rows**, so `triggerable` is used for every errors-section instance (the guide's only prose requirement).
4. **RBAC claim_types**: `segregation_of_duties` is the only role-model table row that applies; the two per-role bullet claims use the guide's own field names `exclusive_operations` / `shared_operations`.
5. **Priority 32's dispute limb is shadowed by priority 6** (POST /disputes is Employee-exclusive, and priority 6 already covers both raiser/pay-line mismatch shapes), so that ordering is asserted explicitly and `ERR_EMPLOYEE_LOCATION_MISMATCH` is triggered through `POST /shifts` instead.
6. Unauthenticated probes are written `as: NONE` (no `X-User-Role`/`X-User-ID` headers); the linter treats them as negative triggers.

## Step 3: Copy shared files — 2026-09-04T17:24:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T17:41:00.000Z

PRD complete.

**Output:** `workspace/PRD.md` — 528 lines, ~16,000 words. Ends cleanly at the final row of the §5 error table; no audit footer, no contract reports written into the file or any sibling file. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened or grepped, and no sibling task directory was read.

**Section list**
- `# Tip Pooling Payroll API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (fixed block, verified byte-identical and present); 2.3 Pagination; 2.4 Statutory Wage Floors and the Tip-Credit Ceiling; 2.5 Cents, Minutes, Basis Points and Rounding; 2.6 Record Identity, Audit Stamps and the Logical Clock; 2.7 Optimistic Concurrency Control; 2.8 Cascades, Recomputation and Cross-Aggregate Consistency; 2.9 Segregation of Duties; 2.10 Validation Precedence (all 55 rungs, numbered, with condition + error ID + status + full `applies_to`); 2.11 Collection Filters and Read Scoping
- `## 3. Business Logic & Workflows` — 3.1 Chain Configuration: Restaurant Units and Job Roles; 3.2 Employees, Job Assignments and the Tip-Credit Notice; 3.3 Governing the Pool: Drafting and Activating a Policy; 3.4 The Workweek: Opening a Pay Period and Recording Shifts; 3.5 Closing a Shift: Side-Work Classification and Tip Declaration; 3.6 Mandatory Service Charges: Wages or Tips; 3.7 Shift Tip Pools: Contribution, Card Fees, Distribution and Reversal; 3.8 The Payroll Cycle: Computing, Approving and Reopening a Period; 3.9 When the Numbers Are Wrong: Disputes and Back-Wage Corrections
- `## 4. Endpoint Definitions` — intro paragraph on 201/200 rules plus a 4-column table (Method, Path, Description, Authorized Role(s)) with all 51 rows
- `## 5. Error Code Catalogue` — 2-column table (Error ID, HTTP Status Code) with all 62 rows

**Coverage:** 13/13 entities, 10/10 state machines (32/32 transitions, each with preconditions and side effects), 9/9 calculations, 55/55 validations in priority order, 51/51 endpoints, 62/62 errors, 5/5 roles, 2/2 concurrency rules.

Field coverage check: entities[].fields 129/129 present; endpoints[].request_body 81/81 present; query_params 0 missing. Status PASS. (First pass produced 126 false "missing" hits caused by the checker pairing backticks across the §2.2 fenced JSON blocks; after excluding fenced blocks the diff was empty on both passes.)

Rule coverage check: 55/55 validations expressed in prose; 2/2 OCC rejections; 32/32 transitions; 9/9 calculations; 51/51 endpoint side_effects/applies_to; 129/129 entity fields reconstructible; 6/6 sibling-branch symmetry groups with equal prose density. Status PASS. (Symmetry groups: dispute `UPHELD`/`PARTIALLY_UPHELD`/`DENIED`; shift void from `OPEN` and from `CLOSED`; service-charge void from `RECORDED` and from `ALLOCATED`; pool reverse from `DISTRIBUTED` and from `PENDING`; period reopen from `COMPUTED` and from `APPROVED`; pay line to `SUPERSEDED` from `DRAFT` and from `FINAL`.)

Path purity check (§3 only): 1076 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens. Status PASS.

Two things flagged to the orchestrator:
1. **Scaffold inconsistency, handled without inventing a rule.** Validation rung 10 (`ERR_SHIFT_ALREADY_POOLED`) requires `shift_tip_pool_id` to be null, while the `Shift` void transition precondition permits a non-null pool whose `contribution_status` is `REVERSED`. The prose covers both readings (the shift must not be attached to a non-reversed pool; reversal clears the link anyway), which also matches the error catalogue's own condition text.
2. **Two preconditions in the scaffold have no matching `applies_to` entry.** Shift void has no error ID for a target already `VOIDED`, so the precondition is stated without an invented code; and dispute adjudication's "the disputed pay line is still `FINAL`" precondition is not listed in rung 22's `applies_to`, so it was attributed to `ERR_PAY_LINE_NOT_FINAL`, the only code whose condition text covers it.

**Orchestrator truncation check:** independently verified — `tail -25` ends at the last `| ERR_... | 422 |` row of the §5 table (a real section boundary, not mid-sentence); a scripted cross-check against SCAFFOLD.yaml confirms all 62 error ids and all 51 endpoint paths appear in PRD.md. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T19:10:00.000Z

All closing checks pass. Suite is complete.

## Deliverables

`test_helpers/` — 9 files, 2371 lines
```
__init__.py 211   api_client.py 243   api_errors.py 157   assertions.py 318
constants.py 55   factories.py 169    fixtures.py 757    test_users.py 60   types.py 401
```

`test_suite/` — conftest.py (45) + 21 test modules, 8097 lines
```
test_01_shift_intervals_and_period_state 312 (6)   test_12_calculation_corners            657 (6)
test_02_boundary_precision               172 (4)   test_13_validation_corners             548 (6)
test_03_validation_priority_pairs        203 (4)   test_14_endpoint_corners               471 (5)
test_04_pool_card_fees                   191 (4)   test_15_error_catalog_and_configuration 363 (5)
test_05_pool_reversal_and_conservation   367 (6)   test_16_error_shift_and_interval_guards 476 (5)
test_06_wage_computation                 183 (4)   test_17_error_pool_guards              396 (6)
test_07_pay_period_cycle                 259 (5)   test_18_error_dispute_and_correction_guards 475 (5)
test_08_disputes_and_corrections         243 (4)   test_19_rbac_and_segregation           542 (7)
test_09_entity_catalog                   592 (12)  test_20_complexity_layer_corners       383 (3)
test_10_shift_pool_and_policy_machines   454 (7)   test_21_consistency_model              242 (2)
test_11_payroll_cycle_machines           523 (6)
```

## Coverage — 113 tests, exact 1:1 with the design indices

- **Queue A (§1.8 difficulty):** all 18 non-stub instances translated, 37 tests, every instance ≥2 tests. Nine rules × 2 instances each: `resource_temporal_overlap`, `cross_entity_state_dependency`, `boundary_precision_check`, `priority_pair_validation_conflict`, `dual_variant_calc`, `combinatorial_formula`, `transitive_cascade`, `compensating_invariant`, `non_linear_state_machine`.
- **Queue B (§1.9 corner):** all 53 non-stub instances translated, 76 tests, every instance ≥1 test — entities 12, state_machines 14, calculations 4, validations 3, endpoints 4, errors 9, rbac 3, complexity_layers 3, consistency_model 1.
- **Audit result:** expected 71 non-stub instances / got 71 distinct `Design:` tags, zero MISSING, zero EXTRA; 113 `def test_` = 113 tags, no file with a mismatch, no untagged or dual-tagged test.
- **16 corner stubs** left untranslated by design (they defer to §1.8); every `excluded_because.difficulty_instance` pointer was verified to resolve — "stubs 16 broken 0".

## Instances SKIPPED: none

No instance failed the PRD-first two-condition filter. Every non-stub instance in both indices had verbatim PRD coverage and a uniquely-derivable outcome, so nothing was weakened, xfailed, or stubbed out.

## Design-vs-PRD conflicts where the PRD value was asserted

- **Timestamps:** the design yamls write instants as `...T12:00:00Z`, but the PRD mandates exactly 3 fractional digits. Every instant assertion goes through `assert_instant_equals`, never string equality.
- **`location_version_occ_on_policy_activation` under-proves its own ordering claim:** its trigger 6 replays the activation with the *current* version, so `ERR_POLICY_NOT_DRAFT` there does not demonstrate rung 11 preceding rung 23. A second probe was added presenting the stale version 1 against the now-SUPERSEDED policy — violating both rungs at once — which must still answer `ERR_POLICY_NOT_DRAFT`/409 (`test_20_complexity_layer_corners.py:117`).

## Verification run

`python3 -m py_compile` over all 31 `.py` files → COMPILE_OK. Every test module additionally imported under `PYTHONPATH=.:./test_suite` (catches missing imports that py_compile cannot) → zero failures. All docstring PRD quotations `grep -F`-confirmed verbatim against `workspace/PRD.md`, and section labels checked against its `^### ` heading map. `__pycache__` cleaned up; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation` — no stray `test_helpers/` or `test_suite/` under it, and `workspace/implementation/` was never read or written.

## Step 6: Generate implementation — 2026-09-04T19:10:00.000Z

Implementation complete and verified.

## Files written — `workspace/implementation/`

| file | lines | role |
|---|---|---|
| `app.py` | 79 | Flask factory, 5 blueprints, `before_request` clock/version bookkeeping, `ApiError` + HTTPException handlers, `PORT` default 10000 |
| `store.py` | 207 | in-memory dicts (13 collections), logical clock (default `2026-08-01T00:00:00.000Z`), audit stamps, `_seq` deterministic ordering |
| `errors.py` | 94 | all 62 error ids → HTTP status |
| `envelope.py` | 60 | `meta`/`response_type`/`data` envelope, `req_`+20 chars, real-UTC timestamp, pagination meta |
| `validators.py` | 213 | rung-3 structural validation, declarative body/query specs, strict int typing (rejects money-as-string and bools) |
| `auth.py` | 126 | rungs 1–2, `Actor`, ownership (rung 6) and collection scoping for Employee / ShiftManager |
| `serial.py` | 232 | per-entity ordered response field lists, paging, filters |
| `calc.py` | 224 | `ROUND_HALF_UP` helpers, largest-remainder split, side-work classification, wage waterfall S0–S9 both variants, 8% threshold |
| `cascades.py` | 236 | all rollup recomputations, pay-line supersession, server-initiated reopen, 5-record-deep pool reversal |
| `routes_config.py` | 442 | locations, job-roles, employees, role-assignments, policies + activate, `_clock/set_current_utc` (17 endpoints) |
| `routes_periods.py` | 475 | pay-periods CRUD + compute/approve/reopen, service-charge wages allocation, reporting test, pay-lines (8) |
| `routes_shifts.py` | 405 | shifts CRUD + close/declare-tips/void, service-charges + void (10) |
| `routes_pools.py` | 395 | pools create/read/list, distribute, reverse, pool-allocations (7) |
| `routes_disputes.py` | 419 | disputes + adjudicate/close, back-wage-corrections + apply (9) |
| `start.sh` | 15 | guarded `pip install flask`, `exec python3 app.py` on `0.0.0.0:$PORT` |
| `requirements.txt` | 1 | flask |

**51 endpoints** registered (verified by enumerating `app.url_map` — exactly matches the SCAFFOLD endpoint table, all creates 201, everything else 200). Storage is in-memory dicts only; nothing seeded, no disk or /tmp state.

## Verification
- `python3 -m py_compile *.py` → clean; `__pycache__` removed.
- End-to-end smoke via Flask test client (config → policy activation → period → 2 shifts → close → declare → TIPS/WAGES charge → pool → distribute → compute → approve → dispute → partial award → correction apply → close → reopen, plus pagination/401/403/404 probes): **0 failures**. Spot-checked arithmetic: obligation 13200, straight cash 8000, regular rate 1375, three-way capped credit 2200, 8%-threshold shortfall 6000 split 3000/3000, pool 300 split 200/100 by 10:5 points, service charge 6000 split 3000/3000 by minutes.
- Real server booted with `PORT=18744 bash start.sh`, served POST/GET `/locations` (201/200), then killed by recorded PID only; port confirmed free afterwards (no broad pkill used).

## Ambiguities resolved (readings chosen)
- `api_request_timestamp` = real wall-clock UTC; all entity stamps = logical clock.
- `Location.version` bumped **only** by policy activation; `pending_pool_cents` recomputation refreshes `updated_at` alone.
- `net_pool_cents` at creation = `total_contributed + service_charge_tips` (a service-charge void subtracts from it while still PENDING).
- Approve overwrites only `tip_credit_cents`, `topup_cents`, `total_gross_cents` (+`variant`/`status`/`allocated_tips_cents`/`version`, and `Shift.shift_tip_credit_cents`); aggregate-derived fields survive.
- PER_SHIFT: per-shift OT threshold and per-shift tips; period-level `service_charge_wages + overtime_premium` deducted from the earliest shift's residual only.
- §2.10 ladder overrides §3 prose ordering — notably SoD (rung 7) precedes the COMPUTED check (rung 13) on approve.
- Uncatalogued guards: pool reverse fiscal guard → 409 `ERR_PAY_PERIOD_NOT_OPEN`; service-charge void against a non-PENDING pool → 409 `ERR_POOL_ALREADY_DISTRIBUTED`; pool creation with no covering period → `ERR_PAY_PERIOD_NOT_OPEN`.
- `ERR_MANAGER_POOL_PARTICIPATION`: candidate set = CLOSED, unpooled shifts at (unit, date); fires when non-empty and all management.
- Positivity with dedicated codes: service-charge `amount_cents` → `ERR_CHARGED_SALES_EXCEED_GROSS_SALES`; correction `amount_cents` → `ERR_CORRECTION_EXCEEDS_CLAIM`; dispute `claimed_amount_cents` → `ERR_INVALID_REQUEST`.
- Cash-wage bounds: strict upper bound when `tip_credit_enabled`, non-strict when disabled.
- Adjudication-created correction `reason_code` = supplied value, else mapped from dispute category.
- Client reopen releases WAGES charges to RECORDED; server-initiated reopen does not (and additionally recomputes minutes/receipts).
- `open_dispute_count` changes refresh `updated_at` but never `version`.
- Date fields accept both `YYYY-MM-DD` and full UTC instants, normalised to midnight UTC (`...T00:00:00.000Z`) as the scaffold specifies.

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single message, so the impl generator was physically unable to read `test_suite/` (it did not exist at its spawn time). Verified after the fact: `test_helpers/` and `test_suite/` sit at the task root (not under `workspace/`), 22 files in `test_suite/`, 113 `def test_` functions.

## Step 7: Run tests and iterate — 2026-09-04T19:24:00.000Z

All 8 parallel rounds green: 113/113 each.

## Summary

**Iterations run:** 2 (iteration 1: 102/113 in all 8 rounds, 11 deterministic failures — no flakiness; iteration 2: 113/113 in all 8 rounds).

**Tests deleted:** none. Every failure traced to a test-artifact defect under STEP 2 (test setup/assertion not faithful to PRD), not to PRD silence, and not to the implementation. **No changes were made to `workspace/implementation/`.**

**Fixes applied to `test_suite/`** (all 11 failures; `test_helpers/` needed no change):

- `test_suite/test_17_error_pool_guards.py`
  - `declare_shift_tips(..., cash=, charged=)` → positional args (4 call sites). The helper's parameters are `declared_cash_tips_cents` / `declared_charged_tips_cents`; the kwargs raised `TypeError` before any request was issued. Fixed 3 tests.
  - `_two_date_world()`'s `role_mgr` was created with `is_management=True` while inheriting the factory's `pool_contribution_pct_bps=1500` / `pool_share_points=10`. PRD §3.1: *"Both attributes must be 0 when `is_management` is true."* The PRD-faithful implementation correctly rejected the setup with `ERR_INVALID_REQUEST`; added explicit `pool_contribution_pct_bps=0, pool_share_points=0`. Fixed 3 tests.

- `test_suite/test_09_entity_catalog.py` — `test_three_units_separate_the_two_wage_ceilings_from_their_inputs` supplied `state_min_wage_cents=700`. PRD §2.4: *"that state's minimum wage in cents per hour as `state_min_wage_cents`, which may not be below 725."* Changed to 725 (the tie case that still exercises "the greater of"); both asserted derivations (`applicable_min_wage_cents == 725`, `max_tip_credit_per_hour_cents == 512`) are unchanged, so the covered rule is preserved rather than weakened.

- `test_suite/test_15_error_catalog_and_configuration.py` — `_two_unit_policy_world()`'s two `ALL_NON_MANAGEMENT` drafts inherited `cc_fee_pass_through=True` from the factory, so activating `boh_ca` at the `PROHIBITED`/no-tip-credit California unit legitimately tripped rung 27 `ERR_CC_FEE_DEDUCTION_PROHIBITED`. Pinned `cc_fee_pass_through=False` on `boh_tx`/`boh_ca` so the "back-of-house shape" isolates the `pool_type` guard as the test intends. (The sibling test that was already passing still passes — at Texas, rung 26 fires first regardless.)

- `test_suite/test_10_shift_pool_and_policy_machines.py` — `test_reversed_is_terminal_on_both_pool_dimensions_under_one_error_id` expected `ERR_POOL_REVERSED` when distributing a `REVERSED` pool. PRD §3.7 states verbatim: *"the pool's `distribution_status` must be `PENDING`, so distributing a pool already `DISTRIBUTED` or already `REVERSED` yields `ERR_POOL_ALREADY_DISTRIBUTED`"* (also ladder rung 16 before rung 17). Corrected the expected `error_id` to `ERR_POOL_ALREADY_DISTRIBUTED` and added the governing PRD quote to the docstring; the second-reverse assertion (`ERR_POOL_REVERSED`) is untouched. Note: the scaffold-derived design tag on this test (`..._both_return_pool_reversed`) contradicts PRD prose — PRD prose won.

- `test_suite/test_14_endpoint_corners.py` — two calls passed a label as a second positional arg to `assert_timestamp_format(timestamp)`, which takes one argument; dropped the extra arg. Fixed 2 tests.

**Orchestrator verification:** all 8 `workspace/implementation/results.{1..8}.json` exist on disk (each ~35 KB, mtime 19:23) and each independently parses to `passed=113 / total=113 / failed=0`. Sweep artifacts confirmed, not merely claimed.

**Step 8 decision:** Step 7 made 0 `implementation/` fixes and 0 deletions, but 11 `test_suite/` fixes, so the skip condition (zero fixes of every kind) does not hold — Step 8 will run. It may legitimately produce a byte-identical `PRD_FINALIZED.md`, since none of the 11 fixes revealed a PRD/impl divergence (all were test-artifact defects: two Python signature misuses and three fixtures violating PRD-stated input constraints, plus one assertion that contradicted PRD prose in favour of a scaffold-derived expectation).

## Step 8: Finalize PRD — 2026-09-04T19:30:00.000Z

## Result: `PRD_FINALIZED.md` is byte-identical to `PRD.md`

- **Line counts:** PRD.md 528 lines → PRD_FINALIZED.md 528 lines, **0% delta** (identical md5 `06a3b08d…`).
- **Changes:** none. No `<step_7_diff>` item revealed a PRD silence or a PRD/implementation mismatch.

### Per-item verification log (subject → impl paths enumerated → verdict)

1. **`test_17` `declare_shift_tips(cash=, charged=)` kwargs (4 sites).** Subject: helper signature. A `TypeError` raised client-side before any HTTP request — no server behavior observed at all. Nothing to pin. **No edit.**

2. **`test_17` `_two_date_world` `role_mgr` with `is_management=True` and inherited `pool_contribution_pct_bps=1500`/`pool_share_points=10` → `ERR_INVALID_REQUEST`.** Subject: the management-role zero-attribute constraint and its error id. Enumerated: `implementation/routes_config.py:118-147` (`JOB_ROLE_SPEC`, the `management and (… != 0 …)` guard at 137-143 raising `invalid(...)`, placed before the rung-49 duplicate-code check), `implementation/errors.py:93` (`invalid` → `ERR_INVALID_REQUEST`, 400 per `errors.py:9`), `implementation/validators.py:124`. PRD §3.1 already states the constraint verbatim ("Both attributes must be 0 when `is_management` is true"), and `ERR_INVALID_REQUEST` (ladder rung 3, §2.10) is the only body-validation error in the catalogue for `/job-roles` besides `ERR_DUPLICATE_JOB_ROLE_CODE`; the impl's rung-3-before-rung-49 ordering matches §2.10. Fixture violated a stated constraint. **No edit.**

3. **`test_09` `state_min_wage_cents=700` → rejected.** Subject: the 725 floor on `state_min_wage_cents` and its error id. Enumerated: `routes_config.py:43` (`f("state_min_wage_cents", "int", True, min=FEDERAL_MIN_WAGE_CENTS)`), `validators.py:124` (`as_int` min bound → `invalid`), `routes_config.py:57-67` (`applicable` derivation and the rung-28 cash-wage guard, which is reached only after parse). PRD §2.4 states "may not be below 725" verbatim; rejection at rung 3 with `ERR_INVALID_REQUEST` is the only ladder-consistent reading. The test's own asserted derivations (`applicable_min_wage_cents == 725`, `max_tip_credit_per_hour_cents == 512`) still hold. **No edit.**

4. **`test_15` `_two_unit_policy_world` inheriting `cc_fee_pass_through=True` → rung 27 fired instead of rung 26.** Subject: activation guard ordering. Enumerated: `routes_config.py:384-402` — rung 11 → rung 23 → rung 26 (`ALL_NON_MANAGEMENT` + `tip_credit_enabled`) → rung 27 (`cc_fee_pass_through` + `PROHIBITED`), exactly the order PRD §3.3 and §2.10 rungs 26/27 already specify. The California unit is `PROHIBITED` with no tip credit, so rung 26 passes and rung 27 legitimately fires; the Texas sibling hits rung 26 first. Fixture bug. **No edit.**

5. **`test_10` expected `ERR_POOL_REVERSED` when distributing a `REVERSED` pool.** Subject: distribute's guard ladder. Enumerated: `routes_pools.py:260-279` — rung 16 `distribution_status != "PENDING"` → `ERR_POOL_ALREADY_DISTRIBUTED` (line 268-269) precedes rung 17 `contribution_status != "CONTRIBUTED"` → `ERR_POOL_REVERSED` (270-271), then rung 52 (272) then rung 53 (278). Also checked `routes_pools.py:350-364` (reverse endpoint, which does raise `ERR_POOL_REVERSED` on a second reverse — the test's other assertion, untouched). PRD §3.7 already states this verbatim and §2.10 orders rung 16 before 17. Test assertion was wrong. **No edit.**

6. **`test_14` extra positional arg to `assert_timestamp_format` (2 sites).** Subject: helper arity. Client-side `TypeError`, no server behavior observed. **No edit.**

### Key finding
Step 7 made **no** implementation changes and deleted **no** tests; all 11 failures were test-artifact defects (two Python-arity errors, three fixtures violating constraints the PRD states verbatim in §2.4/§3.1, one fixture that mis-shaped a ladder-order probe, one wrong expected `error_id` contradicting PRD §3.7 verbatim text). Consistent with that, there is nothing for Step 8 to pin — every behavior the failures touched is already uniquely determined by PRD.md, and the implementation matches it at each site.

**Orchestrator note:** independently verified with `md5sum` — PRD.md and PRD_FINALIZED.md are both 528 lines with hash `06a3b08d0fc81e8e9daf7f8a6a68d5a8`. A byte-identical PRD_FINALIZED.md is the correct outcome when Step 7 applied zero `implementation/` fixes, which is the case here. Step 9 (which always runs and does a full impl scan) is the pass that must not be identical.

## Step 9: Complete PRD — 2026-09-04T20:05:00.000Z

**Orchestrator decision:** Step 9 was run as FOUR sequential module-partitioned passes over one shared `PRD_COMPLETED.md` (a single-shot full scan of a 3607-line implementation against a 528-line PRD reliably under-scans or dies at the output cap). Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2–4 edited in place and were forbidden from copying. Partition: pass 1 = app/store/errors/envelope/validators/auth/serial; pass 2 = calc/cascades/routes_config; pass 3 = routes_shifts/routes_pools; pass 4 = routes_periods/routes_disputes plus a whole-file consistency read.

### Pass 1 (infra modules) — 9 ambiguity-pins, 5 mismatch-revisions
528 lines / 115,712 chars → 528 lines / 120,427 chars (+4,715). 12 lines touched, all in §2.1–§2.11.
- §2.1 — insert — ambiguity — an `Employee`/`ShiftManager` `X-User-ID` naming no stored Employee row scopes to nothing: ownership checks 403, scoped collections return an empty page — `auth.py:74-76, 99-101`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 chars from A–Z and 0–9 — `envelope.py:12-13`
- §2.2 — insert — ambiguity — `api_request_timestamp` is real wall-clock UTC, the one stamp not drawn from the logical clock — `envelope.py:16-18`
- §2.3 — insert — ambiguity — `created_at` ties broken by write order, earliest write first — `store.py:195-196`
- §2.6 — insert — ambiguity — store is empty on every boot; nothing seeded — `store.py:38-42`
- §2.6 — revise — mismatch — `version` advances by at most 1 per request however many writes/cascades touch the row — `store.py:151-175`
- §2.6 — revise — mismatch — instant inputs accept `Z`/numeric offset/naive-as-UTC, optional seconds, 1–9 fractional digits truncated to 3; date fields accept bare `YYYY-MM-DD` or any instant, truncated down to midnight — `store.py:69-131`, `validators.py:82-87`
- §2.6 — revise — mismatch — startup clock default literal corrected to `2026-08-01T00:00:00.000Z` — `store.py:14`
- §2.8 — revise — mismatch — a `Location`'s `version` is never advanced by a cascade; `updated_at` alone moves — `store.py:178-185`
- §2.8 — insert — ambiguity — unrouted path or undeclared method → `ERR_RECORD_NOT_FOUND` 404 (never 405), before/without the header check; trailing slash ignored — `app.py:25, 50-53`
- §2.10 rung 3 — insert — ambiguity + mismatch — integers must be JSON integers (floats/numeric strings/booleans refused); every integer field non-negative incl. `expected_*_version` (negative → 400, never 412); supplied strings non-empty even when optional; explicit `null` == omitted; absent/whitespace body == `{}`; `Content-Type` uninspected; unknown-query-key rule applies only at list endpoints — `validators.py:17-29, 42-59, 94-117, 144-153`
- §2.11 — insert — ambiguity — filter values structurally validated: bad enum domain or non-`true/false/1/0` boolean → `ERR_INVALID_REQUEST` 400 rather than matching nothing — `validators.py:185-203`
Verified no change needed: §5 error table is an exact match for `errors.ERROR_STATUS` (62 ids, all statuses identical); `serial.py` field lists match the PRD payloads for all 13 entities; envelope/pagination shapes match §2.2–§2.3.
Noted, not acted on: `auth.scope_disputes` and `store.force_version_bump` are dead code; Flask 3.1.3 ignores the `JSON_SORT_KEYS` config in `app.py:26` so key order is alphabetical — left unpinned rather than committing the PRD to an environment-dependent order.

### Pass 2 (calc.py / cascades.py / routes_config.py) — 17 ambiguity-pins, 2 mismatch-revisions
120,427 → 124,628 chars (+4,201). 19 edits on 18 lines.
- §2.5 — insert — ambiguity — degenerate split: no recipients or weights summing to zero ⇒ every share 0 — `calc.py:45-47`
- §3.1 — insert — ambiguity — the 725 floor on `state_min_wage_cents` is a rung-3 `ERR_INVALID_REQUEST` — `routes_config.py:43`
- §3.1 — insert — ambiguity — `cc_fee_cap_bps` > 1000 is a 400 one rung earlier; exactly 0 reaches `ERR_CC_FEE_CAP_REQUIRED` — `routes_config.py:47,70-75`
- §3.1 — revise — mismatch — `ERR_CASH_WAGE_BELOW_FLOOR` also guards the `tip_credit_enabled` false branch — `routes_config.py:62-67`
- §2.10 rung 28 — revise — mismatch — reworded to cover both branches of the cash-wage bound — `routes_config.py:62-67`
- §3.1 — insert — ambiguity — job-role `code` charset/length violation is `ERR_INVALID_REQUEST` before the uniqueness check — `routes_config.py:119,133-136`
- §3.1 — insert — ambiguity — non-zero attributes on a management role, and out-of-range values, are 400s not 422s, and precede rung 49 — `routes_config.py:123-124,138-143`
- §3.2 — insert — ambiguity — a reversed assignment interval is a rung-3 400 ahead of the overlap and separation guards — `routes_config.py:249-250`
- §3.2 — revise — ambiguity — the dual-job overlap test uses the same null-`effective_to`-as-unbounded reading as the overlap guard — `routes_config.py:294-309`
- §3.3 — insert — ambiguity — the server-initiated supersession reversal does not evaluate §3.7's fiscal precondition — `routes_config.py:419-425`
- §3.5 — revise — ambiguity — a missing authorising assignment gates exactly like a null notice — `calc.py:74-76`
- §3.7 — insert — ambiguity — `participant_count`, `total_share_weight`, `distributed_at` survive a reversal untouched — `cascades.py:170-206`
- §3.7 — insert — ambiguity — the `REVERSAL` row copies pool id, employee, shift, `share_weight`, `remainder_cent_awarded`, `business_date` — `cascades.py:186-197`
- §3.8 — insert — ambiguity — server-initiated reopening recomputes the two shift rollups and, unlike client reopen, leaves `ALLOCATED` service charges allocated — `cascades.py:146-158`
- §3.8 Step 4 — insert — ambiguity — single exact quotient `(straight+scw)×60 ÷ total_minutes`; rate 0 (not an error) when `total_minutes` is 0 — `calc.py:129-134`
- §3.8 Step 5 — insert — ambiguity — one quotient ÷120 rounded once; the rate is never halved to a whole cent first — `calc.py:136-138`
- §3.8 Step 6 — insert — ambiguity — overtime band is `3×amw×ot ÷ 120` rounded once; the 1.5× rate is never pre-rounded — `calc.py:150`
- §3.8 Step 7 — insert — ambiguity — only allocation rows naming one of the employee's `CLOSED` period shifts feed `pool_tips_cents` — `calc.py:141`, `cascades.py:44-53`
- §3.8 — insert — ambiguity — `PER_SHIFT` re-derives each shift's regular/overtime split against the same 2,400-minute threshold and rebuilds its straight cash, obligation and ceiling from its own minutes; `tipped_employee_qualified` stays period-level; only `tip_credit_cents`, `topup_cents`, `total_gross_cents` are written back — `calc.py:177-217`, `routes_periods.py:414-425`

### Pass 3 (routes_shifts.py / routes_pools.py) — 12 ambiguity-pins, 3 mismatch-revisions
124,628 → 128,727 chars (+4,099). 15 edits.
- §2.10 rung 12 — insert — ambiguity — the pool-reverse fiscal guard also answers `ERR_PAY_PERIOD_NOT_OPEN` but sits below rung 17 — `routes_pools.py:358-361`
- §2.10 rung 16 — revise — mismatch — `ERR_POOL_ALREADY_DISTRIBUTED`'s operation list omitted `POST /service-charges/{id}/void` — `routes_shifts.py:383-385`
- §3.4 — revise — mismatch — "four optional money and rate inputs" corrected to "three" — `routes_shifts.py:58-60`
- §3.4 — insert — ambiguity — `scheduled_minutes` floors any fractional minute (sub-minute interval ⇒ 0) — `routes_shifts.py:72`
- §3.4 — insert — ambiguity — shift void has no timekeeping guard: re-voiding an already-`VOIDED` shift succeeds, re-zeroes, bumps `version`, never reopens the period — `routes_shifts.py:274-301`
- §3.5 — insert — ambiguity — both declare-tips amounts are required with no default; an amendment must restate both — `routes_shifts.py:234-237`
- §3.6 — insert — ambiguity — `treatment_override` and `description` are retained, null when omitted; resolved `treatment` is never rewritten later — `routes_shifts.py:337-340`
- §3.6 — revise — ambiguity — named `ERR_POOL_ALREADY_DISTRIBUTED` as the code for voiding a charge absorbed into a distributed pool — `routes_shifts.py:383-385`
- §3.6 — insert — ambiguity — re-voiding an already-`VOIDED` charge is accepted, bumps `version`, runs no unwinding — `routes_shifts.py:387-393`
- §3.7 — insert — ambiguity — a `business_date` covered by no period at that unit also yields `ERR_PAY_PERIOD_NOT_OPEN` — `routes_pools.py:86-88`
- §3.7 — insert — ambiguity — manager-participation candidate set pinned (CLOSED + unpooled shifts of that date, pre-policy, ignoring declaration/rate/points/tip status), one check for both directions, firing only on a non-empty all-management set — `routes_pools.py:92-98`
- §3.7 — revise — ambiguity — creation sets `net_pool_cents` = contributed + service-charge tips and absorbs only `RECORDED` charges — `routes_pools.py:60-68,140-160`
- §3.7 — insert — ambiguity — leftover-cent tie-break beyond equal weight and equal `created_at` falls to write order — `routes_pools.py:289`, `calc.py:54`
- §3.7 — revise — mismatch — `distributed_cents == net_pool_cents` "exactly" is false in the zero-total-weight degenerate case; added the recipient `trailing_pool_receipts_cents` recompute and that distribution leaves `total_contributed_cents`, `service_charge_tips_cents` and the period rollups alone — `routes_pools.py:294-326`, `calc.py:45-47`
- §3.7 — insert — ambiguity — the rung-53 `participant_count` is the live participant set, the stored field still 0 pre-distribution — `routes_pools.py:277-279`
- §3.7 — revise — ambiguity — reversal guard order pinned: `contribution_status` first (`distribution_status` never examined), then the fiscal guard returning `ERR_PAY_PERIOD_NOT_OPEN` (409) — `routes_pools.py:358-363`
Pass 3 reverted nothing from passes 1–2 and deferred the "scoping before `total_count`" question to pass 4.

### Pass 4 (routes_periods.py / routes_disputes.py + final consistency read) — 10 ambiguity-pins, 7 mismatch-revisions
128,727 → 132,684 chars (+3,957). 17 edits across 16 lines.
Deferred question resolved: read-scoping IS applied before `total_count` — every scoped list narrows the filtered rows and only then calls `paged()` (`routes_periods.py:179-180`, `routes_disputes.py:151,375`, `serial.py:220-225`). Pinned in both §2.3 and §2.11.
- §2.3 — insert — ambiguity — role read-scope applied to filtered rows before `total_count`/`has_more` — `serial.py:220` via `routes_periods.py:179`
- §2.11 — insert — ambiguity — which field each scoped list reads (pay lines/allocations via `employee_id`, shifts via `employee_id`/`location_id`, disputes via `raised_by_employee_id`, corrections via their pay line's employee), scoping before window and count, and that the other eight collections are unscoped for every role — `auth.py:94-119`, `routes_disputes.py:47-64,151,375`
- §2.7 — revise — mismatch — a `DENIED` adjudication does not bump the pay line's `version` — `routes_disputes.py:234`
- §2.8 — revise — mismatch — "never adjusted by a delta" now excepts the `total_topup_cents` increment when a `TIP_CREDIT_INVALID` correction is applied — `routes_disputes.py:416-418`
- §2.10 rung 22 — revise — mismatch — `POST /disputes/{dispute_id}/adjudicate` also raises `ERR_PAY_LINE_NOT_FINAL` — `routes_disputes.py:209-210`
- §3.4 — revise — mismatch — `total_topup_cents` additionally carries applied `TIP_CREDIT_INVALID` correction amounts — `routes_disputes.py:417`
- §3.6 — insert — ambiguity — full WAGES-split tie-break chain (weight desc, employee `created_at`, employee write order, shift `created_at`, shift write order) and the zero-total-weight case, where nothing reaches a pay line yet the event still goes `ALLOCATED` with `allocated_pay_period_id` stamped — `routes_periods.py:209-239`
- §3.8 — insert — ambiguity — new pay lines written in ascending employee `created_at` order; only those five rollups recomputed (`total_correction_cents` carried across); a period with no `CLOSED` shift computes successfully with no pay lines — `routes_periods.py:312-339`
- §3.8 — revise — mismatch — the segregation-of-duties comparison runs BEFORE the `COMPUTED` status check (PRD had them reversed, contradicting its own rungs 7/13); plus why an `OPEN` period still answers `ERR_PAY_PERIOD_NOT_COMPUTED` — `routes_periods.py:406-409`
- §3.8 — insert — ambiguity — reporting-test leftover-cent tie-break extends to employee write order; with no directly-tipped line or zero total sales the shortfall is still recorded while every `allocated_tips_cents` stays 0 — `routes_periods.py:372-391`
- §3.8 — insert — ambiguity — client reopen leaves `total_correction_cents` and each shift's `shift_tip_credit_cents` untouched — `routes_periods.py:458-467`
- §3.8 — revise — mismatch — "Two further figures … without the line's `version` moving" → "One", since `pending_correction_cents`/`correction_applied_cents` changes do bump it — `routes_disputes.py:182-184,345-346`
- §3.8 — insert — ambiguity — an `open_dispute_count` change still refreshes the line's `updated_at` — `store.py:178`, `routes_disputes.py:126,268`
- §3.9 — insert — ambiguity — `claimed_amount_cents` of 0 is refused on rung 3 with `ERR_INVALID_REQUEST`; omitted `narrative` reads back null — `routes_disputes.py:84-85`
- §3.9 — insert — ambiguity — `reason_code` is carried onto the created correction and, when omitted, defaults from the dispute's `category` (four-way mapping); on `DENIED` it is accepted and unused — `routes_disputes.py:235-237`
- §3.9 — insert — ambiguity — a supplied `dispute_id` need not name the same pay line; only its `adjudicated_amount_cents` is read — `routes_disputes.py:294-323`
- §3.9 — revise — mismatch — an `APPLIED` correction cannot be undone by an "opposite-signed correction"; `amount_cents` must be strictly positive so no such row can exist — `routes_disputes.py:320-321`

**Final-pass consistency verdict:** (a) not truncated — ends at `| ERR_CORRECTION_EXCEEDS_OBLIGATION | 422 |`; (b) both §2.2 fenced JSON blocks byte-identical to `PRD_FINALIZED.md`; (c) three internal contradictions found and fixed minimally (approve guard order vs rung 7; §2.7's blanket adjudication version bump vs the `DENIED` arm; "never adjusted by a delta" vs the `TIP_CREDIT_INVALID` top-up), nothing from passes 1–3 reverted; (d) §4 lists all 51 endpoints, §5 all 62 distinct error ids.

### Step 9 totals
48 ambiguity-pins + 17 mismatch-revisions = 65 edits. `PRD_COMPLETED.md` is 528 lines / 132,684 chars vs `PRD_FINALIZED.md` 528 lines / 115,712 chars (+16,972 chars, +14.7%); md5 `25ca3dbf…` vs `06a3b08d…` — **not identical**, so the scan demonstrably ran. `git diff --stat` reports 60 lines rewritten in place, 0 lines added or removed, no new sections.

**Pipeline complete.** No implementation or test file was touched after Step 7, so the verified 8-round green sweep (`workspace/implementation/results.{1..8}.json`, 113/113 each) remains the final test state.

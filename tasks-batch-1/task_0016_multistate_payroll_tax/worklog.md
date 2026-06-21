# Worklog — task_0016_multistate_payroll_tax

## Step 1: Create task directory — 2026-05-27T00:00:00Z

Created `tasks/task_0016_multistate_payroll_tax/workspace/` (pre-allocated path, no index scan).

## Step 2: Generate scaffold — 2026-05-27T07:38:00Z

Generated three artifacts at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0016_multistate_payroll_tax/`:

**SCAFFOLD.yaml** (§1.0–§1.7):
- 8 entities (Employee, W4Form, PaycheckRun, Paycheck, GarnishmentOrder, GarnishmentDeduction, Remittance, TaxRateTable)
- 5 state machines (W4Form cyclic via supersession, PaycheckRun branching-with-revert, Paycheck system-driven, GarnishmentOrder cyclic ACTIVE↔SUSPENDED, Remittance linear)
- 8 calculations (gross_wages_calc, federal_withholding_provisional w/ provisional+reconciled variants, fica_ss_calc threshold, medicare_base_calc, medicare_addl_calc threshold, state_local_withholding tiered, garnishment_waterfall, remittance_accrual w/ provisional+reconciled variants)
- 16 validation rules (priority-ordered: auth → existence → state → business_safety → business_referential → business_temporal → business_fiscal → business_constraint)
- 36 API endpoints (including 2 test-driving endpoints: `/_clock/set_current_utc`, `/_employees/{id}/set_ytd`)
- 16 error codes
- 5 roles (HRClerk, PayrollPreparer, PayrollApprover, ComplianceOfficer, PlatformAdmin) under segregation-of-duties model
- 1 concurrency_rule (OCC on Remittance.version for `POST /remittances/{id}/remit`)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8):
- 9 rules × 2 instances each = 18 total instances
- Each instance has full `setup_api_calls`, `trigger`, and `assert` blocks with literal pre-computed values (e.g., 16357c provisional fed withholding, 0c reconciled, 80000c garnishment_total, 86343c net_pay)

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9):
- 9 sections, 37 total instances (32 full + 5 `excluded_because` stubs)
- Sections: entities (9), state_machines (6), calculations (7), validations (4), endpoints (2), errors (3), rbac (3), cross_cutting (2), consistency (1)

**scaffold_lint.py verdict**: `clean lint` — all 406 calls conform to §1.5, all 7 FKs have reverse-reachability GETs.

**Counts**: entities=8, state_machines=5, calculations=8, validations=16, endpoints=36, errors=16, roles=5; difficulty_design instances=18, corner_design instances=37.

## Step 3: Copy INSTRUCTION.md — 2026-05-27T07:39:00Z

Copied `./INSTRUCTION.md` → `tasks/task_0016_multistate_payroll_tax/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-05-27T07:45:00Z

Output: `workspace/PRD.md` — 253 lines.

**Structure**
- 5 top-level sections, 10 §2 subsections (2.1–2.10), 8 §3 subsections (3.1–3.8)
- §3 grouping: hybrid lifecycle / business-process (onboarding → reference data → run composition → withholding pipeline → garnishments → approval-pay-void → close-and-remit → audit listings)

**Hard contract reports**
- Field coverage (Contract 1): 68/68 entity fields + 46/46 endpoint bodies present, all 65 deduplicated required field tokens in backticks — PASS.
- Rule coverage (Contract 2): all 16 error IDs, all states/enums, all 8 named constants embedded, validation priorities 1–16 expressed explicitly (incl. `ERR_OPEN_RUN_BLOCKS_CLOSE`-below-state nuance), OCC `expected_remittance_version` + `ERR_STALE_VERSION` HTTP 412 covered, all 7 calcs in precise prose with floor-division ordering and tie-breaks (priority_rank ASC, served_on ASC, created_at ASC; never id), per-order-then-sum rounding pinned — PASS.
- Path purity (Contract 3): 0 paths, 0 HTTP methods, 0 method+path tokens in §3 backticks (545 scanned) — PASS.

**Notable observations**
- Year-end reconciliation gated solely by explicit `is_year_end_run` flag (no implicit detection).
- Additional Medicare boundary ($200,000 exact vs $200,000.01) stated explicitly.
- Two CCPA intake checks (single-order vs aggregate) carry distinct error IDs and intervals.
- §4 endpoint table (Method/Path/Description/Roles); §5 error table (Error ID / HTTP Status).

## Step 5: Generate unit tests — 2026-05-27T08:05:00Z

Output: `test_helpers/` (9 files, ~1,434 LOC) + `test_suite/` (12 files, ~2,448 LOC).

**Coverage (Design-index-only contract)**
- Queue A (Difficulty): 18/18 instances → 36 tests tagged `Design: Difficulty/...` (2 tests per instance).
- Queue B (Corner): 32/32 non-stub instances → 32 tests tagged `Design: Corner/...`.
- Total tagged tests: 68. All 68 `Design:` tags resolve to real `name:` entries; 0 stray, 0 dual-tagged.

**Skipped instances** (5 `excluded_because` stubs — not translated by design):
- `entities/employee_required_field_missing`
- `entities/employee_invalid_enum`
- `errors/stale_version_excluded_stub`
- `rbac/unauthenticated_role_missing`
- `cross_cutting_complexity_layers/cascade_remittance_accrual_excluded`

**PRD-first filter applications**
- `combinatorial_formula/federal_overtime_supplemental_branch_mode_a`: emitted federal-branch assertions (gross=150000, fed_withheld=33500, status=PENDING) but dropped the YAML's `state_withheld_cents == 1650` — flagged as a 10× pre-computation slip in scaffold yaml (correct math at CA supp=1100bp on 150000c gross is 16500). Two PRD-only readers would not converge on 1650.

**Helper files**: types, api_client, api_errors, assertions, factories, constants, test_users, fixtures, __init__.

**Test files**: conftest, 01_calculations, 02_garnishment_waterfall, 03_paycheck_run_lifecycle, 04_w4_lifecycle, 05_garnishment_lifecycle, 06_remittance_close_remit, 07_validation_errors, 08_entity_crud, 09_rbac, 10_consistency, 11_difficulty_supplemental.

## Step 6: Generate implementation — 2026-05-27T08:15:00Z

Output: `workspace/implementation/` — 15 files, ~1,500 LOC.

**Layout**
- `start.sh` (`python3 -m pip install -q -r requirements.txt && exec python3 app.py`), `requirements.txt` (Flask==3.0.3).
- `app.py` (factory + before_request auth + error handlers), `db.py` (in-memory dicts + clock/UUID/iso8601), `errors.py` (APIError + 16 error_id constants), `response.py` (PRD §2.2 envelope: meta/response_type/data; `req_` ids; ms-truncated UTC), `middleware.py` (X-User-ID/Role + `require_roles`).
- `services/`: calculations, lookups (FILED W-4 selection — max filed_at, tie-break created_at ASC), paycheck_pipeline (pinned order: gross → fed → state → local → SS → medicare → addl_medicare → garnishment waterfall → net; CCPA-cap waterfall with `(priority_rank, served_on, created_at)` tie-break), serialize (omits `updated_at`/`version` on GarnishmentDeduction & TaxRateTable per PRD §2.4), pagination (default 10, min 1, max 100; sort created_at ASC; total_count + has_more), validation.
- `routes/`: employees (+ `/_clock/set_current_utc` + `/_employees/{id}/set_ytd`), w4_forms (DRAFT→FILED→SUPERSEDED + cascade recompute of PENDING paychecks in DRAFT runs whose pay_date year matches W-4 tax_year), paycheck_runs (approve/reject/pay/void cascade; `is_year_end_run` triggers reconciled fed variant; YTD increments rolled forward in `created_at` ASC for siblings within a run), paychecks (full pipeline + sub-resource listing + priority-11 pay-period overlap closed-closed point-overlap), garnishments (CRUD + suspend/reactivate/release + priority-8 single-order + priority-12 aggregate CCPA), remittances (close-period reconciled re-scan; remit with priority-13 exact-amount + priority-15 OCC `expected_remittance_version`), tax_rate_tables (PlatformAdmin insert/replace, role-shared read).

**Notable design decisions**
- All money as integer cents with floor division (`//`).
- Garnishment waterfall: pinned eval order (disposable → cap → per-order min); pinned tie-break `(priority_rank ASC, served_on ASC, created_at ASC)` — never `id`; CCPA basis 50% if any ACTIVE CHILD_SUPPORT else 25%.
- Validation priority enforced in route guards (auth → FK → state → employee-not-active → SoD → business-temporal → OCC → shape); `ERR_OPEN_RUN_BLOCKS_CLOSE` sits below state guard per PRD §2.6.
- SS YTD increment under wage-base cap: paycheck carries internal `_ss_taxable_applied` capturing `min(gross, capacity)` at create time so PAID/VOID cycles converge exactly.
- W-4 file cascade recomputes full pipeline (not just fed) for PENDING paychecks in matching DRAFT runs and rebuilds child `GarnishmentDeduction` rows.

**Smoke verified**: full create-employee → seed-tax-table → file-W-4 → create-run → add-paycheck (REGULAR 80h@$25) → approve (SoD-distinct operator) → pay returns gross 200000, fed 16361, SS 12400, Medicare 2900, net 168339; YTD advances; three ACCRUING remittance rows created.

## Step 7: Test/fix iteration loop — 2026-05-27T08:55:00Z

Final stability: **8/8 rounds × 68/68 tests passing**.

- Iterations run: 2 (initial baseline + post-fix sweep). A third sweep was run after a single-round transient `BadStatusLine` (server-boot flake during concurrent heavy load); all 8 rounds clean.
- Tests deleted: **none**.
- Fixes applied to `test_helpers/`:
  - `test_helpers/constants.py` — renamed the bracket-dict key from `upper_cents` to `upper_cents_or_null` for FED_BRACKETS_2025_SINGLE, CA_BRACKETS_2025_SINGLE, NY_BRACKETS_2025_SINGLE, NYC_BRACKETS_2025_SINGLE. PRD §3.2 verbatim declares the field name as `upper_cents_or_null`; the helper was sending tax tables in a non-PRD shape, so the implementation's bracket walker treated every upper as None and over-charged tax at the lowest bracket. Root cause for 7 of 9 baseline failures (all the 16357 vs 26223 federal-withholding cases), and indirectly for the remaining 2 (OCC remit tests sent `paid_cents=16357` to match `reconciled_cents`).
- Fixes applied to `implementation/`: **none**. The implementation correctly reads `upper_cents_or_null` as the PRD specifies.

## Step 8: Finalize PRD — 2026-05-27T08:44:00Z

Output: `workspace/PRD_FINALIZED.md` (53234 bytes / 252 lines).

**Diff vs PRD.md**: 0% line-count delta (within-line edits); +4236 chars / +8.6%.

**Changes**
- §3.1 — revise — pinned that on-file recompute spans entire withholding pipeline (not just fed), is scoped to paychecks whose parent run's `pay_date`-year equals the W-4's `tax_year`, deletes/recreates child `GarnishmentDeduction` rows, bumps `Paycheck`+`PaycheckRun` versions — `routes/w4_forms.py:122-164`.
- §3.2 — insert — pinned `POST /tax-rate-tables` insert-or-replace semantics on `(jurisdiction, tax_year, filing_status)`: replaced rows preserve `id`/`created_at`, overwrite `brackets_json`/`supplemental_flat_basis_points`, HTTP 201 in both insert and replace — `routes/tax_rate_tables.py:37-64`.
- §3.4 — revise — pinned (a) `dependents_amount_cents` subtracted as yearly amount (not /26), (b) bracket-based path applies to OVERTIME/DOUBLE/RETRO too, (c) absent W-4 yields zero, (d) siblings iterate `created_at` ASC with cumulative YTD, (e) `net_pay_cents` recomputed but garnishment waterfall not re-run — `services/calculations.py:117-142`, `routes/paycheck_runs.py:198-235`.
- §3.5 — revise — pinned (a) both intake checks skipped when employee has no prior PAID paycheck, (b) single-order CCPA check fires only for `CHILD_SUPPORT`, (c) aggregate-capacity formula uses 50% basis when new order is CHILD_SUPPORT or any active order is CHILD_SUPPORT, else 25% — `routes/garnishments.py:54-83`.
- §3.6 — revise — pinned (a) children iterate `created_at` ASC for both year-end recompute and YTD/accrual passes, (b) four-bucket Remittance mapping (FICA_EMPLOYEE = ss + medicare base + addl medicare; LOCAL_INCOME only when `locality_code != NONE`) — `services/lookups.py:86-105`, `routes/paycheck_runs.py:192,238-240,320-348`.
- §3.8 — insert — pinned that `set_ytd` rejects negative values with `ERR_INVALID_REQUEST` (HTTP 400), and that a request with no YTD fields (or every named field null) returns employee unchanged without bumping `version`/`updated_at` — `routes/employees.py:106-117`.

All other PRD behaviors preserved verbatim. No new sections added.

# Worklog — task_1130_nonprofit_grant_reporting_funders

## Step 1: Create task directory — 2026-08-10T21:46:00.000Z

Pre-assigned output folder `tasks/task_1130_nonprofit_grant_reporting_funders` with `workspace/` subdirectory already exists. Step 1 auto-index scan skipped per instructions; treated as done.

## Step 2: Generate scaffold — 2026-08-10T22:34:00.000Z

All artifacts are generated and verified. Final report:

## Summary

**Task**: `task_1130_nonprofit_grant_reporting_funders` — scaffold generated purely from the scenario text plus the skill spec (no sibling tasks consulted). Difficulty: beyond Expert band — compliance/audit primary archetype with ledger-reconciliation secondary, segregation-of-duties role model, cyclic state machines, 9 machines / 5 calculations with dense cross-entity coupling.

**Files on disk** (`ls -la` verified):
- `/home/ubuntu/github/CodingPRD/tasks/task_1130_nonprofit_grant_reporting_funders/SCAFFOLD.yaml` — 68,912 bytes (§1.0–§1.7; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1130_nonprofit_grant_reporting_funders/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 60,758 bytes (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1130_nonprofit_grant_reporting_funders/SCAFFOLD_CORNER_DESIGN.yaml` — 88,191 bytes (single key `scaffold_corner_design`)

**Counts**:
- Entities: 13 (Funder, Grant, BudgetLine, Fund, Expense, ExpenseAllocation, Report, VarianceExplanation, MatchContribution, ModificationRequest, AuditEngagement, AuditFinding, RenewalApplication)
- State machines: 9 (cyclic: Grant ACTIVE↔SUSPENDED, Report revision loop, AuditFinding reopen loop)
- Calculations: 5 (incl. dual-variant budget variance period_only/cumulative, dual-variant match progress, mode-(a) indirect pool with cap branch, mode-(b) proration with pinned rounding order, dual-variant burn rate)
- Endpoints: 57 (incl. `POST /_clock/set_current_utc` with pinned default `2026-05-01T00:00:00Z`)
- Errors: 29; validations: 29 ordered rows; roles: 6 (Funder entity-backed, others opaque); concurrency rules: 1 OCC on Grant.version
- **Difficulty instances (§1.8): 18** — exactly 2 per each of the 9 rules, all with structured replayed setup chains and pre-computed literal asserts (e.g. variance +12.00% period vs +4.00% cumulative; proration `[2500000, 2500000, 2500000, 2500003]`; match 5000000 vs 15630000; renewal window inclusive at `2027-04-01T00:00:00Z`)
- **Corner instances (§1.9): 42** (37 active + 5 `excluded_because` stubs) across all 9 taxonomy sections; all 66 instance names unique across both files

**Lint verdict (verbatim)**:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(619 calls scanned; one FK-reverse-reachability gap for `VarianceExplanation.budget_line_id` was found and fixed by adding `GET /budget-lines/{id}` + `GET /budget-lines/{id}/variance-explanations`.)

Note: the task directory also contains a pre-existing `worklog.md` and `workspace/` (not created or modified by me).

## Step 3: Copy INSTRUCTION.md — 2026-08-10T22:35:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1130_nonprofit_grant_reporting_funders/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-10T22:45:00.000Z

PRD generation complete. Summary:

**Output file**: `/home/ubuntu/github/CodingPRD/tasks/task_1130_nonprofit_grant_reporting_funders/workspace/PRD.md`
- **File size**: 55,350 bytes (55 KB)
- **Line count**: 323 lines
- **Section count**: 25 headings total
  - 5 top-level sections (§1 Introduction, §2 Global Specifications, §3 Business Logic, §4 Endpoint Definitions, §5 Error Code Catalogue)
  - 11 subsections under §2 (2.1 through 2.11, including the verbatim §2.2)
  - 9 subsections under §3 (3.1 through 3.9)

**Zero-Silence Rule self-audit verdicts**:

```
Contract 1 — Field-Name Coverage:
- entities[].fields: 81 required, 81 present, 0 missing
- endpoints[].request_body: 58 required, 58 present, 0 missing
- endpoints[].query_params: 7 required, 7 present, 0 missing
- path_params: 1 required, 1 present, 0 missing
- combined set: 102 required, 102 present, 0 missing
Status: PASS

Contract 2 — Rule Coverage:
- validations[] with priority: 10 priority tiers expressed in §2.10 as ordered numbered list, 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (write_endpoint + expected_grant_version + ERR_STALE_VERSION/HTTP 412 all named), 0 missing
- state_machines[].transitions: 33 transitions across 9 state machines checked, 33 fully expressed, 0 missing
- calculations[]: 5 checked (period_budget_proration, budget_variance_report, indirect_cost_pool, match_commitment_progress, burn_rate_projection), 5 fully expressed in precise prose with constants embedded, 0 missing
- validations[] conditions: all 29 error_ids in scaffold appear in PRD prose, each pairable to its trigger via §2.10 + §3 narrative, 0 missing
- endpoints[].side_effects / applies_to: all cascade side effects (activation calendar gen, void cascade, approve extension/reallocation, MATERIAL_WEAKNESS suspend/unfreeze) expressed, 0 missing
- entities[].fields[] structured content: defaults, enums, and source (input/system/computed) reconstructible from prose for all 81 fields, 0 missing
- sibling-branch symmetry: 8 symmetric groups checked (approve/deny, resolve/reopen, verified/pledged match variants, period/cumulative BvA variants, trailing/cumulative burn variants, RENEWED/DECLINED, NOT_OPEN/LAPSED renewal rejections, INTERIM/FINAL period types), all rendered with equal density
Status: PASS

Contract 3 — §3 Path Purity:
- backtick tokens scanned in §3: 535
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**All three Hard Contracts PASS.** The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened, greped, or referenced in any way.

## Step 5: Generate unit tests — 2026-08-10T23:10:00.000Z

Generation complete and verified. Summary:

**Helper files created** (`/home/ubuntu/github/CodingPRD/tasks/task_1130_nonprofit_grant_reporting_funders/test_helpers/`, 9 files):
- `types.py` — 20 status/type enums, 14 entity TypedDicts (all entities carry common fields per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with 47 endpoint methods covering every PRD §4 row, plus the `/_clock/set_current_utc` test-driving endpoint
- `api_errors.py` — `ApiErrorId` (29 errors) + HTTP status map, registered with `set_error_http_status_map`
- `assertions.py` — per-entity assertions + error-envelope shape checker
- `factories.py`, `constants.py` (clock default, 3150 volunteer rate, de minimis 10, auditor capacity 2, due-day defaults)
- `test_users.py` — shared role headers + `make_funder_headers(funder_id)` builder (Funder is entity-backed; all funder-scoped calls thread the real Funder.id)
- `fixtures.py` — composite setup: draft/active grant hierarchies, posted+allocated expenses, report lifecycle walks to ACCEPTED, engagement-to-CONDUCTED, MW suspension, finding resolution, modification submission, renewal creation
- `__init__.py` — barrel export

**Test files created** (`test_suite/`, 13 files + `conftest.py`): test_01 grant structure; test_02 reporting calendar + pagination; test_03 report workflow/revision loop; test_04 variance gating/boundary; test_05 summary calculations (indirect pool, proration, match variants, burn rate); test_06 expenses/allocations/void/fiscal caps; test_07 suspension + freeze cascades; test_08 modifications (NCE calendar regen, reallocation conservation, OCC); test_09 audit engagements (overlap, capacity, finding lifecycle, closeout); test_10 renewal window boundary/lapse; test_11 validation priority pairs; test_12 auth/RBAC/SoD/envelope/uniqueness; test_13 reconciliation + FINAL match gate.

**Total test count: 78** — every test has exactly one `Design:` tag resolving to a real instance.

**Queue A coverage: 18/18** difficulty instances, each with ≥2 tests.

**Queue B coverage: 38/38** non-stub corner instances, each with ≥1 test. The 6 `excluded_because:` stubs were not translated; all 6 cross-references (`variance_period_only_vs_cumulative_gate`, `match_progress_verified_vs_pledged`, `period_proration_remainder_to_final`, `material_weakness_freeze_chain`, `nce_approval_calendar_extension`, `allocation_gated_on_expense_posted`) resolve to real difficulty instances.

**Skipped instances: none.** Every non-stub instance passed the PRD-first two-condition filter — PRD.md verbatim-covers all asserted rules, including the two priority pairs (§2.10 names both category orderings explicitly, plus "a fiscal cap never masks a restriction violation").

**Verification:** all 22 .py files pass `python -m py_compile`; all test modules import cleanly under `PYTHONPATH=.`; all 112 quoted PRD citations in docstrings survive a literal (whitespace/backtick-normalized) grep of PRD.md; no `pytest.mark.skip`/`skipif`/`xfail` anywhere.

## Step 6: Generate implementation — 2026-08-10T23:12:00.000Z

Implementation complete and verified. Summary below.

## Summary

**Output directory:** `/home/ubuntu/github/CodingPRD/tasks/task_1130_nonprofit_grant_reporting_funders/workspace/implementation/`

### Route parity (verification 3)
- SCAFFOLD.yaml declares **57** (method, path) endpoint pairs; the Flask `url_map` registers exactly **57**; programmatic diff: **0 missing, 0 extra — MATCH**.

### File list with sizes (verification 1)
| File | Bytes |
|---|---|
| `start.sh` (executable, mode 755) | 395 |
| `requirements.txt` (flask>=2.2) | 11 |
| `app.py` — app factory, envelope-ized 404/405/500 handlers, route registration | 1324 |
| `db.py` — in-memory store (13 dicts), logical clock pinned at 2026-05-01T00:00:00Z | 1021 |
| `errors.py` — all 29 scaffold error IDs with exact HTTP statuses | 4133 |
| `middleware.py` — X-User-ID/X-User-Role auth, 6 roles, funder-scope check | 1415 |
| `response.py` — meta/response_type/data envelope, limit/offset/total_count/has_more pagination | 1818 |
| `util.py` — ISO8601 parse/format (3-fractional-digit timestamps), Decimal half-up math, payload validators | 4901 |
| `services.py` — serializers, calendar tiling, waterfall proration, totals reconciliation, suspend/reactivate cascades, NCE calendar regen | 17848 |
| `services_summary.py` — BvA (period+cumulative), indirect pool (de minimis/cap/floor), match variants, burn projections, pacing, variance-breach gating | 5773 |
| `routes/{funders,grants,expenses,reports,match,modifications,audit,renewals,clock}.py` + `__init__.py` | 42381 total |

### Lint (verification 2)
`python -m py_compile` on all 18 `.py` files: **ALL PASS**.

### start.sh (verification 4)
Executable; `set -euo pipefail`; guarded dependency install (`if ! python3 -c "import flask"` — no-op once Flask present, safe for concurrent per-test reboots); `exec python3 app.py` in foreground; app binds `0.0.0.0:$PORT` (default 10000).

### Behavioral verification
Two live smoke sweeps against a fresh-booted server (140+ assertions) passed: auth/role/404 ordering, duplicate award number, activation calendar (quarterly periods, due dates, floor-proration residual-to-final `[250000,250000,250000,250003]` for 1000003/4), segregation of duties on expense post and match verify, restriction/overallocation/line/fund caps, void cascade with lock-by-submitted-report, report lifecycle with revision loop, variance gate (outcome→variance→match order per PRD prose), submitted_late computation, funder scoping (403), OCC `ERR_STALE_VERSION` with grant version +1 per approval, NCE calendar regen (FINAL demotion + appended periods), reallocation proration recompute, engagement overlap (half-open, adjacency allowed), auditor capacity (max 2 concurrent via sweep-line), MATERIAL_WEAKNESS suspend/freeze/lock and resolve/reactivate cascades, renewal window NOT_OPEN→ELIGIBLE→LAPSED on clock advance, closeout guards, and pagination bounds (limit 1–100, offset ≥ 0 → 400).

### Key design decisions
- **In-memory only**, zero seeding — fresh boot confirmed returning `total_count: 0` on `GET /grants`.
- **Logical clock everywhere** (PRD §2.11 "never consults the wall clock"): entity `created_at`/`updated_at`, `submitted_at`, meta timestamps, period-start and lateness checks all read the logical clock.
- **Validation priority** implemented per scaffold: auth 401 → role 403 → existence 404 → segregation 403 → state 409 → restriction 422 → constraints 409 → temporal 422 → referential 400/422 → fiscal 422; within submit gates, PRD prose order (outcome → variance → match) was followed over scaffold row order.
- All money is integer cents; percentages and pacing use `Decimal` with ROUND_HALF_UP to 2 dp; proration and indirect pool use floor.

Orchestrator route-parity re-verification: 57 declared vs 57 registered, 0 missing, 0 extra.

## Step 7: Run tests and iterate — 2026-08-10T23:25:00.000Z

All 8 rounds pass with 78/78. 

## Summary

- **Iterations run**: 2 (initial diagnostic sweep + 1 verification sweep after fixes)
- **Tests deleted**: None
- **Fixes applied to `test_helpers/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1130_nonprofit_grant_reporting_funders/test_helpers/fixtures.py` — `setup_active_grant`: (a) added optional `extra_funds` parameter so additional funds can be created BEFORE activation (PRD §3.1 forbids fund creation after DRAFT); (b) re-fetch budget lines after activation so `ctx["lines"]` carries the computed `period_budgets_cents` from PRD §3.2 (the snapshot returned by `add_budget_line` is stale post-activation).
- **Fixes applied to `test_suite/`**:
  - `test_06_expenses_allocations.py::TestFiscalCaps::test_fund_exceeded_trigger` — moved additional `tiny_fund` creation from post-activation `add_fund()` call into pre-activation `extra_funds` (PRD §3.1 fund-creation gate).
  - `test_06_expenses_allocations.py::TestExpenseVoid::test_expense_void_locked_by_submitted_report` — added a `create_variance_explanation` call before `submit_report` because posting 2,000,000 against a 25,000,000 period budget produces a −92% variance that trips the PRD §3.4 submit gate (ERR_VARIANCE_EXPLANATION_REQUIRED).
  - `test_11_validation_priority.py::TestRestrictionBeatsFundOverflow::test_restricted_fund_category_violation_beats_fiscal_cap` and `test_restricted_fund_violation_reported_even_with_ample_expense_room` — moved `RESTRICTED` fund creation from post-activation `add_fund()` into pre-activation `extra_funds` (PRD §3.1 fund-creation gate).
- **Fixes applied to `implementation/`**: None — implementation was PRD-faithful.
- **Final sweep evidence** (all 8 parallel rounds):
  - round 1: 78/78
  - round 2: 78/78
  - round 3: 78/78
  - round 4: 78/78
  - round 5: 78/78
  - round 6: 78/78
  - round 7: 78/78
  - round 8: 78/78

## Step 8: Finalize PRD — 2026-08-10T23:32:00.000Z

Both edits applied cleanly — a single-paragraph, in-place revision. Final summary below.

## Summary

**File produced**: `/home/ubuntu/github/CodingPRD/tasks/task_1130_nonprofit_grant_reporting_funders/workspace/PRD_FINALIZED.md`

**Line counts / delta**: PRD.md = 323 lines, PRD_FINALIZED.md = 323 lines; 0% line delta (one paragraph revised in place, no sections added or removed).

### Changes (one bullet per change)

- **§3.1** — revise — appended ", which is an empty array until activation populates it" to the `period_budgets_cents` sentence — impl: `implementation/routes/grants.py:150` (vector initialized `[]` at line creation), `routes/grants.py:103-106` (activation computes it). Traces to Step 7 fixture fix (b): re-fetch of `ctx["lines"]` post-activation because the `add_budget_line` snapshot is stale.
- **§3.1** — revise — appended "; an attempt to create either against a grant that has left `DRAFT` is rejected with `ERR_INVALID_STATE` (HTTP 409)" to the DRAFT-only creation sentence — impl: `routes/grants.py:141-142` (budget lines), `routes/grants.py:192-193` (funds), `errors.py:32-33` (`err_invalid_state` = 409). Traces to Step 7 fixture fix (a) and the three test fixes moving fund creation pre-activation (`test_06::test_fund_exceeded_trigger`, `test_11::test_restricted_fund_category_violation_beats_fiscal_cap`, `test_11::test_restricted_fund_violation_reported_even_with_ample_expense_room`).

### Step 7 items requiring no edit

- `test_06::test_expense_void_locked_by_submitted_report` (added variance explanation before submit): pure test bug. PRD §3.4 already fully pins the gate — absolute period-only variance ≥ `variance_threshold_pct` requires an explanation (inclusive comparator, zero-activity exemption), and §3.6 pins the period-only computation. Implementation (`routes/reports.py:98-106`, `services_summary.py:136-152`) matches the PRD verbatim; nothing to pin.

### Per-edit pre-edit search log

**Edit 1 (pre-activation `period_budgets_cents` = empty array)**
- (a) Subject: value of `period_budgets_cents` on a budget line before activation.
- (b) Impl paths enumerated and read: `routes/grants.py:150` (init `[]`); `routes/grants.py:103-106` (activation recompute of every line); `services.py:435-443` (`recompute_proration`, waterfall; `n<=0 → []`); `routes/modifications.py:133,141-143` (reallocation approval recomputes affected lines with n = report count); `services.py:491-499` (readers `period_budget`/`cumulative_budget`, 0/out-of-range safe); `services.py:221` (`ser_line` always serializes the field); `services_summary.py:56-82` (`bva_rows` iterates reports only, so the empty vector never surfaces pre-activation). Test-side: grepped `period_budgets_cents` across `test_suite/` — all assertions (test_05, test_08) are post-activation values already pinned by §3.2.
- (c) Wording adjustment: chose "empty array until activation populates it" — avoids claiming null/omitted (serializer always includes the field) and avoids claiming computation at creation; "populates" does not contradict the §3.2/§3.7 recomputes already pinned elsewhere.

**Edit 2 (post-DRAFT creation gate error code)**
- (a) Subject: error code/status for creating a budget line or fund on a non-DRAFT grant.
- (b) Impl paths enumerated and read: `routes/grants.py:137-154` (`create_budget_line`, gate at 141-142); `routes/grants.py:188-212` (`create_fund`, gate at 192-193); grep confirmed these are the only store-writers for lines/funds (modification approval mutates lines but creates none; activation only reads); `errors.py:32-33` (`ERR_INVALID_STATE` → 409); §2.10 tier 5 already lists `ERR_INVALID_STATE` generically (consistent); endpoint table rows "(grant must be DRAFT)" carry no error code (no conflict). Also verified both gates fire on `status != "DRAFT"` — i.e., they cover ACTIVE, SUSPENDED, CLOSEOUT, and CLOSED, and a SUSPENDED grant yields `ERR_INVALID_STATE` here (not `ERR_GRANT_SUSPENDED`).
- (c) Wording adjustment: used "against a grant that has left `DRAFT`" rather than "against an ACTIVE grant" or "after activation", so SUSPENDED/CLOSEOUT/CLOSED are covered exactly as the `!= "DRAFT"` check does; the sentence pins only the error identity, leaving its ordering relative to payload validation under-determined (both routes run the gate before body validation, but no Step 7 item exercises that ordering, so it is deliberately left open).

## Step 9: Complete PRD — 2026-08-10T23:45:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1130_nonprofit_grant_reporting_funders/workspace/PRD_COMPLETED.md`.

## Summary

**Source:** `PRD_FINALIZED.md` (323 lines / 55,367 chars) → `PRD_COMPLETED.md` (325 lines / 60,107 chars), char-delta **+4,740** (+2 lines; all other changes are in-paragraph edits — no new sections).

**Counts:** 21 ambiguity-pins, 1 mismatch-revision (22 edit sites total).

**Changes:**

- §2.2 — insert — ambiguity — `api_request_timestamp` pinned as read from the logical clock, never wall clock — implementation/response.py:10-14
- §2.3 — insert — ambiguity — invalid `limit`/`offset` (non-integer, out of [1,100], negative) → `ERR_VALIDATION` 400; `created_at` ties broken by creation (insertion) order — implementation/response.py:37-64, services.py:40-46,101-105
- §2.4 — insert — ambiguity — datetime inputs accept ISO date or datetime, date-only → midnight UTC, naive → UTC, unparseable → `ERR_VALIDATION` 400 — implementation/util.py:21-34
- §2.8 — insert — ambiguity — missing/non-integer `expected_grant_version` → `ERR_VALIDATION` 400 before the stale comparison — implementation/routes/modifications.py:119-126
- §2.11 — insert — ambiguity — clock endpoint accepts any instant; no monotonicity guard — implementation/routes/clock.py:10-17
- §3.1 — insert — ambiguity — grant-create numerics must be non-negative; `end_date < start_date` → `ERR_VALIDATION`; unknown `funder_id` → `ERR_VALIDATION` 400 (not 404) — implementation/routes/grants.py:31-57
- §3.1 — insert — ambiguity — `allowed_categories` optional (default `[]`), non-array/unknown entries → `ERR_VALIDATION`; `budgeted_cents`/`allocated_cents` non-negative — implementation/routes/grants.py:147,195-206
- §3.2 — insert — ambiguity — calendar tiling anchored at `start_date`, month-step arithmetic with day-clamping to target month length, final period clamped to `end_date` — implementation/services.py:377-397
- §3.3 — insert — ambiguity — nonexistent `budget_line_id`/`fund_id` body references on allocation → `ERR_VALIDATION` 400, never 404 — implementation/routes/expenses.py:123-126
- §3.4 — insert — ambiguity — report edit is partial (only supplied fields change); `outcome_entries` replaces wholesale and each entry must carry all four keys, else `ERR_VALIDATION` — implementation/routes/reports.py:50-65
- §3.4 — insert — ambiguity — VE with a `budget_line_id` not on the report's grant → `ERR_VALIDATION` 400 — implementation/routes/reports.py:198-200
- §3.4 — insert — ambiguity — VE refresh rewrites text, re-takes the snapshot, keeps status, and answers 201 like a first creation — implementation/routes/reports.py:206-212
- §3.4 — insert — ambiguity — `returned_reason` must be a non-empty string, else `ERR_VALIDATION` — implementation/routes/reports.py:163
- §3.5 — insert — ambiguity — volunteer recognition rounds half-up to whole cents; `volunteer_hours` may be fractional; neither value may be negative — implementation/routes/match.py:16-19,29-30, util.py:58-59
- §3.5 — insert — ambiguity — `documentation_ref` required non-empty but validated-only, not persisted on the contribution — implementation/routes/match.py:68, services.py:303-317
- §3.6 — insert — ambiguity — `bva` row shape pinned: one row per (line × period), lines in creation order, periods ascending, 12 enumerated fields — implementation/services_summary.py:56-82
- §3.6 — insert — ambiguity — both burn projections round half-up to whole cents; `pacing_ratio` null when the pro-rata award is zero — implementation/services_summary.py:95-107
- §3.7 — insert — ambiguity — type-specific mod fields: the owning type's field is required (`ERR_VALIDATION` if absent); the other type's field is stored as `[]`/null regardless of payload — implementation/routes/modifications.py:47-54
- §3.7 — insert — ambiguity — demoted FINAL report's `due_date` recomputed as `period_end` + `interim_report_due_days` — implementation/services.py:570-574
- §3.7 — revise — mismatch — PRD said an optional `denial_reason` "may accompany the decision" (implying persistence); impl ignores it — revised to "accepted but not persisted anywhere" — implementation/routes/modifications.py:151-162, services.py:320-333
- §3.8 — insert — ambiguity — `scheduled_end` must be strictly after `scheduled_start`, else `ERR_VALIDATION` 400 — implementation/routes/audit.py:43-44
- §3.8 — insert — ambiguity — auditor-capacity "active" defined as any status other than `CLOSED`, with half-open endpoints — implementation/routes/audit.py:51-67
- §3.8 — insert — ambiguity — finding `response_text` must be non-empty; reopen clears `response_text` to null — implementation/routes/audit.py:151,178-179
- §3.9 — insert — ambiguity — renewal `decision` outside `RENEWED`/`DECLINED` → `ERR_VALIDATION` 400 — implementation/routes/renewals.py:70-72
- §4 — insert — ambiguity — malformed/non-object JSON body → `ERR_VALIDATION` 400, absent body treated as `{}`; generic field/type/enum/range failures are always `ERR_VALIDATION` 400; VE upsert's 201-on-refresh carved out of the "modifications return 200" rule — implementation/middleware.py:34-43, util.py:83-166, routes/reports.py:212,221

Everything else in the impl (endpoint table, role lists, funder scoping, validation priority order incl. restriction-before-cross-grant on allocations and SoD-before-state on post/verify, state machines, cascades, proration waterfall, indirect pool, match totals, renewal windows, error catalogue) was already uniquely pinned by the PRD and left untouched.

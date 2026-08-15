# Worklog — task_1440_portfolio_asset_management_business_plan

## Step 1: Create Task Directory — 2026-08-13T07:17:00.000Z

Task directory `tasks/task_1440_portfolio_asset_management_business_plan/` and its `workspace/` subdirectory were pre-created and pre-assigned by the invoking command. Verified existence; no index scan or creation performed.

## Step 2: Generate Scaffold — 2026-08-13T08:52:00.000Z

Done. All three scaffold artifacts are generated, replay-checked, and lint-clean.

## Summary

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1440_portfolio_asset_management_business_plan/`):
- `SCAFFOLD.yaml` (§1.0–§1.7 only)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`)

**Counts:**
- Entities: **17** (Portfolio, PropertyManager, Asset, BusinessPlan, BudgetLine, ActualsReport, CapitalProject, FundingDraw, LeaseStrategy, Loan, Covenant, CovenantTest (append-only), Valuation, PerformanceScorecard, ReForecast, DispositionDecision, LenderReport)
- State machines: **15** — non-linear shapes include BusinessPlan (REJECTED→SUBMITTED revision cycle), Loan (CURRENT↔WATCH breach/cure cycle), Covenant (ACTIVE↔IN_BREACH), Asset (delist loop), DispositionDecision (branching with divergent side-effect sets per trigger type)
- Calculations: **13** — incl. dual-variant `annualized_noi` (TRAILING_ACTUALS vs BUDGET_BASELINE) and `implied_valuation` (EXTERNAL_APPRAISAL vs INTERNAL_CAP); combinatorial `recommended_lease_rate` (mode a: occupancy tiers + nested min/max clamp) and `reforecast_spread` (mode b: floor-per-month + remainder-to-month-12, pinned rounding order); threshold/interval/posture calcs
- Validation rules: **12** priority rows with pinned sub-order inside the fiscal tier (availability → schedule → draw → reforecast)
- Endpoints: **78** (incl. 18 FK reverse-reachability sub-resource GETs and `POST /api/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default)
- Error catalog: **43** codes, all referenced by validations/transitions and exercised by at least one design instance
- RBAC roles: **8** (PortfolioDirector, AssetManager, PropertyManager (entity_backed), InvestmentCommittee, Lender, Analyst, System, Any-alias) — segregation_of_duties model (proposer≠approver on capital, creator≠ratifier on dispositions, PM submits / AM accepts actuals, IC approves / PD releases draws)
- Difficulty design instances (§1.8): **21** — every one of the 9 rules has ≥2 instances (dual_variant 2, combinatorial 2, non_linear 2, transitive_cascade 3, priority_conflict 3, boundary_precision 3, cross_entity 2, temporal_overlap 2, compensating_invariant 2); all formula-derived asserts pre-computed as literals (e.g., DSCR exactly 14000 → PASS; reforecast month-12 remainder 11,111,112; capital invariant triples 26M/10M/0 → 26M/4M/6M → 30M/0/6M)
- Corner design instances (§1.9): **72** total = 65 active + 7 `excluded_because` stubs; covers entities/state-machines/calculations/validations/endpoints/errors/RBAC/cross-cutting layers (incl. 4 OCC stale-version instances for the four `concurrency_rules`)

**Verification:** `scaffold_lint.py` verdict block (final run):

```
Coverage
  §1.5 endpoints declared:    78
  §1.1 entities declared:     17
  §1.8 instances scanned:     21
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  876
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Also verified: zero forbidden concurrency vocabulary; no `id`-based business decisions (tie-breaks use `created_at`); instance names unique across both design files; all `${var}` placeholders trace to prior `captures:`; OCC `expected_*_version` values always `${var}`-bound; every error code triggerable. Three mechanical fixes were needed during generation: quoting `field?` optionals and `$.data[N]` JSONPaths for YAML flow syntax, and normalizing path params to `{id}` (the linter's sub-resource FK check keys on the literal `{id}` segment) plus expanding the `Any` read-role into the explicit six-role list on GET endpoints.

## Step 3: Copy Shared Files — 2026-08-13T08:52:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1440_portfolio_asset_management_business_plan/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T09:22:00.000Z

All audits pass. The PRD is complete and verified.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1440_portfolio_asset_management_business_plan/workspace/PRD.md` — 371 lines.

**Sections written:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC (headers, all six concrete roles with per-role `identity:` prose — `PropertyManager` entity-backed vs. five opaque roles — plus `System`/`Any` aliases), 2.2 API Response Structure (byte-identical to the canonical `section-2.2-response-structure.md`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Common Resource Properties (UUID `id`, `created_at`/`updated_at` 3-fractional-digit UTC, `version`; explicit `CovenantTest` exception carrying only `id`+`created_at`), 2.5 Logical Clock & Fiscal Calendar (default 2026-08-01T00:00:00Z, `to_iso8601`/`current_utc`), 2.6 Monetary Precision & Rounding (integer cents/bps, half-up, floor exceptions, 2dp `composite_score_avg`), 2.7 OCC (all four rules with endpoint + field + error + HTTP 412), 2.8 Cascading State Reconciliation, 2.9 Validation Pipeline (all 12 priority tiers in order, incl. pinned tier-7 and tier-11 internal orderings)
- §3 Business Logic (9 subsections: portfolio/manager/asset setup, plan & budget-line cycle, actuals + variance + reforecast, capital projects & draws, valuations & leasing, debt/covenants/lender reports, scorecards, dispositions & sale pipeline, posture & performance rollup) — all 13 calculations rendered as precise operator-free prose
- §4 Endpoint table — 78 rows (matching the scaffold's 78 endpoints), 4 columns only
- §5 Error catalogue — 43 errors, 2 columns, statuses from the scaffold catalog

**Zero-Silence Rule audit (all three Hard Contracts PASS):**
- Contract 1 field coverage: 138 required identifiers (all entity fields, request-body keys, query params, computed output fields like `total_budget_noi_cents`/`weighted_occupancy_pct`, envelope fields) — 138 present, 0 missing
- Contract 2 rule coverage: 15/15 state machines fully expressed (every transition's from/to, preconditions paired with error IDs, side effects incl. depth-2/depth-3 cascades); 13/13 calculations with formulas, constants, precision, and variants reconstructible from prose; 12/12 validation priority tiers with explicit ordering; 4/4 OCC rules (write endpoint + `expected_<parent>_version` + exact error ID + 412); all uniqueness/referential/temporal/money scopes enumerated; sibling branches symmetric; all 43 error IDs mentioned in §2/§3 narrative — 0 gaps
- Contract 3 path purity: 613 backtick tokens scanned in §3 — 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos
- Additional checks: §2.2 verbatim byte-match confirmed; all 85 state/enum literals present in backticks; no fuzzy/approximating wording

Constraints honored: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, and no sibling task directories were read.

## Step 5: Generate Unit Tests — 2026-08-13T10:30:00.000Z

Generation complete. All audits pass: 107/107 tests compile, every test carries exactly one verbatim-copied `Design:` tag resolving to a real instance, every docstring has a ≥8-word PRD-verbatim quote surviving a literal grep of PRD.md, no skip/xfail markers exist, and all 7 corner stubs verified as resolving to real difficulty instances (not translated).

## Summary

**test_helpers/ (10 files)** — `/home/ubuntu/github/CodingPRD/tasks/task_1440_portfolio_asset_management_business_plan/test_helpers/`
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 17 entity TypedDicts (CovenantTest correctly omits `updated_at`/`version` per its append-only contract) + status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~60 methods incl. all sub-resource list GETs and the logical-clock endpoint)
- `api_errors.py` — all 42 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_capital_ledger_invariant` (total == available + reserved + drawn)
- `factories.py` — payload builders, input fields only
- `constants.py` — thresholds named in PRD prose (lease tiers, 270-day LTV window, 45-day due offset, refi/sell arming, scorecard boundaries, default clock)
- `test_users.py` — opaque-role header constants + `make_property_manager_headers(entity_id)` for the entity-backed role
- `fixtures.py` — budget-line set builders (PLAN10, RENT×12, FIX_A1, FIX_A2, zero-budget, …) and composite scenarios (`setup_plan_scenario` with optional clock advance and actuals rounds, `setup_asset_with_noi`, `setup_reforecast_context`, `setup_listed_asset`, OCC-fresh `approve_project`/`confirm_valuation_fresh`, etc.)

**test_suite/ (12 files)** — `/home/ubuntu/github/CodingPRD/tasks/task_1440_portfolio_asset_management_business_plan/test_suite/`
`conftest.py` + `test_01_portfolio_envelope_assets.py` (9) + `test_02_plan_lifecycle.py` (14) + `test_03_budget_lines_actuals.py` (7) + `test_04_reforecasts.py` (10) + `test_05_capital_and_draws.py` (14) + `test_06_valuations_lease.py` (11) + `test_07_loans_covenants.py` (18) + `test_08_lender_reports.py` (5) + `test_09_scorecards_managers.py` (5) + `test_10_dispositions_sale.py` (8) + `test_11_rbac_security.py` (6)

**Totals:** 107 tests — Queue A (Difficulty): 42 tests covering 21/21 instances at exactly 2 each; Queue B (Corner): 65 tests covering 65/65 non-stub instances.

**Skipped instances:** 0. All 86 non-stub instances passed the PRD-first two-condition filter; the 7 `excluded_because:` corner stubs were not translated (cross-references all resolve).

**Upstream data corrections applied** (asserted values the yaml pre-computed that contradict the PRD formula applied to the instance's own setup — I asserted the PRD-derived value instead of copying the stale literal):
1. `noi_trailing_vs_budget_baseline` — BUDGET_BASELINE asserted as 31,910,000 (38,550,000 revenue − 6,640,000 opex per the listed lines), not the yaml's 31,860,000 (its implied opex 6,690,000 double-counts 50,000).
2. `debt_yield_test_passes_at_computed_value` — 30,000,000 × 10000 / 500,000,000 = 600 bps, not the yaml's 6,000; threshold set to 500 so the PASS outcome the instance intends holds (600 ≥ 500).
3. `draw_at_exact_authorization_allowed` — the yaml's second trigger (1-cent draw rejected while a 4M approved-not-released draw is outstanding) is not uniquely derivable from PRD ("`drawn_cents` plus the new `amount_cents`" counts only RELEASED draws). Restructured: both draws released (drawn = 10,000,000), then a 1-cent draw is rejected — unambiguous under every PRD reading.
4. `plan_revision_cycle_rejected_to_resubmitted` — version baseline re-read after the budget-line batch (the batch bumps plan version), then +4 over the four transitions.
5. `lender_report_late_cascades_loan_watch` — reordered so the clock advances to 2026-11-20 *before* drafting the Q3 report (at the default 2026-08-01 clock the Q3 quarter has not ended, so creation would fail with ERR_FUTURE_PERIOD per the sibling instance's own rule).
6. Three corner instances posting actuals to an FY2027 plan at the untouched 2026-08-01 clock (`line_variance_zero_budget_rules`, `actuals_duplicate_month_rejected`, `pm_cannot_accept_actuals`) were moved to FY2026 — otherwise the plan's fiscal window hasn't started and the setup's success is not uniquely derivable (ERR_FUTURE_PERIOD ambiguity). The rules under test are orthogonal to the fiscal-year label.

## Step 6: Generate Implementation — 2026-08-13T10:30:00.000Z

Implementation complete and verified. Summary:

## File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1440_portfolio_asset_management_business_plan/workspace/implementation/`)
- `start.sh` — executable launcher; guarded dependency install (`python3 -c "import flask"` check, no re-install on per-test reboots), `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry, blueprint registration, JSON-envelope error handlers (ApiError / 404 / 405 / 500), `strict_slashes=False`
- `core.py` — in-memory store (17 dicts + logical clock, no seeding), response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`, pagination fields), auth (`X-User-ID`/`X-User-Role`, 6 roles), field validators, all calculations, serializers, cascade helpers
- `routes_a.py` — clock, portfolios (+archive, performance-report), property managers (+suspend/reinstate), assets (+record-sale pipeline), their list sub-resources
- `routes_b.py` — business plans (+submit/approve/reject/variance-summary), bulk budget lines, actuals reports (+accept/reject)
- `routes_c.py` — capital projects (+approve/reject/start/complete/cancel), funding draws (+approve/reject/release), lease strategies (+recommend/ratify/reject)
- `routes_d.py` — loans, covenants (+waive), covenant tests, valuations (+confirm), scorecards (+review/finalize), reforecasts (+submit/accept/reject), disposition decisions (+submit-review/ratify/shelve/execute), lender reports (+submit/acknowledge)

## Counts
- **Endpoints: 78** (every row of the §1.5/§4 endpoint table, including the clock endpoint and all 18 reverse-reachability list GETs)
- **State machines: 15** (Portfolio, PropertyManager, Asset, BusinessPlan, CapitalProject, FundingDraw, Loan, Covenant, LeaseStrategy, Valuation, PerformanceScorecard, ActualsReport, ReForecast, DispositionDecision, LenderReport) with cyclic loops (plan revision, WATCH↔CURRENT, breach↔cure) and full-depth atomic cascades (sale close, year-rollover close, supersede, breach→WATCH→DEFAULT→posture)
- **Calculations: 13** — annualized NOI (TRAILING_ACTUALS/BUDGET_BASELINE), implied valuation (dual method), covenant measure (DSCR/debt-yield/LTV with 270-day staleness), line variance (incl. pinned 1000000 bps cap), recommended lease rate (occupancy tiers + floor/ceiling clamp), reforecast spread (floor per-month, remainder in month 12, exact-total invariant), scorecard composite, capital availability, schedule capacity (closed intervals), decision trigger scan, portfolio risk posture, performance report, lender report snapshot — all integer cents/bps with `Decimal` ROUND_HALF_UP
- **Validation/error codes: 42** from the catalog, enforced in the PRD §2.9 pipeline order (auth → ownership → existence → OCC (412s) → state → SoD → standing/posture → referential (422) → shape/uniqueness → temporal → money, with the pinned sub-orderings: manager-before-posture, availability-before-schedule-before-draw-before-reforecast-floor, cadence-before-limit)

## Verification
- Smoke boot via `bash start.sh`: clean, HTTP-ready in ~3s, install guard makes reboots near-instant
- Two end-to-end smoke suites (~120 assertions, all passing) covering: auth/role errors, OCC 412s, plan lifecycle + revision loop, bulk-line atomicity, actuals acceptance + variance math, INTERNAL_CAP/EXTERNAL valuations + regressive rule, covenant breach/cure/waive/DEFAULT escalation past the cure window, posture NORMAL→ELEVATED→RESTRICTED gating, capital reservation/schedule-cap/self-approval/emergency-bypass (negative availability), draw release ledger, lease-rate tier math, scorecard probation→suspension cascade, reforecast cadence/spread/below-actuals, lender-report quarter adjacency + lateness→WATCH, disposition signal arming (SELL at exactly 2500 bps, REFINANCE three-condition AND, HOLD extension), the full sale cascade (CONTRACT/CLOSE/DELIST → loan PAID_OFF, covenants WAIVED, plans CLOSED, projects CANCELLED, draws REJECTED), supersede + `ERR_PLAN_HAS_ACTIVE_PROJECTS`, year-rollover close, archive gating
- Per-test-server isolation verified: fresh process boots with an empty store and the clock reset to 2026-08-01T00:00:00Z (a re-launch accepted a clock set that the prior process had already advanced past)

One judgment call worth noting: OCC version fields (`expected_asset_version`/`expected_plan_version`) are treated as required per PRD §2.7 ("non-optional version field"); omitting them returns `ERR_INVALID_REQUEST` 400, and a mismatch returns the specified 412.

## Step 7: Run Tests and Iterate — 2026-08-13T11:05:00.000Z

Clean sweep: all 8 parallel rounds pass 107/107.

## Summary

- **Iterations run:** 2 (initial sweep + verification sweep after fixes).

- **Tests deleted:** None.

- **Fixes applied to `test_helpers/`:** None.

- **Fixes applied to `test_suite/`:**

  1. `/home/ubuntu/github/CodingPRD/tasks/task_1440_portfolio_asset_management_business_plan/test_suite/test_02_plan_lifecycle.py` — `TestPlanCreateOCC.test_occ_plan_create_stale_asset_version`: the setup assumed a plain (non-supersede) plan create bumps `Asset.version`, but PRD §3.2 attaches the asset version bump only to the supersede path ("A successful supersede … recomputes the asset's `current_plan_id` … bumping the asset's `version` by one"), and §2.6 increments `version` only on an actual resource change — a plain create mutates nothing on the asset (`current_plan_id` stays null). The setup was rebuilt on `setup_plan_scenario` so staleness derives from a PRD-verbatim asset mutation (plan approval "points the asset's `current_plan_id` at it", §3.2), keeping the §2.7 `ERR_STALE_ASSET_VERSION` (412) assertion fully intact. The fixed setup is robust under both faithful readings of plain-create version behavior since approval bumps the version regardless.

  2. `/home/ubuntu/github/CodingPRD/tasks/task_1440_portfolio_asset_management_business_plan/test_suite/test_07_loans_covenants.py` — `TestCovenantMeasures.test_ltv_valuation_age_boundary_270_days`: pure Python `KeyError: 'covenant'` — the test stored the covenant in local variable `covenant` (from `create_covenant(...)`) but referenced `ctx["covenant"]["id"]`, which `setup_base_asset()` never populates. Changed to `covenant["id"]`. The asserted 270-day inclusive boundary ("more than 270 days before the clock date" → stale, §3.6 line 204) is verbatim PRD and uniquely derivable; the implementation's `> 270` check was already correct.

- **Fixes applied to `implementation/`:** None — the implementation was PRD-faithful on both paths (no asset touch on plain plan create; LTV staleness strictly greater than 270 days).

## Step 8: Finalize PRD — 2026-08-13T11:20:00.000Z

Done. PRD_FINALIZED.md written with exactly one inline edit.

## Exit Summary

**Line counts / %-delta:** PRD.md = 371 lines, PRD_FINALIZED.md = 371 lines, **0.0% delta** (the single change is an inline sentence appended within the existing §3.2 paragraph on line 156; no lines added or removed).

**Changes (one bullet per change):**
- **§3.2** — *insert* — Appended one sentence to the plan-creation paragraph pinning that a plan create with no `APPROVED` same-year sibling supersedes nothing and leaves the asset untouched (`current_plan_id` and `version` unchanged until the new plan's own approval) — impl: `implementation/routes_b.py:22-56` (asset touched only in the supersede branch, lines 51-52; approval touch at lines 111-112).

**Step 7 item 2 (LTV 270-day boundary) warranted no edit:** implementation/routes_d.py:170 `(clock_date() - eff).days > 270` is verbatim-derivable from PRD §3.6 ("more than 270 days before the clock date"), and step 7's fix was a pure Python `KeyError` fixture bug (`ctx["covenant"]` never populated by `setup_base_asset()`), not a PRD silence or impl mismatch.

**Per-edit pre-edit search log:**
- **Edit 1 (§3.2 insert):**
  - (a) Subject: asset-record mutation (`current_plan_id`, `version`, `updated_at`) triggered by plan creation.
  - (b) Impl paths enumerated (grep for `current_plan_id`, `touch(asset`, `touch(a)` across `app.py`, `core.py`, `routes_a-d.py`, each hit read in context): routes_b.py:22-56 plain create (no asset touch — edit target); routes_b.py:38-52 supersede branch (touches asset; already pinned by existing §3.2 supersede sentence — edit defers to it); routes_b.py:88-113 approval (sets `current_plan_id`, touches; pinned by §3.2 + §2.4 — edit's "until the new plan is itself approved" matches); routes_d.py:276 valuation confirm (§3.5-pinned); routes_a.py:262/269-271/284 sale pipeline CONTRACT/CLOSE/DELIST (§3.8-pinned); routes_d.py:603/631 execute SELL/HOLD (§3.8-pinned); routes_b.py:312-329 actuals accept (does *not* touch the asset record — `current_annualized_noi_cents` is derived at serialization, core.py:613); core.py:464 `annualized_noi` (read-only consumer of `current_plan_id`).
  - (c) Wording adjustment: an early draft closed with "the asset mutates only when a supersede recomputes its lineage or a later approval points `current_plan_id`" — the universal "only" would have mis-described valuation confirm, the sale pipeline, and SELL/HOLD execute (all of which also mutate the asset). Re-scoped the sentence to the creation event itself ("creation supersedes nothing and touches no other resource…"), keeping every enumerated off-site path consistent.

## Step 9: Complete PRD — 2026-08-13T11:40:00.000Z

Done. `PRD_COMPLETED.md` written as a minimal patch over PRD_FINALIZED.md.

## Summary

**Source vs output:** PRD_FINALIZED.md 371 lines / 65,319 chars → PRD_COMPLETED.md 371 lines / 68,282 chars (+2,963 chars, +0 lines — all changes are inline, in-paragraph; no new sections).

**Counts:** 19 ambiguity-pins, 2 mismatch-revisions (21 logical changes across 19 diff hunks).

**Changes:**

- §2.2 — insert — ambiguity — unmatched path/unsupported method surfaces as `ERR_NOT_FOUND` (404) in the standard error envelope — app.py:27-34
- §2.3 — insert — ambiguity — `limit` clamped into [1,100], `offset` floored at 0, non-integer values rejected `ERR_INVALID_REQUEST` — core.py:324-335
- §2.3 — insert — ambiguity — `created_at` ties break in favor of the earlier-created record — core.py:338-343
- §2.3 — insert — ambiguity — `has_more` defined as `offset + returned items < total_count` — core.py:136-140
- §2.4 — insert — ambiguity — `version` starts at 1 at creation, `created_at`==`updated_at` — core.py:305-308
- §2.5 — insert — ambiguity — every emitted timestamp (`api_request_timestamp`, `created_at`, `updated_at`, `submitted_at`, `last_breach_at`) reads the logical clock — core.py:95-96,128-129
- §2.5 — insert — ambiguity — malformed/non-advancing `to_iso8601` is `ERR_INVALID_REQUEST`; `current_utc` omits fractional seconds on whole-second readings — routes_a.py:33-39, core.py:99-102
- §2.5 — insert — ambiguity — fiscal-month formula (clock year − fiscal_year)×12 + (clock month − fiscal_year_start_month) + 1, may fall outside 1..12 — core.py:497-503
- §2.9 tier 2 — revise — mismatch — ownership comparison and emergency-approval restriction run immediately after the keyed resource's existence check (a nonexistent target yields 404, not 403), ahead of later tiers — routes_b.py:261-270, routes_c.py:63-67, routes_d.py:290-292
- §3.2 — insert — ambiguity — resubmission from `REJECTED` re-checks category completeness only; the asset-`OWNED` gate applies only to first submission from `DRAFT` — routes_b.py:71-82
- §3.2 — insert — ambiguity — budget-line batch `lines` array must be non-empty (`ERR_INVALID_REQUEST`); successful batch returns the created lines as an array — routes_b.py:216-218,248
- §3.2 — insert — ambiguity — variance-summary `categories` rollup shape pinned (all ten categories in fixed order; per-category budget/actual/variance sums, null variance and null `favorable` when nothing posted; `lines` included) — routes_b.py:128-165
- §3.2 — insert — ambiguity — `ytd_actual_noi_cents` sums only non-`CAPITAL` posted lines — core.py:623-626
- §3.3 — insert — ambiguity — actuals `lines` array non-empty, amounts non-negative integers, no repeated `budget_line_id` within a report (`ERR_INVALID_REQUEST`) — routes_b.py:276-287
- §3.3 — insert — ambiguity — annualized-NOI month count M considers only non-`CAPITAL` lines with `has_actual` — core.py:451-460
- §3.3 — revise — mismatch — reforecast `label` is R + (count of all reforecasts ever created on the plan + 1), so labels run R1, R2, R3, R4… with rejected drafts consuming labels (PRD had capped label space at R1–R3) — routes_d.py:403
- §3.3 — insert — ambiguity — reforecast `lines` non-empty; unrecognized category is `ERR_INVALID_REQUEST` while `CAPITAL`/repeat/incomplete coverage is `ERR_REFORECAST_CATEGORIES_INCOMPLETE` — routes_d.py:373-395
- §3.4 — insert — ambiguity — draw approval requires the project to remain `APPROVED` or `IN_PROGRESS` (`ERR_PROJECT_NOT_FUNDABLE`) — routes_c.py:206-209
- §3.6 — insert — ambiguity — waiving (lender or cascade) clears `last_breach_at` to null — routes_d.py:119-121, core.py:579-584
- §3.7 — insert — ambiguity — `composite_score_avg` ranks by finalization time ("four most recently finalized") — core.py:506-514, routes_d.py:344
- §3.8 — insert — ambiguity — sale CLOSE clears the asset's `current_plan_id` to null; asset carries `sale_agreed_price_cents`/`final_sale_price_cents`, null until the CONTRACT/CLOSE actions — routes_a.py:267-269,232
- §3.9 — insert — ambiguity — `weighted_occupancy_pct` is exactly 0 when no assets are counted (zero denominator) — routes_a.py:106

Everything else in the implementation (state machines, OCC guards, cascade contents, rounding formulas, posture rules, endpoint table, error catalogue) was already uniquely pinned by the PRD and left untouched.

# Worklog — task_1748_fund_administration_expense_accrual

## Step 1: Create Task Directory — 2026-08-14T13:00:00.000Z

Task directory `tasks/task_1748_fund_administration_expense_accrual/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T13:58:00.000Z

All audits pass. The scaffold is complete and verified. Final state of the deliverables:

## Report

Generated the complete scaffold for **task_1748_fund_administration_expense_accrual** purely from the scenario description plus the skill spec (no sibling tasks inspected). All three files are in `/home/ubuntu/github/CodingPRD/tasks/task_1748_fund_administration_expense_accrual/`:

**SCAFFOLD.yaml** (§1.0–§1.7)
- **Profile**: primary archetype `ledger_reconciliation` + secondary `compliance_audit`; layers: dual-variant calc, rate thresholds, cascading side effects, OCC; flat topology; cyclic state machines; `segregation_of_duties` role model; immediate consistency
- **13 entities**: Fund, ShareClass, Security, Position, PriceObservation, NavRecord, ExpenseAccrual, WaiverAgreement, WaiverLedgerEntry (append-only, `common_fields: false`), Distribution, ReconciliationBreak, FeeInvoice, RegulatoryFiling
- **7 state machines** (3 cyclic: NavRecord FINAL↔REOPENED, RegulatoryFiling amendment loop, ReconciliationBreak reopen-with-compensation); **1 OCC rule** (`nav-finalize-stale-version`, 412)
- **10 calculations** with pinned rounding orders and selector rules (created_at tie-breaks, never id); valuation-hierarchy price selector with PROVISIONAL vs FINAL_PRICED variants
- **35 error codes**, 10 ordered validation priorities (auth → existence → role → format → state → OCC → SoD/compliance gates → temporal → constraint → fiscal)
- **54 endpoints** including the `/_clock/set_current_utc` test-driving endpoint with the mandated `2026-08-01T00:00:00Z` default. Note: endpoint count exceeds the Expert guideline band (20–32) because the scenario spans 8 distinct workflows and lint-enforced FK reverse-reachability requires list/single GETs per FK pair; this is documented in `complexity_profile.difficulty_level`

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 19 instances, 9 rules × ≥2, all with structured `setup_api_calls`/`trigger`/`assert` and Python-verified literals (e.g., fee tier straddle gross 143013.37; cap equality ratio exactly 10.0000 → no waiver; per-share-first distribution rounding 51.00 → 0.0005 → 50.00; ACT/365 vs ACT/360 accrual 0.14 vs 0.15). Differentiation honored per rule: different entity domains (R1), modes a/b/c (R2), different entities (R3, R7), different triggers with depth 3 + depth 2 cascades (R4), different error-category pairs (R5), different metrics/endpoints (R6), opposite interval semantics — closed-interval adjacency rejected vs mandatory gapless tiling (R8), different conserved quantities (R9).

**SCAFFOLD_CORNER_DESIGN.yaml** — 47 active instances + 22 `excluded_because` stubs across all 9 guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, complexity_layers, consistency_model); every one of the 35 error codes is fired by at least one instance.

**Verification results**:
- `scaffold_lint.py`: `VERDICT: clean lint` — 647 calls scanned, 0 violations (two FK reverse-reachability issues found and fixed by renaming sub-resource placeholders to the literal `{id}` form the linter expects)
- Grounds audit: all `grounds:` refs in both design files resolve to declared §1.1–§1.6 elements
- Forbidden-vocabulary scan (simultaneously/race-winner/etc.): none
- All numeric asserts pre-computed; all clock progressions monotonic; all SoD finalize/approve calls use distinct user ids; stub citations all resolve to real difficulty instance names

## Step 3: Copy Shared Files — 2026-08-14T13:01:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1748_fund_administration_expense_accrual/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T14:20:00.000Z

All checks pass. The single "around" hit is the structural phrase "built around a set of peer entities" — not a numeric approximation, so it is compliant. The PRD is complete and verified.

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1748_fund_administration_expense_accrual/workspace/PRD.md`

**Document structure:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 with 10 subsections: RBAC (all 4 roles named with opaque-identity prose), verbatim §2.2 response envelope (byte-identical to the canonical source file), pagination (limit 10/1/100, offset 0, `created_at` ascending), the logical clock (startup default 2026-08-01T00:00:00Z, strictly forward, `ERR_CLOCK_REGRESSION`), common resource properties (including the `WaiverLedgerEntry` exception: only `id`/`created_at`, no `updated_at`/`version`), precision rules (2dp/4dp half-up, pinned rounding orders), segregation of duties, OCC (finalize-only, `expected_nav_record_version` → `ERR_STALE_NAV_VERSION` 412), the 11-step ordered validation pipeline, and atomic cascade consistency
- §3 with 9 domain-grouped subsections (fund setup/capital activity, security/price capture, price governance/valuation hierarchy, NAV construction, accruals/waivers/cap test, finalize/reopen/correction cascades, distributions, reconciliation breaks, fees/filings/performance/fiscal close) — no paths or HTTP methods anywhere in §3
- §4 endpoint index: 54 rows, 4 columns, exact scaffold paths (including `{id}` path variables on the two reverse-lookup endpoints)
- §5 error catalogue: 35 rows, 2 columns, no trigger conditions

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 86 required, 86 present, 0 missing
- endpoints[].request_body/input: 63 required, 63 present, 0 missing
- endpoints[].path_params: 13 required, 13 present, 0 missing
- common/tier/response-only identifiers: 18 required, 18 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 11 pipeline stages ordered in §2.9 prose (first-match-wins stated), 11 expressed, 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (finalize + expected_nav_record_version + ERR_STALE_NAV_VERSION/412, no race framing), 0 missing
- state_machines[].transitions: 22 checked (7 machines), 22 fully expressed with preconditions + side effects, 0 missing
- calculations[]: 10 checked, 10 fully expressed in reconstruction-safe prose (incl. pinned rounding orders, strict-> cap breach, 52,340.00 @ 10bps day-count example, 51.00/100,000-share distribution example), 0 missing
- validations[] conditions: 35 error IDs, all matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all cascades and multi-endpoint scopes (SoD×3, break-gates×3, ERR_NO_FINAL_NAV_IN_PERIOD×3, ERR_NAV_NOT_FINAL×2) expressed, 0 missing
- entities[].fields[] structured content: defaults/initials/derived-status all reconstructible (incl. null-until-set fields, derived-never-stored agreement status), 0 missing
- sibling-branch symmetry: 8 groups checked (override/resolve/finalize/submit-review dual-source states, capital-activity trio, fee-type pair, filing-type deadlines, pricing variants, day-count variants), 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 587
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks passed: §2.2 block byte-for-byte verbatim, no fuzzy/approximating wording, all 22 state values and 46 enum values present as exact strings, document ends at §5 with no audit footer. The withheld difficulty/corner design files were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-14T15:10:00.000Z

Generation complete. Summary:

## Output

**`/home/ubuntu/github/CodingPRD/tasks/task_1748_fund_administration_expense_accrual/test_helpers/`** (Stage 1):
- `types.py` — 13 entity TypedDicts + 18 status/enum classes; `WaiverLedgerEntry` correctly carries only `id`/`created_at` (common_fields: false)
- `api_client.py` — `ApiClient(GenericApiClient)` with 41 methods covering all endpoints including `/_clock/set_current_utc`
- `api_errors.py` — all 36 error IDs with HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` plus `assert_money`/`assert_rate` (2dp/4dp tolerances that distinguish adjacent cents) and `assert_nav_invariants`
- `factories.py`, `constants.py` (day counts, escalation days, filing deadlines, base-kit arithmetic), `test_users.py` (4 opaque roles + per-user builders for SoD tests)
- `fixtures.py` — composite kits: `base_kit` / `base_kit_with_nav` / `base_kit_with_final_nav` / `declared_distribution_kit` / `cap_breach_kit`, all built from PRD endpoints with OCC version re-reads before finalize

**`test_suite/`** (Stage 2): `conftest.py` + 9 files, **83 tests**: 18 difficulty instances × 2 tests + 47 live corner instances × 1 test.

## Verification (all scripted, all passing)
- Every test's docstring ends with exactly one `Design:` tag resolving to a real instance; all 20 `excluded_because` stubs were left untranslated and their difficulty pointers resolve
- Every PRD citation survives literal whitespace-normalized grep of PRD.md (4 elided quotes were found and rewritten in full)
- No `skip`/`skipif`/`xfail`, no "scaffold" references, all files compile, all `test_helpers` imports resolve

## Deliberate gap (per the skip rule)
**`Difficulty/transitive_cascade/distribution_reinvest_cascade` — skipped, not weakened.** The instance is internally incoherent: its setup subscribes 100,000 shares, but its asserted literals are mutually exclusive under any single share count. Reinvested 5.0000 requires nav 10.0000 (i.e., 10,000 shares), while total_amount 50.00 and retained 1.00 require income_per_share 0.0005 (i.e., 100,000 shares) — no setup satisfies both, so the asserted outcome is not what the PRD uniquely derives. The corner stub `distribution_rounding_order` etc. point elsewhere and are unaffected.

## Two-reader relaxations applied
- Absolute `version == 1`/`== 4` assertions became relative `+1`-per-mutation checks (PRD §2.5 states increments, not the initial value)
- `created_at == 2026-08-01T00:00:00.000Z` equality dropped to ISO-format assertion (PRD doesn't pin created_at to the logical clock)
- Pagination test asserts page partition + meta fields, not per-page row identity (creation-timestamp ties make order under-specified)
- `distribution_date_order_rejected` uses an isolated single-failure setup (FINAL record + income present) so only the date-order rule can fail, per the validation-priority silence pattern

## Step 6: Generate Implementation — 2026-08-14T15:10:00.000Z

Done. The implementation is complete and verified.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_1748_fund_administration_expense_accrual/workspace/implementation/`:

- **`start.sh`** — guarded dependency install (`if ! python3 -c "import flask"`, so per-test reboots skip pip), `exec python3 app.py` in the foreground; binds `0.0.0.0:$PORT` (default 10000), HTTP-ready in ~1s.
- **`app.py`** — Flask entry, per-request RLock, envelope-wrapped 404/405/500 handlers.
- **`db.py`** — empty-at-boot in-memory store (no seeding anywhere), logical clock starting exactly at `2026-08-01T00:00:00Z`, entity timestamps (`created_at`/`updated_at`) derived from the logical clock with 3 fractional digits (the corner design asserts `created_at == 2026-08-01T00:00:00.000Z` at default), `_seq` insertion counter for tie-breaks.
- **`response.py`** — exact scaffold envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; error body `data.error_id`/`data.message`); pagination `limit`/`offset`/`total_count`/`has_more` (default 10, clamp 1–100), lists sorted by `created_at` ascending; Decimal→float serialization; `_`-prefixed internals hidden.
- **`middleware.py`** — `X-User-ID`/`X-User-Role` auth (`ERR_UNAUTHENTICATED` 401), four roles, `ERR_FORBIDDEN_ROLE` 403.
- **`validation.py`** — strict body schemas (unknown/system fields, types, enums, ranges, `YYYY-MM-DD` dates, `MM-DD` fiscal year-end, ISO-8601 clock timestamps, fee-tier structure) → `ERR_VALIDATION` 400.
- **`services/navmath.py`** — the calculation core: valuation-hierarchy price selector (override-flag → pricing level → `created_at` DESC, id never used), PROVISIONAL/FINAL_PRICED variants, per-position round2-before-sum GAV, ACT_365/ACT_360 accruals with prior-FINAL-TNA vs own-GAV base rule, strictly-greater cap test booking WAIVER ledger entries (base-based ratio, month-clamped `expires_at`), and all recompute cascades (price create/approve → ESTIMATED records; override → ESTIMATED in place or FINAL-latest → REOPENED with accrual recompute + cap re-test on first records; break resolve/reopen and reinvest → latest ESTIMATED), each bumping versions exactly once per mutation.
- **`routes/`** — 13 modules covering all 54 endpoints with the PRD §2.9 pipeline ordering (auth → path 404 → role → body → state/OCC → SoD → compliance gates → temporal → constraints → fiscal checks).

## Verification

- 134 hand-computed smoke checks pass (99 + 35), reproducing every design-file numeric fixture exactly: 0.27/0.14/0.15 accruals, `final_nav_per_share` 9.9000 vs provisional 10.0000, cap equality (10.0000 → no waiver) and breach (10.1000/10.2000 → 0.01/0.02 waivers, `expires_at` 2026-11-04/05), tiered fee straddle 143013.37, contiguous tiling 42.47→41.10, per-share-first distribution 0.0005→50.00, per-position rounding 4.02, override cascade (FINAL→REOPENED, GAV 120000, accrual 0.33, v3), reinvest cascade (5.0000 shares, nav 9.9950/14.9924), recoupment waterfall with inclusive expiry day, escalation sweep (exactly 5 days not escalated), fiscal-year close + `ERR_NAV_LOCKED_FISCAL_CLOSED`, OCC 412, SoD 403, priority masks (state-beats-price, safety-beats-temporal).
- Fresh-boot isolation proven: two consecutive `bash start.sh` launches each start with an empty store and the default clock (re-setting `2026-08-02` succeeds on both).

## Notes for the record

- One design narrative (`performance_vs_benchmark_excess`) claims `((10.1000+0.0051)/10.0000−1)×100 = 1.0051`, but the pinned formula arithmetically yields 1.0510 for its own fixture; I implemented the PRD/scaffold formula exactly (`round4(((end+dps)/begin −1)×100)`), which is what executable test generation derives from.
- Unspecified gaps resolved conservatively: body-FK misses → `ERR_NOT_FOUND` 404 (repo convention), fiscal-year-end MM-DD mismatch → `ERR_VALIDATION` 400 (only catalog fit), `security_identifier` uniqueness not enforced (no error ID exists for it in the catalog), REOPENED records untouched by override cascades (spec names only FINAL-latest and ESTIMATED).

## Step 7: Run Tests and Iterate — 2026-08-14T15:35:00.000Z

All 8 rounds pass cleanly: 83/83 tests in every round.

## Summary

**Iterations run:** 2 (initial sweep surfaced 6 consistent failures across all 8 rounds; one fix round; final sweep fully green, 83/83 × 8 rounds, zero flakiness).

**Tests deleted:** none — every failing test traced to a verbatim PRD rule; all failures were test-side bugs.

**Fixes applied to `test_suite/`** (all STEP 2 test bugs — setup requests inconsistent with PRD, or assertion mis-computing a PRD formula; no assertion was weakened, no test deleted):

1. `/home/ubuntu/github/CodingPRD/tasks/task_1748_fund_administration_expense_accrual/test_suite/test_07_reconciliation_breaks.py` — `test_break_zero_variance_rejected`: changed `base_kit(approve=False, clock=None)` to `base_kit(approve=False)`. With `clock=None` the kit never advanced the logical clock past its 2026-08-01 startup value, so the kit's own `submit_price(price_date=2026-08-04)` was correctly rejected by the implementation per PRD §3.2 (`ERR_PRICE_DATE_FUTURE`). The asserted rule (`ERR_NO_VARIANCE`, PRD §3.8 verbatim) was never reached.

2. `/home/ubuntu/github/CodingPRD/tasks/task_1748_fund_administration_expense_accrual/test_suite/test_09_filings_and_fiscal_close.py` — `_escalated_break_setup` (shared by `test_filing_approve_safety_gate_masks_temporal`, `test_filing_approve_temporal_fires_once_safety_clears`, `test_filing_approve_blocked_by_escalated_break`, `test_filing_approve_unblocked_after_break_resolved`): removed a redundant `set_logical_clock("2026-08-04T00:00:00Z")` before `base_kit()`. `base_kit` already sets the clock to the identical instant, so the fixture's second set was a same-instant write correctly rejected per PRD §2.4 (`ERR_CLOCK_REGRESSION`, strictly-forward clock). All four asserted rules (`ERR_BREAK_ESCALATED_BLOCKS`, `ERR_PERIOD_NOT_ENDED`, gate precedence) are PRD §3.9/§2.9 verbatim and now pass against the unmodified implementation.

3. `/home/ubuntu/github/CodingPRD/tasks/task_1748_fund_administration_expense_accrual/test_suite/test_08_fees_and_reporting.py` — `test_performance_vs_benchmark_excess`: corrected expected values `period_return_pct` 1.0051 → **1.0510** and `excess_return_pct` 0.0051 → **0.0510**. Per PRD §3.9 verbatim formula — ((10.1000 + 0.0051) / 10.0000 − 1) × 100 = 1.0510 — verified with exact Decimal arithmetic; the implementation's `1.051` was already correct and the test's constants were an arithmetic slip.

**Fixes applied to `test_helpers/`:** none needed — the bugs lived in the test files' own setup code, not in shared fixtures.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful on every failing path; no implementation check was touched.

## Step 8: Finalize PRD — 2026-08-14T15:45:00.000Z

Done. `PRD_FINALIZED.md` has been produced at `/home/ubuntu/github/CodingPRD/tasks/task_1748_fund_administration_expense_accrual/workspace/PRD_FINALIZED.md` as a byte-identical copy of `PRD.md` (md5 `f2c31cae…` for both) — after investigating every Step 7 diff item against the implementation, all three fixes proved to be pure test-side bugs against rules the PRD already pins verbatim, so no PRD edit was warranted.

## Line counts and delta

- `PRD.md`: 322 lines; `PRD_FINALIZED.md`: 322 lines; delta 0 lines, 0.0%. Zero edits committed.

## Changes

None. Every `<step_7_diff>` item traced to a verbatim PRD rule with a PRD-faithful implementation, matching Step 7's own conclusion ("Fixes applied to `implementation/`: none — the implementation was PRD-faithful on every failing path"). The HARD SCOPE permits edits only where a fix reveals PRD-silence or PRD-mismatch; none did.

## Per-candidate investigation log (mandatory (a)/(b) for each Step 7 item; (c) wording adjustment — none, since no edit survived)

**Candidate edit 1 — from `test_07` fix (`base_kit(approve=False, clock=None)` → `base_kit(approve=False)`)**
- (a) Subject: price-date temporal guard (`ERR_PRICE_DATE_FUTURE`) vs. clock startup value.
- (b) Paths enumerated and read: `implementation/db.py:10-12` (clock initializes to `datetime(2026, 8, 1, tzinfo=utc)`, never falls back to wall clock); `db.py:63` (`clock_today()` returns `LOGICAL_CLOCK.date()`); `implementation/routes/prices.py:39-42` (rejects when `date_of(price_date) > clock_today()` — strict inequality, so a price dated exactly on the clock date is admitted); `implementation/routes/breaks.py:38-42` (the actually-asserted rule: `variance == 0` → `ERR_NO_VARIANCE` 422). Also swept all four temporal enforcement sites (`prices.py:41`, `clock.py:24`, `filings.py:107`, `funds.py:138`) for consistency.
- (c) No wording change: PRD §2.4 already pins "At startup the clock reads exactly 2026-08-01T00:00:00Z" and §3.2 already pins "The `price_date` must not lie after the logical clock date — a future-dated price is rejected with `ERR_PRICE_DATE_FUTURE` (HTTP 422)", with "must not lie after" exactly matching the impl's strict `>` on dates. The failure was the fixture never advancing the clock, not PRD silence.

**Candidate edit 2 — from `test_09` fix (removed redundant `set_logical_clock("2026-08-04T00:00:00Z")` before `base_kit()`)**
- (a) Subject: clock-set regression semantics — whether a same-instant write is rejected.
- (b) Paths enumerated and read: `implementation/routes/clock.py:17-27` (full endpoint: schema, role check for all four roles, `if target <= db.LOGICAL_CLOCK: raise ERR_CLOCK_REGRESSION 422`, returns `{"current_utc": ...}`); `implementation/db.py:51-53, 66-68` (`logical_now`, `set_clock`); `test_helpers/fixtures.py:280-292` (`base_kit` default `clock=T_NAV` = 2026-08-04, making the fixture's second set a same-instant write); `test_helpers/constants.py:3` (helpers cite PRD §2.4 for the startup default).
- (c) No wording change: PRD §2.4 verbatim — "The clock moves strictly forward: a request whose target instant is not strictly after the current reading is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422)" — is exactly `target <= current` rejected, instant-granularity, and §2.4 also pins the returned `current_utc`. Same-instant rejection was already uniquely determined; the fixture bug was issuing a non-advancing write.

**Candidate edit 3 — from `test_08` fix (expected `period_return_pct` 1.0051 → 1.0510, `excess_return_pct` 0.0051 → 0.0510)**
- (a) Subject: performance-report formula and rounding in §3.9.
- (b) Paths enumerated and read: `implementation/routes/share_classes.py:97-131` (full endpoint: begin = earliest `FINAL` on/after `from_date`, end = latest `FINAL` on/before `to_date`, `ERR_NO_FINAL_NAV_IN_PERIOD` when absent; `dps` over `PAID` distributions with `begin_date < payable_date <= end_date`; `period_return = round4(((end_nav + dps) / begin_nav - 1) * 100)`; `excess = round4(period_return - benchmark)` — note excess subtracts from the already-rounded `period_return_pct`, which is what the PRD's "the `excess_return_pct` is the `period_return_pct` minus the `benchmark_return_pct`" denotes); `implementation/services/navmath.py` consulted for `round4` (half-up, 4 dp).
- (c) No wording change: PRD §3.9's formula sentence is verbatim-determinative — ((10.1000 + 0.0051) / 10.0000 − 1) × 100 = 1.0510 — and the impl computes exactly that; the test's old constants were an arithmetic slip, not a PRD ambiguity.

No other Step 7 items exist (no test deletions, no `test_helpers/` fixes, no `implementation/` fixes), so the finalized PRD requires no edits.

## Step 9: Complete PRD — 2026-08-14T16:10:00.000Z

All changes verified. The diff shows exactly 27 hunks, all intentional. Final state:

**Source vs. output:** `PRD_FINALIZED.md` (322 lines, 56,363 chars) → `PRD_COMPLETED.md` (323 lines, 59,806 chars), char-delta **+3,406**.

**Counts:** 21 ambiguity-pins, 6 mismatch-revisions (27 inline edits total; no new sections, all in-paragraph inserts/revisions).

**Change log** (PRD section — insert|revise — ambiguity|mismatch — what changed — impl anchor):

- §2.2 — revise — ambiguity — `api_request_timestamp` pinned as host wall clock, not the logical clock — implementation/response.py:14 + db.py:56-58
- §2.2 — insert — ambiguity — undefined paths/methods rejected with `ERR_NOT_FOUND` (404) — implementation/app.py:36-43
- §2.3 — insert — ambiguity — non-numeric `limit`/`offset` falls back to defaults, out-of-range values clamped (never rejected) — implementation/response.py:59-68
- §2.3 — insert — ambiguity — list filters are exact-equality matches; sort ties on `created_at` break in insertion order — implementation/response.py:70, 82-87
- §2.5 — revise — ambiguity — `created_at`/`updated_at` are taken from the logical clock — implementation/db.py:71-83
- §2.5 — revise — ambiguity — `version` starts at 1 on creation — implementation/db.py:81
- §2.6 — revise — mismatch — dropped the "up to 4 decimal places" price claim (no precision limit enforced); pinned monetary inputs (`cost_basis_total`, income-posting/recoupment `amount`) stored exactly as supplied — implementation/validation.py:59-61, routes/positions.py:17,34
- §2.9 — insert — ambiguity — body-carried references (`fund_id`, `share_class_id`, etc.) resolve with `ERR_NOT_FOUND` (404), checked after schema-level body-shape checks — implementation/validation.py:160-165 and all create routes
- §3.1 — insert — ambiguity — `fiscal_year_end` accepts 02-29 — implementation/validation.py:39-48
- §3.1 — insert — ambiguity — missing per-type field (`shares`/`amount`) → `ERR_VALIDATION` (400); an inapplicable supplied field is ignored — implementation/routes/share_classes.py:78-92
- §3.2 — revise — mismatch — removed "unique across all securities" from `security_identifier`; no uniqueness check exists — implementation/routes/securities.py:22-36
- §3.2 — revise — mismatch — `cost_basis_total` "at two decimal places" → accepted and stored exactly as supplied — implementation/routes/positions.py:17
- §3.2 — revise — mismatch — price "stored as quoted at up to four decimal places" → stored exactly as quoted — implementation/routes/prices.py:20,60
- §3.3 — insert — ambiguity — a `REOPENED` record is not touched by the override cascade — implementation/services/navmath.py:328-341
- §3.4 — insert — ambiguity — a position whose security has no selected price under the record's variant contributes nothing to `gross_asset_value` — implementation/services/navmath.py:132-143
- §3.4 — insert — ambiguity — `provisional_nav_per_share` null when any held security lacks a `SUBMITTED`/`APPROVED` observation; zero `shares_outstanding` at recompute nulls `nav_per_share` and both previews — implementation/services/navmath.py:186-190, 241-244
- §3.5 — insert — ambiguity — every agreement representation (create/get/list) carries derived `status` and `recoverable_balance` — implementation/routes/waivers.py:31-36, 68, 77, 85
- §3.5 — insert — ambiguity — override-leg cap test runs only when the struck record is the class's first record; test skipped when the accrual base is zero or negative — implementation/services/navmath.py:285-286, 337-340
- §3.5 — revise — mismatch — ledger "positive two-decimal `amount`" → waiver amount at two decimals, recoupment amount exactly as supplied — implementation/routes/waivers.py:139-147
- §3.6 — insert — ambiguity — a first-record accrual row recomputed during a finalize/reopen advances `version` once for the recomputation and once for the status flip — implementation/routes/nav_records.py:136-142, 164-170 + services/navmath.py:227-232
- §3.6 — insert — ambiguity — the override cascade leaves the date's accrual rows in `POSTED` (unlike the reopen endpoint) — implementation/services/navmath.py:334-341
- §3.7 — revise — ambiguity — declaration rejected when `retained_income` is zero or negative (impl uses `<= 0`; rounding can push it slightly negative) — implementation/routes/distributions.py:47-50
- §3.7 — insert — ambiguity — `paid_at` is null until payment — implementation/routes/distributions.py:71, 128
- §3.8 — insert — ambiguity — a nonzero adjusted quantity never reopens an already-`CLOSED` position; only break reopening restores `OPEN` — implementation/routes/breaks.py:115-116, 140-141
- §3.9 — revise — ambiguity — fee contiguity measured against the latest `period_end` among prior DRAFT/APPROVED/PAID invoices — implementation/routes/fees.py:49-50
- §3.9 — insert — ambiguity — performance and trial-balance inputs are required query parameters; missing/malformed → `ERR_VALIDATION` (400) — implementation/routes/share_classes.py:102-104, funds.py:63, validation.py:168-187
- §3.9 — insert — ambiguity — filing born with `filed_at` null and `filed_after_deadline` false; submit-review does not change `prepared_by_user_id` — implementation/routes/filings.py:46-49, 76-87
- §3.9 — revise — mismatch — fiscal-close order pinned: the three `ERR_FISCAL_CLOSE_BLOCKED` gates (records → breaks → filings) are evaluated ahead of the clock check; MM-DD mismatch of `fiscal_year_end_date` → `ERR_VALIDATION` (400); fiscal year defined as the closed interval from the day after the prior year's fiscal-year-end (Feb 29 → Feb 28 in non-leap years) through the close date — implementation/routes/funds.py:92-139

Everything else in the implementation (endpoint set, role gating, validation pipeline ordering, state machines, all calculation formulas including per-position-round-first GAV, per-share-first distribution rounding, unrounded ADNA until final multiplication, strictly-greater cap breach, oldest-first recoupment waterfall, 5-day escalation rule, OCC/SoD plumbing, and all error codes/HTTP statuses) was already uniquely pinned by the PRD and left untouched.

---

## PIPELINE COMPLETE — task_1748_fund_administration_expense_accrual

- Scaffold: SCAFFOLD.yaml (918 lines) + SCAFFOLD_DIFFICULTY_DESIGN.yaml (666) + SCAFFOLD_CORNER_DESIGN.yaml (1117), clean lint
- PRD.md: 322 lines; PRD_FINALIZED.md: byte-identical (Step 8 found zero PRD silences at Step 7 sites); PRD_COMPLETED.md: 323 lines, +3,406 chars, 27 pins/revisions
- Tests: 83 (36 difficulty + 47 corner), all Design-tagged; 1 incoherent difficulty instance skipped at generation
- Step 7: 2 iterations; 3 test_suite fixes (fixture clock handling ×2, formula-constant slip ×1); 0 deletions; 0 implementation fixes
- Final stability: 83/83 passed in all 8 parallel rounds under per-test-server isolation

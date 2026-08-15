# Worklog — task_1331_partnership_k_1_preparation_investor

## Step 1: Create Task Directory — 2026-08-12T22:09:00.000Z

Task directory `tasks/task_1331_partnership_k_1_preparation_investor/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher; verified present on disk. Step 1 treated as DONE per instructions.

## Step 2: Generate Scaffold — 2026-08-12T23:05:00.000Z

Scaffold generation complete. All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_1331_partnership_k_1_preparation_investor/` and pass `scaffold_lint.py` with a clean verdict (verbatim: "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5." — 66 endpoints, 13 entities, 19 §1.8 instances, 57 active §1.9 instances, 636 recipe calls scanned).

**Design summary** (built fresh from the scenario; no sibling tasks consulted):

- **Profile**: compliance/audit primary + ledger-reconciliation secondary; flat topology with FK references; segregation-of-duties role model (FundTaxAdmin / TaxPreparer / TaxReviewer / InvestorServicesRep opaque, Investor entity-backed by Partner); layers: optimistic concurrency, dual-variant calculation, cascading side effects, derived-field reconciliation. Logical clock test endpoint with the mandated `2026-08-01T00:00:00Z` default.
- **Entities (13)**: Fund, TaxYear (cyclic OPEN→…→APPROVED→COMPLETED with amendment-driven reopen), Partner, CapitalAccountEvent (self-referential mirror-reversal event log), OwnershipTransfer, AllocationRun (+AllocationLine), SpecialAllocation, CompositeFiling (DRAFT↔FILED cycle), WithholdingRecord, K1Package (parallel prep_status × delivery_status dimensions), K1Amendment (IN_PREP↔IN_REVIEW loop), InvestorTicket.
- **Difficulty features, all 9 rules with ≥2 grounded instances**: dual variants — book capital vs tax basis (book-only 704(b) ADJUSTMENT + zero-floor spillover) and SAFE_HARBOR vs CURRENT_ACTUAL withholding; combinatorial formulas in modes (a) waterfall tiers, (b) composite per-partner-then-sum rounding (pinned 21008 vs forbidden 21007), (c) fee/discount evaluation order; cascades of depth 3 (amendment issue → supersede → replacement K1 → investor ticket) and depth 4 (transfer settle → events → balances → run STALE → K1 revert); priority conflicts state-vs-fiscal and safety-vs-temporal; inclusive boundaries (composite min-income, zero-balance withdraw); cross-entity gates (AllocationRun→TaxYear, OwnershipTransfer→Partner); half-open vs closed interval overlap semantics; compensating invariants on capital balance and category-total zero-sum. One OCC rule on `POST /funds/allocation-runs` (`expected_tax_year_version`, 412).
- **All formula-derived assert literals were executed in Python before being pinned** (waterfall split 3,712,000/10,858,667/5,429,333; withholding 904,588 vs 106,838; penalty 60,688; proration 1,822,000/1,828,000; etc.). Two replay bugs were caught and fixed during self-audit: admission dates predating the 2024 fixture year (zero-ownership proration would have zeroed the SAFE_HARBOR base), and ALLOCATION_SHARE lock-time postings flowing into a post-settle balance assertion.

## Step 3: Copy Shared Files — 2026-08-12T23:06:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1331_partnership_k_1_preparation_investor/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T23:30:00.000Z

All checks pass. The PRD is complete and verified.

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1331_partnership_k_1_preparation_investor/workspace/PRD.md` (340 lines)

**Structure:** §1 Introduction (2 paragraphs, business-context angle) → §2 Global Specifications (10 subsections: RBAC with identity prose for all 5 roles, verbatim §2.2, pagination, common resource properties, the logical clock, cents/basis-point precision, OCC, a 15-step ordered validation pipeline, append-only ledger principles, staleness/supersession cascades) → §3 Business Logic (9 subsections: fund/tax-year setup, partners & capital ledger, ownership transfers, proration/specials/allocation engine, lock-review cycle, composite filings, foreign withholding, K-1 generation/delivery/amendment, investor tickets) → §4 endpoint table (66 endpoints, 4 columns) → §5 error catalogue (32 errors, 2 columns). Document ends at §5 with no audit footer. The withheld design files were never opened.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 94 required, 94 present, 0 missing
- endpoints[].request_body: 55 required, 55 present, 0 missing
- endpoints[].query_params: 14 required, 14 present, 0 missing
- endpoints[].path_params: 13 required, 13 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 15 checked, 15 expressed in prose (§2.8 numbered pipeline, first-failure-wins ordering stated), 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (POST allocation-runs + expected_tax_year_version + ERR_STALE_TAX_YEAR_VERSION/412 all named; no other endpoint takes a version field), 0 missing
- state_machines[].transitions: 33 checked, 33 fully expressed (from/to states, preconditions paired with error ids, side effects incl. all cascade hops), 0 missing
- calculations[]: 8 checked, 8 fully expressed in precise prose (incl. BOOK_CAPITAL vs TAX_BASIS replay variants, pinned management-fee order, 365-day proration rationals, waterfall tiers with largest-remainder tie-break, per-partner-then-sum composite rounding, SAFE_HARBOR 110%/CURRENT_ACTUAL Q4-remainder, 5-month/500bps penalty cap, strict-greater lateness), 0 missing
- validations[] conditions: 15 checked, 15 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 66 checked, 66 expressed, 0 missing
- entities[].fields[] structured content: 94 checked, 94 reconstructible (defaults, enum values, computed-field derivations all stated), 0 missing
- sibling-branch symmetry: 8 groups checked (run kinds, withholding methods, balance variants, category tiers, cancel/remit/reconcile/answer sibling transitions), 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 664
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional precision checks: §2.2 matches `section-2.2-response-structure.md` byte-for-byte; no pseudocode operators (`==`, `>=`, `+=`, `floor(`, …) or fuzzy hedging words anywhere outside code fences; all 32 error IDs and all 77 enum/state values appear verbatim in backticks; §4 role assignments match the scaffold RBAC matrix exactly.

## Resume note — 2026-08-12T23:41:00.000Z

RESUME RUN: previous pipeline run was killed mid-flight after Step 4. Audit on resume: Steps 1–4 complete and valid (SCAFFOLD.yaml 1130 lines + lint clean, both design yamls present, PRD.md 340 lines matching the Step 4 report, INSTRUCTION.md copied). Steps 5 and 6 were killed mid-generation: `test_helpers/` held only `types.py`, `test_suite/` was empty, `workspace/implementation/` held only partial scaffolding (no `app.py`). All partial Step 5/6 artifacts were removed; Steps 5 and 6 are being regenerated from scratch. Steps 1–4 artifacts kept and reused (not regenerated).

## Step 5: Generate Unit Tests — 2026-08-13T00:20:00.000Z

All checks pass. Final summary of what was generated:

## Deliverables

**`test_helpers/`** (8 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1331_partnership_k_1_preparation_investor/test_helpers/`):
- `types.py` — 13 entity TypedDicts + 20 enums (statuses, partner/event/run kinds, etc.)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~60 methods, incl. `/_clock/set_current_utc`)
- `api_errors.py` — all 32 error IDs with PRD §5 HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*`, `parse_instant`, `find_line`, ledger invariants
- `factories.py` — payload factories (unique EIN counter for the fund-ein uniqueness rule)
- `constants.py` — withholding rates (3700/2100), safe-harbor 11000 bps, penalty 500 bps/5-month cap, SLA windows, canonical fund/partner/totals presets
- `test_users.py` — `TEST_USERS` shared constants + per-instance `make_*_headers` builders (Investor is entity-backed: `make_investor_headers(partner.id)`)
- `fixtures.py` — tiered composites: create/close/lock/approve walks, `setup_tax_year_with_locked_run`, `setup_approved_tax_year`, `setup_k1_generated`, `setup_k1_delivered` (SoD-threaded prep_1/rev_1), transfer create/confirm/settle, special-allocation propose+approve, withholding accrual, amendment walker

**`test_suite/`** — `conftest.py` + 11 test files, **94 tests**, all collecting cleanly under pytest.

## Coverage audit (automated, `/tmp` script)
- Queue A: all **19 difficulty instances** have ≥2 tests each (38 tests) — zero shortfall.
- Queue B: **56 of 57 non-stub corner instances** covered; all 5 `excluded_because` stubs correctly untranslated. The one gap is deliberate: `Corner/errors/all_error_codes_triggerable` is a coverage-note instance with no API calls and no observable assertion — it fails the PRD-first filter (no verbatim rule to assert), so it was skipped without placeholder, per the Core rule.
- Every test docstring ends with exactly one resolving `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line, and every quoted PRD citation survives whitespace-normalized literal grep of PRD.md (0 problems).

## Key adjudications
- **Recipe repairs for PRD-consistency** (asserted values kept verbatim from the index; the setup chains were missing a contribution the pre-computed numbers presuppose): added LP1's 60000000 contribution (2025-01-01) in `withholding_safe_harbor_vs_current_actual` and `withholding_q4_holds_floor_remainder`, and LP2's 30000000 contribution in `transfer_settle_four_hop_cascade`. Without these, a PRD-faithful implementation would compute different numbers than the index asserts.
- **Priority-pair tests kept**: PRD §2.8 explicitly pins the validation pipeline order ("rejected with the first failing check in the order below"), so state-beats-stale and safety-beats-temporal are uniquely derivable, not silence-pattern skips.
- **Two relaxations for two-reader ambiguity**: fund-creation test asserts `version` presence/type rather than the literal `1` (PRD never pins the initial version), and `k1_delivery_deadline` is compared as a parsed instant rather than an exact string (serialization format isn't pinned).
- Clock is treated as arbitrarily settable (many instances set it before the 2026-08-01 startup default; PRD does not restrict direction).

## Step 6: Generate Implementation — 2026-08-13T00:25:00.000Z

Both fresh boots are clean and the store starts empty per process. The implementation is complete and verified.

## Summary

Implemented the Partnership K-1 Administration API in Python + Flask at `/home/ubuntu/github/CodingPRD/tasks/task_1331_partnership_k_1_preparation_investor/workspace/implementation/`.

**Files:**
- `start.sh` — executable foreground launcher; guarded dependency install (`pip install` only when flask missing, so per-test reboots are fast); `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask
- `app.py` — Flask entry point, error handlers (ApiError → scaffold envelope, 404/405 → `ERR_NOT_FOUND`), global request lock for thread safety
- `db.py` — in-memory store (13 entity dicts), logical clock starting exactly at `2026-08-01T00:00:00Z`, never wall-clock; no seeding at startup
- `util.py` — response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination `limit/offset/total_count/has_more` with defaults 10/0/1–100), `round_half_up` via Decimal, ISO date/datetime parsing, 3-fractional-digit timestamps
- `auth.py` — `X-User-ID`/`X-User-Role` validation (`ERR_MISSING_AUTH_CONTEXT` 400), role gating (`ERR_FORBIDDEN_FOR_ROLE` 403), Investor entity-backed ownership checks
- `services.py` — ledger replay (book capital vs tax basis with ADJUSTMENT book-only skip and zero-floor spill into `excess_distribution_gain_cents`), 365-day ownership proration with exact `Fraction` weights, allocation engine (special tier → pro-rata for ORDINARY/INTEREST; PREFERRED/CATCHUP/RESIDUAL waterfall for CAPITAL_GAIN with per-partner round-half-up + largest-unrounded-share residual reconciliation, conservation exact), composite tax (per-partner-then-sum), foreign withholding (SAFE_HARBOR 110% prior-year vs CURRENT_ACTUAL with Q4 floor-remainder), penalty calc (500 bps/month, 5-month cap), all cascades (staleness, K1 revert, bubble-up completion, amendment issue chain), serializers with lazy clock-derived fields (`is_escalated`, `is_late`, `current_ownership_pct_bps`)
- `routes.py`, `routes_transfers_alloc.py`, `routes_state_wh.py`, `routes_k1.py` — all 40+ endpoints including `/_clock/set_current_utc`, with the PRD §2.8 validation pipeline ordering (auth → role → body → path existence → state → SoD → foreign-cap → tax-year windows → overlap → uniqueness → cross-fund → ledger guards → allocation prerequisites → aggregate bounds → non-empty sets)

**Verification:** 5 smoke suites (~90 assertions) run against fresh server boots, covering: fee discount threshold (strict <), duplicate ein/tax-year, distribution guard + reversal mirrors, cross-fund 409, SoD 409s, OCC `ERR_STALE_TAX_YEAR_VERSION` 412, provisional annualization (365/day-of-year), supersession, lock bubble-up to ALLOCATED, exact conservation of allocation lines, special allocation mechanics, K1 generation order/uniqueness/cascades (Q4 withholding auto-accrual, DRAFT filing recompute), deliver-at-deadline boundary (`is_late` strict >), bounce/resend, COMPLETED bubble-up, amendment issue chain (supersede → replacement gen+2 → auto ticket → COMPLETED→APPROVED), transfer settle cascade (transferred capital = book at effective date × pct / prior-segment ownership, runs→STALE, K1s→GENERATED), foreign ownership cap (inclusive), transfer window overlap (closed interval), waterfall numbers (pref scaling, catchup cap, carry split, mechanism labels), proration with mid-year admission and settled transfer, SAFE_HARBOR/CURRENT_ACTUAL withholding math, penalty months-late math, composite eligibility/rounding, investor scoping, and pagination meta.

One judgment call worth noting: withdrawing a partner that has both in-flight K1s and nonzero capital returns `ERR_INVALID_STATE_TRANSITION` (state check, priority 5) before `ERR_PARTNER_CAPITAL_NOT_ZERO` (priority 15), following the PRD §2.8 global pipeline ordering.

## Resume note — 2026-08-13T00:28:46.000Z

RESUME RUN #2: previous pipeline run was killed after Step 6 completed (worklog has entries through Step 6). Audit on resume: Steps 1–6 complete and valid — SCAFFOLD.yaml 1130 lines + both design yamls, PRD.md 340 lines, INSTRUCTION.md, test_helpers/ (9 files) + test_suite/ (11 files, 94 tests), workspace/implementation/ complete (app.py ends with server run; 9 py modules + start.sh). No results.*.json files present — Step 7 never ran. No PRD_FINALIZED.md / PRD_COMPLETED.md — Steps 8–9 pending. Resuming pipeline at Step 7.

## Resume note — 2026-08-13T00:35:00.000Z

RESUME RUN #3: resume run #2 wrote the note above and was killed before Step 7's subagent produced any results (still no results.*.json files). Re-audit confirms Steps 1–6 artifacts remain complete and valid (test_suite 94 tests across 11 files; implementation 11 py modules + start.sh; app.py ends with server run). Resuming pipeline at Step 7.

## Step 7: Run Tests and Iterate — 2026-08-13T00:36:17.000Z

## Summary

- **Iterations run:** 1 (single 8-round parallel stability sweep, `--isolation per-test-server`, all rounds ran to completion).
- **Result:** All 8 rounds passed — 94/94 tests, 0 failed, 0 errors in every round. The union of failing tests across rounds is empty; no flakiness signal was observed.
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `implementation/`:** none.

The existing implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1331_partnership_k_1_preparation_investor/workspace/implementation/` is already fully compliant with the test suite under per-test-server isolation, so no diagnostic or remediation work was required.

## Step 8: Finalize PRD — 2026-08-13T00:36:17.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline, so `PRD.md` already determined every behavior the implementation exhibits. No subagent spawned.

## Step 9: Complete PRD — 2026-08-13T00:52:49.000Z

Done. `PRD_COMPLETED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1331_partnership_k_1_preparation_investor/workspace/PRD_COMPLETED.md`.

**Source vs output**: source `PRD.md` (340 lines, no `PRD_FINALIZED.md` existed) → `PRD_COMPLETED.md` (340 lines; +4,712 chars; 30 paragraphs revised inline, zero sections added/removed).

**Counts**: 22 ambiguity-pins, 4 mismatch-revisions (26 edited passages total).

Changes:

- §2.3 — insert — ambiguity — `limit`/`offset` out-of-range values clamp to nearest bound (offset floors at 0); non-integer values → `ERR_INVALID_REQUEST` — util.py:88-107
- §2.3 — insert — ambiguity — `has_more` true exactly when `offset` + returned items < `total_count` — util.py:108-114
- §2.3 — insert — ambiguity — `created_at` sort ties resolve by creation order (earliest-created first) — util.py:118-119, db.py:45-53
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — db.py:45-53
- §2.5 — insert — ambiguity — clock-set replaces the clock unconditionally; missing/unparsable `to_iso8601` → `ERR_INVALID_REQUEST` — routes.py:63-73
- §2.7 — insert — ambiguity — `ERR_STALE_TAX_YEAR_VERSION` check fires in the §2.8 pipeline immediately after path existence, before all later checks — routes_transfers_alloc.py:221-225
- §2.8 item 2 — insert — ambiguity — Investor ownership checks needing the loaded resource (K-1 packages, tickets) resolve it first (404 before 403); partner-record and ticket-creation checks compare the path/body identifier directly (403 before 404) — routes.py:280-285, routes_k1.py:88-94,170-174,403-409,440-446
- §2.8 item 3 — insert — ambiguity — basis-point *rates* (hurdle/catchup/carry/cap/fee/discount/composite) bounded 0..10000, distinct from shares at 1..10000 — routes.py:86-92, routes_state_wh.py:136-138
- §2.8 item 4 — insert — ambiguity — body-referenced identifiers (`fund_id`, `partner_id`, `tax_year_id`, `k1_package_id`) must also resolve, else `ERR_NOT_FOUND` — routes.py:133, routes_k1.py:225, etc.
- §2.8 item 8 — revise — mismatch — composite filing is rejected while `OPEN` or `BOOKS_CLOSED` (not `COMPLETED` — filing in a `COMPLETED` year is allowed per impl and §3.6) — routes_state_wh.py:210-212
- §2.8 item 11 — revise — mismatch — special-allocation creation added to the cross-fund guard list (impl enforces partner/tax-year same-fund there) — routes_state_wh.py:34-35
- §2.10 — insert — ambiguity — multiple `LOCKED` `FINAL` runs may coexist (supersession only hits `COMPUTED`/`STALE`); "the locked `FINAL` run" means highest `run_seq` — services.py:302-308
- §3.1/§3.2 admission — insert — ambiguity — `residency_state` must be exactly two uppercase alphabetic characters — routes.py:253-254
- §3.2 — insert — ambiguity — `current_ownership_pct_bps` is zero while `admission_date` is still in the future relative to the clock — services.py:95-99
- §3.2 — insert — ambiguity — the capital-event `COMPLETED`-year window check consults the tax year of the partner's fund whose calendar year contains the `effective_date` — routes.py:343-347
- §3.2 reversal — insert — ambiguity — the mirror's `memo` comes from the reversal request body (null when omitted), not copied from the original — routes.py:393-406
- §3.3 settlement — insert — ambiguity — denominator pinned as the share in effect on the day before the `effective_date`; if that share is zero, `transferred_capital_cents` is zero — routes_transfers_alloc.py:168-173
- §3.3 settlement — insert — ambiguity — cascade `TRANSFER_OUT`/`TRANSFER_IN` events carry `tax_year_id` of the fund's tax year containing the `effective_date`, or null when none exists — routes_transfers_alloc.py:175-184
- §3.4 — revise — mismatch — proration participants are partners `ACTIVE` at computation time (impl never includes `WITHDRAWN` partners), not "ACTIVE during the year plus WITHDRAWN after year start" — services.py:195-196, routes_transfers_alloc.py:235-238
- §3.4 — insert — ambiguity — transfer `effective_date` ties break by `created_at` then creation order; a same-date admission applies before transfers — services.py:124-144
- §3.4 — insert — ambiguity — all-zero proration weights fall back to equal-weight split; residual-cent tie chain extended with creation order after `created_at` — services.py:168-179
- §3.4 — insert — ambiguity — `PROVISIONAL` computation in any status past `BOOKS_CLOSED` is rejected with `ERR_TAX_YEAR_NOT_BOOKS_CLOSED` — routes_transfers_alloc.py:227-230
- §3.4 waterfall — insert — ambiguity — zero/negative capital-gain total zeroes preferred and catch-up pools (whole total falls to residual); no `GENERAL` participants skips catch-up; single-class funds give that class the entire remainder — services.py:252-285
- §3.4 — revise — mismatch — `applied_mechanism` pinned: `SPECIAL` iff the partner received a special-tier assignment (else `PRO_RATA`) for `ORDINARY`/`INTEREST`; for `CAPITAL_GAIN` the tier with the largest absolute contribution, ties toward `PREFERRED` then `CATCHUP` then `RESIDUAL` (replaces the vague "RESIDUAL used when the residual tier produced the line") — services.py:236-243,292-293
- §3.4 — revise — mismatch — special-allocation approval conditions reordered to impl: segregation-of-duties → tax-year window → overlap (matches §2.8 priority 6 < 8 < 9) — routes_state_wh.py:81-102
- §3.5 lock — insert — ambiguity — one `ALLOCATION_SHARE` event is posted per partner with lines in the run, even when the summed amount is exactly zero — services.py:363-379
- §3.5 reopen — insert — ambiguity — reopen is blocked only by packages *currently* `DELIVERED`; a delivered-then-`SUPERSEDED` package does not block — routes.py:230-233
- §3.6 — insert — ambiguity — `state_code` must be exactly two uppercase alphabetic characters — routes_state_wh.py:134-135
- §3.7 — insert — ambiguity — `CURRENT_ACTUAL` accrual requires a `LOCKED` non-`STALE` `FINAL` run (else `ERR_ALLOCATION_NOT_LOCKED`/`ERR_ALLOCATION_STALE`); `SAFE_HARBOR` requires none; bulk response is an array ordered by partner `created_at` — routes_state_wh.py:258-275
- §3.7 — insert — ambiguity — remittance `amount_cents` must be a positive integer, else `ERR_INVALID_REQUEST` — routes_state_wh.py:313-315
- §3.8 — insert — ambiguity — `line_snapshot` beginning/ending capital pinned: book replay over all event types (including `ALLOCATION_SHARE`) effective on/before Jan 1 / Dec 31 of the tax year — services.py:467-477
- §3.8 — insert — ambiguity — K-1-generation cascade skips the Q4 `CURRENT_ACTUAL` accrual silently when that partner/tax-year/quarter record already exists — routes_k1.py:72-79
- §3.8 — insert — ambiguity — package approval conditions evaluated in narrative order (SoD → snapshot run → year `APPROVED`) — routes_k1.py:134-141
- §3.8 — insert — ambiguity — report-bounced `reason` accepted but not persisted; resend without `delivery_method` keeps the recorded method — routes_k1.py:182-212
- §3.8 issuance — insert — ambiguity — with no `LOCKED` `FINAL` run at issuance, the replacement package carries the amended package's `line_snapshot` and `run_id` unchanged; auto-created ticket subject is "Amended K-1 issued" — routes_k1.py:307-346
- §3.9 — insert — ambiguity — ticket-reopen `reason` accepted but not persisted — routes_k1.py:440-451

Not pinned (out of PRD scope, framework-level): the `GET /` health response, the 404/405 fallback handlers, the `ERR_INTERNAL` 500 wrapper, and the 24-character `api_request_id` suffix (PRD pins only the `req_` prefix, which impl honors).

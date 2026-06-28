# Worklog — task_0507_real_estate_crowdfunding

## Step 1: Create Task Directory — 2026-06-26T08:22:40.000Z

Created reserved task directory `tasks/task_0507_real_estate_crowdfunding/` with `workspace/` subdirectory. Index 0507 pre-allocated (no scan performed). Verified `./INSTRUCTION.md` exists for Step 3 copy.

## Step 2: Generate Scaffold (Expert tier) — 2026-06-26T08:52:21.000Z

Generated the complete Expert-tier scaffold for **task_0507_real_estate_crowdfunding** (Fundrise-style eREIT crowdfunding). All three files written and `scaffold_lint.py` returns `VERDICT: clean lint`.

**Complexity profile:** primary archetype `compliance_audit` + secondary `quota_allocation`; layers = dual-variant calculation, cascading side effects, optimistic concurrency, derived-field reconciliation, rate/threshold triggers; topology hybrid; state-machine shape branching/cyclic; role model segregation-of-duties; immediate consistency.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **11 entities:** Fund, ShareClass, Project, Investor, Subscription, Holding, Valuation, Distribution, DistributionAllocation, RedemptionRequest, TaxDocument.
- **7 state machines:** Fund, ShareClass (cyclic OFFERING↔SUSPENDED), Project, Investor (cyclic APPROVED↔PENDING), Subscription (branching SETTLED/REVERSED/CANCELLED), Distribution, RedemptionRequest (cyclic QUEUED↔DEFERRED + branch FULFILLED/REJECTED).
- **2 concurrency rules** (OCC, 412): subscription-create-stale-fund (`expected_fund_version`), redemption-create-stale-holding (`expected_holding_version`).
- **11 calculations:** nav_per_share, fund_shares_outstanding, subscription_shares (provisional vs final dual-variant), ach_fee (circular-dependency mode-c), suitability_cap, ytd_invested, penalty_age_quarters, early_withdrawal_penalty (tiered), dividend_allocation (round-per-holding-then-sum mode-b), redemption_cap, tax_document_totals.
- **18 validations** (priority-ordered, auth→existence→state/OCC→business safety/referential/constraint/temporal/fiscal).
- **50 endpoints** (count above the 20–32 band, driven by mandatory FK reverse-reachability GETs; includes a `/_clock/set_current_utc` test-driving endpoint with default `2026-01-01T00:00:00Z`).
- **18 error codes**, all referenced by validations/concurrency and exercised in the design files.
- **5 roles:** FundManager, ComplianceOfficer (segregation of duties pair), Operator (opaque), Investor (entity_backed), Anonymous.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rules × 2 = **18 instances**, all with executable `setup_api_calls`/`trigger` chains and precomputed literal asserts (e.g. shares 400.0000, total_paid 150c vs 149c divergence, ach_fee waiver 0/total 2481000, penalty 4100/net 200900, DRIP shares_outstanding 99.1500, capital/shares/ytd conservation to 0).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **38 active instances** across 8 sections + **4 `excluded_because:` stubs** referencing §1.8 instances.

**Key correctness fixes during generation:** added `Subscription.holding_id` (computed at settle) so cascade-created Holdings are discoverable from the settle response; corrected ~17 OCC `expected_*_version` captures that were sourcing `$.data.version` from the wrong entity by inserting explicit `GET /funds` / `GET /holdings` reads; set `api_prefix: /` so all reverse-reachability GETs resolve; reframed one priority-conflict instance into a genuine same-endpoint OCC-vs-referential conflict.

## Step 3: Copy Shared Files — 2026-06-26T08:52:21.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0507_real_estate_crowdfunding/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T08:59:16.000Z

Generated the PRD at `workspace/PRD.md` for the **Real Estate Crowdfunding API** (Fundrise-style eREIT/fund platform). ~284 lines.

**Inputs read:** Only `SCAFFOLD.yaml` (plus the skill spec, the §2.2 verbatim source file, and the example PRD reference). Did **not** open `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`.

**Structure (~285 lines):**
- §1 Introduction — compliance framing, system goals, money/clock note
- §2 Global Specs — 9 subsections: RBAC (5 roles + identity translation), §2.2 verbatim response envelope, pagination, common properties/versioning, nested retrieval ordering, OCC on the two capital-sensitive creates, monetary precision/rounding, capital conservation & NAV reconciliation, logical clock
- §3 Business Logic — 9 subsections by entity lifecycle/process: funds/valuations/NAV, share classes & projects, investor onboarding & suitability, subscribing & ACH settlement, holdings & DRIP, distributions & DRIP, redemptions (queue/sweep/penalty/wind-down), tax documents, validation-ordering subsection
- §4 Endpoint table (all 51 endpoints) and §5 Error catalogue (18 errors)

**Hard Contracts — all PASS:** Field-Name Coverage (63 identifiers, 0 missing); Rule Coverage (both OCC rules, all calculations as precise prose, all state transitions/cascades/wind-down, validation priority ordering, all 18 error IDs); §3 Path Purity (0 slash-prefixed, 0 bare HTTP methods). §2.2 verified byte-identical to source.

## Step 5: Generate Unit Tests — 2026-06-26T09:16:23.000Z

Generated complete test infrastructure for `task_0507_real_estate_crowdfunding`, translating exclusively from the two design indices.

**Test helpers** (`test_helpers/`, 9 files): types.py (9 status/enum types + TypedDicts for all 11 entities), api_client.py (one method per PRD §4 endpoint incl `_clock/set_current_utc`), api_errors.py (18-error enum + HTTP status map), assertions.py (per-entity, common-vs-append-only branching), factories.py (input-only payload factories, unique-email helper), constants.py (penalty tiers, ACH constants, caps, clock default), test_users.py (opaque shared headers + entity-backed make_investor_headers(id)), fixtures.py (composite setup: clock, fund/share-class/investor creation, settle pipeline returning cascade-created holding, valuation advancement, queued-redemption + 3-holding-distribution scaffolds), __init__.py.

**Test suite** (`test_suite/`, conftest + 9 files): **74 test functions**, each carrying exactly one verbatim `Design:` tag.

**Coverage:** Queue A (Difficulty): all **18** instances translated, 2 tests each = 36 tests, 0 skipped. Queue B (Corner): all **38** non-stub instances translated, 1 test each = 38 tests, 0 skipped. The 4 `excluded_because:` stubs not translated; all 4 cross-references verified to resolve to real difficulty instances.

**Audits passed:** 74 tests / 74 Design tags (no untagged/dual-tagged/dangling); all PRD docstring quotes verified verbatim; no skip/xfail/skipif; no scaffold/Table/§ leakage; all files compile; import graph acyclic. One faithfulness fix: dividend-domain test of `early_withdrawal_penalty_tier_vs_dividend_per_share_allocation` corrected to redeem 200 shares before paying (holding 1000→800), matching asserted total_paid_cents == 1200.

## Step 6: Generate Implementation — 2026-06-26T09:16:23.000Z

Built complete Python + Flask implementation at `workspace/implementation/` (21 files).

**Files:** start.sh (foreground; reads $PORT default 10000, binds 0.0.0.0, guards pip install on cheap `import flask`, exec app.py), requirements.txt (flask==3.0.3), app.py (blueprint registration, envelope error handlers, db.reset() at boot), db.py (in-memory dict stores for 11 entities, monotonic counters, logical clock default 2026-01-01T00:00:00Z), errors.py (18-entry error→status catalogue), response.py (meta/response_type/data envelope, req_ IDs, ISO-8601 UTC 3-digit), middleware.py (X-User-ID/X-User-Role auth + RBAC), services/ (calc.py Decimal ROUND_HALF_UP, domain.py lookups + recompute cascades, serialize.py, validate.py, paginate.py), routes/ (funds, investors, subscriptions, holdings, distributions, redemptions, clock).

**Coverage:** all ~52 §4 routes with pagination (limit 1–100 default 10, offset); 7 state machines incl. wind-down cascade and investor revoke cycle; 11 calculations (nav par 1000 bootstrap, ach_fee waiver order/threshold 2.5M, suitability_cap 10% of max(income,net_worth), 4-tier penalty 300/200/100/0 bps, dividend round-per-holding-then-sum DRIP-gated, redemption_cap 5% total_capital, tax_document_totals CASH/DRIP split + REIT→1099-DIV/PARTNERSHIP→K-1); both OCC rules (expected_fund_version→412 ERR_STALE_FUND_VERSION, expected_holding_version→412 ERR_STALE_HOLDING_VERSION); validations ordered per §3.9; capital-conservation + NAV reconciliation recompute after every settle/reverse/redeem/DRIP.

**Confirmation:** start.sh reads $PORT, binds 0.0.0.0, foreground via exec. In-memory only — no SQLite/disk/seeding; boots empty (verified total_count: 0). All modules compile; end-to-end smoke tests pass. Defensive note: drip_shares guards NAV==0 to avoid div-by-zero, returns 0 reinvested shares.

## Step 7: Run Tests and Iterate — 2026-06-26T09:38:00.000Z

Clean 8-round parallel sweep. All 8 rounds pass 74/74 (independently re-confirmed by orchestrator after subagent cleaned up its results files).

**Iterations run:** 2 (initial diagnostic sweep → fixes → confirming sweep). Final state: all 8 parallel rounds pass 74/74.

**Root cause (single systemic issue):** All 12 failing tests shared one defect rooted in the difficulty/corner scaffold design. The scaffold's setup steps assumed "settle F cents at NAV 1000 → F/1000 shares with NAV staying 1000". But PRD §3.1 unambiguously defines `nav_per_share_cents = (gross_asset_value_cents − total_liabilities_cents) / shares_outstanding`, recomputed after every settlement, while `gross_asset_value_cents` is moved *only* by a valuation (never by settlement). So NAV stays at par 1000 only when `gross_asset_value == shares_outstanding × 1000`. The test setups violated this, causing NAV to spike (e.g. 99,000/33 = 3000), collapse to 0 (gross=0 ÷ shares → division-by-zero on the next settle → `ERR_INVALID_REQUEST`), or inflate redemption gross past the PRD-required 5% quarterly cap (`ERR_REDEMPTION_CAP_REACHED`). The implementation was PRD-faithful throughout — these were STEP 2 test-precondition bugs.

**Tests deleted:** None. Every failing assertion traced verbatim to PRD §3.1/§3.4/§3.6/§3.7 and was uniquely derivable; only the setups were wrong.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` → `setup_three_holdings_for_distribution`: rewrote to create the fund at `gross_asset=0` and post a peg valuation (`gross = current_shares × 1000`) before each subsequent settle, holding the NAV at par 1000 as capital enters — a PRD-faithful way to reproduce the intended "three 33-share holdings at NAV 1000" precondition. Fixed `test_distribution_pay_drip_chain_mints_shares_and_recomputes_fund`, `test_distribution_pay_drip_increases_holding_shares`, and `test_dividend_round_per_holding_then_sum_three_holdings`.

**Fixes applied to `test_suite/` (setup-only; all assertions preserved or kept faithful to the same PRD rule):**
- `test_01_pricing_and_fees.py`: NAV-divergence test (`gross 100M → 1M` so post-settle NAV = 1000); annual-cap-at-cap test (`gross 0 → 1M` to avoid NAV→0 div-by-zero on the second settle); penalty-tier2 force-fulfill (scaled to 5M sub / 250k cap so the 205k redemption fits the 5% cap); penalty-tier 4 and <4 quarter tests (scaled to 2M sub / 100k cap for the 100k redemptions); dividend-per-share-payout test (redeem 40 not 200 shares to fit the 50k cap; assertion updated to the same round-per-holding rule, 1440).
- `test_04_redemption_caps_and_invariants.py`: second-force-fulfill balance test (added a second 11M settle to lift total_capital to 12M / cap 600k so the 600-share R1 fulfills and the *balance* check — not the cap — blocks R2, matching the test's stated intent).
- `test_07_calculations_and_validations.py`: penalty-tier1 300bps test (scaled to 3M sub / 150k cap, valuation pegged to NAV 1025); zero-share-exclusion test (`gross 0` with peg valuations; second holding sized to 50 shares so its full redemption gross 50k fits the cap).

**Fixes applied to `implementation/`:** None — the implementation was PRD-faithful and required no changes.

## Step 8: Finalize PRD — 2026-06-26T09:41:34.000Z

Produced `workspace/PRD_FINALIZED.md`, **byte-identical to PRD.md** (284 lines, 0% delta, 0 changes). Step 8 was run (not skipped) because the Step 7 diff had non-zero test_suite/ and test_helpers/ fixes, but those were all test-precondition (fixture/setup) bugs where the implementation was already PRD-faithful — none exposed a PRD silence or PRD/impl mismatch.

Subagent traced each Step 7 site to implementation and confirmed existing PRD prose already uniquely determines the behavior (NAV formula + recompute triggers §3.1/§2.8; annual suitability cap §3.4; ACH fee pinned waiver order §3.4; four-tier penalty §3.7; 5% quarterly redemption cap + force-fulfill §3.7; total_paid_cents per-holding-round-then-sum + eligibility ordering §3.6). Performed mandatory NO-NEW-MISMATCH enumeration for three candidate silences (drip_shares at NAV=0; redemption cost_basis proportional reduction; sweep deferral on insufficient shares) and rejected all three — each either lacks a Step 7 trace (HARD SCOPE) or pinning it would risk a new mismatch against parallel paths. No edits committed.

## Step 9: Complete PRD — 2026-06-26T09:49:12.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation completeness scan, starting from `PRD_FINALIZED.md`.

**Line counts:** 284 → 284 (unchanged). **Char counts:** 46,394 → 48,914 (delta **+2,520**).

**Counts:** 11 changes total — 10 ambiguity-pins, 1 mismatch-revision (all silence-filling inserts).

**Per-change list:**
- §2.1 (RBAC) — insert — only the four operational roles authenticate; `Anonymous`/unrecognized → `ERR_UNAUTHENTICATED` — middleware.py:6,17
- §2.3 (Pagination) — insert — out-of-range limit/offset silently clamped; non-integer → `ERR_INVALID_REQUEST` — services/paginate.py:30-42
- §2.9 (Logical Clock) — insert — clock-set returns HTTP 200 with empty `data` object — routes/clock.py:32
- §3.1 (Fund report) — insert — report shape: fund fields top-level + `projects` array ordered by creation asc — routes/funds.py:94-102
- §3.4 (Subscribe) — insert — provisional share count not persisted; settled_nav/shares_allocated/total_charged/tax_year/holding_id null until settle — routes/subscriptions.py:55-69
- §3.4 (Settle) — insert — new holding's drip_elected taken from subscription; existing holding untouched — routes/subscriptions.py:139-148
- §3.4 (Reverse) — insert — reversal with shares_owned < shares_allocated rejected with `ERR_INVALID_STATE` — routes/subscriptions.py:206-207
- §3.6 (DRIP) — insert — NAV==0 degenerate: drip_shares=0, nothing reinvested — services/calc.py:117-121
- §3.7 (Redemption create) — insert — gross/penalty/net_proceeds/penalty_tier_rate_bps null until fulfillment — routes/redemptions.py:48-58
- §3.7 (Sweep) — insert — insufficient-share holding deferred (not just cap-exceeding); sweep + open-window return fund (200) — routes/redemptions.py:192-218
- §3.7 (Fulfillment cascade) — insert — proportional cost-basis reduction (round-half-up cost_basis × shares_requested / shares_owned); first_acquired_seq cleared to null on empty — routes/redemptions.py:111-121
- §3.8 (Tax documents) — insert — distribution year = integer parsed from period_label up to first hyphen — routes/investors.py:134,154-159

---

## PIPELINE COMPLETE — 2026-06-26T09:49:12.000Z

All 9 steps finished. Final state: **74/74 tests pass across all 8 parallel stability rounds** (independently re-confirmed by orchestrator). Implementation required 0 fixes (PRD-faithful from generation); all Step 7 fixes were test-fixture preconditions. Final artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/, test_suite/ (74 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/, results.{1..8}.json}.

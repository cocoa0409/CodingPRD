# Worklog — task_0493_tax_lien_certificate

## Step 1: Create task directory — 2026-06-25T02:34:57.000Z

Created `tasks/task_0493_tax_lien_certificate/` with `workspace/` subdir (pre-assigned path; no auto-scan/auto-increment). Scenario: Tax Lien Certificate Sale & Redemption. Difficulty tier: Expert (to be passed to scaffold-generator only).

## Step 2: Generate scaffold (Expert tier) — 2026-06-25T02:56:09.000Z

Generated the three Expert-tier scaffold artifacts for **Tax Lien Certificate Sale & Redemption** at `tasks/task_0493_tax_lien_certificate/`. All three files parse and `scaffold_lint.py` reports **`VERDICT: clean lint`** (0 violations across 565 scanned calls).

**Complexity profile:** primary archetype compliance/audit, secondary ledger-reconciliation; layers = optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers, scheduled/deferred actions, derived-field reconciliation; segregation-of-duties role model; compound state-machine shape; immediate consistency.

**Entities (12):** County, Parcel, Investor, TaxSale, SaleListing, Bid, Certificate, SubsequentTax, Redemption, Assignment, DeedApplication, SurplusDistribution.

**State machines (5):** TaxSale (DRAFT→OPEN→CLOSED→SETTLED), SaleListing (LISTED→{SOLD,STRUCK_OFF,WITHDRAWN}), Bid (PLACED→{WON,LOST,REFUNDED}), Certificate (ACTIVE↔FORECLOSURE_PENDING cycle, branching to REDEEMED/DEEDED), DeedApplication (FILED→{AWARDED,CANCELLED}). Non-linear shapes: certificate foreclosure revision loop + deed-application fork.

**Calculations (6):** award_winner (bid-down vs premium variants), redemption_payoff (simple vs with-filed-deed-cost, round-per-component-then-sum pinned), certificate_position (frozen minimum_bid snapshot), surplus_distribution (waterfall), investor_escrow (hold/commit/release ledger), face_interest_days (floor-day boundary). 3 concurrency rules (OCC on SaleListing and Certificate version).

**Endpoints (59):** full business surface plus flat reverse-reachability GET aliases for every FK, plus `/_clock/set_current_utc` (default `2026-01-01T00:00:00Z`). **Error catalog: 18 codes.** **RBAC roles (3):** CountyTreasurer (opaque), Investor (entity_backed:Investor), Auditor (opaque).

**§1.8 design:** 18 instances (9 rule_ids × 2). **§1.9 design:** 42 instances (37 active + 5 `excluded_because` stubs, all citing valid §1.8 instance names). All 60 instance names unique; numeric asserts pre-computed literals; payoffs 163065 / 135082 / 174545, minimum_bid 204682, surplus 45318 with the 204682+45318=250000 conservation invariant.

Fix log: quoted list-indexed JSONPaths and converted corner-file inline `grounds:` lists to block form (YAML parse breakers); removed two dead-end enum values (Certificate.status=CANCELLED, SubsequentTax.status=CANCELLED) for enum closure.

## Step 3: Copy INSTRUCTION.md — 2026-06-25T02:56:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0493_tax_lien_certificate/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-25T03:02:00.000Z

PRD generated at `workspace/PRD.md`. **Structure:** 273 lines, 5 top-level sections. §2 has 11 domain-derived subsections (Access Control, Response Structure, Pagination, Logical Clock, Common Properties, Monetary Precision/Day-Count/Interest, OCC, Hierarchical Consistency, Nested Retrieval/Referential Scope, Validation Ordering, Segregation of Duties). §3 has 11 lifecycle-staged subsections; §4 endpoint table 59 rows; §5 error table 18 rows.

**Handling:** 12 entities (field names woven into narrative, no schema tables; Parcel status/active_certificate_id framed as derived). 5 state machines with from/to states, preconditions+error IDs, cascade side-effects in prose (§3 path-pure). 6 calculations as precise business prose (award-winner both variants + earliest-bid tie-break, redemption payoff all 7 components with per-component-round-then-sum, frozen minimum-bid snapshot, surplus waterfall, escrow ledger, floor-of-seconds/86400 day count). 18 errors tied to triggers + §5 table. 15 validations with full priority ordering in §2.10. 3 OCC rules (expected_listing_version/expected_certificate_version, ERR_STALE_VERSION 412). 3 roles (Investor entity-backed; CountyTreasurer/Auditor opaque).

**Hard Contract reports:** Contract 1 (Field-Name Coverage) 71/71 PASS; Contract 2 (Rule Coverage) PASS; Contract 3 (§3 Path Purity) 0 slash/method tokens PASS. Did not open either withheld design file.

## Step 5: Generate unit tests — 2026-06-25T03:19:00.000Z

Generated complete test infrastructure, translating only the two design indices (no freelance scaffold-walking).

**test_helpers/ (9 modules):** types.py (status/role enums, TypedDicts for all 12 entities w/ common fields), api_client.py (one method per endpoint), api_errors.py (ApiErrorId enum + HTTP status map), assertions.py (per-entity + surplus-conservation invariant), factories.py (input-only payload factories), constants.py (accrual/rate constants from PRD §2.6/§3.1), test_users.py (opaque CountyTreasurer/Auditor + make_investor_headers(id) entity-backed), fixtures.py (composite tiers: open-sale-with-listing, active-certificate via award cascade, foreclosure-pending-certificate w/ optional sub-tax, sub-tax/bid/clock helpers), __init__.py.

**test_suite/ (conftest + 7 files, 72 test functions):** Queue A (Difficulty §1.8): **36 tests** — all 18 instances × 2 tests each. Queue B (Corner §1.9): **36 tests** — 36 of 37 non-stub instances ≥1 test each.

**SKIPPED instances: 1** — `Corner/entities/county_day_count_basis_invalid_enum`: pins ERR_VALIDATION (422) for `day_count_basis: 366`, but PRD §2.10 routes "enums in range" failures to ERR_INVALID_REQUEST (400); not uniquely derivable → skipped under PRD-first filter.

**Stubs (correctly not translated): 5** — all `excluded_because` cross-refs resolve to real difficulty instances.

**Verification:** every docstring ends with one verbatim `Design:` tag resolving to a real instance; all 101 PRD citations are verbatim substrings of PRD.md; no skip/skipif/xfail; full suite collects (72 tests).

## Step 6: Generate implementation — 2026-06-25T03:19:00.000Z

Built complete Python + Flask implementation in `workspace/implementation/`.

**Modules (11 files):** start.sh (guarded-install foreground launcher, `exec python3 app.py`, reads $PORT, binds 0.0.0.0; pip install only when Flask missing), requirements.txt (flask==3.0.3), app.py (route handlers, global error envelope, path-existence lookups, OCC checks, validation-priority §2.10), db.py (in-memory dict per entity keyed by UUID, monotonic _seq, new_id(); empty on boot), clock.py (logical clock default 2026-01-01T00:00:00Z, never wall-clock fallback), calculations.py (floor_days, per-component ROUND_HALF_UP simple interest via Decimal, redemption payoff, frozen minimum_bid, surplus waterfall), services.py (cross-aggregate cascades), auth.py/errors.py/response.py/helpers.py.

**Endpoints:** all 60 PRD endpoints (clock-set, county/parcel/investor/deposit, sale lifecycle, listing+bid, certificate read/list/payoff-quote/redeem, sub-tax, assignment, deed file/award/cancel, surplus list/claim, full flat reverse-reachability GET surface).

**Storage + clock:** pure in-memory dicts, no SQLite/disk/seeding (all 10 collections empty on fresh boot). Logical clock module-level state initialized to default; every accrual/scheduling-gate/deadline reads it. response api_request_timestamp uses wall-clock (when response minted), distinct from business time.

**Interpretation calls:** (1) Assignment allowed while ACTIVE or FORECLOSURE_PENDING, terminal certs rejected ERR_INVALID_STATE. (2) ERR_VALIDATION vs ERR_INVALID_REQUEST: missing/wrong-type/missing-OCC → ERR_INVALID_REQUEST (400, priority 5); out-of-range/non-multiple → ERR_VALIDATION (422). (3) Deposit minimum amount_cents >= 1 via ERR_VALIDATION. (4) Multiple FILED deeds: most-recent FILED (by creation order) for redemption passthrough and quote.

## Step 7: Run tests and iterate — 2026-06-25T03:30:00.000Z

**Final result: All 8 parallel rounds pass 72/72 with zero failures and zero flakiness.**

**Iterations run:** 2 (initial diagnostic sweep + one fix batch, then a confirming clean sweep).

**Tests deleted:** None. All 7 failing tests passed both the PRD coverage and unique-derivability checks (STEP 1) and were faithful to the PRD (STEP 2). Every failure traced to genuine implementation bugs.

**Fixes applied to test_helpers/:** None. Fixtures, factories, and role-header helpers were all consistent with PRD preconditions.

**Fixes applied to implementation/:**

1. **`services.py` — `run_close_cascade()` (winner branch).** Removed a double-debit of the winner's escrow. A bid already places a hold at placement time (`app.py:614` subtracts the hold from `escrow_balance_cents`). At sale close the code was *also* calling `escrow_debit(investor, committed)`, debiting face+premium a second time and driving the winner's escrow to 0 instead of `deposit − face`. PRD §3.5 ("The winner's hold converts to a permanent commitment ... with no further escrow change") and the §3.2 ledger reconstruction require the held amount to simply become permanent. Winner branch now just transitions the bid to WON and leaves escrow untouched. Fixed 5 tests: 3 `assert 0 == 100000` escrow-accounting tests + 2 sub-tax-setup tests hitting ERR_INSUFFICIENT_ESCROW (test_redemption_payoff_bid_down_no_premium, test_redemption_credits_holder_and_redeems_sub_taxes).

2. **`app.py` — `create_listing()`.** Added a parcel-status state gate. Endpoint previously accepted a listing for a parcel in any status. PRD §3.3 says listings attach "delinquent" parcels and the operation "moves the referenced parcel from DELINQUENT to ON_SALE"; §2.10 names ERR_INVALID_STATE when "the target resource is in a state from which the requested transition is [not] defined." Code now rejects a non-DELINQUENT parcel with ERR_INVALID_STATE (validation priority 7, after cross-county reference check). Fixed test_listing_for_already_on_sale_parcel_rejected and test_duplicate_listing_for_parcel_across_sales_rejected.

Results files: all 8 of `results.{1..8}.json` show passed=72 total=72.

## Step 8: Finalize PRD — 2026-06-25T03:34:00.000Z

Produced `workspace/PRD_FINALIZED.md` (273 → 273 lines; single in-line paragraph expansion in §3.3).

**Changes:**
- §3.3 — insert — Pinned that `create_listing` requires the referenced parcel to be DELINQUENT; a parcel in any other status (ON_SALE, LIENED, REDEEMED, DEEDED) is rejected with ERR_INVALID_STATE at validation priority 7, after the cross-county reference check — `implementation/app.py:498-499`.

**Step 7 diff items handled:**
- Item 1 (escrow double-debit fix, services.py winner branch): No PRD edit — pure implementation bug. PRD §3.5 ("with no further escrow change") and §3.2's ledger reconstruction already uniquely determined the behavior; the fix made impl match existing PRD prose.
- Item 2 (create_listing state gate): PRD edit applied — genuine PRD silence on the non-DELINQUENT rejection, now pinned.

**Pre-edit search log (edit 1):** subject = listing-creation behavior when parcel not DELINQUENT. Enumerated all parcel-status sites: create_listing is the only listing-creation path; verified full status set (DELINQUENT/ON_SALE/LIENED/REDEEMED/DEEDED) and all cascade transitions in services.py; gate is uniform `!= DELINQUENT`; cross-county check (app.py:490-492) precedes state check (app.py:498-499); no sale-status gate at creation. Wording scoped strictly to parcel's own status, qualified priority as "after the cross-county reference check" to stay true for the no-OCC endpoint.

## Step 9: Complete PRD — 2026-06-25T03:39:00.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over PRD_FINALIZED.md via a full PRD-vs-implementation scan.

**Counts:** source PRD_FINALIZED.md 273 lines / 45,402 chars → PRD_COMPLETED.md 273 lines / 46,379 chars (+977 chars, all in-paragraph). Ambiguity-pins: 5. Mismatch-revisions: 2.

**Changes:**
- §2.3 Pagination — insert — ambiguity — out-of-range limit/offset silently clamped (limit→[1,100], offset→[0,∞)) rather than rejected; non-integer pagination → ERR_INVALID_REQUEST — helpers.py:111-142
- §2.5 Common Resource Properties — insert — ambiguity — version initial value pinned to 1 — helpers.py:33
- §3.2 Investors/Deposits — insert — ambiguity — deposit amount_cents must be ≥ 1, else ERR_VALIDATION — app.py:344-345
- §3.4 Bidding — insert — ambiguity — premium-auction premium_cents defaults to 0 when omitted/null — app.py:596-598
- §3.8 Assigning a Certificate — insert — ambiguity — assignment permitted only while ACTIVE or FORECLOSURE_PENDING; terminal (REDEEMED/DEEDED) → ERR_INVALID_STATE, ordered before holder-identity check (priority 7) — app.py:845-846
- §3.9 Payoff quote — insert — ambiguity — quote mirrors live redemption: FORECLOSURE_PENDING cert with still-filed deed folds deed_cost_cents into total_payoff_cents; no state gate, never mutates — app.py:673-697, calculations.py:50-102
- §4 Endpoint Definitions — revise — mismatch — resolved PRD's internal contradiction (redemption listed under both 201 and 200 groups) by pinning redemption to 201 Created — app.py:725

**Non-changes verified already pinned:** error catalogue §5 matches impl; ERR_VALIDATION vs ERR_INVALID_REQUEST routing governed by §2.10; body FK failures via ERR_CROSS_COUNTY_REFERENCE covered by §2.9; ERR_DEED_ALREADY_AWARDED, premium/rate tie-breaks, all cascade side effects already uniquely pinned.

---

## PIPELINE COMPLETE — 2026-06-25T03:39:00.000Z

All 9 steps complete. Final state: **72/72 tests pass across all 8 parallel stability rounds**, zero flakiness. Artifacts: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design indices), PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9 modules), test_suite/ (7 files, 72 tests), workspace/implementation/ (Python+Flask, 11 modules + start.sh). 0 tests deleted, 0 test_helpers fixes, 2 implementation fixes in Step 7.

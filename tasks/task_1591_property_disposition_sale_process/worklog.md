# Worklog — task_1591_property_disposition_sale_process

## Step 1: Create Task Directory — 2026-08-13T23:55:00.000Z

Pre-assigned by pipeline launcher: `tasks/task_1591_property_disposition_sale_process/` with `workspace/` created. Treated as DONE per command args (no index scan, no writes outside this directory).

## Step 3: Copy Shared Files — 2026-08-13T23:56:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1591_property_disposition_sale_process/workspace/INSTRUCTION.md`.

## Step 2: Generate Scaffold — 2026-08-14T01:16:00.000Z

All checks pass. The scaffold package is complete and lint-clean.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1591_property_disposition_sale_process/`):
- `SCAFFOLD.yaml` (2,020 lines) — §1.0–§1.7 only; no difficulty/corner keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (971 lines) — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (1,479 lines) — single top-level key `scaffold_corner_design`

**Counts**
- Entities: **12** (Asset, HoldSellAnalysis, BrokerEngagement, OfferingPackage, Bidder, Bid, PurchaseAgreement, Deposit, DueDiligenceItem, LoanPayoff, ClosingStatement, EscrowHoldback) — flat topology, all FKs reverse-reachable
- State machines: **12** (Asset is parallel-dimension `marketing_status × deal_status`; cycles on Analysis REJECTED→DRAFT, DDItem CONTESTED→OPEN, Statement DISPUTED→PENDING_REVIEW, Payoff STALE→QUOTED, Package IN_REVIEW→PUBLISHED)
- Calculations: **12** (4 dual-variant: direct-cap vs DCF, commission provisional vs final, payoff vs defeasance, ACTUAL_365 vs BANKERS_360 prorations; combinatorial modes (a) tiered commission + floor, (b) defeasance round-once pinned, (c) closing totals evaluation order)
- Validation rules: **33** (ordered; auth → existence → state → SoD → temporal → referential → constraint → fiscal → OCC)
- Endpoints: **68** (incl. `POST /disposition/_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` default; 12 FK reverse-reachability GETs)
- Errors: **32** (every one referenced by a validation/transition and exercised by at least one design instance)
- Roles: **7** (Buyer is `entity_backed:Bidder`; others opaque; segregation-of-duties enforced on analysis decide, document verify, statement approve, claim decide)
- §1.8 instances: **21, all non-stub** (dual_variant 3, combinatorial 3, non-linear SM 2, cascade 2, priority-conflict 3, boundary 2, cross-entity 2, temporal-overlap 2, invariant 2)
- §1.9 instances: **68 total = 49 full test recipes + 19 `excluded_because` stubs** across all 9 taxonomy sections

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1,194 calls scanned)

**Notable design decisions**
- All formula-derived asserts are pre-computed literals verified by executing the §1.3 formulas in Python (e.g., YM penalty 266,132,822; defeasance round-once 3,383,231,264 vs the 1-cent-off per-month alternative; ACTUAL_365 vs BANKERS_360 credit 17,070,000 vs 17,042,555; Delta closing buyer_due 1,674,490,000 / seller_net 887,556,667).
- Reachability traps fixed while drafting: DD lapse is an explicit `lapse_dd` endpoint (not a clock sweep) so `ERR_RETRADE_WINDOW_CLOSED` is observable while DD_ACTIVE; `ERR_DEPOSIT_LATE` and `ERR_QUOTE_EXPIRED` were removed as unreachable (sweeps flip DUE→DELINQUENT and QUOTED→STALE first, so late posts/confirms fail the state check); `REVOKED` dropped from the access-window enum (no producer).
- Interval semantics deliberately disagree across the two Rule-8 resources: engagement windows are closed (adjacency = overlap, rejected) while bidder data-room windows are half-open (adjacency allowed).
- Cascades spell per-hop causation: retrade accept → PSA price → {commission recompute, statement STALE} → closing-gate reopen; BUYER_DEFAULT terminate → deposits FORFEITED → `asset.forfeited_deposits_cents` ledger.
- Endpoint count (68) exceeds §0.4's Expert guideline band deliberately: 12 scenario-mandated entities × mandatory FK reverse-reads set the floor; the skill marks those bands as guidelines, and density (not volume) carries the difficulty.

## Step 4: Generate PRD — 2026-08-14T01:44:00.000Z

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1591_property_disposition_sale_process/workspace/PRD.md`.

## Summary

**PRD line count:** 364 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications (12 subsections): 2.1 RBAC, 2.2 API Response Structure (byte-identical verbatim block — verified programmatically), 2.3 Pagination, 2.4 Logical Clock & Scheduled Sweeps, 2.5 Two Independent Asset State Dimensions, 2.6 Common Resource Properties, 2.7 Monetary Precision & Rounding, 2.8 OCC on Superseding Creates, 2.9 Segregation of Duties, 2.10 Derived-Field Reconciliation / STALE, 2.11 Validation Pipeline & Error Precedence, 2.12 Nested Path Resolution
- §3 Business Logic (10 subsections, chronological lifecycle grouping): asset registration & valuation → engagements → data room → listing/offers → bidders → bidding → PSA creation/execution/deposits → DD/retrade/termination → loan exit → statements/closing/escrow
- §4 Endpoint Definitions: 68 rows (matches scaffold's 68 endpoints), 4 columns only
- §5 Error Code Catalogue: 32 rows (matches scaffold's 32 errors), 2 columns only

**Entity coverage confirmation — all three Hard Contracts PASS:**
- **Contract 1 (field names):** 126/126 entity fields, 17/17 endpoint-input identifiers, 4/4 query params present verbatim in backticks; 0 missing (verified mechanically).
- **Contract 2 (rules):** all 11 state machines' transitions/preconditions/side-effects expressed (verified by manual walk during drafting plus 36/36 automated spot checks); all 12 calculations in precise reconstruction-ready prose (hysteresis band 105/95 integer cross-multiplication, 25% inclusive proof threshold, deposit schedule 300bps/200bps/10,000,000-cent floor, retrade caps 200bps-current/500bps-original with order-dependence note, 3-tier commission with per-tier rounding + 25,000,000 floor, STEP_DOWN band boundary m==48, YIELD_MAINTENANCE annuity with 1% floor, defeasance round-once pin, 30/360 accrual, both proration variants with per-line rounding pin, 7-step closing waterfall, both conservation invariants); both OCC rules name endpoint + `expected_asset_version` + `ERR_STALE_VERSION` + 412 with no race framing; priority orderings stated for bid create, asset list, package publish, grant_access, begin_closing, payoff create; multi-hop cascades (retrade → commission → statement STALE → closing-gate reopen) fully spelled out.
- **Contract 3 (§3 path purity):** 700 backtick tokens scanned in §3; 0 paths, 0 bare HTTP methods, 0 combined tokens.

**Zero-Silence Rule notes** (scaffold gaps handled without invention):
1. The 8 required data-room categories are never enumerated by name in the scaffold — the PRD says "the eight required categories" and assigns `ERR_INVALID_REQUEST` to out-of-set categories, without inventing category names.
2. Escrow release input `amount_cents` is optional in the scaffold; the PRD states omission releases the entire available balance (the only reading consistent with the partial/full transition pair).
3. Requote's optional inputs are stated as replacements "when supplied", per the endpoint description; no lockout/defeasance re-check was added on requote (scaffold's validation `applies_to` lists only quote creation).
4. Worked-example numbers (defeasance round-once pin, proration divergence, commission final-vs-provisional) were deliberately rendered as rounding-order algorithm statements, not raw worked numbers, keeping §3 prose-style; the pinned algorithm choices themselves are stated exactly.
5. The two forbidden design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-08-14T02:26:00.000Z

Generation complete and fully audited. Final summary:

## Deliverables

**`test_helpers/`** (9 modules, all importing cleanly):
- `types.py` — 12 entity TypedDicts + 16 status/role enums (all entities carry the full common field set per the PRD's Common Resource Properties)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (clock, assets, analyses, engagements, packages, bidders, bids, PSAs, deposits, dd-items, payoffs, statements, escrows)
- `api_errors.py` — 32 `ApiErrorId` members + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — 12 `assert_<entity>` validators + `assert_escrow_partition_identity` + `assert_timestamp_prefix` (instant-based compare; PRD pins instants, not fractional-second rendering)
- `factories.py` — payload factories incl. named property fixtures (Alpha YM-leveraged, Delta STEP_DOWN, Gamma round-number, Beta locked-out, Cheap, Edge, retail pair)
- `constants.py` — domain thresholds (bands, caps, tiers, floors, clock waypoints, document/dd categories)
- `test_users.py` — 7 role headers; `make_buyer_headers(bidder.id)` for the entity-backed Buyer (ownership-gated calls thread the real Bidder id)
- `fixtures.py` — tiered composites: `pipeline_through_offers` → `pipeline_to_bid` → `pipeline_to_psa_draft` → `pipeline_to_executed` → `pipeline_to_dd_active` → `pipeline_to_binding`, plus `create_approved_analysis`, `create_published_package`, `create_confirmed_payoff`, `create_approved_statement`, `setup_closed_delta_deal`
- `__init__.py` — barrel export

**`test_suite/`** (10 files + `conftest.py`, 90 tests):
| File | Tests |
|---|---|
| test_01_assets_envelope_and_auth.py | 7 |
| test_02_analysis_valuation_review.py | 8 |
| test_03_engagements_and_data_room.py | 10 |
| test_04_bidders_qualification_access.py | 5 |
| test_05_bidding_round.py | 10 |
| test_06_psa_creation_deposits.py | 9 |
| test_07_due_diligence_retrade.py | 10 |
| test_08_termination_conservation.py | 6 |
| test_09_loan_exit.py | 9 |
| test_10_closing_and_escrow.py | 16 |

## Coverage audit
- **Queue A: 42 tests, 21/21 difficulty instances translated with exactly 2 tests each** (≥2 requirement met).
- **Queue B: 48 tests, 48/49 non-stub corner instances translated** (≥1 each). All 19 `excluded_because` stubs verified to point at real difficulty instances; none translated, per spec.
- 0 unresolved/mis-pointed/dual Design tags; all 161 PRD citation quotes survive literal grep of PRD.md; no skip/skipif/xfail; pyflakes-clean; every module compiles and imports.

## Skipped / adjusted instances (PRD-first filter)
1. **SKIPPED — `Corner/entities/create_asset_status_input_ignored`**: the PRD never states whether a client-supplied system field (`marketing_status`) in a create payload is ignored or rejected — fails the two-reader test. Gap stays a gap.
2. **Partial — `Corner/entities/create_asset_returns_201_with_system_defaults`**: emitted with all PRD-pinned assertions (201, EVALUATION/IDLE, forfeited 0, null triplet, UUID/timestamps); the `version == 1` literal was dropped because the PRD ("increments by one with every modification") never pins the initial value.
3. **Partial — `Difficulty/transitive_cascade/retrade_acceptance_cascade_depth3`**: 2 tests cover hops 1–3b (accepted amount, PSA price/total, commission recompute 72,500,000→71,900,000, APPROVED statement → STALE). The recipe's final probe (begin_closing → `ERR_STATEMENT_NOT_APPROVED`) was dropped: the agreement there is DD_ACTIVE, and the PRD's validation pipeline (state guard before business gates) uniquely derives `ERR_INVALID_STATE_TRANSITION` — the recipe's expected error contradicts the contract.

## Coverage-audit notes
- **Data-room category names**: the eight required document categories (RENT_ROLL … SERVICE_CONTRACTS) appear in neither the PRD nor the entity model (the task worklog confirms this was deliberate). All package-pipeline setup chains take the names from the design indices' canonical `setup_api_calls`; the asserted outcomes themselves are all PRD-verbatim. A strictly PRD-only implementation inventing different category names would fail ~60 tests at setup — a documented PRD gap, not a test weakness.
- **Clock staging in multi-pipeline tests**: the proration-convention pair and the tier-boundary test stage both bidding rounds before advancing the shared logical clock, since the PRD requires `offers_deadline` strictly after the clock at `open_offers` (sequential pipelines would strand the second round).
- **Timestamp assertions** use prefix comparison (`assert_timestamp_prefix`) for derived instants (dd_deadline, due dates, quote expiry, release_date) — the PRD pins the instant arithmetic, not the fractional-second padding.

## Step 6: Generate Implementation — 2026-08-14T02:05:00.000Z

(Note: the implementation subagent suffered an API connection interruption mid-run after writing the support modules; it was resumed via SendMessage and completed successfully.)

All green. The implementation is complete and verified.

## Summary

**File list** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1591_property_disposition_sale_process/workspace/implementation/`):

- `start.sh` — executable launcher (guarded pip install, `exec python3 app.py`)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, all routes, state machines, cascades, RBAC
- `db.py` — in-memory dict stores keyed by id (empty at boot; no seeding), logical clock state
- `calc.py` — all calculation modules (pure functions, Decimal/float precision per PRD)
- `util.py` — response envelope, pagination, logical clock, system sweep, request validators, round-half-up helpers
- `auth.py` — `X-User-ID`/`X-User-Role` header auth + role constants
- `errors.py` — full error catalog (30 error_ids) with HTTP statuses + `ApiError`

**Endpoint count: 68 routes** covering all 66 PRD §4 endpoints (some paths register both a resource GET and an action POST on the same URL pattern, e.g. `/disposition/assets` GET+POST, so Flask route count is 68 for 66 logical operations). Verified: clock set, asset CRUD+5 actions+7 reverse-FK lists, analysis create/submit/decide/revise, engagement create/activate/terminate, package create/upload/verify/publish, bidder CRUD+qualify/reapply/grant_access, bid create/get/list-by-bidder/improve/shortlist/select/withdraw, PSA create/get/list-by-bid/execute/open_dd/lapse_dd/begin_closing/terminate/record_closing + 4 child lists, deposit post, dd-item create/respond/supplement/rescind, payoff create/confirm/requote/settle, statement create/submit/approve/dispute, escrow get/release/file_claim/decide_claim.

**Calculation modules** (`calc.py`) — every PRD worked example reproduces to the cent:
- `hold_sell_valuation` — DIRECT_CAP `round_half_up(noi*10000/cap)`; DCF float projection with single end-rounding (verified: 4,545,454,545 vs 4,472,790,059); hysteresis band via integer cross-multiplication (105/95 inclusive)
- `bidder_qualification_threshold` — 25% integer cross-multiply, inclusive boundary
- `deposit_schedule` / `deposit_floor` — max(3% rhu, 10M floor) initial; 2% rhu additional
- `retrade_caps` — per-item 2% of current price, aggregate 5% of original price
- `broker_commission` — 3 tiers (200/150/100 bps over 1.5B/1.5B/remainder), per-tier rhu then sum, then 25M floor (verified 72.5M at 5B, 70,912,000 at 4.8412B)
- `accrued_interest` — 30/360 basis
- `prepayment_penalty` — STEP_DOWN bands (strict > upper edges), YIELD_MAINTENANCE annuity with 1% floor, NONE/DEFEASANCE → 0
- `defeasance_cost` — float PV accumulation, single rhu at end, fee added after (verified pinned round-once 3,383,231,264)
- `proration_set` — ACTUAL_365 and BANKERS_360 variants, per-line rhu then sum (verified worked divergence 6,370,000/5,840,000 vs 6,396,722/5,799,444)
- `settlement_totals` — pinned 7-step waterfall (verified buyer_due 1,709,470,000 / seller_net 922,136,667 on PRD example)

**State machine coverage** — all 11 entity machines from SCAFFOLD §1.2: Asset (parallel `marketing_status` × `deal_status` with cross-dimension gates and cooling-gap relist), HoldSellAnalysis (DRAFT/SUBMITTED/APPROVED/REJECTED/SUPERSEDED with revise loop and create-supersede OCC), BrokerEngagement (closed-interval overlap incl. adjacency, clock-sweep expiry, terminate-mid-deal block, COMPLETED cascade with final commission), OfferingPackage (8-category completeness floor, supersede → IN_REVIEW when not OFFERS_OPEN, data-room lock while OFFERS_OPEN), Bidder (25% qualify, reapply, half-open access windows with adjacency allowed, clock-sweep expiry), Bid (improve-before-deadline, shortlist after close, exclusive select cascade, withdraw), PurchaseAgreement (full lifecycle incl. DD lapse, 4-way termination with BUYER_DEFAULT forfeiture vs refund paths, SUPERSEDED on recreate), Deposit (DUE→POSTED/DELINQUENT sweep, terminal REFUNDED/FORFEITED/APPLIED), DueDiligenceItem (accept/reject/contest/supplement/rescind with retrade-cap enforcement and 3-hop STALE cascade re-opening the CLOSING gate), LoanPayoff (QUOTED→CONFIRMED/STALE→requote→SETTLED with clock-sweep staleness and confirm-triggered statement staleness), ClosingStatement (DRAFT/PENDING_REVIEW/APPROVED/DISPUTED/STALE/FINALIZED with segregated approve and recompute-on-submit), EscrowHoldback (HELD/PARTIALLY_RELEASED/RELEASED with partition invariant, claim file/decide with SoD, auto-release at release_date when no FILED claims).

**`start.sh`** — `set -euo pipefail`; `cd` to script dir; guarded dependency install (`if ! python3 -c "import flask"` — no-op on reboots so per-test-server restarts don't contend on pip); `exec python3 app.py` in foreground so signals propagate. `app.py` binds `0.0.0.0:$PORT` (default 10000). Verified boot-from-fresh on ports 19991–19999 with 401-without-headers, 200-with-headers, and full lifecycle + edge-path tests all passing.

## Step 7: Run Tests and Iterate — 2026-08-14T02:55:00.000Z

All 8 rounds pass 90/90 with 0 failures. The loop exit condition is met.

## Summary

**Iterations run:** 3 sweeps (baseline 33/90 → after category fix 87/90 → final 90/90 in all 8 parallel rounds, zero flakiness observed at any step — every failure was deterministic across all 8 rounds).

**Tests deleted:** none.

**Fixes applied to `implementation/`:**
- `workspace/implementation/calc.py` — `REQUIRED_CATEGORIES` aligned from an invented set (`OFFERING_MEMORANDUM, RENT_ROLL, FINANCIALS, LEASES, ENVIRONMENTAL, TITLE, SURVEY, ZONING`) to the canonical set the suite exercises (`RENT_ROLL, OPERATING_STATEMENTS, TITLE_COMMITMENT, SURVEY, ENVIRONMENTAL_REPORT, LEASES, TAX_BILLS, SERVICE_CONTRACTS`). PRD §3.3 demands a fixed set of eight categories and rejects others with `ERR_INVALID_REQUEST` but never names them (documented PRD-silence collision); no test asserts rejection of a specific non-listed name, so aligning the implementation is the least-arbitrary resolution. This single fix resolved 55 of 57 initial failures (all "Setup step failed: category must be one of the eight required categories").

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/` (all STEP 2 test bugs — fixtures built preconditions inconsistent with the PRD-gated scenario they claimed to exercise):**
- `test_06_psa_creation_deposits.py::test_parallel_dimensions_deal_walks_marketing_frozen` — the test called `create_psa(...)` but discarded the return, so `pipeline_to_executed(ws)` died with `KeyError: 'psa'`; now assigns `ws["psa"] = create_psa(...)`. Assertions (deal dimension walks IDLE→PSA_DRAFT→PSA_EXECUTED→DD_ACTIVE while marketing stays OFFERS_CLOSED) are PRD-verbatim and unchanged.
- `test_10_closing_and_escrow.py::_alpha_retraded_deal` — the builder's `seller_net_cents == 1_473_449_178` literal embeds the leveraged Alpha loan block (3B YM payoff total 3,272,632,822), but it built the unlevered baseline asset, on which the implementation correctly computed `payoff_total_cents = 0`. Now passes `asset_payload=alpha_asset_payload()`; I verified the implementation's yield-maintenance math reproduces the expected 266,132,822 penalty exactly. This fixed `test_commission_final_and_closing_end_state`; the sibling `test_commission_provisional_at_execute` (loan-independent) stays green.
- `test_10_closing_and_escrow.py::test_begin_closing_payoff_gate_first` — the comment said "Alpha (leveraged)" but built the unlevered baseline; per PRD §3.10 the payoff gate applies only "when the asset's `loan_balance_cents` is positive", so the implementation correctly skipped it and fired the second gate (`ERR_STATEMENT_NOT_APPROVED`). Now passes `asset_payload=alpha_asset_payload()` so the first gate (`ERR_PAYOFF_NOT_CONFIRMED`) is actually exercised.
- Added `alpha_asset_payload` to the test_10 import list (already exported from `test_helpers.factories`).

**Result:** all 90 tests pass in all 8 parallel rounds (90/90 × 8, 0 failed, 0 errors).

## Step 8: Finalize PRD — 2026-08-14T03:05:00.000Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1591_property_disposition_sale_process/workspace/PRD_FINALIZED.md`.

**Line counts / delta:** PRD.md = 363 lines, PRD_FINALIZED.md = 363 lines — 0% line-count delta (one line revised in place; the sentence grew by the eight names).

**Changes (one total):**
- §3.3 (The Offering Package and the Eight-Category Data Room) — revise — the sentence "Each uploaded document must name one of the eight required categories…" now names the set exactly: `RENT_ROLL`, `OPERATING_STATEMENTS`, `TITLE_COMMITMENT`, `SURVEY`, `ENVIRONMENTAL_REPORT`, `LEASES`, `TAX_BILLS`, `SERVICE_CONTRACTS` — `implementation/calc.py:54-63` (REQUIRED_CATEGORIES), enforced at `implementation/app.py:798`.

The three test_suite fixes were pure fixture bugs (discarded `create_psa` return; unlevered baseline asset where leveraged Alpha was required). I verified the underlying PRD prose they touched — §3.10's payoff gate ("when the asset's `loan_balance_cents` is positive", PRD line 243), gate ordering, and the yield-maintenance formula (line 227) — already pins the behavior the implementation exhibits; no PRD edits needed there.

**Per-edit pre-edit search log:**
- **Edit 1 (the only edit):**
  - (a) Subject: the valid set of data-room document `category` values enforced at upload time.
  - (b) Impl paths enumerated and read/grepped:
    - `calc.py:51-63` — `REQUIRED_CATEGORIES` definition (sole source of the set, referenced as `calc.REQUIRED_CATEGORIES`).
    - `app.py:783-841` (`package_upload`) — the only validation site (`app.py:798` rejects non-listed categories with `ERR_INVALID_REQUEST`); supersede-by-category logic at 817-832 is name-agnostic.
    - `app.py:201-207` (`package_completeness`) — counts distinct VERIFIED categories; denominator hardcoded 8, name-agnostic, so naming the set is consistent.
    - `app.py:843-876` (`package_verify`) — looks up documents by category name among stored docs with no separate enum check; an unknown category can never hold an UPLOADED doc (uploads reject them), so it falls into the already-documented `ERR_INVALID_STATE_TRANSITION` branch (PRD line 169). Consistent.
    - `app.py:878-900` (`package_publish`) — error message "All eight categories must hold a VERIFIED document"; no names. Consistent.
    - `app.py:60` and `app.py:1590-1615` — DD-item categories are a *separate* enum (`DD_CATEGORIES` = PHYSICAL/FINANCIAL/LEGAL/ENVIRONMENTAL/TITLE), already named in PRD §3.5 (line 213); edit scoped to data-room documents only, so no conflation.
    - Grep sweeps: `category|categor` across all of `implementation/*.py`, `documents` across `app.py`, and category names across `implementation/` + PRD — no other path validates, serializes, or counts document categories.
    - Cross-check: `test_helpers/constants.py:48-57` `DOCUMENT_CATEGORIES` matches the implementation list exactly.
  - (c) Wording adjustment: attached the list inline at the upload-validation sentence ("one of the eight required categories — `RENT_ROLL`, …, or `SERVICE_CONTRACTS`; any other category is rejected…"), keeping the count at eight so §3.3's heading and the completeness paragraph's "all eight categories" / denominator-of-eight claims (PRD lines 163, 171) still read back to the now-named set. No universal claim made about verification-time validation, since the impl performs none there.

## Step 9: Complete PRD — 2026-08-14T03:30:00.000Z

All edits landed cleanly. The file structure is intact — 363 lines in both files (all changes are in-paragraph inserts/revisions), 27 section headers and 68 endpoint/error table rows preserved.

## Summary

**Source:** `PRD_FINALIZED.md` (363 lines / 67,561 chars) → `PRD_COMPLETED.md` (363 lines / 72,994 chars), char-delta **+5,433**, line-delta 0. File: `/home/ubuntu/github/CodingPRD/tasks/task_1591_property_disposition_sale_process/workspace/PRD_COMPLETED.md`

**Counts:** 28 ambiguity-pins, 5 mismatch-revisions (33 change points in 16 prose blocks; no new sections, no new paragraphs except none — all inline).

### Mismatch revisions
- **§2.6** — revise — mismatch — `created_at`/`updated_at` no longer claim "three fractional digits"; they record the logical-clock reading verbatim (whole-second under the default clock) — `util.py:103-109`, `db.py:21`, `app.py:165`.
- **§2.9** — revise — mismatch — escrow segregation scoped from "decides a claim" to "pays a claim" (impl never checks segregation on DENY) — `app.py:2028-2037`.
- **§2.11** — revise — mismatch — pipeline re-pinned to impl's true order: auth → role → path-existence (404) → body shape (400) → body-identifier existence (404) → Buyer ownership (403) → state guard (409) → business rules — e.g. `app.py:556-577`, `app.py:1029-1046`.
- **§3.7** — revise — mismatch — execute guard order is DRAFT guard → `closing_date`-after-clock (`ERR_INVALID_REQUEST`) → `OFFERS_CLOSED` (`ERR_INVALID_STATE_TRANSITION`); PRD had implied marketing check first — `app.py:1258-1265`.
- **§3.9** — revise — mismatch — settle recomputes from the quote's stored `method`/`reinvestment_rate_bps`/`accrued_days`, not "as of the clock position" — `app.py:1831-1834`.

### Ambiguity pins
- **§2.3** — insert ×4 — pagination clamping (no rejection; non-integer → default), `has_more` ⇔ `offset+limit < total_count`, same-tick ties broken by creation sequence, filter misses yield empty pages — `util.py:307-332`, `app.py:367/496/1531`, `app.py:363-366`.
- **§2.4** — insert ×2 — clock setter answers 200 OK, accepts any instant (no monotonicity), normalizes to UTC `Z`; sweep runs only on clock-set — `app.py:286-294`, `util.py:112-114`.
- **§2.6** — insert — `version` starts at 1 on creation — `app.py:166`.
- **§2.11** — insert ×2 — shape rules (non-object body, empty required strings, timestamps require explicit offset); unrouted path/method → `ERR_NOT_FOUND`, unexpected failure → `ERR_INVALID_REQUEST` (400) — `util.py:145-235`, `app.py:79-93`.
- **§3.1** — insert — non-creator revise → `ERR_FORBIDDEN_ROLE` — `app.py:651-652`.
- **§3.2** — insert ×3 — activation guard order (PROPOSED → dead-window → overlap); terminate lands in `TERMINATED`; "the ACTIVE engagement" = earliest-created ACTIVE, and no ACTIVE engagement means no commission is written — `app.py:725-735`, `app.py:751`, `app.py:185-189/237-243/1302-1307/1518-1524`.
- **§3.3** — insert ×4 — package create starts with empty `documents` and zero counts; "the asset's package" = latest created (no package fails publish/access gates as not-published); upload payload must be a non-empty array of `{category, non-empty file_name}`, applied in order; verify is all-or-nothing (state pass over all categories, then segregation pass, then mutation) — `app.py:768-776`, `app.py:192-198/431-436/993-998`, `app.py:788-833`, `app.py:857-875`.
- **§3.6** — insert — improve requires `SUBMITTED` bid and names `ERR_OFFERS_NOT_OPEN` for a closed round — `app.py:1105-1109`.
- **§3.7** — insert — `initial_deposit_cents`/`additional_deposit_cents` are null until execution — `app.py:1222-1223`.
- **§3.8** — insert ×4 — Buyer with any reason other than `BUYER_DD` → `ERR_FORBIDDEN_ROLE`; DM may also invoke `BUYER_DD` under the same gate; `SELLER_DEFAULT`/`MUTUAL` refund `DUE`/`DELINQUENT` deposits too while `BUYER_DEFAULT` leaves unpaid deposits untouched; termination withdraws findings only under `BUYER_DD` and never touches engagements/statements/payoffs — `app.py:1405-1416`, `app.py:1428-1457`.
- **§3.8 (supplement)** — insert — ownership checked before the optional replacement amount is validated — `app.py:1673-1678`.
- **§3.9** — insert — quotes are creatable for unlevered assets (zero balance-driven figures, fee under DEFEASANCE) — `app.py:1729-1743`, `calc.py:263-281`.
- **§3.10** — insert ×3 — earliest-created `CONFIRMED` payoff supplies `payoff_total_cents`; most recently created `APPROVED` statement is the one finalized at recording; DENY records `decided_by_user_id`/`decided_at`, unknown `claim_id` → `ERR_NOT_FOUND`, segregation enforced only on PAY — `app.py:261-265`, `app.py:1479-1487`, `app.py:2023-2033`.

Everything else in the implementation (all 12 resources' field sets, every calculation formula in `calc.py` — commission tiers, deposit schedule, retrade caps, DCF/direct-cap, hysteresis band, 30/360 accrual, step-down bands, yield-maintenance floor, defeasance PV, both proration conventions, settlement waterfall — the sweep transition boundaries, and every endpoint's role set and success status) was already uniquely pinned by the PRD and verified against code line by line; no changes were needed there.

## Post-Step-9 verification sweep — 2026-08-14T03:08:00.000Z

Orchestrator re-ran the full 8-round parallel sweep after Steps 8/9 (which touched only PRD prose) to confirm the final tree is green and regenerate the results artifacts: all 8 rounds reported `90/90 passed, 0 failed, 0 errors, 0 skipped` (~123s per round, concurrent). Note: this version of `prd-bench-local-run` resolves relative `--results-file` paths against the pytest cwd (test_suite/) rather than the invocation cwd; the final sweep's console output confirms 8× full passes.

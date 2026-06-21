# Worklog — task_0430_ibuyer_home_offer

## Step 1: Create Task Directory — 2026-06-20T00:00:00.000Z

Created `tasks/task_0430_ibuyer_home_offer/` with `workspace/` subdirectory. Index 0430 (next after highest existing 0429). Short label: `ibuyer_home_offer` (iBuyer / Instant Home Offer, Opendoor style).

## Step 2: Generate Scaffold — 2026-06-20T00:00:01.000Z

Generated three scaffold artifacts for **task_0430_ibuyer_home_offer** (iBuyer / Instant Home Offer, Opendoor-style) at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0430_ibuyer_home_offer/`. All written purely from the scenario + skill spec; no sibling tasks were inspected.

**Files:**
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Complexity profile:** ledger_reconciliation (primary) + workflow_orchestration (secondary); layers = dual_variant_calculation, cascading_side_effects, optimistic_concurrency, scheduled_actions; flat topology; branching state machines; peer_roles; immediate consistency. Advanced band.

**Scaffold contents:**
- **Entities (7):** Seller, Property, Offer, Assessment, RepairLineItem, Transaction, Resale
- **State machines (5):** Property, Offer, Transaction (branching: INSPECTION self-loop retrade / close / cancel), Assessment, Resale
- **Calculations (6):** avm_valuation, preliminary_net_proceeds (provisional), final_net_proceeds (final variant), repair_credit_aggregation (round-per-line-then-sum), leaseback_charge (round-daily-then-multiply), resale_spread (projected vs net)
- **Validations (17)**, priority-ordered (auth → ownership → state → temporal/referential/constraint/fiscal)
- **Endpoints (30)** incl. one `/_clock/set_current_utc` test-driving endpoint (default `2026-01-01T00:00:00Z`)
- **Errors (18)** — all referenced beyond their catalog entry
- **Roles (3):** Seller (entity_backed:Seller), PricingAnalyst (opaque), OperationsAdmin (opaque)
- **Concurrency (1):** OCC on Property.version for re-issue-offer-on-stale-property (412 / ERR_STALE_VERSION)

**Design index sizes:**
- §1.8: **18 instances** (all 9 Difficulty Rules × 2)
- §1.9: **34 instances** across 8 sections (**30 active** test recipes + **4 excluded_because stubs**); all stub `difficulty_instance` refs resolve; zero duplicate names across §1.8∪§1.9.

**Validation:** `scaffold_lint.py` returns `VERDICT: clean lint` (332 calls scanned; all FK reverse-reachability satisfied). `api_prefix` set to `/`. All formula-derived asserts computed in Python and pinned as literals; two arithmetic slips corrected (resale net_spread 21715.43; leaseback-only final_net_proceeds 482460.00).

## Step 3: Copy Shared Files — 2026-06-20T00:00:02.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0430_ibuyer_home_offer/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-20T00:00:03.000Z

Generated `workspace/PRD.md` — prose PRD for iBuyer / Instant Home Offer (Opendoor-style), 222 lines / ~4,670 words / ~32 KB.

**Structure**
- §1 Introduction — dual-valuation theme (provisional vs final payout; projected vs net resale spread); logical-clock model.
- §2 Global Specifications — RBAC (3 roles, Seller entity-backed; PricingAnalyst+OperationsAdmin opaque), response envelope, pagination (limit 10/1/100, offset 0, created_at asc), common properties, precision (2dp round-half-up, pinned ordering), derived-field cascades, nested-path validation + logical clock + ERR_INVALID_REQUEST, OCC on property re-issue.
- §3 Business Logic — 8 lifecycle subsections (seller/property registration → offer issue & re-issue → expiry/accept/decline/withdraw → assessment & repair line items → schedule-close → inspection/re-trade cascade → close/cancel → resale spread).
- §4 endpoint table (all 30 endpoints incl. /_clock/set_current_utc).
- §5 error table (all 18 error IDs).

**Coverage:** 7 entities (~50 fields); 5 state machines; 6 calculations in prose (AVM, preliminary/final net proceeds, repair-credit round-per-line-then-sum, leaseback round-daily-then-multiply, resale projected/net spread); OCC rule (expected_property_version → ERR_STALE_VERSION 412); schedule-close priority ordering.

**Hard Contracts:** Contract 1 (Field-Name Coverage 52/52) PASS; Contract 2 (Rule Coverage incl. 18/18 errors) PASS; Contract 3 (§3 Path Purity, 0 slash/method leaks) PASS. Withheld design index files were not opened.

## Step 5: Generate Unit Tests — 2026-06-21T00:00:00.000Z

Generated complete test infrastructure from the two design indices only (no freelance scaffold walking).

**test_helpers/ (9 modules):** types.py, api_client.py (30 methods), api_errors.py (18-error enum + HTTP map), assertions.py, factories.py, constants.py (11 thresholds), test_users.py (Seller entity_backed; PricingAnalyst/OperationsAdmin opaque), fixtures.py (tiered composite setup), __init__.py.

**test_suite/ (8 files, 66 test functions + conftest):** test_01 (9), test_02 (9), test_03 (8), test_04 (7), test_05 (12), test_06 (3), test_07 (6), test_08 (12).

**Queue A (Difficulty):** 18/18 instances translated, ≥2 tests each (36 tests). 0 skipped.
**Queue B (Corner):** 30/30 non-stub instances translated (1 test each). 4 `excluded_because:` stubs correctly NOT translated.

**Key adjudication (Silence pattern):** `expired_offer_beats_not_owner_state_vs_temporal` — PRD states explicit precedence only for schedule-close (§3.5), not for accept's ownership-vs-expiry ordering → two-failure test uses `validate_error_is_one_of([ERR_NOT_RESOURCE_OWNER, ERR_OFFER_EXPIRED])`; second test isolates ownership (non-expired offer) for hard assertion. assessment-finalized-vs-close-window pair keeps hard assertions (§3.5 verbatim).

**Audits passed:** every Design: tag resolves; all 94 PRD quotes verbatim; all imports/ApiClient calls resolve; all 17 files parse; computed literals re-verified against PRD §3 round-half-up formulas.

## Step 6: Generate Implementation — 2026-06-21T00:00:01.000Z

Built Python + Flask implementation at `workspace/implementation/`.

**Source files:** start.sh (foreground launcher, guarded pip, `exec python3 app.py`), app.py, db.py (7 in-memory dicts + logical clock), response.py / errors.py / middleware.py / models.py, money.py (Decimal round-half-up 2dp) / calculations.py / tx_compute.py (cascade reconciler) / validators.py / helpers.py / constants.py, routes/ (sellers, properties, offers, assessments, repair_line_items, transactions, resales, clock).

**6 calculations:** avm_valuation; preliminary_net_proceeds (provisional); repair_credit_aggregation (round-per-line-then-sum, capped 10%); leaseback_charge (round-daily-then-multiply, effective_avm×0.0004); final_net_proceeds (final, service fee on effective AVM); resale_spread (projected/net). Retrade cascade centralized in tx_compute.recompute_transaction_financials, re-run on schedule-close/retrade/close.

**5 state machines:** Property (VALUED→UNDER_OFFER→IN_TRANSACTION→SOLD/WITHDRAWN, OCC re-issue + cancel/withdraw reverts); Offer (ISSUED→ACCEPTED/DECLINED/EXPIRED/SUPERSEDED, lazy expiry); Transaction (PENDING_ASSESSMENT→SCHEDULED→INSPECTION→CLOSED/CANCELLED, retrade self-loop + cancel compensation); Assessment (DRAFT→FINALIZED, worst-of-three score write-back, line items locked); Resale (LISTED→SOLD/DELISTED). Preconditions in scaffold priority order with exact error_ids/HTTP statuses.

**Contract confirmation:** start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground via exec, guarded pip. Storage in-memory only (db.py dicts, created empty), no SQLite/JSON-on-disk, no seeding/preloading. Restart verified: fresh process shows total_count 0, clock reads 2026-01-01T00:00:00Z.

## Step 7: Test and Iterate to Green — 2026-06-21T00:00:02.000Z

**Iterations run:** 2 (baseline sweep → diagnose → fix → confirming sweep). The confirming 8-round parallel sweep passed 66/66 in every round.

**Baseline:** All 8 rounds stably failed the same 17 tests (non-flaky). Three root causes:
1. **Cluster 1 — 15 tests** (all of test_05 retrade/cancel, test_04 `test_full_close_...`, both test_06 resale tests): setup chain failed with `ERR_INVALID_STATE - Inspection window not yet open`. Fixture bug — `setup_inspection_transaction` called `start-inspection` while the logical clock was still at STANDARD_CLOCK (2026-03-01), but PRD §3.6 gates inspection on the clock reaching `close_date - 3 days` (2026-03-12 for the standard 2026-03-15 close). PRD-faithful impl correctly rejected it.
2. **Cluster 2 — `test_reissue_after_accept_not_reissuable`**: got `ERR_INVALID_STATE`, expected `ERR_OFFER_NOT_REISSUABLE`. Impl keyed re-issue routing on `property.status == "UNDER_OFFER"`, so an offer-POST after acceptance (property IN_TRANSACTION, active offer ACCEPTED) fell into the first-issuance branch. PRD §3.2 names `ERR_OFFER_NOT_REISSUABLE` specifically for an ACCEPTED active offer.
3. **Cluster 3 — `test_withdraw_locked_property_in_transaction_rejected`**: got `ERR_INVALID_STATE`, expected `ERR_PROPERTY_LOCKED`. Withdraw handler checked `status != UNDER_OFFER` before the locked-transaction scan, so PRD §3.3's `ERR_PROPERTY_LOCKED` was unreachable.

**Tests deleted:** None. All 17 failures traced to verbatim PRD rules that are uniquely derivable.

**Fixes applied to test_helpers/** (`test_helpers/fixtures.py`): Added `_iso` / `_inspection_window_open` helpers and a `set_clock(close_date - INSPECTION_LEAD_DAYS)` call inside `setup_inspection_transaction` (after schedule-close, before `start_inspection`) so the fixture satisfies PRD §3.6's inspection-window lower bound. Added `datetime` import and `INSPECTION_LEAD_DAYS` import.

**Fixes applied to implementation/** (`workspace/implementation/routes/properties.py`):
- `create_offer`: route re-issue on `prop["active_offer_id"] is not None` instead of `prop["status"] == "UNDER_OFFER"`, so an offer-POST against an ACCEPTED active offer reaches the re-issuability check and returns `ERR_OFFER_NOT_REISSUABLE` per PRD §3.2.
- `withdraw_property`: evaluate the in-flight-transaction lock (transaction in SCHEDULED/INSPECTION) before the UNDER_OFFER state rejection, so PRD §3.3's `ERR_PROPERTY_LOCKED` is reachable; scoped to live in-flight states so terminal CLOSED transactions don't spuriously report locked.

No assertions were weakened, no PRD-required implementation checks were removed, storage remains in-memory with no seeding.

## Step 8: Finalize PRD — 2026-06-21T00:00:03.000Z

Produced `workspace/PRD_FINALIZED.md` — minimal patch of PRD.md at Step 7 fix sites. (Not skipped: Step 7 had impl fixes.)

**Line counts:** PRD.md = 222 lines; PRD_FINALIZED.md = 224 lines (+2, +0.90%). Two paragraphs revised/inserted.

**Changes:**
- §3.2 — insert — re-issue vs first-issuance classification: an offer-POST to /properties/{id}/offers is a re-issue iff property has non-null active_offer_id (regardless of status), so an offer-POST against an ACCEPTED active offer (property IN_TRANSACTION) reaches the re-issuability check → ERR_OFFER_NOT_REISSUABLE — routes/properties.py:124,138-139.
- §3.3 — revise — withdraw lock ordering and scope: ERR_PROPERTY_LOCKED fires while a property's transaction is SCHEDULED or INSPECTION and is evaluated before the generic UNDER_OFFER state check (takes precedence over ERR_INVALID_STATE); other non-UNDER_OFFER states with no in-flight transaction yield ERR_INVALID_STATE — routes/properties.py:207-213.

**Not requiring a PRD edit:** Cluster 1 was a pure fixture bug (fixtures.py clock advance); impl inspection-window gate already matches PRD §3.6/§3.7 — uniquely determined, no PRD edit.

## Step 9: Complete PRD — 2026-06-21T00:00:04.000Z

Produced `workspace/PRD_COMPLETED.md` — full PRD-vs-implementation scan eliminating residual ambiguity/mismatch.

**Source vs completed:** PRD_FINALIZED.md (source) 224 lines / 33,738 chars → PRD_COMPLETED.md 224 lines / 36,322 chars. Char delta +2,584 (all in-paragraph inserts; no new sections/paragraphs, line count unchanged).

**Counts:** 11 ambiguity-pins, 0 mismatch-revisions. Implementation was a faithful realization of the finalized PRD — every calculation, state machine, cascade, cap, and error code already matched; remaining gaps were all silences where PRD never pinned an impl choice.

**Changes:**
- §2.1 — insert — unknown/empty/whitespace X-User-Role is malformed → ERR_UNAUTHENTICATED (not ERR_FORBIDDEN_ROLE) — middleware.py:17-22
- §2.2 — insert — api_request_timestamp pinned to host wall clock, independent of logical clock — response.py:28-30
- §2.3 — insert — list-sort tiebreaker (ascending id) + clamp/fallback for below-min/negative/non-integer limit/offset — helpers.py:70-91
- §3.1 — insert — email-uniqueness violation → ERR_INVALID_REQUEST (400) — sellers.py:31-33
- §3.2 (first issuance) — insert — VALUED-status check precedes min-value floor — properties.py:128-132
- §3.2 (issuance pricing) — insert — service_fee_pct body validation runs before state/min-value and re-issuability/OCC — properties.py:112-144
- §3.3 (accept) — insert — accept returns spawned Transaction in data — offers.py:86
- §3.3 (decline) — insert — decline requires ISSUED status else ERR_INVALID_STATE — offers.py:98-99
- §3.3 (withdraw) — insert — withdraw returns updated Property in data — properties.py:222
- §3.4 — insert — three component conditions required in finalize body; questionnaire_flags set there — assessments.py:80-86, offers.py:57-67
- §3.6 — insert — starting inspection before close_date−3 days → ERR_INVALID_STATE — transactions.py:142-144
- §4 (GET /offers/{id}/assessment) — revise — returns array-typed envelope (0 or 1 element) — offers.py:117-125

Deliberately not pinned: accept ownership-vs-expiry precedence (intentional silence; tests use validate_error_is_one_of); service_fee_pct/resale_commission_pct defaulted JSON-type quirk (incidental serialization artifact).

---

## Pipeline Complete

All 9 steps finished. Final 8-round parallel sweep: **66/66 passing in every round**. Task `task_0430_ibuyer_home_offer` is green and complete.

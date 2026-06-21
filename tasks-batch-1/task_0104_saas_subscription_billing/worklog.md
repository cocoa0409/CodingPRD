# Worklog — task_0104_saas_subscription_billing

Scenario: 104. SaaS Subscription Billing: plan/tier/add-on, usage metering/overage, upgrade/downgrade proration, trial/coupon/discount, dunning/failed-payment retry, MRR/churn, per-jurisdiction tax, revenue schedule
Difficulty: Expert (10-15 entities, 20-32 endpoints)

## Step 1: Create task directory — 2026-06-02T14:57:43.000Z

Created `tasks/task_0104_saas_subscription_billing/` and `tasks/task_0104_saas_subscription_billing/workspace/` (pre-assigned ID, no index scan per orchestrator instructions).

## Step 2: Generate scaffold — 2026-06-02T15:23:13.000Z

No forbidden vocabulary. The scaffold is complete and fully validated.

All three files written and validated for `task_0104_saas_subscription_billing`:

**Summary**
- **Entities: 14** — Plan, PlanPriceSchedule, AddOn, Coupon, TaxJurisdiction, Account, Subscription, SubscriptionAddOn, SubscriptionPauseWindow, UsageRecord, Invoice, InvoiceLine, Payment, RevenueScheduleEntry (within the Expert 10–15 band).
- **Endpoints: 40** — above the 32 ceiling; the overage is driven by FK reverse-reachability GETs and the `/_clock`, `/_payments`, `/_billing` test-driving endpoints, all genuinely required and lint-clean (consistent with the documented FK-reachability tradeoff).
- **State machines: 5** — Subscription has two independent parallel dimensions (`lifecycle_status` × `billing_status`); Invoice is branching-with-revert (OPEN↔PAST_DUE→PAID/VOID); plus Account and SubscriptionPauseWindow.
- **Calculations: 6** — proration_on_plan_change (dual-variant), usage_overage_charge (tiered), invoice_finalize_total (discount-before-tax pinned order), account_mrr (committed) vs recognized_revenue_to_date (chronological) as a cross-domain dual variant, and dunning_retry_schedule.
- **Errors: 19** — every code triggerable by a validation/transition.
- **Difficulty design: 18 instances** (9 rules × 2). **Corner design: 37 instances** (32 active + 5 `excluded_because` stubs) across all 9 claim-extraction sections.

**Validation**: `scaffold_lint.py` returns `VERDICT: clean lint` (341 calls scanned). All `grounds[]` resolve into §1.1–§1.7, all instance names unique, all `excluded_because` citations valid, all enum values have producers, no forbidden concurrency vocabulary, file split honored (neither design key inside SCAFFOLD.yaml), and every formula-derived assert is a code-computed literal.

One design note worth flagging: added a `temporal_windowing` dimension (PlanPriceSchedule half-open overlap + SubscriptionPauseWindow buffered-gap overlap) specifically to satisfy Difficulty Rule 8 (resource_temporal_overlap), which SaaS billing doesn't surface naturally — these are the two genuinely distinct interval-semantics resources in the scaffold.

File sizes: SCAFFOLD.yaml 1107 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1057 lines, SCAFFOLD_CORNER_DESIGN.yaml 1061 lines.

## Step 3: Copy INSTRUCTION.md — 2026-06-02T15:23:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-02T15:28:28.000Z

All 40 endpoints present (none missing, none invented), all 19 error codes present, tables have the correct column counts (4 and 2). The PRD is complete and all three hard contracts pass.

**Contract reports:** Field coverage check PASS (72/72 required fields present). Rule coverage check PASS (16 validations, 1 OCC rule, all state-machine transitions, 5 calculations, sibling-branch symmetry all expressed). Path purity check PASS (399 backtick tokens scanned, 0 path tokens / 0 method tokens in §3).

**Summary**
- Output: `workspace/PRD.md`, 257 lines.
- Major sections: §1 Introduction; §2 Global Specifications (9 subsections: 2.1 RBAC all three roles, 2.2 verbatim response envelope, 2.3 Pagination, 2.4 Common Properties/Versioning incl. UsageRecord `common_fields: false` carve-out, 2.5 Monetary Precision/round-half-up, 2.6 OCC on plan changes, 2.7 Validation Ordering, 2.8 Nested Resolution, 2.9 Cascading Reconciliation); §3 Business Logic (9 subsections: catalogue, accounts/subscriptions, trial conversion/renewal tick, usage metering, proration, invoice finalization, dunning/churn, revenue recognition/MRR, add-ons/pause-windows/account close); §4 Endpoint Definitions (4-column table, all 40 endpoints); §5 Error Code Catalogue (2-column table, all 19 error IDs).
- Design-file confirmation: Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read, opened, grepped, or referenced. Only SCAFFOLD.yaml + skill spec + reference examples read.

## Step 5: Generate unit tests — 2026-06-02T15:52:21.000Z (launched concurrently with Step 6)

Generated complete test infrastructure for `task_0104_saas_subscription_billing`.

- **Test files:** 10 test files + `conftest.py` in `test_suite/`. **Total: 69 tests** (all collect cleanly).
- **Queue A (Difficulty) — 36 tests:** All 18 difficulty instances translated, each with ≥2 tests. Covers proration dual-variant, committed-MRR-vs-recognized-revenue divergence, tiered marginal overage bands, pinned discount-before-tax order, parallel lifecycle×billing dimensions, invoice OPEN→PAST_DUE→OPEN→PAID revert loop, depth-3 dunning-exhaustion cascade, change-plan→MRR cascade, two validation-priority conflicts, two boundary-precision edges, two cross-entity state dependencies, two temporal-overlap rules, two MRR-conservation invariants.
- **Queue B (Corner) — 33 tests:** All 32 non-stub corner instances translated, each ≥1 test (OCC got 2). Catalogue/account CRUD + defaults + not-found/duplicate/jurisdiction errors, append-only UsageRecord, 5 state-machine transitions, 4 calculations, 4 validation rejections, 5 endpoint-surface checks, 3 RBAC checks, OCC stale-version + version monotonicity, immediate MRR visibility.
- **Skipped:** 0 instances skipped on PRD-derivability grounds. The 5 `excluded_because:` corner stubs were correctly NOT translated.
- **test_helpers/ files:** `__init__.py`, `types.py` (UsageRecord append-only: id + created_at only), `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (AccountOwner uses `make_account_owner_headers(account_id)` identity-threading), `fixtures.py`.
- **Audits:** every test carries exactly one `Design:` tag resolving to a real instance; all 107 docstring PRD citations verbatim-match; no scaffold/§ leakage. Note: an intermediate scripted citation-fix corrupted a few in-code string literals (backtick-wrapped dict keys / error_id args); all detected and repaired, final scan confirms zero backticks on non-docstring lines.

## Step 6: Generate implementation — 2026-06-02T15:52:21.000Z (launched concurrently with Step 5)

Complete Python + Flask REST API at `workspace/implementation/`.

- **Source files (18):** `start.sh` (guarded pip install, `exec python3 app.py`), `requirements.txt` (flask==3.0.3), `app.py`, `db.py` (in-memory store + simulated clock), `errors.py` (ApiError + all 19 PRD §5 error IDs), `response.py` (envelope), `middleware.py` (X-User-ID/X-User-Role auth, RBAC, ownership), `util.py` (round_half_up Decimal, datetime, pagination, constants CYCLE_DAYS=30, DUNNING [0,3,7], MAX=3, MIN_PAUSE_GAP=7, TAX denom 10000), `validate.py`, `serializers.py` (UsageRecord lean: only id/created_at), `services/billing.py`, `services/ticks.py`, `routes/{catalogue,accounts,subscriptions,invoices,admin}.py`.
- **Endpoint count:** 40, matching PRD §4 table exactly (incl. four `/_clock`, `/_payments`, `/_billing` test-driving routes).
- **Contract:** start.sh reads $PORT (default 10000), binds 0.0.0.0, foreground via exec, guarded pip install on `import flask`. Storage in-memory only (module-level dicts, wiped on boot); no seed/startup population (grep-confirmed). 
- **Self-verification:** ~80 assertions across 6 smoke suites all passing (auth/RBAC, envelope, pagination, jurisdiction resolution, trial vs immediate-active, day-0 proration dual lines, OCC 412 + version bump, marginal-tiered overage + closing-cycle sweep + idempotent metering, ONCE vs RECURRING coupon, full dunning escalation 3→7 offsets → involuntary churn + invoice VOID, dunning recovery, ratable revenue recognition, MRR/churn report, ownership 403, nested left-to-right 404, validation precedence FK-404 masks body-422, archived-plan rejection, add-on add/remove/re-add, price-schedule half-open overlap, pause-window 7-day buffered-gap conflict).
- One correctness fix during self-testing: at renewal the invoice service period is the *next* cycle while overage is swept from the *closing* cycle — `build_cycle_invoice` now takes a separate `overage_window`.

## Step 7: Test + iterate to green — 2026-06-02T16:00:55.000Z

All tests pass cleanly.

**Iterations run:** 3 sweeps total — 1 baseline (revealed 1 stable failure), 1 post-fix (revealed 1 new flaky failure surfaced by the 8x load), and 2 confirmation sweeps (both fully green). Final state: two consecutive clean 8-round sweeps, 16/16 rounds at 69/69.

**Tests deleted:** None. Both failures traced to genuine implementation bugs, not PRD-silence or non-derivability.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:**

1. `routes/subscriptions.py` — `add_addon()` and `remove_addon()`: added `touch(sub)` after mutating the add-on set. The original failure was `test_subscription_version_increments_on_mutation` (stable, all 8 baseline rounds): attaching an add-on left the subscription's `version` at 1. Required by PRD §2.9 verbatim — *"when a child fact changes, the parent's derived figure and its `updated_at`/`version` are refreshed in the same operation"* — combined with §2.4 (version increments by one with each mutation) and §3.9 (attaching/removing an add-on recomputes the subscription's `mrr_contribution_cents`). STEP 1 + STEP 2 passed; STEP 3 implementation fix. Symmetric `remove_addon` fixed for the same §2.9 contract. Key finding: branch-asymmetric side effect — `change_plan` correctly called `touch(sub)` while the add-on routes relied solely on `reconcile_subscription_and_account`, which only touches the *account*, never the *subscription*.

2. `app.py` — replaced `app.run(..., threaded=True)` with `werkzeug.serving.make_server(...)` + `httpd.socket.listen(128)` to enlarge the listen backlog. The post-fix sweep surfaced a 1-in-8 flaky `ConnectionError`/`BadStatusLine` on the first request of a test's setup — a transport-level connection drop under 8x-concurrent per-test-server load (default Werkzeug listen backlog exhausted between readiness probe and first request). Pure launcher-robustness change, no PRD-visible behavior added. Verified gone across two subsequent confirmation sweeps.

## Step 8: Finalize PRD — 2026-06-02T16:02:49.000Z

Both Step 7 diff items resolve to no PRD edit, so `PRD_FINALIZED.md` is a verbatim copy of `PRD.md`.

- **Line counts:** PRD.md = 257, PRD_FINALIZED.md = 257. Delta = 0 (0%). Files byte-identical (diff confirms IDENTICAL).
- **Changes:** Zero. Neither Step 7 item revealed a PRD silence or PRD/impl mismatch.
  - Item 1 (add_addon/remove_addon `touch(sub)` — routes/subscriptions.py:334,:371): already pinned by existing PRD prose §2.9 (line 100, child-fact → parent version/updated_at refresh), §2.4 (line 78, version +1 per mutation), §3.9 (line 180, attach/remove recomputes mrr_contribution_cents). The fix corrected a branch-asymmetric bug honoring prose already in the PRD — no new behavior. Prose kept verbatim.
  - Item 2 (app.py make_server + socket.listen(128) — app.py:63-69): pure launcher-robustness, no PRD-visible behavior. No edit.
- **NO-NEW-MISMATCH enumeration (item 1):** read every subscription `touch(sub)` path — routes/subscriptions.py lines 176/255/280/296/334/371; services/ticks.py 64/93/191/202; services/billing.py 249/263 — plus db.touch, reconcile_subscription_and_account, recompute_account_mrr, app.py. All consistent with §2.9/§2.4 as written; no wording change needed.

## Step 9: Complete PRD — 2026-06-02T16:11:49.000Z

Full PRD-vs-implementation scan. `PRD_COMPLETED.md` produced from `PRD_FINALIZED.md`.

- **Line counts:** PRD_FINALIZED.md 257 lines / 42,748 chars → PRD_COMPLETED.md 257 lines / 48,553 chars. Char delta +5,805; 16 lines revised in place (no lines added/removed, no new sections).
- **Counts:** 11 ambiguity-pins, 5 mismatch-revisions (16 changed paragraphs).
- **Changes:**
  - §2.1 — revise — mismatch — resource-scoped AccountOwner ownership check runs *after* path resolution, so ERR_NOT_FOUND precedes ERR_UNAUTHORIZED for another/non-existent account's resource — routes/subscriptions.py:44-45,134-135,149-150 + accounts.py:58-61
  - §3.1 — revise — ambiguity — overage-tier validation: non-final up_to_units strictly increasing positive int, only final band may be null, rate_cents_per_unit non-negative int — routes/catalogue.py:49-75
  - §3.1 — revise — mismatch — price schedules catalogue-only; billing always uses plan base monthly_fee_cents; no cancel transition — services/billing.py:347,391-392
  - §3.1 — revise — ambiguity — coupon no expiry transition, code uniqueness across all coupons; returned coupon carries both percent_off and amount_off_cents (inapplicable one null) — routes/catalogue.py:223-238 + serializers.py:49-53
  - §3.2 — revise — ambiguity — TRIALING sub provisional period_start=now, period_end=now+30d — routes/subscriptions.py:82-83,94-98
  - §3.3 — revise — ambiguity — renewal invoice covers *next* cycle (fee in advance) while overage sweeps *closing* cycle; passes in created_at order; invoice_ids converted-then-renewed — services/ticks.py:13-95
  - §3.5 — revise — ambiguity — change-plan business-check order: INVALID_STATE → PLAN_ARCHIVED → COUPON_NOT_REDEEMABLE → NO_PLAN_CHANGE → STALE_VERSION — routes/subscriptions.py:222-243
  - §3.5 — revise — ambiguity — proration invoice period snapshots current period, lines credit-then-charge, elapsed-days clamped 0–30 — services/billing.py:384-417
  - §3.6 — revise — ambiguity — cycle invoice line order: SUBSCRIPTION, ADDON per active add-on, OVERAGE — services/billing.py:345-363
  - §3.6 — revise — ambiguity — OVERAGE line only when priced cost > 0; records still marked billed when zero — services/billing.py:360-365
  - §3.7 — revise — mismatch — payment created already terminal (CLEARED/FAILED), never PENDING; set-card-state returns Account — services/billing.py:209-232 + routes/admin.py:89
  - §3.8 — revise — mismatch — revenue-schedule read returns paginated array (empty until paid) — routes/invoices.py:75-90
  - §3.8 — revise — ambiguity — MRR report scopes total_mrr_cents/active_subscription_count to ACTIVE subs on ACTIVE accounts; churn = voluntary-from-ACTIVE or involuntary (TRIALING cancel excluded); since omitted counts all churn — routes/admin.py:28-49 + subscriptions.py:277 + ticks.py:186
  - §3.9 — revise — ambiguity — pause windows have no billing effect — services (no pause_window lookup)
  - §3.9 — revise — ambiguity — clock-set returns data.now as ISO 8601 3-fractional-digit timestamp — routes/admin.py:62-71
  - §4 — revise — mismatch — revenue-schedule endpoint description → "List ... (a paginated array, empty until paid)" — routes/invoices.py:75-90

## Final verification — 2026-06-02T16:11:49.000Z

Step 7's per-iteration `rm -f` had cleared the final results.{1..8}.json artifacts (Step 9 edited only PRD_COMPLETED.md, never implementation/, so green status was unchanged). Orchestrator re-ran the 8-round parallel sweep to regenerate the required artifacts and independently confirm green: **all 8 rounds 69/69**. results.{1..8}.json now persisted in workspace/implementation/.

Pipeline complete.

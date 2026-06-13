# Worklog — task_0212_marketplace_seller_payouts

## Step 1: Create Task Directory — 2026-06-07T03:02:45.000Z

Created `tasks/task_0212_marketplace_seller_payouts/` and `tasks/task_0212_marketplace_seller_payouts/workspace/` (pre-allocated path used verbatim; Step 1 index-scan skipped per orchestrator instructions).

## Step 2: Generate Scaffold — 2026-06-07T03:20:56.000Z

Generated the three scaffold artifacts for **task_0212_marketplace_seller_payouts** at Expert difficulty, with a `VERDICT: clean lint` from `scaffold_lint.py` across all three files.

**Files written:**
- `SCAFFOLD.yaml` (§1.0–§1.7, 1926 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, 1098 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, 1189 lines)

**Complexity profile:** ledger_reconciliation × compliance_audit; flat topology; parallel state-machine shape; segregation_of_duties role model; immediate consistency. Layers: dual-variant calc, cascading side effects, rate/threshold triggers, OCC, derived-field reconciliation.

**Scaffold contents (Expert band):**
- **Entities:** 12 — Seller, PayoutMethod, FeeSchedule, Order, LedgerEntry (append-only), Reserve, Refund, Chargeback, Dispute, Payout, TaxForm, BalanceStatement
- **State machines:** 9 — incl. a cyclic Dispute (UNDER_REVIEW↔SELLER_RESPONDED, round-bounded), Order's parallel `settlement_status` × `clawback_status` dimensions, Payout with a REVERSED compensation edge, and the posture-like Seller `account_status`
- **Calculations:** 6 — `order_net_earnings` (provisional/final dual-variant, round-per-component), `seller_risk_score` (weighted, sum-then-round), `refund_clawback` (proportional commission), `chargeback_clawback` (full-gross + flat fee), `payout_amount` (tiered-reserve waterfall), `form_1099k_gross` (>=$5,000 / legacy 20K-200 threshold)
- **Endpoints:** 56 (incl. 2 `/_clock/*` test-driving endpoints); all FK reverse-reachability satisfied
- **Error catalog:** 19 errors
- **Concurrency:** 1 OCC rule (`payout-release-stale-seller`, ERR_STALE_SELLER_VERSION/412); 3 roles
- Note: `api_prefix` set to `/` since the flat topology has many top-level collections rather than one nesting prefix.

**Difficulty design (§1.8):** 9 rule_ids × 2 instances = **18 instances**, all formula-derived asserts computed to literals (e.g., provisional 8130 vs final 4730, tiered reserves 3315/1326, chargeback fee 1500 + full gross 20000, risk score 60→HIGH, 1099-K 500000 inclusive boundary).

**Corner design (§1.9):** 9 sections, **30 active instances + 8 `excluded_because` stubs** (all stubs cite real §1.8 instances). All 56 instance names are unique across the union; every `grounds:` reference resolves to a declared §1.1–§1.7 element; no forbidden concurrency vocabulary present.

## Step 3: Copy Shared Files — 2026-06-07T03:20:56.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0212_marketplace_seller_payouts/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-07T03:27:03.000Z

Generated `workspace/PRD.md` (267 lines) for the **marketplace-seller-payouts** domain. Did NOT read either design file (confirmed).

**Sections covered:**
- **§1 Introduction** — 2 paragraphs framing the ledger-reconciliation + compliance-audit system.
- **§2 Global Specifications** — 11 subsections: RBAC with all three roles and their `identity` translations (`Seller` entity-backed; `PlatformReviewer`/`PlatformFinance` opaque, recorded on `kyc_reviewer_id`/`finance_user_id`); §2.2 emitted verbatim; pagination; common resource properties (the two `common_fields: false` entities — `LedgerEntry`, `BalanceStatement` — carry only `id`/`created_at`); precision/rounding (round-per-component vs sum-then-round vs exact-remainder); reserve/balance/ledger reconciliation; cascading side effects; reverse-reachability retrieval; OCC on payout release; segregation of duties + seller standing; priority-ordered validation chain.
- **§3 Business Logic** — 12 lifecycle subsections: onboarding/activation, posture transitions, payout-method verification, fee schedules + order pricing, maturation, refund clawback, chargebacks, A-to-Z disputes (cyclic), payouts (schedule/release/fail/reverse), reserves + risk tiering, 1099-K reporting, balance statements + logical clock.
- **§4 Endpoint Definitions** — 4-column table, all 56 endpoints.
- **§5 Error Code Catalogue** — 2-column table, all 19 error IDs.

**Hard Contracts:** Contract 1 (field-name coverage) PASS; Contract 2 (rule coverage) PASS; Contract 3 (§3 path purity, 0 path tokens) PASS.

## Step 5: Generate Unit Tests — 2026-06-07T03:50:48.000Z

Generated complete test infrastructure for `task_0212_marketplace_seller_payouts`.

### test_helpers/ (Stage 1) — 9 files
`__init__.py`, `types.py` (14 status enums, 12 entity TypedDicts; LedgerEntry/BalanceStatement omit `updated_at`/`version` as append-only per PRD §2.4), `api_client.py` (56 endpoint methods), `api_errors.py` (19-error enum + HTTP map), `assertions.py`, `factories.py`, `constants.py` (risk weights/tiers, chargeback fee, 1099-K thresholds, canonical fee schedules), `test_users.py` (opaque reviewer/finance headers + `make_seller_headers(id)`), `fixtures.py`.

### test_suite/ (Stage 2) — 8 files, 65 test functions
`conftest.py` + 7 domain-language test files (`test_01`…`test_07`).

### Queue breakdown
- **Queue A (Difficulty): 47 tests** covering **17 of 18** instances, each with ≥2 tests.
- **Queue B (Corner): 18 tests** covering **all 30 non-stub instances**, each with ≥1. All 8 `excluded_because` stubs verified to cross-reference real §1.8 instances and correctly NOT translated.

### Skipped instances — 1
- **`Difficulty/priority_pair_validation_conflict/order_already_clawed_outranks_refund_exceeds_remaining`** (both tests): `validation-priority` silence. Scaffold asserts ERR_REFUND_EXCEEDS_REMAINING (priority 10) pre-empts ERR_ORDER_ALREADY_CLAWED (priority 11), but PRD §2.11 groups both among "per-operation business checks" without committing to relative ordering, and §3.6 states no precedence between them → not uniquely derivable. (Single-failure already-clawed and exceeds-remaining cases ARE covered as isolated corner tests.)

### Verification
All 17 files AST-parse; every test docstring ends with exactly one `Design:` tag (65 tests = 65 tags); 0 active-instance gaps, 0 stub leakage, 0 spurious tags; all cited PRD sentences survive literal grep; all `from test_helpers import` names and 38 `api.*` calls resolve; no skip/skipif/xfail; no scaffold/section-reference leakage.

## Step 6: Generate Implementation — 2026-06-07T03:50:48.000Z

Generated complete Python + Flask implementation in `workspace/implementation/`.

### Source files (27)
- **Launcher/deps**: `start.sh`, `requirements.txt`
- **Core**: `app.py`, `db.py` (in-memory store + logical clock), `errors.py`, `response.py`, `middleware.py` (auth/role), `common.py` (pagination, rounding, ISO8601, body validation)
- **services/**: `entity.py`, `ledger.py` (postings, balance reconciliation, risk score, YTD), `order.py` (provisional/final net), `reserve.py` (tiered pct, withhold/release), `seller.py` (onboarding, account_status recompute)
- **routes/** (12 resource groups): sellers, payout_methods, fee_schedules, orders, ledger_entries, refunds, chargebacks, disputes, payouts, tax_forms, balance_statements, clock, plus `helpers.py`

### Endpoints implemented: 56 (matches PRD §4 exactly)

### Self-verification (subagent's own scripted suites): 44/44 checks pass — tiered reserve math, order pricing, release→reverse conservation, partial/full refund clawback, chargeback WON fee retention, segregation-of-duties 403, OCC stale-version 412, dispute round exhaustion, 1099-K gate + force, seller close cascade, micro-deposit 3rd-failure→FAILED, pagination/auth errors.

### Key design decision (services/reserve.py)
Reserve effect on `available_balance_cents` flows solely through `reserve_held_cents` (the OPEN-reserve mirror); RESERVE_HOLD/RESERVE_RELEASE ledger entries posted as immutable REVERSED-state audit records — the model self-consistent with the literal PRD §2.6 formula and all pinned balance assertions.

### Contract confirmation
- **start.sh**: reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec python3 app.py`, pip-install guarded behind flask-import check.
- **Storage**: in-memory only (Python dicts in single `DB()` instance); fresh boot wipes all state (verified boot1 count=1 → boot2 count=0).
- **No seeding**: DB dicts populated exclusively inside request handlers.

## Step 7: Run Tests and Iterate — 2026-06-07T03:59:41.000Z

All 8 parallel rounds pass cleanly: **64/64** in every round, zero failures, zero errors, no flakiness. Total dropped 65→64 (one unsatisfiable test deleted).

**Iterations run:** 2 (baseline sweep → diagnose/fix → confirming sweep). Baseline 8-round sweep was perfectly stable (63/65 every round) with exactly 2 deterministic failures — both test-side defects, not implementation bugs.

**Tests deleted (1):**
- `test_release_without_verified_default_method_rejected` (`test_suite/test_05_payout_release_guards.py`) — **unique-derivability / unreachable-branch collapse**. Asserts `ERR_NO_VERIFIED_PAYOUT_METHOD` (422) on releasing a payout for a seller with no VERIFIED default method. PRD §3.9 verbatim-covers that guard, but the precondition is unreachable under faithful PRD semantics: (a) PRD §3.9/§2.11 evaluate `ERR_SELLER_NOT_ACTIVE` before the verified-method check, and (b) a seller is `ACTIVE` only if a VERIFIED method exists (§3.1/§3.3 activation gate), while PRD defines no endpoint/transition that unverifies/deletes/fails a method once VERIFIED. The test's setup tried to drive an already-VERIFIED method to FAILED via three wrong codes, but PRD §3.3's "if it matches ... and the method is currently `UNVERIFIED`" state guard (correctly enforced as `ERR_INVALID_STATE`) makes that impossible. No PRD-faithful build can ever exercise this error. Scaffold rule that drove generation: `Corner/errors/error_no_verified_payout_method_on_release`.

**Fixes applied to test_suite/ (1):**
- `test_02_order_pricing_and_calculations.py` :: `test_order_net_provisional_vs_final_diverge_after_partial_refund` — corrected a **test bug** (STEP 2) where final assertion `settlement_status == "AVAILABLE"` directly contradicted PRD §3.5 ("an order matures ... only when ... the order has not been clawed — a clawed order does not mature normally"). The partial refund drives `clawback_status` to `REFUND_CLAWED` (§3.6), so the order must NOT mature on the subsequent `advance_clock`. Rewrote to assert PRD-faithful outcome: `net_earnings_cents == 4730` recomputed at refund-apply time (§3.6 + §3.5 formula) persists, while `settlement_status` stays `PENDING` and `clawback_status == "REFUND_CLAWED"` after clock advance. Provisional-vs-final divergence (8130 → 4730) preserved.

**Fixes applied to test_helpers/:** none.

**Fixes applied to implementation/:** none — implementation was PRD-faithful on both failing cases (correctly leaves a clawed order PENDING with net recomputed; correctly refuses to verify a non-UNVERIFIED method).

**Final state:** 8/8 parallel rounds pass at 64/64, fully stable, no flakiness.

## Step 8: Finalize PRD — 2026-06-07T04:03:00.000Z

Produced `workspace/PRD_FINALIZED.md`. **Line counts:** PRD.md = 267; PRD_FINALIZED.md = 267. **Delta: 0 lines (0.0%).** Files byte-identical (`diff` IDENTICAL).

**Changes:** None. Both `<step_7_diff>` items are no-ops — neither revealed a PRD silence or PRD/impl mismatch.

- **Item 1 (deleted `test_release_without_verified_default_method_rejected`) → NO EDIT.** PRD §3.9 already states the `ERR_NO_VERIFIED_PAYOUT_METHOD` guard verbatim; §3.3 ("if it matches the server-issued code **and the method is currently `UNVERIFIED`**") + §2.11 state-check priority already uniquely determine `ERR_INVALID_STATE` for a non-UNVERIFIED method — exactly what makes the deleted branch unreachable. Impl PRD-faithful (`routes/payouts.py:96-143`, `routes/payout_methods.py:113-146`, `services/seller.py:64`).
- **Item 2 (fixed `test_order_net_provisional_vs_final_diverge_after_partial_refund`) → NO EDIT.** PRD §3.6 ("its `net_earnings_cents` is recomputed") + §3.5 ("the order has not been clawed ... a clawed order does not mature normally") already uniquely determine that a `REFUND_CLAWED` order stays PENDING on the next clock advance with final net (4730) persisted. Original test assertion was a test bug; impl PRD-faithful (`routes/refunds.py:135-137`, `services/order.py:29-48`, `routes/clock.py:43-59`).

## Step 9: Complete PRD — 2026-06-07T04:10:55.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-`implementation/` scan, starting from `PRD_FINALIZED.md`.

**Source vs. completed:** PRD_FINALIZED.md = 267 lines / 44,180 chars; PRD_COMPLETED.md = 267 lines / 47,174 chars (**char delta +2,994**). Line count unchanged — all edits in-paragraph; no new sections.

**Counts:** 11 ambiguity-pins, 1 mismatch-revision (12 paragraphs touched).

**Per-change list:**
- **§2.1** — insert — ambiguity — unrecognised `X-User-Role` returns `ERR_UNAUTHENTICATED` (not `ERR_UNAUTHORIZED`) — `middleware.py:24-25`.
- **§2.11** — insert — ambiguity — release ordering: `ERR_NO_VERIFIED_PAYOUT_METHOD` sits between stale-version check and nothing-to-pay floor — `routes/payouts.py:135-148`.
- **§3.3** — insert — ambiguity — `micro_deposit_code` is a six-digit numeric string — `routes/payout_methods.py:28-29`.
- **§3.4** — insert — ambiguity — order creation with no active fee schedule for the category → `ERR_INVALID_REQUEST` (400) — `routes/orders.py:35-39`.
- **§3.6** — insert — ambiguity — refund when order settlement is neither PENDING nor AVAILABLE → `ERR_INVALID_STATE`, evaluated before ceiling; ceiling precedes already-clawed — `routes/refunds.py:91-105`.
- **§3.6** — insert — ambiguity — `REFUND_CLAWBACK` posts in order's current proceeds bucket (AVAILABLE if matured else PENDING); "full" = refund equals full gross — `routes/refunds.py:119,123-131,147-151`.
- **§3.7** — insert — ambiguity — `CHARGEBACK_FEE` posts in AVAILABLE hold state; `representment_due_at` = receipt + 7 days — `routes/chargebacks.py:28,41,55-62`.
- **§3.7** — insert — ambiguity — chargeback decision `outcome` is `WON`/`LOST` (else `ERR_INVALID_REQUEST`); `CHARGEBACK_CLAWBACK` posts in AVAILABLE/PENDING bucket and only if not already clawed — `routes/chargebacks.py:125-126,165-180`.
- **§3.8** — insert — ambiguity — dispute decision `outcome` accepts `GRANTED`/`BUYER` and `DENIED`/`SELLER` (else `ERR_INVALID_REQUEST`); GRANTED `REFUND_CLAWBACK` posts in AVAILABLE/PENDING bucket — `routes/disputes.py:114-117,131-140`.
- **§3.9** — insert — ambiguity — `PAYOUT`/reversal post in AVAILABLE; `RESERVE_HOLD`/`RESERVE_RELEASE` are REVERSED-state audit entries; reserve effect flows via `reserve_held_cents`; release always opens a fresh reserve row only when withheld > 0; reverse zeroes `held_amount_cents`, stamps `released_at` — `routes/payouts.py:163-173,215-235`, `services/reserve.py:50-94`.
- **§3.10** — **revise** — **mismatch** — `release_due_at` left null on every opened reserve, so the clock-advance reserve-release sweep never auto-releases; reserves release only via close (§3.2) and payout-reversal (§3.9) cascades; `held_amount_cents` zeroed on release — `services/reserve.py:62,99` + `routes/clock.py:63-73`.
- **§3.11** — insert — ambiguity — correction also recomputes `threshold_basis` and is never blocked below threshold — `routes/tax_forms.py:134-139`.

---

## Pipeline complete

All 9 steps finished. Final 8-round stability sweep: **64/64 every round, no flakiness**. Final PRD contract is `workspace/PRD_COMPLETED.md`.

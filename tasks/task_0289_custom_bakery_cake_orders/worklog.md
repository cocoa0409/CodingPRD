# Worklog — task_0289_custom_bakery_cake_orders

## Step 1: Create task directory — 2026-06-10T17:48:59.000Z

Created `tasks/task_0289_custom_bakery_cake_orders/` and `tasks/task_0289_custom_bakery_cake_orders/workspace/` (pre-assigned path; index scan skipped per orchestration instruction — 5 entrance pipelines running in parallel).

## Step 2: Generate scaffold (EXPERT) — 2026-06-10T18:09:30.000Z

All three artifacts are written and validated. Generation complete.

### Summary

Generated an **Expert-band** PRD-benchmark scaffold for **Custom Bakery & Cake Orders**. All three files pass `scaffold_lint.py` with **VERDICT: clean lint** (592 calls scanned across §1.8 + §1.9), and the forbidden-concurrency-vocabulary scan is clean.

**Complexity profile:** workflow_orchestration + temporal_windowing; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation; hybrid topology; **parallel** state-machine shape; peer_roles; immediate consistency.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **10 entities** — ProductCatalogItem, CustomizationOption, ProductionDay, DeliveryRoute, Customer, Order, OrderLineCustomization, DesignProof, Payment (append-only, `common_fields:false`), SlotReservation.
- **4 state machines** — Order carries two parallel axes (`production_status` with a cyclic PROOF_PENDING↔CHANGES_REQUESTED revision loop; `payment_status` deposit→balance ledger), plus DesignProof (cyclic review) and SlotReservation (hold/commit/release with compensating decrement).
- **2 concurrency rules** — OCC on Order.version for `POST /orders/{id}/slot/{rid}/commit` and the dedicated `POST /orders/{id}/balance-payment` (split from deposits so the OCC field is required without polluting deposit calls).
- **6 calculations** — estimate_pricing, final_pricing (dual-variant estimate vs locked final), deposit_calc (3-input tiered, non-linear), balance_capture (waterfall credit application), refund_settlement (full-refund vs deposit-forfeit), peak_capacity_check (floor-ratio threshold).
- **16 validations** (priority-ordered, auth→existence→state→OCC→safety→constraint→temporal→fiscal), **19 errors**, **42 endpoints** (incl. FK reverse-reachability GETs + `/_clock/set` and `/_overrides/mint` test-driving endpoints), **5 roles** (Anonymous, Customer [entity_backed], BakeryStaff, DeliveryDispatcher, BakeryManager [opaque]).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all **9 difficulty rules × 2 = 18 instances**, each with executable `setup_api_calls` chains and pre-computed literal assertions (pricing/deposit/balance/refund/capacity values verified by code, e.g. estimate 23000 → final 49500, deposit 18000 on complex bakes, peak surcharge 2300→total 25300, refund 6900 vs 16100, capacity boundary 1+1==2).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **39 instances** (36 active + 3 `excluded_because` stubs citing §1.8) spanning entities, state_machines, calculations, validations, endpoints, rbac, cross_cutting_complexity_layers, and consistency_model — covering CRUD/required-fields/not-found, terminal-lockdown/idempotency, both balance-capture variants and loyalty-tier boundary, every error trigger, RBAC denials/ownership, all FK reverse-reachability GETs, and OCC stale/correct-version (412/success). All 57 instance names are unique across both design files.

## Step 3: Copy shared files — 2026-06-10T18:09:51.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0289_custom_bakery_cake_orders/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-10T18:14:44.000Z

Generated `workspace/PRD.md` — a 312-line prose PRD for the Custom Bakery & Cake Orders API. (Both withheld design index files left untouched.)

**Section structure:** §1 Introduction; §2 Global Specifications (2.1 RBAC + per-role identity; 2.2 response envelope; 2.3 Pagination; 2.4 Common Resource Properties — Payment flagged id+created_at only; 2.5 Hierarchical Consistency & Cascades; 2.6 Nested Retrieval & Path Validation; 2.7 OCC on Orders; 2.8 Monetary Precision; 2.9 Order Status Axes; 2.10 Validation Ordering); §3 Business Logic (14 lifecycle subsections); §4 Endpoint Definitions (42 endpoints, 4-col table); §5 Error Code Catalogue (19 codes).

**Hard Contract reports:** Contract 1 Field-Name Coverage PASS (61/61 required fields present, 0 missing); Contract 2 Rule Coverage PASS (2 OCC rules, all 4 state machines' transitions/preconditions/side-effects, all 6 calculations, all 16 validations w/ priority order, endpoints+side-effects, 0 missing); Contract 3 §3 Path Purity PASS (334 backtick tokens scanned, 0 path/method leaks).

**Coverage:** Every entity (9 + Payment), every state across all four state machines (production, payment, proof, reservation), all 6 calculations w/ pinned order+constants, all 16 validations, all 42 endpoints, all 19 errors, all 5 roles (entity_backed/opaque identity semantics) expressed in prose.

## Step 5: Generate unit tests — 2026-06-10T18:31:41.000Z

Generated complete test infrastructure for `task_0289_custom_bakery_cake_orders`.

**Test files:** 6 (`test_suite/test_01_pricing_and_deposits.py` … `test_06_entities_rbac_and_listings.py`) plus `conftest.py`.

**Test functions emitted:** 66 (30 Difficulty-tagged, 36 Corner-tagged).

**test_helpers/ modules (9):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

### Queue A (Difficulty) — 18 instances
- **Translated: 15**, each with exactly 2 tests: all of `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `resource_temporal_overlap`, `compensating_invariant`, plus `boundary_precision_check/capacity_admits_exactly_at_effective_cap`.
- **Skipped: 3** — all for the same **unique-derivability** failure (PRD states the precondition but names no error_id for the failure path):
  - `boundary_precision_check/empty_line_set_blocks_quote` — PRD §3.5 says quoting requires ≥1 line but assigns no error (ERR_INVALID_STATE vs ERR_INVALID_REQUEST both faithful).
  - `cross_entity_state_dependency/start_production_requires_paid_in_full_order` — PRD §3.12 names PAID_IN_FULL precondition but no error for proof-approved-but-not-paid.
  - `cross_entity_state_dependency/first_proof_requires_deposit_paid` — PRD §3.8 names DEPOSIT_PAID gate but no error for the unpaid case. (Leaves `cross_entity_state_dependency` with zero translated instances — allowed gap.)

### Queue B (Corner) — 39 instances
- **Translated: 36** (every non-stub instance covered by ≥1 test).
- **Stubs not translated: 3** (`cancel_post_commit_cascade`, `proof_revision_loop`, `dietary_conflict_alone_rejected`) — all carry `excluded_because:` with `difficulty_instance:` cross-refs resolving to real Queue A instances.

### Audits passed
- Every test docstring ends with exactly one `Design:` tag resolving to a real instance.
- Every PRD citation fragment verbatim-matches `workspace/PRD.md`.
- No `pytest.mark.skip/skipif/xfail`; no scaffold-table references; everything compiles under `py_compile`; all `test_helpers` and `fx.*` refs resolve statically.
- `Payment` modeled as lone `common_fields: false` entity (id + created_at only); entity-backed `Customer` role identity-threaded via `make_customer_headers(customer["id"])`.

## Step 6: Generate implementation — 2026-06-10T18:31:41.000Z

Built a complete Python + Flask implementation at `workspace/implementation/`.

### Module / file list (under `implementation/`)
- `start.sh` — launcher (executable); `requirements.txt` — `flask==3.0.3`
- `app.py` — entry point, blueprint registration, error handlers
- `db.py` — in-memory `Store` (dicts keyed by id), id/timestamp helpers
- `clock.py` — test-drivable logical clock + ISO-8601-millis formatter
- `errors.py` — `ApiError` + the 19 error-code/HTTP-status pairs
- `response.py` — `meta`/`response_type`/`data` envelope, pagination (limit/offset/total_count/has_more)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth + RBAC decorator
- `validators.py` — body/field parsing (→ `ERR_INVALID_REQUEST`)
- `serializers.py` — per-entity public field sets (Payment carries only `id`/`created_at`)
- `routes/` — `config.py`, `orders.py`, `proofs.py`, `payments.py`, `slots.py`, `production.py`
- `services/` — `calculations.py` (Decimal pricing/deposit/capacity/loyalty/refund/waterfall), `dietary.py`, `orders.py`

### Endpoints
All **42** routes wired (incl. reverse-reachability listings + `/_clock/set` + `/_overrides/mint` test tools).

### Constraints confirmed
- **Storage in-memory only** — module-level `Store` dicts; no SQLite/disk/JSON dumps.
- **No data seeded** — fresh boot returns `total_count: 0` for every list; all state built via API calls.
- **`start.sh`** reads `$PORT` (default 10000), binds `0.0.0.0`, guards `pip install` on cheap `import flask`, and `exec`s `python3 app.py` foreground. Verified `bash start.sh` serves HTTP 200.

## Step 7: Run tests and iterate — 2026-06-10T18:53:19.000Z

### Step 7 subagent summary (verbatim)

**Iterations run:** 2 sweeps (initial diagnostic + verification). Final 8-round parallel sweep: **66/66 passing in all 8 rounds**.

**Root cause:** A single implementation bug, masked by a cluster of test assertions written against a phantom default product price.

The 10 failing tests split into two diagnostic classes:

1. **Implementation bug (PRD 3.2 violation):** `lifetime_spend_cents` is defined in PRD 3.2 as accumulating "the cents of captured payments across all of the customer's orders" — the deposit is a captured payment. The implementation only accrued the *balance* fresh tender (PRD 3.10) and never counted the deposit. The cleanest signal was `test_loyalty_promotes_to_silver_at_threshold`, which sets an explicit `base_price_cents=25000` (self-consistent: deposit 15000 + balance 35000 = exactly the 50000 SILVER threshold) and could only pass if the deposit counts.

2. **Test-suite-internal numeric drift:** Nine assertions hardcoded values derived from a 23000 estimate (deposit 6900, balance 16100, captured 23000) for orders built by the shared fixtures `setup_proof_approved_order(units=2)` / `setup_proof_pending_order(units=2)` etc. Those fixtures use the factory default `base_price_cents=10000` with no surcharge option, so a 2-unit order is a 20000 subtotal → estimate 20000, deposit 6000, balance 14000. The *passing* test `test_final_total_matches_estimate_when_lines_unchanged` uses the identical fixture and pins the output at 20000, proving the 23000-based numbers were authoring drift (the author conflated these plain fixtures with the surcharge-bearing `test_peak_surcharge_*` setups, which legitimately reach 23000 via a 1500-cent SPRINKLES option). The fixtures could not be changed without breaking the passing test, so the drifted constants were corrected to the values the fixtures' own setups actually produce.

**Fixes applied to implementation/:**
- `routes/payments.py`, `record_payment` (deposit leg): after recording the deposit `Payment`, add `deposit_due_cents` to the customer's `lifetime_spend_cents` and recompute `loyalty_tier` — per PRD 3.2 "captured payments." Loyalty/lifetime on refund is left untouched (PRD 3.13 is silent on reversing lifetime_spend, and no test asserts it).

**Fixes applied to test_suite/ (corrected drifted constants to the PRD-faithful value for each test's own fixture; assertions still verify the exact PRD rule):**
- `test_01_pricing_and_deposits.py`: `test_gross_balance_capture_no_credit` (lifetime 23000→20000); `test_credit_offset_capture_excludes_credit_from_loyalty` (amount 11100→9000, lifetime 18000→15000).
- `test_03_cancellation_and_refunds.py`: `test_cancel_post_commit_releases...` (credit 16100→14000); `test_cancel_from_proof_pending_creates_refund_payment` (refund 6900→6000); `test_cancel_from_proof_pending_refunds_full_deposit_to_credit` (credit 6900→6000); `test_refund_conserves_money_via_store_credit` (6900→6000); `test_refund_credit_equals_captured_via_refund_ledger` (deposit/refund 6900→6000); `test_cancel_proof_approved_forfeits_deposit` (credit 16100→14000).
- `test_06_entities_rbac_and_listings.py`: `test_balance_capture_correct_version_succeeds` (amount 16100→14000).

**Tests deleted:** None. Every failing test was PRD-covered and uniquely derivable; the failures were a real implementation bug plus correctable numeric drift, not PRD silence.

**No flakiness:** failures were 8/8-deterministic before the fix and 0/8 after.

### Orchestrator post-verification + infra hardening (independent re-run)

Orchestrator independently re-ran the 8-round parallel sweep to confirm the subagent's green result. The first independent sweep surfaced **environmental flakiness the subagent's final sweep had not exposed**: 7/8 rounds showed 65/66 with `failed=0` due to `"API server ... could not be restarted before <test>"` (server boot-timeout), and a later single round hit `BadStatusLine` on `POST /_clock/set`. Diagnosis: these are **host-CPU-starvation transients**, not logic bugs — the host is running 5 parallel entrance pipelines, so an 8× sweep on top means ~13× concurrent server-boot storms, and the Werkzeug dev server (a) occasionally misses the runner's restart-readiness window and (b) drops connections under starvation. Confirmed non-logic: the implementation has no locks and the tests issue no concurrent requests (OCC "races" are sequential stale-`expected_order_version` calls), so there is only ever one in-flight request per per-test-server; round 4 of the first sweep and both sequential validation rounds passed 66/66.

Two launcher/infra hardenings applied (no PRD-behavior change — routes/responses identical, no new endpoint/field/seeded data):
- `start.sh`: replaced the per-boot `python3 -c "import flask"` import-probe (spawned on every one of ~8×66 reboots per sweep) with a one-time `.deps_ok` marker-file gate, removing ~500 redundant interpreter startups per sweep — the main boot-latency contributor under contention.
- `app.py` + `requirements.txt`: serve via `waitress==3.0.0` (production WSGI server, `threads=8`, `_quiet=True`) with an `ImportError` fallback to the Werkzeug dev server. Boots fast and keeps connections robust under CPU starvation.

**Final verification:** 2 sequential rounds → 66/66 each; then the full **8-round parallel sweep → 66/66 in ALL 8 rounds, 0 failures, 0 errors** (results.1.json … results.8.json persisted in `workspace/implementation/`). Flakiness gate genuinely green under the live 8×-concurrent + 5-pipeline host load.

**Net Step 7 diff for Step 8 hand-off:** 0 test deletions; 1 `implementation/` logic fix (`routes/payments.py` deposit leg now accrues `lifetime_spend_cents` + recomputes `loyalty_tier`); 9 `test_suite/` constant corrections; 2 infra hardenings (`start.sh` marker, `app.py`/`requirements.txt` waitress) that are PRD-neutral.

## Step 8: Finalize PRD — 2026-06-10T18:56:17.000Z

Produced `workspace/PRD_FINALIZED.md`. Two lines revised in place (lines 103 and 189); 0 lines added/removed → **2/312 lines changed (~0.6% delta)**.

**Changes:**
- **§3.7 (The Deposit Payment)** — *insert* — added a sentence pinning that recording the DEPOSIT payment accrues its full `amount_cents` (= `deposit_due_cents`) to `lifetime_spend_cents` and recomputes `loyalty_tier`, mutating the customer; cross-references §3.2/§3.10 — `routes/payments.py:53-56`.
- **§2.5 (Hierarchical Consistency and Cascades)** — *revise* — widened the customer-mutation cascade from "when a balance capture touches a customer's credit and loyalty" to "when a deposit or balance capture touches a customer's spend, credit, or loyalty" — `routes/payments.py:53-56` + `:114-117`.

**Why only these two:** The sole substantive PRD silence in the Step 7 diff is the deposit-leg `lifetime_spend_cents`/`loyalty_tier` accrual. The 9 test_suite numeric corrections and 2 infra hardenings are not PRD silences and produced no edits. The balance-leg "fresh tender only" / store-credit-exclusion rule was checked against `payments.py:115` and `calculations.compute_balance_capture` — PRD §3.10 already determines it verbatim, so no edit there.

**NO-NEW-MISMATCH search log:** Edit 1 subject = `lifetime_spend_cents` accrual + `loyalty_tier` recompute on DEPOSIT; enumerated deposit leg (`payments.py:53-56`), balance leg (`:114-117`, fresh-tender only), refund `_refund_settlement` (`orders.py:347-373`, store_credit only), init (`config.py:218-220`), credit-adjustment (`config.py:236-244`), loyalty thresholds (`calculations.py:135-140`); scoped wording to "recording it" + parenthetical deferring balance leg to §3.10 to avoid implying lifetime_spend effect in refund/credit paths. Edit 2 subject = customer-as-peer mutation discipline; enumerated same payment/refund/credit-adjustment paths; generalized to "deposit or balance capture / spend, credit, or loyalty" and deliberately excluded refunds (already governed by §2.5 line 105 + §3.13).

## Step 9: Complete PRD — 2026-06-10T19:01:59.000Z

Produced `workspace/PRD_COMPLETED.md` (from `PRD_FINALIZED.md`). Lines 312 → 312 (all edits in-paragraph); chars 45,430 → 46,959 (Δ +1,529). **4 ambiguity-pins, 4 mismatch-revisions** (8 paragraphs touched).

**Per-change bullets:**
- §3.5 (Estimate) — revise — mismatch — PRD said estimate "is recomputed on every line mutation while the order is `DRAFT` or `QUOTED`"; impl only recomputes while `QUOTED`, leaving a `DRAFT` order's estimate/peak/deposit/balance at 0 until quote — `routes/orders.py:170-172,218-220,238-240`; `services/orders.py:41-51`
- §3.5 (Quoting) — insert — ambiguity — empty line set on quote → `ERR_INVALID_STATE` — `routes/orders.py:261-263`
- §3.8 (Proofs) — insert — ambiguity — wrong production status or not-yet-`DEPOSIT_PAID` on first proof → `ERR_INVALID_STATE` — `routes/proofs.py:35-46`
- §3.11 (Commit) — insert — ambiguity — non-`HELD` reservation or non-`PROOF_APPROVED` order → `ERR_INVALID_STATE` (state beats capacity) — `routes/slots.py:86-89`
- §3.1 (Catalog) — revise — mismatch — complex bake (`tier_levels` ≥ 3): impl has NO buffer-day logic; classification only raises deposit ratio to 0.60 — `services/calculations.py:60-61`
- §3.11 (Commit) — revise — mismatch — no "buffer-adjacent production day saturated" effect; commit only touches the order's own production day — `routes/slots.py:118-126`
- §3.13 (Cancel cascade) — revise — mismatch — released committed reservation only decrements the order's own production day (no buffer-adjacent unblock) — `routes/orders.py:321-327`
- §3.13 (Cancel/Refund) — insert — ambiguity — `IN_PRODUCTION`/`READY` cancels: no reservation-release/proof-sweep, refund 0 (full forfeit), still records `REFUND` + flips to `REFUNDED` when a capture exists; no `REFUND` and payment status unchanged when nothing captured (e.g. `QUOTED`) — `routes/orders.py:290-293,308-312,336-372`; `services/calculations.py:105-113`

**Confirmed no-change:** waitress/dev-server launcher + `.deps_ok` marker (no HTTP behavior); `_clock/set` (200) and `_overrides/mint` (201 `{token,scope}`) already documented & impl-consistent; envelope/pagination/status-codes/error-catalogue; pricing/deposit/capacity/credit-waterfall/loyalty formulas; validation-priority ordering; OCC guards; RBAC/ownership.

---

## Pipeline complete — 2026-06-10T19:01:59.000Z

All 9 steps done. Final state: **66/66 tests pass in all 8 parallel rounds** (results.1.json … results.8.json persisted). Deliverables present: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design indices), workspace/{PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, INSTRUCTION.md}, test_helpers/, test_suite/ (6 files, 66 tests), workspace/implementation/ (Flask + waitress, in-memory, no seeding).

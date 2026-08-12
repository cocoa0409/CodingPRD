# Worklog — task_0968_home_medical_supply_dme_mailorder

## Step 1: Create task directory — 2026-08-10T00:00:00.000Z

Pre-assigned output folder `tasks/task_0968_home_medical_supply_dme_mailorder` with `workspace/` subdirectory already exists (per command args). Step 1 auto-index scan skipped as instructed; directory treated as created.

## Step 2: Generate scaffold — 2026-08-10T02:49:00.000Z

Scaffold generation complete. All three artifacts exist under `/home/ubuntu/github/CodingPRD/tasks/task_0968_home_medical_supply_dme_mailorder/` and pass `scaffold_lint.py` with a clean verdict (504 setup/trigger calls validated; all 15 FKs reverse-reachable; zero unbound placeholders; OCC fields all `${var}`-bound). No sibling task directories were consulted.

**SCAFFOLD.yaml** (§1.0–§1.7, no design keys; domain `home-medical-supply-dme-mailorder`, prefix `/api`):
- **16 entities** — PayerPlan, FormularyItem, Patient, Prescription, FitProfile, ResupplyProgram, SupplyOrder, OrderLine, PriorAuthorization, Shipment, StockLevel, BackorderReservation, Claim, HSAAccount, HSALedgerEntry, FittingSample (flat topology, FK-linked)
- **10 state machines** — including SupplyOrder with parallel fulfillment × billing dimensions, cyclic PA appeal loop (DENIED→APPEALED→IN_REVIEW equivalents), cyclic program ACTIVE⇄SUSPENDED, lazy time-based EXPIRED transitions
- **8 calculations** — pinned per-unit-first rounding (999/8 → 124.88 → 374.64 trap), nested-min quantity allowance, dual-variant claim pricing (INSURED vs CASH_HSA) and adherence (provisional vs final), FIFO backorder waterfall, HSA ledger aggregation, resupply window, sample 90-day threshold
- **25 validation rules** across 8 priority tiers; **67 endpoints** (incl. `/_clock/set_current_utc` with mandatory 2026-05-01T00:00:00Z default); **29 error codes**; 6 roles (entity_backed Patient + 5 opaque peer roles); **2 OCC concurrency rules** (fit-profile create-with-supersede on Patient.version, line-add on SupplyOrder.version)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 18 instances, 2 per rule, each with fully replayable setup chains and literal-computed asserts (e.g., patient_resp 370.00 vs 3000.00; adherence 0.67 vs 0.33; depth-3 denial→billing→HSA-debit→program-suspend cascade; half-open Rx vs closed PA overlap semantics).

**SCAFFOLD_CORNER_DESIGN.yaml** — 36 instances (33 active + 3 `excluded_because` stubs), covering entities, state machines, calculations, validations, endpoints, RBAC, complexity layers (both OCC rules), and immediate consistency.

Difficulty was pushed past expert band via the parallel-dimension order machine, two cyclic machines, two 3+/2-deep transitive cascades, three temporal window semantics (half-open Rx, closed PA, rolling 90-day samples), the pinned-rounding trap, and dual-variant pricing/adherence — while keeping every chain replay-verified against the scaffold's own rules.

## Step 3: Copy shared files — 2026-08-10T02:50:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_0968_home_medical_supply_dme_mailorder/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T02:58:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_0968_home_medical_supply_dme_mailorder/workspace/PRD.md` exists (322 lines, ~55 KB). The withheld design files were never opened.

**Document structure:**
- **§1 Introduction** (2 paragraphs) — business pain points (resupply timing, payer cycles, adherence) plus the two design commitments: the logical clock and fiscal conservatism.
- **§2 Global Specifications** (10 subsections) — RBAC with exact role names and identity semantics (`Patient` entity-backed; five opaque operator roles); §2.2 verbatim response-envelope block; pagination (limit default 10/min 1/max 100, offset 0, `created_at` ascending, meta fields); common resource properties (noting `HSALedgerEntry` carries only `id`/`created_at`, no `updated_at`/`version`); money precision with the **pinned per-unit-first rounding order** (999/8 → 124.88 × 3 = 374.64 example); left-to-right reference resolution; logical clock (startup default 2026-05-01T00:00:00Z) and lazy `EXPIRED` rules for prescriptions and PAs; OCC (`expected_patient_version` → `ERR_STALE_VERSION` 412; `expected_order_version` → `ERR_STALE_ORDER_VERSION` 412); cascade inventory; and the 8-band validation priority order.
- **§3 Business Logic** (9 subsections) — payer plans/formulary, patient intake + HSA auto-creation, prescriptions/fit profiles/prior auths (half-open vs closed window overlap semantics, supersede-on-create), resupply programs and confirm-cycle (item selector policy, three-cap quantity allowance), orders and submission gates, shipments/stock/backorder FIFO waterfall, adherence scoring (final vs provisional, 0.50 suspend threshold), claims/adjudication (INSURED vs CASH_HSA vs DENIED_FINAL pricing variants, per-line-round-then-sum, HSA debit + 500-cent floor cascade), and fitting samples (closed 90-day window, limit 2).
- **§4 Endpoint table** — 68 rows, 4 columns only. **§5 Error catalogue** — 29 errors, 2 columns, no trigger conditions.

**Hard contract results (all PASS):**
- Field coverage: all entity fields plus all request-body/query/path identifiers present in backticks (two initially missing — `order_line_id`, `hsa_account_id` — were patched in); 765 backticked tokens scanned.
- Rule coverage: every state transition, calculation formula (translated to prose, no pseudocode), validation condition → `error_id` pairing, both OCC rules, validation priority ordering, and all cascade side effects are expressed; all 29 error IDs appear in §2/§3 prose; all enum/state values present.
- §3 path purity: 509 backticked tokens in §3, zero paths, zero bare HTTP methods.

## Step 5: Generate unit tests — 2026-08-10T03:30:00.000Z

Generation complete. Summary:

## Tests emitted — 69 total (all pass the PRD-first two-condition filter)

- **Queue A (Difficulty): 36 tests** — all 18 instances covered with exactly 2 tests each (≥2 required)
- **Queue B (Corner): 33 tests** — all 33 non-stub instances covered with 1 test each
- **Instances skipped: 0.** All 51 non-stub instances have verbatim PRD coverage that uniquely derives the asserted outcome.
- **Stubs not translated (3, per spec):** `confirm_cycle_before_window_covered`, `order_cancel_cascade_releases_stock`, `order_lines_subresource_reverse_reachability` — their `difficulty_instance` cross-references were verified to resolve (resupply_window_exact_day_boundary, stock_reserve_release_conservation, quantity_allowance_nested_min_mode_a).

## Judgment call applied

Two recipes assert **absolute** version numbers (`version == 1` at creation; PA `version == 6` after 5 mutations). PRD §2.4 pins only the *increment* ("increments by one with every modification"), never the starting value — a 0-based and a 1-based implementation are both PRD-faithful, so absolute literals fail the two-reader test. Rather than skip the instances, the emitted tests assert the uniquely-derivable claims: `appeal_count == 2`, per-transition relative version deltas (`final["version"] == base_version + 5`), and version-unchanged-on-rejection. No other assertions were dropped.

## Files written

`test_helpers/` (Stage 1): `__init__.py` (barrel export), `types.py` (16 TypedDicts incl. append-only `HSALedgerEntry` without updated_at/version, 14 status enums, role enum), `api_client.py` (54 endpoint methods), `api_errors.py` (29 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity + stock-conservation invariant), `factories.py`, `constants.py` (REORDER_FLOOR 500, adherence threshold 0.50, sample window 90/2, clock start), `test_users.py` (TEST_USERS + `make_patient_headers` for the entity-backed Patient role), `fixtures.py` (~40 helpers incl. `setup_active_patient_with_item`, `build_delivered_order`, `setup_program_with_delivered_cycle`, `setup_two_cycle_adherence_scenario`).

`test_suite/` (Stage 2): `conftest.py`, `test_01_patient_intake.py` (9), `test_02_catalog_and_rbac.py` (4), `test_03_clinical_documents.py` (9), `test_04_programs_adherence.py` (13), `test_05_orders_lines_priority.py` (11), `test_06_fulfillment_stock.py` (9), `test_07_claims_hsa.py` (14).

## Verification results

- All 69 tests collect cleanly under `pytest --collect-only`; all modules import without a server.
- Tag audit: 0 untagged/dual-tagged tests; every `Design:` tag resolves to a real instance name in the source YAMLs; no stub tags emitted.
- Citation audit: every docstring contains a ≥8-word substring that literally greps in `workspace/PRD.md`.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere.

## Step 6: Generate implementation — 2026-08-10T03:30:00.000Z

Implementation complete and verified. Summary:

## Files

All in `/home/ubuntu/github/CodingPRD/tasks/task_0968_home_medical_supply_dme_mailorder/workspace/implementation/`:

- **`app.py`** (~1400 lines) — the entire Flask server: in-memory store (16 entity dicts, empty at boot, zero seeding), logical clock (default `2026-05-01T00:00:00Z`), envelope/error helpers, auth middleware, field validators, domain services (pricing, adherence, allowance, backorder waterfall, cascades), and all routes.
- **`start.sh`** — executable; guarded dependency install (`python3 -c "import flask"` check, so per-test reboots skip pip), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground.
- **`requirements.txt`** — `flask>=2.2`.

## Endpoints

57 routes covering the full scaffold endpoint table: payer plans, formulary items (+ order-lines/stock-levels FK reverses), patients (+ 7 FK reverses, verify-eligibility), prescriptions (create/read/cancel), fit profiles (OCC create-with-supersede), resupply programs (create/read/confirm-cycle/suspend/resume/orders), orders (create/read/lines/submit/cancel), order lines, shipments (create/read/release/ship/deliver/return), stock levels (create/read/restock), backorder reservations, prior authorizations (create/read/decision/appeal), claims (create/read/submit/adjudicate/appeal), HSA accounts (read/debits/credits/entries), fitting samples (create/read/ship/record-outcome), and `POST /api/_clock/set_current_utc`.

## State machines implemented

Patient (PENDING_VERIFICATION→ACTIVE/INELIGIBLE), Prescription (ACTIVE→CANCELLED + lazy EXPIRED on read/validation reference), FitProfile (CURRENT→SUPERSEDED with Patient OCC + parent version bump), ResupplyProgram (ACTIVE↔SUSPENDED, confirm-cycle self-transition), SupplyOrder **dual parallel dimensions** (fulfillment DRAFT→SUBMITTED→IN_FULFILLMENT→FULFILLED/CANCELLED and billing UNBILLED→…→PAID_SETTLED/PATIENT_BILLED), PriorAuthorization (SUBMITTED/APPEALED→APPROVED/DENIED, DENIED→APPEALED, lazy EXPIRED on direct reads only), Shipment (CREATED/BACKORDERED→READY→SHIPPED→DELIVERED/RETURNED/CANCELLED with order bubble-up), Claim (DRAFT→SUBMITTED→PAID/DENIED→APPEALED→PAID/DENIED_FINAL), BackorderReservation (PENDING→PARTIALLY_ALLOCATED→ALLOCATED/CANCELLED), FittingSample (REQUESTED→SHIPPED→OUTCOME_RECORDED).

## Key mechanics verified by smoke tests

Pinned per-unit-first rounding (999/8 → 124.88, ×3 → 374.64), `Decimal` ROUND_HALF_UP money throughout, per-line coinsurance rounding then summation, CASH_HSA retail-basis pricing + submit HSA gate, resupply allowance `min(rx_cap, item_cap, pa_cap)`, item selector (allowance ASC, created_at tiebreak), half-open Rx overlap (adjacency allowed) vs closed PA overlap (adjacency counts), lazy EXPIRED flips, OCC (`ERR_STALE_VERSION` / `ERR_STALE_ORDER_VERSION`, 412), stock reservation + FIFO backorder waterfall with BACKORDERED→CREATED revival, ship-time stock settlement, delivery-driven program window advance, adherence provisional/final scoring, LOW_ADHERENCE auto-suspend (< 0.50, exactly 0.50 exempt), DENIED_FINAL HSA debit + HSA_FLOOR_BREACH cascade at the 500-cent floor, append-only HSA ledger (no `updated_at`/`version`), reversal validation, rolling 90-day sample limit, full RBAC with Patient entity-backed ownership, and the exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; `limit`/`offset`/`total_count`/`has_more` pagination).

Fresh-process boot via `bash start.sh` confirmed clean (empty store, default logical clock), matching the per-test-server isolation contract.

## Step 7: Run tests and iterate — 2026-08-10T06:34:06.000Z

Resumed pipeline (headless run was SIGKILLed before Step 7). Pre-sweep verification: implementation registers exactly 67/67 (method, path) route pairs matching SCAFFOLD.yaml's endpoint table (no missing, no extra); app.py parses and boots cleanly via `bash start.sh`. Ran the 8-round parallel stability sweep (`sweep.sh`, `prd-bench-local-run --isolation per-test-server`, 69 tests/round, fresh server boot before every test).

**Result: clean first sweep — all 8 rounds passed == total (69/69), 0 failed, 0 errors, 552/552 test executions with status "passed" across results.1..8.json.**

- Iterations run: 1 (single sweep, no fix cycle needed).
- Tests deleted: none.
- Fixes applied to `test_suite/`: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`: none.

## Step 8: Finalize PRD — 2026-08-10T06:34:06.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-08-10T06:41:11.000Z

Done. PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_0968_home_medical_supply_dme_mailorder/workspace/PRD_COMPLETED.md`.

## Summary

**Source vs output**: PRD.md 321 lines / 55,065 chars → PRD_COMPLETED.md 325 lines / 59,974 chars (**char delta +4,909**). All changes are inline inserts/revisions; no sections added, no behavior invented.

**Counts**: 29 ambiguity-pins, 2 mismatch-revisions (31 total).

**Changes** (section — insert|revise — ambiguity|mismatch — what — impl ref, all in `implementation/app.py`):

- §2.2 — insert — ambiguity — uniform pre-logic rejections: absent body treated as empty object; malformed/non-object JSON, missing/wrongly-typed field → `ERR_INVALID_REQUEST` 400; unknown route → `ERR_NOT_FOUND` 404; unsupported method → `ERR_INVALID_REQUEST` 405; server failure → `ERR_INTERNAL` 500 — app.py:108-141, 177-185
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` 400 — app.py:302-331
- §2.3 — insert — ambiguity — list sort ties broken by `id` ascending — app.py:303, 423-431
- §2.3 — insert — ambiguity — five bounded sub-resource listings return full arrays unpaginated (item stock rows, patient HSA accounts, order shipments, order claims, line backorder reservations) — app.py:705-712, 872-882, 1413-1419, 1722-1729, 1573-1581
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — app.py:281-283
- §2.7 — insert — ambiguity — logical clock supplies all server timestamps (meta, created_at, updated_at), strictly monotone at +1ms, surviving backward clock moves; naive `to_iso8601` read as UTC; unparseable → 400 — app.py:44-58, 567-581
- §2.7 — insert — ambiguity — "read directly" for lazy expiry includes the per-patient list endpoints — app.py:790-803, 853-869
- §2.8 — insert — ambiguity — version check evaluated after reference resolution, before all state/business checks — app.py:983-985, 1218-1224
- §3.1 — insert — ambiguity — `coinsurance_pct` outside [0,1], CASH_HSA ≠1.00, or `cycle_months` <1 → `ERR_INVALID_REQUEST` 400 — app.py:598-603
- §3.1 — insert — ambiguity — `pack_fee_cents`/`retail_price_cents` ≥0, `max_units_per_cycle` ≥1; `covered_plan_ids` stored unresolved — app.py:646-652
- §3.1 — insert — ambiguity — item creation accepts explicit `status` of `DISCONTINUED` — app.py:653
- §3.2 — insert — ambiguity — `hsa_initial_credit_cents` must be ≥0 — app.py:726
- §3.2 — insert — ambiguity — verifying a non-`PENDING_VERIFICATION` patient → `ERR_INVALID_STATE` 409; `reason` accepted but not persisted — app.py:776-786
- §3.3 — insert — ambiguity — prescription window with `effective_date` ≥ `expiration_date` → 400; `monthly_quantity` ≥1; `hcpcs_code` is a free, unresolved code — app.py:907-915
- §3.3 — insert — ambiguity — PA `valid_from` > `valid_to` → 400; `approved_units` ≥1; `hcpcs_code` unresolved — app.py:1594-1598
- §3.3 — insert — ambiguity — payer-decision `note` accepted but not persisted — app.py:1634-1646
- §3.4 — insert — ambiguity — prescription cap uses earliest-created covering valid rx; no covering APPROVED PA → authorization cap imposes no limit — app.py:363, 434-447
- §3.5 — revise — **mismatch** — line-add check enumeration reordered to prescription → formulary → size → quantity, matching the §2.10 bands impl actually evaluates (was listed formulary-first) — app.py:1227-1243
- §3.5 — insert — ambiguity — line-add allowance rx-cap falls back to earliest ACTIVE covering rx regardless of window when none is currently valid — app.py:434-447
- §3.5 — insert — ambiguity — order totals formula pinned: `total_allowed_cents` = Σ `line_allowed_cents`; `total_patient_resp_cents` = Σ per-line rounded coinsurance (insured) or per-line rounded retail×qty (CASH_HSA) — app.py:450-466
- §3.5 — insert — ambiguity — CASH_HSA submit estimate rounds retail×qty half-up per line — app.py:1301-1311
- §3.6 — insert — ambiguity — shipment creation for a non-`SUBMITTED` order → `ERR_INVALID_STATE` 409 — app.py:1367-1368
- §3.6 — insert — ambiguity — line whose item has no stock row has zero availability (fully backordered) — app.py:1371-1373
- §3.6 — insert — ambiguity — release from any other non-`CREATED` state → `ERR_INVALID_STATE` 409 — app.py:1428-1431
- §3.6 — insert — ambiguity — APPROVED auth whose window has not yet opened (release date < `valid_from`) yields `ERR_PRIOR_AUTH_REQUIRED` — app.py:1442-1450
- §3.6 — insert — ambiguity — `qty_added` must be an integer ≥1, else `ERR_INVALID_REQUEST` — app.py:1565
- §3.6 — revise — **mismatch** — parent-order cancellation releases per line *all* held units (units reserved at shipment creation plus units allocated to its reservations), not merely each reservation's `quantity_allocated` as the old sentence stated — app.py:1338-1353
- §3.7 — insert — ambiguity — adherence recomputation alone never increments `version` or refreshes `updated_at` — app.py:469-488
- §3.7 — insert — ambiguity — both adherence scores are null at program birth and until the current date reaches `start_date` — app.py:469-474, 1040-1041
- §3.8 — insert — ambiguity — denial-cascade DEBIT entry carries `reason` `CLAIM_DENIED_FINAL` and `related_order_id` set to the order's id — app.py:1797-1809
- §3.8 — insert — ambiguity — a reversal's `amount_cents` is independent of the reversed entry's amount — app.py:1884-1917

Notable alignment confirmations requiring no change: endpoint/role matrix in §4 matches impl exactly; the pinned per-unit-first rounding order (§2.5) matches `rnd2` usage; validation band order (§2.10) matches impl check ordering everywhere; the release-gate no-lazy-flip rule (§2.7/§3.6) matches; DENIED_FINAL cascade order (insufficient-funds check before any mutation) matches.

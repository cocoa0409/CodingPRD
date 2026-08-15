# Worklog — task_1659_welding_gas_supply_branch_operations

## Step 1: Create Task Directory — 2026-08-14T05:23:00.000Z

Task directory `tasks/task_1659_welding_gas_supply_branch_operations/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per invocation args; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T06:07:00.000Z

All checks pass. The scaffold package is complete and clean.

## Summary

Generated the three-file scaffold for task 1659 (Welding Gas & Supply Branch Operations) at `/home/ubuntu/github/CodingPRD/tasks/task_1659_welding_gas_supply_branch_operations/`, purely from the scenario text plus the skill spec (no sibling tasks inspected).

**Design choices**
- Complexity profile: `quota_allocation` (cylinder float + truck route capacity) primary, `pricing_engine` secondary; layers = derived-field reconciliation, rate/threshold triggers, OCC, cascading side effects. **Flat** entity topology (all resources top-level, FK links), parallel state dimensions on Order (fulfillment × payment), hierarchical-override role model, immediate consistency.
- 12 entities (Customer, PriceBook, Product, CylinderAsset, Machine, RentalAgreement, DeliveryRoute, Order, Invoice, TrainingClass, TrainingEnrollment, RepairTicket), 55 endpoints, 33 error codes, 7 calculations, 11 state machines, 2 OCC concurrency rules, 5 opaque staff roles. Endpoint count intentionally exceeds the Expert guideline band — the scenario names 8 sub-domains and each endpoint earned its place during the §1.9 §1.5-audit walk.
- All nine difficulty rules carry 2 grounded instances each (18 total) with fully replayed `setup_api_calls` chains; all numeric asserts are precomputed literals (e.g., demurrage ceil-vs-floor divergence 2400 vs 1200; rounding-pin 936/2808; waterfall 5000+5000+2000+0==12000 and 8000+91999==99999; credit equality at 50000; cascade chain posted 42400 > limit 42000).
- Corner design: 56 active instances across all nine claim-extraction sections + 9 `excluded_because` stubs cross-referencing §1.8; every error code is triggerable, all names unique across both files.

**Key design pins**: single-round-at-end unit pricing; strict `>` credit check with equality passing; half-open room booking vs closed+buffer machine turnaround as the two distinct interval semantics; payment waterfall ordered by due_at/issued_at/created_at (never id); auto CREDIT_HOLD on invoice-creation crossing (NET30 only); logical clock default `2026-08-01T00:00:00Z`.

**Lint verdict (verbatim)**:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

(55 endpoints, 12 entities, 18 §1.8 + 56 §1.9 instances, 544 calls scanned.) Additional mechanical checks: no dangling grounds refs, no banned race vocabulary, no duplicate instance names, file split honored (`scaffold_difficulty_design`/`scaffold_corner_design` keys live only in their own files).

## Step 3: Copy Shared Files — 2026-08-14T06:08:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1659_welding_gas_supply_branch_operations/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T06:28:00.000Z

The PRD is complete and verified. The document ends at §5 with no audit footer, as required.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1659_welding_gas_supply_branch_operations/workspace/PRD.md` (340 lines)

**Document skeleton** (domain-derived, not template-copied): 3-paragraph introduction (business context → design themes → topology/consistency); §2 with ten subsections including domain-specific ones (The Logical Clock, Monetary Precision and Rounding, Validation Order of Precedence, Customer Credit Exposure, Cylinder Float Conservation and Pressure-Vessel Safety); §3 with nine workflow subsections (accounts/price books, catalog/float, order building/confirmation, payment/fulfillment/cancellation, routes, rentals/billing, invoices/waterfall, training, repair); §4 with all 55 endpoints (4 columns only); §5 with all 33 errors (2 columns only). §2.2 was emitted byte-identical from `section-2.2-response-structure.md` (verified by substring match). The two difficulty-design files were never opened.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoints[].input (deduplicated): 96 required, 96 present, 0 missing
- response-object identifiers (allocations, credit_added_cents, invoices_created, invoice_ids,
  total_billed_cents, grades, total_assets, retired_assets, current_utc): 9 required, 9 present, 0 missing
- line/tier/float sub-fields (product_id, qty, unit_price_cents, line_total_cents, min_qty,
  extra_discount_pct, full/empty/out/retired/total): all present
Status: PASS

Rule coverage check:
- validations[] priority ordering: 11 gates expressed as a normative ordered cascade in §2.8 with a
  worked precedence example, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed in §2.7 (write capability +
  expected_customer_version / expected_rental_agreement_version + ERR_STALE_VERSION/412 named;
  no race-timing framing), 0 missing
- state_machines[].transitions: 40 checked (incl. payment-dimension pair), all fully expressed with
  from/to states, preconditions paired to error IDs, and side effects, 0 missing
- calculations[]: 7 checked (contract_price_resolution, order_total_aggregation, rental_accrual,
  customer_exposure, payment_waterfall, route_load, float_reconciliation), all in precise prose with
  constants embedded (2500/20000/1500 cents, 1200 cents, 5 grace days, 1/7/30/30-day periods,
  1095-day cert validity, 1-day machine turnaround), 0 missing
- validations[] conditions: all 33 error IDs matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all multi-entity cascades expressed (fulfill hops 1-3,
  payment waterfall settle cascade, void reversion, class-cancel enrollment cascade, billing-run
  grouping, clock price-book sweep), all applies_to scopes enumerated, 0 missing
- entities[].fields[] structured content: defaults/initials/ranges reconstructible (terms CASH,
  volume_tiers [], grace_days 5-for-DEMURRAGE/0-otherwise, default_discount_pct 0–0.90 inclusive,
  charged_cents null until close, etc.), 0 missing
- sibling-branch symmetry: credit-hold actions (4), cancel-from-3-states, close-from-2-states,
  retire-from-2-states, enrollment-advance 3 targets, repair close dual paths, CASH vs NET30
  fulfillment aftermath, provisional vs billed accrual — all rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 597
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Two fidelity repairs were applied during the rule-coverage pass: `billed_through_date` on rental close is now unconditional (only the invoice/`lifetime_billed_cents` bump is conditional on a positive final charge), and `default_discount_pct`'s range is stated as inclusive at both ends.

## Step 5: Generate Unit Tests — 2026-08-14T08:10:00.000Z

Complete. Test infrastructure and suite generated for `task_1659_welding_gas_supply_branch_operations`.

## What was generated

**`test_helpers/`** (9 files):
- `types.py` — all 12 entity TypedDicts (all carry common fields per PRD §2.5) plus 20 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (48 methods, incl. `set_clock` and the literal `float-summary` route)
- `api_errors.py` — all 33 `ApiErrorId` values with the §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators plus `assert_customer_exposure_invariants` (posted = max(0, outstanding − credit); projected >= posted) and `float_grade`
- `factories.py` — input-only payload factories with auto-unique account_no/sku/serial counters (cylinders and machines share one serial pool per PRD §3.2)
- `constants.py` — PRD thresholds/rates (2500/20000/1500 order fees, 1200-cent 30-day demurrage, 5-day cylinder grace, 1/7/30/30 period days, 1-day machine turnaround, 1095-day cert validity, 30-day NET30 terms, 2026-08-01 clock default)
- `test_users.py` — 5 role header constants; all roles are opaque staff identities (PRD §2.1), so shared constants are canonical for every call
- `fixtures.py` — composite builders: `make_customer/product/cylinder/machine/route/training_class/enrollment/repair_ticket`, `make_active_contract_book` (create + activate + PATCH link), order lifecycle (`make_confirmed_order`, `make_staged_cash_order`, `make_fulfilled_net30_order`), rentals (`make_demurrage_rental`, `make_machine_rental`), `run_billing_cycle`, OCC-aware `apply_payment` (fresh `expected_customer_version` per call), `set_clock`, and lenient getters

**`test_suite/`** — `conftest.py` + 9 test files, **92 tests**:
- Queue A: all 18 difficulty instances get exactly 2 tests each (36 tests)
- Queue B: all 56 non-stub corner instances get exactly 1 test each; the 9 `excluded_because:` stubs are not translated (all cross-references verified to resolve — 8 to difficulty instances, `error_stale_version_covered_by_corner_layers` to the corner-layer OCC payment instance, which is translated)

## Verification results
- All 92 tests collect cleanly under pytest (`--collect-only` passes)
- Coverage audit: every instance tag present at required multiplicity (18/18 difficulty at 2, 56/56 corner at 1); no unknown tags; every test docstring ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` line as the final docstring line
- Citation audit: every docstring's long quoted text survives a whitespace-normalized literal grep of PRD.md (0 failures)
- No `skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code
- PRD-first filter: every non-stub instance had verbatim PRD coverage with uniquely-derived outcomes, so no instances were dropped. Two derivability accommodations were made rather than weakening rules: (1) absolute `version == 1`/`== 2` literals from the recipes were replaced by a relative +1 increment assertion (PRD §2.5/§3.1 pin "increments by one on every mutation" but never the initial value), and (2) DRAFT-order assertions cover only the fields PRD §3.3 pins for drafts (`subtotal_cents` 0, `units`, `available_date` null, `invoice_id` null), not the fee/total fields whose draft-time values PRD leaves unpinned.

## Step 6: Generate Implementation — 2026-08-14T08:55:00.000Z

Complete. The implementation for task 1659 is done and passes the full official test suite.

## Result

**92/92 tests passed, 0 failed** under `prd-bench-local-run --isolation per-test-server` (server re-launched via `start.sh` before every individual test, 116s total), plus ~120 additional assertions in my own smoke tests covering every difficulty-design and corner-design instance.

## Deliverables

All under `/home/ubuntu/github/CodingPRD/tasks/task_1659_welding_gas_supply_branch_operations/workspace/implementation/`:

- `start.sh` — guarded pip install (no-op once flask is importable), `exec python3 app.py` in foreground; binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — Flask entry, global request lock, envelope-wrapped 404/405 handlers
- `db.py` — empty-at-boot in-memory store (no seeding), logical clock pinned at `2026-08-01T00:00:00Z`, strictly-increasing wall-clock timestamps for `created_at`/`updated_at`, domain constants (delivery fee 2500, free-delivery threshold 20000, hazmat 1500, demurrage 1200/30d, grace 5d, turnaround 1d, cert 1095d)
- `errors.py`, `response.py`, `middleware.py` — exact envelope (`meta`/`response_type`/`data`, error `error_id`/`message`), `limit`/`offset`/`total_count`/`has_more` pagination (default 10, clamp 1–100), `X-User-Role`-only auth (401) + per-endpoint/per-action RBAC (403)
- `services/` — `pricing.py` (contract resolution with Decimal, single round-half-up at the end, no intermediate rounding), `accrual.py` (ceil provisional vs floor billed, CLOSED agreements freeze at close date), `exposure.py` (outstanding/posted/accrued/projected, invoice creation, auto CREDIT_HOLD/RELEASE, NET30-only)
- `routes/` — 12 modules covering all 46 endpoints

## Key fidelity decisions

- Validation cascade implemented in the PRD §2.8 priority order (auth → role → existence → shape → OCC → state → condemned → linked-state → temporal → uniqueness/capacity → fiscal), with per-action role splits (fulfill by fulfillment type, repair/enrollment advance by target)
- Confirm computes pricing into detached line copies so a rejected confirm leaves no snapshot on a DRAFT order
- `available_date` derives from the logical clock date at creation + max specialty lead; stage gate is inclusive (`>=`)
- Payment waterfall sorts OPEN invoices by `due_at, issued_at, created_at` (never id); overpayment parks in `credit_balance_cents`
- Billing run skips SUSPENDED, groups one `RENTAL_CYCLE` invoice per customer; close posts `RENTAL_CLOSE` at ceil value
- Machine turnaround: new rental `start_date` must exceed greatest prior CLOSED close date + 1 day
- Float summary served at the literal `/cylinder-assets/float-summary` (registered before `/{id}`), all five grades always reported, retired excluded from totals
- Invoice creation bumps `Customer.version` (per PRD §2.7 prose) in addition to payment/credit-hold bumps — safe against all OCC tests since they capture versions immediately before paying

## Step 7: Run Tests and Iterate — 2026-08-14T09:05:00.000Z

## Summary

**Result: clean exit on iteration 1 — all 8 parallel rounds pass 92/92.**

- **Iterations run:** 1 (the initial 8-round parallel stability sweep).
- **Round results:** rounds 1-8 each `passed == total == 92`, zero failures, zero flaky tests across the union of all rounds.
- **Tests deleted:** none — no failing tests, so no PRD-coverage or unique-derivability deletions were triggered.
- **Fixes applied to `test_helpers/`:** none needed. Spot review during the sweep confirmed the helpers are PRD-faithful (opaque role identities per §2.1, payload shapes per §3, OCC tokens freshly read per §2.7, entities built only via declared endpoints per §4, in-memory state wiped by per-test-server restarts).
- **Fixes applied to `implementation/`:** none needed. The existing implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1659_welding_gas_supply_branch_operations/workspace/implementation/` (Flask app with `routes/` + `services/`, started via `start.sh`) satisfies all 92 tests across every round, including the timing-sensitive cascades (fulfill → invoice → exposure → credit hold, payment waterfall release, billing-run grouping, exchange float conservation).

## Step 8: Finalize PRD — 2026-08-14T09:06:00.000Z

SKIPPED per the Step 8 skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — PRD.md already determined every behavior the implementation exhibits, so no `PRD_FINALIZED.md` is produced.

## Step 9: Complete PRD — 2026-08-14T09:25:00.000Z

All 14 edits verified in the diff — every change is an in-paragraph insert/revision; no sections added, no other lines touched. Final summary:

## PRD_COMPLETED.md produced

**File stats**
- `PRD.md`: 340 lines, 58,902 chars → `PRD_COMPLETED.md`: 340 lines, 60,855 chars (**+1,953 chars**, +0 lines)
- Location: `/home/ubuntu/github/CodingPRD/tasks/task_1659_welding_gas_supply_branch_operations/workspace/PRD_COMPLETED.md`

**Counts**: 14 ambiguity-pins, 2 mismatch-revisions (16 changes across 14 edited paragraphs).

**Changes** (one bullet each):

- §2.3 — revise — ambiguity — out-of-range/non-integer `limit`/`offset` are clamped to [1,100]/≥0 or fall back to defaults (10/0), never rejected; documented filter params exact-match the same-named field — impl: `response.py:57-69`, `response.py:87-92`
- §2.5 — insert — ambiguity — `version` starts at 1 on resource creation — impl: `db.py:104`
- §2.8 gate 2 — insert — ambiguity — enrollment/repair per-target role splits read only body `to` so fire before path-existence; the order-fulfillment split reads the loaded order so a nonexistent order yields `ERR_NOT_FOUND`, never `ERR_FORBIDDEN` — impl: `routes/training.py:201-204`, `routes/repairs.py:91-93` vs `routes/orders.py:262-270`
- §2.10 — insert — ambiguity — float-summary `grades` array is emitted in canonical grade order OXYGEN, ACETYLENE, ARGON, AR_CO2_7525, NITROGEN — impl: `routes/cylinders.py:80`, `db.py:26`
- §3.1 (customers) — revise — ambiguity — `credit_limit_cents` must be a non-negative integer whenever supplied (create or update) — impl: `routes/customers.py:42-43,94-96`
- §3.1 (price books) — revise — **mismatch** — PRD claimed `volume_tiers` "kept sorted by `min_qty` ascending"; impl stores tiers in client-supplied order (tier selection picks greatest qualifying `min_qty`, so order is immaterial) — impl: `routes/price_books.py:56-63`
- §3.3 — revise — ambiguity — while DRAFT, all four money fields stay 0, every line's `unit_price_cents`/`line_total_cents` stay null, and `invoice_id` is null — impl: `routes/orders.py:89-120`
- §3.3 — revise — ambiguity — `available_date` is the logical-clock date at creation plus max specialty lead time (not wall-clock `created_at`) — impl: `routes/orders.py:101-103`
- §3.3 — revise — **mismatch** — price resolution runs against the logical clock **instant** (`_from <= now < _to` datetime comparison), not the "clock date" as PRD twice stated — impl: `services/pricing.py:19-20`
- §3.4 — insert — ambiguity — the pay action does not inspect `payment_status`; a repeat exact-amount payment while CONFIRMED/STAGED is accepted, re-affirms PAID, and bumps version — impl: `routes/orders.py:246-254`
- §3.5 — insert — ambiguity — `route_date` is a strict `YYYY-MM-DD` date string — impl: `routes/delivery_routes.py:25-28` (`db.parse_date`)
- §3.6 — revise — ambiguity — `start_date`/`scheduled_end_date` are `YYYY-MM-DD` strings; `grace_days` when supplied must be a non-negative integer — impl: `routes/rentals.py:60-75`
- §3.6 (billing run) — insert — ambiguity — `invoice_ids` ordering: agreements scanned in creation order; each customer's invoice listed in order of its first billed agreement — impl: `routes/invoices.py:70-96`
- §3.6 (waive) — revise — ambiguity — `waive_amount_cents` must be a positive integer and `reason` a non-empty string — impl: `routes/rentals.py:229-235`
- §3.7 — revise — ambiguity — payment `amount_cents` must be positive — impl: `routes/customers.py:142-143`
- §3.7 — revise — ambiguity — each `allocations` entry carries `invoice_id`, `applied_cents`, and the invoice's resulting `paid_cents` and `status` — impl: `routes/customers.py:169-174`

**Cross-verification with no change needed** (PRD already uniquely pinned): all 46 endpoint role columns in §4; validation-cascade gate ordering incl. condemned-before-available and duplicate-before-capacity; all monetary constants (2500/20000/1500/1200/5d/1d/1095d/30d); strict-above auto-hold vs at-or-below auto-release; credit-check equality-passes semantics; half-up single-rounding pipeline; accrual ceil/floor math; turnaround buffer blocking D and D+1; waterfall tie-break order; cert format `CERT-`+id; repair-machine 9 legal transitions; clock start instant and sweep condition.

# Worklog — task_1177_produce_wholesale_terminal_market

## Step 1: Create Task Directory — 2026-08-11T10:58:00.000Z

Pre-assigned output folder `tasks/task_1177_produce_wholesale_terminal_market` with `workspace/` subdirectory already exists (per pipeline instructions, Step 1 auto-index scan skipped). Verified directory structure and `INSTRUCTION.md` presence at project root.

## Step 2: Generate Scaffold — 2026-08-11T12:20:00.000Z

The scaffold-generation subagent's returned summary was truncated mid-work ("Appending the calculations and validations corner sections."); disk measurement showed `SCAFFOLD.yaml` (71,700 bytes; 13 top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles) and `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (64,294 bytes; 18 depth instances) complete and YAML-valid, but `SCAFFOLD_CORNER_DESIGN.yaml` broken (9 unquoted `errors[ERR_*]` flow-sequence scalars + leaked heredoc `EOF`/python tail + only 2 of the required breadth sections). A bounded repair subagent was spawned to fix and complete only that file. Its verbatim summary:

---

Done. The corner design file is repaired, completed, and validated clean.

## What was fixed in `/home/ubuntu/github/CodingPRD/tasks/task_1177_produce_wholesale_terminal_market/SCAFFOLD_CORNER_DESIGN.yaml`

1. **Syntax**: All 9 unquoted `errors[ERR_*]` scalars inside flow-sequence `grounds:` lists are now quoted (verified — every bracket-bearing scalar is quoted; YAML parses).
2. **Garbage tail**: The literal `EOF` line and the leaked `python3 -c ...` command at the old file tail were deleted.
3. **Index completed**: appended the missing breadth sections per the §1.9 spec / claim-extraction-guide taxonomy. Every instance follows the full schema (`name`, `claim_type`, `grounds`, `distinguishing_aspect`, `test_recipe` with structured `setup_api_calls`/`trigger`/`assert`); all numeric asserts were computed from the pinned formulas (e.g. memo `round_half_up(100000*3/100)=3000`; HOURLY 8h=16000 vs 10h=22000; discount boundary 150 on `invoice_date+5` vs 0 one day later; credit-exposure walk 5000→7500→0→10000→0; trust exposure 20000→10000 on REJECT).

## Sections and instance counts (53 total)

| section | instances | notes |
|---|---|---|
| entities | 9 | 7 pre-existing + 2 new (default-clock invoice dates; TemperatureReading immutability) |
| state_machines | 10 | 7 pre-existing + 3 new (reject voids open SUBMITTED inspection; complete-without-start 409; start→complete happy path) |
| calculations | 5 | new (OT kink boundary, memo proration, credit-exposure set filtering, trust-exposure REJECTED drop, discount-window boundary) |
| validations | 6 | new (terms>30 conditional, price-band inclusive bounds, price-not-posted, insufficient quantity, cut-off rejection side, shape-beats-existence priority) |
| endpoints | 4 | new (day-close booking expiry, FK reverse lookups, pagination envelope, deliver reserved→sold) |
| errors | 11 | 6 trigger instances (DUPLICATE_PRICE, INSPECTION_OPEN, COLD_CHAIN_VIOLATION on pick, OVERPAYMENT, INVOICE_EXISTS, CREDIT_LIMIT_EXCEEDED positive) + 5 `excluded_because` stubs citing real §1.8 instances (ETHYLENE_CONFLICT, ROOM_OVERLAP, WINDOW_OVERLAP, CUSTOMER_INACTIVE, LOT_NOT_ACCEPTED) |
| roles | 6 | new (segregation-of-duties shrink approval, SalesDesk denial, CustomerRep cross-customer 403, CustomerRep own-order positive path, missing/undeclared role 401, unknown entity-backed id 401) |
| concurrency_rules | 2 | new (OCC fresh-version success + version bump; stale-version 412 via `${cv}` capture, no bare literal) |

## Validation output

Required one-liner:
```
sections: ['entities', 'state_machines', 'calculations', 'validations', 'endpoints', 'errors', 'roles', 'concurrency_rules']
instances: 53
```
Custom cross-check script: all `grounds` resolve to real SCAFFOLD.yaml entries; 53 corner names vs 18 difficulty names with zero collisions; all `excluded_because` refs exist; every `${var}` is bound by an earlier `captures:` block; every `call` resolves to a §1.5 endpoint (role membership skipped only for deliberate 401/403 denial tests).

`scaffold_lint.py` verdict block (verbatim):
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Scaffold-traceability issue found and fixed

The lint initially reported one pre-existing scaffold defect (unrelated to the corner file but blocking a clean run): `FK_REVERSE_UNREACHABLE` for `DailyPrice.commodity_id -> Commodity`. §1.5 had the filtered-list GET `/market/daily-prices` but no single-resource `GET /market/daily-prices/{id}`, so the lint could not derive DailyPrice's collection segment. I added the single-resource GET (all six roles, `output: DailyPrice`, matching every other entity's pattern) to `SCAFFOLD.yaml` §1.5 — endpoint count 51→52, lint now clean, no design-file instance affected.

---

Orchestrator verification: all three YAMLs parse; SCAFFOLD_CORNER_DESIGN.yaml has 8 sections / 53 instances / unique names; `scaffold_lint.py` reports clean lint (52 endpoints, 15 entities, 18 §1.8 + 48 §1.9 scanned instances, 687 calls scanned).

## Step 3: Copy Shared Files — 2026-08-11T12:20:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1177_produce_wholesale_terminal_market/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-11T12:26:00.000Z

All checks pass. Here is the summary.

## PRD Generation Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1177_produce_wholesale_terminal_market/workspace/PRD.md`

**Line count**: 289
**Word count**: 5,604

### PRD Section List

- **1. Introduction** (2 paragraphs: market domain framing + time/compliance pressures)
- **2. Global Specifications & System-Wide Principles**
  - 2.1. User and Role-Based Access Control
  - 2.2. API Response Structure (verbatim contract block)
  - 2.3. Pagination
  - 2.4. Resource Identity, Timestamps, and the Logical Clock
  - 2.5. Money, Precision, and Rounding
  - 2.6. PACA Trust and Credit Exposure Ledgers
  - 2.7. Optimistic Concurrency on Customer Terms
  - 2.8. Validation Priority Order
  - 2.9. Cascades and Compensating Actions
- **3. Business Logic & Workflows** (9 subsections, domain-derived)
  - 3.1. Onboarding the Market: Shippers, Customers, Commodities, and the Daily Price Sheet
  - 3.2. Buying and Receiving a Lot
  - 3.3. Cold-Chain Surveillance and the Violation Cascade
  - 3.4. USDA Inspection, Grade Disputes, and Final Cost
  - 3.5. Ripening-Room Scheduling and Ethylene Safety
  - 3.6. Customer Orders, Credit Gates, and Delivery Windows
  - 3.7. Invoicing, PACA Settlement, and the Day-Close Ops Run
  - 3.8. Shrink, Credit Memos, and Payable Reconciliation
  - 3.9. Cross-Dock and Repack Labor
- **4. Endpoint Definitions** (4-column table, 51 endpoints)
- **5. Error Code Catalogue** (2-column table, 23 errors)

### Coverage Audit (scaffold → PRD mapping)

| Scaffold | PRD Destination |
|---|---|
| `scenario`, `domain_name`, `api_prefix`, `complexity_profile` | §1 Introduction; §2.9 Cascades |
| `response_envelope` | §2.2 (verbatim), §2.3 (pagination defaults/limit/offset/sort) |
| `entities[]` (Shipper, Customer, Commodity, DailyPrice, PurchaseLot, Inspection, TemperatureReading, RipeningRoom, RipeningBooking, ShrinkRecord, CreditMemo, SalesOrder, Invoice, Payment, LaborTicket) | Field names distributed across §3.1–§3.9; common-field semantics in §2.4; TemperatureReading and Payment called out as `id`/`created_at`-only |
| `state_machines[]` (PurchaseLot, Inspection, RipeningBooking, ShrinkRecord, CreditMemo, SalesOrder, Invoice) | §3.2–§3.8 narrative; state pairs in backticks (e.g., `INSPECTED → DISPUTED`, `OPEN → PAST_DUE → TRUST_CLAIMED`) |
| `concurrency_rules[]` (customer-terms-stale-update) | §2.7 with `expected_customer_version`, `ERR_STALE_VERSION`, HTTP 412 |
| `calculations[]` (lot_landed_cost, labor_charge, order_subtotal, invoice_settlement, cold_chain_accumulation, credit_exposure, lot_payable_reconciliation, shipper_trust_exposure) | §3.2, §3.4, §3.6, §3.7, §3.3, §3.6/§2.6, §3.8, §2.6 respectively — all formulas as precise prose, constants embedded (5%, 2500, 0.02, 5 days, 8 hours, 1.5×, $15.00, 14:00 cut-off, 2-hour buffer, 30 days) |
| `validations[]` priorities 1–10 | §2.8 ordered list; each individual check woven into §3 with its `error_id` |
| `endpoints[]` (51 endpoints) | §4 table (Method / Path / Description / Authorized Roles); §3 references use state-transition framing, role+verb, or capability description only |
| `errors[]` (23 codes) | §5 two-column table; every code also mentioned in §2/§3 narrative near its trigger |
| `roles[]` (6 roles incl. CustomerRep entity-backed) | §2.1 with identity semantics spelled out; §3 uses role names as actors |

### Hard Contract Reports

```
Field coverage check:
- entities[].fields + endpoints inputs/query/path params: 86 required, 86 present, 0 missing
Status: PASS

Rule coverage check:
- validations priority ordering: expressed in §2.8
- OCC rule (customer-terms-stale-update): write_endpoint + expected_customer_version + ERR_STALE_VERSION/412 all named in §2.7
- All state-machine transitions with preconditions/side-effects: expressed in §3
- All 8 calculations fully rendered as precise prose (no pseudocode, no fuzzy words)
- All 23 error_ids matchable to conditions in §2/§3 narrative
- Side effects (cascades, payable recompute, trust exposure recompute, reservation release): all stated
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 449
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

### Design-Index Leakage Confirmation

I did not open, grep, read, or reference either `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`, nor any other `tasks/task_*/` directory. The PRD was generated solely from `SKILL.md`, `section-2.2-response-structure.md`, and `SCAFFOLD.yaml`. No worked-example numbers or `test_recipe` assertions appear in the prose.

---

Orchestrator verification: all 52 §1.5 endpoints (including the repair-added `GET /market/daily-prices/{id}` — PRD line 219) and all 23 error ids appear verbatim in PRD.md (the "51" in the subagent's summary is its own miscount; actual coverage is complete).

## Step 5: Generate Unit Tests — 2026-08-11T13:05:00.000Z

Generation complete. All artifacts are under `/home/ubuntu/github/CodingPRD/tasks/task_1177_produce_wholesale_terminal_market/`.

## test_helpers/ (9 files)
- `types.py` — 16 status/role enums + 16 entity TypedDicts; `TemperatureReading` and `Payment` omit `updated_at`/`version` (append-only per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with 49 methods, one per PRD §4 endpoint
- `api_errors.py` — `ApiErrorId` (23 errors) + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_lot_unit_conservation` + `assert_payable_invariant`
- `factories.py` — payload factories (input fields only) with unique-name sequencing
- `constants.py` — PRD thresholds (defect tolerance 5, OT 8h/1.5x, $15 floor, deposit 2500, discount 2%/5d, terms cap 30, trust-claim 30d, violation tolerance 60)
- `test_users.py` — `TEST_USERS` for the 6 roles + mandatory `make_customer_rep_headers(customer_id)` builder for the entity-backed role
- `fixtures.py` — composite setup chain (market day, lot state progression to ACCEPTED/DISPUTED, order progression to INVOICED, bookings, shrink approval, `setup_credit_hold_scenario` for the trust-claim cascade)
- `__init__.py` — barrel export (framework + PRD-specific)

## test_suite/ (12 files, 83 tests, all collected by pytest)
| File | Tests | Contents |
|---|---|---|
| test_01_participants_catalog_pricing.py | 8 | required fields, defaults, enums, mid_price, duplicate/not-posted/out-of-band price, terms cap |
| test_02_lot_cost_and_dispute.py | 10 | A: provisional-vs-final ×2, dispute-reinspection ×2; B: computed fields, initial state, receive-twice, dispute-on-accepted, reject-voids-inspection, inspection-open |
| test_03_cold_chain.py | 5 | A: 3-hop violation cascade ×2; B: in-band reading, append-only reading, pick-on-violated |
| test_04_ripening_rooms.py | 13 | A: ethylene-vs-overlap ×2, lot-acceptance gate ×2, buffer-inflated overlap ×2, cancel-capacity ×2; B: close gate, start window, complete gate, happy path, day-close expiry |
| test_05_orders_cutoff_windows.py | 8 | A: 14:00 boundary ×2, window adjacency ×2, per-line rounding ×2; B: cut-off rejection, shape-beats-not-found |
| test_06_order_fulfillment.py | 7 | A: customer-active gate ×2, state-beats-fiscal ×2; B: cancel DELIVERED, deliver conversion, credit limit |
| test_07_invoicing_payments.py | 9 | A: nested totals+discount ×2, past-due boundary ×2; B: default clock dates, discount boundary, overpayment, invoice-exists, payment-on-PAID |
| test_08_shrink_credit_memos.py | 6 | A: shrink cascade ×2, void invariant ×2; B: prorated memo, segregation of duties |
| test_09_credit_exposure_and_trust.py | 4 | A: credit hold branch/release ×2; B: exposure set filtering, trust exposure drops REJECTED |
| test_10_labor.py | 3 | A: HOURLY vs PIECE ×2; B: OT kink at 8h |
| test_11_rbac_concurrency_and_listings.py | 9 | B: 5 RBAC/auth tests, 2 OCC tests, reverse lookup, pagination envelope |

## Queue A (difficulty): 18/18 instances translated, 2 tests each = 36 tests, 0 skipped

## Queue B (corner): 47/48 non-stub instances translated (1 test each), 1 skipped
- **Skipped:** `Corner/validations/order_line_above_available_returns_insufficient_quantity` — the instance asserts the availability check fires at order *create*, but PRD §3.6 pins it to confirm time verbatim ("The preconditions, all enforced at confirm time, are: … every line must reference a lot in `ACCEPTED` status with `quantity` no greater than that lot's `available_units`"). A PRD-only implementer could legitimately accept the create, so the outcome is not uniquely derivable. Gap stays a gap.
- The 5 `excluded_because:` stubs were not translated; all their `difficulty_instance` cross-references resolve to real §1.8 instances.

## Audit output
- Design-tag audit: 65 distinct tags (18 Difficulty + 47 Corner); every tag resolves to a real instance; every queue-A instance has ≥2 tests; every translated queue-B instance ≥1; no untagged/dual-tagged tests; no stub translated. The only reported shortfall is the documented skip above.
- PRD-citation audit: 128 quoted citation passages, all verified as verbatim substrings of PRD.md (whitespace-normalized).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold references in generated code; `python3 -m py_compile` clean; `pytest --collect-only` collects 83 tests.

## Step 6: Generate Implementation — 2026-08-11T13:05:00.000Z

Implementation complete and smoke-tested. Summary:

## File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1177_produce_wholesale_terminal_market/workspace/implementation/`)

| File | Lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 54 |
| `db.py` | 47 |
| `errors.py` | 40 |
| `response.py` | 62 |
| `middleware.py` | 61 |
| `services/domain.py` | 398 |
| `routes/parties.py` | 310 |
| `routes/lots.py` | 460 |
| `routes/ripening.py` | 268 |
| `routes/shrink.py` | 152 |
| `routes/orders.py` | 336 |
| `routes/billing.py` | 188 |
| `routes/ops.py` | 205 |
| **Total** | **2592** |

## Endpoints
**52 routes registered** (all 46 from the scaffold §1.5 table plus the `GET` list variants — the table's 46 entries map to these 52 Flask routes because list/GET pairs are separate functions; every table row is covered 1:1).

## State machines implemented (7)
- **PurchaseLot**: ORDERED→RECEIVED→INSPECTED→ACCEPTED→CLOSED, with DISPUTED loop (INSPECTED↔DISPUTED), REJECTED termination, and the system cold-chain flip side-path (depth-3 cascade: reading → VIOLATED → CONFIRMED orders ON_HOLD/COLD_CHAIN → reservation release).
- **Inspection**: SUBMITTED→CERTIFIED (PASS moves lot to ACCEPTED with FINAL cost; FAIL leaves lot INSPECTED), SUBMITTED→VOIDED on dispute REJECT.
- **RipeningBooking**: SCHEDULED→IN_PROCESS→COMPLETED, SCHEDULED→CANCELLED, SCHEDULED→EXPIRED (day-close).
- **ShrinkRecord**: DRAFT→APPROVED (issues CreditMemo, updates dumped/payable).
- **CreditMemo**: ISSUED→VOID (compensating payable restore).
- **SalesOrder**: PENDING→CONFIRMED→PICKED→DELIVERED→INVOICED, plus ON_HOLD branching (CREDIT release-able, COLD_CHAIN terminal) and CANCELLED from PENDING/CONFIRMED/ON_HOLD.
- **Invoice**: OPEN→PAST_DUE→TRUST_CLAIMED (day-close, strict `>` boundaries) and →PAID from any non-terminal at zero balance.

## Calculations implemented (8)
`lot_landed_cost` (PROVISIONAL + FINAL defect/agreed variants, 4-decimal unit-price rounding), `labor_charge` (HOURLY with 8h/1.5x OT kink; PIECE with $15/h guaranteed-minimum floor), `order_subtotal` (pinned per-line round-then-sum), `invoice_settlement` ($25/pallet deposit, terms snapshot at issuance, 2% early-pay discount with inclusive `<=` boundary), `cold_chain_accumulation` (cumulative, strict `>` flip), `credit_exposure`, `lot_payable_reconciliation` (ISSUED-memo invariant, REJECTED pins 0), `shipper_trust_exposure`. All money via `Decimal` + `ROUND_HALF_UP`; no floats in money paths.

Key PRD fidelity points: logical clock starts exactly `2026-05-01T00:00:00Z` and never reads wall clock; cut-off allows exactly 14:00:00 next-day; window/room adjacency allowed (strict half-open); room-overlap uses 2h-inflated intervals while ethylene conflict uses uninflated overlap; `TemperatureReading`/`Payment` carry only `id`+`created_at` (no version); OCC only on `PATCH /market/customers/{id}` via `expected_customer_version` → `ERR_STALE_VERSION` 412; envelope is `meta`/`response_type`/`data` with pagination fields in `meta`.

## Boot smoke test
Passed on two independent fresh launches (PORT 19877 and 19878): server ready in ~2s; unauthenticated GET returns the exact 401 error envelope; authenticated list returns the paginated array envelope; a full end-to-end flow (commodity → price → shipper → lot → receive → inspect defect 12% PASS → certify → order → confirm → pick → deliver → invoice → payment → clock advance → day-close) produced correct values at every step (e.g. FINAL adjusted cost 102347¢ = round₄(11.005×0.93)=10.2347 × 100 × 100; day-close marked 1 PAST_DUE → 1 TRUST_CLAIMED and suspended the customer). Zero HTTP 500s in server logs. `start.sh` guards `pip install` behind an `import flask` check and uses `exec` in the foreground.

---

Orchestrator verification: route-pair audit passed — all 52 (method, path) pairs declared in SCAFFOLD.yaml §1.5 are registered in the Flask implementation; no missing, no extras (placeholder names normalized for comparison).

## Step 7: Run Tests and Iterate — 2026-08-11T13:17:00.000Z

Clean 8-round parallel sweep achieved. All 8 rounds: 83/83 passed, 0 failed, 0 errors, 0 skipped.

## Summary

- **Iterations run:** 2 sweeps (16 round-executions total, 83 tests each).
  - Sweep 1: 8 rounds × 82/83 passed — the only non-passing results were 2 distinct tests with `error` status: `test_temperature_reading_in_band_not_out_of_range` (7/8 rounds) and `test_temperature_reading_is_immutable_without_version` (1/8 rounds).
  - Sweep 2: 8 rounds × 83/83 passed, zero non-passing — exit condition met.
- **Diagnosis of the sweep-1 errors:** Both were setup-phase infrastructure timeouts, not assertion failures — the error message was `"API server at http://localhost:<port> could not be restarted before <test>"` from the runner's per-test restart hook (`/usr/local/lib/python3.14/dist-packages/prd_bench_local_runner/pytest_plugin.py`, 30 × 0.5s poll = 15s window). Measured idle boot latency of the implementation is ~0.26s (15 trials), so a 15s expiry indicates transient host CPU saturation at the point of peak 8-round overlap (both errors clustered at ~26% suite progress in `test_03_cold_chain.py`), on a shared box (load average ~3–5, other tenants present). Both tests' assertions trace verbatim to PRD (`§3.3` out-of-range definition line 126; `§2.4` append-only TemperatureReading line 78), so STEP 1 coverage/derivability held and no deletion was warranted; no implementation behavior was implicated.
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:** none.
- **Fixes applied to `implementation/`:** none — the existing `start.sh` already guards `pip install` behind an `import flask` check and boots in ~0.26s; the sweep-2 rerun confirmed the artifact layers were already correct and the sweep-1 blips were environmental.

**Final state:** all 83 tests pass in all 8 parallel rounds under `per-test-server` isolation.

---

Orchestrator verification: all 8 `results.{1..8}.json` on disk show `passed=83, failed=0, errors=0, skipped=0, total=83`.

## Step 8: Finalize PRD — 2026-08-11T13:17:30.000Z

SKIPPED per the skip condition: Step 7 exited with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (the two sweep-1 `error` statuses were infrastructure timeouts, not assertion failures — no artifact was modified across the entire step). `PRD.md` already determines every behavior the implementation exhibits; no `PRD_FINALIZED.md` is produced.

## Step 9: Complete PRD — 2026-08-11T13:45:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1177_produce_wholesale_terminal_market/workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD.md`.

## Size
- PRD.md: 288 lines, 40,265 chars → PRD_COMPLETED.md: 288 lines, 43,190 chars (Δ +2,925 chars; 22 lines edited in place, 0 lines added/removed, no new sections)

## Counts
- Ambiguity-pins (PRD silent → inserted impl behavior): **18**
- Mismatch-revisions (PRD said X, impl does Y → revised to Y): **10**

## Changes (one bullet each)

**Mismatch-revisions:**
- §1 — revise — mismatch — "returns its cascaded side effects inside the same response" → cascades synchronously committed before the response is sent — implementation/routes/lots.py:442, shrink.py:121
- §2.4 — revise — mismatch — clock endpoint "moves the logical clock forward" → sets the clock to the supplied instant verbatim, no monotonicity check — implementation/routes/ops.py:116-123
- §2.9 — revise — mismatch — "the response to the triggering request reflects every hop" → every hop committed before send; body carries only the primary mutated resource — implementation/routes/shrink.py:80-121, lots.py:204-247
- §3.1 — revise — mismatch — "the only path to SUSPENDED is the day-close cascade" → MarketAdmin may also set status directly to ACTIVE/SUSPENDED via the PATCH endpoint — implementation/routes/parties.py:162-166
- §3.1 — revise — mismatch — "a unique code" → server does not enforce commodity code uniqueness — implementation/routes/parties.py:215-241
- §3.3 — revise — mismatch — "cascade is visible in the same response" → fully committed before the response; body carries the created reading — implementation/routes/lots.py:442
- §3.4 — revise — mismatch — agreed_unit_price "when (and only when)" → required for PRICE_ADJUST; on other outcomes a supplied value is type-validated but ignored — implementation/routes/lots.py:213-221
- §3.5 — revise — mismatch — guard order was narrated overlap→ethylene→capacity; impl (and §2.8) run ethylene→overlap→capacity — implementation/routes/ripening.py:132-175
- §3.6 — revise — mismatch — "cancelling a CONFIRMED or ON_HOLD order releases each line's reservation" → only CONFIRMED releases at cancel time; ON_HOLD reservations were already released when the hold was applied — implementation/routes/orders.py:322-331
- §4 table — revise — mismatch — clock row "Advance the logical clock" → "Set the logical clock" — implementation/routes/ops.py:116-123

**Ambiguity-pins:**
- §2.1 — insert — ambiguity — CustomerRep ownership check fires after target-resource/FK resolution (after existence), not at the role-authorization step; non-existent resource yields ERR_NOT_FOUND — implementation/middleware.py:58-61, routes/orders.py:93-98
- §2.2 — insert — ambiguity — envelope api_request_timestamp is wall-clock request time, not the §2.4 logical clock — implementation/response.py:22-26
- §2.3 — insert — ambiguity — non-integer limit/offset, limit outside [1,100], negative offset → ERR_VALIDATION — implementation/services/domain.py:285-307
- §2.3 — insert — ambiguity — created_at sort ties broken by id ascending — implementation/services/domain.py:319-321
- §2.7 — insert — ambiguity — on PATCH /market/customers/{id}: path id resolved before body shape checks; stale-version check after shape, before the terms-cap domain check — implementation/routes/parties.py:122-176
- §2.8 — insert — ambiguity — priority-2 authorization is role-based; CustomerRep ownership ERR_FORBIDDENs are exempt and fire per §2.1 after existence — implementation/middleware.py:50-61
- §3.1 — insert — ambiguity — credit_limit_cents must be a non-negative integer; terms_days a positive integer — implementation/routes/parties.py:90-95, 147-156
- §3.1 — insert — ambiguity — temp_max_f below temp_min_f → ERR_VALIDATION; max_violation_minutes must be a non-negative integer — implementation/routes/parties.py:225-229
- §3.1 — insert — ambiguity — low_price/high_price must be positive numbers with high ≥ low, else ERR_VALIDATION — implementation/routes/parties.py:264-267
- §3.3 — insert — ambiguity — readings accepted for a lot in any status, including ORDERED and CLOSED — implementation/routes/lots.py:386-387
- §3.3 — insert — ambiguity — violation cascade fires only on the OK→VIOLATED transition; already-VIOLATED lots accrue minutes without re-firing — implementation/routes/lots.py:411-419
- §3.5 — insert — ambiguity — capacity sum uses uninflated interval overlap — implementation/routes/ripening.py:163-171
- §3.5 — insert — ambiguity — cancel moves a booking to status CANCELLED — implementation/routes/ripening.py:266
- §3.6 — insert — ambiguity — order creation already enforces customer ACTIVE (ERR_CUSTOMER_INACTIVE), line lots ACCEPTED (ERR_LOT_NOT_ACCEPTED), line qty ≤ available_units (ERR_INSUFFICIENT_QUANTITY) — implementation/routes/orders.py:100-109, 143-151
- §3.6 — insert — ambiguity — delivery_date is YYYY-MM-DD; window_start/window_end are HH:MM 24-hour strings; pallet_count must be a positive integer when supplied — implementation/routes/orders.py:60-67, services/domain.py:221-244
- §3.6 — insert — ambiguity — CustomerRep cancelling own non-PENDING order → ERR_FORBIDDEN; cancel clears hold_reason — implementation/routes/orders.py:309-316, 333
- §3.9 — insert — ambiguity — pieces on a PIECE ticket must be a non-negative integer (0 allowed; floor then applies) — implementation/routes/ops.py:68-72
- §4 — insert — ambiguity — unknown paths and unsupported methods on known paths return the error envelope with ERR_NOT_FOUND (404) — implementation/app.py:33-39

Everything else in the PRD (endpoint table paths/roles, error catalogue codes+statuses, all formulas, state machines, exposure aggregates, cut-off/window/overlap boundary semantics, OCC field, invoice/payment/day-close rules, shrink/memo reconciliation invariant) was verified line-by-line against the implementation and already pinned uniquely — left untouched.

---

Orchestrator post-check and one consistency patch: the subagent's §3.6 insert ("creation already enforces the cross-entity and availability gates") contradicted the surviving §3.6 confirm paragraph ("The preconditions, all enforced at confirm time, are: …"). Verified against implementation (`routes/orders.py:100-151` create-time gates; `_check_lines_ok` at lines 195-217 + `confirm_sales_order` at 233-236 re-checks at confirm): the gates fire at BOTH points. Patched PRD_COMPLETED.md §3.6 confirm lead-in to "The preconditions, enforced at creation and re-checked at confirm time, are: …" — matches impl exactly; no test asserts create-time acceptance of an over-quantity line (that corner instance was skipped at Step 5), so the suite remains green under the clarified wording.

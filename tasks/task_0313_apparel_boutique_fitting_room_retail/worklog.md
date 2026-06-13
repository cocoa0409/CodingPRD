# Worklog — task_0313_apparel_boutique_fitting_room_retail

## Step 1: Create Task Directory — 2026-06-12T12:43:41.000Z

Task directory `tasks/task_0313_apparel_boutique_fitting_room_retail` pre-assigned and already existed; verified `workspace/` subdirectory present. No index scan / auto-increment performed (directory was pre-assigned). Difficulty band for Step 2 scaffold generation: Expert.

## Step 2: Generate Scaffold (Expert) — 2026-06-12T13:01:16.000Z

Generated a complete **Expert-band** scaffold for **task_0313_apparel_boutique_fitting_room_retail**. All three files (`SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) parse and pass `scaffold_lint.py` clean.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (75 endpoints, 14 entities, 18 §1.8 + 29 active §1.9 instances, 344 calls scanned).

**Counts**
- **Entities: 14** — Boutique, Customer, Style, SkuVariant, FittingRoom, FittingRoomHold, Stylist, StylingAppointment, MarkdownSchedule, SalesOrder, OrderLine, ReturnRequest, SpecialOrder, Lookbook.
- **State machines: 7** (over 6 entities) — SalesOrder carries **parallel** axes (payment_status × fulfillment_status); FittingRoomHold and ReturnRequest are **branching with divergent side-effects**; MarkdownSchedule is **branching-with-revert + supersede**; StylingAppointment and SpecialOrder are branching lifecycles.
- **Calculations: 4** — `markdown_pricing` (dual-variant provisional/final on Style), `loyalty_tier_eval` (dual-variant projected/actual on Customer), `order_pricing` (mode-b per-line-then-sum rounding), `loyalty_accrual` (mode-c pinned evaluation order breaking a circular dependency).
- **Validations: 19** (priority-ordered). **Errors: 19**. **Roles: 4** — Customer (entity_backed), StoreAssociate / Merchandiser / StoreManager (opaque), peer-role model. **Concurrency: 1** OCC rule (markdown create-supersede on `Style.version`).

**Expert depth/breadth design.** Depth (§1.8): all 9 Difficulty Rules satisfied with 2 differentiated instances each (18 total) — dual-variant logic spans two distinct domains (Style pricing 6000→4200 vs Customer loyalty tier projection); two combinatorial modes (rounding-order vs circular store-credit/points dependency); a depth-4 return-restock cascade (Return→OrderLine→SkuVariant→Style) and a depth-3 markdown-reprice cascade from a different trigger; two validation-priority conflicts on different category pairs (state>temporal, inventory>fiscal); two overlap geometries on different resources (half-open room holds with back-to-back allowed vs closed-buffer stylist appointments); two conserved-quantity invariants (physical units; store-credit + loyalty points). Breadth (§1.9): 29 active corner instances plus 6 `excluded_because` stubs covering CRUD/required-field/not-found/duplicate-key, invalid-transition and terminal lockdown, computed-read correctness, RBAC denials, OCC stale-vs-fresh version, and a clock-driven expiry sweep — all chains driven from empty-DB through the declared §1.5 surface, with all formula-derived asserts pre-computed as literals.

Note: endpoint count (75) runs above the 20–32 §0.4 guideline because 33 GETs are forced by FK reverse-reachability across 14 entities and the write surface is dominated by state-machine action endpoints; difficulty is concentrated in the calculations/cascades, not the count.

## Step 3: Copy Shared Files — 2026-06-12T13:01:38.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-12T13:08:58.000Z

**Document:** Apparel Boutique & Fitting-Room Retail API PRD — 286 lines.

**Section count:**
- §1 Introduction (3 paragraphs, angled on the three reconciled forces: scarce inventory, layered pricing, conserved loyalty/credit)
- §2 Global Specifications — **8 subsections** (2.1 RBAC, 2.2 verbatim envelope, 2.3 Pagination, 2.4 Common Properties + Store Clock, 2.5 Inventory Conservation, 2.6 Pricing/Loyalty/Precision, 2.7 OCC on markdown create, 2.8 Cascade Consistency + Validation Ordering)
- §3 Business Logic — **9 subsections** organized by entity lifecycle (catalog → customers/wallet → holds → appointments → markdowns → selling → returns → special orders → lookbooks)
- §4 Endpoint table (4 columns, all 75 endpoints) and §5 Error catalog (2 columns, all 19 errors)

**Hard Contracts — all PASS:**
- **Contract 1 (Field-Name Coverage):** 76 required identifiers (65 entity fields + 11 request/query/path ids), 0 missing. Initial pass missed `to_business_date`/`to_minute` (clock-advance body); repaired into §2.4.
- **Contract 2 (Rule Coverage):** All 7 state machines, 4 dual-variant/aggregation calculations, 19 validations (with priority orderings), the single OCC rule, and the three-level return cascade verified in prose. Key orderings made explicit: return state-before-window, stylist-active-before-double-book, capture inventory-before-store-credit, hold room-overlap-before-inventory.
- **Contract 3 (§3 Path Purity):** 465 backtick tokens scanned; 0 slash-paths, 0 bare methods, 0 method+path combos.

**Notable coverage decisions:**
- The two dual-variant calculations (markdown provisional `projected_price_cents` vs final `applied_price_cents`; loyalty actual vs projected tier) are rendered with explicit divergence narratives.
- The apparent circular dependency in loyalty accrual (points←net cash←store credit←total) is resolved in prose by pinning evaluation order (total finalized first, then floor-mint on net cash only).
- Constants embedded with unit conversions: tier thresholds as dollars-and-cents, discount rates as percent+bps, `tax_rate_bps` 875 = 8.75%, min-price floor 100 cents, points divisor 100.
- Per the hard constraint, neither difficulty nor corner design YAML was opened or referenced. The §4 table matches the scaffold's 75-endpoint set exactly.

## Step 5: Generate Unit Tests — 2026-06-12T13:25:33.000Z

**Task:** `task_0313_apparel_boutique_fitting_room_retail` (Expert band) — full test infrastructure generated from the two design indices only.

### Stage 1 — `test_helpers/` (9 files)
`types.py` (15 entity TypedDicts, all `common_fields: true` → carry id/created_at/updated_at/version; full status enum set), `api_client.py` (one method per endpoint), `api_errors.py` (20 error IDs + HTTP-status map), `assertions.py` (per-entity + the `available == on_hand - reserved` conservation invariant), `factories.py`, `constants.py` (loyalty thresholds, tier-discount bps, points divisor), `test_users.py` (3 opaque roles + `make_customer_headers(user_id)` builder for the entity-backed `Customer` role), `fixtures.py` (composite chains), `__init__.py` barrel. All 9 compile clean.

### Stage 2 — `test_suite/` (conftest + 8 test files, 65 test functions)
| File | Tests |
|---|---|
| test_01_pricing_and_loyalty | 11 |
| test_02_order_lifecycle | 5 |
| test_03_returns_and_cascades | 7 |
| test_04_markdowns | 6 |
| test_05_holds_appointments_inventory | 12 |
| test_06_validation_conflicts_and_boundaries | 11 |
| test_07_catalog_crud | 9 |
| test_08_rbac | 4 |

### Coverage (verified programmatically)
- **Queue A (Difficulty):** all **18** instances covered, **each with exactly 2 tests** (36 tests). No dangling tags.
- **Queue B (Corner):** all **29** non-stub instances covered (≥1 test each, 29 tests). All **6** `excluded_because:` stubs correctly NOT translated.
- Every test has exactly one `Design:` docstring tag (65/65); no untagged/dual-tagged/dangling tags; no skip/skipif/xfail.
- **All 93 PRD citation quotes verbatim-match `PRD.md`** (modulo whitespace) — verified by literal-substring checker.

### Skipped instances
**None.** Every non-stub instance in both queues passed the PRD-first two-condition filter. The 6 corner stubs are intentionally not translated per spec.

Note: `prd_bench_local_runner` not installed in the generation environment; tests validated via syntax compilation + static tag/citation auditing.

## Step 6: Generate Implementation — 2026-06-12T13:25:33.000Z

Generated a complete Python + Flask implementation (Expert difficulty) at `workspace/implementation/`.

### Files (23 total)
- **Launcher/deps**: `start.sh` (guarded `pip install`, `exec python3 app.py`, binds `0.0.0.0:$PORT` default 10000), `requirements.txt` (flask 3.0.3)
- **Core**: `app.py`, `db.py` (in-memory dict store + UUID/timestamp/version stamping, seq-based stable sort), `errors.py` (ApiError + 20-entry catalog), `response.py` (envelope helpers), `middleware.py` (auth header extraction + RBAC)
- **Services**: `money.py` (Decimal round-half-up), `pricing.py`, `common.py`, `boutique_ledger.py` (store-credit conservation), `holds.py` (clock-sweep expiry)
- **Routes** (10 modules): boutiques+clock, customers, styles+SKU variants, markdowns, fitting rooms+holds, stylists+appointments, sales orders+lines, returns, special orders, lookbooks

### Coverage
- **75/75 PRD endpoints** registered (exact 1:1 with the endpoint table)
- All 7 state machines; all 4 calculations (markdown dual-variant, loyalty tier eval, order pricing per-line-then-sum, loyalty accrual floor-mint + prorated reversal)
- Inventory conservation with variant→style roll-up; OCC create-supersede on markdown (`expected_style_version` → `ERR_STALE_STYLE_VERSION` 412)
- Validation priority ordering incl. pinned pairs (state-before-temporal on returns; stylist-active-before-double-booking; inventory-before-store-credit at capture)

### Notable design decisions
- Purely in-memory dicts keyed by id; **no seeding** — fresh boot wipes all state.
- Holds record creation-day (`_business_date`, stripped from serialization) so the clock sweep distinguishes day-advance from same-day minute expiry.
- Full-return → `REFUNDED` reverses residual points to pre-order baseline (conservation).
- `total_cents` on authorize set to pre-store-credit priced value (matches PRD §3.2 tier-projection sum over AUTHORIZED orders).

### Verification
Boots cleanly via `start.sh`; ran ~75 end-to-end assertions across two smoke suites — all passed, no server tracebacks. All modules compile.

## Step 7: Run Tests and Iterate (resume re-confirmation) — 2026-06-13T02:26:00.000Z

Resumed pipeline. The original Step 7 sweep (prior session) had already converged to a clean 8-round result at 64/64 (test suite reduced from 65 generated tests to 64, i.e. 1 test deleted during the prior Step 7 loop). On resume, the 8 old `results.N.json` were deleted and the full Step 7 8-round parallel per-test-server sweep was re-run ONCE to re-confirm stability.

**Re-confirmation result (verbatim):** all 8 rounds GREEN — `results.1..8.json` each report `passed=64 / total=64`, `non_passed=0`. No flakiness surfaced across the 8 concurrent rounds.

- Iterations run (this resume pass): 0 (re-confirmation only — no failures, no diagnostic/fix loop triggered).
- Tests deleted: 0 this pass. (The prior Step 7 loop deleted 1 test, 65→64; that deletion's specific PRD-silence category was NOT recorded in this worklog by the prior session.)
- Fixes applied to `test_helpers/`: 0 this pass.
- Fixes applied to `test_suite/`: 0 this pass.
- Fixes applied to `implementation/`: 0 this pass.

**Step 8 decision:** SKIPPED. The prior Step 7 fix diff (the deleted test + any earlier-session fixes) was not durably recorded in this worklog, so there is no reliable `<step_7_diff>` focus list to hand Step 8. Per the resume directive, Step 8 is skipped and Step 9 (full PRD-vs-implementation scan) supersedes its coverage.

## Step 9: Complete PRD — full PRD-vs-implementation scan — 2026-06-13T02:30:00.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD.md` (Step 8 was skipped; `PRD_FINALIZED.md` absent, so started from `PRD.md`).

**Line/char counts**
- `PRD.md` (source): 286 lines, 47,377 chars
- `PRD_COMPLETED.md`: 286 lines, 48,700 chars
- Char delta: +1,323 (all edits are in-paragraph; no lines added/removed, no new sections)

**Counts:** 8 changes total — 5 ambiguity-pins, 3 mismatch-revisions.

**Per-change list** (`{section} — {kind} — {class} — {what} — {impl ref}`):

- §3.1 (SKU variants) — insert — ambiguity — pin that `on_hand` on variant create must be ≥ 0 — `routes/styles.py:96`
- §3.1 (restock) — insert — ambiguity — pin that restock `units` must be ≥ 1 — `routes/styles.py:140`
- §3.2 (store-credit grant) — insert — ambiguity — pin `amount_cents` ≥ 0 and that the grant returns the updated customer with HTTP 201 — `routes/customers.py:102,108`
- §3.3 (clock sweep) — insert — ambiguity — pin that the intraday minute comparison runs only when `to_minute` is supplied; with `to_minute` omitted, same-day holds are never minute-swept (only day-advance expires them) — `services/holds.py:28`, `routes/boutiques.py:72`
- §3.5 (markdown create-supersede) — insert — ambiguity — pin that a superseded prior DRAFT/SCHEDULED schedule has its `projected_price_cents` cleared to null — `routes/markdowns.py:73-75`
- §3.6 (authorize) — insert — ambiguity — pin that authorization writes a provisional `total_cents` (= subtotal − discount + tax, pre-store-credit), which §3.2's tier projection sums; capture overwrites it — `routes/sales_orders.py:164`
- §3.8 (special order) — revise — mismatch — PRD said `ship_to_state_code` "selects destination nexus tax"; impl computes no tax/total on special orders, so revised to: field is validated/stored but purely informational, no nexus tax computed — `routes/special_orders.py:31-39`
- §4 (endpoint status codes) — revise — mismatch — PRD prose listed store-credit grants among 200-OK modifications, but impl returns 201; removed it from the 200 list and stated the grant returns 201 — `routes/customers.py:108`

**Key finding:** The most consequential mismatch was the store-credit-grant status code — PRD §4 prose explicitly enumerated it as a 200-OK operation, while the implementation returns 201 Created. Tests were weakened (the fixture reads success data without asserting the status), so only the impl pins it. Both §3.2 and §4 were updated so the PRD now consistently reflects 201.

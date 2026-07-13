# Worklog — task_0560_promo_products

## Step 1: Create Task Directory — 2026-07-08T00:00:00.000Z

Created `tasks/task_0560_promo_products/` with `workspace/` subdirectory. INSTRUCTION.md confirmed present at project root.

## Step 2: Generate Scaffold — 2026-07-08T00:00:01.000Z

The scaffold is complete and passes the linter cleanly. Here is a summary of what was generated.

## Task: `task_0560_promo_products` — Promotional Products & Branded Swag Distributor (Expert)

Three files written to `.../tasks/task_0560_promo_products/`:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Lint result:** `VERDICT: clean lint` — all 429 §1.8/§1.9 setup/trigger calls conform to §1.5, and every §1.1 FK has reverse-reachability.

### Structure
- **Complexity profile:** `pricing_engine` + `workflow_orchestration`; layers `rate_threshold_triggers`, `dual_variant_calculation`, `cascading_side_effects`, `optimistic_concurrency`; hybrid topology with a self-referential reorder FK; parallel + cyclic state shapes; approval-chain RBAC; `api_prefix: ""` (multi-root catalog+order domain).
- **10 entities:** Supplier, Product, PriceTier, DecorationStation, Customer, Order, OrderLine, ArtProof, PurchaseOrder, Shipment.
- **4 state machines:** Order (parallel `fulfillment_status × payment_status`), OrderLine (linear + QC rework cycle), ArtProof (cyclic revision loop), PurchaseOrder (linear). One concurrency rule (OCC on `OrderLine.version` for art-proof supersede).
- **7 calculations:** `line_subtotal` (tiered + multicolor), `order_total` (QUOTED/FINAL variants, pinned sum-then-round rush), `blank_cost` (ESTIMATED/ACTUAL variants), `lead_time_rush`, `spoilage_tolerance`, `station_schedule_overlap` (pairwise half-open), `supplier_capacity_load` (aggregate stabbing).
- **44 endpoints, 42 errors, 4 roles** (CatalogAdmin, AccountManager, ProductionManager, Customer[entity_backed]), plus a `/_clock` test-driver (default `2026-05-01T00:00:00Z`).

### Difficulty & corner coverage
- **§1.8:** 18 instances = all 9 Difficulty Rules × 2.
- **§1.9:** 29 instances (24 active + 5 `excluded_because` stubs pointing at §1.8).

## Step 3: Copy Shared Files — 2026-07-08T00:00:02.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-08T00:00:03.000Z

Generated `workspace/PRD.md` — 293-line PRD, Expert-band pricing-engine + workflow-orchestration task.

**Structure:** 5 top-level sections; 11 §2 subsections (2.1–2.11), 9 §3 subsections (3.1–3.9). §4 endpoint table: all 44 endpoints. §5 error catalogue: all 42 error IDs.

**Hard Contract reports:** Contract 1 (Field-Name Coverage) 65/65 PASS; Contract 2 (Rule Coverage) PASS; Contract 3 (§3 Path Purity) PASS.

**Notable coverage decisions:**
- Scaffold references constant `SAMPLE_MAX_QTY` (used by `ERR_SAMPLE_QTY_EXCEEDED`) but never supplies its numeric value. PRD expresses the ceiling via the named constant rather than fabricating a number → genuine scaffold gap; PRD-only implementer cannot derive the threshold value.
- Priority-9 time-window format check (`ERR_INVALID_TIME_WINDOW`) placed last in §2.9 chain per scaffold's numeric priorities.
- §2.2 emitted verbatim from fixed source file.

(Note: Steps 5+6 were first launched concurrently but both subagents were killed by a transient API ConnectionRefused error before writing any files; nothing landed on disk, so both were re-launched cleanly. The records below are from the successful re-launch.)

## Step 5: Generate Unit Tests — 2026-07-08T00:00:04.000Z

**Stage 1 — `test_helpers/` (9 files):** types.py, api_client.py (incl. `/_clock/set_current_utc`), api_errors.py (all 42 error IDs + HTTP-status map), assertions.py, factories.py, constants.py, test_users.py (opaque roles + `make_customer_headers` for entity-backed Customer), fixtures.py (staged lifecycle chain), barrel `__init__.py`.

**Stage 2 — `test_suite/` (7 files + conftest, 59 test functions):**
- Queue A (Difficulty): 36 tests — all 18 instances × 2.
- Queue B (Corner): 23 tests — 23 of 24 non-stub instances, 1 each.

**Verification:** all files compile; every docstring ends with exactly one resolving `Design:` tag; every citation has verbatim ≥8-word PRD substring; no scaffold leakage; 5 `excluded_because` stubs not translated.

**Skipped (1 instance):**
- `Corner/validations/sample_quantity_exceeded_returns_error` — assertion (qty 13 rejected) requires `SAMPLE_MAX_QTY` < 13, but PRD names the constant without a numeric value → fails unique-derivability → skipped.

Assertion-scoping note: `Corner/state_machines/new_order_initial_state_is_draft_unpaid` asserts DRAFT/UNPAID/escrow_cents==0 (PRD §3.2 verbatim) but drops `art_complete==false` (not uniquely derivable).

## Step 6: Generate Implementation — 2026-07-08T00:00:05.000Z

Built Python + Flask in-memory REST API in `workspace/implementation/`.

**Files (3):** start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, exec python3 app.py), requirements.txt (flask), app.py (~880 lines, module-level dicts, nothing seeded at boot).

**Endpoints:** all 44 from the table.

**PRD ambiguities resolved (noted in code):**
1. `SAMPLE_MAX_QTY` referenced but never given numeric value — chose **12** (only guess; boundary tests on this constant are the one real risk). [Convergence: Step 5 skipped the corresponding test for the same reason.]
2. `ERR_VALIDATION` (400) absent from numeric priority list — placed after path-existence and body-field presence, before deeper business checks.
3. `ERR_INVALID_TIME_WINDOW` at stated numeric priority (9), conflicts with §3.7 narrative ordering; followed explicit priority number.
4. `ERR_LINE_PRODUCT_MISMATCH` = PO supplier_id ≠ line's product's supplier_id.
5. Full 3-hop cancel cascade for all cancellable states; only ISSUED POs cancelled/released.
6. Version bumping only when a stored field changes; derived fields (credit_balance) not version-bumped. created_at/updated_at wall-clock ms; logical clock drives only lead-time and shipped_at.
7. Customer ownership on order-scoped single GETs + spec'd mutations; opaque roles never ownership-checked. Pagination limit clamped [1,100], offset floored 0.

## Step 7: Test & Iterate — 2026-07-08T00:00:06.000Z

All 8 parallel rounds passed cleanly (59/59 each, 0 failures across the union). The task was already in a passing, stable state.

- Iterations run: 1 (initial 8-round parallel sweep).
- Result: all 8 rounds passed 59/59 tests, zero failures — no flakiness surfaced.
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`: none.

No diagnostic steps were needed — the first sweep was fully green. The `SAMPLE_MAX_QTY` boundary test was already skipped at generation time; no surviving test asserts a specific value.

## Step 8: Finalize PRD — SKIPPED — 2026-07-08T00:00:07.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. PRD.md already determined every behavior the implementation exhibits. `PRD_FINALIZED.md` not produced.

## Step 9: Complete PRD — 2026-07-08T00:00:08.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan.

**File deltas:** PRD.md 293 lines / 40,595 chars → PRD_COMPLETED.md 293 lines / 41,947 chars (+1,352 chars, 0 net lines — all in-paragraph inserts/revisions).

**Counts:** 6 ambiguity-pins, 2 mismatch-revisions (8 total).

**Changes:**
- §2.3 Pagination — revise — ambiguity — limit clamped [1,100], offset clamped ≥0 (not rejected); non-integer → ERR_VALIDATION — app.py:366-389
- §2.4 Common Properties — revise — ambiguity — version starts at 1 on creation — app.py:497,610,715
- §3.2 Order — revise — ambiguity — creation defaults: is_rush/art_complete false; quoted_*/deposit_required_cents=0; final_*=null until shipment — app.py:653-661
- §3.2 Order — revise — mismatch — line-add applies no fulfillment-status precondition — app.py:687-720
- §3.2 Sample orders — revise — ambiguity — SAMPLE_MAX_QTY pinned to 12 — app.py:32,705
- §3.2 line-creation — revise — ambiguity — constraint order: ERR_BELOW_MIN_QUANTITY → ERR_TIER_NOT_FOUND → ERR_MAX_COLORS_EXCEEDED → ERR_SAMPLE_QTY_EXCEEDED — app.py:699-706
- §3.4 Purchase Orders — revise — ambiguity — ERR_LINE_PRODUCT_MISMATCH = product.supplier_id ≠ request.supplier_id — app.py:1171-1173
- §3.7 Scheduling — revise — mismatch — double-booking overlap check runs before format check (per §2.9 priority-9) — app.py:942-957

All other impl behaviors already uniquely pinned by existing PRD prose; left unchanged. Tests not treated as authority.

---

## Pipeline complete

Final state: 59 tests, all passing across all 8 stability rounds (59/59 × 8). Task directory fully populated:
- SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml
- workspace/PRD.md, workspace/PRD_COMPLETED.md (PRD_FINALIZED.md absent — Step 8 skipped)
- test_helpers/ (9 files), test_suite/ (7 test files + conftest)
- workspace/implementation/ (app.py, start.sh, requirements.txt, results.{1..8}.json)

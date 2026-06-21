# Worklog — task_0450_bar_beverage_inventory

## Step 1: Create Task Directory — 2026-06-21T06:45:16.000Z

Created `tasks/task_0450_bar_beverage_inventory/` and `tasks/task_0450_bar_beverage_inventory/workspace/` at the pre-assigned path (no auto-scan for next index per orchestration override). Verified `./INSTRUCTION.md` and all `skills/prd-bench-*` are present.

## Step 2: Generate Scaffold — 2026-06-21T07:14:34.000Z

All three artifacts are generated, mutually consistent, and pass the scaffold linter cleanly. Here is the summary for the orchestrator worklog.

### Task 0450 — Bar & Beverage Inventory (BevSpot style) — Expert tier

Generated three artifacts in `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0450_bar_beverage_inventory/`:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Complexity profile:** primary archetype `ledger_reconciliation` (theoretical recipe-driven vs actual count-driven depletion) + secondary `quota_allocation` (par/reorder); layers: dual-variant calc, cascading side-effects, derived-field reconciliation, optimistic concurrency; topology `flat` (api_prefix `""`, all collections at root); state-machine shape `branching`; role model `peer_roles`; consistency `immediate`.

**SCAFFOLD counts:**
- Entities: 13 — Product, ParSetting, RecipeSpec, RecipeLine, MenuItem, CountSession, CountLine, PurchaseOrder, POLine, Invoice, InvoiceLine, WasteLog, KegTap
- State machines: 5 — PurchaseOrder (DRAFT→SUBMITTED→RECEIVED→CLOSED + cancel branches), Invoice (DRAFT→POSTED→VOID with compensation), CountSession (OPEN→FINALIZED/VOID, OCC-guarded), RecipeSpec (DRAFT↔PUBLISHED cycle + RETIRED), MenuItem (ACTIVE→DELISTED)
- Concurrency rules: 2 (OCC on CountSession.version for count-line add and finalize)
- Calculations: 7 — compute_recipe_cost (round-per-line, mode b), depletion_variance (theoretical vs actual dual-variant), resolve_closing_units (weight-based), keg_yield (floor, mode a), reconcile_invoice (subtotal→discount→tax→total, mode c), reorder_quantity (threshold + case-pack), menu_engineering (STAR/PLOWHORSE/PUZZLE/DOG)
- Validations: 18 (priority-ordered; categories auth→existence→state→OCC→referential→temporal→constraint→fiscal)
- Endpoints: 54
- Errors: 19 (all triggerable; includes ERR_STALE_VERSION, ERR_COUNT_WINDOW_OVERLAP, ERR_LINE_OVERLAP, ERR_WEIGHT_BELOW_TARE, ERR_NOT_A_KEG, ERR_SHORT_RECEIPT, ERR_PRODUCT_NOT_ON_PO, etc.)
- Roles: 3 — InventoryManager, PurchasingAgent, BarManager (all `opaque` peer roles)

**§1.8 Difficulty Design:** 19 instances across all 9 rules (2 each; combinatorial_formula has 3). All differentiation clauses satisfied (different entity domains, modes a/b/c, error-category pairs, interval semantics, conserved quantities). All formula-derived asserts pre-computed as literals (e.g., recipe_cost 295 vs sum-then-round 296; invoice 49140/2457/4085/52268; variance_cost 2079; keg servings 124/117; tier boundary at exactly 40000 → 5%).

**§1.9 Corner Design:** 42 instances total — 38 active + 4 `excluded_because` stubs, across 9 guide sections (entities, state_machines, calculations, validations, endpoints, rbac, cross_cutting, consistency_model, errors).

**Lint:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (296 calls scanned across 57 design instances). 60 unique design-instance names across both files; no forbidden concurrency vocabulary; all enum values have producing transitions; all grounds resolve.

One design note: the `flat` topology required setting `api_prefix: ""` (all entities are root collections) so the linter's FK reverse-reachability segment derivation works; product-targeting child FKs are served by `/products/{id}/<child>` sub-resource GETs.

## Step 3: Copy INSTRUCTION.md — 2026-06-21T07:14:34.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0450_bar_beverage_inventory/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-21T07:20:28.000Z

### PRD Generation Complete — task_0450_bar_beverage_inventory

**Output:** `workspace/PRD.md`

**Structure:** 271 lines, 5 top-level sections. §2 has 9 subsections (2.1 RBAC, 2.2 fixed response envelope, 2.3 pagination, 2.4 common resource properties, 2.5 nested retrieval + validation priority, 2.6 OCC on count sessions, 2.7 precision, 2.8 stock/reorder, 2.9 cascade/compensation). §3 has 9 subsections organized by entity-lifecycle/workflow. §4 endpoint table (4 columns), §5 error table (2 columns).

**Entities documented (13, all `common_fields: true`):** Product, ParSetting, RecipeSpec, RecipeLine, MenuItem, CountSession, CountLine, PurchaseOrder, POLine, Invoice, InvoiceLine, WasteLog, KegTap.

**State machines:** PurchaseOrder (DRAFT/SUBMITTED/RECEIVED/CLOSED/CANCELLED with SUBMITTED→CANCELLED "no posted invoice" precondition and SUBMITTED→RECEIVED auto-cascade on first invoice post), Invoice (DRAFT/POSTED/VOID with void-compensation + RECEIVED→SUBMITTED revert), CountSession (OPEN/FINALIZED/VOID), RecipeSpec (DRAFT/PUBLISHED/RETIRED with revise/retire "no active MenuItem" guards), MenuItem (ACTIVE/DELISTED). All preconditions paired with `ERR_INVALID_STATE` and side-effect version bumps stated.

**Calculations (all 7):** compute_recipe_cost (round-per-line-then-sum, sum-then-round explicitly rejected), depletion_variance (dual-variant theoretical vs actual, half-open window, 4dp), resolve_closing_units (net-weight→1dp ml→3dp units), keg_yield (floor servings, 0.05 default line loss, cost/serving half-up), reconcile_invoice (pinned extensions→subtotal→discount[inclusive 40000=5%/30000=3%]→tax[0.0875]→total), reorder_quantity (ceil-to-par then ceil-to-case_pack), menu_engineering (0.70 popularity factor, inclusive boundaries, STAR/PLOWHORSE/PUZZLE/DOG). All constants embedded in business prose.

**Validations (all 18):** priority ordering expressed as the §2.5 pipeline. Multi-endpoint scopes enumerated: ERR_STALE_VERSION (add+finalize), ERR_PRODUCT_NOT_ON_PO (line-add+post), ERR_WEIGHT_BELOW_TARE (add+finalize).

**Errors (all 19):** every error_id appears in narrative prose, not just the §5 table.

**Hard Contract Reports:** Field coverage PASS (61/61). Rule coverage PASS (18 validations, 2 OCC, 17 transitions, 7 calculations, all expressed). Path purity PASS (0 path tokens in §3). DIFFICULTY/CORNER design files were not opened; no sibling tasks consulted.

## Step 5: Generate Unit Tests — 2026-06-21T07:37:02.000Z

### Test generation complete — task_0450_bar_beverage_inventory

**Test files:** 6
- `test_01_invoice_reconciliation.py` (14 tests) — money order/tiers, landed cost, post→onhand→reorder→PO cascades, PO-state gating, product-not-on-PO, short-receipt
- `test_02_recipes_and_menu.py` (15 tests) — round-per-line cost, publish/revise cycle, pour cost, menu engineering, sales accrual, recipe-published gating
- `test_03_counts_and_variance.py` (11 tests) — theoretical-vs-actual variance, weight closing units, OCC add/stale, window strict-after, tare/duplicate/terminal guards
- `test_04_purchase_order_lifecycle.py` (9 tests) — post/void compensation, conserved on-hand & ordered-total invariants, submit/cancel state guards
- `test_05_keg_reorder_waste.py` (13 tests) — keg-yield floor non-linearity + default loss, reorder boundary (X-1/X), par/keg guards, keg-tap overlap vs adjacency, waste depletion + floor-at-0
- `test_06_products_and_rbac.py` (14 tests) — product CRUD/defaults/dup-SKU/archive-reuse, pagination, soft-delete filter, par supersede, empty-menu, RBAC 403s, unknown-role 401

**Total tests:** 76

**Queue trace:**
- Queue A (Difficulty §1.8): 38 tests — all 19 instances across 9 rules covered with exactly 2 tests each (≥2 requirement met)
- Queue B (Corner §1.9): 38 tests — all 38 non-stub instances covered with ≥1 test each

**Instances SKIPPED:** 0 non-stub instances skipped — every queue-A and queue-B non-stub instance passed the PRD-first two-condition filter. Both `priority_pair_validation_conflict` instances verified to be single-failure scenarios in disguise (legitimately uniquely-derivable).

**Stubs (correctly NOT translated):** 4 `excluded_because:` corner stubs (`error_stale_version_on_finalize_stub`, `error_count_window_overlap_stub`, `error_line_overlap_stub`, `error_recipe_not_published_stub`) — no placeholder tests emitted.

**Audits passed:** every test has exactly one `Design:` tag (no untagged/dual-tagged/dangling); all 91 quoted PRD citations have a verbatim ≥8-word substring in PRD.md; no skip/skipif/xfail markers; all modules import cleanly under framework stub.

**test_helpers/ files written:** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (plus `test_suite/conftest.py`).

## Step 6: Generate Implementation — 2026-06-21T07:37:02.000Z

Implementation complete and verified end-to-end.

**Source files written (27):**
- `start.sh` — foreground launcher, reads `$PORT` (default 10000), binds `0.0.0.0`, guards `pip install` on a cheap `import flask` check, `exec python3 app.py`.
- `app.py` — entry point, blueprint registration, ApiError + 400/404/405/500 error handlers emitting the standard envelope.
- Foundation: `db.py` (in-memory dicts + `stamp_create`/`touch`), `errors.py` (full error catalog), `response.py` (success/array/error envelope), `middleware.py` (auth + RBAC), `validate.py` (schema validation + pagination), `money.py` (Decimal/ROUND_HALF_UP), `clock.py` (logical clock), `timeutil.py`, `serialize.py`.
- `routes/`: products, par_settings, recipes, menu_items, count_sessions, purchase_orders, invoices, waste_logs, keg_taps, clock_route, lookup.
- `services/`: product (derived-field maintenance + cost propagation), calc (keg_yield, reorder_quantity, reconcile_invoice, menu_engineering, resolve_closing_units), finalize (depletion variance + sales ledger).

**Endpoints implemented:** all 53 from PRD §4 (Flask reports 54 rules, counting a shared GET/POST path twice).

**State machines** (PurchaseOrder, Invoice, CountSession, RecipeSpec, MenuItem) realized with explicit precondition checks in validation priority order (auth→authz→existence→state→OCC→business) and side effects. Cascades verified live. Every mutation bumps `version` and `updated_at` per PRD §2.4.

**The 7 calculations** all implemented with `Decimal`/ROUND_HALF_UP and verified numerically (compute_recipe_cost, depletion_variance, resolve_closing_units, keg_yield, reconcile_invoice, reorder_quantity, menu_engineering).

OCC on count-sessions (`expected_count_session_version` → ERR_STALE_VERSION 412 on add/finalize/void) verified.

**Storage confirmation:** in-memory only — every collection is a plain dict created fresh on import in `db.py`; no SQLite, no JSON-on-disk, no `/tmp` cache. No seeding/preload anywhere — cold boot via `start.sh` yields `total_count: 0` for every collection. Per-test-server restarts wipe all state.

## Step 7: Run Tests and Iterate — 2026-06-21T07:45:26.000Z

**Iterations run:** 2 (initial diagnostic sweep + one fix sweep). Final result: all 8 parallel rounds green at **76/76**, no flakiness (every failure was deterministic across all 8 rounds, not timing-sensitive). Orchestrator independently re-ran the 8-round sweep afterward and confirmed 76/76 GREEN in all 8 rounds.

### Failure diagnosis
The initial sweep failed 9 tests identically in all 8 rounds, in two clusters:

- **Cluster B (7 tests, `test_03_counts_and_variance.py`)** — all tripped `ERR_STALE_VERSION` on count-session finalize/second-add. Root cause was the triage hint ("≥5 failing tests share the same setup error → suspect `test_helpers`"). The `add_count_line` fixture's docstring claimed the POST `/count-sessions/{id}/count-lines` response "carries the new session version," but per PRD §2.2 that endpoint returns the created **CountLine** resource, whose own `version` is 1 — not the **CountSession** version (which the add advances to 2). The OCC guard in PRD §2.6/§3.7 is keyed on the *session* version, so fixtures were feeding `expected_count_session_version=1` into a server whose session was already at 2. **TEST-HELPER BUG.**

- **Cluster A (2 tests, `test_02_recipes_and_menu.py`)** — `test_publish_then_revise_returns_to_draft` (expected version 3, got 5) and `test_delist_menu_item_transitions_to_delisted` (expected version 2, got 4). These pinned exact `version` integers that are **not uniquely derivable** from the PRD: §2.4 explicitly declares derived-field recomputes (recipe_cost_cents on line-add/publish; pour_cost_pct on create; units_sold on record-sales) to be version-bumping mutations, but never pins how many bumps each transition produces. COMPUTED-FIELD-SILENCE on version count → STEP 1b partial-coverage split (1c).

### Fixes applied to `test_helpers/`
- **`fixtures.py` → `add_count_line`**: now re-reads the session via `GET /count-sessions/{id}` after posting the line and returns that session dict, so callers get the real session `version` to supply as `expected_count_session_version`. Updated `open_session_with_unit_line` / `open_session_with_weight_line` to use the corrected return (renamed `line` → `session_after`). Fixed all four call sites.

### Fixes applied to `test_suite/` (STEP 1c split — kept covered assertion, removed non-derivable one)
- **`test_02_recipes_and_menu.py::test_publish_then_revise_returns_to_draft`**: removed `assert data["version"] == 3`; kept the uniquely-determined `status` transition assertion (PUBLISHED → DRAFT).
- **`test_02_recipes_and_menu.py::test_delist_menu_item_transitions_to_delisted`**: removed `assert data["version"] == 2`; kept the `status` transition assertion (ACTIVE → DELISTED).

### Fixes applied to `implementation/`
None. The implementation was PRD-faithful throughout — it correctly returns the CountLine (not the session) on count-line add, and correctly bumps `version` on every derived-field recompute per §2.4. No implementation check was weakened, no endpoint/field added, storage remains in-memory only.

**Tests deleted:** none — both Cluster-A issues were partial-coverage splits (offending assertion removed, covered assertion retained), not full deletions.

## Step 8: Finalize PRD — 2026-06-21T07:53:14.000Z

Step 8 ran (skip condition not met — Step 7 had test_helpers/ + test_suite/ fixes). Output: `workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md 271 → PRD_FINALIZED.md 271 (0 line delta; all three edits inline within existing paragraphs — no new lines/sections; character-level additions only).

**Changes:**
- §2.4 — revise — Added `pour_cost_pct` to the enumerated list of recompute-mutations, and pinned that the creation-time `pour_cost_pct` recompute is its own version bump, so a menu item is minted at `version` 1 and returned at `version` 2. — `routes/menu_items.py:43`, `services/product.py:86-93`.
- §3.3 — revise — Pinned that recipe publish performs two distinct version bumps (the `recipe_cost_cents` recompute, always, even if unchanged + the DRAFT→PUBLISHED transition), advancing the recipe's `version` by two per publish. — `routes/recipes.py:95-97`, `services/product.py:67-83`.
- §3.4 — revise — Replaced the misleading "it starts at 0" with: `pour_cost_pct` is seeded at 0 then computed from the recipe cost as part of creation, so the created resource already carries the computed percentage (0 only if recipe cost is 0). — `routes/menu_items.py:35,43`, `services/product.py:86-93`.

**Cluster coverage:** Cluster A (version-count silence on publish→revise and delist traces) fixed by the three edits — a fresh implementer now reproduces version 5 after publish→revise and version 4 after the delist trace. Cluster B (count-session OCC ERR_STALE_VERSION) needed no PRD edit — confirmed a pure test-helper bug; the implementation is PRD-faithful (count-line POST returns the created CountLine per §2.2/§4; OCC keys on session version per §2.6).

**Pre-edit search log:** each edit's subject was identified and all related impl paths enumerated (all `recompute_pour_cost_pct`/`recompute_recipe_cost` callsites, propagate_unit_cost_change, menu-engineering, finalize rollup); wording was scoped narrowly (e.g. did NOT add a parallel total_variance_cost_cents bump claim; preserved forward-looking "recomputed whenever the price changes" prose) to avoid introducing new universal claims.

## Step 9: Complete PRD — 2026-06-21T07:57:56.000Z

Step 9 ran (always runs). Source: `PRD_FINALIZED.md` (existed) → `PRD_COMPLETED.md`, then edited.

- Line counts: `PRD_FINALIZED.md` 271 → `PRD_COMPLETED.md` 271 (no line added/removed; all changes in-paragraph). Char-delta +1062 (43291 → 44353).
- Counts: ambiguity-pins = 3, mismatch-revisions = 2.

Changes:
- §2.3 Pagination — insert — ambiguity — pinned that `created_at` ties (which the logical clock can produce) are broken by insertion order so list order is always creation order — `validate.py:120` (`paginate` sorts by `(created_at, _seq)`).
- §3.2 Keg Yield and Reorder Suggestions — revise — mismatch — replaced the spurious "freight value that has gone negative after defaulting → ERR_VALIDATION" clause; impl never range-checks `line_loss_pct` (a negative value just inflates `servings_net`), and rejects only `servings_net == 0` (422) plus a missing/non-positive `pour_size_ml` as a 400 schema error — `services/calc.py:60-61`, `routes/products.py:102-117`.
- §3.4 Menu and Menu Engineering — insert — ambiguity — pinned that the engineering report returns the classified universe items as a `created_at`-ascending paginated array and that running it bumps every member's `version` by one each time (even when class is unchanged) — `routes/menu_items.py:50-57`.
- §3.6 Invoices — revise — mismatch — dropped the "`vendor_invoice_no` must be unique per vendor" constraint; impl records it as supplied with no uniqueness check (and no error code exists for it) — `routes/invoices.py:28,36`.
- §3.7 Physical Counts — insert — ambiguity — pinned that an invoice's "posted within the window" instant is the logical-clock value captured at post time, and a voided invoice (posting instant cleared) contributes nothing to received-since — `routes/invoices.py:145,183`, `services/finalize.py:62-78`.

Notes: Verified-and-left-unchanged behaviors already pinned uniquely by the PRD: keg-yield/reorder response field names, discount tier inclusivity, 0.0875 tax, round-per-line recipe cost, menu-item creation pour_cost_pct bump (v1→v2), OCC on count-session add/finalize, keg-tap closed-interval-with-adjacency overlap, count-window strict ordering, waste floor-at-zero, clock default `2026-01-01T00:00:00Z`. Tests were used only as auxiliary cross-reference.

---

## Pipeline Complete — 2026-06-21T07:57:56.000Z

All 9 steps finished. Final state: **76/76 tests passing across all 8 parallel stability rounds** (orchestrator-verified). Task directory `tasks/task_0450_bar_beverage_inventory/` contains SCAFFOLD.yaml (+ DIFFICULTY/CORNER design), worklog.md, test_helpers/, test_suite/ (6 files, 76 tests), and workspace/ with INSTRUCTION.md, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, implementation/ (27 source files + results.{1..8}.json all green). Designed at Expert difficulty.

# Worklog — task_0213_bopis_curbside_pickup

## Step 1: Create task directory — 2026-06-07T03:02:35.000Z

Created `tasks/task_0213_bopis_curbside_pickup/` and `tasks/task_0213_bopis_curbside_pickup/workspace/` (pre-allocated path used verbatim; index-scan skipped per orchestrator instructions).

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-07T03:27:00.000Z

Generated all three scaffold artifacts for **task_0213_bopis_curbside_pickup** at **Expert** difficulty, built purely from the verbatim scenario and the scaffold-generator spec (no sibling tasks consulted). All files parse as YAML and `scaffold_lint.py` returns **VERDICT: clean lint**.

**Files written:**
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Scaffold metrics:**
- **Entities:** 12 (Customer, Store, Product, StoreInventory, PickupSlot, Order, OrderLine, Substitution, Hold, CurbsideCheckIn, PickupEvent [append-only], InventoryMovement [append-only ledger])
- **State machines:** 6 — Order *fulfillment* axis + Order *payment* axis (parallel dimensions on one row), OrderLine (cyclic substitution loop), Substitution, Hold, CurbsideCheckIn
- **Calculations:** 8 (inventory_availability dual-view, no_show_risk_posture, order_authorized_total, order_captured_total, order_refunded_total, substitution_price_delta, hold_expiry_deadline, slot_fill_status)
- **Validations / errors:** 22 ordered validations / 23 error codes
- **Endpoints:** 54 (incl. FK reverse-reachability GETs and 2 `/_clock` test-driving endpoints); **2 concurrency rules** (OCC on PickupSlot.version at submit, OCC on StoreInventory.version at restock)
- **Roles:** 6 (Anonymous, Customer [entity_backed], StorePicker, StoreAssociate, StoreManager, PlatformAdmin) — peer-roles model

**§1.8 difficulty instances:** 18 (all 9 §0.5 rules × exactly 2), each grounded in declared elements with falsifiable distinguishing aspects and precomputed literal asserts (e.g., captured 6600, substitution delta ±600/−300, money invariant 3000+3000=6000, strikes→BLOCKED at 4).

**§1.9 corner instances:** 39 total (36 active + 3 `excluded_because` stubs) across entities, state_machines, calculations, validations, endpoints, rbac, cross_cutting_concerns, consistency_model.

Design note for downstream: `api_prefix` is `/` (server root) — genuinely multi-root flat topology (orders, stores, products, customers as peer collections); this is what makes the lint's FK segment derivation resolve all 17 foreign keys.

## Step 3: Copy shared files — 2026-06-07T03:27:18.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-07T03:32:39.000Z

PRD generated at `workspace/PRD.md` for the `bopis-curbside-pickup` domain (~297 lines).

**Metrics:** 5 top-level sections (§1 Introduction, §2 Global Specifications, §3 Business Logic & Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue) with 22 subsections (12 in §2, 10 in §3).

**Hard Contract reports (all PASS):**
- Field coverage: 54/54 entity fields, 35/35 endpoint input params, 12/12 query/optional params present (added `checkin_status` to §3.6 on second pass).
- Rule coverage: 22/22 validations ordered in §2.12; 2/2 OCC rejections expressed (expected_slot_version/expected_inventory_version + error_id + 412); 33/33 state transitions across §3.3–§3.9 (both Order fulfillment + payment axes, OrderLine cyclic substitution, Substitution, Hold, CurbsideCheckIn); 8/8 calculations in precise prose; sibling-branch symmetry maintained.
- Path purity (§3): 456 backtick tokens scanned, 0 paths/methods leaked.

All 23 error IDs, 6 role names, 30 state-enumeration values present. §2.2 emitted verbatim from canonical source.

**Confirmation:** Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was read/grepped/referenced. No sibling tasks consulted.

## Step 5: Generate unit tests — 2026-06-07T03:50:16.000Z

Generated complete test infrastructure for task_0213 from the four inputs plus the unit-test-generator skill spec.

**Stage 1 — `test_helpers/` (9 files):** `types.py` (entity TypedDicts; `PickupEvent`/`InventoryMovement` carry only `id`+`created_at`), `api_client.py` (one method per PRD endpoint), `api_errors.py` (all 23 error IDs + HTTP-status map), `assertions.py` (per-entity + inventory/slot/money invariant checkers), `factories.py`, `constants.py`, `test_users.py` (entity-backed `make_customer_headers(id)` + opaque-role constants), `fixtures.py` (tiered composite helpers incl. `setup_awaiting_pickup_order`, `setup_short_picked_with_proposal`, `setup_picking_order`, `raise_customer_to_strikes`), `__init__.py`.

**Stage 2 — `test_suite/` (conftest + 7 test files, 72 tests):**
- Queue A (Difficulty): **36 tests** — all 18 difficulty instances covered by ≥2 tests (9 rules × 2 instances).
- Queue B (Corner): **36 tests** — all 36 non-stub corner instances covered by ≥1 test.

**Coverage audit: ALL CHECKS PASS** — 18/18 difficulty + 36/36 non-stub corner instances covered; every docstring ends with exactly one verbatim `Design:` tag resolving to a real instance; no untagged/dual-tagged/bad tags; no skip/xfail.

**Stubs (not translated, per spec):** the 3 `excluded_because:` corner stubs (`calculations/no_show_posture_watch_lower_boundary_at_two_strikes`, `validations/customer_blocked_vs_availability_priority`, `cross_cutting_concerns/cancel_submitted_cascade_releases_inventory_and_slot`) — all cross-refs resolve to real difficulty instances owning the assertion.

**Instances skipped due to PRD-first filter:** none.

**Verification:** all files `py_compile` clean; 72 tests collect under pytest; 109 quoted citation segments confirmed verbatim against PRD.md.

## Step 6: Generate implementation — 2026-06-07T03:50:16.000Z

Generated complete Python + Flask implementation at `workspace/implementation/`.

**Files (24 total):** `start.sh`, `requirements.txt` (flask==3.0.3); core: `app.py`, `db.py` (in-memory store), `clock.py`, `errors.py`, `response.py`, `middleware.py`; `services/` (common, inventory, money, derived, order_ops); `routes/` (customers, stores, products, store_inventory, pickup_slots, orders, order_lines, substitutions, curbside, clock_routes).

**Endpoints:** 54 implemented (matches PRD §4 table exactly).

**Contract compliance:** storage in-memory only (Python dicts keyed by UUID; no SQLite/JSON/tmp/external); no seeding (store starts empty every boot — verified `GET /orders` & `GET /store-inventory` return `total_count: 0`); `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec`, guards pip install behind `import flask` check.

**Behaviors verified by live HTTP tests:** full happy path (submit→pick→stage→ready→verify→pickup→COMPLETE, authorize=capture=1500); slot OCC (ERR_STALE_SLOT_VERSION) & inventory OCC (ERR_STALE_INVENTORY_VERSION); reserve/available model; short-pick→substitution propose/accept with signed delta; partial pickup→PARTIALLY_PICKED_UP→close (restock + PARTIALLY_REFUNDED); hold expiry via `/_clock/advance` sweep (restock + full refund + no-show strike); cancel SUBMITTED (release + full refund); abandon; curbside arrival/start-loading/complete with capacity+verified+duplicate gates; RBAC, ownership, pagination bounds, field validation returning correct error IDs/statuses.

**Fidelity notes:** validation precedence follows PRD §2.12; substituted line's effective unit price keyed on presence of ACCEPTED substitution (not transient `line_status`).

## Step 7: Run tests and iterate to PASS — 2026-06-07T04:07:27.000Z

**Iterations run:** 4 sweeps (1 baseline diagnosing 66/72, then 3 post-fix verification sweeps). Final state: two consecutive fully-clean 8-round parallel sweeps (16 rounds, 72/72 every round, 0 failed, 0 errors). Orchestrator independently re-ran a final 8-round sweep — all 8 rounds 72/72, 0 failed, 0 errors (results.1.json–results.8.json regenerated and retained).

**Tests deleted:** None. Every failing test traced to a verbatim PRD rule and was uniquely derivable; all failures were genuine implementation/test-helper/infra bugs.

**Fixes applied to `implementation/`:**
1. `routes/substitutions.py` — `accept_sub()`: on substitution acceptance, increment the parent line's `qty_picked` by `substitute_qty`. PRD §3.5 ("its already-picked units plus the substitute units are treated as picked for staging") and §3.6's hand-over ceiling keyed on `qty_picked`. Original code only flipped `line_status` to SUBSTITUTED without crediting substitute units, so handing over substituted units was wrongly rejected with `ERR_OVER_HANDOVER`. Root cause of 4 consistent money-test failures (`test_authorized_then_refund_evaluation_order_with_substitution_delta`, `test_captured_per_unit_then_multiply_reflected_on_pickup_event`, `test_captured_rounding_order_per_unit_then_multiply_then_sum`, `test_substitution_delta_then_partial_refund_evaluation_order`).
2. `start.sh` — replaced the per-boot `python3 -c "import flask"` import-probe (extra interpreter on every reboot) with a one-time `.deps_ok` sentinel; steady-state boots go straight to `exec python3 app.py`. Cuts boot-time CPU contention that under 8× concurrency occasionally pushed a reboot past the runner's 15s readiness window — the intermittent "API server could not be restarted" setup errors hitting arbitrary tests (test_03, test_05) in ~2/8 rounds. Sentinel is a build artifact (no entity data), in-memory-storage contract preserved.

**Fixes applied to `test_helpers/`:**
3. `fixtures.py` — `raise_customer_to_strikes()`: cycle loop hardcoded a 1-hour clock advance after staging regardless of the `hold_window_minutes` param. With `hold_window_minutes=120` (used by `test_expire_cascades_to_hold_strike_and_standing`), staging at T set the hold deadline to T+120min but the fixture only advanced to T+60min, so §3.7 hold-expirability check (`clock >= expires_at`) correctly rejected the expiry with `ERR_HOLD_NOT_EXPIRABLE` and setup failed. Rewrote loop to advance the logical clock to exactly `staged_at + hold_window_minutes` with a per-cycle stride exceeding the hold window so cycles never overlap.

## Step 8: Finalize PRD — 2026-06-07T04:10:35.000Z

Produced `workspace/PRD_FINALIZED.md` — minimal patch of `PRD.md` pinning the one PRD silence the Step 7 implementation fix revealed.

**Line counts:** PRD.md = 297, PRD_FINALIZED.md = 297. One line revised (the §3.5 substitution-acceptance sentence), 0% line-count delta.

**Change:**
- §3.5 (Substitution Negotiation) — revise — pinned that on substitution acceptance the line's `qty_picked` is increased by `substitute_qty` (becoming already-picked + substitute units), and that this combined `qty_picked` is the figure the §3.6 per-line hand-over ceiling compares against — `implementation/routes/substitutions.py:118`.

**Why only this:** Of the three Step 7 diff items, only item 1 revealed a PRD silence. Item 2 (start.sh `.deps_ok` sentinel) is an infra fix; item 3 (test_helpers fixture clock-advance timing) is a test-helper bug whose behavior (hold-window 120, inclusive `expires_at`) is already pinned in PRD §2.8/§3.1. Neither implies a PRD edit.

**NO-NEW-MISMATCH search log:** subject = `qty_picked` of a SUBSTITUTED line after acceptance and all readers. Enumerated impl paths: substitutions.py:118 (the write), orders.py:339 (ERR_OVER_HANDOVER ceiling), orders.py:343 (total_picked sum for partial-vs-full), orders.py:362 (HANDED_OVER marking), orders.py:415 (close not_taken restock to substitute product), order_ops.py:69-77 (expiry restock), orders.py:243-258 (stage_order guard keys on line_status not numeric qty_picked), services/money.py (capture/auth key on qty_handed_over/qty_ordered, effective unit price keyed on accepted substitution). Wording adjustment: dropped an initial "governs staging readiness" phrasing after confirming staging keys on `line_status`, not numeric `qty_picked`; final sentence attributes the numeric value only to the §3.6 hand-over ceiling — consistent with every enumerated path.

## Step 9: Complete PRD — 2026-06-07T04:15:29.000Z

Produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md` via a full PRD-vs-implementation scan.

**Line counts:** PRD_FINALIZED.md = 297 → PRD_COMPLETED.md = 297 (all in-paragraph inline inserts; no new paragraphs/sections). Chars: 46,840 → 49,122 (+2,282).

**Counts:** 9 ambiguity-pins, 0 mismatch-revisions. (No PRD prose actively contradicted the impl; every gap was silence the impl resolved with a definite choice.)

**Changes:**
- §2.4 — insert — ambiguity — `created_at`/`updated_at` and ledger `created_at` stamped from real server wall clock, not the logical clock (which governs only domain instants like `staged_at`/`expires_at`/cutoff/expiry) — `clock.py:12-15`, `db.py:44-60`.
- §2.8 — insert — ambiguity — clock endpoints need no auth headers but reject a supplied `X-User-Role` other than `PlatformAdmin` with `ERR_UNAUTHORIZED` — `routes/clock_routes.py:16-22`.
- §2.11 — insert — ambiguity — restock takes a signed `delta_on_hand` (appends a `RESTOCK`/`MANUAL` movement); a delta driving `on_hand` below zero → `ERR_INVALID_REQUEST` — `routes/store_inventory.py:88,96-101`.
- §3.1 — insert — ambiguity — duplicate `sku` → `ERR_INVALID_REQUEST` — `routes/products.py:26-28`.
- §3.1 — insert — ambiguity — inventory creation `on_hand` is a non-negative integer, zero permitted — `routes/store_inventory.py:24`, `services/common.py:77-81`.
- §3.2 — insert — ambiguity — duplicate `email` → `ERR_INVALID_REQUEST`; registration needs no auth headers but rejects a supplied role other than `Anonymous`/`PlatformAdmin` with `ERR_UNAUTHORIZED` — `routes/customers.py:21-24,31-33`.
- §3.3 — insert — ambiguity — submitting an order with no lines → `ERR_INVALID_STATE` — `routes/orders.py:173-174`.
- §3.4 — insert — ambiguity — `qty_picked > qty_ordered` → `ERR_INVALID_REQUEST`; pick state guard (order `PICKING` + line `RESERVED`) → `ERR_INVALID_STATE`; abandon guard (non-`SHORT_PICKED` or `qty_picked` ≠ 0) → `ERR_INVALID_STATE` — `routes/order_lines.py:68-73,109-113`.
- §3.6 — insert — ambiguity — verify accepts both fields as non-empty strings, matches against nothing, imposes no state guard; `handovers` body shape (`ERR_INVALID_REQUEST`/`ERR_REFERENCE_NOT_FOUND`) plus cumulative `ERR_OVER_HANDOVER` ceiling semantics — `routes/orders.py:285-294,305-341`.

**Deliberately not changed:** framework-level 404/405→`ERR_NOT_FOUND`; local check orderings inside restock/pick not enumerated by §2.12; curbside/order state-guard `ERR_INVALID_STATE` already implied by the §2.12 global state-guard rule.

---

## Pipeline complete — 2026-06-07T04:15:29.000Z

All 9 steps complete. Final state: **72/72 tests pass across 8 independent parallel rounds** (0 failed, 0 errors). Task directory `tasks/task_0213_bopis_curbside_pickup/` contains all expected artifacts: SCAFFOLD.yaml + 2 design indices, worklog.md, test_helpers/, test_suite/ (7 files, 72 tests), and workspace/ (INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ with results.1–8.json).

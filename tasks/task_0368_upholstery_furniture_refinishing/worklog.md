# Worklog — task_0368_upholstery_furniture_refinishing

## Step 1: Create Task Directory — 2026-06-15T12:35:19.000Z

Created `tasks/task_0368_upholstery_furniture_refinishing/` and `tasks/task_0368_upholstery_furniture_refinishing/workspace/`. Output directory pre-allocated (no ./tasks scan / index increment performed).

## Step 2: Generate Scaffold (Expert) — 2026-06-15T12:59:54.000Z

All three scaffold artifacts are generated and pass the linter cleanly. I did not read any sibling task directory — the scaffold was built purely from the scenario description and the skill specification.

## Summary

Generated three Expert-tier scaffold artifacts for `task_0368_upholstery_furniture_refinishing`:

**SCAFFOLD.yaml** (§1.0–§1.7)
- **Archetype**: workflow_orchestration + pricing_engine; topology **flat** (peer entities by FK, no nested URLs); state-machine shape **cyclic**; role model **peer_roles**; layers: dual-variant calc, cascading side effects, OCC, rate/threshold triggers, derived-field reconciliation.
- **12 entities**: Customer, FabricSku, FoamSpec, WorkOrder, ConditionPhoto, LineItem, Estimate, MaterialOrder, ShopDay, FulfillmentLeg, WarrantyClaim, Payment.
- **5 state machines**: WorkOrder (10-state with a cyclic estimate-revision loop, branching approve/decline, compensating cancel), MaterialOrder, FulfillmentLeg, ShopDay (OPEN/FULL/CLOSED), WarrantyClaim (branching approve/deny).
- **1 concurrency rule**: OCC on `WorkOrder.version` for estimate-supersede (412).
- **8 calculations**: per_piece_subtotal, estimate_total (forward-looking, tiered rush surcharge), final_invoice (chronological actuals), material_finalized_cost (provisional vs finalized), turnaround (threshold), warranty_coverage (90-day threshold), shop_capacity (aggregate), balance_due.
- **52 endpoints** (includes one `/_clock/set_current_utc` test-driving endpoint for deterministic warranty windows).
- **21 error codes**, all triggerable and asserted.
- **4 roles**: IntakeClerk, Estimator, ShopManager (opaque); Customer (entity_backed:Customer).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8): all 9 Difficulty Rules × **2 instances = 18 instances**, each with computed literal asserts (e.g., estimate/final divergence 40300 vs 42000; tiered rush 12000; round-per-term subtotal 36942; capacity FULL at exact 8.0; warranty covered at exactly day 90).

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9): **37 active corner instances + 3 excluded_because stubs** across all 9 claim-extraction sections (entities, state machines, calculations, validations, endpoints, errors, RBAC, cross-cutting layers, consistency model).

**Verdict**: `scaffold_lint.py` reports **clean lint** (495 calls scanned). All grounds references resolve; forbidden concurrency vocabulary absent; no dead enum values; all instance names unique across both design files; all stub references resolve to real §1.8 instances.

## Step 3: Copy Shared Files — 2026-06-15T13:00:13.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0368_upholstery_furniture_refinishing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-15T13:05:05.000Z

The PRD is complete and verified. The §4 table has all 52 endpoints, the §5 table has all 21 error codes, and the structure matches the template.

## Summary

Generated `workspace/PRD.md` — a 283-line PRD for the Upholstery Refinishing API.

**Structure:**
- **§1 Introduction** — 2 paragraphs framing the work-order hub, the dual estimate-vs-invoice financial views, and the four-role model
- **§2 Global Specifications** — 9 subsections: RBAC (with all four role identities translated — three opaque, `Customer` entity-backed), the verbatim §2.2 envelope, pagination, identity/timestamps/versioning (including `ConditionPhoto` as the common-fields-false exception), OCC on `WorkOrder.version`, monetary/day precision, cascading derived-field reconciliation, nested/filtered retrieval, request well-formedness
- **§3 Business Logic** — 10 subsections organized by lifecycle: intake/catalog, per-piece pricing, estimate revision loop, approval/deposit/turnaround, material procurement, production scheduling, finish/settle/complete, cancellation compensation chain, warranty, and a dedicated validation-ordering subsection
- **§4 Endpoint Definitions** — 52-row, 4-column table
- **§5 Error Code Catalogue** — 21-row, 2-column table

**Coverage (all three Hard Contracts PASS):**
- **Contract 1 (Field-Name):** 59/59 entity field names, 44/44 endpoint input identifiers, 10/10 query/path params — all present in backticks, 0 missing
- **Contract 2 (Rule):** all 21 error IDs, all 19 state values, all 11 calculation constants (6500, 50000, 15%, 30%, 3, 8, one-half, 2, 90, 30%, 86400) embedded in business prose; OCC rule fully expressed (`expected_work_order_version` + `ERR_STALE_WORK_ORDER_VERSION` + 412); all state-machine transitions, the dual estimate/final-invoice calculations, tiered rush surcharge, turnaround bands, warranty coverage with `<= 90` boundary inclusivity, compensation cascade, and validation priority ordering all surfaced
- **Contract 3 (§3 Path Purity):** 393 §3 backtick tokens scanned — 0 path-leading tokens, 0 bare HTTP methods, 0 method+path combos; endpoints referenced only via state-transition framing and role+action verbs

All calculation formulas use precise business prose (per-term round-half-up before summation, ceil for deposit/turnaround, floor for warranty days) with no pseudocode or fuzzy wording. Per the hard constraint, the two withheld design index files were not read or referenced.

## Step 5: Generate Unit Tests — 2026-06-15T13:21:09.000Z

Everything checks out. The test infrastructure is complete and passes all completeness/citation audits.

## Summary

Generated complete test infrastructure for **task_0368_upholstery_furniture_refinishing** under the design-index-only contract.

**Stage 1 — `test_helpers/` (9 files):**
- `types.py` — entity TypedDicts + status/role enums; `ConditionPhoto` correctly omits `updated_at`/`version` (common_fields:false); `Payment.status` fixed to `RECORDED`
- `api_client.py` — one method per endpoint (all ~50 endpoints incl. `/_clock/set_current_utc`)
- `api_errors.py` — 21-error catalog with HTTP-status map registered to the framework
- `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (Customer is `entity_backed` → `make_customer_headers(id)` builder; 3 opaque operator roles), `fixtures.py` (full lifecycle composites: intake → estimating → awaiting-approval → approved → in-production → ready → completed, plus catalog/shop-day/material helpers), `__init__.py` barrel

**Stage 2 — `test_suite/` (7 files + conftest, 73 test functions):**
- test_01 intake/CRUD · test_02 estimate/pricing · test_03 materials/cost · test_04 scheduling/fulfillment · test_05 cancellation/compensation · test_06 warranty · test_07 RBAC/auth

**Coverage:**
- **Queue A (Difficulty):** 18/18 instances, each with exactly **2 tests** (36 tags) — second tests use genuinely distinct facets (boundary X-1/X+1 complements, positive-unblock paths, "no state change" assertions, repeated-loop, larger-reservation invariants), each with its own verbatim PRD citation
- **Queue B (Corner):** all **37 non-stub** instances covered with ≥1 test (37 tags); the **3 `excluded_because:` stubs** (`approve_from_intake_returns_invalid_state`, `estimate_total_forward_looking_no_rush`, `material_provisional_cost_at_order`) correctly **not translated** — their difficulty cross-references all resolve
- **Instances skipped:** none beyond the 3 mandated stubs; every non-stub instance passed the PRD-first two-condition filter (the PRD is unusually explicit, so no gaps required skipping)

**Audits passed:** every test carries exactly one `Design:` tag; all 88 PRD docstring citations verified verbatim against PRD.md (one paraphrase bug fixed); no scaffold leakage; no `skip`/`xfail`; all test_suite→test_helpers imports resolve; all files compile cleanly.

Note: the `prd_bench_local_runner` framework is pip-installed by the runner (not present here), so I validated via `py_compile` + static import/citation cross-checks rather than live execution.

## Step 6: Generate Implementation — 2026-06-15T13:21:09.000Z

The implementation is complete and validated end-to-end.

## Summary

Generated a complete Python + Flask implementation for the Upholstery & Furniture Refinishing API at `workspace/implementation/`.

### File list
- `start.sh` — launcher
- `requirements.txt` — `flask==3.0.3`
- `app.py` — entry point, blueprint registration, error handlers, `0.0.0.0:$PORT` bind
- `db.py` — in-memory store (dicts keyed by id) + test-driving server clock
- `errors.py` — `ApiError` class + all 21 error IDs / HTTP status map
- `response.py` — success/array/error envelope helpers (`meta`/`response_type`/`data`)
- `middleware.py` — auth (`X-User-ID`/`X-User-Role`), RBAC, owner check
- `helpers.py` — common fields, pagination, body validation, FK/existence lookups, serialization
- `calculations.py` — all 8 calc rules with `Decimal` round-half-up per-term
- `services.py` — derived-field reconciliation (balance_due, materials_committed, shop-day status flip)
- `routes/` — `customers.py`, `catalog.py`, `work_orders.py`, `estimates.py`, `workflow.py`, `materials.py`, `scheduling.py`, `warranty.py`

### Endpoints
All 52 distinct method+path routes from the PRD §4 table are implemented and registered (cross-checked programmatically: zero missing). Covers the full lifecycle.

### How start.sh launches the server
Reads `$PORT` (default 10000), binds `0.0.0.0`, runs in foreground via `exec python3 app.py`. The pip install is guarded by a cheap `import flask` check so per-test reboots don't re-run installs.

### Key correctness properties verified by smoke tests
- Storage is in-memory only — state fully wipes on `start.sh` reboot (no SQLite/JSON/tmp; no seeding).
- Calculations validated against concrete numbers (per-piece subtotal round-per-term, rush tiering 15%→50000c + 30% above, turnaround bands, deposit gate ceil(0.30·total), final-invoice divergence, warranty boundary covered at exactly 90 days not day 91).
- State machines, compensation chain (yard + money conservation, WALLET store-credit), OCC 412 on stale version, validation ordering, delivery half-open window conflict, RBAC all pass.

**Behavioral note:** placing/receiving/cancelling a material order bumps the parent work order's `version` (mutates `materials_committed_cents`) per PRD §2.7's side-effect rule — callers must re-read the work order version before a subsequent OCC-guarded operation.

## Step 7: Run Tests and Iterate — 2026-06-15T17:13:38.000Z

All 8 parallel rounds are clean. Final state: passed == total == 72 across every round, zero union failures.

## Summary

**Iterations run:** 1 fix batch (after correcting the runner invocation — the `--start-command` must embed `cd <impl-dir> && bash start.sh`, since the runner launches the start command from the project root, not the implementation directory).

**Starting state:** 8 stable rounds at 68/73 (5 stably-failing tests; the orientation's 4 test_04 delivery/settlement failures were already passing).

**Tests deleted (1):**
- `test_material_order_board_feet_without_foam_returns_catalog_unavailable` (test_01) — **PRD-silence (STEP 1a coverage failure)**. The test asserts that placing a *material order* with `board_feet_ordered > 0` and no `foam_spec_id` returns `ERR_CATALOG_ITEM_UNAVAILABLE`. The cited PRD §3.2 sentence ("a positive `board_feet_required` without a foam spec is itself invalid") is scoped to *line items* (field `board_feet_required`); the material-order section §3.5 uses a different field (`board_feet_ordered`) and only specifies negative-value, DISCONTINUED, and FK rejections — it is silent on board-feet-without-foam. The PRD-faithful implementation correctly computes a zero-foam-cost provisional and returns success. Scaffold rule that drove generation: `Corner/errors/material_order_board_feet_without_foam_returns_catalog_unavailable` (a scaffold-only conflation of the line-item rule onto material orders).

**Fixes applied to test_suite/ (test-vs-PRD consistency, STEP 2 — test_helpers were not the culprit here; the bad preconditions lived in the test bodies):**
- `test_suite/test_03_materials_and_cost.py` — `test_material_order_provisional_cost_from_catalog` and `test_material_order_finalized_cost_from_received_price`: removed the `deposit_amount_cents=10000` override. For these REUPHOLSTERY orders the estimate total is 36800 cents, so the PRD §3.4 deposit floor is ceil(0.3·36800)=11040; the literal 10000 violated it, and the implementation correctly returned `ERR_DEPOSIT_TOO_LOW`. Dropping the override lets the deposit default to the full estimate total (always ≥ floor); the deposit value is incidental to the material-order-cost assertions.
- `test_suite/test_02_estimate_and_pricing.py` — `test_revision_supersede_reconciles_work_order_totals` and `test_revision_supersede_repoints_active_estimate`: removed the mid-revision `create_line_item` call issued while the order was `REVISION_REQUESTED`. PRD §3.2 permits line-item adds only in `INTAKE` (first item) and `ESTIMATING` (subsequent), and is silent on `REVISION_REQUESTED`; the PRD-faithful implementation correctly rejects with `ERR_INVALID_STATE`. Restructured both setups to create both line items up front during `ESTIMATING`, so v1 and v2 are authored from the same line-item set (v2 total recomputed equals v1's 39000). This preserves every PRD-covered assertion (§3.3 supersede→`SUPERSEDED`, `active_estimate_id` repoint, `estimate_total_cents` set to the new estimate's total, and §3.7 `balance_due_cents` reconciliation) while dropping the PRD-unsupported precondition.

**Fixes applied to implementation/:** None. No implementation check was weakened or added; all failures traced to test preconditions/assertions that diverged from PRD prose.

**Final result:** 8/8 parallel rounds at passed == total == 72, zero union failures, stable.

## Step 8: Finalize PRD — 2026-06-15T17:18:30.000Z

**Line counts:** PRD.md = 283 lines; PRD_FINALIZED.md = 283 lines. Both edits are inline within existing paragraphs, so line count is unchanged (%-delta of lines = 0%; two paragraphs modified out of 283 lines).

**Changes (one bullet each):**

- **§3.2 — insert — line-item add is permitted only in INTAKE (first) or ESTIMATING (subsequent); any other status (incl. REVISION_REQUESTED) rejects with ERR_INVALID_STATE, checked before field/catalog rules** — `implementation/routes/work_orders.py:159-161` (and ordering vs `:170-190`).
- **§3.5 — insert — a positive `board_feet_ordered` with null `foam_spec_id` is NOT rejected on a material order; the order is accepted with a 0 foam cost term** — `implementation/routes/materials.py:18-86` (foam_price=0 at `:54-55`; `calc.provisional_cost` at `calculations.py:85-89`).

**Deposit-override item:** No PRD change. PRD §3.4 (line 140) already pins the deposit floor as ceil(0.30 · estimate_total_cents) with ERR_DEPOSIT_TOO_LOW, matching `calculations.py:148-150`. Pure fixture bug — correctly no edit.

**Per-edit pre-edit search log:**

Edit 1 (§3.2, line-item state gating):
- (a) Subject: which work-order statuses permit creating a line item, and the error/ordering when disallowed.
- (b) Enumerated paths: `create_line_item` (work_orders.py:134-218) — the status guard at :159-161 (rejects all but INTAKE/ESTIMATING with ERR_INVALID_STATE), first-item advance INTAKE→ESTIMATING at :214-216, FK check :164-167, field rules :170-177, catalog availability :180-190; grep `db.line_items[` confirmed this is the only line-item creation site (no creation in estimates.py); §3.10 global validation ordering (priority 20 ERR_INVALID_STATE before priority 30/31).
- (c) Adjustment: phrased the ordering claim as "before the service-type field rules and catalog-availability constraints" (both genuinely after the state check) rather than an absolute "first" claim, since FK existence also precedes field rules but is not mentioned; this keeps the sentence consistent with every enumerated path and §3.10.

Edit 2 (§3.5, material-order board-feet-without-foam):
- (a) Subject: acceptance/cost behavior of a material order with board_feet_ordered > 0 and null foam_spec_id.
- (b) Enumerated paths: `create_material_order` (materials.py:18-86) — no board-feet-without-foam guard, foam_price=0 when foam_spec_id null (:54-55); `calc.provisional_cost` (calculations.py:85-89) — foam term = round_cents(board_feet, 0) = 0; `receive_material_order`/`calc.finalized_cost` (materials.py:119-154, calculations.py:92-96) — same shape, foam term 0; the distinct line-item path `create_line_item` (work_orders.py:188-190) which DOES reject board_feet_required>0 without foam on the separate `board_feet_required` field.
- (c) Adjustment: explicitly contrasted "Unlike the line-item rule of §3.2" and scoped the closing universal ("Only the negative-value, DISCONTINUED, and missing-reference checks above can reject a material order on these fields") to "on these fields," so it does not collide with the line-item rule at line 124 nor over-claim against global well-formedness (ERR_INVALID_REQUEST) checks.

## Step 9: Complete PRD — 2026-06-15T17:24:40.000Z

**File metrics**
- Source `PRD_FINALIZED.md`: 283 lines, 43,708 chars
- `PRD_COMPLETED.md`: 283 lines, 46,191 chars
- Char delta: +2,483 (all edits are in-paragraph inserts/revisions; no new lines, sections, or paragraphs)

**Counts**
- Ambiguity-pins (PRD silent → pinned): 6
- Mismatch-revisions (PRD described differently → revised): 1
- Total changes: 7

**Changes**
- §2.8 (Nested/Filtered Retrieval) — insert — ambiguity — enumerated the actual filter keys impl exposes and pinned that several lists accept non-FK value filters (work orders `status`/`customer_id`, material orders `status`, fulfillment legs `kind`/`status`, shop days `status`), all return-the-subset — work_orders.py:66-72, materials.py:105/113, scheduling.py:58/204-214, estimates.py:132/136
- §3.3 (Authoring Estimates) — insert — ambiguity — pinned that a `supersedes_estimate_id` violating the null-on-first / name-current-ACTIVE rule is rejected with `ERR_INVALID_REQUEST` (PRD stated the rule but not the error) — estimates.py:46-52
- §3.5 (Procuring Materials, placement) — insert — mismatch — PRD's "After an order is approved" implied a state precondition; impl enforces none, so pinned that placement raises no `ERR_INVALID_STATE` and succeeds against any work-order status — materials.py:18-86 (no status check)
- §3.5 (yard reservation) — revise — ambiguity — pinned that the full `yards_ordered` is reserved/debited unconditionally even below zero (on-hand stock is not a floor), and a foam-only / zero-yard order reserves nothing — materials.py:75-79
- §3.5 (Receiving) — insert — ambiguity — pinned that `received_fabric_price_cents_per_yard` / `received_foam_price_cents_per_board_foot` are integers defaulting to 0 when omitted/null, with wrong-type rejected as `ERR_INVALID_REQUEST` (PRD implied they were always supplied) — materials.py:125-136
- §3.6 (Leg lifecycle, dispatch) — insert — ambiguity — pinned that a PICKUP/DELIVERY dispatch with missing/invalid window is rejected with `ERR_INVALID_WINDOW` — scheduling.py:227-232
- §3.7 (Completion) — insert — ambiguity — pinned that completing while not `READY_FOR_FULFILLMENT`, or with no COMPLETED PICKUP/DELIVERY leg, is rejected with `ERR_INVALID_STATE` — workflow.py:164-174
- §3.10 (Validation Ordering) — revise — mismatch — rewrote the global order to match impl: role-check (no NOT_OWNER yet), then pagination bounds before existence on lists, then path existence, then `ERR_NOT_OWNER` only after the work order is found, then scalar body well-formedness (`ERR_INVALID_REQUEST`) before state, then state/FK/version/cross-entity/business; noted the FK-body-reference vs state position varies by operation, and that the §3.3 `supersedes` linkage check is evaluated last — middleware.py:31-34 + estimates.py/workflow.py/work_orders.py/materials.py/scheduling.py handler bodies, customers.py:46-47

**Notes on items deliberately left unchanged** (already pinned or consistent): rush surcharge tiering, deposit ceiling rounding, turnaround bands, warranty `<=90` boundary, balance-due basis switch, the `{}` clock response (covered by §2.2 no-data rule), and the `complete` "balance_due ≤ 0" clause (subsumed by exact-match settlement).

## Pipeline Complete — 2026-06-15T17:24:40.000Z

Resume from Step 7 finished. Final state: 8/8 parallel rounds at passed == total == 72, stable. Artifacts present: `workspace/PRD.md`, `workspace/PRD_FINALIZED.md` (Step 8), `workspace/PRD_COMPLETED.md` (Step 9), and `workspace/implementation/results.{1..8}.json` (all green).

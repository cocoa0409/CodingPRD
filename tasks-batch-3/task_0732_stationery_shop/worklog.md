# Worklog — task_0732_stationery_shop

## Step 1: Create task directory — 2026-07-04T11:05:22.000Z

Created `tasks/task_0732_stationery_shop/` and `tasks/task_0732_stationery_shop/workspace/`. Pre-assigned ID used directly (no re-assignment). Scenario: Stationery & Custom-Invitation Shop. Difficulty: Expert.

## Step 2: Generate Scaffold — 2026-07-04T14:00:00.000Z

All three files written and lint clean. Here is the summary:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_0732_stationery_shop/SCAFFOLD.yaml` — **1532 lines**
- `/home/ubuntu/github/CodingPRD/tasks/task_0732_stationery_shop/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — **1514 lines**
- `/home/ubuntu/github/CodingPRD/tasks/task_0732_stationery_shop/SCAFFOLD_CORNER_DESIGN.yaml` — **1462 lines**

## Top-level counts

- **Entities:** 12 (Customer, Designer, PaperStock, FinishOption, EventPackage, Design, Proof, Order, LineItem, AddressingJob, WorkOrder, Shipment)
- **Endpoints:** 54 (business + 2 test-driving `/_clock/set_current_utc`, `/_payments/simulate`)
- **State machines:** 4 (Proof with cycle CHANGES_REQUESTED↔SUBMITTED; Order with terminal branches and IN_PRODUCTION cancel; WorkOrder with parallel production_status × addressing_status dimensions; Shipment)
- **Calculations:** 10 (line-item tiered pricing with reorder-lock variant; order subtotal per-line-then-sum; reorder discount; rush tiered surcharge; deposit locked at confirm; total; expected_lead_days; proof_expires_at std/rush variants; two cash + inventory conservation invariants)
- **Validations:** 29 rows spanning auth / existence / state / business_safety / business_constraint / business_temporal / business_referential / business_fiscal
- **Errors:** 31
- **Roles:** 3 (Customer entity_backed, Designer entity_backed, ShopAdmin opaque) with peer_roles model
- **Concurrency rules:** 1 true race — line-item-create-stale-order OCC on Order.version
- **§1.8:** 9 rule_ids × 2 instances = **18 instances** (minimum floor met)
- **§1.9:** **31 active instances + 5 `excluded_because` stubs** across 9 sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting, consistency_model)
- **Lint verdict:** `clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (537 calls scanned)

## Expert-tier adjustments vs. profile

- **Endpoint count 54** exceeds the Expert band (20–32); the scenario legitimately needed 20+ GET endpoints for FK reverse-reachability across 12 entities plus separate production/addressing/shipment dimensions. Density remained high — the extras are almost all reads, with 22 mutating endpoints driving the workflow.
- **Complexity_profile chosen:** primary `workflow_orchestration` + secondary `pricing_engine`; entity_topology `hybrid`; state_machine_shape `cyclic`; role_model `peer_roles` (avoiding the over-used approval_chain).
- **Dual-variant Rule 1** placed on two entity domains (Order-fiscal line-item pricing vs. Proof-lifecycle expiry) rather than repeating the fiscal domain.
- **Combinatorial Rule 2** uses modes (a) tiered non-linear branch and (b) explicit per-line-then-sum rounding order — not two mode-(a)s.
- **Cascade Rule 4** uses two distinct triggers (explicit `/orders/{id}/cancel` vs. system clock advance past `Proof.expires_at`), yielding depth-3 and depth-2 chains.
- **Rule 8 overlap** covers two distinct interval semantics — closed-interval-with-adjacency-rejected on press slots vs. aggregate-daily-capacity on addressing jobs on a different resource entity.
- **Rule 9 invariants** on two conserved quantities of different types (monetary cents vs. physical inventory units).
- Added the mandatory `/_clock/set_current_utc` (default 2026-03-01T00:00:00Z) and a `/_payments/simulate` test-driving endpoint. All fixture dates fall after the default clock time.

## Step 3: Copy INSTRUCTION.md — 2026-07-04T14:01:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0732_stationery_shop/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-04T14:06:00.000Z

The PRD is complete. Summary follows.

**PRD generation summary for task_0732_stationery_shop**

(a) **Output**: `/home/ubuntu/github/CodingPRD/tasks/task_0732_stationery_shop/workspace/PRD.md` — 342 lines.

(b) **Section counts**:
- §2 subsections: 11 (`2.1` User/RBAC, `2.2` Response Structure verbatim, `2.3` Pagination, `2.4` Common Resource Properties, `2.5` Nested Resource Retrieval, `2.6` Monetary/Days/Precision, `2.7` OCC, `2.8` Catalog Lifecycle & Paper Reservations, `2.9` Store Credit & Cash Conservation, `2.10` Cascades & Auto-Transitions, `2.11` Validation Priority).
- §3 subsections: 9 (Catalog → Design & Order Creation → Line Items & Pricing → Rush → Confirm/Deposit/Proofing → Proof Workflow → Production & Addressing → Shipment/Delivery → Cancellation/Forfeiture/Clock).
- §4 endpoint table: 54 endpoint rows covering all scaffold endpoints (Customer, Designer, PaperStock, FinishOption, EventPackage, Design, Proof, Order, LineItem, AddressingJob, WorkOrder, Shipment, `/_clock`, `/_payments/simulate`).
- §5 error catalogue: 31 rows.
- **Entities documented**: 12 (all scaffold entities named + fields covered).
- **State machines documented**: 4 (Proof, Order, WorkOrder with two independent dimensions, Shipment) — all transitions expressed in prose with preconditions, side effects, and cascade rules.
- **Calculations documented**: 9 (line_item_price_cents with dual variants list_price/reorder_locked, order_subtotal_cents with pinned per-line-then-sum ordering, reorder_discount_cents, rush_surcharge_cents with two tier brackets, deposit_due_cents locked at confirm, total_cents, expected_lead_days, proof_expires_at with standard/rush variants, and both conservation invariants — cash_conservation and paper_reserved_conservation — narrated in §2.8/§2.9).

(c) **Hard Contracts**:
- Contract 1 (Field-Name Coverage): PASS — all 65 required field/param names appear verbatim in backticks; initial pass surfaced 11 missing fields (`approved_at`, `balance_due_cents`, `delivered_at`, `deposit_due_cents`, `deposit_paid_at`, `dispatched_at`, `email`, `new_status`, `phone`, `proof_id`, `submitted_at`) which were added by introducing bare-form mentions in natural prose homes rather than dumping-ground lists.
- Contract 2 (Rule Coverage): PASS — every error id in scaffold is mentioned in §1–4 prose; every scaffold state/enum appears verbatim; sibling-branch symmetry preserved (both rush tiers, both proof-expiry variants, both pricing variants, both cancellation cascades DEPOSIT_PENDING vs IN_PRODUCTION). Priority ordering explicitly rendered in §2.11. OCC rule in §2.7 names write endpoint (add-line-item), `expected_order_version` field, `ERR_STALE_VERSION`, and HTTP 412 in stale-version framing (no "simultaneously"/race framing).
- Contract 3 (§3 Path Purity): PASS — 395 backtick tokens scanned in §3; zero tokens starting with `/`, zero bare HTTP methods, zero method+path combos. Endpoints are named via state-transition framing, role+action verbs, or capability descriptions throughout.

**Zero-Silence observations**: (i) `balance_due_cents` is documented as read-only and explicitly not consumed by the delivery cascade, matching the scaffold note about "out of band" invoicing. (ii) Forfeiture is called out as the deliberate exception to the cash-conservation invariant. (iii) The closed-interval press-slot semantics including boundary adjacency are explicit. (iv) The per-line-then-sum rounding order is pinned in prose (§3.3), not just implied. (v) `Customer.cumulative_deposits_paid_cents` monotonicity (never decremented on refund) is called out both in §2.9 and again in §3.8 for the delivery cascade.

## Step 5: Generate Unit Tests — 2026-07-04T14:27:00.000Z

All done. Total: 67 tests (36 difficulty + 31 corner).

Summary:

**test_helpers/ (9 files, 1199 lines total)**
- `__init__.py` (59 lines) — barrel export
- `api_client.py` (181 lines) — ApiClient with one method per PRD endpoint
- `api_errors.py` (77 lines) — ApiErrorId enum + framework registration
- `assertions.py` (108 lines) — per-entity assertions
- `constants.py` (46 lines) — thresholds (rush tiers, reorder window, capacity)
- `factories.py` (109 lines) — payload builders
- `fixtures.py` (336 lines) — composite setup helpers (Tiers 0–5)
- `test_users.py` (32 lines) — role headers with `make_customer_headers`/`make_designer_headers` for identity threading
- `types.py` (251 lines) — status enums + entity TypedDicts

**test_suite/ (10 files, 1760 lines total)**
- `conftest.py` (27 lines) — pytest bridge
- `test_01_catalog_and_crud.py` (146 lines) — 9 corner tests
- `test_02_state_machines.py` (96 lines) — 4 corner tests
- `test_03_calculations.py` (132 lines) — 4 corner tests
- `test_04_validations.py` (106 lines) — 4 corner tests
- `test_05_endpoints_and_concurrency.py` (123 lines) — 5 corner tests
- `test_06_errors_and_rbac.py` (90 lines) — 5 corner tests
- `test_07_pricing_and_variants.py` (196 lines) — 6 difficulty tests
- `test_08_workflows_and_cascades.py` (408 lines) — 12 difficulty tests
- `test_09_difficulty_second_pass.py` (436 lines) — 18 difficulty tests

**Coverage totals**
- **Difficulty queue A**: 36 tests across 18 instances (≥2 per instance, exactly 2 each) ✓
- **Corner queue B**: 31 tests across 31 non-stub instances (≥1 per instance) ✓
- **Excluded stubs (5)** correctly untranslated: `delivered_order_cannot_be_cancelled`, `proof_cycle_and_parallel_dimensions_already_exercised_by_1_8`, `order_subtotal_pinned_per_line_then_sum_already_covered`, `proof_expired_customer_action_returns_expired`, `cascading_side_effects_confirm_reserves_paper` — each cross-references a real difficulty instance name in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`.

**PRD-first filter**: no non-stub instances were skipped due to filter failure. Every rule I generated is verbatim-covered by a distinct sentence in PRD.md (§2.1 RBAC, §2.4 version, §2.5 validation, §2.7 OCC, §2.8 reservations, §2.9 cash conservation, §2.10 cascades, §2.11 priority band, §3.1 catalog defaults, §3.2 reorder eligibility, §3.3 tier multiplier + reorder-locked, §3.4 rush window, §3.5 confirm/deposit, §3.6 proof cycle/revision fee/expiry, §3.7 press slot + addressing capacity, §3.9 cancellation branches).

**Docstring tagging**: 100% of tests carry exactly one `Design: Difficulty/<rule_id>/<instance.name>` or `Design: Corner/<section>/<instance.name>` line, verified programmatically.

## Step 6: Generate Implementation — 2026-07-04T14:18:00.000Z

**Implementation summary for task_0732_stationery_shop:**

Files written under `workspace/implementation/` (line counts):
- `start.sh` (9) — guards `pip install` on `flask` import, `exec python3 app.py`
- `requirements.txt` (1) — flask==3.0.3
- `app.py` (73) — Flask app factory, blueprint registration, ApiError handler
- `db.py` (85) — in-memory stores (customers, designers, paper_stocks, finish_options, event_packages, designs, proofs, orders, line_items, addressing_jobs, work_orders, shipments) + logical UTC clock (default 2026-03-01T00:00:00Z), UUID minting, ISO formatting with 3ms
- `errors.py` (90) — 32-entry ApiError catalog + HTTP status map
- `middleware.py` (29) — X-User-Role / X-User-ID auth extraction, role & ownership checks
- `response.py` (68) — success/error envelope (`meta.api_request_id`, `api_request_timestamp`, `response_type`, `data`), pagination meta (`limit`, `offset`, `total_count`, `has_more`)
- `models.py` (151) — `make_common`, `bump`, existence lookups per entity
- `services.py` (288) — pricing calculations (tiered line pricing with Decimal + ROUND_HALF_UP, subtotal, reorder discount, rush surcharge, deposit due, expected lead days, proof expiry), reservation adjust, cascade helpers (deposit+approval → IN_PRODUCTION, both dims complete → READY_TO_SHIP), proof expiry-on-read cascade
- `util.py` (156) — JSON body parsing, typed field getters, pagination extraction
- `routes/customers.py` (76), `routes/designers.py` (52), `routes/catalog.py` (197) — paper/finish/event-package CRUD + PATCH + discontinue
- `routes/designs.py` (136), `routes/proofs.py` (255), `routes/orders.py` (494), `routes/line_items.py` (62), `routes/addressing.py` (76), `routes/work_orders.py` (183), `routes/shipments.py` (108), `routes/admin.py` (63)

**Endpoints wired (54 total)**: every endpoint from the scaffold's `endpoints` block — customer/designer/paper/finish/package CRUD; design draft/patch/list; proof create/submit/request-changes/approve/get/list; order create/line-items add/delete/apply-rush/confirm/pay-deposit/cancel/get/list; work-order production+addressing; shipment dispatch/mark-delivered; `/_clock/set_current_utc`; `/_payments/simulate`.

**Entity storage layout**: dict-per-entity keyed by UUID; all entities carry `id`/`created_at`/`updated_at`/`version` via `models.make_common`; every mutation calls `models.bump` (updated_at + version++). No seeding — stores are empty on boot; the default logical clock is `2026-03-01T00:00:00Z`.

**State-machine coverage**:
- Proof: DRAFT ↔ SUBMITTED ↔ CHANGES_REQUESTED → APPROVED; DRAFT/SUBMITTED/CHANGES_REQUESTED → CANCELLED (cascade); SUBMITTED → EXPIRED (system on read cascades order → CANCELLED, design → ARCHIVED)
- Order: CART → DEPOSIT_PENDING (confirm) → IN_PRODUCTION (dual-cascade at deposit+approval) → READY_TO_SHIP (workorder both-dim complete) → SHIPPED → DELIVERED; CART/DEPOSIT_PENDING/IN_PRODUCTION → CANCELLED with correct actor gating (ERR_ORDER_NOT_CANCELLABLE for customer @ IN_PRODUCTION)
- WorkOrder: production NOT_STARTED → PRINTING (with press-slot closed-interval overlap check including adjacency) → FINISHING → COMPLETED; addressing PENDING → IN_PROGRESS (500/day capacity across scheduled_date) → COMPLETED
- Shipment: PREPARING → DISPATCHED → DELIVERED; PREPARING → CANCELLED (cascade)
- Cascades: confirm creates DRAFT proof + PROOFING design + reserves paper; approve+deposit → spawn WorkOrder; both work-order dims complete → spawn Shipment; deliver → archive design + release paper; cancel from DEPOSIT_PENDING moves deposit_paid_cents → credit_balance_cents; cancel from IN_PRODUCTION forfeits deposit

**Pricing/precision**: tier multipliers (1.0/1.0/0.9/0.8/0.7) applied via `Decimal * Decimal` then `ROUND_HALF_UP`; finish component is integer `surcharge * qty`; per-line rounding pinned before summing to subtotal; reorder discount 10% and rush pct (15%/30%) applied against `subtotal - reorder_discount`; deposit locked at confirm; `total = subtotal - reorder_discount + rush + revision_fee`; `balance_due = max(0, total - deposit_paid)`.

**start.sh**: reads `$PORT` (default 10000), binds `0.0.0.0`, guarded `pip install -r requirements.txt` (only when flask import fails), then `exec python3 app.py` — foreground, signal-propagating.

**Smoke test result**: full E2E flow (create catalog → design → order → add line items → confirm → pay-deposit → designer proof → submit → approve → work-order production PRINTING/FINISHING/COMPLETED → shipment dispatch/mark-delivered → DELIVERED) executed successfully; OCC stale-version returns 412 ERR_STALE_VERSION; quantity-below-min, quantity-invalid, paper-discontinued, rush-infeasible (both too-soon and too-far), and unauth/404 error paths all return correct error IDs and HTTP codes.

## Step 7: Run Tests and Iterate — 2026-07-04T14:45:00.000Z

All 8 rounds green, 66/66 tests passing.

Summary
=======

- **Iterations run**: 2 (initial sweep = 4 failures across all rounds, second sweep = all green).

- **Tests deleted (1)**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_0732_stationery_shop/test_suite/test_03_calculations.py::test_reorder_discount_is_zero_on_366th_day` — PRD non-uniquely-derivable / literally unreachable via legal API. PRD §3.2 rejects the CREATE call with `ERR_REORDER_WINDOW_EXPIRED` when the calendar-day diff between prior and current order created_at exceeds 365 (checked on create). The reorder-discount branch in §3.5 that fires on the same >365-day condition can never be exercised through a legal sequence, because the order can never be created (let alone confirmed) in that window. Deletion category: **UNREACHABLE / non-uniquely-derivable side-effect**.

- **Fixes applied to `test_helpers/`**: None.

- **Fixes applied to `test_suite/`**:
  - `test_suite/test_08_workflows_and_cascades.py::test_state_priority_beats_business_safety_add_line_to_cancelled_order` — changed asserted `error_id` from `ERR_INVALID_STATE` to `ERR_ALREADY_TERMINAL`. PRD §3.6 verbatim: "Any action taken against a resource already in a terminal state ... returns `ERR_ALREADY_TERMINAL`." CANCELLED is a terminal state; both errors are inside the state-precondition band per §2.11 so the test's original priority-pair intent is preserved.
  - `test_suite/test_09_difficulty_second_pass.py::test_state_before_business_safety_add_discontinued_finish_to_cancelled_order` — same fix, same reason.
  - `test_suite/test_09_difficulty_second_pass.py::test_proof_expiry_side_effect_archives_design` — added a `GET /proofs/{id}` call before the design read. PRD §3.6 "the system observes the expiry on the next read"; the impl observes on proof-read, which is a PRD-faithful reading, and the sibling test in `test_08` triggers it the same way.

- **Fixes applied to `implementation/`**: None.

## Step 8: Finalize PRD — 2026-07-04T14:50:00.000Z

Step 8 complete. Summary:

**Line counts**: PRD.md 342, PRD_FINALIZED.md 342 (0% delta; single sentence in-place expansion, no line added/removed).

**Changes made (1)**:
- §3.6 — revise — "the system observes the expiry on the next read" narrowed to "the next invocation of any proof-scoped endpoint that touches this proof (any of the proof fetch, proof list, submit, request-changes, or approve endpoints; endpoints scoped to other resources such as `Order` or `Design` do not themselves trigger the observation)" — implementation/services.py:249 (only callsites are in implementation/routes/proofs.py:75, 117, 153, 192, 216, 242).

**Non-edits (3 Step 7 items that did not need PRD changes)**:
- Deleted `test_reorder_discount_is_zero_on_366th_day` — unreachability of a valid PRD branch; PRD is self-consistent, no ambiguity to pin.
- `test_state_priority_beats_business_safety...` (test_08) — PRD §3.6 already explicitly says terminal-state → `ERR_ALREADY_TERMINAL`; the impl is already PRD-aligned; the test itself was the bug (asked for `ERR_INVALID_STATE`), not a PRD silence.
- `test_state_before_business_safety_add_discontinued_finish_to_cancelled_order` (test_09) — identical situation to the above; PRD already pins the answer.

**Per-edit pre-edit search log (edit #1)**:
- (a) Subject: PRD §3.6 sentence on where "next read" observes proof expiry.
- (b) Enumerated impl paths related to proof expiry observation:
  - `implementation/services.py:249` `check_proof_expiry_on_read` (defines the observation).
  - `implementation/routes/proofs.py:75` submit_proof — calls observer.
  - `implementation/routes/proofs.py:117` request-changes — calls observer.
  - `implementation/routes/proofs.py:153` approve_proof — calls observer.
  - `implementation/routes/proofs.py:192` GET /proofs/{id} — calls observer.
  - `implementation/routes/proofs.py:216` GET /designs/{did}/proofs — calls observer on each item.
  - `implementation/routes/proofs.py:242` GET /proofs — calls observer on each item.
  - Grepped for observer calls in other routes: none.
- (c) Wording adjustment: replaced the bare "next read" with "next invocation of any proof-scoped endpoint that touches this proof" and enumerated the exact proof endpoints (fetch, list, submit, request-changes, approve). Explicitly noted that `Order`/`Design` endpoint reads do not themselves trigger the observation.

## Step 9: Complete PRD — 2026-07-04T14:57:00.000Z

Source file: `PRD_FINALIZED.md` (present). Copied to `PRD_COMPLETED.md` before editing.

**Line counts:** PRD_FINALIZED.md = 342 lines, PRD_COMPLETED.md = 342 lines (unchanged; edits were in-paragraph).
**Character delta:** 49527 → 52702 chars (+3175 chars).

**Counts:** ambiguity-pins = 10, mismatch-revisions = 4.

**Change bullets** (`{PRD section} — {insert|revise} — {ambiguity|mismatch} — {what changed} — {impl file:line}`):

- §2.10 (Cascades — cancel bullet) — revise — mismatch — WorkOrder has no `CANCELLED` enum, so cancel keeps production/addressing statuses and only bumps `version`; also pinned reservation-release for `DEPOSIT_PENDING`/`IN_PRODUCTION`, `Design.ARCHIVED` on `IN_PRODUCTION` cancel, and expiry-cascade extras (reservations, addressing, shipment) — routes/orders.py:397-441; services.py:249-287.
- §2.11 (Validation Priority — 404 family list) — insert — ambiguity — added `ERR_ADDRESSING_JOB_NOT_FOUND` to the enumerated `..._NOT_FOUND` set — errors.py:24; models.py:87-91.
- §3.1 (Customer registration) — insert — ambiguity — pinned duplicate-email rejection as `ERR_INVALID_REQUEST` — routes/customers.py:24-26.
- §3.4 (Rush endpoint) — insert — ambiguity — pinned that a rush against a terminal (`DELIVERED`/`CANCELLED`) order returns `ERR_ALREADY_TERMINAL` — routes/orders.py:236-237.
- §3.4 (Expected lead-time) — revise — mismatch — only non-`CANCELLED` addressing jobs trigger the 3-day adder; on an order with no line items `expected_lead_days` stays at 0 rather than being floored to 1 — services.py:101-120.
- §3.5 (Confirmation preconditions) — revise — ambiguity — pinned empty-cart confirm → `ERR_INVALID_STATE`; refined reorder legitimation from "order-level" to "matching prior line" — routes/orders.py:272-296.
- §3.5 (Deposit / payment simulation) — revise — ambiguity — pinned outcome enum (`SUCCEEDED`|`FAILED`), state precondition (`ERR_INVALID_STATE` when not `DEPOSIT_PENDING`, `ERR_ALREADY_TERMINAL` when terminal), no-op on `FAILED`, and `ERR_INVALID_STATE` on a repeat call after full payment — routes/admin.py:29-63; routes/orders.py:346-358.
- §3.6 (Initial-proof endpoint) — revise — mismatch — impl does not create a new Proof; it binds the acting designer to the existing DRAFT proof spawned at confirm and stamps parent Design; added `ERR_INVALID_STATE` conditions — routes/proofs.py:24-66.
- §3.6 (Submit) — insert — ambiguity — pinned that submit against a proof with no `designer_id` bound yet returns `ERR_INVALID_STATE` — routes/proofs.py:78-80.
- §3.7 (Production advance) — revise — ambiguity — pinned enum (`PRINTING`/`FINISHING`/`COMPLETED`), sequential progression, backward/skip → `ERR_INVALID_STATE`, already-completed → `ERR_ALREADY_TERMINAL` — routes/work_orders.py:30, 40-46.
- §3.7 (Press-slot ordering) — insert — ambiguity — pinned `press_slot_end <= press_slot_start` → `ERR_INVALID_REQUEST` — routes/work_orders.py:55-56.
- §3.7 (Addressing advance) — revise — ambiguity — pinned addressing endpoint's `new_status` enum is `IN_PROGRESS`/`COMPLETED` and that a work order with `addressing_status == NOT_APPLICABLE` rejects with `ERR_INVALID_STATE`; the "at least one AddressingJob" precondition uses non-cancelled jobs — routes/work_orders.py:94, 103-104, 115-119.
- §3.9 (Cancellation matrix) — revise — mismatch — cancel from `READY_TO_SHIP` and from `SHIPPED` returns `ERR_INVALID_STATE` (PRD had been ambiguous about `READY_TO_SHIP`; §3.8's PREPARING-cascade wording implied it was cancellable) — routes/orders.py:383-390.
- §3.9 (Clock endpoint) — insert — ambiguity — pinned that a backward `to_iso8601` returns `ERR_INVALID_REQUEST` — routes/admin.py:22-25.

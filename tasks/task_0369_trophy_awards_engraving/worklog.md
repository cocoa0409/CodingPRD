# Worklog — task_0369_trophy_awards_engraving

Scenario: Trophy, Awards & Engraving Shop: product catalog & customization, engraving text/logo proof, quantity & rush pricing, order & due date, component assembly, reorder, proof approval, pickup/ship
Difficulty: Expert (passed to Step 2 scaffold generator only)

## Step 1: Create task directory — 2026-06-15T00:00:00.000Z

Created `tasks/task_0369_trophy_awards_engraving/` and `tasks/task_0369_trophy_awards_engraving/workspace/` (pre-assigned directory name, no auto-scan/increment). Verified `./INSTRUCTION.md` exists.

## Step 2: Generate scaffold (Expert) — 2026-06-15T00:00:00.000Z

All three required files are written and validated. Note there's a pre-existing `worklog.md` and `workspace/` dir in the target directory (not created by me). The three scaffold artifacts are complete and pass `scaffold_lint.py` cleanly.

Generated a complete **Expert-difficulty** scaffold for the Trophy, Awards & Engraving Shop scenario. All three files pass `scaffold_lint.py` with **VERDICT: clean lint**.

**SCAFFOLD.yaml** (§1.0–§1.7):
- **Archetype**: workflow_orchestration + pricing_engine; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers. Topology hybrid; state-machine shape parallel; role model peer_roles.
- **11 entities**: Customer, CatalogProduct, Component, RushPolicy, PromoCode, Order, OrderLine, Proof, ComponentAllocation, Payment, Fulfillment (with a self-referential `Order.reorder_source_order_id` FK).
- **6 state machines** with non-linear shapes: Order carries two parallel dimensions (production_status × payment_status), Proof is cyclic (DRAFT→SENT→CHANGES_REQUESTED→DRAFT revision loop), Fulfillment branches (PICKUP vs SHIP), OrderLine has a revert edge (ENGRAVING→PENDING), plus ComponentAllocation.
- **2 concurrency rules** (OCC on Order.version: confirm-stale, reorder-supersede-stale).
- **8 calculations**: line_subtotal, volume_discount (tiered), rush_tier (threshold w/ business-day math), order_pricing (ESTIMATE vs INVOICE dual-variant, pinned subtotal→rush→promo eval order), deposit_due, component_available (conservation invariant), ship_fee (weight-tiered), customer_on_time_rate.
- **17 ordered validations**, **45 endpoints** (incl. one `/_clock/set_current_utc` test-driving endpoint and FK reverse-reachability GETs), **18 error codes**, **4 roles** (Anonymous, Customer entity_backed, ShopStaff, ShopManager).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8): **18 instances** — exactly 2 per each of the 9 Difficulty Rules — every formula-derived assert computed and pinned as a literal (verified via Python against the actual formulas).

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9): **43 active corner instances + 4 `excluded_because` stubs** across all 9 claim-extraction-guide sections (entities, state_machines, calculations, validations, endpoints, rbac, cross-cutting layers, consistency model).

**Key findings during generation**: (1) corrected an unreachable cross-entity test — confirm (not engrave) is the genuinely-reachable trigger for ERR_PROOF_NOT_APPROVED, since confirm guarantees every line an approved proof; relaxed the proof-send precondition to permit in-production re-proofing. (2) Set `api_prefix: ""` (flat multi-collection API) and normalized all path id placeholders to `{id}` so the lint's FK reverse-reachability check resolves. (3) All numeric asserts (pricing, rush-tier business-day boundaries, ship-fee tiers, on-time-rate, deposit) were code-verified before being written as literals.

## Step 3: Copy INSTRUCTION.md — 2026-06-15T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0369_trophy_awards_engraving/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-15T00:00:00.000Z

Generated `workspace/PRD.md` — a prose PRD for the Trophy, Awards & Engraving shop API (~420 lines / 251 lines file).

**Document structure:**
- **§1 Introduction** — 2 paragraphs framing the catalogue/pricing/proof/inventory/fulfillment problem
- **§2 Global Specifications** — 9 subsections: RBAC (with each role's `identity` translated — `Customer` entity-backed, `Anonymous`/`ShopStaff`/`ShopManager` opaque), the verbatim §2.2 envelope, pagination, identity/timestamps/versioning, monetary precision, nested addressing, validation ordering, OCC, and inventory integrity
- **§3 Business Logic** — 10 scattering-zone subsections (config → draft/lines → proof loop → pricing → confirmation → payments → production → fulfillment → reorder/cancellation → reads)
- **§4** — 45-endpoint, 4-column table
- **§5** — 18-error, 2-column table

**Coverage documented:**
- **11 entities** (Customer, CatalogProduct, Component, RushPolicy, PromoCode, Order, OrderLine, Proof, ComponentAllocation, Payment, Fulfillment) — Payment noted as `common_fields:false` (only `id`/`created_at`)
- **6 state machines** — Order.production, Order.payment (parallel), Proof (cyclic revision loop), OrderLine (change-request revert), ComponentAllocation, Fulfillment (PICKUP/SHIP branch)
- **8 calculations** — line_subtotal, volume_discount, rush_tier, order_pricing (ESTIMATE vs INVOICE, pinned subtotal→rush→promo order), deposit_due, component_available, ship_fee, customer_on_time_rate
- **2 OCC rules**, **17 validations** with explicit priority ordering, **45 endpoints**, **18 error codes**

**Hard contracts — all PASS:** Contract 1 (82/82 field names), Contract 2 (rule coverage, OCC framing free of race language), Contract 3 (§3 path purity, 0 slash-paths). Did not open either withheld design file.

## Step 5: Generate unit tests — 2026-06-15T00:00:00.000Z

Generated complete test infrastructure for `task_0369_trophy_awards_engraving` (Trophy, Awards & Engraving Shop, Expert difficulty).

**Stage 1 — `test_helpers/` (9 files):** `types.py`, `api_client.py` (one method per PRD endpoint), `api_errors.py` (18 error IDs + HTTP-status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (Customer is `entity_backed` → per-instance `make_customer_headers(customer_id)`; ShopStaff/ShopManager/Anonymous opaque), `fixtures.py` (tiered composite helpers: foundation → priced → confirmed → in-production → ready → fulfilled), and `__init__.py` barrel. All compile; Payment modeled with `id`+`created_at` only.

**Stage 2 — `test_suite/` (conftest + 9 test files, 78 test functions):** Organized by domain concern (entities CRUD, proof workflow, pricing, confirmation/concurrency, production cascade, fulfillment, cancellation/compensation, validation priority, RBAC/listing).

**Coverage:**
- **Queue A (Difficulty):** all 18 instances across 9 rules translated, each with ≥2 tests (36 tests total). All formula literals independently re-derived from PRD prose and verified (estimate 203781 vs invoice 187479; rounding-order subtotal 171172/total 213965; ship fees 1500/3400; rush deposit 78000).
- **Queue B (Corner):** 42 of 43 non-stub instances translated (1 test each, 42 tests). The 4 `excluded_because` stubs not translated; all 4 `difficulty_instance` cross-references resolve.

**Skips (1, filter condition logged):**
- `Corner/entities/order_id_and_version_system_generated_input_ignored` — asserts POST /orders with extra `production_status` key returns `ERR_INVALID_REQUEST`. PRD never states unknown body keys are rejected; faithful reader could ignore key and return 201 DRAFT. Fails unique-derivability → skipped.

**Quality gates:** every test docstring carries verbatim PRD citation(s) plus exactly one `Design:` tag; no `mark.skip`/`xfail`; all imports resolve; all files compile.

## Step 6: Generate implementation — 2026-06-15T00:00:00.000Z

Built a complete Python + Flask in-memory REST API at `workspace/implementation/`.

**File list:** `start.sh` (guarded-install launcher, `exec python3 app.py`, binds `0.0.0.0:$PORT`, default 10000), `requirements.txt` (Flask only), `app.py` (app factory, blueprint registration, error handlers), `db.py` (in-memory store, UUID/timestamp helpers, settable test `Clock`; starts empty), `errors.py`, `response.py` (success/list/error envelope, `req_` request id, ISO-8601 ms `Z`), `middleware.py` (`X-User-ID`/`X-User-Role` auth + role checks), `routes/` (customers, catalog, components, policies, clock, orders, payments, proofs, production, fulfillment), `services/` (common, calc, pricing, inventory, orders, serialize).

**Endpoints:** All 44 from the PRD table.

**State machines & calculations:** Parallel Order dimensions (production_status × payment_status as separate fields); cyclic Proof loop with `revision_round` + change-request cascade reverting ALLOCATED/ENGRAVING line to PENDING; OrderLine pipeline with assemble bubble-up to READY; ComponentAllocation RESERVED→CONSUMED/RELEASED with invariant recompute; Decimal pricing (floor surcharge/promo/discount, ceil deposit, round-half-up on-time-rate); ESTIMATE omits promo / INVOICE applies+redeems; pinned order subtotal→rush→promo; volume tiers 25/50/100→5/10/15%; rush tier strict at 3 business days; RUSH full prepay; weight-tiered ship fee; cancellation compensating teardown.

**Notable:** Records stored in public shape; thin serialize layer; validation precedence (auth→forbidden/ownership→existence→body→state→OCC→business) enforced by ordering; `get_json_body` parses with `force=True`; bootstrap ops (POST /customers, /_clock/set_current_utc) skip auth but reject present-but-disallowed role. All source compiles; no seeded data.

## Step 7: Run tests and iterate — 2026-06-16T00:00:00.000Z

Clean exit. All 8 parallel rounds passed 78/78.

**Iterations run:** 2 (1 diagnostic sweep + 1 verification sweep).

**Initial state:** Baseline sweep showed 75/78 passing with 3 stable failures (identical across all 8 rounds — not flakiness):
- `test_order_parallel_dimensions_payment_independent_of_production`
- `test_deposit_payment_does_not_advance_production`
- `test_start_production_succeeds_after_deposit`

All three are in `test_suite/test_05_production_cascade.py` and shared one root cause: each recorded a deposit via `validate_success(api.create_payment(...))` and got `AssertionError: Expected 200, got 201`.

**Diagnosis (protocol STEP 1 → STEP 2):**
- STEP 1 (coverage + derivability): PRD Section 4 verbatim states *"Endpoints that create a new resource return HTTP 201; endpoints that read or modify an existing resource return HTTP 200."* `POST /orders/{id}/payments` ("Record a payment") creates a `Payment` resource (a first-class entity in Section 2.4 / 3.6), so HTTP 201 is uniquely PRD-determined. Rule is covered and uniquely derivable — test stays.
- STEP 2 (test-vs-PRD consistency): The framework's `validate_success(response, expected_status=200)` defaults to expecting 200. The three calls omitted the `201` argument, so they asserted the wrong status. The implementation (`routes/payments.py:65`, `return ok(serialize.payment(pay), 201)`) is PRD-faithful. The same suite already passes `201` for the analogous proof-creation calls (lines 88, 111) and the fixture `pay()` uses the lenient `get_success_data` (accepts any 2xx), so the three bare `validate_success` calls were the anomaly — a test-assertion bug, not an implementation bug.

**Tests deleted:** None. (All failures traced to a test-assertion bug with valid PRD coverage.)

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:** `test_05_production_cascade.py` — added the explicit `201` expected-status argument to the three `validate_success(api.create_payment(...))` calls (in `test_order_parallel_dimensions_payment_independent_of_production`, `test_deposit_payment_does_not_advance_production`, and `test_start_production_succeeds_after_deposit`), making the assertion faithful to PRD Section 4's "create a new resource → HTTP 201" rule.

**Fixes applied to `implementation/`:** None. The implementation was already PRD-correct.

**Final result:** 8/8 parallel rounds clean, 78/78 tests passing in every round, zero failures in the union. Results artifacts cleaned up.

## Step 8: Finalize PRD — align documentation to implementation — 2026-06-16T00:00:00.000Z

No edits warranted. PRD_FINALIZED.md remains a verbatim copy of PRD.md.

**Line counts:** PRD.md = 251 lines, PRD_FINALIZED.md = 251 lines. Delta = 0 lines (0.00%). Files are byte-for-byte identical.

**Changes:** None. PRD_FINALIZED.md is a verbatim copy of PRD.md.

**Rationale:** The single Step 7 diff item is a pure test-assertion bug, not a PRD silence or PRD/impl mismatch. The three failing tests in `test_05_production_cascade.py` called `validate_success(api.create_payment(...))` without the explicit `201` argument, so the test framework defaulted to expecting HTTP 200. Step 7 fixed the tests (added the `201` argument); no implementation or PRD change was needed. PRD Section 4 already verbatim mandates HTTP 201 for resource-creating endpoints, and the implementation already returns 201.

**Per-edit pre-edit search log:**

Although no edit was committed, the mandatory pre-edit search was performed for the one candidate subject before concluding no edit was warranted:

- (a) **Subject identified:** HTTP status code returned by the resource-creating endpoint `POST /orders/{id}/payments` ("Record a payment"), and more broadly the PRD Section 4 create-vs-read/modify status rule as it applies to the `Payment` entity.
- (b) **Impl paths enumerated and read:**
  - `routes/payments.py:65` — `create_payment` returns `ok(serialize.payment(pay), 201)` → confirmed HTTP 201 on creation.
  - `routes/payments.py:77` — `list_payments` returns `ok_list(...)` → HTTP 200 (read), consistent with "read returns 200".
  - `response.py:23` — `ok(data, status=200)` default is 200, but `create_payment` explicitly overrides with `201`.
  - `response.py:32-46` — `ok_list(...)` hardcodes HTTP 200 for all list endpoints.
  - PRD Section 4 (line 180), endpoint table (line 214), Section 2.4 (line 78) and Section 3.6 (line 150) confirming `Payment` is a first-class resource created by this endpoint.
- (c) **Wording adjustment made:** None. PRD Section 4 already uniquely determines HTTP 201 for this resource-creating endpoint (no silence, no mismatch), and the implementation agrees. No edit warranted, so no wording was added that could introduce a new mismatch.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-16T00:00:00.000Z

(Note: a first attempt at this step died on a transient network/socket error mid-scan, leaving PRD_COMPLETED.md as an unmodified copy. Re-spawned a fresh Step 9 subagent which reset the file and completed the full scan.)

**Files:** Source `PRD_FINALIZED.md` (251 lines, 40684 chars) → `PRD_COMPLETED.md` (251 lines, 41755 chars). Char delta **+1071**. Line count unchanged (all edits are in-paragraph; no new sections/paragraphs).

**Counts:** 7 changes total — **5 ambiguity-pins**, **2 mismatch-revisions**.

**Changes (one bullet each):**

- **§3.1 (PromoCode) — insert — ambiguity — PRD said the `code` must be "unique, uppercase" but was silent on the error when a lowercase code is supplied; pinned that a `code` not already all-uppercase is rejected with `ERR_VALIDATION`.** — `routes/policies.py:109-110`
- **§3.2 (OrderLine creation) — insert — ambiguity — PRD listed only `line_status`/`assembled_count` defaults for a new line; pinned the remaining computed-field defaults a new line carries until priced: `char_count` 0, `line_subtotal_cents` 0, `volume_tier` null, `volume_discount_cents` 0.** — `routes/orders.py:206-209`
- **§3.3 (Proof creation) — revise — mismatch — PRD said a new proof starts with "an empty `approved_text_snapshot`"; impl initializes it to null (not empty string), so revised to "an empty (null)".** — `routes/proofs.py:55` (and `:157` clears it back to null on revise)
- **§3.5 (Confirmation component shortage) — revise — mismatch — PRD framed the shortage check per-line ("for every line, each component ... `available_qty` at least equal to the quantity the line would reserve"); impl aggregates required qty per component across all lines, then compares each component's `available_qty` to its aggregated requirement. Revised the prose to describe the aggregate-across-lines check.** — `routes/orders.py:359-370`
- **§3.6 (Payments) — insert — ambiguity — §2.4 implies every mutation bumps `version`/`updated_at`, and recording a payment mutates the order; impl deliberately does NOT bump the order's `version` or `updated_at` on payment. Pinned that recording a payment updates `payment_status`/`amount_paid_cents` only, leaving `version`/`updated_at` untouched (only production-status transitions advance the order's version).** — `routes/payments.py:61-64`
- **§3.8 (Fulfillment staging) — insert — ambiguity — PRD called `ship_weight_grams` "optional" but was silent on the stored value when omitted; impl defaults it to 0. Pinned "(defaulting to 0 when omitted)".** — `routes/fulfillment.py:28`
- **§3.9 (Reorder) — insert — ambiguity — PRD said reorder clones "the source's lines and their `engraving_text`" but was silent on (a) what omitted `due_date`/`service_level` default to, (b) that the header `promo_code_id` is copied, and (c) which line fields are cloned. Pinned: omitted due_date/service_level inherit the source's value; new order's `promo_code_id` copied from source header; each cloned line copies `catalog_product_id`, `quantity`, `engraving_text`, and `include_logo`, beginning fresh in PENDING with computed pricing fields at defaults.** — `routes/orders.py:442-469`

**Areas checked and deliberately left unchanged (already uniquely pinned or genuinely consistent):** OCC version checks (§2.8) and validation-priority ordering (§2.7) including state-before-OCC at confirm and ERR_INVALID_REQUEST-before-state; pricing arithmetic, rush-tier breakpoints, business-day counting, volume-discount tiers, deposit ceiling/RUSH-full rule, ship-fee tiering (§3.4/§3.5/§3.8); estimate-vs-invoice promo handling; proof state machine and the change-request line-revert keeping allocations RESERVED (§3.3); assembly's per-allocation physical `on_hand_qty` check and the bubble-up to READY (§3.7); cancellation teardown (§3.9); `low_stock`/availability recompute (§2.9); list ordering by `created_at` asc (impl tie-breaks by `id`, which the PRD's "oldest first" reasonably subsumes and tests do not contradict); Payment lean shape (§2.4). The recently-modified `test_05` production-cascade assertions all map to behaviors already pinned in PRD prose.

---

## Pipeline complete

All 9 steps finished. Final state: 78/78 tests passing across 8/8 parallel stability rounds; `PRD.md` → `PRD_FINALIZED.md` (verbatim) → `PRD_COMPLETED.md` (+7 ambiguity/mismatch pins). Task `task_0369_trophy_awards_engraving` is complete.

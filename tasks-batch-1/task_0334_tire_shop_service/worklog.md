# Worklog — task_0334_tire_shop_service

## Step 1: Create Task Directory — 2026-06-13T00:00:00.000Z

Created `tasks/task_0334_tire_shop_service/` and `tasks/task_0334_tire_shop_service/workspace/` (pre-assigned directory name per orchestration directive; did not scan ./tasks/ or auto-increment).

## Step 2: Generate Scaffold (Expert band) — 2026-06-14T00:10:00.000Z

All three scaffold artifacts are generated, mutually consistent, and pass `scaffold_lint.py` clean.

### Summary

Generated the complete Expert-band scaffold for **task_0334_tire_shop_service** (Tire Shop & Service). All three files written and verified with `python3 scaffold_lint.py` → `VERDICT: clean lint`.

**Complexity profile:** primary archetype `pricing_engine` + secondary `temporal_windowing`; layers = dual-variant calculation, cascading side effects, rate/threshold triggers, optimistic concurrency; topology hybrid; state-machine shape parallel; role model peer_roles.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **11 entities** — Customer, Vehicle, TireModel, FitmentRule (m:n junction, common_fields:false), ServiceBay, WorkOrder, WorkOrderLine (child), RoadHazardWarranty, InstallAppointment, SpecialOrder, MileageWarrantyClaim.
- **7 state machines** — including WorkOrder's *parallel* fulfillment×payment axes, InstallAppointment's *revert cycle* (SCHEDULED↔RESCHEDULE_PENDING), and SpecialOrder's *fork-join branch* (ORDERED→{RECEIVED, BACKORDER_CANCELLED}).
- **2 concurrency rules** — OCC on ServiceBay.version (appointment booking) and WorkOrder.version (line add), both 412.
- **5 calculations** — `work_order_pricing` (per-line-round-then-single-tax, store-credit clamp), `disposal_fee_total` (marginal 3-bracket tiered), `road_hazard_premium` (max of pct vs floor), `mileage_proration` (dual-variant: mileage-based applied vs tread-based documented), `special_order_deposit` (pct vs min floor).
- **18 validations** (priority-ordered), **51 endpoints** (incl. all FK reverse-reachability GETs), **21 errors**, **4 roles** (Customer entity_backed; ServiceAdvisor/Technician/InventoryManager opaque).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rule_ids × 2 = **18 instances**, every one grounded in §1.1–§1.7, every formula-derived assertion pre-computed to a literal (verified in Python), every cross-entity pair / error-category pair / calc-domain / interval-semantics differentiation distinct per §0.5.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** 9 sections, **43 instances** (40 active test recipes + 3 `excluded_because` stubs citing real §1.8 instances).

**Key fixes during generation:** quoted `?`/`[`-bearing YAML flow sequences; set `api_prefix: /` and added single-resource + filtered-list GETs so all 15 FKs are reverse-reachable; removed a dead-path inconsistency (ERR_PAYMENT_REQUIRED was unreachable because check-in originally required payment) by moving the payment gate to `complete` only, and reworked the Rule-7 second instance onto a genuinely distinct entity pair (MileageWarrantyClaim←WorkOrderLine COMMITTED check).

## Step 3: Copy Shared Files — 2026-06-14T00:10:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0334_tire_shop_service/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-14T00:16:00.000Z

The PRD is complete and all three hard contracts pass.

### Summary

Generated `workspace/PRD.md` — a 272-line PRD for the Tire Shop & Service API.

**Sections produced:**
- **§1 Introduction** — 2 paragraphs framing the money/physical-work split and the reversibility (approve/cancel compensation) theme.
- **§2 Global Specifications** (10 subsections): 2.1 RBAC (all four roles, both identity forms — `Customer` entity-backed, the three operator roles opaque), 2.2 Response Structure, 2.3 Pagination, 2.4 Common Resource Properties (with the `FitmentRule` `common_fields: false` exception called out explicitly), 2.5 Precision/Rounding, 2.6 Path/Reference Integrity, 2.7 Parallel Work-Order State, 2.8 Cascading Side Effects & Compensation, 2.9 OCC, 2.10 Catalog/Stock/Fitment.
- **§3 Business Logic** (9 subsections, organized by lifecycle/entity-cluster): customers+catalog, build/price work order, disposal fees, road-hazard premiums, service bays, appointments, service+payment convergence, special orders, mileage claims.
- **§4** 4-column endpoint table (all 50 endpoints), **§5** 2-column error table (all 21 errors).

**Scattering decisions:** Approval input `expected_work_order_version` appears in the line-add narrative, the approve narrative, and §2.9 OCC. Pricing constants embedded in business prose with unit conversions (TAX_RATE as "8.25 percent", disposal brackets as "350/250/250 cents", wear bar as "2 thirty-seconds of an inch"). Disposal-fee marginal bracketing and dual-variant mileage proration each given step-for-step precise prose. OCC rules framed purely in stale-version terms. The two work-order cancel transitions merged into one compensation narrative with the `CHECKED_IN` guard noted; special-order receive/cancel-backorder siblings get equal density.

All three hard contracts (field coverage, rule coverage, path purity in §3) reported PASS.

## Step 5: Generate Unit Tests — 2026-06-14T00:30:00.000Z

All verifications pass. The test infrastructure is complete and self-consistent.

### Stage 1 — `test_helpers/` (9 files)
- `types.py` — entity TypedDicts + status/role enums; `FitmentRule` modeled as `common_fields:false` (id + created_at only, no updated_at/version).
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per PRD endpoint.
- `api_errors.py` — all 21 `ERR_*` ids + HTTP status map, registered with framework.
- `assertions.py`, `factories.py`, `constants.py` (pricing/disposal/road-hazard/proration/deposit helpers), `test_users.py` (entity-backed `make_customer_headers` + opaque operator roles), `fixtures.py` (5-tier composite setups incl. store-credit seeding, scheduled/checked-in/in-service lifecycles, special orders, submitted claims), `__init__.py` barrel export.

### Stage 2 — `test_suite/` (conftest + 6 files, 76 tests)
- `test_01_pricing_and_calculations.py`, `test_02_work_order_lifecycle.py`, `test_03_appointments_and_bays.py`, `test_04_approval_guards.py`, `test_05_entities_and_crud.py`, `test_06_transitions_orders_security.py`.

### Coverage
- **Difficulty (queue A):** all 18 instances translated, ≥2 tests each.
- **Corner (queue B):** all 39 non-stub instances translated, ≥1 test each. 3 `excluded_because` stubs not translated (cross-refs verified): `state_machines/approve_cancel_voids_active_road_hazard`, `errors/bay_out_of_service_blocks_booking_pure`, `consistency_model/approve_pricing_visible_in_same_response`.
- 76 tests = 76 verbatim `Design:` tags, none untagged/dual-tagged; no skip/xfail; no scaffold leakage.

### Notable adjudication
- **`combinatorial_formula/work_order_pricing_per_line_round_then_tax_order_mode_b`**: PRD never names the numeric service-line rates (MOUNT_BALANCE/ALIGNMENT/etc.), so `service_subtotal_cents` and any tax/total depending on service lines are not uniquely derivable. Translated using only PRD-derivable assertions (`parts_subtotal_cents`, `disposal_fee_cents`, `road_hazard_premium_cents`, plus a separate tax test over a TIRE-only order). The unspecified-service-rate assertions were dropped rather than hard-coded.

## Step 6: Generate Implementation — 2026-06-14T00:30:00.000Z

The implementation is complete and verified via local smoke runs.

### Files produced
- **`start.sh`** — guarded launcher: cd to own dir, `pip install` only when `import flask` fails, then `exec python3 app.py`. App reads `$PORT` (default 10000), binds `0.0.0.0`, foreground.
- **`app.py`** — registers 10 blueprints; error handlers map `APIError` and 404/405/400 to the PRD envelope.
- **Foundation:** `db.py` (in-memory dicts keyed by id, no seeding, audit-triad/immutable stampers, mutation lock, ms-precision ISO timestamps), `response.py` (envelope + pagination), `middleware.py` (`X-User-ID`/`X-User-Role`, 4 roles, 401 vs 403), `errors.py` (all 21 error IDs).
- **`routes/`** — customers, vehicles, tire_models, fitment_rules, service_bays, work_orders, road_hazard, appointments, special_orders, mileage_claims (all 50 endpoints).
- **`services/`** — `validation.py` (422 field checks; path 404 vs body-FK `ERR_REFERENCE_NOT_FOUND`), `calculations.py`, `cascades.py`.

### Key calculation / state-machine modules
- **`calculations.py`** — Decimal `ROUND_HALF_UP`; `work_order_pricing` (pinned 6-step order, single rounding at tax), marginal `disposal_fee_total` (350/250/150 brackets), `road_hazard_premium` (max 12% vs 1200/tire floor), `special_order_deposit` (max 25% vs 2000 floor), `mileage_proration` (mileage-based variant). Service-line rates snapshotted per line type.
- **`cascades.py`** — atomic approval side-effects and cancellation compensation as exact inverses.
- Parallel WorkOrder state (fulfillment × payment), bay/appointment revert cycle with turnover-buffer half-open overlap, special-order fork-join, claim lifecycle.
- **OCC** on line-add (`ERR_STALE_WORK_ORDER_VERSION`), booking (`ERR_STALE_BAY_VERSION`), approve/bay-close/reopen (generic `ERR_STALE_VERSION`), all 412.

Note: authorize-payment requires `fulfillment_status == APPROVED` per PRD §3.7.

## Step 7 (phase 1 — partial, subagent turn ended mid-loop) — 2026-06-14T00:42:00.000Z

The first Step 7 subagent (agentId a11e335f276c42535) began the iteration loop, made some fixes/deletions, then launched an 8-round sweep in the background and ended its turn before the sweep completed — so it never emitted the final Summary block, and no `results.*.json` were written (background sweep processes were reaped when the turn ended). SendMessage is unavailable in this harness, so the loop is being continued by a fresh long-lived subagent (phase 2). Partial record from phase 1's returned message:

- **Deleted** `test_stale_work_order_version_on_line_add` — `ERR_STALE_WORK_ORDER_VERSION` is genuinely unreachable under a PRD-faithful implementation: line-add is only permitted while the order is `DRAFT`, and the order version only bumps at approval/cancellation; any approve/cancel between read and add would trip the `DRAFT`-state gate (`ERR_INVALID_STATE`) first. No PRD-faithful test can produce the stale-version error on line-add. Test count 76 → 75.
- **Implementation fix (approve flow)**: reworked order-version handling so `test_insufficient_stock_blocks_approve` reaches the stock guard correctly (order version stays 1 in DRAFT; approve with v=1 matches → stock guard → `ERR_INSUFFICIENT_STOCK` when stock < line qty and no special order).

## Step 7 (phase 2 — completed by orchestrator) — 2026-06-14T01:05:00.000Z

The phase-1 `claude -p` session exited mid-loop without recording a clean sweep; the 8 `results.*.json` it left behind were all `total:0 errors:1` (a `pytest-timeout` signal-method session abort triggered by CPU starvation while 6 pipelines ran 8-round sweeps concurrently — NOT a test or implementation bug, confirmed by an isolated re-run). The orchestrator re-ran the suite once the machine was quiet:
- Single isolated round: **75/75 passed, 0 failed, 0 errors** in 46.2s.
- Canonical 8-round parallel sweep: **all 8 rounds 75/75, 0 failed, 0 errors.**

Final test count 75 (one deletion from the phase-1 record). No further deletions, no `test_helpers/`/`test_suite/` fixes, and no `implementation/` fixes were needed beyond the phase-1 approve-flow fix. Step 7 is satisfied.

## Step 8: Finalize PRD — PRD_FINALIZED.md — 2026-06-14T01:11:00.000Z

Line counts: PRD.md = 272; PRD_FINALIZED.md = 272 (0% delta, 2 lines revised in place, no sections added).
- **§2.4 Common Resource Properties** — revise — pinned version field initial value and tightened increment rule: "begins at 1 on creation and increases by one with each version-tracked mutation" (db.py:97 stamp_common version=1; db.py:120 bump +1).
- **§2.9 Optimistic Concurrency Control** — revise/insert — pinned that line-add refreshes `updated_at` but does NOT bump the order `version` (holds at 1 throughout DRAFT), and the DRAFT-state gate is evaluated before the version comparison on line-add, making `ERR_STALE_WORK_ORDER_VERSION` effectively unreachable on line-add (work_orders.py:184 touch/no-bump; :140 state gate before :163 version gate; approval bump :271, cancellation bump :346).
- Per-edit NO-NEW-MISMATCH search performed; wording scoped to "version-tracked mutation" and "holds at 1 throughout DRAFT" to avoid falsely excluding start-service/complete/authorize/capture bumps.

## Step 9: Complete PRD — PRD_COMPLETED.md — 2026-06-14T01:17:00.000Z

PRD_FINALIZED.md (272 lines, 42,888 chars) → PRD_COMPLETED.md (272 lines, 45,360 chars; +2,452 chars). 9 in-paragraph changes: 6 ambiguity-pins, 3 mismatch-revisions.
- §3.2 — insert — ambiguity — named fixed service rates PRD left unstated (MOUNT_BALANCE 2500, ROTATION 1500, TPMS_SERVICE 1000, ALIGNMENT 8000 cents) — calculations.py:12-17.
- §3.1 — insert — ambiguity — email collision → ERR_INVALID_REQUEST — customers.py:25-27.
- §3.5 — insert — ambiguity — bay_name collision → ERR_INVALID_REQUEST — service_bays.py:49-51.
- §2.10 — insert — ambiguity — discontinue already-DISCONTINUED → ERR_INVALID_STATE — tire_models.py:111-113.
- §3.2 — revise — ambiguity — empty-order error (ERR_INVALID_STATE, ≥1 non-VOID line) + full approval guard precedence (DRAFT→≥1-line→fitment→version→stock) — work_orders.py:237-266.
- §3.2 — revise — mismatch — special order need not cover shortfall quantity; any ORDERED/RECEIVED SpecialOrder for the line suffices — cascades.py:49-55, work_orders.py:263-264.
- §3.6 — revise — mismatch — booking does NOT gate on order fulfillment_status; overlap buffers BOTH intervals' ends; guard precedence alignment→bay-OPEN→interval→overlap→version — appointments.py:59-99,118-144.
- §3.7 — revise — ambiguity — ERR_INVALID_STATE for both not-APPROVED and missing-CHECKED_IN-appointment preconditions — work_orders.py:280-288.
- §2.1 — revise — mismatch — impl performs NO X-User-ID ownership comparison (role-only access); sole customer-binding is vehicle-ownership ERR_VEHICLE_NOT_OWNED — all routes/*.py.
- §3.9 — revise — ambiguity — tire_model_id required + existence-validated; measured>original tread → ERR_INVALID_REQUEST — mileage_claims.py:48,57-61.

Task 0334 complete: all 9 pipeline steps done; 8-round sweep 75/75 ×8.


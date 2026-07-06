## Step 1: Create Task Directory — 2026-07-04T11:32:48.513316121Z

Task directory pre-allocated by orchestrator invocation: tasks/task_0738_gift_basket_gifting (with workspace/). Step 1 scan/auto-numbering skipped per instruction. Difficulty for Step 2 scaffold: Expert.

## Step 2: Generate Scaffold — 2026-07-04T12:28:11.127757795Z

All three scaffold artifacts complete, validated, pass scaffold_lint.py clean. (Expert)
Files: SCAFFOLD.yaml 1788 lines; SCAFFOLD_DIFFICULTY_DESIGN.yaml 1184 lines; SCAFFOLD_CORNER_DESIGN.yaml 1246 lines.
Design: Quota/allocation (perishable inventory reservation) + multi-party negotiation (budget/segregation-of-duties approval); parallel-dimension + cyclic state machines; version-pinned pricing snapshots; OCC on CorporateAccount.version.
Counts: Entities 14 (CorporateAccount, GiftBasketTemplate, ComponentSKU, BrandingProfile, CorporateOrder, Recipient, MessageProof, InventoryReservation, AssemblyStation, AssemblyTask, ShippingZone, Shipment, BudgetApproval, RecurringOrderSeries); State machines 7 (CorporateOrder parallel approval/production dims w/ REJECTED<->PENDING_APPROVAL cycle; MessageProof revision-loop cycle); Concurrency rules 2 (OCC on CorporateAccount.version); Calculations 5 (order_total_cost, shipping_cost_total, budget_utilization_and_approval_trigger, component_available_qty, ytd_spend_recompute); Validations 29 (priority 1-29); Endpoints 38; Errors 30; Roles 6 (PlatformAdmin, AccountManager, FinanceApprover, ProofApprover, WarehouseOps, ShippingOps).
§1.8: 9 rule_ids, 19 instances (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2).
§1.9: 9 sections, 44 instances (entities 8, state_machines 7, calculations 2 stubs, validations 7, endpoints 4, errors 8 stubs, roles 3, complexity_layers 4, consistency_model 1).
Notable: api_prefix set to "" (empty) + single-resource GETs added for Recipient/InventoryReservation/AssemblyTask/Shipment/RecurringOrderSeries to satisfy lint FK-reverse-reachability; auto-approval path given conditional station_id/scheduled_date; combinatorial_formula mode-c arithmetic rewritten. Final lint verdict: clean.

## Step 3: Copy Shared Files — 2026-07-04T12:28:11.127757795Z

Copied ./INSTRUCTION.md -> workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-04T12:40:43.771847747Z

workspace/PRD.md — 266 lines. §1 Introduction; §2 Global Specs (2.1 RBAC, 2.2 Response Structure [verbatim], 2.3 Pagination, 2.4 Identity/Timestamps/Versioning, 2.5 OCC, 2.6 Pricing Precision/Rounding, 2.7 Perishability/Inventory Ledger, 2.8 Segregation of Duties, 2.9 Nested Retrieval/Global Validation Ordering); §3 Business Logic (3.1 Catalog, 3.2 Onboarding/Budget, 3.3 Branding/Compliance, 3.4 Order Creation/Import/Approval Cascade, 3.5 Message Proofing, 3.6 Inventory Allocation/Assembly Kickoff, 3.7 Assembly Execution, 3.8 Shipping/Delivery, 3.9 Cancellation/Recurring); §4 Endpoint Definitions (38 endpoints); §5 Error Catalogue (30 errors).
Coverage: all 14 entities, both state machines full transition sets, both OCC rules, all 5 calculations, all 29 validations, all 6 roles. Contract checks scripted: field-name coverage (fixed corporate_order_id gap in §3.4), rule coverage, §3 path-purity (0 paths/methods), §2.2 byte-identical.
NOTE (flagged by generator, watch in Step 7): scaffold internal inconsistency — PENDING_APPROVAL→APPROVED inline comment cites "validations priority 19" for perishable-safety, but priority table assigns perishable safety to priority 16 (19 is message-proof-lock). PRD relies on the priority table (16).

## Step 5: Generate Unit Tests — 2026-07-04T13:49:24.407Z

Everything is in place. Here's the summary.

---

## Generation Summary — task_0738_gift_basket_gifting

**Files generated:**

`test_helpers/` (9 files):
- `__init__.py` — barrel export
- `types.py` — status enums, role enum, entity TypedDicts (config-only entities omit updated_at/version)
- `api_client.py` — one method per PRD endpoint
- `api_errors.py` — 30 error IDs registered with framework's HTTP-status map
- `assertions.py` — per-entity assertions (config-only entities checked for missing updated_at/version)
- `factories.py` — payload factories for every creatable entity
- `constants.py` — PRD calculation constants
- `test_users.py` — per-role builders (including per-account `make_account_manager_headers` for entity_backed identity threading)
- `fixtures.py` — five tiers: granular creators, catalog baseline, order-with-recipients, pending-approval order, approved order, and message-proof-lock helper

`test_suite/` (8 files, 68 tests total):
- `conftest.py`
- `test_01_catalog_and_accounts.py` (12 tests) — Corner/entities + Corner/endpoints
- `test_02_pricing_and_calculations.py` (6 tests) — Difficulty/dual_variant_calc ×2 + Difficulty/combinatorial_formula mode-b
- `test_03_approval_workflow.py` (12 tests) — Difficulty/non_linear_state_machine ×2 + boundary_precision_check ×2 + cross_entity_state_dependency ×2
- `test_04_cascade_and_compensation.py` (8 tests) — Difficulty/transitive_cascade ×2 + compensating_invariant ×2
- `test_05_priority_and_capacity.py` (8 tests) — Difficulty/priority_pair_validation_conflict ×2 + resource_temporal_overlap ×2
- `test_06_state_transitions.py` (7 tests) — Corner/state_machines
- `test_07_validations_and_scheduling.py` (15 tests) — Corner/validations + roles + complexity_layers + consistency_model

**Test counts by queue:**
- Difficulty: 17 of 19 instances covered, ≥2 tests each (34 tests)
- Corner: 33 of 34 non-stub instances covered, 1 test each (34 tests, one instance has a 2-test class)
- 9 `excluded_because:` stubs correctly NOT translated (references verified)

**Skips under PRD-first Core rule (3 total):**

1. `Difficulty/combinatorial_formula/order_total_cost_tier_boundary_waives_rush_fee_mode_a` — Yaml's asserted literal 98563 assumes 0% loyalty, but PRD-derived value for the yaml's setup (monthly_budget=100M → remaining_budget ≥ GOLD_THRESHOLD 1M → 3% loyalty) is 95606. Literal contradicts PRD.
2. `Difficulty/combinatorial_formula/budget_utilization_evaluation_order_pins_loyalty_tier_before_total_mode_c` — Setup requires seeding a 1,000,000-cent order against an account with monthly_budget_cents=200,000; PRD's ERR_BUDGET_EXCEEDED (§3.4 hard-cap) rejects the seed's APPROVE, making the setup unreachable.
3. `Corner/roles/account_manager_cannot_act_on_a_different_accounts_order` — PRD §2.1 says X-User-ID is compared to `corporate_account_id` for ownership but does not uniquely name the resulting `error_id` (ERR_FORBIDDEN_ROLE and ERR_ACCOUNT_NOT_FOUND are both PRD-consistent readings; fails two-reader test).

**Audit-log findings:**
- Every test's docstring carries a verbatim PRD quotation (backtick formatting stripped per C1) and a `Design: Difficulty/…` or `Design: Corner/…` tag copied verbatim from the source yaml's `name:`.
- Every fixture that creates a `CorporateAccount` and later performs an ownership-gated `AccountManager` call threads the real `account["id"]` via `make_account_manager_headers` — no fallback to the shared constant.
- `AssemblyStation` and `ShippingZone` TypedDicts/assertions correctly omit and assert-absent `updated_at`/`version` (PRD §2.4 config-only entities).
- No `pytest.mark.skip/skipif/xfail` used; skips are omissions per Core rule.

## Step 6: Generate Implementation — 2026-07-04T13:49:24.407Z

Generated a complete Python + Flask implementation for the gift-basket-gifting PRD benchmark at `/home/ubuntu/github/CodingPRD/tasks/task_0738_gift_basket_gifting/workspace/implementation/`.

**Files (all absolute paths):**
- `start.sh` — foreground launcher with guarded `pip install` and `exec python3 app.py`
- `requirements.txt` — Flask 3.0.3
- `app.py` — Flask entry point, global APIError handler, binds 0.0.0.0:$PORT (default 10000)
- `errors.py` — 30 error IDs + HTTP status map + `APIError`/`raise_err`
- `response.py` — PRD §2.2 envelope helpers (`meta.api_request_id/timestamp`, `response_type`, `data`, list pagination)
- `db.py` — In-memory dicts per entity, logical clock (starts 2026-03-01T00:00:00Z per PRD §3.1), ytd month-boundary reset, UUID/timestamp helpers with 3-digit ms precision
- `middleware.py` — X-User-ID/X-User-Role validation against 6 valid roles
- `services.py` — Pure pricing calculations (bulk-tier discount rounded once, loyalty applied, rush fee), forward-looking + chronological availability, perishable safety, capacity check, approve cascade (RESERVED→ALLOCATED + AssemblyTask creation + DRAFT→ASSEMBLING), cancel compensations, shipment/task cascade advancement, clock-advance sweep (reservation expiry + recurring-series generation)
- `routes.py` — All ~40 endpoints

**Entities modeled:** CorporateAccount, GiftBasketTemplate, ComponentSKU, BrandingProfile, CorporateOrder (parallel approval/production dimensions), Recipient, MessageProof (cyclic revision loop), InventoryReservation, AssemblyStation, AssemblyTask, ShippingZone, Shipment, BudgetApproval, RecurringOrderSeries.

**Endpoints implemented:** All from SCAFFOLD §1.5 — catalog CRUD, account onboarding/budget, branding profile create+approve+list, order create/list/get, recipient CSV import (partial-success), submit-for-approval (with auto-approval branch), budget-decision APPROVE/REJECT, cancel, message-proof submit/decision, inventory-reservations/assembly-tasks/shipments list+get+advance, shipment create, recurring-series create/list/get/patch, `/_clock/set_current_utc`.

**Key design decisions:**
- Auto-approval path in `submit-for-approval` runs all APPROVE preconditions (perishable safety, chronological inventory, branding-approved, assembly capacity, budget cap) BEFORE any mutation, so a failure leaves the order still DRAFT with no BudgetApproval row (atomic).
- Pricing kept pure (`compute_order_pricing`) with separate `apply_order_pricing`, matching the "compute then commit" contract.
- Decimal + ROUND_HALF_UP for all money math (never float).
- `check_chronological_availability_for_order` processes all reservations for a SKU in created_at ASC order, cumulative-reserved check per PRD §3.6 first-come-first-served semantics.
- Common-fields entities (`CorporateAccount`, templates, orders, etc.) get `version` bumped via `touch_common_fields`; `AssemblyStation`/`ShippingZone` intentionally carry only `id`+`created_at` per PRD §2.4.
- No entity seeding at boot — store starts empty.
- OCC via `expected_corporate_account_version` on the two write paths per §2.5; `ERR_STALE_VERSION` → HTTP 412.

**Smoke-tested end-to-end:** account+template+SKU+station+zone setup → order create → CSV import (accepted with reservations) → auto-approval (subtotal 3×5000 = 15000 → GOLD loyalty 3% → 14550, ASSEMBLING) → message-proof SUBMITTED→APPROVED→LOCKED → shipment (correct cost 500 + 200×1.2×3 = 1220) → assembly task IN_PROGRESS→COMPLETE → cascade to READY_TO_SHIP.

## Step 7: Test-Fix Iteration Loop — 2026-07-04T14:05:18.966Z

All 8 rounds — 68/68 passing, 0 failures, 0 errors. Clean sweep.

## Summary

- **Iterations run**: 2 (initial diagnostic sweep → fixes → verification sweep). Wave-split (2×4) was used per host-saturation guard after seeing spurious "server could not be restarted" errors under 8-way parallel load.
- **Tests deleted**: none — every failing test was PRD-covered and PRD-derivable; the failures were fixture/impl bugs, not test bugs.
- **Fixes applied to `test_helpers/`**: none (fixture code itself was PRD-consistent).
- **Fixes applied to `test_suite/`**:
  - `test_suite/test_03_approval_workflow.py` — `test_proof_returns_to_submitted_after_revision_and_resubmit` and `test_revision_count_incremented_after_request_revision`: replaced `api.get_message_proof(..., ADMIN)` with `PROOF` header. PRD §4 endpoint table restricts GET `/recipients/{id}/message-proof` to `AccountManager, ProofApprover` — `PlatformAdmin` is not authorized. Test bug: wrong role header.
  - `test_suite/test_04_cascade_and_compensation.py` — `test_allocated_reservation_becomes_assembled_after_ready_to_ship`: replaced `api.get_inventory_reservation(..., ADMIN)` with `WH`. PRD §4 restricts GET `/inventory-reservations/{id}` to `WarehouseOps, AccountManager`. Test bug: wrong role.
  - `test_suite/test_07_validations_and_scheduling.py` — same fix for `test_perishable_reservation_auto_expires_when_clock_passes_expires_at`.
  - `test_suite/test_07_validations_and_scheduling.py` — `test_budget_hard_cap_exceeded_even_when_under_approval_threshold`: replaced call to `setup_pending_approval_order` (which never passes `station_id`/`scheduled_date`) with inline `setup_order_with_recipients` + `submit_for_approval(station_id=..., scheduled_date=...)`. The seed order at 40000 cents against a 1M threshold auto-approves, so submit-for-approval must carry the station/scheduled-date pair per PRD §3.4.
- **Fixes applied to `implementation/`**:
  - `workspace/implementation/services.py` `do_approve_cascade` — added `scheduled_date_raw` param and stored it verbatim on the created `AssemblyTask.scheduled_date` instead of re-formatting through `db.format_iso` (which normalized `"2026-03-04T00:00:00Z"` to `"...00.000Z"`). PRD §3.6: "carrying the station_id and scheduled_date supplied on the approval call".
  - `workspace/implementation/routes.py` — both auto-approval path and manual `budget_decision` APPROVE path pass the raw ISO string to `do_approve_cascade(..., scheduled_date_raw=scheduled_date)`.
- **Final verification**: 8-round parallel sweep, 68 tests each, all passing.

## Step 8: Finalize PRD — 2026-07-04T14:10:14.783Z

**Line counts:** PRD.md 266 lines, PRD_FINALIZED.md 266 lines (0% delta; the single change is inline within an existing line).

**Changes made (one bullet per change):**
- §3.6 (hop 2 of approval cascade) — insert — Pinned that `AssemblyTask.scheduled_date` is persisted verbatim as the caller-supplied ISO string, no server-side re-formatting/canonicalization — services.py:371–378 (also routes.py:531–533 and routes.py:593–595 which pass the raw string through).

**Step_7_diff items evaluated but not requiring PRD edits:**
- test_03/test_04/test_07 role-header swaps (ADMIN→PROOF, ADMIN→WH): PRD §4 endpoint table already correctly restricts GET `/recipients/{id}/message-proof` to `AccountManager, ProofApprover` and GET `/inventory-reservations/{id}` to `WarehouseOps, AccountManager`. Pure test bugs — no PRD silence.
- test_07 budget-hard-cap test — PRD §3.4 already states `station_id`/`scheduled_date` are required whenever the submission might auto-approve. Pure test-fixture bug.

**Per-edit pre-edit search log:**

Edit 1 — AssemblyTask.scheduled_date storage format
- (a) Subject identified: The exact string representation stored in `AssemblyTask.scheduled_date` when the approval cascade creates the task, and whether the server may canonicalize the caller's ISO string.
- (b) Impl paths enumerated & inspected:
  - `implementation/services.py:332–386` `do_approve_cascade` — sole writer of `AssemblyTask.scheduled_date`; picks `scheduled_date_raw` verbatim if passed, else formats via `db.format_iso(scheduled_dt)`. Both callers pass raw.
  - `implementation/services.py:308–327` `check_assembly_capacity` — sole reader of `AssemblyTask.scheduled_date`; parses via `db.parse_iso(...).date()`, using only the calendar-day component — format-insensitive.
  - `implementation/routes.py:485–534` auto-approval submit path — reads `body.scheduled_date`, calls `do_approve_cascade(..., scheduled_date_raw=scheduled_date)`.
  - `implementation/routes.py:558–596` manual `budget_decision` APPROVE path — same: passes raw body value through.
  - `implementation/routes.py` GET `/assembly-tasks/{tid}` (line 757) — returns the row as stored; no re-formatting.
  - Grep confirms no other `AssemblyTask.scheduled_date` write/read sites.
- (c) Wording adjustment: Framed as "verbatim as the caller-supplied ISO 8601 string, without any server-side re-formatting or canonicalization of that string" (rather than "raw", "as sent", or "with the same fractional-digit count as `api_request_timestamp`"). This constrains only that the server does not touch the caller's provided string — consistent with the capacity check's calendar-day-only read (format-insensitive), consistent with `AssemblyTask.created_at`/`updated_at`/`version` which §2.4 already governs and are unaffected, and does not spill onto how `scheduled_date` is treated on the request-body input side or on `order.scheduled_send_date` storage (both irrelevant to this fix).

## Step 9: Complete PRD — 2026-07-04T14:27:16.465Z

All in-paragraph inserts, no new lines added. Char delta +4449.

Summary:

- Source file (PRD_FINALIZED.md): 266 lines, 55,059 chars
- PRD_COMPLETED.md: 266 lines, 59,508 chars (Δ +4,449 chars, 0 line delta — every change is an in-paragraph insert/revision)
- Ambiguity-pins: 9
- Mismatch-revisions: 1

Change list:
- §2.3 Pagination — revise — mismatch — replace "must be no smaller than 1 and no larger than 100" with a silent-clamp rule (values outside [1,100] clamped, not error); add that negative `offset` is clamped up to 0 — implementation/routes.py:47-52
- §2.4 Resource Identity/Versioning — revise — mismatch — extend the account-version-bump list to include the ytd_spend-cents movement legs (order APPROVE and cancellation of already-APPROVED orders) — implementation/services.py:360, services.py:410
- §3.3 (via §3.4 order-creation paragraph) — insert — ambiguity — pin initial CorporateOrder field shape (subtotal/total 0, requires_approval false, both locked_* null, scheduled_send_date stored verbatim or null) — implementation/routes.py:293-308
- §3.4 Recipient import — insert — ambiguity — on all-rows-rejected, REJECTED shells created during the loop are rolled back; on partial success return 201 with `response_type:"array"` containing both ACCEPTED and REJECTED rows in supplied order — implementation/routes.py:417-422
- §3.4 Auto-approval — insert — ambiguity — missing body.station_id or body.scheduled_date on the auto-approval path surfaces as `ERR_FULFILLMENT_REF_NOT_FOUND` (404) — implementation/routes.py:486-487
- §3.5 MessageProof submit — insert — ambiguity — pin `ERR_INVALID_DECISION_STATE` (409) as the specific rejection for illegal prior status, and HTTP 201 for both create and resubmission — implementation/routes.py:665,668,673
- §3.5 MessageProof GET — insert — ambiguity — pin that the recipient message-proof fetch uses the list envelope (0-or-1-element array with pagination meta), not a single-object response — implementation/routes.py:676-681
- §3.6 Assembly-capacity check — insert — ambiguity — pin that only `QUEUED`/`IN_PROGRESS`/`COMPLETE` tasks count (FAILED excluded) and comparison is by UTC calendar day only — implementation/services.py:324
- §3.7 AssemblyTask COMPLETE — insert — ambiguity — pin that `on_hand_qty` decrement walks every reservation on the recipient regardless of reservation status and is floored at zero (excess demand silently absorbed) — implementation/routes.py:791-796
- §3.7 Assembly-complete cascade — insert — ambiguity — pin "all COMPLETE" is judged strictly — a single QUEUED/IN_PROGRESS/FAILED task blocks the READY_TO_SHIP advance — implementation/services.py:506
- §3.8 Shipping cascade — insert — ambiguity — pin that only IN_TRANSIT/DELIVERED shipments satisfy "reached IN_TRANSIT or later" for the READY_TO_SHIP → SHIPPED advance (EXCEPTION/RETURNED do not) — implementation/services.py:536
- §3.9 Clock-advance sweep — insert — ambiguity — pin (a) multi-interval catch-up loop on recurring series generating one clone per crossed cycle, (b) source-missing exits the loop, (c) `expires_at == now` counted as passed, (d) ytd_spend zeroing on UTC month crossover is performed unconditionally by the same clock call before the sweep, (e) clock endpoint returns 200 with `response_type:"object"` and empty `data` — implementation/routes.py:998-1005, services.py:434-458, db.py:113-120

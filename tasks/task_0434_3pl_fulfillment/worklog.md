# Worklog — task_0434_3pl_fulfillment

## Step 1: Create Task Directory — 2026-06-21T00:15:00.000Z

Created `tasks/task_0434_3pl_fulfillment/` with `workspace/` subdirectory. Index 0434 (next after highest existing task_0433_*).

## Step 2: Generate Scaffold — 2026-06-21T00:45:00.000Z

Scaffold generation ran in two parts. The first subagent (a90f3569f65051f65) wrote SCAFFOLD.yaml (1412 lines, §1.0–§1.7: 13 entities, 7 state machines, concurrency rules, 4+ calculations, validations, response envelope, 66 endpoints, error catalog, roles) and SCAFFOLD_DIFFICULTY_DESIGN.yaml (1229 lines, 18 §1.8 depth instances) successfully, but its connection closed mid-response while writing the corner design (left only the stub `scaffold_corner_design: []`). A second subagent (ac49e93e23cbe9f63) completed SCAFFOLD_CORNER_DESIGN.yaml from the existing SCAFFOLD.yaml + DIFFICULTY_DESIGN.yaml + skill §1.9 spec.

Second subagent summary (verbatim):
Wrote the complete §1.9 corner design (1927 lines), overwriting the empty stub. Sections: 9 — entities (6), state_machines (7), calculations (4), validations (6), endpoints (3), errors (3), rbac (3), cross_cutting_layers (4), consistency_model (1). Total instances: 37 — 35 non-stub (full test_recipe) + 2 excluded_because stubs. The two stubs cite real §1.8 instances by exact name: stale_lot_version_cycle_count_rejected → cycle_count_to_zero_floors_available_and_on_hand; ship_cascade_visible_in_same_response_immediate → ship_cascades_lot_consumption_bin_recompute_and_handling_ledger. Breadth dimensions: required-field validation, default application, computed/system fields, not-found, listing+pagination envelope, append-only event immutability (BillingCharge), invalid-from / terminal-state-lockdown / precondition-enforcement transitions (receive, cancel, pack, pick-confirm), valid forward transitions (deliver, return-close), conditional cascade (DAMAGED grade scraps), calculation correctness across all five calc rules (storage per-pallet-once, cartonization step-up boundary, rate-shop published==negotiated at 0 bps, single-unit handling base-only), business-rule violations (ERR_CLIENT_SUSPENDED, ERR_SKU_DISCONTINUED, out-of-range zone, ERR_PACK_UNIT_MISMATCH, ownership mismatch, inclusive capacity boundary pass), action endpoints (suspend, block), filtered-list reverse-reachability, error-catalog coverage of ERR_CARTON_OVERFLOW / ERR_RETURN_QTY_EXCEEDS_SHIPPED / ERR_ORDER_NOT_IMPORTED, peer-role RBAC denials + unauthenticated, OCC happy-path (version increment), FEFO selector determinism by created_at, hazmat force_carrier conditional flag. Validation: scaffold_lint.py returns clean lint (66 endpoints, 13 entities, 18 §1.8 + 35 §1.9 non-stub instances, 520 calls scanned, all FKs reverse-reachable). All names unique across §1.8 ∪ §1.9 union; valid YAML; SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml unmodified.

## Step 3: Copy Shared Files — 2026-06-21T00:46:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0434_3pl_fulfillment/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-21T00:48:00.000Z

Subagent aa33af6b00779a2a8 generated `workspace/PRD.md` (314 lines, 46189 bytes) from SCAFFOLD.yaml only. Both design indices withheld; no sibling tasks read.

Subagent summary (verbatim):
PRD length: 314 lines. Sections: §1 Introduction (per-client inventory ownership + estimate-vs-actual accounting themes). §2 Global Specifications — 10 subsections: RBAC (8 roles, ClientUser the only entity-backed identity, other seven opaque), verbatim §2.2 response envelope, pagination, common resource properties (BillingCharge flagged common_fields:false carrying only id/created_at), left-to-right nested resolution, cross-client/pallet-exclusivity ownership, bin capacity, cascading side effects, monetary precision, cycle-count OCC rule. §3 Business Logic — 11 lifecycle subsections (onboarding → receiving → order/wave → release/reservation → picking/short → pack/cartonization → rate-shop → ship/billing → returns → cycle counts → storage ledger). §4 — 66-endpoint table. §5 — 44-error catalogue.
Notable scaffold rules rendered into prose: Handling estimate vs billed (both integer cents; billed adds per-extra-carton surcharge for cartons beyond first, so multi-carton orders bill strictly above estimate). Cartonization (inclusive thresholds 1000/5000/20000 cc → SMALL/MEDIUM/LARGE, overflow → ERR_CARTON_OVERFLOW). Rate-shop selector (hazmat eligibility filter excluding GROUND_ECONOMY, three fixed rate cards, discount-then-round-half-up pinned evaluation, lowest-negotiated winner, fixed GROUND_ECONOMY → GROUND_PLUS → AIR_EXPRESS tie-break). FEFO reservation by lot created_at ascending (lot id never used), full reserve/consume/release cascades on lot quantities and bin occupied_cc. Cycle-count OCC (expected_lot_version vs live version, mismatch → ERR_STALE_LOT_VERSION 412; reserved-protecting clamp with available_qty flooring at 0 silently). Storage accrual (per-occupied-pallet-bin counted once per client × days). Validation priority ordering (auth 401 → forbidden 403 → left-to-right 404 → state 409 → OCC 412 → business), all 44 error IDs incl. 12 per-resource ERR_*_NOT_FOUND mentioned in prose.
Hard Contracts: Contract 1 Field-Name Coverage PASS (51/51 entity fields, 36/36 request_body fields). Contract 2 Rule Coverage PASS (all calculations, 7 state machines, OCC, 13 validations w/ error IDs, cascades, not-found codes). Contract 3 §3 Path Purity PASS (406 backtick tokens scanned, 0 path/method tokens in §3).

## Step 5: Generate Unit Tests — 2026-06-21T08:55:00.000Z

Subagent a0004279d4c996913 generated test_helpers/ (8 modules + barrel) and test_suite/ (6 files, 70 tests).

Subagent summary (verbatim):
I generated complete test infrastructure and a 70-test suite for task_0434_3pl_fulfillment, translating exclusively from the two design indices.

Stage 1 — test_helpers/ (8 modules + barrel):
- types.py — status/role enums + entity TypedDicts; BillingCharge correctly carries only id + created_at (no updated_at/version, per its common_fields: false).
- api_client.py — one method per endpoint (all 39 endpoint surfaces).
- api_errors.py — full 42-error catalog with HTTP-status map registered with the framework.
- assertions.py, factories.py, constants.py, test_users.py, fixtures.py (composite pipeline helpers: stock→release→pick→pack→label→ship, plus pallet/OCC/capacity setups). Identity threading uses make_client_user_headers(client_id) for the entity-backed ClientUser role.

Stage 2 — test_suite/ (6 domain-language files, 70 tests):
- Queue A (Difficulty): all 18 instances covered by exactly 2 tests each (36 tests).
- Queue B (Corner): 34 of 35 non-stub instances covered by ≥1 test (34 tests).

Deliberate skips (gaps left as gaps):
- Corner create_sku_missing_required_unit_volume_cc_rejected — SKIPPED. The PRD describes unit_volume_cc as a SKU field but never states that omitting a required field yields ERR_INVALID_REQUEST (the PRD's only ERR_INVALID_REQUEST triggers are received_qty<0, zone/lines/qty bounds, picked_qty bounds, and the grade enum). Fails the Coverage condition — not uniquely derivable from PRD alone.
- The 2 excluded_because: stubs (stale_lot_version_cycle_count_rejected, ship_cascade_visible_in_same_response_immediate) were not translated; both difficulty_instance cross-references resolve correctly to covered queue-A instances.

Precedence handling: the two priority_pair_validation_conflict instances use validate_error_is_one_of(...) because the PRD states each guard's trigger but never pins their precedence (per the error-precedence silence pattern); single-guard isolation tests pin the unambiguous cases.

Audits passed: all files py_compile; pytest collects all 70 tests with zero errors; all 39 helper names and all 39 api.* calls resolve; every test docstring ends in exactly one Design: tag; all 82 quoted citation spans survive a verbatim grep of PRD.md; no skip/skipif/xfail anywhere.

## Step 6: Generate Implementation — 2026-06-21T09:10:00.000Z

First subagent adaeee69511283af2 died on connection-closed mid-build (empty routes/ + services/, no app.py); partial implementation/ was removed. SendMessage unavailable in this environment, so a fresh subagent a96bd1d0a75dbda6c regenerated the complete implementation/ from scratch (INSTRUCTION.md + SCAFFOLD.yaml + PRD.md only; test_suite/ and test_helpers/ explicitly withheld to preserve the PRD-only contract).

Subagent summary (verbatim):
Built a complete Python + Flask implementation of the 3PL Fulfillment & Pick-Pack-Ship API at workspace/implementation/, traced exclusively from PRD.md, SCAFFOLD.yaml, and INSTRUCTION.md.

Structure (27 files):
- start.sh — guarded dependency install (if ! python3 -c "import flask") + exec python3 app.py, binds 0.0.0.0:$PORT (default 10000), foreground.
- Foundation: app.py (entry/error handlers/blueprint registration), db.py (empty-on-boot in-memory store, UUID ids, ISO-8601-ms timestamps, version/audit stamping), errors.py (full error catalog with HTTP statuses), response.py (PRD §2.2 envelope: meta/response_type/data, req_ ids), middleware.py (8 roles, X-User-ID/X-User-Role auth → 401/403), serializers.py (per-entity shaping with derived available_qty/occupied_cc/order_count/total_units recomputed live), calc.py, common.py (lookups with correct 404s, pagination).
- Services: inventory.py (bin volume, pallet exclusivity, lot upsert), order_ops.py (FEFO reservation, pick-task gen, consumption, short/cancel release, wave auto-complete).
- 13 route blueprints covering every endpoint in the §4 table (clients, skus, bins, inventory-lots, receipts, orders, waves, pick-tasks, cartons, shipments, returns, cycle-counts, billing), including both flat and client-nested forms.

Key behaviors per PRD prose: estimate-vs-actual handling (estimate at pack base+per-extra-unit no carton surcharge; billed at ship adds per-extra-carton surcharge — 1400→1400 1 carton, 750→850 2 cartons); rate-shop selector (hazmat filter excludes GROUND_ECONOMY, ranking on negotiated quote with single round_half_up after discount via Decimal, fixed precedence tie-break, force_carrier override with hazmat rejection); cascading side effects (ship consumes reservations, cartons→SHIPPED, posts HANDLING charge, credits balance, auto-completes wave, atomic); OCC on cycle counts (expected_lot_version vs live → 412, reserved-conserving correction with silent clamp, version bump cascades to bin); validation precedence per PRD prose; pallet exclusivity; inclusive capacity boundary; cross-ownership 409s; left-to-right nested 404s; BillingCharge carries only id+created_at.

Verification: three end-to-end smoke suites + edge cases all passed. Mid-build correction: release_reservations_short releases shortfall (qty − picked_qty) for every pick task per PRD §3.5, only ASSIGNED tasks transition to SHORT_CLOSED. start.sh boots fresh empty store (no seeding).

Spec-ambiguity decision: for multi-SKU orders the carton payload declares only packed_units count, so cartons consume units sequentially from a line-ordered flat unit list to compute fill_volume_cc (deterministic; unambiguous for the common single-SKU case).

## Step 7: Run Tests and Iterate — 2026-06-21T09:40:00.000Z

Long-lived fix subagent a9beabcad4c3718f6 ran the run-diagnose-fix-rerun loop to a clean 8-round parallel sweep (68/68 on all 8 rounds). Orchestrator re-ran the 8-round sweep independently after exit to regenerate the results artifacts (subagent's final results.*.json had been cleaned up); confirmed 68/68 × 8 rounds, 0 failed.

Subagent summary (verbatim):
Clean exit. All 8 parallel rounds passed 68/68.

Iterations run: 2 sweeps. The first sweep surfaced an infrastructure bug (uniform 0/68 across all rounds — the per-test-server restart couldn't find start.sh from the runner's cwd). The second sweep, after the fixes below, came back 68/68 green on all 8 parallel rounds.

Diagnosis path: A fast single-server diagnostic round (--isolation none) isolated the real test/impl issues (65/70, with 2 of those 5 being state-leakage artifacts of shared-server mode). All 5 traced to test/fixture bugs or unreachable-state assertions — the implementation itself was faithful and needed no logic changes.

Tests deleted (2) — both in test_suite/test_03_order_wave_return_workflows.py:
- test_reserve_then_cancel_conserves_available_qty and test_cancel_reserved_order_short_closes_pick_tasks. Category: unreachable-precondition / non-unique-derivability. Both assert a successful RESERVED → CANCELLED cancel, but PRD §3.4 states release "advances each member order from IMPORTED to RESERVED and immediately onward to PICKING" atomically — so no PRD-faithful API path yields a stable, cancellable RESERVED order. A faithful implementation correctly returns ERR_ORDER_NOT_CANCELLABLE for the PICKING order the fixture actually produces (PRD §3.8: "cancel… while it is IMPORTED or RESERVED; any other status yields ERR_ORDER_NOT_CANCELLABLE"). The asserted success outcome is not derivable, and the fixture cannot be repaired to construct the precondition. Scaffold driver: Difficulty/compensating_invariant/reserve_then_cancel_conserves_available_qty.

Fixes applied to test_suite/ (1):
- test_03_…py::test_order_short_branch_releases_unconfirmed_reservation — corrected the assertion arithmetic. The test quoted PRD §3.5's shortfall formula (qty − picked_qty = 3 − 2 = 1) but then asserted reserved 0 / available 10, which would require releasing all 3 units. Per the cited PRD sentence the result is reserved 2 / available 8 (the 2 picked-but-unshipped units stay reserved). Changed assertions to 2/8.

Fixes applied to test_helpers/ (1):
- fixtures.py::setup_received_receipt — the fixture returned the announce-time receipt snapshot (received_qty=0, status=ANNOUNCED) while discarding the receive response. test_receive_already_received_receipt_rejected reads rcpt["received_qty"] and expected 5. Fixed the fixture to return the post-receive receipt (status RECEIVED, received_qty set), making the returned object reflect the advanced state.

Fixes applied to implementation/ (1):
- start.sh — hardened cwd resolution from cd "$(dirname "$0")" to resolving ${BASH_SOURCE[0]} to an absolute path before cd, so the server boots correctly regardless of the cwd a (re)start is invoked from. The per-test-server runner restarts via this script before every test; the original form broke when the restart didn't preserve cwd. No application logic changed.

No implementation business-logic checks were weakened or removed; all server-side PRD checks remain intact.

## Step 8: Finalize PRD — 2026-06-21T09:50:00.000Z

Subagent a8b60b90987eae9dd produced workspace/PRD_FINALIZED.md as an exact copy of PRD.md (0 edits, 0% delta, 314↔314 lines). All five <step_7_diff> items traced to non-PRD-silence categories.

Subagent summary (verbatim):
PRD_FINALIZED.md is an exact copy of PRD.md with zero edits, which is the correct outcome for this task.

PRD.md vs PRD_FINALIZED.md: 314 lines vs 314 lines. 0 lines changed, 0% delta (files identical). Per-change bullets: None.

Rationale — every <step_7_diff> item maps to a non-PRD-silence category:
1. test_reserve_then_cancel_conserves_available_qty deleted (unreachable precondition). PRD §3.4 already states release "advances each member order from IMPORTED to RESERVED and immediately onward to PICKING" atomically; routes/waves.py:134-138 confirms the impl sets status = "PICKING" directly within release_wave, so RESERVED is never persisted. Combined with §3.8 ("cancel… while it is IMPORTED or RESERVED; any other status yields ERR_ORDER_NOT_CANCELLABLE"), the PRD already uniquely pins that a post-release cancel hits a PICKING order and returns ERR_ORDER_NOT_CANCELLABLE. No silence.
2. test_cancel_reserved_order_short_closes_pick_tasks deleted — identical root cause. No silence.
3. test_order_short_branch_releases_unconfirmed_reservation arithmetic fix — pure test-arithmetic bug. PRD §3.5's shortfall formula (qty − picked_qty) already matches services/order_ops.py:113-130. No silence.
4. fixtures.py::setup_received_receipt fix — pure test-helper bug. PRD §3.2's receive behavior already matches routes/receipts.py. No silence.
5. start.sh cwd-resolution fix — pure launcher/infra fix; "No application logic changed." No silence.

No-new-mismatch verification: grep -rn "RESERVED" across implementation/ confirmed RESERVED appears only as a comment in the release_wave transition path and two dead branches in cancel_order/release_reservations_cancel that no API path can reach.

## Step 9: Complete PRD — 2026-06-21T09:55:00.000Z

Subagent a8f5fdb8549e5cde5 produced workspace/PRD_COMPLETED.md from PRD_FINALIZED.md via a full PRD-vs-implementation scan. 9 in-paragraph changes (6 ambiguity-pins, 3 mismatch-revisions); line count unchanged at 314, char delta +2471.

Subagent summary (verbatim):
Files: source PRD_FINALIZED.md 314 lines / 46,189 chars; output PRD_COMPLETED.md 314 lines / 48,660 chars; char delta +2,471 (line count unchanged; all changes in-paragraph).
Counts: ambiguity-pins: 6 · mismatch-revisions: 3 (9 changes total)

Per-change log:
- §2.3 Pagination — insert — ambiguity — pinned created_at tiebreak as server-side creation order, and out-of-range/non-integer limit/offset yield ERR_INVALID_REQUEST — common.py:163, common.py:126-155
- §2.5 Nested Resolution — revise — mismatch — pinned that a cross-client BillingCharge under /clients/{clientId}/billing-charges/{chargeId} returns ERR_CHARGE_NOT_FOUND, not an ownership violation — routes/billing.py:114-115
- §3.3 Wave Building — revise — mismatch — pinned that wave BUILDING status is checked before order IMPORTED status, so ERR_WAVE_NOT_BUILDING wins when both are violated — routes/waves.py:97-100
- §3.4 Reservation — insert — ambiguity — pinned FEFO created_at tiebreak (creation order), line drawn across successive lots when one lot insufficient, one PickTask per lot segment (N lots → N tasks) — services/order_ops.py:24,55-77
- §3.6 Packing — insert — ambiguity — pinned empty cartons array is ERR_INVALID_REQUEST, packed_units<=0 is ERR_INVALID_REQUEST, running total exceeding total_units is ERR_PACK_UNIT_MISMATCH — routes/orders.py:147-169
- §3.6 Cartonization — insert — ambiguity — pinned unit-to-carton assignment: lines flattened in submitted order into per-unit volume sequence, cartons filled in payload order — routes/orders.py:171-189
- §3.7 Rate-Shop — insert — ambiguity — pinned unknown force_carrier is ERR_INVALID_REQUEST, accepted force_carrier bypasses ranking using its own published→negotiated quote — routes/shipments.py:55-71
- §3.9 Returns Restock — insert — ambiguity — pinned restock lot keyed only on (client_id, sku_id, bin_id) ignoring originating receipt, new restock lot carries null receipt_id — services/inventory.py:42-54, routes/returns.py:164-178
- §3.10 Cycle Counts — insert — ambiguity — pinned resolution order: lot existence → OCC (ERR_STALE_LOT_VERSION, even for another client's lot) → ownership (ERR_CLIENT_OWNERSHIP_MISMATCH) — routes/cycle_counts.py:41-49
- §3.11 Storage Accrual — revise — mismatch — corrected qualification of "occupied pallet bin": decided by holding a client lot with on_hand_qty>0, not by derived occupied_cc — routes/billing.py:19-32

Notes: behaviors left unchanged (PRD already pins or impl matches prose): carrier rate cards / tie-break precedence, handling estimate vs billed formulas, discount-then-round step, cartonization box boundaries, pallet exclusivity, inventory-quantity invariants, BillingCharge append-only shape, wave auto-completion, cancel-from-RESERVED path.

---

## Pipeline Complete — 2026-06-21T09:55:00.000Z

All 9 steps done. Final state: 68/68 tests pass × 8 parallel rounds (per-test-server isolation). Outputs: SCAFFOLD.yaml + 2 design indices, workspace/{PRD.md, PRD_FINALIZED.md (= PRD.md, 0 edits), PRD_COMPLETED.md (9 edits)}, test_helpers/ (8 modules), test_suite/ (6 files, 68 tests after 2 deletions), workspace/implementation/ (27 files, Python+Flask, in-memory), results.{1..8}.json all green.

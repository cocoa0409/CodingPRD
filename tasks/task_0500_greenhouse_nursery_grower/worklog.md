# Worklog — task_0500_greenhouse_nursery_grower

Scenario: 500. Greenhouse & Nursery Grower (wholesale): crop/variety & propagation schedule, bench/zone space allocation, plug/liner sourcing & transplant, climate/irrigation & input log, grow-cycle & ship-ready grade, availability list & broker order, shrink/cull, phytosanitary certificate & shipping

## Step 1: Create task directory — 2026-06-25T11:42:30.000Z

Created `tasks/task_0500_greenhouse_nursery_grower/` with `workspace/` subdirectory (ID pre-allocated; auto-scan skipped per instruction).

## Step 2: Generate scaffold (Expert tier) — 2026-06-25T12:03:52.000Z

All three required files are written and the lint verdict is clean. (Note: there's a pre-existing `worklog.md` and empty `workspace/` directory in the task dir that I did not create — they were already there; I left them untouched.)

Generated a complete **Expert-tier** scaffold for **Task 0500 — Greenhouse & Nursery Grower (wholesale)**. All three files written; `scaffold_lint.py` reports **VERDICT: clean lint** (all six checks a–f pass, including FK reverse-reachability over 11 FKs and 612 design-call replays).

**Complexity profile:** quota/allocation primary (finite bench-zone footprint + finite ship-ready saleable inventory, reserved→committed→released) blended with workflow-orchestration; flat topology, branching state machines, peer roles, immediate consistency. Five cross-cutting layers (OCC, cascading side effects, dual-variant calc, rate/threshold triggers, derived-field reconciliation).

**SCAFFOLD.yaml (§1.0–§1.7):**
- **10 entities** — CropVariety, Zone, PropagationBatch, InputLog (append-only), Broker, AvailabilityEntry, BrokerOrder, OrderLine, Shipment, PhytoCertificate.
- **6 state machines** — CropVariety (linear lifecycle), Zone, PropagationBatch (branching grade fork SALEABLE/HELD + regrade cycle + cull/void compensation), BrokerOrder (branching-with-revert), Shipment (dispatch + compensating void), PhytoCertificate (consume/release/expire).
- **7 calculations** — saleable_count (provisional-vs-final dual variant), shrink_loss_cost (standard-vs-actual dual variant), order_pricing (sum-then-round rebate, pinned), freight_charge (3-input tiered min/max), zone_occupancy, zone_fill_state (threshold), scouting_shrink (auto-cull threshold).
- **2 concurrency rules** — OCC on Zone.version (transplant) and BrokerOrder.version (confirm), both 412.
- **19 validations** (priority-ordered), **52 endpoints** (incl. `/_clock/set_current_utc` defaulting to 2026-01-01T00:00:00Z, and `/nursery/run-ops` checkpoint), **33 error codes**, **4 roles** (GrowerManager/ProductionTech/SalesCoordinator opaque; Broker entity_backed).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rules × 2 = **18 instances**, every formula-derived assertion pre-computed to literals (e.g., order_total 861495 with sum-then-round rebate vs the 861494 round-per-line trap; freight 10800 FAR; loss 14000 vs 17600; fill_state TIGHT boundary at free_units==300; auto-cull at shrink==0.50).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** 9 sections, **45 instances** (38 active test recipes + 7 `excluded_because` stubs, all citing valid §1.8 instance names). No duplicate names across both design files; no forbidden concurrency vocabulary anywhere.

## Step 3: Copy INSTRUCTION.md — 2026-06-25T12:03:52.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0500_greenhouse_nursery_grower/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-25T12:12:30.000Z

Generated `workspace/PRD.md` — a prose PRD for the Greenhouse Nursery Grower (wholesale) API, an EXPERT-difficulty quota-allocation + workflow-orchestration domain.

**Document shape:** 339 lines, 5 top-level sections. §2 has 11 subsections (2.1 RBAC, 2.2 fixed envelope verbatim, 2.3 pagination, plus 8 domain cross-cutting principles: common properties/logical clock, cascades/derived-field reconciliation, nested retrieval, precision, validation ordering, OCC, bench-space quota, loss accounting). §3 has 15 lifecycle-grouped subsections. §4 is a 4-column endpoint table (52 rows). §5 is a 2-column error table (33 rows).

Hard Contract reports all PASS: Field coverage (64/64 required fields + 7 path ids), Rule coverage (19 validations, 2 OCC, 6 state machines, 7 calculations, all cascades/symmetry), Path purity (§3 had 0 path/method tokens in 519 backtick tokens). Withheld design files were not opened; no sibling tasks consulted.

## Step 5: Generate unit tests — 2026-06-26T00:05:00.000Z

(Resumed after session-limit interruption — Step 5 had not run before the interruption.)

Test infrastructure complete and fully validated.

**Stage 1 — `test_helpers/`** (9 files): `types.py` (entity TypedDicts + status enums; `InputLog` correctly carries only `id`/`created_at`, no `version`/`updated_at`), `api_client.py` (one method per endpoint, full `/nursery/...` + `/_clock/...` paths), `api_errors.py` (33 error IDs + HTTP map), `assertions.py`, `factories.py` (input-fields-only), `constants.py`, `test_users.py` (opaque-role constants + `make_broker_headers` for entity-backed Broker), `fixtures.py` (composite setup_* helpers), `__init__.py`.

**Stage 2 — `test_suite/`**: `conftest.py` + 8 domain-named test files.

**Counts**
- Test files: 8 (+ conftest)
- Total tests: 71
- Queue A (Difficulty): 34 tests covering 17 of 18 instances (≥2 each)
- Queue B (Corner): 37 tests covering 37 of 38 non-stub instances (≥1 each); all 7 `excluded_because` stubs correctly not emitted

**Skipped instances (PRD-first filter failures — genuine PRD gaps, left as gaps):**
1. `Difficulty/priority_pair_validation_conflict/dispatch_phyto_required_beats_insufficient_live_stock` — PRD §3.14 lists the live-stock check before the phyto check, so a faithful reader would return `ERR_INSUFFICIENT_LIVE_STOCK`, not the asserted `ERR_PHYTO_REQUIRED`. Not uniquely derivable → skipped.
2. `Corner/validations/transplant_climate_mismatch_rejected` — PRD §3.4 requires zone climate to "match the variety's propagation requirement," but `CropVariety` has no climate attribute and no mapping from `propagation_form` to a climate class is defined. `ERR_CLIMATE_MISMATCH` unimplementable from PRD alone → skipped.

**Notable faithful adaptations:** for the two shipment dispatch→void instances (A6, A17), order line qty set larger than dispatched qty so the order stays `FULFILLING` (avoiding §3.14 auto-close `ERR_ORDER_ALREADY_CLOSED`); asserted live-count/footprint deltas unchanged. A2 asserts only observable cull effects (status/counts) since the loss-cost figure is not response-exposed.

**Verification:** all 71 docstring PRD citations survive whitespace-normalized grep of PRD.md; every test carries exactly one `Design:` tag resolving to a real instance; no stub tags; no skip/xfail/scaffold leakage; suite collects cleanly (71 tests).

## Step 6: Generate implementation — 2026-06-26T00:08:00.000Z

(Resumed after session-limit interruption — Step 6 had not run before the interruption. Ran concurrently with Step 5, isolated from test_suite/test_helpers.)

Built a complete Python + Flask in-memory REST API. All three input files read in full (PRD.md, SCAFFOLD.yaml §1.0–§1.7, INSTRUCTION.md). No sibling tasks, test_suite/, or test_helpers/ accessed.

**Files (15)** under `workspace/implementation/`:
- `start.sh` (guarded dep install + `exec python3 app.py`), `requirements.txt` (flask==3.0.3)
- `app.py` (app factory, blueprints, error handlers), `core.py` (store, logical clock, envelope, 35 error IDs, auth, validation, pagination), `services.py` (zone occupancy/fill-state, saleable-count provisional/final, freight+order pricing rebate tiers sum-then-round, shrink/auto-cull, cull cascade)
- `routes/`: varieties, zones, batches, brokers, availability, orders, phyto, shipments, ops, __init__

**Endpoint count:** 52 (full §1.5 surface incl. `/nursery/run-ops` and `/_clock/set_current_utc`).

**Storage:** pure in-memory `Store` (one dict per entity keyed by UUID + monotonic `_seq` for created_at-ascending pagination). No SQLite/disk/JSON. Zero seeding. Verified kill + start.sh reboot resets total_count 1→0.

**start.sh:** `set -euo pipefail`, cd to script dir, install deps only if `import flask` fails, then `exec python3 app.py` binding `0.0.0.0:$PORT` (default 10000), threaded=True. Boot <3s.

**Verification:** two smoke suites, 0 failures (full happy path + OCC 412, auto-cull 50%, zone TIGHT/FULL caps, credit-limit 402, insufficient-availability, CONFIRMED-cancel compensation, partial-dispatch + shipment void revert, run-ops cert expiry, variety-in-use, HELD/regrade loop). Envelope/RBAC/existence/well-formedness confirmed.

**Key spec ambiguities resolved in code (to be reconciled in Steps 8/9):**
- finalize-grade is a fork (GRADING→SALEABLE | GRADING→HELD), always 200, failures route to HELD; `ERR_GRADE_BELOW_SPEC`/`ERR_LIVE_PCT_BELOW_SPEC` not raised by finalize (PRD prose self-contradicts; structural spec wins).
- Climate compatibility: CropVariety has no climate field → non-MIXED zones treated compatible, `ERR_CLIMATE_MISMATCH` unreachable (scaffold gap).
- Shipment void requires order.status != SHIPPED → `ERR_ORDER_ALREADY_CLOSED`; successful voids from FULFILLING revert toward CONFIRMED.
- version starts at 1, +1 per mutation/cascade.
- Timestamps from logical clock (default 2026-01-01T00:00:00Z), ISO-8601 UTC 3 fractional digits.

## Step 7: Run Tests and Iterate — 2026-06-26T00:18:00.000Z

(Resumed after session-limit interruption — Step 7 had not run before the interruption.)

All 8 rounds pass 71/71 with zero failures in the union. The single root-cause fix resolved all 21 originally-failing tests.

**Iterations run:** 2 sweeps (initial diagnostic sweep + 1 verification sweep after the fix).

**Tests deleted:** None. (No PRD-silence or non-unique-derivability failures encountered. The two genuine PRD-gap instances noted in Step 5 remain correctly absent.)

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py`, `setup_multi_line_order()` — changed `api` from a required positional parameter to `api=None` with a fallback to the module-level `api_client` singleton. Root cause: all ~24 call sites across 5 test files invoke this helper as `setup_multi_line_order(line_specs=..., ...)` without passing `api` (unlike every sibling helper), producing an identical `TypeError: ... missing 1 required positional argument: 'api'` setup error in all 21 failing tests. The conftest `api` fixture is that same singleton, so the fallback is behavior-identical and matches the call convention the test author used. (Triage hint: ≥5 tests sharing one setup error → test_helpers is prime suspect.)

**Fixes applied to `implementation/`:** None. The 21 failures all died at fixture setup before any assertion ran; once setup succeeded, every pricing/freight/rebate, confirm/cancel ledger, dispatch/void cascade, and regrade assertion passed against the existing implementation unchanged.

**Final sweep result:** 71/71 passed × 8 parallel rounds (union of failures across all 8 rounds = 0).

## Step 8: Finalize PRD — 2026-06-26T00:24:00.000Z

Confirmed: `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` (0 edits).

**Line/byte counts:** PRD.md = 339 lines / 55,937 bytes; PRD_FINALIZED.md = 339 lines / 55,937 bytes. %-delta = 0%. Byte-identical (`diff` exit 0). 0 edits.

**Changes:** None — verbatim copy.

**0-edit justification:** The lone <step_7_diff> item is the `test_helpers/fixtures.py setup_multi_line_order()` change (`api` made an optional param defaulting to the module-level `api_client` singleton). Subject = how the multi-line-order test helper obtains its ApiClient handle — a pure test-side transport plumbing fix touching no implementation code. Enumerated the helper's full compose chain and the implementation alignment target (core.py + all route modules + services.py/app.py); confirmed the fix reveals no PRD silence and no PRD/impl mismatch (all 21 failures died at fixture setup before any assertion; once setup succeeded every assertion passed against the unchanged impl, 71/71 × 8 rounds). The order-pricing/availability-commitment/broker-credit/confirmation behaviors `setup_multi_line_order` exercises were already determined by PRD §3.10–§3.11. No wording adjustment warranted — verbatim copy is correct.

## Step 9: Complete PRD — 2026-06-26T00:34:00.000Z

All 11 edits applied. The file remains 339 lines (every change in-paragraph, no lines added/removed), char delta +1238.

**File metrics**
- PRD_FINALIZED.md: 339 lines / 55,937 chars
- PRD_COMPLETED.md: 339 lines / 57,175 chars (Δ +1,238 chars; 10 lines revised in place, 0 added/removed)

**Counts:** 11 changes total — 6 ambiguity-pins, 5 mismatch-revisions.

**Changes:**
- §2.3 Pagination — insert — ambiguity — `limit`<1/>100 and negative `offset` are clamped (not rejected); non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — core.py:330-346
- §2.3 Pagination — insert — ambiguity — list ordering ties on equal `created_at` broken by creation/insertion order — core.py:349-355 (sorts by `_seq`)
- §2.4 Common Resource Properties — revise — ambiguity — `version` creation baseline pinned to `1` — core.py:129-137 (`common_create` sets `version=1`)
- §2.8 Validation Ordering — revise — mismatch — dropped phantom "climate" check from transplant ordering example (no climate gate exists) — batches.py:134-138
- §3.3 Starting a Batch — insert — ambiguity — pinned PLANNED-creation defaults: `started_count`/`cull_count`/`shipped_count`/`mean_height_cm`=0, `stick_date`/`target_ship_date`=null — batches.py:74-90
- §3.4 Transplanting — revise — mismatch — climate-compatibility check removed; any `climate_class` zone accepts any eligible variety, `ERR_CLIMATE_MISMATCH` never raised — batches.py:134-138
- §3.6 Grading — revise — mismatch — finalize-grade is a non-rejecting fork (always 200; failures route to HELD); `ERR_GRADE_BELOW_SPEC`/`ERR_LIVE_PCT_BELOW_SPEC` never raised — batches.py:203-217
- §3.13 Phyto Certificates — revise — mismatch — `certificate_number` uniqueness not enforced (recorded as supplied) — phyto.py:12-38
- §3.14 Shipments (create) — insert — ambiguity — line not belonging to order, or quantity exceeding remaining (`quantity` − `shipped_quantity`), rejected with `ERR_INVALID_REQUEST` — shipments.py:55-71
- §3.14 Shipments (void guard) — revise — ambiguity — order status `SHIPPED` → `ERR_ORDER_ALREADY_CLOSED`; voids occur only while order is `FULFILLING` — shipments.py:206-210
- §3.14 Shipments (void effects) — revise — mismatch — order reverts `FULFILLING`→`CONFIRMED` only when no line retains positive `shipped_quantity`; broker `open_balance_cents` left unchanged (credit released only at `SHIPPED`, which the guard precludes) — shipments.py:234-239

**Verified-and-left-unchanged:** §2.8 validation precedence across endpoints; confirm-order precondition order; dispatch precondition + phyto error order; freight bands/floor/cap/per-rack + rebate tiers (round-half-up); provisional vs final `saleable_count`; auto-cull ≥50% inclusive; OCC version checks; logical-clock default + ISO-8601 3-digit timestamps; zone fill_state thresholds; broker credit rise/fall. Loss accounting (§2.11/§3.7) left as-is (impl computes/surfaces no loss figure).

**Pipeline complete — all 9 steps finished. Final: 71/71 tests passing across 8/8 stability rounds (Expert difficulty).**

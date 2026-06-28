# Worklog — task_0639_blow_dry_bar_styling

## Step 1: Create Task Directory — 2026-06-23T11:07:51.000Z

Task directory `tasks/task_0639_blow_dry_bar_styling/` was pre-assigned and pre-created (with `workspace/`). Skipped the Step 1 max-index scan per orchestration directive. Proceeding with this path as-is.

## Step 2: Generate Scaffold (Expert band) — 2026-06-23T11:25:00.000Z

All three files written and validated (`scaffold_lint.py` → `VERDICT: clean lint`).

**Domain:** Blow-Dry Bar & Styling (Drybar-style). Archetype: temporal_windowing + pricing_engine; topology flat; state-machine shape parallel; role_model peer_roles; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation, scheduled_deferred_actions.

**Entities (12):** StyleService, AddOn, MembershipPlan, Member, Stylist, Chair, Appointment, AppointmentAddOn (junction), EventBlock, Product, RetailSale, PackagePurchase. 13 FKs, all canonical-prefixed with reverse-reachability GETs.

**State machines (6):** Appointment **parallel** axes — `lifecycle_status` (BOOKED→CHECKED_IN→IN_SERVICE→COMPLETED, +NO_SHOW/CANCELLED) and independent `settlement_status` (UNSETTLED→SETTLED/VOIDED); EventBlock **cyclic** (HOLD↔CONFIRMED revision rounds, →CHECKED_IN→CLOSED/CANCELLED); Member (ACTIVE↔SUSPENDED via strikes), RetailSale, PackagePurchase. 2 OCC concurrency rules (book-into-stale-EventBlock, package-purchase-stale-Member), both 412 on `version` mismatch with version-bumping write endpoints.

**Key calculations (9):** per-line-rounded membership discount then sum (rounding-order pinned), blowout-credit waterfall (membership→package), late-fee threshold (grace `<=` boundary, capped), tip split (standalone 70/30 vs event 50/50), tiered commission with event-rate-cap `min()`, retail commission (flat — dual-variant against tiered service commission), event-block deposit (group vs bridal surcharge), no-show strike accrual, prepay-ledger reconciliation.

**RBAC (4 roles):** FrontDesk (opaque), FinanceManager (opaque), Stylist (entity_backed), Member (entity_backed). **56 endpoints, 44 error codes, 14 validation priorities.**

**Corner-case count:** §1.8 = 18 difficulty instances (exactly 2 per each of 9 rules); §1.9 = 43 active corner instances + 2 `excluded_because` stubs.

## Step 3: Copy Shared Files — 2026-06-23T11:26:57.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0639_blow_dry_bar_styling/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-23T11:32:38.000Z

**File written:** `workspace/PRD.md` — 314 lines, 5 top-level sections (Introduction, Global Specs, Business Logic, Endpoint Definitions, Error Catalogue) with 23 subsections.

**Coverage:** 12 entities (all fields), 56 endpoints (§4 table), 44 errors (§5 table + narrative). State machines: Appointment dual-axis (`lifecycle_status` + independent `settlement_status`), cyclic EventBlock (`HOLD↔CONFIRMED→CHECKED_IN→CLOSED`/`CANCELLED`), Member `ACTIVE↔SUSPENDED`, RetailSale, PackagePurchase. Calculations: service pricing (per-line round-then-sum discount, blowout-credit), late fee (10-min grace, 100¢/min, 2,500¢ cap), tip split (70/30 standalone vs 50/50 event), commission tiers (35/45/55%, 40% event cap), retail commission, event deposit (2,000¢/head + 10,000¢ bridal surcharge), no-show strikes (threshold 3), prepay ledger, blowout-credit waterfall.

**Hard contracts all PASS:** Contract 1 (field-name coverage, 81 fields, 0 missing); Contract 2 (rule coverage — both OCC concurrency rules named with `ERR_STALE_VERSION`/412, all enums/states/constants embedded); Contract 3 (§3 path purity, 0 violations). Both `SCAFFOLD_*_DESIGN.yaml` withheld — not opened.

## Step 5: Generate Unit Tests — 2026-06-23T11:48:00.000Z

**`test_helpers/` (9 files):** types.py, api_client.py (one method per endpoint), api_errors.py (47-error catalogue), assertions.py (per-entity + commission/tip-conservation invariants), factories.py, constants.py, test_users.py (opaque FrontDesk/FinanceManager + entity-backed make_stylist_headers/make_member_headers), fixtures.py, __init__.py. Imports verified clean.

**`test_suite/` — conftest.py + 9 test files, 80 test functions:**
- Queue A (Difficulty): 36 tests — all 18 difficulty instances ≥2 tests each.
- Queue B (Corner): 44 tests — all 43 non-stub corner instances ≥1 test each.

**Skips:** None. Every instance passed the PRD-first two-condition filter. The 2 corner `excluded_because:` stubs correctly NOT translated (cross-refs resolve to real difficulty instances).

**Audits passed:** 0 coverage shortfalls; 80 tests = 80 Design tags (each exactly one, real instance); every PRD quote verified verbatim; no skip/xfail; all byte-compile, pyflakes clean, suite collects 80 cleanly. One recipe correction: `ces_checkin_depends_on_member_status` books target appointment before accruing 3 strikes so check-in reaches `ERR_MEMBER_SUSPENDED`.

## Step 6: Generate Implementation — 2026-06-23T11:48:00.000Z

**Files (19, ~2,200 LOC):** start.sh (foreground; reads $PORT default 10000, binds 0.0.0.0, guarded pip install, exec python3 app.py), requirements.txt (flask==3.0.3), app.py, db.py (12 entity dicts + prepay ledger + logical clock, all empty on boot), errors.py, response.py, middleware.py, common.py, lookup.py, serialize.py; routes/ (config.py, members.py, appointments.py, event_blocks.py, retail.py); services/ (reconcile.py — calculations + derived-field reconciliation; scheduling.py — window/overlap/reserved-chair).

**Endpoints:** All 56 from PRD table implemented (verified 56 handlers). In-memory dicts only, no disk/SQLite, no startup seeding (the only seed is request-driven: POST /members seeds blowout_credit_balance from plan per PRD §3.2).

**Self-verification:** 5 smoke suites, 100 assertions all passing — discount rounding order, blowout-credit, late-fee boundaries, tip splits, tiered commission with 40% event cap, no-show strikes→suspension→reinstate, event-block cyclic lifecycle, OCC stale-version 412, PREPAY ledger, package purchase/refund, retail sale/void/restock, RBAC 403, §2.9 validation ordering, 3-digit ISO timestamps, version bumps.

## Step 7: Run Tests and Iterate — 2026-06-23T11:59:01.000Z

**Iterations run:** 2 (baseline sweep, then one fix + verification sweep).

**Tests deleted (1):**
- `test_reopen_in_progress_block_rejected` in `test_suite/test_07_event_blocks.py` — **PRD-silence category: ERROR PRECEDENCE SILENCE (STEP 1b non-unique-derivability).** Test sets up a CONFIRMED block, checks in `appt1` (which per PRD §3.11 auto-advances the block CONFIRMED→CHECKED_IN), then attempts `reopen` and asserts `ERR_BLOCK_IN_PROGRESS`. But the in-progress precondition is logically inseparable from "block no longer CONFIRMED"; PRD lists the CONFIRMED status check first and §2.9 does not order two 409 state errors against each other, so a faithful PRD-only implementer reading preconditions in listed order correctly produces `ERR_EVENT_BLOCK_NOT_CONFIRMED` (what the impl does). Both implementations are articulable and PRD-consistent → not uniquely derivable → deleted, not weakened.

**Fixes applied to `test_helpers/`:** none.
**Fixes applied to `test_suite/`:** 1 deletion (above), no edits.
**Fixes applied to `implementation/`:** none — reopen precedence (status-before-in-progress) already faithful to PRD's literal precondition ordering.

**Final state:** orchestrator re-ran an independent foreground 8-round verification sweep — all 8 rounds fully green: **79/79 passed, 0 failed, 0 errors, 0 skipped** in every round. `results.{1..8}.json` persisted in `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-06-23T12:01:19.000Z

Step 7 had 1 test deletion → skip condition NOT met → Step 8 ran.

**Line counts:** PRD.md 314 → PRD_FINALIZED.md 314 (0% line-delta; +367 chars in-line, ~0.8% byte growth).

**Changes (1):**
- **§3.11 (Event blocks, reopen) — insert — pinned precedence between `ERR_EVENT_BLOCK_NOT_CONFIRMED` and `ERR_BLOCK_IN_PROGRESS`** — `implementation/routes/event_blocks.py:148-152`. Added a clause: reopen preconditions are evaluated in listed order, so the CONFIRMED status check takes precedence over the in-progress check; a non-CONFIRMED block (including one auto-advanced to `CHECKED_IN`) returns `ERR_EVENT_BLOCK_NOT_CONFIRMED`, not `ERR_BLOCK_IN_PROGRESS`. This resolves the single PRD error-precedence silence that drove the Step 7 deletion.

**Pre-edit search log:** subject = reopen-endpoint error precedence; enumerated `event_blocks.py:141-157` (reopen), `appointments.py:277-282` (check-in cascade CONFIRMED→CHECKED_IN), and parallel confirm/close/cancel transitions (all status-first) — consistent. Wording scoped to "these reopen preconditions" and "takes precedence over" so no claim is made about other transitions and the `ERR_BLOCK_IN_PROGRESS` path stays reachable while CONFIRMED.

## Step 9: Complete PRD — 2026-06-23T12:08:29.000Z

Full PRD-vs-implementation completeness scan (always runs). Source: PRD_FINALIZED.md.

**Line counts:** PRD_FINALIZED.md 314 → PRD_COMPLETED.md 314 (in-paragraph edits only; chars 47,873 → 50,439, +2,566). **10 changes: 6 ambiguity-pins, 4 mismatch-revisions.**

**Highest-impact (3 mismatch-revisions):** removed the nonexistent booking-time PREPAY "hold" across §3.2/§3.5/§3.9 — impl debits prepay only at settlement (`services/reconcile.py:185-202`, `routes/appointments.py:153-157,365-374`), never holds at booking nor releases on cancel.

**Other pins:** §2.7 retail/package FK existence order; §2.9 OCC `ERR_STALE_VERSION` (412) check position (after state preconditions / last after domain 409s); §3.2 plan `member_discount_pct` range → `ERR_INVALID_REQUEST`, missing-plan GET 404, duplicate-email 422, unresolved plan-id at registration 404; §3.4 event-block window-containment formula + wrong-status → `ERR_BLOCK_CHAIR_OR_WINDOW_MISMATCH`, reserved-chair exclusion uses interval overlap on CONFIRMED-only blocks; §3.6 add-on chair-collision rollback 409 + precedence; §3.11 organizer-member + reserved-chair existence/array validation; §3.12 duplicate-`sku` 422 + `initial_stock` ≥ 0.

---

## PIPELINE COMPLETE — 2026-06-23T12:08:29.000Z

All 9 steps complete. `workspace/PRD_COMPLETED.md` exists on disk. Final test state: **8/8 stability-sweep rounds fully green, 79/79 tests passed** (0 failed, 0 errors, 0 skipped). `results.{1..8}.json` persisted in `workspace/implementation/`.

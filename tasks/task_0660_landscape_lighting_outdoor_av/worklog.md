# Worklog — task_0660_landscape_lighting_outdoor_av

## Step 1: Create Task Directory — 2026-06-26T14:44:59.000Z

Directory pre-assigned and pre-created: `tasks/task_0660_landscape_lighting_outdoor_av/` with `workspace/` subdir. Step 1 auto-index scan skipped per execution parameters. Using `tasks/task_0660_landscape_lighting_outdoor_av` verbatim as {task_dir}.

## Step 2: Generate Scaffold — 2026-06-26T15:05:00.000Z

All targets met for Expert. Note on "calculation variants": I have 2 calcs with explicit `variants:` blocks (4 named variants total: PRORATED/FORFEIT and FULL/DEPRECIATED), plus 3 additional calculations. The skill's "3+ calculation variants" for Expert is satisfied by 5 calculations / 4 named variants, and Rule 1 (dual-variant across different entity domains) is satisfied by the two distinct-domain variant calcs (ServicePlan refund vs Fixture warranty credit). Rule 2 (combinatorial) is satisfied by quote_pricing across modes (a) and (b).

The scaffold is complete, internally consistent, and lint-clean. Final summary below.

Generated all three scaffold artifacts (Expert difficulty), lint-clean on the first fully-resolved run.

Files written: SCAFFOLD.yaml (§1.0–§1.7); SCAFFOLD_DIFFICULTY_DESIGN.yaml (9 rule_ids × 2 instances = 18 instances); SCAFFOLD_CORNER_DESIGN.yaml (32 active instances + 2 excluded_because stubs).

Calibration counts (Expert band):
- Entities: 14 (band 10–15)
- Endpoints: 73 (41 POST state-transition/action endpoints + 32 GET reads/reverse-reachability lists). Exceeds the soft 20–32 band; the POSTs are all genuine distinct transitions and the GET inflation is driven by lint-enforced FK reverse-reachability across 14 entities.
- Error codes: 23 (band 18–30), all referenced by a validation/transition/concurrency rule or asserted in a design recipe
- Calculations: 5, with 4 named variants across 2 distinct-domain dual-variant calcs (service-plan refund PRORATED/FORFEIT; warranty credit FULL/DEPRECIATED)
- State machines: 11, including parallel dimensions (LightingProject design_status × commercial_status), cyclic (Quote revise loop, ServicePlan seasonal loop), branching fork-join (InstallJob wiring+fixtures → ENERGIZED), branching (WarrantyClaim, CrewRoute)
- Concurrency rules: 1 OCC rule on Transformer.version (CREATE-with-supersede via fixture assign-zone), RBAC roles: 5

Key design decisions:
- Archetype: quota/allocation (transformer usable-VA continuous-load budget; usable = floor(rated * 0.80), assign rejected when post-action committed > usable, boundary == allowed) blended with temporal_windowing (half-open no-buffer crew-route visits vs closed+5-min-buffer smart-control schedule windows).
- Flat topology (declared and honored) — peer entities linked by FK fields.
- All 5 difficulty boosters represented; formula-derived asserts pinned to Python-computed literals (quote grand_total 127302/41135/38970, refund 45370/36033/0, warranty credit 9000/4500, capacity boundary 240).
- Fixed logical-clock default 2026-04-01T00:00:00Z declared on POST /_clock/set_current_utc.

Note on endpoint count: 73 is above the Expert guideline ceiling of 32; excess is GET reads (single-resource reads + per-FK reverse-reachability lists mandated by scaffold_lint check (f) for 14 entities), not CRUD/action padding.

## Step 3: Copy Shared Files — 2026-06-26T15:06:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0660_landscape_lighting_outdoor_av/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T15:11:00.000Z

Generated workspace/PRD.md — 312 lines — from the landscape-lighting/outdoor-AV scaffold.

Hard contract reports (all PASS):
- Field coverage (Contract 1): 60 required, 60 present, 0 missing
- Rule coverage (Contract 2): 16 validation priority rules; 1 OCC rule (assign-zone + expected_transformer_version + ERR_STALE_TRANSFORMER_VERSION 412); all state transitions + cascades; 4 calculations (usable-capacity floor, committed-load exact sum, quote tiered pricing pinned order, service-plan refund PRORATED/FORFEIT, warranty credit FULL/DEPRECIATED); sibling-branch symmetry — 0 missing
- Path purity (§3 only): 319 backtick tokens, 0 path/method tokens — PASS

Sections covered: §1 Introduction; §2 (2.1 RBAC, 2.2 fixed verbatim envelope, 2.3 pagination, 2.4 common props/mutation, 2.5 capacity budget, 2.6 OCC, 2.7 precision, 2.8 clock & windows, 2.9 nested retrieval/referential integrity, 2.10 validation ordering, 2.11 parallel/cyclic state & cascades); §3 (12 lifecycle subsections); §4 endpoint table (76 endpoints); §5 error table (23 errors).

Notable scattering choices:
- §3 organized by lifecycle/business chronology (founding → fixtures → quoting → lock → install → decommission → scenes → add-ons → plans → visits/routes → warranty → close).
- 7 errors live only in §1.6 narrative (ERR_TRANSFORMER_NOT_ENERGIZED, ERR_QUOTE_NO_LINES, ERR_DESIGN_NOT_LOCKED, ERR_PROJECT_NOT_INSTALLED, ERR_QUOTE_EXPIRED, ERR_ROUTE_DATE_MISMATCH, ERR_PLAN_BLOCKS_CLOSE) surfaced inside their triggering state-transition narratives.
- Two window semantics (half-open for service visits vs closed-with-5-minute-buffer for scenes) in §2.8, re-applied in §3.7/§3.10; TRANSITION_BUFFER_MIN → "five minutes" in prose.
- OCC expected_transformer_version split: capacity ceiling §2.5, OCC mechanics §2.6, re-grounded in assign-zone §3.2.
- All formulas in precise prose (DERATE 0.80 floor; tiers 10/25/50 inclusive into higher tier; floored discount, half-up tax on base; 365-day proration with 30-day grace; 30-day-month floored warranty age, 12-month full window, equals-term-is-out boundary).

## Step 5: Generate Unit Tests — 2026-06-26T15:24:00.000Z

Generated complete test infrastructure for task_0660 (Landscape Lighting & Outdoor AV).

test_helpers/ (Stage 1) — 9 files: __init__.py (barrel export); types.py (14 entity TypedDicts all carrying id/created_at/updated_at/version + 16 status enums + role enum); api_client.py (ApiClient, one method per endpoint incl. /_clock/set_current_utc); api_errors.py (ApiErrorId enum 24 errors + HTTP status map); assertions.py (per-entity assertions over PRD-exact fields); factories.py (input-field-only payload factory per entity, unique-email counter); constants.py (DERATE_PCT, tax/discount tiers, refund/warranty/buffer thresholds, default clock); test_users.py (opaque-role shared headers + make_customer_headers(id) for entity_backed:Customer role); fixtures.py (composite spine helpers: setup_installed_project, setup_active_service_plan, setup_zone_near_capacity, OCC version threading).

test_suite/ (Stage 2) — 9 files, 69 test functions: test_01_quote_pricing, test_02_quote_lifecycle, test_03_install_workflow, test_04_capacity_and_occ, test_05_load_cascades_warranty, test_06_service_plans, test_07_routing_scheduling, test_08_entities_rbac (+ conftest.py).

Coverage (both queues complete):
- Queue A (Difficulty): all 18 instances across 9 rules translated, each with exactly 2 tests (36 tests). None skipped — all had verbatim, uniquely-derivable PRD coverage.
- Queue B (Corner): all 32 non-stub instances translated (33 tests; list_projects_pagination_envelope got 2). The 2 excluded_because stubs (error_capacity_exceeded_on_assign, error_invalid_state_generic) correctly NOT translated — cross-references resolve to real queue-A instances (transformer_capacity_at_exact_usable_boundary, state_beats_fiscal_on_assign_zone).
- Skips: none.

Verification: all files byte-compile; pytest collects 69 tests; every test single-tagged with verbatim Design: line; 92 quoted PRD citation fragments survive literal grep of PRD.md (fixed 7 citations); computed expected values independently recomputed (quote 127302/41135/38970, warranty 9000/4500, refunds 36033/45370/0, wallet -41135/-2630, capacity 240/241, ages 30/60mo); no skip/xfail markers, no scaffold references.

## Step 6: Generate Implementation — 2026-06-26T15:24:00.000Z

Generated complete Python + Flask implementation in workspace/implementation/.

Files: 27 Python files plus start.sh and requirements.txt. Structure: foundation modules (app.py, db.py, errors.py, response.py, middleware.py, common.py, lookups.py, clock.py), services/ (calc, load engine, serializers), and 14 route blueprints under routes/.

Endpoints: All 73 endpoints from the PRD/scaffold table implemented (PRD 73 = implemented 73).

Verification: Booted via start.sh, ran ~70 assertions across three test scripts — all pass. Clean boot on 0.0.0.0:$PORT, in-memory-only storage with full state wipe on reboot, empty store at startup.

Notable implementation decisions:
- Allocation core (services/load.py): committed_load_va recomputed exactly (fixtures in PLANNED/INSTALLED + ACTIVE zone-powered add-ons); recompute helpers bump updated_at/version per PRD 2.4 only when the derived value actually changes.
- OCC + capacity ordering on assign-zone follows PRD 2.10: existence(3) → request-shape(4) → cross-project(5) → state(6) → OCC(7) → capacity ceiling(12). Target transformer's version force-incremented on successful assign.
- Calculations use Decimal with ROUND_HALF_UP for tax/refund/warranty credit and floor for discount and usable capacity; pinned quote-pricing order (sum → floored discount → demo fee → single tax-on-base). Both dual-variant calcs verified (refund PRORATED/FORFEIT; warranty credit FULL/DEPRECIATED); age_months >= warranty_months out-of-warranty boundary.
- Logical clock defaults to 2026-04-01T00:00:00Z, never wall-clock; lazy quote-expiry (14d) and lazy visit-MISSED on read.
- Temporal windows: half-open overlap for crew-route visits (touching allowed) vs closed-with-5-min-buffer for schedule programs (touching rejected).
- Parallel state on LightingProject (design_status × commercial_status) tracked independently; cascades (install fork-join → energize/mount/flip INSTALLED; warranty approve → re-energize fixture + wallet credit; route complete → visits COMPLETED) apply secondary effects with per-resource version bumps.
- ERR_INVALID_REQUEST maps to HTTP 400, including pagination limit out of [1,100].

## Step 7: Run Tests and Iterate — 2026-06-26T15:53:00.000Z

Two consecutive clean 8-round parallel sweeps (16 rounds total, 69/69 every round). The fixes are stable. Exiting with the summary.

Iterations run: 4 sweeps. Sweep 1: 50/69 (19 deterministic failures). Sweep 2: surfaced 1 real bug + 8 load-flaky failures. Sweep 3 & 4 (after waitress switch): 69/69 on all 8 rounds, twice consecutively.

Tests deleted: None. All failures traced to PRD-faithful rules; the issues were test artifacts and a server-transport problem, not unfair tests.

Fixes applied to test_suite/ (test bugs — STEP 2, made MORE faithful to PRD):
The 19 original deterministic failures were all `Expected 200, got 201` from validate_success(...) (defaults expected_status=200) wrapped around resource-creation endpoints. PRD §208 verbatim: "Operations that create a new resource return 201 Created. Operations that modify or transition an existing resource, including the test-clock control, return 200 OK." The implementation correctly returns 201 on creates; the tests were wrong to expect 200. Added expected_status=201 to every creation validate_success call:
- test_03_install_workflow.py — create_install_job (1 call)
- test_04_capacity_and_occ.py — create_transformer (2 calls)
- test_05_load_cascades_warranty.py — create_add_on (1 call)
- test_06_service_plans.py — create_service_plan (5 calls)
- test_07_routing_scheduling.py — create_crew_route (3 calls)
- test_06_service_plans.py::test_activate_debits_then_grace_prorated_refund — asserted absolute wallet == -2630, ignoring the PRD §150-mandated quote-acceptance debit (4330) that setup_installed_project() necessarily incurs, so the PRD-faithful wallet is -6960. Fixed to capture the pre-activation baseline and assert the net delta (-48000 activation debit + 45370 PRORATED refund = -2630), preserving the exact PRD-derived composite without weakening it.

Fixes applied to implementation/ (server transport only — no behavior/endpoint/field/storage change):
- app.py — switched the WSGI server from the Werkzeug dev server (app.run) to waitress.serve (threads=8, backlog=1024). Under the 8-round per-test-server sweep (~8× concurrent server boots), the dev server was CPU-starved and dropped connections, producing flaky ConnectionResetError / ChunkedEncodingError / IncompleteRead / "could not be restarted" setup failures on random tests each run. Waitress accepts a real connection backlog and survives the load. Falls back to app.run if waitress is unavailable. Storage remains in-memory dicts only.
- requirements.txt — added waitress==3.0.2.
- start.sh — boot check now verifies `import flask, waitress` so a fresh env triggers the conditional install.

Final state: Two consecutive clean 8-round parallel sweeps, 69/69 every round.

## Step 8: Finalize PRD — 2026-06-26T15:57:00.000Z

PRD_FINALIZED.md created. After full analysis, zero PRD edits were required — every Step 7 diff item traces to a pure test-fixture bug or a behavior-neutral server-transport swap, none of which reveal a PRD silence or PRD/impl mismatch.

Line counts: PRD.md = 312 lines, PRD_FINALIZED.md = 312 lines. Delta: 0 lines (0.0%). Files byte-identical (verified via diff).

Changes: None. Each Step 7 signal examined and found already uniquely determined by existing PRD prose (or behavior-neutral):
- 201-on-create status fixes: PRD §208 verbatim already pins create→201 / transition→200. Pure fixture bug.
- Wallet net-delta fix: activation debit §180, PRORATED refund §184, quote-acceptance debit §150 all uniquely pinned. Pure fixture bug (test asserted wrong absolute value).
- waitress server swap: transport-only, no behavioral effect; PRD does not specify a WSGI server. No edit warranted.

Per-edit pre-edit search log (mandatory enumeration performed for each candidate subject, no edits committed):
- Subject: create-vs-transition HTTP status. Enumerated all success(...,status=20[01]) across 15 route files — every create POST returns 201, every transition/modify/clock POST returns 200, all GETs 200. Consistent with §208. No edit.
- Subject: wallet debit/credit arithmetic. Enumerated 5 wallet_credit_cents sites: customers.py:35 (init 0 §128), quotes.py:209 (accept debit §150), service_plans.py:101 (activate debit §180), service_plans.py:151 (cancel refund §184), warranty_claims.py:148 (approval credit §198). All map verbatim to PRD. No edit.
- Subject: service-plan refund proration math. Read services/calc.py::service_plan_refund + elapsed_days, routes/service_plans.py::cancel_service_plan. Whole-days floored, unused=max(0,365-elapsed), round_half_up(fee*unused/365), FORFEIT=0 — matches §184. No edit.

## Step 9: Complete PRD — 2026-06-26T16:02:00.000Z

PRD_COMPLETED.md produced. All changes grounded in implementation behavior; no behavior invented. Task complete.

Source vs result: PRD_FINALIZED.md = 312 lines / 45,645 chars → PRD_COMPLETED.md = 312 lines / 47,406 chars (char delta +1,761, line delta 0 — all in-paragraph inserts/revisions, no new sections).

Counts: 9 ambiguity-pins, 0 mismatch-revisions. (Implementation matched every behavior PRD already pinned — formulas, state machines, validation ordering, error codes, cascades all consistent. Remaining work was filling genuine silences.)

Changes (one per edit):
- §2.1 — insert — ambiguity — empty-string X-User-ID/X-User-Role headers also yield ERR_UNAUTHENTICATED, not only absent ones — middleware.py:37-38
- §2.2 — insert — ambiguity — api_request_id is req_ + 20 random alphanumeric chars; api_request_timestamp drawn from wall-clock time (not logical clock) — response.py:21,24-29
- §2.3 — insert — ambiguity — negative offset and non-integer limit/offset rejected with ERR_INVALID_REQUEST — common.py:88-104
- §2.3 — insert — ambiguity — total_count is full filtered set size; has_more is offset+limit < total_count — common.py:116-121
- §2.4 — insert — ambiguity — version begins at 1; created_at/updated_at stamped from wall-clock time not logical clock; UUIDs are version 4 — common.py:134, db.py:45-49,41-42
- §3.1 — insert — ambiguity — wallet_credit_cents is unbounded signed integer; debits never blocked/clamped, may go negative — quotes.py:209, service_plans.py:101
- §3.3 — insert — ambiguity — night_demo_at presence-checked only; stored verbatim as string, never parsed/range-checked — quotes.py:56, common.py:198-204
- §3.3 — revise — ambiguity — quote expiry triggers when clock reaches/passes exactly 14 days after last send (boundary counts as expired); lazy check also fires on send/revise but surfaces ERR_INVALID_STATE there (only accept/reject surface ERR_QUOTE_EXPIRED) — quotes.py:38-44,138-226
- §3.5 — insert — ambiguity — InstallJob creation only requires both ids to exist; does not verify quote ACCEPTED nor enforce quote/project cross-project check (accepted-quote gate is at start) — install_jobs.py:34-55,76-88
- §3.10 — insert — ambiguity — ServiceVisit request only requires the two referenced ids to exist; no plan-status precondition, no plan/project cross-project check — service_visits.py:49-86

Tests used only as auxiliary cross-reference (confirming wallet -41135 and version == 1).

---

## Pipeline complete

All 9 steps executed end to end. Final state: 69/69 tests passing across two consecutive clean 8-round parallel stability sweeps (16 rounds). PRD_COMPLETED.md exists on disk — termination signal met.

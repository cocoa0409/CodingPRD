# Worklog — task_1200_timber_sale_forest_management_plan

## Step 1: Create Task Directory — 2026-08-11T18:48:00.000Z

Task directory pre-assigned and pre-created: `tasks/task_1200_timber_sale_forest_management_plan/` with `workspace/` subdirectory. Step 1 auto-index scan skipped per instructions; Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-11T20:09:00.000Z

Done. All three scaffold artifacts are written and the lint verdict is clean.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1200_timber_sale_forest_management_plan/SCAFFOLD.yaml` — §1.0–§1.7 (envelope, entities, state machines, concurrency rules, calculations, validations, endpoints, errors, roles); no `scaffold_difficulty_design`/`scaffold_corner_design` keys inside it
- `/home/ubuntu/github/CodingPRD/tasks/task_1200_timber_sale_forest_management_plan/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1200_timber_sale_forest_management_plan/SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

## Counts
- **Entities:** 18 (4 registry parties + ForestTract, Stand, InventoryCruise, HarvestPrescription, TimberSale, Bid, HarvestContract, PerformanceBond, ScaleTicket, Settlement, BMPInspection, ReforestationObligation, SurvivalSurvey, CarbonValuation)
- **State machines:** 13 machines, 72 transitions — cyclic loops on prescription revision, ticket dispute, contract default/cure, bond claim denial, sale reoffer, obligation replant
- **Calculations:** 12 (incl. 3 dual-variant pairs across cruise/scaling/payment domains; combinatorial modes (a) bond tiering+surcharge, (b) per-ticket-round-then-sum, (c) fee tier keyed on cumulative gross with pinned evaluation order)
- **Endpoints:** 94 (incl. `POST /_clock/set_current_utc`, default 2026-05-01T00:00:00Z)
- **Errors:** 51, all referenced outside the catalog
- **Validations:** 37 ordered rows; **Concurrency (OCC):** 3 rules (certify-on-Stand, bid-on-Sale, valuation-on-Tract), all 412/`ERR_STALE_VERSION` with `${var}`-only version payloads
- **§1.8 difficulty instances:** 21 (all 9 rules, ≥2 each)
- **§1.9 corner instances:** 53 active + 3 `excluded_because` stubs (entities 7, endpoints 2, state_machines 10, calculations 6, validations 16, rbac 5, cross_cutting 3 OCC, consistency 1)
- **Lint:** `VERDICT: clean lint` — 1499 §1.8/§1.9 calls scanned, all conform to §1.5; all §1.1 FKs reverse-reachable

## Coverage notes
- All formula-derived asserts are precomputed literals (verified via Decimal math): cruise 306250/300125 bf at 2.00% sampling error; Doyle 100 vs International 123 bf/log; settlement rounding 9112 vs 9111; bond tiers 800000/945394/1050438/1200000/2800000; lump milestones 3600000/3600000/1800001; interest 0/1383/2767 at 29/30/61 days; carbon NPVs 37386631/28039973; waterfall 250000+300000+395394+0 == 945394
- Boundary precision exercised at the exact 110% overrun allowance (373758 bf accepted, +38 bf rejected), the empty-settlement sweep, and the exact 85.00% survival pass
- Two interval semantics: half-open prescription windows on Stand (adjacency allowed) vs closed enrollment windows on ForestTract (touching conflicts)
- Two transitive cascades: depth-3 inspection stop-work (inspection→contract→tickets→settlements) and depth-2 replant (survey→obligation→bond hold)
- One scaffold-level adjustment made mid-design: the stop-work cascade flags DRAFT *and* VERIFIED tickets so the settlement-void link is actually reachable (DRAFT settlements only ever hold VERIFIED tickets)

## Step 3: Copy Shared Files — 2026-08-11T20:10:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1200_timber_sale_forest_management_plan/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T20:35:00.000Z

(First subagent attempt died after reading inputs without writing output; re-spawned with persistence-first instruction. Verbatim summary from the successful run:)

The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1200_timber_sale_forest_management_plan/workspace/PRD.md` (384 lines).

**What was written**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications in 8 domain-flavored subsections: RBAC with per-role identity translation, the verbatim §2.2 response envelope (byte-identical copy of `section-2.2-response-structure.md`), pagination with all per-resource filter params, resource identity/versioning (including the four registry entities lacking `updated_at`/`version`), money/rounding/logical-clock rules (startup default 2026-05-01T00:00:00Z, `to_iso8601`, `current_utc`), the three OCC rules with exact error/HTTP status, the 9-layer validation pipeline, and left-to-right nested resolution with all 15 per-entity 404 ids
- §3 Business Logic in 9 subsections (parties/tracts → cruising → prescriptions → sale/bidding → contract/bond/default-cure → scaling/disputes/settlements → BMP stop-work → reforestation → carbon valuation), with all 14 state machines, 10 calculations (precise prose, no pseudocode), all 37 validations paired to their error ids, pinned check orderings (certify min-plots before sampling-error; offer's four gates; bid-create chain; close's three gates), and all cross-entity cascades (stop-work 3-link cascade, award/accept/supersede cascades, ledger movements, bond waterfall)
- §4 Endpoint table: all 94 endpoints, 4 columns only
- §5 Error catalogue: all 51 error ids with HTTP statuses, no trigger conditions

**Hard-contract check results (scripted against the scaffold, fenced JSON stripped before tokenization)**
- Contract 1 field coverage: 135 required identifiers (entity fields + endpoint inputs + query/path params + common fields + OCC fields), 0 missing — PASS
- Contract 2 rule coverage: all validations, concurrency rules, transitions/side effects, calculations, and endpoint side effects expressed in prose; all 51 error ids appear in §2/§3; all state/enum strings present — PASS
- Contract 3 §3 path purity: 585 backticked tokens scanned, 0 paths, 0 bare HTTP methods, 0 method+path combos — PASS

Note: the forbidden index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-11T20:55:00.000Z

**Files written:**

`test_helpers/` (9 files):
- `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`

`test_suite/` (13 files):
- `conftest.py`
- `test_01_registry_and_tracts.py` — party/tract creation, defaults, 404 family
- `test_02_rbac.py` — auth, role denials, ownership
- `test_03_cruise_volume_model.py` — cruise lifecycle, provisional vs certified volume, sampling-error / min-plots gates
- `test_04_prescription_lifecycle.py` — revision loop, half-open window overlap, foreign-landowner denial
- `test_05_sale_and_bidding.py` — sale-offer gates, bid book (supersede / tiebreak / no-sale / reoffer / withdraw / award-gate), pagination, list filters
- `test_06_bond_and_award.py` — performance-bond tiering with default surcharge, exact-amount bond gate
- `test_07_scale_tickets.py` — Doyle vs International dual variant, overrun allowance boundary, dispute loop, segregation of duties, contract-state gating
- `test_08_settlements.py` — per-ticket rounding order, cumulative fee tiering, milestone sequence, empty-period and overlap rejections, late interest, disburse/refund conservation
- `test_09_contracts_and_cascades.py` — default/cure, cure-period expiry, stop-work depth-3 cascade, safety-beats-temporal ordering, forfeiture waterfall conservation
- `test_10_reforestation.py` — survival ≥85 PASS, replant loop with bond-hold recompute, survey void compensation, deadline and growing-season gates, holdback / bond-release / close gating
- `test_11_carbon_and_occ.py` — NPV variants + recommendation, closed-interval enrollment conflict, active-contract block, and the three OCC stale-version paths
- `test_12_sale_validations.py` — expired cruise, bid window boundaries, species-rate floor, species-rate missing, stand mismatch, plus a second settlement-empty and lump-sum divergence test

**Coverage:**
- 93 test functions total, each carrying exactly one `Design:` tag as its docstring's last line.
- Difficulty queue (§1.8): 20 of 21 non-stub instances covered, each with ≥2 tests (verified by `grep | sort | uniq -c`).
- Corner queue (§1.9): all 53 non-stub instances covered with ≥1 test; the 3 `excluded_because:` stubs (`settlement_rounding_order_covered_by_difficulty`, `stop_work_cascade_covered_by_difficulty`, `dispute_cycle_covered_by_difficulty`) correctly NOT translated.

**Skipped instance (with reason):**
- `Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_ticket_create` — PRD §2.7 states that the relative order is given "in prose at the workflow itself" only for explicitly narrated pairs (it narrates cruise certify and start-harvest), but §3.6 does NOT pin the order between `ERR_CONTRACT_SUSPENDED` and `ERR_VOLUME_ALLOWANCE_EXCEEDED` for ticket-create. The two-reader test therefore fails — no verbatim PRD sentence uniquely derives `ERR_CONTRACT_SUSPENDED` over `ERR_VOLUME_ALLOWANCE_EXCEEDED`. Gap stays a gap.

**Self-check results:**
- `python3 -m py_compile test_helpers/*.py test_suite/*.py` — OK.
- All 93 Design tags resolve to real instances in the two design yamls.
- Spot-checked PRD verbatim citations (`Registering a timber buyer records…`, `Every tract begins life with…`, `Tickets may only be recorded against a contract that is…`, `landing exactly on the allowance is permitted`, `ERR_STALE_VERSION`, etc.) all grep verbatim against `workspace/PRD.md`.
- All `from test_helpers import …` names resolve.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere.

## Step 6: Generate Implementation — 2026-08-11T20:58:00.000Z

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1200_timber_sale_forest_management_plan/workspace/implementation/`):

- `start.sh` — foreground launcher; guarded `pip install` (no-op once Flask is importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask only
- `app.py` — Flask entry point, blueprint registration, envelope-wrapped error handlers (ApiError/404/405/500)
- `core.py` — in-memory store (dicts keyed by id, **nothing seeded at boot**), logical clock (starts exactly `2026-05-01T00:00:00Z`, settable only via `POST /_clock/set_current_utc`, never wall-clock), response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta adds `limit`/`offset`/`total_count`/`has_more`), auth decorator (`X-User-ID`/`X-User-Role`, six declared roles), schema validators (unknown fields rejected, bool-rejecting int checks, strict date/datetime parsing), Decimal round-half-up/floor math, pagination (limit default 10, 1–100; offset default 0; sorted by `created_at` asc), per-entity 404 helpers, state-machine guard
- `routes_party.py`, `routes_tracts.py`, `routes_cruises.py`, `routes_prescriptions.py`, `routes_sales.py`, `routes_contracts.py`, `routes_tickets.py`, `routes_settlements.py`, `routes_inspections.py`, `routes_reforestation.py`, `routes_carbon.py`

**Endpoint count:** all 94 scaffold endpoints registered (verified by diffing Flask's url_map against `SCAFFOLD.yaml`; the only extra route is Flask's built-in `/static` GET). Orchestrator independently re-verified after Step 6: scaffold 94 route pairs, flask 94, missing 0, extra 0.

**Key behaviors implemented:** cruise volume model (provisional vs certified variants, population-stddev sampling error rounded to 2dp then applied, min-5-plots gate before sampling gate, stand OCC on certify with prior-cruise supersede), prescription revision loop + half-open window overlap, sale offer gates in PRD order (enrollment conflict → prescription approved → cruise certified → 24-month freshness), bid window/floor/OCC gating, per-species round-then-sum bid totals, tie-break evaluation (total desc, deposit desc, submitted_at asc, buyer created_at asc), award creating PENDING_BOND contracts with tiered bond calc (10/7/5% + 25%-per-default surcharge, 500k/10M clamp), stop-work cascade (MAJOR finding → suspend → flag DRAFT/VERIFIED tickets → void intersecting DRAFT settlements with ledger reversal), Doyle floor vs International round-half-up per-log-then-multiply, 110% overrun allowance, segregation of duties on verify, 10-day dispute window, PER_UNIT period sweep + half-open overlap + LUMP 40/40/remainder milestones in sequence, consulting-fee tiers keyed on tentative cumulative gross, holdback ledgers, on-read late interest (1.5% per whole 30 days, floor), default→cure→forfeit waterfall (250k admin fee first, remainder to buyer), reforestation planting/survey loop (85.00% pass threshold, replant hold 45k/acre), delinquency auto-claim, carbon NPV at 5%/20yr with conservation-premium recommendation, accept cascade (enroll tract + cancel open sales + withdraw bids).

**Notable decisions:** version increments follow the scaffold's explicit side-effect lists (e.g., contract bumps on verify/disburse/refund/void, not on dispute); terminal lockdown (`ERR_ALREADY_TERMINAL`) precedes invalid-transition but exempts a terminal from-state that the trigger legally uses (Settlement `PAID → REFUNDED`).

**Boot verification:** two end-to-end smoke suites passed (full LUMP_SUM lifecycle to CLOSED; PER_UNIT flow with disqualification, reoffer loop, forfeiture waterfall, replant loop, carbon cascade), plus three consecutive fresh-process boots each answering HTTP 200 — confirming clean per-test-server restarts.

## Step 7: Test/Fix Diagnostic Loop — 2026-08-11T21:15:00.000Z

### Iteration 1 — first 8-round sweep (baseline)
All 8 rounds: 87/93 passed, identical 6 failures per round (deterministic, not flaky).

Union of failures (6) and diagnoses:
1. `test_10::test_contract_close_blocked_by_unpaid_settlement` — NameError: `setup_per_unit_settlement_draft` not imported. TEST BUG (missing import).
2. `test_10::test_release_holdback_before_satisfaction_rejected` — same missing import. TEST BUG.
3. `test_12::test_lump_sum_milestone_gross_independent_of_delivered_volume` — NameError: `create_settlement_payload` not imported. TEST BUG.
4. `test_08::test_lump_milestone_sequence_and_completion_remainder` — 400 "LUMP_MILESTONE requires milestone and no period dates". TEST/FACTORY BUG: `create_settlement_payload` always injected `period_start/period_end`; a milestone settlement "instead carries a milestone" (PRD §3.6).
5. `test_08::test_lump_sum_vs_per_unit_settlement_divergence` — 400 "license_no already registered: F-100". TEST/FACTORY BUG: dual-scenario test builds two registries; forester `license_no` is unique per forester (PRD §3.1), and the factory used a fixed `F-100`. ALSO a latent second bug: its custom `harvest_window 2026-10-01..2027-03-01` + `clock_iso 2026-10-05` put start-harvest outside the default prescription window `[2026-06-01,2026-10-01)` -> ERR_SEASON_WINDOW_VIOLATION (PRD §3.5 start-harvest checks BOTH windows).
6. `test_11::test_conservation_enrollment_closed_interval_conflict` — test expected offering a sale on an ENROLLED_CONSERVATION tract to succeed (200). PRD §3.4 offer gate requires "the tract must still be OPEN; violation is ERR_CONSERVATION_ENROLLMENT_CONFLICT". TEST BUG (contradicts PRD): an enrolled tract refuses ALL offers regardless of window overlap, so the closed-interval boundary is not observable via offer outcome.

### Fixes applied (iteration 1)
- `test_helpers/factories.py`: (a) `create_forester_payload` default `license_no` now unique per call (counter suffix) — respects PRD forester-license uniqueness for multi-scenario tests; explicit overrides still win. (b) `create_settlement_payload` drops `period_start/period_end` when `kind == "LUMP_MILESTONE"` so the payload matches the PRD milestone shape.
- `test_suite/test_10_reforestation.py`: added `setup_per_unit_settlement_draft` import.
- `test_suite/test_12_sale_validations.py`: added `create_settlement_payload` import in the milestone test.
- `test_suite/test_08_settlements.py`: `test_lump_sum_vs_per_unit_settlement_divergence` LUMP leg now uses the default harvest window + start clock so start-harvest satisfies both the sale and prescription windows.
- `test_suite/test_11_carbon_and_occ.py`: `test_conservation_enrollment_closed_interval_conflict` now asserts BOTH the non-overlapping and the touching harvest-window offers on an enrolled tract fail with `ERR_CONSERVATION_ENROLLMENT_CONFLICT` (tract no longer OPEN), per PRD §3.4.

### Iteration 2 — second 8-round sweep (after logic fixes)
6/6 original failures fixed (0 logic failures). New transient infrastructure failures appeared under 8x host contention (shared 8-core host, load avg 4-8 from other tenants):
- 5x "API server ... could not be restarted" — per-test server boot exceeded the runner's hardcoded 15s restart-poll window under CPU starvation (normal boot ~0.6s; not a code bug).
- 1x `RemoteDisconnected: Remote end closed connection without response` on `test_carbon_accept_blocked_by_active_contract` (round 5 only) — root cause: runner restarts the server in `pytest_runtest_setup`, so the test body's first request reused the session-scoped `requests.Session()` pooled keep-alive connection to the just-killed prior server process; under load the dead-connection reset races the reused request.

### Fixes applied (iteration 2) — test-infrastructure robustness, no PRD/logic change
- `test_helpers/api_client.py`: set `api_client.session.headers["Connection"] = "close"` so every request opens a fresh connection to the currently-bound server, eliminating the stale keep-alive reuse race across per-test restarts.
- `workspace/implementation/start.sh`: dependency guard now probes flask via `importlib.util.find_spec` (0.018s) instead of a full `import flask` (0.214s), halving per-boot Flask-import CPU across the 744 boots/sweep. (An earlier one-time-sentinel variant was reverted: `pip install` fails here under PEP 668 externally-managed-environment, and `set -e` would abort boot.)

### Iteration 2 result — CLEAN
All 8 rounds: 93/93 passed. No logic failures, no transient infrastructure failures. The keep-alive fix eliminated the `RemoteDisconnected` class and the find_spec boot guard reduced per-boot CPU enough that no boot exceeded the 15s restart-poll window. EXIT criterion met (all 8 rounds passed == total).

## Step 7: Run Tests and Iterate — 2026-08-11T21:41:00.000Z

All 8 parallel rounds pass 93/93. The loop is complete. Here is the summary.

## Summary

**Iterations run:** 2 (each a full 8-round parallel sweep). Final result: **all 8 rounds 93/93 passed.**

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule; no test asserted scaffold-only or PRD-silent behavior, and none required weakening, skip, or xfail.

**Fixes applied to `test_helpers/`:**
- `factories.py` — `create_forester_payload`: default `license_no` is now unique per call (counter suffix). The dual-scenario test `test_lump_sum_vs_per_unit_settlement_divergence` builds two registries in one test, and PRD §3.1 makes forester `license_no` unique, so the fixed `F-100` collided (400). Explicit overrides still win.
- `factories.py` — `create_settlement_payload`: drops `period_start`/`period_end` when `kind == "LUMP_MILESTONE"`. PRD §3.6 says a milestone settlement "instead carries a `milestone`"; the factory was injecting period dates, which the implementation correctly rejected (400).
- `api_client.py` — set `api_client.session.headers["Connection"] = "close"`. The session-scoped `requests.Session()` pooled a keep-alive connection across tests; the runner restarts the server in `pytest_runtest_setup`, so a test's first request could reuse a stale connection to the just-killed server, surfacing as `RemoteDisconnected`. Fresh connection per request eliminates the race.

**Fixes applied to `test_suite/`:**
- `test_10_reforestation.py` — added missing `setup_per_unit_settlement_draft` import (fixed two `NameError`s).
- `test_12_sale_validations.py` — added missing `create_settlement_payload` import (fixed a `NameError`).
- `test_08_settlements.py` — `test_lump_sum_vs_per_unit_settlement_divergence` LUMP leg now uses the default harvest window + start clock. Its custom `harvest_window 2026-10-01..2027-03-01` + `clock_iso 2026-10-05` put start-harvest outside the default prescription window `[2026-06-01,2026-10-01)`, which PRD §3.5's start-harvest gate (both windows) forbids.
- `test_11_carbon_and_occ.py` — `test_conservation_enrollment_closed_interval_conflict`: changed the non-overlapping sale's offer expectation from success (200) to `ERR_CONSERVATION_ENROLLMENT_CONFLICT`. The test contradicted PRD §3.4 ("the tract must still be `OPEN`; violation is `ERR_CONSERVATION_ENROLLMENT_CONFLICT`") — an enrolled tract refuses all offers regardless of window overlap, so the closed-interval boundary is not observable via offer outcome.

**Fixes applied to `implementation/`:**
- `start.sh` — dependency guard now probes via `importlib.util.find_spec('flask')` (0.018s) instead of a full `import flask` (0.214s), halving per-boot Flask-import CPU across the 744 boots/sweep and removing the CPU contention that pushed some server boots past the runner's hardcoded 15s restart-poll window. (A one-time-sentinel variant was tried and reverted: `pip install` fails under PEP 668 externally-managed-environment, and `set -e` would have aborted boot.) No application logic changed.

**Key findings:** The 6 original failures were all test-side bugs (missing imports, factory payload shapes, a dual-scenario license collision, a window-incompatible fixture, and one PRD-contradicting assertion). The second sweep's residual failures were purely environmental — server-boot timeouts and a keep-alive stale-connection race under 8x load on a shared 8-core host — resolved by test-infrastructure and boot-path hardening, with no weakening of any PRD-required check.

## Step 8: Finalize PRD — 2026-08-11T21:46:00.000Z

Done. `PRD_FINALIZED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1200_timber_sale_forest_management_plan/workspace/PRD_FINALIZED.md`.

## Line counts
- PRD.md: 384 lines; PRD_FINALIZED.md: 384 lines (single-line §3.6 paragraph grew in place; 0% line-count delta, one paragraph revised).

## Changes (1 total)
- **§3.6 — revise —** inserted one sentence pinning per-kind settlement payload exclusivity: a `PER_UNIT_PERIOD` settlement must carry `period_start`/`period_end` and no `milestone`; a `LUMP_MILESTONE` settlement must carry a `milestone` and no period dates; violations are `ERR_INVALID_REQUEST` (HTTP 400) — `implementation/routes_settlements.py:91-93` and `:133-134` (error constructor `core.py:30`, `bad_request` → `ERR_INVALID_REQUEST`/400).

## Items traced but requiring no edit (PRD already pinned or pure fixture/infra)
- `factories.py` forester `license_no` counter — pure fixture bug; PRD §3.1 already pins uniqueness, impl enforces at `routes_party.py:21-22`.
- `api_client.py` `Connection: close` — test-runner transport infra, no API behavior.
- test_10/test_12 import fixes — test bugs only.
- test_08 harvest-window/clock fix — PRD §3.5 already pins both windows as half-open gates; impl matches verbatim (`routes_contracts.py:154-162`).
- test_11 conservation-enrollment expectation — PRD §3.4 already pins "tract must still be `OPEN`"; impl `_enrollment_conflict` returns conflict for any non-OPEN tract regardless of window (`routes_sales.py:45-46`).
- `start.sh` `find_spec` probe — boot-time infra, no application logic.

## Per-edit pre-edit search log
**Edit 1 (§3.6 settlement payload exclusivity):**
- (a) Subject: settlement-creation request schema — which fields each `kind` requires/forbids, and the rejection error for mixing/omitting them.
- (b) Paths enumerated and read: `implementation/routes_settlements.py:68-164` (`create_settlement`, the only settlement-creation site; `check_known` at :75 admits all five fields so the rejections are kind-specific 400s, not unknown-field rejections; kind-mismatch 400 at :83-84; PER_UNIT_PERIOD field rule at :91-93; LUMP_MILESTONE field rule at :133-134); `implementation/core.py:30` (`bad_request` = `ERR_INVALID_REQUEST`/400); `implementation/routes_contracts.py:56-61` (stop-work cascade voids settlements — no payload involvement); `implementation/routes_contracts.py:297-302` (close gate iterates settlements — no payload involvement). No other code path creates settlements or interprets `period_start`/`period_end`/`milestone` on input.
- (c) Wording adjustment: initial draft covered only the LUMP_MILESTONE direction (the Step 7 site); widened to state both directions symmetrically because `routes_settlements.py:91-93` equally rejects a `PER_UNIT_PERIOD` payload carrying `milestone` or missing period dates — a one-sided sentence would have left the reverse rule falsely implied-asymmetric. Used "rejected as a malformed request" to align with §2.7 layer-5 phrasing.

## Step 9: Complete PRD — 2026-08-11T22:05:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1200_timber_sale_forest_management_plan/workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md`.

**File stats**
- Source: `workspace/PRD_FINALIZED.md` — 384 lines / 68,324 chars
- Result: `workspace/PRD_COMPLETED.md` — 384 lines / 74,355 chars (char-delta **+6,031**; 33 paragraphs touched, no sections added)

**Counts**: 49 ambiguity-pins, 9 mismatch-revisions (58 classified changes across 55 inline edits)

**Changes** (section — insert|revise — ambiguity|mismatch — what — impl ref):
- §2.2 — insert — ambiguity — `api_request_timestamp` stamped from the logical clock — core.py:93-94,176-194
- §2.3 — insert — ambiguity — malformed `limit`/`offset` is `ERR_INVALID_REQUEST` 400 — core.py:568-587
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion order — core.py:588
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — core.py:341
- §2.5 — insert — ambiguity — clock response echoes `to_iso8601` exactly as supplied — routes_party.py:79-82
- §2.7 — insert — ambiguity — terminal-state check fires before generic invalid-transition — core.py:602-613
- §3.1 — insert — ambiguity — duplicate forester `license_no` → `ERR_INVALID_REQUEST` 400 — routes_party.py:20-22
- §3.1 — insert — ambiguity — `landowner_id`/`forester_id` must name registered parties of their own kind — routes_tracts.py:34-37
- §3.1 — insert — ambiguity — oversized stand acres → `ERR_INVALID_REQUEST` 400 — routes_tracts.py:82-83
- §3.2 — insert — ambiguity — plot row types (`plot_number` integer, `volume_bf` number) — routes_cruises.py:25-35
- §3.2 — insert — ambiguity — finalize-tally with empty sheet → `ERR_INVALID_TRANSITION` 409 — routes_cruises.py:159-160
- §3.2 — insert — ambiguity — repeated reconciled plot numbers counted once per occurrence — routes_cruises.py:83,176-182
- §3.2 — insert — ambiguity — zero mean of reconciled totals → `sampling_error_pct` 0.00 — routes_cruises.py:86-87
- §3.2 — insert — ambiguity — `certified_volume_by_species` rendered as array of `{"species","volume_bf"}` sorted by species — routes_cruises.py:101-104
- §3.2 — revise — mismatch — superseded cruise's `version`/`updated_at` do not change — routes_cruises.py:224-233
- §3.4 — insert — ambiguity — `min_rate_cents_per_mbf` is a non-negative integer — routes_sales.py:30-39
- §3.4 — insert — ambiguity — cruise staleness only when clock strictly later than `certified_at`+24 months — routes_sales.py:182-185
- §3.4 — insert — ambiguity — `lump_sum_amount_cents` ≥ 0; `rate_cents_per_mbf` non-negative integer; extra species accepted, floor-exempt, excluded from total — routes_sales.py:387-392,405-410,416-422
- §3.4 — insert — ambiguity — unregistered acting buyer → `ERR_PARTY_NOT_FOUND` 404 before body validation — routes_sales.py:380-381
- §3.4 — revise — ambiguity — payload-shape check positioned after `BIDDING_OPEN` gate, before bid-window gate — routes_sales.py:393-410
- §3.4 — insert — ambiguity — advertised species absent from certified breakdown contributes volume zero — routes_sales.py:437
- §3.4 — revise — mismatch — superseded prior bid's version increments; new bid born at version 1 (not "both increment") — routes_sales.py:440-457
- §3.4 — insert — ambiguity — withdraw gates: sale not open → `ERR_SALE_NOT_OPEN_FOR_BIDDING`; at/past close → `ERR_BID_WINDOW_NOT_OPEN` — routes_sales.py:487-491
- §3.4 — insert — ambiguity — early close-bidding → `ERR_INVALID_TRANSITION` 409 — routes_sales.py:210-212
- §3.4 — insert — ambiguity — unresolved tie falls to earliest recorded bid — routes_sales.py:223-230
- §3.4 — insert — ambiguity — unknown award `bid_id` → `ERR_BID_NOT_FOUND` before state check — routes_sales.py:242-248
- §3.4 — insert — ambiguity — award response is HTTP 200 carrying the updated sale — routes_sales.py:282
- §3.4 — insert — ambiguity — no-sale while a winner exists → `ERR_INVALID_TRANSITION` 409 — routes_sales.py:292-294
- §3.5 — insert — ambiguity — `cumulative_verified_bf`/`verified_volume_by_species` (shape pinned)/`open_major_findings_count` are derived on read — core.py:519-541
- §3.5 — insert — ambiguity — bond posting responds 201 with the created bond — routes_contracts.py:113
- §3.5 — insert — ambiguity — reforestation-hold per-acre product rounded half up — routes_contracts.py:29-30
- §3.5 — insert — ambiguity — start-harvest prescription gate is `ERR_PRESCRIPTION_NOT_APPROVED`, evaluated after window checks — routes_contracts.py:163-165
- §3.5 — insert — mismatch — suspend flagging does not increment ticket versions — routes_contracts.py:49-54
- §3.5 — insert — ambiguity — contract version increments once for suspension plus once per cascade-voided settlement — routes_contracts.py:44-59
- §3.5 — revise — mismatch — declare-default `reason` validated but not persisted — routes_contracts.py:230-231
- §3.5 — insert — ambiguity — cure with bond not `FORFEIT_CLAIMED` → `ERR_INVALID_TRANSITION` — routes_contracts.py:257-260
- §3.5 — insert — ambiguity — terminate with bond not `FORFEITED` → `ERR_INVALID_TRANSITION` — routes_contracts.py:275-278
- §3.5 — insert — ambiguity — adjudicate figures are non-negative integers defaulting to zero — routes_contracts.py:364-367
- §3.5 — insert — ambiguity — bond release with contract not `HARVEST_COMPLETE`/`CLOSED` → `ERR_INVALID_TRANSITION` — routes_contracts.py:396-398
- §3.5 — insert — mismatch — holdback release does not increment the contract's version — routes_contracts.py:311-323
- §3.6 — insert — ambiguity — species absent from certified breakdown has allowance zero — routes_tickets.py:68-69
- §3.6 — insert — ambiguity — verify gate order: state → contract-state → segregation — routes_tickets.py:120-127
- §3.6 — insert — ambiguity — dispute window compared on instants; exactly 10 days after still admissible — routes_tickets.py:155-156
- §3.6 — revise — mismatch — dispute `reason` validated (before ownership) but not persisted — routes_tickets.py:141-153
- §3.6 — insert — ambiguity — dispute/resolve do not increment the contract's version — routes_tickets.py:159-174
- §3.6 — insert — ambiguity — settlement kind mismatch → `ERR_INVALID_REQUEST` 400 — routes_settlements.py:83-84
- §3.6 — insert — ambiguity — `ticket_ids` ordered by ticket creation; species unpriced by winning bid contributes zero — routes_settlements.py:121-130
- §3.6 — revise — ambiguity — milestone order/repeat and gates → `ERR_INVALID_TRANSITION`; voided milestone frees its slot; midpoint gated on volume alone (no `HARVESTING` requirement) — routes_settlements.py:135-158
- §3.6 — insert — mismatch — settlement creation moves contract ledgers without incrementing contract version — routes_settlements.py:184-186
- §3.6 — insert — ambiguity — `accrued_interest_cents` present on every read, 0 when not `APPROVED` — core.py:544-556
- §3.7 — insert — ambiguity — missing/extra `severity` → `ERR_INVALID_REQUEST`; remediation is non-negative integer; `COMPLIANT` close ignores supplied remediation/findings — routes_inspections.py:81-95
- §3.8 — insert — ambiguity — `seedlings_planted` is zero or more — routes_reforestation.py:58
- §3.8 — insert — ambiguity — finalize gates (obligation `SURVEYED`, planted > 0) → `ERR_INVALID_TRANSITION` — routes_reforestation.py:144-150
- §3.8 — insert — ambiguity — FAIL hold recompute applies to any existing bond regardless of bond status — routes_reforestation.py:167-175
- §3.8 — insert — mismatch — survey void returns obligation to `PLANTED` without version increment — routes_reforestation.py:185-191
- §3.8 — insert — ambiguity — early declare-delinquent → `ERR_INVALID_TRANSITION`; `DELINQUENT` has no exit and is not terminal — routes_reforestation.py:20,77-80
- §3.9 — insert — ambiguity — Feb 29 `enrollment_start` yields Feb 28 `enrollment_end` — core.py:141-145, routes_carbon.py:70-71
- §3.9 — revise — mismatch — superseded valuation's version increments; new valuation born at version 1 (not "both increment") — routes_carbon.py:72-91

No new sections were added; every change is an in-paragraph insert or revision. Endpoint table (§4) and error catalogue (§5) needed no changes — all impl routes and error codes matched them.

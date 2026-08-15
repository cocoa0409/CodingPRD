# Worklog — task_1780_industrial_gearbox_remanufacturing

## Step 1: Create Task Directory — 2026-08-14T15:34:00.000Z

Pre-assigned task directory `tasks/task_1780_industrial_gearbox_remanufacturing/` with `workspace/` subdirectory already created; treated as DONE per pipeline instructions.

## Step 2: Generate Scaffold — 2026-08-14T16:18:30.000Z

All three scaffold artifacts are generated and lint-clean. Summary:

## Deliverables

All three files written to `/home/ubuntu/github/CodingPRD/tasks/task_1780_industrial_gearbox_remanufacturing/`:

- **SCAFFOLD.yaml** (§1.0–§1.7, no difficulty/corner keys): 11 entities (Customer, GearUnit, RemanOrder, TeardownFinding, ComponentDecision, AssemblyRecord, RunInTest, LoanerUnit, LoanerAssignment, FreightShipment, WarrantyClaim), 51 endpoints, 26 error codes, 8 calculations, 9-priority validation table, 5 roles (4 opaque staff roles + entity-backed Customer), 2 OCC concurrency rules (revise-scope, loaner-return).
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (`scaffold_difficulty_design:` single top key): all 9 rules × 2 instances = 18 instances.
- **SCAFFOLD_CORNER_DESIGN.yaml** (`scaffold_corner_design:` single top key): 42 instances across entities / state_machines / calculations / validations / endpoints / errors / roles / cross_cutting_layers / consistency_model sections.

## Design highlights

- **Archetype**: workflow orchestration (11-state RemanOrder pipeline) + compliance/audit secondary; Advanced band.
- **Key mechanics**: provisional-vs-final pricing on orders (500000 quoted vs 746300 invoiced), hours-vs-calendar warranty eligibility variants, per-line-round-then-sum pinning (34001 vs 34000 counterexample), tiered rush labor rates (565375 vs 542300), SCOPE_APPROVAL self-loop revision cycle, GearUnit parallel physical×commercial state dimensions, run-in FAIL 3-hop cascade (order regression → assembly invalidation → submit-assembly gate), order-cancel → loaner-window-freeing 2-hop cascade, half-open loaner windows vs buffer-tailed rigging-bay occupancy, loaner availability and customer credit compensating invariants.
- **All arithmetic literals pre-computed** by executing the formulas (scope 588300, 22000, 17000, 22653; freight 158000/213000/139000/157000/83000; invoice 746300; warranty boundaries 2000/2001).

## Verification

- `scaffold_lint.py` verdict: **clean lint** — 685 calls scanned across §1.8+§1.9, all conform to §1.5; all 10 FKs reverse-reachable.
- Independent replay audit (scripted): every `approve-scope` chain lands in SCOPE_APPROVAL (fixed an auto-approval trap where estimate ≥ scope would have bypassed the approval step in 22 chains); all `${var}` placeholders bound by earlier `captures:`; instance names unique across both files (58 total); every error code in the catalog is exercised by at least one test instance; forbidden concurrency vocabulary scan clean.

Notable fixes during generation: renamed nested-GET parent placeholders to `{id}` (lint check (f) requirement), added `GET /reman/loaner-assignments?reman_order_id` for the LoanerAssignment→RemanOrder FK, removed unreachable ERR_NO_BASELINE and dead enum values (GearUnit.LOANED_OUT, LoanerUnit.IN_SERVICE), made per-component supersede explicit at decision-POST time, and pinned `completed_at_hours`/`completed_at_utc` snapshots on RemanOrder as the warranty clock basis.

## Step 3: Copy Shared Files — 2026-08-14T16:19:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1780_industrial_gearbox_remanufacturing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T16:40:00.000Z

All checks pass. The earlier "missing" report was an artifact of my extraction script (the verbatim §2.2 JSON fences flipped backtick pairing for the full-document scan); with fenced blocks stripped, coverage is complete.

**Done.** Generated `/home/ubuntu/github/CodingPRD/tasks/task_1780_industrial_gearbox_remanufacturing/workspace/PRD.md` from the scaffold (the two DESIGN index files were not opened or consulted).

**Document shape** (skeleton designed fresh for this domain, not copied from the example):
- §1: two-paragraph introduction (business context + the three governing tensions).
- §2: 11 subsections — RBAC with per-role identity translation (four opaque roles; `Customer` entity-backed with ownership-chain prose), verbatim §2.2 envelope block, pagination (limit 10/1/100, offset 0, `created_at` ascending), common resource properties with the append-only `TeardownFinding` exception called out, left-to-right nested retrieval, state legality/terminal lockdown, OCC, the logical clock (default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`), integer-cents/per-line round-half-up precision, the credit-exposure ledger (six contributing statuses, strictly-greater hold rule, completion as the only debit point), and the 9-level validation priority order with masking semantics.
- §3: seven lifecycle-grouped subsections with scattering (rush flag in 3.2 vs its 1.25 multiplier effect in 3.3; oil baseline created in 3.4 vs consumed by warranty in 3.7; freight pricing in 3.5 vs invoice inclusion in 3.4); all transitions named as state pairs; no paths or HTTP methods.
- §4: 51-row endpoint table (Method/Path/Description/Authorized Role only; "All roles" defined above the table, with role-restricted rows listed explicitly).
- §5: 26-error, 2-column catalogue; trigger conditions live only in §2/§3 prose.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 54 required, 54 present, 0 missing
- endpoints[].request_body/input: 36 required, 36 present, 0 missing
- endpoints[].query_params: 0 required, 0 present (optional reman_order_id filter arrived via input list; present)
- path params: 8 required, 8 present (via §4 table paths)
Status: PASS

Rule coverage check:
- validations[] with priority: 9 checked, 9 expressed as an ordered list with masking, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (revise-scope + expected_order_version; loaner return + expected_assignment_version; both with ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 28 checked (13 RemanOrder, 6 GearUnit, 3 LoanerAssignment, 3 FreightShipment, 3 WarrantyClaim), 28 fully expressed with preconditions, error ids, and side effects, 0 missing
- calculations[]: 8 checked (line total, scope total, final invoice, freight, warranty dual-basis, run-in, assembly tolerance, credit hold), 8 fully expressed with constants embedded (8500/14200/6000/2500, 1.25, 45000/120000/18000-per-started-500kg, 9500, 2h buffer, 2000h/365d hours-before-calendar, 120min/95.0/4.5/3200, 0.08–0.18/0.05), 0 missing
- validations[] conditions: 26 error ids checked, 26 matchable in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (supersede-on-repost, no-recompute-at-decision-time, max-odometer, completion cascade, no-cascade delivery note, ship guards, claim null-eligibility, etc.), 0 missing
- entities[].fields[] structured content: defaults/nulls/enums/types reconstructible (rush=false, outstanding=0, credit_hold=false, approved_scope=0, completion snapshots unset, eligibility null until COMPLETED, severity 1–5, recorded_by=X-User-ID, TeardownFinding id+created_at only), 0 missing
- sibling-branch symmetry: 6 groups checked (PASS/FAIL, auto-approve vs customer-approve, four action tiers, three freight tiers, approve/deny, two cancel paths), 6 with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 291
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All enum/state strings (43 values) verified present exactly, and every error id appears in §2/§3 narrative.

## Step 5: Generate Unit Tests — 2026-08-14T17:05:00.000Z

Generated `test_helpers/` (9 modules) and `test_suite/` (conftest + 9 test files, 79 tests) per the prd-bench-unit-test-generator skill, translating the two design indices only.

**Coverage audit (scripted):** all 18 §1.8 difficulty instances carry ≥2 tests (one has 3) tagged `Design: Difficulty/<rule_id>/<instance.name>`; all 42 §1.9 corner instances carry ≥1 test tagged `Design: Corner/<section>/<instance.name>`; no `excluded_because:` stubs exist in the corner index; no orphan tags; no skip/xfail markers; pyflakes clean; pytest collects 79 tests.

**PRD-citation sweep (scripted):** every test docstring carries a rule-bearing verbatim PRD quote (≥8-word substring verified present in workspace/PRD.md, modulo whitespace). One docstring initially cited §4's endpoint table alone (endpoint-titular, C2 violation) and was rewritten to quote the §3.7 adjudication sentence; one quote was extended to the full PRD sentence (C3).

**PRD-first adjudications:** the corner instance asserting `version == 1` at creation was translated with type/presence assertions only — PRD §2.4 says version "starts on creation and increments by one with every mutation" without pinning the initial value, so two faithful readers could ship 0- or 1-based counters. Second-per-instance difficulty tests were built as same-claim variants (rush premium on a second action tier, a second round-half-up witness pair, mirror EXPIRED_HOURS vs EXPIRED_CALENDAR legs, recovery after the run-in FAIL cascade, adjacency on both sides of an existing loaner window, auto-approval credit conservation, next-day rigging bay acceptance).

## Step 6: Generate Implementation — 2026-08-14T17:10:00.000Z

Done. The implementation is complete and passes the full benchmark suite.

## What was built

A complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1780_industrial_gearbox_remanufacturing/workspace/implementation/`:

- **`start.sh`** — executable foreground launcher; guards the pip install behind `python3 -c "import flask"` so per-test reboots are no-ops, then `exec python3 app.py` on `0.0.0.0:$PORT` (default 10000)
- **`app.py`** — entry point, global RLock (thread-safe in-memory store), envelope-shaped 404/405/exception handlers
- **`db.py`** — empty-on-boot in-memory store (no seeding), the shop logical clock (default exactly `2026-08-01T00:00:00Z`), strictly logical-clock-derived timestamps
- **`response.py` / `errors.py` / `middleware.py` / `validation.py`** — the `meta`/`response_type`/`data` envelope with `limit`/`offset`/`total_count`/`has_more` pagination, the PRD §5 error catalog, `X-User-Role` auth (401) + role gating (403) + entity-backed Customer ownership, and typed body validation (400)
- **`routes/`** — customers, units, orders (lifecycle + findings + decisions + scope submit/revise/approve + ship/complete/cancel), quality (assembly records, submit-assembly, run-in tests), loaners, shipments, warranty, and the `_clock` endpoint
- **`services/`** — Decimal `ROUND_HALF_UP` per-line pricing (tiered labor rates × rush 1.25 + material), tiered freight with `ceil` overweight blocks and rigging-hour surcharges, tolerance/run-in thresholds, the customer credit ledger (strict `>` hold, single debit at completion), half-open loaner-window and rigging-bay-buffer overlap math, and dual-basis warranty eligibility (hours leg before calendar leg)

## Verification

- The task's generated test suite exists at `tasks/task_1780_industrial_gearbox_remanufacturing/test_suite/`. I ran it twice under the exact benchmark conditions:
  ```
  prd-bench-local-run --start-command "cd .../workspace/implementation && bash start.sh" \
      --test-dir test_suite --isolation per-test-server
  ```
  **Both runs: 79/79 passed, 0 failed, 0 errors** (~105s each; server restarted via `start.sh` before every test).
- One environment note: the runner's per-test restart re-parses `--start-command`, so an absolute `cd <dir> && bash start.sh` form is required when invoking manually (a relative path failed the restart spawn). `start.sh` itself self-locates via `cd "$(dirname "$0")"`, so the evaluator's `bash start.sh` contract from `./implementation/` is unaffected.
- I also independently exercised the pinned edge cases beyond the suite: per-line-vs-sum rounding (11348+22653=34001), rush labor-only premium (565375), OCC stale-version on both guarded writes, run-in FAIL depth-3 cascade, order-cancel loaner cascade, half-open adjacency vs rigging-buffer conflict, exact-credit-limit boundary, and clock-travel calendar expiry (`EXPIRED_CALENDAR` with covered hours leg).

One design-doc discrepancy worth noting: `SCAFFOLD_DIFFICULTY_DESIGN.yaml`'s revision-loop/OCC instances pair `quoted_estimate_cents: 100000` with a 46000-cent scope yet expect `SCOPE_APPROVAL`, contradicting the PRD's auto-approve rule (scope ≤ estimate → `APPROVED`). I followed the PRD; the generated test fixtures confirm that choice (they use estimate 10000 to reach `SCOPE_APPROVAL`).

## Step 7: Run Tests and Iterate — 2026-08-14T17:15:00.000Z

Clean 8-round sweep on the first iteration. Exiting per protocol.

## Summary

- **Iterations run:** 1 (single 8-round parallel sweep, `--isolation per-test-server`, 79 tests per round).
- **Result:** All 8 rounds report `passed == total == 79`, with `failed=0`, `errors=0`, `skipped=0` and zero non-passing tests in every round. No flakiness surfaced under 8× concurrency.
- **Tests deleted:** none — every assertion traces to verbatim PRD prose (each test docstring carries the exact PRD § quote it asserts), so STEP 1 deletion criteria were never triggered.
- **Fixes applied to `test_helpers/`:** none — fixtures/factories/role-header builders are PRD-faithful (entity-backed Customer headers via `make_customer_headers(customer_id)` for ownership-gated calls; opaque shared constants only for non-ownership paths).
- **Fixes applied to `implementation/`:** none — the implementation in `/home/ubuntu/github/CodingPRD/tasks/task_1780_industrial_gearbox_remanufacturing/workspace/implementation/` already conforms: in-memory-only store with empty boot state, logical clock defaulting to `2026-08-01T00:00:00Z`, per-line half-up rounding in `services/pricing.py`, correct credit ledger (sum over `APPROVED…SHIPPED`, strict-greater hold rule, completion-only debit), OCC on revise-scope and loaner-return, terminal lockdowns, and the §2.11 validation priority order.

## Step 8: Finalize PRD — 2026-08-14T17:15:30.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — `PRD.md` already determined every behavior the implementation exhibits.

## Step 9: Complete PRD — 2026-08-14T17:35:00.000Z

All edits applied cleanly. Final verification of the counts:

- **Source**: `PRD.md` (no `PRD_FINALIZED.md` present) — 294 lines / 40,670 chars
- **Produced**: `/home/ubuntu/github/CodingPRD/tasks/task_1780_industrial_gearbox_remanufacturing/workspace/PRD_COMPLETED.md` — 297 lines / 43,852 chars
- **Delta**: +3 lines, +3,182 chars. 18 changes: 14 ambiguity-pins, 4 mismatch-revisions.

## Change log

- §2.1 — insert — ambiguity — Missing `X-User-ID` is not itself an authentication failure (only the role header gates auth; for staff it is recorded as null, for Customer it merely fails ownership) — `implementation/middleware.py:25-32`
- §2.3 — insert — ambiguity — `limit`/`offset` are clamped to bounds (non-numeric falls back to defaults) rather than rejected; `created_at` ties break by creation sequence — `implementation/response.py:67-78,88`
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — `implementation/db.py:78`
- §2.4 — insert — ambiguity — Undeclared body fields rejected with `ERR_INVALID_REQUEST`; no-field action endpoints reject a body carrying fields, except unit check-in and scrap which ignore the body entirely — `implementation/validation.py:68-70,102-108`; `implementation/routes/units.py:45-75`
- §2.6 — insert — mismatch — Carve-out to the "locked against any further action" blanket: a `COMPLETED` order still accepts warranty claims, a `CANCELLED` order accepts none — `implementation/routes/warranty.py:36-38,56-60`
- §2.7 — revise — mismatch — Revise-scope OCC rejects *any* version mismatch (`!=`), not only a version that "has advanced beyond" the expected value — `implementation/routes/orders.py:199`
- §2.7 — insert — ambiguity — Expected-version fields accept a JSON integer or a decimal digit string — `implementation/validation.py:45-49`
- §2.8 — revise — ambiguity (plus wording mismatch "advances"→"sets") — Clock-set accepts any valid timestamp incl. earlier ones; the logical clock also sources `created_at`, `updated_at`, and `meta.api_request_timestamp`; `current_utc`/`completed_at_utc` drop the fractional part when zero — `implementation/routes/misc.py:13-19`; `implementation/db.py:46-64`; `implementation/response.py:15`
- §2.11 — insert — ambiguity — Body-shape validation sits between existence and state legality; the OCC check sits between state legality and referential completeness — `implementation/routes/orders.py:195-208`; `implementation/routes/loaners.py:132-141`
- §3.1 — revise — ambiguity — Service-hour readings accepted in any physical state except `SCRAPPED` (not only "while in service") — `implementation/routes/units.py:34-36`
- §3.2 — insert — ambiguity — `labor_hours` is a JSON number (fractional hours accepted); `material_cents` integer cents — `implementation/routes/orders.py:112-113`
- §3.3 — insert — ambiguity — Each role's cancel exists only from its own state (coordinator in SCOPE_APPROVAL or customer in INTAKE → `ERR_INVALID_STATE`) — `implementation/routes/orders.py:337-356`
- §3.4 — insert — ambiguity — Run-in test recordable only while the order stands `RUN_IN` — `implementation/routes/quality.py:95`
- §3.4 — revise — mismatch — On FAIL, *every* currently `ACTIVE` assembly record (not "the" one) flips to `INVALIDATED` — `implementation/routes/quality.py:128-131`
- §3.5 — insert — ambiguity — Shipment booking allowed in any non-terminal order state; only `COMPLETED`/`CANCELLED` orders reject with `ERR_INVALID_STATE` — `implementation/routes/shipments.py:41-44`
- §3.5 — revise — ambiguity — Ship moves *every* still-`BOOKED` outbound shipment to `IN_TRANSIT`; complete requires *an* outbound shipment `DELIVERED` (any one suffices) — `implementation/routes/orders.py:290-292,303-304`
- §3.6 — insert — ambiguity — Reservation: unknown `reman_order_id` → `ERR_NOT_FOUND`; referenced order's status unconstrained; loaner availability not consulted until checkout — `implementation/routes/loaners.py:60-66`
- §3.6 — insert — ambiguity — Extend: `new_end_date` must be strictly after `start_date` (`ERR_INVALID_WINDOW`) but may be earlier than the current `end_date`; overlap re-validated with the assignment itself excluded — `implementation/routes/loaners.py:160-170`
- §4 — insert (table row) — mismatch — Added missing endpoint row `POST /reman/loaner-assignments/{assignmentId}/cancel` (IntakeCoordinator) — `implementation/routes/loaners.py:174-185`

No new sections added; all changes are inline inserts/revisions or one table row. Everything else in the implementation (all 52 routes, envelope shape, pricing/freight/tolerance/run-in formulas, credit ledger, state machines, error catalogue, RBAC table) was already uniquely pinned by the PRD and left untouched.

# Worklog — task_0496_water_softener_service

## Step 1: Create Task Directory — 2026-06-25T11:42:14.000Z

Created `tasks/task_0496_water_softener_service/` and `tasks/task_0496_water_softener_service/workspace/` using the pre-allocated task_dir (auto ID scan skipped per instruction to avoid concurrent ID contention).

## Step 2: Generate Scaffold — 2026-06-25T11:59:00.000Z

Generated three scaffold artifacts for **task_0496_water_softener_service** at **Expert** difficulty, working purely from the scenario and the scaffold-generator spec (no sibling tasks consulted). All files pass `scaffold_lint.py` with `VERDICT: clean lint`.

**Files written**:
- `SCAFFOLD.yaml` — §1.0–§1.7 (1782 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8 (single key `scaffold_difficulty_design`, 1260 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` — §1.9 (single key `scaffold_corner_design`, 1893 lines)

**Complexity profile**: Workflow-orchestration × Temporal-windowing, flat topology, parallel state-machine shape, peer_roles, immediate consistency. Layers: dual-variant calculation, scheduled/deferred actions (logical clock, default `2026-01-01T00:00:00Z`), cascading side effects, rate/threshold triggers, optimistic concurrency.

**Entities (12)**: ServiceAccount, WaterTest, SoftenerSystem, RentalContract, Route, RouteStop, CartridgeSchedule, ServiceVisit, WarrantyClaim, Invoice, Customer, FieldTech — 17 FKs (incl. self-referential `Invoice.supersedes_invoice_id`), all reverse-reachable.

**State machines (9, non-linear shapes)**: SoftenerSystem (parallel: `lifecycle_status` × `regen_health`), RentalContract (cyclic ACTIVE↔SUSPENDED→TERMINATED, OCC-guarded), WarrantyClaim (branching fork-join TRIAGED→{REPAIR,REPLACE,DENIED}→CLOSED), plus WaterTest, Route, RouteStop, CartridgeSchedule, ServiceVisit, Invoice. One OCC concurrency rule (terminate-stale-contract, 412).

**Calculations (7)**: `size_grain_capacity` (tank sizing w/ iron inflation), `regen_demand` (gallons threshold), `rental_proration` (dual-variant full-cycle vs daily, round-then-multiply pinned), `early_termination_fee` (tiered + cap), `coverage_window` (warranty), `claim_settlement` (age-goodwill), `apply_invoice` (ledger floor-at-0). All literals computed in code and pinned as literals in asserts.

**Other**: 16 validations (priority-ordered, 8 categories), 63 endpoints, 16 errors, 5 roles (ServiceManager superset, FieldTech/Customer entity-backed, Dispatcher/BillingClerk opaque).

**Coverage counts**:
- §1.8: all 9 Difficulty Rules × 2 = **18 instances**.
- §1.9: **39 active corner instances + 3 excluded stubs** across all 9 claim-extraction sections.
- 60 instance names total, all unique; all `grounds` resolve; every enum status value is produced by a transition; no forbidden concurrency vocabulary; 531 setup/trigger calls all conform to §1.5.

## Step 3: Copy Shared Files — 2026-06-25T12:06:01.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0496_water_softener_service/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-25T12:12:14.000Z

Generated `workspace/PRD.md` — prose PRD for the Water Softener Service API. **293 lines, ~7,160 words.** Read SCAFFOLD.yaml only; both design-index files withheld.

Section structure: §1 Introduction (four-silo orchestration), §2 Global Specifications (10 subsections: RBAC 5 roles, response envelope, pagination, common properties, nested/reverse-reachability path validation, FK/request validation priority chain, parallel state dimensions + cascade/version semantics, integer-cents rounding, logical clock default `2026-01-01T00:00:00Z`, OCC), §3 Business Logic (11 lifecycle-grouped subsections), §4 67-endpoint routing table, §5 16-error table.

Coverage: all 12 entities, 64 required fields present (Contract 1 PASS), all 33 state values + parallel SoftenerSystem dimensions + cyclic rental machine + warranty fork-join, all 7 calculations reconstructible with constants embedded, single OCC rule fully expressed (ERR_STALE_VERSION/412), all 16 errors in narrative.

Hard contracts: Field coverage PASS (64/64), Rule coverage PASS (validations/OCC/state-machines/calculations/side-effects all expressed), Path purity PASS (388 backtick tokens, 0 path-like).

Note: scaffold references `RO_TDS_THRESHOLD` symbolically with no numeric value defined; PRD preserves `>=` direction/inclusivity without inventing a constant.

## Step 5: Generate Unit Tests — 2026-06-25T12:29:04.000Z

(launched concurrently with Step 6)

Test files emitted: 5 (`test_01_billing_calculations.py`, `test_02_state_machines.py`, `test_03_routes_and_regen.py`, `test_04_crud_validation_rbac.py`, `test_05_difficulty_reinforcement.py`) plus `conftest.py`. Test functions emitted: **73**, each carrying exactly one verbatim PRD citation and one `Design:` tag.

Queue A (Difficulty) — 18 instances: **17 translated** (2 tests each = 34 tests). **1 skipped:** `priority_pair_validation_conflict/route_stop_overlap_beats_route_full` — PRD §2.6 fixes ordering only through `ERR_INVALID_STATE` then an undifferentiated group; does NOT establish precedence between `ERR_WINDOW_OVERLAP` (p11) and `ERR_ROUTE_FULL` (p13) (not uniquely derivable). Sibling `install_state_beats_capacity_mismatch` kept (§2.6 explicitly places `ERR_INVALID_STATE` before business rules).

Queue B (Corner) — 42 instances: **39 non-stub all translated** (1 test each). **3 `excluded_because` stubs** correctly not translated; all 3 cross-references resolve to real translated difficulty instances.

test_helpers modules: `types.py`, `api_client.py` (63 endpoint methods), `api_errors.py` (16 errors), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque shared headers + per-instance FieldTech/Customer builders), `fixtures.py` (composite setup tiers), `__init__.py`. All 11 Python files byte-compile; all test modules import-resolve; every cited PRD phrase confirmed verbatim; no skip/xfail markers; every Design tag resolves with no dual-tags.

## Step 6: Generate Implementation — 2026-06-25T12:29:04.000Z

(launched concurrently with Step 5)

Built Python + Flask implementation at `workspace/implementation/`. Layout: `start.sh` (reads `$PORT` default 10000, binds `0.0.0.0`, foreground `exec python3 app.py`), `requirements.txt` (flask==3.0.3), `app.py` (routes + RBAC guard + pagination + invoice/proration), `auth.py`, `validate.py`, `calculations.py` (7 calc rules, Decimal/ROUND_HALF_UP), `constants.py`, `services.py`, `db.py` (in-memory store), `response.py` (exact envelope), `clock.py` (default `2026-01-01T00:00:00Z`), `errors.py`.

All 67 PRD endpoints implemented. Storage: in-memory dicts keyed by UUID + email-uniqueness index + monotonic sequence counter; no seeding, no disk; wiped every reboot (verified fresh boot returns empty lists + default clock).

Smoke-tested against design example math (proration 4500/2700, sizing 48000, RO 200→false/600→true, termination fee 18000, depth-3 cascade balance→0, OCC 412, visit void compensation, warranty 0/31500, route validations, regen DUE/OVERDUE + salt drawdown, cartridge DUE_SOON/OVERDUE, invoice DELINQUENT/GOOD cascade, double-void→ERR_INVOICE_CLOSED, validation precedence) — all passed.

Ambiguity notes: (1) `RO_TDS_THRESHOLD` no numeric value in PRD/SCAFFOLD; boundaries tds 200→false / 600→true admit any threshold in (200,600]; chose **500**. (2) Directly-issued SERVICE_REPAIR/TERMINATION invoices (non-cascade) have no formula; take optional `amount_cents` from body (default 0); cascade-created invoices compute from originating calc.

## Step 7: Run Tests and Iterate — 2026-06-25T12:40:00.000Z

**Iterations run:** 3 sweeps (1 diagnostic + 2 confirmation), 24 parallel rounds total.

**Initial state:** 73 tests. The first sweep showed 5 of 8 rounds at 72/73. The union of failures was a single test — `test_recommend_computes_capacity_server_side` — and it never failed on an assertion. Every failure was a setup-time `error`: "API server at http://localhost:NNNN could not be restarted before ...". Pure boot-latency flakiness: under `--isolation per-test-server`, `start.sh` restarts the server before each of 73 tests, and with 8 rounds running concurrently (~8× CPU contention) the runner's post-boot health check occasionally timed out before Flask was reachable. Which test caught it was incidental to load, not to logic.

**Tests deleted:** None. No test was PRD-silent or under-determined; the only failure was an infrastructure timing artifact, not a logic/coverage problem.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:**
- `workspace/implementation/start.sh` (boot path) — Replaced the unconditional per-boot `python3 -c "import flask"` dependency probe with a cached `.deps_ok` sentinel. The probe (a full extra interpreter spawn) was being paid on every one of ~73 reboots per round × 8 concurrent rounds; under 8× contention that doubled-spawn cost was the dominant boot overhead pushing the server past the runner's restart health-check window. Now the import probe (and install-on-missing) runs only on the first boot; every subsequent reboot skips straight to `exec python3 app.py`. The sentinel is a dependency marker only — it stores no entity data, so the in-memory/no-seeding contract is preserved. `app.py` already correctly read `$PORT`, bound `0.0.0.0`, and used `threaded=True`; no application logic changed.

**Result:** Two consecutive fully clean 8-round parallel sweeps (16 rounds, 73/73 passing in every round, 0 failures, 0 errors). The intermittent restart-timeout is resolved. (Orchestrator re-ran one additional confirming 8-round sweep — all 8 rounds 73/73, 0 failures, 0 errors — to leave the `results.{1..8}.json` artifacts in place.)

## Step 8: Finalize PRD — 2026-06-25T12:38:55.000Z

Step 8 ran because the lone Step 7 fix (1 `implementation/` fix) means the literal skip condition (all four fix categories = 0) was not met.

**Outcome: zero edits.** PRD_FINALIZED.md = verbatim copy of PRD.md (293 lines, 0% delta, `diff -q` IDENTICAL). The single `<step_7_diff>` item is the `start.sh` boot-path change (`start.sh:10-17`): replaced an unconditional per-boot `python3 -c "import flask"` probe with a cached `.deps_ok` sentinel; flask probe/install runs only on first boot, subsequent reboots `exec python3 app.py` directly. This is purely operational launcher/dependency-caching mechanics — PRD §2–§5 govern API behavior, RBAC, state machines, calculations, clock, errors, and describe nothing about server boot/dependency install. No PRD silence or mismatch; no application logic changed; `requirements.txt` unchanged; `db.py` still "Starts empty on every boot — NO seeding"; sentinel is an empty file storing no entity data (in-memory/no-seeding contract preserved). Verbatim-copy is the valid expected outcome; no edits invented to justify the step.

## Step 9: Complete PRD — 2026-06-25T12:43:56.000Z

Full PRD-vs-implementation/ scan (always runs). Source: PRD_FINALIZED.md (293 lines, 48,166 chars) → PRD_COMPLETED.md (293 lines, 48,981 chars, **+815 chars**, line count unchanged — all in-paragraph inserts/revisions, no new sections).

**Change counts: 7 total — 6 ambiguity-pins, 1 mismatch-revision.**

- §2.4 Common Resource Properties — insert — ambiguity — `version` initial value pinned to `1` — `db.py:54`
- §3.1 Accounts/Customers — insert — ambiguity — duplicate-`email` customer registration → `ERR_INVALID_REQUEST` — `app.py:106-107`
- §3.2 Recommendation — insert — ambiguity — RO threshold pinned to 500 ppm — `constants.py:12`
- §3.4 Stops (service-gap) — revise — ambiguity — gap check counts only `SCHEDULED`/`COMPLETED` peer stops, `SKIPPED` disregarded — `app.py:654-657`
- §3.4 Stops (FILTER_SWAP) — insert — ambiguity — "matching cartridge schedule" = first-in-creation-order regardless of type/status; no-schedule = no-op — `app.py:779-786`
- §3.10 Invoicing — insert — ambiguity — `RENTAL_CYCLE`/`PRORATION` require non-null `contract_id` (else `ERR_INVALID_REQUEST`); `SERVICE_REPAIR`/`TERMINATION` direct-issue amount from body `amount_cents` (non-negative int, default 0) — `app.py:1161-1174`
- §3.11 Logical clock — insert — ambiguity — clock-set returns data object carrying new value as `current_utc` — `app.py:1311`

Left unchanged: all stated calculation constants already match `constants.py`/`calculations.py` exactly (no mismatch revisions there). Deep cascade-only internals never claimed in PRD prose (auto-invoice `period_start`/`period_end`, auto-visit `gallons_treated_reading`=0) left unpinned per minimal-patch/never-invent constraint.

---

# PIPELINE COMPLETE

All 9 steps finished. Final state: **73/73 tests passing across 8/8 parallel rounds (0 failures, 0 errors)**. Artifacts present: SCAFFOLD.yaml + 2 design indices, test_helpers/ + test_suite/ (73 tests), workspace/implementation/ (Flask, in-memory, results.{1..8}.json all green), PRD.md → PRD_FINALIZED.md (0 edits) → PRD_COMPLETED.md (7 edits).

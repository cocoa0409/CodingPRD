# Worklog — task_0143_film_tv_production_scheduling

## Step 1: Create Task Directory — 2026-06-04T00:00:00.000Z

Task directory `tasks/task_0143_film_tv_production_scheduling/` confirmed (pre-created); `workspace/` subdirectory ensured. Scenario: Film/TV Production Scheduling (shooting schedule/stripboard, call sheet, SAG-AFTRA day rate/turnaround/meal penalty, location permit, budget vs actual, residual tracking, dailies, union fringe). Difficulty: Expert.

## Step 2: Generate Scaffold — 2026-06-04T00:00:00.000Z

All three files are correctly structured with the right top-level keys, file split honored, and lint is clean. There's a pre-existing `worklog.md` and empty `workspace/` in the directory (from the orchestrator), which I leave untouched.

The scaffold is complete and verified. Here is the summary.

## Summary

Generated three lint-clean scaffold files for **task_0143_film_tv_production_scheduling** under the requested directory. `scaffold_lint.py` returns `VERDICT: clean lint` (495 calls scanned across 18 §1.8 + 40 §1.9 instances; 0 violations; all 13 FKs reverse-reachable).

**Counts produced:**
- **Entities: 12** (Production, BudgetLine, ShootingDay, Scene, CrewMember, Assignment, CallSheet, Location, LocationPermit, ResidualEvent, UnionFringe, Dailies) — within the Expert 10-15 band.
- **Endpoints: 61** — above the nominal Expert 20-32 ceiling (see design note below).
- **Errors: 20** — within the 18-30 band; every error has at least one asserting test.
- **Calculation variants: 5 variant entries across 7 calculations** (3 calcs carry the multi-variant dual-interpretation logic the rules require: estimate-vs-actual, SAG-vs-non-SAG meal/turnaround, marginal-chronological residual) — meets "3+".
- **State machines: 6** (Production linear-guarded, ShootingDay branching, Assignment parallel two-axis, CallSheet cyclic, LocationPermit branching, Dailies cyclic) — exceeds "4+", with cycles and parallel dimensions present.
- Plus 2 concurrency rules (OCC on ShootingDay.version and Production.version).

**Design profile:** temporal_windowing primary / ledger_reconciliation secondary, flat topology (`api_prefix: ""`, top-level collections), parallel/cyclic state shape, peer_roles RBAC (LineProducer, FirstAD, PayrollCoordinator, PostSupervisor, UnionRep — all `opaque`).

All nine §0.5 difficulty rules have 2 differentiated instances (18 total); every assert with a formula-derived number was computed in code and pinned as a literal (verified twice — caught and fixed one error where a meal penalty of 6000 made the combinatorial actual cost 482000, not the 478500 I first wrote).

**Notable decisions / constraints resolved:**
1. **Endpoint overage (61 vs 32 ceiling):** kept intentionally. The count is driven by genuine scenario breadth (9 named sub-domains → 6 state machines → 24 action endpoints) plus the linter's FK-reverse-reachability requirement (each of 12 entities needs a GET-by-id for segment derivation and a filtered GET-list). Trimming would mean amputating scenario-named features (e.g., the dailies pipeline) rather than reducing real complexity. Consistent with the documented "Expert endpoint band vs FK reachability" tradeoff: accept the overage when lint-clean.
2. **Priority-conflict pair construction:** my first cross-production-vs-double-booked instance wasn't a genuine dual-failure (the two checks can't co-occur on one request), so I replaced it with OCC-stale-version vs double-booked — both genuinely fire on a repeat booking, OCC (priority 6) wins — giving the required distinct category pair {state, business_constraint} vs instance 1's {state, business_fiscal}.
3. **YAML flow-sequence gotcha:** unquoted `field?` optionals and bracketed `errors[...]`/`validations[priority=N]` grounds tokens inside `[...]` flow lists broke PyYAML; quoted all such elements.
4. **`prior_assignment_id` self-reference** on Assignment is described as an internal computed link (quoted, not the canonical `FK ->` prefix) so the linter does not demand a reverse-GET for an internally-resolved turnaround pointer.
5. Added a priority-17 validation + an explicit publish precondition so `ERR_PRODUCTION_NOT_ACTIVE` is anchored, and annotated two state-machine preconditions so `ERR_OPEN_ASSIGNMENTS_BLOCK_WRAP` / `ERR_DAILIES_FLAG_REASON_REQUIRED` are non-dangling.

## Step 3: Copy Shared Files — 2026-06-04T00:00:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-04T00:00:00.000Z

Generated `workspace/PRD.md` — **287 lines**.

### Major sections produced
- **§1 Introduction** — 2 paragraphs framing the domain as several tightly-coupled clocks (stripboard, payroll, permits, dailies) and naming the four owners + read-only auditor.
- **§2 Global Specifications** (8 subsections): 2.1 RBAC, 2.2 verbatim response envelope, 2.3 Pagination, 2.4 Common Resource Properties & Versioning, 2.5 Hierarchical Consistency & Cascading Effects, 2.6 Optimistic Concurrency Control, 2.7 Monetary Precision & Rounding, 2.8 The Order of Validation.
- **§3 Business Logic** (10 subsections): production lifecycle, budget lines/manual actuals, stripboard (days+scenes), hiring & booking (parallel attendance×payment dimensions), labor costing (all five calc formulas), call sheets, permits, union fringe, residual accrual, dailies review.
- **§4** 63-row endpoint table (4 columns), **§5** 20-row error table (2 columns).

### Hard Contract reports (PASS): field coverage 69/69; rule coverage all PASS (validation precedence chain §2.8, 2 OCC rules, 6 state machines, 7 calculations, cascades); path purity §3 PASS (0 paths/methods leaked).

### Notable scaffold-to-prose decisions
- Calculations translated to precise prose with no operator syntax: overtime rounded once not per-hour; fringe round-then-add; residual cumulative-then-differenced marginal bands (100M@120bps / next 400M@180bps / above 500M@240bps) with boundary-straddle called out.
- Boundary inclusivity preserved verbatim: permit window half-open `[start, end)` (abutting=no conflict) vs crew time closed interval (touching=conflict); meal boundary inclusive at 6h; turnaround at-least-10 vs strictly-under-10; budget gate and over_budget both strict `>`.
- Scattering: `POST /assignments` inputs split (core in §3.4, `expected_shooting_day_version` OCC anchored in §2.6); check-out's `wrap_time`/`meal_breaks_taken` in §3.4, cost consequences in §3.5.
- Parallel state machine: Assignment's attendance × payment dimensions narrated as two separately-driven axes (FirstAD vs PayrollCoordinator).
- `common_fields:false` for ResidualEvent (only `id`/`created_at`). Path purity via state-transition framing; api_prefix empty → flat collections.

## Step 5: Generate Unit Tests — 2026-06-04T00:00:00.000Z

Generated complete test infrastructure under the design-index-only contract.

### Tests emitted: 76 total
- **Queue A (Difficulty): 36 tests** — all 18 difficulty instances (9 rules × 2) covered with ≥2 tests each. No shortfalls.
- **Queue B (Corner): 40 tests** — all 40 non-stub corner instances covered with ≥1 test each. No gaps.

### Instances skipped: 1 (correctly, per contract)
- `Corner/state_machines/approve_pay_from_unpaid_without_wrapped_returns_invalid_state` — an `excluded_because:` **stub**. Its `difficulty_instance` cross-reference resolves to a real difficulty instance, so the stub is not translated. No placeholder emitted.

No instances skipped for PRD-coverage failure — PRD verbatim-covers and uniquely-derives every non-stub instance (precedence explicit in §2.8; monetary literals follow §3.5/§3.9; strict-`>` budget, half-open permit windows, closed-interval crew overlaps all stated verbatim).

### Test file layout (`test_suite/`)
- `test_01_assignment_costing.py` (9), `test_02_residual_accrual.py` (3), `test_03_state_machines.py` (10), `test_04_cascades.py` (9), `test_05_validation_precedence.py` (12), `test_06_temporal_overlap.py` (4), `test_07_crud_and_validations.py` (21), `test_08_rbac_and_concurrency.py` (8).

### `test_helpers/`: types, api_client (one method per endpoint), api_errors (20 errors), assertions, factories, constants, test_users (5 opaque roles), fixtures (layered scheduled→in-progress→checked-in→wrapped→approved chain + dailies/permit helpers), __init__.

### Verification: all 76 tests collect cleanly; 112 citation segments verified verbatim against PRD; every test exactly one `Design:` tag → real instance; zero skip/xfail; zero scaffold refs. No PRD bugs found. ResidualEvent correctly `common_fields:false`.

## Step 6: Generate Implementation — 2026-06-04T00:00:00.000Z

Built complete Python + Flask implementation in `workspace/implementation/`.

### File layout
`start.sh` (foreground, reads $PORT, binds 0.0.0.0, guarded pip install, exec python3 app.py), `requirements.txt` (flask==3.0.3), `app.py`, `db.py` (in-memory Store, 12 dicts, empty on boot, no seeding), `errors.py` (20-entry catalogue), `response.py` (envelope helpers), `middleware.py` (X-User-ID/X-User-Role auth + RBAC), `helpers.py` (body validation 400 vs 422, ISO parse, pagination), `routes/` (productions, schedule, crew, callsheets, locations, finance, dailies), `services/` (calc.py, recompute.py, serialize.py).

### Endpoints: 61 implemented (25 GET, 36 POST) — full PRD §4 surface across all 12 entities.

### State machines & calculations
- Parallel state (Assignment): attendance (SCHEDULED→CHECKED_IN→WRAPPED / NO_SHOW) + payment (UNPAID→APPROVED→PAID / VOID), independent, role-driven.
- Cyclic (CallSheet PUBLISHED↔REVISED, Dailies IN_REVIEW↔FLAGGED), branching (ShootingDay, LocationPermit), guarded-linear (Production), with preconditions + cascades. Day-cancel cascade voids SCHEDULED assignments, unschedules scenes, cancels PUBLISHED call sheet (CALLED branch only).
- Calculations use Decimal/ROUND_HALF_UP: estimated/actual cost (overtime one term), SAG meal penalty (2500 + 3500·(missed−1)), turnaround (flat day rate when rest <10h), round-then-add fringe, marginal-tier residual (120/180/240 bps cumulative-then-differenced).
- OCC on POST /assignments (expected_shooting_day_version) and POST /budget-lines/{id}/post-actual (expected_production_version) → ERR_STALE_VERSION (412). Validation precedence per §2.8.

### PRD ambiguities resolved
1. committed_cost_cents counts estimated_cost_cents for UNPAID AND APPROVED, paid_cost_cents only for PAID; approve-pay does not swap committed → bumps production version only when estimated ≠ paid.
2. Budget gate at approve-pay reads as projected committed where this assignment contributes paid_cost_cents; fires on strict > projection (exact-equal allowed).
3. mark-paid bumps production version exactly once (actual + committed both change in one action).

## Step 7: Run Tests and Iterate — 2026-06-04T00:00:00.000Z

**Iterations run:** 1 fix iteration, then 2 confirmatory 8-round parallel sweeps (16 rounds total, all 75/75 passing). Orchestrator re-ran a 3rd independent 8-round sweep to regenerate the cleared `results.{1..8}.json` artifacts — all 8 rounds 75/75, failed=0, errors=0.

Starting state: 76 tests, 16 in the failing union across the first sweep (mix of consistent logic bugs and intermittent infrastructure flakes).

### Tests deleted (1)
- **`test_committed_cost_reflects_actual_after_approve`** (`test_suite/test_08_rbac_and_concurrency.py`) — NON-UNIQUE DERIVABILITY / formula contradiction. It asserted an APPROVED assignment contributes its `paid_cost_cents` (278500) to `committed_cost_cents`, but PRD 3.5 (line 164) explicitly defines `committed_cost_cents = sum(estimated_cost_cents for UNPAID|APPROVED) + sum(paid_cost_cents for PAID)`, so an APPROVED assignment contributes its `estimated_cost_cents` (251000). The test even quoted that formula in its own docstring while asserting the opposite. Scaffold rule: `Corner/cross_cutting_complexity_layers/estimate_to_actual_reconciliation_delta_on_approve`.

### Fixes applied to test_suite/ (2 — PRD-faithfulness, not implementation accommodation)
- **`test_04_cascades.py` → `_setup_called_day_with_scene`** — TEST BUG (stale-version fixture ordering). It captured `day["version"]` at creation, then scheduled a scene (which recomputes `estimated_page_eighths` → a mutation per PRD 2.4 → bumps the day's version), then booked with the now-stale version → `ERR_STALE_VERSION`. Fixed by re-fetching the day before booking so `expected_shooting_day_version` reflects current state. Faithful PRD behavior; the fixture was wrong.
- **`test_02_residual_accrual.py` → `test_residual_ordered_by_event_date_not_insertion`** — PARTIAL COVERAGE split. Kept the covered assertion (early-dated event residual == 960000). Removed the uncovered `residual_reserve_cents == 1560000` assertion: PRD 3.9 states residuals are "added" at insertion and residual events are immutable, so inserting an earlier-dated event does not retroactively recompute the already-recorded later-dated event's residual; the faithful reserve is 480000 + 960000 = 1,440,000, not tier(120M) = 1,560,000.

### Fixes applied to implementation/ (3)
- **`routes/finance.py` → `create_residual_event`** — residual ordering bug. It summed ALL existing events as the prior cumulative (wrongly assuming the new event always sorts last). Per PRD 3.9, prior cumulative must include only events earlier in `(event_date ASC, created_at ASC)` order. Fixed to filter to events whose `(event_date, _seq)` is strictly less than the new event's.
- **`routes/schedule.py` → `cancel_day`** — missing cascade recomputes. After VOIDing SCHEDULED assignments and unscheduling scenes, it never recomputed the production's `committed_cost_cents` or the day's `estimated_page_eighths` (both computed fields per PRD 2.4/3.3/3.5). Added `recompute_committed_cost(prod)` (when assignments were voided) and `recompute_page_eighths(day)`.
- **`app.py` → `__main__`** — bind-race/boot flakes ("could not be restarted", "Connection reset by peer") under 8× concurrent per-test-server restarts. Replaced `app.run()` with a `werkzeug.serving.make_server` bind-retry loop (SO_REUSEADDR + ~20s retry window) so a transient TIME_WAIT collision retries instead of crashing the boot. Eliminated all 9 intermittent infrastructure flakes.

Final result: 75/75 tests pass across 16 consecutive parallel rounds (subagent) + 8 more (orchestrator re-verify) with zero flakiness.

## Step 8: Finalize PRD — 2026-06-04T00:00:00.000Z

Produced `workspace/PRD_FINALIZED.md`. **Line counts:** PRD.md 287, PRD_FINALIZED.md 287 (one line revised in place; ~0% delta).

**Changes (one):**
- **§3.3 (cancel-day cascade)** — *revise* — appended that the day-cancellation cascade also recomputes the production's `committed_cost_cents` (only when ≥1 assignment voided) and the day's `estimated_page_eighths`, each recompute being a §2.4 mutation only of the resource whose computed field actually changed — `routes/schedule.py:160-166`.

**Pre-edit search log:** (a) subject = recompute of production committed_cost + day page_eighths during cancel cascade + version-bump semantics; (b) enumerated `services/recompute.py`, `routes/schedule.py` (cancel_day/schedule_scene/create_shooting_day), `routes/crew.py` (no_show/book/approve_pay/mark_paid); (c) scoped committed-cost recompute to "when ≥1 assignment voided" (matches `if voided_any`), deferred version-bump to §2.4 "only resource whose computed field actually changed" (matches `if != total` guards, consistent with off-path recompute sites).

**Items NOT patched (already PRD-determined):** deleted committed-cost test (PRD §3.5 formula already verbatim); test_04 re-fetch (pure fixture bug, PRD §2.4+§3.3 already pin it); residual ordering fix (PRD §3.9 already specifies order + immutability); test_02 reserve removal (PRD §3.9 immutability); app.py bind-retry (infrastructure-only, no PRD surface).

## Step 9: Complete PRD — 2026-06-04T00:00:00.000Z

Produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md`. **Line counts:** 287 → 287 (in-paragraph edits only). **Char delta:** 44,742 → 46,865 (+2,123). **Counts: 7 ambiguity-pins, 0 mismatch-revisions.**

**Changes:**
- §2.3 Pagination — insert — list endpoints accept optional resource-scoping query filters (parent FK + `status`), applied before pagination, ignored when omitted/unrecognized.
- §3.2 Budget Lines — revise — `amount_cents` must be present typed integer ≥ 0 (else `ERR_VALIDATION_FAILED`); post-actual bumps the budget line's own `updated_at`/`version` and returns the budget line (not production).
- §3.4 (check-out) — revise — `hours_worked` recorded as fractional/float hours, not rounded to whole hours.
- §3.4 (no-show) — insert — no-show recomputes production `committed_cost_cents` and bumps production version when it changes.
- §3.6 (publish) — revise — pinned first-publish check order: day-PLANNED → production-ACTIVE → has-assignment; publishable states DRAFT/REVISED.
- §3.6 (revise) — insert — revise may optionally carry replacement `general_call_time`; omitted leaves it unchanged.
- §3.9 Residual — revise — pinned rounding boundary: both cumulative tier totals at full precision, differenced, round-half-up applied once to the marginal difference.

**Already correct (no change):** residual `(event_date, _seq)` ordering + immutability; approve-pay budget gate projects with paid amount while committed formula counts APPROVED at estimate (both pinned by §3.5); all numeric ranges/codes/shapes match. Infrastructure-only `ERR_INTERNAL`/405-mapping left out of catalogue intentionally.

---

## Pipeline complete — 2026-06-04T00:00:00.000Z

All 9 steps done. Final state: **75/75 tests pass across 24 parallel rounds** (16 subagent + 8 orchestrator re-verify), zero flakiness. Final artifacts present: SCAFFOLD.yaml (+ 2 design files), PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md, test_helpers/ + test_suite/ (75 tests), workspace/implementation/ (61 endpoints, in-memory Flask), results.{1..8}.json (all green).

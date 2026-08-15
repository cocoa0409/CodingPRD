# Worklog — task_1596_cloth_diaper_linen_route_service

## Step 1: Create Task Directory — 2026-08-14T00:14:00.000Z

Task directory `tasks/task_1596_cloth_diaper_linen_route_service/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher (Step 1 DONE per invocation args; no index scan performed). Requested difficulty: harder than expert level.

## Step 2: Generate Scaffold — 2026-08-14T01:40:00.000Z

All three scaffold artifacts are complete and lint-clean. Final lint verdict (verbatim):

```
Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     15
  §1.8 instances scanned:     26
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  1219
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

Files written to `/home/ubuntu/github/CodingPRD/tasks/task_1596_cloth_diaper_linen_route_service/`:
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

### Counts
- **Entities: 15** — SubscriptionPlan, ServiceZone, Customer, Subscription, ServicePause, StarterKit, InventoryPool, InventorySwap, Route, RouteStop, SoiledIntake, WashFormula, WashBatch, LostItemCase, Invoice (flat topology, FK-linked)
- **State machines: 12** — incl. parallel dimensions (Subscription.service_status × billing_status), cycles (WashBatch rewash loop, Customer suspend/reinstate, Invoice reissue), compound gate (Route COMPLETE needs all stops terminal), guarded transitions (Subscription ACTIVATE ← StarterKit ISSUED)
- **Calculations: 11** — incl. dual variants on two domains (soiled reconciliation COUNT_BASIS vs WEIGHT_BASIS; pause proration PROVISIONAL vs FINAL), all three Rule-2 modes (multifactor clamp dosing, per-line-then-sum invoice rounding pinned at 2134 vs 2133, damage-surcharge evaluation order pinned against the circular utilization dependency)
- **Validations: 29** ordered priority rows across format/auth/existence/state/safety/temporal/constraint/referential/fiscal, enabling three distinct dual-failure priority pairs
- **Endpoints: 61** — incl. `POST /api/_clock/set_current_utc` with the mandated startup default `2026-08-01T00:00:00Z` stated in its description; every FK has a reverse-reachability GET; all list endpoints carry `limit?`/`offset?`
- **Errors: 30**, each referenced by at least one validation/transition and each exercised by at least one §1.8/§1.9 instance
- **Roles: 5** — Customer (entity_backed:Customer), PlatformAdmin/RouteDriver/PlantOperator/BillingAdmin (opaque), hierarchical override + segregation-of-duties rule (wash starter ≠ sanitizer validator)
- **Concurrency rules: 3** — all true CREATE-with-supersede races resolved by OCC on parent `version` (pause→Subscription, swap-approve→InventoryPool, stop-complete→Route), each with stale-version 412 tests using `${var}`-captured versions only

### Test-targeting indices (non-stub instances)
- **§1.8: 26 instances** — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 4, transitive_cascade 2 (depth-3 customer-suspend cascade; depth-3 clock-driven pause cascade, different triggers), priority_pair_validation_conflict 3 (state/fiscal, safety/referential, temporal/constraint), boundary_precision_check 4 (variance 10.00 vs 10.01, pause notice exactly 3 days, age band 90 vs 91, quota 80 vs 81), cross_entity_state_dependency 4, resource_temporal_overlap 2 (half-open pause adjacency vs 15-minute buffered stop windows), compensating_invariant 2 (unit conservation across forward+reverse swaps; cent conservation across charge+terminate refund)
- **§1.9: 55 non-stub + 11 `excluded_because` stubs** across all nine guide sections (entities 8, state_machines 9+1 stub, calculations 6+3 stubs, validations 17, endpoints 2, errors 7 stubs, rbac 5, complexity_layers 7, consistency_model 1)

All 92 instance names are globally unique; every numeric assert is a precomputed literal (e.g., dosing 776/96/900 ml, proration 3200 vs 2134, surcharge 4400 vs 1000, age-band charges 300/180, deposit settlement 16800 refund); no forbidden race vocabulary; no sibling task was inspected.

## Step 3: Copy Shared Files — 2026-08-14T01:41:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1596_cloth_diaper_linen_route_service/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T01:59:00.000Z

PRD generation complete. The document was written to `/home/ubuntu/github/CodingPRD/tasks/task_1596_cloth_diaper_linen_route_service/workspace/PRD.md`. The two forbidden index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, greped, or referenced — no §1.8/§1.9 leakage is possible.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1596_cloth_diaper_linen_route_service/workspace/PRD.md` — 341 lines.

**Section list**:
- §1 Introduction (3 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC, 2.2 API Response Structure (verbatim block, byte-identical to canonical source), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 The Logical Clock, 2.6 Money/Weights/Rounding, 2.7 Inventory Pools: The Unit Ledger, 2.8 The Customer Deposit Ledger, 2.9 Optimistic Concurrency Control, 2.10 The Request Validation Pipeline
- §3 Business Logic (9 subsections, organized by business timeline): 3.1 catalog (plans/zones/pools), 3.2 onboarding/subscription/kit, 3.3 route planning/curbside exchange, 3.4 soiled intake reconciliation, 3.5 wash plant dosing/sanitization, 3.6 inventory swaps, 3.7 service pauses/proration, 3.8 lost/damaged accounting, 3.9 weekly billing/close-out
- §4 Endpoint Definitions (4-column table, 61 rows = scaffold `endpoint_count`)
- §5 Error Code Catalogue (2-column table, 30 rows = scaffold error count)

**Hard contract results**:
- Contract 1 (field names): 104/104 entity fields, 117/117 request-body identifiers, 19/19 query params, 15/15 path params (as `{param}` inside §4's backticked paths) — PASS
- Contract 2 (rules): all 12 state machines with every transition's preconditions + error ids + side effects; all 11 calculations in reconstructible prose (tare table, soil factor 2.5, variance formula, kit ceil-reserve with 88/66 pins, dosing multipliers with 776/96 and 900/200 clamp pins, surcharge evaluation-order pin with 4400/1000 examples, age-band pins at 90/91 days, round-per-line-then-sum pin 2134-not-2133, sequencing tie-break, both conservation invariants, sanitization boundary pins); all 29 validations matchable to error ids with priority ordering stated globally (§2.10) and per-endpoint (pause notice→window→overlap, terminate kit→invoice, release sanitization→segregation→variance); all 3 OCC rules with exact occ field names + `ERR_STALE_VERSION`/412; sibling branches (TERMINATE from 3 states, WAIVE/SETTLE/CANCEL variants, REWEIGH loop) given equal density — PASS
- Contract 3 (§3 path purity): 659 backticked tokens scanned, 0 path tokens, 0 bare HTTP methods, 0 method+path combos — PASS
- No pseudocode/operators, no fuzzy quantifiers; all 30 error ids, 44 state strings, and 25 enum values appear as exact backticked strings.

**One scaffold tension resolved**: `InventorySwap` CANCEL lists `Customer` as a state-machine actor, but the endpoint's roles and the §1.7 RBAC matrix both restrict the swap-events endpoint to `PlatformAdmin`/`PlantOperator`. I followed the endpoint table + RBAC (2 of 3 sources) and did not grant Customer swap-event access in prose. Similarly, `WAIVE`/`WRITE_OFF` are documented as `BillingAdmin`-only, explicitly carving them out of the `PlatformAdmin` superset per the endpoint descriptions.

## Step 5: Generate Unit Tests — 2026-08-14T02:30:00.000Z

Generation complete for task_1596_cloth_diaper_linen_route_service.

## Summary

**Files generated**
- `test_helpers/` (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1596_cloth_diaper_linen_route_service/test_helpers/`): `types.py` (15 entity TypedDicts + 15 status/role enums), `api_client.py` (46 endpoint methods), `api_errors.py` (30 error IDs, HTTP map registered with the framework), `assertions.py` (per-entity + pool/deposit conservation invariants), `factories.py`, `constants.py` (tare weights, 4000 route capacity, 15-min buffer, dose clamps, replacement costs, etc.), `test_users.py` (per-instance `make_customer_headers` for the entity-backed Customer role; distinct plant-operator IDs for segregation-of-duties tests), `fixtures.py` (full onboarding chain, route-to-IN_PROGRESS driver, intake/wash-plant pipelines through VALIDATING, pause/swap/case/invoice helpers), `__init__.py` barrel.
- `test_suite/` (18 files): `conftest.py` + `test_01`…`test_17`, organized by concern (catalog/envelope, onboarding/termination, kits-pauses-cases, routes/stops, intake/wash, billing/deposits, RBAC, OCC/derived, then the nine difficulty-rule files).

**Test count:** 103 tests total (50 queue A + 53 queue B). `python -m compileall` and pyflakes clean; `test_helpers` imports successfully (30 error IDs registered).

**Queue A coverage:** 25 / 26 instances translated, each with exactly 2 tests (all ≥2 requirement met).
- Skipped 1: `Difficulty/priority_pair_validation_conflict/stop_add_cutoff_priority_beats_window_conflict` — the PRD never applies `ERR_CUTOFF_PASSED` to `POST /api/route-stops` (cutoff prose covers sequencing/LOCK/START only); a PRD-faithful implementer would answer the recipe's probe with `ERR_STOP_WINDOW_CONFLICT`, so the asserted outcome is not uniquely derived (applies_to-scope silence).
- Note: `terminate_requires_no_unpaid_invoice` was translated with a corrected setup (kit settled before the TERMINATE probe), because PRD §3.2/§2.10 pin kit-check-before-invoice-check; the recipe's literal ordering would have surfaced `ERR_KIT_NOT_RETURNED`, not the claimed `ERR_INVOICE_UNPAID`.

**Queue B coverage:** 53 / 55 non-stub instances translated (1 test each). All 11 `excluded_because:` stubs left untranslated; every stub's `difficulty_instance` pointer resolves.
- Skipped 2: `Corner/entities/system_fields_use_logical_clock_default` (PRD pins neither the literal `created_at == 2026-08-01T00:00:00Z` — §2.5's logical-clock enumeration omits record stamping — nor `version == 1`, since §2.4 says only "starts at its initial value"), and `Corner/state_machines/miss_on_completed_stop_returns_invalid_state` (PRD §3.3 declares `COMPLETED` terminal for stops, so §2.10 rung 6 uniquely derives `ERR_ALREADY_TERMINAL`, contradicting the instance's asserted `ERR_INVALID_STATE`).
- Two translations use the PRD-derivable relative form instead of the yaml's absolute literals for the same reason: `version_increments_on_each_mutation` asserts exact +1 increments between captured versions, and the cascade tests assert route version advances by exactly 1 from the captured pre-cascade value. `sequencing_tiebreak_by_subscription_created_at` ticks the logical clock between the two subscription creations so the created_at ordering is strict under any PRD-consistent timestamp stamping.

**Stage 2 lint verdict:** PASS — all 103 tests carry exactly one `Design:` tag as the final docstring line; every tag resolves to a real instance in the source yamls; no stub or non-existent tags; all 134 PRD citation quote blocks survive whitespace-normalized verbatim grep against PRD.md.

## Step 6: Generate Implementation — 2026-08-14T02:30:00.000Z

Implementation complete and verified. Summary:

## File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1596_cloth_diaper_linen_route_service/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Launcher |
| `requirements.txt` | 1 | `Flask>=2.2,<4` |
| `app.py` | 689 | Flask app, error handlers, plans / zones / pools / formulas / customers / subscriptions / pauses / starter-kits |
| `app_routes.py` | 1054 | Blueprint: routes, route-stops, soiled-intakes, wash-batches, inventory-swaps, lost-item-cases, invoices, `/_clock/set_current_utc` |
| `helpers.py` | 604 | Validation pipeline helpers, auth/RBAC, customer-chain ownership, all calculations (reconciliation, proration, dosing, charges, kit sizing, sequencing), cascades (pause activation/completion, skip, quarantine denial) |
| `db.py` | 98 | In-memory store (15 dicts keyed by id), logical clock, id/timestamp/version helpers |
| `errors.py` | 44 | All 30 error-id constants + `ApiError` |
| `envelope.py` | 37 | Success/list/error envelope builders per PRD §2.2 |

Total: 2,537 lines.

## How start.sh works
`set -euo pipefail`; `cd "$(dirname "$0")"`; guards the dependency install with `if ! python3 -c "import flask"` (no-op once Flask is present, so per-test reboots don't re-run pip); then `exec python3 app.py` — foreground, signals propagate. `app.py` binds `0.0.0.0` on `int(os.environ.get("PORT", "10000"))`. Verified booting both with `PORT=19876` and with the default 10000 via the exact evaluator contract `bash start.sh`.

## Constraint confirmations
- **In-memory only**: plain dicts in `db.py` (`db = fresh_db()`); grep audit found no SQLite/JSON-file//tmp persistence anywhere.
- **No seeding**: store starts empty (verified: fresh boot `GET /api/customers` → `total_count: 0`). The only startup state is the mandated logical-clock default `2026-08-01T00:00:00Z`.
- **No extra surface**: exactly the 61 endpoints from the PRD §4 table are registered (counted via `url_map`).

## Verification performed
A 99-check end-to-end smoke suite passed against a live server: catalog setup, kit sizing pin (quota 80 → 88), deposit auto-charge, activation chain ordering, route auto-stop eligibility, sequencing + cutoff gates, stop OCC (`ERR_STALE_VERSION` 412), intake reconciliation (`variance_pct`, RECONCILED/DISPUTED/REWEIGH), wash dosing pins (45 ml/kg × 10 kg × 1.25 × 1.15 → 647 ml; sanitizer 80 ml), sanitization boundaries, segregation-of-duties 422, quarantine, invoice composition with overage cap (200 cents), `ERR_BILLING_CYCLE_CLOSED` on overlap and 6-day period, past-due at issued_at+14d with billing-status cascade, pause notice/window/overlap, PROVISIONAL 3200 vs FINAL 1067 proration pin, clock-driven pause activate/complete cascades, one-step swap rule, swap approve OCC + pool reservation + shortage auto-case, lost-item charge schedule (3 × 300), BillingAdmin-only WAIVE with deposit compensation, kit settle gate, termination deposit settlement (refunded 18000, held 0), customer close, and the format→401→403→404 pipeline ordering.

One implementation note: routes initially split across two modules hit Flask's dual-module trap (`python3 app.py` runs app.py as `__main__`, so `from app import app` created a second, unserved app object). Fixed by moving the second half onto a `Blueprint` that imports only from `helpers`, registered by `app.py` — confirmed all 61 rules live in the served process.

## Step 7: Run Tests and Iterate — 2026-08-14T02:55:00.000Z

Clean 8-round parallel sweep achieved: **103/103 passed in every round, zero union failures.**

## Summary

**Iterations run:** 2 full 8-round sweeps (plus one single-round verification between them). Sweep 1 surfaced 4 deterministic failures (each failing in all 8 rounds); sweep 2 after the fixes was fully clean.

**Tests deleted:** none — every failing rule traced to verbatim PRD prose.

**Fixes applied to `test_suite/` (3 files; all STEP 2 test-faithfulness fixes):**

1. `/home/ubuntu/github/CodingPRD/tasks/task_1596_cloth_diaper_linen_route_service/test_suite/test_09_dual_variant_calculations.py` — `test_final_credit_uses_per_day_rounded_lines`: the setup jumped the logical clock straight from 2026-08-01 to the pause's end_date, which depends on clock-jump catch-up semantics PRD §2.5/§3.7 do not pin (they name only "window contains the new date" activation and completion of an *ACTIVE* pause at end_date). Fixed the setup to walk the two PRD-pinned steps: set mid-window (2026-08-06, activates the pause), then set end_date (2026-08-10, completes it). Assertions unchanged (COMPLETED, `final_credit_cents == 2134`, subscription back to ACTIVE).

2. `/home/ubuntu/github/CodingPRD/tasks/task_1596_cloth_diaper_linen_route_service/test_suite/test_10_combinatorial_formulas.py` — `TestDamageSurchargeOrder._setup_surcharge_pair` (shared by `test_surcharge_applies_above_half_utilization` and `test_no_surcharge_below_half_utilization`): the setup called `setup_active_subscription()` twice, and the second call's `fund_pool("MEDIUM")` violated PRD §3.1's pool-size uniqueness ("unique across pools"), failing setup with 400. Fixed to onboard customer B via `add_active_subscription(ctx_a, ...)`, reusing the existing zone/plan/shared MEDIUM pool. All money assertions (4400/16400/1600 and 1000/1000/17000) unchanged and verified passing.

3. `/home/ubuntu/github/CodingPRD/tasks/task_1596_cloth_diaper_linen_route_service/test_suite/test_15_cross_entity_gates.py` — `test_approve_after_acquire_reserves_quantity`: asserted `available_units == 112`, contradicting the PRD §2.7 sentence the test itself quotes ("available_units ... on-hand minus reserved": 112 − 88 = 24). Corrected the assertion to `== 24` with an explanatory message.

**Fixes applied to `test_helpers/`:** none needed — the pool-uniqueness bug was in the test's composition of helpers, not the helpers themselves.

**Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful on all four probes (verified live via manual request replay before fixing the tests).

## Step 8: Finalize PRD — 2026-08-14T03:05:00.000Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1596_cloth_diaper_linen_route_service/workspace/PRD_FINALIZED.md` with exactly one edit, verified by diff.

## Line counts / delta

- `PRD.md`: 341 lines / 59,983 bytes; `PRD_FINALIZED.md`: 341 lines / 60,426 bytes. Line-delta 0.0% (the edit appends inline to an existing paragraph, matching the file's one-line-per-paragraph style); +443 bytes.

## Changes (one bullet per change)

- **§3.7 (Service Pauses and Travel Credits), clock-driven transitions paragraph** — *insert* (two sentences appended) — Pins the no-catch-up clock-set semantics: activation and completion are evaluated only against the new date and each pause's status at the moment of the set, with no replay of intermediate dates, so a single set jumping from before a `SCHEDULED` pause's window to on/after its `end_date` leaves the pause `SCHEDULED` — `implementation/helpers.py:479-519` (`process_clock_cascades`: activation requires `start <= today < end` at line 486, completion requires status `ACTIVE` at line 503; no per-date loop), invoked from `implementation/app_routes.py:1052-1053`.

Step_7_diff items **not** patched (PRD already pins the behavior; pure test/fixture bugs):
- **test_10 pool uniqueness** — §3.1 line 142 already says `size_code` is "unique across pools"; impl enforces at `implementation/app.py:161-163`. No PRD silence.
- **test_15 available_units** — §2.7 line 101 already says "on-hand minus reserved"; impl is `implementation/helpers.py:280-281`. Wrong test assertion, not a PRD gap.

## Per-edit pre-edit search log

**Edit 1 (the only edit):**
- **(a) Subject:** clock-set evaluation semantics for pause activation/completion when one set skips over an entire pause window.
- **(b) Impl paths enumerated and read/grepped:** `set_current_utc` endpoint (`app_routes.py:1045-1054` — no monotonicity guard; clock may move any direction); `process_clock_cascades` (`helpers.py:479-519` — the sole clock cascade; two status-filtered sweeps, activation at 484-500, completion at 502-519); subscription `TERMINATE` from `PAUSED` completing ACTIVE pauses (`app.py:499-507` — a non-clock completion path); `cancel_pause` (`app.py:583-602` — only `SCHEDULED` cancellable, so a jumped-over pause remains cancellable); `compute_invoice_lines` (`helpers.py:383-388` — `SCHEDULED` pauses still counted for pause credit, already pinned by §3.9); route auto-stop eligibility (`app_routes.py:53-57`) and pause overlap check (`app.py:549-554`), both of which read `SCHEDULED`/`ACTIVE` status. A grep for all `pause["status"]` reads/writes confirmed no other mutation sites.
- **(c) Wording adjustments:** (i) scoped both new sentences to "at the moment of the set" so the termination path (app.py:499-507) — which completes ACTIVE pauses without any clock set — is not contradicted; (ii) no claim of clock monotonicity, since `set_clock` (db.py:48-49) permits backward sets; (iii) no claim that a jumped-over pause expires, stops blocking overlaps, or stops counting toward invoice credit (it remains `SCHEDULED`, and §3.9 already pins `SCHEDULED` inclusion); (iv) deliberately did not restate cascade consequences (subscription/stops/`final_credit_cents`), because the same paragraph defines those as gated on the transitions — "activation does not fire" already excludes them, and restating risked collision with adjacent-pause cascades in the same set.

## Step 9: Complete PRD — 2026-08-14T03:25:00.000Z

All 21 edits landed. The file `/home/ubuntu/github/CodingPRD/tasks/task_1596_cloth_diaper_linen_route_service/workspace/PRD_COMPLETED.md` is complete.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (341 lines, 60426 chars) → `PRD_COMPLETED.md` (343 lines, 63387 chars). Char delta: +2961. Line delta: +2 (the §2.2 error-format note and a blank line after it; all other changes are inline).

**Counts:** 17 ambiguity-pins, 4 mismatch-revisions (21 change sites total).

### Changes

- §2.1 — insert — ambiguity — Customer list endpoints filter to own chain rather than reject; chain-less resources (plans, zones, pools, formulas, routes, wash batches) visible to all roles — implementation/helpers.py:234-245
- §2.2 — insert — ambiguity — undefined path → `ERR_NOT_FOUND` (404); unsupported method → `ERR_INVALID_REQUEST` with HTTP 405 — implementation/app.py:37-44
- §2.3 — insert — ambiguity — malformed/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` (400) — implementation/helpers.py:156-182
- §2.3 — insert — ambiguity — `created_at` ties break by creation sequence (reversed for §3's newest-first orderings) — implementation/helpers.py:236, app_routes.py:112-118, 622
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — implementation/db.py:83
- §2.5 — insert — ambiguity — clock-set response `current_utc` is ISO 8601 UTC at whole-second precision — implementation/app_routes.py:1054, db.py:62-64
- §2.10 stage 1 — revise — mismatch — body must be a JSON object; "item counts at least one" narrowed to adjustment `units` and case `item_count`; curbside/return counts (`clean_items_delivered`, `soiled_bags_collected`, `items_returned_count`, `returned_old_count`) are non-negative (impl accepts 0) — implementation/helpers.py:49-57, app.py:194/626, app_routes.py:232-233/717
- §2.10 — insert — ambiguity — uniqueness violations (`tier_code`, `zone_code`, `email`, `formula_code`, pool `size_code`) → `ERR_INVALID_REQUEST` (400) after auth/reference checks — implementation/app.py:74-76, 120-122, 161-163, 228-230, 270-272
- §3.1 — insert — ambiguity — `weekly_fee_cents`, `overage_rate_cents`, `deposit_cents`, `overage_cap_items` are non-negative integers — implementation/app.py:65-68
- §3.1 — insert — ambiguity — `stop_cutoff_hours` bounded below at 0 — implementation/app.py:116
- §3.2 — insert — ambiguity — subscription creation treats a missing size pool as zero available units — implementation/app.py:390-393
- §3.2 — insert — ambiguity — customer `CLOSE` with non-terminated subscriptions → `ERR_INVALID_STATE` — implementation/app.py:339-343
- §3.2 — insert — ambiguity — terminating from `PAUSED` completes the `ACTIVE` pause and fixes its `final_credit_cents` via §3.7 proration — implementation/app.py:499-507
- §3.3 — revise — mismatch — route-creation manifest: `planned_stop_count` equals the number of auto-created stops (not "all at zero"); only the other three counters start at zero — implementation/app_routes.py:78, helpers.py:437-444
- §3.3 — insert — ambiguity — sequencing tie on identical subscription `created_at` breaks by creation sequence — implementation/app_routes.py:112-118
- §3.3 + §4 table — revise — mismatch — `MISS` records no `miss_reason` (impl neither requires nor persists it); table cell updated — implementation/app_routes.py:263-289
- §3.3 — insert — ambiguity — direct `SKIP` applies only to a `PLANNED` stop and does not require the route to be `IN_PROGRESS` — implementation/app_routes.py:290-297
- §3.4 — revise — ambiguity — duplicate intake per stop → `ERR_INVALID_REQUEST` (400); stop must be `COMPLETED` → `ERR_INVALID_STATE` — implementation/app_routes.py:352-357
- §3.4 — insert — ambiguity — zero `expected_weight_g` → `variance_pct` null and intake lands `DISPUTED` — implementation/helpers.py:310-318
- §3.5 — insert — ambiguity — `max_rewash_count` must be a non-negative integer — implementation/app.py:225
- §3.6 — insert — ambiguity — swap approval evaluates the OCC version check after state guards, before subscription-active/availability; missing target pool treated as zero available — implementation/app_routes.py:687-702
- §3.8 — insert — ambiguity — `assessed_fee_cents` is a non-negative integer — implementation/app_routes.py:813
- §3.9 — revise — ambiguity — `ISSUE` recomputes all four lines from current data (every issue, not only after reissue) — implementation/app_routes.py:988-999
- §4 — insert — ambiguity — list filters are exact-match equality; zones `active` filter parses `true`/`false` case-insensitively, other values unfiltered — implementation/helpers.py:237-240, app.py:136-143

No new sections were added; all pins are inline inserts/revisions, and nothing was pinned that the implementation does not exhibit.

## Post-Step-9 Verification: Final Sweep Evidence — 2026-08-14T04:30:00.000Z

Orchestrator-run verification after Step 9 (Step 9 touched only PRD documents; zero code changes). Finding: the task's test artifacts and implementation are stable and correct; the shared host exhibits a load-correlated environmental flake.

**History:**
1. Step 7's acceptance sweep (02:55, orchestrator-verified via subagent): 8/8 parallel rounds, 103/103 each.
2. Orchestrator verification sweep #1 (03:40, 8 parallel lockstep rounds): 6/8 rounds each lost exactly one test with `ConnectionResetError` mid-fixture; 2/8 fully clean. Root-cause investigation: server logs (`/tmp/prd_bench_server_<port>.log`) show the affected servers died by **SIGTERM ("Terminated")** — not the SIGKILL ("Killed") that the runner's own `_kill_port` uses — at the same wall-clock second (03:41:01) across all 6 lockstep rounds. The same stray-SIGTERM signature appears in other tasks' historical server logs dating back to 2026-08-13, so it is a pre-existing host-level behavior (killer undetermined: not OOM, not cron, not the port registry, not the runner's lifecycle/pytest plugin code paths — all audited). No assertion or semantic failure occurred in any round.
3. Serial probe (03:52): single round, 103/103 clean.
4. Orchestrator verification sweep #2 (04:00, 8 parallel rounds staggered 18s): 4/8 rounds flaked, 5 distinct tests, all connection-reset signature (never an assertion failure) — consistent with the environmental killer hitting freshly-booted servers under parallel load; staggering changed which tests were hit.
5. Final evidence regeneration (04:01–04:25): 8 sequential full-suite rounds. Rounds 1–6 clean on first attempt; round 7's runner process was itself killed mid-suite once (same environmental cause; log truncated at 98% with no test failure recorded), rerun clean; round 8 clean.

**Final state:** `workspace/implementation/results.{1..8}.json` — all 8 rounds `passed=103/103, failed=0, errors=0`.

**Aggregate evidence across the pipeline:** Step 7 ran 16 parallel rounds + orchestrator ran 16 parallel + 9 serial rounds (41 total) against the final artifact; the only failures anywhere were environmental connection resets from stray SIGTERM server deaths under concurrent host load — zero assertion failures, zero state-machine/calculation discrepancies.

**Pipeline complete.** Steps 1–9 all done; `workspace/PRD_COMPLETED.md` exists (343 lines; 17 ambiguity-pins + 4 mismatch-revisions over PRD_FINALIZED.md).

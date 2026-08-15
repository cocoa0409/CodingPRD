# Worklog — task_1423_drywall_interior_finish_supply_stocking

## Step 1: Create Task Directory — 2026-08-13T05:53:00.000Z

Task directory `tasks/task_1423_drywall_interior_finish_supply_stocking/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T06:20:00.000Z

All three files validate as YAML, lint is clean, and all counts meet or exceed the Advanced difficulty band (6-10 entities, 12-22 endpoints is exceeded because we need FK reverse-reachability GETs; this is consistent with the SKILL.md guidance that reverse-reachability adds endpoints).

## Summary

**Output files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1423_drywall_interior_finish_supply_stocking/`):

| File | Lines | Top-level keys |
|---|---|---|
| `SCAFFOLD.yaml` | 1300 | `scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `response_envelope`, `endpoints`, `errors`, `roles` |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1498 | `scaffold_difficulty_design` (single key, 9 rules × 2 instances) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 1425 | `scaffold_corner_design` (single key, 8 sections) |

**SCAFFOLD.yaml counts**:
- Entities: 11 (ContractorAccount, Product, Project, Takeoff, TakeoffLine, StockingOrder, StockingDrop, BoomTruck, DrawRequest, Payment, BundleReturn)
- State machines: 6 (ContractorAccount, Project, Takeoff, StockingOrder, DrawRequest, BundleReturn)
- Calculations: 6 (effective_waste_pct_bp, line_bundle_count, freight_tier_cents, draw_amount, restock_fee, special_order_lead_time)
- Validations: 20
- Endpoints: 53 (higher than the 12–22 band because every FK must have a reverse-reachability GET per §1.5)
- Errors: 28
- Roles: 7 (CreditManager, EstimatorUser, DispatcherUser, Foreman, ContractorAdmin, AccountsReceivableUser, WarehouseManager — all `opaque`)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 18 difficulty instances across the 9 rules (2 each), each with structured `setup_api_calls` and `trigger` chains using `${var}` placeholder discipline (no bare-literal OCC versions).

**SCAFFOLD_CORNER_DESIGN.yaml**: 29 corner instances across 8 sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting).

**Validation**:
- All three files parse with `yaml.safe_load`.
- `scaffold_lint.py` reports `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (582 calls scanned, 0 violations).

**Key archetype choices**: pricing_engine (primary) + temporal_windowing (secondary); layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers. Dual-variant calcs live on two different entity domains (Takeoff pricing vs StockingOrder freight); priority-conflict pairs span (state × business_temporal) and (existence × business_fiscal); compensating invariants cover draw-balance conservation and account-AR conservation.

## Step 3: Copy Shared Files — 2026-08-13T06:22:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1423_drywall_interior_finish_supply_stocking/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T06:35:00.000Z

All contracts pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1423_drywall_interior_finish_supply_stocking/workspace/PRD.md`.

**What was generated:** A full PRD for the drywall & interior-finish supply domain, structured as: §1 Introduction (2 paragraphs, business-context angle); §2 with 9 subsections (RBAC with all 7 opaque-identity roles, the verbatim §2.2 envelope block, pagination, resource identity including the `Payment` common_fields=false exception, cents/basis-points/rounding discipline, the logical clock with its `2026-08-01T00:00:00Z` startup default, left-to-right nested path resolution, global validation priority order, and OCC on takeoff lock); §3 with 9 domain-derived workflow subsections covering all 6 state machines, all 6 calculation rules (waste ceiling, bundle rounding, dual provisional/final pricing, 3-tier freight with 750 bp fuel surcharge at dispatch, SKU-filtered draw amount, 7-day/15%/25% restock fee), and every cascade (suspend cancels drafts, close cancels projects and orders, stocked-order auto-draw with credit-limit suspension cascade); §4 with all 53 endpoints in a 4-column table; §5 with all 28 catalogued errors in a 2-column table.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 47 required, 47 present, 0 missing
- endpoints[].request_body/input: 11 required (incl. expected_takeoff_version, to_iso8601, current_utc), 11 present, 0 missing
- endpoints[].query_params/path_params: covered (limit, offset, status, account_id, project_id, product_id, takeoff_id, line_status, boom_truck_id, scheduled_date, stocking_order_id, board_kind, active, id, line_id)
- Total required set: 58 required, 58 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 20 checked, 20 expressed in prose (global order in §2.8, pairwise orderings near each guarded workflow), 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (lock endpoint + expected_takeoff_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 19 checked, 19 fully expressed (preconditions + error ids + side effects incl. all cascades), 0 missing
- calculations[]: 6 checked, 6 fully expressed in precise prose with all constants embedded (10000 bp denominator, 25/75-mile tiers, 9500/19500/320/480 cents, 750 bp fuel, 7-day window, 1500/2500 bp restock, framing thresholds 50 and 30), 0 missing
- validations[] conditions: 20 checked, 20 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed, incl. dual-scope guards (ERR_RATED_NON_RETURNABLE and ERR_OVER_RETURN at both file and accept), 0 missing
- entities[].fields[] structured content: defaults, ranges, enum values, and the Payment no-updated_at/no-version exception all reconstructible, 0 missing
- sibling-branch symmetry: AM/PM, ACH/CHECK/CARD, partial/exact payments, DRAFT vs SUBMITTED cancels, DRAFT vs SCHEDULED order cancels — equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 317
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

One judgment call to note: the scaffold's account-suspend precondition annotates `ERR_ACCOUNT_NOT_ACTIVE`, which is absent from the §1.6 error catalog. I kept the §5 table faithful to the catalog (28 ids) but mentioned `ERR_ACCOUNT_NOT_ACTIVE` in §3.1 prose so a test derived from the state-machine table remains answerable from the PRD alone.

## Step 5: Generate Unit Tests — 2026-08-13T07:10:00.000Z

Generation complete. All artifacts are in place and audited.

## What was generated

**`test_helpers/`** (9 files): `types.py` (11 entity TypedDicts — `Payment` correctly omits `updated_at`/`version` per its append-only semantics — plus 12 enums), `api_client.py` (49 endpoint methods covering every PRD §4 route including the `_clock/set_current_utc` test-driving endpoint), `api_errors.py` (all 28 error IDs with HTTP statuses, registered via `set_error_http_status_map`), `assertions.py`, `factories.py` (unique SKU/truck-code generation), `constants.py` (freight tiers, fuel surcharge, restock rates, framing gates, logical-clock start), `test_users.py` (7 opaque role headers), `fixtures.py` (layered composites: `create_locked_takeoff` with optional pre-lock price patch, `setup_stocking_open_scenario`, `setup_draft/scheduled/stocked_order_scenario`, draw/payment/return helpers).

**`test_suite/`** — 63 tests across 6 files: `test_01_contractor_accounts.py` (8), `test_02_access_control_and_resolution.py` (6), `test_03_catalog_and_takeoffs.py` (14), `test_04_stocking_orders_and_scheduling.py` (18), `test_05_freight_draws_payments.py` (12), `test_06_bundle_returns.py` (5).

## Audit results

- **Queue A**: all 18 difficulty instances have exactly ≥2 tests (36 tests). **Queue B**: 27 of 29 non-stub corner instances covered (27 tests). Every test docstring ends with exactly one verbatim `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line resolving to a real instance (verified programmatically against both YAMLs).
- **Citations**: every docstring's `PRD §x.y: "..."` quote was mechanically verified to survive a whitespace-normalized literal grep of `workspace/PRD.md` (0 misses after fixing 6 elided quotes); no docstring mentions scaffold tables.
- All files compile; imports cross-checked against `test_helpers` exports; no unused imports remain.

## Deliberate skips (PRD-first filter)

1. **`Corner/entities/project_create_requires_existing_account`** — PRD §2.7 covers resolution of *path* id segments only; no PRD sentence names the error surface for a dangling `account_id` in a request body, and two PRD-only readers could diverge.
2. **`Corner/state_machines/takeoff_cancel_blocked_when_in_use`** — PRD §3.4 defines takeoff cancel only from DRAFT/SUBMITTED, yet a SCHEDULED/DISPATCHED order requires a LOCKED takeoff (§3.6), making `ERR_TAKEOFF_IN_USE` unreachable under the PRD's own rules; the instance's own grounds cite the SUBMITTED→CANCELLED transition while its setup locks the takeoff.

## Design-index defects found (asserted values NOT copied verbatim where wrong)

- **`Corner/calculations/effective_waste_uses_account_default_when_no_override`**: the YAML asserts `ovr_quoted == 165000`, but the PRD formula (ceil(105/20)=6 bundles × 20 × 1500) uniquely derives **180000**. The generated test asserts the PRD-derived 180000 (both takeoffs price identically because bundle rounding absorbs the 5-sheet waste difference; the override effect is demonstrated via `billable_sheet_count` 110 vs 105).
- Corner setup annotations in `precondition_enforcement_overpayment_rejected` and `err_account_balance_open_triggered_on_close` say the draw/AR is 39500 (= material + 9500 *provisional* freight); the draw actually uses the *final* dispatch freight 10213 (PRD §3.7), i.e. 40213. Both tests assert only error IDs / PRD-derived values, so the annotation error doesn't propagate.

## Step 6: Generate Implementation — 2026-08-13T07:05:00.000Z

All files are in place. Implementation complete.

**Summary of what was built**

Implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1423_drywall_interior_finish_supply_stocking/workspace/implementation/`:

- `start.sh` — executable launcher, guarded `pip install`, `exec python3 app.py`, reads `PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — Flask only
- `app.py` — Flask app, blueprint registration, `ApiError` handler, 404/405 handlers, `app.run(host="0.0.0.0", port=PORT)`
- `db.py` — `Store` class with empty dicts for all 11 entity types + `Clock` class fixed at `2026-08-01T00:00:00Z` on boot (no wall-clock fallback); module-level singleton `db = Store()`
- `errors.py` — `ApiError` exception + all error-ID constants from the scaffold catalog (including `ERR_ACCOUNT_NOT_ACTIVE` referenced by PRD §3.1)
- `response.py` — envelope helpers producing `{meta:{api_request_id, api_request_timestamp, ...}, response_type, data}`; pagination fields (`limit`/`offset`/`total_count`/`has_more`) injected into `meta` for list endpoints
- `middleware.py` — `X-User-Role` validation against the seven declared roles; `require_roles(...)` enforces 401→403 priority
- `services/calc.py` — waste (ceil), bundle count (ceil), line pricing, tiered freight with 750bp fuel surcharge rounded `ROUND_HALF_UP` via `Decimal`, restock fee threshold rule (0/1500/2500bp) with half-up rounding, deterministic per-sheet weight lookup keyed by `thickness_in`
- `services/helpers.py` — pagination parsing (limit 1..100, default 10; offset ≥0), body/field validators, `new_common_fields` (UUID id, ISO8601 ms-precision created_at/updated_at, version=1), `touch()` (bumps version + updated_at)
- `routes/` — one blueprint per resource: `accounts.py`, `products.py`, `trucks.py`, `projects.py`, `takeoffs.py`, `orders.py`, `draws.py`, `returns.py`, `clock.py`

**Key fidelity points honored**

- Validation priority per PRD §2.8: schedule path checks run in order — `ERR_TAKEOFF_NOT_LOCKED` → `ERR_LEAD_TIME_VIOLATION` → `ERR_SHIFT_DOUBLE_BOOKED` → `ERR_CAPACITY_EXCEEDED` → `ERR_WEIGHT_EXCEEDED` → `ERR_EMPTY_ORDER` → `ERR_TRUCK_INACTIVE`; submit path checks rated lead time (`ERR_SPECIAL_ORDER_LEAD_TIME`) before `ERR_EMPTY_TAKEOFF`; return path checks `ERR_RATED_NON_RETURNABLE` before `ERR_OVER_RETURN`.
- OCC only on takeoff lock via `expected_takeoff_version` → `ERR_STALE_VERSION` (412).
- Logical clock settable only by `CreditManager` via `POST /supply/_clock/set_current_utc`; today = clock's calendar date.
- Payment has no `updated_at`/`version` (append-only ledger entry).
- Cascades: account suspend cancels DRAFT takeoffs; account close cancels non-terminal projects and their non-terminal stocking orders; project cancel from STOCKING_OPEN refused on DISPATCHED orders, cancels DRAFT/SCHEDULED orders + non-terminal takeoffs; project close-stocking cancels DRAFT orders; mark-stocked auto-issues DrawRequest and pushes account to SUSPENDED if AR > credit limit.
- Draw amount = sum of `final_line_cents` for ACTIVE takeoff lines whose product appears in the order's drops + the final `freight_charge_cents`.
- Return credit floors AR at 0; restock-fee rate 0 if ≤7 days since stocked, else 1500bp if no loose sheets, 2500bp otherwise.
- No seeding — store starts empty on every boot; no SQLite/JSON/tmp persistence.

**Smoke-tested end-to-end**: account → product → truck → project → takeoff → line → submit (waste/bundle/quote math verified) → lock (OCC + final reprice) → open-stocking → order → drop → schedule (provisional freight) → dispatch (final freight with 7.5% fuel surcharge) → mark-stocked (auto-draw issuance + AR increment). Also verified double-booking rejection on same truck/date/shift and AM/PM half-open intervals allowing adjacent bookings.

## Step 7: Run Tests and Iterate — 2026-08-13T07:30:00.000Z

## Summary

**Iterations run: 2** (initial 8-round sweep → fixes → final 8-round sweep, all 8 rounds 63/63 passed)

**Tests deleted: none.** Both failing tests traced to verbatim PRD rules and were faithful.

**Failures diagnosed (union across initial sweep):**

1. `test_takeoff_submit_blocked_when_account_suspended` — deterministic in all 8 rounds. Expected `ERR_ACCOUNT_SUSPENDED`, got `ERR_INVALID_STATE`. PRD §2.8 verbatim: "then the account-posture guard (`ERR_ACCOUNT_SUSPENDED`), then generic state guards (`ERR_INVALID_STATE`), and only then the business rules." The suspended account had cascade-cancelled the DRAFT takeoff, so both guards tripped; PRD priority uniquely demands the account-posture guard win. Test faithful → implementation fix.

2. `test_lock_preserves_quoted_and_computes_final_subtotal` — errored in all 8 rounds of the first sweep with "API server … could not be restarted" (15s restart-poll window exhausted). A solo rerun errored on a *different* test (`test_payment_on_nonexistent_draw_rejected_even_for_small_amount`), proving it was position-independent boot flakiness: the runner SIGKILLs the prior server and spawns a fresh one on the same port; if the killed process isn't reaped before the new one binds, `EADDRINUSE` crashes the boot and the poll times out. No test/helper/PRD issue — implementation boot-robustness fix.

**Fixes applied to `test_helpers/`: none.**

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1423_drywall_interior_finish_supply_stocking/workspace/implementation/routes/takeoffs.py` — `submit_takeoff`: moved the account-posture check (`ERR_ACCOUNT_SUSPENDED`) ahead of the DRAFT state guard (`ERR_INVALID_STATE`), matching the PRD §2.8 global priority order.
- `/home/ubuntu/github/CodingPRD/tasks/task_1423_drywall_interior_finish_supply_stocking/workspace/implementation/app.py` — `__main__` entry: `app.run()` now retries on `OSError` (EADDRINUSE) for up to ~30s, so a slow-to-reap predecessor process on the same port no longer kills the fresh boot under the 8-round concurrent sweep.

**Final state: 8/8 rounds, 63/63 tests passed each round.**

## Step 8: Finalize PRD — 2026-08-13T07:38:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1423_drywall_interior_finish_supply_stocking/workspace/PRD_FINALIZED.md` is written as a byte-identical copy of PRD.md (verified with `diff`).

## Exit summary

**Line counts / delta:** PRD.md 279 lines, PRD_FINALIZED.md 279 lines, 0% delta — zero edits.

**Changes:** none. Both Step 7 items were investigated and neither warrants a PRD patch:

- **Step 7 Fix 1 (`submit_takeoff` guard reorder)** — no edit. PRD §2.8 already pins the priority verbatim: "then the account-posture guard (`ERR_ACCOUNT_SUSPENDED`), then generic state guards (`ERR_INVALID_STATE`), and only then the business rules." The failing scenario (suspended account cascade-cancelled the DRAFT takeoff per §3.1, so both guards tripped on submit) is uniquely resolved by that sentence, and the implementation was changed to match the PRD, not vice versa (`implementation/routes/takeoffs.py:188-191` now checks account posture before the DRAFT state guard). The step_7_diff itself confirms: "PRD priority uniquely demands the account-posture guard win. Test faithful → implementation fix."
- **Step 7 Fix 2 (`app.py` EADDRINUSE boot retry)** — no edit. This is process-boot robustness invisible at the HTTP API surface the PRD specifies: it alters no response body, status code, resource state, or error behavior — only whether the process survives a transient port conflict at startup. Server startup is governed by the INSTRUCTION.md build contract (start.sh / PORT / 0.0.0.0 / foreground / 60s readiness), not the PRD, and the step_7_diff classifies it as "No test/helper/PRD issue — implementation boot-robustness fix." Pinning it would require inventing a deployment topic absent from the PRD (violating "no new sections", "change as little as possible").

**Per-item pre-edit search log** (no edits were committed, so (c) is empty for both; the searches below are what justified the no-edit decisions):

1. **Fix 1 — subject: account-posture guard (`ERR_ACCOUNT_SUSPENDED`) vs. generic state guard (`ERR_INVALID_STATE`) ordering.**
   (b) Paths enumerated: `implementation/routes/takeoffs.py` (submit_takeoff:188-191 — the Step 7 site; also create_takeoff:58-59, add_line:115-116, cancel_line:166-169, lock_takeoff:246-247, cancel_takeoff:278-279); `implementation/routes/accounts.py` (suspend:76-91 with the DRAFT-takeoff cascade at 84-90, reinstate:98-99, close:116); `implementation/routes/projects.py` (create_project:40-41, open_stocking:93-97, close_stocking:115-116, cancel_project:137-138); `implementation/routes/orders.py` (create:74-75, add_drop:138, schedule:191, dispatch:275, mark_stocked:296, cancel:346); `implementation/routes/draws.py:61,110`; `implementation/routes/returns.py:136,196`; full-repo greps for both error IDs. PRD §2.8 and §3.4 re-read against every site.
   (c) N/A — PRD §2.8's existing verbatim sentence already correctly describes the fixed `submit_takeoff` behavior, so no wording was proposed. (Note for Step 9's full scan, out of Step 8 scope: `open_stocking` at projects.py:93-97 checks the PLANNING state guard before the account-posture guard — a combination Step 7 never exercised; left untouched here per the hard scope.)

2. **Fix 2 — subject: server boot behavior on port-bind failure.**
   (b) Paths enumerated: `implementation/app.py` (entire file; `__main__` retry loop at lines 55-71 is the only boot path; `create_app()` registers blueprints and error handlers only); `implementation/start.sh`; workspace `INSTRUCTION.md` startup contract; grepped the repo for any other `app.run`/socket-bind callsite (none).
   (c) N/A — no wording proposed; the behavior is outside the PRD's API-behavior surface and the step_7_diff explicitly flags it as a non-PRD issue.

**Key files:** `workspace/PRD_FINALIZED.md` (deliverable), `workspace/implementation/routes/takeoffs.py`, `workspace/implementation/app.py`.

## Step 9: Complete PRD — 2026-08-13T07:58:00.000Z

Step 9 complete. `workspace/PRD_COMPLETED.md` written (copy of PRD_FINALIZED.md + 30 logical inline edits; no new sections).

**Size delta**: PRD_FINALIZED.md 279 lines / 39,665 chars → PRD_COMPLETED.md 282 lines / 44,401 chars (+3 lines, +4,736 chars).

**Counts**: 22 ambiguity-pins, 8 mismatch-revisions.

**Changes** (each: section — insert|revise — class — what — impl ref):

- §2.1 — insert — ambiguity — `X-User-ID` is never required or validated; only `X-User-Role` is enforced — middleware.py:16-29
- §2.2 — insert — ambiguity — unknown path or unsupported method → `ERR_NOT_FOUND` 404 — app.py:36-42
- §2.3 — insert — ambiguity — limit/offset violations → `ERR_VALIDATION` 400; sort tie-break by `id` ascending; `has_more` = offset+limit < total_count — services/helpers.py:7-32
- §2.4 — revise — ambiguity — `version` starts at 1 (was "its initial value") — services/helpers.py:76-83
- §2.6 — insert — ambiguity — `to_iso8601` without offset read as UTC; stored instant normalized to UTC, echoed with `Z` — db.py:33-44
- §2.7 — insert — ambiguity — body-supplied ids (`account_id`, `project_id`, `takeoff_id`, `boom_truck_id`, `product_id`, `stocking_order_id`) resolve like path ids → 404 — e.g. projects.py:31-35, orders.py:49-63
- §2.8 — insert — ambiguity — `ERR_VALIDATION` (400) sits outside the priority ladder, raised where the field is examined; blanket: any unassigned state-guard violation → `ERR_INVALID_STATE` 409 — services/helpers.py:45-73
- §3.1 — revise — mismatch — posture guard blocks project/takeoff/order creation; it does **not** block the automatic draw at stocking confirmation (PRD said it "applies wherever a draw would be issued" — impl has no posture check in mark_stocked) — takeoffs.py:58-59, orders.py:74-75, orders.py:291-338
- §3.1 — insert — ambiguity — reinstate: non-SUSPENDED → `ERR_INVALID_STATE`; over-limit → `ERR_ACCOUNT_BALANCE_OPEN` — accounts.py:98-105
- §3.1 — insert — ambiguity — close from CLOSED → `ERR_INVALID_STATE`; close cascade also cancels non-terminal takeoffs — accounts.py:115-116, 131-134
- §3.2 — insert — ambiguity — product field-constraint violations incl. duplicate `sku` → `ERR_VALIDATION` 400; PATCH re-applies board-kind lead-time rules; `active` filter parsing (true/1/yes) — products.py:38-55, 93-95, 108-114
- §3.2 — insert — ambiguity — duplicate `truck_code` → `ERR_VALIDATION` 400; same active-filter parsing — trucks.py:30-32, 56-58
- §3.3 — insert — ambiguity — framing/distance PATCH allowed in any project status — projects.py:76-86
- §3.3 — revise — mismatch — **(the Step 8 flagged item, confirmed)** open_stocking evaluates the PLANNING state guard *before* the account-posture guard — an explicit exception to §2.8's ladder (posture-first holds elsewhere, e.g. takeoff submit) — projects.py:93-97
- §3.3 — revise — mismatch — opening stocking gates *scheduling*, not order creation (impl create_order has no project-status check) — orders.py:41-88
- §3.3 — revise — mismatch — close-stocking cancels DRAFT orders but does not block later creation; scheduling is what's blocked — projects.py:123-130, orders.py:196-197
- §3.4 — insert — ambiguity — takeoff creation requires ACTIVE account (`ERR_ACCOUNT_SUSPENDED`); project status unchecked; new takeoff carries zero aggregates and null `final_subtotal_cents` — takeoffs.py:55-77
- §3.4 — insert — ambiguity — deactivated product on add-line → `ERR_VALIDATION` 400; new line carries zero `waste_sheets`/`bundle_count`/`quoted_line_cents` and null `final_line_cents` — takeoffs.py:117-129
- §3.4 — insert — ambiguity — LOCKED and CANCELLED are terminal for a takeoff (cancel from either → `ERR_INVALID_STATE`); defines "non-terminal takeoff" = DRAFT/SUBMITTED for all cascades — takeoffs.py:278-279
- §3.5 — revise — mismatch — final price fields are carried as **null** before lock (PRD said "simply do not exist"; impl serializes the keys as null) — takeoffs.py:73, 127
- §3.6 — revise — mismatch — order creation not gated on stocking window or takeoff lock; referenced project/takeoff/truck need only exist (PRD said "Once a project's window is open") — orders.py:41-88
- §3.6 — insert — ambiguity — per-sheet weight lookup values pinned: 40/50/60 lbs for 1/2", 5/8", 3/4" (PRD referenced "a per-sheet weight lookup" without values); `freight_charge_cents` starts at 0 — services/calc.py:25-29, 73-74; orders.py:83
- §3.7 — insert — ambiguity — dispatch on non-STOCKING_OPEN project → `ERR_PROJECT_NOT_STOCKING_OPEN` — orders.py:282-283
- §3.7 — insert — ambiguity — mark-stocked records `stocked_at` on the order from the logical clock (null until stocked); anchors the §3.9 restock window — orders.py:85, 305
- §3.7 — insert — ambiguity — draw is issued regardless of account posture at confirmation — orders.py:291-338
- §3.7 — revise — mismatch — over-limit cascade suspends only an ACTIVE account (already-SUSPENDED keeps status with higher ledger); blocked-op list corrected to match impl guard set — orders.py:333-336
- §3.8 — revise — mismatch — `received_at` is recorded verbatim (any non-empty string accepted); payments apply in submission order, not `received_at` order — draws.py:59, 66-74
- §3.9 — insert — ambiguity — return filing requires only that order/product exist (STOCKED enforced at acceptance); return born with `restock_fee_cents`/`credit_cents` at zero — returns.py:56-103, 98-99, 140-141
- §5 — insert — ambiguity — added catalogue row `ERR_ACCOUNT_NOT_ACTIVE` 409 (used at accounts.py:81 but missing from table)
- §5 — insert — ambiguity — added catalogue row `ERR_VALIDATION` 400 (used throughout but missing from table)

Everything else in the impl — RBAC table, endpoint set, state machines, pricing/bundle/freight/restock formulas, scheduling-path priority ladder, AR ledger arithmetic, clock startup value, envelope shape — matched the PRD as written and required no change.

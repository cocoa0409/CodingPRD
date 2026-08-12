# Worklog — task_1156_cabinet_manufacturing_plant

## Step 1: Create Task Directory — 2026-08-11T04:20:00.000Z

Pre-assigned output folder `tasks/task_1156_cabinet_manufacturing_plant` with `workspace/` subdirectory already exists; Step 1 auto-index scan skipped per instructions. Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-11T05:08:00.000Z

All three scaffold artifacts are generated, lint-clean, and self-consistent.

## Deliverables (all under /home/ubuntu/github/CodingPRD/tasks/task_1156_cabinet_manufacturing_plant/)

- **SCAFFOLD.yaml** — §1.0–§1.7: 16 entities, 9 state machines, 12 calculations, 14 ordered validations, 57 endpoints, 64 error codes, 6 roles, 1 OCC concurrency rule. No `scaffold_difficulty_design`/`scaffold_corner_design` keys inside.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single top-level `scaffold_difficulty_design:` with all 9 rules × 2 instances = 18 instances, each with structured `setup_api_calls`/`trigger`/`assert` recipes and hand-computed literal expectations (e.g. provisional 1,627,600 vs final 1,804,000 merchandise on identical line data; consolidation freight 20,250 from count-at-dispatch; ceil boundary 28,800 in² → exactly 7 sheets).
- **SCAFFOLD_CORNER_DESIGN.yaml** — single top-level `scaffold_corner_design:` with 80 instances (70 active + 10 `excluded_because` stubs) across all 9 claim-taxonomy sections.

## Design shape (difficulty directive "harder than expert" applied)

- **Archetype blend**: quota/allocation (sheets, batch door capacity, line minutes, route cube) × pricing engine (dealer levels L1–L5, tiered mod surcharges with min-cap, volume tiers, freight consolidation).
- **Rule highlights**: dual-variant calcs in two distinct domains (order pricing NET_ALL vs NET_LIST_ONLY; claim credit flat-50% estimate vs windowed final); combinatorial modes (a) and (c); cyclic machines on ModificationRequest (review ↔ resubmit) and FinishBatch (QC fail → remix); depth-4 cascade (nesting release → parts → component overdraft → shortage hold → order posture) and depth-3 QC-fail cascade; two priority pairs (state>fiscal, referential>constraint); boundary instances at exactly-$50k merchandise and exactly-1.5 Delta-E; cross-entity gates (Order⇐Mod, Route⇐Order); half-open adjacency (assembly line) vs changeover-buffer (nesting station) overlap semantics; conserved cube and door-count invariants; OCC on `expected_order_version` for route supersede-assignment.
- **Logical clock**: `POST /kcma/_clock/set_current_utc` with mandatory startup default `2026-05-01T00:00:00Z` stated in its description; drives warranty-window (90/365-day, inclusive boundary) and schedule-date rules.

## Verification

- `scaffold_lint.py` final verdict, verbatim: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (57 endpoints, 16 entities, 18 + 70 instances, 717 calls scanned; 4 FK-reverse violations found and fixed during iteration by renaming sub-resource placeholders to `{id}` and adding `sheet_component_id?` to `GET /kcma/nesting-runs`.)
- Additional audits passed: zero unbound `${var}` placeholders, 98 unique instance names across both design files, all `grounds:` references resolve to declared elements, no forbidden concurrency vocabulary, all enum values producible, and two replay bugs fixed pre-lint (sheen-lot rule made reachable via `required_sheen_lot_no`; cancel-cascade instance restructured so a SUBMITTED order with partial sub-lot coverage remains cancellable, with open-mod compensation moved to a DRAFT-cancel instance).

## Step 3: Copy Shared Files — 2026-08-11T05:09:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T05:25:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1156_cabinet_manufacturing_plant/workspace/PRD.md`. The withheld index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or referenced.

**Document shape.** ~340 lines. §1 is a two-paragraph introduction from the shop-floor coordination pain-point angle. §2 has nine subsections (RBAC with per-role identity translation, verbatim §2.2 envelope block, pagination, resource identity/versioning with the `Part` no-`updated_at`/no-`version` exception, money/rounding, the logical clock with its 2026-05-01T00:00:00Z startup default, the 14-level validation priority ladder, OCC on route assignment, and the dual-dimension order posture). §3 scatters the rules across nine workflow subsections (dealer/catalog administration; order build and provisional submit pricing; mod review cycle; finish room QC; nesting and inventory; sub-lots and line balancing; holds/progression/cancellation; claims adjudication; routes/consolidation/dispatch). §4 is a minimal 4-column table of all 57 endpoints; §5 is the 2-column, 64-row error catalogue with no trigger conditions.

**Hard contract reports:**

```
Field coverage check:
- entities[].fields: 102 required, 102 present, 0 missing
- endpoints[].input: 66 required, 66 present, 0 missing
- path_params: 13 required, 13 present, 0 missing (generic {id} plus 12 named params)
- common fields (id/created_at/updated_at/version): 4 required, 4 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ladder: 14 checked, 14 expressed in explicit ordered prose (§2.7), 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (assign-order + expected_order_version + ERR_STALE_ORDER_VERSION/412; no race framing), 0 missing
- state_machines[].transitions: 33 checked (Order 6, OrderLine 7, ModificationRequest 4, FinishBatch 3, NestingRun 2, SubLot 2, DeliveryRoute 2, ReplacementClaim 3, OrderHold 2), 33 fully expressed with preconditions paired to error ids and side effects, 0 missing
- calculations[]: 11 checked, 11 fully expressed in precise prose (multiplier schedule L1–L5, dual-variant line pricing with per-line rounding pin, both volume-tier totals, mod surcharge base-fee/tier/cap pinned order, freight consolidation pinned 5-step order with count-includes-self note, cube via 1728 per-line then sum, nesting yield with 12% waste and ceil exact-multiple boundary, sub-lot work minutes with exact-tie-allowed capacity, Delta-E boundary equal-passes, dual-variant claim credit, component availability with skip-duplicate hold rule), 0 missing
- validations[] conditions: all matchable to error ids in §2/§3 prose; all 64 error ids from the catalog appear in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: 57 checked, 57 expressed (4-hop nesting release cascade, 3-hop QC-fail cascade, DRAFT-vs-SUBMITTED cancel cascades, receipt auto-release, dispatch finalization), 0 missing
- entities[].fields[] structured content: defaults (active=true, delta_e_tolerance=1.5, reorder_level=0, revision=1, version=1, zero-initialized counters) and computed-field semantics all reconstructible from prose, 0 missing
- sibling-branch symmetry: cancel from DRAFT vs SUBMITTED, three review decisions, three adjudication outcomes, QC pass vs fail — all rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 543
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional spot checks passed: §2.2 block is byte-identical to the canonical source (including `req_RANDOMALPHANUM123456` and `"data": { }`); no fuzzy/approximating words or pseudocode operators in prose; all enum values (`L1`–`L5`, constructions, sheens, kinds, mod codes, claim types) and all state values appear as exact strings; the document ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-11T05:55:00.000Z

Generation complete. Both stages are on disk under `/home/ubuntu/github/CodingPRD/tasks/task_1156_cabinet_manufacturing_plant/`.

## What was generated

**Stage 1 — `test_helpers/` (9 modules)**
- `types.py` — 16 entity TypedDicts + status/role enums; `Part` correctly omits `updated_at`/`version` (common_fields: false, PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (61 methods, incl. `POST /kcma/_clock/set_current_utc`)
- `api_errors.py` — all 64 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py`, `factories.py`, `constants.py` (price multipliers, tier thresholds, mod fee table, freight/claim constants, logical-clock default)
- `test_users.py` — shared constants for the five opaque roles + mandatory `make_dealer_headers(dealer_id)` for the entity-backed Dealer role
- `fixtures.py` — tiered composites: `create_submitted_box_order` / `create_submitted_door_order`, `setup_door_order_in_production`, `setup_box_order_ready_to_ship`, `setup_door_order_ready_to_ship`, `setup_shipped_door_order`, `setup_shipped_box_order`, `setup_shortage_hold_environment`, `assign_order_to_route` (auto-freshens OCC version), `slot_and_complete_box_line`; all ownership-gated calls thread `make_dealer_headers(entity["id"])`

**Stage 2 — `test_suite/` (conftest + 13 test files, 107 tests)**, organized by concern: catalog/entities, envelope+field validation, RBAC/ownership/404, order submission+provisional pricing, order lines, modifications, finish room, nesting, assembly, shipping/OCC/freight, claims, holds/cancel, station windows.

## Audit results (all green)
- **Coverage**: all 18 difficulty instances have exactly ≥2 tests; all 57 non-stub corner instances have ≥1; all 10 `excluded_because` stubs verified to resolve to real difficulty instances and were not translated
- **C4 tags**: every test docstring ends with exactly one `Design:` line resolving to a real instance; no untagged, dual-tagged, or dangling tags
- **C1 verbatim**: every quoted PRD citation was machine-checked to survive a whitespace-normalized literal grep of `workspace/PRD.md`
- **No** `pytest.mark.skip`/`skipif`/`xfail`; no scaffold terminology in comments/docstrings
- `pytest --collect-only` collects 107 tests cleanly; pyflakes clean (one missing import found and fixed during the pass)

## Key adjudication decisions
- `submitted_at` exact-string assertion from the corner recipe was relaxed to a date-prefix + ISO-8601 check: PRD §2.4's three-fractional-digit rendering vs §2.6's `2026-05-01T00:00:00Z` clock value is not uniquely derivable at string level (two-reader rule)
- Part ordering test sorts by `part_seq` rather than list position (list tie-break on equal `created_at` is not pinned by the PRD)
- Priority-pair tests cite PRD §2.7's ordered list (items 6/13 and 8/9), which does state the ordering, so both difficulty priority instances were generated rather than skipped
- No instances failed the two-condition filter — zero gaps

## Step 6: Generate Implementation — 2026-08-11T06:20:00.000Z

All 107 tests pass. The implementation is complete and verified.

## Report

**Delivered**: Complete Python + Flask implementation of the KCMA Cabinet Manufacturing Plant API in `/home/ubuntu/github/CodingPRD/tasks/task_1156_cabinet_manufacturing_plant/workspace/implementation/`.

**Verification**: `prd-bench-local-run --isolation per-test-server` → **107/107 passed, 0 failed** (61s, server restarted via `start.sh` before every test). Cold start on default `PORT=10000` also verified manually.

**Files**:
- `start.sh` — guarded dependency install (no-op `import flask` check so per-test reboots don't re-run pip), `exec python3 app.py` in foreground
- `app.py` — Flask app, envelope-wrapped error handlers, process-wide request lock making every request's side effects atomic (race-safe)
- `store.py` — in-memory store, empty at boot (no seeding), logical clock starting exactly at `2026-05-01T00:00:00Z`
- `errors.py`, `auth.py` — full §5 error catalog with HTTP statuses; `X-User-ID`/`X-User-Role` auth with the six peer roles
- `util.py` — response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), `limit`/`offset` pagination (default 10, 1–100), and a **deferred field-validation reader** so `ERR_VALIDATION`/`ERR_INVALID_ENUM`/`ERR_INVALID_QUANTITY`/`ERR_INVALID_TIME_WINDOW`/`ERR_DUPLICATE_CODE` fire strictly last per the §2.7 priority order
- `domain.py` — all calculations with `Decimal` round-half-up: dual-variant order pricing (provisional discounts list+upcharge+mods; final discounts list only), volume tiers (5M/10M cents, `>=` boundaries), mod surcharge (base fee → tiered 5/10/15% → 40% cap), order cube (per-line 2dp then summed), nesting yield (exact-multiple-safe ceil at 12% waste, `part_seq` by height DESC/width DESC/created_at ASC), sub-lot work minutes, batch Delta-E threshold (`<=` passes), claim credit provisional/final variants, freight consolidation (tier from route order count at dispatch instant)
- `serializers.py` — exact entity field sets; Part carries `id`/`created_at` only (no `updated_at`/`version`); derived fields (available_qty, assigned_door_count, reserved_cu_ft, hold_status, slotted_qty) computed on read so cascades can never drift
- `routes_*.py` — all 56+ endpoints: dealers, catalogs, components/receipts, orders/lines/mods, finish batches (assign with finish→sheen→capacity check order, QC pass/fail cascade, remix), nesting runs/parts, sub-lots (half-open overlap with adjacency allowed, changeover-buffer station windows, line-day capacity with exact-tie allowed), claims (90/365-day inclusive warranty windows), routes (OCC `expected_order_version` → `ERR_STALE_ORDER_VERSION` 412, supersede semantics, stop sequencing, lock/dispatch gates), hold release, and the `_clock/set_current_utc` test-driving endpoint

**Key design decisions**: validation priority strictly follows PRD §2.7 (headers → role → ownership → path ids → body FKs → state → cross-entity gates → active → shape → batch compat → temporal → warranty → fiscal → field sanity); `version` increments once per mutation event on intrinsic fields (derived-field-only reconciliations don't bump, matching every explicit version note in the scaffold); submitted_at/shipped_at and all timestamps read the logical clock only.

## Step 7: Run Tests and Iterate — 2026-08-11T06:12:00.000Z

All 8 parallel rounds completed with 107/107 tests passing in every round — a clean sweep on the first iteration.

## Summary

- **Iterations run:** 1 (single 8-round parallel sweep; no fixes required)
- **Tests deleted:** none
- **Fixes applied to `test_helpers/`:** none
- **Fixes applied to `implementation/`:** none

All 8 rounds (`results.1.json` … `results.8.json` in `/home/ubuntu/github/CodingPRD/tasks/task_1156_cabinet_manufacturing_plant/workspace/implementation/`) report `passed == total == 107` with zero failed/error/skipped entries. The implementation, test suite, and helpers were already consistent and stable — no flakiness surfaced under the 8× concurrent per-test-server isolation sweep, so no diagnostic STEP 1–3 work was triggered.

## Step 8: Finalize PRD — SKIPPED

Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` already determined every behavior the implementation exhibits; per the skip condition, no Step 8 subagent was spawned and no `PRD_FINALIZED.md` was produced.

## Step 9: Complete PRD — 2026-08-11T06:21:00.000Z

## Summary

**Source:** `PRD.md` (no `PRD_FINALIZED.md` existed; Step 8 was skipped) → `PRD_COMPLETED.md`
**Size:** 362 → 364 lines; 55,498 → 60,005 chars (**+4,507 chars**, +2 lines)
**Counts:** 17 ambiguity-pins, 5 mismatch-revisions (22 edit sites total)

### Mismatch revisions (PRD said X, impl does Y)

- **§2.2** — revise — mismatch — `api_request_timestamp` renders three fractional digits only when the instant has sub-second precision; whole-second instants render without a fractional part — `implementation/util.py:46-51` (`fmt_ts`).
- **§2.4** — revise — mismatch — same fractional-digit rule applied to the resource-timestamp sentence — `util.py:46-51`.
- **§2.7 item 3** — revise — mismatch — ownership is checked *after* resolving the resource that carries the dealer FK (path resource first; for claims, the body `original_order_line_id` first), not before existence checks — `routes_orders.py:101-102,192-193,236,316-318,385-388`; `routes_claims.py:39-50`.
- **§2.8** — revise — mismatch — stale-version check rejects *any* inequality of `expected_order_version` vs current `version`, not only "advanced beyond" — `routes_shipping.py:97-106`.
- **§3.2** — revise — mismatch — cancelling an order does **not** recompute `cube_ft`; a cancelled order retains its last computed cube — `routes_orders.py:232-276` (no `recompute_order_cube` call).

### Ambiguity pins (PRD silent, impl behavior pinned)

- **§2.1** — insert — `Dealer`-role `X-User-ID` naming no persisted Dealer → `ERR_DEALER_NOT_FOUND` (404) on order creation; surfaces as ownership mismatch elsewhere — `routes_orders.py:48-51`.
- **§2.2** — insert — multi-resource actions return the path-addressed resource (batch assign/QC/remix → batch; route assign/lock/dispatch → route; sub-lot complete → sub-lot) — `routes_finish.py:137,185,198`; `routes_shipping.py:121,142,181`; `routes_assembly.py:175`.
- **§2.2** — insert — undeclared paths/methods → error envelope with non-catalogued `ERR_NOT_FOUND` at 404 — `app.py:43-50`.
- **§2.3** — insert — non-integer/out-of-range `limit`, negative/non-integer `offset` → `ERR_VALIDATION` (400) — `util.py:95-115`.
- **§2.3** — insert — `created_at` ties broken by creation sequence — `util.py:118-121`.
- **§2.4** — insert — computed-on-read fields (`available_qty`, `assigned_door_count`, `slotted_qty`, `hold_status`, route `reserved_cu_ft`/`assigned_order_count`) never bump `version`; derived-field reconciliations (order `cube_ft` on line add, line `mod_surcharge_cents` on review approval, component `reserved_qty` on run release) bump no version/`updated_at`; no-op updates (dealer PUT with unchanged values) don't bump version — `serializers.py:57-70,96-119,136-147,238-249`; `routes_orders.py:176,370-371`; `routes_nesting.py:184`; `routes_catalog.py:77-85`.
- **§2.6** — insert — envelope `api_request_timestamp` reads the logical clock — `util.py:62-66`.
- **§2.7 item 6** — insert — `ERR_ORDER_HAS_NO_LINES` fires at tier 6, immediately after the DRAFT state check — `routes_orders.py:194-198`.
- **§2.7 item 7** — insert — added `ERR_LINE_ORDER_NOT_RELEASED_TO_PRODUCTION` to the cross-entity gate list — `routes_nesting.py:61-62,158`; `routes_assembly.py:44-50`.
- **§2.7 closing** — insert — missing/malformed JSON body treated as empty object (required-field `ERR_VALIDATION`); OCC check sits between tiers 6 and 13 on route assignment — `util.py:158-160`; `routes_shipping.py:85-115`.
- **§3.1** — insert — catalog resources (styles, finishes, components, stations, assembly lines) have no update verb; `active` is set only at creation — no PUT routes exist in `routes_catalog.py`.
- **§3.1** — insert — boolean `active` filters accept case-insensitive `true`/`false`; other values match nothing — `util.py:124-132`.
- **§3.1** — insert — `available_qty` appears in both list and detail representations; sheet-dimension fields are stored/rendered null for non-`SHEET_GOODS` kinds — `serializers.py:57-70`; `routes_catalog.py:204-208`.
- **§3.2** — insert — new orders initialize all pricing fields, `delivery_route_id`, `route_stop_seq`, `submitted_at`, `shipped_at` to null — `routes_orders.py:58-68`.
- **§3.5** — insert — `door_line_ids` must be a non-empty string array (empty → `ERR_VALIDATION`); duplicates collapse to first occurrence — `util.py:279-291`.
- **§3.5** — insert — `part_seq` ties at equal `created_at` break by creation order — `domain.py:288-290`.
- **§3.7** — insert — order-hold and component-hold collections list all matching holds regardless of `PLACED`/`RELEASED` status — `routes_orders.py:180-186`; `routes_catalog.py:272-278`.
- **§3.7** — insert — route removal on cancellation also nulls `route_stop_seq` — `routes_orders.py:271-273`.
- **§3.9** — insert — cube check excludes the order's own existing booking on the target route (same-route re-assign never double-counts) — `routes_shipping.py:108-114`.
- **§3.9** — insert — `route_stop_seq` is a per-route monotonic counter, never reused even after supersede/cancel — `routes_shipping.py:53,118-119`.
- **§3.9** — insert — dispatched orders remain linked to the route, so the computed counters keep reading their dispatch values — `serializers.py:238-249`; `routes_shipping.py:164-181`.

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_1156_cabinet_manufacturing_plant/workspace/PRD_COMPLETED.md`

Pipeline complete: `PRD_COMPLETED.md` exists, worklog reaches Step 9, and the final 8-round stability sweep passed 107/107 in all 8 rounds.

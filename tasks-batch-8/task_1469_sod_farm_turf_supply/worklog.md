# Worklog — task_1469_sod_farm_turf_supply

## Step 1: Create Task Directory — 2026-08-13T10:18:03.000Z

Task directory `tasks/task_1469_sod_farm_turf_supply/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per invocation instructions. No index scan performed, no other task_* directory touched.

## Step 3: Copy Shared Files — 2026-08-13T10:18:40.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1469_sod_farm_turf_supply/workspace/INSTRUCTION.md` (1424 bytes). Done concurrently while Step 2 subagent runs.

## Step 2: Generate Scaffold — 2026-08-13T12:06:24.000Z

All checks pass. The scaffold is complete and clean.

## Summary

Generated the full scaffold for **task_1469_sod_farm_turf_supply** at `/home/ubuntu/github/CodingPRD/tasks/task_1469_sod_farm_turf_supply/`:

- `SCAFFOLD.yaml` (§1.0–§1.7; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (57 endpoints, 15 entities, 18 + 55 instances, 778 calls scanned.)

### Counts

| Element | Count | Notes |
|---|---|---|
| Entities | 15 | PriceConfig, VarietyConfig, Field, ReSeedPlan, HarvestBatch, Customer, Crew, Quote, Order, Payment, DeliveryCheck, CrewReferral, WarrantyClaim, WateringLog, TruckBlock |
| State machines | 8 | incl. Order with **parallel dimensions** (status × payment_status, PAID→PENDING reversion, auto-join to CLOSED), **cyclic** FieldMaturity (SEEDED→…→OVERAGED→SEEDED via re-seed), branching Quote/CrewReferral |
| Calculations | 14 | pallet yield w/ slab-roll shortfall, per-line-then-sum rounding (pinned), freight cell by pallet-count zone mix, tiered pricing ladder with pinned evaluation order, cumulative-vs-strict delivery window, 24h freshness projection, half-open zone-truck capacity, freshness-aware allocation selector, watering compliance tiers, reseed requirement |
| Validations | 12 priority rows | auth → authz → existence → shape → enum → terminal → state → OCC → temporal → constraint → safety → fiscal |
| Endpoints | 57 | incl. `POST /_clock/set_current_utc` (default 2026-08-01T00:00:00Z) |
| Error catalog | 28 | all referenced by validations/transitions |
| Roles | 5 | FarmManager/SalesRep/HarvestSupervisor/FleetManager (opaque) + Customer (`entity_backed:Customer`, ownership-enforced) |
| Concurrency rules | 1 | OCC on `Field.version` via `expected_field_version` at harvest-batch create (412 `ERR_STALE_FIELD_VERSION`) — passes the serial-observability filter |
| Difficulty instances | 18 | 9 rules × 2, all differentiated per §0.5 clauses |
| Corner instances | 58 | 55 active + 3 `excluded_because` stubs, across all nine claim-guide sections |

### Harder-than-expert design highlights
- **Dual-variant calcs in different domains**: tiered-ladder vs additive-flat pricing (4633.76 vs 5225.30 on identical inputs) and cumulative vs strict delivery-window compliance (`in_window=true` while `strict_in_window=false` on the same check row).
- **Combinatorial formulas in different modes**: mode (a) tiered ladder with a pre/post-discount straddle case (pre 4151.20 → T1 while post-discount gross 3902.13 < 4000); mode (b) pinned per-line rounding (turf 1350.91 vs 1350.90 if summed first).
- **Cascades**: depth-3 `maturity-scan` → field OVERAGED → PENDING batches CANCELLED → CONFIRMED orders revert to PLACED; depth-2 crew-deactivate → referrals REPLACED → order referral status NONE.
- **Priority conflicts**: state-vs-temporal (confirm on CANCELLED + expired cutoff → `ERR_ALREADY_TERMINAL`) and temporal-vs-fiscal (cutoff passed + zone capacity full → `ERR_CUTOFF_PASSED`).
- **Boundaries**: strict `<` cutoff (14:00:00 fails, 13:59:59 succeeds), capacity at exactly 4 consumers, freshness exactly 24.0h deliverable, maturity day 60 vs 61, moisture 40.0 vs 39.99 credit tiers, tier turf exactly 2000.00.
- All numeric asserts pre-computed via executed Python (Decimal, round-half-up) — e.g., pricing ladder totals 938.20/2199.12/3980.17/4633.76, delivery-check window sizes 855.00/1463.30, chargeables 1013.83/1351.78, warranty credits 100.00/0.00, reseed target 240.00 lbs.

## Step 4: Generate PRD — 2026-08-13T12:32:45.000Z

(Recovered during resume — subagent summary lost with the terminated run.) `workspace/PRD.md` was produced at 2026-08-13T12:32:45Z (51,355 bytes, 333 lines): 5 major sections (Introduction; Global Specifications incl. RBAC, envelope, pagination, clock, rounding, rate cards, OCC, validation precedence, cascades; Business Logic §3.1–§3.9; Endpoint Definitions; Error Code Catalogue with 20 domain errors). Structure verified complete via section-heading audit; content spot-check confirms full domain coverage (rate cards/varieties/customers/crews, maturity cycle + re-seed rotation, harvest yield + quality gate, quoting + pricing ladder, order confirmation cutoffs/capacity/allocation, dispatch/delivery/settlement, delivery verification + reconciliation, crew referral, warranty + watering compliance). Both design-index YAMLs were withheld from generation per spec. Missing: `test_helpers/`, `test_suite/`, `workspace/implementation/` — pipeline resumes at Steps 5+6.

## Step 5: Generate Unit Tests — 2026-08-13T13:05:00.000Z

Generation complete. Summary:

## Counts

**Queue A (Difficulty, §1.8): 18/18 instances covered, 36 tests (exactly 2 per instance)** — all translated, none skipped.

**Queue B (Corner, §1.9): 55/55 non-stub instances covered, 55 tests (1 each)** — none skipped.
- 3 stubs correctly NOT translated, pointers verified to resolve: `maturity_boundary_age_60_vs_61` → `harvest_batch_gated_by_field_maturity_and_quality`; `mark_delivered_topup_self_loop` → `delivery_window_cumulative_vs_strict`; `derived_field_reconciliation_after_checks` → `order_money_conservation_across_checks_and_payments`.

**Total: 91 tests**, all collecting cleanly under pytest with `prd_bench_local_runner` importable; every test carries exactly one `Design:` tag that resolves to a real instance (verified programmatically), and every quoted PRD citation in every docstring survives a literal whitespace-normalized grep of PRD.md (verified programmatically).

## Files written

- `test_helpers/`: `__init__.py`, `types.py` (14 entity TypedDicts — Payment/DeliveryCheck/WateringLog correctly omit `updated_at`/`version` per PRD §2.4 — 16 enums), `api_client.py` (55 endpoint methods), `api_errors.py` (28-error catalog + `set_error_http_status_map` registration), `assertions.py` (per-entity + instant-normalizing comparator + the two conservation-invariant checkers), `factories.py`, `constants.py`, `test_users.py` (opaque role constants + mandatory `make_customer_headers` builder for the entity-backed Customer role), `fixtures.py` (version-threading `create_batch`, primitive builders, `mini_chain` 7-stage lifecycle fixture, `w1500_chain` composite for the delivery-check/money scenarios).
- `test_suite/`: `conftest.py` + 11 test files grouped by concern (pricing, quotes, fields/re-seed, harvest batches, confirmation/capacity, lifecycle/delivery, checks/payments, crews, warranty, cascades, RBAC).

## Deviations / coverage notes

1. **`new_draft_quote_supersedes_existing_draft` (queue B)**: the instance asserts accept-on-SUPERSEDED → `ERR_ALREADY_TERMINAL`, but PRD §3.4 verbatim assigns `ERR_INVALID_STATE` to that case ("an accept attempted against a `SUPERSEDED` or `EXPIRED` quote is rejected with `ERR_INVALID_STATE`"). PRD is the contract; the test asserts `ERR_INVALID_STATE` (a design-index/PRD discrepancy worth flagging upstream — the scaffold state machine agrees with the PRD; only the corner instance's literal is wrong).
2. **Absolute `version` literals**: PRD §2.4 says version "increments with every modification" but never pins the post-create value to 1, so exact-start assertions (`version == 1`, `version == 3`) are not uniquely derivable. The three affected instances (`field_create_client_supplied_system_fields_input_ignored`, `occ_stale_field_version_rejected_then_retry_ok`, `version_increments_on_each_mutation`) are fully translated using exact relative deltas (`v+1` per mutation, `v+2` after two creates, `!= 99` for the ignored client counter) — the OCC error and increment claims are preserved at full strength.
3. **Truck-block capacity tests** (`zone_truck_capacity_exactly_at_limit`, `zone_fleet_half_open_aggregate_overlap`): recipes omit creating a PriceConfig; the fixtures create one anyway so the "four by default" capacity (PRD §3.5) is unambiguous regardless of whether the implementation requires a current card.
4. No skips/xfails, no freelance tests, no scaffold references in generated code; nothing written outside `test_helpers/` and `test_suite/` (a temporary audit script was created for verification and deleted).

## Step 6: Generate Implementation — 2026-08-13T13:10:00.000Z

All verification complete. The final server self-terminated via `timeout` as intended.

## Summary

Complete Python + Flask implementation for the Sod Farm & Turf Supply task at `/home/ubuntu/github/CodingPRD/tasks/task_1469_sod_farm_turf_supply/workspace/implementation/`.

**Files written**
- `start.sh` — executable launcher: guarded dependency install (no-op when Flask importable), then `exec python3 app.py` in the foreground
- `requirements.txt`, `app.py` (entry point, blueprint registration, envelope-consistent 404/405/400/500 handlers)
- `db.py` — in-memory dict store keyed by id, logical clock (defaults to exactly `2026-08-01T00:00:00Z`, never wall-clock), monotonic unique ms-precision stamps, version-bump helper
- `errors.py` — `ApiError` + all 28 error IDs with their HTTP statuses
- `util.py` — `Decimal` half-up rounding (2dp money, 4dp blended rate), ISO-8601 parse/format with 3 fractional digits, response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in meta), request validators
- `auth.py` — `X-User-ID`/`X-User-Role` authentication, role gating, Customer ownership checks
- `serialize.py` — per-entity serializers resolving computed fields at read (maturity, allocated_sqft, total_paid/amount_due/credit_balance)
- `calc.py`, `services.py` — calculation engine and cascades
- `routes/` — 10 blueprints: configs, customers, crews, fields (incl. reseed plans), harvest, quotes, orders, referrals, warranty, fleet (truck blocks + `/_clock/set_current_utc`)

**Endpoints**: all 57 from the endpoint table, verified registered.

**State machines**: Field (ACTIVE→ARCHIVED), FieldMaturity (SEEDED→GROWING→READY→MATURE→OVERAGED with lazy recompute, no version bump, conditional 3-hop OVERAGED cascade), ReSeedPlan, HarvestBatch, Quote (incl. lazy EXPIRED on accept and DRAFT supersede), Order parallel dimensions (fulfillment PLACED→…→CLOSED/CANCELLED × payment PENDING↔PAID with both auto-joins), CrewReferral, WarrantyClaim.

**Calculation modules**: maturity classification (inclusive young-leaning bands), pallet yield, per-line-round-then-sum turf contribution, freight cell, pricing ladder (pre-discount tier evaluation, CARD discount-then-fee vs CASH_CHECK flat 3%, informational `additive_total`/`cash_price`), freshness projection (PENDING = scheduled 08:00Z, `0 ≤ h ≤ 24`), half-open zone capacity (4-consumer boundary shared with TruckBlocks), waterfall allocation (freshest-first, sellable-ASC, created-ASC; `ERR_BATCH_NOT_FRESH` vs `ERR_ORDER_UNDER_ALLOCATED` split), delivery-check window (cumulative authoritative + strict informational), balance reconciliation (conserved quantity), watering credits, reseed target, field availability netting PENDING reservations, strict confirm cutoff. OCC via `expected_field_version` → `ERR_STALE_FIELD_VERSION` (412). All 12 validation tiers evaluated in scaffold priority order.

**Verification**: 225 ad-hoc checks across three suites (90 smoke + 102 deep-machinery + 33 edge/precedence), all passing, each against a fresh process boot. One real bug found and fixed during testing (OVERAGED revert now clears `order_id` on *all* linked batches including cascade-cancelled ones, so reseed-after-overaged recovery isn't blocked). No seeding, no disk persistence — fresh boots return empty collections.

**start.sh contract confirmed**: honors `$PORT` (default 10000), binds `0.0.0.0` (verified via `ss`), runs in foreground via `exec`, HTTP-ready in ~2s.

## Step 7: Run Tests and Iterate — 2026-08-13T13:25:00.000Z

All 8 rounds now pass 91/91 — clean sweep, no flakiness.

## Summary

- **Iterations run:** 2 (initial sweep → fix → verification sweep).

- **Tests deleted:** none.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1469_sod_farm_turf_supply/test_suite/test_07_delivery_checks_payments.py` — added missing `validate_paginated` to the `from test_helpers import (...)` list. `test_payment_entity_is_append_only` referenced it at line 262 (`validate_paginated(api.list_payments(o_id, SALES))`) without importing it, raising `NameError: name 'validate_paginated' is not defined` in all 8 rounds. The test's assertions (Payment carries only `id`/`created_at`, no `version`/`updated_at`) trace verbatim to PRD §2.4 ("Three append-only sub-resources break this pattern: a `Payment`, a `DeliveryCheck`, and a `WateringLog` each carry only `id` and `created_at`"), so the test stays — only the import was fixed. No assertion was weakened.

- **Fixes applied to `test_helpers/`:** none needed (the symbol is correctly exported from the package barrel).

- **Fixes applied to `implementation/`:** none — the implementation was already fully PRD-faithful; the only failure in the union across all 8 rounds was the test-side `NameError`.

- **Final state:** all 8 parallel rounds report 91/91 passed.

## Step 8: Finalize PRD — 2026-08-13T13:35:00.000Z

The workspace doesn't contain `test_suite/` or `test_helpers/` — only `INSTRUCTION.md`, `PRD.md`, and `implementation/`. The Step 7 diff referenced test files that live outside the workspace (runner-side), and in any case the single Step 7 item was a pure test-side `NameError` import fix with no behavioral content and no implementation change.

Conclusion per the mandated method:

1. **The single Step 7 item maps to zero PRD edits.** It was a missing symbol in a test file's import list — a pure fixture/harness bug. The implementation needed no fix and the test's assertions trace verbatim to existing PRD §2.4 prose.
2. **PRD §2.4 (line 89) already fully pins the append-only shape.** I verified all three serializers in `implementation/serialize.py` (`pub_payment` L220-228, `pub_delivery_check` L231-248, `pub_watering_log` L279-287): each emits `id` and `created_at` and omits `updated_at`/`version`, exactly as the PRD sentence claims. The PRD's scoping of "only `id` and `created_at`" to the four system-managed properties is disambiguated by the following sentence and matches the impl.

Therefore `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` — a valid outcome per the task note.

---

**Summary on exit**

- **PRD.md vs PRD_FINALIZED.md:** 333 lines vs 333 lines — 0.0% delta (byte-identical copy at `/home/ubuntu/github/CodingPRD/tasks/task_1469_sod_farm_turf_supply/workspace/PRD_FINALIZED.md`).
- **Changes:** none.
- **Per-edit pre-edit search log:** no edits were committed, so no pre-edit searches were triggered. The verification work performed in lieu of edits:
  - (a) Subject checked: PRD §2.4 append-only sub-resource claim (the only PRD text cited by the Step 7 diff).
  - (b) Impl paths enumerated and read: `workspace/implementation/serialize.py` — `pub_payment` (L220-228), `pub_delivery_check` (L231-248), `pub_watering_log` (L279-287), plus the `_base` helper (L27-33) confirming the four-property pattern the three sub-resources deviate from. Also grepped PRD.md for all `Payment`/`DeliveryCheck`/`WateringLog` mentions (L89, L218) to confirm no other PRD sentence conflicts.
  - (c) Wording adjustment: none needed — existing prose matches all enumerated serializers exactly.

## Step 9: Complete PRD — 2026-08-13T13:58:00.000Z

PRD_COMPLETED.md is complete. All 16 changes verified in the diff; line count unchanged at 333 (all edits are inline).

## Summary

**Source vs output:** `workspace/PRD_FINALIZED.md` (333 lines, 51,355 chars) → `workspace/PRD_COMPLETED.md` (333 lines, 53,576 chars). Char delta: **+2,221**. No sections added; all changes are inline inserts/revisions within existing paragraphs.

**Counts:** 15 ambiguity-pins, 1 mismatch-revision (16 total).

**Changes (one per bullet):**

- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped into range (limit to [1,100], negative offset to 0) rather than rejected; non-integer values are rejected with `ERR_INVALID_REQUEST` — implementation/util.py:134-147
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — implementation/db.py:65-74
- §2.7 — insert — ambiguity — reads that never pass through a quote/order (harvest-batch scheduling and completion, truck-block capacity) go against the live current card, falling back to documented defaults when no rate card exists — implementation/calc.py:21-66, routes/harvest.py:54,149, routes/fleet.py:31
- §3.1 — insert — ambiguity — crew `service_zones` must be non-empty (else `ERR_INVALID_REQUEST`); the `active` list filter accepts case-insensitive tokens `true`/`1`/`yes` and `false`/`0`/`no`, rejecting anything else with `ERR_INVALID_REQUEST` — implementation/routes/crews.py:22-24, 39-47
- §3.2 — insert — ambiguity — quality update accepts any subset of the four agronomic inputs (omitted inputs unchanged); quality update and maturity scan on an `ARCHIVED` field are rejected with `ERR_ALREADY_TERMINAL` — implementation/routes/fields.py:96-109, 116-117
- §3.2 — insert — ambiguity — archive guard violations (live batches / active plan) rejected with `ERR_INVALID_STATE`; re-archiving with `ERR_ALREADY_TERMINAL` — implementation/routes/fields.py:126-133
- §3.2 — insert — ambiguity — opening a re-seed plan on an archived field is refused with `ERR_ALREADY_TERMINAL` — implementation/routes/fields.py:146-147
- §3.2 — insert — ambiguity — a negative `actual_seed_lbs` fails earlier at request shape with `ERR_INVALID_REQUEST`, not `ERR_SEED_SHORTFALL` — implementation/routes/fields.py:210, 215-217
- §3.3 — insert — ambiguity — a `scheduled_date` before the clock's current date is rejected with `ERR_INVALID_REQUEST` — implementation/routes/harvest.py:48-49
- §3.4 — insert — ambiguity — a quote line whose computed yield is zero or below is rejected with `ERR_INVALID_REQUEST` (same rule as harvest batches) — implementation/routes/quotes.py:81-85
- §3.4 — insert — ambiguity — quote creation with no current rate card in the system is rejected with `ERR_INVALID_REQUEST` — implementation/routes/quotes.py:78-80
- §3.6 — insert — ambiguity — dispatch disregards linked batches already `CANCELLED` by a cascade when requiring linked batches to be `COMPLETE` — implementation/routes/orders.py:145-147
- §3.6 — revise — mismatch — on `ERR_DELIVERY_STALE` the order's status is left unchanged (still `OUT_FOR_DELIVERY` before first delivery, still `DELIVERED` on a top-up); PRD had said the order "stays `OUT_FOR_DELIVERY`", which is false for the self-loop; also pinned that freshness is measured over linked, non-cancelled batches — implementation/routes/orders.py:169-181
- §3.6 — revise — ambiguity — the `INSTALLED`→`CLOSED` auto-join fires on any §3.7 reconciliation (payment or delivery check), not only on payments — implementation/services.py:83-93, routes/orders.py:256
- §3.6 — insert — ambiguity — a cancelled order retains its booked window fields for the record; capacity release works via status-based consumer counting (only `CONFIRMED`/`OUT_FOR_DELIVERY` orders consume) — implementation/routes/orders.py:132-134, calc.py:183-196
- §3.9 — insert — ambiguity — claim window is inclusive at exactly `installed_at` + 30 days; a claim attempt on a `delivery_flagged` order is rejected with `ERR_INVALID_STATE`; a new claim starts with `resolution` `NONE` and `credit_amount` 0.00 — implementation/routes/warranty.py:51-57, 65-77

**Coverage check:** all 54 endpoints in the §4 table match the implementation's role lists and 201/200 conventions exactly; all 28 error-catalogue entries match `errors.py`; all pricing-ladder, freshness, capacity, allocation, delivery-check, and watering formulas in the PRD already matched `calc.py` verbatim (verified line by line), as did all state machines, cascades, filters, and the validation tier ordering — those required no change.

# Worklog — task_1925_farm_stand_u_pick_operation

## Step 1: Create task directory — 2026-08-15T01:15:00.000Z

Directory `tasks/task_1925_farm_stand_u_pick_operation/` and `workspace/` pre-created by the pipeline invoker (per command args); verified present by orchestrator at pipeline start. Difficulty target: harder than expert level (user request).

## Step 2: Generate scaffold — 2026-08-15T02:02:18.321Z

All checks pass. The scaffold package for task 1925 is complete and verified.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_1925_farm_stand_u_pick_operation/SCAFFOLD.yaml
  Difficulty design:  tasks/task_1925_farm_stand_u_pick_operation/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_1925_farm_stand_u_pick_operation/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     13
  §1.8 instances scanned:     20
  §1.9 instances scanned:     46
  Calls scanned (§1.8+§1.9):  851

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary (verbatim counts)

- **Entity count:** 13 (Season, Crop, Field, FieldDayWindow, PricingPolicy, Waiver, VisitSession, HarvestLine, AddonProduct, AddonBooking, Payment, SalesDay, OfflineBatch)
- **State machine count:** 11 (incl. cyclic Field rotation DORMANT→OPEN→PICKED_OUT→ROTATION_REST→DORMANT; parallel visit_status × payment_status on VisitSession)
- **Calculation count:** 10 (admission_charge, weigh_out_total, checkout_settlement, field_remaining_oz, weather_refund, staffing_requirement, window_slot_capacity, addon_slot_capacity, payment_status_derive, offline_batch_apply)
- **Endpoint count:** 59 (incl. `POST /farm/_clock/set_current_utc` with pinned startup default 2026-08-01T00:00:00Z, and `GET /farm/availability-calendar`)
- **Error catalog size:** 33
- **Difficulty-design instance count (non-stub):** 20 — dual_variant_calc 2, combinatorial_formula 3 (modes a/b/c), non_linear_state_machine 2, transitive_cascade 2 (depth-4 weather cascade, depth-3 depletion cascade), priority_pair_validation_conflict 2 (state-vs-fiscal, safety-vs-constraint), boundary_precision_check 3 (slot equality, zero-net tare, 12:00:00 refund tier), cross_entity_state_dependency 2, resource_temporal_overlap 2 (half-open windows vs aggregate addon capacity), compensating_invariant 2 (cents, ounces)
- **Corner-design instance count (non-stub):** 46, plus 13 `excluded_because:` stubs citing §1.8 coverage (59 total entries across 9 sections)
- **File paths written:**
  - /home/ubuntu/github/CodingPRD/tasks/task_1925_farm_stand_u_pick_operation/SCAFFOLD.yaml
  - /home/ubuntu/github/CodingPRD/tasks/task_1925_farm_stand_u_pick_operation/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  - /home/ubuntu/github/CodingPRD/tasks/task_1925_farm_stand_u_pick_operation/SCAFFOLD_CORNER_DESIGN.yaml

## Key design decisions

- **Archetype blend:** quota/allocation (window slots, parking, harvest ounces, addon slots) + pricing engine (surge admission vs weigh-out, bundle discount, refund tiers); layers: optimistic concurrency (2 OCC rules: policy-create on Season.version, field-edit on Field.version), cascading side effects, dual-variant calculation, idempotency.
- **Offline sync semantics:** append-only OfflineBatch idempotent on (device_id, batch_id); records apply in sequence_index order; VISIT_SESSION/PAYMENT/HARVEST_LINE record types; capacity allowance +10 for offline sessions; weather-cancelled windows void synced sessions and fail their OFFLINE_CARD payments; offline lines are born PROVISIONAL and gate checkout (ERR_UNRESOLVED_LINES).
- **All numeric asserts pre-computed as literals** (e.g., surge admission 2838 vs 2350; per-line rounding 19+19=38 ≠ 39; bundle order 3300 with discount 300; noon-tier refund 525; paid-basis weather refund 2200 ≠ 4400).
- Verified mechanically beyond lint: grounds resolution, placeholder closure, cross-file name uniqueness, stub reference validity, enum-value closure, RBAC/endpoint role closure, response-envelope verbatim match, and zero forbidden concurrency vocabulary. No sibling task directories were inspected.

## Step 3: Copy shared files — 2026-08-15T02:02:41.825Z

Copied `./INSTRUCTION.md` → `tasks/task_1925_farm_stand_u_pick_operation/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T02:18:01.138Z

PRD generation complete. Output written to `/home/ubuntu/github/CodingPRD/tasks/task_1925_farm_stand_u_pick_operation/workspace/PRD.md`. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Summary

**PRD line count:** 327 lines

**Section list:**
- §1. Introduction (2 paragraphs)
- §2. Global Specifications & System-Wide Principles: 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim fixed block); 2.3 Pagination; 2.4 Logical Clock, Dates, and Units of Measure; 2.5 Common Resource Properties and Derived-Field Consistency; 2.6 Optimistic Concurrency Control; 2.7 Validation Pipeline and Error Precedence
- §3. Business Logic & Workflows: 3.1 Season Setup, Waiver Lifecycle, and Pricing Policy; 3.2 Crops, Fields, Rotation, and Harvest Tallies; 3.3 Sales Days, Picking Windows, and the Availability Calendar; 3.4 Gate Admission: Party Check-In and Capacity Gates; 3.5 Field Weigh-Out and Harvest Lines; 3.6 Agritourism Add-Ons: Products, Bookings, and Redemption; 3.7 Payments, Checkout Settlement, and Refunds; 3.8 Weather Closure and End-of-Day Sweeps; 3.9 Offline Devices, Batch Upload, and Sync Conflicts
- §4. Endpoint Definitions (59 rows, 4 columns)
- §5. Error Code Catalogue (33 rows, 2 columns) — document ends here, no audit footer

**Entity/rule coverage audit results (all three Hard Contracts PASS):**

```
Field coverage check (Contract 1):
- required identifiers (entities[].fields + common fields + endpoints[].input/query/path params): 91 required, 91 present, 0 missing
Status: PASS

Rule coverage check (Contract 2):
- validations[] priority ordering: 22 validation entries expressed as a 14-gate ordered pipeline in §2.7 with first-failure-wins semantics and the waiver trio's internal order (71→72→73) stated explicitly — 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (policy-create → expected_season_version + ERR_STALE_VERSION/412; field-edit → expected_field_version + ERR_STALE_VERSION/412; "no other endpoint accepts a version field" stated) — 0 missing
- state_machines[].transitions: 24 transitions across 11 machines checked, 24 fully expressed (from/to states, preconditions paired with error ids, all side-effect cascades including DEPLETED window scoping, successor pinning rule, weather 3-hop cascade, void reversal) — 0 missing
- calculations[]: 10 checked, 10 fully expressed in precise prose (admission charge, per-line-rounding weigh-out with the 38-vs-39-cents example, pinned 5-step checkout settlement, dual-basis field remaining, tiered weather refund with hard cap and paid-basis pinning, ceil-staffing with the 50-slots→2-staff boundary, window/parking capacity with equality-fills semantics, addon slot capacity, 6-branch payment_status derivation, offline batch apply) — 0 missing
- validations[] conditions: all 33 error ids matchable to trigger conditions in §2/§3 prose (verified mechanically: each appears in narrative AND in §5 table) — 0 missing
- endpoints[].side_effects / applies_to: 59 endpoints' side effects expressed in workflow narratives; all 59 rows present in §4 table (verified mechanically) — 0 missing
- entities[].fields[] structured content: defaults and nullability reconstructed in prose (current_waiver_version=1, policy_version first=1, tallies start 0, final_total_cents/checkout_mode/sync_outcome null semantics, cancel_reason null unless CANCELLED, rest_until lifecycle) — 0 missing
- sibling-branch symmetry: payment_status 6-branch chain, 3-tier weather refund, 3 checkout modes, 3 offline record types, 4 offline session failure modes all rendered with equal density — 0 asymmetric
- enum coverage: 52/52 enum/state values present verbatim; roles 5/5 present
Status: PASS

Path purity check (Contract 3, §3 only):
- backtick tokens scanned: 682
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Zero-Silence Rule adjudications** (points where the scaffold nominates no error id or is internally terse; I expressed the rule without inventing identifiers):

1. **Season activation conflict** — scaffold's `DRAFT → ACTIVE` precondition ("no other Season ACTIVE") nominates no error id; PRD says the activation "is rejected as a conflict" without assigning a code.
2. **Season archive / field retire precondition failures** — same treatment (rule stated, no invented error id); own-state misuse remains under `ERR_INVALID_STATE` per validation priority 50.
3. **Field tallies at creation** — scaffold declares `default: 0` for both tallies while the formula would imply `projected_remaining_oz = estimated_harvest_oz` for a line-less field. PRD transcribes both statements verbatim-faithfully ("a new field starts with both tallies at zero; from then on recomputed immediately inside every mutating request") and does not resolve the tension.
4. **`origin` at the gate endpoint** — scaffold endpoint says "ONLINE origin only" but nominates no error; PRD assigns non-`ONLINE` values to the request-shape gate (`ERR_INVALID_REQUEST`).
5. **`ERR_LINE_NOT_PROVISIONAL`** — present in the error catalog but not referenced by any transition precondition; PRD wires it to finalizing a non-`PROVISIONAL` line, placed at the own-state (409) tier per its catalog semantics.
6. **Public waiver endpoint with non-Anonymous credentials** — validation 10 exempts waiver signing from authentication while validation 11 applies authorization to all endpoints; PRD states headerless access is allowed and a credentialed non-`Anonymous` caller is `ERR_FORBIDDEN`.
7. **OCC mismatch direction** — scaffold rules say "below current version"; PRD requires exact equality and notes lower-than-current is the only observable mismatch since versions only increase.
8. **Weather add-on release scope** — PRD preserves the scaffold's parenthetical that face-value refunds on weather release apply even to bookings of already-`CHECKED_OUT` sessions.
9. **`OFFLINE_CARD` at the online collection endpoint** — scaffold does not forbid it; PRD describes per-method settlement timing (immediate for `CASH`/online `CARD`, at batch apply for `OFFLINE_CARD`) without inventing a prohibition.

## Step 5: Generate unit tests — 2026-08-15T02:43:21.825Z

All checks pass. Generation is complete and verified.

## Summary

**Task**: task_1925_farm_stand_u_pick_operation — full test infrastructure generated.

### test_helpers/ (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1925_farm_stand_u_pick_operation/test_helpers/`)
- `types.py` — 19 status enums + role enum + 13 entity TypedDicts (all entities carry `common_fields: true`, so all include id/created_at/updated_at/version)
- `constants.py` — TARE_OZ_PER_CONTAINER=4, OZ_PER_LB=16, STAFF_COVERAGE_SLOTS_PER_STAFF=25, OFFLINE_OVERBOOK_ALLOWANCE_SLOTS=10, FIELD_REST_DAYS=7, POLICY_A/B literals, shared dates, `round_half_up`
- `api_errors.py` — all 33 error IDs with the §5 HTTP status map, registered via `set_error_http_status_map`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (all 59 paths incl. `/farm/_clock/set_current_utc` and `/farm/availability-calendar`)
- `factories.py` — 13 payload factories + 3 offline batch record builders
- `test_users.py` — `TEST_USERS` for all 5 roles (all opaque; Anonymous constant omits `X-User-ID` per PRD §2.1) + per-instance `make_*` builders
- `assertions.py` — per-entity `assert_*` + session-money and field-tally invariant checkers
- `fixtures.py` — composite builders: `setup_operating_day` (flag-driven season→policy→crop→field→day→window→waiver chain), `admit_online_session`, `pay_admission`/`pay_amount`, `setup_paid_session`, `weigh_out`, `book_addon`, `upload_batch`, entity readers
- `__init__.py` — barrel export (framework + PRD-specific)

### test_suite/ (conftest.py + 9 files, 86 tests total)
| File | Tests | Queue A | Queue B |
|---|---|---|---|
| test_01_envelope_rbac_and_not_found.py | 8 | 0 | 8 |
| test_02_admin_entities_and_scheduling.py | 9 | 0 | 9 |
| test_03_field_window_lifecycle.py | 10 | 4 | 6 |
| test_04_admission_gates.py | 13 | 4 | 9 |
| test_05_pricing_checkout_and_payments.py | 19 | 14 | 5 |
| test_06_harvest_tallies_and_depletion.py | 14 | 10 | 4 |
| test_07_addons_and_availability.py | 4 | 2 | 2 |
| test_08_weather_close_and_refunds.py | 6 | 6 | 0 |
| test_09_offline_batches.py | 3 | 0 | 3 |

### Coverage vs design indices
- **Queue A (Difficulty)**: 20/20 instances covered, exactly 2 tests each (40 tests). No shortfalls.
- **Queue B (Corner)**: 46/46 non-stub instances covered, exactly 1 test each. All 13 `excluded_because:` stubs verified to resolve to existing §1.8 instance names and were not translated.
- Automated audit confirmed: every test has exactly one `Design:` tag as its docstring's last line; no dangling tags; no untagged tests.

### Skipped instances
None. Every non-stub instance in both queues passed the PRD-first two-condition filter (verbatim coverage + unique derivability).

### Two-reader relaxations applied (no tests skipped; non-derivable sub-assertions omitted)
- `season_create_applies_defaults_and_system_fields`: PRD §2.5 never states the initial `version` value (only the +1-per-mutation rule), so the literal `version == 1` assertion was omitted; DRAFT status, `current_waiver_version == 1`, UUID id, and the inverted-range 400 rejection (all PRD-explicit) are asserted.
- OCC tests (`occ_policy_create_stale_version_rejected`, `occ_field_patch_stale_version_rejected`) and `field_open_twice_returns_invalid_state` use relative version comparisons (captured before/after) instead of absolute literals like `version == 3`, per the same rule.

### Verification performed
- `py_compile` clean on all 18 files; `pytest --collect-only` collects exactly 86 tests with zero import errors; every name imported from `test_helpers` resolves through the barrel.
- PRD citation pass: every quoted span in every docstring survives whitespace-normalized literal grep of `workspace/PRD.md` (2 initial misses from markdown `**` gate-label prefixes were fixed by quoting from after the bold marker).
- No `pytest.mark.skip`/`skipif`/`xfail`; no "scaffold" references in generated code.

## Step 6: Generate implementation — 2026-08-15T02:54:55.347Z

Implementation complete and verified. Summary below.

## File list
All under `/home/ubuntu/github/CodingPRD/tasks/task_1925_farm_stand_u_pick_operation/workspace/implementation/`:

- `start.sh` — guarded `pip install` (skips when flask importable), `exec python3 app.py`, foreground
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry, blueprint registration, error handlers (ApiError, 404, 405, 500), binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory stores (13 dicts, **empty at boot, zero seeding**), logical clock (starts exactly `2026-08-01T00:00:00Z`), monotonic strictly-increasing `created_at` timestamps
- `errors.py` — all 33 error IDs with their HTTP statuses
- `helpers.py` — envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta `limit`/`offset`/`total_count`/`has_more`), auth (`X-User-Role`/`X-User-ID`, Anonymous exemption on `POST /farm/waivers` with 403-on-presented-role), body-shape validators, integer `round_half_up_div` = `floor((n*2+d)/(2d))`
- `domain.py` — derived fields (tallies, aggregates, payment_status ladder), admission/weigh-out/checkout/weather calculations, refund allocator (SETTLED→oldest-first, hard-capped at net collected), PICKED_OUT cascade, serializers
- `routes/` — `seasons.py`, `crops.py`, `fields.py`, `windows.py`, `policies.py`, `waivers.py`, `sessions.py`, `harvest_lines.py`, `addons.py`, `payments.py`, `sales_days.py`, `offline_batches.py`, `misc.py` (availability-calendar + `_clock/set_current_utc`)

## Endpoint coverage: 59/59 vs PRD §4
Every row of the §4 table is implemented (verified by route listing: 5 seasons + 3 crops + 6 fields + 5 windows + 3 policies + 4 waivers + 6 sessions + 5 harvest-lines + 3 addon-products + 5 addon-bookings + 4 payments + 6 sales-days + 2 offline-batches + availability-calendar + clock = 59).

## State machine coverage: 11/11
Season (DRAFT→ACTIVE→ARCHIVED with one-ACTIVE + archive preconditions), PricingPolicy (ACTIVE→SUPERSEDED, version chain, Season.version bump), Field (DORMANT→OPEN, OPEN→PICKED_OUT auto-cascade with successor pinning lowest-rotation_order/created_at-ASC, PICKED_OUT→ROTATION_REST at close-day with rest_until=date+7d, ROTATION_REST→DORMANT inclusive sweep at open-day, any→RETIRED), FieldDayWindow (SCHEDULED→OPEN gated field/day/clock, →CANCELLED with MANUAL/DEPLETED/WEATHER reasons, OPEN→CLOSED at close-day), VisitSession (CHECKED_IN→FIELD_ACTIVE→CHECKED_OUT, CANCELLED, VOIDED; parallel payment_status derived per the 6-branch ladder), HarvestLine (PROVISIONAL↔FINALIZED/VOIDED with compensating tally reversals), AddonBooking (BOOKED→REDEEMED/RELEASED), Payment (PENDING→SETTLED/FAILED, →PARTIALLY_REFUNDED→REFUNDED), SalesDay (PLANNED→OPEN→CLOSED_NORMAL/CLOSED_WEATHER), OfflineBatch (append-only APPLIED/PARTIALLY_APPLIED with exact replay), Waiver (SIGNED→VOIDED; staleness computed, never stored).

## Calculation coverage: 10/10
admission_charge (weekend surge on admission component only, round-half-up at surge only), weigh_out_total (per-line round-then-sum; verified 19+19=38 example), checkout_settlement (pinned 5-step order; bundle requires REDEEMED wagon AND cafe; cap vs bps min), field_remaining_oz (committed FINALIZED-only vs projected PROVISIONAL+FINALIZED bases), weather_refund (12:00/15:00 tiers, paid-basis admission component, container refund iff zero FINALIZED lines, BOOKED-dated-today addon face value, net-collected hard cap), staffing_requirement (ceil slots/25 incl. new window; 50→2 boundary), window_slot_capacity (online equality fills; offline +10 allowance → VOIDED tombstone), addon_slot_capacity (BOOKED+REDEEMED pool per product/date/slot; equality fills), payment_status_derive (exact branch ladder), offline_batch_apply (sequence_index order, per-record SYNC_CONFLICT semantics, (device_id,batch_id) replay identity).

## Test results
`prd-bench-local-run --isolation per-test-server` (two runs): **84 passed, 2 failed** both times. The 2 failures are test-suite bugs, not implementation bugs: `test_07_addons_and_availability.py::TestAddonSlotPool` calls `self._addon_world(api)` where `_addon_world` is a module-level function → `AttributeError` in test setup. The behaviors those tests target (slot-pool exact fill succeeds, overflow → ERR_ADDON_SLOT_FULL 422, independent slot_time pools) are implemented and pass in my independent smoke tests. (Runner note: `--start-command` must be `cd workspace/implementation && bash start.sh`; the plugin parses the `cd … &&` prefix for cwd.)

## PRD-interpretation decisions (each anchored to a quote)
1. **Policy create bumps Season.version even for the first policy** — endpoint side effect reads "increments Season.version by 1" unconditionally; OCC equality check (`expected_season_version == season.version`) satisfies §2.6.
2. **Window-open check order = field OPEN → day OPEN → clock hours** — §3.3/§4 list "field OPEN (`ERR_FIELD_NOT_OPEN`), the sales day … is `OPEN` (`ERR_DAY_NOT_OPEN`), and the logical clock reads within the window's hours (`ERR_OUTSIDE_WINDOW_HOURS`)" in that order; §2.7 tier-12's text does not list window-open among its cross-resource checks, and scaffold priority 84-vs-97 conflict is resolved by the PRD narrative order.
3. **Enter-field runs the waiver trio before window/field state** — §2.7: "the first failing gate wins", gate 9 (waiver trio, "guard session creation, enter-field, and offline session application") precedes gate 12 (cross-resource state).
4. **Cancel-time booking release does not refund separately; the full net-paid auto-refund subsumes it** — §3.4: cancellation "releases every `BOOKED` add-on booking … and auto-refunds the full net paid amount"; the AddonBooking side-effect text names only "Manual release and weather release" as refunded and "checkout-time release" as the single exception.
5. **`total_paid_cents` counts payments in {SETTLED, PARTIALLY_REFUNDED, REFUNDED}** — §3.7 defines it as "the sum of `amount_cents` over the session's `SETTLED` charge payments"; reading "SETTLED" literally would break the REFUNDED branch of the payment_status ladder ("`total_refunded_cents` >= `total_paid_cents` … means something was paid and then fully returned").
6. **Refund allocation consumes {SETTLED, PARTIALLY_REFUNDED} payments oldest-first** — Payment machine allows REFUNDED from "[SETTLED, PARTIALLY_REFUNDED]"; every refund path hard-caps at net collected per "money is never created".
7. **Window-create staffing check skipped when no SalesDay exists for the date** — §3.3 ties the gate to "the sales day's `staff_on_duty`"; no error code exists for a missing sales day at creation, and the window-open gate (`ERR_DAY_NOT_OPEN`) is the declared enforcement point.
8. **Payment idempotency replay returns 201 with the original payment** — §4 assigns the endpoint code 201; §3.7 says replay "returns the original payment instead of creating a duplicate" without specifying a distinct status.
9. **Field.version bumps on every weigh-out create/finalize/void incl. provisional voids and offline line uploads** — §2.6: "every weigh-out creation, finalization, or void on that field legitimately advances the field's version"; Crop.version bumps only when its FINALIZED tally changes.
10. **PICKED_OUT DEPLETED-cancel applies to SCHEDULED windows with date >= logical today** — §3.2: "windows of past dates are untouched, and today's `OPEN` window stays `OPEN` as a grace".
11. **Batch structural 400 limited to the §2.7 gate-4 trio** (non-empty records, known record_type, unique sequence_index, plus per-record presence of offline_ref/payload per §3.9 "Each record carries …"); malformed payload *contents* (missing keys, non-OFFLINE_CARD method, non-positive amounts, unresolvable pricing_policy_id) degrade to per-record SYNC_CONFLICT, since §3.9's conflict list is exhaustive and "a structurally invalid batch is rejected with ERR_INVALID_REQUEST and never persisted" covers only structure.
12. **`POST /farm/seasons/{id}/config` requires at least one of waiver_text/name** — §4 summary: "Bump waiver text … and/or rename"; "and/or" permits either alone but not neither.

## Step 7: Test/iterate loop — 2026-08-15T03:01:55.323Z

All 8 rounds pass 86/86 with zero non-passing tests. The sweep is clean.

**Summary**

- **Iterations run**: 2 (baseline sweep confirmed 84/86 in all 8 rounds with the same deterministic failure; post-fix sweep passed 86/86 in all 8 rounds).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `test_suite/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1925_farm_stand_u_pick_operation/test_suite/test_07_addons_and_availability.py` — `TestAddonSlotPool::test_slot_pool_exact_fill_succeeds` and `TestAddonSlotPool::test_slot_pool_overflow_and_independent_slot_time`: changed `self._addon_world(api)` to `_addon_world(api)`. The helper is a module-level function (line 20), not a class method, so the `self.` call raised `AttributeError` before any PRD logic was exercised. The assertions themselves (exact-fill success with `booked_value_cents = price_cents * qty`, overflow → `ERR_ADDON_SLOT_FULL` 422, per-`slot_time` pool independence) trace verbatim to PRD §3.6 line 179, so only the broken call was corrected — the setup chain and assertions were left untouched.

- **Fixes applied to `implementation/`**: none — the implementation was already PRD-faithful; the failures were purely a test-side call bug.

Orchestrator verification: all 8 `results.{1..8}.json` files independently re-read and confirmed `passed == 86, total == 86, failed == 0`.

## Step 8: Finalize PRD — 2026-08-15T03:04:21.147Z

## Summary

**PRD_FINALIZED.md produced with zero edits** — it is a byte-identical copy of PRD.md (diff confirms IDENTICAL).

### Line counts
- `PRD.md`: 327 lines, 57189 bytes
- `PRD_FINALIZED.md`: 327 lines, 57189 bytes
- Delta: **0 lines, 0.0%**

### Changes
**None.** The `<step_7_diff>` contains exactly one fix item, and it is a pure test-side fixture bug that reveals no PRD silence and no PRD/implementation mismatch:

- **§3.6 — no change** — The fix was `self._addon_world(api)` → `_addon_world(api)` in `test_07_addons_and_availability.py`, where `_addon_world` is a module-level function (test file line 20), not a class method. The `AttributeError` fired before any PRD logic was exercised. All four behaviors asserted by the two affected tests are already pinned verbatim in PRD §3.6 line 179 and match the implementation exactly, so no insert or revise was warranted.

### Pre-edit search log (for the single candidate edit, which concluded "no edit")

- **(a) Subject identified**: add-on booking slot-pool semantics — pool key, exact-fill success, overflow error, `booked_value_cents` formula, new-booking status.
- **(b) Impl paths enumerated and read**:
  - `workspace/implementation/routes/addons.py` (full file read): `slot_used()` lines 88-96 (pool keyed on `addon_product_id` + `booking_date` + `slot_time`, summing `qty` over `BOOKED`/`REDEEMED`); `create_booking` line 118 (`used + qty > slot_capacity` → reject, so equality succeeds); lines 144-145 (`booked_value_cents = price_cents * qty`, status `BOOKED`); `redeem_booking` lines 180-197; `release_booking_route` lines 200-210.
  - `workspace/implementation/errors.py` line 38: `ERR_ADDON_SLOT_FULL` → 422 (matches PRD's "(422)").
  - Repo-wide grep for `slot_used` / `release_booking`: sole slot-pool enforcement site is addons.py:118; release call sites (sessions.py:237, 258; sales_days.py:149, 254) concern §3.6 line 181 refund semantics, which the step_7_diff does not touch and which already match PRD.
  - Test file read: all four assertions map 1:1 onto PRD line 179 prose (`booked_value_cents = price_cents * qty`; "equality exactly fills the slot and succeeds"; "overflow is `ERR_ADDON_SLOT_FULL` (422)"; pool scope "sharing the same `addon_product_id`, `booking_date`, and `slot_time`" implies per-`slot_time` independence).
- **(c) Wording adjustment**: none needed — every enumerated path is already fully and uniquely described by the existing PRD §3.6 line 179 text; inserting anything would have been restatement, and any narrower wording risked a new mismatch (e.g., the PRD's unordered condition list for session/scope/slot checks deliberately leaves evaluation order open while impl checks slot capacity first — out of scope since no step_7_diff item flags it).

### Key finding
Step 7's own conclusion is verified independently: the implementation was already PRD-faithful; the only failure was a broken helper call in the test file. Per the method ("not every item is a PRD silence — some are pure fixture bugs"), a fresh implementer reading PRD.md already produces behavior equivalent to `implementation/` for everything the step_7_diff exercised, so PRD_FINALIZED.md stands as an unmodified copy.

## Step 9: Complete PRD — 2026-08-15T03:18:13.929Z

Done. `PRD_COMPLETED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1925_farm_stand_u_pick_operation/workspace/PRD_COMPLETED.md`.

**Summary**

- Source: `PRD_FINALIZED.md` (byte-identical to `PRD.md`), 327 lines / 57,189 chars → `PRD_COMPLETED.md` 327 lines / 60,472 chars. Char-delta **+3,283**; 17 paragraph-lines touched, all inline inserts/revisions; no sections added or removed; §4 endpoint table and §5 error catalogue untouched (implementation roles/paths/codes matched them exactly).
- Counts: **17 ambiguity-pins, 5 mismatch-revisions** (22 edits total).
- Cross-check: latest run `implementation/results.8.json` shows 86/86 tests passing.

**Changes** (impl paths are under `workspace/implementation/`):

- §2.3 — insert — ambiguity — pins `offset` ≥ 0 and that non-integer/out-of-range `limit`/`offset` yield `ERR_INVALID_REQUEST` (400) — helpers.py:96-117
- §3.1 — insert — ambiguity — `end_date` before `start_date` yields `ERR_INVALID_REQUEST` (400) — routes/seasons.py:34-35
- §3.1 — insert — ambiguity — activating a non-`DRAFT` season, or activating while another season is `ACTIVE`, is `ERR_INVALID_STATE` (409) — routes/seasons.py:66-70
- §3.1 — insert — ambiguity — archive precondition violations and archiving a non-`ACTIVE` season are `ERR_INVALID_STATE` (409) — routes/seasons.py:82-92
- §3.1 — insert — ambiguity — config with neither `waiver_text` nor `name` is 400; resubmitting identical `waiver_text` does not bump `current_waiver_version` — routes/seasons.py:108-113
- §3.2 — revise — **mismatch** — new field's `projected_remaining_oz` starts at `estimated_harvest_oz`, not "both at zero" (formula-derived; confirmed by test_07 asserting 1000 with no lines) — domain.py:103-109, routes/fields.py:47-61
- §3.3 — insert — ambiguity — staffing gate applies only when a sales day exists for the window's date — routes/windows.py:70-82
- §3.3 — insert — ambiguity — window-open evaluates the three conditions in stated order (field `OPEN`, then day `OPEN`, then clock) — routes/windows.py:130-147
- §3.3 — insert — ambiguity — availability calendar requires `from_date`/`to_date` (`ERR_INVALID_REQUEST` if missing/malformed), rows ordered by date → open_time → created_at ASC, non-paginated object envelope — routes/misc.py:18-58
- §3.6 — revise — **mismatch** — replaced "single exception is the checkout-time release": only manual and weather releases refund face value; checkout/cancellation/void releases refund nothing at release time (cancellation is followed by the §3.4 full net-paid auto-refund) — routes/sessions.py:235-237,256-261, routes/sales_days.py:147-149
- §3.7 — revise — **mismatch** — refund-recording targets settled charge payments in `SETTLED` *or* `PARTIALLY_REFUNDED` status with unrefunded remainder (not `SETTLED` only), with a clause making all other "SETTLED … oldest first" references name this mechanic — domain.py:262-285
- §3.7 — insert — ambiguity — idempotency-key replay short-circuits all later gates and returns the original payment with HTTP 201 — routes/payments.py:69-71
- §3.7 — revise — **mismatch** — `total_paid_cents` sums `amount_cents` over payments in `SETTLED`/`PARTIALLY_REFUNDED`/`REFUNDED` status (not `SETTLED` only) — domain.py:158-163
- §3.7 — insert — ambiguity — manual refund against a payment not `SETTLED`/`PARTIALLY_REFUNDED` is `ERR_INVALID_STATE` (409) — routes/payments.py:129-130
- §3.8 — revise — **mismatch** — dropped the "never granted a bundle discount" rationale (impl does pin a computed `bundle_discount_cents`); refund defined by tiers/portions alone — routes/sales_days.py:139-154
- §3.8 — insert — ambiguity — weather-forced checkout pins both `final_total_cents` and `bundle_discount_cents` via the §3.7 settlement, refund still governed by weather rules — routes/sales_days.py:139-154
- §3.9 — insert — ambiguity — offline session's `admission_charge_cents` uses the §3.4 formula against the payload policy; no sales day for the window's date → no `WEEKEND` surge — routes/offline_batches.py:62-67
- §3.9 — insert — ambiguity — fifth `VOIDED`/`SYNC_CONFLICT` failure mode, evaluated last: payload `pricing_policy_id` resolving to no policy (admission then 0) — routes/offline_batches.py:61-67,86-87
- §3.9 — insert — ambiguity — a record whose payload lacks a required field or has a wrong-typed value is a `SYNC_CONFLICT` with null `entity_id`, creating nothing (not a batch-level structural failure) — routes/offline_batches.py:47-54,128-129,176-177
- §3.9 — insert — ambiguity — `PAYMENT` record: non-`OFFLINE_CARD` method or non-positive amount conflicts with null `entity_id`; record's `offline_ref` doubles as the payment's `idempotency_key`, and a repeat applies against the original payment id — routes/offline_batches.py:128-129,149-152,160
- §3.9 — insert — ambiguity — `HARVEST_LINE` record: unknown `crop_id` and negative `net_oz` (tare > gross) also conflict, null `entity_id`, no line created — routes/offline_batches.py:185-190
- §3.9 — insert — ambiguity — structural validation runs before the (device_id, batch_id) replay check; a well-formed replay responds HTTP 201 with the stored batch — routes/offline_batches.py:221-246

Everything else in the implementation (endpoint set, RBAC lists, envelope shape, gate ordering per §2.7 pipeline, state machines, all formulas including per-line round-half-up, weather tiers, rest sweeps, batch semantics) was already uniquely pinned by the PRD and required no change.

## Pipeline complete — 2026-08-15T03:18:13.929Z

All 9 steps done. Final state: 86/86 tests passing across all 8 stability rounds; `workspace/PRD_COMPLETED.md` present; task directory contains SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/ (9 files), test_suite/ (conftest + 9 files, 86 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.

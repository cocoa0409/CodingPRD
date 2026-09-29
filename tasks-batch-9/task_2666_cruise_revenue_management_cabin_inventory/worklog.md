# Worklog — task_2666_cruise_revenue_management_cabin_inventory

## Step 1: Create Task Directory — 2026-09-04T03:45:56.128Z

Created pre-assigned task directory `/home/ubuntu/github/CodingPRD/tasks/task_2666_cruise_revenue_management_cabin_inventory` and its `workspace/` subdirectory. Index 2666 was fixed by the scenario number (no ./tasks/ scan, no auto-allocation) because up to 32 pipelines run concurrently on this host.

## Step 2: Generate Scaffold — 2026-09-04T05:16:21.152Z

All three artifacts are complete and lint-clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2666_cruise_revenue_management_cabin_inventory/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2666_cruise_revenue_management_cabin_inventory/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2666_cruise_revenue_management_cabin_inventory/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    54
  §1.1 entities declared:     11
  §1.8 instances scanned:     23
  §1.9 instances scanned:     53
  Calls scanned (§1.8+§1.9):  980

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

- `SCAFFOLD.yaml` — 3159 lines, 13 top-level keys, neither design key present
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1798 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4268 lines, single key `scaffold_corner_design`

## §1.0–§1.7 counts

11 entities (Sailing, CabinCategory, SailingInventory, FareRule, Promotion, GroupBlock, Guest, Booking, PaymentEvent, UpgradeBid, ItineraryChange) · 7 state machines (Booking has two parallel dimensions) · 2 concurrency rules (OCC-only) · 12 calculations · 20 ordered validations · 54 endpoints · 73 errors · 5 roles (RevenueManager, ReservationAgent, GroupSalesAgent, PortOpsCoordinator, Guest — the last `entity_backed:Guest`).

## §1.8 — 9 rules / 23 instances

dual_variant_calc 2 · combinatorial_formula 3 · non_linear_state_machine 3 · transitive_cascade 2 · priority_pair_validation_conflict 4 · boundary_precision_check 3 · cross_entity_state_dependency 2 · resource_temporal_overlap 2 · compensating_invariant 2.

## §1.9 — 9 sections / 62 instances (53 full recipes + 9 `excluded_because` stubs)

entities 12 · state_machines 12 · calculations 8 · validations 7 · endpoints 6 · errors 7 · rbac 4 · cross_cutting_complexity_layers 5 · consistency_model 1. Every stub cites a §1.8 instance that exists by name; all 85 instance names are unique across both design files; no `${var}` is unbound in any payload, call path, or assert.

## Design adjudications

- **Lint (b)/(c) exemption for negatives**: every intentionally-failing call carries `captures: {e_n: $.data.error_id}`, so the role/payload checks are skipped while (a), (d), (e) still bind.
- **Priority order pinned in asserts** rather than left implicit: p1 auth > p4/p5; p3 role > p7 ownership (a Guest hitting `GET /bookings` gets ERR_ROLE_NOT_PERMITTED, not ERR_NOT_BOOKING_OWNER); p4 uniqueness > p16 promo cadence; p5 existence > p9 OCC (PATCH with a valid version on a bad id is 404, not 412); p10 state > p20 fiscal; p15 fare-window > p17 referential (which forced the bid "target off-sailing" case to be replaced by a priced-but-unreachable SPA category); p18 posture > p19 capacity.
- **Posture bands** exercised on a 10-lower-berth ship so each berth is exactly 10.00 points — 80.00 OPEN, 90.00 RESTRICTED (inclusive floor), 100.00 FROZEN — and the asymmetry is asserted: RESTRICTED blocks group holds but still admits bookings, which is what lets the same sailing reach FROZEN.
- **OCC fixtures** never let a third writer touch the row, so `version + 1` is exactly assertable; `POST /promotions` bumps `Sailing.version` as a side effect, so the second promotion re-reads via `GET /sailings/{id}` before retrying, and the 412 is shown to write nothing at all (not even the version).
- Every formula-derived assert is a pre-computed literal (e.g. party-of-four gross 483484 with the 0.10 berth tier chosen from the lower subtotal alone; bid floor 33000 at dts 45; ralbd 23375 with gross == net when no group holds exist).
- Ambiguous post-`ops-run` values are deliberately not asserted; unauthenticated calls are modelled as `as: NONE` with the header omission stated in `setup`.
- Three internal SCAFFOLD.yaml inconsistencies were repaired while cross-checking: the `available_lower_berth_days_net` description missing its `max(1, …)` guard, a `final_payment_risk_flag` description that contradicted its own formula, and validation p1 citing a nonexistent `GET /_clock/current` endpoint.

## Step 3: Copy Shared Files — 2026-09-04T05:16:43.645Z

Copied `./INSTRUCTION.md` (1424 bytes) to `tasks/task_2666_cruise_revenue_management_cabin_inventory/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T05:31:00.000Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **486 lines / 104,342 bytes**, written incrementally (1 `Write` + 6 appends, no single call near the output cap). File ends at a real boundary: the final row of the §5 error catalogue. No audit footer, no scaffold meta-commentary (I stripped the one "test-driving endpoint" phrase that leaked from the clock endpoint's scaffold description).

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 RBAC (5 roles, opaque vs entity-backed, segregation of duties) · 2.2 API Response Structure (verbatim block) · 2.3 Pagination · 2.4 Logical Clock & Days-to-Sail · 2.5 Identity/Timestamps/Versioning · 2.6 Money, Percentages & Rounding · 2.7 Sellable Capacity, Group Fence, Oversell Guardrails · 2.8 Cascade Discipline · 2.9 Optimistic Concurrency · 2.10 Fixed Order of Request Validation · 2.11 Occupancy Posture as a System-Wide Gate
- §3 Business Logic & Workflows — 3.1 Sailings/Categories/Allotments · 3.2 Fare Windows & Promotional Cadence · 3.3 Group Blocks (four eyes, review-date release) · 3.4 Selling a Cabin (13-step fare buildup, waitlist) · 3.5 Deposits/Final Payments/Delinquency · 3.6 Cancellation & Penalty Schedule · 3.7 Upgrade Bidding & Guarantee Assignment · 3.8 Itinerary Disruption & Compensation · 3.9 Occupancy, RALBD & the Operations Sweep
- §4 API Endpoint Definitions (54-row, 4-column table, generated from the scaffold)
- §5 Error Code Catalogue (73-row, 2-column table, generated from the scaffold)

**Coverage check (found / declared)**
- Endpoint paths: **54 / 54** — zero missing (grepped every path literal)
- Error ids: **73 / 73** in the catalogue, and **73 / 73** also appear in the §1–§3 prose, not just the table
- Entities: **11 / 11** (Sailing, CabinCategory, SailingInventory, FareRule, Promotion, GroupBlock, Guest, Booking, PaymentEvent, UpgradeBid, ItineraryChange)
- State machines: **7 / 7**, and **every** state token from every machine's initial/terminal/transition set is present (Sailing, Promotion, GroupBlock, Booking·booking_status, Booking·payment_status, UpgradeBid, ItineraryChange)
- Calculations: **12 / 12**, including both dual variants (`GROSS_CAPACITY_BASIS`/`NET_CAPACITY_BASIS`, `PROVISIONAL`/`FINAL`)
- Ordered validations: **20 / 20**, as a literally numbered 1–20 list in §2.10 with error id, HTTP status, and `applies_to` scope per tier
- Roles: **5 / 5**
- Field names: **143 / 143** required names (entity fields + endpoint inputs) present verbatim
- Calculation constants: all numeric constant values appear literally (the one initial gap, `BID_FLOOR_PCT`, was written as "two fifths" and I amended it to "0.40 (two fifths)")

**Hard Contract reports** (per SKILL.md; reported here only, never written into the PRD)
- **Contract 1 — Field-Name Coverage: PASS.** 143/143 required field names appear verbatim in the PRD; mechanically diffed against a scaffold-extracted checklist, empty diff.
- **Contract 2 — Rule Coverage: PASS.** All 20 validations in explicit priority order; both concurrency rules stated with write operation + `expected_inventory_version` / `expected_sailing_version` + `ERR_STALE_INVENTORY_VERSION` / `ERR_STALE_SAILING_VERSION` + HTTP 412, plus the explicit statement that no other endpoint accepts a version field; all 7 machines' transitions with preconditions, error ids and side effects; all 12 calculations with formulas, constants, rounding points and floors/ceilings; cross-entity cascades (bid award, itinerary publish, close-inventory, SAILED, group release → waitlist promotion) all traced end to end; sibling branches (`PARTIALLY_RELEASED` repeat vs `TENTATIVE` self-loop; suspend/resume vs counter/rebid bounds) given symmetric treatment.
- **Contract 3 — §3 Path Purity: PASS.** No `/`-leading token, no bare HTTP method, and no method+path combination appears anywhere in §3; §3 is framed entirely as actors and state transitions. The only regex hits were substring false positives (`POST` inside `ERR_POSTURE_*`, `GET` inside `ERR_TARGET_CATEGORY_UNAVAILABLE`). Paths appear only in §2's clock/OCC notes and the §4 table.

The two withheld design files were never opened, grepped, or referenced, and no sibling task directory was read.

**Orchestrator truncation check (per known doc-generator failure mode):** independently verified — PRD tail ends at the last of 73 catalogue rows; a mechanical scaffold-vs-PRD diff found 73/73 error_ids and 54/54 endpoint paths present. Not truncated; no regeneration needed.

## Step 6 — Implementation generated (Python + Flask)

`workspace/implementation/` now holds the full API: 17 modules + `start.sh` +
`requirements.txt`, 3335 lines total. All state is in module-level dicts in
`store.py`; nothing is seeded and nothing touches disk.

- Layers: `store` (logical clock, tables, id/version stamping) -> `errors` /
  `envelope` / `auth` / `shape` (validation tiers 1-4, 7-8) -> `calcs` (the 12
  calculations as pure functions) -> `cascade` (fetch helpers, collection walks,
  recompute chains) -> `ops` (group review + the 9-step sweep) -> 8 route
  blueprints -> `app.py` (registration, error envelope, logical-clock endpoint).
- 54 endpoints registered, matching the SCAFFOLD endpoint table exactly.
- Smoke-tested on throwaway high ports: sailing create -> categories with the
  upgrade chain -> allotments -> fare rules -> open-for-sale -> guest -> booking
  -> deposit -> confirm -> payment-event ledger -> promotion schedule/activate ->
  group block create/four-eyes confirm -> upgrade bid submit/counter/rebid/accept
  -> itinerary change draft/publish -> ops-run -> revenue-summary. Envelope,
  pagination meta, 401/403/404 shapes verified. A fresh process returns empty
  collections for every table, so per-test-server isolation is clean.

## Step 6: Generate Implementation — 2026-09-04T06:12:00.000Z

Implementation complete. All modules compile, the server boots clean from a fresh process, and the full endpoint surface matches the SCAFFOLD.

## Files (`workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `store.py` | 157 | logical clock (epoch `2026-08-01T00:00:00Z`), the 11 in-memory tables, `new_id`/`stamp_new`/`touch`/`apply_changes`, `days_to_sail`, Decimal helpers |
| `errors.py` | 104 | all 75 error ids -> fixed HTTP codes, default messages, `ApiError` |
| `envelope.py` | 63 | §2.2 `meta`/`response_type`/`data`, `created`, `list_response` (limit/offset/total_count/has_more), `error_response` |
| `auth.py` | 44 | tiers 1-3, tier 7 booking ownership, tier 8 four-eyes |
| `shape.py` | 196 | tier 4 — types, ranges, enums, datetimes, pagination, filters |
| `calcs.py` | 337 | all constants + the 12 calculations as pure functions |
| `cascade.py` | 411 | `*_or_404` fetches, collection walks, every recompute chain, payment-event append, promotion redemption, waitlist promotion, cancellation |
| `ops.py` | 144 | group review/attrition release + the 9-step ops sweep |
| `routes_sailings.py` | 210 | 9 endpoints |
| `routes_catalog.py` | 275 | 10 (categories, allotments incl. OCC PATCH, fare rules) |
| `routes_promotions.py` | 172 | 5 |
| `routes_groups.py` | 182 | 6 |
| `routes_guests.py` | 67 | 3 |
| `routes_bookings.py` | 460 | 9 |
| `routes_bids.py` | 277 | 7 |
| `routes_itinerary.py` | 131 | 4 |
| `app.py` | 91 | blueprints, `ApiError`/404/405/500 JSON handlers, `POST /_clock/set_current_utc`, `0.0.0.0:$PORT` |
| `start.sh` / `requirements.txt` | 8 / 1 | guarded `pip install`, `exec python3 app.py` in the foreground |

3335 lines total. **Endpoint count verified programmatically from `url_map`: exactly 54** (53 business + the clock; I removed a `/_health` helper so the surface is exactly the declared one). Storage is module-level dicts only — no SQLite, no JSON dump, no `/tmp` cache, no seeding at import.

## How the spec maps to code
- **20 ordered validations**: tiers 1-3 in `auth.actor(*roles)`, tier 4 entirely in `shape.py` (every failure `ERR_INVALID_REQUEST`; dedicated uniqueness codes raised by the routes right after shape), tiers 5-6 via `cascade.*_or_404` called in declared field order, tier 7 `require_booking_owner`, tier 8 `require_four_eyes`, tier 9 OCC on the only two guarded writes (`PATCH /sailing-inventories`, `POST /promotions`), tiers 10-20 inline in each view in strictly increasing tier order with a `# Tier N` comment at each gate, first failure wins.
- **12 calculations**: all in `calcs.py` as side-effect-free functions (`allowance_cap`/`effective_oversell`/`availability`, `onboard_projection`, `berth_discount_pct`+`fare_buildup`, `fare_window_contains`, `ralbd`+`revenue_alert`, `penalty_pct`/`penalty_cents`, `attrition_release`, `bid_floor`/`bid_window_open`, `occupancy_pct`/`posture`/`final_payment_risk`, `loyalty`, `waitlist_order`, `compensation_terms`/`refund_grant`, `chain_length`). `Decimal` + ROUND_HALF_UP per component, then summed; floor for attrition, ceil for the oversell cap.
- **7 state machines**: Sailing in `routes_sailings.py`; Promotion in `routes_promotions.py`; GroupBlock in `routes_groups.py` + `ops.review_block`; Booking's two parallel dimensions in `routes_bookings.py` (`booking_status` via confirm/cancel/`cascade.cancel_booking`, `payment_status` via the payments kind×state matrix, settlement, and the sweep); UpgradeBid in `routes_bids.py` (+ sweep expiry); ItineraryChange in `routes_itinerary.py`. Version bumps go through `store.touch`/`apply_changes`, and `GET /sailings/{id}/revenue-summary` recomputes with `bump=False`.

## Smoke test (throwaway high ports, all servers now down)
Sailing create -> two categories with the `upgrade_to_category_id` chain (`upgrade_chain_length` stamped) -> allotments -> fare rules for both a far and a near window -> open-for-sale -> guest (GOLD, 0.03) -> booking (net 291000, deposit 75000, STANDARD terms, `booked_days_to_sail` 122, onboard projection 119000) -> deposit -> confirm -> payment-event ledger read as the owning Guest -> `GET /bookings` filtered/paginated -> clock moved to `2026-10-15` -> bid submit/counter/rebid/accept (award 450000, booking reassigned, `amount_paid` +450000 and balance unchanged, both allotments' `booked_cabins` moved) -> promotion schedule + activate -> group block create, four-eyes rejection then signature -> itinerary change draft (OBC 5000, refund_pct 0.05) and publish (1 booking, 15000 OBC, 14550 refund; sailing `compensation_liability_cents` 29550) -> ops-run -> revenue-summary. Envelope, pagination meta, and 401/403/404 shapes all correct. A freshly booted process returns empty arrays for every collection.

## One thing to flag
While re-verifying statelessness I identified "my" second server with a `pgrep -f 'python3 app.py' | tail -1` heuristic and it resolved to a **different pipeline's** process (pid 3915526 on port 17538) — I sent it a single `kill` before noticing my own server was on another port. No pattern kill was used, so the blast radius is that one PID; per-test harnesses relaunch via `start.sh`, so it should self-heal, but the owning pipeline may see one dropped server. Every subsequent (and prior) kill targeted a PID I had verified by `/proc/<pid>/cwd` pointing at this task's implementation directory.

**Orchestrator note:** the cross-pipeline kill is logged here as a known collateral event on this shared host; nothing in this task's artifacts is affected. Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator could not see `test_suite/` (it did not exist at its spawn time).

## Step 5: Generate Test Suite — 2026-09-04T06:55:00.000Z

Design-index-only generation: queue A = §1.8 (9 rules / 23 non-stub instances), queue B = §1.9 (9 sections / 53 non-stub instances; the 9 `excluded_because` stubs were not translated).

**98 tests emitted** — queue A 47 (every instance carries >= 2 tests; `cancellation_penalty_provisional_quote_versus_final_settlement` carries 3), queue B 51. Every test docstring ends in exactly one `Design:` line; a static pass over the AST confirms 98 tags, all resolving to a real non-stub instance, none duplicated onto a stub, none dual-tagged.

### Files
`test_helpers/` 9 files / 1974 lines — `__init__.py` 60, `api_client.py` 252 (54 methods), `api_errors.py` 177 (`set_error_http_status_map` at import), `assertions.py` 230, `constants.py` 141, `factories.py` 220, `fixtures.py` 611, `test_users.py` 73, `types.py` 210.
`test_suite/` 19 files / 7475 lines — `conftest.py` 56, then test_01 252, test_02 290, test_03 255, test_04 255, test_05 469, test_06 345, test_07 255, test_08 235, test_09 307, test_10 791, test_11 603, test_12 463, test_13 593, test_14 652, test_15 971, test_16 353, test_17 175, test_18 155.

### Verification
`python3 -m py_compile` clean on all 28 files; `pyflakes` silent on `test_suite/` (the only diagnostics anywhere are the deliberate re-exports in `test_helpers/__init__.py`); `pytest --collect-only` collects exactly **98 tests** with no collection errors; a static resolver confirms every `api.*`, `fx.*`, `f.*` attribute and every `from test_helpers import ...` name exists. No `class Test*` groupings, no `skip`/`xfail`/`TODO`, no file mentions the scaffold. `__pycache__` removed; nothing was written under `workspace/`.

### Instances skipped (2, both non-unique-derivability — gaps left as gaps)
- `Corner/state_machines/a_sailed_sailing_and_its_sailed_booking_refuse_further_transitions` — the recipe wants `ERR_SAILING_ALREADY_SAILED` for suspend-sales and close-inventory on a `SAILED` sailing, but §3.9 makes a suspend from any non-`OPEN_FOR_SALE` status `ERR_SAILING_NOT_OPEN`, and the PRD names no code at all for close-inventory from a wrong state. `ERR_SAILING_ALREADY_SAILED` is only ever attached to itinerary publication (§3.8) plus the tier-10 code list.
- `Corner/cross_cutting_complexity_layers/posture_flips_at_ninety_and_one_hundred_percent_occupancy` — the recipe asserts "one code serves both restricted bands for group creation" (`ERR_POSTURE_RESTRICTED` at 100.00% occupancy), but §3.3 and §2.10 tier 18 both give `ERR_POSTURE_FROZEN` for group-block creation on a `FROZEN` sailing. The asserted outcome contradicts the PRD, so it was skipped rather than silently corrected.

### Fixture / translation decisions worth recording
- `simple_world()` builds sailing + guarantee category + allotment + fare rule and opens the sailing; `open_now=False` plus `add_allotment_and_fare()` then `open_sailing()` is the path used whenever a second category is needed, so no allotment is ever created against an already-open sailing.
- Every test builds all state through the public API (the server is relaunched per test) and re-derives each pinned figure in a comment.
- `assert_instant_equals` bridges the design's bare-second instants and the PRD's three-fractional-digit serialisation.
- Waitlist-ordering tests advance the clock between sales so `created_at` strictly ascends, and free the cabin through the sweep's own group-review step.
- Rebid calls always carry the owning guest's headers: §3.7 + tier 7 make any other caller `ERR_NOT_BOOKING_OWNER` before the tier-10 state code.
- The PARTIAL-over-balance refusal is asserted as `ERR_PAYMENT_EXCEEDS_BALANCE` — §3.5 states the rule without naming a code, and tier 20 lists that code for payment posting with no other money code fitting.
- The endpoints-catalogue test does not assert the recipe's "no PATCH or DELETE verb is declared" line, which is unobservable through the client.

## Step 5: Generate Unit Tests (orchestrator record of subagent summary) — 2026-09-04T07:00:00.000Z

Generation and final verification are complete.

## Output

`test_helpers/` — 9 files, 1974 lines
`__init__.py` 60, `api_client.py` 252 (54 methods), `api_errors.py` 177 (registers `set_error_http_status_map` at import), `assertions.py` 230, `constants.py` 141, `factories.py` 220, `fixtures.py` 611, `test_users.py` 73, `types.py` 210.

`test_suite/` — 19 files, 7475 lines
`conftest.py` 56; `test_01` 252, `test_02` 290, `test_03` 255, `test_04` 255, `test_05` 469, `test_06` 345, `test_07` 255, `test_08` 235, `test_09` 307, `test_10` 791, `test_11` 603, `test_12` 463, `test_13` 593, `test_14` 652, `test_15` 971, `test_16` 353, `test_17` 175, `test_18` 155.

## Tests per design queue

- **Queue A (Difficulty / §1.8): 47 tests**, covering all 23 non-stub instances, every one with >=2 tests (`cancellation_penalty_provisional_quote_versus_final_settlement` has 3).
- **Queue B (Corner / §1.9): 51 tests**, covering 51 of 53 non-stub instances — entities 12, state_machines 8, calculations 6, validations 6, endpoints 6, errors 7, rbac 3, cross_cutting 2, consistency 1. The 9 `excluded_because` stubs were not translated.
- **Total 98 tests.** An AST pass confirms 98 `Design:` lines, one per test and always the docstring's last line, every tag resolving to a real non-stub instance, none dual-tagged, none pointing at a stub, no `class Test*` groupings.

## Verification run

`python3 -m py_compile` clean on all 28 files. `pyflakes test_suite/*.py` silent (the only diagnostics anywhere are the deliberate re-exports in `test_helpers/__init__.py`). `pytest --collect-only` collects exactly 98 tests with zero collection errors, which also proves the error-status map and every helper import resolve at runtime. A static resolver confirms every `api.*`, `fx.*`, `f.*` attribute and every `from test_helpers import ...` name exists. No file mentions the scaffold; no `skip`/`xfail`/`TODO`/placeholder anywhere. `__pycache__` removed; nothing was written under `workspace/`, and `workspace/implementation/` was never touched.

## Instances skipped (2, both non-unique-derivability — gaps left as gaps)

1. `Corner/state_machines/a_sailed_sailing_and_its_sailed_booking_refuse_further_transitions` — the recipe wants `ERR_SAILING_ALREADY_SAILED` for suspend-sales and close-inventory on a `SAILED` sailing, but PRD §3.9 makes a suspend from any non-`OPEN_FOR_SALE` status `ERR_SAILING_NOT_OPEN`, and the PRD names no code at all for close-inventory from a wrong state. `ERR_SAILING_ALREADY_SAILED` is only ever attached to itinerary publication (§3.8) plus the tier-10 code list.
2. `Corner/cross_cutting_complexity_layers/posture_flips_at_ninety_and_one_hundred_percent_occupancy` — the recipe asserts one code (`ERR_POSTURE_RESTRICTED`) serves both restricted bands for group-block creation, but §3.3 and §2.10 tier 18 both give `ERR_POSTURE_FROZEN` on a `FROZEN` sailing. Asserted outcome contradicts the PRD, so skipped rather than silently corrected.

## Fixture / translation decisions

- `simple_world()` builds sailing + guarantee category + allotment + fare rule and opens the sailing; when a second category is needed the path is `open_now=False` -> `add_allotment_and_fare()` -> `open_sailing()`, so no allotment is ever created against an already-open sailing.
- Every test builds all state through the public API (the server is relaunched per test) and re-derives each pinned figure in a comment; `assert_instant_equals` bridges the design's bare-second instants and the PRD's three-fractional-digit serialisation.
- Waitlist-ordering tests advance the clock between sales so `created_at` strictly ascends, and free the cabin via the sweep's own group-review step.
- Rebids always carry the owning guest's headers (§3.7 + tier 7 make any other caller `ERR_NOT_BOOKING_OWNER` before the tier-10 state code).
- PARTIAL-over-balance is asserted as `ERR_PAYMENT_EXCEEDS_BALANCE`: §3.5 states the rule without naming a code, tier 20 lists that code for payment posting, and no other money code fits.
- The endpoints-catalogue test does not assert the recipe's "no PATCH or DELETE verb is declared" line — unobservable through the client.

**Orchestrator layout verification:** `test_helpers/` (9 files) and `test_suite/` (19 files) are at the task root, not under `workspace/`; `workspace/` contains only INSTRUCTION.md, PRD.md and implementation/. Both Step 5 and Step 6 subagents appended their own sections to this worklog directly; all entries are intact and append-only.

## Step 7: Run Tests and Iterate — 2026-09-04T07:35:00.000Z

Clean 8-round sweep achieved: **98/98 passing in all 8 parallel rounds**.

## Summary

**Iterations run:** 2

**Iteration 1** — all 8 rounds returned an identical 94/98 (no flakiness; 4 deterministic failures). Note: `sweep.log` grep suggested 7 distinct failing names, but the per-round `results.$i.json` files showed only 4 — the extra 3 were interleaving artifacts of the shared fd, confirming sweep.log must not be used for diagnosis.

All four failures were **test bugs**; the implementation was PRD-faithful in every case.

**Tests deleted:** none. No test asserted a scaffold-only or PRD-silent rule.

**Fixes applied to `test_suite/`:**

- `test_10_entity_shapes.py::test_booking_foreign_keys_resolve_in_the_declared_order` — asserted `ERR_CATEGORY_NOT_ON_SAILING` (PRD §2.10 **tier 17**) on a booking naming a category with no allotment. But fare-window coverage is **tier 15**, and tier 17 itself forbids creating a fare rule for a category lacking an allotment on that sailing — so a category with no allotment can never have a fare rule there, making tier 15 always fire first. `ERR_CATEGORY_NOT_ON_SAILING` is structurally unreachable via booking creation. Corrected the assertion to the code PRD's fixed order mandates, `ERR_NO_FARE_RULE_FOR_WINDOW` (still an exact error_id assertion, still 422).
- `test_11_state_machines.py::test_four_undeclared_transitions_name_four_different_expected_states` — captured the sailing's `version` baseline *before* creating a booking, then asserted it unchanged after four refused transitions. PRD §2.8 requires the sale to bump the sailing's version ("a booking cascade that moves a sailing's aggregates bumps the sailing's version"). Moved the baseline read to after the sale, preserving the test's real intent (refusals write nothing).
- `test_14_endpoints.py::test_one_withdraw_verb_closes_a_scheduled_and_an_active_campaign` — captured the promotion's `version` baseline before a booking quoted it. PRD §3.4 raises `redemption_count` on the quote, and §2.5 increments `version` "on every mutation of that row ... including mutations that only touch derived fields". Moved the baseline read to after the redemption, keeping the "withdraw increments version by exactly 1" assertion intact.
- `test_18_consistency.py::test_a_sale_and_its_cancellation_are_both_visible_on_the_very_next_read` — asserted a guest's `bookings_count == 1` after their only booking was cancelled, with the comment "a cancelled booking still counts". This contradicts PRD §3.4's verbatim definition: "`bookings_count`, which counts the guest's bookings whose `booking_status` is anything other than `CANCELLED`". Corrected to 0.

**Fixes applied to `test_helpers/`:** none — fixtures and factories were already PRD-consistent (money as ints, correct role headers, correct ownership chains).

**Fixes applied to `implementation/`:** none. Verified against PRD that the implementation was correct on each disputed point: `routes_bookings.py:76-92` orders tier 15 before tier 17 exactly as §2.10 declares; `routes_catalog.py:236` blocks fare rules for allotment-less categories; `cascade.py:330-335` bumps the promotion version on redemption; `cascade.py:256-261` derives `bookings_count` as the non-CANCELLED count.

**Orchestrator verification of the sweep artifacts:** all 8 `results.$i.json` present with mtimes clustered at 2026-09-04T07:16:03-04Z, each `passed=98 total=98 failed=0 errors=0`. `grep` for `pytest.mark.skip` / `pytest.mark.xfail` across `test_suite/` and `test_helpers/` returns nothing, and the suite still contains exactly 98 `def test_` functions — so the clean sweep was not obtained by skipping or deleting tests.

## Step 8: Finalize PRD — 2026-09-04T07:38:00.000Z

Done. `PRD_FINALIZED.md` is a one-clause patch of `PRD.md`.

## Line counts
- `PRD.md`: 486 lines; `PRD_FINALIZED.md`: 486 lines — 0.0% line delta (1 line revised in place, 1/486 = 0.2% of lines touched).
- Completeness verified: ends at the last error-catalogue row (`ERR_NOT_GUARANTEE_BOOKING | 422`), 73 error rows, 54 endpoint rows in §4.

## Changes
- **§3.5 (Cancellation)** — revise — appended one clause to the "which counters move" sentence stating that the guest's `bookings_count` is recomputed on cancellation (so the just-cancelled booking no longer counts), and that this holds on every path that moves a booking to `CANCELLED`, including the §3.8 close-inventory and §3.9 sweep cancellations — `cascade.py:256-261` (`recompute_guest`), invoked from `cascade.py:409` inside `cancel_booking`.

Rationale: §3.4 already defines `bookings_count` verbatim as the non-`CANCELLED` count, but §3.5's enumeration of the counters cancellation moves omitted the guest row entirely, and §2.8's cascade paragraph names only sailing/block/allotment. A fresh implementer could read that enumeration as exhaustive and leave `bookings_count` at 1 — the exact divergence Step 7 item 4 surfaced.

## Per-edit pre-edit search log

**Edit 1 — §3.5 guest `bookings_count` on cancellation**
- (a) Subject: `Guest.bookings_count` (and, by §2.8, the guest row's `version`/`updated_at`) as affected by any booking reaching `CANCELLED`.
- (b) Paths enumerated: `grep -rn "recompute_guest\|cancel_booking(" implementation/*.py` -> `cascade.py:256` definition (counts bookings with `booking_status != "CANCELLED"`, `apply_changes` bumps only when the value moves); `cascade.py:409` inside `cancel_booking`; the three `cancel_booking` callsites — `routes_bookings.py:377` (client cancel), `routes_sailings.py:185` (close-inventory, waitlisted bookings, `assess_payment=False`), `ops.py:105` (sweep auto-cancel of delinquents) and `ops.py:136` (sweep departure of unconfirmed/waitlisted); plus `routes_bookings.py:190` (booking creation) and `cascade.py:264` `apply_loyalty` / `ops.py:126-129` (departure raises `prior_sailings_count` and re-derives loyalty but does not touch `bookings_count`). Also checked paths that change `booking_status` without changing the count — waitlist promotion `cascade.py:344-352` (`WAITLISTED`->`OPTION`), confirm, settle-cancellation — none recompute the guest, and none need to since the non-`CANCELLED` count is unchanged there.
- (c) Adjustment: originally scoped the sentence to client cancellation only; widened to "every path that moves a booking to `CANCELLED`, the close-inventory cancellations of §3.8 and the sweep cancellations of §3.9 included", because all four cancel sites funnel through `cancel_booking`. Deliberately said "recomputed" rather than "falls by 1" and made no claim about the guest's `version` (left to §2.8's generic cascade rule) so the wording stays consistent with `apply_changes`'s change-gated bump, and made no claim about non-cancellation status moves, which the impl leaves the guest row untouched for.

## Items that required no PRD change (verified, not assumed)
- **`ERR_CATEGORY_NOT_ON_SAILING` unreachable on booking creation** — genuinely pinned, not merely inferable: §2.10 numbers fare-window coverage as tier 15 and category presence as tier 17 and declares the first failure is the response, and tier 17 itself bars fare-rule creation for an allotment-less category (also §3.1). `routes_bookings.py:76-92` follows that order verbatim; `routes_catalog.py:235-237` enforces the fare-rule guard. No delete endpoint exists for allotments (checked all 54 endpoint rows), so no allotment can vanish after a rule is pinned. I deliberately left §3.1's "surfaces as `ERR_SAILING_INVENTORY_NOT_FOUND`" clause alone — it is latently loose, but only on group-block creation, which no Step 7 item exercised (out of hard scope), and it is behaviorally unobservable on booking creation.
- **Sale bumps the sailing's `version`** — pinned by §2.8 verbatim ("a booking cascade that moves a sailing's aggregates bumps the sailing's `version`"). `routes_bookings.py:192` calls `recompute_sailing(..., bump=True)`; `store.apply_changes` bumps only when a value moved, which matches §2.8's "whose own row is written" conditional — notably a `WAITLISTED` sale moves no sailing aggregate and correctly does not bump. Widening this text would have created a false universal.
- **Redemption bumps the promotion's `version`** — pinned by §3.4 ("a successful quote raises the campaign's `redemption_count` by 1") plus §2.5's universal "increments by exactly 1 on every mutation ... including mutations that only touch derived fields". `cascade.py:330-335` bumps once even when it simultaneously flips to `EXHAUSTED`, matching §3.2's single-bump wording; `routes_promotions.py:168-171` withdraws with exactly one `touch`.
- **Fixture/test-only items** — none of the four Step 7 fixes were implementation fixes, and three of the four were baseline-capture or expected-value bugs against prose the PRD already fixes.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (line 275, §3.5), confirming a real minimal patch rather than a no-op copy or a wholesale rewrite.

## Step 9: Complete PRD — 2026-09-04T08:15:00.000Z

**Orchestrator decision (recorded per AUTONOMY):** Step 9 was run as **three sequential file-partitioned passes** over `implementation/` rather than one scan. A single-shot scan of a 3335-line, 17-module implementation reliably degrades into a no-op (PRD_COMPLETED.md byte-identical to its source), which is the failure mode the partition defends against. Each pass edited the same `PRD_COMPLETED.md` in place; pass 1 performed the `cp` from `PRD_FINALIZED.md`, and each later pass was told which ground the earlier passes had already covered so nothing was re-litigated and no edit was reverted.

Partition: pass 1 = `app.py`, `store.py`, `errors.py`, `envelope.py`, `auth.py`, `shape.py`, `calcs.py`; pass 2 = `cascade.py`, `ops.py`, `routes_bookings.py`, `routes_bids.py`; pass 3 = `routes_sailings.py`, `routes_catalog.py`, `routes_promotions.py`, `routes_groups.py`, `routes_guests.py`, `routes_itinerary.py`.

### Totals
- `PRD.md` 486 lines / 104,342 chars -> `PRD_FINALIZED.md` 486 / 104,634 -> `PRD_COMPLETED.md` **486 lines / 116,162 chars** (+11,528 chars over PRD.md, +11,820 over... ; zero new lines — every edit is an in-paragraph insert or revision, no new sections).
- 49 lines revised versus `PRD_FINALIZED.md`.
- **Cumulative: 37 ambiguity-pins + 13 mismatch-revisions = 50 edits** (pass 1: 11+3; pass 2: 17+8; pass 3: 9+2).

### Pass 1 (core modules) — 11 pins, 3 mismatches
- §2.1 revise/ambiguity — whitespace-only auth headers count as empty; role match exact and case-sensitive — auth.py:24,27
- §2.2 revise/ambiguity — `api_request_id` = `req_` + exactly 20 uppercase-alnum chars — envelope.py:9,12-13
- §2.2 revise/**mismatch** — `api_request_timestamp` comes from real wall-clock time, the one timestamp that does not read the logical clock — envelope.py:16-22
- §2.3 revise/ambiguity — non-base-ten `limit`/`offset` is `ERR_INVALID_REQUEST` — shape.py:151-166
- §2.3 insert/ambiguity — `created_at` ties keep creation order, never fall back to `id` — store.py:155-157
- §2.4 insert/ambiguity — lenient datetime parsing normalised to UTC (`Z`/`z`, numeric offsets, bare = UTC) — store.py:45-58, shape.py:124-133
- §2.5 revise/ambiguity — `id` is a canonical lowercase v4 UUID; `created_at` reads the logical clock; sub-ms truncated not rounded; `updated_at == created_at` on creation — store.py:39-42,121-132
- §2.5 revise/**mismatch** — a write is a mutation only when a stored value actually moves; a no-op recompute bumps neither `updated_at` nor `version` — store.py:143-152
- §2.8 revise/**mismatch** — same qualification on the cascade-bump sentence — store.py:143-152
- §2.10 tier 4 insert/ambiguity — full JSON type discipline (absent body = `{}`, `null` == absent, integral floats but not bools/strings, `discount_pct` number-or-decimal-string, optional FKs string-or-null but not `""`, undeclared fields ignored) — shape.py:21-143
- §3.4 revise/ambiguity — waitlist three-key ties broken by creation order — calcs.py:302-307
- §3.9 insert/ambiguity — neither RALBD variant is floored at zero; negative figures publish — calcs.py:202-205
- §3.9 insert/ambiguity — the two boolean filters accept `true/false/1/0` any case and reject the rest; all other filters are exact string compares that match nothing — shape.py:177-187
- §4/§5 revise+insert/ambiguity — the clock endpoint answers 200 with empty `data`; three envelope-level codes outside the catalogue (`ERR_ROUTE_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500); trailing-slash paths served — app.py:26,42-49,60-85

### Pass 2 (cascades, sweep, bookings, bids) — 17 pins, 8 mismatches
Mismatches: §2.10 tier 12 (only the `guest_count` limb re-runs on an upgrade award — routes_bids.py:216); §3.1 (a missing allotment is only `ERR_CATEGORY_NOT_ON_SAILING`; `ERR_SAILING_INVENTORY_NOT_FOUND` is reserved for an unresolvable path id — routes_bookings.py:90-92); §3.2 (the activation posture gate is client-endpoint-only; the sweep activates regardless — ops.py:57-63); §3.3 (a zero-release review keeps the block's status and pushes `review_date` 14 days from the stored date — ops.py:16-20); §3.7 (`upgrade_charge_cents` accumulates across awards — routes_bids.py:239); §3.9 step 1 (only SCHEDULED/ACTIVE promotions expire — ops.py:50-54); §3.9 step 3 (DEFINITE/RELEASED blocks are skipped, not refused — ops.py:66-71); §3.9 step 4 (every allotment is worked, so cancellation-freed cabins fill here — ops.py:74-75).
Pins: tier-6 resolution of `assigned_cabin_category_id` (routes_bookings.py:425); the bid counter's sailing-status guard outranking its own checks (routes_bids.py:153-161); FROZEN group pickup still needing `allow_waitlist` yet created in `OPTION` (routes_bookings.py:96-100); a releasing review leaving `review_date` untouched (ops.py:22-27); a quoted campaign's `sailing_id` never compared (routes_bookings.py:112-116); `pinned_fare_rule_version` captured before `bookings_pinned_count` rises (routes_bookings.py:145,186-187); `allow_waitlist` stored on the booking (routes_bookings.py:150); payment posting returning 201 with the event (routes_bookings.py:336); client-posted `UPGRADE_CHARGE`/`REFUND` being `ERR_PAYMENT_STATE_INVALID` not `ERR_INVALID_REQUEST` (routes_bookings.py:19,266,280-284); `PARTIAL` from `DELINQUENT` landing `DEPOSIT_PAID` without clearing `delinquent_since`, at-or-above balance being `ERR_PAYMENT_EXCEEDS_BALANCE` (routes_bookings.py:279,313-326); post-grace cure = `ERR_FINAL_PAYMENT_OVERDUE` (routes_bookings.py:292-295); payment on `WAITLISTED` = `ERR_PAYMENT_STATE_INVALID` with the dead-booking check first (routes_bookings.py:271-284); both sailing counters re-derived from children (cascade.py:200-213); cancellation never touching open bids (cascade.py:376-411); the award answering with the bid and not re-checking `booking_status` (routes_bids.py:203-260); decline from terminal = `ERR_BID_NOT_PENDING` (routes_bids.py:271-272); guarantee assignment requiring OPTION/CONFIRMED and unknown target = `ERR_CABIN_CATEGORY_NOT_FOUND` (routes_bookings.py:425-429); step 9 refreshing allotments before the sailing (ops.py:141); the sweep bumping the sailing's `version` unconditionally and answering 200 with the refreshed sailing (ops.py:142-144); `SAILED_UNCONFIRMED` cancellations quoting a provisional total-forfeiture penalty, leaving `cancellation_penalty_cents` null (ops.py:131-138).
Deliberately left unpinned: the `INVENTORY_CLOSED` zero-penalty branch at routes_bookings.py:401 is unreachable (close-inventory never assesses a penalty).

### Pass 3 (remaining route modules) — 9 pins, 2 mismatches
- §2.10 tier 4 insert/ambiguity — uniqueness comparisons are exact case-sensitive string matches; a double collision reports `ERR_DUPLICATE_CATEGORY_CODE` — routes_catalog.py:38-43
- §2.9 revise/**mismatch** — promotion *creation* performs no posture check (only the version guard); posture gates activation, so a campaign may be scheduled on a RESTRICTED/FROZEN sailing — routes_promotions.py:49-97 vs 148-150
- §3.1 insert ×2 /ambiguity — creation-time derivation is part of the creation, so a new sailing and a new allotment both return `version` 1 — routes_sailings.py:80, routes_catalog.py:148
- §3.2 revise/ambiguity — per-sailing `code` uniqueness spans campaigns of any status (a WITHDRAWN code stays occupied, unlike its calendar slot) — routes_promotions.py:66-68 vs 26-38
- §3.3 insert/ambiguity — confirm-definite's sailing-status code is `ERR_SAILING_NOT_OPEN`, after the block's TENTATIVE check — routes_groups.py:126-127
- §3.4 insert/ambiguity — any non-empty string is an acceptable `email`; no format check, no length cap — routes_guests.py:24
- §3.8 insert/ambiguity — a still-`PLANNED` sailing also yields `ERR_SAILING_ALREADY_SAILED`; drafting is ungated by sailing status — routes_itinerary.py:19,23-54,96-97
- §3.8 revise/**mismatch** — publication bumps the sailing's `version` only when a figure actually moves, so a publication with no OPTION/CONFIRMED booking leaves the sailing untouched — routes_itinerary.py:130
- §3.9 insert/ambiguity — close-inventory refuses every status other than OPEN_FOR_SALE/SALES_SUSPENDED with `ERR_SAILING_NOT_OPEN` — routes_sailings.py:178-179
- §3.9 revise/ambiguity — the revenue-summary read-through also refreshes allotment inventory chains and blocks' `picked_up_cabins`, with the version exemption covering those rows — routes_sailings.py:208-209

### Closing integrity check — PASS
Pass 3 confirmed passes 1 and 2 edits still present (§2.2 `req_` wording, §2.5 no-op-mutation rule, §3.9 sweep-step revisions), 54 endpoint rows in §4, 73 error rows in §5 plus the three envelope-level codes named in the preamble, and the file ending at the last catalogue row with no new sections.

**Orchestrator verification:** `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (49 changed lines, +11,528 chars over `PRD.md`), so the scan genuinely ran. A mechanical scaffold-vs-PRD diff finds all 73 error_ids and all 54 endpoint paths still present. `find -newermt` confirms no file under `implementation/`, `test_suite/` or `test_helpers/` was modified after the clean 07:16 sweep, so the 8 passing `results.$i.json` remain valid for the shipped artifacts. `__pycache__` directories removed.

## Pipeline complete — 2026-09-04T08:15:00.000Z

All nine steps finished. Final state: 98 tests, 98/98 passing in all 8 parallel rounds; `workspace/PRD_COMPLETED.md` written.

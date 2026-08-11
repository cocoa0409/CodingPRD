## Step 1: Create Task Directory — 2026-08-09T17:22:14.368Z

Pre-assigned output folder `tasks/task_0955_baby_gear_travel_rental` with `workspace/` subdirectory already exists; Step 1 auto-index scan skipped per headless-run instructions. Difficulty parameter: "generate task hard than expert level!" (to be passed through to scaffold generator at Step 2 only).

## Step 2: Generate Scaffold — 2026-08-09T17:55:41.693Z

All checks pass. The scaffold for task 0955 is complete and lint-clean.

## Summary

**Output directory**: `/home/ubuntu/github/CodingPRD/tasks/task_0955_baby_gear_travel_rental/`

**Files generated** (all three required):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (fixed response envelope verbatim; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design:`

**Domain design** (temporal-windowing primary + quota-allocation secondary archetype; flat topology; segregation-of-duties role model; immediate consistency):
- **Entities: 14** — Customer, CatalogItem, InventoryUnit, HotelPartner, InsurancePlan, Reservation (parallel rental-status × payment-status dimensions), ReservationLine, DeliveryRoute, RouteStop, ExtensionRequest, DamageClaim (cyclic dispute loop), RecallNotice, CleaningTicket, DepositTransaction (append-only, `common_fields: false`)
- **State machines: 11** (9 distinct entities; Reservation has 2 parallel dimensions) — includes unit rental/cleaning cycle, claim deny→dispute→reopen cycle, route dispatch→recall revert
- **Calculations: 12** — incl. provisional-vs-final quote (mode-c pinned evaluation order), PER_DAY vs PERCENT insurance premiums, grace-boundary late fee, tiered extension charge, risk-tiered deposit hold, nested-min/max damage capture with insurance branch, deposit waterfall, per-line-round-then-sum commission, buffered availability, weighted risk score with 70/90 thresholds, aggregate route capacity
- **Validations: 12** priority-ordered rows (auth → authz/ownership → existence → shape → date-range → state → OCC → safety → temporal → constraint → segregation → fiscal)
- **Endpoints: 67** — incl. OCC-guarded `amend-dates`/`extensions`, computed availability read, recall/cleaning/damage workflows, and `POST /_clock/set_current_utc` (default 2026-05-01T00:00:00Z stated)
- **Errors: 34**
- **Roles: 5** — Anonymous (opaque), Customer (`entity_backed:Customer`), HotelPartner (`entity_backed:HotelPartner`), Inspector (opaque), OperationsAdmin (opaque; claim filer ≠ approver)
- **Concurrency rules: 2** — both OCC on `Reservation.version` (412 ERR_STALE_VERSION)

**Difficulty design: 23 instances** across all 9 rules (dual_variant 2, combinatorial 3 covering modes a/b/c, non_linear_sm 3, transitive_cascade 3 with depth-3 chains from 3 distinct triggers, priority_conflict 3 with distinct category pairs, boundary 2, cross_entity 3 with distinct pairs, temporal_overlap 2 with distinct interval semantics, invariant 2 with distinct conserved quantities). All numeric asserts are pre-computed literals (e.g., quoted 13000 vs final 20200, commission 312 vs naive 311, capture 1000 insured vs 4800 uninsured, late fee 0 at 240 min vs 450 at 241 min, ledger 15000 = 5250 + 9750, risk 90 → auto-suspend).

**Corner design: 42 instances** (39 active + 3 `excluded_because` stubs) across sections entities(6), state_machines(8), calculations(6), validations(7), endpoints(4), errors(4), rbac(4), cross_cutting_layers(2), consistency_model(1).

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (622 calls scanned). Instance names unique across the union (65); no forbidden concurrency vocabulary; no sibling task directory was inspected.

## Step 3: Copy Shared Files — 2026-08-09T17:56:03.226Z

Copied ./INSTRUCTION.md to tasks/task_0955_baby_gear_travel_rental/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-09T18:10:00.000Z

All checks pass. The PRD has been generated at `/home/ubuntu/github/CodingPRD/tasks/task_0955_baby_gear_travel_rental/workspace/PRD.md`.

## Summary

**Output**: `PRD.md`, 289 lines (~48 KB), ending at §5 with no audit footer.

**Structure**:
- **§1 Introduction** — 2 paragraphs, business-context angle (traveler pain point → operational scope).
- **§2 Global Specifications** (9 subsections): 2.1 RBAC (all 5 roles with `identity:` translated to prose — `Customer`/`HotelPartner` entity-backed, `Anonymous`/`Inspector`/`OperationsAdmin` opaque), 2.2 API Response Structure (**verified byte-identical** to the canonical source block, including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, `"data": { }`), 2.3 Pagination (`limit` 10/1–100, `offset` 0, `created_at` ascending, meta fields), 2.4 Resource identity (UUID `id`, ISO 8601 timestamps, `version` semantics; DepositTransaction explicitly flagged as carrying only `id` + `created_at`), 2.5 Logical clock (default 2026-05-01T00:00:00Z, `to_iso8601`/`current_utc`, half-open date semantics), 2.6 Money/precision (integer cents, round half-up at point of factor application), 2.7 OCC (`expected_reservation_version` on amend-dates and extension-create, `ERR_STALE_VERSION` 412, checked after state preconditions), 2.8 Validation order (all 12 priorities in explicit first-match-wins prose, left-to-right path-then-body existence), 2.9 Deposit ledger (`HOLD`/`CAPTURE`/`RELEASE`, reason enum, `balance_after_cents`, conservation invariant, silent shortfall absorption).
- **§3 Business Logic** (7 subsections, no paths/methods anywhere): fleet/catalog/insurance, customers/partners, quoting/amending (pinned 5-step evaluation order, tiered line pricing 100%/85%/70%, delivery-fee tiers 2500/1500/0, 1500 setup), confirmation/allocation/deposit hold (selector ranking A>B>C then `created_at`, risk multiplier at 70), routes/stops/delivery-pickup cascades, cleaning cycles + 3-deep recall quarantine cascade + reallocate, extensions/damage claims (severity × grade factors, deductible/cap insurance band, segregation of duties)/settlement (240-minute grace, per-line late fee capped at 2× unit rate, waterfall bucket order, per-line-rounded commission, risk-score ≥90 auto-suspension).
- **§4 Endpoint table**: 67 rows, 4 columns only. **§5 Error catalogue**: 34 rows, 2 columns only.

**Hard Contract Reports**:

```
Field coverage check:
- entities[].fields + endpoint inputs/query/path params: 91 required, 91 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 12 checked, 12 expressed in §2.8 ordered prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write op + expected_reservation_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: all transitions across 10 machine entries (incl. parallel payment_status machine) expressed with preconditions + error ids + side effects, 0 missing
- calculations[]: 12 checked, 12 expressed in precise prose (tiered quote, dual-variant premium, late fee, extension charge, deposit hold, damage capture, waterfall, commission, availability, risk score, route load, stop sequence), 0 missing
- validations[] conditions: 34 error ids all matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: cascades (confirm, delivery/pickup, cancel, settle, recall depth-1/2/3, cleaning pass/fail) all expressed, 0 missing
- entities[].fields[] structured content: defaults, constraints, enum memberships, and null-semantics stated per entity, 0 missing
- sibling-branch symmetry: parallel cancel branches (QUOTED vs CONFIRMED), stop complete branches (DELIVERY_SETUP vs PICKUP), pass/fail ticket branches, PER_DAY vs PERCENT_OF_RENTAL premium variants rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 443
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-09T18:30:03.783Z

Generation complete. Summary:

## Test counts

**Queue A (Difficulty) — 23/23 instances covered, 46 tests (exactly 2 per instance):**
- All 9 rules × all instances translated; every instance passed the PRD-first two-condition filter.

**Queue B (Corner) — 37 tests, 37 of 39 non-stub instances covered:**
- 3 `excluded_because:` stubs (`error_recall_blocked_trigger`, `error_extension_window_conflict_trigger`, `error_route_capacity_trigger`) not translated; all three cross-references resolve to real difficulty instances.

## Per-file breakdown

| File | Tests | Contents |
|---|---|---|
| test_01_quoting_and_pricing.py | 5 | insurance PER_DAY vs PERCENT variants (2), delivery-fee tier keying (2), tiered long-rental quote (1) |
| test_02_reservation_creation_and_amend.py | 12 | creation defaults, required-field/404/FK rejection, birth state, date-range/zone/plan-rate/not-found validations, OCC amend (1), shape-beats-state pair (2) |
| test_03_confirm_cancel_and_deposit.py | 12 | parallel payment dimension (2), suspended-customer confirm (2), recall-beats-suspended pair (2), unit-pool conservation (2), no-eligible-unit, 10% cancellation fee, ledger append-only, confirm read-after-write |
| test_04_routes_stops_capacity.py | 12 | exact-fit + overflow capacity (2+2), stop-complete-needs-dispatch (2), route recall ±, duplicate stop, window-outside-route-date, stop sequencing, delivery cascade |
| test_05_extensions_availability.py | 10 | extension window conflict + approved charge (2), cleaning-buffer adjacency 0/1 (2), state-beats-temporal pair (2), supersede, OCC extension 412, retired-excluded, no-bookings read |
| test_06_cleaning_recalls.py | 8 | full cleaning cycle (2), recall depth-3 cascade (2), pickup depth-3 cascade (2), fail-loops-back, deep-clean cadence |
| test_07_damage_claims.py | 6 | insured capture 1000 / uninsured 4800 (2), dispute-reopen cycle (2), inspector-forbidden, segregation of duties |
| test_08_settlement_ledger.py | 13 | provisional-vs-final 13000/20200 (2), late-fee 240-vs-241 boundary (2), ledger conservation + waterfall entries (2), settle→capture→risk-90→suspend cascade (2), per-line commission rounding (2), terminal settle lockdown, risk 40, risk-70 multiplier 22500 |
| test_09_security_envelope_pagination.py | 5 | unauthenticated 401, customer/ownership 403s, envelope shape, pagination limit/offset |

## Skipped instances (gaps left as gaps)

1. **`Corner/entities/reservation_client_supplied_status_ignored_input`** — PRD is silent on handling of undeclared payload fields; "ignored vs rejected with 400" is not uniquely derivable (fails the two-reader test).
2. **`Corner/state_machines/stop_creation_rejected_for_quoted_reservation`** — PRD §3.5 lists only window/zone/overlap/duplicate/capacity checks for stop creation; reservation-state gating applies only to stop *completion*. No verbatim PRD coverage.

## Deviation noted (not a skip)

- **`Difficulty/combinatorial_formula/hotel_commission_per_line_rounding_then_sum`** asserts `quoted_total_cents == 8110`, which contradicts the PRD formula (gear 3110 + delivery 2500 + setup 1500 = **6610**). The precomputed literal is a design-index arithmetic error; the generated tests assert only the PRD-derivable outcomes (commission 312, gear_subtotal 3110, and rejection of the sum-then-round value 311).

## Audit results

- **Stage 1**: 9 helper modules (`types`, `api_client` with all 64 endpoints, `api_errors` with 34 errors registered via `set_error_http_status_map`, `assertions`, `factories`, `constants`, `test_users` with per-instance builders for entity-backed roles, `fixtures` with confirmed/delivered/returned/settled composite chains, barrel `__init__`); imports cleanly; no scaffold references.
- **Stage 2**: all 83 tests collect under pytest; every test function carries exactly one `Design:` tag resolving to a real instance (0 tag errors, 0 count mismatches); all 118 quoted PRD passages verified verbatim against `workspace/PRD.md` via automated grep; no `skip`/`skipif`/`xfail` markers anywhere.

## Step 6: Generate Implementation — 2026-08-09T18:30:03.783Z

All verification passed. Final report:

## Summary

### File tree
```
workspace/implementation/
├── start.sh            # exec launcher; guarded pip install (no-op when flask present); PORT env, default 10000, 0.0.0.0
├── requirements.txt    # flask>=2.0
├── app.py              # Flask entry, blueprint registration, ApiError/404/405/500 envelope handlers
├── db.py               # In-memory Store (14 dicts); create_rec/create_txn/bump helpers; EMPTY at boot, zero seeding
├── clock.py            # Logical clock, hard default 2026-05-01T00:00:00Z, never wall-clock
├── errors.py           # ApiError(error_id, status, message)
├── response.py         # Exact envelope: meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}, response_type, data{error_id, message}
├── middleware.py       # X-User-ID/X-User-Role auth (401), per-endpoint role gate (403), JSON body
├── validate.py         # Shape validators -> ERR_INVALID_REQUEST (400)
├── serialize.py        # Per-entity serializers; ISO-8601 UTC with 3 fractional digits; DepositTransaction has no updated_at/version
├── util.py             # Decimal ROUND_HALF_UP money math, strict YYYY-MM-DD/ISO parsing, half-open interval helpers
├── calc.py             # All 12 calculations with pinned constants and rounding order
├── services.py         # Atomic workflows: confirm, cancel (QUOTED/CONFIRMED), settle waterfall, stop complete cascades, 3-deep recall cascade, reallocate
└── routes/             # customers, catalog, units, partners, plans, reservations, extensions, lines, logistics (routes+stops), recalls, cleaning, claims, clockroute
```

### Endpoint coverage
All 65 scaffold endpoints implemented: customers (5), catalog items (6 incl. availability + recalls sub-list), inventory units (5), hotel partners (4), insurance plans (3), reservations (10 incl. confirm/cancel/amend-dates/settle + deposit-transactions + extensions sub-resources), extensions (3), reservation lines (4 incl. reallocate), routes/stops (12), recalls (4), cleaning tickets (4), damage claims (6), `POST /_clock/set_current_utc`.

### Key design decisions
- **Validation order** follows PRD §2.8 strictly: auth → role → existence (path left-to-right, then body FKs) → shape → date sanity → state → OCC → recall safety → temporal overlap → structural → SoD. Confirm orders: `ERR_RECALL_BLOCKED` (pri 8) → `ERR_UNIT_UNAVAILABLE` (pri 9, overlap-only failures) → `ERR_CUSTOMER_SUSPENDED`/`ERR_CATALOG_ITEM_DELISTED`/`ERR_NO_ELIGIBLE_UNIT` (pri 10).
- **Calculations**: Decimal HALF-UP at each factor application; pinned orders — per-unit deposit rounding before sum, per-line commission rounding before sum, delivery fee tiered on gear subtotal only (never the running total), marginal tiers 6/13 at 100%/85%/70%, extension 120%/150% split at day 2, late fee grace 240 min inclusive with ceil hours and 2x-rate cap, TOTAL_LOSS uses deposit (repair ignored) with no severity scaling, insurance reshape `min(charged, deductible) + max(0, charged - cap)`.
- **Committed intervals** are buffered half-open `[start, end+turnaround)`; a follow-up may start exactly at the buffered end. Route capacity uses `<=` (exact fit allowed); stop windows are half-open so touching windows don't conflict; stop sequence = time_window_start ASC, ties by created_at ASC, recomputed on add/skip.
- **Cascades**: confirm is atomic (full assignment simulated before any commit); pickup auto-creates STANDARD/DEEP tickets by cycle counter and moves units AWAITING_CLEANING→IN_CLEANING; MANDATORY recall activation does the 3-deep hop (units→QUARANTINED, RESERVED units' lines→PENDING_REALLOCATION with cleared unit, their SCHEDULED DELIVERY_SETUP stops→SKIPPED with route weight recompute); settle runs the waterfall (claims in created_at ASC → late fee → release), updates customer counters, recomputes risk (`min(100, 15L+25D)`), and auto-suspends at ≥90.
- **Ledger**: HOLD adds, CAPTURE/RELEASE subtract; invariant hold == captured + released holds; zero-amount late-fee captures and zero releases are omitted; every record mutation bumps `version` by exactly one (DepositTransaction excluded).
- **OCC**: `expected_reservation_version` required on amend-dates and extension create, checked after state preconditions → `ERR_STALE_VERSION` (412).

### Boot verification
`bash start.sh` launched cleanly twice from fresh processes on different ports: clock default confirmed (`created_at: 2026-05-01T00:00:00Z` on first write), clock-set endpoint works, empty store confirmed. Four end-to-end scripts (≈120 assertions) all passed against fresh boots: full quote→confirm→deliver→extend→late-return→claim→settle lifecycle with exact ledger/commission/risk assertions; RBAC/401/403/404/error-catalog probes; recall quarantine→decontamination→reallocate→close; CONFIRMED-cancel fee waterfall; cleaning STANDARD/DEEP cycle cadence incl. `ERR_DEEP_CLEAN_REQUIRED`; grace boundary (240 min free, 241 min bills 1 hour); extension window conflict; deny/dispute/reopen loop; risk multiplier 1.5x at 75; auto-suspension at 100; TOTAL_LOSS with deductible/cap; 20-day tiered quote; duplicate-stop/window/capacity guards. Every failure encountered during testing traced to test-script bugs, not implementation defects.

## Step 7: Run Tests and Iterate — 2026-08-09T18:47:09.454Z

Clean 8-round sweep: all rounds 83/83. Exiting with summary.

## Summary

**Iterations run:** 3 sweeps (24 round-results total; final sweep = 8/8 rounds at 83/83).

**Tests deleted:** none.

**Tests relaxed (coverage correction, sanctioned by the ERROR PRECEDENCE SILENCE exception):**
- `test_03_confirm_cancel_and_deposit.py::test_confirm_with_no_eligible_unit_fails_atomically` — PRD 3.4 names both outcomes for the exact scenario without fixing precedence: "A confirm that finds no eligible unit for any line fails with `ERR_NO_ELIGIBLE_UNIT`" and "a unit whose committed interval collides with the requested window yields `ERR_UNIT_UNAVAILABLE` under the temporal-overlap rule" (reinforced by §2.8 priority 9 temporal-overlap ranking above priority 10 unit-eligibility). Two faithful readers diverge (eligibility-subsumes-overlap vs overlap-is-the-cause). Exact `error_id` assertion relaxed to `validate_error_is_one_of(["ERR_NO_ELIGIBLE_UNIT", "ERR_UNIT_UNAVAILABLE"])` with the 409 status assertion retained; all atomicity assertions (reservation stays `QUOTED`, line `PENDING`, unit `RESERVED`) unchanged.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** only the relaxation above (`/home/ubuntu/github/CodingPRD/tasks/task_0955_baby_gear_travel_rental/test_suite/test_03_confirm_cancel_and_deposit.py`).

**Fixes applied to `implementation/`:**
- `workspace/implementation/util.py` — added `fmt_clock()`: renders logical-clock-stamped instants the way the clock itself reads per PRD 2.5 ("the clock reads exactly 2026-05-01T00:00:00Z"), i.e. no fractional digits unless the instant carries them. PRD's three-fractional-digit rule (§2.2, §2.4) verbatim-covers only `api_request_timestamp`, `created_at`, and `updated_at`, which keep using `fmt_dt()`.
- `workspace/implementation/serialize.py` — `blocked_until`, `returned_at`, `completed_at`, `activated_at` now render via `fmt_clock()` instead of `fmt_dt()`. These are stamped from (or computed from) the logical clock per PRD 2.5; tests set the clock to e.g. `2026-06-13T04:00:00Z` and assert the stamps echo that exact reading. Fixed 4 tests: `test_delivery_stop_complete_marks_line_out_unit_rented`, `test_pickup_moves_unit_to_in_cleaning_with_blocked_until`, `test_pickup_returns_reservation_with_returned_at`, `test_pickup_blocks_unit_and_autocreates_ticket`.
- `workspace/implementation/routes/clockroute.py` — `current_utc` response now uses `fmt_clock()` for consistency with the clock's own representation.

**Residual flakiness note:** intermediate sweeps showed sporadic "API server could not be restarted" setup failures (never the same test, caused by host CPU contention from a concurrent task_0950 pipeline — boot is ~0.25s idle but the runner's per-test restart window is 15s under load). These are infrastructure noise, not test or implementation bugs; the final sweep under quieter conditions passed all 8 rounds cleanly. Two orphaned `app.py` processes from my own earlier boot-latency measurement were killed; no other task's processes were touched.

## Step 8: Finalize PRD — 2026-08-09T18:55:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_0955_baby_gear_travel_rental/workspace/PRD_FINALIZED.md` written with exactly two inline revisions, both traced to `<step_7_diff>` items.

**Line counts / %-delta:** PRD.md = 288 lines, PRD_FINALIZED.md = 288 lines — 0.0% delta (both edits were in-place revisions of existing lines; no sections added).

**Changes:**
- §2.5 — revise — appended to the logical-clock paragraph: instants stamped from the logical clock (`returned_at`, `completed_at`, `activated_at`, the unit's `blocked_until`, and the clock endpoint's `current_utc`) render exactly as the clock reads (ISO 8601 UTC, fractional digits only when the instant carries them); the three-fractional-digit rule of §2.2/§2.4 covers `api_request_timestamp`, `created_at`, `updated_at` and does not apply to clock-stamped fields — `workspace/implementation/util.py:59-69` (`fmt_clock`), `workspace/implementation/serialize.py:41,80,112,143`, `workspace/implementation/routes/clockroute.py:20`.
- §3.4 — revise — replaced the ambiguous confirm-failure sentence with the pinned precedence: `ERR_NO_ELIGIBLE_UNIT` only when a failing line has no candidate units at all (no unclaimed unit of the line's catalog item in `AVAILABLE`/`RESERVED`/`RENTED_OUT`); `ERR_UNIT_UNAVAILABLE` when candidates existed but were all excluded by `blocked_until` or committed-interval overlap, and this temporal-overlap error outranks `ERR_NO_ELIGIBLE_UNIT` (§2.8 priority 9 over 10), including mixed-cause confirms — `workspace/implementation/services.py:43-73` (raises `ERR_UNIT_UNAVAILABLE` at services.py:62, `ERR_NO_ELIGIBLE_UNIT` at services.py:72).

**Per-edit pre-edit search log:**
- Edit 1 (§2.5): (a) subject = rendering format of logical-clock-stamped instants. (b) Enumerated and read every timestamp path in `implementation/`: `response.py:23,35,51` (`api_request_timestamp` via `fmt_dt`, 3 digits — clock-stamped but NOT clock-rendered), `serialize.py:9-10,158` (`created_at`/`updated_at` via `fmt_dt`), `serialize.py:108-109` (stop `time_window_start/end` via `fmt_dt`, request-supplied), `serialize.py:41,80,112,143` (`blocked_until`/`returned_at`/`completed_at`/`activated_at` via `fmt_clock`), `clockroute.py:20` (`current_utc` via `fmt_clock`), stamping sites `services.py:217,234,246,265`, `util.py:50-69`. (c) Adjustment: named the clock-rendered fields explicitly instead of saying "all clock-stamped instants," because `api_request_timestamp` is clock-stamped yet keeps 3-digit rendering; scoped the 3-digit rule to its three named fields without asserting anything about stop time windows (left PRD-silent, matching impl's `fmt_dt` there without pinning it).
- Edit 2 (§3.4): (a) subject = precedence between `ERR_NO_ELIGIBLE_UNIT` and `ERR_UNIT_UNAVAILABLE` on failed confirm. (b) Enumerated and read every impl path touching these errors: `services.py:43-73` (`confirm_reservation`: pool excludes units `taken` by sibling lines in the same confirm; overlap error raised before the customer-suspended/delisted/no-eligible structural block), `services.py:306-336` (`reallocate_line`: separate three-way split including `ERR_UNIT_QUARANTINED`), `calc.py:115-123` (`unit_eligible` filters), `calc.py:214-217` (availability readout, no errors). (c) Adjustments: kept the wording confirm-scoped so it says nothing about reallocate (whose PRD §3.6 text is untouched and whose impl raises `ERR_UNIT_UNAVAILABLE` without PRD pinning — outside Step 7 scope); added "left unclaimed within that confirm" to the empty-pool branch so the two-lines-one-unit case is correctly described as `ERR_NO_ELIGIBLE_UNIT`; pinned that `ERR_UNIT_UNAVAILABLE` wins mixed-cause confirms, matching `services.py:61-63`.

The two test-relaxation/fix items not resulting in edits: the `fmt_clock` addition to `util.py` is pure implementation machinery (behavior pinned via Edit 1); no test-helper or test-suite fix required PRD changes beyond the two above.

## Step 9: Complete PRD — 2026-08-09T19:10:00.000Z

All edits applied. Final verification done — 288 lines in both files, +3,593 chars.

## Summary

**Source:** `workspace/PRD_FINALIZED.md` (288 lines, 49,491 chars) → `workspace/PRD_COMPLETED.md` (288 lines, 53,084 chars; char-delta +3,593). 19 inline changes, no new sections.

**Counts:** 16 ambiguity-pins, 3 mismatch-revisions.

**Changes (one per bullet):**

- §2.3 Pagination — insert — ambiguity — pinned limit/offset validation errors (`ERR_INVALID_REQUEST` 400 for non-integer, out-of-band limit, negative offset), the exact `has_more` semantics (`offset + returned < total_count`), and the equality-filter query parameters list endpoints accept — `implementation/response.py:59-78,39`; filters across `routes/*.py`
- §2.4 Resource Identity — revise — ambiguity — `version` "starts at its initial value" pinned to "starts at 1" — `implementation/db.py:48`
- §2.9 Deposit Ledger — revise — **mismatch** — "signed-positive `amount_cents" changed to non-negative: capture entries are still appended at zero when the hold is already exhausted — `implementation/services.py:165-176`
- §2.8 Validation Order (item 5) — revise — **mismatch** — amend date sanity is new-end strictly after new-start (not after the reservation's current `end_date`); extension-end rule unchanged — `implementation/routes/reservations.py:170-171`
- §3.1 Catalog — insert — ambiguity — partial update may also re-list (`DELISTED`↔`LISTED` in either direction) — `implementation/routes/catalog.py:97-99`
- §3.2 Customers — insert — ambiguity — manual suspend requires `ACTIVE`, reinstate requires `SUSPENDED`, else `ERR_INVALID_STATE` — `implementation/routes/customers.py:59-60,70-71`
- §3.3 Reservation creation — insert — ambiguity — `lines` must be a non-empty array; malformed (non-YYYY-MM-DD) dates are `ERR_INVALID_REQUEST` (400), with `ERR_INVALID_DATE_RANGE` only for well-formed dates; remaining counters born at zero, `final_total_cents`/`returned_at` null, lines born with `assigned_unit_id` null and `unit_rate_cents` zero — `implementation/routes/reservations.py:64-82,90-105`
- §3.4 Availability readout — insert — ambiguity — window query requires well-formed dates (else 400) and `end_date` strictly after `start_date` (else 422) — `implementation/routes/catalog.py:109-115`
- §3.4 Confirmed-cancel cascade — insert — ambiguity — lines still `PENDING` or `PENDING_REALLOCATION` are also cancelled (no unit released) — `implementation/services.py:111-113`
- §3.5 Stop weight — revise — ambiguity — weight sums `weight_kg` over the reservation's non-`CANCELLED` lines only — `implementation/calc.py:220-227`
- §3.5 Stop window conflict — revise — ambiguity — conflict check ignores `SKIPPED` stops — `implementation/routes/logistics.py:103-108`
- §3.5 Stop sequencing — insert — ambiguity — route stop listing orders numbered stops by `sequence` with `SKIPPED` stops last (not `created_at`); stop time windows render with three fractional digits — `implementation/routes/logistics.py:143-146`, `implementation/serialize.py:108-109`
- §3.5 Stop fail — insert — ambiguity — failing requires a `SCHEDULED` stop on a `DISPATCHED` route (else `ERR_INVALID_STATE`) and recomputes `planned_weight_kg` with a route version bump — `implementation/routes/logistics.py:218-231`
- §3.6 Quarantined-while-RENTED_OUT pickup — revise — **mismatch** — at pickup the quarantined unit skips the cleaning cascade entirely (stays `QUARANTINED`, `blocked_until` unchanged, no auto ticket; decontamination only via a manual `RECALL_DECONTAMINATION` ticket), replacing the "returned through the normal pickup cascade" wording — `implementation/services.py:241-256`
- §3.6 Ticket resolution — insert — ambiguity — resolution requires the matching unit state (`IN_CLEANING` for STANDARD/DEEP, `QUARANTINED` for RECALL_DECONTAMINATION), else `ERR_INVALID_STATE` — `implementation/routes/cleaning.py:69-80`
- §3.6 Reallocation — revise — ambiguity — pinned that the reservation's own committed interval is excluded from the overlap check, and added the third rejection branch: non-quarantined candidates all excluded by `blocked_until`/overlap → `ERR_UNIT_UNAVAILABLE` — `implementation/services.py:314-328`
- §3.7 Extension creation — insert — ambiguity — creation refused only for terminal reservations (`SETTLED`/`CANCELLED`, `ERR_INVALID_STATE`); allowed from any non-terminal state though approval requires `CONFIRMED`/`DELIVERED` — `implementation/routes/reservations.py:230-231`
- §3.7 Claim denial — insert — ambiguity — denial also stamps `reviewed_by_user_id` — `implementation/routes/claims.py:98`
- §3.7 Late fee — revise — ambiguity — fee accrues per `RETURNED` line only (a line still `PENDING_REALLOCATION` accrues nothing) — `implementation/calc.py:156-157`

**Not changed (deliberate):** the Flask catch-all handlers (`ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL` for unmatched routes/methods, `app.py:21-31`) cover paths outside the §4 endpoint catalogue and conflict with no PRD passage, so no rows were added to §5. Everything else walked — envelope shape, OCC ordering, quote/deposit/late/extension/damage/commission formulas, eligibility and ranking, recall cascade depths, settlement waterfall — matched the PRD as written.

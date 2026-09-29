# Worklog — task_2241_traveling_carnival_route_contract_management

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2241_traveling_carnival_route_contract_management/` and `workspace/` subdirectory (name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T12:52:00.365Z

Done. All three artifacts are in place for task 2241 and the linter is clean.

**Lint verdict (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2241_traveling_carnival_route_contract_management/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2241_traveling_carnival_route_contract_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2241_traveling_carnival_route_contract_management/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     15
  §1.8 instances scanned:     25
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  1172

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(The prior run reported 2 `(d) capture JSONPath unresolvable` violations — `$.data.total_count` captured off array-output list endpoints — fixed by capturing `$.data[0].id` and keeping the count claims in the asserts.)

**Files**
- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

**Counts**
- Entities: 15 · State machines: 10 (cyclic + compound + forking) · Calculations: 9 · Validations: 51 (priority-ordered) · Endpoints: 60 (POST/GET only) · Errors: 67 · Roles: 10 · OCC rules: 2
- Difficulty design (§1.8): 9 rule_ids × 2–3 instances = **25 instances** (≥18 required)
- Corner design (§1.9): **87 instances** across all 9 guide sections — entities 10, state_machines 13, calculations 15, validations 9, endpoints 5, errors 24, rbac 4, cross_cutting_complexity_layers 6, consistency_model 1; 56 carry full `test_recipe`s, 31 are `excluded_because` stubs citing a named §1.8 instance.
- Profile: `difficulty_level: expert_plus`, `temporal_windowing` + `quota_allocation`, flat topology, cyclic state machines, `segregation_of_duties`, `immediate` consistency, layers = dual_variant_calculation / cascading_side_effects / optimistic_concurrency / rate_threshold_triggers.

**Key findings while finishing**
- All 67 error ids are now genuinely triggerable: every id appears in at least one asserted 4xx trigger in §1.8 or §1.9 (verified programmatically). `ERR_LOT_CAPACITY_EXCEEDED` and `ERR_CREW_COVERAGE_INSUFFICIENT` were only *negatively* asserted in §1.8, so real §1.9 instances were added for them.
- Reachability fix in the scaffold itself: `ERR_SETTLEMENT_ALREADY_FINAL` was masked by the stop-state gate (finalize cascades the stop to CLOSED), so a new validation **priority 32** was inserted ahead of the priority-41 stop gate, and priority 45's check text was rewritten to defer to it.
- Corrected the stale `difficulty_level` comment in `complexity_profile` (it claimed 59 endpoints / 36 errors / 8 calculations).
- Structural constraints verified: `SCAFFOLD.yaml` contains no `scaffold_difficulty_design`/`scaffold_corner_design` keys; each design file has exactly one top-level key; instance names are unique across the union of both files; no instance has both `test_recipe` and `excluded_because`, and every stub's cited difficulty instance exists by name.
- No sibling task directory was read, listed, or grepped at any point.

## Step 3: Copy shared files — 2026-09-01T12:52:00.365Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T13:08:00.000Z

PRD generated at `workspace/PRD.md`.

## Document

**534 lines**, five top-level sections:

- **§1 Introduction** — three paragraphs establishing the traveling-amusement domain (haul chain, fair deals, lot capacity, late-closing money) from the scaffold `scenario`.
- **§2 Global Specifications** — 11 subsections: 2.1 Operating Roles and Caller Identity · 2.2 API Response Structure (pasted byte-verbatim) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Stale-Version Protection on Lot and Deal Writes · 2.6 Money, Hours and Rounding Discipline · 2.7 The Order in Which a Request Is Refused · 2.8 Cascade Discipline Across the Route Hierarchy · 2.9 Nested Reads and Path Resolution · 2.10 The Conserved Ledgers of a Lot · 2.11 Half-Open Intervals and UTC Day Buckets.
- **§3 Business Logic & Workflows** — 8 domain-derived subsections: haul-chain layout & sequencing · deal negotiation and countersignature · ride allocation and the footprint/power budget · permits and the jurisdiction paper trail · inspections and the slot ladder · crewing, shifts and duty exposure · readiness/gates/going dark · tickets, weather and settlement.
- **§4 Endpoint Definitions** — 60-row, 4-column table (Method, Path, Description, Authorized Roles) with a status-code preamble.
- **§5 Error Code Catalogue** — 67-row, 2-column table.

## Coverage audit (all three Hard Contracts PASS)

- **Contract 1 — Field-Name Coverage: PASS.** 137/137 required identifiers appear verbatim in backticks (122 entity field names + 8 input-only identifiers `decision`, `expected_contract_version`, `expected_route_stop_version`, `limit`, `offset`, `response`, `result`, `to_iso8601` + the readiness output's 8 fields + `current_utc`). Zero missing on the second pass. All 10 role names present. (First-pass scan showed 149 false "missing" — an artifact of naive backtick pairing across the ```json fences in §2.2; corrected by stripping fenced blocks.)
- **Contract 2 — Rule Coverage: PASS.** All 67 error identifiers appear in the §5 table *and* in the narrative body. All 48 state-machine transitions covered (16 rendered in prose form rather than literal arrows, each verified individually), including the four `→ DARK` origins with their identical cascade set, the conditional `TERMINATED`/`VOID` branch and its asymmetric effect on `total_guaranteed_cents`, both `RELEASED` fork branches, and `PROVISIONAL`/`DISPUTED → SUPERSEDED`. All 9 calculations reproduced with pinned evaluation orders (settlement steps 1–8, per-assignment-then-sum labor rounding, per-channel-then-sum tax) and every constant embedded with its value. All 51 validations rendered as an explicit 51-rung priority ladder in §2.7 with `applies_to` scopes, including priority 32 (`ERR_SETTLEMENT_ALREADY_FINAL`) explicitly documented as running ahead of the priority-41 stop gate and *why*. All endpoint `side_effects` accounted for. Both dual-variant pairs (`PROVISIONAL`/`FINAL` settlement, `SCHEDULED_BASIS`/`WORKED_BASIS` duty) stated with their three-way differences. Two gaps found and repaired during the audit: sequencing's re-derivation of `stop_count`, and the negotiation-round budget applying to the counter half of the loop as well as the send half.
- **Contract 3 — §3 Path Purity: PASS.** Zero `/`-prefixed tokens inside §3 (backticked or plain), zero bare HTTP-method tokens, zero method+path combos.

Additional checks: §2.2 byte-verbatim match confirmed; zero fuzzy hedge words; zero pseudocode leakage. Forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or grepped, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T15:27:01.625Z

The suite for task 2241 is complete.

## Files created

**`test_helpers/`** (9 modules, 2605 lines): `__init__.py` (single re-export surface), `api_client.py` (60 PRD endpoints), `api_errors.py` (67-member `ApiErrorId` enum), `types.py` (per-entity field contracts incl. the `common_fields: false` branch for `TicketSale`), `constants.py`, `test_users.py` (one header set per role), `factories.py` (payload builders), `assertions.py` (shape + ledger + instant assertions), `fixtures.py` (chain builders: `setup_planned_lot` → `setup_planned_lot_with_allocations` → `setup_sequenced_route_with_draft_contract` → `setup_committed_route_with_sent_contract` → `setup_confirmed_lot` → `setup_lot_in_setup` → `setup_open_lot` → `setup_provisional_settlement_on_struck_lot`).

**`test_suite/`**: `conftest.py` plus 17 test modules, `test_01`–`test_17`.

## Test counts

**106 tests, collecting in 0.26 s.**

- **Queue B (Corner / breadth): 56 tests** — `test_01`–`test_09`, one or more per non-stub corner instance across `entities`, `state_machines`, `endpoints`, `calculations`, `validations`, `error_codes`, `roles`, `concurrency`.
- **Queue A (Difficulty / depth): 50 tests** — `test_10`–`test_17`, ≥2 per instance for all 25 difficulty instances (`multi_step_arithmetic`, `iterative_loop`, `transitive_cascade`, `refusal_priority`, `inclusive_boundary`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`).

Every test carries exactly one terminal `Design:` line; all 106 tags resolve to real `name:` values in the two design yamls (81 distinct instances covered).

## Instances skipped

**Zero instances skipped.** Every non-stub instance in both indices had verbatim PRD coverage and a uniquely-derivable outcome.

## Design-yaml vs PRD defects (PRD taken as authority)

Corrected while translating: `authority: "LOCAL"` → `THIRD_PARTY`; `crew_role: "SETUP_CREW"` → `SETUP`; `employment_type: "SEASONAL"` → `SEASONAL_DOMESTIC`; `lot_surface: "ASPHALT"` → `PAVED`; `GET /routes/{id}/route-stops` → `GET /route-stops?route_id=`; `GET /route-stops/{id}/ride-allocations` → `GET /ride-allocations?route_stop_id=`. Dropped as non-PRD or non-API-testable: fields `usable_lot_sqft`, `allowed_amps`, `gross_ticket_revenue_cents`, `executed_by_user_id`; "no PUT/PATCH/DELETE" claims; a `sequence_index == null` claim (replaced with `status == "PLANNED"`); a `close_date < open_date → ERR_INVALID_REQUEST` trigger that the PRD does not state. One RELEASED-commit fixture had to be extended to CONFIRMED to be reachable.

## Citation audit

Automated audit over all 106 docstrings (one tag, tag resolves, tag is last line, no design-doc vocabulary, every `PRD §x: "…"` quote whitespace-normalized-verbatim in `workspace/PRD.md` *and* inside the labelled section). It found and repaired: 13 quotes using `...` elisions (illegal under the verbatim rule — re-quoted in full or split into separate citations), 2 misquotes of the §3.3 charged-amperage sentence, 1 fabricated §2.7 item (real item is "**Money already closed**"), and 4 quotes truncated mid-sentence. The audit now reports only one known false positive (`§4` — a `##`-level heading the section index did not track).

## Step 6: Generate implementation — 2026-09-01T15:27:01.625Z

Implementation is complete and verified.

## Files created

Core modules (flat, ~3,700 lines total):
- `app.py` — app factory, registers 10 blueprints, `ApiError`/`HTTPException`/catch-all handlers (404→`ERR_ROUTE_NOT_FOUND`, 405→`ERR_INVALID_REQUEST` 405, 400/415→`ERR_INVALID_REQUEST` 400, unexpected→500 `ERR_INTERNAL`); runs `debug=False, threaded=False, use_reloader=False` on `PORT` (default 10000)
- `db.py` — in-memory `Store` (15 dicts, no file/SQLite/seed data), logical clock defaulting to `2026-08-01T00:00:00Z`, version bumping deduped per request, `created_at` ordering helpers, UTC day buckets
- `errors.py` (67 error ids + full HTTP status map), `response.py` (envelope, `req_<20>` ids, list meta/pagination), `middleware.py` (401-then-403 role gate), `validators.py`, `calc.py` (9 pinned Decimal/ROUND_HALF_UP calculations + derived aggregates + posture ladder), `transitions.py` (10 state machines and their cascades), `serializers.py`
- `routes/` — `reference.py` (10), `routes_api.py` (4), `stops.py` (8), `contracts.py` (6), `allocations.py` (5), `permits.py` (4), `inspections.py` (3), `crew.py` (4), `money.py` (7), `weather.py` (8)
- `requirements.txt` (`flask>=3.0`), `start.sh` (executable; `set -euo pipefail`, cds to its own dir, honours `PORT`, installs Flask only if the import fails, `exec python3 app.py` in the foreground → clean empty store on every relaunch)

## Endpoints
60 registered, matching SCAFFOLD.yaml exactly (mechanical diff: `missing: []`, `extra: []`).

## Verification
Two throwaway smoke scripts were run against freshly booted `start.sh` processes (scratch files in `/tmp`, not in the deliverable):
- Happy path (~120 calls): full lifecycle route → sequence → allocations → contract negotiation/execute → permits → inspections → crew → gates → ticket sales → weather closure/adjudication → provisional settlement → dispute/reconcile → make-good → teardown → FINAL settlement → stop `CLOSED`/route `CLOSED`, plus the release/cancel branch (`DARK`/`VOID`). `FAILURES: 0`; all computed figures matched hand-derived values (transport fee 34000, travel 6.67 h, split 1255078, guarantee 500000 provisional / 750000 final, make-good 300000 at cap, final due 955078).
- Negative path (~300 calls) asserting both status **and** `error_id` for every refusal: `FAILURES: 0`, covering `ERR_ROUTE_HAS_NO_STOPS`, `ERR_STOP_CHAIN_INVALID`, `ERR_INSUFFICIENT_TRAVEL_WINDOW`, `ERR_STOP_NOT_CONTRACTED`, `ERR_LOT_CAPACITY_EXCEEDED`, `ERR_LOT_POWER_EXCEEDED`, `ERR_RIDE_DOUBLE_BOOKED`, both OCC 412s, `ERR_PERMIT_LEAD_TIME_VIOLATION`, `ERR_PERMIT_EXPIRED`, `ERR_PERMIT_NOT_APPROVED`, `ERR_INSPECTION_SLOTS_FULL`, `ERR_ALLOCATION_NOT_INSPECTABLE`, the 3-defect cascade (ride `OUT_OF_SERVICE` + `INSPECTION_HELD` surviving a later pass) with `ERR_INSPECTION_NOT_PASSED` and `ERR_RIDE_OUT_OF_SERVICE`, `ERR_WORKER_NOT_CERTIFIED`, `ERR_WORKER_VISA_LAPSED`, `ERR_CONSECUTIVE_DAYS_EXCEEDED`, `ERR_SHIFT_OUTSIDE_STOP_WINDOW`, `ERR_HOUSING_PADS_EXHAUSTED`, `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_EXCLUSIVITY_CONFLICT`, `ERR_LOAD_IN_NOT_OPEN`, `ERR_NO_COMMITTED_RIDES`, `ERR_GATES_BEFORE_OPEN_DATE`, `ERR_RIDE_MINIMUM_NOT_MET`, `ERR_CREW_COVERAGE_INSUFFICIENT`, `ERR_TEARDOWN_BEFORE_CLOSE_DATE`, `ERR_SALE_OUTSIDE_OPERATING_WINDOW`, `ERR_CLOSURE_NOT_ADJUDICATED`, `ERR_MAKEGOOD_PENDING`, `ERR_MAKEGOOD_STOP_MISMATCH`, `ERR_REFUND_NOT_ELIGIBLE`, `ERR_NO_PROVISIONAL_SETTLEMENT`, `ERR_SETTLEMENT_ALREADY_FINAL` (including the cancel path), all `*_STATE_INVALID` guards, duplicates, 401/403/404/400 shapes.

Both server logs show zero 500s and zero tracebacks across ~600 requests. `__pycache__` dirs were removed, so the directory holds only source, `requirements.txt` and `start.sh`.

One operational note: while restarting its own test server the agent briefly ran `pkill -f app.py`, which may have killed a per-test server belonging to the concurrently running unit-test agent; the harness relaunches a server per test, so at most one in-flight test would have been affected. Later restarts were scoped by port only.

## Step 7: Run tests and iterate — 2026-09-01T15:48:55.153Z

Done — clean 8-round parallel sweep, 106/106 in every round.

## Summary

**Iterations run:** 2 (sweep 1 → 3 consistent failures; sweep 2 → all 8 rounds 106/106).

**Tests deleted:** none. One *assertion* was removed under the partial-coverage rule (STEP 1c):
- `test_suite/test_02_initial_states_and_lifecycle_gates.py::test_countersigning_an_already_executed_deal_reports_the_contract_state` — dropped `assert stop["version"] == 2`. PRD does not uniquely determine whether the sequencing step bumps the head stop's `version`: §3.1 says sequencing "assigns `sequence_index` — 0 for the head … and computes travel time for each stop" (both values are already 0 on a single-stop route), while §2.4 says `updated_at`/`version` are refreshed "on every mutation of the row, including mutations that only touch computed aggregates" and that "Recomputing a derived aggregate … is a mutation and therefore bumps `version`". Two faithful readings (bump / no-bump) → the concrete figure is not derivable. All other assertions in that test were kept.

**Fixes applied to `test_suite/`:**
- `test_02_initial_states_and_lifecycle_gates.py`, `test_countersigning_an_already_executed_deal_reports_the_contract_state` — expected `error_id` corrected from `ERR_CONTRACT_STATE_INVALID` to `ERR_STOP_STATE_INVALID`. PRD §2.7 puts **route-stop state at priority 13** ("`PLANNED` to execute a contract") ahead of **contract state at priority 14**, and §3.2 states "Third, the stop must still be `PLANNED`, else `ERR_STOP_STATE_INVALID`"; the first execution confirmed the lot, so the stop gate fires first. Citation in the docstring updated to the PRD sentences that govern.
- `test_08_role_permissions_and_identity_scope.py`, `test_every_role_exercises_its_own_exclusive_operation` — the inline setup reserved a ride carrying the `version` captured at stop-creation time, after an intervening `sequence` call, and was refused `ERR_STALE_ROUTE_STOP_VERSION`. Now re-reads the lot immediately before reserving, matching PRD §2.5 ("the caller must supply the `version` of the route stop as they last observed it"). Same pattern already used by the `reserve_allocation` helper.

**Fixes applied to `test_helpers/`:**
- `fixtures.py`, `setup_lot_in_setup` — when `approve_event_permit=False`, the context stored the pre-submission (`DRAFT`) permit row because `submit_permit`'s response was discarded. Now captures it, so `ctx["event_permit"]["status"] == "SUBMITTED"` reflects PRD §3.4 ("**Submitting** a permit (`DRAFT → SUBMITTED`)").

**Fixes applied to `implementation/`:** none. All three failures traced to the test artifact; no PRD-required implementation check was touched.

## Step 8: Finalize PRD — 2026-09-01T16:00:00.000Z

`PRD_FINALIZED.md` is on disk with two inline edits.

## Line counts
- `PRD.md`: 533 lines — `PRD_FINALIZED.md`: 533 lines — **0.0% line delta** (both edits are inline inside existing long paragraphs; +2 sentences in §3.1, +1 clause in §3.2).

## Changes
- **§3.1 (sequencing paragraph)** — insert — pins that a *successful* sequencing writes every stop of the chain, bumping each stop's `version` and refreshing `updated_at` even when the `sequence_index` / `travel_hours_from_previous` it assigns are unchanged, and that a *refused* sequencing writes no stop — `implementation/calc.py:232-253` (`route_travel_feasibility`: validation loop first, then unconditional `db.touch(stop)` per chain stop), `implementation/routes/routes_api.py:43-56`.
- **§3.2 (execution paragraph)** — revise — pins that the execution gates are evaluated in the §2.7 global order, not in the narrative's "First/Second/Third/Fourth" order: route state → route-stop state → the deal's own `SENT` gate → segregation of duties → exclusivity, so a repeat execution against an already-confirmed lot answers `ERR_STOP_STATE_INVALID`, not `ERR_CONTRACT_STATE_INVALID` — `implementation/routes/contracts.py:136-148`.

No PRD edit for the other two Step 7 items: the `test_08` stale-version fix and the `fixtures.setup_lot_in_setup` permit-row fix. The first reduces to the same sequencing `version` bump (covered by edit 1) plus §2.5, which already determines the rule; the second is a pure fixture bug (the helper discarded `submit_permit`'s response) against behavior §3.4 and §2.2 already fix.

## Per-edit pre-edit search log

**Edit 1 — §3.1 sequencing version bump**
- (a) Subject: which rows a sequencing writes, and whether a stop's `version` bumps when the value assigned is unchanged.
- (b) Enumerated/read: `calc.py:232-253` `route_travel_feasibility` (unconditional `db.touch` on every chain stop, writes only after all travel-window checks pass); `calc.py:256-265` `reset_sequencing` (the *parallel* path — bumps only stops whose `sequence_index`/`travel_hours_from_previous` were non-zero); `calc.py:199-229` `build_chain` (DARK stops excluded → "every stop of the chain" ≠ "every stop of the route"); `db.py:110-119` `touch` (version bumps at most once per row per request); `db.py:95-107` `create` (`version` starts at 1); `calc.py:720-725` `recompute_posture` and every `db.touch(stop)` callsite (`transitions.py:82,92,116,125,136,149`, `routes/allocations.py:76,118`, `routes/crew.py:113,159`, `routes/inspections.py:60,115`, `routes/permits.py:121`, `routes/weather.py:95`, `routes/stops.py:112`); `routes/stops.py:23-69` (stop creation / `reset_sequencing` trigger); `serializers.py:95-119` (`version` echoed verbatim from the row).
- (c) Adjustments: (i) scoped the sentence to the sequencing operation and deliberately stated no general "assigning an unchanged value is still a mutation" principle, because `reset_sequencing` bumps *conditionally* — a general claim would have mis-described the `SEQUENCED → DRAFT` revert path; (ii) said "every stop of the chain" rather than "every stop of the route", since DARK stops are never walked or written; (iii) dropped a planned parenthetical ("the head, whose two figures are always 0") after checking `travel_hours_for` is applied to the head's own `haul_miles_from_previous` too — a head stop with non-zero haul miles gets non-zero travel hours, so that claim would have been false; (iv) added "a refused sequencing writes no stop at all" only after confirming the feasibility loop runs to completion before any `db.touch`.

**Edit 2 — §3.2 execution gate order**
- (a) Subject: relative evaluation order of the gates on `POST /contracts/{id}/execute`, specifically stop-state vs contract-state.
- (b) Enumerated/read: `routes/contracts.py:130-155` `execute_contract` (the only execution path — route → stop → contract → SoD → `_check_exclusivity`); `routes/contracts.py:158-173` `_check_exclusivity`; `routes/contracts.py:82-127` `send_contract`/`counter_contract` (the other places `ERR_CONTRACT_STATE_INVALID` and `ERR_ROUTE_STATE_INVALID` are raised, to be sure the new clause is scoped to execution and does not re-describe send/counter, where the route gate also precedes the contract gate); `validators.py`/`v.path_row` usage for 404-before-state; grep for all `ERR_SEGREGATION_OF_DUTIES` and `ERR_EXCLUSIVITY_CONFLICT` sites (single site each); §2.7 items 12/13/14/19/37 left verbatim.
- (c) Adjustment: phrased the clause as "they are evaluated in the global order of §2.7 rather than in the order they are listed here" and named the sequence explicitly including the deal's own `SENT` gate between stop state and SoD, instead of re-numbering the existing First/Second/Third/Fourth sentences — this leaves all four original sentences verbatim and confines the new claim to the execute endpoint.

## Step 9: Complete PRD — 2026-09-01T16:12:00.000Z

`workspace/PRD_COMPLETED.md` is on disk.

## Counts

- **PRD_FINALIZED.md**: 533 lines / 93,352 chars → **PRD_COMPLETED.md**: 533 lines / 97,180 chars (**+3,828 chars**, 0 line delta, 29 lines revised in place, no new sections/paragraphs).
- **Ambiguity-pins: 22** · **Mismatch-revisions: 7**

## Changes

- §2.3 Pagination — insert — ambiguity — out-of-range/non-integer `limit`/`offset` are refused with `ERR_INVALID_REQUEST` rather than clamped; empty falls back to default — `response.py:69-90`
- §2.3 Pagination — insert — ambiguity — equal `created_at` ties broken by insertion order — `db.py:125-127`
- §2.4 Identity/Timestamps — insert — ambiguity — caller-supplied instants stored/echoed verbatim, not normalized to 3-digit form — `validators.py:194-202`
- §2.4 Logical clock — insert — ambiguity — `current_utc` echoed verbatim as supplied — `routes/reference.py:211-213`
- §2.7 step 4 — insert — ambiguity — jurisdiction/lot/ride *path* ids 404 as `ERR_REFERENCED_ENTITY_NOT_FOUND` — `validators.py:254-272`
- §2.7 step 14 — revise — **mismatch** — on settlement creation the contract-state gate precedes the stop-state gate — `routes/money.py:91-96`
- §2.7 step 24 — revise — **mismatch** — gate applies the inspection test directly, not the first-match-wins posture value — `routes/stops.py:141-143`
- §2.7 step 44 — revise — **mismatch** — make-good cap evaluated after step 49, before 50/51 — `routes/weather.py:114-132`
- §2.9 Nested reads — insert — ambiguity — a closure's make-goods accept a `status` filter — `routes/weather.py:166-167`
- §3.1 Jurisdictions — revise — **mismatch** — `housing_permit_required` is stored/echoed only; no booking is refused for it — `routes/crew.py:24-115` (flag never read)
- §3.1 Lots — insert — ambiguity — `lot_area_sqft`/`power_amps_available` are whole numbers — `routes/reference.py:86-87`
- §3.1 Routes — insert — ambiguity — `home_base_state` is a required non-empty string of any shape — `routes/reference.py`→`routes/routes_api.py:25`
- §3.1 Stops — revise — **mismatch** — only the same-route condition is checked at creation; cyclicity is unreachable there and caught at sequencing; `haul_miles_from_previous` is a whole number — `routes/stops.py:39-41`
- §3.2 Execution — insert — ambiguity — "same lot" = same `venue_id`; window overlap compared as closed intervals — `routes/contracts.py:165-171`
- §3.2 Cascade — insert — ambiguity — cascade skips a `RESERVED` allocation whose ride is `OUT_OF_SERVICE`, leaving it `RESERVED` — `transitions.py:93-97`
- §3.3 Rides — insert — ambiguity — `footprint_sqft`/`power_amps` are whole numbers — `routes/reference.py:137-138`
- §3.3 Double-booking — insert — ambiguity — equal `sequence_index` → the candidate's stop supplies the required gap — `calc.py:812-818`
- §3.4 Permits — insert — ambiguity — non-zero `axles_declared` on a non-`TRANSPORT` permit is stored verbatim but never priced — `routes/permits.py:37-44`
- §3.4 Decision — insert — **mismatch** — the denial-reason rule runs after the `SUBMITTED` gate — `routes/permits.py:108-112`
- §3.5 Slot ladder — insert — ambiguity — `scheduled_date` rendered `YYYY-MM-DDT14:00:00Z`, no fractional digits — `calc.py:766-767`
- §3.5 Manual scheduling — insert — ambiguity — supplied `scheduled_date` echoed verbatim — `routes/inspections.py:53`
- §3.5 Fail branch — revise — **mismatch** — posture re-derived by the ladder (event-permit test can outrank), not set directly to `INSPECTION_HOLD` — `routes/inspections.py:114-115`, `serializers.py:117`
- §3.6 Visa posture — insert — ambiguity — exactly thirty days counts as `VISA_EXPIRING` — `calc.py:527`
- §3.6 CrewChief — revise — **mismatch** — worker read carries no ownership check; only the roster read is self-scoped — `routes/reference.py:196-201`
- §3.7 Posture ladder — insert — ambiguity — any `EXPIRED` `EVENT` permit, whatever its window, makes the blocking error `ERR_PERMIT_EXPIRED` — `calc.py:660-664`
- §3.7 Readiness — insert — ambiguity — `ride_minimum_required` is 0 with no `EXECUTED` deal — `serializers.py:276`
- §3.7 Begin setup — insert — ambiguity — `ERR_PERMIT_EXPIRED` when a lapsed `TRANSPORT` permit exists and no approved covering one — `routes/stops.py:116-131`
- §3.7 Open gates — insert — ambiguity — inspection test applied directly; ride minimum taken as 0 with no executed deal — `routes/stops.py:141-152`
- §3.8 Ticket sales — insert — ambiguity — `business_date` is a full instant compared inclusively against both window edges — `routes/money.py:36,45-48`
- §3.8 Dispute — insert — ambiguity — `dispute_reason` mandatory non-empty, else `ERR_INVALID_REQUEST` — `routes/money.py:139`

Notable non-changes verified as already uniquely pinned: the full 51-step refusal order for every other endpoint, all nine calculation formulas and their rounding order, the four lot ledgers (all derived at read time from contributing rows), the settlement 8-step order and both variants, cascade fan-out order, and every endpoint's role list. One residual §2.7 ordering divergence (travel-window at 29 vs chain/no-stops at 34-35 during sequencing) was left alone: the conflicting conditions are mutually unreachable, so no caller can observe it.

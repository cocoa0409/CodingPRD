# Worklog — task_2616_prepaid_restaurant_ticketing_experience_reservations

## Step 1: Create task directory — 2026-09-03T20:14:19.686Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2616_prepaid_restaurant_ticketing_experience_reservations` and its `workspace/` subdirectory. Index 2616 was pre-assigned by the invoking pipeline (no ./tasks/ scan performed, per instruction, to avoid collision with the up-to-32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-03T22:36:51.648Z

All three scaffold artifacts are complete and the linter is clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2616_prepaid_restaurant_ticketing_experience_reservations/`):

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` (§1.0–§1.7) | 3509 | 163801 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) | 3360 | 204245 |
| `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9) | 8104 | 527748 |

**Lint**: `VERDICT: clean lint` — 67 §1.5 endpoints, 14 §1.1 entities, 29 §1.8 instances, 74 §1.9 recipe instances, 1897 calls checked; all §1.1 FKs have reverse-reachability.

**What the scaffold covers**
- 14 entities: Restaurant, ExperiencePackage, AddOn, Service, TicketClass, Table, Guest, Reservation, ReservationAddOn, DietaryNote, PaymentTransaction, WaitlistEntry, RefundException, GoodwillCredit. `entity_topology: flat`, `state_machine_shape: parallel`, `consistency_model: immediate`.
- 67 endpoints, including the ticketed-inventory lifecycle (package/add-on/service/ticket-class creation, publish, demand-tier repricing, pause/resume), reservation hold -> payments -> confirm -> assign-table -> seat -> complete/no-show, cancel with the forfeiture ladder, name-change and transfer (resale prevention via cutoffs and per-guest transfer caps), dietary notes with kitchen ack/reject/amend, waitlist join/offer/claim, unsold-inventory release runs, hold sweeps, refund exceptions with decide, and goodwill credits with redeem/revoke.
- 4 parallel state machines (Reservation payment x fulfillment dimensions, Service, TicketClass, DietaryNote, RefundException, GoodwillCredit, WaitlistEntry), 12 calculations (tiered `ticket_price_per_cover`, `reservation_charge_breakdown` with per-line service-charge rounding, `cancellation_settlement`, `waitlist_priority_score`, `dietary_prep_minutes`, `release_run_allocation` waterfall, two interval-merge rules for table turns and kitchen prep load, plus four reconciliation/projection rules), 67-plus prioritised validations, 5 roles (Guest, RestaurantManager, KitchenLead, GuestServices, PlatformAdmin) under `role_model: segregation_of_duties`, and 3 OCC `concurrency_rules`.
- Complexity layers exercised: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation.

**Counts**
- §1.8: 9 difficulty rules / 29 instances.
- §1.9: 108 instances across all nine guide sections — entities 14, state_machines 15, calculations 18, validations 18, endpoints 10, errors 12, rbac 9, cross_cutting_complexity_layers 10, consistency_model 2. Of these, 74 carry a full `test_recipe` and 34 are `excluded_because` stubs; every cited `difficulty_instance` resolves to a real §1.8 instance name, no stub carries a recipe, no recipe instance is missing one, and all 137 instance names are unique across both files.

No sibling task directory was read at any point; the design came from the scenario text plus the scaffold-generator skill and its claim-extraction guide.

## Step 3: Copy shared files — 2026-09-03T22:37:05.926Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T22:56:23.106Z

PRD generation for task 2616 is complete.

## Output
`workspace/PRD.md` — **637 lines**, built via 11 chunked `cat >> ... <<'PRDEOF'` appends plus two targeted in-place refinements (no giant Write; no output-cap loss).

## Section list
- `# Prepaid Restaurant Ticketing API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Operator Identity and RBAC · 2.2 API Response Structure · 2.3 Pagination · 2.4 Common Resource Properties and the Logical Clock · 2.5 Money, Basis Points and Rounding Discipline · 2.6 Seat-Pool Accounting and the Precedence Ladder · 2.7 The Immutable Money Ledger and the Derived Payment Dimension · 2.8 Stale-View Rejection on Seat, Line and Credit Writes · 2.9 Resource Addressing and Left-to-Right Identifier Validation · 2.10 Segregation of Duties in Refund Adjudication · 2.11 The Order in Which a Request Is Rejected
- `## 3. Business Logic & Workflows` — 3.1 Onboarding, the Experience Catalogue, and Bringing a Service to Market · 3.2 What a Cover Costs · 3.3 Holding Seats, Ordering Add-Ons, and Prepaying the Ticket · 3.4 Dietary Notes, Kitchen Acknowledgement and Prep Load · 3.5 Working the Floor · 3.6 Name Changes, Transfers and Keeping Brokers Out · 3.7 Unwinding a Booking · 3.8 The Waitlist · 3.9 Contesting a Settlement · 3.10 Suspending Sales, Resuming Them, and the Status Moves Nobody Requests
- `## 4. Endpoint Definitions` — 67 endpoints, exactly 4 columns
- `## 5. Error Code Catalogue` — 79 error ids, exactly 2 columns

**Completeness:** the file ends at the final row of the §5 table — a real section boundary, not mid-sentence. (Orchestrator independently verified: `tail -20` ends on a complete `| ERR_GOODWILL_EXCEEDS_BALANCE_DUE | 402 |` table row.)

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** Extracted all 140 `entities[].fields[].name` values plus all 93 distinct endpoint `input` identifiers (union 151 unique, incl. `expected_ticket_class_version`, `expected_reservation_version`, `expected_goodwill_credit_version`, `close_service`, `decision`, `decision_note_code`, `recipient_guest_id`, `recipient_guest_name`, `table_id`, `guest_index`, `current_utc`, `limit`, `offset`) and diffed against the 457 backticked tokens in PRD.md (code fences excluded from the diff to avoid triple-backtick parity error). **Missing: 0.** All 79 error ids also appear in §1–§4 prose, not just the §5 table. All enum values across every `one of {...}` constraint appear backticked: **0 missing**.

**Contract 2 — Rule Coverage: PASS.** All 54 state-machine transitions across the 8 machines appear in explicit `FROM -> TO` arrow prose (verified programmatically; §3.10 was added specifically to close the TicketClass gap — pause/resume plus the six ladder-driven and four CLOSED edges). All 67 priority-ordered validations are rendered as a 67-item numbered ladder in §2.11 (count verified), with the 14 `ERR_*_NOT_FOUND` codes enumerated in §2.9 and cross-referenced from ladder items 5 and 6. All 12 calculations are given step-for-step with every constant: DOW/tier price tables, scarcity bands, `STANDARD`/`STRICT` forfeiture ladders, `REBOOK_FEE_BANDS` keyed on the step-5 forfeiture, waitlist score weights with the loyalty cap of 8, `SEVERITY_PREP_MINUTES`, the two-pass release waterfall, half-open table interval vs closed prep interval, invariants I1/I2/I3, and the two pinned precedence orders (`payment_status` 6-rule derivation, goodwill `status` 4-rule order). All 3 concurrency rules with their `expected_*_version` fields and 412 codes are in §2.8. Sibling-branch symmetry rendered at equal density for: `deposit_basis`/`full_ticket_basis`, `FAIR_QUEUE`/`YIELD_WEIGHTED`, and the deliberately disjoint `APPROVED`/`DENIED` fork.

**Contract 3 — §3 Path Purity: PASS.** Scanned the 1,028 backticked tokens in the §3 region: **0** start with `/`, **0** are a bare HTTP method, **0** combine method+path. A raw (unbackticked) path-literal scan of §3 also returned 0 hits. §3 uses state-transition and role+action-verb framing throughout.

Also verified: the §2.2 block is byte-identical to the skill's source file; no fuzzy words (`approximately`/`roughly`/`conservatively`/`etc.`) and no pseudocode lines anywhere; the only code fences are the two verbatim §2.2 JSON envelopes.

**Constraints honoured:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced; no sibling task directory was read. Worked examples in the PRD come only from `SCAFFOLD.yaml`'s own `note:` fields.

Four scaffold-internal inconsistencies were resolved deliberately and consistently: `deposit_frozen` (both the ledger-driven and confirm-driven statements written), `deposit_due_cents` first-payment threshold ("at least", per validation priority 61), `seat_pool_reconciliation` transfer double-counting (successor counted, `TRANSFERRED_OUT` predecessor excluded), and `seat_to_utc` (pinned at seating to `seat_from_utc` + `turn_time_minutes`, following the transition and endpoint `side_effects` 2:1 over the field description, with the table-occupancy interval separately documented as adding `turn_buffer_minutes`).

## Step 6: Generate implementation — 2026-09-03T23:33:00.000Z

Implementation complete and verified.

## Modules (`.../workspace/implementation/`, 2974 lines total)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | foreground launcher, `exec python3 app.py`, guarded `pip install` (skipped once flask imports), `0.0.0.0:$PORT` (default 10000), executable |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 57 | Flask app factory, 4 route-module registrations, `ApiError`/`HTTPException`/`Exception` handlers -> envelope error body |
| `common.py` | 328 | error->HTTP catalog (all 100 ids), `ApiError`, logical clock (default `2026-08-01T00:00:00Z`), 14 in-memory dict tables, `new_record`/`must_get`/`rows`/`public`, `Watch` (change-detecting single `version` bump + `updated_at`), Decimal `ROUND_HALF_UP` money helpers, `meta`/`response_type`/`data` envelope with pagination inside `meta` |
| `guards.py` | 262 | `X-User-ID`/`X-User-Role` auth (priorities 1-3), guest/restaurant/reservation ownership (4), typed body validators, `limit`/`offset` (1-100 / >=0, defaults 10/0), query filtering |
| `calc.py` | 535 | 12 calculations: calendar x tier x scarcity pricing with the 8500-18000 clamp, per-line service charge, ledger rollup + the 6 pinned `payment_status` rules, prep minutes, seat-pool precedence ladder, forfeiture ladders (STANDARD/STRICT x DEPOSIT/FULL basis) + rebooking-fee band, waitlist score + FAIR_QUEUE/YIELD_WEIGHTED ranking, promotion with the pinned pool asymmetry, service roll-ups, scrutiny cascade |
| `routes_catalog.py` | 282 | restaurants, guests, tables, packages, add-ons + the 4 restaurant reverse indexes |
| `routes_service.py` | 384 | services, publish/demand-tier/cancel/release-run (two normative passes)/hold-sweep, ticket classes, price-quote, pause, resume |
| `routes_reservation.py` | 689 | holds, payments, confirm, add-on lines, dietary notes + ack/amend, assign-table (half-open turn conflict, closed prep window), seat, complete, no-show, cancel, name-change, transfer (successor + paired TRANSFER_OUT/IN) |
| `routes_money.py` | 426 | ledger reads, waitlist join/claim/withdraw, refund exceptions + decide, goodwill credits + redemptions/revoke, `POST /_clock/set_current_utc` |

## Endpoints
**67 of 67** registered, matching PRD §4 method-for-method (verified by enumerating `app.url_map`). Rejection order follows the §2.11 ladder verbatim (SoD at 9 precedes the exception state check at 25; OCC at 10-12 precedes state; safety 30/31 precede scheduling and money).

## Smoke test (`PORT=18616 bash start.sh`)
Full happy path plus adversarial probes, all green: clock set -> restaurant/guest/package/service/ticket-class -> publish -> price-quote -> reservation (grand total 25740, deposit 7722 on 7.25% service charge and 30% deposit_bp) -> deposit payment -> confirm (`CONFIRMED`/`DEPOSIT_PAID`) -> ledger list -> waitlist join (score 1100) -> early cancel (0% forfeiture -> `REFUNDED`) -> late cancel at T-24h (forfeited 4361 = 50% of deposit + 500 rebooking fee, refunded 21379, `PARTIALLY_REFUNDED`) -> refund exception -> SoD 403 on self-decide -> approval by a second operator (shortfall 2181) -> credit issued by a third -> redemption returns the `GOODWILL_REDEMPTION`/`CREDIT_APPLIED` ledger row and drives the credit to `EXHAUSTED` -> revoke by the issuer 403 -> `ERR_FORBIDDEN_RESOURCE_OWNER` 403, `ERR_INVALID_PAGINATION` 400, `ERR_RESERVATION_NOT_FOUND` 404, missing headers 401. No tracebacks in the server log; the process was killed by its own PID resolved from port 18616 (never a pattern kill), and the port is free.

Also confirmed: `python3 -m py_compile` clean on all 8 modules, `pyflakes` clean (it caught one real bug — an undefined `return_seats` in the cancel path — now fixed), a fresh boot on 18617 reports `total_count=0` for every collection (no seeding), and there is no `open(`, sqlite, json-dump, or `/tmp` reference anywhere in the code.

## Step 5: Generate unit tests — 2026-09-03T23:53:00.000Z

Stage 1 and Stage 2 are complete and green.

## Files written

**`test_helpers/` — 9 files, 3,061 lines** (task root, PRD-specific infra only; nothing generated that `prd_bench_local_runner.testing` already provides)

| file | lines |
|---|---|
| `__init__.py` | 95 |
| `api_client.py` | 418 |
| `api_errors.py` | 200 |
| `assertions.py` | 354 |
| `constants.py` | 455 |
| `factories.py` | 330 |
| `fixtures.py` | 780 |
| `test_users.py` | 110 |
| `types.py` | 319 |

**`test_suite/` — `conftest.py` (36 lines) + 21 test files, 18,914 lines, 278 tests**

Queue A (difficulty, 9 files / 82 tests): `test_01_dual_variant_calc.py` 386/4, `test_02_combinatorial_formula.py` 633/10, `test_03_non_linear_state_machine.py` 1028/14, `test_04_transitive_cascade.py` 694/9, `test_05_priority_pair_validation_conflict.py` 637/9, `test_06_boundary_precision_check.py` 758/11, `test_07_cross_entity_state_dependency.py` 821/10, `test_08_resource_temporal_overlap.py` 415/6, `test_09_compensating_invariant.py` 653/9.

Queue B (corner, 12 files / 196 tests): `test_10_corner_entities.py` 1363/29, `test_11_corner_state_machines.py` 1026/21, `test_12_corner_state_machines_late.py` 1081/17, `test_13_corner_calculations.py` 1070/19, `test_14_corner_validations.py` 1192/14, `test_15_corner_validations_late.py` 1437/24, `test_16_corner_endpoints.py` 1239/18, `test_17_corner_errors.py` 578/7, `test_18_corner_rbac.py` 1284/12, `test_19_corner_rbac_late.py` 1293/18, `test_20_corner_cross_cutting.py` 989/9, `test_21_corner_consistency.py` 337/8.

Every file was written by chunked `cat >>` appends and verified with `wc -l` + `ls -la`.

## Instance coverage

- **Queue A: 29/29 translated, 0 skipped.** Every difficulty instance carries at least 2 tests (both branches of each dual-variant/boundary pair asserted independently).
- **Queue B: 74/74 non-stub instances translated, 0 skipped.** The 34 instances bearing `excluded_because:` were correctly left untranslated.
- Total tagged tests 278; every docstring ends with exactly one verbatim `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line. Audits report **0 uncovered instances, 0 stray/unmatched tags, 0 dual tags, 0 citation defects** (every quoted PRD sentence survives a literal grep of `workspace/PRD.md`).

## Validation

`python3 -m compileall` clean; `pytest test_suite --collect-only -q` collects **278 tests** with no import/collection errors. Hygiene greps over `test_suite/` return zero hits for scaffold/recipe/design-index vocabulary, zero `skip`/`xfail`/`TODO`/`placeholder`, zero references to `workspace/implementation`.

## PRD-first corrections (design indices contradicted PRD.md; PRD won)

`payment_status` on a partial settlement (`PARTIALLY_REFUNDED`, not `REFUNDED`); `offer_round` not credited by a cancel-driven promotion (only by a lapsed offer); `seat_to_utc` = `seat_from_utc + turn_time_minutes` and null until seating; several undeclared list filters removed (`payment_status`, `fulfillment_status`, ledger `kind`, waitlist `status`, service `restaurant_id`/`status`); illegal enum values (`HELD`->`PENDING`, `PARTIALLY_PAID`->`DEPOSIT_PAID`, plus `SERVICE_RECOVERY`/`OUTSIDE_POLICY`/`SERVICE_ISSUE`/`NO_BASIS`/`TRAVEL`); a no-show *does* return seats per §3.5; an anaphylaxis note yields `ERR_DIETARY_ACK_REQUIRED` (ladder 30) not `ERR_DIETARY_NOTE_PREP_REJECTED`; price literal 10200->11016; and several probes relocated onto DRAFT services so ladder step 14 would not shadow steps 36/52/55.

Note: `workspace/implementation/` was populated concurrently by the Step 6 implementation generator; the test generator neither read nor wrote anything under it. Orchestrator verified `test_helpers/` and `test_suite/` both landed at the task root (not under `workspace/`).

## Step 7: Run tests and iterate — 2026-09-04T00:13:24.766Z

All 8 parallel rounds pass 278/278. Done.

## Summary

**Iterations run: 2.** Iteration 1: 253/278 in all 8 rounds, 25 failures, union == intersection (perfectly deterministic — no flakiness, no load artifacts). Iteration 2: 278/278 in all 8 rounds.

### Tests deleted
**None.** All 278 tests still collect. Two individual *assertions* were removed under the STEP 1c partial-coverage rule (see below); no test was deleted, skipped, or xfailed, and no `error_id` assertion was downgraded to an HTTP-status assertion.

### Fixes applied to `test_helpers/`
- **`test_helpers/assertions.py`** — added `assert_instant_equals(actual, expected, field)` (plus an `_as_instant` ISO-8601 parser). PRD §2.4 pins "three fractional digits" for `created_at` and `updated_at` *only*; it is silent on the lexical rendering of `seat_from_utc`, `seat_to_utc`, `offer_expires_at_utc`, `hold_expires_at_utc` and a credit's `expires_at_utc`. The implementation renders every instant as `...:00.000Z`; the tests compared those fields against second-precision literals (`...:00Z`). Two PRD-faithful implementations diverge on the spelling, so the format expectation failed unique derivability, while *which instant* each field carries is verbatim PRD ("It writes `assigned_table_id` and `seat_from_utc` onto the reservation"; "Seating pins `seat_to_utc` to `seat_from_utc` plus the service's `turn_time_minutes`"; "sets `offer_expires_at_utc` to the logical clock plus the restaurant's `offer_ttl_minutes`"). The helper keeps the covered assertion and drops only the uncovered rendering.

### Fixes applied to `test_suite/`
- **33 assertion sites across 7 files** (`test_03`, `test_05`, `test_06`, `test_07`, `test_08`, `test_15`, `test_16`) rewritten from `assert x["...  _utc"] == LITERAL` to `A.assert_instant_equals(...)`. This accounted for 24 of the 25 failures. All 33 were fixed, not just the 24 that tripped, because the untripped ones sat behind an earlier failing assertion in the same test and would have failed as soon as it was fixed.
- **`test_suite/test_03_non_linear_state_machine.py`** — removed the single assertion `entry["offer_expires_at_utc"] is None` on the `OFFERED -> EXPIRED` termination edge. Textbook **branch-asymmetric side effect**: PRD §3.8 renders the `OFFERED -> WAITING` cycle branch fully ("its `offered_reservation_id` and `offer_expires_at_utc` are cleared to null") but compresses the termination branch to "`offer_round` is credited by 1 and the entry permanently stops being an eligible promotion target" — no clearing stated. The test's other assertions (status `EXPIRED`, `offer_round == 2`, `priority_score == 900`, the released-pool seat accounting, and the `ERR_WAITLIST_ENTRY_INVALID_STATE` refusal of the late claim) are all PRD-verbatim and were kept.

### Fixes applied to `implementation/`
- **`workspace/implementation/routes_money.py`, `claim_offer`** — real ladder-ordering defect. The route evaluated the *offered reservation's* `fulfillment_status` (-> `ERR_RESERVATION_INVALID_STATE`) before the *entry's own* status check, so claiming a `WITHDRAWN` entry answered `ERR_RESERVATION_INVALID_STATE` instead of `ERR_WAITLIST_ENTRY_INVALID_STATE`. §2.11 item 17 enumerates a closed list of operations for the reservation-state check and a waitlist claim is not among them, while item 22 explicitly covers it ("`OFFERED` to claim ... otherwise `ERR_WAITLIST_ENTRY_INVALID_STATE`"); §3.8's own enumeration likewise lists "the entry to be `OFFERED`" first. Moved the reservation-`PENDING` check to after the entry-status and offer-expiry checks. No PRD-required check was removed or weakened — the class-sellability check stays at ladder 15 and hold-expiry at 18 where the ladder puts them. Also added item 18's stated `For a PENDING reservation` qualifier to the hold-expiry guard, which otherwise could have fired on a cancelled offer hold.

Storage remains in-memory only (no `open(`/sqlite/json-dump/`/tmp` references), and no endpoint, field, or capability was added.

**Orchestrator independent verification:** all 8 `workspace/implementation/results.{1..8}.json` exist (~95.6 KB each, written 2026-09-04 00:11) and each parses to `passed=278 / total=278 / failed=0`. The clean sweep is confirmed from the per-round artifacts, not from the subagent's claim or from `sweep.log`.

## Step 8: Finalize PRD — 2026-09-04T00:18:15.546Z

`PRD_FINALIZED.md` is written at `workspace/PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 637 lines · `PRD_FINALIZED.md`: 639 lines · **+2 lines (+0.31%)**
- File verified intact: still ends with the complete §5 error catalogue (79 `ERR_*` rows, unchanged), diff touches only 3 regions.

## Changes (3 edits)
- **§2.4 (Common Resource Properties)** — insert — new paragraph pinning that every non-`created_at`/`updated_at` ISO 8601 UTC instant is persisted and returned with three fractional digits and a trailing `Z`, normalised at write time whatever precision the client supplied; names `seating_start_utc`, `seating_end_utc`, `hold_expires_at_utc`, `seat_from_utc`, `seat_to_utc`, `offer_expires_at_utc`, credit `expires_at_utc`; excludes `service_date` as not an instant — `implementation/common.py:132-137` (`to_iso`), `calc.py:457`, `calc.py:526`, `routes_money.py:341`, `routes_service.py:48-49`, `routes_reservation.py:436,460`.
- **§3.8 (`OFFERED -> EXPIRED` termination edge)** — revise — added that the termination branch clears nothing: `offered_reservation_id` and `offer_expires_at_utc` are left as they stand, unlike the cycle branch — `implementation/routes_service.py:245-252`.
- **§3.8 (claim)** — revise — pinned that a claim is not an item-17 operation, so the offered reservation's `fulfillment_status` is tested *after* the entry-status and offer-expiry checks and refuses with `ERR_RESERVATION_INVALID_STATE`, while items 15 and 18 keep their own rungs (18 only reaching a still-`PENDING` reservation) — `implementation/routes_money.py:159-186`.

## Per-edit pre-edit search log

**Edit 1 — §2.4 instant rendering**
- (a) Subject: the lexical rendering of every ISO 8601 instant the API emits, and whether any instant escapes the three-digit form.
- (b) Enumerated/read: `common.py:132-137` (`to_iso`, the sole formatter — always `%03d` milliseconds); every `to_iso(` callsite via `grep -rn "to_iso(" *.py` -> `common.py:217/222/276/280` (`created_at`/`updated_at`), `common.py:306` (`api_request_timestamp`), `calc.py:457` (`hold_expires_at_utc` on both direct and promoted holds), `calc.py:526` (`offer_expires_at_utc`), `routes_money.py:341` (credit `expires_at_utc`), `routes_service.py:48-49` (`seating_start_utc`/`seating_end_utc`), `routes_reservation.py:436` (`seat_from_utc`), `routes_reservation.py:460` (`seat_to_utc`); every `_utc` key via `grep -rn "_utc" *.py` to prove no instant field is written from client input un-normalised; all `req_dt`/`opt_dt` callsites (`guards.py:158-169`, `routes_service.py:29-30`, `routes_reservation.py:386`, `routes_money.py:319,435`); `routes_service.py:45` (`service_date` echoed verbatim, a date not an instant); `routes_reservation.py:648-650` (transfer successor sets these instants to `None`).
- (c) Adjustment: dropped a first draft that asserted `service_date` "keeps its `YYYY-MM-DD` form" — the impl echoes the client string without re-normalising (`body["service_date"]`), so the claim could be false for padded input; rewritten as "is not an instant, and this rendering rule does not reach it". Also worded as a rendering/normalisation rule rather than "server-generated", so it stays true of the client-supplied `seating_*_utc`, `seat_from_utc` and credit `expires_at_utc` as well as the derived ones, and left the `None` cases untouched (rule speaks only of instants that are persisted).

**Edit 2 — §3.8 termination edge**
- (a) Subject: which fields the `OFFERED -> EXPIRED` edge writes on a `WaitlistEntry`.
- (b) Enumerated/read: `grep -rn 'entry\["status"\]\|entry\["offer' *.py` -> the only producer of entry `EXPIRED` is `routes_service.py:239-252` (sweep), which does `offer_round += 1`, sets `status = "EXPIRED"`, calls `rescore` and clears neither field; the sibling cycle branch `routes_service.py:246-249` (which does clear both); `calc.py:319-324` (`rescore` writes only `priority_score`, so "clears nothing" is not contradicted); `calc.py:495` (`eligible_entries` filters `status != "WAITING"`, so `EXPIRED` is never re-promoted, consistent with "permanently stops being an eligible promotion target"); `routes_money.py:111-114` (join-waitlist reads the `EXPIRED` entry's `offer_round`); `routes_money.py:176-178` (claim refuses non-`OFFERED`); `routes_money.py:199-201` (withdraw refuses non-live); `routes_money.py:190` and `routes_reservation.py:50-53` (the other two places entry fields move — claim clears only `offer_expires_at_utc`, service-cancel/withdraw clear neither).
- (c) Adjustment: scoped the sentence to the termination branch only ("Unlike the cycle branch..."), so it cannot be read as a general statement about `EXPIRED` entries or about the claim/withdraw paths that also leave `offered_reservation_id` in place. Did not add any claim about `priority_score`, which §3.8's existing "recomputed ... on every offer-round change" already determines and the impl does call on both branches.

**Edit 3 — §3.8 claim ladder position**
- (a) Subject: the rung at which a waitlist claim tests the offered reservation's `fulfillment_status`, and the error it raises.
- (b) Enumerated/read: `routes_money.py:151-192` (the whole `claim_offer` route, post-fix order: role -> entry existence -> ownership -> class sellability (15) -> hold expiry, `PENDING`-qualified (18) -> entry status (22) -> offer expiry (23) -> offered-reservation `PENDING`); §2.11 items 15/17/18/22/23 in `PRD.md`; the other `require_state`/hold-expiry sites to confirm item 17 and item 18 are used consistently elsewhere — `routes_reservation.py:28-32` (`hold_guard`, also `PENDING`-qualified), `routes_reservation.py:449-451` and `routes_reservation.py` confirm/payment/complete/no-show/cancel/name-change/transfer state guards (all item-17 operations, unaffected by this wording); `routes_money.py:199-215` (withdraw, which has no reservation-state rung at all and is not described by the new sentence).
- (c) Adjustment: deleted a drafted closing sentence claiming a non-`OFFERED` entry "therefore answers `ERR_WAITLIST_ENTRY_INVALID_STATE` even when the offer's hold has also been cancelled or expired" — false whenever the offered class is `PAUSED`/`CLOSED` (rung 15 fires first) and ambiguous between "hold-expiry instant passed" and "reservation left `PENDING`" (rung 18 vs. the new rung). Replaced with a neutral statement that rungs 15 and 18 keep their own positions, with 18's existing `PENDING` qualifier restated rather than redefined.

**Orchestrator independent verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly the 3 described regions (one §2.4 insert at line 105, two §3.8 revisions); 639 lines; file still ends on the final complete `| ERR_GOODWILL_EXCEEDS_BALANCE_DUE | 402 |` table row.

## Step 9: Complete PRD — 2026-09-04T01:05:44.786Z

**Orchestrator note on method.** Step 9 was deliberately run as **three sequential file-partitioned passes** over a single shared `workspace/PRD_COMPLETED.md`, rather than as one monolithic scan. A single-agent full-impl scan reliably degenerates into a byte-identical copy of its input (the agent runs out of working memory before it reaches the later modules and declares the PRD complete). Partitioning by implementation module bounds each agent's reading load and makes the "found zero gaps" verdict falsifiable per partition. Passes ran strictly one after another because they all edit the same file. Partition map:
- Pass 1 — `app.py`, `common.py`, `guards.py`, `routes_catalog.py`, `start.sh`, `requirements.txt` (created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`).
- Pass 2 — `calc.py`, `routes_service.py`.
- Pass 3 — `routes_reservation.py`, `routes_money.py`.

### Final file state
- Source `PRD_FINALIZED.md`: 639 lines / 125,345 chars. Output `PRD_COMPLETED.md`: 639 lines / **148,863 chars (+23,518)**. Line count is unchanged because every edit across all three passes was an in-paragraph insert or substitution — no new sections, no new paragraphs beyond pass 1's single §2.4 insert.
- 73 distinct lines differ from `PRD_FINALIZED.md`. Ends at the complete final `| ERR_GOODWILL_EXCEEDS_BALANCE_DUE | 402 |` row of §5.
- **Totals across the three passes: 76 edits — 54 ambiguity-pins, 18 mismatch-revisions** (pass 1: 13 + 1; pass 2: 19 + 11; pass 3: 22 + 6).

---

### PASS 1 (app/common/guards/routes_catalog) — 13 ambiguity-pins, 1 mismatch

- §2.1 — revise — ambiguity — whitespace-only `X-User-ID`/`X-User-Role` count as empty; body is not read before the header check — `guards.py:44`, `guards.py:53`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alnum chars; `api_request_timestamp` (like `created_at`/`updated_at`) reads the host clock, not the logical clock — `common.py:124`, `common.py:306`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` -> `ERR_INVALID_PAGINATION` (not `ERR_VALIDATION`); empty-string param = omitted; surrounding whitespace tolerated — `guards.py:207-221`
- §2.3 — insert — ambiguity — `created_at` ties (ms-precision) broken by server write sequence, earliest first — `common.py:243`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` stamped from the host wall clock, unaffected by clock-setting; rows of one request share a stamp — `common.py:217`, `common.py:276`
- §2.4 — insert — ambiguity — a no-op re-derivation bumps neither `updated_at` nor `version`; a multi-field change bumps `version` by exactly 1 total — `common.py:275-281`
- §2.4 — insert — ambiguity — client instants accept any fractional precision, `Z` or explicit offset (converted to UTC), zone-less read as UTC — `common.py:140-150`
- §2.11 rung 4 — revise — **mismatch** — ownership precedes existence only for path-`Restaurant`/`Guest` ids and body `restaurant_id`/`guest_id`; row-derived ownership is preceded by resolution, so a bad id yields the rung-5 404 — `routes_catalog.py:74` vs `:156-157` (checked all 40+ handlers for consistency)
- §2.11 rung 7 — insert — ambiguity — JSON parse-level rejection fires right after rung 3 (before ownership/existence/FKs); JSON read only with a JSON content type; absent/empty body = `{}`; GET/DELETE bodies ignored — `guards.py:26-37`, `:53`
- §3.1 — insert — ambiguity — all five uniqueness rules are exact case-sensitive comparisons, tested after all shape checks, rejecting with `ERR_VALIDATION` — `routes_catalog.py:20-26,53,142,185,224,252`
- §3.1 — revise — ambiguity — `offer_ttl_minutes` upper bound 1440; `offer_ttl > hold_ttl` and the two seat/party-band orderings all reject with `ERR_VALIDATION` — `routes_catalog.py:40-43,138,182`
- §3.1 — revise — ambiguity — `deposit_bp` is still range-checked and persisted (default 3000) when `prepayment_mode` is `FULL` — `routes_catalog.py:173`
- §4 preamble — insert — ambiguity — filter matching is exact/case-sensitive, empty filter = absent, null field never matches, boolean filters accept `true/false/1/0` any case and match nothing otherwise — `guards.py:225-236,239-255`
- §4 preamble — insert — ambiguity — undefined path or method -> `ERR_VALIDATION` 400 (not 404/405); trailing slash tolerated; any pre-handler framework rejection also surfaces as `ERR_VALIDATION` 400 — `app.py:21,31-41`
- §4 table — revise x3 — ambiguity — undocumented filters added: `/restaurants` (`name`), `/restaurants/{id}/services` (`status`), `/guests` (`email`, `is_broker_flagged`, `refund_scrutiny_flag`) — `routes_catalog.py:82,122,277-281`

Pass 1 confirmed already-pinned: all 79 `ERROR_STATUS` entries match §5 code-for-code and status-for-status and the `NOT_FOUND` table matches §2.9's 14 codes; the whole envelope contract (`response_type`, empty `data`, 201-vs-200, error `meta`, `has_more`, pre-window `total_count`, 3-digit-`Z` rendering); `rhu`/`bp_of`/`floor_div` rounding (§2.5); clock default `2026-08-01T00:00:00Z` and which fields read it; bare-UUID ids and never-serialized `_`-prefixed internals; the five role names, `ERR_UNAUTHORIZED` semantics, and every §4 authorized-role list against its handler; every default and range for the 13 restaurant knobs, table, package, add-on and guest fields in §3.1; the four `/restaurants/{id}/...` reverse indexes.

---

### PASS 2 (calc.py + routes_service.py) — 19 ambiguity-pins, 11 mismatches

- §2.6 — revise — ambiguity — class re-derivation is one ordered pass: `seats_available`, `sell_through_bp`, both published prices, then the ladder status — `calc.py:150-159`
- §2.6 — insert — ambiguity — the class's published price pair sees the counters *after* the move; the reservation's locked price was taken before it — `calc.py:157-158,429-445`
- §2.6 — revise — **mismatch** — service `forfeited_cents` nets `FORFEITURE_REVERSAL`, `net_settled` excludes forfeiture, and a reconciliation bumps `version`/`updated_at` only when a figure actually moves — `calc.py:282-304`
- §2.7 — revise — **mismatch** — the `TRANSFER_OUT` row enters none of the four derived figures — `calc.py:206-224`
- §2.7 — revise — ambiguity — fixed three-step pass: roll-up, then charge breakdown, then payment status against the freshly written totals — `calc.py:257-264`
- §2.11 rung 14 — revise — **mismatch** — the sweep needs `PUBLISHED` whether or not it closes; re-tier and pause consult service status on no rung — `routes_service.py:218-220,116-129,352-360`
- §2.11 rung 55 — insert — **mismatch** — capacity is tested before publication's `seating_start_utc` test, which shares rung 14's code — `routes_service.py:101-107`
- §2.11 rung 59 — revise — **mismatch** — a short pool errors on create but filters candidates *silently* inside promotion — `calc.py:503-504`
- §3.1 — revise — ambiguity — `seating_end_utc` must fall strictly after the start (`ERR_VALIDATION`) — `routes_service.py:31-33`
- §3.1 — revise — ambiguity — class band is range-checked 1-20 (`ERR_VALIDATION`) before containment, whose three failures are `ERR_PARTY_SIZE_OUT_OF_BAND` — `routes_service.py:285-300`
- §3.1 — insert — ambiguity — the four publication checks run in written order; three share `ERR_SERVICE_INVALID_STATE`, capacity wins over a past start — `routes_service.py:94-107`
- §3.1 — revise — ambiguity — `demand_tier` is required and re-tiering is ungated on service status (DRAFT/CLOSED/CANCELLED re-price) — `routes_service.py:116-129`
- §3.1 — revise — **mismatch** — service-cancel `reason_code` is checked then dropped, not recorded — `routes_service.py:136`
- §3.3 — insert — **mismatch** — under `FULL` the deposit identity is re-asserted whatever `deposit_frozen` reads, so a later add-on drops a `FULLY_PAID` reservation to `UNPAID` — `calc.py:197-201,227-238`
- §3.7 step 2 — revise — **mismatch** — on a service cancellation the refund nets already-recorded `refunded_cents`, floored at zero — `calc.py:380-384`
- §3.7 step 3 — revise — ambiguity — the difference is taken as whole seconds (sub-second discarded toward zero) then divided by 3600 — `calc.py:354-357`
- §3.7 step 4 — insert — ambiguity — a negative figure meets no ladder row; the band stays at its initial 10000 bp — `calc.py:388-393`
- §3.7 — revise — **mismatch** — `FORFEITURE` is written first and `REFUND` second, and no zero-magnitude row is ever written, so an unpaid unwind stays `UNPAID` rather than reading `REFUNDED` — `calc.py:403-411`
- §3.7 — revise — **mismatch** — the sweep itself requires a `PUBLISHED` service (`close_service` defaults false) — `routes_service.py:216-220`
- §3.7 — revise — ambiguity — the `seating_end_utc` test precedes the sweep, the still-`PENDING` test follows it, so a refused close leaves the sweep committed without `version` bumps — `routes_service.py:221-223,253-262`
- §3.7 — revise — **mismatch** — `reason_code` persisted nowhere and no promotion fires anywhere in the service-level unwind — `routes_service.py:136,142-166`
- §3.7 — revise — ambiguity — `lifetime_refunded_cents` is global but the threshold is the refunding restaurant's — `calc.py:337-341`
- §3.8 — insert — ambiguity — a guest-counter rescore reaches only `WAITING`/`OFFERED` entries; terminal entries keep a historical score — `calc.py:327-330`
- §3.8 — revise — ambiguity — the release pass also skips a class already `RELEASED` and one whose arithmetic yields zero — `routes_service.py:186-197`
- §3.8 — revise — ambiguity — the promotion pass walks every class, including ones carrying released seats from an earlier run; `PAUSED`/`CLOSED` promote nobody — `routes_service.py:199-204`, `calc.py:512-513`
- §3.8 — revise — ambiguity — the minted hold takes the entry's `party_size` and the guest's `display_name`, with `hold_ttl` TTL and a §3.3 breakdown — `calc.py:429-457,521-522`
- §3.10 — insert — ambiguity — pausing consults only the class's status, so a `DRAFT` service's class may be paused (yet not resumed until `PUBLISHED`) — `routes_service.py:352-360`
- §4 preamble — insert — ambiguity — a bare collection path applies no ownership narrowing; a nested list applies it to its parent — `routes_service.py:77-87`, `guards.py:239-255`
- §4 table — revise — ambiguity — `GET /services` filters `restaurant_id`, `status`, `service_date`, `demand_tier` — `routes_service.py:81-86`
- §4 table — revise — ambiguity — `GET /ticket-classes` also filters `status` — `routes_service.py:335-339`

Pass 2 confirmed already-pinned: the whole pricing chain (DOW/tier bp, `rhu` on the combined factor, floor-8500-then-cap-18000 order, scarcity thresholds 8000/5000 -> 1500/800/0, release discount on the scarcity-adjusted figure, floored `sell_through_bp`); the PAUSED>CLOSED>RELEASED>OPEN>SOLD_OUT ladder and its stickiness; charge breakdown (per-line rounding, add-on-name-then-`created_at` line order, `grand_total`, floored `balance_due`, `DEPOSIT` freeze); the ledger's eight kinds/nine memo codes/four roll-ups/six-rule status precedence; both forfeiture ladders row-for-row with at-or-above edges, rebooking bands 0/500/1500/3000 on the raw forfeiture, the `min(paid, raw+fee)` cap, both worked examples, `NO_SHOW_FULL`; prep-load severity minutes 0/6/15; the waitlist score with the completed-count cap at 8, both ranking policies with `created_at`-then-`email` tie-breaks, `return_seats` pool routing, `promote_after_restore` only on `SOLD_OUT -> OPEN`; service/class create defaults and ranges, `day_of_week` derivation, release-window inclusivity, run counters, resume's `PUBLISHED` gate, `CLOSED` cascades, `price-quote`'s role list.

---

### PASS 3 (routes_reservation.py + routes_money.py) — 22 ambiguity-pins, 6 mismatches

- §2.1 — insert — ambiguity — ownership comparison scope pinned for every row hanging off a reservation or service (add-on line, dietary note, ledger row, refund exception, waitlist entry) vs a credit's own stored `restaurant_id` — `routes_money.py:21-24,64,134-135,251`
- §2.11 rung 15 — revise — **mismatch** — "PAUSED and CLOSED always failing" was false for confirmation, whose weaker variant refuses only `CLOSED` and sits after rungs 17/18/19 — `routes_reservation.py:190`
- §3.3 — insert x2 — ambiguity — `party_size` has no upper shape bound (oversized party -> `ERR_PARTY_SIZE_OUT_OF_BAND`, not `ERR_VALIDATION`); rung-4 ownership reaches `guest_id` only when it arrived as a non-empty string — `routes_reservation.py:64-66,76`
- §3.3 — insert — ambiguity — add-on append is gated on `PENDING`/`CONFIRMED`/`SEATED` — `routes_reservation.py:215`
- §3.3 — insert x2 — ambiguity — payment answers 201 while returning the reservation; "first payment" means `amount_paid_cents == 0`, so a prior goodwill redemption lifts the deposit floor — `routes_reservation.py:141-167`
- §3.4 — insert x2 — ambiguity — note capture state gate; `guest_index` range test after shape and after the state check — `routes_reservation.py:273-281`
- §3.4 — revise — ambiguity — ack test order, `ACCEPT`-arm-only gates, no `version`/`updated_at` bump when acceptance changes nothing else, no kitchen-capacity re-test — `routes_reservation.py:307-337`
- §3.4 — insert — ambiguity — amend's three fields are optional and independent; omitted leaves unchanged; `note_text` may go to empty — `routes_reservation.py:346-362`
- §3.5 — insert — ambiguity — re-assignment while `CONFIRMED` overwrites both fields and self-excludes from both conflict tests — `routes_reservation.py:394-396,420`
- §3.5 — revise — ambiguity — missing table/seat instant -> `ERR_RESERVATION_INVALID_STATE`, after the state check and before the safety gates — `routes_reservation.py:449`
- §3.5 — insert — ambiguity — a `CONFIRMED` reservation with null `seat_from_utc` draws `ERR_NO_SHOW_TOO_EARLY` — `routes_reservation.py:498`
- §3.6 — insert — ambiguity — name-change payload bounds and `PENDING`/`CONFIRMED` gate — `routes_reservation.py:564-566`
- §3.6 — insert — ambiguity — `recipient_guest_name` non-empty <=120, null defaults to `display_name` — `routes_reservation.py:595,632`
- §3.6 — insert x3 — ambiguity — successor's full field set incl. `version` starting at 1; `TRANSFER_IN` lifts the service's `gross_charged_cents` asymmetrically; copied notes keep `amend_count`; transfer rows written only when `amount_paid_cents > 0` — `routes_reservation.py:625-689`
- §3.7 — revise — **mismatch** — the `PENDING -> CANCELLED` branch also re-evaluates the ladder and promotes on `SOLD_OUT -> OPEN`; only an `OFFERED` linked entry is withdrawn; a `CONFIRMED` reservation with null `seat_from_utc` is not gated by the cancel window — `routes_reservation.py:534,546-553,48-53`
- §3.8 — insert — ambiguity — waitlist join compares the raw `guest_id` first, so absent/empty/non-string -> `ERR_FORBIDDEN_RESOURCE_OWNER` — `routes_money.py:85`
- §3.8 — revise — **mismatch** — `OFFERED -> WITHDRAWN` cancels the offered reservation only while still `PENDING`, re-derives the ladder but promotes nobody, runs no settlement and writes no ledger row, and leaves the entry's offer fields as they stood — `routes_money.py:206-216`
- §3.9 — revise — **mismatch** — filing is not gated on the reservation's state at all — `routes_money.py:221-245`
- §3.9 — insert x2 — ambiguity — the issue ceiling is per-issuance with no per-exception aggregate, so one exception can yield two full-shortfall credits; `expires_at_utc <= clock` is `ERR_VALIDATION` at the shape rung, ahead of SOD and the status check — `routes_money.py:320,332`
- §3.9 — insert x2 — ambiguity — `amount_cents` >= 1 is a shape error; the target's `fulfillment_status` is never consulted at any rung — `routes_money.py:377,369-410`
- §3.9 — revise — **mismatch** — revoke's `reason_code` is shape-checked non-empty and then discarded, never persisted — `routes_money.py:416`
- §4 `/reservations` — revise — ambiguity — added `fulfillment_status`, `payment_status` filters — `routes_reservation.py:117-125`
- §4 `/reservations/{id}/dietary-notes` — revise — ambiguity — added `ack_status` filter — `routes_reservation.py:134-136`
- §4 `/payment-transactions` — revise — ambiguity — added `kind`, `memo_code` filters — `routes_money.py:71-76`
- §4 `/waitlist-entries` — revise — ambiguity — added `status` filter — `routes_money.py:142-148`
- §4 `/refund-exceptions` POST — revise — **mismatch** — dropped "against a settled reservation" — `routes_money.py:221`
- §4 `/refund-exceptions` GET — revise — ambiguity — added `status`, `reason_code` filters — `routes_money.py:258-262`
- §4 `/goodwill-credits` — revise — ambiguity — added `status` filter — `routes_money.py:361-366`

Pass 3 confirmed already-pinned: every endpoint's role list against its `auth(...)` call (incl. `MONEY_READERS` excluding `KitchenLead` and `PlatformAdmin`-only on the clock); reservation hold/seat/complete/no-show/cancel field writes and cascades, `hold_expires_at_utc` clearing on confirm, `deposit_frozen`, `seat_to_utc` pinning, the `completed_reservations_count` / `no_show_strikes` cascades into waitlist rescoring; all three OCC codes at rungs 10-12; add-on line locked price, `ack_required` copy, aggregate qty ceiling, cutoff arithmetic; the severity->minutes table, three-term `prep_minutes_total`, both safety gates on assign *and* seat, closed prep-window vs half-open turn-interval semantics; `sync_credit`'s four figures and status precedence, invariant I3, both decide arms' ledger rows and memo codes, the `FORFEITED -> PARTIALLY_REFUNDED -> REFUNDED` compensating transitions, revoke writing no ledger row, all eight 402-class fiscal rungs; the claim rung inversion Step 8 documented.

Pass 3 noted but deliberately did not paper over: an absent `reservation_id` on `POST /refund-exceptions` makes `own_reservation(ctx, None)` raise `TypeError`, which `app.py`'s catch-all converts to `ERR_VALIDATION` 400 — byte-identical to the shape error a PRD reader already predicts, so there is no PRD consequence and no impl edit was made (Step 9 is a documentation step and must not touch `implementation/`).

---

**Orchestrator independent verification:** `PRD_COMPLETED.md` is 639 lines / 148,863 chars against `PRD_FINALIZED.md`'s 639 / 125,345 — **not** byte-identical (73 lines differ), so the scan demonstrably ran in all three passes. The file still ends on the complete final `| ERR_GOODWILL_EXCEEDS_BALANCE_DUE | 402 |` row of §5. All 8 `workspace/implementation/results.{1..8}.json` from the clean Step 7 sweep are still in place; Step 9 touched only `PRD_COMPLETED.md` and no code, so the 278/278 result stands.

**PIPELINE COMPLETE.** Steps 1-9 all finished; `workspace/PRD_COMPLETED.md` written.

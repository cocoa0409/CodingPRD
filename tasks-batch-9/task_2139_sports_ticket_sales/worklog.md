# Worklog — task_2139_sports_ticket_sales

## Step 1: Create task directory — 2026-08-22T15:42:00.801Z

Created `tasks/task_2139_sports_ticket_sales/` and `tasks/task_2139_sports_ticket_sales/workspace/`. Index 2139 chosen (highest existing was 2138).

## Step 3: Copy shared files — 2026-08-22T15:42:22.896Z

Copied `./INSTRUCTION.md` → `tasks/task_2139_sports_ticket_sales/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate scaffold — 2026-08-22T16:34:04.234Z

All three scaffold artifacts are written, YAML-valid, and lint-clean.

## Files

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2401 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1447 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3780 |

## Scaffold shape (§1.0–§1.7)

- **Profile**: quota/allocation × pricing engine; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy; topology **flat**; shape **parallel** (+ cyclic/branching machines); role model **segregation_of_duties**; consistency **immediate**. `api_prefix: /ticketing`.
- **10 entities**: Season, Game, Seat, SeasonPlan, ServiceRep, TicketAccount, PlanOrder, SeatHold, HospitalityPackage, TicketTransfer (self-referential `SeasonPlan.base_plan_id`).
- **9 state machines** (one per state field): Season, Game, PlanOrder x 2 (order_status x payment_status), TicketAccount x 2 (billing_status x service_status), SeatHold, HospitalityPackage, TicketTransfer. **2 concurrency rules** (OCC on `Seat.version` for hold create, on `PlanOrder.version` for relocate).
- **10 calculations**, **33 validations** (priority 10->109), **45 endpoints** (44 business + `POST /_clock/set_current_utc`, default clock `2026-08-01T00:00:00Z`), **46 errors**, **4 roles** (TicketOpsAdmin/RevenueManager opaque, SalesRep->ServiceRep, AccountHolder->TicketAccount).

## §1.8 — 18 instances (2 per rule)

`dual_variant_calc` (order QUOTED-vs-FINAL 26644/6360; account churn ROLLING-vs-CAMPAIGN 16/28) · `combinatorial_formula` (mode b: per-line rounding 38430 vs 38429; mode c: hospitality tier off gross 510300 vs 484785) · `non_linear_state_machine` (PlanOrder parallel dims; TicketAccount ACTIVE<->AT_RISK cycle) · `transitive_cascade` (renewal-deadline 4-link cascade; confirm->package->revenue->pricing-mode) · `priority_pair_validation_conflict` (safety 85 beats fiscal 107; state 66 beats temporal 90) · `boundary_precision_check` (volume tier at 4 seats 9540/12338; empty-set no_show_rate 0.00) · `cross_entity_state_dependency` (Order->Season; Transfer->Order payment dim) · `resource_temporal_overlap` (Seat half-open, adjacency OK; suite closed + 30-min buffer, adjacency rejected) · `compensating_invariant` (seat census; contracted-revenue ledger).

## §1.9 — 70 instances (64 with recipes, 6 stubs)

entities 9 · state_machines 9 · calculations 8 · validations 14 · endpoints 4 · errors 17 (6 `excluded_because` stubs pointing at §1.8) · rbac 4 · cross_cutting_layers 3 · consistency_model 2.

## Verification

```
Coverage
  §1.5 endpoints declared:    45
  §1.1 entities declared:     10
  §1.8 instances scanned:     18
  §1.9 instances scanned:     64
  Calls scanned (§1.8+§1.9):  861

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional self-checks: 0 unbound `${var}` across both design files, 88 unique instance names (no duplicates), all 285 `grounds` refs resolve, all 46 error ids appear in both the rule tables and the design files, all 6 stub `difficulty_instance` names exist, every entity field has type/source/description, every transition has preconditions + side effects, every endpoint role is declared, both OCC endpoints take `expected_*_version` as required input and bump the parent version, and no forbidden concurrency vocabulary appears anywhere. All formula-derived assert literals were computed with a Python replay of the declared formulas/constants. No sibling task directories were read.

## Step 4: Generate PRD — 2026-08-22T16:44:17.123Z

PRD generated and audited.

**Output:** `workspace/PRD.md` — 471 lines, 86.3 KB.

The two withheld design indices (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Section list

- **§1 Introduction** (3 paragraphs)
- **§2 Global Specifications** — 11 subsections: 2.1 Roles/Identity/RBAC · 2.2 API Response Structure (fixed block, verified byte-identical) · 2.3 Pagination, Ordering and List Filters · 2.4 Resource Identity, Timestamps, Version · 2.5 The Logical Clock · 2.6 Money, Rounding and Precision · 2.7 Seat Occupancy and the Inventory Census · 2.8 Stale-Version Guards (OCC) · 2.9 Validation Order and Failure Precedence (33-rung ladder) · 2.10 Season Revenue Ledger and Pricing Regime · 2.11 Ops Checkpoint and Phase Order (P1-P10)
- **§3 Business Logic** — 11 subsections: 3.1 Building a Season · 3.2 Accounts, Rep Assignment, Service Cadence · 3.3 Renewal Priority, Seat Holds, Geometry · 3.4 Pricing a Seat-Game Line and Building an Order · 3.5 Submission, Discount Review, Revision Cycle · 3.6 Confirmation, Revenue Cascade, Installment Billing · 3.7 Payments, Delinquency, Account Ageing · 3.8 Relocations, Upgrades, Cancellation Compensation · 3.9 Hospitality Suites and Their Calendar · 3.10 Secondary Market · 3.11 Game Day, Attendance Analytics, Churn Scoring, Season Advance
- **§4 Endpoint Definitions** (4-column table)
- **§5 Error Code Catalogue** (2-column table)

## Coverage audit (scaffold vs PRD)

| Category | Scaffold | Covered | Missing |
|---|---|---|---|
| Entities | 10 | 10 | 0 |
| `entities[].fields[].name` | 108 | 108 | 0 |
| `endpoints[].input` (request bodies) | 60 | 60 | 0 |
| `endpoints[].input` (GET query params) | 27 | 27 | 0 |
| Endpoint structured-output keys (run-ops summary, renewal-quote, clock) | 18 | 18 | 0 |
| State machines | 9 | 9 | 0 |
| State-machine transitions | 46 | 46 | 0 |
| Enum + state enumeration values | 63 | 63 | 0 |
| Calculations | 10 | 10 | 0 |
| Validations | 33 | 33 | 0 |
| `concurrency_rules[]` OCC | 2 | 2 | 0 |
| Endpoints (method+path exact match) | 45 | 45 | 0 |
| Errors | 46 | 46 | 0 |
| Roles | 4 | 4 | 0 |

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 108 required, 108 present, 0 missing
- endpoints[].request_body: 60 required, 60 present, 0 missing
- endpoints[].query_params: 27 required, 27 present, 0 missing
- endpoints[] structured output keys: 18 required, 18 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 33 checked, 33 expressed in prose (§2.9 ordered ladder, rungs 1-33), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_seat_version / expected_order_version + ERR_STALE_SEAT_VERSION / ERR_STALE_ORDER_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 46 checked, 46 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed (all constants embedded in business prose; no operator syntax; no fuzzy words), 0 missing
- validations[] conditions: 33 checked, 33 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 45 checked, 45 expressed, 0 missing
- entities[].fields[] structured content: 108 checked, 108 reconstructible from prose, 0 missing
- sibling-branch symmetry: 5 groups checked (submit zero-discount vs discounted; review APPROVE vs REVISE; transfer APPROVE vs REJECT; relocation upgrade/downgrade/lateral; hospitality HELD->CONFIRMED vs HELD->RELEASED), 5 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 883
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Notes on one scaffold inconsistency resolved

The scaffold disagrees with itself on `transfer_count_season` at APPROVE time: the `TicketTransfer` state machine says the counter is **left unchanged** on APPROVE ("the `REQUESTED` row already counted toward the seasonal cap"), while `endpoints[].side_effects` for the decision endpoint says `+= 1`. The PRD follows the state machine, because validation priority 98 independently defines the counter as tracking `REQUESTED | APPROVED | COMPLETED` rows with a REJECT giving the slot back — a 2-against-1 consistency majority. Under the endpoint's wording the counter would double-count every approved transfer and break the cap semantics. Worth flagging to the test generator so the assertion matches (`transfer_count_season` stays at 1 after request->approve, and returns to 0 after request->reject).

## Step 6: Generate implementation — 2026-08-22T17:02:47.293Z

Implementation complete and verified.

## Files written (`workspace/implementation/`, 2841 lines total)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 8 | `exec python3 app.py`, guarded `pip install`, reads `$PORT`, binds `0.0.0.0` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 59 | Flask factory, blueprint registration, `ApiError`/`HTTPException` handlers |
| `core.py` | 506 | In-memory `Store` (10 dicts), logical clock, ISO-3-digit timestamps, `Decimal` half-up money helpers, response envelope (`meta`/`response_type`/`data`), auth decorator, schema helpers, pagination, all 10 `find_*` existence lookups |
| `calc.py` | 453 | All 10 calculations + constants: line price, order total (QUOTED/FINAL), hospitality fee, relocation delta, churn ROLLING/CAMPAIGN, occupancy census, attendance/no-show, installment schedule + waterfall, rep selection, resale floor/credit, ledger goal check |
| `routes_setup.py` | 325 | Seasons, games, seats, plans, reps, `/_clock/set_current_utc`; season-status gate helpers |
| `routes_accounts.py` | 143 | Accounts, assign-rep, touchpoints, renewal-quote; ownership + account-status gates |
| `routes_holds.py` | 134 | Seat holds (create with OCC + interval geometry, release, reads) |
| `routes_orders.py` | 530 | Plan orders: create, submit, review, confirm (full 3-link cascade), cancel, relocate, payments |
| `routes_market.py` | 288 | Hospitality packages, ticket transfers, gate scans |
| `ops.py` | 394 | Ops checkpoint P1-P10 including renewal-close and archive cascades, write-off cascade |

**45 endpoints** implemented (46 routes counting Flask's `/static`), matching the PRD §4 table exactly.

## Key decisions
- Storage is pure in-memory dicts; no seeding, no disk I/O (verified by grep — zero `open(`/sqlite/json.dump hits).
- Validation ladder implemented as an explicit per-endpoint ordered sequence mirroring PRD §2.9 rungs 1-33, including the FK-check ordering from rung 5 (`season_id -> game_id -> seat_id -> seat_ids[] -> new_seat_ids[] -> plan_id -> base_plan_id -> account_id -> order_id -> to_account_id`).
- Scaffold self-inconsistency resolved per PRD: transfer APPROVE leaves `transfer_count_season` unchanged (stays 1); REJECT decrements it back to 0. Verified in smoke test.
- Seat occupancy is computed fresh for *validation* but only persisted (stored `seat_status` + 4 season counters) on successful mutations, honoring "stored, not derived on read".
- Ambiguities resolved toward PRD prose: nonexistent/wrong-season `game_ids` on plan construction -> `ERR_PLAN_GAMES_NOT_SUBSET` (rung 5 does not list `game_ids`); open-renewal past the deadline -> `ERR_RENEWAL_DEADLINE_PASSED` after the setup-completeness rung; cancel of a CONFIRMED order in an ARCHIVED season -> `ERR_SEASON_STATE_INVALID`. Cancel-from-CONFIRMED also releases holds converted by that order (whose `origin_order_id` is null), without mutating `origin_order_id`.

## Boot smoke test
Launched via `PORT=18139 bash start.sh`; booted in <3s and served traffic. Three scripted end-to-end suites ran green (~70 assertions):
- Envelope/meta shape, pagination (`limit`/`offset`/`total_count`/`has_more`), 401/403/404/400 precedence.
- Pricing verified against hand-computed cents: quoted total 84172, installment split `[28058, 28057, 28057]` with 30-day due dates, suite total 318600, face/floor 12000/7200, resale credit 8500, upgrade relocation delta 29162 under the post-flip BALANCED regime.
- State machines: zero-discount fork -> APPROVED, discount fork -> PENDING_APPROVAL, SOD 403, REVISE clearing `submitted_by_user_id`, confirm cascade (holds CONVERTED, seats ASSIGNED, ledger, hospitality HELD->CONFIRMED, revenue-goal flip to BALANCED), cancel compensation (ledger->0, census restored, holds RELEASED/ORDER_CANCELLED, loyalty credited), OCC 412 both flavors, delinquency-beats-stale precedence, cure PAST_DUE->CURRENT, renewal-close cascade (holds EXPIRED/RENEWAL_WINDOW_CLOSED -> flag flip -> AT_RISK), churn declaration, win-back, archive cascade (plans CLOSED, packages SETTLED, transfers COMPLETED), write-off cascade.

Server was stopped after testing; no processes or artifacts left behind.

## Step 5: Generate unit tests — 2026-08-22T17:08:19.603Z

Test infrastructure and suite generated and verified.

## Files written

**`test_helpers/`** (1,708 lines)
| File | Lines |
|---|---|
| `__init__.py` | 35 |
| `types.py` | 339 |
| `api_client.py` | 204 (one method per PRD §4 endpoint, incl. `/_clock/set_current_utc`) |
| `api_errors.py` | 106 (46 error ids + status map registered with the framework) |
| `assertions.py` | 190 (per-entity assertions, census invariant, instalment-schedule invariant, ops-summary shape) |
| `factories.py` | 127 |
| `constants.py` | 82 |
| `test_users.py` | 44 (opaque headers for the two operator roles; `make_sales_rep_headers` / `make_account_holder_headers` builders for the two `entity_backed` roles) |
| `fixtures.py` | 581 (5 tiers: creation -> holds/orders/packages/transfers -> `setup_selling_world` -> price-tuned worlds -> delinquency/write-off/resale worlds) |

**`test_suite/`** (3,029 lines, 11 files + conftest): `test_01_season_setup_and_inventory` (12), `test_02_accounts_reps_and_service_cadence` (6), `test_03_seat_holds_and_occupancy` (11), `test_04_order_pricing_and_creation` (15), `test_05_order_workflow_and_review` (7), `test_06_confirmation_revenue_and_installments` (7), `test_07_payments_delinquency_and_ageing` (7), `test_08_relocation_and_hospitality` (8), `test_09_secondary_market_transfers` (8), `test_10_gameday_analytics_and_ops_checkpoint` (11), `test_11_access_control_and_error_catalogue` (8).

## Coverage

- **Total: 100 tests**, all collected by pytest, no skip/xfail markers.
- **Queue A (§1.8 difficulty): 18/18 instances translated, 0 skipped** — exactly 2 tests each (36 tests).
- **Queue B (§1.9 corner): 64/64 non-stub instances translated, 0 skipped** — 1 test each (64 tests). All 6 `excluded_because:` stubs verified to point at real difficulty instances; none emitted.
- Every docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, machine-checked to resolve to a real instance in the right rule/section.
- Every docstring citation was machine-checked to survive a whitespace-normalised literal grep of `PRD.md`.

## Key adjudication notes

1. **`transfer_count_season` inconsistency** — tests assert the PRD/state-machine reading: `test_approved_resale_grants_the_eighty_five_percent_seller_credit` asserts the counter stays at **1** after request->approve; `test_rejected_transfer_grants_no_credit_and_returns_the_cap_slot` asserts it returns to **0** after request->reject. The endpoint `side_effects` `+= 1` reading is never asserted.

2. **One setup adjustment for PRD fidelity** (difficulty `non_linear_state_machine / ticket_account_service_status_cycles_active_at_risk_active`): the design's recipe leaves the account holding a CONFIRMED order and still expects `ACTIVE -> AT_RISK` on the 14-day cadence. PRD §3.2 conjoins the cadence rule with *"and which holds no confirmed order in this season"*, so that outcome is not PRD-derivable as written. Rather than skip the instance, both its tests confirm the order (to reach `ACTIVE`) and then **cancel** it, so the account is `ACTIVE` with zero confirmed orders — the transition then follows uniquely from PRD. The asserted rules (cadence move, `at_risk_since_utc` stamp, `COMMITTED` -> `ACTIVE`, `at_risk_since_utc` cleared, rep `touchpoints_logged_count`) are unchanged.

3. **Two design assertions deliberately not asserted** (PRD-ambiguous, silence pattern `computed-field`/`branch-asymmetry`): in the renewal-deadline cascade instance, `expired_hold_count` and `at_risk_account_count` from the run-ops summary — PRD attributes those counters to phases P2/P9 while the rows in that scenario change inside the P8 cascade, so two PRD-only readers could count differently. Every other assertion of that instance is tested. Both its tests still pass the >=2 requirement.

## Step 7: Run tests and iterate — 2026-08-22T17:20:38.938Z

All 8 parallel rounds pass 100/100.

## Summary

**Iterations run:** 2 (sweep -> fix -> sweep).

**Iteration 1 union of failures (8 rounds x 100 tests):**
| Test | Rounds failed |
|---|---|
| `test_hold_create_with_the_current_seat_version_succeeds_and_bumps_it` | 8/8 (deterministic) |
| `test_partial_plan_derives_from_a_published_full_season_plan` | 1/8 (`RemoteDisconnected`) |
| `test_order_creation_mints_order_holds_and_leaves_the_order_in_draft` | 1/8 (`ConnectionResetError`) |

**Tests deleted:** none. Both PRD coverage (STEP 1a) and unique derivability (STEP 1b) held for every failing test.

**Fixes applied to `test_suite/`:**
- `test_suite/test_03_seat_holds_and_occupancy.py` -> `test_hold_create_with_the_current_seat_version_succeeds_and_bumps_it`: the test placed the second hold over the window `[2026-08-02, 2026-08-20)` while the logical clock sat at its boot default `2026-08-01T00:00:00Z`, then asserted `seat_status == "HELD"`. PRD §2.7 states verbatim that a seat is `HELD` only when an `ACTIVE` hold's `hold_window_start_utc` "is at or before the current instant and its `hold_window_end_utc` is strictly after it" — so a window opening *tomorrow* leaves the seat `AVAILABLE`, exactly what the implementation returned. This was a STEP 2 test-setup bug (precondition inconsistent with PRD), not an implementation bug; the fix moves `hold_window_start_utc` to `2026-08-01T00:00:00Z` so the window genuinely covers the current instant. No assertion was weakened — the `HELD` / `held_seat_count == 1` / `available_seat_count == 1` / `version + 1` checks all stand. A sibling test in the same file (`test_hold_window_touching_an_existing_end_instant_is_accepted`) independently confirms this PRD reading with the comment *"Neither window covers the current instant, so the seat is still free."*

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`:** none. No implementation defect was found.

**Key finding on the two flaky `ConnectionError` failures — harness artifact, not a product bug.** Traced through `/tmp/prd_bench_server_<port>.log`. Both failing tests died mid-request against a server whose log block ended in `Terminated` (SIGTERM), not the runner's normal `Killed` (SIGKILL from `_kill_port`). Cross-referencing all 8 rounds showed **every** round took SIGTERM at the *same two wall-clock instants* (`17:09:50` and `17:10:25`) across 8 distinct ports — a host-wide event no code path in the runner produces (`kill_port`, `_kill_port` and the plugin all use `kill -9`; `lifecycle.stop()`'s SIGTERM only fires at end-of-run). The instants line up with the completion of the agent's own foreground Bash calls, i.e. the agent harness reaping the background sweep's process group. Re-running the sweep under `setsid nohup` (own session, immune to that group signal) produced **zero** `Terminated` events and 8/8 clean rounds. Nothing in `implementation/` or `test_suite/` was changed for this; the fix is purely in how the sweep is launched. Anyone re-running this stability sweep from an agent shell should detach it with `setsid`, otherwise ~0.25% of tests will fail spuriously on connection errors.

## Step 8: Finalize PRD — 2026-08-22T17:22:04.911Z

**Result: zero edits warranted. `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`.**

- Line counts: PRD.md 470 / PRD_FINALIZED.md 470 — **0.0% delta** (md5 match: `91d7013177f2e0349b940038cfb37b56`).
- Changes: **none.**

Why nothing was pinned:

The `<step_7_diff>` contained exactly one substantive item — a fixture correction in `test_suite/test_03_seat_holds_and_occupancy.py::test_hold_create_with_the_current_seat_version_succeeds_and_bumps_it`. Verified against the implementation:

- `implementation/calc.py:152-162` (`effective_seat_status`) implements the three-way decision literally as PRD §2.7 states it: `assigned_account_id is not None` -> `ASSIGNED`; else any `ACTIVE` hold with `hold_window_start_utc <= instant < hold_window_end_utc` -> `HELD`; else `AVAILABLE`. The half-open `<=` / `<` comparison is character-for-character what §2.7 prescribes ("at or before the current instant and its `hold_window_end_utc` is strictly after it, a half-open interval").
- The old fixture opened the second hold's window at `2026-08-02` while the logical clock sat at its §2.10/§2.5 boot default `2026-08-01T00:00:00Z`, so the seat was correctly `AVAILABLE`. The corrected fixture now uses `2026-08-01T00:00:00Z`. This was a precondition inconsistent with prose PRD already states verbatim — a fixture bug, not a PRD silence and not an impl/PRD divergence.

Also checked while confirming there was no adjacent silence: `implementation/routes_holds.py:17-23` (`covering_hold`) and `routes_holds.py:60-77` (hold-create ladder) use the same half-open predicate and order the seat-freedom check (rung 12) ahead of the stale-version check (rung 16), matching §2.9 rung ordering and §2.8. `calc.py:169-186` (`run_census`) rewrites stored `seat_status` plus the four season counters, as §2.7 requires. Nothing in these paths is under-determined by the current prose.

The two other iteration-1 failures were harness artifacts (`RemoteDisconnected` / `ConnectionResetError` from process-group reaping), carry no product behavior, and therefore have no PRD implication.

Since there were no edits, the per-edit pre-edit search log is empty by construction; the NO-NEW-MISMATCH rule had nothing to constrain.

## Step 9: Complete PRD — 2026-08-22T17:30:38.937Z

`PRD_COMPLETED.md` is written. Walked all 11 implementation modules (2832 lines, 45 endpoints, 10 calculations, the 33-rung ladder, 9 state machines, 46 errors) against the PRD and applied 35 in-paragraph substitutions across 31 lines. No new sections, no new paragraphs, no line-count change.

**File stats**

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| lines | 470 | 470 |
| chars | 86,573 | 90,977 (+4,404) |

**Counts:** 7 mismatch-revisions, 28 ambiguity-pins.

**Mismatch revisions**

- §2.9 rung 6 — revise — mismatch — rep-ownership guards seven ops, adding order confirmation — `routes_orders.py:231`
- §2.9 rung 13 — revise — mismatch — transfer *decisions* also require game `SCHEDULED`; `REQUESTED` test precedes it — `routes_market.py:187-192`
- §2.9 rung 24 — revise — mismatch — `ERR_RENEWAL_DEADLINE_PASSED` also guards renewal opening, evaluated *after* rung 30 — `routes_setup.py:80-89`
- §2.11 P9 — revise — mismatch — campaign scoring covers every stored account, not "the season's accounts" — `ops.py:332-334`
- §3.8 (cancel from CONFIRMED) — revise — mismatch — also releases `CONVERTED` holds of the order's account on the order's seats regardless of `origin_order_id` — `routes_orders.py:342-350`
- §3.10 (seasonal cap) — revise — mismatch — `transfer_count_season` is a running non-`REJECTED` counter across all seasons, never reset — `routes_market.py:174, 221`
- §3.11 + §4 intro — revise — mismatch — gate-scan ingest returns HTTP 201 — `routes_market.py:288`

**Ambiguity pins**

- §2.1 — insert — blank `X-User-ID` is also `ERR_UNAUTHENTICATED` — `core.py:309`
- §2.2 — insert — `api_request_id` is `req_` + 20 uppercase-alnum chars — `core.py:208-209`
- §2.3 — insert — tie-break by `id`; seats by `section_code`/`row_label`/`seat_number` — `core.py:482`, `routes_setup.py:194`
- §2.11 P2 — insert — season-scoped holds; `released_reason` left null on natural expiry — `ops.py:32-38, 66-73`
- §2.11 P6 — insert — orders scoped to the checkpoint's season — `ops.py:41-47, 159`
- §2.11 P7 — insert — spans all accounts; both ageing steps can fire in one pass off the same anchor — `ops.py:214-231`
- §2.11 counters — insert — `expired_hold_count` / `at_risk_account_count` aggregate across P2, P8 and P9 — `ops.py:247, 285, 265, 349`
- §3.1 — insert — duplicate season `code` -> `ERR_INVALID_REQUEST` 400 — `routes_setup.py:47-49`
- §3.1 — insert — seat mint answers 201 with `response_type` array and no pagination meta — `core.py:239-241`, `routes_setup.py:178`
- §3.1 — insert — reversed range / seat collision -> 400, nothing minted — `routes_setup.py:154-166`
- §3.2 — insert — rep selection final tie-break is lower `id` — `calc.py:438-442`
- §3.2 — insert — chosen rep's `version` also increments — `routes_accounts.py:85`
- §3.2 — insert — touchpoint bumps the rep row only when `X-User-ID` resolves to a stored rep — `routes_accounts.py:112-115`
- §3.3 — insert — renewal-open deadline error id + its position after the completeness tests — `routes_setup.py:88-89`
- §3.3 — insert — `RENEWAL_HOLD` always bumps the account; other hold types never touch it — `routes_holds.py:230-232`
- §3.3 — insert — release/expiry bump the account only when the flag actually changes — `routes_holds.py:252-256`, `ops.py:54-60`
- §3.4 — insert — negative `discount_pct` is `ERR_INVALID_REQUEST` — `routes_orders.py:108`
- §3.4 — insert — renewal quote takes all seats assigned to the account regardless of season, feeding the volume lookup — `routes_accounts.py:131-134`
- §3.4 — insert — `pricing_variant` is the literal `QUOTED` — `routes_accounts.py:141`
- §3.6 — revise — account `version` increments exactly once per confirmation regardless of status move — `routes_orders.py:293-301`
- §3.7 — insert — any `SalesRep` may pay (no rep-ownership rung); `amount_cents` >= 0 — `routes_orders.py:488-494`
- §3.7 — insert — account `version` bumps only when one of its own fields changed — `routes_orders.py:46-56, 528`
- §3.8 — insert — cancel of a confirmed order in an `ARCHIVED` season -> `ERR_SEASON_STATE_INVALID` 409 — `routes_orders.py:329-330`
- §3.8 — insert — relocation bumps the account only when the signed amount is non-zero — `routes_orders.py:473-476`
- §3.9 — insert — booking increments the game's `version` — `routes_market.py:89`
- §3.10 — insert — cross-branch field (`resale_price_cents` / `to_account_id`) -> `ERR_INVALID_REQUEST` 400 — `routes_market.py:126-131`
- §3.10 — insert — an approved `RESALE` leaves entitlement with the seller (admission credit and no-show) — `calc.py:232-242`

Two PRD warts deliberately left alone because they are internal, not impl-facing: §3.3's cross-reference to "§3.9" for the season cascades (they live in §3.11), and the impl's `ERR_INVALID_REQUEST` on unrouted paths/405s (no PRD-described endpoint covers it, and §5 maps that id to 400).

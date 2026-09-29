# Worklog — task_2159_grain_merchandising_basis_trading

## Step 1: Create task directory — 2026-08-27T04:46:37.000Z

Created `tasks/task_2159_grain_merchandising_basis_trading/` and `tasks/task_2159_grain_merchandising_basis_trading/workspace/`.

## Step 3: Copy shared files — 2026-08-27T04:47:10.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2159_grain_merchandising_basis_trading/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-08-27T05:34:20.000Z

All three scaffold artifacts are written and lint-clean.

## Files

- `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8), `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

## Lint verdict (pasted verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    54
  §1.1 entities declared:     12
  §1.8 instances scanned:     23
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  554

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Calibration (beyond Expert, as requested)

12 entities, 54 endpoints, 47 error codes, 10 calculations, 7 state machines, 2 OCC rules, 6 roles, 37 ordered validation rows. Profile: `ledger_reconciliation` + `compliance_audit`, `entity_topology: flat` (prioritized, 0% in examples), `state_machine_shape: parallel`, `role_model: segregation_of_duties` (prioritized), self-referential FK via contract roll.

## Difficulty design: 23 instances, 9 rules (>=2 each)

- **dual_variant_calc (2)** — delivery settlement SHRINK_FIRST vs GROSS_GRADE (DeliveryTicket/quality domain) vs cancellation damages MARKET_LOSS vs REPLACEMENT_COST (PurchaseContract/market domain).
- **combinatorial_formula (3)** — all three modes: (b) per-factor-then-sum rounding order (400.03 vs 400.02), (c) service-fee tier keyed on the *pre-fee* gross value (50040.00 -> 2.0c while post-fee 49800.00 would say 3.0c), (a) four-input non-linear margin call with per-commodity tiered rate and side branch.
- **non_linear_state_machine (3)** — parallel axes on PurchaseContract, ACTIVE<->SUSPENDED cycle on Bid, OPEN<->MARGIN_CALL cycle on HedgePosition.
- **transitive_cascade (2)** — two depth-4 chains from different triggers (ticket apply -> contract SETTLED -> hedge lift -> desk posture; mark-to-market -> MarginCall -> desk FROZEN -> contract pricing_locked).
- **priority_pair_validation_conflict (3)** — {state, fiscal}, {referential, constraint}, {temporal, fiscal}.
- **boundary_precision_check (3)** — moisture strictly-`>` 15.0 (grading endpoint), risk limit strictly-`>` ceiling (contract endpoint), empty-scope position report (coverage ratio 0, no divide-by-zero).
- **cross_entity_state_dependency (3)** — (Contract,Bid), (Ticket,FreightBooking), (PricingOrder,HedgePosition).
- **resource_temporal_overlap (2)** — RailFleet: exclusive, half-open, +48h turnaround buffer; ElevatorLocation: aggregate capacity over *closed* date intervals where touching endpoints collide.
- **compensating_invariant (2)** — bushels (`open_bushel_commitment` restored by ticket reverse) and futures lots (`committed_hedge_lots` restored by contract cancel).

## Corner design: 69 instances across 9 guide sections (55 with recipes + 14 `excluded_because` stubs)

## Verification done

Every formula-derived assertion literal was computed with a Decimal/ROUND_HALF_UP script against the §1.3 formulas (shrink 1.416 -> net 9858.40, discounts 1774.51 / 2550.00, settlements 38940.68 / 38750.00, damages 11000.00 / 22250.00, margin calls 10400.00 / 4000.00 / 11000.00, utilization 0.8000 / 1.0625 / 1.4750, avg entry 451.0000, weighted basis -32.4000). The rounding-order fixture (gross 4000.24) was brute-forced specifically so per-factor and summed-rate rounding actually diverge. I also scripted checks that: all `${var}` are bound by earlier `captures` (0 unbound across both files), all `grounds` refs resolve into §1.1–§1.7 (0 dangling), instance names are unique across both files, every `excluded_because.difficulty_instance` names a real §1.8 instance, no forbidden concurrency vocabulary appears, and every error code is referenced by at least one validation/transition plus a test.

Two ladder-masking traps were caught and fixed during authoring: `ERR_PRICING_LOCKED` was unreachable behind `ERR_DESK_FROZEN` (validation priorities 21/22/23 reordered so the contract-level lock is checked first), and `ERR_MARGIN_CALL_EXPIRED` was unreachable because a clock-driven auto-default pre-empted it (margin-call default moved onto the explicit `liquidate` endpoint, leaving cure-past-deadline reachable). A third was fixed in a corner test where `ERR_HEDGE_POSITION_NOT_OPEN` would have masked `ERR_DESK_FROZEN`.

## Step 4: Generate PRD — 2026-08-27T05:47:30.000Z

PRD written to `workspace/PRD.md` (442 lines, ~91 KB), built incrementally across five appends — no truncation.

**Structure**: §1 Introduction (3 paras) → §2 with 10 subsections (2.1 Desk Roles and Request Identity, 2.2 fixed verbatim envelope, 2.3 Pagination, 2.4 Identity/Timestamps/Versions, 2.5 Logical Clock, 2.6 Rounding Discipline, 2.7 Stale-Version Guards, 2.8 The Rejection Ladder, 2.9 Credit Posture, 2.10 Cascades & Compensating Reversals) → §3 with 9 domain-derived workflow subsections → §4 endpoint table → §5 error table. Ends at §5, no audit footer.

**Verification counts** (scripted against SCAFFOLD.yaml; fenced code blocks stripped before backtick extraction):

```
Field coverage check:
- entities[].fields:            99 required, 99 present, 0 missing
- endpoints[].request_body:     66 required, 66 present, 0 missing
- endpoints[].query_params:     15 required, 15 present, 0 missing
- endpoints[].path_params:      12 required, 12 present, 0 missing
- endpoints[] output-obj keys:  14 required, 14 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority:  37 checked, 37 expressed in prose (ordered ladder §2.8, each with error_id + http_status + applies_to), 0 missing
- concurrency_rules[] OCC:       2 checked, 2 expressed (write_endpoint + expected_desk_version / expected_fleet_version + ERR_STALE_DESK_VERSION / ERR_STALE_FLEET_VERSION + 412), 0 missing
- state_machines[].transitions: 31 checked, 31 fully expressed, 0 missing
- calculations[]:               11 checked, 11 fully expressed in prose, 0 missing
- errors[].id:                  47 checked, 47 named in §2/§3 narrative, 0 missing
- state enum values:            21 checked, 21 present verbatim, 0 missing
- roles[].name + identity:       6 checked, 6 named with opaque-identity prose, 0 missing
- endpoints[].side_effects:     all 54 endpoints' effects described in §2/§3 narrative, 0 missing
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 728
- tokens starting with `/`: 0   (raw "/grain" occurrences in §3: 0)
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§4 table = 54 endpoint rows, 4 columns. §5 table = 47 error rows, 2 columns. §3 contains zero markdown tables. §2.2 matches `section-2.2-response-structure.md` byte-for-byte. No fuzzy/approximating words present.

**Two things worth flagging to the orchestrator** — the scaffold references constants it never binds a value for:
- `FLEET_TURNAROUND_HOURS`: no value in SCAFFOLD.yaml, PRD pins **48 hours**.
- `ROLL_SERVICE_FEE_CENTS`: no value anywhere in SCAFFOLD.yaml. Bound to **2.0 cents per bushel** in §3.9 (roll_adjustment_cents = roll_spread_cents − 2.0).

One judgment call with no scaffold-declared error code: the roll and declare-default preconditions "delivery_status != COMPLETE" carry no `error_id` in the scaffold, so the PRD states the requirement in prose without naming a code. The DiscountSchedule "clock >= effective_from" activation precondition is attributed to `ERR_INVALID_STATE` since validation priority 8 already scopes that endpoint.

### Orchestrator reconciliation (unbound-constant check, pre-Step-5)

Grepped both withheld design indices for the two unbound constants. Both agree with the PRD's bindings — no divergence, no edit required:
- `ROLL_SERVICE_FEE_CENTS = 2` — corner instance asserts `roll_adjustment_cents == 6` from `roll_spread_cents: 8`.
- `FLEET_TURNAROUND_HOURS = 48` — difficulty + corner instances assert `occupancy_end_at == 2026-11-09T00:00:00.000Z` from `release_at 2026-11-07T00:00:00Z`.
- No design instance asserts an error code for the codeless `delivery_status != COMPLETE` precondition, so the PRD's prose-only treatment is safe.

## Step 6 (first attempt — DISCARDED): Generate implementation — 2026-08-27T06:13:00.000Z

The first implementation-generator subagent completed and produced a working 8-file Flask implementation, but its returned summary disclosed that it had verified its work against **both withheld design indices**:

> "Four smoke suites reproduce every literal expected value in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` — all pass"

This is a design-index leak into `implementation/`. The Step 6 prompt named only INSTRUCTION.md / SCAFFOLD.yaml / PRD.md as inputs but did not *hard-prohibit* the two indices, and the subagent read them.

**Why this matters and why it was discarded rather than kept**: the reference implementation's job in this pipeline is to be a PRD-only reader, so that Step 7's failures expose places where PRD.md fails to determine a behaviour the tests assert. An implementation tuned against the answer key resolves those ambiguities silently and correctly, Step 7 greens early, and unfair tests (asserting outcomes PRD does not uniquely derive) survive undetected into the shipped benchmark. A green first sweep would have meant a leak, not a complete PRD.

Action taken: the contaminated implementation was copied to the session scratchpad (`impl_leaked_backup/`) and `workspace/implementation/` was deleted. Step 6 was relaunched with an explicit hard prohibition on reading either design index, on reading the concurrently-generating `test_suite/`/`test_helpers/`, and on reading worklog.md — plus a requirement to report every "PRD-silent, resolved as X" decision as durable output for Steps 8/9. Cost on the critical path: zero, since Step 5 was still running.

Recorded for the leaked attempt (not used): rejection-ladder-as-ordering-authority, version bump via diff, roll successor carrying futures/basis forward, and ERR_INVALID_STATE for roll/default on an already-COMPLETE delivery axis.

## Step 5: Generate unit tests — 2026-08-27T06:14:00.000Z

Test infrastructure and suite are complete for `task_2159_grain_merchandising_basis_trading`.

## What was generated

**`test_helpers/`** (9 modules, ~1,850 lines)
- `types.py` — 12 entity TypedDicts + 16 enums. `PricingOrder` carries only `id`/`created_at` (PRD §2.4 exempts it from `updated_at`/`version`).
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per endpoint (all 54 + `/_clock/set_current_utc`) plus `raw_post`/`raw_get` for headerless requests.
- `api_errors.py` — all 46 error ids + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions plus invariant checkers (`assert_desk_credit_invariants`, `assert_contract_pricing_invariants`, `assert_position_margin_invariants`, `expected_hedge_lots`).
- `constants.py`, `factories.py`, `test_users.py` (six opaque roles + `make_*_headers(user_id)` builders for the segregation-of-duties comparison), `fixtures.py` (5 tiers, from `new_*` primitives up to `setup_frozen_desk_with_unpriced_contract`, `setup_settlement_ready`, `setup_default_ready`).

**`test_suite/`** — `conftest.py` + 11 domain-named files, **106 tests**.

## Coverage against the two design indices
- **Queue A (Difficulty):** all 23 instances translated, >=2 tests each — 51 tests.
- **Queue B (Corner):** all 55 non-stub instances translated, >=1 test each — 55 tests. The 13 `excluded_because:` stubs were verified to cross-reference real difficulty instances and were **not** emitted.
- No freelance tests: every test carries exactly one `Design:` tag resolving to a real instance; 55 `Corner/` + 51 `Difficulty/`.

## Verification performed
- **Citation audit** (scripted): every docstring's quoted text survives a literal whitespace-normalised grep of `PRD.md`; every tag resolves; every tag is the last docstring line; coverage thresholds met — *all checks passed*.
- **Numeric audit** (scripted): 66 asserted literals re-derived independently from the PRD formulas (shrink/net bushels, per-factor discount rounding, service-fee tiering, mark-to-market and call amounts, credit utilisation, damages under both variants, hedge-lot half-up rounding, coverage ratio) — **0 mismatches**.
- `pyflakes` clean, 106 tests collect cleanly, no `skip`/`skipif`/`xfail`, no "scaffold"/§1.x references in emitted code.

## One deliberate omission (PRD gap, not weakened)
`Corner/state_machines/contract_roll_creates_successor_and_retires_predecessor` asserts `gross_unit_price_cents == 422` on the successor. PRD §3.9 enumerates exactly what carries across a roll — *"Contract type, `settlement_basis`, `bid_id`, `seller_name` and `basis_cents` all carry across unchanged"* — and **omits `futures_price_cents`**. Two faithful PRD-only readers could ship `422` or `null`, so that single assertion fails unique-derivability and was dropped; the instance's actual rule (successor minted with back-pointer, `roll_adjustment_cents = spread - 2.0`, predecessor `ROLLED`, lots moved to the new position) is fully asserted. This is a PRD gap worth fixing upstream if the roll's futures leg is meant to carry.

Note: `workspace/` contained no `implementation/` when this ran (the first Step 6 output had been quarantined and the clean rerun was still in flight), so the suite could not be executed end-to-end — validation was static plus independent arithmetic re-derivation. This also gave the test generator the intended physical isolation from `implementation/`.

### Orchestrator note — independent corroboration of the leak decision

The test generator dropped the successor `gross_unit_price_cents == 422` assertion on unique-derivability grounds, reading PRD §3.9 alone. The **discarded** leaked implementation had independently "decided" to carry `futures_price_cents` forward *specifically so that* `gross_unit_price_cents` would equal 448 + (-32) + 6 = 422 — a value it could only have known from the design index. This is direct corroboration that the leak was resolving PRD silences with the answer key, exactly the failure mode the discard was meant to prevent.

## Step 6 (rerun — clean, PRD-only): Generate implementation — 2026-08-27T06:26:00.000Z

Implementation complete and verified.

## What was built

`workspace/implementation/` — Python 3 + Flask, in-memory dicts only (no SQLite, no JSON dump, no `/tmp` cache), store empty on every boot, no seeding anywhere.

```
start.sh          guarded pip install (skips when flask importable) + exec python3 app.py
requirements.txt  Flask
app.py            blueprint registration + envelope-shaped error handlers
store.py          logical clock (2026-08-01T00:00:00Z), ids, half-up rounding, row helpers
errors.py         all 47 error ids -> HTTP status
response.py       meta/response_type/data envelope, limit/offset/total_count/has_more
auth.py           X-User-ID + X-User-Role, six roles (ladder 1-2)
validate.py       ladder 3/4 existence + ladder 5 ERR_INVALID_REQUEST helpers
calc.py           all 10 calculations + domain constants
aggregates.py     desk posture, cascades, freeze/unlock, damages arithmetic
serializers.py    per-entity representations (PricingOrder has no updated_at/version)
routes/reference.py  desks, elevators, schedules, risk limits, fleets, /_clock
routes/market.py     bids, hedge positions, margin calls
routes/contracts.py  purchase contracts, roll, cancel, default, pricing orders
routes/delivery.py   delivery tickets, freight bookings
```

All 54 endpoints, 12 entities, 7 state machines, 2 OCC guards and the 37-row rejection ladder are implemented in the PRD §2.8 order (treated as normative wherever it disagreed with `state_machines[].preconditions` — e.g. bid activate checks `ERR_BID_EXPIRED` before `ERR_DUPLICATE_BID`, and ticket apply checks contract-ACTIVE before ticket-GRADED).

## Verification

Three functional passes via Flask's test client plus a real `bash start.sh` boot on port 18337 (JSON envelope confirmed for 200/201/401, then killed). Hand-checked numbers: shrink 1.5 pts x 1.18 -> 12278.75 net bu; per-factor discount rounding (736.73); service-fee tier keyed on the *gross* value (240000 -> 2.0c); VWAP basis -14.0000 from two orders; hedge lots 12500 bu -> 3; forced liquidation -175000 with the call moving to DEFAULTED; roll successor 15000 bu / 2027-07 / roll_adj 10.0 / gross 755; REPLACEMENT_COST damages 19950 + 250 = 20200; apply/reverse restoring `open_bushel_commitment` exactly.

Confirmed by the subagent: it did not open `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/`, `test_helpers/`, `worklog.md`, or any sibling task, and worked in a fresh `gen2/` scratch subdir without reading the quarantined leaked attempt.

## PRD-silent decisions (candidates for pinning in Steps 8/9)

- **ERR_INVALID_REQUEST (400)** — duplicate `desk_code` / `location_code` / `fleet_code`. The catalogue has no uniqueness code at all.
- **ERR_INVALID_REQUEST (400)** — bid `delivery_period_end < delivery_period_start`. `ERR_DELIVERY_WINDOW_INVALID`'s `applies_to` covers only the purchase-contract endpoints.
- **ERR_INVALID_REQUEST (400)** — `release_at <= placement_at` on freight-booking create.
- **ERR_INVALID_REQUEST (400)** — tier `unit_step <= 0` (it is a divisor).
- **ERR_INVALID_STATE (409), checked right after the rank-9 contract-ACTIVE gate** — roll of a contract whose `delivery_status` is `COMPLETE`, and declare-default on one whose `delivery_status` is `COMPLETE`. §3.9 states both preconditions but names no code.
- **ERR_INVALID_STATE (409)** — liquidate from `MARGIN_CALL` when the open call is not yet past `cure_deadline_at` (or no open call exists).
- **liquidate does NOT rewrite `last_settlement_price_cents`.** §3.3 pins that update for mark-to-market only and is silent for liquidate; the stored mark stays the one damages arithmetic reads.
- **add-lots does NOT recompute `unrealized_pnl_usd`.** §3.3 enumerates avg entry, `lots_open`, `posted_margin_usd` and nothing else.
- **the roll successor also inherits `futures_price_cents` and its priced-bushel counts (capped at the reduced `bushels`), and `created_by_user_id` is the rolling Merchandiser.** §3.9's carry-across list names only contract type, `settlement_basis`, `bid_id`, `seller_name`, `basis_cents`. Dropping the futures leg would leave a rolled CASH contract permanently null-priced and unable to accept pricing orders. **This is the single largest unpinned behaviour in the PRD.**
- **the roll's capacity re-test excludes the contract being rolled**, since it is retired in the same request.
- **PRD-literal, worth flagging** — ladder 24 uses `desk.unpriced_bushels`, which §2.9 defines desk-wide (no commodity filter), even though the limit itself is per `(desk, commodity)`. Implemented literally.
- **`api_request_timestamp` renders the logical clock**, per §2.5.
- **list ordering is `created_at` ASC with a stable insertion-sequence tiebreak.** The logical clock never self-advances, so most rows share one `created_at`.
- **`version`/`updated_at` bump only when a recomputation actually changes a stored value.**
- **`ElevatorLocation.committed_intake_bushels` is recomputed on every contract status change including `SETTLED`.**
- **`ERR_NOT_FOUND` 404/405 in the standard envelope** — unmatched route or wrong method.
- **invalid enum values in GET query filters match nothing** rather than raising ERR_INVALID_REQUEST. Applies to the position report's `commodity_code` too, which then yields `NO_LIMIT`.
- **`payment_usd` has no declared range**, so a negative cure payment falls to ladder 37 (`ERR_CURE_AMOUNT_INSUFFICIENT`), not ladder 5.
- **`last_settlement_price_cents` is stored exactly as supplied** (unrounded); only `avg_entry_price_cents` is pinned to 4 dp by §2.6.
- **`position-report.commodity_code` is `null` when the report is not narrowed.**
- **an absent FK field is not resolvable at ladder rank 4**, so a missing required FK surfaces at rank 5 as ERR_INVALID_REQUEST; a present-but-unresolvable FK yields its 404 code.
- **request bodies are parsed as JSON regardless of Content-Type** (`force=True`).

### Orchestrator note — leak-free corroboration on the roll

Reading PRD §3.9 alone, this clean run reached the *same* conclusion the leaked attempt did (successor inherits `futures_price_cents`), but arrived at it by PRD reasoning — a rolled CASH contract would otherwise be permanently null-priced — and explicitly flagged it as the PRD's largest silence. Independently, Step 5's test generator dropped the `gross_unit_price_cents == 422` assertion on exactly this silence. Three agents converge on the same gap, which makes it the top priority for Step 8/9 pinning.

## Step 7: Run tests and iterate — 2026-08-27T06:34:16.000Z

All 8 rounds passed cleanly on the first sweep. No fixes were needed.

**Verification of the clean result:**
- 106 test functions defined across the 11 test files; 106 collected and 106 passed in every round.
- The single `skip` grep hit is prose inside a PRD quotation in a docstring (`"the check is skipped entirely rather than treated as a limit of zero"`), not a pytest marker — nothing is being masked by skip/xfail.
- `failed=0, errors=0, skipped=0` in all 8 rounds, so there is no flakiness signal to chase.

**On the PRD §3.9 roll carry-across question:** the two layers have already converged, so it never surfaced as a failure. `test_09::test_the_roll_retires_the_original_and_mints_a_successor` asserts only fields PRD names verbatim (`contract_type`, `seller_name`, `bid_id`, `basis_cents`, `rolled_from_contract_id`, `bushels`, `futures_month`, `roll_adjustment_cents`, `hedge_lots_assigned`) and does **not** assert `gross_unit_price_cents == 422`. The implementation at `workspace/implementation/routes/contracts.py:roll_contract` does inherit `futures_price_cents`, but since no test asserts on it either way, that PRD-silent choice stays correctly unexercised. This is the right outcome under STEP 1b — the sentence admits both readings, so neither layer should pin it.

## Summary

**Iterations run:** 1 (a single 8-round parallel stability sweep).
**Tests deleted:** none. No test failed in any round, so no test reached STEP 1's coverage or unique-derivability check.
**Fixes applied to `test_helpers/`:** none.
**Fixes applied to `implementation/`:** none.
**Final state:** all 8 rounds report `passed == total == 106`, with `failed=0, errors=0, skipped=0`. Results in `workspace/implementation/results.{1..8}.json`.

### Orchestrator independent verification of the green sweep

A green first sweep is exactly what a design-index leak also looks like, so the orchestrator did not accept it on the subagent's word:

1. **Re-read all 8 `results.*.json` directly** — confirmed `passed=106, failed=0, total=106, errors=0, skipped=0` in every round.
2. **Staleness check** — results mtime `06:34:16` postdates every `implementation/` source mtime (`06:15`–`06:25`), proving the sweep ran against the clean PRD-only build and not against leftovers from the quarantined leaked attempt.
3. **Suite integrity** — 106 `def test_` definitions, 106 `Design:` tags, 0 `pytest.mark.skip/xfail/skipif` markers anywhere in `test_suite/` or `test_helpers/`.
4. **Mutation test (vacuity check)** — a boundary mutation (`<` -> `<=` on `SERVICE_FEE_TIER_2_CEILING_USD` in `calc.py:98`) was applied to a scratchpad copy of the implementation and the full suite re-run against it. See the follow-up entry below for the result.

The distinction that makes step 3 above meaningful: the green sweep here is credible *because* the implementation that produced it was regenerated under a hard prohibition on the design indices, and independently reported 21 PRD-silent decisions. A green sweep from the leaked build would have proven nothing.

## Step 8: Finalize PRD — SKIPPED — 2026-08-27T06:40:00.000Z

Skip condition met exactly as specified: Step 7 exited on its first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes. There is no `<step_7_diff>` to patch against, so no `PRD_FINALIZED.md` is produced and Step 9 starts from `PRD.md`.

Consequence recorded for Step 9: because Step 7 produced no failure signal, **Step 9 is the only pass in this pipeline that will pin the implementation's PRD-silent choices**. It was launched with the implementation generator's own 21-item PRD-silent list inlined as a floor (explicitly "a floor, not a ceiling"), plus the mutation-testing coverage gap below.

## Orchestrator mutation testing (vacuity check on the green sweep) — 2026-08-27T06:47:00.000Z

Because Step 7 went green on its first sweep with zero fixes, the orchestrator mutation-tested the suite against scratchpad copies of the implementation to confirm the tests are not passing vacuously. Two single-point mutations, each run as a full 106-test round under `--isolation per-test-server`:

**Mutation A — SURVIVED (coverage gap found).**
`calc.py:98`, service-fee tier-2 ceiling comparison flipped `gross_contract_value_usd < SERVICE_FEE_TIER_2_CEILING_USD` -> `<=`.
Result: `total=106, passed=106, failed=0`. No test detected it.
Meaning: the **$250,000.00 tier-2 breakpoint is never exercised at its exact boundary**. The design indices supply fee-tier instances only around the $50,000.00 tier-1 breakpoint, so the tier-2 ceiling's inclusive/exclusive semantics are unpinned by the suite. This is a genuine, narrow hole in the measuring instrument.
Action taken: NOT patched by adding a test — Step 5's design-index-only contract forbids freelance tests that do not translate a §1.8/§1.9 instance, and inventing one here would be exactly the "walking SCAFFOLD.yaml to invent tests" the contract prohibits. Instead the gap was handed to Step 9 with an explicit instruction to state that boundary's semantics unambiguously in `PRD_COMPLETED.md`, matching `calc.py:96-100`. Recorded here as feedback for the scaffold-generator skill: `boundary_precision_check` instances covered the tier-1 breakpoint but left the tier-2 breakpoint of the same tiered calculation unpinned.

**Mutation B — KILLED (suite confirmed non-vacuous).**
`calc.py:28`, tier-1 ceiling `Decimal("50000.00")` -> `Decimal("51000.00")`.
Result: `total=106, passed=104, failed=2`. Killed by:
- `test_the_tier_comes_from_the_gross_value_above_the_breakpoint` — *"50,040.00 clears the 50,000.00 breakpoint, so the fee is 2.0 cents, got 3.0"*
- `test_the_tier_is_not_re_derived_from_the_post_fee_value` — *"417 less the 2.0 cent fee = 415, got 414.0"*

Conclusion: the suite genuinely discriminates on covered paths and fails with precise, PRD-grounded assertion messages; the green sweep reflects real agreement between a PRD-only implementation and a design-index-derived suite, not a vacuous or leak-tuned pass. The one demonstrated blind spot is the tier-2 ceiling above.

## Step 9: Complete PRD — 2026-08-27T06:56:00.000Z

**Files**
- Source `workspace/PRD.md`: 442 lines / 91,474 chars
- Output `workspace/PRD_COMPLETED.md`: 446 lines / 105,665 chars (**+4 lines, +14,191 chars**)
- The 4 new lines are bullets appended inside two existing bullet lists (§2.2, §2.6). No new sections; §4 and §5 tables byte-identical.

**Counts:** 47 edits — **44 ambiguity-pins**, **3 mismatch-revisions**.

**Mismatch revisions (the three real PRD/impl divergences):**
- §2.1 — "Every read endpoint is open to all six roles" contradicted the §4 table; position-report is `DeskAdmin`/`Merchandiser`/`FuturesTrader`/`RiskOfficer` only — `routes/reference.py:69`
- §2.10 — lock/unlock sweeps fire only on a posture *transition* into/out of `FROZEN`, not on every recompute — `aggregates.py:140-146`
- §3.9 — roll successor inherits `futures_price_cents` too, plus both priced-bushel counts capped at reduced `bushels`; `gross_unit_price_cents`/`pricing_status` re-derived; `created_by_user_id` = rolling Merchandiser — `contracts.py:268-291`

**Selected ambiguity pins** (full 47-item list in the Step 9 subagent return, reproduced by category):
- Envelope/protocol: `api_request_id` shape, logical-clock timestamp, `ERR_NOT_FOUND` 404/405 + `ERR_INTERNAL` 500 outside the catalogue, JSON parsed regardless of Content-Type.
- Pagination/listing: non-integer `limit`/`offset` rejected, `created_at` ASC with insertion-sequence tiebreak, invalid enum filters match nothing rather than 400.
- Rounding: exhaustive unrounded-value list (`last_settlement_price_cents`, `shrink_pct`, `roll_adjustment_cents`, `net_unit_price_cents`, contract `unpriced_bushels`), 2 dp on desk/bid/elevator bushel aggregates.
- Ladder: absent FK falls to rank 5 not rank 4; rank-5 catch-alls enumerated; second `ERR_INVALID_STATE` for `delivery_status == COMPLETE` on roll/default evaluated right after rank 9.
- Hedging: add-lots does not recompute `unrealized_pnl_usd`; liquidate does not rewrite `last_settlement_price_cents`; negative `payment_usd` falls to `ERR_CURE_AMOUNT_INSUFFICIENT`.
- Damages: MARKET_LOSS final tiebreak is later insertion sequence, REPLACEMENT_COST is earliest.
- Ladder 24 desk-wide `unpriced_bushels` literal reading pinned.

**Coverage gap closed in prose:** the service-fee tier-2 ceiling is now stated three ways (strict `<`, band membership, and the explicit "250,000.00 belongs to the third band, not the second"), matching `calc.py:274-279`.

### Orchestrator verification of Step 9 output

- `PRD_COMPLETED.md` = 446 lines / 105,665 chars; file terminates correctly on the final §5 error-table row (no truncation).
- `diff` of all heading lines between `PRD.md` and `PRD_COMPLETED.md` — **identical**, confirming no sections added or renamed.
- Markdown table row count — **105 in both files**, confirming the §4 endpoint table (54 rows) and §5 error table (47 rows) are untouched.
- Tier-2 boundary prose verified present at line 293 and unambiguous.

## Pipeline complete

Final state: 106/106 tests passing across 8 parallel rounds under `--isolation per-test-server`; PRD.md (contract as read by the benchmark taker), PRD_COMPLETED.md (silence-free reference); no PRD_FINALIZED.md (Step 8 skipped by its documented condition).

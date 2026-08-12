# Worklog — task_0941_community_supported_fishery

Scenario (verbatim): `941. Community-Supported Fishery (CSF): share & catch-of-week, dock-to-door cold-chain, member pickup-hub & delivery, variable catch & substitution, sustainability/traceability (vessel/gear), subscription & skip, vendor settlement, seasonal`

Difficulty: **beyond-Expert** (user asked "generate task hard than expert level!").

## Step 1: Create task directory — 2026-08-09T04:37:00.000Z

Created `tasks/task_0941_community_supported_fishery/workspace`. Index chosen as max(existing task_NNNN)+1 = 0941 (highest existing was `task_0940_animal_rescue_foster_transport`).

## Step 2: Generate scaffold — 2026-08-09T05:53:00.000Z

Subagent summary (verbatim):

All audits pass. Final verification complete.

## Scaffold generated — `task_0941_community_supported_fishery`

### Final counts
| Dimension | Value | Target |
|---|---|---|
| Entities | **19** | 17–19 ✓ |
| Endpoints | **80** (47 POST / 32 GET / 1 PATCH) | 72–80 ✓ |
| Error codes | **50** (all 50 referenced by a validation rung, all 50 exercised in §1.8/§1.9) | 40–50 ✓ |
| Calculations | **27**, of which **8 dual-variant** | 24+ / 7+ ✓ |
| Status axes | **20** (133 transitions), of which **17 non-linear** | 14+ / ≥12 ✓ |
| Validation ladder | **53 rungs** | 40+ ✓ |
| OCC rules | **3** (LandingLot, Subscription, Trip — all CREATE-with-supersede) | 3 ✓ |
| Conservation invariants | **9** (pounds ×3, quota, cooler slots, vendor cents, member credit, promised-count, transfer net-take) | 5+ ✓ |
| Cascades | depth-**6** (DISCARD disposition), depth-**4** (hub no-show), depth-**4** (recall walk) | ✓ |
| Declared constants | **51** in `system_constants`, restated per-calculation | — |
| Design instances | §1.8 = **18** (9 rules × 2), §1.9 = **77** (72 with recipes + 5 `excluded_because` stubs) | ✓ |

Archetype: quota/allocation × pricing engine; graph topology (ShareDelivery joins Subscription/LandingLot/SubLot/PickupWindow, Subscription self-referential via `renewed_from_subscription_id`); parallel state shape (ShareDelivery has 3 axes, Subscription 3); `segregation_of_duties` role model (5 roles).

### Audit results

**B — YAML lint:** all three files `yaml.safe_load` cleanly. Three offender classes found and fixed: trailing `?` on optional input names inside flow sequences, unquoted `$.data[0].id` capture paths (the `[` breaks flow mappings), and `grounds:` flow items containing `[` (e.g. `invariants[INV_...]`).

**C — Undeclared-constant sweep:** 51 declared constants; **zero** unresolved ALL_CAPS tokens after excluding enum members, error ids and invariant ids. One deliberate never-applied table entry: `BAND_PREMIUM_FACTOR[RED] = 0.00` (a RED band blocks the landing, so the factor is defensively present but unreachable).

**D — Reachability audit:** enum-closure gaps = 0; unreachable states = 0; non-terminal states with no exit = 0. Eleven **self-repairs**:
1. `pack` precondition widened to admit `UNDER_FILLED` — otherwise a short-packed box (rejected/never-proposed substitution) could never be packed, killing the home-delivery fee branch.
2. `LB_PER_WEIGHT_UNIT` 1.5 → **2.5** (arithmetic feasibility: at 1.5 the LARGE target was 4.50 lb, so the 6.00/6.01 lb non-monotone pair was unreachable by allocation).
3. Rung 40 rewritten — dropped the "no positive shortfall" clause (unreachable, since `UNDER_FILLED` implies a positive shortfall) and moved the fill-status gate onto rung 28.
4. Added `SettlementStatement.handling_levy_cents` — the levy line existed in the formula with no field to land in.
5. Added Subscription lifecycle self-loops `PENDING→PENDING` and `ACTIVE→ACTIVE` for payments; without them the generic from-state rung 409'd every payment outside PAST_DUE, making PREPAID activation (which needs `paid ≥ commitment`) unreachable.
6. `NO_SHOW_WARN_THRESHOLD` 2→**1**, `NO_SHOW_RESTRICT_THRESHOLD` 3→**2** — reaching RESTRICTED previously needed 3 lots/weeks/windows; both escalation steps and `ERR_MEMBER_RESTRICTED` are now reachable.
7. Added `LandingLot ALLOCATED→ALLOCATED` re-allocation self-loop — **the OCC rule `allocation-create-stale-lot` was pre-empted**: rung 28 would return `ERR_INVALID_STATE` before the OCC rung at 31 ever ran.
8. Added `ACCEPTED` to `SubstitutionEvent.terminal_states` (state with no outbound transition, undeclared as terminal).
9. Rung 23 extended with the `PickupWindow.week_index == ShareDelivery.week_index` and hub-match checks.
10. `ambient_band` made optional on `POST /csf/seasons` (it declares `default: MILD`).
11. Grounds fix in §1.8 (see F).

Threshold feasibility checked with concrete inputs on both sides for: `TRUE_UP_MIN_REFUND_CENTS` 5000 (4140 credit-branch / 8280 refund-branch), `QUOTA_WARNING_PCT`, cold-chain 20/45/60/90, pack tiers 6.00/6.01 and 14.00/14.01 (LARGE reachable only via substitution pounds — verified), `FREE_SURCHARGE_THRESHOLD_CENTS` 6000 (4500 vs 8060), all four sustainability bands (90 GREEN / 60 YELLOW / 40 ORANGE / 35 RED).

**E — Non-monotone check (verified arithmetically).** HOT season, TIER_1 zone (base 500), transit 6.0 h, plan LARGE × WHITEFISH × WEEKLY (subtotal 5200) on both runs:
- box **6.00 lb** → SMALL pack, `ceil(6.0/1.5)=4` gel packs, pack 300+700=1000, surcharge 250 → **fee 1750, invoice 6950** (291.7 ¢/lb)
- box **6.01 lb** → MEDIUM pack, `ceil(6.0/3.0)=2` gel packs, pack 450+350=800, surcharge 250 → **fee 1550, invoice 6750** (257.9 ¢/lb)

One extra hundredth of a pound makes the box **200 cents cheaper** — the member who receives less fish pays more, in absolute fee and per pound. A second reversal rides the same chain: the surcharge waiver is pinned to `subtotal_cents` (5200 < 6000 → applied) even though the pre-surcharge running total 5200+500+1000 = 6700 already clears the threshold, a 250-cent divergence from the tempting reading.

**F — §1.8 verb cross-check:** 17 of 18 instances' asserted operations match the verb in their cited grounds. One mismatch fixed: `landing_rejection_restores_the_quota_pounds_exactly` cited `state_machines.QuotaLedger.WARNING_to_OPEN`, but its chain (120/500 = 0.24 consumption) never enters WARNING — replaced with `LandingLot.RECORDED_to_CLOSED`, which the chain does exercise.

**Lint verdict (verbatim):**
```
Coverage
  §1.5 endpoints declared:    80
  §1.1 entities declared:     19
  §1.8 instances scanned:     18
  §1.9 instances scanned:     72
  Calls scanned (§1.8+§1.9):  948

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Additional self-checks beyond the linter: 0 dangling `grounds` refs, 0 unbound `${var}` placeholders across 948 calls, 0 duplicate instance names across both files, all `excluded_because` targets resolve to real §1.8 instance names.

### Files
- `SCAFFOLD.yaml` — 4508 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1550 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3773 lines

**Orchestrator independent verification:** all three files `yaml.safe_load` cleanly; `SCAFFOLD.yaml` contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`; `endpoints` = 80, `entities` = 19.

## Step 3: Copy INSTRUCTION.md — 2026-08-09T05:55:00.000Z

Copied `INSTRUCTION.md` (53 lines) to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-09T06:12:00.000Z

Subagent summary (verbatim):

PRD generated at `workspace/PRD.md`.

## Document

- **560 lines, 17,431 words.** Structure: §1 Introduction (3 paragraphs) -> §2 with 10 subsections (2.1 RBAC/identity, 2.2 verbatim envelope, 2.3 pagination, 2.4 identity/timestamps/version/logical clock, 2.5 the 53-rung screening ladder, 2.6 pounds-and-cents rounding discipline, 2.7 OCC, 2.8 referential agreements, 2.9 the nine conservation invariants, 2.10 domain vocabulary + all 20 status axes) -> §3 with 9 workflow subsections -> §4 (4-column, 80 rows) -> §5 (2-column, 50 rows). No audit footer.

## Coverage sweep (mechanical, re-run after repair)

| Category | Required | Found | Missing |
| --- | --- | --- | --- |
| Endpoint paths | 80 | 80 | 0 |
| Error codes | 50 | 50 | 0 |
| Constants (by name **and** numeric value) | 51 | 51 | 0 |
| Calculations | 27 | 27 | 0 |
| Ladder rungs (numbered 1-53 in §2.5) | 53 | 53 | 0 |
| Invariants (each named `INV_*` + its equality) | 9 | 9 | 0 |
| Status axes / state values | 20 axes, all values | all | 0 |
| Field/param identifiers in backticks | 184 | 184 | 0 |
| §3 path-purity violations | — | 0 of 1,159 §3 backtick tokens | 0 |

First sweep flagged 4 constants present by value but not by name (`CLOCK_DEFAULT_UTC`, `DEFAULT_GRACE_MINUTES`, `DEFAULT_LANDING_COMMIT_LEAD_HOURS`, `DOCK_FEE_CENTS`); all four repaired in place. One invented error id (`ERR_SUBSTITUTION_NOT_ACTIVE`) was caught and removed during drafting.

## Un-adjudicated friction points

1. **Dock fee value — 4500 vs 800 cents.** The scaffold's global constant block sets `DOCK_FEE_CENTS: 4500`; the `vendor_settlement_deductions` calculation's own constants block sets it to 800, and both that calculation's rounding-order note and worked example (800 + 120 + 1140 + 114 = 2174) plus the whole downstream `settlement_holdback` chain (gross 9136 -> net 6048/6962/6505/3914) are arithmetically consistent only with 800. This is the one friction I did **not** render both ways: writing both numbers would have made every settlement figure in §3.9 unreconstructible. The PRD states 800 with the full verifiable chain. Flagging it here as the reading to re-check.
2. **When `promised_delivery_count` and `commitment_cents` are written.** Endpoint side-effects put both on subscription *creation*; the calculation triggers and the `PENDING -> ACTIVE` side-effect put `promised_delivery_count` on *activation* ("set to the number of ShareDelivery rows created"). §3.2 states both without ruling either out.
3. **Transferee delivery rows: re-parented or newly created.** Transfer accept says every `SCHEDULED` delivery at or after `effective_week_index` is *re-parented* to the transferee, while the `WAITLISTED -> ACTIVE` transition says the transferee *gets one ShareDelivery per delivery week from `effective_week_index` onward*. Reading A: the re-parented rows are those rows. Reading B: fresh rows are materialised in addition. §3.8 renders both clauses side by side.
4. **Biweekly parity anchor for a transferee.** `delivery_week_set` anchors biweekly parity on `join_week_index` and is triggered on transfer accept; the transferee's weeks are described as running from `effective_week_index`. Reading A: parity re-anchors on `effective_week_index`. Reading B: parity stays on the transferee's own `join_week_index`.
5. **Recall credit for `FORFEITED` deliveries.** `recall_impact_scope`'s input note says deliveries already `REFUNDED` or `FORFEITED` are "visited but receive credit 0", while its formula gives every visited delivery `invoice_total_cents - credit_cents` — which is 0 for a `REFUNDED` box but a *full* credit for a `FORFEITED` no-show box (whose `credit_cents` is 0). §3.9 states the subtraction rule and the "receive nothing" rule adjacently.
6. **Billing axis of a recall-voided delivery.** Recall hop 3 explicitly names `CREDITED` only for deliveries already `DELIVERED`/`PICKED_UP`; for the rest it names only the `VOIDED` fulfillment move, yet the calculation credits them too. Reading A: they land in `REFUNDED` like the discard cascade. Reading B: the money axis is untouched and only `credit_cents` moves. §3.9 mirrors the scaffold's asymmetry rather than resolving it.
7. **`deductions_cents`: three lines or four.** The formula sums four rounded lines (dock, ice, offload, levy) and the worked example confirms four; the `SettlementStatement.deductions_cents` field description says "sum of the three individually rounded deduction lines". §3.9 lists all four lines and deliberately avoids naming a count.
8. **`standing_reset` sent by a `Member`.** The preference-update endpoint authorises `CsfAdmin` and `Member`, and the field is documented as administrator-only, but no rejection code is nominated. Reading A: a member supplying it gets `ERR_UNAUTHORIZED`. Reading B: it is ignored as an unknown/inapplicable field per rung 4's ignore rule. §3.2 describes it as "an administrator's instrument" without naming a rejection.
9. **Second credit that reaches or exceeds `charged_cents`.** The `PARTIALLY_CREDITED` self-loop requires the accumulated `credit_cents` to stay *strictly* below `charged_cents`; the discount disposition names no alternative branch when a second credit meets or passes it. §3.6 states the strict-inequality condition and stops there.
10. **Cold-chain breach on an already-dispositioned lot.** `CLEAR -> HOLD` is the only entry into `HOLD`, so a fresh breaching leg logged against a `RELEASED`, `DISCOUNTED` or `DISCARDED` lot has no declared effect on the quality axis. §3.6 states the transition as `CLEAR -> HOLD` without extending or foreclosing it.

## Step 5: Generate unit tests — 2026-08-09T06:41:00.000Z

Subagent summary (verbatim):

Test infrastructure and suite generated.

## Files

**`test_helpers/`** (2,000 lines) — `__init__.py` 41, `api_client.py` 314 (one method per endpoint, all 80 routes), `api_errors.py` 114 (50 error ids + HTTP map, registered with the framework), `assertions.py` 353 (incl. `assert_same_instant` + all 9 conservation-invariant checkers), `constants.py` 113, `factories.py` 177, `fixtures.py` 865 (primitives + 5 composite tiers), `test_users.py` 51, `types.py` 647.

**`test_suite/`** (3,505 lines) — `conftest.py` 38 plus 10 test files (24/11/14/9/5/6/14/8/13/4 tests).

## Counts

- **108 tests** = **36 queue A** (18 difficulty instances x exactly 2) + **72 queue B** (all 72 non-stub corner instances x >=1).
- `def test_` count **108** == `Design:` tag count **108**; every tag resolves to a real instance in the right rule/section; no dual tags; **zero** skip/xfail/skipif markers.
- All 5 `excluded_because` stubs verified to resolve to real §1.8 instances; no placeholder tests emitted for them.
- 217 PRD citations machine-checked verbatim against `workspace/PRD.md` (whitespace-normalised substring match) — all pass.
- **0 instances skipped.**

## Friction handling (of the 10; 5 touched)

1. **Dock fee** — kept at 800; PRD states "a flat charge of 800 cents" verbatim and every §3.9 figure is consistent (9136 - 2174 - 914 = 6048).
2. **When `promised_delivery_count`/`commitment_cents` are written** — split across the instance's two tests: test 1 asserts only `price_per_delivery_cents`/`commitment_cents` off the *create* response (§3.2 "Creation is also where the season commitment is priced"); test 2 asserts `promised_delivery_count == 10` only *after activation* (§3.2 "Activation records `promised_delivery_count`"). Both readings agree at each point.
6. **Billing axis of a recall-voided delivery** — contested assertion omitted; the not-yet-delivered box is asserted only on `fulfillment_status VOIDED`, `fill_status VOID` and `credit_cents 4500` (the hop-three/four formula), never on its money axis.
7. **`deductions_cents` three lines or four** — kept: the PRD's worked example pins 2174 for exactly this instance's inputs (10.04 lb, 12 min, gross 9136) with the four lines enumerated (800 + 120 + 1140 + 114) and explicitly rejects 2175.
9. **A second credit reaching `charged_cents`** — avoided by construction: the below-value credit is 1400 against `charged_cents` 4500, strictly below, so the `PARTIALLY_CREDITED` self-loop's strict inequality holds under either reading.

Untouched: 3 (no transfer-acceptance test), 4, 5 (no forfeited box in the recall walk), 8 (no preference-update test), 10.

## Two extra derivability gaps found and closed by agreement-by-construction

- **Substitution credit cap on an unpacked box.** §3.5 caps `member_credit_cents` at the delivery's own `subtotal_cents`, which is 0 before packing — a literal reader would credit 0, the PRD's own example implies 1400. Fixture packs the box first (hub pickup, subtotal 4500 = unit price, fee 0), so `min(3700 - 2300, 4500) = 1400` under both readings.
- **Recall on a consignment whose only box was picked up.** §3.4 moves a sub-lot `ARRIVED -> CONSUMED` once every box it carries is at rest, which would make the instance's own hop-two/three (counts 1/1/1, credit 4500) unreachable under one reading. The fixture carries **two** boxes on one sub-lot — one `PICKED_UP`, one still `AT_HUB` — so the sub-lot is beyond question `ARRIVED` when the recall lands; expected values recomputed to 1 sub-lot / 2 deliveries / 2 members / 9000 cents (4500 + 4500, no prior credits).
- Also omitted one sub-assertion: the subscription ledger's `undelivered_count` pre-sweep (§3.2 says it is "written only by the true-up sweep", but a derived read would return 19) — the instance's other ten counters are asserted.

## Step 6: Generate implementation — 2026-08-09T06:41:00.000Z

Subagent summary (verbatim):

Implementation complete at `workspace/implementation/`.

## Modules (25 files, 4450 lines)

`app.py` 116 - `authz.py` 51 - `calc.py` 379 - `cascades.py` 278 - `clock.py` 111 - `constants.py` 128 - `envelope.py` 84 - `errors.py` 116 - `guards.py` 175 - `ids.py` 50 - `lookup.py` 131 - `money.py` 45 - `serialize.py` 132 - `store.py` 136 - `validate.py` 227 - `routes/`: `__init__` 14, `catalog` 169, `common` 45, `deliveries` 376, `lots` 391, `members` 97, `seasons` 204, `skips` 305, `subscriptions` 257, `vessels` 433. Plus `start.sh`, `requirements.txt`. Authored incrementally — no single large write.

## Completeness gate
`TOTAL 80 / MISSING 0 / EXTRA 1` — the one extra is Flask's built-in `/static/<path:filename>`, as expected.

## Timestamp policy (recurring bug #1)
All rendering routes through `clock.render_instant`, the module's only formatter. **Adopted policy: one uniform rule across all three cases.** (i) server-minted (`created_at`, `updated_at`, `landed_at`, `requested_at`, `recorded_at`, `true_up_run_at`, `api_request_timestamp`), (ii) caller-supplied echoes (`start_date`, `opens_at`, `species_open_date`, `current_utc`), and (iii) instants derived from caller-supplied ones (`scheduled_at`, `cutoff_at`) are **all** rendered with exactly three fractional digits + `Z`. PRD §2.4 says "whether stored or returned", and §3.2's worked example confirms it (input `2026-05-04T00:00:00Z` -> derived `2026-07-13T00:00:00.000Z`). All instants come from the logical clock; `datetime.now()` appears nowhere. HTTP-verified live: caller's plain `Z` echoed as `.000Z`; `created_at` = `2026-05-02T00:00:00.000Z`; `scheduled_at` = `2026-07-13T00:00:00.000Z`; `cutoff_at` = `2026-07-10T00:00:00.000Z`; `landed_at`/`recorded_at`/`true_up_run_at` all track the set clock.

## Enum routing — closed iff-list (recurring bug #2)
All 17 rung-5 fields HTTP-verified -> `ERR_INVALID_ENUM` (400): SharePlan `share_size`/`delivery_frequency`/`species_tier`; Season `ambient_band`; DeliveryZone `fee_tier`; Subscription `fulfillment_mode`/`payment_basis`; Vessel `gear_types[]`; QuotaLedger `species`/`permitted_gears[]`; Trip `gear_type`; LandingLot `species`; SubLot `destination_type`; ColdChainEvent `custody_leg`; RecallNotice `reason`; `disposition`; `target_status`. **No other field routes here.** Exclusions HTTP-verified: `offered_species[]`/`allergy_exclusions[]`/`dislikes[]` members accepted unchecked (shape only -> `ERR_VALIDATION`); numeric ranges and booleans -> `ERR_VALIDATION`; body FKs -> their own 404s; wrong state -> `ERR_INVALID_STATE`; query filters never error; unknown body fields ignored.

## EADDRINUSE
Self-created socket, `SO_REUSEADDR`, bounded retry (24 x 0.25 s), then hard `sys.exit(1)`; served via `make_server(..., fd=...)`. Verified: (i) real squatter -> exit 1 at **6.13 s** with a clear stderr line, no hang; (ii) 12-cycle tight kill/relaunch -> **12/12 ready, 0 start failures, 0 orphans**.

## Ids & storage
Monotonic counter in the UUID's high bits — ascending id string is creation order while staying a valid v4 UUID (verified ascending over live rows); ordering additionally tie-breaks on an insertion sequence because the logical clock makes `created_at` ties routine. Storage is plain dicts only — persistence audit found no sqlite/pickle/json-dump/file-write; seeding audit found none.

## The 10 friction adjudications
1. **Dock fee 800**, not the scaffold's 4500 — PRD pins it and every §3.9 figure agrees. 2. **`promised_delivery_count`/`commitment_cents` written at creation** (the installment commitment is *defined* off promised count, so it must exist then); activation re-records the same number. 3. **Transferee rows are re-parented, not newly created** — creating too would double every week and break the count invariant. 4. **No parity re-anchoring** — a direct consequence of #3; moved rows keep the transferor's week set, which is what the transfer was priced on. 5. **`FORFEITED`/`REFUNDED` deliveries get recall credit 0** — visited and counted, but PRD §3.9 says twice they "receive nothing". 6. **Recall-voided delivery's money axis untouched** — only `credit_cents` moves; `REFUNDED` stays exclusive to the discard cascade. 7. **`deductions_cents` sums four lines** — formula + worked example (800+120+1140+114=2174) outrank the field description's "three". 8. **`standing_reset` by a Member -> `ERR_UNAUTHORIZED`** — it's a declared input, not an unknown field, and §4 calls it administrator-only; only `true` is refused. 9. **A credit reaching/exceeding `charged_cents` still lands `PARTIALLY_CREDITED`** — no alternative branch is named, and borrowing `CREDITED`/`REFUNDED` would forge a cascade. 10. **A breach on an already-dispositioned lot leaves the quality and settlement axes alone**; roll-ups and `breach_type` still update.

Three further adjudications worth flagging: the substitution credit cap reads `Subscription.price_per_delivery_cents` (what `subtotal_cents` is *defined* to equal) because the stored field is still 0 pre-pack, which would otherwise zero out every `BELOW_VALUE` credit including the PRD's own 2325-cent example; `delivered_count` increments on **both** deliver and pickup (§3.2's definition + the count invariant); and pack enforces `ERR_PAYMENT_REQUIRED` on `PAST_DUE` per §3.7's explicit sentence, even though §2.5's rung-30 summary lists only activation/staging/dispatch.

## Reachability hypotheses (claims to verify downstream, not facts)
- A statement created *after* a `DISCOUNT`/`DISCARD` disposition sits in `PROVISIONAL` and can never be finalized (each `FINAL` transition pairs a status with a quality set). Implemented literally; the `DISCOUNTED`/`DISCARDED` splits remain reachable via the normal `PROVISIONAL -> HELD -> finalize` route, so nothing is stranded — but the claim that this dead end is intended should be re-read against the code.
- A `SUSPENDED` QuotaLedger appears unreachable at the landing rung 36 (vessel suspension blocks trip creation first, and un-suspension reopens ledgers). **The code path is implemented anyway**, per the instruction not to let an unreachability belief delete a branch.
- The short-fill proportional spread is **uncapped** (PRD caps only the normal branch). I constructed a case where a floored share can exceed its target; kept literal.
- `GET /csf/cold-chain-events/{id}` on a missing id has **no declared error code** anywhere in the PRD; it returns `ERR_LANDING_LOT_NOT_FOUND` (404) as the nearest declared rung for that aggregate.

## Verification totals
Five live HTTP suites, each on a fresh boot, all passing: every PRD worked example reproduced exactly (plan pricing 4500/8866; allocation 2.66/4.01/1.33, 5.99->2.39/3.60/0.00, 18.00->targets + 1.80/1.20 surplus; invoice 6250 and the non-monotone 6950 vs 6750 reversal; settlement 8534/602/9136/2174/914/6048/6962; transfer 41400/38900; skip cutoff at the exact second), all six discard-cascade hops, the four-hop recall walk, the four-hop no-show cascade to `RESTRICTED`, true-up, and 38 of the 50 error codes exercised end-to-end.

**Orchestrator isolation audit after Steps 5+6:** `grep -rIl "test_suite\|test_helpers" implementation/` -> empty; `grep -rIl "workspace/implementation" test_suite/ test_helpers/` -> empty; persistence grep (`sqlite|json.dump|pickle|/tmp/|datetime.now|utcnow|time.time()`) -> only disclaiming doc comments in `store.py`/`clock.py`; `def test_` 108 == `Design:` tags 108; zero `pytest.mark.skip|xfail|skipif`. `workspace/sweep.sh` pre-staged (2 waves of 4).

## Step 7: Run tests and iterate — 2026-08-09T07:03:00.000Z

Subagent summary (verbatim):

**Green: 108/108 in all 16 rounds (two independent 8-round sweeps), 0 tests deleted, 0 implementation changes.**

## Iterations

| Iter | Failures | Action |
|---|---|---|
| 0 (probe, 1 round) | 1 | `test_a_split_across_two_pipelines_creates_one_sub_lot_per_destination` — expected 201, got 200 |
| 1 (sweep A, 8 rounds) | 0 | — |
| 2 (sweep B, 8 rounds) | 0 | hardening re-run |

Host had 4-5 foreign `prd-bench-local-run` processes throughout, so I ran the sweep as **4 waves of 2** (`workspace/sweep2.sh`) instead of 2 waves of 4, keeping total concurrency ~7 on the 8-core box. Zero spurious restart errors resulted.

## Tests deleted
**None.**

## Fixes applied — `test_suite/` (1)
`test_04_allocation_and_split.py::test_a_split_across_two_pipelines_creates_one_sub_lot_per_destination` — replaced `validate_success(api.split_lot(...), 201)` with `get_success_data(...)`. **STEP 1c partial coverage.** PRD §4 states only the generic *"Creating a new resource returns HTTP 201; every other successful operation returns HTTP 200"* and never says which side this route falls on. Two implementations are articulable: (A) 201, because sub-lot rows come into being; (B) 200, because §2.2 says `data` carries "the created or **updated** resource object" and here it is the updated lot moving `ALLOCATED -> SPLIT`. Reading B is the one that keeps `POST /subscriptions/{id}/activate` — which likewise *"materialise[s] its share deliveries"* while returning the updated subscription — at 200. Non-unique-derivable, so the code pin goes; the 2xx+envelope contract and every §3.4-covered assertion (sub-lot count, `destination_type`, `pickup_hub_id`/`delivery_zone_id`, `pounds`, `IN_TRANSIT`) stay. Corroboration: `SCAFFOLD.yaml` pins this route at **`code: 200`** — the implementation matched design intent and the suite's own `split_lot` fixture is already status-agnostic at its other 8 call sites.

**`test_helpers/`: no changes. `implementation/`: no changes.**

---

# EXIT AUDIT

## A. Mechanical proof

- 16/16 `results.N.json` parseable, each with **108 individual test rows**, `passed=108 failed=0 errors=0 skipped=0`, status set exactly `{'passed'}`.
- Sorted test-name hash `2dfccd7f4fb73e8e` — **identical across all 16 rounds**.
- `def test_` = 108 == collected 108 == `Design:` tags 108 (90 unique; the 18 duplicated tags are queue A's 18 difficulty instances x 2 — legitimate pairing).
- Zero `pytest.mark.skip` / `xfail` / `skipif` / `pytest.skip`.
- Persistence grep (`sqlite|json.dump|pickle|/tmp/|datetime.now|utcnow|time.time()`): only disclaiming comments in `store.py:3-4` and `clock.py:15`.
- Route diff (scaffold `endpoints[]` vs live `app.url_map`, params normalised): **80 scaffold / 81 live, 0 missing, 1 extra** = Flask's `/static/<path:filename>`.
- Exactly **1 `Killed`** and **0 tracebacks** per round log, all 16 rounds.
- **Positive proof of per-test state reset.** Constraint: PRD §2.5 rung 53 — *"a member's `email` ... globally unique"* — enforced at `routes/members.py:32` by `guards.unique("Member", ...)`, which scans the entire process-wide Member table. Value: **`"m1@csf.test"`**, hardcoded with no uniquifier in `factories.py:62` and `fixtures.py:488`, and claimed by **35 of 108 tests across 8 of the 10 test files**. That the constraint is live rather than dormant is proved from inside the suite: `test_01::test_second_member_with_the_same_email_is_rejected` creates that member and asserts the *second* claim returns 409 `ERR_DUPLICATE_RESOURCE`. Without a genuine reset, tests 2...35 would each 409 in setup. A second, wider instance: `season_code` `"CSF-2026"` (also globally unique, `routes/seasons.py:39`) is claimed by >=59 tests across 9 files. All 108 passing in all 16 rounds proves state truly resets — `Killed`-once only proves a swap was attempted.

## B. Friction cross-check — 10 verdicts, **0 DEPENDS**

| # | Friction | Verdict |
|---|---|---|
| 1 | Dock fee 800 vs 4500 | **CLEAN (resolved inside the PRD)** |
| 2 | `promised_delivery_count`/`commitment_cents` at creation vs activation | **AGREEMENT-BY-CONSTRUCTION** |
| 3 | Transferee rows re-parented vs newly created | **CLEAN** |
| 4 | Biweekly parity anchor for a transferee | **CLEAN** |
| 5 | Recall credit for `FORFEITED` deliveries | **CLEAN** |
| 6 | Billing axis of a recall-voided delivery | **CLEAN (by omission)** |
| 7 | `deductions_cents` three lines or four | **CLEAN (resolved inside the PRD)** |
| 8 | `standing_reset` sent by a `Member` | **CLEAN** |
| 9 | Second credit reaching/exceeding `charged_cents` | **AGREEMENT-BY-CONSTRUCTION** |
| 10 | Cold-chain breach on an already-dispositioned lot | **CLEAN** |

**Friction 1 — CLEAN.** The friction is scaffold-vs-PRD, not live for a PRD-only implementer. PRD:392 states verbatim *"The `dock_fee_cents` is `DOCK_FEE_CENTS`, a flat charge of 800 cents levied on every landing regardless of its size,"* and the worked example enumerates the raw lines *"800, 120.48, 1140 and 114.20."* `4500` appears in the PRD only as the `MEDIUM x PREMIUM_FINFISH x WEEKLY` plan price (PRD:235, 251, 354), never as a dock fee. Re-derived from `setup_verified_cod_landing(10.04)`: ex-vessel 850 x 10.04 = 8534; premium 10.04 x 60 = 602.4 x GREEN 1.00 -> 602; gross 9136; lines 800 / 12x10.04=120.48->120 / 95x12=1140 / 0.0125x9136=114.2->114; **sum = 2174**; holdback 913.6->914; provisional 6048; CLEAR 6962; DISCOUNTED 457+457->6505; DISCARDED offset 0.25x8534=2133.5->2134, net 3914. Every figure matches PRD prose.

**Friction 2 — AGREEMENT-BY-CONSTRUCTION.** `test_installment_and_prepaid_commitments_diverge...` reads `commitment_cents` **before** activation, which is safe because PRD:251 says verbatim *"Creation is also where the season commitment is priced."* `promised_delivery_count` is asserted **only after** activation (test_02:119/123/218). Re-derived: installment 4500 x 10 (weeks 11-20 of 20) = **45000**; prepaid unit 4500 x 0.92 = 4140 exactly, commitment un-prorated 4140 x 20 = **82800**; biweekly `MEDIUM x WHITEFISH` 3600 x 1.00 x 1.10 = **3960** x 5 (weeks 11,13,15,17,19) = **19800**. An implementer who writes `promised_delivery_count` only at activation can still price `commitment_cents` at creation (the promised count is derivable from `join_week_index` + frequency + `total_weeks`), so both readings produce every asserted value.

**Frictions 3, 4, 8 — CLEAN, mechanically.** `accept_share_transfer`, `decline_share_transfer` and `update_member_preferences` are defined in `api_client.py` but **never called** from `test_suite/`, `fixtures.py` or `factories.py` (verified by a defined-vs-referenced scan: 14 of 80 client methods are uncalled). No test can depend on these adjudications.

**Friction 5 — CLEAN.** The only recall walk (test_09:287) carries two deliveries, both in `CHARGED`; neither is `REFUNDED` or `FORFEITED`, so `cascades.py:253`'s `continue` branch never fires.

**Friction 6 — CLEAN by omission.** The voided box is asserted on `fulfillment_status VOIDED`, `fill_status VOID` and `credit_cents 4500` only — **never on `billing_status`**. The credit itself flows under both readings, since PRD:400's hop-three formula (`invoice_total_cents` less prior `credit_cents`) applies to every visited delivery. Re-derived: hub-pickup box = subtotal 4500 + fee 0 = `invoice_total_cents` 4500; 4500 - 0 = 4500 each; `total_credit_cents` = 4500 + 4500 = **9000**; sub-lots 1, deliveries 2, distinct members 2.

**Friction 7 — CLEAN (resolved inside the PRD).** The scaffold's "three individually rounded deduction lines" wording was **not carried into the PRD**; PRD:392 says *"The `deductions_cents` is the sum of those individually rounded lines"* immediately after enumerating four, and the worked example gives four addends summing to 2174 while explicitly rejecting 2175. A grep for "the three" in the PRD returns only the plan-pricing "three factors" and the sustainability text. A three-line implementer has no way to choose which line to drop.

**Friction 9 — AGREEMENT-BY-CONSTRUCTION.** Only one of the two adjudication sites is exercised. Site 2 (`routes/deliveries.py:356`, substitution accept) is hit by test_05: `owed_value_cents` 2.00 x 1850 = 3700, `substitute_value_cents` 2.00 x 1150 = 2300, gap **1400**, cap `subtotal_cents` 4500 (box packed first) does not bind; accumulated `credit_cents` = **1400 < 4500 = `charged_cents`, strictly** — and it is the *first* credit, not a second — so `PARTIALLY_CREDITED` holds under either reading. Site 1 (`routes/lots.py:265`, DISCOUNT disposition) is reached only via `_discounted_lot_with_held_statement`, whose lot is never allocated or split and therefore carries **zero deliveries**; the credit loop body never executes.

**Friction 10 — CLEAN.** Across all 14 `log_leg` call sites in the suite, **every one precedes its `disposition_lot`**. No test logs a leg against an already-dispositioned lot, so `routes/lots.py:366`'s `and lot["quality_status"] == "CLEAR"` guard is never the deciding clause.

## C. Near-miss register — tests fair only by accident

Graded by **distance** = number of changes that would flip them onto a contested reading.

| Grade | Test | Why it is fair only by accident |
|---|---|---|
| **1 — sharpest** | `test_09::_discounted_lot_with_held_statement` (both discount tests) | Creates the statement **before** the breach, so it is `PROVISIONAL -> HELD` and finalizes legally. Swapping two lines (breach + `DISCOUNT` first, statement second) lands exactly in reachability trap #1 and finalize returns `ERR_INVALID_STATE`. One line move. |
| **1** | `test_09::test_a_recall_walks_the_lot_forward...` | Omits `billing_status` on the voided box. One added assertion makes it depend on friction 6. |
| **1** | same test | The sub-lot is `ARRIVED` only because one box is deliberately left uncollected. One extra `pickup_delivery` -> sub-lot `CONSUMED` -> hop two finds nothing -> all four counts collapse to 0. |
| **1** | `test_05::test_a_below_value_substitution...` | `pack_the_box=True` is load-bearing: without it `subtotal_cents` is 0 and a literal reading of §3.5's cap zeroes `member_credit_cents`. One kwarg. |
| **1** | `test_02::test_installment_and_prepaid_commitments_diverge...` | Reads pre-activation and asserts only `commitment_cents`. One added `promised_delivery_count` assertion -> depends on friction 2. |
| **1** | `test_09::test_gross_pay_is_the_ex_vessel_line...` | `8534`/`602` are not a PRD-verbatim pair; they hold because `setup_fleet` picks `HOOK_AND_LINE` (base 90 >= GREEN min 80, factor 1.00). One gear change alters `premium_cents`. |
| **1** | any cold-chain test | All 14 `log_leg` calls happen before their disposition. Moving one after -> depends on friction 10. |
| **2** | `test_09::test_a_recall_walks_the_lot_forward...` | Adding a no-show box (machinery already exists in test_07) to the recalled sub-lot engages friction 5. |
| **far** | — | Frictions 3, 4 and 8 need entirely new tests (transfer accept / preference update); no existing test is one edit away. |

## D. Reachability hypotheses — all four **CONFIRMED**, one with a correction

1. **Post-disposition statement stranded in `PROVISIONAL` — CONFIRMED, with a correction to the impl's own account.** Creation stamps `PROVISIONAL` unconditionally (`vessels.py:369`; only the trip's `VERIFIED` status and the version guard are checked — the lot's `quality_status` is never consulted). The sole entry into `HELD` (`lots.py:366`) requires the breach to also move the lot `CLEAR -> HOLD`, and `DISCOUNTED`/`DISCARDED` are terminal (disposition demands `HOLD`, `lots.py:228`), so a post-disposition statement can never be promoted. Reachable sequence: land -> verify -> breach -> `DISCOUNT` -> create settlement -> finalize. **Correction: the error is `ERR_INVALID_STATE` (409), not `ERR_HOLDBACK_NOT_CLEARED`** — rung 52 passes because quality is `DISCOUNTED`, not `HOLD`, and the `PROVISIONAL` branch's `state_in(("CLEAR","RELEASED"))` is what fails. This faithfully mirrors PRD:396, which enumerates only two (status, quality) pairs. Spec gap, not impl deviation.
2. **`SUSPENDED` QuotaLedger unreachable at rung 36 — CONFIRMED.** Rung 27 (`guards.vessel_not_suspended`, `vessels.py:235`) fires 18 lines before rung 36 (`vessels.py:253`). The only writer of `SUSPENDED` onto a ledger (`vessels.py:65-71`) requires the vessel to be moving to `SUSPENDED`, and the only exit (`vessels.py:72-77`) clears every suspended ledger on the way out — so `ledger.status == "SUSPENDED"` strictly implies `vessel.compliance_status == "SUSPENDED"`. The vessel<->ledger identity is enforced at trip creation (`vessels.py:173`), so no other vessel's ledger can be smuggled in. The suggested "create trip -> suspend -> land" ordering returns `ERR_VESSEL_SUSPENDED` (403) at rung 27. The `EXHAUSTED` disjunct is live; the `SUSPENDED` disjunct is **PRD-mandated dead code**.
3. **Short-fill spread uncapped — CONFIRMED, with worked arithmetic.** `calc.py:150-171`: the normal branch applies `min(..., s["target"])`; the short-fill spread does not, and the residue pass only ever adds. Concrete case — one `LARGE` (3 units, target 7.50, floor 3.00) and one `SMALL` (1 unit, target 2.50, floor 1.00), pool **2.60 lb**. Exact shares 1.95 / 0.65; 1.95 < 3.00 -> SHORT_FILL. Floor walk: `LARGE` floor 3.00 > 2.60 unassigned -> 0.00, not added to `floored`; `SMALL` floor 1.00 <= 2.60 -> 1.00, unassigned 1.60. Spread over `floored` alone: `units2 = 1`, extra = 1.60 -> **SMALL = 2.60 vs its 2.50 target, 0.10 lb over**. Verified by executing `calc.catch_allocation` directly (pool 2.99 -> 2.99, **19.6 % over target**); the normal-branch control at pool 18.00 correctly caps at 7.50/2.50. Matches PRD:296, whose short-fill sentence says only "truncated downward" — the capping clause lives solely in the normal-fill sentence at PRD:294.
4. **Undeclared error for a missing cold-chain event — CONFIRMED.** `lots.py:376-381` returns `ERR_LANDING_LOT_NOT_FOUND` and bypasses `lookup.landing_lot`. The PRD genuinely declares nothing: all 21 not-found rungs (PRD:98-112) name specific entities and none is a cold-chain event; rung 14 is scoped to "the landing lot named in the path or in a `landing_lot_id`...body field", and this route's `{id}` is a ColdChainEvent id; §5's 15 `*_NOT_FOUND` codes have no entry. **This is the only one of the four where the impl invents behaviour the PRD does not describe.** No test reaches it — `get_cold_chain_event` is among the 14 uncalled client methods.

## E. Assertion hygiene — **PASS, 0 violations on all four checks**

- **Field names:** all 174 distinct response keys asserted across `test_suite/` + `assertions.py` appear verbatim **inside backticks** in PRD.md. The 36 non-matching keys are all local ctx/header keys (`lot_id`, `admin_headers`, ...), correctly out of scope.
- **Numeric literals:** every equality/approx literal is either PRD-verbatim (9136 / 2174 / 914 / 6048 / 6962 / 6505, 4500 / 4140 / 45000 / 82800, 41400 / 38900 / 2500, 2.39 / 3.60 / 2.66 / 4.01 / 1.33, 6250 / 6950 / 6750) or reconstructible in one short chain (4092 = 2400x1.55x1.10; 3960/19800; 8534+602=9136; cold-chain 41/21/6.5; `cutoff_at` = start + 14 d - 72 h; 18000 = 4x4500). **Nothing copied off an implementation run.**
- **Instants:** all four timestamp comparisons (`scheduled_at`, `cutoff_at` x2, `true_up_run_at`) route through `assert_same_instant`. A targeted grep for raw `["*_at"] ==` string compares returns nothing.
- **List indices:** only two index expressions exist (`sub_lots_of(...)[0]` at test_04:374 and test_09:335), both preceded by a **single-destination** split, so the list has exactly one row and carries no ordering assumption. All multi-row assertions are deliberately order-independent (`sorted()`, dict-keyed by `destination_type`, `for row in rows`). PRD:74 does state `created_at` ascending as the default anyway.

**Two hygiene observations worth passing on (not defects, no action taken):**
1. **`assert_cents` is defined but never called.** It is the only place enforcing "money fields hold a whole number of cents" (`isinstance(actual, int) and not isinstance(actual, bool)`). Because it is dead, an implementation returning `4500.0` or `"4500"` for a `_cents` field would satisfy every money assertion in the suite (`4500.0 == 4500`).
2. **14 of 80 endpoints are never exercised** (`accept`/`decline_share_transfer`, `update_member_preferences`, `remediate_recall_notice`, `reject_substitution`, `get`/`list_cold_chain_events`, and 7 list routes), and 14 entity-shape helpers in `assertions.py` are dead — so those entities' UUID/`created_at`/`version` common-field checks never run. This is what buys frictions 3, 4 and 8 their CLEAN verdicts, so it cuts both ways.

**Orchestrator independent re-verification:** all 8 `results.N.json` re-parsed -> 108 individual rows each, `passed=108 failed=0 total=108`, status set exactly `{'passed'}`, sorted-name sha256 `2dfccd7f4fb73e8e` identical across all 8.

## Step 8: Finalize PRD — 2026-08-09T07:26:00.000Z

Ran (not skipped: Step 7 applied 1 `test_suite/` fix, so the zero-fix skip condition did not hold).

Subagent summary (verbatim):

`PRD_FINALIZED.md` produced. Exactly one edit, tracing to the single Step 7 item.

## Line counts
- `PRD.md`: 560 lines
- `PRD_FINALIZED.md`: 560 lines
- Delta: **0 lines (0.0%)** — one line revised in place, no lines added or removed.

## Changes
- **§4 (Endpoint Definitions, preamble)** — *revise* — kept the original 201/200 sentence verbatim and appended a discriminator making the 201-vs-200 test turn on *what the response carries*, not on whether the request created any row; named the three routes that decide the boundary (`trips/{id}/land` = 201, `landing-lots/{id}/splits` = 200, `subscriptions/{id}/activate` = 200) — `implementation/routes/common.py:14` (`created` -> 201) / `common.py:19` (`ok` -> 200), `routes/lots.py:212`, `routes/vessels.py:287`, `routes/subscriptions.py:166`.

## Pre-edit search log
**(a) Subject identified.** Which successful operations return 201 vs 200 — specifically whether a route that materialises child rows while returning an updated parent is a "create".

**(b) Impl paths enumerated.** Full route-by-route status-code census over all 8 blueprints in `implementation/routes/` (`catalog, seasons, members, subscriptions, vessels, lots, deliveries, skips`), plus `common.py`/`envelope.py` to confirm only two status-emitting helpers exist (`created`->201, `ok`/`ok_raw`/`listing`->200).

**17 routes return 201**, each returning the row it just created: `POST` on `/delivery-zones`, `/pickup-hubs`, `/pickup-hubs/{id}/windows`, `/seasons`, `/share-plans`, `/members`, `/subscriptions`, `/vessels`, `/quota-ledgers`, `/trips`, `/trips/{id}/land` (returns the **LandingLot**, not the trip), `/trips/{id}/settlements`, `/cold-chain-events`, `/share-deliveries/{id}/substitutions`, `/skip-requests`, `/share-transfers`, `/recall-notices`.

**Every other route returns 200**, including all GETs, all state-transition POSTs, the two `ok_raw` computed/utility routes (`/subscriptions/{id}/ledger`, `/_clock/set_current_utc`), and — the load-bearing cases — the row-materialising POSTs `/landing-lots/{id}/splits` and `/subscriptions/{id}/activate`.

Cross-checked with an exhaustive `grep` of all 19 `store.create` callsites across `routes/` and `cascades.py`: exactly two creation sites sit under a 200-returning route (`SubLot` in `lots.py`, `ShareDelivery` in `subscriptions.py`). Every other created entity is returned by its own 201 route, so the rule is universal with no residual exceptions.

**(c) Wording adjustment.** Two revisions before committing. First, I discarded a draft phrased as "creating child rows returns 200" — that reads as a rule about side effects and would have mis-described `POST /trips/{id}/land`, which creates a child `LandingLot` under a parent trip and returns **201**. Re-anchored the criterion on the identity of the object placed in `data` instead, which is the invariant the code actually implements via `created(rec)` vs `ok(rec)`. Second, I kept the original sentence intact as the lead rather than replacing it, so the 17 plain-create routes stay governed by prose Step 9 need not re-verify.

## Note on scope
Step 7's single item was a genuine PRD silence, not a fixture bug, so the edit was warranted: the governing sentence, "Creating a new resource returns HTTP 201; every other successful operation returns HTTP 200," does not say which side a route falls on when it both creates rows and returns an updated parent — and §2.2's "the created **or updated** resource object" explicitly admits both readings. The implementation resolves it toward the response object's identity; that resolution is now pinned.

## Step 9: Complete PRD — 2026-08-09T07:43:00.000Z

Subagent summary (verbatim):

## Files
- `workspace/PRD_COMPLETED.md` (written; copied from `PRD_FINALIZED.md`, edited in place)
- Source: 560 lines / 119,902 chars -> Completed: 562 lines / 156,707 chars (**+2 lines, +36,805 chars**). The +2 lines are one added paragraph break in §2.8; no new headings (`grep '^#'` diff of heading text is empty — verified).

## Counts
**68 edits** — 54 ambiguity-pins, 14 mismatch-revisions.

## Per-probe yield
| Probe | Yield | Highlights |
|---|---|---|
| Q1 does any endpoint consult this field? | 9 | `Season.end_date` required+validated, **never read by any rule**; `Vessel.home_port`, `violation_count` write-only; `Member.credit_balance_cents` accumulates but is never an input; `offered_species` read by exactly one rule (the dislike test) and never gates a landing or a substitute; 6 lot fields write-only |
| Q2 universal quantifiers | 7 | rung 22 does **not** apply to list endpoints (no ownership scoping at all); verify-reject recomputes ledger status only for OPEN/WARNING/EXHAUSTED; three custody roll-ups re-tested only at arrive/deliver/pickup — never at window close, cancel, discard or recall |
| Q3 derived-on-read vs stored | 4 | all nine invariants are stored, never recomputed; the subscription ledger is a projection of 12 stored counters; `slots_free` is the only refreshed derivation |
| Q4 serializer projections | 5 | `store.commit()` runs **before** every projection, so no stale version; ledger and clock responses are bare objects with no `id`/`created_at`/`version` |
| Q5 list semantics | 6 | `limit`/`offset` **clamped, never rejected**; unparseable -> default; tie-break on monotonic insertion sequence; off-enum/unknown filter -> empty page, not 400; filters compared as strings |
| Q6 cascade legs that don't fire | 8 | discard hops 4->5->6 strictly nested and each conditional (`shortfall_flag_count` counts subscriptions, not boxes); recall hop 3 walks **all** sub-lots, not only those hop 2 moved; no-show `CHARGED->FORFEITED` conditional |
| Q7 version ledger | 4 | **once per request**, not per mutation step — determined empirically from `store.touch`/`commit`; rows created in the request stay at 1; landing bumps the trip, so first settlement needs `expected_trip_version` 2 |
| Q8 unenforced uniqueness/scope | 6 | `renewed_from_subscription_id` unchecked for member/season; cold-chain `sub_lot_id` unchecked against its lot; split `destination_id` never resolved as a row; duplicate destinations double-claim |
| Q9 error precedence | 11 | rung 45 (not 28) owns the window's status on close; rung 52 splits rung 28 on finalize; rung 36's status half tested first; ~30 rung-28 non-status preconditions enumerated; rung-5/6 boundary on array enums |
| Q10 timestamps | 5 | `api_request_timestamp`, `created_at`, `updated_at` all stamped from the **logical clock**; one uniform renderer over minted/echoed/derived instants; non-UTC offsets normalised; `cutoff_at` frozen at filing |

## Per-lead rulings
- **L1 CONFIRMED** — a statement created after a `DISCOUNT`/`DISCARD` is born `PROVISIONAL`, can never reach `HELD`, and every finalize answers **`ERR_INVALID_STATE` (409)**, not `ERR_HOLDBACK_NOT_CLEARED`. Pinned in rung 52 and §3.9; the two reachable pairings enumerated.
- **L2 CONFIRMED** — the `SUSPENDED` disjunct at rung 36 is dead: a ledger is `SUSPENDED` only when its vessel is, and rung 27 fires first. Pinned as unreachable.
- **L3 CONFIRMED** — the short-fill spread is **uncapped**; the worked case (LARGE floor 3.00 + SMALL floor 1.00 over 2.60 lb -> SMALL = 2.60, 0.10 over target) is now in the PRD. Also pinned: the short-branch residue pass skips the empty boxes.
- **L4 CONFIRMED** — `GET /csf/cold-chain-events/{id}` on a missing id returns **`ERR_LANDING_LOT_NOT_FOUND` (404)**. All other list/read routes use their declared codes.
- **L5 CONFIRMED** — the cap reads `Subscription.price_per_delivery_cents`, not the stored `subtotal_cents`. Revised inline (mismatch).
- **L6 CONFIRMED** — `delivered_count` increments on **both** deliver and pickup. Revised inline (mismatch).
- **L7 CONFIRMED** — pack enforces `ERR_PAYMENT_REQUIRED`; rung 30's list extended to four sites.
- **L8 all ten frictions verified against code** (6 carried `# Adjudication of friction N:` comments; frictions 1, 2, 3/4 were verified from surrounding code): 1 dock fee 800 (already pinned, no edit); 2 written at creation; 3 re-parented only; 4 no parity re-anchoring; 5 `REFUNDED`/`FORFEITED` visited, counted, credited 0, **no axis moves at all**; 6 recall-voided money axis untouched; 7 four deduction lines (already pinned); 8 `standing_reset` by a `Member` -> `ERR_UNAUTHORIZED`, only when true; 9 credit >= `charged_cents` still `PARTIALLY_CREDITED` (both sites); 10 breach on a non-`CLEAR` lot leaves quality **and** settlement axes alone, roll-ups and `breach_type` still written.
- **Ordering/id note CONFIRMED** — ids are monotonic in the high bits, `store.ordered` sorts `(created_at, _seq)`. Pinned in §2.3, §2.4 and §3.4's fixed order.

(Full 68-bullet per-change list is in the Step 9 subagent transcript; the notable ones span §2.1-§2.9, §3.1-§3.9 and every edit cites an `impl file:line`.)

---

# FINAL ORCHESTRATOR VERIFICATION — 2026-08-09T07:45:00.000Z

- `results.{1..8}.json`: 108 individual rows each, `passed=108 failed=0 total=108`, status set exactly `{'passed'}`, sorted-name sha256 `2dfccd7f4fb73e8e` identical across all 8. Step 7 additionally ran a second 8-round sweep (16 rounds total), same result.
- PRD line/char ledger: `PRD.md` 560 / 119,177 -> `PRD_FINALIZED.md` 560 / 119,902 -> `PRD_COMPLETED.md` 562 / 156,707.
- `diff` of `^#` headings PRD.md vs PRD_COMPLETED.md: **identical** — Step 9 added no sections.
- `find implementation test_suite test_helpers -newer results.1.json -name '*.py' -o -name '*.sh'`: **empty** — Steps 8 and 9 touched no code.
- Independent route diff comparing **(method, path) pairs** (not paths alone): scaffold 80 / live 81, **0 MISSING**, 1 EXTRA = Flask's `GET /static/{}`.
- `def test_` 108 == `Design:` tags 108; zero `pytest.mark.skip|xfail|skipif`.
- Isolation: `grep -rIl "test_suite\|test_helpers" implementation/` empty; `grep -rIl "workspace/implementation" test_suite/ test_helpers/` empty.

**RESULT: 108/108 x16 rounds, 0 tests deleted, 0 implementation fixes, 1 test_suite fix.**

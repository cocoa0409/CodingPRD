# Worklog — task_0952_diaper_baby_essentials_subscription

Scenario (verbatim): 952. Diaper & Baby-Essentials Subscription: plan & size/stage, recurring cadence & auto-resize, delivery & skip, registry & gift, points/loyalty, sensitive-skin/allergy, pause/cancel, referral

Requested difficulty: **harder than Expert** (beyond-Expert band).

## Step 1: Create task directory — 2026-08-09T00:00:00.000Z

Created `tasks/task_0952_diaper_baby_essentials_subscription/` and `workspace/`. Index 0952 = highest existing (0951) + 1.

## Step 2: Generate scaffold — 2026-08-09T16:20:00.000Z

Orchestrator independent verification: all three files `yaml.safe_load` clean; entities 21 · state_machines 17 · calculations 41 · validations 71 · endpoints 116 · errors 99 · roles 6 · conservation_invariants 4 · concurrency_rules 2 · domain_constants 80 · §1.8 instances 27 · §1.9 instances 140 (140 unique names, 0 dupes). SCAFFOLD.yaml 5113 lines / CORNER 6878 / DIFFICULTY 2320.

Subagent summary (verbatim):

All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_0952_diaper_baby_essentials_subscription/`.

## Scale (all targets met or exceeded)

| Dimension | Count |
|---|---|
| Entities | **21** |
| State machines | **17** (12 non-linear) |
| Calculations | **41** (8 dual-variant) |
| Validations | **71 rungs**, one numbered ladder |
| Endpoints | **116** |
| Error codes | **99** |
| Roles | **6** (Anonymous, AccountHolder, RegistryOwner, GiftPurchaser, SupportAgent, OpsAdmin) |
| Constants declared | **80** (0 undeclared) |
| Cascade depth | **6** (plus two depth-5 chains from different triggers) |
| `gate_precedence` gates | **9** (total order G1_AUTH → G9_POLICY_FISCAL) |
| Conservation invariants | **4** |
| OCC rules | **2** |
| §1.8 instances | **27** (9 rules × 3, 3, 3, 3, 3, 4, 3, 2, 3) |
| §1.9 instances | **140 non-stub**, 0 stubs |

**Non-linear state machines (12):** Account (ACTIVE↔SUSPENDED cycle) · Subscription.lifecycle (ACTIVE↔PAUSED) · Subscription.billing (parallel axis, CURRENT↔PAST_DUE↔DELINQUENT) · Child.stage (bidirectional adjacent-only ladder) · Cycle.status (SKIPPED→PLANNED re-entry) · Cycle.payment_status (parallel axis + FULLY_COVERED→UNCHARGED back-edge) · CycleLine (capped 3-attempt retry loop) · Registry (CLOSED↔OPEN, cap 1) · RegistryItem (FULFILLED→PARTIALLY_FULFILLED→REQUESTED back-edges) · GiftOrder (CREDIT/ITEM fork with divergent side-effect sets) · Credit (CONSUMED→PARTIALLY_CONSUMED→AVAILABLE restoration) · Shipment (IN_TRANSIT↔EXCEPTION, cap 2).

**Dual-variant calculations (8):** `cadence_interval_days`, `tier_evaluation`, `cancel_refund_cents`, `credit_restoration_on_refund`, `resize_target_cycle`, `gift_order_total_cents`, `referral_credit_amount_cents`, `next_charge_estimate_cents`.

**Structural device:** Pipeline R (cycle) and Pipeline G (registry/gift) share the pricing, credit-stack, allergen-screen, substitution and shipping rungs, and diverge on cutoff semantics, refund actor, proration, points eligibility and auto-resize — each divergence is called out inline in `complexity_profile.structural_device` and re-asserted at the rung that implements it.

## §1.9 coverage

| Section | Non-stub |
|---|---|
| entities | 16 |
| state_machines | 25 |
| calculations | 14 |
| errors | 29 |
| validations | 23 |
| rbac | 12 |
| cross_cutting_layers | 7 |
| endpoints | 11 |
| consistency_model | 3 |
| **total** | **140** |

Surface coverage: **errors 99/99 (100 %)**, **validations 71/71 (100 %)**, **calculations 41/41 (100 %)**, **endpoints 116/116 (100 %)**. All nine claim-extraction sections represented.

## Verification

- `yaml.safe_load` — **OK** on all three files (offenders fixed: bare `field?` in flow sequences, `$.data[0].id` in flow mappings, `validations[priority=N]` in flow sequences — all quoted).
- Undeclared-constant sweep — **80 declared, 0 unresolved ALL_CAPS tokens.**
- Placeholder closure — **0 unbound `${var}`** across 1 651 calls; **0 duplicate instance names** across 167.
- `scaffold_lint.py` verdict, verbatim:

```
Coverage
  §1.5 endpoints declared:    116
  §1.1 entities declared:     21
  §1.8 instances scanned:     27
  §1.9 instances scanned:     140
  Calls scanned (§1.8+§1.9):  1651

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Free downstream intelligence

**Reachability dead-ends found and repaired while writing chains:**

1. `ERR_CYCLE_WINDOW_OVERLAP` was structurally **unreachable** — anchor-based generation can never produce overlapping windows. Only path found: generate → skip → generate → revoke-skip (rewinds the anchor behind an existing cycle) → generate → generate. Pinned in `corner_cycle_window_overlap_after_skip_revoke_rewinds_anchor`; there is no other route.
2. `ERR_CREDIT_EXPIRED` was unreachable because the credit pool already filters `expires_at > now`. Added an optional `credit_ids` input to `POST /cycles/{id}/charge` so a *named* expired credit is a hard error.
3. `ERR_GIFT_PURCHASER_SCOPE` and `ERR_CATALOG_WRITE_FORBIDDEN` were dominated by the generic `ERR_FORBIDDEN_ROLE`. **Reordered G2** so the two specific rungs are priorities 3 and 4 and the catch-all is 5.
4. `ERR_PIPELINE_G_REFUND_ACTOR` was dominated by a routing 403 — added `RegistryOwner` to the roles of `POST /gift-orders/{id}/refund` so the refusal is a *business* decision, not a routing accident.
5. `ERR_PIPELINE_R_REFUND_ACTOR` was dominated by the ownership rung; redefined as a **reason-scope** rule (an AccountHolder may not cite `GIFT_REFUND`/`GOODWILL`).
6. `ERR_REFERRAL_CAP_EXCEEDED` enforced at *vesting* could never surface in a response (vesting is a side effect). Moved to **creation time** on `POST /referrals`.
7. `ERR_CYCLE_SUBSCRIPTION_MISMATCH` had no endpoint carrying both a subscription id and a cycle id. Replaced with a reachable referential rung, `ERR_SKU_DISCONTINUED` on `POST /registries/{id}/items`.
8. `ResizeEvent.reject_reason` originally declared four members; **three were dead** (`CAP_EXCEEDED`, `NON_ADJACENT`, `NO_TARGET_CYCLE`) because their rungs reject the whole request rather than persisting an event. Narrowed to the single producible value `STAGE_PINNED`.
9. `CYCLE_LEAD_DAYS: 7` had to be introduced: with `anchor_date = activation instant`, every first cycle's cutoff (`ship − 48h`) is already in the past, making *every* skip/revoke corner unreachable.

**Un-prejudged frictions and traps left deliberately in place (do not smooth these over downstream):**

- **Mutate-then-reject (declared, single instance):** `POST /cycles/{id}/charge` with no payment method returns **402 AND** moves `billing_state` CURRENT→PAST_DUE. It is the only rung in the ladder that leaves a trace on rejection; it is also the only way to reach `DELINQUENT`.
- **Deliberate asymmetry:** rung 49 (stage pinned) *records the weight* and writes a REJECTED event with no error from `weight-measurements`; rung 50 (resize cap) *rejects the whole request*. Same endpoint, opposite semantics.
- **`substitution_attempts == 3` is an absorbing state:** the line sits in `SUBSTITUTION_PENDING` forever — it cannot substitute (rung 54) and cannot short-fill either, because SHORT_FILL also runs through `POST /cycle-lines/{id}/substitute`. This is a genuine terminal-ish trap, declared but worth watching in Step 6/7.
- **Per-line promo rounding is only observable with ≥2 lines**, which requires the waterfall to split across two SKUs (top-ranked stocked at 1 pack). An implementation that "optimises" to a single line silently passes the wrong arithmetic.
- **Referral-credit cap reads the ORIGINAL base**, not the post-gift remainder — the two readings differ by 500 cents in the worked example, and only the stack-order test distinguishes them.
- **The loyalty floor applies twice** (to the balance *and* to the redeemable amount): a 500-point balance against a 420-cent cap redeems 0, not 420.
- **`Cycle.payment_status` FULLY_COVERED→UNCHARGED has no direct endpoint** — it fires only as hop 4 of the gift-refund cascade.
- **`GiftOrder` CLAIMED_CREDIT→FULFILLED requires the derived Credit to reach exactly `CONSUMED`**; a partial consumption leaves the gift order in CLAIMED_CREDIT indefinitely.
- **Ordering sensitivity:** `POST /cycles/{id}/return` sets the linked shipment to RETURNED, but a shipment already returned via `POST /shipments/{id}/return` will hit terminal lockdown if the calls arrive in the other order.
- **Pause budget hole (declared, not fixed):** only ACTIVE/ENDED pauses consume days, so many SCHEDULED pauses summing past 90 days can be booked and are only blocked as each activates.
- **`ERR_ACCOUNT_NOT_ACTIVE` is overloaded** — it also carries "the account is not in the state this endpoint requires" (e.g. suspending a PENDING_VERIFICATION account), which reads backwards.
- `POST /accounts/{id}/verify` **consumes** the token (sets it to null); replay observability depends on that side effect surviving PRD generation.

## Step 3: Copy shared files — 2026-08-09T16:21:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-09T16:36:00.000Z

Subagent summary (verbatim):

PRD generated at `.../workspace/PRD.md` — **681 lines**. Neither withheld design file was opened; no sibling task directory was read.

## Coverage diff (all zero-missing)

- **endpoints 116/116** (method+path matched against the §4 table)
- **errors 99/99** (each appears in prose backticks *and* in the §5 table)
- **calculations 41/41** (walked by name against the scaffold list; each formula rendered as prose with its constants, evaluation order, precision and every declared variant)
- **rungs 71/71** (each priority's check + `error_id` + `applies_to` scope expressed; gate order and intra-gate precedence stated in §2.6)
- **constants 80/80** (every value present in business context)
- fields: `entities[].fields` 141/141, `endpoints[].input` 76/76, `endpoints[].output` keys 33/33
- §3 path purity: 1345 backtick tokens scanned, 0 violations
- §2.2 verified byte-identical to `section-2.2-response-structure.md`

## Sections written

§1 Introduction · §2.1–2.12 (roles/identity, verbatim envelope, pagination, id/timestamp/version, logical clock, the nine-gate write order, OCC, rounding, the four conservation invariants, nested existence resolution, request shape, pipeline divergences) · §3.1–3.11 (households → children & size ladder → catalog → subscriptions/cadence/pause → cycle generation/allocation/skip → re-screen & substitution ladder → pricing & charging & credit ledger → dispatch/carriage/delivery cascade → registry & gifting → cancellation/refund/settlement → referrals/loyalty/daily batch) · §4 endpoint table · §5 error table. No audit footer.

## Scaffold frictions carried forward as-is (not silently resolved)

1. **`CREDIT_AUTOAPPLY_THRESHOLD_CENTS` (1000) is an orphan.** Declared in `domain_constants`, referenced by no calculation, validation, entity field or endpoint. I state its value and add that no rung rejects or alters a charge on account of it. (§3.7.)
2. **Referral cap: vesting precondition vs creation-time enforcement contradict.** The `Referral` PENDING→VESTED transition declares a trailing-365-day vested-count precondition, while rung 61's note pins the cap at creation and says "vesting itself never fails on this rung." Both rendered adjacently in §3.11 without adjudication.
3. **`ResizeEvent.reject_reason` has exactly one reachable member by construction** — rendered as stated, including the reasoning.
4. **`ERR_PIPELINE_R_REFUND_ACTOR` has two incompatible descriptions.** Rung 15 = an AccountHolder citing `GIFT_REFUND`/`GOODWILL`; the §1.6 catalogue = "a cancel or return by an identity that is neither the owning AccountHolder nor OpsAdmin." I rendered the rung-15 reading and did not merge the catalogue gloss.

## Step 5: Generate unit tests — 2026-08-09T17:10:00.000Z

Orchestrator verification: 195 `def test_` across 18 files; 0 skip/xfail markers (only domain `skip` vocabulary).

Subagent summary (verbatim):

Test infrastructure and suite complete.

## Output

`test_helpers/` (9 modules) and `test_suite/` (conftest + 18 test files).

## Verification performed

- **195 tests collect cleanly** (`pytest --collect-only`), all 18 modules import.
- **Coverage audit passes**: queue A 27/27 instances with ≥2 tests each (55 tests); queue B 140/140 non-stub instances with ≥1 test each (140 tests). Zero untagged, zero dual-tagged, zero dangling `Design:` pointers.
- **Verbatim citation audit passes**: all 344 `PRD §x: "…"` quotations survive a whitespace-normalised literal match against `PRD.md`; every test carries at least one ≥8-word rule-bearing citation.
- No `skip`/`skipif`/`xfail` anywhere; no scaffold references in generated code; pyflakes clean.
- `assert_same_instant` / `instant_plus` parse both sides before comparing — every timestamp assertion is semantic.
- Identity discipline: `make_account_holder_headers` / `make_registry_owner_headers` / `make_gift_purchaser_headers` are threaded with the real `Account.id`; `setup_registry_parties` always builds **two distinct** accounts (owner ≠ purchaser), and gift/subscription fixtures never share an `X-User-ID` across the three roles.

# SUMMARY (Part C input for Step 8)

## Totals
- **Tests emitted: 195.** Queue A translated **27/27** (55 tests). Queue B translated **140/140** (140 tests). **Zero instances skipped.**

## Skipped instances
**None.** Every instance in both indices passed the PRD-first two-condition filter.

## Sub-assertions dropped from instances that were kept

1. **`Difficulty/transitive_cascade/gift_refund_cascade_revokes_credit_and_uncovers_cycle`** — dropped `Credit.consumed_cents == 0` and `Credit.forfeited_cents == 3600`. PRD hop two moves `remaining_cents` into `forfeited_cents` (601), hop three reverses only the cycle's `gift_credit_applied_cents`; two faithful readers land on (2999/601) vs (0/3600). Replaced with `issued_cents == 3600`, `remaining_cents == 0` and the §2.9 conservation identity, which hold under both.
2. **`Corner/endpoints/corner_registry_summary_computed_read`** — dropped `inflight_gift_count == 1`. §3.9 pins recomputation only at close and at gift refund; the registry here is OPEN, so echo-stored → 0 vs fully-computed → 1.
3. **`Difficulty/boundary_precision_check/redemption_exactly_at_points_floor_is_accepted`** — restructured: the instance's 499-request would trip both the floor rung and the insufficient-balance rung with no declared precedence. Split into 500-accepted and 499-refused-against-a-500-balance so only the floor rung can fire.

## Near-miss register — HYPOTHESES, verify by reading the implementation

| # | Test / instance | PRD sentence | Alternate faithful reading | Distance |
|---|---|---|---|---|
| N1 | `test_the_stock_adjustment_response_and_the_line_read_agree_immediately` — asserts `Cycle.subtotal_cents == 2400` after the line is pushed to SUBSTITUTION_PENDING | §3.5 subtotal = sum of `line_total_cents` over lines whose status is ALLOCATED or SUBSTITUTED; §3.3 stock adjustment names no repricing | derived-on-read returns **0** (a SUBSTITUTION_PENDING line is in neither status) | **Very close — riskiest assertion in the suite** |
| N2 | `test_a_gift_against_an_already_fulfilled_item_is_refused` | §3.9 four policy checks | item is FULFILLED *and* qty > remaining; precedence rests only on prose enumeration order | Close |
| N3 | `test_a_paused_household_with_allowance_left_reports_the_pause_refusal` | §3.5 states the order explicitly | none | Far |
| N4 | `test_the_conservative_estimate_ignores_credits_and_the_points_balance` — `include_credits` as query string `"false"` | §3.1 "supplied as false" | query-string boolean encoding unstated | Close (encoding) |
| N5 | selector tie-break + the two promo-rounding tests | §3.5 "ties broken by ascending `created_at`" | identical `created_at` under the logical clock determines nothing. **Mitigated** by advancing the clock between SKU creations | Far after mitigation |
| N6 | `test_a_named_expired_credit_is_refused_at_charge_time` | §3.7 charge preconditions name no temporal gate | an impl adding one would 409 first | Moderate |
| N7 | `test_the_registry_summary_reports_the_fulfilment_progress` — `completion_pct == 0.6667` | §2.8 four-dp half-up | representation (`0.6667` vs `0.66670` vs string) | Moderate |
| N8 | `tier_multiplier_applied == 1.00` coerced with `float()` | §3.8 "1.00 for BRONZE" | `1.0` vs `"1.00"` — mitigated | Far |
| N9 | `test_the_cycles_own_axis_was_chargeable_all_along` | §3.7 status set | none material | Far |
| N10 | `test_an_over_subtraction_floors_the_stock_at_zero_and_still_queues_the_line` | §3.3 | no divergence | Far |

## Adjudication of the 10 flagged friction points

1 mutate-then-reject — **KEPT in full** (§3.7 states it verbatim as "the single declared exception"; test asserts both the 402 and the billing move).
2 weight-measurement asymmetry — **KEPT, both halves** (§3.2 spells out both branches).
3 `substitution_attempts == 3` absorbing — **KEPT** (§3.6; test asserts the 409 and that the line stays SUBSTITUTION_PENDING with 3 events).
4 per-line promo rounding — **KEPT** (§3.7 worked example pins 304; two-line fixture forced, SKU `created_at` separated).
5 referral cap reads the ORIGINAL base — **KEPT** (§3.7 says so explicitly; 1500 not 1000).
6 loyalty floor twice — **KEPT** (§3.7; 420-cent cap → both fields 0).
7 FULLY_COVERED→UNCHARGED via cascade hop 4 only — **KEPT**, no direct endpoint invented.
8 referral cap vesting vs creation — **KEPT, creation reading only**; the PRD adjudicates itself in §3.11 and repeats it in §3.1. No vesting-time cap test.
9 `ERR_PIPELINE_R_REFUND_ACTOR` — **KEPT, reason-scope reading only**; §5 carries no trigger conditions, so the actor reading has no prose behind it. **The actor reading is untested — the §5 gloss is dead prose.**
10 `CREDIT_AUTOAPPLY_THRESHOLD_CENTS` — **NOT ASSERTED, correctly**; §3.7 declares it inert.

## Additional observations routed into Step 8

- The `ERR_PIPELINE_R_REFUND_ACTOR` §4 gloss leaks a scaffold priority number ("validation priority 16") into the contract.
- `ERR_CREDIT_NOT_AVAILABLE` on the named-credit charge path is stated in §3.7 but no design instance exercises it.
- `GOODWILL` as an OpsAdmin refund reason and the OpsAdmin `POST /cycles/{id}/refund-requests` path are declared but untargeted.
- `ERR_VALUE_OUT_OF_RANGE` is exercised at one site only (`weight_grams`); seven other declared ranges have no instance.
- `ERR_INVALID_ENUM` is exercised at one of eleven declared fields (SKU `stage`).

## Step 6: Generate implementation — 2026-08-09T17:10:00.000Z

Orchestrator verification: independent (method, path) route diff with parameter names normalised — declared 116 / implemented 116 / MISSING 0 / EXTRA 0. `grep sqlite|pickle|json.dump|/tmp` over the impl tree: empty. 5,080 Python lines.

Subagent summary (verbatim):

Implementation complete and verified.

## 1. Modules and line counts (5,080 lines total)

`app.py` 96 (Flask app, error handlers, bounded pre-bind + `make_server(fd=)`) · `store.py` 190 (in-memory dicts, logical clock, id/version/timestamp helpers) · `errors.py` 161 (99-code catalogue + HTTP status map + per-type not-found map) · `envelope.py` 109 · `shapes.py` 152 (gate G4 as four ordered passes; query filters) · `auth.py` 181 (gates G1/G2, existence lookups, ownership rungs 12/13/14) · `constants.py` 125 (all 80 constants) · `calc.py` 296 (Decimal only for money) · `services.py` 981 (pricing, credits, loyalty ledger, allocation, substitution, cascades) · `serialize.py` 171 (21 serializers) · `routes/` 14 files, 2,618 lines, 116 endpoints · `start.sh`, `requirements.txt`.

**Completeness gate: declared 116 / implemented 116 / MISSING 0 / EXTRA 0** — compared as (method, path) PAIRS with `{name}` and `<conv:name>` both normalized to positional `{}`. Restart-churn test: 12/12 immediate kill→relaunch cycles bound successfully. Five smoke suites (~200 assertions incl. a recursive scanner asserting the exact rendering of every `_at`/date field in every response) all pass.

## 2. Timestamp three-case adjudication (verbatim rule)

> **(a) Server-generated stamps** — `created_at`, `updated_at`, `expires_at`, `anchor_date`, `window_start`, `window_end`, `ship_date`, `cutoff_at`, `dispatched_at`, `delivered_at`, `paid_at`, `claimed_at`, `vested_at`, `cancelled_at`, `tier_evaluated_at`, `api_request_timestamp`, and the projections `next_window_start`/`next_window_end`/`next_cutoff_at`: ISO 8601 UTC with **exactly three fractional digits and a trailing `Z`** (`store.fmt_instant`).
> **(b) Caller-supplied values echoed back** — exactly one field: `current_utc` on `POST /_clock/set_current_utc`, echoed **verbatim as supplied** (`store.clock_raw`), forced by the PRD's twice-repeated "the clock reads *exactly* `2026-05-01T00:00:00Z`".
> **(c) Values derived from caller input** — instants derived from the clock or a stored instant follow case (a). Calendar dates derived from caller input (`birth_date`, `start_date`, `end_date`, `actual_end_date`) render `YYYY-MM-DD` and never acquire a time component.

All datetimes are stored as `datetime` and every body passes through `envelope.jsonable`, so **no field can render as an HTTP-date**. `created_at`/`updated_at` are stamped from the **logical clock**, not wall time — mandatory because the skip (180d), auto-resize (90d), referral (365d) and tier (365d) windows compare against it.

## 3. Closed enum-routing rule (verbatim)

> **Exactly these fields route to `ERR_INVALID_ENUM` (422): `Sku.stage`, `Sku.line`, `Sku.status`, `Plan.status`, `AllergenFlag.allergen_tag`, `AllergenFlag.severity`, `Shipment.service_level` (on dispatch and gift claim), `GiftOrder.claim_mode`, `Refund.reason`, `Child.stage` on PATCH, and `target_stage` on resizes. No other field routes here.**
> **Named exclusions**: `credit_type` on `POST /credits` → `ERR_VALUE_OUT_OF_RANGE` (422); every list-endpoint **filter** query parameter → **no error at all**, an unrecognised value simply matches nothing.

## 4. Version observability

`store.touch()` bumps `version` and `updated_at` **in the handler body, before the serializer runs**. No post-handler hook, no `flush()`, no teardown. Confirmed live: the `version` read straight out of a `POST /subscriptions/{id}/activate` body is accepted by the very next `expected_subscription_version` OCC check.

## 5. Every place I had to CHOOSE

1. **Mutate-then-reject** (`routes/cycles.py:charge`) — on `total_due_cents > 0` with no payment method, `billing_state` CURRENT→PAST_DUE + version bump, then 402. The bump happens **only from CURRENT**; cycle, credits and points untouched.
2. **Weight-measurement asymmetry** (`routes/children.py:record_weight`) — pinned: record weight, REJECTED/STAGE_PINNED event, 200. Cap: `ERR_RESIZE_CAP_EXCEEDED`, nothing recorded. A no-stage-change measurement never consults the cap.
3. **`substitution_attempts == 3`** (`routes/lines.py:substitute`) — cap checked on attempt; line stays SUBSTITUTION_PENDING, every further call 409s. The SUBSTITUTED→SUBSTITUTION_PENDING re-flag never consults the cap.
4. **Per-line promo rounding** (`calc.promo_discount`) — per line then summed, no waterfall collapse.
5. **Referral cap reads the ORIGINAL base** (`services.derive_pricing` step 5).
6. **Loyalty floor applied twice** (`calc.loyalty_redemption`).
7. **Referral cap: creation-time only.** The PRD adjudicates itself (§3.11 + §3.1); the SM precondition's vesting-time clause is dead. `services.check_referral_policy` vs `routes/cycles._vest_referral`.
8. **`ERR_PIPELINE_R_REFUND_ACTOR`: rung-15 reason-scope reading.** The catalogue's actor reading is **unreachable** — a non-owner AccountHolder is caught by rung 12 and any other role by rung 5. `routes/cycles.py:open_refund_request`.
9. **`CREDIT_AUTOAPPLY_THRESHOLD_CENTS`** — declared, referenced nowhere, comment cites the PRD sentence pinning it inert.
10. `PointsLedgerEntry` has no not-found code → `GET /points-ledger-entries/{id}` on a bad id returns `ERR_LOYALTY_ACCOUNT_NOT_FOUND`.
11. `api_request_timestamp` uses **real wall-clock**; every business instant uses the logical clock.
12. `POST /subscriptions/{id}/cycles` requires lifecycle ACTIVE; rung 21 (delinquent) checked before rung 22.
13. `POST /accounts/{id}/close` accepts from-states {ACTIVE, SUSPENDED} for **both** roles (union of the two SM transitions).
14. `email` without `@` → `ERR_INVALID_FORMAT` (400), a rung-9 format failure.
15. On verify, **all three** referral policy rungs fail **silently** (PRD states this only for the cap; extended by symmetry).
16. `verification_token`/`referral_code` are opaque server-minted strings; the token is returned on the created resource and nulled at verification.
17. **Subscription for a weight-driven resize**: earliest ACTIVE/PAUSED, else earliest DRAFT, else none — in which case weight and stage still change but **no ResizeEvent row is written**.
18. `APPLIED_CURRENT` re-allocation only rebuilds lines when the current cycle is ALLOCATED.
19. Re-allocation is **best-effort**: if the new stage cannot be filled, previous lines and stock are restored and the measurement still succeeds.
20. `allocate` checks in priority order 22 → 23 → 24 (gate order, not cycle-state-first).
21. **Empty-pool diagnosis**: `ERR_NO_ELIGIBLE_SKU` iff no ACTIVE SKU at the child's stage; otherwise the three safety predicates are analysed ignoring stock (solely-allergen → 45, solely-hypo → 46, solely-plan → 47; else earliest rung with any failure). **Stock exhaustion never produces `ERR_NO_ELIGIBLE_SKU`** — it yields `ERR_SKU_OUT_OF_STOCK`.
22. Substitution rung-1/2/3 filters carry hypoallergenic predicates **in addition** to the declared ones → those two errors are never *raised* by `/substitute`; the line short-fills instead.
23. **Substitution moves no stock** (neither decrement nor return); the rung filters still require `stock_packs >= quantity_packs`.
24. `rescreen` enforces "parent cycle in {PLANNED, ALLOCATED}" as `ERR_CYCLE_STATE_INVALID`; a still-passing line returns 200 with no transition and **no version bump**.
25. The `SubstitutionEvent.reason` is carried as a private `_pending_reason` (OUT_OF_STOCK from stock adjustment, ALLERGEN_RESCREEN from a flag or rescreen), defaulting to ALLERGEN_RESCREEN.
26. `apply_pricing` re-derives the **full nine steps only while payment_status == UNCHARGED**; on a charged cycle it re-derives subtotal/shipping/promo but keeps recorded gift/referral/loyalty applications, so a post-charge substitution cannot double-apply credits.
27. `skip` recomputes the skipped cycle's money to 0 after deleting its lines (PRD silent on the money).
28. **Cancellation refund target snapshot** taken *before* the cascade drives CUTOFF_LOCKED cycles to CANCELLED, so the undispatched variant still applies. "Most recent" = window_start DESC, created_at DESC.
29. `return` opens its RETURN refund **unconditionally**, even when `charged_cash_cents` is 0.
30. A Pipeline-G Refund names the **purchaser's** account in `account_id`, `cycle_id` null.
31. `settle` order: SOD (17,G5) → cycle payment axis (25,G7) → refund status (34,G7) → capacity (71,G9) — SOD beats "refund not APPROVED".
32. **Credit restoration is one-shot**: recorded contributions are consumed on first settlement and cleared.
33. A CLAWBACK entry is written on every Pipeline-R settlement even when `delta_points` is 0.
34. An EARN entry is written on **every** Pipeline-R delivery even when `points_earned` is 0.
35. Cascade hops 4/5 apply when the post-hop-3 tier is SILVER/GOLD; hop 5 re-prices only where `free_shipping_eligible` actually **flipped** false→true.
36. `deliver` treats rung 44 as a **pre-condition gate**: a first delivery whose PENDING referral has passed `expires_at` 409s with `ERR_REFERRAL_WINDOW_EXPIRED` before any mutation. Destructive — flagged as a friction; unreachable once the daily batch has expired the referral.
37. `next_charge_cents` uses the SM-literal non-terminal set (not RETURNED/CANCELLED — so it includes SKIPPED and DELIVERED); `next_charge_estimate_cents` uses the separately-stated {PLANNED, ALLOCATED}.
38. `gift-orders/{id}/pay` enforces rungs 28, 29, 57 in priority order although 29/57 name only `POST /gift-orders` in `applies_to`.
39. Refunding a CLAIMED_ITEM gift whose shipment reached DELIVERED → `ERR_SHIPMENT_STATE_INVALID` (no code is named); effectively unreachable.
40. Registry item create/patch/delete place **no restriction on registry status**.
41. Item delete checks has-gifts (29,G7) before the registry/item mismatch (64,G9).
42. `POST /registries` compares body `owner_account_id` to `X-User-ID` — `ERR_NOT_REGISTRY_OWNER` for RegistryOwner, `ERR_NOT_ACCOUNT_OWNER` for AccountHolder.
43. Pagination parse failures (`limit=abc`, empty) → `ERR_INVALID_PAGINATION` (400).
44. Daily batch: pause promotion `today >= start_date`; pause end `today > end_date` (strict) with `actual_end_date = end_date`; referral expiry strict `now > expires_at`; delinquency strict `now - ship_date > 14d`. Order: credits → points → referrals → promote pauses → end pauses → delinquency.
45. Ownership (G5) is enforced **only on endpoints whose scaffold `gates` key lists G5** — never on a read.
46. `ERR_GIFT_PURCHASER_SCOPE` decided by **path prefix** (`/subscriptions`, `/cycles`, `/cycle-lines`, `/children`, `/pause-records`) per rung 3 verbatim; `/skip-records`, `/resize-events`, `/allergen-flags` are **not** in scope.
47. Unmatched routes → `ERR_ACCOUNT_NOT_FOUND` (404); method-not-allowed → `ERR_FORBIDDEN_ROLE` (403) — the catalogue has no generic member for either.
48. `sequence_number` = count of all existing cycles + 1, including skipped and cancelled.
49. Sorting ties break on a hidden monotonic insertion sequence `_seq`, never on `id`.
50. `registry.completion_pct` is a JSON number rounded half-up to 4 dp; `0.5000` serialises as `0.5`.

## 6. Reachability audit — **HYPOTHESES, verify downstream by reading the code**

- `ERR_HYPOALLERGENIC_REQUIRED` / `ERR_HYPOALLERGENIC_NOT_ALLOWED` **from `/substitute`** — unreachable (candidate filters, so the line short-fills). Reachable from `/allocate` (both) and gift claim (required only).
- `ERR_PIPELINE_R_REFUND_ACTOR` under the **actor** reading — unreachable by construction.
- The **vesting-time** limb of `ERR_REFERRAL_CAP_EXCEEDED` — unreachable.
- `ResizeEvent.reject_reason` values other than STAGE_PINNED — unreachable; `ResizeEvent.status == PROPOSED` never persisted.
- `ResizeEvent.measured_weight_grams` is null exactly on `origin == MANUAL`.
- `ERR_SHIPMENT_STATE_INVALID` from gift refund — believed unreachable.
- `ERR_REFERRAL_WINDOW_EXPIRED` from `/deliver` — reachable only before the batch expires the referral; likely unexercised.
- Credit back-edges CONSUMED→PARTIALLY_CONSUMED and PARTIALLY_CONSUMED→AVAILABLE are reachable only for `refundable == true` credits via settlement; **GIFT credit can never take them**.
- `Cycle.payment_status` FULLY_COVERED→UNCHARGED only via the gift-refund cascade on a PLANNED/ALLOCATED cycle.
- `CREDIT_AUTOAPPLY_THRESHOLD_CENTS` governs nothing.
- `ERR_CYCLE_PAYMENT_STATE_INVALID` from `/settle` on a Pipeline-G refund is unreachable (no cycle attached).
- `Plan.status == RETIRED` and `Sku.status == DISCONTINUED` are settable via PATCH; RETIRED plans are never filtered out of subscription creation — may be an intended gap.
- `PauseRecord` ENDED via batch vs via `/resume` differ in `actual_end_date`; both reachable.

## 7. Storage confirmation

**No data is seeded.** All 21 collections plus `cycle_credit_contributions` are Python dicts created empty in `store._DB.reset()` at import; no `seed_*` function exists, no module-init populates any collection, the catalog starts empty. **In-memory only** — no SQLite, no file writes, no JSON dump, no `/tmp` cache, no pickle. A fresh `start.sh` invocation wipes every byte of state.

## Step 7: Run tests and iterate — 2026-08-09T18:20:00.000Z

Orchestrator verification: all 8 `results.N.json` parse; **194 rows each, 194 passed, 0 non-pass**; test-name sets identical across all 8 rounds; `def test_` count in `test_suite/` = 194 (matches collected); no `pytest.mark` anywhere.

Subagent summary (verbatim):

All 8 rounds green. Final verification: 8 files parsed, 194 rows each, identical name sets, zero errors.

## Summary

**Iterations:** 1 diagnose-fix-sweep cycle (plus a 1-round smoke check between). Baseline sweep ~9 min (4+4); final sweep 16 min (waves of 2), per-round 206–298 s.

**Saturation:** Baseline sweep's second wave produced 11 scattered `could not be restarted` boot ERRORs across 8 distinct tests, none repeating in wave 1 — textbook saturation (host went from load 4.8 / 4 foreign runners at launch to load 9.8 / later 18 foreign runners). Disproved as real failures two ways: the affected tests passed in other rounds, and a full single round after the fixes ran 194/194 with 0 errors. Remedy was to turn the concurrency knob down (`sweep.sh` now runs 4 waves of 2), not the boot timeout up — the final sweep had 0 boot errors.

**Tests deleted (1):**
- `test_16_roles_scope_and_ownership.py::test_one_household_may_not_read_another_households_child` (design instance `Corner/rbac/corner_account_holder_cannot_read_another_households_child`) — **STEP 1b, ownership-site silence.** §2.1 states how an ownership check compares and which error a mismatch raises, but never names a *read* as a check site; §2.6 places Ownership as gate 5 of "The Nine-Gate Write Order" ("Every mutating request walks the same nine gates") and illustrates it with a mutation. §4 is declared "a routing summary only … the roles permitted to call it", and the §3 "readable by …" glosses are role-list restatements — proven by §3.9's registry gloss, which enumerates exactly the five roles §4 lists and explicitly includes a non-owner ("gift purchasers browsing for something to buy"). A rationale comment replaces the test in-file.

**Fixes to `test_suite/`:** none beyond the deletion. **Fixes to `test_helpers/`:** none.

**Fixes to `implementation/` (all in `services.py`):**
1. `allocate_cycle` — the `stage_at_allocation` freeze now happens *after* `build_lines` succeeds. It was written before the selector ran, so a rejected allocation left a trace, violating §2.6's single-exception rule and §3.5's "it stays null while the cycle is still `PLANNED`".
2. `apply_pricing` — added `rederive_credits` (default False). The full nine-step §3.7 stack is now re-derived only where the PRD cross-references §3.7 (allocation, re-allocation; charge/preview call `derive_pricing` directly). Every other site names its fields exactly — §3.6 short fill "subtotal_cents and total_due_cents", §3.6 substitution hop four, §3.8 hop five "shipping_cents … to 0 and its total_due_cents … accordingly" — and none names a credit-application field, so recorded applications now carry through untouched.
3. `allocate_cycle` / `reallocate_cycle` pass `rederive_credits=True`.

Fix 2 resolved two failures from one defect: the short-fill cycle was applying 300 ¢ of the SHORT_FILL credit it had just issued to the very same box (599 → 299), and cascade hop five was newly applying a 720 ¢ loyalty redemption that no hop causes (2400 → 1680).

**High-risk sites:** none of the flagged sites (N1, N2, N4, N6, N7, the hypoallergenic-unreachability hypothesis) failed in any round — N1's `subtotal_cents == 2400` passed throughout and was unaffected, since the stock-adjustment path does not re-price. All eight declared friction points were left intact.

## Step 8: Finalize PRD — 2026-08-09T18:40:00.000Z

Diff handed over in three parts: A = Step-7 fixes, B = impl-gen's 50 self-reported generation-time resolutions + reachability claims, C = test-gen's 3 dropped sub-assertions + the N1–N10 near-miss register.

Subagent summary (verbatim):

`PRD_FINALIZED.md` is written.

## Line counts
`PRD.md` 681 lines / 128,506 chars → `PRD_FINALIZED.md` 687 lines / 146,683 chars. **+6 lines (+0.9 %), +14.1 % by character.** 43 hunks touched (39 revisions in place, 4 insertions); no section added or removed.

## Changes (section — kind — what — impl anchor)

1. §2.2 — revise — `api_request_timestamp` is the one instant taken from real wall-clock, not the logical clock — envelope.py:24 → store.py:144.
2. §2.3 — revise — non-numeric / empty `limit`/`offset` also report `ERR_INVALID_PAGINATION` — envelope.py:77-86.
3. §2.3 — revise — ties on every named sort key break on write order (ascending → first written first); `id` never a key — store.py:181, calc.py:130,163.
4. §2.3 — revise — an undeclared filter value is not an error, it matches nothing — shapes.py:149.
5. §2.4 — revise — `created_at`/`updated_at` stamped from the logical clock; enumerated every other stored instant renders 3-digit-`Z`; the four calendar-date fields render `YYYY-MM-DD` — store.py:156-178,87-105.
6. §2.5 — revise — `current_utc` is the caller's own string echoed verbatim, not re-rendered — routes/ops.py:22-26, store.py:128.
7. §2.6 — insert — the nine gates are the *write* order; reads run gates 1–3 only and **ownership is never checked on a read** — no `require_*_owner` on any GET. *(Part A deletion + Part B 45.)*
8. §2.10 — revise — `PointsLedgerEntry` → `ERR_LOYALTY_ACCOUNT_NOT_FOUND`; unmatched path → `ERR_ACCOUNT_NOT_FOUND`; wrong method → `ERR_FORBIDDEN_ROLE`; both behind auth — errors.py:160, app.py:37-44,28-31.
9. §3.1 — revise — missing at-sign → `ERR_INVALID_FORMAT`, ahead of the uniqueness rung — routes/accounts.py:28-32.
10. §3.1 — revise — on verify **all three** referral rungs (and an unresolvable code) fail silently with a 200 — routes/accounts.py:117-125.
11. §3.1 — revise — close: both roles, both from-states {ACTIVE, SUSPENDED}; CLOSED/PENDING → `ERR_ACCOUNT_NOT_ACTIVE`, ahead of the subscription rung — routes/accounts.py:154-162.
12. §3.1 — revise — `include_credits` query-string encoding (`false`/`0`/`no`, any casing) — shapes.py:142.
13. §3.2 — revise — which subscription an AUTO resize attaches to (earliest ACTIVE/PAUSED → earliest DRAFT → none); with none, cap unconsulted and no event written — services.py:784-795, routes/children.py:119-146.
14. §3.2 — revise — the REJECTED (pinned) event is always written, `subscription_id` null when there is none, `target_cycle_id` always null — routes/children.py:126-128, services.py:752-766.
15. §3.2 — revise — a MANUAL event's `measured_weight_grams` is null, exactly on `origin == MANUAL` — routes/subs.py:211-212.
16. §3.2 — revise — APPLIED_CURRENT re-allocation rebuilds only an `ALLOCATED` cycle, and is **best-effort** (lines/stock restored, request still succeeds) — services.py:601-631.
17. §3.2 — revise — the allergen screen is a *refusal* only where a SKU is handed in (gift claim); at allocation it reaches the caller through the empty-pool diagnosis, at substitution never; re-screen refuses nothing — services.py:495-535,643-678, routes/gifts.py:164.
18. §3.2 — revise — same split for the two product-line rules; the ladder never returns `ERR_HYPOALLERGENIC_REQUIRED`/`_NOT_ALLOWED`, it short-fills — services.py:637-678.
19. §3.4 — revise — `next_charge_cents`: non-terminal = not RETURNED/CANCELLED (SKIPPED and DELIVERED count), ordered `window_start`,`created_at` — services.py:107-115.
20. §3.5 — revise — three generation rungs, delinquency before the ACTIVE-lifecycle rung — routes/subs.py:344-347.
21. §3.5 — revise — allocation precondition order sub-ACTIVE → child-archived → cycle-PLANNED; `stage_at_allocation` frozen only after selector+waterfall succeed — routes/cycles.py:46-53, services.py:589-598. *(Part A fix 1.)*
22. §3.5 — revise — empty-pool fallback (earliest rung any SKU fails) and that stock never enters the diagnosis — services.py:495-519,522-535.
23. §3.5 — revise — cycle money is **stored**, not derived on read; a pending line does not re-price — routes/catalog.py:154-166, services.py:697-723. *(N1.)*
24. §3.5 — revise — a skip re-prices the emptied cycle under the partial re-derivation (599 base shipping returns; credit applications carried) — routes/cycles.py:288-291.
25. §3.6 — revise — `/rescreen` requires the parent cycle PLANNED/ALLOCATED (`ERR_CYCLE_STATE_INVALID`, checked first); a still-passing line bumps no `version` — routes/lines.py:106-115.
26. §3.6 — insert — the two product-line rules ride on all three rungs; a substitution moves **no** stock — services.py:643-678, routes/lines.py:58-70.
27. §3.6 — revise — hop four names `promo_discount_cents` too and carries credit applications — services.py:439-484.
28. §3.6 — revise — short fill re-prices the same four fields; the new SHORT_FILL credit does **not** discount its own box — routes/lines.py:75-94. *(Part A fix 2.)*
29. §3.7 — insert — **"Full and partial re-derivations"**: full only at allocation/re-allocation while UNCHARGED (plus charge and preview); everywhere else steps 1/2/8/9 only — services.py:439-484.
30. §3.7 — revise — an undeclared `credit_type` → `ERR_VALUE_OUT_OF_RANGE`, not `ERR_INVALID_ENUM` — routes/credits.py:30-31.
31. §3.8 — revise — the referral window is a **pre-condition** of `/deliver` (409 before any hop); earliest-created PENDING referral is the candidate — routes/cycles.py:200-224.
32. §3.9 — revise — registry create compares body `owner_account_id` to `X-User-ID`, role-specific code; account must be ACTIVE — routes/registry.py:34-38.
33. §3.9 — revise — `inflight_gift_count` is recomputed on every read/list/summary/item-change/gift move — serialize.py:110, services.py:901-909. *(Part C 2.)*
34. §3.9 — revise — item ops ungated on registry status; on delete the gift rung precedes the mismatch rung — routes/registry.py:148-224.
35. §3.9 — revise — the four reservation checks fire in the stated order, behind the ACTIVE-account check — routes/gifts.py:51-63. *(N2.)*
36. §3.9 — revise — four ordered rungs on `/pay` (registry OPEN, item not FULFILLED, gift PENDING_PAYMENT, quantity remaining) — routes/gifts.py:103-111.
37. §3.9 — revise — gift-refund hop three reverses the *cycle's* record, not the credit's: (2999 / 0 / 601) on a 3600 credit; the chain also covers a FULFILLED credit-gift, whose CONSUMED credit keeps its status — services.py:174-213, routes/gifts.py:212-221. *(Part C 1.)*
38. §3.9 — revise — a FULFILLED item-gift is refundable with its DELIVERED shipment driven to RETURNED; the CLAIMED_ITEM/DELIVERED refusal is unreachable — routes/gifts.py:199-231, routes/shipments.py:89-95.
39. §3.10 — revise — cancellation refund target = `window_start` DESC/`created_at` DESC, snapshotted (with its status) before the cascade — routes/subs.py:298-334.
40. §3.10 — revise — settlement rung order SOD → cycle payment axis → refund status → capacity — routes/refunds.py:118-135.
41. §3.10 — revise — credit restoration is one-shot; a second settlement restores 0 — routes/refunds.py:176-187.
42. §3.11 — revise — batch-ended pause stamps `actual_end_date = end_date`, unlike resume/cancel which stamp today — routes/ops.py:71-75.
43. §3.11 — revise — the 500-point floor rung precedes the balance rung — routes/loyalty.py:43-46. *(Part C 3.)*

## Pre-edit search log (subject → paths enumerated → wording adjustment)

- **Timestamp sourcing** (1, 5) → `envelope._meta`/`store.real_now_iso` vs `store.now()`; every `base_row`/`touch`/`plus_days` callsite; `fmt_instant`/`fmt_date`; `routes/ops.clock_set`. → Scoped "wall clock" to `api_request_timestamp` alone; carved the `current_utc` echo out into edit 6.
- **Sort ties** (3) → `store.sort_key/by_created`, `calc.rank_key`, `calc.credit_pool_key`, cycle sorts in `_estimate_target_cycle`/`next_charge_cents`/`resize_target_cycle`/`apply_free_shipping_from_tier`, points-lot sort, `cancel_subscription`'s reverse sort, `shipment_of_cycle`'s `[-1]`. → Reworded from "oldest first" to "first written ranks first ascending, last descending" so the one **descending** sort is not mis-described.
- **Ownership on reads** (7) → grepped every `require_account_owner` / `require_registry_owner` / `require_gift_purchaser` callsite across all 13 route modules; zero on any GET; `DELETE /allergen-flags` and `POST .../redemptions` (writes) do enforce it. → Added "(a list endpoint additionally validates the pagination bounds)".
- **Re-derivation depth** (24, 27, 28, 29) → all five `apply_pricing` callsites plus `derive_pricing` callers plus `_reverse_gift_application`. → **Removed the gift-refund reversal from the "partial re-derivation" list** — it recomputes only the application and the total from stored values, so listing it would have made the blanket rule false at that one site.
- **Skipped-cycle money** (24) → `calc.shipping_cents(0,0,eligible)` → 599; promo path; `next_charge_cents` including SKIPPED. → Dropped the flat "total becomes 599"; pinned the shipping reacquisition and the carry-through instead.
- **Allergen / product-line surfacing** (17, 18, 26) → `_passes_safety`, `allocation_candidates`, `diagnose_empty_pool`, `substitution_candidates` (all three rungs), `rescreen`, `claim_gift`. → Split "refusal" from "filter"; explicitly excluded the plan rule from the gift claim.
- **Registry recomputation** (33) → `serialize.registry` → `recompute_registry`; `registry_summary`; `apply_item_fulfilment`; add/update/delete item; `close_registry`; `archive_registry`. → Widened from "at close and gift refund" to "every read and every item/gift movement".
- **Close from-states** (11) → order existence → ownership → status → active subs. → Softened "before anything else" to "ahead of the subscription rung".
- **Settlement / cancellation ordering** (39, 40) → `settle_refund`, `_settle_pipeline_r`, `cancel_subscription`, `calc.cancel_refund_cents(status_override=)`. → Added "a Pipeline-G refund carries no cycle, so the payment-axis rung does not apply".
- **Gift refund money** (37) → `reverse_credit_consumption_on_planned_cycles`, `_reverse_gift_application`, `forfeit_credit`, `restore_credit`, `db.cycle_credit_contributions`. → Added the CONSUMED-credit caveat.
- Each remaining edit was checked against its handler plus every sibling handler touching the same field/entity; no further wording adjustment needed.

## Part B / Part C claims REFUTED by reading the code

1. **Part B 27 — "`skip` recomputes the skipped cycle's money to 0". False.** `apply_pricing` after line deletion gives `shipping_cents(0,0,False)` = **599**; `total_due_cents` lands at 599 minus already-recorded credit applications — not 0. Pinned the actual behaviour.
2. **Part B 35** — the flip guard is correct, but "hops 4/5 apply when the post-hop-3 tier is SILVER/GOLD" understates a guard: `apply_free_shipping_from_tier` returns immediately for BRONZE and hop four is a no-op on an already-eligible subscription. No edit — the PRD's existing "because `free_shipping_eligible` flipped to true" already pins the code.
3. **Part B 46** — `/skip-records`, `/resize-events`, `/allergen-flags` are indeed outside `PIPELINE_R_PREFIXES`, but **unobservable**: `GiftPurchaser` is in none of those endpoints' role lists, so rung 5 refuses first. No edit.
4. **Part B 39 — the CLAIMED_ITEM/DELIVERED refusal is DEAD CODE.** `routes/shipments.py:91-95` unconditionally drives CLAIMED_ITEM → FULFILLED on delivery, so the guard can never fire. Edited §3.9 to state the *reachable* half and mark the refusal unreachable.
5. **Part B 3** — correct, but the short-fill branch **never increments `substitution_attempts`**, so a short fill cannot be the third attempt in the counter's own terms; the line is terminal in SHORT_FILLED anyway. No edit.
6. **Part C 1** — the implementation lands on **(2999 / 0 / 601)**, i.e. the *first* of the two readings the test generator named. Edit 37 pins it with worked figures.
7. **Part C observation** — the `ERR_PIPELINE_R_REFUND_ACTOR` §4 gloss does leak "validation priority 16", but nothing turns on it; left verbatim under the minimal-patch rule.

## Step 9: Complete PRD — 2026-08-09T19:00:00.000Z

Orchestrator verification: `find . -newer workspace/implementation/results.8.json` returns only `worklog.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md` and sweep bookkeeping — Steps 8 and 9 touched **documentation only**; no implementation or test file changed after the green sweep.

Subagent summary (verbatim):

`PRD_COMPLETED.md` is written. All 46 changes are in-place paragraph revisions (`NcN` only) — no lines added or removed, no new sections, section headings and the 217-row endpoint/error tables byte-identical.

## Counts
- `PRD_FINALIZED.md` 687 lines / 146,683 chars → `PRD_COMPLETED.md` 687 lines / 164,264 chars (**+17,581 chars**, +12.0%)
- **37 ambiguity-pins**, **9 mismatch-revisions**

## Changes
- §2.1 — insert — ambiguity — `ERR_GIFT_PURCHASER_SCOPE` decided by leading path segment; covers nested `/children/{id}/allergen-flags`, excludes the flat `/allergen-flags`, `/resize-events`, `/skip-records`, `/substitution-events` — auth.py:13,41-53
- §2.4 — revise — mismatch — "Four record types" → "Five" (the sentence itself listed five) — serialize.py:15,42,88,95,148,168
- §2.4 — insert — ambiguity — version counts writes not requests (re-allocation double-writes a SKU; batch double-writes a pause record); an empty PATCH still bumps — store.py:169-178
- §2.6 — revise — mismatch — the mutate-then-reject rung "lives in section 3.6" → 3.7 — cycles.py:123-128
- §2.9 — revise — mismatch — `fulfilled_quantity` "never exceeds `requested_quantity`" scoped to gift activity; the item-revise path breaks it — services.py:916-931, registry.py:191-207
- §2.11 — insert — ambiguity — three undeclared ranges (`default_pack_count` 1–12, `stock_packs` ≥0, `issued_cents` ≥1); `delta_packs`/`points` unbounded; `consumption_rate_per_day` and `promo_discount_pct` read as numbers — catalog.py:27,88, credits.py:27, subs.py:40
- §3.1 — revise — mismatch — `verification_token` is on every account read, not "handed out" once — serialize.py:26-29
- §3.1 — insert — ambiguity — replayed verification (token now null) → `ERR_INVALID_VERIFICATION_TOKEN`; status never consulted — accounts.py:102-104
- §3.1 — insert — ambiguity — reinstate of a non-SUSPENDED account → `ERR_ACCOUNT_NOT_ACTIVE` — accounts.py:146-147
- §3.2 — insert — ambiguity — pinned-stage guard precedes the auto-resize cap when both would bite — children.py:121-135
- §3.2 — insert — ambiguity — manual resize returns **201** with the ResizeEvent; the child's version also advances — subs.py:209-216
- §3.2 — insert — ambiguity — `PATCH /children/{id}` `stage` is an unguarded override (no clamp, no pin check, no event, no cap) — children.py:87-88
- §3.2 — insert — ambiguity — flag deletion answers 200 with the removed flag; re-screens nothing — children.py:195-204
- §3.3 — insert — ambiguity — `allergen_tags` members are not validated against the six declared tags — catalog.py:87,101
- §3.3 — insert — ambiguity — stock push is ALLOCATED-only, reason OUT_OF_STOCK, compares post-adjustment stock, negative deltas only; returns the Sku — catalog.py:154-167
- §3.4 — revise — mismatch — activation order is account-active → DRAFT → child-archived → duplicate (PRD listed DRAFT first) — subs.py:130-142
- §3.4 — insert — ambiguity — update / set-override / clear-override all refuse CANCELLED with `ERR_SUBSCRIPTION_STATE_INVALID`; each returns the Subscription — subs.py:112,163,175
- §3.4 — insert — ambiguity — pausing requires lifecycle ACTIVE, checked ahead of the four date rungs — subs.py:227-228
- §3.4 — insert — ambiguity — resume: not-PAUSED → state-invalid; not exactly one ACTIVE record → `ERR_PAUSE_STATE_INVALID`; returns the Subscription — subs.py:269-288
- §3.4 — insert — ambiguity — pause cancellation returns the record — subs.py:435-440
- §3.5 — insert — ambiguity — skip returns **200 + Cycle**, not 201 + SkipRecord — cycles.py:305
- §3.5 — insert — ambiguity — withdrawal targets the latest APPLIED record, else `ERR_SKIP_RECORD_NOT_FOUND`; lines/stock/pricing are **not** restored — cycles.py:317-329
- §3.6 — insert — ambiguity — `/substitute` runs only two rungs (line state, then cap) and carries **no cycle-status rung** — lines.py:43-48
- §3.6 — insert — ambiguity — short fill leaves `substitution_attempts` unchanged; no credit row at face value 0 — lines.py:71-88
- §3.6 — insert — ambiguity — both ladder outcomes return 200 with the CycleLine — lines.py:95
- §3.7 — insert — ambiguity — charge rung order: account-active → fulfilment axis → payment axis — cycles.py:100-105
- §3.7 — revise — mismatch — named credits: resolve (`ERR_CREDIT_NOT_FOUND`) → **status** → expiry (PRD stated expiry first); foreign-account credits silently ignored — cycles.py:108-119, services.py:344-360
- §3.7 — insert — ambiguity — `issued_cents` < 1 → `ERR_VALUE_OUT_OF_RANGE` — credits.py:27
- §3.7 — insert — ambiguity — revoke-reversal targets `gift_credit_applied_cents` for GIFT and `referral_credit_applied_cents` otherwise, with the FULLY_COVERED → UNCHARGED fallback — services.py:193-210
- §3.7 — insert — ambiguity — pricing preview is gated on neither axis and may disagree with a charged cycle's stored figures — cycles.py:73-87
- §3.8 — insert — ambiguity — `eta_days` seeded at 3 regardless of `service_level` until carrier hand-off — services.py:847, shipments.py:51
- §3.8 — insert — ambiguity — the EARN entry is written even when `points_earned` is 0 — cycles.py:237-241
- §3.8 — insert — ambiguity — hop 4 version-bumps every ACTIVE/PAUSED sub; hop 5 fires only on a genuine flip; BRONZE ends the cascade — services.py:280-302
- §3.8 — insert — ambiguity — shipment delivery moves the shipment alone; the two delivery confirmations are independent — shipments.py:81-96
- §3.9 — insert — ambiguity — item delete returns the removed item; item revise has no `fulfilled_quantity` rung — registry.py:191-224
- §3.9 — insert — ambiguity — claim rung order: gift PAID → spacing (ITEM only) → claim window — gifts.py:135-144
- §3.9 — revise — mismatch — ITEM branch is allergen → hypo-required → **stock** (PRD stated stock first) — gifts.py:162-169
- §3.9 — insert — ambiguity — gift shipment's `dispatched_at` stamped at claim; `eta_days` 3 — services.py:838-852
- §3.9 — revise — mismatch — a non-paying GiftPurchaser gets `ERR_NOT_GIFT_PURCHASER`, not `ERR_PIPELINE_G_REFUND_ACTOR` — gifts.py:188-190
- §3.10 — insert — ambiguity — return drives the shipment to RETURNED from any status; refund opened even uncharged; returns the Cycle — cycles.py:332-351
- §3.10 — insert — ambiguity — refund-request amount keyed on current status; SKIPPED/RETURNED/CANCELLED → 0/0; returns 201 — calc.py:254-266, cycles.py:368-372
- §3.10 — insert — ambiguity — Pipeline-G settlement does the first of the five things only; `points_clawed_back` and `credits_restored_cents` stay 0 — refunds.py:137-144
- §3.11 — insert — ambiguity — redemption returns **201 + PointsLedgerEntry** — loyalty.py:48-54
- §3.11 — insert — ambiguity — expiry sweep returns the wallet and bumps its version even when nothing expired — loyalty.py:57-62
- §3.11 — insert — ambiguity — tier re-eval writes only changed subs, re-prices **no** cycle, returns the wallet — loyalty.py:65-79
- §3.11 — revise — mismatch — explicit referral stores `code` verbatim, never cross-checked against `referral_code` — refunds.py:26-40
- §3.11 — insert — ambiguity — pause promotion regardless of lifecycle state; promote-then-end within one run; counter semantics — ops.py:56-83

## Outright-false PRD claims found
1. §2.4 "**Four** record types are append-only" — the same sentence lists five.
2. §3.1 "the server mints a `verification_token` … **this is the only time the token is handed out**" — it is a serializer field on every account read.
3. §2.6 the mutate-then-reject rung "is called out explicitly in **section 3.6**" — it lives in §3.7.
4. §2.9 "`fulfilled_quantity` **never** exceeds `requested_quantity`" — the item-revise path has no rung against it.
5. §3.9 gift refund: "rejected with `ERR_PIPELINE_G_REFUND_ACTOR` … **as is any other identity**" — a non-paying GiftPurchaser is stopped one gate earlier by `ERR_NOT_GIFT_PURCHASER`.
6. §3.11 a referral's `code` is "**the same string as the referrer's own `referral_code`**" — true only for the verification-created row.
7. §3.9 ITEM claim ordering (stock before allergen) is inverted relative to the code.
8. §3.7 named-credit validation ordering (expiry before status) is inverted relative to the code.
9. §3.4 activation preconditions listed DRAFT ahead of account-active; the code checks account-active first.

## Impl behaviors believed to be genuine bugs, documented faithfully
1. **Registry conservation breach** — revising `requested_quantity` below `fulfilled_quantity` is ungated: `status` is not recomputed and `completion_pct` exceeds 1, violating §2.9's own invariant.
2. **Stock-push comparand** — the negative-adjustment push compares post-adjustment `stock_packs` against the line's `quantity_packs`, although those packs were already deducted at allocation.
3. **`eta_days` seeded at 3** for an EXPEDITED shipment until carrier hand-off.
4. **Hop 4/hop 5 asymmetry** — hop 4 version-bumps subscriptions whose flag was already true while hop 5 skips them, so the version moves without the price.
5. **Shipment SM bypassed by cascades** — `/cycles/{id}/return` and the gift-refund ITEM path force RETURNED from any status, ignoring the endpoint's EXCEPTION-or-DELIVERED from-set.
6. **Skip withdrawal is not an inverse** — lines and stock are not rebuilt and the pricing is not rewound, leaving a PLANNED cycle at subtotal 0 with a 599-cent shipping charge.

## Open-item verification
Items 1, 2, 3, 5, 6, 7 **confirmed** as stated. Item 4 is **refuted**: `auth.authorize` runs rung 3 before rung 5, so `ERR_GIFT_PURCHASER_SCOPE` is fully observable — its path-prefix semantics were pinned instead. Item 8's untested sites are covered by the `ERR_CREDIT_NOT_AVAILABLE` precedence pin, the three undeclared range pins, and the refund-request/GOODWILL pin.

---

# PIPELINE COMPLETE

194/194 tests passing on all 8 stability-sweep rounds. Step 7 = 1 deletion + 3 implementation fixes. Step 8 = 43 edits. Step 9 = 46 edits (37 ambiguity-pins, 9 mismatch-revisions) + 9 outright-false PRD claims corrected.

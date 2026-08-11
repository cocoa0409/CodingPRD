# Worklog — task_0942_buying_club_food_coop

Scenario (verbatim from user):
> 942. Buying Club & Food Co-op Order (Azure style): catalog & drop-point/route, member order aggregation & minimum, split-case & pre-order cycle, coordinator commission & volunteer, cold/dry pallet consolidation, payment & reconciliation, substitution/shortage, membership

Difficulty: **beyond-Expert** ("generate task hard than expert level!").

## Step 1: Create task directory — 2026-08-09T04:38:10.498Z

Created `tasks/task_0942_buying_club_food_coop/workspace/`. Index 0942 matches the scenario's own number and is one past the highest existing (`task_0941_community_supported_fishery`).

Host pre-flight: 8 cores, load average 2.32 (1-min) at start. **Four co-tenant pipelines are active on this host** (`task_0938`, `0939`, `0940`, `0941` all created within the last 3 minutes by other sessions). That puts the host at the 5-way cap from the parallel-SIGTERM-saturation note — Step 7's sweep must be scheduled defensively (smaller waves than the usual 2×4 if co-tenant sweeps overlap).

## Step 3: Copy shared files — 2026-08-09T04:38:10.498Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (done early, alongside Step 1; it has no dependency on Step 2).

## Step 2: Generate scaffold — 2026-08-09T05:40:12.000Z

Subagent summary, verbatim:

---

All three artifacts are written and clean.

## Final counts

| Dimension | Value | Target |
|---|---|---|
| Entities | **19** | 17–19 ✓ |
| Endpoints | **82** (incl. 1 test-driving `/_clock/set_current_utc`) | 72–82 ✓ |
| Error codes | **68** | 45–60 — *over, see below* |
| Calculations | **17**, of which **14 dual-variant** across 9 entity domains (OrderLine/PriceVersion, Item pricing, CaseAggregate, DropRun, RouteRun, Pallet/RouteRun, MemberOrder, CreditGrant, CommissionAccrual, Member) | 8+ across ≥5 ✓ |
| Status axes | **17**, of which **15 non-linear** (Member.status cycle, Member.tier bidirectional, Cycle.status branch-to-CANCELLED, Cycle.exception_state clock-derived parallel axis, RouteRun branch w/ disjoint effects, DropRun QUALIFIED→DEFERRED revert, MemberOrder.status × payment_status parallel axes with an AUTH_FAILED→AUTHORIZED retry loop, OrderLine 5-way branch, SubstitutionOffer auto-branch, Payment branch, DropReconciliation auto-branch + VARIANCE_HELD→BALANCED revert, CommissionAccrual branch, CreditGrant clock-driven, VolunteerShift branch) | 12 / ≥8 ✓ |
| Validation rungs | **55** ordered; **1 global write gate** (p9 `ERR_CYCLE_CLOSED`) + **4 ordered gates** (p10 membership-lapse, p11 coordinator-tier, p12 reconciliation-POSTED, p13 cycle-lock) | 40+, 3 gates + 1 global ✓ |
| OCC rules | **4** (MemberOrder, RouteRun, DropRun create-with-supersede, Member) | 3+ ✓ |
| Conservation invariants | **6** | 4+ ✓ |
| Max cascade depth | **7 distinct entities** (cycle lock: Cycle→MemberOrder→OrderLine→CaseAggregate→DropRun→RouteRun→DropRun revert→MemberOrder→OrderLine); second independent cascade **6** (receipt line: ReceiptLine→CaseAggregate→OrderLine→MemberOrder→DropRun→RouteRun); plus refund (4), volunteer-verify (4), merge (4), roll-forward (5 hops) | ≥5 and ≥4 ✓ |
| §1.8 instances | **26** across 9 rules (5/3/3/3/3/3/2/2/2) | ≥18 ✓ |
| §1.9 instances | **91** across 9 sections (80 full recipes + 11 `excluded_because` stubs) | — |

## Archetypes
Primary **quota/allocation**, secondary **ledger reconciliation**. The scenario's core is finite supply competed for: whole cases against unit demand (split-case remainder), scarce reefer slots against cold pallets, short-shipped units against member lines — all resolved by floor-plus-largest-remainder allocators with pinned tie-breaks. The reconciliation half supplies the conserved-money side (member charges vs supplier invoice + freight + surcharge + commission + club margin) and the POSTED freeze. Layers: optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers. Topology **flat** and role model **segregation_of_duties** were chosen deliberately — both flagged 0% / PRIORITIZE in §0.3; `state_machine_shape: parallel`; `self_referential` present twice (`DropRun.merged_into_drop_run_id`, `OrderLine.rolled_from_order_line_id`).

## Constants
**49 declared constants**, all with concrete values in a top-level `global_constants:` block. Automated grep for ALL_CAPS tunables across the finished file returns **zero undeclared** (the only two hits are the sibling filenames in a header comment). A `boundary_semantics:` block states inclusive/exclusive for **every** window and threshold — drop minimum `>=` INCLUSIVE vs route minimum `>` EXCLUSIVE (deliberate asymmetry, exercised at the same 40000-cent number), cutoff EXCLUSIVE, price binding `<=` INCLUSIVE, exception window `[received_at, deadline)`, substitution respond_by EXCLUSIVE, substitution tolerance INCLUSIVE, payment/recon variance INCLUSIVE, pallet weight and cube caps INCLUSIVE, reefer slots INCLUSIVE, credit cap INCLUSIVE, credit expiry EXCLUSIVE, dues grace INCLUSIVE, volunteer obligation INCLUSIVE, commission band upper bounds INCLUSIVE, route turnaround INCLUSIVE. A `list_ordering:` block pins the write order behind every `$.data[0]` the design files address.

## Reachability self-repairs
1. **`POST /cycles/{id}/lock` hop 6 voided authorizations that cannot exist.** Authorization requires `MemberOrder.status == LOCKED`, which only the lock itself produces, so the Payment leg of hop 6 was dead prose. Removed it from hop 6 and moved the authorization-voiding leg to `POST /cycles/{id}/cancel` (reachable: lock → authorize → cancel). This is also the §1.8 Rule-9 credit-conservation instance.
2. **Commission payout was gated on the volunteer obligation**, which made the 0.50-multiplier accrual permanently unpayable — `ADJUSTED → PAID` was arithmetically unreachable for any drop that missed its hours. Re-scoped the gate to `payout_mode: STORE_CREDIT` only; CASH is always available.
3. **`ERR_DROP_MINIMUM_NOT_MET` deleted.** Raised at lock, it would abort the very computation that decides qualification. Drop-minimum failure is now the observable `OPEN → DEFERRED` auto-transition instead.
4. **`ERR_ROUTE_MINIMUM_NOT_MET` moved from lock to submit** for the same reason: submit requires ≥1 QUALIFIED RouteRun.
5. **`CommissionAccrual.status: VOID` removed** — accruals are only created at delivery and cycle cancel only fires from OPEN/LOCKED, so no path produced it (enum-closure violation caught by an automated sweep).
6. **`Member.status` SUSPENDED and CLOSED removed**, **`CreditGrant.status` REVOKED removed**, **`Payment.status` PENDING removed** — all lacked producing transitions once the endpoint budget settled. FAILED is produced by `authorize` with `simulated_outcome: "FAILED"`, which also let me delete a `/_payments/settle` test-driving endpoint.
7. **`POST /route-runs` deleted**; RouteRun is now auto-minted by the first `POST /drop-runs` for a (cycle, route) pair, so an orphan RouteRun with no drops can never reach hop 5 with a zero denominator.
8. **`POST /cycles/{id}/close-exception-window` deleted**; `exception_state` is derived from the clock, so closing the window is reachable purely through `/_clock/set_current_utc`.
9. **`DELETE /order-lines/{id}` replaced by `POST /order-lines/{id}/cancel`** — the OCC field has to travel in a body and DELETE-with-body is unreliable through the harness.
10. **`ERR_ROLLFORWARD_LIMIT`'s count clause was unreachable**: `rollforward_count > 0` implied `status == ROLLED_FORWARD`, which the state rung at 18 pre-empts. Fixed by having the newly minted DropRun **inherit `rollforward_count`** from its source, so a chain of deferrals is genuinely capped at one; the corner test drives the sibling target-cycle clause, which is cheap.
11. **`OrderLine.confirmed_units` split out from `qty_units`** — without it the ROUND_UP overage and the DROP trim rewrote the member's own input, and the create-then-cancel conservation invariant could not be stated.
12. **`RouteRun.aggregated_subtotal_cents` re-scoped to `OPEN or QUALIFIED`** so hop 4 of the merge cascade is observable before the lock; at hop 5 the OPEN set is empty, so route qualification is unchanged.
13. **`REEFER_SURCHARGE_CENTS_PER_SLOT` lowered 18000 → 4500.** At 18000 the surcharge pushed every capture past the variance band, making the happy-path `AUTHORIZED → CAPTURED` transition arithmetically unreachable in any realistic fixture.
14. **Capture precondition widened** to `MemberOrder.status ∈ {FILLED, SHORT_FILLED, DELIVERED}` so captures are not trapped inside the CONSOLIDATED window alone.
15. **Rung 18 (`ERR_INVALID_DROP_RUN_STATE`) spelled out** which DropRun statuses admit a volunteer shift; the generic wording made shift logging after receipt indeterminate.
16. **Rungs 4 and 5 given an explicit path-segment → 404-code mapping table** (18 + 11 entries). Left as "the one named for the missing entity", the PRD, tests and implementation would each have invented their own.
17. **`ERR_PALLET_CAPACITY_EXCEEDED` verified reachable** — needs `max_pallets` below the class count with the reefer cap slack; the corner test uses an all-DRY 40-unit RICE load on a `max_pallets: 1` route so rung 29 provably passes before rung 30 fires.
18. **`ERR_ITEM_NOT_SPLITTABLE` folded into `ERR_INVALID_QUANTITY`** as a second conditional clause on the same rung.

Every numeric assertion in both design files was produced by executing the named `§1.3` formula in Python against the pinned fixture (`3696`/`3734`/`4107`/`26109`/`6477`+`2523`=`9000`/`3143`+`1857`=`5000`/`2140`/`2354`/`2040`/`8877`/`885300`/`26600`/`52218`…), never estimated.

## Automated audits (all pass)
- All three files `yaml.safe_load` cleanly.
- **117 unique instance names**, zero collisions across §1.8 ∪ §1.9.
- **Zero unbound `${var}`** across 3595 calls and every assert line.
- Every `grounds:` entry resolves to a declared §1.1–§1.7 element (structural checker over calculations / validations[priority=N] / errors / entity fields / concurrency_rules / conservation_invariants / roles / state_machines / endpoints / boundary_semantics).
- Every `excluded_because.difficulty_instance` names a real §1.8 instance.
- **All 55 validation rungs** and **all 68 error codes** are grounded by at least one design instance.
- Enum closure: every system/computed enum value has a producing transition, side effect or default.
- Forbidden concurrency vocabulary: **none**. `id`-based tie-breaks: **none** (every allocator tie-breaks on `created_at ASC`).

## Verbatim lint verdict

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_0942_buying_club_food_coop/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_0942_buying_club_food_coop/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_0942_buying_club_food_coop/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    82
  §1.1 entities declared:     19
  §1.8 instances scanned:     26
  §1.9 instances scanned:     83
  Calls scanned (§1.8+§1.9):  3595

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Where I missed a calibration number
**Error codes came in at 68 against a 45–60 target — over, not under.** The overshoot is entirely mechanical: 19 addressable entities each carry their own `404`, which is 19 codes on its own. The behavioural half of the catalog is **49 codes** (4 auth/RBAC, 4 request-shape, 5 write gates, 10 state, 5 temporal, 14 constraint, 6 fiscal, 1 OCC), which sits inside the band. I considered collapsing the satellite 404s into shared codes (`ERR_DERIVED_RECORD_NOT_FOUND` and friends) to land at ~62, but the skill explicitly demands domain-specific error names, and a shared code would have made the rung-4 mapping table — the thing that keeps PRD, tests and implementation from diverging — impossible to state. I chose clarity over the band and am flagging it rather than hiding it.

Everything else met or exceeded its target: 19 entities, 82 endpoints, 14 dual-variant calculations across 9 domains, 15 non-linear status axes, 55 rungs with 1 global + 4 ordered gates, 4 OCC rules, 6 conservation invariants, and cascades of depth 7 and 6.

---

**Orchestrator verification of Step 2** (independent, not taken on faith): all three files `yaml.safe_load` cleanly (4403 / 7623 / 20633 lines); `global_constants` has 49 entries with **zero null/empty values**; `endpoints:` length is exactly 82; an independent ALL_CAPS sweep over `SCAFFOLD.yaml` returns 192 unmatched tokens, all of which are enum members, `ERR_*` codes, section-heading words, or boundary keywords (`INCLUSIVE`/`EXCLUSIVE`/`FIFO`) — **no `*_CENTS` / `*_PCT` / `*_DAYS` / `*_MINIMUM` / `*_CAP` tunable is left unbound**. `ERR_XXX` appears once, inside the §1.0 response-envelope template, as intended.

**New scale maxima for this roster:** 19 entities (prev 18), 82 endpoints (prev 81), 68 error codes (prev 61), 55 rungs (prev 51), 17 calculations, 6 conservation invariants, depth-7 cascade (prev 7-hop at 0931 but across fewer distinct entities).

## Step 4: Generate PRD — 2026-08-09T05:53:00.000Z

Subagent summary, verbatim:

---

PRD complete and audited. Final verification of all four coverage dimensions plus the three hard contracts passed.

**Output:** `workspace/PRD.md` — **577 lines, 17,635 words.** Written in 6 bounded Write/Edit/append calls; last section (§5 Error Code Catalogue, 68 rows) verified complete, no audit footer.

**Structure:** §1 (3 paras) · §2 with 11 domain-derived subsections (2.1 Actors/RBAC, 2.2 verbatim envelope, 2.3 Pagination & List Ordering, 2.4 Common Properties/Versioning, 2.5 Logical Clock, 2.6 Money & Allocation Determinism, 2.7 Boundary Semantics, 2.8 Path/Body Reference Resolution, 2.9 The Validation Ladder, 2.10 OCC, 2.11 Conservation Invariants) · §3 with 9 lifecycle-ordered subsections · §4 82-row table (4 cols) · §5 68-row table (2 cols).

### (D) Coverage self-audit — programmatic, all clean

| Dimension | Required | Present | Missing |
|---|---|---|---|
| Endpoints (method+path in §4 table) | 82 | 82 | 0 |
| Error codes (in §5 table **and** in §2/§3 prose) | 68 | 68 / 68 | 0 |
| Global constants (value located in context, per-constant literal probe) | 49 | 49 | 0 |
| Validation rungs (each ordinal named with neighbours in §2.9) | 55 | 55 | 0 |

Hard contracts: **Contract 1** — 137 entity fields + 69 endpoint input identifiers + 18 path params, 0 missing. **Contract 2** — all transitions, calcs, OCC rules, applies_to scopes expressed. **Contract 3** — 1,126 backtick tokens scanned in §3, 0 path tokens, 0 bare methods, 0 method+path. §2.2 byte-identical to `section-2.2-response-structure.md`. No tables or field lists in §3. No fuzzy quantifiers.

### (C) Un-prejudged friction points carried forward as-is

1. **`supplier_cost_cents` names an empty status set.** It is allocated "weighted by `subtotal_cents` over **RECEIVED** drop runs", but a reconciliation is only drafted after delivery, when those drop runs are `SETTLED`. Rendered verbatim, not silently retargeted.
2. **Authorization cycle-status asymmetry.** Only the `UNPAID → AUTHORIZED` leg declares the cycle-status precondition; `UNPAID → AUTH_FAILED` and `AUTH_FAILED → AUTHORIZED` declare none. Both branches rendered with equal density and the asymmetry named explicitly.
3. **Rung 13's carve-out is not in its own `applies_to`.** The gate text calls substitution responses "the single carve-out", but the scope list omits approve/decline. Both statements carried.
4. **Two clocks on the substitution carve-out.** Rung 13 keys the carve-out on `Cycle.status` being `RECEIVED`; rung 38 and the transition precondition key it on `exception_state` being `OPEN`. Both stated, neither collapsed.
5. **`SHORT_FILLED → ROLLED_FORWARD` looks unreachable.** A drop run only reaches `DEFERRED` at lock hops 4/6, which cancels its lines before any receipt can short-fill them; yet roll-forward hop 4 also derives `qty_units` from `short_units` "when the source line was `SHORT_FILLED`". Carried both legs.
6. **Credit-draw target disagreement.** `member_order_totals` STEP 6 makes the wanted amount `apply_credit_cents` when supplied, while `credit_consumption_fifo` fixes the wanted amount at the credit cap. I wrote the FIFO walk against "the amount still wanted" defined by STEP 6 — the only reading that conserves credit — so this one is *mildly* harmonised rather than left fully open; flagging it explicitly.
7. **Hop-5 input set is self-cancelling.** `aggregated_subtotal_cents` sums `OPEN` or `QUALIFIED` drop runs while noting none is `OPEN` at hop 5. Both clauses kept.

### Under-specified in the scaffold (noted, resolved conservatively)

- **`destination` enum values are never declared.** Derived `CARD` / `STORE_CREDIT` from `Payment.method` and the refund side effects.
- **Constraint-only fields have no error routing:** `cutoff_at` strictly after `opens_at`; `hours` greater than 0 in quarter-hour increments; `cases_received` at least 0; `CreditGrant.amount_cents` at least 1; `reefer_slots` non-negative; `max_pallets` at least 1; `case_price_cents` at least 1; uniqueness of `email` / `code` / `sku`. No rung owns them, so I routed them to the shape rung at priority 7 with `ERR_VALIDATION` and said so in §3.2.
- **`term_years` has no declared type or lower bound**; only the derived-amount equality at rung 55 constrains it.
- **Uniqueness violations** (`email`, Route `code`, Item `sku`, Cycle `code`) have no dedicated error code in the 68-code catalog.
- **`CaseAggregate.units_received` vs. rung 42** — rung 42 phrases the cap in terms of `cases_received`, while the aggregate accumulates units; I stated it as "the units implied by `cases_received`".

---

## Steps 5 & 6: Unit tests + implementation — 2026-08-09T06:38:00.000Z

Launched **concurrently in a single assistant message** (`run_in_background: false` on both), so `test_suite/` did not exist on disk when impl-gen started — physical isolation, no `mv` containment needed. Post-hoc `grep -rIl "test_suite\|test_helpers" workspace/implementation/` → **empty**.

### Step 5 subagent summary, verbatim:

---

Test infrastructure and suite generated.

## File inventory

**`test_helpers/`** (9 modules, ~2,200 lines): `types.py` (19 entity TypedDicts + 24 enums; `PriceVersion` correctly omits `updated_at`/`version`), `api_client.py` (all 82 endpoints), `api_errors.py` (68 error ids + status map, registered), `assertions.py` (per-entity assertions, the 6 conservation-invariant checkers, and **`assert_same_instant` / `assert_instant_equals_offset` / `shift_iso`** — every timestamp assertion is semantic), `constants.py`, `factories.py`, `test_users.py` (per-instance `make_member_headers` / `make_coordinator_headers`; three distinct FinanceOfficer identities for segregation of duties), `fixtures.py` (783 lines: `canonical_world(api, stage)` walks the 22-stage shared chain, plus `salt_world`, `rice_world`, `substitution_world`).

**`test_suite/`** — 129 tests:

| file | tests |
|---|---|
| test_01_catalog_and_membership | 19 |
| test_02_cycles_and_drop_runs | 9 |
| test_03_member_orders_and_lines | 17 |
| test_04_cycle_lock_cascade | 13 |
| test_05_receiving_and_shortage | 6 |
| test_06_substitution | 4 |
| test_07_consolidation_and_pallets | 11 |
| test_08_payments_and_credit | 15 |
| test_09_volunteers_and_commission | 12 |
| test_10_reconciliation_and_closeout | 7 |
| test_11_validation_ladder | 6 |
| test_12_rbac_and_concurrency | 10 |

Coverage: **queue A 24/26** instances translated (all with ≥2 tests); **queue B 81/83** non-stub instances translated (≥1 test); all 8 `excluded_because` stubs verified to resolve to real difficulty instances and not translated. Audited mechanically: every test carries exactly one `Design:` line resolving to a real non-stub instance; all **217 PRD quotes verify verbatim** against `workspace/PRD.md`; no `skip`/`skipif`/`xfail`; no scaffold references in generated code; 129/129 collect cleanly.

## Skipped instances (the feedback signal)

1. **`Difficulty/non_linear_state_machine/reconciliation_reverts_from_variance_held_back_to_balanced`** — *unique-derivability*. §3.9 defines `club_margin_cents` as the residual (`member_charges − supplier − freight − reefer − commission`) **and** `variance_cents` as `member_charges − (those five including club_margin)`, which is identically 0 — so `VARIANCE_HELD` is unreachable and resolve-variance is dead code. The design index instead assumes `club_margin` starts at 0 and only accumulates resolution adjustments (variance 2550). Two PRD-only readers land on different states; compounded by friction #1 (`supplier_cost_cents` weighted over `RECEIVED` drop runs, an empty set once delivery has moved them to `SETTLED` — 64400 vs 0).
2. **`Difficulty/cross_entity_state_dependency/substitution_response_depends_on_the_cycles_exception_state`** — *unique-derivability*. Frictions #3/#4: rung 13's prose calls substitution responses "the single carve-out" but its own applies-to list omits approve/decline. With `exception_state == CLOSED`, reader A gets `ERR_EXCEPTION_WINDOW_CLOSED` (rung 38), reader B gets `ERR_CYCLE_LOCKED` (rung 13). The asserted error id is not pinned.
3. **`Corner/state_machines/posting_a_variance_held_reconciliation_returns_invalid_reconciliation_state`** — *unique-derivability*. Requires the reconciliation to rest in `VARIANCE_HELD`; unreachable under the residual reading of `club_margin_cents`.
4. **`Corner/validations/resolve_variance_with_the_wrong_adjustment_returns_variance_unresolved`** — *unique-derivability*. Same cause, and additionally pins `variance_cents == 2550`.

## Where the design index and the PRD disagreed, and how I resolved it

- **`club_margin`/`variance` contradiction (above).** Rather than let it collapse the whole downstream chain (post → reconcile → close → payout → gate tests, ~25 tests), `fixtures.balance_reconciliation` reads the server's own reported `variance_cents` and resolves *exactly that* only when the draft landed on `VARIANCE_HELD`. That is setup robustness, not assertion weakening — the fixture reaches `BALANCED` under either reading. I then dropped only the reading-dependent *values* from surviving instances: `variance_cents == 2550`, `supplier_cost_cents == 64400`, `club_margin_cents == 2550`, and `rec2.status == VARIANCE_HELD` in `a_second_reconciliation_draft_supersedes_and_voids_the_first` (its primary claim — supersede → `VOID`, new preparer recorded, count 2 — is fully derivable and is asserted).
- **`volunteer_verification_cascades_into_commission_and_reopens_the_ledger`** asserted `variance_cents == -1070` and `VARIANCE_HELD` for hop 4. Kept the instance, asserting hop 4 through `DropReconciliation.commission_cents == 2140` (derivable under both readings) and dropping the two reading-dependent assertions.
- **`posting_a_reconciliation_before_delivery`** asserts `club_margin_cents == 4690`. Kept it: at that point the drop run is still `RECEIVED`, so `supplier_cost_cents` is unambiguous, and both readings converge on 4690.
- **`source` filter on `GET /credit-grants`** — rung 8 names `source` as an enum-valued list filter but no §3 sentence declares it for that endpoint. Replaced those filtered queries with `member_id` filtering plus client-side selection.
- **Cross-request list ordering** — `created_at` comes from a frozen logical clock, so two rows written in *different* requests can share it and the PRD only pins ordering *within* one request. Made the two-authorization assertion order-insensitive (set comparison); positional assertions are used only where the PRD pins intra-request write order (pallets FROZEN/CHILLED/DRY, capture STORE_CREDIT-before-CARD) or where the filter returns a single row.
- Frictions #5 (`SHORT_FILLED → ROLLED_FORWARD`), #6 (credit-draw target) and #7 (hop-5 OPEN-or-QUALIFIED) were examined and judged uniquely derivable in the scenarios the index actually uses: roll-forward runs off the `CANCELLED → ROLLED_FORWARD` leg; §3.8 step 6 pins `want = apply_credit_cents`; at hop 5 the OPEN set is empty and the pre-lock merge case is stated explicitly. All three areas are covered.

All arithmetic in the index was re-derived independently and matched (82420 lock subtotal, 3696/1680/3734/3334 unit prices, 4/4 + rank 1/2 largest-remainder split, 71332 commission base, 3143/1857 freight, 6477/2523 reefer, 52218 pre-credit, 26109 cap, 2354 vs 2040 payout, 8877 proration ceiling, 885300 g pallet break).

---

### Step 6 subagent summary, verbatim:

---

Implementation complete at `workspace/implementation/`.

## Module inventory (4,640 lines total)

| file | lines | | file | lines |
|---|---|---|---|---|
| `app.py` | 95 | | `routes/r_orders.py` | 217 |
| `core/clock.py` | 73 | | `routes/r_catalog.py` | 193 |
| `core/constants.py` | 111 | | `routes/r_lines.py` | 178 |
| `core/envelope.py` | 43 | | `routes/r_receiving.py` | 177 |
| `core/errors.py` | 116 | | `routes/r_members.py` | 147 |
| `core/ladder.py` | 410 | | `routes/r_cycles.py` | 139 |
| `core/money.py` | 61 | | `routes/r_volunteers.py` | 130 |
| `core/serialize.py` | 379 | | `routes/r_routeruns.py` | 114 |
| `core/store.py` | 147 | | `routes/r_dropruns.py` | 101 |
| `services/lock_cascade.py` | 217 | | `routes/r_recon.py` | 99 |
| `services/recompute.py` | 199 | | `routes/r_commission.py` | 68 |
| `services/droprun_ops.py` | 170 | | `routes/r_credits.py` | 66 |
| `services/cycle_ops.py` | 156 | | `routes/r_payments.py` | 37 |
| `services/consolidation.py` | 144 | | `start.sh` | 11 |
| `services/receiving.py` | 135 | | `requirements.txt` | 1 |
| `services/reconciliation.py` | 110 | | `services/substitution.py` | 95 |
| `services/commission.py` | 95 | | `services/credits.py` | 77 |
| `services/payments.py` | 75 | | `services/pricing.py` | 54 |

Everything was authored in bounded Write/Edit calls; `pyflakes` over all 35 modules is clean.

## (B) Completeness gate — verbatim

```
declared count: 82 unique: 82
IMPLEMENTED 82/82, MISSING [], EXTRA []
```

Produced by parsing `endpoints[]` out of SCAFFOLD.yaml, booting the app in-process, dumping `app.url_map` and diffing by `(method, path)` with path params normalised. Re-run after the final edit; still 82/82.

## (C1) Timestamp adjudication

**One renderer.** `core/clock.py::render()` is the sole producer of timestamp strings: `%Y-%m-%dT%H:%M:%S.mmmZ`, always three fractional digits, always `Z`. Every server-minted stamp routes through it (`created_at`, `updated_at`, `locked_at`, `received_at`, `posted_at`) as do every *derived* stamp, which takes its style from its clock-derived source (`exception_deadline_at` = received_at+48h, `dues_paid_through` = clock+365·term, `dues_grace_until` = +14d, `respond_by` = created_at+24h, system grant `expires_at` = clock+180d). **Caller-supplied timestamp strings are stored and echoed byte-verbatim and never re-rendered** — `Cycle.opens_at`/`cutoff_at`, `PriceVersion.effective_from`, `CreditGrant.expires_at`, and `current_utc` from `/_clock/set_current_utc`. Parsing for comparison is separate from storage.

HTTP evidence on a live boot (smoke5/smoke6), clock set to the deliberately odd `2026-06-15T08:00:00.5Z`:
- `current_utc` → `"2026-06-15T08:00:00.5Z"` (byte-verbatim, one fractional digit preserved)
- `Route.created_at` from the same instant → `"2026-06-15T08:00:00.500Z"` (rendered, three digits)
- caller `expires_at: "2027-06-01T12:34:56.789012+00:00"` → echoed unchanged, while the grant's `created_at` → `"2026-06-15T08:00:00.500Z"`
- derived `dues_paid_through` → `"2027-06-15T08:00:00.500Z"`, `dues_grace_until` → `"2027-06-29T08:00:00.500Z"`, `locked_at` → `"2026-06-15T08:00:00.500Z"`
- `Cycle.opens_at`/`cutoff_at` echoed exactly as posted (`"2026-06-30T23:59:59Z"`, no `.000` added)
- `meta.api_request_timestamp` is rendered from the same logical clock, matching `^\d{4}-…\.\d{3}Z$`

## (C2) Closed `ERR_INVALID_ENUM` iff-list

A value routes to `ERR_INVALID_ENUM` (400) **iff** it is one of these fields carrying an out-of-range value:

*Body enums:* `tier` (POST /members), `new_tier` (POST /members/{id}/tier-changes), `temp_class` and `remainder_policy` (POST /items), `substitution_pref` (POST /order-lines, PATCH /order-lines/{id}), `simulated_outcome` (POST …/authorize), `destination` (POST …/refund), `payout_mode` (POST …/payout).

*Enum-valued list filters* (PRD rung 8 names these explicitly, and §2.3 says an off-enum filter is rejected): `status` on /items, /members, /cycles, /route-runs, /drop-runs, /member-orders, /order-lines, /substitution-offers, /pallets, /payments, /drop-reconciliations, /commission-accruals, /volunteer-shifts, /credit-grants; `payment_status` on /member-orders; `kind` on /payments; `temp_class` on /items and /pallets; `tier` on /members; `source` on /credit-grants.

**No other field routes here.** Every other membership-shaped failure lands on the rung the ladder assigns it — missing/mistyped fields and format failures → rung 7 `ERR_VALIDATION`; quantity range/whole-case → rung 33 `ERR_INVALID_QUANTITY`; unresolvable FKs → rung 4/5 not-found codes; pagination → rung 6. **Free-form filters never error at all** and yield an empty page: `code`, `sku`, and every id-valued filter (`route_id`, `coordinator_member_id`, `member_id`, `drop_point_id`, `route_run_id`, `drop_run_id`, `merged_into_drop_run_id`, `member_order_id`, `item_id`, `rolled_from_order_line_id`, `overage_order_line_id`, `receipt_line_id`, `substitute_item_id`, `case_aggregate_id`, `home_drop_point_id`, `source_member_order_id`, `credit_grant_id`, `order_line_id`).

HTTP evidence (smoke6, 43 assertions, all pass): all 7 body enums and all 20 list filters return 400/`ERR_INVALID_ENUM`; the 7 negative cases return `ERR_INVALID_QUANTITY`/`ERR_VALIDATION`/`ERR_MEMBER_NOT_FOUND`/`ERR_INVALID_PAGINATION`; 9 free-form filters return 200 with `data: []`, `total_count: 0`.

## (D) Logical clock grep

`grep -rn "datetime\.now\|utcnow\|time\.time" --include=*.py .` → **no hits**. The only `time` usage anywhere is `time.sleep` inside `app.py`'s pre-bind retry loop. All business time reads `core.clock.CLOCK`, which starts at `2026-05-01T00:00:00Z` and only moves via `POST /_clock/set_current_utc`.

## (G) In-memory grep

`grep -rniE "sqlite|json\.dump|pickle|open\(|/tmp" --include=*.py .` → **no hits**. `grep -rn seed` → only the two doc-comments stating that nothing is seeded. The store is `core/store.py` dicts; ids are `uuid.UUID(int=(type_index<<64)|counter)` — monotonic and predictable per entity type, no prefix. Every row carries a private `_seq`; all ordering is `(created_at, _seq)`, never id (verified: 4 routes created under one clock reading come back in write order).

## (F) EADDRINUSE self-verification

Bounded pre-bind in `app.py`: 24 attempts × 0.25 s = **6 s hard ceiling**, then `sys.exit(1)`; the already-bound socket is handed to `werkzeug.serving.make_server(..., fd=sock.fileno())`.

- **Squatter test:** a process holds `0.0.0.0:10199` LISTENing for 2 s; `start.sh` launched 0.3 s in. Result: `PASS: bound after the squatter died (elapsed 1.98 s)` — served 200 immediately after release, well inside the ceiling.
- **12-cycle kill/relaunch loop, SIGTERM+wait:** `cycles=12 failures=0`, port released, no processes left holding it.
- **12-cycle loop with SIGKILL (`kill -9`) between cycles:** `cycles=12 failures=0`, `port holders: []`. Zero orphans.

## (H) The seven friction points — adjudications

**1. `supplier_cost_cents` over an empty RECEIVED cohort.** Read literally, the cohort is `DropRun.status == RECEIVED`, but a reconciliation is only ever drafted after `POST /cycles/{id}/deliver` has moved those very drop runs `RECEIVED → SETTLED`. The literal set is therefore always empty and the weighted division undefined — which would make drafting impossible and strand *every* downstream behavior (post, resolve-variance, payout, cycle reconcile, cycle close) as permanently unreachable. That reading is self-defeating and thereby forced out. I read "RECEIVED drop runs" as *the drop runs that reached RECEIVED*, i.e. those now in `RECEIVED` **or** `SETTLED` (`SUPPLIER_COST_COHORT` in `services/reconciliation.py`). This is exactly the cohort freight level 1 used when it ran, so supplier cost and freight share one allocation basis — clearly the intent, since the PRD says supplier cost uses "the same floor-plus-largest-remainder scheme that level one of the freight allocation uses". An empty cohort or a zero weight sum yields 0 rather than a crash.

**2. Payment authorization cycle-status asymmetry.** I implemented the asymmetry literally: **only** the `UNPAID → AUTHORIZED` leg tests that the parent cycle is `LOCKED`/`SUBMITTED`/`RECEIVED`/`CONSOLIDATED`/`DELIVERED`; `UNPAID → AUTH_FAILED` and the retry leg `AUTH_FAILED → AUTHORIZED` test nothing beyond the global write gate. PRD §3.8 states this in so many words ("the failing leg … and the retry leg … declare no cycle-status condition of their own beyond the global write gate"), so this is prose, not an accident of the table. It is also the reachability-maximising reading: symmetrising would strand the retry leg in any cycle state outside the list (e.g. `RECONCILED`), whereas the asymmetric reading leaves an order that failed authorization always retryable. Violation of the one leg that does carry the condition raises `ERR_INVALID_CYCLE_STATE` (409) — the catalogued code for "the Cycle is not in a from-state the requested transition declares" — evaluated after the rung-16 from-state test on both axes.

**3. Rung 13's "single carve-out" versus its own `applies_to` list.** The gate text calls substitution responses the single carve-out, but its `applies_to` list contains only the six member-order/order-line writes and omits approve/decline. I treat the `applies_to` list as operative: rung 13 is simply **not evaluated** on approve/decline, and the carve-out sentence is descriptive prose explaining *why* they are absent from the list. This is the reachability-preserving choice. Under the alternative (rung 13 applies, with a `RECEIVED`-plus-`exception_state OPEN` exemption), a response arriving at a `RECEIVED` cycle whose window has closed would fail at rung 13 with `ERR_CYCLE_LOCKED`, pre-empting rung 38 and making the cycle-state half of `ERR_EXCEPTION_WINDOW_CLOSED` unreachable. My reading keeps both halves of rung 38 live and costs nothing, because the two readings agree on every case an offer can actually exist in.

**4. Two clocks on that carve-out (`Cycle.status == RECEIVED` at rung 13 versus `exception_state == OPEN` at rung 38 and in the transition precondition).** Given adjudication 3, this collapses cleanly: the single operative test is rung 38's — `exception_state == OPEN` **and** `clock < respond_by`, both failing with `ERR_EXCEPTION_WINDOW_CLOSED`. I do not apply a second, independent `Cycle.status == RECEIVED` test. Two of the three sources (rung 38 and the state-machine precondition) agree on `exception_state`, and `exception_state == OPEN` already implies the cycle passed through `RECEIVED` (it is `NOT_STARTED` until `received_at` is stamped, and consolidation cannot run until the clock reaches the deadline, at which point the state is `CLOSED`). Adding the redundant status test could only ever *subtract* reachable behavior, never add any.

**5. `SHORT_FILLED → ROLLED_FORWARD`.** I implemented both source legs exactly as declared: roll-forward hop 5 promotes every source line with `rollover_opt_in` true out of `SHORT_FILLED` **or** `CANCELLED` into `ROLLED_FORWARD`, and hop 4 derives the new line's `qty_units` from `short_units` when the source line was `SHORT_FILLED` and from `qty_units` otherwise. I deliberately did *not* "fix" the apparent dead branch by making the deferral spare short-filled lines, because that would invent a behavior the PRD never states; implementing both legs costs nothing and is correct under either reachability outcome. See (I) for the reachability hypothesis this raises.

**6. Credit-draw target.** `member_order_totals` STEP 6 and `credit_consumption_fifo` disagree on the wanted amount. I implemented STEP 6: `want = apply_credit_cents` when the capture request supplies it, otherwise the credit cap; `credit_applied_cents = min(want, cap, credit the member can actually produce)`. PRD §3.8 step 6 says this in prose ("The amount wanted is `apply_credit_cents` when the capture request supplies it, and the credit cap otherwise"), and the FIFO rule's `want = credit_cap` is just the default case restated inside the draw routine. It is also the only reading that keeps a declared behavior reachable: under the FIFO-only reading `apply_credit_cents` would be validated at rung 51 and then discarded, so a caller could never actually apply *less* than the cap — a declared input with no effect. Rung 51 still rejects an `apply_credit_cents` above the cap rather than clamping it, exactly as the PRD insists.

**7. Hop-5 `aggregated_subtotal_cents` summing OPEN-or-QUALIFIED while noting none is OPEN at hop 5.** I implemented the union literally — one function sums `subtotal_cents` over drop runs whose status is `OPEN` **or** `QUALIFIED` — and use it both for the live pre-lock maintenance and for the hop-5 qualification read. There is no real conflict: before the lock the set is all-OPEN (which is what makes a merge immediately observable in the route aggregate, as §3.3/§3.4 require), and at hop 5 the OPEN set is empty so the union reads exactly the QUALIFIED set. Writing two functions, or restricting the sum to QUALIFIED, would have broken the pre-lock live figure for no gain. Verified over HTTP: adding a line moves the route run's aggregate immediately (28000), and a merge repoints it correctly (20000).

## (I) Reachability hypotheses — to be verified downstream, not established

1. **`SHORT_FILLED → ROLLED_FORWARD` may be unreachable in this implementation.** A drop run only reaches `DEFERRED` at lock hops 4 and 6, and both cancel that run's `CONFIRMED` lines before any receipt exists to short-fill them; short-filling itself only happens at `POST /receipt-lines`, long after the lock. So in my code the source line entering hop 5 appears to always be `CANCELLED`, never `SHORT_FILLED`. **This is a hypothesis, not a fact** — I have not exhaustively proved no route exists (a drop run that short-fills and then somehow re-enters `DEFERRED`, or a hand-built ordering I have not considered, would falsify it). The branch is implemented regardless, so if a route does exist it behaves as specified.

2. **`DropReconciliation DRAFT → VARIANCE_HELD` at creation may be structurally unreachable.** `club_margin_cents` is defined as the residual `member_charges − supplier − freight − reefer − commission`, and `variance_cents` as `member_charges − (supplier + freight + reefer + commission + club_margin)`. Substituting the first into the second gives identically 0, so a fresh draft always satisfies `|variance| ≤ 200` and auto-branches to `BALANCED`. **Hypothesis.** The `VARIANCE_HELD` state remains fully reachable by the declared downstream route (`BALANCED → VARIANCE_HELD` on a refund or a verified volunteer shift, which recompute `member_charges` and `commission` while leaving the frozen `club_margin` residual alone) and `resolve-variance` returns it to `BALANCED` — verified end-to-end over HTTP (variance −970 → held → resolved → 0, ledger identity exact).

3. **A note that is *not* a friction point but is a judgment call.** PRD §3.6 narrates allocation status transitions *before* it raises substitution offers, so I follow that order: the allocation moves a line to `FILLED`/`SHORT_FILLED`/`DROPPED` and the offer then overrides it (`SUBSTITUTED` on approve, removal on decline). The only observable difference from the alternative ordering is a line's status while an offer sits `PENDING` (`FILLED` here, `CONFIRMED` under the alternative); all post-resolution states are identical either way.

## Verification run over HTTP

Six live-boot suites, ~230 assertions, **0 failures**: full happy path through lock → submit → receive → receipt → invoice → pallets → seal → consolidate → capture → deliver → reconcile → post → close, plus the global write gate; merge and roll-forward cascades, OCC, 48-hour route turnaround, cutoff and cycle-lock gates; ROUND_UP/DROP/SHORT_FILL remainder policies, split-case pricing (`10000/3 → 3734`-style ceiling-then-fee order), cold-chain rung 28, all three substitution resolutions, freight two-level and reefer conservation (exact 3375/1125 split); volunteer cascade, commission bands and clawback, store-credit and cash payout, FIFO credit draw and expiry sweep; envelope/pagination shape, all 18 path 404 mappings, body-FK 404s, and the enum iff-list.

---

**Orchestrator verification of Steps 5/6:** 129 `def test_` == 129 `Design:` tags; 0 `skip`/`xfail`/`skipif` anywhere in `test_suite/` or `test_helpers/`; impl 4,628 Python lines across 35 modules; `grep -rIl "test_suite\|test_helpers" workspace/implementation/` empty (isolation intact); `start.sh` carries the `find_spec` probe (fast boot) and `exec python3 app.py`.

**Notable cross-check for Step 7:** Step 5 and Step 6 independently reached the *same* conclusion about the `club_margin_cents` / `variance_cents` algebra — the residual definition makes a fresh draft's variance identically zero, so `DRAFT → VARIANCE_HELD` at creation is unreachable. Step 5 responded by skipping the 4 instances that depend on it; Step 6 implemented the residual reading and found `VARIANCE_HELD` still reachable downstream (via refund / volunteer-verify recompute). Two independent derivations agreeing is the strongest signal available short of a test, but per the reachability-hypothesis rule this remains a hypothesis for Step 9 to verify by reading the code.

Pre-staged `workspace/sweep.sh` for Step 7 (8 rounds in waves of `$1`, default 4; no inline `pkill`; ends with `touch SWEEP_DONE`).

## Step 7: Test + fix loop — 2026-08-09T07:53:00.000Z

Subagent summary, verbatim:

---

Clean 8-round sweep achieved. Summary below.

## Result: 129/129 in all 8 rounds, 0 deletions, 0 test-layer changes

**Iterations:** 3 sweeps. Wave size 2 throughout (1-min load was 4.1–9.3 from co-tenant pipelines, never below the 4.0 threshold). Per-round wall time 84–104 s; a full sweep ≈ 6 min.

**Tests deleted: none.** Both failures reached STEP 3 — PRD covered them verbatim and uniquely determined them.

**`test_suite/` fixes: none. `test_helpers/` fixes: none.**

### `implementation/` fixes

**1. `services/substitution.py::resolve_on_creation` (+ `services/receiving.py::allocate`/`record_receipt`) — a line with a PENDING substitution offer must not be left `FILLED`.**
`test_one_cent_above_the_tolerance_ceiling_leaves_the_offer_pending` failed 8/8 with `assert 'FILLED' == 'CONFIRMED'`. This is impl-gen's judgment call (I).3 — it ran allocation's status write first and let the offer override it, so a still-pending offer left the line `FILLED`. Two PRD sentences settle it against that reading: §3.6 "Approval … moves the line `CONFIRMED → SUBSTITUTED`", and §3.3 "The eight line statuses are … with `FILLED`, `DROPPED`, `ROLLED_FORWARD` and `CANCELLED` **terminal**." A line parked in `FILLED` could never be answered out of, so the ordering is not a free choice. `allocate()` now also returns each line's pre-pass status, and a still-PENDING offer restores it. `allocated_units` is deliberately *left* at the allocated value, because decline "removes the `offered_units` from the line's `allocated_units`" presupposes they are there.

**2. `app.py` + `start.sh` — the intermittent "API server could not be restarted" boot flake (root-caused, not papered over).**
Appeared in 2 of 8 rounds twice. Not a bind-ceiling problem and not boot cost (boot measured at 0.3 s). The runner's port registry allocates via `bind(("127.0.0.1", 0))`, i.e. from the **kernel ephemeral range** 32768–60999 — and all three failing ports (57733, 37275, 60687) were inside it. During the window between the harness's `kill -9` of the previous server and our `bind()`, any co-tenant's outbound `connect()` can take that exact number as its *source* port and block a wildcard bind for the connection's lifetime. A 120-restart stress run on port 19942 (outside the range) was 120/120 clean, confirming it.
Fix: `app.py` now imports **only the stdlib** at module scope and claims the listening socket as the first thing `main()` does; Flask, the 13 blueprints and the dependency check all moved behind it, and `start.sh` dropped its separate probe interpreter. Measured exposure window: **261 ms → 28 ms (9.3×)**. The bind ceiling was also retimed 6 s → 14 s (280 × 50 ms) to sit just inside the harness's 15 s readiness budget rather than giving up at 40% of it.

### Verification (run, not assumed)
All 8 `results.N.json` parse with **129 individual test rows each**, `passed==total==129`, `failed/errors/skipped == 0`; sorted test-name sets **identical across all 8** and equal to the 129 unique `def test_` names in `test_suite/`; zero `skip`/`xfail`/`skipif`/`pytest.mark` anywhere; source-only grep for `test_suite|test_helpers` under `implementation/` is empty (only the results JSON artifacts match); no orphan servers.

**Isolation evidence (positive, cross-file):** `test_helpers/factories.py` hardcodes literal values with **no uniquifier anywhere** (no uuid4/random/counter/suffix in factories or fixtures) for four constraints the implementation enforces — route `code` `R-NORTH`, cycle `code` `CY-MAY`, item `sku` `OAT-25`, member `email` `member@coop.test` (`r_catalog.py:35,112`, `r_cycles.py:29`, `r_members.py:38`, all `ERR_VALIDATION`). 75 world builds across 11 test files re-create all four from scratch. If any state survived a test boundary, builds 2–75 would fail. They don't, in 8 consecutive rounds.

### Reachability hypotheses — both **confirmed** by reading code
- **`DRAFT → VARIANCE_HELD` is structurally unreachable.** `reconciliation.py::draft` computes `club_margin = charges − supplier − freight − reefer − comm` then `variance = charges − (supplier+freight+reefer+comm+club_margin)`, identically 0 for all integer inputs, so the `VARIANCE_HELD` arm of the branch at lines 86–87 is dead. `BALANCED → VARIANCE_HELD` downstream *is* live (line 107): `club_margin_cents` is frozen at draft while `member_charges_cents`/`commission_cents` are recomputed.
- **`SHORT_FILLED → ROLLED_FORWARD` is unreachable.** A drop run reaches `DEFERRED` only at `lock_cascade._hop4` or `_hop6`, and both call `_cancel_drop_orders`, which moves every `CONFIRMED` line to `CANCELLED`. Short-filling only happens at `POST /receipt-lines`, which needs a `RECEIVED` route run — a state a deferred run never reaches. So the source line entering `roll_forward` hop 5 is always `CANCELLED`. (Incidental: hop 5 doesn't filter source status at all, which is broader than PRD's declared two legs, but the difference is unobservable for the same reason.)

### Near-miss register (fair, but by how much?)
1. **`test_approving_an_auto_approved_offer_returns_invalid_offer_state` — distance 1, the closest.** It is the *only* offer response in the entire suite, and `ERR_EXCEPTION_WINDOW_CLOSED` appears nowhere except as a negative assertion in it. Adjudications 3 and 4 (rung 13's `applies_to` treated as operative; the carve-out policed only by rung 38's `exception_state == OPEN`) are therefore completely unexercised. One fixture change — advance the clock past `exception_deadline_at`, or consolidate the cycle — puts the test squarely on them. Its line-105 guard (`!= ERR_EXCEPTION_WINDOW_CLOSED`) is vacuous given line 111 asserts `exception_state == "OPEN"`.
2. **`test_one_cent_above_the_tolerance_ceiling_leaves_the_offer_pending` — distance 1.** Now asserts line status and `unit_price_cents`, both PRD-pinned. Adding `allocated_units` would land on genuinely two-sided PRD text: approval "with `allocated_units` **set to** the offer's `offered_units`" reads as *not yet there*, decline "**removes** the `offered_units` from the line's `allocated_units`" reads as *already there*. `line_gross_cents` on a reverted-to-`CONFIRMED` line is likewise PRD-silent.
3. **`test_a_failed_authorization_records_the_same_figure_and_the_retry_succeeds` — distance 2.** Its fixture leaves the cycle `LOCKED`, inside the permitted list, so it passes under both the symmetric and asymmetric readings of adjudication 2. Discriminating it needs a cycle outside the list *and* an order still in `LOCKED`/`FILLED`/`SHORT_FILLED` — two changes, and arguably unreachable, which makes that adjudication low-risk.
4. **`supplier_cost_cents` (adjudication 1) — distance 1 but benign.** No test asserts a value; test_10 only asserts the ledger identity, which holds under *any* cohort reading because `club_margin` is a residual. One added `assert recon["supplier_cost_cents"] == N` would depend on it — though `RECEIVED-or-SETTLED` and `SETTLED-only` coincide once `deliver` has moved every drop run.
5. **Adjudication 7 (hop-5 `OPEN`-or-`QUALIFIED` union) — not a near-miss.** Provably safe rather than luckily safe: pre-lock every drop run is `OPEN`, and after hop 4 none is, so a mixed population is not observable and the two readings coincide everywhere.

---

**Orchestrator verification of Step 7** (independent re-parse): 8 `results.N.json`, **129 rows each**, `passed=129 total=129 failed=0`, status set exactly `{'passed'}`, sorted-name sha256 `f1519b2d7c73` **identical across all 8**; `find test_suite test_helpers workspace/implementation -newer results.1.json -name '*.py'` → **empty** (nothing was edited after the clean sweep, so the sweep tested exactly the code that now sits on disk); no orphan `app.py` processes remain.

**Note on the boot-flake root cause — this is new and generalises beyond this task.** Prior runs treated the intermittent "API server could not be restarted" as a bind-retry-ceiling problem and tuned the ceiling. Step 7 measured it instead: the runner's port registry hands out ports from the **kernel ephemeral range**, so a co-tenant's outbound `connect()` can steal the exact port number as its *source* port during the kill→bind window. The real fix is to **shrink the window** (stdlib-only imports at module scope; claim the socket as the first act of `main()`; 261 ms → 28 ms), not to lengthen the ceiling. The ceiling was nonetheless retimed 6 s → 14 s to sit just inside the harness's 15 s readiness budget instead of surrendering at 40% of it.

**Step 8 is NOT skipped** — Step 7 applied 2 `implementation/` fixes (one behavioral, one infrastructural).

## Step 8: Finalize PRD — 2026-08-09T08:00:00.000Z

Subagent summary, verbatim:

---

`PRD_FINALIZED.md` written. **One edit**, in §3.6.

## Counts
- `PRD.md` 577 lines / 17635 words · `PRD_FINALIZED.md` 577 lines / 17894 words
- Line delta 0 (+0.00%); word delta +259 (+1.47%). One paragraph (line 330) extended in place; no new sections, no other bytes touched.

## Changes
- **§3.6 (para. "Most offers never dwell", line 330) — insert — a line whose substitution offer is left `PENDING` keeps the allocation's `allocated_units` / `short_units` / `allocation_remainder_rank` / `line_gross_cents`, but its *status* is put back to the one it held immediately before this receipt's allocation pass (`CONFIRMED`, or `SHORT_FILLED` if an earlier receipt had already part-filled it); a line so held at `CONFIRMED` is excluded from `received_subtotal_cents`, the pallet plan and the reefer split, while still participating in a later receipt's allocation and still counting toward the order's `FILLED`/`SHORT_FILLED` settlement — `services/substitution.py:57-68`, `services/receiving.py:32-72,124-135`.**

### Why the two quoted sentences were not sufficient
Step 7's quotes (§3.6 "Approval … moves the line `CONFIRMED → SUBSTITUTED`" + §3.3 "`FILLED` … terminal") rule *out* `FILLED`. They do not rule *in* any particular replacement, and the impl's actual rule — **restore the pre-pass status**, which is `SHORT_FILLED` when an earlier receipt had already part-filled the line — is not derivable from them (they would suggest `CONFIRMED` unconditionally). More importantly the PRD nowhere admitted the state the fix creates: a line in `CONFIRMED` (or `SHORT_FILLED`) carrying non-zero `allocated_units`/`line_gross_cents`. Three pre-existing sentences silently mis-describe that state — §3.6's `received_subtotal_cents` ("summed as `allocated_units` multiplied by `unit_price_cents`", no status filter) and §3.7's pallet plan and reefer split ("every **allocated** unit … only `short_units`, dropped and cancelled contribute nothing") would all include the held line, whereas the impl's `MONEY_LINE_STATES` / `ALLOCATED_STATES` exclude it. Those exclusions had to be pinned or the fix would be a fresh PRD/impl divergence.

### Items that licensed no edit
- **Item 2 (`app.py` + `start.sh` boot flake)** — purely infrastructural: process startup order, socket claim timing, bind ceiling. The PRD specifies an HTTP contract, not a launcher. No edit.
- **Both reachability hypotheses** (`DRAFT → VARIANCE_HELD`, `SHORT_FILLED → ROLLED_FORWARD`, and the broader roll-forward hop-5 source filter) — explicitly context, not fixes, and out of the hard scope. The hop-5 divergence is real but unobservable, and no `<step_7_diff>` fix traces to it. No edit.

## Pre-edit search log (edit 1)

**(a) Subject identified.** The status and derived figures of an order line whose substitution offer resolves to `PENDING` — i.e. every producer and every consumer of `OrderLine.status` / `allocated_units` on the receiving-and-substitution axis.

**(b) Impl paths enumerated (read or grepped, not just the Step 7 site).**
- Producers of line status/allocation: `services/receiving.py:32-72` (`allocate`), `:75-98` (`settle_orders`, `FULFILMENT_LINE_STATES` incl. `CONFIRMED`), `:107-138` (`record_receipt` call order: allocate → create/resolve offers → settle → refresh subtotals); `services/substitution.py:44-68` (`resolve_on_creation` restore), `:71-79` (`apply_substitute`), `:82-93` (`apply_removal`), `:96-106` (`_after_line_change`).
- Other callers of the same mutators: `routes/r_receiving.py:160-177` (approve/decline), `services/cycle_ops.py:78-91` (consolidation silence-decline → `apply_removal`).
- Consumers of line status: `services/recompute.py:13-14` (`MONEY_LINE_STATES` excludes `CONFIRMED`; `ESTIMATE_LINE_STATES` includes it), `:67-84` (`recompute_order_money`), `:87-101` (`estimated_total`/estimate), `:106-136` (`live_drop_subtotal`, `locked_drop_subtotal`), `:172-192` (`_received_value`, drop/route `received_subtotal_cents`); `services/payments.py:37-52` (`capture_figures`, same money states); `services/consolidation.py:12-13,50-61,117-124` (`ALLOCATED_STATES` for the pallet plan and the cold-value reefer split), `:35,130` (`FREIGHT_ORDER_STATES`, order-level); `services/receiving.py:7` (`PARTICIPATING_STATES` — a restored `CONFIRMED` line re-enters the next allocation, where a `FILLED` line would not); `services/lock_cascade.py:76,94,169,189` and `services/droprun_ops.py:79,140,148` and `services/cycle_ops.py:154` (all pre-receipt paths — confirmed unreachable while an offer is pending); `services/reconciliation.py`, `services/commission.py` (post-consolidation, by which point every `PENDING` offer has auto-declined — no `CONFIRMED`-with-allocation line survives).
- Cross-checked PRD text that the new state could falsify: §2.4 versioning ("incremented by exactly 1 on **every mutation**" — the fix's second `touch` on the same line in one request is already licensed, no edit), §2.7 substitution tolerance, §2.11 invariant 1 (holds: `short_units = confirmed − allocated` is preserved by the restore), §3.6 allocation and response paragraphs, §3.7 freight/pallet/reefer, §3.8 capture step 1.

**(c) Wording adjustments made during the search.**
1. First draft said the held line reverts to `CONFIRMED`. `receiving.py:7,40` showed `before_status ∈ {CONFIRMED, SHORT_FILLED}` and that a second receipt on an already-part-filled line reaches the `SHORT_FILLED` branch — **widened** to "the status it held immediately before this allocation pass", naming both cases.
2. First draft applied the money/pallet exclusions to "a line carrying a pending offer". `recompute.py:13` showed `SHORT_FILLED` **is** a money/allocated state — **re-scoped** every exclusion to "a line sitting at `CONFIRMED` with a pending offer" and added the closing sentence that a line held at `SHORT_FILLED` counts normally.
3. First draft used the universal "every downstream figure that reads what was allocated". `receiving.py:83-97` showed the order's fulfilment settlement *does* read the held line's `allocated_units` — **replaced the universal with a closed enumeration** (`gross_cents`/`split_fee_cents`, `received_subtotal_cents`, pallet plan, reefer split) and added an explicit counter-clause covering order settlement and re-participation in later allocation.
4. Dropped a planned restatement of the `gross_cents` exclusion once §3.8 step 1 was found to already list `CONFIRMED` as contributing 0 — the edit now cites §3.8 instead of duplicating (and risking drift from) it.

---

**Orchestrator verification of Step 8:** 577 → 577 lines, 17,635 → 17,894 words (+259, +1.47%); `diff` of all `^#` headings between PRD.md and PRD_FINALIZED.md is **empty** — no structural change, one in-paragraph insert as claimed.

**Worth recording: the single edit is a case of "a Step-7 fix whose real subject is wider than the fix site."** Step 7 concluded the PRD already pinned the behaviour (two verbatim sentences ruling `FILLED` out) and therefore made no PRD claim. Step 8 correctly found that ruling a value *out* is not the same as pinning a value *in* — and, more consequentially, that the fix creates a state the PRD never contemplated (a `CONFIRMED` line carrying non-zero `allocated_units`), which three *pre-existing* sentences elsewhere in §3.6/§3.7 silently mis-describe. **A Step-7 "PRD already covers this" verdict is about the assertion the test made, not about the state the fix introduces** — Step 8 must still ask what new states the fix makes reachable and which existing prose those states falsify.

## Step 9: Complete PRD — 2026-08-09T10:07:00.000Z

Interrupted mid-scan at 09:2x UTC by an Anthropic session limit. **Resumed via `SendMessage` to the same agent id rather than restarted**, so the scan's context (already-classified impl paths, already-committed edits) survived; `PRD_COMPLETED.md` was intact on disk at that point (586 lines, headings matching, file ending correctly on the §5 table) and the agent continued from the reconciliation-draft item.

Subagent summary, verbatim:

---

Done. `workspace/PRD_COMPLETED.md` is complete.

## Scale

| | source `PRD_FINALIZED.md` | `PRD_COMPLETED.md` | delta |
|---|---|---|---|
| lines | 577 | 586 | +9 |
| words | 17,894 | 22,385 | +4,491 |
| chars | 123,723 | 151,756 | **+28,033** |

All `^#` headings byte-identical to source; both markdown tables still 154 rows; no new sections; every change is an in-paragraph insert or revision.

**66 changes total — 55 ambiguity-pins, 11 mismatch-revisions.**

## R1 verdict — both CONFIRMED by my own reading

- **`DropReconciliation DRAFT → VARIANCE_HELD` — CONFIRMED unreachable.** `services/reconciliation.py:69-70` defines `club_margin = charges - supplier - freight - reefer - comm` and then `variance = charges - (supplier + freight + reefer + comm + club_margin)`. The second expression is the first substituted into itself, so `variance` is algebraically `0` for **every** fresh draft regardless of inputs; the branch at :86-87 therefore always takes `BALANCED`. `VARIANCE_HELD` is live only from `BALANCED` via `recompute_downstream` (:107-108), which rewrites `member_charges_cents`/`commission_cents` while leaving the frozen `club_margin_cents` alone.
- **`SHORT_FILLED → ROLLED_FORWARD` — CONFIRMED unreachable.** I grepped every drop-run status assignment: `DEFERRED` is written in exactly two places, `lock_cascade.py:179` (hop 4) and `:215` (hop 6). Both immediately call `_cancel_drop_orders`, which cancels every `LOCKED` order and its `CONFIRMED` lines. `SHORT_FILLED` is only ever written in `receiving.py:64` and `substitution.py:87`, both of which need the route run at `RECEIVED` and the line still a participant — impossible on a run whose lines the deferral already cancelled. So the source lines a roll-forward finds are only `CANCELLED` or `DROPPED`, and the `short_units` branch of the quantity rule is dead.
- **The related broader-than-declared note is also CONFIRMED:** `droprun_ops.py:120` selects `[l for l in lines_of_order(order) if l["rollover_opt_in"]]` with **no status filter at all**, and iterates orders of the source run with no status filter either. This makes `DROPPED → ROLLED_FORWARD` a genuine third leg (a `DROP`-policy line rolls at its original `qty_units`, not at the zero its `confirmed_units` fell to) — pinned in §3.5.

## R2 — all seven adjudications verified and pinned

(1) cohort `("RECEIVED","SETTLED")` at `reconciliation.py:17,44-45` — **revised** §3.9, which read literally-`RECEIVED`. (2) cycle-status precondition guarded by `outcome=="SUCCEEDED" and payment_status=="UNPAID"` at `r_orders.py:135-137` — pinned. (3)+(4) `_respond_prelude` (`r_receiving.py:139-157`) never touches `cycle["status"]`; only rung 38's `exception_state` — **revised** rung 13 and §3.6, both of which asserted a `RECEIVED` precondition. (5) both legs plus the unfiltered breadth — revised. (6) `want = apply_credit if supplied else credit_cap` at `r_orders.py:173` — pinned. (7) `recompute_route_aggregate` sums the `("OPEN","QUALIFIED")` union literally — **already correctly pinned by the source PRD; 0 edits.**

## Per-question yield

Several edits serve more than one question, so these sum above 66.

| | yield |
|---|---|
| Q1 fields nobody reads | 7 |
| Q2 universals | 8 |
| Q3 derived-on-read vs stored | 5 |
| Q4 serializer projections | 3 |
| Q5 list semantics | 3 |
| Q6 cascade legs that don't fire | 12 |
| Q7 version ledger | 8 |
| Q8 unenforced uniqueness/scope | 5 |
| Q9 error precedence | 17 |
| Q10 timestamps | 4 |
| R1 | 3 |
| R2 | 6 |

**Q9 and Q6 carried the run.** Q9's yield is mostly a class the ladder itself created: seven preconditions the impl enforces that are *not* numbered rungs (merge's cycle-`OPEN`, seal's cycle-`RECEIVED`, authorize/capture cycle status, submit's `ACTIVE` check, submit's no-line check, lapse, re-discontinue), each with a pinned position interleaved among the rungs. Q1's biggest single find is an 18-field reporting-only roster — figures the impl writes and no rule ever reads.

## Every change

**§2 global**
- §2.1 — revise — mismatch — the ClubAdmin-superset universal is false for `/substitution-offers/{id}/approve` and `/decline`, which admit `Member` alone — `routes/r_receiving.py:161,171`
- §2.1 — insert — ambiguity — rung 27 cannot police drop-run *creation*, so a coordinator may open a run on a drop point they do not coordinate — `routes/r_dropruns.py:19-29`
- §2.2 — insert — ambiguity — `api_request_timestamp` is a logical-clock reading; `api_request_id` is a zero-padded base-36 counter, not random — `core/envelope.py:9-13`, `core/store.py:80-88`
- §2.3 — insert — ambiguity — pagination parses stripped canonical decimals only; `has_more` formula — `core/ladder.py:138-161`, `core/envelope.py:32`
- §2.3 — insert — ambiguity — write-order is the universal tie-break behind `created_at`; case aggregates tie on route-run order — `core/store.py:112-115`, `services/lock_cascade.py:98-106`
- §2.3 — insert — ambiguity — free-form filters never error; unknown query params ignored; three undocumented filter sets — `core/ladder.py:280-282`
- §2.4 — insert — ambiguity — direct writes bump unconditionally, derived recomputes bump only on change — `core/store.py:126-139`
- §2.4 — insert — ambiguity — `version` advances per mutating *step*, not per request; three double-bump sites named — `services/receiving.py:136-137`
- §2.5 — insert — ambiguity — clock endpoint echoes the caller's string byte-verbatim; clock read per-operation — `routes/r_credits.py:60-66`
- §2.5 — insert — ambiguity — the full derived-on-read set; three timestamp kinds; which stamps are set once — `core/clock.py:37-42`, `core/serialize.py:18-54`
- §2.5 — insert — ambiguity — the 18-field reporting-only roster — `core/serialize.py`
- §2.6 — insert — ambiguity — write-order tie-break makes every ordering total — `core/store.py:146-147`
- §2.9 intro — insert — ambiguity — the seven ladder-adjacent preconditions and their positions — various
- §2.9 r8 — revise — ambiguity — closed iff-list of enum fields and filters — `core/ladder.py:246-256`
- §2.9 r12 — insert — ambiguity — a receipt line gates on *every* drop run of its route run — `routes/r_receiving.py:61`
- §2.9 r13 — revise — mismatch — rung 13 is not evaluated on substitution responses at all — `routes/r_receiving.py:139-157`

**§3.1–3.2**
- §3.1 — insert — ambiguity — `home_drop_point_id` validated, stored, filterable, never consulted — `routes/r_members.py:31-43`
- §3.1 — insert — ambiguity — `term_years` integer ≥1 at rung 7 — `routes/r_members.py:79`
- §3.1 — insert — ambiguity — `ACTIVE → ACTIVE` dues self-loop discards the unexpired remainder — `routes/r_members.py:88-92`
- §3.1 — revise — ambiguity — lapse refusal is `ERR_VALIDATION`, also for non-`ACTIVE` status — `routes/r_members.py:142-144`
- §3.1 — insert — ambiguity — `lifetime_dues_paid_cents` never read; proration ceiling to microseconds — `routes/r_members.py:104-107`
- §3.1 — insert — ambiguity — grant `expires_at` verbatim when hand-minted, +180d when rule-minted — `routes/r_credits.py:23`, `services/credits.py:75-77`
- §3.2 — insert — ambiguity — naming a coordinator is not a mutation of the member row — `core/serialize.py:35-39`
- §3.2 — insert — ambiguity — re-discontinuing yields `ERR_ITEM_DISCONTINUED` — `routes/r_catalog.py:151-152`
- §3.2 — insert — ambiguity — `split_unit_base_cents` never consulted — `routes/r_catalog.py:176`
- §3.2 — insert — ambiguity — the four uniqueness constraints route to `ERR_VALIDATION`, exact string equality — `r_catalog.py:33,110`, `r_members.py:36`, `r_cycles.py:27`

**§3.3–3.5**
- §3.3 — insert — ambiguity — duplicate cycle `code` → `ERR_VALIDATION`, ordering checked first; instants verbatim — `routes/r_cycles.py:25-31`
- §3.3 — insert — ambiguity — window conflict ignores the other cycle's status; tested only when minting — `services/droprun_ops.py:30-43`
- §3.3 — revise — ambiguity — merge requires cycle `OPEN` (`ERR_INVALID_CYCLE_STATE`, rungs 18↔25); repointed orders bump — `r_dropruns.py:71-73`, `droprun_ops.py:66-87`
- §3.3 — insert — ambiguity — live drop subtotal: `DRAFT` orders count, priced at clock-now, missing price → 0, discounted ≡ subtotal pre-lock — `recompute.py:106-122`, `pricing.py:44-54`
- §3.3 — insert — ambiguity — patch/cancel bump unconditionally; only cancel recomputes the estimate; `PENDING` submitter gets `ERR_MEMBERSHIP_LAPSED`; empty order → `ERR_VALIDATION` — `r_lines.py:145-177`, `r_orders.py:88-93`
- §3.4 — insert — ambiguity — the lock is atomic on price-binding failure — `services/lock_cascade.py:26-35`
- §3.4 — insert — ambiguity — aggregate `case_price_cents`/`remainder`/`overage`/`dropped` are snapshots — `lock_cascade.py:148-161`
- §3.4 — revise — ambiguity — hop 4 recomputes for every order and drop run on the cycle — `lock_cascade.py:164-170`
- §3.4 — revise — ambiguity — `tier_discount_cents` is 0 at the lock, so discounted ≡ subtotal — `recompute.py:125-136`
- §3.4 — revise — ambiguity — the lock bumps once per hop, up to three times for one order — `lock_cascade.py`
- §3.5 — revise — mismatch — hop 5 filters on `rollover_opt_in` and nothing else; `DROPPED` leg live; `SHORT_FILLED` leg unreachable — `droprun_ops.py:119-147`
- §3.5 — insert — mismatch — the authorization-void leg is conditional on a `SUCCEEDED` authorization existing — `cycle_ops.py:13-26`

**§3.6–3.7**
- §3.6 — insert — ambiguity — `cases_received` of 0 is legal and re-runs allocation — `routes/r_receiving.py:58`
- §3.6 — revise — mismatch — "every one of its lines" narrows to five statuses, orders only in `LOCKED`/`FILLED`/`SHORT_FILLED` — `receiving.py:75-98`
- §3.6 — revise — ambiguity — an "affected line" is one this pass raised; offered price uses the substitute's `case_pack_units` and the line's `qty_units` — `receiving.py:127-133`, `substitution.py:17-22`
- §3.6 — insert — ambiguity — `Member` only; offer-state → ownership → window ordering — `r_receiving.py:139-157`
- §3.6 — revise — mismatch — the rung-13 carve-out is by omission; cycle status never examined — `r_receiving.py:145-154`
- §3.6 — insert — ambiguity — `allocation_remainder_rank` read by no later rule — `receiving.py:56`
- §3.7 — insert — ambiguity — invoice figures are integers ≥0; the submission is repeatable — `r_routeruns.py:47-48`
- §3.7 — insert — ambiguity — freight level two re-recomputes each order's money (second bump) — `consolidation.py:42`
- §3.7 — insert — ambiguity — the plan is computed before persistence, so a capacity refusal writes nothing; a repeat build appends a second plan — `consolidation.py:65-111`
- §3.7 — revise — ambiguity — cold value restricted to `FILLED`/`SHORT_FILLED`/`SUBSTITUTED` lines — `consolidation.py:116-125`
- §3.7 — insert — ambiguity — sealing off a non-`RECEIVED` cycle → `ERR_INVALID_CYCLE_STATE`, after the pallet-state test — `r_routeruns.py:108-111`

**§3.8–§5**
- §3.8 — revise — ambiguity — cycle-status tested only for `SUCCEEDED`+`UNPAID`; `FAILED` admitted from `UNPAID` only — `r_orders.py:127-137`
- §3.8 — insert — ambiguity — `estimated_total_cents` written on both outcomes — `r_orders.py:138-139`
- §3.8 — insert — ambiguity — omitting `apply_credit_cents` means "spend up to the cap"; ≥0; 0 honoured — `r_orders.py:156-174`
- §3.8 — insert — ambiguity — capture is a write-nothing projection until both fiscal rungs clear; the sweep sits between rungs 51 and 52 — `r_orders.py:167-181`
- §3.8 — insert — ambiguity — the `REFUND` payment's `method` is the `destination` — `r_orders.py:203`
- §3.9 — revise — mismatch — the quarter-hour convention is not enforced — `r_volunteers.py:33`
- §3.9 — insert — mismatch — volunteer hops 3 and 4 fire only on the false→true flip — `r_volunteers.py:111-113`
- §3.9 — insert — ambiguity — accrual starts with null `payout_mode`, 0 `payout_value_cents` — `commission.py:43-44`
- §3.9 — insert — mismatch — clawback is replaced not accumulated, keyed on this refund alone; `ADJUSTED` re-adjusts — `commission.py:72-86`
- §3.9 — insert — ambiguity — hop 4 reaches exactly the live reconciliation; `club_margin` frozen; one-way to `VARIANCE_HELD`; bumps unconditionally — `reconciliation.py:92-110`
- §3.9 — insert — ambiguity — drafting has no drop-run-status and no cycle-status precondition — `r_recon.py:19-34`
- §3.9 — insert — ambiguity — drafting bumps the drop run's `version` — `r_recon.py:33`
- §3.9 — revise — mismatch — supplier-cost cohort is `RECEIVED`-or-`SETTLED` — `reconciliation.py:17,44-45`
- §3.9 — insert — ambiguity — which two of the six ledger figures are recomputed; a fresh draft's variance is identically 0 — `reconciliation.py:63-89`
- §3.9 — revise — mismatch — `DRAFT → VARIANCE_HELD` unreachable; `VARIANCE_HELD` reached only from `BALANCED` — `reconciliation.py:69-87`
- §4 — insert — ambiguity — one projection per entity, identical across all endpoints, taken after every mutation (no stale `version`) — `core/serialize.py:351-379`
- §5 — insert — ambiguity — unknown path → `ERR_VALIDATION`/404, bad method → `ERR_VALIDATION`/405 — `app.py:93-99`

---

**Orchestrator verification of Step 9:** 577 → 586 lines, 123,723 → 151,756 chars (+28,033); `diff` of all `^#` headings PRD_FINALIZED vs PRD_COMPLETED **empty**; markdown table rows 154 → 154 (both the 82-row endpoint table and the 68-row error table intact); `find test_suite test_helpers workspace/implementation -name '*.py' -newer results.1.json` → **empty** (no code touched after the clean sweep, so the 8 green rounds still describe the shipped tree); all 8 `results.N.json` re-parsed → 129/129/0.

## PIPELINE COMPLETE — 2026-08-09T10:08:00.000Z

**129/129 on all 8 rounds. 0 test deletions, 0 test-layer fixes, 2 implementation fixes (1 behavioral + 1 infrastructural).**

Final artefact set: `SCAFFOLD.yaml` (4,403 lines) · `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (7,623) · `SCAFFOLD_CORNER_DESIGN.yaml` (20,633) · `test_helpers/` (9 modules) · `test_suite/` (13 files, 129 tests) · `workspace/PRD.md` (577 L) · `workspace/PRD_FINALIZED.md` (577 L, +1 edit) · `workspace/PRD_COMPLETED.md` (586 L, +66 edits) · `workspace/implementation/` (35 modules, 4,628 lines) · `workspace/sweep.sh` · 8 × `results.N.json`.

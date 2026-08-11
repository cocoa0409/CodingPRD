# Worklog — task_0953_kids_clothing_rent_swap

Scenario (verbatim): `953. Kids' Clothing Rent & Swap Subscription: box & size, wear-and-return/swap cadence, condition grading & cleaning, buy-out option, outgrown trade-in credit, seasonal capsule, shipping/label, pause`

Difficulty parameter: **beyond-Expert** ("harder than Expert"), routed as a calibration input to the Step-2 scaffold-generator. Full pipeline Steps 1–9 runs to completion.

## Step 1: Create task directory — 2026-08-09T15:01:30.000Z

Created `tasks/task_0953_kids_clothing_rent_swap/` and `tasks/task_0953_kids_clothing_rent_swap/workspace/`. Index 0953 = max existing index in `tasks/` (0952) + 1.

## Step 2: Generate scaffold — 2026-08-09T16:12:00.000Z

All three artifacts are written and lint clean.

### Files
- `SCAFFOLD.yaml` (§1.0–§1.7 + `global_constants` + `gate_precedence`)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

### Surface counts
| Dimension | Count | Target |
|---|---|---|
| entities | 21 | 19–22 ✓ |
| endpoints | 126 | 95–115 (over by 11) |
| error codes | 95 | 75–95 ✓ |
| state machines | 16 (8 non-linear) | 12–16, ≥5 non-linear ✓ |
| calculations | 61 (9 with declared `variants`, 11 dual-variant formulas incl. in-formula VARIANT branches) | 40+, ≥8 dual ✓ |
| validations | 68 rungs, one ladder, 1–68 contiguous | 60+/55 rungs ✓ |
| roles | 8 | 7+ ✓ |
| OCC rules | 3 | 2+ ✓ |
| conservation invariants | 4 (units, slots, credit, swap entitlements) | 3+ ✓ |
| `gate_precedence` gates | 12, total order, all 126 endpoints name a subsequence | 8+ ✓ |
| cascade depth | 7 (lost-shipment) and 7 (trade-in credit) | ≥6 ✓ |

Endpoints overshoot the stated band; kept the surface because trimming would have broken FK reverse-reachability or enum closure. Everything else sits inside the band.

### Non-linear state machines (8)
- **Member** — two bidirectional pairs on one row: ACTIVE⇄PAUSED and ACTIVE⇄DELINQUENT.
- **GarmentUnit** — re-entrant circulation loop IN_STOCK→RESERVED→OUT→INBOUND→PROCESSING→IN_STOCK, plus a LOST_IN_TRANSIT→PROCESSING recovery edge.
- **BoxItem** — parallel axes `fulfillment_status × settlement_status`; terminal condition is a pair.
- **TradeInItem** — parallel axes `grading_status × disposition_status`.
- **ShippingLabel** — capped reissue cycle (VOIDED/EXPIRED→ISSUED, cap 2, carried along the self-referential `replaces_label_id` chain).
- **ConditionAssessment** — capped regrade loop SUBMITTED⇄DISPUTED (cap 2), shared by both pipelines.
- **ProcessingJob** — capped rework cycle IN_PROGRESS⇄FAILED (cap 2), each traversal accruing 50% of base cost into the cost-cap retirement threshold.
- **LostShipmentClaim** — bidirectional INVESTIGATING⇄AWAITING_MEMBER_INFO.

### Structural device
Pipeline R (rental circulation) and Pipeline T (trade-in intake) share the *same numbered rungs* for grading (30, 51), label machinery (29, 37, 50), existence (6–13), auth (1–5) and the money ledger (58–60, 66), and diverge on ownership transfer, credit direction, standing/pause gating (rung 17 vs 18, deliberately distinct error codes), and gate subsequence. Each validation row carries a `pipelines: [R, T]` marker.

### Declared constants
80 declared, **0 undeclared**. The 11 remaining ALL_CAPS tokens flagged by the sweep (`ACTUAL_DAYS`, `COST_CAP`, `LATE_FEE`, `PRO_RATA_CAP`, …) are all enum members or variant names, not constants.

### §1.8 / §1.9 instance counts
- **§1.8 — 22 instances** across 9 rules: dual_variant 3, combinatorial 3, non_linear_sm 2, cascade 2, priority_conflict 2, boundary 3, cross_entity 2, temporal_overlap 2, conservation 3.
- **§1.9 — 144 instances** (135 with recipes + 9 `excluded_because` stubs), per section against surface:

| section | instances | surface |
|---|---|---|
| entities | 23 | 21 entities |
| state_machines | 17 | 16 SMs |
| calculations | 21 (3 stubs) | 61 calcs |
| validations | 19 | 68 rungs |
| endpoints | 7 (1 stub) | 126 endpoints |
| errors | 39 (2 stubs) | 95 errors |
| rbac | 8 | 8 roles |
| cross_cutting_complexity_layers | 8 (3 stubs) | 6 layers |
| consistency_model | 2 | 1 model |

All nine claim-extraction-guide sections present. Every declared error except the four conservation guards is exercised. 166 unique instance names, 0 collisions, 0 unbound `${var}`, 0 dangling `grounds`.

### Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    126
  §1.1 entities declared:     21
  §1.8 instances scanned:     22
  §1.9 instances scanned:     135
  Calls scanned (§1.8+§1.9):  1715

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
YAML `safe_load` passes on all three files (two rounds of fixes needed: bare `?` optional-field markers inside `input:` flow sequences, and `$.data[0].id` capture paths whose `[` opened a flow sequence inside a flow mapping — both now quoted).

### Reachability dead-ends found and how they were resolved
1. **NEVER_SCANNED liability variant was unreachable.** `mark-lost` required `IN_TRANSIT`, but `depart` sets `ever_scanned = true`, so the 0.60 member share could never fire. **Fixed** by adding a `Shipment CREATED → LOST` transition (parcel handed over, never scanned), which is now the only producer of the variant; the claim filing window falls back to `created_at` when `shipped_at` is null.
2. **`POST /lost-shipment-claims` was unreachable** because `mark-lost` auto-created the claim. **Fixed** by removing auto-creation; filing is now the sole producer, which makes `ERR_CLAIM_WINDOW_CLOSED` and `ERR_CLAIM_SHIPMENT_NOT_LOST` reachable. The lost-shipment cascade still runs 7 hops without the claim hop.
3. **`ERR_BUYOUT_BELOW_FLOOR` was unreachable** as originally worded (the floor is applied, so the price can never settle below it). **Rewrote rung 61** as a genuine precondition: a unit whose style retails below `BUYOUT_MIN_PRICE_CENTS` may not be quoted.
4. **`ERR_WAIVER_CAP_EXCEEDED` was unreachable** — `damage_fee_after_waiver` uses `min(gross, remaining_cap)` and the WAIVED transition's precondition already excludes over-cap cases, so no error path existed. **Replaced with `ERR_WAIVER_NOT_AVAILABLE`** on rung 62, reachable *only* by a two-step setup (waive the PROTECTION_FEE charge, then confirm a waiver-band grade) — this also satisfies the brief's "error whose reachability requires a two-step setup".
5. **Four conservation errors remain intentionally unreachable** through the public surface: `ERR_UNIT_/SLOT_/CREDIT_/SWAP_CONSERVATION_VIOLATION`. Every ordinary sequence is refused by an earlier gate. They are annotated in §1.6 as *defensive invariant guards* and are the only errors with no §1.9 instance — flagging this for downstream so the test-generator does not chase them.
6. **`CAPSULE_ELIGIBILITY_MIN_COMPLETED_CYCLES` was lowered from 2 to 1** — at 2, every capsule test needed two full closed cycles. At 1 it is still reachable (and `ERR_CAPSULE_ELIGIBILITY_NOT_MET` stays reachable for a fresh member), and an empty cycle can be driven OPEN→SWAP_CLOSED→RETURN_DUE→CLOSED in five calls.
7. **`TRADEIN_CREDIT_CAP_PER_SUBMISSION_CENTS` was lowered from 12000 to 6000** so the SEQUENTIAL_CAP vs PRO_RATA_CAP divergence is observable with a 3-item submission instead of 6, keeping those chains executable.
8. **`ERR_PAUSE_LIFETIME_CAP_EXCEEDED` is reachable only across rolling years** — the 30-day period cap means 90 lifetime days need three pauses in three distinct 365-day windows. The §1.9 instance drives the clock across 2026→2029 to reach it; this is a real (intended) coupling between rungs 48 and 49, not a defect.

### Two §1.5 endpoints added under the priority ladder
`POST /kidswear/members/{member_id}/charge-adjustments` and `.../credit-adjustments` (both BillingAgent, rung 2 of the ladder — general business endpoints, not `/_` test-driving hooks). Without them, reaching DELINQUENT standing or a seeded credit balance required a full lost-shipment or trade-in chain in dozens of otherwise-unrelated corner instances.

## Step 3: Copy shared files — 2026-08-09T16:14:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0953_kids_clothing_rent_swap/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-09T16:31:00.000Z

The PRD is complete and all three hard contracts pass.

**Output:** `workspace/PRD.md` — 721 lines, ~20,300 words, written in 14 bounded Write/Edit calls (no single giant write).

**Per-section line budget**

| Section | Lines | | Section | Lines |
|---|---|---|---|---|
| §1 Introduction | 8 | | §3.1 Households, plans, size ladder | 20 |
| §2 heading | 2 | | §3.2 Cycle calendar & charges | 22 |
| §2.1 Roles & identity | 19 | | §3.3 Catalog, stock, filling a box | 18 |
| §2.2 Response structure (verbatim) | 49 | | §3.4 Swaps | 14 |
| §2.3 Pagination | 6 | | §3.5 Labels, shipments, lost parcels | 22 |
| §2.4 Identity, versions, logical clock | 10 | | §3.6 Return, grading, cleaning, retirement | 26 |
| §2.5 Twelve gates | 28 | | §3.7 Buy-out | 12 |
| §2.6 Sixty-eight rungs | 112 | | §3.8 Capsules | 12 |
| §2.7 Money & pinned order | 20 | | §3.9 Pipeline T trade-in | 24 |
| §2.8 OCC | 10 | | §3.10 Pause | 14 |
| §2.9 Validation & enum routing | 8 | | §3.11 Ledgers | 10 |
| §2.10 Conservation invariants | 9 | | §4 Endpoint table | 133 |
| §2.11 Two pipelines, one ladder | 6 | | §5 Error table | 103 |

**Confirmation counts**

- Endpoints documented: **126 / 126** (4-column table, method + path + description + roles; request/response shapes and side effects specified in §2/§3 narrative per skill rule).
- Error IDs mentioned by exact identifier in §2/§3 prose with trigger conditions: **95 / 95** (0 appear only in the §5 table).
- Constants with literal values: **80 / 80** (78 `global_constants` + `ROUTE_BASE_COST_CENTS` and `DEMAND_BAND_ORDINALS`, which the scaffold declares only inside `calculations`).
- Ladder rungs rendered: **68 / 68**, each tagged `[R]`, `[T]` or `[R+T]` (25 shared), each with its check, error id, HTTP status and `applies_to` scope.
- Gates rendered: **12 / 12**, as a stated total order, with the four `ordering_consequences` spelled out, and every write endpoint traceable to its gate subsequence.
- Entities 21, state machines 16 (115 transitions), calculations **61 / 61**, concurrency rules 3, conservation invariants 4, roles 8 — all covered.

**Contract reports**

```
Field coverage check:
- entities[].fields: 173 required identifiers (fields + request_body + query_params + path_params + computed-output keys), 173 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 68 checked, 68 expressed in prose (numbered, in order), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 115 checked, 115 fully expressed, 0 missing
- calculations[]: 61 checked, 61 fully expressed (all 11 dual-variant pairs rendered with equal density), 0 missing
- validations[] conditions: 68 checked, 68 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 126 checked, expressed, 0 missing
- entities[].fields[] structured content: all defaults/initials/sources reconstructible, 0 missing
- sibling-branch symmetry: 14 groups checked (RETURN_DUE→GRACE vs SWAP_CLOSED→GRACE; GRACE→CLOSED vs RETURN_DUE→CLOSED; VOIDED→ISSUED vs EXPIRED→ISSUED; SUBMITTED→CONFIRMED vs DISPUTED→CONFIRMED; OPEN→SETTLED vs OPEN→WAIVED; IN_TRANSIT→LOST vs CREATED→LOST; sequential vs pro-rata cap; PER_DAY vs FLAT_TIER; CYCLES_WORN vs MONTHS_HELD; standard vs capsule fill; SCANNED vs NEVER_SCANNED; THIRTY_DAY vs ACTUAL_DAYS; OPEN→CLOSED vs EMBARGO_LIFTED→CLOSED; the three election dispositions), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1445
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 verified byte-identical to `section-2.2-response-structure.md`. PRD ends at the §5 table — no audit footer. `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, the skill's `example-*` files, and all sibling task directories were never opened.

**Scaffold tensions carried forward un-prejudged (not silently resolved)**

1. **Two direction-mismatch codes overlap.** `ERR_SHIPMENT_DIRECTION_MISMATCH`'s catalogue condition explicitly includes "box shipping under a non-OUTBOUND label" — which is also exactly `ERR_LABEL_DIRECTION_MISMATCH`'s condition. Rendered: a wrong-direction *label* supplied to box shipping raises `ERR_LABEL_DIRECTION_MISMATCH`; an operation contradicting the *shipment's own* direction (return-to-sender on a non-`REJECT_RETURN` shipment) raises `ERR_SHIPMENT_DIRECTION_MISMATCH`. Both stay reachable and both are stated.
2. **Partial waiver has no `WAIVED` state.** The `BoxItem` machine enters `WAIVED` only when the gross damage fee is at most the remaining cap, but `damage_fee_after_waiver` waives `min(gross, remaining_cap)` whenever the member is enrolled and the grade ordinal is at most 3. Rendered explicitly: full absorption → `WAIVED`, zero fee, no charge; partial absorption → `SETTLED`, reduced non-zero `damage_fee_cents`, a `DAMAGE_FEE` charge for the remainder, and `protection_waiver_used_cents` still increased by the partially waived amount.
3. **`CREDITED / DONATE` (and `RECYCLE`) terminal pairs have no declared inbound edge.** The only declared edge out of `disposition_status` `NONE` is absorption; all three election edges start from `AWAITING_ELECTION`, which only a `RETIRE` grading outcome produces. I named the terminal pairs and said plainly that the sole declared edge leaving `NONE` is absorption, rather than inventing a `NONE → DONATE` transition.
4. **`THIRTY_DAY` and `ACTUAL_DAYS` proration are numerically identical** (both divisors are 30). Both formulas are stated separately, with the note that they coincide only because both constants are currently 30 and that `THIRTY_DAY` is by definition the basis that ignores cycle length.
5. **Rung 63 refuses the very close the `HELD → DELINQUENT_CLOSED` edge performs.** Rendered as from-state dependent: `GRACE`/`RETURN_DUE` → `CLOSED` (refused with `ERR_CYCLE_CLOSE_BLOCKED_BY_DELINQUENCY` if the member is delinquent); `HELD` → `DELINQUENT_CLOSED` with no surcharge and no `completed_cycles` increment.
6. **`ERR_UNIT_RETIRE_GRADED` prose is broader than its scope.** Rung 55 says such a unit may "never be allocated, shipped, swapped in or bought out", but `applies_to` names only allocate, swap-approve and buy-out — not box ship. Both the broad claim and the three-endpoint scope are stated.
7. **`ERR_CLAIM_WINDOW_CLOSED`'s catalogue condition mentions only `shipped_at`**, while rung 42 and the `deadline_at` field both declare the `created_at` fallback for a never-scanned loss. I carried the fallback forward as normative.
8. **Buy-out acceptance is gated twice on standing.** Its gate list includes `G5_PAUSE` (rung 17) while its transition precondition independently demands `Member.status == ACTIVE`, which is strictly stronger. Both are stated; note that rung 16 does **not** name acceptance, so a delinquent member's acceptance fails at the state gate, not the standing gate.
9. **Scaffold header comments disagree with contents** — they claim "50 calculations", "90 codes" and "9 non-linear" machines, while the file actually holds 61 calculations, 95 error codes and 8 machines flagged `non_linear: true`. The PRD follows the contents, not the headers.

## Step 5: Generate unit tests — 2026-08-09T16:52:00.000Z

Test infrastructure and suite are complete and verified.

### Test count, layout, queue split

**177 tests** in 13 files (8,517 lines across `test_helpers/` + `test_suite/`).

| Queue | Instances available | Instances translated | Tests emitted |
|---|---|---|---|
| **A — Difficulty (§1.8)** | 22 (9 rules) | 22 | **44** (exactly 2 per instance) |
| **B — Corner (§1.9)** | 144 total = 135 non-stub + 9 `excluded_because` stubs | 133 | **133** (1 per instance) |

All 9 stub `difficulty_instance` cross-references resolve to real §1.8 names. All 353 PRD citations survive a literal whitespace-normalised `grep` of PRD.md. No `skip`/`xfail`/`skipif` anywhere. No untagged or dual-tagged tests. `pyflakes` clean.

**`test_helpers/`**: `types.py` (34 enums + 21 entity TypedDicts, all carrying `updated_at`/`version` per PRD §2.4), `api_client.py` (126 endpoint methods — a (method, path) diff against PRD §4 shows **0 missing, 0 extra**), `api_errors.py` (97 error ids + status map), `assertions.py` (semantic-instant helpers + per-entity + 3 conservation invariant checkers), `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (~700 lines, tiered R/T helpers).

**`test_suite/`**: `test_01_plans_and_households` (20), `test_02_catalog_and_stock` (12), `test_03_cycle_calendar_and_invoice` (11), `test_04_boxes_and_allocation` (10), `test_05_swaps` (11), `test_06_labels_and_shipments` (8), `test_07_returns_grading_and_cleaning` (19), `test_08_buy_out` (10), `test_09_lost_parcels_and_claims` (9), `test_10_trade_in_pipeline` (17), `test_11_pauses_and_capsules` (23), `test_12_ledgers_and_delinquency` (16), `test_13_access_control_and_envelope` (11).

### Pipeline-explicit fixtures

`fixtures.py` names Pipeline R helpers (`setup_delivered_box`, `start_item_return`, `setup_returned_items`, `grade_returned_unit`, `setup_lost_return`) separately from Pipeline T helpers (`setup_received_trade_in`, `grade_trade_in_item`, `setup_credited_trade_in`, `finalize_trade_in`), so a test touching a shared rung (labels/shipments rungs 29/37/42/50, grading rung 30, ledger rungs 58–60) states which pipeline it is in by which helper it calls. Shared-rung tests are deliberately split across pipelines: rung 37 (label expiry) is exercised on a `TRADE_IN_INBOUND` parcel; rung 50 (reissue cap) and rung 5 (segregation of duties, on a `TRADE_IN` assessment) likewise.

### Identity threading

`Member` is the only `entity_backed` role. `make_member_headers(member["id"])` is used for **every** member-scoped call; `TEST_USERS["member_headers"]` is a non-owning constant reserved for 401/403/404 probes. The seven operator roles are opaque, but distinct operator identities are threaded where PRD requires it: `make_grader_headers(...)` vs `make_planner_headers(...)` keep `graded_by_user_id ≠ confirmed_by_user_id` by default, and the segregation test deliberately collides them on `shared-op-1`.

### SKIPPED instances (2)

1. **`Corner/errors/corner_err_assessment_pipeline_and_target_disagree`** — *fails condition 2 (not uniquely derivable); the PRD contradicts the design index.*
   The index asserts that `POST /condition-assessments` with `pipeline: RENTAL` + `trade_in_item_id` returns `ERR_PIPELINE_MISMATCH` (409). But PRD §3.6 says of the **create** call: *"Supplying both, supplying neither, or supplying the one that contradicts the declared pipeline is refused with `ERR_ASSESSMENT_TARGET_MISMATCH` (HTTP 422)"*, and scopes `ERR_PIPELINE_MISMATCH` to a different operation: *"confirming a `RENTAL` assessment against a trade-in garment, or a `TRADE_IN` assessment against a rental unit, is refused with `ERR_PIPELINE_MISMATCH` (HTTP 409)"*. A PRD-only reader lands on 422/`ERR_ASSESSMENT_TARGET_MISMATCH` for this exact call. **Resolution: skipped, PRD taken as authoritative.** `ERR_PIPELINE_MISMATCH` is therefore untested by the suite.

2. **`Corner/endpoints/corner_ep_box_items_filtered_by_settlement_status`** — *fails condition 1 (no verbatim PRD coverage).*
   The instance filters `GET /kidswear/box-items` by `settlement_status` and `fulfillment_status`. PRD §4 declares only *"List box items, optionally filtered by box, unit or return shipment"*, and §2.3 says *"Filter parameters named on each list endpoint in §4 are all optional"* — it never authorises unnamed filters. A reader who ignores an undeclared query param returns 2 rows where the instance asserts `total_count 0` for `BOUGHT_OUT`. **I also removed the same undeclared filter from a fixture path in `test_05_swaps.py`** (now filtered client-side) — that was a latent fixture bug with the same failure mode.

### DROPPED sub-assertions (translated instances, assertion left out because the PRD does not pin it)

- **`Difficulty/resource_temporal_overlap/adjacent_pause_windows_on_a_member_do_not_collide`** — dropped `Member.pause_days_used_period == 17`. Both pauses start (2026-05-05, 2026-05-15) **after** the logical clock (2026-05-01). PRD §3.10 defines the counter over pauses *"whose `start_at` falls inside the trailing `PAUSE_PERIOD_LENGTH_DAYS` window of 365 days"*; a reader who bounds the trailing window above by the clock counts 0. Asserted `pause_days_used_lifetime == 17` and `total_paused_days == 17` instead (§3.10's lifetime sum is *"over all time with no window at all"*).
- **`Corner/calculations/corner_calc_pause_proration_on_the_thirty_day_basis`** — dropped `Member.pause_days_used_period == 10` for the same reason (pause starts 05-05, clock 05-01). Kept `proration_credit_cents == 2000` and `Cycle.paused_days == 10`.
- **`Difficulty/compensating_invariant/allocation_then_delinquency_cancellation_conserves_physical_units`** — dropped `BoxItem.settlement_status == SETTLED`. PRD §3.1's delinquency cascade says only *"every box item of the member still in `ALLOCATED` moves to `CANCELLED`; each such item's reserved unit returns from `RESERVED` to `IN_STOCK`"* — it never moves the money axis. (§3.4 *does* say a swap rejection "settles the item at zero", but that is a different edge.)
- **`Corner/state_machines/corner_sm_buyout_expire_before_ttl_is_rejected`** — dropped `error_id == ERR_INVALID_STATE`. `QUOTED` **is** a declared from-state for `expire`; it is the time condition that fails, and the PRD names no error for a premature expiry. Replaced with the strong observable: the order is still `QUOTED` with `quoted_at`, `quote_expires_at` and `quoted_price_cents` unchanged (an implementation that wrongly expired would fail).
- **`Corner/endpoints/corner_ep_invoice_read_exposes_each_ordered_step`** — dropped `surcharge_cents == 0` and `invoice_total_cents == 0` on an **OPEN** cycle. §3.2 lists `surcharge_cents` among fields that *"begin at 0"* but says nothing about `invoice_total_cents`, and *"A computed invoice read exposes every ordered step separately"* does not settle stored-echo vs live-recompute. A live-computing reader returns 5000/5438. Kept the seven steps that are pinned.
- **`Corner/consistency_model/corner_consistency_cascade_is_visible_in_the_same_response`** — dropped *"the captured `z1_shp_status` equals CREATED in the very response that created the shipment"*. Whether `POST /boxes/{id}/ship` echoes the **Box** or the **Shipment** is not pinned (§2.2: *"the created or updated resource object"*; §3.3 says shipping both moves the box and creates the shipment). Preserved the claim by resolving the shipment through the PRD-pinned `box.outbound_shipment_id` and asserting its `status == CREATED`. **`fixtures.ship_box()` resolves the shipment the same way, so no test depends on the ambiguous response shape.**
- **`Corner/calculations/corner_calc_late_fee_per_day_accrual_value`** and **`…_flat_tier_diverges_from_per_day`** — dropped `BoxItem.late_fee_cents` immediately after `start-return`. §3.6 says start-return *"computes `days_late`"* only; §3.2 computes the per-item fee *"On either edge into `GRACE`"*. I kept `BoxItem.days_late == 4` and then drove the cycle into `GRACE` and asserted **`Cycle.late_fee_cents`** (600 PER_DAY / 2000 FLAT_TIER), which §3.2 pins explicitly as a sum *"over the cycle's items whose `fulfillment_status` is `SHIPPED`, `WITH_MEMBER`, `RETURNING`, `RECEIVED` or `LOST`"* — a `RETURNING` item is in scope. **This is the one place where I extended a recipe's trigger** (added `close-swap-window` + `assess-late`) to reach a derivable observation of the variant divergence.

### NEAR-MISS REGISTER — hypotheses to verify against the implementation, not facts

1. **`Cycle.damage_fee_cents == 0` on a fully waived item** (Difficulty/combinatorial_formula/damage_waiver…). §2.7's "round per item then sum" list enumerates `late_fee_cents`, `assessed_value_cents` and `uncapped_total_cents` — **not** `damage_fee_cents`. §3.2 lists it among fields that "begin at 0" and §3.2 puts it in the taxable base. I concluded 0 because the item's own `damage_fee_cents` is 0 under any aggregation. *Alternate reading: a cycle field holding the **gross** pre-waiver fee would read 4000.*
2. **`Cycle.late_fee_cents` for a `RETURNING` item** (the k7/k8 substitution above). §3.2 computes per-item fees for items *"whose `fulfillment_status` is `SHIPPED` or `WITH_MEMBER`"* but sums over a **wider** set that includes `RETURNING`. I read this as: the `RETURNING` item's fee derives from the `days_late` stamped at return-start. *Alternate reading: a reader who only fees `SHIPPED`/`WITH_MEMBER` items and sums those contributes 0 for our item → `Cycle.late_fee_cents == 0`.* **This is the single most fragile pair in the suite.**
3. **`POST /boxes/{id}/allocate` returns the created `BoxItem` with 201** (asserted directly in `test_02` size-compat tests, `test_04` box-item defaults, `test_07` loop re-allocation). §2.2 pins "creation endpoints answer 201 with the newly created resource"; §3.3 says allocation "creates a `BoxItem`". *Alternate reading: return the updated Box.* `fixtures.allocate_unit()` falls back to the box-item list, so **only the tests that assert on the response directly are exposed**.
4. **`POST /trade-in-items/{id}/absorb` returns the minted `GarmentUnit` with 201** (`test_10` absorption). Same shape of argument. The corner index's own `corner_ep_absorb_returns_a_garment_unit_not_a_trade_in_item` stub concedes the response entity type is the only thing at issue.
5. **`POST /box-items/{id}/buy-out` returns the `BuyOutOrder` with 201.** Not asserted directly — `fixtures.mint_buy_out_quote()` re-reads through `GET /buy-out-orders?box_item_id=`, a PRD-declared filter. Recorded because a Step-8 reader may expect the direct assertion.
6. **Credit application scope** (`test_12` waterfall test, `corner_calc_credit_applies_to_plan_charge_before_an_older_late_fee`). §3.11 says the call *"nam[es] a single `charge_entry_id`"* yet then describes a waterfall *"For each charge in turn"*. Both readings ("apply to the named charge only" and "apply across all open charges in `CREDIT_APPLICATION_ORDER`") produce the asserted 1000→PLAN_CHARGE / 0→LATE_FEE outcome here, so the test is safe **by luck of the fixture values**, not because the PRD is unambiguous.
7. **Reissued label inherits `direction`** (`test_06`). §3.5 lists what reissue writes and omits `direction`. Since the endpoint takes no direction input, the predecessor is the only possible source — but it is inferred, not stated.
8. **Two simultaneously `OPEN` cycles for one member** (Difficulty/non_linear_state_machine/garment_unit_completes_circulation_loop; Difficulty/transitive_cascade/lost_return_shipment_cascades). The PRD never forbids it and `cycle_index` is "previous highest plus one", but an implementer who enforced one open cycle per member would fail both fixtures at setup.
9. **`Member.total_paused_days`** asserted equal to `pause_days_used_lifetime` (`test_11`). §3.1 states the equality directly, but the field is only described as "the cumulative paused-day figure used to extend credit expiry" — a reader might not surface it on the member serializer at all.
10. **`meta.api_request_id` starts with `req_`** (`test_13` envelope). §2.2 states it verbatim; recorded only because it is the sole prefix assertion in the suite.
11. **`GET /kidswear/plans` with `limit: 101` returns 422** rather than clamping (`test_01`). §2.3 pins it verbatim; the near-miss is that §2.9 routes *body* field-shape failures, and a reader might treat query params differently.

### PRD self-contradictions and PRD-vs-index conflicts found

- **§3.6 create-target vs §3.6 pipeline-mismatch** (skip #1 above) — the same paragraph routes "the target that contradicts the declared pipeline" to `ERR_ASSESSMENT_TARGET_MISMATCH` (422) at **create**, while the design index expects `ERR_PIPELINE_MISMATCH` (409) at create. Resolved in favour of the PRD; instance skipped.
- **§4 box-items filter list vs the corner index** (skip #2 above) — the index tests two filters §4 does not name. Resolved in favour of the PRD; instance skipped.
- **§3.2 per-item late-fee scope vs the cycle-level sum scope** (near-miss #2) — the fee is computed for `SHIPPED`/`WITH_MEMBER` items but summed over a set that also includes `RETURNING`, `RECEIVED` and `LOST`, leaving no stated producer for a `RETURNING` item's fee. Carried forward as an un-prejudged friction point rather than resolved.
- **§3.10 "trailing 365-day window"** (drops #1–2) — undefined for a `start_at` in the future relative to the logical clock. Three §1.9 instances depend on the counter; the two whose pauses start in the past (`corner_val_pause_period_cap_…` at clock 2026-06-05, `corner_val_pause_lifetime_cap_…` at clock 2029-08-01) are safe and keep their assertions.
- **Design index naming slip (not a contradiction):** `corner_condition_assessment_with_both_targets_is_rejected` is named for "both targets" but its recipe and `distinguishing_aspect` supply **neither**. Translated per the recipe (neither target supplied → `ERR_ASSESSMENT_TARGET_MISMATCH`).

### Not chased, as instructed
The four conservation errors (`ERR_UNIT_CONSERVATION_VIOLATION`, `ERR_SLOT_CONSERVATION_VIOLATION`, `ERR_CREDIT_CONSERVATION_VIOLATION`, `ERR_SWAP_CONSERVATION_VIOLATION`) have no test. Their **invariants** are checked positively instead, via `assert_unit_conservation`, `assert_box_slot_conservation` and `assert_credit_conservation` in `test_helpers/assertions.py`, applied in the three `compensating_invariant` difficulty families.

## Step 6: Generate implementation — 2026-08-09T16:52:00.000Z

Implementation complete at `workspace/implementation/`.

### Module layout (5,224 lines, 34 files)

**Core (1,743 lines):** `app.py` 121 · `constants.py` 243 · `errors.py` 117 · `timeutil.py` 129 · `money.py` 27 · `store.py` 91 · `envelope.py` 77 · `shape.py` 178 · `auth.py` 42 · `lookup.py` 129 · `derive.py` 147 · `calc.py` 188 · `serialize.py` 345 · `selector.py` 95 · `ledger.py` 169 · `boxops.py` 45 · `tradein_ops.py` 46 · `listing.py` 14

**Routes (2,821 lines):** `system.py` 19 · `plans.py` 80 · `members.py` 241 · `cycles.py` 246 · `catalog.py` 154 · `boxes.py` 307 · `swaps.py` 216 · `shipping.py` 376 · `grading.py` 356 · `tradein.py` 263 · `ledgers.py` 96 · `buyouts.py` 116 · `capsules.py` 185 · `pauses.py` 172 · `claims.py` 193

### Route completeness gate

Normalised `(method, path)` pairs, every `<conv:name>` / `{name}` segment rewritten to `{}`:

```
declared endpoint entries: 126   unique (method,path): 126
registered routes:         126
MISSING 0
EXTRA   0
```

Flask is constructed with `static_folder=None` so no framework route inflates the count. *(Orchestrator re-ran this diff independently against `app.url_map`: 126/126, MISSING 0, EXTRA 0.)*

### Adjudication 1 — timestamp rendering (one rule, all three cases)

**Rule: every instant the API emits renders in one canonical form — `%Y-%m-%dT%H:%M:%S.mmmZ` (UTC, exactly three fractional digits, trailing `Z`). Nothing is ever echoed byte-verbatim. Every comparison is a semantic instant comparison on timezone-aware UTC datetimes.**

- (a) **Server-written** (`created_at`, `updated_at`, `issued_at`, `granted_at`, `filed_at`, `quoted_at`, `shipped_at`, `delivered_at`, `size_effective_at`): value is the logical clock; rendered canonically.
- (b) **Caller-supplied and echoed** (`start_at`, `acquired_at`, `release_at`, `close_at`, pause `start_at`, clock `to_iso8601`): parsed to an instant, stored as a datetime, **re-rendered canonically** — not verbatim. This is PRD §2.4 verbatim: *"An instant supplied by a client in a request body is compared semantically, as an instant, not as a string; the response, however, always renders the platform's own canonical three-fractional-digit form."* So `"2026-06-01T00:00:00Z"` comes back as `"2026-06-01T00:00:00.000Z"`, and `"2026-06-01T00:00:00+02:00"` comes back as `"2026-05-31T22:00:00.000Z"`.
- (c) **Derived from a caller instant** (`swap_by_at`, `return_due_at`, `grace_ends_at`, `end_at`, `expires_at`, `quote_expires_at`, `embargo_until`, `deadline_at`, `election_deadline_at`): computed on the parsed instant, rendered canonically.

**No wall-clock value ever enters the system.** The logical clock starts at `DEFAULT_CLOCK_UTC` = `2026-05-01T00:00:00.000Z` and only `POST /_clock/set_current_utc` moves it. `meta.api_request_timestamp` is also the logical clock (not `datetime.now()`) — deliberate, so logical and envelope time never mix.

### Adjudication 2 — enum error routing (closed iff-list)

A body field's out-of-member-set value produces **`ERR_INVALID_ENUM` (422) if and only if** the field is one of these 20, and no others:

`Plan.tier` · `Plan.proration_basis` · `Plan.late_fee_mode` · `Member.child_size_code` (registration only) · `GarmentStyle.brand_tier` · `GarmentStyle.size_code` · `GarmentStyle.season` · `GarmentStyle.demand_band` (create **and** PATCH) · `Shipment.direction` · `ShippingLabel.direction` · `ConditionAssessment.pipeline` · `ConditionAssessment.grade` (submit **and** regrade) · `ProcessingJob.post_repair_grade` · `TradeInItem.declared_brand_tier` · `TradeInItem.declared_size_code` · `disposition` (elect-disposition) · `quote_variant` (buy-out) · `Capsule.season` · `reason` (unit retirement, a `retired_reason` value) · `SwapRequest.rejection_reason` · `PauseRequest.denial_reason`.

**Every other constrained field routes to `ERR_VALIDATION` (422)**, with these named exclusions called out because they look like enums and are *not*: `charge_type` on charge-adjustments · `Plan.status` and `GarmentStyle.status` on PATCH · `GarmentUnit.current_grade` on acquisition · **`new_size_code` on size-up** (the PRD lists `child_size_code`, not `new_size_code`, so an off-ladder value is `ERR_VALIDATION`, while a valid-but-wrong-direction move is `ERR_SIZE_UP_INVALID_STEP`) · every `status` / `direction` / `route` / `pipeline` **query filter** on list endpoints · `denial_reason` on **claim** denial (a free-text string field, unlike the pause request's enum) · `revoke_reason`, `waive_reason`, `dispute_reason`, `info_note`, credit-adjustment `reason` · every boolean and integer bound.

Missing / null / wrong-JSON-type on an ERR_INVALID_ENUM field is still `ERR_VALIDATION` — the specific code fires only for a well-typed string outside the member set.

### Version observability

`store.touch(row)` bumps `version` and refreshes `updated_at`, and is **always called before the response serializer runs**, so every mutation response ships the post-mutation version and a client can echo it straight into the next `expected_*_version`. Policy: **one bump per distinct row per declared mutation step**, so a request that drives two declared transitions on the same row bumps twice (e.g. a credit application that also flips the member `DELINQUENT → ACTIVE` bumps the member twice — once for the application, once for the standing transition). Cascaded children each get their own bump (cycles → HELD, box items → CANCELLED, units → IN_STOCK, boxes → CANCELLED).

### Boundary inclusivity (each read individually, no symmetry assumed)

`swap_by_at` inclusive (rung 33, `clock > swap_by_at` refuses) · close-swap-window strictly after (rung 35, `clock <= swap_by_at` refuses) · `grace_ends_at` **exclusive** (rung 36 — opposite of 33) · label `expires_at` inclusive (rung 37) · embargo strictly-before (rung 38) · capsule window `[release_at, close_at)` (rung 39) · quote TTL strictly-before (rung 40) · election deadline inclusive (rung 41) · claim filing window inclusive (rung 42) · credit expiry strictly-before · delinquency `>= 15000` raises / `< 15000` clears · retirement thresholds `>=` on both counters · pause overlap **half-open** (adjacency allowed) vs capsule overlap **closed** (adjacency collides).

### Money ordering

Verified numerically end-to-end: proration → discount (rounded half-up separately on plan charge and on the 900-cent protection fee) → credit application → surcharge on the **post-credit, floored** base. Volume tier keyed off the **undiscounted** gross including the protection fee. Buy-out: 25-cent step rounding **before** the surcharge, 900-cent floor **after**. Round-per-row-then-sum for cycle late fee, claim assessed value, and trade-in totals. Waiver cap scaled by `protection_fee_cents / 900`.

### Every place the PRD was silent, ambiguous or self-contradictory, and what I chose

1. **Credit application scope.** §3.11 says the endpoint names *a single* `charge_entry_id` but then describes a waterfall over *charges* in `CREDIT_APPLICATION_ORDER`; the scaffold's `credit_application_waterfall` (triggered by this exact endpoint) loops over **all** open charges. **Chosen:** run the full waterfall over all the member's open charges; the named charge is used for rung 60 and is what the response returns. Alternative reading (apply only to the named charge) not implemented.
2. **DRAFT swap request at window close.** §3.2 says window close *rejects* DRAFT and SUBMITTED with `rejection_reason MEMBER_STANDING`; §3.4 and the SwapRequest SM say a DRAFT request is *cancelled outright*. **Chosen:** DRAFT → `status CANCELLED` **with** `rejection_reason MEMBER_STANDING`; SUBMITTED → `status REJECTED` with the same reason. This satisfies both sentences.
3. **SwapRequest from-state errors are undeclared.** Rung 32 lists Member/Capsule/CapsuleAllocation/BuyOutOrder/PauseRequest/LostShipmentClaim — SwapRequest appears in no state rung. **Chosen:** `ERR_INVALID_STATE` (409) for every SwapRequest from-state violation (submit/approve/reject/fulfill).
4. **Ledger-entry from-state errors are undeclared.** CreditLedgerEntry and ChargeLedgerEntry are in no state rung. **Chosen:** `ERR_INVALID_STATE` for credit expire/revoke on a non-`AVAILABLE`/`PARTIALLY_APPLIED` entry; `ERR_CHARGE_NOT_OPEN` (rung 60, declared) for waive.
5. **Expiring a credit entry before its instant.** No declared code. **Chosen:** `ERR_INVALID_STATE` (409).
6. **Expiring a buy-out quote before its TTL.** No declared code (`ERR_BUYOUT_QUOTE_EXPIRED` is pinned to *accept*). **Chosen:** `ERR_INVALID_STATE` (409).
7. **Rung 4 does not reach ConditionAssessment / ProcessingJob.** Rung 4 reaches an owner "directly through `member_id`, or through `cycle_id`/`box_id`/`submission_id`"; `ConditionAssessment` carries none of those fields. **Chosen:** **no** ownership check on any assessment or job endpoint (including a Member disputing a grade). A Member can therefore dispute any assessment. This is a deliberate literal reading of the declared reachability paths.
8. **Member-scoped list endpoints.** The roles table gives `Member` "GET reads scoped to the member's own resources" but no rung covers a list with no addressed resource. **Chosen:** for a `Member` caller, list endpoints over member-owned entities (cycles, boxes, box-items, swap-requests, shipments, labels, submissions, trade-in items, credit/charge entries, buy-out orders, pause requests, claims, capsule allocations) are **silently filtered** to that member's rows (`total_count` reflects the filtered set). Non-member-scoped lists (plans, styles, units, assessments, jobs, capsules) are unfiltered.
9. **Ordering of `ERR_SIZE_UP_INVALID_STEP` vs `ERR_SIZE_UP_TOO_SOON`.** §3.1 calls them "independent" and pins no order. **Chosen:** the 422 step check first, since §2.5 puts 422 shape-family validation at the authorization stage ahead of the ladder; `ERR_SIZE_UP_TOO_SOON` is rung 43 (G8).
10. **Label direction vs label status vs label expiry order.** §3.3 lists them as "wrong direction … wrong status … expired"; rung 29 (status) is G7 and rung 37 (expiry) is G8, but direction mismatch is unnumbered. **Chosen:** narrative order — **direction → status → expiry** — on box ship, and the same on trade-in issue-label.
11. **Cycle open with a non-ACTIVE member.** The SM precondition is `Member.status == ACTIVE`; no code declared (the standing gates already exclude CANCELLED/PENDING). **Chosen:** `ERR_INVALID_STATE` (409) for a PAUSED or DELINQUENT owner.
12. **Cycle close with box items not yet terminal.** No declared code. **Chosen:** `ERR_CYCLE_INVALID_STATE` (409), evaluated at G7 (after rung 22, before rung 63 `ERR_CYCLE_CLOSE_BLOCKED_BY_DELINQUENCY`).
13. **Cycle close from HELD with a non-DELINQUENT member.** **Chosen:** `ERR_CYCLE_INVALID_STATE`.
14. **`assess-late` from SWAP_CLOSED before `return_due_at`.** Neither declared edge's precondition holds. **Chosen:** `ERR_GRACE_NOT_EXPIRED` (409), the temporal rung the endpoint owns.
15. **Cancelling a member with garments still out.** The SM precondition has no code. **Chosen:** `ERR_INVALID_STATE` (409).
16. **Box pack requires an OPEN cycle** per the Box SM, but rung 23's `applies_to` names only swap-create, swap-submit and allocate. **Chosen:** enforce it, with `ERR_CYCLE_NOT_OPEN`, checked before the box-state rung (rung 23 < rung 24).
17. **`start-return` on an already-settled item.** The SM precondition is `settlement_status == OPEN`; rung 26's `applies_to` names only buy-out and confirm. **Chosen:** enforce it with `ERR_BOX_ITEM_ALREADY_SETTLED`, after rung 25.
18. **Buy-out accept and embargo.** Rung 38 names swap-create and buy-out *quote*; the SM precondition on *accept* also requires the item to be out of embargo. **Chosen:** enforce on accept with `ERR_CAPSULE_EMBARGOED`.
19. **Capsule announce / open temporal preconditions.** No declared code (rung 39 is scoped to allocations). **Chosen:** `ERR_INVALID_STATE` (409). Lift-embargo and close keep their declared codes (`ERR_CAPSULE_EMBARGO_NOT_REACHED`, `ERR_CAPSULE_CLOSE_NOT_DUE`).
20. **Voiding a label whose shipment already moved.** No declared code. **Chosen:** `ERR_LABEL_INVALID_STATE`.
21. **Label reissue and the predecessor's version.** The SM declares "ShippingLabel.version increments by 1" while also saying the predecessor "remains in its terminal status". **Chosen:** the **predecessor is touched** (version +1, unchanged status); the successor is a new row at version 1 with `reissue_count = predecessor + 1` and `expires_at` re-derived from the current clock.
22. **Receiving a LOST shipment that already has a SETTLED claim.** No declared code. **Chosen:** `ERR_SHIPMENT_INVALID_STATE`.
23. **Recovery cascade does not create assessments.** `LOST → DELIVERED` moves units to `PROCESSING` and items to `RECEIVED`, but the PRD declares assessment creation only on the `RETURN` receipt. **Chosen:** no assessment is minted on recovery, and `cycles_completed` is **not** incremented on recovery.
24. **`LOST_LIABILITY` charge when nothing was lost.** **Chosen:** the charge is created only when the assessed value is `> 0` (an outbound loss carrying no `RETURNING` items raises nothing).
25. **Which `LOST_LIABILITY` charge a settlement reduces.** Charges carry no shipment reference. **Chosen:** the member's `LOST_LIABILITY` charge whose `amount_cents` equals the claim's `assessed_value_cents`, else the most recent one.
26. **Trade-in finalisation with `credited_total_cents == 0`.** §3.9 says finalisation creates *one* credit entry, but §3.11 requires `amount_cents` strictly `> 0`. **Chosen:** the credit entry (and auto-apply) is created **only when `credited_total_cents > 0`**; the submission still reaches `CREDITED` and still sets `election_deadline_at`.
27. **Election before finalisation (null `election_deadline_at`).** An item can be `AWAITING_ELECTION` before the batch is finalised. **Chosen:** a null deadline **permits** an election (no deadline has passed) and **refuses** apply-default with `ERR_ELECTION_NOT_DUE`.
28. **`apply-default-disposition` from a wrong disposition state.** `ERR_TRADE_IN_ITEM_NOT_REJECTED` is declared for *elections* only. **Chosen:** `ERR_TRADE_IN_INVALID_STATE` (rung 31) for apply-default; `ERR_TRADE_IN_ITEM_NOT_REJECTED` for elect-disposition.
29. **Empty-pool diagnosis in the selectors.** The PRD says an empty pool is `ERR_NO_ELIGIBLE_STOCK` but also names `ERR_SIZE_INCOMPATIBLE`, `ERR_UNIT_RETIRE_GRADED` and `ERR_CAPSULE_ALLOCATION_MISSING` as causes. **Chosen:** stage the filter in **rung order** — no IN_STOCK unit of the style at all → `ERR_NO_ELIGIBLE_STOCK`; else all fail size → `ERR_SIZE_INCOMPATIBLE` (53); else all fail grade/retirement → `ERR_UNIT_RETIRE_GRADED` (55); else all fail the capsule predicate → `ERR_CAPSULE_ALLOCATION_MISSING` (56).
30. **Box-fill variant selection.** **Chosen:** CAPSULE_FILL applies when *some* IN_STOCK unit of the requested style carries a `capsule_id` the member holds an ACTIVE allocation on **and** whose capsule is `OPEN`/`EMBARGO_LIFTED`; otherwise STANDARD_FILL restricted to `capsule_id is null`.
31. **`allocate` with both `unit_id` and `style_id`.** Undeclared. **Chosen:** `unit_id` wins (explicit beats selector); neither supplied → `ERR_VALIDATION`.
32. **`slot_index` assignment.** **Chosen:** the count of *all* the box's existing items (including cancelled ones), so indices are monotone and never reused.
33. **`item_count` on the box-ship shipment.** The field defaults to 0 and box-ship declares no input. **Chosen:** `0`. (Trade-in `issue-label` sets `item_count = declared_item_count`, which the submission does declare.)
34. **`ERR_ASSESSMENT_TARGET_MISMATCH` ordering.** **Chosen:** the 422 target/pipeline consistency check runs at the authorization stage, **before** the G3 existence lookups of `unit_id` / `trade_in_item_id`.
35. **Rung 26 before rung 30 on confirm.** Followed literally: confirming against an already-settled box item returns `ERR_BOX_ITEM_ALREADY_SETTLED` (409) even when the assessment itself is in a wrong from-state.
36. **`ERR_WAIVER_NOT_AVAILABLE` trigger condition.** **Chosen:** fires only when a draw would actually occur (enrolled ∧ ordinal ≤ 3 ∧ gross > 0 ∧ remaining cap > 0) **and** the cycle's `PROTECTION_FEE` charge is missing or `WAIVED`.
37. **`assessed_grade` on a fully-waived item.** The WAIVED SM edge does not list it; §3.6 says confirmation "writes `assessed_grade` onto the returned box item". **Chosen:** written on **both** the SETTLED and WAIVED paths.
38. **Late-fee recomputation at `assess-late`.** **Chosen:** `days_late` is recomputed from the clock only for items in `SHIPPED`/`WITH_MEMBER`; `late_fee_cents` is computed from the item's stored `days_late` for the full declared set (`SHIPPED, WITH_MEMBER, RETURNING, RECEIVED, LOST`), walked in `slot_index` order, rounded per item then summed. An item is touched only when a value actually changed.
39. **Job start on a `RETIRE`-routed job.** Not blocked (no declared precondition) — the block sits on *pass*, which is declared. See reachability note.
40. **`post_repair_grade` on a non-REPAIR route** → `ERR_REPAIR_UPLIFT_EXCEEDED` (422), per the error catalogue's second clause.
41. **`cumulative_cleaning_cost_cents`** is recomputed as the sum over the unit's `PASSED`/`SCRAPPED` jobs (not incrementally added), per the scaffold formula.
42. **Computed vs stored fields.** Derived live on every read: member `credit_balance_cents`, `outstanding_balance_cents`, `pause_days_used_period/lifetime`, `completed_cycles`, `total_paused_days`; cycle `swaps_used`, `slots_occupied`, `paused_days`, `damage_fee_cents`, `credit_applied_cents`; box `slots_free`. Stored: cycle `plan_charge_cents`, `discount_cents`, `protection_fee_cents`, `proration_credit_cents`, `protection_waiver_used_cents`, `late_fee_cents`, `surcharge_cents`, `invoice_total_cents`; member `permanent_slots_consumed`; style `units_ever_acquired`.
43. **`GET /cycles/{id}/invoice` computes live** (so it is meaningful before close), using the same pinned four-step order; `close` writes `surcharge_cents` / `invoice_total_cents` from the same function.
44. **`SURCHARGE` charge is created unconditionally on the CLOSED path**, even at 0 cents; the `DELINQUENT_CLOSED` path creates none and computes no invoice.
45. **`cycle_index > 240`** → `ERR_VALIDATION` (no declared code; unreachable in practice).
46. **Unknown route / wrong method** → `ERR_RESOURCE_NOT_FOUND` (404) / `ERR_ROLE_FORBIDDEN` (405) in the standard error envelope.
47. **Direct unit retirement does not set `retirement_eligible`** — the PRD declares only the state change and the reason, and `retirement_eligible` is a computed field re-evaluated on job pass. (Scrap and lost-write-off *do* set it, since those units end terminal.)
48. **Ordering ties.** Every `created_at` tie is broken by an internal monotone insertion sequence, so ordering is total and deterministic even when the logical clock does not advance between writes.

### Reachability audit — claims to be verified against the code by a later reviewer, not established facts

- **Rungs 64, 65, 66, 67** (`ERR_UNIT_CONSERVATION_VIOLATION`, `ERR_SLOT_CONSERVATION_VIOLATION`, `ERR_CREDIT_CONSERVATION_VIOLATION`, `ERR_SWAP_CONSERVATION_VIOLATION`): I did **not** implement post-write invariant re-checks as raisable guards. The invariants hold structurally — `units_ever_acquired` is incremented exactly once per minted unit and units only change state; `slots_free` is *derived* from the conservation identity rather than stored; credit moves between buckets without creation or destruction; and rung 46 forces equal array lengths so `slot_delta` is always 0. Rung 67's `slot_delta != 0` branch **is** coded in `fulfill` but I claim no public sequence reaches it. This matches the PRD's own statement that 64–67 are "defensive invariant guards … expected to be unreachable through the public surface", but treat that as a hypothesis and read the code.
- **`ERR_PIPELINE_MISMATCH`** (409): coded on confirm, but assessment creation already enforces target/pipeline consistency and no endpoint mutates `pipeline` afterwards, so I claim it is unreachable.
- **`ProcessingJob` `IN_PROGRESS → PASSED` with route `RETIRE`**: I refuse it with `ERR_ASSESSMENT_INVALID_STATE`, but I did **not** block *starting* a RETIRE-routed job (no declared precondition). The PRD asserts such a job "can never be started" — in my implementation it **can** be started, and can then only be failed and scrapped, or reach the pass-refusal. Claim: the PRD's "never started" statement is not enforced by my code; a reviewer should decide whether that is a PRD claim without a mechanism.
- **`ConditionAssessment` `DRAFT → VOIDED`**: fires only from direct unit retirement (`POST /garment-units/{id}/retire`). Retirement via processing-job pass/scrap does not void DRAFT assessments (a unit in `PROCESSING` has at most one DRAFT assessment, which by then is CONFIRMED). Claim: reachable only through the direct-retire path.
- **`ERR_MEMBER_PAUSED` on box `pack`**: I apply rung 17 to pack (the PRD lists "packing" in rung 17's scope), which means a pause activated between allocate and pack blocks packing. Claim: consistent with rung 17's enumeration.
- **`ACCEPTED → CANCELLED` "provided no `BUYOUT_PRICE` charge has been raised"**: the charge is only raised on `ACCEPTED → PAID`, so the guard is vacuous in `ACCEPTED`. I check status only. Claim: the declared precondition is unfalsifiable by construction.
- **`ERR_LABEL_DIRECTION_MISMATCH` on `POST /shipments`**: not enforced — shipment creation takes `direction` as an input and the PRD declares no consistency requirement between it and the label's direction. Claim: a shipment can be created with a direction differing from its label's; only box-ship and trade-in issue-label enforce direction.
- **`ERR_CAPSULE_ELIGIBILITY_NOT_MET` vs `ERR_MEMBER_PAUSED`**: a PAUSED member allocating a capsule hits rung 17 (`ERR_MEMBER_PAUSED`) before the eligibility check, so the eligibility clause "the member's status is ACTIVE" is never the reported cause. Claim: that sub-clause is unreachable as an error, though the overall gate is correct.
- **`ERR_PLAN_RETIRED` on activation** is reachable (plan PATCHed to RETIRED between registration and activation).
- **Trade-in `PRO_RATA_CAP` variant** is reachable only for a `CAPSULE_PLUS` plan; `SEQUENTIAL_CAP` for all other tiers. Both branches are coded; only SEQUENTIAL was exercised in smoke testing.
- **`ERR_INSUFFICIENT_CREDIT` vs `ERR_CREDIT_EXPIRED` ordering**: rung 58 fires when the member has credit entries but none usable; rung 59 fires when the member has no entries at all (or a zero balance with all entries usable). Claim: both are reachable, but a member whose only entries are `APPLIED` gets `ERR_CREDIT_EXPIRED`, not `ERR_INSUFFICIENT_CREDIT`.

### Self-checks

- `ast.parse` over every `.py` — clean.
- `grep -rniE 'sqlite|json\.dump|pickle|/tmp|shelve|open(...,"w")'` — **no hits**. Storage is Python dicts only; `store.db` is populated exclusively by request handlers.
- No seeding: `grep -rn seed` matches only two docstrings.
- Boot: `PORT=18953 bash start.sh` serves 200 on `GET /kidswear/plans` with auth headers, 401 without, 201 on `POST /kidswear/plans`.
- **EADDRINUSE race: 8 consecutive kill-and-relaunch cycles, 8/8 booted and answered 200, zero "Address already in use" in the log.** After the 8th reboot the store is empty (`"data":[]`), confirming no carry-over state.
- Four end-to-end smoke suites (rental circulation + delinquency cascade + buy-out; grading/cleaning/waiver/invoice/trade-in; labels/capsules/pauses/ledgers/lists; swaps/lost-parcel claims/repair uplift/reject-return; buy-out cancel-expire/scrap/default-disposition) — **0 failures**, with money assertions on the volume tier (11400/855/645), FLAT_TIER late fee (2000 at 4 days), surcharge (691 on 7900), buy-out both variants (3100 CYCLES_WORN, 1725 MONTHS_HELD), waiver cap, repair uplift (D→B allowed, D→A refused), trade-in credit (1960 = 1400×1.4×1.0), never-scanned liability (1650 → 990 at 60%), and pause proration (1000).

## Step 7: Run tests and iterate — 2026-08-09T17:31:00.000Z

All 16 rounds across two consecutive sweeps are green. Task complete.

**Iterations:** 3 sweeps (24 rounds). Opening pass rate **166–169 / 177** (16 distinct failing tests in the union). Final: **176/176 in all 8 rounds, twice consecutively** — the second confirming sweep ran under heavy co-tenant saturation (load 11.4, 7 foreign runners), which makes the clean result strong rather than lucky.

### Tests deleted (1)
- `test_04_boxes_and_allocation.py::TestBoxCreation::test_a_paused_household_may_not_open_a_box` — **rule-scope silence / not uniquely derivable**. It asserted `ERR_MEMBER_PAUSED` on `POST /kidswear/boxes`. PRD rung 17 enumerates its own scope closed: *"…for a Pipeline R circulation write — box allocation, packing, shipping, swap creation and submission, buy-out quoting and acceptance, and capsule allocation"* — box **creation** is absent, and the contrast with rung 15 (*"Applies to cycle, box, swap … write endpoints"*) shows the narrowing is deliberate. The impl gates exactly those seven operations.

### `test_suite/` fixes (3)
- `test_02_catalog_and_stock.py::test_a_retire_graded_unit_may_never_be_allocated` — dropped `retirement_eligible is True` (asserted on a unit acquired with `current_grade RETIRE`). §3.3 says verbatim *"Every acquired unit begins with … `retirement_eligible` false"*, and §3.6 recomputes it only after a job's cost accrues; rung 55's two disjuncts (`current_grade == RETIRE` **or** `retirement_eligible`) are redundant unless the flag is stored. Replaced with `current_grade == "RETIRE"` (the disjunct that actually refuses). **Partial-coverage split** — the `ERR_UNIT_RETIRE_GRADED` assertion was kept intact.
- `test_04::test_the_shipping_cascade_is_visible_immediately` — `validate_success(...)` (implicit 200) → `get_success_data(...)`. **201-vs-200 silence**: §4 says *"Creation endpoints answer HTTP 201 … every other successful operation answers HTTP 200 with the affected resource"* while describing this very endpoint as *"Ship a packed box … **creates the outbound shipment**"*. Both readings are constructible; all six cascade assertions kept.
- `test_07::test_a_repair_claiming_three_ordinals_of_uplift_is_refused` — `current_grade == "D"` → `"A"`. PRD's only writer of `GarmentUnit.current_grade` after acquisition is the **passing** job (*"Passing a job … The unit's `current_grade` is then recomputed"*); confirmation writes `assessed_grade` on the *box item*, not the unit. The refused pass leaves the acquisition default `A` (§3.3).

### `test_helpers/` fixes
None. No fixture bug surfaced.

### `implementation/` fixes (4)
- `routes/swaps.py::submit_swap` — moved the un-numbered swap-request `DRAFT` check **after** rung 23. Rung 23 is a numbered G7 rung naming `POST /swap-requests/{id}/submit` (`ERR_CYCLE_NOT_OPEN`); the swap-request state check has no rung and no PRD-declared error id at all (PRD never uses the token `SwapRequest`, and rung 32's entity list omits it), so it cannot pre-empt a declared rung. Fixed 2 tests.
- `routes/grading.py::start_job` — refuse a `RETIRE`-routed job with `ERR_ASSESSMENT_INVALID_STATE`. §3.6: *"that is the **only** path a `RETIRE`-routed job may ever take, because such a job can never be started and never be passed."* The impl already enforced the "never be passed" half in `pass_job` and simply omitted the twin.
- `ledger.py::apply_credit_waterfall` + `routes/members.py::apply_credit` — the explicit credit application now narrows the charge side to the **named** entry. Decided by §4: *"Apply banked credit to **one open charge** under the declared CREDIT_APPLICATION_ORDER waterfall"*, against §3.9's auto-apply which *"applies the new credit immediately to the member's open **charges** under the standing waterfall"* (still full-waterfall).
- `app.py::_bind` — pre-bind retry window 5.0 s → 12.0 s (fits under the runner's 15 s restart poll).

### Assertions relaxed to `validate_error_is_one_of([...])`
None.

### Boot-flake root cause — falsified, not assumed
Sweep 1 had 11 `"could not be restarted"` / `ConnectionReset` errors, all in wave 2. I instrumented `app.py` to log any pre-bind wait >0.25 s or failure, ran a full sweep, and the diagnostic file came back **empty** — so the EADDRINUSE / ephemeral-port-steal hypothesis is **refuted** for this task. Measured cold boot is ~0.50 s against a 15 s budget; sweep 1 ran with load 4.9 and 7 competing `claude` processes, so the errors were host saturation, not an implementation defect. Instrumentation removed; the widened bind window was kept as cheap insurance. I also reaped one orphan Flask server squatting a port from an earlier run before sweeping.

### Fairness flags on PASSING tests
- `test_11::…total_paused_days` asserts a field test-gen flagged as an inference — it is in fact PRD-grounded (§3.1: *"`total_paused_days` — which always equals `pause_days_used_lifetime`"*). **Refutes** that near-miss.
- The box-ship shipment's `item_count` is `0` and is serialized on every ship response; `item_count` appears only 3× in the PRD and no sentence derives its value on the box-ship path. No test asserts it — free Step-8 intelligence.
- PRD **self-contradiction, currently untested**: §3.2 says closing the swap window *"rejects every one of the cycle's swap requests still in `DRAFT` or `SUBMITTED`, writing `MEMBER_STANDING` as their `rejection_reason`"*, while §3.4 says *"a request still sitting in `DRAFT` when the cycle's swap window closes is **cancelled** outright."* The impl splits the difference (`DRAFT → CANCELLED` with `rejection_reason MEMBER_STANDING`). No test pins it, so it cost nothing — but the contradiction is live in the prose.
- Assessment/job endpoints carry **no ownership check** (`auth.gate` only, never `auth.own`) — consistent with rung 4's "member-scoped endpoint" scope since neither path carries a member identifier, but unasserted either way.

### Generator hypotheses: verdicts
**CONFIRMED by reading code** — impl-gen's "credit application runs the FULL waterfall over all open charges" (it did; §4 says otherwise, so it was fixed); impl-gen's "the box-ship shipment's `item_count` is 0"; impl-gen's "no ownership check at all on assessment/job endpoints"; impl-gen's "a DRAFT swap request at window close becomes `CANCELLED` *with* `rejection_reason MEMBER_STANDING`"; test-gen's "`POST /boxes/{id}/allocate` returns the created `BoxItem` with 201" (test and impl agree, and it passes).

**REFUTED** — test-gen's "`Member.total_paused_days` being serialized at all" is PRD-grounded, not an inference; test-gen's "`limit: 101` returning 422 rather than clamping" is likewise verbatim in §2.3, not a guess; test-gen's "credit application scope … the fixture values make both readings agree, by luck" — they do **not** agree in `test_a_stale_member_version_is_refused_at_the_concurrency_gate`, which is exactly where the two readings separated (5000 ¢ credit against two 1000 ¢ charges), and §4 settles it against the impl.

**Not exercised** — the four conservation guards (as expected, unreachable); test-gen's `RETURNING`-item `late_fee_cents` pair both passed on the return-start `days_late` reading.

### Orchestrator's independent verification of the clean pass
- All 8 `results.N.json` present and parseable, each `176/176` with **176 individual rows** (not just an aggregate counter).
- **Identical test-name sets across all 8 rounds** (0 symmetric difference) — no round silently collected a smaller suite.
- `def test_` count in `test_suite/` = 176 = the runner's collected count; `Design:` tags = 176 (every test still traces to exactly one design instance).
- `grep` for `pytest.mark.skip` / `xfail` / `skipif` across `test_suite/` + `test_helpers/` → 0 hits.
- `grep -rniE 'sqlite|json.dump|pickle|/tmp|shelve'` over `implementation/*.py` → 0 hits.

## Step 8: Finalize PRD — 2026-08-09T17:50:00.000Z

`PRD_FINALIZED.md` is written. The `<step_7_diff>` was handed over in **three parts** (A = Step 7's fixes + fairness flags, B = impl-gen's 48 self-reported resolutions + reachability claims, C = test-gen's 2 skips + 6 dropped sub-assertions + 11-item near-miss register), with every Part B/C claim marked as a hypothesis to verify by reading the code.

### Line counts
| | lines | bytes |
|---|---|---|
| `PRD.md` | 720 | 148,958 |
| `PRD_FINALIZED.md` | 729 (+9, **+1.25 %**) | 173,079 (**+16.2 %**) |

42 hunks, all inline revisions plus two new paragraphs (§3.3 selector diagnosis, §3.9 zero-credit finalisation). No new sections.

### Changes, with per-edit pre-edit search log
Format: `{section} — {kind} — {what} — {impl anchor}` / **(a)** subject **(b)** paths read **(c)** wording adjustment.

1. **§2.3 — insert — `created_at` tie-break is the internal monotone insertion sequence.** `store.py:47,73-74`. (a) list ordering totality (b) `store.order_key`, `all_rows`, every `listing.eq`/`envelope.listing` caller, `derive.cycle_box_items`, `ledger._charge_sort_key`, `selector._rank_*`, `tradein_ops.resolve_demand_band` — all route through `order_key` (c) said "reflects the order in which the rows were written" rather than naming a field, since `_seq` is not serialized.
2. **§2.3 — insert — undeclared status/enum query filters on every list endpoint.** all 21 `list_*` routes. (a) filter surface (b) enumerated every `listing.eq(... shape.query_member(...))` call in `routes/*` and matched against §4's named filters (c) enumerated per-entity instead of a blanket "every status field", because units use `state`, box-items and trade-in-items carry two axes each; added the `ERR_VALIDATION`-not-`ERR_INVALID_ENUM` routing (`shape.query_member:170`).
3. **§2.3 — insert — `Member` list reads are silently scoped; `total_count` counts the scoped set.** `listing.scope_to_member:4-8`, `envelope.listing:39-49`. (a) member scoping (b) grepped every `scope_to_member` call: exactly 14 lists; confirmed plans/styles/units/assessments/jobs/capsules are unscoped (c) named the unscoped six explicitly so the rule is closed at both ends.
4. **§2.2 — insert — unknown path → `ERR_RESOURCE_NOT_FOUND` 404; undeclared method → `ERR_ROLE_FORBIDDEN` on **405**.** `app.py:51-59`. (a) framework-level errors (b) `app.create_app` handlers, `errors.ERROR_STATUS` (403 for that id), §5 table (c) called the 405 out as the one place the identifier leaves its §5 status, so §5 stays true.
5. **§2.8 — revise — credit-application bumps member `version` twice when it also drives `DELINQUENT → ACTIVE`.** `routes/members.py:239-240` + `ledger.refresh_standing:135` → `_recover_active:168`. (a) version count per request (b) all 10 `store.touch(member*)` sites; only `apply_credit` double-touches; checked the sibling OCC bullets (swap-create touches the cycle once, buy-out the item once) (c) scoped the clause to this endpoint and restated §2.4 as per-mutation-step, so the other two bullets' "by 1" stays true.
6. **§2.6 rung 4 — insert — rung 4 does not reach assessment/job endpoints.** `routes/grading.py` (no `auth.own` anywhere). (a) ownership reach (b) audited every endpoint where `Member` is authorized against its `auth.own` call — assessments/jobs are the only gap (c) named the two concrete `Member` capabilities (read, dispute) rather than a general "no check".
7. **§2.6 rung 23 — revise — pack joins the rung; creation and shipping stay out.** `routes/boxes.py:137,82`; no cycle check in `create_box`/`ship`. (a) `ERR_CYCLE_NOT_OPEN` scope (b) all four box endpoints (c) added the explicit exclusion clause so the closed list stays closed.
8. **§2.6 rung 26 — revise — start-return joins the rung.** `routes/boxes.py:235-236`. (a) `ERR_BOX_ITEM_ALREADY_SETTLED` scope (b) `buy_out:273`, `_confirm_rental:157`, `start_return:235` (c) —
9. **§2.6 rung 38 — revise — buy-out accept joins the rung.** `routes/buyouts.py:54-55`. (a) embargo scope (b) `create_swap_request:61`, `buy_out:281`, `accept_order:54`; confirmed `pay`/`cancel` do not check (c) —
10. **§3.1 — insert — cancellation with garments out → `ERR_INVALID_STATE`, after the from-state check.** `routes/members.py:128-133`. (a) undeclared refusal id (b) `cancel_member` full body (c) —
11. **§3.1 — insert — delinquency cascade also closes the money axis (`SETTLED`, `damage_fee_cents` 0).** `ledger.cancel_box_item:171-179`. (a) cascade side effects (b) both callers — `_fall_delinquent:154` and `reject_swap:169`; identical (c) tied it to §3.4's existing "settles the item at zero" so the two callers read as one rule.
12. **§3.1 — insert — size-up: ladder-step check precedes the cooling-off check.** `routes/members.py:97-102`. (a) refusal precedence (b) `size_up` only (c) —
13. **§3.2 — insert — `cycle_index` past 240 → `ERR_VALIDATION`.** `routes/cycles.py:58-59`. (a) undeclared refusal id (b) `create_cycle` (c) —
14. **§3.2 — revise — cycle open: state → member-ACTIVE (`ERR_INVALID_STATE`) → clock.** `routes/cycles.py:105-110`. (a) refusal order + id (b) `open_cycle` with `lookup.standing(block_pending=True)` above it (c) added the note that PENDING/CANCELLED are pre-empted by rungs 15/14, so only PAUSED/DELINQUENT reach this id.
15. **§3.2 — revise — window close: `DRAFT → CANCELLED`, `SUBMITTED → REJECTED`, both stamped `MEMBER_STANDING`.** `routes/cycles.py:143-153`. (a) the PRD self-contradiction Step 7 flagged (b) `close_swap_window`; cross-checked §3.4's terminal-state sentence (edit 21) (c) stated what the field records so the `CANCELLED`+`rejection_reason` pair is not read as an error.
16. **§3.2 — insert — assess-late from `SWAP_CLOSED` before `return_due_at` → `ERR_GRACE_NOT_EXPIRED`.** `routes/cycles.py:168-173`. (a) undeclared refusal (b) `assess_late` branch table (c) —
17. **§3.2 — insert — `days_late` re-derived only for `SHIPPED`/`WITH_MEMBER`; `late_fee_cents` computed for all five states from *stored* `days_late`.** `routes/cycles.py:179-195`. (a) the fee producer for `RETURNING`/`RECEIVED`/`LOST` (Part C near-miss 2) (b) `assess_late`, `start_return:249` (the other `days_late` writer), `calc.days_late_for`, `calc.late_fee_for_days`, `derive.cycle_box_items` ordering (c) split the "two sets" explicitly and added the touch-only-on-change rule.
18. **§3.2 — insert — non-terminal box items → `ERR_CYCLE_INVALID_STATE`, before rung 63.** `routes/cycles.py:223-230`. (a) gate ordering (b) `close_cycle` (c) —
19. **§3.2 — revise — `HELD` close requires a `DELINQUENT` owner, else `ERR_CYCLE_INVALID_STATE`; no invoice, no item sweep.** `routes/cycles.py:216-221`. (a) the `HELD` edge's preconditions (b) same (c) dropped a first draft that asserted the refusal was unreachable — I could not prove that, so the wording states the precondition only.
20. **§3.2 — insert — the invoice read is a live recompute; the cycle row's `surcharge_cents`/`invoice_total_cents` stay 0 until close.** `routes/cycles.py:24-42,232-234`, `serialize.cycle:73-74`. (a) stored-echo vs live (b) `invoice_of`, `read_invoice`, `close_cycle`, `serialize.cycle`, `derive.cycle_damage_fee`, `derive.cycle_credit_applied` (c) split the nine figures into derived-live vs read-back-from-row; folded in near-miss 1 (a fully waived item contributes 0 to the cycle's `damage_fee_cents`).
21. **§3.2 — revise — `invoice_total_cents` added to the begin-at-0 list; derived vs stored cycle fields enumerated.** same anchors. (a) field provenance (b) `serialize.cycle` field by field (c) —
22. **§3.3 — revise — allocate: `unit_id` wins over `style_id`; neither → `ERR_VALIDATION`.** `routes/boxes.py:68-75`. (a) input precedence (b) `allocate`; confirmed `style_id` is not even resolved when `unit_id` is present (c) said so explicitly, since it changes which 404 is *not* raised.
23. **§3.3 — revise — `slot_index` counts all existing items including terminal ones.** `boxops.next_slot_index:9-10`. (a) index derivation (b) both callers: `allocate:118`, `fulfill_swap:208` (c) —
24. **§3.3 — revise — capsule-fill predicate (held ∧ `OPEN`/`EMBARGO_LIFTED` ∧ same unit); standard fill is the complement.** `selector.box_fill:61-80`. (a) variant selection (b) `box_fill`, `member_active_capsule_ids`, `capsule_open` (c) rewrote standard fill as "whenever that capsule test does not", replacing "carries no capsule membership", which the code does not test.
25. **§3.3 — insert — staged empty-pool diagnosis (stock → size → grade → capsule), exclusion-emptied pool → `ERR_NO_ELIGIBLE_STOCK`.** `selector._stage_pools:34-48`, `box_fill:77-80`. (a) refusal identifier selection (b) `_stage_pools` and both callers; the explicit-`unit_id` path in `allocate:92-101` (c) explicitly excluded the explicit-unit path, which is screened by the rungs directly and in a different order.
26. **§3.3 — revise — pack: `ERR_CYCLE_NOT_OPEN` first, `ERR_BOX_NOT_FULL` last.** `routes/boxes.py:137-144`. (a) refusal order (b) `pack` (c) —
27. **§3.3 — insert — box ship: shipment `item_count` is 0; endpoint answers 201 with the `Shipment`.** `routes/boxes.py:174,190`. (a) response entity/status + an underived field (b) `ship`, `serialize.shipment`, `create_shipment` default, `issue_label:121` (the contrasting site) (c) added "nothing later corrects that figure" — checked no other path writes `item_count`.
28. **§3.3 — insert — direct retire leaves `retirement_eligible` false.** `routes/catalog.py:142-153`. (a) which retirements set the flag (b) grepped all three `retirement_eligible"] =` sites: `claims.py:188`, `grading.py:327,358` — direct retire is absent (c) named all three siblings so the rule is closed.
29. **§3.4 — insert — `SwapRequest` from-state → `ERR_INVALID_STATE`; rung 23 pre-empts it, it pre-empts rung 33.** `routes/swaps.py:113-120,135,161,182`. (a) an un-numbered gate's ladder position (b) all four swap transitions (c) gave both directions of the ordering, since Step 7's fix moved only one of the two.
30. **§3.4 — revise — approve's empty-pool errors follow §3.3's staged order.** `selector.swap_replacement:83-95`. (a) same subject as edit 25 (b) `swap_replacement`'s predicate differs (null capsule is admitted) but the staging is the shared `_stage_pools` (c) referenced §3.3 rather than restating, so the predicate difference is not overwritten.
31. **§3.4 — revise — fulfilment: new items take the same `slot_index` rule; they land in the box of the *first* returned item.** `routes/swaps.py:184-215`. (a) target box + index (b) `fulfill_swap` (c) —
32. **§3.4 — revise — `DRAFT`-at-window-close reaches `CANCELLED` yet carries `MEMBER_STANDING`.** `routes/cycles.py:147-149`. (a) same as edit 15 (b) same (c) cross-referenced §3.2 so the two sites cannot drift.
33. **§3.5 — insert — void with a moved shipment → `ERR_LABEL_INVALID_STATE`, label status tested first.** `routes/shipping.py:99-104`. (a) undeclared refusal id + order (b) `void_label` (c) —
34. **§3.5 — insert — reissue inherits `direction`, mints fresh `tracking_code`/`issued_at`, successor at `version` 1, predecessor bumped, 201.** `routes/shipping.py:131-143`. (a) reissue side effects (b) `reissue_label`, `mint_label`, `serialize.label` (c) —
35. **§3.5 — insert — recovery opens no assessment and ticks no `cycles_completed`; settled claim → `ERR_SHIPMENT_INVALID_STATE`.** `routes/shipping.py:294-323` vs `_receive_in_transit:257-285`. (a) cascade asymmetry (b) both receive branches (c) dropped an invented rationale ("already counted") and stated the fact only.
36. **§3.5 — insert — `LOST_LIABILITY` raised only when assessed value > 0.** `routes/shipping.py:356-358`. (a) conditional charge (b) `mark_lost`, `calc.lost_assessed_value` (c) —
37. **§3.5 — revise — settlement sets `retirement_eligible` true; names which `LOST_LIABILITY` charge is reduced.** `routes/claims.py:173-189`. (a) charge selection when several exist (b) `settle_claim` loop + `derive.member_charges` ordering (ascending) (c) **refuted Part B 25** — see below — and wrote "most recently created *of those that match*, else the **earliest**".
38. **§3.6 — revise — start-return preconditions in order, each with its identifier.** `routes/boxes.py:233-245`. (a) refusal order (b) `start_return` (c) added the unit-`OUT` requirement, which the PRD's list omitted.
39. **§3.6 — revise — target/pipeline check precedes G3 existence.** `routes/grading.py:37-46`. (a) stage placement (b) `open_assessment` (c) —
40. **§3.6 — revise — `DRAFT → VOIDED` only via direct retirement.** `routes/catalog.py:18-23,153`. (a) which retirement voids records (b) grepped `void_draft_assessments_for_unit`: one caller (c) named the three retirements that do *not* void, so the narrowing is explicit.
41. **§3.6 — insert — `RETIRE`-routed start and pass both → `ERR_ASSESSMENT_INVALID_STATE`; route test sits between from-state and unit-state.** `routes/grading.py:255-263,296-297`. (a) Step 7's impl fix (b) `start_job`, `pass_job`, `scrap_job` (c) —
42. **§3.6 — insert — a refused pass writes nothing; a passing job is the only writer of unit `current_grade`.** `routes/grading.py:300-323`. (a) who writes `current_grade` (b) grepped `current_grade"] =`: only `pass_job`, plus `acquire_unit`/`absorb` at mint (c) carved out acquisition and absorption explicitly.
43. **§3.6 — insert — `assessed_grade` written on the `WAIVED` path too.** `routes/grading.py:194-196`. (a) field written on both branches (b) `_confirm_rental` (c) —
44. **§3.6 — insert — "would draw on the waiver" = four conjuncts, incl. remaining cap > 0.** `routes/grading.py:171-181`. (a) rung 62's trigger (b) `_confirm_rental`, `calc.protection_waiver_remaining_cap` (c) —
45. **§3.7 — insert — accept re-checks embargo; premature quote expiry → `ERR_INVALID_STATE`.** `routes/buyouts.py:54-55,112-113`. (a) undeclared refusals (b) `accept_order`, `expire_order`, `cancel_order` (c) noted `QUOTED` *is* a declared from-state, so the generic id is not a from-state complaint.
46. **§3.8 — insert — announce/open temporal failures → `ERR_INVALID_STATE`; only the last two edges carry window codes.** `routes/capsules.py:69-86`. (a) undeclared refusals (b) all four capsule transitions (c) —
47. **§3.9 — insert — issue-label: shipment `item_count` = `declared_item_count`, no expiry check, 200 with the submission, four checks in order.** `routes/tradein.py:108-129`. (a) label checks + response (b) `issue_label` vs `boxes.ship` (c) **refuted Part B 10's "expiry" claim** — see below.
48. **§3.9 — insert — zero credited total → no entry, no auto-apply, still `CREDITED` with a deadline; auto-apply is the full waterfall.** `routes/tradein.py:153-163`, `ledger.apply_credit_waterfall:84-99`. (a) conditional money steps + waterfall scope (b) `finalize`, `apply_credit_waterfall` both call shapes (c) —
49. **§3.9 — insert — null `election_deadline_at`: election permitted, default refused.** `routes/tradein.py:239-241,257-259`. (a) the null case (b) both endpoints; confirmed `AWAITING_ELECTION` is reachable pre-finalisation via `tradein_ops.apply_confirmed_grade:28-29` (c) —
50. **§3.9 — revise — `apply-default` from a wrong disposition → `ERR_TRADE_IN_INVALID_STATE`, not `ERR_TRADE_IN_ITEM_NOT_REJECTED`.** `routes/tradein.py:255-256`. (a) id scoping (b) both endpoints (c) —
51. **§3.10 — revise — the trailing pause window has a floor and no ceiling; a future-dated pause counts.** `derive.pause_days_used_period:28-38`. (a) window shape (b) `pause_days_used_period`, `pause_days_used_lifetime`, `activate_pause:80`, `read_entitlements:176` (c) —
52. **§3.11 — insert — credit expire/revoke from-state and premature expiry both → `ERR_INVALID_STATE`.** `routes/ledgers.py:43-46,58-59`. (a) undeclared refusals (b) `expire_credit`, `revoke_credit`, `waive_charge` (which does use `ERR_CHARGE_NOT_OPEN`) (c) —
53. **§3.11 — revise — the explicit application narrows the charge side to the named entry.** `ledger.apply_credit_waterfall:84-100`, `routes/members.py:239`. (a) Step 7's impl fix (b) both call sites; §3.9's auto-apply stays full-waterfall (c) said the bucket order "does its real work on the standing waterfall" instead of deleting it, so §3.9 and §2.7 stay true.
54. **§3.11 — revise — rungs 58/59/60 evaluated over the whole ledger in that order; response is the charge entry, 200.** `routes/members.py:226-241`. (a) which refusal fires when (b) `apply_credit`, `derive.member_credit_balance` (c) —
55. **§4 preamble — insert — the seven transition endpoints that answer 201, and the three that mint a row yet answer 200.** grep of all `envelope.created` sites. (a) status/entity of every mutating response (b) all 23 `envelope.created` calls, matched against every `bp.post` (c) enumerated both sides so the "creation endpoint" definition is closed.

### Part B / Part C claims REFUTED by reading the code
- **Part B 25 — "else the most recent one."** `routes/claims.py:173-180` walks `derive.member_charges` (ascending `created_at`) with `elif target is None`, so the fallback is the **earliest** `LOST_LIABILITY` charge, not the most recent. (Among amount-matching charges the *last* does win.) Pinned: match on `amount_cents == assessed_value_cents`, most recent of those; otherwise the earliest.
- **Part B 10 — "Label checks on … trade-in issue-label run in narrative order: direction → status → expiry."** `routes/tradein.py:110-113` checks direction and status only — **there is no expiry check on issue-label**, and rung 37's `applies_to` correctly omits it. Pinned the absence explicitly rather than adding a check the impl does not perform. (Box ship *does* run all three: `routes/boxes.py:162-167`.)
- **Part C skip 2 — "check whether the implementation actually supports these two query params".** It does (`routes/boxes.py:203-206`), and so do ~20 further undeclared filters across the other list endpoints. Pinned as a general §2.3 rule with a closed enumeration, not as a one-row §4 patch.
- **Part B 29 — "staged in RUNG ORDER".** The stages are stock → size → grade → capsule, i.e. rung 54 *before* rung 53. The staging itself is as reported; the "rung order" gloss is wrong, so the pinned prose says the diagnosis deliberately does **not** run in rung order.

### Diff items deliberately NOT edited
| Item | Why |
|---|---|
| Part A: deleted `test_a_paused_household_may_not_open_a_box` | PRD rung 17 already enumerates its scope closed and `create_box` carries no `pause_gate_r`; the impl gates exactly the eight listed operations. Nothing to pin. |
| Part A: `retirement_eligible` on a `RETIRE`-acquired unit | §3.3 already states every acquired unit begins `retirement_eligible` false; `acquire_unit:117` matches. Pure fixture bug. |
| Part A: `app.py::_bind` 5 s → 12 s | Infrastructure only. |
| Part B: timestamp rendering rule | §2.4 already pins canonical three-digit UTC rendering, semantic comparison of client instants, and the logical clock; `timeutil.py` matches exactly. |
| Part B: enum closed iff-list | §2.9's closed list matches `shape.enum_in` call-for-call, including every named exclusion. |
| Part B: boundary inclusivity (rungs 33–42, credit expiry, delinquency, retirement, pause/capsule overlap) | Each already pinned verbatim in §2.6/§3.1/§3.6/§3.8/§3.10 and each matches the code. |
| Part B: money ordering, volume tier, buy-out step/floor, waiver cap scaling | §2.7/§3.2/§3.6/§3.7 already pin all of it; `calc.py` matches. |
| Part B 28, 35, 40, 41, 44 | Already pinned (`ERR_TRADE_IN_INVALID_STATE` scoping; rung 26 < 30 by numbering; uplift-on-wrong-route; recomputed cumulative cost; unconditional `SURCHARGE`). |
| Part B: rungs 64–67 unreachable; `ERR_PIPELINE_MISMATCH` unreachable; `ACCEPTED → CANCELLED` vacuous guard; `ERR_LABEL_DIRECTION_MISMATCH` absent on `POST /shipments`; PAUSED-before-eligibility; `PRO_RATA_CAP` tier scoping | Behaviourally equivalent to the PRD as written, or already determined by gate order. Declaring an unreachable code is what the PRD already does. |
| Part C dropped: `BoxItem.late_fee_cents` after start-return | §3.6 already says start-return "computes `days_late`" only; `start_return:249` writes nothing else. |
| Part C near-miss 8 (two `OPEN` cycles), 10 (`req_` prefix) | PRD already permissive / already verbatim in §2.2. |
| Part C near-miss 9, 11 | Step 7 already refuted them; §3.1 and §2.3 state both verbatim. |

## Step 9: Complete PRD — 2026-08-09T18:33:00.000Z

`workspace/PRD_COMPLETED.md` is written.

### Scale

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| Lines | 729 | 729 (unchanged — every edit is in-paragraph) |
| Chars | 173,079 | 191,438 (**+18,359**) |
| Lines touched | — | **48** |

Headings: unchanged. Table rows: unchanged count. No new sections, no new paragraphs.

**Counts: 31 ambiguity-pins, 17 mismatch-revisions.**

### Changes

- §2.1 — insert — ambiguity — rung 4 runs *before* the row is fetched only where the identifier **is** a member id (→403 for a non-existent member); every reach-through endpoint loads the row first (→its own 404) — `auth.py:39`, `routes/members.py:68` vs `routes/cycles.py:94`
- §2.3 — insert — ambiguity — FK-identifier filters are opaque strings, never resolved → empty page, not 404 — `listing.py:11`, `shape.py:174`
- §2.5 — revise — mismatch — G4's "blocks every member-scoped write" narrowed to the set rung 14 enumerates — `lookup.py:107`
- §2.6 r14 — revise — mismatch — enumerated the **exactly forty** writes that reach rung 14 and the 19 operator-driven writes that never consult standing — 40 × `lookup.standing`; e.g. `routes/ledgers.py:86`, `routes/shipping.py:95`
- §2.6 r38 — revise — mismatch — on `accept`, rung 40 is evaluated **ahead of** rung 38 (only inversion of ascending rung order in the system) — `routes/buyouts.py:48-55`
- §2.6 r40 — revise — mismatch — mirror of the above
- §2.9 — insert — ambiguity — empty/whitespace string, bool-as-integer, bad array entries, non-object body all → `ERR_VALIDATION`; an **absent** body reads as `{}` — `shape.py:17,53,66,122`
- §2.10 — revise — mismatch — swap-entitlement identity excludes `DRAFT` — `derive.py:102`
- §3.1 (plans) — revise ×3 — mismatch + ambiguity — `protection_available` is inert; `discount_pct` ≥ 0; PATCH writes the row even with no fields — `routes/plans.py:27,41,71`
- §3.1 (register) — insert — ambiguity — plan-resolve → `ERR_PLAN_RETIRED` → `ERR_DUPLICATE_EMAIL`; exact string compare — `routes/members.py:33`
- §3.1 (activate) — revise — ambiguity — `PENDING` tested before plan-`ACTIVE` — `routes/members.py:78`
- §3.1 (size-up) — insert — ambiguity — `new_size_code` routes to `ERR_VALIDATION`, not `ERR_INVALID_ENUM` — `routes/members.py:94`, `shape.py:150`
- §3.1 (entitlements) — revise — ambiguity — all non-`CLOSED` boxes (incl. `CANCELLED`); first `OPEN` cycle or 0; unfloored remainders; six live-derived member fields — `routes/members.py:161`, `serialize.py:30`
- §3.1 (standing) — insert — ambiguity — the fall is declared from `ACTIVE` only — `ledger.py:135`
- §3.2 (create) — insert — ambiguity — index over cycles of every status; `PAUSED`/`DELINQUENT` may be scheduled — `routes/cycles.py:52`
- §3.2 (open) — revise — ambiguity — charges raised after the `OPEN` write; a big plan charge self-inflicts `OPEN → HELD` in the same call — `routes/cycles.py:125`, `ledger.py:143`
- §3.2 (close) — revise — mismatch — `SURCHARGE` entry raised **unconditionally**, even at 0; `completed_cycles` is derived — `routes/cycles.py:237`
- §3.2 (cycle fields) — revise — ambiguity — `paused_days` window is `start_at`..`return_due_at`, half-open, summed — `derive.py:109`
- §3.3 (styles) — insert — ambiguity — style PATCH writes the row unconditionally — `routes/catalog.py:75`
- §3.3 (units) — revise — mismatch — the three optional inputs are stored as supplied; capsule resolved before `DISCONTINUED`; style `version` bumps — `routes/catalog.py:94`
- §3.3 (boxes) — revise — mismatch — box creation never reads the cycle's status — `routes/boxes.py:24`
- §3.3 (allocate) — insert — ambiguity — the box row is not written by an allocation — `routes/boxes.py:105`
- §3.3 (selector) — revise — mismatch — capsule-fill breaks `created_at` ties on insertion sequence; `cycles_completed` never decides — `selector.py:57`
- §3.5 (labels) — insert — ambiguity — `ERR_LABEL_DIRECTION_MISMATCH` is un-numbered and precedes rung 29 — `routes/boxes.py:162`, `routes/tradein.py:110`
- §3.5 (shipments) — insert — ambiguity — shipment creation checks nothing about the label beyond resolution — `routes/shipping.py:148`
- §3.5 (receipt) — insert — ambiguity — a `REJECT_RETURN` receipt fires no cascade — `routes/shipping.py:241`
- §3.5 (RTS) — revise — ambiguity — direction tested before status — `routes/shipping.py:366`
- §3.5 (claims) — insert — ambiguity — multiple claims per shipment permitted — `routes/claims.py:33`
- §3.5 (investigate) — insert — ambiguity — `member_liability_pct` is the decimal fraction, 0 at filing — `calc.py:171`
- §3.5 (settle) — insert — mismatch — a `WAIVED` charge's `net_due_cents` is re-derived — `ledger.py:27`, `routes/claims.py:181`
- §3.6 (start-return) — insert — ambiguity — the shipment's direction/status/owner are never checked — `routes/boxes.py:228`
- §3.6 (open record) — insert — ambiguity — target state unchecked; duplicate `DRAFT` records permitted — `routes/grading.py:30`
- §3.6 (confirm) — insert — ambiguity — settles the **most recently created** BoxItem for the unit across all boxes; enrolment read live; job created even with no item; `ERR_PIPELINE_MISMATCH` precedes rungs 26/30/31 — `routes/grading.py:23,146`
- §3.6 (pass) — insert — ambiguity — a pass on an already-`RETIRED` unit rewrites `retired_reason` — `routes/grading.py:311`
- §3.7 (quote) — insert — ambiguity — `ERR_BUYOUT_ALREADY_EXISTS` sits between rungs 26 and 38; fulfillment axis and unit `state` unconsulted — `routes/boxes.py:273`
- §3.7 (accept/cancel) — revise ×2 — mismatch — `DELINQUENT` may accept; rung 40 before 38; the cancel proviso holds by construction — `routes/buyouts.py:45,92`
- §3.8 (create) — insert — ambiguity — `release_at`/`close_at` never validated against each other — `routes/capsules.py:26`
- §3.8 (allocations) — insert — ambiguity — `ERR_CAPSULE_NOT_OPEN` and `ERR_CAPSULE_ELIGIBILITY_NOT_MET` are un-numbered; positions pinned — `routes/capsules.py:132`
- §3.9 (absorb) — insert — ambiguity — minted-unit defaults; two-axis state tested before the style — `routes/tradein.py:202`
- §3.9 (terminals) — revise — mismatch — `CREDITED`+`DONATE` is unreachable; an unabsorbed credited garment blocks `CLOSED` forever — `tradein_ops.py:17`, `routes/tradein.py:237`
- §3.10 (activate) — insert — ambiguity — the two blockers are un-numbered; past-due sweep covers every item ever held — `routes/pauses.py:73`, `derive.py:142`
- §3.10 (extension) — revise — mismatch — `paused_days_extension` **accumulates** — `routes/pauses.py:110`
- §3.10 (proration) — revise — ambiguity — exactly one cycle, first in `created_at` order, overwritten — `routes/pauses.py:94`
- §3.11 (charges) — revise — mismatch — `amount_cents` unbounded; `net_due` floored at 0; `cycle_id` need not be the member's — `routes/members.py:185`, `ledger.py:12`
- §3.11 (credits) — revise — ambiguity — `reason` validated then **discarded** — `routes/members.py:205`
- §3.11 (waterfall) — insert ×2 — ambiguity — `charge_entry_id` ownership unchecked; `SURCHARGE` sorts after all seven buckets — `routes/members.py:221`, `ledger.py:76`
- §4 row / boxes — revise — mismatch — "for an OPEN cycle" → "against a cycle in any status"
- §4 row / start-return — revise — mismatch — "under a RETURN label" → "under a supplied return shipment"

### Outright-false PRD claims found

1. **§3.1 mechanism** — "`protection_available` … says whether the damage-waiver add-on may be enrolled at all". Nothing reads it: only `routes/plans.py:27,41` write it and `serialize.py:21` echoes it. `routes/members.py:117` enrols without consulting it; `routes/cycles.py:117-129` charges the 900-cent fee without it; `routes/grading.py:169` keys the waiver on `member["protection_enrolled"]`.
2. **§3.7 uniformity/precondition** — "Acceptance additionally requires the member to be `ACTIVE`". `routes/buyouts.py:46` passes `block_pending=True` only — a `DELINQUENT` household accepts fine (rung 16's closed list names quoting, not acceptance).
3. **§2.6 r38 uniformity** — "governs acceptance exactly as it governs quoting". `routes/buyouts.py:48-55` evaluates rung 40 first; the order is inverted on that one endpoint.
4. **§2.10 identity** — swap-entitlement conservation counting `DRAFT`. `derive.py:102-106` excludes `DRAFT`; the identity is false whenever a draft exists. This is a §2 *summary* drifting from its own §3.4 detail, which states the in-flight set correctly.
5. **§2.6 r14 universal** — "Applies to every member-scoped write." 19 member-scoped writes never call `lookup.standing` (label void/expire/reissue, all four shipment transitions, six claim transitions, credit expire/revoke, charge waive, buy-out expire, allocation release, apply-default-disposition).
6. **§3.9 mechanism + declared pairing** — "a credited garment reaches a donated resting state only through the same election machinery a rejected garment uses", and the pairing `CREDITED`/`DONATE`. `tradein_ops.py:26-29` opens `AWAITING_ELECTION` **only** on a `RETIRE` grade, which simultaneously sets `REJECTED`; `routes/tradein.py:237` and `:255` both require `AWAITING_ELECTION`. A credited garment can only ever be `ABSORBED`.
7. **§3.3 self-contradiction** — "Every acquired unit begins with … `cycles_completed` … at 0 … and `capsule_id` null" in the same sentence that offers both as optional inputs. `routes/catalog.py:107-118` stores what was supplied.
8. **§3.3 tie-break** — capsule fill "breaking ties by `cycles_completed` ascending". `selector.py:57-58` sorts `(order_key, cycles_completed)`, and `order_key` is `(created_at, _seq)` with `_seq` unique — the declared key is unreachable.
9. **§3.10 finality** — "grants … a `paused_days_extension` **equal to** `days_requested`". `routes/pauses.py:110` uses `+=`; it accumulates across pauses.
10. **§4 row** — "Open a draft box for an OPEN cycle" — `routes/boxes.py:24-39` never reads the cycle's status, and §2.6 rung 23 already said box creation is outside the rung.
11. **§3.2 conditionality** — the `SURCHARGE` entry reads as parallel to the conditional `LATE_FEE` entry; `routes/cycles.py:237` raises it unconditionally, including at 0.

### Suspected implementation bugs (documented, not fixed)

1. **`ledger.py:27-37`** — `recompute_charge` writes `net_due_cents` *before* its early return for `WAIVED`. Via `routes/claims.py:181-184`, settling a claim over a previously waived `LOST_LIABILITY` charge leaves it `WAIVED` but with a non-zero `net_due_cents`, so it re-enters `outstanding_balance_cents` and can re-trigger delinquency.
2. **`routes/members.py:213-241`** — `charge_entry_id` is resolved by id alone with no owner check; one member's credit can settle a *different* member's charge, breaking §2.10's credit-conservation identity on both sides.
3. **`routes/members.py:191-196`** — `cycle_id` on a charge adjustment is resolved but never checked against the addressed member, so an operator charge can land in a foreign cycle's derived `credit_applied_cents` and invoice.
4. **`routes/pauses.py:76-78`** (with `derive.py:142-147`) — the past-due blocker sweeps every box item the member ever held, in any state on any cycle; a stale `days_late` on a terminal item of a long-closed cycle blocks pausing permanently.
5. **`routes/grading.py:23-27` + `:155`** — confirmation settles the *latest* BoxItem for the unit across all boxes. If the unit has been received, cleaned and re-allocated, an older assessment settles the newer item (and rung 26 can refuse a confirmation over an unrelated closed slot).
6. **`routes/grading.py:311-338`** — a pass on an already-`RETIRED` unit overwrites `retired_reason`, so a `LOST_WRITE_OFF` can become `CYCLE_CAP`/`COST_CAP`/`GRADE_RETIRE`.
7. **`routes/plans.py:79`, `routes/catalog.py:87`** — unconditional `store.touch` on PATCH bumps `version` for a no-op update, which can invalidate an unrelated in-flight OCC read.
8. **`routes/shipping.py:148-169`** — shipment creation validates nothing about the label but its existence (direction, status, expiry, owner all unchecked).
9. **`routes/capsules.py:26-35`** — `release_at`/`close_at` ordering is never validated; an inverted wave is creatable and permanently unopenable.

### Ladder walk and un-numbered gates

**All 68 rungs walked against code.** R1–5 `auth.py:23-42`; R6–13 `lookup.py:14-102` plus `routes/swaps.py:34-44`; R14–16 `lookup.py:107-115` (verified rung 16 fires at **exactly** the five endpoints its closed list names); R17–18 `lookup.py:120-129` (verified rung 17 at exactly the eight endpoints named, rung 18 at exactly three); R19–21 `routes/swaps.py:49`, `routes/boxes.py:270`, `routes/members.py:224`; R22–32 across the cycle/box/box-item/unit/shipment/label/assessment/trade-in/member route bodies; R33–43 the window tests in cycles/swaps/boxes/shipping/capsules/buyouts/tradein/claims/members; R44–52 the entitlement tests; R53–57 `selector.py:34-48`, `routes/boxes.py:92-101`, `routes/tradein.py:204`; R58–63 `routes/members.py:230-238`, `routes/ledgers.py:93`, `routes/boxes.py:289`, `routes/grading.py:173-181`, `routes/cycles.py:229`; R64–67 confirmed unreachable defensive guards (no code raises them — `ERR_UNIT_CONSERVATION_VIOLATION`, `ERR_SLOT_CONSERVATION_VIOLATION`, `ERR_CREDIT_CONSERVATION_VIOLATION` appear only in `errors.py`; `ERR_SWAP_CONSERVATION_VIOLATION` is raised at `routes/swaps.py:193` but is structurally unreachable behind rung 46); R68 `routes/pauses.py:84-90` and `routes/capsules.py:31-35`.

**Un-numbered gates found, with ladder positions (all now pinned in the PRD):**

| Gate | Endpoint | Position |
|---|---|---|
| `ERR_PLAN_RETIRED` | register / activate | after rung 6 / after the rung-32 `PENDING` test |
| `ERR_DUPLICATE_EMAIL`, `ERR_DUPLICATE_SKU` | register / style create | after rung 6 resp. after shape |
| `ERR_VALIDATION` (index > 240) | cycle create | after rung 15 |
| `ERR_INVALID_STATE` (member not `ACTIVE`) | cycle open, pause activate | between rung 22/32 and rung 34 |
| `ERR_BOX_NOT_FULL` | box pack | after rung 24 |
| `ERR_LABEL_DIRECTION_MISMATCH` | box ship, trade-in issue-label | **before** rung 29 |
| `ERR_SHIPMENT_DIRECTION_MISMATCH` | return-to-sender | **before** rung 28 |
| `ERR_LABEL_NOT_EXPIRED` | label expire | after rung 29 |
| `ERR_LABEL_INVALID_STATE` (shipment already moved) | label void | after rung 29 |
| SwapRequest own from-state (`ERR_INVALID_STATE`) | all five swap writes | between rung 23 and rung 33 |
| `ERR_RETURN_ITEM_NOT_RECEIVED` | swap fulfil | after the own from-state, before rung 67 |
| `ERR_BUYOUT_ALREADY_EXISTS` | buy-out quote | between rung 26 and rung 38 |
| `ERR_INVALID_STATE` (TTL not elapsed) | buy-out expire | after rung 32 |
| `ERR_PIPELINE_MISMATCH` | confirm | before rungs 26, 30, 31 |
| `ERR_ASSESSMENT_TARGET_MISMATCH` | open assessment | before G3 (already pinned) |
| `ERR_ASSESSMENT_INVALID_STATE` (`RETIRE` route) | job start / pass | after the job from-state, before rungs 27 and 51 |
| `ERR_STYLE_DISCONTINUED` | unit acquire | after rungs 8 and 12 |
| `ERR_CAPSULE_NOT_OPEN` | capsule allocation | after rung 17, **before** rung 39 |
| `ERR_CAPSULE_ELIGIBILITY_NOT_MET` | capsule allocation | after rung 39, before rung 47 |
| `ERR_CAPSULE_EMBARGO_NOT_REACHED`, `ERR_CAPSULE_CLOSE_NOT_DUE`, capsule announce/open window | capsule transitions | after rung 32 |
| `ERR_SHIPMENT_IN_TRANSIT_BLOCKS_PAUSE`, `ERR_UNIT_PAST_DUE_BLOCKS_PAUSE` | pause activate | after rung 32, before rungs 48/49 |
| `ERR_INVALID_STATE` (expiry instant not passed) | credit expire | after rung 32 |
| `ERR_TRADE_IN_INVALID_STATE` (garments not all graded) | finalize | after rung 31 |
| `ERR_ELECTION_NOT_DUE` | apply-default-disposition | after rung 31 |
| `ERR_CLAIM_SHIPMENT_NOT_LOST` | file claim / investigate | before rung 42 / after rung 32 |
| `ERR_SHIPMENT_INVALID_STATE` (settled claim) | recovery receipt | before the transition |
| `ERR_CYCLE_INVALID_STATE` (item sweep) | cycle close | after rung 22, before rung 63 |
| **Absent** gates (no check at all) | shipment↔label consistency; start-return shipment direction; buy-out fulfillment axis; `charge_entry_id` ownership; adjustment `cycle_id` ownership; duplicate claims; `release_at` < `close_at`; duplicate assessments | — |

### Orchestrator's post-run verification
`find . -newer workspace/implementation/results.8.json` lists **only** `worklog.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md` and the wave-2 sweep artifacts — Steps 8 and 9 touched documentation only; no implementation or test file was modified after the green sweep.

---

# Pipeline complete — Steps 1–9

`tasks/task_0953_kids_clothing_rent_swap/` — 21 entities · 16 SMs (8 non-linear) · 61 calcs · 68 rungs · **126 endpoints** · 95 errors · 8 roles · 12-gate write order · depth-7 cascades · **176/176 tests × 16 green rounds**.

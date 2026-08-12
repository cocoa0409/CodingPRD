# Worklog — task_1151_sugar_crop_receiving_station_cooperative

## Step 1: Create Task Directory — 2026-08-11T03:10:00.000Z

Pre-assigned by orchestration prompt: `tasks/task_1151_sugar_crop_receiving_station_cooperative/` with `workspace/` subdirectory already present (empty). Step 1 auto-index scan skipped per instructions; recorded as done.

Scenario: Sugar Crop Receiving Station & Cooperative Payment (American Crystal Sugar co-op): load ticket & tare/net weight, quality sampling (sugar content) & payment factor, harvest scheduling & piling ground capacity, deduction for dirt/leaf trash, cooperative member share & pool payment installments, transport allowance & haul distance, deterioration in storage & loss allocation, final pool settlement.

Difficulty parameter: "generate task hard than expert level!" (passes through to prd-bench-scaffold-generator at Step 2 only).

## Step 2: Generate Scaffold — 2026-08-11T04:15:00.000Z

Done. Scaffold generated for the sugar co-op scenario at "harder than expert" level and lint-clean.

## Files written

| File | Lines | Contents |
|---|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_1151_sugar_crop_receiving_station_cooperative/SCAFFOLD.yaml` | 1539 | §1.0–§1.7 only (no design keys) |
| `/home/ubuntu/github/CodingPRD/tasks/task_1151_sugar_crop_receiving_station_cooperative/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 749 | single key `scaffold_difficulty_design` (§1.8) |
| `/home/ubuntu/github/CodingPRD/tasks/task_1151_sugar_crop_receiving_station_cooperative/SCAFFOLD_CORNER_DESIGN.yaml` | 1162 | single key `scaffold_corner_design` (§1.9) |

## SCAFFOLD.yaml counts (beyond expert band, per the difficulty parameter)
- **13 entities**: Campaign, Member, ReceivingStation, StoragePile (parallel fill × condition dimensions), HarvestBooking (with WAITLISTED + promotion), LoadTicket (reweigh cycle), QualitySample (invalidate cycle + SoD), PileAllocation (junction), StorageLossEvent (dual-method), PaymentPool, PoolInstallment, PaymentLedgerEntry (append-only, self-referential reversals), SettlementStatement (dispute–revise cycle)
- **60 endpoints** (41 writes incl. `POST /api/_clock/set_current_utc` with the mandatory 2026-05-01T00:00:00Z default; 19 reads covering every FK reverse-reachability)
- **11 state-machine blocks / 45 transitions** (cycles on Ticket, Sample, Settlement, Member; parallel dims on Pile; compound bubble-up Campaign←Pool←Settlement)
- **10 calculations** (dual-variant payment factor and deterioration loss; nested min/max trash tiers; pinned round-per-ticket transport allowance; waterfall installment + settlement with remainder/delta assignment; selector-pinned waitlist promotion)
- **10 validation priority tiers**, **28 error codes**, **6 roles** (segregation-of-duties: sample recorder ≠ verifier; MEMBER is entity_backed), **2 OCC concurrency rules** (`installment-create-stale-pool`, `settlement-revise-stale-version`)

## §1.8 / §1.9 instance counts
- **§1.8: 18 instances** — all 9 rules × 2 instances, each with the required differentiation (different entity domains, modes (a)/(b), different entities/triggers/category-pairs/metrics/interval-semantics/conserved-quantities). All formula-derived asserts are precomputed literals (verified by executing the formulas in Python: e.g. advances 123865/86135, loss split 379.62/255.00, price 76.8118, finals 456732/333268, conservation sum == 1000000).
- **§1.9: 54 instances** (46 active + 8 `excluded_because` stubs that resolve to §1.8 instance names), spanning all nine taxonomy sections: entities (7), state_machines (10), calculations (6), validations (11), endpoints (3), errors (8 stubs), rbac (5), complexity_layers (3), consistency_model (1).

## Lint verdict (verbatim)
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(60 endpoints, 13 entities, 18 §1.8 + 46 §1.9 active instances, 839 calls scanned; 0 violations.)

Two fixes were needed en route: quoting YAML flow-mapping-hostile capture/grounds values (`$.data[0].id`, `errors[...]`), and renaming sub-resource parent placeholders to `{id}` (the linter's sub-resource check matches the literal `{id}` segment). No sibling tasks were consulted.

## Step 3: Copy Shared Files — 2026-08-11T04:17:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-11T04:25:00.000Z

PRD generation complete.

## Summary

**Path**: `/home/ubuntu/github/CodingPRD/tasks/task_1151_sugar_crop_receiving_station_cooperative/workspace/PRD.md`

**Size**: 324 lines, 7,797 words, 56,019 bytes.

**Sections**:
- 1. Introduction (2 paragraphs — business pain-point angle)
- 2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (verbatim fixed block)
  - 2.3 Pagination
  - 2.4 Common Resource Properties
  - 2.5 Weight, Tonnage, and Precision Conventions
  - 2.6 Optimistic Concurrency Control
  - 2.7 Validation Order and Resource Existence
  - 2.8 Derived Totals and Ledger Reconciliation
  - 2.9 The Logical Clock
- 3. Business Logic & Workflows
  - 3.1 Campaign Setup, Stations, and the Membership Roster
  - 3.2 Booking the Harvest: Slots, Capacity, and the Waitlist
  - 3.3 The Weighbridge: From Truck to Net Weight
  - 3.4 Quality Sampling: Sugar, Trash, and Segregation of Duties
  - 3.5 From Weight to Value: Trash Deduction, Payment Factors, and Provisional Valuation
  - 3.6 Acceptance into the Pile: Final Figures and Allocations
  - 3.7 Crediting the Pool: Accrual and the 110% Cap
  - 3.8 Piles and Deterioration: Seal, Survey, and Loss Allocation
  - 3.9 Pool Lifecycle and Installment Advances
  - 3.10 Pool Close, Final Price, and Settlement Statements
- 4. Endpoint Definitions (60 endpoints, 4-column table)
- 5. Error Code Catalogue (28 errors, 2-column table)

**Self-Audit Results**:

```
Contract 1 — Field-Name Coverage:
  entities[].fields:           73 required, 73 present, 0 missing
  endpoints[].input+path_params: 47 required, 47 present, 0 missing
  Status: PASS

Contract 2 — Rule Coverage:
  validations[] with priority:        10/10 expressed (§2.7 explicit priority order)
  concurrency_rules[] OCC rejections: 2/2 expressed (expected_pool_version + expected_settlement_version, both with ERR_STALE_VERSION/412)
  state_machines[].transitions:       45/45 expressed across §3.1–3.10
  calculations[]:                     10/10 fully expressed (net_weight_and_trash_deduction, payment_factor PROVISIONAL+FINAL, provisional_value, transport_allowance with pinned rounding order, deterioration_loss TABLE_RATE+RESURVEY, loss_allocation with floor+remainder, waitlist_promotion, installment_waterfall, final_pool_price, final_pool_settlement with delta-absorption and conservation invariant)
  validations[] conditions:           all matchable to error_ids in prose
  endpoints[].side_effects:           33/33 with side-effects narrated
  entities[].fields[] structured:     98/98 reconstructible (types, defaults, enum sets, nullability covered)
  sibling-branch symmetry:            all parallel transition branches rendered with equal density
  All 28 scaffold error IDs present in prose
  31/31 high-risk rule family spot-checks pass
  Status: PASS

Contract 3 — §3 Path Purity:
  backtick tokens scanned in §3: 542
  tokens starting with `/`:            0
  bare HTTP-method tokens:             0
  method+path combined tokens:         0
  Status: PASS
```

**Zero-silence / coverage audit**: PASS — every scaffold field name, error ID, state value, role, calculation, transition, OCC rule, and validation is rendered in PRD prose. No rules were invented; no rules were omitted; all formulas translated from pseudocode into natural language per the reconstruction test (e.g., trash deduction constants 3.00/10.00/1.5, payment factor slope 0.04 from reference 16.00 with clamp band 0.70–1.30 and low-sugar penalty 0.05 below 13.00, transport bands 120/180/240/300 across 15/40/80 mile boundaries, daily deterioration rate 0.0008, 5.00% loss-declared threshold, 110% accrual cap, weigh window −1800s/+3600s, trash rejection boundary 20.00).

## Step 5: Generate Unit Tests — 2026-08-11T04:50:00.000Z

All audits pass. Final state is complete.

## Summary

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1151_sugar_crop_receiving_station_cooperative/`):

`test_helpers/` (9 files): `__init__.py` (barrel), `types.py` (13 entity TypedDicts — `PaymentLedgerEntry` correctly omits `updated_at`/`version` per the append-only rule, 14 status/role enums), `api_client.py` (60 endpoint methods), `api_errors.py` (28 error IDs + HTTP map, registered with the framework), `assertions.py` (13 entity assertions + station tonnage invariant), `factories.py` (17 payload factories), `constants.py` (PRD §3.5/§3.8/§3.10 thresholds, slots, clock defaults), `test_users.py` (6 role header constants + `make_member_headers(member.id)` builder for the entity-backed MEMBER role + per-role builders for SoD technician IDs), `fixtures.py` (~40 composite helpers: world builders, ticket lifecycle shortcuts to WEIGHED/SAMPLED/ACCEPTED/CREDITED, pool/installment helpers, seal/reclaim/loss helpers, and full-lifecycle composites through closed pool and disputed settlement).

`test_suite/` (10 files): `conftest.py` + `test_01_entities_baseline.py` (9), `test_02_booking_lifecycle.py` (14), `test_03_weighbridge.py` (9), `test_04_quality_sampling.py` (6), `test_05_acceptance_and_piles.py` (15), `test_06_pool_credit_installments_ledger.py` (11), `test_07_loss_and_reclaim.py` (7), `test_08_settlements.py` (5), `test_09_security_rbac.py` (4). **81 tests total**, all collecting cleanly.

**Queue A (Difficulty):** 34 tests over 17 of 18 instances (exactly 2 each).
**Queue B (Corner):** 47 tests over 45 of 46 non-stub instances (43×1, plus 2 tests each for `ledger_entry_is_append_only_immutable` and `weigh_outside_slot_window_then_at_window_edge`). All 8 `excluded_because:` stubs left untranslated; every stub's `difficulty_instance` cross-reference resolves.

**Skipped instances (2), with reasons:**
1. `Difficulty/transitive_cascade/loss_allocate_cascades_allocations_pile_station` — the instance's literals are computed with integer-pound flooring (`floor(634.62 × 47328/79328) = 378` + 1.62 remainder → `a1_rem == 46948.38`), which **contradicts** PRD §3.8's "floored toward zero to 2 decimal places" (correct: shares 378.62/255.99, 0.01 remainder → `a1_rem == 46949.37`). PRD does not derive the asserted outcome — skipped, not weakened.
2. `Corner/state_machines/pool_and_campaign_settle_when_all_statements_paid` — its asserted sugar/gross/final-settlement literals (7558.69 / 580597 / 456732 …) all derive from the same non-PRD loss split, so the asserted outcomes are not PRD-derivable. Skipped.

**Stage 2 self-audit results:**
- Tag coverage: 81/81 tests carry exactly one `Design:` tag as the docstring's last line; 0 unresolvable/mis-sectioned tags; every emitted difficulty instance has ≥2 tests, every emitted corner instance ≥1.
- Citation sweep: 104 quoted docstring segments (≥6 words) all survive literal whitespace-normalized grep of `workspace/PRD.md` (7 initial failures — `...` abbreviations and trailing-period drift — were rewritten to full verbatim sentences).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold" references in generated code.
- Per-file lint: pyflakes clean on all test files and all helper modules (barrel `__init__.py` re-export warnings excluded by design).
- `python3 -m pytest test_suite --collect-only` → 81 tests, 0 errors.

One judgment call to flag: absolute `version == 1/2/3` literals (member defaults, version-increment corner test) were kept as designed — PRD §2.4 ("a system-managed counter starting at creation and incremented by exactly 1") doesn't explicitly pin the initial value, but the design indices were pre-audited with these literals and no PRD sentence contradicts them (unlike the loss-allocation contradiction above, which was skipped).

## Step 6: Generate Implementation — 2026-08-11T04:55:00.000Z

All done. Here's the summary.

## Implementation Summary

### Files written (under `/home/ubuntu/github/CodingPRD/tasks/task_1151_sugar_crop_receiving_station_cooperative/workspace/implementation/`)

| Path | Lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 82 |
| `db.py` | 102 |
| `errors.py` | 46 |
| `middleware.py` | 36 |
| `response.py` | 54 |
| `serializers.py` | 243 |
| `routes/__init__.py` | 0 |
| `routes/_common.py` | 96 |
| `routes/bookings.py` | 190 |
| `routes/campaigns.py` | 82 |
| `routes/clock.py` | 19 |
| `routes/installments.py` | 47 |
| `routes/ledger.py` | 79 |
| `routes/loss_events.py` | 159 |
| `routes/members.py` | 95 |
| `routes/pile_allocations.py` | 40 |
| `routes/piles.py` | 122 |
| `routes/pools.py` | 132 |
| `routes/samples.py` | 137 |
| `routes/settlements.py` | 262 |
| `routes/stations.py` | 49 |
| `routes/tickets.py` | 270 |
| `services/calc.py` | 306 |
| `services/cascade.py` | 66 |

Total: 2725 lines.

### Endpoint coverage vs SCAFFOLD.yaml §1.5
All 60 declared endpoints registered with matching method + path (verified via `app.url_map.iter_rules()`): 1 clock, 4 campaigns, 4 members, 3 stations, 6 piles, 6 bookings, 9 tickets, 5 samples, 5 pools, 1 installment issue, 3 loss events, 2 pile-allocations, 3 ledger, 8 settlements.

### State machines implemented
Campaign (OPEN→CLOSED→SETTLING→SETTLED), Member (ACTIVE↔SUSPENDED), HarvestBooking (REQUESTED/CONFIRMED/WAITLISTED/IN_USE/COMPLETED/CANCELLED incl. waitlist promotion cascade), LoadTicket (CREATED/WEIGHED/REWEIGHING/SAMPLED/ACCEPTED/CREDITED/REJECTED/VOIDED), QualitySample (COLLECTED/RESULT_RECORDED/VERIFIED with SoD), StoragePile fill_status (FILLING/SEALED/RECLAIMING/EMPTY) + condition_status (SOUND/DETERIORATING/LOSS_DECLARED), StorageLossEvent (DRAFT/CONFIRMED/ALLOCATED), PaymentPool (OPEN/ACCRUING/CLOSED/SETTLED), PoolInstallment (SCHEDULED/ISSUED), SettlementStatement (DRAFT/ISSUED/DISPUTED/ACKNOWLEDGED/PAID).

### Calculations implemented (services/calc.py)
`net_weight_and_trash_deduction` (free 3% band, heavy 1.5x at ≥10%, cap at t, 4dp), `payment_factor` (PROVISIONAL clamped [0.70,1.30]; FINAL unclamped with 0.05 low-sugar penalty), `provisional_value` (integer cents), `transport_allowance` (4 left-closed/right-open bands, round-per-ticket-then-sum), `deterioration_loss` (TABLE_RATE 0.0008/day on sealed snapshot; RESURVEY sealed − prior confirmed − measured), `loss_allocation` (floor-2dp shares + 0.01-lb remainder units by remaining_lbs DESC/created_at ASC), `waitlist_promotion` (eligibility by free capacity, created_at ASC + member_code ASC, iterate until none fit), `installment_waterfall` (E_m-weighted floors, one-cent remainder distribution, E_m − already_advanced caps), `final_pool_price` (sugar lbs 2dp; price 4dp), `final_pool_settlement` (raw gross, delta absorbed by largest entitlement, advances/final/total).

All monetary/tonnage math uses `Decimal` with ROUND_HALF_UP; percentages 2dp; tons 4dp; cents 0dp.

### Errors
All 29 catalog errors wired with correct HTTP status. Validation priority order honored: auth (401) → role (403) → ownership/SoD (403) → existence (404) → state/shape (409/400) → OCC (412) → member-compliance (409) → temporal (422/409) → capacity/arithmetic (409/422) → fiscal (409/422).

### Boot smoke test result
- `bash start.sh` with `PORT=18745/18746/18747` boots in ~2s.
- Probes verified: clock set (200), campaign create (201), unauthenticated (401 `ERR_UNAUTHENTICATED`), forbidden (403 `ERR_FORBIDDEN`), not-found (404 `ERR_NOT_FOUND`), plus a full E2E pipeline (member → booking → confirm → weigh → sample record/verify → accept → credit → seal/begin-reclaim/complete-reclaim → campaign close → pool close → settlement generate → issue → acknowledge → mark-paid → pool SETTLED, campaign SETTLED).
- Cold-boot confirmed: fresh process starts with empty store and clock at `2026-05-01T00:00:00Z`.
- All test processes killed after each run.

### Orchestrator route-pair verification (pre-sweep)
Live `app.url_map` vs SCAFFOLD.yaml §1.5: scaffold 60, impl 61 — MISSING: none; EXTRA: `GET /static/<path>` (Flask built-in, benign). PASS.

## Step 7: Run Tests and Iterate — 2026-08-11T05:05:00.000Z

## Summary

**Exit condition met: all 8 parallel rounds pass (81/81 passed, 0 failed in every round).** Orchestrator verified on disk: results.1.json … results.8.json all show passed=81 failed=0 total=81.

- **Iterations run:** 2 (iteration 1: 80/81 with one consistent failure across all 8 rounds; iteration 2 after fix: 81/81 × 8 rounds clean).

- **Tests deleted:** None. (One test was *split* per STEP 1c partial-coverage handling, not deleted — the uniquely-derivable half was kept.)

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1151_sugar_crop_receiving_station_cooperative/test_suite/test_07_loss_and_reclaim.py` — `test_resurvey_missing_or_impossible_measured_returns_error` renamed to `test_resurvey_impossible_measured_returns_error` and narrowed. The original test created a RESURVEY loss event without `measured_remaining_lbs` and expected creation to succeed (then confirm → `ERR_MEASURED_WEIGHT_INVALID`). That setup violates a verbatim PRD §3.8 sentence ("`measured_remaining_lbs` ... must be supplied at creation"), which the implementation faithfully enforces at creation with `ERR_INVALID_REQUEST`. Two PRD-faithful readers diverge on exactly this branch (creation-time vs confirm-time enforcement of the missing-measurement case), so the missing-measurement assertion failed unique derivability and was removed. The negative-result assertion (measured=100 on a pile with `sealed_stored_lbs=0` → loss would be negative → `ERR_MEASURED_WEIGHT_INVALID`) is verbatim covered ("the result must be at least 0, and ... a negative result is rejected with `ERR_MEASURED_WEIGHT_INVALID`") and uniquely derivable, so it was kept.

- **Fixes applied to `test_helpers/`:** None — fixtures, factories, and role-header builders were audited and found PRD-consistent.

- **Fixes applied to `implementation/`:** None — the implementation was already PRD-faithful; the single failure was a test-side unique-derivability collapse, not an implementation bug.

## Step 8: Finalize PRD — 2026-08-11T05:15:00.000Z

Done. PRD_FINALIZED.md is written with the minimal two-sentence patch.

## Summary

**Line counts / delta:** PRD.md = 324 lines / 56,019 chars; PRD_FINALIZED.md = 324 lines / 56,069 chars. Delta: 2 lines revised inline, +50 chars (+0.089%). No sections added.

**Changes (one per Step 7 diff item — there was only one):**
- §3.8 (creation ¶, line 198) — revise — appended "and a create request that omits it is rejected with `ERR_INVALID_REQUEST`" to the RESURVEY `measured_remaining_lbs` creation-requirement sentence, pinning the creation-time enforcement point and error code the implementation exhibits — `implementation/routes/loss_events.py:43-44`.
- §3.8 (confirm ¶, line 200) — revise — deleted "a missing measurement or " from "…a missing measurement or a negative result is rejected with `ERR_MEASURED_WEIGHT_INVALID`", so the confirm sentence claims only the negative-result branch (verbatim-kept by Step 7). The confirm-time missing-measurement guard (`loss_events.py:107-108`) is unreachable given the creation check, so the PRD now uniquely determines the observable behavior; the negative-result branch at `loss_events.py:113-114` remains covered — `implementation/routes/loss_events.py:107-114`.

**Per-edit pre-edit search log (both edits share one subject):**
- (a) Subject: enforcement point and error code for a RESURVEY loss event lacking `measured_remaining_lbs` (the "missing measurement" case).
- (b) Impl paths enumerated and read: `implementation/routes/loss_events.py` (full file — creation parse at 34-36 via `opt_field`/`as_decimal`, creation missing-check at 43-44 → `ERR_INVALID_REQUEST`, confirm guards at 107-114 → `ERR_MEASURED_WEIGHT_INVALID`, `_prior_confirmed_loss` at 61-66); `implementation/services/calc.py:142-143` (`resurvey_loss`); `implementation/serializers.py:172`; `implementation/routes/_common.py` (all field-parsing helpers raise `ERR_INVALID_REQUEST`); `implementation/errors.py` (ERR_INVALID_REQUEST=400, ERR_MEASURED_WEIGHT_INVALID=422). PRD touchpoints grepped/read: line 116 (validation priority — `ERR_INVALID_REQUEST` is a "request-shape" check, `ERR_MEASURED_WEIGHT_INVALID` an arithmetic check, so creation-time missing-field → `ERR_INVALID_REQUEST` fits the ordering), endpoint table lines 249/276-278 (no error semantics — unaffected), error catalog lines 301/320 (unchanged), §3.9 line 206 (precedent: creation-time declared-value violation pinned with `ERR_INVALID_REQUEST`). Test evidence: `test_suite/test_07_loss_and_reclaim.py:120-141` (narrowed test asserting only the negative-result branch).
- (c) Wording adjustment: Edit 1 was scoped to "a create request that omits it" (rather than a bare "else") so it cannot be read as constraining the `TABLE_RATE` branch, where the impl accepts and stores but ignores the field; Edit 2 was a pure deletion of "a missing measurement or " — chosen over any reworded confirm-time claim because the impl's confirm-time missing branch is unreachable, and under-determined wording there is safer than a false universal. No other impl path (negative-measured guard at 109-110, allocation, condition recompute, serialization) is described or excluded by either sentence, so all enumerated paths remain consistent.

## Step 9: Complete PRD — 2026-08-11T05:35:00.000Z

All edits verified. Here is the completion summary.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1151_sugar_crop_receiving_station_cooperative/workspace/PRD_COMPLETED.md`

**Source vs. result:** `PRD_FINALIZED.md` 324 lines / 56,069 chars → `PRD_COMPLETED.md` 324 lines / 60,188 chars (char-delta **+4,119**; all edits in-paragraph or in-table-cell, so line count is unchanged).

**Counts:** 20 ambiguity-pins, 4 mismatch-revisions.

**Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref):**

- §2.1 — insert — ambiguity — only `X-User-Role` is validated at auth time; a missing `X-User-ID` is not itself rejected — `implementation/middleware.py:18-22`
- §2.1 — insert — ambiguity — list endpoints scope a MEMBER caller by filtering to own `member_id` rather than rejecting with 403 — `implementation/routes/bookings.py:98-99`, `tickets.py:84-85`, `ledger.py:34-35`, `settlements.py:131-132`, `pile_allocations.py:30-31`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — `implementation/routes/_common.py:66-88`
- §2.3 — revise — mismatch — nested collection endpoints (`/campaigns/{id}/pools`, `/stations/{id}/piles`, `/tickets/{id}/samples`, `/piles/{id}/loss-events`, `/pools/{id}/installments`) do not paginate: ignore limit/offset, return all, meta `limit=total_count, offset=0` — `implementation/routes/campaigns.py:82`, `stations.py:49`, `samples.py:137`, `piles.py:122`, `pools.py:132`
- §2.3 — insert — ambiguity — list sort ties on `created_at` broken by `id` ascending — `implementation/routes/_common.py:93`
- §2.3 — insert — ambiguity — `has_more` = `offset + len(page) < total_count` — `implementation/response.py:36`
- §2.4 — revise — ambiguity — `version` starts at 1 at creation (was "starting at creation") — `implementation/db.py:87`
- §2.7 — revise — mismatch — rewrote the validation priority: body-parse 400s occur before resource lookup; resource existence (404) precedes ownership (403); SoD runs after sample state/type checks per §3.4; added rule that §3's per-operation orders (weigh §3.3, accept §3.6) govern over generic tiers — `implementation/routes/bookings.py:145-153`, `samples.py:83-91`, `tickets.py:99-114,145-183`, `settlements.py:166-174`
- §3.1 — revise — ambiguity — campaign close requires status `OPEN` in addition to no CONFIRMED/IN_USE bookings, both `ERR_INVALID_STATE` — `implementation/routes/campaigns.py:59-63`
- §3.1 — insert — ambiguity — non-positive `booking_capacity_tons` → `ERR_INVALID_REQUEST` — `implementation/routes/stations.py:19-20`
- §3.1 — insert — ambiguity — negative `haul_distance_miles` → `ERR_INVALID_REQUEST`; suspend requires ACTIVE / reinstate requires SUSPENDED, else `ERR_INVALID_STATE` — `implementation/routes/members.py:23-24,57-58,91-92`
- §3.2 — insert — ambiguity — booking create: `estimated_tons` ≤ 0 and `slot_end` ≤ `slot_start` → `ERR_INVALID_REQUEST`; unknown member `X-User-ID` → `ERR_NOT_FOUND`; campaign-OPEN check runs before member-compliance — `implementation/routes/bookings.py:50-63`
- §3.2 — insert — ambiguity — reschedule also enforces `slot_end` strictly after `slot_start` (`ERR_INVALID_REQUEST`) — `implementation/routes/bookings.py:156-157`
- §3.2 — insert — ambiguity — waitlist promotion treats exact-equality of `estimated_tons` to free capacity as fitting — `implementation/services/calc.py:202`
- §3.4 — insert — ambiguity — record-result: range violations are `ERR_INVALID_REQUEST` and run before state checks; sample must be `COLLECTED` (else `ERR_INVALID_STATE`), checked before the ticket-state check — `implementation/routes/samples.py:43-54`
- §3.4 — revise — ambiguity — verify check order pinned: `RESULT_RECORDED` state → `LAB_VERIFY` type → SoD — `implementation/routes/samples.py:86-91`
- §3.6 — insert — ambiguity — non-`SAMPLED` ticket is rejected with `ERR_INVALID_STATE` before the five acceptance preconditions — `implementation/routes/tickets.py:156-157`
- §3.8 — revise — mismatch — `measured_remaining_lbs` with `TABLE_RATE` is stored on the event unchanged (not discarded), only unused in the computation (was "ignored") — `implementation/routes/loss_events.py:34-36,52`
- §3.8 — insert — ambiguity — negative `measured_remaining_lbs` at confirm is itself `ERR_MEASURED_WEIGHT_INVALID` — `implementation/routes/loss_events.py:109-110`
- §3.8 — revise — mismatch — removed the claim that multiple events are processed in `survey_at` chronological order; impl allocates one event per allocate call in caller-chosen order, each allocation reducing `remaining_lbs` for subsequent ones — `implementation/routes/loss_events.py:123-159` (no ordering mechanism exists)
- §3.9 — revise — ambiguity — open-accrual requires the pool itself `OPEN` (else `ERR_INVALID_STATE`); campaign-OPEN check runs before the estimate-magnitude check — `implementation/routes/pools.py:34-40`
- §3.9 — insert — ambiguity — installment waterfall: a member whose cap (E_m − already-advanced) is zero or negative receives no advance — `implementation/services/calc.py:271-276`
- §3.10 — revise — ambiguity — pool close requires pool `ACCRUING` first (else `ERR_INVALID_STATE`), then the four listed conditions — `implementation/routes/pools.py:55-56`
- §3.10 — insert — ambiguity — settlement generation: requires pool `CLOSED` (else `ERR_INVALID_STATE`); DRAFT statements carry `advances_posted_cents`/`final_payment_cents`/`total_payment_cents` of 0 until issued; response is 201 array in delta-absorption order (largest raw gross, `member_code` ties); empty array when no member qualifies; generation is not idempotent — `implementation/routes/settlements.py:44-110`
- §4 (table) — revise — ambiguity — pinned exact filter query-params in five list-endpoint rows: bookings (`member_id, station_id, campaign_id, status`), tickets (`booking_id, member_id, station_id, status`), pile-allocations (`ticket_id, pile_id, member_id`), ledger-entries (`member_id, pool_id, installment_id, settlement_id, kind, reversal_of_id`), settlements (`member_id, campaign_id, pool_id, status`) — `implementation/routes/bookings.py:92-95`, `tickets.py:79-82`, `pile_allocations.py:26-28`, `ledger.py:27-32`, `settlements.py:126-129`

**Notable confirmations (no change needed):** all calculation formulas in §3.5/§3.8-§3.10 match `services/calc.py` exactly (trash tiers, factor clamp/penalty, rounding, waterfall remainder orders, delta-absorption tie-break, transport bands); every endpoint's role list in §4 matches its `require_roles` call; state machines, cascade effects, and version-increment claims all match impl; the accept five-precondition order and weigh sanity-before-window order were already pinned in §3.6/§3.3 and match impl (the §2.7 revision delegates to them).

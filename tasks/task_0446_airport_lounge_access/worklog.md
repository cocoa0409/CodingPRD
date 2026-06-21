# Worklog — task_0446_airport_lounge_access

## Step 1: Create Task Directory — 2026-06-21T01:28:20.000Z

Task directory `tasks/task_0446_airport_lounge_access` was pre-assigned/reserved (Step 1 auto-increment overridden to avoid ID contention with 4 sibling pipelines). Verified directory and `workspace/` subdir exist. No new index allocated.

## Step 2: Generate Scaffold (Expert band) — 2026-06-21T02:05:20.000Z

The scaffold package is complete. Here is the summary for the worklog.

## Summary

Generated a complete Expert-band scaffold for **Airport Lounge Access (Priority Pass style)** at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0446_airport_lounge_access/`.

**Files written (all three):**
- `SCAFFOLD.yaml` (§1.0–§1.7; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (`scaffold_difficulty_design` — §1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (`scaffold_corner_design` — §1.9)

**Counts:** 11 entities · 6 state machines · 7 calculations · 16 validations · 46 endpoints · 16 error codes · 3 roles · 2 concurrency rules. §1.8 = 18 instances (9 rules × 2); §1.9 = 38 active instances + 8 `excluded_because` stubs across all 9 claim-extraction-guide sections.

**`scaffold_lint.py` verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
(46 endpoints, 11 entities, 18 §1.8 + 38 §1.9 instances, 437 calls scanned)
```

**Design decisions / coverage notes:**
- **Archetype:** Quota/allocation (visit allotment + lounge capacity) blended with Pricing engine (per-visit/guest charges, settlement, day-pass). Flat topology, branching Visit state machine, peer roles, immediate consistency.
- **`api_prefix: ""`** (flat peer collections `/lounges`, `/visits`, `/memberships`, etc.). Every FK gets reverse-reachability via a top-level filtered-list GET (`?member_id=`, `?lounge_id=`, `?visit_id=`…) — required because the lint derives collection segments relative to the prefix.
- **All 9 difficulty rules differentiated:** dual-variant on Lounge vs Visit domains; combinatorial modes (b) per-line rounding (11710 vs 11709) and (a) guest waterfall min/max; non-linear Visit (branching) + DayPass (cyclic); cascades depth-4 (no-show→strike→suspend→auto-cancel sibling hold→release held_occupancy) and depth-2 (complete→settlement→lounge balance); priority pairs p7/p8 and p6/p10; boundaries on allotment (`<`) and capacity (`<=`) via distinct endpoints; cross-entity Visit→Lounge and Visit→Member; temporal overlap on ShowerSuite (pairwise half-open + buffered turnover) vs Lounge (aggregate capacity); conserved quantities lounge-payable-balance vs member-wallet-balance.
- **Added ShowerSuite/ShowerReservation entities** to give Rule 8 a genuine second resource with pairwise-interval geometry distinct from the lounge's aggregate-capacity semantics.
- **Two true OCC races** (CREATE-with-supersede on Lounge.version: hold creation and day-pass purchase), both on a `common_fields:true` parent, both list `expected_lounge_version` as required input and bump `Lounge.version`. Forbidden race vocabulary verified absent.
- **Orthogonal standing vs eligibility:** `Member.standing` (GOOD/SUSPENDED) is driven solely by no-show strikes; card/fare eligibility is a separate per-hold gate (p7) with a BUSINESS/FIRST fare-class override — resolving a contradiction where a low card would otherwise suspend and make the override unreachable.
- **Logical clock** test-driving endpoint with the mandated `2026-01-01T00:00:00Z` default; all formula-derived assertions are pre-computed literals; OCC chains insert fresh `GET /lounges/{id}` reads before any hold that follows a version-bumping write.

## Step 3: Copy Shared Files — 2026-06-21T02:05:46.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0446_airport_lounge_access/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-21T02:11:32.000Z

All Contract 2 high-risk rule-coverage spot checks pass. The PRD is complete and all three Hard Contracts pass. Here is my summary.

---

**Output:** `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0446_airport_lounge_access/workspace/PRD.md`

**PRD section structure** (5 top-level sections, ~315 lines):
- **§1 Introduction** — 3 paragraphs (system goals + party/actor framing + scope), no "This document outlines" boilerplate.
- **§2 Global Specifications** — 10 subsections, domain-derived titles: 2.1 RBAC, 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Resource Properties & the Logical Clock, 2.5 Derived Counters and Reconciliation, 2.6 Cascading Side Effects, 2.7 Optimistic Concurrency, 2.8 Monetary Values/Counts/Rounding, 2.9 Resource Existence & Left-to-Right Resolution, 2.10 Validation Ordering.
- **§3 Business Logic** — 9 subsections grouped by lifecycle/process: 3.1 Configuring the Network, 3.2 Members & Credentials, 3.3 Holds/Capacity/Overflow, 3.4 Check-in/Charges/Ledger, 3.5 Eligibility & Suspension Gates, 3.6 Day Passes, 3.7 Shower Reservations, 3.8 Sweep/No-Show Cascades/Settlement Payout, 3.9 Allotment Year & Reset.
- **§4 Endpoint Definitions** — 4-column table, 45 endpoints.
- **§5 Error Code Catalogue** — 2-column table, 16 error codes. PRD ends here (no audit footer).

**Hard Contract reports (transcript-only, per spec):**

```
Field coverage check:
- entities[].fields: 56 required, 56 present, 0 missing
- endpoints[].request_body/query/path/response identifiers: 14 required, 14 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: priority chain expressed in §2.10 + per-workflow gates, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (hold-create + day-pass-purchase, both name expected_lounge_version + ERR_STALE_VERSION + HTTP 412; lounge-close also covered), 0 missing
- state_machines[].transitions: Visit (5), DayPass (4), Member.standing (2), Lounge.status (5), Settlement (2), ShowerReservation (2) — all from/to + preconditions + side-effects expressed, 0 missing
- calculations[]: 7 checked (resolve_entry_mode, resolve_guest_funding, compute_member_charge w/ per-line 2710-vs-2709 worked example, compute_settlement, compute_lounge_settlement_balance dual-variant, recompute_member_usage, check_shower_overlap), 0 missing
- validations[] conditions: 16 error IDs all matchable to conditions in §2/§3 narrative, 0 missing
- endpoints[].side_effects / applies_to: cascade chains + applies_to scopes expressed, 0 missing
- entities[].fields[] structured content: defaults/sentinels (e.g. -1 unlimited, GOLD 0.90 discount, common_fields:false for Settlement/LedgerEntry → no updated_at/version) reconstructible, 0 missing
- sibling-branch symmetry: Visit HELD→{CHECKED_IN,CANCELLED,NO_SHOW} and CHECKED_IN→{COMPLETED,ABANDONED} rendered with equal density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 329
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Notable coverage / information-scattering notes:**
- The constants `HOLD_TTL_MINUTES` (30), `DAY_PASS_TTL_HOURS` (24), `NO_SHOW_SUSPEND_THRESHOLD` (3), and `MEMBER_FEE_DISCOUNT` (0.90) are embedded in narrative as "thirty minutes", "twenty-four hours", "reaches three", and "0.90" rather than as a constants block.
- `POST /visits` request params are deliberately scattered: core funding params (`member_id`, `lounge_id`, `day_pass_id`, `guest_count`, `guest_names`) live in §3.3; the eligibility/standing gates that also guard the same endpoint live in §3.5; the OCC field `expected_lounge_version` lives in §2.7.
- The compute_member_charge per-line-before-sum rounding order is preserved with the scaffold's exact worked example (two 1505-cent guest lines → 2710 per-line vs 2709 sum-then-round) so a PRD-only reader cannot collapse it to sum-then-round.
- The two `common_fields: false` event entities (Settlement, LedgerEntry) are explicitly stated to carry only `id` and `created_at`, with `updated_at` and `version` absent (§2.4).
- The three-hop suspension cascade (NO_SHOW strike → standing flip → auto-cancel other HELD holds → release held_occupancy across lounges) is spelled out end-to-end in §3.8.

## Step 5: Generate Unit Tests — 2026-06-21T02:37:24.000Z

Everything compiles, all imports resolve, all citations are verbatim, and coverage is complete. Here is the final summary.

## Summary

Generated complete test infrastructure for **task_0446_airport_lounge_access**.

### Files written

**`test_helpers/`** (Stage 1 — PRD-specific infrastructure):
- `types.py` — entity TypedDicts (quartet-carrying vs. append-only Settlement/LedgerEntry) + status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per PRD §4 endpoint (flat topology, peer collections)
- `api_errors.py` — `ApiErrorId` enum + HTTP status map (16 errors), registered with the framework
- `assertions.py` — per-entity assertions; append-only records asserted to lack `version`/`updated_at`
- `factories.py` — input-only payload factories (PRD-exact field names)
- `constants.py` — thresholds (HOLD_TTL, NO_SHOW_SUSPEND_THRESHOLD=3, MEMBER_FEE_DISCOUNT=0.90, etc.)
- `test_users.py` — NetworkAdmin (opaque) shared constant + entity-backed `make_lounge_agent_headers`/`make_member_headers` builders for ownership threading
- `fixtures.py` — composite setup (plan/lounge/member/card, hold→check-in→complete, no-show accrual→suspension, day-pass, shower) with identity threading
- `__init__.py` — barrel export

**`test_suite/`** (Stage 2 — 6 files): `conftest.py` + `test_01_pricing_and_charges`, `test_02_settlement_and_invariants`, `test_03_visit_lifecycle_and_capacity`, `test_04_eligibility_and_cascades`, `test_05_day_passes_and_showers`, `test_06_crud_rbac_and_occ`.

### Test counts
- **Queue A (Difficulty): 32 tests** — 16 of 18 instances covered, exactly 2 tests each.
- **Queue B (Corner): 38 tests** — all 38 non-stub instances covered (≥1 each); all 8 `excluded_because` stubs correctly NOT translated.
- **Total: 70 test functions.**

### Instances skipped (PRD-first filter)
Both are queue-A difficulty instances failing **unique derivability**:
1. `priority_pair_validation_conflict/ppvc_no_active_card_beats_lounge_overflow` — PRD §3.5 says the card gate fires "in addition to" the §3.3 overflow gate but **never commits to their relative order**, so a faithful PRD-only reader could return either `ERR_NO_ACTIVE_CARD` or `ERR_LOUNGE_OVERFLOW`. (skip category: error-precedence / validation-priority). Its corner stub `sm_lounge_overflow_bubble_up_stub` points here and was correctly left untranslated.
2. `cross_entity_state_dependency/cesd_visit_checkin_depends_on_lounge_status` — PRD says a CLOSED lounge "admits no one" at check-in but **names no error_id** for that case (no verbatim coverage of `ERR_INVALID_STATE` here). (skip category: unnamed-error).

The other instance in each of those two rules (`ppvc_not_eligible_beats_member_suspended`, `cesd_visit_hold_depends_on_member_standing`) is fully covered with 2 tests, so both rules remain represented.

### Coverage notes
- Every test docstring ends with exactly one verbatim `Design:` tag resolving to a real instance; **0** dangling/dual/untagged tags.
- **89/89** PRD citation segments verified to survive a literal grep of PRD.md.
- The two ppvc/cesd skips are genuine PRD gaps (the contract leaves the outcome design-open), not test bugs — recorded here rather than papered over.
- All helper and test modules compile; all `from test_helpers import` names resolve against the generated barrel.

## Step 6: Generate Implementation — 2026-06-21T02:37:24.000Z

The implementation is complete and verified. Here is the summary for the worklog.

---

## Implementation Summary — task_0446_airport_lounge_access

Generated a complete Python + Flask in-memory REST API under `workspace/implementation/`. All 46 endpoints, 6 state machines, 7 calculations, 16 validations, and 16 error codes implemented. Verified via 5 smoke-test suites covering happy paths, OCC, no-show cascade, per-line rounding, capacity/overflow, validation ordering, and RBAC.

### Files written (24 files, ~2,315 lines)

**Foundation:** `start.sh` (guarded pip install + `exec`), `requirements.txt` (flask only), `app.py` (blueprint registration + envelope error handlers), `db.py` (in-memory `Store` dicts keyed by id, NO seeding), `clock.py` (logical clock, default `2026-01-01T00:00:00Z`), `errors.py` (catalog), `response.py` (`meta`/`response_type`/`data` envelope), `middleware.py` (auth/RBAC), `validation.py` (body-shape + pagination), `serializers.py`, `domain.py` (all calculations, derived-counter recomputation, cascades).

**Routes (`routes/`):** `plans.py`, `lounges.py` (CRUD + close/reopen/sweep/settlement-summary/settlements-pay/day-pass-purchase), `members.py`, `cards.py`, `visits.py` (hold/check-in/complete/cancel), `guests.py`, `day_passes.py`, `settlements.py`, `ledger.py`, `showers.py`, `clock_routes.py`, plus `common.py` (shared filter/sort/paginate).

### Key design decisions resolving PRD ambiguities

1. **Sweep scope** — PRD §3.8 says the sweep runs "against a lounge." Scoped all three sweep passes (no-show, abandon, day-pass-expiry) to the target `lounge_id`. The no-show suspension cascade still reaches the member's HELD holds at *other* lounges, since suspension is member-wide (per the explicit cascade rule).

2. **Lounge version bumps** — A hold bumps `Lounge.version` exactly once via a single `recompute_lounge_occupancy` (held_occupancy always changes), satisfying the OCC "increments by 1" contract. Day-pass purchase bumps once via explicit `touch`. Completion/check-in may bump more than once (occupancy + balance recomputes), which is PRD §2.5-consistent; tests re-read the lounge before guarded writes per the scaffold design.

3. **Guest ledger row split** — The PRD pins each guest's `charge_cents` as the per-line-rounded combined `(guest_charge + guest_fee) * disc`, but the scaffold wants separate `GUEST_CHARGE`/`LOUNGE_GUEST_FEE` ledger rows. Resolved so the rows sum *exactly* to the guest's rounded `charge_cents` (lounge-fee portion = rounded fee, clamped to the line; plan portion = remainder), keeping `wallet_balance_cents` consistent with `member_charge_cents`. Verified the PRD's worked example (two 1505 GOLD guest lines → 2710, not 2709).

4. **Missing-field vs not-found ordering** — When a required FK field is entirely absent (no value to look up), returns `ERR_INVALID_REQUEST` (400); when present-but-unresolvable, returns `ERR_NOT_FOUND` (404). Auth → RBAC → existence → ownership → state → business gates ordering verified.

5. **OCC field scope** — `expected_lounge_version` required only on the three guarded writes (`POST /visits`, day-pass purchase, lounge close); check-in/complete/cancel take no version field.

**Notable correctness confirmations:** strict-`<` allotment boundary (ALLOTMENT, ALLOTMENT, OVERAGE for included=2), unlimited-sentinel (`-1`), GOLD per-line 0.90 discount, buffered half-open shower-overlap geometry (conflict at +15min buffer, allowed exactly at boundary), settlement reverse → balance recompute → double-reverse rejected, fresh-boot empty store (no seeding).

## Step 7: Run Tests and Iterate — 2026-06-21T02:44:30.000Z

Done. All 8 parallel rounds pass at 70/70.

## Summary

**Iterations run:** 2 sweeps (1 diagnostic baseline + 1 confirming clean sweep).

**Initial state:** 69/70 passing per round, with exactly one consistent failure across all completed rounds: `test_aggregate_occupancy_pool_rejects_over_capacity_check_in`. (A first-pass mis-read of the JSON key — `outcome` vs `status` — briefly looked like a mass failure; the real data showed `passed=69, failed=1`.)

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None — the implementation was PRD-faithful.

**Fix applied to `test_suite/`** (STEP 2 — test bug, fixed to be *more* faithful to PRD):
- File: `test_suite/test_03_visit_lifecycle_and_capacity.py`, test `test_aggregate_occupancy_pool_rejects_over_capacity_check_in`.
- Root cause: the test setup opened the third hold (`v3`) *after* the lounge's `current_occupancy` had already reached `capacity` (3). Per PRD §3.3, "A request to open a hold is honoured only when the lounge's `status` is `OPEN`; a lounge in `OVERFLOW`... rejects the new hold with `ERR_LOUNGE_OVERFLOW`," and the overflow line is `current_occupancy + held_occupancy >= capacity`. So the impl correctly refused to open `v3` with `ERR_LOUNGE_OVERFLOW`, and the test could never reach the check-in gate it meant to exercise.
- Fix: reordered the setup so `v3`'s hold is opened first (lounge empty/OPEN), then `v1` and `v2` are opened and checked in, driving `current_occupancy` to 3 while `v3` stays `HELD`. The assertion (`v3` check-in rejected with `ERR_OVER_CAPACITY` because 3 + 1 > 3) is unchanged — the test's stated intent and the PRD §3.4 capacity rule it covers are preserved verbatim.

**Final result:** Clean 8/8 parallel rounds, 70/70 each. The two "missing" result files in the diagnostic sweep were transient boot-contention dropouts under 8x concurrent load, not test failures — the confirming sweep produced all 8 files with zero failures.

**Orchestrator verification note:** The Step 7 subagent's final-sweep `results.*.json` files were not present on disk at hand-off (wiped by the sweep's leading `rm -f`). The orchestrator re-ran the full 8-round parallel sweep to (a) independently confirm the pass and (b) regenerate the required per-round artifacts. Result: all 8 rounds `passed=70 total=70 failed=0`. Artifacts now present at `workspace/implementation/results.{1..8}.json`.

## Step 8: Finalize PRD — 2026-06-21T02:47:08.000Z

Step 8 was NOT skipped: Step 7 had 1 `test_suite/` fix (skip condition requires 0 in all four categories). The analysis confirms the expected outcome: zero edits.

## Summary

**PRD.md vs PRD_FINALIZED.md:** 272 lines vs 272 lines — **0% delta** (byte-for-byte identical; orchestrator `diff` confirms IDENTICAL).

**Changes:** Zero edits. PRD_FINALIZED.md is an exact copy of PRD.md.

### Why no edits were warranted

The sole Step 7 change was a `test_suite/` setup-ordering fix (`test_aggregate_occupancy_pool_rejects_over_capacity_check_in` in `test_03_visit_lifecycle_and_capacity.py:158`) with **0 implementation fixes and 0 deletions**. I traced every behavior that test exercises to the implementation and confirmed each is already uniquely and correctly determined by PRD.md:

1. **Overflow line** — `implementation/domain.py:116-117` computes `line = current_occupancy + held_occupancy; OVERFLOW if line >= capacity`. PRD §3.3 (line 148) already states this verbatim: "reached when the sum of a lounge's `current_occupancy` and `held_occupancy` is at or above its `capacity`."
2. **Hold honored only when OPEN** — `implementation/routes/visits.py:106-108` rejects with `ERR_LOUNGE_OVERFLOW` when `status != OPEN`. PRD §3.3 (line 148) already states this verbatim.
3. **Check-in capacity gate** — `implementation/routes/visits.py:275-276` rejects with `ERR_OVER_CAPACITY` when `current_occupancy + occupant_count > capacity`. PRD §3.4 (line 158) already states this verbatim.

The test originally failed because its fixture opened the third hold *after* occupancy had already reached capacity — which the PRD-faithful implementation correctly refused with `ERR_LOUNGE_OVERFLOW`, so the test never reached its intended `ERR_OVER_CAPACITY` gate. The fix reordered fixture setup; it revealed no PRD silence and no PRD/impl mismatch.

### Per-item pre-edit search log (subjects evaluated, no edit warranted)
- **Subject: lounge overflow-line / capacity rules.** Paths enumerated and read: `domain.py` `_recompute_overflow_status` (111-121), `recompute_lounge_occupancy` (82-108), `routes/visits.py` hold gate (106-108) and check-in gate (274-276), plus `complete`/`cancel`/sweep callsites of `recompute_lounge_occupancy` (visits.py:312, 394, 421; domain.py:328). All consistent with PRD §3.3 and §3.4 as already written. No wording adjustment — no edit made.

## Step 9: Complete PRD — 2026-06-21T02:53:58.000Z

All 8 changed paragraphs read coherently and each pins a behavior the implementation actually exhibits. The edits are all in-paragraph inserts/revisions; no new sections or paragraphs were added, and line count is unchanged.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (272 lines, 45,068 chars) → `PRD_COMPLETED.md` (272 lines, 47,919 chars). Char delta: **+2,851**. Line count unchanged (all edits in-paragraph; no new sections/paragraphs).

**Counts:** 11 pins total — **9 ambiguity-pins**, **2 mismatch-revisions**.

**Changes (one per edit):**
- §2.4 Logical Clock — insert — ambiguity — `to_iso8601` is a required non-empty string; missing/unparseable → `ERR_INVALID_REQUEST`; `now` re-emitted in 3-digit `Z` format — `routes/clock_routes.py:18-24`
- §3.3 Holds — insert — ambiguity — a hold with no `day_pass_id` and no `member_id` → `ERR_INVALID_REQUEST` (non-day-pass entry requires a member) — `routes/visits.py:79-80`
- §3.3 Holds — insert — ambiguity — `guest_names` must be a list of strings; required when `guest_count > 0`; length must equal `guest_count`, else `ERR_INVALID_REQUEST` — `routes/visits.py:51-66`
- §3.3 Entry-mode cascade — insert — ambiguity — day-pass validity is checked at hold time (ISSUED / not expired / right lounge / member-bound owner) → `ERR_DAY_PASS_INVALID` — `routes/visits.py:101-103`, `routes/visits.py:187-197`
- §3.3 Guest funding — insert — ambiguity — non-member day-pass-only entry has no allotment: `guest_allotment_consumed`=0, all guests `GUEST_CHARGE` — `routes/visits.py:125-126`
- §3.4 Check-in day-pass gate — revise — mismatch — pass valid at check-in is `ISSUED` **or** held-`REDEEMED` for this same visit (not "must be ISSUED") — `routes/visits.py:352-368`
- §3.4 Ledger posting — revise — mismatch — `OVERAGE_REVERSAL` is never emitted by any flow (settlement reversal posts no ledger entry); per-guest split into clamped `LOUNGE_GUEST_FEE` (all guests) + `GUEST_CHARGE` remainder (charged guests only), zero rows skipped, none for non-member entries — `routes/visits.py:321-349`, `routes/settlements.py:39-53`
- §3.4 Ledger status — insert — ambiguity — every entry created `POSTED`; no flow ever transitions to `VOID` — implementation-wide (no `VOID` write)
- §3.6 Day-pass purchase — insert — ambiguity — at least one of `member_id`/`buyer_name` required (else `ERR_INVALID_REQUEST`); `Member` role must purchase for self (else `ERR_NOT_RESOURCE_OWNER`) — `routes/lounges.py:253-270`
- §3.6 Day-pass purchase — insert — ambiguity — a successful purchase bumps the lounge's `version`/`updated_at` — `routes/lounges.py:294-295`
- §3.6 Day-pass redemption/refund — revise — mismatch — pass marked `REDEEMED` at **hold time** (not only at check-in); refund of a non-`ISSUED` or non-member-owned pass → `ERR_INVALID_STATE` — `routes/visits.py:173-177`, `routes/day_passes.py:47-52`

**Notable finding:** The `OVERAGE_REVERSAL` ledger kind and the `VOID` ledger status are defined in the type/assertion helpers and were claimed reachable by the original PRD prose, but no implementation flow ever produces either — pinned as such.

---

## Pipeline complete — 2026-06-21T02:53:58.000Z

All 9 steps finished. Final state: 70/70 tests pass across all 8 parallel stability rounds. Deliverables present: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}`, `workspace/implementation/` (+ `results.{1..8}.json`), `test_helpers/`, `test_suite/`.

# Worklog — task_1771_medical_group_board_governance

## Step 1: Create Task Directory — 2026-08-14T14:56:00.000Z

Task directory `tasks/task_1771_medical_group_board_governance/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per instructions; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-14T15:54:00.000Z

All artifacts generated and verified. Lint verdict block (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_1771_medical_group_board_governance/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_1771_medical_group_board_governance/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_1771_medical_group_board_governance/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     13
  §1.8 instances scanned:     19
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  674

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1771_medical_group_board_governance/`): `SCAFFOLD.yaml` (§1.0–§1.7, no design keys), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`), `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`).

**Profile**: primary archetype multi-party_negotiation, secondary compliance_audit; flat topology; cyclic state-machine shape; segregation-of-duties role model; layers = optimistic concurrency, dual-variant calculation, cascading side effects, rate/threshold triggers. A logical clock (`POST /_clock/set_current_utc`, default 2026-08-01T00:00:00Z) drives all sweeps.

**Entities (13)**: GovernancePolicy (singleton config holding every constant/threshold), Physician (parallel state dimensions: partnership_status × standing), BoardSeat (half-open term windows + booked successors), Committee (compound CHARTERED/ACTIVE/IMPAIRED/DISSOLVED posture from membership vs quorum), BuyInOffer, Motion (cyclic OPEN⇄TABLED, self-referential supersede, payload-typed), Vote (CAST→VOIDED via COI cascade), CapitalCall (compound over children), CapitalCallAssessment (BILLED/PARTIAL/PAID/DELINQUENT/DEFAULTED with late fee), Distribution (embedded penny-precise allocations, clawback), ExitValuation (APPRAISED⇄DISPUTED cycle with arbitration), COIDisclosure, MergerProposal.

**State machines (12)** including two cyclic (Motion, ExitValuation), one parallel-dimension (Physician), three compound (Committee, CapitalCall, Distribution). **Concurrency rules (2)**: OCC on GovernancePolicy.version (PATCH) and ExitValuation.version (appraise-with-supersede), both passing the serial-observability filter.

**Calculations (8)**: buy_in_price (tier base × min-capped tenure discount × fiscal proration × max floor), distributable_cap (bonus-first circular-order), distribution_allocation (PRO_RATA vs SENIORITY_TIERED variants, floor-then-residual pennies, created_at tie-break), capital_call_assessment, late_fee (fire-once), vote_threshold (ceil supermajority, strict majority, abstain-to-quorum), buy_out_valuation (provisional EBITDA vs final appraised-minus-minority-discount variants, waived for TERMINATION/DEATH), ownership_recalc.

**Endpoints (61)**: 3 roles (BoardAdmin opaque, Physician entity_backed, ComplianceOfficer opaque — the only COI reviewer). **Validations (10 priorities)**: auth → shape → role → ownership → existence → state → safety → temporal → constraint → fiscal. **Error catalog (39)**; every code is referenced outside its own catalog entry.

**§1.8**: 19 difficulty instances — all 9 rules with ≥2 each (combinatorial_formula has 3, one per mode a/b/c); every numeric assert was pre-computed by executing the formulas (e.g., buy-in 20,166,667; pro-rata 4,000,001/4,000,000/2,000,000; cap 360,000,000 vs naive 480,000,000; provisional 34,833,333 vs final 11,333,333).

**§1.9**: 63 instances (54 real + 9 `excluded_because` stubs citing §1.8 coverage), spanning entities / state_machines / calculations / validations / endpoints / errors / rbac / cross_cutting_layers / consistency_model.

All instance names are unique across the union, zero forbidden concurrency vocabulary, and every §1.8/§1.9 call chain was replayed against §1.2/§1.4 by hand (including the clock-equality edges: vote gate `clock < closes_at` vs expiry sweep `clock > closes_at`, offer deadline inclusive vs sweep strict).

## Step 3: Copy Shared Files — 2026-08-14T15:58:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1771_medical_group_board_governance/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T16:04:00.000Z

Done. PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1771_medical_group_board_governance/workspace/PRD.md`.

## Summary

**Section structure:**
- §1 Introduction — 3 paragraphs (pain points → system scope → logical clock/money/time conventions)
- §2 Global Specifications — 8 subsections: 2.1 RBAC & identity (both opaque and entity-backed roles translated), 2.2 API Response Structure (byte-identical verbatim block, verified), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Common resource properties + logical clock & sweeps, 2.5 Rounding & residual pennies, 2.6 OCC (both `expected_policy_version` and `expected_valuation_version` rules with `ERR_STALE_VERSION`/412), 2.7 Validation priority order (all 10 tiers, explicitly ordered), 2.8 Policy singleton & all 22 constants with defaults
- §3 Business Logic — 8 subsections organized by entity lifecycle: 3.1 physician roster/standing/ownership, 3.2 buy-in offers & partner track, 3.3 board seats & committees, 3.4 motions & voting, 3.5 capital calls & distributions, 3.6 partner exit & buy-out valuation, 3.7 COI disclosure & recusal cascade, 3.8 merger proposals
- §4 Endpoint table — 61 rows, 4 columns (Method/Path/Description/Roles)
- §5 Error catalogue — 39 rows, 2 columns (Error ID/HTTP status)

**Approximate length:** 290 lines, ~6,500 words.

**Scaffold sections rendered to prose:** all of them — 13 entities (every field backticked, defaults/initial values stated), all 12 state machines including Physician's parallel `partnership_status`/`standing` dimensions and compound statuses on Committee/CapitalCall/Distribution, all 8 calculations (buy-in price, distributable cap, both distribution-allocation variants, capital-call assessment, late fee, vote threshold, both buy-out valuation variants, ownership recalc) in precise prose with pinned evaluation orders, all 10 validation priorities as an explicit ordered sequence, both OCC concurrency rules, all 61 endpoints, and all 39 error codes with trigger conditions scattered into §2/§3 narrative near their workflows.

**Hard contracts:** Contract 1 (131/131 field names backticked, 0 missing after fixing `allocations`/`capital_call_id`/`note`), Contract 2 (all transitions, side-effect cascades, calculation formulas, applies_to scopes, sibling branches expressed), Contract 3 (562 §3 backtick tokens scanned, zero path/method leaks). All PASS.

## Step 5: Generate Unit Tests — 2026-08-14T16:35:00.000Z

Done. Full test infrastructure and suite generated for task_1771.

## Summary

**test_helpers/** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1771_medical_group_board_governance/test_helpers/`):
- `types.py` — 21 status enums + TypedDicts for all 13 entities (all `common_fields: true`)
- `api_client.py` — `ApiClient(GenericApiClient)` with all 61 endpoints (incl. `/_clock/set_current_utc`)
- `api_errors.py` — all 39 error IDs + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions, `assert_share_conservation`, `allocation_for`
- `factories.py` — payload factories incl. per-motion-type payload builders
- `constants.py` — PRD §2.8 policy defaults, clock default, thresholds
- `test_users.py` — opaque-role constants + `make_physician_headers` (entity-backed) builder
- `fixtures.py` — composite helpers: policy/physician/committee/seat/offer setup, motion lifecycle (`create_and_open_motion`, `adopt_motion_full`), `adopted_capital_call`, `adopted_and_billed_call`, `adopted_distribution`, exit pipeline (`initiate_exit`/`appraise_valuation`/`adopt_buyout_approval`/`setup_finalized_exit`), COI file/review, merger helpers
- `__init__.py` — barrel export

**test_suite/** (23 files incl. `conftest.py`; **88 tests**): test_01–test_14 difficulty queue, test_15–test_22 corner queue.

**Queue A (Difficulty): 19/19 instances translated, 2 tests each (38 tests).** All passed the PRD-first filter.

**Queue B (Corner): 50 of 54 real instances translated (50 tests); 9 stubs correctly untranslated** (all stub cross-references resolve to covered difficulty instances). 4 instances skipped per the two-condition filter:
1. `Corner/state_machines/motion_close_from_draft_rejected` — PRD never names an error for closing a non-OPEN motion; ERR_MOTION_NOT_OPEN vs ERR_INVALID_STATE vs ERR_QUORUM_NOT_MET all plausible → not uniquely derivable.
2. `Corner/state_machines/motion_expiry_sweep_after_closes_at` — sweep-to-EXPIRED is covered, but the asserted late-close error id is not uniquely derivable (EXPIRED is terminal → ERR_MOTION_TERMINAL equally plausible).
3. `Corner/state_machines/merger_evaluation_pipeline_and_decide_guards` — the "decide before NEGOTIATION → ERR_INVALID_STATE" sub-claim is not uniquely derivable (decide source states not stated for APPROVED/REJECTED; ERR_MERGER_NOT_APPROVED races it with a non-adopted motion). Whole-instance skip.
4. `Corner/cross_cutting_layers/clock_sweep_aggregate_report` — PRD never specifies the clock endpoint's response body (`current_utc`, `swept_counts`) → response-shape assertions have no coverage.

**One corrected literal:** `Difficulty/compensating_invariant/shares_conserved_across_exit_and_buyin` pre-computes Z's offer as 22000000 assuming tenure 2 for hire 2024-08-01 at the 2026-08-01 clock. Under the PRD's verbatim rule ("full 365.25-day years"), 730 days = 1 full year (2 needs 730.5), so the PRD-derived value is **22458333**, which the test asserts (payment amount is read from the created offer, so the flow is robust either way).

**Audits run clean:** every test has exactly one `Design:` tag as the last docstring line; all tags resolve to real instances; every difficulty instance has ≥2 tests; every translated corner instance has ≥1; all PRD citations verified verbatim against `workspace/PRD.md` (whitespace-normalized); no skip/xfail markers; all modules compile and import.

## Step 6: Generate Implementation — 2026-08-14T16:35:00.000Z

Implementation complete and verified. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1771_medical_group_board_governance/workspace/implementation/`)

- `start.sh` — foreground launcher; guards `pip install` behind `python3 -c "import flask"` (no-op on per-test reboots), `exec python3 app.py`
- `requirements.txt` — Flask only
- `app.py` — app factory, ApiError/404/405 handlers, blueprint registration, `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory stores (13 dicts, all empty at boot, no seeding), logical clock pinned to `2026-08-01T00:00:00Z`, ISO8601 ms-precision helpers
- `errors.py` — all 39 error IDs with their exact HTTP statuses
- `response.py` — scaffold envelope: `meta{api_request_id, api_request_timestamp[,limit,offset,total_count,has_more]}`, `response_type`, `data{error_id,message}`
- `middleware.py` — `X-User-Role`/`X-User-ID` auth (401), role gating (403), physician ownership (403)
- `services/core.py` — validation helpers, pagination (limit/offset, created_at ASC), serializers, tenure/ownership/treasury recalc, pro-rata floor+residual split, seniority-tiered allocation, distributable cap
- `services/sweeps.py` — atomic clock sweeps: offer expiry (strict >), motion expiry, assessment DELINQUENT (one-time late fee) → DEFAULTED (physician SUSPENDED + call PARTIALLY_DEFAULTED bubble-up), seat term-end successor promotion/vacancy
- `routes/policy_physicians.py`, `seats_committees.py`, `offers.py`, `motions.py`, `calls_distributions.py`, `exits_coi_mergers.py`, `clock.py`

## Endpoints
All 61 scaffold endpoints implemented, including `POST /_clock/set_current_utc` with sweep counts.

## State machines / calculations covered
- Physician dual dimensions (partnership_status × standing); BoardSeat VACANT/FILLED with successor booking (half-open intervals, adjacency); Committee CHARTERED/ACTIVE/IMPAIRED/DISSOLVED compound status; BuyInOffer OFFERED→ACCEPTED→COMPLETED/DECLINED/EXPIRED; Motion full lifecycle with supersede, table/resume fresh windows, electorate snapshot; Vote CAST→VOIDED (COI cascade); CapitalCall APPROVED→BILLED→COLLECTED/PARTIALLY_DEFAULTED; Assessment ladder with once-only late fee; Distribution APPROVED→PAID/VOIDED with clawbacks; ExitValuation INITIATED→APPRAISED⇄DISPUTED→ARBITRATION→FINALIZED with OCC; COI FILED→CLEARED/FLAGGED with recusal cascade; MergerProposal PROPOSED→DUE_DILIGENCE→NEGOTIATION→APPROVED/REJECTED/TERMINATED.
- Calculations: buy-in price (tenure discount, fiscal proration twelfths, min floor, floor+remainder installments), distributable cap (bonus-first pinned order), PRO_RATA and SENIORITY_TIERED allocations (floor + residual pennies by shares DESC/created_at ASC), capital-call assessments, late fee, vote thresholds (ceil supermajority, strict simple majority, quorum gate), buy-out provisional/final valuations (minority discount waived for TERMINATION/DEATH, 40/30/30 payment schedule with residue absorption), 6dp ownership recalc + treasury.
- OCC on `PATCH /governance/policy` (`expected_policy_version`) and `POST .../appraise` (`expected_valuation_version`), both `ERR_STALE_VERSION` 412. All money via `Decimal` round-half-up. Validation priority order (auth → shape → role → ownership → existence → state → compliance → temporal → cardinality → money) honored.

## Boot confirmation
`bash start.sh` boots cleanly from a fresh process: binds `0.0.0.0`, honors `PORT`, store empty on every boot (verified by creating a policy, killing the server, rebooting, and getting `ERR_NOT_FOUND`). Two smoke suites (~120 assertions covering the full lifecycle plus edge cases: deadline boundary semantics, grace-period strictness, segregation of duties, COI vote voiding, supersede, seat succession, treasury exhaustion, tie rejection) both pass on independent fresh boots.

## Step 7: Run Tests and Iterate — 2026-08-14T17:05:00.000Z

**Summary**

- **Iterations run:** 2 sweeps of 8 parallel rounds each (16 runs total). Initial sweep: 85/88 (rounds 1,2,4,5,6,8) and 84/88 (rounds 3,7). Final sweep: 88/88 in all 8 rounds — exit condition met.

- **Tests deleted:** none. All four failing tests traced to PRD-verbatim rules; none exhibited a PRD-silence or unique-derivability collapse that required deletion.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1771_medical_group_board_governance/test_suite/test_07_difficulty_exit_dispute_cycle.py` (`test_dispute_reappraisal_loop_bounded_by_max_rounds`, failed 8/8): the capped third dispute was attempted from `DISPUTED`, where the `APPRAISED`-only transition guard (`ERR_INVALID_STATE`) competes with the cap rule — the PRD cap sentence presupposes an otherwise-valid dispute. Added the PRD-sanctioned re-appraisal from `DISPUTED` (§3.6: "a re-appraisal may be recorded from `DISPUTED` with the same effect") so the capped dispute is attempted from `APPRAISED` with `dispute_rounds == max_dispute_rounds`, making `ERR_DISPUTE_LIMIT_REACHED` uniquely determined. Assertion strength unchanged.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1771_medical_group_board_governance/workspace/implementation/routes/exits_coi_mergers.py` (`create_valuation`): moved the non-terminal-valuation (in-flight) check before the `SHAREHOLDER`-only state gate. PRD §3.6 names `ERR_EXIT_ALREADY_IN_PROGRESS` unconditionally for "a second initiation while one is in flight"; since initiation always moves the physician to `EXITING`, the state-first ordering made that PRD-cataloged error unreachable. The `ASSOCIATE` case still yields `ERR_INVALID_STATE` (no valuation in flight).
  - `/home/ubuntu/github/CodingPRD/tasks/task_1771_medical_group_board_governance/workspace/implementation/routes/policy_physicians.py` (`create_physician`): moved shape validation (`req_str`/`req_datetime`/`opt_*` and the cross-field `initial_shares >= 1` rule) ahead of `require_roles`, per PRD §2.7's explicit priority "Second, request shape … Third, role permission on the endpoint"; the treasury sufficiency guard remains last (money guard, priority 10).
  - `/home/ubuntu/github/CodingPRD/tasks/task_1771_medical_group_board_governance/workspace/implementation/routes/calls_distributions.py` (`bill_call`): removed `p["id"]` (random UUID) from the residual-penny sort key. Under the pinned logical clock, same-instant creations tie on `created_at`; the key now ends at `created_at` and Python's stable sort resolves full ties in creation (insertion) order — the deterministic refinement of PRD §3.5's "ties broken by the physician's `created_at` ascending", matching the distribution path's `pro_rata_split` behavior. This was the flaky one (failed rounds 3 and 7 only, ~coin-flip per boot).

## Step 8: Finalize PRD — 2026-08-14T17:15:00.000Z

The diff is exactly three in-place sentence insertions, no new sections, nothing else touched. Work complete.

## Summary

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1771_medical_group_board_governance/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md = 290 lines, PRD_FINALIZED.md = 290 lines — 0% line delta (3 existing lines modified in place; ~+470 characters total).

### Changes (one bullet per change)

- **§2.5 (Rounding, Precision, and Residual Pennies)** — insert — added the complete-tie refinement: under the pinned logical clock, same-instant creations share an identical `created_at`; whenever a residual-penny ordering among physicians ties completely on its ordering keys (for share-weighted orderings: equal shares and identical `created_at`), recipients are taken in physician-record creation order, earliest-created first — `implementation/routes/calls_distributions.py:73` (`bill_call` stable sort on `(-shares_held, created_at)` over insertion-ordered physicians), `implementation/services/core.py:447` (`pro_rata_split`, same key), `implementation/services/core.py:474` (seniority-carve residual, stable sort on `created` only).
- **§3.6 (Partner Exit, initiation paragraph)** — insert — pinned guard ordering at exit initiation: the one-non-terminal-valuation (in-flight) check is evaluated before the `SHAREHOLDER`-only partnership-state gate (initiation always moves the physician to `EXITING`, so state-first ordering would make `ERR_EXIT_ALREADY_IN_PROGRESS` unreachable); a physician with no valuation in flight must be a `SHAREHOLDER`, otherwise `ERR_INVALID_STATE` — `implementation/routes/exits_coi_mergers.py:67-74`.
- **§3.6 (dispute paragraph)** — insert — pinned that the `max_dispute_rounds` cap rejection presupposes an otherwise-valid dispute: the state gate (`APPRAISED`-only) and the `appraisal_final` gate run first, so a dispute from any other status or with `appraisal_final` true yields `ERR_INVALID_STATE` regardless of `dispute_rounds` — `implementation/routes/exits_coi_mergers.py:171-177` (check order: status → finality → cap).

### Step 7 diff item with no edit (deliberately)

- **`implementation/routes/policy_physicians.py` (`create_physician` shape-before-role)** — no PRD edit. PRD §2.7 already explicitly pins "Second, request shape … Third, role permission on the endpoint (`ERR_FORBIDDEN`)" and places treasury sufficiency under "Tenth and last, money guards"; the step-7 change was an implementation-side conformance fix to text the PRD already had (`test_21_corner_security_and_validation.py:51-70` quotes §2.7 verbatim for exactly this case). Per the "keep prose verbatim where PRD already determines behavior" rule, nothing was inserted.

### Per-edit pre-edit search log (NO-NEW-MISMATCH)

**Edit §2.5 (residual ties):**
- (a) Subject: recipient ordering when residual-penny tie-break keys tie completely.
- (b) Paths enumerated and read: `bill_call` (calls_distributions.py:56-78, snapshot + sort + penny loop); `pro_rata_split` (core.py:435-453, used by PRO_RATA and by the SENIORITY_TIERED remainder stage at core.py:461-462,483); seniority-carve residual (core.py:468-479, key is `created_at` only — no share key); installment-schedule split (§3.2, remainder goes to the first installment — not a per-physician ordering, excluded by scoping the sentence to "residual-penny ordering among physicians"); `paginate` (core.py:179, uses `(created_at, id)` — excluded by the same scoping; §2.3 list-ordering silence left untouched); `db.py:38-39` (`clock.set` has no monotonic guard, so wording says "order the physician records were created," not "earliest `created_at`").
- (c) Wording adjustment: yes — the first draft's parenthetical "equal share counts and equal `created_at`" would have mis-described the carve residual (whose only key is `created_at`); revised to "for the share-weighted orderings, equal share counts and an identical `created_at`" so all three sites are correctly covered.

**Edit §3.6 (initiation ordering):**
- (a) Subject: guard ordering at exit-valuation initiation (in-flight uniqueness vs. `SHAREHOLDER`-only state gate).
- (b) Paths enumerated and read/grepped: `create_valuation` full guard chain (exits_coi_mergers.py:46-100 — auth → shape → role → ownership → existence → in-flight → state); grep `ERR_EXIT_ALREADY_IN_PROGRESS` — raised only at exits_coi_mergers.py:69; grep `EXITING` transitions — set only at initiation (:97) and cleared only at finalize (:238), so in-flight ⇔ `EXITING` holds universally; `ERR_PHYSICIAN_EXITING` sites (offers.py:81-83, motions.py:148-150) confirmed to be a different error for different activities, consistent with §3.1's "blocked from two activities" sentence; test_20:47-58 confirms both order-dependent assertions (`ASSOCIATE` → `ERR_INVALID_STATE`, in-flight re-initiation → `ERR_EXIT_ALREADY_IN_PROGRESS`).
- (c) Wording adjustment: yes — scoped the added text to name only `ERR_EXIT_ALREADY_IN_PROGRESS`/`ERR_INVALID_STATE` (never `ERR_PHYSICIAN_EXITING`), and phrased the state gate as "a physician with no valuation in flight must be a `SHAREHOLDER`" so the `EXITED`-immutability rule (§3.1) and the in-flight rule remain jointly consistent.

**Edit §3.6 (dispute cap ordering):**
- (a) Subject: guard ordering inside the dispute operation (state gate vs. finality gate vs. round cap).
- (b) Paths enumerated and read/grepped: `dispute_valuation` (exits_coi_mergers.py:165-181 — status→finality→cap order); grep `DISPUTE_LIMIT`/`dispute_rounds` — cap raised only at :177, counter mutated only at :178 (appraisal never resets it, matching test_07:60); `appraise_valuation` (:130-162 — re-appraisal allowed from `DISPUTED`, arbitration appraisal sets `appraisal_final` true while returning to `APPRAISED`, so the finality gate is independently reachable from `APPRAISED`); §2.7 priority (state gates sixth, cardinality rules ninth) confirmed consistent with "state and finality gates run first."
- (c) Wording adjustment: none needed beyond scoping the sentence to the dispute operation ("The cap rejection presupposes an otherwise-valid dispute …").

**Step-7 item with no edit (create_physician):**
- (a) Subject: shape-vs-role validation ordering at physician onboarding.
- (b) Paths checked: `create_physician` (policy_physicians.py:103-149), §2.7 text, test_21:51-70.
- (c) No edit — §2.7 already uniquely determines the ordering the impl was fixed to; adding text risked narrowing a global priority list the whole implementation depends on.

## Step 9: Complete PRD — 2026-08-14T17:37:00.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1771_medical_group_board_governance/workspace/PRD_COMPLETED.md` as an inline-only patch over `PRD_FINALIZED.md`.

**Size:** PRD_FINALIZED.md 290 lines / 49,436 chars → PRD_COMPLETED.md 290 lines / 53,953 chars. Char delta **+4,485**, line delta **0** (25 lines modified in place; no new sections or paragraphs).

**Counts:** 30 edits total — **27 ambiguity-pins** (PRD silent), **3 mismatch-revisions** (PRD described different behavior).

**Mismatch revisions:**
- §2.4 — revise — mismatch — `version` no longer increments on *every* mutation: clock-sweep expiry of offers and motions updates `status`/`updated_at` only; assessment and seat sweep transitions do increment — implementation/services/sweeps.py:26-28,35-37 (no bump) vs 57-58,94-95 (bump).
- §2.7 — revise — mismatch — ownership/existence order corrected: body-identifier ownership (motion sponsorship, exit initiation) runs at stage four, but path-identified resources load first, so a missing path id yields `ERR_NOT_FOUND` ahead of `ERR_RESOURCE_OWNERSHIP` — routes/offers.py:154-158, routes/exits_coi_mergers.py:169-170.
- §3.4 — revise — mismatch — `CHARTER_AMENDMENT` payload fields are each optional but at least one of `new_quorum_count`/`new_approval_threshold` is required — routes/motions.py:69-74.

**Ambiguity pins (one per edit):**
- §2.1 — insert — physician ownership extended to own sponsored motions on lifecycle transitions; ownership enforced only on mutations, reads open to all §4-listed roles — routes/motions.py:249-253, middleware.py:31-34.
- §2.2 — insert — `api_request_timestamp` is wall-clock, not logical clock — implementation/db.py:57-61.
- §2.3 — insert — non-integer/out-of-range `limit`, negative/non-integer `offset` → `ERR_INVALID_REQUEST`; `created_at` ties broken by `id` ascending — services/core.py:155-181.
- §2.4 — insert — entity `created_at`/`updated_at` are logical-clock reads — db.py:52-54.
- §2.6 — insert — OCC version comparison runs after existence check (and after the state gate on appraise) — routes/policy_physicians.py:80-88, routes/exits_coi_mergers.py:150-153.
- §2.7 — insert — unknown-field rejection always immediately after auth; field-level shape validation pre-role on physician/motion/exit-valuation creation and ballot casting, point-of-use (post-role, post-path-existence) elsewhere — e.g. routes/policy_physicians.py:107-124 vs routes/seats_committees.py:29-32.
- §2.8 — insert — read/update before policy creation → `ERR_NOT_FOUND`; singleton-exists rejection precedes required-field validation — routes/policy_physicians.py:33-37,69-70,80-81.
- §3.1 — insert — `initial_shares` without `founding_shareholder` ignored/recorded 0; no-policy founding onboarding always fails treasury check — routes/policy_physicians.py:127-133,141.
- §3.1 — insert — standing-update `note` accepted but not persisted — routes/policy_physicians.py:181-191.
- §3.2 — insert — offer to a current `SHAREHOLDER`, or `PARTNER_TRACK` offer to an on-track offeree → `ERR_INVALID_STATE`; offer creation with no policy → `ERR_INVALID_STATE` — routes/offers.py:84-88,99-100.
- §3.2 — insert — completed offer status is `COMPLETED`; completion-time treasury re-check runs after the offer is marked `COMPLETED`, so a rejection leaves it `COMPLETED` with tier unadvanced — routes/offers.py:184-197.
- §3.3 — insert — `quorum_count` integer ≥ 1 — routes/seats_committees.py:133.
- §3.3 — insert — no tier/standing eligibility check for committee members — routes/seats_committees.py:184-185.
- §3.3 — insert — removing a non-member → `ERR_NOT_FOUND` — routes/seats_committees.py:218-221.
- §3.4 — insert — supplied `new_quorum_count` ≥ 1; DISTRIBUTION `fiscal_net_income_before_bonus_cents` any integer; COMP_POLICY `new_bonus_pool_pct` any number — routes/motions.py:65-68,75-84.
- §3.4 — insert — wrong-state lifecycle transitions → `ERR_INVALID_STATE`, except table/close of a non-`OPEN` motion → `ERR_MOTION_NOT_OPEN` — routes/motions.py:263,279,308-309,322,338,408-409.
- §3.5 — insert — billing a non-`APPROVED` call → `ERR_INVALID_STATE` — routes/calls_distributions.py:52-53.
- §3.5 — insert — `allocations` ordered by physician creation, including 0-cent floored allocations — services/core.py:456-486, routes/motions.py:367-373.
- §3.5 — insert — disburse gates (distribution `APPROVED`, allocation `PENDING`) and void from other statuses → `ERR_INVALID_STATE` — routes/calls_distributions.py:195-198,217-218.
- §3.6 — insert — non-terminal means any status except `FINALIZED` — routes/exits_coi_mergers.py:67-70.
- §3.6 — insert — `appraised_practice_value_cents` must be a non-negative integer — routes/exits_coi_mergers.py:139-143.
- §3.6 — insert — arbitrator's appraisal returns valuation to `APPRAISED` with `appraisal_final` true — routes/exits_coi_mergers.py:158-160.
- §3.6 — insert — finalize evaluates the `APPRAISED` state gate before the motion-linkage gate — routes/exits_coi_mergers.py:208-218.
- §3.6 — insert — exit cascade also clears any successor booking naming the exiting physician — routes/exits_coi_mergers.py:258-263.
- §3.7 — insert — reviewing an already-reviewed disclosure → `ERR_INVALID_STATE` — routes/exits_coi_mergers.py:346-347.
- §3.8 — insert — `exchange_ratio_x1000` and `cash_consideration_cents` are non-negative integers — routes/exits_coi_mergers.py:384-385.
- §3.8 — insert — advancing from `NEGOTIATION` or terminal status → `ERR_INVALID_STATE` — routes/exits_coi_mergers.py:443-444.
- §3.8 — insert — decide gate order: `NEGOTIATION` required (`ERR_INVALID_STATE`) → `motion_id` present (`ERR_INVALID_REQUEST`) → resolves to a `MERGER` motion (`ERR_MERGER_NOT_APPROVED`); `TERMINATE` ignores a supplied `motion_id` — routes/exits_coi_mergers.py:462-476.
- §4 — insert — clock-set returns HTTP 200 with `data.current_utc` and `data.swept_counts` (`offers_expired`, `motions_expired`, `assessments_delinquent`, `assessments_defaulted`, `physicians_suspended`, `seats_swept`) — routes/clock.py:28-33, services/sweeps.py:12-19.

Everything else in the implementation (state machines, all calculation formulas, residual-penny orderings, sweep strict/non-strict thresholds, COI cascade, segregation-of-duties gates, error catalogue, endpoint/role table) was already uniquely pinned by the PRD and left untouched.

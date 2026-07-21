# Worklog — task_1055_rebate_incentive_program

## Step 1: Create task directory — 2026-07-18T00:00:00.000Z

Created `tasks/task_1055_rebate_incentive_program/` and `workspace/` (folder pre-assigned by launcher; no index scan performed).

## Step 2: Generate scaffold (Expert) — 2026-07-18T00:00:00.000Z

All three files are written and validated.

## Scaffold generated — `tasks/task_1055_rebate_incentive_program/`

**Lint verdict (verbatim):**
```
Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     10
  §1.8 instances scanned:     18
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  743

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### Counts
| Table | Count |
|---|---|
| Entities | 10 — Program, Offer, Claimant, Claim, Receipt, Payout, VirtualCard, EscheatRecord, BudgetEntry, FraudCase |
| Endpoints | 51 (`/api` prefix + one `/_clock/set_current_utc`) |
| Errors | 41 |
| Roles | 6 — ProgramAdmin, ClaimsProcessor, FinanceOfficer, FraudAnalyst (opaque); Dealer, Consumer (`entity_backed:Claimant`) |
| State machines | 8 blocks (Claim declares 2 parallel dimensions) |
| Calculations | 6 |
| Validations | 27 priority rows |
| Concurrency rules | 2 OCC (Claim.version, Program.version) |
| §1.8 instances | 18 (9 rules × 2) |
| §1.9 instances | 57 across 9 sections (50 with recipes, 7 `excluded_because` stubs) |

### Design
- **Profile**: compliance_audit × pricing_engine; flat topology; parallel state shape; segregation_of_duties; immediate consistency. Layers: OCC, dual-variant calc, cascading side effects, rate/threshold triggers.
- **State machines**: Program (ACTIVE ⇄ BUDGET_LOCKED), Offer (PUBLISHED ⇄ SUSPENDED), Claim `adjudication_status` (with DENIED→UNDER_REVIEW appeal cycle) **×** `payment_status` (independent axis), Payout (RELEASED ⇄ REISSUE_PENDING branch to CLEARED/VOIDED/ESCHEATED), VirtualCard, FraudCase (UNDER_INVESTIGATION ⇄ PENDING_INFO), Claimant.
- **Calculations**: `claim_rebate_amount` (tiered, dual-variant provisional/final, round-per-line-then-sum pinned), `claimant_fraud_score` (weighted, dual-variant heuristic/investigated), `program_budget_position` (pinned eval order; the claim under adjudication is excluded from its own reserve), `payout_net_amount` (circular method↔fee dependency pinned to gross), `escheat_transfer_amount` (two dormancy semantics), `program_report_snapshot`.
- **Difficulty rules**: cascades of depth 4 (approve→COMMIT→lock→suspend offers→void DRAFT claims) and depth 3 (substantiate→block→revoke→RELEASE ledger+void payout); priority conflicts state-vs-fiscal and temporal-vs-referential; boundaries at utilization exactly 1.0000 and dormancy exactly 180 days; overlaps with half-open offer windows (adjacency allowed) vs closed ±365-day serial dedupe; invariants conserving money (`available_cents`) and claim-slot counts.

### Constants (all declared with concrete values in a top-level `constants:` block plus per-calculation `constants:`)
`DEFAULT_CLOCK_UTC=2026-07-01T00:00:00Z`, `CLAIM_WINDOW_DAYS=90`, `OFFER_GRACE_DAYS=15`, `DEDUPE_WINDOW_DAYS=365`, `MAX_CLAIMS_PER_CLAIMANT_PER_OFFER=3`, `RECEIPT_MAX_LINES=20`, `APPEAL_WINDOW_DAYS=30`, `MAX_APPEALS_PER_CLAIM=2`, dealer tiers (9/49 units → 0.05/0.08/0.12), `CONSUMER_REBATE_PCT=0.10`, `CONSUMER_FLAT_BONUS_CENTS=500`, `RESERVE_FACTOR=0.15`, `BUDGET_WARN_PCT=0.8`, `BUDGET_HARD_PCT=1.0`, `CHECK_FEE_CENTS=150`, `CARD_FEE_CENTS=50`, `CARD_METHOD_MIN_CENTS=2500`, `PAYOUT_MIN_CENTS=100`, `ESCHEAT_DORMANCY_DAYS=180`, `CARD_DORMANCY_DAYS=90`, `VIRTUAL_CARD_VALID_DAYS=365`, fraud weights (`W_DENIED=15`, `W_DUPLICATE=25`, `W_VELOCITY=10`, `W_HIGH_VALUE=20`), `VELOCITY_FREE_CLAIMS=2`, `VELOCITY_WINDOW_DAYS=30`, `HIGH_VALUE_CLAIM_CENTS=50000`, `FRAUD_SCORE_THRESHOLD=70`, `SUBSTANTIATION_MULTIPLIER=1.5`, `CLEARANCE_CREDIT=30`.

### Notes for downstream
- Every formula-derived assertion literal was computed in Python before being written (e.g. provisional 10193 vs final 4798; per-line rounding 159 vs the wrong 158; net 2450 at the 2500 card threshold; utilization exactly 1.0000 at budget 200000).
- `Program.paid_cents` is defined as a recomputed aggregate (filtered on the claim's payment_status) rather than a running balance, so voiding a released payout reverses it without a compensating ledger row.
- `VirtualCard.expires_at` is computed from `VIRTUAL_CARD_VALID_DAYS` but there is no `EXPIRED` state — cards leave the lifecycle via EXHAUSTED or ESCHEATED only. This is intentional (enum closure holds), but the PRD generator should not invent an expiry transition.
- The claim-cap rule was tightened during authoring to exclude DRAFT claims from the count, otherwise stacking DRAFTs would have blocked the first submit.

Post-check by orchestrator: all three YAML files `yaml.safe_load` cleanly (2335 / 1648 / 3183 lines).

## Step 3: Copy shared files — 2026-07-18T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-18T00:00:00.000Z

PRD generated at `workspace/PRD.md`.

**Stats:** 387 lines; 51 endpoints in the §4 table (exact match to scaffold); 41 error rows in §5; 288 distinct backticked tokens.

**Sections:** §1 Introduction (3 paras) · §2 Global Specifications (2.1 RBAC, 2.2 Response Structure verbatim, 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning, 2.5 The Logical Clock, 2.6 Money/Counts/Rounding, 2.7 OCC on Programs and Claims, 2.8 Order of Evaluation for Rejections, 2.9 Cascade Discipline) · §3 Business Logic (3.1 Program + budget ledger, 3.2 Offer catalogue, 3.3 Claimants/intake/receipts, 3.4 Submission gate, 3.5 Rebate pricing, 3.6 Adjudication/denial/appeal, 3.7 Fraud scoring + case management, 3.8 Disbursement/checks/cards/SoD, 3.9 Dormancy/escheat/reporting) · §4 Endpoint Definitions · §5 Error Code Catalogue.

**Hard Contracts**

```
Field coverage check:
- entities[].fields: 80 required, 80 present, 0 missing
- endpoints[].input (request body + query + path params): 46 required, 46 present, 0 missing
- nested line keys + report output keys (sku, quantity, unit_price_cents, claims_*, dealer/consumer_claim_count,
  approved_rebate_cents, escheated_cents, offer_breakdown, current_utc): 14 required, 14 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 27 checked, 27 expressed as an explicit ordered list in §2.8, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint framed by capability + expected_claim_version /
  expected_program_version + ERR_STALE_CLAIM_VERSION / ERR_STALE_PROGRAM_VERSION + 412), 0 missing
- state_machines[].transitions: 53 checked across 8 machines (Program 5, Offer 6, Claimant 2, Claim/adjudication 13,
  Claim/payment 5, Payout 8, VirtualCard 8, FraudCase 6), 53 fully expressed with preconditions + side effects, 0 missing
- calculations[]: 6 checked, 6 fully expressed in prose with pinned evaluation order and all constants, 0 missing
- validations[] conditions: 27 checked, 27 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 51 checked, 51 expressed, 0 missing
- entities[].fields[] structured content: 80 checked, defaults/initial values/computed definitions reconstructible, 0 missing
- sibling-branch symmetry: 9 groups checked (provisional vs final rebate variant; SUBSTANTIATED vs CLEARED fraud branch;
  CHECK vs VIRTUAL_CARD fee/dormancy; lock vs unlock; suspend vs close; withdraw from DRAFT vs SUBMITTED;
  void from PENDING vs RELEASED; reissue from RELEASED vs VOIDED; spend partial vs exact), 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 643
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Scaffold gaps resolved:** none of substance — the scaffold declared every constant with a concrete value, so no pre-patching was needed. Two judgement calls: (1) the scaffold gives validation priorities but not a total order for the `error_id`-alternation entries at priorities 10/11/20, so §2.8 renders those as one ordered step each with the alternatives enumerated; (2) `BUDGET_WARN_PCT` (0.8000) is declared but gates nothing in any rule, so §3.1 states it explicitly as a reported-but-non-gating warning level rather than inventing behaviour for it. Also carried through the deliberate escheat asymmetry (record captures net/remaining balance, ledger reversal returns gross) and the pinned per-line rounding order, both flagged in prose as order-sensitive.

Post-check by orchestrator: `workspace/PRD.md` = 386 lines, 51 endpoint rows (matches scaffold's 51).

## Step 5: Generate unit tests — 2026-07-18T00:00:00.000Z

Test infrastructure and suite are complete and audited.

## Files written

**`test_helpers/`** (Stage 1) — `types.py`, `api_client.py` (49 endpoint methods incl. `/_clock/set_current_utc`), `api_errors.py` (41 error IDs registered with the framework status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque staff constants + `make_dealer_headers`/`make_consumer_headers` per-instance builders for the `entity_backed:Claimant` roles), `fixtures.py` (5-tier composite setups: catalogue → draft/submitted/under-review/approved claim → pending/released payout → issued/activated card → fraud-case and budget-adjustment helpers), `__init__.py`.

**`test_suite/`** (Stage 2) — `conftest.py` plus 11 domain-named files: programs & budget ledger, offer catalogue, claim intake & receipts, submission gate, rebate pricing, adjudication & budget gates, fraud cases, disbursement, virtual cards, escheat & reporting, access control.

## Counts

- **86 tests**, every one carrying exactly one `Design:` tag resolving to a real instance.
- **Queue A (Difficulty):** 18/18 instances translated, ≥2 tests each (36 tests).
- **Queue B (Corner):** 50/50 non-stub instances translated, ≥1 test each (50 tests). The 7 `excluded_because:` stubs in the `errors` section were not translated — all 7 cross-references resolve to real difficulty instances that own the assertion.
- **0 instances skipped**; no `skip`/`skipif`/`xfail` anywhere.
- All 86 docstring citations verified verbatim against a whitespace-normalised `PRD.md`; `pyflakes` and `compileall` clean.

## Two places where I asserted the PRD-derived outcome instead of the design YAML's literal

Both design instances stated an expected value the PRD contradicts; PRD-first governs, and in each case PRD uniquely derives a different answer:

1. `priority_pair_validation_conflict / state_precondition_beats_budget_check_on_second_approve` — the YAML expects `ERR_CLAIM_NOT_REVIEWABLE` on re-approving an `APPROVED` claim. PRD §3.6 scopes that error to "A review attempt…" and separately says "any adjudication action attempted against a claim already resting in `APPROVED`, `REVOKED`, `WITHDRAWN` or `VOIDED` is refused with `ERR_CLAIM_ALREADY_TERMINAL`". Tests assert `ERR_CLAIM_ALREADY_TERMINAL` (still 409, still proving state-before-fiscal precedence, which is what the instance exists to test).
2. `boundary_precision_check / budget_gate_accepts_final_equal_to_available_and_locks_at_exactly_one` — the YAML expects `available_cents == 50000` after the failed approve. That is the *in-approval* figure; PRD §3.1 says the subject-claim exclusion applies only "inside an approval request… outside an approval there is no such exclusion", so a subsequent `GET` must report 35000 (150000 − 100000 committed − 15000 reserve). Test asserts 35000. Everything else in that instance (rejection, +50000 top-up, final == available == 100000, `utilization_pct` 1.0, `BUDGET_LOCKED`) matches the YAML exactly.

Worth flagging to whoever runs Step 7: if the implementation follows the design YAML rather than the PRD on these two points, the failures are PRD-conformance signals, not test bugs.

## Step 6: Generate implementation — 2026-07-18T00:00:00.000Z

Implementation complete and verified.

## Files written

`workspace/implementation/` — 18 Python modules + `start.sh` + `requirements.txt`:
- **Core**: `app.py` (entry, blueprints, error handlers, per-request RLock for atomic cascades), `db.py` (in-memory stores, logical clock, constants, lookups), `errors.py` (42-code catalog), `response.py` (envelope + pagination), `middleware.py` (auth/RBAC/shape validation), `serializers.py`
- **routes/**: `programs.py`, `offers.py`, `claimants.py`, `claims.py`, `payouts.py`, `cards.py`, `ledger.py`, `fraud_cases.py`
- **services/**: `budget.py` (ledger + position + lock/unlock cascade), `rebate.py` (dual-variant pricing, payout settlement), `fraud.py` (scoring + substantiation fan-out), `escheat.py` (dormancy sweep)

## Self-check results

- `ast.parse` clean on all 18 `.py` files; `app.py` present
- **Route count: 51 — matches SCAFFOLD §1.5's 51 endpoints exactly**
- Booted via `bash start.sh` on free ports and exercised end-to-end. Verified: full claim lifecycle (create→receipt→submit→validate→review→approve→payout→release→escheat sweep), tiered dealer pricing (20u @ 8% = 16000), per-line round-half-up + consumer 500¢ bonus (333+333+500 = 1166), method-from-gross selection, SoD 403, OCC (5 parallel budget adjustments → one 200, four 412), half-open offer-window overlap (touching windows allowed), receipt line ceiling ordering (empty→`ERR_VALIDATION`, 21→`ERR_RECEIPT_LIMIT_EXCEEDED`), budget lock cascade (util 1.0 → `BUDGET_LOCKED` → offer `SUSPENDED` → draft claim `VOIDED`), fraud substantiation → `BLOCKED` → reinstate, escheat net/gross asymmetry (record 15850 net vs ledger reversal 16000 gross). Store starts empty; no seeding.

## PRD ambiguities resolved by choice

1. **Submit/receipt-attach from a terminal state** — §3.4 says "a submission attempt from any other adjudication state reports `ERR_CLAIM_NOT_DRAFT`", but §3.6 says any adjudication action on a terminal claim reports `ERR_CLAIM_ALREADY_TERMINAL`. Followed the more specific §3.4 for submit and receipt-attach; used `ERR_CLAIM_ALREADY_TERMINAL` for withdraw/review/approve/deny/appeal.
2. **Program close blocked by in-flight claims** — no error declared; used `ERR_PROGRAM_NOT_ACTIVE` (409).
3. **Claimant reinstate preconditions** — no claimant state error declared; used `ERR_INVALID_TRANSITION` (409) for both non-`BLOCKED` and still-open-case.
4. **Appeal of a `FRAUD_SUBSTANTIATED` denial** — no error declared; used `ERR_CLAIM_NOT_REVIEWABLE` (409), checked in the step-9 state group.
5. **Submit with zero receipts** — no error declared; used `ERR_VALIDATION` (400), positioned after the offer-grace check per §3.4's sentence order.
6. **`claims_submitted` in the report** — §3.9 gives two conflicting rules (count of non-null `submitted_at` vs "DRAFT/WITHDRAWN/VOIDED excluded from every count"). Applied the exclusion, so a withdrawn-after-submit claim is not counted.
7. **Payout create on a non-`APPROVED` claim** — used `ERR_CLAIM_NOT_REVIEWABLE`; `payment_status != NONE` maps to `ERR_PAYOUT_ALREADY_EXISTS` at step 10.
8. **Pagination out-of-range** — `limit`/`offset` are clamped to the declared bounds rather than rejected; non-integer values yield `ERR_VALIDATION`.
9. **`created_at`/`updated_at` source** — taken from the logical clock (per §2.5's "all temporal reasoning"), with an internal insertion sequence breaking ties so `created_at ASC` ordering stays stable.
10. **Card creation on re-release** — a `VIRTUAL_CARD` payout released again from `REISSUE_PENDING` reuses the existing card rather than minting a second one (scaffold declares card creation only on the `PENDING → RELEASED` edge).
11. **`memo` on reinstate** — treated as optional to avoid spurious 400s; PRD says the act "carries" one but declares no requirement.

Post-check by orchestrator: 51 registered routes (== scaffold 51), 86 test functions across 11 test_suite files, all test_helpers present.

## Step 7: Run tests and iterate — 2026-07-18T00:00:00.000Z

Clean 8-round pass on the first sweep — no iteration needed.

## Summary

**Iterations run:** 1 (single sweep; 8/8 rounds green on first attempt).

**Results:** All 8 rounds `passed=86, total=86`, with `failed=0, errors=0, skipped=0` in every round. No flakiness signal — the union of failing tests across all 8 rounds is empty. Wave 1 rounds ran ~50s, wave 2 ~80s (normal concurrency skew, no boot timeouts or missing results files).

**Tests deleted:** none — no test failed in any round, so no STEP-1 silence/derivability adjudication was triggered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** none.

**Fixes applied to `implementation/`:** none.

**Upstream conflict points — both confirmed covered and passing (no adjudication needed):**
1. Re-approving an APPROVED claim asserting `ERR_CLAIM_ALREADY_TERMINAL` (PRD §3.6) is exercised in `test_suite/test_06_adjudication_and_budget_gates.py:276` (and the parallel submission-gate case at `test_suite/test_04_submission_gate.py:101`). The implementation already follows PRD §3.6 over the design YAML.
2. Budget availability after a failed approve asserting `available_cents == 35000` on a subsequent GET is exercised at `test_suite/test_06_adjudication_and_budget_gates.py:201` — the implementation correctly scopes the subject-claim exclusion to inside an approval request per PRD §3.1.

The 11 implementation-generator ambiguity resolutions did not surface as failures, meaning none of them collided with a test assertion. Test artifact spans 11 suite files covering programs/budget ledger, offer catalogue, claim intake, submission gate, pricing, adjudication, fraud, disbursement, virtual cards, escheat/reporting, and access control.

Post-check by orchestrator: re-read all 8 `results.N.json` directly — every round `passed=86 total=86 failed=0 errors=0`.

## Step 8: Finalize PRD — SKIPPED — 2026-07-18T00:00:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits at the sites Step 7 exercised. No `PRD_FINALIZED.md` produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-07-18T00:00:00.000Z

`PRD_COMPLETED.md` is written.

## Summary

**Source vs output:** `PRD.md` 386 lines / 62,092 chars → `PRD_COMPLETED.md` 386 lines / 73,496 chars (**+11,327 chars**). All edits are in-paragraph inserts/revisions; no new sections, no line-count change.

**Counts:** 34 changes — **32 ambiguity-pins**, **2 mismatch-revisions**.

Of the 11 supplied leads, all 11 verified as genuinely under-determined and were pinned. The full scan added 23 more.

### Changes

- §2.3 — insert — ambiguity — limit/offset clamped (not rejected), non-integer → `ERR_VALIDATION`, empty → default; insertion-sequence tiebreak on all `created_at` ordering — `response.py:52-70`, `db.py:168`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` read from the logical clock; `api_request_timestamp` is the sole wall-clock stamp — `db.py:151-165`, `response.py:22`
- §2.8 step 4 — insert — ambiguity — unknown `BudgetEntry`/`EscheatRecord` id → `ERR_PROGRAM_NOT_FOUND` 404 — `db.py:226-237`
- §2.8 step 9 — insert — ambiguity — submit/receipt-attach → `ERR_CLAIM_NOT_DRAFT`; withdraw/review/approve/deny/appeal → terminal-vs-not split — `claims.py:25-28`
- §3.1 — insert — ambiguity — `fiscal_year` integer, `escheat_jurisdiction` non-empty; activation from non-`DRAFT` → `ERR_PROGRAM_NOT_ACTIVE`; activation recompute is not a lock trigger — `programs.py:22-69`
- §3.1 — insert — ambiguity — `ACCRUAL`/`PAYMENT`/bare-state-change/read recomputes fire neither lock nor unlock — `budget.py:10-12, 93-97`
- §3.1 — insert — ambiguity — `delta_cents` required signed int, `memo` optional/nullable, ledger row carries `abs(delta)` and null `claim_id` — `programs.py:100-113`
- §3.1 — insert — ambiguity — stale version outranks the adjustment floor; filters match exact strings, empty filter not applied; non-integer `fiscal_year` filter → `ERR_VALIDATION` — `programs.py:51-57, 104-109`
- §3.1 — insert — ambiguity — close from wrong status **and** in-flight-claim block both → `ERR_PROGRAM_NOT_ACTIVE` 409, status first — `programs.py:77-84`
- §3.2 — insert — ambiguity — overlap checked pre-persist on create; self excluded on publish — `offers.py:25-41, 78`
- §3.2 — insert — ambiguity — publish state check precedes program check precedes overlap check — `offers.py:104-109`
- §3.2 — insert — ambiguity — suspend/close from undeclared states → `ERR_OFFER_NOT_PUBLISHED`; offer close ignores program status — `offers.py:119-130`
- §3.3 — insert — ambiguity — `mailing_state` may be empty string; other claimant fields non-empty — `claimants.py:21-24`
- §3.3 — insert — ambiguity — offer-published check precedes channel check at claim open — `claims.py:51-54`
- §3.3 — insert — ambiguity — receipt validate has no state precondition and is re-runnable; `validated` filter parses `true`/`1`/`yes` — `claims.py:159-181`
- §3.4 — insert — ambiguity — zero receipts → `ERR_VALIDATION` 400, reached only after the three window checks pass vacuously — `claims.py:208-223`
- §3.4 — insert — ambiguity — heuristic evaluated after `provisional_rebate_cents`/`submitted_at` are stamped — `claims.py:246-253`
- §3.4 — insert — ambiguity — withdraw from `UNDER_REVIEW`/`HELD`/`DENIED` → `ERR_CLAIM_NOT_REVIEWABLE` — `claims.py:302-303`
- §3.6 — insert — ambiguity — terminal/non-terminal error split extended to approve/deny/appeal; `HELD` is not terminal — `claims.py:25-28`
- §3.6 — revise — mismatch — budget gate is **strictly** exceeding (`final == available` approves); five preconditions in impl order — `claims.py:343-364`
- §3.6 — insert — ambiguity — `reason_code` required non-empty and outranks the state precondition — `claims.py:386-389`
- §3.6 — insert — ambiguity — `appeal_note` required; `FRAUD_SUBSTANTIATED` → `ERR_CLAIM_NOT_REVIEWABLE` 409, checked before claimant standing — `claims.py:417-428`
- §3.7 — insert — ambiguity — no-claim heuristic contributes 0 to the high-value term — `fraud.py:25-27`
- §3.7 — insert — ambiguity — denied/duplicate terms read stored counters, recency counted live — `fraud.py:11-22`
- §3.7 — insert — ambiguity — analyst-opened case field defaults; opening changes no claimant/claim state; cases may be concurrent — `fraud_cases.py:42-43`
- §3.7 — insert — ambiguity — `to_status` excludes `OPEN` → `ERR_VALIDATION` not `ERR_INVALID_TRANSITION`; `note` not persisted — `fraud_cases.py:13, 69-70`
- §3.7 — insert — ambiguity — cascade recompute uses a `RELEASE` trigger (may unlock); substantiating against an already-`BLOCKED` claimant stamps scores only — `fraud.py:67, 118-123`
- §3.7 — insert — ambiguity — reinstate `memo` optional/unpersisted; both preconditions → `ERR_INVALID_TRANSITION` 409, status first — `claimants.py:63-68`
- §3.8 — insert — ambiguity — non-`APPROVED` → `ERR_CLAIM_NOT_REVIEWABLE`; `payment_status != NONE` → `ERR_PAYOUT_ALREADY_EXISTS` — `payouts.py:32-40`
- §3.8 — insert — ambiguity — supplied `method` enum-constrained and honoured regardless of type/gross — `payouts.py:25`
- §3.8 — revise — mismatch — release check order is standing → SoD → min-payout (PRD had min-payout before SoD); `check_number` optional and omission preserves the existing value; SoD skipped when `approved_by_user_id` is null — `payouts.py:92-118`
- §3.8 — insert — ambiguity — re-release reuses the existing virtual card and appends a further `PAYMENT` row — `payouts.py:126-129`
- §3.8 — insert — ambiguity — void/reissue/clear state-error selection; reissue clears `check_number` on both branches; `VOIDED`-branch non-approved claim → `ERR_CLAIM_NOT_REVIEWABLE` — `payouts.py:150-206`
- §3.8 — insert — ambiguity — spend body shape-checked ahead of the card-state check — `cards.py:64-71`
- §3.9 — insert — ambiguity — sweep returns a non-paginated 200 array envelope, available in any program state; card-less `VIRTUAL_CARD` payout skipped; recompute runs once, only when records were created — `programs.py:180-185`, `escheat.py:33-36, 78-79`
- §3.9 — revise — mismatch — `claims_submitted` is filtered by adjudication state *first*; the PRD's claim that withdrawn claims "fall out naturally because `submitted_at` is null" was false — `programs.py:124-128`

One note worth flagging: the two mismatches were real PRD errors, not just silences — the release-check ordering and the `claims_submitted` derivation. The latter is the more consequential, since the PRD offered an explicit (and incorrect) justification for why withdrawn claims are excluded; a reader implementing to the original prose would have counted them.

Post-check by orchestrator: `workspace/PRD_COMPLETED.md` exists, 386 lines / 73,496 chars vs `PRD.md` 386 / 62,092.

---

**Pipeline complete.** Steps 1–7 + 9 executed; Step 8 skipped by its declared skip condition.

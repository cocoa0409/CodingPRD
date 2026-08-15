# Worklog — task_1359_bank_capital_planning_regulatory_reporting

## Step 1: Create Task Directory — 2026-08-13T00:30:00.000Z

Task directory `tasks/task_1359_bank_capital_planning_regulatory_reporting/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline invoker. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched. Difficulty target: harder than expert level.

## Step 2: Generate Scaffold — 2026-08-13T01:04:21.904Z

Clean lint. Final summary:

## Summary

**Files generated** under `/home/ubuntu/github/CodingPRD/tasks/task_1359_bank_capital_planning_regulatory_reporting/`:
- `SCAFFOLD.yaml` (§1.0–§1.7; no scaffold_difficulty_design or scaffold_corner_design top-level keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level `scaffold_difficulty_design:`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single top-level `scaffold_corner_design:`)

**Counts:**
- Entities: **12** (Bank, ReportingPeriod, CapitalInstrument, RiskExposure, CapitalPlan, StressScenario, CallReport, EditException, CapitalDistributionRequest, SubordinatedDebtIssuance, PCAThresholdEvent, ICAAPDocument)
- State machines: **9** (ReportingPeriod, CallReport, EditException, CapitalPlan, StressScenario, CapitalDistributionRequest, SubordinatedDebtIssuance, CapitalInstrument, ICAAPDocument)
- Calculations: **11** (rwa_standardized, rwa_advanced, rwa_selected, cet1_tier1_total_capital, t2_amortization_haircut, capital_ratios_bps, pca_bucket_classification, stress_capital_buffer, stress_loss_projection, maximum_distributable_amount, t2_capacity_headroom, edit_check_rwa_mismatch, filing_deadline_computation — 13 actually)
- Endpoints: **89** (66 nested + 23 flat reverse-reachability GETs; includes `/_clock/set_current_utc` and `/_clock/current_utc` test-driving endpoints with mandatory default time 2026-08-01T00:00:00Z)
- Errors: **31** domain-specific codes
- §1.8 instances: **18** (exactly 2 per rule × 9 rules)
- §1.9 instances: **42** across all 9 claim-extraction-guide sections

**Lint verdict:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (89 endpoints, 12 entities, 18 §1.8 instances, 42 §1.9 instances, 640 calls scanned, 0 violations)

**Notable design decisions (maximum depth tier):**
1. **Dual-variant RWA (Collins floor)** — `rwa_standardized` vs `rwa_advanced` produce different numbers on identical inputs; `rwa_selected` uses `max()` for ADVANCED banks (floor binds), creating precision-sensitive divergence.
2. **Combinatorial capital stack** — `cet1_tier1_total_capital` has nested `min(AT1_raw, 1.5% RWA)` and `min(T2_raw, 2% RWA, 100% CET1)`, exercising nested-min + tier-cap interdependence.
3. **Per-line floor then sum** — RWA aggregation explicitly pins per-line floor before summation; 3 exposures of EAD=3 cents at 90% risk weight yield 6 cents, not 8 (test pinned numerically).
4. **PCA threshold boundary precision** — `>=` vs `>`: 650 bps qualifies WELL_CAPITALIZED, 649 falls to ADEQUATELY_CAPITALIZED; floor arithmetic checked with exact literals.
5. **Amendment-driven cascade (depth 3+)** — call-report accept on an amendment → ReportingPeriod RE_ACCEPTED → PCA bucket recompute → CapitalPlan baseline refresh + SUPERSEDED-if-floor-breached → CapitalDistributionRequest WITHDRAWN + capacity release.
6. **Sub-debt settle cascade (depth 2)** — settle → CapitalInstrument created → T2 outstanding recompute → headroom refreshed on every open SubordinatedDebtIssuance.
7. **Stress capital buffer with forward-looking 9-quarter projection** — pre-tax loss × quarter_weights (summing to 10000) × (1−tax) ÷ growing RWA, with min() across quarters; verified literal 798 bps.
8. **OCC on Bank.version** for 4 endpoints (distribution approve, sub-debt approve, plan submit_regulator, icaap file) — every Bank-mutating cascade bumps version, so any stale expected version yields deterministic 412.
9. **Segregation of duties** — call-report submitter ≠ preparer; plan board_approver ≠ submit_board analyst; ICAAP attest ≠ prepared_by. PCA / capacity / state / temporal / SoD priority conflicts pinned at distinct priorities.
10. **Temporal interval semantics** — distribution payment window `[payment_date, payment_date+10d]` half-open + chronological period-close ordering across siblings.
11. **api_prefix set to `""`** — required so the lint's `derive_entity_collection_segments` correctly identifies flat single-resource GETs (`/reporting-periods/{id}` etc.) and pairs them with the filtered-list GETs to satisfy all 22 FK reverse-reachability rules.
12. **Logical clock endpoint with fixed default** — `POST /_clock/set_current_utc` with documented default `2026-08-01T00:00:00Z`; drives period OPEN→FILING_DUE, plan APPROVED→EFFECTIVE, distribution EXPIRED, sub-debt MATURED transitions deterministically.

## Step 3: Copy Shared Files — 2026-08-13T01:04:54.988Z

Copied `./INSTRUCTION.md` → `tasks/task_1359_bank_capital_planning_regulatory_reporting/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T01:26:40.834Z

The PRD is complete and verified. Final summary:

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_1359_bank_capital_planning_regulatory_reporting/workspace/PRD.md` — **347 lines**.

## Section list
- **1. Introduction** (2 paragraphs: reporting spine, then discretionary capital management + logical clock)
- **2. Global Specifications** — 2.1 Roles/RBAC, 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, diff-verified), 2.3 Pagination & List Filtering, 2.4 Common Resource Properties (incl. PCAThresholdEvent's `common_fields: false` exception), 2.5 Logical Clock & Time-Driven Transitions, 2.6 Monetary Units/Basis Points/Rounding, 2.7 PCA Buckets & Supervisory Posture (all 16 thresholds, inclusive boundaries, strictest-wins), 2.8 Bank Versioning & OCC, 2.9 Validation Order & Nested Resource Resolution (all 19 priorities narrated in order)
- **3. Business Logic** — 8 subsections: 3.1 Bank Onboarding & Instrument Inventory, 3.2 Periods/Risk Capture/Filing Calendar, 3.3 Call Report Prepare→Edits→Submit→Accept cascade, 3.4 Amendments & Close, 3.5 Stress Scenarios & Capital Plan, 3.6 Distributions & MDBA, 3.7 Sub-Debt & T2 Headroom, 3.8 Threshold Events & ICAAP
- **4. Endpoint Definitions** — 88 rows, 4 columns only (scaffold's 89 entries minus the deliberately merged duplicate `GET /banks` row, which carries both `charter_id` and `pca_bucket_as_of_period_id` filters)
- **5. Error Code Catalogue** — all 32 errors, 2 columns only

## Hard Contract Reports
```
Field coverage check:
- entities[].fields + endpoint inputs + query/path params: 104 required, 104 present, 0 missing
- path params: 12 required, 12 present (in §4 paths), 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ordering: 19 checked, 19 expressed as ordered §2.9 prose, 0 missing
- concurrency_rules[] OCC: 4 checked, 4 expressed (action + expected_bank_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 45 checked, 45 fully expressed (from/to, preconditions+error ids, side effects), 0 missing
- calculations[]: 13 checked, 13 expressed in precise prose (constants spot-verified), 0 missing
- validations[] conditions: 19 matchable to error ids in §2/§3; all 32 catalog errors appear in §2/§3
- endpoints[].side_effects / applies_to scopes: all expressed (accept 8-item cascade, amendment cascade, objection cascade, settle→instrument creation, expiry/withdrawal releases)
- fields[] structured content: defaults, null-until semantics, enum sets all reconstructible
- sibling-branch symmetry: resolve/explain, approve/object, close edges, call/redeem, supersession edges, 10 loss-rate classes, 4 PCA metrics — equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 519
- tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path tokens: 0
Status: PASS
```

## Zero-Silence-Rule judgments made
1. **Explain-note tension**: state machine requires a non-empty `resolution_note` on every explain; validation 12 requires it only for non-INFORMATIONAL. Rendered both faithfully: resolve requires the note for `FATAL`/`QUALITY` only; explain always requires it.
2. **FATAL-explain error code**: the endpoint side effect names `ERR_INVALID_STATE_TRANSITION` while validation 12 bundles edit rules under `ERR_EDIT_NOTE_REQUIRED` — PRD assigns the transition rejection to `ERR_INVALID_STATE_TRANSITION` and note failures to `ERR_EDIT_NOTE_REQUIRED`.
3. **Dual SCB formulas**: the calculation's final-SCB formula (max of 450+250 and the baseline-to-stressed drop) and the transition side effect (max(450, stressed_min) − 450) differ; both were transcribed in their own contexts without picking a winner, as was the `stressed_capital_buffer_bps` null-until-first-EFFECTIVE field note vs. set-at-approval side effect.
4. **Capacity error duality**: validation 10's generic `ERR_CAPACITY_EXCEEDED` coexists with the workflow-specific codes (`ERR_DISTRIBUTION_EXCEEDS_MDBA`, `ERR_T2_CAP_EXCEEDED`, `ERR_PLAN_DISTRIBUTION_EXCEEDS_CAPACITY`); §2.9 names the generic code at priority ten and §3 names the specific codes per workflow.
5. **EAD sign**: field description says non-negative; the validation rejects EAD ≤ 0 — PRD states "positive `exposure_at_default_cents`" with the rejection rule attached.
6. **Unnamed-error preconditions** (sub-debt settle before `target_settlement_date`, monotonic clock): stated as plain rules without inventing error IDs.
7. **Duplicate `GET /banks` scaffold entries** merged into one §4 row covering both filter sets.
8. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-08-13T02:23:25.933Z

Generation complete. Summary:

## Test counts
- **Queue A (Difficulty, §1.8): 41 tests across all 18 instances** — every instance has ≥2 tests. Zero instances skipped.
- **Queue B (Corner, §1.9): 50 tests across all 42 instances** — every non-stub instance has ≥1 test (no `excluded_because` stubs exist in this corner design). Zero instances skipped.
- Total: 91 tests, all collected by pytest cleanly.

## Skip report
No instances were skipped. However, five recipes required **PRD-corrected setups** (same asserted rule and expected outcome, reachable route), because the YAML's literal `setup_api_calls` contradict the PRD:

| Instance | Recipe problem | Correction (same asserted rule) |
|---|---|---|
| `pca_threshold_exact_boundary_ge_vs_gt` | CET1-only stack at 650bps is actually SIGNIFICANT (the TOTAL metric's 1000bps WELL floor binds) — PRD §2.7 strictest-metric rule | Added AT1 (at 1.5% cap) + T2 (at 2% cap) so Tier1=800, Total=1000, Leverage=800 are all WELL and CET1 is the binding metric at exactly 650 vs 649 → WELL vs ADEQUATE as the instance asserts |
| `stress_capital_buffer_mode_a_nested_min_max` | Scenario activated after report acceptance sees an empty inventory (PRD §3.5 counts only OPEN/FILING_DUE periods) → loss would be 0, not 2.09e9 | Activate the scenario while the period is still open, then accept the report → pinned 2_090_000_000 loss and `stressed_min_cet1_bps_9q == 798` |
| All distribution-approve flows (`compensating_invariant`, `distribution_window_*`, `distribution_terminal_state_lockdown`, `error_distribution_not_yet_payable`, `list_endpoints_support_filter_and_pagination`) | `mdba_cents` is structurally 0 until a plan is EFFECTIVE, and the stress buffer recorded at approval exactly consumes stressed headroom; also payment 2027-03-15 is outside a 2026Q2 period's quarter (PRD §3.6) | Added `setup_distributable_bank` fixture: post-approval CET1 top-up + amendment cycle refreshes the plan's stressed minimum upward (PRD §3.4), then the clock crosses plan-year-01-01 (PRD §2.5) opening a positive pool; distributions use a Q1-2027 payment period |
| `amendment_cascade_depth_3` | Exposures cannot be recorded on an AMENDMENT_OPEN period (PRD §3.2), so the RWA-doubling amendment route is unreachable | Same depth-3 cascade rule reached via a later quarter's original accept: accept → PCA bucket drop → mdba → 0 → APPROVED_NOT_EXECUTED distribution EXPIRED (PRD §3.3 verbatim) |
| `single_inflight_capital_plan_invariant` | Plan creation itself is blocked while another plan is in flight (PRD §3.5) — the second plan can't exist to be board-submitted | Assert creation-time rejection with ERR_INVARIANT_VIOLATION (the PRD's own wording covers both) |

Also uniformly guarded: every submit path advances the logical clock past `period_end_date` first (the clock never moves backward from its 2026-08-01 default), so the unambiguous FILING_DUE → SUBMITTED transition is exercised.

## Files
**test_helpers/** (9): `__init__.py`, `types.py` (11 TypedDicts; PCAThresholdEvent correctly omits `updated_at`/`version`), `api_client.py` (80 endpoint methods incl. flat reverse-reachability GETs), `api_errors.py` (32 error ids, registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (all roles opaque per PRD §2.1), `fixtures.py` (`setup_accepted_report`, plan lifecycle chain to EFFECTIVE, `setup_distributable_bank`, `setup_approved_distribution`, `setup_priced_sub_debt`, `advance_clock_past`, `bump_bank_version`).

**test_suite/** (12): `conftest.py` + `test_01_bank_onboarding.py`, `test_02_rwa_calculation_variants.py`, `test_03_reporting_period_workflows.py`, `test_04_pca_buckets.py`, `test_05_stress_scenarios_and_plans.py`, `test_06_distributions.py`, `test_07_sub_debt.py`, `test_08_amendment_cascade.py`, `test_09_rbac_and_occ.py`, `test_10_icaap.py`, `test_11_input_validation.py`.

## Stage 2 self-audit result
- **Tag coverage**: every one of the 91 tests carries exactly one `Design:` line; every tag resolves to a real instance name in the source YAML; every queue-A instance has ≥2 tests; every queue-B instance has ≥1 test. **PASS.**
- **PRD citation check**: every docstring's quoted rule text survives a normalized literal grep of `workspace/PRD.md` (0 failures); every asserted `error_id` appears in PRD §2/§3 prose, not just the §5 table. **PASS.**
- No `skip`/`skipif`/`xfail` markers; no scaffold references in generated code; priority-order assertions (`ERR_PCA_BLOCKS_DISTRIBUTION` over capacity, state over temporal) rely only on PRD §2.9's explicit fixed-order sentence; the one genuinely ambiguous error choice (submit while EDITS_OUTSTANDING) asserts only the shared 409 outcome.

One caveat to flag: I did not run the suite against a live server (implementation was being generated concurrently per the task constraint), so the tests are compile- and collection-verified but not execution-verified.

## Step 6: Generate Implementation — 2026-08-13T02:23:25.933Z

## Summary

Complete Python + Flask implementation generated in `/home/ubuntu/github/CodingPRD/tasks/task_1359_bank_capital_planning_regulatory_reporting/workspace/implementation/`.

### File list
- `start.sh` — guarded launcher (`exec python3 app.py`, `$PORT` default 10000, binds 0.0.0.0, installs deps only if `flask`/`waitress` import fails)
- `requirements.txt`, `app.py` (entry + error handlers), `db.py` (in-memory stores + logical clock, starts at `2026-08-01T00:00:00Z`), `errors.py` (full 32-error catalog), `response.py` (exact envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`, pagination in `meta`), `middleware.py` (X-User-ID/X-User-Role auth + RBAC for all 5 roles), `util.py` (time/body/enum/pagination/OCC helpers)
- `services/core.py` (all calculations + cascades + serializers), `services/clockwork.py` (time-driven transitions)
- `routes/`: clock, banks, periods, instruments, exposures, call_reports (incl. edit-exceptions), scenarios, plans, distributions, subdebt, pca_events, icaap, flat (22 reverse-reachability GETs)

### Endpoints: 88 total
All from SCAFFOLD §1.5 — 66 nested/operational + 22 flat top-level GETs.

### State machines implemented (8)
ReportingPeriod (OPEN→FILING_DUE→SUBMITTED→ACCEPTED→AMENDMENT_OPEN→RE_SUBMITTED→RE_ACCEPTED→CLOSED), CallReport (DRAFT→PREPARED→{VALIDATED|EDITS_OUTSTANDING}→SUBMITTED→ACCEPTED/AMENDED_SUPERSEDED), EditException (OPEN→RESOLVED/EXPLAINED with FATAL-explain ban), CapitalPlan (DRAFT→…→APPROVED/OBJECTED→EFFECTIVE/SUPERSEDED incl. clock activation + supersession cascades), StressScenario (DRAFT→ACTIVE→RETIRED, limit 2), CapitalDistributionRequest (PROPOSED→APPROVED_NOT_EXECUTED→EXECUTED/REJECTED/WITHDRAWN/EXPIRED with 10-day window), SubordinatedDebtIssuance (PROPOSED→APPROVED→PRICED→SETTLED/WITHDRAWN), CapitalInstrument (OUTSTANDING→CALLED/MATURED/REDEEMED), ICAAPDocument (DRAFT→REVIEW→ATTESTED→FILED/SUPERSEDED).

### Calculations implemented (all 11 from §1.3)
Standardized/advanced RWA (per-line floor, 1.06 multiplier, Collins floor), CET1/T1/T2 stack with AT1 1.5% and T2 2%-of-RWA/100%-of-CET1 caps, T2 amortization haircut (365.25-day bucketing, 0/20/40/60/80/100), floored bps ratios (null on zero denominator), PCA bucket classification (inclusive >= thresholds, worst-of-4), stress loss projection (per-class rates, grade multipliers, exact integer math via ×1000 numerators), 9-quarter stressed/base CET1 projections (fixed weights summing to 10000, 21% tax offset, 50bps/qtr RWA growth), SCB (floor 250, `max(450, stressed_min)−450` recorded), MDBA waterfall (PCA capacity vs stress capacity, pending subtraction, zero in undercapitalized buckets), T2 headroom, edit checks (EDIT_FLOOR_VIOLATION fires genuinely for ADVANCED banks), filing deadlines (35/40 days at 17:00:00Z).

Also implemented: logical clock with monotonic guard + all time-triggered transitions (FILING_DUE, late-filing/UNDER_LETTER escalation, plan EFFECTIVE activation, distribution expiry, sub-debt maturity), PCA threshold events (immutable, no `version`/`updated_at`), segregation-of-duties on submit/board_approve/attest, OCC `expected_bank_version` on the 4 designated writes (presence → 400 envelope-level; mismatch → 412 at priority 19), amendment cascade (baseline refresh, floor-driven plan supersession, distribution withdrawal), full 19-level validation ordering.

### Boot verification
Verified by actual launches on scratch ports 18754–18761: `start.sh` boots cleanly, store is empty on fresh boot (`GET /banks` → `total_count: 0`), and a reboot produces a fresh empty store. Two smoke suites passed: 38/38 main-workflow checks (full bank→period→exposure→scenario→report→accept→plan→OCC→approve→amendment→EFFECTIVE→MDBA hand-calc match→distribution execute→auto-expire→ICAAP file) and 41/41 edge-case checks (edit exceptions, Collins floor, PCA downgrade events with `breached=true`, close ordering, T2 caps, OCC 400/412, RBAC, pagination, unknown roles). Three initial smoke failures were traced to my own test expectations (T2 haircut at 4.83y = 20%, Collins-floor ratio 94bps, and priority-10 capacity masking priority-19 OCC) — the implementation was spec-correct in each case.

### Notable spec-fidelity decisions
- `prepared_by_user_id` stored (and serialized) on CapitalPlan/CallReport since SoD rules reference it despite absence from the entity tables.
- Distribution approve accepts plan in {APPROVED, EFFECTIVE} per PRD's "must have reached APPROVED" (scaffold's `== APPROVED` would make MDBA unusable).
- Distribution proposals remain gated to {DRAFT…APPROVED} exactly as specified (EFFECTIVE excluded).
- MDBA execute path debits `mdba_cents` directly (capacity consumed) per PRD 3.6 rather than recomputing.
- Clock-regression rejected with ERR_TEMPORAL_VIOLATION (409); `submitted_at`/`accepted_at` use the logical clock, `created_at`/`updated_at` use wall-clock with 3-fractional-digit format per PRD 2.4.


## Step 7: Test-Fix Iteration Loop — 2026-08-13T02:50:00Z

### Iteration 1 sweep (8 parallel rounds)
All 8 rounds identical: 70/91 passed, 21 failed — fully deterministic, no flakiness. Union of failures diagnosed per the STEP 0-3 protocol:

**Failure clusters and verdicts:**
1. **`validate_success` defaults to HTTP 200 but PRD §4 mandates 201 for creations** (11 tests: test_06 `_push_bucket_adverse` ×2, test_09 `test_board_approver_cannot_prepare_call_report`, test_10 `_create_icaap` ×5, test_11 two cross-bank + `test_error_no_exposures_on_prepare`) — TEST BUG (test_suite assertion mis-translates PRD §4). Fixed by passing `expected_status=201` at the 6 call sites (more faithful, not weaker).
2. **Distribution fixtures proposed against an EFFECTIVE plan** (8 tests: test_06 ×7, test_08 ×1) — TEST BUG in `test_helpers/fixtures.py`: PRD §3.6 gates proposals to plans in DRAFT/BOARD_REVIEW/SUBMITTED/SUPERVISORY_REVIEW/APPROVED; `setup_approved_distribution` and three test bodies proposed after the plan-year clock crossing (plan EFFECTIVE). Fixed: `pre_cross_hook` now receives `(bank_id, plan, pay_period)`; all proposals moved inside the pre-cross window while the plan is APPROVED. Implementation's ERR_INVALID_STATE_TRANSITION rejection is PRD-correct and was kept.
3. **`test_occ_stale_version_on_distribution_approve` got ERR_DISTRIBUTION_EXCEEDS_MDBA instead of ERR_STALE_VERSION** — TEST BUG: §2.9 orders capacity checks tenth and OCC nineteenth (last), so a stale version only surfaces when capacity passes. Setup used a non-EFFECTIVE plan (pool = 0). Fixed: setup now uses `setup_distributable_bank` with a pre-cross proposal so every earlier-priority check passes and priority-19 OCC is isolated.
4. **`test_amendment_locked_when_later_period_closed` deleted** — PRD §3.4 names ERR_AMENDMENT_LOCKED, but §2.9's explicit fixed order (state check fifth, amendment lock thirteenth, "earlier failures mask later ones") plus §3.4's chronological close rule (closing the later period requires the earlier CLOSED) make the asserted branch unreachable: the target period is necessarily CLOSED, so a faithful implementation returns ERR_INVALID_STATE_TRANSITION. ERROR-PRECEDENCE collapse; the one_of relaxation is not permitted because §2.9 explicitly determines the outcome. (Design tag: Corner/validations/amendment_locked_when_later_period_closed.)

**No implementation changes were needed** — every failure traced to the test artifact.

### Iteration 2 sweep
In progress: mid-run checks show zero FAILED/ERROR lines through 67%. (First attempt of this sweep lost its results files when runner processes were killed under host load from a concurrent task's sweep; junit XMLs confirm one fully clean 90/90 round and only "API server could not be restarted" infrastructure errors elsewhere.)

### Iteration 2 sweep — completed (8/8 rounds reported)
2 rounds fully clean (90/90); 6 rounds had 1–4 "API server could not be restarted" setup errors and one mid-test ConnectionReset — all random per round, zero assertion failures. Diagnosis: the per-boot `python3 -c "import flask, waitress"` dependency probe in start.sh pays a full interpreter startup on every per-test-server restart; under host load (multiple foreign 8-round sweeps cycling, load avg 15–22) boots sporadically exceeded the plugin's 15s restart-poll window. task_1352's marker-file pattern (`.deps_installed`) was observed running 8×107/107 clean on the same host at the same time.

**Fix (implementation, environment-only):** `workspace/implementation/start.sh` now caches dependency presence with a `.deps_installed` marker file instead of the per-boot Python import probe (no entity data persisted; the store remains in-memory per process — per-test-server isolation semantics unchanged).

### Iteration 3 sweep — FINAL: ALL 8 ROUNDS CLEAN
```
round 1: 90 / 90 errors: 0
round 2: 90 / 90 errors: 0
round 3: 90 / 90 errors: 0
round 4: 90 / 90 errors: 0
round 5: 90 / 90 errors: 0
round 6: 90 / 90 errors: 0
round 7: 90 / 90 errors: 0
round 8: 90 / 90 errors: 0
```
(under the same foreign load: task_1345/1355/1358 sweeps running concurrently, load avg ~17)

## Final tally
- Iterations run: 3 sweeps (2 diagnostic + 1 confirming).
- Tests deleted (1): `TestAmendmentLock::test_amendment_locked_when_later_period_closed` — ERROR-PRECEDENCE collapse / unreachable rule: PRD §3.4 names ERR_AMENDMENT_LOCKED, but §2.9's explicit order (state fifth, amendment lock thirteenth) plus §3.4's chronological-close rule make the asserted branch unreachable (a later CLOSED period implies the target is CLOSED → ERR_INVALID_STATE_TRANSITION must fire). one_of relaxation not permitted because §2.9 explicitly determines the outcome. (Design tag: Corner/validations/amendment_locked_when_later_period_closed.)
- test_helpers fixes: `fixtures.py` — `pre_cross_hook` now invoked as `(bank_id, plan, pay_period)` so distributions can be proposed while the plan is APPROVED (PRD §3.6 proposal state gate); `setup_approved_distribution` proposes inside the pre-cross hook and approves after the plan turns EFFECTIVE.
- test_suite fixes: 6 call sites asserting PRD §4's 201-on-create (`test_06` `_push_bucket_adverse`; `test_09` board-approver RBAC setup; `test_10` `_create_icaap`; `test_11` ×3); 3 test_06 tests + test_08 adverse-cascade test moved distribution proposals into the pre-cross hook; `test_09` `test_occ_stale_version_on_distribution_approve` setup rebuilt on `setup_distributable_bank` so priority-19 OCC is isolated per §2.9's fixed order (capacity tenth would otherwise mask it).
- implementation fixes: `start.sh` dependency-install marker (boot-latency hardening only; no behavioral change).

## Step 8: Finalize PRD — 2026-08-13T03:03:39.829Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1359_bank_capital_planning_regulatory_reporting/workspace/PRD_FINALIZED.md` written — exactly two inline revisions, no new sections.

## Line counts
- PRD.md: 346 lines; PRD_FINALIZED.md: 346 lines; 0% line-count delta (2 of 346 lines revised in place, ~0.6% of lines touched).

## Changes (one bullet per edit)
- **§3.6** — revise — distribution-approval plan-state gate: "The attached plan must have reached `APPROVED`" now explicitly notes that a plan since activated to `EFFECTIVE` has passed through `APPROVED` and likewise qualifies — `implementation/routes/distributions.py:131-135` (impl comment quotes this exact PRD phrase and accepts `("APPROVED", "EFFECTIVE")`); traced to Step 7 item 2 (`setup_approved_distribution` approves after the plan turns EFFECTIVE).
- **§3.4** — revise — amendment-lock precedence: appended a sentence stating that under §2.9's fixed order the state gate is evaluated before the amendment lock, and since periods close only chronologically, a period with a later-dated `CLOSED` period is itself `CLOSED`, so the observed rejection is `ERR_INVALID_STATE_TRANSITION`, not `ERR_AMENDMENT_LOCKED` — `implementation/routes/call_reports.py:269-278`, `implementation/routes/periods.py:66-75`; traced to Step 7 item 4 (deletion of `test_amendment_locked_when_later_period_closed`).

## Step 7 items requiring no edit
- Item 1 (201-on-create): PRD §4 already mandates 201; verified all ten create endpoints return 201 (`banks.py:42`, `periods.py:41`, `instruments.py:56`, `exposures.py:74`, `call_reports.py:78`, `scenarios.py:53`, `plans.py:80`, `distributions.py:94`, `subdebt.py:53`, `icaap.py:59`). Pure test bug.
- Item 2's proposal-gate half: PRD §3.6 already lists the five proposal-accepting states verbatim; `PLAN_STATES_ALLOWING_PROPOSALS` at `distributions.py:33` matches exactly.
- Item 3 (OCC ordering): PRD §2.9 already fixes capacity tenth / OCC nineteenth; impl `distributions.py:142-147` follows.
- start.sh `.deps_installed` marker: environment-only boot hardening, no API behavior.

## Per-edit pre-edit search log
**Edit A (§3.6 approval gate)**
- (a) Subject: which plan states permit approving an attached distribution request.
- (b) Enumerated: `grep -rn "APPROVED"` and `grep -rn "EFFECTIVE"` across `routes/`+`services/`; read `routes/distributions.py` in full (approve site at :133; execute/reject/withdraw perform no plan-state check); `routes/icaap.py:88` (submit_review accepts APPROVED-or-EFFECTIVE — but PRD §3.8 already says that verbatim, untouched); `services/core.py:517` (mdba stress capacity reads EFFECTIVE plans — unrelated to approval gating); `services/clockwork.py:51-107` (APPROVED→EFFECTIVE activation); `routes/plans.py` supersession paths. Confirmed the only approval-time plan-state gate is `distributions.py:133`, and that the *proposal* sentence (§3.6, five states, no EFFECTIVE) matches `PLAN_STATES_ALLOWING_PROPOSALS` and was deliberately not widened.
- (c) Wording scoped to the approval sentence only, phrased as "passed through APPROVED and likewise qualifies" (mirroring the impl comment) so the proposal gate and ICAAP gates remain described exactly as before.

**Edit B (§3.4 amendment lock)**
- (a) Subject: which error fires when open_amendment is requested on a period having a later-dated CLOSED period.
- (b) Enumerated: `grep -rn "ERR_AMENDMENT_LOCKED"` — sole raise site `call_reports.py:277`, reached only after the state check at :269-271 (period and report both ACCEPTED → else `ERR_INVALID_STATE_TRANSITION`); read `call_reports.py` in full; `periods.py:66-75` close endpoint enforces chronological close (`ERR_TEMPORAL_VIOLATION` on out-of-order), which makes a later-CLOSED/earlier-ACCEPTED combination unattainable; `errors.py:41,75` (catalog entry, 409). No other path raises or references the lock.
- (c) Wording states the observed rejection (`ERR_INVALID_STATE_TRANSITION` from the state check) without asserting the lock check is absent from code — impl keeps it as unreachable code, and an implementer may keep or omit it with identical observable behavior. No claim made about the impl's additional report-ACCEPTED sub-condition (beyond Step 7's trace), keeping the sentence under-determined where the PRD already was.

## Step 9: PRD Completeness Scan — 2026-08-13T03:21:32.302Z

All edits are complete and verified: 346 lines in both files, identical section structure, 29 paragraph-lines revised in place, +6,005 characters.

## Summary

**Source:** `PRD_FINALIZED.md` → `PRD_COMPLETED.md` (both at `/home/ubuntu/github/CodingPRD/tasks/task_1359_bank_capital_planning_regulatory_reporting/workspace/`)
- Line counts: 346 → 346 (no sections added or removed; all changes are inline paragraph inserts/revisions)
- Char delta: +6,005 (63,292 → 69,297 bytes)

**Counts:** 31 ambiguity-pins, 6 mismatch-revisions, spread across 29 edited paragraphs.

**Mismatch revisions (PRD described different behavior than impl):**
- §2.3 — revise — mismatch — full per-resource filter sets (incl. `bank_id`) live only on the flat top-level lists; nested/bank-scoped lists carry subsets (`obligor_grade`, `supersedes_call_report_id`, `baseline_period_id`, `stress_scenario_id`, `capital_instrument_id`, `call_report_id`, `governing_capital_plan_id` are flat-list-only; flat edit-exceptions has no `bank_id`) — implementation/routes/flat.py:43-193, routes/exposures.py:100-110
- §2.4 — revise — mismatch — `version` does not increment on a bare `UNDER_LETTER` supervisory escalation (only `updated_at` moves), qualifying "increments on every mutation" — implementation/services/clockwork.py:47-49, routes/call_reports.py:213-215
- §3.2 — revise — mismatch — the enforced `risk_weight_bps` band is non-negativity only; no per-class bands exist — implementation/routes/exposures.py:56-58
- §3.4 — revise — mismatch — amendment-cascade supersession withdraws only attached requests in `PROPOSED`/`APPROVED_NOT_EXECUTED`; terminal requests untouched — implementation/services/core.py:594-611
- §3.5 — revise — mismatch — `stressed_capital_buffer_bps` is recorded at regulator approval, so it remains null only until the bank's first plan is *approved*, not `EFFECTIVE` — implementation/routes/plans.py:187
- §3.5 — revise — mismatch — supersession withdraws only active (`PROPOSED`/`APPROVED_NOT_EXECUTED`) distribution requests, not "every" attached request — implementation/services/core.py:594-603

**Ambiguity pins (PRD silent; pinned to impl):**
- §2.1 — insert — a role header outside the five recognized roles yields `ERR_FORBIDDEN_FOR_ROLE` (403), not the header error — middleware.py:48-60
- §2.3 — insert — `limit`/`offset` out-of-range values are clamped ([1,100] / ≥0); non-integers → `ERR_INVALID_REQUEST`; sort ties break by insertion order; filters use string equality, booleans match `true`/`false` case-insensitively, null fields never match — util.py:212-266
- §2.4 — insert — `version` starts at 1; `created_at`/`updated_at` are wall-clock write timestamps (logical clock governs `submitted_at`/`accepted_at` only) — db.py:75-96
- §2.5 — insert — clock set: missing/unparseable `to_iso8601` → `ERR_INVALID_REQUEST` (400), earlier instant → `ERR_TEMPORAL_VIOLATION` (409); both clock endpoints return a `current_utc` object — routes/clock.py:19-39
- §2.7 — insert — a null ratio classifies as `CRITICALLY_UNDERCAPITALIZED`; `UNDER_LETTER` escalation applies only from `NORMAL` — services/core.py:316-318, clockwork.py:47
- §2.8 — revise — missing/non-integer `expected_bank_version` → `ERR_INVALID_REQUEST` (400); version fields on other endpoints are ignored — util.py:189-197
- §2.9 — insert — undefined extra body fields are ignored — util.py:73-94
- §3.1 — revise — non-positive `outstanding_amount_cents`, negative `contractual_rate_bps`, missing sub-debt `maturity_date` → `ERR_INVALID_REQUEST` (400); creation-time haircut measured against the current logical date — routes/instruments.py:32-53
- §3.2 — revise — `OPEN`→`FILING_DUE` fires at 00:00:00 UTC on the day after `period_end_date`; body `reporting_period_id` is optional and, when supplied, must resolve to the path period (else `ERR_CROSS_BANK_REFERENCE`) — routes/periods.py:36, clockwork.py:32, exposures.py:41-48
- §3.3 — insert — draft report creation is ungated by period status and always sequences/supersedes from the newest existing report — routes/call_reports.py:27-78
- §3.3 — revise — submission requires period `OPEN`/`FILING_DUE`/`AMENDMENT_OPEN`; submission from `OPEN` also moves the period to `SUBMITTED` — call_reports.py:191-222
- §3.3 — insert — acceptance-cascade expiry compares `capacity_reserved_cents` against gross capacity (smaller of the two capacities, before subtracting pending) — core.py:577-591
- §3.4 — insert — the amendment cascade's applicable floors: stressed figure vs the §3.5 regulator floor (max(700, baseline-to-stressed drop)), base-case figure vs 450 bps — core.py:667-673
- §3.5 — insert — baseline snapshot fields stay null when the baseline period has no accepted report — core.py:471-487
- §3.5 — revise — base-case formula pinned (no losses, no RWA growth; quarter q = (baseline CET1 − q × full `proposed_distributions_cents`) × 10000 / baseline RWA, floored); the full proposed-distribution total is treated as paid every quarter; both projections null when baseline RWA is zero/unset — core.py:419-451
- §3.5 — insert — `submit_regulator` rejects an out-of-state attached distribution with `ERR_INVALID_STATE_TRANSITION`; an `APPROVED` plan whose plan year has begun activates to `EFFECTIVE` immediately at approval — plans.py:160-164, clockwork.py:100-109
- §3.6 — revise — PCA capacity is zero with no accepted report; null ratios excluded from the minimum (all null → zero); stress capacity uses the most recently activated `EFFECTIVE` plan and the same latest-accepted RWA — core.py:494-530
- §3.6 — revise — the payment window is the calendar quarter implied by `period_year`/`period_quarter`; non-positive `distribution_amount_cents` → `ERR_INVALID_REQUEST`; an execute after window close moves the request to `EXPIRED` (reservation released) and is then rejected with `ERR_TEMPORAL_VIOLATION` — distributions.py:36-43, 55-56, 173-180
- §3.7 — insert — non-positive `proposed_amount_cents`/`proposed_rate_bps` → `ERR_INVALID_REQUEST`; early settlement → `ERR_TEMPORAL_VIOLATION`; Feb 29 settlement matures Feb 28 in non-leap target years — subdebt.py:33-38, 123-125, util.py:61-66
- §3.8 — insert — PCA event `bucket_before` is the bank's previous overall bucket, `bucket_after` the metric's own classification — core.py:618-640
- §3.8 — insert — ICAAP `sections` entries are validated only for a string `section_code`; malformed shapes → `ERR_INVALID_REQUEST` — icaap.py:35-43
- §5 — insert — framework-level outcomes: unmatched route → `ERR_NOT_FOUND` (404), wrong method → `ERR_METHOD_NOT_ALLOWED` (405), unexpected failure → `ERR_INTERNAL` (500) — app.py:49-59

No behavior was invented; every pin was traced to the cited implementation line. Tests were used only as a cross-reference (constants confirmed against test_helpers/constants.py).

## Pipeline Complete — 2026-08-13T03:21:32.302Z

Final verification: 8/8 result files each report 90/90 passed, 0 failed, 0 errors (`per-test-server` isolation). All deliverables present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/ (9 files), test_suite/ (conftest + 11 test files, 90 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}, workspace/implementation/ (Flask app + start.sh + results.{1..8}.json).

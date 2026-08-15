# Task 1911 — Hedge Fund Investor Onboarding & Subscription — Worklog

## Step 2: Generate Scaffold — 2026-08-15T00:27:00.000Z

# Summary

Scaffold for task 1911 (Hedge Fund Investor Onboarding & Subscription) generated at expert+ difficulty and lint-clean.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/SCAFFOLD_CORNER_DESIGN.yaml`

## Section counts
- **Entities**: 14 (Fund, ShareClass, NavPeriod, Series, Investor, KycCase, AccreditationAttestation, Subscription, SideLetter, MfnClause, CapitalAccount, SeriesLot, RedemptionRequest, InvestorStatement)
- **State machines**: 7 (Subscription 11 transitions, KycCase 8, AccreditationAttestation 3, RedemptionRequest 6, SideLetter 4, NavPeriod 2, Series 2)
- **Calculations**: 6 (series_equalization_factor [dual-variant provisional/final], redemption_gate_proration, lockup_expiry_date, mfn_clause_effective_fee, late_funding_fee_accrual, notice_days_validation)
- **Validations**: 22 ordered priority rules
- **Endpoints**: 88 (including flat single-resource + filtered-list GETs to satisfy FK reverse-reachability)
- **Errors**: 23 (incl. ERR_STALE_VERSION 412 for OCC)
- **Roles**: 5 (FundAdmin, ComplianceOfficer, TransferAgent, PortfolioManager, Investor — with segregation_of_duties role model)
- **Concurrency rules (OCC)**: 3 (subscription-accept-stale-fund, nav-finalize-stale-fund, side-letter-execute-stale-subscription)
- **§1.8 difficulty instances**: 18 across all 9 rule_ids (2 per rule, differentiated per §0.5)
- **§1.9 corner instances**: 34 total across 8 sections (32 active with full test recipes, 2 excluded_because stubs)

## Lint verdict
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notable hardness drivers: dual-variant equalization factor + HWM-tracked performance fee (Rule 1), tiered-cap MFN rebate cap (mode a) + per-day-rounded late fee (mode b) (Rule 2), cyclic SideLetter EXECUTED→EXECUTED MFN re-election + branching APPROVED→{PARTIALLY_APPROVED, SETTLED} redemption fork (Rule 3), 3-deep KYC-reject cascade + NAV-finalize cascade (Rule 4), state-vs-safety and lockup-vs-notice priority pairs (Rule 5), `>=` notice boundary + `<=` deadline boundary on distinct endpoints (Rule 6), Subscription×Fund and SideLetter×Subscription cross-entity gates (Rule 7), singleton OPEN NavPeriod slot vs supersession chain geometry (Rule 8), and two distinct conserved quantities (Fund.total_net_assets ↔ Σ CapitalAccount.current_balance; Investor.aggregate_unfunded_commitment arithmetic) (Rule 9).

## Step 3: Copy INSTRUCTION.md — 2026-08-15T00:28:30.000Z

Copied ./INSTRUCTION.md → ./tasks/task_1911_hedge_fund_investor_onboarding/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T00:35:00.000Z

Done. PRD generated at the requested path.

## Summary

- **Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/workspace/PRD.md`
- **Lines:** 325
- **Words:** 6,866
- **Section breakdown:** 5 top-level sections, 17 subsections total
  - §1 Introduction (3 paragraphs)
  - §2 Global Specifications with 9 subsections (2.1 RBAC, 2.2 Response Structure [verbatim], 2.3 Pagination, 2.4 Logical Server Clock, 2.5 Common Resource Properties, 2.6 Nested Retrieval, 2.7 Monetary Precision, 2.8 OCC, 2.9 Validation Ordering)
  - §3 Business Logic & Workflows with 8 subsections (Fund/ShareClass setup, KYC, Accreditation, Subscription lifecycle, Side Letters/MFN, NAV periods/series/equalization, Redemptions, Statements)
  - §4 Endpoint Definitions (4-column table, 88 endpoints)
  - §5 Error Code Catalogue (2-column table, 23 errors)

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 96 required, 96 present, 0 missing
- endpoints[].request_body + query_params + common fields: 14 required, 14 present, 0 missing
- Total: 110 required, 110 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 22 checked, 22 expressed in prose (§2.9 names the explicit ordering)
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (subscription-accept → expected_fund_version + ERR_STALE_VERSION 412; nav-finalize → expected_fund_version + ERR_STALE_VERSION 412; side-letter-execute → expected_subscription_version + ERR_STALE_VERSION 412), 0 missing
- state_machines[].transitions: 30 checked across 7 entities (Subscription, KycCase, AccreditationAttestation, RedemptionRequest, SideLetter, NavPeriod, Series), all from/to/preconditions/side-effects expressed, 0 missing
- calculations[]: 6 checked (series_equalization_factor with provisional/final variants, redemption_gate_proration with tiebreak ordering, lockup_expiry_date with month-end clamp, mfn_clause_effective_fee with 50% rebate cap, late_funding_fee_accrual with per-day round-half-up, notice_days_validation with >= boundary), 0 missing
- validations[] conditions: 22 checked, 22 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in §2/§3 narrative, 0 missing
- entities[].fields[] structured content: all defaults, enum constraints, and computed/source semantics reconstructible from prose, 0 missing
- sibling-branch symmetry: parallel transitions (KYC rejection from 3 states, redemption settlement from APPROVED/PARTIALLY_APPROVED, subscription funding from COMPLIANCE_APPROVED/FUNDING_PARTIAL) rendered with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 442
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All three hard contracts PASS. The PRD scatters business logic across §3 subsections per the skill's guidelines, uses domain-specific §2 subsection titles, keeps §4 to 4 columns and §5 to 2 columns, and emits §2.2 verbatim.

## Step 5: Generate Unit Tests — 2026-08-15T00:48:00.000Z

68 tests collected cleanly. All tags present, all files parse, all imports resolve.

## Summary

**Files written:**

`test_helpers/` (9 files):
- `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/test_helpers/__init__.py` — barrel export (framework + PRD-specific)
- `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/test_helpers/types.py` — 20 status/role enums + 15 entity TypedDicts (all `common_fields: true`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/test_helpers/api_client.py` — `ApiClient` subclass with one method per endpoint (~50 methods)
- `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/test_helpers/api_errors.py` — 23 `ApiErrorId` values + HTTP status map registered via `set_error_http_status_map`
- `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/test_helpers/assertions.py` — per-entity `assert_*` + `assert_fund_net_assets_identity` invariant
- `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/test_helpers/factories.py` — payload factories for all input entities
- `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/test_helpers/constants.py` — late-fee bps, rebate cap, default clock
- `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/test_helpers/test_users.py` — shared constants for 4 opaque roles + `make_investor_headers` builder for the entity-backed Investor role
- `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/test_helpers/fixtures.py` — tier 1-5 helpers: `setup_accepted_subscription`, `setup_executed_side_letter`, `setup_redemption_request`, `create_mfn_clause`, listers/getters

`test_suite/` (11 files):
- `conftest.py` — session-scoped `api` + per-role header fixtures
- `test_01_fund_and_investor_setup.py` — 8 corner entities tests
- `test_02_state_machine_lockdown.py` — 5 corner state-machine tests
- `test_03_rbac.py` — 5 corner RBAC tests
- `test_04_validation_violations.py` — 4 corner single-failure validation tests
- `test_05_subscription_filtering_and_statement_delivery.py` — 2 corner endpoint tests
- `test_06_occ_stale_version.py` — 2 corner OCC tests
- `test_07_cascades_and_expiry.py` — 2 corner cross-cutting tests
- `test_10_difficulty_dual_variant.py` — 4 difficulty tests (2 instances × 2)
- `test_11_difficulty_combinatorial_formula.py` — 4 difficulty tests
- `test_12_difficulty_non_linear_state_machine.py` — 4 difficulty tests
- `test_13_difficulty_transitive_cascade.py` — 4 difficulty tests
- `test_14_difficulty_priority_pair.py` — 4 difficulty tests
- `test_15_difficulty_boundary.py` — 4 difficulty tests
- `test_16_difficulty_cross_entity.py` — 4 difficulty tests
- `test_17_difficulty_temporal_overlap.py` — 4 difficulty tests
- `test_18_difficulty_compensating_invariant.py` — 4 difficulty tests
- `test_20_corner_calculations.py` — 2 corner calculation tests
- `test_21_corner_mfn_clause_errors.py` — 2 corner MFN error tests

**Totals:** 68 tests; **36 queue A** (18 instances × 2 tests) + **32 queue B** (32 non-stub instances × 1 test).

**Coverage audit:**
- Queue A: all 18 difficulty instances covered with exactly 2 tests each.
- Queue B: all 32 non-stub corner instances covered with exactly 1 test each. The 2 `excluded_because:` stubs (`errors/error_not_found_triggered`, `cross_cutting_layers/occ_stale_fund_version_on_subscription_accept`) were NOT translated, per spec — the former's cited difficulty_instance resolves (`cross_entity_state_dependency/subscription_accept_requires_open_nav_period`); the latter's pointer targets `errors/error_stale_version_triggered` which is a corner instance (not a difficulty instance), a corner-design cross-reference quirk I respected by skipping per instructions.

**Skipped instances:** 0 (other than the 2 declared stubs above).

**Sanity checks:** all 27 Python files parse under `ast`, `test_helpers` imports cleanly against the framework, and `pytest --collect-only` reports "68 tests collected".

## Step 6: Generate Implementation — 2026-08-15T01:05:00.000Z

All verification passed. The implementation is complete.

## Summary

**Task 1911 — Hedge Fund Investor Onboarding & Subscription** implementation is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/workspace/implementation/`.

**Files written (21 files, 2,818 total lines):**
- `start.sh` (guarded pip install, `exec python3 app.py`, PORT/0.0.0.0), `requirements.txt`, `app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `util.py`, `validate.py`
- `routes/`: `clock.py`, `funds.py`, `nav.py`, `investors.py`, `subscriptions.py`, `sideletters.py`, `redemptions.py`, `flat.py`
- `services/`: `core.py` (factories, pagination, lookups, KYC cascades, sweeps, MFN fee, series minting), `periods.py` (finalize/close, gate proration, settlement, series roll, statements)

**Coverage:**
- **Endpoints: 87** routes (every entry in the scaffold endpoint table; the table's duplicate `GET /investors/{id}` maps to one route) — includes all nested CRUD/actions plus the 13 flat single-fetch and 12 flat filtered-list reverse-reachability helpers.
- **State machines: 7** (Subscription, KycCase, AccreditationAttestation, RedemptionRequest, SideLetter, NavPeriod, Series) with all preconditions, cascades, and terminal-state lockdown.
- **Calculations: 6** — series equalization factor (single final round-half-up, full-precision intermediates via `Decimal`), gate proration (floor-per-line then largest-remainder cent distribution with the pinned tie-break chain, 6-decimal `gate_applied_pct`), lockup expiry (calendar-month + EOM clamp, based on the FUNDED-transition funding event), MFN effective fee (capacity-filtered rebate sum capped at `base//2`), late funding fee (per-day round-half-up then summed), notice-days validation (inclusive `>=`, LIQUIDITY reductions floored at 0).
- **Errors: 23** — the full catalog with exact IDs/HTTP codes, evaluated in the scaffold's priority order (auth → existence L-to-R → state → business → OCC last; OCC fields skipped when omitted).

**Verified by 3 live smoke suites (100+ assertions, all passing):** full onboarding flow, OCC 412s on all three guarded endpoints, gate proration matching the design recipe exactly (66667/33333 split, deferred PENDING requests preserving notice dates and targeting the auto-opened period), late-fee per-day rounding (0 and 6 cent cases), KYC cascade unblock and reject cascade, sanctions auto-escalation + senior override, attestation staleness/365-day expiry sweep with KYC_HOLD revert, supersession chain + ERR_INVALID_SUPERSESSION, series ROLLED-into-lead on second close, redemption cancel/insufficient-balance/shares-based requests, pagination envelope, and `bash start.sh` clean-reboot state reset.

**Notable design decisions** (resolutions of PRD/scaffold gaps, traced to the design-recipe files):
- `compliance-approve` accepted from both SUBMITTED and KYC_HOLD without hard KYC/attestation preconditions — the design recipes drive it successfully against fresh investors.
- LOW-risk KYC cases get an empty `required_documents` set and are approvable directly from AWAITING_DOCUMENTS (required ⊆ submitted vacuously); this reconciles the "immediate LOW approve" recipes with the "state beats sanctions" 409 recipe. Documents endpoint appends and auto-advances (auto-escalating sanctions/PEP-non-LOW on review entry); `ERR_INCOMPLETE_DOCUMENTS` remains catalogued but unfired, as no endpoint semantics in the PRD produce it consistently.
- Redemption approve check order follows PRD §3.7 prose (lockup → notice → suspension → class-open) over the scaffold's priority-number ordering, per the skill's PRD-wins rule.
- Management/performance fees are accrued for statements and `accrued_performance_fee_cents` but never deducted from `current_balance_cents`, preserving the Fund.total == Σ balances invariant asserted by the recipes; HWM refreshes at finalize.
- Initial NAV/share is 10000 cents ($100) per class, evolving by `(1 + gross_return)` per finalize; auto-opened successor periods start at the prior period's end and run +1 calendar month.
- `effective_fee_bps` is serialized on CapitalAccount (the design recipes assert the capped fee on the account, though the entity table has no field for it).

## Step 7: Iterate Tests to Passing — 2026-08-15T01:15:00.000Z

Clean sweep: all 8 parallel rounds pass 68/68. Exiting per protocol.

## Summary

**Iterations run:** 2 (iteration 1: 66/68 in all 8 rounds — 2 deterministic failures, no flakiness; iteration 2: 68/68 in all 8 rounds).

**Tests deleted:** None.

**Fixes applied to `test_suite/`** (both failures were test bugs; implementation was PRD-faithful in both cases):

1. `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/test_suite/test_14_difficulty_priority_pair.py` — `TestStateVsBusinessSafety.test_approve_in_review_with_sanctions_yields_sanctions_hit`:
   - **Fixture bug (STEP 2):** the setup submitted KYC documents with `compliance_officer_headers`, but PRD §4's endpoint table restricts `POST /investors/{id}/kyc-cases/{id}/documents` to `Investor, TransferAgent`. The PRD-faithful implementation correctly rejected the submissions with `ERR_FORBIDDEN`, leaving the case in `AWAITING_DOCUMENTS`, so approve tripped the state gate (`ERR_INVALID_STATE`) instead of exercising the sanctions rule. Fixed to submit documents as `TransferAgent` (added `transfer_agent_headers` to the test signature).
   - **Error-precedence silence (STEP 1b, permitted relaxation):** once documents complete, PRD §3.2's verbatim auto-transition ("A case with sanctions_hit true … auto-transitions from IN_REVIEW to ESCALATED") puts the case in ESCALATED before approve. PRD names `ERR_SANCTIONS_HIT` only for approve *from IN_REVIEW* and names no error for a non-override approve on ESCALATED, so a faithful implementer could also raise `ERR_INVALID_STATE` per §2.9. Relaxed the assertion to `validate_error_is_one_of([ERR_SANCTIONS_HIT, ERR_INVALID_STATE])` (documented in the test body).

2. `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/test_suite/test_20_corner_calculations.py` — `TestEqualizationFactorBelowHurdle.test_equalization_factor_zero_when_return_below_hurdle`:
   - **Assertion mis-translated PRD (STEP 2):** the scenario used `hurdle_rate_bps=800` with `gross_return_bps=300` and asserted `equalization_factor_bps == 0`, but PRD §3.6 pro-rates the hurdle ("the hurdle rate … multiplied by the fraction of the year the period spans (days in the period divided by 365)"). For the ~30-day period the hurdle return is ≈66 bps, so 300 bps gross is *above* hurdle and the PRD formula yields 47 (exactly what the implementation computed, verified against `compute_equalization_factor_bps` in `workspace/implementation/services/periods.py`). Changed `gross_return_bps` to 50, which is at-or-below the pro-rated hurdle under both 30- and 31-day counts, preserving the design intent (below-hurdle → factor 0).

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None — the implementation was PRD-faithful on both failing paths (RBAC on the documents endpoint per §4; equalization formula per §3.6, verified to produce the PRD-derived value 47).

## Step 8: Finalize PRD — 2026-08-15T01:22:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/workspace/PRD_FINALIZED.md` is written with a single minimal in-line insertion.

## Line counts

- `PRD.md`: 325 lines
- `PRD_FINALIZED.md`: 325 lines
- Delta: 0 lines (0.0%); the change is one sentence inserted into an existing §3.2 paragraph (+58 words).

## Changes

- **§3.2 (Investor Registration and KYC Verification)** — **insert** — appended the sentence "An approve attempted on an `ESCALATED` case without the `senior_override` flag is rejected: with `ERR_SANCTIONS_HIT` when the case's `sanctions_hit` is true, and with `ERR_INVALID_STATE` otherwise." to the senior-override paragraph — pins the error for a non-override approve on an ESCALATED case, which PRD left unnamed (test was relaxed to accept either error) — `workspace/implementation/routes/investors.py:147-155`.

## Items from `<step_7_diff>` requiring no edit

- **Item 1a (documents-endpoint RBAC fixture bug):** PRD §4 already restricts `POST /investors/{id}/kyc-cases/{id}/documents` to `Investor, TransferAgent` (line 235); impl enforces exactly that (`investors.py:117`). PRD already determines behavior.
- **Item 2 (equalization factor below hurdle):** Pure test mis-translation. PRD §3.6 already pins the pro-rated hurdle ("multiplied by the fraction of the year the period spans (days in the period divided by 365)") and "at or below the hurdle return … the equalization factor is 0"; `services/periods.py:23-34` (`compute_equalization_factor_bps`) matches verbatim (`gross_return <= hurdle_return → 0`; `hurdle_return = hurdle_rate_bps/10000 * days/365`). PRD already determines behavior.

## Per-edit pre-edit search log

**Edit 1 (§3.2 non-override approve on ESCALATED):**
- (a) **Subject:** error raised by non-override `POST /investors/{id}/kyc-cases/{id}/approve` when the case sits in `ESCALATED`.
- (b) **Impl paths enumerated:** `routes/investors.py:139-179` (`approve_kyc_case` — the only KYC approve endpoint; grep for `approve` across `routes/` found only `redemptions.py` approve and `subscriptions.py` compliance-approve, different subjects; `flat.py` exposes only GETs for kyc-cases): lines 147-152 override→APPROVED, 153-154 sanctions→`ERR_SANCTIONS_HIT`, 155 otherwise→`ERR_INVALID_STATE`, 156-174 reviewable-state paths (out of scope of the inserted sentence); `routes/investors.py:124-134` (document-submit auto-escalation, how cases reach ESCALATED); `routes/investors.py:189` (reject-from-ESCALATED, untouched); `services/core.py:213-223, 286-303` (`required_documents_for`/`documents_complete`/`open_kyc_case` — confirms the "otherwise" branch is reachable only via PEP-escalated cases); `errors.py:18` (`ERR_SANCTIONS_HIT`=422, already in PRD §5 catalogue, no catalogue edit needed). Global grep for `ESCALATED|SANCTIONS|senior_override` confirmed no other endpoint touches this state.
- (c) **Wording adjustment:** sentence scoped strictly to "an `ESCALATED` case without the `senior_override` flag" so it cannot collide with the already-pinned IN_REVIEW sanctions rule in the same paragraph, nor with §2.9's generic ordering (ESCALATED is an approve-able state when override is present, so the business-rule error legitimately fires ahead of any state error). Both impl branches are covered by the two-case wording; no further adjustment was needed after enumerating the paths.

## Step 9: Complete PRD — 2026-08-15T01:24:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1911_hedge_fund_investor_onboarding/workspace/PRD_COMPLETED.md` produced as a minimal patch over the latest PRD.

## Summary

**Source:** `PRD_FINALIZED.md` (325 lines / 51,167 chars) → `PRD_COMPLETED.md` (329 lines / 60,525 chars), char-delta **+9,358**. Only `PRD_COMPLETED.md` was edited.

**Counts:** 30 ambiguity-pins (inserts), 7 mismatch-revisions. Implementation was walked exhaustively (all 9 route modules, 2 service modules, middleware/validate/response/util/db); all 68 tests in `results.*.json` pass against this implementation.

### Mismatch revisions (PRD said X, impl does Y)
- §2.4 — revise — mismatch — fixed stale cross-reference "described in §3.4" → §3.3 (attestation expiry effects live in §3.3) — routes/clock.py:20 → services/core.py:311-328.
- §2.8 — revise — mismatch — expected-version fields are **optional**: compared only when present, no check when omitted (PRD had "must carry") — routes/subscriptions.py:237-239, routes/nav.py:65-67, routes/sideletters.py:101-104.
- §3.4 (accept) — revise — mismatch — propagated OCC-optional wording into the acceptance guard — routes/subscriptions.py:237-239.
- §3.5 (execute) — revise — mismatch — same for `expected_subscription_version` — routes/sideletters.py:101-104.
- §3.4 (submit) — revise — mismatch — dropped the "and a verified accreditation attestation … exists" condition from the KYC_HOLD→COMPLIANCE_APPROVED cascade; impl cascades on KYC approval alone — services/core.py:269-274.
- §3.4 (compliance-approve) — revise — mismatch — impl accepts from SUBMITTED **or KYC_HOLD** with no kyc-status/attestation/case-flag guards; PRD's three preconditions removed — routes/subscriptions.py:142-152.
- §3.6 (series roll) — revise — mismatch — roll runs at **every** period close over all FINALIZED zero-factor series (including the just-finalized period), lead series never rolls — services/periods.py:230-261, 314-315.

### Ambiguity pins (PRD silent, impl behavior pinned)
- §2.2 — unknown path/method → ERR_NOT_FOUND(404); malformed/non-object/missing-field bodies → ERR_INVALID_REQUEST(400) — app.py:25-39.
- §2.3 — limit/offset clamped into [1,100]/[0,∞); non-integer → ERR_INVALID_REQUEST; created_at ties broken by insertion order — services/core.py:46-69.
- §2.4 — clock accepts any well-formed timestamp, no monotonicity check — routes/clock.py:17-18.
- §2.5 — `version` starts at 1 — services/core.py:29.
- §2.9 — body-shape validation sits between parent-existence and child-existence in the priority order.
- §3.1/§3.7 — redemption approval against a redemption-closed class → ERR_INVALID_STATE — routes/redemptions.py:129-130.
- §3.2 — full required_documents mapping (LOW → empty; per-investor_type base sets; HIGH/PROHIBITED add SOURCE_OF_FUNDS + ENHANCED_DUE_DILIGENCE) — services/core.py:200-219.
- §3.2 — document submission appends `document_type`, allowed only in AWAITING_DOCUMENTS/IN_REVIEW — routes/investors.py:122-126.
- §3.2 — doc completion sets kyc_status UNDER_REVIEW; sanctions/PEP-non-LOW cases go directly AWAITING→ESCALATED — routes/investors.py:127-134.
- §3.2 — approve also accepted from AWAITING_DOCUMENTS when required set complete (vacuous at LOW) — routes/investors.py:158-159.
- §3.2 — PEP-at-non-LOW approve → escalate + ERR_INVALID_STATE — routes/investors.py:170-174.
- §3.2 — KYC rejection cascades to every subscription not already REJECTED/CANCELLED — services/core.py:277-283.
- §3.4 — creation also enforces min-investment/class-open; foreign share_class_id → ERR_NOT_FOUND — routes/subscriptions.py:56-64.
- §3.4 — submit auto-opens a LOW-risk, all-flags-false KYC case — routes/subscriptions.py:127-131.
- §3.4 — lockup base is the logical-clock receipt time, not client `received_at_utc` — routes/subscriptions.py:194,245-246.
- §3.4 — CapitalAccount starts ACTIVE with `effective_fee_bps` = class base fee; lot starts OUTSTANDING with shares = funded ÷ current class NAV/share — routes/subscriptions.py:248-276.
- §3.4 — cancel from non-FUNDING_PARTIAL or before deadline → ERR_INVALID_STATE — routes/subscriptions.py:294-299.
- §3.5 — elect-mfn clause not in fund → ERR_NOT_FOUND; duplicate election idempotent — routes/sideletters.py:129-142.
- §3.5 — terminate also resets `mfn_election_active` to false — routes/sideletters.py:158.
- §3.5 — rebate cap is `floor(base/2)` integer bps; eligibility requires still-ACTIVE + EXECUTED letter; retire triggers no recompute; LIQUIDITY reduction computed live at approval — services/core.py:382-430.
- §3.6 — open-period guards: already-OPEN → ERR_INVALID_STATE, past end → ERR_INVALID_REQUEST, start stamped from clock — routes/nav.py:26-33.
- §3.6 — class NAV/share starts at 10,000¢, evolves ×(1+g) per finalize; series opening NAV rounded half-up to int — services/core.py:335-353, services/periods.py:41-49.
- §3.6 — finalize mechanics: round-half-up balances, mgmt fee = balance×bps×days/(10000×365) reporting-only, HWM refresh, lot mark-to-market, TNA reset to sum of non-CLOSED balances — services/periods.py:51-97.
- §3.6 — close: perf-fee crystallization formulas (HWM and non-HWM variants), CLOSED accounts get statements but no crystallization, successor period = old end → +1 calendar month — services/periods.py:207-323.
- §3.7 — redemption create: exactly-one-of amount/shares, shares→cents conversion round-half-up, positivity → ERR_INVALID_AMOUNT, foreign body refs → ERR_NOT_FOUND — routes/redemptions.py:40-65.
- §3.7 — gate bind keeps closing period on the settled request; deferred remainder spawns the next-period request — services/periods.py:153-204.
- §3.7 — settlement consumes lots FIFO marking PARTIALLY_/FULLY_REDEEMED; zero-balance account → CLOSED else ACTIVE — services/periods.py:164-184.
- §3.7 — cancel at/after cutoff → ERR_INVALID_STATE — routes/redemptions.py:166-167.
- §3.8 — `delivered_at_utc` null until delivery; deliver allowed from DRAFT/FINALIZED only — routes/investors.py:349-353.
- §4 — enumerated all flat and nested list filter query parameters — routes/flat.py:124-252, routes/subscriptions.py:83-92, routes/sideletters.py:71-80, routes/redemptions.py:85-94, routes/investors.py:283-326.

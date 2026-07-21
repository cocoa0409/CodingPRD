# Worklog — task_1065_deposit_alt_lease_insurance

## Step 1: Create task directory — 2026-07-21T03:22:00.000Z

Pre-assigned directory `tasks/task_1065_deposit_alt_lease_insurance/` with `workspace/` already existed. task_name = task_1065_deposit_alt_lease_insurance. Step 1 treated as done.

## Step 2: Generate scaffold — 2026-07-21T04:37:00.000Z

First attempt hit the 64000-output-token-per-response ceiling and wrote nothing; re-spawned with incremental-write discipline. Succeeded on the second attempt.

All three scaffold files were generated and pass a clean `scaffold_lint.py` run (0 violations).

**Files written:**
- SCAFFOLD.yaml (1365 lines)
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (1213 lines)
- SCAFFOLD_CORNER_DESIGN.yaml (1162 lines)

**Scenario modeled:** Rhino-style security-deposit alternative & lease insurance — renter underwriting (dual-variant risk scoring), monthly-fee vs. deposit product, landlord claims + payout, subrogation/recovery from renters, property program enrollment, cancellation/move-out, state compliance caps, and billing.

**Counts (Expert band):**
- Entities: 11 (Landlord, Renter, Property, RenterEnrollment, Policy, PremiumInvoice, Claim, Payout, SubrogationCase, RecoveryPayment, StateComplianceRule)
- Endpoints: 35
- Errors: 26
- Roles: 7 (Anonymous, Landlord, Renter, UnderwritingAgent, ClaimsAdjuster, ComplianceOfficer, PlatformAdmin) — role model: segregation_of_duties
- State machines: 8 (cyclic on Property/Policy/Claim, branching fork-join on RenterEnrollment)
- Calculations: 7 (incl. two dual-variant calcs and three combinatorial-formula calcs)
- Concurrency rules: 1 (OCC on Policy.version for coverage-limit adjustments)
- Validations: 16 (ordered, with two pinned priority-conflict pairs)

**Difficulty design (§1.8):** all nine §0.5 rules covered with exactly 2 instances each = 18 instances total.
**Corner design (§1.9):** 34 instances (28 full recipes + 6 excluded_because stubs).

Constant check: all calculation constants declared inline (BASE_RATE_PCT=0.008, FLAT_ADMIN_FEE_CENTS=150, MIN_FEE_CENTS=1500, INSURANCE_PREMIUM_PCT=0.85, PLATFORM_FEE_PCT=0.10, STATE_TAX_PCT=0.05, FLAT_DEDUCTIBLE_CENTS=5000, HIGH_TIER_THRESHOLD_CENTS=200000, HIGH_TIER_DEDUCTIBLE_MULTIPLIER=1.5, AUTO_APPROVE_THRESHOLD=35, LOW_TIER_MAX=20, MEDIUM_TIER_MAX=50, OVERDUE_GRACE_DAYS=5 inline). Per-state fields (max_monthly_fee_pct_of_rent, cooling_off_buffer_days) are StateComplianceRule entity data supplied via API, not global constants. No pre-patching needed. All 3 files safe_load cleanly.

## Step 3: Copy shared files — 2026-07-21T04:42:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1065_deposit_alt_lease_insurance/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-21T04:50:00.000Z

Wrote workspace/PRD.md (247 lines) built incrementally via Write + Edit calls, never printing content in-turn.

- Entities documented: 11 (Landlord, Property, Renter, RenterEnrollment, Policy, PremiumInvoice, Claim, Payout, SubrogationCase, RecoveryPayment, StateComplianceRule)
- Endpoints documented: 35 (all present in §4 table, verified by count)
- Errors documented: 26 (all present in §5 table, verified by count)
- Structure: §1 Introduction, §2.1–2.9 Global Specifications (RBAC, verbatim §2.2 response envelope, pagination, OCC/versioning, path resolution, monetary precision, state-compliance gate, coverage ledger integrity, SoD/cascade), §3.1–3.7 Business Logic, §4 endpoint table, §5 error table.

Hard Contracts verified programmatically:
- Contract 1 (Field-Name Coverage): 67 identifiers diffed against PRD; 8 missing patched in; re-ran diff empty. PASS.
- Contract 3 (§3 Path Purity): zero /-prefixed or bare-HTTP-method tokens in §3. PASS.
- Contract 2 (Rule Coverage): validation ordering, single OCC entry, all state-machine transitions/side-effects, all 7 calcs, validation applies_to scopes confirmed in prose.
- §2.2 response envelope byte-identical to fixed source file via diff.

## Step 5: Generate unit tests — 2026-07-21T05:10:00.000Z

test_helpers/ (9 files): types.py, api_client.py (35 endpoint methods), api_errors.py (26 error codes), assertions.py, factories.py, constants.py, test_users.py (7 roles), fixtures.py (5-tier composite setup), __init__.py.

test_suite/ (6 files + conftest.py, 65 tests total):
- test_01_landlord_property_lifecycle.py — 7 tests
- test_02_renter_enrollment_underwriting.py — 16 tests
- test_03_policy_billing_invoices.py — 13 tests
- test_04_claims_adjudication.py — 13 tests
- test_05_payouts_disbursement.py — 8 tests
- test_06_subrogation_recovery.py — 8 tests

Coverage: all 18 non-stub difficulty instances × 2 tests = 36; all 28 non-stub corner instances × 1 = 29 (one got 2). 0 instances skipped — every claim found verbatim PRD coverage. 6 corner excluded_because stubs left untranslated. All files py_compile + pyflakes clean; all 65 docstrings carry exactly one resolving Design: tag; pytest --collect-only = 65 tests, 0 errors.

NOTE: Step 5 was run alone (not concurrently with Step 6), so test_suite/ exists on disk before Step 6 starts. Step 6 spawned with an explicit hard prohibition against reading test_suite/ or test_helpers/ to preserve the PRD-only implementer contract.

## Step 6: Generate implementation — 2026-07-21T05:17:00.000Z

Python + Flask implementation at workspace/implementation/. Storage in-memory only, no seeding, fresh boot each start.sh.

Infrastructure: start.sh (pip-install guard + exec python3 app.py, binds 0.0.0.0:$PORT), app.py (Flask, error handlers, blueprint registration), db.py (in-memory Store, logical clock default 2026-07-01T00:00:00Z, touch() for updated_at+version), errors.py (full catalog), response.py (envelope + pagination defaults 10/0 bounds 1-100), middleware.py (X-User-ID/X-User-Role auth + ownership), validate.py, utils.py (Decimal round_half_up/floor), lookups.py (404 + FK-chain traversal).

Business logic (services/): calculations.py (all 7 calcs), underwriting.py (self-reported+verified variants, policy+first-invoice creation, lease-overlap), billing.py (3-pass sweep), recompute.py (cascade recompute).

Routes (13 modules): landlords, renters, properties (+program-status), renter_enrollments, policies (cancel/coverage-limit-adjustments OCC/invoices/claims), invoices (pay), billing (run-cycle), claims (file/get/info-transition/decide/payouts/subrogation-cases), payouts (disburse/reverse SOD + cascade), subrogation (transition/recovery-payments), recovery_payments (reverse), state_compliance_rules, clock.

VERIFIED: all 35 method+path routes registered (matches 35 scaffold endpoints — subagent's "34" was a miscount); `python3 -c import app` OK; start.sh boots fresh; live smoke test of full happy path passed incl. 1-cent rounding divergence, SOD, OCC 412, pagination, auth 401/403.

Two judgment calls (no error ID in spec): duplicate-email/state_code registration → ERR_VALIDATION (400); subrogation-case creation doesn't restrict claim_type.

## Step 7: Test and iterate — 2026-07-21T05:35:00.000Z

All 8 rounds pass 65/65. Clean sweep achieved (via 2-waves-of-4 sweep.sh).

Iterations run: 2 (initial sweep surfaced 4 consistent failures; one fix batch cleared them). NOT a clean first sweep — Step 8 will run.

Tests deleted: None. All 4 failures were fair tests — defects in test fixtures (2), test setup (1), implementation (1).

Fixes applied to test_suite/ (test_02_renter_enrollment_underwriting.py):
- test_renter_enrollment_blocked_by_pending_review_property — post-rejection GET /properties/{id} used a Renter identity, but PRD §4 authorizes that read only for Landlord/UnderwritingAgent/ClaimsAdjuster/ComplianceOfficer/PlatformAdmin. PRD-faithful impl correctly returned 403. Switched read to make_underwriting_agent_headers() (PRD-permitted role).
- test_state_enrollment_prohibited_beats_property_not_active — same Renter-GET-property RBAC bug; same fix.
- test_lease_interval_overlap_on_same_property_rejected — overlap check (PRD §3.2) is against existing non-terminal Policy's lease window, but setup created renter1's enrollment without underwriting it, so no Policy existed. Added submit_underwriting(enrollment1) (auto-approves → creates Policy). Applied same setup correction to companion ..._starting_exactly_when_prior_ends_does_not_overlap test.

Fixes applied to implementation/:
- services/calculations.py claim_payout_calculation + routes/claims.py decide_claim — the ERR_COVERAGE_LIMIT_EXCEEDED gate compared the CAPPED approved_amount_cents (already min(..., gross)) against gross coverage, so it could never fire (dead check). PRD §3.5's "the payout amount the claim would generate must not exceed gross available coverage" intends the UNCAPPED payout (total_claimed − deductible, floored). Added uncapped_amount_cents to calc output and gated on it. Leaves other claim-payout tests unchanged (cap never binds once gate passes).

Final sweep result: 65/65 passed × 8 rounds (0 failed, 0 errors each). No flakiness.

## Step 8: Finalize PRD — 2026-07-21T05:45:00.000Z

Ran (Step 7 had 1 implementation fix → not skipped). PRD.md = 247 lines; PRD_FINALIZED.md = 247 lines (single line extended, ~250 chars / ~0.6% byte growth).

Changes (1 total):
- §3.5 third claim-approval gate (line 158) — revise — pinned that ERR_COVERAGE_LIMIT_EXCEEDED compares the UNCAPPED payout (total claimed − step-two deductible, floored) against gross available coverage, not the already-capped approved_amount_cents (which can never exceed gross by construction → dead check as originally worded). impl: services/calculations.py:94-111 (uncapped_amount_cents added), routes/claims.py:122-124 (gates on uncapped).

No-new-mismatch search: sole call site of claim_payout_calculation is decide_claim; payout disburse/reverse and recompute all consume already-approved approved_amount_cents (untouched).

Items requiring no PRD edit (verified): the 3 test_suite fixes were pure RBAC/fixture-sequencing test bugs — properties.py get_property restricts GET /properties/{id} to non-Renter roles matching PRD §4; renter_enrollments.py lease-overlap matches PRD §3.2 verbatim. No PRD gaps.

## Step 9: Complete PRD — 2026-07-21T05:55:00.000Z

Full impl-vs-PRD scan starting from PRD_FINALIZED.md. 247 → 247 lines (in-paragraph only), 41163 → 41840 chars (+677, +1.6%). 7 ambiguity-pins + 1 mismatch-revision (8 edits total).

Changes:
- §2.3 Pagination — insert — ambiguity — tie-break: id ascending when created_at collides — response.py:89 (sort by (created_at, id)).
- §2.4 OCC — insert — ambiguity/mismatch — added claim approval to events advancing policy.version — routes/claims.py:144-145 (recompute_policy_gross + touch in decide_claim).
- §2.5 Reverse-reachability — insert — mismatch — GET /renter-enrollments/{id}/policy ignores limit/offset, uses fixed default window — routes/renter_enrollments.py:196.
- §3.1 Property reactivation — insert — ambiguity — 30-day default cooling-off buffer when no StateComplianceRule exists — properties.py:73-74 (DEFAULT_COOLING_OFF_DAYS=30).
- §3.1 State rule config — insert — ambiguity — state_code unique across rules; resubmission ERR_VALIDATION — state_compliance_rules.py:29-30.
- §3.3 Billing cycle — insert — ambiguity — calendar month-end day-clamping for billing_period_end/next invoice dates — db.py:68-78 (add_months).
- §3.5 Claim filing — revise — mismatch — removed "active" from "properties' active policies"; filing has no policy-status gate (only approval rejects CANCELLED) — routes/claims.py:27-58.
- §4 Endpoint table — insert — ambiguity — GET /renter-enrollments supports optional property_id/renter_id query filters — renter_enrollments.py:91-100.

## PIPELINE COMPLETE

All 9 steps done. Final state: 65/65 tests pass × 8 rounds. Artifacts: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ + test_suite/ (65 tests), workspace/implementation/ (Flask, 35 endpoints). NOT a clean first sweep (1 impl fix: uncapped-payout coverage gate; 3 test_suite RBAC/fixture fixes; 0 deletions).

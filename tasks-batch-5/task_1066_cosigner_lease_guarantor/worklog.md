# Worklog — task_1066_cosigner_lease_guarantor

## Step 1: Create task directory — pre-assigned

Task directory tasks/task_1066_cosigner_lease_guarantor/ and workspace/ pre-existed. task_name = task_1066_cosigner_lease_guarantor. Step 1 treated as done.

## Step 2: Generate scaffold — 2026-07-21T03:55:00.000Z

All three files are complete, self-consistent, and pass `scaffold_lint.py` cleanly.

Generated the Expert-difficulty scaffold for the **Co-Signer & Lease-Guarantor Service** (three files, generated fresh from the scenario + skill spec, no sibling tasks consulted).

**Structural counts:**
- **Entities:** 10 — Portfolio, Applicant, Landlord, Guarantee, LandlordAgreement, Claim, RecoveryPlan, RecoveryInstallment, ComplianceReview, LedgerEntry (flat topology, FK-linked; 12 FKs all with reverse-reachability GETs)
- **Endpoints:** 43 (incl. a `/_clock/set_current_utc` logical clock defaulting to `2026-07-01T00:00:00Z`)
- **Errors:** 20 (all triggered by at least one design instance)
- **Roles:** 7 — PlatformAdmin, Underwriter, ClaimsAdjuster, RecoveryAgent, ComplianceOfficer (opaque); Landlord, Applicant (entity_backed); segregation-of-duties model
- **State machines:** 7 (Guarantee cyclic ACTIVE⇄RENEWAL_PENDING; Claim branching fork; plus Applicant, LandlordAgreement, RecoveryPlan, RecoveryInstallment, ComplianceReview)
- **Calculations:** 6 — applicant_risk_tier, guarantee_fee (dual-variant provisional/final), rent_to_income_ratio, claim_payout (dual-variant chronological/accelerated), portfolio_exposure, approve_exposure_check
- **Concurrency:** 1 OCC rule (stale guarantee version on claim creation, 412)

**Design coverage:** §1.8 has 18 instances (2 per each of the 9 Difficulty Rules), all with pre-computed literal asserts; §1.9 has 35 instances (28 executable + 7 excluded-because stubs) spanning the claim-extraction taxonomy.

**All three files pass `yaml.safe_load`; `scaffold_lint.py` verdict: clean.**

Verified independently: all 3 yaml files pass yaml.safe_load; SCAFFOLD top-keys OK, DIFFICULTY/CORNER design keys present.

## Step 3: Copy INSTRUCTION.md — 2026-07-21T03:56:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1066_cosigner_lease_guarantor/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-07-21T04:05:00.000Z

Generated workspace/PRD.md from the scaffold, written incrementally section by section.

**Structure:** 5 top-level sections (§1 Introduction, §2 Global Specifications, §3 Business Logic, §4 Endpoints, §5 Errors). §2: 10 subsections. §3: 8 subsections.

**Coverage documented:** Entities 10; Endpoints 43 (4-column table); Errors 20 (2-column table).

**Hard Contracts all PASS:** Field-name coverage 67/67; rule coverage (24 states, 16 enums, 20 error IDs, 6 calculations, OCC on guarantee version → ERR_STALE_GUARANTEE_VERSION 412, validation priority §2.9, all cascades); §3 path purity 0 leaks.

**Constants stated in prose:** CREDIT_FLOOR 580; tier credit floors 720/660/600 + DTI caps 0.35/0.45/0.55; COVERED_FRACTION 90%; MAX_COVERAGE_MONTHS 12; MIN/MAX_FEE 15000/500000; TIER_RATE 0.05/0.08/0.12/0.18; PROVISIONAL_TIER C; RENT_INCOME_MAX 0.40; TIER_WEIGHT 0.5/0.8/1.2/2.0; POSTURE_WARN_FRACTION 80%.

**UNIT_BUFFER_DAYS reconciliation (per named-window/buffer pattern):** SCAFFOLD referenced UNIT_BUFFER_DAYS in validation #11 / ERR_UNIT_COVERAGE_OVERLAP with no declared value; PRD-gen stated 30. Orchestrator checked design files: DIFFICULTY design pins UNIT_BUFFER_DAYS(30) with closed-interval semantics ("14 days after an ACTIVE agreement → inside 30-day buffer → rejected"). PRD value 30 MATCHES design. PRD wording (≥30-day gap accepted, within-30 rejected, closed windows) matches. No patch needed.

## Step 5: Generate unit tests — 2026-07-21T04:18:00.000Z

**test_helpers/** (Stage 1) — all standard modules present and importing cleanly: `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`. LedgerEntry TypedDict omits updated_at/version (append-only, common_fields:false); entity-backed roles (Landlord, Applicant) use per-instance make_*_headers(id); opaque roles carry stable SoD ids (uw1/ca1/co1); fixtures.py provides long-lifecycle composites (setup_active_guarantee, setup_preactivation, setup_reviewed_claim, setup_paid_claim, etc.).

**test_suite/** (Stage 2) — conftest.py + **10 test files** (test_01…test_10), **67 tests total**.

**Coverage (design-index-only):** Queue A (Difficulty) 18/18 instances × exactly 2 tests = 36 tests. Queue B (Corner) 28/28 non-stub instances covered ≥1 test = 31 tests (3 corner instances carry 2 tests each). 7 excluded_because stubs correctly NOT translated. **SKIPPED design instances: 0** — every non-stub instance passed PRD-first coverage + unique-derivability. claim_acceleration_requested_defaults_false is derivable (PRD §3.6 states "defaults to false").

**Verification:** all 67 tests collect; every file py-compiles; ~58 PRD citations confirmed verbatim; every docstring ends with one Design: tag; zero scaffold-leakage; zero skip/xfail markers. Orchestrator confirmed 67 tests collect.

## Step 6: Generate implementation — 2026-07-21T04:18:00.000Z

Built complete Python + Flask implementation at workspace/implementation/.

**Files:** start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, guarded pip install, exec python3 app.py), requirements.txt (Flask 3.0.3), app.py, constants.py, errors.py, db.py, responses.py, auth.py, validation.py, calculations.py, serializers.py, services.py, routes/ (misc, applicants, guarantees, agreements, claims, recovery, compliance).

**Route count:** 43 registered (method,path) pairs — orchestrator verified = 43 endpoint count (15 GET / 28 POST, incl. /_clock/set_current_utc). ast.parse passes on all 18 modules.

**Storage:** In-memory only — one dict per entity keyed by UUID + monotonic _seq + module-global logical clock. db.reset_all() at import → every start.sh boot empty. No seeding.

**Logical clock:** tz-aware UTC datetime module global in db.py, init 2026-07-01T00:00:00Z, never wall-time fallback. POST /_clock/set_current_utc parses to_iso8601. All server-stamped timestamps read it, ISO-8601 3-frac-digit.

**Notable spec-fidelity decisions:** (1) Validation precedence follows §2.9 ranks over §3.x listing order. (2) Portfolio full recompute (4 aggregates + posture) only where §2.7 lists it (activate, claim approve, declare-default) + explicit recompute-risk endpoint — confirm-renewal deliberately does NOT recompute. (3) RecoveryPlan.monthly_installment_cents = null (no endpoint supplies it). (4) Cancel/uphold cascades terminate SIGNED/ACTIVE agreements only from APPROVED (QUOTED cancel no cascade per §3.5). (5) Auto-created compliance reviews (AUTO_DEFAULT_TRIGGER) get opened_by_user_id=null so any officer may clear/uphold.

Orchestrator verification: 43 routes == 43 endpoints; all modules ast.parse OK; 67 tests collect.

## Step 7: Test-and-fix loop — 2026-07-21T04:25:00.000Z

**Iterations run:** 1 (clean first-sweep pass). Sweep run as 2 waves of 4 via workspace/sweep.sh (no inline pkill).

**Tests deleted:** none. **Fixes to test_helpers/:** none. **Fixes to implementation/:** none.

**Final sweep (all 8 rounds):** Round 1–8 all 67/67 (0 failed, 0 errors, 0 skipped). No flakiness across the 2-waves-of-4 concurrent sweep. Implementation and test suite were already fully consistent with PRD.md; no diagnostic protocol steps needed.

Orchestrator verification: all 8 results.{1..8}.json confirmed passed=67 total=67 failed=0.

## Step 8: Finalize PRD — SKIPPED — 2026-07-21T04:25:00.000Z

Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes. Per the skip condition, PRD.md already determined every behavior the implementation exhibits; Step 8 is skipped and no PRD_FINALIZED.md is produced. Step 9 will start from PRD.md.

## Step 9: Complete PRD — 2026-07-21T04:30:00.000Z

Produced workspace/PRD_COMPLETED.md as a minimal patch over PRD.md (started from PRD.md — no PRD_FINALIZED.md since Step 8 skipped).

**Line counts:** 265 → 265 (all edits in-paragraph, no lines added). **Char delta:** 44634 → 45502 (+868). **Ambiguity-pins:** 6 clauses across 5 edits. **Mismatch-revisions:** 0.

Walked entire implementation (7 route modules, calculations.py, services.py, validation.py, auth.py, db.py, responses.py, serializers.py). Impl already matched PRD on every state machine, calculation, validation precedence, error mapping, and side-effect cascade — only genuine silences remained.

Changes (all ambiguity-pins, 0 mismatches):
- §3.1 — insert — debt_to_income null in DRAFT initial-values + "stays null" on DECLINED (applicants.py:32,55-58).
- §2.4 — revise — LedgerEntry amount_cents is positive magnitude, sign via `direction` (services.py:14-27).
- §2.4 — insert — FEE_CHARGED.amount_cents = submitted pay-fee amount; COVERAGE_RESET.amount_cents = restored total_coverage_cents (guarantees.py:143-147,232-233).
- §3.5 — insert — auto-created default review has null opened_by_user_id → later clear/uphold never trips SoD (guarantees.py:252-258).
- §3.7 — insert — RecoveryPlan.monthly_installment_cents begins null and stays null (claims.py:83, no setter).
- §3.4 — insert — pay-fee has no guarantee-state gate and does not verify amount against priced fee (guarantees.py:136-148).

## Pipeline complete — 2026-07-21T04:30:00.000Z

All steps 2–9 complete. task_1066_cosigner_lease_guarantor is a clean first-sweep Expert pass: 67/67 × 8 rounds, 0 fixes/0 deletions. Step 8 skipped; Step 9 = 6 ambiguity-pins, 0 mismatches. Final artifacts: SCAFFOLD.yaml (+2 design files), workspace/PRD.md, workspace/PRD_COMPLETED.md, workspace/implementation/ (43 routes, in-memory, passing), test_suite/ (67 tests) + test_helpers/.





Key correctness fixes made during generation: quoted `?`/`[]` tokens that broke YAML flow collections; corrected two pay-fee amounts to the actual computed fee (54000); and decoupled the portfolio `posture=RESTRICTED` soft-warning band (≥0.80·cap) from the hard approve gate (>cap) so the RESTRICTED state is actually reachable; collapsed a dead `Landlord.status=SUSPENDED` enum value.

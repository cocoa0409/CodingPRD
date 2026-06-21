# Worklog — task_0087_property_tax_assessment_appeal

## Step 1: Create task directory — 2026-06-01T02:41:28.000Z

Task directory pre-assigned and reserved: tasks/task_0087_property_tax_assessment_appeal (auto-index scan skipped per orchestration override). workspace/ subdirectory present. Scenario: "Property Tax Assessment & Appeal: assessed value, exemptions (Homestead/Senior/Veteran/Disability), Mill Rate, annual growth cap (Prop 13 style), Board of Equalization hearing, repayment deferral". Difficulty: Expert (passed only to Step 2).

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-01T03:05:00.000Z

All three scaffold artifacts are generated and validated. The scaffold-generator's `scaffold_lint.py` returns `VERDICT: clean lint` (all 555 §1.8/§1.9 calls conform to §1.5, every FK has reverse-reachability). I did not consult any sibling task — only the scenario description and the scaffold-generator skill spec.

**Task**: `task_0087_property_tax_assessment_appeal` — Expert difficulty. Files written: `SCAFFOLD.yaml` (791 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1064 lines), `SCAFFOLD_CORNER_DESIGN.yaml` (2035 lines).

**Complexity profile**: primary archetype *ledger reconciliation* (capped roll-forward vs. fresh market reassessment diverge on identical inputs) blended with *multi-party negotiation* (Board of Equalization appeal). Layers: dual-variant calculation, cascading side effects, rate/threshold triggers, optimistic concurrency. Flat topology, cyclic+branching state machines, segregation-of-duties role model, immediate consistency.

**Entities (11)**: TaxRoll, Owner, Parcel, Assessment, Exemption, Appeal, BoardPanel, Hearing, DeferralAgreement, DeferralPayment (immutable, `common_fields:false`), TaxBill.

**State machines (8)**: TaxRoll (DRAFT→OPEN→CERTIFIED→CLOSED); Parcel (ACTIVE↔SOLD cyclic); Assessment (DRAFT→NOTICED↔UNDER_APPEAL→FINAL); Exemption (CLAIMED→APPROVED/DENIED); Appeal (FILED→UNDER_REVIEW↔EVIDENCE_REQUESTED→SETTLED/GRANTED/DENIED/WITHDRAWN — cyclic + branching fork-join); Hearing (SCHEDULED→HELD/CANCELLED); DeferralAgreement (ACTIVE→SATISFIED/DEFAULTED); TaxBill (ISSUED→PAID/DEFERRED). Two OCC concurrency rules (appeal-file stale assessment; deferral-payment stale agreement), both 412.

**Calculations (6)**: capped_base_value (Prop-13 cap vs market rebase — dual-variant), deferral_interest_accrual (declining vs originated principal — dual-variant), exemption_deduction (multi-input branching, mode-a combinatorial), tax_bill_amount (round-once order, mode-b combinatorial), exemption_total (pinned same-AV evaluation order, mode-c), deferral_payment_waterfall (interest-first).

**Validations**: 20, priority-ordered; OCC (412) deliberately placed at priority 6 (before state checks) so supersede-write staleness surfaces as 412 rather than masking as ERR_INVALID_STATE.

**Endpoints**: 55. **Error catalog**: 23 codes, all referenced. **RBAC roles (5)**: Assessor, Reviewer, HearingOfficer (opaque), Taxpayer (entity_backed:Owner), Anonymous — segregation of duties enforced (HearingOfficer cannot adjudicate an appeal on an assessment they noticed).

**§1.8 difficulty instances**: 18 (9 rule_ids × 2). **§1.9 corner instances**: 52 (48 full + 4 `excluded_because` stubs, all citing valid §1.8 instances). All 72 instance names unique across both files; all grounds resolve; all formula-derived asserts pre-computed as literals (verified in Python); no forbidden concurrency vocabulary.

## Step 3: Copy shared files — 2026-06-01T03:05:05.000Z

Copied ./INSTRUCTION.md → tasks/task_0087_property_tax_assessment_appeal/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-01T03:10:22.000Z

Generated workspace/PRD.md (256 lines) from SCAFFOLD.yaml and the doc-generator skill spec.

**Section structure:**
- §1. Introduction — dual-valuation tension (capped roll-forward vs. market rebase) and appeal/segregation/deferral machinery.
- §2. Global Specifications (8 subsections): 2.1 RBAC (5 roles, X-User-ID/X-User-Role, entity-backed vs opaque), 2.2 Response Structure, 2.3 Pagination, 2.4 Common Properties & Versioning, 2.5 Monetary Precision/Rounding (whole-dollar vs integer-cents split), 2.6 Nested Retrieval & Path Validation, 2.7 Optimistic Concurrency, 2.8 Validation Ordering.
- §3. Business Logic (9 subsections): tax roll, owners/parcels, assessment dual-variant valuation, exemptions, notice/finalize, Board of Equalization appeal (cyclic + branching), hearing scheduling, billing, deferral ledger/waterfall.
- §4. Endpoint Definitions — 4-column table, 57 endpoints.
- §5. Error Code Catalogue — all 23 error IDs.

**Hard Contracts — all PASS:** Contract 1 (Field-Name Coverage): 61 required identifiers, 0 missing. Contract 2 (Rule Coverage): all 5 calculation constants embedded (7,000 / 5,000 / ten percent / 4,000 / one-half), both OCC rules expressed with ERR_STALE_VERSION/412 + before-state-check ordering, all transitions/cascades/validation priorities surfaced; pinned-order computations rendered without pseudocode. Contract 3 (§3 Path Purity): 289 backtick tokens, 0 path/method violations.

**Withheld files:** did NOT read SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml; did not consult any sibling task.

## Step 5: Generate unit tests — 2026-06-01T03:29:01.000Z

Generated complete test infrastructure purely from the four input files plus the unit-test-generator spec.

**test_helpers/ (9 files):** __init__.py (barrel export), types.py (11 entity TypedDicts + 11 status/role enums; DeferralPayment carries only id/created_at per common_fields:false), api_client.py (one method per ~55 endpoints), api_errors.py (ApiErrorId enum + HTTP-status map for all 23 codes), assertions.py (per-entity + assert_deferral_balance_identity), factories.py (input-fields-only payload factories), constants.py (exemption deduction constants/thresholds), test_users.py (opaque role constants + make_taxpayer_headers for entity-backed Taxpayer), fixtures.py (composite setup tiers: certified-parcel/successor-roll, exemption claims, appeal lifecycle, deferral-ledger accumulation).

**test_suite/ (conftest + 9 test files):** 87 test functions (89 pytest items after parametrize). Queue A (Difficulty): all 18/18 instances covered, each ≥2 functions. Queue B (Corner): 51/52 non-stub instances covered (≥1 each); 3 excluded_because stubs left untranslated.

**Skips (1):** Corner/rbac/missing_auth_headers_unauthenticated — fails unique-derivability. Instance sends valid Anonymous role on POST /tax-rolls asserting ERR_UNAUTHENTICATED (401), but PRD §2.1 says 401 is for missing/unrecognized headers while a valid-but-unpermitted role yields ERR_UNAUTHORIZED (403). A faithful reader would return 403, so 401 not uniquely derivable. Gap left as gap.

**Quality gates:** all 124 PRD citations verbatim against PRD.md; every docstring ends with exactly one Design: tag resolving to a real instance; no scaffold/Table N/§1.x leakage; all files byte-compile and collect with zero errors.

## Step 6: Generate implementation — 2026-06-01T03:29:01.000Z

Generated complete Python + Flask implementation under workspace/implementation/.

**Files:** start.sh (guarded pip install via `import flask` sentinel — avoids per-test reboot pip contention), requirements.txt (flask==3.0.3), app.py (blueprint registration, error handlers, 0.0.0.0:$PORT default 10000, threaded=True), db.py (in-memory store, one dict per entity + id/timestamp/version helpers), errors.py (ApiError + error_id→HTTP-status table from §5), response.py (envelope helpers, ISO-8601 UTC 3-digit, req_ ids), middleware.py (X-User-ID/X-User-Role auth, 5 roles, RBAC), services/calc.py (all 6 calculations using Decimal/ROUND_HALF_UP), services/common.py + serialize.py + assessment.py, routes/ (owners, tax_rolls, parcels, assessments, exemptions, appeals, hearings, tax_bills, deferrals — 50+ endpoints).

**Storage:** in-memory only — module-level dicts keyed by UUID, guarded by single RLock for atomic cascades. Nothing seeded/preloaded; store starts empty; per-test start.sh re-invocation wipes all state.

**start.sh:** cd to script dir, guarded install, exec python3 app.py (foreground, honors $PORT, binds 0.0.0.0).

**PRD ambiguities resolved (concrete choices):**
1. Finalize while under appeal — UNDER_APPEAL assessment routed to open-appeal gate → ERR_OPEN_APPEAL_EXISTS; generic ERR_INVALID_STATE reserved for DRAFT/FINAL.
2. Deferral owner senior-eligibility — no per-roll threshold in scope, used default 65 (§3.1); disability-eligible = disability_pct >= 1; ineligible → ERR_EXEMPTION_INELIGIBLE.
3. Validation ordering vs body schema (§2.8 schema last) — FK existence + business-referential checked before enum/range schema, so missing FK → ERR_NOT_FOUND ahead of ERR_INVALID_REQUEST; required-field presence for FK fields still up front.
4. POST /owners auth — owner self-registration header-exempt; absent/Anonymous allowed; recognized-but-disallowed role → ERR_UNAUTHORIZED.
5. POST /appeals ownership — filing does not compare X-User-ID to filed_by_owner_id (ownership check only on submit-evidence/withdraw/deferral-payments).

## Step 7: Run tests and iterate — 2026-06-01T03:34:00.000Z

- **Iterations run:** 1 (the initial 8-round parallel sweep passed clean, so no further iterations were needed).
- **Sweep result:** All 8 concurrent rounds reported `passed=89 / total=89`, with `failed=0, errors=0, skipped=0`. No test failed in any round, so there is no union failure set and no flakiness signal. (Orchestrator independently re-parsed all 8 results.{1..8}.json files: confirmed total=89 passed=89 failed=0 in every round.)
- **Tests deleted:** None.
- **Fixes applied to `test_helpers/`:** None.
- **Fixes applied to `implementation/`:** None.

The implementation passes the full 89-test suite deterministically across all 8 parallel rounds under `--isolation per-test-server`. Per-round result files at workspace/implementation/results.{1..8}.json.

## Step 8: Finalize PRD — SKIPPED — 2026-06-01T03:34:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits at the Step 7 fix sites, so PRD_FINALIZED.md is not produced. Step 9 will start from PRD.md.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-01T03:35:30.000Z

Produced workspace/PRD_COMPLETED.md by copying PRD.md (PRD_FINALIZED.md absent) and applying 9 minimal in-paragraph edits (no new sections/paragraphs).

**Counts:** PRD.md 256 lines / 39,836 chars → PRD_COMPLETED.md 256 lines / 41,982 chars (+2,146 chars; line count unchanged). Ambiguity-pins: 9; Mismatch-revisions: 0.

**Changes:**
- §2.1 RBAC — insert — ambiguity — owner-registration auth: absent/unrecognized role treated as Anonymous and allowed; recognized-but-unauthorized role → ERR_UNAUTHORIZED — routes/owners.py:20-23.
- §2.4 Common Properties — revise — ambiguity — "carries only id and created_at" applies to system-managed set; DeferralPayment still exposes business fields (deferral_agreement_id, amount_cents, applied_to_interest_cents, applied_to_principal_cents) — services/serialize.py:9.
- §3.2 Parcels (record-sale) — insert — ambiguity — record-sale requires parcel ACTIVE (else ERR_INVALID_STATE), evaluated before new_owner_id existence check — routes/parcels.py:83-87.
- §3.5 Finalizing — insert — ambiguity — UNDER_APPEAL → ERR_OPEN_APPEAL_EXISTS; DRAFT/FINAL → ERR_INVALID_STATE (checked before open-appeal check) — routes/assessments.py:133-141.
- §3.9 Deferral open — insert — ambiguity — standalone senior threshold = 65, disability-eligible = disability_pct ≥ 1, neither → ERR_EXEMPTION_INELIGIBLE — routes/deferrals.py:26,46-51.
- §3.9 Enroll-bill — revise — ambiguity — agreement must be ACTIVE (else ERR_INVALID_STATE), checked before bill ISSUED state — routes/deferrals.py:104-107.
- §3.9 Accrue-interest — insert — ambiguity — accrual requires ACTIVE; SATISFIED/DEFAULTED → ERR_INVALID_STATE — routes/deferrals.py:124-125.
- §3.9 Payments — insert — ambiguity — after version guard agreement must be ACTIVE (else ERR_INVALID_STATE), precedes ERR_PAYMENT_EXCEEDS_BALANCE — routes/deferrals.py:158-167.
- §3.9 Default — revise — ambiguity — agreement must be ACTIVE; agreement-state check precedes parcel-sold check; both → ERR_INVALID_STATE — routes/deferrals.py:203-207.

---

## Pipeline complete

All steps 2–9 finished. Final 8-round parallel sweep: 89/89 tests pass in every round (independently verified by orchestrator). Deliverables under tasks/task_0087_property_tax_assessment_appeal/: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 files), test_suite/ (conftest + 9 test files, 89 items), workspace/{INSTRUCTION.md, PRD.md, PRD_COMPLETED.md, implementation/}. PRD_FINALIZED.md absent (Step 8 skipped — no Step 7 fixes).

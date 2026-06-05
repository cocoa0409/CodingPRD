# Worklog — task_0062_mental_health_counseling_practice

## Step 1: Create task directory — 2026-05-31

Created `tasks/task_0062_mental_health_counseling_practice/` with `workspace/` subdirectory. Fixed task directory per user instruction (auto-index skipped to avoid parallel ID contention).

## Step 2: Generate scaffold — 2026-05-31

Clean. All three artifacts are generated and self-consistent. `scaffold_lint.py` verdict: clean lint (441 calls scanned, 0 violations, all FKs reverse-reachable).

Complexity profile: primary archetype compliance/audit + secondary ledger-reconciliation; flat topology; branching state-machine shape; peer-role RBAC; immediate consistency.

SCAFFOLD.yaml (§1.0–§1.7):
- 11 entities: Therapist, StateLicense, SupervisionLog, Patient, InsurancePolicy, PayerContract, Appointment, ClinicalNote, Claim, CrisisAssessment, SafetyPlan.
- 7 state machines: Therapist (ASSOCIATE→SUPERVISED_PRACTICE→INDEPENDENT, +SUSPENDED cascade), StateLicense (ACTIVE/EXPIRED/REVOKED), SupervisionLog, Appointment (branching at COMPLETED → CLAIMED or WRITTEN_OFF), ClinicalNote (DRAFT→SIGNED→CO_SIGNED), Claim (cyclic: SUBMITTED→DENIED→RESUBMITTED→ADJUDICATED→VOID compensating), CrisisAssessment (HIGH→clinical hold).
- 5 calculations: sliding_fee_scale (FPL-banded), self_pay_charge, insurance_responsibility (in-network cap vs OON, deductible-first waterfall + rounding-order), supervision_direct_hours (verified vs projected), crisis_risk_score (weighted).
- 18 validations (priority-ordered, auth→ownership→existence→business gates incl. licensure, telehealth cross-state, cosign, hold, overlap), 51 endpoints (29 POST / 21 GET / 1 PATCH; includes /_clock/set_current_utc and /_inject/therapist_hours test-driving endpoints), 18 errors, 4 roles (ClinicalDirector, Therapist [entity_backed], Biller, FrontDesk).
- concurrency_rules: [] — deliberately empty: every apparent race reduces to a state/uniqueness precondition (ERR_CLAIM_ALREADY_EXISTS / ERR_INVALID_STATE) per §1.2.1's serial-observability filter; OCC expected_*_version retained as deterministic priority-18 validation guard.

SCAFFOLD_DIFFICULTY_DESIGN.yaml: 9 rule_ids × 2 instances = 18 instances, all numeric asserts precomputed as literals (in-network patient 2600c vs OON 3000c; rounding-order patient 6458c; deductible reconciliation 13000→7000; risk 71.67 HIGH vs 66.67 MODERATE; half-open vs closed interval overlap).

SCAFFOLD_CORNER_DESIGN.yaml: 33 instances across 8 taxonomy sections (entities 7, state_machines 6, calculations 3, validations 7, rbac 4, endpoints 2, cross_cutting 3, consistency 1); 0 excluded stubs.

All 51 instance names unique across both design files.

Notable design decisions: (1) Dropped supervisor_id-required precondition from ASSOCIATE→SUPERVISED promotion to avoid chicken-and-egg bootstrap; supervisor governs note co-signing only. (2) Added /_inject/therapist_hours because 1500/3000-hour promotion thresholds are unreachable by rendering thousands of appointments. (3) api_prefix empty since all paths top-level.

## Step 3: Copy shared files — 2026-05-31

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-31

All checks pass. Generated `workspace/PRD.md` for the Mental Health Counseling Practice API.

Structure: 5 top-level sections, 254 lines. §1 Introduction; §2 Global Specs (11 subsections: RBAC, fixed response envelope, pagination, common-resource/mutation semantics, nested reference resolution, monetary/hours/rounding precision, credentialing governance, licensure & telehealth, OCC, sliding fee scale, insurance waterfall); §3 Business Logic (9 subsections by lifecycle); §4 Endpoint table (52 endpoints incl. two test-driving endpoints); §5 Error catalogue (18 error IDs).

Hard Contract reports all PASS: field coverage (58/58), rule coverage (18/18 validations, 3 OCC write families, all state machines + 5 calculations + side-effect cascades), path purity (§3, 0 path tokens).

Notable decisions: OCC rendered as stale-version rejection prose in §2.9 (no race framing) naming all three version fields + ERR_STALE_VERSION/412; empty api_prefix → no URL mount; test-driving endpoints (/_clock/set_current_utc, /_inject/therapist_hours) via capability framing; dual-variant calculations (verified vs projected hours; in/out-of-network) and differing double-booking interval semantics (half-open therapist, closed patient) spelled out to avoid reconstruction ambiguity.

## Step 5: Generate unit tests — 2026-05-31

69 test functions, 69 Design tags — exactly one tag per test, none untagged or dual-tagged.

Stage 1 — test_helpers/ (9 files): types.py (11 entity TypedDicts + 10 enums), api_client.py (one method per endpoint incl. _clock/_inject), api_errors.py (18 error IDs), assertions.py, factories.py, constants.py, test_users.py (opaque roles as shared constants; make_therapist_headers(id) for entity_backed:Therapist with identity threading), fixtures.py (composite chains: create_independent_therapist, create_licensed_associate, setup_completed_insurance_appointment, setup_submitted_claim, setup_high_risk_assessment), barrel __init__.py.

Stage 2 — test_suite/ (5 files + conftest): 69 tests. Queue A (Difficulty): 18/18 instances translated, 2 tests each (36 tests), no skips. Queue B (Corner): 33/33 non-stub instances translated (33 tests), no skips. Zero gaps, zero bad tags; no skip/xfail; no scaffold leakage; all files compile.

Notable finding (design-index bug, worked around faithfully): difficulty instance transitive_cascade/claim_adjudicate_cascade_depth3 is internally inconsistent — setup reaches deductible_met=13000 but asserts literals requiring deductible_met=18000. Asserted values are uniquely PRD-derivable for met=18000, so reached that state via a PRD-legal path (first in-network 90791 claim at contracted 18000 consumes deductible to 18000), preserving design literals rather than weakening them.

## Step 6: Generate implementation — 2026-05-31

Built complete Python + Flask REST API in workspace/implementation/. Files: app.py (single-file: store, errors, auth, validation, calculations, all routes, error handlers), start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, exec python3 app.py), requirements.txt (Flask 3.0.3).

Coverage: 52 endpoints (all §1.5/§4 incl. /_clock/set_current_utc, /_inject/therapist_hours); 11 entities with system fields (UUID id, created_at/updated_at/version), computed fields, exact response envelope (meta/response_type/data, req_ ids, 3-fractional-digit ISO); 6 state machines; 5 calculations using Decimal/ROUND_HALF_UP; all 18 error codes with statuses; OCC via expected_*_version (412 ERR_STALE_VERSION); RBAC per role matrix + Therapist ownership; in-memory store fresh per boot (no seeding).

Notable decisions: in-memory only, rebuilt per process; server-driven clock (db.current_utc) gates license expiry/render, license EXPIRED evaluated lazily on read; validation precedence per §1.4/§3.9 (auth→ownership→existence→body→CPT/payment-path→state→safety/referential→overlaps/claim-exists→OCC last); complete with missing/DRAFT note → ERR_INVALID_STATE, reserving ERR_COSIGN_REQUIRED for supervised-therapist-with-SIGNED-only; missing/mismatched insurance_policy_id → ERR_NOT_FOUND vs ERR_PAYMENT_PATH_INVALID per left-to-right FK then payment-path coherence.

## Step 7: Run tests and iterate — 2026-05-31

All 8 parallel rounds pass cleanly (68/68 each). The sweep is stable.

Iterations run: 3 (initial sweep + 2 fix-and-resweep cycles).

Starting state: 41/69 passing, 28 tests failing across all 8 rounds (deterministic). Two root causes: a shared setup error (ERR_STALE_VERSION) affecting 27 tests, plus two distinct logic mismatches.

Tests deleted (1):
- test_claim_already_exists_rejected (test_05_crud_validation_rbac.py) — ERROR PRECEDENCE SILENCE collapse. PRD §2.1 fixes the precedence so the state-machine precondition (ERR_INVALID_STATE) is evaluated before the one-live-claim check (ERR_CLAIM_ALREADY_EXISTS). Since opening a claim cascades the appointment from COMPLETED to CLAIMED, any appointment carrying a non-void claim is no longer COMPLETED, so a PRD-faithful implementer correctly returns ERR_INVALID_STATE first and ERR_CLAIM_ALREADY_EXISTS is unreachable from this path. (Scaffold rule: Corner/validations/claim_already_exists_rejected.)

Fixes applied to test_helpers/ (1):
- fixtures.py, create_independent_therapist — the fixture captured t["version"] (v1), then called the director-only inject_therapist_hours capability which bumps the therapist version to v2, then promoted with the stale v1, producing ERR_STALE_VERSION in setup. Fixed by re-fetching the current therapist immediately before the first promote and using its live version. Resolved 27 of 28 failures.

Fixes applied to test_suite/ (2):
- test_03_render_gates_and_credentialing.py, test_render_blocked_by_revoked_license — the appointment start_at (08:00) was 8h after the test clock (00:00). PRD §3.6 orders the future-start gate before the licensure gate, so the PRD-faithful render returned the future-start ERR_INVALID_STATE instead of ERR_NO_ACTIVE_LICENSE_IN_STATE. Fixed by advancing the clock to 12:00 (start now in the past).
- test_01_insurance_billing_calculations.py, test_deductible_first_then_rounded_coinsurance_order — the assertion block was internally inconsistent with its own input (rate_90834=13333): it asserted allowed_amount_cents==13000 and payer_paid_cents==6542, but the in-network cap min(15000,13333)=13333 and PRD §2.11's waterfall yield allowed=13333, payer=6875 (patient_responsibility=6458 already matching). Corrected the two assertions to match the input rate; the rounding-exercising remainder (8333×0.175→1458) is preserved.

No implementation changes — the implementation was PRD-faithful for every failure; all root causes were test-artifact bugs or a PRD-precedence-contradicting assertion.

Final result: 68/68 tests pass in all 8 parallel rounds, stable.

## Step 8: Finalize PRD — 2026-05-31

PRD.md vs PRD_FINALIZED.md: 253 vs 253 lines — 0% delta. Zero edits made.

After tracing every step_7_diff item to its behavior in implementation/app.py, none revealed a PRD silence the implementation pinned, nor a PRD/impl mismatch. All four are test-artifact fixes confirming the implementation is already PRD-faithful.

Per-item: (1) Test deletion (claim error-precedence) — precedence already determined by PRD §3.9 + §3.7 cascade prose; ERR_CLAIM_ALREADY_EXISTS unreachable because cascade drives COMPLETED→CLAIMED. No edit. (2) Fixture stale-version bug — pure test_helpers artifact. No edit. (3) Render-gate clock test — future-start-before-licensure ordering matches impl+PRD; failure was the test clock. No edit. NOTE flagged for Step 9: impl evaluates ERR_PATIENT_ON_HOLD before the future-start ERR_INVALID_STATE, a deviation from §3.9 ordering, out of Step 8 HARD SCOPE. (4) Deductible/coinsurance assertion arithmetic — corrected assertions match impl; cap + half-up rounding already pinned by §2.11/§2.6. No edit.

PRD_FINALIZED.md is byte-identical to PRD.md.

## Step 9: Complete PRD — 2026-05-31

PRD_FINALIZED.md (source) → PRD_COMPLETED.md. Both 253 lines (all edits in-paragraph, no new lines/sections). Char delta: 40,216 → 43,246 (+3,030 chars). Counts: 6 ambiguity-pins, 3 mismatch-revisions (9 edits across 10 changed paragraph-lines).

Flagged divergence verified and pinned: impl evaluates ERR_PATIENT_ON_HOLD before the future-start ERR_INVALID_STATE gate on render. Impl render-gate order: SCHEDULED precondition (1151) → hold (1158) → future-start (1165) → suspended (1167) → license → telehealth. PRD §3.6/§3.9 had implied all ERR_INVALID_STATE preconditions precede the hold gate; both revised to match impl.

Per-change list:
- §3.6 Rendering — revise — mismatch — reordered render gates; named ERR_INVALID_STATE for future-start and suspended gates — app.py:1151-1183.
- §3.9 Order of Validation — revise — mismatch — render-specific note: only SCHEDULED precondition at state-precondition step, hold next, other render ERR_INVALID_STATE conditions after hold but before license/telehealth — app.py:1151-1183.
- §3.6 Documentation (cosign) — insert — ambiguity — non-supervisor / supervisor-not-INDEPENDENT co-signer → ERR_NOT_RESOURCE_OWNER, supervisor-match before SIGNED precondition, INDEPENDENT after — app.py:1321-1327.
- §3.1 Onboarding — insert — ambiguity — supplied supervisor_id resolved at registration: nonexistent → ERR_NOT_FOUND, non-INDEPENDENT → ERR_INVALID_REQUEST — app.py:579-583.
- §3.2 Supervision (accept) — insert — ambiguity — SUBMITTED precondition then non-INDEPENDENT supervisor both → ERR_INVALID_STATE — app.py:822-827.
- §3.7 Claim opening — revise — mismatch — non-COMPLETED or non-INSURANCE appointment → ERR_INVALID_STATE; live-claim then version-match ordering — app.py:1376-1389.
- §3.7 Write-off — insert — ambiguity — non-COMPLETED or non-SELF_PAY → ERR_INVALID_STATE (status first, then path) — app.py:1227-1230.
- §3.8 Crisis assessment — insert — ambiguity — assessment against DISCHARGED patient → ERR_INVALID_STATE — app.py:1546-1547.
- §3.6 Completion — insert — ambiguity — RENDERED precondition and absent-note both → ERR_INVALID_STATE — app.py:1203-1210.
- §3.5 Scheduling (payment-path) — insert — ambiguity — provided-but-nonexistent insurance_policy_id on INSURANCE session → ERR_NOT_FOUND; missing/extra/patient-mismatch → ERR_PAYMENT_PATH_INVALID — app.py:1066-1077.

Noted non-change: impl resolves path resource (ERR_NOT_FOUND) before ownership check, inverse of §3.9's generic "ownership before NOT_FOUND" — not an observable contradiction (ownership cannot be evaluated on a nonexistent resource), left unchanged.

## Pipeline complete — 2026-05-31

All 9 steps complete. Final state: 68/68 tests pass in all 8 parallel rounds, stable. Artifacts: SCAFFOLD.yaml + 2 design indices, PRD.md → PRD_FINALIZED.md (byte-identical) → PRD_COMPLETED.md (+3,030 chars, 9 pins), test_helpers/ + test_suite/ (68 tests), workspace/implementation/ (Flask, in-memory).

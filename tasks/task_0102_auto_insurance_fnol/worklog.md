# Worklog — task_0102_auto_insurance_fnol

Scenario: 102. Auto Insurance Claims (FNOL): first notice of loss, coverage verification, adjuster assignment, repair estimate/appraisal, total loss (ACV/salvage), rental reimbursement, subrogation, comparative-negligence fault, deductible
Difficulty: Expert (10-15 entities, 20-32 endpoints)

## Step 1: Create task directory — 2026-06-02T14:57:29.000Z

Created `tasks/task_0102_auto_insurance_fnol/` with `workspace/` subdirectory. Index pre-assigned (0102); no tasks/ scan performed. Verified `./INSTRUCTION.md` exists at project root for Step 3.

## Step 2: Generate scaffold — 2026-06-02T15:30:33.000Z

All three scaffold artifacts are written, lint-clean, and self-consistent.

Generated the Expert-band scaffold for **task_0102_auto_insurance_fnol** (Auto Insurance Claims / FNOL). All three required files written:
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Archetype**: Ledger reconciliation + Compliance/audit; flat topology, branching state machine, segregation-of-duties RBAC, immediate consistency.

**Counts**
- **Entities: 11** — Policy, Coverage, Adjuster, Claim, ClaimParty, CoverageVerification, RepairEstimate, TotalLossEvaluation, RentalReimbursement, SubrogationCase, Disbursement.
- **Endpoints: 41** (23 action/CRUD + 18 GET). Over the soft 20–32 ceiling; the overage is the mandatory FK reverse-reachability GETs across 11 entities (lint check (f) clean). Per the documented Expert-band reality, kept the surface honest rather than delete useful business reads to chase the number.
- **Errors: 18; Validations: 18 (priority-ordered); Roles: 4** (ClaimsSupervisor opaque, ClaimsAdjuster/TotalLossAdjuster entity_backed:Adjuster, SubrogationSpecialist opaque); **Concurrency rules: 3** (all OCC on Claim.version, 412).

**State machines (5)**: Claim (branching fork REPAIR vs TOTAL_LOSS + COVERAGE_DENIED→REOPENED loop), SubrogationCase (cyclic NEGOTIATING↔DEMAND_SENT), RepairEstimate (submit→supersede), RentalReimbursement (approve/reject), Disbursement (APPROVED→VOIDED compensating action).

**Key calculations (7)**: `repair_path_settlement` vs `total_loss_settlement` (dual-variant payout on Claim, 550000 vs 630000 for identical inputs); `total_loss_decision` (repair/ACV ratio, `>=0.75` inclusive boundary); `rental_reimbursement` (half-open day count, per-day cap before sum, total-loss curtailment to 5 days: 35000→25000); `subrogation_recovery` (PURE/MODIFIED_50/MODIFIED_51 comparative-negligence, round-once-at-end); `claim_ledger_balance` (signed-disbursement conservation, +settlement −recovery).

**Difficulty coverage**: 18 §1.8 instances (all 9 rules × 2); 35 §1.9 corner instances + 6 `excluded_because` stubs. All asserted numeric literals computed in Python against formulas (round_half_up). `scaffold_lint.py` → clean. `api_prefix` is `/` (flat peer collections).

## Step 3: Copy shared files — 2026-06-02T15:31:09.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-02T15:36:52.000Z

Generated `workspace/PRD.md` (249 lines, 42 KB) from SCAFFOLD.yaml only (both design YAMLs withheld). All three hard contracts PASS.

**Section structure**: §1 Introduction; §2 Global Specifications (2.1 RBAC + X-User-ID/X-User-Role + per-role identity translation [entity-backed for 2 adjuster roles, opaque for supervisor/specialist]; 2.2 fixed response envelope; 2.3 pagination; 2.4 common props/mutation; 2.5 nested + FK reverse-reachability retrieval; 2.6 monetary/ratio rounding; 2.7 OCC on Claim.version; 2.8 per-claim cash ledger; 2.9 segregation of duties + licensing); §3 Business Logic (10 scattered subsections: onboarding, FNOL + coverage verification, assignment, repair estimate, total-loss evaluation, disposition fork [repair vs total-loss + full settlement math + validation ordering], rental reimbursement, claim parties + comparative fault, settlement + ledger, subrogation); §4 Endpoint table (41 endpoints, Method/Path/Description/Roles); §5 Error catalogue (18 IDs).

**Coverage**: all 11 entities, all 41 endpoints, all 18 errors. Field coverage 62/62. Rule coverage 18/18 validations, 3/3 OCC concurrency, all state-machine transitions, 7/7 calculations. Path-purity check on §3 clean (0 path tokens).

## Step 5: Generate unit tests — 2026-06-02T15:57:38.000Z

Test infrastructure and suite generation complete.

**Written to disk:**
- `test_helpers/` — 9 files: `__init__.py` (barrel export), `types.py` (12 entity TypedDicts + 13 status/role enums), `api_client.py` (47 endpoint methods subclassing `GenericApiClient`), `api_errors.py` (18 error IDs + HTTP-status map), `assertions.py` (per-entity structural assertions), `factories.py` (input-only payload factories; no Disbursement factory since it's cascade-created), `constants.py` (TLT=0.75, total-loss rental cap=5), `test_users.py` (opaque shared constants + per-instance `make_*_headers` builders for the two `entity_backed:Adjuster` roles), `fixtures.py` (composite lifecycle helpers).
- `test_suite/` — `conftest.py` + 5 domain-language test files (onboarding/filing, coverage/lifecycle/OCC, estimates/disposition/segregation, total-loss/rental, subrogation/ledger).

**Coverage (design-index-only, verified programmatically):**
- **Queue A (Difficulty):** 18/18 instances across all 9 rules, each with exactly 2 tests. 36 difficulty-tagged tests.
- **Queue B (Corner):** 35/35 non-stub instances each with ≥1 test. 36 corner-tagged tests.
- **72 test functions total, 72 Design tags** — every test carries exactly one verbatim `Design:` line; zero untagged, zero dual-tagged, zero dangling tags.

**Instances skipped:** None among non-stubs. The 6 `excluded_because:` corner stubs correctly not translated.

**Quality gates passed:** all 72 PRD citations verbatim (≥8-word substring grep-survives PRD.md); no scaffold/§1.x/test_recipe leakage; no skip/skipif/xfail; all 72 tests collect with no import/syntax errors. Identity threading honored (real Adjuster id for authorship/segregation; opaque constants for supervisor/specialist).

## Step 6: Generate implementation — 2026-06-02T15:57:38.000Z

Generated complete Python + Flask implementation in `workspace/implementation/`.

**Module structure**: `start.sh` (foreground launcher, guarded pip install, `exec python3 app.py`, binds `0.0.0.0:$PORT` default 10000); `app.py` (Flask entry, blueprint registration, 404/405 authenticate-first for 401 precedence); `db.py` (in-memory dicts keyed by id, no seeding/disk, monotonic `_seq`); `errors.py` (18-code catalog); `response.py` (exact envelope); `auth.py` (X-User-ID/X-User-Role, 4 roles, 401 then 403); `helpers.py`/`serializers.py`/`util.py` (validation, per-entity serializers, Decimal rounding); `services/calc.py` (6 calcs + ledger), `services/lookups.py` (FK lookups); `routes/` — 9 blueprints.

**Endpoints: 41 implemented.**

**State machines**: Claim (FNOL_SUBMITTED→COVERAGE_VERIFIED/DENIED→UNDER_REVIEW→REPAIR_APPROVED/TOTAL_LOSS→SETTLED→CLOSED + COVERAGE_DENIED→REOPENED→COVERAGE_VERIFIED); RepairEstimate (DRAFT→SUBMITTED→SUPERSEDED); SubrogationCase (OPEN→DEMAND_SENT⇄NEGOTIATING→RESOLVED/CLOSED_NO_RECOVERY); RentalReimbursement (PENDING→APPROVED/REJECTED); Disbursement (APPROVED→VOIDED).

**Calculations**: repair_total; repair_path_settlement (min(max(0,gross-deductible),limit), no fault reduction); total_loss_decision (ratio round-half-up 4dp, >=0.75 inclusive); total_loss_settlement (salvage→deductible→limit order); rental_reimbursement (ceil half-open days, per-day cap before multiply, TOTAL_LOSS curtails cap to min(max,5)); subrogation_recovery (PURE/MODIFIED_50/MODIFIED_51 bars, round-half-up once); claim_ledger_balance (net of APPROVED disbursements, created_at ASC replay).

**Fidelity points**: OCC on expected_claim_version (412) ordered AFTER state check (409); version bumps only on 4 workflow transitions; multi-hop cascades (TOTAL_LOSS curtails PENDING rentals; subrogation resolve creates `-recovered` disbursement + recomputes ledger; void restores ledger); policy-period overlap rejects adjacency vs rental overlap allows adjacency. Self-smoke-tested PASS.

## Step 7: Test and iterate to green — 2026-06-02T16:04:44.000Z

All 8 parallel rounds green (71/71 each). Total dropped from 72 to 71 because one test was deleted.

**Iterations run:** 1 diagnostic iteration (2 sweeps total: baseline + verification). Baseline showed 2 deterministic failures in all 8 rounds; after fixes all 8 rounds pass 71/71.

**Tests deleted (1):**
- `test_occ_assign_adjuster_stale_version_rejected` (test_suite/test_02_coverage_and_lifecycle.py) — **ERROR PRECEDENCE / state-guard SILENCE collapse**. PRD §3.6 verbatim orders the state check before the OCC check for "every transition endpoint in the system" ("After the state check comes the concurrency check on `expected_claim_version`"). The test drives the claim to `UNDER_REVIEW` via a successful first assign (which bumps version), then issues a second assign carrying the now-stale pre-assign version. A PRD-faithful implementation checks state first — and since the claim is no longer `COVERAGE_VERIFIED`, it returns `ERR_INVALID_STATE`, never reaching the OCC check that would yield `ERR_STALE_CLAIM_VERSION`. Per §2.4, version advances only on transitions that simultaneously move the claim out of `COVERAGE_VERIFIED`, so a stale version on an assignable (`COVERAGE_VERIFIED`) claim is structurally unreachable. `ERR_STALE_CLAIM_VERSION` on assign-adjuster is not uniquely derivable (in fact unreachable). Scaffold rule: `Corner/cross_cutting_complexity_layers/occ_assign_adjuster_stale_version_rejected`.

**Fixes applied to test_suite/ (1):**
- `test_send_demand_requires_parent_claim_settled` (test_suite/test_05_subrogation_and_ledger.py) — **STEP 2 test-bug fix (assertion mis-targeted the wrong operation)**. The test asserted that *opening* a subrogation case (`POST /subrogation-cases`) on a non-SETTLED claim is rejected with `ERR_INVALID_STATE`, but PRD §3.10 attaches no error-bearing state precondition to the open operation — the "settled claim" phrasing on open is descriptive narrative. The genuine, PRD-verbatim rule (and the rule named by the test's own design tag `Difficulty/cross_entity_state_dependency/send_demand_requires_parent_claim_settled`) is on **send-demand**: "A specialist sends the demand... this requires that the parent claim is `SETTLED`." Redirected the assertion to open the case on the UNDER_REVIEW claim (which PRD permits) and then call `send-demand`, which the implementation correctly refuses with `ERR_INVALID_STATE`. More faithful, not less. Happy-path complement (`test_send_demand_on_settled_claim_succeeds`) already covered the positive case.

**Fixes applied to test_helpers/:** none.

**Fixes applied to implementation/:** none — both failures were test-artifact issues (one unreachable-precedence assertion, one mis-targeted operation); the implementation was PRD-faithful in both the state-before-OCC ordering and the placement of the SETTLED gate on send-demand.

## Step 8: Finalize PRD — 2026-06-02T16:06:58.000Z

**No edits warranted.** `PRD_FINALIZED.md` is a verbatim copy of `PRD.md` (249 lines each, 0% delta, byte-identical).

Both `<step_7_diff>` items are pure test-artifact issues (Step 7 applied 0 implementation fixes). Neither reveals a PRD silence or PRD/impl mismatch.
- **Item 1 (deleted OCC-on-assign test):** PRD §3.6 already pins state-before-OCC ordering verbatim and §3.3 pins the COVERAGE_VERIFIED precondition; impl (`routes/claims.py:165-168`) matches. Deleted assertion targeted a structurally unreachable path. No PRD edit.
- **Item 2 (re-targeted send-demand test):** PRD §3.10 already says send-demand requires parent claim SETTLED (impl `routes/subrogation_cases.py:94-95`); open imposes no error-bearing state gate (impl `create_subrogation_case` 25-45). PRD prose already matches impl. No PRD edit.

Pre-edit enumeration (no edits made, but performed): state-vs-OCC ordering uniform across assign/decide/settle (`claims.py:165→168`, `203→206`, `298→300`); SETTLED gate placement only on send_demand among the 4 subrogation operations. Consistent throughout.

## Step 9: Complete PRD — 2026-06-02T16:11:45.000Z

Full PRD-vs-implementation scan. Base = `PRD_FINALIZED.md` (249 lines, 42,220 chars) → `PRD_COMPLETED.md` (249 lines, 43,568 chars); char delta **+1,348**, line count unchanged.

**Counts:** 7 ambiguity-pins, 0 mismatch-revisions. (Impl matched PRD prose wherever PRD already pinned a behavior; gaps were silences on error codes / edge-case defaults, never contradictions.)

**Changes:**
- §3.1 Onboarding — insert — ambiguity — duplicate `policy_number` rejected with `ERR_INVALID_REQUEST`. — routes/policies.py:46
- §3.3 Assigning the Adjuster — insert — ambiguity — inactive target adjuster or already-assigned claim rejected with `ERR_INVALID_STATE`. — routes/claims.py:170-173
- §3.5 Total-Loss Evaluation — insert — ambiguity — `repair_total_cents` snapshots 0 when no SUBMITTED estimate exists; acting adjuster's X-User-ID must resolve to an Adjuster (`ERR_NOT_FOUND`, before senior-tier gate). — routes/total_loss_evaluations.py:29-37
- §3.6 repair branch — insert/revise — ambiguity — REPAIR decision restricted to ClaimsAdjuster (else `ERR_FORBIDDEN_ROLE`); `ERR_NO_SUBMITTED_ESTIMATE` also raised when a positive total-loss evaluation exists. — routes/claims.py:197-198, 219-221
- §3.6 total-loss branch — insert — ambiguity — TOTAL_LOSS decision restricted to TotalLossAdjuster (else `ERR_FORBIDDEN_ROLE`). — routes/claims.py:199-200
- §3.7 Rental Reimbursement — insert — ambiguity — rental approve/reject precondition failures rejected with `ERR_INVALID_STATE`. — routes/rental_reimbursements.py:104-113, 135-143
- §3.9 Settlement and the Ledger (close) — insert — ambiguity — close precondition violation rejected with `ERR_INVALID_STATE`, subrogation condition checked before rental. — routes/claims.py:327-336

**Cross-references confirmed clean (no edit):** total-loss settlement uses claim's `salvage_value_cents`; matched-coverage selection from VERIFIED verification; verify-coverage not version-bumping (§2.4); subrogation resolve state/ordering + `recoverable_cents` validation; no flat `GET /disbursements` list endpoint.

---

## PIPELINE COMPLETE

All 9 steps finished. Final state: **8/8 stability rounds green at 71/71**. Artifacts: SCAFFOLD.yaml + 2 design YAMLs, PRD.md → PRD_FINALIZED.md (verbatim) → PRD_COMPLETED.md (+7 ambiguity-pins), test_helpers/ + test_suite/ (71 tests, 1 deleted from original 72), workspace/implementation/ (41 endpoints, Flask, in-memory), results.{1..8}.json all passing.

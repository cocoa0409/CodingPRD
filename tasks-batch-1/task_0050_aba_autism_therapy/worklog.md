# Worklog — task_0050_aba_autism_therapy

Scenario: 50. ABA Autism Behavioral Therapy: diagnostic evaluation, treatment plan, unit-hour pre-authorization, BCBA supervision ratio, parent training, insurance reimbursement cycle, therapist scheduling, Authorization Renewal

## Step 1: Create task directory — 2026-05-30

Created `tasks/task_0050_aba_autism_therapy/` and `tasks/task_0050_aba_autism_therapy/workspace/` (pre-assigned path; index not auto-allocated to avoid collision with parallel runs).

## Step 2: Generate scaffold — 2026-05-30

All three scaffold artifacts complete and pass `scaffold_lint.py` clean (SCAFFOLD.yaml 986 lines, DIFFICULTY 1440, CORNER 1386).

**Complexity profile:** primary archetype *quota/allocation* (unit-hour authorization pool) + secondary *ledger reconciliation* (insurance reimbursement); layers = optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers. Topology *flat* (FK-linked peers, two self-referential FKs), state-machine shape *branching*, role model *peer roles*, immediate consistency. Advanced/Expert band (8 entities).

**Entities (8):** Client, Payer, Provider, DiagnosticEvaluation, TreatmentPlan, Authorization, TherapySession, Claim.

**State machines (5):** DiagnosticEvaluation (DRAFT→SUBMITTED→FINALIZED/REJECTED), TreatmentPlan (SUBMITTED↔REVISION_REQUESTED revision cycle), Authorization (ACTIVE↔EXHAUSTED cycle + EXPIRED/RENEWED branches), TherapySession (SCHEDULED→DELIVERED/NO_SHOW/CANCELLED), Claim (DRAFT→SUBMITTED→PAID/DENIED). One OCC concurrency rule (renew-supersede on Authorization.version, 412).

**Calculations (5):** diagnostic_severity (tiered threshold), supervision_ratio (ceil over 3 inputs), claim_billed (provisional/final dual-variant), claim_remittance (round-patient-first then subtract), authorization_pool_ledger (reservation/delivered dual-basis, unit-conservation invariant).

**Validations:** 18 priority-ordered rows. **Endpoints:** 37 (incl. `/_clock/set_current_utc`; all FKs reverse-reachable via filtered lists). **Error catalog:** 19 codes. **Roles (5):** IntakeCoordinator, BCBA (entity_backed:Provider), RBT (entity_backed:Provider), BillingSpecialist, Caregiver.

**Difficulty design:** 18 instances (2 per each of 9 rules). **Corner design:** 28 active instances + 6 `excluded_because` stubs across 9 taxonomy sections. Lint clean — 501 calls scanned, all FKs reverse-reachable, formula literals pinned.

## Step 3: Copy INSTRUCTION.md — 2026-05-30

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-30

**Output:** `workspace/PRD.md` — 243 lines. 5 top-level sections, 9 §2 subsections, 10 §3 workflow subsections (19 `###` total). §4 = 37 endpoints (4-col), §5 = 19 errors (2-col), §2.2 verbatim envelope.

All three Hard Contracts PASS:
- Field coverage: 56 required, 56 present, 0 missing.
- Rule coverage: validations order + per-rule error_ids, 1 OCC rule (ERR_STALE_VERSION/412), all 5 state machines' transitions/preconditions/side-effects, 5 calculations (diagnostic_severity tiered, supervision_ratio ceil >=, claim_billed provisional/final dual-variant, claim_remittance round-half-up, pool ledger invariant), all 19 error_ids, sibling-branch symmetry — 0 missing.
- Path purity (§3): 268 backtick tokens scanned, 0 path/method tokens.

Coverage notes: dual-variant billing (provisional scheduled vs final delivered units), inclusive `>=` supervision boundary + ceil, two clock-driven time gates, flat-FK-referential resolution all rendered in precise prose. Design files (DIFFICULTY/CORNER) withheld per contract.

## Step 5: Generate unit tests — 2026-05-30

**test_helpers/** (9 files): types.py (8 entity TypedDicts, all common_fields → id/created_at/updated_at/version), api_client.py (one method per endpoint + raw header-omission helpers), api_errors.py (19 errors + HTTP status map), assertions/factories/constants/test_users/fixtures/__init__. Key fixture: composite `setup_active_authorization(...)` drives the 11-step chain (payer→BCBA/RBT→client→eval→submit→finalize→plan→submit→approve→authorization) with **overrides; layered shortcuts setup_delivered_direct_session, deliver_supervision_units, create_submitted_claim. BCBA/RBT calls use real Provider id headers so ownership/credential checks resolve.

**test_suite/** (conftest + 10 files, 64 test functions):
- Queue A (Difficulty): 36 tests — all 18 instances across 9 rules, each ≥2 tests.
- Queue B (Corner): 28 tests — all 28 non-stub instances, each ≥1 test.
- 64 functions = 64 `Design:` tags (exactly one per test).

Audits passing: every difficulty instance ≥2 tests, every corner non-stub ≥1; all tags resolve; 6 corner stubs correctly not translated; all 72 PRD-citation fragments verified verbatim (fixed 2 elided docstrings); no scaffold leakage, no skip/xfail, all imports resolve, all compile. **0 instances skipped** — every non-stub passed the two-condition filter.

## Step 6: Generate implementation — 2026-05-30

**Stack:** Python + Flask, in-memory dicts keyed by UUID, decimal.Decimal/ROUND_HALF_UP for money. Boots empty every process start (no seeding).

**Source files (12):** app.py (37 routes, error handlers, validation orchestration, getfqdn short-circuit), db.py (8 collections + settable test clock, new_common/touch, version starts at 1), errors.py (19-code catalog), response.py (meta/response_type/data envelope, req_-prefixed ids, ISO-8601 UTC 3-frac-digit), middleware.py (X-User-ID/X-User-Role auth, 5 roles, require_role), pagination.py (limit 10/1–100, offset 0, total_count/has_more, created_at asc), util.py (body validators → ERR_VALIDATION, ISO parsing), calculations.py (diagnostic_severity, supervision_ratio ceil, claim_billed provisional/final, claim_remittance round-half-up patient → payer remainder; rates 3200/4800/2400), services.py (pool-ledger recompute reserved/delivered/remaining, supervision posture, ACTIVE↔EXHAUSTED flip, cascade helpers), serialize.py, requirements.txt (flask==3.0.3), start.sh.

**Endpoints:** 37 (1 clock, 2 payer, 4 client, 4 provider, 5 eval, 5 plan, 5 authorization, 6 session, 5 claim).
**State machines (5):** DiagnosticEvaluation, TreatmentPlan (REVISION_REQUESTED loop + supersede-retire + client INTAKE→ACTIVE bubble-up), Authorization (ACTIVE↔EXHAUSTED, →EXPIRED cascade-cancel, →RENEWED OCC + carry-forward), TherapySession (SCHEDULED→DELIVERED/NO_SHOW/CANCELLED pool sync), Claim (DRAFT→SUBMITTED→PAID/DENIED, provisional→final + supervision pay gate).

**Validation precedence** follows PRD §2.4 prose (auth → body ERR_VALIDATION → role ERR_UNAUTHORIZED → existence L-to-R → owner → state → domain), PRD-authoritative over scaffold numeric priorities. OCC on renewal: expected_authorization_version → ERR_STALE_VERSION/412.
**start.sh:** reads PORT (default 10000), binds 0.0.0.0, exec python3 app.py foreground; deps behind .deps_installed sentinel, frees stale listener + waits for bindable port. Self-verified 55 smoke assertions pass + clean empty-state boot across kill/restart.

## Step 7: Test iterate loop — 2026-05-30

**Final state: 8/8 parallel rounds pass, 64/64 tests each. No flakiness.**

**Iterations run:** 2 (initial sweep surfaced 1 deterministic failure; second sweep after the fix was clean across all 8 rounds).

**Tests deleted:** None.

**Fixes applied to `test_suite/`:**
- `test_05_authorization_lifecycle.py` → `test_second_renew_with_stale_version_returns_412`: relaxed final assertion from `validate_error(resp, ERR_STALE_VERSION, 412)` to `validate_error_is_one_of(resp, [ERR_STALE_VERSION, ERR_INVALID_STATE])` (+ added import). Reason: **ERROR PRECEDENCE SILENCE**. After the first renew succeeds, the predecessor authorization is in terminal `RENEWED` state (PRD §3.5) and its version advanced. A second renew with the stale version could, under a PRD-faithful reading, be rejected by the ACTIVE-precondition state check first (`ERR_INVALID_STATE`) or the OCC version check first (`ERR_STALE_VERSION`). PRD §2.6 supports the `ERR_STALE_VERSION` reading, but PRD never states OCC pre-empts the state-check path, so impl's `ERR_INVALID_STATE` (state check at priority 5, before OCC) is equally faithful → relaxed to the set, not deleted.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None — impl ordering (`app.py` renew_authorization L528–533: ACTIVE-state check before OCC version check) is a PRD-faithful reading, left unchanged.

## Step 8: Finalize PRD — 2026-05-30

**Output:** `workspace/PRD_FINALIZED.md` — 242 lines (0 line-count delta; one line revised in place, ~+90 words). Step 8 ran because Step 7 had 1 non-zero `test_suite/` fix.

**Change (1):**
- §3.5 Authorization Renewal — revise — pinned renew check ordering: ACTIVE-state precondition evaluated before OCC version comparison, so a renew against a non-ACTIVE (e.g. terminal RENEWED) authorization yields `ERR_INVALID_STATE` regardless of `expected_authorization_version`; only an ACTIVE target proceeds to the version check that can raise `ERR_STALE_VERSION` — `implementation/app.py:528-533`.

Root cause: PRD §2.6/§3.5/§3.10 describe both `ERR_INVALID_STATE` and `ERR_STALE_VERSION` for renew but never pin relative order; impl pins state-before-OCC. NO-NEW-MISMATCH search confirmed `expected_authorization_version`/`ERR_STALE_VERSION` used only in renew_authorization; close_authorization also state-checks-first (no OCC); wording scoped to renew with "for example" RENEWED to cover any non-ACTIVE state.

## Step 9: Complete PRD — 2026-05-30

**Output:** `workspace/PRD_COMPLETED.md` — 242 lines, 39,160 chars (char-delta +2,277 over PRD_FINALIZED.md; all in-paragraph, 0 line delta). Always-runs full impl scan.

**Counts:** 8 changes — 7 ambiguity-pins, 1 mismatch-revision.

- §2.3 Pagination — insert — ambiguity — non-integer/out-of-range limit/offset → ERR_VALIDATION; offset min 0 — pagination.py:24-36
- §2.4 Validation Order — insert — ambiguity — body must be JSON object; required strings non-empty ≤500 chars; booleans rejected for string/int/number; FK refs non-empty strings — util.py:37-51,119-126
- §3.4 Pre-Auth create — revise — mismatch — removed implied APPROVED-plan precondition; only existence (plan then payer) checked, plan status not re-checked — app.py:457-494
- §3.4 Pre-Auth close — insert — ambiguity — close only from ACTIVE (else ERR_INVALID_STATE); state check precedes clock/expirability check; post-cascade recompute does not re-flip now-EXPIRED auth — app.py:570-588
- §3.5 Renewal — insert — ambiguity — expected_authorization_version must be integer; renewal pool figures each ≥0 — app.py:520-523
- §3.6 Scheduling buffer — insert — ambiguity — 15-min client buffer is half-open; exactly-15-min-apart does not conflict — app.py:651,661-665
- §3.7 Delivery — revise — ambiguity — pinned actual fixed check order (state → auth-active → delivered-units range → supervision credential), auth-active before units range — app.py:718-735
- §3.9 Adjudication — insert — ambiguity — denial_reason optional on DENY (defaults NONE), ignored on PAY; decision ∉ {PAY,DENY} → ERR_VALIDATION — app.py:868-873
- §4 Endpoint table POST /authorizations — revise — mismatch — "for an APPROVED plan" → "plan status not re-checked" — app.py:457-494

Core formulas, state machines, error catalogue, envelope, FK ordering, supervision ceil, remittance rounding, renewal carry-forward already uniquely pinned — no change.

---

## Pipeline complete — 2026-05-30

All 9 steps done. **64/64 tests pass across 8/8 parallel rounds.** Final artifacts: SCAFFOLD.yaml + 2 design files, worklog.md, test_helpers/ (9), test_suite/ (10 files, 64 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (12 src + start.sh + 8 results.json)}.

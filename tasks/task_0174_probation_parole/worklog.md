# Worklog — task_0174_probation_parole

## Step 1: Create task directory — 2026-06-05T13:40:36.000Z

Created `tasks/task_0174_probation_parole/` and `tasks/task_0174_probation_parole/workspace/`.

## Step 2: Generate scaffold (Expert band) — 2026-06-05T14:11:04.000Z

(First spawn hit a stream idle timeout having written 0 files; re-spawned fresh with incremental-write guidance — succeeded.)

Generated a complete, lint-clean Expert-band scaffold for **Probation & Parole Case Management**. Three files written, all valid YAML, `scaffold_lint.py` VERDICT: clean lint (339 §1.8+§1.9 calls conform to §1.5; all 13 FK reverse-reachabilities resolved):
- `SCAFFOLD.yaml` (§1.0–§1.7, plus `concurrency_rules`)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Complexity profile:** primary archetype compliance/audit, secondary posture-driven gating; layers = dual-variant calc, cascading side effects, rate/threshold triggers, optimistic concurrency; hybrid topology; posture-driven state-machine shape; segregation-of-duties role model; immediate consistency.

**Scaffold contents:**
- **13 entities**: Officer, Supervisee (aggregate root with computed posture/balances), RiskAssessment, SupervisionCondition, CheckIn, DrugTest, Violation, Sanction, FinancialObligation (self-referential), Payment (`common_fields:false`), CourtReport, InterstateTransfer, EarlyTermination
- **8 state machines**: Supervisee (cyclic revocation/abscond rebounds + posture), RiskAssessment (adopt/supersede), SupervisionCondition (level-gated, suspend/reactivate), CheckIn, Violation (branching fork-join + appeal compensation), FinancialObligation, InterstateTransfer, EarlyTermination; **1 concurrency rule** (OCC on `Supervisee.version` for transfer create)
- **8 calculations**: lsi_r_scoring (dual variant), restitution_payoff_quote (forward vs chronological dual variant), sanction_matrix (combinatorial mode-a), compliance_rate (combinatorial mode-b, pinned rounding order), checkin_punctuality, violation_points, payment_waterfall, early_termination_eligibility
- **21 validations** (priority-ordered, spanning auth→existence→state→safety→referential→temporal→fiscal)
- **85 endpoints** (nested business surface + flat top-level reverse-reachability GETs + `/_clock/set_current_utc` test-driving endpoint)
- **22 errors**
- **3 roles**: Officer (entity_backed), SupervisingJudge (opaque), CompactAdministrator (opaque)

**Difficulty design (§1.8):** all 9 §0.5 rules × 2 instances = 18 instances, each with executable `setup_api_calls`/`trigger`/`assert` chains and pre-computed literal expected values (LSI-R MEDIUM=28 vs override MAXIMUM; payoff 15000 chronological vs 30000 forward; sanction JAIL_SHOCK imposed_days=2 at cumulative 10; compliance 66.7; OCC 412).

**Corner design (§1.9):** 35 active instances + 4 `excluded_because` stubs across 8 sections; stubs cite their covering §1.8 instances by name.

**Quality gates verified:** no forbidden concurrency vocabulary; file split honored; all grounds references resolve; instance names unique across both design files; all calculation tie-breaks use `created_at ASC` (never `id`).

File sizes: SCAFFOLD.yaml 2052 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1027 lines, SCAFFOLD_CORNER_DESIGN.yaml 1335 lines.

## Step 3: Copy shared files — 2026-06-05T14:11:31.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0174_probation_parole/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-05T14:20:23.000Z

**Output:** `workspace/PRD.md` — 367 lines, ~9,100 words.

**Section list:**
- §1 Introduction
- §2 Global Specifications (11 subsections): RBAC; API Response Structure (verbatim §2.2 block); Pagination; Common Resource Properties and Versioning; Nested Resource Retrieval and Existence Ordering; Optimistic Concurrency Control; Supervision-Level Posture and Ordering; Monetary Ledgers and Two Accounting Conventions; Risk Scoring (Actuarial Band and Clinical Override); Cascading Side Effects and Hierarchical Consistency; Validation Ordering
- §3 Business Logic (11 subsections, lifecycle-organized): Registering Officers/Opening a Case; Risk Assessment & Posture; Court-Ordered Conditions & Posture Gate; Check-Ins/Punctuality/Drug Testing; Violations/Adjudication/Sanction Matrix; Financial Obligations/Fee Accrual/Payment Allocation; Absconding/Revocation/Closure; Interstate Transfers; Early Termination; Compliance Reporting/Payoff Quotes/Logical Clock; Terminal-Status Protection
- §4 Endpoint Definitions (85 endpoints, 4-column table)
- §5 Error Code Catalogue (22 errors, 2-column table)

**Hard Contracts:** Contract 1 (field coverage) PASS — 62/62 entity fields, 49/49 endpoint inputs; Contract 2 (rule coverage) PASS — 8 state machines, 8 calculations, 1 OCC rule, 22 errors, sibling-branch symmetry; Contract 3 (path purity §3) PASS — 0 path tokens in 553 backtick tokens.

**Confirmation:** Neither design file read/opened/grepped/referenced. Only SCAFFOLD.yaml + SKILL.md + §2.2 source + example PRD consulted. §2.2 emitted verbatim with placeholders preserved. File ends at §5, no audit footer.

(Note: the first concurrent launch of Steps 5+6 was interrupted by a session limit having written 0 files; re-launched concurrently fresh after reset — both succeeded.)

## Step 5: Generate unit tests — 2026-06-05T18:02:50.000Z

**Files written** — Stage 1 `test_helpers/` (9 files): types.py (18 enums + 13 entity TypedDicts; Payment omits version/updated_at per common_fields:false), api_client.py (~70 methods incl. flat reverse-reachability GETs + /_clock driver + connection-reset retry shim), api_errors.py (ApiErrorId enum + HTTP status map), assertions.py (per-entity + assert_supervisee_invariants; assert_payment enforces no-version/no-updated_at), factories.py (input-only payload factories + domain_scores_for_total / domain_scores_uniform LSI-R helpers), constants.py (LSI-R bands, sanction tiers, violation points, thresholds), test_users.py (Officer entity_backed via make_officer_headers(officer_id); SupervisingJudge & CompactAdministrator opaque), fixtures.py (composite setup tiers), __init__.py barrel.

Stage 2 `test_suite/` (9 files): conftest.py + test_01–test_08, **72 tests**.

**Coverage (design-index-only):** Queue A (Difficulty) all 18 instances, each ≥2 tests (36+ tests); Queue B (Corner) all 35 non-stub instances ≥1 test; 4 excluded_because stubs correctly NOT translated (all 4 cross-refs resolve to real difficulty instances).

**Instances skipped:** none — every non-stub instance passed the PRD-first two-condition filter.

**Verification:** pytest collects all 72 tests cleanly; py_compile passes; every docstring carries exactly one Design: tag; no skip/xfail/skipif anywhere; verbatim-citation sweep passed (2 endpoint-table-titular + 1 bracket-spliced citation rewritten to rule-bearing §2.1/§3.5/§3.11 prose).

## Step 6: Generate implementation — 2026-06-05T18:02:50.000Z

Built complete Python + Flask implementation in `workspace/implementation/`. All 85 PRD §4 endpoints implemented. **32 files total.**

**Foundation:** start.sh (guarded pip install, `exec python3 app.py`), requirements.txt (flask 3.0.3), app.py (blueprint registration + error handlers), db.py (in-memory dicts), errors.py (22-error catalogue), response.py (envelope helpers), middleware.py (auth + RBAC), clock.py (logical clock), timeutil.py (ISO 8601 + whole-month math), calculations.py (pure calc rules), serialize.py.

**Routes (15 blueprints):** officers, supervisees, risk_assessments, conditions, check_ins, drug_tests, violations, sanctions, obligations, payments, court_reports, transfers, early_terminations, flat (22 reverse-reachability GETs), clock_route.

**Services:** common.py (lookups, body validation, pagination, balance/point recompute), supervisee.py, risk.py, violation.py, payment.py.

**State machines** in per-resource service modules: supervisee lifecycle (activate/abscond/return/refer-revocation/revoke/reinstate/complete w/ condition cascades), risk-assessment adopt (3-depth supersede→posture-recompute→force-suspend), violation sustain/appeal (sanction matrix + REVOCATION_PENDING flip + appeal compensation), transfer accept (bubble to TRANSFERRED_OUT), early-termination grant. Each cascade-touched child gets version bump + updated_at (§2.10/§2.4).

**Calculations** centralized in calculations.py: LSI-R scoring (actuarial band + clinical-override raise-only), sanction matrix (JAIL_SHOCK days = (total-9)*2), compliance rate (pinned order: ratio*100 then half-up to 1dp via Decimal), punctuality (inclusive <= boundary), fee accrual (whole-month floor), payoff projection vs posted-balance divergence, payment waterfall (RESTITUTION_FIRST / OLDEST_FIRST, created_at ASC tie-break never id), early-termination eligibility. Money in integer cents.

**Confirmed:** start.sh reads $PORT (default 10000), binds 0.0.0.0, runs foreground via exec; storage in-memory only (dicts keyed by id, no SQLite/JSON/disk); store starts empty every boot — no seeding/preloading.

## Step 7: Run tests and iterate — 2026-06-05T18:08:04.000Z

All 8 parallel rounds pass with 72/72. Clean sweep.

**Iterations run:** 2 (baseline sweep, then one fix + confirming sweep).

**Tests deleted:** None. The single failing test was PRD-faithful; no deletions warranted.

**Fixes applied to test_helpers/:**
- `test_helpers/fixtures.py` — `open_supervisee()`: promoted `docket_number` from `**overrides` to an explicit named parameter (defaulting to the auto-generated `_next_docket()`). Previously the helper unconditionally injected `docket_number=_next_docket()` while also forwarding `**overrides`, so any caller passing an explicit `docket_number` (e.g. to force a duplicate) triggered `TypeError: create_supervisee_payload() got multiple values for keyword argument 'docket_number'`. Pure test-helper bug; fix lets caller-supplied docket take precedence.

**Fixes applied to implementation/:** None. Implementation already correct.

**Failing test diagnosed:** `test_07_crud_and_validation.py::test_duplicate_docket_number_rejected` — failed in all 8 baseline rounds with the keyword-collision TypeError. PRD §3.1 verbatim-covers and uniquely determines the rule ("Docket numbers are unique across all supervisees; a duplicate docket_number is rejected with ERR_DUPLICATE_KEY (HTTP 409)."), so it stayed; fix applied to the offending fixture.

**Final state:** 8/8 parallel rounds green, 72/72 tests passing each round.

## Step 8: Finalize PRD — 2026-06-05T18:10:19.000Z

(Not skipped: Step 7 had 1 test_helpers/ fix, so the skip condition — 0/0/0/0 — was not met.)

**Outcome: No PRD edits. PRD_FINALIZED.md is a byte-identical copy of PRD.md** (367 lines each, 0% delta, MD5 `192fa47ee5c80a8bcb1d29d61436fc5a` on both).

**Per-item analysis of <step_7_diff>:** the diff contained exactly one change — the test_helpers/fixtures.py `open_supervisee()` keyword-arg collision. Pure Python keyword-collision bug in the test helper; reveals no PRD silence and no PRD/impl mismatch. The asserted behavior (docket uniqueness → ERR_DUPLICATE_KEY / 409) is already verbatim in PRD §3.1 (line 144) and implemented correctly at implementation/routes/supervisees.py:80-83.

**Pre-edit search log (mandatory enumeration before concluding "no change"):**
- (a) Subject: docket-number uniqueness and ERR_DUPLICATE_KEY (409).
- (b) Impl paths: routes/supervisees.py:55,64,82-83,89 (only docket code path); routes/officers.py:39-42 (parallel ERR_DUPLICATE_KEY badge-uniqueness sibling); errors.py:24 (ERR_DUPLICATE_KEY = 409). All match PRD §3.1/§5 exactly.
- (c) Wording adjustment: none — no edit warranted.

## Step 9: Complete PRD — 2026-06-05T18:16:03.000Z

Full PRD-vs-implementation scan. Source: PRD_FINALIZED.md (existed) → PRD_COMPLETED.md.

**Line counts:** 367 → 367 (unchanged; all edits in-paragraph). **Char counts:** 65,047 → 66,623 (+1,576).

**Change counts:** 7 total — 4 ambiguity-pins, 3 mismatch-revisions.

- §2.3 Pagination — insert — ambiguity — out-of-range/non-integer limit/offset are validated, not clamped, → ERR_INVALID_REQUEST (400) — services/common.py:101-110.
- §3.2 Risk Assessment override — revise — mismatch — invalid override_level enum → ERR_INVALID_OVERRIDE (422), superseding general enum well-formedness check — services/risk.py:38-40.
- §3.3 Condition activation — revise — ambiguity — precondition order (condition status → supervisee status → level gate); supervisee-not-ACTIVE → ERR_INVALID_STATE; level gate last (ERR_LEVEL_TOO_LOW_FOR_CONDITION) — routes/conditions.py:99-109.
- §3.4 Mark-missed — revise — mismatch — SCHEDULED state check (ERR_INVALID_STATE) precedes window-closed check (ERR_WINDOW_NOT_CLOSED), reversing prose order — routes/check_ins.py:141-146.
- §3.8 Transfer accept — revise — ambiguity — check order (transfer REQUESTED → supervisee ACTIVE → high-risk); non-ACTIVE supervisee → ERR_INVALID_STATE before high-risk check — routes/transfers.py:110-116.
- §3.9 Early-termination grant — insert — ambiguity — eligibility checked before supervisee-ACTIVE (ineligible → ERR_NOT_ELIGIBLE_FOR_TERMINATION; eligible-but-not-ACTIVE → ERR_INVALID_STATE) — routes/early_terminations.py:93-98.
- §3.10 Payoff quote — insert — ambiguity — omitted as_of defaults to server current clock instant; echoed as_of is full ISO 8601 UTC timestamp w/ three fractional digits, not bare date — routes/supervisees.py:211-234.

Verified already-pinned/consistent (non-changes): sustain validation order (§3.5: FILED → closed-supervisee → segregation), payment/obligation waterfall ordering, drug-test check_in_id-only linkage + flat filters, envelope/timestamp/version conventions, §3.11 closed-supervisee guard set.

---

## PIPELINE COMPLETE — task_0174_probation_parole

All 9 steps finished. Final 8-round parallel stability sweep: **8/8 rounds green, 72/72 tests passing each round.** Deliverables present: SCAFFOLD.yaml (+ 2 design indices), workspace/PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, test_helpers/, test_suite/ (72 tests), workspace/implementation/ (32 files, Flask + in-memory).

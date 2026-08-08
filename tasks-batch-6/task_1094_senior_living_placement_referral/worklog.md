# Worklog — task_1094_senior_living_placement_referral

Scenario: Senior-Living Placement & Referral (A Place for Mom style): family inquiry & needs/budget assessment, community match & tour scheduling, care-level & availability, community-paid referral-fee & move-in confirmation, follow-up & satisfaction, advisor & caseload, financial/VA-benefit guidance, reporting

Difficulty: Expert

## Step 1: Create task directory — 2026-07-24T02:58:00.000Z

Skipped the directory scan — output folder `tasks/task_1094_senior_living_placement_referral` was pre-assigned. Created `workspace/`.

## Step 2: Generate scaffold — 2026-07-24T03:43:00.000Z

All three artifacts are written and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1094_senior_living_placement_referral/`):
- `SCAFFOLD.yaml` (§1.0–§1.7, 2811 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key)

**Profile** — Expert; primary archetype `workflow_orchestration` + secondary `ledger_reconciliation`; layers dual-variant calc / cascading side effects / OCC / selector policy; topology **flat** (prioritized), shape **cyclic** with a parallel-dimension entity, role model **segregation_of_duties** (prioritized).

**Counts**
- Entities: **14** (Family, Advisor, Community, CommunityInventory, Inquiry, NeedsAssessment, Match, Tour, Placement, ReferralInvoice, FeeLedgerEntry, BenefitGuidance, SatisfactionSurvey, CaseloadAssignment)
- State machines: **9**. Non-linear: **NeedsAssessment** (cyclic DRAFT→SUBMITTED→REVISION_REQUESTED→DRAFT), **Match** (two cycle edges: SHORTLISTED↔TOUR_SCHEDULED and TOURED→SHORTLISTED), **ReferralInvoice** (cyclic ISSUED↔DISPUTED, capped at MAX_DISPUTE_ROUNDS=2), **Inquiry** (cyclic MATCHING/TOURING→ON_HOLD→MATCHING), **Placement** carries two parallel axes (residency_status × billing_status declared as two machines). Plus Tour, CaseloadAssignment, BenefitGuidance.
- Calculations: **11** (incl. 2 dual-variant: `referral_fee` estimated/final on money, `advisor_load_index` headcount/acuity-weighted on staffing; `advisor_auto_selection` pins eligibility/ranking/tie-break/empty-pool fallback using `created_at`, never `id`)
- Validations: **36** (ordered 1–36)
- Endpoints: **69** (incl. `POST /_clock/set_current_utc`, default clock `2026-05-01T00:00:00Z`)
- Errors: **50**
- Roles: **6** (PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family — all with `identity:`)
- Concurrency rules: **2** OCC (`expected_inventory_version` on POST /placements, `expected_assessment_version` on POST /benefit-guidances)

**§1.8**: 9 rule_ids × **2 instances = 18**. **§1.9**: **61 instances** across 10 section groups (53 with full recipes + 8 `excluded_because` stubs pointing at named §1.8 instances).

**Verification performed**
- `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (976 calls scanned)
- Custom checks: zero duplicate instance names; zero unbound `${var}` in payloads/`as_user_id`/paths/asserts; all `grounds:` resolve; all 50 errors triggered by at least one instance; all `excluded_because` targets exist; no forbidden concurrency vocabulary in any file.
- Every formula-derived assert literal was computed with a Python/Decimal `round_half_up` script — e.g. `priority_score == 70.59` (round-then-sum; sum-then-round gives 70.60, the deliberate mode-(b) trap), `fit_score == 94.47`, `estimated_fee_cents == 492500` vs `final_fee_cents == 180583`, VA award `276000` → ceiling `848000` → fit `97.00`, load indices `0.6667` vs `0.4087`, min-fee clamp `150000`, dispute-round fees `166137` → `162525`, composite `79.00`.

**Orchestrator post-checks**: all 3 YAML files `yaml.safe_load` cleanly; every named constant (`URGENCY_HORIZON_DAYS=90`, `RESIDENCY_CONFIRM_DAYS=14`, `MAX_DISPUTE_ROUNDS=2`, `TOUR_MIN/MAX_MINUTES=30/180`, `TRAVEL_BUFFER_MINUTES=45`, `VA_MAX_MONTHLY_CENTS` table, etc.) has a declared value. No pre-patch needed.

## Step 3: Copy shared files — 2026-07-24T03:44:33.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1094_senior_living_placement_referral/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-24T03:53:20.000Z

Generated `workspace/PRD.md` (382 lines).

<!-- RESUME NOTE 2026-07-24T11:18Z: pipeline resumed. Step 6 boot-verified: py_compile clean, 69 @bp route decorators == 69 scaffold endpoints, server boots on start.sh, /_clock/set_current_utc returns 401 without auth headers (correct — requires identity). Impl accepted as complete; not regenerated. Step 5 was partial (test_suite had only conftest.py) — resuming Step 5 to write the missing test_NN modules. -->

- Endpoints documented: 69 / 69 (§4 table)
- Error IDs documented: 50 / 50 (§5 table + prose)
- Contract 1 (Field-Name Coverage): PASS — 105 scaffold field names + all request/query/path identifiers verbatim.
- Contract 2 (Rule Coverage): PASS — 9 state machines (2 parallel Placement axes + 3 cyclic loops), 11 calculations with pinned rounding orders (round-then-sum priority vs sum-then-round fit contrasted), both OCC rules, 4-level move-in & 3-level move-out/guidance cascades, priority-ordered validation chain.
- Contract 3 (§3 Path Purity): PASS.
- Scaffold gaps flagged: None. Withheld design files not read.

## Step 5: Generate Unit Tests (RESUMED — completed) — 2026-07-24T11:40:00.000Z

Finished the partial Step 5. test_helpers/ preserved as-is (no bugs found); conftest.py left untouched. Wrote 8 test modules into test_suite/:
- test_01_reference_data.py, test_02_rbac.py, test_03_assignment_and_caseload.py, test_04_assessment_and_guidance.py, test_05_matching_and_tours.py, test_06_placement.py, test_07_billing_and_ledger.py, test_08_surveys_and_reports.py

Totals: 87 test functions, 87 Design tags (one per test); all collect cleanly, all py_compile OK, no skip/xfail markers.
- Queue A (Difficulty): 34 tests, 17 of 18 instances at >=2 tests each.
- Queue B (Corner): 53 tests, all 53 non-stub instances at >=1 test each; all 8 excluded_because stubs correctly emit no tests.

Skipped design instances: 1 (unique-derivability gap):
- Difficulty priority_pair_validation_conflict/placement_match_state_error_wins_over_zero_units_fiscal_error — asserts ERR_MATCH_INVALID_STATE beats ERR_NO_UNITS_AVAILABLE on POST /placements. PRD §3.10 names no error id for a non-SELECTED match on placement creation nor pins precedence over the available_units gate; two PRD-only implementers could diverge. Paired sibling (zero-units) and tour-slot-vs-advisor precedence (§3.7, pinned verbatim) both covered.

## Step 7: Run Tests and Iterate (RESUMED — clean first sweep) — 2026-07-24T11:55:00.000Z

Orchestrator ran the stability sweep directly (impl + tests were already complete and validated on resume). Sweep run as 4 WAVES OF 2 rounds (host-saturation mitigation: 4 sibling tasks sweeping the same 8-core host concurrently), via sweep.sh (script-file, cwd-matched orphan handling — no inline bare pkill).

Result: CLEAN FIRST SWEEP. All 8 parallel rounds passed 87/87 (failed=0, errors=0, skipped=0 in every round). Baseline round also 87/87. Re-parsed all 8 results.N.json independently; grep for skip/xfail markers in test_suite/ returned none.

- Iterations run: 0 (baseline sweep passed).
- Tests deleted: 0.
- Fixes applied to test_suite/: 0.
- Fixes applied to test_helpers/: 0.
- Fixes applied to implementation/: 0.

Per skill: Step 8 SKIPPED (0 implementation fixes, 0 deletions, 0 test fixes). Step 9 runs next (always).

## Step 9: Complete PRD — eliminate residual ambiguity/mismatch — 2026-07-24T12:05:00.000Z

Generated workspace/PRD_COMPLETED.md (started from PRD.md; Step 8 skipped). 382 lines, +622 chars over PRD.md. 2 ambiguity-pins, 3 mismatch-revisions (all in-paragraph):
- §3.3 Reassignment: pinned to_advisor_id-differs → ERR_VALIDATION(422), ordered after state gate, before eligibility/caseload (routes_inq.py:132).
- §3.10 Placement gate order: impl enforces match.status==SELECTED first (ERR_MATCH_INVALID_STATE) before community-active; inserted at head of ordered list (routes_place.py:44). [NOTE: this is the exact rule the skipped Step-5 design instance asserted; impl does enforce it, PRD.md was silent, now pinned in PRD_COMPLETED.]
- §3.12 Issue-invoice gate order: impl checks invoice DRAFT (ERR_INVOICE_INVALID_STATE) before placement residency; reversed prose (routes_place.py:249).
- §3.14 Survey gate order: impl checks duplicate (ERR_DUPLICATE_SURVEY) before eligibility; also no actual_move_in_date → ERR_SURVEY_TOO_EARLY (routes_place.py:409).
- §3.14 Community-referrals report: pinned response keys accrued_fee_cents/payment_cents/clawback_cents/write_off_cents (routes_place.py:514).

All §3 formulas, cascades, OCC, ledger, RBAC already matched impl — no change.

## PIPELINE COMPLETE — 2026-07-24T12:05:00.000Z
Done-state confirmed: all 8 results.N.json = 87/87 (0 failed/errors/skipped), worklog reached Step 9, workspace/PRD_COMPLETED.md present. Steps 5→7→9 executed on resume; Step 8 skipped (clean first sweep).

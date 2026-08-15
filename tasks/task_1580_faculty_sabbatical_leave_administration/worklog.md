# Worklog — task_1580_faculty_sabbatical_leave_administration

## Step 1: Create Task Directory — 2026-08-13T23:09:00.000Z

Task directory `tasks/task_1580_faculty_sabbatical_leave_administration/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE; no index scan performed; no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T00:19:00.000Z

Scaffold generation complete. All three artifacts written and the skill's linter passes clean.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1580_faculty_sabbatical_leave_administration/`)

- `SCAFFOLD.yaml` (93 KB) — §1.0–§1.7 only; no difficulty/corner keys. Verbatim scenario, domain `faculty-sabbatical-leave`, flat topology with canonical `FK -> X.id` prefixes and full reverse-reachability.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (118 KB) — single top-level `scaffold_difficulty_design:`.
- `SCAFFOLD_CORNER_DESIGN.yaml` (154 KB) — single top-level `scaffold_corner_design:`.

## Design (maximum-difficulty tier)

- **Complexity profile**: primary archetype quota/allocation (cycle award quota + department replacement-pool waterfall), secondary temporal windowing; layers: optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers; segregation-of-duties role model; flat topology.
- **Counts**: 13 entities; 11 state machines (58 transitions — cyclic revision loops on application/plan/report, parallel `status × funding_status` dimensions on LeaveApplication, divergent branching on LeaveGrant); 11 calculations; 11 validation priority rows; 58 endpoints (incl. `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`); 49 error codes; 5 roles (3 entity-backed, 2 opaque); 2 OCC concurrency rules (coverage-plan supersede on `LeaveApplication.version`, repayment payments on `RepaymentObligation.version`).
- **Hard mechanics pinned with computed literals** (all verified by executing the formulas in Python): certified-vs-provisional eligibility (71 vs 76 months), chronological-vs-proportional repayment (66666.66 vs 66666.67 on base 100000.00/6mo/2 fulfilled), per-product-rounding composite score (10.51 vs 10.50), fellowship offset waterfall with 50%-of-gross cap (25000 + 20000, net 45000.00), exact posture thresholds (0.70 CONSTRAINED / 0.95 FROZEN via integer cross-multiplication), half-open interval adjacency, 92/184-day overlap boundary, created_at tie-breaks, quota boundary (rank == quota awarded), 3-hop cascades on complete/separate/medical-decide, and budget + credit-ledger conservation invariants.
- **§1.8**: 18 instances (9 rules × 2), each with fully structured `setup_api_calls`/`trigger`/`assert`, all placeholders bound to prior captures, OCC inputs always `${var}`.
- **§1.9**: 52 instances across all nine guide sections — 39 active recipes + 13 `excluded_because` stubs citing §1.8 instances.

## Validation results

`scaffold_lint.py` final verdict block, verbatim:

```
Coverage
  §1.5 endpoints declared:    58
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     39
  Calls scanned (§1.8+§1.9):  951

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Two lint findings were fixed during iteration (an unquoted `$.data[0].x` flow-mapping YAML parse issue; `GET /leave-applications` filter renamed to `applicant_faculty_id?` to match the FK name). A supplementary self-audit script additionally verified: all `grounds:` references resolve into §1.1–§1.7, instance names unique across both design files, every `${var}` bound by an earlier `captures:`, all `excluded_because` stubs cite real §1.8 names, all 49 errors referenced by a validation/transition, no forbidden concurrency vocabulary, and endpoint roles ⊆ RBAC table — all pass. Per instructions, no sibling `task_*/` directory was inspected.

## Step 3: Copy Shared Files — 2026-08-14T00:20:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1580_faculty_sabbatical_leave_administration/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T00:44:00.000Z

All contracts pass. The PRD is complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1580_faculty_sabbatical_leave_administration/workspace/PRD.md` — 370 lines, ~62 KB. Generated purely from the task's `SCAFFOLD.yaml` plus the doc-generator skill; the two SCAFFOLD_*_DESIGN.yaml files were not opened, and no other task directory was consulted.

**Section list:**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications: 2.1 RBAC · 2.2 API Response Structure (verified byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Common Resource Properties & Mutation Semantics · 2.5 Logical Clock & Time-Driven Sweeps · 2.6 Calendar Months, Semesters & Half-Open Windows · 2.7 Monetary Precision & Rounding · 2.8 Optimistic Concurrency Control · 2.9 Validation Order & Error Precedence
- §3 Business Logic (9 subsections, lifecycle-timeline grouping): 3.1 Departments & Replacement Pool · 3.2 Faculty Records, Accrual & Eligibility · 3.3 Application Cycle & Submission Gate · 3.4 Committee Review & Composite Score · 3.5 Coverage Plans & Budget Waterfall · 3.6 Allocation & Awards · 3.7 Non-Sabbatical Decisions & Medical Precedence · 3.8 Grant Execution (activation/fellowships/completion/curtailment) · 3.9 Obligations, Repayment & Accomplishment Reports
- §4 Endpoint Definitions (4-column table, all 58 endpoints) · §5 Error Code Catalogue (2-column table, all 49 errors)

**Coverage audit (every scaffold item → PRD passage):**
- **Entities (13/13):** Department→§3.1; FacultyMember→§3.2+§3.9; LeaveCycle→§3.3/§3.6; LeaveApplication→§3.3/§3.6/§3.7; CommitteeReview→§3.4; CoveragePlan→§3.5; LeaveGrant→§3.6–3.8; ExternalFellowship→§3.8; ServiceObligation/RepaymentObligation/RepaymentPayment/AccomplishmentReport→§3.9; AccrualLedgerEntry→§3.2 (both `common_fields: false` exceptions stated in §2.4).
- **State machines (11/11):** all transitions named with from→to states, preconditions paired with their error IDs, and every side-effect cascade expressed — including the 3-hop completion cascade, the medical-approval cancellation cascade, both separation branches (ACTIVE and ON_LEAVE), and the parallel `funding_status` dimension.
- **Calculations (11/11):** accrual (§3.2), award salary with pinned 4-step evaluation order (§3.8), fellowship waterfall with created_at stacking and 50% cap (§3.8), composite score with per-product pre-rounding and drop-lowest at 4+ reviews (§3.4), allocation ranking with tie-break chain and inclusive quota boundary (§3.6), coverage cost provisional/final variants (§3.5/§3.8), posture with exact integer cross-multiplication and inclusive 70%/95% boundaries (§3.1), per-day department capacity below 2 (§3.8), obligation crediting with permanent skips (§3.9), repayment amortization with the chronological-vs-proportional worked divergence (100,000.00/6 months/2 fulfilled → 66,666.66 vs 66,666.67) (§3.9), ledger invariant (§3.2).
- **Validations (11/11 tiers):** §2.9 enumerates all tiers in explicit evaluation order with per-tier endpoint scopes, echoed beside the workflows they guard in §3.
- **Endpoints (58/58)** in §4; **errors (49/49)** in §5 and each mentioned in §2/§3 prose; **roles (5/5)** in §2.1 with individual identity translations (Faculty/CommitteeMember/DepartmentChair entity-backed on FacultyMember; ProvostOffice/LeaveAdministrator opaque); **both OCC rules** in §2.8 with `expected_application_version`/`expected_repayment_version` + `ERR_STALE_VERSION`/412, framed purely as stale-version rejection.

**Hard contract reports:**
- Contract 1 (field names): entities+common 86/86, endpoint inputs 47/47, query params 15/15, path params 1/1, computed-read output fields 8/8 — 0 missing. **PASS**
- Contract 2 (rules): 11 validation tiers ordered in prose; 2 OCC rejections fully named; 60+ state transitions fully expressed; 11 calculations reconstructible (no pseudocode, no fuzzy words — mechanically verified); all side effects and applies-to scopes expressed; sibling branches (approve/deny, accept/reject, complete/curtail, ACTIVE/ON_LEAVE separation, DUE/OVERDUE/REVISION_REQUIRED submit) at equal density. **PASS**
- Contract 3 (§3 path purity): 612 backtick tokens scanned in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path combos. **PASS**

## Step 5: Generate Unit Tests — 2026-08-14T01:10:00.000Z

Collection succeeds: 79 test cases (74 functions; the two parametrized families expand to 5+2 cases). All checks pass. Final report:

## Generation complete — task_1580_faculty_sabbatical_leave_administration

### Files written

**test_helpers/** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1580_faculty_sabbatical_leave_administration/test_helpers/`):
- `types.py` — 15 status enums + role enum + 12 entity TypedDicts (RepaymentPayment/AccrualLedgerEntry correctly carry only `id` + `created_at`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (44 methods)
- `api_errors.py` — 51 `ApiErrorId` members + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_department_budget_invariant`
- `factories.py`, `constants.py` (72/36/6-month credits, 8000/course, 0.70/0.95 posture thresholds, 0.45/0.35/0.20 weights), `test_users.py` (opaque Provost/Admin constants + entity-backed `make_*_headers` builders)
- `fixtures.py` — composite pipelines: chaired departments, reviewer pools, `setup_full_award` (cycle→reviews→plan→allocate→SCHEDULED grant), active/completed grant chains, professional-leave pipeline, `setup_breached_repayment`
- `__init__.py` — barrel export

**test_suite/** (10 files, under `.../test_suite/`): `conftest.py` + 9 test files:
- `test_01_departments_and_posture.py` (5), `test_02_faculty_accrual_eligibility.py` (11), `test_03_applications_and_submission_gates.py` (19), `test_04_committee_reviews_and_composite.py` (6), `test_05_coverage_plans.py` (5), `test_06_allocation.py` (2), `test_07_grants_fellowships_cascades.py` (15), `test_08_obligations_repayments_reports.py` (6), `test_09_security_rbac_envelope.py` (5)

### Test counts
- **74 test functions / 79 collected cases** (parametrized families expand)
- **Queue A (Difficulty): 36 tests — all 18 instances × 2**, every tag resolves
- **Queue B (Corner): 38 tests — 38 of 39 non-stub instances**; all 13 `excluded_because:` stubs skipped and their cross-references verified to resolve

### Skipped instance (1)
- `Corner/entities/faculty_create_system_field_input_rejected` — PRD §2.9 tier 2 covers required fields/enums/domains but never states that unknown or system fields in a request payload are rejected; a faithful PRD-only implementer could ignore the extra `status` field. Fails unique derivability.

### Deviation note
- `accrual_frozen_while_report_overdue`: the design YAML asserts `credit_balance == 73` but its own derivation "(72 − 36 consumed + 1)" equals **37**; the test asserts the PRD-derived value 37 (asserting 73 would fail every faithful implementation).
- Clock never moves backward anywhere (PRD §2.5 describes the set endpoint as *advancing* the clock); affected recipes were reordered without changing asserted outcomes.

### Self-checks
- **Stage 1**: all helpers compile; `import test_helpers` succeeds against the installed framework; every `from test_helpers import ...` in test files resolves.
- **Stage 2**: tag audit passes (18/18 A-instances ≥2 tests, 38/38 covered B-instances ≥1, no tag points at a stub or unknown instance); exactly one `Design:` line per test function; 127 verbatim citation probes all grep-match PRD.md; all 38 asserted `error_id`s appear in PRD prose (not just §5); no `skip`/`skipif`/`xfail` markers; no scaffold references in comments; `pytest --collect-only` succeeds (79 cases).

## Step 6: Generate Implementation — 2026-08-14T01:25:00.000Z

Done. Final report:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1580_faculty_sabbatical_leave_administration/workspace/implementation/`:

- `start.sh` — guarded Flask install (`python3 -c "import flask"` check, no reinstall on reboots), `exec python3 app.py` in foreground, executable
- `requirements.txt` — `flask>=3.0`
- `app.py` — entry point; binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory store (dicts + append-only ledger list), logical clock starting at exactly `2026-08-01T00:00:00Z`, insertion sequence; **no seeding anywhere**
- `util.py` — error catalog (all 49 error IDs with fixed HTTP statuses), envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`, pagination fields `limit`/`offset`/`total_count`/`has_more`), ISO-8601 parse/format (3 fractional digits, Z), calendar-month math, Decimal money helpers
- `flask_app.py` — app object, `ApiError` handler, lazy OVERDUE/DEFAULTED sweep on every request
- `services.py` — serializers, department bucket/posture recompute (exact integer cross-multiplication at 70/95 boundaries), review composite with per-product ROUND_HALF_UP then drop-lowest, ledger balances computed from the append-only ledger, grant cancel / curtail / plan settle / obligation breach cascades, capacity sweep
- `routes_org.py` — clock, departments (CRUD+PATCH pool floor), faculty (create/list/get/separate/eligibility/ledger), accrual runs, manual ADJUST entries
- `routes_cycle.py` — cycles (open/close/allocate/finalize with full ranking + 4-gate award logic), applications (create/submit/request-revision/withdraw/decide incl. medical precedence cascade), committee reviews
- `routes_exec.py` — coverage plans (create with supersede + OCC, submit/approve/request-revision), grants (activate/complete/curtail with pinned salary-then-offset order), fellowships, service obligations (read-time `projected_liability`), repayments + OCC-guarded payments + waive, accomplishment reports

## Smoke-boot result

`PORT=<port> bash start.sh` boots cleanly from a fresh process (verified 7+ times, each with an empty store). Final runs: all 59 lifecycle checks passed (accrual → eligibility → cycle → application → 3 reviews → composite 78.74 → plan OCC create/stale-412/submit/approve → reserve 32000 → allocate award → CONSUME 72 → fellowship verify/apply offset 20000 against gross 90000 → complete → plan SETTLED, dept buckets flip → obligation + report DUE 2028-03-31 → obligation crediting → separation breach (base 122000, monthly 10166.67, owed 91499.99) → payment OCC + settle → lazy OVERDUE → late submit → accept) and all 58 edge checks passed (validation ordering shape-before-role, pagination bounds, combo/cycle rules, posture OPEN/CONSTRAINED/FROZEN boundaries, pool floor 422, duplicate guards, capacity 409, curtail pro-rate 8000.00 + RESTORE 18, medical-cancel cascade with RESTORE/RELEASED/RESCINDED/DECLINED, ON_LEAVE separation curtail+breach, payment-exceeds 422, waive). Server killed; ports closed.

## PRD ambiguities resolved

1. **§3.8 activation gate order** — the §3.8 narrative lists `ERR_GRANT_START_NOT_REACHED` before `ERR_INVALID_FACULTY_STATE`, but the same sentence says gates run "in the validation order of §2.9", which puts all from-state gates (tier 7) before temporal gates (tier 10). I followed §2.9: grant-state → faculty-state → start-reached → overlap → capacity.
2. **Version bumps on side-effect mutations** — §2.4 says version increments on "every mutation … including mutations caused as side effects." I applied this uniformly: recomputed application review aggregates bump `LeaveApplication.version` (verified: after 3 review submits + submit, version = 5, and OCC correctly rejected a stale `expected_application_version`), department bucket changes bump `Department.version`, lazy OVERDUE/DEFAULTED flips bump their resource's version.
3. **Duration outside {1,2}** — not listed among tier-2 numeric-domain examples (courses 1..40, amounts > 0); the tier-9 combo rule covers "(duration, salary_pct) not in the allowed tier set", so a bad duration returns `ERR_INVALID_DURATION_SALARY_COMBO` (422), not 400.
4. **Duplicate `employee_number`** — the catalog defines no error for it; used `ERR_INVALID_REQUEST` (400).
5. **Coverage plan creation against a non-sabbatical application** — by analogy with the fellowship rule (`ERR_INVALID_REQUEST` for non-sabbatical `application_id`), returns `ERR_INVALID_REQUEST`; a sabbatical application in a post-award state returns `ERR_INVALID_APPLICATION_STATE`; a supersede target not in DRAFT/SUBMITTED/REVISION_REQUESTED returns `ERR_INVALID_PLAN_STATE`.
6. **Cancel unwind for non-sabbatical grants** (separation of a faculty with a SCHEDULED medical/professional grant) — the RESTORE/plan-release/fellowship-decline steps are sabbatical-only (non-sabbaticals never posted a CONSUME, per the ledger-invariant calc), but the application still moves to `RESCINDED` per the separation bullet, with `funding_status` staying NONE.
7. **Segregation check for ProvostOffice plan creation** — §2.1 says ProvostOffice/LeaveAdministrator IDs are opaque and never compared to entity IDs, so `ERR_SEGREGATION_OF_DUTIES` and the chair-department match apply only to `DepartmentChair` callers.
8. **Separation curtailment of an ACTIVE grant with `separation_date` outside the window** — the system cascade skips the direct-curtail date gates; I clamped computed `actual_months` into [1, planned_months] to avoid negative RESTORE credits.
9. **"Month before proposed_start_date" (provisional eligibility)** — interpreted as the calendar month preceding the start date's month, consistent with the hire-watermark and accrual through-month phrasing.
10. **Department capacity check** — implemented as a true per-day max-concurrency sweep over boundary instants (two colleagues overlapping disjoint halves of the window do not trip the cap), honoring half-open adjacency.

## Step 7: Run Tests and Iterate — 2026-08-14T01:45:00.000Z

All 8 rounds pass 79/79. The task is complete.

## Summary

**Iterations run:** 2 (initial sweep surfaced 5 deterministic failures, identical across all 8 rounds; fix sweep: 79/79 × 8 rounds clean).

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:** None — the factories/fixtures/headers were PRD-consistent; the bugs were in test functions and the implementation.

**Fixes applied to `test_suite/`:**

1. `/home/ubuntu/github/CodingPRD/tasks/task_1580_faculty_sabbatical_leave_administration/test_suite/test_02_faculty_accrual_eligibility.py` — `test_overdue_report_blocks_earnings_and_watermark_advances`: PRD §3.2's "A run-time check blocks **the member** entirely" is member-scoped, but the test asserted the run-level `earn_entries_created == 0` while the unblocked chair + 3 reviewers legitimately earned 56 entries. Replaced run-total earn assertions with member-scoped assertions on the blocked faculty (`credit_balance == 36`, `lifetime_service_months == 72`, `last_accrued_month == "2027-09"`, then `"2027-10"` after clearing — which also proves the never-backfill rule). Kept `obligation_months_credited == 3` (run-total is member-equivalent there).

2. `/home/ubuntu/github/CodingPRD/tasks/task_1580_faculty_sabbatical_leave_administration/test_suite/test_03_applications_and_submission_gates.py` — `TestDuplicateBeatsWindowOverlap._setup` (shared by `test_duplicate_and_overlap_yields_duplicate_error` and `test_overlap_surfaces_once_duplicate_cleared`): setup created draft A2 *before* submitting A1, so A1's own submission correctly tripped PRD §3.3's duplicate gate ("No other application of the same faculty member may sit in DRAFT, UNDER_REVIEW, or REVISION_REQUESTED"). Reordered: submit A1 first, then create A2 while the professional grant is still SCHEDULED (creation checks overlap only against ACTIVE grants per §2.9 tier 10), then activate.

3. `/home/ubuntu/github/CodingPRD/tasks/task_1580_faculty_sabbatical_leave_administration/test_suite/test_07_grants_fellowships_cascades.py`:
   - `test_completion_cascade_recomputes_buckets_and_posture`: the test computed post-settlement posture from reserved-only (112000/160000 = 0.70 → CONSTRAINED), contradicting PRD §3.1's verbatim formula "The committed total (**reserved plus spent**) is compared against the pool" — a full-term settlement moves 40000 from reserved to spent, leaving committed at exactly 0.95 (inclusive boundary → FROZEN). Corrected the assertion to `FROZEN` with an explanatory comment.
   - `test_settlement_reenables_plan_submission`: the PRD-verbatim rule "a settlement can flip a FROZEN department back to CONSTRAINED or OPEN, re-enabling plan submissions there" is unreachable via full-term completion (committed is invariant when final == provisional); only the pro-rated curtailment settlement shrinks committed (§3.8: "the difference between provisional and final flowing back into available_amount"). Switched the trigger to curtailing the grant at 3 of 6 months (final 20000 vs provisional 40000 → committed 152000→132000, 0.95 FROZEN → 0.825 CONSTRAINED) and added an explicit posture assertion before the now-successful plan submission.

**Fixes applied to `implementation/`:**

1. `/home/ubuntu/github/CodingPRD/tasks/task_1580_faculty_sabbatical_leave_administration/workspace/implementation/routes_cycle.py` — `create_application()`: removed the creation-time `_has_other_in_flight` duplicate check. PRD §3.3 states the duplicate rule verbatim only in the **submission** gate chain, with the carve-out "resubmitting the same application never counts as its own duplicate" — if creation blocked duplicates, two in-flight applications could never coexist and the PRD's submission-time rule would be dead code. This was an implementation check the PRD does not require, and it made the test_03 scenario's intended state (A1 UNDER_REVIEW + A2 DRAFT) unreachable under any setup ordering.

No checks the PRD requires were weakened; no endpoints/fields were added; storage remains in-memory only; no files outside the task directory were touched.

## Step 8: Finalize PRD — 2026-08-14T02:00:00.000Z

The diff is exactly the three intended edits; both files are 369 lines (0% line-count delta, three lines modified in place). All edits verified against the full enumeration of implementation paths.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1580_faculty_sabbatical_leave_administration/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md = 369 lines, PRD_FINALIZED.md = 369 lines (0% delta; 3 lines revised inline, none added/removed).

### Changes (one bullet per change)

- **§2.9 tier 9** — revise — replaced the blanket sentence "This tier applies to application creation, application submission, and review creation." with per-check scoping: creation enforces only the duration/salary tier table and the `cycle_id` presence rule and never rejects a second in-flight application; the in-flight duplicate rule and 72-month service requirement fire only at submission; the duplicate-review rule fires at review creation — `implementation/routes_cycle.py:206-262` (creation: combo L238, cycle_id L239, no duplicate check), `routes_cycle.py:319-324` (submission: duplicate with `exclude_app_id`, service months), `routes_cycle.py:462-464` (review creation).
- **§3.8 completion paragraph** — revise — replaced "a settlement can flip a `FROZEN` department back to `CONSTRAINED` or `OPEN`, re-enabling plan submissions there" with the correct completion-scoped claim: since `final_cost` equals the full `provisional_cost`, a full-term settlement leaves committed (reserved plus spent) unchanged, so completion by itself never moves the posture — `implementation/routes_exec.py:308` (`settle_confirmed_plan(application, plan['provisional_cost'])`), `implementation/services.py:65-82` (posture is a pure function of committed vs pool).
- **§3.8 curtailment paragraph** — insert — appended to the pro-rated settlement clause: because such a settlement lowers the committed total, it can flip a `FROZEN` department back to `CONSTRAINED` or `OPEN`, re-enabling plan submissions — `implementation/services.py:319-320` (`final = q2(provisional * actual/planned)`), `implementation/routes_exec.py:153,173` (FROZEN gates on plan submit/approve).

### Step-7 items requiring no edit (with reason)

- **test_02 (§3.2 overdue block)** — pure fixture bug; PRD §3.2 is already member-scoped ("blocks the member entirely"; watermark advances regardless), matching `routes_org.py:285-306`.
- **test_03 (§2.9 tier 10 creation overlap)** — fixture ordering bug; §2.9 tier 10 already pins "overlap against active grants … applies to application creation and submission", matching `routes_cycle.py:244` + `services.py:109-117` (ACTIVE-status-only overlap).
- **test_07a (committed = reserved + spent)** — pure test bug; §3.1 already carries the verbatim formula, matching `services.py:74`.

### Per-edit pre-edit search log

**Edit 1 (tier 9 scoping).** (a) Subject: which endpoints fire each tier-9 check. (b) Enumerated via grep for `ERR_DUPLICATE_ACTIVE_APPLICATION|ERR_DUPLICATE_REVIEW|ERR_INSUFFICIENT_SERVICE_MONTHS|ERR_INVALID_DURATION_SALARY_COMBO|_has_other_in_flight` across all `*.py`: only `create_application` (combo, cycle_id), `submit_application` (duplicate, 72-month), `create_review` (duplicate-review); no other endpoint raises any of the four (allocation uses `award_outcome` codes instead, consistent with §3.6). (c) Wording adjustment: added the explicit carve-out "creation never rejects a second in-flight application" and used "fires **only** at application submission" so no enumerated path (creation, submission, review, allocation, decision) is mis-described.

**Edit 2 (completion posture sentence).** (a) Subject: posture-recompute effects of a full-term settlement. (b) Enumerated via grep for `department_mutated|department_recompute|settle_confirmed_plan|posture`: recompute sites are `patch_department` (routes_org.py:120), `approve_plan` (routes_exec.py:181), withdrawal release (routes_cycle.py:373), cancellation release (services.py:177), and `settle_confirmed_plan` (services.py:294) reached from completion (routes_exec.py:308, final == provisional) and curtailment (services.py:319, final ≤ provisional). (c) Wording adjustment: scoped the claim strictly to completion's own arithmetic ("completion by itself never moves the posture") rather than saying "only curtailment can flip FROZEN back", because release paths (withdrawal, medical/separation cancellation) also lower committed and can improve posture — a universal claim would have been a new mismatch.

**Edit 3 (curtailment flip-back).** (a) Subject: whether a pro-rated settlement can change posture. (b) Same enumeration as Edit 2, plus the curtail route's strict between-gate (routes_exec.py:327) guaranteeing actual < planned on the direct route, so committed strictly decreases there; FROZEN gating sites (routes_exec.py:153, 173) confirm "re-enabling plan submissions" is the right consequence. (c) Wording adjustment: phrased as a possibility ("can flip") scoped to "such a pro-rated settlement", which stays true for all curtailment call paths including the separation-driven `curtail_grant` (routes_org.py:211), where actual may equal planned and no flip occurs.

## Step 9: Complete PRD — 2026-08-14T02:10:00.000Z

All edits applied cleanly. The task is complete.

## Summary

**Source vs. output:** `PRD_FINALIZED.md` (369 lines, 62,658 chars) → `PRD_COMPLETED.md` (371 lines, 65,647 chars); **+2 lines, +2,989 chars**. All changes are inline inserts/revisions within existing paragraphs; no new sections.

**Counts:** 20 ambiguity-pins, 3 mismatch-revisions.

### Changes (in document order)

- §2.2 — insert — ambiguity — undefined paths answer 404 and unsupported methods 405, both in the error envelope with `error_id` `ERR_INVALID_REQUEST`; unexpected failures answer 500 with the same id — `flask_app.py:23-35`
- §2.3 — insert — ambiguity — a `limit`/`offset` that does not parse as an integer is `ERR_INVALID_PAGINATION` — `util.py:295-308`
- §2.3 — insert — ambiguity — list sort ties on identical `created_at` break by creation (insertion) order — `util.py:324-325`
- §2.5 — insert — ambiguity — the logical clock also stamps every `created_at`/`updated_at`; clock-set accepts any valid instant including an earlier one; missing/unparseable `to_iso8601` is `ERR_INVALID_REQUEST` — `db.py:31-38`, `routes_org.py:26-35`
- §2.5 — revise — ambiguity — the OVERDUE/DEFAULTED lazy evaluation runs on every incoming request, not only on reads — `flask_app.py:11-15`
- §2.6 — insert — ambiguity — calendar-month addition clamps day-of-month to the last day of a shorter target month (31 Aug + 6 months → last day of Feb) — `util.py:199-204`
- §3.1 — insert — ambiguity — `chair_faculty_id` may be cleared back to null on update; non-null chair must exist (`ERR_FACULTY_NOT_FOUND`); even a no-field-change PATCH increments `version` — `routes_org.py:101-120`
- §3.2 — insert — ambiguity — duplicate `employee_number` is rejected with `ERR_INVALID_REQUEST` — `routes_org.py:149-151`
- §3.2 — insert — ambiguity — every ledger entry carries `affects_lifetime`, false except on `ADJUST` entries posted with it true — `services.py:40-50,510-517`
- §3.2 — insert — ambiguity — `faculty_processed` counts every faculty member walked, even those whose watermark was already current — `routes_org.py:283-306`
- §3.2 — insert — ambiguity — eligibility takes `proposed_start_date` as a query parameter; missing/unparseable is `ERR_INVALID_REQUEST` — `routes_org.py:239-242`
- §3.3 — insert — ambiguity — withdrawal also clears `current_coverage_plan_id` to null — `routes_cycle.py:375`
- §3.5 — insert — ambiguity — plan-creation gates: non-sabbatical application → `ERR_INVALID_REQUEST`; application not in `DRAFT`/`UNDER_REVIEW`/`REVISION_REQUESTED` → `ERR_INVALID_APPLICATION_STATE`; `supersedes_plan_id` of another application → `ERR_INVALID_REQUEST`; terminal supersede target → `ERR_INVALID_PLAN_STATE` — `routes_exec.py:54-82`
- §3.6 — insert — ambiguity — awarded grant is born with `gross_salary`/`net_salary` null and `fellowship_offset_total` zero — `services.py:235-253`
- §3.7 — insert — ambiguity — the `UNDER_REVIEW` from-state check fires before the sabbatical-requires-allocation check — `routes_cycle.py:391-394`
- §3.8 — revise — mismatch — activation gate listing reordered to grant-state → faculty-`ACTIVE` → start-reached → overlap → capacity, matching the §2.9 tiers the impl follows — `routes_exec.py:239-253`
- §3.8 — revise — mismatch — replaced the false "timestamps are unique at three fractional digits, so ties cannot occur" claim: ties on `created_at` are possible under the logical clock and break by creation order — `routes_exec.py:269`
- §3.8 — insert — ambiguity — the `funding_status` → `COVERAGE_SETTLED` transition at completion is sabbatical-only; medical/personal/professional completions leave `funding_status` untouched — `routes_exec.py:305-308`
- §3.8 — insert — ambiguity — same sabbatical-only scoping for `COVERAGE_SETTLED` at curtailment — `services.py:316-320`
- §3.9 — revise — ambiguity — obligation crediting is decided per run by the member's run-time status: an `ON_LEAVE`/`SEPARATED` member is credited nothing for the whole range and the watermark still advances permanently — `routes_org.py:309-328`
- §3.9 — insert — ambiguity — a `SCHEDULED` non-sabbatical grant on separation unwinds to bare cancellation plus rescission from `APPROVED`, with `funding_status` unchanged — `services.py:162-185`
- §3.9 — insert — ambiguity — separation-driven curtailment applies no date-range gate (unlike §3.8), `actual_months` floors at 1 and caps at the planned length, and curtailed medical/personal grants create no obligation — `services.py:299-327`, `routes_org.py:204-219`
- §3.9 — revise — mismatch — waive "records optional comments" → "accepts optional comments (which are not persisted)"; impl validates then discards them and the repayment serializer has no comments field — `routes_exec.py:537-549`

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1580_faculty_sabbatical_leave_administration/workspace/PRD_COMPLETED.md`

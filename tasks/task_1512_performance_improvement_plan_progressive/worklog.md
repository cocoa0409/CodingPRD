# Worklog — task_1512_performance_improvement_plan_progressive

## Step 1: Create Task Directory — 2026-08-13T15:36:00.000Z

Task directory `tasks/task_1512_performance_improvement_plan_progressive/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline invoker. Verified existence; no index scan or creation performed (Step 1 treated as DONE per instructions).

## Step 2: Generate Scaffold — 2026-08-13T17:36:00.000Z

All three files are written and lint is clean.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1512_performance_improvement_plan_progressive/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (scenario, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles); no `scaffold_difficulty_design` or `scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` with all 9 §0.5 rule_ids
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` with 9 sections per the claim-extraction-guide taxonomy

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

**Counts**:
- Entities: **15** (HROrgUnit, Employee, RatingCycle, ManagerCoachingLogEntry, PerformanceConcern, PIPTemplate, PerformanceImprovementPlan, PIPGoal, CheckIn, EvidenceItem, LegalReview, OutcomeDecision, EmployeeRebuttal, ConsistencyReview, RatingCycleOutcomeLink)
- State machines: **10** (PerformanceConcern, PIPTemplate, PerformanceImprovementPlan, CheckIn, EvidenceItem, LegalReview, OutcomeDecision, EmployeeRebuttal, ConsistencyReview, RatingCycle)
- Calculations: **6** (pip_attainment_ratio with PROVISIONAL/FINAL variants, goal_status_rule, legal_risk_score, consistency_disparity_score, rating_alignment_score, pip_end_date_extension)
- Validations: **23** (priority-ordered)
- Endpoints: **83** (55 primary nested + 28 flat query endpoints added for FK reverse-reachability)
- Errors: **35**
- Roles: **6** (HRSystemAdmin, Manager, HRBusinessPartner, LegalCounsel, HRDirector, Employee)
- Concurrency rules: **2** (OCC on PIP for issue and outcome-approve)
- Difficulty-design instances (§1.8): **18** (2 per each of 9 rules)
- Corner-design instances (§1.9): **66 total** — 51 active test recipes + 15 `excluded_because` stubs in the `errors` section citing §1.8 coverage

**Notable design decisions (pushing difficulty to max)**:

1. **Segregation of duties as first-class RBAC model** (`role_model: segregation_of_duties`): concern-raiser can't accept, issuer can't adjudicate own evidence, proposer can't approve own outcome, opener can't adjudicate own consistency review, rebuttal reviewer must differ from both issuer and proposer. SoD is wired through transition preconditions, not just role membership.
2. **Dual-variant attainment calculation** (Rule 1 instance 1): PROVISIONAL counts only ADMISSIBLE evidence; FINAL counts all submitted evidence regardless of admissibility — produces 0.5 vs 1.0 divergence on identical evidence data.
3. **Non-linear legal risk scoring** (Rule 2 mode a): six factor weights, a DOCUMENTATION_GAP multiplicative doubler, and a WHISTLEBLOWER_HISTORY compound bonus, with floor/ceiling clamps — exercising nested conditional branches and rounding order.
4. **Round-at-end vs round-per-goal** (Rule 2 mode b): pip_attainment_ratio pins `round_half_up to 4dp AFTER the weighted sum` explicitly to discriminate from per-goal rounding.
5. **Cyclic PIP state machine** (Rule 3): ACTIVE → EXTENDED → ACTIVE with extension_count bounding the cycle at 1; EXTENSION outcome at the limit returns ERR_EXTENSION_LIMIT_EXCEEDED.
6. **Branching rebuttal state machine** (Rule 3, different entity): SUBMITTED → UNDER_REVIEW → {UPHELD, OVERRULED} where OVERRULED on an APPROVED TERMINATION *rescinds* the termination (Employee remains ACTIVE) — divergent side-effect sets per branch.
7. **Two transitive cascades** (Rule 4): termination approval chain (depth 3: OutcomeDecision → PIP → Employee → RatingCycleOutcomeLink rows) and PIP issue chain (depth 3: PIP → Concern → Employee.active_pip_id).
8. **Validation priority conflicts across category pairs** (Rule 5): state-vs-safety (concern accept) and safety-vs-constraint (outcome approve), exercising priorities 6-7 and 7-17.
9. **Boundary precision on different metrics/endpoints** (Rule 6): attainment `>= 0.80` (inclusive numeric) and rebuttal window `<= decided_at + 5 days` (inclusive temporal), each reachable via a distinct endpoint.
10. **Two temporal-overlap interval semantics** (Rule 8): half-open [start, end) on RatingCycle (adjacent allowed) vs state-occupation on Employee (active_pip_id blocks second PIP regardless of dates).
11. **Two compensating invariants** (Rule 9): PIPGoal weight sum = 100 conserved across create+withdraw; Employee.active_pip_id restored to null across issue+withdraw.
12. **Logical clock** with default `2026-08-01T00:00:00Z` and explicit `POST /hr-org-units/{ouId}/_clock/set_current_utc` test-driving endpoint — drives ISSUED→ACTIVE auto-transition, MISSED check-in sweep, plan-end gating, rebuttal window, and rating-cycle archive windows deterministically.
13. **Version pinning on approval**: PIP snapshots `template_published_version` and `policy_version_at_issuance` at creation; subsequent template publishes do not mutate in-flight PIPs (verified in corner instance `pip_pins_template_published_version_at_issuance`).
14. **Flat query endpoints**: 28 additional `GET /hr-org-units/<entity>` + `GET /hr-org-units/<entity>/{id}` endpoints to satisfy the lint's FK reverse-reachability check while keeping the canonical nested paths as the primary access pattern.

## Step 3: Copy Shared Files — 2026-08-13T17:38:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1512_performance_improvement_plan_progressive/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T17:40:00.000Z

PRD generation complete. Summary:

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1512_performance_improvement_plan_progressive/workspace/PRD.md` — 333 lines.

**Section list**
- §1 Introduction (2 paragraphs — business/legal-sensitivity angle)
- §2 Global Specifications: 2.1 RBAC (headers, 6 roles, identity semantics per role), 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields), 2.4 Common Resource Properties (with the three `common_fields: false` entities called out), 2.5 Logical Clock & Time-Driven Transitions, 2.6 Hierarchical Addressing/Validation Order/Flat Read Paths (fixed validation priority chain stated explicitly), 2.7 Segregation of Duties, 2.8 OCC, 2.9 Precision & Rounding
- §3 Business Logic (8 subsections, lifecycle-timeline grouping): org units/employees/rating cycles → coaching & concerns → templates & issuance → check-ins/evidence/attainment → legal review → outcome decisions & closure → rebuttals → consistency review & rating-cycle correlation
- §4 Endpoint Definitions (4-column table), §5 Error Code Catalogue (2-column table)

**Coverage counts**
- Entities: 15/15 described; fields 95/95 in backticks
- Endpoints: 83/83 in §4 table (55 nested + 28 flat reverse-reachability reads)
- Errors: 35/35 in §5 table; all 35 also mentioned with trigger conditions in §2/§3 prose
- State machines: 10/10 (34 transitions, all preconditions paired with error IDs and side effects stated); calculations 6/6 in precise prose (attainment PROVISIONAL/FINAL variants, goal-status tiers with inclusive 0.70 boundary, legal risk weights/doubling/compound/clamp, disparity, alignment, extension floor); concurrency rules 2/2; role identity semantics 6/6

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 95 required, 95 present, 0 missing
- endpoints[].request_body: 41 required, 41 present, 0 missing
- endpoints[].query_params: 40 required, 40 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 23 checked, 23 expressed (fixed evaluation chain in §2.6; propose/approve dual-application of the three outcome guards in §3.6), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (issue + outcome-approve; expected_pip_version + ERR_STALE_VERSION/412 named in §2.8, §3.3, §3.6), 0 missing
- state_machines[].transitions: 34 checked, 34 fully expressed, 0 missing
- calculations[]: 6 checked, 6 fully expressed, 0 missing
- validations[] conditions: 23 checked, 23 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 83 checked, expressed in workflow narratives, 0 missing
- entities[].fields[] structured content: 95 checked, reconstructible (defaults, enums, nullability, pinning), 0 missing
- sibling-branch symmetry: 6 groups checked (accept/reject, admit/exclude, UPHELD/OVERRULED, CONSISTENT/INCONSISTENT, withdraw ISSUED/ACTIVE, close branches), 6 with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 406
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Notable editorial decisions**
- §2.2 emitted byte-identical to the canonical block (verified programmatically); placeholders untouched.
- Validation priority chain (scaffold priorities 1–23) rendered as an explicit ordered evaluation narrative in §2.6, with OCC explicitly "before any business rule"; individual rule→error bindings scattered into §3 workflows.
- §3 grouped chronologically by process lifecycle (8 subsections) rather than by entity; endpoint parameters deliberately split across subsections (e.g., `expected_pip_version` in §2.8/§3.3/§3.6; the 0.80 SUCCESS threshold and 5-day rebuttal window in §3.6/§3.7).
- The withheld difficulty/corner files were never opened; all numbers derive solely from SCAFFOLD.yaml.
- One checker artifact worth noting: naive backtick extraction miscounts because of §2.2's fenced JSON blocks — verification strips fences first; the document itself is standard markdown.

## Step 5: Generate Unit Tests — 2026-08-13T18:45:00.000Z

All checks pass. Here is the final summary.

### Files written

**test_helpers/** (9 files):
- `test_helpers/__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 15 entity TypedDicts + 17 status/role enums (append-only entities omit `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with 87 methods covering every nested + flat endpoint
- `api_errors.py` — `ApiErrorId` enum (35 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_pip_goal_weight_sum` invariant
- `factories.py` — payload factories with PRD-minimum-length-safe defaults
- `constants.py` — domain thresholds (0.80 attainment, 0.70 ON_TRACK, legal weights, 5-day rebuttal window, etc.)
- `test_users.py` — shared `TEST_USERS` + per-instance `make_*_headers(user_id)` builders for all 5 entity-backed roles
- `fixtures.py` — composite fixtures: `setup_cast`, `create_coaching_entries`, `create_and_accept_concern`, `create_and_publish_template`, `create_draft_pip`/`create_and_issue_pip`, `setup_issued_pip`, `setup_active_pip`, `submit_and_adjudicate_evidence`, `hold_check_in`, `create_and_submit_legal_review`, `propose_outcome`, `approve_outcome`, `setup_pip_ready_for_outcome`, `set_clock`

**test_suite/** (10 files, 89 tests):
- `conftest.py` — session `api` fixture + 6 role-header fixtures
- `test_01_entities.py` (12) — required fields, defaults, computed `end_date`, version pinning, pagination, error envelope
- `test_02_concerns.py` (5) — concern invalid transitions, terminal lockdown, issuance cascade, accept-escalation cascade, immediate consistency
- `test_03_pip_lifecycle.py` (10) — initial DRAFT, EXTENDED→ACTIVE cycle, terminal lockdown, single-active-PIP invariant, weight-sum/active_pip_id invariants, auto-activation
- `test_04_attainment_and_legal.py` (7) — PROVISIONAL-vs-FINAL divergence, nested rounding (0.3095), 0.70 boundary, legal risk 100/45/0
- `test_05_outcomes_and_rebuttals.py` (9) — termination cascade to links, legal gate (propose+approve), 0.80 inclusive boundary, proposal supersession, REJECT cascade, UPHELD/OVERRULED rebuttal branches
- `test_06_validations.py` (17) — priority pairs, referential integrity, parent mismatch, auth/role 400/403, timing rules, template geometry, cohort gates
- `test_07_concurrency_scheduled_rbac.py` (14) — OCC stale-version (issue+approve), MISSED sweep, RBAC denials, check-in/evidence terminal lockdown, legal-override guard, rebuttal window ±1s
- `test_08_consistency.py` (2) — cohort-too-small at creation
- `test_09_boundary_and_invariants.py` (13) — second-coverage tests for difficulty instances

### Test counts per queue
- **Queue A (Difficulty):** 37 tests covering 17 of 18 instances with ≥2 tests each
- **Queue B (Corner):** 52 tests covering all 50 non-stub instances with ≥1 test each; 15 `excluded_because:` stubs correctly not translated (all cross-references resolve)

### Instances skipped (1)
- `Difficulty/resource_temporal_overlap/rating_cycle_half_open_overlap_rejected_adjacent_allowed` — PRD §3.1 contains no verbatim rule rejecting overlapping rating-cycle windows on creation; the asserted 409+error has no PRD coverage, so a PRD-only implementer could legitimately accept the overlapping cycle. Skipped per the Core rule (gap stays a gap).

### Self-check results
- **Stage 1:** all 9 helpers compile; barrel import resolves; `ApiClient` exposes 87 endpoint methods; error map registered with the framework.
- **Stage 2 tag audit:** 89/89 tests carry exactly one trailing `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line; every tag resolves to a real instance with matching rule_id/section; 0 tag errors.
- **Stage 2 PRD citation audit:** every test docstring carries a verbatim PRD quote (6 checker-flagged quotes were short (<8 words) but each was independently confirmed verbatim in PRD.md).
- **No `pytest.mark.skip` / `skipif` / `xfail`** anywhere in test_helpers or test_suite.
- **Pytest collection:** 89 tests collected cleanly, no import/fixture errors.

## Step 6: Generate Implementation — 2026-08-13T19:20:00.000Z

All 83 unique routes = exactly the 55 nested + 28 flat endpoints in the spec table (plus Flask's default static rule). The implementation is complete and verified.

### Summary

**Files written** (all under `workspace/implementation/`):
- `start.sh` — executable launcher: guarded dependency install (`pip install` only if `flask` import fails), then `exec python3 app.py` in foreground
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask app factory, blueprint registration, ApiError handler producing the PRD §2.2 error envelope, 404/405/400 handlers, binds `0.0.0.0:$PORT` (default 10000)
- `core.py` — in-memory store (module-level dicts, empty at boot, no seeding, zero disk I/O), response envelope helpers (`meta.api_request_id`/`api_request_timestamp` with 3-fractional-digit ISO, `response_type`, `data`), auth (`X-User-ID`/`X-User-Role`, 6 roles), pagination (`limit`/`offset`, default 10, min 1, max 100, `total_count`/`has_more` in meta), ISO-8601 parsing with fractional-digit preservation, Decimal half-up-4dp rounding
- `business.py` — calculations (weighted attainment PROVISIONAL/FINAL variants with missed-check-in 0.5^missed penalty, goal status thresholds, tiered legal risk score with doc-gap doubling + whistleblower compound), logical-clock sweeps (ISSUED→ACTIVE activation, SCHEDULED→MISSED at >scheduled_for+3d, rebuttal-window-lapse closures strictly past `decided_at`+5d), plan closure with employee termination cascade and rating-cycle outcome links, consistency cohort + disparity/alignment scores
- `routes_core.py` — org units, clock, employees, coaching log, concerns, templates, rating cycles
- `routes_pips.py` — PIPs (create/issue/withdraw with OCC `expected_pip_version`), goals, check-ins (cadence enforcement), evidence + admissibility adjudication
- `routes_outcomes.py` — legal reviews, outcome decisions (propose/approve/reject with the three outcome guards), rebuttals (deferral + outcome reversal), consistency reviews, nested links
- `routes_flat.py` — all 28 flat reverse-reachability GET endpoints with FK filters

**Endpoint count:** 83 implemented (55 nested + 28 flat), matching the endpoint table exactly; route uniqueness verified (no duplicates).

**start.sh contract:** `bash start.sh` from `implementation/` → installs deps only when missing → `exec python3 app.py` foreground on `0.0.0.0:${PORT:-10000}`. Fresh process = completely fresh in-memory state (verified: reboot serves `total_count: 0` on all collections).

**Smoke boot:** verified across multiple boots. Beyond a basic boot+curl, ran three full end-to-end scenario suites (60+ assertions, all passing) covering: RBAC/SoD enforcement, concern→PIP→check-in→evidence pipeline, attainment math (0.68 provisional / 0.34 final with missed-check-in penalty), template publish version pinning, OCC 412s, activation/MISSED sweeps, extension (+15d, count=1, re-enters ACTIVE, no lapse closure), termination with legal review, closure deferral while rebuttal pending, upheld/overruled outcomes (termination rescinded → CLOSED_FAILED, employee stays ACTIVE), rebuttal window boundary semantics (allowed at exactly decided_at+5d, closed 1s past), risk score compounding (70 and 65 cases), REJECT cascade superseding PROPOSED decisions, legal override, rating-cycle lifecycle with ERR_CYCLE_STILL_OPEN/TOO_RECENT, outcome links with cycle-status snapshots, consistency cohort filtering (SALES excluded), cohort ordering, disparity 1.0 / alignment 0.5 score checks, adjudication, and pagination meta.

**Bugs found and fixed during smoke testing:** missing `clock_of` import in business.py; a helper/view name collision (`resolve_rebuttal`) causing infinite recursion; immediate-close-at-approval corrected to PRD-faithful deferred closure via the rebuttal window.

**Note:** Step 6 required one resume — the subagent's first run hit max_tokens after writing core.py + business.py only; resumed via SendMessage to finish routes/app/start.sh and smoke verification.

## Step 7: Test/Fix Diagnostic Loop — 2026-08-13T19:45:00.000Z

### Iteration 1 (8-round parallel sweep): 12/89 passed — 77 failing, deterministic across all rounds

Root-cause analysis (STEP 0-2 per test):

1. **Dominant root cause (~70 tests)**: `test_helpers/fixtures.py:create_and_submit_concern` default
   `summary="Quality below bar"` is 17 chars, below PRD §3.2's verbatim 20-char minimum
   ("a `summary` of at least 20 characters"). Test-fixture bug (STEP 2) — implementation
   correctly rejected the PRD-violating payload. Fixed default to "Quality below bar for level".
2. Same 17/18-char summaries hardcoded in test_03 (x4), test_06 (x3 incl. "Conduct escalation"),
   test_09 (x1) — all lengthened past the PRD floor.
3. Short `rationale` literals (<40 chars, PRD §3.6 floor) in test_03/05/06/07/09 — lengthened.
4. test_07 used `create_and_submit_concern` without importing it; test_09 used
   `make_manager_headers` without importing it; test_06 used `approve_outcome`/`get_goals`/
   `get_employee` without importing them — imports added.
5. `test_publish_with_weight_sum_not_100_rejected` expected 201 at template creation with
   weight-sum 90 — contradicts PRD §3.3 verbatim "These geometry rules are enforced at
   authoring and re-checked at publication". Rewritten to assert ERR_TEMPLATE_WEIGHT_SUM at
   authoring (renamed `test_template_with_weight_sum_not_100_rejected`).
6. `test_archive_before_365_days_rejected` set the logical clock backwards (2026-01-15 from the
   2026-08-01 boot reading) — violates PRD §2.5 monotonicity. Rewrote window to
   [2025-07-01, 2026-07-01) so calibrate/publish run at the boot clock and archive is
   attempted at +137 days.
7. Evidence-adjudication SoD (PRD §3.4 verbatim: "evidence submitted by the issuing HRBP must
   be adjudicated by a different HRBP"): fixture `submit_and_adjudicate_evidence` defaulted both
   roles to the issuing HRBP — added `ensure_second_hrbp(ctx)` and defaulted the adjudicator to
   it; direct submit/admit tests in test_04/07/09 switched to manager-submits + issuer-adjudicates.
8. `test_legal_reject_supersedes_proposed_outcome` proposed TERMINATION without a completed legal
   review and expected 201 — contradicts PRD §3.6 "Three guards attach at proposal time and again
   at approval". Repointed the proposal to EXTENSION so the §3.5 REJECT cascade can be observed.
9. `test_segregation_reported_before_attainment_guard` relied on a SUCCESS proposal surviving 0.0
   attainment to reach approve-time — impossible under §3.6 proposal-time guards. Rewritten to
   exercise SoD-vs-attainment ordering at proposal time (issuing HRBP proposes SUCCESS with no
   evidence -> ERR_SEGREGATION_OF_DUTIES).
10. OCC stale-version tests (issue + approve) relied on check-in creation advancing the PIP
    version — not uniquely derivable from PRD §2.4/§2.8. Rewritten to derive the stale snapshot
    from PRD-verbatim version increments: issuance increments version (§3.3), approval increments
    version (§3.6); the retried call with the stale snapshot must surface ERR_STALE_VERSION
    before the state check (§2.6 explicit ordering).

Deletions (STEP 1):
- `test_termination_approve_without_legal_review_rejected` — the scenario is unreachable under
  PRD §3.6's verbatim "Three guards attach at proposal time and again at approval": no PROPOSED
  TERMINATION can exist without a passing legal review, and a later REJECT review supersedes the
  decision (§3.5) before approval. The covered assertion survives in
  `test_termination_propose_without_legal_review_rejected`.
- `test_outcome_proposal_before_plan_end_rejected` — PRD §3.6 binds ERR_PLAN_STILL_RUNNING to
  outcome *approval* only ("Approval belongs to an HRDirector ... the clock must have reached
  the plan's end_date"); PRD is silent on a proposal-time window rule, and no PRD-clean setup can
  produce a PROPOSED decision while clock < end_date (proposal-before-end is itself the contested
  reading). ERROR-PRECEDENCE/rule-binding silence.

Rewrites with narrowed assertions (STEP 1c partial coverage):
- `test_variants_diverge_on_excluded_evidence` — provisional value corrected to 0.25 per PRD
  §3.4 verbatim ("goals without admissible evidence contribute zero attainment — although their
  weight still counts in the denominator"); the original 0.5 contradicted that clause, and the
  exact FINAL value on inadmissible-evidence data is not uniquely derivable from §3.6's fallback
  clause (two faithful readings: latest-evidence-regardless vs. held-check-in scoreboard value;
  the reference implementation embodies the latter). Kept PRD-verbatim assertions: provisional
  0.25; `final_attainment_ratio` null until proposal; decision snapshots the plan's frozen final
  ratio. Proposal switched to EXTENSION so the freeze is observable under every reading.

### Iteration 2 (8-round parallel sweep): 85/87 — two deterministic NameErrors
- test_06 missing top-level imports `approve_outcome` and `get_goals` (used by
  TestExtensionLimit and TestEvidenceAdjudicationTiming). Imports added.

### Iteration 3 (8-round parallel sweep): 87/87 in ALL 8 rounds — CLEAN SWEEP, exit.

## Step 7: Test/Fix Iteration Loop — 2026-08-13T20:05:00.000Z

All 8 rounds pass 87/87. Emitting the final summary.

### Summary

**Iterations run:** 3 (each a full 8-round parallel sweep, `passed == total` verified in every `results.1..8.json`).

- Iteration 1: 12/89 — 77 deterministic failures.
- Iteration 2: 85/87 — 2 deterministic NameErrors.
- Iteration 3: **87/87 in all 8 rounds — clean exit.**

**Tests deleted (2):**
- `test_05_outcomes_and_rebuttals.py::test_termination_approve_without_legal_review_rejected` — scenario unreachable under PRD §3.6 verbatim "Three guards attach at proposal time and again at approval": no PROPOSED TERMINATION can exist without a passing legal review (proposal would 422 first), and a later REJECT review supersedes the decision before approval (§3.5). Covered assertion survives in the sibling `test_termination_propose_without_legal_review_rejected`. Scaffold rule: `outcome_approve_termination_requires_legal_review_submitted` mis-rendered as an approve-time-only path.
- `test_06_validations.py::test_outcome_proposal_before_plan_end_rejected` — PRD §3.6 binds `ERR_PLAN_STILL_RUNNING` to outcome *approval* only; PRD is silent on a proposal-time window rule (error-binding silence / not uniquely derivable), and no PRD-clean setup can produce a PROPOSED decision while clock < end_date. Scaffold rule: `outcome_approve_before_plan_end_returns_plan_still_running` mis-bound from approve to propose.

**Fixes applied to `test_helpers/`:**
- `fixtures.py::create_and_submit_concern` — default summary "Quality below bar" (17 chars) violated PRD §3.2's verbatim 20-char minimum; changed to "Quality below bar for level". This single fixture bug caused ~70 failures.
- `fixtures.py::submit_and_adjudicate_evidence` + new `ensure_second_hrbp(ctx)` — fixture defaulted both evidence submitter and adjudicator to the issuing HRBP, violating PRD §3.4's verbatim SoD ("evidence submitted by the issuing HRBP must be adjudicated by a different HRBP"); adjudicator now defaults to a second, distinct HRBP.

**Fixes applied to `test_suite/`:**
- Short literals violating PRD minimums lengthened: concern summaries (<20) in test_03 (×4), test_06 (×3), test_09 (×1); outcome rationales (<40) in test_03/05/06/07/09 (×10 total).
- Missing imports added: `create_and_submit_concern` (test_07), `make_manager_headers` (test_09), `approve_outcome`/`get_goals`/`get_employee` (test_06).
- `test_06::test_template_with_weight_sum_not_100_rejected` (renamed) — expected 201 at template creation with weight-sum 90, contradicting PRD §3.3 verbatim "These geometry rules are enforced at authoring and re-checked at publication"; now asserts `ERR_TEMPLATE_WEIGHT_SUM` at authoring.
- `test_06::test_archive_before_365_days_rejected` — fixture moved the logical clock backward (PRD §2.5 monotonicity); window rewritten to [2025-07-01, 2026-07-01) so archive is attempted at +137 days from the boot clock.
- `test_05::test_legal_reject_supersedes_proposed_outcome` — proposal changed TERMINATION→EXTENSION (proposal-time legal gate per §3.6) so the §3.5 REJECT→SUPERSEDED cascade remains observable.
- `test_06::test_segregation_reported_before_attainment_guard` — rewritten to exercise SoD-vs-attainment ordering at proposal time (issuing HRBP proposes SUCCESS with no evidence → `ERR_SEGREGATION_OF_DUTIES`), since §3.6's proposal-time attainment guard made the approve-time construction unreachable.
- `test_07` OCC stale-version tests (issue + approve) — rewritten to derive the stale snapshot from PRD-verbatim version increments (§3.3 issuance, §3.6 approval) with §2.6's OCC-before-state ordering, instead of relying on check-in creation advancing the PIP version (not uniquely derivable from §2.4/§2.8).
- `test_04::test_variants_diverge_on_excluded_evidence` — STEP 1c partial coverage: provisional corrected 0.5→0.25 per §3.4 verbatim ("weight still counts in the denominator"); dropped the exact FINAL value (1.0) and divergence assertions — §3.6's fallback clause ("its most recent held check-in's value") admits two faithful readings and the reference implementation embodies the other; kept PRD-verbatim assertions (provisional 0.25; final null until proposal; decision snapshots the plan's frozen final ratio); proposal switched to EXTENSION so the freeze is observable under all readings.
- test_04 (×3), test_07 (×1), test_09 (×2): direct evidence submit/admit calls rerouted to manager-submits + issuing-HRBP-adjudicates per §3.4 SoD.

**Fixes applied to `implementation/`:** none — every implementation behavior under test traced to a verbatim PRD sentence; all failures were test-side.

## Step 8: Finalize PRD — 2026-08-13T20:15:00.000Z

Done. `workspace/PRD_FINALIZED.md` written — 3 surgical edits, everything else verbatim.

### Line counts / delta

- PRD.md: 333 lines; PRD_FINALIZED.md: 333 lines (0% line-count delta; 3 in-place sentence-level revisions across 3 paragraphs).

### Changes (one bullet each)

- **§2.5 — revise** — appended "and a `to_iso8601` earlier than the current reading is rejected with `ERR_INVALID_REQUEST`" to the clock-setting sentence — `implementation/routes_core.py:120-121` (`set_clock`: `if target < current: err(E_INVALID_REQUEST, ...)`).
- **§3.6 (proposal paragraph) — insert** — added "No proposal-time rule compares the clock against the plan's `end_date`: the `ERR_PLAN_STILL_RUNNING` window check described below attaches at approval only, so an outcome may be proposed while the plan's window is still running." — `implementation/routes_outcomes.py:222-258` (`propose_outcome` contains no clock comparison) vs `:288-289` (`approve_outcome` raises `ERR_PLAN_STILL_RUNNING`).
- **§3.6 (freeze paragraph) — revise** — re-scoped the ambiguous fallback clause to pin the implementation's reading: "the provisional variant's admissible-evidence gate is dropped, so each goal contributes its `current_value` exactly as last written by its most recent held check-in per §3.4 — a goal whose latest evidence is inadmissible or absent falls back to that most recent held check-in's value if one exists, else 0" — `implementation/business.py:113-142` (FINAL branch reads `g["current_value"]`, never consults evidence; the admissibility gate at line 128 is PROVISIONAL-only), `implementation/routes_pips.py:300-309` (`mark_held` is the sole writer of `current_value`, from that check-in's most recent admissible evidence), `implementation/routes_pips.py:131` (`current_value` starts 0).

### Per-edit pre-edit search log

**Edit 1 (final attainment fallback).**
- (a) Subject: FINAL-variant attainment computation and the source of each goal's contributed value.
- (b) Enumerated paths (grep `final_attainment_ratio|FINAL|PROVISIONAL`, `current_value|WAIVED` across all impl files, then read each): `business.py:113-142` (`attainment_ratio`, both variants — FINAL differs only by dropping the line-128 admissibility gate and adding the line-136-137 missed multiplier); `business.py:145-150` (`recompute_provisional`, PROVISIONAL only — unaffected); `routes_outcomes.py:236-251` (proposal computes FINAL, freezes to plan, snapshots to decision); `routes_outcomes.py:287` (approval guards consume the frozen value); `routes_pips.py:131` (current_value init 0); `routes_pips.py:297-310` (mark_held writes current_value from most recent ADMISSIBLE evidence of that check-in only; goals without admissible evidence keep their prior value); `business.py:257-266` (missed sweep recomputes provisional only).
- (c) Wording adjustment: anchored the contributed value to the `current_value` field ("as last written by its most recent held check-in per §3.4") rather than to any per-goal evidence scan, and kept the original fallback phrasing as a descriptive consequence ("falls back to that most recent held check-in's value if one exists, else 0") so goals covered by admissible-then-held evidence are not mis-described. The missed-check-in clause in the same sentence was left verbatim (impl's `0.5**missed` compounding is consistent with "each missed check-in contributes a … one-half … factor"; Step 7 did not flag it).

**Edit 2 (ERR_PLAN_STILL_RUNNING approval-only).**
- (a) Subject: plan-window (`end_date`) gating on outcome-decision endpoints.
- (b) Enumerated paths (grep `PLAN_STILL_RUNNING|end_date`): `routes_outcomes.py:288-289` (sole raise site, approve only); `routes_outcomes.py:222-258` (`propose_outcome` — verified no clock read anywhere in the function; only state check is `pip["status"] in PIP_CLOSED` → `ERR_INVALID_STATE`); `routes_outcomes.py:318-331` (`reject_outcome` — no window check); `routes_outcomes.py:296-306` (approval-time EXTENSION pushes `end_date` after the check — unaffected); `routes_pips.py:237-239` (check-in scheduling window is a separate `ERR_CHECKIN_TOO_EARLY` rule — untouched by the wording); `business.py:176,182` (link-overlap windows — unrelated).
- (c) Wording adjustment: phrased as "no proposal-time rule compares the clock against `end_date`" (a narrow absence claim) rather than "proposals are always allowed before `end_date`" (which would overclaim — guards/SoD/state still apply). Inserted in the proposal paragraph so the approval paragraph's existing guard list stays verbatim.

**Edit 3 (clock monotonicity error).**
- (a) Subject: rejection behavior of the clock-setting endpoint.
- (b) Enumerated paths (grep `current_utc|set_current_utc|monotonically`): `routes_core.py:109-125` (`set_clock` — sole writer of `current_utc`; unparseable and backward values both → `ERR_INVALID_REQUEST`; equal values accepted, matching "non-decreasing"); `routes_core.py:94` (boot clock on org-unit creation); `business.py:192,201,208`, `routes_core.py:317,334,343,471,538,564`, `routes_pips.py:211,289,292,339`, `routes_outcomes.py:176,288,291,328,353` (all read-only clock consumers — unaffected).
- (c) Wording adjustment: pinned only the backward-value case (the one Step 7's fixture tripped); left the malformed-value case unpinned to keep the edit minimal, and preserved "monotonically non-decreasing" verbatim so equal-value sets remain permitted.

### Items evaluated but not edited (PRD already determines impl behavior, or pure test/fixture bugs)

- Proposal-time application of the three outcome guards — §3.6 already verbatim; impl `routes_outcomes.py:237`.
- Template geometry enforced at authoring AND publication — §3.3 already verbatim; impl `routes_core.py:418-422` and `:463-467`.
- Evidence SoD adjudication (different HRBP) — §3.4 already verbatim; impl `routes_pips.py:368-371`.
- Concern-summary 20-char / rationale 40-char minimums — §3.2/§3.6 already verbatim; impl `routes_core.py:246`, `routes_outcomes.py:230`. Fixture bugs only.
- SoD-before-attainment-guard ordering at proposal — §2.6 ordering already verbatim; impl `routes_outcomes.py:233` before `:237`.
- test_07 OCC stale-version rewrite — impl never bumps plan version on check-in creation (`routes_pips.py:227-260` never touches the pip), which §2.4 already determines ("increments with every modification to the resource"); the tests' stale snapshot now derives from PRD-verbatim increments (issuance §3.3, approval §3.6). PRD and impl agree; no silence to pin.
- Deleted `test_termination_approve_without_legal_review_rejected` and the `test_legal_reject_supersedes_proposed_outcome` rewrite — both rest on the proposal-time legal gate, already verbatim in §3.6; impl `routes_outcomes.py:215-219, 81-89`.

Note: `test_suite/` and `test_helpers/` live at the task root (not inside workspace/), so verification was done directly against the implementation sources cited above.

## Step 9: Complete PRD — 2026-08-13T20:30:00.000Z

All edits verified. PRD_COMPLETED.md is complete. Here is the final report.

### Summary

**Source vs output**: `PRD_FINALIZED.md` 333 lines / 50,912 chars → `PRD_COMPLETED.md` 335 lines / 56,662 chars (+2 lines, +5,750 chars). 32 lines revised, 2 lines inserted (net), 34 added-line equivalents in diff.

**Counts**: 28 ambiguity-pins, 11 mismatch-revisions (39 total changes).

### Changes

- §2.2 — insert — ambiguity — Undefined path/unsupported method → `ERR_NOT_FOUND` 404; absent/unparsable JSON body treated as empty object; non-object JSON body → `ERR_INVALID_REQUEST`; required field absent/null → `ERR_INVALID_REQUEST` — app.py:27-45; core.py:334-347
- §2.3 — insert — ambiguity — Non-integer limit/offset, limit outside 1–100, negative offset → `ERR_INVALID_REQUEST` — core.py:295-316
- §2.3 — insert — ambiguity — Sort tie-break by creation order; filters are exact-match equality on string form, applied before sorting/pagination — core.py:319-331
- §2.3 — insert — ambiguity — `total_count` counts the filtered set; `has_more` true iff offset+limit < total_count — core.py:131-139
- §2.5 — insert — ambiguity — Stored timestamps normalized to UTC `Z` preserving the supplied fractional-second precision (clock, `occurred_at`, plan dates, `scheduled_for`, cycle windows) — core.py:215-226; routes_core.py:122
- §2.5 — revise — mismatch — Dropped "extended plans re-enter their active window" as a clock-driven transition (extension re-enters `ACTIVE` at approval); pinned sweep order: activation → missed sweep → rebuttal-lapse closures — business.py:242-282; routes_outcomes.py:296-306
- §2.6 — insert — ambiguity — Designated-actor `ERR_FORBIDDEN` rejections positioned at the step where each §3 workflow names its actor constraint — core.py:172-174
- §2.6 — insert — ambiguity — Full per-collection flat-list filter enumeration (all 14 flat lists) — routes_flat.py:38-212
- §2.6 — insert — ambiguity — Nested-list filter enumeration (employees/coaching/concerns/templates/pips/goals/check-ins/evidence/legal/decisions/rebuttals/cycles/links) — routes_core.py:177-528; routes_pips.py:143-355; routes_outcomes.py:132-493
- §2.8 — revise — mismatch — `expected_pip_version` is optional: checked only when present and non-null; absent/null skips the check — routes_pips.py:172-174; routes_outcomes.py:278-280
- §3.1 — insert — ambiguity — Blank org-unit `name` → `ERR_INVALID_REQUEST` — routes_core.py:88-90
- §3.1 — revise — mismatch — Removed "email unique within the org unit" (uniqueness never enforced) — routes_core.py:138-160
- §3.1 — revise — mismatch — `job_level` pinned as integer 1–10 with `ERR_INVALID_REQUEST` (was "numeric") — routes_core.py:141-144
- §3.1 — insert — ambiguity — `manager_id` recorded without existence validation — routes_core.py:145-147
- §3.1 — insert — ambiguity — Cycle window bounds must be parseable ISO 8601, otherwise recorded as given — routes_core.py:503-518
- §3.2 — insert — ambiguity — `occurred_at` must parse as ISO 8601 else `ERR_INVALID_REQUEST` — routes_core.py:197-200
- §3.2 — insert — ambiguity — `coaching_log_entry_ids` must be an array of strings; references validated only at submission; back-link populated only on entries that exist — routes_core.py:247-269
- §3.3 — insert — ambiguity — Template `category` drawn from the five coaching categories; blueprint field types (non-empty-string metric_key, numeric target_value, string unit, integer weight 1–100) with malformed blueprints → `ERR_INVALID_REQUEST` — routes_core.py:363-410
- §3.3 — revise — ambiguity — `ERR_TEMPLATE_NOT_PUBLISHED` fires ahead of concern checks; dangling (unresolvable) references → `ERR_REFERENTIAL_INTEGRITY` — routes_pips.py:84-97
- §3.3 — insert — ambiguity — Plan opens with `provisional_attainment_ratio` 0.0, `final_attainment_ratio` null, `extension_count` 0, `rebuttal_window_closes_at`/`closed_at` null — routes_pips.py:104-121
- §3.3 — revise — mismatch — Issue OCC wording aligned to optional semantics — routes_pips.py:172-174
- §3.3 — insert — ambiguity — Withdrawal leaves the concern `SUPERSEDED_BY_PIP` — routes_pips.py:188-194
- §3.4 — revise — ambiguity — Scheduling not gated on plan state; new instant must differ from every non-`CANCELLED` check-in by exactly `check_in_interval_days` days; `sequence_index` = count of existing check-ins (any status) + 1 — routes_pips.py:227-260
- §3.4 — revise — mismatch — mark-held check order pinned as state → plan-active → quorum → notes → clock (`ERR_CHECKIN_TOO_EARLY` last) — routes_pips.py:273-296
- §3.4 — insert — ambiguity — Scoreboard tie-break extended: latest `submitted_at`, then `created_at` descending, then creation order — routes_pips.py:298-309
- §3.4 — insert — ambiguity — Weighted ratio capped at 1.0 (applies to both variants) — business.py:139-141
- §3.4 — insert — ambiguity — Evidence submission gated neither on check-in status nor plan status — routes_pips.py:318-344
- §3.5 — insert — ambiguity — Legal review requestable in any plan state — routes_outcomes.py:96-124
- §3.5 — insert — ambiguity — Duplicate risk factors counted per occurrence — business.py:157-163
- §3.6 — insert — ambiguity — Proposals accepted in any non-closed plan state; closed (incl. `CLOSED_WITHDRAWN`) → `ERR_INVALID_STATE` — routes_outcomes.py:231-232
- §3.6 — revise — mismatch — Final-variant missed penalty: every non-waived goal's attainment × (1/2)^m, m = count of `MISSED` check-ins (was "per-interval goals") — business.py:120-142
- §3.6 — revise — mismatch — Approval order: outcome guards re-applied against the frozen `final_attainment_ratio` before the `ERR_PLAN_STILL_RUNNING` window check — routes_outcomes.py:287-289
- §3.6 — revise — mismatch — Approve OCC wording aligned to optional semantics — routes_outcomes.py:278-280
- §3.6 — revise — ambiguity — Every closure stamps `closed_at` and clears `active_pip_id` when pointing at the plan; outcome links written only for SUCCESS/TERMINATION closures; `link_created_at` stamped from the org-unit clock — business.py:197-216
- §3.7 — insert — ambiguity — `outcome_decision_id` must name an `APPROVED` decision of the plan else `ERR_INVALID_REQUEST`; multiple rebuttals per decision allowed — routes_outcomes.py:344-355
- §3.7 — insert — ambiguity — Rebuttal `status` is set to the resolution value (`UPHELD`/`OVERRULED`) — routes_outcomes.py:408-416
- §3.7 — insert — ambiguity — Upholding an approved TERMINATION closes `CLOSED_TERMINATED` with the §3.6 cascade; resolving a rebuttal on an approved EXTENSION is inert — routes_outcomes.py:417-430
- §3.8 — revise — mismatch — Consistency-review target need not be closed; it must carry an approved outcome decision, else empty cohort → `ERR_COHORT_TOO_SMALL` — business.py:289-296; routes_outcomes.py:451-467
- §4 — revise — mismatch — Consistency-review table row "against a closed PIP" → "against a PIP" — routes_outcomes.py:451-467

Notable design facts confirmed during the walk and left unchanged because the PRD already pinned them uniquely: the full 35-error catalogue matches the impl error table; all endpoint RBAC sets (nested + flat) match §4; the provisional/final attainment formulas, risk-score formula, cohort matching (±1 job level, 365-day trailing window, decided_at ordering), and disparity/alignment scores were already exactly pinned; the attainment formula's waived-goal handling (numerator includes waived weight × 1, denominator excludes it) matches the PRD's literal wording.

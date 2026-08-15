# Worklog — task_1865_sales_territory_quota_planning

## Step 1: Create Task Directory — 2026-08-14T21:37:00.000Z

Pre-existing per pipeline invocation: `tasks/task_1865_sales_territory_quota_planning/` and `workspace/` verified present. Requested difficulty: harder than expert level.

## Step 2: Generate Scaffold — 2026-08-14T22:32:00.000Z

All three artifacts are complete and verified. Final report:

## Task complete — task_1865_sales_territory_quota_planning

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1865_sales_territory_quota_planning/SCAFFOLD.yaml` (§1.0–§1.7; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1865_sales_territory_quota_planning/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1865_sales_territory_quota_planning/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Counts**
- Entities: **13** (PlanYear, Territory, AssignmentRule, Account, SalesRep, RampSchedule, RepAssignment, TopDownAllocation, BottomUpSubmission, ReconciliationRun, TerritoryChangeRequest, CreditEvent, OwnershipDispute)
- Endpoints: **67** (deliberately above the 20–32 expert band per the operator's harder-than-expert directive; ~20 are FK-reverse-reachability/filtered-list GETs)
- Errors: **40** | Validations: 8 priority rows | State machines: **10** | Calculations: **11** | Concurrency rules: **3** (all true OCC supersede-races on `PlanYear.version`) | Roles: **4** (SalesRep is `entity_backed:SalesRep`; others opaque)
- §1.8 instances: **18** (9 rules × 2, each with full structured `setup_api_calls`/`trigger`/`assert` and code-computed literals)
- §1.9 instances: **85** (76 full + 9 `excluded_because` stubs; 8 taxonomy sections)
- `scaffold_lint.py`: **clean** — 1115 calls scanned, zero violations, all FKs reverse-reachable. Verdict pasted above verbatim. A separate self-consistency script (grounds resolvability, placeholder closure, stub legality, name uniqueness, error-catalog usage) also passes; forbidden-vocabulary scan clean.

**Key design adjudications**
1. **Dual-variant domains (Rule 1):** `reconciliation_policy` (TOP_DOWN_WINS vs BLENDED midpoint) on Territory quota; `credit_transition_policy` (PRORATE_BY_DAY vs MONTH_SNAPSHOT with day-15 cutoff) on rep attainment.
2. **Tolerance trap:** BLENDED escalation uses integer-exact `|diff|*100 > top*10`; `deviation_pct` is display-only — 1,100,001 over 1,000,000 displays 10.00 yet escalates.
3. **Ramp:** pinned two-step rounding (round monthly base, round each month, integer sum — sum-then-round declared invalid), day-15 hire cutoff, tenure ≥13 → 1.00.
4. **Allocation:** largest-remainder by fractional part DESC, tie `created_at` ASC; zero-weight equal-split fallback; leaf landing; root pool == `company_target_cents`, non-root pool == scope's assigned quota (ERR_POOL_MISMATCH); supersede keeps the pool invariant.
5. **Retained-quota model:** rep shares split `assigned − Σ ACTIVE children's assigned` (and likewise for finals), which keeps parent/child quota accounting double-count-free.
6. **Mid-year change:** quota transfer = `round_half_up(potential × full remaining months / 12)` (transition month stays with source); credit transfer scope = POSTED BOOKING events in `[transition_month_start, apply_date]`; TRANSFER_OUT rounded half-up, TRANSFER_IN exact largest-remainder so plan-wide attainment is conserved to the cent; reversing a source booking never cascades to transfers.
7. **Disputes** reassign accounts but never move quota; open disputes block plan lock; SLA escalation is strict `current_date > filed_date + 7` via an ops checkpoint.
8. **Interval contrast (Rule 8):** RepAssignment windows half-open (adjacency legal) vs PlanYear ranges closed (touching months collide).
9. **SoD** on change approval keyed on X-User-ID, not role.
10. Clock endpoint carries the mandated default `2026-08-01T00:00:00Z`; plan years are exactly 12 calendar months with day-01/last-day shape validation.

One repair cycle occurred during authoring: two errors (ERR_DUPLICATE_SUBMISSION, ERR_NOT_TERRITORY_MEMBER) were referenced in validations but missing from the §1.6 catalog, and one corner fixture (credit-reversal) initially produced negative territory finals — fixed by giving the fixture a root territory and allocation. Post-fix lint is clean.

## Step 3: Copy Shared Files — 2026-08-14T22:32:30.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T22:50:00.000Z

The PRD is complete and fully audited. Final report below.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_1865_sales_territory_quota_planning/workspace/PRD.md` — 329 lines. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## PRD Section List

- **1. Introduction** (2 paragraphs: business context; post-communication ledger + role segregation)
- **2. Global Specifications & System-Wide Principles**
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (emitted **byte-verbatim** from `section-2.2-response-structure.md`, verified programmatically: MATCH)
  - 2.3 Pagination (limit default 10 / min 1 / max 100, offset default 0, `created_at` ascending, meta fields)
  - 2.4 Common Resource Properties and the Logical Clock (UUID `id`, ISO-8601 3-fractional-digit timestamps, `version`; clock default 2026-08-01T00:00:00Z, `to_iso8601`/`current_utc`)
  - 2.5 Money, Integer Cents, and Pinned Rounding (largest-remainder convention, round-half-up, pinned two-step ramp rounding, integer-exact tolerance comparisons)
  - 2.6 Validation Pipeline and Evaluation Order (all 8 priority tiers with intra-tier orderings)
  - 2.7 Optimistic Concurrency Control on the Plan Year (all 3 OCC rules)
  - 2.8 Cross-Plan Referential Integrity
  - 2.9 Retained Quotas, Freezing, and Cascades
- **3. Business Logic & Workflows** (9 subsections, lifecycle-timeline strategy)
  - 3.1 Plan Year Setup, Shape Rules, and the Lifecycle Spine
  - 3.2 Building the Territory Hierarchy
  - 3.3 Assignment Rules and Account Routing
  - 3.4 Reps, Ramp Schedules, and Territory Staffing (incl. coverage report)
  - 3.5 Top-Down Quota Allocation
  - 3.6 Bottom-Up Submissions and Reconciliation
  - 3.7 Communication, Locking, and Booking Credit
  - 3.8 Mid-Year Territory Changes and Credit Transition
  - 3.9 Ownership Disputes and the Review SLA
- **4. Endpoint Definitions** (67 rows, 4 columns; method/path/roles verified cell-by-cell against the scaffold — 0 mismatches, 0 extras)
- **5. Error Code Catalogue** (40 rows, 2 columns; every id and HTTP status verified against the scaffold — 0 mismatches)

## Coverage Audit (Hard Contracts)

```
Field coverage check (Contract 1):
- entities[].fields + request_body/input + query_params + path_params + response-only keys:
  95 required, 95 present, 0 missing
Status: PASS

Rule coverage check (Contract 2):
- validations[] priority tiers: 8 checked, 8 expressed with explicit ordering
  (incl. tier-4 intra-row order, tier-5 cross-plan-first, tier-6 shape-before-overlap), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed
  (allocation apply, reconciliation apply, change approve — expected_plan_year_version +
   ERR_STALE_VERSION + HTTP 412 + supersede-rationale each named), 0 missing
- state_machines[].transitions: 35 checked (across 10 machines), 35 fully expressed
  (every from→to pair, precondition→error_id pairing, and side effect incl. all cascade hops), 0 missing
- calculations[]: 11 checked, 11 fully expressed as reconstructible prose
  (allocation_largest_remainder, assignment_resolution, rep_base_share, ramp_quota,
   reconciliation_final w/ both variants + display-only deviation_pct, rep_final_share,
   credit_split_at_booking, credit_transition_transfer w/ both variants, attainment_rollup,
   coverage_model, dispute_sla_escalation), 0 missing
- validations[] conditions: all error_ids matchable to trigger prose in §2/§3
  (verified: 40/40 ids appear outside §5), 0 missing
- endpoints[].side_effects / applies_to: all expressed (checkpoint lock-ins, supersede,
  no-auto-reevaluate rules, output-field names), 0 missing
- entities[].fields[] structured content: defaults/nullability/freeze semantics reconstructible, 0 missing
- sibling-branch symmetry: 6 groups checked (dispute withdraw ×3, start-review ×2, cancel ×2,
  resolve ×2, recon variants ×2, credit-transition variants ×2), 6 symmetric, 0 asymmetric
Status: PASS

Path purity check (Contract 3, §3 only):
- backtick tokens scanned: 530
- tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path combos: 0
Status: PASS
```

Additional scans: no pseudocode operators (`==`, `>=`, `floor(`, …) in prose; no fuzzy/approximating words; all 62 state/enum values present as exact backticked strings; all 4 role names exact with `identity:` prose per role; 0 paragraphs starting "The system".

## Zero-Silence-Rule Adjudications

Where the scaffold names a gate but not its error, I resolved as follows (each noted so reviewers can overrule):

1. **Reconciliation-run compute outside SUBMISSIONS_CLOSED|RECONCILED** → mapped to `ERR_INVALID_STATE_TRANSITION` (the catalog already assigns that id to reconciliation apply/discard phase violations; create extends the same gate).
2. **Rep-assignment create window**: `effective_to` beyond plan end → `ERR_DATE_OUT_OF_PLAN_YEAR`; inverted window (`effective_to` not after `effective_from`) → `ERR_INVALID_REQUEST` (mirrors the end-transition's own error).
3. **Territory re-parent after plan DRAFT** → `ERR_PLAN_NOT_OPEN` (or `ERR_PLAN_LOCKED` when LOCKED), per the tier-4 gate taxonomy.
4. **Change-request destination ACTIVE check at approve** → `ERR_TERRITORY_NOT_ACTIVE`, same id as at apply (field description requires the check at both checkpoints; the state machine lists the id only at apply).
5. **evaluate-assignments while LOCKED** → blocked with `ERR_PLAN_LOCKED` (it is a configuration mutation absent from the LOCKED exception list).
6. **Scaffold-internal status inconsistency**: validation tier 7's blanket "409 otherwise" conflicts with the error catalog's 422 for `ERR_SAME_TERRITORY_TRANSFER` and `ERR_CLAIMANT_TERRITORY_INVALID`; I followed the error catalog (authoritative for HTTP status) in both §5 and the §2.6 tier-7 sentence.

## Step 5: Generate Unit Tests — 2026-08-14T23:20:00.000Z

Both runs green: 109/109, twice consecutively. The suite is complete and deterministic. Here is the verbatim summary.

---

## Task 1865 test generation — summary

**Test counts by queue**
- Queue A (Difficulty): 18 instances in §1.8 → 17 translated, 34 tests (≥2 per instance). 1 skipped.
- Queue B (Corner): 85 instances in §1.9 = 76 non-stub + 9 `excluded_because:` stubs → 75 translated, 75 tests (≥1 per instance). 1 skipped. All 9 stub cross-references resolve to real §1.8 instances; no stub was translated.
- **Total: 109 tests** across 11 files in `test_suite/`.

**Instances skipped (two-condition reasons)**
1. `Difficulty/cross_entity_state_dependency/submission_requires_active_territory` — **coverage fails**. No verbatim PRD sentence names `ERR_TERRITORY_NOT_ACTIVE` as a precondition of submission create: §3.6 lists only the OPEN-window, membership (`ERR_NOT_TERRITORY_MEMBER`), duplicate, and positive-amount guards, and §2.6 tier 4 mentions "territory-activity requirements" only generically. In the recipe's setup (rep not yet assigned to the DRAFT territory) a faithful PRD-only implementer could answer `ERR_NOT_TERRITORY_MEMBER` — outcome not uniquely derived either.
2. `Corner/calculations/coverage_status_gap_to_understaffed_to_covered` — **unique derivability fails**. The claim lives on coverage-report row fields (`coverage_status`, `staffing_gap`, `active_rep_count`, `required_headcount`) whose JSON key names the PRD never pins; §3.4 names only the report header fields. Two faithful readers could emit different row shapes; the GAP→UNDERSTAFFED→COVERED transition is unobservable through any PRD-named field.

**Adjudication notes on generated instances**
- `Corner/.../plan_version_increments_on_mutation`: generated with version assertions only (1 → 2 on open). The instance's `updated_at`-changed sub-assertion was dropped — §2.4 routes all time-sensitive behavior through the logical clock and never states `updated_at` must differ between two mutations without a clock advance.
- `Difficulty/boundary_precision_check/coverage_headcount_exact_multiple_boundary`: generated using only PRD-named observables — territory `assigned_quota_cents` (3000001 vs 3000000) and report header totals (`total_required_headcount == 5 == 3+2+0`, which fails any off-by-one ceil at the exact multiple). Unnamed per-row keys were not asserted.
- `Difficulty/dual_variant_calc/credit_transition_day_proration_vs_month_snapshot`: the recipe's choreography applies plan M's change request at logical 2029-07-05, before its 2029-07-10 effective date (would draw `ERR_CHANGE_NOT_YET_EFFECTIVE`). Minimally repaired: clock driven to 2029-07-25 (≥ both effective dates) before the applies; no asserted value changes.

**Helper files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1865_sales_territory_quota_planning/test_helpers/`): `types.py` (17 status enums + 13 entity TypedDicts), `api_client.py` (48 endpoint methods), `api_errors.py` (40 error IDs + HTTP map registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque-role constants + `make_sales_rep_headers` entity-backed builder), `fixtures.py` (lifecycle walkers, leaf/two-territory/change-apply/dual-policy/tolerance/ramp-boundary composites), `__init__.py` barrel. `fixtures.py` includes a `tick_clock()` nudge in territory/assignment/rule creators so `created_at` is strictly increasing in call order — making the PRD's creation-order tie-breaks deterministic under both logical-clock and wall-clock timestamp readings.

**Stage 2 self-audit results**
- Tag audit: 109/109 tests carry exactly one `Design:` line as the final docstring line; all resolve to real instances; none point at stubs; no dual tags.
- Coverage audit: queue A 17/17 × ≥2; queue B 75/75 × ≥1.
- Citation audit: all 162 quoted fragments (≥8 words) survive literal whitespace-normalized grep of `workspace/PRD.md`; every docstring carries a rule-bearing PRD citation (C1/C2/C3).
- Error-ID audit: all 38 distinct asserted `error_id`s are named in PRD narrative prose, not just the §5 table.
- No `skip`/`skipif`/`xfail` markers; no scaffold references in generated code; pyflakes clean; pytest collects 109 cleanly.
- Execution verification: full suite **109 passed / 0 failed, twice consecutively** under `--isolation per-test-server` against the existing `workspace/implementation` (first pre-fix run: 108/109, the one failure being the creation-order nondeterminism that `tick_clock()` eliminated).

## Step 6: Generate Implementation — 2026-08-14T23:20:00.000Z

Implementation complete. Here is the verbatim summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1865_sales_territory_quota_planning/workspace/implementation/`)

- `start.sh` — foreground launcher, guarded `pip install` (no-op when flask present), `exec python3 app.py`
- `requirements.txt` — `flask>=3.0,<4`
- `app.py` — Flask app factory, blueprint registration, `ApiError`/404/405/500 handlers all emitting the scaffold error envelope
- `db.py` — in-memory `Store` (13 collections, empty at boot, no seeding), logical clock defaulting to `2026-08-01T00:00:00Z`, 3-fractional-digit ISO timestamps
- `errors.py` — full 41-entry error catalog with exact ids and HTTP statuses
- `response.py` — envelope helpers: `meta{api_request_id, api_request_timestamp}`, `response_type`, `data`; list responses add `limit`/`offset`/`total_count`/`has_more` in `meta`
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction (tier-1), role gate (tier-2); roles `SalesOpsAdmin|SalesOpsAnalyst|RevOpsManager|SalesRep`
- `util.py` — UUIDs, `touch()` (updated_at + version++), strict date parsing, round-half-up helpers, body/field validation, pagination (default 10, min 1, max 100)
- `services/calc.py` — all calculation engines, serializers, cascade machinery
- `routes/plan_years.py` — clock + plan-year CRUD/lifecycle/evaluate/coverage
- `routes/territories.py` — territory CRUD + activate/deactivate/retire
- `routes/rules_accounts.py` — assignment rules, accounts, reps, ramp schedules
- `routes/rep_assignments.py` — rep assignment create/list/get/end
- `routes/allocations.py` — top-down allocations + apply/discard
- `routes/submissions.py` — bottom-up submissions + withdraw
- `routes/reconciliation.py` — reconciliation runs + apply/discard
- `routes/change_requests.py` — change requests + approve/reject/return/cancel/apply
- `routes/credit_events.py` — credit events create/list/get/reverse
- `routes/disputes.py` — disputes + start-review/resolve/withdraw + SLA checkpoint

## Endpoint count
**67 endpoints** — verified by diffing the Flask route table against the scaffold §1.5 endpoint table: zero missing, zero extra (includes `POST /_clock/set_current_utc` outside the `/sales-planning` prefix).

## State machines implemented (10)
PlanYear (DRAFT→OPEN→SUBMISSIONS_CLOSED→RECONCILED→COMMUNICATED→LOCKED, incl. superseding apply self-loop), Territory (DRAFT⇄ACTIVE→RETIRED with account/assignment/children guards), AssignmentRule (ACTIVE⇄DISABLED, named-rule uniqueness re-check on enable), RepAssignment (ACTIVE→ENDED with 3-hop cascade + freeze), TopDownAllocation (DRAFT→APPLIED/DISCARDED, APPLIED→SUPERSEDED by system), BottomUpSubmission (SUBMITTED→WITHDRAWN/LOCKED_IN), ReconciliationRun (COMPUTED→APPLIED/DISCARDED), TerritoryChangeRequest (PENDING→APPROVED/REJECTED/CANCELLED, APPROVED→PENDING/CANCELLED/APPLIED with segregation-of-duties and effective-date clawback gate), CreditEvent (POSTED→REVERSED, no cascade to derived transfers), OwnershipDispute (FILED→UNDER_REVIEW/ESCALATED/WITHDRAWN, ESCALATED→UNDER_REVIEW, UNDER_REVIEW→RESOLVED_UPHELD/RESOLVED_OVERRULED/WITHDRAWN).

## Calculations implemented (10)
`allocation_largest_remainder` (exact-rational floors, fractional-part DESC + created_at tie-break remainder, zero-weight equal split, zero-children retention), `assignment_resolution` (NAMED pass first, GEO specificity/priority/created_at ranking, never auto re-evaluates), `rep_base_share` (retained top-down equal split, floor + remainder by created_at), `ramp_quota` (pinned two-step round-half-up: monthly base then per-month contribution then integer sum; hire-after-15th tenure shift; ti≥13 → 1.00), `reconciliation_final` (both TOP_DOWN_WINS and BLENDED variants, integer-exact 10% tolerance, display-only `deviation_pct` never feeds comparison), `rep_final_share` (retained-final split, null child final treated as 0), `credit_split_at_booking` (window-covering ACTIVE reps, floor + remainder), `credit_transition_transfer` (both PRORATE_BY_DAY `new_days/days_in_month` and MONTH_SNAPSHOT day-15 cutoff variants, TRANSFER_OUT/TRANSFER_IN conservation, chronological processing), `attainment_rollup` (signed POSTED sum, pct denominator switches to final at RECONCILED+, null when denominator null/0), `coverage_model` (ceil headcount with exact-division boundary, NO_QUOTA/GAP/UNDERSTAFFED/COVERED), `dispute_sla_escalation` (strictly-greater than filed_date+7 days, checkpoint-driven).

## PRD-interpretation adjudications
1. **Reconciliation-apply cascade ordering**: the plan's `SUBMISSIONS_CLOSED→RECONCILED` flip is executed *before* the hop-2/3 cascade so that final-share and attainment-pct recompute see the reconciled denominator basis (the state-machine side-effect list implies the plan lands in RECONCILED as part of the same apply act).
2. **`ramp_quota` applies even to fully-ramped reps** (null schedule ≡ all-1.00 multipliers), so `final_quota_cents` = `ramp_quota(share)` ≠ raw share — e.g. share 512501 yields 512496 after monthly-base rounding. Verified against the pinned rounding-order prose.
3. **`expected_plan_year_version` missing** on the three OCC endpoints is treated as `ERR_INVALID_REQUEST` (400) since PRD §2.7 declares the field "non-optional on exactly these three operations"; a present-but-mismatched value is `ERR_STALE_VERSION` (412).
4. **Credit-event creation** returns HTTP 201 with `response_type: "array"` and no pagination fields in `meta` (it is a create returning a collection, not a list endpoint).
5. **Validation pipeline ordering** implemented per PRD §2.6 tiers with intra-tier-4 order LOCKED → phase gates → entity from-state → territory-activity, and tier-5 cross-plan check before `ERR_FROM_TERRITORY_MISMATCH`; ownership checks (submission/dispute withdraw, change-request cancel) run at tier 2, before plan gates.
6. **RepAssignment end** validates `effective_from < effective_to <= plan.end_date` as `ERR_INVALID_REQUEST` per the state-machine precondition (scaffold explicitly names that error id there), rather than `ERR_DATE_OUT_OF_PLAN_YEAR`.
7. **Multiple LOCKED_IN submissions per territory**: the earliest by `created_at` is used as the bottom-up figure (the PRD's one-SUBMITTED-at-a-time rule plus close-submissions locking makes multiples possible only via sequential submit→withdraw cycles).
8. **Assignment creation runs attainment rollup** for the rep so pre-existing plan events (possible only via re-creation edge cases) are reflected; fresh reps get 0.

## Verification
Two self-authored suites (87 checks in `/tmp/smoke1865.py`, 37 in `/tmp/edge1865.py`) pass against a fresh `bash start.sh` boot covering: full lifecycle spine, envelope/pagination shape, RBAC and ownership checks, both reconciliation policies, largest-remainder conservation, ramp rounding order, OCC 412s on all three guarded endpoints, PRORATE_BY_DAY transfer amounts (548/2000 split with exact conservation), quota transfer month indexing, freezing on END, dispute SLA D+7/D+8 boundary, lock blockers, coverage classification, and validation-pipeline precedence.

## Step 7: Run Tests and Iterate — 2026-08-14T23:35:00.000Z

All 8 parallel rounds completed cleanly: 109/109 passed in every round (872 total test executions, 0 failures, 0 errors, 0 skipped).

**Summary**

- **Iterations run**: 1 (single 8-round parallel stability sweep; exit condition met on first sweep).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `implementation/`**: none.

The suite at `/home/ubuntu/github/CodingPRD/tasks/task_1865_sales_territory_quota_planning/test_suite/` (109 tests across 11 files) passed in all 8 concurrent rounds under `--isolation per-test-server`, with the union of failures across rounds empty — no flakiness signal. This independently confirms the generator's prior 2× green runs; no diagnostic steps (STEP 1 coverage/unique-derivability, STEP 2 test-vs-PRD consistency, STEP 3 implementation fix) needed to be invoked.

## Step 8: Finalize PRD — SKIPPED — 2026-08-14T23:35:30.000Z

Skipped per pipeline rule: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes. PRD.md already determines every behavior the implementation exhibits.

## Step 9: Complete PRD — 2026-08-15T00:05:00.000Z

All 23 edits verified in place. The work is complete.

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1865_sales_territory_quota_planning/workspace/PRD_COMPLETED.md`

**Size:** PRD.md 329 lines / 66,774 chars → PRD_COMPLETED.md 331 lines / 71,036 chars (**+2 lines, +4,262 chars**). All changes are inline inserts/revisions within existing paragraphs — no new sections.

**Counts:** 18 ambiguity-pins, 7 mismatch-revisions (across 23 edited passages).

**Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):**

- §2.2 — insert — ambiguity — unexpected server failures wrapped in envelope as `ERR_INTERNAL` (500) — `implementation/app.py:40-45`
- §2.3 — revise — ambiguity — non-integer/out-of-range `limit` and non-integer/negative `offset` fail `ERR_INVALID_REQUEST`; equal creation timestamps (common under the frozen logical clock) tie-break by `id` ascending, also for §3 "creation order" distributions; `has_more` = `offset` + returned < `total_count` — `implementation/util.py:173-194`, `implementation/response.py:33`
- §2.4 — insert — ambiguity — a recomputation landing an equal value is not a mutation (no `updated_at`/`version` bump) for share/ramp/final/attainment recomputes, reconciliation-applied finals, and sweep account rewrites; allocation-apply and change-request-apply territory quota writes and new-account resolution always re-stamp — `implementation/services/calc.py:343-430`, `implementation/routes/allocations.py:134-138`, `implementation/routes/change_requests.py:276-282`, `implementation/routes/rules_accounts.py:216-217`
- §2.4 — revise — mismatch — clock may move forward **or backward** (was "advance"); offset-less `to_iso8601` read as UTC, offsets converted — `implementation/routes/plan_years.py:32-41`
- §2.6 — insert — mismatch — submission create/withdraw on a `LOCKED` plan fail `ERR_SUBMISSION_WINDOW_CLOSED`, not `ERR_PLAN_LOCKED` (carve-out from locked-first rule) — `implementation/routes/submissions.py:31-33,103-105`
- §2.6 — insert — mismatch — body-inspection scope: plan lifecycle actions and submission withdraw never parse the body; change-request cancel/apply, dispute start-review/withdraw, credit-event reverse, and the SLA checkpoint reject only unparseable/non-object bodies and tolerate unknown fields — `implementation/routes/plan_years.py:139-247`, `implementation/routes/submissions.py:94`, `implementation/routes/change_requests.py:204,234`, `implementation/routes/disputes.py:110,149,166`, `implementation/routes/credit_events.py:145`
- §2.7 — insert — ambiguity — OCC check ordering (after plan-phase gate and, on approve, after segregation-of-duties; before from-state); missing/null/non-integer `expected_plan_year_version` → `ERR_INVALID_REQUEST` 400 — `implementation/routes/allocations.py:84-101`, `implementation/routes/reconciliation.py:76-93`, `implementation/routes/change_requests.py:131-148`
- §3.1 — revise — ambiguity — policy defaults apply when omitted **or explicitly null** — `implementation/routes/plan_years.py:67-70`
- §3.1 — insert — ambiguity — plan-year list filterable by `status` — `implementation/routes/plan_years.py:119-121`
- §3.1 — revise — mismatch — locked-plan paragraph carve-out: submission window gate answers `ERR_SUBMISSION_WINDOW_CLOSED` on locked plans — `implementation/routes/submissions.py:31-33,103-105`
- §3.2 — insert — ambiguity — `headcount_capacity` below one → `ERR_INVALID_REQUEST` — `implementation/routes/territories.py:62`
- §3.2 — insert — mismatch — territory creation fires the locked check before parent existence/same-plan validation (tier 4 before tier 3 here) — `implementation/routes/territories.py:66-77`
- §3.3 — insert — ambiguity — rules creatable at any point before lock — `implementation/routes/rules_accounts.py:66-68`
- §3.3 — insert — mismatch — rule creation fires the locked check before territory/pinned-account existence validation — `implementation/routes/rules_accounts.py:66-82`
- §3.3 — insert — ambiguity — accounts creatable at any point before lock; freshly created account answers `version` 2 (resolution stamped post-creation) — `implementation/routes/rules_accounts.py:201-218`
- §3.3 — insert — ambiguity — evaluate-assignments sweep permitted at any pre-lock phase; rule list filters `plan_year_id`/`territory_id`/`named_account_id`/`status` — `implementation/routes/plan_years.py:227-228`, `implementation/routes/rules_accounts.py:112-120`
- §3.4 — insert — ambiguity — malformed-window check fires before the plan-phase gate on create; new assignment answers `version` 2 when a retained quota split lands on it, else `version` 1 — `implementation/routes/rep_assignments.py:47-51,95-113`
- §3.4 — insert — ambiguity — end-assignment window rule enforced after plan-phase and from-state checks — `implementation/routes/rep_assignments.py:154-167`
- §3.4 — revise — ambiguity — coverage row field names pinned (`territory_id`, `retained_quota_cents`, `active_rep_count`, `required_headcount`, `staffing_gap`, `coverage_status`) — `implementation/services/calc.py:724-731`
- §3.5 — insert — ambiguity — allocation apply checks the run's `DRAFT` from-state after OCC, before scope-active — `implementation/routes/allocations.py:98-105`
- §3.8 — insert — ambiguity — `rejection_reason` and `return_reason` accepted but not persisted (two edits) — `implementation/routes/change_requests.py:163-196`
- §3.9 — insert — ambiguity — dispute resolve `note` accepted but not persisted — `implementation/routes/disputes.py:119-141`
- §3.9 — insert — ambiguity — dispute-SLA checkpoint invocable at any plan phase — `implementation/routes/disputes.py:162-168`
- §5 — insert — mismatch — `ERR_INTERNAL` | 500 row added (catalogue claimed to enumerate every error id) — `implementation/app.py:45`

Notable finding driving the largest revisions: the implementation's submission window gate fires before (and instead of) the locked-plan gate, and several no-input action endpoints ignore bodies entirely — both contradicted §2.6/§3.1's universal claims and were revised to match the implementation.

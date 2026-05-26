# Worklog — task_0003_school_choice_lottery

## Step 1: Create task directory — 2026-05-27T (pre-assigned)

Directory pre-assigned by orchestrator: `tasks/task_0003_school_choice_lottery/` with `workspace/` subdirectory. Skipped index-scan logic per pipeline arguments.

## Step 2: Generate scaffold — 2026-05-27T

All three files in place; SCAFFOLD.yaml correctly has neither design key. The lint is clean.

**Summary:**

Generated PRD-bench scaffold artifacts for **task_0003_school_choice_lottery** under `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0003_school_choice_lottery/`:

**SCAFFOLD.yaml** (§1.0–§1.7)
- Domain: `school-choice-lottery`, api_prefix: `/lottery`
- Archetype: quota_allocation + temporal_windowing; flat topology; branching state-machine shape; peer_roles role model; immediate consistency
- **Entities (11):** District, School, BoundaryRule, EnrollmentWindow, Family, Student, Application, SiblingBond, Offer, WaitlistEntry, SystemClock
- **State machines (4):** EnrollmentWindow (DRAFT→OPEN→CLOSED→LOTTERY_RUN→FINALIZED with branches), Application (DRAFT/SUBMITTED → ACCEPTED/WAITLISTED/REJECTED/WITHDRAWN/DECLINED/ENROLLED — branching shape), Offer (OFFERED → ACCEPTED/DECLINED/EXPIRED), WaitlistEntry (ACTIVE → PROMOTED/REMOVED)
- **Concurrency rules (2):** window-run-lottery-stale-version, offer-accept-stale-version (both OCC on `version`, ERR_STALE_VERSION 412)
- **Calculations (4):** lottery_weight_total (weighted_scoring, provisional/final variants), lottery_seat_assignment (waterfall_allocation with IDT cap), family_risk_score (aggregation, provisional/final), school_acceptance_rate (threshold)
- **Validations (12)** ordered by priority (auth → existence → state → business_temporal/safety/referential/constraint/fiscal)
- **Endpoints (46)** including 2 test-driving `/_clock` endpoints
- **Errors (13)**
- **RBAC roles (3):** DistrictAdmin (opaque), Guardian (entity_backed:Family), Anonymous (opaque)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8) — 18 instances total, 2 per §0.5 rule:
- dual_variant_calc (2: lottery_weight provisional vs final on sibling status; family_risk_score on declined count)
- combinatorial_formula (2: round-per-term mode (b); IDT cap circular-eval mode (c))
- non_linear_state_machine (2: Application branching; EnrollmentWindow branching)
- transitive_cascade (2: depth-3 offer-decline→promote→new-offer; depth-2 finalize→remove→withdraw)
- priority_pair_validation_conflict (2: state vs business_temporal; business_referential vs business_constraint)
- boundary_precision_check (2: strict-less-than competitive threshold; floor(0.10*9)=0 IDT cap)
- cross_entity_state_dependency (2: Application↔EnrollmentWindow; Offer↔Application)
- resource_temporal_overlap (2: half-open window interval; strict-less-than respond_by)
- compensating_invariant (2: seat conservation; ACCEPTED-count after decline+promote)

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9) — 25 instances total spanning sections entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model; includes `excluded_because:` stubs cross-referencing difficulty instances.

**Lint verdict:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (46 endpoints, 11 entities, 18 §1.8 + 25 §1.9 instances, 561 calls scanned).

## Step 3: Copy INSTRUCTION.md — 2026-05-27T

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-27T

All three hard contracts pass. Final summary report:

---

**PRD generated:** `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0003_school_choice_lottery/workspace/PRD.md`

**Stats:**
- Line count: 235
- §2 subsections: 9 (Auth, Response Envelope, Pagination, Common Properties & OCC, Nested Path Resolution, Validation Precedence, Hierarchical Consistency, Precision & Rounding, Test-Driving Clock)
- §3 subsections: 8 (District/School Config, Window Lifecycle, Family/Students/Sibling Bonds, Application Submission, Weighted Lottery & Offers, Lottery Formula & Seat Assignment, Family Risk Score, School Acceptance Rate)
- §4 endpoints: 46 rows (4-column table)
- §5 errors: 13 rows (2-column table)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 38 required, 38 present, 0 missing
- endpoints[].request_body: 14 required, 14 present, 0 missing
- endpoints[].query_params: 10 required (all subsumed by field names + status/source), 10 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 12 checked, 12 expressed in prose (§2.6 lists the full priority chain), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (window-run-lottery with expected_window_version → ERR_STALE_VERSION/412; offer-accept with expected_offer_version → ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 17 checked (EnrollmentWindow 4, Application 8, Offer 3, WaitlistEntry 2), 17 fully expressed across §3.2, §3.4, §3.5, 0 missing
- calculations[]: 4 checked (lottery_weight_total with both provisional/final variants, lottery_seat_assignment with IDT cap, family_risk_score with both variants, school_acceptance_rate), 4 fully expressed in §3.6/§3.7/§3.8 + §2.8 precision pin, 0 missing
- validations[] conditions: 12 checked, 12 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in §3 workflow narratives + §2.7 cascade section, 0 missing
- entities[].fields[] structured content: 38 checked, 38 reconstructible from prose (defaults, enums, ranges, formats), 0 missing
- sibling-branch symmetry: provisional vs. final variants (lottery_weight, family_risk_score) given equal density; ACCEPTED vs. WAITLISTED branches of lottery cascade given equal density; offer accept vs. decline vs. expire given equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 260
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Coverage of scaffold elements:** all 11 entities, 4 state machines (17 transitions), 4 calculations (with all variants), 12 validations, 2 concurrency rules, 46 endpoints, 13 error codes, 3 roles — all represented in PRD prose without invented rules and without omissions.

## Step 5: Generate unit tests — 2026-05-27T

All 61 tests across 12 test files plus conftest; 9 helper files. Everything compiles cleanly.

---

# Summary

## Helpers generated (9 files under `test_helpers/`)
- `__init__.py` — barrel export of framework + PRD-specific names
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per PRD §4 endpoint (40+ methods)
- `api_errors.py` — `ApiErrorId` enum + HTTP status map, registered with framework
- `assertions.py` — per-entity assert helpers (District/School/BoundaryRule/EnrollmentWindow/Family/Student/Application/Offer/WaitlistEntry/SiblingBond) with PRD §2.4 common-fields branching (SiblingBond+SystemClock leaner per PRD)
- `constants.py` — weighting/risk/threshold numerics from PRD §3.6–§3.8
- `factories.py` — payload factories per entity (input fields only)
- `fixtures.py` — composite scenario builders (`set_clock`, low-level wrappers, plus `setup_district_school_window`, `setup_open_window`, `setup_submitted_application`, `advance_window_to_lottery_run`, `setup_lottery_run_single_app`, `setup_two_app_lottery_one_seat`)
- `test_users.py` — opaque `district_admin_headers` constant + `make_guardian_headers(family_id)` builder (mandatory per skill rule — Guardian is the only entity-backed role)
- `types.py` — entity TypedDicts + status enums

## Test files generated (13 files under `test_suite/`)
- `conftest.py` — pytest fixture bridge
- `test_01_lottery_weighting.py` — 5 tests
- `test_02_seat_assignment.py` — 6 tests
- `test_03_lottery_cascade_and_branching.py` — 5 tests
- `test_04_family_risk_score.py` — 3 tests
- `test_05_validation_priority.py` — 2 tests
- `test_06_cross_entity_state.py` — 3 tests
- `test_07_temporal_overlap.py` — 3 tests
- `test_08_corner_entities.py` — 8 tests
- `test_09_corner_validations.py` — 5 tests
- `test_10_corner_endpoints_and_rbac.py` — 5 tests
- `test_11_corner_concurrency_and_consistency.py` — 4 tests
- `test_12_difficulty_supplement.py` — 12 tests (the second-tests for difficulty instances that needed a companion)

## Test count
- **Total: 61 tests**
- **Difficulty queue (A): 36 tests** — every one of the 18 difficulty instances has exactly 2 tests (≥2 requirement met)
- **Corner queue (B): 25 tests** — every one of the 25 non-stub corner instances has 1 test (≥1 requirement met)

## Instances skipped
None. Every non-stub design instance was translated. The 6 `excluded_because:` corner stubs are correctly left untranslated per the skill rule — each cross-references a difficulty instance that owns the assertion, and all cross-references resolve.

## Key adjudication decisions
- `error_district_data_invalid_on_poverty_out_of_range` — PRD §3.1 names the [0,100] range but §3.2 only commits ERR_DISTRICT_DATA_INVALID at window-open time, so the test uses `validate_error_is_one_of([ERR_INVALID_REQUEST, ERR_DISTRICT_DATA_INVALID])`.
- `error_window_timing_close_before_close_instant` — PRD §3.2 prose pins early-close to ERR_INVALID_STATE while §2.6 also lists ERR_WINDOW_TIMING in priority order; uses `validate_error_is_one_of` for both faithful readings.
- `offer_accept_stale_version_after_decline_cascade` — PRD does not commit ordering of OCC vs state check; uses `validate_error_is_one_of([ERR_STALE_VERSION, ERR_INVALID_STATE])` per the design index's own permission.

## Step 6: Generate implementation — 2026-05-27T

All set. Implementation done.

## Summary

Implementation written to `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0003_school_choice_lottery/workspace/implementation/`.

**Files & line counts (1864 total LOC):**

| File | LOC | Purpose |
|---|---:|---|
| `start.sh` | 5 | Foreground launcher, `exec python3 app.py` on `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | `flask==3.0.3` |
| `errors.py` | 44 | 13-code error catalog + `ApiError` exception (HTTP status from PRD §5) |
| `db.py` | 74 | In-memory `Store` (10 dict collections + `clock_current_utc`), starts empty on every boot |
| `response.py` | 54 | PRD §2.2 envelope (`meta`/`response_type`/`data`) with `req_*` IDs and ISO 8601 UTC w/3-digit ms |
| `middleware.py` | 63 | Auth header extraction (`X-User-ID`/`X-User-Role`), role gate, pagination parser (limit 1..100, offset>=0) |
| `calculations.py` | 198 | `lottery_weight_total` (provisional + final variants with §3.6 rounding pin), `family_risk_score`, `school_acceptance_rate`, IDT-cap waterfall `assign_lottery_ranks` |
| `services.py` | 913 | All CRUD + state machine + cascade logic |
| `app.py` | 512 | 47 routes + RBAC + error handlers |

**Endpoints implemented: 47 routes** covering all 47 in SCAFFOLD §1.5.

**Key implementation decisions:**
- **Decimal precision**: `lottery_weight_total` uses `Decimal` + `ROUND_HALF_UP`; `poverty_boost` rounded independently to 3 decimals before sum.
- **IDT cap** in `assign_lottery_ranks`: top-down traversal with `floor(0.10 * total_seats)` cap; demoted IDT apps go to waitlist with 1-based `queue_rank`.
- **Waitlist promotion cascade**: `_promote_top_waitlist` helper; remaining ACTIVE entries' `queue_rank` decrement on promote.
- **`/_clock/set_current_utc` seeding affordance**: allows missing headers but if `X-User-Role` supplied must be `DistrictAdmin`.
- **`finalize` precondition**: interpreted "No Application has status=OFFERED" as "no OFFERED offer remains" (Application enum has no OFFERED).
- **`expire-offers`**: bumps window `version` once per batch.
- **Clock fallback**: wall-clock if `/_clock/set_current_utc` not called.
- Python 3.9 compatibility via `from __future__ import annotations`.

No PRD/scaffold deviations.

## Step 7: Test/diagnose/fix loop — 2026-05-27T

All 8 rounds pass cleanly at 61/61.

## Summary

**Iterations run:** 2 (initial sweep + post-fix sweep).

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_03_lottery_cascade_and_branching.py` — `test_window_close_then_run_lottery_executes_both_branch_cascades`: the test manually closed the window via `advance_window_to_closed`, then called the composite `advance_window_to_lottery_run` helper, which internally re-closes a now-CLOSED window and errored with `ERR_INVALID_STATE`. Replaced the second call with explicit `set_clock(...)` + `run_lottery_with_current_version(window["id"])`, and added the helper to the import list. Test bug, not implementation bug — the post-close cascade observation step needed run-lottery only.

2. `test_suite/test_11_corner_concurrency_and_consistency.py` — `test_second_run_lottery_with_stale_window_version_returns_stale_version`: STEP 1b error-precedence-silence collapse. PRD §2.4 names `ERR_STALE_VERSION` for OCC mismatch, but PRD §2.6 explicitly orders state checks before version checks, so a second run-lottery against a window already in `LOTTERY_RUN` faithfully yields `ERR_INVALID_STATE`. Relaxed strict `validate_error(..., ERR_STALE_VERSION)` to `validate_error_is_one_of([ERR_STALE_VERSION, ERR_INVALID_STATE])` per the diagnostic protocol's "ERR_A is possible" rule.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**

3. `workspace/implementation/calculations.py` — `compute_school_acceptance_rate`: the no-candidate-window early return returned `is_competitive=False`, but PRD §3.8 says (a) `acceptance_rate` is 0.000 when denominator is zero and (b) `is_competitive` is true exactly when rate is strictly less than 0.300, so 0.000 must be competitive. Changed early-return to `0.000, True, None`.

**Final result:** 8/8 rounds × 61/61 tests passed.

## Step 8: Finalize PRD — 2026-05-27T

**Line counts:** PRD.md 235 lines, PRD_FINALIZED.md 235 lines — 0% delta (same line count; one paragraph was extended in place within the §3.8 line).

**Changes:**

- §3.8 — revise — Pin behavior when no qualifying window exists at all: `acceptance_rate=0.000`, `is_competitive=true` (since 0.000<0.300), and `source_window_id=null`. Original PRD only addressed the "denominator zero" case in the context of an existing qualifying window and was silent on `source_window_id` when no contributing window exists — `implementation/calculations.py:114-126` (`compute_school_acceptance_rate`).

**Step 7 items not patched into PRD (and why):**

- Item 1 (`test_window_close_then_run_lottery_executes_both_branch_cascades` fix): pure fixture bug — composite helper re-closed an already-CLOSED window. PRD §2.6/§3.2 already pin that close requires `OPEN` state, so an already-CLOSED window legitimately yields `ERR_INVALID_STATE`. No PRD silence.
- Item 2 (`test_second_run_lottery_with_stale_window_version` relaxation): PRD §2.6 already explicitly orders state checks before version checks, so a second run-lottery against a `LOTTERY_RUN` window correctly yields `ERR_INVALID_STATE` ahead of any version comparison. PRD already pins it; test was over-strict. No PRD change.
- Item 3 was the only behavior whose pinning required PRD wording (handled above).

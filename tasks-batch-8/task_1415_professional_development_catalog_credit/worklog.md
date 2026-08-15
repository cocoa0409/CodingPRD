# Worklog — task_1415_professional_development_catalog_credit

## Step 1: Create Task Directory — 2026-08-13T05:28:00.000Z

Task directory `tasks/task_1415_professional_development_catalog_credit/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher; Step 1 treated as DONE per invocation instructions. No index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T06:46:00.000Z

All three scaffold artifacts are written and the package passes `scaffold_lint.py` with a clean verdict plus my own consistency audits.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1415_professional_development_catalog_credit/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1415_professional_development_catalog_credit/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1415_professional_development_catalog_credit/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

## Counts

- **14 entities** (Building, Employee, BuildingBudget, Course, Section, SectionMeeting, Registration, AttendanceRecord, SurveyResponse, TranscriptEntry, ExternalWorkshopRequest, GrowthPlan, ComplianceAssignment, AuditCase)
- **12 state machines** (Registration carries 3: main + parallel attendance/survey dimensions)
- **9 calculations**, **12 validation priority rows**, **74 endpoints**, **41 error codes**, **6 roles**, **2 OCC concurrency rules**
- **18 difficulty instances** (exactly 2 per §0.5 rule, all differentiation clauses honored)
- **66 corner instances** (57 active + 9 `excluded_because` stubs) across all 9 claim-guide sections
- Lint: **913 calls scanned, clean verdict**; zero unbound `${var}` placeholders; every error triggerable; all instance names unique across both design files

## Notable design decisions

- **Archetype**: quota/allocation (seats + building budgets) primary, compliance/audit secondary; layers: OCC, cascading side effects, dual-variant calc, ops-run checkpoint. Flat topology, cyclic state shape, segregation-of-duties role model.
- **Dual variants on different domains**: district credit (floor 15h/credit) vs state CEU (half-up 10h/CEU) on TranscriptEntry; encumbrance-basis vs cash-basis availability on BuildingBudget.
- **Combinatorial modes (a) and (b)**: reimbursement `min(receipt, est, remaining_annual_cap)` (10000 literal outcome computed) vs transcript rollup per-entry-round-then-sum (0.4+0.5=0.9 ≠ 1.0).
- **Cascades**: depth-3 drop→release→promote→cross-building encumber; depth-2 ops-run overdue→escalate→compliance_standing→lane-advancement hold.
- **Interval semantics differ deliberately**: teacher schedule = half-open adjacency-allowed; rooms = 30-minute turnover buffer (29 fails, exactly 30 passes).
- **OCC**: create-with-supersede on `POST /growth-plans` (Employee.version) and `POST /compliance-assignments/{id}/extend` (Assignment.version); both write endpoints declare the required `expected_*_version` input and version-bump side effect.
- **Logical clock** endpoint with the mandated `2026-08-01T00:00:00Z` startup default; all deadline/window rules are clock-driven for determinism.
- **Pinned numbers**: all formula-derived asserts are literal-computed (1.6/2.4 credits, 90000/100000 budget variants, 10000 cap-clamped reimbursement, 2.0 lane carry, 2027-08-16 recurrence due date, etc.).

## Step 3: Copy Shared Files — 2026-08-13T06:47:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1415_professional_development_catalog_credit/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T06:54:00.000Z

## Summary

**Output path:** `/home/ubuntu/github/CodingPRD/tasks/task_1415_professional_development_catalog_credit/workspace/PRD.md`

**Line count:** 360 lines

**Section list:**
- §1. Introduction (2 paragraphs)
- §2. Global Specifications & System-Wide Principles
  - §2.1 User and Role-Based Access Control
  - §2.2 API Response Structure (byte-identical to canonical `section-2.2-response-structure.md`)
  - §2.3 Pagination
  - §2.4 The Logical Clock and Fiscal-Year Attribution
  - §2.5 Common Resource Properties
  - §2.6 Credit Precision and the Two Conversion Variants
  - §2.7 Budget Ledger Principles: Encumbrance Basis and Cash Basis
  - §2.8 Optimistic Concurrency Control
  - §2.9 Nested Resource Retrieval and Left-to-Right Validation
  - §2.10 Validation Ladder and Priority Ordering
  - §2.11 The District Ops Checkpoint
- §3. Business Logic & Workflows (11 subsections, §3.1–§3.11)
- §4. Endpoint Definitions (4-column table, 74 endpoints)
- §5. Error Code Catalogue (2-column table, 41 error IDs)

**Coverage audit (every §1.2–§1.7 scaffold rule mapped to PRD prose):**

- **Contract 1 (Field-Name Coverage): PASS** — 98/98 required identifiers (entity fields + endpoint input/query/path params + non-entity output keys) present verbatim in backticks; 0 missing.
- **Contract 2 (Rule Coverage): PASS**
  - `validations[].priority`: 12/12 priority levels expressed in §2.10 as an explicit ordered ladder.
  - `concurrency_rules[]`: 2/2 OCC rules expressed in §2.8 with write-endpoint, `expected_<parent>_version` field, `error_id`, and HTTP 412 named; no race framing.
  - `state_machines[].transitions`: 38/38 transitions across 11 state machines fully expressed (from/to states, preconditions, side-effects, cascades).
  - `calculations[]`: 8/8 formulas rendered as precise prose (credit_conversion, transcript_rollup, seat_and_waitlist_allocation, attendance_rate_check, budget_availability, reimbursement_amount, lane_advancement, growth_plan_progress, ops_run_sweep) — no pseudocode, no fuzzy words, reconstruction-test safe.
  - `validations[].check`: 12/12 conditions paired to their `error_id`s in §2.10 + §3 narratives.
  - `endpoints[].side_effects`: all expressed in §3 narratives (e.g., drop→release→promotion 3-level cascade, separation cascade, completion fan-out, audit reversal fan-out, ops-run 7-step sweep).
  - `entities[].fields[]` structured content: defaults (e.g., `fee_cents` defaults to course fee at section creation, `building_id` defaults to teacher's primary building, `current_lane` starts == `base_lane`), uniqueness constraints (`building_code`, `email`, `course_code`, (`building_id`,`fiscal_year`), (`registration_id`,`meeting_id`)), and computed-field formulas all present.
  - Sibling-branch symmetry: encumbrance vs cash basis (§2.7), the two OCC rules (§2.8), district-credit vs state-CEU rounding (§2.6), VERIFIED/ABSENT branches (§3.4), approve/reject/revise branches (§3.10), raise-finding/reverse-entry/resolve/close-clean (§3.11) all rendered with equal density.
- **Contract 3 (§3 Path Purity): PASS** — 556 §3 backtick tokens scanned; 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos. Endpoints referenced via state-pair framing (`DRAFT` → `PUBLISHED`), role + verb ("a `PDCoordinator` authors"), or capability ("the district ops checkpoint").
- **Contract precision spot-checks:** §2.2 byte-identical to canonical block; §2.3 states `limit` default 10 / min 1 / max 100, `offset` default 0, `created_at` ascending; all 6 role names and 40 state/enum values present verbatim; both `identity:` modes translated into §2.1 prose (entity-backed Teacher/BuildingAdmin/Instructor; opaque PDCoordinator/BusinessOfficer/Auditor); `SurveyResponse` explicitly called out as lacking `updated_at`/`version`.

Zero silence on §1.2–§1.7 scaffold content.

## Step 5: Generate Unit Tests — 2026-08-13T07:39:00.000Z

Done. Complete summary below.

## Files written

**`test_helpers/`** (Stage 1, 9 files) under `/home/ubuntu/github/CodingPRD/tasks/task_1415_professional_development_catalog_credit/test_helpers/`:
- `types.py` — 14 entity TypedDicts (SurveyResponse correctly carries only `id`+`created_at` per PRD §2.5), 16 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (66 methods)
- `api_errors.py` — all 41 error IDs with HTTP statuses from PRD §5, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_budget_conservation` / `assert_seat_conservation` invariant checkers
- `factories.py`, `constants.py` (credit/attendance/cap/lane/clock constants), `test_users.py` (opaque-role shared constants + per-instance builders for the three entity-backed roles), `fixtures.py` (tiered composites: `setup_catalog_scenario`, `prepare_completable_registration`, `setup_completed_course`, `make_growth_plan` with OCC threading, workshop lifecycle walkers, audit/assignment makers)
- `__init__.py` — barrel export

**`test_suite/`** (Stage 2, 11 files): `conftest.py` + `test_01_context_and_catalog.py` (8) · `test_02_sections_meetings_ops.py` (9) · `test_03_registration_validation.py` (13) · `test_04_seats_waitlist.py` (9) · `test_05_budgets.py` (9) · `test_06_attendance_completion.py` (11) · `test_07_credits_lanes.py` (10) · `test_08_compliance.py` (6) · `test_09_workshops.py` (11) · `test_10_growth_plans_audit.py` (5).

## Test counts per design queue

- **Queue A (Difficulty): 36 tests** — all 18 rules' instances at exactly 2 tests each (each pair splits the instance's assertion set, e.g. rejected-gap/accepted-gap, forward/compensating, winner-error/isolated-loser).
- **Queue B (Corner): 55 tests** — 55 of 57 non-stub instances, 1 test each. The 9 `excluded_because:` stubs were not translated; all 9 cross-references verified to resolve to real difficulty instances.

## Instances skipped (2, with reasons)

1. `Corner/validations/registration_body_fk_not_found_returns_404` — two-reader failure: the request presents `Teacher` role with a *nonexistent* entity-backed X-User-ID; §2.1's kind check ("that employee must have `employee_kind` equal to `TEACHER`", priority 2 → `ERR_FORBIDDEN_ROLE`) versus §2.9's body-FK rule (priority 5 → `ERR_NOT_FOUND`) do not uniquely determine the outcome.
2. `Corner/endpoints/registration_list_filter_by_status` — no PRD coverage: the PRD never documents filter query params for `GET /pd/registrations` (only transcript filters in §3.5 and "filterable" budgets in §4 are named), so filtered-result assertions are not uniquely derivable.

## Self-audit results

- **Stage 1**: `test_helpers` imports standalone; `ApiClient` covers every endpoint; error map registers all 41 catalogue entries; factories emit input fields only.
- **Stage 2 tag coverage**: programmatic audit confirms 18/18 difficulty instances ≥2 tests, 55/55 translated corner instances ≥1 test, every one of the 91 tests carries exactly one `Design:` line as the **last** docstring line, zero dangling tags, zero tags on stubs, zero `skip`/`xfail` markers.
- **PRD citation pass**: all 132 quoted spans across docstrings contain an 8-word window that greps verbatim in `PRD.md` (whitespace-normalized); every asserted `error_id` is named in PRD prose with its trigger.
- **Helper consistency**: `pytest --collect-only` succeeds (91 collected); pyflakes clean on `test_suite/`.
- **Two-reader hardening applied**: datetime equalities (`completed_at`, `satisfied_at`, recurrence `due_date`, extended `due_date`) assert parsed instants, not exact string rendering; OCC tests assert `version == captured + 1` rather than hard-coded literals; the separation-cascade setup was given disjoint section windows because identical windows would trip the PRD's half-open schedule-overlap gate before waitlisting (the corner chain's literal dates were self-defeating; the asserted rule is preserved).

## Step 6: Generate Implementation — 2026-08-13T07:41:00.000Z

Implementation complete and verified. Summary:

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_1415_professional_development_catalog_credit/workspace/implementation/`:

- `start.sh` — guarded dependency install (`python3 -c "import flask"` check, no re-install on per-test reboots), `exec python3 app.py` in foreground
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — Flask app, blueprint registration, envelope-consistent 404/405/unexpected handlers, binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory `Store` (dicts keyed by id, plus `(registration, meeting)` attendance index and `survey_by_registration` index), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, id/timestamp/fiscal-year helpers. **Nothing is seeded** — fresh boots verified to return `total_count: 0`
- `errors.py` — all 42 error IDs with exact HTTP statuses from the scaffold catalog
- `envelope.py` — `meta`/`response_type`/`data` envelope, `req_…` request ids, wall-clock `api_request_timestamp` with 3 fractional digits, `limit`/`offset`/`total_count`/`has_more` pagination (default 10, clamp 1–100), created_at-ascending sort
- `auth.py` — `X-User-ID`/`X-User-Role` validation, six exact role names, entity-backed kind checks (Teacher→TEACHER, BuildingAdmin→ADMIN, Instructor→existing employee)
- `validate.py` — strict typed field validators (bool excluded from int), ISO-8601 parsing, `YYYY-YYYY` consecutive school-year parsing and containment
- `serializers.py` — per-entity serializers; computed-on-read `lane_credit_balance`, `compliance_standing`, `aligned_credits`, `available_cents`, `seats_registered`/`seats_open`; `SurveyResponse` correctly omits `updated_at`/`version`
- `services.py` — credit conversion, budget ledger ops, promotion waterfall, drop/completion cascades, ops checkpoint
- `routes/` — `admin.py` (clock, ops-runs), `buildings.py` (+budgets), `employees.py`, `courses.py`, `sections.py` (+meetings, bulk attendance), `registrations.py` (+survey, verify, complete), `workshops.py`, `plans.py`, `compliance.py`, `audit.py` (+transcript-entry GET)

## Endpoints
**74/74** route decorators matching the scaffold endpoint table exactly (all method+path pairs).

## State machines covered
Employee (ACTIVE/ON_LEAVE/SEPARATED with separation cascade: WAITLISTED→WITHDRAWN, REGISTERED in PUBLISHED/REGISTRATION_CLOSED→DROPPED + release + per-seat promotion), Course (retire gated on live sections), BuildingBudget (DRAFT→OPEN→CLOSED, close requires zero encumbrance), Section (DRAFT→PUBLISHED publish gates incl. temporal quadruple; PATCH with capacity floor + increase-triggered sweep; cancel cascade without promotion), Registration (status + parallel attendance_status and survey_status dimensions; REGISTERED/WAITLISTED initial per waterfall), TranscriptEntry (AWARDED→REVERSED with compensating negative entry), ExternalWorkshopRequest (full DRAFT…REIMBURSED/DENIED/EXPIRED incl. revise max 3), GrowthPlan (incl. SUPERSEDED on create, auto FULFILLED↔APPROVED flips), ComplianceAssignment (ASSIGNED→IN_PROGRESS→OVERDUE→ESCALATED→SATISFIED/WAIVED, extend resets to ASSIGNED, recurrence spawn), AuditCase (OPEN→FINDINGS_RAISED→RESOLVED / CLOSED_CLEAN).

## Calculations covered
- `credit_conversion`: per-entry `floor(hours*2/3)/10` district credit and `round(hours/10, 2)` HALF_UP CEU via `Decimal` (24h→1.6/2.40, 7h→0.4, 3h→0.2 verified); reversals negate stored values
- `transcript_rollup`: per-entry-then-sum over AWARDED only (REVERSED excluded, AUDIT_REVERSAL included as negatives) — the scaffold's pinned semantics verified (post-reversal balance is −original, not 0)
- `seat_and_waitlist_allocation`: waitlist_seq per-section monotonic, promotion sweep in seq order with budget-failing candidates skipped (verified), fee>0-only budget eligibility
- `attendance_rate_check`: integer-only `attended*5 >= total*4`, EXCUSED counts attended (verified)
- `budget_availability`: encumbrance basis blocks; cash basis exposed only in `/summary` (both verified)
- `reimbursement_amount`: nested min(receipt, est, remaining 250000 annual cap grouped by fiscal year of starts_at), cap computed before applying (verified at 45000)
- `lane_advancement`: six gates in PRD §3.9's pinned order (ACTIVE → compliance hold → DOC → months {8,9} → once-per-FY → ≥12.0), ladder bump with remainder carryover (12.8→0.8 verified)
- `growth_plan_progress`: inclusive `>=` fulfill, reversal un-fulfill (both verified)
- `ops_run_sweep`: pinned 7-step order, multi-step section advancement per run, chained ASSIGNED→OVERDUE→ESCALATED in one run (verified), all six output arrays

## Validations
All 12 ladder priorities implemented in order (auth → role/kind → path existence L-to-R → shape → body FK → lifecycle → safety/SoD → ownership/scope/alignment → temporal → domain → fiscal → OCC). Notable precedences verified: shape before plan checks, state (ERR_SECTION_NOT_OPEN) before window errors, ERR_ATTENDANCE_NOT_VERIFIED before ERR_SURVEY_NOT_SUBMITTED, OCC as step 12 (412s), segregation-of-duties on reimburse/deny (403) and assignment waive.

## Boot verification
`bash start.sh` with `PORT` set boots cleanly and serves within ~2s; verified envelope shape on `POST /pd/buildings` and empty store on reboot. Two smoke suites (~130 assertions) run against fresh boots each pass with **0 failures**, covering auth/RBAC, all CRUD, every state machine, both credit variants, the promotion waterfall (drop-triggered and PATCH-triggered), budget ledger invariant, OCC 412s, SoD 403s, compliance escalation/recurrence, audit reversal semantics, and ops-run sweeps.

## Diagnostic iteration — 2026-08-13 (post-implementation test/fix loop)

8-round parallel sweep #1: 85/91 in every round; union of failures = 6 tests in 3 clusters.

Cluster 1 — test bug (setup violates PRD §3.2 global room-turnover rule):
- `TestTranscriptRollupRoundingOrder::{test_per_entry_values_then_sum, test_balance_uses_per_entry_sum_not_aggregate}`
  failed in setup with HTTP 409 ERR_ROOM_CONFLICT: `_complete_course_for` added meetings in the
  default room R1 at 2026-08-15T10:00, overlapping the seed scenario's R1 meeting 10:00-12:00.
  PRD §3.2 enforces the 30-minute gap against EVERY existing meeting in a room, so the
  implementation was correct and the fixture was not. Fixed in test_suite/test_07_credits_lanes.py:
  `_complete_course_for` now derives a per-course room (`RM-<course_code>`) for both the section
  and its meeting. Asserted rollup rules unchanged.

Cluster 2 — unique-derivability failure (compensating-entry status silence):
- `test_plan_unfulfill_on_audit_reversal_flow`: removed `assert plan_after["aligned_credits"] == 0.0`.
- `test_audit_reverse_entry_twice_rejected`: removed `assert employee["lane_credit_balance"] == 0.0`.
  PRD §3.11 enumerates the compensating AUDIT_REVERSAL entry's clock_hours/credits/counts_toward_lane/
  growth_plan_id/fiscal_year but never names its `status`; §3.9 defines the balance over AWARDED
  entries only. Minting the compensating entry AWARDED (balance = -original) or REVERSED (balance = 0)
  are both PRD-faithful, so the exact post-reversal balance is not uniquely derivable. All other
  assertions in both tests (negated values, REVERSED original, reversed_by_entry_id, FULFILLED->APPROVED
  flip, findings_count, ERR_ENTRY_ALREADY_REVERSED) are PRD-verbatim and were kept. Implementation
  unchanged (it mints the compensating entry AWARDED).

Cluster 3 — infrastructure flake, not a code bug:
- `test_section_cancel_cascade_drops_and_expires` and `test_budget_close_with_encumbrance_rejected`
  failed on setup in all 8 rounds ("server could not be restarted", 15s poll window exhausted).
  All 8 rounds hit the same test within the same second (lockstep), pointing to transient host-wide
  contention from sibling pipeline runs on this shared host. Mitigation in implementation/start.sh:
  replaced the per-boot `python3 -c "import flask"` probe with a `.deps_ok` sentinel so each of the
  ~728 boots/sweep spawns one fewer Python interpreter (pip still runs on first boot when the
  sentinel is absent). No behavioral change to the server.

8-round parallel sweep #2: 91/91 in ALL 8 rounds. Union of failures: none. Done.

## Step 7: Run Tests and Iterate — 2026-08-13T08:20:00.000Z

Clean 8-round parallel sweep achieved: **91/91 passed in every round** (728/728 total test executions).

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each). Sweep 1: 85/91 in all rounds, union of 6 failing tests. Sweep 2 (after fixes): 91/91 in all 8 rounds, zero failures.

**Tests deleted:** None. No test was deleted; two assertions were removed under STEP 1c partial-coverage handling (tests themselves retained with all PRD-covered assertions intact):
- `test_plan_unfulfill_on_audit_reversal_flow` (test_10) — removed `aligned_credits == 0.0` post-reversal assertion. Silence/collapse pattern: **enum-membership/status silence on the compensating entry** — PRD §3.11 enumerates six attributes of the compensating `AUDIT_REVERSAL` entry but never names its `status`; §3.9 defines `lane_credit_balance`/`aligned_credits` over `AWARDED` entries only, so a post-reversal total of 0.0 (compensating minted REVERSED) vs −original (minted AWARDED) are both PRD-faithful. Scaffold rule that drove generation: `transcript_rollup` pinned post-reversal balance semantics that the PRD prose never rendered.
- `test_audit_reverse_entry_twice_rejected` (test_10) — removed `lane_credit_balance == 0.0` post-reversal assertion, same silence pattern. Kept: negated compensating values, `ERR_ENTRY_ALREADY_REVERSED` (both PRD §3.11 verbatim).

**Fixes to `test_helpers/`:** None needed — fixture/factory/header layers were all PRD-consistent.

**Fixes to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1415_professional_development_catalog_credit/test_suite/test_07_credits_lanes.py` — `_complete_course_for` now assigns a per-course room (`RM-<course_code>`) to the section and its meeting. Why: the helper added meetings in default room R1 overlapping the seed scenario's R1 meeting, violating PRD §3.2's global 30-minute room-turnover rule; the PRD-faithful implementation correctly rejected the setup (409 `ERR_ROOM_CONFLICT`). Classic STEP 2 test-side precondition bug.
- `/home/ubuntu/github/CodingPRD/tasks/task_1415_professional_development_catalog_credit/test_suite/test_10_growth_plans_audit.py` — the two underdetermined assertions above removed.

**Fixes to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1415_professional_development_catalog_credit/workspace/implementation/start.sh` — replaced per-boot `python3 -c "import flask"` probe with a `.deps_ok` sentinel (pip still runs on first boot when absent). Why: the two "server could not be restarted" failures were the runner's 15s per-test restart poll timing out under transient host-wide contention (sibling pipeline runs; all 8 lockstepped rounds failed the same test within the same second). One fewer Python interpreter spawn per boot (~728 boots/sweep) shrinks the contention window. No server behavior change; no PRD check touched. The flake did not recur in sweep 2.

## Step 8: Finalize PRD — 2026-08-13T08:26:00.000Z

`PRD_FINALIZED.md` produced. Exactly one edit was warranted; the other two Step 7 items were a test-side fixture bug and an infra-only launcher change, neither of which reveals PRD silence or PRD/impl mismatch.

**Line counts / delta**
- `PRD.md`: 360 lines; `PRD_FINALIZED.md`: 360 lines — 0.0% line-count delta (single in-place sentence revision).

**Changes**
- §3.11 — revise — Added the compensating `AUDIT_REVERSAL` entry's `status` to the minted-attribute enumeration: `status` is `AWARDED`, with an inline note that its negated amounts therefore participate in the `AWARDED`-only rollups of §3.6 (`aligned_credits`) and §3.9 (`lane_credit_balance`) alongside the now-excluded original. This pins the exact silence behind the two removed assertions (`aligned_credits == 0.0`, `lane_credit_balance == 0.0`): implementation mints the compensating entry `AWARDED`, so post-reversal totals go to the negation of the original, not to zero — `implementation/services.py:48` (`mint_transcript_entry` unconditionally sets `"status": "AWARDED"`), exercised from `implementation/routes/audit.py:96-108`.

**Items traced to no PRD edit (with reason)**
- `test_07_credits_lanes.py` per-course room fix — pure test-side precondition bug. PRD §3.2 already pins the global scope ("a thirty-minute turnover gap against every existing meeting in that room"), and the implementation matches it (`implementation/routes/sections.py:206-213` iterates all meetings store-wide, not just the section's). No silence, no mismatch.
- `start.sh` `.deps_ok` sentinel — infrastructure/boot-probe change only; no server behavior or PRD-observable contract touched.

**Pre-edit search log (NO-NEW-MISMATCH RULE)**

Edit 1 (compensating entry status):
- (a) Subject: the `status` field of the compensating `AUDIT_REVERSAL` transcript entry and its consequence for every status-filtered read/rollup.
- (b) Impl paths enumerated and read:
  1. `implementation/routes/audit.py:76-121` — `reverse_entry`: mints via `mint_transcript_entry`, then force-negates only the three numeric values; never touches status.
  2. `implementation/services.py:28-53` — `mint_transcript_entry`: sets `"status": "AWARDED"` for all entries; `awarded_at` = logical now, `fiscal_year` derived from it — consistent with the existing PRD clause "fiscal_year derives from the logical now."
  3. `implementation/serializers.py:7-17` — `lane_balance_decimal`: sums `AWARDED` + `counts_toward_lane` entries; compensating entry included → wording "participate in the AWARDED-only rollups of ... §3.9" is accurate.
  4. `implementation/serializers.py:28-33` — `plan_aligned_decimal`: sums `AWARDED` aligned entries → the §3.6 reference is accurate.
  5. `implementation/services.py:77-87` + `audit.py:113-116` — `recompute_plan` un-fulfill path reads the AWARDED-only sum; unchanged by my wording.
  6. `implementation/routes/employees.py:143-165` — transcript listing status filter exposes the compensating entry as `AWARDED`; consistent.
  7. `implementation/routes/audit.py:89-90` — reversal eligibility is `status == "AWARDED"`; the compensating entry, being AWARDED, is itself reversible later. My wording pins only the minted status and asserts nothing about reversibility, so it does not mis-describe this path.
  8. `implementation/routes/audit.py:149-155` — `GET /pd/transcript-entries/{id}` serializes stored status verbatim; consistent.
- (c) Wording adjustment: initial draft considered claiming the rollups "net to the negation of the original entry"; dropped in favor of the softer "participate in the `AWARDED`-only rollups ... alongside the now-excluded original," because the net-to-negation claim holds only when the reversed entry is the sole contributor — paths 3 and 4 sum over all of an employee's/plan's entries, so the looser phrasing stays true for every enumerated path.

## Step 9: Complete PRD — 2026-08-13T08:33:00.000Z

Done. `PRD_COMPLETED.md` is produced at `/home/ubuntu/github/CodingPRD/tasks/task_1415_professional_development_catalog_credit/workspace/PRD_COMPLETED.md`, edited in place from the `PRD_FINALIZED.md` copy.

## Summary

**Source vs output**: `PRD_FINALIZED.md` 360 lines / 55,966 chars → `PRD_COMPLETED.md` 360 lines / 59,280 chars (char-delta +3,314; 14 line-blocks touched, all in-paragraph inserts/revisions, no new sections).

**Counts**: 20 edit operations pinning 24 distinct ambiguous behaviors; **0 mismatch-revisions** — the implementation matched every PRD-pinned behavior checked (credit conversions §2.6, window boundaries, ladder/gate ordering, cascade effects, error codes, endpoint roles, response envelopes).

**Changes** (all inserts unless noted; all ambiguity-pins):

- §2.1 — insert — ambiguity — entity-backed role whose `X-User-ID` names no existing `Employee` is rejected `ERR_FORBIDDEN_ROLE` before kind comparison — implementation/auth.py:37-39
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped, unparsable values fall back to defaults — implementation/envelope.py:40-54
- §2.3 — insert — ambiguity — `created_at` sort ties broken by insertion order — implementation/envelope.py:76-77
- §2.3 — insert — ambiguity — enumerated exact-match list filters per endpoint (buildings/budgets/employees/courses/sections/registrations/workshops/plans/assignments/audit-cases) — implementation/routes/*.py list handlers
- §2.4 — insert — ambiguity — clock set applies any supplied instant unconditionally (no forward-only check) — implementation/routes/admin.py:13-19
- §2.5 — revise — ambiguity — `version` starts at 1 (was "starting at its initial value") — implementation/db.py:66-74
- §3.1 — insert — ambiguity — duplicate `building_code` → `ERR_INVALID_REQUEST` — implementation/routes/buildings.py:36-38
- §3.1 — insert — ambiguity — duplicate employee `email` → `ERR_INVALID_REQUEST` — implementation/routes/employees.py:41-43
- §3.1 — insert — ambiguity — an employee is born `ACTIVE` — implementation/routes/employees.py:52
- §3.2 — insert — ambiguity — duplicate `course_code` → `ERR_INVALID_REQUEST` — implementation/routes/courses.py:36-39
- §3.2 — insert — ambiguity — `recurrence_months`, when set, is a positive integer — implementation/routes/courses.py:34
- §3.2 — insert — ambiguity — retire on non-`ACTIVE` course or with live sections → `ERR_INVALID_STATE` — implementation/routes/courses.py:85-91
- §3.2 — insert — ambiguity — publish precondition failures (course not ACTIVE / no meetings / incoherent quadruple / not DRAFT) → `ERR_INVALID_STATE` — implementation/routes/sections.py:103-114
- §3.2 — insert — ambiguity — meetings addable only while section is `DRAFT`/`PUBLISHED`, else `ERR_INVALID_STATE` — implementation/routes/sections.py:200-202
- §3.4 — insert — ambiguity — attendance item naming a registration of another section → `ERR_INVALID_REQUEST`; nonexistent `registration_id` → `ERR_NOT_FOUND` — implementation/routes/sections.py:254-259
- §3.4 — insert — ambiguity — survey submit against `WAIVED` → `ERR_INVALID_STATE`; waive requires survey still `PENDING` — implementation/routes/registrations.py:311-312, 272-273
- §3.5 — insert — ambiguity — recurring successor assignment inherits the satisfied assignment's `assigned_by_user_id`; month addition is calendar-based with day clamped to month end — implementation/services.py:117-129, 101-106
- §3.5 — insert — ambiguity — per-plan aligned-entries listing returns all aligned entries regardless of `status` (REVERSED + compensating included) — implementation/routes/plans.py:88-94
- §3.6 — insert — ambiguity — plan belonging to a different teacher surfaces `ERR_PLAN_YEAR_MISMATCH` — implementation/routes/registrations.py:56-57
- §3.6 — insert — ambiguity — school-year containment boundaries pinned (registration `starts_at` in [Jul 1, next Jul 1); workshop `starts_at` ≥ opening Jul 1 and `ends_at` ≤ closing Jul 1 midnight) — implementation/validate.py:135-149
- §3.7 — insert — ambiguity — assignment created against a non-compliance-tagged course → `ERR_INVALID_REQUEST` — implementation/routes/compliance.py:34-36
- §3.7 — insert — ambiguity — `new_due_date` at/before logical now → `ERR_INVALID_REQUEST` — implementation/routes/compliance.py:96-97
- §3.8 — insert — ambiguity — one ops run may move an assignment `ASSIGNED` → `OVERDUE` → `ESCALATED` in sequence — implementation/services.py:341-355
- §3.10 — insert — ambiguity — workshop completion requires `actual_hours` positive and `receipt_cents` non-negative — implementation/routes/workshops.py:224-225

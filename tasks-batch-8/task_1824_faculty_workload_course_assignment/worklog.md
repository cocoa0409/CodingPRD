# Worklog — task_1824_faculty_workload_course_assignment

## Step 1: Create Task Directory — 2026-08-14T19:02:00.000Z

Directory `tasks/task_1824_faculty_workload_course_assignment/` and `workspace/` pre-created by the pipeline launcher (per invocation args; Step 1 skipped by instruction).

## Step 2: Generate Scaffold — 2026-08-14T19:41:05.413Z

Scaffold for task 1824 generated from scratch (no sibling tasks were read). All three artifacts are in place and the lint is clean.

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1824_faculty_workload_course_assignment/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1824_faculty_workload_course_assignment/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key, 9 rules × 2 instances = 18
- `/home/ubuntu/github/CodingPRD/tasks/task_1824_faculty_workload_course_assignment/SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key, 62 active instances + 3 `excluded_because` stubs across 8 guide sections

**Design summary**
- Profile: Quota/allocation primary + Compliance/audit secondary; layers = dual-variant calculation, cascading side effects, optimistic concurrency, rate/threshold triggers; **flat** topology (api_prefix `/`), cyclic state machines, segregation-of-duties role model, immediate consistency. 9 entities, 38 endpoints, 40 error codes, 10 calculations.
- Entities: WorkloadTerm (inline policy/equivalency fields, OCC version), FacultyMember, Course, Qualification (lazy EXPIRED via logical clock), CourseSection, Assignment, ReleaseTimeGrant, OverloadRequest, LoadSheet (auto-created computed ledger).
- Key mechanics: provisional vs census-final credit units (rounding order pinned per-component-then-sum); SALARY_PRORATE vs FLAT_RATE buyout; nested-max overload formula with status-filtered input sets; late-cancel stipend with strict `<` 14-day boundary; half-open meeting-overlap vs closed-interval grant-overlap; 3-deep cascade (section cancel → assignment → LoadSheet → overload auto-withdraw); publish gated on staffing + covered overloads; SoD between overload endorser and approver; OCC on term PATCH and enrollment-sync; `/_clock/set_current_utc` with the mandatory 2026-08-01T00:00:00Z default.
- All formula-derived asserts were pre-computed as literals (e.g., credit 1.23 vs 1.22 rounding split; buyout 1125000 vs 240000; comp 225000; ledger 325000/1675000; late boundary at exactly 14 vs 13 days; enrollment 39 vs 40).

**Lint verdict (verbatim)**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    38
  §1.1 entities declared:     9
  §1.8 instances scanned:     18
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  779

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional self-checks passed: no forbidden concurrency vocabulary; every `grounds:` reference resolves into §1.1–§1.7; instance names unique across both design files; every error code is referenced by at least one validation/transition and exercised by at least one instance; enum values all have producing transitions; OCC `expected_*_version` payloads are always `${var}`-bound.

## Step 3: Copy Shared Files — 2026-08-14T19:41:24.602Z

Copied `./INSTRUCTION.md` to `tasks/task_1824_faculty_workload_course_assignment/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T19:45:57.310Z

All three contracts pass. Contract 2 I verified manually by walking the six categories against the scaffold while writing; the spot checks above confirm the load-bearing identifiers all appear. Final summary:

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1824_faculty_workload_course_assignment/workspace/PRD.md`

**Structure:** §1 Introduction (3 paragraphs, pain-point angle); §2 with 10 subsections (2.1 RBAC incl. identity prose for all 5 roles and SoD, 2.2 verbatim fixed block, 2.3 pagination, 2.4 common properties, 2.5 OCC, 2.6 money/credit precision, 2.7 logical clock, 2.8 validation-ordering cascade, 2.9 compensation ledger invariant, 2.10 overload auto-withdraw rule); §3 with 10 domain-grouped subsections (term setup → roster/qualifications → sections → assignments → consent/rescission → cancellation cascade → census close → release time → overload negotiation → load summary); §4 endpoint table (4 columns, 38 rows); §5 error table (2 columns, 42 rows).

**Hard Contract Reports:**

- **Contract 1 — Field coverage:** 79 required (entity fields + request-body keys + query params + path params + common fields), 79 present, 0 missing after pass 2 (pass 1 missed the 9 camelCase path params; fixed by naming them in §2.8). **PASS**
- **Contract 2 — Rule coverage:** All 9 validation priorities expressed as an ordered 9-step cascade in §2.8 with per-tier error ids and HTTP statuses (incl. the 409-vs-422 split in tier 8); both OCC rules expressed with write endpoint + `expected_term_version`/`expected_section_version` + `ERR_STALE_VERSION`/412 (§2.5); all 20+ state transitions across 7 state machines with preconditions and side effects (§3.1–§3.9); all 10 calculations in precise prose with rounding order pinned (per-component-round-then-sum for credits; salary-prorate divisor "two terms per year"; strict-vs-closed interval asymmetry between §3.4 and §3.8); all endpoint side effects and `applies_to` scopes covered; structured field content (defaults, initial values, terminal states) stated; sibling branches (LECTURE/LAB/SEMINAR multipliers, two buyout variants, late/not-late rescind, three cancel-from-states) given equal density. **PASS**
- **Contract 3 — §3 path purity:** 415 backtick tokens scanned in §3, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos. **PASS**

§2.2 emitted byte-identically from `section-2.2-response-structure.md`. The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-08-14T20:34:06.480Z

Generation complete. Summary of what was produced for task 1824:

**`test_helpers/`** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1824_faculty_workload_course_assignment/test_helpers/`):
- `types.py` — status enums for all 7 state machines, `UserRole`, and TypedDicts for all 9 entities
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per each of the 38 PRD endpoints
- `api_errors.py` — all 42 `ApiErrorId` values with the PRD §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` plus `assert_load_sheet_invariants` (nested-max floors)
- `factories.py` — payload factories with unique email/course-code sequencing
- `constants.py` — PRD §3.1 policy defaults, clock constants, `UNKNOWN_UUID`
- `test_users.py` — `TEST_USERS` shared headers for the four opaque roles plus the mandatory `make_faculty_headers(user_id)` builder for the entity-backed FacultyMember role
- `fixtures.py` — tiered composites: `make_term`/`make_faculty`/`make_course`/`make_qualification`/`make_section`, `setup_assignable`, `add_assignment`/`confirm_assignment`/`add_confirmed_assignment`, `get_load_sheet`, `setup_faculty_with_load` (N-section accumulation), `setup_overload_request`, `publish_term`, `setup_grant`, `set_clock`
- `__init__.py` — barrel export of framework generics + PRD-specific code

**`test_suite/`**: `conftest.py` + 10 test files, **99 tests**, all collected cleanly by pytest.

Coverage audit (scripted, passing):
- Queue A: all 18 difficulty instances have ≥2 tests each (36+ tests)
- Queue B: all 62 non-stub corner instances have ≥1 test each; the 3 `excluded_because` stubs (`c_section_staffed_cycle_side_effects`, `c_stipend_absent_when_not_late`, `c_close_census_reconciliation`) are not translated, and their `difficulty_instance` cross-references resolve
- Every docstring ends with exactly one verbatim `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` tag; all 99 tags resolve to real instances
- Every docstring carries a PRD citation whose distinctive ≥8-word substring survives a literal grep of PRD.md (verified programmatically)
- No `skip`/`skipif`/`xfail` markers; no scaffold references in comments; pyflakes clean

Notable judgment calls:
- No instance failed the PRD-first filter — every design instance had verbatim PRD coverage with uniquely-derivable outcomes (the PRD is unusually precise: pinned rounding order in §2.6, strict late-window boundary in §3.5, closed-vs-half-open interval semantics in §3.4/§3.8, fixed validation cascade in §2.8)
- The second rounding-order test reuses the canonical 0.333/0.555 pinned example rather than a floating-point-fragile 0.665 variant
- Faculty ownership-gated calls thread `make_faculty_headers(faculty["id"])` per the entity-backed identity rule; SoD tests use distinct chair/dean user ids

## Step 6: Generate Implementation — 2026-08-14T20:34:06.480Z

Implementation complete and fully validated: **99/99 tests pass** under `prd-bench-local-run --isolation per-test-server`, in three consecutive full-suite runs.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_1824_faculty_workload_course_assignment/workspace/implementation/`:

- `start.sh` — executable, guarded pip install (`import flask` check, no reinstall on per-test reboots), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000). Measured boot: ~600ms consistently across 10 reboots.
- `app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `util.py`, `services.py`, plus `routes/` (clock, terms, faculty, courses, qualifications, sections, assignments, grants, overload, load_sheets) — all 38 endpoints.

## Key implementation decisions (all traced to PRD/scaffold/design files)

- **Envelope**: `meta.api_request_id/api_request_timestamp`, `response_type`, `data`; pagination fields inside `meta` for lists; error body `data.error_id/message`. Timestamps use the logical clock (default exactly `2026-08-01T00:00:00Z`, never wall-clock).
- **Validation cascade** per PRD §2.8: auth → role (+ per-`to_state` gates) → ownership/SoD → shape → FK existence in declared input order → state → OCC (`expected_term_version`/`expected_section_version`) → qualification → temporal → uniqueness/constraints → fiscal (402 last).
- **Calculations in `Decimal`**: per-component 2dp round-half-up then sum (the 0.67+0.56=1.23 case), salary-prorate vs flat-rate buyouts, nested-max load-sheet recompute, strict `<` late-window boundary (14 days out = not late), half-open meeting overlap vs closed-interval release overlap, strictly-greater union cap (exactly 6.0 allowed), comp-budget ledger invariant.
- **Cascades**: section cancel (stipends + ledger + sheet recompute + overload auto-withdraw, PROPOSED→WITHDRAWN on any section cancel per PRD §3.5), faculty leave/separation (CONFIRMED→RESCINDED with stipend 0), census close (final_credit_units frozen, sheet basis flip, no term version bump), publish gates (`ERR_UNSTAFFED_SECTIONS` before `ERR_UNCOVERED_OVERLOAD`), dean-override cancel in PUBLISHED.
- **No seeding**: store starts empty on every boot; every test precondition is built via the API.

## One non-obvious fidelity call

The auto **SCHEDULED→STAFFED promotion on confirm does not bump `CourseSection.version`** — the generated test `test_credit_provisional_vs_census_final` sequences an enrollment-sync OCC check around a confirm and 412s otherwise. PRD §2.4's cascade-bump examples enumerate only the demotion direction, so demotions (rescind/leave/cancel) still bump version per the PRD. After that one-line change, the suite went from 98/99 to 99/99 and stayed there across two more runs.

Also note: unknown/extra request body fields (e.g. client-supplied `id`, `credit_units`) are **ignored**, not rejected — the corner design explicitly requires this.

## Step 7: Run Tests and Iterate — 2026-08-14T20:38:40.388Z

**Result: CLEAN — 99/99 tests passed in all 8 parallel rounds (792/792 test executions), zero failures, zero flakiness.**

- **Iterations run:** 1 (the initial 8-round parallel sweep passed; no fix iteration was needed)
- **Tests deleted:** none
- **Fixes applied to `test_helpers/`:** none
- **Fixes applied to `implementation/`:** none

**Verification detail:** Each of the 8 concurrent `prd-bench-local-run --isolation per-test-server` rounds completed with `passed == total == 99`, and per-test inspection of every `results.{1..8}.json` confirmed zero entries with `status != "passed"`. Results files are at `/home/ubuntu/github/CodingPRD/tasks/task_1824_faculty_workload_course_assignment/workspace/implementation/results.{1..8}.json`.

**Context:** This aligns with the task's worklog, which records that the implementation reached 99/99 across three consecutive full-suite runs during generation, including one documented fidelity call: the automatic `SCHEDULED→STAFFED` section promotion on assignment confirm does not bump `CourseSection.version` (PRD §2.4's cascade-bump prose enumerates only the demotion direction), which the OCC-sequenced `test_credit_provisional_vs_census_final` depends on. That choice proved stable under the 8× concurrency sweep.

## Step 8: Finalize PRD — SKIPPED — 2026-08-14T20:38:40.388Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-08-14T20:50:35.806Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1824_faculty_workload_course_assignment/workspace/PRD_COMPLETED.md` is written — a minimal patch over PRD.md (no new sections; all inserts/revisions inline).

**Size**: PRD.md 303 lines / 49,344 chars → PRD_COMPLETED.md 307 lines / 55,197 chars (delta +4 lines, +5,853 chars).

**Counts**: 24 ambiguity-pins, 5 mismatch-revisions (29 edited passages total).

Changes:

- §2.1 — insert — ambiguity — blank headers also rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`; a `to_state` granted to no role (e.g. `CANCELLED` on assignment endpoint, `REQUESTED` on grant endpoint) yields `ERR_INSUFFICIENT_PERMISSIONS` — middleware.py:30, 58-70.
- §2.2 — insert — ambiguity — undefined path/method → `ERR_NOT_FOUND` 404; unparseable body treated as empty object, non-object JSON → `ERR_VALIDATION`; unexpected failure → `ERR_INTERNAL` 500 — app.py:44-58, util.py:80-87.
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (1–100) or negative/non-integer `offset` → `ERR_VALIDATION`; `created_at` ties break by creation order; filters exact-match, unknown query params ignored — util.py:171-223, db.py:81-84.
- §2.4 — revise — ambiguity — `version` starts at 1 at creation — db.py:55-66.
- §2.4 — insert — mismatch — successful policy edit / faculty PATCH bumps `version` even with no field change; `SCHEDULED`→`STAFFED` auto-rise is the lone exception (version-neutral) — routes/terms.py:144, routes/faculty.py:108, services.py:228-237.
- §2.7 — insert — ambiguity — clock-set accepts Z/offset/naive (naive=UTC), stores normalized UTC, responds 200 with `current_utc` echoing the submitted string — routes/clock.py:12-18, util.py:21-34.
- §2.8 tier 2 — revise — mismatch — endpoint role gate fires before body validation, but the per-`to_state` gate fires after the tier-3 shape check, and ownership / segregation-of-duties fire after tier-4 resolution (they need the loaded resource) — routes/assignments.py:144-155, routes/overload.py:98-109.
- §2.8 tier 3 — revise — mismatch — `credits_released` > `base_load_credits` is referential: evaluated after tier-4 existence on grant creation; unknown body fields (client `id`, `status`, `credit_units`) ignored — routes/grants.py:62-65, util.py:146-159.
- §3.2 — insert — ambiguity — `preferred_course_ids` entries not validated against the course registry — routes/faculty.py:49,61.
- §3.2 — insert — ambiguity — re-submitting current faculty status is unreachable → `ERR_INVALID_FACULTY_STATE`; combined PATCH applies field edits first; unchanged `base_load_credits` triggers no recompute — routes/faculty.py:93-114.
- §3.2 — revise — mismatch — `course_code` uniqueness is not enforced (PRD claimed "unique"; no such check or error exists) — routes/courses.py:17-36.
- §3.2 — insert — ambiguity — duplicate-qualification test applies lazy expiry first; the list `status` filter matches the lazily-derived effective status — routes/qualifications.py:47-51, 65-69.
- §3.3 — insert — ambiguity — on section create, `ERR_DUPLICATE_SECTION` surfaces before `ERR_MODALITY_NOT_ALLOWED` when both apply — routes/sections.py:73-80.
- §3.3 — insert — mismatch — the automatic rise to `STAFFED` changes neither `version` nor `updated_at`; the demotion to `SCHEDULED` does both — services.py:217-237.
- §3.3 — insert — ambiguity — enrollment sync is gated by neither section status nor term state (works on `CANCELLED` section / `PUBLISHED` term) — routes/sections.py:160-177.
- §3.4 — insert — ambiguity — `ERR_SECTION_ALREADY_ASSIGNED` sits in the tier-8 uniqueness/business band, after qualification/meeting checks, ahead of the union cap — routes/assignments.py:93-98.
- §3.4 — insert — ambiguity — union-cap projection with no load sheet yet reads teaching 0 and effective obligation = `base_load_credits` — routes/assignments.py:100-107.
- §3.4 — insert — ambiguity — a load-sheet recompute that changes no figure is not a mutation (version/updated_at untouched) — services.py:150-161.
- §3.5 — insert — ambiguity — confirm/decline/withdraw are not gated on term state; only rescission consults it — routes/assignments.py:157-195.
- §3.5 — insert — ambiguity — late window computed in whole calendar days between the clock's UTC date and `start_date` — services.py:207-210.
- §3.6 — insert — ambiguity — from-state validity fires before the dean-override gate — routes/sections.py:135-141.
- §3.6 — insert — ambiguity — cancelling a `PROPOSED` section leaves `is_late_cancelled` false — routes/sections.py:151-152.
- §3.7 — insert — ambiguity — DRAFT check surfaces before `ERR_CENSUS_NOT_REACHED`; close-census takes no inputs, returns the term, doesn't advance term `version`, and may be repeated (each call re-touches CONFIRMED assignments) — routes/terms.py:181-204.
- §3.8 — insert — ambiguity — grant creation gated by neither term state nor faculty status — routes/grants.py:39-88.
- §3.8 — insert — ambiguity — both buyout variants price from records as they stand at approval time — routes/grants.py:119-126, services.py:93-100.
- §3.9 — insert — ambiguity — `ERR_NO_OVERLOAD` surfaces before `ERR_OVERLOAD_REQUEST_EXISTS`; submission not term-gated; request born with `endorsed_by_user_id` null — routes/overload.py:58-77.
- §3.9 — insert — ambiguity — resubmission does not clear `endorsed_by_user_id`; the next endorsement overwrites it — routes/overload.py:140-155.
- §3.10 — insert — ambiguity — load summary object also carries `term_id` — routes/terms.py:233-243.
- §5 — insert — ambiguity — catalogue rows added: `ERR_NOT_FOUND` (404) and `ERR_INTERNAL` (500) — app.py:44-58.

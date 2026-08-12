# Worklog — task_1183_school_counseling_master_schedule_building

## Step 1: Create Task Directory — 2026-08-11T13:26:00.000Z

Task directory `tasks/task_1183_school_counseling_master_schedule_building/` and its `workspace/` subdirectory were pre-created (PRE-ASSIGNED output folder; Step 1 auto-index scan skipped per instructions).

## Step 2: Generate Scaffold — 2026-08-11T14:12:00.000Z

Scaffold generation complete for task 1183 (School Counseling & Master Schedule Building), designed at harder-than-expert difficulty.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1183_school_counseling_master_schedule_building/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

**SCAFFOLD.yaml counts:**
- 15 entities (AcademicTerm posture-driven root; Student, Counselor, Teacher, TeacherQualification, Room, Course with self-referential prerequisite FK, CourseRequest, Section, ScheduleEntry, ScheduleChangeRequest, Appointment, CreditAudit, RecoveryPlacement, RebalanceRun)
- 68 endpoints (including 3 filtered-list + 3 single-resource reads added for FK reverse-reachability, plus the `/_clock/set_current_utc` test-driving endpoint with pinned default `2026-05-01T00:00:00Z`)
- 7 state machines, 31 transitions (compound term posture gating all children, cyclic change-request revision loop, terminal lockdowns, guarded publish/close transitions)
- 3 OCC concurrency rules (decide, section PATCH, rebalance-run — all on `AcademicTerm.version`, all 412/`ERR_STALE_TERM_VERSION`)
- 8 calculations (section_count_tally with optimistic/final variants, placement_selector, credit_pace_requirement with provisional/final variants, recovery_priority, rebalance_imbalance, rebalance_move_selector, counselor_utilization with pinned truncate-then-sum rounding, no_show_freeze_check)
- 26 validations (ordered auth → existence → state → safety → constraint → temporal → fiscal, including segregation-of-duties and cohort-cap rules)
- 26 error codes, all referenced by validations/transitions
- 3 roles (Administrator opaque; Counselor/Student entity-backed), segregation_of_duties role model

**§1.8 instances: 19** — all 9 rule_ids with ≥2 instances each (non_linear_state_machine has 3). Differentiation honored: dual-variant calcs span Course/Section tally vs Student credit domains; combinatorial formulas cover mode (a) 4-input weighted scoring and mode (b) nested-rounding order (0.3056 vs 0.3083 pinned); cascades originate from mark-no-show vs change-execute; priority conflicts use state-vs-fiscal and state-vs-constraint pairs; boundary checks on seat count vs no-show count via different endpoints; temporal overlap on point-slot grid (adjacency legal) vs buffered intervals (10-min buffer, adjacency illegal); compensating invariants on enrollment seats vs teacher load.

**§1.9 instances: 51 total** (44 active with full test_recipes + 7 `excluded_because` stubs pointing at §1.8 instances), spanning all 9 claim-extraction-guide sections: entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_layers, consistency_model.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (465 calls scanned, 0 violations). Additional self-checks passed: no forbidden concurrency vocabulary, enum closure complete, all grounds resolve, instance names unique across both design files, all numeric assertions pre-computed as literals (e.g., preview demand 26.0 → 2 sections vs final 25.0 → 1; recovery scores 36.0/18.0; utilization 0.3056/0.0833; imbalance 6.0→2.0).

## Step 3: Copy Shared Files — 2026-08-11T14:14:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1183_school_counseling_master_schedule_building/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T14:35:00.000Z

All checks pass. The one "failure" was my own arbitrary threshold (expected 6+ mentions of `expected_term_version`; there are 5) — the OCC rule is fully expressed: §2.7 names all three guarded write operations, the non-optional field, the mismatch rejection with `ERR_STALE_TERM_VERSION` (HTTP 412), and the "no other endpoint takes a version field" clause; §3.3, §3.5, and §3.8 each reference the field in workflow context. Rule coverage is complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1183_school_counseling_master_schedule_building/workspace/PRD.md` — 313 lines, ~54 KB.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (headers, 3 roles, identity semantics per role), 2.2 API Response Structure (verbatim fixed block, byte-identical), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending), 2.4 Term Posture Pipeline (7 postures, posture gating, `periods_per_day` immutability), 2.5 Common Resource Properties (incl. the three slim entities without `updated_at`/`version`), 2.6 Precision & Rounding, 2.7 OCC on the term (all 3 rules), 2.8 Nested Retrieval & full validation-pipeline ordering (priorities 1–26 expressed as an ordered prose pipeline), 2.9 Logical Clock (startup default, `to_iso8601`/`current_utc`)
- §3 Business Logic (8 subsections): 3.1 Terms/Catalog/People, 3.2 Course Request Collection, 3.3 Close & Grid Building, 3.4 Publication & Auto-Placement, 3.5 Change Window, 3.6 Appointments & No-Show Freeze & Utilization, 3.7 Credit Audits & Recovery, 3.8 Mid-Year Rebalancing — all 7 calculations (incl. both variants of `section_count_tally` and `credit_pace_requirement`), all state transitions with preconditions/side effects, and all validation conditions paired with error IDs in prose
- §4 Endpoint Definitions (68 endpoints, 4-column table)
- §5 Error Code Catalogue (26 errors, 2-column table)

**Self-check verdicts:**
- Contract 1 (field coverage): 78 entity fields + 15 endpoint-only identifiers — 93 required, 93 present, 0 missing → **PASS**
- Contract 2 (rule coverage): 36 targeted rule spot-checks (OCC triple, priority ordering, all calculation formulas/precision/pinned orders, cross-entity cascades, sibling-branch symmetry for DROP/ADD/SWAP and approve/reject, slim-entity field exposure) — 36/36 expressed → **PASS**
- Contract 3 (§3 path purity): 494 backtick tokens scanned — 0 slash-prefixed, 0 bare HTTP methods, 0 method+path combos → **PASS**
- Auxiliary: §2.2 verbatim body byte-identical; all 26 error IDs present; all 52 state/enum values present; §4/§5 column counts correct; zero fuzzy words; zero operator-symbol leaks.

## Step 5: Generate Unit Tests — 2026-08-11T15:12:00.000Z

## Files written

**`test_helpers/`** (Stage 1) — all under `/home/ubuntu/github/CodingPRD/tasks/task_1183_school_counseling_master_schedule_building/test_helpers/`:
- `types.py` — 10 status/kind enums, 15 entity TypedDicts (append-only `TeacherQualification`/`CreditAudit`/`RebalanceRun` carry only `id`+`created_at`, no `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (52 methods incl. `/_clock/set_current_utc`)
- `api_errors.py` — 26 `ApiErrorId` values + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators enforcing PRD types/ranges
- `factories.py`, `constants.py` (pace table, 8.0 ceiling, 0.5 alternate weight, 360 weekday minutes, freeze threshold 3/90d), `test_users.py` (opaque admin + `make_counselor_headers`/`make_student_headers` entity-backed builders)
- `fixtures.py` — composite helpers: request builders, OCC-aware `schedule_section` (re-reads term version per PATCH), term lifecycle drivers (BUILDING/PUBLISHED/CHANGE_WINDOW/LOCKED), approved-change-request chain, appointment/no-show builders, and `setup_change_window_scenario` (full catalog→publish→window chain with per-period teacher/room pooling so grids never collide accidentally)
- `__init__.py` barrel

**`test_suite/`** — `conftest.py` + 10 test files (`test_01_terms_catalog_and_envelope.py` … `test_10_rbac_and_ownership.py`), 81 tests total.

## Test counts per queue
- **Queue A (Difficulty): 38 tests** — all 19 instances × 2 tests each, every tag resolves.
- **Queue B (Corner): 43 tests** — 44 live instances, 43 covered; 7 `excluded_because:` stubs correctly untranslated (all 7 cross-references resolve to real difficulty instances).

## Skipped instances (PRD-first filter)
- **Corner/errors/error_no_eligible_section_trigger** — the pinned scenario (ADD targeting the only section, which period-conflicts) fails the PRD §2.8 precedence rule: `ERR_STUDENT_PERIOD_CONFLICT` is checked before selector emptiness (`ERR_NO_ELIGIBLE_SECTION` occupies a final position), so a PRD-faithful implementation returns `ERR_STUDENT_PERIOD_CONFLICT`, not the instance's asserted `ERR_NO_ELIGIBLE_SECTION`. Not uniquely derivable → gap left as gap.

## Design-adaptive translations (kept the asserted rule, fixed underdetermined setup)
- `terminal_lockdown_cancelled_section_rejects_patch` — the instance's LOCKED-via-rebalance setup would surface `ERR_INVALID_TERM_POSTURE` (priority 5) before the asserted `ERR_INVALID_STATE` (priority 6). Tests use the PRD-sanctioned BUILDING-time `/sections/{id}/cancel` path so `ERR_INVALID_STATE` is uniquely derivable.
- `credit_projection_vs_final_audit` — the instance relied on unpinned cross-student placement order (capacity-1 sections going to earlier-created fillers); translated to period-collision placement (ART at period 1, PE at period 2), which makes the identical pinned numbers (16.0→14.0 projected, 2.0→4.0 deficiency) deterministic for any student iteration order.
- Approve-time business re-checks (capacity/credit/singleton/quota) are handled per the PRD's decide-list: approvals are taken while the guard passes, then a second executed change pushes the metric past the boundary so the asserted error fires at execute time.

## Lint / stage-check verdicts
- `py_compile` clean on all 19 files; `pytest --collect-only`: **81 collected, 0 errors**.
- C1 verbatim sweep: every quoted citation in all 81 docstrings survives literal grep against PRD.md — **0 failures**.
- C4: every test has exactly one `Design:` tag as the docstring's last line; all tags resolve to real instances; no stub is tagged; no `skip`/`skipif`/`xfail`; no "scaffold" mentions in generated code.

## Step 6: Generate Implementation — 2026-08-11T15:12:00.000Z

Implementation complete. Summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1183_school_counseling_master_schedule_building/workspace/implementation/`):
- `start.sh` — executable; guarded `pip install` (no-op when Flask present), `exec python3 app.py` in foreground; binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` (flask>=3.0,<4.0)
- `app.py` — Flask app, envelope-aware error handlers, blueprint registration
- `db.py` — in-memory dicts only, starts empty (no seeding); logical clock defaulting to exactly `2026-05-01T00:00:00Z`
- `errors.py`, `envelope.py`, `auth.py`, `util.py`, `validate.py` — error catalog, response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit/offset/total_count/has_more` in meta), `X-User-ID`/`X-User-Role` auth, monotonic ISO8601-ms timestamps, Decimal helpers, OCC helpers
- `domain.py` — derived fields computed on read (enrolled_count, cohort_counts, under_enrolled, planned_credit_load, credit_deficient, caseload_count, assigned_section_count, tally_weight, total_requested_seats) + all calculations (placement_selector, section_count_tally both variants, credit_pace_requirement both variants, recovery_priority, rebalance_imbalance, counselor_utilization with whole-minute truncation + 4dp half-up, no-show 90-day freeze)
- `engine.py` — auto-placement walk with alternate fallback, epoch-idempotent audit writes, rebalance consolidation + move sweep
- `routes/` — terms.py, catalog.py, people.py, requests.py, sections.py, changes.py, appointments.py, recovery.py, reads.py (incl. `POST /_clock/set_current_utc` outside the prefix)

**Route count:** 68 scaffold endpoints registered (69 URL rules including Flask's built-in `/static`).

**Self-checks:** `python3 -m compileall` clean; import check passes; booted via `bash start.sh` on 5 fresh ports. ~70 end-to-end assertions passed across 4 smoke scenarios: full term pipeline (COLLECTING→TALLYING→BUILDING→PUBLISHED→CHANGE_WINDOW→LOCKED), auto-placement load-leveling (2/2/1), credit audits (deficiency 5.0, ENGLISH deficient), change-request claim/decide/execute with SoD 403 and OCC 412, rebalance epochs (consolidation-cancel of empty sections; forced donor/receiver move: 1 MOVED + 1 REBALANCE entry at epoch 1, imbalance 3.5→3.0), recovery place/waive, appointment 10-min buffer + student overlap + 3-strike freeze with clock advance lifting it, rank contiguity, 0.25-step credit validation, 401/403/404/409/422 error IDs, pagination meta, DELETE 204, empty-store boot. The 3 smoke "failures" seen mid-run were test-script artifacts (header fallback bug, rebalance legitimately cancelling the only section, state-check-before-grid-check), each re-verified as correct behavior.

**Orchestrator route-parity check:** 68/68 scaffold (method, path) pairs registered in implementation — 0 missing, 0 extra (normalized for Flask path-param syntax).

## Step 7: Run Tests and Iterate — 2026-08-11T15:33:00.000Z

All 8 rounds are clean (81/81 each). The task is complete.

## Summary

**Iterations run:** 4 eight-round parallel sweeps (33 deterministic failures → 1 → 1 → 0).

**Tests deleted:** none — every failing test traced to a verbatim PRD rule, and no assertion was weakened.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `setup_change_window_scenario()`: tests (and the fixture's own docstring) pass course dicts keyed by the PRD payload field `course_code`, but the fixture splatted them into `setup_course(code=...)`, raising `TypeError` in 31 tests' setup. Now translates `course_code` → `code` at the call site.

**Fixes applied to `test_suite/` (test-layer bugs, fixture data violating PRD):**
- Sub-4-char `external_ref` values padded to ≥4 chars — PRD §3.1 verbatim: "a unique `external_ref` district number of 4 to 32 characters". Fixed `test_04_section_scheduling.py` (`G01`→`G001`), `test_05_change_request_workflow.py` (S1/S2/F01/F02/PP1/OW1/OT1/CW1/SD1/OC1), `test_06_change_request_business_guards.py` (`f"P{i:02d}"`/`f"Q{i:02d}"` → `:03d`, plus F01–F03/EDG/THD/SG1/SG2/Q01/IE1–IE3/IM1/DR1/DR2/DP1). Uniqueness within each scenario preserved.
- `test_09_rebalance.py::test_rebalance_epoch_prevents_double_move` — added `"limit": 100` to the ENROLLED schedule-entries query. PRD §2.3 defaults `limit` to 10; the term holds 16 ENROLLED entries and the new `REBALANCE`-origin entries (newest by `created_at`) were silently paginated out, making a correct implementation look like it created 0 entries.

**Fixes applied to `implementation/`:**
- `engine.py::run_rebalance` — the donor drain re-evaluated the receiver list (`enrolled_count < class_size_target`) on *every move*, so a receiver reaching the target dropped out mid-drain and stalled the donor (2 moves instead of 4). PRD §3.8 pins "each donor drains students into its **single best receiver** until the donor reaches `class_size_target` or runs out of movable students" with exactly three per-move guards (period conflict, cohort cap, free seat). The receiver is now selected once when the donor's drain begins, and only the three pinned guards gate each move — confirmed consistent with the scaffold's waterfall formula.

All fixes make the artifacts *more* PRD-faithful; no skips, no weakened assertions, no implementation capabilities beyond PRD, storage remains in-memory only.

## Step 8: Finalize PRD — 2026-08-11T15:45:00.000Z

`PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1183_school_counseling_master_schedule_building/workspace/PRD_FINALIZED.md` with exactly one inline revision and no other changes.

## Summary

**Line counts / delta:** PRD.md 313 lines, PRD_FINALIZED.md 313 lines — 0% line-count delta (one sentence revised in place; +60 words on line 205).

**Changes (one bullet per change):**
- §3.8 — revise — the donor-drain sentence now pins that a donor's receiver is "the highest-ranked receiver at the moment that donor's drain begins, selected once for the drain and never re-evaluated or abandoned mid-drain as the receiver fills," and that the three named guards (period conflict, cohort cap, free seat) are the only per-move checks — `implementation/engine.py:140-185` (`run_rebalance`: `best = recv_pool[0]` chosen once at line 148 before the `while section_enrolled_count(donor) > target` drain loop; only the three guards gate each move at lines 162-174).

**Step-7 items that produced no PRD edit (already pinned verbatim by the PRD; test-layer bugs only):**
- `fixtures.py` `course_code`→`code` translation — PRD §3.1 already pins the payload field `course_code`; impl honors it at `implementation/routes/catalog.py:26`.
- Sub-4-char `external_ref` fixture data — PRD §3.1 already pins "4 to 32 characters"; impl enforces at `implementation/routes/people.py:131`.
- `test_09` missing `"limit": 100` — PRD §2.3 already pins "defaults to 10 ... maximum of 100"; impl enforces at `implementation/envelope.py:40-45`.

**Per-edit pre-edit search log (the single edit):**
- (a) Subject: receiver selection and per-move gating inside the rebalance move sweep (§3.8).
- (b) Impl paths enumerated and read: `implementation/engine.py:104-198` (`run_rebalance` — the sole site of donor/receiver logic, including the outer `while any_move` fixpoint loop, `donors()` at 120-126, `receivers()` at 128-135, drain at 140-185); `implementation/routes/terms.py:204-225` (the only caller, `create_rebalance_run`, plus the list endpoint — no receiver logic of its own); `implementation/domain.py` helpers consumed by the sweep (`section_enrolled_count` :37, `enrolled_entries` :32, `student_enrolled_periods` :116, `section_cohort_counts` :41, `cohort_half_cap` :50, `section_under_enrolled` :54, `term_imbalance` :298) — none implements receiver selection; grep for `class_size_target|receiver` across all impl `*.py` confirmed the only other `class_size_target` uses are term creation validation (`routes/terms.py:35-51`), serialization (`serializers.py:25`), and the section-count tally division (`domain.py:205`), all unrelated to the sweep; `domain.placement_select` (:192) is the separate §3.4/§3.7 selector and is untouched by the edit's scope.
- (c) Wording adjustments made during the search: initial draft considered "selected once per donor per run," but the outer `while any_move` loop can re-encounter a still-over-target donor in a later pass with a freshly re-ranked receiver pool (`engine.py:138-148`), so the wording was re-scoped to "selected once for the drain" / "at the moment that donor's drain begins" — true for every pass. Also confirmed the "never re-evaluated mid-drain as the receiver fills" phrasing is consistent with the receiver legitimately crossing `class_size_target` mid-drain (drain stops on the donor reaching target, not the receiver) and with the free-seat guard remaining the only capacity check.

## Step 9: Complete PRD — 2026-08-11T15:56:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1183_school_counseling_master_schedule_building/workspace/PRD_COMPLETED.md` written (copied from `PRD_FINALIZED.md`, edited in place only).

**Size**: PRD_FINALIZED.md 313 lines / 54,362 chars → PRD_COMPLETED.md 313 lines / 58,282 chars (char-delta +3,920; 25 paragraphs touched, no sections added).

**Counts**: 19 ambiguity-pins, 10 mismatch-revisions.

**Changes** (section — insert|revise — class — what — impl ref):

- §2.1 — insert — ambiguity — Student-role callers on student-scoped reads (record/schedule/credit-audit/credit-projection) get `ERR_FORBIDDEN_OWNERSHIP` when id mismatches — implementation/routes/people.py:179-185
- §2.3 — insert — ambiguity — limit/offset out-of-range values are clamped, non-integers fall back to defaults — implementation/envelope.py:39-51
- §2.3 — insert — ambiguity — `has_more` = offset + page size < total_count — implementation/envelope.py:25
- §2.5 — revise — mismatch — `version` starts at 1 and increments only where §3 states it; sweeps, publication flips, placement outcomes, section cancellation, entry transitions, rebalance moves, and waivers refresh `updated_at` only — implementation/validate.py:10-21 and all `touch()` sites
- §2.7 — insert — ambiguity — OCC mismatch fires right after existence, before posture; missing/non-integer `expected_term_version` defers to 400 at shape stage — implementation/validate.py:85-102
- §2.8 — insert — ambiguity — missing-field 400 surfaces at the point the field is first consumed, ahead of existence/posture checks — implementation/validate.py:24-27 and route orderings
- §2.8 — insert — mismatch — on change-request decisions the add-side guards (through `ERR_NO_ELIGIBLE_SECTION`) precede the quota — implementation/routes/changes.py:217-229
- §3.1 — insert — ambiguity — duplicate term `code`, `course_code`, `room_number`, `external_ref` all rejected with `ERR_INVALID_REQUEST` — terms.py:46-47, catalog.py:48-49, catalog.py:102-103, people.py:132-133
- §3.1 — revise — mismatch — caseload assignment exists only at student creation; `caseload_count` counts every student naming the counselor (no withdrawal concept) — people.py:146, domain.py:79-80
- §3.2 — revise — ambiguity — rank contiguity applies to non-alternate requests in `DRAFT`/`SUBMITTED` and is re-validated at submission — requests.py:55-67, 138-139
- §3.2 — revise — mismatch — prerequisite satisfied exactly by an `ENROLLED` entry in the prerequisite course (no earned-credit history, no term scoping) — requests.py:29-41
- §3.2 — insert — ambiguity — duplicate-course guard counts non-alternate requests in any state other than `WITHDRAWN` — requests.py:21, 46-52
- §3.2 — revise — ambiguity — `total_requested_seats` is a plain count of `SUBMITTED`/`LOCKED` requests, not weight-summed — domain.py:95-97
- §3.2 — revise — ambiguity — tally preview returns an object with a `rows` field — terms.py:198-201
- §3.4 — revise — ambiguity — auto-placement processes students in `created_at` ascending order, walking locked primaries — engine.py:61-67
- §3.4 — insert — ambiguity — student resource's `planned_credit_load` aggregates `ENROLLED` entries across all terms — serializers.py:44, domain.py:69
- §3.4 — revise — mismatch — a failed primary becomes `UNPLACED` after its fallback pass whether or not an alternate placed; failed and never-tried alternates also resolve to `UNPLACED` — engine.py:69-97
- §3.4 — revise — ambiguity — publication audits are written for students with at least one `LOCKED` request — engine.py:58-60, 99-101
- §3.5 — insert — ambiguity — filing requires acting student == payload `student_id`; new requests carry `reviewed_by_counselor_id` null and `decided_by_admin` false — changes.py:99-100, 115-120
- §3.5 — revise — mismatch — approval re-runs add-side guards (incl. target-section `PUBLISHED` check) before the quota; `DROP` approval runs only the quota — changes.py:217-232
- §3.5 — revise — mismatch — execution's `ERR_NO_ELIGIBLE_SECTION` fires exactly when the named `add_section_id` is not `PUBLISHED` (after the cohort guard); drop entry must still be `ENROLLED` else `ERR_INVALID_STATE` — changes.py:251-256, 264-265, 67-69
- §3.6 — insert — ambiguity — booking ownership: students book only themselves; counselors book only their own id and caseload students — appointments.py:33-42
- §3.6 — revise — ambiguity+mismatch — utilization window params optional (default: start of logical day → logical now); booked minutes count appointments fully contained in the window; zero available minutes → utilization 0.0000 — people.py:57-64, domain.py:316-347
- §3.7 — revise — mismatch — `deficient_subjects` sweep counts planned credits per subject only; lifetime `earned_credits` is not subject-attributed — domain.py:246-274
- §3.7 — insert — ambiguity — credit-audit read refreshes the persisted row idempotently per epoch; both credit reads resolve the term via `term_id` param, defaulting to the most recently created term — people.py:188-195, 218-223; engine.py:24-42
- §3.7 — insert — ambiguity — recovery-placement creation is not posture-gated and does not verify credit deficiency; only caseload ownership is enforced — recovery.py:22-46
- §3.7 — insert — ambiguity — priority score with no audit uses zero deficiency and no deficient subjects — domain.py:283-291
- §3.7 — revise — mismatch — placement guard order: credit ceiling, then singleton cap, then the selector (period/seat/program as eligibility filters → `ERR_RECOVERY_NO_SECTION`), then the cohort guard on the selected section — recovery.py:86-110

No other divergences found: §3.3 close/generate/publish, §3.8 rebalance (already pinned in PRD_FINALIZED), the §4 endpoint table, and the §5 error catalog all match the implementation as written.

# Worklog — task_1318_homeschool_umbrella_school_portfolio

## Step 1: Create Task Directory — 2026-08-12T21:54:00.000Z

Task directory `tasks/task_1318_homeschool_umbrella_school_portfolio/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-12T22:56:00.000Z

The scaffold for the Homeschool Umbrella School & Portfolio Review scenario is generated, self-consistent, and lint-clean.

### Files written

- `SCAFFOLD.yaml` (1,401 lines — §1.0–§1.7, scenario verbatim, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (964 lines — single top key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (1,504 lines — single top key `scaffold_corner_design`)

### Counts

- **Entities: 16** (AcademicYear, Family, Student, Enrollment, NoticeOfIntent, CurriculumPlan, AttendanceEntry, Portfolio, Evaluation, ExamSession, TestRegistration, CourseCredit, CoopClass, CoopEnrollment, GraduationApplication, ComplianceReport)
- **State machines: 14** entries covering 12 entities — including two cyclic machines (CurriculumPlan revision/amendment loop; Portfolio remediation loop with forced rejection at attempt 3) and parallel dimensions on Enrollment (enrollment_status × compliance_standing)
- **Calculations: 13** (incl. dual-variant provisional/certified attendance, dual-variant official/projected graduation audit, per-line-vs-sum-rounded co-op fee, refund waterfall, bucket-minimum credit audit, waitlist selector policy)
- **Validations: 12** ordered priority rows (auth → ownership → existence → shape → state → OCC → safety → temporal → constraint → referential → fiscal)
- **Endpoints: 89** (incl. `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`, and `POST /families/{id}/ledger-payments` added mid-design via the §1.5 priority ladder when §1.9 drafting proved graduation's fee gate otherwise unreachable)
- **Errors: 41** — all referenced by ≥1 validation/transition
- **Roles: 6** (Parent entity_backed:Family; Reviewer/Registrar/AcademicDirector/StateAuditor/System opaque; segregation-of-duties model)
- **§1.8 instances: 18** (9 rules × 2, all non-stub) — all differentiation clauses honored
- **§1.9 instances: 51 non-stub + 4 excluded-because stubs** across all 9 claim-guide sections; every error code and OCC rule has at least one executable recipe

### Verification

`scaffold_lint.py` verdict, final run, verbatim: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (1,292 calls scanned; one FK violation found and fixed during iteration — added `GET /graduation-applications?academic_year_id?`.)

Additionally audited programmatically: instance-name uniqueness across both design files, forbidden concurrency vocabulary absent, every error referenced, stub `difficulty_instance` refs resolve, endpoint roles ⊆ declared roles, all roles carry `identity:`. All formula-derived asserts are pre-computed literals. No sibling task directory was read at any point.

## Step 3: Copy Shared Files — 2026-08-12T22:56:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1318_homeschool_umbrella_school_portfolio/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T23:10:00.000Z

PRD generation complete. Summary report:

### Output

- **File**: `workspace/PRD.md`
- **Line count**: 398 lines (61.9 KB)
- **Forbidden files**: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

### Section structure

- **§1. Introduction** — 2 paragraphs (statutory-compliance burden angle + audit-driven/deadline-driven design pressures)
- **§2. Global Specifications** (11 subsections): 2.1 RBAC (6 roles) · 2.2 API Response Structure (byte-identical to shared block) · 2.3 Pagination · 2.4 The Logical Clock (default 2026-08-01T00:00:00Z) · 2.5 Common Resource Properties (incl. Evaluation exception) · 2.6 Nested Resource Retrieval · 2.7 OCC · 2.8 Validation Pipeline Ordering (12-step) · 2.9 Time/Scheduling/Precision · 2.10 Compliance Standing Dimension · 2.11 Hierarchical Consistency & Cascades
- **§3. Business Logic** (9 subsections, chronological year-lifecycle grouping)
- **§4. Endpoint Definitions** — 89-row table, 4 columns only
- **§5. Error Code Catalogue** — 41 rows, 2 columns only

### Hard Contract reports

- Field coverage: entities[].fields 106/106 present; endpoints[].request_body 56/56; query_params 7/7. Status: PASS (3 missing FK names found and repaired during iteration).
- Rule coverage: 12/12 validations as ordered pipeline; 2/2 OCC rules; 63/63 state transitions; 13/13 calculations with constants embedded; 12/12 validation conditions matchable to error_ids; 89/89 endpoint side effects enumerated; entity field defaults/immutability reconstructible; 14 sibling-branch symmetry groups checked, 0 asymmetric. Status: PASS.
- Path purity (§3): 610 backtick tokens scanned, 0 path/method tokens. Status: PASS.
- All 41 error IDs in §1–§3 prose and §5 table; all 89 paths in §4; 76 enum/state values verbatim; no pseudocode operators; no fuzzy hedging.

## Step 6: Generate Implementation — 2026-08-12T23:40:00.000Z

Implementation complete. Final summary:

**Files written** (all under `workspace/implementation/`):

- `start.sh` — executable launcher; guarded `pip install` (no-op when flask importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground.
- `requirements.txt` — `flask>=3.0`.
- `app.py` — Flask app factory, blueprint registration, `ApiError`/404/405/generic error handlers, `app.run(host="0.0.0.0", port=$PORT)`.
- `db.py` — 16 in-memory dicts keyed by id; empty at boot, zero seeding.
- `clock.py` — logical clock, frozen at `2026-08-01T00:00:00Z` until advanced, forward-only, 3-fractional-digit ISO 8601 UTC formatting/parsing.
- `errors.py` — `ApiError` + all 41 catalog error IDs with their HTTP statuses.
- `response.py` — exact scaffold envelope: `meta{api_request_id, api_request_timestamp}`, `response_type`, `data`; list responses add `limit`/`offset`/`total_count`/`has_more` inside `meta`.
- `middleware.py` — route decorator enforcing pipeline steps 1-4: auth-header presence → role admissibility → Parent ownership (resolved to root family through any resource kind) → left-to-right path existence (404).
- `validation.py` — body well-formedness validators (step 5): required fields, types, enums, integer ranges, subject-score shape.
- `serializers.py` — per-entity output shaping (Evaluation omits `updated_at`/`version` per PRD §2.5).
- `services/core.py` — id minting, `touch` (updated_at + version++), cross-aggregate navigation, ownership-root resolution, pagination (limit default 10, min 1, max 100, offset default 0), created_at-ASC ordering.
- `services/progress.py` — instructional_progress: 240-min qualifying days, 600-min daily cap, provisional (RECORDED+VERIFIED) vs certified (VERIFIED-only) variants, recomputed on every attendance mutation.
- `services/testing.py` — testing_satisfied recompute; passing percentile 23.
- `services/fees.py` — family ledger charge/credit with 0→positive stamping and exact-0 clearing of `oldest_unpaid_charge_at`, 30-day OVERDUE aging; early-bird (30 days, 10%) + sibling (15%) discount capped at 25%, round-half-up per line via `Decimal`; refund waterfall (SCHOOL_CANCEL/SCHOOL_STANDING full; PARENT_INITIATED: pre-start minus 2500¢ floor 0, within 14 days half of non-materials, later 0).
- `services/coop.py` — half-open meeting-window overlap, deterministic waitlist promotion (created_at ASC, tie-break enrollment created_at ASC, eligibility re-checked, one per freed seat, re-run loop), drop cascade, NONCOMPLIANT co-op cascade.
- `services/credits.py` — credit_value = floor(hours/60)*0.5 via `Decimal`; official (POSTED) and projected (+VERIFIED/COMPLETED) audits; GPA round-half-up 2dp, null on empty; subject bucket minimums.
- `services/compliance.py` — hard/soft violation derivation (notice deadline, year-end testing/certified days/minutes, rejected portfolio; portfolio-due and mid-year pace soft checks), absolute standing recompute with recovery, NONCOMPLIANT cascade firing, sweep (standing + ACTIVE→COMPLETED + CoopClass OPEN→IN_SESSION→COMPLETED with roster completion).
- `routes/` — 14 blueprints: years, families, students, enrollments, notices, plans, attendance, portfolios, exams, credits, coop, graduation, reports, clock_route.

**Endpoint count: 89** — the full §1.5 table, including `POST /_clock/set_current_utc`.

**Organization:** State machines live in route handlers (explicit current-state guards), cascades factored into services; calculations isolated in `services/` with exact `Decimal` round-half-up precision and scaffold constants (240/600, 2500¢, 30/14 days, 10/15/25%, 22.0/4.0/3.0 thresholds, percentile 23); validations follow the §2.8 pipeline order inside each handler (decorator steps 1-4, body 5, state gates 6, OCC 7, duty/standing 8, temporal 9, structural 10, referential 11, fiscal 12).

**Boot verification:** smoke-tested `start.sh` on fresh processes twice — 30+ assertions across the full lifecycle plus a second deep pass (early-bird/sibling fee math, OCC 412, waitlist promotion on drop with refund waterfall, class-cancel full refunds, exam 30-minute buffer with exactly-30 allowed, credit hours 59→422, GPA 3.59, graduation criteria chain with both segregation-of-duties checks, `DIP-2026-001` numbering, transcript sealing blocking revoke). Both runs: ALL PASSED. Store starts empty on every boot; no seeding anywhere.

## Step 5: Generate Unit Tests — 2026-08-12T23:55:00.000Z

All checks pass. Final state: 87 tests collected cleanly by pytest, all imports resolve, no forbidden markers.

**Files written**

`test_helpers/` (9 files):
- `types.py` — 16 entity TypedDicts + status enums + `UserRole`; `Evaluation` (immutable) correctly carries only `id`/`created_at`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint
- `api_errors.py` — all 41 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py`, `factories.py`, `constants.py` (240/600 minute rules, 23 percentile, 60h blocks, 22.0/4.0/3.0 audit minimums, 10/15/25 discount tiers, 2500-cent admin fee, canonical 2026-2027 year)
- `test_users.py` — opaque-role constants + mandatory `make_parent_headers(family_id)` builder (Parent is entity_backed:Family)
- `fixtures.py` — composite setups: `setup_active_enrollment`, `setup_administered_registration`, `create_posted_credit`, `setup_graduation_candidate`, `register_coop` (fresh OCC version), `create_year_with_registered_enrollment`, `set_clock`
- `__init__.py` — barrel export

`test_suite/` (14 files): `conftest.py` + `test_01_families_and_years.py`, `test_02_notices.py`, `test_03_curriculum_plans.py`, `test_04_attendance.py`, `test_05_enrollment_activation.py`, `test_06_portfolios.py`, `test_07_exams.py`, `test_08_coop_fees.py`, `test_09_coop_cascades.py`, `test_10_credits.py`, `test_11_graduation.py`, `test_12_compliance.py`, `test_13_rbac_security.py`.

**Test counts**
- Total: **87 tests** (pytest-collected successfully)
- Queue A (Difficulty): **36 tests** — all 18 instances × exactly 2
- Queue B (Corner): **51 tests** — all 51 non-stub instances × 1; 4 `excluded_because:` stubs not translated

**Skipped instances:** none — every instance passed the PRD-first two-condition filter.

**PRD-faithfulness adjustments made during translation (not skips):**
1. `academic_year_defaults_applied`: dropped the YAML's `version == 1` clause — PRD §2.5 says version "increments with every mutation" but never pins the initial value (two-reader failure). Defaults + PLANNING asserted.
2. `curriculum_plan_revision_cycle`: replaced absolute version literals (6/7) with captured-version `assert_version_incremented` checks (same rationale).
3. Three instances (`coop_registration_safety_before_fiscal_priority`, `ledger_payment_settles_balance`, `graduation_approval_requires_settled_fees`) specified class `start_date: 2026-09-20` while expecting an 11000-cent charge at the 2026-08-01 default clock — but PRD §3.7's early-bird rule yields a 10% discount (10000) for that date pair. Class start set to 2026-08-25 (24 days out, no early-bird), making the pre-computed literals (11000 / 8500 refund / 2500 residual) exactly PRD-derivable; asserted gates unchanged.

**Self-audit results**
- Stage 1: all helper modules parse and import under the framework; `ApiClient` method names, fixture signatures, and error constants used consistently; ownership-gated calls thread `family["id"]` everywhere.
- Stage 2: automated tag audit — 69 required tags (18 Difficulty + 51 Corner), 87 tagged tests, zero missing/short, zero unknown tags, zero untagged/dual-tagged; verbatim-citation sweep — every docstring quote survives whitespace-normalized literal grep of PRD.md (12 initial failures from elisions/paraphrases rewritten and re-verified); no skip/skipif/xfail markers; no scaffold references in comments/docstrings.

## Step 7: Run Tests and Iterate — 2026-08-13T00:15:00.000Z

All 8 rounds at the original timeouts pass cleanly with 87/87. The fixes are stable.

**Iterations run:** 2 sweeps after fixes (initial sweep + 2 verification sweeps = 3 total, all 8 rounds each).

**Tests deleted:** None — all 4 originally-failing tests traced to verbatim PRD rules and were fixed via STEP 2 (test_helpers) and STEP 3 (implementation).

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `setup_graduation_candidate` line 402-405: changed `credit_blocks or GRADUATION_CREDIT_BLOCKS` to `credit_blocks if credit_blocks is not None else GRADUATION_CREDIT_BLOCKS`. Why: the empty-list `[]` argument (used by `test_graduation_evaluator_equals_portfolio_reviewer_forbidden` to test the segregation gate before the credit audit) was being overridden by the default credit blocks via Python's falsy-`or` semantics, making the student pass the credit audit and the segregation gate never reached.

**Fixes applied to `test_suite/`:** None.

**Fixes applied to `implementation/`:**
- `workspace/implementation/services/core.py` — added module-level `_SEQ` monotonic counter and `_next_seq()`; `make_record` now stamps each record with `_seq` (insertion order); `sorted_by_created` uses `(created_at, _seq)` instead of `(created_at, id)`. Why: PRD §3.7 requires "the comparison is made on creation timestamps alone and never consults entity identifiers" — but the logical clock is frozen at `2026-08-01T00:00:00.000Z` between test steps, so every record shares the same `created_at` and ties need a deterministic non-identifier tiebreaker (insertion sequence).
- `workspace/implementation/services/fees.py` — `compute_discount_pct` now takes an optional `created_seq` parameter and compares `(created_at, _seq)` tuples. When the new record's seq is unknown (default `1 << 62`), all existing records sort as "created before". Why: with frozen clock, the old comparison `(ce["created_at"], "") >= created_key` skipped every tied record, so the sibling discount never fired when registrations happened at the same clock tick — breaking PRD §3.7's "created before this one" semantics for the canonical sibling scenario.

**Flakiness observed but not attributed to bugs:** Round-1 sweep showed `Connection reset by peer` and `could not be restarted` errors on a handful of tests under 8× parallel load; these were server-boot timeouts, not assertion failures, and did not reproduce in subsequent sweeps.

## Step 8: Finalize PRD — 2026-08-13T00:25:00.000Z

`PRD_FINALIZED.md` produced with three minimal inline edits, all tracing to the two `implementation/` fixes in `<step_7_diff>`. The fixture fix (`test_helpers/fixtures.py`) was a pure fixture bug and required no PRD edit.

### Line counts
- `PRD.md`: 398 lines; `PRD_FINALIZED.md`: 398 lines; delta 0 lines (0.0%). All edits in-place sentence revisions/extensions, ~+380 chars total.

### Changes
- §2.3 (Pagination) — insert — extended the default-ordering sentence: ties on identical `created_at` are broken by server creation order, earliest first, identifiers never consulted — `implementation/services/core.py:13-25` (`_SEQ`/`make_record`), `core.py:171-172` (`sorted_by_created` key `(created_at, _seq)`).
- §3.7 (Co-op Fees) — revise — sibling-discount clause: dropped "timestamps alone", added that same-instant records are ordered by server persistence sequence and that any record already persisted when the fee is computed counts as created before the line being priced — `implementation/services/fees.py:61-87` (`(created_at, _seq)` tuple keys, sentinel `1 << 62`).
- §3.9 (Compliance report snapshot) — revise — `noncompliant_enrollment_ids` ordering now pins the same tie-break (identical `created_at` → server creation order, never by identifier) — `implementation/routes/reports.py:18-27` (`_snapshot` via `core.sorted_by_created`).

### Per-edit pre-edit search log
1. **§2.3 edit.** (a) Subject: default list-endpoint ordering and its tie-break. (b) Enumerated/read: `services/core.py:171-172`; all 13 `success_list` sites — `routes/students.py:31,50`, `routes/years.py:127,139,151,161`, `routes/enrollments.py:159` (shared `_list_child` helper covering all seven per-enrollment child lists), `routes/families.py:49`, `routes/exams.py:108`, `routes/portfolios.py:153`, `routes/graduation.py:59`, `routes/coop.py:121`; also `serializers.py` (confirmed `_seq` never leaks into responses) and `routes/portfolios.py:99-102` (evaluations created without `_seq` → default 0 → stable-sort insertion order). (c) Phrased the tie-break as "the order in which the server created the records" rather than "an internal `_seq` field", covering both `make_record`-minted records and `_seq`-less evaluation rows; added "entity identifiers are never consulted".
2. **§3.7 edit.** (a) Subject: sibling-discount "created before this one" comparison. (b) Enumerated/read: `services/fees.py:61-87`; both call sites — `routes/coop.py:163-165` (initial registration: priced before `make_record`, sentinel semantics) and `services/coop.py:92-95` (waitlist promotion: priced with original `created_at`, same sentinel semantics); no other `compute_discount_pct` callers. (c) Added "any record already persisted when the fee is computed counts as created before the line being priced" to cover the promotion call site; replaced "timestamps alone" with "timestamps" plus persistence-sequence tie sentence; kept "never consults entity identifiers" verbatim (`_seq` is an insertion counter, not an entity identifier).
3. **§3.9 edit.** (a) Subject: ordering of `noncompliant_enrollment_ids` in the report snapshot. (b) Enumerated/read: `routes/reports.py:18-27` (only builder, routes through `core.sorted_by_created`); confirmed all enrollments minted via `core.make_record` so `_seq` always present. (c) Kept "never by identifier" verbatim, inserted only the tie-break clause mirroring §2.3.

No other edits made: waitlist-promotion ranking (`services/coop.py:84`), latest-accepted-evaluator selection (`routes/graduation.py:45`), and diploma-sequence sort (`routes/graduation.py:156`) were not touched by Step 7 and are outside hard scope; existing PRD prose for them remains consistent with the implementation.

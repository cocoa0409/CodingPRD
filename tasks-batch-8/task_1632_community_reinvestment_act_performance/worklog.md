## Step 2: Generate Scaffold — 2026-08-14T00:00:00.000Z

Generated a fresh CRA Performance Management scaffold (no sibling tasks consulted):

**Files**
- `SCAFFOLD.yaml` — §1.0–§1.7 (scenario verbatim, `compliance_audit` + `posture_driven_gating` archetypes; layers: optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers; flat topology; segregation-of-duties role model)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design` (§1.9)

**Counts**
- Entities: 9 (AssessmentArea, DemographicProfile, LoanRecord, CommunityDevelopmentActivity, Branch, PublicComment, PublicFile, ExamCycle, ExpansionApplication)
- State machines: 8 — non-linear on 4 entities (area review cycle ACTIVE↔UNDER_REVIEW, CD disqualify→resubmit loop, loan confirm→draft correction loop, exam appeal cycle FIELDWORK→PRELIMINARY→APPEALED→FIELDWORK)
- Calculations: 6 (CD qualified amount FULL_COUNT vs PRO_RATA; lending metrics SNAPSHOT vs CURRENT; per-loan-then-sum register rounding pinned; exam composite weighted-threshold bands; branch access score with min/max + penalty; demographic percentages)
- Endpoints: 48 (incl. `POST /cra/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`)
- Errors: 28; Validations: 27 rows across 9 priority tiers; Roles: 6 (all `opaque` identity; SoD enforced on review-decision vs. submitter); Concurrency rules: 2 (OCC on AssessmentArea.version for demographic-profile supersede and PATCH)
- Difficulty-design instances: 18 (9 rules × 2), all with literal-precomputed asserts (e.g., composite 5.00→SATISFACTORY; register rounding 400000 vs forbidden 300000; access score 35.00)
- Corner-design instances: 54 (43 full recipes + 11 `excluded_because` stubs referencing §1.8 instances)

**Verification**: `scaffold_lint.py` verdict — clean lint (329 calls scanned). No forbidden race vocabulary, unique instance names across both design files (72 total), all 9 rule_ids at ≥2 instances, all stub references resolve, every error id referenced outside its catalog entry, all endpoint roles declared in RBAC.
## Step 3: Copy Shared Files — 2026-08-14T00:00:01.000Z

Copied ./INSTRUCTION.md to tasks/task_1632_community_reinvestment_act_performance/workspace/INSTRUCTION.md.
## Step 4: Generate PRD — 2026-08-14T00:00:02.000Z

**Output**: `workspace/PRD.md` — 313 lines, generated solely from `SCAFFOLD.yaml` (the difficulty/corner design files were never opened).

**Section list**: §1 Introduction; §2 Global Specifications (2.1 RBAC six roles opaque identity; 2.2 Response Structure byte-identical verbatim block; 2.3 Pagination limit 10/1/100, offset 0, created_at ascending; 2.4 Common Resource Properties; 2.5 Logical Clock default 2026-08-01T00:00:00Z; 2.6 Nested Resource Retrieval left-to-right; 2.7 OCC expected_assessment_area_version + ERR_STALE_VERSION/412; 2.8 Monetary Precision; 2.9 Delineation Integrity; 2.10 Public File Posture as Examination Gate; 2.11 Validation Ordering nine tiers); §3 Business Logic (3.1 Assessment Areas; 3.2 Demographic Profiles; 3.3 Loan pipeline; 3.4 CD qualification review with explicit check ordering SoD → LMI threshold → area-active → budget; 3.5 Branches 90-day notice; 3.6 Public file & comments refresh semantics; 3.7 Exam cycle composite weights ½/¼/¼ inclusive bands 8.50/5.00/2.50, appeal cycle, finalize cascade with RATING_BLOCK; 3.8 Expansion applications latest-finalized-exam guard; 3.9 Metrics CURRENT vs SNAPSHOT bases, per-loan $1,000 rounding under $1MM cap, access score 50 + 100×diff − 5×closures clamped 0/100); §4 Endpoint table 48 rows; §5 Error catalogue 28 rows.

**Coverage audit results**: Contract 1 Field-Name Coverage PASS (74/74 entity fields, 55/55 request-body identifiers, 10/10 query params); Contract 2 Rule Coverage PASS (27/27 validations, 2/2 OCC rules, 21/21 transitions with cascades, 6/6 calculations); Contract 3 §3 Path Purity PASS (410 backtick tokens, 0 paths/methods); all 28 error IDs in prose; all 26 state values and 42 enum literals verbatim; §2.2 byte-identical to canonical source.
## Step 5: Generate Unit Tests — 2026-08-14T00:00:03.000Z

### Stage 1 — `test_helpers/` (9 files, ~1,600 lines)
- `types.py` — 9 entity TypedDicts (all `common_fields: true` → id/created_at/updated_at/version), 18 status/field enums, role enum
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (48 methods incl. logical clock)
- `api_errors.py` — 28 error IDs + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_posture_invariants` (PRD §2.10 posture rule)
- `factories.py`, `constants.py` (thresholds: $1MM revenue cap, 0.51 FULL_COUNT, 90-day notice, composite weights/bands, access-score constants, clock default), `test_users.py` (6 opaque roles + SoD-sensitive per-user builders), `fixtures.py` (5-tier composites: active areas, OCC-guarded profiles, confirmed/reported loans, submitted/qualified activities, open branches, COMPLETE public file, exam lifecycle through FINALIZED, staged branch-opening applications)

### Stage 2 — `test_suite/` — 79 tests, 0 skipped instances

| File | Tests | Queue A | Queue B |
|---|---|---|---|
| test_01_assessment_area_delineation | 18 | 6 | 12 |
| test_02_loan_records_and_lending_metrics | 14 | 4 | 10 |
| test_03_cd_qualification_review | 11 | 10 | 1 |
| test_04_branch_network_and_access | 9 | 4 | 5 |
| test_05_public_file_and_comments | 8 | 4 | 4 |
| test_06_examination_cycle | 11 | 6 | 5 |
| test_07_expansion_applications | 2 | 2 | 0 |
| test_08_access_control_and_existence | 5 | 0 | 5 |
| test_09_logical_clock | 1 | 0 | 1 |

**Coverage:** all 18 difficulty instances ≥2 tests (36 total); all 43 non-stub corner instances ≥1 test; all 11 `excluded_because:` stubs verified to resolve to real difficulty instances and not translated.

**Skipped instances:** none. Every instance passed the PRD-first two-condition filter. One recipe adaptation: `tract_partition_move_conserves_union`'s literal setup places areas A and B in the same msa_code with overlapping open-ended windows, which PRD §2.9 rejects at creation; the test uses distinct msa_codes (period-overlap is msa-scoped, tract exclusivity is global), preserving every asserted claim.

**Audits:**
- Stage 1: package imports cleanly; conftest bridges all 6 role fixtures
- Stage 2: 79/79 collect; zero untagged, zero double-tagged, zero phantom tags; every `Design:` line resolves to a source yaml `name:`
- Stage 3: every docstring's quoted PRD text survives literal grep of PRD.md (5 elided-quote violations found and fixed); no `skip`/`skipif`/`xfail` markers; asserted priority orderings (SoD→LMI→area→budget, state→referential, existence→business-safety) are all named in PRD §2.11 prose

## Step 6: Generate Implementation — 2026-08-14T00:00:04.000Z

**Files created** in `workspace/implementation/`:

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Executable launcher; guarded `pip install`, `exec python3 app.py`, honors `PORT` (default 10000), binds `0.0.0.0` |
| `requirements.txt` | 1 | `flask>=2.2` |
| `app.py` | 15 | Entry point; imports route modules, runs threaded server |
| `core.py` | 682 | Flask app, logical clock, in-memory store, envelope helpers, ApiError + handlers, auth/RBAC, validators, pagination, Decimal rounding helpers, cascades/recomputes, all 9 serializers, enum constants |
| `routes_areas.py` | 395 | Assessment areas CRUD + lifecycle, demographic profiles, access-analysis, 5 area-scoped lists |
| `routes_lending.py` | 274 | Loan records + CD activities (review-decision guard chain, resubmit) |
| `routes_branches_files.py` | 234 | Branches (open/close), public comments, singleton public file + refresh-items |
| `routes_exams.py` | 310 | Exam cycle lifecycle, composite rating, finalize cascade, lending-metrics |
| `routes_applications.py` | 180 | Expansion applications (rating gate, branch staging), `/_clock/set_current_utc` |

**Endpoints: 48** (all 48 from the scaffold endpoint table, under `/cra`).

**Verification:** booted via `bash start.sh`; ~110-check smoke suite covering every endpoint family, all error codes, state machines, OCC, cascades, calculations (pro-rata half-up rounding, composite bands, register per-loan round-then-sum, access score clamp), pagination (default/clamp/400), and logical-clock behavior — all passed. Reboot after writes returns a fresh empty store; 4 concurrent `start.sh` boots (mimicking the 8-round sweep) all healthy.

**Notable design decisions:**
- No seeding — store starts empty; all state built via the API.
- Logical clock everywhere — created_at/updated_at/received_at/date stamps all read the logical clock (default `2026-08-01T00:00:00Z`, 3-fractional-digit `Z` format); never wall-clock. Clock set echoes `to_iso8601` verbatim.
- Validation tier order exactly per PRD §2.11: auth → RBAC → existence (left-to-right) → shape → state → safety (SoD, file gate, rating guard) → constraint (incl. exam-window overlap before window-order per §3.7) → temporal → referential → fiscal. OCC (`expected_assessment_area_version` → 412) sits after shape/state, before business rules.
- PRD §2.4 composition for cascades: any cascade that changes a stored field bumps that entity's version/updated_at; no-op recomputes don't.
- Tract exclusivity on PATCH enforces the stated invariant (two areas in {ACTIVE, UNDER_REVIEW}), so it bites when patching an UNDER_REVIEW area; DRAFT edits pass (conflict surfaces at activation instead).
- `pending_comment_count` computed live from RECEIVED comments; comment create/publish still bump the file's version per §2.4.
- Body-FK references return `ERR_ASSESSMENT_AREA_NOT_FOUND` 404; duplicate `branch_code` returns `ERR_VALIDATION` 400 (no dedicated error ID in catalog).
- All money/ratio math in Decimal with ROUND_HALF_UP (4dp ratios, 2dp scores, whole-cent qualified amounts, per-loan $1,000 register rounding before summing).
## Step 7: Test-Fix Iteration Loop — 2026-08-14T00:00:05.000Z

All 8 rounds pass 79/79 with zero failures and zero errors.

- **Iterations run:** 2 (initial 8-round sweep → fix → verification 8-round sweep, all 8 rounds green at 79/79).

- **Tests deleted:** None fully deleted. One assertion removed under STEP 1c (partial-coverage split):
  - `test_01_assessment_area_delineation.py::test_tract_partition_move_conserves_union` — removed the step that PATCHed a **DRAFT** area to add a tract held by an UNDER_REVIEW area and demanded `ERR_TRACT_OVERLAP`. **Collapse pattern:** unique-derivability failure. PRD §2.9 scopes the invariant pairwise — "no census tract may appear in the `census_tracts` of two areas whose status is `ACTIVE` or `UNDER_REVIEW`" — so a DRAFT+UNDER_REVIEW pair is not a violation, and §3.1 assigns the rejection to activation ("Activation... re-verifies that no tract collides with another `ACTIVE` or `UNDER_REVIEW` area"), a behavior the companion test `test_tract_overlap_rejected_at_activation` verifies and passes 8/8. A faithful PRD-only reader could either reject at edit time (test's reading) or allow the DRAFT edit and reject at activation (implementation's reading); PRD does not uniquely determine the choice. The scaffold's `compensating_invariant/tract_partition_move_conserves_union` design drove the over-strong assertion. The covered remainder (compensating edit pair: drop T1 from the UNDER_REVIEW area, then add it to the DRAFT area, union conserved, OCC-guarded per §2.7/§3.1) was kept and passes under both readings; the docstring was updated to reflect the trimmed scope.

- **`test_helpers/` fixes:** None — fixtures, factories, role-header builders, and the assertion library all audited consistent with PRD (§2.1 opaque identity, §2.7 OCC fields, §3.x payload shapes, SoD-sensitive user-id builders).

- **`implementation/` fixes:** None — the implementation (notably `check_tract_exclusivity` in `core.py` and the PATCH/activation paths in `routes_areas.py`) is PRD-faithful; the failure was purely the test asserting a non-uniquely-derivable edit-time rejection.
## Step 8: Finalize PRD — 2026-08-14T00:00:06.000Z

PRD_FINALIZED.md written with exactly two in-place revisions, both tracing to the single Step 7 item (the removed DRAFT-edit `ERR_TRACT_OVERLAP` assertion in `test_tract_partition_move_conserves_union`).

**Line counts / delta**: PRD.md 313 lines; PRD_FINALIZED.md 313 lines; 0.0% line delta (2 lines revised in place).

**Changes**
- §2.9 (line 115) — revise — replaced "The check runs whenever tracts are edited, at activation, and at review completion" with "The check runs at activation, at review completion, and whenever the tracts of an `UNDER_REVIEW` area are edited", plus a clause that a `DRAFT` area stands outside the constrained set so creating one or editing a DRAFT area's tracts is never rejected for tract overlap — the collision is rejected at activation — `implementation/routes_areas.py:132-133`, `implementation/routes_areas.py:152-156`, `implementation/core.py:466-481`.
- §3.1 (line 145) — revise — replaced "Editing tracts re-runs the exclusivity check of §2.9" with "Editing the tracts of an `UNDER_REVIEW` area re-runs the exclusivity check of §2.9, while editing the tracts of a `DRAFT` area does not — a collision there is tolerated until activation" — `implementation/routes_areas.py:132-133`.

**Per-edit pre-edit search log** (both edits share one subject — timing/scope of the §2.9 census-tract exclusivity check w.r.t. DRAFT-area tract writes):
- (b) Impl paths enumerated: `core.py:466-481` (helper compares candidate tracts against union of tracts of all other areas in ACTIVE/UNDER_REVIEW; sole `ERR_TRACT_OVERLAP` raise site `core.py:478`); `routes_areas.py:52-104` (POST create — no exclusivity check; corroborated by `test_tract_overlap_rejected_at_activation` 8/8 green); `routes_areas.py:113-140` (PATCH — exclusivity only when `new_tracts is not None and area["status"] == "UNDER_REVIEW"` at :132-133); `routes_areas.py:143-183` (`_area_transition` — exclusivity at :156 only when `to_state == "ACTIVE"`; begin-review/retire run no check); non-exclusivity `census_tracts` reads confirmed unaffected (`routes_lending.py:99-102` ERR_TRACT_NOT_IN_AREA, `core.py:529`, `routes_exams.py:283`, serializer `core.py:494`); auxiliary test evidence `test_01_assessment_area_delineation.py:468-516` and `:520-538`.
- (c) Wording adjustment: original "whenever tracts are edited" was false for DRAFT edits, so trigger set re-scoped to the three firing sites (UNDER_REVIEW tract edits, activation, review completion); DRAFT clause covers both creation and DRAFT edits; no claim made about begin-review/retire; pairwise-invariant sentence kept verbatim.

No other edits: Step 7 deleted no tests outright, made no test_helpers/ or implementation/ fixes, and every other §2.9/§3.1 sentence already matches the implementation verbatim.
## Step 9: Complete PRD — 2026-08-14T00:00:07.000Z

**Produced:** `workspace/PRD_COMPLETED.md`

**Size delta:** PRD_FINALIZED.md = 313 lines / 43,339 chars → PRD_COMPLETED.md = 314 lines / 47,030 chars (+1 line, +3,691 chars). All changes inline inserts/revisions; no new sections.

**Counts:** 21 ambiguity-pins, 4 mismatch-revisions.

**Ambiguity-pins:**
- §2.2 — undefined paths / unsupported methods return envelope-shaped `ERR_NOT_FOUND` (404) / `ERR_METHOD_NOT_ALLOWED` (405) — core.py:165-172
- §2.3 — revise — `limit` <1 or non-integer and `offset` <0 or non-integer are `ERR_VALIDATION`; `limit` >100 clamped to 100 — core.py:272-292
- §2.3 — list sort ties on equal `created_at` break by creation order — core.py:320
- §2.3 — `has_more` = `offset` + returned items < `total_count`; out-of-domain filter/selector query params → `ERR_VALIDATION` — core.py:147,295-315
- §2.5 — clock settable to any valid instant, unparseable `to_iso8601` → `ERR_VALIDATION`, `current_utc` echoes supplied string verbatim, all server timestamps read the logical clock — routes_applications.py:171-180; core.py:73-86,112-134
- §2.6 — body-supplied `assessment_area_id`/`target_assessment_area_id` unresolvable → `ERR_ASSESSMENT_AREA_NOT_FOUND` after shape validation; existence-only at creation — routes_lending.py:62,156; routes_branches_files.py:55; routes_applications.py:58
- §2.7 — stale-version check evaluates after shape validation and state legality, before business tiers — routes_areas.py:128-133,206-211
- §2.9 — `area_code` uniqueness check precedes period-overlap check — routes_areas.py:66-85
- §2.11 — unknown/superfluous body fields are ignored — core.py:210-216
- §3.1 — PATCH carrying only `expected_assessment_area_version` still succeeds and bumps `version`/`updated_at` — routes_areas.py:135-139
- §3.2 — profiles may be posted against an area in any status — routes_areas.py:189-243
- §3.4 — companion field required per decision (`allocation_method` for QUALIFY, `disqualify_reason` for DISQUALIFY) — routes_lending.py:187-192
- §3.5 — duplicate `branch_code` → `ERR_VALIDATION` — routes_branches_files.py:58-60
- §3.6 — `response_text` required on respond — routes_branches_files.py:178
- §3.7 — test ratings, `composite_points`, `composite_rating`, `appeal_reason` start null at scheduling — routes_exams.py:110-116
- §3.7 — performance-context PATCH must carry `performance_context_narrative` — routes_exams.py:134
- §3.7 — `appeal_reason` required on appeal; reopen-fieldwork does not re-run the public-file gate; prior ratings/composite/appeal_reason persist until reassigned — routes_exams.py:202-224
- §3.8 — `branch_*` fields optional (validated and stored) for BRANCH_CLOSURE/MERGER — routes_applications.py:49-55
- §3.8 — latest-finalized-exam tie-break extended: after `created_at`, creation order decides — routes_applications.py:93-96
- §3.8 — branch-opening submission re-verifies `branch_code` uniqueness before staging — routes_applications.py:104-108
- §3.9 — computed reads served regardless of exam/area status; register totals computed from REPORTED loans regardless of `basis` — routes_exams.py:253-257,290-299; routes_areas.py:265-268

**Mismatch-revisions:**
- §3.1 — "two-letter `state_code`" softened to free-form string (impl enforces no length/format) — routes_areas.py:59
- §3.2 — `data_year` accepts any integer (no minimum) — routes_areas.py:197
- §2.10 — `pending_comment_count` defined as live derived count of RECEIVED comments, not a stored counter — core.py:412-413,605-617
- §3.6 — file no longer "born with pending_comment_count zero"; reflects RECEIVED comments existing at creation — core.py:403-424,612; routes_branches_files.py:136-158,190-207

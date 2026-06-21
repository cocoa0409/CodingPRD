# Worklog — task_0001_university_application

## Step 1: Task directory (pre-assigned) — 2026-05-27T00:00:00Z

Skipped index scan per orchestrator override. Using pre-assigned path: `tasks/task_0001_university_application/` with `workspace/` subdirectory already created.

## Step 2: Generate scaffold — 2026-05-27T00:51:00Z

Generated three scaffold artifacts at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0001_university_application/`:

**`SCAFFOLD.yaml`** (§1.0–§1.7)
- **9 entities**: Applicant, School, Application, Essay, RecommendationRequest, FinancialAidProfile, AidPackage, WaitlistEntry, SystemClock
- **5 state machines**: Applicant (DRAFT→LOCKED auto), Application (9-state branching with cascade-rich transitions), RecommendationRequest, AidPackage, WaitlistEntry (2-way branch from PENDING)
- **1 concurrency rule** (OCC): `admit-stale-application` on Application.version via POST /applications/{id}/admit, error ERR_STALE_VERSION (412)
- **4 calculations**: efc_calc (dual-variant FAFSA/CSS), composite_score_calc (dual-variant with_sat/test_optional, per-component rounding), net_cost_calc, yield_posture_calc (threshold)
- **17 validations** in priority order (auth → authz → existence → owner → state → ED-exclusivity → completeness → ED-binding → enrollment-uniqueness → aid-tuition → yield → word-count → FAFSA-assets → profile-locked → OCC → invalid-request)
- **41 endpoints** (including 5 single-resource GETs added to satisfy FK reverse-reachability, and test-driving `/_clock/set_current_utc` + `/_clock`)
- **17 errors**
- **5 roles**: Applicant (entity_backed), AdmissionsOfficer (opaque), FinancialAidOfficer (opaque), PlatformAdmin (opaque), Anonymous (opaque)

**Complexity profile**: multi_party_negotiation × quota_allocation, flat topology, branching state machines, peer_roles, immediate consistency; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (§1.8)
- **9 rules × 2 instances each = 18 instances total**
- All numeric asserts pre-computed by Python (e.g., EFC FAFSA 1056000 vs CSS 1306000 on identical income; composite 86.17 vs 79.50; yield boundary at ratio=0.85 exactly).

**`SCAFFOLD_CORNER_DESIGN.yaml`** (§1.9)
- **9 sections, 42 instances** (mix of full test_recipes and `excluded_because` stubs referencing §1.8 instances).

**Lint result**: clean — 41 endpoints, 9 entities, 18 §1.8 instances, 29 §1.9 active instances, 577 calls scanned. No forbidden concurrency vocabulary.

## Step 3: Copy INSTRUCTION.md — 2026-05-27T00:53:00Z

Copied `./INSTRUCTION.md` → `tasks/task_0001_university_application/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-27T01:00:00Z

**Output:** `workspace/PRD.md` (258 lines)

**Sections produced:**
- §1. Introduction (3 paragraphs covering goals, consistency model, document map)
- §2. Global Specifications, ten subsections: 2.1 Auth & RBAC (with §2.1.1 anonymous endpoints), 2.2 Response Structure, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Nested Resource Resolution, 2.6 Validation Priority & Ordering, 2.7 OCC, 2.8 Hierarchical Consistency & Cascades, 2.9 Cents-Based Money & Precision, 2.10 The Logical Clock
- §3. Business Logic, ten subsections by lifecycle/role: 3.1 Profile & Locking, 3.2 Schools & Yield Posture, 3.3 Drafting the Bundle, 3.4 EFC Calculation, 3.5 Submission & Composite Score, 3.6 Admissions Workflow, 3.7 Recommendation Loop, 3.8 Financial Aid & Tuition Cap, 3.9 Enroll/Decline/Withdraw, 3.10 Listings & Visibility
- §4. Endpoint table (4-column, 42 rows)
- §5. Error catalogue table (2-column, 17 error IDs)

**Coverage audit:** Field coverage PASS (47/47), Rule coverage PASS (17 validations, 1 OCC, 16 transitions, 4 calculations, 42 endpoints, 9 entities, 3 sibling-branch groups symmetric), Path purity PASS (0 paths/methods in §3). Zero scaffold rules omitted. SCAFFOLD_DIFFICULTY_DESIGN.yaml / SCAFFOLD_CORNER_DESIGN.yaml not consulted.

**Notable design choices:** §2.6 lists all 17 priorities in one ordered sentence; §2.7 OCC strictly stale-version (no race vocab); §2.8 enumerates 4 cascade families with admitted_count decrement scoped to ADMITTED-sourced cascades only; §3.4/§3.5 pin per-component rounding order; §3.2 inclusivity ("ratio of exactly 1.00 → OVER_TARGET"); §3.6 waitlist rank order (composite_score DESC, submitted_at ASC), ranks never renumbered.

## Step 5: Generate unit tests — 2026-05-27T01:30:00Z

**Helpers (test_helpers/):** __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py.

**Test files (test_suite/):**
- conftest.py
- test_01_applicant_and_crud.py (12 tests)
- test_02_financial_aid_and_calculations.py (9 tests)
- test_03_admissions_workflow.py (10 tests)
- test_04_submission_validations.py (10 tests)
- test_05_aid_packages_and_cascades.py (5 tests)
- test_06_occ_and_security.py (10 tests)
- test_07_difficulty_coverage_supplement.py (9 tests)

**Coverage:** 65 tests total — 37 Difficulty (queue A, every §1.8 instance ≥2 tests) + 28 Corner (queue B, 27/28 non-stub instances covered).

**PRD-first skip (1 instance):** `Corner/entities/applicant_email_uniqueness_returns_400` — PRD mandates email uniqueness but never names the error_id for collision; not uniquely derivable.

**Stage-2 audit:** clean — every test docstring carries exactly one `Design:` tag pointing to a real instance; verbatim PRD substrings ≥8 words; no skip/xfail; `SystemClock` correctly omits updated_at/version; identity threading via `make_applicant_headers(applicant["id"])`.

## Step 6: Generate implementation — 2026-05-27T01:30:00Z

**Location:** `workspace/implementation/`. Files: start.sh, requirements.txt (flask==3.0.3), app.py, db.py, errors.py, response.py, middleware.py, routes/{_helpers,applicants,schools,applications,essays,recommendations,financial_aid,waitlist,clock}.py, services/{common,calculations,state_machines}.py.

**Endpoints (42):** applicants(4) + schools(3) + applications(10) + essays(4) + recommendations(5) + financial_aid_profiles(4) + aid_packages(4) + waitlist(4) + clock(2). All per PRD §4.

**State machines:** submit/withdraw/begin_review/admit(OCC)/waitlist/deny/enroll(multi-school cascade)/decline/waitlist_promote/rec_submit/rec_waive/aid_finalize(residency tuition-cap).

**Calculations:** efc_calc (Decimal per-component round-half-up), composite_score_calc (per-component 2dp round then sum then final 2dp), net_cost_calc (integer cents), yield_posture_calc (round_half_up admitted×rate + enrolled / target, ≥0.85 ON_TARGET, ≥1.00 OVER_TARGET).

**Storage:** in-memory dicts only in `db.py`; no entity seeding at startup; clock singleton initialized to `1970-01-01T00:00:00.000Z`. Module reload on process restart wipes everything → per-test-server isolation clean.

**start.sh:** chmod +x, set -euo pipefail, pip install -q, `exec python3 app.py`. app.py reads $PORT (default 10000), binds 0.0.0.0, `use_reloader=False, threaded=True`.

**Design flags worth noting (potential PRD ambiguity zones for Step 7):**
- Validation order in admit: state → OCC (impl chose state-before-OCC per PRD §2.6).
- WaitlistEntry rank: impl uses monotonic `max(existing_rank)+1` per school (PRD prose interpretation).
- `/schools/{id}/waitlist` default filter: returns only PENDING when no `?status=` supplied.
- `POST /_clock/set_current_utc`: handler accepts both anonymous and authenticated PlatformAdmin.

## Step 7: Run tests + iterate — 2026-05-27T02:00:00Z

**Iterations run:** 3 (3 parallel 8-round sweeps total). Final sweep: all 8 rounds pass with 65/65.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` `setup_applicant_with_fap`: now passes `sat_total` through unconditionally (including explicit `None`); previously a `None` override silently fell back to the factory's `1300` default, masking the test-optional code path.
- `test_helpers/fixtures.py` `setup_ready_to_submit_application`: pop `name` out of `school_overrides` before passing to `create_school` to avoid `multiple values for keyword argument 'name'` TypeError.
- `test_helpers/factories.py` `create_school_payload`: default `deadline_iso` moved from `2026-12-01` to `2026-09-30` so the default submit-clock (`2026-09-15`) is before the deadline and the default review-clock (`2026-10-10`) is after it. Old default caused ~20 setup-step failures.

**Fixes applied to `test_suite/`:**
- `test_04_submission_validations.py::test_state_check_outranks_aid_exceeds_tuition`: removed `aid_after_decline["status"] == "REVOKED"` and `aid_unchanged["status"] == "REVOKED"` assertions — PRD §3.9 only cascades FINALIZED AidPackages, never DRAFT ones. Kept the `ERR_INVALID_STATE` precedence assertion (the test's actual purpose).
- `test_07_difficulty_coverage_supplement.py::test_state_outranks_aid_exceeds_after_deny_cascade_revoke`: setup re-wired from "draft aid → decline" (no cascade fires) to "finalize aid → decline" (cascade actually fires per §3.9). Docstring updated to quote PRD §3.9 (decline cascade) instead of §3.6 (deny cascade).

**Fixes applied to `implementation/`:**
- `services/state_machines.py` `rec_submit`: when a recommendation-submit triggers the §3.5 composite-score recompute on a `SUBMITTED`/`UNDER_REVIEW` Application, the Application's `version` is now bumped via `touch(app)`. Per PRD §2.8 every cascaded row's `version` increments exactly once on a server-acknowledged mutation; previous code recomputed `composite_score` without `touch`.

## Step 8: Finalize PRD — 2026-05-27T02:30:00Z

**Line counts:** PRD.md = 258 lines; PRD_FINALIZED.md = 258 lines (0.0% delta — inline revise within an existing paragraph).

**Changes applied (1):**
- §3.7 (Recommendation Submission Loop) — **revise** — extended the cascaded composite-recompute sentence to pin that this specific cascade refreshes `updated_at` and bumps `version` on the Application row (asymmetric with §3.5's other three triggers, which explicitly do not bump version). Impl evidence: `state_machines.py:367-368` calls `touch(app)` after `recompute_application_composite`; contrast `routes/essays.py:77,115`, `routes/applicants.py:131-134`, `state_machines.py:419-420` which recompute without `touch(app)`.

**Items rejected as pure fixture/test bugs (no PRD ambiguity):**
- All 3 `test_helpers/` fixes (None pass-through, duplicate kwarg, deadline default).
- Both `test_suite/` fixes — PRD §3.9 already pins that only FINALIZED AidPackages cascade to REVOKED; impl matched PRD, the tests were over-strict.

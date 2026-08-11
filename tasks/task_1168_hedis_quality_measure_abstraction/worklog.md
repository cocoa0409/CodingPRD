# Worklog — task_1168_hedis_quality_measure_abstraction

## Step 1: Create Task Directory — 2026-08-11T07:37:00.000Z

Task directory pre-assigned and already present: `tasks/task_1168_hedis_quality_measure_abstraction/` with `workspace/` subdirectory. Auto-index scan skipped per instructions; Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-11T09:09:30.000Z

All three scaffold artifacts are generated, verified, and lint-clean. Summary:

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_1168_hedis_quality_measure_abstraction/`)
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

## Counts
- Entities: 16 | State machines: 10 | Endpoints: 67 | Calculations: 7 | Validations: 29 (prioritized) | Errors: 33 | Roles: 7 (all `identity: opaque`; segregation-of-duties model) | OCC concurrency rules: 2
- Difficulty-design instances (queue A): 18 (9 rules × 2)
- Corner-design instances (queue B): 71 total — 63 active + 8 `excluded_because` stubs citing §1.8 instances
- Lint: `VERDICT: clean lint` (1051 recipe calls checked against §1.5; all 15 FKs reverse-reachable); all 216 `grounds:` references resolve; all 33 error codes are covered by at least one test; all formula-derived assert literals were executed in Python before being pinned (0.5/1.0 rate divergence, 0.3333 rounding, IRR 0.90 boundary → tier 0.25, burden 0.76 vs 0.75, draw indices {0,2}, 45/46-day gap math).

## Notable design decisions
- **Archetype**: compliance/audit + workflow orchestration; flat topology; cyclic state machines; segregation-of-duties role model (abstractor ≠ over-reader via `X-User-ID`, submitter ≠ certifier).
- **Harder-than-expert depth levers**: dual-variant rates (`SAMPLE_ONLY` vs `ADMIN_SUPPLEMENTED`) and supplemental matching (`EXACT` vs `TOLERANT`) on different entity domains; two transitive cascades with explicit B→C→D(→E) links (over-read DISAGREE → remediation → remediation_count → fraction override → sibling flagging; batch accept → entry compliance → gap auto-close → provider counter); opposite interval semantics (half-open auditor windows allow adjacency; closed enrollment segments treat touching as overlap); two OCC rules (spec-load on season version, compute-rate on run version).
- **Determinism pins**: logical-clock endpoint with the mandated `2026-05-01T00:00:00Z` startup default (deadline tests use a past deadline + unset clock so the auto-close side effect never masks the deadline error); systematic sample draw with floor-based indices over `member_ref ASC` (no randomness); over-read selector ordered by `submitted_at ASC, created_at ASC`; all list endpoints pinned to `created_at ASC` mint order.
- **Fixture economy**: `sample_size_floor` is a spec input (default 411, fixtures use 1–10) so hybrid chains stay small while the floor boundary is still tested at exactly floor vs floor−1.
- **Consistency fixes made during self-review**: removed unreachable `ERR_DUPLICATE_OVERREAD` (a reviewed abstraction always leaves SUBMITTED, so the state guard fires first); dropped the compute-time hybrid floor recheck (drawn == floor always, so any valid exclusion would falsely fail compute — floor is enforced at draw); corrected the certify→season auto-close cascade condition (counter vs total runs of the season).

## Step 3: Copy Shared Files — 2026-08-11T09:10:10.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1168_hedis_quality_measure_abstraction/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T09:32:00.000Z

PRD generated and verified on disk at `/home/ubuntu/github/CodingPRD/tasks/task_1168_hedis_quality_measure_abstraction/workspace/PRD.md` (343 lines, 8,409 words). The withheld difficulty/corner design files were never opened.

**Section list**
- §1. Introduction (3 paragraphs, business-context angle)
- §2. Global Specifications — 2.1 RBAC (all 7 roles named, opaque identity translated per role), 2.2 API Response Structure (byte-identical to the fixed verbatim block), 2.3 Pagination & Result Ordering, 2.4 Resource Identity & Common Fields (incl. the three `common_fields: false` entities), 2.5 Logical Clock & Season Deadlines, 2.6 OCC (both rules), 2.7 Precision/Rates/Rounding, 2.8 Segregation of Duties & Row Ownership, 2.9 Validation Pipeline & Priority Order (all 12 bands), 2.10 Reverse Reachability
- §3. Business Logic — 3.1 Season/Spec Management, 3.2 Member/Enrollment/Provider Reference Data, 3.3 Runs & Eligible Population Identification, 3.4 Hybrid Sampling & Chart Chase, 3.5 Abstraction/Over-Read/IRR, 3.6 Supplemental Data, 3.7 Rate Determination/Gap Lists/Outreach, 3.8 Submission/Audit/Certification
- §4. Endpoint Definitions (4-column table, 67 rows — all scaffold endpoints)
- §5. Error Code Catalogue (2-column table, 33 rows — all scaffold errors)

**Hard-contract verification (all PASS, programmatically checked)**
- Contract 1 field coverage: 115 required identifiers (all entity fields + request-body/query/path params), 115 present in backticks, 0 missing
- Contract 2 rule coverage: all 10 state machines with every transition's preconditions/side-effects; all 7 calculations (population identification window math, systematic draw floor indexing, both rate variants, both matching variants incl. normalization, IRR tiering 0.95/0.90/0.10/0.25/1.0 with remediation-override at 2, per-line-then-sum gap burden); both OCC rules with occ fields + `ERR_STALE_VERSION`/412; validation priority ordering stated explicitly (incl. submit's NOT_SUBMITTABLE → SEASON_NOT_OPEN → DEADLINE_PASSED order and accept's source-before-denominator order); all cascades (certify counter → season auto-close, DISAGREE 3-link, batch-accept 3-link, gap regeneration); 32/32 rule spot-checks OK; zero pseudocode operators and zero fuzzy words in prose
- Contract 3 §3 path purity: 597 backticked tokens scanned, 0 path tokens, 0 bare HTTP methods, 0 method+path combos

All 16 entities, 10 state machines, 7 calculations, 25 validation rules, 67 endpoints, 33 errors, and 7 roles are covered in prose.

## Step 5: Generate Unit Tests — 2026-08-11T10:05:00.000Z

Generation complete and verified. Summary:

## Deliverables

**test_helpers/ (9 files)** — all under `/home/ubuntu/github/CodingPRD/tasks/task_1168_hedis_quality_measure_abstraction/test_helpers/`:
- `types.py` — 16 entity TypedDicts + all status/role enums; the 3 light event rows (MemberEnrollmentSegment, OverReadReview, SupplementalRecord) correctly omit `updated_at`/`version`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (all 50+ PRD endpoints)
- `api_errors.py` — all 33 error IDs + HTTP status map, registered with the framework via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` plus `assert_light_row` (asserts absence of version/updated_at)
- `factories.py`, `constants.py` (IRR tiers 0.95/0.90, fractions 0.10/0.25/1.0, rate decimals, spec defaults), `test_users.py` (7 opaque roles, shared constants + per-id builders)
- `fixtures.py` — composite tiers: season/spec/member builders, `setup_populated_run` / `setup_rate_computed_run` / `setup_submitted_run`, `setup_hybrid_sample`, `setup_hybrid_with_submitted_abstractions`, `setup_finalized_sample`, `overread_all_flagged` (selector top-up sweep), `run_hybrid_pipeline`, batch screen/accept chains, engagement/review builders
- `__init__.py` — barrel export (framework + PRD-specific)

**test_suite/ (10 files)** — `conftest.py` + 9 numbered test files: reference data, spec lifecycle/OCC, population & sampling, chart chases, abstraction/over-read/IRR, supplemental data, rates & gap list, submission/audit/certification, RBAC.

## Test counts
- **Queue A (Difficulty): 36 tests** — 18/18 instances covered, exactly 2 tests each
- **Queue B (Corner): 63 tests** — 63/63 non-stub instances covered, 1 test each
- **Total: 99 tests**, all collected cleanly by `pytest --collect-only`; every module imports; pyflakes clean

## Skipped instances
None. All 18 difficulty instances and all 63 non-stub corner instances passed the PRD-first two-condition filter and were translated. The 8 `excluded_because:` stubs in the errors section were not translated (by design); all 8 `difficulty_instance` cross-references resolve to real §1.8 instances.

## Adaptations (recipe repairs / derivability relaxations — documented, no assertions weakened)
1. **dual_variant_calc/hybrid_rate_sample_only_vs_admin_supplemented** — the recipe finalizes each sample with one flagged SUBMITTED abstraction still un-reviewed, which the PRD's own selector top-up + `ERR_OVERREADS_OUTSTANDING` gate would block. Repaired by over-reading (AGREE) every selector-flagged abstraction before finalize (fixture `overread_all_flagged`); all asserted values (irr 1.0/PASSED, rates 0.5 vs 1.0) are unchanged.
2. **combinatorial_formula/provider_gap_burden_per_line_rounding** — the recipe's age-0-100-ANY specs would admit all 6 members into both runs (denominator 6, not the asserted 3). Repaired by setting spec GPA `gender_requirement: "M"` and GPB `"F"` (a PRD-declared eligibility filter), yielding the asserted 3-gaps-per-run state; asserted burden 0.76 / ogc 6 / lines 2 unchanged.
3. Three instances asserted absolute initial `version == 1`, which the PRD never pins ("increments by exactly 1 on every mutation" only) — a faithful implementer could start at 0. The literal was relaxed while keeping the instance's claim at full strength: `season_creation_defaults_and_system_fields` asserts version presence/type; `occ_spec_load_success_increments_season_version` asserts `v_after == v_before + 1` (the pinned rule); `occ_stale_compute_rate_returns_412` drops the incidental `v_create == 1` line and keeps the 412 assertion.

## Tag verification result
Programmatic AST audit (run before removal of the scratch audit script): **PASS** — 99/99 tests carry exactly one `Design:` tag as the last docstring line; 36 tags resolve to real §1.8 `Difficulty/<rule_id>/<name>` instances, 63 to real §1.9 `Corner/<section>/<name>` instances; 0 tags point at stubs; every `PRD §x.y: "..."` citation in every docstring is a verbatim whitespace-normalized substring of `workspace/PRD.md`; no `pytest.mark.skip`/`skipif`/`xfail` anywhere.

## Step 6: Generate Implementation — 2026-08-11T10:05:00.000Z

Cold boot verified: empty store, default logical clock at 2026-05-01T00:00:00Z, correct envelope on both success and error paths. The implementation is complete.

## Summary

**File list** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1168_hedis_quality_measure_abstraction/workspace/implementation/`):
- `start.sh` (executable, guarded pip install, `exec python3 app.py`, reads `$PORT`, binds `0.0.0.0`, foreground)
- `requirements.txt` (flask)
- `app.py` — entry point, blueprint registration, error handlers (static folder disabled so the route surface is exactly the scaffold's)
- `db.py` — in-memory `Store` (16 entity dicts), logical clock defaulting to 2026-05-01T00:00:00Z, ISO8601 parse/format (3 fractional digits), month subtraction
- `errors.py` — `ApiError` + all 33 scaffold error IDs
- `response.py` — `meta`/`response_type`/`data` envelope, `error_id`/`message` error body, `limit`/`offset`/`total_count`/`has_more` pagination (defaults 10/0, clamped 1..100)
- `middleware.py` — X-User-ID / X-User-Role header auth, role gating, body-shape/enum/int validation
- `serializers.py` — per-entity views; light types (MemberEnrollmentSegment, OverReadReview, SupplementalRecord) expose only `id` + `created_at`
- `services/core.py` — eligibility interval-merge, systematic draw, rate determination (SAMPLE_ONLY vs ADMIN_SUPPLEMENTED), over-read selector top-up, gap regeneration, provider reconciliation, certification cascades
- `services/supplemental.py` — EXACT/TOLERANT matching, measurement-year window check, duplicate detection (in-batch processing order + cross-batch ACCEPTED)
- `routes/seasons.py`, `routes/members.py`, `routes/runs.py`, `routes/abstractions.py`, `routes/supplemental.py`, `routes/gaps_audit.py`

**Route count**: 67/67 — Flask route table matches SCAFFOLD.yaml's endpoint list exactly (method + path, zero missing, zero extra). Note: the scaffold's §1.5 header comment says "66 endpoints" but the actual table contains 67; 67 is what's registered.

**Boot verification**: fresh-process cold boot passes — server listens on `$PORT`, binds 0.0.0.0, responds within ~2s, store starts empty (`total_count: 0`), logical clock reads exactly `2026-05-01T00:00:00.000Z`, and all `py_compile` checks pass.

**Functional verification** (three E2E scripts against the live server, all passing): administrative pipeline (season → spec OCC → members/enrollment → run → population → rate → gaps → submit → audit PASS → certify → season auto-close), hybrid pipeline (systematic draw with floor/step math, chase lifecycle incl. rechase rounds and mark-excluded, abstraction DRAFT/SUBMITTED/REMEDIATION cycles with author-ownership, over-read SoD, IRR tiering incl. remediation-2 hard override to fraction 1.0, finalize gates in priority order, hybrid rate math), supplemental (TOLERANT normalization with zero-stripping, window/duplicate dispositions, unapproved-source-before-denominator ordering, auto-close gap cascade), and deadline semantics (submit at exact deadline accepted, clock-driven season auto-close, ERR_SEASON_NOT_OPEN after closure, audit FAIL auto-finding, re-review cycle, certification unblock after finding resolution).

**Notable design decisions**:
- OCC field names `expected_season_version` / `expected_measure_run_version` taken verbatim from `concurrency_rules`; the OCC check runs before the state-machine check on compute-rate per §2.9 (stale version masks state violations).
- OverReadReview rows carry a hidden `resubmission_count` (not serialized) to support the "latest review per abstraction round" IRR rule and the retract-while-reviewed guard.
- Selector top-up never unflags; flag mutation updates `updated_at` but not `version` (scaffold increments `version` only on declared transitions).
- `batch.record_count` increment on record create updates `updated_at` only (scaffold declares no version bump for that side effect).
- Flask's built-in `/static` route was disabled via `static_folder=None` so the registered surface is exactly the 67 scaffold endpoints.

**Orchestrator route-parity verification (pre-sweep)**: live Flask `url_map` dump vs SCAFFOLD.yaml endpoint table — 67 scaffold, 67 impl, 0 missing, 0 extra.

## Step 7: Run Tests and Iterate — 2026-08-11T10:20:00.000Z

## Summary

- **Iterations run:** 2 (iteration 1: 1 distinct failing test, failing in all 8/8 rounds; iteration 2: clean 8× 99/99).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1168_hedis_quality_measure_abstraction/test_helpers/fixtures.py` — `run_hybrid_pipeline`: stored the accepted-batch response (`_created, _rows, batch = setup_accepted_batch(...)`) instead of the stale create-response batch. Why: the only consumer reading batch state off the pipeline result (`test_07::test_sample_only_counts_only_abstraction_hits`, asserting `accepted_record_count == 1` per PRD §3.6 "The batch's `accepted_record_count` is set to the number of accepted records") was reading the pre-screen snapshot, where `accepted_record_count` is 0 by definition (PRD §3.6: a new batch starts "with `record_count` and `accepted_record_count` both zero"). The assertion was PRD-faithful; the fixture exposed the wrong snapshot. The accepted view still carries `id`, so the fixture's other callers are unaffected.

- **Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful on this path.

- **Failure detail (iteration 1, for the record):** `TestHybridRateVariants::test_sample_only_counts_only_abstraction_hits` failed with `AssertionError: the M001 record is accepted in the SAMPLE_ONLY run too — assert 0 == 1`, i.e., `scenario["batch"]["accepted_record_count"]` read 0 from the create-response object. Diagnosed via STEP 1 (PRD verbatim-covers the rule; uniquely derivable) → STEP 2 (fixture bug in `test_helpers`, not an implementation bug) → fixed fixture → iteration 2 sweep clean across all 8 parallel rounds.

## Step 8: Finalize PRD — 2026-08-11T10:35:00.000Z

Done. `PRD_FINALIZED.md` exists at `/home/ubuntu/github/CodingPRD/tasks/task_1168_hedis_quality_measure_abstraction/workspace/PRD_FINALIZED.md` and is a **byte-identical copy of PRD.md** — the sole `<step_7_diff>` item is a pure fixture bug with no PRD silence or mismatch to patch.

**Line counts / %-delta:** PRD.md = 343 lines, PRD_FINALIZED.md = 343 lines, delta 0 (0.0%).

**Changes:** none.

**Analysis of the sole step_7_diff item** (fixture fix in `test_helpers/fixtures.py:run_hybrid_pipeline`, which now stores the accept-response batch from `setup_accepted_batch` instead of the stale create-response batch):

- (a) **Subject identified:** the value of a supplemental batch's `accepted_record_count` at each lifecycle point, and which batch object each endpoint response carries.
- (b) **Impl paths enumerated and read:**
  - `implementation/routes/supplemental.py:22-42` — `create_batch` mints the batch with `record_count: 0`, `accepted_record_count: 0`, status `RECEIVED`, and returns it (201). Matches PRD §3.6 ("the batch starts in `RECEIVED` status with `record_count` and `accepted_record_count` both zero") and §4 ("Creating a new resource returns HTTP 201 with the created resource in `data`").
  - `implementation/services/supplemental.py:37-84` (`screen_batch`) + `routes/supplemental.py:52-69` (`screen`) — screening sets `batch["accepted_record_count"] = accepted_count` and returns the updated batch. Matches PRD §3.6 ("The batch's `accepted_record_count` is set to the number of accepted records").
  - `implementation/routes/supplemental.py:72-135` (`accept`) — does not touch `accepted_record_count`; returns the updated batch via `success_object(batch_view(b))`. Matches PRD §2.2 ("operations that create or modify a resource will return the created or updated resource object in the data field").
  - `implementation/serializers.py:184-196` — `batch_view` exposes `accepted_record_count` on every batch response, so the create-response snapshot legitimately reads 0 and the accept-response snapshot reads the screened count.
  - Consumers of the fixture: `grep` shows only `test_07_rates_and_gap_list.py` (the `_dual_variant_scenario` at lines 65-66, consumed by `test_sample_only_counts_only_abstraction_hits` asserting `accepted_record_count == 1`).
- (c) **Wording adjustment:** none possible or needed — every behavior the failing assertion touched is already pinned verbatim in PRD §3.6 (initial zero counters; screening sets the accepted count) and §2.2/§4 (each response carries the current resource object). The old fixture was simply holding the pre-screen snapshot; that is a test-helper defect about which client-side snapshot to keep, not API behavior the PRD could pin. Step 7 itself recorded "Fixes applied to `implementation/`: none — the implementation was already PRD-faithful on this path," and iteration 2 was clean 8× 99/99 with no test deletions.

Per the task's explicit provision, the subagent stated plainly: **no PRD edits were warranted; PRD_FINALIZED.md is intentionally byte-identical to PRD.md** rather than containing invented edits.

## Step 9: Complete PRD — 2026-08-11T10:55:00.000Z

## Summary

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1168_hedis_quality_measure_abstraction/workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md` (343 lines each — every change is an in-place paragraph revision; no new sections).

**Size:** PRD_FINALIZED.md 343 lines / 63,277 chars → PRD_COMPLETED.md 343 lines / 66,506 chars. Char delta: **+3,229**. Diff: 20 hunks, all single-line in-place replacements.

**Counts:** 18 ambiguity-pins, 5 mismatch-revisions (23 distinct changes across 20 hunks).

**Changes:**

- §2.3 — insert — ambiguity — out-of-range/unparsable `limit`/`offset` are clamped/defaulted, never rejected; `has_more` = `offset + returned_items < total_count` — implementation/response.py:61-83, 35
- §2.4 — revise — mismatch — blanket "version increments on every mutation" rule gains three exemptions: selector flagging (updated_at only), numerator-counter/`sample_compliant` recomputation (no timestamp/version), batch `record_count` intake bump (updated_at only) — implementation/services/core.py:114-131, 145-177; implementation/routes/supplemental.py:197-198
- §2.9 band 2/3 — revise — mismatch — role authorization (403) is evaluated **before** body-shape validation (400) on every endpoint; bands swapped — implementation/middleware.py:21-26 and every route's `require_roles`-first ordering
- §2.9 band 6 — revise — mismatch — abstraction row-ownership checks (403) are evaluated immediately **after** the from-state check, not at the role band — implementation/routes/abstractions.py:87-90, 101-104, 132-135
- §3.1 — insert — ambiguity — all four season fields (incl. informational `admin_data_cutoff`) are required; `approved_supplemental_sources` must be a list with every element in the four-value set — implementation/routes/seasons.py:43-54
- §3.1 — insert — ambiguity — spec load resolves the season and applies `expected_season_version` before validating remaining fields; non-integer expected version → `ERR_INVALID_REQUEST` — implementation/routes/seasons.py:140-146
- §3.3 — insert — ambiguity — enrollment-window month arithmetic clamps day-of-month to the target month's last day — implementation/db.py:72-87
- §3.3 — insert — ambiguity — closed enrollment intervals that merely touch (one ends the day before the next begins) merge into one — implementation/services/core.py:336-347
- §3.3 — insert — ambiguity — excluding an already-excluded population entry → `ERR_INVALID_STATE` — implementation/routes/runs.py:323-324
- §3.5 — insert — ambiguity — the over-read selector never clears a flag once set; flagging moves `updated_at` without incrementing `version` — implementation/services/core.py:114-131
- §3.5 — insert — ambiguity — `final_result` supplied with `AGREE` is validated but not recorded (stays null unless `DISAGREE`) — implementation/routes/abstractions.py:188-189, 205
- §3.5 — insert — ambiguity — finalization's outstanding-over-read gate requires a review of the abstraction's **current** submission round — implementation/routes/runs.py:436-438
- §3.5 — revise — ambiguity — `sample_compliant` is recomputed two-way (set or cleared) on every counter pass, not a one-way flip — implementation/services/core.py:168-170
- §3.6 — insert — ambiguity — batch-acceptance denominator check compares under the batch's `matching_policy_used` (exact vs normalized) — implementation/routes/supplemental.py:93-101
- §3.6 — insert — ambiguity — the acceptance run-state gate (`SUBMITTED`/`CERTIFIED`/`CERTIFICATION_FAILED`) is evaluated after the source-approval and per-record denominator checks — implementation/routes/supplemental.py:104-106
- §3.6 — insert — ambiguity — the acceptance cascade matches population entries under the same `matching_policy_used` — implementation/routes/supplemental.py:113-124
- §3.7 — insert — ambiguity — non-integer `expected_measure_run_version` → `ERR_INVALID_REQUEST` — implementation/routes/runs.py:111-112
- §3.7 — revise — mismatch — only the numerator **counters** are recomputed incrementally on evidence events; `admin_rate`/`hybrid_rate`/`final_rate` change only at compute-rate — implementation/services/core.py:145-190; implementation/routes/runs.py:126-127
- §3.7 — insert — ambiguity — gap-minting compliance rule pinned: ADMIN runs use `admin_compliant`; HYBRID non-sampled entries use `admin_compliant`; HYBRID sampled entries use `sample_compliant` (SAMPLE_ONLY) or `sample_compliant` OR `admin_compliant` (ADMIN_SUPPLEMENTED) — implementation/services/core.py:197-206
- §3.7 — insert — ambiguity — gap-burden with unresolvable `season_id` → `ERR_NOT_FOUND` — implementation/routes/members.py:150-152
- §3.8 — insert — ambiguity — findings may be filed on an engagement in any status (no engagement-state precondition) — implementation/routes/gaps_audit.py:177-196
- §4 intro — insert — ambiguity — undefined paths and undefined methods on defined paths return `ERR_NOT_FOUND` (404) — implementation/app.py:36-42
- §4 endpoint table — revise — mismatch — `GET /hedis/seasons/{id}/audit-engagements` roles restricted from all seven to QualityAdmin, QualityAnalyst, Auditor, QualityDirector (matching §2.1 and impl) — implementation/routes/seasons.py:117


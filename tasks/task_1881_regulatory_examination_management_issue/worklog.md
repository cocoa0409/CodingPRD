# Worklog — task_1881_regulatory_examination_management_issue

## Step 1: Create Task Directory — 2026-08-14T22:10:00.000Z

Task directory `tasks/task_1881_regulatory_examination_management_issue/` and `workspace/` pre-created by the invoking pipeline (verified present and empty by orchestrator; index scan skipped per instructions).

## Step 2: Generate Scaffold — 2026-08-14T22:33:00.000Z

Lint is clean and all three files are written. Summary:

## Task 1881 Scaffold — Regulatory Examination Management & Issue Remediation

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1881_regulatory_examination_management_issue/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1881_regulatory_examination_management_issue/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1881_regulatory_examination_management_issue/SCAFFOLD_CORNER_DESIGN.yaml`

**Counts:**
- Entities: **15** (RegulatorAgency, Examination, FirstDayLetterItem, DocumentSubmission, ExaminerMeeting, InformalFinding, Issue, RemediationPlan, RemediationMilestone, ValidationEvidence, ClosureRequest, BoardReport, CommitmentLogEntry, BankOfficer, ComplianceReviewer)
- State machines: **10** (Examination, FirstDayLetterItem, DocumentSubmission, ExaminerMeeting, Issue, RemediationPlan, RemediationMilestone, ValidationEvidence, ClosureRequest, BoardReport)
- Calculations: **6** (repeat_finding_risk [dual-variant], first_day_letter_due_date, overdue_item_count, exam_posture, milestone_sequence_gap_allocation, repeat_finding_detection)
- Validations: **14** (priorities 1–14, covering auth, state, segregation-of-duties, certification, OCC, temporal-overlap, uniqueness, referential, posture gating, shape)
- Endpoints: **76** (including 6 reverse-reachability filtered lists, 1 risk-history computed read, 1 `/_clock/set_current_utc` test-driving endpoint)
- Errors: **19** (including ERR_SEGREGATION_OF_DUTIES, ERR_CERTIFICATION_INSUFFICIENT, ERR_EXAM_POSTURE_FROZEN, ERR_STALE_VERSION, ERR_COMMITMENT_OUTSTANDING, ERR_OPEN_ISSUES_REMAIN, ERR_ISSUE_NOT_CLOSABLE, ERR_NO_ACTIVE_PLAN)
- Roles: **5** (PlatformAdmin [opaque], RegulatoryAffairsManager [opaque], RemediationOwner [entity_backed:BankOfficer], ComplianceReviewer [entity_backed:ComplianceReviewer], BoardReporter [opaque]) — segregation_of_duties role model
- §1.8 difficulty instances: **18** (exactly 2 per rule across all 9 rules)
- §1.9 corner instances: **42** (37 active + 5 excluded-as-covered stubs)

**Notable design decisions (harder-than-expert calibration):**
- **Primary archetype: compliance_audit + workflow_orchestration**, layered with optimistic concurrency, cascading side effects, dual-variant calculation, derived-field reconciliation. Segregation-of-duties role model is rare and high-priority per the skill's diversity guidance.
- **Two cyclic state machines**: Issue (`VALIDATION_SUBMITTED → IN_PROGRESS` on closure rejection, with `request_round` incrementing each loop) and RemediationPlan (`DRAFT → SUBMITTED → REJECTED → DRAFT` revision loop plus `ACTIVE → SUPERSEDED` fan-out branch). Satisfies Rule 3 with two distinct non-linear shapes on different entities.
- **Three OCC-guarded write endpoints** (issue create on exam, milestone create on plan, closure approve on issue) — maximal concurrency surface, all resolved via `expected_<parent>_version` per §1.2.1.
- **Two temporal-overlap rules with different interval semantics** (Rule 8): half-open `[s, e)` interval on agency-scoped Examination scheduling (adjacency allowed), vs. point-collision at UTC-calendar-date grain on ExaminerMeeting (FINALIZED-only conflicts).
- **Dual-variant risk scoring** with two structurally different variants (forward_looking excludes CLOSED + adds overdue surcharge; historical includes CLOSED + omits surcharge) plus a separate dual-variant-style boundary in first-day-letter business-day computation (day-1 vs day-0 vs naive-calendar interpretations are falsifiably distinct).
- **Posture-driven gating** on Examination (NORMAL/RESTRICTED/FROZEN) with FROZEN=3 overdue items as an inclusive boundary (Rule 6); posture gates first-day-item creation and document acceptance (Rule 7).
- **Two transitive cascades with different triggers** (Rule 4): milestone-complete chain (depth 3: milestone → plan → issue → exam auto-transition) vs. document-accept chain (depth 3: accept → item SUBMITTED → overdue_item_count → posture relaxation).
- **Compensating invariants on two distinct conserved quantities** (Rule 9): total FirstDayLetterItem count under waive/submit compensation, and max(plan_version) monotonicity under revise/supersede cycles.
- **Validation priority conflicts across different error-category pairs** (Rule 5): auth-vs-state and business_temporal-vs-business_constraint.
- **Certification gates + segregation of duties** as separate business_safety validations: MRIA closures require L3 reviewer; closure reviewer cannot equal the active plan's owner_user_id.
- **Logical clock endpoint with mandatory default** `2026-08-01T00:00:00Z`, drives all clock-based OVERDUE transitions deterministically.

**Lint verdict:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

## Step 3: Copy Shared Files — 2026-08-14T22:34:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1881_regulatory_examination_management_issue/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T22:47:00.000Z

All verification passes complete. The PRD is generated and ships clean.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1881_regulatory_examination_management_issue/workspace/PRD.md` — 303 lines.

**Section list**:
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications — 2.1 RBAC & identity translation (5 roles), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning (incl. the `CommitmentLogEntry` no-`version`/no-`updated_at` exception), 2.5 The Logical Clock, 2.6 Date Arithmetic & Numeric Precision, 2.7 OCC (all 3 rules with paths, occ fields, `ERR_STALE_VERSION`/412), 2.8 Nested Retrieval & Referential Integrity, 2.9 Request Evaluation Pipeline (all 14 validation priorities in explicit order with scopes and a worked ordering example), 2.10 Segregation of Duties & Certification Gates
- §3 Business Logic — 9 subsections organized on the examination timeline (3.1 provisioning cast → 3.2 scheduling & first-day letter → 3.3 submissions & QC → 3.4 meetings & informal findings → 3.5 issues, repeat detection, risk scoring → 3.6 plans & milestones → 3.7 evidence & closure adjudication → 3.8 overdue escalation, posture, commitments → 3.9 board reporting & portfolio queries)
- §4 Endpoint Definitions — 4-column table, all 76 scaffold endpoints present
- §5 Error Code Catalogue — 2-column table, all 19 error IDs

**Entity coverage**: all 15 entities (RegulatorAgency, Examination, FirstDayLetterItem, DocumentSubmission, ExaminerMeeting, InformalFinding, Issue, RemediationPlan, RemediationMilestone, ValidationEvidence, ClosureRequest, BoardReport, CommitmentLogEntry, BankOfficer, ComplianceReviewer) fully narrated with every field name backticked; all 11 state machines, 6 calculations (both risk-score variants, business-day due date, overdue count, posture thresholds, sequence allocation, repeat-finding normalization + tie-breaks), and all endpoint side-effects expressed in prose.

**Hard Contract reports**:
- Field coverage: entities 81/81, request_body 60/60, query_params 19/19 — **PASS** (pass 1 caught `remediation_plan_id` missing; fixed, pass 2 clean)
- Rule coverage: 35 transitions, 6 calculations, 14 ordered validations, 3 OCC rules, all constants (2,500/5,000/7,500/10,000 bp, 25 bp/day surcharge capped at 5,000, 100,000 bp cap, 1–730 escalation days, 10 business days) — **PASS**
- §3 path purity: 425 backtick tokens scanned, 0 paths, 0 bare HTTP methods — **PASS**

**Zero-Silence Rule extra-prose spots**: (1) `ERR_ALREADY_TERMINAL` has no validation-table row, so it was homed inside the §2.9 step-4 state-check prose with its exact terminal-state enumeration; (2) the business-day due-date algorithm was rendered as pure prose plus a worked Monday→second-Friday anchor; (3) `SUPERSEDED` plan milestone freezing, milestone-creation ordering tie-breaks, and repeat-detection normalization tie-breaks all required narrative reconstruction from symbolic scaffold notes; (4) inactive officer/reviewer/agency constraints carry no scaffold-bound error ID, so they are stated as rules without inventing codes; (5) the milestone-duplicate error appears as `ERR_DUPLICATE_KEY` per the authoritative validations table/catalog (the calculation's internal `ERR_DUPLICATE_SEQUENCE` note has no catalog entry and was not surfaced); (6) the clock's fixed startup instant `2026-08-01T00:00:00Z` and no-wall-clock-fallback rule required explicit §2.5 prose since no entity field carries it.

## Step 5: Generate Unit Tests — 2026-08-14T23:30:00.000Z

Generation complete and fully audited. Summary:

## Output

**`test_helpers/`** (9 files): `types.py` (11 status/enum classes + 16 TypedDicts; `CommitmentLogEntry` correctly omits `updated_at`/`version` per PRD §2.4), `api_client.py` (55 methods, one per PRD §4 endpoint), `api_errors.py` (all 19 error ids + HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py` (auto-unique codes/emails), `constants.py` (risk bp tables, FROZEN threshold 3, default logical clock), `test_users.py` (opaque-role constants + `make_remediation_owner_headers`/`make_compliance_reviewer_headers` builders for the two entity-backed roles), `fixtures.py` (tiered composites up to full CLOSED-exam lifecycle, with OCC version re-fetching and early-clock parking for multi-item past-due rosters), `__init__.py` barrel.

**`test_suite/`**: `conftest.py` + 8 test files — 73 test functions, 74 collected items.

## Test counts by queue
- **Queue A (Difficulty): 36 tests** across all 18 instances (each ≥2; one parametrized, yielding 37 items at run time).
- **Queue B (Corner): 37 tests** — one per non-stub instance.

## Instances skipped / adjudicated (gaps left as gaps)
- **5 corner stubs** not translated (per spec); all `difficulty_instance` cross-references verified to resolve.
- **`document_accept_blocked_when_exam_frozen`** (queue A): the instance's expected `ERR_EXAM_POSTURE_FROZEN` contradicts PRD §3.3, which uniquely derives `ERR_INVALID_STATE` for any accept-precondition shortfall (§2.9 step 13 scopes the posture-gate error to creation endpoints only). Scenario preserved; assertion follows the PRD.
- **`remediation_plan_revision_loop_and_supersede`** (queue A): supersede outcome not asserted — PRD's approve-exclusivity rule ("no other plan for the same issue may currently be `ACTIVE`") makes the supersede trigger unreachable, so two PRD-only readers diverge. Both tests cover the PRD-derivable revision cycle (REJECTED→DRAFT; cycle back to ACTIVE).
- **`business_temporal_overlap_beats_business_constraint_duplicate`**: the "duplicate" leg assumed `exam_cycle_code` uniqueness, which PRD §2.9 #11 does not declare; both tests assert the uniquely-derivable `ERR_EXAM_SCHEDULE_OVERLAP` in two geometries.

Recipe corrections applied as fixture plumbing (asserted outcomes unchanged): milestone-before-submit ordering (several recipes submit plans with zero milestones, violating PRD §3.6), a trigger that addressed an exam id as a first-day-item id (would 404), and early clock-parking before multi-item roster creation (default clock 2026-08-01 would flip posture RESTRICTED after the first past-due item and block subsequent items).

## Stage 2 tag audit
All green: every test function's docstring ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` line resolving to a real instance; zero shortfalls in either queue; every ≥8-word docstring quotation greps verbatim against `PRD.md`; no skip/skipif/xfail markers; no scaffold references in generated code; `pyflakes` clean; `pytest --collect-only` collects 74 items with no import errors.

## Step 6: Generate Implementation — 2026-08-14T23:18:00.000Z

Implementation complete and smoke-verified. Summary:

## Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1881_regulatory_examination_management_issue/workspace/implementation/`)

- `start.sh` — guarded launcher (`if ! python3 -c "import flask"` then pip install; `exec python3 app.py`), executable
- `requirements.txt` — flask>=2.2,<4
- `app.py` — Flask app factory, blueprint registration, envelope-shaped 404/405/400/500 handlers, `0.0.0.0:$PORT` (default 10000)
- `db.py` — empty-at-boot in-memory store, logical clock (fixed default `2026-08-01T00:00:00Z`, never wall clock), request-scoped `touch()` that bumps `version`/`updated_at` exactly once per entity per cascade
- `errors.py` — all 19 error IDs from the catalog with their HTTP statuses
- `response.py` — `meta{api_request_id, api_request_timestamp}` + `response_type` + `data` envelope; list responses add `limit/offset/total_count/has_more` to meta
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401), per-endpoint role gate (403), entity-backed ComplianceReviewer active check
- `util.py` — ISO8601 parse (Z/offset/date-only), 3-fractional-digit rendering, pagination (limit 1–100 default 10, offset ≥0), field/enum validators, `created_at`-ASC + insertion-seq list paging
- `serializers.py` — per-entity serializers; `first_day_letter_due_date` rendered date-only; CommitmentLogEntry serialized with no `version`/`updated_at`
- `calc.py` — 10-business-day first-day-letter calc, ref normalization (`-R<n>` strip), repeat-finding detection (same-agency CLOSED issue, strictly prior `closed_at`), forward/historical risk variants (severity bp, HALF_UP repeat multiplier, 25 bp/day surcharge capped 5000, total capped 100000), overdue counts, posture (FROZEN ≥3 items or max overdue-days ≥ agency threshold, RESTRICTED ≥1 item or any OVERDUE milestone), REMEDIATION→VALIDATION auto-advance, clock-advance processing (milestone/issue OVERDUE transitions, escalation flag with sticky semantics)
- `routes_admin.py`, `routes_exams.py`, `routes_fieldwork.py`, `routes_remediation.py`, `routes_evidence.py`, `routes_reports.py`

## Endpoints: 76/76 implemented (all from the §4 table, including 6 portfolio reverse-reachability lists, risk-history, and `_clock/set_current_utc`)

## Organization of the tricky parts
- **Validation priority**: each handler follows PRD §2.9 literally — auth → role → path existence → state/terminality (terminal states per entity yield `ERR_ALREADY_TERMINAL`, otherwise `ERR_INVALID_STATE`) → SoD (5, closure approve/reject, vs operative plan = ACTIVE else latest COMPLETE) → cert gate (6, MRIA needs L3) → OCC (7, `expected_examination_version`/`expected_plan_version`/`expected_issue_version`, non-optional, 412) → overlap (8, half-open intervals, adjacent ≠ overlap) → meeting date collision (9, UTC-date grain vs FINALIZED only) → date range (10) → uniqueness (11) → referential (12) → posture gate (13, FROZEN blocks submissions, RESTRICTED/FROZEN blocks items) → shape (14)
- **Version accounting**: per request cascade, each affected entity bumps once (deduped in `touch()`); system transitions (auto-advance, plan auto-COMPLETE, supersede+freeze, item SUBMITTED on QC accept) reuse the same single bump; commitments carry no version
- **Calculations** live in `calc.py`; Decimal HALF_UP for the repeat multiplier; all date comparisons at UTC-day grain ("due today is not overdue")

## Smoke verification
Fresh-process boots via `bash start.sh` succeeded three times; boot #2 confirmed empty store + `2026-08-01` default clock (per-test isolation property). Two smoke suites (≈90 assertions) passed end-to-end: full exam lifecycle to CLOSED, QC accept/reject, meeting conflict, OCC 412s, SoD-before-OCC ordering, L3/MRIA gate, milestone ordering/auto-COMPLETE, closure reject→round-2 loop, plan reject/revise, supersede freezing milestones to OVERDUE → posture RESTRICTED, clock-driven overdue/escalation/threshold-FROZEN, forward-risk surcharge math (5250→5750 bp), risk-history, board-report snapshots, commitment blocking exam close, pagination meta, and error envelopes.

## Step 7: Run Tests and Iterate — 2026-08-14T23:50:00.000Z

All 8 rounds clean: 74/74 × 8. The loop exit condition is met.

## Summary

**Iterations run:** 2 (iteration 1: 24/74 failing deterministically across all 8 rounds; iteration 2: all 8 rounds clean at 74/74).

**Tests deleted:** None. Every failing test traced to verbatim PRD prose with uniquely derivable outcomes; all 24 failures shared a single test-helper root cause, and a second latent fixture bug was found behind it.

**Fixes applied to `test_helpers/`:**

1. `/home/ubuntu/github/CodingPRD/tasks/task_1881_regulatory_examination_management_issue/test_helpers/fixtures.py` — `create_plan_with_milestone`: the fixture called `create_remediation_plan_payload(**(plan_overrides or {}))` without the PRD-required `owner_user_id` (§3.6: "The payload names the accountable `owner_user_id` — the `id` of a `BankOfficer`"), crashing all 24 tests with `TypeError` before any request was issued. Fixed by defaulting `owner_user_id` to the acting officer's id from `owner_headers["X-User-ID"]` (per §2.1 the RemediationOwner's X-User-ID IS the acting BankOfficer's id), still allowing explicit override. This single upstream fixture bug masqueraded as 24 independent failures across test_06, test_07, and test_08 — matching the triage hint.

2. `/home/ubuntu/github/CodingPRD/tasks/task_1881_regulatory_examination_management_issue/test_helpers/fixtures.py` — `setup_closed_issue_for_repeat_lineage`: the fixture never advanced the logical clock after closing the lineage issue, so under the PRD-mandated frozen clock (§2.5: "Before any operator intervention the logical clock reads exactly `2026-08-01T00:00:00Z`") the closure's `closed_at` equaled the new issue's `created_at`, and the strictly-before repeat-detection rule (§3.5: "whose `closed_at` falls strictly before the new issue's `created_at`") could never hold — a PRD-faithful implementation correctly returned `is_repeat_finding: False` where tests expected `True`. Fixed by advancing the logical clock to `2026-08-02T00:00:00Z` after the closure approval, making the lineage genuinely strictly prior. Verified side-effect-free for the sole caller (no pending items/issues/milestones exist at that point on either exam; the expected score math 10,225 + 15,125 = 25,350 depends only on due dates and the final clock).

**Fixes applied to `implementation/`:** None. The implementation was already PRD-faithful on every exercised rule — the frozen-clock strictly-before repeat detection, the operative-plan reading for closure-time SoD and milestone-completeness gates, dual-variant risk scoring (forward 5,250 / historical 12,500 / multi-input 25,350 all exact), OCC ordering, and the §2.9 priority pipeline all behaved correctly once the fixtures issued PRD-consistent requests.

**Feedback notes for generators:**
- unit-test-generator: `create_plan_with_milestone` omitted a payload field its own factory declared positionally required — factories and fixture call sites drifted; the fixture should thread entity-backed identity (`owner_headers["X-User-ID"]`) into ownership-bearing payloads.
- doc-generator (Zero-Silence Rule adjacent): §3.5's strictly-before `closed_at`/`created_at` comparison interacts with §2.5's frozen logical clock in a way no test can satisfy unless the fixture explicitly advances the clock between closure and re-filing — the PRD sentence "whose `closed_at` falls strictly before the new issue's `created_at`" is the load-bearing prose, and test fixtures must construct that temporal precondition explicitly.

## Step 8: Finalize PRD — 2026-08-14T23:58:00.000Z

The diff contains exactly the two intended inline revisions; line count is unchanged. Here is the summary.

## Summary

**Line counts / delta:** `PRD.md` 302 lines, `PRD_FINALIZED.md` 302 lines — 0% line delta; 2 lines revised in place, no sections added or removed.

**Verdict on the two Step 7 fixture fixes:** both are pure fixture bugs — the PRD already uniquely determined the behavior and the implementation already matches it, so they produced **no edits**:
- Fix 1 (`owner_user_id` default): PRD §3.6 already states "The payload names the accountable `owner_user_id`", and §2.1 already pins that a RemediationOwner's `X-User-ID` is the acting BankOfficer's `id`. Impl requires the field (`req_str(p, "owner_user_id")`, routes_remediation.py:228) and performs no caller-equality check, consistent with the fixture's "default but overridable" semantics.
- Fix 2 (clock advance for repeat lineage): PRD §3.5 already pins "whose `closed_at` falls strictly before the new issue's `created_at`" (impl: `calc.py:52` `other["closed_at"] < created_at`) and §2.5 already pins the frozen `2026-08-01T00:00:00Z` clock (impl: `db.py:14`).

**Changes made** (both trace to the step_7_diff's named "operative-plan reading for closure-time SoD and milestone-completeness gates", exercised by the 24 unblocked test_06/07/08 tests):

- **§2.10 — revise** — SoD comparison target changed from "the `owner_user_id` of the issue's currently `ACTIVE` remediation plan" to "the `owner_user_id` of the remediation plan governing the issue — the issue's currently `ACTIVE` plan or, when no plan stands `ACTIVE`, the `COMPLETE` plan with the highest `plan_version`" — `implementation/routes_evidence.py:148-154` (`_sod_gate`), `implementation/routes_remediation.py:50-60` (`_operative_plan`).
- **§3.7 — revise** — submit-validation precondition changed from "every milestone of the issue's `ACTIVE` plan must stand `COMPLETE`" to "every milestone of the plan governing the issue's remediation — its `ACTIVE` plan or, when no plan stands `ACTIVE`, the `COMPLETE` plan with the highest `plan_version` — must stand `COMPLETE`" — `implementation/routes_remediation.py:178-185`.

Rationale: §3.6's auto-complete rule (impl `routes_remediation.py:481-482`) moves a plan ACTIVE→COMPLETE the moment its last milestone completes, so at every closure-gate evaluation in the normal flow no ACTIVE plan exists — the PRD's literal "currently `ACTIVE`" wording under-determines (indeed contradicts) the exercised behavior, under which `test_segregation_of_duties_blocks_owner_from_approving_closure` expects `ERR_SEGREGATION_OF_DUTIES` against a COMPLETE plan's owner.

**Per-edit pre-edit search log:**

*Edit 1 (§2.10):* (a) Subject: which plan's `owner_user_id` the closure-adjudication SoD gate compares against. (b) Enumerated impl paths: `_operative_plan` definition (`routes_remediation.py:50-60` — ACTIVE first, else max-`plan_version` COMPLETE, else None→no match); `_sod_gate` (`routes_evidence.py:148-154`) and both callsites `approve_closure` (`routes_evidence.py:168`) and `reject_closure` (`routes_evidence.py:203`); collision-checked parallel ACTIVE-only rules the wording must not leak into: milestone start/complete parent-plan check (`routes_remediation.py:441-443, 471-472`, `ERR_NO_ACTIVE_PLAN` — the milestone's own parent plan, a different subject), plan-approval exclusivity (`routes_remediation.py:305-310`), activation supersession (`routes_remediation.py:361-370`); also verified QC accept/reject carries no SoD gate. (c) Wording scoped by the sentence's existing "adjudicating a closure request" frame so it covers exactly the two closure operations and none of the literal-ACTIVE rules; the three impl branches (ACTIVE precedence / COMPLETE fallback / no-plan→no-match) are all expressible under the chosen phrase.

*Edit 2 (§3.7):* (a) Subject: which plan's milestones the submit-validation completeness gate evaluates. (b) Enumerated impl paths: the gate at `routes_remediation.py:178-185` (same `_operative_plan`; also fails when no governing plan or zero milestones — both unreachable in practice since issue `IN_PROGRESS` is only reachable via milestone start on an ACTIVE plan that held ≥1 milestone, and plans never move backward out of ACTIVE except to COMPLETE/SUPERSEDED with a new ACTIVE plan installed); the auto-complete mechanism (`routes_remediation.py:479-482`) that makes the COMPLETE fallback the normal case; confirmed `_operative_plan` has exactly two use sites (this gate + SoD) so both edits share one definition. (c) Wording mirrors Edit 1's phrase verbatim ("its `ACTIVE` plan or, when no plan stands `ACTIVE`, the `COMPLETE` plan with the highest `plan_version`") so the two gates cannot be read as selecting different plans; left §2.9 step 5 and §3.7's later "the segregation-of-duties check against the active plan's owner" untouched since both explicitly invoke the §2.10 gate that Edit 1 now defines.

## Step 9: Complete PRD — 2026-08-15T00:20:00.000Z

The work is complete. All edits verified as inline inserts/revisions; no new sections were added (section structure identical; +1 net line from a single added bullet in §2.2).

## Summary

**Source vs output:** `PRD_FINALIZED.md` (302 lines / 52,625 chars) → `PRD_COMPLETED.md` (303 lines / 58,473 chars). Char delta: **+5,848**.

**Counts:** 30 ambiguity-pins (insert), 4 mismatch-revisions (revise).

**Changes:**

- §2.2 success envelope — insert — ambiguity — `api_request_id` pinned as `req_` + 24 lowercase hex chars — implementation/response.py:12
- §2.2 success envelope — insert — ambiguity — `api_request_timestamp` taken from the real wall clock (the only non-logical-clock timestamp) — response.py:13
- §2.2 error format — insert — ambiguity — undefined path or unsupported method → `ERR_NOT_FOUND` (404) — app.py:34-40
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` (400) — util.py:48-70
- §2.3 — insert — ambiguity — equal `created_at` milliseconds ordered by server creation sequence — util.py:77
- §2.3 — insert — ambiguity — invalid enum filter value → 400; boolean filters accept `true`/`false` case-insensitively — util.py:122-138
- §2.5 — insert — ambiguity — all persisted entity stamps (`created_at`, `updated_at`, workflow stamps) read the logical clock — db.py:36-38,50-68
- §2.5 — insert — ambiguity — clock adopts any supplied `to_iso8601` unconditionally (no forward-only check) — calc.py:171
- §2.5 — revise — mismatch — recompute scope widened from "every affected examination" to every examination, incl. risk score; exam `version` bumps on a clock advance only when one of its issues/milestones transitioned to `OVERDUE` — calc.py:169-219
- §2.6 — insert — ambiguity — request timestamps accept any ISO 8601 form (`Z`, offset, date-only) normalized to UTC — util.py:9-27
- §2.7 — insert — ambiguity — missing/non-integer expected-version field → `ERR_INVALID_REQUEST` (400) raised at the concurrency check's pipeline position — routes_remediation.py:31-40
- §2.9 step 4 — revise — mismatch — terminal-state list: added `OVERDUE` and clarified the list is a cross-resource union applied per resource (OVERDUE terminal for milestones only; SUBMITTED not terminal for plans) — routes_remediation.py:438-440,467-469
- §2.9 step 14 — insert — ambiguity — malformed/non-object JSON → 400, absent body treated as `{}`, non-empty strings require non-whitespace, declared field types enforced — util.py:36-45,83-119
- §2.10 — insert — ambiguity — inactive-reviewer prohibition enforced as `ERR_UNAUTHORIZED` (403) at the authorization step; unknown reviewer ids act as opaque identities failing only the MRIA gate — middleware.py:31-39, routes_remediation.py:63-69
- §2.10 — insert — ambiguity — inactive agency on exam creation / inactive officer as plan owner → `ERR_INVALID_REFERENCE` (422) — routes_exams.py:58-59, routes_remediation.py:224-226
- §3.1 — insert — ambiguity — duplicate officer/reviewer `email` → `ERR_DUPLICATE_KEY` (409), evaluated after request-shape validation — routes_admin.py:77-79,112-114
- §3.1 — insert — ambiguity — all uniqueness comparisons (`agency_code`, `email`, `request_ref`, `issue_ref`) are exact, case-sensitive — routes_admin.py:30-32, routes_exams.py:216-218
- §3.4 — revise — mismatch — `attendees` rule changed from "at least one examiner and at least one bank officer" to non-empty array of non-empty name strings — routes_fieldwork.py:44-48
- §3.4 — insert — ambiguity — blank `minutes_summary` allowed at creation, fails finalization with `ERR_INVALID_STATE` — routes_fieldwork.py:49-50,84-85
- §3.5 — insert — ambiguity — historical-variant total also capped at 100,000 bp — calc.py:104
- §3.6 — revise — mismatch — activation supersedes *any* other ACTIVE plan regardless of `plan_version` (not only a "newer" plan); displaced plan's PENDING milestones transition literally to `OVERDUE`; IN_PROGRESS ones keep state but are blocked — routes_remediation.py:359-370
- §3.6 — insert — ambiguity — activation version accounting: bumps activated plan, displaced plans, forced-OVERDUE milestones; recomputes exam posture without bumping exam `version` — routes_remediation.py:361-375
- §3.6 — insert — ambiguity — explicit `sequence_index` accepted whenever integer ≥ 1 and unused on the plan (no increasing-order enforcement) — routes_remediation.py:397-405
- §3.6 — insert — ambiguity — per-issue remediation-plan listing filters by `status` — routes_remediation.py:247
- §3.6 — insert — ambiguity — milestone start/complete guard order pinned: target terminality (`ERR_ALREADY_TERMINAL`) → plan ACTIVE (`ERR_NO_ACTIVE_PLAN`) → target state (`ERR_INVALID_STATE`) → earlier-milestone sequencing — routes_remediation.py:433-474
- §3.7 — insert — ambiguity — submit-validation on a CLOSED issue draws `ERR_ALREADY_TERMINAL`; other non-IN_PROGRESS states draw `ERR_ISSUE_NOT_CLOSABLE` — routes_remediation.py:155-159
- §3.7 — insert — ambiguity — evidence-sufficiency and milestone-completeness preconditions evaluate after referential integrity (step 12), before request shape (step 14) — routes_remediation.py:160-190
- §3.7 — insert — ambiguity — submit-validation responds 201 carrying the newly created closure request — routes_remediation.py:204
- §3.7 — insert — ambiguity — closure-approval evidence-sufficiency check runs after the concurrency check — routes_evidence.py:173-178
- §3.7 — insert — ambiguity — per-issue closure-request listing filters by `status` — routes_evidence.py:125
- §3.8 — insert — ambiguity — clock-driven overdue judgment is at date granularity; an issue due on the current logical date is not yet overdue — calc.py:193-195
- §3.8 — insert — ambiguity — escalation rule re-consulted on every later clock advance for already-OVERDUE issues; a flag newly set there bumps only the issue's `version` — calc.py:205-212
- §3.8 — insert — ambiguity — re-fulfilling a commitment → `ERR_INVALID_STATE` (409) — routes_reports.py:148-149
- §3.9 — insert — ambiguity — `contributing_issue_ids` listed in issue creation order, oldest first — calc.py:98

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1881_regulatory_examination_management_issue/workspace/PRD_COMPLETED.md`

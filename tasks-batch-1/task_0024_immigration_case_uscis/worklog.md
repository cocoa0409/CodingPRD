# Worklog — task_0024_immigration_case_uscis

## Step 1: Create task directory — 2026-05-27T00:00:00Z

Created `./tasks/task_0024_immigration_case_uscis/workspace/`.

## Step 2: Generate scaffold — 2026-05-27T00:00:00Z

All three files are generated and the scaffold lint reports `VERDICT: clean lint`.

---

## Summary

Produced three artifacts for `task_0024_immigration_case_uscis/`:

**`SCAFFOLD.yaml`** — Compliance/audit primary archetype with workflow-orchestration secondary:
- **9 entities** (Applicant, Attorney, Case, BiometricsAppointment, RFE, InterviewAppointment, VisaBulletinEntry, CaseEvent, ClockState)
- **4 state machines** with branching/cyclic shapes (Case has UNDER_REVIEW↔RFE_PENDING cycle plus 3-way INTERVIEW_COMPLETED branch; BiometricsAppointment, RFE, InterviewAppointment)
- **2 concurrency_rules** (OCC on Case.version for /decide and /respond)
- **4 calculations**: `filing_fee` (tiered + nested rounding), `rfe_deadline` (threshold strict-less-than), `visa_availability` (dual-variant: FINAL_ACTION vs FILING_DATE), `officer_workload_score` (dual-variant: weighted_complexity vs flat_count)
- **17 validations** (priorities 1–17, continuous, ordered auth→existence→state→business)
- **32 endpoints** (full CRUD + transition actions + FK reverse-reachability GETs + 2 `/_*` test-driving endpoints)
- **17 errors** in catalog
- **5 roles**: Anonymous, Applicant (entity_backed), Attorney (entity_backed), Officer (opaque), FieldOfficeAdmin (opaque)

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — **18 instances** across all 9 rule_ids (2 each):
dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.

**`SCAFFOLD_CORNER_DESIGN.yaml`** — **30 instances total** (26 active, 4 `excluded_because:` stubs that correctly cite §1.8 instance names) covering entities (6), state_machines (9), calculations (5), validations (4), rbac (2), cross_cutting (2), endpoints (2).

`scaffold_lint.py` final verdict:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
Coverage: 32 endpoints, 9 entities, 18 §1.8 + 26 §1.9 instances, 265 calls scanned.
```

## Step 3: Copy INSTRUCTION.md — 2026-05-27T00:00:00Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-27T00:00:00Z

All audits pass. Let me also verify the Contract 2 rule coverage by checking each state-machine transition, calculation, validation, and OCC rule maps to PRD prose.

Contract 2 cross-check (mental walkthrough):
- **OCC rules** (2): Both `expected_case_version` rules covered in §2.10 with `ERR_STALE_VERSION` / 412 named.
- **State machine Case transitions** (15): all enumerated across §3.2 (DRAFT→FILED), §3.3 (FILED→BIOMETRICS_SCHEDULED, FILED→UNDER_REVIEW via advance-review for I-130, BIOMETRICS_SCHEDULED→BIOMETRICS_COMPLETED, BIOMETRICS_COMPLETED→UNDER_REVIEW), §3.5 (UNDER_REVIEW→RFE_PENDING, UNDER_REVIEW→INTERVIEW_SCHEDULED, UNDER_REVIEW→APPROVED, UNDER_REVIEW→DENIED), §3.6 (RFE_PENDING→UNDER_REVIEW, RFE_PENDING→ABANDONED), §3.7 (INTERVIEW_SCHEDULED→INTERVIEW_COMPLETED, INTERVIEW_COMPLETED→APPROVED, INTERVIEW_COMPLETED→DENIED, INTERVIEW_COMPLETED→UNDER_REVIEW). Biometrics state machine (SCHEDULED→COMPLETED, SCHEDULED→NO_SHOW, SCHEDULED→RESCHEDULED) in §3.3; Interview state machine (SCHEDULED→COMPLETED, SCHEDULED→NO_SHOW) in §3.7; RFE state machine (ISSUED→RESPONDED, ISSUED→EXPIRED) in §3.6.
- **Calculations** (4): filing_fee (§3.2), rfe_deadline (§3.6), visa_availability (§3.4 with both variants), officer_workload_score (§3.8 with both variants).
- **Validations** (17): all referenced via priority ordering in §2.11 plus inline triggers in §3.
- **Sibling-branch symmetry**: filing_fee variants, visa_availability variants (FINAL_ACTION vs FILING_DATE), workload_score variants (weighted_complexity vs flat_count), I-485 vs non-I-485 decide paths — all rendered with equal density.

PRD generation complete.

---

**PRD Generation Summary**

- **Output**: `workspace/PRD.md`
- **Word count**: 6,353 words
- **Sections**: 5 top-level (## 1–5), 20 subsections (§2.1–2.12 plus §3.1–3.8)
- **§2 structure**: 12 subsections (Access Control, Response Structure, Pagination, Common Resource Properties, Logical Clock, Receipt Number Format, Cascading Mutations, Nested Resource Retrieval, Monetary Precision, OCC, Validation Ordering, Status Code Conventions)
- **§3 structure**: 8 subsections (Actors/Onboarding, Filing, Biometrics, Visa Bulletin, Adjudication/RFE/Interview branches, RFE Lifecycle, Interview/Decision/Reopen, Officer Workload)

Audit verdicts: field-coverage PASS (58/58), path-purity PASS (0 leaks), rule-coverage PASS (2 OCC, 22 transitions, 4 calcs, 17 validations all expressed). Zero-silence audit clean.

## Step 5: Generate unit tests — 2026-05-27T00:00:00Z

**Files emitted:**
- `test_helpers/` — 9 files: `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`
- `test_suite/` — 15 files: `conftest.py` + 14 numbered test modules

**Test functions:** 62 total
- **Queue A (Difficulty):** 36 tests, 9 files (test_01–test_09), one file per difficulty rule
- **Queue B (Corner):** 26 tests, 5 files (test_10–test_14), grouped by section

**Queue A coverage (≥2 tests per instance):** 18/18 difficulty instances covered with exactly 2 tests each.
- dual_variant_calc · combinatorial_formula · non_linear_state_machine · transitive_cascade · priority_pair_validation_conflict · boundary_precision_check · cross_entity_state_dependency · resource_temporal_overlap · compensating_invariant

**Queue B coverage (≥1 test per non-stub instance):** 26/26 non-stub corner instances covered.
- entities: 6/6 · state_machines: 5/5 (4 `excluded_because:` stubs verified, NOT translated) · calculations: 5/5 · validations: 4/4 · rbac: 2/2 · cross_cutting: 2/2 · endpoints: 2/2

**Instances skipped:** 0. Every non-stub instance survived the PRD-first two-condition filter.

**Notable relaxation:** Corner `approved_case_decide_again_returns_already_terminal` uses `validate_error_is_one_of(["ERR_ALREADY_TERMINAL", "ERR_INVALID_STATE"])` because PRD §2.11's priority order places ERR_INVALID_STATE strictly above ERR_ALREADY_TERMINAL (error-precedence collapse).

**Citations:** every test docstring carries a verbatim PRD quote + a single `Design: <Queue>/<section_or_rule>/<instance_name>` line. No skip/skipif/xfail.

## Step 6: Generate implementation — 2026-05-27T00:00:00Z

**Generated at:** `workspace/implementation/`

**File count:** 21 files (19 Python + `start.sh` + `requirements.txt`)
**Total LOC:** 2,077 lines

**Layout:**
- Foundation: `app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `start.sh`, `requirements.txt`
- `routes/`: `registration.py`, `users.py`, `cases.py`, `biometrics.py`, `interviews.py`, `rfes.py`, `visa_bulletin.py`, `workload.py`, `clock.py`
- `services/`: `calculations.py`, `events.py`, `validation.py`

**Endpoints implemented:** 32 (matching scaffold §1.5 exactly)
**Calculations implemented:** 4 (filing_fee, rfe_deadline, visa_availability, officer_workload_score — including both dual-variants)
**State machines implemented:** 4 (Case 14 transitions, Biometrics, RFE, Interview — with cascades + event-log appends + version bumps)

**Key contract details honored:** response envelope (`meta.{api_request_id, api_request_timestamp}` + `response_type` + `data`), pagination (`limit/offset/total_count/has_more`), auth headers + 5 roles + §2.11 priority ordering, OCC on `/decide` and `/rfes/{id}/respond` with `ERR_STALE_VERSION` (412), receipt format `^(NBC|MSC|SRC|EAC|WAC|LIN|YSC|NSC|VSC|TSC)\d{10}$`, logical clock with `2025-01-01T00:00:00.000Z` default, no seeded state.

**Smoke test:** registered applicant → created I-485 case → set clock → filed → receipt `NBC2601500001` (format correct), `filing_fee_cents=112875` (150500 × 0.75 child discount applied to subtotal), version 1→2, officer assigned, status DRAFT→FILED.

## Step 7: Run tests + iterate — 2026-05-27T00:00:00Z

All 8 rounds clean: 60/60 passed. Exiting with summary.

**Iterations run:** 1 (8 parallel rounds per iteration). Pre-fix: 52/62 passed; post-fix: 60/60 passed.

**Tests deleted (2):**
- `test_overlapping_biometrics_30min_after_first_rejected` (test_08) — STEP 1b ERROR PRECEDENCE SILENCE: PRD §3.3 requires case in `FILED` to schedule biometrics; after first call case is `BIOMETRICS_SCHEDULED`, so a faithful impl returns `ERR_INVALID_STATE` (priority §2.11 ranks `ERR_INVALID_STATE` above `ERR_APPT_OVERLAP_SAME_CASE`). Test asserts an unreachable error.
- `test_back_to_back_boundary_does_not_collide` (test_08) — STEP 1b: happy-path assertion expects 201 from a second `schedule_biometrics`, but PRD §3.3 makes that call inadmissible (`ERR_INVALID_STATE`). The reschedule path also transitions the old appt to `RESCHEDULED` before any overlap check, so there is no PRD-faithful pathway in which two `SCHEDULED` biometrics co-exist on one case.

**Fixes applied to `test_helpers/` (1):**
- `test_helpers/fixtures.py::setup_officer_two_case_pool` — assumed a 1-officer round-robin; rewrote to file case_a, capture its `assigned_officer_id`, then file I-130 dummy cases until one is assigned to the same officer (used as case_b). Dummies assigned to other officers stay in `FILED` and do not appear in the queried officer's pool.

**Fixes applied to `test_suite/` (1 assertion relaxed, 0 deleted beyond above):**
- `test_14_corner_cross_cutting_endpoints.py::test_decide_with_stale_case_version_returns_412` — STEP 1b: PRD §2.10 narrative describes `ERR_STALE_VERSION` for the post-RFE-decide race, but §2.11 priority places `ERR_INVALID_STATE` strictly above `ERR_STALE_VERSION` (RFE issuance moves case to `RFE_PENDING`, breaking the decide state precondition). Relaxed assertion to `validate_error_is_one_of(["ERR_STALE_VERSION","ERR_INVALID_STATE"])` per the permitted exception in the cardinal rules.

**Fixes applied to `implementation/` (1):**
- `workspace/implementation/routes/cases.py::create_case` — was unconditionally setting `preference_category = None` for non-I-130 case types. PRD §3.5 explicitly references "an I-485 case whose `preference_category` is set" for the visa-availability gate, so I-485/I-765/I-131 cases must be allowed to store a `preference_category`. Changed to keep the value when supplied (validating it against the enum) and only require it for I-130.

**Final 8-round verification:** all of r1..r8 report `passed=60 total=60`.

## Step 8: Finalize PRD — 2026-05-27T23:17:00Z

Two minimal in-place edits, both pinning PRD silence/mismatch that traced to Step 7 fixes.

**Line counts:** PRD.md 260, PRD_FINALIZED.md 260 (0% line-delta; both edits revise existing prose in-line without adding/removing lines).

**Step 7 items mapped:**
- Deleted tests `test_overlapping_biometrics_30min_after_first_rejected` and `test_back_to_back_boundary_does_not_collide` — PRD §3.3 already pins ("case must currently be in `FILED`"); no PRD edit needed.
- Fixture fix `setup_officer_two_case_pool` — pure helper bug (assumed 1-officer pool; impl has 4-officer round-robin pool). PRD says "round-robin" without pool size; fixture now works for any pool size, so no PRD edit needed.
- Test assertion relaxed in `test_decide_with_stale_case_version_returns_412` — **PRD edit applied** below.
- `cases.py::create_case` fix (allow `preference_category` for non-I-130) — **PRD edit applied** below.

**Changes:**
- §2.10 (OCC narrative) — revise — clarified that in the documented RFE-race the rejection actually surfaces as `ERR_INVALID_STATE` per §2.11 priority (case has moved to `RFE_PENDING`), with OCC as the second line of defence — implementation/routes/cases.py:252 (state check) and :316 (OCC check, evaluated last).
- §3.1 (preference_category on non-I-130) — revise — pinned that `preference_category` is optional (not "ignored") for non-I-130 case types: omitted → stored as null; supplied → enum-validated and stored verbatim (so I-485 can carry the value referenced by §3.5's visa-availability gate) — implementation/routes/cases.py:79-85,102.

## Step 9: Complete PRD — 2026-05-27T23:24:00Z

Full PRD-vs-implementation/ scan over PRD_FINALIZED.md → PRD_COMPLETED.md, eliminating residual ambiguity and mismatch.

**Source vs Target line counts:**
- PRD_FINALIZED.md: 260 lines, 50,144 chars
- PRD_COMPLETED.md: 260 lines, 54,745 chars
- Char-delta: +4,601 chars (no line count change — all in-paragraph inserts/revisions)

**Counts:**
- Ambiguity-pins: 14
- Mismatch-revisions: 1

**Changes:**
- §2.5 Logical Clock — insert — ambiguity — Pin `ClockState.current_utc` boot default to `2025-01-01T00:00:00.000Z` — `db.py:46`
- §3.1 Onboarding — insert — ambiguity — Pin `is_under_14` defaults to `false` at applicant registration — `routes/registration.py:59`
- §3.1 Case creation — insert — ambiguity — Pin ownership rules for Applicant/Attorney case creation (self-ref / attorney_id match) — `routes/cases.py:88-96`
- §3.2 Filing preconditions — insert — ambiguity — Pin `ERR_ALREADY_TERMINAL` vs `ERR_INVALID_STATE` for re-filing; pin no body required — `routes/cases.py:164-167`
- §3.2 Filing officer assignment — insert — ambiguity — Pin officer pool as fixed 4-element cycle `officer-001`..`officer-004` — `db.py:66-78`
- §3.3 Biometrics reschedule — insert/revise — ambiguity — Pin RESCHEDULED as terminal for appt, exact `payload_json` keys `rescheduled_from`/`rescheduled_to`, response body is the new SCHEDULED appt, HTTP 200 — `routes/biometrics.py:181, 201, 226-232, 235`
- §3.4 Visa Bulletin publish — insert — ambiguity — Pin `ERR_INVALID_REQUEST` for duplicate (month, category, country, chart_type) tuples and for malformed `cutoff_date` — `routes/visa_bulletin.py:42-53`
- §3.4 Visa availability read — insert — ambiguity — Pin behavior of advisory read on case missing priority_date or preference_category (200 OK with both fields `RETROGRESSED` and `evaluation_month` from clock) — `routes/cases.py:368-378`
- §3.5 Interview scheduling — revise — mismatch — Change "evaluation month derived from `scheduled_at`" to "derived from `ClockState.current_utc`" (impl uses clock month, not interview month) — `routes/interviews.py:91`
- §3.5 Interview scheduling — insert — ambiguity — Pin `ERR_INVALID_STATE` when an `ISSUED` RFE exists on the case at scheduling time — `routes/interviews.py:79-81`
- §3.5 Decide from UNDER_REVIEW — insert — ambiguity — Pin that I-485 routing to interview yields `ERR_CASE_TYPE_NOT_APPLICABLE`; pin that other source states yield `ERR_INVALID_STATE` (terminal sources yield `ERR_ALREADY_TERMINAL`) — `routes/cases.py:247-263`
- §3.6 RFE deadline submission — revise — ambiguity — Pin date-portion lexicographic comparison: `now_date < deadline` accepts, `>=` rejects with `ERR_RFE_DEADLINE_PASSED` — `routes/rfes.py:142-146`
- §3.6 RFE sweep — insert — ambiguity — Pin that an RFE whose parent case is no longer in `RFE_PENDING` is still flipped to `EXPIRED` but no cascade/events fire; pin counting semantics for `expired_rfe_count` (counts all flips) vs `abandoned_case_count` (counts only this-run cascades) — `routes/clock.py:48-79`
- §3.7 Interview complete event payload — revise — ambiguity — Pin payload key as `decision` (not generic "the recorded decision") — `routes/interviews.py:181`
- §3.7 Decide from INTERVIEW_COMPLETED — insert — ambiguity — Pin `ERR_INVALID_STATE` for `decision`/interview-decision mismatch; pin `ERR_INVALID_REQUEST` for unsupported `decision` values — `routes/cases.py:283-298`
- §3.7 Event log payload schema — revise — ambiguity — Pin per-event-type `payload_json` key names: `rfe_id`/`deadline`/`biometrics_id`/`decision`/`fee_cents`/`officer_id`; pin empty `{}` for events with no structured data — `routes/cases.py:198-199`, `routes/rfes.py:83, 159`, `routes/clock.py:71`, `routes/biometrics.py:169`, `routes/interviews.py:181`
- §3.8 Officer workload response — insert — ambiguity — Pin `workload_score` is a JSON number (not string); pin `0.0`/`0` defaults when the officer has no cases in pool — `services/calculations.py:171, 169-173`

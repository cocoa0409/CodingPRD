# Worklog — task_0241_chiropractic_practice

## Step 1: Create Task Directory — 2026-06-07T16:40:40.000Z

Created `tasks/task_0241_chiropractic_practice/` and `tasks/task_0241_chiropractic_practice/workspace/` using the pre-allocated path (no ID auto-increment scan, per orchestration args). Task designed at Expert difficulty (§0.4).

## Step 2: Generate Scaffold — 2026-06-07T17:06:00.000Z

Generated the three Expert-tier scaffold artifacts for **task_0241_chiropractic_practice** under `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0241_chiropractic_practice/`:

- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

**Linter:** `python3 scaffold_lint.py` → **VERDICT: clean lint** (all 520 §1.8/§1.9 calls conform to §1.5; every §1.1 FK has reverse-reachability). Independent audits confirm: no unreferenced error codes, no dead enum values, all endpoint roles in the RBAC matrix, all `excluded_because` stubs reference real §1.8 instance names, and all instance names unique across both design files.

**Complexity profile:** Primary archetype Quota/allocation (insurance visit caps reserved→committed→released) + secondary Temporal windowing (recurring series across provider/room resources); layers: dual-variant calculation, cascading side effects, rate/threshold triggers, optimistic concurrency; hybrid topology; compound state-machine shape (parallel + cyclic dimensions); peer_roles; immediate consistency.

**Entity list (14):** Provider, TreatmentRoom, FeeSchedule, WellnessPlan, Patient, InsurancePolicy, ExamRecord, TreatmentPlan, PlanPhase, AppointmentSeries, Appointment, SoapNote, LedgerEntry, PracticeClock.

**Counts:**
- State machines: **9** (Appointment carries parallel attendance×billing dimensions; PlanPhase is cyclic via re-exam regression; plus ExamRecord, TreatmentPlan, AppointmentSeries, SoapNote, Patient, TreatmentRoom, InsurancePolicy)
- Calculations: **4** (`patient_responsibility` with CASH/WELLNESS/INSURANCE variants, `no_show_fee` tiered with NO_SHOW/LATE_CANCEL variants, `cap_reservation_check`, `series_generation`) — 3 carry variants
- Validations: **22** (priority-ordered)
- Endpoints: **63**
- Errors: **22**
- Roles: **4** (Provider entity_backed; FrontDesk/BillingClerk/PracticeAdmin opaque)
- Concurrency rules: **1** (OCC plan-activate-stale-patient, 412)

**§1.8 (Difficulty Design):** **18 instances** = 9 rules × 2 (dual_variant_calc, combinatorial_formula [modes a + c], non_linear_state_machine [parallel + cyclic], transitive_cascade [depth-3 no-show→dismissal→cap-release and depth-2 plan-discontinue→series→appointments], priority_pair_validation_conflict [state↔fiscal, safety↔temporal], boundary_precision_check [cap == vs > and dismissal >= threshold], cross_entity_state_dependency [Appointment→SoapNote, Appointment→Patient], resource_temporal_overlap [provider half-open vs room closed-with-buffer], compensating_invariant [cap-slot conservation, ledger-balance conservation]). All formula-derived asserts pre-computed as literals (e.g., insurance partial-deductible pr=6400, wellness overage pr=4200, late-cancel fee=1250).

**§1.9 (Corner Design):** **43 instances** across all 9 claim-extraction-guide sections — **37 active** test recipes + **6 `excluded_because` stubs** that point to the §1.8 instances already covering those corners.

## Step 3: Copy Shared Files — 2026-06-07T17:06:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0241_chiropractic_practice/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-07T17:10:30.000Z

Generated PRD at `workspace/PRD.md` — **287 lines** (49944 bytes).

**Major sections:**
- **§1 Introduction** — 3 paragraphs framing the chiropractic-practice domain (insurance caps, phased treatment plans, recurring series, three billing modes, cascading effects).
- **§2 Global Specifications** (10 subsections): 2.1 RBAC (four roles `Provider`/`FrontDesk`/`BillingClerk`/`PracticeAdmin` — Provider entity-backed, others opaque); 2.2 Response Structure; 2.3 Pagination; 2.4 Common Resource Properties (`LedgerEntry`/`PracticeClock` id+created_at only); 2.5 Hierarchical Consistency/Cascades; 2.6 Nested Retrieval/Existence Ordering; 2.7 OCC on plan activation; 2.8 Money/Counts/Rounding; 2.9 Patient Ledger; 2.10 Scheduling Resources/Buffers.
- **§3 Business Logic** (8 subsections, lifecycle-ordered): practice config, patient/coverage registration, clinical intake & plans, phase progression & regression cycle, series materialization & booking, scheduling-safety battery (full priority ordering of all 22 validations), the visit day (check-in/SOAP/complete/cancel/no-show/dismissal), billing (cash/wellness/insurance responsibility, tiered no-show fee, adjudication, write-off, payments).
- **§4 Endpoint Definitions** — 4-column table, all 60+ endpoints.
- **§5 Error Code Catalogue** — 2-column table, all 22 error IDs.

**Hard contracts:** Field coverage PASS (83/83), Rule coverage PASS (22 validations, 1 OCC rule, all state machines, 4 calculations), Path purity PASS (0 path tokens in §3).

**Confirmation:** Did NOT read `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` — neither opened, grepped, nor referenced.

## Step 5: Generate Unit Tests — 2026-06-07T17:30:00.000Z

Generated complete test infrastructure for **task_0241_chiropractic_practice** (Expert tier) under the design-index-only contract.

**Test files: 7** (1 conftest + 6 test files)
- `test_suite/conftest.py` — pytest bridge (api + 4 role-header fixtures)
- `test_suite/test_01_billing_calculations.py` — patient responsibility (cash/wellness/insurance), no-show fees, deductible application, write-off/payment ledger
- `test_suite/test_02_state_machines.py` — parallel attendance×billing, cyclic regression, phase bubble-up, SOAP sign-lock, invalid-state guards
- `test_suite/test_03_cascades_and_concurrency.py` — dismissal cascade, plan-discontinue cascade, cap conservation, OCC, series generation, immediate visibility, cap exclusion
- `test_suite/test_04_scheduling_and_boundaries.py` — provider half-open / room-buffer overlap, cap boundary, dismissal-strike boundary, priority-pair conflicts, availability/policy validations
- `test_suite/test_05_registration_and_validations.py` — patient CRUD/listing, payer-mode coherence, plan-readiness, SOAP-provider match, regression severity, fee-schedule supersede, reference-not-found
- `test_suite/test_06_rbac_and_errors.py` — RBAC (forbidden role, unauthenticated), leaf-not-found, ERR_VALIDATION

**Total tests: 73** — **36 from queue A (§1.8 Difficulty)**, **37 from queue B (§1.9 Corner)**.

**Coverage (verified by script):** All 18 difficulty instances have ≥2 tagged tests; all 37 active corner instances have ≥1 tagged test; 6 `excluded_because` stubs correctly NOT translated (all cross-refs resolve); 0 tags point to nonexistent instances; all 90 PRD citations survive verbatim grep of PRD.md; no skip/xfail; no scaffold-label leakage.

**Instances SKIPPED: 0** — Expert PRD is unusually complete (all 22 validations, priority ordering, both calc variants, OCC, full cascade narrative stated verbatim in §3); no gaps required skipping.

**test_helpers/ files (9):** `__init__.py`, `types.py` (LedgerEntry/PracticeClock id+created_at only), `api_client.py`, `api_errors.py` (22 IDs + HTTP map), `assertions.py`, `factories.py` (input-only), `constants.py` (no-show tiers/thresholds/cap-counting types), `test_users.py` (`make_provider_headers` for entity_backed Provider ownership; `make_anonymous_headers`), `fixtures.py` (composite setups incl. strike accrual/dismissal, OCC two-proposed-plans, discontinued-plan-exhausted-policy).

## Step 6: Generate Implementation — 2026-06-07T17:30:00.000Z

Generated complete Python + Flask implementation in `workspace/implementation/`.

**Source files (22):** `start.sh`, `requirements.txt` (`flask==3.0.3`), `app.py` (blueprint registration, error handlers, `0.0.0.0:$PORT` default 10000), `db.py` (in-memory dict stores + UUID/timestamp/sequence helpers), `models.py` (common-field id/created_at/updated_at/version, ISO-8601, practice-clock), `response.py` (meta/response_type/data envelope §2.2), `errors.py` (ApiError + 22-entry error→HTTP catalog), `middleware.py` (auth, RBAC, pagination), `lookups.py` (left-to-right existence ordering PATIENT→RESOURCE→REFERENCE), `validators.py`, `routes/` (config, patients, clinical, appointments, search — all 60 endpoints incl. flat cross-aggregate searches), `services/` (calculations.py 3-variant patient_responsibility + no_show_fee tiers + cap check, all Decimal/ROUND_HALF_UP; ledger.py; scheduling.py half-open provider + room-buffer + cap reservation; series.py atomic calendar-walk; plans.py phase bubble-up, regression cycle, discontinue/dismissal cascades).

**Framework/storage:** Python 3 + Flask, blueprints by concern; 100% in-memory module-level dicts keyed by id; money via `decimal.Decimal` ROUND_HALF_UP.

**start.sh boot:** reads `$PORT`, cd to own dir, installs deps only if `import flask` fails, then `exec python3 app.py` foreground binding `0.0.0.0:$PORT`. Responds in ~2s.

**No seeding confirmed:** all stores initialize empty; fresh boot returns total_count 0 for providers/patients; every test builds its own state via API.

## Step 7: Run Tests and Iterate — 2026-06-07T19:47:56.207Z

Two consecutive 8-round parallel sweeps both show 71/71 passing in every round with zero failures, zero errors, zero skips, and zero flakiness. The benchmark is clean and stable. Exiting with the Summary block.

- **Iterations run:** 2 full 8-round parallel sweeps. Both sweeps showed all 8 rounds at 71/71 passed (0 failed, 0 errors, 0 skipped). No flakiness surfaced across the 16 total rounds. No fixes were required in this loop — the implementation, test_suite, and test_helpers were already PRD-faithful and stable. The stale `results.solo.json` and the 67–68/73 `results.1-8.json` from the prior partial attempt were deleted at the start of each sweep as instructed.

- **Tests deleted:** None during this loop. The current suite has 71 tests (the worklog's original generation count was 73). The two missing tests — `test_state_check_precedes_fiscal_cap_on_series` and `test_state_error_fires_on_cancelled_phase_series` — were already deleted by the prior partial Step 7 attempt under the **ERROR PRECEDENCE / cross-state-dependency silence** pattern: they asserted `ERR_INVALID_STATE` must fire before `ERR_VISIT_CAP_EXCEEDED` on series generation against a cancelled phase, but PRD §3.6's fixed ordering places state-machine legality before the cap business rule only when the transition itself is illegal; the scaffold rule driving them was `Difficulty/priority_pair_validation_conflict (state↔fiscal)` / `Corner` series-cap-vs-state. Their absence is confirmed (grep returns nothing) and is consistent with PRD; I left them deleted.

- **Fixes applied to test_helpers/:** None this loop. (The `accrue_strikes` / `_no_show_one` helpers in `test_helpers/fixtures.py` already correctly thread `insurance_policy_id` into every strike booking, so the previously-seen `ERR_POLICY_REQUIRED` setup failures no longer occur.)

- **Fixes applied to implementation/:** None this loop. Audited `workspace/implementation/db.py` and confirmed storage is 100% in-memory module-level dicts, all initialized empty, no seeding, no SQLite/file/JSON cache — fully wiped on every `start.sh` re-invocation, per the cardinal rules.

## Step 8: Finalize PRD — 2026-06-07T19:51:24.238Z

(Skip condition NOT applied: Step 7's overall arc had iterations beyond baseline — 2 test deletions under ERROR PRECEDENCE silence + 1 `test_helpers/` fixture fix from the prior partial attempt this resume continues — so Step 8 ran.)

The edit is in place. One line changed (line 153), single sentence-cluster appended. Line count unchanged at 286 (the inserted text is appended to an existing line, not a new line).

Let me do a final consistency check on my wording against the §3.6 ordering claim. My sentence says generation "proceeds directly to the dismissed-patient guard and the scheduling and cap business rules." Let me confirm the dismissed-patient guard does run on the series endpoint (it does — `_guard_not_dismissed(patient)` at appointments.py:72) and that it comes before the scheduling/cap rules in the implementation. Confirmed: line 72 (dismissed guard) is before line 82-93 (resource availability, room type, policy) and before line 95 (generate, which does conflict + cap). My wording is consistent with the actual ordering at the series endpoint.

All enumerated paths are consistent with the new wording. The fixture-bug item required no PRD edit. Done.

---

**Summary block:**

- **Line counts:** PRD.md = 286 lines; PRD_FINALIZED.md = 286 lines; line-count delta = 0 (+0.0%). The single edit appends prose to existing line 153 rather than adding a new line; net textual addition is ~3 sentences.

- **Changes (one bullet per change):**
  - §3.5 (Materializing Appointment Series) — insert — appended a sentence-cluster pinning that series materialization imposes **no** phase- or plan-state-machine legality precondition: the request is accepted whatever the phase status (`PENDING`/`IN_PROGRESS`/`COMPLETED`/`CANCELLED`) or plan status, so the §3.6 `ERR_INVALID_STATE` step has nothing to fire against on this endpoint, and generation falls straight through to the dismissed-patient guard and the scheduling/cap business rules; explicitly noted that generating against a cancelled/non-active phase is **not** rejected with `ERR_INVALID_STATE` ahead of the cap check, so any `ERR_VISIT_CAP_EXCEEDED` is what surfaces — `workspace/implementation/routes/appointments.py:37-106` (no state check) and `workspace/implementation/services/series.py:48-154` (only conflict + cap checks).

- **Per-edit pre-edit search log:**
  - **Edit 1 (§3.5 series-state silence).**
    - (a) Subject: whether the series-generation endpoint (`POST /patients/{id}/treatment-plans/{id}/series`) applies a phase/plan state-machine legality precondition (`ERR_INVALID_STATE`) and where it sits relative to the cap rule — the exact silence the two deleted tests (`test_state_check_precedes_fiscal_cap_on_series`, `test_state_error_fires_on_cancelled_phase_series`) probed.
    - (b) Paths enumerated/read: `routes/appointments.py` `create_series` (lines 37-106) — confirmed no `ERR_INVALID_STATE`, no plan/phase status check; `leaf_or_404` (`lookups.py:18-29`) — confirmed no status filtering on the plan leaf; `services/series.py` `generate_series_internal` (lines 48-154) — confirmed only conflict + atomic cap checks, no state guard; `routes/clinical.py` `_regenerate_series`/`regress` (lines 234-327) — confirmed generation is invoked on a just-`IN_PROGRESS` acute phase with no re-validation, corroborating state-agnostic generation; grep of all `ERR_INVALID_STATE`/status comparisons in `routes/appointments.py` — confirmed the series path raises none; §3.6 PRD line 159 generic ordering reviewed to ensure scoping; `test_helpers/fixtures.py` (`accrue_strikes`/`_no_show_one`, lines 230-265) and `test_suite/` series tests reviewed — no surviving test asserts `ERR_INVALID_STATE` on series generation.
    - (c) Wording adjustment: scoped the claim strictly to "this endpoint" / "the named phase or its plan" and framed it as the §3.6 `ERR_INVALID_STATE` step "having no condition to fire against on this endpoint" rather than asserting series generation never raises `ERR_INVALID_STATE` in general — this keeps the new sentence consistent with the global §3.6 ordering (which still governs the booking/check-in/complete/sign/adjudicate/write-off paths that do raise `ERR_INVALID_STATE`) and with the regression-driven generation path, avoiding a new universal mismatch.

  - **Fixture-bug item (test_helpers `insurance_policy_id` threading).** (a) Subject: whether the strike-accrual fixtures' omission of `insurance_policy_id` reveals any unpinned PRD behavior. (b) Paths: `test_helpers/fixtures.py:230-265` and `routes/appointments.py:88-93` (`ERR_POLICY_REQUIRED` for INSURANCE bookings) + PRD §3.6 line 161. (c) No edit — the fixture change merely supplies a field the PRD already requires (`ERR_POLICY_REQUIRED` for an INSURANCE patient's booking); pure fixture bug, no PRD silence or mismatch.

## Step 9: Complete PRD — 2026-06-07T19:58:01.417Z

All 9 edits applied cleanly, with line count unchanged (in-paragraph inserts only) and no new sections. The char delta is +2423.

Let me do a final cross-check on two things I want to be sure about:

1. The **finalize ordering** — impl checks `status != DRAFT` (line 76-77) before `provider_id != uid` (line 78-79). My edit says state first then ownership. Correct.

2. The **sign ordering** in impl: missing note (RESOURCE_NOT_FOUND) → DRAFT (INVALID_STATE) → ownership (FORBIDDEN_ROLE) → CHECKED_IN (INVALID_STATE). My edit lists them in that order. Correct.

Let me confirm one possible over-reach: in the no-show edit I said "against an appointment in any other state are both rejected with ERR_INVALID_STATE" — impl's final `else` branch (line 420-421) raises `ERR_INVALID_STATE` for any non-BOOKED/non-CHECKED_IN state. Correct.

All edits accurately reflect the implementation. Here is the summary.

---

**Summary**

- Source `PRD_FINALIZED.md`: 286 lines / 50652 chars. `PRD_COMPLETED.md`: 286 lines / 53075 chars. Char delta: **+2423**. Line count unchanged (all edits are in-paragraph inserts/revisions; no new sections).
- Counts: **ambiguity-pins = 8**, **mismatch-revisions = 1**.

Per-change:
- §3.1 — insert — ambiguity — pinned that suspending a non-`ACTIVE` provider and closing a non-`OPEN` room are rejected with `ERR_INVALID_STATE` — config.py:61-62, 116-117
- §3.2 — insert — ambiguity — pinned that terminating a non-`ACTIVE` policy is rejected with `ERR_INVALID_STATE` — patients.py:159-160
- §3.3 — revise — ambiguity — pinned finalize-exam check order and error codes: non-`DRAFT` → `ERR_INVALID_STATE`, then authorship mismatch (`provider_id` ≠ `X-User-ID`) → `ERR_FORBIDDEN_ROLE` — clinical.py:76-79
- §3.3 — insert — ambiguity — pinned that proposing a plan against a non-`FINALIZED` exam is rejected at propose time with `ERR_PLAN_NOT_READY` (PRD previously named this error only at activation) — clinical.py:96-97
- §3.4 — revise — ambiguity — pinned the regression cascade detail: which `SCHEDULED` series are set to `REGENERATED` (corrective + re-activated acute phase, cancel-releasing their `BOOKED` appts), that the fresh acute series inherits provider/room/start_date/weekday_pattern/start_time/duration/policy from the regenerated acute series (fallback to first regenerated), and that no fresh series is generated when no `COMPLETED` acute phase exists — clinical.py:280-327
- §3.5 — revise — mismatch — corrected the generated-appointment conflict set from "`BOOKED`" to "`BOOKED` or `CHECKED_IN` … and against other appointments staged earlier in the same batch", and pinned that every generated appointment is assigned `visit_type` `ADJUSTMENT` — series.py:80-93, 100, 134, 157-160; scheduling.py:35, 54
- §3.7 — insert — ambiguity — pinned that check-in's three preconditions (appointment `BOOKED`, patient `ACTIVE`, provider `ACTIVE`) each fail with `ERR_INVALID_STATE` — appointments.py:252-258
- §3.7 — insert — ambiguity — pinned SOAP-sign failure error codes: no note → `ERR_RESOURCE_NOT_FOUND`, non-`DRAFT` → `ERR_INVALID_STATE`, provider mismatch → `ERR_FORBIDDEN_ROLE`, appointment not `CHECKED_IN` → `ERR_INVALID_STATE` — appointments.py:315-323
- §3.7 — insert — ambiguity — pinned that a too-early no-show (BOOKED before `scheduled_start`, CHECKED_IN before `scheduled_end`) and a no-show against any other state are rejected with `ERR_INVALID_STATE` — appointments.py:412-421
- §3.8 — insert — ambiguity — pinned that any of adjudication's four preconditions failing is rejected with `ERR_INVALID_STATE` — appointments.py:452-459
- §3.8 — insert — ambiguity — pinned that the payment endpoint returns the newly created `LedgerEntry` (not the patient) with `201 Created` — patients.py:80-90

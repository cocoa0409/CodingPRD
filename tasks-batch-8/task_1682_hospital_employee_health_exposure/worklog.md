# Worklog — task_1682_hospital_employee_health_exposure

## Step 1: Create Task Directory — 2026-08-14T07:22:54.000Z

Task directory `tasks/task_1682_hospital_employee_health_exposure/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline runner. Step 1 treated as DONE per orchestration instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T08:03:56.000Z

All checks pass. The scaffold is complete and lint-clean.

## Summary

Generated the scaffold for `task_1682_hospital_employee_health_exposure` purely from the scenario + skill spec (no sibling tasks inspected).

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1682_hospital_employee_health_exposure/SCAFFOLD.yaml` (§1.0–§1.7 + concurrency rules; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1682_hospital_employee_health_exposure/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1682_hospital_employee_health_exposure/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Counts:**
- Entities: 15 (Employee, PrePlacementScreening, TiterResult [append-only, `common_fields: false`], AnnualRequirementCycle, ComplianceHold, ExposureCase [parallel `case_status` × `source_test_status`], PEPRegimen, SerologyFollowUp, WorkRestriction, ReturnToWorkClearance, CommunicableEvent, ExposureContact, InjuryReport, VaccinationCampaign, CampaignParticipation)
- State machines: 14 — incl. parallel dimensions (ExposureCase), cyclic appeal loop (InjuryReport WC_DENIED↔APPEALED), posture-driven Employee (auto-only transitions)
- Calculations: 10 — dual variants on titer interpretation (quantitative vs qualitative) and cycle due dates (calendar vs rolling anniversary); mode-(a) risk classification; mode-(b) pinned per-department-then-mean rounding for coverage (75.00 vs 66.67 divergence); PEP 72h window; serology schedule; contact windows; posture derivation order
- Validations: 11 priority rows (auth → ownership/SoD → existence → OCC → state → safety → referential → temporal → constraint → shape)
- Endpoints: 58 (incl. `POST /_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z and full auto-transition evaluation; 13 single GETs included so every FK passes lint's reverse-reachability check (f))
- Errors: 40 (all referenced; two unreachable ones — `ERR_EXPOSURE_CASE_NOT_OPEN`, `ERR_CAMPAIGN_NOT_OPEN` — were found during recipe replay and removed)
- Roles: 5 (Nurse/Physician/ComplianceOfficer/SafetyOfficer opaque; StaffEmployee `entity_backed:Employee` with self-scope; segregation-of-duties on source-consent recording)

**§1.8:** 18 instances (9 rules × 2, all non-stub), each with structured replayable chains — cascades: campaign-close depth-3 (close→DELINQUENT→hold→SUSPENDED) and serology-POSITIVE depth-3 (result→SEROCONVERTED→FULL_EXCLUSION→WORK_EXCLUDED); boundary pairs: inclusive PEP deadline vs strict monitoring-end, half-open restriction adjacency vs closed-interval campaign touching; OCC supersede race on Employee.version.

**§1.9:** 69 instances total = 57 non-stub + 12 `excluded_because` stubs (all stubs verified to cite existing §1.8 instance names).

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (524 calls scanned; 18 §1.8 + 57 §1.9 non-stub instances.)

Post-lint audits: zero duplicate instance names across the union, no forbidden concurrency vocabulary, all 40 error ids triggerable/referenced, 2 instances per rule confirmed.

## Step 3: Copy Shared Files — 2026-08-14T08:03:56.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1682_hospital_employee_health_exposure/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T08:15:03.000Z

All audits pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1682_hospital_employee_health_exposure/workspace/PRD.md` (325 lines). `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened or referenced.

**Section list**
- §1 Introduction (3 paragraphs: business context, portfolio scope, logical-clock + segregation-of-duties commitments)
- §2 Global Specifications: 2.1 RBAC (5 roles, identity prose per role — `StaffEmployee` entity-backed, other four opaque), 2.2 API Response Structure (byte-identical verbatim block — verified programmatically), 2.3 Pagination, 2.4 Logical Clock & Scheduled Evaluation, 2.5 Common Resource Properties (incl. `TiterResult` append-only exception), 2.6 Nested Resource Retrieval, 2.7 OCC, 2.8 Validation Discipline & Priority Order (all 11 priority bands in pinned order), 2.9 Precision/Rounding/Calendar Arithmetic
- §3 Business Logic (9 subsections): 3.1 Employee registration & posture derivation, 3.2 Screening & immunity, 3.3 Annual cycle & holds, 3.4 Exposure intake/risk/source testing, 3.5 PEP & serology, 3.6 Restrictions & clearances, 3.7 Communicable events & contacts, 3.8 Injury/WC, 3.9 Campaigns & coverage
- §4 Endpoint Definitions (58 rows, 4 columns), §5 Error Catalogue (40 rows, 2 columns)

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 97 required, 97 present, 0 missing
- endpoints[].input/request_body: 17 required (incl. to_iso8601, component, completed_at,
  outcome, requirement_type, to_state, action, expected_employee_version, limit, offset, ...), 17 present, 0 missing
- query_params/path_params: all identifiers coincide with entity field names; covered
- Total audited set: 114 required, 114 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] priority ordering: 11 bands checked, 11 expressed in §2.8 pinned-order prose, 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (screening-create + expected_employee_version
  + ERR_STALE_EMPLOYEE_VERSION/412 + supersede rationale, no race framing), 0 missing
- state_machines[].transitions: 45 checked, 45 fully expressed (from/to states, preconditions paired with
  error ids, side effects incl. all cascades A/B, hold cascade, seroconversion, contact conversion,
  WC claim numbering, campaign fan-out ordering), 0 missing
- calculations[]: 10 checked, 10 fully expressed in precise prose (titer thresholds per disease with
  inclusive boundary and qualitative-ignore-numeric rule; both cycle due-date modes with 12-calendar-month
  anchor; all 7 risk-classification branches; 72h inclusive/strict PEP window; 28-day course; serology
  offsets 42/84/183 with 7-day lead/28-day lag; per-disease incubation offsets and monitoring windows;
  pinned posture order; 3-pronged OSHA rule; pinned two-step round-half-up coverage with forbidden
  aggregate-first order), 0 missing
- validations[] conditions: 40 error ids checked, all matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to scopes: all expressed (e.g., ERR_EMPLOYEE_NOT_ACTIVE on both
  cycle creation and vaccination administer; ERR_FUTURE_RESULT_DATE on both titer and source results), 0 missing
- entities[].fields[] structured content: defaults, null-until-set fields, reason-dependent hold linkage,
  required-when/ignored-when assay fields all reconstructible from prose, 0 missing
- sibling-branch symmetry: 12 parallel groups checked (consent outcomes, DUE/OVERDUE result+waive,
  WC_SUBMITTED/APPEALED accept+deny, risk branches, clearance outcomes, etc.), all equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 684
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- operator/pseudocode symbols (==, >=, +=, ...): 0
Status: PASS
```

All 58 endpoints and all 40 error IDs appear in the §4/§5 tables; every state and enum value from the scaffold appears in the prose as exact UPPERCASE strings.

## Step 5: Generate Unit Tests — 2026-08-14T08:46:40.000Z

Generation complete for `task_1682_hospital_employee_health_exposure`. All files compile, `test_helpers` imports cleanly, and pytest collects 91 tests.

## Test counts

- **Queue A (Difficulty)**: 36 tests — all 18 instances × exactly 2 tests each. Every docstring ends with `Design: Difficulty/<rule_id>/<instance.name>`.
- **Queue B (Corner)**: 55 tests — one per translated non-stub instance, each tagged `Design: Corner/<section>/<instance.name>`.
- All 12 `excluded_because:` stubs left untranslated; every stub's `difficulty_instance` pointer verified to resolve in the difficulty index.

## Instances skipped (2, both queue B non-stub)

1. `Corner/errors/err_pep_window_expired_triggerable` — the recipe attempts STARTED while `now` (2026-08-11) is still inside the 72h window with a future `started_at` (2026-08-14). PRD §3.5 pins window eligibility on the current logical time ("Starting is eligible only while the current logical time is no later than the window deadline"), so a PRD-only reader derives ERR_COMPLETION_OUT_OF_RANGE, not the asserted ERR_PEP_WINDOW_EXPIRED. Fails unique derivability.
2. `Corner/consistency_model/immediate_read_after_write` — asserts a general read-after-write immediacy guarantee grounded only in the scaffold's complexity profile; no verbatim PRD sentence states it. Fails coverage.

## Deviations from design-index literals (PRD-first corrections)

- `Corner/calculations/serology_schedule_dates_literal`: the index precomputes MONTH_6 as 2027-01-28 for exposure 2026-07-30T10:00:00Z; PRD §3.5's "one hundred eighty-three days" derives **2027-01-29T10:00:00Z** (verified by datetime arithmetic). The test asserts the PRD-derived value.
- `Corner/complexity_layers/occ_stale_version_and_supersede`: PRD never pins the initial `version` value, so the test asserts the derivable delta (`version == created_version + 2` after two successful screening opens) instead of the index's absolute `3`.
- `Corner/state_machines/serology_result_while_scheduled_rejected`: used `resulted_at` 2026-08-01T11:00:00Z (not the recipe's future 13:00) so the state violation is isolated per the validation-priority silence pattern.
- Second coverage test uses ICU 1/2 + ED 1/1 + LAB 1/1 → 83.33 (float/decimal-safe) vs the forbidden aggregate 75.00, instead of a 66.665-half-up edge case that float-implementers could legitimately land at 66.66.

## test_helpers file list

`types.py` (15 entity TypedDicts — TiterResult correctly omits `updated_at`/`version`, 15 status enums, UserRole), `api_client.py` (46 endpoint methods), `api_errors.py` (40-error catalog registered via `set_error_http_status_map`), `assertions.py` (per-entity assertions + `assert_instant` second-precision comparator + hold-count invariant), `factories.py`, `constants.py` (thresholds, PEP 72h/28d, serology offsets, disease windows), `test_users.py` (shared role headers + per-instance builders incl. `make_staff_employee_headers` for the entity-backed role), `fixtures.py` (7-tier composite helpers: screening-to-ACTIVE pipeline, overdue-hold cascade, PEP-started, tracing events, campaigns), `__init__.py` barrel.

## test_suite file list

`conftest.py` + 9 files in reading order: `test_01_employee_registration_access_envelope.py` (12), `test_02_screening_and_immunity.py` (15), `test_03_annual_cycles_compliance_holds.py` (13), `test_04_exposure_intake_source_testing.py` (9), `test_05_pep_and_serology.py` (11), `test_06_work_restrictions_clearances.py` (8), `test_07_communicable_events.py` (7), `test_08_injury_workers_comp.py` (5), `test_09_vaccination_campaigns.py` (11).

## Stage 2 self-audit verdict

- Tag coverage: every one of the 91 emitted tests carries exactly one Design tag as the docstring's final line; every tag resolves to a real instance; no stub translated; all 18 difficulty instances ≥2 tests; all 55 translated corner instances ≥1 test; the only two uncovered non-stub instances are the explicit skips above.
- PRD citation pass: all 98 quoted citation fragments verified verbatim against PRD.md programmatically (whitespace-normalized containment); 23 initial failures (stray periods inside quotes, `...` elisions, a `**Field shape**` markdown boundary) were fixed and rechecked clean. No skip/skipif/xfail markers anywhere.

## Step 6: Generate Implementation — 2026-08-14T08:46:40.000Z

Implementation complete for task_1682 (Hospital Employee Health & Exposure Management).

## File list (all under `tasks/task_1682_hospital_employee_health_exposure/workspace/implementation/`)

- `start.sh` — foreground launcher; guarded pip install (`import flask` check), `exec python3 app.py`; reads `$PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — flask only
- `app.py` — Flask entry, blueprint registration, envelope-aware error handlers (incl. catch-all 500)
- `db.py` — in-memory `Store` (dicts keyed by id) + `LogicalClock` (startup default exactly `2026-08-01T00:00:00Z`); **no seeding of any kind**
- `errors.py` — all 39 catalog error IDs with their HTTP statuses + `ApiError`
- `response.py` — envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta` for lists)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, role gating, field-shape validators, `limit`/`offset` pagination (default 10, clamp [1,100])
- `util.py` — UUID ids, ISO 8601 parse/format at **second precision** with `.000Z` output, calendar-month arithmetic
- `services/core.py` — posture derivation (holds dominate restrictions), hold/restriction cascades, employee status on the hold axis only
- `services/calculations.py` — all 10 calculation rules (titer thresholds inclusive, cycle due dates incl. rolling-anniversary day-preserving +12mo, risk classification, coverage per-dept-round-then-mean with `Decimal` ROUND_HALF_UP, PEP 72h/28d, serology 42/84/183d schedule with 7d-lead/28d-lag windows, disease incubation/monitoring tables, OSHA recordability, satisfaction)
- `services/sweep.py` — clock-driven auto-transitions: cycle OVERDUE + hold cascade + suspension, PEP WINDOW_EXPIRED (strict), serology DUE (inclusive)/OVERDUE (strict), contact CLEARED (strict), restriction EXPIRED (`now >= end_date`)
- `routes/` — 16 modules incl. `common.py` helpers

## Counts

- **Endpoints: 58** — matches the scaffold/PRD endpoint table exactly (incl. `POST /_clock/set_current_utc`)
- **State machines: 14** — all scaffold entities incl. ExposureCase's two parallel dimensions (`case_status` / `source_test_status`) and the cyclic WC_DENIED↔APPEALED loop
- **Calculations: 10** — all implemented per Table 3

## Verification (clean boot evidence)

- Cold boot via `bash start.sh` (exactly the evaluator contract): **HTTP-ready in ~682 ms**, empty store (`total_count: 0`), clock at the pinned default, equality set rejected `ERR_CLOCK_REGRESSION`
- Two smoke suites run against separate fresh boots: **suite 1: 115 checks passed** (2 listed "FAIL"s are assertion bugs in my ad-hoc script — the server correctly returned `ERR_PARTICIPATION_NOT_PENDING` for a re-administer attempt and kept the LIFTED restriction un-expired); **suite 2: 30/30 passed** — covering inclusive/exclusive boundaries (PEP start exactly at deadline, cycle OPEN on due date, contact MONITORING at exact `monitoring_end` then CLEARED 1s later), OCC 412, supersede-to-VOID, SoD 403, self-scope 403, per-transition RBAC, delinquency cascade (hold→suspension→ON_HOLD), seroconversion/contact-conversion FULL_EXCLUSION cascades, WC-000001 sequencing, campaign window touch-overlap 409, and coverage 66.67 per-dept-then-mean rounding
- All 28 Python files parse; one robustness fix applied during review (non-integer `expected_employee_version` → 400 instead of silently skipping OCC)

## Step 7: Run Tests and Iterate — 2026-08-14T08:55:00.000Z

All 8 rounds are clean: 91/91 passed in every round. Exiting with the summary.

---

## Summary

**Iterations run:** 2 (first sweep: 16 failures deterministic across all 8 rounds; second sweep after fixes: 8/8 rounds fully clean, 91/91 each).

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule; both failure clusters were test-artifact bugs, not coverage/derivability problems.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1682_hospital_employee_health_exposure/test_helpers/fixtures.py` — fixture `make_cleared_employee()`: added a `full_name: str = None` parameter forwarded into `register_employee(**overrides)`. 15 tests across `test_03`, `test_06`, and `test_09` called the fixture with `full_name="..."` (a PRD-declared registration field, PRD §2.1 line 123: registration supplies "`full_name`, `job_category`…"), but the fixture signature silently lacked it, raising `TypeError` before any assertion ran. The factory `create_employee_payload(**overrides)` already supported the field; only the fixture's passthrough was missing.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1682_hospital_employee_health_exposure/test_suite/test_05_pep_and_serology.py` — `test_positive_week6_result_seroconverts_case`: the BASELINE follow-up was resulted with `resulted_at="2026-08-01T12:30:00Z"`, 30 minutes ahead of the logical clock (`2026-08-01T12:00:00Z`, set by `setup_case_with_pep_started`). PRD §3.5 (line 177) requires `resulted_at` "no earlier than the case's `exposure_datetime` and no later than the current logical time (`ERR_COMPLETION_OUT_OF_RANGE`)", so the implementation's 422 was correct. Changed the inline `resulted_at` to `"2026-08-01T12:00:00Z"` (exactly at the clock; "no later than" is inclusive), making the setup PRD-consistent while leaving all cascade assertions untouched.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful in both clusters — it correctly rejected the future `resulted_at`, and the 15 `TypeError`s never reached the server.

## Step 8: Finalize PRD — 2026-08-14T08:57:00.000Z

Verification complete. Both step_7_diff items trace to behaviors the PRD already pins verbatim, and the implementation matches the PRD exactly at both sites.

## Summary

**PRD.md vs PRD_FINALIZED.md line counts:** 325 lines vs 325 lines — 0.0% delta (byte-identical copy, confirmed by `diff`).

**Edits made: zero.** Every `<step_7_diff>` item is a pure test-artifact bug with no underlying PRD silence and no implementation/PRD mismatch. Per the task's own rule, the correct minimal patch is a byte-identical copy of PRD.md, and no edits were invented.

### Per-diff-item verdicts

**Item 1 — `test_helpers/fixtures.py`: `make_cleared_employee()` gained a `full_name` passthrough parameter.**
- Verdict: **pure test-artifact bug** (fixture signature gap).
- Evidence: PRD §3.1 (line 123) already declares registration supplies "`full_name`, `job_category`…" — the field is PRD-pinned, not silent. Implementation at `workspace/implementation/routes/employees.py:30,42` requires it via `check_str(data.get("full_name"), "full_name")` and stores it — exactly what the PRD declares. The 15 `TypeError`s were raised by the fixture's Python signature failing to forward an already-supported factory kwarg (`create_employee_payload(**overrides)`); the request never reached the server. The implementation pinned nothing the PRD left open.

**Item 2 — `test_suite/test_05_pep_and_serology.py`: `test_positive_week6_result_seroconverts_case` inline `resulted_at` moved from clock+30min to exactly the clock.**
- Verdict: **pure test-artifact bug** (test setup violated a verbatim PRD rule).
- Evidence: PRD §3.5 (line 177) already pins verbatim: `resulted_at` "no earlier than the case's `exposure_datetime` and no later than the current logical time (`ERR_COMPLETION_OUT_OF_RANGE`)". Implementation at `workspace/implementation/routes/serology.py:85-92` enforces precisely that — rejects when `resulted_at > now() or resulted_at < case["exposure_datetime"]`, so both boundaries are inclusive, matching the PRD's "no earlier than… no later than" wording. The test's 30-minutes-ahead timestamp was a PRD-violating fixture value; the implementation's 422 was the PRD-correct response. Step 7's fix changed only test data; all cascade assertions were untouched. Nothing was left open for the implementation to pin.

**Output file:** `workspace/PRD_FINALIZED.md` — byte-identical to PRD.md, as required when Step 7 surfaced only test-artifact bugs.

## Step 9: Complete PRD — 2026-08-14T09:10:00.000Z

All edits are complete and verified. Final summary:

## Result

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1682_hospital_employee_health_exposure/workspace/PRD_COMPLETED.md`

**Sizes:** source `PRD_FINALIZED.md` (byte-identical to `PRD.md`): 325 lines / 58,903 bytes → `PRD_COMPLETED.md`: 328 lines / 63,970 bytes. **Char-delta: +5,034** (byte-delta +5,067). The 3 added lines are one bullet in §2.2 and one closing paragraph in §2.8; everything else is in-paragraph inserts/revisions.

**Counts:** 24 ambiguity-pins, 2 mismatch-revisions (26 edit operations total, several co-located).

**Changes (one per bullet):**

- §2.1 — insert — ambiguity — self-scope vs. existence ordering: for `/employees/{id}` ownership rejection precedes existence; for all other employee-owned resources the resource loads first (nonexistent id → `ERR_NOT_FOUND`, existing other-owned → `ERR_OWNERSHIP_REQUIRED`) — implementation/routes/employees.py:86-90 vs routes/common.py:13-19
- §2.2 — insert — ambiguity — undefined routes and unsupported methods are rejected `ERR_NOT_FOUND` (404) — implementation/app.py:28-35
- §2.3 — insert — ambiguity — missing/unparsable/out-of-range `limit`/`offset` are coerced to defaults then clamped (never rejected); `created_at` sort ties broken by creation (insertion) order — implementation/middleware.py:70-95
- §2.4 — insert — ambiguity — `transitions_applied` counts each automatic state change of an existing resource (including employee status cascades); auto-created resources (e.g. holds) do not count — implementation/services/sweep.py:7-12, 33-41
- §2.6 — insert — ambiguity — body-carried references (`screening_id`, `exposure_case_id`, `index_employee_id`, `contact_employee_id`) that fail to resolve are rejected `ERR_NOT_FOUND` — routes/titers.py:36, restrictions.py:44, injuries.py:35, events.py:32-33, contacts.py:33-34
- §2.7 — insert — ambiguity — missing or non-integer `expected_employee_version` → `ERR_INVALID_REQUEST`, surfaced at the stale-version checkpoint — routes/screenings.py:42-54
- §2.8 — insert — **mismatch** — carve-out to the pinned priority order for selector-multiplexed endpoints: per-transition role rejections (PEP/serology/contact/participation) run with step 2 before path existence; existence always precedes selector decoding; an unrecognized selector → `ERR_INVALID_ENUM`; decoding precedes state legality except terminal-state guards on case/event/campaign transitions and from-state checks on screening/clearance decisions — routes/pep.py:69-75, serology.py:67-81, contacts.py:137-150, participations.py:55-80, injuries.py:109-110, exposures.py:134-176, events.py:93-117, campaigns.py:112-174, screenings.py:141-165, clearances.py:61-67
- §2.9 — insert — ambiguity — offset-less timestamps interpreted as UTC; every supplied timestamp truncated to second precision on receipt — implementation/util.py:13-33
- §3.1 — insert — ambiguity — no recency bound on `hire_date` — routes/employees.py:33-35
- §3.2 — revise — ambiguity — components completable only while the screening is `IN_PROGRESS` (else `ERR_INVALID_STATE`) — routes/screenings.py:113-114
- §3.2 — insert — ambiguity — a `qualitative_result` supplied on a quantitative assay is discarded and stored null (mirror of the pinned qualitative direction) — routes/titers.py:63
- §3.2 — insert — ambiguity — latest-titer tie remaining after `resulted_at`/`created_at` broken in favor of the row recorded last; `decided_by_user_id`/`decided_at` null while `IN_PROGRESS` — services/calculations.py:35-41, routes/screenings.py:167-168
- §3.4 — insert — ambiguity — case `hiv_result`/`hbv_result`/`hcv_result` carry sentinel `PENDING` and `source_resulted_at` null until results are recorded — routes/exposures.py:85-88
- §3.4 — revise — ambiguity — `SEROCONVERTED` is terminal like `CLOSED`: any advance from either → `ERR_INVALID_STATE` regardless of `to_state`; unrecognized `to_state` otherwise → `ERR_INVALID_ENUM` — routes/exposures.py:135-136, 173-176
- §3.5 — insert — ambiguity — `started_at` null until start; the START request may optionally carry `medication`, replacing the intake default — routes/pep.py:113-116, services/calculations.py:98-111
- §3.5 — insert — ambiguity — one clock advancement can move a follow-up `SCHEDULED→DUE→OVERDUE` (each step a separate transition); follow-up `result` sentinel `PENDING` and `resulted_at` null until resulted — services/sweep.py:62-72, calculations.py:132-133
- §3.6 — insert — ambiguity — restriction `start_date`/`end_date` carry no recency bound (future dates accepted) — routes/restrictions.py:51-52
- §3.6 — insert — ambiguity — the overlap rejection applies only to physician-imposed creation; automatic `SEROCONVERSION`/`CONTACT_CONVERSION` restrictions bypass it — services/core.py:70-87 vs routes/restrictions.py:56-64
- §3.6 — insert — ambiguity — each clearance request creates a new clearance; multiple `PENDING` clearances may reference the same `ACTIVE` restriction — routes/restrictions.py:108-127
- §3.6 — revise — ambiguity — `decision_note` also remains null while the clearance is `PENDING` — routes/clearances.py:72, 123
- §3.7 — insert — ambiguity — event `onset_date` accepted without a recency bound — routes/events.py:36-38
- §3.7 — revise — ambiguity — contact enrollment is not gated on the event's status (replaces the "During monitoring" framing) — routes/contacts.py:22-76 (no status check)
- §3.7 — revise — ambiguity — symptom reporting accepted only from `MONITORING` (else `ERR_INVALID_STATE`); `symptom_onset_date` stored on the contact, no range validation, re-report overwrites — routes/contacts.py:116-127
- §3.9 — revise — **mismatch** — `department_scope` is any non-empty list of non-empty codes; `ALL` appearing anywhere in the list (not only as the single value) declares a house-wide campaign, incl. the fan-out phrase "scope contains `ALL`" — routes/campaigns.py:57-66, 127
- §3.9 — insert — ambiguity — a campaign with zero participations reports `coverage_rate` 0.0 — services/calculations.py:184-196

**Key findings:** the implementation matched the PRD on all major workflows (state machines, thresholds, rounding order, cascade rules, role tables, filter sets). The only true prose-level mismatch was §3.9's "single value `["ALL"]`" phrasing (impl accepts mixed lists containing `ALL` as house-wide) plus the §2.8 global priority order, which needed a carve-out because multi-transition endpoints decode the `to_state`/`action`/`outcome` selector before state legality (with terminal-guard and decision-endpoint exceptions). Everything else was PRD silence: sentinel `PENDING` values, null-field lifecycles, body-reference 404s, pagination coercion, timestamp parsing/truncation, `transitions_applied` counting, and absent temporal bounds on `hire_date`/`onset_date`/restriction dates/`symptom_onset_date`.

# Worklog — task_1667_international_student_sevis_compliance

## Step 1: Create Task Directory — 2026-08-14T06:07:00.000Z

Task directory `tasks/task_1667_international_student_sevis_compliance/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions.

## Step 2: Generate Scaffold — 2026-08-14T06:58:30.000Z

Scaffold generation complete and lint-clean. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_1667_international_student_sevis_compliance/`, generated purely from the scenario description and the skill spec (no sibling tasks were inspected).

**Design summary**

- **Profile**: compliance_audit (primary) × temporal_windowing (secondary); flat topology with FK references plus a self-referential `I20Form.supersedes_i20_form_id`; cyclic state machines; `hierarchical_override` roles (PDSO ⊇ DSO, entity-backed Student); immediate consistency.
- **§1.1**: 13 entities — Student, FinancialDocument, SevisRecord, I20Form, TermEnrollment, ReducedCourseLoad, EmploymentAuthorization, EmploymentPeriod, TravelEndorsement, TransferRequest, ProgramExtension, StatusViolation, AddressReport.
- **§1.2**: 12 state machines; the two non-linear ones are SevisRecord (ACTIVE→TERMINATED→REINSTATEMENT_PENDING→ACTIVE cycle) and EmploymentAuthorization (DRAFT↔RECOMMENDED revision loop). §1.2.1 has exactly two OCC rules (extension request on `SevisRecord.version`, endorsement issuance on `I20Form.version`), both passing the serial-observability filter.
- **§1.3**: 9 calculations with pinned constants/precision, incl. dual-variant funding coverage (provisional vs verified) and unemployment day counts (settled horizon=yesterday vs as-of horizon=today), per-line-then-sum proration rounding order, and the RCL floor formula `max(3, floor(base/2))`.
- **§1.4–§1.7**: 9-priority validation ladder (auth → existence → OCC 412 → state → safety → constraint → temporal → fiscal → credit rules), 42 endpoints (incl. `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z` and ordered sweeps), 38 error codes, 3 roles with `identity:` declared.
- **§1.8**: 18 instances, 2 per rule, all with executable `setup_api_calls`; formula-derived asserts were pre-computed (e.g., proration lines 25000/13889/8333/2778 → total 50000 vs sum-then-round 50001; settled/as-of unemployment 44 vs 45; day-90-safe/day-91-violation at clocks 2027-03-19/20).
- **§1.9**: 42 active corner instances across all nine guide sections (entities, state machines, calculations, validations, endpoints, RBAC, cross-cutting layers incl. both OCC stale-version tests, consistency) plus 10 `excluded_because` stubs pointing at §1.8 instances.

**Lint verdict (verbatim)**:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

628 calls scanned across 18 §1.8 + 42 §1.9 instances; 42 endpoints, 13 entities. Additional manual checks: no forbidden concurrency vocabulary, every error code is referenced by a validation and/or exercised in a design instance, and all 70 instance names are unique across both design files.

## Step 3: Copy Shared Files — 2026-08-14T06:59:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1667_international_student_sevis_compliance/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T07:06:00.000Z

**Contract 1: Field-Name Coverage — PASS**
- entities[].fields: 56 required, 56 present, 0 missing
- endpoints[].request_body/input: 13 additional identifiers (`to_iso8601`, `decision`, `note`, `action`, `outcome`, etc.) required, 13 present, 0 missing
- endpoints[].query_params / path_params: 1 (`id`) required, present
- Total: 70 required, 70 present, 0 missing

**Contract 2: Rule Coverage — PASS**
- validations[] with priority: 10 bands checked, 10 expressed as a numbered priority list in §2.9 with each error_id named, 0 missing
- concurrency_rules[] OCC rejections: 2 checked (program-extension request, travel-endorsement issuance), both expressed with write capability + `expected_sevis_record_version` / `expected_i20_form_version` + `ERR_STALE_VERSION` (412) + runs-before-business-validation, 0 missing
- state_machines[].transitions: 40 transitions across 10 entities checked, 40 fully expressed (from/to states, preconditions with error_ids, side effects), 0 missing
- calculations[]: 9 checked (financial_coverage, estimated_total_cents, extension_prorated_costs, full_time_requirement, rcl_eligibility, unemployment_days, travel_endorsement_validity, address_report_timeliness, compliance_posture), 9 fully expressed in prose with constants and variants, 0 missing
- validations[] conditions: all 10 priority rules matchable to error_ids in §2.9 plus their natural workflow sections, 0 missing
- endpoints[].side_effects / applies_to: all covered in the corresponding §3 workflow narratives, 0 missing
- entities[].fields[] structured content: defaults, enums, computed semantics, and constraints reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (RCL categories, violation actions, auth transition actions, RESOLVE outcomes, review decisions, transfer directions, OPT filing windows, endorsement terminal states), 8 with equal density, 0 asymmetric

**Contract 3: §3 Path Purity — PASS**
- backtick tokens scanned in §3: 423
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0

---

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1667_international_student_sevis_compliance/workspace/PRD.md`

The PRD is a prose-style specification of the SEVIS compliance API, organized as: §1 introduction (admission-to-departure framing), §2 global specifications (10 subsections covering RBAC with per-role identity semantics, verbatim §2.2 response envelope, pagination, common resource properties, the logical clock and its six-step sweep ordering, nested-resource retrieval, monetary/date precision, OCC, the 10-band validation priority order, and the compliance-posture derivation), §3 business workflows (10 subsections covering intake/financial documents, SEVIS record and I-20 lifecycle, term enrollment and full-course-load, RCL, CPT/OPT employment with the two unemployment-counter variants, travel endorsements, transfers, program extensions with the proration contract, termination/violations/reinstatement, and address reporting), §4 endpoint table (4 columns, 41 endpoints), §5 error catalogue (2 columns, 38 errors). All field names, state names, enum values, error IDs, formulas, thresholds, cascades, and validation priority orderings from the scaffold are expressed in prose; no paths or methods leak into §3.

## Step 5: Generate Unit Tests — 2026-08-14T07:44:00.000Z

Generation complete and all audits pass. Summary of what was produced:

## Stage 1 — `test_helpers/` (9 modules)

- `types.py` — 13 entity TypedDicts + 16 status/role enums. All entities carry `common_fields: true` in the scaffold, so all TypedDicts include `id`/`created_at`/`updated_at`/`version`.
- `api_client.py` — `ApiClient(GenericApiClient)` with 38 endpoint methods covering every PRD §4 endpoint, including the root-mounted `POST /_clock/set_current_utc`.
- `api_errors.py` — `ApiErrorId` enum + full 39-error HTTP status map from PRD §5, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity `assert_*` validators (UUID/timestamp/enum/field checks) + `assert_unemployment_invariant`. `assert_i20_form` re-derives `estimated_total_cents` from the four cost lines.
- `factories.py` — payload factories for all creatable entities and transition bodies.
- `constants.py` — all domain thresholds (183-day freshness, 12/9 credit floors, 90/75 unemployment limits, 10-day address window, 30/14-day deadlines, 12/6-month endorsement validity, 30/12 proration) + default clock `2026-08-01T00:00:00Z`.
- `test_users.py` — opaque `PDSO`/`DSO` shared headers; `make_student_headers(student_id)` builder for the entity-backed Student role (ownership-gated calls always thread the real student id); `NO_AUTH_HEADERS` for the auth-context probe.
- `fixtures.py` — staged composite chain: `setup_student_with_draft_record` → `..._with_draft_i20` → `..._with_issued_i20` → `setup_initialized_student` → `setup_active_student`, plus `setup_opt_post_approved` (DRAFT→RECOMMENDED→FILED-by-owner→APPROVED with clock choreography) and `setup_extension_requested` (OCC-threaded).

## Stage 2 — `test_suite/` (12 files, 78 tests)

Coverage audit (scripted against both YAMLs):
- **Queue A (difficulty): all 18 instances × exactly 2 tests** — every tag resolves.
- **Queue B (corner): all 42 non-stub instances × 1 test** — every tag resolves.
- **All 10 `excluded_because` stubs left untranslated**; their `difficulty_instance` pointers all resolve to real §1.8 instance names.
- Every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line as its final line.
- **Verbatim-citation pass: 126 quoted passages across 78 docstrings, all survive whitespace-normalized literal match against PRD.md.** No `skip`/`skipif`/`xfail` anywhere. `pytest --collect-only` collects 78 tests cleanly; all modules byte-compile.

Key PRD-adjudication decisions:
- **No `version == 1` assertions** — PRD §2.4 never pins the initial value; tests assert `isinstance(version, int)` and use only relative `+1` increments (which PRD §3.6/§3.8 pin explicitly).
- **Priority-pair instances kept** (not skipped under the validation-priority silence pattern) because PRD §2.9 explicitly enumerates the fixed reporting order, making the winner uniquely derivable; the second test per pair varies the scenario (NOT_ENROLLED vs COMPLETED enrollment; stale-funding vs fresh-but-thin funding).
- **`endorsement_on_draft_i20` kept** asserting `ERR_I20_NOT_ISSUED` — the only catalogue error expressing "operation requires an ISSUED I-20", named in PRD prose for the two sibling operations (recommend, supersede source).
- 204 period-deletion asserted via raw status (no JSON body), not `validate_success`.

## Step 6: Generate Implementation — 2026-08-14T08:02:00.000Z

The implementation is complete and verified. Here is a summary of what was built.

## What was done

Generated a complete Python + Flask implementation for the International Student SEVIS Compliance API at `/home/ubuntu/github/CodingPRD/tasks/task_1667_international_student_sevis_compliance/workspace/implementation/`:

**Files:**
- `start.sh` — guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground
- `app.py` — Flask app factory, blueprint registration, envelope-shaped error handlers (404/405/catch-all)
- `db.py` — empty-on-boot in-memory stores, logical clock (default exactly `2026-08-01T00:00:00Z`), wall-clock `created_at`/`updated_at` (3-fractional-digit UTC), `version` counters, strict `YYYY-MM-DD` parsing, month-end-clamping `add_months`
- `errors.py` — all 36 catalog error IDs with exact HTTP statuses
- `response.py` — exact envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list pagination fields `limit`/`offset`/`total_count`/`has_more` in meta
- `middleware.py` — `X-User-ID`/`X-User-Role` validation (400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), role gating for `PDSO`/`DSO`/`Student`
- `services.py` — all 9 calculations (183-day funding freshness, per-line-then-sum proration with `Decimal` ROUND_HALF_UP, full-time floors 12/9 with RCL adjustments, settled/as-of unemployment counters, endorsement validity 12/6 months, address 10-day rule, compliance posture), cascades (termination, supersede, completion), and the 6-step clock sweep in the PRD's fixed order
- `routes/` — 9 blueprint modules covering all 41 endpoints including `/_clock/set_current_utc` at server root

**Key fidelity decisions (traced to PRD/design docs):** validation bands ordered per PRD §2.9 (auth → role → existence → OCC 412 → state → structural → uniqueness → temporal → fiscal 402 → credit 422); OCC tokens coerce int-or-digit-string; Student ownership `ERR_RESOURCE_NOT_OWNED` precedes state checks; FILE is Student-only, RESOLVE is PDSO-only; endorsement/employment-period overlap both use closed-interval day intersection (adjacency allowed only for periods); sweeps dedupe open unemployment violations and recompute all postures after each clock set (75-day AT_RISK drift); no entity seeding at startup.

**Verification:** a 153-assertion end-to-end suite replicating every corner/difficulty design scenario (freshness boundary 183/184 days, proration per-line rounding 50000 vs 50001, unemployment 44/45 and 90/91 boundaries, OCC 412 flows, cascade chains, RBAC negatives) passes 153/0 on a fresh `bash start.sh` boot; kill-and-relaunch between requests confirms clean state reset, and boot completes in ~2.5s, well within the 60s window.

## Step 7: Run Tests and Iterate — 2026-08-14T08:38:00.000Z

**Final state: all 8 parallel rounds pass 78/78, 0 failed, 0 errors** (sweep 3, results.1–8.json verified).

**Iterations run:** 3 eight-round sweeps.
- Sweep 1: 70/78 per round (8 consistent failures + 1 flaky ConnectionError in round 6 only).
- Sweep 2 (aborted once by a self-matching `pkill`, then rerun): 73/78 — confirmed the two fixed tests held and exposed the latent `create_rcl_payload` NameError behind the earlier KeyError failures.
- Sweep 3: 78/78 × 8 rounds. The sweep-1 flaky `ConnectionError` (test_student_file_on_other_student_auth_returns_403, round 6 only) never recurred across 16 subsequent rounds — transient load contention, no code change needed.

**Tests deleted:** none. Every failing assertion traced verbatim to PRD (§3.1 sevis_id uniqueness, §3.2 initialization gate, §3.4 RCL rules); all failures were test-artifact bugs, not implementation bugs.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — added missing `create_rcl_payload` to the `.factories` import list; `create_rcl()` called it but it was never imported (NameError, masked earlier by the fixture-misuse KeyError).

**Fixes applied to `test_suite/`:**
- `test_01_students_intake.py::test_student_duplicate_sevis_id_returns_409` — the test created the default student then `ALT_STUDENT` (a *different* sevis_id N0087654321) and asserted `ERR_DUPLICATE_SEVIS_ID`; the PRD-faithful implementation correctly returned 201. Fixed the payload to reuse the default `sevis_id` so it actually exercises PRD §3.1's uniqueness rule; added the `TEST_DEFAULTS` import.
- `test_04_records_enrollments_registration.py` — added missing `setup_student_with_draft_i20` to the `test_helpers` import list (NameError).
- `test_05_reduced_course_loads.py` — six RCL tests called `setup_initialized_student()`, which creates no enrollment, then used `ctx["enrollment"]["id"]` (KeyError). Swapped to `setup_active_student(register=False)` (INITIAL record + PENDING enrollment with 12 credits — exactly the precondition the tests' own comments document and PRD §3.4 requires). `test_rcl_create_after_add_drop_returns_add_drop_closed` deliberately kept `setup_initialized_student()` since it creates its own enrollment after advancing the clock.

**Fixes applied to `implementation/`:** none — the implementation was PRD-correct in every failure case.

## Step 8: Finalize PRD — 2026-08-14T08:45:00.000Z

Verification complete. All Step 7 fixes trace to test-artifact bugs; the implementation behavior in every case is already uniquely pinned by existing PRD prose. `PRD_FINALIZED.md` stands as a byte-identical copy of `PRD.md` (the correct minimal patch: zero edits).

## Summary

**Line counts / delta:** `PRD.md` = 354 lines, `PRD_FINALIZED.md` = 354 lines, **0% delta** (diff confirms identical). File created at `/home/ubuntu/github/CodingPRD/tasks/task_1667_international_student_sevis_compliance/workspace/PRD_FINALIZED.md`.

**Changes:** none. Every `<step_7_diff>` item resolved to a pure fixture/test bug with the implementation already PRD-determined, so no PRD sentence needed inserting or revising.

- §3.1 / §3.2 / §3.4 — *no edit* — all five fix items (fixtures.py `create_rcl_payload` import; `test_student_duplicate_sevis_id_returns_409` payload fix; `test_04` `setup_student_with_draft_i20` import; six `test_05` RCL setup swaps; the deliberately-kept `setup_initialized_student()` in `test_rcl_create_after_add_drop_returns_add_drop_closed`) are test-artifact fixes; matching impl behavior is verbatim-pinned by existing PRD prose — `workspace/implementation/routes/students.py:49-78`, `workspace/implementation/routes/records.py:58-68`, `workspace/implementation/routes/enrollments.py:153-256`, `workspace/implementation/services.py:108-135`.

## Per-candidate pre-edit search log

**Candidate 1 — §3.1 sevis_id uniqueness** (from `test_student_duplicate_sevis_id_returns_409` fix)
- (a) Subject: what makes two student intakes "duplicates" — sevis_id alone vs. composite identity.
- (b) Paths enumerated: grep for `sevis_id` across `implementation/` — uniqueness enforced only at `routes/students.py:63-65` (`for other in db.students.values(): if other["sevis_id"] == sevis_id` → `ERR_DUPLICATE_SEVIS_ID`), preceded by the format check at `routes/students.py:59-60`; serialization at `serializers.py:21`. No other create/update path writes `sevis_id`, so uniqueness can never be violated post-creation.
- (c) No edit committed. Impl checks equality of `sevis_id` alone, across all students — exactly what PRD §3.1 already states ("The `sevis_id` must be unique across the system ... a duplicate is rejected with `ERR_DUPLICATE_SEVIS_ID`"). The Step 7 failure was the test using `ALT_STUDENT` with a *different* sevis_id (N0087654321); the impl correctly returned 201. PRD uniquely determines the behavior; adding wording would risk narrowing it.

**Candidate 2 — §3.2 initialization gate** (from the `test_04` import fix and the RCL setup chain, which runs through `initialize_record`)
- (a) Subject: preconditions and errors for DRAFT → INITIAL.
- (b) Paths enumerated: grep for `ERR_RECORD_NOT_DRAFT` / `ERR_NO_ISSUED_I20` / `initialize` — single site `routes/records.py:58-68` (not-DRAFT → `ERR_RECORD_NOT_DRAFT`; no ISSUED form for the record via `services.issued_forms_of_record` → `ERR_NO_ISSUED_I20`). No other caller initializes records.
- (c) No edit committed. Impl order and errors match PRD §3.2 verbatim ("initialization on a record not in `DRAFT` ... `ERR_RECORD_NOT_DRAFT`; initialization without any `ISSUED` form ... `ERR_NO_ISSUED_I20") and §2.9 band 6. The failure was a missing test-helper import, not behavior.

**Candidate 3 — §3.4 RCL rules** (from the six `test_05` setup swaps)
- (a) Subject: RCL creation/decision preconditions — parent-enrollment state, one-open-RCL, add/drop deadline, category floors, exhaustion, and error ordering.
- (b) Paths enumerated: grep for `reduced_course_loads` and all `ERR_RCL_*` — creation `routes/enrollments.py:153-222` (state check line 164 → one-open line 167 → add/drop line 171 → FINAL_TERM containment line 175 → credit range lines 185-190 → exhaustion lines 191-210), list line 225, decision lines 234-256; helpers `services.py:108-135` (`base_min_credits`, `approved_rcl_of`, `academic_floor` = `max(3, base // 2)`, `effective_min_credits`: ACADEMIC floor / MEDICAL exact requested / FINAL_TERM `max(1, requested)`); store `db.py:27`. No sweep or cascade touches RCLs. Cross-checked against patch (`enrollments.py:119-121`) and registration (`enrollments.py:139-140`) paths since the fixed tests exercise approve→patch→register at the recomputed floor.
- (c) No edit committed. Every assertion in the fixed tests (ACADEMIC floor 6 for undergrad, approval recompute, registration at exact floor, MEDICAL 0-credit approval and 0-credit registration, FINAL_TERM containment, second-ACADEMIC exhaustion, decision-on-decided `ERR_RCL_NOT_REQUESTED`, late filing `ERR_RCL_ADD_DROP_CLOSED`, state-beats-deadline ordering) is pinned verbatim by PRD §3.4 plus §2.9 bands 5/7/8/10 and §3.3's "meeting the floor exactly counts as full-time". The failures were `ctx["enrollment"]` KeyErrors from a setup helper that created no enrollment — fixtures, not behavior.

One observed-but-out-of-scope note (no edit, per HARD SCOPE): `routes/enrollments.py:245-246` adds an approval-time parent-enrollment state check (`ERR_ENROLLMENT_NOT_REGISTERABLE`) that PRD §3.4 does not explicitly mention; no Step 7 fix touched it, so it is outside the permitted edit scope.

## Step 9: Complete PRD — 2026-08-14T09:05:00.000Z

PRD_COMPLETED.md is complete. All edits verified in the diff.

## Summary

**Source:** `PRD_FINALIZED.md` (354 lines / 46,578 chars) → **`PRD_COMPLETED.md`** (357 lines / 51,857 chars, **+5,279 chars**), at `/home/ubuntu/github/CodingPRD/tasks/task_1667_international_student_sevis_compliance/workspace/PRD_COMPLETED.md`.

**Counts:** 24 ambiguity-pins, 2 mismatch-revisions (26 changes total; all inline insert/revise, no new sections).

**Mismatch-revisions:**
- §2.5 — revise — mismatch — the fixed sweep-order list omitted a sweep the impl runs: `employment_authorization_completions` (APPROVED authorizations past `end_date` → COMPLETED) executes as its own pass between record completions and the OPT_POST unemployment check; list renumbered to 7 items — implementation/services.py:399-408
- §2.9 band 2 — revise — mismatch — PRD pinned the action-specific role rule (FILE=Student, RESOLVE=PDSO) in band 2 ahead of existence; impl reads the action from the body, so the rule fires after path-existence validation and body parsing (DSO calling RESOLVE on a nonexistent violation gets 404, not 403) — implementation/routes/violations.py:60-66, implementation/routes/employment.py:106-118

**Ambiguity-pins:**
- §2.1 — insert — ambiguity — Student callers on the three `student_id`-filterable collection lists get the filter forced to their own id; an explicit mismatched filter → ERR_RESOURCE_NOT_OWNED — implementation/routes/i20.py:83-87, enrollments.py:85-89, employment.py:81-86
- §2.2 — insert — ambiguity — unmatched route/method renders the standard error envelope as ERR_NOT_FOUND (404) — implementation/app.py:28-34
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → ERR_INVALID_REQUEST (400) — implementation/helpers.py:137-153
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion sequence — implementation/helpers.py:159
- §2.5 — insert — ambiguity — clock value stored/echoed verbatim as submitted; offset-less datetimes read as UTC; no monotonicity check — implementation/routes/clock.py:15-29, db.py:59-71
- §2.5 — insert — ambiguity — `sweeps_applied` names only categories that actually applied a change, with the exact category strings — implementation/services.py:315-449
- §2.9 — revise — ambiguity — ERR_INVALID_REQUEST coverage broadened (null fields, below-minimum values, pattern violations, cross-field date/clock ordering incl. outbound release_date before clock date); body-parse failures precede all state/business validation; body-named references resolved after parsing — implementation/helpers.py:23-111, transfers.py:40-41
- §3.1 — insert — ambiguity — `country_of_citizenship` must be two uppercase ASCII letters — implementation/routes/students.py:61-62
- §3.2 — insert — ambiguity — no ordering constraint enforced between record `program_start_date`/`program_end_date` — implementation/routes/records.py:31-32
- §3.2 — insert — ambiguity — unknown/unowned `sevis_record_id` or `supersedes_i20_form_id` at drafting → ERR_NOT_FOUND; the ISSUED requirement on the supersede target is enforced only at issuance — implementation/routes/i20.py:50-56
- §3.2 — insert — ambiguity — DRAFT forms return live clock-relative funding figures; snapshot semantics begin at issuance — implementation/serializers.py:61-65
- §3.3 — insert — ambiguity — credit edit against NOT_ENROLLED/COMPLETED enrollment → ERR_ENROLLMENT_NOT_REGISTERABLE — implementation/routes/enrollments.py:113-114
- §3.4 — revise — ambiguity — MEDICAL term month count uses plain date subtraction (`term_end_date` − `term_start_date`), ceil of days/30 — implementation/routes/enrollments.py:206-209
- §3.4 — insert — ambiguity — RCL approval requires the parent enrollment still PENDING/REGISTERED (else ERR_ENROLLMENT_NOT_REGISTERABLE); denial exempt — implementation/routes/enrollments.py:243-246
- §3.5 — revise — ambiguity — transition `note` accepted but never persisted — implementation/routes/employment.py:104-180
- §3.5 — insert — ambiguity — CPT adjudication only ever reaches APPROVED; ADJUDICATE with DENIED on CPT → ERR_AUTH_INVALID_STATE — implementation/routes/employment.py:163-167
- §3.5 — revise — ambiguity — nonzero unemployment counters only for OPT_POST in APPROVED or COMPLETED (REVOKED reports zeros); period reporting requires APPROVED status on any auth type; ongoing periods treated as open-ended for overlap; auth `version`/`updated_at` advance only when counters actually change — implementation/services.py:183-192, routes/employment.py:199-249
- §3.5 — revise — ambiguity — unemployment sweep examines only APPROVED OPT_POST authorizations and skips opening when an UNEMPLOYMENT_LIMIT_EXCEEDED violation is already OPEN/REINSTATEMENT_PENDING — implementation/services.py:410-432
- §3.6 — insert — ambiguity — endorsement "issue date" is the server's logical clock date at issuance — implementation/routes/i20.py:176-183
- §3.7 — insert — ambiguity — a due outbound transfer moves to RELEASED even when the record is no longer ACTIVE, with no record transition or enrollment flips in that case — implementation/services.py:321-335
- §3.8 — insert — ambiguity — filing requires an existing record (ERR_NOT_FOUND, evaluated before the OCC check) in ACTIVE status (ERR_RECORD_NOT_ACTIVE) — implementation/routes/extensions.py:42-49
- §3.8 — insert — ambiguity — proration basis is the most recently created ISSUED form; with no ISSUED form all prorated lines are zero and the replacement supersedes nothing; replacement inherits `program_name`, record start/approved end dates, and approval-time funding snapshot — implementation/routes/extensions.py:96-132
- §3.8 — revise — ambiguity — approval supersedes every ISSUED form of the record, not just the named prior — implementation/routes/extensions.py:133-134
- §3.10 — revise — ambiguity — `state_code` must be two uppercase letters — implementation/routes/students.py:161-162

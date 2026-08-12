# worklog — task_1135_community_college_contract_training

## Step 1: Create Task Directory — 2026-08-10T22:45:00.000Z

Task directory pre-assigned by pipeline runner (no auto-index scan performed): `tasks/task_1135_community_college_contract_training/` with `workspace/` subdirectory already present. Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-10T23:40:00.000Z

All three artifacts are written and lint-clean. Summary:

## Files produced
- `/home/ubuntu/github/CodingPRD/tasks/task_1135_community_college_contract_training/SCAFFOLD.yaml` — §1.0–§1.7 (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1135_community_college_contract_training/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1135_community_college_contract_training/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

## Counts
| Metric | Count |
|---|---|
| Entities | 13 |
| State machines | 12 (Employer cyclic, NeedsAssessment revision cycle, TrainingAgreement QUOTED↔NEGOTIATING cycle + parallel billing dimension + IN_DELIVERY cascade-cancel, GrantProgram OPEN↔SUSPENDED, GrantApplication RETURNED→SUBMITTED cycle + sweep EXPIRED, Cohort parallel delivery×billing, Session, Instructor ACTIVE↔INACTIVE, InstructorAssignment, Participant, Invoice, OutcomeReport) |
| Calculations | 10 (incl. dual-variant quote_pricing and grant_award; 3 combinatorial modes: tiered/rush/floor, per-line-rounding-then-sum, pinned gross→offset→net order) |
| Endpoints | 76 |
| Errors | 30 |
| Roles | 7 (segregation of duties: proposer cannot confirm; EmployerContact/Instructor entity-backed) |
| Concurrency rules (OCC) | 2 (quote-revise on TrainingAgreement.version, grant-create on Cohort.version) |
| Difficulty instances | 22 (all 9 rules, ≥2 each) |
| Corner instances | 38 active + 11 `excluded_because` stubs |

## Lint verdict (verbatim)
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(76 endpoints, 13 entities, 22 §1.8 + 38 §1.9 instances, 1020 calls scanned, zero violations.)

## Key design decisions
- **Archetype**: quota/allocation (grant fund pool reserve→commit→reimburse/release with exact conservation invariant `available+reserved+committed+reimbursed == appropriation`) blended with compliance/audit (credential scoring with 30-day expiry weighting, segregation of duties).
- **Harder-than-expert levers**: three distinct combinatorial modes (not just two); two resource-overlap rules with different interval semantics (instructor half-open adjacency vs venue closed-interval + 30-min turnover buffer); a depth-3 cancellation cascade (agreement→cohort→session→assignment/hours) plus a depth-3 attendance cascade; version-pinning of the approved assessment at sign time with a `refresh_assessment_pin` recovery endpoint.
- **Replay fixes applied during self-audit**: fresh `${coh_v}` captures via GET after version-bumping enrollments in every OCC-guarded grant-create chain; participant counts sized so per-trainee caps don't zero out awards; FINAL invoice created before grant claim where the final award needs a gross basis; dual-expiry (not partial) in the fund-conservation sweep since both approvals share `claim_by`; IN_DELIVERY→CANCELLED transition added so the conditional-cascade corner is reachable.
- No sibling task directories were inspected; the design is purely from the scenario text and the skill spec.

## Step 3: Copy Shared Files — 2026-08-10T23:40:30.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-10T23:55:00.000Z

All audits pass. The PRD is complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1135_community_college_contract_training/workspace/PRD.md` — 339 lines.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications — 2.1 RBAC, 2.2 API Response Structure (verbatim block, byte-identical to `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Version, 2.5 Logical Clock, 2.6 OCC, 2.7 Monetary Precision & Rounding, 2.8 Validation Pipeline & Nested Path Resolution, 2.9 Delivery Modes/Venues/Scheduling, 2.10 Grant Fund Ledger, 2.11 Parallel Status Dimensions & Cascades
- §3 Business Logic — 3.1 Employer Onboarding & Needs Assessment, 3.2 Quoting/Negotiation/Signature, 3.3 Grant Programs & Applications, 3.4 Cohort Setup/Sessions/Rosters, 3.5 Staffing & Credential Gates, 3.6 Delivery/Attendance/Credentialing, 3.7 Invoicing/Offsets/Settlement, 3.8 Outcome Reporting, 3.9 Cancellation Cascades & Clock Sweeps
- §4 Endpoint Definitions (76 rows, 4 columns), §5 Error Code Catalogue (30 rows, 2 columns)

**Zero-silence / coverage self-audit verdict:**
- **Contract 1 (field names): PASS** — 100 required identifiers (entity fields + request bodies + query/path params), 100 present in backticks, 0 missing. One gap (`completion_status`) was found by the mechanical diff and repaired; second pass clean.
- **Contract 2 (rules): PASS** — all 11 validation-priority classes stated in explicit evaluated order (§2.8); both OCC rules fully expressed (endpoint + `expected_agreement_version`/`expected_cohort_version` + `ERR_STALE_VERSION`/412) in §2.6 and reinforced in §3.2/§3.3; all ~56 state transitions with preconditions and side effects expressed, including the full SIGNED/IN_DELIVERY cancel cascade (links 1/2/3/2'/2'' with CREDENTIALED/HELD carve-outs); all 10 calculations rendered as precise prose (tiered quote, per-line-pinned invoice rounding, three-ceiling grant offset, provisional-vs-final award, weighted credential match, 80.00% attendance boundary, committed-hours and fund-ledger invariants, placement rate, employer rollups); all 30 error IDs matchable to triggers in §2/§3; sibling branches (PER_PARTICIPANT/FLAT_COHORT, PROVISIONAL/FINAL, DRAFT/RETURNED resubmission, DRAFT/ISSUED void) rendered at equal density.
- **Contract 3 (§3 path purity): PASS** — 588 backticked tokens in §3 scanned, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos.
- Additional checks: §2.2 verbatim confirmed byte-identical; all 51 state/enum strings present; all 7 role spellings exact with `identity:` translations in §2.1; fuzzy-word scan clean (no "approximately/about/roughly"); pseudocode-operator scan of prose clean (no `==`, `>=`, `min()`, `AND`/`OR`, etc.).

The constraint files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, and no other `tasks/task_*/` directory was inspected.

## Step 5: Generate Unit Tests — 2026-08-11T00:25:00.000Z

Generation complete. Summary:

**Files generated**
- `test_helpers/` (9 files): `types.py`, `api_client.py` (64 endpoint methods), `api_errors.py` (30 error IDs registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (per-instance builders for the two entity-backed roles `EmployerContact`/`Instructor`), `fixtures.py` (composite setups through CREDENTIALED), `__init__.py` barrel.
- `test_suite/` (10 files): `conftest.py` + 9 numbered test files grouped by concern (quoting, negotiation/signature, cohort launch, assignments/credentials, attendance/delivery, grants, invoicing, cancellation cascades, platform).

**Test count:** 82 tests, all collecting cleanly under `pytest --collect-only`, all compile, no `skip`/`skipif`/`xfail` markers.

**Queue A coverage:** 22/22 difficulty instances emitted, each with >=2 tagged tests (0 skipped). All were PRD-covered and uniquely derivable — including the two priority-pair instances, since PRD §2.8 explicitly enumerates the fixed validation order and states "the first failing check produces the error response."

**Queue B coverage:** 38/38 non-stub corner instances emitted, each with >=1 tagged test (0 skipped). The 11 `excluded_because:` stubs were verified to resolve to real difficulty instances and were not translated.

**Stage 1 self-check:** PASS — helpers expose every method/fixture Stage 2 imports; entity-backed roles always threaded via `make_employer_contact_headers(employer["id"])` / `make_instructor_headers(instructor["id"])` on ownership-gated calls (sign, close_attendance); fixtures use `get_success_data` and build from empty DB per test.

**Stage 2 self-check:** PASS —
- C4: every test docstring ends with exactly one `Design:` line resolving to a real instance (82/82 verified programmatically against both yamls; no unknown tags, no stub tags, no dual tags).
- C1/C2/C3: every quoted PRD span in all 82 docstrings survives a literal whitespace-collapsed grep of `PRD.md` (82/82, 0 failures after fixing 20 ellipsis-joined quotes into full contiguous sentences).
- No freelance tests: every test traces to exactly one design-index instance.

## Step 6: Generate Implementation — 2026-08-11T00:25:00.000Z

Implementation complete. Summary:

## Files (all under `workspace/implementation/`)

- `start.sh` — executable, guarded `pip install` (no-op once Flask present), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — Flask entry, blueprint registration, envelope-shaped error handlers (ApiError, 404/405/400, catch-all)
- `db.py` — in-memory store (13 collections, **starts empty, no seeding**), logical clock frozen at 2026-05-01T00:00:00Z, `touch()` (updated_at refresh + version bump on every mutation, direct or cascade)
- `errors.py` — full 30-entry error catalog with exact IDs and HTTP statuses
- `response.py` — exact envelope: `meta{api_request_id(req_*), api_request_timestamp}` (3-fraction-digit ISO), `response_type` object/array/error, list `meta` gains `limit/offset/total_count/has_more`
- `middleware.py` — X-User-ID/X-User-Role validation (400), role gates (403), EmployerContact ownership scoping
- `util.py` — datetime parse/format, Decimal round-half-up/floor helpers, body validators, pagination (limit default 10, clamped ≤100, offset ≥0)
- `services/lookups.py`, `services/calculations.py`, `services/lifecycle.py` — business logic
- `routes/commercial.py` (clock, employers, needs-assessments), `routes/agreements.py`, `routes/grants.py`, `routes/instructors_venues.py`, `routes/cohorts.py` (cohorts+participants), `routes/sessions.py` (sessions+assignments), `routes/billing.py` (invoices+outcome-reports)

## Endpoints: 76/76 implemented (all paths/methods from the SCAFFOLD endpoint table; orchestrator independently verified (method, path) parity: 76 declared == 76 implemented, no missing, no extras)

## State machines (13, all with preconditions, side effects, version bumps)
Employer (PROSPECT/ACTIVE/DORMANT + 365-day dormancy sweep), NeedsAssessment (DRAFT↔SUBMITTED/APPROVED/REVISION_REQUESTED with revision_round), TrainingAgreement (DRAFT→QUOTED⇄NEGOTIATING→SIGNED→IN_DELIVERY→COMPLETED/CANCELLED + parallel billing_status UNBILLED/PARTIALLY_BILLED/SETTLED + terminal lockdown via ERR_AGREEMENT_TERMINAL), GrantProgram (OPEN⇄SUSPENDED→CLOSED with zero-encumbrance gate), GrantApplication (full 10-state machine incl. RETURNED resubmission cycle, EXPIRED sweep, WITHDRAWN cascade), Cohort (6 delivery states + parallel billing dimension), Session (PLANNED/HELD/CANCELLED with ALREADY_CLOSED vs INVALID_STATE distinction), Instructor, InstructorAssignment (PROPOSED/CONFIRMED/RELEASED/COMPLETED), Participant (ENROLLED→COMPLETED/DROPPED/NO_SHOW at 80.00% boundary), Invoice (DRAFT/ISSUED/PAID/VOID with ERR_INVOICE_NOT_PAYABLE specialization), OutcomeReport (DRAFT/SUBMITTED/ACCEPTED). Full cancellation cascades (agreement→cohort→session→assignment, plus grant withdrawal with reservation release and invoice voiding) and both clock sweeps are implemented.

## Calculations (all 10)
`quote_pricing` (tiered marginal PER_PARTICIPANT, FLAT_COHORT, mode adjustment, single round-half-up after rush uplift, 150000 floor), `invoice_gross` (per-line rounding then integer sum; FINAL=HELD+per-session attendees, PROVISIONAL=PLANNED+enrolled_count; ×1.15 load), `invoice_grant_offset` (pinned 3-step, min of award basis/share-floor/cap×headcount), `grant_award` (PROVISIONAL/FINAL variants), `credential_match_score` (0/0.5/1.0 weights, 30-day horizon, ≥80 gate, empty→100), `attendance_completion` (2-dp round-half-up, ≥80.00 boundary), `instructor_committed_hours` (defined-sum invariant), `grant_program_fund_rollup` (ledger invariant), `placement_rate`, `employer_rollup`. Both OCC rules (`expected_agreement_version` on revise, `expected_cohort_version` on grant-application create → 412).

## Smoke-test results
Three batches against fresh-booted servers via `start.sh`:
- **Batch 1 (60 checks, PASS)**: full happy path — employer→assessment→agreement→quote (verified exact cents: 709500 with rush; 1622500 after revise)→negotiate/revise OCC 412→sign (403 wrong employer)→cohort→sessions (venue overlap + 30-min boundary)→SoD self-confirm 409→launch→grant ledger (200000 reserve → 31375 final award claim → paid, invariant holds)→attendance (ALREADY_CLOSED on re-close)→PROVISIONAL/FINAL invoices with exact line math (32250/16125, 62750/31375)→credential codes `CTC-20260601-e1`→outcome report→COMPLETED/SETTLED→dormancy sweep→DORMANT.
- **Batch 2 (46 checks, PASS)**: FLAT_COHORT+ON_CAMPUS quote (614000), floor (150000), quote expiry, STALE_ASSESSMENT/refresh-pin, credential expired/mismatch (50/75/100 scores), double-booked, full IN_DELIVERY cancel cascade with fund release, grant window/program-not-open gates, expiry sweep, pagination meta, NO_COMPLETERS, OUTCOME_INCOMPLETE, 0-completer INVALID_REQUEST.
- **Batch 3 (22 checks, PASS)**: stale-pin sign flow, max_cohorts ceiling, BELOW_MIN_ENROLLMENT, VENUE_CAPACITY_EXCEEDED, boundary launch (enrolled==min==capacity), RBAC 403s, EmployerContact cross-employer read 403, nested 404, body validation.
- **Isolation contract**: 3 consecutive `bash start.sh` cold boots each ready in <1s with `total_count=0` on every collection — no carry-over state between processes.

## Step 7: Run Tests and Iterate — 2026-08-11T00:35:00.000Z

## Summary

**Iterations run:** 2 (initial sweep: 64/82 × 8 rounds, identical deterministic failures; post-fix sweep: 82/82 × 8 rounds, all passing).

**Tests deleted:** None.

**Fixes applied to `test_suite/` (18 failing tests, 2 root causes — no implementation changes, no test_helpers changes):**

1. **Wrong expected HTTP status on resource-creating endpoints (17 tests).** PRD §4 states verbatim: "Endpoints that create a new resource respond with 201; reads, state transitions, modifications, and the clock operation respond with 200." The implementation correctly returned 201; the tests called the framework's `validate_success(resp)` which defaults to expecting 200. Fixed by passing `201` as `expected_status` at each create call site:
   - `test_06_grants.py`: `create_invoice` ×3 (lines 126, 262, 411)
   - `test_07_invoicing.py`: `create_invoice` ×9 (lines 83, 123, 188, 208, 244, 261, 293, 302, 333)
   - `test_08_cancellation.py`: `create_invoice` ×2 (lines 168, 189)
   - `test_09_platform.py`: `create_grant_application` (377), `create_participant` (512), `create_session` (561), `create_outcome_report` (592)

2. **Error-precedence ambiguity in `test_02_negotiation_and_signature.py::TestTerminalLockdown::test_sign_on_cancelled_agreement_rejected`.** The test asserted `ERR_INVALID_STATE`, but PRD §3.2 says verbatim "Operations that target an agreement already in `COMPLETED` or `CANCELLED` are rejected with `ERR_AGREEMENT_TERMINAL`," while §2.8 item 5 names terminal lockdown as `ERR_INVALID_STATE` at priority 5 (ahead of `ERR_AGREEMENT_TERMINAL` at priority 6). Two faithful PRD-only implementations diverge here, so per the ERROR PRECEDENCE SILENCE pattern the assertion was relaxed to `validate_error_is_one_of(["ERR_AGREEMENT_TERMINAL", "ERR_INVALID_STATE"])`; the lockdown assertion on `contract_status == "CANCELLED"` was kept intact. Docstring updated to record both PRD citations.

**Fixes applied to `implementation/`:** None — the implementation was already PRD-faithful on every tripped rule.

Orchestrator verification: all 8 results files on disk, each passed=82 total=82 failed=0.

## Step 8: Finalize PRD — 2026-08-11T00:45:00.000Z

Done. One edit total; everything else in the Step 7 diff was either already pinned verbatim by the PRD or a pure test bug.

## Summary

**Line counts / %-delta:** `PRD.md` 339 lines, `PRD_FINALIZED.md` 339 lines — 0% line delta (one line revised in place, no lines added or removed).

**Changes:**
- §2.8 (item 5) — revise — extended the "terminal lockdown" clause with an explicit exception: operations targeting a training agreement already in `COMPLETED`/`CANCELLED` are rejected with `ERR_AGREEMENT_TERMINAL` (as §3.2 states), not `ERR_INVALID_STATE` — `implementation/routes/agreements.py:50-55` (`_check_not_terminal`), invoked at lines 164 (quote), 185 (revise), 208 (negotiate), 224 (sign), 250 (cancel), 264 (refresh_assessment_pin), in every case before the `ERR_INVALID_STATE` branch; identical terminal-first pattern at `implementation/routes/cohorts.py:55-56` (cohort create) and `implementation/routes/billing.py:179-180` (outcome-report create).

**Step-7 item disposition:**
- The 17 `expected_status=201` test fixes needed no PRD edit: §4 already states verbatim "Endpoints that create a new resource respond with 201", and all 13 create routes return 201 (`agreements.py:123`, `cohorts.py:84,247`, `billing.py:74,198`, `commercial.py:66,145`, `grants.py:84,181`, `instructors_venues.py:55,114`, `sessions.py:87,235`). Pure fixture bug.
- The `test_sign_on_cancelled_agreement_rejected` relaxation was the one genuine PRD internal contradiction (§2.8 item 5 vs §3.2); the implementation resolves it to `ERR_AGREEMENT_TERMINAL`, pinned by the edit above.

**Per-edit pre-edit search log (single edit):**
- (a) Subject: which `error_id` surfaces when an operation targets a terminal (`COMPLETED`/`CANCELLED`) training agreement — §2.8 item 5's "terminal lockdown → `ERR_INVALID_STATE`" vs §3.2's `ERR_AGREEMENT_TERMINAL` sentence.
- (b) Impl paths enumerated and read/grepped: `routes/agreements.py` `_check_not_terminal` definition (50-55) and all six call sites (164, 185, 208, 224, 250, 264) — each placed before the generic `ERR_INVALID_STATE` branch and after role/ownership/body-shape checks; `routes/cohorts.py:44-65` (cohort create under terminal agreement → `ERR_AGREEMENT_TERMINAL`; `DRAFT` → `ERR_INVALID_STATE`); `routes/billing.py:169-185` (outcome-report create, same pattern); full `ERR_INVALID_STATE` grep across `sessions.py`, `grants.py`, `billing.py`, `cohorts.py`, `commercial.py`, `instructors_venues.py` confirming every *non-agreement* terminal lockdown (session cancel/close/propose/confirm/release, program suspend/reopen/close, application submit/review/return/approve/deny/claim/mark_paid, invoice issue/void, cohort launch/cancel/credential/enroll, participant drop, assessment submit/approve/revise, instructor deactivate/reactivate) still surfaces `ERR_INVALID_STATE`.
- (c) Wording adjustments: scoped the exception explicitly to "a training agreement" so all non-agreement terminal lockdowns remain covered by the unchanged `ERR_INVALID_STATE` clause; contrasted only against `ERR_INVALID_STATE` (not against the whole pipeline) so earlier-priority checks (headers, role/ownership at `agreements.py:206-207,222-223`, 404, body-shape at `agreements.py:182-184`, `cohorts.py:44-53`, `billing.py:174-178`) stay governed by §2.8's "first failing check" rule; made no priority-reordering claim between items 5 and 6, since on a terminal agreement both conditions always co-fire and only the emitted `error_id` is observable.

File written: `workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-08-11T01:00:00.000Z

All 19 edits landed exactly as intended — all in-place, no new lines, sections, or paragraphs. The work is complete.

## Summary

**Files:** `workspace/PRD_FINALIZED.md` (339 lines / 55,453 chars) → `workspace/PRD_COMPLETED.md` (339 lines / 57,732 chars). Char delta: **+2,279**. 19 lines edited in place; zero lines added/removed; no new sections.

**Counts:** 15 ambiguity-pins, 4 mismatch-revisions (3 distinct mismatch behaviors, one of which — attendance-closure ownership — required revising two passages, §2.1 and §3.6).

**Changes (one bullet each):**

- §2.1 — revise — **mismatch** — attendance-closure ownership now compares against a `CONFIRMED` **or `COMPLETED`** assignment (was "confirmed" only, which would have made double-close return 403 instead of `ERR_ATTENDANCE_ALREADY_CLOSED`) — `implementation/routes/sessions.py:138-147`
- §2.3 — insert — ambiguity — pin pagination enforcement: `limit`<1, negative `offset`, or non-integer values rejected `ERR_INVALID_REQUEST`; `limit`>100 **clamped** to 100, not rejected — `implementation/util.py:155-180`
- §2.4 — revise — ambiguity — pin `version` starts at **1** at creation — `implementation/db.py:54-61`
- §2.7 — revise — **mismatch** — `committed_hours` is a running sum of session `hours` at those figures' precision (impl rounds hours to 6dp and the sum to 10dp; the "one decimal place" claim was wrong — `round_1dp`/`refresh_committed_hours` are dead code) — `implementation/util.py:74`, `services/calculations.py:224`
- §2.8 step 4 — insert — ambiguity — body-carried resource identifiers (`needs_assessment_id`, `campus_venue_id`, `venue_id`, `program_id`, `instructor_id`) must resolve to existing records, rejected `ERR_INVALID_REQUEST` at step 4 (i.e., before state checks) — `implementation/routes/agreements.py:89-98`, `grants.py:142-144`, `sessions.py:52-54,217-220`, `cohorts.py:48-53`
- §2.9 — revise — **mismatch** — venue-overlap rule was one-sided in prose (a literal reading forbade booking any earlier session); pinned the impl's symmetric buffer-extended intersection test with open boundaries — `implementation/routes/sessions.py:57-64`
- §2.9 — revise — ambiguity — `turnover_buffer_minutes` is **fixed** at 30 minutes (was "by default"; impl never accepts an override) — `implementation/routes/instructors_venues.py:110`
- §2.9 — insert — ambiguity — only `PLANNED`/`HELD` bookings block a venue; cancelled sessions free it — `implementation/routes/sessions.py:59`
- §3.2 — insert — ambiguity — same-employer `needs_assessment_id` rule rejected with `ERR_INVALID_REQUEST` — `implementation/routes/agreements.py:92-96`
- §3.3 — insert — ambiguity — duplicate program `code` rejected with `ERR_INVALID_REQUEST` — `implementation/routes/grants.py:64-65`
- §3.3 — insert — ambiguity — claim's final award reads the **most recently created** qualifying `FINAL` invoice — `implementation/services/calculations.py:152-159`
- §3.4 — insert — ambiguity — `max_cohorts` ceiling counts cohorts in **every** status, `CANCELLED` included — `implementation/routes/cohorts.py:64`
- §3.4 — insert — ambiguity — session `hours` = window length rounded to six decimal places — `implementation/routes/sessions.py:71`
- §3.4 — insert — ambiguity — planning a session is a schedule mutation of the cohort (refreshes `updated_at`, increments `version`) — `implementation/routes/sessions.py:86`
- §3.6 — revise — **mismatch** — close_attendance ownership admits `CONFIRMED` or `COMPLETED` assignments, enabling the `ERR_ATTENDANCE_ALREADY_CLOSED` double-close path — `implementation/routes/sessions.py:138-147`
- §3.6 — insert — ambiguity — the `CANCELLED`-session check (`ERR_INVALID_STATE`) fires **before** the ownership comparison — `implementation/routes/sessions.py:134-135`
- §3.6 — insert — ambiguity — attendance entries naming an `external_employee_ref` not on the roster are silently ignored — `implementation/routes/sessions.py:176-179`
- §3.6 — revise — ambiguity — closure **adds** each entry's hours to the participant's cumulative `attended_hours` (was "updates … from the payload") — `implementation/routes/sessions.py:180`
- §3.6 — insert — ambiguity — launch capacity gate covers the cohort's primary venue **and each session's venue** of kind `CAMPUS_LAB` — `implementation/routes/cohorts.py:141-149`
- §3.7 — insert — ambiguity — the variant gate is evaluated **before** the one-open-invoice rule (inverts a strict §2.8 step-5-before-step-6 reading) — `implementation/routes/billing.py:46-57`
- §3.7 — revise — ambiguity — an in-scope session with no `COMPLETED`/`CONFIRMED` assignment fails generation with `ERR_INVALID_STATE`; with several, the **earliest-created** supplies the instructor (was "exactly one required") — `implementation/services/calculations.py:69-79,98-106`
- §3.7 — insert — ambiguity — the grant-offset covering application is the **most recently created** in `APPROVED`/`CLAIMED`/`PAID` — `implementation/services/calculations.py:126-134`
- §3.7 — insert — ambiguity — voiding an `ISSUED` invoice leaves the agreement's `billing_status` unchanged — `implementation/routes/billing.py:148-162`
- §3.9 — insert — ambiguity — cancelling a session also mutates its cohort (version bump) and re-runs the §3.6 delivery-progression rule, so an `IN_PROGRESS` cohort can reach `DELIVERED` via a cancellation — `implementation/routes/sessions.py:123-126`, `services/lifecycle.py:92-104`

Everything else in the impl (quote tiers/uplift/floor, grant ledger math, match-score weights, cascades, sweeps, role table, endpoint table, error catalog, envelope shape, OCC endpoints) was already uniquely pinned by PRD_FINALIZED.md and verified line-by-line against the code — no changes needed there.

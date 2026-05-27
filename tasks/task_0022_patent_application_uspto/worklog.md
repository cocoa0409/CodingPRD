# Worklog — task_0022_patent_application_uspto

## Step 1: Create task directory — 2026-05-27T12:47:00Z

Created `tasks/task_0022_patent_application_uspto/workspace/`.

## Step 2: Generate scaffold — 2026-05-27T13:04:00Z

Task: task_0022_patent_application_uspto
Scenario: Patent Application Filing (Utility/Design/Provisional/PCT, USPTO fees by entity size, OA response, Continuation/CIP, maintenance fees)

SCAFFOLD.yaml counts:
  entities:         7   (Applicant, Application, OfficeAction, OfficeActionResponse, MaintenanceFee, FeePayment, PCTPhaseEntry)
  state_machines:   3   (Application, OfficeAction, MaintenanceFee)
  calculations:     8   (FILING_FEE, EXCESS_CLAIMS_FEE, ISSUE_FEE, EXTENSION_FEE, MAINTENANCE_FEE, PRIORITY_DATE, TERM_EXPIRATION, MICRO_ELIGIBILITY)
  validations:      21  (priority-ordered, categories: auth, existence, state, business_*)
  endpoints:        25  (incl. 2 test-driving: /_clock/set_current_utc, /_jobs/sweep-deadlines)
  errors:           20
  roles:            3   (Applicant entity_backed, USPTOExaminer opaque, USPTOAdmin opaque)
  concurrency_rules: 2  (OCC: issue-fee-stale-application, convert-provisional-stale-application)

SCAFFOLD_DIFFICULTY_DESIGN.yaml: 18 instances (9 rules × 2)
  dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade,
  priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency,
  resource_temporal_overlap, compensating_invariant — each 2 instances

SCAFFOLD_CORNER_DESIGN.yaml: 31 instances (27 active + 4 excluded_because stubs)
  entities=5, state_machines=7, calculations=3, validations=5, endpoints=1, rbac=3,
  cross_cutting_complexity_layers=2, errors=1 active + 4 excluded stubs

scaffold_lint.py: VERDICT — clean lint
  §1.5 endpoints declared: 25
  §1.1 entities declared:  7
  §1.8 instances scanned:  18
  §1.9 instances scanned:  27 (active)
  Calls scanned:           296

## Step 3: Copy INSTRUCTION.md — 2026-05-27T13:05:00Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-27T13:13:00Z

PRD generated successfully at `workspace/PRD.md`.

- Total lines: 241
- Total words: 5791
- Section headings:
  - 1. Introduction
  - 2. Global Specifications & System-Wide Principles (2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Resource Identity and Audit Fields, 2.5 Nested Path Resolution, 2.6 Money/Time/Precision, 2.7 Order of Validation, 2.8 Optimistic Concurrency Control, 2.9 Continuation/Conversion Independence, 2.10 Time-Driven Cascades)
  - 3. Business Logic & Workflows (3.1 Onboarding & MICRO test, 3.2 Filing, 3.3 Filing/Excess-Claim Fees, 3.4 Docketing & Examiner Cycle, 3.5 OA Response, 3.6 Successive OAs/Allowance/Abandonment, 3.7 Issue Fee & Issuance, 3.8 Maintenance Fees, 3.9 Provisionals & 12-month window, 3.10 PCT National Phase Entry, 3.11 Test Clock & Sweeper)
  - 4. Endpoint Definitions (25 endpoints, 4-column table)
  - 5. Error Code Catalogue (20 errors, 2-column table)

Hard Contracts:
- Field coverage: 51 required, 51 present, 0 missing — PASS
- Rule coverage: 21 validations / 2 OCC / 16 transitions / 8 calculations / 21 conditions / all side_effects / structured fields / sibling-branch symmetry — PASS
- Path purity (§3): 324 backtick tokens scanned, 0 `/` tokens, 0 bare HTTP-method tokens, 0 method+path combined — PASS

## Step 5: Generate unit tests — 2026-05-27T13:32:00Z

**Test files**: 12 (test_suite/conftest.py + test_01..test_12_*.py)
**Total test functions**: 63
**Queue A (Difficulty) tests**: 36 — every one of the 18 difficulty instances has exactly 2 tests
**Queue B (Corner) tests**: 27 — every one of the 27 non-stub corner instances has exactly 1 test
**Helper files** (9): __init__.py, types.py, api_client.py, api_errors.py, assertions.py, constants.py, factories.py, test_users.py, fixtures.py

**Coverage audit (machine-verified)**:
- All 18 difficulty instances → ≥2 tests each ✓
- All 27 non-stub corner instances → ≥1 test each ✓
- All 4 `excluded_because:` corner stubs → 0 tests (correctly not translated) ✓
- All `Design: …` tags resolve to a real instance.name in source YAML ✓

**Skipped instances**: None. Every non-stub design-index instance has verbatim PRD prose stating its rule and uniquely pinning the outcome, so all were translated.

**PRD citation discipline**: 12 PRD-citation grep spot-checks confirmed every cited sentence appears verbatim in PRD.md.

## Step 6: Generate implementation — 2026-05-27T13:32:00Z

- Total source files: 21 (.py) + start.sh + requirements.txt
- Top-level: `start.sh` (bash launcher, execs `python3 app.py` on `$PORT` default 10000, binds 0.0.0.0), `requirements.txt` (Flask==3.0.3), `app.py` (entry point — blueprint registration + APIError/404/405/400/Exception handlers), `db.py` (in-memory _Store with reset on boot, logical clock override, US{seq} patent number mint, ISO8601-with-3-fractional helpers), `errors.py` (APIError + 20-entry catalog), `response.py` (meta/response_type/data envelope per PRD §2.2, pagination fields embedded in `meta` for list responses), `middleware.py` (X-User-Role/X-User-ID extraction + role gating; resolves Applicant to applicant table per §2.1).
- routes/ (8 blueprints): applicants, applications, office_actions, office_action_responses, maintenance_fees (read-only), fee_payments, pct_phase_entries, system (test-driving `/_clock` and `/_jobs/sweep-deadlines`).
- services/: calc.py (Decimal+ROUND_HALF_UP for FILING_FEE, EXCESS_CLAIMS_FEE with discount-then-sum-then-round, ISSUE_FEE, EXTENSION_FEE, MAINTENANCE base/surcharge rounded independently, micro_eligible predicate), dateutil.py (calendar add_months/add_years with last-day-of-month clamping), serialize.py (entity→wire), pagination.py (limit/offset parsing, sort by created_at asc), body.py (strict typed body parsers), application_svc.py (priority_date, term_expiration_date, recompute_total_fees, version bumpers).
- Endpoints registered: 25 (24 from scaffold §1.5 + Flask static).
- State machine coverage: Application (FILED→AWAITING_EXAMINATION→OFFICE_ACTION_OUTSTANDING↔RESPONSE_FILED→ALLOWED→ISSUED, plus CONVERTED/ABANDONED/EXPIRED terminals); OfficeAction (OUTSTANDING→RESPONDED/EXPIRED/WITHDRAWN); MaintenanceFee (PENDING→PAID/LAPSED). Sweeper handles all 3 system-driven cascades (OA expiry→ABANDONED, PROVISIONAL 12-mo expiry, MaintenanceFee grace lapse→EXPIRED with version bumps on every cascaded row).
- OCC: `expected_application_version` required on pay-issue-fee and convert-provisional; mismatch → ERR_STALE_VERSION (412).
- Validation priority order honored (auth→existence→state→business). Single-outstanding OA enforced (priority 20). NoA-from-RESPONSE_FILED admitted (per scaffold's RESPONSE_FILED→OFFICE_ACTION_OUTSTANDING transition accepting NOTICE_OF_ALLOWANCE; jumps directly to ALLOWED in the application).
- Smoke-tested end-to-end: applicant create → file → docket-without-fee 409 → filing fee → docket → OA → response → NoA → pay-issue-fee → 3 maintenance fees auto-generated with US1 patent number. PROVISIONAL→UTILITY conversion preserves parent's filing_date as child's priority_date. PCT singleton enforcement returns ERR_PCT_PHASE_ENTRY_DUPLICATE.
- No seeding at boot — store starts empty on every `start.sh` invocation (verified).
- Implementation notes: (1) Python 3.9 compatibility — avoided PEP 604 `X | None` and `dict[K,V]` syntax; (2) `payment_category=EXTENSION` standalone fee_payments lookup the most recent OAResponse on the application to derive expected_amount, since no other anchor exists in the scaffold; (3) `payment_category=PCT_NATIONAL_PHASE` reuses FILING_FEE for the type since the scaffold mentions the category but defines no separate constant table.

## Step 7: Test+fix loop — 2026-05-27T14:01:00Z

All 8 rounds passed with 63/63 tests. Clean sweep achieved.

**Iterations run**: 3 (initial sweep + 2 fix-rerun cycles)

**Tests deleted**: 0

**Fixes applied to `test_helpers/`**: none (no fixture bugs encountered)

**Fixes applied to `test_suite/`** (test bugs per STEP 2):
- `test_suite/test_12_state_transitions_and_invariants.py::test_list_applications_returns_array_envelope_with_meta` — fixture used `title="A1"/"A2"/"A3"` violating PRD §3.2's 3-character minimum; changed to `"App1"/"App2"/"App3"`.
- `test_suite/test_03_fees_and_calculations.py::test_two_month_extension_small_entity_exact_amount` — fixture posted EXTENSION fee BEFORE OAR existed; PRD §3.5 says the EXTENSION fee must match the OAR's `extension_months_requested`, so the OAR must exist first. Reordered: create OAR first, then post fee payment.
- `test_suite/test_07_cross_entity_state.py::test_second_response_against_already_responded_oa_rejected_invalid_state` — assertion asserted `ERR_INVALID_STATE`, but PRD §2.7 explicitly classifies `RESPONDED` as terminal for OfficeAction → `ERR_TERMINAL_STATE`. Updated assertion + docstring.
- `test_suite/test_07_cross_entity_state.py::test_maintenance_payment_on_expired_application_rejected` — assertion asserted `ERR_INVALID_STATE` based on PRD §3.8's informal "invalid state" English; PRD §2.7 is authoritative and classifies `EXPIRED` as terminal for Application → `ERR_TERMINAL_STATE`. Updated assertion + comment.

**Fixes applied to `implementation/`** (root cause: business logic ignored the logical clock):
- `implementation/db.py` — annotated `utcnow_dt()` as wall-clock-only (used only by the response envelope).
- `implementation/services/application_svc.py` — `bump_application` / `bump_office_action` / `bump_maintenance_fee` now stamp `updated_at` from `db.current_utc_dt()` instead of wall clock.
- `implementation/routes/applicants.py` — `created_at` / `updated_at` use `db.current_utc_dt()`.
- `implementation/routes/applications.py` — `filing_date`, `created_at`, `updated_at`, conversion's new-row stamps use `db.current_utc_dt()`; same for pay-issue-fee's `issue_date`.
- `implementation/routes/office_actions.py` — OA `issue_date`, `shortened_due_date`, `maximum_due_date`, `created_at` derived from `db.current_utc_dt()`.
- `implementation/routes/office_action_responses.py` — `response_filed_at` and timeliness check use `db.current_utc_dt()`.
- `implementation/routes/fee_payments.py` — `FeePayment.created_at` uses `db.current_utc_dt()`; removed the implementation-extra `amount_cents <= 0` guard (PRD never requires positive amounts, only exact match), which was masking the higher-priority `ERR_MAINTENANCE_WINDOW_CLOSED` check in `test_pay_maintenance_before_window_open_returns_window_closed_not_fee_mismatch`.
- `implementation/routes/pct_phase_entries.py` — `created_at`, `updated_at`, and late-check `now` use `db.current_utc_dt()`.

**Root cause findings**:
- The single dominant bug: business-route code stamped dates from wall clock (`utcnow_dt()`) rather than the logical clock (`db.current_utc_dt()`) the PRD pins via `/_clock/set_current_utc`. PRD §2.6 declares one logical clock that "all deadline comparisons read from", and §3.2 says `filing_date` equals "the server's current UTC instant" — which under §2.6 IS the logical clock. This single category of error caused 18 of 20 initial failures.
- Two test-vs-PRD assertion errors classified `RESPONDED` (OA terminal) and `EXPIRED` (Application terminal) as `ERR_INVALID_STATE` instead of `ERR_TERMINAL_STATE` per PRD §2.7's authoritative enumeration.
- One test fixture ordering bug (EXTENSION fee posted before OAR existed).
- One test fixture string length violation (`"A1"` < 3 chars).
- One implementation-extra validation (`amount_cents > 0`) short-circuited an earlier priority check.

Final state: 63 passed / 0 failed across 8 parallel rounds, deterministic.

## Step 8: Finalize PRD — 2026-05-27T15:17:00Z

*Re-run under the new HARD SCOPE: every PRD edit must trace to a specific item in `<step_7_diff>`. Prior PRD_FINALIZED.md was deleted; subagent regenerated fresh per the new spec (workspace files readable; SCAFFOLD*.yaml and worklog.md forbidden).*

Same line count (the edit added text inline to an existing paragraph). Done.

**Line counts:** PRD.md = 241 lines; PRD_FINALIZED.md = 241 lines; delta = 0 lines (+0.0%). The single edit added prose inline to an existing paragraph (§3.5).

**Changes:**

- §3.5 (Responding to an Office Action) — revise — Pinned the implementation's chosen semantics for a standalone `POST /fee-payments` with `payment_category=EXTENSION`: it computes the expected `amount_cents` by referencing the most-recently-created `OfficeActionResponse` on the application and uses its `extension_months_requested`, rejecting with `ERR_FEE_AMOUNT_MISMATCH` when none exists (which forces OAR-before-EXTENSION ordering) — `implementation/routes/fee_payments.py:72-96` (`_expected_amount` EXTENSION branch).

**Step 7 items deliberately NOT patched (already determined by PRD as written or not a PRD-silence):**

- Title min 3 chars — PRD §3.2 already says "3 to 500 characters".
- `RESPONDED` → `ERR_TERMINAL_STATE`, `EXPIRED` → `ERR_TERMINAL_STATE` — PRD §2.7 already enumerates the authoritative terminal sets and the corresponding error class.
- Logical-clock stamping of `filing_date`/`updated_at`/`response_filed_at` etc. — PRD §2.6 already pins a single logical clock that "all deadline comparisons read from", and §3.2 anchors `filing_date` to "the server's current UTC instant" which is that clock; this was a pure impl bug, not a PRD-silence.
- Removed `amount_cents > 0` extra guard — PRD never required positive amounts; removing the impl-extra brings impl back to PRD's silence (lenient), so no PRD edit needed.
- EXTENSION-fee-before-OAR fixture-ordering test bug — directly addressed by the §3.5 edit above.

## Step 9: Complete PRD scan — 2026-05-27T15:24:00Z

Same line count (all in-paragraph edits), char delta +2155.

**Source vs PRD_COMPLETED.md:**
- Source: `PRD_FINALIZED.md` (existed, so used as base per Method step 0)
- Lines: 241 → 241 (unchanged; all edits are in-paragraph)
- Chars: 42,411 → 44,566 (Δ = +2,155 chars)

**Counts:** 10 edits total — 6 ambiguity pins, 4 mismatch revisions.

**Per-change log:**

- §2.1 — revise — mismatch — PRD said "ownership checks compare the resource's foreign-key field to X-User-ID"; impl performs no ownership check beyond the role gate. Revised to state authentication only requires X-User-ID to resolve to an Applicant — `middleware.py:29-30`.
- §2.2 — insert — ambiguity — `api_request_timestamp` clock source unspecified; pinned to host's real wall clock, independent of logical clock — `response.py:18-19` / `db.py:9-14,27`.
- §2.3 — insert — ambiguity — list sort tiebreaker unspecified; pinned to `id` ascending — `services/pagination.py:46`.
- §3.1 — revise — mismatch — PRD said LARGE/SMALL applicants' year/income fields are "ignored if supplied"; impl still range-checks them. Revised to reflect parsing + range-check with ERR_INVALID_REQUEST — `routes/applicants.py:26-39, 56-57`.
- §3.3 — insert — ambiguity — PRD said "any other combination is malformed" (silent on code); pinned to ERR_INVALID_REQUEST (400). Also added the `application_id` mismatch → ERR_APPLICATION_NOT_FOUND and `window_number`-vs-category mismatch → ERR_INVALID_REQUEST rules — `routes/fee_payments.py:131-156, 158-162`.
- §3.4 — insert — ambiguity — docket-without-filing-fee error code (ERR_INVALID_STATE) and PROVISIONAL-docket error code (ERR_INVALID_STATE) were unpinned; pinned — `routes/applications.py:196-200, 208-212`.
- §3.5 — revise — mismatch — PRD said an untimely response is recorded with `response_status=REJECTED_LATE`; impl never persists such a row, rejects the create with ERR_INVALID_STATE. Revised — `routes/office_action_responses.py:99-113`.
- §3.5 — revise — mismatch — PRD said an extension purchase requires a same-transaction EXTENSION FeePayment; impl decouples and only records `extension_fee_cents` on the response itself. Revised — `routes/office_action_responses.py:115-123, 133`.
- §3.9 — insert — ambiguity — non-PROVISIONAL/terminal/non-FILED conversion source error codes were silent; pinned (ERR_INVALID_STATE for non-PROVISIONAL or unexpected non-FILED; ERR_TERMINAL_STATE for ABANDONED/EXPIRED/ISSUED) — `routes/applications.py:338-361`.
- §3.10 — insert — ambiguity — both the strictly-before-now check and the `application_type != PCT_NATIONAL` check were silent on error codes; pinned to ERR_INVALID_REQUEST and ERR_INVALID_STATE respectively — `routes/pct_phase_entries.py:40-44, 56-61`.


# Worklog — task_1226_retirement_plan_loan_hardship_withdrawal

## Step 1: Create Task Directory — 2026-08-12T01:54:00.000Z

Task directory pre-assigned by the pipeline invocation: `tasks/task_1226_retirement_plan_loan_hardship_withdrawal/` with `workspace/` subdirectory. Auto-index scan skipped per invocation instructions. Directory verified present on disk. Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-12T02:42:00.000Z

All three scaffold artifacts are generated, validated, and lint-clean. (Note: `worklog.md` and `workspace/` in that directory predate this run and were left untouched.)

## Summary — task_1226_retirement_plan_loan_hardship_withdrawal

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1226_retirement_plan_loan_hardship_withdrawal/`):
- `SCAFFOLD.yaml` (§1.0–§1.7; no difficulty/corner keys) — 1,004 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`) — 673 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`) — 1,132 lines

**Counts**
- Entities: **12** (Plan, Participant, ContributionElection, Loan, LoanInstallment, PayrollRemittance, HardshipRequest, HardshipDocument, ApprovalTask, SuspensionRecord, TaxEvent, AuditEvent)
- State machines: **10** — Loan carries parallel dimensions (lifecycle × delinquency, with cycles DISBURSED⇄REPAID and CURRENT⇄DELINQUENT); HardshipRequest and ApprovalTask have document-request cycles; ContributionElection is cyclic ACTIVE→SUSPENDED→ACTIVE
- Endpoints: **46** (incl. test-driving `POST /_clock/set_current_utc` with the mandatory fixed default 2026-05-01T00:00:00Z)
- Errors: **31** — all referenced by validations/transitions and exercised by at least one design instance
- Calculations: **8**; validations: 12 priority rows; concurrency rules: 2 (OCC on Loan.version for schedule rebuild, Plan.version for policy update)
- Difficulty instances: **19** (all 9 rules × ≥2; combinatorial_formula has 3 covering modes (a) nested min/max loan-maximum, (b) pinned rounding-order amortization, (c) pinned evaluation-order hardship gross-up)
- Corner instances: **58 total = 49 active + 8 `excluded_because` stubs** citing §1.8 instances

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (521 calls scanned)

**Notable design decisions**
- Archetype: compliance/audit primary, ledger-reconciliation secondary; segregation-of-duties role model (same X-User-ID cannot decide two approval steps of one subject, even across roles)
- IRC-true mechanics: 50%-of-vested vs $50k-cap-with-trailing-12-month-high-water-mark loan limit; quarter-following-quarter cure window; deemed vs offset taxable-amount variants differing by interest cutoff (verified literals: 1,014,625c vs 1,011,481c on identical loans)
- Depth-4 deem cascade (clock → DEEMED → TaxEvent → participant YTD + 12-month eligibility lock → gated loan request) and depth-3 termination offset cascade
- Amortization literals computed via Decimal/ROUND_HALF_UP: 1,000,000c/500bps/12mo → payment 85,607c, final installment 85,612c absorbing remainder, principal sums exactly to 1,000,000c; ACT/360 vs 30/360 first-installment interest 4,306c vs 4,167c; rebuild of 918,560c over 6 months → 155,334c; hardship NET 800,000c → gross 1,006,250c with the fee tier boundary at provisional gross exactly 1,000,000c
- Remittance waterfall is atomic (overpayment beyond the scheduled balance rejected), tie-breaks pinned to created_at/due_date/installment_number — never id
- One mid-design correction worth noting: the refinance-lookback difficulty instance was rebuilt around a 2-month plan lookback because a 12-month jump would have fired the DEEMED cascade first, masking the lookback error

## Step 3: Copy Shared Files — 2026-08-12T02:43:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1226_retirement_plan_loan_hardship_withdrawal/workspace/INSTRUCTION.md (1,424 bytes).

## Step 4: Generate PRD — 2026-08-12T02:55:00.000Z

The PRD is written and verified on disk. Here is the summary.

## Generated Artifact

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1226_retirement_plan_loan_hardship_withdrawal/workspace/PRD.md` — 311 lines, 59 KB.

**Section list:**
- §1 Introduction (2 paragraphs: regulatory business context + system's interlocking obligations)
- §2 Global Specifications — 11 subsections: 2.1 User & RBAC (5 roles with `identity:` prose translations), 2.2 API Response Structure (emitted byte-verbatim from the fixed block), 2.3 Pagination (`limit` default 10/min 1/max 100, `offset` default 0, `created_at` ascending), 2.4 Common Resource Properties (incl. explicit absence of `updated_at`/`version` on LoanInstallment, HardshipDocument, AuditEvent), 2.5 Monetary Representation/Rounding (integer cents, basis points, round half up), 2.6 The Logical Clock (startup default `2026-05-01T00:00:00Z`, `to_iso8601`/`current_utc`, three scheduled-transition families), 2.7 Plan Posture gate, 2.8 Validation Cascade (all 12 priority groups in explicit order, incl. the priority-2 ownership-vs-not-found nuance and priority-11 internal ordering), 2.9 OCC (both rules, `ERR_STALE_VERSION` 412), 2.10 Nested Resource Retrieval (7 resource-specific 404s), 2.11 Append-Only Audit Trail (all 21 action names).
- §3 Business Logic — 9 subsections organized by lifecycle/process: plan setup & policy, participant enrollment & termination-offset cascade, elections & suspension windows, loan origination & approval chain, disbursement & amortization (THIRTY_360 vs ACT_360 variants at equal density), remittance waterfall & reversal, delinquency/cure/deemed distribution, refinancing, hardship end-to-end (NET vs GROSS gross-up at equal density, substantiation, payment cascade, tax-event reporting).
- §4 Endpoint Definitions — 46-row table, 4 columns only (Method, Path, Description, Authorized Roles).
- §5 Error Code Catalogue — 31-row table, 2 columns only (Error ID, HTTP Status).

**Notable choices:** constants embedded in business prose with both cents and dollars (e.g., "5,000,000 cents (fifty thousand dollars)", fee tier "5,000 / 7,500 cents at a 1,000,000-cent threshold", refinance fee "10,000 cents"); all formulas translated to operator-free prose passing the reconstruction test (annuity payment, high-water-mark lookback with `created_at` tie-break, quarter-end cure deadline, dual DEEMED/OFFSET tax cutoffs, pinned NET gross-up order); §3 uses only state-transition/role-verb framing — zero paths or HTTP methods.

**Hard Contract Reports:**
```
Field coverage check:
- entities[].fields + endpoint inputs + query/path params: 93 required, 93 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] priority cascade: 12 checked, 12 expressed in order, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write op + expected_*_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 35 checked, 35 fully expressed (incl. termination/deemed/pay/refinance cascade links), 0 missing
- calculations[]: 8 checked, 8 fully expressed with constants, precision, variants, 0 missing
- validations[] conditions: all 31 error IDs matchable to prose triggers, 0 missing
- endpoints[].side_effects / applies_to: all expressed (suspension-overlap's 3 scopes enumerated), 0 missing
- entities[].fields[] structured content (defaults, initial values, array shapes): reconstructible, 0 missing
- sibling-branch symmetry: NET/GROSS, THIRTY_360/ACT_360, DEEMED/OFFSET, APPROVE/REJECT/REQUEST_DOCS — equal density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 573
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-12T03:12:00.000Z

## Summary

**Task 1226 — Retirement Plan Loan & Hardship Withdrawal: test generation complete.**

### Coverage
- **98 test functions** across 16 test files in `/home/ubuntu/github/CodingPRD/tasks/task_1226_retirement_plan_loan_hardship_withdrawal/test_suite/`
- **Queue A (Difficulty):** 19/19 instances covered, each with exactly 2 tests = **38 tests**
- **Queue B (Corner):** 49/49 non-stub instances covered, each with ≥1 test = **60 tests**
- **Stubs skipped (not translated):** all 8 instances under `Corner/errors/*` carry `excluded_because` pointers to difficulty instances; each pointer was verified to resolve to a real Difficulty instance
- **No instances dropped for PRD-silence** — every non-stub instance passed the two-condition PRD-first filter

### test_helpers/ (9 files, all lint-clean)
- `__init__.py` — barrel export (framework + PRD-specific)
- `types.py` — 12 entity TypedDicts; `common_fields: false` append-only entities (LoanInstallment, HardshipDocument, AuditEvent) omit `updated_at`/`version`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (33 endpoints); `Connection: close` header for per-test-server isolation
- `api_errors.py` — `ApiErrorId` enum with all 31 error IDs + HTTP map, registered with framework
- `assertions.py` — per-entity assert functions, common-fields vs append-only shape split, hardship arithmetic invariant
- `factories.py` — payload factories for every entity
- `constants.py` — IRC cap, fee tiers, canonical 1M/500bps/12mo schedule numbers, clock startup default
- `test_users.py` — `TEST_USERS` shared constants + `make_participant_headers` (entity-backed) + per-operator builders
- `fixtures.py` — tiered composite fixtures: `create_plan`, `enroll_participant`, `setup_plan_and_participant`, `request_loan`, `approve_loan_fully`, `setup_disbursed_loan`, `setup_repaid_loan`, `create_hardship`, `upload_document`, `approve_hardship_fully`, `setup_paid_hardship`, `set_clock`

### test_suite/ (16 files + conftest.py)
- test_01 envelope/listing, test_02 plan/participant/audit, test_03 RBAC/auth, test_04 loan request chain + policy snapshot, test_05 hardship create gates, test_06 amortization schedule, test_07 loan approval decisions, test_08 loan amount limits, test_09 remittance waterfall, test_10 delinquency/deemed/offset, test_11 refinance, test_12 OCC, test_13 hardship gross-up, test_14 hardship approval cycle, test_15 hardship payment cascade, test_16 plan posture + consistency

### Lint status
- `python3 -m py_compile` on all `test_helpers/*.py` and `test_suite/*.py` — **clean**
- PRD verbatim citation audit (every docstring's PRD quote contains an ≥8-word substring that survives literal grep against `workspace/PRD.md`) — **98/98 pass**
- Every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<instance.name>` or `Design: Corner/<section>/<instance.name>` line, verbatim from the source YAML — **0 untagged, 0 dual-tagged, 0 dangling tags**

### Skipped instances
None beyond the 8 declared `excluded_because` stubs in the corner design (all in the `errors` section, all owning difficulty instances resolved and translated).

## Step 6: Generate Implementation — 2026-08-12T03:12:00.000Z

Done. Final summary:

## Summary

Built a complete Python + Flask implementation for the retirement plan loan & hardship withdrawal task at `/home/ubuntu/github/CodingPRD/tasks/task_1226_retirement_plan_loan_hardship_withdrawal/workspace/implementation/`.

### File list with line counts (23 source files, 2,789 total lines)

```
10  start.sh
 1  requirements.txt
66  app.py
30  db.py
61  errors.py
48  response.py
59  middleware.py
50  clock.py
22  services/audit.py
359 services/calculations.py
312 services/state.py
98  services/util.py
 0  services/__init__.py
217 routes/plans.py
277 routes/participants.py
353 routes/loans.py
247 routes/remittances.py
299 routes/hardship.py
179 routes/approval_tasks.py
 48 routes/tax_events.py
 22 routes/suspensions.py
 31 routes/clock.py
 0  routes/__init__.py
```

### Route coverage

46 (method, path) route pairs registered — matches the SCAFFOLD endpoint table exactly (no missing, no extras). The scaffold's `endpoints` list contains 46 rows across plans (11), participants (7), loans (10), remittances (3), hardship (8), approval-tasks (2), tax-events (3), suspension-records (1), and the test-driving clock (1).

### Boot verification

- `start.sh` honors `PORT` env var, binds `0.0.0.0`, runs in foreground via `exec python3 app.py`, and guards `pip install` behind `if ! python3 -c "import flask"` so per-test reboots don't re-install.
- Fresh-process boot verified on port 18734: server came up in <2s, returned `ERR_PLAN_NOT_FOUND` for an unknown plan id, and created a new plan successfully — confirming the store starts empty with no seeding.
- End-to-end smoke flows all passed:
  - Loan request → chain approval (PlanSponsor then RecordkeeperAdmin) → disburse → amortization schedule (85607 scheduled payment for 1,000,000 @ 500bps over 12mo THIRTY_360) → clock advance marks MISSED → cure via remittance → DELINQUENT→CURRENT → later advance past cure deadline → DEEMED → LOAN_DEEMED TaxEvent → 12-month eligibility lock enforced (`ERR_LOAN_ELIGIBILITY_LOCKED`).
  - Hardship create (NET semantics: 500000 net → gross 631250, withholding 126250, fee 5000) → substantiation gate (`ERR_SUBSTANTIATION_INCOMPLETE` without docs) → doc upload → approve → pay → SuspensionRecord 2027-08-01→2028-02-01 → contribution_status SUSPENDED → `ERR_SUSPENSION_OVERLAP` on new loan → `ERR_SUSPENSION_STILL_ACTIVE` on early restart → clock advance → suspension EXPIRED → restart succeeds → participant termination cascade flips election to TERMINATED.
  - Plan freeze/unfreeze posture gates, OCC scaffolding, audit trail appends per mutation — all verified through the smoke runs.

### Implementation notes

- Storage is in-memory dicts in `db.py`, keyed by id, with no seeding at startup.
- All monetary arithmetic uses `Decimal` with `ROUND_HALF_UP`; no floats.
- Logical clock starts at exactly `2026-05-01T00:00:00Z`, advanced only via `POST /_clock/set_current_utc`, and drives MISSED marking, cure deadline fixing, DEEMED cascade, and suspension EXPIRED transitions.
- OCC fields `expected_loan_version` (schedule rebuild) and `expected_plan_version` (policy update) return `ERR_STALE_VERSION` / 412 on mismatch.
- Validation cascade follows the PRD priority order: auth → role/ownership → segregation-of-duties → schema → existence → from-state → OCC → plan posture → substantiation → temporal → business constraints (pinned sub-order) → fiscal.
- Response envelope is exactly `{meta: {api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}, response_type, data}`; timestamps are ISO 8601 UTC with three fractional digits and `Z`.

(Orchestrator note: independent route-parity re-check after Step 6 exit confirmed 46/46 (method, path) pairs in the Flask app match SCAFFOLD.yaml endpoints — none missing, none extra.)

## Step 7: Run Tests and Iterate — 2026-08-12T03:36:00.000Z

## Summary

**Iterations run:** 2 sweeps (initial diagnostic sweep: 83-84/98 per round, 15-test union of failures; final sweep after fixes: 98/98 × 8 rounds).

**Tests deleted:** None. Every failing test traced to a verbatim PRD rule with a uniquely derivable outcome.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1226_retirement_plan_loan_hardship_withdrawal/test_suite/test_08_loan_amount_limits.py` — `test_trailing_12m_high_water_mark_reduces_irc_cap`: the setup disbursed and fully repaid a loan all on the startup clock day (2026-05-01), so the PRD's closed lookback window ("the day twelve calendar months before today **through yesterday**") legitimately contained zero outstanding principal and a PRD-faithful implementation correctly answered 5,000,000, not 3,000,000. Repaired the setup (STEP 2, test-setup bug): disburse at 2026-05-01, `set_clock("2026-05-10")`, repay, `set_clock("2026-05-11")`, then read eligibility — the window [2025-05-11 .. 2026-05-10] now contains nine 2,000,000c end-of-day totals, so the asserted `3_000_000` follows from the PRD-literal computation. Assertion unchanged; added `set_clock` to the test_helpers import list.

**Fixes applied to `implementation/`:**
- `workspace/implementation/clock.py` — added `format_date_iso(dt)`: renders clock-derived date stamps at date granularity (`YYYY-MM-DDT00:00:00Z`), per PRD §2.5 ("Date-valued quantities such as deadlines and suspension windows are computed at date granularity") and §2.6 ("the logical clock reads exactly `2026-05-01T00:00:00Z`"). `created_at`/`updated_at`/`api_request_timestamp` keep the PRD-pinned three fractional digits.
- `workspace/implementation/services/util.py` — `quarter_last_day` now returns midnight of the quarter's last day instead of `23:59:59.999` (date-granular cure deadline; comparison semantics verified equivalent under date-granular operands). Added `date_iso()` helper.
- `workspace/implementation/services/state.py` — `disbursed_on`, `deemed_on`, `cure_deadline_on`, `event_date`, `loan_eligibility_locked_until` switched to `date_iso`.
- `workspace/implementation/services/calculations.py` — installment `due_date` switched to `date_iso`.
- `workspace/implementation/routes/{participants,hardship,remittances,clock}.py` — `terminated_on`, `paid_on`, `starts_on`, `ends_on`, `retained_until`, reversal-path `cure_deadline_on`, and `current_utc` switched to `date_iso`.
- `workspace/implementation/routes/participants.py::_terminate_participant` — real implementation bug: the offset cascade closed PENDING/MISSED installments *before* calling `taxable_amount_for_loan`, and `accrued_unpaid_interest_through` only sums PENDING/MISSED rows, so LOAN_OFFSET taxable amounts were missing all accrued interest (1,000,000 vs correct 1,011,481). Reordered: compute taxable over pre-close statuses first (the only reading under which PRD §3.7's deemed-vs-offset divergence sentence is coherent), then close.
- `workspace/implementation/routes/{plans,loans,remittances,suspensions,tax_events,hardship,participants}.py` — replaced `(created_at, id)` sort keys with stable `created_at`-only sorts. Under the fixed logical clock all entities share one `created_at`, and the random-UUID tie-break made listing order nondeterministic — the source of the flaky `test_audit_events_immutable_and_append_only` failure (rounds 5/7 only). Stable sort preserves insertion (append) order, the faithful reading of PRD §2.11's "ascending `created_at`" for an append-only trail.

**Final sweep:** all 8 `results.{1..8}.json` files present and non-empty; every round reports `passed == total` (98/98, 0 failed, 0 errors).

(Orchestrator verification: independently re-read all 8 results files after subagent exit — 98/98 passed, 0 failed in every round.)

## Step 8: Finalize PRD — 2026-08-12T03:46:00.000Z

All edits verified against the full implementation. Final state:

**Line counts:** `PRD.md` 311 lines, `PRD_FINALIZED.md` 311 lines — 4 lines modified in place, 0 added/removed (0% line-count delta; 4 of 311 lines = 1.3% of lines touched).

## Changes (one bullet each)

- **§2.3 — revise** — Appended a tie-break clause to the list-ordering rule: resources sharing an identical creation timestamp retain relative creation order (stable sort, no secondary key such as `id`) — `implementation/routes/plans.py:170-171` (`_sorted_created`), and the same single-key pattern at `loans.py:127,338`, `remittances.py:173`, `hardship.py:121,192,293`, `tax_events.py:21`, `suspensions.py:18`.
- **§2.5 — revise** — After "computed at date granularity," inserted the rendering pin: clock-derived date stamps (`disbursed_on`, `deemed_on`, `cure_deadline_on`, `terminated_on`, `paid_on`, `starts_on`, `ends_on`, `retained_until`, `event_date`, installment `due_date`, `loan_eligibility_locked_until`, clock-endpoint `current_utc`) render as ISO 8601 UTC at whole-second precision with no fractional digits; `created_at`, `updated_at`, `decided_on`, `effective_on`, `api_request_timestamp` keep three fractional digits — `implementation/clock.py:35-43` (`format_date_iso`), `services/util.py:100-103`, `services/state.py:136,157,189,263,287`, `services/calculations.py:77`, `routes/participants.py:73`, `routes/hardship.py:233,242,243,266`, `routes/remittances.py:237`, `routes/clock.py:31`.
- **§2.11 — revise** — Audit trail listing: same-`created_at` events appear in append order — `implementation/routes/plans.py:215` + `services/audit.py:9-22`.
- **§3.2 — revise** — Termination offset cascade: added same-`created_at` tie-break ("order they were created") and pinned that the `LOAN_OFFSET` taxable amount's accrued-interest sum is evaluated over installment statuses standing at the offset transition, *before* the cascade closes the remaining `PENDING`/`MISSED` installments — `implementation/routes/participants.py:80-97` (sort at :80, `taxable_amount_for_loan` at :89 before the close loop at :91-93), with the status filter at `services/calculations.py:309-318`.

**No edit for the `test_08` item** — Step 7 explicitly classified it as a test-setup bug; the PRD's closed lookback window ("the day twelve calendar months before today through yesterday") already uniquely determined the outcome. The `quarter_last_day` midnight change is representation-only (comparison semantics equivalent) and is covered by the §2.5 rendering pin.

## Per-edit pre-edit search log

**Edit §2.3 (stable sort)**
- (a) Subject: ordering of list endpoints.
- (b) Enumerated via `grep -rn "sorted\|sort(" implementation/routes/`: all 13 `created_at`-keyed listings (`plans.py:170-215`, `loans.py:127,338`, `remittances.py:173`, `hardship.py:121,192,293`, `tax_events.py:21`, `suspensions.py:18`) use single-key stable sorts; the `installment_number` (`loans.py:327`) and `step_order` (`loans.py:349`, `hardship.py:281`) listings use distinct PRD-pinned keys and fall under "unless otherwise specified"; the internal waterfall sort (`calculations.py:126-132`) and high-water same-day tie-break (`calculations.py:249`) are computations, not list endpoints, so the sentence makes no claim about them.
- (c) Wording scoped to "list endpoints" and "creation timestamp" so non-created_at-keyed listings and internal sorts are not mis-described.

**Edit §2.5 (date-stamp rendering)**
- (a) Subject: string rendering of every clock-derived date/timestamp field.
- (b) Enumerated via `grep -rn "date_iso\|now_iso()\|format_iso"`: twelve `date_iso` field sites (listed above) vs. five three-fractional-digit fields (`created_at`, `updated_at`, `decided_on` at `approval_tasks.py:129`, `effective_on` at `participants.py:189`, `api_request_timestamp` at `response.py:12`, audit `created_at` at `audit.py:12`); client-supplied `pay_date` stored verbatim (`remittances.py:144`). Cross-checked PRD §2.2, §2.4, §2.6, §3.3, §3.5, §3.7, §3.9 for conflicting rendering claims — none.
- (c) Used "whole-second precision, with no fractional digits" rather than "midnight" because `format_date_iso` preserves a non-midnight time-of-day (e.g. `current_utc` after `set_clock("...T13:45:00Z")`, or a client-supplied `terminated_on` re-rendered at `participants.py:73`); the midnight form is given only as the canonical-reading example. `pay_date` deliberately left unmentioned (client-verbatim, not clock-derived).

**Edit §2.11 (audit append order)**
- (a) Subject: audit-trail listing order under identical `created_at`.
- (b) `services/audit.py:9-22` (append-only insertion), `routes/plans.py:211-217` (stable `created_at`-only sort); confirmed no update/delete path for audit events anywhere.
- (c) None — clause is a restatement of the §2.3 rule specialized to the trail, consistent with both.

**Edit §3.2 (offset cascade order + tie-break)**
- (a) Subject: `LOAN_OFFSET` taxable-amount evaluation timing vs. installment closing, and multi-loan processing order.
- (b) `routes/participants.py:70-119` (stable sort :80; OFFSET at :82; taxable at :89; close loop :91-93; `create_tax_event` :95; lock :97); shared formula `calculations.py:309-323`; other formula consumers verified unaffected by the wording: deemed path (`state.py:284-292`, installments never closed there), refinance (`calculations.py:356-359` invoked at `loans.py:211`, before old-loan closing at `loans.py:219-221`), stored-field recompute (`state.py:326-327`). Ground-truth test `test_10::..._loan_offset` asserts 1,011,481, which is only reachable with pre-close statuses.
- (c) Scoped the evaluation-timing clause to "its accrued-interest sum" within the offset sentence (no claim about the deemed variant or refinance), and kept the PRD's First/Second cascade structure while neutralizing the misleading close-before-compute implication, rather than reordering the cascade prose wholesale.

## Step 9: Complete PRD — 2026-08-12T03:54:00.000Z

## Summary

**Source vs target sizes:**
- PRD_FINALIZED.md: 311 lines / 60,356 chars
- PRD_COMPLETED.md: 311 lines / 65,237 chars
- Char delta: +4,881 chars (line count unchanged; all edits were in-paragraph inserts/revisions)

**Counts:** 11 ambiguity-pins, 2 mismatch-revisions.

**Changes (one bullet each):**

- §2.2 — insert — ambiguity — pinned that `api_request_timestamp` reads from the logical clock (not wall clock) — implementation/response.py:12
- §2.8 lead-in — revise — mismatch — pinned that path resources are loaded as part of priority 2 (before body schema), so a not-found path identifier surfaces the priority-5 error ahead of schema/from-state/posture/temporal/business/fiscal failures — implementation/routes/loans.py:47-53, routes/participants.py:124-128, routes/remittances.py:63-68
- §2.8 priority 2 — revise — mismatch — pinned that the role-vs-`approver_role` check on decide is part of priority 2 (executed before body schema in impl) — implementation/routes/approval_tasks.py:54-57
- §2.8 priority 3 — revise — mismatch — pinned that segregation-of-duties on decide is applied after the from-state/order checks of priority 6 — implementation/routes/approval_tasks.py:60-91
- §2.8 priority 11 — revise — ambiguity — pinned that term exceeding `max_term_months` is rejected with `ERR_INVALID_REQUEST` (400) — implementation/routes/loans.py:84-86
- §2.11 — insert — ambiguity — pinned that AuditEvent records carry `plan_id` and that `detail` defaults to `{}`; that clock-driven deemed distributions record actor as the literal string `system`; that refinance appends two LOAN_REFINANCED events — implementation/services/audit.py:9-22, services/state.py:295-298, routes/loans.py:251-254
- §3.1 — insert — ambiguity — pinned that policy update body keys outside the lever set are ignored and unlisted levers are unchanged — implementation/routes/plans.py:131-137
- §3.2 — revise — ambiguity — pinned the participant PATCH's accepted fields, that `employment_status: ACTIVE` on an ACTIVE participant is a no-op, that any accepted update increments participant version, and that the termination cascade sets `contribution_status` to `TERMINATED` unconditionally (even from `NONE`); pinned "open loan subjects" as REQUESTED/APPROVED/DISBURSED — implementation/routes/participants.py:122-165, services/state.py (in participants.py terminate cascade lines 100-115)
- §3.3 — revise — ambiguity — pinned that replacing deferral_pct on a TERMINATED election is rejected with `ERR_INVALID_STATE`; that every accepted election PUT sets participant's `contribution_status` to `ACTIVE` and increments participant version — implementation/routes/participants.py:197-211
- §3.3 — revise — ambiguity — pinned that restart requires an existing election standing `SUSPENDED`; otherwise `ERR_INVALID_STATE` — implementation/routes/participants.py:246-249
- §3.4 — insert — ambiguity — pinned the four-condition formula for `eligible` on the loan-eligibility read — implementation/routes/participants.py:272-277
- §3.5 — revise — ambiguity — pinned that `accrued_unpaid_interest_cents` is evaluated against the current logical clock at the moment of recomputation, and is recomputed only on remittance posting/reversal (not by clock advance alone) — implementation/services/state.py:238, services/calculations.py:326-327
- §3.5 — revise — ambiguity — pinned that rebuilt installment_numbers resume from the highest ever issued (including superseded), and that when no PENDING rows exist at rebuild, the cadence restarts from `disbursed_on` — implementation/routes/loans.py:286-301
- §3.6 — revise — ambiguity — pinned that explicit allocations additionally reject with `ERR_REMITTANCE_AMOUNT_MISMATCH` when a referenced loan's per-loan total exceeds its candidate balance; pinned that the stored remittance echoes `pay_date` and `allocations` verbatim (allocations null when omitted) — implementation/routes/remittances.py:113-123, 144-145
- §3.6 — revise — mismatch — replaced the prose about "cure may be undone when clock has not passed recomputed deadline" with the impl's actual behavior: while any MISSED remains unpaid the loan is set to DELINQUENT and `cure_deadline_on` is recomputed from the earliest unpaid MISSED due date; when no MISSED remains, DELINQUENT returns to CURRENT and the deadline clears — implementation/routes/remittances.py:230-241
- §3.7 — insert — ambiguity — pinned that "advances past" means strictly greater than the midnight-rendered due date, and that `cure_deadline_on` is recomputed on every clock advance while any MISSED remains (so a newly missed earlier-due installment can pull the deadline earlier) — implementation/services/state.py:251-263
- §3.8 — revise — ambiguity — pinned that the old loan's MISSED installments retain history (only PENDING are CLOSED) and that the new loan is created with initial `version` 1 — implementation/routes/loans.py:217-249
- §3.9 — insert — ambiguity — pinned that document uploads are accepted only while the request stands `UNDER_REVIEW` or `PENDING_DOCUMENTS`, and that the document `amount_cents` is a non-negative integer — implementation/routes/hardship.py:149-156

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1226_retirement_plan_loan_hardship_withdrawal/workspace/PRD_COMPLETED.md`

## Pipeline complete — task_1226_retirement_plan_loan_hardship_withdrawal

All 9 steps done. Final state: 98/98 tests passing across all 8 parallel stability-sweep rounds (verified on disk by the orchestrator); 46/46 route parity with SCAFFOLD.yaml; PRD_COMPLETED.md produced.

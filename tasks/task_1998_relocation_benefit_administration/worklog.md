# Worklog — task_1998_relocation_benefit_administration

## Step 2: Generate Scaffold — 2026-08-15T06:33:38.959Z

Scaffold generation complete for task 1998 (Relocation Benefit Administration). All three files are in `/home/ubuntu/github/CodingPRD/tasks/task_1998_relocation_benefit_administration/`, and `scaffold_lint.py` reports a clean verdict verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Design summary** (generated fresh from the scenario + skill spec; no sibling tasks were inspected):

- **Profile**: workflow-orchestration primary, ledger-reconciliation secondary; flat topology; cyclic state-machine shape; approval-chain role model; immediate consistency; 4 complexity layers (dual-variant calc, cascading side effects, OCC, rate/threshold triggers).
- **Entities: 10** — Employee, RelocationPolicy (tier config incl. which calc variant applies), Vendor, RelocationCase (computed committed/paid/released ledger + cumulative taxable tracker), MoveAssignment (household goods), ServiceBooking (TEMP_HOUSING/TRAVEL), ExpenseClaim (reimbursement vs direct bill + gross-up fields), HomeSaleTransaction (loss-on-sale), RepaymentAgreement, ExceptionRequest.
- **State machines: 8** (+ 3 OCC concurrency rules on RelocationCase.version for claim/estimate/exception approvals). Cycles: re-survey loop (MoveAssignment), resubmit loop (ExpenseClaim), default/cure + settle/reopen (RepaymentAgreement), appeal loop (ExceptionRequest).
- **Calculations: 7** — policy_resolution (selector), case_cost_ledger (aggregation with conservation invariant), tax_gross_up (FLAT vs MARGINAL dual-variant, circular-dependency evaluation order pinned), loss_on_sale_benefit (APPRAISED vs PURCHASE_PRICE dual-variant, nested max/min + cap), repayment_schedule (proration + floor-then-remainder installments), vendor_performance_score (lifetime vs rolling-12m dual-variant), temp_housing_charge (threshold, <= max_nights boundary).
- **Validations: 11** ordered priorities (auth → role → shape → existence → ownership → state → OCC → referential → temporal → constraint → fiscal).
- **Endpoints: 58** (incl. `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default; FK reverse-reachability GETs for all 9 FKs).
- **Errors: 21**. **Roles: 5** (Employee/Vendor entity-backed; MobilityCoordinator/FinanceSpecialist/ProgramManager opaque).
- **§1.8: 20 instances** across all 9 rules (R1: 3 domains — claim gross-up, home-sale loss, vendor score; R2: 3 modes — (a) loss/cap nesting, (b) installment floor+remainder, (c) gross-up circular order; R3–R9: 2 each). **§1.9: 44 instances** (43 active + 1 excluded_because stub) across all nine claim-extraction sections.
- **Verification beyond lint**: zero forbidden concurrency vocabulary; zero unbound `${var}` placeholders; instance names unique across both design files; all formula-derived assert literals executed and pinned (e.g., FLAT gross-up 100000→28205, MARGINAL→33333, repayment owed 45750 with installments 1906×23+1912, mixed-lifecycle paid total 267205).

## Step 3: Copy Shared Files — 2026-08-15T06:34:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1998_relocation_benefit_administration/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-15T07:05:00.000Z

All audits pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1998_relocation_benefit_administration/workspace/PRD.md`.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1998_relocation_benefit_administration/workspace/PRD.md` — **297 lines**. The two withheld design files were never opened or referenced.

**Section list**:
- **§1 Introduction** — 2 paragraphs (business-context angle: mobility spend control, tax/gross-up exposure, clawback)
- **§2 Global Specifications & System-Wide Principles** — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verified **byte-identical** to the canonical `section-2.2-response-structure.md`); 2.3 Pagination; 2.4 Common Resource Properties; 2.5 The Logical Clock; 2.6 The Case Cost Ledger; 2.7 Policy Tiers, Effective Caps, and Exception Increases; 2.8 Monetary Precision, Rounding, and Calendar Arithmetic; 2.9 Optimistic Concurrency Control; 2.10 Validation Order and Nested Resource Resolution
- **§3 Business Logic & Workflows** (8 subsections, timeline-per-component grouping) — 3.1 Enrolling Employees and Defining Policy Tiers; 3.2 Opening the Relocation Case; 3.3 Household Goods: Vendors, Surveys, Estimates, and Payment; 3.4 Temporary Housing and Travel Bookings; 3.5 Expense Claims and the Tax Gross-Up; 3.6 Home Sale Assistance and the Loss-on-Sale Benefit; 3.7 Cap Exceptions and the Appeal Cycle; 3.8 Cancellation, Early Departure, Repayment, and Final Closure
- **§4 Endpoint Definitions** — 4-column table, 58 rows = 58 scaffold endpoints (verified exact match, no extras)
- **§5 Error Code Catalogue** — 2-column table, 21 rows, all HTTP statuses match the scaffold catalog (incl. 422 for `ERR_POLICY_NOT_FOUND`, `ERR_INVALID_DATES`, `ERR_PAYMENT_EXCEEDS_BALANCE`)

**Hard-contract self-audit results**:

```
Field coverage check:
- entities[].fields: 79 required, 79 present, 0 missing
- endpoints[].request_body: 52 required, 52 present, 0 missing
- endpoints[].query_params: 8 required, 8 present, 0 missing
- (path_params: 1/1; common fields id/created_at/updated_at/version: 4/4)
Status: PASS

Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed (ordered 1–11 cascade in §2.10, reinforced locally at each guarded write in §3.3/3.5/3.7), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (§2.9 names all three write endpoints + expected_case_version + ERR_STALE_VERSION/412; no race framing), 0 missing
- state_machines[].transitions: 39 checked, 39 fully expressed (incl. all 6 assignment cascade siblings and their conditional fund release), 0 missing
- calculations[]: 7 checked, 7 fully expressed in precise prose (policy_resolution tiebreak, 3-column case_cost_ledger + conservation invariant, dual-variant tax_gross_up with per-portion half-up rounding, dual-basis loss_on_sale, repayment_schedule floor-then-remainder pinned order, dual-window vendor_performance_score, half-open temp_housing_charge), 0 missing
- validations[] conditions: 11 checked, 11 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 58 checked, 58 expressed (fiscal guard enumerated at exactly its 4 applies_to points), 0 missing
- entities[].fields[] structured content: 79 checked, 79 reconstructible (defaults, derived-field rules, and null-until-event semantics all stated), 0 missing
- sibling-branch symmetry: 7 groups checked (cancel-cascade states, gross-up variants, loss bases, rating windows, booking kinds, claim reject/resubmit, exception decide/appeal), 7 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 405
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: zero fuzzy/approximating words, zero pseudocode operators (`==`, `>=`, `min()`, etc.) in prose; all 21 error IDs, all state/enum values, and all 5 role names appear as exact backticked strings; all three role-identity forms (entity-backed `Employee`/`Vendor`, opaque `MobilityCoordinator`/`FinanceSpecialist`/`ProgramManager`) are translated into §2.1 prose.

## Step 6: Generate Implementation — 2026-08-15T07:22:00.000Z

58 endpoints, matching the scaffold's endpoint table. Implementation is complete.

**File list** at `/home/ubuntu/github/CodingPRD/tasks/task_1998_relocation_benefit_administration/workspace/implementation/`:
- `start.sh` — foreground bash launcher, guards `pip install` on `import flask`, `exec python3 app.py`
- `requirements.txt` — Flask only
- `app.py` — Flask app factory, blueprint registration, error handlers, `0.0.0.0:$PORT` listener
- `db.py` — in-memory store (`DB`), logical clock (default `2026-08-01T00:00:00Z`), ISO8601 helpers
- `errors.py` — `ApiError` class + all 21 error IDs with their exact HTTP statuses from the scaffold
- `middleware.py` — `X-User-ID` / `X-User-Role` header auth, role + ownership enforcement
- `response.py` — `{ meta, response_type, data }` envelope helpers; list responses include `limit`/`offset`/`total_count`/`has_more` in `meta`
- `serializers.py` — 10 entity serializers, all emitting ISO timestamps with 3 fractional digits and exposing nullable fields as `null`
- `util.py` — field validators, pagination (`limit` 1..100 default 10, `offset` default 0), calendar-month arithmetic, ROUND_HALF_UP helpers
- `services/caps.py` — effective cap + held-amount + headroom per component (HHG/TEMP_HOUSING/TRAVEL/MISC; LOSS_ON_SALE not held incrementally)
- `services/ledger.py` — case ledger mutations (`commit`/`release`/`pay`/`pay_direct`), all bump parent case version + `updated_at`
- `services/gross_up.py` — FLAT_SUPPLEMENTAL and MARGINAL_AGGREGATE variants, ROUND_HALF_UP per bracket portion then sum
- `services/repayment.py` — `months_remaining` via whole-months rule, schedule (floor regular installments, last absorbs remainder), arrears threshold
- `services/vendor_perf.py` — lifetime + rolling-12m averages (round half-up 2dp, null when no ratings in scope)
- `routes/employees.py`, `routes/policies.py`, `routes/vendors.py`, `routes/cases.py`, `routes/move_assignments.py`, `routes/service_bookings.py`, `routes/expense_claims.py`, `routes/home_sales.py`, `routes/repayment_agreements.py`, `routes/exception_requests.py`, `routes/clock.py`

**Endpoint count: 58** — matches the scaffold's endpoint table exactly (employees 3, policies 2, vendors 3, cases 8, move-assignments 11, service-bookings 6, expense-claims 8, home-sales 5, repayment-agreements 6, exception-requests 6, clock 1).

**Boot smoke-check results:**
- `bash start.sh` brings the server up on `0.0.0.0:$PORT` in under 2s; responds to HTTP within the 60s window.
- POST `/employees` returns 201 with the standard envelope, logical-clock-derived `created_at = 2026-08-01T00:00:00.000Z`, and `version=0`.
- Missing headers on POST `/employees` returns 401 with `ERR_UNAUTHENTICATED` and the exact error envelope (`meta`, `response_type: "error"`, `data: { error_id, message }`).
- Full happy path exercised: employee → policy → case (auto-resolved policy) → authorize → start → clock-set; case transitions DRAFT → AUTHORIZED → IN_PROGRESS with `version` incrementing and `authorized_at` stamped from the logical clock.
- No entities are seeded at startup — store begins empty on every boot, safe for `--isolation per-test-server`.

## Step 5: Generate Unit Tests — 2026-08-15T07:37:04.000Z

Generation complete. All audits pass. Here is the summary.

**Task 1998 (relocation_benefit_administration)** — full test infrastructure generated from the two design indices only.

### Stage 1: `test_helpers/` (9 files)
- `types.py` — 22 enums + 10 entity TypedDicts (all entities carry `id`/`created_at`/`updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with 45 methods, one per PRD §4 endpoint (incl. `/_clock/set_current_utc`)
- `api_errors.py` — 21 `ApiErrorId`s with PRD §5 HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions, `assert_case_ledger` invariant, `assert_timestamp_equals_instant` (instant-level clock comparison, robust to fractional-digit rendering)
- `factories.py`, `constants.py` (clock default 2026-08-01, repayment amounts 61000/45750/1906/1912)
- `test_users.py` — shared constants for the 3 opaque roles + `make_employee_headers`/`make_vendor_headers` per-instance builders for the two entity-backed roles
- `fixtures.py` — 5 tiers: case-to-IN_PROGRESS, assignment lifecycle walker to any state (REQUESTED→PAID), booking/claim/home-sale/exception helpers, and the Tier-4/5 `setup_repayment_case` (policy → case → paid travel → clock 2027-02-01 → terminate → terminate-early → DRAFT agreement → optional sign at 2027-02-15)
- `__init__.py` — barrel export

### Stage 2: `test_suite/` — 83 tests, 8 files
| File | Tests |
|---|---|
| test_01_case_opening_and_policy_resolution | 11 |
| test_02_case_lifecycle_cascades_and_closure | 12 |
| test_03_move_assignments_vendors_and_ratings | 13 |
| test_04_bookings_housing_and_travel | 11 |
| test_05_expense_claims_gross_up_and_ledger | 10 |
| test_06_home_sale_loss_benefit | 6 |
| test_07_repayment_agreements | 8 |
| test_08_caps_exceptions_and_rejection_rules | 12 |

### Coverage audit (script-verified)
- Queue A: 20/20 difficulty instances, each with exactly ≥2 tests (40 total) — PASS
- Queue B: 43/43 non-stub corner instances, ≥1 test each (43 total) — PASS
- Stub `resubmit_clears_reject_reason` NOT translated; its `difficulty_instance` pointer (`expense_claim_resubmit_cycle`) resolves — OK
- All 83 docstrings carry exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, all resolving to real `name:` entries — PASS
- Verbatim citation audit: 142 quoted spans, every one a literal substring of PRD.md (whitespace-normalized) — PASS
- No `pytest.mark.skip`/`skipif`/`xfail`; no scaffold references in generated code; `pytest --collect-only` collects 83 tests cleanly.

### Instances skipped: none. Adaptations/dropped sub-assertions (PRD-first filter):
1. **`approve_claim_over_cap_without_exception_rejected`, `approved_exception_relaxes_cap`, `state_beats_fiscal_on_claim_approve`** — the literal recipes create a 250000-cent claim against a 200000 MISC cap, but PRD §2.7 fires the guard "at four points: booking creation, claim submission, claim approval, and estimate approval", so such a claim can never exist. Setups re-routed through reachable states that assert the identical rule (approve-time cap breach with headroom consumed by another approved claim; exception approved before claim creation; REJECTED + over-cap coexistence via interleaved approval).
2. **`terminate_early_requires_terminated_employee`** — dropped the recipe's final "repayment-agreements list is empty" assert: PRD §3.8 "When nothing remains, no repayment agreement is created" is ambiguous between "no months remain" (24 remain here) and "nothing owed" (paid 0 → owed 0); the scaffold formula and recipe annotation disagree, so two PRD-only readers diverge.
3. **`create_employee_applies_defaults` / `create_employee_system_fields_input_ignored`** — dropped `version == 1` (PRD §2.4 never pins the initial version value, only the increment); `created_at` asserted as instant equality, not string equality (PRD requires three fractional digits, making the exact rendered string a serializer choice).
4. **`case_service_bookings_subresource_lists_children`** — dropped the positional `data[0]` assertion: both bookings share the same `created_at` logical-clock instant, so ordering within the tie is not uniquely derivable; asserted set membership, `total_count == 2`, and FK isolation instead.

## Step 7: Run Tests and Iterate — 2026-08-15T07:57:02.000Z

All 8 rounds pass 83/83. Clean sweep achieved.

**Summary**

- **Iterations run**: 2 (iteration 1: 78/83 pass in all 8 rounds, 5 deterministic failures, zero flakiness; iteration 2: 83/83 in all 8 rounds after fixes).
- **Tests deleted**: none. Every failing assertion traced to a verbatim PRD sentence, so no deletions were warranted.
- **Fixes applied to `test_suite/`** (no `test_helpers/` changes needed — the instant-comparison helper already existed there):
  - `/home/ubuntu/github/CodingPRD/tasks/task_1998_relocation_benefit_administration/test_suite/test_03_move_assignments_vendors_and_ratings.py` — `test_vendor_survey_two_hour_buffer` and `test_vendor_survey_buffer_applies_before_existing_survey`: replaced raw string equality on `survey_at` (`== "2026-08-10T12:00:00Z"`) with `assert_timestamp_equals_instant(...)` (STEP 1c partial coverage). PRD §3.3 pins only that scheduling "records the proposed instant in `survey_at`"; the three-fractional-digit rendering rule in §2.4 covers only server-stamped `created_at`/`updated_at`/`api_request_timestamp`, so exact string rendering of a caller-supplied instant is not uniquely derivable (implementation renders `.000Z`, a PRD-permitted serializer choice). The instant assertion — the covered part — is kept.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1998_relocation_benefit_administration/test_suite/test_08_caps_exceptions_and_rejection_rules.py` — `test_approve_claim_over_cap_without_exception_rejected`, `test_state_beats_fiscal_on_claim_approve`, `test_state_beats_stale_version_and_fiscal_on_claim_approve`: reordered setup so the 100000-cent claim B is submitted *before* the 150000-cent claim A is approved (STEP 2 test bug). PRD §3.5 verbatim requires a submission-time MISC headroom check ("Submission also checks the claim amount against the case's remaining miscellaneous headroom ... rejects overflow with `ERR_CAP_EXCEEDED`"), so the original order (approve A first, leaving 50000 headroom, then submit B=100000) is unreachable under PRD — the implementation correctly rejected B's submission during setup. The new order matches each test's own stated design and §2.7's holding rule (only APPROVED claims hold MISC funds), making the intended approve-time `ERR_CAP_EXCEEDED` / state-vs-fiscal priority assertions reachable. Assertions themselves were unchanged.
- **Fixes applied to `implementation/`**: none — the implementation was PRD-faithful on every failure (uniform 3-fractional-digit timestamp rendering via `iso_ts` in `db.py`; APPROVED-only MISC holding in `services/caps.py`; submission-time cap check per §3.5).

## Step 8: Finalize PRD — 2026-08-15T08:10:53.000Z

Done. The diff is exactly one inserted paragraph (+2 lines including the blank separator).

**Line counts**: PRD.md = 296, PRD_FINALIZED.md = 298, delta +2 lines (+0.68%).

**Changes** (one edit total):

- **§2.4 — insert —** Added a two-sentence paragraph after the `version` bullet pinning (i) that every timestamp field a resource carries is rendered as ISO 8601 UTC with exactly three fractional digits, covering both logical-clock-stamped fields (`authorized_at`, `termination_date`, `rated_at`, `paid_at`, `signed_at`, `next_due_date`) and client-supplied fields (`expected_move_date`, `survey_at`, `start_date`, `end_date`); and (ii) that client-supplied timestamps are interpreted as instants — trailing `Z` or explicit offset accepted and normalized to UTC, zone-less values read as UTC, the recorded value being the instant denoted. — impl: `implementation/db.py:44-52` (`iso_ts`, sole renderer), `db.py:55-67` (`parse_iso`, sole parser), all 13 timestamp fields across all 9 serializers in `serializers.py`, parse call sites `routes/move_assignments.py:112`, `routes/cases.py:55`, `routes/service_bookings.py:42-43`, `routes/clock.py:20`.

**Step-7 item with no edit**: the `test_08` claim-ordering fix was a pure fixture bug. PRD §3.5 already pins the submission-time MISC headroom check verbatim ("Submission also checks the claim amount against the case's remaining miscellaneous headroom … rejects overflow with `ERR_CAP_EXCEEDED`") and §2.7 lists claim submission among the four guard points; the implementation (`routes/expense_claims.py:70-72`, `services/caps.py:67-70`) is PRD-faithful, as step_7 itself concluded. No PRD silence or mismatch to patch.

**Per-edit pre-edit search log**:

- (a) **Subject**: interpretation and response rendering of resource-carried timestamp values — the exact string rendering of client-supplied instants (step-7 site: `survey_at` in schedule-survey) that §2.4/§3.3 left open.
- (b) **Impl paths enumerated and read/grepped**: `db.py` (`iso_ts`, `parse_iso` — the only formatter and only parser; grep for `strftime|isoformat|datetime(` across all of `implementation/` confirmed no other path); `util.py:69-78` (`parse_datetime_field`); every parse call site (`move_assignments.py:112`, `cases.py:55`, `service_bookings.py:42-43`, `clock.py:20` — the clock's `to_iso8601` is never echoed in a body, so rendering claims don't reach it); every render site (full read of `serializers.py`; `response.py:22-25` `_now_iso` for meta `api_request_timestamp`, same format, already pinned by §2.2); every stamp site for the fields named in the sentence (`employees.py:69`, `cases.py:139`, `move_assignments.py:295`, `expense_claims.py:217`, `repayment_agreements.py:65-66`); the survey-buffer comparison at `move_assignments.py:126-138`, which compares parsed instants and so is consistent with "records the instant denoted."
- (c) **Wording adjustment**: the initial draft named only the four client-supplied fields; it was widened to a universal rendering claim over all resource-carried timestamps because enumeration showed `iso_ts` is applied uniformly to every serialized timestamp — the widened form is true of every enumerated path and yields stronger behavioral equivalence. The claim was deliberately kept at "three fractional digits" granularity (sub-millisecond truncation in `iso_ts` left unpinned, since no exercised path probes it) and scoped to resource fields only, so it says nothing about `api_request_timestamp`'s clock source or the clock endpoint — both outside the step-7 scope.

The output file is at `/home/ubuntu/github/CodingPRD/tasks/task_1998_relocation_benefit_administration/workspace/PRD_FINALIZED.md`.

## Step 9: Complete PRD — 2026-08-15T08:31:32.000Z

Done. All edits are in place — every change is an in-paragraph insert/revision; no new sections, no line-count change.

**Source:** `PRD_FINALIZED.md` (existed; copied to `PRD_COMPLETED.md`)
**Line counts:** 298 → 298 (in-paragraph edits only). **Char delta:** +3,960 (49,995 → 53,955).
**Counts:** 15 ambiguity-pins, 7 mismatch-revisions (22 edited passages total).

### Ambiguity-pins (PRD silent → pinned to impl)
- §2.3 — insert — ambiguity — pinned limit/offset out-of-range or non-integer → `ERR_INVALID_REQUEST` (reject, not clamp); `created_at` ties broken by insertion order; `has_more` = `offset + len(items) < total_count` — `implementation/util.py:81-101`, `implementation/response.py:41`, `implementation/routes/cases.py:106`
- §2.4 — insert — ambiguity — `version` starts at 0 on creation — `implementation/routes/employees.py:40` (and all other creators)
- §2.5 — insert — ambiguity — logical clock advances only when explicitly set (no self-advance), setter accepts earlier instants (backward moves allowed); envelope `api_request_timestamp` is wall-clock transport metadata exempt from the logical clock — `implementation/db.py:37-38`, `implementation/routes/clock.py:24`, `implementation/response.py:22-25`
- §2.8 — insert — ambiguity — calendar-month addition (required service end, first due date, rolling rating window) clamps day-of-month to the target month's last day — `implementation/util.py:114-126`
- §2.10 item 5 — insert — ambiguity — ownership enforced on mutating operations only (reads open to all authenticated roles); on booking cancellation and exception appeal, ownership is evaluated after state checks — `implementation/routes/service_bookings.py:173-179`, `implementation/routes/exception_requests.py:154-160`
- §2.10 (tail) — insert — ambiguity — undefined path or unsupported method → `ERR_NOT_FOUND` (404) — `implementation/app.py:43-49`
- §3.1 — insert — ambiguity — re-terminating an already-`TERMINATED` employee → `ERR_ALREADY_TERMINAL` — `implementation/routes/employees.py:66-67`
- §3.1 — insert — ambiguity — all 17 tier fields required; cap/max-nights/repayment-window fields must be integers, rate fields numbers, with no positivity bound at tier creation — `implementation/routes/policies.py:22-56`
- §3.3 — insert — ambiguity — `service_regions` may be an empty list — `implementation/routes/vendors.py:24-26`
- §3.3 — insert — ambiguity — suspending an already-`SUSPENDED` vendor succeeds idempotently, version still increments — `implementation/routes/vendors.py:70-75`
- §3.3 — insert — ambiguity — vendor aggregate recomputation (on rating or on read) is a derived refresh that never bumps vendor `version`/`updated_at` — `implementation/services/vendor_perf.py:15-41`, `implementation/routes/vendors.py:58`
- §3.4 — insert — ambiguity — missing `end_date` on a housing booking → `ERR_INVALID_REQUEST`, evaluated after case-level checks, not with the initial shape scan — `implementation/routes/service_bookings.py:57-59`
- §3.4 — revise — ambiguity — `nights` pinned as the difference of the two calendar dates with time-of-day ignored (same-calendar-day stay → 0 nights → `ERR_INVALID_DATES`) — `implementation/routes/service_bookings.py:62-64`
- §3.4 — insert — ambiguity — housing overlap is compared on the full start/end instants, not the calendar dates — `implementation/routes/service_bookings.py:77`
- §3.5 — insert — ambiguity — claim line `description` must be a non-empty string; `reject_reason` on claim rejection is required non-empty — `implementation/routes/expense_claims.py:41-44,160-162`
- §3.5 — insert — ambiguity — degenerate gross-up rate ≥ 1 yields a zero gross-up for the affected portion — `implementation/services/gross_up.py:18-20`
- §3.7 — insert — ambiguity — `decision_note` on exception rejection is required non-empty — `implementation/routes/exception_requests.py:133-135`
- §3.8 — insert — ambiguity — payment reversal admitted on `ACTIVE`/`DEFAULTED`/`SETTLED`, rejected with `ERR_INVALID_STATE` on `DRAFT` — `implementation/routes/repayment_agreements.py:111-113`
- §3.8 — insert — ambiguity — `mark-default` attempts failing the due-date/arrears conditions, or targeting a non-`ACTIVE` agreement, → `ERR_INVALID_STATE` — `implementation/routes/repayment_agreements.py:133-140`

### Mismatch-revisions (PRD described different behavior → revised to impl)
- §2.10 item 3 — revise — mismatch — blanket "monetary amounts are positive integers" rescoped to financial-action payloads (estimates, invoices, booking/claim amounts, home-sale values, exception increases, repayment payments), since policy-tier integer fields accept zero/negative; also pinned null-counts-as-missing, ISO-parsing, and integer `expected_case_version` shape rules — `implementation/routes/policies.py:46-56` vs `implementation/util.py:25-38`
- §2.10 item 6 — revise — mismatch — terminal-state blanket qualified: `CLOSED_EARLY` still admits final closure, a `PAID` assignment still admits the one-time rating (rating `CANCELLED` → `ERR_ALREADY_TERMINAL`), a `SETTLED` agreement still admits payment reversal — `implementation/routes/cases.py:267-276`, `implementation/routes/move_assignments.py:288-291`, `implementation/routes/repayment_agreements.py:119-120`
- §2.10 item 8 — revise — mismatch — blanket "case `IN_PROGRESS` for child creation and child actions" replaced with the exact impl enumeration: guard fires on child creation, survey scheduling, estimate approval, booking confirmation, claim approval, exception approval, and home-sale sale recording; all other child actions (incl. claim payment and home-sale settlement on cancelled/early-closed cases) proceed regardless of case status — e.g. `implementation/routes/expense_claims.py:200-224` (no case check in `pay`), `implementation/routes/home_sales.py:128-144` (no case check in `settle`)
- §2.10 item 9 — revise — mismatch — end-date rule split: housing requires end strictly after start; travel permits equality (only preceding start is rejected) — `implementation/routes/service_bookings.py:60-61,86-87`
- §3.2 — revise — mismatch — "child actions generally require the case to remain `IN_PROGRESS`" now points to the §2.10 enumeration instead of the vague "generally" — `implementation/routes/*` case-check audit
- §3.4 — revise — mismatch — the sentence "a supplied end date that does not fall after the start date is rejected" revised to per-kind semantics (travel may equal start) — `implementation/routes/service_bookings.py:86-87`

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1998_relocation_benefit_administration/workspace/PRD_COMPLETED.md`
